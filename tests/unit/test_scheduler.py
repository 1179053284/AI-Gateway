"""调度状态机 UT（UT-03 ~ UT-11 / UT-16 / UT-17；纯内存，FakeAdapter 不触网）。"""

from __future__ import annotations

import asyncio

import pytest

from model_gateway.config.schemas import AppConfig
from model_gateway.core.errors import UpstreamError
from model_gateway.core.ir import IRRequest
from model_gateway.core.scheduler import CallCtx, GatewayError

from tests.unit.conftest import (
    DEFAULT_RESPONSE, FakeAdapter, build_runtime, chat_model, http_err, make_config,
)


def _ir(stream: bool = False) -> IRRequest:
    return IRRequest(system_model="test-model", endpoint="chat", stream=stream,
                     body={"messages": [{"role": "user", "content": "hi"}]})


def _ctx(cfg: AppConfig) -> CallCtx:
    return CallCtx.new(None, "test-model", "chat", False, cfg)


def _res(rt) -> dict:
    return {p.resource_id: p for p in rt.resources.registry.values()}


class TestYThreshold:
    """UT-03：默认 m=3,y=2 —— 连续 2 次失败 → 冷却 + 当次切 B。"""

    async def test_two_failures_cooldown_and_switch(self):
        adapter = FakeAdapter()
        adapter.set("sk-A", http_err(500, "internal_server_error"), http_err(500, "internal_server_error"))
        rt = build_runtime(make_config(models=[chat_model("test-model", "AB")]), adapter)
        cfg = rt.config

        result, meta = await rt.scheduler.execute_chat(_ir(), _ctx(cfg))

        assert result["choices"][0]["message"]["content"] == "ok"
        assert [a.resource for a in meta.attempts] == ["资源A/vm-A", "资源B/vm-B"]
        assert meta.attempts[0].attempts == 2  # 第 2 次失败后立即切 B
        assert meta.attempts[0].switched is True
        assert meta.attempts[1].attempts == 1
        assert meta.retry_count == 1
        assert meta.switch_count == 1
        assert meta.status == "success"
        res = _res(rt)
        assert res[("res-A", "vm-A")].status == "cooldown"
        assert rt.resources.cooldown_remaining_ms(res[("res-A", "vm-A")]) > 59_000  # ≈ now+60s
        assert len(rt.events.switches) == 1
        assert rt.events.switches[0]["reason_cls"] == "RETRYABLE_Y"

    async def test_switch_is_transparent(self):
        """INT-03 的 UT 前置：切换对调用方零感知（无异常暴露）。"""
        adapter = FakeAdapter()
        adapter.set("sk-A", http_err(500, "internal_server_error"))
        rt = build_runtime(make_config(models=[chat_model("test-model", "AB")]), adapter)
        result, _ = await rt.scheduler.execute_chat(_ir(), _ctx(rt.config))
        assert result["choices"][0]["message"]["content"] == "ok"


class TestMExhaustion:
    """UT-04：y=5,m=2（y>m+1）—— A 上 m+1=3 次失败后切 B，A 不冷却。"""

    async def test_m_exhaustion_switches_without_cooldown(self):
        adapter = FakeAdapter()
        adapter.set("sk-A", *(http_err(500, "internal_server_error") for _ in range(3)))
        rt = build_runtime(make_config(
            models=[chat_model("test-model", "AB")],
            scheduling={"fail_threshold": 5, "retry_per_request": 2}), adapter)
        cfg = rt.config

        result, meta = await rt.scheduler.execute_chat(_ir(), _ctx(cfg))

        assert result["choices"][0]["message"]["content"] == "ok"
        assert meta.attempts[0].attempts == 3  # 切换发生在第 3 次失败后
        assert meta.attempts[0].switched is True
        res = _res(rt)
        assert res[("res-A", "vm-A")].status == "active"  # 未冷却
        assert res[("res-A", "vm-A")].C == 3
        # 切换事件 reason = RETRY_EXHAUSTED（非 y 路径）
        assert rt.events.switches[0]["reason_cls"] == "RETRY_EXHAUSTED"

    async def test_all_resources_m_exhausted_unified_error(self):
        """m 耗尽且无资源可切 → 统一兜底错误。"""
        adapter = FakeAdapter()
        adapter.set("sk-A", *(http_err(500, "internal_server_error") for _ in range(4)))
        adapter.set("sk-B", *(http_err(500, "internal_server_error") for _ in range(4)))
        rt = build_runtime(make_config(
            models=[chat_model("test-model", "AB")],
            scheduling={"fail_threshold": 99, "retry_per_request": 3}), adapter)
        with pytest.raises(GatewayError) as ei:
            await rt.scheduler.execute_chat(_ir(), _ctx(rt.config))
        err = ei.value.to_openai_error()
        assert ei.value.exhausted_reason == "RETRY_EXHAUSTED"
        assert "test-model" in str(err)


