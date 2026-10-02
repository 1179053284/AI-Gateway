"""`query_balance` 运营操作（tech-design v2.0 §16.6 / §22.6；R1-F6 接线）。

§16.6 边界一句话：**`upstream/` 负责"怎么调上游"，`ops/` 负责"什么时候调、怎么批量、
结果怎么归类"** → 本模块只做薄适配器，**不自己发请求**。

执行通道（**2026-10-02 方案裁决①/⑤ 后只有一条**）

| 环节 | 覆盖 | 为什么 |
|---|---|---|
| 产品 `quota` 钩子（§22.5-6：ops tick **后台**刷新后 `set_quota`，选路只读） | **10/10 全部在册产品** | 取数不再分通道：zcode 的钩子内部委托 `upstream/zcode/billing.py` 联网，其余 9 家本来就是联网钩子。结果同时缓存进账号 `runtime.json` |
| 额度**回写**按产品分派（`_POOL_APPLYERS`） | zcode 专属一张小表，其余走通用三态体 | zcode 的余量是**可量化 token 数**，且 §17 要求"余量 0 → 回写资源状态 + `last_error`"。把这两件事并进通用体 = 给通用体长 `if product == "zcode"`，还会让 9 个产品在未取证的情况下突然开始 bench |

> 旧形状（r3 之前）是"两条通道"：zcode 走 `quota.py` 的**离线日志**通道、其余 9 家走钩子通道。
> 那是"额度一直没有数据"的**真因**——离线通道读的是账号目录里的客户端日志，而 16 个导入号
> **一个 `.log` 都没有**；联网能力又长在私有通道里，通用体拿不到。
> 实测证据与完整推理见 `docs/changes/e2e-records/E2E-20261002-zcode-quota-probe.md`。
> 日志通道**保留**为 `/admin/api/zcode/quota` 与启动种的**离线面**（不删，但它不再是额度的真相来源）。

四类结果的映射（§16.2）：

| 情形 | 类别 | 为什么 |
|---|---|---|
| 额度已取回（available / exhausted） | `success` | 查询本身正常完成；"耗尽"信号以**两处**透出：额度池写 0 + 缓存三态（zcode 另加资源状态与 `last_error`） |
| 未能取到（`unknown`；含 `reason=no_plan/expired/unreachable/circuit/no_credentials/no_identity`） | `inactive` | 🔴 **正常业务态，不是失败** —— 判 `failed` 会让红点每轮常亮，稀释真正需要关注的失败（§21.3 原则 3）；**未知不当零**：缓存按 §4-1 分档写，额度池一个字节都不动 |
| **熔断状态文件读不动**（`reason=circuit-untrusted`） | 🔴 `failed` | 与领取腿**同口径**（`zcode_claim.py:140-149`，第十二轮 PM B-12-4：「红点只数 failed，记 inactive 就等于'拒跑了但没人知道'」）；同一个信号两条腿两种后果 = 规矩 5 禁止的同问题两处口径 |
| 读取 / 落盘过程抛异常 | `failed` | 真出错（权限/磁盘/解析），需要用户看 —— **落盘失败也进这一类**（不谎报成功） |

参与方 = 所有 `Capabilities.balance=True` 的产品（**从注册表推导**；在册 10 个全 ✓，含 zcode）。
"""

from __future__ import annotations

import datetime as dt
import logging

from model_gateway.accounts import registry as account_registry
from model_gateway.accounts import store as accounts_store
from model_gateway.accounts.types import QuotaSnapshot
from model_gateway.ops import runner as ops_runner
from model_gateway.ops.base import OpResult
from model_gateway.ops.builtin import product_hooks

logger = logging.getLogger("model_gateway.ops")

#: 注册 id（与 `ops/builtin/__init__.py` 的 OPERATIONS 键一致）
OPERATION_ID = "query_balance"

#: 该 operation 支持的产品（§16.4 per-operation 声明；**从能力矩阵推导**，不硬编码产品名）
SUPPORTED_PRODUCTS: tuple[str, ...] = tuple(
    pid for pid in account_registry.PRODUCT_IDS
    if account_registry.get(pid).capabilities.balance)

