"""Anthropic 原生入站 /v1/messages（tech-design §4.1，M1 任务 7）。

IR 双向转换（透传优先，只做协议间必需的语义映射）：
- 请求：Anthropic blocks（text/image/tool_use/tool_result/thinking）→ OpenAI 形
- 非流式响应：OpenAI message（content/reasoning_content/tool_calls）→ Anthropic content 块
- 流式：OpenAI chunk delta → Anthropic SSE 事件（message_start/content_block_*/
  message_delta/message_stop + ping 心跳）
"""

from __future__ import annotations

import asyncio
import contextlib
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from model_gateway.core.cancel import DisconnectWatcher
from model_gateway.core.ir import IRRequest, ReasoningSpec
from model_gateway.core.scheduler import ERROR_EVENT, CallCtx, GatewayError
from model_gateway.enums.matcher import resolve_request_model

router = APIRouter()

_STOP_REASON_MAP = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "refusal",
    None: "end_turn",
}


def _anthropic_error(status: int, err_type: str, message: str,
                     code: str | None = None) -> JSONResponse:
    err: dict = {"type": err_type, "message": message}
    if code is not None:
        err["code"] = code
    return JSONResponse(status_code=status, content={"type": "error", "error": err})


# —— 请求转换：Anthropic → OpenAI 形 ——

def _blocks_to_text(blocks) -> str:
    if isinstance(blocks, str):
        return blocks
    out = []
    for b in blocks or []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text", ""))
    return "\n".join(out)


