"""`raccoon` 产品钩子单测（tech-design v2.0 §22.4 行；`20 §2.7/§3.1/§4.1`、`21 §1.1`）。

🔴 假上游（`httpx.MockTransport`）：**无网络、无真实凭据**。逐条对应取证判据：

- 扫码登录：`code` **本地随机生成**（32 位 hex，服务端接受自造值）+ **服务端出 PNG 图**
  （M7-C1：`qr_payload` 是图片 data URI、`url` 才是内容串）→ 轮询
  `login_with_qrcode_code`；`pending`/`logging`/未知状态都是 `pending`（**不是错误**），
  `success` 却缺 `access_token` 仍算 `pending`，`canceled` → **就地换发新码继续 pending**；
- 短信路径（备选形态）：手机号 **AES-128-CFB 加密**（解密回环断言）+ 图形验证码失败文案；
- **登录奖励**（`claim_onboarding`）：判据 = 响应体 `granted`；**必需 `X-Client-Platform` 头**
  （断言请求头）；`precheck` 走**只读**账单反查且「注册礼包不算登录奖励」；
- 额度三态（**未知不当零**：网络/HTTP/HTML/业务码/缺字段 全部 `unknown`）；
- 模型目录：远端过滤 `visible:false` + 倍率进展示名 + `context_window` 字段回退；
  取不到 → 6 条兜底表（逐条比对 id/name，**不编造**）；
- `claim` 不可用语义：`inactive` + 可读原因 + **零上游请求**（每日 300 分服务端自动发放）；
- 契约表：10 钩子齐全、`login_callback`/`build_out` 显式 `NotImplementedError`。

⚠️ 判据里出现的模型 id / 数值都是**假上游数据**（与真上游无关），只有**契约**（端点路径、
状态映射、请求头、字段名、展示名格式）照 DSH 取证。
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import re
import urllib.parse
from types import SimpleNamespace

import httpx
import pytest

from model_gateway.accounts import net, qr, registry, store
from model_gateway.accounts.login import LoginEngine
from model_gateway.accounts.types import NotRefreshable
from model_gateway.upstream.raccoon import const as C
from model_gateway.upstream.raccoon import product as raccoon
from model_gateway.upstream.raccoon import protocol as p

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
            return httpx.Response(404, json={"code": 404, "message": "no route",
                                             "path": request.url.path})
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

    def json_of(self, path: str, index: int = 0) -> dict:
        return json.loads(self.requests_for(path)[index].content.decode())

    def headers_of(self, path: str, index: int = 0) -> httpx.Headers:
        return self.requests_for(path)[index].headers


def _patch_client(monkeypatch, upstream: FakeUpstream) -> None:
    """把 `accounts/net.py::make_client` 换成本用例的假上游。

    产品层的每个模块都经 `net.make_client` 建客户端（单一注入点，不在各调用点留后门）。
    """

    def factory(*, base_url="", headers=None, timeout=None, follow_redirects=True):
        return httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler),
                                 base_url=base_url, headers=headers or {})

    monkeypatch.setattr(net, "make_client", factory)


def _session(**state) -> SimpleNamespace:
    """会话替身：钩子只许经 `session.state` 存私态（不进 Challenge / Outcome.detail）。"""
    return SimpleNamespace(state=dict(state), product="raccoon", name="raccoon-test0001")


def _jwt(exp: int) -> str:
    """造一个只有 payload 可解析的 JWT（本层只解 exp、不验签，`raccoon.ts:115-129`）。"""
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{payload}.sig"


def _cred(**over) -> dict:
    return {"access_token": _jwt(2_000_000_000), "refresh_token": "r-old",
            "expires_at": "2000000000000", **over}


def _envelope(data: dict | None = None, *, code: int = 0, message: str = "") -> httpx.Response:
    body: dict = {"code": code, "message": message}
    if data is not None:
        body["data"] = data
    return httpx.Response(200 if code == 0 else 400, json=body)


# ============ 扫码登录（主形态）============


async def test_qr_start_generates_code_locally_and_emits_scannable_png(monkeypatch):
    """第一步：本地生成 32 位 hex code（实测服务端接受自造值）→ **服务端出图**，零网络请求。

    🔴 M7-C1 的字段分工（缺陷钉桩，见下面那条 `_bare_url` 判据）：
      · `Challenge.url` = 二维码**内容**（与 DSH `raccoon-oauth.ts:127-130` 逐字同形，可复制）；
      · `Challenge.qr_payload` = 那段内容的 **PNG data URI**（`accounts/qr.py`，byte 模式 / EC M
        / 版本 ≤10），不再是同一条 URL。
    """
    upstream = FakeUpstream({})
    _patch_client(monkeypatch, upstream)
    session = _session()

    challenge = await raccoon.login_start(session)
    code = session.state["qr_code"]
    assert len(code) == 32 and code == code.lower()
    assert all(ch in "0123456789abcdef" for ch in code)
    # 内容形态 = 微信登录页 + code + appname（`raccoon-oauth.ts:127-130`，一个字节都没改）
    assert challenge.url == f"{C.API_BASE}{C.QR_PAGE_PATH}?code={code}&" + \
        f"appname={urllib.parse.quote(C.QR_PAGE_APPNAME)}"
    assert "appname=" in challenge.url
    assert challenge.device_code == "" and challenge.sms_sent is False
    # 图片：data URI，且**就是**上面那条内容的正规编码（同参数重跑逐字节相同）
    assert challenge.qr_payload.startswith("data:image/png;base64,")
    assert challenge.qr_payload == qr.png_data_uri(challenge.url)
    assert challenge.qr_payload != challenge.url
    assert upstream.calls == []                                  # 出图是本地计算，不打上游


async def test_qr_start_payload_is_an_image_not_a_bare_url_regression():
    """🔴 钉住本轮缺陷：`qr_payload` 只要退化成"光秃秃的一条 URL"（本轮之前的形态）就判红。

    旧实现 `Challenge(url=url, qr_payload=url)`：前端没有二维码编码器，于是向导把这条 URL
    印成一行文字让用户"用手机扫一扫"——**什么都扫不出来**。现在图片必须在 `qr_payload` 里，
    文字内容留在 `url`（复制兜底），两者不得再是同一个东西。
    """
    challenge = await raccoon.login_start(_session())
    assert not re.fullmatch(r"(https?|ftp)://\S+", challenge.qr_payload), \
        f"回归：qr_payload 又是一条裸 URL（{challenge.qr_payload[:60]}…）——界面只能印文字"
    assert challenge.qr_payload.startswith("data:image/"), "qr_payload 必须是图片 data URI"
    assert challenge.qr_payload != challenge.url, "qr_payload 与 url 同值 = 旧缺陷形态"



async def test_qr_poll_pending_then_success_via_engine(tmp_path, monkeypatch):
    """轮询：`pending` → `logging` → `success`（经**入口层实际路径**落盘凭据，§22.3）。"""
    upstream = FakeUpstream({
        C.LOGIN_QRCODE_PATH: [
            _envelope({"status": "pending"}),
            _envelope({"status": "logging", "expired_at": "2026-09-29T05:23:47Z"}),
            _envelope({"status": "success", "access_token": _jwt(1_800_000_000),
                       "refresh_token": "r-new"}),
        ],
        C.USER_INFO_PATH: _envelope({"id": "u-1", "name": "RaccoonAva",
                                     "phone": "13800138000", "office_identity": ""}),
    })
    _patch_client(monkeypatch, upstream)
    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)

    session = await engine.start("raccoon")
    assert session.name.startswith("raccoon-")           # 默认名 `{product}-{8hex}`
    assert (await engine.poll("raccoon", session.id)).state == "pending"
    assert (await engine.poll("raccoon", session.id)).state == "pending"   # logging 也是 pending
    assert store.load_credentials("raccoon", session.name, root=root) == {}  # pending 不落盘

    outcome = await engine.poll("raccoon", session.id)
    assert outcome.state == "success"
    assert not store.has_account(root, session.name), "success 只暂存（M7-E 两阶段提交）"
    assert (await engine.commit_pending(session.id))["committed"] is True
    stored = store.load_credentials("raccoon", session.name, root=root)
    assert stored["access_token"] == _jwt(1_800_000_000)
    assert stored["refresh_token"] == "r-new"
    # expires_at 由 JWT 的 exp 推算（毫秒时间戳字符串，`raccoon-oauth.ts:245-250`）
    assert stored["expires_at"] == str(1_800_000_000 * 1000)
    assert stored["phone"] == "13800138000"              # 多账号消歧字段（登录后补全）
    assert "office_identity" not in stored               # 空串不写（个人账号）
    meta = store.load_meta(root, session.name)
    assert meta["via"] == "login"
    assert meta["nickname"] == "RaccoonAva (8000)"       # `jet-hub-rpc.ts:251-270`
    # 确认落盘后出表（内存有界）
    assert (await engine.poll("raccoon", session.id)).state == "expired"

    # 轮询请求体 = {"qrcode_code": <会话里的 code>}；登录端点**不带** Authorization
    # （`raccoon-oauth.ts:83-93` 的 postJson 只加 Content-Type）
    body = upstream.json_of(C.LOGIN_QRCODE_PATH)
    assert body == {"qrcode_code": session.state["qr_code"]}
    assert "Authorization" not in upstream.headers_of(C.LOGIN_QRCODE_PATH)
    assert upstream.headers_of(C.LOGIN_QRCODE_PATH)["Content-Type"] == "application/json"


async def test_qr_poll_success_without_access_token_stays_pending(monkeypatch):
    """`success` 却缺 `access_token` → 仍 `pending`（否则产出空凭据卡死，`raccoon-oauth.ts:169-170`）。"""
    upstream = FakeUpstream({C.LOGIN_QRCODE_PATH: _envelope({"status": "success"})})
    _patch_client(monkeypatch, upstream)
    outcome = await raccoon.login_poll(_session(qr_code="ab" * 16))
    assert outcome.state == "pending" and outcome.credentials == {}


async def test_qr_poll_canceled_reissues_a_fresh_code_and_image(monkeypatch):
    """`canceled`（用户在微信里取消）→ **就地换发新 code + 新图**，会话继续 pending。

    照抄 DSH 的本地页处置（`raccoon-login-page.ts:213-220`：`canceled` 时换新二维码，
    注释原话"否则用户卡死"）。M7-C1 之前的本层实现是判 `expired` 终态 + 要用户手点
    「重新发起登录」，本轮改成与 DSH 的用户可见行为一致。
    """
    upstream = FakeUpstream({C.LOGIN_QRCODE_PATH: [
        _envelope({"status": "canceled"}), _envelope({"status": "pending"})]})
    _patch_client(monkeypatch, upstream)
    session = _session(qr_code="ab" * 16, qr_reissues=0)
    session.challenge = None

    outcome = await raccoon.login_poll(session)
    assert outcome.state == "pending" and "换发" in outcome.detail, outcome.detail
    assert outcome.credentials == {}
    new_code = session.state["qr_code"]
    assert new_code != "ab" * 16 and len(new_code) == 32, "旧码已作废，必须换发新 code"
    assert session.state["qr_reissues"] == 1
    # 新图写回会话（入口层在 `login/poll` 的响应里带回 → 界面自动换图）
    assert session.challenge is not None
    assert session.challenge.url == p.qr_login_url(new_code)
    assert session.challenge.qr_payload.startswith("data:image/png;base64,")
    assert "abab" not in json.dumps(vars(session.challenge)), "旧码不得还留在展示物里"
    # 下一轮打的是**新 code**（不是拿作废的旧码继续徒劳查询）
    await raccoon.login_poll(session)
    assert upstream.json_of(C.LOGIN_QRCODE_PATH, 1) == {"qrcode_code": new_code}


async def test_qr_reissue_cap_reports_expired_instead_of_reforging_forever(monkeypatch):
    """换发次数到上限 → 如实 `expired` 请用户重新发起（不无限重铸一张没人扫的码）。"""
    upstream = FakeUpstream({C.LOGIN_QRCODE_PATH: _envelope({"status": "canceled"})})
    _patch_client(monkeypatch, upstream)
    session = _session(qr_code="ab" * 16, qr_reissues=qr.MAX_REISSUES)

    outcome = await raccoon.login_poll(session)
    assert outcome.state == "expired" and "上限" in outcome.detail, outcome.detail
    assert session.state["qr_reissues"] == qr.MAX_REISSUES      # 不再换发
    assert len(upstream.requests_for(C.LOGIN_QRCODE_PATH)) == 1  # 只打了那一次判定



@pytest.mark.parametrize("route", [
    httpx.Response(500, json={"code": 500, "message": "boom"}),       # 服务端故障
    httpx.Response(200, text="<html>gateway error</html>"),          # HTML 错误页（非 JSON）
    _envelope({"status": "pending"}, code=1, message="业务码非零"),   # 业务码非零
    _envelope({"status": "some-new-status"}),                        # 未知状态
    httpx.ConnectError("network down"),                              # 传输层失败
])
async def test_qr_poll_degrades_to_pending(monkeypatch, route):
    """轮询噪声一律 `pending`（照抄 `raccoon-oauth.ts:132-139`）：偶发失败不该中断登录流程。"""
    upstream = FakeUpstream({C.LOGIN_QRCODE_PATH: route})
    _patch_client(monkeypatch, upstream)
    outcome = await raccoon.login_poll(_session(qr_code="ab" * 16))
    assert outcome.state == "pending"
    assert outcome.credentials == {} and outcome.meta == {}


async def test_qr_poll_without_code_fails_without_request(monkeypatch):
    """缺会话私态（`login_start` 未成功）→ 显式失败，**不打上游**。"""
    upstream = FakeUpstream({})
    _patch_client(monkeypatch, upstream)
    outcome = await raccoon.login_poll(_session())
    assert outcome.state == "failed" and "二维码" in outcome.detail
    assert upstream.calls == []


# ============ 短信登录（备选形态，`login_alt=("sms_code",)`）============


def _decrypt_phone(payload_b64: str) -> str:
    """按 DSH 算法解回手机号（独立实现，用于验证加密确为 AES-128-CFB + iv‖ct 布局）。"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

    from model_gateway.upstream.raccoon.protocol import _cfb_mode

    blob = base64.b64decode(payload_b64)
    iv, body = blob[:16], blob[16:]
    decryptor = Cipher(algorithms.AES(C.PHONE_CIPHER_SECRET.encode("utf-8")),
                       _cfb_mode(iv)).decryptor()
    return (decryptor.update(body) + decryptor.finalize()).decode("utf-8")


