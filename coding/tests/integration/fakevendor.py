"""FakeVendor：本地假供应商后端（test-cases.md §1.2）。

- OpenAI 兼容端点：POST /v1/chat/completions（流式/非流式）、POST /v1/images/generations
- 按 key 可编程脚本（按序消费，耗尽后重复最后一步）：
  Ok（成功，可延迟）/ Err（状态码+错误体）/ StreamOk（流式内容）/ Hang（挂起等待取消）
- 记录每个收到的请求（key/path/body/stream）；处理 task 被取消时记录 cancelled
- GET /static/{name}：静态文件（INT-31 image_url 下载源）
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route


@dataclass
class Ok:
    content: str = "ok"
    delay: float = 0.0
    usage: bool = True
    reasoning: str = ""  # 非流式思考文本（thinking_content 风格）
    thinking_style: str = "thinking_content"  # thinking_content | reasoning_content | reasoning
    # 工具调用（INT-121 起）：[{"id","name","arguments"}]；给了就把 finish_reason 设成 tool_calls
    tool_calls: list[dict] | None = None
    usage_extra: dict | None = None  # 并入 usage 的附加字段（cached_tokens / reasoning_tokens）


@dataclass
class Err:
    status: int = 500
    err_type: str = "internal_server_error"
    message: str = "vendor error"
    delay: float = 0.0


@dataclass
class StreamOk:
    chunks: list[str] = field(default_factory=lambda: ["你", "好"])
    delay_first: float = 0.0
    delay_between: float = 0.0
    abort_after: int | None = None  # 输出 N chunk 后硬断连接（中途失败·网络中断）
    err_after: Err | None = None  # 输出全部 chunk 后返回错误体（中途失败·不可重试类）
    reasoning_chunks: list[str] | None = None  # 思考片段（INT-30）
    thinking_style: str = "thinking_content"
    # 工具调用增量帧（按序下发）：[{"index","id"?,"name"?,"arguments"?}]
    tool_call_chunks: list[dict] | None = None
    usage_extra: dict | None = None


@dataclass
class Hang:
    duration: float = 60.0  # 挂起（延迟提交窗口测试；被取消时记录 cancelled）


@dataclass
class _Received:
    key: str
    path: str
    body: dict
    stream: bool
    cancelled: bool = False


class FakeVendor:
    def __init__(self):
        self.script: dict[str, list] = {}
        self.requests: list[_Received] = []
        self.app = Starlette(routes=[
            Route("/v1/chat/completions", self._chat, methods=["POST"]),
            Route("/v1/images/generations", self._images, methods=["POST"]),
            Route("/v1/models", self._models, methods=["GET"]),
            Route("/static/{name}", self._static, methods=["GET"]),
        ])

    # —— 脚本注入 ——
    def set(self, key: str, *steps) -> None:
        assert steps, "至少一个步骤（耗尽后重复最后一步）"
        self.script[key] = list(steps)

    # —— 记录查询 ——
    def calls_for(self, key: str) -> list[_Received]:
        return [r for r in self.requests if r.key == key]

    def bodies_for(self, key: str) -> list[dict]:
        return [r.body for r in self.calls_for(key)]

    @property
    def cancelled_keys(self) -> list[str]:
        return [r.key for r in self.requests if r.cancelled]

    def reset(self) -> None:
        self.script.clear()
        self.requests.clear()

    # —— 内部 ——
    def _key(self, request: Request) -> str:
        auth = request.headers.get("authorization", "")
        return auth.removeprefix("Bearer ").strip() or "(none)"

    async def _sleep_or_disconnect(self, request: Request, seconds: float) -> None:
        """延迟/挂起期间监测连接断开：网关关闭上游连接（取消透传）→ 模拟真实
        上游的在途生成被中断（uvicorn 不会主动取消非流式 app task，须轮询探测）。"""
        loop = asyncio.get_running_loop()
        end = loop.time() + seconds
        while True:
            remaining = end - loop.time()
            if remaining <= 0:
                return
            await asyncio.sleep(min(0.05, remaining))
            if await request.is_disconnected():
                raise asyncio.CancelledError()

    async def _next(self, key: str):
        steps = self.script.get(key)
        if not steps:
            return Ok()
        if len(steps) > 1:
            return steps.pop(0)
        return steps[0]  # 仅剩最后一步 → 重复消费（恒定行为）

    async def _chat(self, request: Request) -> Response:
        key = self._key(request)
        body = await request.json()
        rec = _Received(key, request.url.path, body, bool(body.get("stream")))
        self.requests.append(rec)
        step = await self._next(key)
        try:
            if isinstance(step, Hang):
                await self._sleep_or_disconnect(request, step.duration)
                return self._ok_json(Ok())
            if isinstance(step, Err):
                if step.delay:
                    await asyncio.sleep(step.delay)
                return JSONResponse(status_code=step.status, content={"error": {
                    "message": step.message, "type": step.err_type, "code": step.status}})
            if isinstance(step, (Ok, StreamOk)) and body.get("stream"):
                return self._stream_response(step, rec)
            if isinstance(step, Ok):
                if step.delay:
                    await self._sleep_or_disconnect(request, step.delay)
                return JSONResponse(self._ok_json(step))
            return JSONResponse(self._ok_json(Ok()))
        except asyncio.CancelledError:
            rec.cancelled = True
            raise

    def _ok_json(self, step: Ok) -> dict:
        message: dict = {"role": "assistant", "content": step.content}
        if step.reasoning:
            message[step.thinking_style] = step.reasoning
        finish = "stop"
        if step.tool_calls:
            message["tool_calls"] = [
                {"id": tc.get("id") or f"call_{i}", "type": "function",
                 "function": {"name": tc.get("name", ""), "arguments": tc.get("arguments", "")}}
                for i, tc in enumerate(step.tool_calls)]
            finish = "tool_calls"
        data = {
            "id": "chatcmpl-fake", "object": "chat.completion", "model": "vendor-model",
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        }
        if step.usage:
            usage = {"prompt_tokens": 10, "completion_tokens": 5}
            usage.update(step.usage_extra or {})
            data["usage"] = usage
        return data

    def _stream_response(self, step, rec) -> StreamingResponse:
        async def gen():
            try:
                async for ev in _gen_body(step):
                    yield ev
            except asyncio.CancelledError:
                rec.cancelled = True
                raise

        async def _gen_body(step):
            async def send_event(payload: dict | str):
                data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
                yield f"data: {data}\n\n"

            s = step
            if isinstance(s, Ok):
                s = StreamOk(chunks=[s.content], delay_first=s.delay,
                             reasoning_chunks=([s.reasoning] if s.reasoning else None),
                             thinking_style=s.thinking_style,
                             tool_call_chunks=([
                                 {"index": i, "id": tc.get("id"), "name": tc.get("name"),
                                  "arguments": tc.get("arguments")}
                                 for i, tc in enumerate(s.tool_calls)]
                                 if s.tool_calls else None),
                             usage_extra=s.usage_extra)
            if s.delay_first:
                await asyncio.sleep(s.delay_first)
            first = {"id": "chatcmpl-fake", "object": "chat.completion.chunk", "model": "vendor-model",
                     "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
            async for ev in send_event(first):
                yield ev
            n = 0
            if s.reasoning_chunks:
                for rc in s.reasoning_chunks:
                    delta: dict = {s.thinking_style: rc}
                    chunk = {"id": "chatcmpl-fake", "object": "chat.completion.chunk",
                             "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
                    async for ev in send_event(chunk):
                        yield ev
            for text in s.chunks:
                if s.abort_after is not None and n >= s.abort_after:
                    # 模拟网络中断：已在响应途中，raise 让 uvicorn 硬断连接（RST 语义）
                    # abort_after=0 → 首个内容 chunk 前即断（首帧前中断场景）
                    raise ConnectionResetError("vendor simulated network abort")
                chunk = {"id": "chatcmpl-fake", "object": "chat.completion.chunk",
                         "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}
                async for ev in send_event(chunk):
                    yield ev
                n += 1
                if s.delay_between:
                    await asyncio.sleep(s.delay_between)
            if s.abort_after is not None and n >= s.abort_after:
                # chunks 耗尽且恰在中断点：连接在 N chunk 后硬断（不发收尾帧/usage/[DONE]）
                raise ConnectionResetError("vendor simulated network abort")
            if s.err_after is not None:
                # 输出完内容后返回错误体（HTTP 层在流中间无法换状态码 → 用 SSE error 帧模拟）
                err = {"error": {"message": s.err_after.message,
                                 "type": s.err_after.err_type, "code": s.err_after.status}}
                async for ev in send_event(err):
                    yield ev
                return
            for tc in s.tool_call_chunks or []:
                entry: dict = {"index": tc.get("index", 0)}
                if tc.get("id"):
                    entry["id"] = tc["id"]
                fn: dict = {}
                if tc.get("name"):
                    fn["name"] = tc["name"]
                if tc.get("arguments"):
                    fn["arguments"] = tc["arguments"]
                if fn:
                    entry["function"] = fn
                chunk = {"id": "chatcmpl-fake", "object": "chat.completion.chunk",
                         "choices": [{"index": 0, "delta": {"tool_calls": [entry]},
                                      "finish_reason": None}]}
                async for ev in send_event(chunk):
                    yield ev
            final = {"id": "chatcmpl-fake", "object": "chat.completion.chunk",
                     "choices": [{"index": 0, "delta": {},
                                  "finish_reason": "tool_calls" if s.tool_call_chunks else "stop"}]}
            async for ev in send_event(final):
                yield ev
            usage_payload = {"prompt_tokens": 10, "completion_tokens": 5}
            usage_payload.update(s.usage_extra or {})
            usage = {"id": "chatcmpl-fake", "usage": usage_payload}
            async for ev in send_event(usage):
                yield ev
            async for ev in send_event("[DONE]"):
                yield ev

        return StreamingResponse(gen(), media_type="text/event-stream",
                                headers={"Cache-Control": "no-cache"})

    async def _images(self, request: Request) -> Response:
        key = self._key(request)
        body = await request.json()
        rec = _Received(key, request.url.path, body, False)
        self.requests.append(rec)
        step = await self._next(key)
        try:
            if isinstance(step, Err):
                return JSONResponse(status_code=step.status, content={"error": {
                    "message": step.message, "type": step.err_type, "code": step.status}})
            if isinstance(step, Hang):
                await asyncio.sleep(step.duration)
            fmt = body.get("response_format", "b64_json")
            item = {"url": f"http://vendor/static/img_{len(self.requests)}.png"} if fmt == "url" \
                else {"b64_json": "aGVsbG8="}
            return JSONResponse({"created": 0, "data": [item]})
        except asyncio.CancelledError:
            rec.cancelled = True
            raise

    async def _models(self, request: Request) -> Response:
        return JSONResponse({"object": "list", "data": [
            {"id": "vendor-model", "object": "model"}]})

    async def _static(self, request: Request) -> Response:
        name = request.path_params["name"]
        return Response(content=b"\x89PNG-fake-image-bytes", media_type="image/png",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})


def start_fake_vendor(vendor: FakeVendor):
    """在随机端口起 uvicorn；返回 (server_task, get_port)。"""
    import uvicorn
    config = uvicorn.Config(vendor.app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)

    async def run():
        await server.serve()

    task = asyncio.get_running_loop().create_task(run())

    async def wait_ready():
        for _ in range(500):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started, "FakeVendor 启动超时"
        return server.servers[0].sockets[0].getsockname()[1]

    return server, task, wait_ready