def anthropic_to_openai(body: dict) -> tuple[dict, ReasoningSpec | None]:
    """Anthropic /v1/messages 请求体 → OpenAI 形 body + 推理显式值（Q15）。"""
    out: dict = {}
    messages: list[dict] = []

    system = body.get("system")
    if system:
        text = system if isinstance(system, str) else _blocks_to_text(system)
        if text:
            messages.insert(0, {"role": "system", "content": text})

    for m in body.get("messages", []) or []:
        role = m.get("role", "user")
        content = m.get("content")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        if role == "assistant":
            text_parts: list[str] = []
            thinking_parts: list[str] = []
            tool_calls: list[dict] = []
            for b in content or []:
                if not isinstance(b, dict):
                    continue
                t = b.get("type")
                if t == "text":
                    text_parts.append(b.get("text", ""))
                elif t == "thinking":
                    thinking_parts.append(b.get("thinking", ""))
                elif t == "tool_use":
                    tool_calls.append({
                        "id": b.get("id"), "type": "function",
                        "function": {"name": b.get("name", ""),
                                     "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)},
                    })
            msg: dict = {"role": "assistant"}
            if thinking_parts:
                msg["reasoning_content"] = "\n".join(thinking_parts)
            if text_parts:
                msg["content"] = "\n".join(text_parts)
            if tool_calls:
                msg["tool_calls"] = tool_calls
            if len(msg) == 1:
                msg["content"] = ""  # 空 assistant 消息兜底
            messages.append(msg)
        else:  # user
            parts: list[dict] = []
            tool_results: list[dict] = []
            for b in content or []:
                if not isinstance(b, dict):
                    continue
                t = b.get("type")
                if t == "text":
                    parts.append({"type": "text", "text": b.get("text", "")})
                elif t == "image":
                    src = b.get("source") or {}
                    if src.get("type") == "base64":
                        media = src.get("media_type", "image/png")
                        parts.append({"type": "image_url",
                                      "image_url": {"url": f"data:{media};base64,{src.get('data', '')}"}})
                    elif src.get("url"):
                        parts.append({"type": "image_url", "image_url": {"url": src["url"]}})
                elif t == "tool_result":
                    inner = b.get("content")
                    text = inner if isinstance(inner, str) else _blocks_to_text(inner)
                    tool_results.append({"role": "tool",
                                         "tool_call_id": b.get("tool_use_id"),
                                         "content": text or ""})
            if parts:
                messages.append({"role": "user", "content": parts})
            messages.extend(tool_results)

    out["messages"] = messages
    if body.get("stream"):
        out["stream"] = True  # 出站体必须显式带 stream（供应商按 body 判定；E2E 实测：
        # 缺失时商汤返回非流式 JSON，chat_stream 的 SSE 解析零事件 → 空流）
    if body.get("max_tokens") is not None:
        out["max_tokens"] = body["max_tokens"]
    if body.get("temperature") is not None:
        out["temperature"] = body["temperature"]
    if body.get("top_p") is not None:
        out["top_p"] = body["top_p"]
    if body.get("stop_sequences"):
        out["stop"] = body["stop_sequences"]
    if body.get("tools"):
        out["tools"] = [
            {"type": "function",
             "function": {"name": t.get("name", ""),
                          "description": t.get("description", ""),
                          "parameters": t.get("input_schema") or {"type": "object"}}}
            for t in body["tools"] if isinstance(t, dict)]
    tc = body.get("tool_choice")
    if isinstance(tc, dict):
        tct = tc.get("type")
        if tct == "any":
            out["tool_choice"] = "required"
        elif tct == "auto":
            out["tool_choice"] = "auto"
        elif tct == "tool":
            out["tool_choice"] = {"type": "function",
                                   "function": {"name": tc.get("name", "")}}

    reasoning = None
    thinking = body.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") in ("enabled", "disabled"):
        reasoning = ReasoningSpec(enabled=(thinking.get("type") == "enabled"))
    return out, reasoning


# —— 非流式响应转换：OpenAI → Anthropic ——

def openai_to_anthropic(resp: dict, system_model: str) -> dict:
    choices = resp.get("choices") or [{}]
    msg = (choices[0] or {}).get("message") or {}
    content: list[dict] = []
    rc = msg.get("reasoning_content")
    if rc:
        content.append({"type": "thinking", "thinking": rc, "signature": ""})
    text = msg.get("content")
    if isinstance(text, str) and text:
        content.append({"type": "text", "text": text})
    elif isinstance(text, list):
        for part in text:
            if isinstance(part, dict) and part.get("type") == "text":
                content.append({"type": "text", "text": part.get("text", "")})
    for tc in msg.get("tool_calls") or []:
        fn = (tc or {}).get("function") or {}
        try:
            arguments = json.loads(fn.get("arguments") or "{}")
        except (json.JSONDecodeError, ValueError):
            arguments = {"_raw": fn.get("arguments")}
        content.append({"type": "tool_use", "id": tc.get("id"),
                        "name": fn.get("name", ""), "input": arguments})
    usage = resp.get("usage") or {}
    return {
        "id": resp.get("id") or "msg_unknown",
        "type": "message",
        "role": "assistant",
        "model": system_model,
        "content": content,
        "stop_reason": _STOP_REASON_MAP.get((choices[0] or {}).get("finish_reason"), "end_turn"),
        "stop_sequence": None,
        "usage": {"input_tokens": usage.get("prompt_tokens") or 0,
                  "output_tokens": usage.get("completion_tokens") or 0},
    }


# —— 流式转换：OpenAI chunks → Anthropic SSE ——

class AnthropicStreamEncoder:
    """有状态编码器：OpenAI delta → Anthropic 事件序列（INT-16 流式语义）。

    块管理（E2E 实测修正）：thinking/text 同类 delta 连续累积在同一块内（仅
    content_block_delta），类型切换时才 content_block_stop + 新块 start；
    stop_reason / usage 先记录，流结束时并入单一 message_delta（Anthropic 语义）。
    """

    def __init__(self, system_model: str):
        self.system_model = system_model
        self.blocks: list[str] = []  # 块类型登记（text/thinking/tool_use）
        self.tool_block_of: dict[int, int] = {}  # openai tool index → anthropic 块序号
        self.message_started = False
        self.stop_reason: str | None = None
        self.usage_output: int | None = None
        self._cur_kind: str | None = None  # 当前开放块类型（thinking/text/tool_use）
        self._cur_idx: int | None = None

    def _new_block(self, kind: str) -> int:
        self.blocks.append(kind)
        return len(self.blocks) - 1

    def _close_current(self, events: list[tuple[str, dict]]) -> None:
        if self._cur_idx is not None:
            events.append(("content_block_stop", {
                "type": "content_block_stop", "index": self._cur_idx}))
            self._cur_idx = None
            self._cur_kind = None

    def _ensure_block(self, kind: str, events: list[tuple[str, dict]],
                      start_payload: dict) -> int:
        """同类复用当前块；异类先关旧块再开新块，返回块序号。"""
        if self._cur_kind == kind and self._cur_idx is not None:
            return self._cur_idx
        self._close_current(events)
        idx = self._new_block(kind)
        self._cur_kind = kind
        self._cur_idx = idx
        events.append(("content_block_start", {
            "type": "content_block_start", "index": idx,
            "content_block": start_payload}))
        return idx

    def encode(self, chunk: dict) -> list[tuple[str, dict]]:
        events: list[tuple[str, dict]] = []
        if not self.message_started:
            self.message_started = True
            events.append(("message_start", {
                "type": "message_start",
                "message": {"id": chunk.get("id") or "msg_unknown", "type": "message",
                            "role": "assistant", "content": [], "model": self.system_model,
                            "usage": {"input_tokens": 0, "output_tokens": 1}},
            }))
            events.append(("ping", {"type": "ping"}))
        choices = chunk.get("choices") or []
        delta = (choices[0] or {}).get("delta") if choices else None
        if isinstance(delta, dict):
            rc = delta.get("reasoning_content")
            if rc:
                idx = self._ensure_block("thinking", events,
                                         {"type": "thinking", "thinking": ""})
                events.append(("content_block_delta", {
                    "type": "content_block_delta", "index": idx,
                    "delta": {"type": "thinking_delta", "thinking": rc}}))
            text = delta.get("content")
            if isinstance(text, str) and text:
                idx = self._ensure_block("text", events, {"type": "text", "text": ""})
                events.append(("content_block_delta", {
                    "type": "content_block_delta", "index": idx,
                    "delta": {"type": "text_delta", "text": text}}))
            for tc in delta.get("tool_calls") or []:
                oi = tc.get("index", 0)
                if oi not in self.tool_block_of:
                    idx = self._ensure_block("tool_use", events, {
                        "type": "input_tool_use",
                        "id": tc.get("id") or f"toolu_{oi}",
                        "name": (tc.get("function") or {}).get("name", "")})
                    self.tool_block_of[oi] = idx
                args = (tc.get("function") or {}).get("arguments")
                if args:
                    events.append(("content_block_delta", {
                        "type": "content_block_delta", "index": self.tool_block_of[oi],
                        "delta": {"type": "input_json_delta", "partial_json": args}}))
        usage = chunk.get("usage")
        if isinstance(usage, dict):
            self.usage_output = usage.get("completion_tokens") or 0
        if choices:
            finish = (choices[0] or {}).get("finish_reason")
            if finish:
                self.stop_reason = _STOP_REASON_MAP.get(finish, "end_turn")
        return events

    def finish_events(self) -> list[tuple[str, dict]]:
        events: list[tuple[str, dict]] = []
        if not self.message_started:
            events.append(("message_start", {
                "type": "message_start",
                "message": {"id": "msg_unknown", "type": "message", "role": "assistant",
                            "content": [], "model": self.system_model,
                            "usage": {"input_tokens": 0, "output_tokens": 1}}}))
        self._close_current(events)  # 收尾开放块（content_block_stop）
        events.append(("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": self.stop_reason or "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": self.usage_output or 0},
        }))
        events.append(("message_stop", {"type": "message_stop"}))
        return events


