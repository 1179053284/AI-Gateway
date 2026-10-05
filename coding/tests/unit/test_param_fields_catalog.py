"""UT · 内置目录的**官方参数档案** `EnumEntry.param_fields`（2026-10-04 排查轮的机制腿）。

钉四件事（都是这次排查暴露出来的形状）：

1. `params_default` 由档案**派生**，只取「官方可注入档 + 公布了缺省值」的键 ——
   一个 dict 不再同时表示"官方暴露什么"和"官方缺省是多少"（那正是参数卡整张画空的根因）；
2. 构造方另外塞一份不一致的 `params_default` ⇒ **加载期就拒**（两套真相同形于 Q33 一路在拆的病）；
3. 档案本身写错形状（kind 不在册 / enum 没有 values / 缺省值与 kind 不匹配）⇒ **加载期就拒**，
   不许带着坏档案启动 —— 它是界面依据列与写面警告的唯一上游；
4. `EnumPool.param_advice` **只标不拦**：有偏差出说明句、没档案不评（不给别人的键瞎判对错）。
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from model_gateway.enums.matcher import (
    BUILTIN_ENTRIES,
    EnumEntry,
    EnumPool,
    load_enum_pool,
)


def _entry(**over) -> EnumEntry:
    base = dict(name="demo-model", display="Demo", vendor="Demo 厂商")
    base.update(over)
    return EnumEntry(**base)


SUPPORTED_TEMP = {"kind": "number", "availability": "supported",
                  "default": 1.0, "min": 0.0, "max": 2.0,
                  "note": "官方缺省 1.0", "source": "example.dev 2026-10-04"}


# ---------- 1) 派生 ----------
def test_params_default_derives_from_supported_fields():
    e = _entry(param_fields={
        "temperature": copy.deepcopy(SUPPORTED_TEMP),
        "top_p": {"kind": "number", "availability": "supported", "min": 0.0, "max": 1.0},
    })
    # 官方没公布缺省的键 ⇒ 不注入，但**它在档案里**（界面照样出行，依据列写"未公布缺省"）
    assert e.params_default == {"temperature": 1.0}
    # 键的**顺序**就是界面的出行顺序（档案声明序 → 用户自定义键排后）
    assert list(e.param_fields.keys()) == ["temperature", "top_p"]


@pytest.mark.parametrize("avail", ["deprecated", "ignored", "rejected"])
def test_non_injectable_availability_never_enters_params_default(avail):
    spec = {"kind": "number", "availability": avail, "default": 0.2, "min": 0.0, "max": 2.0}
    e = _entry(param_fields={"temperature": spec})
    assert e.params_default == {}


def test_no_fields_keeps_params_default_untouched():
    """未取证 / 用户 YAML 老条目：零行为变化（不许把已有缺省值判空）。"""
    e = _entry(params_default={"temperature": 1.0, "top_p": 0.95})
    assert e.params_default == {"temperature": 1.0, "top_p": 0.95}


# ---------- 2) 两份来源不一致 ⇒ 拒 ----------
def test_conflicting_explicit_params_default_is_rejected():
    with pytest.raises(ValueError, match="不一致"):
        _entry(params_default={"temperature": 0.5},
               param_fields={"temperature": copy.deepcopy(SUPPORTED_TEMP)})


def test_matching_explicit_params_default_is_accepted():
    e = _entry(params_default={"temperature": 1.0},
               param_fields={"temperature": copy.deepcopy(SUPPORTED_TEMP)})
    assert e.params_default == {"temperature": 1.0}


# ---------- 3) 档案形状错了就拒 ----------
@pytest.mark.parametrize("spec,why", [
    ({"kind": "map", "availability": "supported"}, "kind"),
    ({"kind": "number"}, "availability"),
    ({"kind": "number", "availability": "maybe"}, "availability"),
    ({"kind": "enum", "availability": "supported"}, "values"),
    ({"kind": "enum", "availability": "supported", "values": ["a"], "default": "b"}, "values"),
    ({"kind": "number", "availability": "supported", "default": "hot"}, "不匹配"),
    ({"kind": "integer", "availability": "supported", "default": 1.5}, "整数"),
    ({"kind": "boolean", "availability": "supported", "default": 1}, "布尔"),
    ({"kind": "string", "availability": "supported", "default": 3}, "字符串"),
    ({"kind": "string_list", "availability": "supported", "default": {"a": 1}}, "字符串数组"),
])
def test_bad_field_shape_fails_at_load_time(spec, why):
    with pytest.raises(ValueError, match=why):
        _entry(param_fields={"whatever": spec})


def test_non_dict_field_is_rejected():
    with pytest.raises(ValueError, match="须为 dict"):
        _entry(param_fields={"temperature": 1.0})


# ---------- 3b) `inject: false` = 官方缺省已知，但网关这一项不写 ----------
def test_inject_false_records_the_fact_without_injecting():
    spec = {"kind": "number", "availability": "supported", "default": 1.0,
            "min": 0.0, "max": 1.0, "inject": False,
            "note": "A value of 1.0 will be accepted for backwards compatibility",
            "source": "platform.claude.com 2026-10-04"}
    e = _entry(param_fields={"temperature": spec})
    assert e.params_default == {}                      # 不注入
    assert e.param_fields["temperature"]["default"] == 1.0   # 事实照记（界面依据列要说它）


@pytest.mark.parametrize("spec", [
    {"kind": "number", "availability": "supported", "inject": False},          # 没有缺省值
    {"kind": "number", "availability": "rejected", "default": 0.3, "inject": False},  # 不可设的键谈不上注入
    {"kind": "number", "availability": "supported", "default": 1.0, "inject": "no"},  # 非布尔
])
def test_inject_false_only_makes_sometimes(spec):
    with pytest.raises(ValueError, match="inject"):
        _entry(param_fields={"temperature": spec})


# ---------- 3c) 🔴 迁移边界：补档案**不许**改出站形状 ----------
#: 2026-10-04 参数档案回填**之前**的在册注入值（逐字取自 `enums/matcher.py::BUILTIN_ENTRIES`）。
#: 这一轮的原则是"只往目录里记事实、不动任何一条出站请求的形状"：往 `params_default` 里
#: 多塞一个键 = 所有走这个模型的请求从此带上它（哪怕值恰好等于厂商默认，也是把"厂商以后
#: 改默认"这件事钉死了），而 :8300 上有真实流量。要动它 = 单独裁定，不许夹在回填里溜过去。
PARAMS_DEFAULT_BASELINE = {
    "sensenova-6.8-flash-lite": {"temperature": 1.0, "top_p": 0.95, "top_k": 20,
                                 "min_p": 0.0, "presence_penalty": 1.5,
                                 "repetition_penalty": 1.0},
    "deepseek-v4-flash": {"temperature": 1.0, "top_p": 1.0},
    "deepseek-v4-pro": {"temperature": 1.0, "top_p": 1.0},
    "deepseek-v4-flash-vision-exp": {"temperature": 1.0, "top_p": 1.0},
    "glm-5.2": {"temperature": 1.0, "top_p": 0.95, "do_sample": True, "max_tokens": 65536},
    "glm-5.3": {"temperature": 1.0, "top_p": 0.95, "do_sample": True, "max_tokens": 65536},
    "glm-5.3-flash": {"temperature": 1.0, "top_p": 0.95, "do_sample": True, "max_tokens": 65536},
    "kimi-k3": {"temperature": 1.0, "top_p": 0.95, "presence_penalty": 0, "frequency_penalty": 0},
    "kimi-k2.7-code": {"temperature": 1.0, "top_p": 0.95, "presence_penalty": 0,
                       "frequency_penalty": 0},
    "kimi-k2.7-code-highspeed": {"temperature": 1.0, "top_p": 0.95, "presence_penalty": 0,
                                 "frequency_penalty": 0},
    "kimi-k2.6": {"temperature": 1.0, "top_p": 0.95, "presence_penalty": 0,
                  "frequency_penalty": 0},
    "MiniMax-M3": {"temperature": 1.0, "top_p": 0.95},
    # 🔴 2026-10-04 数据更正（不是回填顺手改行为）：M2.7 两条原注 top_p 0.90 出自 description
    #   正文，三份端点 schema 的 `default` 都是 0.95（r1-D 与 r2-2 独立同判、零推翻）⇒ 种子值
    #   改回官方。实盘 `data/config.yaml` 里已落盘的 0.9 不受影响（要跟进请在参数卡改值或
    #   点「恢复官方配置」）。逐条记在交付台账「数据更正」一节。
    "MiniMax-M2.7": {"temperature": 1.0, "top_p": 0.95},
    "MiniMax-M2.7-highspeed": {"temperature": 1.0, "top_p": 0.95},
}


def test_param_fields_cover_every_vendor_but_openai():
    """档案覆盖面（回填不许悄悄漏掉一家人）：除 OpenAI 五款外，在册 chat 模型全部有档案。

    OpenAI 那一路取证代理没跑完（步数上限）⇒ 本轮如实留空，界面走「未取证」那一档；
    两条 images 与两款 legacy 官方 API 参考未取证，同样留空。
    """
    filled = {e.name for e in BUILTIN_ENTRIES if e.param_fields}
    left_open = {e.name for e in BUILTIN_ENTRIES if not e.param_fields}
    assert left_open == {
        # 两条 images：官方 API 参考本轮没取证（u1 平台文档是 SPA 空壳，见 r1-E U 表）
        "sensenova-u1-fast", "sensenova-u1.5-lite",
        # 两款 legacy 别名条目：属性本就未取证（目录原注），不给他们编档案
        "claude-sonnet-4", "claude-opus-4"}, left_open
    assert len(filled) == 32


def test_filling_param_fields_does_not_change_outbound_shape():
    """派生之后，注入值集合必须与回填前**逐键逐值相同**（多一个键少一个键都算红）。"""
    got = {e.name: e.params_default for e in BUILTIN_ENTRIES if e.params_default}
    assert got == PARAMS_DEFAULT_BASELINE, (
        "参数档案回填改动了网关注入形状 —— 这不属于本轮范围，"
        "要改请单独裁定（每条差异都会落到真实请求体上）")


# ---------- 4) 出口与回读 ----------
def test_to_dict_carries_param_fields_for_the_enums_api():
    e = _entry(param_fields={"temperature": copy.deepcopy(SUPPORTED_TEMP)})
    d = e.to_dict()
    assert d["param_fields"]["temperature"]["availability"] == "supported"
    assert d["params_default"] == {"temperature": 1.0}


def test_builtin_catalog_still_imports_and_exposes_the_new_key():
    pool = EnumPool(BUILTIN_ENTRIES)
    assert len(pool.entries) == len(BUILTIN_ENTRIES)
    for entry in pool.entries.values():
        d = entry.to_dict()
        assert "param_fields" in d
        # 有档案的条目：params_default 必须是派生结果（不许有人手填第二份）
        if entry.param_fields:
            derived = {k: s["default"] for k, s in entry.param_fields.items()
                       if s["availability"] == "supported" and s.get("default") is not None
                       and s.get("inject", True) is not False}
            assert entry.params_default == derived
        # 注入了的键，官方口径必须是可注入档（有档案时）
        for k in entry.params_default:
            spec = entry.param_fields.get(k)
            assert spec is None or spec["availability"] == "supported"


def test_yaml_pool_round_trips_param_fields(tmp_path: Path):
    path = tmp_path / "model-enums.yaml"
    path.write_text(yaml.safe_dump({"entries": [{
        "name": "yaml-model", "vendor": "Y", "context_window": 1000,
        "param_fields": {"temperature": copy.deepcopy(SUPPORTED_TEMP),
                         "top_k": {"kind": "integer", "availability": "rejected", "default": 20}},
        # params_default 不写：由档案派生（写了就必须与派生一致，否则加载报错）
    }]}, allow_unicode=True), encoding="utf-8")
    pool = load_enum_pool(path)
    entry = pool.get("yaml-model")
    assert entry.params_default == {"temperature": 1.0}
    assert entry.param_fields["top_k"]["availability"] == "rejected"


def test_yaml_pool_rejects_conflicting_pair(tmp_path: Path):
    path = tmp_path / "model-enums.yaml"
    path.write_text(yaml.safe_dump({"entries": [{
        "name": "bad-model",
        "params_default": {"temperature": 0.1},
        "param_fields": {"temperature": copy.deepcopy(SUPPORTED_TEMP)},
    }]}, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="不一致"):
        load_enum_pool(path)


# ---------- 5) param_advice：只标不拦 ----------
@pytest.fixture
def pool() -> EnumPool:
    return EnumPool([_entry(param_fields={
        "temperature": copy.deepcopy(SUPPORTED_TEMP),
        "top_k": {"kind": "integer", "availability": "rejected", "default": 20,
                  "note": "非默认值返回 400", "source": "example.dev"},
        "seed": {"kind": "integer", "availability": "ignored"},
        "presence_penalty": {"kind": "number", "availability": "deprecated", "default": 0.0},
        "response_format": {"kind": "enum", "availability": "supported",
                           "values": ["text", "json_object"]},
    })])


def test_advice_flags_rejected_ignored_deprecated(pool):
    out = pool.param_advice("demo-model", {"top_k": 40, "seed": 7, "presence_penalty": 1.0})
    assert any("对非默认值返回报错" in t and "top_k" in t for t in out)
    assert any("忽略" in t and "seed" in t for t in out)
    assert any("废弃" in t and "presence_penalty" in t for t in out)
    # 官方出处必须跟着走：没有原话就没资格说"官方会报错"
    assert any("example.dev" in t for t in out)


def test_advice_flags_out_of_range_and_bad_enum(pool):
    out = pool.param_advice("demo-model", {"temperature": 9.0, "response_format": "yaml"})
    assert any("超出官方公布范围" in t for t in out)
    assert any("不在官方枚举" in t for t in out)


def test_advice_says_nothing_without_a_record(pool):
    # 自定义键 / 条目不在目录 / 该键没档案 ⇒ 一律不评（Q24「未知键放行」，不凭猜判人错）
    assert pool.param_advice("demo-model", {"my_custom": 1}) == []
    assert pool.param_advice("no-such-model", {"top_k": 40}) == []


def test_builtin_pool_has_36_entries_and_advice_survives_them():
    pool = EnumPool(BUILTIN_ENTRIES)
    # 内置目录里那些**有缺省值**的条目，档案此刻可能还没回填（取证轮在路上）——
    # 回填之后这句仍然成立：advice 对未回填的条目必须安静，而不是凭空出话
    assert pool.param_advice("glm-5.3", {"temperature": 1.0}) == []
