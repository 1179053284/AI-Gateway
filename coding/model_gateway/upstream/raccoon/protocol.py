"""Raccoon 协议纯函数：信封解析 / 凭据归一 / JWT 过期 / 请求头 / 展示名 / 手机号加密。

🗂 全部照抄 DSH（`src/raccoon.ts`、`src/raccoon-oauth.ts`、`src/raccoon-credits.ts`、
   `src/raccoon-auth.ts`），每条函数 docstring 给出 `file:line`。
🔴 本模块**无 IO、无日志、不抛业务异常**（只做解析/构造），便于离线单测；
   网络与失败折叠在 `login.py` / `models.py` / `product.py`。
"""

from __future__ import annotations

from model_gateway.upstream._text import strip_control

import base64
import json
import math
import re
import secrets
import urllib.parse
from dataclasses import dataclass

from model_gateway.accounts.types import ModelInfo
from model_gateway.upstream.raccoon import const as C

#: 手机号形态（`raccoon-login-page.ts:229`：11 位、1 开头、第二位 3-9）
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


# ---------- 信封与字段读值 ----------


@dataclass(frozen=True)
class Envelope:
    """业务信封（`raccoon-oauth.ts:62-73` / `raccoon-credits.ts:52-64` 的统一形状）。

    `code == 0` = 成功；缺失 `code` 时按 HTTP 状态兜底（`status >= 400` → `code = status`，
    否则 0）——两条 DSH 实现都有这条兜底，照抄以免把"HTTP 200 + 无 code"误判成失败。
    """

    code: int
    message: str = ""
    details: str = ""
    data: dict | None = None
    status: int = 0

    @property
    def ok(self) -> bool:
        return self.code == 0

    def error_text(self, fallback: str) -> str:
        """错误文案（服务端 `message` 优先，其次 `details`；都没有才用 fallback）。

        `raccoon-oauth.ts:76-80`（message + details 拼接）、`raccoon-credits.ts:57-59`。
        """
        parts = [text for text in (self.message, self.details) if text]
        return "：".join(parts) if parts else fallback


def parse_envelope(payload: object, status: int = 0) -> Envelope:
    """解析业务信封（非对象载荷 → 全空信封；`code` 走状态兜底）。"""
    record = payload if isinstance(payload, dict) else {}
    raw_code = record.get("code")
    # 🔴 R2a-F-2（2026-10-06 第三轮对账修）：数字字符串按数字读（同族实证见
    # trae/protocol.py:84）——`{"code":"200003"}`（字符串）旧读法会落到 0 ⇒
    # `product.py:162` 的 NotRefreshable 恒不触发、`envelope.ok` 反为真 ⇒
    # 坏号被判成功。布尔排除；非数字字符串维持「状态兜底」不猜。
    if isinstance(raw_code, bool):
        code = status if status >= 400 else 0
    elif isinstance(raw_code, (int, float)):
        code = raw_code
    elif isinstance(raw_code, str) and re.fullmatch(r"-?\d+", raw_code.strip()):
        code = int(raw_code.strip())
    else:
        code = status if status >= 400 else 0
    message = record.get("message") if isinstance(record.get("message"), str) else ""
    details = record.get("details") if isinstance(record.get("details"), str) else ""
    data = record.get("data") if isinstance(record.get("data"), dict) else None
    return Envelope(code=int(code), message=message, details=details, data=data, status=status)


def read_str(record: dict | None, key: str) -> str:
    """读字符串字段（缺失 / 类型不符 → 空串；**不猜**）。

    🔴 R2a-F-4（2026-10-06）：控制字符剥离与 buddy 同口径（`upstream/_text.py` 一份
    实现）——上游多行文本会破坏落盘 JSON（buddy `scope` 缺陷的同形状敞口）。
    """
    if not isinstance(record, dict):
        return ""
    value = record.get(key)
    return strip_control(value) if isinstance(value, str) else ""


