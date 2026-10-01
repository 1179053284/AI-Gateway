"""Loomy 微信扫码登录：二维码获取与长轮询（**纯 HTTP，无需浏览器**）。

🗂 证据面（只读）：DSH `src/loomy-wechat.ts`（2026-09-26 实测打通）；搬运时保留全部坑位说明。

## 为什么不能用官方的 Electron 做法

官方客户端用 `BrowserWindow` 的 `will-redirect` 在**导航发生前**截获微信回调里的 `code`，
而那个回调页（`https://loomy.xunfei.cn/oauth/wechat/callback`）实测 **404**
（`loomy-wechat.ts:5-12`）。本网关同理没有 `will-redirect` 能力，故**不碰回调页**，
改为纯 HTTP 三步（`loomy-wechat.ts:11-21`）：

```
1. GET open.weixin.qq.com/connect/qrconnect?appid=…&redirect_uri=…&state=…
     → HTML 里**内嵌 uuid**（正则直接提取，无需执行 JS）
2. GET open.weixin.qq.com/connect/qrcode/<uuid>
     → 二维码图片（实测 JPEG，约 47KB）
3. GET long.open.weixin.qq.com/connect/l/qrconnect?uuid=<uuid>[&last=<prev>]
     → 长轮询状态机（见 constants 的 WECHAT_ERR_*）
```

⚠️ **redirect_uri 必须是官方地址**（`loomy-wechat.ts:24-30`）：微信校验域名白名单，换本地
   地址会得到「redirect_uri 参数错误」；它只用于**取 uuid**，不参与回调。

## 与 Challenge 的衔接（§22.3 字段语义，M7-C1 改口径）

微信给我们的**只有那张图**（内容串由微信服务端在生成图片时编码，我们拿不到）→ 旧实现把
`Challenge.url` 填成图片地址、`qr_payload` 留空，前端 `<img src="{url}">` 让**浏览器**去
跨域取图 —— 必挂：那张图必须由**铸出 uuid 的同一组 UA + Referer** 才取得到
（`:129-130` 早就知道这件事），浏览器带不上、也不被允许带上。

现在改成：**网关自己取图**（本模块 `fetch_qr_image`），把 JPEG 转成
`data:image/jpeg;base64,…` 放进 `Challenge.qr_payload`，浏览器只做一件事：显示。
`Challenge.url` 保留官方图片地址作为**可复制的展示文本**（换发/兜底时用户看的是它）。
「不编造内容串」这条纪律**保持不变**：本层依然不假装知道微信二维码里写的是什么。
"""

from __future__ import annotations

import logging
import re
import time
from base64 import b64encode
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from model_gateway.accounts.net import make_client  # 可被单测替换（monkeypatch 本模块属性）
from model_gateway.upstream.loomy import constants as C

logger = logging.getLogger("model_gateway.accounts")

#: uuid 的字符集下限（`loomy-wechat.ts:104-109`）：实测形如 `001ZDsw64Vu7ll2E`（15 位）、
#: `4Y0N_jyVQg==`（base64 补位）。下限取 6 而非更长：微信未承诺长度，收紧只会让格式微调时
#: **静默失效**。
_UUID_PATTERN = re.compile(r"^[A-Za-z0-9_\-=+/]{6,64}$")
#: 主路径：`<img class="js_qrcode_img" src="/connect/qrcode/<uuid>"/>`（`loomy-wechat.ts:140`）。
_UUID_FROM_IMG = re.compile(r"/connect/qrcode/([A-Za-z0-9_\-=+/]+)")
#: 兜底：`var fordevtool = "…/connect/l/qrconnect?uuid=<uuid>"`（`loomy-wechat.ts:146`）。
_UUID_FROM_POLL = re.compile(r"l/qrconnect\?uuid=([A-Za-z0-9_\-=+/]+)")
#: 长轮询响应里的 `wx_errcode = N` / `wx_code = '…'`（`loomy-wechat.ts:282-283`）。
_ERRCODE_RE = re.compile(r"wx_errcode\s*=\s*(\d+)")
_WX_CODE_RE = re.compile(r"wx_code\s*=\s*'([^']*)'")

