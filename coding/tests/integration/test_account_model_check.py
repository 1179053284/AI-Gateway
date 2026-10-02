"""账号维度「模型检测」的数据面（2026-10-02 用户指令）。

覆盖两条判据：
1. `GET …/check-models` 的范围 = **该账号资源上 `enabled=true` 的映射**
   （映射级开关关掉的不测、别的账号的映射不测、资源停用不掩盖）；
2. `POST /admin/api/resources/test` 对 `product` 非空的资源**不再要求 Key**
   （§22.5-2：账号体系供给的资源 `api_key` 恒空、凭据由适配器自解 §22.3）——
   旧实现在这里对账号侧资源**永远**回「无可用出站适配器或 Key」（审计登记的死路径）。
"""

from __future__ import annotations

import pytest

from model_gateway.accounts import materialize, store
from model_gateway.config.loader import load_config, save_config
from model_gateway.config.schemas import ModelResource, SystemModel

from tests.integration.test_admin_accounts import TOKENS, _cfg, _seed  # 复用同一套夹具口径


pytestmark = pytest.mark.asyncio


async def test_check_models_lists_only_enabled_mappings_of_this_account(
        vendor, make_gateway, client, tmp_path):
    gw = await make_gateway(_cfg(vendor.port))
    _seed("buddy", "acc-check-1", {"token": "sekret-1"}, {"plan": "pro"})
    _seed("buddy", "acc-check-2", {"token": "sekret-2"}, {"plan": "pro"})
    rid1 = materialize.ensure_resource("buddy", "acc-check-1", config_path=gw.config_path)
    rid2 = materialize.ensure_resource("buddy", "acc-check-2", config_path=gw.config_path)

    cfg = load_config(gw.config_path)
    cfg.models.append(SystemModel(
        name="sys-a", endpoint="chat",
        resources=[
            ModelResource(resource=rid1, model="vm-on", enabled=True),
            ModelResource(resource=rid1, model="vm-off", enabled=False),   # 关掉的映射
            ModelResource(resource=rid2, model="vm-other-account"),         # 别的账号
        ]))
    save_config(cfg, gw.config_path)
    ok, errs = await gw.runtime.reload_from_file()
    assert ok, f"配置未生效：{errs}"

    resp = await client.get(f"{gw.base_url}/admin/api/accounts/buddy/acc-check-1/check-models")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert [m["vendor_model"] for m in data["models"]] == ["vm-on"], \
        "只出本账号**已开启**的映射（关掉的与别的账号都不进范围）"
    assert data["models"][0]["system_model"] == "sys-a"
    assert data["models"][0]["resource_id"] == rid1
    assert data["mapped_off"] == 1, "关闭态条数要如实报（界面据此说明「不在本次范围内」）"
    assert data["resource_enabled"] is True

    missing = await client.get(f"{gw.base_url}/admin/api/accounts/buddy/no-such/check-models")
    assert missing.status_code == 404, "账号不存在必须 404，不得回空清单装作「没有可测模型」"


async def test_resources_test_accepts_product_resource_without_api_key(
        vendor, make_gateway, client):
    """产品资源 `api_key` 恒空 ⇒ 旧守卫会把它判成「没 Key」，检测永远走不到出站。"""
    gw = await make_gateway(_cfg(vendor.port))
    _seed("buddy", "acc-test-1", {"token": "sekret"}, {"plan": "pro"})
    rid = materialize.ensure_resource("buddy", "acc-test-1", config_path=gw.config_path)
    cfg = load_config(gw.config_path)
    row = next(r for r in cfg.resources if r.id == rid)
    assert row.api_key == "", "§22.5-2：账号体系供给的资源不带 Key"
    save_config(cfg, gw.config_path)
    ok, errs = await gw.runtime.reload_from_file()
    assert ok, f"配置未生效：{errs}"

    resp = await client.post(f"{gw.base_url}/admin/api/resources/test",
                             json={"resource": rid, "model": "vm-x"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "无可用出站适配器或 Key" not in str(body), \
        "不得再用 Key 缺失挡掉账号侧资源（该文案现在只对按量 API 资源成立）"


async def test_account_switch_drives_derived_resource_bit(vendor, make_gateway, client):
    """「一个开关一个主人」（2026-10-02 裁决）：账号启停必须同步其派资源的启用位。

    分流后派生资源不再出现在「接入模型资源」页 ⇒ 资源位若不同步，就是
    "看不见、也永不复活"的隐藏停用位（删号置 false 后重新启用账号仍不可服务）。
    """
    gw = await make_gateway(_cfg(vendor.port))
    _seed("buddy", "acc-sw", {"token": "sekret"}, {"plan": "pro"})
    rid = materialize.ensure_resource("buddy", "acc-sw", config_path=gw.config_path)

    async def _switch(action: str) -> int:
        resp = await client.post(f"{gw.base_url}/admin/api/accounts/buddy/acc-sw/{action}")
        assert resp.status_code == 200, resp.text
        cfg = load_config(gw.config_path)
        row = next(r for r in cfg.resources if r.id == rid)
        return 1 if row.enabled else 0

    assert await _switch("disable") == 0, "停用账号后其资源仍启用（会继续被调度）"
    assert await _switch("enable") == 1, "启用账号后其资源仍停用（界面上已无处可拨回）"
    # 纪律 1 未被推翻：**登录/续期**仍不拨回用户手动停用（test_materialize.py 那条继续成立）