async def test_sms_send_encrypts_phone_and_passes_captcha(monkeypatch):
    """发码：手机号 **AES-128-CFB 加密**（解密回环）+ `nation_code=86` + 图形验证码透传。"""
    upstream = FakeUpstream({C.SEND_SMS_PATH: _envelope({})})
    _patch_client(monkeypatch, upstream)
    session = _session()

    challenge = await raccoon.sms_send(session, phone="13800138000", captcha_param="CAP-1")
    assert challenge.sms_sent is True
    body = upstream.json_of(C.SEND_SMS_PATH)
    assert body["nation_code"] == "86" and body["captcha_param"] == "CAP-1"
    assert body["phone"] != "13800138000"
    assert _decrypt_phone(body["phone"]) == "13800138000"     # 加密正确（不是"看起来像加密"）
    assert session.state["sms_phone"] == "13800138000"        # 只在发送成功后记住手机号


@pytest.mark.parametrize("phone", ["", "12345", "23800138000", "1380013800"])
async def test_sms_send_rejects_invalid_phone_without_request(monkeypatch, phone):
    """手机号形态（`raccoon-login-page.ts:229` 同款判据）→ 本地即拒，不打上游。"""
    upstream = FakeUpstream({})
    _patch_client(monkeypatch, upstream)
    with pytest.raises(RuntimeError, match="11 位"):
        await raccoon.sms_send(_session(), phone=phone, captcha_param="CAP")
    assert upstream.calls == []


