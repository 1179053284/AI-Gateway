"""`loomy` 产品钩子单测（tech-design v2.0 §22.4 行；`20 §2.6/§2.8/§3.1/§3.3`、`21 §1.1`）。

🔴 假上游（`httpx.MockTransport`）：**无网络、无真实凭据**。逐条对应取证判据：

- **扫码为主**：**网关代取微信那张 JPEG**（M7-C1：`qr_payload` = 图片 data URI，取图与铸 uuid
  同一组 UA + Referer）→ 长轮询的 **404 = 已扫码待确认 / 405 = 已确认**（DSH 真实缺陷的读反，
  `loomy-wechat.ts:243-248`）；402/403 → **就地换发一张新码**（不再判终态）；单轮读预算 2s，
  不把管理端请求挂在微信的 40s 长轮询上；
- **短信两段**（`login.sendSms`/`submitSms` 语义，经 `_ALT_HOOKS` 的 `sms_send`/`sms_submit`）：
  `login/phone/sendMsgCode` → `checkCode`；微信首次登录的绑手机号走 `thirdAccount/bind/*`；
- **不可续期**：`refresh` → `NotRefreshable`（`loomy.ts:198-205`）；
- **两池额度**：`balance`（永久）+ `dailyBalance`（每日赠送），**未知不当零**；
- **签到**：`POST /points/first-login`，幂等判据 `alreadyProcessed`，本次额度 =
  `dailyQuota − dailyConsumed`（**不是 +5000**）；
- **新手任务**：8 任务 10000 分，**按本地分值表现算**（服务端 `earned` 不采信），`100002` 立即中断；
- **模型目录**：远端 `/api/v1/models`（只认 `token` 头）取 `type==='chat'` + 8 条兜底表。

⚠️ 判据里出现的模型 id / 分值都是**假上游数据**（与真上游无关），只有**契约**（端点路径、
请求体字段、状态机、算式、幂等判据）照 DSH 取证。
"""

from __future__ import annotations

import asyncio
import hmac as hmac_mod
import hashlib
import inspect
import json
import re
import time
from base64 import b64encode
from types import SimpleNamespace

import httpx
import pytest

from model_gateway.accounts import registry, store
from model_gateway.accounts import login as accounts_login
from model_gateway.accounts import qr
from model_gateway.accounts.login import LoginEngine
from model_gateway.accounts.types import (
    Challenge, ClaimOutcome, NotRefreshable, ProbeResult, QuotaSnapshot,
)
from model_gateway.upstream.loomy import api, constants as C, envelope, login as loomy_login
from model_gateway.upstream.loomy import models as loomy_models
from model_gateway.upstream.loomy import product as loomy
from model_gateway.upstream.loomy import sign, wechat

# ============ 假上游 ============

WECHAT_HOST = "open.weixin.qq.com"
WECHAT_LONG_HOST = "long.open.weixin.qq.com"
ACCOUNT_HOST = "account.xfinfr.com"
API_HOST = "loomyad.xunfei.cn"


def _api(path: str) -> str:
    """业务端点的**线上路径**：注册表基址含 `/api/v1`（适配器按 `{base_url}/chat/completions` 拼接）。

    ⚠️ 常量里的 `POINTS_RECORDS_PATH` 自带 query（`pageNo/pageSize/recordType`）——
       路由按 `request.url.path` 匹配，故这里剥掉 query 段（query 另在用例里断言）。
    """
    return f"/api/v1{path.split('?', 1)[0]}"


def _ok(data: object = None) -> httpx.Response:
    """业务成功响应 —— ⚠️ Loomy 的业务失败恒 HTTP 200，成败只看 `code`（`loomy.ts:80-104`）。"""
    return httpx.Response(200, json={"code": C.OK_CODE, "desc": "", "data": data})


def _fail(code: str, desc: str = "") -> httpx.Response:
    """业务失败响应（同样 HTTP 200）。"""
    return httpx.Response(200, json={"code": code, "desc": desc})


class FakeUpstream:
    """按 `(host, path)` 分发的假上游（`httpx.MockTransport` handler 的薄封装）。

    - 路由值 = `httpx.Response`（可复用）｜`list[Response]`（按调用次序消费，最后一个复用）
      ｜`Exception` 实例（抛出，模拟传输层失败）；
    - `calls` 记录全部请求（断言请求体 / 请求头 / 调用次序）；未登记的路径 → 404。
    """

    def __init__(self, routes: dict[tuple[str, str], object]) -> None:
        self.routes = dict(routes)
        self.calls: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        key = (request.url.host, request.url.path)
        route = self.routes.get(key)
        if route is None:
            return httpx.Response(404, json={"error": "no route", "url": str(request.url)})
        if isinstance(route, list):
            route = route.pop(0) if len(route) > 1 else route[0]
        if isinstance(route, Exception):
            raise route
        assert isinstance(route, httpx.Response)
        return route

    def requests_for(self, key: tuple[str, str]) -> list[httpx.Request]:
        return [r for r in self.calls if (r.url.host, r.url.path) == key]

    def count(self, key: tuple[str, str]) -> int:
        return len(self.requests_for(key))

    def body_of(self, key: tuple[str, str]) -> str:
        return self.requests_for(key)[0].content.decode()

    def json_of(self, key: tuple[str, str]) -> dict:
        return json.loads(self.body_of(key))

    def paths(self) -> list[str]:
        return [r.url.path for r in self.calls]


def _patch_clients(monkeypatch, upstream: FakeUpstream) -> None:
    """把三个 IO 模块的 `make_client` 都换成本用例的假上游。

    产品层只有三处建客户端：`api.py`（业务）、`login.py`（讯飞账号）、`wechat.py`（微信）。
    """

    def factory(*, base_url="", headers=None, timeout=None, follow_redirects=True):
        return httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler),
                                 base_url=base_url, headers=headers or {},
                                 timeout=timeout or 30.0)

    for module in (api, loomy_login, wechat):
        monkeypatch.setattr(module, "make_client", factory)


def _session(**state) -> SimpleNamespace:
    """会话替身：钩子只许经 `session.state` 存私态（私态绝不进 Challenge/Outcome）。"""
    return SimpleNamespace(state=dict(state), product="loomy")


def _auth_page(uuid: str) -> httpx.Response:
    """微信授权页（uuid 内嵌在 img src 里；实测无需执行 JS 就能提取）。"""
    return httpx.Response(200, text=(
        f'<html><img class="js_qrcode_img web_qrcode_img" src="/connect/qrcode/{uuid}"/></html>'))


def _long_poll(errcode: str, code: str = "") -> httpx.Response:
    """长轮询响应（官方 JS 读的是 `window.wx_errcode` / `window.wx_code`）。"""
    body = f"<script>window.wx_errcode = {errcode};"
    if code:
        body += f" window.wx_code = '{code}';"
    return httpx.Response(200, text=body + "</script>")


def _verify_account_signature(request: httpx.Request, *,
                              access_key_secret: str = C.ACCOUNT_ACCESS_KEY_SECRET) -> None:
    """独立复算账号请求签名（**逐字节**对照 `loomy-sign.ts` 的算法，防"只序列化一次"回归）。

    用**收到的那份 body**（`request.content`）与收到 `Date`/`Nonce` 重算签名：若 HTTP 层二次
    序列化了 JSON（键序/空格变了），这里必然对不上 → 该断言就是「签名与发送共用同一字符串」的护栏。
    """
    string_to_sign = "\n".join([
        "POST",
        "/".join(sign.escape_rfc3986(seg) if seg else ""
                 for seg in request.url.path.split("/")),
        "",
        b64encode(hashlib.md5(request.content).digest()).decode("ascii"),
        "application/json",
        request.headers["Date"],
        request.headers["Nonce"],
        "", "",
    ])
    expected = b64encode(hmac_mod.new(access_key_secret.encode(), string_to_sign.encode(),
                                      hashlib.sha1).digest()).decode("ascii")
    assert request.headers["Authorization"] == f"account {C.ACCOUNT_ACCESS_KEY_ID}:{expected}"


# ============ 注册表（M6-3 回填）============

