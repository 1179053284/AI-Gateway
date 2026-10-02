"""凭据**登录态失效时刻**的统一解析（2026-10-01 用户裁决：续期入账号行 + 失效前自动续期）。

🔴 本模块只回答一个问题：这份凭据的 access 侧**什么时候失效**。返回毫秒时间戳或
`None`（**解析不出不判定**——绝不当 0/已过期，与「未知不当零」同尺）。

字段形态逐产品取证（各 `upstream/<product>/` 落盘侧）：
- buddy/workbuddy：`expires_at` = 毫秒时间戳**字符串**（`protocol.parse_token_data`，
  缺失时回退 JWT `exp`，写入侧已固化）；
- trae / lobsterai：`expires_at` 毫秒（trae 回写 meta.json，!IKIRTT 教训）；
- qoder/qodercn：**`expire_time`**（毫秒，`flow.py:166` 写入侧归一化后的值；
  响应侧才叫 `expires_at|expiresAt`）；
- loomy：本地按 14 天推算的毫秒时间戳字符串（`login.py:452-459`）；
- raccoon：`expires_at` 由 JWT `exp` 推算后落盘；
- cline / zcode：凭据只有 JWT（workos: 前缀 / zcodejwttoken）→ 走 JWT `exp` 兜底。

兼容矩阵（与 `qoder.flow._read_timestamp` / `lobsterai.protocol.credential_expires_at_ms`
同口径，这里收敛成一份）：10 位数字 = 秒、13 位 = 毫秒、ISO 8601 串按本地时区
（与 JS `Date.parse` 同口径）。⚠️ JWT 只解 payload 的 `exp`，**不做签名校验**
（本地自己人自己的凭据，不跨信任边界）。
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import json

#: 候选键（按序取第一个可解析的；覆盖各产品落盘命名差异）
#: ⚠️ `expire_time` 不是笔误：qoder/qodercn 的凭据写入侧用的就是这个名字
#:    （`upstream/qoder/flow.py:166` `out["expire_time"] = _read_timestamp(...)`，毫秒），
#:    cline 的导入凭据同键。只认 `expires_at` 会让这两个产品的倒计时恒"未知"（实测盘上形态取证）。
_EXPIRY_KEYS = ("expires_at", "expiresAt", "expire_time", "token_expires_at", "expires")
#: JWT 形态的令牌字段（cline 的 `access_token` 带 `workos:` 前缀；zcode 用 `zcodejwttoken`）
_TOKEN_KEYS = ("access_token", "token", "zcodejwttoken")


def _ms_from_number(value: float) -> int | None:
    """秒/毫秒二义性：>1e12 视为毫秒，其余视为秒（10 位秒 / 13 位毫秒的同一判据）。"""
    if value <= 0:
        return None
    return round(value) if value > 1e12 else round(value * 1000)


def _ms_from_str(raw: str) -> int | None:
    text = raw.strip()
    if not text:
        return None
    if text.isdigit():
        return _ms_from_number(int(text))
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    return round(parsed.timestamp() * 1000)


def _jwt_exp_ms(token: str) -> int | None:
    """JWT payload 的 `exp`（秒）→ 毫秒；**不校验签名**。非 JWT / 无 exp → None。"""
    token = token.removeprefix("workos:")
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode()))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    exp = data.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)) or exp <= 0:
        return None
    return round(exp * 1000)


def credential_expiry_ms(cred: object) -> int | None:
    """凭据（credentials.json 的 dict）→ 登录态失效时刻（毫秒）；解析不出 → `None`。"""
    if not isinstance(cred, dict):
        return None
    for key in _EXPIRY_KEYS:
        value = cred.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            ms = _ms_from_number(float(value))
        elif isinstance(value, str):
            ms = _ms_from_str(value)
        else:
            continue
        if ms:
            return ms
    for key in _TOKEN_KEYS:
        token = cred.get(key)
        if isinstance(token, str) and token:
            ms = _jwt_exp_ms(token)
            if ms:
                return ms
    return None


def credential_expires_at_iso(cred: object) -> str:
    """同上，产出 ISO 文本（管理端视图字段 `credential_expires_at`；取不到 = 空串）。"""
    ms = credential_expiry_ms(cred)
    if not ms:
        return ""
    return dt.datetime.fromtimestamp(ms / 1000).isoformat(timespec="seconds")