async def test_sms_send_captcha_failure_is_actionable(monkeypatch):
    """图形验证码失败（业务码 `100006`）→ 可读文案，且**不**记手机号（`raccoon-oauth.ts:204-208`）。"""
    upstream = FakeUpstream({C.SEND_SMS_PATH: _envelope(code=C.CODE_CAPTCHA_VERIFY_ERROR,
                                                        message="captcha_verify_error")})
    _patch_client(monkeypatch, upstream)
    session = _session()
    with pytest.raises(RuntimeError, match="图形验证码校验失败"):
        await raccoon.sms_send(session, phone="13800138000", captcha_param="bad")
    assert "sms_phone" not in session.state


async def test_sms_send_phone_encrypt_error_is_surfaced(monkeypatch):
    """`100003 params_encryted_error` 单列文案：本地 AES 实现若与客户端漂移，这里是唯一信号。"""
    upstream = FakeUpstream({C.SEND_SMS_PATH: _envelope(code=C.CODE_PHONE_ENCRYPT_ERROR,
                                                        message="params_encryted_error")})
    _patch_client(monkeypatch, upstream)
    with pytest.raises(RuntimeError, match="100003"):
        await raccoon.sms_send(_session(), phone="13800138000", captcha_param="CAP")


async def test_sms_submit_preconditions_and_success(monkeypatch):
    """提交验证码：未先发码 → failed；成功 → 凭据（含手机号）+ 昵称消歧；失败 → 可读原因。"""
    upstream = FakeUpstream({
        C.SEND_SMS_PATH: _envelope({}),
        C.LOGIN_SMS_PATH: [
            _envelope(code=400, message="sms_code_invalid"),
            _envelope({"access_token": _jwt(1_900_000_000), "refresh_token": "r-sms"}),
        ],
        C.USER_INFO_PATH: _envelope({"id": "u-2", "name": "RaccoonBob", "phone": "13900139000"}),
    })
    _patch_client(monkeypatch, upstream)

    # ① 未先发码 → 本地拒绝（`raccoon-login-page.ts:253-257`）
    fresh = _session()
    early = await raccoon.sms_submit(fresh, sms_code="123456")
    assert early.state == "failed" and "请先获取手机验证码" in early.detail
    # ② 空验证码
    session = _session(sms_phone="13900139000")
    assert (await raccoon.sms_submit(session, sms_code="  ")).state == "failed"
    # ③ 服务端拒绝 → failed（原因来自服务端）
    bad = await raccoon.sms_submit(session, sms_code="000000")
    assert bad.state == "failed" and "sms_code_invalid" in bad.detail
    # ④ 成功：手机号加密提交 + 凭据落盘形态（手机号保留，昵称带尾号）
    ok = await raccoon.sms_submit(session, sms_code="123456")
    assert ok.state == "success"
    assert ok.credentials["refresh_token"] == "r-sms"
    assert ok.credentials["phone"] == "13900139000"
    assert ok.meta["nickname"] == "RaccoonBob (9000)"
    assert _decrypt_phone(upstream.json_of(C.LOGIN_SMS_PATH, 1)["phone"]) == "13900139000"


