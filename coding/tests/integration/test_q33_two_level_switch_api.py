"""INT Q33 · 两级开关的端到端契约（产品位 × 号位 × 号启用时自动继承）。

与 `test_q33_routing.py`（纯内存判据）的分工：这里验**写面与落盘**——
`POST /admin/api/accounts/mappings` 到底往配置里写了什么、号被启用时条目是否自动长出来、
`/v1/models` 与 catalog 回执是否如实。全部走生产入口（`store.commit_login` 落账号、
`mappings` 端点写映射），零真实网络（假上游一律 503，本文件不发起推理）。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

from model_gateway.accounts import net as accounts_net
from model_gateway.accounts import store
from model_gateway.upstream.cline import product as cline_product

SECRET = "SECRET-TOKEN-DO-NOT-LEAK-9c4f"
TOKENS = {"access_tokens": [{"id": "t-user", "value": "gw-user"}]}


@pytest.fixture(autouse=True)
def offline_upstream(monkeypatch):
    """假上游：任何出站请求一律 503（本文件只验配置与声明，不打流量）。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "offline-for-test"})

    def fake_make_client(*, base_url: str = "", headers=None, timeout=None,
                         follow_redirects: bool = True):
        return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler),
                                 headers=headers or {}, timeout=timeout or 5.0,
                                 follow_redirects=follow_redirects)

    monkeypatch.setattr(accounts_net, "make_client", fake_make_client)
    monkeypatch.setattr(cline_product, "make_client", fake_make_client)


def _cfg(port: int, *, models: list[dict]) -> dict:
    from tests.integration.conftest import gateway_config

    return gateway_config(port, models=models, gateway=TOKENS)


def _seed(product: str, name: str, *, enabled: bool = True) -> None:
    store.commit_login(product, name, {"access_token": SECRET},
                       {} if enabled else {"enabled": False})


def _saved(gw) -> dict:
    return yaml.safe_load(Path(gw.config_path).read_text(encoding="utf-8"))


def _enable_url(gw, product: str, name: str, verb: str) -> str:
    return f"{gw.base_url}/admin/api/accounts/{product}/{name}/{verb}"


class TestMappingsWriteProductBit:
    async def test_write_lands_bit_and_entries_together(self, vendor, make_gateway, client):
        """映射写入 = **产品位 + 条目扇出**两处一起落盘，且回执如实报出位。"""
        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "bit-a")
        _seed("buddy", "bit-b")
        r = await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                              json={"product": "buddy",
                                    "items": [{"model": "vm-x", "target": "glm-5.3"}]})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["product_models"] == [{"model": "vm-x", "target": "glm-5.3",
                                          "enabled": True}]
        saved = _saved(gw)
        bits = saved["product_models"]
        assert [b["product"] for b in bits] == ["buddy"]
        assert bits[0]["model"] == "vm-x" and bits[0]["system_model"] == "glm-5.3"
        assert bits[0]["enabled"] is True
        model = next(m for m in saved["models"] if m["name"] == "glm-5.3")
        assert sorted(e["model"] for e in model["resources"]) == ["vm-x", "vm-x"]
        assert len(model["resources"]) == 2                      # 两个启用号各一条

    async def test_bit_off_is_persisted_and_model_stops_being_declared(
            self, vendor, make_gateway, client):
        """关产品位 ⇒ 落盘 `enabled: false`，`/v1/models` 立刻不再声明这个模型。"""
        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "bit-off")
        url = f"{gw.base_url}/admin/api/accounts/mappings"
        await client.post(url, json={"product": "buddy",
                                     "items": [{"model": "vm-x", "target": "glm-5.3"}]})
        assert "glm-5.3" in [m["id"] for m in
                             (await client.get(f"{gw.base_url}/v1/models",
                                               headers={"Authorization": "Bearer gw-user"}
                                               )).json()["data"]]
        r = await client.post(url, json={"product": "buddy",
                                         "items": [{"model": "vm-x", "target": "glm-5.3",
                                                    "enabled": False}]})
        assert r.status_code == 200, r.text
        assert _saved(gw)["product_models"][0]["enabled"] is False
        ids = [m["id"] for m in (await client.get(
            f"{gw.base_url}/v1/models",
            headers={"Authorization": "Bearer gw-user"})).json()["data"]]
        assert "glm-5.3" not in ids

    async def test_catalog_reports_bit_not_entry_aggregation(self, vendor, make_gateway,
                                                             client, monkeypatch):
        """`catalog.map_enabled` 读**产品位**：位关着时，即便有条目开着也报 false。

        这条钉死"弹窗显示进池、实际不进池"那类两套真相的分叉。
        目录内容经假钩子给（`list_models`），与生产同一条取数路径，零真实网络。
        """
        from model_gateway.accounts.types import ModelInfo
        from model_gateway.upstream.buddy import product as buddy_product

        async def fake_models(cred, meta):
            return [ModelInfo(id="vm-x"), ModelInfo(id="vm-y")]

        monkeypatch.setitem(buddy_product._HOOKS, "list_models", fake_models)
        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "cat-bit")
        await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                          json={"product": "buddy",
                                "items": [{"model": "vm-x", "target": "glm-5.3"}]})
        # 模拟旧数据残留：产品位关，但条目位还开着（历史上这两把位是同一把）
        saved = _saved(gw)
        rids = [r["id"] for r in saved["resources"] if r.get("account_ref") == "cat-bit"]
        assert rids, saved["resources"]
        saved["product_models"][0]["enabled"] = False
        for m in saved["models"]:
            for e in m["resources"]:
                if e["resource"] in rids:
                    e["enabled"] = True
        Path(gw.config_path).write_text(yaml.safe_dump(saved, allow_unicode=True,
                                                       sort_keys=False), encoding="utf-8")
        assert await gw.runtime.reload_from_file()
        body = (await client.get(f"{gw.base_url}/admin/api/accounts/buddy/catalog")).json()
        entry = next((m for m in body["models"] if m["id"] == "vm-x"), None)
        assert entry is not None, body["models"]
        assert entry["map_enabled"] is False          # 真相 = 产品位，不是条目聚合
        assert entry["mapped_to"] == ["glm-5.3"]      # "挂过"与"在生效"仍然是两件事


