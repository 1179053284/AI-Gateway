"""`mgw zcode` 子命令（tech-design v2.0 §17 / §19 M5-0）。

账号管理：login（OAuth 设备流登录）/ import（导入缓存）/ list（列表）/ claim（领取）。

login = **官方 CLI 设备授权流**（`12 §④`；协议层 `upstream/zcode/oauth.py` 的
`cli_init`/`cli_poll`）：打印授权地址与设备码 → 浏览器完成授权 → 轮询（pending 非错误）
→ 成功落账号（`accounts.store.commit_login`）+ 写该账号的客户端数据根
（`oauth.write_client_credentials`，与 UI 向导同路径）。退出码：`0` = 成功；`1` = 失败。
`mgw zcode import` 仍保留为导入通道，并在 Q31（2026-10-01）扩展为**三源兼容**：
单文件自动识别面板/小店**粘贴形态**与 **zcode-switch 文件**（转换层
`upstream/zcode/imports.py`）；`--from-panel`/`--from-switch` 整库批量（冲突不中断）。

⚠️ 设备 ID 冲突的交互契约（§15.1 硬约束 3）：**不自动替换**，打印 3 个显式选项，
   **默认取消、退出码非 0** —— 自动换 = 让已登录账号在上游眼里"换设备"，反而触发风控。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import time
from pathlib import Path


def run_zcode(args: argparse.Namespace) -> int:
    cmd = getattr(args, "zcode_command", None)
    if cmd is None:
        print("用法：mgw zcode {list|login|import|claim}（加 --help 看详情）")
        return 0

    if cmd == "list":
        return _list()
    if cmd == "launch":
        return _launch(args)
    if cmd == "login":
        try:
            return asyncio.run(_login(args))
        except KeyboardInterrupt:
            # 🔴 轮询提示里写了"Ctrl+C 可取消"，这里就得**真的接住它**：否则用户按下
            #    中断键只会拿到一段 asyncio 栈（承诺与行为必须一致；取消 = 未成功，退出码 1）。
            print("\n已取消（本次未新增账号）", file=sys.stderr)
            return 1
    if cmd == "import":
        return _import(args)
    if cmd == "claim":
        return asyncio.run(_claim(args))
    if cmd == "remove":
        return _remove(args)
    return 0


def _accounts_root():
    from model_gateway.upstream.zcode import store
    return store.accounts_root()


def _wcwidth(s: str) -> int:
    """粗略显示宽度（CJK 占 2 列）—— 验收发现 `list` 表头右偏。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _wcwidth(s))


def _list() -> int:
    from model_gateway.upstream.zcode import store
    accounts = store.list_accounts()
    if not accounts:
        print("暂无已接入的 ZCode 账号。")
        print("  接入方式：`mgw zcode login`（浏览器授权）或 `mgw zcode import <凭据.json>`")
        return 0

    rows = [(a.name, a.device_id, a.plan or "-", a.status) for a in accounts]
    heads = ("账号", "设备 ID", "套餐", "状态")
    widths = [max(_wcwidth(h), *(_wcwidth(r[i]) for r in rows))
              for i, h in enumerate(heads)]
    print("  ".join(_pad(h, w) for h, w in zip(heads, widths)))
    for r in rows:
        print("  ".join(_pad(c, w) for c, w in zip(r, widths)))
    return 0