# ============ 登录奖励（claim_onboarding，一次性 3000 分）============


async def test_claim_onboarding_granted_with_required_platform_header(monkeypatch):
    """`granted:true` → success；**必需 `X-Client-Platform` 头**（`raccoon-credits.ts:87-90,171-173`）。"""
    upstream = FakeUpstream({C.LOGIN_POINTS_GRANT_PATH: _envelope(
        {"granted": True, "popup": {"points": 3000}})})
    _patch_client(monkeypatch, upstream)

    outcome = await raccoon.claim_onboarding(_cred(), raccoon.meta(), precheck=False)
    assert outcome.category == "success" and "3000" in outcome.detail
    headers = upstream.headers_of(C.LOGIN_POINTS_GRANT_PATH)
    assert headers["X-Client-Platform"] == C.client_platform()
    assert headers["X-Client-Platform"] in {C.PLATFORM_WINDOWS, C.PLATFORM_MACOS, C.PLATFORM_LINUX}
    assert headers["X-Client-Version"] == C.CLIENT_VERSION
    assert headers["Authorization"].startswith("Bearer ")
    assert headers["X-Raccoon-Language"] == "zh"
    assert upstream.requests_for(C.LOGIN_POINTS_GRANT_PATH)[0].method == "POST"


async def test_claim_onboarding_granted_without_popup_uses_default_points(monkeypatch):
    """`granted:true` 但无 `popup.points` → 用取证过的默认额度 3000（不编造别的数）。"""
    upstream = FakeUpstream({C.LOGIN_POINTS_GRANT_PATH: _envelope({"granted": True})})
    _patch_client(monkeypatch, upstream)
    outcome = await raccoon.claim_onboarding(_cred(), raccoon.meta(), precheck=False)
    assert outcome.category == "success" and str(C.LOGIN_REWARD_POINTS) in outcome.detail


async def test_claim_onboarding_granted_false_is_already_done(monkeypatch):
    """幂等判据 = `granted`：重复领取回 `granted:false` → `already_done`（正常状态，非失败）。"""
    upstream = FakeUpstream({C.LOGIN_POINTS_GRANT_PATH: _envelope({"granted": False})})
    _patch_client(monkeypatch, upstream)
    outcome = await raccoon.claim_onboarding(_cred(), raccoon.meta(), precheck=False)
    assert outcome.category == "already_done" and "已领取" in outcome.detail


@pytest.mark.parametrize("route,needle", [
    (_envelope(code=12345, message="service_error"), "service_error"),
    (httpx.Response(200, text="<html>oops</html>"), "不是 JSON"),
    (httpx.ConnectError("down"), "网络错误"),
])
async def test_claim_onboarding_failures_are_failed_not_fabricated(monkeypatch, route, needle):
    """业务码非零 / HTML / 网络 → `failed`（**唯一需要用户关注**的一类）。"""
    upstream = FakeUpstream({C.LOGIN_POINTS_GRANT_PATH: route})
    _patch_client(monkeypatch, upstream)
    outcome = await raccoon.claim_onboarding(_cred(), raccoon.meta(), precheck=False)
    assert outcome.category == "failed" and needle in outcome.detail


async def test_claim_onboarding_without_token_fails_without_request(monkeypatch):
    """无凭据 → `failed` + **零上游请求**（fail closed，不编造成功）。"""
    upstream = FakeUpstream({})
    _patch_client(monkeypatch, upstream)
    outcome = await raccoon.claim_onboarding({}, raccoon.meta(), precheck=False)
    assert outcome.category == "failed" and "access_token" in outcome.detail
    assert upstream.calls == []


async def test_claim_onboarding_precheck_reads_bills_and_skips_grant(monkeypatch):
    """`precheck=True` → **只读**账单反查（`reward_grant` + 「桌面端登录奖励」）→ 已领则不打写端点。"""
    upstream = FakeUpstream({C.BILLS_PATH: _envelope({"items": [
        {"biz_type": C.BILL_BIZ_REWARD_GRANT, "event_name": "新人注册礼包", "points": 3000},
        {"biz_type": C.BILL_BIZ_REWARD_GRANT, "event_name": C.LOGIN_REWARD_EVENT_NAME,
         "points": 3000},
    ]})})
    _patch_client(monkeypatch, upstream)

    outcome = await raccoon.claim_onboarding(_cred(), raccoon.meta(), precheck=True)
    assert outcome.category == "already_done"
    bills_request = upstream.requests_for(C.BILLS_PATH)[0]
    assert bills_request.method == "GET"
    assert bills_request.url.params["paging.limit"] == "50"
    assert upstream.requests_for(C.LOGIN_POINTS_GRANT_PATH) == []      # 写端点**未被触碰**


