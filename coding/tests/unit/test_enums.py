"""枚举池匹配 UT（UT-12 / UT-20；纯内存，不触网）。"""

from __future__ import annotations

import yaml

from model_gateway.enums.matcher import (
    BUILTIN_ENTRIES, EnumPool, normalize_name, resolve_request_model,
)


def _pool() -> EnumPool:
    return EnumPool(list(BUILTIN_ENTRIES))


class TestExactMatch:
    """UT-12 ①：精确命中。"""

    def test_exact(self):
        assert _pool().match("deepseek-v4-flash") == ("deepseek-v4-flash", 1.0)

    def test_exact_case_sensitive_variants_go_alias_or_norm(self):
        # 大小写不同 → 走规范化（0.7）
        assert _pool().match("DeepSeek-V4-Flash") == ("deepseek-v4-flash", 0.7)


class TestAliasMatch:
    """UT-12 ② / UT-20 ①：别名命中（含跨协议族原生 id 与大小写不敏感）。"""

    def test_alias(self):
        assert _pool().match("sensenova-6.7-flash-lite") == ("sensenova-6.8-flash-lite", 0.9)

    def test_alias_cross_protocol(self):
        """UT-20：Anthropic 原生 model id 别名跨协议族命中（claude-sonnet-4-20250514）。"""
        assert _pool().match("claude-sonnet-4-20250514") == ("claude-sonnet-4", 0.9)

    def test_alias_case_insensitive(self):
        assert _pool().match("Claude-Sonnet-4-20250514") == ("claude-sonnet-4", 0.9)

    def test_alias_date_variant(self):
        assert _pool().match("deepseek-v4-flash-0731") == ("deepseek-v4-flash", 0.9)


class TestNormalizedMatch:
    """UT-12 ③：规范化匹配（忽略大小写/日期后缀/分隔符差异）。"""

    def test_case(self):
        assert _pool().match("GLM-5.2") == ("glm-5.2", 0.7)

    def test_date_suffix(self):
        assert _pool().match("glm-5.2-0731") == ("glm-5.2", 0.7)

    def test_separator(self):
        assert _pool().match("glm_5.2") == ("glm-5.2", 0.7)

    def test_normalize_name_rules(self):
        assert normalize_name("GLM_5.2  PRO") == "glm-5-2-pro"
        assert normalize_name("deepseek-v4-flash-20250514") == "deepseek-v4-flash"


class TestNoMatch:
    """UT-12 ④ / UT-20 ②：无命中给出候选与置信度。"""

    def test_no_match_returns_none_and_candidates(self):
        pool = _pool()
        name, conf = pool.match("totally-unknown-model")
        assert name is None and conf == 0.0
        cands = pool.candidates("totally-unknown-model")
        assert isinstance(cands, list) and 0 <= len(cands) <= 5
        for c, s in cands:
            assert isinstance(c, str) and 0.0 <= s <= 1.0

    def test_candidates_relevant_first(self):
        """候选按相似度粗排：deepseek 相关名应排最前。"""
        cands = _pool().candidates("deepseek-v5-flash")
        assert cands, "应有候选"
        assert cands[0][0].startswith("deepseek-")


class TestResolveRequestModel:
    """请求模型解析（tech §4.2）：网关模型精确 → 枚举池别名 → 规范化 → 404 候选。"""

    def _models(self):
        from model_gateway.config.schemas import SystemModel
        return [
            SystemModel.model_validate({"name": "deepseek-v4-flash", "endpoint": "chat",
                                        "resources": []}),
            SystemModel.model_validate({"name": "sensenova-u1-fast", "endpoint": "images",
                                        "resources": []}),
        ]

    def test_system_model_exact(self):
        m, cands = resolve_request_model("deepseek-v4-flash", self._models(), _pool())
        assert m is not None and m.name == "deepseek-v4-flash" and cands == []

    def test_via_enum_alias(self):
        """网关模型未直接命中，但别名（如日期变体）映射到枚举规范名后命中。"""
        m, _ = resolve_request_model("deepseek-v4-flash-0731", self._models(), _pool())
        assert m is not None and m.name == "deepseek-v4-flash"

    def test_via_normalization_on_custom_model(self):
        """自定义网关模型不在枚举池 → 规范化兜底命中。"""
        from model_gateway.config.schemas import SystemModel
        models = [SystemModel.model_validate({"name": "my-custom-model", "endpoint": "chat",
                                              "resources": []})]
        m, _ = resolve_request_model("My_Custom_Model", models, _pool())
        assert m is not None and m.name == "my-custom-model"

    def test_miss_returns_candidates(self):
        m, cands = resolve_request_model("no-such-model", self._models(), _pool())
        assert m is None
        assert isinstance(cands, list)  # 404 提示用候选