#: 长轮询状态（字符串常量，语义见 constants 的 `WECHAT_ERR_*` 与 `loomy-wechat.ts:72-85`）。
STATUS_WAITING = "waiting"      # 408：等待扫码（常态）；**本轮读预算到点也归这一档**
STATUS_SCANNED = "scanned"      # 404：已扫码，等确认 → **继续轮询**
STATUS_CONFIRMED = "confirmed"  # 405：已确认，`code` 在本帧
STATUS_CANCELLED = "cancelled"  # 403：用户取消
STATUS_EXPIRED = "expired"      # 402：二维码失效
STATUS_ERROR = "error"          # 网络/解析异常：调用方应继续轮询（瞬时不代表失败）

#: 本轮**读预算**到点时写进 `WechatPoll.errcode` 的本地标记（M7-C1）。
#: 🔴 刻意不是数字：`login.py` 只把 `isdigit()` 的 errcode 回传作下一轮的 `last=` 参数，
#: 本地标记绝不能被发回上游（DSH 原样回传把网络文案当日志参数发出去的那个毛病，同一族）。
_ERRCODE_ROUND_TIMEOUT = "round-timeout"


@dataclass(frozen=True)
class WechatPoll:
    """一次长轮询的结果（`loomy-wechat.ts:91-97`）。"""

    status: str
    #: 仅在 `confirmed` 时非空：微信一次性授权码。
    code: str = ""
    #: 本次响应的 errcode（诊断用；网络失败时是错误文案）。
    errcode: str = ""


def build_auth_url(state: str) -> str:
    """拼微信授权页 URL（`loomy-wechat.ts:116-124`）。

    `state` = 32 位随机串（微信原样回传；本实现不依赖它，但保持与官方一致）。
    """
    return (f"{C.WECHAT_OPEN_ORIGIN}/connect/qrconnect"
            f"?appid={C.WECHAT_APP_ID}"
            f"&redirect_uri={quote(C.WECHAT_REDIRECT_URI, safe='')}"
            "&response_type=code"
            "&scope=snsapi_login"
            f"&state={quote(state, safe='')}"
            "#wechat_redirect")


def extract_uuid(html: object) -> str:
    """从授权页 HTML 提取二维码 uuid（`loomy-wechat.ts:137-152`）。

    两条路径互为兜底（img src 主路径 / fordevtool 长轮询 URL 兜底）。**无需执行 JS** ——
    这是本方案能脱离浏览器的基础。提取不到时返回**空串**（由调用方决定是否抛错）。
    """
    if not isinstance(html, str) or not html:
        return ""
    for pattern in (_UUID_FROM_IMG, _UUID_FROM_POLL):
        found = pattern.search(html)
        if found is not None and _UUID_PATTERN.match(found.group(1)):
            return found.group(1)
    return ""


def qr_image_url(uuid: str) -> str:
    """拼二维码图片地址（`loomy-wechat.ts:155-157`）。

    ⚠️ 这个地址**只作为展示文本**进 `Challenge.url`：把它直接塞给浏览器的 `<img src>` 就是
       本轮修掉的缺陷（浏览器跨域取不到 —— 取图必须带下面那组 UA + Referer）。
    """
    return f"{C.WECHAT_OPEN_ORIGIN}/connect/qrcode/{quote(uuid, safe='')}"


def _detect_image_mime(raw: bytes) -> str:
    """按**魔数**认图片格式（`loomy-wechat.ts:224-229`）；未知 → 空串。

    ⚠️ 实测微信回的是 **JPEG**，早期只认 PNG 会误报「不是图片」→ JPEG/PNG/GIF 三种都认。
    """
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:4] == b"\x89PNG":
        return "image/png"
    if raw[:3] == b"GIF":
        return "image/gif"
    return ""


