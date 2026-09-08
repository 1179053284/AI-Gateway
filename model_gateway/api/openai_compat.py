"""OpenAI 兼容入站端点（tech-design §4.1 / §4.5 / §6，M1 任务 3/5/8）。

- GET /v1/models：全部启用系统模型（OpenAI 格式）
- POST /v1/chat/completions：stream true/false 全支持；延迟提交（首内容事件前
  零字节、耗尽返回非 200 JSON——绝不「先 200 再 error」）；SSE 心跳注释帧；
  中途失败 error 帧两分支（retryable 标注 / 原始错误透传）
- POST /v1/images/generations：调度/重试/切换/取消同样适用；URL 有效期提示三处
  （响应体 _gw_note.url_valid_hours + 响应头 X-GW-URL-Valid-Hours，INT-38）
"""

from __future__ import annotations

import asyncio
import contextlib
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from model_gateway.core.cancel import CancelRegistry, DisconnectWatcher
from model_gateway.core.ir import IRRequest, lift_reasoning_from_body
from model_gateway.core.scheduler import ERROR_EVENT, CallCtx, GatewayError
from model_gateway.enums.matcher import resolve_request_model

router = APIRouter()


def _runtime(request: Request):
    return request.app.state.runtime


def _openai_json_error(status: int, body: dict) -> JSONResponse:
    return JSONResponse(status_code=status, content=body)


@router.get("/v1/models")
async def list_models(request: Request):
    runtime = _runtime(request)
    data = [
        {"id": m.name, "object": "model", "created": 0, "owned_by": "model-gateway",
         "endpoint": m.endpoint, "group": m.group}
        for m in runtime.config.models if m.enabled  # FR-2.3：仅返回启用模型
    ]
    return {"object": "list", "data": data}


def _resolve_model_or_404(request: Request, model_name: str):
    """模型解析（tech §4.2）：系统模型精确 → 枚举池别名 → 规范化；无命中 404 + 候选。

    命中 enabled=false 的禁用模型（含别名命中）→ 同样 404，但 code=model_disabled
    （FR-2.3 / Q17 / D1：不进入选路、不触达上游；禁用优先于端点类型检查）。
    """
    runtime = _runtime(request)
    model_def, candidates = resolve_request_model(model_name, runtime.config.models, runtime.enum_pool)
    if model_def is None:
        body = {"error": {
            "message": f"模型 '{model_name}' 不存在（未定义的系统模型名，且枚举池无匹配）",
            "type": "invalid_request_error",
            "code": "model_not_found",
            "requested_model": model_name,
        }}
        if candidates:
            body["error"]["candidates"] = [{"name": c, "confidence": conf} for c, conf in candidates]
        return None, _openai_json_error(404, body)
    if not model_def.enabled:
        return None, _openai_json_error(404, {"error": {
            "message": f"模型 '{model_name}' 已禁用，可在管理界面开启",
            "type": "invalid_request_error",
            "code": "model_disabled",
            "requested_model": model_name,
        }})
    return model_def, None


def _endpoint_type_error(model_name: str, model_def, want: str):
    """端点类型校验（UT-21）：endpoint 不匹配 → 400 明确提示（不触达上游）。"""
    if model_def.endpoint != want:
        kind = "图像生成模型" if model_def.endpoint == "images" else "对话模型"
        right = "/v1/images/generations" if model_def.endpoint == "images" else "/v1/chat/completions"
        return _openai_json_error(400, {"error": {
            "message": f"模型 '{model_name}' 为{kind}（endpoint={model_def.endpoint}），"
                       f"请通过 {right} 调用",
            "type": "invalid_request_error",
            "code": "endpoint_mismatch",
        }})
    return None


def _watch_disconnects(request: Request, registry: CancelRegistry, request_id: str):
    """延迟提交窗口断连探测（tech §4.6/§8-11）：探测到断连 → 取消处理 task → 上游取消。"""
    task = asyncio.current_task()
    registry.register(request_id, task)
    watcher = DisconnectWatcher(
        request.is_disconnected,
        on_disconnect=lambda: registry.cancel(request_id),
    )
    watcher.start()
    return watcher


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    runtime = _runtime(request)
    body = await request.json()
    if not isinstance(body, dict):
        return _openai_json_error(400, {"error": {
            "message": "请求体必须是 JSON 对象", "type": "invalid_request_error"}})

    model_name = body.get("model")
    if not isinstance(model_name, str) or not model_name:
        return _openai_json_error(400, {"error": {
            "message": "缺少必填字段 model", "type": "invalid_request_error"}})
    model_def, err = _resolve_model_or_404(request, model_name)
    if err is not None:
        return err
    assert model_def is not None
    err = _endpoint_type_error(model_name, model_def, "chat")
    if err is not None:
        return err

    stream = bool(body.get("stream", False))
    reasoning = lift_reasoning_from_body(body)  # 防出站双重注入（Q15）
    body.pop("model", None)
    ir = IRRequest(system_model=model_def.name, endpoint="chat", stream=stream,
                   body=body, reasoning=reasoning)
    token_id = request.scope.get("state", {}).get("token_id")

    scheduler = runtime.scheduler
    snapshot = runtime.config  # 请求开始即绑定快照（tech §8-4）
    ctx = CallCtx.new(token_id, model_def.name, "chat", stream, snapshot,
                      check_disconnected=request.is_disconnected)
    watcher = _watch_disconnects(request, runtime.cancel_registry, ctx.request_id)
    try:
        if stream:
            return await _chat_stream_response(request, scheduler, ir, ctx, model_def, watcher)
        result, _meta = await scheduler.execute_chat(ir, ctx)
        return JSONResponse(content=result)
    except asyncio.CancelledError:
        raise  # aborted 事件已由调度器落盘；客户端已断连，无需响应
    except GatewayError as e:
        return _openai_json_error(e.status_code, e.to_openai_error())
    finally:
        watcher.cancel_sync()
        runtime.cancel_registry.unregister(ctx.request_id)