def test_registry_backfilled_from_dsh_evidence():
    """`registry` 的 loomy 行：base_url 取证回填（其余字段 M6-1 已冻结，不动）。"""
    meta = registry.get("loomy")
    # `loomy.ts:30` 的 `LOOMY_API_BASE`（推理 / 目录 / 积分 / 新手任务全挂它下面）
    assert meta.base_url == "https://loomyad.xunfei.cn/api/v1" == C.API_BASE
    assert meta.login == "qr" and meta.login_alt == ("sms_code",)      # §22.4 扫码 / 短信
    assert meta.device.fields == () and meta.protocol == "openai"      # 无设备标识
    caps = meta.capabilities
    assert (caps.balance, caps.checkin, caps.onboarding, caps.permanent_lock, caps.refresh) \
        == (True, True, True, True, False)                             # 不可续期（`20 §2.6`）


def test_claim_onboarding_is_registered_optional_hook():
    """§22.3 可选钩子 `claim_onboarding`：进 `_HOOKS`（入口层按表调度）且签名 == 冻结面。"""
    assert loomy._HOOKS["claim_onboarding"] is loomy.claim_onboarding
    assert "claim_onboarding" in loomy._IMPLEMENTED
    signature = inspect.signature(loomy.claim_onboarding)
    assert inspect.iscoroutinefunction(loomy.claim_onboarding)
    assert list(signature.parameters) == ["cred", "meta", "precheck"]
    assert signature.parameters["precheck"].kind is inspect.Parameter.KEYWORD_ONLY
    assert str(signature.return_annotation).strip("'\"") == "ClaimOutcome"
    # `login_callback` 显式失败（非 local_callback 型）→ **不在**已接线清单里；
    # `build_out` 自 **M6-5b** 起接线（原「M6-5 TODO」护栏按波次转正）→ 在清单里。
    frozen = {"meta", "login_start", "login_poll", "login_callback", "refresh", "probe",
              "quota", "claim", "list_models", "build_out"}
    assert set(loomy._HOOKS) == frozen | {"claim_onboarding"}
    # `_IMPLEMENTED` 登记已接线的业务钩子（`meta` 恒从注册表取，按各产品既有口径不入表）
    assert set(loomy._IMPLEMENTED) == frozen - {"meta", "login_callback"} \
        | {"claim_onboarding"}


def test_build_out_is_wired_to_the_family_adapter():
    """`build_out` 自 M6-5b 起接线（原 M6-5 TODO 护栏在此**按波次转正**）：
    返回 openai 族出站适配器；路径 = 基类缺省 `/chat/completions` + 基址已含 `/api/v1`
    = 取证值 `{apiBase}/chat/completions`（`loomy-adapter.ts:483`）。

    行为判据（Bearer + 小写 `token` 双头 / 错误映射 / 端到端）在
    `tests/integration/test_loomy_out.py`；本用例只钉「接线本身成立」。
    """
    from model_gateway.adapters.product_out import ProductAccount
    from model_gateway.upstream.loomy import constants as C
    from model_gateway.upstream.loomy.out import LoomyOut

    account = ProductAccount(product=loomy.PRODUCT, name="acc-1", base_url=C.API_BASE)
    adapter = loomy.build_out(account)
    assert isinstance(adapter, LoomyOut)
    assert (adapter.product, adapter.account_ref) == ("loomy", "acc-1")
    assert adapter.chat_path == "/chat/completions"
    assert adapter.base_url == C.API_BASE
    asyncio.run(adapter.aclose())


async def test_sms_alt_hooks_table_and_no_callback_path():
    """短信两段 = `_ALT_HOOKS`（§22.3 补入③）；旧路（`login_callback` 的动作分派）已删除。

    - 表名/取用面与 raccoon 同形（`sms_send` / `sms_submit`），**不在**十钩子表内；
    - 传参形状：`session` 位置 + kwarg（`phone` / `sms_code`）；
    - `login_callback` 按「非 local_callback 型」显式失败（与 raccoon 同款）。
    """
    assert set(loomy._ALT_HOOKS) == {"sms_send", "sms_submit"}
    for name, fn in loomy._ALT_HOOKS.items():
        assert fn is getattr(loomy, name)
        assert name not in loomy._HOOKS, "备选形态不得混进 §22.3 十钩子冻结契约"
        assert inspect.iscoroutinefunction(fn)
    assert list(inspect.signature(loomy.sms_send).parameters) == ["session", "phone"]
    assert inspect.signature(loomy.sms_send).parameters["phone"].kind \
        is inspect.Parameter.KEYWORD_ONLY
    assert list(inspect.signature(loomy.sms_submit).parameters) == ["session", "sms_code"]
    assert inspect.signature(loomy.sms_submit).parameters["sms_code"].kind \
        is inspect.Parameter.KEYWORD_ONLY
    # 旧动作分派彻底删除：`login.py` 不再有 `callback` 实现，钩子恒显式失败
    assert not hasattr(loomy_login, "callback")
    with pytest.raises(NotImplementedError, match="非 local_callback"):
        await loomy.login_callback(_session(), {"action": "explode"})


# ============ 签名（`loomy-sign.ts` 的逐字节复刻）============

def test_signing_string_composition_and_escaping():
    """9 段拼串：空 query、MD5 段、**以 `\\n\\n` 结尾**、路径逐段转义、method 大写。"""
    string_to_sign = sign.build_signing_string(
        method="post", path="/a b/c/", body='{"a":1}', content_type="application/json",
        date="Thu, 26 Sep 2026 00:00:00 GMT", nonce="n-1")
    lines = string_to_sign.split("\n")
    assert len(lines) == 9
    assert lines[0] == "POST"                       # method 统一大写
    assert lines[1] == "/a%20b/c"                   # 逐段转义 + 剥末尾斜杠
    assert lines[2] == ""                           # 无 query
    assert lines[3] == sign.content_md5('{"a":1}')
    assert lines[4] == "application/json"
    assert lines[5] == "Thu, 26 Sep 2026 00:00:00 GMT"
    assert lines[6] == "n-1"
    assert lines[7] == lines[8] == ""               # signedHeaders / canonicalizedHeaders 恒空
    assert string_to_sign.endswith("\n\n")          # 去掉尾随换行会让签名不匹配
    # query 保持传入顺序、key 与 value 都转义
    other = sign.build_signing_string(method="GET", path="/p", query_params={"b": "2", "a": "1 2"},
                                      date="d", nonce="n")
    assert other.split("\n")[2] == "b=2&a=1%202"
    # `!'()*` 五个字符必须补转（JS encodeURIComponent 不转、Python quote 转 → 结果一致）
    assert sign.escape_rfc3986("a!b'c(d)e*f") == "a%21b%27c%28d%29e%2Af"


def test_content_md5_and_auth_header_shape():
    """空 body → 空串（不发 Content-MD5）；非空 → base64(md5)；前缀是 `account` 不是 Bearer。"""
    assert sign.content_md5("") == ""
    assert sign.content_md5('{"a":1}') == b64encode(
        hashlib.md5(b'{"a":1}').digest()).decode("ascii")
    headers = sign.auth_headers(method="POST", path="/p", body="{}",
                                date="Thu, 26 Sep 2026 00:00:00 GMT", nonce="n-1")
    assert headers["Authorization"].startswith(f"account {C.ACCOUNT_ACCESS_KEY_ID}:")
    assert headers["Content-MD5"] == sign.content_md5("{}")
    assert headers["Content-Type"] == "application/json" and headers["Date"].endswith("GMT")
    assert "Content-MD5" not in sign.auth_headers(method="GET", path="/p", date="d", nonce="n")


# ============ 登录：扫码（主通道）============