async def test_claim_onboarding_precheck_ignores_registration_bonus(monkeypatch):
    """「新人注册礼包」也是 `reward_grant`，**不得**算作登录奖励（`raccoon-credits.ts:221-224`）。"""
    upstream = FakeUpstream({
        C.BILLS_PATH: _envelope({"items": [
            {"biz_type": C.BILL_BIZ_REWARD_GRANT, "event_name": "新人注册礼包", "points": 3000},
        ]}),
        C.LOGIN_POINTS_GRANT_PATH: _envelope({"granted": True, "popup": {"points": 3000}}),
    })
    _patch_client(monkeypatch, upstream)
    outcome = await raccoon.claim_onboarding(_cred(), raccoon.meta(), precheck=True)
    assert outcome.category == "success"
    assert len(upstream.requests_for(C.LOGIN_POINTS_GRANT_PATH)) == 1


async def test_claim_onboarding_precheck_failure_still_attempts_grant(monkeypatch):
    """反查查不到（网络/HTML）→ **仍然尝试领取**（服务端幂等；宁可多点一次也不误报已领）。"""
    upstream = FakeUpstream({
        C.BILLS_PATH: httpx.ConnectError("down"),
        C.LOGIN_POINTS_GRANT_PATH: _envelope({"granted": True}),
    })
    _patch_client(monkeypatch, upstream)
    outcome = await raccoon.claim_onboarding(_cred(), raccoon.meta(), precheck=True)
    assert outcome.category == "success"
    assert len(upstream.requests_for(C.LOGIN_POINTS_GRANT_PATH)) == 1


# ============ 签到：本产品无此能力（checkin=False）============


async def test_claim_is_inactive_with_zero_upstream_requests(monkeypatch):
    """每日 300 分由服务端按日自动发放、**无签到端点** → `inactive` + 可读原因 + 零请求。

    判据 = 注册表能力位（§22.6「能力矩阵是判据不是标签」），不是本函数里的硬编码分支。
    """
    upstream = FakeUpstream({})
    _patch_client(monkeypatch, upstream)
    assert registry.get("raccoon").capabilities.checkin is False

    outcome = await raccoon.claim(_cred(), raccoon.meta(), precheck=True)
    assert outcome.category == "inactive"                 # 正常业务状态，不是 failed
    assert "自动发放" in outcome.detail and "登录奖励" in outcome.detail
    assert upstream.calls == []                           # 绝不打必然失败的请求


# ============ 额度（三态；未知不当零）============


async def test_quota_available_reports_pools(monkeypatch):
    """`available_points>0` → `available`；分项池如实列出（会员池为 0 不列，`raccoon-credits.ts:148-155`）。"""
    upstream = FakeUpstream({C.BALANCE_PATH: _envelope({
        "available_points": 1250, "reward_points": 1000, "daily_points": 250,
        "monthly_points": 0, "topup_points": 0})})
    _patch_client(monkeypatch, upstream)
    snap = await raccoon.quota(_cred(), raccoon.meta())
    assert snap.state == "available" and snap.source == "raccoon-points"
    assert "1250" in snap.detail and "奖励积分 1000" in snap.detail and "每日积分 250" in snap.detail
    assert "会员积分" not in snap.detail                   # 0 值的会员池不列
    assert upstream.requests_for(C.BALANCE_PATH)[0].method == "GET"   # 只读端点


async def test_quota_zero_is_exhausted(monkeypatch):
    """真的查到 0 → `exhausted`（与 `unknown` 严格分开：前者可选路跳过）。"""
    upstream = FakeUpstream({C.BALANCE_PATH: _envelope({"available_points": 0,
                                                        "daily_points": 0})})
    _patch_client(monkeypatch, upstream)
    snap = await raccoon.quota(_cred(), raccoon.meta())
    assert snap.state == "exhausted" and "0" in snap.detail


@pytest.mark.parametrize("route,needle", [
    (httpx.Response(200, text="<html>expired</html>"), "合法信封"),
    (httpx.Response(500, json={"code": 500}), "HTTP 500"),
    (_envelope(code=7, message="bad"), "bad"),
    (_envelope({"reward_points": 100}), "available_points"),          # 缺核心字段
    (httpx.ConnectError("down"), "网络错误"),
])
async def test_quota_unknown_never_zero(monkeypatch, route, needle):
    """查不动/形状不对 → `unknown`（**绝不写成 0** —— 那是"已用光"的语义，`23 B2`）。"""
    upstream = FakeUpstream({C.BALANCE_PATH: route})
    _patch_client(monkeypatch, upstream)
    snap = await raccoon.quota(_cred(), raccoon.meta())
    assert snap.state == "unknown" and needle in snap.detail


async def test_quota_without_token_is_unknown_without_request(monkeypatch):
    upstream = FakeUpstream({})
    _patch_client(monkeypatch, upstream)
    snap = await raccoon.quota({}, raccoon.meta())
    assert snap.state == "unknown" and "access_token" in snap.detail
    assert upstream.calls == []


# ============ 探活（连通 / 凭据有效两维）============


