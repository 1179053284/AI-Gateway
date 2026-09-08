"""调度状态机（tech-design §5，M1 任务 3/4/5/6/8 核心）。

- §5.2 统一判定规则（y 先判定；CancelledError 专用捕获必须 re-raise）
- §5.3 并发溢出生效集：生效集 = top-x 可用资源；集内在途最少者承接（平局取优先级高）
- §5.5 请求总预算：每次尝试边界检查，耗尽走统一兜底错误
- §6 流式边界：首帧转发前可重放（重试/切换零感知）；首帧后失败 → error 帧（不重放）

统一错误出口（GatewayError）：
- BAD_REQUEST / CANCELED(408) → 原样透传（同状态码 + 原错误体）
- 资源耗尽 / 预算耗尽 → 统一「无可用资源」错误（OpenAI error 格式，含已尝试摘要）
"""

from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

from model_gateway.config.schemas import AppConfig
from model_gateway.core.errors import ErrorClass, UpstreamError
from model_gateway.stats.events import error_summary
from model_gateway.core.ir import (
    IRRequest,
    _iter_deltas,
    apply_model_params,
    chunk_is_content,
    inject_reasoning_into_body,
    merge_reasoning,
)
from model_gateway.stats.aggregate import estimate_usage

ERROR_EVENT = "_error"  # 流内错误标记（committed 后的中途失败，编码层转 error 帧）


