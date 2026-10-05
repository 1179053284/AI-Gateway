"""TRAE 协议层：JSON 安全读取 / 请求头 / 设备身份派生 / 回调解出 / 目录解析。

**全部为纯函数或纯数据构造**（不发请求、不写盘）——网络与落盘分别归 `login.py` /
`quota.py` / `claim.py` / `models.py` 与 `accounts/store.py`（§22.2 不变式⑤）。

取证（`file:line` 均为 DSH `deepseek-harness-codearts/src/trae*.ts`）：

- JSON 读取三件套 = `trae.ts:1409-1437`（`readStringField` / `readNumberField` /
  `readBooleanField`）。**「字段缺失」与「显式为假」必须分开**：布尔读取只认
  `true/1/"true"` 与 `false/0/"false"`，其余（含缺失）回 `None`。
- 设备身份派生 = `trae.ts:316-381`（`deriveDeviceId15` / `deriveMarketUserId` /
  `deriveSessionId` + `seededStream` 的 SHA-256 伪随机流）。
- 请求头三族 = `trae.ts:204-314`（SOLO / UG / 签到专用完整头）。
- 回调解出 = `trae-oauth.ts:263-345`（两套流程：老流程直传 token、新流程 PKCE 码）。
- 目录解析 = `trae.ts:1056-1273`（条目解析 + 三规则合并 + 三条硬性过滤）。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

from model_gateway.upstream.trae import const

# ── JSON 安全读取（`trae.ts:1409-1437`）─────────────────────────────────

def read_str(source: Any, *keys: str) -> str:
    """读第一个非空字符串字段；数字按字符串收（后端会把数字返回成 number，`trae.ts:1409`）。"""
    if not isinstance(source, dict):
        return ""
    for key in keys:
        value = source.get(key)
        if isinstance(value, str):
            if value:
                return value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return ""


def read_num(source: Any, *keys: str) -> float | None:
    """读第一个可解析的数字字段（兼容字符串形态，`trae.ts:1417`）；取不到 `None`。"""
    if not isinstance(source, dict):
        return None
    for key in keys:
        value = source.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and re.fullmatch(r"-?\d+(\.\d+)?", value.strip()):
            return float(value.strip())
    return None


def read_bool(source: Any, key: str) -> bool | None:
    """读布尔字段（**只认明确取值**，`trae.ts:1431`）：缺失/异形态 → `None`。

    不接受任意 truthy 值 —— 空字符串在 JS 里 falsy，把它当 `false` 是没有依据的断言。
    """
    if not isinstance(source, dict):
        return None
    value = source.get(key)
    if isinstance(value, bool):
        return value
    if value == 1 or value == "true":
        return True
    if value == 0 or value == "false":
        return False
    return None


def read_code(body: Any) -> int:
    """读业务码（兼容数字与数字字符串，`trae-credits.ts:127-132` 的 `readClaimCode`）。

    ⚠️ **字段缺失 = 0**（照抄）：后端在部分网关上以字符串 `"9074"` 返回，只认数字会把
    它误读成 `0`（= 成功）；反之缺字段时 DSH 也按 0 处理（调用方另有 status 复核兜底）。
    """
    if not isinstance(body, dict):
        return -1
    raw = body.get("code")
    if isinstance(raw, bool):
        return -1
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str) and re.fullmatch(r"-?\d+", raw.strip()):
        return int(raw.strip())
    return 0


def message_of(body: Any) -> str:
    """业务消息（`message` 优先、`msg` 兜底，`trae-credits.ts:272,278`）。"""
    return read_str(body, "message") or read_str(body, "msg")


# ── 设备身份确定性派生（`trae.ts:316-381`）──────────────────────────────

def seeded_stream(seed: str, salt: str, nbytes: int) -> bytes:
    """SHA-256 确定性伪随机流（`trae.ts:353-373` 的逐字节移植）。

    算法：`SHA256(utf8(f"{salt}:{seed}") ++ counterBE32)` 串联到够 `nbytes` 字节。
    输入相同 → 输出永远相同（跨进程、跨重启稳定）。
    """
    prefix = f"{salt}:{seed}".encode("utf-8")
    out = bytearray()
    counter = 0
    while len(out) < nbytes:
        digest = hashlib.sha256(prefix + counter.to_bytes(4, "big")).digest()
        out.extend(digest[: nbytes - len(out)])
        counter += 1
    return bytes(out)


def derive_device_id15(uid: str) -> str:
    """由 uid 派生 **15 位数字**设备号（`trae.ts:324-326` 的 `deriveDeviceId15`）。

    这是**签到身份的唯一形态**（`trae.ts:259-286`：签到头 `X-Device-Id` 用它；
    `trae-credits.ts:219` 原文「设备身份：基于 `credential.uid` 确定性派生，每个账号
    独立稳定」）。同 uid 永远得到同一套设备标识 → 跨进程稳定、天然互异、免持久化
    （`20 §3.5` / `20 B12`）。
    """
    stream = seeded_stream(uid, "devid", 15)
    return "".join(str(byte % 10) for byte in stream)


def derive_market_user_id(uid: str) -> str:
    """由 uid 派生 `X-Market-User-Id`（UUID v4 形态，`trae.ts:331-337`）。"""
    buf = bytearray(seeded_stream(uid, "market", 16))
    buf[6] = (buf[6] & 0x0F) | 0x40   # version 4
    buf[8] = (buf[8] & 0x3F) | 0x80   # variant RFC 4122
    hexed = buf.hex()
    return (f"{hexed[0:8]}-{hexed[8:12]}-{hexed[12:16]}-"
            f"{hexed[16:20]}-{hexed[20:32]}")


def derive_session_id(uid: str) -> str:
    """由 uid 派生 `Vscode-Sessionid`（64 位 hex，`trae.ts:342-345`）。"""
    return seeded_stream(uid, "sess", 32).hex()


def machine_trace_id(machine_id: str, device_id: str) -> str:
    """`login_trace_id` = 拼接串的**尾部 16 字符**（`trae-oauth.ts:71-76`）。

    作用是让回调能被关联回本次登录的 pending（TRAE 回调**不保证**回传
    machine_id/device_id，但会回传 `login_trace_id`）→ 本网关据此做回跳校验
    （`login.py::validate_callback`）。
    """
    joined = f"{machine_id}{device_id}"
    return joined[-16:] if len(joined) >= 16 else joined.rjust(16, "0")


def new_machine_id() -> str:
    """新的 `machine_id`：**32 位 hex**（`trae.ts:1283-1287` 的 `generateMachineId`）。

    ⚠️ 登录时生成后**绝不重新生成**（`trae.ts:135-141`：上游按它标识设备，
    换值可能触发风控或要求重新登录）。跨账号唯一性由 `login.py` 查重后落 meta。
    """
    return secrets.token_hex(16)


def new_login_device_id() -> str:
    """新的**登录期** device_id：32 位 hex（`trae.ts:1301-1305` 的 `generateDeviceId`）。

    ⚠️ 与「账号设备身份」区分（本产品有两套 device 语义，见 `login.py` 模块头）：
    本值只用于登录 URL 的 `device_id`/`x_device_id` 与将来 SOLO 出站的 `X-Device-Id`；
    签到身份一律用 `derive_device_id15(uid)`（`trae.ts:265-314`）。
    """
    return secrets.token_hex(16)


# ── 请求头（`trae.ts:204-314`）──────────────────────────────────────────

def oauth_headers() -> dict[str, str]:
    """OAuth（ExchangeToken / GetUserInfo）头（`trae.ts:408-414`）：无签名，仅 UA。"""
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": const.USER_AGENT,
    }


def user_info_headers(access_token: str) -> dict[str, str]:
    """GetUserInfo 头 = OAuth 头 + `X-Cloudide-Token`（`trae-oauth.ts:417-418`）。"""
    headers = oauth_headers()
    headers["X-Cloudide-Token"] = access_token
    return headers


def checkin_headers(access_token: str, uid: str) -> dict[str, str]:
    """签到 / 积分专用**完整客户端头**（`trae.ts:281-314` 的 `traeCheckinHeaders`）。

    🔴 与简化的 `traeUgHeaders` 的**关键区别**：`X-Device-Id` 用
    `derive_device_id15(uid)`（15 位数字、每账号独立稳定），而不是凭据里的 hex32
    `device_id` —— trae-mate 实测签到成功用的就是这一套（`trae.ts:265-286`）。
    每次请求生成独立的 `X-Request-Id` 与 `X-Tt-Trace-Id`。
    """
    return {
        "Content-Type": "application/json",
        "User-Agent": const.CHECKIN_USER_AGENT,
        "Authorization": f"Cloud-IDE-JWT {access_token}",
        "X-Market-Client-Id": const.CHECKIN_MARKET_CLIENT_ID,
        "X-Market-User-Id": derive_market_user_id(uid),
        "X-User-Region": "CN",
        "X-Device-Id": derive_device_id15(uid),
        "App-Version": const.IDE_VERSION,
        "X-Tt-Trace-Id": f"00-{secrets.token_hex(8)}-01",
        "Vscode-Sessionid": derive_session_id(uid),
        "X-Request-Id": str(uuid.uuid4()),
        **const.CHECKIN_FIXED_HEADERS,
    }


def solo_headers(cred: dict, *, stream: bool = False) -> dict[str, str]:
    """SOLO（对话 / 模型目录）头（`trae.ts:204-236` 的 `traeSOLOHeaders`）。

    ⚠️ 多处重复设置同一个 token（`Authorization` / `X-Cloudide-Token` / `X-Ide-Token`），
    **缺任一都可能被上游拒绝**（`trae.ts:196-198` 原文），故三个都发。
    `X-Machine-Id` / `X-Device-Id` 取凭据里的设备字段（登录时写入）。
    """
    access_token = read_str(cred, "access_token")
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
        "User-Agent": const.USER_AGENT,
        "Authorization": f"Cloud-IDE-JWT {access_token}",
        "X-Cloudide-Token": access_token,
        "X-Ide-Token": access_token,
        "X-Uid": read_str(cred, "uid"),
        "X-App-Id": const.APP_ID,
        "X-Ide-Version": const.IDE_VERSION,
        "X-Ide-Version-Code": const.IDE_VERSION_CODE,
        "X-App-Version-Code": const.IDE_VERSION_CODE,
        "X-OS-Version": const.OS_VERSION,
        "X-Device-Brand": const.DEVICE_BRAND,
        **const.SOLO_FIXED_HEADERS,
    }
    machine_id = read_str(cred, "machine_id")
    if machine_id:
        headers["X-Machine-Id"] = machine_id
    device_id = read_str(cred, "login_device_id") or read_str(cred, "device_id")
    if device_id:
        headers["X-Device-Id"] = device_id
    return headers


# ── 登录 URL（`trae-oauth.ts:99-127`）───────────────────────────────────

def login_url(machine_id: str, device_id: str, *, callback_url: str,
              console_host: str = const.CONSOLE_HOST) -> str:
    """构造登录 URL（**17 参数一个不能少**，`trae-oauth.ts:99-127`）。

    ## ⚠️ 为什么参数一个都不能少（真实缺陷）

    DSH 的早期实现只发了 `client_id` / `machine_id` / `device_id` / `callback_url`
    （`trae-oauth.ts:84-97` 的缺陷复盘）：

    1. 回调地址的参数名是 **`auth_callback_url`**，不是 `callback_url`（也没有
       `redirect_uri`）—— 名字错了 TRAE 拿不到回调地址，登录页**永远停在授权中**；
    2. `auth_from` / `login_channel` / `auth_type` / `redirect` 决定授权通道，
       缺了走不到本地回传分支；
    3. `login_trace_id` 是回调反查 pending 的唯一凭据（本网关的回跳校验也用它）；
    4. `x_*` 系列是客户端形态伪装，缺席可能被风控拦截。
    """
    from urllib.parse import urlencode

    params = {
        "login_version": "1",
        "auth_from": "solo",
        "login_channel": "native_ide",
        "plugin_version": const.PLUGIN_VERSION,
        "auth_type": "local",
        "client_id": const.CLIENT_ID,
        "redirect": "0",
        "login_trace_id": machine_trace_id(machine_id, device_id),
        "auth_callback_url": callback_url,
        "machine_id": machine_id,
        "device_id": device_id,
        "x_device_id": device_id,
        "x_machine_id": machine_id,
        "x_device_brand": const.LOGIN_DEVICE_BRAND,
        "x_device_type": const.LOGIN_DEVICE_TYPE,
        "x_os_version": const.LOGIN_OS_VERSION,
        "x_app_version": const.IDE_VERSION,
        "x_app_type": const.LOGIN_APP_TYPE,
    }
    return f"{console_host}{const.LOGIN_PATH}?{urlencode(params)}"


def callback_url(port: int = const.CALLBACK_PORT) -> str:
    """本次登录对外声明的回调地址（`http://127.0.0.1:{**实际**端口}/authorize`）。

    🔴 BD4（2026-09-30）：这个端口上**真的有一个接收端**在听
    （`accounts/callback_server.py`，随登录会话创建）——此前它只是"构造出来但没人听"，
    浏览器打开就是 connection refused，登录只能靠人把地址栏整串粘回来。

    ⚠️ 参数必须是接收端 `start()` 返回的**实际**端口，不能传常量：TRAE 首选 18080，
       被占用时接收端回退随机端口（`trae-oauth.ts:530-543`），而授权地址要跟着回退后的
       端口重建（`:680-693`）——写死 18080 会让回跳打到别人家。
       没有接收端时（起监听失败 / 直接构造的会话）传缺省值 18080，粘贴兜底仍按它校验。
    """
    return f"http://127.0.0.1:{port}{const.CALLBACK_PATH}"


# ── 回调解出（`trae-oauth.ts:263-345`）─────────────────────────────────

@dataclass(frozen=True)
class CallbackInfo:
    """回跳地址里解出的凭据料（`TraeCallbackInfo`，`trae-oauth.ts:134-162`）。"""

    #: 优先取 query.refreshToken；缺失时回退 userJwt.RefreshToken。
    refresh_token: str = ""
    #: 无 refreshToken 时的兜底 access token（userJwt.Token）。
    access_token: str = ""
    uid: str = ""
    nickname: str = ""
    #: ⚠️ 回调里的字段名是 **TenantID**（不是 EnterpriseID），`trae-oauth.ts:141`。
    enterprise_id: str = ""
    #: 新流程（PKCE）携带的授权码 —— 本实现**不支持**，只用于精确报错（`trae-oauth.ts:161`）。
    auth_code: str = ""
    #: 回跳带回的关联串（本网关做校验用；上游不保证带回）。
    login_trace_id: str = ""
    #: 回跳带回的设备字段（上游不保证带回；带回时必须与本次会话一致）。
    machine_id: str = ""
    device_id: str = ""


@dataclass(frozen=True)
class CallbackParse:
    """解出结果 or 失败原因（`TraeCallbackParseResult`，`trae-oauth.ts:171-173`）。"""

    ok: bool
    info: CallbackInfo | None = None
    reason: str = ""
    #: True = 上游走了 PKCE 流程（合法回调，但本实现不支持该分支）。
    auth_code_flow: bool = False


def _json_param(raw: str) -> dict | None:
    """解析 URL 编码的 JSON 参数（`trae-oauth.ts:182-198` 的 `parseJsonParam`）。

    `parse_qs` 已解一层 percent-encoding，但 TRAE 的 `userInfo` 中文存在**双重编码**
    （实测昵称乱码 `Óû§8847309959`）→ 再容错解一层。
    """
    from urllib.parse import unquote

    if not raw:
        return None
    candidates = [raw]
    unescaped = unquote(raw)
    if unescaped != raw:
        candidates.append(unescaped)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _param_value(source: dict, key: str) -> str:
    """从**已解出的参数表**取字符串值（dict 值转 JSON 串，兼容前端结构化传参）。"""
    value = source.get(key)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def callback_params(params: dict) -> dict[str, str]:
    """把入口层传来的 `params` 归一成**回跳查询参数表**（两种形态都认）。

    - `{"url": "<整串地址 / `/authorize?…` / `refreshToken=…&…`>"}`（回跳粘贴主通道）；
    - 或直接给回调的平铺键（`refreshToken` / `userInfo` / `userJwt` / `login_trace_id` …）。

    ⚠️ **不做更多别名猜测**（lobsterai 同口径）：认不出的形态当场解出空表 → 由
    `parse_callback` 给出可读失败原因。
    """
    if not isinstance(params, dict):
        return {}
    raw = str(params.get("url") or "").strip()
    if raw:
        if "?" not in raw and "=" in raw:
            raw = "?" + raw
        split = urlsplit(raw if "://" in raw else f"http://127.0.0.1{raw}")
        values = parse_qs(split.query, keep_blank_values=True)
        return {key: (items[0] if items else "") for key, items in values.items()}
    keys = ("refreshToken", "userJwt", "userInfo", "code", "authCode", "authCodeInfo",
            "login_trace_id", "machine_id", "device_id", "x_machine_id", "x_device_id")
    if any(key in params for key in keys):
        return {key: _param_value(params, key) for key in keys if key in params}
    return {}


def callback_url_problem(raw: str, *, declared_port: int = const.CALLBACK_PORT) -> str:
    """回跳地址的**形态**校验（返回失败原因，空串 = 通过或未给地址）。

    照 DSH 的回调处理器（`trae-oauth.ts:620-671`）：路径必须 `/authorize`
    （`:622,731` 对其它路径回 404）、端口必须是**本次登录声明的那个端口**、
    主机必须回环（`:499-503` 只绑 `127.0.0.1`）。

    🔴 `declared_port` = 回跳接收端的**实际**端口（`callback_server.declared_port(session)`）：
       18080 只是**首选**，被占用时接收端回退随机端口（`:530-543`）并且授权 URL 跟着重建
       （`:680-693`）—— 校验若还钉着 18080，就会把真回跳判成伪造（这是 BD4 接线必须一起改
       的一处；没有接收端时回退常量，与粘贴兜底同口径）。

    ⚠️ 地址**没有显式端口**时按「本次登录声明的端口」处理（用户手改地址栏的场景），
    显式给了别的端口才判失败 —— 那是别的程序的回调，不可能是本次登录的回跳。
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    if "?" not in text and "=" in text:
        text = "?" + text
    split = urlsplit(text if "://" in text else f"http://127.0.0.1{text}")
    path = split.path or ""
    if path != const.CALLBACK_PATH:
        return f"回跳路径不是 {const.CALLBACK_PATH}（实际 {path or '（空）'}）"
    if (split.hostname or "") not in const.CALLBACK_HOSTS:
        return f"回跳主机不是回环地址（实际 {split.hostname or '（空）'}）"
    try:
        port = split.port
    except ValueError:
        return f"回跳端口非法（{text[:60]}）"
    if port is not None and port != declared_port:
        return (f"回跳端口不是本次登录声明的端口 {declared_port}（实际 {port}；"
                f"本产品首选 {const.CALLBACK_PORT}，该端口被其它程序占用时接收端回退随机端口）")
    return ""


