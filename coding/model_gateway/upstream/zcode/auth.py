"""ZCode 双通道鉴权与降级（tech-design v2.0 §17 / `15` §⑧）。

**双通道**（Q27-② 用户"都需要"）：

| 通道 | 凭证 | 头 | 目标端点 |
|---|---|---|---|
| **Plan / JWT** | `zcodejwttoken` | `Authorization: Bearer <jwt>` | `zcode.z.ai/.../zcode-plan/anthropic` |
| **API Key** | 用户自有 Key | `x-api-key: <key>` | `api.z.ai/api/anthropic` |

**三级降级链**（`15` §⑧）::

    JWT + 验证码 → JWT 直连 → API Key 回退

**TLS 指纹**（`15` §⑦）：`zcode.z.ai` 前置 ESA WAF，Go 默认 ClientHello **易被**识别为机器程序
→ 需伪装。Python 侧用 `curl_cffi`；**由本模块统一提供并注入给 `anthropic_out`**
（适配器不直接持 httpx client）。
⚠️ 待实测（§19 T5a 放行 / **T5b async SSE 流式**）；流式不可用时降级为只走 API Key 通道。

**状态判定**：401/403 → invalid；429 → cooling；402/余额不足 → exhausted；
**3012 风控单列**（不立即冷却整号）。
"""

from __future__ import annotations

from dataclasses import dataclass

#: 客户端身份头（联网额度/权益接口必需）
EXTRA_HEADERS = {
    "X-Platform": "darwin",
    "X-Client-Language": "zh-CN",
    "X-Release-Channel": "stable",
}


@dataclass
class Credentials:
    """ZCode 凭据（解密后）。"""

    jwt: str = ""            # zcodejwttoken（Plan 通道）
    api_key: str = ""        # 自有 API Key（API Key 通道）
    device_mid: str = ""     # 设备码（**联网额度接口必需**）
    provider: str = ""       # oauth:active_provider


def looks_like_jwt(value: str | None) -> bool:
    """JWT 形状识别：**不解析 claims**，只按"三段点分 + base64url 字符集"判断（`models.py` 同口径）。"""
    if not isinstance(value, str) or value.count(".") != 2:
        return False
    import re
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", value))


def build_headers(mode: str, creds: Credentials, *, app_version: str = "3.11.2") -> dict:
    """按通道构造鉴权头（§17：**双通道鉴权归本模块**，调用方不再各写一份）。

    - `jwt`   → `Authorization: Bearer <jwt>` + `X-Device-Mid`
    - `apikey`→ `x-api-key: <key>`
    """
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"ZCode/{app_version}",
    }
    if mode == "jwt":
        headers["Authorization"] = f"Bearer {creds.jwt}"
    elif mode == "apikey":
        headers["x-api-key"] = creds.api_key
    if creds.device_mid:
        # 🔴 联网额度接口缺此头 → 400 code=3001（parameter error）
        headers["X-Device-Mid"] = creds.device_mid
    headers.update(EXTRA_HEADERS)
    return headers


# ⚠️ 已删除 `degradation_chain()`（验收修正）：
#    它是**参考项目"适配器内三级降级"**的做法；**我们的架构用「两个资源 + 调度器故障切换」
#    表达降级链**（Plan 通道一个资源、API Key 通道另一个资源，由 `core/scheduler.py` 切换）。
#    在本项目里它属于重复实现 → 按"不过度设计"删除（保留 `build_headers` 供额度/领取路径用）。


def build_client(*, fingerprint: bool = False, timeout: float = 60.0):
    """构造 HTTP 客户端 —— **统一由本模块提供给适配器**（§17 / P1-8）。

    `fingerprint=True` 时尝试 `curl_cffi` 的 Chrome 模拟客户端；
    不可用则**降级**返回普通 `httpx.AsyncClient`（调用方据此决定是否只走 API Key 通道）。

    ⚠️ 待实测（§19 T5a/T5b）：`curl_cffi` 能否过 `zcode.z.ai` 的 WAF、以及 **async SSE 流式**是否可用。
    """
    if fingerprint:
        try:
            from curl_cffi.requests import AsyncSession
            return AsyncSession(impersonate="chrome", timeout=timeout)
        except Exception:  # noqa: BLE001 — 依赖缺失/导入失败 → 降级
            pass
    import httpx
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout))


def fingerprint_available() -> bool:
    """`curl_cffi` 是否可用（§19 T5a/T5b 前置自检）。"""
    try:
        import curl_cffi.requests  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False