# ── 2026-10-02 方案裁决①/⑤：10 产品同一条取数通道 ────────────────────────────
#
# 过去 zcode 有一条**私有离线通道**（`_query_zcode` → `quota.read_account_snapshot`），
# 理由写在旧注释里：「余量是数值，写共享额度池；其 `quota` 钩子只出三态、不带数量」。
# 这个理由今天仍然成立（通用体的池写入确实只认三态），但**取数**通道的分裂才是病根：
# 联网能力长在私有通道里，通用体拿不到，于是 zcode 的额度永远空。
#
# ⇒ 现在的形状：
#   · **取数**只有一条路 = 产品 `quota` 钩子（zcode 的钩子内部委托 `upstream/zcode/billing`）；
#   · **回写**按产品分派（`_POOL_APPLYERS`）—— zcode 保留 §17 的「余量 0 → 回写资源状态 +
#     `last_error`」义务（`tech-design.md:1266/1274/1419`），**不**并进通用体，
#     免得给通用体长出 `if product == "zcode"`，也免得 9 个产品在未取证的情况下突然开始 bench。
#   见方案 §2 裁决⑤ 与 `tests/unit/test_ops_balance_multi.py::test_zcode_exhausted_writes_status`。
_BALANCE_DIRECT: dict = {}      # 旧取数特例已清空（保留符号名给 wiring 期望表与 CLI 的既有引用面）

#: 🔴 "上游这一轮**没**说话"的档位（方案 §4-1）。这些档 **合并写**：只覆盖状态类字段，
#: 保住上一轮的 `items/plan/remaining/data_at/plan_key`。
#: 方向不能反过来（工程 r7 B-R7-1：9 个产品的失败腿正是 `state=unknown, reason=""`，
#: 反向判据会把它们一起拖进合并写，洗盘语义就变了）；
#: "新加一档忘了登记"的风险由 `tests/unit/test_zcode_billing.py` 的完备性护栏兜住。
#: 表里的每一档都必须由某个钩子**真的产出过**（`tests/unit/test_zcode_billing.py` 逐档跑一遍
#: zcode 钩子分支）—— 防的是「新加一档忘了登记」：那不会红在任何测试里，只会静默洗掉
#: 上一轮的真实数值（工程 r7 B-R7-1 判死的就是"把方向反过来"这种写法）。
SILENT = ("circuit", "circuit-untrusted", "unreachable", "no_credentials", "no_identity")

#: 合并写时要保住的键（其余键一律用本轮快照覆盖）
PRESERVE_KEYS = ("items", "plan", "remaining", "data_at", "plan_key")


def _quota_net_on(runtime) -> bool:
    """`gateway.zcode.quota_net`（默认 **false**，见 `config/schemas.py` 的字段注释）。

    🔴 取不到配置时按 **false** 处理：这是一个"要不要在用户不在场时对外发请求"的开关，
    读不到就默认不发（fail-closed，与铁律 1「本地自用、不外发」的默认契约同向）。
    """
    try:
        return bool(runtime.config.gateway.zcode.quota_net)
    except (AttributeError, TypeError, ValueError):
        return False


def _apply_zcode_quota(product: str, account: str, snap: QuotaSnapshot, runtime) -> int:
    """zcode 的额度回写：数值进**共享池**（按 rid）+ 余量 0 时**回写资源状态与原因**。

    🔴 为什么不并进通用体（方案 §2 裁决⑤ / PM+工程 r5 B-R4-1、B-R4-2）：
    `upstream/zcode/quota.py` 那条 `apply_to_resource(reason=QUOTA_EXHAUSTED_REASON)` 是
    **§17 表格的字面义务**（`tech-design.md:1266/1274/1419`），它的 docstring 原话是
    「只写额度池是不够的 —— 预留闸门虽挡住了派发，但用户在总览看到的是 `active` 且没有任何原因」。
    通道合并时若把它悄悄丢掉，**既有单测照样绿**（它们函数直调那个函数），
    属于最危险的那一类缺陷：「全绿 + 行为变了」。

    触发条件按 **有量化余量这一事实**（`snap.remaining`）而不是 `state == "exhausted"`：
    后者今天就在 qoder 上成立（实盘 `qoder-eff2c221`），并进通用体会让那些产品在
    **未经取证**的情况下突然开始 bench 资源。隔离边界由
    `test_ops_balance_multi.py::test_generic_applier_never_writes_resource_status` 反向钉住。

    实现**委托**给 `quota.apply_remaining_to_runtime`（离线面与联网面共用同一个实现）——
    在这里另抄一份"写池 + 余量 0 则 bench"就会与离线面分叉，那正是
    `quota.py` 老注释警告过的"两条路径算了两种额度"。
    """
    from model_gateway.upstream.zcode import quota as zq

    return zq.apply_remaining_to_runtime(runtime, account, snap.remaining)


#: 额度**回写**的产品分派表（缺省 = 通用三态体）。**只有填了 `remaining` 的产品才进这张表** ——
#: 9 个产品本轮不填 ⇒ 它们的池行为逐字节不变（方案 §8.1-6 的零回归承诺靠这个结构性保证，
#: 而不是靠"记得别改"）。
_POOL_APPLYERS = {"zcode": _apply_zcode_quota}


