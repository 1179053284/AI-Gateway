"""`upstream/lobsterai` 产品钩子单测（tech-design v2.0 §22.3；`httpx.MockTransport` 假上游）。

🔴 判据逐条对应契约（**无网络、无真实凭据**：MockTransport 只认显式注册的 URL，未注册 → 404）：

  · 登录：`login_start` 的 portal URL 形态（source / redirect_uri / state）与"私有态不进
    Challenge"；`redirect_uri` 端口 = 回跳接收端**实际**端口（BD4；无接收端才兜底
    `gateway.port`），投递路径判据见 `tests/integration/test_m7_callback_capture.py`；
    `login_callback` 成功换凭据（5 字段请求体、无 `Authorization`）、**state 不匹配拒绝**、
    缺 code 拒绝、exchange 失败 → failed；`login_poll` = pending（正常业务状态）
  · 签到：三步**顺序**与请求形态（幂等键 uuid4）；幂等预检（`claimedToday` → already_done
    **不再发 check_in**；actions 无 check_in → inactive）；`precheck` 两种取值行为一致
  · 额度：三态 available / exhausted / **unknown（未知不当零）**
  · 刷新：字段合并（身份字段沿用 / refresh_token 空则不覆盖）/ 三条终态 → NotRefreshable /
    网络失败 → ProtocolError / **expires_at 回写 meta.json**（!IKIRTT 教训）
  · 目录：远端两种形状（单层数组 / `data.data` 嵌套）+ keyfrom query（**不带 refreshToken**）
    + 兜底表；`_HOOKS` 契约表与 `build_out` 的 M6-5 TODO 状态
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid

import httpx
import pytest

from model_gateway.accounts.login import LoginSession
from model_gateway.accounts.types import NotRefreshable
from model_gateway.upstream.lobsterai import (
    claim as claim_mod,
    const,
    login,
    models,
    product,
    protocol,
    quota as quota_mod,
)

API_HOST = "lobsterai-server.youdao.com"
VERSION_API_NEEDLE = "api-overmind.youdao.com"


# ============ 假上游 ============

def _raise_connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused")


class FakeUpstream:
    """按 URL 子串分派的假上游（httpx.MockTransport）；记录每次请求供断言。"""

    def __init__(self) -> None:
        self._routes: list[tuple[str, object]] = []
        self.requests: list[httpx.Request] = []

    def on(self, needle: str, response) -> "FakeUpstream":
        """注册路由（**同子串覆盖**，便于同一用例里改上游行为）。

        `response` 可以是 `httpx.Response` 或 `(request) -> Response`。
        """
        self._routes = [route for route in self._routes if route[0] != needle]
        self._routes.append((needle, response))
        return self

    def install(self, monkeypatch) -> None:
        """替换产品层**唯一**的客户端构造点（`protocol.make_client`，生产侧是同步工厂）。"""
        transport = httpx.MockTransport(self._handle)

        def factory(**kwargs) -> httpx.AsyncClient:
            return httpx.AsyncClient(transport=transport)

        monkeypatch.setattr(protocol, "make_client", factory)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for needle, response in self._routes:
            if needle in str(request.url):
                return response(request) if callable(response) else response
        return httpx.Response(404, json={"code": 404, "msg": f"未注册的假路由：{request.url}"})

    # —— 断言助手 ——

    def urls(self, needle: str = API_HOST) -> list[str]:
        """命中的请求 URL（默认只看业务 API 主机，版本号端点会被滤掉）。"""
        return [str(r.url) for r in self.requests if needle in str(r.url)]

    def request(self, needle: str) -> httpx.Request:
        """最后一条命中该子串的请求（不存在 → 断言失败，等于"没有发出这个请求"）。"""
        hits = [r for r in self.requests if needle in str(r.url)]
        assert hits, f"没有发出包含 {needle!r} 的请求；实际：{[str(r.url) for r in self.requests]}"
        return hits[-1]

    def body_of(self, needle: str) -> dict:
        request = self.request(needle)
        return json.loads(request.content.decode("utf-8") or "null")


def ok(data: dict, *, message: str = "OK") -> httpx.Response:
    """业务成功信封（`{code:0, msg, data}`）。"""
    return httpx.Response(200, json={"code": 0, "msg": message, "data": data})


def fail(code: int, message: str = "失败", *, status: int = 200) -> httpx.Response:
    """业务失败信封（HTTP 状态与业务码可分别指定）。"""
    return httpx.Response(status, json={"code": code, "msg": message})


@pytest.fixture(autouse=True)
def _reset_version_cache():
    """版本号缓存是**模块级**状态：不清会让用例互相串扰（照 DSH 的类实例动机）。"""
    login._reset_client_version_cache()
    yield
    login._reset_client_version_cache()


@pytest.fixture
def upstream(monkeypatch) -> FakeUpstream:
    """假上游 + 默认注册版本号端点（真实流程每轮都会先解析一次版本号）。"""
    fake = FakeUpstream()
    fake.on(VERSION_API_NEEDLE,
            httpx.Response(200, json={"code": 0, "msg": "OK",
                                      "data": {"value": {"version": "2026.9.9"}}}))
    fake.install(monkeypatch)
    return fake


def _session(**state) -> LoginSession:
    session = LoginSession(id="s-1", product="lobsterai", name="acc-1",
                           created_at=0.0, ttl_s=600.0)
    session.state.update({"state": "STATE-1", "uuid": "UUID-1", "first_keyfrom": "111000"})
    session.state.update(state)
    return session


def _cred(**over) -> dict:
    cred = {"access_token": "AT-1", "refresh_token": "RT-1", "expires_at": "99999999999999",
            "uid": "u-1", "user_id": "y-1", "nickname": "130****1100",
            "uuid": "UUID-1", "first_keyfrom": "111000", "latest_keyfrom": "222000"}
    cred.update(over)
    return cred


# ============ 登录：start / poll / callback ============

async def test_login_start_builds_portal_url_and_keeps_private_state(upstream):
    """`login_start` 零网络调用；URL 形态 = `lobsterai-oauth.ts:104-116`；私有态不进 Challenge。"""
    session = _session()
    session.state.clear()
    challenge = await product.login_start(session)

    state = session.state
    assert set(vars(challenge)) == {"url", "device_code", "qr_payload", "sms_sent"}
    assert challenge.url.startswith(f"{const.PORTAL_BASE}/portal#/login?")
    assert "source=electron" in challenge.url
    # 这条会话**没有**接收端（直接构造）→ 8300 只是兜底端口；有接收端时见下一条用例
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8300%2Fauth%2Fcallback" in challenge.url
    assert f"state={state['state']}" in challenge.url
    # 安装 uuid / first_keyfrom 是**私有态**（服务端识别同一安装的依据），不得出现在 URL 里
    assert str(uuid.UUID(state["uuid"])) == state["uuid"]
    assert state["uuid"] not in challenge.url
    assert state["first_keyfrom"].isdigit()
    assert upstream.requests == [], "login_start 不该有任何网络调用（弹窗被拦截的教训）"


async def test_login_start_uses_the_listener_port_when_present(upstream):
    """🔴 BD4：`redirect_uri` 的端口 = 回跳接收端的**实际**端口，不是网关自己的 8300。

    旧注释说"网关自己就是那个本地服务器"是**错的**（FastAPI 上没有 `/auth/callback`
    路由，实测 404）。门户校验的只是**形状** `http://127.0.0.1:{port}/auth/callback`
    （`lobsterai-oauth.ts:95-97`）→ 随机端口完全可用，形状不能变。
    """
    class _Listener:
        port = 21333

    session = _session()
    session.state.pop("state")
    session.callback = _Listener()
    challenge = await product.login_start(session)

    from urllib.parse import parse_qs, urlsplit

    fragment = urlsplit(challenge.url).fragment.split("?", 1)[1]   # hash 路由：参数在 # 之后
    redirect = parse_qs(fragment)["redirect_uri"][0]
    assert redirect == f"http://127.0.0.1:21333{const.CALLBACK_PATH}"
    assert "8300" not in challenge.url
    assert parse_qs(fragment)["state"][0] == session.state["state"]


def test_redirect_port_falls_back_to_the_gateway_port_only_without_a_listener(tmp_path,
                                                                              monkeypatch):
    """没有接收端（起监听失败 / 直接构造的会话）才回退 `gateway.port`，且只作兜底。"""
    config = tmp_path / "cfg" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("gateway:\n  port: 9317\n", encoding="utf-8")
    monkeypatch.setenv("MG_CONFIG", str(config))

    class _Listener:
        port = 21444

    session = _session()
    session.callback = _Listener()
    assert login.redirect_port(session) == 21444        # 实际端口优先
    session.callback = None
    assert login.redirect_port(session) == 9317          # 兜底 = 生效配置的网关端口


def test_callback_table_declares_the_listener_shape():
    """接收端形状的唯一真相源 = `product._CALLBACK`（引擎**读表**，不猜字段名）。"""
    assert product._CALLBACK == {
        "path": const.CALLBACK_PATH,                    # /auth/callback（门户校验形状）
        "preferred_port": 0,                            # 无首选 → 随机 ≥10000
        "secret_state_key": "state",
        "secret_key": "state",
        "secret_required": True,                        # portal 恒回传 state（防 CSRF）
    }


async def test_login_start_uses_configured_gateway_port(tmp_path, monkeypatch):
    """兜底端口取生效配置的 `gateway.port`（`config/schemas.py:75`）——仅在没有接收端时。"""
    config = tmp_path / "cfg" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("gateway:\n  port: 9317\n", encoding="utf-8")
    monkeypatch.setenv("MG_CONFIG", str(config))
    assert login.gateway_port() == 9317
    assert "127.0.0.1%3A9317" in login.login_url(login.gateway_port(), "S-1")


async def test_login_poll_stays_pending(upstream):
    """回调型产品的轮询**只**返回 pending（§22.3：pending 不是错误）。"""
    outcome = await product.login_poll(_session())
    assert outcome.state == "pending"
    assert "粘贴" in outcome.detail
    assert upstream.requests == [], "轮询不该打上游"


def test_new_login_state_uses_registry_identity_spec(monkeypatch, tmp_path):
    """安装 uuid 经 `device.generate_unique` 生成，**直接用注册表规格**（无单字段投影）。

    历史（W2-fix 已修）：本产品 DeviceSpec 曾是三字段（uuid + 两个 keyfrom），旧的
    `generate_unique` 拿单值候选与完整元组比较 → 查重恒通过，产品层只好投影成单字段绕开；
    §22.3 裁决后身份收敛为 `("uuid",)`（keyfrom 属元数据），投影删除、直接走公共层。
    """
    seen: dict = {}

    def fake_generate(root, spec, **kwargs):
        seen["spec"] = spec
        seen["root"] = root
        return "UUID-FIXED"

    with monkeypatch.context() as patch:
        patch.setattr(login.device, "generate_unique", fake_generate)
        state = login.new_login_state()
    assert state["uuid"] == "UUID-FIXED"
    assert seen["spec"] is product.meta().device, "必须直接用注册表规格（不再投影副本）"
    assert seen["spec"].fields == ("uuid",), "身份字段只有安装标识"
    assert seen["root"].name == "accounts" and "lobsterai" in str(seen["root"])
    assert state["first_keyfrom"].isdigit() and state["state"]

    other = login.new_login_state()
    assert other["uuid"] != state["uuid"]
    assert str(uuid.UUID(other["uuid"])) == other["uuid"]


def test_keyfrom_is_metadata_and_uuid_is_the_only_identity(tmp_path):
    """keyfrom 落 `meta.json` 但**不参与唯一性**；唯一身份 = 安装 uuid（§22.3 裁决）。"""
    from model_gateway.accounts import device

    spec = product.meta().device
    for name, keyfrom in (("a", "222000"), ("b", "333000")):
        account = tmp_path / name
        account.mkdir()
        (account / "meta.json").write_text(json.dumps(protocol.credential_meta(
            _cred(uuid="UUID-SAME", latest_keyfrom=keyfrom),
            fallback_name=name, device_fields=spec.fields)), encoding="utf-8")
    # 两个账号只差 keyfrom（时间戳元数据）→ 仍按"同一安装 uuid"冲突（任一身份字段相同）
    assert device.find_account_by_values(tmp_path, spec, ("UUID-SAME",)) == "a"
    # 无 uuid、只有 keyfrom 的账号**不构成占用**（keyfrom 不是身份字段）
    lone = tmp_path / "c"
    lone.mkdir()
    (lone / "meta.json").write_text(
        json.dumps({"first_keyfrom": "111000", "latest_keyfrom": "222000"}), encoding="utf-8")
    assert device.check_unique(tmp_path, spec, ("UUID-OTHER",)) is True
    assert device.find_account_by_values(tmp_path, spec, ("UUID-OTHER",)) is None


async def test_login_callback_success(upstream):
    """回跳粘贴 → 校验 state → exchange → success（含 meta 的展示字段镜像）。"""
    upstream.on(const.PATH_EXCHANGE, ok({
        "accessToken": "AT-NEW", "refreshToken": "RT-NEW", "expiresIn": 3600,
        "user": {"id": "u-9", "userId": "y-9", "nickname": "130****1100"},
    }))
    before = int(time.time() * 1000)
    outcome = await product.login_callback(_session(), {
        "url": "http://127.0.0.1:8300/auth/callback?code=CODE-1&state=STATE-1"})

    assert outcome.state == "success", outcome.detail
    cred = outcome.credentials
    assert cred["access_token"] == "AT-NEW" and cred["refresh_token"] == "RT-NEW"
    assert cred["uid"] == "u-9" and cred["user_id"] == "y-9"
    assert cred["uuid"] == "UUID-1" and cred["first_keyfrom"] == "111000"
    assert int(cred["latest_keyfrom"]) >= before
    assert int(cred["expires_at"]) >= before + 3600_000

    # meta：设备字段（§22.4 冻结的三字段都落 meta）+ 展示镜像（昵称按手机号掩码归一化 /
    # expires_at 是整数毫秒）
    assert outcome.meta["uuid"] == "UUID-1"
    assert outcome.meta["first_keyfrom"] == "111000"
    assert outcome.meta["latest_keyfrom"] == cred["latest_keyfrom"]
    assert outcome.meta["nickname"] == "130******00"
    assert isinstance(outcome.meta["expires_at"], int)
    assert "access_token" not in json.dumps(outcome.meta), "meta 不得承载凭据"

    # 请求形态：5 字段、无 Authorization（换 token 时还没有 token）
    request = upstream.request(const.PATH_EXCHANGE)
    assert request.headers.get("Authorization") is None
    body = upstream.body_of(const.PATH_EXCHANGE)
    assert set(body) == {"authCode", "firstKeyfrom", "latestKeyfrom", "uuid", "version"}
    assert body["authCode"] == "CODE-1" and body["uuid"] == "UUID-1"
    assert body["version"] == "2026.9.9"       # 动态版本号（不是兜底值）


async def test_login_callback_accepts_bare_query_string(upstream):
    """粘贴的可以只是 `code=…&state=…` 查询串（没有 `?` 前缀、没有主机）。"""
    upstream.on(const.PATH_EXCHANGE,
                ok({"accessToken": "AT-1", "refreshToken": "RT-1", "expiresIn": 60}))
    outcome = await product.login_callback(_session(), {"url": "code=CODE-2&state=STATE-1"})
    assert outcome.state == "success"


async def test_login_callback_rejects_state_mismatch_and_missing_code(upstream):
    """state 不匹配 / 缺 code → **拒绝**，且一次 exchange 都不打。"""
    upstream.on(const.PATH_EXCHANGE, ok({"accessToken": "AT-1"}))
    mismatch = await product.login_callback(
        _session(), {"url": "http://127.0.0.1:8300/auth/callback?code=C&state=OTHER"})
    assert mismatch.state == "failed" and "state" in mismatch.detail
    missing = await product.login_callback(_session(), {"url": "?state=STATE-1"})
    assert missing.state == "failed"
    assert upstream.urls(const.PATH_EXCHANGE) == []


async def test_login_callback_folds_exchange_failures(upstream):
    """exchange 业务失败 / `code:0` 但缺 accessToken → failed（**不谎报成功**）。"""
    upstream.on(const.PATH_EXCHANGE, fail(40100, "token rejected"))
    outcome = await product.login_callback(_session(), {"code": "C", "state": "STATE-1"})
    assert outcome.state == "failed" and "40100" in outcome.detail
    assert outcome.credentials == {}

    upstream.on(const.PATH_EXCHANGE, ok({"refreshToken": "RT"}))
    outcome = await product.login_callback(_session(), {"code": "C", "state": "STATE-1"})
    assert outcome.state == "failed" and "accessToken" in outcome.detail


async def test_login_callback_without_session_state_fails_closed(upstream):
    """会话态缺失（被取消/过期后残留调用）→ failed，**不发** exchange。"""
    session = _session()
    session.state.clear()
    outcome = await product.login_callback(session, {"code": "C", "state": "STATE-1"})
    assert outcome.state == "failed"
    assert upstream.urls(const.PATH_EXCHANGE) == []


async def test_login_engine_persists_credentials_and_device_meta(tmp_path, upstream):
    """经 `LoginEngine` 走完整两步式：粘贴回调 → 认领暂存 →「确定接入」→ 落盘 + 设备字段进 meta。"""
    from model_gateway.accounts import store
    from model_gateway.accounts.login import LoginEngine

    upstream.on(const.PATH_EXCHANGE, ok({"accessToken": "AT-E", "refreshToken": "RT-E",
                                         "expiresIn": 3600, "user": {"id": "u-5"}}))
    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)
    session = await engine.start(const.PRODUCT_ID, name="acc-e")
    assert session.challenge is not None
    assert session.challenge.url.startswith(f"{const.PORTAL_BASE}/portal#/login?")

    outcome = await engine.callback(const.PRODUCT_ID, session.id, {
        "url": f"?code=C&state={session.state['state']}"})

    assert outcome.state == "success", outcome.detail
    assert not store.has_account(root, "acc-e"), "到达只暂存，不落盘（M7-E 两阶段提交）"
    assert (await engine.commit_pending(session.id))["committed"] is True
    cred = store.load_credentials(const.PRODUCT_ID, "acc-e", root=root)
    assert cred["access_token"] == "AT-E" and cred["uuid"] == session.state["uuid"]
    meta = store.load_meta(root, "acc-e")
    assert meta["uuid"] == session.state["uuid"]
    assert meta["first_keyfrom"] == session.state["first_keyfrom"]
    assert meta["latest_keyfrom"] and meta["via"] == "login"
    assert engine._sessions == {}, "确认落盘后会话必须出表（内存有界 §22.8-9）"


# ============ 签到：三步 + 幂等预检 ============

def _slot_routes(upstream) -> FakeUpstream:
    upstream.on(const.PATH_ACTIVITY_SLOT, ok(
        {"slotState": "available",
         "activity": {"activityCode": "daily-checkin", "configRevision": 42}}))
    upstream.on("/actions/check_in", ok({"result": {"creditsGranted": 30}}))
    return upstream


async def test_claim_three_steps_success(upstream):
    """三步顺序 slot → context → check_in；请求形态与幂等键照抄取证。"""
    _slot_routes(upstream)
    upstream.on("/context?", ok({"state": {"claimedToday": False}, "actions": ["check_in"]}))

    outcome = await claim_mod.claim_daily(_cred(), precheck=False)

    assert outcome.category == "success"
    assert "30" in outcome.detail
    product_urls = upstream.urls()
    assert [u.split(API_HOST)[1].split("?")[0] for u in product_urls] == [
        const.PATH_ACTIVITY_SLOT,
        f"{const.PATH_ACTIVITY_CONTEXT}/daily-checkin/context",
        f"{const.PATH_ACTIVITY_CONTEXT}/daily-checkin/actions/check_in",
    ]
    slot_url = product_urls[0]
    assert "placement=desktop_sidebar" in slot_url and "platform=win32" in slot_url
    assert "containerApiVersion=2" in slot_url and "clientVersion=2026.9.9" in slot_url
    assert "configRevision=42" in product_urls[1]

    body = upstream.body_of("/actions/check_in")
    assert body["configRevision"] == 42 and isinstance(body["configRevision"], int)
    assert body["payload"] == {}
    assert str(uuid.UUID(body["idempotencyKey"])) == body["idempotencyKey"], "幂等键必须是 uuid4"


async def test_claim_already_claimed_today_skips_checkin(upstream):
    """幂等预检之一：`claimedToday` → already_done，**不发** check_in。"""
    _slot_routes(upstream)
    upstream.on("/context?", ok({"state": {"claimedToday": True}, "actions": ["check_in"]}))
    outcome = await claim_mod.claim_daily(_cred(), precheck=True)
    assert outcome.category == "already_done"
    assert upstream.urls("/actions/check_in") == []


async def test_claim_inactive_without_checkin_action(upstream):
    """幂等预检之二：`actions` 不含 `check_in` → inactive（正常业务状态，不是失败）。"""
    _slot_routes(upstream)
    upstream.on("/context?", ok({"state": {"claimedToday": False}, "actions": []}))
    outcome = await claim_mod.claim_daily(_cred(), precheck=False)
    assert outcome.category == "inactive"
    assert upstream.urls("/actions/check_in") == []


async def test_claim_inactive_when_slot_unavailable(upstream):
    """无可用活动（slotState != available）→ inactive，且**不做**后两步。"""
    upstream.on(const.PATH_ACTIVITY_SLOT, ok({"slotState": "not_started"}))
    outcome = await claim_mod.claim_daily(_cred(), precheck=False)
    assert outcome.category == "inactive"
    assert upstream.urls("/context") == [] and upstream.urls("/actions/check_in") == []


async def test_claim_failed_on_lookup_errors(upstream):
    """槽位/上下文查询本身失败 → failed（异常与业务状态严格区分）。"""
    upstream.on(const.PATH_ACTIVITY_SLOT, httpx.Response(500, json={"code": 500, "msg": "boom"}))
    outcome = await claim_mod.claim_daily(_cred(), precheck=False)
    assert outcome.category == "failed" and "槽位" in outcome.detail

    upstream.on(const.PATH_ACTIVITY_SLOT, ok(
        {"slotState": "available", "activity": {"activityCode": "a", "configRevision": 1}}))
    upstream.on("/context?", fail(500, "ctx boom"))
    outcome = await claim_mod.claim_daily(_cred(), precheck=False)
    assert outcome.category == "failed" and "上下文" in outcome.detail


async def test_claim_failed_when_checkin_rejected(upstream):
    """签到请求被业务码拒绝 → failed（**业务码不重试**，§22.6）。"""
    _slot_routes(upstream)
    upstream.on("/context?", ok({"state": {"claimedToday": False}, "actions": ["check_in"]}))
    upstream.on("/actions/check_in", fail(402, "免费额度已用完，请升级套餐"))
    outcome = await claim_mod.claim_daily(_cred(), precheck=False)
    assert outcome.category == "failed"
    assert "402" in outcome.detail and "升级套餐" in outcome.detail


async def test_claim_failed_without_access_token(upstream):
    """凭据没有 access_token → failed（凭据未配置，需用户处理；不发任何请求）。"""
    outcome = await claim_mod.claim_daily(_cred(access_token=""), precheck=False)
    assert outcome.category == "failed" and "access_token" in outcome.detail
    assert upstream.urls() == []


async def test_claim_precheck_flag_behaviour_identical(upstream):
    """`precheck` 两种取值行为一致（流程自带预检；见 `claim.py` 模块头）。"""
    _slot_routes(upstream)
    upstream.on("/context?", ok({"state": {"claimedToday": False}, "actions": ["check_in"]}))
    with_false = await claim_mod.claim_daily(_cred(), precheck=False)
    calls_after_false = len(upstream.urls())
    with_true = await claim_mod.claim_daily(_cred(), precheck=True)
    assert with_false.category == with_true.category == "success"
    assert len(upstream.urls()) == calls_after_false * 2, "两种取值都是恰好三步"


# ============ 额度：三态 + 未知不当零 ============

async def test_quota_available(upstream):
    upstream.on(const.PATH_PROFILE_SUMMARY,
                ok({"totalCreditsRemaining": 5297.72,
                    "creditItems": [{"creditsRemaining": 100, "label": "每日登录奖励"}]}))
    snapshot = await quota_mod.quota_snapshot(_cred())
    assert snapshot.state == "available"
    assert snapshot.source == "profile-summary" and "5297.72" in snapshot.detail
    request = upstream.request(const.PATH_PROFILE_SUMMARY)
    assert request.headers["Authorization"] == "Bearer AT-1"


async def test_quota_exhausted_needs_explicit_zero(upstream):
    """`exhausted` 只在有**显式 0 证据**时给出（字段为 0 + 明细全 0）。"""
    upstream.on(const.PATH_PROFILE_SUMMARY, ok(
        {"totalCreditsRemaining": 0, "creditItems": [{"creditsRemaining": 0}]}))
    snapshot = await quota_mod.quota_snapshot(_cred())
    assert snapshot.state == "exhausted"


async def test_quota_zero_without_items_is_unknown(upstream):
    """**未知不当零**：0 且无明细 → unknown（照抄 DSH「视作查不到」口径）。"""
    upstream.on(const.PATH_PROFILE_SUMMARY, ok({"totalCreditsRemaining": 0}))
    snapshot = await quota_mod.quota_snapshot(_cred())
    assert snapshot.state == "unknown" and snapshot.source == "profile-summary"


async def test_quota_unknown_on_rejected_or_unreachable(upstream):
    """401 与网络失败都是 unknown（不伪装成 0；原因写进 detail）。"""
    upstream.on(const.PATH_PROFILE_SUMMARY, fail(401, "unauthorized", status=401))
    snapshot = await quota_mod.quota_snapshot(_cred())
    assert snapshot.state == "unknown" and "401" in snapshot.detail

    upstream.on(const.PATH_PROFILE_SUMMARY, _raise_connect_error)
    snapshot = await quota_mod.quota_snapshot(_cred())
    assert snapshot.state == "unknown" and "网络失败" in snapshot.detail


# ============ 探活：两维分开 ============

async def test_probe_valid_and_rejected_and_unreachable(upstream):
    upstream.on(const.PATH_PROFILE_SUMMARY, ok({"totalCreditsRemaining": 1}))
    result = await quota_mod.probe_credential(_cred())
    assert result.reachable and result.valid and result.ok

    upstream.on(const.PATH_PROFILE_SUMMARY, fail(401, "unauthorized", status=401))
    result = await quota_mod.probe_credential(_cred())
    assert result.reachable and not result.valid and not result.ok

    upstream.on(const.PATH_PROFILE_SUMMARY, _raise_connect_error)
    result = await quota_mod.probe_credential(_cred())
    assert not result.reachable and not result.valid


async def test_probe_without_token_does_not_call_upstream(upstream):
    """本地缺凭据 → 不发请求（别把"没凭据"报成"网络不通"）。"""
    result = await quota_mod.probe_credential(_cred(access_token=""))
    assert not result.reachable and "access_token" in result.detail
    assert upstream.urls() == []


# ============ 刷新 ============

async def test_refresh_merges_fields_and_writes_back_meta(upstream, tmp_path):
    """续期成功：身份字段沿用旧值、refresh_token 空则不覆盖、`expires_at` 回写 meta.json。"""
    account_dir = tmp_path / "accounts" / "acc-1"
    account_dir.mkdir(parents=True)
    (account_dir / "meta.json").write_text(json.dumps(
        {"uuid": "UUID-1", "nickname": "130******00", "expires_at": 1, "via": "login"}),
        encoding="utf-8")
    upstream.on(const.PATH_REFRESH, ok({"accessToken": "AT-2", "refreshToken": ""}))
    merged = await login.refresh_credential(
        _cred(), {"account": "acc-1", "dir": str(account_dir)})

    assert merged["access_token"] == "AT-2"
    assert merged["refresh_token"] == "RT-1", "响应空 refreshToken 不得覆盖"
    assert merged["expires_at"] == "99999999999999", "无 expiresIn/JWT → 沿用旧值"
    for key in ("uuid", "first_keyfrom", "latest_keyfrom", "uid", "user_id", "nickname"):
        assert merged[key] == _cred()[key], f"身份字段 {key} 必须沿用旧值"

    request = upstream.request(const.PATH_REFRESH)
    assert request.headers.get("Authorization") is None
    body = upstream.body_of(const.PATH_REFRESH)
    assert body["refreshToken"] == "RT-1" and body["uuid"] == "UUID-1"
    assert body["firstKeyfrom"] == "111000" and body["latestKeyfrom"] == "222000"
    assert body["version"] == "2026.9.9"

    meta = json.loads((account_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["uuid"] == "UUID-1" and meta["via"] == "login", "只补不删"
    assert meta["expires_at"] == 99999999999999 and meta["expires_at"] != 1


async def test_refresh_expires_in_updates_meta(upstream, tmp_path):
    """`expiresIn` 路径：按当前时刻换算新 `expires_at` 并写回 meta.json。"""
    account_dir = tmp_path / "accounts" / "acc-2"
    account_dir.mkdir(parents=True)
    (account_dir / "meta.json").write_text(json.dumps({"uuid": "UUID-2"}), encoding="utf-8")
    upstream.on(const.PATH_REFRESH,
                ok({"accessToken": "AT-3", "refreshToken": "RT-3", "expiresIn": 7200}))
    before = int(time.time() * 1000)
    merged = await login.refresh_credential(
        _cred(), {"account": "acc-2", "dir": str(account_dir)})
    assert before + 7200_000 <= int(merged["expires_at"]) <= int(time.time() * 1000) + 7200_000
    meta = json.loads((account_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["expires_at"] == int(merged["expires_at"])


async def test_refresh_without_refresh_token_is_not_refreshable(upstream):
    with pytest.raises(NotRefreshable):
        await login.refresh_credential(_cred(refresh_token=""), None)
    assert upstream.urls() == [], "本地就知道不可续期 → 不该打上游"


async def test_refresh_terminal_failures_are_not_refreshable(upstream):
    """三条终态：HTTP 401 / 响应体 40101 / `code:0` 但缺 accessToken。"""
    upstream.on(const.PATH_REFRESH, fail(401, "token rejected", status=401))
    with pytest.raises(NotRefreshable):
        await login.refresh_credential(_cred(), None)

    upstream.on(const.PATH_REFRESH, fail(40101, "refresh token was rejected"))
    with pytest.raises(NotRefreshable):
        await login.refresh_credential(_cred(), None)

    upstream.on(const.PATH_REFRESH, ok({"refreshToken": "RT-9"}))
    with pytest.raises(NotRefreshable):
        await login.refresh_credential(_cred(), None)


async def test_refresh_transient_failure_is_protocol_error(upstream):
    """网络抖动 / 非 JSON → `ProtocolError`（**可重试**，不判终态：比 Go 精确的那处改进）。"""
    upstream.on(const.PATH_REFRESH, _raise_connect_error)
    with pytest.raises(protocol.ProtocolError):
        await login.refresh_credential(_cred(), None)

    upstream.on(const.PATH_REFRESH, httpx.Response(503, text="<html>bad gateway</html>"))
    with pytest.raises(protocol.ProtocolError):
        await login.refresh_credential(_cred(), None)


async def test_write_meta_fields_only_writes_when_changed(tmp_path):
    """`write_meta_fields` 只补不删、值没变不写盘（照抄 DSH「现值一致时不写盘」）。"""
    account_dir = tmp_path / "acc"
    account_dir.mkdir()
    meta_path = account_dir / "meta.json"
    meta_path.write_text(json.dumps({"uuid": "U-1", "note": "keep"}), encoding="utf-8")
    stamp = meta_path.stat().st_mtime_ns

    protocol.write_meta_fields(str(account_dir), {"expires_at": 123})
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta == {"uuid": "U-1", "note": "keep", "expires_at": 123}

    stamp = meta_path.stat().st_mtime_ns
    protocol.write_meta_fields(str(account_dir), {"expires_at": 123})
    assert meta_path.stat().st_mtime_ns == stamp, "值没变不该重写（每次续期都写会平白落盘）"

    protocol.write_meta_fields(str(tmp_path / "不存在"), {"expires_at": 1})  # 不抛、不建目录
    assert not (tmp_path / "不存在").exists()


# ============ 目录 ============

async def test_list_models_remote_shapes_and_headers(upstream):
    """远端两种形状都认；query 是 keyfrom（**不带 refreshToken**）；两个客户端头必带。"""
    upstream.on(const.PATH_MODELS, httpx.Response(200, json={
        "code": 0, "message": "success",
        "data": [
            {"modelId": "kimi-k3", "modelName": "Kimi K3", "contextWindow": 1000000,
             "maxTokens": 32768, "supportsImage": True, "supportsThinking": True,
             "thinkingConfig": {"options": [
                 {"level": "off", "openclawLevel": "off"},
                 {"level": "high", "openclawLevel": "high"},
                 {"level": "max", "openclawLevel": "xhigh"}],
                 "defaultLevel": "high"}},
            {"modelId": "glm-5", "modelName": ""},
            {"modelName": "没有 id，丢弃"},
        ]}))
    result = await product.list_models(_cred(), None)
    assert [m.id for m in result] == ["kimi-k3", "glm-5"]
    assert result[0].name == "Kimi K3" and result[1].name == "glm-5"
    assert result[0].context_window == 1000000 and result[0].max_output == 32768
    assert result[0].image_input is True and result[0].reasoning is True
    assert result[0].effort_levels == ("off", "high", "max")
    assert result[1].context_window is None, "远端没给就不编造"

    request = upstream.request(const.PATH_MODELS)
    query = str(request.url).split("?", 1)[1]
    assert "firstKeyfrom=111000" in query and "latestKeyfrom=222000" in query
    assert "uuid=UUID-1" in query and "userId=y-1" in query and "version=2026.9.9" in query
    assert "refreshToken" not in query, "refreshToken 不得进 query（会进服务端访问日志）"
    assert request.headers["Authorization"] == "Bearer AT-1"
    assert request.headers["X-LobsterAI-Client-Capabilities"] == const.CLIENT_CAPABILITIES
    assert request.headers["X-LobsterAI-Client-Version"] == "2026.9.9"


async def test_list_models_accepts_nested_data_shape(upstream):
    """双层形态 `data.data`（`client.go:254-278`）也要认。"""
    upstream.on(const.PATH_MODELS, httpx.Response(200, json={
        "code": 0, "msg": "OK", "data": {"data": [{"modelId": "MiniMax-M3"}]}}))
    result = await product.list_models(_cred(), None)
    assert [m.id for m in result] == ["MiniMax-M3"]


async def test_list_models_falls_back_when_remote_unavailable(upstream):
    """远端失败 / 未登录 → 兜底表（19 条；`context_window` 留空 —— 不编造估计值）。"""
    upstream.on(const.PATH_MODELS, httpx.Response(500, text="boom"))
    result = await product.list_models(_cred(), None)
    assert [m.id for m in result] == [model_id for model_id, _ in models.FALLBACK_MODELS]
    assert len(result) == 19
    assert all(m.context_window is None for m in result)
    assert all(m.name == m.id for m in result)

    upstream.on(const.PATH_MODELS, ok({}))
    assert await product.list_models(_cred(access_token=""), None) == result, "无凭据不发请求"


async def test_thinking_config_is_dropped_when_half_valid(upstream):
    """`thinkingConfig` 结构不符（off 一致性 / defaultLevel / 只有 off）→ 整块丢弃、不解析半截。"""
    upstream.on(const.PATH_MODELS, httpx.Response(200, json={"code": 0, "data": [
        {"modelId": "only-off", "thinkingConfig": {"options": [
            {"level": "off", "openclawLevel": "off"}], "defaultLevel": "off"}},
        {"modelId": "bad-default", "thinkingConfig": {"options": [
            {"level": "low", "openclawLevel": "low"}], "defaultLevel": "high"}},
        {"modelId": "off-mismatch", "thinkingConfig": {"options": [
            {"level": "off", "openclawLevel": "low"}], "defaultLevel": "off"}},
    ]}))
    result = await product.list_models(_cred(), None)
    assert [m.effort_levels for m in result] == [(), (), ()]


# ============ 契约面 ============

def test_hooks_table_matches_frozen_contract_and_build_out_is_wired():
    """`_HOOKS` == §22.3 的 10 个钩子；`build_out` 自 **M6-5b** 起接线
    （原「M6-5 TODO」护栏按波次转正，处置同 buddy 的 M6-5a）。

    行为判据（强制 `stream:true` / 非流式 SSE 聚合 / 头 / 错误映射 / 端到端）在
    `tests/integration/test_lobsterai_out.py`；本用例只钉「接线本身成立」。
    """
    assert set(product._HOOKS) == {
        "meta", "login_start", "login_poll", "login_callback", "refresh",
        "probe", "quota", "claim", "list_models", "build_out"}
    assert "build_out" in product._IMPLEMENTED

    from model_gateway.adapters.product_out import ProductAccount
    from model_gateway.upstream.lobsterai.out import LobsteraiOut

    account = ProductAccount(product=product.PRODUCT, name="acc-1", base_url=const.API_BASE)
    adapter = product.build_out(account)
    assert isinstance(adapter, LobsteraiOut)
    assert (adapter.product, adapter.account_ref) == ("lobsterai", "acc-1")
    assert adapter.chat_path == "/api/proxy/v1/chat/completions"   # lobsterai.ts:45
    assert adapter.base_url == const.API_BASE
    asyncio.run(adapter.aclose())


def test_meta_reflects_registry_backfill():
    """`meta()` 从注册表取（唯一事实源）；M6-2 回填了 base_url，身份字段 = uuid 单字段
    （§22.3 裁决 2026-09-29：keyfrom 属元数据、不进 spec）。"""
    info = product.meta()
    assert info.id == const.PRODUCT_ID == product.PRODUCT
    assert info.base_url == const.API_BASE
    assert info.device.fields == ("uuid",)
    assert info.login == "local_callback" and info.models_source == "remote"


def test_read_num_filters_nan_and_inf():
    """R2a-F-1（2026-10-06 第三轮对账）：读入口过滤 NaN/Infinity（同 trae read_num）。"""
    from model_gateway.upstream.lobsterai.protocol import read_num

    assert read_num({"k": float("nan")}, "k") is None
    assert read_num({"k": float("inf")}, "k") is None
    assert read_num({"k": 300}, "k") == 300.0
