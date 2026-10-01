"""M6-6 Fix-γ 修复轮护栏（B-1 / B-2 / F-3 / F-5 / F-6）—— 每条都有**撤修复红证**。

来源 = 独立评审报告 `docs/changes/reviews/m6-r2-traffic.md` 的发现；本文件只测
"修复后的护栏是否真的存在"，红证（撤掉对应修复后本文件哪条转红）见 M6-6 Fix-γ 报告：

| 用例 | 发现 | 撤修复后的红态 |
|---|---|---|
| `test_b1_...` | B-1 未登记 product 打死热重载（静默冻结配置） | 第 1 次热重载抛 KeyError → watcher 死 → 第 2 次改动不生效（断言超时） |
| `test_b2_...` | B-2 401 判死的产品资源不能靠"重新登录"复活 | `status` 停在 `disabled`、复活后的请求仍 503 |
| `test_f3_...` | F-3 captcha 缝 provider 裸异常 → 500 | 响应 500 + `Internal Server Error`（非 503 可读失败） |
| `test_f5_...` | F-5 前提未注入的资源照常进 `/v1/models` | 模型出现在清单里、且无 ⑤ 号横幅 |
| `test_f6_...` | F-6 `_apply` 覆写产品自报的协议族 | `adapter.protocol` 变回 schema 字面量 |

纪律：无网络（假上游 / 端口 9 丢弃位）、不碰 `data/`（conftest 已把 MG_CONFIG 指到 tmp）、
不碰 `127.0.0.1:8300`。
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import types

import pytest
import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from model_gateway.accounts import store

#: 配置里的 Key 故意留着：产品资源出站**绝不用**它（铁律 1）
CONFIG_KEY = "sk-config-key-must-not-be-sent"


# ============ 基建：假 buddy 上游（401 / 200 可切）============

class _FakeBuddyUpstream:
    """假 CodeBuddy 上游：`POST /v2/chat/completions`；`status` 可切成 401。"""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.status = 200
        self.app = Starlette(routes=[
            Route("/v2/chat/completions", self._chat, methods=["POST"])])

    async def _chat(self, request: Request):
        body = await request.json()
        self.requests.append({"path": request.url.path,
                              "headers": dict(request.headers), "body": body})
        if self.status != 200:
            return JSONResponse({"error": {"message": "token rejected"}},
                                status_code=self.status)
        return JSONResponse({
            "id": "chatcmpl-fake-buddy", "object": "chat.completion", "model": body["model"],
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "来自假上游"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        })


@pytest.fixture
async def buddy_upstream():
    fake = _FakeBuddyUpstream()
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(fake.app, host="127.0.0.1", port=0,
                                           log_level="warning"))
    task = asyncio.get_running_loop().create_task(server.serve())
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.01)
    assert server.started, "假上游启动超时"
    fake.port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield fake
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=10)


# ============ 配置工厂 ============

def _resource(rid: str, product: str, account: str, base_url: str, *, name: str = "产品资源",
              protocol: str = "openai") -> dict:
    return {"id": rid, "name": name, "vendor": "", "preset": "", "account": account,
            "product": product, "account_ref": account, "protocol": protocol,
            "base_url": base_url, "api_key": CONFIG_KEY, "enabled": True,
            "access_mode": "api"}


def _model(name: str, rid: str, vendor_model: str) -> dict:
    return {"name": name, "endpoint": "chat",
            "resources": [{"resource": rid, "model": vendor_model}]}


def _buddy_cfg(port: int, *, account: str = "acc-1", model: str = "cb-model",
               vendor_model: str = "hy3", rid: str = "res-cb") -> dict:
    return {"resources": [_resource(rid, "buddy", account, f"http://127.0.0.1:{port}")],
            "models": [_model(model, rid, vendor_model)]}


def _zcode_cfg(port: int, *, account: str = "zc-1", model: str = "zc-model",
               vendor_model: str = "GLM-5.3", rid: str = "res-zc") -> dict:
    return {"resources": [_resource(rid, "zcode", account,
                                    f"http://127.0.0.1:{port}/api/v1/zcode-plan/anthropic",
                                    protocol="anthropic")],
            "models": [_model(model, rid, vendor_model)]}


def _qoder_cfg(port: int, *, account: str = "qd-1", model: str = "qd-model",
               vendor_model: str = "qfmodel", rid: str = "res-qd") -> dict:
    return {"resources": [_resource(rid, "qoder", account, f"http://127.0.0.1:{port}")],
            "models": [_model(model, rid, vendor_model)]}


def _body(model: str = "cb-model") -> dict:
    return {"model": model, "messages": [{"role": "user", "content": "hi"}]}


async def _get_ids(client, gw) -> list[str]:
    r = await client.get(f"{gw.base_url}/v1/models")
    assert r.status_code == 200, r.text
    return [m["id"] for m in r.json()["data"]]


async def _warnings(client, gw) -> dict:
    r = await client.get(f"{gw.base_url}/admin/api/overview")
    assert r.status_code == 200, r.text
    return {w["kind"]: w["message"] for w in r.json()["warnings"]}


async def _wait(predicate, timeout: float = 8.0, interval: float = 0.05) -> bool:
    """轮询到条件成立（热重载 watcher 是 1s 轮询，必须给足时间窗）。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


