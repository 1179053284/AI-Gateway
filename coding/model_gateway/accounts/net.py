"""公共层的网络与脱敏工具（tech-design v2.0 §22.2 不变式② / §22.8-1、-8）。

🔴 两条纪律：
  ① **所有上游调用**都要有显式超时（§22.8-1：禁止阻塞事件循环的默认无限等待）
     → 统一从这里取客户端，不各产品自己 `httpx.AsyncClient()` 裸建；
  ② 日志/事件里凭据**只以短哈希指纹**出现（§22.2 不变式②，照抄 `23 B4`：
     `SHA256(key)[:6]`）——**不要把 key 尾号/前缀写进日志**（`mask()` 只供界面展示）。
"""

from __future__ import annotations

import hashlib

import httpx

#: 默认超时（显式，`httpx.Timeout` 四段全给）：登录/探活这类交互调用足够宽，
#: 又不至于让"上游不响应"变成无限挂起（§22.8-1）。
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)


def make_client(*, base_url: str = "", headers: dict | None = None,
                timeout: httpx.Timeout | float | None = None,
                follow_redirects: bool = True) -> httpx.AsyncClient:
    """构造带**显式超时**的 `httpx.AsyncClient`（§22.8-1）。

    调用方负责生命周期（`async with` 或 `await aclose()`）；公共层不代持长连接。
    """
    return httpx.AsyncClient(
        base_url=base_url, headers=headers or {},
        timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        follow_redirects=follow_redirects,
    )


def cred_fingerprint(value: str) -> str:
    """凭据的**短哈希指纹**（`SHA256(value)[:6]`，`23 B4`）——日志/事件里唯一的凭据标识。

    取 6 位十六进制：足够在同一份日志里区分几个账号凭据，又不可能反推原文。
    """
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:6]


def mask(value: str, *, head: int = 5, tail: int = 4) -> str:
    """界面展示用的掩码（前 5 + `****` + 后 4，同资源页 Key 规格）。

    ⚠️ 与 `cred_fingerprint` 分工：`mask` 只用于**界面**（用户自己的屏幕上），
    **不进日志**（`23 B4` 明确要求日志里只有短哈希）；值太短时退化为全掩码。
    """
    text = str(value or "")
    if len(text) <= head + tail:
        return "****"
    return f"{text[:head]}****{text[-tail:]}"
