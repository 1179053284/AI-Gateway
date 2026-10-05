"""Cline 协议**纯函数**（解析 / 构造 / 判定；不做任何 IO —— 与 DSH `cline.ts` 同形）。

🗂 证据面（只读）：DSH `src/cline.ts`（凭据模型与协议纯函数）、`src/cline-oauth.ts`（登录载荷）、
   `src/cline-credits.ts`（余额解析）、`src/cline-models.ts`（目录解析与合并）。

🔴 与既有 provider 的三处差异（都踩过或差点踩，逐条照抄 DSH 注释）：
   ① **访问令牌带 `workos:` 前缀且不可剥**（`cline.ts:159-182`；见 `bearer_value` 的坑位说明）；
   ② **续期字段是驼峰 `refreshToken` / `grantType`**，不是 OAuth 标准的
      `refresh_token` / `grant_type`（`cline.ts:250-268`）；
   ③ **注册/续期响应套一层 `{success, data}` 信封**，且字段名是 `accessToken`（驼峰）
      而非 `access_token`（`cline.ts:101-120`）。
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from model_gateway.accounts.types import ModelInfo
from model_gateway.upstream.cline import constants as C

# ==================== 鉴权头（`workos:` 前缀坑位）====================


def bearer_value(access_token: str) -> str:
    """确保访问令牌带 `workos:` 前缀（**幂等补齐**，`cline.ts:159-182`）。

    🔴 **坑位适用范围（必读，`cline-product.ts:96-115`）**：该前缀只在**解码 JWT** 时被剥掉
    （`decodeJwtPayload(token.replace(/^workos:/, ""))`），**从不出现在请求头构造里** ——
    即凡是把存储的访问令牌放进 `Authorization` 的请求（出站推理 `/chat/completions`、
    探活 `users/me`、余额 `users/{id}/balance`）**都必须保留前缀**。实测同一凭据：

    - `Authorization: Bearer workos:eyJ…` → `/api/v1/users/me` **200**
    - `Authorization: Bearer eyJ…`（剥前缀）→ **401**，文案是
      "make sure you're using the latest version of Cline" —— **与真实原因毫不相干**，
      剥前缀会让人误判成「版本过旧」。

    ⚠️ **不适用于** token 交换类调用：`/api/v1/auth/register` 与 `/api/v1/auth/refresh`
    用请求体字段自证身份（`accessToken`/`refreshToken`），不构造 `Authorization` 头；
    前缀在那些地方既不必要也不该补（register 的 `accessToken` 原样来自 WorkOS 轮询结果）。

    实现为幂等补齐而非强制加前缀：服务端确实下发带前缀的值（`cline.ts:171-176`），
    补前缀分支是对「上游某天改回不带前缀」这一变更保持鲁棒。
    """
    token = str(access_token or "").strip()
    if not token:
        return ""
    return token if token.startswith(C.TOKEN_PREFIX) else f"{C.TOKEN_PREFIX}{token}"


def auth_headers(access_token: str, extra: dict | None = None) -> dict[str, str]:
    """带前缀令牌 + 客户端标识头的鉴权头（`cline.ts:270-307` 的 `clineHeaders`/`clineAuthHeaders`）。"""
    headers = {
        "Authorization": f"Bearer {bearer_value(access_token)}",
        "Accept": "application/json",
        **C.CLIENT_HEADERS,
    }
    if extra:
        headers.update(extra)
    return headers


# ==================== 凭据本体 ====================


def parse_token_payload(value: Any) -> dict:
    """解析注册/续期响应（`parseClineTokenPayload`，`cline.ts:101-157`）。

    两处响应**同构**（源码 `registerWorkOSTokens` 与 `refreshClineToken` 都过 `toClineCredentials`）::

        {"success": true,
         "data": {"accessToken": "workos:eyJ…", "refreshToken": "tmgEeM…",
                  "expiresAt": "2026-09-25T05:23:47.000Z", "tokenType": "Bearer",
                  "userInfo": {"clineUserId": "usr-…", "email": "…",
                               "firstName": "", "lastName": ""}}}

    垃圾输入返回空 `accessToken`（而非抛错），由调用方判定失败（与 `parseQoderTokenPayload` 同约定）。
    兼容裸响应（无 `data` 信封）与下划线字段名（对上游变更鲁棒）。
    """
    out: dict = {"access_token": ""}
    if not isinstance(value, dict):
        return out
    inner = value.get("data") if isinstance(value.get("data"), dict) else value
    out["access_token"] = _read_str(inner, "accessToken", "access_token") or ""
    refresh = _read_str(inner, "refreshToken", "refresh_token")
    if refresh:
        out["refresh_token"] = refresh
    expires = parse_timestamp_ms(inner.get("expiresAt", inner.get("expires_at",
                                  inner.get("expire_time"))))
    if expires is not None:
        out["expire_time"] = expires
    user_info = inner.get("userInfo") if isinstance(inner.get("userInfo"), dict) else None
    if user_info is not None:
        account_id = _read_str(user_info, "clineUserId", "accountId") \
            or _read_str(inner, "accountId", "account_id")
        email = _read_str(user_info, "email") or _read_str(inner, "email")
        name = " ".join(filter(None, (_read_str(user_info, "firstName"),
                                      _read_str(user_info, "lastName"))))
    else:
        account_id = _read_str(inner, "accountId", "account_id")
        email = _read_str(inner, "email")
        name = ""
    if account_id:
        out["account_id"] = account_id
    if email:
        out["email"] = email
    display_name = (name or "").strip()
    if display_name:
        out["display_name"] = display_name
    return out


def build_credentials(payload: dict) -> dict:
    """把 token 载荷合成为**落盘凭据本体**（`buildClineCredential`，`cline.ts:184-204`）。

    键名沿用官方 SDK 口径（`access_token` / `refresh_token` / `expire_time` / `account_id` /
    `email` / `nickname`，`cline.ts:27-51`）；昵称优先邮箱（唯一且稳定），其次展示名，最后账号 id。
    """
    account_id = payload.get("account_id") or ""
    email = payload.get("email") or ""
    credential: dict = {"access_token": bearer_value(payload.get("access_token") or "")}
    if payload.get("refresh_token"):
        credential["refresh_token"] = payload["refresh_token"]
    if payload.get("expire_time") is not None:
        credential["expire_time"] = payload["expire_time"]
    if account_id:
        credential["account_id"] = account_id
    if email:
        credential["email"] = email
    nickname = email or payload.get("display_name") or account_id
    if nickname:
        credential["nickname"] = nickname
    return credential


def apply_refresh(credential: dict, payload: dict) -> dict:
    """把一次续期结果合并回既有凭据（`applyClineRefresh`，`cline.ts:206-227`）。

    🔴 **保留** `account_id` / `email` / `nickname`：它们不在续期响应里（可能缺省），
    丢了会让账号卡片失去展示名与**余额查询所需的账号 id**。
    """
    merged = dict(credential or {})
    merged["access_token"] = bearer_value(payload.get("access_token") or "")
    for key in ("refresh_token", "expire_time", "account_id", "email"):
        if payload.get(key) is not None:
            merged[key] = payload[key]
    return merged


def refresh_body(credential: dict) -> dict[str, str]:
    """续期请求体（`clineRefreshBody`，`cline.ts:250-268`）。

    ⚠️ 字段名是**驼峰** `refreshToken` / `grantType`，不是 OAuth 标准的
    `refresh_token` / `grant_type`。写错字段名服务端不会明确报「缺字段」，
    而是回一个泛化的认证失败，**极难定位**（两者都是必填）。
    """
    return {"refreshToken": str((credential or {}).get("refresh_token") or ""),
            "grantType": "refresh_token"}


def parse_timestamp_ms(value: Any) -> int | None:
    """时间形态归一为毫秒时间戳（`parseClineTimestamp`，`cline.ts:81-99`）。

    实测 `expiresAt` 是 **ISO 8601 字符串**（源码 `toEpochMs` 直接 `Date.parse`），
    为鲁棒同时接受数字（<1e12 视为秒，否则毫秒）。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return round(value * 1000) if value < 1e12 else round(value)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:                                  # `Z` 后缀 → `+00:00`（3.11 起原生支持 Z，双保险）
            parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return round(parsed.timestamp() * 1000)
    return None


