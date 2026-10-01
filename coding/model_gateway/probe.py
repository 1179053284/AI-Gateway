"""参数方言探测（tech-design v2.0 §13.3 / PRD Q25-⑤）。

三步探测（**S2 不可省**）：

| 步 | 动作 | 产出 |
|---|---|---|
| S1 | 发**非法值**触发 400，从**错误文案**抠出合法值域 | 候选值域 |
| S2 | **只发 `none`/`off` 类关闭值**，比 `reasoning_tokens` 是否**归零** | 真写入位 |
| S3 | 定档：值域 ∩ 规范序（规范外保留） | 方言表 |

🔴 为什么 S2 不可省（实测 `08` §九）：
    `reasoning.effort = "bogus"`（非法值）→ HTTP **200**，且 reasoning_tokens 与基线无异；
    `thinking.type = "enabled"` → 同样 200、同样与基线无异。
    **即：非法值也返回 200 —— 上游"忽略"了它，而非"接受"了它。**
    只做「200/400 二分」会把被忽略的字段误判成支持的写法。

🔴 为什么 S2 只验**单一锚点**、不逐档比数值：
    实测同模型同题的 `reasoning_tokens` 波动为 22/23/38/43/61 —— 逐档比数值在 n=1 时必然误判；
    而 `none` → **0** 与 22–61 **无重叠区间**，是唯一可靠锚点，**单次采样即可**。
    （因此不做"多次采样 + 阈值调参"——那正是过度设计。）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from model_gateway.core.dialects import LEVELS, Dialect, is_closed

#: 探测调用签名：`(body) -> (http_status, response_json)`。
#: 生产环境注入真实出站适配器；单测注入"按请求体返回指定响应"的假序列（可确定性验证）。
CallFn = Callable[[dict], Awaitable[tuple[int, dict]]]

#: 各写法族的探测表达式（键路径 → 实际请求体构造）。
#: 实测真写入位是**扁平式** `reasoning_effort`；`reasoning.effort` / `thinking.type` 在该端点是**假方言**。
WRITE_STYLES: list[tuple[str, str]] = [
    ("reasoning_effort", "flat"),      # {"reasoning_effort": <v>}
    ("reasoning.effort", "nested"),    # {"reasoning": {"effort": <v>}}
    ("thinking.type", "thinking"),     # {"thinking": {"type": <v>}}
]

#: 从 400 文案里抠值域的常见句式（实测商汤：`should be one of: low, medium, high, xhigh, none`）
_VALUE_HINT = re.compile(
    r"(?:should be one of|must be one of|one of|合法值|可选值)[:\s]*([A-Za-z0-9_,\-\s]+)",
    re.IGNORECASE,
)
#: 探测用的非法值（几乎不可能被任何上游接受）
ILLEGAL = "__mgw_probe__"


@dataclass
class ProbeOutcome:
    """单个模型的探测结果（含证据，便于人工复核）。"""

    dialect: Dialect
    #: 各步的原始证据摘要
    evidence: list[str]


def _body(style: str, model: str, value: str) -> dict:
    """按写法族构造最小探测请求体。"""
    base = {"model": model, "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}]}
    if style == "flat":
        base["reasoning_effort"] = value
    elif style == "nested":
        base["reasoning"] = {"effort": value}
    elif style == "thinking":
        base["thinking"] = {"type": value}
    return base


def parse_value_hint(message: str) -> list[str]:
    """从 400 错误文案里解析出上游回显的合法值域（S1 的核心）。"""
    m = _VALUE_HINT.search(message or "")
    if not m:
        return []
    raw = m.group(1)
    vals = [v.strip().strip('"\'`.').lower() for v in re.split(r"[,\s]+", raw)]
    return [v for v in vals if v and v.isascii()]


def _reasoning_tokens(body: dict) -> int | None:
    """从响应体取 reasoning_tokens（兼容 usage.completion_tokens_details 与 usage.reasoning_tokens）。"""
    usage = body.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    for v in (details.get("reasoning_tokens"), usage.get("reasoning_tokens")):
        if isinstance(v, int):
            return v
    return None


def _error_message(body: dict) -> str:
    err = body.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or "")
    return str(err or "")


async def probe_model(model: str, call: CallFn) -> ProbeOutcome:
    """三步探测单个模型（§13.3）。

    返回 `ProbeOutcome`：`dialect.verified=True` 仅当 **S1 与 S2 都通过**。
    S1 通过但 S2 未通过 → 该写法是**假方言**（上游忽略它），**不得**写进方言表。
    """
    evidence: list[str] = []
    best: Dialect | None = None

    for field, style in WRITE_STYLES:
        # —— S1：发非法值，从 400 文案抠值域 ——
        status, body = await call(_body(style, model, ILLEGAL))
        if status != 400:
            evidence.append(f"S1 {field}: 非法值返回 {status}（非 400）→ 该写法不可探测")
            continue
        values = parse_value_hint(_error_message(body))
        if not values:
            evidence.append(f"S1 {field}: 400 但文案无可解析值域 → 跳过")
            continue
        evidence.append(f"S1 {field}: 值域={','.join(values)}")

        # —— S2：只发关闭值，看 reasoning_tokens 是否归零（单锚点）——
        closed = next((v for v in values if is_closed(v)), None)
        if closed is None:
            evidence.append(f"S2 {field}: 值域内无关闭档 → 无法做生效验证，判为未验证")
            if best is None:
                best = Dialect(model=model, write_field=field, values=values,
                               thinking_format="", verified=False,
                               note="S1 通过但无关闭档，S2 无法执行")
            continue
        s2_status, s2_body = await call(_body(style, model, closed))
        if s2_status != 200:
            evidence.append(f"S2 {field}: 关闭值 {closed} 返回 {s2_status} → 判为假方言")
            continue
        rt = _reasoning_tokens(s2_body)
        if rt == 0:
            # —— S3：定档（值域按规范序排列；规范外档位保留在末尾）——
            best = Dialect(model=model, write_field=field, values=ordered_values(values),
                           thinking_format=_guess_format(field, values),
                           verified=True,
                           note=f"S2 生效验证通过（{closed} → reasoning_tokens=0）")
            evidence.append(f"S2 {field}: {closed} → reasoning_tokens=0 ✅ 真写入位")
            break
        evidence.append(f"S2 {field}: {closed} → reasoning_tokens={rt}（未归零）→ 假方言，丢弃")

    if best is None:
        best = Dialect(model=model, verified=False, note="三步探测均未通过，保留硬编码 fallback")
    return ProbeOutcome(dialect=best, evidence=evidence)


def _guess_format(field: str, values: list[str]) -> str:
    """方言族猜测（保守）：扁平式 → openai；嵌套式 → openrouter；thinking.type → anthropic 系。

    ⚠️ 这是**启发式**，仅作初始值；真实方言族由接入方按官方文档校准（§4.4 既有口径：
    不在设计文档预先断言参数名）。
    """
    if field == "reasoning_effort":
        return "openai"
    if field == "reasoning.effort":
        return "openrouter"
    if field == "thinking.type":
        return "anthropic"
    return ""


def ordered_values(values: list[str]) -> list[str]:
    """按规范序排序值域；**规范外档位排在最后但保留**（开放可扩展，§13.1）。"""
    in_seq = [v for v in LEVELS if v in values]
    extra = [v for v in values if v not in LEVELS]
    return in_seq + extra
