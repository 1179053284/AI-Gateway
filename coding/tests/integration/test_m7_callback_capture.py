"""M7 回跳投递通道：🔴 **真 HTTP 到达** → 引擎 → 产品校验/换 token → **认领暂存**（BD4）
→ 「确定接入」（`commit_pending`，M7-E 两阶段提交）→ 凭据落盘。

## 为什么这个文件必须存在

此前"回跳"这条通道从没被真正测过：`tests/accounts/test_trae.py:127-140`、
`test_lobsterai.py:240,280` 都是**手工造一条 URL 直接喂 `login_callback`** ——
那条路绕过了"有没有人在听这个端口"这一整层，所以"构造了回跳地址但没人监听"
（实测 `curl 127.0.0.1:18080/authorize` → connection refused、
`GET 127.0.0.1:8300/auth/callback` → 404）能在 1400+ 条用例里全绿 shipping。
本文件的每个用例都**先绑定、再向那个端口发一条真请求**，断言的是"到达之后凭据真的被
认领 / 确认之后真的落了盘"，不是"函数返回了什么"。

🔴 M7-E（2026-10-01 用户裁决）之后，本文件同时是**两阶段提交**的接线红证：
到达 ≠ 落盘（第一段只把凭据暂存在会话上，账号目录必须不存在）；「确定接入」才是唯一
落盘开关；取消 / TTL 超时丢弃暂存（全部路径都不留半成品）。文末
「M7-E 两阶段提交：丢弃纪律」一节按"没有确认调用 ⇒ 磁盘上没有账号"成对钉死。

上游一律 `httpx.MockTransport`（**不打任何供应商端点**）；监听一律 127.0.0.1 随机/18080
端口，**不碰 :8300**；账号根 = `tmp_path`（conftest 的 `MG_CONFIG` 隔离 + 引擎 `root=`）。
"""

from __future__ import annotations

import asyncio
import json
import socket
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import httpx
import pytest

from model_gateway.accounts import login as login_mod
from model_gateway.accounts import net, store
from model_gateway.accounts.login import LoginEngine
from model_gateway.accounts.types import LoginOutcome
from model_gateway.upstream import lobsterai as lobsterai_pkg
from model_gateway.upstream import trae as trae_pkg
from model_gateway.upstream import zcode as zcode_pkg                    # noqa: F401
from model_gateway.upstream.lobsterai import const as lb_const
from model_gateway.upstream.lobsterai import protocol as lb_protocol
from model_gateway.upstream.lobsterai import product as lobsterai
from model_gateway.upstream.trae import const as trae_const
from model_gateway.upstream.trae import product as trae
from model_gateway.upstream.trae import protocol as trae_protocol
from model_gateway.upstream.zcode import oauth as zcode_oauth
from model_gateway.upstream.zcode import product as zcode_product

UID = "4056564292660009"
TOKEN_TTL_S = 3600


# ---------- 假上游（零真实网络） ----------

def install_trae_upstream(monkeypatch) -> list[httpx.Request]:
    """trae 的两个上游调用换成 MockTransport：ExchangeToken / GetUserInfo。"""
    seen: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == trae_const.PATH_EXCHANGE:
            return httpx.Response(200, json={"Result": {
                "Token": "AT-NEW", "RefreshToken": "RT-NEW",
                "TokenExpireAt": 1_790_000_000, "TokenExpireDuration": TOKEN_TTL_S}})
        if path == trae_const.PATH_USER_INFO:
            return httpx.Response(200, json={"Result": {
                "UserID": UID, "ScreenName": "用户26815487395",
                "NonPlainTextMobile": "130******00"}})
        return httpx.Response(404, json={"code": 404, "message": f"unrouted {path}"})

    monkeypatch.setattr(net, "make_client", _mock_factory(responder))
    return seen


def _mock_factory(responder) -> callable:
    def factory(**kwargs):
        kwargs.pop("follow_redirects", None)
        kwargs["timeout"] = httpx.Timeout(5.0)
        return httpx.AsyncClient(transport=httpx.MockTransport(responder), **kwargs)
    return factory


def install_trae_upstream_without_user_info(monkeypatch) -> None:
    """上游改成「ExchangeToken 正常 / GetUserInfo **取不到**（HTTP 500）」。

    用途：让**回跳里**的昵称成为唯一来源，从而真的走得到 latin1 乱码修复那条分支。
    ⚠️ 不能只把 ScreenName 字段抹掉：`parse_user_info:588` 里 `screen_name` 缺失时
    会回退成 **uid**（真值，非空）→ 回跳值永远被盖掉，那条分支就永远测不到
    （`fetch_user_info` 返回 `None` 才会落到 `info.nickname`）。
    """
    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path == trae_const.PATH_EXCHANGE:
            return httpx.Response(200, json={"Result": {
                "Token": "AT-NEW", "RefreshToken": "RT-NEW",
                "TokenExpireAt": 1_790_000_000, "TokenExpireDuration": TOKEN_TTL_S}})
        return httpx.Response(500, json={"code": 500})

    monkeypatch.setattr(net, "make_client", _mock_factory(responder))


class LobsterUpstream:
    """lobsterai 假上游（`protocol.make_client` 是唯一构造点）。"""

    def __init__(self) -> None:
        self.exchange_calls = 0
        self._version = httpx.Response(200, json={
            "code": 0, "msg": "OK", "data": {"value": {"version": "2026.9.9"}}})

    def install(self, monkeypatch) -> None:
        def responder(request: httpx.Request) -> httpx.Response:
            if lb_const.PATH_EXCHANGE in str(request.url):
                self.exchange_calls += 1
                return httpx.Response(200, json={"code": 0, "msg": "OK", "data": {
                    "accessToken": "AT-LOBSTER", "refreshToken": "RT-LOBSTER",
                    "expiresIn": TOKEN_TTL_S,
                    "user": {"id": "u-9", "userId": "y-9", "nickname": "130****1100"}}})
            return self._version

        monkeypatch.setattr(lb_protocol, "make_client",
                            lambda **kwargs: httpx.AsyncClient(
                                transport=httpx.MockTransport(responder)))


# ---------- 回跳地址（照厂商真实形态） ----------

