"""LobsterAI 协议层：信封 / 身份载荷 / 凭据组装 / **唯一网络出入口**（照抄 DSH 取证）。

🔴 三件事在这一个模块里定死（其余模块只做编排，不再各写一份）：

  ① **统一信封** `{code, msg, data}`（`src/lobsterai.ts:233-252`）——`code !== 0` 即失败，
     且 `data` 必须是**对象**（上游在凭据失效时倾向于返回 `code:0` + `data:null`，
     只看 code 会把这种失败当成成功，随后崩在更远的地方）；
  ② **身份载荷 keyfrom**（`lobsterai.ts:305-341`）：`firstKeyfrom`/`latestKeyfrom`/`version`
     +（非空才带）`uuid`/`userId`。⚠️ 两个 keyfrom 发的是**凭据里存储的原值**，
     不取当前时刻（Go `KeyfromBody()` 读的就是 `a.LatestKeyfrom`，而 `RefreshToken`
     从不更新它 → DSH 照做，`lobsterai.ts:311-315`）；
  ③ **网络出入口** `fetch_json()`（§22.8-1：显式超时、禁止阻塞事件循环）。单测把
     `make_client` 换成 `MockTransport` 即可注入假上游，**不需要在每个调用点留后门**。

⚠️ 凭据的字段名（`access_token` / `refresh_token` / `expires_at` / `uid` / `user_id` /
   `nickname` / `uuid` / `first_keyfrom` / `latest_keyfrom`）与 DSH **逐字一致**
   （`lobsterai.ts:79-114`、`buildLobsteraiCredential` `:423-447`）——名字一致才能把
   上游字段与 DSH 的排查经验（含 U 项漂移清单）直接对照。
"""

from __future__ import annotations

from model_gateway.upstream._text import strip_control

import math

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

from model_gateway.accounts import net, store
from model_gateway.upstream.lobsterai import const

#: 版本号合法形态（`sigin.py:16-18` 的 `version_key`）：点分数字主干 + 可选预发布后缀。
VERSION_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:-[0-9A-Za-z.-]+)?$")

#: 响应文本保留长度上限（关键词分类只需开头；防止把整页 HTML 挂在内存里）。
_TEXT_KEEP = 2000


class ProtocolError(RuntimeError):
    """协议层**可重试**失败（网络抖动 / 非 JSON / 非终态业务码）。

    与 `NotRefreshable`（终态）严格分开：前者交给调用方决定重试或报错，
    后者只能重新登录（`src/lobsterai-errors.ts:205-215` 的终态口径）。
    """


# ---------- JSON 读取（兼容后端把数字返回成字符串） ----------

def read_str(source: dict, key: str) -> str:
    """安全读字符串（数字按字符串收，`lobsterai.ts:205-210`）；控制字符剥离同 buddy
    口径（R2a-F-4，`upstream/_text.py` 一份实现）——上游多行文本破坏落盘 JSON。"""
    value = source.get(key) if isinstance(source, dict) else None
    if isinstance(value, str):
        return strip_control(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def read_num(source: dict, key: str) -> float | None:
    """安全读数字（字符串形态的数字也收，`lobsterai.ts:213-218`）；读不到 → `None`。"""
    value = source.get(key) if isinstance(source, dict) else None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # R2a-F-1（2026-10-06）：NaN/Infinity 在读入口过滤（同 trae read_num）——
        # json.loads 会照收 NaN/Infinity 字面量，下游 int(nan) 抛未捕获 ValueError
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str) and re.fullmatch(r"-?\d+(\.\d+)?", value.strip()):
        return float(value)
    return None


def read_bool(source: dict, key: str) -> bool:
    """严格布尔读取（只有真 `true` 才算，`lobsterai-credits.ts:137-139`）。"""
    return (source.get(key) if isinstance(source, dict) else None) is True


def read_str_list(source: dict, key: str) -> list[str]:
    """读字符串数组（非数组/含非字符串项 → 空表，`lobsterai-credits.ts:150-154`）。"""
    value = source.get(key) if isinstance(source, dict) else None
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def is_session_dead(text: str) -> bool:
    """响应体是否命中**会话终止标记**（`src/lobsterai-errors.ts:73-75` 的标记表）。"""
    return any(marker in text for marker in const.SESSION_DEAD_MARKERS)