class TestAccountEnableInheritsMappings:
    """号从停用变启用 ⇒ 按产品位自动继承映射条目（不需要用户回弹窗重点）。"""

    async def test_enable_creates_missing_entries(self, vendor, make_gateway, client):
        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "late-a")
        _seed("buddy", "late-b", enabled=False)          # 写映射时这个号是停的
        await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                          json={"product": "buddy",
                                "items": [{"model": "vm-x", "target": "glm-5.3"}]})
        assert len(_saved(gw)["models"][0]["resources"]) == 1     # 只有启用号拿到条目

        r = await client.post(_enable_url(gw, "buddy", "late-b", "enable"))
        assert r.status_code == 200, r.text
        entries = _saved(gw)["models"][0]["resources"]
        assert len(entries) == 2                                  # 启用后自动继承
        assert sorted(e["model"] for e in entries) == ["vm-x", "vm-x"]

    async def test_enabled_account_joins_the_pool(self, vendor, make_gateway, client):
        """继承完条目后，这个号必须真的**进池**（否则继承只是配置上的动作）。"""
        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "pool-a")
        _seed("buddy", "pool-b", enabled=False)
        await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                          json={"product": "buddy",
                                "items": [{"model": "vm-x", "target": "glm-5.3"}]})
        runtime = gw.runtime
        assert len(runtime.resources.pools["glm-5.3"]) == 1
        await client.post(_enable_url(gw, "buddy", "pool-b", "enable"))
        # 落盘是端点的事，进程内视图由 1s mtime 轮询追上；测试里显式重载，不把时序留给运气
        assert await runtime.reload_from_file()
        assert len(runtime.resources.pools["glm-5.3"]) == 2

    async def test_enable_backfills_entry_for_existing_resource(self, vendor, make_gateway,
                                                               client):
        """🔴 真正会漏的那一支：**资源早已存在、只是缺新模型的条目**（启用时必须回填）。

        场景是真实运营顺序：号先接入（资源已物化）→ 中途停用 → 期间产品又开了一个新模型
        （扇出只覆盖启用号，所以这个号没拿到条目）→ 后来把它重新启用。
        此时 `ensure_resource` 走的是**命中路径**（原样返回、按纪律 1 不碰任何东西），
        回填只能靠 `sync_product_models` —— 所以这条才是"继承"这一步的真判据：
        只验上一条（启用时顺带新建资源）会连 `_backfill_product_models` 的创建路径一起
        把变异蒙混过去（实测变异"掏空 sync_product_models"在上一条上仍然全绿 = 假绿）。
        """
        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "sync-a")
        _seed("buddy", "sync-b")
        url = f"{gw.base_url}/admin/api/accounts/mappings"
        # ① 第一个模型：两号都在线 ⇒ 都拿到条目，也都物化了资源
        r = await client.post(url, json={"product": "buddy",
                                         "items": [{"model": "vm-x", "target": "glm-5.3"}]})
        assert r.status_code == 200, r.text
        # ② 停掉 sync-b，期间产品再开第二个模型 ⇒ 扇出只落在 sync-a 上
        assert (await client.post(_enable_url(gw, "buddy", "sync-b", "disable"))).status_code == 200
        assert await gw.runtime.reload_from_file()
        r2 = await client.post(url, json={"product": "buddy",
                                          "items": [{"model": "vm-y", "target": "kimi-k3"}]})
        assert r2.status_code == 200, r2.text
        saved = _saved(gw)
        kimi = next(m for m in saved["models"] if m["name"] == "kimi-k3")
        rid_b = next(x["id"] for x in saved["resources"] if x.get("account_ref") == "sync-b")
        assert all(e["resource"] != rid_b for e in kimi["resources"])   # 停用号确实没拿到
        # ③ 重新启用 sync-b ⇒ 资源已存在（走命中路径），条目必须由产品位回填
        assert (await client.post(_enable_url(gw, "buddy", "sync-b", "enable"))).status_code == 200
        saved2 = _saved(gw)
        kimi2 = next(m for m in saved2["models"] if m["name"] == "kimi-k3")
        assert rid_b in [e["resource"] for e in kimi2["resources"]], \
            "重新启用的号没有继承产品位 ⇒ 它会永久进不了 kimi-k3 的池"
        assert await gw.runtime.reload_from_file()
        assert any(s.account == "sync-b" for s in gw.runtime.resources.pools["kimi-k3"])

    async def test_disable_account_takes_only_itself_out(self, vendor, make_gateway, client):
        """号位关 = 只这个号退出对外声明与调度，同产品其他号不受影响（正交轴）。"""
        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "solo-a")
        _seed("buddy", "solo-b")
        await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                          json={"product": "buddy",
                                "items": [{"model": "vm-x", "target": "glm-5.3"}]})
        r = await client.post(_enable_url(gw, "buddy", "solo-b", "disable"))
        assert r.status_code == 200, r.text
        runtime = gw.runtime
        assert await runtime.reload_from_file()
        state_b = next(s for s in runtime.resources.registry.values() if s.account == "solo-b")
        assert state_b.available() is False            # 这个号不再被选到
        assert "glm-5.3" in [m["id"] for m in (await client.get(
            f"{gw.base_url}/v1/models",
            headers={"Authorization": "Bearer gw-user"})).json()["data"]]   # 模型仍在对外