async def test_wechat_start_fetches_the_qr_image_with_the_uuid_pairing_headers(monkeypatch):
    """`login_start`：取 uuid → **网关自己带着同一组 UA + Referer 把图取回来** → data URI。

    🔴 M7-C1 换口径（本轮缺陷本体）：旧实现只回 `url = 官方图片地址` 并把 `qr_payload` 留空，
    前端 `<img src="{url}">` 让浏览器自己去取 —— 跨域且带不上 UA/Referer，图必然加载失败。
    现在 `qr_payload` 是 `data:image/jpeg;base64,…`，浏览器只负责显示。
    ⚠️ 私态（uuid/state）只进 `session.state`；图片地址仍留在 `url` 作为可复制的兜底文字。
    """
    image = _qr_jpeg()
    upstream = FakeUpstream({
        (WECHAT_HOST, "/connect/qrconnect"): _auth_page("UUID-abc123"),
        (WECHAT_HOST, "/connect/qrcode/UUID-abc123"): httpx.Response(
            200, content=image, headers={"content-type": "image/jpeg"}),
    })
    _patch_clients(monkeypatch, upstream)
    session = _session()

    challenge = await loomy.login_start(session)

    assert challenge.url == "https://open.weixin.qq.com/connect/qrcode/UUID-abc123"
    assert challenge.qr_payload == "data:image/jpeg;base64," + b64encode(image).decode("ascii")
    assert challenge.device_code == "" and challenge.sms_sent is False
    assert session.state["mode"] == loomy_login.MODE_WECHAT
    assert session.state["wechat_uuid"] == "UUID-abc123"
    assert session.state["wechat_state"] and len(session.state["wechat_state"]) == 32
    assert session.state["last_errcode"] == "" and session.state["qr_reissues"] == 0
    assert "UUID-abc123" not in challenge.qr_payload.replace(b64encode(image).decode("ascii"), "")

    auth, picture = upstream.calls
    # 🔴 取图必须**与铸出该 uuid 的那次页面请求同一 UA、同一 Referer、同一个 uuid**
    assert auth.headers["User-Agent"] == picture.headers["User-Agent"] == C.WECHAT_UA
    assert auth.headers["Referer"] == picture.headers["Referer"] == "https://open.weixin.qq.com/"
    assert str(picture.url).endswith("/connect/qrcode/UUID-abc123")
    # 授权页 URL 里的 redirect_uri 仍是官方白名单地址（换成回环地址会得到「redirect_uri 参数错误」）
    assert "redirect_uri=https%3A%2F%2Floomy.xunfei.cn%2Foauth%2Fwechat%2Fcallback" in str(auth.url)


async def test_wechat_start_degrades_honestly_when_image_fetch_fails(monkeypatch):
    """图片端点坏了：会话照起（uuid 与长轮询都有效），但**不给坏图**，原因由轮询如实播报。"""
    upstream = FakeUpstream({
        (WECHAT_HOST, "/connect/qrconnect"): _auth_page("UUID-abc123"),
        (WECHAT_HOST, "/connect/qrcode/UUID-abc123"): httpx.Response(200, text="<html>404</html>"),
    })
    _patch_clients(monkeypatch, upstream)
    session = _session()

    challenge = await loomy.login_start(session)
    assert challenge.qr_payload == "", "取不到图就不许编一个图片载荷（否则界面是个坏 <img>）"
    assert challenge.url.endswith("/connect/qrcode/UUID-abc123")
    assert session.state["wechat_uuid"] == "UUID-abc123"        # 流程没被打断

    upstream.routes[(WECHAT_LONG_HOST, "/connect/l/qrconnect")] = _long_poll("408")
    outcome = await loomy.login_poll(session)
    assert outcome.state == "pending"
    assert "二维码图片取不到" in outcome.detail and "不是图片" in outcome.detail
    # 播报一次即清：下一轮不再重复同一条原因
    again = await loomy.login_poll(session)
    assert "二维码图片取不到" not in again.detail


@pytest.mark.parametrize("bad", [
    httpx.Response(200, text="<html>error page</html>"),        # 不是图片（无魔数）
    httpx.Response(200, content=b"\xff\xd8\xff" + b"\x00" * 50),  # JPEG 魔数对，但小得离谱
    httpx.Response(503, text="busy"),
])
async def test_qr_image_endpoint_junk_is_refused_not_rendered(monkeypatch, bad):
    """微信图片端点回错误页/半截图 → `fetch_qr_image` 抛错（`wechat.py` 的魔数+尺寸判据）。"""
    from model_gateway.upstream.loomy import wechat as w
    upstream = FakeUpstream({(WECHAT_HOST, "/connect/qrcode/U"): bad})
    _patch_clients(monkeypatch, upstream)
    with pytest.raises(RuntimeError, match="二维码图片|不是图片"):
        await w.fetch_qr_image("U")


async def test_qr_payload_is_an_image_not_a_bare_url_regression(monkeypatch):
    """🔴 钉住本轮缺陷（loomy 半边）：`qr_payload` 是空串或一条裸 URL 时，一律判红。

    本轮之前的实际出口是 `Challenge(url="https://open.weixin.qq.com/connect/qrcode/<uuid>")`
    + `qr_payload=""`，页面把它画成 `<img src="https://…">`：浏览器跨域带不上 UA/Referer →
    一张加载失败的图 + 一行 toast。现在图片必须由服务端代取进 `qr_payload`。
    """
    upstream = FakeUpstream({
        (WECHAT_HOST, "/connect/qrconnect"): _auth_page("UUID-abc123"),
        (WECHAT_HOST, "/connect/qrcode/UUID-abc123"): httpx.Response(200, content=_qr_jpeg()),
    })
    _patch_clients(monkeypatch, upstream)
    challenge = await loomy.login_start(_session())
    assert challenge.qr_payload.startswith("data:image/"), \
        f"回归：qr_payload 又不是图片（{challenge.qr_payload[:60]!r}）"
    assert not re.fullmatch(r"(https?|ftp)://\S+", challenge.qr_payload), "qr_payload 不许是一条裸 URL"


def _qr_jpeg() -> bytes:
    """一张够大的假 JPEG（魔数对 + 超过 `MIN_QR_IMAGE_BYTES`；测的是搬运，不是像素）。"""
    return b"\xff\xd8\xff\xe0" + bytes(range(256)) * 3


async def test_wechat_poll_uses_a_short_read_budget_not_the_40s_ceiling(monkeypatch):
    """🔴 节奏判据（M7-C1）：管理端那一轮用 **2s 读预算**，40s 只留在连接/写/池上。

    旧实现把微信长轮询的 40s 上限原样挂在 `login/poll` 这条**管理端请求**上：
    一次轮询能把一个 admin 请求按住 40 秒。现在读维度收在 `WECHAT_POLL_BUDGET_S`，
    到点即「这一轮没有变化」（见下一条：读超时判 `waiting`，不判网络错误）。
    """
    seen: dict = {}
    upstream = FakeUpstream({(WECHAT_LONG_HOST, "/connect/l/qrconnect"): _long_poll("408")})

    def factory(*, base_url="", headers=None, timeout=None, follow_redirects=True):
        seen["timeout"] = timeout          # 记录产品层**实际传给 httpx 的超时形状**
        return httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler),
                                 base_url=base_url, headers=headers or {},
                                 timeout=timeout or 30.0)

    monkeypatch.setattr(wechat, "make_client", factory)
    await loomy.login_poll(_session(mode="wechat", wechat_uuid="U", last_errcode=""))

    used = seen["timeout"]
    assert isinstance(used, httpx.Timeout), f"长轮询应显式给四段超时，实得 {used!r}"
    assert used.read == C.WECHAT_POLL_BUDGET_S == 2.0, used
    assert used.connect == used.write == used.pool == C.WECHAT_POLL_TIMEOUT_S == 40.0, used


async def test_wechat_read_timeout_counts_as_waiting_not_error(monkeypatch):
    """读预算到点 = 「还没人扫」→ `waiting`（界面停在"等待微信扫码"，不是网络错误横幅）。"""
    upstream = FakeUpstream({(WECHAT_LONG_HOST, "/connect/l/qrconnect"):
                             httpx.ReadTimeout("timed out")})
    _patch_clients(monkeypatch, upstream)
    outcome = await loomy.login_poll(_session(mode="wechat", wechat_uuid="U"))
    assert outcome.state == "pending" and outcome.detail.startswith("等待微信扫码"), outcome.detail
    # 其它传输层异常仍是 error 文案（两者必须分得开，不能一起糊成"继续等待"）
    upstream.routes[(WECHAT_LONG_HOST, "/connect/l/qrconnect")] = httpx.ConnectError("boom")
    again = await loomy.login_poll(_session(mode="wechat", wechat_uuid="U"))
    assert again.state == "pending" and "网络错误" in again.detail, again.detail



async def test_wechat_start_surfaces_failure_without_fake_challenge(monkeypatch):
    """取不到 uuid → 抛 `RuntimeError`（不编造 Challenge；引擎不吞异常，入口层可见）。"""
    upstream = FakeUpstream({
        (WECHAT_HOST, "/connect/qrconnect"): httpx.Response(200, text="<html>no uuid</html>"),
    })
    _patch_clients(monkeypatch, upstream)
    with pytest.raises(RuntimeError, match="未包含二维码 uuid"):
        await loomy.login_start(_session())


async def test_wechat_uuid_extraction_two_paths():
    """uuid 提取两条路径（img src 主路径 / fordevtool 长轮询 URL 兜底），非法值不认。"""
    assert wechat.extract_uuid(
        '<img class="js_qrcode_img" src="/connect/qrcode/0713Y9iC4gqQkl25"/>') == "0713Y9iC4gqQkl25"
    assert wechat.extract_uuid(
        'var fordevtool = "https://long.open.weixin.qq.com/connect/l/qrconnect?uuid=4Y0N_jyVQg=="'
    ) == "4Y0N_jyVQg=="
    assert wechat.extract_uuid("<html>nothing</html>") == ""
    assert wechat.extract_uuid(None) == ""


