"""Loomy 业务请求基建（`API_BASE` 之下的所有请求都经这里）。

🔴 **唯一**的客户端构造点 → 单测只需替换本模块的 `make_client` 就能覆盖全部业务调用
   （`credits.py` / `models.py` 都经 `api.request` 发请求）。
🔴 业务失败**恒 HTTP 200**（`loomy.ts:80-85`）→ 一律返回 `(status, body)` 由调用方拆封套
   （`envelope.parse`），**不看状态码判成败**。
"""

from __future__ import annotations

from model_gateway.accounts.net import make_client  # 可被单测替换（monkeypatch 本模块属性）
from model_gateway.upstream.loomy import constants as C


def business_headers(token: str) -> dict[str, str]:
    """业务端点请求头（`loomy.ts:213-215`）。

    ⚠️ 这些端点（`/models`、`/points/*`、`/onboarding/*`）**只认小写 `token` 头**，
       带 `Authorization: Bearer` 会被判「缺少 token」→ 这里刻意**不加** Authorization。
    """
    return {"Accept": "application/json", "token": token}


def access_token_of(cred: dict | None) -> str:
    """取凭据里的 `access_token`（讯飞 32 位小写 hex `session`；`loomy.ts:54-58`）。"""
    value = (cred or {}).get("access_token")
    return value if isinstance(value, str) else ""


async def request(method: str, path: str, *, token: str, body: dict | None = None,
                  timeout: float | None = None) -> tuple[int, object | None]:
    """发一次业务请求并尽力解析 JSON：返回 `(status, body|None)`。

    🔴 不用 `response.json()` 直接判失败（同 buddy 的 `_request` 口径）：失败响应可能是
       HTML/空体，`json()` 抛出的 `Unexpected token '<'` 对用户毫无意义 → 吞掉解析异常回
       `None`，由调用方带上 HTTP 状态码给出可读原因。网络异常**照常抛出**（由各钩子 folding）。
    """
    async with make_client(base_url=C.API_BASE,
                           timeout=timeout if timeout is not None else C.REQUEST_TIMEOUT_S) as client:
        response = await client.request(method, path, headers=business_headers(token), json=body)
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, None