class TestSuccessResetsC:
    """UT-05：成功清零 —— C=1 → 成功 → C=0；再失败 1 次不触发冷却。"""

    async def test_success_resets_counter(self):
        adapter = FakeAdapter()
        adapter.set("sk-A", http_err(500, "internal_server_error"))
        rt = build_runtime(make_config(models=[chat_model("test-model", "A")]), adapter)
        cfg = rt.config
        a = _res(rt)[("res-A", "vm-A")]

        # 请求 1：失败 1 次（C=1）→ 同资源重试成功
        result, meta = await rt.scheduler.execute_chat(_ir(), _ctx(cfg))
        assert meta.retry_count == 1
        assert a.C == 0  # 成功清零
        assert a.status == "active"

        # 请求 2：再失败 1 次（C=1）→ 重试成功，无冷却无切换
        adapter.set("sk-A", http_err(500, "internal_server_error"))
        await rt.scheduler.execute_chat(_ir(), _ctx(cfg))
        assert a.C == 0
        assert a.status == "active"
        assert rt.events.switches == []


class TestQuotaPath:
    """UT-06：QUOTA 路径 —— 429×(退避2+1) 耗尽 → 冷却 + 切换；plan/api 冷却时长。"""

    async def test_quota_backoff_then_cooldown_switch(self):
        adapter = FakeAdapter()
        adapter.set("sk-A", *(http_err(429, "quota_exceeded_error") for _ in range(3)))
        rt = build_runtime(make_config(
            models=[chat_model("test-model", "AB")],
            scheduling={"quota_retry": 2, "quota_backoff_base_seconds": 0.0}), adapter)
        cfg = rt.config

        result, meta = await rt.scheduler.execute_chat(_ir(), _ctx(cfg))

        assert result["choices"][0]["message"]["content"] == "ok"
        assert meta.attempts[0].attempts == 3  # 429×3（退避重试 2 次耗尽）
        assert meta.attempts[0].switched is True
        assert meta.retry_count == 2
        res = _res(rt)
        assert res[("res-A", "vm-A")].status == "cooldown"
        assert rt.events.switches[0]["reason_cls"] == "QUOTA"

    async def test_cooldown_duration_by_access_mode(self):
        """api 模式冷却 60s / plan 模式冷却 18000s。"""
        plan_res = {"id": "res-P", "name": "资源P", "access_mode": "plan",
                    "protocol": "openai", "base_url": "http://fake.local/v1",
                    "api_key": "sk-P"}
        cfg_dict = make_config(models=[chat_model("test-model", "AB")], scheduling={
            "quota_retry": 0})
        cfg_dict["resources"].append(plan_res)
        cfg_dict["models"][0]["resources"].append(
            {"resource": "res-P", "model": "vm-P"})
        adapter = FakeAdapter()
        adapter.set("sk-A", http_err(429, "quota_exceeded_error"))
        adapter.set("sk-P", http_err(429, "quota_exceeded_error"))
        rt = build_runtime(cfg_dict, adapter)
        adapter.script["sk-B"] = []  # B 直接成功
        # B 的脚本为空 → 默认成功；先 A 429 冷却切 B？quota_retry=0 → 立即冷却切换
        result, _ = await rt.scheduler.execute_chat(_ir(), _ctx(rt.config))
        assert result["choices"][0]["message"]["content"] == "ok"
        res = _res(rt)
        assert res[("res-A", "vm-A")].status == "cooldown"
        assert 59_000 < rt.resources.cooldown_remaining_ms(res[("res-A", "vm-A")]) <= 60_500

        # 构造 plan 资源独立触发（单独 runtime，P 冷却）
        adapter2 = FakeAdapter()
        adapter2.set("sk-P", http_err(429, "quota_exceeded_error"))
        cfg2 = make_config(models=[{"name": "m2", "endpoint": "chat", "resources": [
            {"resource": "res-P", "model": "vm-P"},
            {"resource": "res-B", "model": "vm-B"},
        ]}], scheduling={"quota_retry": 0})
        cfg2["resources"].append(plan_res)
        rt2 = build_runtime(cfg2, adapter2)
        await rt2.scheduler.execute_chat(
            IRRequest(system_model="m2", endpoint="chat", stream=False,
                      body={"messages": [{"role": "user", "content": "hi"}]}),
            CallCtx.new(None, "m2", "chat", False, rt2.config))
        p = rt2.resources.registry[("res-P", "vm-P")]
        assert p.status == "cooldown"
        assert rt2.resources.cooldown_remaining_ms(p) > 17_900_000  # plan 18000s