class TestNoHalfApplied:
    """🔴 产品位与条目必须"一起改或都不改"（Q33 评审 R1-① 判死的 P0）。"""

    async def test_repoint_conflict_leaves_bit_and_entries_untouched(self, vendor,
                                                                     make_gateway, client):
        """把已挂在 A 模型的映射改挂到 B 模型 ⇒ 整条拒绝，**位与条目一个字节都不动**。

        旧顺序是"先写位再扇出"，扇出发现冲突就跳过 ⇒ 位指向 B、条目还留在 A，
        于是 **A 模型静默掉出 `/v1/models`**、B 模型没有条目、而回执是 200。
        """
        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "atom-a")
        url = f"{gw.base_url}/admin/api/accounts/mappings"
        await client.post(url, json={"product": "buddy",
                                     "items": [{"model": "vm-x", "target": "glm-5.3"}]})
        before = _saved(gw)
        r = await client.post(url, json={"product": "buddy",
                                         "items": [{"model": "vm-x", "target": "kimi-k3"}]})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["product_models"] == []                       # 本条一位未写
        assert out["added"] == 0 and out["turned_on"] == 0
        assert len(out["skipped"]) == 1 and "整体未生效" in out["skipped"][0]["reason"]
        assert _saved(gw) == before                              # 配置逐字未动
        ids = [m["id"] for m in (await client.get(
            f"{gw.base_url}/v1/models",
            headers={"Authorization": "Bearer gw-user"})).json()["data"]]
        assert "glm-5.3" in ids and "kimi-k3" not in ids         # 旧模型没被搞掉


class TestCatalogCacheWriteThrough:
    """🔴 「缓存 TTL + 只有实时腿落盘」这条判据必须由测试钉住（R2-⑤：先前只有注释）。"""

    async def test_account_source_catalog_writes_cache_and_fallback_does_not(
            self, vendor, make_gateway, client, monkeypatch):
        from model_gateway.accounts import catalog_cache
        from model_gateway.accounts.types import ModelInfo
        from model_gateway.upstream.buddy import product as buddy_product

        root = store.product_root("buddy")
        cache_file = catalog_cache.cache_path("buddy", root=root.parent)

        async def fake_models(cred, meta):
            return [ModelInfo(id="vm-x", context_window=123456, max_output=4096)]

        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "cache-1")
        monkeypatch.setitem(buddy_product._HOOKS, "list_models", fake_models)
        assert not cache_file.exists()
        body = (await client.get(f"{gw.base_url}/admin/api/accounts/buddy/catalog")).json()
        assert body["source"]["kind"] == "account"
        assert cache_file.exists(), "实时目录取到了却没落缓存 ⇒ 规格层永远读不到来源"
        got = catalog_cache.read_cache("buddy", root=root.parent)
        assert got["stale"] is False and got["source_account"] == "cache-1"
        assert got["models"][0].context_window == 123456

        # 兜底腿（无凭据/无启用号）**不得**写缓存：内置静态表冒充"有来源"就是假数据
        cache_file.unlink()
        monkeypatch.setitem(buddy_product._HOOKS, "list_models",
                            lambda cred, meta: _boom(cred, meta))
        body2 = (await client.get(f"{gw.base_url}/admin/api/accounts/buddy/catalog")).json()
        assert body2["source"]["kind"] != "account"
        assert not cache_file.exists(), "兜底/失败腿把静态表写进了缓存 = 伪造来源"

        async def _boom(cred, meta):
            raise RuntimeError("upstream down")


    async def test_hook_returning_a_dirty_field_still_answers_200(self, vendor,
                                                                  make_gateway, client,
                                                                  monkeypatch):
        """🔴 INT-83 · 上游数据出格不得把读端点打成 500（复验轮 R4-⑤/E 的收口判据）。

        钩子回传 `Decimal` 的 `context_window` 时，缓存序列化的 `TypeError` 旧实现不捕
        ⇒ 用户这一次**明明取到了目录**却在界面上什么都看不见（500 无原因）。
        定版口径（§22.7 B-1 同尺）：**缓存是加速件，它挂了不得改动本次结果** ⇒
        200 + 目录照出 + `source.kind=account`，缓存不落盘（下次再试），并留 WARNING。
        """
        from decimal import Decimal

        from model_gateway.accounts import catalog_cache, store
        from model_gateway.accounts.types import ModelInfo
        from model_gateway.upstream.buddy import product as buddy_product

        async def dirty(cred, meta):
            return [ModelInfo(id="vm-dirty", context_window=Decimal("1000"))]

        root = store.product_root("buddy")
        cache_file = catalog_cache.cache_path("buddy", root=root.parent)
        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "dirty-1")
        monkeypatch.setitem(buddy_product._HOOKS, "list_models", dirty)
        assert not cache_file.exists()

        body = (await client.get(f"{gw.base_url}/admin/api/accounts/buddy/catalog")).json()
        assert body["source"]["kind"] == "account"
        assert [m["id"] for m in body["models"]] == ["vm-dirty"]
        assert not cache_file.exists(), "写缓存失败却把脏数据落盘 = 伪造来源"


class TestAccountSwitchIsInstantAndHonest:
    """号启停必须**即时**反映到运行态，且回执如实说有没有落地（R3 F-4：实测有 ≥3s 窗口）。"""

    async def test_disable_takes_effect_without_waiting_for_watcher(self, vendor,
                                                                   make_gateway, client):
        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "inst-a")
        _seed("buddy", "inst-b")
        await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                          json={"product": "buddy",
                                "items": [{"model": "vm-x", "target": "glm-5.3"}]})
        runtime = gw.runtime
        assert len(runtime.resources.pools["glm-5.3"]) == 2
        r = await client.post(_enable_url(gw, "buddy", "inst-b", "disable"))
        assert r.status_code == 200, r.text
        assert r.json()["reload"] is True                  # 即时生效，不等 mtime 轮询
        st = next(s for s in runtime.resources.registry.values() if s.account == "inst-b")
        assert st.available() is False
        seen = set()
        for _ in range(4):
            got = runtime.resources.pick_and_acquire("glm-5.3", set())
            assert got is not None and got.account != "inst-b"
            seen.add(got.account)
            runtime.resources.release(got)
        assert seen == {"inst-a"}