def fix_nickname_mojibake(raw: str, uid: str) -> str:
    """修复回调 `userInfo.ScreenName` 的**双重编码乱码**（`trae-oauth.ts:216-232`）。

    实测昵称形如 `Óû§8847309959`（UTF-8 字节被按 latin-1 解读一次）→ 回转修复；
    修不动且**不含任何 CJK 字符**时回退「用户+uid 末 4 位」（不把乱码写进凭据）。
    """
    if not raw:
        return raw
    try:
        fixed = raw.encode("latin-1").decode("utf-8")
        if fixed and "\ufffd" not in fixed and all(ord(ch) >= 32 for ch in fixed):
            return fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    if not re.search(r"[\u4e00-\u9fff]", raw):
        return f"用户{uid[-4:]}"
    return raw


def parse_callback(params: dict) -> CallbackParse:
    """解析回跳参数（`trae-oauth.ts:273-345` 的 `parseTraeCallbackDetailed`）。

    ⚠️ 回调**没有** `?code=`（老流程直传 token）：真实形态
    `…/authorize?refreshToken=…&userInfo={…}&userJwt={…}`（`trae-oauth.ts:239-243`）。
    但「带 code」的 PKCE 回调**不是无效回调**（`trae-oauth.ts:249-259`）→ 单独报
    「上游走了 PKCE 流程，本实现暂不支持」，而不是含糊地说「缺少 refreshToken」。
    """
    table = callback_params(params)
    if not table:
        return CallbackParse(ok=False, reason="没有可解析的回跳参数（请粘贴浏览器地址栏里的整串地址）")
    user_info = _json_param(table.get("userInfo") or "")
    user_jwt = _json_param(table.get("userJwt") or "")
    refresh_token = table.get("refreshToken") or ""
    uid = read_str(user_info, "UserID")
    nickname_raw = read_str(user_info, "ScreenName")
    enterprise_id = read_str(user_info, "TenantID")
    jwt_token = read_str(user_jwt, "Token")
    if not refresh_token:
        refresh_token = read_str(user_jwt, "RefreshToken")
    auth_code_info = _json_param(table.get("authCodeInfo") or "")
    auth_code = next((candidate.strip() for candidate in (
        table.get("code") or "",
        table.get("authCode") or "",
        read_str(auth_code_info, "code"),
        read_str(auth_code_info, "authCode"),
        table.get("authCodeInfo") or "",
    ) if candidate.strip()), "")
    info = CallbackInfo(
        refresh_token=refresh_token,
        access_token=jwt_token if not refresh_token else "",
        uid=uid,
        nickname=fix_nickname_mojibake(nickname_raw, uid),
        enterprise_id=enterprise_id,
        auth_code=auth_code,
        login_trace_id=table.get("login_trace_id") or "",
        machine_id=table.get("machine_id") or table.get("x_machine_id") or "",
        device_id=table.get("device_id") or table.get("x_device_id") or "",
    )
    if not info.refresh_token and not info.access_token:
        if auth_code:
            return CallbackParse(
                ok=False, auth_code_flow=True,
                reason="上游返回了 PKCE 授权码（code/authCodeInfo），本实现暂不支持该流程；"
                       "请确认 TRAE 授权页是否已切换到新流程")
        return CallbackParse(ok=False, reason="回调未携带 refreshToken / userJwt.Token / code")
    return CallbackParse(ok=True, info=info)