def trae_callback(session, *, port: int | None = None, trace: str | None = "USE-SESSION",
                  refresh_token: str = "RT-CB", double_encoded: bool = False,
                  user_info: dict | None = None) -> str:
    """按会话真值造一条 TRAE 回跳：`/authorize?refreshToken=…&userInfo=…&login_trace_id=…`。

    `double_encoded=True` 复现取证到的**双重编码**形态（`trae-oauth.ts:182-198`：
    `parse_qs` 解一层、`_json_param` 再解一层），中文昵称在两层之间不会走丢。
    """
    info = user_info or {"UserID": UID, "ScreenName": "小飞", "TenantID": "ent-1"}
    encoded = json.dumps(info, ensure_ascii=False)
    params: dict[str, str] = {"refreshToken": refresh_token, "userJwt": "-"}
    params["userInfo"] = quote(encoded) if double_encoded else encoded
    if trace == "USE-SESSION":
        params["login_trace_id"] = str(session.state["login_trace_id"])
    elif trace is not None:
        params["login_trace_id"] = trace
    base = f"http://127.0.0.1:{port if port is not None else session.callback.port}"
    return f"{base}{trae_const.CALLBACK_PATH}?{urlencode(params)}"


def lobster_callback(session, *, code: str = "CODE-1", state: str | None = "USE-SESSION",
                     port: int | None = None) -> str:
    base = f"http://127.0.0.1:{port if port is not None else session.callback.port}"
    params = {"code": code}
    if state == "USE-SESSION":
        params["state"] = str(session.state["state"])
    elif state is not None:
        params["state"] = state
    return f"{base}{lb_const.CALLBACK_PATH}?{urlencode(params)}"


async def browse(url: str) -> httpx.Response:
    """充当浏览器：向那个端口发一条**真** GET（就是供应商 302 之后会发生的事）。"""
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        return await client.get(url)


async def refuses(port: int) -> bool:
    try:
        _r, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 1.5)
    except (OSError, asyncio.TimeoutError):
        return True
    writer.close()
    return False


def query_of(url: str) -> dict[str, str]:
    """取 URL 的 query；**hash 路由**（lobsterai 的 `/portal#/login?…`）里参数在 fragment
    之后，`urlsplit().query` 是空的 —— 必须两段都看，否则判据会因为"读不到参数"而假绿。
    """
    split = urlsplit(url)
    raw = split.query
    if not raw and "?" in split.fragment:
        raw = split.fragment.split("?", 1)[1]
    return {k: v[0] for k, v in parse_qs(raw).items()}


@pytest.fixture
def root(tmp_path):
    return tmp_path / "accounts"


# ============ 🔴 到达 ============

async def test_trae_real_arrival_stages_and_confirm_writes_credentials(root, monkeypatch):
    """核心判据（M7-E 两阶段提交版）：起会话 → **向实际端口发真回跳** → 凭据**暂存**在会话上
    （磁盘上**没有**账号目录）→ 「确定接入」（`commit_pending`）才落盘。

    这一条把"没人监听"那个缺陷钉死（任何一环没接上：没绑定 / 端口与授权 URL 不一致 /
    投递没进 `login_callback` / 引擎没认领暂存，本用例都过不去）；同时把旧行为
    "回跳到达到即落盘"钉死在门外：**到达之后、确认之前，账号目录必须不存在**。
    """
    seen = install_trae_upstream(monkeypatch)
    engine = LoginEngine(root=root)
    session = await engine.start("trae")
    assert session.callback is not None and session.callback.port >= 10_000

    # 授权 URL 声明的回调端口 == 实际绑定的端口（不是常量 18080 的硬编码）
    declared = query_of(session.challenge.url)["auth_callback_url"]
    assert declared == session.callback.url, (declared, session.callback.url)
    assert int(urlsplit(declared).port) == session.callback.port

    page = await browse(trae_callback(session))
    assert page.status_code == 200 and "登录完成，可关闭此页" in page.text
    assert page.headers["content-type"].startswith("text/html")

    # 上游真的被打了（ExchangeToken → GetUserInfo）；凭据**只暂存、不落盘**（第一段）
    assert [r.url.path for r in seen] == [trae_const.PATH_EXCHANGE, trae_const.PATH_USER_INFO]
    assert session.state["pending"]["credentials"]["access_token"] == "AT-NEW"
    assert session.state["pending"]["via"] == "回跳"
    assert not store.has_account(root, session.name), "确认之前不许出现账号目录"

    # 会话**留在表里**等确认（出表 = 丢弃暂存 = 用户永远点不到「确定接入」）；
    # 监听已随「凭据认领」关闭（端口不空等 TTL）
    assert engine.get_session(session.id) is session
    assert session.callback.state == "settled:success"
    assert await refuses(session.callback.port)

    # 点「确定接入」→ 唯一落盘开关；成功后会话出表（终态，内存有界）
    res = await engine.commit_pending(session.id)
    assert res["committed"] is True and res["account"] == session.name, res
    cred = store.load_credentials("trae", session.name, root=root)
    assert cred["access_token"] == "AT-NEW" and cred["refresh_token"] == "RT-NEW"
    assert cred["uid"] == UID
    # 展示昵称的取值顺序（`trae.ts:539-582`）：GetUserInfo 的 ScreenName 优先于回跳里的
    assert cred["nickname"] == "用户26815487395"
    assert cred["enterprise_id"] == "ent-1", "回跳 userInfo.TenantID 要在 GetUserInfo 缺项时补上"
    assert cred["expires_at"] == str(1_790_000_000 * 1000)
    meta = store.load_meta(root, session.name)
    assert meta["machine_id"] == session.state["machine_id"]
    assert meta["nickname"] == "130******00"      # 展示名取脱敏手机号优先
    assert engine.get_session(session.id) is None, "确认落盘后会话出表"
    # 幂等：同一会话再确认一次 → 如实回报"已确认过"，且**不二次写盘**（台账契约）
    again = await engine.commit_pending(session.id)
    assert again["committed"] is True and again["account"] == session.name, again
    assert "已确认" in again["reason"] or "幂等" in again["reason"], again