def read_number(record: dict | None, key: str) -> float | None:
    """读有限数字（`raccoon-credits.ts:66-69`：非法返回 `None`，**不编造 0**）。"""
    if not isinstance(record, dict):
        return None
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def positive_int(value: object) -> int | None:
    """读正整数（`raccoon-auth.ts:168-170` 的 `readPositiveInt`；不合法 → `None`）。

    ⚠️ DSH 该函数对不合法值返回 **0**，再由调用方按 `> 0` 过滤；本网关的 `ModelInfo`
    语义是 `None = 未取到`（`21 §5.1-1`），故这里直接归一成 `None`（等价判据，少一层）。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


# ---------- 扫码登录（`raccoon-oauth.ts:111-180`）----------


def new_qr_code() -> str:
    """生成扫码用的 `qrcode_code`：**32 位小写 hex**（16 字节随机）。

    依据客户端 `CryptoJS.lib.WordArray.random(16)`（`raccoon-oauth.ts:111-118`）。
    实测服务端接受任意自造 code 并进入 `pending`，故无需官方那条收不到的自定义协议回调
    （`raccoon.ts:10-15`）。
    """
    return secrets.token_hex(16)


def qr_login_url(code: str) -> str:
    """二维码承载的微信登录页 URL（`raccoon-oauth.ts:127-130`）。

    ``{apiBase}/login/mp?code=<code>&appname=商汤小浣熊官网`` —— 公开页面，扫码后在微信内
    完成授权，服务端据此把该 code 置为 `success`，我们轮询 `login_with_qrcode_code` 取回 token。
    """
    query = urllib.parse.urlencode({"code": code, "appname": C.QR_PAGE_APPNAME})
    return f"{C.API_BASE}{C.QR_PAGE_PATH}?{query}"


# ---------- 凭据本体（`raccoon.ts:71-106`、`raccoon-oauth.ts:238-319`）----------


def credentials_from_login(data: dict | None) -> dict:
    """从登录成功信封的 `data` 组装凭据（`raccoon-oauth.ts:238-253`）。

    - `access_token` 空 → 由调用方判失败（本函数**不抛**）；
    - `expires_at` 由 JWT 的 `exp` **本地推算**（毫秒时间戳字符串；`raccoon.ts:140-150`
      的实现同时保留 `expires_at` 与 JWT 回退两条路径）；
    - `office_identity` 为空则不写（个人账号为空串）。
    """
    raw = data if isinstance(data, dict) else {}
    access_token = read_str(raw, "access_token")
    refresh_token = read_str(raw, "refresh_token")
    office_identity = read_str(raw, "office_identity")
    out: dict = {"access_token": access_token, "refresh_token": refresh_token}
    exp_ms = jwt_exp_ms(access_token)
    if exp_ms is not None:
        out["expires_at"] = str(exp_ms)
    if office_identity:
        out["office_identity"] = office_identity
    return out


def jwt_exp_ms(token: str) -> int | None:
    """解码 JWT payload 的 `exp` → **毫秒**时间戳（`raccoon.ts:108-129`）。

    ⚠️ **只解码、不验签** —— 我们只需要知道什么时候该续期，签名由服务端校验。
    ⚠️ 任何解析失败返回 `None` 而**不抛**：凭据可能被手工改坏，那时应降级成
    「无过期信息」（宁可试一次），而不是让整个产品崩。
    """
    if not isinstance(token, str) or not token:
        return None
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload_segment = parts[1]
    padded = payload_segment + "=" * (-len(payload_segment) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return None
    if not math.isfinite(float(exp)) or float(exp) <= 0:
        return None
    return int(float(exp) * 1000)


def is_refreshable(cred: dict | None) -> bool:
    """是否可静默续期 = `refresh_token` 非空（`raccoon.ts:164-172`）。

    raccoon **有**刷新端点（`POST /api/web/auth/v1/refresh`），与 loomy（恒 False）不同。
    """
    return bool(read_str(cred, "refresh_token").strip())


def access_token_of(cred: dict | None) -> str:
    """取访问令牌（空串 = 未登录，调用方据此**不发请求**）。"""
    return read_str(cred, "access_token").strip()


def apply_refresh(cred: dict, data: dict | None) -> dict:
    """续期响应 → **新的**凭据本体（`raccoon-oauth.ts:289-319`）。

    🔴 两条照抄的语义：
    ① 服务端可能**只返回新的 access_token**（不带新 refresh_token）→ 必须**保留旧值**，
       否则续期一次就把账号变成不可续期；
    ② 服务端不返回的附加字段（昵称、身份、手机号、设备号）**原样保留**（`...credential` 展开）。
    """
    raw = data if isinstance(data, dict) else {}
    access_token = read_str(raw, "access_token")
    next_refresh = read_str(raw, "refresh_token") or read_str(cred, "refresh_token")
    out = {**dict(cred or {}), "access_token": access_token, "refresh_token": next_refresh}
    exp_ms = jwt_exp_ms(access_token)
    if exp_ms is not None:
        out["expires_at"] = str(exp_ms)
    return out


def build_nickname(cred: dict | None, fallback_id: str) -> str:
    """多账号消歧昵称（`jet-hub-rpc.ts:251-270` 的 `buildRaccoonNickname`，逐字照抄）。

    服务端的 `name` 是**自动生成的默认名**（实测 `RaccoonAva`），微信扫码不回传微信昵称
    → 多个账号会重名。故追加**手机号尾号**（其次 user id）消歧：`RaccoonAva (1100)`。
    """
    nickname = read_str(cred, "nickname").strip()
    phone = read_str(cred, "phone").strip()
    user_id = read_str(cred, "user_id").strip()
    suffix = phone[-4:] if len(phone) >= 4 else user_id
    if nickname:
        # 已有该后缀时不重复追加（例如服务端名字里本就带手机号尾号）
        return f"{nickname} ({suffix})" if suffix and suffix not in nickname else nickname
    if suffix:
        return f"Raccoon {suffix}"
    return fallback_id


# ---------- 请求头（`raccoon.ts:264-293`）----------


def headers(cred: dict | None, *, platform: str = "", version: str = "") -> dict[str, str]:
    """业务端点请求头（照抄 `raccoonHeaders`，`raccoon.ts:264-293`）。

    - `X-Org-Code` **总是**发送（个人账号为空串，`raccoon.ts:279-280`）；
    - `X-Client-Platform` / `X-Client-Version` 由调用方按端点决定是否带
      （`login/points/grant` **必需** platform，`raccoon-credits.ts:87-90,171-173`）；
    - `X-Client-Device-ID` 仅在凭据里确有 `device_id` 时发送（可选字段，`raccoon.ts:289-291`）。
    """
    raw = cred if isinstance(cred, dict) else {}
    out: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {read_str(raw, 'access_token')}",
        "X-Org-Code": read_str(raw, "office_identity"),
        "X-Raccoon-Language": C.LANGUAGE,
    }
    if platform:
        out["X-Client-Platform"] = platform
    if version:
        out["X-Client-Version"] = version
    device_id = read_str(raw, "device_id").strip()
    if device_id:
        out["X-Client-Device-ID"] = device_id
    return out


# ---------- 手机号（短信登录路径）----------


def phone_valid(phone: str) -> bool:
    """11 位手机号形态（`raccoon-login-page.ts:229` 的前端同款判据）。"""
    return bool(_PHONE_RE.match(str(phone or "").strip()))


def encrypt_phone(phone: str, *, iv: bytes | None = None) -> str:
    """加密手机号 → `Base64(iv ‖ ciphertext)`（`raccoon.ts:174-201`，算法照抄客户端）。

    ```
    key  = UTF8("senseraccoon2023")  → 16 字节 ⇒ AES-128
    iv   = 随机 16 字节
    mode = CFB, padding = NoPadding
    ```

    ⚠️ 必须**显式**用 `aes-128-cfb`：密钥 16 字节，写成 `aes-256-cfb` 会因长度不足抛错。
    ⚠️ 不加密会被服务端拒（`100003 params_encryted_error`，`raccoon.ts:17`）。

    `iv` 形参仅供单测注入固定值；生产路径省略（随机）。
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

    key = C.PHONE_CIPHER_SECRET.encode("utf-8")
    nonce = iv if iv is not None else secrets.token_bytes(16)
    encryptor = Cipher(algorithms.AES(key), _cfb_mode(nonce)).encryptor()
    body = encryptor.update(str(phone).encode("utf-8")) + encryptor.finalize()
    return base64.b64encode(nonce + body).decode("ascii")


