"""厂商预设注册表 UT（UT-26；PRD FR-1.2 / tech-design §4.7）。

三条内置预设字段完整性 + 计费口径降级 + 深拷贝防篡改。
"""

from __future__ import annotations

from model_gateway.config.presets import PRESETS, display_billing, list_presets


class TestPresets:
    """UT-26：预设注册表内置数据。"""

    def test_three_presets_with_expected_ids(self):
        presets = list_presets()
        assert len(presets) == 3
        assert {p["id"] for p in presets} == {
            "sensenova-api", "sensenova-tokenplan", "custom"}

    def test_field_completeness(self):
        """七字段全存在；sensenova 两条 base_url 非空且 https:// 开头；mode 合法。"""
        fields = {"id", "name", "mode", "protocol", "base_url", "billing", "notes"}
        by_id = {p["id"]: p for p in list_presets()}
        assert set(by_id) == {"sensenova-api", "sensenova-tokenplan", "custom"}
        for pid, p in by_id.items():
            assert set(p.keys()) == fields, f"{pid} 字段不完整"
            assert p["name"] and p["protocol"]  # name/protocol 均非空
        # sensenova 两条：base_url 非空且 https:// 开头（tech-design §4.7 表）
        assert by_id["sensenova-api"]["base_url"] == "https://api.sensenova.cn/compatible-mode/v2"
        assert by_id["sensenova-tokenplan"]["base_url"] == "https://token.sensenova.cn/v1"
        # custom：空白模板（mode/base_url/billing 全空，用户手动填）
        assert by_id["custom"]["base_url"] == "" and by_id["custom"]["billing"] == ""
        # mode ∈ {api, plan, ""}
        assert by_id["sensenova-api"]["mode"] == "api"
        assert by_id["sensenova-tokenplan"]["mode"] == "plan"
        assert by_id["custom"]["mode"] == ""

    def test_display_billing(self):
        """有值返回原值；空/未知口径（缺失或空串）降级「—」不报错。"""
        by_id = {p["id"]: p for p in list_presets()}
        assert display_billing(by_id["sensenova-api"]) == "按量付费"
        assert display_billing(by_id["sensenova-tokenplan"]) == "积分制"
        assert display_billing(by_id["custom"]) == "—"
        assert display_billing({"billing": ""}) == "—"
        assert display_billing({}) == "—"  # 缺 billing 字段 = 未知口径

    def test_list_presets_returns_deep_copy(self):
        """改返回值不影响内部常量（外部篡改隔离）。"""
        presets = list_presets()
        presets[0]["name"] = "篡改"
        presets[0]["billing"] = ""
        presets.pop()
        fresh = list_presets()
        assert len(fresh) == 3
        assert fresh[0]["name"] == "商汤按量 API"
        assert fresh[0]["billing"] == "按量付费"
        # 内部常量本体未被污染
        assert PRESETS[0]["name"] == "商汤按量 API"
        assert len(PRESETS) == 3