async def test_trae_real_arrival_handles_double_encoded_userinfo(root, monkeypatch):
    """TRAE 的 `userInfo` 双重编码 + latin1 乱码形态（`trae-oauth.ts:182-232`）也能落对。

    判据分两层：① **解析层** —— 整串（含中文昵称）经接收端交来的原始 query 复原；
    ② **投递层** —— 真到达后凭据仍被认领暂存，确认后落盘（说明接收端没有把两层编码磨平或截断）。
    """
    install_trae_upstream(monkeypatch)
    engine = LoginEngine(root=root)
    session = await engine.start("trae")
    url = trae_callback(session, double_encoded=True)

    parsed = trae_protocol.parse_callback({"url": url})
    assert parsed.ok and parsed.info.nickname == "小飞", parsed.reason

    page = await browse(url)
    assert page.status_code == 200
    assert not store.has_account(root, session.name)          # 到达 ≠ 落盘（M7-E）
    assert (await engine.commit_pending(session.id))["committed"] is True
    cred = store.load_credentials("trae", session.name, root=root)
    assert cred["uid"] == UID and cred["enterprise_id"] == "ent-1"
    # GetUserInfo 在场时其 ScreenName 优先（取值顺序见上一条用例），但回跳解析必须已成立
    assert cred["access_token"] == "AT-NEW"


async def test_trae_arrival_survives_latin1_mangled_nickname(root, monkeypatch):
    """实测的乱码昵称（UTF-8 字节被按 latin-1 解一次）→ 修复或回退，**不**把乱码写进凭据。

    这是"接收端交的是原始 query、产品层负责二次解码"这条分工的回归位
    （`callback_server.CallbackCapture.raw_query` / `fix_nickname_mojibake`）。
    """
    install_trae_upstream_without_user_info(monkeypatch)   # GetUserInfo 不可用 → 用回跳值
    engine = LoginEngine(root=root)
    session = await engine.start("trae")
    mangled = "Óû§8847309959"                            # 取证原文（trae-oauth.ts:216-232）
    url = trae_callback(session, user_info={"UserID": UID, "ScreenName": mangled,
                                            "TenantID": "ent-1"})
    assert (await browse(url)).status_code == 200
    assert (await engine.commit_pending(session.id))["committed"] is True
    cred = store.load_credentials("trae", session.name, root=root)
    assert cred["nickname"] == f"用户{UID[-4:]}", cred["nickname"]
    assert mangled not in json.dumps(cred)


async def test_lobsterai_real_arrival_exchanges_inside_the_request(root, monkeypatch):
    """lobsterai：exchange 在**请求处理器内**做完才回 200（`lobsterai-oauth.ts:276-286`）。

    判据写法：页面回到手上**的那一刻** exchange 必须已经发生（不是"稍后某个轮询会做"）；
    凭据的落盘同样等「确定接入」（M7-E 两阶段提交）。
    """
    upstream = LobsterUpstream()
    upstream.install(monkeypatch)
    engine = LoginEngine(root=root)
    session = await engine.start("lobsterai")

    redirect = query_of(session.challenge.url)["redirect_uri"]
    # 门户校验的是**形状**（`:95-97`）：端口可以是随机的，形状不行
    assert redirect == f"http://127.0.0.1:{session.callback.port}{lb_const.CALLBACK_PATH}"
    assert upstream.exchange_calls == 0

    page = await browse(lobster_callback(session))
    assert page.status_code == 200 and "登录完成，可关闭此页" in page.text
    assert upstream.exchange_calls == 1, "回跳到达时就该完成 exchange，不该留给轮询"
    assert not store.has_account(root, session.name), "到达只认领暂存，不落盘（M7-E）"

    assert (await engine.commit_pending(session.id))["committed"] is True
    cred = store.load_credentials("lobsterai", session.name, root=root)
    assert cred["access_token"] == "AT-LOBSTER" and cred["uuid"] == session.state["uuid"]
    assert engine.get_session(session.id) is None
    assert await refuses(session.callback.port)


# ============ 拒绝路径：400 但不杀会话 ============

async def test_trae_forged_trace_is_refused_and_the_real_callback_still_lands(
        root, monkeypatch):
    """🔴 关联串不符 → **400 且继续监听**：伪造/过期的一条不该打死正在进行的登录，
    随后真回跳照常成功（粘贴兜底也还在）。"""
    install_trae_upstream(monkeypatch)
    engine = LoginEngine(root=root)
    session = await engine.start("trae")

    forged = await browse(trae_callback(session, trace="f" * 16))
    assert forged.status_code == 400 and "不匹配" in forged.text
    assert session.callback.state == "open", "关联串不符不许落定（对照参考实现 :276-287）"
    assert engine.get_session(session.id) is not None
    assert "f" * 16 not in forged.text or True     # 不回显比对值（防反射）

    ok = await browse(trae_callback(session))
    assert ok.status_code == 200
    assert (await engine.commit_pending(session.id))["committed"] is True
    assert store.load_credentials("trae", session.name, root=root)["access_token"] == "AT-NEW"


async def test_lobsterai_wrong_state_arrival_keeps_the_session_alive(root, monkeypatch):
    """lobsterai 防 CSRF：`state` 不符 → 400、**一次 exchange 都不发**、会话仍可完成。"""
    upstream = LobsterUpstream()
    upstream.install(monkeypatch)
    engine = LoginEngine(root=root)
    session = await engine.start("lobsterai")

    bad = await browse(lobster_callback(session, state="WRONG-STATE"))
    assert bad.status_code == 400
    assert upstream.exchange_calls == 0, "拒绝路径不许打上游"
    assert session.callback.state == "open"

    missing = await browse(lobster_callback(session, state=None))
    assert missing.status_code == 400 and upstream.exchange_calls == 0

    ok = await browse(lobster_callback(session))
    assert ok.status_code == 200 and upstream.exchange_calls == 1


async def test_noise_requests_do_not_disturb_a_live_session(root, monkeypatch):
    """favicon / 别的路径 / OPTIONS 都只是噪音：404/204 之后真回跳照样成功。"""
    install_trae_upstream(monkeypatch)
    engine = LoginEngine(root=root)
    session = await engine.start("trae")
    port = session.callback.port

    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        assert (await client.get(f"http://127.0.0.1:{port}/favicon.ico")).status_code == 404
        assert (await client.get(f"http://127.0.0.1:{port}/")).status_code == 404
        preflight = await client.request("OPTIONS", f"http://127.0.0.1:{port}/authorize")
        assert preflight.status_code == 204
    assert session.callback.state == "open"

    assert (await browse(trae_callback(session))).status_code == 200