async def _query_via_hook(product: str, account: str, runtime, *, reasons_out=None) -> OpResult:
    """通用体（F6 接线）：`hook_meta` → 产品 `quota` 钩子 → 三态缓存 + 已物化资源 `set_quota`。"""
    # 凭据解析**在 try 内**（§22.8-6 失败隔离：单账号异常不中断批量）
    try:
        cred = accounts_store.load_credentials(product, account)
        hook_meta = accounts_store.hook_meta(product, account)      # §22.3 补入① 唯一组装入口
        hook = product_hooks.hook_of(product, "quota")
        snap = await hook(cred, hook_meta)
    except Exception as e:  # noqa: BLE001 — 单账号失败隔离，不抛给批量执行器
        return OpResult(account, "failed", f"{type(e).__name__}: {e}",
                        retryable=product_hooks.is_transport_failure(e))

    if not isinstance(snap, QuotaSnapshot):
        return OpResult(account, "failed",
                        f"quota 钩子返回值类型异常：{type(snap).__name__}（不把非快照当额度）")

    reason = getattr(snap, "reason", "") or ""
    if reasons_out is not None:
        reasons_out[account] = reason               # 端点回执按**码**分档计数，不做中文串匹配
    if reason == "circuit-untrusted":
        # 🔴 与领取腿**同口径**记 `failed`（`zcode_claim.py:140-149`，第十二轮 PM B-12-4：
        #    「红点只数 failed，记 inactive 就等于'拒跑了但没人知道'」）。
        #    同一个信号在两条腿上有两种后果 = 规矩 5 禁止的"同问题两处口径"。
        #    detail **不带恢复钟点**（`untrusted` 时 `reason()` 自己也拒给时刻，`quota.py:774-777`）。
        cache_error = _write_quota_cache(product, account, snap)
        why = (f"熔断状态文件读不动 → 本腿按熔断拒跑，且这一轮的「未知」不可信"
               f"：{snap.detail or '无详情'}")
        if cache_error:
            why = f"且运行态缓存写入失败（{cache_error}）；{why}"
        return OpResult(account, "failed", why)

    cache_error = _write_quota_cache(product, account, snap)
    updated = _apply_quota_to_pools(product, account, snap, runtime)
    tail = f"；已刷新 {updated} 个资源额度池" if updated else ""
    if cache_error:
        # 查询到手但**状态没落盘** → 记 failed 且原因可读（§22.8-5 / S-26④：落盘失败必须留痕）
        return OpResult(account, "failed",
                        f"额度已取回但运行态缓存写入失败（{cache_error}）；"
                        f"{snap.state}：{snap.detail or '无详情'}")
    if snap.state == "unknown":
        # 未知不当零（§22.3）：缓存原样落 unknown、额度池不动；类别取 inactive（正常业务态）
        return OpResult(account, "inactive",
                        f"未能取到额度（未知不当零）：{snap.detail or '无详情'}"
                        f"（来源 {snap.source or '未知'}）")
    label = "额度已耗尽" if snap.state == "exhausted" else "额度可用"
    return OpResult(account, "success",
                    f"{label}：{snap.detail or '无详情'}（来源 {snap.source or '未知'}）{tail}")


#: 落盘的 `quota` 键集 = 公共快照字段 + 缓存层自己的 `checked_at`（写盘时刻，不是上游数据时刻）。
#: 🔴 护栏写成**并集**而不是"键集 == 字段"：现盘 6 键 = dataclass 5 字段 + `checked_at`，
#: 按 v3 的字面写法今天即红（三杆 r3 同点：PM B-R3-2 / 工程 B-R7-7 / QA X-R3-6）。
CACHE_ONLY_KEYS = ("checked_at",)


def _quota_cache_keys() -> tuple[str, ...]:
    """`runtime.json.quota` 应有的键集（从 `QuotaSnapshot` 字段**推导**，不手抄第二份清单）。"""
    import dataclasses

    return tuple(f.name for f in dataclasses.fields(QuotaSnapshot)) + CACHE_ONLY_KEYS