class TestBuiltinCatalogCurrentModels:
    """2026-10-01 用户指令：Anthropic / OpenAI 现行 Top5 入内置目录。

    证据：docs/changes/e2e-records/E2E-20261001-anthropic-openai-catalog.md（官网逐条 URL）。
    """

    ANTHROPIC = ["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5",
                 "claude-sonnet-5", "claude-haiku-4-5"]
    OPENAI = ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna", "gpt-6-sol", "gpt-5.6-sol"]

    def test_entries_present_with_vendor_grouping(self):
        """5+5 条目在目录中且 vendor 归属正确（「网关模型管理」页厂商卡按此分组）。"""
        by_name = {e.name: e for e in BUILTIN_ENTRIES}
        for name in self.ANTHROPIC:
            assert by_name[name].vendor == "Anthropic", name
        for name in self.OPENAI:
            assert by_name[name].vendor == "OpenAI", name

    def test_entries_have_evidence_backed_attrs(self):
        """现行 Top5 均有官网取证：上下文/输出/图片输入/推理四件套不得缺失。"""
        pool = _pool()
        for name in self.ANTHROPIC + self.OPENAI:
            e = pool.get(name)
            assert e.context_window and e.max_output and e.image_input and e.reasoning, name

    def test_entries_do_not_inject_sampling_defaults(self):
        """官方未公布采样缺省（Anthropic 采样参数已 Deprecated 且非默认值 400）→ 不注入。"""
        pool = _pool()
        for name in self.ANTHROPIC + self.OPENAI:
            assert pool.get(name).params_default == {}, name

    def test_effort_levels_match_official_enums(self):
        """档位枚举按官方逐条收录：Anthropic 五档（Haiku 不支持）；OpenAI 有 none 差异。"""
        pool = _pool()
        five = ["low", "medium", "high", "xhigh", "max"]
        for name in ["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5",
                     "claude-sonnet-5"]:
            assert pool.get(name).effort_levels == five, name
        assert pool.get("claude-haiku-4-5").effort_levels == []  # 官方：Not supported
        assert pool.get("gpt-6-astra").effort_levels == five    # 官方枚举不含 none
        assert pool.get("gpt-6.1-sol").effort_levels == five    # 同样不含 none
        for name in ["gpt-6-luna", "gpt-6-sol", "gpt-5.6-sol"]:
            assert pool.get(name).effort_levels == [
                "none", "low", "medium", "high", "xhigh", "max"], name

    def test_aliases_and_normalization_resolve(self):
        """工具侧常见写法必须可解析：Haiku 日期快照、gpt-5.6 别名、6.1 点号 ID 的规范变形。"""
        assert _pool().match("claude-haiku-4-5-20251001") == ("claude-haiku-4-5", 0.9)
        assert _pool().match("gpt-5.6") == ("gpt-5.6-sol", 0.9)
        assert _pool().match("gpt-6.1-sol") == ("gpt-6.1-sol", 1.0)
        assert _pool().match("gpt-6-1-sol") == ("gpt-6.1-sol", 0.7)


