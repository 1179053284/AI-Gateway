"""M6 面板修复轮-2 集成测试（A-1 事件循环阻塞 / F1 可服务性 / F2 半应用 / F3 凭据回显）。

对应评审报告（`docs/changes/reviews/m6-panel-eng-a.md` A-1、`m6-panel-eng-b.md` F1/F2/F3）。
每条修复都带**撤修复红证**（同一文件内可复现旧行为），全部本机跑、无真实上游；
真 uvicorn 一律 `127.0.0.1:0`（随机端口），`:8300` 与 `data/` 零触碰。

- **A-1**：`commit_login_async` 把等锁/写盘下放工作线程 —— 锁被他人持有时事件循环
  打点间隔仍 < 50ms（撤修复 = 协程里直接调同步版 → 停摆 ~1.0s）。
- **F1**：空 `base_url` / 适配器构造失败的资源**不进 `/v1/models`** 且出横幅
  （撤掉谓词 `unservable_reason` → 两条模型立刻回到清单）；调用文案不再谎报
  "protocol 未实现"。
- **F2**：`_apply` 前置步骤（坏 `model-enums.yaml`）失败 → 运行态**同代**（config 与
  adapters 都是上一代）+ 出横幅（撤回旧顺序 → 半应用可观测化）。
- **F3**：假上游回显我方 Key → 响应体 / 事件 JSONL / 日志三处零明文（撤脱敏 → 三处红）。
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from model_gateway.accounts import store
from model_gateway.core.errors import UpstreamError, scrub_upstream_text
from model_gateway.main import Runtime
from model_gateway.config.loader import load_config
from model_gateway.stats.events import error_summary

pytestmark = pytest.mark.asyncio


async def _ids(gw) -> list[str]:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{gw.base_url}/v1/models")
    assert r.status_code == 200
    return [m["id"] for m in r.json()["data"]]


async def _warnings(gw) -> dict[str, str]:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{gw.base_url}/admin/api/overview")
    assert r.status_code == 200
    return {w["kind"]: w["message"] for w in r.json()["warnings"]}


def _events_text(gw) -> str:
    day = dt.datetime.now().strftime("%Y%m%d")
    path = Path(gw.usage_dir) / f"events-{day}.jsonl"
    return path.read_text(encoding="utf-8") if path.exists() else ""


# ============ A-1：锁等待不阻塞事件循环 ============

async def _measure(coro) -> tuple[float, float, BaseException | None]:
    """跑 `coro` 并测事件循环心跳：返回 `(耗时秒, 最大打点间隔毫秒, 未捕获异常)`。"""
    gaps: list[float] = []
    stop = asyncio.Event()

    async def _beat() -> None:
        last = time.monotonic()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    beat = asyncio.get_running_loop().create_task(_beat())
    await asyncio.sleep(0.02)   # 先让心跳跑起来：否则阻塞发生在 last 初始化之前，测不到它
    started = time.monotonic()
    exc: BaseException | None = None
    try:
        await coro
    except BaseException as e:  # noqa: BLE001 — WriteLockError 是预期结果（锁被占用）
        exc = e
    elapsed = time.monotonic() - started
    stop.set()
    await beat
    return elapsed, (max(gaps) if gaps else 0.0) * 1000, exc


def _foreign_lock_dir(tmp_path: Path, monkeypatch) -> Path:
    """把锁目录指到 tmp 并伪造"另一个进程持有锁"（pid=1 恒活 → 等满预算后拒写）。"""
    lock_dir = tmp_path / "locks"
    monkeypatch.setenv(store.ACCOUNTS_LOCK_DIR_ENV, str(lock_dir))
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / store.ACCOUNTS_LOCK_NAME).write_text(f"1 {'f' * 16}", encoding="utf-8")
    return lock_dir


async def test_a1_commit_login_async_waits_off_the_event_loop(tmp_path, monkeypatch):
    """🔴 A-1：锁被他人持有时，异步入口**等满锁预算**但事件循环照常打点（< 50ms）。"""
    _foreign_lock_dir(tmp_path, monkeypatch)
    elapsed, max_gap_ms, exc = await _measure(
        store.commit_login_async("buddy", "acct-1", {"token": "t"}, {},
                                 root=tmp_path / "accounts"))
    assert isinstance(exc, store.WriteLockError), f"预期锁被占用而拒写，实际：{exc!r}"
    assert elapsed >= 0.8, (
        f"没等满锁预算（{elapsed:.2f}s）—— 不是「等锁被下放」，是快速失败")
    assert max_gap_ms < 50, (
        f"等锁阻塞了事件循环：最大打点间隔 {max_gap_ms:.0f}ms（阈值 50ms）—— "
        "A-1 未修（等锁回到了事件循环线程）")


async def test_a1_revert_to_direct_sync_call_blocks_the_loop(tmp_path, monkeypatch):
    """🔴 A-1 撤修复红证：把异步入口换回"协程里直接调同步版"（修复前形态）→ 停摆 ~1s。"""
    _foreign_lock_dir(tmp_path, monkeypatch)

    async def _direct(*args, **kwargs):
        return store.commit_login(*args, **kwargs)     # 旧形态：同步等锁落在循环线程

    monkeypatch.setattr(store, "commit_login_async", _direct)
    _elapsed, max_gap_ms, exc = await _measure(
        store.commit_login_async("buddy", "acct-1", {"token": "t"}, {},
                                 root=tmp_path / "accounts"))
    assert isinstance(exc, store.WriteLockError)
    assert max_gap_ms >= 500, (
        f"撤修复后事件循环未被阻塞（{max_gap_ms:.0f}ms）—— 红证不成立："
        "本用例没有真正打到'等锁'路径（阈值 500ms）")


# ============ F1：空 base_url / 适配器构造失败 → 不下发 + 横幅 ============

def _f1_config(vendor_port: int) -> dict:
    return {
        "resources": [
            {"id": "res-good", "name": "好资源", "protocol": "openai",
             "base_url": f"http://127.0.0.1:{vendor_port}/v1", "api_key": "sk-good-key-1234"},
            {"id": "res-nourl", "name": "空址资源", "protocol": "openai",
             "base_url": "", "api_key": "sk-nourl-key-1234"},
            {"id": "res-ghost", "name": "幽灵资源", "protocol": "openai",
             "base_url": "http://127.0.0.1:9/v1", "api_key": "",
             "product": "ghostproduct", "account_ref": "g-1"},
        ],
        "models": [
            {"name": "m-good", "endpoint": "chat",
             "resources": [{"resource": "res-good", "model": "vm-good"}]},
            {"name": "m-nourl", "endpoint": "chat",
             "resources": [{"resource": "res-nourl", "model": "vm-nourl"}]},
            {"name": "m-ghost", "endpoint": "chat",
             "resources": [{"resource": "res-ghost", "model": "vm-ghost"}]},
        ],
    }


async def test_f1_resources_without_adapters_are_hidden_with_banner(make_gateway, vendor):
    """🔴 F1：没有可用出站适配器的资源，其模型**不进清单**且横幅点名；撤谓词 → 回列表。"""
    gw = await make_gateway(_f1_config(vendor.port))
    try:
        assert await _ids(gw) == ["m-good"], "空址/构造失败的模型仍被下发（选了必 503）"

        warns = await _warnings(gw)
        assert "resource_adapter_unbuilt" in warns, warns
        msg = warns["resource_adapter_unbuilt"]
        assert "空址资源" in msg and "幽灵资源" in msg     # 点名资源（成因各写一句）
        assert "m-nourl" in msg and "m-ghost" in msg      # 点名被隐藏的模型（去向）
        assert "model_unservable" not in warns, (
            "装配面缺口被错误归因成「已停用或凭据失效」（用户会去查凭据，"
            "而问题是配置/产品名）")

        # 调用文案不得再谎报"protocol 未实现"（真成因是 base_url 为空 / 构造失败）
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{gw.base_url}/v1/chat/completions",
                             json={"model": "m-nourl",
                                   "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 503, r.text
        assert "无可用出站适配器" in r.text and "protocol 未实现" not in r.text, r.text
        assert "base_url" in r.text, r.text

        # 🔴 撤谓词红证：拿掉装配侧判据 → 两条模型立刻回到 /v1/models（修复前行为）
        gw.runtime.resources.unservable_reason = None
        assert {"m-nourl", "m-ghost"} <= set(await _ids(gw)), \
            "撤掉谓词后模型没有回到清单 —— 谓词没有被 /v1/models 真正使用"
    finally:
        await gw.stop()


# ============ F2：_apply 前置失败 → 不得半应用 ============

def _f2_config(models: tuple[str, ...], resources: tuple[str, ...]) -> dict:
    return {
        "resources": [{"id": rid, "name": rid, "protocol": "openai",
                       "base_url": "http://127.0.0.1:9/v1", "api_key": f"sk-{rid}-1234"}
                      for rid in resources],
        "models": [{"name": name, "endpoint": "chat",
                    "resources": [{"resource": resources[0], "model": f"vm-{name}"}]}
                   for name in models],
    }


def _f2_runtime(tmp_path: Path) -> tuple[Runtime, Path]:
    """建一个真 `Runtime`（配置文件 + 枚举池 + 方言表全在 tmp）。"""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(_f2_config(("m-old",), ("res-a",)),
                                       allow_unicode=True), encoding="utf-8")
    rt = Runtime(load_config(cfg_path), cfg_path,
                 usage_dir=tmp_path / "usage",
                 enums_path=tmp_path / "model-enums.yaml",
                 dialects_path=tmp_path / "dialects.json")
    return rt, cfg_path


async def test_f2_front_step_failure_keeps_the_previous_generation(tmp_path):
    """🔴 F2：坏 `model-enums.yaml`（用户可扩展文件）→ 不半应用 + 横幅 + 修好即自愈。"""
    rt, cfg_path = _f2_runtime(tmp_path)
    try:
        assert [m.name for m in rt.config.models] == ["m-old"]
        assert set(rt.adapters) == {"res-a"}

        # 新一代配置（新增模型 + 资源）写盘，同时把枚举池文件改坏
        cfg_path.write_text(yaml.safe_dump(_f2_config(("m-old", "m-new"),
                                                      ("res-a", "res-b")),
                                           allow_unicode=True), encoding="utf-8")
        (tmp_path / "model-enums.yaml").write_text("entries: [ : 坏 YAML", encoding="utf-8")

        ok, errors = await rt.reload_from_file()
        assert ok is False and errors, "坏枚举池没有让本轮热重载失败"
        assert [m.name for m in rt.config.models] == ["m-old"], "config 被换成了新一代（半应用）"
        assert set(rt.adapters) == {"res-a"}, "adapters 与 config 不同代（半应用）"
        assert rt.key_values.get("res-b") is None, "key_values 被换成了新一代（半应用）"

        kinds = {w["kind"]: w["message"] for w in rt.config_warnings()}
        assert "hot_reload_failed" in kinds, f"热重载失败没有横幅出口：{kinds}"
        assert "ParserError" in kinds["hot_reload_failed"], kinds["hot_reload_failed"]

        # 自愈：修好枚举池 → 再重载 → 新配置生效，横幅消失
        (tmp_path / "model-enums.yaml").unlink()
        ok, errors = await rt.reload_from_file()
        assert ok, errors
        assert [m.name for m in rt.config.models] == ["m-old", "m-new"]
        assert "hot_reload_failed" not in {w["kind"] for w in rt.config_warnings()}
    finally:
        await rt.aclose()


async def test_f2_revert_to_the_legacy_apply_order_is_half_applied(tmp_path, monkeypatch):
    """🔴 F2 撤修复红证：旧顺序（config/registry 先落地、枚举池后读）→ 半应用可观测。"""
    rt, cfg_path = _f2_runtime(tmp_path)
    try:
        from model_gateway.core.errors import ErrorClassifier
        from model_gateway.enums.matcher import load_enum_pool

        cfg_path.write_text(yaml.safe_dump(_f2_config(("m-old", "m-new"),
                                                      ("res-a", "res-b")),
                                           allow_unicode=True), encoding="utf-8")
        new_cfg = load_config(cfg_path)
        (tmp_path / "model-enums.yaml").write_text("entries: [ : 坏 YAML", encoding="utf-8")

        def _legacy_apply(self, config):                      # 逐行复刻修复前的顺序
            self.config = config
            self.resources.rebuild(config)
            self.classifier = ErrorClassifier(config.error_rules)
            self.enum_pool = load_enum_pool(self.enums_path)  # ← 在这里抛

        monkeypatch.setattr(Runtime, "_apply", _legacy_apply)
        ok, errors = await rt.reload_from_file()
        assert ok is False and errors
        assert [m.name for m in rt.config.models] == ["m-old", "m-new"], "旧顺序应当半应用"
        assert set(rt.adapters) == {"res-a"}, "adapters 仍是旧代 = 半应用的可观测化"
    finally:
        await rt.aclose()


# ============ F3：上游回显凭据 → 三出口统一脱敏 ============

class _EchoVendor:
    """假上游：把收到的 `Authorization` 原样回显进 401 错误体（含**裸值**一份）。"""

    def __init__(self) -> None:
        self.seen_auth = ""
        self.calls = 0

    async def chat(self, request: Request) -> JSONResponse:
        await request.json()
        auth = request.headers.get("authorization", "")
        raw = auth.split(" ", 1)[1] if " " in auth else auth
        self.seen_auth = auth
        self.calls += 1
        return JSONResponse(status_code=401, content={"error": {
            "message": f"token rejected; got Authorization: {auth}",
            "type": "auth_error",
            "code": 401,
            "received_key": raw,     # 裸回显（无 Bearer / 无 sk- 形态）→ 靠字面值登记遮
        }})


async def _start_echo_vendor(echo: _EchoVendor) -> tuple[uvicorn.Server, asyncio.Task, str]:
    app = Starlette(routes=[Route("/v1/chat/completions", echo.chat, methods=["POST"])])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0,
                                           log_level="warning"))
    task = asyncio.get_running_loop().create_task(server.serve())
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.01)
    assert server.started, "假上游启动超时"
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, task, f"http://127.0.0.1:{port}"


async def test_f3_echoed_credential_is_scrubbed_from_response_events_and_logs(
        make_gateway, caplog):
    """🔴 F3（红线）：上游回显我方 Key → 响应体 / 事件 JSONL / 日志**零明文**。"""
    secret = "SECRET-F3-KEY-9a11c7d3"        # 无 sk- 形态：必须靠"字面值登记"遮住
    echo = _EchoVendor()
    server, server_task, base = await _start_echo_vendor(echo)
    logger = logging.getLogger("model_gateway.f3_probe")
    try:
        gw = await make_gateway({
            "resources": [{"id": "res-f3", "name": "回显资源", "protocol": "openai",
                           "base_url": f"{base}/v1", "api_key": secret}],
            "models": [{"name": "m-f3", "endpoint": "chat",
                        "resources": [{"resource": "res-f3", "model": "vm-f3"}]}],
        })
        try:
            with caplog.at_level(logging.WARNING):
                async with httpx.AsyncClient(timeout=15) as c:
                    resp = await c.post(f"{gw.base_url}/v1/chat/completions",
                                        json={"model": "m-f3",
                                              "messages": [{"role": "user", "content": "hi"}]})
                # 日志出口的代表形态：把网关的错误摘要打出去（`api/admin.py` 同款消费）
                exc = UpstreamError(
                    "upstream 401", status_code=401,
                    error_body=json.dumps({"error": {
                        "message": f"token rejected; got Authorization: Bearer {secret}",
                        "type": "auth_error", "code": 401}}, ensure_ascii=False))
                logger.warning("请求失败：%s", error_summary(exc))
            await gw.drain_events()
            events_text = _events_text(gw)

            # —— 前提（真回显）——
            assert secret in echo.seen_auth, f"假上游没收到我方 Key：{echo.seen_auth!r}"
            assert resp.status_code >= 400 and "token rejected" in resp.text, resp.text
            masked = scrub_upstream_text(secret)
            assert masked and masked != secret, "字面值登记没生效（Key 没被遮罩）"

            # —— 三出口零明文 + 遮罩确实在场（证明链路真被打到）——
            assert secret not in resp.text, f"响应体回显了明文凭据：{resp.text[:200]}"
            assert masked in resp.text, resp.text
            assert secret not in events_text, "事件 JSONL 回显了明文凭据"
            assert masked in events_text, events_text[:300]
            assert secret not in caplog.text, "日志回显了明文凭据"

            # —— 撤脱敏红证（判据本体）：上游原文里明文在，scrub 后不在 ——
            raw = json.dumps({"error": {"message": f"got Authorization: Bearer {secret}",
                                        "received_key": secret}})
            assert secret in raw, "前提不成立：上游原文没带明文"
            assert secret not in (scrub_upstream_text(raw) or ""), "撤掉脱敏即本行红"
        finally:
            await gw.stop()
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, timeout=10)
