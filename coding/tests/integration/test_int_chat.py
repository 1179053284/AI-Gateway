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
        """GET 默认脱敏。🔴 S-2（2026-10-05）：脱敏形态改为**显式哨兵前缀**
        `mgw-masked:sk-****k-1` —— 旧形态 `sk-****k-1` 与"用户手滑把掩码当新 Key 粘回"
        同形，是审计 S-2 静默毁数据路径的一半；哨兵形态与任何合法明文都不同形。"""
        vendor.set("sk-A", Ok())
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")],
                                               gateway={"access_tokens": [
                                                   {"id": "t1", "value": "gw-token-1"}]}))
        resp = await client.get(f"{gw.base_url}/admin/api/config")
        assert resp.status_code == 200
        text = json.dumps(resp.json(), ensure_ascii=False)
        # 短 key（≤8 位）经 mask_key 是纯 "****" ⇒ 哨兵形态 = "mgw-masked:****"
        assert "mgw-masked:" in text
        # 明文绝不出现：脱敏值的明文位不含 "sk-A" 本体
        import re
        assert not re.search(r'"api_key":\s*"sk-A"', text)


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
        """INT-36：推理参数三级合并端到端（资源默认 + 请求覆盖 + 无默认不注入）。

        🔴 Q33-③ 改判带来的前置调整（**不是放宽判据，是把前提换对**）：本用例原先靠
        「串行请求恒走 A（平局取优先级）」这条 §5.3 旧定论来保证第二、三条请求还打到 A。
        号间轮转之后该前提不再成立（串行会 A→B→A 分摊，正是用户要的"开 4 个号就 4 个号轮流"）。
        所以三级合并改为**按资源各建一个池**来验：验 A 的资源默认与请求覆盖就用只含 A 的池；
        验"B 无默认 ⇒ 一个字段都不注入"就用 A 恒 500 逼出切换。判据一条没少，
        只是不再依赖那条被推翻的路由行为。
        """
        vendor.set("sk-A", Ok(content="r"))
        cfg = gateway_config(vendor.port, models=[{
            "name": "test-model", "endpoint": "chat",
            "resources": [
                {"resource": "res-A", "model": "vm-A",
                 "reasoning": {"enabled": True, "effort": "low"}}]}])
        gw = await make_gateway(cfg)

        # ① 请求不带推理字段 → 出站走资源默认（enabled + low）
        await _chat(client, gw, _body())
        a_body = vendor.bodies_for("sk-A")[0]
        assert a_body["thinking"] == {"type": "enabled"}
        assert a_body["reasoning_effort"] == "low"

        # ② 请求带 reasoning_effort=high → 出站 high（请求级覆盖资源默认）；
        #    未指定的 thinking 仍走资源默认
        await _chat(client, gw, _body(reasoning_effort="high"))
        a_body2 = vendor.bodies_for("sk-A")[1]
        assert a_body2["reasoning_effort"] == "high"
        assert a_body2["thinking"] == {"type": "enabled"}

        # ③ 换到**无默认**的资源 B（让 A 恒 500 逼出切换）⇒ 推理字段一个都不注入
        vendor.set("sk-A", Err(500))
        vendor.set("sk-B", Ok(content="r"))
        cfg2 = gateway_config(vendor.port, models=[{
            "name": "test-model", "endpoint": "chat",
            "resources": [
                {"resource": "res-A", "model": "vm-A",
                 "reasoning": {"enabled": True, "effort": "low"}},
                {"resource": "res-B", "model": "vm-B"},
            ]}])
        gw2 = await make_gateway(cfg2)
        resp = await _chat(client, gw2, _body())
        assert resp.status_code == 200
        b_body = vendor.bodies_for("sk-B")[0]
        assert "thinking" not in b_body and "reasoning_effort" not in b_body

    async def test_rotation_spreads_sequential_requests_over_accounts(self, vendor,
                                                                     make_gateway, client):
        """🔴 Q33-③ 端到端判据：串行请求**摊到多个号**上，而不是恒打优先级首位。

        四号全空闲、`x=2`：连续四条必须落在**四个不同的 key** 上各一条。
        撤证：把 `pick_and_acquire` 的滑动窗口改回固定前缀切片，C/D 两个 key 永远收不到请求，
        这条立刻红 —— 所以它钉的是"轮转真的发生"，不是"恰好没堆在一起"。
        """
        for key in ("sk-A", "sk-B", "sk-C", "sk-D"):
            vendor.set(key, Ok(content="r"))
        cfg = gateway_config(vendor.port, scheduling={"max_active_per_model": 2},
                             models=[{"name": "test-model", "endpoint": "chat",
                                      "resources": [{"resource": f"res-{k}", "model": f"vm-{k}"}
                                                    for k in "ABCD"]}])
        gw = await make_gateway(cfg)
        for _ in range(4):
            resp = await _chat(client, gw, _body())
            assert resp.status_code == 200
        hit = [k for k in ("sk-A", "sk-B", "sk-C", "sk-D") if vendor.bodies_for(k)]
        assert hit == ["sk-A", "sk-B", "sk-C", "sk-D"], hit   # 四条 = 四个号各一条

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
    """Q24：网关级模型参数注入端到端（工具传参 > 网关设置 > 供应商通道默认；仅 chat）。"""

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

        生效序 = **请求级 > 资源级默认 > 参数卡（网关设置）> 供应商通道默认**：
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
        """网关未配置 params → 不注入任何键（走该供应商通道默认）。"""
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