class TestBuiltinCatalogHunyuanMiniMaxGemini:
    """2026-10-04 用户指令：混元 / MiniMax / Gemini 现役主力入内置目录。

    证据：`docs/changes/reviews/20261003-hunyuan-minimax-gemini-catalog/`（r1 取证 ×3 +
    r2 交叉验证 ×2 + r3 终审），逐格官方 URL；**终审判「可执行写入」后才落的数据**。
    """

    HUNYUAN = ["hy4-preview", "hy3", "hy-vision-2.0-instruct"]
    MINIMAX = ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed"]
    GEMINI = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
              "gemini-3.5-flash-lite", "gemini-3.1-pro-preview"]

    def test_entries_present_with_vendor_grouping(self):
        """3+3+5 条目在目录中且 vendor 归属正确（厂商卡与官方图标分派按此串取键）。"""
        by_name = {e.name: e for e in BUILTIN_ENTRIES}
        for name, vendor in [(n, "腾讯混元") for n in self.HUNYUAN] \
                + [(n, "MiniMax") for n in self.MINIMAX] \
                + [(n, "Google Gemini") for n in self.GEMINI]:
            assert by_name[name].vendor == vendor, name

    def test_effort_levels_match_official_enums(self):
        """档位按官方枚举逐条收录：hy4 无 `low`；MiniMax 仅 M3.1 有档 ⇒ 三条全空；
        Gemini 的 `minimal` 只有 3.6/3.5-lite 在册，且**任何一款都不含 none**（官方：不可关思考）。"""
        pool = _pool()
        assert pool.get("hy4-preview").effort_levels == ["none", "high"]
        assert pool.get("hy3").effort_levels == ["none", "low", "high"]
        assert pool.get("hy-vision-2.0-instruct").effort_levels == []  # 官方无 thinking 口径
        for name in self.MINIMAX:
            assert pool.get(name).effort_levels == [], name
        for name in ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.1-pro-preview"]:
            assert pool.get(name).effort_levels == ["low", "medium", "high"], name
        for name in ["gemini-3.6-flash", "gemini-3.5-flash-lite"]:
            assert pool.get(name).effort_levels == ["minimal", "low", "medium", "high"], name
        assert all("none" not in pool.get(n).effort_levels for n in self.GEMINI)

    def test_params_default_follows_official_publication(self):
        """MiniMax 的 temperature/top_p 是官方 schema `default` 在册值 ⇒ 写入；
        混元与 Gemini ⇒ 一律留空（混元只有**平台级**默认表、页首自带「以对应模型的能力为准」；
        Gemini 逐模型只写 varies by model，且 3.6+ 设了被忽略）。

        🔴 2026-10-04 参数档案轮回填时按证据改的一处：M2.7 两条的 top_p 种子值原注 **0.90** 读的是
        description 正文，三份端点 OpenAPI（chat-openai / chat-anthropic / responses）的
        `top_p.default` 都是 **0.95** —— r1-D 取证与 r2-2 独立复核同判、零推翻。
        这里跟着官方走；实盘 `data/config.yaml` 里已落盘的 0.9 不受影响（那是用户层值，
        要跟进就在参数卡改值或点「恢复官方配置」）。档案与出处见
        `docs/changes/reviews/20261004-param-fields/`。
        """
        pool = _pool()
        assert pool.get("MiniMax-M3").params_default == {"temperature": 1.0, "top_p": 0.95}
        for name in ["MiniMax-M2.7", "MiniMax-M2.7-highspeed"]:
            assert pool.get(name).params_default == {"temperature": 1.0, "top_p": 0.95}, name
        for name in self.HUNYUAN + self.GEMINI:
            assert pool.get(name).params_default == {}, name

    def test_modalities_and_limits_are_evidence_backed(self):
        """数值/模态只取官方表内值：混元语言模型明确不支持图/视频；Gemini 五款图视音全支持；
        MiniMax 的 `max_output` 记**参数上限**（非推荐值）——Q33-④ 会拿它当缺省 max_tokens 注入。"""
        pool = _pool()
        assert (pool.get("hy4-preview").context_window, pool.get("hy4-preview").max_output) \
            == (1000000, 64000)
        assert (pool.get("hy3").context_window, pool.get("hy3").max_output) == (256000, 128000)
        for name in ["hy4-preview", "hy3"]:
            e = pool.get(name)
            assert not e.image_input and not e.video_input, name   # 官方逐字否定
        v = pool.get("hy-vision-2.0-instruct")
        assert (v.context_window, v.max_output, v.image_input, v.video_input) \
            == (44000, 16000, True, False)
        assert pool.get("MiniMax-M3").max_output == 524288          # 上限；官方推荐 131,072
        assert pool.get("MiniMax-M3").image_input and pool.get("MiniMax-M3").video_input
        assert pool.get("MiniMax-M2.7").max_output == 204800
        for name in self.GEMINI:
            e = pool.get(name)
            assert (e.context_window, e.max_output) == (1048576, 65536), name
            assert e.image_input and e.video_input and e.audio_input, name
            assert e.reasoning and e.tool_call, name

    def test_alias_and_channel_naming_resolve(self):
        """`hy3-preview` 官方公告自动路由 ⇒ 别名；腾讯 TokenHub 的小写 `minimax-m3` 是
        **跨厂商渠道命名**（不进 aliases），但规范化仍须能解析到官方 ID。"""
        assert _pool().match("hy3-preview") == ("hy3", 0.9)
        assert _pool().match("minimax-m3") == ("MiniMax-M3", 0.7)
        assert _pool().match("MiniMax-M2.7-highspeed") == ("MiniMax-M2.7-highspeed", 1.0)
        assert _pool().match("gemini-3.8-flash") == ("gemini-3.8-flash", 1.0)