# ==================== 登录载荷 ====================


def parse_device_authorization(value: Any) -> dict:
    """解析 WorkOS 设备码授权响应（`requestClineDeviceAuthorization`，`cline-oauth.ts:178-212`）。

    字段齐备性判据照 DSH：缺 `device_code` / `user_code` / `verification_uri`
    **任一即视为无效响应**（`cline-oauth.ts:194-199`）。

    ⚠️ 返回的 `device_code` 是**设备码私钥**（轮询用），`user_code` 才是**给用户看的码** ——
    前者只许进 `LoginSession.state`，后者才进 `Challenge`（§22.3 / `accounts/types.py:87-103`）。

    归一化字段：`device_code` / `user_code` / `verification_uri` / `login_url` /
    `expires_in_s` / `interval_ms`。
    """
    if not isinstance(value, dict):
        raise ValueError("设备码授权响应不是 JSON 对象")
    device_code = str(value.get("device_code") or "").strip()
    user_code = str(value.get("user_code") or "").strip()
    verification_uri = str(value.get("verification_uri") or "").strip()
    if not device_code or not user_code or not verification_uri:
        raise ValueError("设备码授权响应缺少必要字段（device_code/user_code/verification_uri）")
    complete = str(value.get("verification_uri_complete") or "").strip()
    return {
        "device_code": device_code,
        "user_code": user_code,
        "verification_uri": verification_uri,
        # 有 `verification_uri_complete` 时优先用它：用户不必再手输 user_code（`cline-oauth.ts:398-399`）
        "login_url": complete or verification_uri,
        "expires_in_s": _to_seconds(value.get("expires_in"), C.DEVICE_AUTH_EXPIRES_S),
        "interval_ms": max(C.DEVICE_AUTH_MIN_INTERVAL_MS,
                           _to_seconds(value.get("interval"), C.DEVICE_AUTH_INTERVAL_S) * 1000),
    }