def _auth_hint(result: HttpResult) -> str:
    """HTTP 401/403 的凭据失效提示（文案照抄 `lobsterai-credits.ts:127-131`）；否则空串。"""
    if result.status in (401, 403):
        return f"凭据已失效（HTTP {result.status}），请重新登录该账号"
    return ""


def non_json_reason(result: HttpResult) -> str:
    """「响应不是 JSON」的可读原因（`lobsterai-credits.ts:127-134` 逐条照抄）。

    凭据失效时服务端可能返回 HTML 错误页：401/403 直接给出「请重新登录」，
    其余带状态码 + 响应片段（截 80 字、压平空白），便于用户与排查者对照。
    """
    hint = _auth_hint(result)
    if hint:
        return hint
    snippet = " ".join(result.text.split())[:80]
    return f"服务端返回了非 JSON 响应（HTTP {result.status}）：{snippet}"


def envelope_failure(result: HttpResult, envelope: Envelope, label: str) -> str:
    """信封失败的可读原因（**只看业务码不看 HTTP 状态是不够的**）。

    401/403 时优先说「凭据已失效」（与 `non_json_reason` 同一句文案，两处不得分叉），
    否则回落到「`{label}`：服务端 msg」。用户看到的失败原因要能直接指到动作
    （重新登录 / 等会儿再试），而不是一句 `unauthorized`。
    """
    hint = _auth_hint(result)
    return f"{hint}：{envelope.message}" if hint else f"{label}：{envelope.message}"


def parse_version(raw: object) -> str:
    """校验并归一化日期式版本号（`lobsterai.ts:588-593` = `sigin.py:16-18` 的 `version_key`）。

    要**校验**而不是直接采信：版本号是签到接口的必填 query 参数，上游返回 `null` /
    空串 / HTML 时把它拼进 URL 只会让签到以更费解的方式失败。格式非法 → 空串。
    """
    if not isinstance(raw, str):
        return ""
    text = raw.strip()
    return text if VERSION_RE.fullmatch(text) else ""


# ---------- 统一信封 ----------

@dataclass(frozen=True)
class Envelope:
    """`{code, msg, data}` 的解析结果（`ok=False` 时 `message` 一定是可读原因）。"""

    ok: bool
    data: dict = field(default_factory=dict)
    code: int = -1
    message: str = ""


def parse_envelope(body: object) -> Envelope:
    """解析统一信封（三条判定照抄 `lobsterai.ts:233-252`）。

    ① 响应体必须是对象；② `code` 必须为 0；③ `data` 必须是**对象**
    （第 ③ 条专门拦「凭据失效 → `code:0` + `data:null`」这种假成功）。
    """
    if not isinstance(body, dict):
        return Envelope(False, message="响应不是 JSON 对象")
    code_num = read_num(body, "code")
    code = int(code_num) if code_num is not None else -1
    message = read_str(body, "msg") or read_str(body, "message")
    if code != 0:
        return Envelope(False, code=code, message=message or f"code={code}")
    data = body.get("data")
    if not isinstance(data, dict):
        return Envelope(False, code=code,
                        message=message or "data 为空（accessToken 可能已失效）")
    return Envelope(True, data=data, code=code, message=message)


# ---------- 网络出入口 ----------

@dataclass(frozen=True)
class HttpResult:
    """一次请求的结果：`reachable` = 拿到了 HTTP 响应（**与凭据是否有效是两件事**）。"""

    reachable: bool
    status: int = 0
    body: object = None
    text: str = ""
    #: 传输层失败原因（timeout / connect error…），**保留原文**便于诊断
    error: str = ""


def make_client(*, timeout: float = const.REQUEST_TIMEOUT_S) -> httpx.AsyncClient:
    """构造带**显式超时**的客户端（§22.8-1；统一走 `accounts/net.py` 的工厂）。

    🔴 本函数是本产品**唯一的客户端构造点**：单测把它替换成
    `httpx.AsyncClient(transport=httpx.MockTransport(…))` 就能整体注入假上游（**无网络**）。
    """
    return net.make_client(timeout=timeout)


