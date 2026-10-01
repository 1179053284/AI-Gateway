"""Raccoon 登录两步式（扫码主形态 + 短信备选）+ 登录后补全。

🗂 证据面：`src/raccoon-oauth.ts`（纯 API 层）、`src/raccoon-login-page.ts`（本地页承载）、
   `src/jet-hub-rpc.ts:1113-1167`（account.create 的 raccoon 分支）、`:1363-1436`
   （`login.sendSms`/`login.submitSms` 两条辅助通道）；`docs/research/20 §2.8/§4.1`。

**页面承载方式（与 DSH 的对应关系：用户可见行为一致，传输面不同）**：

| 维度 | DSH（宿主侧 Node 进程，无自带界面） | 本网关（自带回环 Web 界面） |
|---|---|---|
| 承载 | 临时 HTTP 服务 `127.0.0.1:<随机端口>`（`raccoon-login-page.ts:50-56,140-141`） | **复用既有回环管理界面 `127.0.0.1:8300`**（§22.7 登录向导弹窗） |
| 路径 | `/raccoon/login`、`/raccoon/poll`、`/raccoon/sms/send`、`/raccoon/sms/verify` | 无新增路径、**无回调路径**（轮询由向导调本层钩子驱动） |
| 二维码 | 宿主侧渲染 **SVG 内联**进页面（`raccoon-qr.ts`，不走 CDN） | **服务端出图**（M7-C1）：`accounts/qr.py` 把同一条内容编成 PNG data URI 进 `Challenge.qr_payload`，前端只显示不编码、也不走 CDN |
| 换码 | `canceled` 时宿主侧就地换新 code 并把新二维码塞回页面（`raccoon-login-page.ts:212-221`） | **同款**：`_reissue()` 换新 code + 新图写回 `session.challenge`，入口层在 `login/poll` 响应里带回当前 challenge → 界面自动换图 |
| 节奏 | 页面每 **2 秒**轮询 `/raccoon/poll`（`raccoon-login-page.ts:421`） | 入口层驱动（§22.8-2/-3：**钩子内不打循环、不 sleep**），TTL 600s 兜总时限 |

🔴 与官方桌面端的差别（照抄 DSH 的结论，`raccoon.ts:10-15`）：官方走
   `office-raccoon://auth/callback` 自定义协议回调，而该回调地址在授权页里**写死**、
   改不成回环地址；故改为「客户端本地生成 code + 自行轮询」—— **实测任意自造 code 都被接受**。
🔴 **短信路径不属于 §22.3 的十钩子**：`login_start` / `login_poll` 只承载**主形态（扫码）**；
   短信两步（发码 / 提交验证码）与 DSH 的 `login.sendSms` + `login.submitSms` 两条辅助 RPC
   （`jet-hub-rpc.ts:1363-1436`）同构，故在本模块导出两个**产品私有**入口，由入口层按
   `ProductMeta.login_alt` 渲染短信 Tab 后调用（接线属 M6-4，见 `product.sms_send` 的注释）。
🔴 上游调用**只经** `accounts/net.py::make_client`（显式超时，§22.8-1）→ 测试可 monkeypatch。
"""

from __future__ import annotations

import logging

import httpx

from model_gateway.accounts import net
from model_gateway.accounts import qr
from model_gateway.accounts.types import Challenge, LoginOutcome
from model_gateway.upstream.raccoon import const as C
from model_gateway.upstream.raccoon import protocol as p

logger = logging.getLogger("model_gateway.upstream.raccoon")


# ---------- 扫码（主形态，§22.4）----------


async def start(session) -> Challenge:
    """扫码登录第一步：本地生成 `qrcode_code` → **服务端出二维码图**（`raccoon-oauth.ts:111-130`）。

    ```
    code = 32 位小写 hex（本地随机，服务端接受任意自造值）
    内容 = {apiBase}/login/mp?code=<code>&appname=商汤小浣熊官网
    图片 = 内容编成 PNG（`accounts/qr.py`：byte 模式 + 纠错等级 M + 版本 ≤10）
    ```

    🔴 分工（M7-C1 改口径；`accounts/types.py:95-105`）：
      · 二维码**图片** data URI → `Challenge.qr_payload`（界面直接 `<img src>`，不再跨域、
        不再"把内容串印成一行字让用户扫"）；
      · 二维码**内容**（那条 URL）→ `Challenge.url`：它仍是用户可见物 —— 复制给另一台
        能扫码的设备、或在"这台设备扫不了"时人工打开的兜底；
      · 轮询所需的 `code` → `session.state`（**不进 Challenge**：它已经在图里，
        而 `LoginOutcome.detail` 绝不出 code）。
    ⚠️ 内容**过长**（>213 字节）→ `accounts/qr.py` 抛 `RuntimeError`，**不静默截断**
       （照 `raccoon-qr.ts:488-493` 的纪律：截断产出的是一张扫不出来的坏码）。
       本产品的内容形态固定约 145 字节，走不到那条分支，但判据必须在位。
    """
    code = p.new_qr_code()
    session.state["qr_code"] = code
    session.state["qr_reissues"] = 0
    return _challenge(code)