# —— 端点 ——

@router.post("/v1/messages")
async def messages(request: Request):
    runtime = request.app.state.runtime
    body = await request.json()
    if not isinstance(body, dict):
        return _anthropic_error(400, "invalid_request_error", "请求体必须是 JSON 对象")

    model_name = body.get("model")
    if not isinstance(model_name, str) or not model_name:
        return _anthropic_error(400, "invalid_request_error", "缺少必填字段 model")
    model_def, candidates = resolve_request_model(
        model_name, runtime.config.models, runtime.enum_pool)
    if model_def is None:
        cand = "；候选：" + ", ".join(c for c, _ in candidates) if candidates else ""
        return _anthropic_error(404, "invalid_request_error",
                                f"模型 '{model_name}' 不存在{cand}")
    if not model_def.enabled:
        # 禁用拒绝（FR-2.3 / Q17 / D1，与 /v1/chat/completions 语义一致）：
        # 404 + Anthropic 错误格式 + code=model_disabled；禁用优先于端点类型检查。
        return _anthropic_error(404, "invalid_request_error",
                                f"模型 '{model_name}' 已禁用，可在管理界面开启",
                                code="model_disabled")
    if model_def.endpoint != "chat":
        return _anthropic_error(400, "invalid_request_error",
                                f"模型 '{model_name}' 为图像生成模型，请通过 /v1/images/generations 调用")

    stream = bool(body.get("stream", False))
    openai_body, reasoning = anthropic_to_openai(body)
    ir = IRRequest(system_model=model_def.name, endpoint="chat", stream=stream,
                  body=openai_body, reasoning=reasoning)
    token_id = request.scope.get("state", {}).get("token_id")

    scheduler = runtime.scheduler
    ctx = CallCtx.new(token_id, model_def.name, "chat", stream, runtime.config,
                      check_disconnected=request.is_disconnected)
    watcher = DisconnectWatcher(request.is_disconnected,
                                on_disconnect=lambda: runtime.cancel_registry.cancel(ctx.request_id))
    watcher.start()
    try:
        if stream:
            return await _messages_stream(request, scheduler, ir, ctx, model_def, watcher)
        result, _meta = await scheduler.execute_chat(ir, ctx)
        return JSONResponse(content=openai_to_anthropic(result, model_def.name))
    except asyncio.CancelledError:
        raise
    except GatewayError as e:
        return _anthropic_error(e.status_code, _gw_error_type(e),
                                str(e.args[0]) if e.args else "请求失败")
    finally:
        watcher.cancel_sync()
        runtime.cancel_registry.unregister(ctx.request_id)