# ============ B-1：未登记 product 只降级该资源，热重载任务不死 ============

def _rt(cfg: dict, cfg_path, tmp_path):
    """真 `Runtime`（与 `create_app` 同一装配路径；不起服务）。"""
    from model_gateway.config.loader import load_config
    from model_gateway.main import Runtime

    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return Runtime(load_config(cfg_path), cfg_path, usage_dir=tmp_path / "usage",
                   enums_path=tmp_path / "enums.yaml", dialects_path=tmp_path / "dialects.json")


async def test_b1_unknown_product_degrades_and_hot_reload_keeps_working(tmp_path):
    """🔴 B-1：配置里出现**未登记产品** → 该资源降级（无适配器 + 横幅标记）；
    热重载任务**不死** —— 再改一次配置仍然生效。

    原实现：`_apply` 只捕 `NotImplementedError`，未登记产品的 `KeyError` 冒穿 →
    watcher 静默退出 → 此后所有配置改动不再生效（界面/`/health` 毫无提示）。
    红证（撤兜底）：第 ② 步的 `_wait` 超时（watcher 已死）。
    """
    from model_gateway.main import _reload_watcher

    cfg_path = tmp_path / "config.yaml"
    good = _buddy_cfg(9)                       # 端口 9 = 丢弃位（本用例不发请求）
    rt = _rt(good, cfg_path, tmp_path)
    assert "res-cb" in rt.adapters
    assert rt.config_warnings() == [], rt.config_warnings()   # 好配置零告警（对照）

    app = types.SimpleNamespace(state=types.SimpleNamespace(runtime=rt))
    watcher = asyncio.get_running_loop().create_task(_reload_watcher(app))
    try:
        # 🔴 先让 watcher 跑完**第一轮**（记录基线 mtime 后进入 1s sleep）再改文件：
        #    否则新 mtime 会被当成基线，改动永远不会被判为"变了"（用例空过）。
        await asyncio.sleep(0.2)
        assert not watcher.done()

        # ① 写入含**未登记产品**的配置：原实现在这一轮打死 watcher
        bad = copy.deepcopy(good)
        bad["resources"].append(_resource("res-ghost", "ghostproduct", "g-1",
                                          "http://127.0.0.1:9", name="幽灵资源"))
        bad["models"][0]["resources"].append({"resource": "res-ghost", "model": "gm"})
        cfg_path.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
        assert await _wait(lambda: len(rt.config.resources) == 2), "第一次热重载没生效"

        assert "res-ghost" not in rt.adapters, "未登记产品的资源不得有适配器"
        assert "res-cb" in rt.adapters, "坏资源不得牵连好资源（按资源降级）"
        kinds = {w["kind"]: w["message"] for w in rt.config_warnings()}
        assert "resource_adapter_unbuilt" in kinds, kinds          # 用户可见出口（不只写日志）
        assert "幽灵资源" in kinds["resource_adapter_unbuilt"]
        assert "ghostproduct" not in json.dumps(rt.adapters, default=str)

        # ② 再改一次配置（新增一条好资源 + 新模型）→ **仍然生效**（watcher 活着）
        better = copy.deepcopy(bad)
        better["resources"].append(_resource("res-p2", "buddy", "acc-2", "http://127.0.0.1:9",
                                             name="资源二"))
        better["models"].append(_model("m2", "res-p2", "hy3"))
        cfg_path.write_text(yaml.safe_dump(better, allow_unicode=True), encoding="utf-8")
        assert await _wait(lambda: "m2" in {m.name for m in rt.config.models}), \
            "第二次热重载没生效 —— watcher 已死（配置从此静默冻结，B-1 原缺陷）"
        assert "res-p2" in rt.adapters
        assert not watcher.done(), "热重载任务不得退出"
    finally:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
        await rt.aclose()