@pytest.mark.parametrize("errcode,text", [("408", "扫码"), ("404", "确认")])
async def test_wechat_poll_pending_states(monkeypatch, errcode, text):
    """408（待扫码）/ 404（已扫码待确认）都是 `pending`（**不是错误**，§22.3）。"""
    upstream = FakeUpstream({
        (WECHAT_LONG_HOST, "/connect/l/qrconnect"): _long_poll(errcode),
    })
    _patch_clients(monkeypatch, upstream)
    outcome = await loomy.login_poll(_session(mode="wechat", wechat_uuid="U", last_errcode=""))
    assert outcome.state == "pending" and text in outcome.detail
    assert outcome.credentials == {} and outcome.meta == {}
    assert upstream.count((WECHAT_LONG_HOST, "/connect/l/qrconnect")) == 1


async def test_wechat_long_poll_escapes_uuid_and_passes_last(monkeypatch):
    """长轮询 URL：uuid 含 base64 字符要转义；上一轮 errcode 作 `last` 回传（`loomy-wechat.ts:260-262`）。"""
    upstream = FakeUpstream({
        (WECHAT_LONG_HOST, "/connect/l/qrconnect"): _long_poll("404"),
    })
    _patch_clients(monkeypatch, upstream)
    await loomy.login_poll(_session(mode="wechat", wechat_uuid="4Y0N_jyVQg==", last_errcode="408"))
    url = str(upstream.requests_for((WECHAT_LONG_HOST, "/connect/l/qrconnect"))[0].url)
    assert "uuid=4Y0N_jyVQg%3D%3D" in url and "last=408" in url
    # 本轮 errcode（404）记进私态，供下一次轮询作 `last`（网络错误文案不记，见 login.py 注释）
    session = _session(mode="wechat", wechat_uuid="U", last_errcode="")
    upstream.routes[(WECHAT_LONG_HOST, "/connect/l/qrconnect")] = httpx.ConnectError("x")
    await loomy.login_poll(session)
    assert session.state["last_errcode"] == ""


async def test_wechat_poll_network_error_stays_pending(monkeypatch):
    """长轮询网络失败**不终止**流程（`loomy-wechat.ts:272-280`）→ pending + 原因。"""
    upstream = FakeUpstream({
        (WECHAT_LONG_HOST, "/connect/l/qrconnect"): httpx.ConnectError("boom"),
    })
    _patch_clients(monkeypatch, upstream)
    outcome = await loomy.login_poll(_session(mode="wechat", wechat_uuid="U"))
    assert outcome.state == "pending" and "网络错误" in outcome.detail


@pytest.mark.parametrize("errcode,label", [
    ("402", "微信二维码已失效"),      # 二维码失效
    ("403", "你已取消授权"),          # 用户在手机侧撤掉
])
async def test_wechat_poll_402_403_reissue_a_fresh_qr(monkeypatch, errcode, label):
    """402/403 → **换发一张全新的码**（新 state + 新 uuid + 新图），会话继续 pending。

    判据来源 = raccoon 那条同款处置（`raccoon-login-page.ts:213-220` 在 `canceled` 时换新码
    并把新图塞回页面）；DSH 在 loomy 上是"显示『请关闭窗口后重试』"（`loomy-wechat-login.ts:452-459`），
    本波次按任务书把两个产品统一到换发形态（差异登记在 `login._reissue` 的 docstring）。
    🔴 旧的 402→`expired` / 403→`failed` 终态映射已推翻：那会让用户白点一次「重新发起登录」。
    """
    image = _qr_jpeg()
    upstream = FakeUpstream({
        (WECHAT_LONG_HOST, "/connect/l/qrconnect"): _long_poll(errcode),
        (WECHAT_HOST, "/connect/qrconnect"): _auth_page("UUID-second"),
        (WECHAT_HOST, "/connect/qrcode/UUID-second"): httpx.Response(200, content=image),
    })
    _patch_clients(monkeypatch, upstream)
    session = _session(mode="wechat", wechat_uuid="UUID-first", last_errcode="408",
                       qr_reissues=0)
    session.challenge = Challenge(url="https://open.weixin.qq.com/connect/qrcode/UUID-first",
                                  qr_payload="data:image/jpeg;base64,OLD")

    outcome = await loomy.login_poll(session)
    assert outcome.state == "pending", f"换发不是终态：{outcome}"
    assert label in outcome.detail and "换发第 1 张" in outcome.detail, outcome.detail
    # 会话私态整体换新（旧 uuid 已在上游判死，`last` 也必须清零）
    assert session.state["wechat_uuid"] == "UUID-second"
    assert len(session.state["wechat_state"]) == 32
    assert session.state["wechat_state"] != "旧 state"
    assert session.state["last_errcode"] == "" and session.state["qr_reissues"] == 1
    # 新图写回会话的 challenge（入口层在 `login/poll` 响应里带回 → 界面自动换图）
    assert session.challenge.qr_payload == "data:image/jpeg;base64," + b64encode(image).decode()
    assert "UUID-first" not in json.dumps(vars(session.challenge))
    # 下一轮长轮询打的是**新 uuid**
    upstream.routes[(WECHAT_LONG_HOST, "/connect/l/qrconnect")] = _long_poll("408")
    await loomy.login_poll(session)
    poll_url = str(upstream.requests_for((WECHAT_LONG_HOST, "/connect/l/qrconnect"))[-1].url)
    assert "uuid=UUID-second" in poll_url, poll_url


async def test_wechat_reissue_cap_reports_expired(monkeypatch):
    """换发次数到上限 → 如实 `expired`（不无限重铸一张没人扫的码）。"""
    upstream = FakeUpstream({(WECHAT_LONG_HOST, "/connect/l/qrconnect"): _long_poll("402")})
    _patch_clients(monkeypatch, upstream)
    session = _session(mode="wechat", wechat_uuid="U", qr_reissues=qr.MAX_REISSUES)

    outcome = await loomy.login_poll(session)
    assert outcome.state == "expired" and "上限" in outcome.detail, outcome.detail
    assert session.state["qr_reissues"] == qr.MAX_REISSUES      # 不再换发
    assert upstream.calls == [] or all(                          # 只打了判定那一轮，没再要新码
        r.url.host != WECHAT_HOST for r in upstream.calls)


async def test_wechat_reissue_reports_expired_when_new_uuid_fails(monkeypatch):
    """换发时拿不到新 uuid → `expired` + 原因（手里这张码上游已判死，继续 pending 是骗人）。"""
    upstream = FakeUpstream({
        (WECHAT_LONG_HOST, "/connect/l/qrconnect"): _long_poll("403"),
        (WECHAT_HOST, "/connect/qrconnect"): httpx.Response(200, text="<html>no uuid</html>"),
    })
    _patch_clients(monkeypatch, upstream)
    session = _session(mode="wechat", wechat_uuid="U", qr_reissues=0)
    outcome = await loomy.login_poll(session)
    assert outcome.state == "expired" and "重新获取二维码失败" in outcome.detail, outcome.detail



async def test_wechat_poll_without_uuid_fails_closed(monkeypatch):
    """缺私态 → failed 且**不打上游**（fail closed）。"""
    upstream = FakeUpstream({})
    _patch_clients(monkeypatch, upstream)
    outcome = await loomy.login_poll(_session(mode="wechat"))
    assert outcome.state == "failed" and "uuid" in outcome.detail
    assert upstream.calls == []