async def test_probe_valid_and_failure_paths(monkeypatch):
    """`user_info` 200+code0 → 两维皆真；401/业务码 200003/HTML → 可达但凭据无效；网络 → 不可达。"""
    upstream = FakeUpstream({C.USER_INFO_PATH: _envelope({"id": "u-1"})})
    _patch_client(monkeypatch, upstream)
    ok = await raccoon.probe(_cred(), raccoon.meta())
    assert ok.reachable and ok.valid and ok.ok
    assert upstream.headers_of(C.USER_INFO_PATH)["Authorization"].startswith("Bearer ")

    for route, needle in [
        (httpx.Response(401, json={"code": 401}), "已失效"),
        (_envelope(code=C.CODE_SESSION_EXPIRED, message="expired"), "已失效"),
        (httpx.Response(200, text="<html>expired</html>"), "不是 JSON"),
        (httpx.Response(500, json={"code": 500}), "未确认"),
    ]:
        upstream = FakeUpstream({C.USER_INFO_PATH: route})
        _patch_client(monkeypatch, upstream)
        got = await raccoon.probe(_cred(), raccoon.meta())
        assert got.reachable and not got.valid and not got.ok, needle
        assert needle in got.detail

    upstream = FakeUpstream({C.USER_INFO_PATH: httpx.ConnectError("down")})
    _patch_client(monkeypatch, upstream)
    down = await raccoon.probe(_cred(), raccoon.meta())
    assert not down.reachable and not down.valid


async def test_probe_without_token_does_not_call_upstream(monkeypatch):
    upstream = FakeUpstream({})
    _patch_client(monkeypatch, upstream)
    got = await raccoon.probe({}, raccoon.meta())
    assert not got.ok and "access_token" in got.detail and upstream.calls == []


# ============ 续期（refresh_token 轮换）============


async def test_refresh_rotates_tokens_and_keeps_extra_fields(monkeypatch):
    """续期：新 access/refresh + `expires_at` 重算；附加字段（昵称/手机/设备）原样保留。"""
    new_token = _jwt(2_500_000_000)
    upstream = FakeUpstream({C.REFRESH_PATH: _envelope(
        {"access_token": new_token, "refresh_token": "r-new"})})
    _patch_client(monkeypatch, upstream)
    cred = _cred(nickname="RaccoonAva", phone="13800138000", device_id="d" * 32,
                 office_identity="org-1")
    fresh = await raccoon.refresh(cred, raccoon.meta())

    assert fresh["access_token"] == new_token and fresh["refresh_token"] == "r-new"
    assert fresh["expires_at"] == str(2_500_000_000 * 1000)
    assert fresh["nickname"] == "RaccoonAva" and fresh["phone"] == "13800138000"
    assert fresh["device_id"] == "d" * 32 and fresh["office_identity"] == "org-1"
    # 请求体只有 refresh_token（`raccoon-oauth.ts:294-298`；该端点不带 Authorization）
    assert upstream.json_of(C.REFRESH_PATH) == {"refresh_token": "r-old"}


async def test_refresh_keeps_old_refresh_token_when_server_omits_it(monkeypatch):
    """服务端只回新 `access_token` → **保留旧 refresh_token**（否则续期一次就永不可续期）。"""
    upstream = FakeUpstream({C.REFRESH_PATH: _envelope({"access_token": _jwt(2_600_000_000)})})
    _patch_client(monkeypatch, upstream)
    fresh = await raccoon.refresh(_cred(), raccoon.meta())
    assert fresh["refresh_token"] == "r-old"


@pytest.mark.parametrize("route", [
    httpx.Response(401, json={"code": 401}),                    # HTTP 401
    _envelope(code=C.CODE_SESSION_EXPIRED, message="expired"),  # 业务码 200003
])
async def test_refresh_expired_token_is_not_refreshable(monkeypatch, route):
    """`refresh_token` 失效 → `NotRefreshable`（终态，不触发冷却；§22.3）。"""
    upstream = FakeUpstream({C.REFRESH_PATH: route})
    _patch_client(monkeypatch, upstream)
    with pytest.raises(NotRefreshable, match="重新登录"):
        await raccoon.refresh(_cred(), raccoon.meta())


async def test_refresh_without_refresh_token_is_not_refreshable(monkeypatch):
    upstream = FakeUpstream({})
    _patch_client(monkeypatch, upstream)
    with pytest.raises(NotRefreshable, match="refresh_token"):
        await raccoon.refresh({"access_token": _jwt(1)}, raccoon.meta())
    assert upstream.calls == []


@pytest.mark.parametrize("route", [
    httpx.Response(500, json={"code": 500, "message": "boom"}),   # 5xx（可重试）
    _envelope({}),                                                # 200 却缺 access_token
    httpx.ConnectError("down"),                                   # 传输层失败
])
async def test_refresh_retryable_failures_are_runtime_errors(monkeypatch, route):
    """可重试失败 = `RuntimeError`（**不判终态**；200 却缺令牌也不写回空值）。"""
    upstream = FakeUpstream({C.REFRESH_PATH: route})
    _patch_client(monkeypatch, upstream)
    with pytest.raises(RuntimeError):
        await raccoon.refresh(_cred(), raccoon.meta())


# ============ 模型目录（远端 + 兜底表）============


def _catalog(models: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "data": {"categories": [
        {"type": "image", "models": [{"name": "not-chat"}]},
        {"type": "chat", "models": models},
    ]}})


async def test_list_models_remote_filters_and_normalizes(monkeypatch):
    """远端目录：只取 `chat` 分类、过滤 `visible:false`、倍率进展示名、`params` 字段回退。"""
    upstream = FakeUpstream({C.MODEL_CATALOG_PATH: _catalog([
        {"name": "sn-sensenova-6-8-flash", "description": "SenseNova-6.8-Flash",
         "billing_effective_multiplier": 0, "billing_multiplier": 0.5,
         "params": {"context_window": 256000, "max_tokens": 63999},
         "tags": ["vision", "text"]},
        {"name": "sn-glm-5-3-flash", "description": "GLM-5-3-Flash",
         "billing_effective_multiplier": 0.1, "billing_multiplier": 0.2,
         "context_window": 1000000, "params": {"max_tokens": 100000}},
        {"name": "hidden-internal", "visible": False},
        {"name": "sn-sensenova-6-8-flash"},                      # 重复 id → 去重
        {"description": "没有 name 字段"},                        # id 取不到 → 跳过
    ])})
    _patch_client(monkeypatch, upstream)
    models = await raccoon.list_models(_cred(), raccoon.meta())

    assert [m.id for m in models] == ["sn-sensenova-6-8-flash", "sn-glm-5-3-flash"]
    assert models[0].name == "SenseNova-6.8-Flash · 免费"        # 生效价 0 → 免费
    assert models[0].context_window == 256_000 and models[0].max_output == 63_999
    assert models[0].image_input is True
    assert models[1].name == "GLM-5-3-Flash · x0.2→x0.1"        # 促销：原价→折后价
    assert models[1].context_window == 1_000_000                 # 顶层字段回退（`params` 无该键）
    assert models[1].image_input is False
    for model in models:
        assert model.tool_call is None and model.vendor == ""    # 未声明 → 不编造
        assert model.reasoning is True                           # provider 级方言，全模型一致
        assert model.effort_levels == ("on", "off")
    # 目录端点：带 Bearer 与语言头，但**不带** platform（`raccoon-auth.ts:479-484` 不发它）
    headers = upstream.headers_of(C.MODEL_CATALOG_PATH)
    assert headers["Authorization"].startswith("Bearer ")
    assert headers["X-Raccoon-Language"] == "zh" and "X-Client-Platform" not in headers