# ============ B-2：401 判死的产品资源靠"重新登录"复活 ============

async def test_b2_relogin_revives_a_dead_product_resource(buddy_upstream, make_gateway,
                                                          client):
    """🔴 B-2：401 判死（终态）→ 重新登录同一账号（凭据变化）→ 回 active 且可调用。

    红证（撤修复）：`_conn_fingerprint` 不算凭据分量 → reload 后 `status` 停在
    `disabled`（断言即红），复活后的调用仍是 503。
    """
    store.commit_login("buddy", "acc-1", {"access_token": "TOKEN-OLD"}, {})
    gw = await make_gateway(_buddy_cfg(buddy_upstream.port))

    buddy_upstream.status = 401
    r1 = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert r1.status_code == 401, r1.text                       # AUTH 如实透传
    st = gw.runtime.resources.registry[("res-cb", "hy3")]
    assert st.status == "disabled", "401 必须判死（终态）"

    r2 = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert r2.status_code == 503, r2.text                       # 判死后用户看到的症状

    # 用户按提示"重新登录该账号"（凭据变化 = 新的连接身份）→ 下一次配置热重载清零终态
    store.commit_login("buddy", "acc-1", {"access_token": "TOKEN-NEW"}, {})
    ok, errors = await gw.runtime.reload_from_file()
    assert ok, errors
    assert st.status == "active", "重新登录后仍是 disabled —— 用户按提示操作却永远 503（B-2）"

    buddy_upstream.status = 200
    r3 = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert r3.status_code == 200, r3.text
    assert buddy_upstream.requests[-1]["headers"]["authorization"] == "Bearer TOKEN-NEW"
    assert CONFIG_KEY not in json.dumps(buddy_upstream.requests[-1]["headers"])

    await gw.drain_events()
    assert gw.read_events()[-1]["status"] == "success"


# ============ F-3：captcha 缝的异常契约（provider 抛错 → 503 可读，不是 500）============

async def test_f3_captcha_provider_failure_is_classified_not_a_500(make_gateway, client,
                                                                  vendor, monkeypatch):
    """🔴 F-3：provider 抛非 `UpstreamError`（Playwright 超时形态）→ 可读 503 + 事件行。

    原实现：裸异常冒穿调度器的 `UpstreamError/CancelledError` 捕获面 → 500
    `Internal Server Error`（无分类、无事件、无冷却、无提示）。
    红证（撤包装）：响应 500，`验证码` 文案与事件行都不存在。
    """
    from model_gateway.upstream.zcode import out as zcode_out

    calls: list[int] = []

    async def _boom() -> str:
        calls.append(1)
        raise asyncio.TimeoutError("playwright: browser launch timeout")

    monkeypatch.setattr(zcode_out, "CAPTCHA_PROVIDER", _boom)
    gw = await make_gateway(_zcode_cfg(vendor.port))

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body("zc-model"))
    assert resp.status_code != 500, resp.text
    assert resp.status_code == 503, resp.text
    payload = json.dumps(resp.json(), ensure_ascii=False)
    assert "验证码" in payload and "TimeoutError" in payload      # 可读 + 含异常类型
    assert calls, "provider 根本没被调用（用例会空过）"
    assert vendor.requests == [], "验证码失败必须 fail closed（零次上游请求）"

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "failed" and "验证码" in (ev["error_summary"] or ""), ev