async def test_wechat_confirmed_with_bound_phone_logs_in(monkeypatch):
    """405 + `wx_code` → `bind/auth`（`bind=1` 已绑手机号）→ `bind/skip` → 凭据成功。

    ⚠️ 404/405 **不得读反**（DSH 真实缺陷：读反会永远卡在「已扫码」，`loomy-wechat.ts:243-248`）。
    """
    upstream = FakeUpstream({
        (WECHAT_LONG_HOST, "/connect/l/qrconnect"): _long_poll("405", "wx-code-1"),
        (ACCOUNT_HOST, "/login/thirdAccount/bind/auth"): _ok(
            {"bind": 1, "rcode": "rc-1", "nickname": "微信昵称"}),
        (ACCOUNT_HOST, "/login/thirdAccount/bind/skip"): _ok(
            {"session": "a" * 32, "userid": "123456789012345678"}),
    })
    _patch_clients(monkeypatch, upstream)
    session = _session(mode="wechat", wechat_uuid="U")
    before = int(time.time() * 1000)

    outcome = await loomy.login_poll(session)

    assert outcome.state == "success" and outcome.detail.startswith("登录成功")
    cred = outcome.credentials
    assert cred["access_token"] == "a" * 32                 # 讯飞 session（32 位小写 hex）
    assert cred["userid"] == "123456789012345678"
    assert cred["phone"] == ""
    # expires_at = 本地按 14 天推算的**毫秒时间戳字符串**（服务端不下发到期时间）
    assert int(cred["expires_at"]) >= before + C.SESSION_TTL_S * 1000
    assert outcome.meta["login_via"] == "wechat" and outcome.meta["nickname"] == "微信昵称"
    # 账号端点全部经 HMAC 签名（前缀 `account`）+ 逐字节可复算
    auth_request = upstream.requests_for((ACCOUNT_HOST, "/login/thirdAccount/bind/auth"))[0]
    _verify_account_signature(auth_request)
    assert upstream.json_of((ACCOUNT_HOST, "/login/thirdAccount/bind/auth"))["param"] == {
        "tcode": {"code": "wx-code-1"}, "type": "wx"}


async def test_wechat_first_login_requires_phone_then_binds(monkeypatch):
    """`bind=0`（首次）→ pending「需绑定手机号」→ 绑手机号两段 → 成功（`loomy-wechat-login.ts:262-287`）。"""
    upstream = FakeUpstream({
        (WECHAT_LONG_HOST, "/connect/l/qrconnect"): _long_poll("405", "wx-code-2"),
        (ACCOUNT_HOST, "/login/thirdAccount/bind/auth"): _ok({"bind": 0, "rcode": "rc-2"}),
        (ACCOUNT_HOST, "/login/thirdAccount/bind/sendMsg"): _ok({"msgid": "msg-bind-1"}),
        (ACCOUNT_HOST, "/login/thirdAccount/bind/checkCode"): _ok(
            {"session": "b" * 32, "userid": "u-2", "phone": "13800138000"}),
    })
    _patch_clients(monkeypatch, upstream)
    session = _session(mode="wechat", wechat_uuid="U")

    first = await loomy.login_poll(session)
    assert first.state == "pending" and "绑定手机号" in first.detail
    assert session.state["mode"] == loomy_login.MODE_WECHAT_BIND

    # 已进入绑定态：再轮询**不打上游**（微信 code 是一次性的，绝不重放）
    again = await loomy.login_poll(session)
    assert again.state == "pending" and upstream.count((WECHAT_LONG_HOST, "/connect/l/qrconnect")) == 1

    # 发码（走绑定端点，不是独立短信登录端点）
    sent = await loomy.sms_send(session, phone="13800138000")
    assert sent.state == "pending" and "验证码已发送" in sent.detail
    assert upstream.count((ACCOUNT_HOST, "/login/phone/sendMsgCode")) == 0
    bind_send = upstream.json_of((ACCOUNT_HOST, "/login/thirdAccount/bind/sendMsg"))
    assert bind_send["param"]["rcode"] == "rc-2" and bind_send["param"]["ccode"] == "86"

    # 提交验证码 → 成功（phone 用服务端回传值）
    done = await loomy.sms_submit(session, sms_code="123456")
    assert done.state == "success"
    assert done.credentials["access_token"] == "b" * 32 and done.credentials["phone"] == "13800138000"
    assert done.meta["login_via"] == "wechat"
    check = upstream.json_of((ACCOUNT_HOST, "/login/thirdAccount/bind/checkCode"))
    assert check["param"] == {"rcode": "rc-2", "mcode": "123456", "msgid": "msg-bind-1",
                             "expire": C.SESSION_TTL_S}


async def test_wechat_bind_sms_rejects_bad_phone_without_upstream(monkeypatch):
    """手机号格式不对 → pending（会话保活，用户可改）+ 可读 detail；**不打上游**。"""
    upstream = FakeUpstream({})
    _patch_clients(monkeypatch, upstream)
    outcome = await loomy.sms_send(_session(mode="wechat_bind", rcode="rc"), phone="123")
    assert outcome.state == "pending" and "11 位有效手机号" in outcome.detail
    assert upstream.calls == []


# ============ 登录：短信（备通道）============

async def test_sms_two_steps_success(monkeypatch):
    """独立短信登录：`sendMsgCode` → `checkCode`（`login.sendSms`/`submitSms` 语义）。"""
    upstream = FakeUpstream({
        (ACCOUNT_HOST, "/login/phone/sendMsgCode"): _ok({"msgid": "msg-1"}),
        (ACCOUNT_HOST, "/login/phone/checkCode"): _ok(
            {"session": "c" * 32, "userid": "u-3"}),
    })
    _patch_clients(monkeypatch, upstream)
    session = _session(mode="wechat", wechat_uuid="U")

    sent = await loomy.sms_send(session, phone="13900139000")
    assert sent.state == "pending" and "139****9000" in sent.detail
    assert session.state["mode"] == loomy_login.MODE_SMS
    send_param = upstream.json_of((ACCOUNT_HOST, "/login/phone/sendMsgCode"))["param"]
    assert send_param == {"ccode": "86", "phone": "13900139000", "expire": C.SMS_CODE_TTL_S}
    _verify_account_signature(upstream.requests_for((ACCOUNT_HOST, "/login/phone/sendMsgCode"))[0])

    # 短信态下 poll 只回 pending，不打上游
    waiting = await loomy.login_poll(session)
    assert waiting.state == "pending" and "等待短信验证码提交" in waiting.detail
    assert upstream.count((WECHAT_LONG_HOST, "/connect/l/qrconnect")) == 0

    done = await loomy.sms_submit(session, sms_code="654321")
    assert done.state == "success"
    assert done.credentials["access_token"] == "c" * 32
    assert done.credentials["phone"] == "13900139000"      # 用发码时存的手机号（不是提交参数）
    assert done.meta["login_via"] == "sms"
    check_param = upstream.json_of((ACCOUNT_HOST, "/login/phone/checkCode"))["param"]
    assert check_param == {"ccode": "86", "phone": "13900139000", "mcode": "654321",
                           "msgid": "msg-1", "expire": C.SESSION_TTL_S}


async def test_sms_wrong_code_keeps_session_retryable(monkeypatch):
    """验证码错误 → pending（**会话保活**，DSh 同语义：登录失败不删条目，允许重试）+ 复提成功。"""
    upstream = FakeUpstream({
        (ACCOUNT_HOST, "/login/phone/sendMsgCode"): _ok({"msgid": "msg-2"}),
        (ACCOUNT_HOST, "/login/phone/checkCode"): [
            httpx.Response(200, json={"code": "010001", "desc": "验证码错误"}),
            _ok({"session": "d" * 32, "userid": "u-4"}),
        ],
    })
    _patch_clients(monkeypatch, upstream)
    session = _session()
    await loomy.sms_send(session, phone="13700137000")

    first = await loomy.sms_submit(session, sms_code="000000")
    assert first.state == "pending" and "验证码错误" in first.detail and first.credentials == {}

    second = await loomy.sms_submit(session, sms_code="111111")
    assert second.state == "success" and second.credentials["access_token"] == "d" * 32
    assert upstream.count((ACCOUNT_HOST, "/login/phone/checkCode")) == 2


async def test_sms_submit_before_send_is_retryable(monkeypatch):
    """未发码先提交 → pending「请先发送验证码」（不打上游）；空验证码同样 pending。

    （旧的「未知动作 → failed」用例随 `login_callback` 动作分派一并删除：动作名不复存在，
    接线错误由 `alt_call` 的表纪律当场 `KeyError` 暴露 —— 见公共层用例。）
    """
    upstream = FakeUpstream({})
    _patch_clients(monkeypatch, upstream)
    early = await loomy.sms_submit(_session(), sms_code="1")
    assert early.state == "pending" and "请先发送验证码" in early.detail
    blank = await loomy.sms_submit(_session(), sms_code="  ")
    assert blank.state == "pending" and "请输入短信验证码" in blank.detail
    assert upstream.calls == []