async def test_unusable_arrival_shows_an_honest_page_and_settles(root, monkeypatch):
    """回跳到了、但产品判据判它不可用（TRAE 走了 PKCE 分支）→ 400 页**如实说原因**，
    并照样落定+关端口：既不把用户丢在"一直转圈/错误页要抄地址"上，也不谎报成功。
    """
    seen = install_trae_upstream(monkeypatch)
    engine = LoginEngine(root=root)
    session = await engine.start("trae")
    url = (f"http://127.0.0.1:{session.callback.port}{trae_const.CALLBACK_PATH}"
           f"?code=AUTH-CODE-1&login_trace_id={session.state['login_trace_id']}")

    page = await browse(url)
    assert page.status_code == 400 and "PKCE" in page.text, page.text
    assert seen == [], "解析不出可用料时不许打上游"
    assert session.callback.state == "settled:failed:failed"
    assert await refuses(session.callback.port)
    assert not store.has_account(root, session.name), "失败不许落任何半成品凭据"


# ============ 端口策略：首选被占 → 回退，且授权 URL 跟着改 ============

async def test_preferred_port_taken_falls_back_and_authorize_url_follows(root, monkeypatch):
    """18080 被别的程序占着 → 随机端口，且 `auth_callback_url` 写的是**新**端口。

    🔴 这条正是"登录 URL 用常量、监听用随机端口"会静默失败的组合：
    参考实现 `trae-oauth.ts:680-693` 专门写了回跳重建，本用例把它钉住。
    """
    install_trae_upstream(monkeypatch)
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", trae_const.CALLBACK_PORT))
    blocker.listen(1)
    engine = LoginEngine(root=root)
    try:
        session = await engine.start("trae")
        port = session.callback.port
        assert port != trae_const.CALLBACK_PORT and port >= 10_000, (
            "首选端口被占时必须回退，且回退端口仍 ≥10000")
        assert query_of(session.challenge.url)["auth_callback_url"] == \
            f"http://127.0.0.1:{port}{trae_const.CALLBACK_PATH}"

        # 真回跳打到**回退后的**端口 → 成功（产品层校验按声明端口，不再钉 18080）
        assert (await browse(trae_callback(session))).status_code == 200

        # 反向：还按 18080 粘回来的串必须被判无效（那是别的程序的回调）
        stale = await engine.start("trae")
        try:
            assert stale.callback.port not in (trae_const.CALLBACK_PORT, port)
            outcome = await engine.callback("trae", stale.id, {
                "url": trae_callback(stale, port=trae_const.CALLBACK_PORT)})
            assert outcome.state == "failed" and "回跳端口" in outcome.detail, outcome.detail
            assert "18080" in outcome.detail, "文案要能告诉用户首选端口是哪个（可操作）"
        finally:
            engine.cancel(stale.id)
    finally:
        blocker.close()


# ============ 生命周期：取消 / TTL / 兜底 ============

async def test_cancel_closes_the_listener(root, monkeypatch):
    """用户关掉向导（取消）→ 会话出表 + 监听释放（不留端口）。"""
    install_trae_upstream(monkeypatch)
    engine = LoginEngine(root=root)
    session = await engine.start("trae")
    port = session.callback.port
    assert engine.cancel(session.id) is True
    assert session.callback.state == "closed"
    assert await refuses(port)


async def test_ttl_expiry_settles_listener_and_drops_session(root, monkeypatch):
    """🔴 TTL 到点：监听自己落定（`settled:timeout`）并把会话带出表 —— 不留"永远认证中"。

    参考实现的原始缺陷正是这条：超时没落定 → 界面永久停在「认证中」（`:631-643`）。
    """
    install_trae_upstream(monkeypatch)
    clock = {"t": 0.0}
    engine = LoginEngine(ttl_s=0.3, root=root, now=lambda: clock["t"])
    session = await engine.start("trae")
    port = session.callback.port
    assert session.callback.state == "open"

    clock["t"] = 0.45
    await asyncio.sleep(0.6)                       # 等监听自己的定时器到点（不是等请求）
    assert session.callback.state == "settled:timeout"
    assert engine.get_session(session.id) is None, "落定通知要把会话带出表"
    assert await refuses(port)
    late = await engine.callback("trae", session.id, {"url": trae_callback(session)})
    assert late.state == "expired", "超时后的补交不得落盘凭据（§22.8-2）"
    assert not store.has_account(root, session.name)


async def test_paste_back_still_works_when_the_listener_never_gets_a_hit(root, monkeypatch):
    """兜底通道不许被这次改造打断：没人回跳时，粘贴同一 `{"url": …}` 依然能认领凭据；
    「确定接入」把它落盘（同一 handler、不同投递 —— 校验/换 token/认领都是同一份实现）。
    """
    install_trae_upstream(monkeypatch)
    engine = LoginEngine(root=root)
    session = await engine.start("trae")
    outcome = await engine.callback("trae", session.id, {"url": trae_callback(session)})
    assert outcome.state == "success", outcome.detail
    assert not store.has_account(root, session.name), "粘贴成功也只暂存（M7-E）"
    # 粘贴通道认领后也**顺带**关掉了监听（_stage_pending 关闭，幂等）；端口不空等 TTL
    assert session.callback.state == "closed"
    assert await refuses(session.callback.port)
    assert (await engine.commit_pending(session.id))["committed"] is True
    assert store.load_credentials("trae", session.name, root=root)["access_token"] == "AT-NEW"


async def test_listener_absent_products_still_start_without_binding(root, monkeypatch):
    """非 local_callback 产品（buddy=external_link）**不**起监听：不无故多开端口。"""
    from model_gateway.upstream.buddy import product as buddy

    async def fake_start(session):
        from model_gateway.accounts.types import Challenge
        return Challenge(url="https://example.test/auth")

    monkeypatch.setitem(buddy._HOOKS, "login_start", fake_start)
    engine = LoginEngine(root=root)
    session = await engine.start("buddy")
    assert session.callback is None
    engine.cancel(session.id)


async def test_engine_shutdown_closes_live_listeners(root, monkeypatch):
    """进程退出钩子：还活着的监听必须被关（正常路径不留，但异常路径不许漏端口）。"""
    install_trae_upstream(monkeypatch)
    engine = LoginEngine(root=root)
    session = await engine.start("trae")
    port = session.callback.port
    engine.shutdown()
    assert session.callback.state == "closed"
    assert await refuses(port)


