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

import httpx

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


def _translate_curl_error(e: Exception) -> Exception:
    """curl_cffi 异常 → httpx 等价异常（调度器的捕获面只认 httpx 那套）。

    🔴 2026-10-07 23:10 实盘抓到的真缺陷：curl_cffi 的异常树独立于 httpx，
    而 `anthropic_out` 只捕获 `httpx.TimeoutException` / `httpx.HTTPError`
    ⇒ curl_cffi 的超时/网络异常**裸穿**成无分类异常：不记 C、不换号、
    `error_summary` 空、`ttft_ms=null`（两条 21.3s 流式请求的形状）。
    """
    try:
        from curl_cffi.requests import exceptions as cex
    except Exception:  # noqa: BLE001 — curl_cffi 不可用时理论上不可达
        return e
    if isinstance(e, cex.Timeout):
        return httpx.ReadTimeout(str(e))
    if isinstance(e, cex.RequestException):
        return httpx.TransportError(str(e))
    return e


class _CurlCffiResponse:
    """curl_cffi `Response` 的 httpx 风格薄包装（只覆盖出站适配器用到的面）。

    🔴 为什么必须包（2026-10-07 T5b 实测，装上 curl_cffi 后暴露的真缝）：
    - `aiter_lines()` 产出 **bytes**（httpx 产出 str）—— `parse_sse_line` 按
      str 写（`line.startswith("event:")`），bytes 直传必 TypeError；
    - 无 `aread()`（curl_cffi 叫 `acontent()`）—— 流式错误路径读体用 `aread`。
    """

    __slots__ = ("_r",)

    def __init__(self, r) -> None:
        self._r = r

    @property
    def status_code(self) -> int:
        return self._r.status_code

    @property
    def headers(self):
        return self._r.headers

    @property
    def text(self) -> str:
        return self._r.text

    def json(self):
        return self._r.json()

    async def aread(self) -> bytes:
        data = self._r.acontent()
        if hasattr(data, "__await__"):
            data = await data
        return data or b""

    async def aiter_lines(self):
        try:
            async for line in self._r.aiter_lines():
                if isinstance(line, (bytes, bytearray)):
                    line = line.decode(self._r.encoding or "utf-8", "replace")
                yield line
        except Exception as e:  # noqa: BLE001 — 流中途断连在此抛出（必须翻译）
            raise _translate_curl_error(e) from e


class _CurlCffiStream:
    """curl_cffi `stream()` 上下文的 httpx 风格薄包装。

    🔴 异常翻译与 `CurlCffiClient` 同源（`__aenter__` 的建连超时、迭代期的读超时
    都必须变成 httpx 类型，否则调度器捕获不到 —— 见 `CurlCffiClient` docstring）。
    """

    __slots__ = ("_session", "_method", "_url", "_kwargs", "_cm")

    def __init__(self, session, method: str, url: str, kwargs: dict) -> None:
        self._session = session
        self._method = method
        self._url = url
        self._kwargs = kwargs
        self._cm = None

    async def __aenter__(self) -> _CurlCffiResponse:
        self._cm = self._session.stream(self._method, self._url, **self._kwargs)
        try:
            raw = await self._cm.__aenter__()
        except Exception as e:  # noqa: BLE001 — 翻译后重抛
            raise _translate_curl_error(e) from e
        return _CurlCffiResponse(raw)

    async def __aexit__(self, *exc) -> bool:
        return await self._cm.__aexit__(*exc)


class CurlCffiClient:
    """curl_cffi `AsyncSession` 的 httpx 风格适配（`anthropic_out` 只用 post/stream/aclose）。

    TLS 指纹伪装的**唯一**客户端形态；接口差异在此收口，出站适配器零感知。

    🔴 **异常类型也必须收口**（2026-10-07 23:10 实盘抓到的真缺陷）：curl_cffi 的
    异常树独立于 httpx（`curl_cffi.requests.exceptions.RequestException` 为基类，
    `Timeout` 为超时基类），而 `anthropic_out` 的流式/非流式只捕获
    `httpx.TimeoutException` / `httpx.HTTPError` ⇒ curl_cffi 抛出的超时/网络异常
    **裸穿**成无分类异常：不记 C、不换号、`error_summary` 空、`ttft_ms=null`，
    事件行只留 `status=failed`（实盘两条 21.3s 流式请求的形状）。
    这里把 curl_cffi 异常**翻译成 httpx 等价类型**，让适配器既有的分类/重试/换号
    机器照常工作（读超时 → `ReadTimeout` → RETRYABLE → 换号）。
    """

    def __init__(self, session) -> None:
        self._s = session

    async def post(self, url: str, *, headers=None, content=None, timeout=None):
        try:
            r = await self._s.post(url, headers=headers, content=content, timeout=timeout)
        except Exception as e:  # noqa: BLE001 — 翻译后重抛（见类 docstring）
            raise _translate_curl_error(e) from e
        return _CurlCffiResponse(r)

    def stream(self, method: str, url: str, *, headers=None, content=None, timeout=None):
        return _CurlCffiStream(self._s, method, url,
                               {"headers": headers, "content": content, "timeout": timeout})

    async def aclose(self) -> None:
        # 🔴 AsyncSession.close 是**协程**（2026-10-07 实测 `RuntimeWarning:
        # coroutine ... was never awaited`；同步调用只创建协程不关连接）
        await self._s.close()


def build_client(*, fingerprint: bool = False, timeout: float = 60.0):
    """构造 HTTP 客户端 —— **统一由本模块提供给适配器**（§17 / P1-8）。

    `fingerprint=True` 时返回 `CurlCffiClient`（curl_cffi Chrome 模拟 +
    httpx 风格薄包装）；不可用则**降级**返回普通 `httpx.AsyncClient`。

    ✅ T5a/T5b 已实测（2026-10-07 19:4x）：curl_cffi 连通 `zcode.z.ai`
    （GET 200 / POST 401-JSON，无 WAF HTML）；async SSE 流式经本地假上游
    验证 `stream`/`aiter_lines`/`content=` 全兼容（bytes→str 在包装层归一）。
    """
    if fingerprint:
        try:
            from curl_cffi.requests import AsyncSession
            return CurlCffiClient(AsyncSession(impersonate="chrome", timeout=timeout))
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