async def test_sms_send_response_missing_msgid_is_retryable(monkeypatch):
    """发码响应缺 `msgid` → 不当成功（`loomy-oauth.ts:145-149`）→ pending 可重试。"""
    upstream = FakeUpstream({
        (ACCOUNT_HOST, "/login/phone/sendMsgCode"): _ok({}),
    })
    _patch_clients(monkeypatch, upstream)
    outcome = await loomy.sms_send(_session(), phone="13700137000")
    assert outcome.state == "pending" and "缺少 msgid" in outcome.detail


# ============ 登录：经会话引擎（入口层实际路径）============

async def test_engine_end_to_end_commits_credential(tmp_path, monkeypatch):
    """引擎跑真链路（`_HOOKS` 契约表 + `store.commit_login` 写回自检）：pending 不落盘 → success 落盘。"""
    upstream = FakeUpstream({
        (WECHAT_HOST, "/connect/qrconnect"): _auth_page("UUID-engine"),
        (WECHAT_LONG_HOST, "/connect/l/qrconnect"): [
            _long_poll("408"),                      # 第一次轮询：还没扫
            _long_poll("405", "wx-code-e2e"),       # 第二次：已确认
        ],
        (ACCOUNT_HOST, "/login/thirdAccount/bind/auth"): _ok({"bind": 1, "rcode": "rc-e2e"}),
        (ACCOUNT_HOST, "/login/thirdAccount/bind/skip"): _ok(
            {"session": "e" * 32, "userid": "u-e2e"}),
    })
    _patch_clients(monkeypatch, upstream)
    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)

    session = await engine.start("loomy")
    assert session.name.startswith("loomy-")               # 默认名 `{product}-{8hex}`
    pending = await engine.poll("loomy", session.id)
    assert pending.state == "pending" and "扫码" in pending.detail
    assert store.load_credentials("loomy", session.name, root=root) == {}   # pending 不落盘

    outcome = await engine.poll("loomy", session.id)
    assert outcome.state == "success"
    assert not store.has_account(root, session.name), "success 只暂存（M7-E 两阶段提交）"
    assert (await engine.commit_pending(session.id))["committed"] is True
    stored = store.load_credentials("loomy", session.name, root=root)
    assert stored["access_token"] == "e" * 32 and stored["userid"] == "u-e2e"
    meta = store.load_meta(root, session.name)
    assert meta["via"] == "login" and meta["login_via"] == "wechat"
    assert (await engine.poll("loomy", session.id)).state == "expired"      # 确认后出表


async def test_engine_alt_call_path_drives_sms_login(tmp_path, monkeypatch):
    """短信通道的入口 = `login.alt_call`（§22.3 补入③）：`start(kind="sms_code")` → 两段。

    🔴 M7-E 两阶段提交（修前是"第二段成功即落盘"）：短信第二段成功**只认领暂存**，
    与其它四型统一由用户点「确定接入」（`commit_pending`）落盘 —— 五型只有一次确认。
    本用例钉住新行为：第二段成功 → 暂存在会话上（磁盘干净）→ 确认 → `store.commit_login`
    （写回自检 + 失败回滚）把凭据写进该账号目录。
    """
    upstream = FakeUpstream({
        (WECHAT_HOST, "/connect/qrconnect"): _auth_page("UUID-sms"),
        (ACCOUNT_HOST, "/login/phone/sendMsgCode"): _ok({"msgid": "m-9"}),
        (ACCOUNT_HOST, "/login/phone/checkCode"): _ok({"session": "f" * 32, "userid": "u-sms"}),
    })
    _patch_clients(monkeypatch, upstream)
    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)
    session = await engine.start("loomy", kind="sms_code")
    assert session.kind == "sms_code"                  # 形态写进会话（供钩子/入口层读取）

    sent = await accounts_login.alt_call("loomy", session, "sms_send", phone="13600136000")
    assert sent.state == "pending" and "验证码已发送" in sent.detail
    assert store.load_credentials("loomy", session.name, root=root) == {}   # pending 不落盘
    done = await accounts_login.alt_call("loomy", session, "sms_submit", sms_code="808080")
    assert done.state == "success" and done.credentials["userid"] == "u-sms"
    assert not store.has_account(root, session.name), "第二段成功也只暂存（M7-E）"
    assert session.committed_via == "辅助调用（sms_submit）"
    assert (await engine.commit_pending(session.id))["committed"] is True
    stored = store.load_credentials("loomy", session.name, root=root)
    assert stored["access_token"] == "f" * 32 and stored["userid"] == "u-sms"


# ============ 续期：不可续期 ============

async def test_refresh_is_not_refreshable(monkeypatch):
    """`refresh` 恒 `NotRefreshable`（Loomy 无 refresh 端点；不是故障、不触发冷却）。"""
    upstream = FakeUpstream({})
    _patch_clients(monkeypatch, upstream)
    with pytest.raises(NotRefreshable, match="无 refresh 端点"):
        await loomy.refresh({"access_token": "x"}, loomy.meta())
    assert upstream.calls == []


# ============ 探活 ============

async def test_probe_valid_and_invalid_paths(monkeypatch):
    """探活两维分开：有效 / `100002` 失效 / 非 JSON / 传输失败 / 无凭据。"""
    records_key = (API_HOST, _api(C.POINTS_RECORDS_PATH))
    upstream = FakeUpstream({records_key: [
        _ok({"balance": 1}),                                   # 有效
        httpx.Response(200, json={"code": C.AUTH_ERROR_CODE, "desc": "缺少 token"}),
        httpx.Response(200, text="<html>oops</html>"),
        httpx.ConnectError("down"),
    ]})
    _patch_clients(monkeypatch, upstream)
    cred = {"access_token": "t" * 32}

    good = await loomy.probe(cred, loomy.meta())
    assert good.ok and good.reachable and good.valid
    dead = await loomy.probe(cred, loomy.meta())
    assert dead.reachable and not dead.valid and "请重新登录" in dead.detail
    not_json = await loomy.probe(cred, loomy.meta())
    assert not_json.reachable and not not_json.valid
    down = await loomy.probe(cred, loomy.meta())
    assert not down.reachable and not down.valid
    empty = await loomy.probe({}, loomy.meta())
    assert not empty.ok and "未发请求" in empty.detail
    # 业务端点只认 `token` 头（带 Bearer 会被判「缺少 token」）
    request = upstream.requests_for(records_key)[0]
    assert request.headers["token"] == "t" * 32 and "Authorization" not in request.headers
    # 探活/额度用最便宜的只读端点：`?pageNo=1&pageSize=1&recordType=all`（`loomy-auth.ts:375`）
    assert dict(request.url.params) == {"pageNo": "1", "pageSize": "1", "recordType": "all"}


# ============ 两池额度 ============

async def test_quota_two_pools_available(monkeypatch):
    """两池分开：永久 15000 + 每日 4992 = 可用 19992（实测形态，`loomy-credits.ts:11-15`）。"""
    upstream = FakeUpstream({
        (API_HOST, _api(C.POINTS_RECORDS_PATH)): _ok(
            {"balance": 15000, "dailyBalance": 4992, "availableBalance": 19992}),
    })
    _patch_clients(monkeypatch, upstream)
    snapshot = await loomy.quota({"access_token": "t"}, loomy.meta())
    assert isinstance(snapshot, QuotaSnapshot)
    assert snapshot.state == "available" and snapshot.source == "loomy-points-records"
    assert "永久积分 15000" in snapshot.detail and "每日赠送 4992" in snapshot.detail
    assert "可用 19992" in snapshot.detail


async def test_quota_available_derives_total_when_missing(monkeypatch):
    """`availableBalance` 缺失时本地相加（不编造第三方字段）。"""
    upstream = FakeUpstream({
        (API_HOST, _api(C.POINTS_RECORDS_PATH)): _ok({"balance": 100, "dailyBalance": 25}),
    })
    _patch_clients(monkeypatch, upstream)
    snapshot = await loomy.quota({"access_token": "t"}, loomy.meta())
    assert snapshot.state == "available" and "可用 125" in snapshot.detail


@pytest.mark.parametrize("route,expect_detail", [
    (_ok({"balance": 0, "dailyBalance": 0, "availableBalance": 0}), "永久积分 0"),   # 真的为 0
    (_ok({"availableBalance": 10}), "缺少 balance"),                                 # 形状不对
    (_fail(C.AUTH_ERROR_CODE, "缺少 token"), "100002"),                              # 凭据失效 ≠ 0
    (httpx.Response(200, text="<html>"), "不是 JSON"),
    (httpx.ConnectError("down"), "网络错误"),
])
async def test_quota_exhausted_vs_unknown(monkeypatch, route, expect_detail):
    """`exhausted`（确实为 0）与 `unknown`（查不到 / 凭据失效 / 结构变更）**严格分开**（§22.3）。"""
    upstream = FakeUpstream({(API_HOST, _api(C.POINTS_RECORDS_PATH)): route})
    _patch_clients(monkeypatch, upstream)
    snapshot = await loomy.quota({"access_token": "t"}, loomy.meta())
    if expect_detail == "永久积分 0":
        assert snapshot.state == "exhausted"
    else:
        assert snapshot.state == "unknown"
    assert expect_detail in snapshot.detail
    assert snapshot.source == "loomy-points-records"