class TestAuthAndNotFound:
    """UT-07/UT-08：AUTH 停用 / NOT_FOUND 无效 —— 不重试、不计 C、切下一资源。"""

    async def test_auth_disables_resource(self):
        adapter = FakeAdapter()
        adapter.set("sk-A", http_err(401, "invalid_api_key"))
        rt = build_runtime(make_config(models=[chat_model("test-model", "AB")]), adapter)
        result, meta = await rt.scheduler.execute_chat(
            _ir(), _ctx(rt.config))
        assert result["choices"][0]["message"]["content"] == "ok"
        assert meta.attempts[0].attempts == 1  # 不重试
        res = _res(rt)
        a = res[("res-A", "vm-A")]
        assert a.status == "disabled"
        assert a.C == 0  # 不计 C
        assert rt.events.switches[0]["reason_cls"] == "AUTH"
        # 后续请求不再选 A
        await rt.scheduler.execute_chat(_ir(), _ctx(rt.config))
        assert all(c[0] != "sk-A" for c in adapter.calls[1:])

    async def test_not_found_invalidates_resource(self):
        adapter = FakeAdapter()
        adapter.set("sk-A", http_err(404, "not_found_error"))
        rt = build_runtime(make_config(models=[chat_model("test-model", "AB")]), adapter)
        result, meta = await rt.scheduler.execute_chat(
            _ir(), _ctx(rt.config))
        assert result["choices"][0]["message"]["content"] == "ok"
        assert meta.attempts[0].attempts == 1
        assert _res(rt)[("res-A", "vm-A")].status == "invalid"
        assert _res(rt)[("res-A", "vm-A")].C == 0
        assert rt.events.switches[0]["reason_cls"] == "NOT_FOUND"


class TestNoResourceFallback:
    """UT-09：全部资源不可用 → 统一「无可用资源」错误（OpenAI 格式，不挂起）。"""

    async def test_all_cooldown_unified_error(self):
        adapter = FakeAdapter()
        adapter.set("sk-A", http_err(429, "quota_exceeded_error"))
        rt = build_runtime(make_config(
            models=[chat_model("test-model", "A")], scheduling={"quota_retry": 0}), adapter)
        with pytest.raises(GatewayError) as ei:
            await rt.scheduler.execute_chat(_ir(), _ctx(rt.config))
        # 第一次：A 冷却 → 无资源 → 兜底
        assert ei.value.status_code == 429  # 全部 QUOTA 出口
        assert ei.value.exhausted_reason == "NO_RESOURCE"

    async def test_error_body_openai_format(self):
        adapter = FakeAdapter()
        adapter.set("sk-A", http_err(429, "quota_exceeded_error"))
        rt = build_runtime(make_config(
            models=[chat_model("test-model", "A")], scheduling={"quota_retry": 0}), adapter)
        try:
            await rt.scheduler.execute_chat(_ir(), _ctx(rt.config))
        except GatewayError as e:
            body = e.to_openai_error()
            assert set(body) == {"error"}
            assert body["error"]["system_model"] == "test-model"
            assert body["error"]["code"] == "NO_RESOURCE"
            assert "已尝试" in body["error"]["message"]
            assert "资源A/vm-A" in body["error"]["message"]
            return
        pytest.fail("应抛出 GatewayError")


class TestCooldownLazyRecovery:
    """UT-10：冷却到期懒恢复 —— 到期后选路回 A（原优先级归位）。"""

    async def test_lazy_recovery_returns_to_a(self):
        adapter = FakeAdapter()
        adapter.set("sk-A", http_err(429, "quota_exceeded_error"))
        rt = build_runtime(make_config(
            models=[chat_model("test-model", "AB")], scheduling={"quota_retry": 0}), adapter)
        cfg = rt.config
        await rt.scheduler.execute_chat(_ir(), _ctx(cfg))  # A 冷却，B 承接

        clock = [1000.0]
        rt.resources.clock = lambda: clock[0]
        a = _res(rt)[("res-A", "vm-A")]
        a.cooldown_until = clock[0] - 1  # 已到期

        adapter.calls.clear()
        await rt.scheduler.execute_chat(_ir(), _ctx(cfg))
        assert adapter.calls[0][0] == "sk-A"  # 到期归位：直接回 A


