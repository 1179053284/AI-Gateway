"""UT-24：禁用模型解析拒绝（纯逻辑层，不触网、不建服务器）。

针对 openai_compat._resolve_model_or_404（chat / images 两端点共用的解析层）：
- ① 网关模型名直接命中 enabled=false → 404 + code=model_disabled
- ② 枚举池别名命中 disabled 模型（别名 → 网关模型 → enabled=false）→ 同样拒绝
- ③ enabled=true → 正常返回 model_def
- 与「未命中」（model_not_found + 候选建议）明确区分：不进入选路。

对应 test-cases UT-24 / PRD FR-2.3 / FR-5.6 / tech-design §4.2·§4.7。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from model_gateway.api.openai_compat import _resolve_model_or_404
from model_gateway.config.schemas import AppConfig
from model_gateway.enums.matcher import BUILTIN_ENTRIES, EnumPool


def _runtime(models: list[dict]) -> SimpleNamespace:
    """最小 runtime：解析层仅需 config.models + enum_pool。"""
    cfg = AppConfig.model_validate({"models": models})
    return SimpleNamespace(config=cfg, enum_pool=EnumPool(list(BUILTIN_ENTRIES)))


def _request(rt: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=rt)))


def _resolve(models: list[dict], name: str):
    model_def, err = _resolve_model_or_404(_request(_runtime(models)), name)
    return model_def, err


def _err_json(err) -> dict:
    assert err is not None
    return json.loads(err.body)


def _disabled_models() -> list[dict]:
    # deepseek-v4-flash 及其别名 deepseek-v4-flash-0731 均在内置枚举池登记
    return [{"name": "deepseek-v4-flash", "endpoint": "chat",
             "enabled": False, "resources": []}]


class TestDisabledModelRejection:
    """① 直名命中 / ② 别名命中 enabled=false → 404 model_disabled。"""

    def test_direct_name_disabled_rejected(self):
        model_def, err = _resolve(_disabled_models(), "deepseek-v4-flash")
        assert model_def is None
        assert err.status_code == 404
        e = _err_json(err)["error"]
        assert e["code"] == "model_disabled"
        assert "已禁用" in e["message"]
        assert "管理界面" in e["message"]
        assert e["type"] == "invalid_request_error"
        assert e["requested_model"] == "deepseek-v4-flash"

    def test_alias_hit_disabled_rejected(self):
        """别名 deepseek-v4-flash-0731 → 网关模型 deepseek-v4-flash（enabled=false）。"""
        model_def, err = _resolve(_disabled_models(), "deepseek-v4-flash-0731")
        assert model_def is None
        assert err.status_code == 404
        e = _err_json(err)["error"]
        assert e["code"] == "model_disabled"
        assert "已禁用" in e["message"]
        assert e["requested_model"] == "deepseek-v4-flash-0731"

    def test_disabled_takes_priority_over_not_found_semantics(self):
        """禁用拒绝与「未命中」明确区分：disabled 无候选建议（不是找不到，是被关了）。"""
        _, err_disabled = _resolve(_disabled_models(), "deepseek-v4-flash")
        assert _err_json(err_disabled)["error"]["code"] == "model_disabled"
        assert "candidates" not in _err_json(err_disabled)["error"]

        _, err_unknown = _resolve(_disabled_models(), "totally-unknown-model")
        unknown = _err_json(err_unknown)["error"]
        assert unknown["code"] == "model_not_found"
        assert "candidates" in unknown  # 未命中才给候选建议


class TestEnabledModelResolves:
    """③ enabled=true（含缺省默认）→ 正常返回 model_def。"""

    def test_enabled_true_resolves(self):
        models = [{"name": "deepseek-v4-flash", "endpoint": "chat",
                   "enabled": True, "resources": []}]
        model_def, err = _resolve(models, "deepseek-v4-flash")
        assert err is None
        assert model_def is not None and model_def.name == "deepseek-v4-flash"

    def test_enabled_default_true_when_missing(self):
        """旧配置缺省 enabled 字段 → 默认启用，解析正常（向后兼容）。"""
        models = [{"name": "deepseek-v4-flash", "endpoint": "chat", "resources": []}]
        model_def, err = _resolve(models, "deepseek-v4-flash-0731")
        assert err is None
        assert model_def is not None and model_def.name == "deepseek-v4-flash"


class TestResourceDisabledSwitch:
    """UT-29：资源开关 resources[].enabled（Q18-② 扁平资源；resources.py 聚合语义）。

    - ① 资源 enabled=false → 退出调度（available()=False，选路 None）
    - ② 热重载重新启用 → 资源恢复可用（rebuild 刷新 enabled）
    - ③ 资源缺省 enabled → 默认启用（向后兼容）
    """

    def test_resource_disabled_removes_from_scheduling(self):
        from tests.unit.conftest import FakeAdapter, build_runtime, chat_model, make_config

        cfg = make_config(models=[chat_model("m", keys="AB")], resources=[{
            "id": "res-A", "name": "资源A", "access_mode": "api", "protocol": "openai",
            "base_url": "http://fake.local/v1", "api_key": "sk-A", "enabled": False,
        }, {
            "id": "res-B", "name": "资源B", "access_mode": "api", "protocol": "openai",
            "base_url": "http://fake.local/v1", "api_key": "sk-B", "enabled": False,
        }])
        rt = build_runtime(cfg, FakeAdapter())
        assert rt.resources.pick_and_acquire("m", set()) is None  # 全部资源不可用

    def test_resource_reenabled_after_reload(self):
        from tests.unit.conftest import FakeAdapter, build_runtime, chat_model, make_config
        from model_gateway.config.schemas import AppConfig

        base = make_config(models=[chat_model("m", keys="A")])
        rt = build_runtime(base, FakeAdapter())
        assert rt.resources.pick_and_acquire("m", set()) is not None

        cfg2 = AppConfig.model_validate({**base, "resources": [
            {**base["resources"][0], "enabled": False}]})
        rt.resources.rebuild(cfg2)
        assert rt.resources.pick_and_acquire("m", set()) is None

        cfg3 = AppConfig.model_validate({**base, "resources": [
            {**base["resources"][0], "enabled": True}]})
        rt.resources.rebuild(cfg3)
        picked = rt.resources.pick_and_acquire("m", set())
        assert picked is not None and picked.resource_id == ("res-A", "vm-A")

    def test_resource_enabled_strict_bool(self):
        from model_gateway.config.schemas import AppConfig
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AppConfig.model_validate({"resources": [{
                "id": "res-1", "api_key": "sk", "enabled": "yes"}]})