def display_nickname(phone: str, email: str, nickname: str, uid: str, fallback: str) -> str:
    """展示名的取值顺序：手机号 → 邮箱 → ScreenName → uid（`trae.ts:569-582`）。

    ## 为什么不能直接用 ScreenName（真实缺陷，用户报障 2026-09-27）

    `ScreenName` 是字节 passport **按 uid 自动生成的默认名**（`用户` + uid 片段，
    实测 `用户26815487395` 这种），多账号一屏列出来无法区分；`GetUserInfo` 下发的
    **脱敏**手机号 `130******00` 末两位互异，足以消歧（`trae.ts:539-568`）。
    手机号/邮箱都是脱敏形态，照原样展示，**不要试图还原**。
    """
    for candidate in (phone, email, nickname, uid):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return fallback


# ── ExchangeToken / GetUserInfo 响应解析（`trae.ts:435-492`）───────────

@dataclass(frozen=True)
class ExchangeResult:
    """ExchangeToken 的 `Result` 部分（`trae.ts:419-428`）。"""

    access_token: str = ""
    refresh_token: str = ""
    #: 绝对值过期时刻（原始形态：毫秒 / 秒两种都可能，`trae.ts:512-517` 归一化）。
    token_expire_at: float = 0.0
    #: 相对过期秒数。
    token_expire_duration: float = 0.0
    refresh_expire_at: float = 0.0