async def fetch_qr_image(uuid: str) -> str:
    """下载微信二维码图片并转成 **data URI**（`loomy-wechat.ts:198-221`）。

    🔴 **必须与铸出 uuid 的那次请求同 UA 同 Referer**（`fetch_uuid` 用的是
    `{origin}/`，这里逐字复用）：微信按这次页面加载的上下文发图，换了请求头就是另一张图 /
    直接被拒 —— 而用户扫的必须是**我们长轮询的那个 uuid** 对应的那张图。
    浏览器自己取不到这张图（跨域 + 带不上这两个头），所以只能由网关取。

    ⚠️ 内容不是已知图片、或小得离谱（< `MIN_QR_IMAGE_BYTES`）→ **抛错**：
    那是错误页（HTML），把它当二维码显示会让用户扫一张不存在的花图（照 `:216-218` 的判据）。
    @raises RuntimeError 网络失败 / HTTP 非 200 / 不是图片。
    """
    url = qr_image_url(uuid)
    try:
        async with make_client(timeout=C.WECHAT_FETCH_TIMEOUT_S) as client:
            response = await client.get(
                url, headers={"User-Agent": C.WECHAT_UA,
                              "Referer": f"{C.WECHAT_OPEN_ORIGIN}/"})
    except httpx.HTTPError as e:      # 文案对齐 DSH 的可读原因（`loomy-wechat.ts:208-212`）
        raise RuntimeError(f"微信二维码图片下载失败：{e}") from e
    if response.status_code != 200:
        raise RuntimeError(f"微信二维码图片返回 HTTP {response.status_code}")
    raw = response.content
    mime = _detect_image_mime(raw)
    if mime == "" or len(raw) < C.MIN_QR_IMAGE_BYTES:
        raise RuntimeError("微信二维码响应不是图片（可能是错误页）")
    return f"data:{mime};base64,{b64encode(raw).decode('ascii')}"


async def fetch_uuid(state: str) -> str:
    """拉取授权页并提取 uuid（`loomy-wechat.ts:164-188`）。

    ⚠️ 走这一步的是**我们自己的 HTTP 客户端**（带浏览器 UA + Referer）；uuid 与本次页面
       加载绑定 —— 用户必须扫这张图对应的二维码，长轮询才可能拿到 `code`
       （所以不能把授权页 URL 丢给用户自己去开：那是**另一个** uuid）。

    @raises RuntimeError 页面拉取失败或提取不到 uuid（**不返回空串**让上层拿去轮询）。
    """
    url = build_auth_url(state)
    try:
        async with make_client(timeout=C.WECHAT_FETCH_TIMEOUT_S) as client:
            response = await client.get(
                url, headers={"User-Agent": C.WECHAT_UA,
                              "Referer": f"{C.WECHAT_OPEN_ORIGIN}/"})
    except httpx.HTTPError as e:  # 文案对齐 DSH 的可读原因（`loomy-wechat.ts:175-177`）
        raise RuntimeError(f"微信授权页拉取失败：{e}") from e
    if response.status_code != 200:
        raise RuntimeError(f"微信授权页返回 HTTP {response.status_code}")
    uuid = extract_uuid(response.text)
    if not uuid:
        raise RuntimeError("微信授权页未包含二维码 uuid（页面结构可能已变化）")
    return uuid