# ============ F-5 / F-4：前提未注入的资源不进 /v1/models + 横幅说明 ============

async def test_f5_unwired_premises_are_not_published_and_are_explained(vendor, make_gateway,
                                                                       client):
    """🔴 F-5：qoder（签名未注入）/ zcode（验证码未注入）的模型**不得对外声明**，
    且必须有横幅说明去向；F-4 的 D1 诚实标注并入同一条文案。

    红证（撤修复）：两个模型照常出现在 `/v1/models`，且没有 `model_unservable_premise`。
    """
    cfg = {"resources": [
        _resource("res-qd", "qoder", "qd-1", f"http://127.0.0.1:{vendor.port}"),
        _resource("res-zc", "zcode", "zc-1",
                  f"http://127.0.0.1:{vendor.port}/api/v1/zcode-plan/anthropic",
                  protocol="anthropic"),
    ], "models": [_model("qd-model", "res-qd", "qfmodel"),
                  _model("zc-model", "res-zc", "GLM-5.3")]}
    gw = await make_gateway(cfg)

    ids = await _get_ids(client, gw)
    assert "qd-model" not in ids, "qoder 签名未注入 → 选了必 503，不得下发"
    assert "zc-model" not in ids, "zcode 验证码未注入 → 不得诚实地宣称可用"

    kinds = await _warnings(client, gw)
    assert "model_unservable_premise" in kinds, kinds
    msg = kinds["model_unservable_premise"]
    assert "qoder 签名未注入" in msg and "zcode 验证码未注入" in msg
    assert "zcode 直连前提未验证（D1）" in msg          # F-4 的诚实标注（不宣称可用）
    assert "qd-model" in msg and "zc-model" in msg      # 点名（隐藏必须解释去向）
    assert "model_unservable" not in kinds, "前提缺口与资源不可用（③）必须分开计数"

    # "选了必 503"的现场证据（qoder 侧；zcode 侧要真上游，见 zcode 集成测试）
    store.commit_login("qoder", "qd-1", {"access_token": "TOKEN", "family": "qoder"}, {})
    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body("qd-model"))
    assert resp.status_code == 503, resp.text
    assert "WASM" in resp.text and "SIGNER_FACTORY" in resp.text


async def test_f5_premise_predicate_follows_the_injection(vendor, make_gateway, client,
                                                          monkeypatch):
    """反向护栏：注入验证码 provider（前提就位）→ zcode 模型**回到** `/v1/models`。

    没有这条，"隐藏"可能只是把 zcode 永久拉黑 —— 判据必须跟着注入状态走。
    """
    from model_gateway.upstream.zcode import out as zcode_out

    async def _provider() -> str:
        return "param-fake"

    monkeypatch.setattr(zcode_out, "CAPTCHA_PROVIDER", _provider)
    gw = await make_gateway(_zcode_cfg(vendor.port))

    assert "zc-model" in await _get_ids(client, gw)
    kinds = await _warnings(client, gw)
    assert "model_unservable_premise" not in kinds, kinds


# ============ F-6：`_apply` 不得覆写产品自报的协议族 ============

def test_f6_apply_keeps_the_product_self_reported_protocol(tmp_path):
    """🔴 F-6：`adapter.protocol = r.protocol` 那行死写已删 —— 产品适配器自报的协议族
    不得被 schema 字面量覆写（qoder → `custom`；原先会被写成 `openai`/`anthropic`）。

    红证（加回该行）：`adapter.protocol` 变回 schema 字面量 `"anthropic"`，断言即红。
    """
    cfg_path = tmp_path / "config.yaml"
    rt = _rt(_qoder_cfg(9), cfg_path, tmp_path)          # protocol 故意给 anthropic（错值）
    adapter = rt.adapters["res-qd"]
    assert adapter.protocol == "custom", \
        "产品适配器自报协议族被 schema 字面量覆写（F-6：死写 + 语义污染）"
    assert adapter.product == "qoder"
    asyncio.run(rt.aclose())