async def _chat_stream_response(request: Request, scheduler, ir, ctx, model_def, watcher):
    """流式端点（§4.5/§6）：

    - 延迟提交：先 await 首个内容事件；窗口耗尽 → JSONResponse 非 200（INT-35）
    - 提交后 StreamingResponse(200)；心跳 = 静默超 heartbeat_seconds 发注释帧（INT-21）
    - 中途失败 → error 帧（retryable 标注）+ [DONE]（INT-11/12）
    """
    runtime = _runtime(request)
    heartbeat = runtime.config.gateway.heartbeat_seconds
    gen = scheduler.stream_chat(ir, ctx)

    # —— 延迟提交窗口：拿首帧（内容事件）——
    first = None
    try:
        first = await gen.__anext__()
    except StopAsyncIteration:
        # 零内容成功（罕见）：空流 + [DONE]
        watcher.cancel_sync()
        return StreamingResponse(_sse(_finish_only()), media_type="text/event-stream",
                                 headers=_sse_headers())
    except GatewayError as e:
        watcher.cancel_sync()
        return _openai_json_error(e.status_code, e.to_openai_error())

    watcher.cancel_sync()  # 首帧已到，断连职责移交 StreamingResponse（starlette）

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
                    yield ": keep-alive\n\n"  # 心跳注释帧（FR-3.11）
                    continue
                if ev is END:
                    break
                if isinstance(ev, dict) and ev.get("type") == ERROR_EVENT:
                    yield _sse_error_frame(ev)
                    break
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            task.cancel()
            # 不能直接 `await task`：客户端断连时 Starlette 任务组会向本生成器反复投递
            # 取消；host 任务恰在直接 await pull 上时，asyncio 的 Task.cancel() 会把
            # 取消经 _fut_waiter 转发进 pull 任务本体，打断 httpcore 的 shielded 连接
            # 关闭 → 上游 TCP 永不关闭 → 取消无法透传（INT-08 根因）。
            # asyncio.wait 经内部 future 间接等待：取消只落在 future 上，pull 的
            # 清理链路（response.aclose → TCP close）得以完整执行。
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait([task], timeout=5.0)

    return StreamingResponse(body_stream(), media_type="text/event-stream",
                             headers=_sse_headers())


def _sse_headers() -> dict:
    return {"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
            "Connection": "keep-alive"}


def _finish_only():
    yield "data: [DONE]\n\n"


def _sse_error_frame(ev: dict) -> str:
    """中途失败 error 帧：厂商原始错误不修饰 + retryable 标注（§6 两分支）。"""
    err = ev.get("error")
    if not isinstance(err, dict):
        err = {"message": str(err)}
    err = dict(err)
    err.setdefault("message", "")
    err["retryable"] = bool(ev.get("retryable"))
    if ev.get("status_code"):
        err.setdefault("code", ev["status_code"])
    return f"data: {json.dumps({'error': err}, ensure_ascii=False)}\n\n"


@router.post("/v1/images/generations")
async def images_generations(request: Request):
    """图像生成（M1 任务 8）：调度/重试/切换/取消同样适用；URL 有效期提示三处。"""
    runtime = _runtime(request)
    body = await request.json()
    if not isinstance(body, dict):
        return _openai_json_error(400, {"error": {
            "message": "请求体必须是 JSON 对象", "type": "invalid_request_error"}})

    model_name = body.get("model")
    if not isinstance(model_name, str) or not model_name:
        return _openai_json_error(400, {"error": {
            "message": "缺少必填字段 model", "type": "invalid_request_error"}})
    model_def, err = _resolve_model_or_404(request, model_name)
    if err is not None:
        return err
    assert model_def is not None
    err = _endpoint_type_error(model_name, model_def, "images")
    if err is not None:
        return err

    body.pop("model", None)
    ir = IRRequest(system_model=model_def.name, endpoint="images", stream=False, body=body)
    token_id = request.scope.get("state", {}).get("token_id")

    ctx = CallCtx.new(token_id, model_def.name, "images", False, runtime.config,
                      check_disconnected=request.is_disconnected)
    watcher = _watch_disconnects(request, runtime.cancel_registry, ctx.request_id)
    try:
        result, _meta = await runtime.scheduler.execute_images(ir, ctx)
    except asyncio.CancelledError:
        raise
    except GatewayError as e:
        return _openai_json_error(e.status_code, e.to_openai_error())
    finally:
        watcher.cancel_sync()
        runtime.cancel_registry.unregister(ctx.request_id)

    headers = {}
    response_format = body.get("response_format")
    if response_format in (None, "url"):
        hours = runtime.enum_pool.url_valid_hours(model_def.name)
        if hours is not None:
            # 终审确认点 8 三处齐上之两处（第三处 M2 界面模型详情页）
            result = dict(result)
            result["_gw_note"] = {"url_valid_hours": hours,
                                  "note": f"图像 URL 有效期约 {hours} 小时，请及时保存"}
            headers["X-GW-URL-Valid-Hours"] = str(hours)
    return JSONResponse(content=result, headers=headers)