class TestCAccumulationAcrossRequests:
    """UT-11：C 跨请求累计 —— 请求 1 在 A 上失败后切走（C 留存），请求 2 再失败即命中 y。

    注：请求以 A 成功结束时 C 必清零（UT-05），故本用例用 m=0（每资源 1 次尝试）
    构造「A 失败 1 次 → m 耗尽切 B 成功」让 C=1 留存（B 成功只清 B 的 C）。
    """

    async def test_c_accumulates_across_requests(self):
        adapter = FakeAdapter()
        # 请求 1：A 失败 1 次（C=1）→ m 耗尽切 B → B 成功（A 的 C 留存）
        adapter.set("sk-A", http_err(500, "internal_server_error"))
        rt = build_runtime(make_config(
            models=[chat_model("test-model", "AB")],
            scheduling={"retry_per_request": 0}), adapter)
        cfg = rt.config
        result, meta1 = await rt.scheduler.execute_chat(_ir(), _ctx(cfg))
        assert result["choices"][0]["message"]["content"] == "ok"
        assert meta1.switch_count == 1  # A→B 切换
        a = _res(rt)[("res-A", "vm-A")]
        assert a.C == 1

        # 请求 2：A 再失败 1 次 → C=2 命中 y → A 冷却；B 承接成功
        adapter.set("sk-A", http_err(500, "internal_server_error"))
        result, meta2 = await rt.scheduler.execute_chat(_ir(), _ctx(cfg))
        assert result["choices"][0]["message"]["content"] == "ok"
        assert a.status == "cooldown"
        assert a.C == 2
        assert meta2.attempts[0].resource == "资源A/vm-A"
        assert meta2.attempts[1].resource == "资源B/vm-B"
        assert rt.events.switches[-1]["reason_cls"] == "RETRYABLE_Y"


class TestContentFilter:
    """UT-16：finish_reason=content_filter → 正常结束不算失败、不切换。"""

    async def test_content_filter_success_no_switch(self):
        adapter = FakeAdapter()
        cf = {**DEFAULT_RESPONSE,
              "choices": [{"index": 0, "message": {"role": "assistant", "content": "filtered"},
                           "finish_reason": "content_filter"}]}
        adapter.set("sk-A", cf)
        rt = build_runtime(make_config(models=[chat_model("test-model", "A")]), adapter)
        result, meta = await rt.scheduler.execute_chat(
            _ir(), _ctx(rt.config))
        assert meta.status == "success"
        assert meta.switch_count == 0
        assert result["choices"][0]["finish_reason"] == "content_filter"
        assert rt.events.switches == []


class TestGlobalResourceState:
    """UT-17：全局资源状态一致性 —— 同一资源映射 M1/M2，在 M1 冷却 → M2 选路同步跳过。"""

    async def test_cooldown_shared_across_system_models(self):
        adapter = FakeAdapter()
        # M1 的请求在 A 上 429 → 冷却
        adapter.set("sk-A", http_err(429, "quota_exceeded_error"))
        rt = build_runtime(make_config(
            models=[
                chat_model("M1", "AB"),
                chat_model("M2", "AB"),
            ], scheduling={"quota_retry": 0}), adapter)
        await rt.scheduler.execute_chat(
            IRRequest(system_model="M1", endpoint="chat", stream=False,
                      body={"messages": [{"role": "user", "content": "hi"}]}),
            CallCtx.new(None, "M1", "chat", False, rt.config))
        a = rt.resources.registry[("res-A", "vm-A")]
        assert a.status == "cooldown"

        # M2 选路同步跳过 A（同一次计数、同一次冷却）
        adapter.calls.clear()
        await rt.scheduler.execute_chat(
            IRRequest(system_model="M2", endpoint="chat", stream=False,
                      body={"messages": [{"role": "user", "content": "hi"}]}),
            CallCtx.new(None, "M2", "chat", False, rt.config))
        assert adapter.calls[0][0] == "sk-B"