async def fetch_json(url: str, *, method: str = "GET", headers: dict | None = None,
                     body: dict | None = None) -> HttpResult:
    """发一次控制面请求并解析 JSON（**不用 `response.json()`**，照抄 DSH `requestJson`）。

    为什么先取文本再解析（`lobsterai-credits.ts:92-96`）：凭据失效时上游可能返回 HTML
    错误页，`json()` 抛出的 `Unexpected token '<' ...` 对用户毫无意义；先取文本才能给出
    带状态码的可读原因。传输层失败**原样保留**（timeout / connect error），不吞诊断。
    """
    client = make_client()
    try:
        try:
            response = await client.request(method, url, headers=headers or {}, json=body)
        except httpx.HTTPError as e:
            return HttpResult(reachable=False, error=f"{type(e).__name__}: {e}")
        text = response.text
        try:
            parsed: object = json.loads(text)
        except ValueError:
            parsed = None
        return HttpResult(reachable=True, status=response.status_code, body=parsed,
                          text=text[:_TEXT_KEEP])
    finally:
        await client.aclose()


# ---------- 请求头（三套，`lobsterai.ts:492-570`） ----------

def anonymous_headers() -> dict[str, str]:
    """无认证请求头（exchange / refresh 用；这两个端点**不要** `Authorization`）。"""
    return {"Accept": "application/json", "Content-Type": "application/json",
            "User-Agent": const.USER_AGENT}


def auth_headers(cred: dict, *, accept: str = "application/json") -> dict[str, str]:
    """带 Bearer 的基础头（**只有四个**，`lobsterai.ts:492-503`）。

    LobsterAI 不认 CodeBuddy 那套 `X-Domain` / `X-Product*` / `X-IDE-*` 归属头：
    带上不仅无用，还可能让服务端按错误的客户端形态归因。
    """
    return {"Authorization": f"Bearer {read_str(cred, 'access_token')}",
            "Accept": accept, "Content-Type": "application/json",
            "User-Agent": const.USER_AGENT}


def client_headers(cred: dict, client_version: str, *,
                   accept: str = "application/json") -> dict[str, str]:
    """基础头 + 两个 `X-LobsterAI-Client-*`（模型列表与对话端点必需，`lobsterai.ts:517-555`）。

    ⚠️ 这两个头**不是可有可无的元数据**：服务端按 `Capabilities` 声明的能力**过滤模型集合**
    （不带时 `kimi-k3` 不会返回，实测 25 vs 26 个）。
    """
    return {**auth_headers(cred, accept=accept),
            "X-LobsterAI-Client-Capabilities": const.CLIENT_CAPABILITIES,
            "X-LobsterAI-Client-Version": client_version}


# ---------- 身份载荷（keyfrom）与续期请求体 ----------

def keyfrom_body(cred: dict, client_version: str) -> dict:
    """keyfrom 身份载荷（`lobsterai.ts:305-321`，对应 Go `auth.go:37-50`）。

    `uuid` / `userId` **缺省时删键而不是写空串**（Go 的 `if a.Uuid != ""` 就是「有才带」，
    空串可能被服务端当成非法值）。
    """
    body: dict = {
        "firstKeyfrom": read_str(cred, "first_keyfrom"),
        # 用凭据里**存储的**值，不取当前时刻（见模块头 ②；Go 每次续期发的都是登录那一刻）。
        "latestKeyfrom": read_str(cred, "latest_keyfrom"),
        "version": client_version,
    }
    uuid = read_str(cred, "uuid")
    if uuid:
        body["uuid"] = uuid
    user_id = read_str(cred, "user_id")
    if user_id:
        body["userId"] = user_id
    return body