def _launch(args: argparse.Namespace) -> int:
    """以该账号的**数据根**启动 ZCode 客户端（v2.0 §15.3 整根隔离）。

    切换账号 = 启动对应那一份数据（**不覆写任何凭据**）。
    与参考项目 `ZCode-Panel` 同路线；进程控制用 macOS `pgrep`/`pkill -x`/`open`。
    """
    from model_gateway.upstream.zcode import dataroot, store

    root = store.accounts_root()
    account = args.account
    if not (root / account).exists():
        print(f"✗ 账号『{account}』不存在（见 `mgw zcode list`）", file=sys.stderr)
        return 2

    exe = args.exe or _detect_zcode_exe()
    if not exe:
        print("✗ 未找到 ZCode 客户端 —— 用 --exe 指定路径", file=sys.stderr)
        return 2

    dataroot.ensure_layout(root, account)
    exe_path, argv, env = dataroot.launch_command(exe, root, account)

    print(f"账号：{account}")
    print(f"客户端：{exe_path}")
    print(f"数据根：{env[dataroot.ENV_DATA_BASE]}")
    print(f"设备码：{argv[0].split('=', 1)[1]}")
    if args.dry_run:
        print("\n[dry-run] 将设置的环境变量：")
        for k, v in env.items():
            print(f"  {k}={v}")
        return 0

    if dataroot.is_zcode_running():
        print("检测到 ZCode 正在运行 → 关闭后重启（整根隔离要求进程用新数据根启动）…")
        if not dataroot.kill_zcode():
            print("✗ 无法关闭 ZCode 客户端", file=sys.stderr)
            return 3

    import os
    import subprocess

    full_env = {**os.environ, **env}
    try:
        subprocess.Popen([exe_path, *argv], env=full_env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError as e:
        print(f"✗ 启动失败：{e}", file=sys.stderr)
        return 3
    print("✓ 已以该账号的数据根启动 ZCode")
    return 0


def _detect_zcode_exe() -> str | None:
    """探测 ZCode 可执行文件（macOS 常见位置）。"""
    from pathlib import Path as _P

    candidates = [
        _P("/Applications/ZCode.app/Contents/MacOS/ZCode"),
        _P.home() / "Applications/ZCode.app/Contents/MacOS/ZCode",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _remove(args: argparse.Namespace) -> int:
    """删除账号的本地数据根（整根隔离下 = 该账号那一套数据 + 设备码）。

    🔴 破坏性操作的呈现纪律（§21.3 原则 2）：**先打印要删什么，再确认**；
    非交互必须显式 `--yes`。原先 `store.delete_account` 无任何出口（验收列为死代码）
    —— 没有它，用户只能手删我们自己定的目录结构，正是整根隔离要避免的事。
    """
    from model_gateway.upstream.zcode import store

    root = store.accounts_root()
    target = root / store._sanitize(args.account)
    if not target.exists():
        print(f"✗ 账号『{args.account}』不存在（见 `mgw zcode list`）", file=sys.stderr)
        return 2

    print(f"将删除账号『{args.account}』的本地数据根：")
    print(f"    {target}")
    print("    （含该账号的凭据与设备码；不影响网关配置里指向它的资源）")

    if not args.yes:
        if not sys.stdin.isatty():
            print("✗ 非交互环境需显式 --yes", file=sys.stderr)
            return 2
        try:
            ans = input("继续？[y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            print("已取消")
            return 0

    if not store.delete_account(args.account):
        print(f"✗ 删除失败：{target}", file=sys.stderr)
        return 3
    print(f"✓ 已删除 {target}")
    return 0


#: 登录轮询的**本地上界**（秒）——与 §22.8-2 的会话 TTL 同源（`accounts/login.py::
#: DEFAULT_SESSION_TTL_S`，10 分钟）：仅在上游未给 `expires_at` 时生效；给了到期时刻
#: 就取较早者（`oauth.DeviceFlow.expired` 不空转）。
LOGIN_MAX_WAIT_S = 600.0


async def _wait(seconds: float) -> None:
    """轮询间隔的等待（**注入缝**：用例替换它即可零时延驱动设备流并断言间隔取值）。"""
    await asyncio.sleep(seconds)


def _default_login_name(root) -> str:
    """默认账号名 `zcode-<hex4>`；与既有账号不重名才采纳（重名会覆盖别人的凭据目录）。"""
    from model_gateway.accounts import store as accounts_store

    for _ in range(20):
        candidate = f"zcode-{secrets.token_hex(2)}"
        if not accounts_store.has_account(root, candidate):
            return candidate
    raise RuntimeError("无法生成不重名的默认账号名（尝试 20 次）")


def _login_device_mid(account: str, root) -> str:
    """本次登录要落盘的**设备码**（§15.1 两条硬约束）：已有账号**原样复用**（绝不重生成 ——
    重登换码在上游眼里就是"换设备"，反而触发风控）；新账号生成跨账号唯一码。

    决策实现与 UI 向导同一处（`upstream/zcode/product.py::_device_mid_for_login`）——
    §22.1「zcode 零重写」：不在此另立一套 §15.1 判定（两份实现必漂移）。
    """
    from model_gateway.upstream.zcode import product as zcode_product

    return zcode_product._device_mid_for_login(account, root)


async def _login(args: argparse.Namespace) -> int:
    """`mgw zcode login` —— 官方 CLI 设备授权流（`12 §④`）。

    init（`oauth.cli_init`）→ 打印授权地址与设备码 → 轮询（`oauth.cli_poll`，pending 打点
    + 剩余时间；间隔取服务端下发值 / `oauth.DEFAULT_POLL_INTERVAL_S`）→ `ready` 即：
    ① `accounts.store.commit_login` 落账号（§22.2 唯一入口，写回自检 + 失败整体回滚）；
    ② `oauth.write_client_credentials` 写该账号的**客户端数据根**（与 UI 向导同路径 ——
       既有领取/额度/`mgw zcode launch` 读的就是它）。

    退出码（§17 / Q28-⑧ 口径不变）：`0` = 登录成功并已落盘；`1` = 失败（发起失败 /
    授权被拒 / 流程过期或等待超时 / 落盘被拒）。
    """
    import httpx

    from model_gateway.accounts import store as accounts_store
    from model_gateway.upstream.zcode import dataroot, oauth, store as zstore

    provider = str(getattr(args, "provider", "") or oauth.PROVIDERS[0])
    root = zstore.accounts_root()
    raw_name = str(getattr(args, "name", "") or "").strip()
    if raw_name and accounts_store.sanitize_name(raw_name) != raw_name:
        print(f"✗ 账号名必须匹配 [A-Za-z0-9_-]{{1,32}}：{raw_name!r}", file=sys.stderr)
        return 1
    try:
        account = raw_name or _default_login_name(root)
        device_mid = _login_device_mid(account, root)      # §15.1：重登复用 / 新号唯一
        flow = await oauth.cli_init(provider)
    except (ValueError, RuntimeError, OSError, httpx.HTTPError) as e:
        print(f"✗ 登录失败：{e}", file=sys.stderr)
        return 1

    print(f"已发起 {provider} 设备授权（账号：{account}）")
    print(f"设备码（device_mid）：{device_mid}")
    print("请在浏览器打开以下地址完成授权：")
    print(f"    {flow.authorize_url}")

    deadline = time.time() + LOGIN_MAX_WAIT_S
    if flow.expires_at:
        deadline = min(deadline, flow.expires_at)          # 服务端作废时刻优先（不空转）
    while True:
        poll = await oauth.cli_poll(flow)
        if poll.state == "ready":
            break
        if poll.state != "pending":
            print(f"✗ 登录失败：{poll.detail}", file=sys.stderr)
            return 1
        remaining = deadline - time.time()
        if remaining <= 0:
            print("✗ 登录失败：等待授权超时（浏览器授权未在有效期内完成）", file=sys.stderr)
            return 1
        print(f"… {poll.detail}（剩余约 {int(remaining)} 秒；Ctrl+C 可取消）")
        await _wait(flow.poll_interval_s)

    # —— ① 落账号（§22.2：落盘只经 `accounts.store`；写回自检 + 失败整体回滚）——
    user = poll.user_info if isinstance(poll.user_info, dict) else {}
    meta: dict = {"device_mid": device_mid, "provider": provider}
    display = str(user.get("name") or user.get("email") or "").strip()
    if display:
        meta["display_name"] = display                     # 展示镜像（同 UI 向导的 meta 组法）
    uid = str(user.get("user_id") or user.get("id") or "").strip()
    if uid:
        meta["user_id"] = uid
    try:
        accounts_store.commit_login("zcode", account, poll.credentials, meta)
    except (accounts_store.CommitError, accounts_store.WriteLockError,
            OSError, ValueError) as e:
        print(f"✗ 登录失败：凭据落盘未完成（{type(e).__name__}: {e}）→ 未新增账号",
              file=sys.stderr)
        return 1

    # —— ② 客户端数据根（整根隔离布局；既有领取/额度/启动路径读它）——
    try:
        dataroot.ensure_layout(root, account)
        client_file = oauth.write_client_credentials(
            dataroot.v2_dir_of(root, account), poll.credentials)
        dataroot.sync_device_mid_to_telemetry(root, account, device_mid)
    except OSError as e:
        print(f"✗ 账号 {account} 已落盘，但客户端数据根写入失败（{e}）→ "
              f"重跑 `mgw zcode login --name {account}` 可补齐（设备码原样复用）", file=sys.stderr)
        return 1
    print(f"✓ 已新增账号 {account}（设备码 {device_mid}）")
    print(f"   凭据：{accounts_store.account_dir(root, account) / 'credentials.json'}")
    print(f"   客户端数据根：{client_file}")
    return 0


def _import(args: argparse.Namespace) -> int:
    """导入账号（单文件自动识别形态 / 整库批量）。Q31（2026-10-01）扩展。

    单文件：文件内容先经 `upstream/zcode/imports.py` 识别 —— 面板/小店**粘贴形态**与
    **zcode-switch 文件**走「转换 → 载荷导入」；其余（`{name, device_mid}` 旧形态等）
    按**原路径**直交 `store.import_account`（既有契约零变化）。
    批量（`--from-panel` / `--from-switch`）：逐条导入，**冲突不中断**（收集后汇总）。

    设备 ID 冲突 → **拒绝 + 交用户决策**（3 个显式选项，默认取消、退出码 4）。
    """
    panel_arg = getattr(args, "from_panel", None)
    switch_arg = getattr(args, "from_switch", None)
    if panel_arg is not None and switch_arg is not None:
        print("✗ --from-panel 与 --from-switch 不能同用", file=sys.stderr)
        return 2
    if panel_arg is not None or switch_arg is not None:
        if args.path:
            print("✗ 批量导入（--from-panel / --from-switch）不接受位置参数",
                  file=sys.stderr)
            return 2
        if getattr(args, "device_mid", None):
            print("✗ --device-mid 仅适用于单文件导入（批量里各账号带各自的设备 ID）",
                  file=sys.stderr)
            return 2
        return _import_bulk(args, source="panel" if panel_arg is not None else "switch",
                            explicit=(panel_arg or switch_arg or None))

    if not args.path:
        print("✗ 缺少凭据文件路径（用法：mgw zcode import <凭据.json>）"
              "；批量导入见 --from-panel / --from-switch", file=sys.stderr)
        return 2

    from model_gateway.upstream.zcode import imports as zim
    from model_gateway.upstream.zcode import store

    p = Path(args.path)
    raw = None
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
    form = zim.detect_payload_form(raw)

    payload = None
    if form in (zim.FORM_PASTE, zim.FORM_SWITCH):
        try:
            template = (zim.find_config_template(store.accounts_root())
                        if form == zim.FORM_PASTE else None)
            payload = zim.payload_for_form(raw, form, template=template)
        except zim.ImportValidationError as e:
            return _import_failed(args, f"{e.message}（{e.code}）")

    if payload is not None:
        res = store.import_account(
            None, reuse=args.reuse, regenerate=args.regenerate, payload=payload,
            fallback_name=p.stem, device_mid=getattr(args, "device_mid", None))
    else:
        res = store.import_account(
            path=args.path, reuse=args.reuse, regenerate=args.regenerate,
            device_mid=getattr(args, "device_mid", None))

    if res.ok:
        if args.json:
            print(json.dumps({"ok": True, "account": res.account,
                              "device_id": res.device_id, "message": res.message,
                              "form": form}, ensure_ascii=False))
        else:
            print(f"✓ 已导入账号 {res.account}（设备 ID {res.device_id}）")
        return 0

    if res.conflict:
        if args.json:
            print(json.dumps({"ok": False, "conflict": True, "account": res.account,
                              "conflict_with": res.conflict_with,
                              "message": res.message, "form": form},
                             ensure_ascii=False), file=sys.stderr)
        # —— 交互契约（§15.1）：打印冲突详情 + 3 个显式选项 ——
        print(f"设备 ID 冲突：账号「{res.account}」的 device_id 已被账号「{res.conflict_with}」占用。",
              file=sys.stderr)
        print("可选：", file=sys.stderr)
        print(f"  ① --reuse {res.conflict_with}    复用该设备 ID（两者共享设备，上游可能风控）",
              file=sys.stderr)
        print("  ② --regenerate     为本账号生成新 ID（上游会视为换设备）", file=sys.stderr)
        print("  ③ 取消（默认）", file=sys.stderr)
        return 4
    return _import_failed(args, res.message)


def _import_failed(args: argparse.Namespace, message: str) -> int:
    if getattr(args, "json", False):
        print(json.dumps({"ok": False, "message": message}, ensure_ascii=False),
              file=sys.stderr)
    print(f"✗ 导入失败：{message}", file=sys.stderr)
    return 1


def _import_bulk(args: argparse.Namespace, *, source: str, explicit: str | None) -> int:
    """整库批量导入（面板账号库 / zcode-switch 账号库）。

    退出码（与单文件契约同族）：
    `1` = 有硬失败（转换/读盘/写盘失败 —— 优先于冲突）；`0` = 无硬失败且**至少一条成功**
    （冲突已逐条明示，可 `--reuse`/`--regenerate` 重跑）；`4` = 无成功、全为设备冲突
    （与单文件同一约定：冲突 = 需用户决策）；`2` = 来源目录缺失/无可导入账号（无动作不报成功）。
    """
    from model_gateway.upstream.zcode import imports as zim
    from model_gateway.upstream.zcode import store

    label = "面板账号库" if source == "panel" else "zcode-switch 账号库"
    root = Path(explicit).expanduser() if explicit else None
    if root is not None and not root.is_dir():
        print(f"✗ 目录不存在：{root}", file=sys.stderr)
        return 2
    effective = root if root is not None else (
        zim.default_panel_root() if source == "panel" else zim.default_switch_root())
    if not effective.is_dir():
        print(f"✗ 未发现{label}（解析到的目录不存在）：{effective}", file=sys.stderr)
        return 2
    entries = (zim.scan_panel_dir(str(root)) if source == "panel"
               else zim.scan_switch_dir(str(root)))
    if not entries:
        print(f"✗ {label}中没有可导入的账号：{effective}", file=sys.stderr)
        return 2

    if not args.json:
        print(f"导入源：{label} {effective}（发现 {len(entries)} 个账号）")
    rows: list[dict] = []
    for entry in entries:
        try:
            payload = (zim.from_panel_account(entry.path) if source == "panel"
                       else zim.from_switch_json(entry.path))
        except zim.ImportValidationError as e:
            rows.append({"name": entry.name, "result": "failed", "reason": e.message})
            continue
        except OSError as e:
            rows.append({"name": entry.name, "result": "failed",
                         "reason": f"{type(e).__name__}: {e}"})
            continue
        res = store.import_account(None, reuse=args.reuse, regenerate=args.regenerate,
                                   payload=payload, fallback_name=entry.name)
        if res.ok:
            rows.append({"name": res.account, "result": "ok",
                         "device_id": res.device_id})
        elif res.conflict:
            rows.append({"name": res.account, "result": "conflict",
                         "reason": res.message, "conflict_with": res.conflict_with})
        else:
            rows.append({"name": entry.name, "result": "failed", "reason": res.message})

    ok_n = sum(1 for r in rows if r["result"] == "ok")
    conflict_n = sum(1 for r in rows if r["result"] == "conflict")
    failed_n = sum(1 for r in rows if r["result"] == "failed")
    summary = {"total": len(rows), "ok": ok_n, "conflict": conflict_n, "failed": failed_n}

    if args.json:
        print(json.dumps({"source": source, "root": str(effective),
                          "results": rows, "summary": summary}, ensure_ascii=False))
    else:
        for r in rows:
            if r["result"] == "ok":
                print(f"✓ {r['name']}：已导入（设备 ID {r['device_id']}）")
            elif r["result"] == "conflict":
                print(f"冲突 {r['name']}：设备 ID 冲突（被『{r['conflict_with']}』占用），"
                      "未导入（可用 --reuse/--regenerate 重跑）")
            else:
                print(f"✗ {r['name']}：{r['reason']}")
        print(f"合计：成功 {ok_n} / 冲突 {conflict_n} / 失败 {failed_n}")

    if failed_n:
        return 1
    if ok_n:
        return 0
    if conflict_n:
        return 4
    return 2


async def _claim(args: argparse.Namespace) -> int:
    """领取 / 签到 —— 输出按类分组，**只有 `✗` 行着色**（§16.2 呈现约定）。

    退出码：`0` = 全部正常；`1` = 有失败；`2` = **无账号参与**（§16.4「N=0 不得报 success」）；
    `3` = **全局风控熔断中，本轮未发起领取**（验收 IX-2：原先这种情形会打"全部正常"+退出码 0，
    把"被风控挡住"说成"一切都好"）。`3` **优先于** `1`：同屏列出的失败属"未发起即失败"。
    同一份说明已进 `mgw zcode claim --help` 的 epilog（面板 S-8：原先只活在源码注释里）。
    """
    from model_gateway.ops import builtin as ops_builtin
    from model_gateway.ops import runner as runner_mod
    from model_gateway.ops.runner import default_usage_dir, run_once, write_report
    from model_gateway.upstream.zcode import quota as zq

    op = ops_builtin.OPERATIONS[ops_builtin.zcode_claim.OPERATION_ID]
    circuit = zq.get_circuit()
    #: 本轮**开局即被熔断挡住**（与"跑着跑着才命中 3012"区分开）
    breakered = circuit.active()
    report = await run_once(operation=op, accounts=args.account or None,
                            manual=args.manual)
    # 🔴 CLI 腿也必须落盘（验收 M-4）：红点与 toast 把用户指到
    #    `data/usage/ops-results-*.jsonl`，而原先只有网关 cron 腿写它 ——
    #    CLI 看到的失败永远不在那个被指路的文件里。
    results_path = write_report(report)
    if results_path is None and report.failed:
        # 🔴 界面上"逐条原因见 ops-results-*.jsonl"这条指路当场作废（验收 S-26④）：
        #    数据目录写不进去时，红点也不会亮 —— 必须把"这次没落盘"说出来，
        #    否则用户以为"没有失败"，而实际有 N 条失败只是没人记得住。
        print(f"⚠ 本轮结果未能写入 {default_usage_dir()}"
              "（数据目录不可写？）→ 顶栏红点不会记录这些失败，"
              "逐条原因只存在于本终端的输出与网关日志里", file=sys.stderr)

    if breakered:
        print(f"⚠ {circuit.reason()} —— 本轮未对上游发起任何领取")
        # 🔴 第十二轮 PM B-12-3：未知档**没有"点"可到**，第二行不能再写"到点自动恢复"
        #    （那与上一行的"读不动 → 按熔断拒跑"自相矛盾，用户会以为等着就行）。
        if circuit.untrusted:
            print(f"    状态文件：{zq.circuit_path()}（**读不动 → 不会自动恢复**；"
                  "只有删除该文件才会放开后续领取，已被冷却的资源仍按各自剩余时间回池）")
        else:
            # 🔴 说清"删除该文件"**只**立即放开运营闸门：已被熔断 bench 下去的资源仍按各自
            #    剩余冷却时间回池（方案未定义"一键解除"表面，不做超出事实的承诺 —— 面板 S1）
            print(f"    状态文件：{zq.circuit_path()}"
                  "（到点自动恢复；删除该文件可立即放开后续领取，"
                  "已冷却的资源按其剩余时间自行回池）")
    elif circuit.active():
        # 🔴 熔断是**本轮里**被建立的（开局没熔、跑着跑着命中 3012）——
        # 上一版只在开局判，于是"把风控打出来了"的这一轮反而一个字都不提（面板 ix-M-1）
        # 🔴 第十二轮 eng-A BLK-B：没落盘成功就不能说"已建立"——
        #    别的进程与重启都看不见这条熔断，闸门下一轮照开。
        if circuit.unpersisted:
            print(f"⚠ 本轮命中风控，但熔断**未能写入状态文件**：{circuit.reason()}")
            print("    只有本进程会停止领取；其它进程与重启后看不到这条熔断，"
                  "下一轮仍可能打向风控中的账号")
        else:
            print(f"⚠ 本轮命中风控，已建立全局熔断：{circuit.reason()}")
            print("    后续 30 分钟内所有 ZCode 账号都会停止领取与转发选中；"
                  f"状态文件 {zq.circuit_path()}")

    # 🔴 空跑情形 ②：**无账号参与** → 明确说明 + 非 0 退出（不得打印"全部正常"）
    if report.no_participants:
        print("无账号参与 —— 尚未接入任何 ZCode 账号。")
        print("  先 `mgw zcode login` 或 `mgw zcode import <凭据.json>` 接入账号。")
        return 2

    if report.success:
        print(f"✓ 已领取 {len(report.success)} 个")
    skipped = list(report.already_done) + list(report.inactive)
    if skipped:
        parts = []
        if report.already_done:
            parts.append(f"已领过 {len(report.already_done)}")
        if report.inactive:
            # 🔴 `inactive` 里混着三种因由（无可领活动 / 今日名额已用完 / 被全局熔断拦住），
            # 一律标成"无资格"是错的归因（面板 ix-M-2）：熔断轮的账号根本没被允许去试，
            # 而"名额用完"是等下一个周期、不是账号没资格。分类措辞按事实给。
            parts.append("被熔断拦住" if breakered else f"无需动作 {len(report.inactive)}")
        print(f"– 跳过 {len(skipped)} 个（{' / '.join(parts)}）")
    if report.skipped:
        print(f"– 跳过 {len(report.skipped)} 个（并发占用 / 已停用）")

    if report.failed:
        # 前缀只打一次（验收发现多失败时前缀重复）
        # 🔴 抬头必须把"未发起（本轮拒跑）"与"发起了但失败"分开（第八轮 ix-8）：
        #    只写「✗ 失败 3 个」会让人以为三次领取都打了上游、只是没成 ——
        #    而拒跑轮一个请求都没发出去，处置动作完全不同（查目录权限 vs 查凭据）。
        refused = sum(1 for _n, r in report.failed
                      if r.startswith(runner_mod.LOCK_REFUSAL_PREFIX))
        head = f"✗ 失败 {len(report.failed)} 个"
        if refused:
            head += f"（其中 {refused} 个**未发起**：互斥锁不可用，本轮拒跑 → 查数据目录权限）"
        print(f"\033[31m{head}：\033[0m")
        for name, reason in report.failed:
            print(f"\033[31m    {name}  {reason}\033[0m")
        # 🔴 **只有真的展示了失败明细才 ack**（验收 M-3）：原先无条件清零会把
        # 网关 cron 轮里用户从未看过的失败一起抹掉（实测未读 7 → 0）。
        _ack_failures()
        if results_path is not None:
            print(f"    逐条明细已落盘：{results_path}")
        # 🔴 熔断优先于失败（面板 S-8）：本轮**根本没对上游发起领取**，同屏的失败
        # 是"未发起即失败"（如缺凭据）。返回 1 会让脚本把"被风控挡住"读成
        # "跑了但有错" —— 正是 §16.2/§21.3 要分开的两类结论。
        return 3 if breakered else 1

    # 本轮无失败：**不动**未读计数（此前 cron/别的入口写的失败用户可能还没看过）
    if not breakered:
        print("全部正常，无需处理")
    if results_path is not None:
        print(f"    本轮结果已落盘：{results_path}")
    return 3 if breakered else 0


def _ack_failures() -> None:
    """清零顶栏红点（用户在 CLI **已看到失败明细**，§21 / M-IX-2）。

    🔴 必须有清零出口 —— 否则一次失败后顶栏红点**永久常亮**。
    未读数以 `data/usage/ops-results-<date>.jsonl` 为准，本调用写"已确认水位"；
    网关未运行（如停机中）时静默跳过（文件已在，下次启动数得出来一样是对的）。
    """
    from model_gateway.core.local_admin import admin_post

    admin_post("/admin/api/ops/ack")