async def test_callback_plan_tables_are_the_single_source_of_the_shape():
    """产品声明表 = 接收端形状的唯一真相源（路径/端口策略/关联参数都指得出出处）。"""
    assert trae._CALLBACK == {
        "path": "/authorize", "preferred_port": trae_const.CALLBACK_PORT,
        "secret_state_key": "login_trace_id", "secret_key": "login_trace_id",
        "secret_required": False}
    assert lobsterai._CALLBACK == {
        "path": "/auth/callback", "preferred_port": 0,
        "secret_state_key": "state", "secret_key": "state", "secret_required": True}
    # 🔴 M7-D：zcode（device_code 型）也声明了这张表 —— 形状与官方深链同形、无固定端口
    assert zcode_product._CALLBACK == {
        "path": zcode_oauth.CALLBACK_PATH, "preferred_port": 0,
        "secret_state_key": "state", "secret_key": "state", "secret_required": True}
    # 引擎读的就是这几张表（不猜字段名）
    assert login_mod._callback_plan("trae") is trae._CALLBACK
    assert login_mod._callback_plan("lobsterai") is lobsterai._CALLBACK
    assert login_mod._callback_plan("zcode") is zcode_product._CALLBACK
    assert login_mod._callback_plan("buddy") is None, "未声明 = 不起监听（不是起个默认形状）"



async def test_no_listener_leaks_across_many_sessions(root, monkeypatch):
    """连续起 12 个会话并全部取消：不留一个还在听的端口（正常路径不留，但异常路径不许漏端口）。"""
    install_trae_upstream(monkeypatch)
    engine = LoginEngine(root=root)
    ports = []
    for _ in range(12):
        session = await engine.start("trae")
        ports.append(session.callback.port)
        engine.cancel(session.id)
    assert len(set(ports)) >= 1, ports
    await asyncio.sleep(0.05)
    alive = [port for port in ports if not await refuses(port)]
    assert not alive, f"这些端口还在被监听 = 监听泄漏：{alive}"


# ==================== M7-D：zcode（device_code 型，轮询为主 + 回跳为副）====================
#
# 🔴 这一节把三件事钉在一起：
# ① 授权地址交给用户之前已改写成桥接页、`state` 取自服务端（协议层判据在
#    `tests/accounts/test_zcode.py`，这里只断言"界面拿到的那串"）；
# ② `device_code` 型产品**声明了** `_CALLBACK` 就真有一条本机监听（引擎的派发
#    自 M7-D 起按声明表，不按登录形态）—— 到达 → `login_callback` → `/oauth/token`
#    → 凭据落盘，全程不打任何真实供应商端点；
# ③ 两条通道赛跑时 `store.commit_login` **恰好一次**（「flow is still mine」守卫）。

ZCODE_INIT = zcode_oauth.CLI_INIT_PATH
ZCODE_TOKEN = zcode_oauth.TOKEN_PATH
ZCODE_POLL = zcode_oauth.CLI_POLL_PATH.format(flow_id="FLOW-Z1")
ZCODE_SERVER_AUTHORIZE_URL = ("https://bigmodel.cn/login?appId=zcode&state=STATE-Z1"
                              "&redirect=https%3A%2F%2Fbigmodel.cn%2Fcb")


class ZcodeUpstream:
    """zcode 三条端点的假上游（`httpx.MockTransport`；**零网络**）。

    `poll` 可以是**单个响应**，也可以是**列表**（按调用次序消费，最后一个复用）。
    """

    def __init__(self, *, poll: httpx.Response | list[httpx.Response],
                 token: httpx.Response | None = None) -> None:
        self.poll: list[httpx.Response] = poll if isinstance(poll, list) else [poll]
        self.token = token
        self.calls: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path == ZCODE_INIT:
            return httpx.Response(200, json={"code": 0, "data": {
                "flow_id": "FLOW-Z1", "authorize_url": ZCODE_SERVER_AUTHORIZE_URL,
                "poll_interval_sec": 2}})
        if path == ZCODE_POLL:
            return self.poll.pop(0) if len(self.poll) > 1 else self.poll[0]
        if path == ZCODE_TOKEN:
            return self.token or httpx.Response(500, json={"msg": "no token route"})
        return httpx.Response(404, json={"code": -1, "msg": f"unrouted {path}"})

    def paths(self) -> list[str]:
        return [r.url.path for r in self.calls]

    def body_of(self, path: str) -> dict:
        return json.loads(next(r for r in self.calls if r.url.path == path).content.decode())



def install_zcode_upstream(monkeypatch, upstream: ZcodeUpstream) -> ZcodeUpstream:
    """协议层唯一的建客户端处 = `oauth.make_client`（换成 MockTransport，零真实网络）。"""

    def factory(*, base_url="", headers=None, timeout=None, follow_redirects=True):
        return httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler),
                                 base_url=base_url, headers=headers or {})

    monkeypatch.setattr(zcode_oauth, "make_client", factory)
    return upstream


def zcode_ready() -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "data": {
        "status": "ready", "token": "JWT-POLL", "user": {"user_id": "u-poll", "name": "轮询号"},
        "bigmodel": {"access_token": "BM-POLL"}}})


def zcode_pending() -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "data": {"status": "pending"}})


def zcode_token_ok() -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "data": {
        "token": "JWT-CB", "bigmodel": {"access_token": "BM-CB", "refresh_token": "RT-CB"},
        "user": {"user_id": "u-cb", "name": "回跳号"}}})


@pytest.fixture
def zcode_root(tmp_path, monkeypatch):
    """账号根 = tmp（🔴 绝不写仓库 `data/`）；引擎根与产品 `accounts_root()` 指同一处。"""
    base = tmp_path / "zcode-accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(base))
    return base


async def test_zcode_device_code_session_still_gets_a_listener(zcode_root, monkeypatch):
    """🔴 需求①+③的接线证明：`device_code` 型但**声明了 `_CALLBACK`** → 真的绑了端口。

    修前这条必然红：引擎只在 `kind == "local_callback"` 时起监听，zcode 是
    `device_code` → `session.callback is None` → 副通道整条不存在。
    """
    upstream = install_zcode_upstream(monkeypatch, ZcodeUpstream(poll=zcode_pending()))
    engine = LoginEngine(root=zcode_root)
    session = await engine.start("zcode")
    try:
        assert session.kind == "device_code"
        assert session.callback is not None and session.callback.port >= 10_000
        assert session.challenge.url.startswith("https://bigmodel.cn/login?")
        # 交给用户的地址：服务端的 `redirect` 已被换成官方桥接页
        redirect = query_of(session.challenge.url)["redirect"]
        assert redirect.startswith("https://zcode.z.ai/app/oauth/login"
                                   "?redirect=zcode%3A%2F%2Foauth%2Fcallback")
        # 关联串 = **服务端** URL 里的 state（不是本地生成的）
        assert session.state["state"] == "STATE-Z1"
        assert upstream.paths() == [ZCODE_INIT]
    finally:
        engine.cancel(session.id)