def _to_seconds(value: Any, fallback: int) -> int:
    """把秒归一为整数秒；非法值回退默认（`toMs` 的秒级版本，`cline-oauth.ts:164-168`）。"""
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return fallback


# ==================== 余额 ====================


def parse_balance(value: Any) -> tuple[float | None, str]:
    """解析余额响应 → `(原始数值, 失败原因)`（`parseClineBalanceResponse`，`cline-credits.ts:126-162`）。

    判据：`success === true` 且 `data.balance` 为有限数值；**查不到不显示成 0**
    （那是「已用光」的语义，`cline-credits.ts:129-131`）。

    ⚠️ **失败形态有两种，必须都认**（真实缺陷，`cline-credits.ts:133-140`）：
    `{success:false, error:…}`（业务层失败，HTTP 200）与 `{error:"Unauthorized: …"}`
    （网关层失败，HTTP 401 —— **没有 `success` 字段**）。只判第一种会把服务端真正给的原因丢掉，
    而那正是排查鉴权问题唯一有用的线索。
    """
    if not isinstance(value, dict):
        return None, "响应不是 JSON 对象"
    server_error = str(value.get("error") or "").strip()
    if value.get("success") is False or (server_error and value.get("success") is not True):
        return None, server_error or "服务端返回失败"
    data = value.get("data") if isinstance(value.get("data"), dict) else None
    if data is None:
        return None, "响应缺少 data 字段"
    raw = data.get("balance")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        if isinstance(raw, str) and raw.strip():
            try:
                raw = float(raw.strip())
            except ValueError:
                return None, "响应缺少 balance 字段"
        else:
            return None, "响应缺少 balance 字段"
    return float(raw), ""