class TestSpecDefaultOutboundLeg:
    """INT-80 · 统一规格层的**出站腿接线**判据（评审 R2-③：先前只有直接调函数的单测，
    把 `scheduler.py` 的 `apply_spec_defaults` 调用点删掉仍然全绿）。

    这条把"出站缺省带不带规格的数"钉在**真实请求路径**上：
    这条资源的供应商模型名 `sensenova-6.8-flash-lite` 恰好等于厂商标准名 ⇒ 枚举目录（按
    **厂商模型标准名** `EnumEntry.name` 索引，见 `core/model_spec.py:224`）里它的 `max_output=65536` ⇒
    调用方不给 `max_tokens` 时，出站体必须带上**该资源自己**的 65536；
    给了就用给的（Q28 的优先级「工具传参 > 网关设置 > 规格 > 供应商通道默认」不得被翻案）。
    """

    async def test_vendor_spec_default_reaches_outbound_body(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="r"))
        cfg = gateway_config(vendor.port, models=[{
            "name": "test-model", "endpoint": "chat",
            "resources": [{"resource": "res-A", "model": "sensenova-6.8-flash-lite"}]}])
        gw = await make_gateway(cfg)

        await _chat(client, gw, _body())
        b = vendor.bodies_for("sk-A")[0]
        assert b.get("max_tokens") == 65536, f"出站缺省没走规格层：{b!r}"

        await _chat(client, gw, _body(max_tokens=128))
        assert vendor.bodies_for("sk-A")[1]["max_tokens"] == 128

    async def test_default_uses_this_resources_own_number_not_the_pool_max(
            self, vendor, make_gateway, client):
        """🔴 INT-80 的第二腿（评审 R9 报备）：单资源那条腿**分不出**"自己的"与"池内最大"。

        把 `scheduler._out_body` 的取数从 `resource_specs[(rid, vm)]` 换成 `model_specs[name]`
        （= 池内最大）时，原判据照样绿，而真机上会给上限 65536 的号注入 131072 ⇒ 真实上游 400
        —— 正是 R1-⑤ 当初判死的那件事，只是没人把"两个数不相等"的形状造出来。
        """
        vendor.set("sk-A", Ok(content="small"))
        vendor.set("sk-B", Ok(content="big"))
        cfg = gateway_config(vendor.port, models=[{
            "name": "test-model", "endpoint": "chat",
            "resources": [{"resource": "res-A", "model": "sensenova-6.8-flash-lite"},   # 65536
                          {"resource": "res-B", "model": "glm-5.2"}]}],                  # 131072
            scheduling={"max_active_per_model": 1})
        gw = await make_gateway(cfg)
        await _chat(client, gw, _body())                     # 调用方什么都不给
        bodies = vendor.bodies_for("sk-A")
        assert bodies, "res-A 本该承接第一条"
        assert bodies[0]["max_tokens"] == 65536, (
            f"注入了池内最大而不是这条资源自己的数：{bodies[0]!r}")
        # 同一模型换到大的那条号 ⇒ 注入它自己的 131072（两份数各自成立）
        await _chat(client, gw, _body())
        assert vendor.bodies_for("sk-B")[-1]["max_tokens"] == 131072, vendor.bodies_for("sk-B")



