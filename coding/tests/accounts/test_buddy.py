"""`upstream/buddy` 产品钩子单测（tech-design v2.0 §22.3/§22.4；M6-2 波次 A1）。

HTTP **全部**用 `httpx.MockTransport` 注入（monkeypatch `accounts/net.py::make_client`
—— 钩子只经它取客户端，§22.8-1）→ **无网络、无真实凭据**。

判据逐条对应契约：
  · 登录两步式：`auth/state` → 外链 URL（`Challenge` 只承载用户可见物）→ 轮询 token → 账户 → success
  · `pending` 不是错误（业务码 11217 / 12151）；网络错误也不中断登录（`buddy-oauth.ts:206-209`）
  · 幂等：**HTTP 400 + 业务码 10001** → `already_done`（不是失败）；precheck 短路省一次领取
  · 额度三态：available / exhausted / unknown（**未知不当零**）；失效包不并入总额
  · 刷新失败语义：`refresh_token` 失效（401）→ `NotRefreshable`；网络/5xx → 可重试异常
  · 模型表合并：兜底表为主集 + 远端逐字段优先 + agent 引用/试用横幅追加在尾
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from model_gateway.accounts import net
from model_gateway.accounts.login import LoginEngine
from model_gateway.accounts.store import has_account, load_credentials
from model_gateway.accounts.types import NotRefreshable
from model_gateway.upstream.buddy import product as buddy

# 供断言使用的固定时刻（JWT iat/exp，避免用例依赖真实时钟）
IAT = 1_700_000_000
ACCESS = ""   # 由 _jwt() 在下方填充
REFRESH = "RT-1-REFRESH-TOKEN"


def _jwt(claims: dict) -> str:
    """最小 JWT（只拼三段，不签名）：供昵称 / 过期时间解析用例使用。"""
    def seg(obj: dict) -> str:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{seg({'alg': 'none'})}.{seg(claims)}.sig"


ACCESS = _jwt({"iat": IAT, "exp": IAT + 3600, "nickname": "小明", "sub": "u-1"})

AUTH_URL = "https://www.codebuddy.cn/login/?platform=ide&state=ST-1"

#: 一次成功登录的三个端点（顺序即钩子调用顺序）
LOGIN_ROUTES: dict = {
    "/v2/plugin/auth/state": (200, {"code": 0, "data": {"state": "ST-1", "authUrl": AUTH_URL}}),
    "/v2/plugin/auth/token": (200, {"code": 0, "data": {
        # e2e 实证：实测只回相对秒数 expiresIn（没有 expiresAt，`buddy.ts:314-321`）
        "accessToken": ACCESS, "refreshToken": REFRESH, "expiresIn": 3600,
        "refreshExpiresIn": 7200, "tokenType": "Bearer",
        "scope": "profile\n  offline_access", "domain": "copilot.tencent.com"}}),
    "/v2/plugin/login/account": (200, {"code": 0, "data": {
        # nickname 为空：真名只在 JWT（`buddy.ts:344-362`）；type 走默认 personal
        "uid": "u-1", "nickname": "", "enterpriseId": ""}}),
}

#: 一个有效资源包（本周期剩余 100.5）+ 一个已失效包（Status=3 → 不得并入总额）
BALANCE_ROUTES = {
    "/v2/billing/meter/get-user-resource": (200, {"code": 0, "data": {"Response": {"Data": {
        "Accounts": [
            {"PackageName": "个人体验版", "CapacityUnit": "credits", "Status": 0,
             "CycleCapacityRemain": 100, "CycleCapacityRemainPrecise": "100.50",
             "DeductionEndTime": 4_102_444_800_000},      # 2100 年（未到期）
            {"PackageName": "裂变包", "CapacityUnit": "credits", "Status": 3,
             "CycleCapacityRemain": 500, "CycleCapacityRemainPrecise": "500.00"},
        ]}}}}),
}

_CRED = {"access_token": ACCESS, "refresh_token": REFRESH, "user_id": "u-1"}

#: 兜底表的 id 序列（合并用例的判据：兜底表定集合与顺序；符号仅测试内使用）
FALLBACK_IDS = [m.id for m in buddy._PROFILE.fallback_models]


def _raise(exc_type, message: str):
    """造一个「传输层异常」路由（模拟网络不可达/超时）。"""
    def route(request: httpx.Request) -> httpx.Response:
        raise exc_type(message, request=request)
    return route


def _raw(status: int, text: str):
    """造一个「非 JSON 响应」路由（腾讯网关在凭据失效时回 HTML 错误页）。"""
    def route(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=text, request=request)
    return route


def _install_http(monkeypatch, routes: dict) -> list[httpx.Request]:
    """把 `net.make_client` 换成 MockTransport 客户端（记录请求；无网络）。"""
    seen: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        route = routes.get(request.url.path)
        if route is None:
            return httpx.Response(404, json={"code": 404, "message": f"unrouted {request.url.path}"})
        if callable(route):
            return route(request)
        status, body = route
        return httpx.Response(status, json=body, request=request)

    def factory(**kwargs):
        # 与 `net.make_client` **同形**：base_url/headers 必须照传（钩子用相对路径，
        # 只有 base_url 参与合并后请求才是绝对的 —— 否则 MockTransport 拿到相对 URL）。
        kwargs.pop("follow_redirects", None)
        kwargs["timeout"] = httpx.Timeout(5.0)
        return httpx.AsyncClient(transport=httpx.MockTransport(responder), **kwargs)

    monkeypatch.setattr(net, "make_client", factory)
    return seen


# ============ 登录：两步式 ============

async def test_login_start_returns_external_link_and_keeps_state_private(tmp_path, monkeypatch):
    """第一步：`auth/state` → 外链 URL；轮询用的 state 留在 `session.state`（不回显）。"""
    seen = _install_http(monkeypatch, LOGIN_ROUTES)
    engine = LoginEngine(root=tmp_path / "accounts")
    session = await engine.start(buddy.PRODUCT)

    assert session.challenge.url == AUTH_URL
    assert session.challenge.device_code == "" and session.challenge.qr_payload == ""
    assert session.state["auth_state"] == "ST-1"
    # Challenge 只允许 §22.3 的四个用户可见字段（state 由服务端嵌在 authUrl 里，属正常；
    # 这里断言的是**没有第五个字段**、没有把 §22.3 私有态另立一栏）
    assert set(vars(session.challenge)) == {"url", "device_code", "qr_payload", "sms_sent"}
    request = seen[0]
    assert request.method == "POST" and request.url.path == "/v2/plugin/auth/state"
    assert request.url.params["platform"] == "ide"               # product.ts:270
    assert request.headers["X-Domain"] == "copilot.tencent.com"  # buddy.ts:98
    assert request.headers["X-No-Authorization"] == "true"       # buddy-oauth.ts:145


async def test_login_poll_pending_then_success_and_commits_credential(tmp_path, monkeypatch):
    """11217=token 未就绪（**非 200** 响应体业务码）→ `pending`（**不是错误**）；
    就绪后 success 且凭据落盘。"""
    calls = {"token": 0}
    routes = dict(LOGIN_ROUTES)

    def token_route(request: httpx.Request) -> httpx.Response:
        calls["token"] += 1
        if calls["token"] == 1:
            # 判定以**响应体 code** 为准：不能只看 HTTP 状态（credits.ts:19-21）
            return httpx.Response(400, json={"code": 11217, "message": "token not ready"},
                                  request=request)
        return httpx.Response(200, json=LOGIN_ROUTES["/v2/plugin/auth/token"][1], request=request)

    routes["/v2/plugin/auth/token"] = token_route
    _install_http(monkeypatch, routes)
    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)
    session = await engine.start(buddy.PRODUCT)

    first = await engine.poll(buddy.PRODUCT, session.id)
    assert first.state == "pending" and "授权" in first.detail
    second = await engine.poll(buddy.PRODUCT, session.id)
    assert second.state == "success", second.detail
    assert not has_account(root, session.name), "success 只暂存（M7-E 两阶段提交）"
    assert (await engine.commit_pending(session.id))["committed"] is True

    saved = load_credentials(buddy.PRODUCT, session.name, root=root)
    assert saved["access_token"] == ACCESS and saved["refresh_token"] == REFRESH
    # 相对 expiresIn 换算为绝对毫秒（基准 = JWT iat，`buddy.ts:271-299`）
    assert saved["expires_at"] == str(IAT * 1000 + 3600 * 1000)
    assert saved["refresh_expires_at"] == str(IAT * 1000 + 7200 * 1000)
    # scope 的多行文本被折叠（否则 JSON 落盘会被破坏，`buddy.ts:243-249`）
    assert "\n" not in saved["scope"] and saved["scope"].startswith("profile")
    # 昵称取自 JWT（account.nickname 为空），uid 取自账户响应
    assert saved["nickname"] == "小明" and saved["user_id"] == "u-1"
    meta = json.loads((root / session.name / "meta.json").read_text(encoding="utf-8"))
    assert meta["uid"] == "u-1" and meta["account_type"] == "personal" and meta["via"] == "login"


async def test_login_poll_expires_at_falls_back_to_jwt_exp(tmp_path, monkeypatch):
    """token 响应既无 `expiresAt` 也无 `expiresIn` → 用 access_token 的 JWT `exp` 兜底
    （`buddy.ts:154-161` 的权威兜底口径）。"""
    routes = dict(LOGIN_ROUTES)
    routes["/v2/plugin/auth/token"] = (200, {"code": 0, "data": {
        "accessToken": ACCESS, "refreshToken": REFRESH}})      # 两个过期字段都没有
    _install_http(monkeypatch, routes)
    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)
    session = await engine.start(buddy.PRODUCT)
    assert (await engine.poll(buddy.PRODUCT, session.id)).state == "success"
    assert (await engine.commit_pending(session.id))["committed"] is True
    saved = load_credentials(buddy.PRODUCT, session.name, root=root)
    assert saved["expires_at"] == str((IAT + 3600) * 1000)     # JWT exp


async def test_login_poll_account_not_ready_then_failed_code(tmp_path, monkeypatch):
    """12151=账户未就绪 → pending；其他业务码 → failed（**显式失败**，不静默）。"""
    routes = dict(LOGIN_ROUTES)
    routes["/v2/plugin/login/account"] = (400, {"code": 12151, "message": "account not ready"})
    _install_http(monkeypatch, routes)
    engine = LoginEngine(root=tmp_path / "accounts")
    session = await engine.start(buddy.PRODUCT)
    assert (await engine.poll(buddy.PRODUCT, session.id)).state == "pending"

    routes["/v2/plugin/login/account"] = (403, {"code": 12345, "message": "拒绝"})
    session2 = await engine.start(buddy.PRODUCT)
    outcome = await engine.poll(buddy.PRODUCT, session2.id)
    assert outcome.state == "failed" and "12345" in outcome.detail


async def test_login_poll_network_error_stays_pending(tmp_path, monkeypatch):
    """网络错误**不中断登录流程**（DSH `buddy-oauth.ts:206-209` 原文语义）→ pending。"""
    routes = dict(LOGIN_ROUTES)
    routes["/v2/plugin/auth/token"] = _raise(httpx.ConnectError, "boom")
    _install_http(monkeypatch, routes)
    engine = LoginEngine(root=tmp_path / "accounts")
    session = await engine.start(buddy.PRODUCT)
    outcome = await engine.poll(buddy.PRODUCT, session.id)
    assert outcome.state == "pending" and "网络错误" in outcome.detail


async def test_login_start_network_error_is_readable(tmp_path, monkeypatch):
    """`auth/state` 网络失败 → 可读异常（对齐 `jet-hub-rpc.ts:844-847` 的文案形态）。"""
    _install_http(monkeypatch, {"/v2/plugin/auth/state": _raise(httpx.ConnectError, "down")})
    engine = LoginEngine(root=tmp_path / "accounts")
    with pytest.raises(RuntimeError, match="无法获取 CodeBuddy 登录地址"):
        await engine.start(buddy.PRODUCT)


async def test_login_callback_is_explicitly_unsupported(tmp_path, monkeypatch):
    """非 local_callback 型：回跳粘贴必须**显式拒绝**（不伪造成功）。"""
    _install_http(monkeypatch, LOGIN_ROUTES)
    engine = LoginEngine(root=tmp_path / "accounts")
    session = await engine.start(buddy.PRODUCT)
    with pytest.raises(NotImplementedError, match="external_link"):
        await engine.callback(buddy.PRODUCT, session.id, {"code": "x"})


# ============ 签到（幂等 + precheck）============

async def test_claim_already_done_on_http400_code_10001(monkeypatch):
    """🔴 幂等判据 = **HTTP 400 + 业务码 10001** → `already_done`，**不是失败**。"""
    _install_http(monkeypatch, {
        "/v2/billing/meter/checkin-activity-status": (200, {"code": 0, "data": {
            "active": True, "today_checked_in": False}}),
        "/v2/billing/meter/daily-checkin": (400, {"code": 10001, "message": "今天已签到，请明天再来"}),
    })
    outcome = await buddy.claim(_CRED, buddy.meta(), precheck=True)
    assert outcome.category == "already_done" and "明天再来" in outcome.detail


async def test_claim_precheck_short_circuits_when_checked_in(monkeypatch):
    """precheck=True 且今日已签 → 直接 `already_done`，**不打领取端点**（省一次无效请求）。"""
    seen = _install_http(monkeypatch, {
        "/v2/billing/meter/checkin-activity-status": (200, {"code": 0, "data": {
            "active": True, "today_checked_in": True, "streak_days": 3}}),
        "/v2/billing/meter/daily-checkin": (200, {"code": 0, "data": {"credit": 100}}),
    })
    outcome = await buddy.claim(_CRED, buddy.meta(), precheck=True)
    assert outcome.category == "already_done" and "今天已签到" in outcome.detail
    assert [r.url.path for r in seen] == ["/v2/billing/meter/checkin-activity-status"]


async def test_claim_inactive_when_activity_closed(monkeypatch):
    """活动未开启 → `inactive`（正常业务状态）；同样不打领取端点。"""
    seen = _install_http(monkeypatch, {
        "/v2/billing/meter/checkin-activity-status": (200, {"code": 0, "data": {"active": False}}),
    })
    outcome = await buddy.claim(_CRED, buddy.meta(), precheck=True)
    assert outcome.category == "inactive" and "未开启" in outcome.detail
    assert len(seen) == 1


async def test_claim_success_reports_credit(monkeypatch):
    """code 0 + data.credit → `success`，detail 带上额度与连续天数。"""
    _install_http(monkeypatch, {
        "/v2/billing/meter/checkin-activity-status": (200, {"code": 0, "data": {
            "active": True, "today_checked_in": False}}),
        "/v2/billing/meter/daily-checkin": (200, {"code": 0, "data": {
            "credit": 100, "streak_days": 2, "is_streak_day": False}}),
    })
    outcome = await buddy.claim(_CRED, buddy.meta(), precheck=True)
    assert outcome.category == "success" and "100" in outcome.detail and "2" in outcome.detail


async def test_claim_status_failure_still_tries_claim(monkeypatch):
    """状态查询失败（None）**不代表不能领**：继续打领取端点，以响应体 code 定夺。"""
    seen = _install_http(monkeypatch, {
        "/v2/billing/meter/checkin-activity-status": (500, {"code": 500, "message": "boom"}),
        "/v2/billing/meter/daily-checkin": (200, {"code": 0, "data": {"credit": 1}}),
    })
    outcome = await buddy.claim(_CRED, buddy.meta(), precheck=True)
    assert outcome.category == "success"
    assert [r.url.path for r in seen] == ["/v2/billing/meter/checkin-activity-status",
                                          "/v2/billing/meter/daily-checkin"]


@pytest.mark.parametrize("status,body,expected", [
    (200, {"code": 1002, "message": "无资格"}, "inactive"),
    (200, {"code": 1003, "message": "活动结束"}, "inactive"),
    (200, {"code": 1001, "message": "已领取"}, "already_done"),
    (200, {"code": 9988, "message": "未知业务码"}, "failed"),
    (200, {"code": 0, "data": None}, "failed"),                    # code 0 但缺 data → 不谎报成功
    (502, None, "failed"),                                          # 非 JSON（网关 HTML 错误页）
])
async def test_claim_business_code_mapping(monkeypatch, status, body, expected):
    """业务码映射逐条对照 `credits.ts:382-417`；`precheck=False` 直连领取端点。"""
    route = _raw(status, "<html>error</html>") if body is None \
        else (status, body)
    _install_http(monkeypatch, {"/v2/billing/meter/daily-checkin": route})
    outcome = await buddy.claim(_CRED, buddy.meta(), precheck=False)
    assert outcome.category == expected, outcome.detail


async def test_claim_without_credential_fails_closed(monkeypatch):
    """⚠️ 凭据缺失 → `failed` + 明确原因，**不发请求**（fail closed，§22.8-5）。"""
    seen = _install_http(monkeypatch, {})
    outcome = await buddy.claim({}, buddy.meta(), precheck=True)
    assert outcome.category == "failed" and "access_token" in outcome.detail
    assert seen == []


# ============ 额度三态 ============

async def test_quota_available_excludes_expired_packages(monkeypatch):
    """有效包计入本周期余额；`Status=3` 的失效包**不并入**（`credits.ts:511-520`）。"""
    _install_http(monkeypatch, BALANCE_ROUTES)
    snapshot = await buddy.quota(_CRED, buddy.meta())
    assert snapshot.state == "available" and snapshot.source == "buddy-billing"
    assert "100.5" in snapshot.detail and "失效包" in snapshot.detail


async def test_quota_exhausted_when_all_active_packages_are_zero(monkeypatch):
    """查询成功且有效包余额为 0 → `exhausted`（**真的为 0**，与 unknown 分开）。"""
    _install_http(monkeypatch, {"/v2/billing/meter/get-user-resource": (200, {"code": 0, "data": {
        "Response": {"Data": {"Accounts": [
            {"PackageName": "P", "Status": 0, "CycleCapacityRemain": 0}]}}}})})
    snapshot = await buddy.quota(_CRED, buddy.meta())
    assert snapshot.state == "exhausted"


async def test_quota_expired_only_counts_as_exhausted_not_available(monkeypatch):
    """只剩失效包的额度 → `exhausted`（≠ available），失效额度写进 detail 供核对。"""
    _install_http(monkeypatch, {"/v2/billing/meter/get-user-resource": (200, {"code": 0, "data": {
        "Response": {"Data": {"Accounts": [
            {"PackageName": "P", "Status": 3, "CycleCapacityRemain": 500}]}}}})})
    snapshot = await buddy.quota(_CRED, buddy.meta())
    assert snapshot.state == "exhausted" and "500" in snapshot.detail


@pytest.mark.parametrize("route", [
    _raise(httpx.ConnectError, "down"),                  # 网络不可达
    (500, {"code": 500, "message": "boom"}),             # 服务端错误
    (200, {"code": 403, "message": "forbidden"}),        # 业务层拒绝
    (200, {"code": 0, "data": {}}),                      # 结构缺失（嵌套层不对）
    _raw(200, "<html>gateway error</html>"),             # 非 JSON（网关 HTML 错误页）
])
async def test_quota_unknown_never_zero(monkeypatch, route):
    """🔴 查不动/结构变更一律 `unknown` —— **未知不当零**（§22.3 / `23 B2`）。"""
    _install_http(monkeypatch, {"/v2/billing/meter/get-user-resource": route})
    assert (await buddy.quota(_CRED, buddy.meta())).state == "unknown"


async def test_quota_without_credential_is_unknown_without_request(monkeypatch):
    """凭据缺失 → unknown 且**不发请求**（不拿"没登录"当"没有额度"）。"""
    seen = _install_http(monkeypatch, {})
    snapshot = await buddy.quota({}, buddy.meta())
    assert snapshot.state == "unknown" and seen == []


# ============ 探活（两维）============

async def test_probe_valid_when_business_code_zero(monkeypatch):
    """两维都成立才 `ok`（§22.3）。"""
    _install_http(monkeypatch, BALANCE_ROUTES)
    result = await buddy.probe(_CRED, buddy.meta())
    assert result.reachable and result.valid and result.ok


@pytest.mark.parametrize("status,expected", [(401, False), (403, False), (500, False)])
async def test_probe_reachable_but_invalid(monkeypatch, status, expected):
    """拿到了响应 = 连通；被 401/403 拒绝 = 凭据无效 —— **两维分开**。"""
    _install_http(monkeypatch, {"/v2/billing/meter/get-user-resource":
                                (status, {"code": status, "message": "nope"})})
    result = await buddy.probe(_CRED, buddy.meta())
    assert result.reachable is True and result.valid is expected


async def test_probe_html_response_is_not_valid(monkeypatch):
    """HTTP 200 但响应是 HTML（网关错误页）→ **不得**判「凭据有效」（`code_of(None)` 是 0，易误判）。"""
    _install_http(monkeypatch, {"/v2/billing/meter/get-user-resource":
                                _raw(200, "<html>error</html>")})
    result = await buddy.probe(_CRED, buddy.meta())
    assert result.reachable is True and result.valid is False


async def test_probe_unreachable_is_not_valid(monkeypatch):
    """连不上 → reachable=False（此时 valid 亦不成立）。"""
    _install_http(monkeypatch, {"/v2/billing/meter/get-user-resource":
                                _raise(httpx.ConnectTimeout, "timeout")})
    result = await buddy.probe(_CRED, buddy.meta())
    assert result.reachable is False and result.ok is False


async def test_probe_without_credential_fails_closed(monkeypatch):
    """凭据缺失 → 两维皆假且**不发请求**。"""
    seen = _install_http(monkeypatch, {})
    result = await buddy.probe({}, buddy.meta())
    assert not result.reachable and not result.valid and seen == []


# ============ 续期 ============

async def test_refresh_merges_new_token_and_keeps_unreturned_fields(monkeypatch):
    """续期成功：新令牌写回；**响应未回 refresh_token 时保留旧值**（不丢续期能力）。"""
    seen = _install_http(monkeypatch, {"/v2/plugin/auth/token/refresh": (200, {"code": 0, "data": {
        "accessToken": _jwt({"iat": IAT + 3600, "exp": IAT + 7200}),
        "expiresIn": 3600, "tokenType": "Bearer"}})})
    merged = await buddy.refresh(dict(_CRED, expires_at="old"), buddy.meta())
    assert merged["refresh_token"] == REFRESH and merged["user_id"] == "u-1"
    assert merged["access_token"] != ACCESS
    assert merged["expires_at"] == str((IAT + 3600) * 1000 + 3600 * 1000)
    request = seen[0]
    assert request.headers["X-Refresh-Token"] == REFRESH            # buddy.ts:80
    assert request.headers["X-Auth-Refresh-Source"] == "ide-main"    # buddy.ts:95
    assert request.headers["X-Domain"] == "copilot.tencent.com"


async def test_refresh_without_refresh_token_is_not_refreshable(monkeypatch):
    """无 `refresh_token` → `NotRefreshable`（**不是**异常故障、不触发冷却，§22.3）。"""
    seen = _install_http(monkeypatch, {})
    with pytest.raises(NotRefreshable, match="refresh_token"):
        await buddy.refresh({"access_token": ACCESS}, buddy.meta())
    assert seen == []


async def test_refresh_rejected_token_is_not_refreshable(monkeypatch):
    """`refresh_token` 被判定失效（401）→ `NotRefreshable`（停止重试，`buddy-oauth.ts:312-324`）。"""
    _install_http(monkeypatch, {"/v2/plugin/auth/token/refresh":
                                (401, {"code": 401, "message": "refresh token expired"})})
    with pytest.raises(NotRefreshable, match="expired"):
        await buddy.refresh(dict(_CRED), buddy.meta())


async def test_refresh_server_error_is_retryable(monkeypatch):
    """5xx → 普通异常（可重试），**不得**误判成「不可续期」。"""
    _install_http(monkeypatch, {"/v2/plugin/auth/token/refresh":
                                (503, {"code": 503, "message": "busy"})})
    with pytest.raises(RuntimeError, match="HTTP 503"):
        await buddy.refresh(dict(_CRED), buddy.meta())


async def test_refresh_never_writes_empty_token(monkeypatch):
    """响应缺 accessToken → 异常（**绝不把空令牌交回落盘**，`expiry-sync.ts:201-206`）。"""
    _install_http(monkeypatch, {"/v2/plugin/auth/token/refresh":
                                (200, {"code": 0, "data": {"refreshToken": "RT-2"}})})
    with pytest.raises(RuntimeError, match="accessToken"):
        await buddy.refresh(dict(_CRED), buddy.meta())


# ============ 模型目录 ============

CONFIG_ROUTES = {"/v3/config": (200, {"code": 0, "data": {
    "agents": [
        {"name": "craft", "models": ["deepseek-v4.1-flash", "auto", "hy4-preview-f"]},
        {"name": "cli", "models": ["deepseek-v4.1-flash", "glm-5.3"]},
    ],
    "models": [
        {"id": "deepseek-v4.1-flash", "name": "Deepseek-V4.1-Flash(远端)",
         "maxInputTokens": 999_999, "maxOutputTokens": 128_000,
         "reasoning": {"supportedEfforts": ["low", "medium"]}},
        {"id": "glm-5.3", "name": "GLM-5.3"},
        {"id": "auto", "name": "Auto"},
        {"id": "nes-completion", "name": "补全"},                       # 补全专用 → 过滤
        {"id": "hunyuan-image-alpha", "name": "图", "tags": ["text-to-image"]},  # 生图 → 过滤
        {"id": "tiny-completion", "name": "极小", "maxOutputTokens": 128},       # ≤256 → 过滤
    ],
    "productFeaturesConfig": {"ModelTrialBanner": {"banners": [
        {"targetModelId": "hy4-preview-f"}]}},
}})}


async def test_list_models_merges_fallback_base_with_remote_priority(monkeypatch):
    """兜底表定集合与顺序，远端逐字段优先；被 agent 引用/试用下发的模型追加在尾。"""
    seen = _install_http(monkeypatch, CONFIG_ROUTES)
    models = await buddy.list_models(_CRED, buddy.meta())
    by_id = {m.id: m for m in models}

    # 集合 = 兜底表（16）+ 追加的 agent 引用模型（hy4-preview-f：只由 /v3/config 下发，
    # 这正是 DSH 那条真实缺陷 —— 纯白名单重建会把它丢掉，`buddy-adapter.ts:890-899`）
    assert [m.id for m in models[:len(FALLBACK_IDS)]] == FALLBACK_IDS
    assert [m.id for m in models[len(FALLBACK_IDS):]] == ["hy4-preview-f"]
    assert "nes-completion" not in by_id and "tiny-completion" not in by_id
    assert "hunyuan-image-alpha" not in by_id and "auto" not in by_id
    # 远端优先：名字与上下文窗口取远端值；远端缺的字段由兜底表补位
    dsf = by_id["deepseek-v4.1-flash"]
    assert dsf.name == "Deepseek-V4.1-Flash(远端)" and dsf.context_window == 999_999
    assert dsf.effort_levels == ("low", "medium")           # 远端 supportedEfforts 覆盖兜底
    assert by_id["glm-5.3"].max_output == 64_000            # 远端未声明 → 兜底表补位
    assert by_id["glm-5.3"].context_window == 1_000_000
    # 追加项排在末尾（不打乱已熟悉的顺序）
    assert models[-1].id == "hy4-preview-f"
    assert seen[0].url.path == "/v3/config"
    assert seen[0].headers["X-Product-Code"] == "codebuddy"  # buddy-oauth.ts:363


async def test_list_models_without_credential_uses_static_table(monkeypatch):
    """无凭据 / 远端失败 → 兜底表（`product.ts:126-135`：它是 IDE 内置静态目录）。"""
    seen = _install_http(monkeypatch, {})
    models = await buddy.list_models({}, buddy.meta())
    assert len(models) == len(FALLBACK_IDS) and seen == []
    assert [m.id for m in models][:3] == ["hy4-preview", "hy3", "hy3-x"]
    assert all(m.tool_call is None for m in models)          # 取不到不编造
    assert models[0].effort_levels == ("high",)               # product.ts:182-184


async def test_list_models_remote_failure_falls_back(monkeypatch):
    """远端 5xx → 兜底表（不抛异常，目录面保持可用）。"""
    _install_http(monkeypatch, {"/v3/config": (502, {"code": 502, "message": "bad gateway"})})
    models = await buddy.list_models(_CRED, buddy.meta())
    assert len(models) == len(buddy._CODEBUDDY_FALLBACK_MODELS)


# ============ 出站适配（M6-5a 接线）============

def test_build_out_is_wired_to_the_family_adapter():
    """`build_out` 自 M6-5a 起接线（原 M6-5 TODO 护栏在此**按波次转正**）：
    返回 CodeBuddy 系出站适配器，路径 = 取证值 `/v2/chat/completions`。

    行为判据（头/体/端到端）在 `tests/unit/test_product_out.py` 与
    `tests/integration/test_buddy_out.py`；本用例只钉"接线本身成立"。
    """
    from model_gateway.adapters.product_out import ProductAccount
    from model_gateway.upstream.buddy.out import BuddyFamilyOut

    account = ProductAccount(product=buddy.PRODUCT, name="acc-1",
                             base_url="https://copilot.tencent.com")
    adapter = buddy.build_out(account)
    assert isinstance(adapter, BuddyFamilyOut)
    assert (adapter.product, adapter.account_ref) == ("buddy", "acc-1")
    assert adapter.chat_path == "/v2/chat/completions"
    assert adapter.base_url == "https://copilot.tencent.com"


# ============ 推理面身份头（M6-F3 修复：与 DSH 取证对齐）============

_CRED_WITH_IDS = {"access_token": ACCESS, "user_id": "u-1", "enterprise_id": "ent-9"}


def test_inference_headers_send_attribution_name_not_deployment_type():
    """🔴 推理面 `X-Product` 发**归属名**、`X-IDE-*` 按已取证取值发出（F3 修正）。

    证据（DSH 只读源逐行核过，行号已校准）：
    - `buddy-adapter.ts:1564-1581`（`send()`）：`X-Product` = `product.attributionName`
      （`:1577`），并在 `:1570-1572` 注明「历史实现发成 `SaaS` 导致后台归因不到产品」；
    - 取值：buddy `product.ts:278-279`（`'CodeBuddy'` / `'1.106.1'`）、
      workbuddy `product.ts:401-402`（`'WorkBuddy'` / `'5.5.2'`）；
    - 归属头族（`buddy-adapter.ts:1573-1577`）：`X-Agent-Purpose: conversation`、
      `X-IDE-Name`/`X-IDE-Type` = 归属名、`X-IDE-Version` = 客户端形态版本号；
      缺任一个后台「使用端」列显示 `-`（`:1570`）；
    - 对照：`X-Product: SaaS` 出自**计费面** `credits.ts:236`（另一面，不得套用到推理面）。

    红证（撤修复）：把 `inference_headers` 的 `HEADER_PRODUCT` 换回 `DEPLOYMENT_TYPE`、
    或删掉三个 `X-IDE-*` → 本用例必红。
    """
    from model_gateway.upstream.buddy import protocol as p

    headers = p.inference_headers(buddy._PROFILE, _CRED_WITH_IDS,
                                  domain="copilot.tencent.com")
    assert headers[p.HEADER_PRODUCT] == "CodeBuddy"              # product.ts:278
    assert headers[p.HEADER_IDE_NAME] == "CodeBuddy"             # buddy-adapter.ts:1574
    assert headers[p.HEADER_IDE_TYPE] == "CodeBuddy"             # :1575
    assert headers[p.HEADER_IDE_VERSION] == "1.106.1"            # :1576 + product.ts:279
    assert headers[p.HEADER_AGENT_PURPOSE] == "conversation"     # :1573
    assert headers[p.HEADER_PRODUCT_CODE] == "codebuddy"         # :1569
    assert headers[p.HEADER_DOMAIN] == "copilot.tencent.com"     # :1568
    assert headers["Authorization"].startswith("Bearer ")
    # 计费面专属头**不得**出现在推理面（DSH 的 `send()` 不发，`:1564-1581`；混面 = F3 的形态）
    assert "X-User-Id" not in headers and "X-Enterprise-Id" not in headers

    from dataclasses import replace

    from model_gateway.upstream.workbuddy import product as workbuddy
    wb = p.inference_headers(workbuddy._PROFILE, _CRED_WITH_IDS, domain="www.workbuddy.ai")
    assert wb[p.HEADER_PRODUCT] == "WorkBuddy"                   # product.ts:401
    assert wb[p.HEADER_IDE_VERSION] == "5.5.2"                   # product.ts:402

    # 计费面（`identity_headers`）**保持**部署类型口径 —— 两个面各有各的取值，
    # 本次修正只动推理面（`credits.ts:236` 一行未改）
    billing = p.identity_headers(buddy._PROFILE, _CRED_WITH_IDS)
    assert billing[p.HEADER_PRODUCT] == "SaaS" and "X-IDE-Name" not in billing

    # 未登记的档案 → 当场拒绝（fail closed：编个归属名 = 把用量记到别人头上）
    with pytest.raises(ValueError, match="未登记推理面归属头"):
        p.inference_headers(replace(buddy._PROFILE, id="ghost"), _CRED_WITH_IDS)