class TestSwitchCountersAndBanner:
    """🔴 复验轮 R4-③④：回执的开关计数与总览横幅这两条腿先前**零断言**
    （`turned_on/turned_off` 全仓只被断过一次 `== 0`；`config_warnings` 对
    `product_models` 没有任何用例）—— 把这两处改成常数 0 / 改回读条目位，
    过去没有任何一条判据会红。"""

    async def test_toggle_counts_are_the_entries_actually_flipped(self, vendor,
                                                                  make_gateway, client):
        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "cnt-1")
        url = f"{gw.base_url}/admin/api/accounts/mappings"
        body = {"product": "buddy", "items": [{"model": "vm-x", "target": "glm-5.3"}]}

        first = (await client.post(url, json=body)).json()
        assert (first["added"], first["turned_on"], first["turned_off"]) == (1, 0, 0)

        off = (await client.post(url, json={**body, "items": [
            {**body["items"][0], "enabled": False}]})).json()
        assert (off["added"], off["turned_on"], off["turned_off"]) == (0, 0, 1), off

        on = (await client.post(url, json=body)).json()
        assert (on["added"], on["turned_on"], on["turned_off"]) == (0, 1, 0), on

        again = (await client.post(url, json=body)).json()
        assert (again["already"], again["turned_on"], again["turned_off"]) == (1, 0, 0)

    async def test_banner_uses_the_same_predicate_as_routing(self, vendor, make_gateway, client):
        """位开 + 条目全关 ⇒ 模型**在池、在服务** ⇒ 横幅不得说它"没有任何生效映射"。

        反向对照（位关）⇒ 横幅必须报（这条腿此前恒真，因为它读的是条目位）。
        """
        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "ban-1")
        await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                          json={"product": "buddy",
                                "items": [{"model": "vm-x", "target": "glm-5.3"}]})
        runtime = gw.runtime
        kinds = [w["kind"] for w in runtime.config_warnings()]
        assert "model_without_resource" not in kinds              # 正常态：不指路

        # 条目全关（手改盘，模拟"用户只关了条目位"的旧形状）+ 产品位仍开 ⇒ 仍在服务
        cfg = runtime.config
        for m in cfg.models:
            for e in m.resources:
                e.enabled = False
        from model_gateway.core.resources import servable_models
        assert "glm-5.3" in servable_models(cfg, runtime.resources.registry)   # 判据 = 产品位
        kinds = [w["kind"] for w in runtime.config_warnings()]
        assert "model_without_resource" not in kinds, kinds

        # 位关 ⇒ 既不声明也要指路（两条读同一个判据，不许一条响一条哑）
        bit = cfg.product_mapping("buddy", "vm-x")
        bit.enabled = False
        assert "glm-5.3" not in servable_models(cfg, runtime.resources.registry)
        warnings = runtime.config_warnings()
        assert any(w["kind"] == "model_without_resource" for w in warnings), warnings


class TestDisabledAccountEntriesAreInScope:
    """🔴 INT-81 · 预检扫描面必须含**停用号**的旧条目（复验轮 R4 阻塞项 2）。

    形状：两个号都把 `vm-x` 挂在 A 上 → 停用其中一个（条目照旧留着）→ 把产品位改挂到 B。
    旧实现只扫启用号 ⇒ 预检放行、位改成 B、A 上那条仍挂着；等这个号被重新启用，
    `sync_product_models` 再按位补一条到 B ⇒ **同一 `(资源, 厂商模型)` 同时挂两个系统模型**，
    正是本写面自己宣布禁止的形状（`_mapping_holder` 的组合唯一判据），
    而且此后该组合再映射永远 `skipped`，提示还指向一个已经不再服务它的模型。
    """

    async def test_repoint_blocked_by_a_disabled_accounts_stale_entry(self, vendor,
                                                                      make_gateway, client):
        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "ds-1")
        _seed("buddy", "ds-2")
        url = f"{gw.base_url}/admin/api/accounts/mappings"
        first = (await client.post(url, json={"product": "buddy", "items": [
            {"model": "vm-x", "target": "glm-5.3"}]})).json()
        assert first["added"] == 2, first

        r = await client.post(_enable_url(gw, "buddy", "ds-2", "disable"))
        assert r.status_code == 200 and r.json()["changed"] is True

        out = (await client.post(url, json={"product": "buddy", "items": [
            {"model": "vm-x", "target": "kimi-k3"}]})).json()
        # 逐号一条说明（启用号 ds-1 + 停用号 ds-2 都仍挂在 glm-5.3 上）
        assert len(out["skipped"]) == 2, out["skipped"]
        assert out["product_models"] == []
        assert {s["reason"].split(" ")[1] for s in out["skipped"]} == {"ds-1", "ds-2"}
        assert out["created_models"] == []

        saved = _saved(gw)
        holders = {m["name"]: [e["resource"] for e in m["resources"] if e["model"] == "vm-x"]
                   for m in saved["models"]}
        assert holders.get("kimi-k3", []) == [], holders        # 没往新模型挂任何一条
        assert sorted(holders["glm-5.3"]) == sorted(
            {e["resource"] for e in next(m for m in saved["models"]
                                         if m["name"] == "glm-5.3")["resources"]
             if e["model"] == "vm-x"})                          # 旧挂载原样

        # 重新启用那个号 ⇒ 继承腿不得造出跨模型重复组合（判据 = 全配置唯一）
        r2 = await client.post(_enable_url(gw, "buddy", "ds-2", "enable"))
        assert r2.status_code == 200 and r2.json()["reload"] is True
        again = _saved(gw)
        seen: dict[tuple[str, str], int] = {}
        for m in again["models"]:
            for e in m["resources"]:
                seen[(e["resource"], e["model"])] = seen.get((e["resource"], e["model"]), 0) + 1
        dup = [k for k, v in seen.items() if v > 1]
        assert dup == [], f"同一 (资源, 厂商模型) 被挂到两个系统模型：{dup}"


