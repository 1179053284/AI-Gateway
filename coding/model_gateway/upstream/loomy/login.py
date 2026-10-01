"""Loomy 登录编排：微信扫码（主）+ 短信（备），以及**不可续期**的续期钩子语义。

🗂 证据面（只读）：DSH `src/loomy-wechat-login.ts`（扫码全流程）、`src/loomy-oauth.ts`
   （账号端点与请求体）、`src/loomy-auth.ts`（凭据形态与探测）、`src/jet-hub-rpc.ts:1058-1112`
   （扫码作为 `account.create` 的 loomy 分支）、`:1363-1436`（`login.sendSms` / `login.submitSms`）。

## 两条登录通道（§22.4：`login="qr"` + `login_alt=("sms_code",)`）

| 通道 | 端点 | 触发方式 |
|---|---|---|
| **微信扫码（主）** | `open.weixin.qq.com` 三段式（见 `wechat.py`）+ `account.xfinfr.com` 的 `bind/*` | `login_start` 返回二维码 → `login_poll` 长轮询 → （首次）绑手机号 |
| **短信（备）** | `account.xfinfr.com` 的 `login/phone/*`（`loomy-oauth.ts:141,173`） | `_ALT_HOOKS` 的 `sms_send` / `sms_submit` 两步（本模块 `send_sms_code` / `submit_sms_code`） |

⚠️ **顺序死锁教训**（照抄，勿重犯）：DSH 早期实现要求 `account.create`（= 本层的 `start`）
   **必须带手机号**，而登录表单要等它返回 `loginMode:'sms'` 才渲染 → 用户根本没机会输入手机号，
   直接报错，表单永远出不来（`jet-hub-rpc.ts:1063-1067`，用户报障「新建账号失败：Loomy 短信
   登录需要手机号」）。本实现的结构性规避：**`login_start` 绝不索取手机号**（只起二维码），
   手机号在 `sms_send`（备选形态第一步）那一步由用户表单提供；短信通道因此不依赖 `start`
   的任何中间态。

## 通道表达（M6-3 设计 → W3-fix 按 §22.3 补入③ 收口）

`LoginEngine.start(product, name=…, kind=…)` 的 `kind` 只表达**用户选了哪个形态**
（`LoginSession.kind` 供钩子/入口层读取），产品侧仍**不**在 `start` 时区分通道：

- `login_start` 恒走**扫码**（主形态）；
- 短信两段经产品模块的 `_ALT_HOOKS` 表暴露（`sms_send` / `sms_submit`，§22.3 补入③：
  「入口层专用辅助调用」），入口层按 `ProductMeta.login_alt` 渲染短信 Tab 后经
  `accounts/login.py::alt_call(product, session, name, **kw)` 调用 —— 与 DSH 把短信两步
  放在独立的 `login.sendSms` / `login.submitSms` RPC（`jet-hub-rpc.ts:1363-1436`）同构。
- ⚠️ **W3-fix 收口**：旧路（经 `login_callback(session, params)` 的 `action=send_sms/
  submit_sms` 动作分派）已**删除**；`login_callback` 现按「本产品非 local_callback 型」
  显式失败（`product.py`），与 raccoon 同款。`login_poll` 仍负责扫码长轮询。

## 结果状态纪律（本产品口径，M6-3 登记）

| 情形 | 状态 | 理由 |
|---|---|---|
| 等待扫码 / 已扫码待确认 / 等待验证码提交 | `pending` | §22.3：pending 是正常业务状态 |
| **用户可重试**的失败（手机号格式、验证码错误、发码失败、网络抖动） | `pending` + 可读 `detail` | 与 DSH 一致（它的 `login.submitSms` 回 `done:false + error` 并**保留条目**让用户重试，`jet-hub-rpc.ts:1424-1433`）；本引擎只有 pending 能保活会话 |
| 会话状态坏了（缺 mode / 缺 uuid） / 上游协议不可恢复 | `failed` | 重试无意义 |
| 二维码失效（微信 402）/ 用户取消（403） | **`pending` + 就地换发一张新码** | M7-C1：照 raccoon 的换发语义（`raccoon-login-page.ts:213-220`）；只有换发次数超上限、或换发时拿不到新 uuid，才如实落 `expired`（`_reissue`） |

⚠️ **M6-4 必须把 `pending` 的 `detail` 展示给用户**（否则「验证码错误」会表现为无限等待）。
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
import uuid

import httpx

from model_gateway.accounts import qr
from model_gateway.accounts.net import make_client  # 可被单测替换（monkeypatch 本模块属性）
from model_gateway.accounts.types import (
    Challenge,
    LoginOutcome,
    NotRefreshable,
)
from model_gateway.upstream.loomy import constants as C
from model_gateway.upstream.loomy import envelope, sign, wechat

logger = logging.getLogger("model_gateway.accounts")

#: 手机号形态（`jet-hub-rpc.ts:1370` 的同一条判据；服务端另有一层校验）。
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")

#: 会话私态键（都在 `LoginSession.state` 里；**绝不进 Challenge / LoginOutcome.detail**）。
MODE_WECHAT = "wechat"            # 扫码进行中（等扫码 / 等确认）
MODE_WECHAT_BIND = "wechat_bind"  # 已拿到微信授权码，等绑手机号（首次登录）
MODE_SMS = "sms"                  # 短信通道：已发码，等提交验证码


# ── 续期：**不可续期**（`loomy.ts:195-205`、`loomy-auth.ts:4-21`）──────────

async def refresh_credential(cred, meta) -> dict:
    """凭据续期（§22.3；返回**新的**凭据本体；不可续期 → `NotRefreshable`）。

    🔴 Loomy **没有任何 refresh 端点**（`loomy.ts:198-205`）：`session` 是登录时向服务端声明
       `expire: 1209600`（14 天）得来的，过期只能**重新登录**。`loomy-auth.ts:319-324` 的
       `refresh()` 也只能做「确认这份凭据还活着」的探测 —— 那是**探活**，归本产品的 `probe`。
       故这里恒抛 `NotRefreshable`（§22.3 的合法返回形态：**不是**异常故障，不触发冷却）。
    """
    del cred, meta  # 形参按 §22.3 保留：本产品无设备身份、无私有文件（`20 §2.7`）
    raise NotRefreshable(
        "Loomy 无 refresh 端点（凭据有效期 14 天，过期只能重新登录；`loomy.ts:198-205`）")


# ── 登录：start（扫码）────────────────────────────────────────────────

async def _qr_challenge(session, qr_uuid: str) -> Challenge:
    """组装扫码展示的 `Challenge`：**网关自己去取微信那张图**，取不到就如实降级。

    - `qr_payload` = `data:image/...;base64,` 的 data URI（浏览器只显示，不发跨域请求）；
    - `url` = 官方图片地址（**可复制的展示文本**：换发、以及"这台设备扫不了"时给用户看的）；
    - 🔴 取图失败**不**掐掉一次已经起好的会话：uuid 与长轮询都是有效的（失败的是图片端点）。
      把原因留在 `session.state["qr_image_error"]`，由下一次 `login_poll` 的 `detail`
      如实说给用户（§22.3：pending 的 detail 就是给用户看的），并**不给一个空 `<img>`**。
    """
    image_url = wechat.qr_image_url(qr_uuid)
    try:
        image = await wechat.fetch_qr_image(qr_uuid)
    except RuntimeError as e:
        session.state["qr_image_error"] = str(e)
        logger.warning("[loomy] 微信二维码图片取不到（%s）—— 本次只给文字地址，不给坏图", e)
        return Challenge(url=image_url)
    session.state.pop("qr_image_error", None)
    return Challenge(url=image_url, qr_payload=image)


async def start(session) -> Challenge:
    """两步式第一步：拉微信授权页 → 取 uuid → **网关代取二维码图片** → 返回展示物。

    🔴 M7-C1 改口径（本轮缺陷的本体）：`Challenge.qr_payload` 现在装的是**图片 data URI**
    （`wechat.fetch_qr_image`：用铸出该 uuid 的同一组 UA + Referer 去下载 JPEG）。
    旧实现只回 `url = 图片地址` 让浏览器 `<img src>` 自己去取 —— 跨域且带不上那两个头，
    用户看到的是一张永远加载失败的图（M6-3 登记的「qr_payload 留空 + 待实测」由此收口）。
    ⚠️ **不编造内容串**这条纪律不变：微信二维码里写的什么我们仍然不知道，也不猜。
    ⚠️ 拉授权页失败 → **抛** `RuntimeError`（引擎不吞异常，入口层可见；不编造 Challenge）；
       取图失败 → 不抛，按 `_qr_challenge` 的降级面处理。
    """
    state = secrets.token_hex(16)                     # 32 位随机串（`loomy-wechat.ts:114-124`）
    qr_uuid = await wechat.fetch_uuid(state)          # 失败抛 RuntimeError（含可读原因）
    session.state["mode"] = MODE_WECHAT
    session.state["wechat_uuid"] = qr_uuid
    session.state["wechat_state"] = state
    session.state["last_errcode"] = ""
    session.state["qr_reissues"] = 0
    return await _qr_challenge(session, qr_uuid)


def _image_note(session) -> str:
    """把「上一次取图失败」的原因取出来拼进 pending 文案（**取走即清**，不重复播报）。"""
    reason = str(session.state.pop("qr_image_error", "") or "")
    if not reason:
        return ""
    return (f"（注意：二维码图片取不到——{reason}。"
            f"可复制下方地址在能扫码的设备里打开，或点「重新发起登录」重试）")


# ── 登录：poll ────────────────────────────────────────────────────────

async def poll(session) -> LoginOutcome:
    """两步式第二步：微信长轮询 → （首次）绑手机号 → 凭据。

    🔴 `pending` 是**正常业务状态**（用户还没扫/还没确认），不是错误（§22.3）。
    🔴 一轮的读预算由 `wechat.poll_once` 收在 `WECHAT_POLL_BUDGET_S`（2s）——
       到点判 `waiting`，**不把一个管理端请求挂在微信的长轮询上 40s**（M7-C1）。
    🔴 402（失效）/ 403（取消）**不再直接判终态**：就地换发一张全新的码（见 `_reissue`），
       界面拿到新图继续等（`raccoon-login-page.ts:213-220` 的换发语义搬到 loomy）。
    """
    mode = str(session.state.get("mode") or "")
    if mode == MODE_WECHAT_BIND:
        return LoginOutcome(state="pending", detail="已扫码；首次使用需绑定手机号（提交手机号与验证码）")
    if mode == MODE_SMS:
        return LoginOutcome(state="pending", detail="等待短信验证码提交")
    if mode != MODE_WECHAT:
        return LoginOutcome(state="failed", detail="会话缺少登录模式（登录未正确启动，请重新发起）")
    qr_uuid = str(session.state.get("wechat_uuid") or "")
    if not qr_uuid:
        return LoginOutcome(state="failed", detail="会话缺少微信二维码 uuid（登录未正确启动，请重新发起）")

    polled = await wechat.poll_once(qr_uuid, str(session.state.get("last_errcode") or ""))
    # ⚠️ 只把**数字** errcode 回传作 `last`：DSH 原样回传，会把网络错误文案当日志参数发回上游。
    if polled.errcode.isdigit():
        session.state["last_errcode"] = polled.errcode

    if polled.status == wechat.STATUS_WAITING:
        return LoginOutcome(state="pending", detail=f"等待微信扫码{_image_note(session)}")
    if polled.status == wechat.STATUS_SCANNED:
        return LoginOutcome(state="pending", detail=f"已扫码，请在手机上确认{_image_note(session)}")
    if polled.status == wechat.STATUS_CANCELLED:
        return await _reissue(session, "你已取消授权")
    if polled.status == wechat.STATUS_EXPIRED:
        # 402：二维码失效（`loomy-wechat.ts:296-298`）—— 换发新码，不换会话。
        return await _reissue(session, "微信二维码已失效")
    if polled.status == wechat.STATUS_ERROR:
        # 长轮询偶发失败**不终止**流程（`loomy-wechat.ts:272-280`）。
        return LoginOutcome(state="pending",
                            detail=f"微信长轮询网络错误（继续等待）：{polled.errcode}")

    # confirmed：拿到一次性 `wx_code` → 换 rcode / 判断是否已绑手机号（`loomy-wechat-login.ts:234-256`）。
    try:
        auth = await bind_auth(polled.code)
    except (httpx.HTTPError, RuntimeError) as e:
        # 微信 code 一次性：换取失败即本次会话不可能再成功 → failed（不谎报 pending）。
        return LoginOutcome(state="failed", detail=f"微信授权码换取会话失败（请重新发起登录）：{e}")
    session.state["rcode"] = auth["rcode"]
    if auth["nickname"]:
        session.state["bind_nickname"] = auth["nickname"]
    if auth["bind"] == 1:
        # 已绑手机号：直接 skip 换 session，整个流程结束（`loomy-wechat-login.ts:243-247`）。
        try:
            login = await bind_skip(auth["rcode"])
        except (httpx.HTTPError, RuntimeError) as e:
            return LoginOutcome(state="failed", detail=f"微信登录换取凭据失败（请重新发起登录）：{e}")
        return _success(login["session"], login["userid"],
                        phone="", nickname=str(session.state.get("bind_nickname") or ""),
                        login_via="wechat")
    # 首次使用：需绑定手机号 → 交回前端表单（`loomy-wechat-login.ts:249-250`）。
    session.state["mode"] = MODE_WECHAT_BIND
    return LoginOutcome(state="pending", detail="已扫码；首次使用需绑定手机号（提交手机号与验证码）")


async def _reissue(session, reason: str) -> LoginOutcome:
    """402/403 → **换发一张全新的二维码**（新 state + 新 uuid + 新图，游标清零），会话继续。

    判据来源 = raccoon 那条同款处置：DSH 的本地页在 `canceled` 时就地
    `state.qrCode = generateQrCode()` 并把新二维码 SVG 塞回页面
    （`raccoon-login-page.ts:213-220`，注释原话"否则用户卡死"）。loomy 侧 DSH 是
    「显示『请关闭窗口后重试』」（`loomy-wechat-login.ts:452-459`）—— 本轮**按任务书改按
    raccoon 形态做**（同一份 errcode 表两条产品走两条路反而是坏事），差异已登记。

    🔴 换发**不是**成功也不是失败：回 `pending`，让界面继续等（会话 TTL 仍在兜总时限）；
    🔴 同时把新 `Challenge` 写回 `session.challenge` —— 入口层在轮询响应里带回当前 challenge
       （`api/admin_accounts.py::login_poll`），前端比对 `qr_payload` 换图。
       没有这条通道时，用户只能手动点「重新发起登录」（M6-3 的旧口径，本轮推翻）。
    ⚠️ 上限 `accounts/qr.py::MAX_REISSUES`：超限如实回 `expired` 让用户重新发起
       （不无限重铸一张没人看的码；算法见该模块头）。
    ⚠️ 换发时取不到新 uuid（授权页抖动）→ `expired`：此刻手里这张码上游已经判死，
       继续 pending 只会让用户对着一张扫不出来的图等待（诚实优先于"多撑一会儿"）。
    """
    used = int(session.state.get("qr_reissues") or 0)
    if used >= qr.MAX_REISSUES:
        return LoginOutcome(state="expired", detail=(
            f"{reason}，且本次会话已换发 {used} 张二维码（上限 {qr.MAX_REISSUES}）"
            f"——请重新发起登录"))
    try:
        state = secrets.token_hex(16)
        qr_uuid = await wechat.fetch_uuid(state)
    except RuntimeError as e:
        return LoginOutcome(state="expired",
                            detail=f"{reason}，且重新获取二维码失败（{e}）——请重新发起登录")
    session.state["mode"] = MODE_WECHAT
    session.state["wechat_uuid"] = qr_uuid
    session.state["wechat_state"] = state
    session.state["last_errcode"] = ""
    session.state["qr_reissues"] = used + 1
    session.challenge = await _qr_challenge(session, qr_uuid)
    return LoginOutcome(state="pending", detail=(
        f"{reason}，已换发第 {used + 1} 张二维码，请扫新码"
        f"（界面会自动换成新图）{_image_note(session)}"))


# ── 登录：短信两段（`_ALT_HOOKS` 的 sms_send / sms_submit；主扫码的绑手机号同走这里）──

async def send_sms_code(session, *, phone: str) -> LoginOutcome:
    """**短信第一步**（`_ALT_HOOKS["sms_send"]`）：下发验证码。

    语义照 DSH 的 `login.sendSms`（`jet-hub-rpc.ts:1363-1401`），但与 DSH 的两处差异
    都在本网关的既定口径内（§22.3 补入③只统一**入口形状**，不改各产品的结果状态纪律）：

    - 本产品返回 `LoginOutcome`（raccoon 的 `sms_send` 返回 `Challenge`）：Loomy 的
      **可重试失败**（手机号格式 / 发码失败 / 网络抖动）必须走 `pending` + 可读 `detail`
      让用户原地重试（R-6 契约；DSH 同语义 `:1424-1434`），`Challenge` 装不下这个状态。
    - 分支：会话已有 `rcode`（扫到码且未绑手机号）→ 走**绑定端点** `bind/sendMsg`，
      否则走**独立短信登录** `login/phone/sendMsgCode`（用户视角是同两个按钮）。
    """
    phone = str(phone or "").strip()
    if not _PHONE_RE.match(phone):
        # 用户可修正 → pending 保活（见模块头的状态纪律）
        return LoginOutcome(state="pending", detail="需要 11 位有效手机号（phone）")
    rcode = str(session.state.get("rcode") or "")
    try:
        if rcode:
            session.state["bind_msgid"] = await bind_send_msg(rcode, phone)
        else:
            session.state["sms_msgid"] = await send_sms(phone)
            session.state["sms_phone"] = phone
            # 通道切换是**终态**：此后 `login_poll` 只回「等待验证码提交」，不再长轮询二维码
            # （用户想改回扫码 = 重新发起登录；微信 uuid 绑定的是一张已展示的码，重扫无意义）。
            session.state["mode"] = MODE_SMS
    except (httpx.HTTPError, RuntimeError) as e:
        # 发码失败（频率限制 / 网络）可重试；会话保活（DSH 同样允许重发，`loomy-wechat-login.ts:486-489`）。
        return LoginOutcome(state="pending", detail=f"验证码发送失败（可重试）：{e}")
    return LoginOutcome(state="pending", detail=f"验证码已发送至 {phone[:3]}****{phone[-4:]}")


async def submit_sms_code(session, *, sms_code: str) -> LoginOutcome:
    """**短信第二步**（`_ALT_HOOKS["sms_submit"]`）：提交验证码 → 成功（凭据）或可重试的 pending。

    kwarg 名与 raccoon 对齐（`sms_code`）；手机号取自上一步的会话态（不重复信任表单）。
    """
    code = str(sms_code or "").strip()
    if not code:
        return LoginOutcome(state="pending", detail="请输入短信验证码（sms_code）")
    rcode = str(session.state.get("rcode") or "")
    try:
        if rcode:
            msgid = str(session.state.get("bind_msgid") or "")
            if not msgid:
                return LoginOutcome(state="pending", detail="请先发送验证码")
            login = await bind_check_code(rcode, code, msgid)
            return _success(login["session"], login["userid"], phone=login["phone"],
                            nickname=str(session.state.get("bind_nickname") or ""),
                            login_via="wechat")
        msgid = str(session.state.get("sms_msgid") or "")
        if not msgid:
            return LoginOutcome(state="pending", detail="请先发送验证码")
        phone = str(session.state.get("sms_phone") or "")
        login = await login_by_sms(phone, code, msgid)
        return _success(login["session"], login["userid"], phone=phone, login_via="sms")
    except (httpx.HTTPError, RuntimeError) as e:
        # ⚠️ 验证码错误 / 网络失败都是**可重试**的：不删会话（对齐 DSH
        # `jet-hub-rpc.ts:1424-1434`「登录失败不删除占位条目：用户可能只是验证码输错」）。
        return LoginOutcome(state="pending", detail=f"验证码提交失败（可重试）：{e}")


# ── 讯飞账号端点（HMAC-SHA1 签名；`loomy-oauth.ts:78-123`）─────────────

def build_account_body(param: dict) -> dict:
    """构建账号端点的请求体信封 `{base, param}`（`loomy-oauth.ts:55-71`）。

    `traceid` 每次调用重新生成（去掉连字符的 uuid，32 位 hex）。
    """
    return {
        "base": {
            "appid": C.ACCOUNT_APP_ID,
            "modelid": C.ACCOUNT_MODEL_ID,
            "version": C.ACCOUNT_VERSION,
            "devid": C.ACCOUNT_DEVID,
            "ua": C.ACCOUNT_UA,          # ⚠️ 硬编码 macOS（客户端在 Windows 上发的也是它）
            "traceid": uuid.uuid4().hex,
        },
        "param": param,
    }


async def _post_account(path: str, param: dict) -> dict:
    """发一次账号端点请求并拆信封（`loomy-oauth.ts:78-123`）。

    🔴 body **只序列化一次**、签名与发送共用同一个字符串（二次序列化会改变字节 → 签名失效）。
    @raises RuntimeError 网络失败 / 响应不是 JSON / 业务码非成功（消息含服务端 `desc`）。
    """
    body = build_account_body(param)
    serialized = json.dumps(body, ensure_ascii=False)
    headers = sign.auth_headers(method="POST", path=path, body=serialized)
    try:
        async with make_client(base_url=C.ACCOUNT_BASE,
                               timeout=C.REQUEST_TIMEOUT_S) as client:
            response = await client.post(path, content=serialized.encode("utf-8"),
                                         headers=headers)
    except httpx.HTTPError as e:
        raise RuntimeError(f"讯飞账号请求失败（{path}）：{e}") from e
    try:
        payload = response.json()
    except ValueError as e:
        raise RuntimeError(f"讯飞账号响应不是 JSON（{path}，HTTP {response.status_code}）") from e
    parsed = envelope.parse(payload)
    if not parsed.ok:
        # 账号端点的鉴权错误码与业务端点不同（实测 `020002` 也是登录态问题），但对本模块而言
        # 都是「这次调用失败」，直接透传 desc（`loomy-oauth.ts:116-121`）。
        raise RuntimeError(parsed.message or f"讯飞账号请求失败（{path}）")
    return parsed.data if isinstance(parsed.data, dict) else {}


async def send_sms(phone: str) -> str:
    """独立短信登录第 1 步：下发验证码，返回 `msgid`（`loomy-oauth.ts:131-151`）。

    ⚠️ 响应缺 `msgid` 时**抛错**（不返回空串）：上层会拿它去登录，服务端必然报「msgid 无效」，
       用户看到的将是一个与真实原因无关的错误。
    """
    data = await _post_account(C.SEND_SMS_PATH,
                               {"ccode": "86", "phone": phone, "expire": C.SMS_CODE_TTL_S})
    msgid = data.get("msgid")
    if not isinstance(msgid, str) or not msgid:
        raise RuntimeError("短信验证码响应缺少 msgid")
    return msgid


async def login_by_sms(phone: str, code: str, msgid: str) -> dict:
    """独立短信登录第 2 步：提交验证码 → `{session, userid}`（`loomy-oauth.ts:159-180`）。"""
    data = await _post_account(C.LOGIN_SMS_PATH, {
        "ccode": "86", "phone": phone, "mcode": code, "msgid": msgid,
        "expire": C.SESSION_TTL_S,
    })
    session_value = data.get("session")
    userid = data.get("userid")
    if not isinstance(session_value, str) or not session_value:
        raise RuntimeError("登录响应缺少 session")
    if not isinstance(userid, str) or not userid:
        raise RuntimeError("登录响应缺少 userid")
    return {"session": session_value, "userid": userid}


async def bind_auth(code: str) -> dict:
    """微信第 1 步：code 换 `rcode`，并得知是否已绑手机号（`loomy-oauth.ts:214-242`）。

    ⚠️ `bind` 缺失时**归为 0**（走绑定流程）：保守方向 —— 若实际已绑，用户最多多填一次手机号；
       若实际未绑却跳过，会拿到一个没有手机号的账号。
    """
    data = await _post_account(C.BIND_AUTH_PATH, {"tcode": {"code": code}, "type": "wx"})
    rcode = data.get("rcode")
    if not isinstance(rcode, str) or not rcode:
        raise RuntimeError("微信授权响应缺少 rcode")
    return {
        "bind": 1 if data.get("bind") == 1 else 0,
        "rcode": rcode,
        "nickname": data.get("nickname") if isinstance(data.get("nickname"), str) else "",
    }


async def bind_send_msg(rcode: str, phone: str) -> str:
    """微信第 2 步：向待绑定手机号下发验证码，返回 `msgid`（`loomy-oauth.ts:249-267`）。"""
    data = await _post_account(C.BIND_SEND_MSG_PATH, {
        "rcode": rcode, "phone": phone, "ccode": "86", "expire": C.SMS_CODE_TTL_S,
    })
    msgid = data.get("msgid")
    if not isinstance(msgid, str) or not msgid:
        raise RuntimeError("绑定手机号响应缺少 msgid")
    return msgid


async def bind_check_code(rcode: str, code: str, msgid: str) -> dict:
    """微信第 3 步：验证并完成绑定 + 登录（`loomy-oauth.ts:274-295`）。"""
    data = await _post_account(C.BIND_CHECK_CODE_PATH,
                               {"rcode": rcode, "mcode": code, "msgid": msgid,
                                "expire": C.SESSION_TTL_S})
    session_value = data.get("session")
    userid = data.get("userid")
    if not isinstance(session_value, str) or not session_value:
        raise RuntimeError("绑定登录响应缺少 session")
    if not isinstance(userid, str) or not userid:
        raise RuntimeError("绑定登录响应缺少 userid")
    phone = data.get("phone") if isinstance(data.get("phone"), str) else ""
    return {"session": session_value, "userid": userid, "phone": phone}


async def bind_skip(rcode: str) -> dict:
    """微信第 4 步（`bind == 1`）：跳过绑定直接换 session（`loomy-oauth.ts:303-319`）。"""
    data = await _post_account(C.BIND_SKIP_PATH, {"rcode": rcode, "expire": C.SESSION_TTL_S})
    session_value = data.get("session")
    userid = data.get("userid")
    if not isinstance(session_value, str) or not session_value:
        raise RuntimeError("微信登录响应缺少 session")
    if not isinstance(userid, str) or not userid:
        raise RuntimeError("微信登录响应缺少 userid")
    return {"session": session_value, "userid": userid}


# ── 凭据组装 ──────────────────────────────────────────────────────────

def build_credential(session: str, userid: str, phone: str, nickname: str = "") -> dict:
    """构造凭据本体（`loomy-auth.ts:280-288` / `loomy.ts:54-70`）。

    ⚠️ `access_token` 字段名**必须**是这个（含本网关的公共层口径——它是跨产品的身份键）。
    ⚠️ `expires_at` 由**本地**按 14 天推算、以**毫秒时间戳字符串**存（服务端响应里不带到期时间戳，
       它只接受登录请求里的 `expire` 参数；`loomy-auth.ts:277-279`）。
    """
    credential = {
        "access_token": session,
        "userid": userid,
        "phone": phone,
        "expires_at": str(int(time.time() * 1000) + C.SESSION_TTL_S * 1000),
    }
    if nickname:
        credential["nickname"] = nickname
    return credential


def _success(session: str, userid: str, *, phone: str, nickname: str = "",
             login_via: str) -> LoginOutcome:
    """组装成功结果（凭据 + 元信息；落盘由引擎经 `store.commit_login` 负责，§22.3）。"""
    return LoginOutcome(
        state="success",
        credentials=build_credential(session, userid, phone, nickname),
        meta={
            "uid": userid,
            "phone": phone,
            "nickname": nickname,
            "login_via": login_via,   # 审计用：本次是扫码还是短信通道（`via` 由 store 落 "login"）
        },
        detail="登录成功（Loomy）",
    )
