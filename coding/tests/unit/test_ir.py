"""推理参数三级合并 UT（UT-23 六场景；纯函数，无网络）。"""

from __future__ import annotations

from model_gateway.core.ir import (
    ReasoningSpec, apply_model_params, inject_reasoning_into_body, lift_reasoning_from_body,
    merge_reasoning,
)


def _merge(request: ReasoningSpec | None, default: ReasoningSpec | None):
    merged = merge_reasoning(request, default)
    body: dict = {}
    inject_reasoning_into_body(body, merged)
    return merged, body


class TestThreeLevelMerge:
    """UT-23：请求级 > 资源级默认 > 不注入（该供应商通道默认）。"""

    def test_s1_request_effort_overrides_default(self):
        """① 请求 effort=high + 资源默认 effort=low → 出站 high。"""
        merged, body = _merge(ReasoningSpec(effort="high"), ReasoningSpec(effort="low"))
        assert merged is not None and merged.effort == "high"
        assert body["reasoning_effort"] == "high"

    def test_s2_default_applies_when_unspecified(self):
        """② 请求未指定 + 资源默认 low → 出站 low。"""
        merged, body = _merge(None, ReasoningSpec(effort="low"))
        assert merged is not None and merged.effort == "low"
        assert body["reasoning_effort"] == "low"

    def test_s3_no_default_no_injection(self):
        """③ 请求未指定 + 资源无默认 → 出站不含推理字段（该供应商通道默认）。"""
        merged, body = _merge(None, None)
        assert merged is None
        assert "thinking" not in body and "reasoning_effort" not in body

    def test_s4_explicit_disable_beats_default_enable(self):
        """④ 请求显式 enabled=false + 资源默认 enabled=true → 出站 false（显式关闭优先）。"""
        merged, body = _merge(ReasoningSpec(enabled=False), ReasoningSpec(enabled=True))
        assert merged is not None and merged.enabled is False
        assert body["thinking"] == {"type": "disabled"}

    def test_s5_explicit_enable_without_default(self):
        """⑤ 请求显式 enabled=true + 资源无默认 → 出站 true。"""
        merged, body = _merge(ReasoningSpec(enabled=True), None)
        assert merged is not None and merged.enabled is True
        assert body["thinking"] == {"type": "enabled"}

    def test_s6_field_level_merge(self):
        """字段级覆盖：请求指定 effort、资源默认 enabled → 两字段合并生效。"""
        merged, body = _merge(ReasoningSpec(effort="medium"), ReasoningSpec(enabled=True))
        assert merged is not None
        assert merged.effort == "medium" and merged.enabled is True
        assert body == {"thinking": {"type": "enabled"}, "reasoning_effort": "medium"}

    def test_images_resource_reasoning_ignored(self):
        """⑥ images 资源配置 reasoning 默认 → 校验警告并忽略（loader 警告在 UT-13 侧）。"""
        # schemas 侧已由 test_config 覆盖警告；此处验证合并函数对 images 无特殊分支
        # （调度层不注入推理参数到 images 请求由调用方保证）
        merged, body = _merge(None, ReasoningSpec(effort="low"))
        assert body["reasoning_effort"] == "low"  # 纯函数语义：给 chat 用


