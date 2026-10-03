"""INT · `/admin/api/config` 的映射条目必须带**同一个进池判据**（Q33-① 的界面出口）。

为什么要这一份：「网关模型管理」的资源池行与「N 个资源」计数此前直接读条目位
`resources[].enabled`，而 Q33 之后账号侧资源的真相是 **(产品, 厂商模型) 产品位 + 号开关**
（`AppConfig.mapping_enabled`，调度 / `/v1/models` / 映射弹窗都读它）。两处各判一次就是
两套真相：弹窗那颗开关说「已进池」，资源池表却说「没有这一行」。本文件钉三件事：

1. 出口把派生位 `mapping_enabled` 带上，且**账号侧以产品位为准**（条目位反过来也不受影响）；
2. 厂商侧维持条目位语义（零变化）；
3. 这个派生位是**只读视图**——把它原样 PUT 回去不会污染配置文件（Pydantic 忽略未知键）。
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from tests.integration.conftest import chat_res, gateway_config

TOKENS = {"access_tokens": [{"id": "t-user", "value": "gw-user"}]}
PRODUCT = "cline"


def _account_resource(cid: str = "res-acc") -> dict:
    """账号侧派生资源（§22.5-2：`product` + `account_ref` 必填、不落 Key；
    `access_mode` 仍是 `api` —— 派生资源与按量资源的区别在 `product`，不在接入形式）。"""
    return {"id": cid, "name": "账号资源", "access_mode": "api", "protocol": "openai",
            "base_url": "", "api_key": "", "product": PRODUCT, "account_ref": "acc-a",
            "enabled": True}


def _bit(model: str, system_model: str, enabled: bool) -> dict:
    return {"product": PRODUCT, "model": model, "system_model": system_model,
            "enabled": enabled}


@pytest.fixture
def cfg_factory(vendor):
    def make(*, entries: list[dict], bit: dict | None = None,
             extra_models: list[dict] | None = None) -> dict:
        cfg = gateway_config(vendor.port,
                             models=[{"name": "sys-a", "endpoint": "chat", "resources": entries}]
                                  + (extra_models or []),
                             gateway=TOKENS)
        cfg["resources"].append(_account_resource())
        if bit is not None:
            cfg["product_models"] = [bit]
        return cfg
    return make


async def _entries(client, gw, model_name: str = "sys-a") -> list[dict]:
    data = (await client.get(f"{gw.base_url}/admin/api/config")).json()
    m = next(x for x in data["models"] if x["name"] == model_name)
    return m["resources"]


class TestProviderSideStillEntryBit:
    """厂商侧（`product` 空）：派生位 == 条目位，语义零变化。"""

    async def test_open_and_closed_entries_report_their_own_bit(
            self, vendor, make_gateway, client, cfg_factory):
        gw = await make_gateway(cfg_factory(entries=[
            {"resource": "res-A", "model": "vm-A", "enabled": True},
            {"resource": "res-B", "model": "vm-B", "enabled": False},
        ]))
        entries = await _entries(client, gw)
        assert [e["mapping_enabled"] for e in entries] == [True, False]
        # 原字段照旧在位（界面别的处还读它，本改动只做加法）
        assert [e["enabled"] for e in entries] == [True, False]


class TestAccountSideFollowsProductBit:
    """账号侧：产品位是唯一真相，条目位与它相反时**以产品位为准**。"""

    async def test_bit_off_wins_over_an_open_entry(self, vendor, make_gateway, client,
                                                   cfg_factory):
        gw = await make_gateway(cfg_factory(
            entries=[{"resource": "res-acc", "model": "glm-5.3", "enabled": True}],
            bit=_bit("glm-5.3", "sys-a", False)))
        entries = await _entries(client, gw)
        assert entries[0]["enabled"] is True, "前置：条目位还开着（旧配置形态）"
        assert entries[0]["mapping_enabled"] is False, "产品位关 ⇒ 不进池，界面不得说有这一行"

    async def test_bit_on_wins_over_a_closed_entry(self, vendor, make_gateway, client,
                                                   cfg_factory):
        gw = await make_gateway(cfg_factory(
            entries=[{"resource": "res-acc", "model": "glm-5.3", "enabled": False}],
            bit=_bit("glm-5.3", "sys-a", True)))
        entries = await _entries(client, gw)
        assert entries[0]["enabled"] is False
        assert entries[0]["mapping_enabled"] is True

    async def test_bit_pointing_elsewhere_is_not_this_model(
            self, vendor, make_gateway, client, cfg_factory):
        """位指向别的系统模型（手改 YAML 的不一致形态）⇒ **只有位指的那个模型算进池**。

        同一 `(资源, 厂商模型)` 组合出现在两个系统模型下时，读侧只在**同一个模型内**去重
        （`schemas.py` 的组合唯一 = per-model），跨模型由写面拦；判据因此必须逐模型算，
        不能"有一条开着就算进池"。
        """
        gw = await make_gateway(cfg_factory(
            entries=[{"resource": "res-acc", "model": "glm-5.3", "enabled": True}],
            bit=_bit("glm-5.3", "sys-b", True),
            extra_models=[chat_res("", name="sys-b", resources=[
                {"resource": "res-acc", "model": "glm-5.3"}])]))
        a = await _entries(client, gw, "sys-a")
        b = await _entries(client, gw, "sys-b")
        assert a[0]["mapping_enabled"] is False, "位指 sys-b ⇒ sys-a 里这条不算进池"
        assert b[0]["mapping_enabled"] is True, "位指哪个模型，就只在哪个模型进池"

    async def test_no_bit_falls_back_to_entry_aggregation(
            self, vendor, make_gateway, client, cfg_factory):
        """旧配置零迁移：没有产品位时按条目位判（缺字段 ≠ 一律关）。"""
        gw = await make_gateway(cfg_factory(entries=[
            {"resource": "res-acc", "model": "glm-5.3", "enabled": True}]))
        entries = await _entries(client, gw)
        assert entries[0]["mapping_enabled"] is True


class TestDerivedBitIsReadOnly:
    """派生位是视图，不是配置：原样 PUT 回去既不 400 也不落进文件。"""

    async def test_put_roundtrip_drops_the_derived_key(self, vendor, make_gateway, client,
                                                       cfg_factory):
        gw = await make_gateway(cfg_factory(entries=[
            {"resource": "res-A", "model": "vm-A", "enabled": True}]))
        data = (await client.get(f"{gw.base_url}/admin/api/config")).json()
        assert data["models"][0]["resources"][0]["mapping_enabled"] is True
        sent = copy.deepcopy(data)
        resp = await client.put(f"{gw.base_url}/admin/api/config", json=sent)
        assert resp.status_code == 200, resp.text
        saved = yaml.safe_load(Path(gw.config_path).read_text(encoding="utf-8"))
        entry = saved["models"][0]["resources"][0]
        assert "mapping_enabled" not in entry, f"派生位漏进配置文件：{entry}"
        assert entry["enabled"] is True


class TestMergedSpecExitOnAdminView:
    """🔴 INT-95 · 债务 Q33-债14 的第一半：`/admin/api/config` 每条模型带只读派生位 `spec`。

    为什么要有这个出口：`specStale` 上一轮只落在 `/v1/models`（机器出口），管理界面里
    没有任何地方显示**网关承诺**这份合并规格 —— 「网关模型管理」属性卡画的是内置目录
    （官网取证），两者来源不同。于是"工具看到的窗口为什么是这个数 / 这个数是不是昨天的"
    在界面上无处可查，标注位等于只有出口没有出口。三条判据：
    ① 与 `/v1/models` **同一份数**（两个出口各算一份就是两套真相）；
    ② 陈旧 ⇒ `stale=true`，且数值照旧声明（标陈旧 ≠ 收回承诺）；
    ③ 只读视图：原样 PUT 回去不会把 `spec` 写进配置文件。
    """

    async def test_spec_matches_the_public_declaration(self, vendor, make_gateway, client,
                                                       cfg_factory):
        gw = await make_gateway(cfg_factory(entries=[
            {"resource": "res-A", "model": "glm-5.2", "enabled": True}]))
        data = (await client.get(f"{gw.base_url}/admin/api/config")).json()
        spec = next(x for x in data["models"] if x["name"] == "sys-a")["spec"]
        declared = next(x for x in (await client.get(
            f"{gw.base_url}/v1/models", headers={"Authorization": "Bearer gw-user"}
        )).json()["data"] if x["id"] == "sys-a")
        assert spec["max_input"] == declared["maxInputTokens"], (spec, declared)
        assert spec["max_output"] == declared["maxOutputTokens"], (spec, declared)
        assert spec["stale"] is False and spec["sources"] >= 1, spec

    async def test_stale_per_account_cache_is_marked_and_still_declares(
            self, vendor, make_gateway, client, cfg_factory):
        import json

        from model_gateway.accounts import catalog_cache, store
        from model_gateway.accounts.types import ModelInfo

        gw = await make_gateway(cfg_factory(
            entries=[{"resource": "res-acc", "model": "vm-x", "enabled": True}],
            bit=_bit("vm-x", "sys-a", True),
            extra_models=[]))
        catalog_cache.write_cache(PRODUCT, [ModelInfo(id="vm-x", context_window=200000,
                                                      max_output=8192)],
                                  source_account="acc-a")
        # 🔴 路径只经 `cache_path()` 现取（Q33-债12 那条红线的同一课）：按号副本的文件名是
        #    `_catalog_cache.<清洗名>-<sha1[:8]>.json`，照文档拼字符串或 glob 猜目录，
        #    就会出现"改了文件、读的还是另一份"这种假读数（本条第一次就是这么绿的）。
        root = store.product_root(PRODUCT).parent
        paths = [catalog_cache.cache_path(PRODUCT, account="acc-a", root=root),
                 catalog_cache.cache_path(PRODUCT, root=root)]
        pushed = 0
        for p in paths:
            if not p or not p.exists():
                continue
            d = json.loads(p.read_text(encoding="utf-8"))
            d["fetched_at"] -= catalog_cache.DEFAULT_TTL_SECONDS + 60
            p.write_text(json.dumps(d), encoding="utf-8")
            pushed += 1
        assert pushed, f"两份缓存都没找到 ⇒ 这条判据没有对象（glob/路径口径错了）：{paths}"
        assert (await client.post(f"{gw.base_url}/admin/api/config/reload")).status_code == 200

        spec = next(x for x in (await client.get(
            f"{gw.base_url}/admin/api/config")).json()["models"]
            if x["name"] == "sys-a")["spec"]
        assert spec["stale"] is True, spec
        assert (spec["max_output"], spec["max_input"]) == (8192, 200000), spec

    async def test_put_roundtrip_does_not_persist_the_view(self, vendor, make_gateway, client,
                                                           cfg_factory):
        gw = await make_gateway(cfg_factory(entries=[
            {"resource": "res-A", "model": "glm-5.2", "enabled": True}]))
        data = (await client.get(f"{gw.base_url}/admin/api/config")).json()
        assert all("spec" in m for m in data["models"]), "出口没带 spec"
        r = await client.put(f"{gw.base_url}/admin/api/config", json=data)
        assert r.status_code == 200, r.text
        raw = yaml.safe_load(Path(gw.config_path).read_text(encoding="utf-8"))
        assert all("spec" not in m for m in raw["models"]), raw["models"]