def _write_quota_cache(product: str, account: str, snap: QuotaSnapshot) -> str:
    """把快照写进账号 `runtime.json`（§22.2 布局 / §22.5-6「后台刷新落盘快照」）。

    返回错误原因（`""` = 成功）：
    - **读-改-写**：只动 `quota` 一个键，冷却 / 最近错误 / 续期台账等既有顶层键原样保留
      （§22.2 不变式④：运行态与凭据分离，且一个写者不得洗掉别家的键）；
    - 文件**读不动**（`RuntimeUnreadable`）→ 直接报错、**不覆盖**（§22.8-5 fail closed：
      不得把"状态文件坏了"当健康，也不得把用户的运行态洗成一份只有额度的文件）。

    🔴 2026-10-02 的**分档写**（方案 §4-1；工程 r4 B-R4-1 / QA r4 X-R4-5）：
    原本是整键重建 `current["quota"] = {…}` —— 于是"熔断中"或"网络不可达"这种
    **上游这一轮根本没说话**的情况，会把上一轮刚落盘的**真实余量整块洗成空**，
    界面从「1.00M Token · 查于 …」变成「未知 · 查于 刚才」。删掉节奏层并没有消灭这个洞，
    因为洗盘发生在写盘侧。⇒ 现在按 `SILENT` 白名单分档：

    - `reason ∈ SILENT`（`circuit` / `circuit-untrusted` / `unreachable` /
      `no_credentials` / `no_identity`）→ **合并写**：只覆盖状态类字段，
      保住旧 `items/plan/remaining/data_at/plan_key`（`plan_key` 是串号防护的唯一数据源，
      漏它就等于"防护不成立的那一轮把防护主键抹掉"，工程 r7 B-R5-1）；
    - 其余（正常数值 / `no_plan` / `expired`）= **上游明确说了** → 整键覆盖。
      `expired` 走覆盖是有意的：凭据死了，旧数值不再可信。
    """
    try:
        current = accounts_store.read_runtime(product, account)
    except Exception as e:  # noqa: BLE001 — 读不动 = 拒写（fail closed），原因交给用户
        return f"{type(e).__name__}: {e}"
    fresh = {
        "state": snap.state,
        "source": snap.source,
        "detail": snap.detail,
        # 写盘时刻（缓存层字段，**不在** QuotaSnapshot 里；上游数据时刻是 `data_at`）
        "checked_at": dt.datetime.now().isoformat(timespec="seconds"),
        # 套餐识别 + 逐包余量（2026-10-01）· 量化余量/原因码/上游时刻/套餐主键（2026-10-02）
        # 🔴 这些键必须**全部**在这里显式写出：`_write_quota_cache` 是手写字典而不是 `asdict`，
        #    新加字段忘了写这里就静默丢失（QA r3 X-R3-6 的成因）。键集由 `_quota_cache_keys()`
        #    与 `QuotaSnapshot` 字段对账，测试 `test_quota_cache_key_set_matches_fields` 钉住。
        "plan": snap.plan,
        "items": [dict(item) for item in snap.items],
        "remaining": snap.remaining,
        "reason": snap.reason,
        "data_at": snap.data_at,
        "plan_key": snap.plan_key,
    }
    base = current.get("quota") or {}
    if (getattr(snap, "reason", "") or "") in SILENT and base:
        # 保住旧数值面；本轮没给的状态类字段照新值（`state/reason/detail/source/checked_at`）
        merged = dict(fresh)
        for k in PRESERVE_KEYS:
            if k in base:
                merged[k] = base[k]
        current["quota"] = merged
    else:
        current["quota"] = fresh
    try:
        accounts_store.write_runtime(product, account, current)
    except Exception as e:  # noqa: BLE001 — 落盘失败必须留痕（不谎报成功）
        return f"{type(e).__name__}: {e}"
    return ""


def _apply_quota_to_pools(product: str, account: str, snap: QuotaSnapshot, runtime) -> int:
    """把三态写进**该账号已物化资源**的共享额度池（§22.5-6：后台刷新、选路只读）。

    🔴 先走**产品分派表**：`_POOL_APPLYERS` 里有产品的（zcode：数值进池 + 余量 0 回写状态）
    用它，别长在通用体里变成 `if product == "zcode"`（那既违反裁决①，又会把 §17 义务
    误发给 9 个没报告量化余量的产品）。

    三态口径（**未知不当零**，§22.3，通用体）：

    - `available` → `None`（回到"未知/不限"：三态只说"有余量"，没有数量可写，
      不做额度管控；同时把上一轮"耗尽"写下的 0 清掉 —— 否则充值成功后资源会被旧 0
      **永久**挡住）；
    - `exhausted` → `0`（确定耗尽 → 预留闸门拦截），不编造数量；
    - `unknown` → **一个字节都不动**（fail closed：不把未知洗成 0，也不把已知的 0 洗成不限）。
    """
    applier = _POOL_APPLYERS.get(product)
    if applier is not None:
        return applier(product, account, snap, runtime)
    if runtime is None or snap.state == "unknown":
        return 0
    manager = getattr(runtime, "resources", None)
    config = getattr(runtime, "config", None)
    if manager is None or config is None:
        return 0
    remaining = 0 if snap.state == "exhausted" else None
    updated = 0
    for res in getattr(config, "resources", None) or []:
        if str(getattr(res, "product", "") or "") != product:
            continue
        # 物化资源写 product + account_ref（M6-5）；`account` 是旧口径的备注列，作回退
        ref = str(getattr(res, "account_ref", "") or "") or str(getattr(res, "account", "") or "")
        if ref and ref != account:
            continue
        try:
            if manager.set_quota(res.id, remaining):
                updated += 1
        except Exception as e:  # noqa: BLE001 — 单个资源写失败不中断（失败隔离，§22.8-6）
            logger.warning("额度池写入失败（%s/%s → %s）：%s", product, account, res.id, e)
    return updated