def parse_exchange(body: Any) -> ExchangeResult | None:
    """解析 ExchangeToken 响应（`trae.ts:435-449`）：`{Result: {Token, RefreshToken, …}}`。"""
    if not isinstance(body, dict):
        return None
    result = body.get("Result") if isinstance(body.get("Result"), dict) else body.get("result")
    if not isinstance(result, dict):
        return None
    access_token = (read_str(result, "Token") or read_str(result, "token")
                    or read_str(result, "accessToken"))
    if not access_token:
        return None
    return ExchangeResult(
        access_token=access_token,
        refresh_token=read_str(result, "RefreshToken") or read_str(result, "refreshToken"),
        token_expire_at=read_num(result, "TokenExpireAt", "tokenExpireAt") or 0.0,
        token_expire_duration=(read_num(result, "TokenExpireDuration",
                                        "tokenExpireDuration") or 0.0),
        refresh_expire_at=read_num(result, "RefreshExpireAt", "refreshExpireAt") or 0.0,
    )


@dataclass(frozen=True)
class UserInfoResult:
    """GetUserInfo 的 `Result` 部分（`trae.ts:452-468`）。"""

    uid: str = ""
    screen_name: str = ""
    enterprise_id: str = ""
    #: 脱敏手机号（`NonPlainTextMobile`）；短信登录才有值。
    phone: str = ""
    #: 脱敏邮箱（`NonPlainTextEmail`）；短信登录实测为空。
    email: str = ""


def parse_user_info(body: Any) -> UserInfoResult | None:
    """解析 GetUserInfo 响应（`trae.ts:477-492`）：uid 取不到 → `None`。"""
    if not isinstance(body, dict):
        return None
    result = body.get("Result") if isinstance(body.get("Result"), dict) else body.get("result")
    if not isinstance(result, dict):
        return None
    uid = read_str(result, "UserID") or read_str(result, "userId") or read_str(result, "uid")
    if not uid:
        return None
    return UserInfoResult(
        uid=uid,
        screen_name=read_str(result, "ScreenName", "screenName") or uid,
        enterprise_id=read_str(result, "EnterpriseID", "enterpriseId"),
        # ⚠️ 字段名是 **NonPlainTextMobile / NonPlainTextEmail**（不是 Mobile/Phone/Email）
        # —— GetUserInfo 只下发这两个脱敏形态（`trae.ts:487-490`）。
        phone=read_str(result, "NonPlainTextMobile", "nonPlainTextMobile"),
        email=read_str(result, "NonPlainTextEmail", "nonPlainTextEmail"),
    )


