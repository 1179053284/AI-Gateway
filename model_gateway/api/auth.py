"""访问密钥中间件（tech-design §4.1 / PRD FR-10；Q18-① 管理端免鉴权）。

- 纯 ASGI 中间件（不用 BaseHTTPMiddleware：其包装会破坏 StreamingResponse
  的客户端断连取消传播——本项目取消透传的生命线，tech §4.6）
- 仅 /v1/* 需接入密钥：Authorization: Bearer <token>（OpenAI 惯例）/ x-api-key（Anthropic）
- /health 与 /admin/api/* 免鉴权（自用本地系统，Q18-①：管理界面与 Admin API 直连）
- 未配置任何密钥时 /v1 亦放行（附运行警告）
- 错误体按入站协议：/v1/messages → Anthropic 格式；其余 → OpenAI 格式（INT-14）
"""

from __future__ import annotations

import json

EXEMPT_PREFIXES = ("/health", "/admin/")
ANTHROPIC_PREFIX = "/v1/messages"


def _openai_error(status: int, message: str, err_type: str) -> bytes:
    body = {"error": {"message": message, "type": err_type, "code": status}}
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def _anthropic_error(status: int, message: str, err_type: str) -> bytes:
    body = {"type": "error", "error": {"type": err_type, "message": message}}
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


class AuthMiddleware:
    """scope 级鉴权：校验通过后把 token_id 放入 scope["state"]。"""

    def __init__(self, app, runtime_provider):
        # runtime_provider: Callable[[], Runtime]——热重载后取最新密钥配置
        self.app = app
        self._runtime = runtime_provider

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path.startswith(EXEMPT_PREFIXES) or not path.startswith("/v1/"):
            await self.app(scope, receive, send)
            return

        runtime = self._runtime()
        tokens = [t for t in runtime.config.gateway.access_tokens if t.enabled]
        token_id = None
        if tokens:
            value = self._extract_token(scope)
            if value is None:
                await self._deny(scope, receive, send, 401, "缺少接入密钥（Authorization: Bearer 或 x-api-key）",
                                 "authentication_error")
                return
            matched = next((t for t in tokens if t.value == value), None)
            if matched is None:
                await self._deny(scope, receive, send, 401, "接入密钥无效或已停用",
                                 "authentication_error")
                return
            token_id = matched.id

        scope.setdefault("state", {})
        scope["state"]["token_id"] = token_id
        await self.app(scope, receive, send)

    @staticmethod
    def _extract_token(scope) -> str | None:
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            v = auth[7:].strip()
            if v:
                return v
        for key in ("x-api-key", "x-goog-api-key"):
            v = headers.get(key, "")
            if v:
                return v
        return None

    @staticmethod
    async def _deny(scope, receive, send, status: int, message: str, err_type: str) -> None:
        is_anthropic = scope.get("path", "").startswith(ANTHROPIC_PREFIX)
        body = (_anthropic_error(status, message, err_type) if is_anthropic
                else _openai_error(status, message, err_type))
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
