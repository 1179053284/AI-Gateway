"""`cline` 产品钩子单测（tech-design v2.0 §22.4 行；`20 §1.2/§3.1`、`21 §1.1`）。

🔴 假上游（`httpx.MockTransport`）：**无网络、无真实凭据**。逐条对应取证判据：

- 设备码登录：`authorization_pending` **不是错误**（判据 = 响应体 `error` 字段，
  **不是** HTTP 状态码 —— 用例故意用 404 承载它，与 Qoder 分支的判据形态区分开，
  `cline-oauth.ts:40-44`、`jet-hub-rpc.ts:1022-1026`）→ 之后转 `success` 并落凭据本体；
- 余额：三态 + `account_id`（不是 JWT 的 `sub`）+ 两种失败形态（HTTP 200 业务失败 /
  HTTP 401 只有 `error`）；
- 模型目录：两端点合并**顺序**（免费集合 → 兜底表 → 推荐/订阅 → 远端大列表）与
  「兜底表排在远端大列表之前」；
- `claim` 不可用语义（能力位 `checkin=False`；入口层按 `Capabilities` 不渲染）。

⚠️ 判据里出现的模型 id / 数值都是**假上游数据**（与真上游无关），只有**契约**（顺序、状态、
前缀、字段名）照 DSH 取证。
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from model_gateway.accounts import store
from model_gateway.accounts.login import LoginEngine
from model_gateway.accounts.types import NotRefreshable
from model_gateway.upstream.cline import constants as C
from model_gateway.upstream.cline import product as cline

# ============ 假上游 ============


class FakeUpstream:
    """按路径分发的假上游（`httpx.MockTransport` handler 的薄封装）。

    - 路由值 = `httpx.Response`（可复用）｜`list[Response]`（按调用次序消费，最后一个复用）
      ｜`Exception` 实例（抛出，模拟传输层失败）；
    - `calls` 记录全部请求（断言请求体 / 请求头 / 调用次序）；未登记的路径 → 404。
    """

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = dict(routes)
        self.calls: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        route = self.routes.get(request.url.path)
        if route is None:
            return httpx.Response(404, json={"error": "no route", "path": request.url.path})
        if isinstance(route, list):
            route = route.pop(0) if len(route) > 1 else route[0]
        if isinstance(route, Exception):
            raise route
        assert isinstance(route, httpx.Response)
        return route

    def paths(self) -> list[str]:
        return [str(request.url.path) for request in self.calls]

    def requests_for(self, path: str) -> list[httpx.Request]:
        return [request for request in self.calls if request.url.path == path]

    def body_of(self, path: str) -> str:
        return self.requests_for(path)[0].content.decode()

    def json_of(self, path: str) -> dict:
        return json.loads(self.body_of(path))

    def auth_of(self, path: str) -> str:
        return self.requests_for(path)[0].headers.get("Authorization", "")


def _patch_client(monkeypatch, upstream: FakeUpstream) -> None:
    """把产品层的 `make_client` 换成本用例的假上游（产品钩子只经它建客户端）。"""

    def factory(*, base_url="", headers=None, timeout=None, follow_redirects=True):
        return httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler),
                                 base_url=base_url, headers=headers or {})

    monkeypatch.setattr(cline, "make_client", factory)


def _device_routes(authenticate: object) -> dict[str, object]:
    return {
        C.DEVICE_AUTHORIZATION_PATH: httpx.Response(200, json={
            "device_code": "DEV-SECRET", "user_code": "ABCD-1234",
            "verification_uri": "https://cline.bot/device",
            "verification_uri_complete": "https://cline.bot/device?code=ABCD-1234",
            "expires_in": 300, "interval": 5,
        }),
        C.DEVICE_AUTHENTICATE_PATH: authenticate,
    }


def _session(**state) -> SimpleNamespace:
    """会话替身：钩子只许经 `session.state` 存私态（私钥不进 Challenge/Outcome）。"""
    return SimpleNamespace(state=dict(state), product="cline")


# ============ 登录：设备码 pending → success ============


async def test_device_login_pending_then_success(monkeypatch):
    """🔴 `authorization_pending`（**HTTP 404 承载**）→ `pending`（不是错误）→ 成功落凭据。"""
    upstream = FakeUpstream(_device_routes([
        # 判据形态：Qoder 用「404 = 未授权」，Cline 用响应体 error —— 这里故意用 404 承载 pending
        httpx.Response(404, json={"error": "authorization_pending"}),
        httpx.Response(200, json={"access_token": "workos:eyJw", "refresh_token": "r-1",
                                  "token_type": "Bearer"}),
    ]))
    upstream.routes[C.REGISTER_PATH] = httpx.Response(200, json={
        "success": True,
        "data": {"accessToken": "workos:eyJcline", "refreshToken": "r-2",
                 "expiresAt": "2026-09-29T05:23:47.000Z", "tokenType": "Bearer",
                 "userInfo": {"clineUserId": "usr-01ABC", "email": "dev@example.test",
                              "firstName": "", "lastName": ""}},
    })
    _patch_client(monkeypatch, upstream)
    session = _session()

    # —— start：设备码申请 ——
    challenge = await cline.login_start(session)
    assert challenge.url == "https://cline.bot/device?code=ABCD-1234"   # 优先 verification_uri_complete
    assert challenge.device_code == "ABCD-1234"                        # 给用户看的码（展示 + 复制）
    # 🔴 轮询私钥绝不进 Challenge（§22.3：Challenge 只承载用户可见物）
    assert "DEV-SECRET" not in json.dumps(vars(challenge))
    assert session.state["device_code"] == "DEV-SECRET"
    assert session.state["interval_ms"] == 5_000
    assert session.state["expires_at"] > time.monotonic()
    # 设备码申请是 x-www-form-urlencoded 表单体（不是 JSON）
    start_body = upstream.body_of(C.DEVICE_AUTHORIZATION_PATH)
    assert f"client_id={C.WORKOS_CLIENT_ID}" in start_body

    # —— poll #1：pending 不是错误 ——
    first = await cline.login_poll(session)
    assert first.state == "pending" and "等待用户" in first.detail
    assert first.credentials == {} and first.meta == {}
    poll_body = upstream.body_of(C.DEVICE_AUTHENTICATE_PATH)
    assert "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Adevice_code" in poll_body
    assert "device_code=DEV-SECRET" in poll_body

    # —— poll #2：成功 ——
    second = await cline.login_poll(session)
    assert second.state == "success"
    credential = second.credentials
    assert credential["access_token"] == "workos:eyJcline"    # 🔴 前缀保留（剥掉即 401）
    assert credential["refresh_token"] == "r-2"
    assert credential["expire_time"] == int(
        dt.datetime.fromisoformat("2026-09-29T05:23:47+00:00").timestamp() * 1000)
    assert credential["account_id"] == "usr-01ABC"
    assert credential["email"] == "dev@example.test"
    assert credential["nickname"] == "dev@example.test"       # 昵称优先邮箱
    assert second.meta["account_id"] == "usr-01ABC"
    # 注册请求体字段是**驼峰**（`cline-oauth.ts:309-338`）
    assert upstream.json_of(C.REGISTER_PATH) == {"accessToken": "workos:eyJw", "refreshToken": "r-1"}


async def test_slow_down_stays_pending_and_backs_off_cumulatively(monkeypatch):
    """`slow_down` 不是失败：间隔**累积** +1s（源码 `intervalSeconds += 1`）。"""
    upstream = FakeUpstream(_device_routes([
        httpx.Response(400, json={"error": "slow_down"}),
        httpx.Response(400, json={"error": "slow_down"}),
    ]))
    _patch_client(monkeypatch, upstream)
    session = _session()
    await cline.login_start(session)
    assert session.state["interval_ms"] == 5_000

    first = await cline.login_poll(session)
    second = await cline.login_poll(session)
    assert first.state == second.state == "pending"
    assert session.state["interval_ms"] == 7_000       # 累积：5000 → 6000 → 7000


@pytest.mark.parametrize("error,status,expect_state", [
    ("access_denied", 400, "failed"),
    ("invalid_grant", 400, "failed"),
    ("expired_token", 400, "expired"),        # 设备码过期：语义精确的 expired，不泛化成 failed
])
async def test_terminal_device_errors(monkeypatch, error, status, expect_state):
    """终态错误码逐条映射（`cline-oauth.ts:279-291`）。"""
    upstream = FakeUpstream({
        C.DEVICE_AUTHENTICATE_PATH: httpx.Response(status, json={"error": error}),
    })
    _patch_client(monkeypatch, upstream)
    outcome = await cline.login_poll(_session(device_code="D", expires_at=0.0))
    assert outcome.state == expect_state and error in outcome.detail


@pytest.mark.parametrize("response,expect", [
    (httpx.Response(500, json={"error_description": "boom"}), "failed"),   # 未知错误 → failed（HTTP 500 在文案里）
    (httpx.Response(200, json={"access_token": "workos:x"}), "failed"),    # 2xx 却缺 refresh_token（不当 pending）
])
async def test_unexpected_poll_response_never_hangs_as_pending(monkeypatch, response, expect):
    """服务端异常不得被当成「等用户」（否则轮询死循环，`cline-oauth.ts:259-262`）。"""
    upstream = FakeUpstream({C.DEVICE_AUTHENTICATE_PATH: response})
    _patch_client(monkeypatch, upstream)
    outcome = await cline.login_poll(_session(device_code="D", expires_at=0.0))
    assert outcome.state == expect
    assert outcome.state != "pending"


async def test_poll_without_device_code_or_after_expiry(monkeypatch):
    """缺私态 / 设备码超时 → 显式失败/过期，**不打上游**。"""
    upstream = FakeUpstream({})
    _patch_client(monkeypatch, upstream)
    missing = await cline.login_poll(_session())
    expired = await cline.login_poll(_session(device_code="D", expires_at=time.monotonic() - 1))
    assert missing.state == "failed" and "设备码" in missing.detail
    assert expired.state == "expired"
    assert upstream.calls == []


async def test_login_start_surfaces_authorization_failure(monkeypatch):
    """设备码申请失败 → 抛异常（引擎不吞异常，入口层可见；不编造 Challenge）。"""
    upstream = FakeUpstream({
        C.DEVICE_AUTHORIZATION_PATH: httpx.Response(
            400, json={"error": "invalid_client", "error_description": "bad client"}),
    })
    _patch_client(monkeypatch, upstream)
    with pytest.raises(RuntimeError, match="设备码授权失败（HTTP 400）"):
        await cline.login_start(_session())


async def test_engine_end_to_end_commits_credential(tmp_path, monkeypatch):
    """经 `accounts/login.py` 会话引擎跑真链路：pending 不落盘 → success 落盘（§22.3）。

    这条走的是**入口层实际调用路径**（`_HOOKS` 契约表 + `store.commit_login` 写回自检）。
    """
    upstream = FakeUpstream(_device_routes([
        httpx.Response(400, json={"error": "authorization_pending"}),
        httpx.Response(200, json={"access_token": "workos:eyJw", "refresh_token": "r-1"}),
    ]))
    upstream.routes[C.REGISTER_PATH] = httpx.Response(200, json={
        "success": True,
        "data": {"accessToken": "workos:eyJcline", "refreshToken": "r-2",
                 "expiresAt": "2026-09-29T05:23:47.000Z",
                 "userInfo": {"clineUserId": "usr-01ABC", "email": "dev@example.test"}},
    })
    _patch_client(monkeypatch, upstream)
    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)

    session = await engine.start("cline")
    assert session.name.startswith("cline-")                     # 默认名 `{product}-{8hex}`
    assert (await engine.poll("cline", session.id)).state == "pending"
    assert store.load_credentials("cline", session.name, root=root) == {}   # pending 不落盘

    outcome = await engine.poll("cline", session.id)
    assert outcome.state == "success"
    assert not store.has_account(root, session.name), "success 只暂存（M7-E 两阶段提交）"
    assert (await engine.commit_pending(session.id))["committed"] is True
    stored = store.load_credentials("cline", session.name, root=root)
    assert stored["access_token"] == "workos:eyJcline"
    assert stored["account_id"] == "usr-01ABC" and stored["refresh_token"] == "r-2"
    meta = store.load_meta(root, session.name)
    assert meta["via"] == "login" and meta["email"] == "dev@example.test"
    assert (await engine.poll("cline", session.id)).state == "expired"      # 确认后出表


# ============ 续期 ============


async def test_refresh_uses_camel_case_body_and_keeps_identity(monkeypatch):
    """续期：驼峰请求体 + `workos:` 幂等补齐 + **保留** account_id/email/nickname。"""
    upstream = FakeUpstream({C.REFRESH_PATH: httpx.Response(200, json={
        "success": True,
        "data": {"accessToken": "eyJnew", "refreshToken": "r-9",
                 "expiresAt": "2027-01-01T00:00:00.000Z"},
    })})
    _patch_client(monkeypatch, upstream)
    old = {"access_token": "workos:eyJold", "refresh_token": "r-1", "expire_time": 1,
           "account_id": "usr-1", "email": "a@b.c", "nickname": "a@b.c"}

    new = await cline.refresh(dict(old), cline.meta())

    assert upstream.json_of(C.REFRESH_PATH) == {"refreshToken": "r-1", "grantType": "refresh_token"}
    # ⚠️ token 交换类调用**不构造** Authorization（`workos:` 前缀坑位不适用于此，见 protocol 文档）
    assert upstream.auth_of(C.REFRESH_PATH) == ""
    assert new["access_token"] == "workos:eyJnew"          # 幂等补齐前缀
    assert new["refresh_token"] == "r-9"
    assert new["expire_time"] == int(
        dt.datetime.fromisoformat("2027-01-01T00:00:00+00:00").timestamp() * 1000)
    assert (new["account_id"], new["email"], new["nickname"]) == ("usr-1", "a@b.c", "a@b.c")
    assert old["access_token"] == "workos:eyJold"          # 不改入参（返回**新**凭据本体)


@pytest.mark.parametrize("cred", [
    {},                                    # 完全空凭据
    {"access_token": "workos:x"},          # 有访问令牌但没有 refresh_token
])
async def test_refresh_without_token_is_not_refreshable(monkeypatch, cred):
    """无 `refresh_token` → `NotRefreshable`（不是故障、不触发冷却、不打上游）。"""
    upstream = FakeUpstream({})
    _patch_client(monkeypatch, upstream)
    with pytest.raises(NotRefreshable, match="refresh_token"):
        await cline.refresh(cred, cline.meta())
    assert upstream.calls == []


@pytest.mark.parametrize("status,expect_retryable", [(401, False), (403, False), (500, True), (429, True)])
async def test_refresh_terminal_vs_retryable(monkeypatch, status, expect_retryable):
    """401/403 = 终态（`NotRefreshable`）；5xx/429 = 可重试（`RuntimeError`，不判终态）。"""
    upstream = FakeUpstream({C.REFRESH_PATH: httpx.Response(status, json={"error": "nope"})})
    _patch_client(monkeypatch, upstream)
    cred = {"access_token": "workos:x", "refresh_token": "r-1"}
    if expect_retryable:
        with pytest.raises(RuntimeError) as err:
            await cline.refresh(cred, cline.meta())
        assert not isinstance(err.value, NotRefreshable)
        assert f"HTTP {status}" in str(err.value)
    else:
        with pytest.raises(NotRefreshable, match=f"HTTP {status}"):
            await cline.refresh(cred, cline.meta())


async def test_refresh_200_without_token_is_terminal(monkeypatch):
    """200 却缺访问令牌 = 无法续期（需重新登录），**不是**可重试的瞬时故障。"""
    upstream = FakeUpstream({C.REFRESH_PATH: httpx.Response(200, json={"success": True, "data": {}})})
    _patch_client(monkeypatch, upstream)
    with pytest.raises(NotRefreshable, match="缺少访问令牌"):
        await cline.refresh({"access_token": "workos:x", "refresh_token": "r-1"}, cline.meta())


# ============ 探活 ============


async def test_probe_two_dimensions(monkeypatch):
    """探活：连通 / 凭据有效分开；`workos:` 前缀在鉴权头上补齐。"""
    upstream = FakeUpstream({C.ME_PATH: httpx.Response(200, json={"success": True})})
    _patch_client(monkeypatch, upstream)
    result = await cline.probe({"access_token": "eyJraw"}, cline.meta())   # 故意不带前缀
    assert result.ok and result.reachable and result.valid
    assert upstream.auth_of(C.ME_PATH) == "Bearer workos:eyJraw"

    upstream_401 = FakeUpstream({C.ME_PATH: httpx.Response(401, json={"error": "Unauthorized"})})
    _patch_client(monkeypatch, upstream_401)
    denied = await cline.probe({"access_token": "workos:x"}, cline.meta())
    assert denied.reachable and not denied.valid and "401" in denied.detail

    upstream_down = FakeUpstream({C.ME_PATH: httpx.ConnectError("boom")})
    _patch_client(monkeypatch, upstream_down)
    down = await cline.probe({"access_token": "workos:x"}, cline.meta())
    assert not down.reachable and not down.valid and "网络不可达" in down.detail

    no_cred = await cline.probe({}, cline.meta())
    assert not no_cred.reachable and "access_token" in no_cred.detail


# ============ 额度（三态 + 未知不当零）============


async def test_quota_available_uses_account_id_not_sub(monkeypatch):
    """余额端点必须用凭证里的 `account_id`（`usr-…`），不是 JWT 的 `sub`。"""
    upstream = FakeUpstream({"/api/v1/users/usr-01ABC/balance": httpx.Response(200, json={
        "data": {"userId": "usr-01ABC", "balance": 500000}, "success": True,
    })})
    _patch_client(monkeypatch, upstream)
    snap = await cline.quota({"access_token": "eyJraw", "account_id": "usr-01ABC"}, cline.meta())
    assert snap.state == "available" and snap.source == "cline-balance"
    assert "500000" in snap.detail and "未取证" in snap.detail     # 只报原始值，不做换算
    assert upstream.paths() == ["/api/v1/users/usr-01ABC/balance"]
    assert upstream.auth_of("/api/v1/users/usr-01ABC/balance") == "Bearer workos:eyJraw"


async def test_quota_zero_is_exhausted_not_unknown(monkeypatch):
    """真的为 0 = `exhausted`（可据此跳过选路）；查不到才是 `unknown`。"""
    upstream = FakeUpstream({"/api/v1/users/usr-1/balance": httpx.Response(200, json={
        "data": {"userId": "usr-1", "balance": 0}, "success": True,
    })})
    _patch_client(monkeypatch, upstream)
    snap = await cline.quota({"access_token": "workos:x", "account_id": "usr-1"}, cline.meta())
    assert snap.state == "exhausted" and "0" in snap.detail


@pytest.mark.parametrize("route,expect_fragment", [
    # ⚠️ 失败形态二：HTTP 401 的响应体**没有** success 字段，真原因只在 error 里（真实缺陷）
    (httpx.Response(401, json={"error": "Unauthorized: make sure you're using the latest version"}),
     "Unauthorized"),
    # 失败形态一：HTTP 200 业务失败
    (httpx.Response(200, json={"success": False, "error": "quota backend down"}), "quota backend down"),
    (httpx.Response(200, json={"success": True, "data": {}}), "balance"),
])
async def test_quota_unknown_keeps_reason(monkeypatch, route, expect_fragment):
    """**未知不当零**：查不到 → `unknown`，且 detail 保留服务端真原因。"""
    upstream = FakeUpstream({"/api/v1/users/usr-1/balance": route})
    _patch_client(monkeypatch, upstream)
    snap = await cline.quota({"access_token": "workos:x", "account_id": "usr-1"}, cline.meta())
    assert snap.state == "unknown" and expect_fragment in snap.detail


async def test_quota_without_account_id_does_not_call_upstream(monkeypatch):
    """缺 `account_id` → `unknown`（不猜 id、不打上游）。"""
    upstream = FakeUpstream({})
    _patch_client(monkeypatch, upstream)
    snap = await cline.quota({"access_token": "workos:x"}, cline.meta())
    assert snap.state == "unknown" and "account_id" in snap.detail
    assert upstream.calls == []


# ============ 模型目录（两端点合并）============


async def test_list_models_merges_two_endpoints_in_evidence_order(monkeypatch):
    """🔴 合并顺序：远端 free → 兜底表 → 推荐/订阅条目 → 远端大列表（兜底表在大列表**之前**）。"""
    upstream = FakeUpstream({
        C.RECOMMENDED_MODELS_PATH: httpx.Response(200, json={
            "free": [
                {"id": "cline-free/gemini-3.8-flash"},
                # 既非 `cline-free/` 前缀也非 `:free` 后缀 → 免费身份**只**能来自远端 free 集合
                {"id": "stealth/new-free-model", "name": "New Free Model"},
            ],
            "recommended": [{"id": "deepseek/deepseek-v4.1-flash", "description": "付费同族"}],
            "clinePass": [{"id": "cline-pass/opus", "name": "Opus (Pass)"}],
        }),
        C.MODELS_PATH: httpx.Response(200, json={"data": [
            {"id": "deepseek/deepseek-v4.1-flash", "object": "model"},
            {"id": "zzz/paid-1", "object": "model"},
        ]}),
    })
    _patch_client(monkeypatch, upstream)

    models = await cline.list_models({"access_token": "TOKEN-1"}, cline.meta())
    ids = [model.id for model in models]
    assert ids == [
        # ① 远端 free 数组（唯一权威，顺序有意义）
        "cline-free/gemini-3.8-flash", "stealth/new-free-model",
        # ② 兜底表（含内嵌目录缺的 gemini；远端大列表之前）
        "stealth/space-bunny-alpha", "cline-free/mimo-v2.6-flash",
        "cline-free/deepseek-v4.1-flash", "cline-free/muse-spark-1.3-contributor",
        # ③ 推荐 / 订阅条目（保持可发现性）
        "deepseek/deepseek-v4.1-flash", "cline-pass/opus",
        # ④ 远端 /models 的其余 id（460 条量级，放最后）
        "zzz/paid-1",
    ]
    by_id = {model.id: model for model in models}
    # 免费标记进 **name**（不是 description）；付费同族 id 不带标记
    assert by_id["cline-free/gemini-3.8-flash"].name == "Gemini 3.8 Flash · 免费"
    assert by_id["stealth/new-free-model"].name == "New Free Model · 免费"
    assert by_id["deepseek/deepseek-v4.1-flash"].name == "Deepseek V4.1 Flash"
    assert "免费" not in by_id["cline-pass/opus"].name
    # 兜底表元数据逐条回填；未知（远端只给 id）**不编造**
    assert by_id["cline-free/gemini-3.8-flash"].max_output == 65_536     # ⚠️ 不是 131072（实测 400 的真缺陷）
    assert by_id["cline-free/deepseek-v4.1-flash"].max_output == 131_072
    assert by_id["cline-free/gemini-3.8-flash"].context_window == 1_048_576
    assert by_id["cline-free/gemini-3.8-flash"].image_input is True
    assert by_id["zzz/paid-1"].context_window is None
    assert by_id["zzz/paid-1"].image_input is None and by_id["zzz/paid-1"].tool_call is None
    assert by_id["zzz/paid-1"].vendor == ""                              # 厂商展示名取不到 → 留空
    # 思考档位 = 产品级统一表（远端不下发）
    assert by_id["zzz/paid-1"].effort_levels == ("none", "low", "medium", "high", "max")
    # 两端点都打了；`/models` 需认证 → 必须带前缀令牌
    assert set(upstream.paths()) == {C.RECOMMENDED_MODELS_PATH, C.MODELS_PATH}
    assert upstream.auth_of(C.MODELS_PATH) == "Bearer workos:TOKEN-1"


async def test_list_models_falls_back_and_survives_partial_failure(monkeypatch):
    """两端点独立容错：`/models` 挂掉不影响推荐集合与兜底表（反之亦然）。"""
    upstream = FakeUpstream({
        C.RECOMMENDED_MODELS_PATH: httpx.Response(200, json={
            "free": [{"id": "stealth/new-free-model", "name": "New Free Model"}],
            "recommended": [], "clinePass": [],
        }),
        C.MODELS_PATH: httpx.Response(500, json={"error": "boom"}),
    })
    _patch_client(monkeypatch, upstream)
    models = await cline.list_models({"access_token": "workos:x"}, cline.meta())
    ids = [model.id for model in models]
    assert ids[:2] == ["stealth/new-free-model", "stealth/space-bunny-alpha"]
    assert "zzz/paid-1" not in ids
    assert len(ids) == 6            # 1 远端 free + 5 兜底（去重后）

    both_down = FakeUpstream({C.RECOMMENDED_MODELS_PATH: httpx.Response(503),
                              C.MODELS_PATH: httpx.ConnectError("down")})
    _patch_client(monkeypatch, both_down)
    fallback_only = await cline.list_models({"access_token": "workos:x"}, cline.meta())
    assert [model.id for model in fallback_only] == [model.id for model in C.FALLBACK_MODELS]
    assert all("· 免费" in model.name for model in fallback_only)


async def test_list_models_skips_authenticated_endpoint_without_credential(monkeypatch):
    """无凭据 → **不发** `/models`（需认证，匿名必然 401，白产生 warning）。"""
    upstream = FakeUpstream({
        C.RECOMMENDED_MODELS_PATH: httpx.Response(200, json={
            "free": [], "recommended": [], "clinePass": [],
        }),
    })
    _patch_client(monkeypatch, upstream)
    models = await cline.list_models({}, cline.meta())
    assert upstream.paths() == [C.RECOMMENDED_MODELS_PATH]
    assert len(models) == len(C.FALLBACK_MODELS)


# ============ claim 不可用语义 / 未接线钩子 ============


async def test_claim_is_explicitly_unavailable():
    """🔴 本产品**无签到端点**：钩子显式 NotImplementedError + 能力位 `checkin=False`
    （入口层按 Capabilities 不渲染按钮；`20 §3.1`、`22 §22.6`）。"""
    with pytest.raises(NotImplementedError, match="无签到端点"):
        await cline.claim({}, cline.meta(), precheck=False)
    with pytest.raises(NotImplementedError, match="无签到端点"):
        await cline.claim({"access_token": "workos:x"}, cline.meta(), precheck=True)
    product_meta = cline.meta()
    assert product_meta.capabilities.checkin is False        # 判据（不是标签）
    assert product_meta.capabilities.balance is True
    assert product_meta.capabilities.refresh is True         # 可续期（有 refresh_token 时）
    assert product_meta.base_url == "https://api.cline.bot/api/v1"   # registry 回填（M6-2）


async def test_hooks_still_unimplemented_are_declared_and_raise():
    """`login_callback`（非 local_callback 型）仍显式失败；`_IMPLEMENTED` 登记已接线的 7 个钩子。

    ⚠️ `build_out` 自 **M6-5b** 起已接线 → 原「M6-5 TODO」护栏**按波次转正**
    （处置同 buddy 的 M6-5a：正向断言见下一条用例）。
    """
    assert cline._IMPLEMENTED == frozenset(
        {"login_start", "login_poll", "refresh", "probe", "quota", "list_models", "build_out"})
    with pytest.raises(NotImplementedError, match="local_callback"):
        await cline._HOOKS["login_callback"](_session(), {})
    assert set(cline._HOOKS) == {"meta", "login_start", "login_poll", "login_callback",
                                 "refresh", "probe", "quota", "claim", "list_models", "build_out"}


def test_build_out_is_wired_to_the_family_adapter():
    """`build_out` 自 M6-5b 起接线（原 M6-5 TODO 护栏在此**按波次转正**）：
    返回 openai 族出站适配器；路径 = 基类缺省 `/chat/completions` + 基址已含 `/api/v1`
    = 取证值 `{apiBase}/api/v1/chat/completions`（`cline-product.ts:301`）。

    行为判据（`workos:` 前缀头 / 403 非凭据语义 / 错误映射 / 端到端）在
    `tests/integration/test_cline_out.py`；本用例只钉「接线本身成立」。
    """
    from model_gateway.adapters.product_out import ProductAccount
    from model_gateway.upstream.cline.out import ClineOut

    account = ProductAccount(product=cline.PRODUCT, name="acc-1",
                             base_url="https://api.cline.bot/api/v1")
    adapter = cline.build_out(account)
    assert isinstance(adapter, ClineOut)
    assert (adapter.product, adapter.account_ref) == ("cline", "acc-1")
    assert adapter.chat_path == "/chat/completions"
    assert adapter.base_url == "https://api.cline.bot/api/v1"
    asyncio.run(adapter.aclose())
