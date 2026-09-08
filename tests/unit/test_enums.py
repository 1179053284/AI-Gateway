"""枚举池匹配 UT（UT-12 / UT-20；纯内存，不触网）。"""

from __future__ import annotations

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
    """请求模型解析（tech §4.2）：系统模型精确 → 枚举池别名 → 规范化 → 404 候选。"""

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
        """系统模型未直接命中，但别名（如日期变体）映射到枚举规范名后命中。"""
        m, _ = resolve_request_model("deepseek-v4-flash-0731", self._models(), _pool())
        assert m is not None and m.name == "deepseek-v4-flash"

    def test_via_normalization_on_custom_model(self):
        """自定义系统模型不在枚举池 → 规范化兜底命中。"""
        from model_gateway.config.schemas import SystemModel
        models = [SystemModel.model_validate({"name": "my-custom-model", "endpoint": "chat",
                                              "resources": []})]
        m, _ = resolve_request_model("My_Custom_Model", models, _pool())
        assert m is not None and m.name == "my-custom-model"

    def test_miss_returns_candidates(self):
        m, cands = resolve_request_model("no-such-model", self._models(), _pool())
        assert m is None
        assert isinstance(cands, list)  # 404 提示用候选
