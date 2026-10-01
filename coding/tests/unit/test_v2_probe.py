"""v2.0 §13.3 探测单元测试（tech-design §19 M3-3）。

🔴 可测试性要求（§13.4）：探测函数接受**可注入的 `call_fn`**，
单测注入"按请求体返回 400/200 + 指定 reasoning_tokens"的假序列 →
**S1/S2/S3 三步逻辑可确定性验证**，无需真实上游。
"""

from __future__ import annotations

from typing import Any

import pytest

from model_gateway.probe import (
    ILLEGAL,
    ordered_values,
    parse_value_hint,
    probe_model,
)


def _resp(status: int, *, message: str = "", reasoning_tokens: int | None = None) -> dict:
    if status == 400:
        return {"error": {"message": message, "type": "invalid_request_error"}}
    usage: dict[str, Any] = {}
    if reasoning_tokens is not None:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    return {"choices": [{"message": {"content": "ok"}}], "usage": usage}


def make_call_fn(*, hint_values: str, closed_zero: bool, accept_flat_only: bool = True):
    """构造假探测序列。

    - 扁平式 `reasoning_effort`：非法值 → 400 回显 `hint_values`；关闭值 → 200
    - 嵌套/thinking 式：`accept_flat_only=True` 时**静默忽略**（返回 200 且 reasoning_tokens 非 0）
      —— 正是实测中"假方言"的表现
    """
    async def _call(body: dict) -> tuple[int, dict]:
        if "reasoning_effort" in body:
            v = body["reasoning_effort"]
            if v == ILLEGAL:
                return 400, _resp(400, message=f"field ReasoningEffort invalid, should be one of: {hint_values}")
            closed = v in ("off", "none")
            return 200, _resp(200, reasoning_tokens=0 if (closed and closed_zero) else 37)
        # 其它写法族：上游不认识 → 静默忽略（200，但推理 token 与基线同量级）
        return 200, _resp(200, reasoning_tokens=43)
    return _call


# ---------- S1：从 400 文案抠值域 ----------

def test_parse_value_hint_real_error_text():
    """实测文案（商汤）：`should be one of: low, medium, high, xhigh, none`。"""
    msg = "field ReasoningEffort invalid, should be one of: low, medium, high, xhigh, none"
    assert parse_value_hint(msg) == ["low", "medium", "high", "xhigh", "none"]


def test_parse_value_hint_no_match_returns_empty():
    assert parse_value_hint("something went wrong") == []


# ---------- S2：单锚点（none → 0） ----------

async def test_probe_verifies_real_write_field():
    """S1 拿到值域 + S2 关闭值归零 → `verified=True`，写入位是扁平式。"""
    call = make_call_fn(hint_values="low, medium, high, none", closed_zero=True)
    out = await probe_model("glm-5.2", call)

    assert out.dialect.verified is True
    assert out.dialect.write_field == "reasoning_effort"
    assert "none" in out.dialect.values
    assert any("reasoning_tokens=0" in e for e in out.evidence)


async def test_probe_rejects_fake_dialect_when_not_zeroed():
    """🔴 核心：关闭值**未归零** → 判为**假方言**，**不得**写进方言表（§13.3）。"""
    call = make_call_fn(hint_values="low, high, none", closed_zero=False)
    out = await probe_model("glm-5.2", call)

    assert out.dialect.verified is False
    assert "未归零" in " ".join(out.evidence)


async def test_probe_rejects_style_ignored_by_upstream():
    """非法值返回 200（上游忽略该字段）→ S1 即失败，不会误判为支持。"""
    async def _call(body: dict) -> tuple[int, dict]:
        return 200, _resp(200, reasoning_tokens=22)   # 一切请求都 200（实测：非法值也 200）
    out = await probe_model("glm-5.2", _call)

    assert out.dialect.verified is False
    assert all("非 400" in e for e in out.evidence if e.startswith("S1"))


async def test_probe_without_closed_level_cannot_verify():
    """值域内无关闭档 → S2 无法执行 → **未验证**（不冒充 verified）。"""
    call = make_call_fn(hint_values="low, medium, high", closed_zero=True)
    out = await probe_model("glm-5.2", call)

    assert out.dialect.verified is False
    assert "无关闭档" in " ".join(out.evidence)


async def test_probe_no_value_hint_gives_unverified():
    call = make_call_fn(hint_values="", closed_zero=True)
    out = await probe_model("glm-5.2", call)
    assert out.dialect.verified is False


# ---------- S3：定档（规范序 + 规范外保留） ----------

def test_ordered_values_keeps_out_of_spec_levels():
    """规范外档位（`ultra`）**保留**，排在最后（开放可扩展，§13.1）。"""
    got = ordered_values(["max", "ultra", "low", "none"])
    assert got == ["low", "max", "ultra", "none"]


def test_ordered_values_all_in_spec():
    assert ordered_values(["max", "minimal", "high"]) == ["minimal", "high", "max"]


async def test_probe_records_out_of_spec_value():
    """探测值域含规范外档位 → 原样记入方言表（不丢弃）。"""
    call = make_call_fn(hint_values="low, high, max, ultra, none", closed_zero=True)
    out = await probe_model("deepseek-v4-pro", call)

    assert out.dialect.verified is True
    assert "ultra" in out.dialect.values


async def test_probe_returns_evidence_for_audit():
    """探测结果带**证据摘要**，便于人工复核（不是黑盒结论）。"""
    call = make_call_fn(hint_values="low, none", closed_zero=True)
    out = await probe_model("m", call)
    assert out.evidence and any("S1" in e for e in out.evidence)
