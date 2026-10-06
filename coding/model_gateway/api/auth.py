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


def _client_is_loopback(scope) -> bool:
    """客户端（不是监听地址）是否回环：S-5 完整版的判定基元。"""
    client = scope.get("client")
    host = client[0] if client else ""
    return host in ("127.0.0.1", "::1", "localhost", "")

class AdminLanGuard:
    """🔴 S-5 完整版（2026-10-06 架构审计核验轮）：管理面**局域网收口**。

    免鉴权是按「自用本地系统」裁定的（本模块头部原话）；`host` 显式开放到
    `0.0.0.0` 时这个前提对同网段设备不再成立 ⇒ 三类**敏感管理面**对非回环
    客户端 403（判定书 §4-1 原话「开关内把 reveal/写面/resources/test 收口」）：
      1. `?reveal=1`（接入密钥明文出口——S-5 的核心暴露物）；
      2. `/admin/api/*` 的写方法（POST/PUT/DELETE——含 PUT config 全量覆盖写面）；
      3. `POST /admin/api/resources/test`（会拿用户 Key 真实出站探测）。
    `gateway.lan_admin_open: true` 是显式逃生门（打开 = 声明同网段设备可信）；
    回环客户端零变化；GET（不 reveal）照常放行——局域网只读视图无密钥泄露面。
    纯 ASGI、不引 BaseHTTPMiddleware（同 AuthMiddleware 的取消传播理由）。
    """

    _WRITE_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})

    def __init__(self, app, runtime_provider):
        self.app = app
        self._runtime = runtime_provider

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").startswith("/admin/"):
            # 🔴 守卫自身必须防弹：runtime 缺失 / config 读不动（BD3a 判据钉的形状，
            #    test_m7_backend_preconditions 实测抓到）都不许冒穿成 500——
            #    降级 = 不收口，放行给下游（视图有自己的 fail-closed 兜底）。
            try:
                runtime = self._runtime()
                gw = getattr(runtime.config, "gateway", None)
                denied = self._should_deny(scope, gw)
            except Exception:  # noqa: BLE001 — 守卫永不对正常流量加害
                denied = False
            if denied:
                body = json.dumps(
                    {"detail": "管理面仅限本机（回环）访问：host 已开放到非回环地址；"
                               "要从局域网设备管理请把 gateway.lan_admin_open 设为 true"},
                    ensure_ascii=False).encode("utf-8")
                await send({
                    "type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())],
                })
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)

    @staticmethod
    def _should_deny(scope, gw) -> bool:
        """True = 本请求必须 403。gw 不可用（None / 抛错）一律不拦（见 __call__ 的 try）。"""
        if gw is None or gw.lan_admin_open:
            return False
        # 🔴 括号不可省：`a or b in c` 会被解析成 `a or (b in c)`——host 为真值时
        #    整个表达式返回 host 本身（truthy）⇒ 守卫永不触发（核验轮实测抓到）。
        host_is_loopback = ((getattr(gw, "host", "") or "")
                            in ("127.0.0.1", "::1", "localhost", ""))
        if host_is_loopback or _client_is_loopback(scope):
            return False  # 回环监听 or 回环客户端：零变化
        sensitive = (
            ("reveal=1" in scope.get("query_string", b"").decode("latin-1"))
            or scope.get("method", "GET") in AdminLanGuard._WRITE_METHODS
            or scope.get("path", "") == "/admin/api/resources/test")
        return sensitive