class TestReasoningDefaultIsPerSystemModel:
    """🔴 INT-92 · 资源级**推理默认**的键必须带网关模型维度（评审 R9-B-1'）。

    与本轮刚修的 `resource_specs` 是同一类缺陷，而且就在同一次装配里、红线注释的上面二十行：
    `reasoning` 住在 `models[].resources[]` 这条条目上，同一个 `(资源, 供应商模型名)` 被别名挂到
    第二个网关模型时两边完全可以填不同默认，而旧表键只有 `(rid, vendor_model)` + 后写覆盖 ⇒
    顺序决定哪一份活下来，另一份整份消失（或凭空串到另一个网关名上），定向判据零红。
    """

    def _cfg(self, port, *, alias_last: bool):
        main = {"name": "m-main", "endpoint": "chat",
                "resources": [{"resource": "res-A", "model": "vm-A",
                               "reasoning": {"enabled": True, "effort": "low"}}]}
        alias = {"name": "m-alias", "endpoint": "chat",
                 "resources": [{"resource": "res-A", "model": "vm-A",
                                "reasoning": {"enabled": False}}]}
        models = [main, alias] if alias_last else [alias, main]
        return gateway_config(port, models=models)

    async def test_both_aliases_keep_their_own_reasoning_default(self, vendor, make_gateway,
                                                                 client):
        for alias_last in (False, True):
            vendor.reset()
            vendor.set("sk-A", Ok(content="r"))
            gw = await make_gateway(self._cfg(vendor.port, alias_last=alias_last))
            await _chat(client, gw, _body(model="m-main"))
            await _chat(client, gw, _body(model="m-alias"))
            bodies = vendor.bodies_for("sk-A")
            assert len(bodies) == 2, bodies
            # m-main 那条：条目自己填的 enabled+low 必须还在（被别名覆盖时会整份消失或变成 disabled）
            assert bodies[0].get("thinking") == {"type": "enabled"}, (alias_last, bodies[0])
            assert bodies[0].get("reasoning_effort") == "low", (alias_last, bodies[0])
            # m-alias 那条：它自己的 disabled 默认（配对补 none）
            assert bodies[1].get("thinking") == {"type": "disabled"}, (alias_last, bodies[1])
            assert bodies[1].get("reasoning_effort") == "none", (alias_last, bodies[1])

class TestCapacityAwareRouting:
    """INT-84 · 出站**承载校验**接线（债务 Q33-债6-② / tech §22.5-9 第①条）。

    定版口径三条，缺一不可：
    ① 请求要的输出一**已知大于**该资源的上限 ⇒ 这条资源承载不了，直接换下一条，
       **一次都不往它身上打**（旧行为 = 打上去吃上游 400，白烧一次额度并把好资源冷却掉）；
    ② 避开**不记失败**：不计入 `C`（y 的计数）、不冷却、不进 `attempts`
       —— 一次成功的避开不是故障，否则 y 会把用户刚配好的大窗口请求越用越窄地冷却掉；
    ③ **不知道 = 不拦**：目录/缓存都没给这个数时照发（宁可吃一个可见的 400，
       也不凭空否决一条可能可用的资源，与 §12「消灭无报错的失败」同一条立意）。
    """

    async def test_over_capacity_resource_is_skipped_without_failure_credit(
            self, vendor, make_gateway, client):
        """res-A（目录 max_output=65536）装不下 100000 ⇒ 必须换到 res-B（131072）。"""
        vendor.set("sk-A", Ok(content="small"))
        vendor.set("sk-B", Ok(content="big"))
        cfg = gateway_config(vendor.port, models=[{
            "name": "test-model", "endpoint": "chat",
            "resources": [{"resource": "res-A", "model": "sensenova-6.8-flash-lite"},
                          {"resource": "res-B", "model": "glm-5.2"}]}])
        gw = await make_gateway(cfg)

        r = await _chat(client, gw, _body(max_tokens=100000))
        assert r.status_code == 200, r.text
        assert vendor.bodies_for("sk-A") == [], "已知装不下却仍打出去了（白烧额度）"
        assert vendor.bodies_for("sk-B")[0]["max_tokens"] == 100000

        st = gw.runtime.resources.registry[("res-A", "sensenova-6.8-flash-lite")]
        assert st.C == 0 and st.status == "active", (st.C, st.status)   # ② 不记失败
        assert gw.runtime.resources.pools["test-model"] and \
            len(vendor.bodies_for("sk-A")) == 0

    async def test_unknown_capacity_is_never_a_rejection(self, vendor, make_gateway, client):
        """目录里查不到的供应商模型名 ⇒ `max_output=None` = 不知道 ⇒ 照发，不拦、不换。"""
        vendor.set("sk-A", Ok(content="r"))
        cfg = gateway_config(vendor.port, models=[{
            "name": "test-model", "endpoint": "chat",
            "resources": [{"resource": "res-A", "model": "vm-not-in-catalog"}]}])
        gw = await make_gateway(cfg)

        r = await _chat(client, gw, _body(max_tokens=200000))
        assert r.status_code == 200, r.text
        assert vendor.bodies_for("sk-A")[0]["max_tokens"] == 200000

    async def test_default_injection_cannot_self_reject(self, vendor, make_gateway, client):
        """缺省注入的那份本来就取自**这条资源自己**的规格 ⇒ 等值必须放行（R1-⑤ 的另一半）。"""
        vendor.set("sk-A", Ok(content="r"))
        cfg = gateway_config(vendor.port, models=[{
            "name": "test-model", "endpoint": "chat",
            "resources": [{"resource": "res-A", "model": "sensenova-6.8-flash-lite"}]}])
        gw = await make_gateway(cfg)
        await _chat(client, gw, _body())               # 调用方什么都不给
        assert vendor.bodies_for("sk-A")[0]["max_tokens"] == 65536