class TestPerAccountEntitlementGate:
    """🔴 INT-85 · 判定式第四项「**该号目录确实有此模型**」接线（债务 Q33-债6-②）。

    旧形状：这一项只写在注释里当判定式的一部分，实现从不查目录 ⇒ 目录里没有这个模型的号
    照样拿到条目、照样进池，请求必然打出去吃上游错误（白烧额度 + 计入 y）。
    三条定版判据：
    ① 只认**这个号自己的**、**未过期**的目录缓存 —— 产品级那份代表不了单个号的权益；
    ② 闸门拦下时**逐号如实报进 `skipped`**，产品位与其余号照写照挂（这是逐号事实，不是整条冲突）；
    ③ 没取过 / 缓存过期 ⇒ **不知道 = 不拦**（照建条目），由调用期上游答复告诉我们 ——
       与 §12「消灭无报错的失败」同一条立意：静默否决比一次可见的 404 更坏。
    """

    async def test_fresh_account_catalog_without_the_model_gates_only_that_account(
            self, vendor, make_gateway, client):
        from model_gateway.accounts import catalog_cache, store
        from model_gateway.accounts.types import ModelInfo

        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "gate-a")
        _seed("buddy", "gate-b")
        # 只有 gate-a 号取到过自己的实时目录，且那份目录里**没有** vm-x
        catalog_cache.write_cache("buddy", [ModelInfo(id="vm-other")], source_account="gate-a")
        root = store.product_root("buddy").parent
        assert catalog_cache.cache_path("buddy", account="gate-a", root=root).exists()
        assert not catalog_cache.cache_path("buddy", account="gate-b", root=root).exists()

        out = (await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                                 json={"product": "buddy", "items": [
                                     {"model": "vm-x", "target": "glm-5.3"}]})).json()
        # ② 拦下的那一个如实报，且理由指到"刷新目录"
        assert len(out["skipped"]) == 1 and out["skipped"][0]["model"] == "vm-x"
        assert "gate-a" in out["skipped"][0]["reason"] and "刷新" in out["skipped"][0]["reason"]
        # 产品位照写、另一个号照挂（③ 没取过目录 = 不拦）
        assert out["product_models"] == [{"model": "vm-x", "target": "glm-5.3",
                                          "enabled": True}]
        assert out["added"] == 1
        saved = _saved(gw)
        model = next(m for m in saved["models"] if m["name"] == "glm-5.3")
        rids = {r["id"] for r in saved["resources"] if r.get("account_ref") == "gate-b"}
        assert {e["resource"] for e in model["resources"]} == rids
        assert rids and not ({e["resource"] for e in model["resources"]} & {
            r["id"] for r in saved["resources"] if r.get("account_ref") == "gate-a"})

    async def test_stale_account_catalog_is_not_a_rejection(self, vendor, make_gateway, client,
                                                            monkeypatch):
        """缓存超 TTL ⇒ 权益是天级变化的，陈旧值不足以否决 ⇒ 照建条目（③）。"""
        from model_gateway.accounts import catalog_cache
        from model_gateway.accounts.types import ModelInfo

        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "stale-1")
        catalog_cache.write_cache("buddy", [ModelInfo(id="vm-other")], source_account="stale-1")
        # 把这份按号缓存的 fetched_at 推到 TTL 之外（不改实现，只改数据）
        path = catalog_cache.cache_path("buddy", account="stale-1",
                                        root=catalog_cache.product_dir("buddy"))
        data = json.loads(path.read_text(encoding="utf-8"))
        data["fetched_at"] -= catalog_cache.DEFAULT_TTL_SECONDS + 60
        path.write_text(json.dumps(data), encoding="utf-8")

        out = (await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                                 json={"product": "buddy", "items": [
                                     {"model": "vm-x", "target": "glm-5.3"}]})).json()
        assert out["skipped"] == [] and out["added"] == 1, out

    async def test_enable_backfill_honours_the_same_gate(self, vendor, make_gateway, client):
        """号被启用时的继承腿共用**同一个**判据函数（`_backfill_product_models`），
        不在两处各写一份规则：闸门拦下 ⇒ 该号不进池，别的号不受影响。"""
        from model_gateway.accounts import catalog_cache
        from model_gateway.accounts.types import ModelInfo

        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "eb-1")
        _seed("buddy", "eb-2", enabled=False)
        catalog_cache.write_cache("buddy", [ModelInfo(id="vm-other")], source_account="eb-2")
        await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                          json={"product": "buddy", "items": [
                              {"model": "vm-x", "target": "glm-5.3"}]})
        r = await client.post(_enable_url(gw, "buddy", "eb-2", "enable"))
        assert r.status_code == 200 and r.json()["reload"] is True
        # 🔴 复验轮 R5-⑧：闸门在这条腿上原先**只写日志**，回执 200 + changed:true，
        #    用户看到"已启用"而映射一条没落地 = "看着已开、盘上没写"的假态。
        #    定版 = 启停两条腿同一键集，多出来的 `mapping_skipped` 必须如实带上被拦的模型名。
        assert r.json()["mapping_skipped"] == ["vm-x"], r.json()
        saved = _saved(gw)
        model = next(m for m in saved["models"] if m["name"] == "glm-5.3")
        eb2 = {x["id"] for x in saved["resources"] if x.get("account_ref") == "eb-2"}
        assert not (eb2 & {e["resource"] for e in model["resources"]}), \
            "启用继承腿绕过按号闸门建了条目"