# ── 过期时刻归一（`trae.ts:504-537` / `:614-637`）──────────────────────

def expires_at_ms(exchange: ExchangeResult, access_token: str, *,
                  now_ms: int) -> str:
    """归一化 `expires_at`（**毫秒字符串**，照抄 `trae.ts:510-524`）。

    顺序：① `TokenExpireAt` > 1e12 视为毫秒直接用；② > 0 视为秒 → ×1000；
    ③ `TokenExpireDuration`（相对秒）→ `now + duration×1000`；④ 都拿不到 → 从
    `access_token`（JWT）的 `exp` 兜底；⑤ 再拿不到 → 空串（不编造过期时刻）。
    """
    if exchange.token_expire_at > 1e12:
        return str(int(exchange.token_expire_at))
    if exchange.token_expire_at > 0:
        return str(int(exchange.token_expire_at * 1000))
    if exchange.token_expire_duration > 0:
        return str(int(now_ms + exchange.token_expire_duration * 1000))
    exp = jwt_expires_at_ms(access_token)
    return "" if exp is None else str(exp)


def jwt_expires_at_ms(token: str) -> int | None:
    """从 JWT 的 `exp` 取毫秒时间戳（`buddy.ts::jwtExpiresAtMs` 同口径）。

    只做 base64url 解载荷，**不验签**（签名验证是上游的事；这里只读过期时刻）。
    解析不动 → `None`（不编造）。
    """
    parts = str(token or "").split(".")
    if len(parts) < 2:
        return None
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload + padding)
        claims = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(claims, dict):
        return None
    exp = claims.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return None
    return int(exp * 1000)


# ── 模型目录解析（`trae.ts:1056-1273`）──────────────────────────────────

@dataclass(frozen=True)
class ActivityDiscount:
    """当前**确实生效**的活动折扣（`readActivityDiscount` 的返回形态，`trae.ts:1002-1042`）。"""

    #: 折扣前倍率（`activity_discount.data.current.before_consumption_rate`）。
    original_rate: float
    #: 活动截止时间（Unix **秒**）；`None` = 该活动类型不带截止（如 `subsidy` 型）。
    ends_at_sec: float | None = None


#: 活动折扣的截止时间来源（`trae.ts:1031-1038`）：取 `data` 下第一个带 `end_at` 的子对象
#: （实测仅 `limited` 型带；`subsidy` / `off_peak` 型没有）。
_END_AT_KEYS = ("end_at", "endAt")


def read_consumption_rate(entry: dict) -> float | None:
    """解析 `display_contact_config` 里的**消耗倍率**（`readConsumptionRate`，`trae.ts:968-981`）。

    🔴 `display_contact_config` 是**一个 JSON 字符串**（不是对象），必须二次解析 ——
       直接读 `entry.display_contact_config.consumption_rate` 永远得到 undefined
       （`trae.ts:953-957` 的真实坑位）。

    三条判据（缺一不可，照抄）：
    1. `consumption_rate.enable !== false` —— 上游显式关闭时**视为无倍率**（不是当成 0）；
    2. `data.rate` 是**有限非负数**（实测形态是裸数字 `0.08`，不是字符串 `"x0.08"`）；
    3. ⚠️ **`rate: 0` 是合法值**（免费）—— 不能用 `> 0` 过滤（`trae.ts:962-964`）。

    解析失败一律 `None`（**不编造倍率**：宁可只显示模型名）。
    """
    config = _display_contact_config(entry)
    if config is None:
        return None
    rate = config.get("consumption_rate", config.get("ConsumptionRate"))
    if not isinstance(rate, dict):
        return None
    if read_bool(rate, "enable") is False:
        return None
    data = rate.get("data", rate.get("Data"))
    if not isinstance(data, dict):
        return None
    value = read_num(data, "rate")
    return value if value is not None and value >= 0 else None


def read_activity_discount(entry: dict, now_sec: float | None = None) -> ActivityDiscount | None:
    """解析 `activity_discount` —— 只在**当前确实生效**时返回折扣（`trae.ts:1002-1042`）。

    🔴 不能只看 `enable: true`：实测 `enable` 为 `true` 但**当前并没有折扣** —— `off_peak`
       型形如 `{type:"none", before:0.13, after:0.13, discount:100}`（`discount: 100` =
       「无折扣」，百分比制，`before === after`）。照显会得到 `x0.13→x0.13`，让用户以为
       有活动（`trae.ts:986-992`）。

    四条判据：
    1. `activity_discount.enable !== false`；
    2. `data.current` 存在，且 `discount_type` **不是 `"none"`**（空值同判）；
    3. `before_consumption_rate` 是有限正数，且**严格大于** `consumption_rate`（真降价）；
    4. `end_at`（Unix 秒，仅 `limited` 型带）已过 → 整个折扣**视为不存在**
       （否则用户按折扣价预期、实际被按原价计费）。

    `now_sec` 镜像 DSH 的 `nowSec = Math.floor(Date.now()/1000)` 注入缝（`trae.ts:1003-1004`）。
    """
    config = _display_contact_config(entry)
    if config is None:
        return None
    discount = config.get("activity_discount", config.get("ActivityDiscount"))
    if not isinstance(discount, dict):
        return None
    if read_bool(discount, "enable") is False:
        return None
    data = discount.get("data", discount.get("Data"))
    if not isinstance(data, dict):
        return None
    current = data.get("current", data.get("Current"))
    if not isinstance(current, dict):
        return None
    kind = (read_str(current, "discount_type") or read_str(current, "discountType")).strip().lower()
    if not kind or kind == "none":
        return None
    before = read_num(current, "before_consumption_rate", "beforeConsumptionRate")
    after = read_num(current, "consumption_rate", "consumptionRate")
    if before is None or before <= 0:
        return None
    if after is not None and before <= after:
        return None
    moment = time.time() if now_sec is None else now_sec
    ends_at: float | None = None
    for value in data.values():
        if not isinstance(value, dict):
            continue
        end = read_num(value, *_END_AT_KEYS)
        if end is not None and end > 0:
            ends_at = end
            break
    if ends_at is not None and ends_at <= moment:
        return None    # 已过期的活动不再是「当前生效」
    return ActivityDiscount(original_rate=before, ends_at_sec=ends_at)


