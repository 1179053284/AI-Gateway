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
    """最小合法配置（含一个供应商资源 + 一个网关模型资源引用）。"""
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
        """资源 = 供应商 + Key：api_key 必填（空值拒绝）。

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
    """三者语义不同，不得互相推断：preset=供应商 / account=备注 / product=账号体系归属。"""
    from model_gateway.config.schemas import AppConfig

    cfg = AppConfig.model_validate({
        "resources": [{"id": "r1", "preset": "sensenova-tokenplan", "account": "主号",
                       "product": "zcode", "account_ref": "zcode-acc-1",
                       "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-1"}],
        "models": []})
    r = cfg.resources[0]
    assert (r.preset, r.account, r.product) == ("sensenova-tokenplan", "主号", "zcode")


class TestMaskedKeySentinel:
    """S-2（2026-10-05 架构审计）：GET 脱敏改显式哨兵 + PUT fail-closed 还原。

    旧形态 `sk-aa****1111` 是 `mask_key` 的不动点（`mask_key(掩码) == 掩码`）⇒ 另一页签
    拿旧快照拨开关会把掩码串逐字当新 Key 落盘、返回 ok —— 静默毁数据。哨兵形态与任何
    合法明文都不同形，还原只认哨兵。
    """

    def _body(self, api_key: str) -> dict:
        return {"resources": [{"id": "r1", "base_url": "http://127.0.0.1:9/v1",
                               "api_key": api_key}], "models": []}

    def test_sentinel_never_collides_with_plain_or_masked_form(self):
        from model_gateway.api.admin import _mask_key_sentinel
        from model_gateway.stats.events import mask_key

        for key in ("sk-aaaaaaaa1111", "short", "tok-value-xyz", "mg-abc"):
            s = _mask_key_sentinel(key)
            assert s.startswith("mgw-masked:")
            assert s != key and s != mask_key(key), "哨兵必须与明文/旧掩码都不同形"
            assert "mgw-masked:" not in key

    def test_unmask_restores_sentinel_and_keeps_user_input_literal(self):
        from model_gateway.api.admin import _mask_key_sentinel, _unmask_resources
        from model_gateway.config.schemas import AppConfig

        cur = AppConfig.model_validate(self._body("sk-aaaaaaaa1111"))
        body = self._body(_mask_key_sentinel("sk-aaaaaaaa1111"))   # 界面原样传回哨兵
        _unmask_resources(body, cur)
        assert body["resources"][0]["api_key"] == "sk-aaaaaaaa1111"  # 还原明文

        stale = self._body("sk-old-old-old-999")                   # 用户真改了 Key
        _unmask_resources(stale, cur)
        assert stale["resources"][0]["api_key"] == "sk-old-old-old-999"  # 按字面保存

    def test_legacy_masked_form_is_no_longer_a_restore_trigger(self):
        """🔴 关键回归：旧掩码形态 `sk-aa****1111` 现在**不再**被当成"没改过"——
        它会被逐字落盘吗？不会：它不属于哨兵，但它是用户在请求里**显式给出的值**；
        fail-closed 的含义是"网关不再猜"，防的是**网关自己生成**的 GET 形态被误存。
        这里钉的是：旧掩码传入时不会被还原成任何明文（认不出就按字面）。"""
        from model_gateway.api.admin import _unmask_resources
        from model_gateway.config.schemas import AppConfig

        cur = AppConfig.model_validate(self._body("sk-aaaaaaaa1111"))
        legacy = self._body("sk-****1111")
        _unmask_resources(legacy, cur)
        assert legacy["resources"][0]["api_key"] == "sk-****1111"  # 不猜 → 字面
        assert legacy["resources"][0]["api_key"] != "sk-aaaaaaaa1111"


class TestSchemaVersionAndForbid:
    """R7-K4 / S-4 后续（2026-10-06）：配置面两道保险——① 键名打错即报错（forbid），
    ② schema 版本位（拒绝半懂地读未来格式）。都钉「无报错的失败」这一形状的封口。"""

    def test_unknown_top_level_key_is_rejected(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text(yaml.safe_dump({"gatewy": {"host": "127.0.0.1"}}), encoding="utf-8")
        with pytest.raises(ConfigError) as ei:
            load_config(f)
        assert "gatewy" in str(ei.value.errors), ei.value.errors

    def test_unknown_nested_key_is_rejected(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text(yaml.safe_dump(
            {"gateway": {"host": "127.0.0.1", "quota_net_typo": False}}), encoding="utf-8")
        with pytest.raises(ConfigError) as ei:
            load_config(f)
        assert "quota_net_typo" in str(ei.value.errors), ei.value.errors

    def test_missing_version_defaults_to_1(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text(yaml.safe_dump({"gateway": {"host": "127.0.0.1"}}), encoding="utf-8")
        cfg = load_config(f)
        assert cfg.schema_version == 1

    def test_future_version_is_rejected_loudly(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text(yaml.safe_dump({"schema_version": 99}), encoding="utf-8")
        with pytest.raises(ConfigError) as ei:
            load_config(f)
        assert "99" in str(ei.value.errors), ei.value.errors

    def test_version_survives_save_roundtrip(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text(yaml.safe_dump({"schema_version": 1, "gateway": {"host": "127.0.0.1"}}),
                     encoding="utf-8")
        cfg = load_config(f)
        save_config(cfg, f)
        assert load_config(f).schema_version == 1


class TestConfigVersionOptimisticLock:
    """S-2 收尾（2026-10-06）：配置代次乐观锁——GET 带出 `version`，PUT 可选校验，
    不匹配 409 让界面重取。闭合 R1-F-5「多页签旧快照整份覆盖静默还原」的机器可判
    形态；不带 version 的旧客户端保持兼容零变化。"""

    def _runtime(self, tmp_path):
        import yaml

        from model_gateway.config.loader import load_config
        from model_gateway.main import Runtime

        f = tmp_path / "config.yaml"
        f.write_text(yaml.safe_dump({"gateway": {"host": "127.0.0.1"}}), encoding="utf-8")
        return Runtime(load_config(f), f, usage_dir=tmp_path / "usage"), f

    def test_version_increments_on_every_successful_apply(self, tmp_path):
        rt, _ = self._runtime(tmp_path)
        v0 = rt.config_version
        assert v0 == 1                       # 构造时 __init__ 置 0 + 首次 _apply 提交 ⇒ 1
        from model_gateway.config.loader import load_config

        rt._apply(load_config(rt.config_path))
        rt._apply(load_config(rt.config_path))
        assert rt.config_version == v0 + 2

    def test_extract_client_version_shapes(self):
        from model_gateway.api.admin import _extract_client_version

        body = {"version": 3, "gateway": {"host": "127.0.0.1"}}
        assert _extract_client_version(body) == 3
        assert "version" not in body                     # 取走即剥（forbid 配套）
        assert _extract_client_version({}) is None       # 旧客户端 → 不校验
        body2 = {"version": "3"}
        assert _extract_client_version(body2) == -1      # 非法形状 → 必不匹配
        body3 = {"version": True}
        assert _extract_client_version(body3) == -1      # bool 排除
        body4 = {"version": -5}
        assert _extract_client_version(body4) == -1

    def test_reload_books_mtime_shared_with_poller(self, tmp_path):
        """双计次修复（2026-10-09）：reload 吃进的 mtime 必须记账进
        `Runtime._seen_config_mtime` —— mtime 轮询与 reload 共用这本账。

        坏形态（资源池排序轮真机实拍）：界面 PUT 成功 → 管理端 reload（version+1）
        → 1s 轮询看到 mtime 变化**再** reload（version+1）→ 界面刚重取的快照过期，
        连续第二次保存必撞 409 乐观锁（置顶/置底/拖拽这类高频连点全被拒）。
        """
        import asyncio

        rt, f = self._runtime(tmp_path)
        from model_gateway.config.loader import load_config

        before = rt.config_version
        ok, errors = asyncio.run(rt.reload_from_file())
        assert ok, errors
        assert rt.config_version == before + 1           # reload 本体 +1（这一条不变）
        assert rt._seen_config_mtime == f.stat().st_mtime  # 但 mtime 已被当场记账
        # 轮询口径：同一 mtime 不再触发二次重载（生产在 _mtime_watcher 里读这本账）
        assert rt._seen_config_mtime == f.stat().st_mtime

    def test_mtime_watcher_skips_reload_already_seen(self, tmp_path):
        """轮询循环真的按共享账本跳过自己写盘引发的 mtime（B-1 兜底路径不覆盖本判据）。"""
        import asyncio
        import contextlib
        import unittest.mock as mock

        from model_gateway.config.loader import load_config
        from model_gateway.main import Runtime, _reload_watcher

        f = tmp_path / "config.yaml"
        f.write_text(yaml.safe_dump({"gateway": {"host": "127.0.0.1"}}), encoding="utf-8")
        rt = Runtime(load_config(f), f, usage_dir=tmp_path / "usage")

        class _App:
            state = type("S", (), {})()

        app = _App()
        app.state.runtime = rt

        reloads = {"n": 0}
        real_reload = rt.reload_from_file

        async def counting_reload():
            reloads["n"] += 1
            return await real_reload()

        rt.reload_from_file = counting_reload

        async def drive(n_rounds: int, mutate_at: int | None = None) -> None:
            """跑 n 轮 watcher：sleep 换成计数哨兵，第 n 轮结束退出。

            `mutate_at` = 第几轮 sleep 后改写配置文件 —— 模拟"外部改动发生在
            两次轮询之间"（watcher 的 initialized 只在第一轮记账，改动放启动前
            会被首轮直接吃进，测不到触发路径）。"""

            class _Stop(Exception):
                pass

            count = {"n": 0}

            async def fast_sleep(_s):
                count["n"] += 1
                if mutate_at and count["n"] == mutate_at:
                    # 🔴 safe_dump 带 encoding 参数 = 返回 bytes（PyYAML 语义），
                    #   不带才是 str —— 这里要 str。
                    dump = yaml.safe_dump(
                        {"gateway": {"host": f"0.0.0.{count['n']}.{count['n'] + 1}"}})
                    f.write_text(dump, encoding="utf-8")
                if count["n"] >= n_rounds:
                    raise _Stop

            with mock.patch("asyncio.sleep", fast_sleep):
                with contextlib.suppress(_Stop):
                    await _reload_watcher(app)

        # ① 首轮记账后、轮询间隙里外部改动文件 ⇒ 必须重载恰好一次（重载已把新 mtime 记账）
        asyncio.run(drive(4, mutate_at=2))
        assert reloads["n"] == 1, f"外部改动应触发 1 次重载，实际 {reloads['n']}"
        # ② 账本已记同一 mtime（含重载自己写盘被当场记账的情形）⇒ 零重载
        rt._seen_config_mtime = f.stat().st_mtime
        asyncio.run(drive(3))
        assert reloads["n"] == 1, f"已见 mtime 不得再重载，实际 {reloads['n']}"