def keyfrom_query(cred: dict, client_version: str) -> dict[str, str]:
    """keyfrom 的 **query 形态**（`lobsterai.ts:302-312`）：去掉空值后用于模型列表。

    ⚠️ **不含 `refreshToken`**（`client.go:229-241` 只用 keyfrom 字段）：把 refreshToken
    放进 query 既是信息泄露（会进服务端访问日志），也不是该端点的预期输入。
    """
    return {key: str(value) for key, value in keyfrom_body(cred, client_version).items()
            if str(value)}


def refresh_body(cred: dict, client_version: str) -> dict:
    """续期请求体 = keyfrom 载荷 + `refreshToken`（`lobsterai.ts:333-341`）。"""
    return {**keyfrom_body(cred, client_version),
            "refreshToken": read_str(cred, "refresh_token")}


# ---------- 令牌载荷与凭据组装 ----------

@dataclass(frozen=True)
class TokenPayload:
    """exchange / refresh 响应的令牌部分（`lobsterai.ts:346-381`）。"""

    access_token: str
    refresh_token: str = ""
    #: 相对过期秒数；缺失时由 JWT `exp` 兜底
    expires_in: float | None = None
    #: `user.id`（账号池去重/排序的标识候选）
    user_id: str = ""
    #: 有道 yid（与 uid 不一定相同）
    yid: str = ""
    #: `user.userId`（账号 userId；refresh 请求体的 `userId` 取自这里）
    account_user_id: str = ""
    nickname: str = ""


def parse_token_payload(data: dict) -> TokenPayload:
    """解析 exchange / refresh 响应的令牌与用户信息（`lobsterai.ts:367-381`）。"""
    user = data.get("user")
    user = user if isinstance(user, dict) else {}
    return TokenPayload(
        access_token=read_str(data, "accessToken"),
        refresh_token=read_str(data, "refreshToken"),
        expires_in=read_num(data, "expiresIn"),
        user_id=read_str(user, "id"),
        yid=read_str(user, "yid"),
        account_user_id=read_str(user, "userId"),
        nickname=read_str(user, "nickname"),
    )


def _uid_hash(access_token: str) -> str:
    """`sha256(accessToken)` 前 16 位（Go `fmt.Sprintf("%x", sha256.Sum256(...))[:16]`）。

    ⚠️ 不复用 `net.cred_fingerprint`（那是日志指纹，只取 6 位）：uid 要与
    `lobsterai2api` 生成的 `auths/lobsterai-{uid}.json` **逐字节对照**（`lobsterai.ts:391-394`）。
    """
    return hashlib.sha256(access_token.encode("utf-8")).hexdigest()[:16]


def resolve_uid(payload: TokenPayload) -> str:
    """账号唯一 ID：`user.id` → `user.userId` → `user.yid` → `sha256(accessToken)[:16]`。

    四级回退严格对齐 `lobsterai.ts:383-406`（= Go `main.go:297-306`）：不同账号形态下
    哪个服务端字段非空并不固定；末级哈希兜底保证**任何情况下都有稳定 ID**
    （否则空 uid 会让多个账号互相覆盖）。⚠️ 刻意**不在** `yid` 与哈希之间插 JWT `sub`：
    插进去会让同一账号在本网关与 Go 侧得到两种 uid，破坏逐字节对照能力。
    """
    for candidate in (payload.user_id, payload.account_user_id, payload.yid):
        if candidate:
            return candidate
    return _uid_hash(payload.access_token)


def jwt_exp_ms(token: str) -> int | None:
    """从 JWT payload 读 `exp`（秒）并换算成毫秒；非 JWT / 解析失败 → `None`。

    只做 base64url 解码、**不验签**（该值只用于展示与续期调度，`buddy.ts:176-190`——
    lobsterai 复用它作 `expires_at` 的后备来源，`lobsterai.ts:262-277`）。
    """
    parts = token.split(".")
    if len(parts) < 2:
        return None
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    exp = payload.get("exp") if isinstance(payload, dict) else None
    # R2a-F-1（2026-10-06）：NaN/Inf ⇒ None，与 raccoon 同防护（int(nan) 抛未捕获 ValueError）
    if isinstance(exp, (int, float)) and not isinstance(exp, bool) and math.isfinite(exp):
        return int(exp) * 1000
    return None


