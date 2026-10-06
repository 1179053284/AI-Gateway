"""S-5 完整版：AdminLanGuard 行为判据（纯 ASGI 直调，无网络）。"""
import asyncio
import json

import pytest
from model_gateway.api.auth import AdminLanGuard
from model_gateway.config.schemas import GatewayConfig


def make_app(captured):
    async def app(scope, receive, send):
        captured.append(scope)
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"ok": true}'})
    return app


def make_guard(gw, captured):
    runtime = type("R", (), {"config": type("C", (), {"gateway": gw})()})()
    return AdminLanGuard(make_app(captured), lambda: runtime)


async def call(guard, path="GET", url="/admin/api/config", query=b"", client=("10.0.0.8", 5555)):
    sent = []

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "method": path, "path": url,
             "query_string": query, "client": client, "headers": []}
    await guard(scope, lambda *a: None, send)
    return sent


@pytest.mark.asyncio
async def test_lan_open_host_blocks_reveal_from_remote():
    captured = []
    g = make_guard(GatewayConfig(host="0.0.0.0"), captured)
    sent = await call(g, query=b"reveal=1")
    assert sent[0]["status"] == 403 and not captured
    body = json.loads(sent[1]["body"])
    assert "lan_admin_open" in body["detail"]


@pytest.mark.asyncio
async def test_lan_open_host_blocks_write_methods_from_remote():
    for method, url in [("PUT", "/admin/api/config"), ("POST", "/admin/api/enums"),
                        ("POST", "/admin/api/resources/test"),
                        ("POST", "/admin/api/system/restart")]:
        captured = []
        g = make_guard(GatewayConfig(host="0.0.0.0"), captured)
        sent = await call(g, path=method, url=url)
        assert sent[0]["status"] == 403, (method, url, sent[0]["status"])
        assert not captured


@pytest.mark.asyncio
async def test_lan_open_host_allows_plain_get_and_loopback():
    captured = []
    g = make_guard(GatewayConfig(host="0.0.0.0"), captured)
    sent = await call(g)                                   # 非回环 + 纯 GET → 放行
    assert sent[0]["status"] == 200 and len(captured) == 1
    sent = await call(g, query=b"reveal=1", client=("127.0.0.1", 5555))  # 回环 + reveal → 放行
    assert sent[0]["status"] == 200


@pytest.mark.asyncio
async def test_loopback_host_never_blocks():
    captured = []
    g = make_guard(GatewayConfig(host="127.0.0.1"), captured)
    sent = await call(g, path="PUT", url="/admin/api/config", query=b"reveal=1")
    assert sent[0]["status"] == 200 and len(captured) == 1


@pytest.mark.asyncio
async def test_escape_hatch_lan_admin_open():
    captured = []
    g = make_guard(GatewayConfig(host="0.0.0.0", lan_admin_open=True), captured)
    sent = await call(g, path="PUT", url="/admin/api/config", query=b"reveal=1")
    assert sent[0]["status"] == 200 and len(captured) == 1


@pytest.mark.asyncio
async def test_guard_never_pierces_when_runtime_missing_or_unreadable():
    """🔴 BD3a 同形判据（2026-10-06 核验轮实测抓到的冒穿）：runtime=None / config
    取值即抛时，守卫必须**降级放行**（下游视图有自己的 fail-closed 兜底），
    绝不许把「配置读不动」升级成全管理面 500。"""
    g1 = AdminLanGuard(make_app([]), lambda: None)          # 没有运行态
    sent = await call(g1, path="PUT", url="/admin/api/config", query=b"reveal=1")
    assert sent[0]["status"] == 200

    class _Unreadable:
        @property
        def config(self):
            raise RuntimeError("配置读不动（测试假体）")

    g2 = AdminLanGuard(make_app([]), lambda: _Unreadable())  # config 取值即抛
    sent = await call(g2, path="PUT", url="/admin/api/config", query=b"reveal=1")
    assert sent[0]["status"] == 200


@pytest.mark.asyncio
async def test_global_concurrency_gate_limits_v1_and_spares_admin():
    """P1 收口（2026-10-06）：`max_concurrent_requests` 执行点——/v1 在途达上限 ⇒
    429 + Retry-After；管理面与 health 不计数；0=不限零变化。"""
    from model_gateway.api.auth import GlobalConcurrencyGate

    def make(gw):
        runtime = type("R", (), {"config": type("C", (), {"gateway": gw})()})()
        captured = []

        async def app(scope, receive, send):
            captured.append(scope)
            await asyncio.sleep(0.05)  # 模拟在途
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": b"{}"})

        return GlobalConcurrencyGate(app, lambda: runtime), captured

    async def call(guard, path="/v1/chat/completions"):
        sent = []

        async def send(msg):
            sent.append(msg)

        await guard({"type": "http", "method": "POST", "path": path,
                     "query_string": b"", "client": ("127.0.0.1", 1), "headers": []},
                    lambda *a: None, send)
        return sent

    # 限额 1：第一条在途期间第二条 429 + Retry-After
    g, captured = make(GatewayConfig(host="127.0.0.1", max_concurrent_requests=1))
    first = asyncio.ensure_future(call(g))
    await asyncio.sleep(0.01)
    second = await call(g)
    await first
    assert second[0]["status"] == 429
    assert dict(second[0]["headers"])[b"retry-after"] == b"1"
    assert len(captured) == 1                        # 被拒者不进下游

    # 0 = 不限：并发多条全放行
    g2, cap2 = make(GatewayConfig(host="127.0.0.1"))
    results = await asyncio.gather(*[call(g2) for _ in range(5)])
    assert all(r[0]["status"] == 200 for r in results) and len(cap2) == 5

    # 管理面不受限
    g3, cap3 = make(GatewayConfig(host="127.0.0.1", max_concurrent_requests=1))
    first3 = asyncio.ensure_future(call(g3, path="/admin/api/config"))
    await asyncio.sleep(0.01)
    second3 = await call(g3, path="/admin/api/config")
    await first3
    assert second3[0]["status"] == 200 and len(cap3) == 2
