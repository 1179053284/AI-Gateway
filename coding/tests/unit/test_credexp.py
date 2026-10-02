"""`accounts/credexp` 的判据（2026-10-01 用户裁决：登录态失效时刻 = 续期倒计时/自动续期唯一判据）。

钉三件事：
1. **形态矩阵**：毫秒/秒（数字与字符串）、ISO（带/不带时区）全部归一化成毫秒；解析不出 = `None`
   （**不判定过期**，绝不回 0 —— 0 会被读成"1970 年已过期"从而触发无意义的写盘动作）；
2. **JWT 兜底**：无 `expires_at` 字段的产品（cline 的 `workos:` 前缀令牌 / zcode 的
   `zcodejwttoken`）解 payload 的 `exp`；显式字段**优先于** JWT（上游给的值是权威）；
3. `bool` 不当数（`True` 被读成 1 是 JS 的坑，不是我们的语义）。
"""

from __future__ import annotations

import base64
import json
import time

from model_gateway.accounts import credexp


def _jwt(exp: int | None) -> str:
    def b64(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    sig = b64({"sig": "x"})
    payload = b64({"exp": exp} if exp is not None else {"sub": "u"})
    return f"{b64({'alg': 'none'})}.{payload}.{sig}"


def test_number_and_string_shapes_normalize_to_ms():
    now = int(time.time())
    assert credexp.credential_expiry_ms({"expires_at": now * 1000}) == now * 1000
    assert credexp.credential_expiry_ms({"expires_at": str(now * 1000)}) == now * 1000
    assert credexp.credential_expiry_ms({"expires_at": now}) == now * 1000        # 10 位 = 秒
    assert credexp.credential_expiry_ms({"expires_at": str(now)}) == now * 1000
    iso_ms = credexp.credential_expiry_ms({"expires_at": "2026-12-31T10:00:00"})
    assert iso_ms and iso_ms > 1e12, "ISO 串必须归一化成毫秒时间戳"


def test_unparseable_is_none_not_zero():
    """🔴 未知 ≠ 已过期：解析不出一律 `None`（0 会被当成"1970 年到期"触发续期写盘）。"""
    for value in ("", "   ", "not-a-date", 0, -1, True, None, [], {}):
        assert credexp.credential_expiry_ms({"expires_at": value}) is None, value
    assert credexp.credential_expiry_ms({}) is None
    assert credexp.credential_expiry_ms(None) is None
    assert credexp.credential_expires_at_iso({"expires_at": "bad"}) == ""


def test_field_key_variants_are_accepted():
    ms = int(time.time() * 1000) + 60_000
    for key in ("expires_at", "expiresAt", "token_expires_at", "expires"):
        assert credexp.credential_expiry_ms({key: ms}) == ms


def test_qoder_cline_expire_time_key_is_recognized():
    """🔴 盘上取证：qoder/qodercn/cline 的凭据写的是 `expire_time`（不是 expires_at）。
    漏认这个键 = 这两个产品的登录态倒计时永远"未知"（自动续期腿也就永远不触发）。"""
    ms = int(time.time() * 1000) + 3_600_000
    assert credexp.credential_expiry_ms({"expire_time": ms}) == ms
    assert credexp.credential_expiry_ms({"expire_time": str(ms)}) == ms
    s = int(time.time()) + 3_600          # 10 位 = 秒（cline 导入形态按秒给时也要读对）
    assert credexp.credential_expiry_ms({"expire_time": s}) == s * 1000


def test_explicit_field_wins_over_jwt():
    """显式 `expires_at` 是权威值；JWT 只是兜底（两者不一致时取前者）。"""
    ms = int(time.time() * 1000) + 3_600_000
    cred = {"expires_at": ms, "access_token": _jwt(int(time.time()) + 999_999)}
    assert credexp.credential_expiry_ms(cred) == ms


def test_jwt_fallback_covers_workos_prefix_and_bare_token():
    exp_s = int(time.time()) + 7_200
    assert credexp.credential_expiry_ms({"access_token": f"workos:{_jwt(exp_s)}"}) == exp_s * 1000
    assert credexp.credential_expiry_ms({"zcodejwttoken": _jwt(exp_s)}) == exp_s * 1000
    # 非 JWT / 无 exp / 坏 base64 → None（不判定）
    assert credexp.credential_expiry_ms({"access_token": "opaque-token"}) is None
    assert credexp.credential_expiry_ms({"access_token": _jwt(None)}) is None
    assert credexp.credential_expiry_ms({"access_token": "a.b"}) is None


def test_iso_output_is_local_wall_clock():
    """`credential_expires_at_iso` 出本地墙钟 ISO（与 `runtime.quota.checked_at` 同一口径）。"""
    ms = int(time.time() * 1000) + 3_600_000
    iso = credexp.credential_expires_at_iso({"expires_at": ms})
    assert iso and "T" in iso and len(iso) == 19, iso