def credential_expires_at_ms(cred: dict) -> int | None:
    """解析凭据的过期时刻（毫秒）；**兼容毫秒/秒时间戳与 ISO 8601**（`lobsterai.ts:266-277`）。

    后备来源：`expires_at` 为空时解 `access_token` 这个 JWT 的 `exp`（实测 HS512
    access token，`main.go:317` 说明其有效期 30 天）。⚠️ 无时区 ISO 串按**本地时间**解析
    （与 JS `Date.parse` 同口径）。解析不出 → `None`（**不判定过期**，`lobsterai.ts:279-283`）。
    """
    raw = read_str(cred, "expires_at")
    if raw:
        if raw.isdigit():
            value = int(raw)
            return value if value > 1_000_000_000_000 else value * 1000
        try:
            parsed = datetime.fromisoformat(raw.replace(" ", "T"))
        except ValueError:
            parsed = None
        if parsed is not None:
            return int(parsed.timestamp() * 1000)
    return jwt_exp_ms(read_str(cred, "access_token"))


def build_credential(payload: TokenPayload, *, uuid: str, first_keyfrom: str,
                     latest_keyfrom: str, now_ms: int) -> dict:
    """由令牌载荷组装可持久化凭据（字段名与 `lobsterai.ts:423-447` **逐字一致**）。

    `expires_at` 取值顺序（与 Go 一致，`main.go:313-319`）：① `expiresIn`（以**当前时刻**
    为基准换算，Go 用的是 `time.Now()` 而非 JWT `iat`）；② 缺失时用 access token 的
    JWT `exp`；③ 都拿不到则空串（展示层会显示「有效期未知」，而不是让登录失败）。
    `uuid` / `first_keyfrom` / `latest_keyfrom` **不在响应里**，由登录流程提供。
    """
    if payload.expires_in is not None and payload.expires_in > 0:
        expires_at = str(now_ms + int(payload.expires_in * 1000))
    else:
        exp = jwt_exp_ms(payload.access_token)
        expires_at = "" if exp is None else str(exp)
    return {
        "access_token": payload.access_token,
        "refresh_token": payload.refresh_token,
        "expires_at": expires_at,
        "uid": resolve_uid(payload),
        "user_id": payload.account_user_id or payload.yid,
        "nickname": payload.nickname,
        "uuid": uuid,
        "first_keyfrom": first_keyfrom,
        "latest_keyfrom": latest_keyfrom,
    }


def merge_refreshed(previous: dict, payload: TokenPayload, *, now_ms: int) -> dict:
    """用续期结果更新凭据（`lobsterai.ts:463-481`）。

    **所有身份字段一律沿用旧值**（`uuid` / `first_keyfrom` / `latest_keyfrom` / `uid` /
    `user_id` / `nickname`）：refresh 响应只带令牌、不含 account 对象。
    ⚠️ `latest_keyfrom` **刻意不更新为当前时刻**（字段名虽是「最近活动」，但 Go 的
    `RefreshToken` 从不更新它、续期时原样回发；自作聪明地更新将无法从代码推导后果，
    需要实测支撑 —— `lobsterai.ts:456-462`）。
    `refresh_token` 响应为空时**不覆盖**（不能把好凭据冲成空串）。
    """
    if payload.expires_in is not None and payload.expires_in > 0:
        expires_at = str(now_ms + int(payload.expires_in * 1000))
    else:
        exp = jwt_exp_ms(payload.access_token)
        expires_at = str(exp) if exp is not None else read_str(previous, "expires_at")
    return {
        **previous,
        "access_token": payload.access_token,
        "refresh_token": payload.refresh_token or read_str(previous, "refresh_token"),
        "expires_at": expires_at,
    }


# ---------- 展示层（昵称掩码 / 账号元信息） ----------