async def poll_once(uuid: str, last_errcode: str = "", *,
                    budget_s: float | None = None) -> WechatPoll:
    """执行一次长轮询（`loomy-wechat.ts:255-301`）。

    ⚠️ **状态语义以微信授权页内嵌 JS 为准**（`switch(window.wx_errcode)`，官方源码）：

    | errcode | 含义 | 本实现返回 |
    |---|---|---|
    | 408 | 待扫码（常态；长轮询会挂起直到状态变化） | `waiting` |
    | 404 | **已扫码待确认**（显示 js_wx_after_scan，继续轮询） | `scanned` |
    | 405 | **已确认**，`wx_code` 就在这一帧 | `confirmed` |
    | 403 | 用户取消 | `cancelled` |
    | 402 | 二维码失效 | `expired` |

    ⚠️ DSH 真实缺陷（用户报障「扫码后显示已扫码但没有后续跳转」）：早期把 **404 当「已确认」、
       405 当「待确认」**，**恰好读反** → 用户确认后实现仍在等一个「带 code 的 404」，
       永远等不到 → 卡在「已扫码」。搬运时逐字保留该判据（`loomy-wechat.ts:243-248`）。
    ⚠️ **405 但 `wx_code` 为空时不判成功**：保守判 `scanned`（继续轮询），绝不拿空 code 去换会话。
    ⚠️ 网络异常返回 `error` 状态而**不抛错**：长轮询偶发失败不该终止整个流程，由调用方决定重试
       （`loomy-wechat.ts:273-280`）。

    ## `budget_s`：管理端请求路径的读预算（M7-C1，本轮改的正是这一处）

    微信的长轮询会**挂住连接**直到状态变化（约 25s，DSH 因此给 40s 上限，见
    `constants.WECHAT_POLL_TIMEOUT_S`）。DSH 把它放在自己那条**本机页面**的请求上，挂多久
    都不影响别人；本网关这条请求来自**管理端 `login/poll`**，挂 40s 就是把一个管理端请求
    按住 40s（前端的节奏是 2s 一次，`accounts.js::POLL_MS`，全靠 `_single_flight` 与
    `st.busy` 挡着才没排队）。故**读**超时收到 `WECHAT_POLL_BUDGET_S`（2s）：到点就是
    「这一轮没有变化」。

    🔴 **读超时判 `waiting`，不判 `error`**：长轮询按 `last=` 续查，微信在有变化时会立刻
       回新状态，所以主动断开不会丢事件；把它算成网络错误会让界面反复弹「轮询网络错误」，
       而真正的语义只是"还没人扫"。（connect / write / pool 超时**仍**归 `error`。）
    """
    # ⚠️ uuid 与 last 都要转义（uuid 实测含 `=` / `+` / `/` 等 base64 字符；照
    #    `loomy-wechat.ts:260-262` 的 encodeURIComponent 口径）。
    query = f"uuid={quote(uuid, safe='')}"
    if last_errcode:
        query += f"&last={quote(last_errcode, safe='')}"
    query += f"&_={int(time.time() * 1000)}"
    url = f"{C.WECHAT_LONG_ORIGIN}/connect/l/qrconnect?{query}"
    read_budget = C.WECHAT_POLL_BUDGET_S if budget_s is None else float(budget_s)
    timeout = httpx.Timeout(connect=C.WECHAT_POLL_TIMEOUT_S, read=read_budget,
                            write=C.WECHAT_POLL_TIMEOUT_S, pool=C.WECHAT_POLL_TIMEOUT_S)
    try:
        async with make_client(timeout=timeout) as client:
            response = await client.get(
                url, headers={"User-Agent": C.WECHAT_UA,
                              "Referer": build_auth_url("")})
        body = response.text
    # ⚠️ 本轮预算到点 = **没有状态变化**（不是故障）→ 判 waiting 继续下一轮（见上面 `budget_s`）。
    #    刻意在宽捕获**之前**：`httpx.ReadTimeout` 也是 `TransportError` 的子类。
    except httpx.ReadTimeout:
        return WechatPoll(status=STATUS_WAITING, errcode=_ERRCODE_ROUND_TIMEOUT)
    # ⚠️ 长轮询**永不抛**：任何异常都降级成 `error` 状态，由调用方决定重试
    #    （照 `loomy-wechat.ts:273-280` 的语义）→ 这里刻意宽捕获 `Exception`。
    except Exception as e:  # noqa: BLE001
        return WechatPoll(status=STATUS_ERROR, errcode=str(e))

    errcode_match = _ERRCODE_RE.search(body)
    code_match = _WX_CODE_RE.search(body)
    errcode = errcode_match.group(1) if errcode_match is not None else ""
    code = code_match.group(1) if code_match is not None else ""
    if errcode == C.WECHAT_ERR_CONFIRMED:
        # ⚠️ 405 = **已确认**（官方 JS 在此分支用 wx_code 拼回调 URL）。
        if code:
            return WechatPoll(status=STATUS_CONFIRMED, code=code, errcode=errcode)
        return WechatPoll(status=STATUS_SCANNED, errcode=errcode)
    if errcode == C.WECHAT_ERR_SCANNED:
        return WechatPoll(status=STATUS_SCANNED, errcode=errcode)
    if errcode == C.WECHAT_ERR_CANCELLED:
        return WechatPoll(status=STATUS_CANCELLED, errcode=errcode)
    if errcode == C.WECHAT_ERR_EXPIRED:
        return WechatPoll(status=STATUS_EXPIRED, errcode=errcode)
    # 408（常态等待）与未知值一律归 waiting（保守：绝不误判成功）。
    if errcode != C.WECHAT_ERR_WAITING:
        logger.debug("[loomy] 微信长轮询未知 errcode=%r（按 waiting 处理）", errcode)
    return WechatPoll(status=STATUS_WAITING, errcode=errcode)
