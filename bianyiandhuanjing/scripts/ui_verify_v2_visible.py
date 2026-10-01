#!/usr/bin/env python3
"""v2.0 §21 用户可见出口 · 浏览器实测（headless Chrome CDP）。

验证三件事（§21.2 出口 ①② + Q28 新增 ③④）：
  ① 配置告警横幅：总览页渲染 `.alert-warn`，四类告警**措辞各不相同**
  ② 运营失败红点：`/admin/api/status` 的未读计数（后端半）+ 前端显隐契约（另半）
  ③ `/v1/models` 只下发**可服务**模型，且被隐藏者必有横幅说明（Q28-②）

⚠️ **覆盖边界（不得让"实测"二字夸大范围）**：
  ①③ 走真 HTTP + 真装配函数；②的前端**半**（`dot.hidden` 按计数翻转、点击 POST 确认）
  是在 `verify_v2_frontend.mjs` 里按**源码契约**断言的，**不是**驱动真实浏览器点出来的 ——
  本机沙箱下 Chrome `--dump-dom` 加载真实页面会挂住。红点计数的**后端半**另有
  `test_ops_ack_endpoint_clears_counter` / `test_int_v2_ops_isolation` 走真端点。

用法：.venv/bin/python scripts/ui_verify_v2_visible.py [--mutation]
  --mutation 交给 `verify_v2_frontend.mjs` 跑**变异自证**（每条前端断言都必须能红）
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
# 🔴 fixture 落**每次运行独有**的目录（第十一轮 PM 与 eng-B 各被并行会话污染过一次：
#    共享 `/tmp/mg-v2-visible/overview.json` 时，另一个面板正往同一份文件里写它的
#    变异中间态，本面板的门就假红）。要固定路径就 `MGW_V2_VISIBLE_DIR=…` 显式指定。
OUT = Path(os.environ.get("MGW_V2_VISIBLE_DIR")
           or tempfile.mkdtemp(prefix="mg-v2-visible-"))
OUT.mkdir(parents=True, exist_ok=True)
MUTATE = "--mutation" in sys.argv

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}{('  ' + detail) if detail else ''}")


def main() -> int:
    sys.path.insert(0, str(ROOT / "coding"))
    import asyncio
    import uvicorn
    from model_gateway.main import create_app

    # —— 配置：故意造两类告警 ——
    # 四类告警各造一条（§21 出口① + Q28-②/③ 新增③④）
    cfg = {
        "resources": [
            {"id": "res-a", "name": "资源A", "access_mode": "api", "protocol": "openai",
             "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-a"},
            {"id": "res-b", "name": "孤儿资源", "access_mode": "api", "protocol": "openai",
             "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-b"},
            {"id": "res-c", "name": "停用资源", "enabled": False, "access_mode": "api",
             "protocol": "openai", "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-c"},
            {"id": "res-d", "name": "资源D", "access_mode": "api", "protocol": "openai",
             "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-d"},
        ],
        "models": [
            {"name": "ok-model", "endpoint": "chat",
             "resources": [{"resource": "res-a", "model": "vm-a"}]},
            {"name": "empty-model", "endpoint": "chat", "resources": []},   # 告警 ①
            {"name": "zombie-model", "endpoint": "chat",                    # 告警 ③
             "resources": [{"resource": "res-c", "model": "vm-c"}]},
            {"name": "shadow-model", "endpoint": "chat",                    # 告警 ④
             "params": {"reasoning_effort": "max"},
             "resources": [{"resource": "res-d", "model": "vm-d",
                            "reasoning": {"enabled": True, "effort": "low"}}]},
        ],
    }
    tmp = Path(tempfile.mkdtemp(prefix="mg-v2vis-"))
    cfg_path = tmp / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    app = create_app(config_path=cfg_path, usage_dir=tmp / "usage",
                     enums_path=tmp / "enums.yaml")

    uc = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(uc)

    # 🔴 网关必须跑在**独立线程的事件循环**里 —— 否则主线程发请求时无人驱动循环，请求会挂住
    import threading

    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def _serve() -> None:
        asyncio.set_event_loop(loop)

        async def run() -> None:
            task = loop.create_task(server.serve())
            while not server.started:
                await asyncio.sleep(0.01)
            ready.set()
            await task

        loop.run_until_complete(run())

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    if not ready.wait(20):
        print("网关启动超时")
        return 2
    gw_port = server.servers[0].sockets[0].getsockname()[1]
    gw = f"http://127.0.0.1:{gw_port}"

    # 🔴 让「连续失败」与「处理中」两列取**不同的值**（第十一轮 eng-B B11-4）：
    #    这两列在 fixture 里恒为 0/0 时，把两列的取值对调谁都不知道 —— 判据要能红，
    #    喂给它的数据必须先可判别。走**生产函数**造状态：
    #    `pick_and_acquire` 让 `in_flight` 记在途，`note_failure` 累计连续失败 C。
    _res = app.state.runtime.resources
    _held = _res.pick_and_acquire("ok-model", set())
    if _held is not None:
        for _ in range(3):
            _res.note_failure(_held, "上游 500：连续失败（fixture 造的判别值）")

    # —— 后端出口先验证 ——
    print("\n[后端出口]")
    ov = json.load(urllib.request.urlopen(f"{gw}/admin/api/overview"))
    kinds = {w["kind"] for w in ov.get("warnings", [])}
    want = {"model_without_resource", "resource_without_model",
            "model_unservable", "param_shadowed"}
    check("overview 含四类告警", kinds == want, str(sorted(kinds)))
    msgs = {w["kind"]: w["message"] for w in ov["warnings"]}
    check("四类措辞互不相同", len(set(msgs.values())) == len(msgs), f"{len(msgs)} 条")
    check("① 零映射告警提到 503", "503" in msgs.get("model_without_resource", ""))
    check("③ 不可服务告警指名模型", "zombie-model" in msgs.get("model_unservable", ""))
    check("④ 覆盖告警说清生效序", "请求级" in msgs.get("param_shadowed", "")
          and "reasoning_effort" in msgs.get("param_shadowed", ""))

    # 🔴 Q28-②：/v1/models 只下发可服务模型（隐藏必须与横幅配套）
    published = {m["id"] for m in json.load(
        urllib.request.urlopen(f"{gw}/v1/models"))["data"]}
    check("/v1/models 不含零映射模型", "empty-model" not in published, str(sorted(published)))
    check("/v1/models 不含不可服务模型", "zombie-model" not in published)
    check("/v1/models 保留可服务模型", {"ok-model", "shadow-model"} <= published)
    st = json.load(urllib.request.urlopen(f"{gw}/admin/api/status"))
    check("status 含 ops_failed_unread", "ops_failed_unread" in st, f"= {st.get('ops_failed_unread')}")

    # 🔴 §17 熔断回写的唯一用户可见出口 = 资源状态表的「最近错误」列。
    #    这里用**生产函数** `quota.apply_to_resource`（管理端点 `/admin/api/zcode/bench`
    #    调的就是它）把 res-a 打进熔断，再看接口与界面是否真的把原因透出来。
    from model_gateway.upstream.zcode import quota as zq

    benched = zq.apply_to_resource(app.state.runtime, ["res-a"],
                                   reason="ZCode 风控熔断（30min，全局）")
    check("熔断回写命中 1 条资源", benched == 1, f"benched={benched}")
    ov = json.load(urllib.request.urlopen(f"{gw}/admin/api/overview"))
    res_a = next((r for r in ov.get("resources", []) if r["rid"] == "res-a"), {})
    check("overview 资源项带 last_error",
          "风控熔断" in str(res_a.get("last_error") or ""),
          repr(res_a.get("last_error")))
    check("overview 资源项带冷却剩余", int(res_a.get("cooldown_remaining_ms") or 0) > 0,
          f"{res_a.get('cooldown_remaining_ms')}ms")

    # —— 前端渲染逻辑实测 ——
    # ⚠️ 本机沙箱下 headless Chrome 加载真实页面会挂住（`--dump-dom` + 真实 URL 超时），
    #    故改用 **Node 直接执行 dashboard.js 里的真实渲染函数**（同一份源码，非复制品）。
    print("\n[前端渲染逻辑]")
    ov_path = OUT / "overview.json"
    ov_path.write_text(json.dumps(ov, ensure_ascii=False), encoding="utf-8")
    print(f"  fixture={ov_path}（本轮新写，别拿旧文件当本轮结论）")
    node = "/Users/w/.workbuddy-ai/binaries/node/versions/22.22.2-2/bin/node"
    if not Path(node).exists():
        node = "node"
    cmd = [node, str(ROOT / "bianyiandhuanjing" / "scripts" / "verify_v2_frontend.mjs"), str(ov_path)]
    if MUTATE:
        cmd.append("--mutation")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr.strip()[:400])

    server.should_exit = True
    thread.join(timeout=10)

    print("\n" + "=" * 60)
    failed = [n for n, ok, _ in results if not ok]
    print(f"后端出口实测 {len(results)} 项，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项")
    for n in failed:
        print(f"  ✗ {n}")
    return 0 if (not failed and r.returncode == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