def _cfb_mode(iv: bytes):
    """CFB 模式构造（`cryptography` 46+ 把它挪进 `hazmat.decrepit`，旧版仍在 primitives）。

    ⚠️ 两处都试而不是直接 import 一处：`pyproject.toml` 的依赖下限是 `cryptography>=44.0`，
    44–45 只有 `primitives.ciphers.modes.CFB`；直接用新路径会在下限版本上 ImportError。
    """
    try:
        from cryptography.hazmat.decrepit.ciphers.modes import CFB
    except ImportError:  # pragma: no cover — cryptography < 46（依赖下限 44.0）
        from cryptography.hazmat.primitives.ciphers.modes import CFB
    return CFB(iv)


# ---------- 展示名 / 结构化计费（`raccoon.ts:219-262`）----------


def _format_multiplier(value: float) -> str:
    """倍率格式化：最多 4 位小数、去尾随 0（`raccoon.ts:219-223` 的 `formatMultiplier`）。"""
    text = f"{round(float(value), 4):.4f}".rstrip("0").rstrip(".")
    return text or "0"


def billing_info(effective: float | None, base: float | None) -> tuple[bool | None, str]:
    """结构化计费（`free` / `rate`）= `display_name` 的同一判据（`raccoon.ts:225-262`）。

    | 情形 | `free` | `rate` |
    |---|---|---|
    | 生效倍率 = 0 | `True` | `x0`（`display_name` 同情形显示「免费」，`free` 是权威信号） |
    | 生效 < 原价（且原价 > 0） | `False` | `x原价→x折后价` |
    | 其余（**含 1 倍**） | `False` | `x生效价` |
    | 倍率取不到（非有限数 / 负数） | `None`（未取到） | `""` |

    ⚠️ **1 倍也要给倍率**（`x1`）：省略会让该模型看起来「没有计费信息」
       （`raccoon.ts:232-236`，用户报障纠正过）。
    """
    if effective is None or not math.isfinite(effective) or effective < 0:
        return None, ""
    if effective == 0:
        return True, "x0"
    if base is not None and math.isfinite(base) and base > 0 and base > effective:
        return False, f"x{_format_multiplier(base)}→x{_format_multiplier(effective)}"
    return False, f"x{_format_multiplier(effective)}"