class TestPerAccountSpecWiring:
    """🔴 INT-89 · 号级规格的**装配接线**（真机复验 R5-F-1 判死的阻塞项）。

    单元层 `resolve_entry` 一直是按**单条映射**算的，但生产装配 `main.py::_apply` 调
    `product_spec` 时不带 `account` ⇒ 账号侧唯一的来源是**产品级** `_catalog_cache.json`，
    于是 `Runtime.resource_specs[(rid, vm)]` 里同产品所有号共用一份数。真机后果三条：
    ① 上限 64 的号照样被派活（承载判据根本不看号）；
    ② 没有自己目录的号被打上别号的上限 ⇒ 真实上游 400；
    ③ 只有按号缓存时 `/v1/models` 一律 `null`（规格取到了却不声明）。

    分工（不冒充端到端）：**消费腿**（判据读 `resource_specs`）由 INT-84 钉住；
    本类钉的是这份表**按号成立** + 对外声明不再是 null —— 两段接起来才是"号级承载"。
    本文件的假上游对账号侧一律 503（不打流量），所以不在这里发起推理。
    """

    async def _map_two_accounts(self, vendor, make_gateway, client, *, cap_big, cap_small,
                                target: str = "glm-5.3"):
        """两个号各落一份**自己的**目录缓存（产品级那份删掉），然后映射进池。"""
        from model_gateway.accounts import catalog_cache
        from model_gateway.accounts.types import ModelInfo

        # 系统模型**预先存在**：映射写面不自动新建用户无法追溯的名字（400 口径），
        # 而这里要的正是一个**不在内置目录**里的名字 —— 否则枚举池那份数会顶掉账号侧的。
        gw = await make_gateway(_cfg(vendor.port, models=[
            {"name": target, "endpoint": "chat", "resources": []}]))
        _seed("buddy", "cap-big")
        _seed("buddy", "cap-small")
        catalog_cache.write_cache("buddy", [ModelInfo(id="vm-x", context_window=200000,
                                                      max_output=cap_big)],
                                  source_account="cap-big")
        catalog_cache.write_cache("buddy", [ModelInfo(id="vm-x", context_window=200000,
                                                      max_output=cap_small)],
                                  source_account="cap-small")
        # 🔴 只留按号证据：产品级那份是"最后一次刷新那个号"的目录，留着就分不清
        #    读到的究竟是哪一份 ⇒ 判据会假绿（R5-F-1 之所以能藏这么久也是这个原因）
        product_copy = catalog_cache.cache_path("buddy")
        if product_copy.exists():
            product_copy.unlink()

        r = await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                              json={"product": "buddy", "items": [
                                  {"model": "vm-x", "target": target}]})
        assert r.status_code == 200, (r.status_code, r.text)
        out = r.json()
        assert [b["target"] for b in out["product_models"]] == [target], out
        by_name = {a["name"]: a["resource_id"] for a in out["accounts"]}
        return gw, by_name

    async def test_resource_specs_are_per_account_after_a_real_reload(
            self, vendor, make_gateway, client):
        gw, by_name = await self._map_two_accounts(vendor, make_gateway, client,
                                                   cap_big=8192, cap_small=64)
        big, small = by_name["cap-big"], by_name["cap-small"]
        specs = gw.runtime.resource_specs
        assert specs[(big, "vm-x")].max_output == 8192, specs[(big, "vm-x")]
        assert specs[(small, "vm-x")].max_output == 64, specs[(small, "vm-x")]

    async def test_declaration_uses_the_per_account_caches_not_null(
            self, vendor, make_gateway, client):
        """③ 的反证：只有按号缓存时对外也必须出数，且出的是**池内最大**（固定最大标准）。

        系统模型名故意用**不在内置目录**里的 `cap-custom` —— 用 `glm-5.3` 会被枚举池
        那份 131072 顶掉（取大规则本身正确），测不到"账号侧一份数都没声明出来"这个形状。
        """
        from model_gateway.accounts import catalog_cache

        gw, _ = await self._map_two_accounts(vendor, make_gateway, client,
                                             cap_big=8192, cap_small=64, target="cap-custom")
        assert catalog_cache.read_cache("buddy") is None      # 前提：产品级那份确实不在场
        entry = next(m for m in (await client.get(
            f"{gw.base_url}/v1/models",
            headers={"Authorization": "Bearer gw-user"})).json()["data"]
            if m["id"] == "cap-custom")
        assert entry["maxOutputTokens"] == 8192, entry
        assert entry["maxInputTokens"] == 200000, entry

    async def test_the_small_account_is_the_one_the_capacity_rule_sees(
            self, vendor, make_gateway, client):
        """① 的接线判据：同一个请求，判据对**小上限那个号**给出拒绝理由、
        对大号给出 `None` —— 读的必须是号自己那份数，产品级那一份在这里帮不上忙。"""
        gw, by_name = await self._map_two_accounts(vendor, make_gateway, client,
                                                   cap_big=8192, cap_small=64)
        reg = gw.runtime.resources.registry
        big = reg[(by_name["cap-big"], "vm-x")]
        small = reg[(by_name["cap-small"], "vm-x")]

        class Ir:                        # 承载判据只看这三个字段
            endpoint = "chat"
            system_model = "glm-5.3"
            body = {"max_tokens": 2048}

        reject = gw.runtime.scheduler._capacity_reject
        reason = reject(Ir(), small)
        assert reason is not None
        assert reject(Ir(), big) is None
        # 🔴 评审 R8-报备 R-9：拦人的理由必须用界面上那把名字（`备注名/厂商模型`），
        #    掺裸 `res-xxxxxxxx` 会让用户在自己没起过的串里找资源
        # 🔴 收紧（评审 R9-报备 R9-2：先前两条断言其实是同一个串，写成 `rid/vm-x` 照样不红）
        assert "res-" not in reason, f"理由串里仍有裸资源 id：{reason}"
        assert "cap-small" in reason and "vm-x" in reason, reason

    async def test_another_system_model_switch_cannot_erase_this_resources_spec(
            self, vendor, make_gateway, client):
        """🔴 评审 R8-B-1：资源级规格**不得**带系统模型维度（别名形状会把它抹成空壳）。

        `(资源, 厂商模型)` 在**别的**系统模型下也被引用是既有设计（别名 + 运行态按
        `(rid, vendor_model)` 共享冷却，`schemas.py` 的去重明确只在同一系统模型内、
        UT-84 还专门留了反证腿），而 `Runtime.resource_specs` 的键就是 `(rid, vendor_model)`。
        值若由带映射判据的那条路算出来，另一头那条映射关着时空壳就**覆盖**生效那份 ⇒
        承载判据不再拦、缺省注入也不注（方向 = fail-open，真实上游 400），
        🔴 而且**红不红取决于配置里的书写顺序** ⇒ 两个顺序都必须验。
        """
        from model_gateway.accounts import catalog_cache
        from model_gateway.accounts.types import ModelInfo

        for alias_first in (False, True):        # 两个顺序都得活
            names = ["cap-custom", "cap-alias"] if not alias_first else ["cap-alias", "cap-custom"]
            gw = await make_gateway(_cfg(vendor.port, models=[
                {"name": n, "endpoint": "chat", "resources": []} for n in names]))
            _seed("buddy", "cap-alias")
            catalog_cache.write_cache("buddy", [ModelInfo(id="vm-x", context_window=200000,
                                                          max_output=8192)],
                                      source_account="cap-alias")
            catalog_cache.cache_path("buddy").unlink(missing_ok=True)   # 只留按号证据

            out = (await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                                     json={"product": "buddy", "items": [
                                         {"model": "vm-x", "target": "cap-custom"}]})).json()
            rid = {a["name"]: a["resource_id"] for a in out["accounts"]}["cap-alias"]
            assert gw.runtime.resource_specs[(rid, "vm-x")].max_output == 8192

            # 同一个 (号, 厂商模型) 组合另挂到第二个系统模型上，那一头**关着**
            saved = _saved(gw)
            other = next(m for m in saved["models"] if m["name"] == "cap-alias")
            other["resources"] = [{"resource": rid, "model": "vm-x", "enabled": False}]
            r = await client.put(f"{gw.base_url}/admin/api/config", json=saved)
            assert r.status_code == 200, r.text
            # 🔴 前提腿（评审 §1.1）：别名那条**必须真的落盘**，否则这条判据只验了"没写进去"
            landed = next(mm for mm in _saved(gw)["models"] if mm["name"] == "cap-alias")
            assert [x["resource"] for x in landed["resources"]] == [rid], landed
            assert landed["resources"][0].get("enabled") is False, landed
            spec = gw.runtime.resource_specs[(rid, "vm-x")]
            assert spec.max_output == 8192, (
                f"别名那头一个关着的开关把生效这头的按号规格抹成空壳（alias_first={alias_first}）：{spec}")

            class Ir:
                endpoint = "chat"
                system_model = "cap-custom"
                body = {"max_tokens": 2048}
            state = gw.runtime.resources.registry[(rid, "vm-x")]
            assert gw.runtime.scheduler._capacity_reject(Ir(), state) is None   # 8192 ≥ 2048