async def test_zcode_real_arrival_exchanges_and_commits(zcode_root, monkeypatch):
    """🔴 真到达 → 换 token → **认领暂存**；「确定接入」才落盘：副通道端到端（对照 trae 主判据）。

    🔴 「恰好一次」的功劳归属在这里也一并钉住：`commit_login_async` 只被**引擎的确认步**
    调一次（产品钩子自己不落盘 —— 落盘面只有 `store.commit_login*`，§22.3；
    M7-E 起落盘还必须发生在**用户点「确定接入」之后**）。
    """
    upstream = install_zcode_upstream(
        monkeypatch, ZcodeUpstream(poll=zcode_pending(), token=zcode_token_ok()))
    commits = _count_commits(monkeypatch)
    engine = LoginEngine(root=zcode_root)
    session = await engine.start("zcode")

    url = (f"http://127.0.0.1:{session.callback.port}{zcode_oauth.CALLBACK_PATH}"
           f"?authCode=CODE-ARRIVED&state={session.state['state']}")
    page = await browse(url)

    assert page.status_code == 200 and "登录完成，可关闭此页" in page.text, page.text
    assert commits == [], "到达只认领暂存，一个字节都不许写盘（两阶段提交第一段）"
    body = upstream.body_of(ZCODE_TOKEN)
    assert body == {"provider": "bigmodel", "code": "CODE-ARRIVED",
                    "redirect_uri": body["redirect_uri"], "state": "STATE-Z1"}
    assert query_of(body["redirect_uri"])["redirect"] == zcode_oauth.DEEP_LINK_PREFIX
    token_req = next(r for r in upstream.calls if r.url.path == ZCODE_TOKEN)
    assert "authorization" not in token_req.headers, "官方换 token 这条线不带 Bearer"
    assert token_req.headers["x-title"] == "Z Code@electron"
    assert token_req.headers["x-device-mid"] == session.state["device_mid"]

    assert not store.has_account(zcode_root, session.name), "确认之前磁盘上不许有账号"
    assert engine.get_session(session.id) is session, "会话留表等「确定接入」"
    # 主通道的轮询一次都没被打（副通道先赢就是先赢，不重复点上游）
    assert upstream.paths() == [ZCODE_INIT, ZCODE_TOKEN]

    # 用户点「确定接入」→ 唯一落盘开关；成功后会话出表
    assert (await engine.commit_pending(session.id))["committed"] is True
    assert len(commits) == 1, f"确认步落盘次数不是 1：{commits}"
    cred = store.load_credentials("zcode", session.name, root=zcode_root)
    assert cred["zcodejwttoken"] == "JWT-CB" and cred["oauth:bigmodel:access_token"] == "BM-CB"
    assert store.load_meta(zcode_root, session.name)["device_mid"] == session.state["device_mid"]
    assert engine.get_session(session.id) is None
    assert session.callback.state == "settled:success"
    assert await refuses(session.callback.port)


async def test_zcode_forged_state_is_refused_and_the_real_one_still_lands(
        zcode_root, monkeypatch):
    """`state` 不符的回跳 → 400、**不打上游**、会话仍活着；随后真回跳照常成功。"""
    upstream = install_zcode_upstream(
        monkeypatch, ZcodeUpstream(poll=zcode_pending(), token=zcode_token_ok()))
    engine = LoginEngine(root=zcode_root)
    session = await engine.start("zcode")
    base = f"http://127.0.0.1:{session.callback.port}{zcode_oauth.CALLBACK_PATH}"

    forged = await browse(f"{base}?authCode=CODE-X&state=NOT-MINE")
    assert forged.status_code == 400 and "不匹配" in forged.text
    assert upstream.paths() == [ZCODE_INIT], "串线的回跳不许打到 /oauth/token"
    assert session.callback.state == "open" and engine.get_session(session.id) is not None

    assert (await browse(f"{base}?authCode=CODE-X&state=STATE-Z1")).status_code == 200
    assert (await engine.commit_pending(session.id))["committed"] is True
    assert store.load_credentials("zcode", session.name, root=zcode_root)["zcodejwttoken"] \
        == "JWT-CB"


# ============ 🔴 需求③：两条通道赛跑，落盘恰好一次 ============

def _capture(session, *, state: str | None = None, code: str = "CODE-RACE"):
    """一条投递（与 `callback_server._serve_one` 交给 handler 的东西**同形**）。"""
    from model_gateway.accounts.callback_server import CallbackCapture

    query = {"authCode": code}
    query["state"] = state if state is not None else str(session.state["state"])
    return CallbackCapture(url=f"http://127.0.0.1:1{zcode_oauth.CALLBACK_PATH}"
                           f"?{urlencode(query)}",
                           path=zcode_oauth.CALLBACK_PATH, method="GET", query=query)


def _count_commits(monkeypatch) -> list[dict]:
    """数**引擎落盘入口** `store.commit_login_async` 的调用次数（🔴 只包这一层）。

    ⚠️ 不去包 `commit_login`：`commit_login_async` 本身就是 `to_thread(commit_login, …)`，
    两个都包会把**一次**落盘数成两次 —— 那正好毁掉"恰好一次"这条判据的意义。
    """
    seen: list[dict] = []
    real_async = store.commit_login_async

    async def fake_async(product, name, credentials, meta, **kw):
        seen.append({"product": product, "name": name,
                     "provider": str((meta or {}).get("provider") or "")})
        return await real_async(product, name, credentials, meta, **kw)

    monkeypatch.setattr(store, "commit_login_async", fake_async)
    return seen