def _display_contact_config(entry: dict) -> dict | None:
    """`display_contact_config`（**JSON 字符串**）→ 对象；非对象/非法 JSON → `None`。

    大小写双兼容（`display_contact_config` / `DisplayContactConfig`），照抄
    `trae.ts:968-975` 的 `parseJsonObject` 口径：数组与标量都不算对象。
    """
    raw = entry.get("display_contact_config", entry.get("DisplayContactConfig"))
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


@dataclass(frozen=True)
class RemoteEntry:
    """`config_info_list` 里的一条目录条目（`TraeRemoteModel` 的必要子集，`trae.ts:642-798`）。"""

    id: str
    name: str
    #: 提供该模型的通道（`function`）；同一 id 在不同通道的配置**可以不同**。
    channel: str = ""
    #: `context_window_tokens.dev`（默认可用档；`max` 只在 Max 模式下生效，**不混用**）。
    context_window: int | None = None
    #: `model_detail_list[__dev].max_tokens`。
    max_output: int | None = None
    #: `display_config.multimodal` —— 逐模型的图片输入能力（`trae.ts:738-764` 的实测结论）。
    multimodal: bool | None = None
    #: `reasoning_effort_config.options`（**wire 值**，与 function 同源，`trae.ts:1175-1177`）。
    reasoning_options: tuple[str, ...] = ()
    #: `reasoning_effort_config.support_thinking`。
    support_thinking: bool | None = None
    #: `display_config.is_custom_model`：需用户在 IDE 内自行绑定供应商 → 本侧必然调不通。
    is_custom: bool | None = None
    #: `is_invisible_to_user`：官方隐藏条目（可调用但官方 picker 不列）。
    is_hidden: bool | None = None
    #: `config_switch`：上游是否启用该条目。
    is_enabled: bool | None = None
    #: `usage`：只有 `chat_completion` 才适合作为对话模型。
    usage: str = ""
    #: 消耗倍率（`display_contact_config.consumption_rate.data.rate`，裸数字；0=免费）。
    #: 2026-10-01 补：此前被整个丢弃（`ModelInfo` 无承载字段）。
    rate: float | None = None
    #: 活动折扣的**原价**（仅当前确实生效时；`trae.ts:1002-1042` 的三条判据）。
    original_rate: float | None = None


def _context_window_of(entry: dict) -> int | None:
    """`context_window_tokens.dev`（缺失回退 `max`，`trae.ts:850-859`）。

    ⚠️ 取 `dev` 而非 `max` 是刻意的（`trae.ts:645-651`）：`max` 需开 Max 模式才可用，
    采信它会让上层以为有 1M 窗口、实际请求被上游按 200K 拒。
    """
    raw = entry.get("context_window_tokens", entry.get("ContextWindowTokens"))
    if not isinstance(raw, dict):
        return None
    value = (read_num(raw, "dev", "Dev") or read_num(raw, "max", "Max"))
    return int(value) if value is not None and value > 0 else None


def _max_tokens_of(entry: dict, suffix: str = "__dev") -> int | None:
    """`model_detail_list` 里 `model_name` 以 `suffix` 结尾那条的 `max_tokens`（`trae.ts:885-899`）。"""
    raw = entry.get("model_detail_list", entry.get("ModelDetailList"))
    if not isinstance(raw, list) or not raw:
        return None
    details = [item for item in raw if isinstance(item, dict)]
    chosen = next((item for item in details
                   if read_str(item, "model_name").endswith(suffix)), None)
    if chosen is None:
        chosen = details[0] if details else None
    if chosen is None:
        return None
    value = read_num(chosen, "max_tokens", "MaxTokens")
    return int(value) if value is not None and value > 0 else None


def _reasoning_of(entry: dict) -> tuple[tuple[str, ...], bool | None]:
    """`reasoning_effort_config` → `(options, support_thinking)`（`trae.ts:911-946`）。

    `options` 兼容字符串数组（实测形态）与对象数组（`{level}/…` 防御性兼容）；
    一个字段都没有 → 空 options（调用方据此**不声明**推理能力）。
    """
    raw = entry.get("reasoning_effort_config", entry.get("ReasoningEffortConfig"))
    if not isinstance(raw, dict):
        return (), None
    options: list[str] = []
    raw_options = raw.get("options", raw.get("Options"))
    if isinstance(raw_options, list):
        for item in raw_options:
            if isinstance(item, str) and item.strip():
                options.append(item.strip())
            elif isinstance(item, dict):
                wire = (read_str(item, "openclawLevel") or read_str(item, "level")
                        or read_str(item, "Level"))
                if wire.strip():
                    options.append(wire.strip())
    support = read_bool(raw, "support_thinking")
    if support is None:
        support = read_bool(raw, "SupportThinking")
    return tuple(options), support


def parse_entry(entry: dict, channel: str = "", now_sec: float | None = None) -> RemoteEntry | None:
    """解析单条 `config_info_list` 条目（`trae.ts:1056-1122` 的 `parseTraeConfigEntry`）。

    所有标志「上游没说」都保持 `None`（**不填 False**）：过滤方只挡明确命中者
    （`trae.ts:1069`：宁可多留一个模型，也不要因缺字段误删整批）。

    `now_sec`：活动折扣时效判定的注入时刻（Unix 秒；缺省 = 当下）—— 折扣「当前是否
    生效」必须可复现（`trae.ts:1002-1004` 的同一注入缝）。
    """
    entry_id = read_str(entry, "config_name", "ConfigName")
    if not entry_id:
        return None
    display = entry.get("display_config", entry.get("DisplayConfig"))
    display = display if isinstance(display, dict) else None
    options, support = _reasoning_of(entry)
    is_custom = multimodal = None
    if display is not None:
        is_custom = read_bool(display, "is_custom_model")
        if is_custom is None:
            is_custom = read_bool(display, "IsCustomModel")
        multimodal = read_bool(display, "multimodal")
        if multimodal is None:
            multimodal = read_bool(display, "Multimodal")
    is_hidden = read_bool(entry, "is_invisible_to_user")
    if is_hidden is None:
        is_hidden = read_bool(entry, "IsInvisibleToUser")
    is_enabled = read_bool(entry, "config_switch")
    if is_enabled is None:
        is_enabled = read_bool(entry, "ConfigSwitch")
    # 计费（`display_contact_config` 二次解析，`trae.ts:1099-1101`）：倍率 + 当前生效折扣。
    discount = read_activity_discount(entry, now_sec)
    return RemoteEntry(
        id=entry_id,
        name=(read_str(display, "display_name") if display is not None else "") or entry_id,
        channel=channel,
        context_window=_context_window_of(entry),
        max_output=_max_tokens_of(entry),
        multimodal=multimodal,
        reasoning_options=options,
        support_thinking=support,
        is_custom=is_custom,
        is_hidden=is_hidden,
        is_enabled=is_enabled,
        usage=read_str(entry, "usage", "Usage"),
        rate=read_consumption_rate(entry),
        original_rate=discount.original_rate if discount is not None else None,
    )