def num_text(value: float) -> str:
    """数值的展示文本（整数值不显示小数点；**不做任何单位换算**，见 constants 的未取证说明）。"""
    return str(int(value)) if float(value).is_integer() else repr(value)


# ==================== 模型目录 ====================


def merge_models(free_ids: list[str], entries: list[dict], remote_ids: list[str]) -> list[ModelInfo]:
    """三来源合并为最终目录（`mergeClineModels`，`cline-models.ts:180-235`）。

    顺序（**决定列表展示顺序，逐条照抄**）：

    1. 远端 `free` 数组（免费集合**唯一权威**，且顺序有意义）；
    2. 兜底表（含内嵌目录缺的 `cline-free/gemini-3.8-flash`，离线/抖动时也可见）；
    3. `recommended` / `clinePass` 里出现但上面没覆盖的（保持可发现性）；
    4. 远端 `/models` 的其余 id —— **放最后**：它们只有裸 id、无元数据，且数量达 460 个，
       放前面会把免费模型挤到看不见（`cline-models.ts:180-191`）。

    元数据优先级：兜底表（有 `contextWindow`/`maxTokens`/`capabilities`）> 远端 `free`/`recommended`
    的 `name` > 由 id 派生的名字（`cline-models.ts:188-191`）。**未知一律不编造**（`21 §1.2`）：
    远端只给 id 的模型 → `context_window` / `image_input` 保持 `None`。

    免费判定（**不硬编码模型名**，`cline-models.ts:20-36, 85-94`）::

        isFree(id) = remoteFreeIds.has(id) || id.endsWith(':free')
                  || id.startsWith('cline-free/') || fallback.isFree

    ⚠️ **免费模型是独立 id**：`cline-free/deepseek-v4.1-flash`（免费）与
    `deepseek/deepseek-v4.1-flash`（按量计费）是两个不同条目，绝不可模糊匹配
    —— 那会把付费条目误标为免费，用户按免费预期使用却被计费。
    """
    fallback_index = {model.id: model for model in C.FALLBACK_MODELS}
    free_set = set(free_ids)
    entry_index: dict[str, dict] = {}
    for entry in entries:
        entry_index.setdefault(str(entry.get("id") or ""), entry)

    out: list[ModelInfo] = []
    seen: set[str] = set()

    def push(model_id: str) -> None:
        if not model_id or model_id in seen:
            return
        seen.add(model_id)
        out.append(_build_model(model_id, fallback_index.get(model_id),
                                entry_index.get(model_id), free_set))

    for model_id in free_ids:
        push(model_id)
    for model in C.FALLBACK_MODELS:
        push(model.id)
    for entry in entries:
        push(str(entry.get("id") or ""))
    for model_id in remote_ids:
        push(model_id)
    return out


def _build_model(model_id: str, fallback, entry: dict | None, free_set: set[str]) -> ModelInfo:
    """构造一条 `ModelInfo`（免费标记拼进 `name`，**不是** description —— 与 DSH 同因，见下）。

    `is_free` 判定见 `merge_models` 的文档；展示名规则见 `display_name`。
    `free`（结构化，2026-10-01 补）= `is_free` 判定结果（本产品的免费信息**只有布尔形态**：
    远端 `free` 集合 / id 形态 / 兜底表标志，没有数值倍率）→ `rate` 留空（未提供）。
    """
    entry = entry or {}
    base_name = ""
    if fallback is not None and fallback.name:
        base_name = fallback.name
    elif entry.get("name"):
        base_name = str(entry["name"]).strip()
    else:
        base_name = name_from_id(model_id)
    is_free = is_free_model(model_id, free_set, fallback)
    return ModelInfo(
        id=model_id,
        name=display_name(base_name, is_free),
        # vendor：口径 = **厂商（模型生产公司）展示名** —— `ModelInfo` 逐字段镜像内置目录
        # `EnumEntry`（`accounts/types.py:201`），而 `enums/matcher.py:27` 的 `vendor` 就是厂商。
        # 远端只给 id 的命名空间前缀（`deepseek/…`）与兜底表都不带可核对的厂商展示名，
        # 无法可靠映射 → **留空（未归类），不编造**。
        vendor="",
        context_window=fallback.context_window if fallback is not None else None,
        max_output=fallback.max_output if fallback is not None else None,
        # 工具调用：远端与兜底表都不下发该信息 → 保持 None（`None` = 未取到，`False` = 明确不支持）
        tool_call=None,
        image_input=fallback.supports_image if fallback is not None else None,
        # 思考档位是**产品级统一表**（远端不下发，`cline-product.ts:206-213`）：DSH 对所有
        # cline 模型统一声明，本项目同样照抄（上游对未知档位静默忽略，最坏是开关无效）。
        reasoning=True,
        effort_levels=tuple(effort for effort, _ in C.REASONING_EFFORTS),
        free=is_free,
        rate="",   # 无数值倍率：本产品只有「免费 / 非免费」的布尔信息（不编造 x1）
    )