def _challenge(code: str) -> Challenge:
    """内容串 + **服务端出的** PNG data URI（`start` 与换发 `_reissue` 共用同一份实现）。

    出图是本地纯计算（无网络、无 IO），所以本函数是同步的 —— 也因此 `start()` 全程零上游请求
    （既有测试 `test_qr_start_generates_code_locally_without_network` 钉的就是这条）。
    """
    payload = p.qr_login_url(code)
    return Challenge(url=payload, qr_payload=qr.png_data_uri(payload))


def _reissue(session, reason: str) -> LoginOutcome:
    """上游判旧码作废（`canceled`）→ **就地换发一张新码**，会话继续（回 `pending`）。

    照抄 DSH 的本地页处置（`raccoon-login-page.ts:213-220`：`canceled` 时
    `state.qrCode = generateQrCode()` 并把新二维码 SVG 塞回页面，注释原话"否则用户卡死"）。
    本网关同形：新 code → 新 PNG 写回 `session.challenge`，入口层在轮询响应里带回当前
    challenge（`api/admin_accounts.py::login_poll`），前端比对 `qr_payload` 换图。
    ⚠️ 上限 `accounts/qr.py::MAX_REISSUES`（超限如实 `expired` 让用户重新发起）：
       旧实现把 `canceled` 直接判 `expired` 终态 → 用户必须手动点一次「重新发起登录」，
       这一条按 M7-C1 任务书改（并保留"多次换发后如实收场"的兜底）。
    """
    used = int(session.state.get("qr_reissues") or 0)
    if used >= qr.MAX_REISSUES:
        return LoginOutcome(state="expired", detail=(
            f"{reason}，且本次会话已换发 {used} 张二维码（上限 {qr.MAX_REISSUES}）"
            f"——请重新发起登录"))
    session.state["qr_reissues"] = used + 1
    code = p.new_qr_code()
    session.state["qr_code"] = code
    session.challenge = _challenge(code)
    return LoginOutcome(state="pending", detail=(
        f"{reason}，已换发第 {used + 1} 张二维码，请扫新码（界面会自动换成新图）"))