def declares_reasoning(entry: RemoteEntry) -> bool:
    """该条目**能否真正声明出思考档位**（`trae.ts:1258-1273` 的判据）。

    必须与消费侧（`/v1/models` 能力位）完全一致：配置存在 + 未显式
    `support_thinking: false` + `options` 非空 —— 只判「配置存在」会把
    `{support_thinking: false, options: []}` 也算成有档位。
    """
    if entry.support_thinking is False:
        return False
    return len(entry.reasoning_options) > 0


def parse_batch_models(body: Any, *,
                       channel_priority: tuple[str, ...] = const.CHANNELS,
                       now_sec: float | None = None) -> list[RemoteEntry]:
    """解析 `batch_get_detail_param` 响应（`trae.ts:1191-1256` 的移植）。

    响应形如 `{function_configs: [{function, config_info_list: […]}, …]}`：**每个通道
    各自一套目录**，同一条目在不同通道的配置可以不同（可用性/思考档位/1M 声明）。

    三条**硬性过滤**（缺一不可，`trae.ts:1220-1231`）：`usage` 非 `chat_completion`、
    `config_switch === false`、`is_invisible_to_user === true`。

    同 id 多通道条目的**择优三规则**（`trae.ts:1160-1170`，修正 issue IKI7WT/IKILR7）：
    ① 空档位不得覆盖有档位（原「无条件后覆盖前」会让信息更全的条目被覆盖成空档位）；
    ② 两侧都声明档位时按 `channel_priority` 取更靠前者（档位必须与 `function` 同源）；
    ③ 其余情形保持既有「后覆盖前」语义。

    `now_sec` 透传给 `parse_entry`（活动折扣时效判定的注入缝）。
    """
    if not isinstance(body, dict):
        return []
    groups = body.get("function_configs", body.get("FunctionConfigs"))
    if not isinstance(groups, list):
        return []

    def rank_of(channel: str) -> int:
        return channel_priority.index(channel) if channel in channel_priority else len(channel_priority)

    by_id: dict[str, RemoteEntry] = {}
    chosen_rank: dict[str, int] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        channel = read_str(group, "function", "Function")
        items = group.get("config_info_list", group.get("ConfigInfoList"))
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            model = parse_entry(item, channel, now_sec)
            if model is None:
                continue
            if model.usage and model.usage != "chat_completion":
                continue
            if model.is_enabled is False:
                continue
            if model.is_hidden is True:
                continue
            incumbent = by_id.get(model.id)
            if incumbent is None:
                by_id[model.id] = model
                chosen_rank[model.id] = rank_of(model.channel)
                continue
            incumbent_has = declares_reasoning(incumbent)
            candidate_has = declares_reasoning(model)
            if incumbent_has and not candidate_has:
                continue                       # 规则 ①
            if incumbent_has and candidate_has:
                current = chosen_rank.get(model.id, len(channel_priority))
                if current != len(channel_priority) and rank_of(model.channel) >= current:
                    continue                   # 规则 ②
            by_id[model.id] = model            # 规则 ③（含「都无档位」）
            chosen_rank[model.id] = rank_of(model.channel)
    return list(by_id.values())


#: 模型目录请求体（逐条照抄 `trae-auth.ts:673-690`）。
def models_body() -> dict:
    """目录请求体（`trae-auth.ts:673-690`）：22 个 function + 一组固定开关。"""
    return {
        "functions": list(const.MODELS_FUNCTIONS),
        "agent_type": "",
        "current_config_info": {"config_name": "", "is_custom_model": False},
        "mode_type": 0,
        "access_type": 0,
        "ab_force_vids": "",
        "ab_autotest_advanced_mode": 0,
        "show_custom_model": True,
    }


# ════════════════════ 出站（模型转发，M6-5）════════════════════════════
#
# 取证：`trae.ts:1511-1832`（`transformToSOLOBody` / `parseTraeSSELine` /
# `buildOpenAIChunk`）；消费侧跨行成帧 = `trae-adapter.ts:1223-1523`。


def _solo_message(msg: dict) -> dict:
    """单条消息的 SOLO 塑形（`transformSOLOMessage`，`trae.ts:1566-1605`）。

    ① assistant 的 `tool_calls[].function` → `function_call`（无可用 `name` 的整条剔除）；
    ② `content` 字符串 → `[{type:'text',text:...}]`（**数组原样透传**，兼容多模态）；
    ③ 其余字段原样（逐字段搬运，不把调用方的内部字段展开进去）。
    """
    result = dict(msg)
    if result.get("role") == "assistant" and isinstance(result.get("tool_calls"), list):
        kept: list[dict] = []
        for tc in result["tool_calls"]:
            if not isinstance(tc, dict):
                continue
            t = dict(tc)
            fn = t.get("function")
            if isinstance(fn, dict):
                t["function_call"] = dict(fn)
                t.pop("function", None)
            fc = t.get("function_call")
            name = fc.get("name") if isinstance(fc, dict) else None
            if not (isinstance(name, str) and name.strip()):
                continue
            kept.append(t)
        if kept:
            result["tool_calls"] = kept
        else:
            result.pop("tool_calls", None)
    content = result.get("content")
    if isinstance(content, str):
        result["content"] = [{"type": "text", "text": content}]
    # content 为 None / 数组 → 原样（纯 tool_calls 的 assistant 消息跳过 content）
    return result


def _normalize_tool_choice(body: dict) -> None:
    """`tool_choice` 归一化（`normalizeToolChoice`，`trae.ts:1615-1663`）。

    - `"none"` / `{type:"none"}` → 删 `tool_choice` + 删 `tools`/`functions`；
    - `{type:"auto"|"required"}` → 字符串 `"auto"`/`"required"`；
    - `{type:"function",function:{name}}` → 字符串 `name`（缺 name 回 `"auto"`）；
    - 其余类型 → 删 `tool_choice`。
    """
    tc = body.get("tool_choice")
    if tc is None:
        return

    def suppress() -> None:
        body.pop("tools", None)
        body.pop("functions", None)

    if isinstance(tc, str):
        if tc.strip().lower() == "none":
            body.pop("tool_choice", None)
            suppress()
        return
    if isinstance(tc, dict):
        typ = str(tc.get("type") or "").strip().lower()
        if typ == "none":
            body.pop("tool_choice", None)
            suppress()
        elif typ in ("auto", "required"):
            body["tool_choice"] = typ
        elif typ == "function":
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            name = str(fn.get("name") or tc.get("name") or "").strip()
            body["tool_choice"] = name or "auto"
        else:
            body.pop("tool_choice", None)
        return
    body.pop("tool_choice", None)