class GatewayError(Exception):
    """网关层最终错误（透传上游 / 无可用资源 / 预算耗尽）。

    error_body 非 None 时为上游原始响应体（透传，状态码同上游）；
    否则为网关统一「无可用资源」错误体。
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 503,
        error_body: Any = None,
        error_type: str | None = None,
        exhausted_reason: str | None = None,
        system_model: str | None = None,
        attempts: list[dict] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_body = error_body
        self.error_type = error_type
        self.exhausted_reason = exhausted_reason
        self.system_model = system_model
        self.attempts = attempts or []

    def to_openai_error(self) -> dict:
        """统一 OpenAI 标准 error 格式（UT-09/INT-13：含系统模型名与原因摘要）。"""
        if self.error_body is not None:
            body = self.error_body
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except (json.JSONDecodeError, ValueError):
                    body = {"message": body}
            if isinstance(body, dict) and "error" in body:
                return body  # 上游已是标准形态 → 原样透传
            return {"error": body}
        parts = [str(self.args[0]) if self.args else "请求失败"]
        if self.exhausted_reason:
            reason_txt = {
                "BUDGET_EXHAUSTED": "请求总预算耗尽",
                "RETRY_EXHAUSTED": "重试额度耗尽",
                "NO_RESOURCE": "无可用资源",
            }.get(self.exhausted_reason, self.exhausted_reason)
            parts.append(f"原因：{reason_txt}")
        if self.attempts:
            summary = "; ".join(
                f"{a['resource']}×{a['attempts']}"
                + (f"（{'、'.join(a.get('errors', []))}）" if a.get("errors") else "")
                for a in self.attempts
            )
            parts.append(f"已尝试：{summary}")
        return {
            "error": {
                "message": "；".join(parts),
                "type": "gateway_error",
                "code": self.exhausted_reason or "upstream_failed",
                "system_model": self.system_model,
            }
        }


@dataclass
class CallCtx:
    """单请求执行上下文（请求开始即绑定配置快照，tech §8-4）。"""

    request_id: str
    token_id: str | None
    system_model: str
    endpoint: str  # chat | images
    stream: bool
    snapshot: AppConfig
    check_disconnected: Callable[[], Awaitable[bool]] | None = None
    started_mono: float = field(default_factory=time.monotonic)

    @staticmethod
    def new(token_id: str | None, system_model: str, endpoint: str, stream: bool,
            snapshot: AppConfig, check_disconnected=None) -> "CallCtx":
        return CallCtx(
            request_id=f"req_{uuid.uuid4().hex[:12]}",
            token_id=token_id,
            system_model=system_model,
            endpoint=endpoint,
            stream=stream,
            snapshot=snapshot,
            check_disconnected=check_disconnected,
            started_mono=time.monotonic(),
        )

    async def client_disconnected(self) -> bool:
        if self.check_disconnected is None:
            return False
        try:
            r = self.check_disconnected()
            if inspect.isawaitable(r):
                r = await r
            return bool(r)
        except Exception:  # noqa: BLE001 — 探测失败不阻断主链路
            return False


@dataclass
class _ResourceAttempt:
    """resource_attempts 明细行（tech §4.8 事件格式）。"""

    resource: str
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    switched: bool = False

    def to_dict(self) -> dict:
        return {"resource": self.resource, "attempts": self.attempts,
                "errors": self.errors, "switched": self.switched}


@dataclass
class ExecMeta:
    """事件落盘字段（tech §4.8；UT-15 聚合输入；provider/account 为承接资源冗余字段）。"""

    status: str = "failed"  # success | failed | aborted
    attempts: list[_ResourceAttempt] = field(default_factory=list)
    final_resource: str | None = None
    provider: str | None = None  # 厂商展示名（资源 preset 口径，Q18-②）
    account: str | None = None  # 账号标识（资源次要备注）
    retry_count: int = 0
    switch_count: int = 0
    ttft_ms: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    usage_source: str = "estimated"  # vendor | estimated
    images_count: int | None = None
    error_summary: str | None = None
    text_output: str = ""  # 流式文本累积（估算 token 用）

    def event(self, ctx: CallCtx) -> dict:
        duration_ms = int((time.monotonic() - ctx.started_mono) * 1000)
        return {
            "request_id": ctx.request_id,
            "ts": dt.datetime.now().isoformat(timespec="milliseconds"),
            "client_token_id": ctx.token_id,
            "system_model": ctx.system_model,
            "endpoint": ctx.endpoint,
            "stream": ctx.stream,
            "status": self.status,
            "resource_attempts": [a.to_dict() for a in self.attempts],
            "final_resource": self.final_resource,
            "provider": self.provider,
            "account": self.account,
            "retry_count": self.retry_count,
            "switch_count": self.switch_count,
            "duration_ms": duration_ms,
            "ttft_ms": self.ttft_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usage_source": self.usage_source,
            "images_count": self.images_count,
            "error_summary": self.error_summary,
        }


class Scheduler:
    """§5 调度状态机（通过 runtime 间接访问热重载后的最新配置/资源状态）。"""

    def __init__(self, runtime):
        # runtime: main.Runtime（config/resources/classifier/adapters/key_values/
        #         resource_reasoning/events/switch_ring），字段热重载时整体替换
        self.runtime = runtime

    # —— 工具 ——

    def _adapter(self, resource):
        adapter = self.runtime.adapters.get(resource.rid)
        if adapter is None:
            raise GatewayError(f"资源 '{resource.label}' 无可用出站适配器（protocol 未实现）")
        return adapter

    def _key_value(self, resource) -> str:
        value = self.runtime.key_values.get(resource.rid)
        if value is None:
            raise GatewayError(f"资源 '{resource.label}' 的 Key 不存在（配置已变更）")
        return value

    def _out_body(self, ir: IRRequest, resource) -> dict:
        """每次尝试独立构造出站请求体（推理参数按当前资源默认重算，INT-37；
        网关级模型参数字段级注入：工具传参 > 网关设置 > 厂商内置，Q24，仅 chat）。"""
        body = dict(ir.body)
        body["model"] = resource.vendor_model
        if ir.endpoint == "chat":
            apply_model_params(body, self.runtime.model_params.get(ir.system_model))
        merged = merge_reasoning(ir.reasoning, self.runtime.resource_reasoning.get(resource.resource_id))
        inject_reasoning_into_body(body, merged)
        return body

    def _exit_status_code(self, exits: list[str], exhausted: str | None) -> int:
        """兜底错误状态码（tech §4.5：按兜底原因取 503/429/401/404）。"""
        if exhausted == "BUDGET_EXHAUSTED":
            return 503
        if exits and all(e == "QUOTA" for e in exits):
            return 429
        if exits and all(e == "AUTH" for e in exits):
            return 401
        if exits and all(e == "NOT_FOUND" for e in exits):
            return 404
        return 503

    def _emit_switch(self, ctx: CallCtx, from_res: str, to_res: str | None,
                     reason_cls: str, err_summary: str | None, was_cooldown: bool) -> None:
        ev = {
            "ts": dt.datetime.now().isoformat(timespec="milliseconds"),
            "request_id": ctx.request_id,
            "system_model": ctx.system_model,
            "from_resource": from_res,
            "to_resource": to_res,
            "reason_cls": reason_cls,
            "error_summary": err_summary,
            "was_cooldown": was_cooldown,
        }
        self.runtime.switch_ring.append(ev)
        self.runtime.events.log_switch(ev)

    async def _sleep_interruptible(self, seconds: float, ctx: CallCtx) -> None:
        """退避 sleep 分段 + 断连探测（INT-24：退避期断连可被及时打断）。"""
        end = time.monotonic() + seconds
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            await asyncio.sleep(min(remaining, 0.1))
            if await ctx.client_disconnected():
                raise asyncio.CancelledError("client_disconnected")

    def _usage_from(self, usage: dict | None, meta: ExecMeta, ir: IRRequest) -> None:
        """usage 落盘口径：厂商 usage 优先；缺失时本地估算（FR-5.8）。"""
        if usage and (usage.get("prompt_tokens") or usage.get("completion_tokens")):
            meta.input_tokens = usage.get("prompt_tokens") or 0
            meta.output_tokens = usage.get("completion_tokens") or 0
            meta.usage_source = "vendor"
        elif meta.usage_source != "vendor":
            meta.input_tokens, meta.output_tokens = estimate_usage(ir.body, meta.text_output)
            meta.usage_source = "estimated"

    def _log(self, ctx: CallCtx, meta: ExecMeta) -> None:
        self.runtime.events.log_request(meta.event(ctx))

    # —— 非流式统一执行（chat 非流式 / images 共用）——

    async def _execute(self, ir: IRRequest, ctx: CallCtx,
                       call: Callable,
                       on_success: Callable[[dict, ExecMeta], None] | None = None) -> tuple[dict, ExecMeta]:
        """非流式统一执行：事件落盘统一收尾（成功/失败/取消各一行，tech §5.1-10）。"""
        meta = ExecMeta()
        try:
            result = await self._execute_inner(ir, ctx, call, meta, on_success)
            return result, meta
        except asyncio.CancelledError:
            meta.status = "aborted"  # 客户端断连/任务取消（INT-32：aborted 落盘）
            raise
        finally:
            self._log(ctx, meta)

    async def _execute_inner(self, ir: IRRequest, ctx: CallCtx,
                             call: Callable, meta: ExecMeta,
                             on_success: Callable[[dict, ExecMeta], None] | None = None) -> dict:
        snap = ctx.snapshot
        deadline = ctx.started_mono + snap.gateway.request_total_budget_seconds
        m = snap.scheduling.retry_per_request  # 全局唯一（Q18-③）
        y = snap.scheduling.fail_threshold
        tried: set[tuple[str, str]] = set()
        exits: list[str] = []
        exhausted: str | None = None
        terminal = False  # 终止外层循环（预算耗尽 / no_failover 的 m 耗尽）
        # 延迟落盘的切换事件（from_res, reason_cls, err, was_cooldown）——tech §4.8
        # to_resource = 实际补位资源，须等下一轮选路后才能确定
        pending_switch: tuple[str, str, str | None, bool] | None = None

        while True:
            if await ctx.client_disconnected():
                meta.status = "aborted"
                if pending_switch is not None:  # 切换后、选路前断连：to=None 落盘
                    self._emit_switch(ctx, pending_switch[0], None, pending_switch[1],
                                      pending_switch[2], pending_switch[3])
                    pending_switch = None
                raise asyncio.CancelledError("client_disconnected")
            resource = self.runtime.resources.pick_and_acquire(ctx.system_model, exclude=tried)
            if pending_switch is not None:
                self._emit_switch(ctx, pending_switch[0],
                                  resource.resource_id_str if resource else None,
                                  pending_switch[1], pending_switch[2], pending_switch[3])
                pending_switch = None
            if resource is None:
                exhausted = exhausted or "NO_RESOURCE"
                break
            tried.add(resource.resource_id)
            rec = _ResourceAttempt(resource.resource_id_str)
            meta.attempts.append(rec)
            quota_retries = 0
            switch: tuple[str, bool] | None = None  # (reason_cls, was_cooldown)
            try:
                for attempt in range(1, m + 2):
                    if await ctx.client_disconnected():
                        meta.status = "aborted"
                        raise asyncio.CancelledError("client_disconnected")
                    if time.monotonic() > deadline:
                        exhausted = "BUDGET_EXHAUSTED"
                        terminal = True
                        break
                    rec.attempts += 1
                    if rec.attempts > 1:
                        meta.retry_count += 1
                    try:
                        result = await call(resource, self._out_body(ir, resource))
                    except asyncio.CancelledError:
                        raise
                    except UpstreamError as e:
                        cls = self.runtime.classifier.classify(e)
                        summary = error_summary(e)
                        if cls is ErrorClass.CANCELED:
                            meta.status = "aborted"
                            meta.error_summary = summary
                            raise GatewayError(
                                "上游已取消", status_code=e.status_code or 408,
                                error_body=e.error_body, error_type=e.error_type,
                            ) from e
                        if cls is ErrorClass.BAD_REQUEST:
                            meta.status = "failed"
                            meta.error_summary = summary
                            raise GatewayError(
                                summary or "上游拒绝请求", status_code=e.status_code or 400,
                                error_body=e.error_body, error_type=e.error_type,
                            ) from e
                        if cls is ErrorClass.AUTH:
                            rec.errors.append(summary or "auth_error")
                            self.runtime.resources.disable(resource)
                            exits.append("AUTH")
                            switch = ("AUTH", False)
                            break
                        if cls is ErrorClass.NOT_FOUND:
                            rec.errors.append(summary or "not_found")
                            self.runtime.resources.invalidate(resource)
                            exits.append("NOT_FOUND")
                            switch = ("NOT_FOUND", False)
                            break
                        if cls is ErrorClass.QUOTA:
                            rec.errors.append(summary or "quota")
                            if quota_retries < snap.scheduling.quota_retry:
                                quota_retries += 1
                                delay = snap.scheduling.quota_backoff_base_seconds * (2 ** (quota_retries - 1))
                                await self._sleep_interruptible(delay, ctx)
                                continue
                            self.runtime.resources.bench(
                                resource, self.runtime.resources.cooldown_seconds_for(resource, snap))
                            exits.append("QUOTA")
                            switch = ("QUOTA", True)
                            break
                        # RETRYABLE：计入 C（跨请求累计），y 先判定（§5.2）；
                        # no_failover（如 URL 下载失败）仅同资源重试，m 耗尽即终止（tech §4.2，INT-31）
                        rec.errors.append(summary or "retryable")
                        c = self.runtime.resources.note_failure(resource, summary or "retryable")
                        if e.no_failover:
                            if attempt == m + 1:
                                exhausted = "RETRY_EXHAUSTED"
                                terminal = True
                                break
                            if snap.scheduling.retry_backoff_seconds > 0:
                                await self._sleep_interruptible(snap.scheduling.retry_backoff_seconds, ctx)
                            continue
                        if c >= y:
                            self.runtime.resources.bench(
                                resource, self.runtime.resources.cooldown_seconds_for(resource, snap))
                            exits.append("RETRYABLE_Y")
                            switch = ("RETRYABLE_Y", True)
                            break
                        if attempt == m + 1:
                            exhausted = "RETRY_EXHAUSTED"
                            break  # m 耗尽（C 仍 < y）→ 切下一资源，R 不冷却（§5.2）
                        if snap.scheduling.retry_backoff_seconds > 0:
                            await self._sleep_interruptible(snap.scheduling.retry_backoff_seconds, ctx)
                    else:
                        self.runtime.resources.note_success(resource)
                        meta.status = "success"
                        meta.final_resource = rec.resource
                        meta.provider = resource.vendor
                        meta.account = resource.account or None
                        # usage 在落盘前吸收（厂商值优先，缺失本地估算，FR-5.8）
                        self._usage_from(result.get("usage") if isinstance(result, dict) else None,
                                         meta, ir)
                        if on_success is not None:
                            on_success(result, meta)
                        return result
            finally:
                self.runtime.resources.release(resource)
            # 切换续跑：记录切换事件（延迟到下一轮选路后落盘，to_resource =
            # 实际补位资源；terminal / 无资源补位时 to=None）
            if switch is not None or exhausted == "RETRY_EXHAUSTED":
                rec.switched = True
                meta.switch_count += 1
                if not meta.error_summary and rec.errors:
                    meta.error_summary = rec.errors[-1]
                reason_cls, was_cooldown = switch if switch is not None else ("RETRY_EXHAUSTED", False)
                pending_switch = (rec.resource, reason_cls,
                                  rec.errors[-1] if rec.errors else None, was_cooldown)
            if terminal:
                break

        if pending_switch is not None:  # 循环终止未选路（no_failover 耗尽等）：to=None
            self._emit_switch(ctx, pending_switch[0], None, pending_switch[1],
                              pending_switch[2], pending_switch[3])
            pending_switch = None
        meta.status = "failed"
        meta.error_summary = meta.error_summary or (
            "请求总预算耗尽" if exhausted == "BUDGET_EXHAUSTED" else "无可用资源")
        raise GatewayError(
            meta.error_summary or "无可用资源",
            status_code=self._exit_status_code(exits, exhausted),
            exhausted_reason=exhausted or "NO_RESOURCE",
            system_model=ctx.system_model,
            attempts=[a.to_dict() for a in meta.attempts],
        )

    # —— 公开入口 ——

    async def execute_chat(self, ir: IRRequest, ctx: CallCtx) -> tuple[dict, ExecMeta]:
        """chat 非流式：返回厂商响应（已归一化思考字段），失败抛 GatewayError。"""

        async def call(resource, body: dict) -> dict:
            return await self._adapter(resource).chat_nonstream(
                self._key_value(resource), resource.vendor_model, body,
                ctx.snapshot.gateway.attempt_timeout_seconds)

        result, meta = await self._execute(ir, ctx, call)
        self._usage_from(result.get("usage") if isinstance(result, dict) else None, meta, ir)
        if isinstance(result, dict):
            result["model"] = ctx.system_model  # 统一名替换厂商名（流式同规则 _tag_model）
        return result, meta

    async def execute_images(self, ir: IRRequest, ctx: CallCtx) -> tuple[dict, ExecMeta]:
        """images 生成：调度/重试/切换/取消同样适用（tech §4.1）。"""

        async def call(resource, body: dict) -> dict:
            return await self._adapter(resource).images_generate(
                self._key_value(resource), resource.vendor_model, body,
                ctx.snapshot.gateway.attempt_timeout_seconds)

        def on_success(result: dict, meta: ExecMeta) -> None:
            # 必须在 _execute 落盘前设置（on_success 时机）——放在 _execute 返回后
            # 再赋值会晚于 finally 的 _log，事件行 images_count 恒为 None（E2E 实测发现）
            data = result.get("data")
            if isinstance(data, list):
                meta.images_count = len(data)

        result, meta = await self._execute(ir, ctx, call, on_success=on_success)
        return result, meta

    # —— 流式（延迟提交 + 首帧边界 + 中途失败两分支，§6）——

    async def stream_chat(self, ir: IRRequest, ctx: CallCtx) -> AsyncIterator[dict]:
        """流式 chat：yield 归一化 chunk 字典。

        - 首个内容事件前：全部失败静默重试/切换（延迟提交窗口；耗尽抛 GatewayError）
        - 首个内容事件后（committed）：失败 → yield {type: ERROR_EVENT,...} 后结束（不重放）
        - 客户端断连：CancelledError → aborted 落盘后 re-raise（绝不吞，tech §8-1）
        """
        snap = ctx.snapshot
        deadline = ctx.started_mono + snap.gateway.request_total_budget_seconds
        m = snap.scheduling.retry_per_request  # 全局唯一（Q18-③）
        y = snap.scheduling.fail_threshold
        meta = ExecMeta()
        tried: set[tuple[str, str]] = set()
        exits: list[str] = []
        exhausted: str | None = None
        terminal = False  # 终止外层循环（预算耗尽 / no_failover 的 m 耗尽）
        timeout = snap.gateway.attempt_timeout_seconds
        # 延迟落盘的切换事件（from_res, reason_cls, err, was_cooldown）——tech §4.8
        # to_resource = 实际补位资源，须等下一轮选路后才能确定
        pending_switch: tuple[str, str, str | None, bool] | None = None

        try:
            logged = False  # 中途失败分支已先行落盘（yield ERROR_EVENT 前防竞态）
            while True:
                if await ctx.client_disconnected():
                    meta.status = "aborted"
                    if pending_switch is not None:  # 切换后、选路前断连：to=None 落盘
                        self._emit_switch(ctx, pending_switch[0], None, pending_switch[1],
                                          pending_switch[2], pending_switch[3])
                        pending_switch = None
                    raise asyncio.CancelledError("client_disconnected")
                resource = self.runtime.resources.pick_and_acquire(ctx.system_model, exclude=tried)
                if pending_switch is not None:
                    self._emit_switch(ctx, pending_switch[0],
                                      resource.resource_id_str if resource else None,
                                      pending_switch[1], pending_switch[2], pending_switch[3])
                    pending_switch = None
                if resource is None:
                    exhausted = exhausted or "NO_RESOURCE"
                    break
                tried.add(resource.resource_id)
                rec = _ResourceAttempt(resource.resource_id_str)
                meta.attempts.append(rec)
                quota_retries = 0
                switch: tuple[str, bool] | None = None
                try:
                    for attempt in range(1, m + 2):
                        if await ctx.client_disconnected():
                            meta.status = "aborted"
                            raise asyncio.CancelledError("client_disconnected")
                        if time.monotonic() > deadline:
                            exhausted = "BUDGET_EXHAUSTED"
                            terminal = True
                            break
                        rec.attempts += 1
                        if rec.attempts > 1:
                            meta.retry_count += 1
                        body = self._out_body(ir, resource)
                        agen = self._adapter(resource).chat_stream(
                            self._key_value(resource), resource.vendor_model, body, timeout)
                        buffer: list[dict] = []
                        committed = False
                        try:
                            async for chunk in agen:
                                if not isinstance(chunk, dict):
                                    continue
                                err = chunk.get("error")
                                if isinstance(err, dict):
                                    # 厂商 SSE 内 error 帧（INT-11 形态）→ 中途失败
                                    e = UpstreamError(
                                        f"upstream stream error: {err.get('message', '')}",
                                        status_code=err.get("code") or err.get("http_status"),
                                        error_body=json.dumps(err, ensure_ascii=False),
                                        error_type=err.get("type"),
                                    )
                                    raise e
                                if committed:
                                    self._absorb_chunk(chunk, meta)
                                    yield self._tag_model(chunk, ctx)
                                elif chunk_is_content(chunk):
                                    committed = True
                                    meta.ttft_ms = meta.ttft_ms or int(
                                        (time.monotonic() - ctx.started_mono) * 1000)
                                    for b in buffer:  # 先转发缓冲的前导 chunk（如 role）
                                        self._absorb_chunk(b, meta)
                                        yield self._tag_model(b, ctx)
                                    buffer = []
                                    self._absorb_chunk(chunk, meta)
                                    yield self._tag_model(chunk, ctx)
                                else:
                                    buffer.append(chunk)
                            # 流正常结束（[DONE] 消费完毕）
                            self.runtime.resources.note_success(resource)
                            meta.status = "success"
                            meta.final_resource = rec.resource
                            meta.provider = resource.vendor
                            meta.account = resource.account or None
                            for b in buffer:  # 零内容成功的尾部 chunk（如 usage 帧）
                                self._absorb_chunk(b, meta)
                                yield self._tag_model(b, ctx)
                            return
                        except asyncio.CancelledError:
                            raise
                        except UpstreamError as e:
                            if committed:
                                # §6 首帧后失败：不重放；error 帧终止；计入 C（中途失败也是失败）
                                # 注意：先落盘再 yield——消费端收帧后即取消本生成器，
                                # CancelledError 不应覆写已定的 failed 状态（防事件竞态）
                                cls = self.runtime.classifier.classify(e)
                                summary = error_summary(e)
                                rec.errors.append(summary or "midstream")
                                c = self.runtime.resources.note_failure(resource, summary or "midstream")
                                if c >= y:
                                    self.runtime.resources.bench(
                                        resource, self.runtime.resources.cooldown_seconds_for(resource, snap))
                                meta.status = "failed"
                                meta.error_summary = summary
                                self._usage_from(None, meta, ir)
                                self._log(ctx, meta)
                                logged = True
                                yield {
                                    "type": ERROR_EVENT,
                                    "error": self._parsed_body(e),
                                    "retryable": cls in (ErrorClass.RETRYABLE, ErrorClass.QUOTA),
                                    "status_code": e.status_code,
                                }
                                return
                            # 窗口内失败 → 正常分类处理（重试/切换/透传）
                            cls = self.runtime.classifier.classify(e)
                            summary = error_summary(e)
                            if cls is ErrorClass.CANCELED:
                                meta.status = "aborted"
                                meta.error_summary = summary
                                raise GatewayError(
                                    "上游已取消", status_code=e.status_code or 408,
                                    error_body=e.error_body, error_type=e.error_type) from e
                            if cls is ErrorClass.BAD_REQUEST:
                                meta.status = "failed"
                                meta.error_summary = summary
                                raise GatewayError(
                                    summary or "上游拒绝请求", status_code=e.status_code or 400,
                                    error_body=e.error_body, error_type=e.error_type) from e
                            if cls is ErrorClass.AUTH:
                                rec.errors.append(summary or "auth_error")
                                self.runtime.resources.disable(resource)
                                exits.append("AUTH")
                                switch = ("AUTH", False)
                                break
                            if cls is ErrorClass.NOT_FOUND:
                                rec.errors.append(summary or "not_found")
                                self.runtime.resources.invalidate(resource)
                                exits.append("NOT_FOUND")
                                switch = ("NOT_FOUND", False)
                                break
                            if cls is ErrorClass.QUOTA:
                                rec.errors.append(summary or "quota")
                                if quota_retries < snap.scheduling.quota_retry:
                                    quota_retries += 1
                                    delay = snap.scheduling.quota_backoff_base_seconds * (2 ** (quota_retries - 1))
                                    await self._sleep_interruptible(delay, ctx)
                                    continue
                                self.runtime.resources.bench(
                                    resource, self.runtime.resources.cooldown_seconds_for(resource, snap))
                                exits.append("QUOTA")
                                switch = ("QUOTA", True)
                                break
                            rec.errors.append(summary or "retryable")
                            c = self.runtime.resources.note_failure(resource, summary or "retryable")
                            if e.no_failover:
                                # 仅同资源重试（URL 下载失败换资源无帮助，tech §4.2）
                                if attempt == m + 1:
                                    exhausted = "RETRY_EXHAUSTED"
                                    terminal = True
                                    break
                                if snap.scheduling.retry_backoff_seconds > 0:
                                    await self._sleep_interruptible(snap.scheduling.retry_backoff_seconds, ctx)
                                continue
                            if c >= y:
                                self.runtime.resources.bench(
                                    resource, self.runtime.resources.cooldown_seconds_for(resource, snap))
                                exits.append("RETRYABLE_Y")
                                switch = ("RETRYABLE_Y", True)
                                break
                            if attempt == m + 1:
                                exhausted = "RETRY_EXHAUSTED"
                                break  # m 耗尽（C 仍 < y）→ 切下一资源，R 不冷却（§5.2）
                            if snap.scheduling.retry_backoff_seconds > 0:
                                await self._sleep_interruptible(snap.scheduling.retry_backoff_seconds, ctx)
                        finally:
                            await aclose_quiet(agen)
                finally:
                    self.runtime.resources.release(resource)
                # 切换续跑：记录切换事件（延迟到下一轮选路后落盘，to_resource =
                # 实际补位资源；terminal / 无资源补位时 to=None）
                if switch is not None or exhausted == "RETRY_EXHAUSTED":
                    rec.switched = True
                    meta.switch_count += 1
                    if not meta.error_summary and rec.errors:
                        meta.error_summary = rec.errors[-1]
                    reason_cls, was_cooldown = switch if switch is not None else ("RETRY_EXHAUSTED", False)
                    pending_switch = (rec.resource, reason_cls,
                                      rec.errors[-1] if rec.errors else None, was_cooldown)
                if terminal:
                    break

            if pending_switch is not None:  # 循环终止未选路（no_failover 耗尽等）：to=None
                self._emit_switch(ctx, pending_switch[0], None, pending_switch[1],
                                      pending_switch[2], pending_switch[3])
                pending_switch = None
            meta.status = "failed"
            meta.error_summary = meta.error_summary or (
                "请求总预算耗尽" if exhausted == "BUDGET_EXHAUSTED" else "无可用资源")
            raise GatewayError(
                meta.error_summary or "无可用资源",
                status_code=self._exit_status_code(exits, exhausted),
                exhausted_reason=exhausted or "NO_RESOURCE",
                system_model=ctx.system_model,
                attempts=[a.to_dict() for a in meta.attempts],
            )
        except asyncio.CancelledError:
            if not logged:
                meta.status = "aborted"
            raise
        finally:
            if not logged:  # 防双写：中途失败分支已落盘
                self._usage_from(None, meta, ir)  # vendor 已采则保留，否则本地估算
                self._log(ctx, meta)

    # —— 流式辅助 ——

    def _absorb_chunk(self, chunk: dict, meta: ExecMeta) -> None:
        """流式 usage / 文本累积（估算 token 与 vendor usage 捕获）。"""
        usage = chunk.get("usage")
        if isinstance(usage, dict):
            self._usage_from(usage, meta, _EMPTY_IR)
        else:
            for delta in _iter_deltas(chunk):
                # 估算口径对齐厂商：completion_tokens 含 reasoning_tokens（FR-3.12
                # aborted「含已产生的 token」；中途停止的思考流也应计入已产文本）
                for key in ("content", "reasoning_content"):
                    c = delta.get(key)
                    if isinstance(c, str):
                        meta.text_output += c

    @staticmethod
    def _tag_model(chunk: dict, ctx: CallCtx) -> dict:
        if "model" in chunk:
            chunk["model"] = ctx.system_model
        return chunk

    @staticmethod
    def _parsed_body(e: UpstreamError) -> Any:
        """中途失败 error 帧体：厂商原始错误不修饰（§6-b）。"""
        if e.error_body:
            try:
                return json.loads(e.error_body) if isinstance(e.error_body, str) else e.error_body
            except (json.JSONDecodeError, ValueError):
                return {"message": e.error_body}
        return {"message": str(e)}


class _EmptyIR:
    """_absorb_chunk 用占位（estimate_usage 仅读 body.messages）。"""

    body: dict = {}


_EMPTY_IR = _EmptyIR()


async def aclose_quiet(agen) -> None:
    """关闭未耗尽的出站流生成器（窗口失败重试前，防连接泄漏）。"""
    try:
        await agen.aclose()
    except Exception:  # noqa: BLE001
        pass