async def poll_qr(session) -> LoginOutcome:
    """扫码登录第二步：`POST /api/web/auth/v1/login_with_qrcode_code`（`raccoon-oauth.ts:140-180`）。

    状态机（**判据 = 响应体 `data.status`**，`:158-179`）：

    | 上游 `status` | 本项目状态 | 说明 |
    |---|---|---|
    | `pending` / `logging` / 未知值 | `pending` | **不是错误**：等待扫码（`logging` = 已扫码待确认） |
    | `success` **且**有 `access_token` | `success` | 组装凭据（`expires_at` 由 JWT 推算） |
    | `success` 但缺 `access_token` | `pending` | 缺 token 的 success 视为未完成（`:169-170`：否则产出空凭据卡死） |
    | `canceled` | **`pending` + 就地换发一张新码** | 用户在微信里取消 → 旧码作废；新 code/新图写回 `session.challenge`（M7-C1，见 `_reissue`） |

    ⚠️ **网络异常 / 响应畸形 / 非零 code ⇒ `pending`**（照抄 `:132-139` 的降级）：轮询期间偶发
    失败不应中断流程；把未知状态误判成 `success` 会拿到空 token 卡死，误判成 `canceled` 会让
    用户正在扫的二维码被无故刷新。
    ⚠️ `canceled` 的映射（M7-C1 改口径）：DSH 的本地页在 `canceled` 时**就地换一个新 code**
    并把新二维码塞回页面（`raccoon-login-page.ts:212-221`）。旧实现因为"`LoginOutcome` 没有
    载荷通道"而判 `expired` 终态、要用户手动点「重新发起登录」；现在换发通道 =
    **产品把新 `Challenge` 写回 `session.challenge`** + 入口层在轮询响应里带回当前 challenge
    （`api/admin_accounts.py::login_poll`）→ 与 DSH 的用户可见行为一致（页面自己换图）。
    ⚠️ 本钩子**不打轮询循环、不 sleep**：一次 poll = 一次上游请求，节奏与总时限由入口层/会话 TTL
    负责（§22.8-2/§22.8-3）。DSH 的 2 秒间隔（`raccoon.ts:57-58`）只是它页面侧的节奏。
    ℹ️ 与 loomy 的差别：本产品这个端点**即刻返回**（不是长轮询），所以 `REQUEST_TIMEOUT_S=60`
       不会把一个管理端请求挂几十秒，无需 loomy 那样的读预算（`loomy/constants.py` 的
       `WECHAT_POLL_BUDGET_S` 是为微信长轮询专门加的）。
    ⚠️ DSH 轮询在 `logging` 时还回 `expired_at` 供页面展示倒计时（`raccoon-oauth.ts:160-165`）；
    本层丢弃该字段 —— 冻结的 `LoginOutcome` 没有承载它的位置，倒计时展示归前端。
    """
    code = str(session.state.get("qr_code") or "")
    if not code:
        return LoginOutcome(state="failed", detail="会话缺少二维码 code（login_start 未成功）")
    try:
        async with net.make_client(base_url=C.API_BASE, timeout=C.REQUEST_TIMEOUT_S) as client:
            resp = await client.post(C.LOGIN_QRCODE_PATH, json={"qrcode_code": code})
            payload = _json_or_none(resp)
    except httpx.HTTPError as e:
        return LoginOutcome(state="pending", detail=f"扫码状态查询网络错误（继续等待）：{e}")

    envelope = p.parse_envelope(payload, resp.status_code)
    if not envelope.ok or envelope.data is None:
        # 未登录时的失败属正常轮询噪声（DSH 同样降级为 pending）；不把 code 写进 detail
        return LoginOutcome(state="pending", detail="扫码状态查询暂不可用（继续等待）")
    status = p.read_str(envelope.data, "status")
    if status == C.QR_STATUS_CANCELED:
        return _reissue(session, "二维码已失效（你在微信中取消了授权）")
    if status not in (C.QR_STATUS_PENDING, C.QR_STATUS_LOGGING, C.QR_STATUS_SUCCESS):
        # 未知状态：保守当「等用户」（照抄 `raccoon-oauth.ts:179` 的兜底），不误判成功/取消
        return LoginOutcome(state="pending", detail="扫码状态未知（继续等待）")
    if status == C.QR_STATUS_LOGGING:
        return LoginOutcome(state="pending", detail="已扫码，请在微信中确认")
    if status == C.QR_STATUS_PENDING:
        return LoginOutcome(state="pending", detail="等待用户用微信扫码并确认")
    if not p.read_str(envelope.data, "access_token"):
        return LoginOutcome(state="pending", detail="登录尚未就绪（success 但缺 access_token）")

    credentials = p.credentials_from_login(envelope.data)
    credentials = await _enrich(credentials)
    return LoginOutcome(state="success", credentials=credentials,
                        meta={"nickname": p.build_nickname(credentials,
                                                           getattr(session, "name", ""))},
                        detail="登录成功")


async def _enrich(credentials: dict) -> dict:
    """登录后补全用户信息（`raccoon-auth.ts:232-256` 的 `persistLogin` 前段）。

    ⚠️ 手机号专门为**多账号消歧**而存：远端的 `name` 是自动生成的默认名（实测 `RaccoonAva`），
    微信扫码不回传微信昵称，故多个账号会重名（`raccoon.ts:87-103`）。
    ⚠️ **失败不影响登录**（`:238-256`）：`user_info` 只是展示/消歧用，它抖动不能让登录失败。
    """
    if all(p.read_str(credentials, key) for key in ("nickname", "user_id", "phone")):
        return credentials
    info = await user_info(credentials)
    merged = dict(credentials)
    for key in ("user_id", "nickname", "office_identity", "phone"):
        if info.get(key) and not p.read_str(merged, key):
            merged[key] = info[key]
    return merged


async def user_info(credentials: dict) -> dict:
    """`GET /api/web/auth/v1/user_info`（只读；`raccoon-oauth.ts:330-359`）。

    返回 `{user_id?, nickname?, office_identity?, phone?}`；**失败返回空 dict**（不抛）——
    它只用于展示与探活。
    """
    try:
        async with net.make_client(base_url=C.API_BASE, timeout=C.REQUEST_TIMEOUT_S) as client:
            resp = await client.get(C.USER_INFO_PATH, headers=p.headers(credentials))
            payload = _json_or_none(resp)
    except httpx.HTTPError:
        return {}
    envelope = p.parse_envelope(payload, resp.status_code)
    if not envelope.ok or envelope.data is None:
        return {}
    out: dict = {}
    for src, dst in (("id", "user_id"), ("name", "nickname"),
                     ("office_identity", "office_identity"), ("phone", "phone")):
        value = p.read_str(envelope.data, src)
        if value:
            out[dst] = value
    return out


# ---------- 短信（备选形态，`login_alt=("sms_code",)`）----------