class TestCapacityAvoidReturnsItsReservation:
    """🔴 INT-87 · 避开一条资源时必须**成对归还**它在选路段里做的两件事（复验轮 R5-①）。

    `pick_and_acquire` 在同一个同步段里既 `in_flight += 1` **又** `reserve_quota()`（M5-3 的
    租约设计，就是为了并发下不撞"剩余额度=1"）。承载判据只 `release()` 一半 ⇒
    每避开一次就有一个号的额度被"已预留"永久吃掉：实测 `reserved` 1→2→3 后
    该号谁也派不到，而错误码还指着 `ALL_OVER_CAPACITY` 说谎。
    """

    async def test_reserved_quota_returns_to_zero_after_avoids(self, vendor, make_gateway,
                                                               client):
        """额度**已知**时才算真的在预留（`reserve_quota` 在 `remaining is None` 时直接放行、
        不留预留 ⇒ 不设额度这条判据是空的，第一版就是这么假绿过一遍）。
        """
        vendor.set("sk-A", Ok(content="small"))
        vendor.set("sk-B", Ok(content="big"))
        cfg = gateway_config(vendor.port, models=[{
            "name": "test-model", "endpoint": "chat",
            "resources": [{"resource": "res-A", "model": "sensenova-6.8-flash-lite"},
                          {"resource": "res-B", "model": "glm-5.2"}]}])
        gw = await make_gateway(cfg)
        a = gw.runtime.resources.registry[("res-A", "sensenova-6.8-flash-lite")]
        assert gw.runtime.resources.set_quota("res-A", 3) is True   # 余量已知 ⇒ 预留真的会记

        for _ in range(3):
            r = await _chat(client, gw, _body(max_tokens=100000))
            assert r.status_code == 200, r.text
        assert a.quota.reserved == 0, (
            f"避开腿漏还额度预留：{a.quota!r}（三次避开吃掉三次预留 ⇒ 该号从此派不到活）")
        assert a.in_flight == 0
        assert len(vendor.bodies_for("sk-A")) == 0, "被预留吃满之前它就该一直被避开"
        assert len(vendor.bodies_for("sk-B")) == 3

        # 反证的后半句：这个号**没被弄坏** —— 换成它承载得了的请求，照样派到它
        r = await _chat(client, gw, _body(max_tokens=128))
        assert r.status_code == 200, r.text
        assert len(vendor.bodies_for("sk-A")) == 1, (
            f"避开过一次就被永久饿死（reserved 泄漏的直接后果）：quota={a.quota!r}")

    async def test_max_completion_tokens_is_measured_too(self, vendor, make_gateway, client):
        """🔴 复验轮 R5-②：`max_tokens` 键**显式为 null** 时，真正的上限在 `max_completion_tokens`
        上 —— 旧写法 `body.get("max_tokens", body.get(...))` 读出 None ⇒ 该拦的不拦，
        白烧一次额度吃 400（正是这条判据要消灭的形状）。
        """
        vendor.set("sk-A", Ok(content="small"))
        vendor.set("sk-B", Ok(content="big"))
        cfg = gateway_config(vendor.port, models=[{
            "name": "test-model", "endpoint": "chat",
            "resources": [{"resource": "res-A", "model": "sensenova-6.8-flash-lite"},
                          {"resource": "res-B", "model": "glm-5.2"}]}])
        gw = await make_gateway(cfg)
        r = await _chat(client, gw, _body(max_tokens=None, max_completion_tokens=100000))
        assert r.status_code == 200, r.text
        assert vendor.bodies_for("sk-A") == [], "显式 null 把另一个键掩掉了 ⇒ 小上限的号照样被打"
        assert vendor.bodies_for("sk-B")[0]["max_completion_tokens"] == 100000