class TestNoFailover:
    """INT-31 的 UT 前置：no_failover 错误仅同资源重试，m 耗尽兜底、不切资源。"""

    async def test_no_failover_retries_same_resource_only(self):
        adapter = FakeAdapter()
        adapter.set("sk-A", *(UpstreamError("image_url download failed: ConnectError",
                                            no_failover=True) for _ in range(4)))
        rt = build_runtime(make_config(models=[chat_model("test-model", "AB")]), adapter)
        with pytest.raises(GatewayError) as ei:
            await rt.scheduler.execute_chat(_ir(), _ctx(rt.config))
        assert ei.value.exhausted_reason == "RETRY_EXHAUSTED"
        # 全部 4 次尝试（m+1）都落在 A，B 从未被触达
        assert [c[0] for c in adapter.calls] == ["sk-A"] * 4
        assert _res(rt)[("res-A", "vm-A")].C == 4


class TestBudget:
    """预算耗尽的 UT 前置（完整链路见 INT-25）。"""

    async def test_budget_exhausted_before_first_attempt(self):
        adapter = FakeAdapter()
        adapter.set("sk-A", http_err(500, "internal_server_error"))
        rt = build_runtime(make_config(
            models=[chat_model("test-model", "A")],
            gateway={"request_total_budget_seconds": 60, "attempt_timeout_seconds": 60}), adapter)
        ctx = CallCtx.new(None, "test-model", "chat", False, rt.config)
        ctx.started_mono = -(10 ** 12)  # 远古开始时间 → 已超预算
        with pytest.raises(GatewayError) as ei:
            await rt.scheduler.execute_chat(_ir(), ctx)
        assert ei.value.exhausted_reason == "BUDGET_EXHAUSTED"
        assert adapter.calls == []  # 未触达上游
        assert rt.events.requests[-1]["status"] == "failed"


class TestEventLogging:
    """事件落盘字段（配合 INT-01 / UT-15）。"""

    async def test_success_event_logged(self):
        adapter = FakeAdapter()
        rt = build_runtime(make_config(models=[chat_model("test-model", "A")]), adapter)
        await rt.scheduler.execute_chat(_ir(), _ctx(rt.config))
        assert len(rt.events.requests) == 1
        ev = rt.events.requests[0]
        assert ev["status"] == "success"
        assert ev["final_resource"] == "资源A/vm-A"
        assert ev["resource_attempts"] == [
            {"resource": "资源A/vm-A", "attempts": 1, "errors": [], "switched": False}]
        assert ev["usage_source"] == "vendor"
        assert ev["input_tokens"] == 10 and ev["output_tokens"] == 5
        assert ev["duration_ms"] >= 0
        assert ev["system_model"] == "test-model"

    async def test_usage_estimated_when_vendor_omits(self):
        adapter = FakeAdapter()
        adapter.set("sk-A", {"id": "x", "choices": [{"index": 0, "message": {
            "role": "assistant", "content": "你好"}, "finish_reason": "stop"}]})  # 无 usage
        rt = build_runtime(make_config(models=[chat_model("test-model", "A")]), adapter)
        await rt.scheduler.execute_chat(_ir(), _ctx(rt.config))
        ev = rt.events.requests[0]
        assert ev["usage_source"] == "estimated"
        assert ev["input_tokens"] > 0 and ev["output_tokens"] > 0

    async def test_images_count_in_event(self):
        """images 成功 → 事件行 images_count = data 数量（E2E 实测回归：
        曾因赋值晚于 _execute 落盘而恒为 None，改 on_success 时机修复）。"""
        adapter = FakeAdapter()
        adapter.set("sk-A", {"data": [{"url": "https://x/1.png"}, {"url": "https://x/2.png"}]})
        rt = build_runtime(make_config(models=[chat_model("img-model", "A", endpoint="images")]),
                           adapter)
        ir = IRRequest(system_model="img-model", endpoint="images", stream=False, body={})
        ctx = CallCtx.new(None, "img-model", "images", False, rt.config)
        await rt.scheduler.execute_images(ir, ctx)
        ev = rt.events.requests[0]
        assert ev["status"] == "success"
        assert ev["images_count"] == 2


class TestClientDisconnect:
    """断连中止（CancelledError 绝不吞，tech §8-1）的 UT 前置。"""

    async def test_disconnected_before_pick_aborts(self):
        adapter = FakeAdapter()
        rt = build_runtime(make_config(models=[chat_model("test-model", "A")]), adapter)
        ctx = CallCtx.new(None, "test-model", "chat", False, rt.config,
                          check_disconnected=lambda: True)
        with pytest.raises(asyncio.CancelledError):
            await rt.scheduler.execute_chat(_ir(), ctx)
        assert adapter.calls == []
        ev = rt.events.requests[0]
        assert ev["status"] == "aborted"
        assert rt.resources.registry[("res-A", "vm-A")].C == 0
        assert rt.resources.registry[("res-A", "vm-A")].in_flight == 0