def is_free_model(model_id: str, free_set: set[str], fallback=None) -> bool:
    """免费判定（并集；`cline-models.ts:85-94`）—— 顺序无关，保留短路以省集合查找。"""
    if model_id in free_set:
        return True
    if model_id.endswith(C.FREE_ID_SUFFIX) or model_id.startswith(C.FREE_ID_PREFIX):
        return True
    return bool(fallback is not None and fallback.is_free)


def display_name(name: str, is_free: bool) -> str:
    """展示名：免费模型拼 ` · 免费`（`clineDisplayName`，`cline-models.ts:96-109`）。

    ⚠️ **必须写进 `name`，不是 `description`**：composer 的模型切换菜单只渲染 `name`，
    `description` 只在 `/model` 弹窗里用（用户报障纠正过的结论，`cline-models.ts:99-105`）。
    `name` 纯属展示：选择与持久化只用 `id`，故附加标记不会污染会话历史。
    """
    text = str(name or "").strip()
    return f"{text} · 免费" if is_free and text else text


def name_from_id(model_id: str) -> str:
    """从远端 id 派生可读兜底展示名（`nameFromId`，`cline-models.ts:111-118`）。

    去掉 provider 命名空间前缀（`deepseek/deepseek-v4.1-flash` → `Deepseek V4.1 Flash`）；
    id 保持原样，展示名只求可读。
    """
    tail = model_id.split("/", 1)[1] if "/" in model_id else model_id
    tail = tail.replace(C.FREE_ID_SUFFIX, "").replace("-", " ")
    return re.sub(r"\b\w", lambda m: m.group().upper(), tail)


def parse_recommended_models(value: Any) -> dict:
    """解析 `recommended-models` 响应（`parseClineRecommendedModels`，`cline-models.ts:148-164`）。

    ⚠️ **`clinePass` 不是免费集合**：它是 Cline Pass 订阅制模型（`cline-pass/*`），
    按订阅额度计费而非免费；把它当免费会误导用户（`cline-models.ts:148-153`）。
    """
    empty = {"free": [], "recommended": [], "clinePass": []}
    if not isinstance(value, dict):
        return empty
    return {key: _entry_list(value.get(key)) for key in empty}


def parse_remote_model_ids(value: Any) -> list[str]:
    """解析 `/api/v1/models` 响应，取出 id 列表（`parseClineRemoteModelIds`，`cline-models.ts:166-178`）。"""
    if not isinstance(value, dict):
        return []
    data = value.get("data")
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        if isinstance(item, dict):
            model_id = str(item.get("id") or "").strip()
            if model_id:
                out.append(model_id)
    return out


def _entry_list(value: Any) -> list[dict]:
    """把远端数组归一化（丢弃无 id 的垃圾项；`parseEntryList`，`cline-models.ts:130-146`）。"""
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            continue
        entry = {"id": model_id}
        for key in ("name", "description"):
            text = str(item.get(key) or "").strip()
            if text:
                entry[key] = text
        out.append(entry)
    return out


def _read_str(source: dict, *keys: str) -> str | None:
    """从记录里读第一个非空字符串字段（`readString`，`cline.ts:72-79`）。"""
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