class TestStaleSpecHasAUserVisibleExit:
    """🔴 INT-93 · 陈旧规格必须有**对外可见**的标注位（债务 Q33-债8 第①条，用户批准的契约扩展）。

    `ModelSpec.from_stale_cache` 从 Q33 第一版起就算得出来，但**零消费方** ⇒ 界面上
    "昨天缓存里的数"与"刚刚实时取到的数"长得一模一样，用户以为看到的是当下事实。
    出口定在声明侧（`/v1/models` 每条模型一个只读位 `specStale`），三条缺一不可：
    ① 陈旧 ⇒ `true`，且数**照旧声明出来**（陈旧仍是可用的兜底来源，不许顺手改成 null）；
    ② 新鲜 ⇒ `false`（这一腿是①的反证：写成恒 `true` 或恒 `false` 都必须红）；
    ③ 前提自证 —— 读缓存函数自己说这份是陈旧的，不然整条判据是在测"我以为的数据"。
    """

    async def _map_with_freshness(self, vendor, make_gateway, client, *, stale: bool,
                                  target: str):
        from model_gateway.accounts import catalog_cache
        from model_gateway.accounts.types import ModelInfo

        gw = await make_gateway(_cfg(vendor.port, models=[
            {"name": target, "endpoint": "chat", "resources": []}]))
        _seed("buddy", "fresh-1")
        catalog_cache.write_cache("buddy", [ModelInfo(id="vm-x", context_window=200000,
                                                      max_output=8192)],
                                  source_account="fresh-1")
        catalog_cache.cache_path("buddy").unlink(missing_ok=True)   # 只留按号证据
        path = catalog_cache.cache_path("buddy", account="fresh-1",
                                        root=catalog_cache.product_dir("buddy"))
        if stale:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["fetched_at"] -= catalog_cache.DEFAULT_TTL_SECONDS + 60
            path.write_text(json.dumps(data), encoding="utf-8")
        view = catalog_cache.read_cache("buddy", account="fresh-1",
                                        root=catalog_cache.product_dir("buddy"))
        # ③ 前提自证：这次装配读到的究竟是哪一种，由读函数自己说
        assert view and view["stale"] is stale, view

        r = await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                              json={"product": "buddy", "items": [
                                  {"model": "vm-x", "target": target}]})
        assert r.status_code == 200, r.text
        assert r.json()["added"] == 1, r.json()
        entry = next(m for m in (await client.get(
            f"{gw.base_url}/v1/models",
            headers={"Authorization": "Bearer gw-user"})).json()["data"]
            if m["id"] == target)
        return entry

    async def test_stale_declares_true_and_keeps_the_numbers(self, vendor, make_gateway, client):
        entry = await self._map_with_freshness(vendor, make_gateway, client,
                                               stale=True, target="stale-custom")
        assert entry["specStale"] is True, entry
        # ① 的另半句：标注"陈旧"不等于"不声明"—— 离线时这是唯一可用的规格来源
        assert entry["maxOutputTokens"] == 8192 and entry["maxInputTokens"] == 200000, entry

    async def test_fresh_declares_false(self, vendor, make_gateway, client):
        entry = await self._map_with_freshness(vendor, make_gateway, client,
                                               stale=False, target="fresh-custom")
        assert entry["specStale"] is False, entry
        assert entry["maxOutputTokens"] == 8192, entry


