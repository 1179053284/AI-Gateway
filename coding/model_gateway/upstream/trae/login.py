"""TRAE 登录 / 凭据续期 / 探活（§22.4 行 + `20 §1.2/§2.7/§3.5`）。

## 登录形态：local_callback 两步式（**回跳接收端** + 回跳粘贴兜底）

DSH 的做法（`trae-oauth.ts:550-706`）：**自己**在 `127.0.0.1:18080` 起一个回调服务器，
`auth_callback_url = http://127.0.0.1:18080/authorize`，登录页回跳后**就地**用
ExchangeToken 换凭据；18080 被占用时回退随机端口，并用**实际**端口重建授权 URL
（`:530-543,680-693`）。

本网关同款监听由公共层提供（`accounts/callback_server.py`，BD4，2026-09-30 补齐）：
引擎在 `local_callback` 会话 `start()` 时**先绑定**、把**实际端口**交给本模块拼授权 URL，
回跳真到达 → 交给下面这同一条校验/换凭据路径：

    login_start(session)      → 生成 machine_id / 登录期 device_id，用**接收端实际端口**
                                拼 `auth_callback_url`，返回登录页 URL（**零网络**）
    浏览器被 TRAE 302 回本机   → 接收端收到整串 `/authorize?refreshToken=…&userInfo=…`
                                → 引擎 `_deliver` → `login_callback(session, {"url": 整串})`
    （兜底）地址栏粘回来       → 同一入口、同一判据、同一换 token 路径

🔴 本模块**不**起监听、也**不**重复实现任何凭据交换：接收端只负责把一条真 URL
   投递进 `login_callback`（BD4 的接线纪律：一套校验、两套投递）。
   没有接收端时（引擎起监听失败 / 直接构造的会话）`declared_port()` 回退常量 18080，
   粘贴兜底照常可用。

校验三件（**照 DSH 的回调处理器**，`trae-oauth.ts:620-671`）：路径 `/authorize`
（`:622,731` 的 `url.startsWith('/authorize')`，否则 404）、端口 = 本次登录声明的
**实际**端口（`:40,718` + `:680-693` 的回退重建）、以及 `login_trace_id` 关联校验
（`:71-76` 的 `machineTraceId`）——见 `validate_callback`。

失败语义照取证：`state`/关联串不匹配 = 不是本次登录发起的回调（或伪造）→ **直接拒绝**；
ExchangeToken 失败 → 本次登录作废（授权码/token 一次性，重试无意义）。关闭语义由
`accounts/login.py::LoginEngine` 提供：终态出表、取消即失效、TTL 600s，
并**一并关闭该会话的回跳接收端**（BD4：监听与会话同生命周期，出表即关）。

## 🔴 本产品有两套 device 语义，**不得混用**（`trae.ts:82-148,265-314`）

| 值 | 形态 | 生成 | 用途 |
|---|---|---|---|
| `machine_id` | 32 hex | 登录时随机（**此后绝不重生成**） | SOLO 头 `X-Machine-Id`；上游按它标识设备 |
| `device_id`（账号设备身份） | **15 位数字** | `derive_device_id15(uid)` **确定性派生** | 签到头 `X-Device-Id`（`trae-credits.ts:219`） |
| `login_device_id`（登录期） | 32 hex | 登录时随机 | 登录 URL 的 `device_id`；SOLO 头 `X-Device-Id` |

- 第 2 行是 §22.4 / `20 §3.5` 的落点：**9074 设备轮换代次机制已废弃**
  （`20 R14`；`trae-credits.ts:265-276` 注释原文「设备轮换已废弃，不再重试」），
  改用 uid 确定性派生 —— 天然跨账号互异，**不需要**轮换，也**不实现**代次。
- 第 3 行只是**登录载荷**（DSH 的 `generateDeviceId()`，`trae.ts:1301-1305`）：
  协议要求它随登录 URL 下发（`:117-119`），且 DSH 把它当凭据里的 `device_id`
  用于 SOLO 头（`:232-234`）。本网关把它单独存 `meta["login_device_id"]`
  （**不丢信息**，也不与第 2 行同键相撞）——M6-5 出站若要复现 DSH 形态可直接取用。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from model_gateway.accounts import callback_server, device, net, store
from model_gateway.accounts.registry import get as registry_get
from model_gateway.accounts.types import (
    Challenge,
    LoginOutcome,
    NotRefreshable,
    ProbeResult,
)
from model_gateway.upstream.trae import const, protocol

logger = logging.getLogger("model_gateway.accounts")

#: 本产品标识（单一真相源 = `const.PRODUCT_ID`）
PRODUCT = const.PRODUCT_ID


class LoginError(RuntimeError):
    """登录流程的**可预期失败**（网络 / 换 token / 缺 uid/accessToken）。

    由钩子折叠成 `LoginOutcome(state="failed", detail=…)` —— 用户看得见的失败，
    不是"内部故障"（`accounts/login.py` 的「引擎不吞异常」针对的是**未预期**异常）。
    """


def _now_ms() -> int:
    return int(time.time() * 1000)


# ---------- 设备身份（两套语义见模块头）----------

def _machine_spec():
    """`machine_id` 的**单字段投影**规格（跨账号查重用）。

    本产品是多字段 `DeviceSpec`（`machine_id` + `device_id`），而公共层
    `device.generate_unique` 的单值候选与完整元组比较**恒不相等**（查重会静默通过，
    lobsterai 已复现同一缺陷并上报）→ 这里按「设备元组第一字段」投影查重，
    语义 = 「同一 machine_id 不得被第二个账号复用」（§15.1 硬约束 1）。
    """
    from model_gateway.accounts.types import DeviceSpec

    spec = registry_get(PRODUCT).device
    return DeviceSpec(fields=spec.fields[:1], derive=False)


def new_unique_machine_id() -> str:
    """生成**跨账号唯一**的 `machine_id`（32 hex，§22.2 不变式③ / §15.1 硬约束 1）。

    - 形态照抄 `trae.ts:1283-1287`（16 随机字节 → 32 hex，`secrets.token_hex(16)`）；
    - 查重路径不可用（账号根读不动等）时**降级为不查重**：唯一性检查不该让登录起不来
      （碰撞概率 ~0；且随机 machine_id 正是参考实现的行为）。
    """
    spec = _machine_spec()
    try:
        root = store.product_root(PRODUCT)
    except Exception:  # noqa: BLE001 —— 见上：查重失败降级，不阻断登录
        return protocol.new_machine_id()
    for _ in range(20):
        candidate = protocol.new_machine_id()
        try:
            if device.check_unique(root, spec, (candidate,)):
                return candidate
        except Exception:  # noqa: BLE001 —— 同上（目录异常不阻断登录）
            return candidate
    raise LoginError("无法生成不重复的 machine_id（尝试 20 次仍冲突）")


# ---------- 第一步：登录 URL（零网络）----------

def new_login_state() -> dict:
    """生成一次性登录会话态（进 `session.state`，**绝不进 `Challenge`**）。

    - `machine_id`：随机 32hex（跨账号唯一；登录后写入 meta.json，**此后不再改**）；
    - `login_device_id`：登录期 device_id（随机 32hex，随登录 URL 下发）；
    - `login_trace_id`：`machineTraceId(machine_id, login_device_id)` —— 回调关联校验用。
    """
    machine_id = new_unique_machine_id()
    login_device_id = protocol.new_login_device_id()
    return {
        "machine_id": machine_id,
        "login_device_id": login_device_id,
        "login_trace_id": protocol.machine_trace_id(machine_id, login_device_id),
    }


async def login_start(session) -> Challenge:
    """第一步：生成设备字段 + 返回登录页 URL（**零网络调用**，照抄两步式动机）。

    零网络是刻意的（`lobsterai-auth.ts:239-250` 同款）：浏览器只在用户点击后的短暂窗口
    （transient activation，约 5 秒）内允许 `window.open`，任何阻塞式取数都会让弹窗被
    拦截、前端兜底跳转把整个设置页带走。🔴 所以回跳监听**不在这里起** —— 引擎在建会话
    时已经**先绑定**好了（`accounts/login.py::LoginEngine._open_callback`），本函数只读
    它绑到的**实际端口**（BD4：先绑定后拼 URL，`trae-oauth.ts:680-693`）。

    🔴 授权地址的参数名必须是 `auth_callback_url`（`protocol.login_url`，
       `trae-oauth.ts:99-127`）——换别的名字 TRAE 拿不到回调地址，页面永远停在授权中。
    """
    session.state.update(new_login_state())
    port = callback_server.declared_port(session) or const.CALLBACK_PORT
    url = protocol.login_url(str(session.state["machine_id"]),
                             str(session.state["login_device_id"]),
                             callback_url=protocol.callback_url(port))
    return Challenge(url=url)


# ---------- 第二步：回跳校验 + 换凭据 ----------

def validate_callback(session, params: dict) -> str:
    """校验回跳（**返回失败原因，空串 = 通过**）。四层判据逐条附证据：

    ① **路径**：必须是 `/authorize`（DSH 的回调处理器对其它路径回 404，
       `trae-oauth.ts:622,731`）；
    ② **端口**：必须是**本次登录声明的端口**（`:40,718`；BD4 之后它是接收端 `start()`
       绑到的**实际**端口 —— 首选 18080 被占用时接收端回退随机端口并用新端口重建授权 URL，
       `:530-543,680-693`；没有接收端时回退常量 18080，与粘贴兜底同口径）；
    ③ **主机**：必须是回环地址（DSH 只绑 `127.0.0.1`，`:499-503`）；
    ④ **关联串**：回跳带回 `login_trace_id` / `machine_id` / `device_id` 时
       **必须**与本次会话一致（`machineTraceId`，`:71-76`）。

    ⚠️ ④ 只在「带回了」时校验：上游**不保证**回传 machine_id/device_id
    （`:67-70` 原文），DSH 对这些字段**完全不校验**（只看路径）—— 本网关覆写更严，
       但保留「未带回则不拦」以不误伤合法回调（真凭据实测时若发现它恒不回传，
       按 §22.11 记录后收紧）。
    """
    raw = str((params or {}).get("url") or "").strip()
    if raw:
        problem = protocol.callback_url_problem(
            raw, declared_port=callback_server.declared_port(session) or const.CALLBACK_PORT)
        if problem:
            return problem
    table = protocol.callback_params(params or {})
    expected_trace = str(session.state.get("login_trace_id") or "")
    got_trace = str(table.get("login_trace_id") or "")
    if got_trace and expected_trace and got_trace != expected_trace:
        return "回跳与本次登录不匹配（login_trace_id 不一致），已拒绝"
    expected_machine = str(session.state.get("machine_id") or "")
    got_machine = str(table.get("machine_id") or table.get("x_machine_id") or "")
    if got_machine and expected_machine and got_machine != expected_machine:
        return "回跳与本次登录不匹配（machine_id 不一致），已拒绝"
    expected_device = str(session.state.get("login_device_id") or "")
    got_device = str(table.get("device_id") or table.get("x_device_id") or "")
    if got_device and expected_device and got_device != expected_device:
        return "回跳与本次登录不匹配（device_id 不一致），已拒绝"
    return ""


async def _post_json(client: httpx.AsyncClient, url: str, *,
                     headers: dict, body: dict) -> tuple[int, object | None, str]:
    """发一次 POST 并尽力解析 JSON：返回 `(status, body|None, text)`。

    🔴 **不用 `response.json()` 直接判失败**（`trae-auth.ts:399-412` 的真实缺陷复盘）：
       凭据失效时网关返回 **HTML 错误页**，`json()` 抛出的 `Unexpected token '<'`
       对用户毫无意义 → 这里吞掉解析异常回 `None`，由调用方带 HTTP 状态码给可读原因。
    """
    response = await client.post(url, headers=headers, json=body)
    text = response.text
    try:
        return response.status_code, response.json(), text
    except ValueError:
        return response.status_code, None, text


async def exchange_token(refresh_token: str) -> protocol.ExchangeResult:
    """`ExchangeToken`：refreshToken 换 accessToken（**并轮换 refreshToken**）。

    取证：`trae-auth.ts:378-431`（续期同款请求）/ `trae-oauth.ts:375-393`（登录路径）。
    请求体 4 字段 `{ClientID, RefreshToken, ClientSecret:'-', UserID:''}`（`'-'` 是占位，
    不是真实密钥）。⚠️ 续期路径**不复用**本函数：它还要拿原始 status/text 做终态判定
    （见 `refresh_credential`），故那边单独发一次请求。
    """
    body = {
        "ClientID": const.CLIENT_ID,
        "RefreshToken": refresh_token,
        "ClientSecret": const.EXCHANGE_CLIENT_SECRET,
        "UserID": "",
    }
    try:
        async with net.make_client(timeout=const.REQUEST_TIMEOUT_S) as client:
            status, parsed, text = await _post_json(
                client, f"{const.OAUTH_HOST}{const.PATH_EXCHANGE}",
                headers=protocol.oauth_headers(), body=body)
    except httpx.HTTPError as e:
        raise LoginError(f"ExchangeToken 网络失败：{e}") from e
    exchange = protocol.parse_exchange(parsed)
    if exchange is None:
        detail = text.strip().replace("\n", " ")[:120] or "（空响应）"
        raise LoginError(f"ExchangeToken 失败（HTTP {status}）：{detail}")
    return exchange


async def fetch_user_info(access_token: str) -> protocol.UserInfoResult | None:
    """`GetUserInfo` 补齐 uid / 昵称 / 脱敏手机号（**失败不阻塞**，`trae-oauth.ts:405-438`）。

    返回 `None` = 查询失败或结构不符（调用方回退回调里的 `userInfo` 值）。
    """
    if not access_token:
        return None
    try:
        async with net.make_client(timeout=const.REQUEST_TIMEOUT_S) as client:
            status, parsed, _ = await _post_json(
                client, f"{const.OAUTH_HOST}{const.PATH_USER_INFO}",
                headers=protocol.user_info_headers(access_token),
                body=dict(const.USER_INFO_BODY))
    except httpx.HTTPError:
        return None
    if status != 200:
        return None
    return protocol.parse_user_info(parsed)


async def login_callback(session, params: dict) -> LoginOutcome:
    """第二步：校验回跳 → 换凭据 → 组装 `LoginOutcome(state="success")`。

    🔴 **两条投递共用这一个入口**（BD4）：① 回跳接收端把真 URL 交给引擎
    （`accounts/login.py::LoginEngine._deliver` → `callback` → 本函数），
    ② 用户把地址栏整串粘回界面（`POST /admin/api/accounts/login/callback`）。
    参数形态都是 `{"url": 整串地址}`，判据与换 token 路径**同一份实现**。

    凭据落盘由引擎经 `store.commit_login` 完成（§22.3；本函数**不写盘**，只建 meta 增量）。
    """
    problem = validate_callback(session, params)
    if problem:
        return LoginOutcome(state="failed", detail=f"回跳校验未通过：{problem}")
    parsed = protocol.parse_callback(params or {})
    if not parsed.ok or parsed.info is None:
        return LoginOutcome(state="failed", detail=f"回跳解析失败：{parsed.reason}")
    info = parsed.info

    machine_id = str(session.state.get("machine_id") or "")
    login_device_id = str(session.state.get("login_device_id") or "")
    if not machine_id or not login_device_id:
        return LoginOutcome(
            state="failed",
            detail="登录会话缺少 machine_id/device_id（会话状态丢失），请重新发起登录")

    try:
        if info.refresh_token:
            # 分支 1：ExchangeToken（access + refreshToken 轮换）—— `trae-oauth.ts:373-393`
            exchange = await exchange_token(info.refresh_token)
        else:
            # 分支 2：无 refreshToken，直接用 userJwt.Token 兜底（`trae-oauth.ts:394-403`）
            exchange = protocol.ExchangeResult(access_token=info.access_token)
    except LoginError as e:
        # 授权料**一次性**：换失败即本次登录作废，重试无意义（Go/DSH 同）
        return LoginOutcome(state="failed", detail=str(e))
    if not exchange.access_token:
        return LoginOutcome(state="failed", detail="换 token 后没有 accessToken（不落盘半成品）")

    user_info = await fetch_user_info(exchange.access_token)
    uid = (user_info.uid if user_info is not None else "") or info.uid
    if not uid:
        return LoginOutcome(
            state="failed",
            detail="未能确定 uid（回调 userInfo 与 GetUserInfo 均为空）")
    screen_name = (user_info.screen_name if user_info is not None else "") or info.nickname
    phone = user_info.phone if user_info is not None else ""
    email = user_info.email if user_info is not None else ""
    enterprise_id = ((user_info.enterprise_id if user_info is not None else "")
                     or info.enterprise_id)
    display = protocol.display_nickname(phone, email, screen_name, uid, session.name)

    # 🔴 签到设备身份 = uid 确定性派生（`20 §3.5`；9074 轮换代次已废弃，不实现）
    device_id = protocol.derive_device_id15(uid)
    expires_at = protocol.expires_at_ms(exchange, exchange.access_token, now_ms=_now_ms())
    credentials = {
        "access_token": exchange.access_token,
        "refresh_token": exchange.refresh_token,
        "expires_at": expires_at,
        "uid": uid,
        "nickname": screen_name,
        "enterprise_id": enterprise_id,
        # 设备字段（DSH 形状兼容，qoder 同口径）：**权威副本在 meta.json**（§22.2）
        "machine_id": machine_id,
        "device_id": device_id,
        # 登录期 device_id（hex32）：只用于登录 URL / SOLO 头，见模块头第 3 行
        "login_device_id": login_device_id,
    }
    if phone:
        credentials["phone"] = phone
    if email:
        credentials["email"] = email
    meta = {
        "machine_id": machine_id,
        "device_id": device_id,
        "login_device_id": login_device_id,
        "uid": uid,
        "nickname": display,
    }
    if phone:
        meta["phone"] = phone
    if email:
        meta["email"] = email
    logger.info("trae 登录成功（uid %s，设备号 %s，token 指纹 %s）",
                uid, device_id, net.cred_fingerprint(exchange.access_token))
    return LoginOutcome(state="success", credentials=credentials, meta=meta,
                        detail=f"登录成功（{display}）")


# ---------- 续期（`trae-auth.ts:378-431`；`trae.ts:614-637` 的字段合并）----------

async def refresh_credential(cred: dict, meta: dict | None = None) -> dict:
    """静默续期：`ExchangeToken` 换新 token → **新的**凭据体（§22.3）。

    终态判定（`trae-auth.ts:414-430` 的三条依据）：
      - HTTP 401/403 → `NotRefreshable`；
      - 2xx 且响应是 JSON 却没有 token（Go 的 `refresh_failed: no token in response`）
        → `NotRefreshable`（重试一万次也不会有 token，必须让用户重新登录）；
      - 其余失败（网络 / 5xx / 非 JSON）→ 普通异常（**可重试**，由调用方按 §22.6 退避）。

    ⚠️ 一处**已核实的简化**（不是省略）：DSH 在这里还调了 `classifyTraeError` +
    `isTraeTerminalError`（`trae-auth.ts:416,426`），但按 `trae-errors.ts:106-111`，
    `session-dead` 的判据就是 `status === 401` —— 与上面第一条**恒等价**
    （其它分支给出的 hard-plan/soft-rate/quota 都不影响终态判定）→ 不重复引入那套分类。

    成功时把新的 `expires_at` **回写 `meta.json`**（照抄 DSH 缺陷教训 !IKIRTT：
    只更新凭据不写回账号展示值，界面会永远显示「已过期」且没有自救手段）。
    设备字段**一律不改写**（`trae.ts:614-637`：machine_id/device_id/uid 等原样保留）。
    """
    refresh_token = protocol.read_str(cred, "refresh_token")
    if not refresh_token:
        raise NotRefreshable("无 refresh_token，请重新登录")
    api_host = protocol.read_str(cred, "api_host")
    body = {
        "ClientID": const.CLIENT_ID,
        "RefreshToken": refresh_token,
        "ClientSecret": const.EXCHANGE_CLIENT_SECRET,
        "UserID": "",
    }
    try:
        async with net.make_client(timeout=const.REQUEST_TIMEOUT_S) as client:
            status, parsed, text = await _post_json(
                client, f"{api_host or const.OAUTH_HOST}{const.PATH_EXCHANGE}",
                headers=protocol.oauth_headers(), body=body)
    except httpx.HTTPError as e:
        raise RuntimeError(f"TRAE 续期网络失败（可重试）：{e}") from e
    exchange = protocol.parse_exchange(parsed)
    if exchange is None:
        no_token_in_success = 200 <= status < 300 and parsed is not None
        if status in (401, 403) or no_token_in_success:
            raise NotRefreshable("TRAE refresh_token 已失效，请重新登录")
        detail = text.strip().replace("\n", " ")[:200] or "（空响应）"
        raise RuntimeError(f"TRAE 续期失败（HTTP {status}）：{detail}")
    merged = {
        **cred,
        "access_token": exchange.access_token,
        # refresh_token 也会被轮换；新值为空时保留旧值（`trae.ts:633-634`）
        "refresh_token": exchange.refresh_token or refresh_token,
        "expires_at": protocol.expires_at_ms(exchange, exchange.access_token, now_ms=_now_ms()),
    }
    logger.info("trae 续期成功（新 token 指纹 %s）",
                net.cred_fingerprint(exchange.access_token))
    if isinstance(meta, dict) and merged.get("expires_at"):
        write_meta_fields(str(meta.get("dir") or ""), {"expires_at": merged["expires_at"]})
    return merged


# ---------- 探活（§22.3「连通 / 凭据有效」两维）----------

async def probe(cred: dict, meta: dict) -> ProbeResult:
    """探活：连通（拿到了 HTTP 响应）+ 凭据有效（上游认可该凭据）**两维分开**。

    判据端点 = `GetUserInfo`（`trae-oauth.ts:405-438`）：**只读**、不消耗额度、不需要
    签到族头（只要 `Authorization` 形态的 `X-Cloudide-Token`）。DSH 的探活是"发一次
    真实 chat"（`account-probe.ts:163-206`），属出站适配面（M6-5 接线）；本波次用
    账号信息端点做**凭据级**判定，避免为探活烧额度。
    """
    del meta  # 形参按 §22.3 保留：本产品探活不读账号目录（设备字段在凭据本体里）
    access_token = protocol.read_str(cred, "access_token")
    if not access_token:
        return ProbeResult(reachable=False, valid=False,
                           detail="凭据缺少 access_token（未登录，未发请求）")
    try:
        async with net.make_client(timeout=const.REQUEST_TIMEOUT_S) as client:
            status, parsed, _ = await _post_json(
                client, f"{const.OAUTH_HOST}{const.PATH_USER_INFO}",
                headers=protocol.user_info_headers(access_token),
                body=dict(const.USER_INFO_BODY))
    except httpx.HTTPError as e:
        return ProbeResult(reachable=False, valid=False, detail=f"上游不可达：{e}")
    if status in (401, 403):
        return ProbeResult(reachable=True, valid=False,
                           detail=f"凭据已失效（HTTP {status}），请重新登录")
    if status == 200 and parsed is None:
        # 200 但非 JSON：网关在异常时会回 HTML 页面 —— **不得**当成「凭据有效」
        return ProbeResult(reachable=True, valid=False,
                           detail="响应不是 JSON（凭据失效时网关会回 HTML 错误页）")
    info = protocol.parse_user_info(parsed) if status == 200 else None
    if info is not None:
        return ProbeResult(reachable=True, valid=True,
                           detail=f"凭据有效（uid {info.uid}）")
    return ProbeResult(reachable=True, valid=False,
                       detail=f"上游未认可该凭据（HTTP {status}，未取到 UserID）")


def write_meta_fields(dir_path: str, updates: dict) -> None:
    """把展示字段写回账号 `meta.json`（**只补不删**，值没变就不写盘）。

    - 路径由 `meta` 通道给出（§22.3 ③：账号目录经 `meta["dir"]` 传入）；
    - 读不动既有 meta.json → **不动它**（宁可少写一次展示值，也不覆盖账号目录）；
    - 落盘走 `store.atomic_write_json`（§22.2 不变式⑤：禁止 ad-hoc 写盘）。
    """
    if not dir_path:
        return
    path = Path(dir_path) / "meta.json"
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(current, dict):
        return
    merged = {**current, **updates}
    if merged == current:
        return
    store.atomic_write_json(path, merged)