# ============ 签到（每日赠送额度）============

async def test_claim_daily_records_quota_minus_consumed(monkeypatch):
    """签到 = 触发每日赠送额度：本次发放 = `dailyQuota − dailyConsumed`（**不是 +5000**）。"""
    key = (API_HOST, _api(C.POINTS_FIRST_LOGIN_PATH))
    upstream = FakeUpstream({key: _ok({
        "alreadyProcessed": False, "currentBalance": 15000, "permanentBalance": 15000,
        "dailyBalance": 4992, "dailyQuota": 5000, "dailyConsumed": 8,
        "dailyCycleDate": "2026-09-29", "availableBalance": 19992,
    })})
    _patch_clients(monkeypatch, upstream)
    outcome = await loomy.claim({"access_token": "t"}, loomy.meta(), precheck=True)
    assert isinstance(outcome, ClaimOutcome) and outcome.category == "success"
    assert "本次发放 4992 分" in outcome.detail                # 5000 − 8
    assert "dailyQuota 5000" in outcome.detail and "dailyConsumed 8" in outcome.detail
    assert "每日赠送额度（消耗后不回补）" in outcome.detail
    # 请求体为 `{}`（`loomy-credits.ts:216`），且只认 token 头
    request = upstream.requests_for(key)[0]
    assert json.loads(request.content.decode()) == {}
    assert request.headers["token"] == "t" and "Authorization" not in request.headers


async def test_claim_daily_grant_without_numbers_is_not_fabricated(monkeypatch):
    """响应没下发 `dailyQuota`/`dailyConsumed` → 不折算具体分值（不编造 5000）。"""
    upstream = FakeUpstream({
        (API_HOST, _api(C.POINTS_FIRST_LOGIN_PATH)): _ok({"alreadyProcessed": False}),
    })
    _patch_clients(monkeypatch, upstream)
    outcome = await loomy.claim({"access_token": "t"}, loomy.meta(), precheck=False)
    assert outcome.category == "success" and "不折算具体分值" in outcome.detail
    assert "5000" not in outcome.detail


async def test_claim_already_processed_maps_to_already_done(monkeypatch):
    """幂等判据 = 响应体 `alreadyProcessed` → `already_done`（**不是** success，`:202-227`）。"""
    upstream = FakeUpstream({
        (API_HOST, _api(C.POINTS_FIRST_LOGIN_PATH)): _ok(
            {"alreadyProcessed": True, "dailyQuota": 5000, "dailyConsumed": 2,
             "dailyBalance": 4998, "balance": 15000, "availableBalance": 19998}),
    })
    _patch_clients(monkeypatch, upstream)
    outcome = await loomy.claim({"access_token": "t"}, loomy.meta(), precheck=True)
    assert outcome.category == "already_done" and "今日额度已初始化" in outcome.detail
    assert "每日赠送 4998" in outcome.detail


@pytest.mark.parametrize("precheck", [True, False])
async def test_claim_precheck_both_values_do_one_request(monkeypatch, precheck):
    """`precheck` 两取值行为一致（无独立签到状态端点、领取自带幂等判据 → **不做额外预检**）。"""
    key = (API_HOST, _api(C.POINTS_FIRST_LOGIN_PATH))
    upstream = FakeUpstream({key: _ok({"alreadyProcessed": False, "dailyQuota": 5000,
                                       "dailyConsumed": 5000, "dailyBalance": 0,
                                       "balance": 10, "availableBalance": 10})})
    _patch_clients(monkeypatch, upstream)
    outcome = await loomy.claim({"access_token": "t"}, loomy.meta(), precheck=precheck)
    assert outcome.category == "success" and "本次发放 0 分" in outcome.detail
    assert upstream.count(key) == 1


@pytest.mark.parametrize("route,expect", [
    (_fail(C.AUTH_ERROR_CODE, "缺少 token"), "100002"),
    # `100001`（参数错误，`loomy.ts:42`）：与其它业务码一样落 failed + 原始 desc
    (_fail("100001", "参数错误"), "100001"),
    (httpx.Response(200, text="<html>"), "不是 JSON"),
    (httpx.ConnectError("down"), "网络错误"),
])
async def test_claim_daily_failures_are_failed(monkeypatch, route, expect):
    """上游失败（业务码 / 非 JSON / 网络）→ `failed` + 可读原因（不谎报成功）。"""
    upstream = FakeUpstream({(API_HOST, _api(C.POINTS_FIRST_LOGIN_PATH)): route})
    _patch_clients(monkeypatch, upstream)
    outcome = await loomy.claim({"access_token": "t"}, loomy.meta(), precheck=True)
    assert outcome.category == "failed" and expect in outcome.detail


async def test_claim_without_token_fails_closed(monkeypatch):
    """无凭据 → `failed` 且**不打上游**（fail closed）。"""
    upstream = FakeUpstream({})
    _patch_clients(monkeypatch, upstream)
    outcome = await loomy.claim({}, loomy.meta(), precheck=True)
    assert outcome.category == "failed" and "未发请求" in outcome.detail
    assert upstream.calls == []


# ============ 新手任务 ============

async def test_onboarding_computes_points_locally_and_skips_done(monkeypatch):
    """8 任务：只补未完成的、按**本地分值表**现算（服务端 `earned` 谎报也不采信）。"""
    tasks_key = (API_HOST, _api(C.ONBOARDING_TASKS_PATH))
    complete_key = (API_HOST, _api(C.ONBOARDING_COMPLETE_PATH))
    done = {"first_message": True, "pick_skill": True}                  # 已完成 1500 分
    upstream = FakeUpstream({
        # ⚠️ 服务端回传的 earned 是**谎报值**（本地表现算才是真相，`loomy-onboarding.ts:26-28`）
        tasks_key: _ok({"tasks": done, "earned": 99999, "total": 10000}),
        complete_key: _ok({"alreadyCompleted": False, "balance": 1000}),
    })
    _patch_clients(monkeypatch, upstream)

    outcome = await loomy.claim_onboarding({"access_token": "t"}, loomy.meta(), precheck=True)

    assert outcome.category == "success"
    assert "已领取 6 个新手任务共 8500 分" in outcome.detail     # 10000 − 1500
    assert "99999" not in outcome.detail                        # 不采信服务端 earned
    assert "累计 10000/10000 分" in outcome.detail
    posted = [json.loads(r.content.decode())["key"] for r in upstream.requests_for(complete_key)]
    assert posted == [k for k in C.TASK_POINTS if k not in done]   # 本地表顺序、跳过已完成
    assert upstream.count(tasks_key) == 1


async def test_onboarding_all_done_is_already_done(monkeypatch):
    """全部完成 → `already_done`，**一个 complete 请求都不发**。"""
    tasks_key = (API_HOST, _api(C.ONBOARDING_TASKS_PATH))
    upstream = FakeUpstream({tasks_key: _ok({"tasks": {k: True for k in C.TASK_POINTS}})})
    _patch_clients(monkeypatch, upstream)
    outcome = await loomy.claim_onboarding({"access_token": "t"}, loomy.meta(), precheck=True)
    assert outcome.category == "already_done" and "全部领取" in outcome.detail
    assert "10000/10000 分" in outcome.detail
    assert upstream.count((API_HOST, _api(C.ONBOARDING_COMPLETE_PATH))) == 0


async def test_onboarding_auth_error_interrupts_immediately(monkeypatch):
    """`100002` → **立即中断**（不再对后续任务发请求），已领数如实上报（`loomy-onboarding.ts:204-207`）。"""
    complete_key = (API_HOST, _api(C.ONBOARDING_COMPLETE_PATH))
    upstream = FakeUpstream({
        (API_HOST, _api(C.ONBOARDING_TASKS_PATH)): _ok({"tasks": {}}),
        complete_key: _fail(C.AUTH_ERROR_CODE, "缺少 token"),
    })
    _patch_clients(monkeypatch, upstream)
    outcome = await loomy.claim_onboarding({"access_token": "t"}, loomy.meta(), precheck=True)
    assert outcome.category == "failed"
    assert "已完成 0 个任务" in outcome.detail and "100002" in outcome.detail
    assert upstream.count(complete_key) == 1                    # 中断：只发了一次