@pytest.mark.parametrize("route", [
    httpx.Response(500, json={"code": 500}),
    httpx.Response(200, text="<html>bad</html>"),
    _envelope(code=1, message="bad"),
    httpx.Response(200, json={"code": 0, "data": {"categories": [
        {"type": "chat", "models": [{"name": "only-hidden", "visible": False}]}]}}),
    httpx.ConnectError("down"),
])
async def test_list_models_falls_back_to_six_entries(monkeypatch, route):
    """远端失败 / 形态不认识 / 无可见模型 → **6 条兜底表**（逐条比对，不编造）。"""
    upstream = FakeUpstream({C.MODEL_CATALOG_PATH: route})
    _patch_client(monkeypatch, upstream)
    models = await raccoon.list_models(_cred(), raccoon.meta())
    assert models == list(C.FALLBACK_MODELS)
    assert [m.id for m in models] == [
        "sn-sensenova-6-8-flash", "sn-sensenova-6-8-flash-lite", "sn-glm-5-3",
        "sn-kimi-k3", "sn-glm-5-3-flash", "sn-deepseek-v4-1-flash"]


async def test_list_models_without_token_uses_fallback_without_request(monkeypatch):
    """无凭据 → 兜底表（不发必然 401 的请求，白产生一条 warning）。"""
    upstream = FakeUpstream({})
    _patch_client(monkeypatch, upstream)
    models = await raccoon.list_models({}, raccoon.meta())
    assert models == list(C.FALLBACK_MODELS) and upstream.calls == []


# ============ 纯函数（协议面）============


def test_client_platform_mapping_follows_desktop_device_identity():
    """`X-Client-Platform` 只允许三值（`raccoon-product.ts:175-183`）。"""
    assert C.client_platform("win32") == C.PLATFORM_WINDOWS
    assert C.client_platform("darwin") == C.PLATFORM_MACOS
    assert C.client_platform("linux") == C.PLATFORM_LINUX
    assert C.client_platform() in {C.PLATFORM_WINDOWS, C.PLATFORM_MACOS, C.PLATFORM_LINUX}


def test_display_name_rules():
    """四条展示规则（`raccoon.ts:225-262`）：免费 / 促销箭头 / **1 倍也要显示** / 取不到不追加。"""
    assert p.display_name("GLM-5-3", 0.75, 0.75) == "GLM-5-3 · x0.75"
    assert p.display_name("X", 0, 0.5) == "X · 免费"
    assert p.display_name("Y", 0.1, 0.2) == "Y · x0.2→x0.1"
    assert p.display_name("Kimi-K3", 1, 1) == "Kimi-K3 · x1"        # 1 倍必须显示
    assert p.display_name("Z", None, None) == "Z"                   # 不产出孤立 " · "


def test_jwt_exp_decode_never_verifies_and_degrades_on_bad_input():
    """JWT 只解码不验签（`raccoon.ts:108-129`）；坏值一律 `None`（降级成"无过期信息"）。"""
    assert p.jwt_exp_ms(_jwt(1_800_000_000)) == 1_800_000_000 * 1000
    for bad in ("", "not-a-jwt", "a.b", "a." + base64.urlsafe_b64encode(b"{}").decode() + ".c",
                _jwt(0)):
        assert p.jwt_exp_ms(bad) is None


def test_device_id_header_only_when_present():
    """设备字段可选：凭据里有才发 `X-Client-Device-ID`（`raccoon.ts:289-291`）——本实现留空。"""
    assert "X-Client-Device-ID" not in p.headers({"access_token": "t"})
    assert p.headers({"access_token": "t", "device_id": "d" * 32})["X-Client-Device-ID"] == "d" * 32


def test_build_nickname_deduplicates_suffix():
    """消歧后缀不重复追加（`jet-hub-rpc.ts:264-266`）。"""
    assert p.build_nickname({"nickname": "RaccoonAva", "phone": "13800138000"}, "x") \
        == "RaccoonAva (8000)"
    assert p.build_nickname({"nickname": "RaccoonAva 8000", "phone": "13800138000"}, "x") \
        == "RaccoonAva 8000"
    assert p.build_nickname({"user_id": "u-9"}, "x") == "Raccoon u-9"
    assert p.build_nickname({}, "raccoon-abc") == "raccoon-abc"


# ============ 契约表（§22.3）============