async def send_sms(session, *, phone: str, captcha_param: str = "") -> Challenge:
    """短信第一步：`POST /api/web/auth/v1/send_sms`（`raccoon-oauth.ts:183-210`）。

    ```
    body: {captcha_param, nation_code: "86", phone: <AES-128-CFB 加密>}
    ```

    ⚠️ 两条必需条件（缺一必被拒，`:185-188`）：
      ① 手机号必须加密（否则 `100003 params_encryted_error`）；
      ② `captcha_param` 是阿里云滑块产物（否则 `100006 captcha_verify_error`）。
    滑块在**前端**完成（DSH 也是页面侧加载官方脚本，`raccoon-login-page.ts:504-522`），
    本层只做服务端提交。

    成功 → `Challenge(sms_sent=True)`，并把手机号暂存 `session.state`（供 `submit_sms` 取用；
    照抄 DSH「只在发送成功后才记住手机号」的次序，`raccoon-login-page.ts:234-238`）。
    失败 → **抛 `RuntimeError`**（可读原因由入口层回给向导；用户可重试，不终止流程）。
    """
    if not p.phone_valid(phone):
        raise RuntimeError("请输入有效的 11 位手机号")
    body = {"captcha_param": str(captcha_param or ""), "nation_code": "86",
            "phone": p.encrypt_phone(phone)}
    try:
        async with net.make_client(base_url=C.API_BASE, timeout=C.REQUEST_TIMEOUT_S) as client:
            resp = await client.post(C.SEND_SMS_PATH, json=body)
            payload = _json_or_none(resp)
    except httpx.HTTPError as e:
        raise RuntimeError(f"下发短信验证码网络错误：{e}") from e
    envelope = p.parse_envelope(payload, resp.status_code)
    if not envelope.ok:
        if envelope.code == C.CODE_CAPTCHA_VERIFY_ERROR:
            # 服务端原文口径（`raccoon-oauth.ts:205-207`）
            raise RuntimeError("图形验证码校验失败，请重新完成滑块验证")
        if envelope.code == C.CODE_PHONE_ENCRYPT_ERROR:
            # 本地 AES-128-CFB 若与客户端算法漂移，这里是**唯一**能暴露它的信号
            # （`raccoon.ts:17`：`100003 params_encryted_error`）
            raise RuntimeError("手机号加密参数被服务端拒绝（100003 params_encryted_error）")
        raise RuntimeError(f"下发短信验证码失败（HTTP {resp.status_code}）："
                           f"{envelope.error_text('服务端未给原因')}")
    session.state["sms_phone"] = phone
    return Challenge(sms_sent=True)


async def submit_sms(session, *, sms_code: str) -> LoginOutcome:
    """短信第二步：`POST /api/web/auth/v1/login_with_sms`（`raccoon-oauth.ts:212-235`）。

    - 未先发码（`session.state` 无手机号）→ `failed`「请先获取手机验证码」
      （`raccoon-login-page.ts:253-257` 的同款前置检查）；
    - 成功 → 凭据（`_enrich` 补全，同扫码路径）；失败 → `failed` + 可读原因
      （用户可重输，**不再**复用 DSH「失败不删占位」那套——本网关的账号只在成功时物化）。
    """
    phone = str(session.state.get("sms_phone") or "")
    if not phone:
        return LoginOutcome(state="failed", detail="请先获取手机验证码")
    code = str(sms_code or "").strip()
    if not code:
        return LoginOutcome(state="failed", detail="请输入验证码")
    body = {"nation_code": "86", "phone": p.encrypt_phone(phone), "sms_code": code}
    try:
        async with net.make_client(base_url=C.API_BASE, timeout=C.REQUEST_TIMEOUT_S) as client:
            resp = await client.post(C.LOGIN_SMS_PATH, json=body)
            payload = _json_or_none(resp)
    except httpx.HTTPError as e:
        return LoginOutcome(state="failed", detail=f"短信登录网络错误：{e}")
    envelope = p.parse_envelope(payload, resp.status_code)
    if not envelope.ok:
        return LoginOutcome(
            state="failed",
            detail=f"短信登录失败（HTTP {resp.status_code}）：{envelope.error_text('验证码不正确或已过期')}")
    if not p.read_str(envelope.data, "access_token"):
        # 200 却缺 token：服务端异常，不得当成功（不产出半截凭据）
        return LoginOutcome(state="failed", detail="短信登录响应缺少 access_token")
    credentials = await _enrich(p.credentials_from_login(envelope.data))
    credentials.setdefault("phone", phone)
    return LoginOutcome(state="success", credentials=credentials,
                        meta={"nickname": p.build_nickname(credentials, session.name)},
                        detail="登录成功")


# ---------- 内部工具 ----------


def _json_or_none(resp: httpx.Response) -> object:
    """读 JSON 体；非 JSON → `None`（**不因解析失败而丢掉 HTTP 事实**）。

    照抄 DSH 的容错口径：凭据过期时网关可能回 HTML 错误页，`resp.json()` 抛出的
    `Unexpected token '<'` 对用户毫无意义。
    """
    try:
        return resp.json()
    except ValueError:
        return None
