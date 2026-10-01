"""ZCode 凭据加解密：`enc:v1`（tech-design v2.0 §17 / `19` §6.3）。

**格式**（参考实现逆向所得，`12` §3.1）::

    enc:v1:<b64url(nonce 12B)>.<b64url(authTag 16B)>.<b64url(ciphertext)>

**算法**：AES-256-GCM，`key = SHA256(secret)`

**secret 来源**（按优先级）::
    1. 环境变量 `ZCODE_CREDENTIAL_SECRET`
    2. `zcode-credential-fallback:{platform}:{homedir}:{username}`

⚠️ 两个已知坑（`12` §3.1）：
  - secret **绑定平台+家目录+用户名** → 换机器/换用户名即解不开历史凭据
  - 三份参考实现的 `username` 取值口径**各不相同**（`id -un` / `$USER` / `os.userInfo()`）
    → **必须实测本机上哪个对**（§19 T3）

**非 `enc:v1` 前缀的值一律原样返回**（明文兼容）。
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

PREFIX = "enc:v1:"


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def fallback_secret(*, platform: str | None = None, home: str | None = None,
                    username: str | None = None) -> str:
    """构造回退 secret：`zcode-credential-fallback:{platform}:{home}:{username}`。

    `username` 的取值顺序（防御三个参考实现口径不一致）：
    `os.environ["USER"]` → `getpass.getuser()` → `os.environ["LOGNAME"]` → 空串。
    ⚠️ 到底哪个与本机 ZCode 客户端一致 —— **必须实测**（§19 T3）。
    """
    plat = platform or _platform()
    home_dir = home or str(Path.home())
    user = username if username is not None else _username()
    return f"zcode-credential-fallback:{plat}:{home_dir}:{user}"


def _platform() -> str:
    return {"darwin": "darwin", "win32": "win32", "linux": "linux"}.get(
        os.sys.platform, os.sys.platform)


def _username() -> str:
    for getter in (
        lambda: os.environ.get("USER") or "",
        lambda: os.environ.get("LOGNAME") or "",
        _getpass_user,
    ):
        try:
            v = getter()
        except Exception:  # noqa: BLE001 — 用户名探测尽最大努力
            continue
        if v:
            return v
    return ""


def _getpass_user() -> str:
    import getpass
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return ""


def derive_key(secret: str) -> bytes:
    """`key = SHA256(secret)`（32 字节，AES-256）。"""
    return hashlib.sha256(secret.encode("utf-8")).digest()


def current_secret() -> str:
    """当前生效的 secret：环境变量优先，否则回退式。"""
    env = os.environ.get("ZCODE_CREDENTIAL_SECRET")
    if env:
        return env
    return fallback_secret()


def decrypt(value: str, *, secret: str | None = None) -> str:
    """解密 `enc:v1:...`；非该前缀**原样返回**。

    解密失败（tag 校验不过 / 格式不对 / 依赖缺失）→ **返回空串并静默降级**
    （与参考实现 `safeDecrypt` 同口径：表现为"账号显示但信息空白"，不崩）。
    """
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value or ""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:  # pragma: no cover — 依赖缺失时不崩，降级为空
        return ""
    body = value[len(PREFIX):]
    parts = body.split(".")
    if len(parts) != 3:
        return ""
    try:
        nonce = _b64url_decode(parts[0])
        tag = _b64url_decode(parts[1])
        ct = _b64url_decode(parts[2])
        # 🔴 参考实现：Rust/JS 输出 `ct || tag` → 解密前**拼接**回去
        aes = AESGCM(derive_key(secret or current_secret()))
        plain = aes.decrypt(nonce, ct + tag, None)
        return plain.decode("utf-8")
    except Exception:  # noqa: BLE001 — 静默降级（同参考实现）
        return ""


def encrypt(plain: str, *, secret: str | None = None) -> str:
    """加密为 `enc:v1:...`（写回 ZCode 凭据文件时需要）。

    加密失败 → 抛异常（**不静默** —— 写入侧静默失败会产出不可读凭据）。
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    aes = AESGCM(derive_key(secret or current_secret()))
    nonce = os.urandom(12)
    sealed = aes.encrypt(nonce, plain.encode("utf-8"), None)
    # sealed = ct || tag（16B）
    ct, tag = sealed[:-16], sealed[-16:]
    return PREFIX + ".".join((_b64url_encode(nonce), _b64url_encode(tag),
                              _b64url_encode(ct)))