def _normalize_tools(body: dict) -> None:
    """`tools[].function.parameters` object → JSON 字符串（`normalizeTools`，`trae.ts:1672-1693`）。

    SOLO 上游要求 `parameters` 是 **string**；无 `function` 的条目剔除；全空则删 `tools`。
    """
    raw = body.get("tools")
    if not isinstance(raw, list) or not raw:
        return
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        fn = item.get("function")
        if not isinstance(fn, dict):
            continue
        t = dict(item)
        fn_copy = dict(fn)
        params = fn_copy.get("parameters")
        if isinstance(params, dict):
            fn_copy["parameters"] = json.dumps(params, ensure_ascii=False)
        t["function"] = fn_copy
        out.append(t)
    if out:
        body["tools"] = out
    else:
        body.pop("tools", None)


def solo_body(body: dict, vendor_model: str, channel: str = "") -> dict:
    """OpenAI Chat 请求体 → **SOLO 请求体**（`transformToSOLOBody`，`trae.ts:1529-1561`）。

    逐条对齐 Go 端 `payload.go:PrepareBody` 的改写规则（`trae.ts:1514-1527`）：
    ① `messages[].content` 字符串 → `[{type:"text",…}]`；② `stream` **强制 true**
    （SOLO 上游只发 SSE，非流式由本层聚合）；③ `model` → `config_name` + `model`
    **双字段**（`__` 后缀先消除，`trae.ts:1549`）；④ `function` = **该模型所属通道**
    （调用方经 `models.channel_for` 取，缺省回退 `const.FUNCTION`）；⑤ `tool_choice`
    归一化；⑥ assistant `tool_calls[].function` → `function_call`；⑦ `tools[].function
    .parameters` object → JSON 字符串。

    ⚠️ **不修改入参**（调度器同一次请求会重试多个资源、复用同一个 `ir.body`）——
    逐层构造新对象（消息与工具都做了浅拷贝改写）。
    """
    out = dict(body)
    out["stream"] = True
    out["function"] = channel or const.FUNCTION

    msgs = out.get("messages")
    if isinstance(msgs, list):
        out["messages"] = [_solo_message(m) for m in msgs if isinstance(m, dict)]

    model = str(out.get("model") or "")
    base_model = model.split("__", 1)[0] if "__" in model else model
    config_name = base_model or const.TRAE_DEFAULT_MODEL
    out["config_name"] = config_name
    out["model"] = config_name

    _normalize_tool_choice(out)
    _normalize_tools(out)
    return out


# ── SOLO SSE 成帧（跨行 `event:` + `data:`；`trae-adapter.ts:1280-1523`）──

@dataclass
class SoloEvent:
    """解析后的一条 SOLO 事件（`TraeSSEEvent`，`trae.ts:1707-1717`）。"""

    event: str
    response: str = ""
    reasoning: str = ""
    tool_calls: list | None = None
    usage: dict | None = None
    finish_reason: str = ""
    code: int | None = None
    message: str = ""


def _normalize_solo_tool_calls(calls: list) -> list:
    """SOLO tool_calls 字段归一（`function_call` → `function`；清 SOLO 专属字段）。

    对齐 `normalizeTraeToolCalls`（`trae.ts:1768-1785`）：删 `function.namespace`
    与 `function.partial_arguments`（那是 SOLO 增量拼接用的内部字段）。
    """
    out: list = []
    for call in calls:
        if not isinstance(call, dict):
            out.append(call)
            continue
        c = dict(call)
        if isinstance(c.get("function_call"), dict):
            c["function"] = dict(c["function_call"])
            c.pop("function_call", None)
        fn = c.get("function")
        if isinstance(fn, dict):
            fn = dict(fn)
            fn.pop("namespace", None)
            fn.pop("partial_arguments", None)
            c["function"] = fn
        out.append(c)
    return out


def parse_solo_event(event: str, data_line: str) -> SoloEvent:
    """解析一条 SOLO 事件（`parseTraeSSELine`，`trae.ts:1727-1761`）。

    数据行不是 JSON → 只保留事件名（`trae.ts:1734-1736` 同口径：不因解析失败丢事件名）。
    """
    ev = SoloEvent(event=event.strip())
    if not data_line:
        return ev
    try:
        raw = json.loads(data_line)
    except (json.JSONDecodeError, ValueError):
        return ev
    if not isinstance(raw, dict):
        return ev
    name = ev.event
    if name == "output":
        if isinstance(raw.get("response"), str):
            ev.response = raw["response"]
        if isinstance(raw.get("reasoning_content"), str):
            ev.reasoning = raw["reasoning_content"]
        if isinstance(raw.get("tool_calls"), list):
            ev.tool_calls = _normalize_solo_tool_calls(raw["tool_calls"])
    elif name == "token_usage":
        ev.usage = raw
    elif name == "done":
        if isinstance(raw.get("finish_reason"), str):
            ev.finish_reason = raw["finish_reason"]
    elif name == "error":
        code = raw.get("code")
        if isinstance(code, int) and not isinstance(code, bool):
            ev.code = code
        if isinstance(raw.get("message"), str):
            ev.message = raw["message"]
    return ev


def openai_chunk(delta: dict, *, finish_reason: str | None = None,
                 usage: dict | None = None, chunk_id: str = "chatcmpl-trae",
                 model: str = "", created: int | None = None) -> dict:
    """构造一个 OpenAI `chat.completion.chunk`（`buildOpenAIChunk`，`trae.ts:1792-1823`）。

    形状与 `openai_out` 收到的供应商 chunk 逐字一致（消费方 = 既有 SSE 出口）：
    `choices[0].delta` + 可选 `finish_reason` / `usage`。
    """
    choice: dict[str, Any] = {"index": 0, "delta": delta}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    chunk: dict[str, Any] = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created if created is not None else int(time.time()),
        "model": model,
        "choices": [choice],
    }
    if usage is not None:
        chunk["usage"] = usage
    return chunk