def _mask_phone_tail(value: str, visible_tail: int = 2) -> str:
    """手机号掩码归一化为**只露末 2 位**（照抄 `lobsterai.ts:143-169`）。

    服务端把**手机号本身**当昵称下发且只脱敏到露 4 位（用户 2026-09-27 要求归一化）。
    ⚠️ 只对「像手机号」的输入生效（11 位纯数字 / `3 位数字+星号+数字` 的脱敏形态）：
    泛化到任意字符串会把真实昵称（如 `用户26815487395`）也掩码掉。星号个数按原串总长推算。
    """
    trimmed = value.strip()
    if not trimmed:
        return trimmed

    def rebuild(prefix: str, total_length: int, tail: str) -> str:
        star_count = total_length - len(prefix) - len(tail)
        return trimmed if star_count < 0 else f"{prefix}{'*' * star_count}{tail}"

    if re.fullmatch(r"1\d{10}", trimmed):
        return rebuild(trimmed[:3], len(trimmed), trimmed[-visible_tail:])
    masked = re.fullmatch(r"(\d{3})(\*+)(\d+)", trimmed)
    if masked is not None:
        total = len(masked.group(1)) + len(masked.group(2)) + len(masked.group(3))
        return rebuild(masked.group(1), total, masked.group(3)[-visible_tail:])
    return trimmed


def display_nickname(nickname: str, fallback: str) -> str:
    """账号展示名：昵称经手机号掩码归一化；空昵称回退账号名（`lobsterai.ts:178-185`）。"""
    text = (nickname or "").strip()
    return _mask_phone_tail(text) if text else fallback


#: lobsterai 的**非身份元数据**字段（§22.3 裁决 2026-09-29：keyfrom 不进 `DeviceSpec`）：
#: 存 `meta.json` 供界面/续期取证，但**不参与跨账号唯一性判定**（`DeviceSpec.fields`
#: 里没有它们，`accounts/device.py` 也就不会拿它们比较）。
META_ONLY_FIELDS = ("first_keyfrom", "latest_keyfrom")


def credential_meta(cred: dict, *, fallback_name: str, device_fields: tuple[str, ...]) -> dict:
    """`LoginOutcome.meta` / `refresh` 写回用的**账号元信息**（§22.2：设备字段住 meta.json）。

    - `device_fields`（来自注册表 `DeviceSpec.fields`）= **身份字段**（本产品 = `uuid`），
      逐个从凭据里取；`META_ONLY_FIELDS`（keyfrom 时间戳）= 非身份元数据，**同样落
      meta.json**（裁决口径）但不在 spec 里、不参与唯一性。
    - **空值不落键** —— `accounts/device.py::_present_fields` 只把「字符串且非空白」的字段
      视为存在；写空串等于给账号留半截身份（同字段两个空值会被误判成"同一设备"）。
    - `uid` / `nickname` / `expires_at`：**展示用镜像**。§22.7 要求管理端返回体不含凭据
      明文 → 界面要的昵称与有效期必须落在 meta.json 里（凭据仍是唯一权威；
      `expires_at` 在此为整数毫秒，凭据里是毫秒字符串 —— 照抄 DSH 的凭据格式）。
    """
    meta: dict = {}
    for field_name in (*device_fields, *META_ONLY_FIELDS):
        value = read_str(cred, field_name)
        if value:
            meta[field_name] = value
    uid = read_str(cred, "uid")
    if uid:
        meta["uid"] = uid
    meta["nickname"] = display_nickname(read_str(cred, "nickname"), fallback_name)
    expires = credential_expires_at_ms(cred)
    if expires is not None:
        meta["expires_at"] = int(expires)
    return meta


# ---------- 元信息写回（唯一落盘入口 = accounts/store.py） ----------

def write_meta_fields(dir_path: str, updates: dict) -> None:
    """把展示字段写回账号 `meta.json`（**只补不删**，值没变就不写盘）。

    为什么需要它（照抄 DSH 的真实缺陷教训 !IKIRTT）：续期只更新凭据、不回写池值，
    会让界面**永远显示「已过期」**且没有自救手段（`lobsterai-auth.ts:420-425`）。
    本函数只被 `login.refresh_credential` 用来同步 `expires_at`。

    - 路径由 `meta` 通道给出（§22.3 ③：账号目录经 `meta["dir"]` 传入）；
    - 读不动既有 meta.json → **不动它**（宁可少写一次展示值，也不覆盖用户的账号目录）；
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