def display_name(description: str, effective: float | None, base: float | None) -> str:
    """模型展示名 = 名字主体 + 倍率后缀（`raccoon.ts:225-262`，逐条规则照抄）。

    | 情形 | 展示 |
    |---|---|
    | 生效倍率 = 0 | `名字 · 免费`（**不是** `x0`） |
    | 生效 < 原价（且原价 > 0） | `名字 · x原价→x折后价` |
    | 其余（**含 1 倍**） | `名字 · x生效价` |
    | 倍率取不到（非有限数 / 负数） | 只显示名字（**不产出孤立 ` · `**） |

    ⚠️ **1 倍也要显示**：省略会让该模型看起来「没有计费信息」（用户报障纠正过，
    `raccoon.ts:232-236`）。
    ⚠️ 本函数自 2026-10-01 起复用 `billing_info` 的分支（单一事实源）；输出**逐字不变**。
    """
    name = description if description else ""
    free, rate = billing_info(effective, base)
    if free is None:
        return name
    return f"{name} · 免费" if free else f"{name} · {rate}"


# ---------- 模型目录（`raccoon-auth.ts:137-182,622-652`）----------


def _normalize_remote_model(entry: dict) -> ModelInfo | None:
    """单条远端模型 → `ModelInfo`（`raccoon-auth.ts:137-182` 的 `normalizeRemoteModel`）。

    - 模型 id = 远端的 **`name` 字段**（不是 `id`；`raccoon-auth.ts:138`）；
    - `visible === False` → 过滤（缺省视为可见，**不因字段缺失而隐藏模型**，`:140-141`）；
    - `context_window` = `params.context_window ?? entry.context_window`（`:178`）；
    - `max_output` = `params.max_tokens`（`:179`）；
    - `image_input` = `tags` 命中 `vision`/`image`/`image-understanding`（`:180`；DSH 同口径：
      未声明保守报「纯文本」）；
    - `tool_call` 留 `None`：DSH 未声明工具能力 → **不编造**（`21 §5.1-1`）；
    - 思考档位：provider 级方言，所有模型一致（`raccoon-product.ts:100-110`）。
    """
    model_id = read_str(entry, "name").strip()
    if not model_id:
        return None
    if entry.get("visible") is False:
        return None
    raw_params = entry.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}
    description = read_str(entry, "description") or model_id
    effective = read_number(entry, "billing_effective_multiplier")
    base = read_number(entry, "billing_multiplier")
    tags = entry.get("tags")
    lowered = ({tag.lower() for tag in tags if isinstance(tag, str)}
               if isinstance(tags, list) else set())
    efforts = tuple(effort for effort, _ in C.REASONING_EFFORTS)
    # `params.context_window ?? entry.context_window`（`raccoon-auth.ts:178`）
    context_window = positive_int(params.get("context_window"))
    if context_window is None:
        context_window = positive_int(entry.get("context_window"))
    # 结构化计费：与展示名同判据（`billing_effective_multiplier` 生效价 / 原价）
    free, rate = billing_info(effective, base)
    return ModelInfo(
        id=model_id,
        name=display_name(description, effective, base),
        # 厂商未在目录里声明 → 留空（不编造）
        vendor="",
        context_window=context_window,
        max_output=positive_int(params.get("max_tokens")),
        tool_call=None,
        image_input=bool(lowered & set(C.VISION_TAGS)),
        reasoning=True if efforts else None,
        effort_levels=efforts,
        free=free,
        rate=rate,
    )


def parse_catalog(payload: object) -> list[ModelInfo] | None:
    """`GET /model_catalog` 响应 → 可见模型列表（`raccoon-auth.ts:622-652`）。

    只取 `categories[].type == 'chat'` 的那个分类（实测只有一个）、过滤 `visible === false`、
    按 id 去重（`:642-650`）。

    返回 `None` = **响应形态不认识**（非对象 / `code != 0` / 无 data / 无 chat 分类）——
    调用方据此回退兜底表；返回空列表 = 形态认识但确实没有可见模型。
    """
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    categories = data.get("categories")
    if not isinstance(categories, list):
        return None
    chat = next((item for item in categories
                 if isinstance(item, dict) and item.get("type") == "chat"), None)
    if not isinstance(chat, dict):
        return None
    raw_models = chat.get("models")
    if not isinstance(raw_models, list):
        return None
    seen: set[str] = set()
    out: list[ModelInfo] = []
    for raw in raw_models:
        if not isinstance(raw, dict):
            continue
        model = _normalize_remote_model(raw)
        if model is None or model.id in seen:
            continue
        seen.add(model.id)
        out.append(model)
    return out