async def test_onboarding_partial_then_network_error(monkeypatch):
    """中途网络失败 → `failed`，但已领的部分如实写进 detail（不丢进度、不谎报全成）。"""
    keys = list(C.TASK_POINTS)
    upstream = FakeUpstream({
        (API_HOST, _api(C.ONBOARDING_TASKS_PATH)): _ok({"tasks": {}}),
        (API_HOST, _api(C.ONBOARDING_COMPLETE_PATH)): [
            _ok({"alreadyCompleted": True, "balance": 500}),       # 幂等重放也算成功
            httpx.ConnectError("down"),
        ],
    })
    _patch_clients(monkeypatch, upstream)
    outcome = await loomy.claim_onboarding({"access_token": "t"}, loomy.meta(), precheck=False)
    assert outcome.category == "failed"
    assert f"已完成 1 个任务（{C.TASK_POINTS[keys[0]]} 分）" in outcome.detail
    assert f"任务 {keys[1]}（{C.TASK_TITLES[keys[1]]}）请求网络错误" in outcome.detail


async def test_onboarding_state_query_failure_and_no_token(monkeypatch):
    """状态查询失败 → failed；无凭据 → failed 且不打上游。"""
    upstream = FakeUpstream({(API_HOST, _api(C.ONBOARDING_TASKS_PATH)):
                             _fail("100001", "参数错误")})
    _patch_clients(monkeypatch, upstream)
    bad = await loomy.claim_onboarding({"access_token": "t"}, loomy.meta(), precheck=True)
    assert bad.category == "failed" and "100001" in bad.detail
    calls = len(upstream.calls)
    empty = await loomy.claim_onboarding({}, loomy.meta(), precheck=True)
    assert empty.category == "failed" and "未发请求" in empty.detail
    assert len(upstream.calls) == calls


# ============ 模型目录 ============

async def test_list_models_remote_filters_chat_and_normalizes(monkeypatch):
    """远端目录：只留 `type==='chat'`、展示名规范化（三种括号风格）、档位取远端。"""
    key = (API_HOST, _api(C.MODELS_PATH))
    upstream = FakeUpstream({key: httpx.Response(200, json={"data": [
        {"id": "MiniMax-M3", "type": "chat", "name": "MiniMax M3 （x4.0）",
         "context_length": 1048576,
         "capabilities": {"input_modalities": ["text", "image"], "reasoning": True},
         "reasoning_efforts": ["none", "low", "high", "high"],
         "default_reasoning_effort": "low"},
        {"id": "GLM-5.3-Flash", "type": "chat", "name": "GLM 5.3 Flash(x0.8)",
         "context_length": 1048576, "capabilities": {"input_modalities": ["text"]}},
        {"id": "hy-image-3.5", "type": "image", "name": "Hy image 3.5",
         "context_length": 4096},
    ]})})
    _patch_clients(monkeypatch, upstream)

    models = await loomy.list_models({"access_token": "t"}, loomy.meta())

    assert [m.id for m in models] == ["MiniMax-M3", "GLM-5.3-Flash"]     # 生图模型被滤掉
    first = models[0]
    assert first.name == "MiniMax M3 · x4.0"                            # 全角括号 → 规范形态
    assert first.context_window == 1_048_576
    assert first.image_input is True and first.reasoning is True
    assert first.effort_levels == ("none", "low", "high")               # 去重、保序
    assert first.max_output is None and first.tool_call is None         # 取不到不编造
    second = models[1]
    assert second.name == "GLM 5.3 Flash · x0.8"
    assert second.image_input is False and second.reasoning is None      # 未声明 ≠ 明确不支持
    request = upstream.requests_for(key)[0]
    assert request.headers["token"] == "t" and "Authorization" not in request.headers


async def test_list_models_accepts_bare_array_and_skips_unknown_shape():
    """裸数组形态也认；非数组 / 非对象条目 → 空表（不抛错）。"""
    assert [m.id for m in loomy_models.parse_remote_models(
        [{"id": "a", "type": "chat"}])] == ["a"]
    assert loomy_models.parse_remote_models({"data": [{"id": "b", "type": "chat"}]})[0].id == "b"
    assert loomy_models.parse_remote_models("nope") == []
    assert loomy_models.parse_remote_models([{"type": "chat"}, {"id": "x", "type": "chat "}]) == []


@pytest.mark.parametrize("route", [
    None,                                                      # 无凭据（不打上游）
    httpx.Response(500, text="boom"),
    httpx.Response(200, text="<html>"),
    httpx.Response(200, json={"data": [{"id": "img", "type": "image"}]}),   # 无 chat 条目
    httpx.ConnectError("down"),
])
async def test_list_models_falls_back_to_static_table(monkeypatch, route):
    """远端失败 / 无 chat 条目 / 无凭据 → **兜底表**（8 条，`loomy-product.ts:104-113`）。"""
    key = (API_HOST, _api(C.MODELS_PATH))
    upstream = FakeUpstream({} if route is None else {key: route})
    _patch_clients(monkeypatch, upstream)
    cred = {} if route is None else {"access_token": "t"}

    models = await loomy.list_models(cred, loomy.meta())

    assert [m.id for m in models] == [m.id for m in C.FALLBACK_MODELS] == [
        "deepseek-v4-flash-0731", "MiniMax-M3", "Kimi-k2.6", "qwen-3.8-max",
        "GLM-5.3-Flash", "qwen3.8-flash", "spark-x", "mimo-v2.5"]
    assert len(models) == 8 and all(m.name and m.context_window for m in models)
    assert models[0].effort_levels == C.LOOMY_EFFORTS
    if route is None:
        assert upstream.calls == []


def test_display_name_forms_and_idempotency():
    """倍率识别两种形态（远端原值括号 / 已规范化 `· x`）且**幂等**（`loomy.ts:118-160`）。"""
    assert loomy_models.display_name("MiniMax M3 （x4.0）") == "MiniMax M3 · x4.0"
    assert loomy_models.display_name("Qwen 3.8 Max (x12.0)") == "Qwen 3.8 Max · x12.0"
    assert loomy_models.display_name("GLM 5.3 Flash(x0.8)") == "GLM 5.3 Flash · x0.8"
    assert loomy_models.display_name("Hy image 3.5 preview") == "Hy image 3.5 preview"
    for raw in ("MiniMax M3 （x4.0）", "Spark X2.5 · x0.1", "无倍率模型"):
        once = loomy_models.display_name(raw)
        assert loomy_models.display_name(once) == once
    assert loomy_models.split_rate("") == ("", "")
    # 已规范化的 `· x` 形态：去掉倍率后是纯模型名
    assert loomy_models.split_rate("Spark X2.5 · x0.1") == ("Spark X2.5", "x0.1")


# ============ 封套解析（纯函数）============

def test_envelope_parse_semantics():
    """封套：成功码 / `desc` 优先 / 缺 code 一律失败 / 非对象失败（`loomy.ts:86-104`）。"""
    assert envelope.parse({"code": C.OK_CODE, "desc": "", "data": {"a": 1}}).ok
    assert envelope.parse({"code": C.OK_CODE, "data": [1]}).data == [1]
    bad = envelope.parse({"code": "1", "desc": "描述", "message": "兜底"})
    assert not bad.ok and bad.message == "描述"
    assert not envelope.parse({"code": "1", "message": "只有 message"}).ok
    assert envelope.parse({"code": "1"}).message == "业务错误 1"
    assert envelope.parse({"desc": "缺 code"}).message == "缺 code"
    assert not envelope.parse([1, 2]).ok and not envelope.parse(None).ok


def test_business_request_never_carries_authorization():
    """业务端点请求头 = 只有 `token`（带 Bearer 会被判「缺少 token」，`loomy.ts:207-215`）。"""
    headers = api.business_headers("abc")
    assert headers == {"Accept": "application/json", "token": "abc"}
    assert "Authorization" not in headers


def test_claim_outcome_categories_are_ops_four():
    """四类结果字面量与 `ops/base.py::Category` 同源（不另写一份字面量）。"""
    categories = {ClaimOutcome(category=c).category
                  for c in ("success", "already_done", "inactive", "failed")}
    assert categories == {"success", "already_done", "inactive", "failed"}
    assert ProbeResult().__class__ is ProbeResult and QuotaSnapshot().state == "unknown"
