"""关闭推理档（`off`/`none`/`disabled`）与规范外档位的归属判据 —— 概念审计 A3-P0 / A2-P0-1 的回归钉。

钉三件事（缺省档 = 网关规范词表说了算，不是厂商那一个词说了算）：
1. `merge_reasoning` 认**全部**关闭词 ⇒ `enabled=False`（旧写法只认字面 `none`，
   工具按 `/v1/models` 的 `caps.thinkingLevelMap` 里网关自己的规范档 `off` 发来关闭请求，
   被判成"开了推理"）；
2. `degrade_effort` 对**规范外档位原样透传**（§13.1 开放可扩展），且关闭档**不参与升降**
   （旧写法把规范外当"高于 max"取 `len(LEVELS)` 当下标 ⇒ `IndexError`，实测
   `degrade_effort("none", ["low","high"])` 直接抛 = 一个正常请求打成 500）；
3. 档位兜底查表带**本次请求的网关模型**（别名形状下不是"这条资源挂到的第一个网关模型"），
   关闭档只在**该厂商表自己在册**的关闭词上归一（在根因处整形成上游能收的形状，
   不是跳过它 / 不是把判据改绿 —— PRD Q35-③ 红线）。
"""

import sys
from dataclasses import replace

import pytest

sys.path.insert(0, ".")

from model_gateway.core.dialects import CLOSED_LEVELS, degrade_effort, is_closed
from model_gateway.core.ir import IRRequest, inject_reasoning_into_body, merge_reasoning
from model_gateway.core.resources import ResourceManager  # noqa: F401（锚点：接线面）
from tests.unit.conftest import build_runtime, chat_model, make_config


class _Entry:
    def __init__(self, levels):
        self.effort_levels = tuple(levels)


class _Pool:
    """枚举池替身：键空间 = 厂商模型标准名（生产 `EnumPool.get` 同尺）。"""

    def __init__(self, table):
        self._table = dict(table)

    def get(self, name):
        return self._table.get(name)


# ─────────────────────────────── 1) 合并层：关闭词全认 ───────────────────────────────
@pytest.mark.parametrize("word", ["off", "none", "disabled", "OFF", " None "])
def test_every_closed_word_means_reasoning_disabled(word):
    """请求只给档位词、没给 enabled ⇒ 关闭词必须推出 `enabled=False`（不是 True）。"""
    merged = merge_reasoning(_spec(None, word), None)
    assert merged is not None and merged.enabled is False, f"{word!r} 被当成开启"


@pytest.mark.parametrize("word", ["low", "medium", "high", "max", "ultra"])
def test_non_closed_words_still_imply_enabled(word):
    assert merge_reasoning(_spec(None, word), None).enabled is True


def _spec(enabled, effort):
    from model_gateway.core.ir import ReasoningSpec
    return ReasoningSpec(enabled=enabled, effort=effort)


# ─────────────────────────── 2) 纯函数：规范外不抛、关闭档不升 ───────────────────
@pytest.mark.parametrize("effort,sup", [
    ("none", ["low", "high"]),        # 厂商表没有关闭词：原样，绝不 IndexError
    ("ultra", ["low", "high"]),       # 规范外自定义档（§13.1）：原样透传
    ("off", ["none", "high"]),        # 关闭档不许被"向上就近"升成 high
    ("disabled", ["low", "high"]),
])
def test_degrade_never_crashes_and_never_upgrades_a_closed_or_unknown_level(effort, sup):
    out = degrade_effort(effort, sup)
    assert out == effort, f"{effort!r} 被改成 {out!r}（规范外/关闭档不许升降）"


def test_degrade_still_downgrades_within_the_canonical_order():
    """反向腿：正例必须照旧 —— 判据不是把函数变成恒等返回。"""
    assert degrade_effort("xhigh", ["low", "high"]) == "high"
    assert degrade_effort("max", ["low", "high"]) == "high"


# ─────────────────────── 3) 接线层：clamp 查的是本次请求的网关模型 ───────────────────────
def _alias_runtime():
    """同一资源挂在两个网关模型上（别名形状），两家的档位表不同。

    `models[]` 书写顺序刻意把 `other-model`（厂商表含 `none`）放在**前面** ⇒
    旧实现 `_system_model_of(resource)` 会取到它，而请求发的是 `glm-model`（无关闭词）。
    """
    cfg = make_config(models=[
        chat_model("other-model", "A", resources=[{"resource": "res-A", "model": "vm-A"}]),
        chat_model("glm-model", "A", resources=[{"resource": "res-A", "model": "vm-A"}]),
    ])
    rt = build_runtime(cfg, _Adapter())
    rt.enum_pool = _Pool({"vm-A": _Entry(["low", "high"])})   # 供应商模型名在册（两家共用）
    return rt


class _Adapter:
    protocol = "openai"

    def supports(self, endpoint):
        return True


def test_clamp_uses_this_requests_gateway_model_not_the_first_pool():
    rt = _alias_runtime()
    res = rt.resources.pools["glm-model"][0]
    ir = IRRequest(system_model="glm-model", endpoint="chat", stream=False,
                   body={"messages": [{"role": "user", "content": "hi"}]},
                   reasoning=_spec(None, "xhigh"))
    body = rt.scheduler._out_body(ir, res)
    # `xhigh` 不在 vm-A 的表里 ⇒ 向下就近 = high（升降的依据是这次请求那张表）
    assert body["reasoning_effort"] == "high", body


def test_closed_level_is_normalized_only_to_a_word_the_producer_has():
    rt = _alias_runtime()
    res = rt.resources.pools["glm-model"][0]
    ir = IRRequest(system_model="glm-model", endpoint="chat", stream=False,
                   body={"messages": [{"role": "user", "content": "hi"}]},
                   reasoning=_spec(None, "off"))
    body = rt.scheduler._out_body(ir, res)
    assert body["thinking"] == {"type": "disabled"}, body          # 关就是关
    assert body["reasoning_effort"] == "off", body                 # 厂商表无关闭词 ⇒ 原样，不升档


def test_closed_level_maps_to_the_channel_word_when_producer_has_one():
    rt = _alias_runtime()
    rt.enum_pool = _Pool({"vm-A": _Entry(["none", "high"])})
    res = rt.resources.pools["glm-model"][0]
    ir = IRRequest(system_model="glm-model", endpoint="chat", stream=False,
                   body={"messages": [{"role": "user", "content": "hi"}]},
                   reasoning=_spec(None, "off"))
    body = rt.scheduler._out_body(ir, res)
    # 厂商在册的关闭词是 `none` ⇒ 出站必须写 `none`（商汤配对约束：disabled 只在 effort=none 时被接受）
    assert body["thinking"] == {"type": "disabled"} and body["reasoning_effort"] == "none", body


def test_closed_levels_membership_is_the_single_source():
    """关闭词语义只有一份词表；`is_closed` 必须与 `merge_reasoning`/clamp 用的是同一个集合。"""
    for word in sorted(CLOSED_LEVELS):
        assert is_closed(word) and merge_reasoning(_spec(None, word), None).enabled is False