async def run_for(product: str, account: str, *, manual: bool = False, runtime=None,
                  via: str = "cron", reasons_out: dict | None = None) -> OpResult:
    """**唯一执行体**：给定 (产品, 账号) 查一次额度（方案 §5-1）。

    🔴 为什么必须有这个函数（工程 r3 B-R2-1）：`run_once` 只把 `(account, manual, runtime)`
    传给 ClaimFn（`ops/runner.py:515`），产品靠 `product_of_account` **反查**得到 ——
    于是管理端点"我在给 ix-quota-net 这个 zcode 号刷额度"这件事**传不进执行体**，
    跨产品同名账号会被认成首个在册产品（既有 BD5）。端点用闭包把 product 绑进来才是真修。

    `via`（`"cron" | "user"`）—— 🔴 **不能挂 `manual`**（工程 r6 B-R6-2）：
    全仓 `run_once(..., manual=True)` **零调用**（7 处 `manual=True` 全在领取腿/验证码夹具），
    `query_balance` 还 `del manual` ⇒ 若把开关写成 `not manual`，
    `quota_net=false` 时**连用户自己点的那颗按钮也会被挡**，界面就变成"刷新了但没刷新"。
    `via` 是本函数自己的 kwarg，**不碰被 `FROZEN_HOOKS` 钉死的钩子签名**：
    端点侧（单账号腿直调、产品级腿在闭包里绑）传 `via="user"`；cron 腿不传 ⇒ 默认 `"cron"`。

    `reasons_out`：端点回执的分档计数器（照 `admin_accounts.py:626-632` 的闭包收集器姿势）。
    写入的是**机器可读 `reason` 码**，不是中文文案 ⇒ 界面三段计数不做字符串匹配。
    """
    del manual                                          # ClaimFn 形参面保留（额度查询无人工验证码路径）
    if product == "zcode" and via != "user" and not _quota_net_on(runtime):
        # 第 8 格：**不发起、不改盘**（连 `checked_at` 都不前进 —— 什么都没做，凭什么说"查过了"）
        if reasons_out is not None:
            reasons_out[account] = QUOTA_NET_OFF        # 哨兵：开关关掉时这一格没有 reason 可用
        return OpResult(account, "inactive",
                        "额度联网腿未启用（gateway.zcode.quota_net=false）→ 本轮未发起、未改写")
    if reasons_out is not None:
        reasons_out.setdefault(account, "")
    direct = _BALANCE_DIRECT.get(product)
    if direct is not None:
        return await direct(account, runtime=runtime)
    return await _query_via_hook(product, account, runtime, reasons_out=reasons_out)


#: `reasons_out` 的哨兵值：`quota_net=false` 时该腿**没有** `reason` 可用（快照都没产出）。
#: 端点把这一档计入回执的"未发起 J"，与 `OpReport.skipped`（停用/锁未参与）**分家**。
QUOTA_NET_OFF = "quota_net_off"


async def query_balance(account: str, *, manual: bool = False, runtime=None,
                        reasons_out: dict | None = None) -> OpResult:
    """查一次该账号的额度/余额（`run_once` 的 `ClaimFn` 约定；`manual` 对本动作无意义）。

    账号归属产品经注册表推导：认不出 → `failed` + 可读原因（不静默、不拿别的产品接口误跑）。
    **cron 腿走的也是 `run_for`**（不留两条真相）；`via` 缺省 `"cron"` ⇒ 受 `quota_net` 开关约束。
    """
    product = ops_runner.product_of_account(account)
    if not product:
        return OpResult(account, "failed",
                        "认不出账号归属的产品（账号目录缺失或不在册），未查询额度")
    return await run_for(product, account, manual=manual, runtime=runtime,
                         reasons_out=reasons_out)

