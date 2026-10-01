"""FakeAnthropic：本地假 **Anthropic Messages** 上游（v2.0 §18 / M4-1 验收用）。

只实现网关真正会调的一条路径：`POST /v1/messages`（非流式 / SSE 流式），
响应体按 Anthropic Messages 真实结构返回（`content[]` blocks、`stop_reason`、
`usage.input_tokens/output_tokens`、SSE `event:`+`data:` 成对）。

判据（§19 M4-1）：**假 Anthropic 上游可完全 mock** → 完成一次 chat。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route


@dataclass
class Resp:
    """可编程非流式响应。"""

    text: str = "ok"
    thinking: str = ""
    stop_reason: str = "end_turn"
    input_tokens: int = 10
    output_tokens: int = 4
    status: int = 200
    #: 返回 HTML（模拟 WAF 挑战页 / 登录页）→ 触发 2xx 非 JSON 分支
    html_body: str | None = None
    tool_use: list[dict] | None = None


@dataclass
class StreamResp:
    """可编程流式响应（Anthropic 事件序列）。"""

    texts: list[str] = field(default_factory=lambda: ["你", "好"])
    thinkings: list[str] | None = None
    tool: dict | None = None          # {"id","name","input_json"}
    stop_reason: str = "end_turn"
    input_tokens: int = 10
    output_tokens: int = 7
    status: int = 200
    html_body: str | None = None
    err_after: str | None = None      # 输出全部后发一个 error 事件


class FakeAnthropic:
    def __init__(self):
        self.requests: list[dict] = []
        self.script: list[Resp | StreamResp] = []
        self._i = 0
        self.app = Starlette(routes=[Route("/v1/messages", self.messages, methods=["POST"])])

    def enqueue(self, *items):
        self.script.extend(items)
        return self

    def _next(self):
        if not self.script:
            return Resp()
        i = min(self._i, len(self.script) - 1)
        self._i += 1
        return self.script[i]

    async def messages(self, request: Request):
        body = await request.json()
        self.requests.append({
            "path": request.url.path,
            "headers": dict(request.headers),
            "body": body,
        })
        item = self._next()

        if item.html_body:
            return JSONResponse({}, status=200) if False else _html(item.status, item.html_body)

        if isinstance(item, StreamResp):
            return StreamingResponse(
                self._stream(item), media_type="text/event-stream", status_code=item.status)

        if item.status != 200:
            return JSONResponse({
                "type": "error",
                "error": {"type": "invalid_request_error", "message": "vendor error"},
            }, status_code=item.status)

        content = []
        if item.thinking:
            content.append({"type": "thinking", "thinking": item.thinking})
        for t in (item.tool_use or []):
            content.append(t)
        content.append({"type": "text", "text": item.text})
        return JSONResponse({
            "id": "msg_fake", "type": "message", "role": "assistant",
            "model": body.get("model", ""),
            "content": content,
            "stop_reason": item.stop_reason,
            "usage": {"input_tokens": item.input_tokens, "output_tokens": item.output_tokens},
        })

    async def _stream(self, s: StreamResp):
        def ev(name: str, data: dict) -> bytes:
            return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode("utf-8")

        yield ev("message_start", {"type": "message_start",
                                   "message": {"id": "msg_fake", "usage": {"input_tokens": s.input_tokens}}})
        idx = 0
        for th in (s.thinkings or []):
            yield ev("content_block_start", {"type": "content_block_start", "index": idx,
                                             "content_block": {"type": "thinking"}})
            yield ev("content_block_delta", {"type": "content_block_delta", "index": idx,
                                             "delta": {"type": "thinking_delta", "thinking": th}})
            yield ev("content_block_stop", {"type": "content_block_stop", "index": idx})
            idx += 1

        if s.tool is not None:
            yield ev("content_block_start", {"type": "content_block_start", "index": idx,
                                             "content_block": {"type": "tool_use",
                                                               "id": s.tool["id"],
                                                               "name": s.tool["name"]}})
            yield ev("content_block_delta", {"type": "content_block_delta", "index": idx,
                                             "delta": {"type": "input_json_delta",
                                                       "partial_json": s.tool.get("input_json", "")}})
            yield ev("content_block_stop", {"type": "content_block_stop", "index": idx})
            idx += 1

        yield ev("content_block_start", {"type": "content_block_start", "index": idx,
                                         "content_block": {"type": "text"}})
        for t in s.texts:
            yield ev("content_block_delta", {"type": "content_block_delta", "index": idx,
                                             "delta": {"type": "text_delta", "text": t}})
        yield ev("content_block_stop", {"type": "content_block_stop", "index": idx})

        yield ev("message_delta", {"type": "message_delta",
                                   "delta": {"stop_reason": s.stop_reason},
                                   "usage": {"output_tokens": s.output_tokens}})
        if s.err_after:
            yield ev("error", {"type": "error",
                               "error": {"type": "overloaded_error", "message": s.err_after}})
        yield ev("message_stop", {"type": "message_stop"})


def _html(status: int, body: str):
    from starlette.responses import Response
    return Response(content=body, status=status, media_type="text/html")


def start_fake_anthropic(vendor: FakeAnthropic):
    """在随机端口起 uvicorn；返回 (server, task, wait_ready)。"""
    import uvicorn

    config = uvicorn.Config(vendor.app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.get_event_loop().create_task(server.serve())

    async def wait_ready():
        for _ in range(500):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started, "FakeAnthropic 启动超时"
        return server.servers[0].sockets[0].getsockname()[1]

    return server, task, wait_ready