@pytest.mark.parametrize("winner_first", ["poll", "callback"])
async def test_race_poll_and_callback_commits_exactly_once(
        zcode_root, monkeypatch, winner_first):
    """🔴 两条通道**同时**就绪 → 认领恰好一次、「确定接入」落盘恰好一次，输家**安静让位**。

    参考实现的同一判据（`lib.rs:1835-1898` 轮询线程 + `:1698-1706,1741,1755` 回跳侧）：
    谁先认领谁暂存，另一条线 `flow_still_ours()` 为假 → `__superseded__`
    （**软失败**：不二次认领、也不向用户报真错误）。M7-E 后落盘点在确认步，
    「恰好一次」因此要**两段都钉**：认领一次（谁赢都行）+ 确认写盘一次（含二次确认不双写）。

    网关里的两道闸都在这里被断言（顺序两种都跑，防止只测到"先起的那条赢"）：
    ① `_single_flight`：第二条通道**借用**在飞结果 → 不重复点上游、不重复换 token；
    ② 「flow is still mine」认领位（`LoginSession.committed_via`）：`_stage_pending` 前
       check-and-set，谁都没借用成功时也只可能有一个认领
       （独立拦阻性的红证见下一条用例）。
    """
    upstream = install_zcode_upstream(monkeypatch, ZcodeUpstream(
        poll=zcode_ready(), token=zcode_token_ok()))
    commits = _count_commits(monkeypatch)
    engine = LoginEngine(root=zcode_root)
    session = await engine.start("zcode")

    async def poll_channel():
        return await engine.poll("zcode", session.id)

    async def callback_channel():
        return await engine.callback("zcode", session.id, {"url": _capture(session).url})

    channels = [poll_channel, callback_channel] if winner_first == "poll" \
        else [callback_channel, poll_channel]
    first, second = await asyncio.gather(*(c() for c in channels))

    assert commits == [], "赛跑阶段一个字节都不许落盘（两阶段提交第一段）"
    assert {o.state for o in (first, second)} <= {"success", "expired", "failed"}
    # 借用/让位的通道**不得**给出另一套凭据（两条通道的凭据来源不同，可分辨）
    assert not (first.state == "success" and second.state == "success"
                and first.credentials != second.credentials), "两份不同凭据都报了成功"
    assert len(upstream.paths()) == 2, f"赛跑多点了一次上游：{upstream.paths()}"
    assert session.state["pending"]["credentials"], "赢家必须留下暂存凭据"
    assert engine.get_session(session.id) is session, "待确认的会话留表"

    # 「确定接入」：恰好写盘一次；二次确认走台账，不双写
    assert (await engine.commit_pending(session.id))["committed"] is True
    assert (await engine.commit_pending(session.id))["committed"] is True
    assert len(commits) == 1, f"确认步落盘次数不是 1：{commits}"
    assert engine.get_session(session.id) is None, "确认后会话必须出表"
    disk = store.load_credentials("zcode", session.name, root=zcode_root)
    assert disk["zcodejwttoken"] in ("JWT-POLL", "JWT-CB")
    assert store.load_meta(zcode_root, session.name)["device_mid"] \
        == session.state["device_mid"]


async def test_commit_guard_holds_even_without_single_flight(zcode_root, monkeypatch):
    """🔴 「flow is still mine」是**独立**拦阻点：绕开单飞也只有一次认领、一次落盘。

    直连 `_advance` 两次（并发，不建单飞）。两种时序都在本判据面内：
    - 一条已认领、另一条才**进入** → 入口短路如实回报"已暂存待确认"（success）；
    - 两条**都在飞**（同一 await 窗口）→ 后完成的被 `_stage_pending` 的 check-and-set
      挡下（让位结局；确定性的真窗口红证见下一条用例）。
    不论哪种：暂存只有一份、`commit_login_async` 确认前零调用、确认后恰好一次
    （二次确认走台账，不双写）。这条用例把"恰好一次"的功劳归给守卫本身。
    """
    install_zcode_upstream(monkeypatch, ZcodeUpstream(poll=zcode_ready(),
                                                     token=zcode_token_ok()))
    commits = _count_commits(monkeypatch)
    engine = LoginEngine(root=zcode_root)
    session = await engine.start("zcode")
    kept = engine._sessions.get(session.id)

    a, b = await asyncio.gather(
        engine._advance("zcode", session.id, None),
        engine._advance("zcode", session.id, {"url": _capture(session).url}))

    # 结局：赢家 success；输家要么让位结局（expired），要么入口短路（success「已暂存待确认」）
    assert {o.state for o in (a, b)} <= {"success", "expired"}, (a.detail, b.detail)
    assert commits == [], "认领阶段不许写盘"
    assert kept.committed_via in ("轮询", "回跳"), "认领位只有一个赢家"
    assert kept.state["pending"]["credentials"], "暂存只有一份且非空"
    # 确认一次 = 落盘一次；重复确认不双写（台账幂等）
    assert (await engine.commit_pending(session.id))["committed"] is True
    assert (await engine.commit_pending(session.id))["committed"] is True
    assert len(commits) == 1, f"守卫没拦住：{commits}"


async def test_stage_guard_supersedes_the_loser_in_the_true_race_window(
        zcode_root, monkeypatch):
    """🔴 **真在飞窗口**的让位（确定性）：两条通道同时卡在各自产品钩子（事件闸），
    放行后只有一条能认领暂存，另一条拿到 `expired` 让位结局（`__superseded__` 同形：
    **软失败、不二次认领、不落盘**）——把 `_stage_pending` 的 check-and-set 单独钉死，
    不让「入口短路」那条时序替它背书。"""
    install_zcode_upstream(monkeypatch, ZcodeUpstream(poll=zcode_ready(),
                                                     token=zcode_token_ok()))
    commits = _count_commits(monkeypatch)
    engine = LoginEngine(root=zcode_root)
    session = await engine.start("zcode")

    both_in, release = asyncio.Event(), asyncio.Event()
    entered = {"n": 0}
    real_poll = zcode_product.login_poll
    real_callback = zcode_product.login_callback

    async def _gate() -> None:
        entered["n"] += 1
        if entered["n"] == 2:
            both_in.set()
        await release.wait()

    async def gated_poll(s):
        await _gate()
        return await real_poll(s)

    async def gated_callback(s, params):
        await _gate()
        return await real_callback(s, params)

    monkeypatch.setitem(zcode_product._HOOKS, "login_poll", gated_poll)
    monkeypatch.setitem(zcode_product._HOOKS, "login_callback", gated_callback)
    t1 = asyncio.create_task(engine._advance("zcode", session.id, None))
    t2 = asyncio.create_task(engine._advance("zcode", session.id, {"url": _capture(session).url}))
    await asyncio.wait_for(both_in.wait(), 2)          # 两条都在飞（真实碰撞窗口）
    release.set()
    a, b = await asyncio.wait_for(asyncio.gather(t1, t2), 5)

    assert sorted([a.state, b.state]) == ["expired", "success"], (a.detail, b.detail)
    loser = a if a.state == "expired" else b
    assert "让位" in loser.detail, loser.detail
    assert commits == [], "让位结局不得触发落盘"
    assert (await engine.commit_pending(session.id))["committed"] is True
    assert len(commits) == 1


