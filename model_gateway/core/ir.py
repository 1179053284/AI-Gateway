"""IR：内部标准格式（tech-design §4.2）。

M1 形态（透传优先）：IR 请求体 = OpenAI 形字典（OpenAI 入站近乎零转换；
Anthropic 入站由 api/anthropic.py 转换为 OpenAI 形后再进调度）。
流事件 = 归一化后的 OpenAI chunk 字典（思考字段统一补充 reasoning_content）。

推理参数（Q15 / FR-3.16）：ReasoningSpec 用 None 严格区分「未指定」与「显式关闭」，
三级合并 = 请求级 > 资源级默认 > 不注入（厂商默认）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReasoningSpec:
    """推理参数显式值（请求级或资源级默认）。None = 未指定。"""

    enabled: bool | None = None
    effort: str | None = None

    def is_empty(self) -> bool:
        return self.enabled is None and self.effort is None


def merge_reasoning(
    request_spec: ReasoningSpec | None,
    resource_default: ReasoningSpec | None,
) -> ReasoningSpec | None:
    """三级合并（UT-23 / E2E-15 实测校准）：请求级 > 资源级默认 > 不注入。

    - 字段级覆盖：请求显式值优先；请求未指定的字段走资源默认
    - 显式关闭（enabled=False）优先于资源默认开启，且压制**资源级** effort
      填补（防矛盾出站组合 thinking:disabled + reasoning_effort:<非none>——
      商汤 400：「only be disabled when reasoning effort is none」）；
      客户端显式同时给出两字段则原样透传（其自身矛盾由厂商错误兜底）
    - 请求级显式 effort 隐含开关意图（厂商语义：effort 非 none 必须 thinking
      enabled；effort=none 即关闭），不再回落资源级 enabled
    - 合并结果全空 → None（出站不注入任何推理字段，走厂商默认）
    """
    enabled = None
    effort = None
    if request_spec is not None:
        enabled = request_spec.enabled
        effort = request_spec.effort
        if effort is not None and enabled is None:
            enabled = effort.lower() != "none"  # 显式 effort 隐含开关
    if enabled is None and resource_default is not None:
        enabled = resource_default.enabled
    if effort is None and resource_default is not None and enabled is not False:
        effort = resource_default.effort  # 仅在未被显式关闭时填补（矛盾防护）
    merged = ReasoningSpec(enabled=enabled, effort=effort)
    return None if merged.is_empty() else merged


def apply_model_params(body: dict[str, Any], params: dict[str, Any] | None) -> dict[str, Any]:
    """网关级模型参数注入（Q24 / FR-2.5）：工具调用传参 > 网关设置 > 厂商内置。

    字段级合并：请求体已含该键且非 null → 保留（工具传参最高优先）；
    缺省或显式 null → 注入网关设置值；网关未配置该键 → 不注入（走厂商内置默认）。
    原地修改并返回 body（调用方持有副本，语义同 inject_reasoning_into_body）。
    """
    if not params:
        return body
    for k, v in params.items():
        if body.get(k) is None:
            body[k] = v
    return body


def lift_reasoning_from_body(body: dict[str, Any]) -> ReasoningSpec | None:
    """入站提升：把请求体中的推理字段取出为显式值（防出站双重注入）。

    - reasoning_effort（str）→ effort
    - thinking（{type: enabled|disabled}）→ enabled
    返回 None 表示请求未指定任何推理参数；字段从 body 中移除。
    """
    spec = ReasoningSpec()
    if "reasoning_effort" in body:
        v = body.pop("reasoning_effort")
        if isinstance(v, str) and v:
            spec.effort = v
    if "thinking" in body:
        v = body.pop("thinking")
        if isinstance(v, dict):
            t = v.get("type")
            if t in ("enabled", "disabled"):
                spec.enabled = (t == "enabled")
    return None if spec.is_empty() else spec


def inject_reasoning_into_body(body: dict[str, Any], spec: ReasoningSpec | None) -> None:
    """出站注入（商汤 OpenAI 兼容口径，实测验证）：

    - enabled → thinking: {type: enabled|disabled}
    - effort → reasoning_effort（opaque 透传）
    - disabled 且未指定 effort → 补 reasoning_effort:none（厂商配对约束，E2E 实测：
      glm-5.2 拒绝「thinking:disabled 不带 effort」——「only be disabled when
      reasoning effort is none」；补 none 后 glm-5.2 / deepseek-v4-flash 均 200；
      enabled 不受约束，无需配对）
    """
    if spec is None:
        return
    if spec.enabled is not None:
        body["thinking"] = {"type": "enabled" if spec.enabled else "disabled"}
        if spec.enabled is False and spec.effort is None:
            body["reasoning_effort"] = "none"  # 配对归一化（语义等价的合法序列化）
    if spec.effort is not None:
        body["reasoning_effort"] = spec.effort


@dataclass
class IRRequest:
    """调度层请求：endpoint=chat 时 body 为 OpenAI 形；endpoint=images 时为 images 形。"""

    system_model: str  # 已解析的系统模型名（canonical）
    endpoint: str  # chat | images
    stream: bool
    body: dict[str, Any]  # 原始请求体（model 已移除、推理字段已提升）
    reasoning: ReasoningSpec | None = field(default=None)  # 请求级显式推理参数


# —— 流事件（归一化 OpenAI chunk；type 字段为网关内部标记，出站编码时剔除） ——

HEARTBEAT_EVENT = {"type": "_heartbeat"}


def _iter_deltas(chunk: dict[str, Any]):
    """产出 chunk 中全部 delta/message 字典（OpenAI 标准形态位于 choices[] 内）。"""
    delta = chunk.get("delta")
    if isinstance(delta, dict):
        yield delta
    message = chunk.get("message")
    if isinstance(message, dict):
        yield message
    for ch in chunk.get("choices") or []:
        if not isinstance(ch, dict):
            continue
        d = ch.get("delta")
        if isinstance(d, dict):
            yield d
        m = ch.get("message")
        if isinstance(m, dict):
            yield m


def chunk_is_content(chunk: dict[str, Any]) -> bool:
    """首帧判定（§6）：chunk 是否携带内容（text/reasoning/tool_call 任一）。"""
    for delta in _iter_deltas(chunk):
        if delta.get("content"):
            return True
        if delta.get("reasoning_content") or delta.get("thinking_content") or delta.get("reasoning"):
            return True
        if delta.get("tool_calls"):
            return True
    return False


def normalize_stream_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    """归一化厂商思考字段差异（INT-30）：thinking_content / reasoning → 补充 reasoning_content。

    原字段保留（透传原则：无字段丢失），统一字段为增量补充。
    """
    for delta in _iter_deltas(chunk):
        rc = delta.get("reasoning_content")
        if not rc:
            for src in ("thinking_content", "reasoning"):
                v = delta.get(src)
                if v:
                    delta["reasoning_content"] = v
                    break
    return chunk
