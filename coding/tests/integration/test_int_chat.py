"""INT 非流式链路（INT-01~07 / INT-13 / INT-23 / INT-25 / INT-27 / INT-29 / INT-34）。

通用前置：网关（随机端口）+ FakeVendor（随机端口）；m=3、y=2、冷却 60s（默认）。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tests.integration.conftest import chat_res, gateway_config
from tests.integration.fakevendor import Err, Ok

CHAT_URL = "/v1/chat/completions"


def _body(model: str = "test-model", **over) -> dict:
    d = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    d.update(over)
    return d


async def _chat(client, gw, body: dict, token: str | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    return await client.post(f"{gw.base_url}{CHAT_URL}", json=body, headers=headers)


class TestBaseline:
    """INT-01：非流式成功基线。"""

    async def test_success_baseline(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="hello"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        resp = await _chat(client, gw, _body())
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "hello"
        assert data["model"] == "test-model"  # 统一名替换厂商名

        await gw.drain_events()
        events = gw.read_events()
        assert len(events) == 1
        ev = events[0]
        assert ev["status"] == "success"
        assert ev["system_model"] == "test-model"
        assert ev["final_resource"] == "资源A/vm-A"
        assert ev["resource_attempts"] == [
            {"resource": "资源A/vm-A", "attempts": 1, "errors": [], "switched": False}]
        assert ev["input_tokens"] == 10 and ev["output_tokens"] == 5  # vendor usage
        assert ev["usage_source"] == "vendor"
        assert ev["duration_ms"] >= 0

    async def test_usage_estimated_when_vendor_omits(self, vendor, make_gateway, client):
        """INT-18 ②：厂商无 usage → 本地估算标注。"""
        vendor.set("sk-A", Ok(content="你好世界", usage=False))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await _chat(client, gw, _body())
        assert resp.status_code == 200
        await gw.drain_events()
        ev = gw.read_events()[0]
        assert ev["usage_source"] == "estimated"
        assert ev["input_tokens"] > 0 and ev["output_tokens"] > 0


class TestRetryNoSwitch:
    """INT-02：请求级重试无感（同资源失败后重试成功）。"""

    async def test_retry_transparent(self, vendor, make_gateway, client):
        vendor.set("sk-A", Err(500), Ok(content="recovered"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        resp = await _chat(client, gw, _body())
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "recovered"

        await gw.drain_events()
        ev = gw.read_events()[0]
        assert ev["status"] == "success"
        assert ev["retry_count"] == 1
        assert ev["switch_count"] == 0
        a = gw.resource("res-A")
        assert a.C == 0  # 成功清零（UT-05 定案；INT-02 原描述「C(A)=1」已过时）
        assert a.status == "active"


class TestFailoverSwitch:
    """INT-03：切换续跑（核心）——A 恒 500 → 冷却切 B，客户端零感知。"""

    async def test_switch_transparent(self, vendor, make_gateway, client):
        vendor.set("sk-A", Err(500))
        vendor.set("sk-B", Ok(content="from-B"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        resp = await _chat(client, gw, _body())
        assert resp.status_code == 200  # 无任何错误暴露
        assert resp.json()["choices"][0]["message"]["content"] == "from-B"

        await gw.drain_events()
        ev = gw.read_events()[0]
        assert ev["status"] == "success"
        assert ev["final_resource"] == "资源B/vm-B"
        assert ev["switch_count"] == 1
        # A 尝试 2 次（C=2 冷却）后切换
        assert ev["resource_attempts"][0] == {
            "resource": "资源A/vm-A", "attempts": 2,
            "errors": ev["resource_attempts"][0]["errors"], "switched": True}
        assert ev["resource_attempts"][0]["attempts"] == 2
        a = gw.resource("res-A")
        assert a.status == "cooldown"

        switches = gw.read_switches()
        assert len(switches) == 1
        assert switches[0]["reason_cls"] == "RETRYABLE_Y"
        assert switches[0]["from_resource"] == "资源A/vm-A"
        assert switches[0]["was_cooldown"] is True


class TestQuotaBackoff:
    """INT-04：429 退避路径。"""

    async def test_429_backoff_then_cooldown_switch(self, vendor, make_gateway, client):
        vendor.set("sk-A", Err(429, "quota_exceeded_error"))
        vendor.set("sk-B", Ok(content="quota-B"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")],
                                               scheduling={"quota_retry": 2,
                                                           "quota_backoff_base_seconds": 0.05}))
        resp = await _chat(client, gw, _body())
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "quota-B"
        await gw.drain_events()
        ev = gw.read_events()[0]
        assert ev["resource_attempts"][0]["attempts"] == 3  # 429×3（退避 2 次耗尽）
        assert ev["switch_count"] == 1
        assert gw.read_switches()[0]["reason_cls"] == "QUOTA"
        assert gw.resource("res-A").status == "cooldown"


class TestAuthAndInvalid:
    """INT-05 / INT-06：401 停用 / 404 无效标记（不重试、切下一资源）。"""

    async def test_401_disables(self, vendor, make_gateway, client):
        vendor.set("sk-A", Err(401, "invalid_api_key"))
        vendor.set("sk-B", Ok(content="B"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        resp = await _chat(client, gw, _body())
        assert resp.status_code == 200
        await gw.drain_events()
        ev = gw.read_events()[0]
        assert ev["resource_attempts"][0]["attempts"] == 1  # 无重试
        assert gw.resource("res-A").status == "disabled"
        assert gw.resource("res-A").C == 0
        assert gw.read_switches()[0]["reason_cls"] == "AUTH"

        # 后续请求不再选 A（reset 清空记录后仅 B 被触达）
        vendor.reset()
        vendor.set("sk-B", Ok(content="B"))
        await _chat(client, gw, _body())
        assert [r.key for r in vendor.requests] == ["sk-B"]

    async def test_404_invalidates(self, vendor, make_gateway, client):
        vendor.set("sk-A", Err(404, "not_found_error"))
        vendor.set("sk-B", Ok(content="B"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        resp = await _chat(client, gw, _body())
        assert resp.status_code == 200
        await gw.drain_events()
        assert gw.resource("res-A").status == "invalid"
        assert gw.read_switches()[0]["reason_cls"] == "NOT_FOUND"


class TestBadRequestPassthrough:
    """INT-07：400 原样透传（同状态码 + 原错误体；不切换、不重试、C 不变）。"""

    async def test_400_passthrough(self, vendor, make_gateway, client):
        vendor.set("sk-A", Err(400, "invalid_request_error", "bad input shape"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        resp = await _chat(client, gw, _body())
        assert resp.status_code == 400
        err = resp.json()["error"]
        assert err["type"] == "invalid_request_error"
        assert err["message"] == "bad input shape"
        # 不切换：B 从未被触达
        assert all(r.key != "sk-B" for r in vendor.requests)
        assert gw.resource("res-A").C == 0
        await gw.drain_events()
        assert gw.read_events()[0]["status"] == "failed"


class TestAllResourcesDown:
    """INT-13：全部资源不可用 → 统一兜底（不挂起）。"""

    async def test_all_down_unified_error(self, vendor, make_gateway, client):
        vendor.set("sk-A", Err(500))
        vendor.set("sk-B", Err(500))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        resp = await _chat(client, gw, _body())
        assert resp.status_code == 503
        err = resp.json()["error"]
        assert err["system_model"] == "test-model"
        assert "已尝试" in err["message"]
        assert err["code"] == "NO_RESOURCE"

    async def test_budget_exhausted_error(self, vendor, make_gateway, client):
        """INT-25：总预算耗尽 → 统一错误（预算耗尽），总耗时 ≈ 预算。

        y=99 防止冷却耗尽资源（保证预算先到）；m=3 + backoff 0.5s 拉长尝试链。
        """
        import time
        vendor.set("sk-A", Err(500))
        vendor.set("sk-B", Err(500))
        gw = await make_gateway(gateway_config(
            vendor.port, models=[chat_res("AB")],
            gateway={"request_total_budget_seconds": 2, "attempt_timeout_seconds": 1},
            scheduling={"retry_backoff_seconds": 0.5, "fail_threshold": 99}))
        t0 = time.monotonic()
        resp = await _chat(client, gw, _body())
        elapsed = time.monotonic() - t0
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "BUDGET_EXHAUSTED"
        assert elapsed < 4.0  # 不挂起（≈2s 预算 + 收尾余量）
        await gw.drain_events()
        ev = gw.read_events()[0]
        assert ev["status"] == "failed"
        assert ev["resource_attempts"]  # 已完成尝试明细


class TestUnknownModel:
    """INT-23：入站未知模型 → 404 + 候选；不触达上游。"""

    async def test_unknown_model_404(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok())
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        resp = await _chat(client, gw, _body(model="no-such-model-xyz"))
        assert resp.status_code == 404
        err = resp.json()["error"]
        assert err["code"] == "model_not_found"
        assert "no-such-model-xyz" in err["message"]
        assert "candidates" in err  # 候选列表
        assert vendor.requests == []  # 不触达上游


class TestKeyMasking:
    """INT-27：Key 脱敏（事件 JSONL 无明文 Key）。"""

    async def test_no_plaintext_key_in_artifacts(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="x"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        await _chat(client, gw, _body())
        await gw.drain_events()
        for path in Path(gw.usage_dir).iterdir():
            text = path.read_text(encoding="utf-8")
            assert "sk-A" not in text, f"{path.name} 泄漏明文 Key"

    async def test_admin_config_masks_keys(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok())
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")],
                                               gateway={"access_tokens": [
                                                   {"id": "t1", "value": "gw-token-1"}]}))
        resp = await client.get(f"{gw.base_url}/admin/api/config")
        assert resp.status_code == 200
        text = json.dumps(resp.json(), ensure_ascii=False)
        assert "sk-A" not in text
        assert "****" in text  # 脱敏形态（短 key 全掩码）


class TestAdminStatusAndSwitchEvents:
    """INT-29：切换事件独立记录 + admin 状态端点。"""

    async def test_switch_events_and_admin_status(self, vendor, make_gateway, client):
        vendor.set("sk-A", Err(500))
        vendor.set("sk-B", Ok(content="B"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")],
                                                gateway={"access_tokens": [
                                                    {"id": "t1", "value": "gw-token-1"}]}))
        await _chat(client, gw, _body(), token="gw-token-1")
        await gw.drain_events()

        # admin 状态（overview）：A 冷却中 + 最近切换事件（资源健康按资源聚合口径）
        resp = await client.get(f"{gw.base_url}/admin/api/overview",
                                headers={"Authorization": "Bearer gw-token-1"})
        assert resp.status_code == 200
        data = resp.json()
        a = next(r for r in data["resources"] if r["name"] == "资源A")
        assert a["status"] == "cooldown"
        assert a["cooldown_remaining_ms"] > 0
        assert data["recent_switch_events"]
        sw = data["recent_switch_events"][0]
        assert sw["from_resource"] == "资源A/vm-A"
        assert sw["reason_cls"] == "RETRYABLE_Y"

        # switch-events JSONL 新增 1 行且字段完整
        switches = gw.read_switches()
        assert len(switches) == 1
        assert {"ts", "request_id", "system_model", "from_resource", "to_resource",
                "reason_cls", "error_summary", "was_cooldown"} <= set(switches[0])


class TestErrorRulesE2E:
    """INT-34：error_rules 覆写端到端（400 failed_precondition_error → RETRYABLE）。"""

    async def test_override_to_retryable(self, vendor, make_gateway, client):
        vendor.set("sk-A", Err(400, "failed_precondition_error"), Ok(content="after-override"))
        gw = await make_gateway(gateway_config(
            vendor.port, models=[chat_res("AB")],
            error_rules=[{"http": 400, "type": "failed_precondition_error",
                          "class": "RETRYABLE"}]))
        resp = await _chat(client, gw, _body())
        assert resp.status_code == 200  # 同资源重试后成功（非 400 透传）
        assert resp.json()["choices"][0]["message"]["content"] == "after-override"
        await gw.drain_events()
        ev = gw.read_events()[0]
        assert ev["retry_count"] == 1
        assert gw.read_switches() == []  # 未切换
        assert gw.resource("res-A").C == 0  # 成功清零（覆写路径同样计入失败后清零）

    async def test_without_override_is_passthrough(self, vendor, make_gateway, client):
        """对照组：不配置覆写 → 400 原样透传（与 UT-19 分层验证）。"""
        vendor.set("sk-A", Err(400, "failed_precondition_error"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        resp = await _chat(client, gw, _body())
        assert resp.status_code == 400


class TestReasoningParams:
    """INT-36：推理参数三级合并端到端（资源默认 + 请求覆盖）。"""

    async def test_three_level_merge(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="r"))
        vendor.set("sk-B", Ok(content="r"))
        cfg = gateway_config(vendor.port, models=[{
            "name": "test-model", "endpoint": "chat",
            "resources": [
                {"resource": "res-A", "model": "vm-A",
                 "reasoning": {"enabled": True, "effort": "low"}},
                {"resource": "res-B", "model": "vm-B"},
            ]}])
        gw = await make_gateway(cfg)

        # ① 请求不带推理字段 → A 出站资源默认（enabled+low）
        await _chat(client, gw, _body())
        a_body = vendor.bodies_for("sk-A")[0]
        assert a_body["thinking"] == {"type": "enabled"}
        assert a_body["reasoning_effort"] == "low"

        # ② 请求带 reasoning_effort=high → 出站 high（请求级覆盖资源默认）
        await _chat(client, gw, _body(reasoning_effort="high"))
        a_body2 = vendor.bodies_for("sk-A")[1]
        assert a_body2["reasoning_effort"] == "high"
        assert a_body2["thinking"] == {"type": "enabled"}  # 未指定字段走资源默认

        # ③ B 无默认 → 不注入（厂商默认）；串行请求恒选 A（平局取优先级），
        # 故先让 A 恒 500 触发切换，B 承接后检查出站体
        vendor.set("sk-A", Err(500))
        resp = await _chat(client, gw, _body())
        assert resp.status_code == 200
        b_body = vendor.bodies_for("sk-B")[0]
        assert "thinking" not in b_body and "reasoning_effort" not in b_body

    async def test_request_override_reaches_upstream(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="r"))
        cfg = gateway_config(vendor.port, models=[{
            "name": "test-model", "endpoint": "chat",
            "resources": [
                {"resource": "res-A", "model": "vm-A",
                 "reasoning": {"enabled": True, "effort": "low"}}]}])
        gw = await make_gateway(cfg)
        # 请求覆盖：thinking disabled + effort high
        await _chat(client, gw, _body(thinking={"type": "disabled"}, reasoning_effort="high"))
        body = vendor.bodies_for("sk-A")[0]
        assert body["thinking"] == {"type": "disabled"}  # 显式关闭优先于资源默认开启
        assert body["reasoning_effort"] == "high"
        assert "reasoning" not in body  # 防双重注入：提升后不再透传原始字段


class TestSwitchReMergesReasoning:
    """INT-37：切换续跑按目标资源重算推理参数。"""

    async def test_remerge_on_switch(self, vendor, make_gateway, client):
        vendor.set("sk-A", Err(500))
        vendor.set("sk-B", Ok(content="B"))
        cfg = gateway_config(vendor.port, models=[{
            "name": "test-model", "endpoint": "chat",
            "resources": [
                {"resource": "res-A", "model": "vm-A",
                 "reasoning": {"effort": "low"}},
                {"resource": "res-B", "model": "vm-B",
                 "reasoning": {"effort": "high"}},
            ]}])
        gw = await make_gateway(cfg)
        # 请求不带推理字段；A 恒 500 → y 切换至 B
        resp = await _chat(client, gw, _body())
        assert resp.status_code == 200
        a_body = vendor.bodies_for("sk-A")[0]
        b_body = vendor.bodies_for("sk-B")[0]
        assert a_body["reasoning_effort"] == "low"  # A 尝试时按 A 默认
        assert b_body["reasoning_effort"] == "high"  # 切到 B 后按 B 默认重算


class TestModelParamsInjection:
    """Q24：网关级模型参数注入端到端（工具传参 > 网关设置 > 厂商内置；仅 chat）。"""

    async def test_inject_and_request_override(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="r"))
        cfg = gateway_config(vendor.port, models=[
            chat_res("A", params={"temperature": 0.3, "max_tokens": 99})])
        gw = await make_gateway(cfg)
        # ① 请求不带参数 → 网关设置注入出站
        await _chat(client, gw, _body())
        b1 = vendor.bodies_for("sk-A")[0]
        assert b1["temperature"] == 0.3 and b1["max_tokens"] == 99
        # ② 请求带 temperature → 请求值优先；未带键（max_tokens）仍注入
        await _chat(client, gw, _body(temperature=0.7))
        b2 = vendor.bodies_for("sk-A")[1]
        assert b2["temperature"] == 0.7 and b2["max_tokens"] == 99

    async def test_reasoning_effort_priority_resource_default_over_params(
            self, vendor, make_gateway, client):
        """🔴 两处都能配 `reasoning_effort` 时的定序（PRD FR-3.16 / Q15 为准，本轮定论）。

        生效序 = **请求级 > 资源级默认 > 参数卡（网关设置）> 厂商内置**：
        资源级默认更具体（"免费资源默认 low 省额度、主力资源默认 max"），
        所以它盖过参数卡；参数卡盖不过时由 `param_shadowed` 告警说明（§21 / BUG-2 可见性）。
        """
        vendor.set("sk-A", Ok(content="r"))
        cfg = gateway_config(vendor.port, models=[{
            "name": "test-model", "endpoint": "chat",
            "params": {"reasoning_effort": "max"},          # 参数卡（网关设置）
            "resources": [
                {"resource": "res-A", "model": "vm-A",
                 "reasoning": {"enabled": True, "effort": "low"}}]}])  # 资源级默认
        gw = await make_gateway(cfg)
        try:
            # ① 请求不指定 → 资源级默认赢过参数卡
            await _chat(client, gw, _body())
            assert vendor.bodies_for("sk-A")[0]["reasoning_effort"] == "low"
            # ② 请求指定 → 请求级最高，两者都盖
            await _chat(client, gw, _body(reasoning_effort="high"))
            assert vendor.bodies_for("sk-A")[1]["reasoning_effort"] == "high"
        finally:
            await gw.stop()

    async def test_params_reasoning_applies_when_no_resource_default(
            self, vendor, make_gateway, client):
        """资源级未配推理 → 参数卡的 `reasoning_effort` 正常生效（不得一律忽略）。"""
        vendor.set("sk-A", Ok(content="r"))
        cfg = gateway_config(vendor.port, models=[
            chat_res("A", params={"reasoning_effort": "max"})])
        gw = await make_gateway(cfg)
        try:
            await _chat(client, gw, _body())
            assert vendor.bodies_for("sk-A")[0]["reasoning_effort"] == "max"
        finally:
            await gw.stop()

    async def test_no_params_passthrough(self, vendor, make_gateway, client):
        """网关未配置 params → 不注入任何键（走厂商内置默认）。"""
        vendor.set("sk-A", Ok(content="r"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        await _chat(client, gw, _body())
        b = vendor.bodies_for("sk-A")[0]
        assert "temperature" not in b and "max_tokens" not in b

    async def test_images_endpoint_not_injected(self, vendor, make_gateway, client):
        """images 端点不注入 chat 参数（payload 组装不同，Q24 仅 chat）。"""
        vendor.set("sk-A", Ok(content="r"))
        cfg = gateway_config(vendor.port, models=[{
            "name": "img-model", "endpoint": "images",
            "params": {"temperature": 0.3},
            "resources": [{"resource": "res-A", "model": "vm-A"}]}])
        gw = await make_gateway(cfg)
        resp = await client.post(f"{gw.base_url}/v1/images/generations",
                                 json={"model": "img-model", "prompt": "a cat"})
        assert resp.status_code == 200
        b = vendor.bodies_for("sk-A")[0]
        assert "temperature" not in b