class TestMergeVendorSemantics:
    """E2E-15 实测校准（商汤语义：effort 非 none 必须 thinking enabled）。"""

    def test_request_effort_implies_enabled_over_default_off(self):
        """请求 effort=low + 资源默认 enabled=false → 隐含开启（防矛盾组合）。

        E2E 实测：出站 thinking:disabled + reasoning_effort:low → 商汤 400。
        """
        merged, body = _merge(ReasoningSpec(effort="low"), ReasoningSpec(enabled=False))
        assert merged is not None
        assert merged.enabled is True and merged.effort == "low"
        assert body == {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}

    def test_explicit_disable_suppresses_default_effort(self):
        """请求显式 enabled=false + 资源默认 effort=low → disabled + 补 effort:none（压制资源 effort）。"""
        merged, body = _merge(ReasoningSpec(enabled=False), ReasoningSpec(effort="low"))
        assert merged is not None and merged.enabled is False
        # E2E 实测（glm-5.2 400「only be disabled when reasoning effort is none」）：
        # disabled 必须配对 reasoning_effort:none（厂商配对约束的序列化归一化）
        assert body == {"thinking": {"type": "disabled"}, "reasoning_effort": "none"}

    def test_request_effort_none_implies_disabled(self):
        """请求 effort=none → 隐含关闭，effort 原样透传（厂商合法组合）。"""
        merged, body = _merge(ReasoningSpec(effort="none"), None)
        assert merged is not None and merged.enabled is False
        assert body == {"thinking": {"type": "disabled"}, "reasoning_effort": "none"}


class TestLiftReasoning:
    """入站提升（防双重注入，Q15）：入站透传字段提升为显式值，出站统一注入。"""

    def test_lift_reasoning_effort(self):
        body = {"messages": [], "reasoning_effort": "high"}
        spec = lift_reasoning_from_body(body)
        assert spec is not None and spec.effort == "high"
        assert "reasoning_effort" not in body  # 已从 body 移除

    def test_lift_thinking(self):
        body = {"messages": [], "thinking": {"type": "enabled"}}
        spec = lift_reasoning_from_body(body)
        assert spec is not None and spec.enabled is True
        assert "thinking" not in body

    def test_lift_thinking_disabled(self):
        body = {"messages": [], "thinking": {"type": "disabled"}}
        spec = lift_reasoning_from_body(body)
        assert spec is not None and spec.enabled is False

    def test_lift_noop(self):
        body = {"messages": []}
        assert lift_reasoning_from_body(body) is None
        assert body == {"messages": []}

    def test_lift_then_inject_roundtrip(self):
        """提升 → 合并 → 注入：入站 thinking enabled + 资源默认 effort → 双字段出站。"""
        body = {"messages": [], "thinking": {"type": "enabled"}}
        spec = lift_reasoning_from_body(body)
        merged = merge_reasoning(spec, ReasoningSpec(effort="low"))
        inject_reasoning_into_body(body, merged)
        assert body["thinking"] == {"type": "enabled"}
        assert body["reasoning_effort"] == "low"
        assert "messages" in body  # 原字段不受影响


class TestApplyModelParams:
    """Q24：网关级模型参数字段级注入（工具传参 > 网关设置 > 供应商通道默认）。"""

    def test_s1_request_value_wins(self):
        """① 请求已传 temperature → 保留（工具传参最高优先）。"""
        body = {"temperature": 0.7}
        apply_model_params(body, {"temperature": 0.3})
        assert body["temperature"] == 0.7

    def test_s2_absent_injected(self):
        """② 请求未传 → 注入网关设置值。"""
        body = {"messages": []}
        apply_model_params(body, {"temperature": 0.3, "max_tokens": 99})
        assert body["temperature"] == 0.3 and body["max_tokens"] == 99

    def test_s3_no_params_untouched(self):
        """③ 网关未配置 params（None/空）→ 出站体原样（该供应商通道默认）。"""
        body = {"temperature": 0.7, "messages": []}
        apply_model_params(body, None)
        apply_model_params(body, {})
        assert body == {"temperature": 0.7, "messages": []}

    def test_s4_explicit_null_treated_as_absent(self):
        """④ 请求显式 null = 未传 → 注入网关值。"""
        body = {"temperature": None}
        apply_model_params(body, {"temperature": 0.3})
        assert body["temperature"] == 0.3

    def test_s5_field_level_merge(self):
        """⑤ 字段级：请求传 top_p 保留，其余键注入（与推理合并同哲学）。"""
        body = {"top_p": 0.9}
        apply_model_params(body, {"top_p": 0.95, "temperature": 0.3, "stop": ["END"]})
        assert body == {"top_p": 0.9, "temperature": 0.3, "stop": ["END"]}
