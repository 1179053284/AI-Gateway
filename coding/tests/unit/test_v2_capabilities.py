"""v2.0 §12 / §13 单元测试：能力位组装、方言表、参数归一化。

对应 tech-design v2.0 §12（能力位下发）/ §13（参数归一化与方言表）；
验收判据见 §19 M3-2 / M3-3 / M3-4。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from model_gateway.core.capabilities import build_caps_block, build_model_caps
from model_gateway.core.dialects import (
    LEVELS,
    Dialect,
    DialectTable,
    build_level_map,
    degrade_effort,
    is_closed,
)
from model_gateway.enums.matcher import EnumEntry, EnumPool


class _Model:
    """最小 SystemModel 替身（name + caps_overrides + endpoint）。"""

    def __init__(self, name: str, caps_overrides: dict | None = None,
                 endpoint: str = "chat"):
        self.name = name
        self.caps_overrides = caps_overrides or {}
        self.endpoint = endpoint


def _pool(*entries: EnumEntry) -> EnumPool:
    return EnumPool(list(entries))


# ---------- §12.2 能力位字段映射 ----------

def test_caps_fields_map_from_enum_entry():
    """7 个能力位字段从 EnumEntry 直映射（§12.2 映射表）。"""
    pool = _pool(EnumEntry(
        "glm-5.2", "GLM-5.2", vendor="智谱 GLM",
        context_window=1048576, max_output=131072,
        image_input=True, reasoning=True,
        effort_levels=["max", "high", "low"],
    ))
    caps = build_model_caps(_Model("glm-5.2"), pool)

    assert caps["name"] == "GLM-5.2"
    assert caps["vendor"] == "智谱 GLM"
    assert caps["maxInputTokens"] == 1048576
    assert caps["maxOutputTokens"] == 131072
    assert caps["supportsImages"] is True
    assert caps["supportsReasoning"] is True
    # 🔴 supportsToolCall 是唯一净新增的能力位（EnumEntry.tool_call）
    assert caps["supportsToolCall"] is True


def test_custom_model_falls_back_without_crash():
    """自定义网关模型（不在内置目录）→ 最小字段集，**不崩**（§12.3 兜底）。

    🔴 Q33 复验轮 R3-F-3 改判的三个能力位：`null` = **不知道**，不再印 `false`。
    `false` 是"这个模型明确不能干这件事"的 affirmative 承诺，而我们并没有这个证据；
    工具侧 `!== true` 对 `null` 与 `false` 的处理**完全相同**（照旧保守 ⇒ 零回归），
    差别只在我们不再说谎、且管理端能把它渲染成"未知"。
    """
    caps = build_model_caps(_Model("my-own-model"), _pool())

    assert caps["name"] == "my-own-model"
    assert caps["vendor"] == ""
    assert caps["maxInputTokens"] is None
    assert caps["supportsToolCall"] is None        # 不知道 ⇒ null（不是 false）
    assert caps["supportsImages"] is None
    assert caps["supportsReasoning"] is None


def test_images_endpoint_is_the_one_place_false_is_a_claim():
    """`supportsToolCall` 在非 chat 端点上的 `false` 是**有依据的否**（图像端点没有 tools 参数，
    与 `EnumEntry.__post_init__` 同一条不变量），其余能力位仍只能是"不知道"。

    反向对照：同一模型换成 chat 端点 ⇒ 三个能力位必须回到 `null`，
    防止下一轮把"保守"重新实现成"一律 false"（那会把三态又压回两态）。
    """
    img = build_model_caps(_Model("my-own-model", endpoint="images"), _pool())
    assert img["supportsToolCall"] is False          # 有依据的否
    assert img["supportsImages"] is None             # 图像输出能力 ≠ tools 参数，仍是不知道
    assert img["supportsReasoning"] is None
    chat = build_model_caps(_Model("my-own-model"), _pool())
    assert chat["supportsToolCall"] is None


def test_missing_directory_attr_emits_null_not_fabricated():
    """目录缺属性（如 claude-sonnet-4 无 context_window）→ 输出 None，**不臆造数值**（§12.3）。"""
    pool = _pool(EnumEntry("claude-sonnet-4", "Claude Sonnet 4", vendor="Anthropic"))
    caps = build_model_caps(_Model("claude-sonnet-4"), pool)

    assert caps["maxInputTokens"] is None
    assert caps["maxOutputTokens"] is None


# ---------- §12.3 `tool_call` 的**覆写通道**（验收 P3-2：原先通道断在加载器里）----------

def test_yaml_can_turn_tool_call_off_per_model(tmp_path):
    """用户扩展目录（`data/model-enums.yaml`）写 `tool_call: false` 必须落到能力位输出。

    这是 §12.3 指定的**唯一**按模型关掉 `supportsToolCall` 的入口
    （`caps_overrides` 只管 `thinkingLevelMap` / `thinkingFormat`，§14.1）。
    上一版 `load_enum_pool` 根本没有读这个键 → 写了也恒为 True。
    """
    import yaml as _yaml

    from model_gateway.enums.matcher import load_enum_pool

    path = tmp_path / "model-enums.yaml"
    path.write_text(_yaml.safe_dump({"entries": [
        {"name": "no-tools-model", "display": "无工具", "endpoint": "chat"},
        {"name": "with-tools-model", "display": "有工具", "endpoint": "chat"},
    ]}, allow_unicode=True), encoding="utf-8")
    # 第一条显式关掉，第二条不写（走默认 True）—— 两条必须**不同**，否则说明读的是常量
    data = _yaml.safe_load(path.read_text(encoding="utf-8"))
    data["entries"][0]["tool_call"] = False
    path.write_text(_yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    pool = load_enum_pool(path)
    assert build_model_caps(_Model("no-tools-model"), pool)["supportsToolCall"] is False
    assert build_model_caps(_Model("with-tools-model"), pool)["supportsToolCall"] is True


def test_images_family_entries_do_not_claim_tool_call():
    """🔴 内置目录里 `endpoint: images` 的模型**不得**下发 `supportsToolCall: true`。

    文生图端点没有 tools 参数；声称支持会让工具把它列进"可用于 Agent 的模型"。
    判据取自**真实内置目录**而不是手搓条目，否则改了目录数据也没人红。
    """
    from model_gateway.enums.matcher import BUILTIN_ENTRIES, load_enum_pool

    non_chat = [e for e in BUILTIN_ENTRIES if e.endpoint != "chat"]
    assert non_chat, "内置目录已无非 chat 条目 —— 本用例失去意义，请连同判据一起删除"
    assert all(e.tool_call is False for e in non_chat), \
        [(e.name, e.endpoint, e.tool_call) for e in non_chat]

    caps = [build_model_caps(_Model(e.name), load_enum_pool(None)) for e in non_chat]
    assert all(c["supportsToolCall"] is False for c in caps)
    # 对照：同一次加载里 chat 条目仍为 True（否则"全 False"也是通过的）
    chat = [e for e in BUILTIN_ENTRIES if e.endpoint == "chat"]
    assert any(build_model_caps(_Model(e.name), load_enum_pool(None))
               ["supportsToolCall"] is True for e in chat)


def test_forcing_tool_call_on_a_non_chat_entry_is_normalized():
    """不变量在 dataclass 上：即便 YAML/界面写 `endpoint: images + tool_call: true` 也归 False。"""
    e = EnumEntry("gen-img", "生成图像", endpoint="images", tool_call=True)
    assert e.tool_call is False
    assert EnumEntry("chat-m", "对话", endpoint="chat", tool_call=True).tool_call is True


# ---------- §12.2a thinkingLevelMap 必须 7 键齐全 ----------

def test_level_map_has_all_seven_keys_with_null_for_unsupported():
    """🔴 7 键**必须齐全**，不支持的档**显式写 None**（键缺失 ≠ null，工具会误判为"支持"）。"""
    m = build_level_map(["low", "high", "max"])

    assert list(m.keys()) == list(LEVELS)          # 键集合与规范序完全一致
    assert len(m) == 7
    assert m["low"] == "low"
    assert m["max"] == "max"
    assert m["minimal"] is None                    # 不支持 → 显式 None（JSON 后为 null）
    assert m["medium"] is None
    assert "minimal" in m                          # 键存在（不是缺失）


def test_level_map_keeps_unsupported_high_tiers_explicit():
    """`xhigh` / `max` 即使不支持也**必须显式出现**（工具侧明确要求）。"""
    m = build_level_map([])

    assert m["xhigh"] is None and "xhigh" in m
    assert m["max"] is None and "max" in m


def test_caps_overrides_wins_over_directory():
    """用户手改的 `caps_overrides` 优先级最高（§12.3 逃生口）。"""
    pool = _pool(EnumEntry("glm-5.2", "GLM-5.2", effort_levels=["low", "high"]))
    m = _Model("glm-5.2", {"thinkingLevelMap": {"max": "ultra"}})

    block = build_caps_block(m, pool)
    assert block["thinkingLevelMap"]["max"] == "ultra"   # 覆写生效
    assert block["thinkingLevelMap"]["low"] == "low"     # 其余仍来自目录


def test_thinking_format_comes_from_dialects_not_enum_entry():
    """`thinkingFormat` 从**方言表**取（L-C 层），不在 `EnumEntry` 上取（它没有该字段）。"""
    pool = _pool(EnumEntry("glm-5.2", "GLM-5.2"))
    table = DialectTable(entries={"glm-5.2": Dialect("glm-5.2", thinking_format="openai")})

    block = build_caps_block(_Model("glm-5.2"), pool, table)
    assert block["thinkingFormat"] == "openai"


def test_enum_entry_has_no_thinking_format_field():
    """回归护栏：`EnumEntry` **不得**出现 `thinking_format`（方案原稿曾误引）。"""
    assert not hasattr(EnumEntry("x"), "thinking_format")


# ---------- §13.1 规范档位序（开放可扩展） ----------

def test_levels_are_seven_in_ascending_order():
    assert LEVELS == ("off", "minimal", "low", "medium", "high", "xhigh", "max")


def test_off_spec_level_passes_through_unchanged():
    """🔴 规范外档位（实测 `ultra`）**原样透传、不报错**（开放可扩展）。"""
    assert degrade_effort("ultra", ["low", "high", "ultra"]) == "ultra"


# ---------- §13.2 降级：只降不升、就近 ----------

def test_degrade_only_goes_down():
    """目标档不支持 → 向下就近取（**只降不升**）。"""
    assert degrade_effort("max", ["low", "high"]) == "high"


def test_degrade_passes_through_when_supported():
    assert degrade_effort("high", ["low", "high", "max"]) == "high"


def test_degrade_without_lower_option_takes_nearest_above():
    """向下无可用时向上取最近（宁可多给推理预算，也不静默丢参数）。"""
    assert degrade_effort("minimal", ["high", "max"]) == "high"


def test_degrade_no_supported_list_is_noop():
    """无支持列表 → 原样返回（不臆断）。"""
    assert degrade_effort("high", []) == "high"


def test_is_closed_recognizes_off_and_none():
    assert is_closed("off") and is_closed("none") and is_closed("disabled")
    assert not is_closed("high")


# ---------- §13.4 方言表读写 ----------

def test_dialect_table_roundtrip(tmp_path: Path):
    p = tmp_path / "dialects.json"
    t = DialectTable(path=p)
    t.entries["glm-5.2"] = Dialect(
        "glm-5.2", write_field="reasoning_effort", values=["low", "high", "max"],
        thinking_format="openai", verified=True, note="S2 通过",
    )
    t.save()

    back = DialectTable.load(p)
    d = back.get("glm-5.2")
    assert d is not None
    assert d.write_field == "reasoning_effort"
    assert d.values == ["low", "high", "max"]
    assert d.verified is True
    assert back.thinking_format_of("glm-5.2") == "openai"


def test_dialect_table_missing_file_is_empty():
    """文件缺失 → 空表（安全降级，走硬编码 fallback），不抛异常。"""
    t = DialectTable.load("/nonexistent/dialects.json")
    assert t.entries == {}
    assert t.thinking_format_of("anything") == ""


def test_dialect_table_corrupt_file_is_empty(tmp_path: Path):
    p = tmp_path / "dialects.json"
    p.write_text("{ not json", encoding="utf-8")
    assert DialectTable.load(p).entries == {}


def test_dialect_table_save_is_atomic(tmp_path: Path):
    """落盘走 tempfile + replace（与既有纪律同口径）—— 不留 .tmp 残留。"""
    p = tmp_path / "dialects.json"
    t = DialectTable(path=p)
    t.entries["m"] = Dialect("m", verified=True)
    t.save()

    assert p.exists()
    assert not (tmp_path / "dialects.json.tmp").exists()
    assert json.loads(p.read_text(encoding="utf-8"))["dialects"]["m"]["verified"] is True
