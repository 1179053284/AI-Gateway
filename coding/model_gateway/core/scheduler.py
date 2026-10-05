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
import logging
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
    apply_spec_defaults,
    chunk_is_content,
    inject_reasoning_into_body,
    merge_reasoning,
)
from model_gateway.stats.aggregate import estimate_usage

logger = logging.getLogger("model_gateway")


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
        """统一 OpenAI 标准 error 格式（UT-09/INT-13：含网关模型名与原因摘要）。"""
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
                "ALL_OVER_CAPACITY": "没有可用资源承载得了本次请求所需的输出上限（已知装不下的候选已跳过，且当时没有其余可用候选）",
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
    provider: str | None = None  # 供应商展示名（资源 preset 口径，Q18-②）
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
            # 🔴 F1（面板修复轮-2）：原文案「（protocol 未实现）」是**误导** —— 协议常常
            #    已实现，真实成因是 `base_url` 为空被装配侧跳过，或适配器构造失败降级
            #    （两者都已不进 `/v1/models` + 出总览横幅，正常请求到不了这里；
            #    这里是直呼模型名的兜底文案）。有构造失败原因就带上，否则给准确的中性描述。
            errors = getattr(self.runtime, "_adapter_errors", None) or {}
            reason = errors.get(resource.rid)
            detail = f"（{reason}）" if reason else "（base_url 未配置或出站装配失败）"
            raise GatewayError(
                f"资源 '{resource.label}' 无可用出站适配器{detail} —— 见总览页配置告警横幅")
        return adapter

    def _key_value(self, resource) -> str:
        value = self.runtime.key_values.get(resource.rid)
        if value is None:
            raise GatewayError(f"资源 '{resource.label}' 的 Key 不存在（配置已变更）")
        return value

    def _out_body(self, ir: IRRequest, resource) -> dict:
        """每次尝试独立构造出站请求体（推理参数按当前资源默认重算，INT-37；
        网关级模型参数字段级注入：工具传参 > 网关设置 > 供应商通道默认，Q24，仅 chat）。"""
        body = dict(ir.body)
        body["model"] = resource.vendor_model
        if ir.endpoint == "chat":
            apply_model_params(body, self.runtime.model_params.get(ir.system_model))
            # 🔴 Q33-④：调用方与网关设置都没写输出上限时，按统一规格的**最大输出**注入。
            # 取的是**这条资源自己**的那份规格（`resource_specs`），不是模型级的池内最大
            # （R1-⑤：拿池内最大去请求一个上限更小的号 = 我主动制造 400）；
            # 规格里没有这个数就什么都不注入，继续走该供应商通道默认（不编数）。
            apply_spec_defaults(body, getattr(self.runtime, "resource_specs", {})
                                .get((resource.rid, resource.vendor_model)))
        # 🔴 查表带**网关模型**这一维（评审 R9-B-1'）：推理默认住在条目上
        #    （`(网关模型, 资源, 供应商模型名)`），别名时两个网关模型各填各的，少一维就会后写覆盖。
        merged = merge_reasoning(ir.reasoning, self.runtime.resource_reasoning.get(
            (ir.system_model, resource.rid, resource.vendor_model)))
        # 网关层档位兜底（v2.0 §13.2）：**只降不升**，就近取值。
        # 🔴 仅在"请求的档位不在该模型支持列表内"时才动 —— 工具已 clamp（值本身受支持）
        #    时原样透传，**不做二次 clamp**（§13.2 明确要求）。规范外档位原样保留。
        merged = self._degrade_effort_if_needed(merged, resource, ir.system_model)
        inject_reasoning_into_body(body, merged)
        return body

    def _degrade_effort_if_needed(self, spec, resource, system_model: str | None = None):
        """档位兜底（§13.2）：目标档不受支持 → 就近降级；受支持 → 原样透传。

        🔴 查表的第二级用**本次请求的网关模型**（`ir.system_model`），不是"这条资源在配置里
           挂到的第一个网关模型"（`_system_model_of`）：别名形状下两者不同 ⇒ 拿**另一家厂商**的
           档位表来降这一条请求的档，降什么结果取决于 `models[]` 的书写顺序（A2-P0-1 实测三态：
           静默失去兜底 / 支持档被别家表降掉 / 顺序翻转答案就翻转）。
        """
        if spec is None or not spec.effort:
            return spec
        pool = self.runtime.enum_pool
        entry = pool.get(resource.vendor_model) or \
            pool.get(system_model or self._system_model_of(resource))
        supported = list(getattr(entry, "effort_levels", None) or []) if entry else []
        if not supported:
            return spec  # 目录无档位信息 → 不臆断，原样透传
        # 🔴 关闭档不参与"就近升降"（升降的依据是强度序，关闭没有强度）；
        #    只在该厂商自己的表里**有**关闭词时，把网关规范词归一成它在册的那个词
        #    —— 这是在根因处把输入整形成上游能收的形状（PRD Q35-③），不是跳过它/瞒住判据。
        from model_gateway.core.dialects import CLOSED_LEVELS, is_closed
        if is_closed(spec.effort):
            if spec.effort in supported:
                return spec
            alias = next((w for w in supported if w.lower() in CLOSED_LEVELS), None)
            if alias is None:
                return spec        # 该厂商没有关闭词：原样透传，由通道的答复告诉我们（未知=不拦）
            from dataclasses import replace as _rep
            return _rep(spec, effort=alias)
        from dataclasses import replace

        from model_gateway.core.dialects import degrade_effort

        degraded = degrade_effort(spec.effort, supported)
        if degraded == spec.effort:
            return spec
        return replace(spec, effort=degraded)

    def _system_model_of(self, resource) -> str:
        for name, pool in self.runtime.resources.pools.items():
            if any(r.resource_id == resource.resource_id for r in pool):
                return name
        return ""

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
        """usage 落盘口径：供应商 usage 优先；缺失时本地估算（FR-5.8）。"""
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

    def _capacity_reject(self, ir: IRRequest, resource) -> str | None:
        """已知这条资源**承载不了**本次请求 ⇒ 返回可读原因（选路换下一条），否则 `None`。

        🔴 债务 Q33-债6-② 的落地口径（tech §22.5-9 第①条）——只用"我们真的知道的数"：
        - 只看 chat（图像/嵌入没有输出上限这回事）；
        - 请求里最终会带上的输出上限（调用方给的 `max_tokens` / `max_completion_tokens`，
          或网关设置 `params` 注入的）才是比较对象；
        - 该资源规格 `max_output` 为 `None`（目录没说、缓存也没有）⇒ **不知道 = 不拦**，
          照发。宁可吃上游一个可见的 400，也不凭空否决一条可能可用的资源 ——
          与 §12「消灭无报错的失败」同一条立意；
        - 缺省注入的那一份本来就取自**这条资源自己**的规格（R1-⑤），等值 ⇒ 不会自我否决。
        拦下时**不记失败、不计入 y、不冷却**：这不是上游故障，是网关已知的容量事实。
        """
        if ir.endpoint != "chat":
            return None
        body = dict(ir.body or {})
        apply_model_params(body, self.runtime.model_params.get(ir.system_model))
        # 🔴 复验轮 R5-2：`body.get("max_tokens", body.get(...))` 的默认值只在**键缺失**时生效，
        #    而工具/客户端会显式发 `"max_tokens": null` —— 那种情况下真正的上限在
        #    `max_completion_tokens` 上，旧写法读出 None ⇒ 该拦的不拦，白烧一次额度吃 400。
        asked = next((body.get(k) for k in ("max_tokens", "max_completion_tokens")
                      if body.get(k) is not None), None)
        if isinstance(asked, bool) or not isinstance(asked, int) or asked <= 0:
            return None
        spec = getattr(self.runtime, "resource_specs", {}).get(
            (resource.rid, resource.vendor_model))
        cap = getattr(spec, "max_output", None) if spec is not None else None
        if cap is None or asked <= cap:
            return None
        # 🔴 用界面同一把尺的名字（`label/供应商模型名`），不用裸 `res-xxxxxxxx`
        #    （评审 R8-报备 R-9：同一条链路上日志前缀、`GatewayError` 的"已尝试：资源B/glm-5.2×1"、
        #    请求日志与总览页都是 `resource_id_str`，这里掺裸 id 会让用户读到自己没起过的串）
        return (f"{resource.resource_id_str} 的最大输出上限 {cap} < 本次请求的输出上限 {asked}"
                f" ⇒ 承载不了，已换下一条（不记失败、不计入 y）")

    async def _execute_inner(self, ir: IRRequest, ctx: CallCtx,
                             call: Callable, meta: ExecMeta,
                             on_success: Callable[[dict, ExecMeta], None] | None = None) -> dict:
        snap = ctx.snapshot
        deadline = ctx.started_mono + snap.gateway.request_total_budget_seconds
        m = snap.scheduling.retry_per_request  # 全局唯一（Q18-③）
        y = snap.scheduling.fail_threshold
        tried: set[tuple[str, str]] = set()
        # 🔴 终局原因是 `ALL_OVER_CAPACITY` 的**唯一**形状：真的拦过至少一条（rejected）
        #    且从头到尾一次真实尝试都没发生（not attempted）。真机复验 R5-F-2 判死的是
        #    "初值 True"那种写法 —— 池空 / 产品位全关时第一轮 `pick_and_acquire` 直接返回
        #    `None`，一个布尔初值就把「没号可用」谎报成「所有号都装不下」，用户会照文案去
        #    调 `max_tokens` 而不是去把账号启用；这同时违反本节自己那句"故障与容量是两件事"。
        #    ⇒ 两个事实分开记，不靠一个初值替两者代言。
        capacity_rejected = False
        attempted = False
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
                exhausted = exhausted or (
                    "ALL_OVER_CAPACITY" if (capacity_rejected and not attempted)
                    else "NO_RESOURCE")
                break
            tried.add(resource.resource_id)
            # 🔴 出站承载校验（债务 Q33-债6-②，tech §22.5-9 第①条）：已知这条资源装不下
            #    本次请求 ⇒ 立刻归还、换下一条，**不产生任何失败记账**（一次成功的避开
            #    不该被算成一次故障，否则 y 会把用户刚配好的大窗口请求越用越窄地冷却掉）。
            reject = self._capacity_reject(ir, resource)
            if reject is not None:
                # 🔴 R5-1：`pick_and_acquire` 在同一个同步段里既 +1 在途**又预留了额度**
                #    （`reserve_quota`），所以避开这条腿必须成对归还两样东西。少归还预留 =
                #    每避开一次就有一个号被"已预留"吃满，最终谁也不派得到活，
                #    而界面还指着 `ALL_OVER_CAPACITY` 说谎（实测 reserved 1→2→3、hits 恒 0）。
                # 🔴 R5-4：**不往 `exits` 里塞中文说明** —— 那个列表是机器码集合
                #    （`_exit_status_code` 用 `all(e == "AUTH"/"QUOTA"/"NOT_FOUND")` 定 401/429/404），
                #    混进人类文案会让任何一次避开都退化成 503，把客户端的退避策略带偏。
                #    原因进日志与终局错误码，不进机器码集合。
                self.runtime.resources.release_quota(resource)
                self.runtime.resources.release(resource)
                logger.info("[选路] %s/%s：%s", ctx.system_model,
                            resource.resource_id_str, reject)
                capacity_rejected = True
                continue
            attempted = True
            rec = _ResourceAttempt(resource.resource_id_str)
            meta.attempts.append(rec)
            quota_retries = 0
            settled = False  # 额度预留结算标志：成功=转消耗，其余出口=释放（M5-3）
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
                            self.runtime.resources.disable(resource, summary or "auth_error")
                            exits.append("AUTH")
                            switch = ("AUTH", False)
                            break
                        if cls is ErrorClass.NOT_FOUND:
                            rec.errors.append(summary or "not_found")
                            self.runtime.resources.invalidate(resource, summary or "not_found")
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
                        # 额度**事后结算**：预留转实际消耗（未成功则在 finally 释放预留，M5-3）
                        self.runtime.resources.settle_quota(resource)
                        settled = True
                        meta.status = "success"
                        meta.final_resource = rec.resource
                        meta.provider = resource.vendor
                        meta.account = resource.account or None
                        # usage 在落盘前吸收（供应商值优先，缺失本地估算，FR-5.8）
                        self._usage_from(result.get("usage") if isinstance(result, dict) else None,
                                         meta, ir)
                        if on_success is not None:
                            on_success(result, meta)
                        return result
            finally:
                self.runtime.resources.release(resource)
                if not settled:
                    self.runtime.resources.release_quota(resource)
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
        """chat 非流式：返回供应商响应（已归一化思考字段），失败抛 GatewayError。"""

        async def call(resource, body: dict) -> dict:
            result = await self._adapter(resource).chat_nonstream(
                self._key_value(resource), resource.vendor_model, body,
                ctx.snapshot.gateway.attempt_timeout_seconds)
            if not isinstance(result, dict) or not chunk_is_content(result):
                # 🔴 零内容不得记 success（S-1，2026-10-05 架构审计）：上游回 200 但没有任何
                #    内容（choices 缺失 / 正文空 / 只剩信封壳）= 「无报错的失败」这一整类故障，
                #    旧实现照记 success 并把失败计数清零 ⇒ 故障自动切换在这类通道上失效，
                #    用户拿到一条空 200 而界面显示成功。现按**可重试类**抛出（502 → RETRYABLE）：
                #    同资源重试 m 次 → 计 C → 达 y 冷却换号；全部候选回空时客户端拿 503。
                #    判据与流式同一条谓词（`chunk_is_content`：正文/推理/工具调用任一即内容）；
                #    content_filter 带正文仍算成功（UT-16），带零正文按本条处理 ——
                #    「模型真的决定回空」与「通道回空」在网关侧不可区分，统一按故障换号。
                raise UpstreamError(
                    f"上游 200 但零内容（{resource.resource_id_str} 的响应没有正文/推理/工具调用）",
                    status_code=502, error_type="empty_content")
            return result

        result, meta = await self._execute(ir, ctx, call)
        self._usage_from(result.get("usage") if isinstance(result, dict) else None, meta, ir)
        if isinstance(result, dict):
            result["model"] = ctx.system_model  # 统一名替换厂商名（流式同规则 _tag_model）
        return result, meta

    async def execute_images(self, ir: IRRequest, ctx: CallCtx) -> tuple[dict, ExecMeta]:
        """images 生成：调度/重试/切换/取消同样适用（tech §4.1）。"""

        async def call(resource, body: dict) -> dict:
            result = await self._adapter(resource).images_generate(
                self._key_value(resource), resource.vendor_model, body,
                ctx.snapshot.gateway.attempt_timeout_seconds)
            data = result.get("data") if isinstance(result, dict) else None
            if not isinstance(data, list) or not data:
                # 🔴 零内容不得记 success（S-1，与 chat 同判）：images 空列表/缺 data 同属
                #    「通道回空」，按可重试抛出走重试/换号，不把空手而归记成成功。
                raise UpstreamError(
                    f"上游 200 但图像列表为空（{resource.resource_id_str} 的响应没有 data 项）",
                    status_code=502, error_type="empty_content")
            return result

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
        # 🔴 终局原因是 `ALL_OVER_CAPACITY` 的**唯一**形状：真的拦过至少一条（rejected）
        #    且从头到尾一次真实尝试都没发生（not attempted）。真机复验 R5-F-2 判死的是
        #    "初值 True"那种写法 —— 池空 / 产品位全关时第一轮 `pick_and_acquire` 直接返回
        #    `None`，一个布尔初值就把「没号可用」谎报成「所有号都装不下」，用户会照文案去
        #    调 `max_tokens` 而不是去把账号启用；这同时违反本节自己那句"故障与容量是两件事"。
        #    ⇒ 两个事实分开记，不靠一个初值替两者代言。
        capacity_rejected = False
        attempted = False
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
                    exhausted = exhausted or (
                        "ALL_OVER_CAPACITY" if (capacity_rejected and not attempted)
                        else "NO_RESOURCE")
                    break
                tried.add(resource.resource_id)
                # 🔴 承载校验与**非流那条同一条判据**（`_capacity_reject`），不在此重复
                #    规则；流式侧必须在**任何字节提交前**避开，否则失败无法回退。
                reject = self._capacity_reject(ir, resource)
                if reject is not None:
                    # 与上面非流那条**同一组归还动作**（额度预留 + 在途），且不写进机器码集合。
                    self.runtime.resources.release_quota(resource)
                    self.runtime.resources.release(resource)
                    logger.info("[选路·流式] %s/%s：%s", ctx.system_model,
                                resource.resource_id_str, reject)
                    capacity_rejected = True
                    continue
                attempted = True
                rec = _ResourceAttempt(resource.resource_id_str)
                meta.attempts.append(rec)
                quota_retries = 0
                stream_settled = False  # 额度预留结算标志（M5-3，与非流式路径对称）
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
                                    # 供应商 SSE 内 error 帧（INT-11 形态）→ 中途失败
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
                            if not committed:
                                # 🔴 零内容不得记 success（S-1，2026-10-05 架构审计）：一帧内容/
                                #    推理/工具调用都没收到就干净收尾 = 「通道回空」故障，与非流式
                                #    「200 零 choices」同判。旧实现照记 success 并把失败计数清零，
                                #    故障自动切换在这一整类上失效（R3 T-2 / R2a F-3 / Z20 实测）。
                                #    按可重试抛出（502 → RETRYABLE）：走既有窗口重试/换号机制，
                                #    客户端零感知；全部候选回空才以 503 终局。
                                raise UpstreamError(
                                    f"上游流已收尾但零内容"
                                    f"（{resource.resource_id_str} 未产生任何内容/推理/工具调用帧）",
                                    status_code=502, error_type="empty_content")
                            self.runtime.resources.note_success(resource)
                            self.runtime.resources.settle_quota(resource)  # 预留转消耗（M5-3）
                            stream_settled = True
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
                                self.runtime.resources.disable(resource, summary or "auth_error")
                                exits.append("AUTH")
                                switch = ("AUTH", False)
                                break
                            if cls is ErrorClass.NOT_FOUND:
                                rec.errors.append(summary or "not_found")
                                self.runtime.resources.invalidate(resource, summary or "not_found")
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
                    if not stream_settled:
                        self.runtime.resources.release_quota(resource)
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
                # 估算口径对齐供应商通道：completion_tokens 含 reasoning_tokens（FR-3.12
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
        """中途失败 error 帧体：供应商原始错误不修饰（§6-b）。"""
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