async def test_hooks_contract_and_unimplemented_todo(monkeypatch):
    """`_HOOKS` = §22.3 十钩子；`claim_onboarding` 为可选钩子（不在表内）；
    `login_callback` 显式失败；`build_out` 自 **M6-5b** 起接线（原「M6-5 TODO」护栏按波次转正）。"""
    assert set(raccoon._HOOKS) == {
        "meta", "login_start", "login_poll", "login_callback", "refresh", "probe",
        "quota", "claim", "list_models", "build_out"}
    for name, fn in raccoon._HOOKS.items():
        assert fn is getattr(raccoon, name)
    # 备选登录形态的两步（不在十钩子内；DSH 对应 `login.sendSms`/`login.submitSms`）
    assert set(raccoon._ALT_HOOKS) == {"sms_send", "sms_submit"}
    for name, fn in raccoon._ALT_HOOKS.items():
        assert fn is getattr(raccoon, name)
    # 可选钩子表（§22.3：`claim_onboarding` 只由 onboarding 产品实现；不入十钩子表）
    assert set(raccoon._OPTIONAL_HOOKS) == {"claim_onboarding"}
    assert raccoon._OPTIONAL_HOOKS["claim_onboarding"] is raccoon.claim_onboarding
    with pytest.raises(NotImplementedError, match="非 local_callback"):
        await raccoon.login_callback(_session(), {})
    assert raccoon._IMPLEMENTED == frozenset(
        {"login_start", "login_poll", "refresh", "probe", "quota", "claim",
         "claim_onboarding", "list_models", "build_out"})
    # 可选钩子签名（§22.3）：`(cred, meta, *, precheck: bool)`，async
    signature = inspect.signature(raccoon.claim_onboarding)
    assert list(signature.parameters) == ["cred", "meta", "precheck"]
    assert signature.parameters["precheck"].kind is inspect.Parameter.KEYWORD_ONLY
    assert inspect.iscoroutinefunction(raccoon.claim_onboarding)


def test_build_out_is_wired_to_the_family_adapter():
    """`build_out` 自 M6-5b 起接线（原 M6-5 TODO 护栏在此**按波次转正**）：
    返回 openai 族出站适配器；路径 = 基类缺省 `/chat/completions` + 基址已含推理前缀
    = 取证值 `{apiBase}/api/web/llm/v2/chat/completions`（`raccoon-adapter.ts:427`）。

    行为判据（chat 四头集 / `extra_body.thinking` 方言 / 错误映射 / 端到端）在
    `tests/integration/test_raccoon_out.py`；本用例只钉「接线本身成立」。
    """
    from model_gateway.adapters.product_out import ProductAccount
    from model_gateway.upstream.raccoon.out import RaccoonOut

    base = f"{C.API_BASE}{C.LLM_PREFIX}"
    account = ProductAccount(product=raccoon.PRODUCT, name="acc-1", base_url=base)
    adapter = raccoon.build_out(account)
    assert isinstance(adapter, RaccoonOut)
    assert (adapter.product, adapter.account_ref) == ("raccoon", "acc-1")
    assert adapter.chat_path == "/chat/completions"
    assert adapter.base_url == base
    asyncio.run(adapter.aclose())


def test_registry_base_url_is_taken_from_dsh_evidence():
    """`registry.base_url` = API 基址 + 推理前缀（适配器按 `{base_url}/chat/completions` 拼接）。

    推理端点取证：`POST {apiBase}/api/web/llm/v2/chat/completions`（`raccoon-adapter.ts:6,427`）。
    """
    assert registry.get("raccoon").base_url == f"{C.API_BASE}{C.LLM_PREFIX}"
    assert registry.get("raccoon").base_url.endswith("/api/web/llm/v2")


def test_parse_envelope_reads_numeric_string_codes():
    """R2a-F-2（2026-10-06 第三轮对账修）：`{"code":"200003"}`（字符串）必须读成
    200003 ⇒ product.refresh 的 NotRefreshable 正常触发。旧实现读到 0 ⇒ 既不触发
    NotRefreshable、`envelope.ok` 反为真 ⇒ 坏号被判成功。"""
    from model_gateway.upstream.raccoon.const import CODE_SESSION_EXPIRED
    from model_gateway.upstream.raccoon.protocol import parse_envelope

    env = parse_envelope({"code": "200003", "message": "expired"}, 200)
    assert env.code == CODE_SESSION_EXPIRED and not env.ok
    env2 = parse_envelope({"code": 200003}, 200)
    assert env2.code == CODE_SESSION_EXPIRED and not env2.ok   # 数值形状不变
    env3 = parse_envelope({"code": "abc"}, 200)
    assert env3.code == 0 and env3.ok                          # 非数字字符串维持不猜
    env4 = parse_envelope({"code": "401"}, 401)
    assert env4.code == 401                                    # 状态兜底形状不变


def test_read_str_strips_control_chars():
    """R2a-F-4（2026-10-06）：raccoon read_str 接入共享剥离（多行 scope 破坏落盘 JSON
    的同形状敞口，buddy 一手复盘）。"""
    from model_gateway.upstream.raccoon.protocol import read_str

    assert read_str({"k": "line1\nline2\tend"}, "k") == "line1 line2 end"
    assert read_str({"k": "普通"}, "k") == "普通"
    assert read_str({"k": 123}, "k") == ""            # 非字符串 → 空串（既有口径）
    assert read_str(None, "k") == ""


def test_json_parsers_are_one_shared_implementation():
    """R2a-F-5（2026-10-06 第三轮落地）：同包 4 份 `_json_or_none` + cline/zcode 2 份
    `_json_or_empty` 收编为 `upstream/_text.py` 一份实现——本地名只是 re-export，
    18 个调用点形状零变化。"""
    from model_gateway.upstream._text import json_or_empty, json_or_none
    from model_gateway.upstream.raccoon.credits import _json_or_none as j_credits
    from model_gateway.upstream.raccoon.login import _json_or_none as j_login
    from model_gateway.upstream.raccoon.models import _json_or_none as j_models
    from model_gateway.upstream.raccoon.product import _json_or_none as j_product
    from model_gateway.upstream.cline.product import _json_or_empty as je_cline
    from model_gateway.upstream.zcode.product import _json_or_empty as je_zcode

    for alias in (j_credits, j_login, j_models, j_product):
        assert alias is json_or_none
    for alias in (je_cline, je_zcode):
        assert alias is json_or_empty