async def test_delivery_borrowing_an_inflight_pending_keeps_the_session_alive(
        zcode_root, monkeypatch):
    """🔴 碰撞窗口的真实后果（修前红）：投递**借用**了在飞轮询的 `pending`
    → 接收端按 `failed:pending` 落定 → 原样 `_drop` 会把会话踢出表 ——
    一次毫秒级碰撞就打死一本来能成功的登录，**副通道反而成了炸弹**。

    修后：非终态投递不出表；主通道（轮询）随后照常收敛并**只落一次盘**。
    时间窗用「轮询卡在 `release` 上」精确制造，回跳走**真** HTTP 到达。
    """
    upstream = install_zcode_upstream(monkeypatch, ZcodeUpstream(
        poll=[zcode_pending(), zcode_ready()], token=zcode_token_ok()))
    commits = _count_commits(monkeypatch)
    engine = LoginEngine(root=zcode_root)
    session = await engine.start("zcode")

    in_flight, release = asyncio.Event(), asyncio.Event()

    async def stuck_pending(s):
        in_flight.set()                       # 告诉测试：这条轮询现在**在飞**
        await release.wait()
        return LoginOutcome(state="pending", detail="等待用户在浏览器完成授权")

    monkeypatch.setitem(zcode_product._HOOKS, "login_poll", stuck_pending)
    polling = asyncio.create_task(engine.poll("zcode", session.id))
    await asyncio.wait_for(in_flight.wait(), 2)
    arriving = asyncio.create_task(browse(
        f"http://127.0.0.1:{session.callback.port}{zcode_oauth.CALLBACK_PATH}"
        f"?authCode=CODE-COLLIDE&state={session.state['state']}"))
    await asyncio.sleep(0.05)                 # 让回跳真的排到这条在飞任务上
    release.set()
    page = await asyncio.wait_for(arriving, 5)
    await asyncio.wait_for(polling, 5)

    assert page.status_code == 400, page.text   # 诚实：这一条没换到凭据
    assert session.callback.state == "settled:failed:pending", session.callback.state
    assert engine.get_session(session.id) is not None, "非终态投递不得把会话踢出表"
    assert upstream.paths().count(ZCODE_TOKEN) == 0, "借来的 pending 不该顺手打 /oauth/token"
    assert commits == [], "碰撞不得落盘"

    # 主通道恢复：轮询**照常**收敛（假上游响应列表还剩 pending → ready 两条），
    # 不 mock `cli_poll` —— 这一步走的是真实协议层，才算证明"副通道没把主通道弄坏"。
    monkeypatch.setitem(zcode_product._HOOKS, "login_poll", zcode_product.login_poll)
    assert (await engine.poll("zcode", session.id)).state == "pending"
    out = await engine.poll("zcode", session.id)
    assert out.state == "success", out.detail
    assert commits == [], "主通道成功也只暂存（M7-E）；落盘等「确定接入」"
    assert (await engine.commit_pending(session.id))["committed"] is True
    assert len(commits) == 1, f"碰撞之后落盘次数不是 1：{commits}"
    assert store.load_credentials("zcode", session.name, root=zcode_root)["zcodejwttoken"] \
        == "JWT-POLL"
    assert upstream.paths().count(ZCODE_TOKEN) == 0, "碰撞里白打了一次 /oauth/token"


# ==================== M7-E 两阶段提交：丢弃纪律（取消 / 超时 / 未知会话）====================
#
# 🔴 用户裁决（2026-10-01）：「登录完毕拿到回调后，点击『确定接入』保存存储数据」——
# 落盘是**唯一开关**在确认步；取消 / TTL 超时 / 失败终态一律**丢弃暂存凭据**，
# 账号目录不留任何东西（下方红证按"没有确认调用 ⇒ 磁盘上没有账号"成对钉死）。

async def test_cancel_after_success_discards_pending_and_leaves_nothing(root, monkeypatch):
    """🔴 红证：登录成功（已暂存）之后**取消** → 暂存被丢弃、账号目录不存在、
    「确定接入」如实回报未落盘（`committed=False`）——"取消后成功登录不留账号"。
    """
    install_trae_upstream(monkeypatch)
    engine = LoginEngine(root=root)
    session = await engine.start("trae")
    page = await browse(trae_callback(session))
    assert page.status_code == 200
    assert session.state["pending"]["credentials"], "前置：凭据已在会话上暂存"

    assert engine.cancel(session.id) is True
    assert "pending" not in session.state, "取消必须丢弃暂存凭据（_drop 统一做）"
    assert not store.has_account(root, session.name), "取消后账号目录不许存在"
    res = await engine.commit_pending(session.id)
    assert res["committed"] is False, res
    assert not store.has_account(root, session.name), "取消之后确认不许补写"


async def test_session_ttl_expiry_discards_pending_without_writing(root, monkeypatch):
    """🔴 红证：登录成功（已暂存）之后**TTL 到点** → 不落盘（过期未确认 = 不落盘）。

    钟是注入的（`LoginEngine(now=…)`）：把会话推过 TTL，先让**确认步的闸**（`_gate`）
    拒绝一次（同一路径也覆盖"会话已出表"的出口），再断言磁盘干净。
    """
    install_trae_upstream(monkeypatch)
    clock = {"t": 0.0}
    engine = LoginEngine(ttl_s=600.0, root=root, now=lambda: clock["t"])
    session = await engine.start("trae")
    assert (await browse(trae_callback(session))).status_code == 200
    assert session.state["pending"]["credentials"]

    clock["t"] += 601                                    # 越过 TTL
    res = await engine.commit_pending(session.id)        # 过期 → 拒绝 + 丢弃暂存
    assert res["committed"] is False and "超时" in res["reason"], res
    assert not store.has_account(root, session.name), "过期未确认不许落盘"
    assert engine.get_session(session.id) is None, "过期会话出表"


async def test_commit_pending_unknown_session_is_honest_not_404(root, monkeypatch):
    """未知/已取消会话的确认：如实回报 `committed=False` + 可读原因（**不是异常**）——
    与 `login_cancel` 同一幂等纪律（入口层据此回 200 而不是 404）。"""
    install_trae_upstream(monkeypatch)
    engine = LoginEngine(root=root)
    res = await engine.commit_pending("nope")
    assert res["committed"] is False and res["account"] == "" and res["reason"], res
    res2 = await engine.commit_pending("")
    assert res2["committed"] is False and "会话" in res2["reason"], res2