def _gw_error_type(e: GatewayError) -> str:
    if e.status_code == 429:
        return "rate_limit_error"
    if e.status_code == 401:
        return "authentication_error"
    if e.status_code == 404:
        return "not_found_error"
    if e.status_code == 400:
        return "invalid_request_error"
    return "api_error"


async def _messages_stream(request: Request, scheduler, ir, ctx, model_def, watcher):
    """Anthropic 流式（INT-16/28）：延迟提交同 /v1/chat/completions。"""
    runtime = request.app.state.runtime
    heartbeat = runtime.config.gateway.heartbeat_seconds
    gen = scheduler.stream_chat(ir, ctx)
    encoder = AnthropicStreamEncoder(model_def.name)

    first = None
    try:
        first = await gen.__anext__()
    except StopAsyncIteration:
        watcher.cancel_sync()
        return StreamingResponse(_anthropic_sse(encoder.finish_events()),
                                  media_type="text/event-stream", headers=_sse_headers())
    except GatewayError as e:
        watcher.cancel_sync()
        return _anthropic_error(e.status_code, _gw_error_type(e),
                                str(e.args[0]) if e.args else "请求失败")

    watcher.cancel_sync()

    async def body_stream():
        queue: asyncio.Queue = asyncio.Queue()
        END = object()

        async def pull():
            try:
                if first is not None:
                    await queue.put(first)
                async for ev in gen:
                    await queue.put(ev)
            finally:
                queue.put_nowait(END)

        task = asyncio.create_task(pull())
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {\"type\": \"ping\"}\n\n"
                    continue
                if ev is END:
                    break
                if isinstance(ev, dict) and ev.get("type") == ERROR_EVENT:
                    err = ev.get("error") or {}
                    payload = {"type": "error",
                               "error": {"type": "api_error",
                                         "message": err.get("message", "上游流中断")}}
                    yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    break
                for name, event in encoder.encode(ev):
                    yield f"event: {name}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            for name, event in encoder.finish_events():
                yield f"event: {name}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            task.cancel()
            # 不能直接 `await task`：客户端断连时 Starlette 会向本生成器反复投递
            # 取消；直接 await 会把取消转发进 pull 任务本体，打断 httpcore 的
            # shielded 连接关闭 → 上游 TCP 永不关闭 → 取消无法透传（INT-28 根因，
            # 同 openai_compat._chat_stream_response 的 INT-08 修复）。
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait([task], timeout=5.0)

    return StreamingResponse(body_stream(), media_type="text/event-stream",
                             headers=_sse_headers())


def _sse_headers() -> dict:
    return {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


async def _anthropic_sse(events):
    for name, event in events:
        yield f"event: {name}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
