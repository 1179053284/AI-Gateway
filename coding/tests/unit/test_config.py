"""配置加载与校验单元测试（M1 任务 1 验证；对应 test-cases UT-13/UT-18 的部分场景）。

Q18-② 资源扁平化后同步重写：
- 样例配置加载通过（config.example.yaml 与 schema 同步不漂移）
- 引用完整性：资源引用不存在的 resource / 重复 resource id / 重复令牌 id / 重复模型名 → 拒绝并指明位置
- 数值边界：endpoint 非法值 / 总预算 < 尝试超时 / x=0 → 拒绝
- images 资源配置 reasoning → 警告并忽略（Q15）
- 原子写：save_config 后可完整读回

执行状态：以 pytest 实际输出为准（铁律 2：无证据不得打 ✅）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from model_gateway.config.loader import ConfigError, load_config, save_config
from model_gateway.config.schemas import AppConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = PROJECT_ROOT / "config.example.yaml"


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def _minimal_cfg() -> dict:
    """最小合法配置（含一个厂商资源 + 一个系统模型资源引用）。"""
    return {
        "resources": [
            {
                "id": "res-1",
                "name": "商汤·主Key",
                "preset": "sensenova-api",
                "access_mode": "api",
                "protocol": "openai",
                "base_url": "https://api.sensenova.cn/compatible-mode/v2",
                "api_key": "sk-x",
                "account": "主账号",
            }
        ],
        "models": [
            {
                "name": "deepseek-v4-flash",
                "endpoint": "chat",
                "resources": [{"resource": "res-1", "model": "deepseek-v4-flash"}],
            }
        ],
    }


class TestLoadExample:
    def test_example_config_loads(self):
        """样例配置必须能通过全量校验（schema 与样例同步）。"""
        cfg = load_config(EXAMPLE_CONFIG)
        assert cfg.gateway.port == 8300
        assert cfg.gateway.attempt_timeout_seconds == 60
        assert cfg.gateway.request_total_budget_seconds == 300
        assert cfg.scheduling.max_active_per_model == 2
        assert cfg.scheduling.fail_threshold == 2
        assert cfg.scheduling.retry_per_request == 3
        assert len(cfg.resources) == 1
        assert cfg.resources[0].id == "res-xxxxxxxx"
        assert {m.name for m in cfg.models} == {"deepseek-v4-flash", "sensenova-u1-fast"}
        assert cfg.warnings == []

    def test_default_config_when_file_missing(self, tmp_path):
        """配置文件不存在 → 内置默认值 + 警告（tech-design §4.7）。"""
        cfg = load_config(tmp_path / "nope.yaml")
        assert cfg.gateway.attempt_timeout_seconds == 60
        assert any("不存在" in w for w in cfg.warnings)

    def test_empty_file_loads_defaults(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("", encoding="utf-8")
        cfg = load_config(p)
        assert cfg.models == []


class TestCrossReferences:
    def test_resource_ref_unknown_resource(self, tmp_path):
        data = _minimal_cfg()
        data["models"][0]["resources"][0]["resource"] = "res-404"
        with pytest.raises(ConfigError) as e:
            load_config(_write(tmp_path, data))
        assert "引用不存在的 resource 'res-404'" in "; ".join(e.value.errors)
        assert "models[0]('deepseek-v4-flash').resources[0]" in "; ".join(e.value.errors)

    def test_duplicate_resource_id(self, tmp_path):
        data = _minimal_cfg()
        data["resources"].append(dict(data["resources"][0]))
        with pytest.raises(ConfigError) as e:
            load_config(_write(tmp_path, data))
        assert "重复" in "; ".join(e.value.errors)

    def test_duplicate_token_id(self, tmp_path):
        data = _minimal_cfg()
        data["gateway"] = {"access_tokens": [
            {"id": "t1", "value": "mg-a"}, {"id": "t1", "value": "mg-b"}]}
        with pytest.raises(ConfigError) as e:
            load_config(_write(tmp_path, data))
        assert "access_tokens[].id 重复" in "; ".join(e.value.errors)

    def test_duplicate_model_name(self, tmp_path):
        data = _minimal_cfg()
        data["models"].append(dict(data["models"][0]))
        with pytest.raises(ConfigError) as e:
            load_config(_write(tmp_path, data))
        assert "models[].name 重复" in "; ".join(e.value.errors)

    def test_resource_requires_api_key(self, tmp_path):
        """资源 = 厂商 + Key：api_key 必填（空值拒绝）。

        M6-5a 起该约束由**模型级**校验器给出（`product` 为空时必须非空，§22.5-2），
        所以报错位置是 `resources.0`（不再是字段路径 `resources.0.api_key`）——
        判据改为「点到 api_key + 给出原因」，避免把实现形态当成契约钉死。
        """
        data = _minimal_cfg()
        del data["resources"][0]["api_key"]
        with pytest.raises(ConfigError) as e:
            load_config(_write(tmp_path, data))
        errors = "; ".join(e.value.errors)
        assert "api_key" in errors and "不能为空" in errors


class TestValueBounds:
    def test_endpoint_invalid(self, tmp_path):
        data = _minimal_cfg()
        data["models"][0]["endpoint"] = "audio"
        with pytest.raises(ConfigError):
            load_config(_write(tmp_path, data))

    def test_budget_lt_attempt_timeout(self, tmp_path):
        data = _minimal_cfg()
        data["gateway"] = {"attempt_timeout_seconds": 60, "request_total_budget_seconds": 30}
        with pytest.raises(ConfigError) as e:
            load_config(_write(tmp_path, data))
        assert "request_total_budget_seconds" in "; ".join(e.value.errors)

    def test_x_zero_rejected(self, tmp_path):
        data = _minimal_cfg()
        data["scheduling"] = {"max_active_per_model": 0}
        with pytest.raises(ConfigError):
            load_config(_write(tmp_path, data))

    def test_port_out_of_range(self, tmp_path):
        data = _minimal_cfg()
        data["gateway"] = {"port": 99999}
        with pytest.raises(ConfigError):
            load_config(_write(tmp_path, data))


class TestReasoningRules:
    def test_images_resource_reasoning_ignored_with_warning(self, tmp_path):
        """images 资源配置 reasoning → 警告并忽略（§4.7 ⑥，Q15）。"""
        data = _minimal_cfg()
        data["models"].append(
            {
                "name": "sensenova-u1-fast",
                "endpoint": "images",
                "resources": [
                    {
                        "resource": "res-1",
                        "model": "sensenova-u1-fast",
                        "reasoning": {"enabled": True, "effort": "high"},
                    }
                ],
            }
        )
        cfg = load_config(_write(tmp_path, data))
        assert cfg.models[1].resources[0].reasoning is None
        assert any("reasoning" in w for w in cfg.warnings)

    def test_chat_resource_reasoning_kept(self, tmp_path):
        data = _minimal_cfg()
        data["models"][0]["resources"][0]["reasoning"] = {"enabled": True, "effort": "low"}
        cfg = load_config(_write(tmp_path, data))
        assert cfg.models[0].resources[0].reasoning is not None
        assert cfg.models[0].resources[0].reasoning.effort == "low"


class TestAtomicWrite:
    def test_save_and_reload_roundtrip(self, tmp_path):
        """原子写：save_config 后可完整读回（UT-14 场景的前置）。"""
        p = tmp_path / "config.yaml"
        cfg = AppConfig.model_validate(_minimal_cfg())
        save_config(cfg, p)
        reloaded = load_config(p)
        assert reloaded.models[0].name == "deepseek-v4-flash"
        assert reloaded.resources[0].api_key == "sk-x"
        assert reloaded.resources[0].account == "主账号"

    def test_save_leaves_no_tmp_files(self, tmp_path):
        p = tmp_path / "config.yaml"
        save_config(AppConfig.model_validate(_minimal_cfg()), p)
        leftovers = [f.name for f in tmp_path.iterdir() if f.name.endswith(".tmp")]
        assert leftovers == []


class TestModelEnabledSwitch:
    """UT-25：models[].enabled 校验与默认兼容（PRD FR-2.3 / Q17 / D1）。

    ① 非 bool 值 → 拒绝并指明位置与类型错误；② 旧配置缺省该字段 → 正常加载，
    视为 enabled=true（向后兼容）。
    """

    def test_enabled_string_rejected(self, tmp_path):
        """① 字符串 "yes" → 拒绝（Pydantic 宽松模式会强制转换，故字段为 strict）。"""
        data = _minimal_cfg()
        data["models"][0]["enabled"] = "yes"
        with pytest.raises(ConfigError) as e:
            load_config(_write(tmp_path, data))
        joined = "; ".join(e.value.errors)
        assert "models.0.enabled" in joined  # 指明位置
        assert "boolean" in joined  # 类型错误说明

    def test_enabled_int_rejected(self, tmp_path):
        """① 数值 1 → 同样拒绝（非 bool）。"""
        data = _minimal_cfg()
        data["models"][0]["enabled"] = 1
        with pytest.raises(ConfigError) as e:
            load_config(_write(tmp_path, data))
        assert "models.0.enabled" in "; ".join(e.value.errors)

    def test_enabled_missing_defaults_true(self, tmp_path):
        """② 旧配置无 enabled 字段 → 正常加载且默认启用（向后兼容）。"""
        cfg = load_config(_write(tmp_path, _minimal_cfg()))  # 不写 enabled
        assert cfg.models[0].enabled is True

    def test_enabled_false_and_explicit_true_load(self, tmp_path):
        """显式 false / true 均可加载（YAML 布尔）。"""
        data = _minimal_cfg()
        data["models"][0]["enabled"] = False
        cfg = load_config(_write(tmp_path, data))
        assert cfg.models[0].enabled is False

        data["models"][0]["enabled"] = True
        cfg = load_config(_write(tmp_path, data))
        assert cfg.models[0].enabled is True

    def test_example_config_enabled_true(self):
        """样例配置显式 enabled: true 可正常加载（示例与 schema 同步）。"""
        cfg = load_config(EXAMPLE_CONFIG)
        assert all(m.enabled for m in cfg.models)


class TestModelParams:
    """Q24：models[].params 网关级参数默认（已知键范围校验 + 开放键放行）。"""

    def test_params_roundtrip(self, tmp_path):
        """官方默认参数写入后可完整读回。"""
        data = _minimal_cfg()
        data["models"][0]["params"] = {"temperature": 0.6, "top_p": 0.95, "max_tokens": 8192}
        cfg = load_config(_write(tmp_path, data))
        assert cfg.models[0].params == {"temperature": 0.6, "top_p": 0.95, "max_tokens": 8192}

    def test_temperature_out_of_range_rejected(self, tmp_path):
        data = _minimal_cfg()
        data["models"][0]["params"] = {"temperature": 99}
        with pytest.raises(ConfigError):
            load_config(_write(tmp_path, data))

    def test_max_tokens_invalid_rejected(self, tmp_path):
        data = _minimal_cfg()
        data["models"][0]["params"] = {"max_tokens": 0}
        with pytest.raises(ConfigError):
            load_config(_write(tmp_path, data))

    def test_unknown_key_allowed(self, tmp_path):
        """未知键放行（架构可扩展：将来放开自定义参数时后端零改）。"""
        data = _minimal_cfg()
        data["models"][0]["params"] = {"top_k": 40}
        cfg = load_config(_write(tmp_path, data))
        assert cfg.models[0].params == {"top_k": 40}


# ---------- v2.0 §14.2 阶段一：`Resource.product`（调研 09 D7）----------

def test_product_defaults_to_empty_for_old_configs(tmp_path):
    """🔴 向后兼容（§14.2 明文"默认空 = 旧行为"）：老配置里没有该字段也必须能加载。"""
    from model_gateway.config.schemas import AppConfig

    cfg = AppConfig.model_validate({
        "resources": [{"id": "r1", "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-1"}],
        "models": []})
    assert cfg.resources[0].product == ""


def test_product_round_trips_through_dump():
    """写盘（`PUT /admin/api/config` 用 `model_dump`）必须带上 product，否则重启即丢。"""
    from model_gateway.config.schemas import AppConfig

    cfg = AppConfig.model_validate({
        "resources": [{"id": "r1", "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-1",
                       "account": "acct-a", "product": "zcode", "account_ref": "acct-a"}],
        "models": []})
    dumped = cfg.model_dump(mode="json")
    assert dumped["resources"][0]["product"] == "zcode"
    assert dumped["resources"][0]["account_ref"] == "acct-a"      # M6-5a：写盘必须带上它
    assert AppConfig.model_validate(dumped).resources[0].product == "zcode"


def test_product_is_independent_from_account_and_preset():
    """三者语义不同，不得互相推断：preset=接入商 / account=备注 / product=账号体系归属。"""
    from model_gateway.config.schemas import AppConfig

    cfg = AppConfig.model_validate({
        "resources": [{"id": "r1", "preset": "sensenova-tokenplan", "account": "主号",
                       "product": "zcode", "account_ref": "zcode-acc-1",
                       "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-1"}],
        "models": []})
    r = cfg.resources[0]
    assert (r.preset, r.account, r.product) == ("sensenova-tokenplan", "主号", "zcode")