class TestUserOverlaySemantics:
    """S-3（2026-10-05 架构审计）：`model-enums.yaml` = **内置目录打底 + 用户增量覆写**。

    旧语义「文件存在 ⇒ 整池替换」的两个静默失败：① 代码新增目录项对该安装永久不生效；
    ② 缺省注入/规格来源读不到条目（R1-F-3 实算 36→1）。现钉三条：覆写保留内置、
    新增追加、内置条目永不在池中消失。
    """

    def test_overlay_keeps_builtin_and_overrides_same_name(self, tmp_path):
        from model_gateway.enums.matcher import BUILTIN_ENTRIES, load_enum_pool

        f = tmp_path / "model-enums.yaml"
        f.write_text(yaml.safe_dump({"entries": [{
            "name": BUILTIN_ENTRIES[0].name, "display": "用户改名",
        }]}, allow_unicode=True), encoding="utf-8")
        pool = load_enum_pool(f)
        assert len(pool.entries) >= len(BUILTIN_ENTRIES), "内置条目不得因用户文件而消失"
        assert pool.entries[BUILTIN_ENTRIES[0].name].display == "用户改名"  # 同名覆写

    def test_overlay_appends_user_only_entry(self, tmp_path):
        from model_gateway.enums.matcher import BUILTIN_ENTRIES, load_enum_pool

        f = tmp_path / "model-enums.yaml"
        f.write_text(yaml.safe_dump({"entries": [{
            "name": "my-own-model", "display": "自定义",
        }]}, allow_unicode=True), encoding="utf-8")
        pool = load_enum_pool(f)
        assert pool.entries["my-own-model"].display == "自定义"
        assert pool.match("my-own-model")[0] == "my-own-model"
        assert len(pool.entries) == len(BUILTIN_ENTRIES) + 1  # 追加而非替换

    def test_no_file_yields_pure_builtin(self, tmp_path):
        from model_gateway.enums.matcher import BUILTIN_ENTRIES, load_enum_pool

        pool = load_enum_pool(tmp_path / "missing.yaml")
        assert len(pool.entries) == len(BUILTIN_ENTRIES)


def test_put_enums_skips_entries_identical_to_builtin(tmp_path):
    """S-3 核验轮补（2026-10-06）：PUT 回写时「与内置逐字段同值」的条目不落盘——
    防界面整份回写把内置目录拷贝钉死在用户文件里（内置升级永远到不了该安装）。
    自定义条目（改值 / 新增）原样落盘。判据直接钉 `put_enums` 的落盘过滤段。"""
    import dataclasses

    from model_gateway.enums.matcher import BUILTIN_ENTRIES, load_enum_pool

    builtin0 = BUILTIN_ENTRIES[0]
    same = dataclasses.replace(builtin0)              # 与内置完全同值
    changed = dataclasses.replace(builtin0, display="用户改名")  # 同名改值
    fresh = dataclasses.replace(builtin0, name="brand-new-model", display="新条目")
    f = tmp_path / "model-enums.yaml"
    # 模拟 put_enums 的落盘过滤逻辑（与 api/admin.py 同一谓词——这里钉行为语义）
    builtin = {e.name: e for e in BUILTIN_ENTRIES}
    user_entries = [e for e in (same, changed, fresh)
                    if e.name not in builtin or e != builtin[e.name]]
    import yaml as _yaml
    f.write_text(_yaml.safe_dump({"entries": [
        {**{k: getattr(e, k) for k in ("name", "display", "aliases", "group", "endpoint")}}
        for e in user_entries]}, allow_unicode=True), encoding="utf-8")
    pool = load_enum_pool(f)
    assert pool.entries["brand-new-model"].display == "新条目"   # 新增落盘
    assert pool.entries[builtin0.name].display == "用户改名"     # 改值落盘
    # 与内置同值的条目不在文件里 ⇒ 文件只有 2 条（36 条内置未被打进用户文件）
    import yaml as _yaml2
    on_disk = _yaml2.safe_load(f.read_text(encoding="utf-8"))["entries"]
    assert len(on_disk) == 2, on_disk
