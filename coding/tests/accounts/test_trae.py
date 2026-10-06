"""`upstream/trae` 产品钩子单测（tech-design v2.0 §22.3/§22.4；M6-3 波次 B）。

HTTP **全部**用 `httpx.MockTransport` 注入（monkeypatch `accounts/net.py::make_client`
—— 钩子只经它取客户端，§22.8-1）→ **无网络、无真实凭据**。

判据逐条对应契约（证据行 = DSH `trae*.ts`）：

  · 登录：`login_start` 零网络 + 回调 URL 用**回跳接收端的实际端口**（17 参数、
    `auth_callback_url` 参数名；BD4）+ 私有态不进 `Challenge`；`login_callback` 换凭据落盘
    （引擎路径；**投递路径见 `tests/integration/test_m7_callback_capture.py`**）；
    **路径 / 端口 / 主机 / login_trace_id 四层校验**照 DSH；PKCE 回调单独报「不支持」；
    `login_poll` = **显式 NotImplementedError**（本产品无轮询通道）
  · 刷新：`ExchangeToken` 请求体 4 字段；新 refresh_token 空则保留旧值；设备字段不改写；
    终态（401/403、2xx 却无 token）→ `NotRefreshable`；网络失败 → 可重试异常；
    **expires_at 回写 meta.json**（!IKIRTT 教训）
  · 探活：连通 / 凭据有效两维（200+UserID / 401 / HTML 错误页）
  · 签到：**幂等只能靠 status 的 `checked_in`** —— 已签到 → `already_done` 且
    **不发** claim；活动关闭 → `inactive`；claim 成功后**必须**复核 status（未更新 → failed，
    不谎报成功）；9074 → failed（冷却 300s，**不再换设备号重试**，`20 R14`）
  · 冷却表：`trae-credits.ts:74-100` 逐行（1005→43200 / 429→60 / 401→-1 / 404→60 /
    5xx→600 / 4xx→600 / 业务码→300 / 其余→0）
  · 设备：`device_id = deriveDeviceId15(uid)` 稳定 15 位数字（对照**独立重写的**派生算法）
  · 目录：远端 batch（三条硬过滤 + 三规则合并 + 22 个 function）+ 28 条兜底表
  · 契约：`_HOOKS` 齐全、`_IMPLEMENTED` 不含 `login_poll`；`build_out` 自 **M6-5c**
    起接线（原「M6-5 TODO」护栏按波次转正，处置同 buddy 的 M6-5a）
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pytest

from model_gateway.accounts import callback_server, net
from model_gateway.accounts.login import LoginEngine
from model_gateway.accounts.store import has_account, load_credentials, load_meta
from model_gateway.accounts.types import NotRefreshable
from model_gateway.upstream.trae import (
    claim as claim_mod,
    const,
    login,
    models,
    product,
    protocol,
    quota as quota_mod,
)

#: 一个真实形态的 uid（实测样例，`trae.ts:561`）
UID = "4056564292660009"
CRED = {"access_token": "AT-1", "refresh_token": "RT-1", "uid": UID,
        "machine_id": "m" * 32, "device_id": protocol.derive_device_id15(UID),
        "login_device_id": "d" * 32}


# ============ 假上游 ============

def _install_http(monkeypatch, routes: dict) -> list[httpx.Request]:
    """把 `net.make_client` 换成 MockTransport 客户端（记录请求；无网络）。"""
    seen: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = str(request.url)
        for needle, route in routes.items():
            if needle in url:
                return route(request) if callable(route) else route
        return httpx.Response(404, json={"code": 404, "message": f"unrouted {url}"})

    def factory(**kwargs):
        # 与 `net.make_client` **同形**：参数照传（钩子用绝对 URL，base_url 缺省空）
        kwargs.pop("follow_redirects", None)
        kwargs["timeout"] = httpx.Timeout(5.0)
        return httpx.AsyncClient(transport=httpx.MockTransport(responder), **kwargs)

    monkeypatch.setattr(net, "make_client", factory)
    return seen


def _raise(exc_type, message: str):
    def route(request: httpx.Request) -> httpx.Response:
        raise exc_type(message, request=request)
    return route


def _html(status: int, text: str = "<html>error</html>"):
    def route(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=text, request=request)
    return route


OK_EXCHANGE = httpx.Response(200, json={"Result": {
    "Token": "AT-NEW", "RefreshToken": "RT-NEW",
    # Go 端存秒（`trae.ts:95-101`）→ 本网关归一化成毫秒字符串
    "TokenExpireAt": 1_790_000_000, "TokenExpireDuration": 3600,
    "RefreshExpireAt": 1_790_600_000}})

OK_USER_INFO = httpx.Response(200, json={"Result": {
    "UserID": UID, "ScreenName": "用户26815487395",
    "NonPlainTextMobile": "130******00", "NonPlainTextEmail": "",
    "EnterpriseID": "ent-1"}})


@pytest.fixture(autouse=True)
def _hermetic_accounts(tmp_path, monkeypatch):
    """账号根隔离（泛化的 `MGW_ZCODE_ACCOUNTS` 口径）：绝不碰真实 `data/`。"""
    monkeypatch.setenv("MGW_TRAE_ACCOUNTS", str(tmp_path / "trae-accounts"))


def _session(**state):
    """造一个**状态自洽**的登录会话（`login_trace_id` 由设备字段派生，与 `login_start` 同口径）。"""
    from model_gateway.accounts.login import LoginSession

    session = LoginSession(id="s-1", product="trae", name="acc-1",
                           created_at=0.0, ttl_s=600.0)
    session.state.update(state)
    if state.get("machine_id") and state.get("login_device_id") \
            and "login_trace_id" not in state:
        session.state["login_trace_id"] = protocol.machine_trace_id(
            str(state["machine_id"]), str(state["login_device_id"]))
    return session


def _callback_url(session, *, refresh_token: str = "RT-CB", trace: str | None = None,
                  user_info: dict | None = None, **extra) -> str:
    """按本次会话的真实 machine_id/device_id 造回跳地址（回跳粘贴的主通道）。

    🔴 端口取**本会话声明的那个**：有接收端时 = 接收端实际端口（首选 18080 被占时是
       回退端口），没有接收端时回退常量 —— 与 `validate_callback` 同一把基准，
       用例才不会因为"上一位把 18080 占了"而莫名变红。
       投递路径（真 HTTP 到达）的判据在 `tests/integration/test_m7_callback_capture.py`。
    """
    params = {
        "refreshToken": refresh_token,
        "userInfo": json.dumps(user_info or {"UserID": UID, "ScreenName": "用户26815487395",
                                             "TenantID": "ent-1"}, ensure_ascii=False),
        "login_trace_id": (protocol.machine_trace_id(str(session.state.get("machine_id") or ""),
                                                     str(session.state.get("login_device_id") or ""))
                           if trace is None else trace),
    }
    params.update(extra)
    query = urlencode({k: v for k, v in params.items() if v is not None})
    port = callback_server.declared_port(session) or const.CALLBACK_PORT
    return f"http://127.0.0.1:{port}{const.CALLBACK_PATH}?{query}"


# ============ 登录：start ============

async def test_login_start_builds_fixed_port_url_zero_network(monkeypatch):
    """第一步：零网络；URL = 门户 `/authorization` + 固定端口回调 + 17 参数（`trae-oauth.ts:99-127`）。"""
    seen = _install_http(monkeypatch, {})
    session = _session()
    challenge = await product.login_start(session)

    assert seen == [], "login_start 不得发任何网络请求（transient activation 窗口）"
    assert challenge.url.startswith(f"{const.CONSOLE_HOST}{const.LOGIN_PATH}?")
    from urllib.parse import parse_qs, urlsplit

    query = parse_qs(urlsplit(challenge.url).query)
    # 回调地址的参数名必须是 auth_callback_url（不是 callback_url / redirect_uri）
    assert query["auth_callback_url"][0] == f"http://127.0.0.1:{const.CALLBACK_PORT}/authorize"
    assert query["client_id"][0] == const.CLIENT_ID
    assert query["plugin_version"][0] == const.PLUGIN_VERSION
    assert query["auth_type"][0] == "local"
    assert query["machine_id"][0] == session.state["machine_id"]
    assert query["device_id"][0] == session.state["login_device_id"]
    assert query["x_device_id"][0] == session.state["login_device_id"]
    assert query["x_machine_id"][0] == session.state["machine_id"]
    assert query["login_trace_id"][0] == session.state["login_trace_id"]
    # 设备字段形态：machine_id 32 hex；登录期 device_id 32 hex（`trae.ts:1283-1305`）
    assert len(session.state["machine_id"]) == 32
    assert len(session.state["login_device_id"]) == 32
    # Challenge 只承载用户可见物（凭据/设备私态不进 Challenge，§22.3）
    assert challenge.device_code == "" and challenge.qr_payload == ""
    assert challenge.sms_sent is False


async def test_login_start_machine_id_is_cross_account_unique(tmp_path, monkeypatch):
    """`machine_id` 跨账号唯一（§22.2 不变式③ / §15.1 硬约束 1）：已有账号占用的值不得复用。"""
    from model_gateway.accounts import store

    seen = _install_http(monkeypatch, {})
    root = store.product_root("trae")
    store.commit_login("trae", "acc-old", {"access_token": "x"},
                       {"machine_id": "a" * 32, "device_id": "123456789012345"}, root=root)
    session = _session()
    await product.login_start(session)
    assert session.state["machine_id"] != "a" * 32
    assert seen == []


async def test_login_start_url_and_validation_follow_the_listener_port(monkeypatch):
    """🔴 BD4 接线判据：授权 URL 里的端口 = 接收端**实际**端口，校验也按同一个端口。

    参考实现专门做了"绑定后重建 URL"（`trae-oauth.ts:680-693`）：18080 被占时接收端
    回退随机端口 —— URL 若仍写常量，回跳打到别人家；校验若仍钉常量，真回跳被判成伪造。
    这里用一个非 18080 的假接收端把**两头**都钉住。
    """
    from urllib.parse import parse_qs, urlsplit

    _install_http(monkeypatch, {})

    class _Listener:
        port = 21211

    session = _session()
    session.callback = _Listener()
    challenge = await product.login_start(session)

    declared = parse_qs(urlsplit(challenge.url).query)["auth_callback_url"][0]
    assert declared == f"http://127.0.0.1:21211{const.CALLBACK_PATH}"
    # 同端口的回跳：形态 + 关联串都过
    assert login.validate_callback(session, {"url": _callback_url(session)}) == ""
    # 还按常量 18080 粘回来的串 = 别的程序的回调 → 判失败，并把两个端口都说清
    stale = login.validate_callback(session, {"url": (
        f"http://127.0.0.1:{const.CALLBACK_PORT}{const.CALLBACK_PATH}"
        f"?login_trace_id={session.state['login_trace_id']}")})
    assert "回跳端口" in stale and "21211" in stale and "18080" in stale, stale


def test_callback_table_declares_the_listener_shape():
    """接收端形状的唯一真相源 = `product._CALLBACK`（引擎**读表**，不猜字段名）。"""
    assert product._CALLBACK == {
        "path": const.CALLBACK_PATH,
        "preferred_port": const.CALLBACK_PORT,      # 18080 首选（用户裁决）
        "secret_state_key": "login_trace_id",
        "secret_key": "login_trace_id",
        "secret_required": False,                   # 上游不保证回传（`trae-oauth.ts:67-70`）
    }


def test_callback_url_problem_accepts_the_declared_port():
    """形态校验接受**声明端口**；缺省仍是常量口径（粘贴兜底不受影响）。"""
    ok = f"http://127.0.0.1:21213{const.CALLBACK_PATH}?refreshToken=RT"
    assert protocol.callback_url_problem(ok, declared_port=21213) == ""
    assert "回跳端口" in protocol.callback_url_problem(ok, declared_port=18080)
    assert "回跳端口" in protocol.callback_url_problem(ok)      # 缺省 = 18080


# ============ 登录：callback ============

async def test_login_callback_success_commits_credentials_and_meta(monkeypatch):
    """第二个：回跳粘贴 → ExchangeToken → GetUserInfo → 引擎**认领暂存** →「确定接入」落盘。"""
    seen = _install_http(monkeypatch, {
        const.PATH_EXCHANGE: OK_EXCHANGE,
        const.PATH_USER_INFO: OK_USER_INFO,
    })
    engine = LoginEngine()
    session = await engine.start("trae")
    outcome = await engine.callback("trae", session.id, {"url": _callback_url(session)})

    assert outcome.state == "success", outcome.detail
    # 两阶段提交（M7-E）：到达只暂存，确认才落盘
    assert session.state["pending"]["credentials"]["access_token"] == "AT-NEW"
    assert not has_account(Path(os.environ["MGW_TRAE_ACCOUNTS"]), session.name)
    assert (await engine.commit_pending(session.id))["committed"] is True
    # 落盘：凭据（明文）+ 元信息（§22.2 布局）
    cred = load_credentials("trae", session.name)
    assert cred["access_token"] == "AT-NEW"
    assert cred["refresh_token"] == "RT-NEW"
    assert cred["uid"] == UID
    # expires_at 归一化成毫秒字符串（Go 端秒 → ×1000，`trae.ts:95-101`）
    assert cred["expires_at"] == str(1_790_000_000 * 1000)
    meta = load_meta(Path(os.environ["MGW_TRAE_ACCOUNTS"]), session.name)
    assert meta["machine_id"] == session.state["machine_id"]          # 随机、此后不改写
    assert meta["device_id"] == protocol.derive_device_id15(UID)      # uid 确定性派生（20 §3.5）
    assert meta["login_device_id"] == session.state["login_device_id"]
    assert meta["uid"] == UID
    # 展示名取脱敏手机号优先（真实缺陷复盘，`trae.ts:539-582`）
    assert meta["nickname"] == "130******00"
    # 两个请求：ExchangeToken → GetUserInfo（顺序即钩子调用顺序）
    assert [r.url.path for r in seen] == [const.PATH_EXCHANGE, const.PATH_USER_INFO]
    exchange_body = json.loads(seen[0].content)
    assert exchange_body == {"ClientID": const.CLIENT_ID, "RefreshToken": "RT-CB",
                             "ClientSecret": "-", "UserID": ""}


async def test_login_callback_path_port_host_checks(monkeypatch):
    """回跳地址形态校验（照 DSH 的回调处理器）：路径 `/authorize`、本会话声明的端口、回环主机。"""
    seen = _install_http(monkeypatch, {const.PATH_EXCHANGE: OK_EXCHANGE,
                                       const.PATH_USER_INFO: OK_USER_INFO})
    session = _session(machine_id="m" * 32, login_device_id="d" * 32)
    query = _callback_url(session).split("?", 1)[1]
    cases = {
        "http://127.0.0.1:18080/auth/callback?" + query: "回跳路径",
        "http://127.0.0.1:1234/authorize?" + query: "回跳端口",
        "http://10.0.0.5:18080/authorize?" + query: "回跳主机",
    }
    for url, needle in cases.items():
        outcome = await product.login_callback(session, {"url": url})
        assert outcome.state == "failed", url
        assert needle in outcome.detail, outcome.detail
    assert seen == [], "形态校验未通过时不得发任何上游请求"


async def test_login_callback_trace_mismatch_rejected_but_absent_tolerated(monkeypatch):
    """`login_trace_id` 不一致 → 拒绝；**未带回**时放行（上游不保证回传，`trae-oauth.ts:67-70`）。"""
    seen = _install_http(monkeypatch, {const.PATH_EXCHANGE: OK_EXCHANGE,
                                       const.PATH_USER_INFO: OK_USER_INFO})
    session = _session(machine_id="m" * 32, login_device_id="d" * 32)
    bad = await product.login_callback(
        session, {"url": _callback_url(session, trace="f" * 16)})
    assert bad.state == "failed" and "login_trace_id" in bad.detail
    assert seen == []
    # 不带 login_trace_id：放行（DSH 对这些字段完全不校验）
    ok = await product.login_callback(
        session, {"url": _callback_url(session, trace=None)})
    assert ok.state == "success", ok.detail


async def test_login_callback_pkce_flow_is_reported_as_unsupported(monkeypatch):
    """带 code 的 PKCE 回调 = **合法回调但不支持**：精确报出，不误报「缺少 refreshToken」。"""
    _install_http(monkeypatch, {})
    session = _session(machine_id="m" * 32, login_device_id="d" * 32)
    url = (f"http://127.0.0.1:{const.CALLBACK_PORT}/authorize?"
           + urlencode({"code": "AUTH-CODE-1"}))
    outcome = await product.login_callback(session, {"url": url})
    assert outcome.state == "failed"
    assert "PKCE" in outcome.detail


async def test_login_callback_exchange_failure_and_missing_session_state(monkeypatch):
    """ExchangeToken 失败（HTTP 401 HTML 页）→ failed；会话缺设备私态 → fail closed。"""
    _install_http(monkeypatch, {const.PATH_EXCHANGE: _html(401)})
    ready = _session(machine_id="m" * 32, login_device_id="d" * 32)
    outcome = await product.login_callback(ready, {"url": _callback_url(ready)})
    assert outcome.state == "failed" and "ExchangeToken" in outcome.detail
    # 会话状态丢失（如重启）：不发请求、不猜设备
    observed = _install_http(monkeypatch, {const.PATH_EXCHANGE: OK_EXCHANGE})
    empty = _session()
    outcome = await product.login_callback(empty, {"url": _callback_url(empty, trace=None)})
    assert outcome.state == "failed" and "machine_id" in outcome.detail
    assert observed == []


async def test_login_callback_user_jwt_token_branch_skips_exchange(monkeypatch):
    """无 refreshToken 时直接用 `userJwt.Token`（`trae-oauth.ts:394-403`）→ 不调 ExchangeToken。"""
    seen = _install_http(monkeypatch, {const.PATH_USER_INFO: OK_USER_INFO})
    session = _session(machine_id="m" * 32, login_device_id="d" * 32)
    url = (f"http://127.0.0.1:{const.CALLBACK_PORT}/authorize?"
           + urlencode({"userJwt": json.dumps({"Token": "AT-JWT"}),
                        "userInfo": json.dumps({"UserID": UID, "ScreenName": "X"}),
                        "login_trace_id": session.state["login_trace_id"]}))
    outcome = await product.login_callback(session, {"url": url})
    assert outcome.state == "success", outcome.detail
    assert outcome.credentials["access_token"] == "AT-JWT"
    assert [r.url.path for r in seen] == [const.PATH_USER_INFO]


async def test_login_callback_from_flat_params_and_missing_uid(monkeypatch):
    """平铺参数形态（前端结构化传参）也认；uid 两侧都取不到 → failed（不落半成品）。"""
    _install_http(monkeypatch, {
        const.PATH_EXCHANGE: OK_EXCHANGE,
        const.PATH_USER_INFO: httpx.Response(500, json={"code": 500}),
    })
    session = _session(machine_id="m" * 32, login_device_id="d" * 32)
    outcome = await product.login_callback(session, {"refreshToken": "RT-CB", "userInfo": {}})
    assert outcome.state == "failed" and "uid" in outcome.detail


async def test_login_poll_is_explicitly_not_applicable(monkeypatch):
    """本产品**无轮询通道** → 显式 NotImplementedError（不伪装成 pending，不静默成功）。"""
    seen = _install_http(monkeypatch, {})
    with pytest.raises(NotImplementedError, match="无轮询通道"):
        await product.login_poll(_session())
    assert seen == []


# ============ 续期 ============

async def test_refresh_success_merges_and_writes_meta(tmp_path, monkeypatch):
    """续期：ExchangeToken 轮换 token；身份字段保留；新 expires_at 回写 meta.json。"""
    seen = _install_http(monkeypatch, {const.PATH_EXCHANGE: OK_EXCHANGE})
    account_dir = tmp_path / "acc"
    account_dir.mkdir()
    (account_dir / "meta.json").write_text(json.dumps({"machine_id": "m" * 32,
                                                       "device_id": "123456789012345"}),
                                           encoding="utf-8")
    merged = await product.refresh(CRED, {"account": "acc", "dir": str(account_dir)})
    assert merged["access_token"] == "AT-NEW"
    assert merged["refresh_token"] == "RT-NEW"
    assert merged["uid"] == UID and merged["machine_id"] == "m" * 32     # 身份字段不改写
    assert merged["device_id"] == protocol.derive_device_id15(UID)
    assert merged["expires_at"] == str(1_790_000_000 * 1000)
    meta = json.loads((account_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["expires_at"] == merged["expires_at"]                    # !IKIRTT 教训
    assert json.loads(seen[0].content)["RefreshToken"] == "RT-1"
    assert str(seen[0].url) == f"{const.OAUTH_HOST}{const.PATH_EXCHANGE}"


async def test_refresh_keeps_old_refresh_token_when_response_empty(monkeypatch):
    """新 refresh_token 为空 → 保留旧值（不丢续期能力，`trae.ts:633-634`）。"""
    _install_http(monkeypatch, {const.PATH_EXCHANGE: httpx.Response(200, json={"Result": {
        "Token": "AT-NEW", "TokenExpireDuration": 3600}})})
    merged = await product.refresh(dict(CRED), None)
    assert merged["refresh_token"] == "RT-1"
    assert merged["expires_at"]  # 相对秒数 → now+duration×1000


@pytest.mark.parametrize("route,needle", [
    (_html(401), "已失效"),
    (_html(403), "已失效"),
    # 2xx + JSON 却无 token：Go 的 refresh_failed「重试一万次也不会有 token」（`trae-auth.ts:420-426`）
    (httpx.Response(200, json={"Result": {}}), "已失效"),
])
async def test_refresh_terminal_failures_are_not_refreshable(monkeypatch, route, needle):
    _install_http(monkeypatch, {const.PATH_EXCHANGE: route})
    with pytest.raises(NotRefreshable, match=needle):
        await product.refresh(dict(CRED), None)


async def test_refresh_retryable_failures_and_missing_token(monkeypatch):
    """网络 / 5xx 是可重试异常（**不是** NotRefreshable）；无 refresh_token → NotRefreshable。"""
    _install_http(monkeypatch, {const.PATH_EXCHANGE: _raise(httpx.ConnectError, "down")})
    with pytest.raises(RuntimeError, match="网络失败") as err:
        await product.refresh(dict(CRED), None)
    assert not isinstance(err.value, NotRefreshable)
    _install_http(monkeypatch, {const.PATH_EXCHANGE: _html(500)})
    with pytest.raises(RuntimeError, match="HTTP 500") as err:
        await product.refresh(dict(CRED), None)
    assert not isinstance(err.value, NotRefreshable)
    with pytest.raises(NotRefreshable, match="无 refresh_token"):
        await product.refresh({"access_token": "AT-1"}, None)


# ============ 探活 ============

async def test_probe_two_dimensions(monkeypatch):
    """连通 / 凭据有效**两维分开**（§22.3）：200+UserID / 401 / HTML 错误页 / 未登录。"""
    no_cred = await product.probe({}, {})
    assert (no_cred.reachable, no_cred.valid) == (False, False)
    assert "access_token" in no_cred.detail

    _install_http(monkeypatch, {const.PATH_USER_INFO: OK_USER_INFO})
    ok = await product.probe(dict(CRED), {})
    assert ok.ok and UID in ok.detail

    _install_http(monkeypatch, {const.PATH_USER_INFO: _html(401)})
    bad = await product.probe(dict(CRED), {})
    assert (bad.reachable, bad.valid) == (True, False) and "已失效" in bad.detail

    _install_http(monkeypatch, {const.PATH_USER_INFO: _html(200)})
    html = await product.probe(dict(CRED), {})
    assert (html.reachable, html.valid) == (True, False) and "不是 JSON" in html.detail

    _install_http(monkeypatch, {const.PATH_USER_INFO: _raise(httpx.ConnectError, "down")})
    down = await product.probe(dict(CRED), {})
    assert (down.reachable, down.valid) == (False, False) and "不可达" in down.detail


# ============ 签到：幂等 / 冷却表 ============

@pytest.mark.parametrize("status,code,expect_type,cooldown", [
    (200, 1005, "PlanLimit", 43_200),
    (429, None, "SoftRate", 60),
    (401, None, "SessionDead", -1),
    (404, None, "NotFound", 60),
    (500, None, "Server", 600),
    (503, None, "Server", 600),
    (400, None, "Client", 600),
    (200, 1234, "BusinessError", 300),
    (200, 9074, "BusinessError", 300),
    (200, 0, "Unknown", 0),
    (200, None, "Unknown", 0),
])
def test_classify_checkin_error_table(status, code, expect_type, cooldown):
    """冷却表逐行对照 `trae-credits.ts:74-100`（12h/60s/-1/600s/300s）。"""
    error = claim_mod.classify_checkin_error(status, code)
    assert (error.type, error.cooldown_secs) == (expect_type, cooldown)
    if cooldown == -1:
        assert "需重新登录" in claim_mod.failure_detail(error, "x")
    elif cooldown > 0:
        assert f"{cooldown}s" in claim_mod.failure_detail(error, "x")


async def test_claim_precheck_already_done_skips_claim(monkeypatch):
    """🔴 幂等**只能**靠 status 的 `checked_in`：已签到 → already_done 且**不发** claim。"""
    seen = _install_http(monkeypatch, {
        const.PATH_CHECKIN_STATUS: httpx.Response(200, json={
            "code": 0, "checked_in": True, "enable": True, "credits": 150}),
        const.PATH_CHECKIN_CLAIM: httpx.Response(200, json={"code": 0, "message": "success"}),
    })
    outcome = await product.claim(dict(CRED), {}, precheck=True)
    assert outcome.category == "already_done" and "150" in outcome.detail
    assert [r.url.path for r in seen] == [const.PATH_CHECKIN_STATUS]


async def test_claim_precheck_inactive_when_activity_disabled(monkeypatch):
    _install_http(monkeypatch, {const.PATH_CHECKIN_STATUS: httpx.Response(200, json={
        "code": 0, "checked_in": False, "enable": False})})
    outcome = await product.claim(dict(CRED), {}, precheck=True)
    assert outcome.category == "inactive" and "未开启" in outcome.detail


async def test_claim_success_verifies_via_status_and_reports_credits(monkeypatch):
    """claim code 0 后**必须复核 status**：checked_in=true → success 并带上积分数。"""
    calls = {"n": 0}

    def status_route(request: httpx.Request) -> httpx.Response:
        # 第一次（预检）未签到；第二次（复核）已签到 —— 复刻真实时序
        calls["n"] += 1
        checked = calls["n"] > 1
        return httpx.Response(200, json={"code": 0, "checked_in": checked,
                                        "enable": True, "credits": 150 if checked else 0,
                                        "streak_days": 3 if checked else 0})

    seen = _install_http(monkeypatch, {const.PATH_CHECKIN_STATUS: status_route,
                                       const.PATH_CHECKIN_CLAIM: httpx.Response(
                                           200, json={"code": 0, "message": "success"})})
    outcome = await product.claim(dict(CRED), {}, precheck=True)
    assert outcome.category == "success"
    assert "150" in outcome.detail and "连续 3 天" in outcome.detail
    paths = [r.url.path for r in seen]
    assert paths == [const.PATH_CHECKIN_STATUS, const.PATH_CHECKIN_CLAIM,
                     const.PATH_CHECKIN_STATUS]
    claim_request = next(r for r in seen if r.url.path == const.PATH_CHECKIN_CLAIM)
    assert json.loads(claim_request.content) == {}          # body 是 `{}`（trae-credits.ts:23）
    headers = {k.lower(): v for k, v in claim_request.headers.items()}
    assert headers["authorization"] == "Cloud-IDE-JWT AT-1"
    assert headers["x-device-id"] == protocol.derive_device_id15(UID)   # 派生 15 位（20 §3.5）
    assert headers["x-market-user-id"] == protocol.derive_market_user_id(UID)
    assert headers["user-agent"] == const.CHECKIN_USER_AGENT


async def test_claim_code_zero_but_status_not_updated_is_failed(monkeypatch):
    """claim 回 code 0 但 status 复核说没签到 → **不谎报成功**（用户报障形态的反面）。"""
    _install_http(monkeypatch, {
        const.PATH_CHECKIN_STATUS: httpx.Response(200, json={
            "code": 0, "checked_in": False, "enable": True}),
        const.PATH_CHECKIN_CLAIM: httpx.Response(200, json={"code": 0, "message": "success"}),
    })
    outcome = await product.claim(dict(CRED), {}, precheck=True)
    assert outcome.category == "failed" and "状态未更新" in outcome.detail


async def test_claim_code_zero_with_unavailable_status_is_failed(monkeypatch):
    """claim 成功但 status 复核查不动 → failed（不把无法确认报成成功）。"""
    _install_http(monkeypatch, {
        const.PATH_CHECKIN_STATUS: _html(500),
        const.PATH_CHECKIN_CLAIM: httpx.Response(200, json={"code": 0, "message": "success"}),
    })
    outcome = await product.claim(dict(CRED), {}, precheck=True)
    assert outcome.category == "failed" and "不谎报成功" in outcome.detail


async def test_claim_status_failure_before_claim_still_claims(monkeypatch):
    """预检查不动（不是「未签到」）→ 仍然尝试领取，由 claim + 复核定夺（DSH 同语义）。"""
    seen: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == const.PATH_CHECKIN_STATUS:
            if len([r for r in seen if r.url.path == const.PATH_CHECKIN_STATUS]) == 1:
                return httpx.Response(500, text="boom")
            return httpx.Response(200, json={"code": 0, "checked_in": True,
                                             "enable": True, "credits": 150})
        return httpx.Response(200, json={"code": 0, "message": "success"})

    _install_http(monkeypatch, {const.PATH_CHECKIN_STATUS: responder,
                                const.PATH_CHECKIN_CLAIM: responder})
    outcome = await product.claim(dict(CRED), {}, precheck=True)
    assert outcome.category == "success"
    assert [r.url.path for r in seen] == [const.PATH_CHECKIN_STATUS, const.PATH_CHECKIN_CLAIM,
                                          const.PATH_CHECKIN_STATUS]


async def test_claim_busy_9074_is_failed_with_cooldown_and_no_device_rotation(monkeypatch):
    """9074：「签到人数过多」→ failed + 冷却 300s；**不再换设备号重试**（`20 R14`）。"""
    seen = _install_http(monkeypatch, {
        const.PATH_CHECKIN_STATUS: httpx.Response(200, json={
            "code": 0, "checked_in": False, "enable": True}),
        # ⚠️ 后端在部分网关上以**字符串**返回业务码（`trae-credits.ts:121-132`）
        const.PATH_CHECKIN_CLAIM: httpx.Response(200, json={"code": "9074", "message": "too many"}),
    })
    outcome = await product.claim(dict(CRED), {}, precheck=True)
    assert outcome.category == "failed"
    assert "300s" in outcome.detail and "too many" in outcome.detail
    assert len([r for r in seen if r.url.path == const.PATH_CHECKIN_CLAIM]) == 1


async def test_claim_plan_limit_and_http_errors_are_failed_with_cooldowns(monkeypatch):
    """1005 → PlanLimit 43200s；429 → SoftRate 60s；401 → 永久（需重新登录）。"""
    def claim_route(code: int):
        return httpx.Response(200, json={"code": code, "message": "plan limited"})

    _install_http(monkeypatch, {const.PATH_CHECKIN_STATUS: httpx.Response(
        200, json={"code": 0, "checked_in": False, "enable": True}),
        const.PATH_CHECKIN_CLAIM: claim_route(1005)})
    outcome = await product.claim(dict(CRED), {}, precheck=False)
    assert outcome.category == "failed" and "43200s" in outcome.detail

    _install_http(monkeypatch, {const.PATH_CHECKIN_CLAIM: httpx.Response(
        429, json={"code": 0, "message": "slow down"})})
    outcome = await product.claim(dict(CRED), {}, precheck=False)
    assert outcome.category == "failed" and "60s" in outcome.detail

    _install_http(monkeypatch, {const.PATH_CHECKIN_CLAIM: httpx.Response(
        401, json={"code": 0, "message": "unauthorized"})})
    outcome = await product.claim(dict(CRED), {}, precheck=False)
    assert outcome.category == "failed" and "需重新登录" in outcome.detail


async def test_claim_without_credentials_or_uid_fails_closed(monkeypatch):
    seen = _install_http(monkeypatch, {})
    no_token = await product.claim({"uid": UID}, {}, precheck=True)
    assert no_token.category == "failed" and "access_token" in no_token.detail
    no_uid = await product.claim({"access_token": "AT-1"}, {}, precheck=True)
    assert no_uid.category == "failed" and "uid" in no_uid.detail
    assert seen == []


# ============ 设备身份派生 ============

def test_derive_device_id15_is_stable_15_digits_and_matches_algorithm():
    """`device_id = deriveDeviceId15(uid)`：同 uid 同值、恒 15 位数字、跨账号互异。

    对照算法 = **独立重写**的 `trae.ts:324-381`（SHA256(utf8("devid:"+uid) ++ counterBE32)，
    逐字节 % 10 取 15 位）—— 不是拿实现自己验自己。
    """
    def reference(uid: str) -> str:
        prefix = f"devid:{uid}".encode("utf-8")
        digest = hashlib.sha256(prefix + (0).to_bytes(4, "big")).digest()
        return "".join(str(byte % 10) for byte in digest[:15])

    assert protocol.derive_device_id15(UID) == reference(UID)
    assert protocol.derive_device_id15(UID) == protocol.derive_device_id15(UID)
    value = protocol.derive_device_id15(UID)
    assert len(value) == 15 and value.isdigit()
    assert protocol.derive_device_id15("9340371069") != value
    # 派生的 market user id / session id 形态（`trae.ts:331-345`）
    market = protocol.derive_market_user_id(UID)
    assert len(market) == 36 and market[14] == "4"
    assert len(protocol.derive_session_id(UID)) == 64


# ============ 目录 ============

def test_fallback_table_is_verbatim_and_hidden_entries_excluded():
    """32 条兜底表逐条照抄（`trae-product.ts:169-202`）；4 条隐藏条目按同判据不返回。"""
    assert len(const.FALLBACK_MODELS) == 32
    assert [row[0] for row in const.FALLBACK_MODELS[:5]] == [
        "DeepSeek-V4-Flash-Official", "Doubao-Seed-2.1-Pro", "seed-code-pro-0430",
        "Doubao-Seed-2.1-Turbo", "Doubao-Seed-2.0-Code"]
    assert [row[0] for row in const.FALLBACK_MODELS if row[3]] == [
        "browser_use_subagent", "explore_sub_agent_v13", "explore_sub_agent_v2", "summary"]
    listed = models.fallback_models()
    assert len(listed) == 28
    assert listed[0].id == "DeepSeek-V4-Flash-Official"
    assert listed[0].context_window == 200_000        # 照抄（DSH 自注为估值）
    assert listed[0].max_output is None and listed[0].tool_call is None


async def test_list_models_without_credentials_uses_fallback_zero_network(monkeypatch):
    seen = _install_http(monkeypatch, {})
    listed = await product.list_models({}, {})
    assert len(listed) == 28
    assert seen == [], "未登录不得打目录端点（必然 401，只增风控可见性）"


async def test_list_models_remote_batch_filters_and_merges(monkeypatch):
    """远端 batch：三条硬过滤 + 三规则合并 + 22 个 function（`trae.ts:1158-1256`）。"""
    def entry(name, *, usage="chat_completion", enabled=True, hidden=False,
              options=None, support=None, channel=None):
        item = {"config_name": name, "usage": usage, "config_switch": enabled,
                "is_invisible_to_user": hidden,
                "display_config": {"display_name": f"{name}-name", "multimodal": True},
                "context_window_tokens": {"dev": 200_000, "max": 1_000_000},
                "model_detail_list": [{"model_name": f"{name}__dev", "max_tokens": 32_000}]}
        if options is not None:
            item["reasoning_effort_config"] = {"options": options, "support_thinking": support}
        return item

    body = {"function_configs": [
        # 通道优先级：solo_agent(0) > solo_work_lite(1) > 其它
        {"function": "solo_work_lite", "config_info_list": [
            entry("glm-5.2"),                                        # 无档位
            entry("kimi-k3", options=["light", "high"], support=True),
            entry("skip-usage", usage="multimodal"),                 # 过滤：非对话用途
            entry("skip-off", enabled=False),                        # 过滤：上游停用
            entry("skip-hidden", hidden=True),                       # 过滤：官方隐藏
        ]},
        {"function": "solo_agent", "config_info_list": [
            # 规则①：空档位不得覆盖有档位 —— 同 id 在更靠前通道只有空档位时，保留有档位那条
            entry("kimi-k3", options=[], support=False),
            # 规则②：两侧都有档位 → 取优先级更靠前的通道（solo_agent）
            entry("qwen-3.7-plus", options=["light", "high"], support=True),
        ]},
        {"function": "solo_agent_remote", "config_info_list": [
            entry("qwen-3.7-plus", options=["light"], support=True),  # 被规则②挡掉
            entry("glm-5.2", options=["light", "high"], support=True),  # 规则③：后覆盖前
        ]},
    ]}
    seen = _install_http(monkeypatch, {const.PATH_BATCH_MODELS: httpx.Response(200, json=body)})
    listed = await product.list_models(dict(CRED), {})
    by_id = {m.id: m for m in listed}
    assert set(by_id) == {"glm-5.2", "kimi-k3", "qwen-3.7-plus"}
    assert by_id["glm-5.2"].effort_levels == ("light", "high")       # 规则③ + 档位
    assert by_id["glm-5.2"].reasoning is True
    assert by_id["kimi-k3"].effort_levels == ("light", "high")        # 规则① 保住有档位那条
    assert by_id["qwen-3.7-plus"].effort_levels == ("light", "high")  # 规则② 取 solo_agent
    assert by_id["glm-5.2"].context_window == 200_000                # 取 dev（不是 max）
    assert by_id["glm-5.2"].max_output == 32_000
    assert by_id["glm-5.2"].image_input is True                      # display_config.multimodal
    assert by_id["glm-5.2"].tool_call is None                        # 远端无该字段 → 不编造
    request = seen[0]
    assert json.loads(request.content)["functions"] == list(const.MODELS_FUNCTIONS)
    assert len(const.MODELS_FUNCTIONS) == 22
    headers = {k.lower(): v for k, v in request.headers.items()}
    assert headers["authorization"] == "Cloud-IDE-JWT AT-1"
    assert headers["x-machine-id"] == "m" * 32
    assert headers["x-device-id"] == "d" * 32          # SOLO 族用登录期 hex32
    assert headers["x-uid"] == UID


async def test_list_models_reads_device_fields_from_meta_channel(monkeypatch):
    """导入账号（凭据无设备字段）→ 设备字段走 `meta` 正式通道（§22.3 ③）。"""
    seen = _install_http(monkeypatch, {const.PATH_BATCH_MODELS: httpx.Response(
        200, json={"function_configs": []})})
    await product.list_models({"access_token": "AT-1", "uid": UID},
                              {"machine_id": "M" * 32, "login_device_id": "L" * 32})
    headers = {k.lower(): v for k, v in seen[0].headers.items()}
    assert headers["x-machine-id"] == "M" * 32
    assert headers["x-device-id"] == "L" * 32


async def test_list_models_remote_failure_falls_back(monkeypatch):
    """远端非 2xx / 网络失败 / 空目录 → 整体回退兜底表（`trae-product.ts:167`）。"""
    for route in (_html(500), _raise(httpx.ConnectError, "down"),
                  httpx.Response(200, json={"function_configs": []})):
        _install_http(monkeypatch, {const.PATH_BATCH_MODELS: route})
        listed = await product.list_models(dict(CRED), {})
        assert len(listed) == 28 and listed[0].id == "DeepSeek-V4-Flash-Official"


# ============ 额度 ============

async def test_quota_three_states(monkeypatch):
    """三态：available / exhausted / **unknown（未知不当零）**（§22.3 + `23 B2`）。"""
    packs = {"user_entitlement_pack_list": [
        {"entitlement_base_info": {"display_desc": "每月登录赠送",
                                   "quota": {"credits_limit": 500}},
         "usage": {"credits_amount": 120}, "expire_time": 1_790_783_999},
        {"entitlement_base_info": {"display_desc": "签到奖励", "quota": {"credits_limit": 150}},
         "usage": {"credits_amount": 150}},
    ]}
    _install_http(monkeypatch, {const.PATH_ENT_USAGE: httpx.Response(200, json=packs)})
    snapshot = await product.quota(dict(CRED), {})
    assert snapshot.state == "available" and snapshot.source == "trae-ent-usage"
    assert "380" in snapshot.detail

    # 资源包列表存在但有效包合计为 0 → exhausted（确实为 0）
    empty_packs = {"user_entitlement_pack_list": [
        {"entitlement_base_info": {"quota": {"credits_limit": 0}}, "usage": {}}]}
    _install_http(monkeypatch, {const.PATH_ENT_USAGE: httpx.Response(200, json=empty_packs)})
    assert (await product.quota(dict(CRED), {})).state == "exhausted"

    for route in (_html(500), _raise(httpx.ConnectError, "down"),
                  httpx.Response(200, json={}),                     # 结构变更：无包列表
                  httpx.Response(200, json={"user_entitlement_pack_list": []})):
        _install_http(monkeypatch, {const.PATH_ENT_USAGE: route})
        assert (await product.quota(dict(CRED), {})).state == "unknown"
    # 缺 uid / 缺 token：不发请求，报 unknown（不冒充 0）
    seen = _install_http(monkeypatch, {})
    assert (await product.quota({"access_token": "AT-1"}, {})).state == "unknown"
    assert (await product.quota({}, {})).state == "unknown"
    assert seen == []


async def test_quota_uses_uid_from_meta_when_credential_lacks_it(monkeypatch):
    """uid 也认 `meta` 通道（§22.3③）—— 导入的老凭据可能没有 uid 字段。"""
    seen = _install_http(monkeypatch, {const.PATH_ENT_USAGE: httpx.Response(
        200, json={"user_entitlement_pack_list": [
            {"entitlement_base_info": {"quota": {"credits_limit": 10}}, "usage": {}}]})})
    snapshot = await product.quota({"access_token": "AT-1"}, {"uid": UID})
    assert snapshot.state == "available"
    headers = {k.lower(): v for k, v in seen[0].headers.items()}
    assert headers["x-device-id"] == protocol.derive_device_id15(UID)


# ============ 契约表 ============

def test_hooks_table_and_implemented_are_consistent():
    """`_HOOKS` 齐全；`_IMPLEMENTED` **不含** `login_poll`（骨架纪律仍需生效）；
    `build_out` 自 **M6-5c** 起接线（原「M6-5 TODO」护栏按波次转正）。"""
    assert set(product._HOOKS) == {
        "meta", "login_start", "login_poll", "login_callback", "refresh", "probe",
        "quota", "claim", "list_models", "build_out"}
    for name, fn in product._HOOKS.items():
        assert fn is getattr(product, name)
    assert "login_poll" not in product._IMPLEMENTED
    assert "build_out" in product._IMPLEMENTED


def test_build_out_is_wired_to_the_solo_adapter():
    """`build_out` 自 M6-5c 起接线（原「M6-5 TODO」护栏在此**按波次转正**）：
    返回 trae 自己的 custom 协议适配器（**不套 `FamilyOpenAIOut`** —— SOLO 请求塑形与
    跨行 SSE 成帧都是产品私有的，§22.4）；路径 = 取证值 `/api/agent/v3/llm_utils_chat`
    （`trae.ts:44`，`trae-adapter.ts:1175`）。

    行为判据（SOLO 请求塑形 / 跨行 SSE 成帧 / 错误映射 / 端到端）在
    `tests/integration/test_trae_out.py`；本用例只钉「接线本身成立」。
    """
    import asyncio

    from model_gateway.adapters.product_out import ProductAccount
    from model_gateway.upstream.trae.out import TraeOut

    account = ProductAccount(product=product.PRODUCT, name="acc-1", base_url=const.AGENT_HOST)
    adapter = product.build_out(account)
    assert isinstance(adapter, TraeOut)
    assert (adapter.product, adapter.account_ref) == ("trae", "acc-1")
    assert adapter.protocol == "custom"                          # §22.4：custom 协议
    assert adapter.chat_path == "/api/agent/v3/llm_utils_chat"   # trae.ts:44
    assert adapter.base_url == const.AGENT_HOST
    asyncio.run(adapter.aclose())


def test_const_hosts_match_registry_base_url():
    """注册表 `base_url` 与产品层 `AGENT_HOST` **必须同值**（资源物化读注册表）。"""
    from model_gateway.accounts.registry import get as registry_get

    assert registry_get("trae").base_url == const.AGENT_HOST == "https://trae-api-cn.mchost.guru"
    assert protocol.callback_url() == "http://127.0.0.1:18080/authorize"
    assert const.UG_HOST == "https://api.trae.cn"
    assert const.OAUTH_HOST == "https://api.trae.com.cn"


def test_display_nickname_priority():
    """展示名顺序：手机号 → 邮箱 → ScreenName → uid（`trae.ts:569-582`）。"""
    assert protocol.display_nickname("130******00", "", "用户1", UID, "fb") == "130******00"
    assert protocol.display_nickname("", "a@b.c", "用户1", UID, "fb") == "a@b.c"
    assert protocol.display_nickname("", "", "用户1", UID, "fb") == "用户1"
    assert protocol.display_nickname("", "", "", UID, "fb") == UID
    assert protocol.display_nickname("", "", "", "", "fb") == "fb"


def test_mojibake_nickname_is_repaired():
    """回调昵称双重编码乱码的修复（`trae-oauth.ts:216-232`）。"""
    garbled = "用户8847".encode("utf-8").decode("latin-1")
    assert protocol.fix_nickname_mojibake(garbled, UID) == "用户8847"
    # 修不动且无 CJK → 回退「用户+uid 末 4 位」（不把乱码写进凭据）
    assert protocol.fix_nickname_mojibake("Óû§8847309959", UID) == "用户" + UID[-4:]
    # 纯 ASCII 的 roundtrip 是恒等变换（与 DSH 的 Buffer.from(...latin1) 同结果）→ 原样
    assert protocol.fix_nickname_mojibake("abc", UID) == "abc"


def test_jwt_exp_fallback_and_readers():
    """`expires_at` 的 JWT 兜底（`trae.ts:519-524`）+ JSON 读取三件套的严格性。"""
    import base64

    payload = base64.urlsafe_b64encode(json.dumps({"exp": 1_790_000_000}).encode()).decode()
    token = f"h.{payload}.s"
    assert protocol.jwt_expires_at_ms(token) == 1_790_000_000 * 1000
    assert protocol.jwt_expires_at_ms("not-a-jwt") is None
    exchange = protocol.ExchangeResult(access_token=token)
    assert protocol.expires_at_ms(exchange, token, now_ms=0) == str(1_790_000_000 * 1000)
    assert protocol.expires_at_ms(protocol.ExchangeResult(access_token="x"), "x", now_ms=0) == ""
    # 布尔读取只认明确取值（缺失 ≠ false，`trae.ts:1431`）
    assert protocol.read_bool({"a": True}, "a") is True
    assert protocol.read_bool({"a": "false"}, "a") is False
    assert protocol.read_bool({"a": "yes"}, "a") is None
    assert protocol.read_bool({}, "a") is None
    # 业务码：数字 / 数字字符串都认；缺失 = 0（照抄 `readClaimCode`）
    assert protocol.read_code({"code": "9074"}) == 9074
    assert protocol.read_code({"code": 12}) == 12
    assert protocol.read_code({}) == 0


def test_read_num_filters_nan_and_inf():
    """R2a-F-1（2026-10-06 第三轮对账）：json.loads 会照收 NaN/Infinity 字面量
    （Python 默认允许）⇒ 读入口必须过滤，否则下游 int(nan) 抛未捕获 ValueError
    （trae/protocol.py:608 实证抛点）。"""
    from model_gateway.upstream.trae.protocol import read_num

    assert read_num({"k": float("nan")}, "k") is None
    assert read_num({"k": float("inf")}, "k") is None
    assert read_num({"k": 300}, "k") == 300.0          # 正常值不变
    assert read_num({"k": "300"}, "k") == 300.0        # 字符串形状不变
    assert read_num({"k": "abc"}, "k") is None         # 非数字不猜