class TestProductModelRemoval:
    """🔴 INT-94 · 产品位**删除入口**（用户批准的契约扩展第二条，台账 §17）。

    Q33-① 把 `(产品, 厂商模型) → 系统模型 + enabled` 定为账号侧映射的唯一真相，但界面上
    只有开/关两颗状态，**没有删除**：想"这个产品的这个模型我根本不想接"没有出口 ——
    关着的位永远留在配置里，而且号被重新启用时还会按它把条目**补回来**（继承腿读的就是位）。
    本类钉的是删除面必须成立的六件事，其中 ①② 是"删了但没删"的两种形状：
    只删位 ⇒ 条目失去主人、`mapping_enabled` 回落条目位 ⇒ 照进池；
    只删条目 ⇒ 位还开着 ⇒ 号一启用就被补回来。所以判据必须**同时**看配置里的位与条目。
    """

    async def _map(self, gw, client, *, product="buddy", model="vm-x", target="glm-5.3"):
        r = await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                              json={"product": product, "items": [{"model": model,
                                                                   "target": target}]})
        assert r.status_code == 200, r.text
        return r.json()

    async def _one_account_model(self, vendor, make_gateway, client, *, target="glm-5.3"):
        gw = await make_gateway(_cfg(vendor.port, models=[
            {"name": target, "endpoint": "chat", "resources": []}]))
        _seed("buddy", "rm-1")
        await self._map(gw, client, target=target)
        return gw

    async def test_bit_and_entries_are_removed_together(self, vendor, make_gateway, client):
        gw = await self._one_account_model(vendor, make_gateway, client)
        r = await client.post(f"{gw.base_url}/admin/api/accounts/product-models/remove",
                              json={"product": "buddy", "model": "vm-x"})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["bit_removed"] is True and out["entries_removed"] == 1, out
        assert out["emptied_models"] == ["glm-5.3"], out       # 该模型一条映射都不剩
        assert out["product_resources"] == 1, out              # 该产品派生资源数（如实报）
        saved = _saved(gw)
        assert saved.get("product_models") in (None, []), saved    # ① 位真没了
        model = next(m for m in saved["models"] if m["name"] == "glm-5.3")
        assert model["resources"] == [], model                 # ② 条目也真没了
        ids = [m["id"] for m in (await client.get(
            f"{gw.base_url}/v1/models",
            headers={"Authorization": "Bearer gw-user"})).json()["data"]]
        assert "glm-5.3" not in ids, ids                       # 掉出对外声明，不是只改了盘

    async def test_removal_is_idempotent_and_says_so(self, vendor, make_gateway, client):
        gw = await self._one_account_model(vendor, make_gateway, client)
        url = f"{gw.base_url}/admin/api/accounts/product-models/remove"
        first = (await client.post(url, json={"product": "buddy", "model": "vm-x"})).json()
        second = (await client.post(url, json={"product": "buddy", "model": "vm-x"}))
        assert second.status_code == 200, second.text            # 幂等 = 200，不是 404
        out = second.json()
        assert out["bit_removed"] is False and out["entries_removed"] == 0, out
        assert first["bit_removed"] is True, first               # 第一次确实删过东西

    async def test_other_products_and_vendor_entries_are_untouched(self, vendor, make_gateway,
                                                                  client):
        """🔴 删除的作用域 = **该产品的派生资源** × 这个厂商模型，别的二字不动。

        故意让**厂商侧**资源也挂一个同名厂商模型 `vm-x`：按"厂商模型"一把删就会把
        用户自己的按量 Key 映射一起清掉（那是另一类接入，与这个产品无关）。
        """
        gw = await make_gateway(_cfg(vendor.port, models=[
            {"name": "glm-5.3", "endpoint": "chat",
             "resources": [{"resource": "res-A", "model": "vm-x"}]}]))
        _seed("buddy", "scope-1")
        await self._map(gw, client)
        out = (await client.post(f"{gw.base_url}/admin/api/accounts/product-models/remove",
                                 json={"product": "buddy", "model": "vm-x"})).json()
        assert out["emptied_models"] == [], out                  # 厂商侧那条还在 ⇒ 模型不该被清空
        model = next(m for m in _saved(gw)["models"] if m["name"] == "glm-5.3")
        assert [e["resource"] for e in model["resources"]] == ["res-A"], model
        assert model["resources"][0]["model"] == "vm-x", model

    async def test_a_closed_bit_can_be_deleted_too(self, vendor, make_gateway, client):
        """需求动机本身：位**关着**时也只能开/关、删不掉 ⇒ 这一条就是那个缺失的出口。"""
        gw = await self._one_account_model(vendor, make_gateway, client)
        off = await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                                json={"product": "buddy", "items": [
                                    {"model": "vm-x", "target": "glm-5.3", "enabled": False}]})
        assert off.status_code == 200, off.text
        assert _saved(gw)["product_models"][0]["enabled"] is False   # 前提：现在是"关着的位"
        out = (await client.post(f"{gw.base_url}/admin/api/accounts/product-models/remove",
                                 json={"product": "buddy", "model": "vm-x"})).json()
        assert out["bit_removed"] is True, out
        assert _saved(gw).get("product_models") in (None, []), _saved(gw)

    async def test_no_enabled_account_is_not_a_blocker(self, vendor, make_gateway, client):
        """号全停了也要能删（写入面要求"至少一个启用号"是因为条目要有落点；删除不需要落点）。"""
        gw = await make_gateway(_cfg(vendor.port, models=[
            {"name": "glm-5.3", "endpoint": "chat", "resources": []}]))
        _seed("buddy", "off-1")
        await self._map(gw, client)
        r = await client.post(_enable_url(gw, "buddy", "off-1", "disable"))
        assert r.status_code == 200, r.text                        # 前提：真的停用了
        out = await client.post(f"{gw.base_url}/admin/api/accounts/product-models/remove",
                                json={"product": "buddy", "model": "vm-x"})
        assert out.status_code == 200, out.text
        assert out.json()["bit_removed"] is True, out.text

    async def test_bad_input_is_rejected_without_touching_the_disk(self, vendor, make_gateway,
                                                                   client):
        gw = await self._one_account_model(vendor, make_gateway, client)
        before = Path(gw.config_path).read_text(encoding="utf-8")
        url = f"{gw.base_url}/admin/api/accounts/product-models/remove"
        for body in ({"product": "buddy"}, {"product": "buddy", "model": "   "},
                     {"product": "not-registered", "model": "vm-x"}):
            r = await client.post(url, json=body)
            assert r.status_code == 400, (body, r.status_code, r.text)
        assert Path(gw.config_path).read_text(encoding="utf-8") == before   # 一次都没写