class TestEmptyPoolIsNotACapacityVerdict:
    """🔴 INT-88 · 空池的终局原因（真机复验 R5-F-2 判死的**本轮引入的回归**）。

    接线时把 `capacity_only` 初值写成 True，判据就成了"只要没被真试过就是装不下"。
    池里一个候选都没有（号全停 / 条目全关）时第一轮 `pick_and_acquire` 直接返回 None，
    错误码被写成 `ALL_OVER_CAPACITY`、文案是"所有候选资源的输出上限都小于本次请求所需"
    ⇒ 用户照着去调 `max_tokens`，而真问题是"没把账号启用"。
    R3 在同一形状下拿到的是 `NO_RESOURCE`（`docs/changes/reviews/q33-r3-live.md:96`），
    所以这不是口径分歧而是回归 —— 也与这段注释自己那句"故障与容量是两件事"冲突。

    三个形状分开钉（缺一个都允许退化回单个初值）：
    ① 空池 ⇒ `NO_RESOURCE`（根本没拦过任何一条）；
    ② 拦过一条、但至少真试过一条 ⇒ **不得**是 `ALL_OVER_CAPACITY`；
    ③ 每条都被拦、一次都没真试过 ⇒ 这才是 `ALL_OVER_CAPACITY`。
    """

    async def test_empty_pool_is_no_resource_not_over_capacity(self, vendor, make_gateway,
                                                                client):
        cfg = gateway_config(vendor.port, models=[chat_res("A")])
        cfg["resources"][0]["enabled"] = False          # 号停用 ⇒ 池空，与容量毫无关系
        gw = await make_gateway(cfg)
        r = await _chat(client, gw, _body())
        assert r.status_code == 503, r.text
        code = r.json()["error"]["code"]
        assert code == "NO_RESOURCE", f"空池被谎报成容量问题：{code}"
        assert "上限" not in r.json()["error"]["message"]

    async def test_one_avoid_plus_one_real_try_is_not_over_capacity(self, vendor, make_gateway,
                                                                     client):
        """② 真试过的腿必须赢：一次 5xx 是故障，不许被说成"网关认为装不下"。"""
        vendor.set("sk-A", Ok(content="small"))
        vendor.set("sk-B", Err(status=500, message="upstream boom"))
        cfg = gateway_config(vendor.port, models=[{
            "name": "test-model", "endpoint": "chat",
            "resources": [{"resource": "res-A", "model": "sensenova-6.8-flash-lite"},
                          {"resource": "res-B", "model": "glm-5.2"}]}])
        gw = await make_gateway(cfg)
        # res-A 上限 65536 < 100000 ⇒ 被避开；res-B 承载得了 ⇒ 真打出去并失败
        r = await _chat(client, gw, _body(max_tokens=100000))
        assert r.status_code == 503, r.text
        assert r.json()["error"]["code"] != "ALL_OVER_CAPACITY", r.text
        assert len(vendor.bodies_for("sk-B")) >= 1, "真试过这条腿没成立 ⇒ ② 判据为空"
        assert len(vendor.bodies_for("sk-A")) == 0

    async def test_every_candidate_rejected_is_over_capacity(self, vendor, make_gateway,
                                                              client):
        """③ 的正向腿：拦过**且**从没真试过 ⇒ 这个码才是真的。"""
        cfg = gateway_config(vendor.port, models=[{
            "name": "test-model", "endpoint": "chat",
            # 目录里这两条的上限是 65536 / 131072（`chat_res` 用的 `vm-A/vm-B` 不在目录里
            # ⇒ "不知道 = 不拦"会直接放过，这条判据就变成空的）
            "resources": [{"resource": "res-A", "model": "sensenova-6.8-flash-lite"},
                          {"resource": "res-B", "model": "glm-5.2"}]}])
        gw = await make_gateway(cfg)
        r = await _chat(client, gw, _body(max_tokens=200000))   # 65536 / 131072 都装不下
        assert r.status_code == 503, r.text
        assert r.json()["error"]["code"] == "ALL_OVER_CAPACITY", r.text
        assert vendor.requests == [], "一条都没该打出去"
        # 🔴 文案本身也是判据（评审 R9-报备 R2-续：换回旧的过度断言时 48 条全绿）：
        #    旧串"所有候选资源的输出上限都小于本次请求所需"在"拦过 + 其余号正好在冷却"这种
        #    混合形状下替网关说了没证据的话，新串只断言它真的知道的那部分
        msg = r.json()["error"]["message"]
        assert "所有候选资源的输出上限" not in msg, msg
        assert "已知装不下的候选已跳过" in msg, msg
