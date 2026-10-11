"""INT 模型映射三端点（2026-10-01 增补）：产品目录 / 初始化映射 / 一键领取。

背景：管理端「模型映射」弹窗需要**产品级**目录（`GET …/{product}/catalog`）与批量
初始化映射（`POST …/mappings`）；「一键领取」（`POST …/claim-all`）把批量化签到收进
同一个账号面。三端点均按既有出口复用实现（§16.4 / §22.6 / §22.7）：

| # | 端点 | 判据 |
|---|---|---|
| 1 | `GET …/{product}/catalog` | 账号选源 / 空凭据兜底 / `suggest` 四级 + null / `mapped_to` / **10 产品兜底逐条** |
| 2 | `POST …/mappings` | 建模型 + 物化 + 追加 + 幂等 + **改挂 = 搬条目**（2026-10-05）+ 原落点不唯一 → skipped 且**零写盘** |
| 3 | `POST …/claim-all` | 产品过滤 / 能力位拒绝 / `details` 收集 / 全局腿按动作声明枚举 |

假钩子（产品契约表 `_HOOKS` 注入）与假上游（`accounts.net.make_client` → MockTransport）
双轨：**零真实网络** —— 兜底腿全覆盖（`net` 属性替换 + cline 的 import 期直接绑定
`make_client` 单独替换）；登录/账号数据经生产同一条落盘入口（`store.commit_login`）。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import httpx
import pytest
import yaml

from model_gateway.accounts import net as accounts_net
from model_gateway.accounts import registry as account_registry
from model_gateway.accounts import store
from model_gateway.accounts.types import ClaimOutcome, ModelInfo
from model_gateway.upstream.buddy import product as buddy
from model_gateway.upstream.cline import product as cline_product
from model_gateway.upstream.trae import product as trae
from tests.integration.conftest import chat_res, gateway_config

#: 全用例共用的"凭据不落 HTTP"探针值（出现在所有假凭据里，逐个响应对它断言）
SECRET = "SECRET-TOKEN-DO-NOT-LEAK-7a2e"

#: 接入密钥（管理端免鉴权，仅 gateway 段完整性所需）
TOKENS = {"access_tokens": [{"id": "t-user", "value": "gw-user"}]}

#: 枚举池内置条目的官方默认参数抽样（`BUILTIN_ENTRIES["glm-5.3"].params_default`，Q24）
GLM_PARAMS_DEFAULTS = {"temperature": 1.0, "top_p": 0.95, "do_sample": True,
                       "max_tokens": 65536}


@pytest.fixture
def offline_upstream(monkeypatch):
    """把所有产品的出站 HTTP 换成 MockTransport（一律 503）——测试期零真实网络。

    两个取用点都要替换（替换点由**导入形态**决定，不是随手多写一份）：
    - `accounts.net.make_client`：buddy/trae/raccoon/lobsterai(protocol)/qoder(flow) 等
      都经 `net.make_client(...)` **调用时**取属性 → 一处替换全生效；
    - `cline.product.make_client`：该模块 **import 期直接绑定**（`from … import make_client`），
      不随 net 模块的 monkeypatch 变化 —— 漏掉它，cline 的免认证 `recommended-models`
      探测就会打真实网络。
    """
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(503, json={"error": "offline-for-test"})

    calls: list[str] = []

    def fake_make_client(*, base_url: str = "", headers=None,
                         timeout=None, follow_redirects: bool = True):
        return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler),
                                 headers=headers or {}, timeout=timeout or 5.0,
                                 follow_redirects=follow_redirects)

    monkeypatch.setattr(accounts_net, "make_client", fake_make_client)
    monkeypatch.setattr(cline_product, "make_client", fake_make_client)
    return calls


def _cfg(port: int, *, models: list[dict] | None = None,
         extra_resources: list[dict] | None = None) -> dict:
    """最小网关配置（资源指向 FakeVendor；账号侧数据经 `store.product_root` 落在 tmp）。"""
    cfg = gateway_config(port, models=[chat_res("A")] if models is None else models,
                         gateway=TOKENS)
    cfg["resources"].extend(extra_resources or [])
    return cfg


def _seed(product: str, name: str, credentials: dict | None = None,
          meta: dict | None = None) -> None:
    """造一个账号（走生产同一条落盘入口 `store.commit_login`）。"""
    store.commit_login(product, name, credentials or {"access_token": SECRET}, meta or {})


def _saved(gw) -> dict:
    """读网关的**生效配置目录文件**（热重载的权威是文件，不是任何进程内快照）。"""
    return yaml.safe_load(Path(gw.config_path).read_text(encoding="utf-8"))


def _cat(gw, product: str) -> str:
    return f"{gw.base_url}/admin/api/accounts/{product}/catalog"


def _entry(body: dict, mid: str) -> dict:
    return next(m for m in body["models"] if m["id"] == mid)


# ============ 1. 产品级目录（catalog）============

class TestProductCatalog:
    async def test_account_source_suggest_levels_and_mapped_to(self, vendor, make_gateway,
                                                               client, monkeypatch):
        """账号选源 + `suggest` 四级（含 null）+ `mapped_to` + 账号列（resource_id）。

        假钩子返回五种形态的条目，逐条钉死 `_enum_suggest` 的取用规则：
        前缀剥段（sn-glm-5-3 → glm-5.3，0.7）/ 精确（1.0）/ 别名（0.9）/ 规范化（0.7）/ 无命中（null）。
        """
        gw = await make_gateway(_cfg(vendor.port, models=[{
            "name": "glm-5.3", "endpoint": "chat",
            "resources": [{"resource": "res-P1", "model": "sn-glm-5-3"}]}],
            extra_resources=[{
                "id": "res-P1", "name": "账号资源", "product": "buddy",
                "account_ref": "cat-1", "account": "cat-1", "protocol": "openai",
                "base_url": "http://127.0.0.1:9/v1", "api_key": ""}]))
        _seed("buddy", "cat-1", {"access_token": SECRET})
        seen: dict = {}

        async def fake(cred, meta):
            seen["cred"], seen["meta"] = cred, meta
            return [ModelInfo(id="sn-glm-5-3"),
                    ModelInfo(id="glm-5.3"),
                    ModelInfo(id="claude-sonnet-4-20250514"),
                    ModelInfo(id="GLM 5.3"),
                    ModelInfo(id="mystery-x")]

        monkeypatch.setitem(buddy._HOOKS, "list_models", fake)
        r = await client.get(_cat(gw, "buddy"))
        assert r.status_code == 200, r.text
        assert SECRET not in r.text
        body = r.json()

        assert body["product"] == "buddy" and body["title"] == "CodeBuddy"
        assert body["checkin"] is True
        assert body["source"] == {"kind": "account", "account": "cat-1",
                                  "detail": "来自账号 cat-1 的实时目录"}
        assert "reason" not in body
        # 账号实时目录：凭据只进钩子（进程内流转），绝不回传
        assert seen["cred"] == {"access_token": SECRET}
        assert seen["meta"]["account"] == "cat-1"
        assert str(Path(seen["meta"]["dir"]).name) == "cat-1"

        assert _entry(body, "sn-glm-5-3")["suggest"] == {
            "name": "glm-5.3", "confidence": 0.7, "via": "prefix"}
        assert _entry(body, "glm-5.3")["suggest"] == {
            "name": "glm-5.3", "confidence": 1.0, "via": "exact"}
        assert _entry(body, "claude-sonnet-4-20250514")["suggest"] == {
            "name": "claude-sonnet-4", "confidence": 0.9, "via": "alias"}
        assert _entry(body, "GLM 5.3")["suggest"] == {
            "name": "glm-5.3", "confidence": 0.7, "via": "normalized"}
        assert _entry(body, "mystery-x")["suggest"] is None

        # mapped_to：只有 (本产品资源, 条目 id) 组合已挂上的条目带出模型名
        assert _entry(body, "sn-glm-5-3")["mapped_to"] == ["glm-5.3"]
        assert _entry(body, "glm-5.3")["mapped_to"] == []
        assert _entry(body, "mystery-x")["mapped_to"] == []

        # 账号列：resource_id = 物化资源（本用例预置 res-P1）；条目键含 suggest/mapped_to
        assert body["accounts"] == [{"name": "cat-1", "enabled": True,
                                     "resource_id": "res-P1"}]
        assert {"suggest", "mapped_to"} <= set(_entry(body, "glm-5.3"))

    async def test_fallback_source_read_only_and_failure_modes(self, vendor, make_gateway,
                                                               client, monkeypatch):
        """兜底腿三连（一个用例三个相邻态 —— 合并不减断言）：

        (a) 启用账号返回空表 → **空凭据 `{}`** 兜底腿；停用账号只进 `accounts` 列、
            不参与选源；读端点**零写盘**；
        (b) 兜底钩子抛错 → **200 + 空 models + reason**（不编造条目，不 5xx；B-1 同口径）；
        (c) 未登记产品 → 400（§22.6「未登记 = 不支持」）。
        """
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "cat-empty", {"access_token": SECRET})
        _seed("buddy", "cat-off", {"access_token": SECRET}, {"enabled": False})
        before = Path(gw.config_path).read_bytes()
        calls: list[dict] = []

        async def fake(cred, meta):
            calls.append(dict(cred))
            return [ModelInfo(id="fb-1")] if not cred else []

        monkeypatch.setitem(buddy._HOOKS, "list_models", fake)
        r = await client.get(_cat(gw, "buddy"))
        assert r.status_code == 200, r.text
        body = r.json()
        # ——(a) ① 启用账号返回空表 → ② 空凭据兜底（两次调用，顺序可断言）——
        assert calls == [{"access_token": SECRET}, {}]
        assert body["source"] == {"kind": "fallback", "account": "",
                                  "detail": "内置兜底目录（无可用账号或远端目录不可用）"}
        assert [m["id"] for m in body["models"]] == ["fb-1"]
        assert _entry(body, "fb-1")["suggest"] is None
        assert body["accounts"] == [
            {"name": "cat-empty", "enabled": True, "resource_id": ""},   # 未物化 → 空串
            {"name": "cat-off", "enabled": False, "resource_id": ""}]
        assert Path(gw.config_path).read_bytes() == before, "读端点不得产生写盘副作用"

        # ——(b) 兜底腿也取不动 → 空表 + 原因（不编造）——
        async def boom(cred, meta):
            raise RuntimeError("目录端点未移植（假钩子）")

        monkeypatch.setitem(buddy._HOOKS, "list_models", boom)
        r = await client.get(_cat(gw, "buddy"))
        assert r.status_code == 200, r.text
        assert SECRET not in r.text
        body = r.json()
        assert body["source"]["kind"] == "fallback" and body["models"] == []
        assert body["reason"].startswith("RuntimeError") and "未移植" in body["reason"]

        # ——(c) 未登记产品 → 400（不落任何调用）——
        r = await client.get(f"{gw.base_url}/admin/api/accounts/codearts/catalog")
        assert r.status_code == 400
        assert "未登记的产品" in r.json()["error"]["message"]

    async def test_fallback_catalog_for_all_products_without_network(
            self, vendor, make_gateway, client, offline_upstream):
        """🔴 逐产品验证（任务书判据；Q44 起 11 个产品，遍历 PRODUCT_IDS 动态覆盖）：
        全部产品的 `list_models` 对**空凭据**都回非空内置
        目录、都不抛；且全程零真实网络（`offline_upstream` 把出站换成 MockTransport 503，
        远端腿按其自身纪律回退兜底表）。

        条目形态统一断言：每个模型都带 `suggest` / `mapped_to` 两把计算键。
        假上游**被真的用上**的证据：cline 的 `recommended-models`（免认证、无凭据也必打）
        出现在拦截记录里 —— 没有它，"没打网络"可能只是碰巧没打。
        """
        gw = await make_gateway(_cfg(vendor.port))
        for pid in account_registry.PRODUCT_IDS:
            r = await client.get(_cat(gw, pid))
            assert r.status_code == 200, (pid, r.text)
            body = r.json()
            assert body["source"]["kind"] == "fallback", (pid, body["source"])
            assert body["models"], f"{pid} 空凭据兜底目录为空（应回内置静态表）：{body}"
            assert body["accounts"] == []
            assert body["checkin"] is account_registry.get(pid).capabilities.checkin
            for m in body["models"]:
                assert {"id", "suggest", "mapped_to"} <= set(m), (pid, m)
        assert any("recommended-models" in url for url in offline_upstream), \
            f"假上游未被触发（cline 的免认证端点必打）—— 真实网络仍可能被放行：{offline_upstream}"


# ============ 2. 初始化映射（mappings）============

class TestMappings:
    async def test_create_model_append_and_idempotent(self, vendor, make_gateway, client):
        """建模型（枚举池条目，含官方默认参数）→ 物化账号资源 → 追加映射 → 保存 + 热重载；
        重发同载荷 → `added: 0`（幂等）。停用账号不参与、也不物化。"""
        gw = await make_gateway(_cfg(vendor.port, models=[]))
        _seed("buddy", "map-a", {"token": SECRET})
        _seed("buddy", "map-b", {"token": SECRET})
        _seed("buddy", "map-off", {"token": SECRET}, {"enabled": False})
        body = {"product": "buddy", "items": [{"model": "vm-x", "target": "glm-5.3"},
                                              {"model": "vm-y", "target": ""}]}

        r = await client.post(f"{gw.base_url}/admin/api/accounts/mappings", json=body)
        assert r.status_code == 200, r.text
        assert SECRET not in r.text
        first = r.json()
        assert first["created_models"] == ["glm-5.3"] and first["added"] == 2
        assert first["already"] == 0 and first["skipped"] == [] and first["reload"] is True
        assert [a["name"] for a in first["accounts"]] == ["map-a", "map-b"]
        assert all(a["enabled"] is True for a in first["accounts"])
        rids = {a["name"]: a["resource_id"] for a in first["accounts"]}
        assert all(rid.startswith("res-") for rid in rids.values())
        assert len(set(rids.values())) == 2

        saved = _saved(gw)
        model = next(m for m in saved["models"] if m["name"] == "glm-5.3")
        assert model["group"] == "编程" and model["endpoint"] == "chat"
        assert model["enabled"] is True
        # Q24：官方默认参数作网关初始值（枚举池 params_default 逐值）
        for k, v in GLM_PARAMS_DEFAULTS.items():
            assert model["params"][k] == v
        assert [(e["resource"], e["model"]) for e in model["resources"]] \
            == [(rids["map-a"], "vm-x"), (rids["map-b"], "vm-x")]
        # 物化行：product/account_ref/account 三写一致、api_key 空串、启用（§22.5-1/2）
        by_id = {r["id"]: r for r in saved["resources"]}
        for name, rid in rids.items():
            row = by_id[rid]
            assert (row["product"], row["account_ref"], row["account"]) == ("buddy", name, name)
            assert row["api_key"] == "" and row["enabled"] is True
        assert not any(r.get("account_ref") == "map-off" for r in saved["resources"]), \
            "停用账号不得被物化（运营跳过停用的同一判据）"
        # 热重载已生效：运行态配置看到新模型与新资源
        assert any(m.name == "glm-5.3" for m in gw.runtime.config.models)
        assert {rids["map-a"], rids["map-b"]} <= {r.id for r in gw.runtime.config.resources}

        # 幂等：同载荷重发 → added 0 / 全部 already / 不重复追加
        r2 = await client.post(f"{gw.base_url}/admin/api/accounts/mappings", json=body)
        assert r2.status_code == 200, r2.text
        again = r2.json()
        assert again["added"] == 0 and again["already"] == 2
        assert again["created_models"] == [] and again["skipped"] == []
        assert again["reload"] is True
        saved2 = _saved(gw)
        model2 = next(m for m in saved2["models"] if m["name"] == "glm-5.3")
        assert len(model2["resources"]) == 2, "重发把映射挂了第二遍（不去重）"

    async def test_repoint_moves_the_entry_instead_of_rejecting(self, vendor, make_gateway,
                                                                client):
        """2026-10-05 用户裁定「为什么要多保存这一步呢，好傻好蠢的设计」⇒ **改挂 = 一次动作**。

        本行**原来的落点**（产品位所指；无位时 = 那唯一一个持有该 `(资源 × 供应商模型名)` 组合的
        网关模型）不算冲突，算移动：条目本体整条搬到新目标下，产品位在同一次写盘里一起改指。
        旧契约把这条整条拒（`skipped` + 指路"先去「网关模型管理」页把该映射移除"），界面只能
        "先选「跳过」保存一次、再选新目标保存一次" —— 那一步多余保存的根因在**写面**，不在前端。
        🔴 "要么位和条目一起改，要么一个都不动"没有放宽：搬的是条目**本体**（推理默认住在这条上，
        删了重建会把它清空 —— 第八轮 B-1' 那条），且整行只 `save_config` 一次。
        """
        gw = await make_gateway(_cfg(vendor.port, models=[]))   # 起初没有任何网关模型
        _seed("buddy", "map-s2", {"access_token": SECRET})
        url = f"{gw.base_url}/admin/api/accounts/mappings"
        first = (await client.post(url, json={
            "product": "buddy", "items": [{"model": "vm-z", "target": "glm-5.3"}]})).json()
        assert first["added"] == 1 and first["moved"] == 0, first
        assert first["created_models"] == ["glm-5.3"]
        rid = first["accounts"][0]["resource_id"]

        # 条目级推理默认（界面在「网关模型管理」行内改的就是这一位）—— 移动必须带着它走
        cfg = yaml.safe_load(Path(gw.config_path).read_text(encoding="utf-8"))
        ref = next(e for m in cfg["models"] if m["name"] == "glm-5.3"
                   for e in m["resources"] if e["resource"] == rid)
        ref["reasoning"] = {"effort": "high"}
        Path(gw.config_path).write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
        assert (await client.post(f"{gw.base_url}/admin/api/config/reload")).status_code == 200

        out = (await client.post(url, json={
            "product": "buddy", "items": [{"model": "vm-z", "target": "kimi-k3"}]})).json()
        assert out["moved"] == 1, out
        assert out["added"] == 0 and out["already"] == 0 and out["skipped"] == []
        assert out["created_models"] == ["kimi-k3"]           # 目标模型按既有规则就地建
        assert out["product_models"] == [{"model": "vm-z", "target": "kimi-k3",
                                          "enabled": True}]   # 位一起改指新目标
        assert out["emptied_models"] == ["glm-5.3"]           # 旧模型一条不剩 ⇒ 会掉出 /v1/models
        saved = _saved(gw)
        moved_ref = next(m for m in saved["models"] if m["name"] == "kimi-k3")["resources"]
        assert [(e["resource"], e["model"], e["enabled"]) for e in moved_ref] == [
            (rid, "vm-z", True)]
        # 🔴 搬的是本体：条目级推理默认必须跟着走，不能被"删了重建"抹平
        assert (moved_ref[0]["reasoning"] or {}).get("effort") == "high", moved_ref
        assert next(m for m in saved["models"] if m["name"] == "glm-5.3")["resources"] == []
        ids = [m["id"] for m in (await client.get(
            f"{gw.base_url}/v1/models",
            headers={"Authorization": "Bearer gw-user"})).json()["data"]]
        assert "kimi-k3" in ids and "glm-5.3" not in ids      # 声明侧跟着这一次移动一起变

    async def test_ambiguous_landing_is_still_rejected_with_zero_write(self, vendor,
                                                                       make_gateway, client):
        """不变量的另一半必须仍可红：**原落点不唯一** ⇒ 写面不猜，整条拒、位不写、模型不建。

        形状 = 别名（同一 `(资源 × 供应商模型名)` 同时挂在两个网关模型下 —— 跨模型别名是既有
        设计，`schemas.py` 的唯一性校验只查**同一模型内**重复）且**没有产品位** ⇒ 界面那一行的
        "当前挂在哪"本身就有两个答案，搬哪一侧都是替用户做决定，且会把另一侧留成孤儿
        （这一行同时住两处 = 本写面自己宣布禁止的形状）。
        """
        gw = await make_gateway(_cfg(vendor.port, models=[
            {"name": "other", "endpoint": "chat",
             "resources": [{"resource": "res-Q", "model": "vm-z"}]},
            {"name": "other2", "endpoint": "chat",
             "resources": [{"resource": "res-Q", "model": "vm-z"}]}],
            extra_resources=[{
                "id": "res-Q", "name": "账号资源", "product": "buddy",
                "account_ref": "map-s3", "account": "map-s3", "protocol": "openai",
                "base_url": "http://127.0.0.1:9/v1", "api_key": ""}]))
        _seed("buddy", "map-s3", {"access_token": SECRET})

        out = (await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                                 json={"product": "buddy",
                                       "items": [{"model": "vm-z", "target": "kimi-k3"}]})).json()
        assert out["moved"] == 0 and out["added"] == 0, out
        assert out["product_models"] == [] and out["created_models"] == []
        assert len(out["skipped"]) == 2, out["skipped"]      # 两个持有模型各报一条原话
        assert {s["reason"].split("已挂在网关模型 ")[1].split("（")[0]
                for s in out["skipped"]} == {"other", "other2"}
        assert all("整体未生效" in s["reason"] for s in out["skipped"])
        saved = _saved(gw)
        assert "kimi-k3" not in {m["name"] for m in saved["models"]}
        assert saved.get("product_models") in (None, [])
        for name in ("other", "other2"):
            refs = next(m for m in saved["models"] if m["name"] == name)["resources"]
            assert [e["resource"] for e in refs] == ["res-Q"], (name, refs)

    async def test_refusals_leave_disk_untouched(self, vendor, make_gateway, client):
        """拒绝分支（未知产品 / 参数形态 / 目标不可追溯 / 无已启用账号）→ 400 可读原因，
        且**零写盘**（"先拒后动"：坏输入不得留下任何半成品）。"""
        gw = await make_gateway(_cfg(vendor.port, models=[]))
        before = Path(gw.config_path).read_bytes()
        cases = [
            ({"product": "codearts", "items": [{"model": "m", "target": "glm-5.3"}]},
             "未登记的产品"),
            ({"product": "buddy", "items": []}, "items"),
            ({"product": "buddy", "items": "nope"}, "items"),
            ({"product": "buddy", "items": [{"target": "glm-5.3"}]}, "model"),
            ({"product": "buddy", "items": ["not-a-dict"]}, "必须是对象"),
            ({"product": "buddy", "items": [{"model": "m", "target": 123}]}, "target"),
            ({"product": "buddy", "items": [{"model": "m", "target": "不存在-的名字"}]},
             "枚举池"),
            ({"product": "buddy", "items": [{"model": "m", "target": ""}]}, "target 为空"),
        ]
        for body, needle in cases:
            r = await client.post(f"{gw.base_url}/admin/api/accounts/mappings", json=body)
            assert r.status_code == 400, (body, r.text)
            assert needle in r.json()["error"]["message"], (body, r.json())
        assert Path(gw.config_path).read_bytes() == before

        # 目标合法但没有已启用账号 → 400（映射无处可落），且不物化、不写盘
        _seed("buddy", "map-off1", {"token": SECRET}, {"enabled": False})
        r = await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                              json={"product": "buddy",
                                    "items": [{"model": "m", "target": "glm-5.3"}]})
        assert r.status_code == 400
        assert "启用" in r.json()["error"]["message"]
        assert Path(gw.config_path).read_bytes() == before


# ============ 3. 一键领取（claim-all）============

class TestClaimAll:
    async def test_product_filter_details_and_report(self, vendor, make_gateway, client,
                                                     monkeypatch):
        """给定产品：名单 = 该产品账号（存储序）；停用 → skipped 且不发钩子；
        `details` 收齐四类里的实际返回；报告落 `ops-results-*.jsonl`（红点同源）。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "ca-1", {"token": SECRET})
        _seed("buddy", "ca-2", {"token": SECRET})
        _seed("buddy", "ca-f", {"token": SECRET})
        _seed("buddy", "ca-off", {"token": SECRET}, {"enabled": False})
        _seed("trae", "ca-9", {"access_token": SECRET})          # 别的产品：不得被发起
        box = {"category": "success", "detail": "已领取 +100"}
        calls: list[str] = []

        async def fake_claim(cred, meta, *, precheck):
            name = meta["account"]
            calls.append(name)
            if name == "ca-2":
                return ClaimOutcome(category="already_done", detail="今天已签到")
            if name == "ca-f":
                return ClaimOutcome(category="failed", detail="验证码失败（业务码 3007）")
            return ClaimOutcome(category=box["category"], detail=box["detail"])

        monkeypatch.setitem(buddy._HOOKS, "claim", fake_claim)
        r = await client.post(f"{gw.base_url}/admin/api/accounts/claim-all",
                              json={"product": "buddy"})
        assert r.status_code == 200, r.text
        assert SECRET not in r.text
        out = r.json()
        assert out["product"] == "buddy"
        assert out["participants"] == ["ca-1", "ca-2", "ca-f", "ca-off"]
        assert out["report"]["success"] == ["ca-1"]
        assert out["report"]["already_done"] == ["ca-2"]
        assert out["report"]["failed"] == [{"account": "ca-f",
                                            "reason": "验证码失败（业务码 3007）"}]
        assert out["report"]["skipped"] == ["ca-off"]            # 停用 = 运营跳过（§22.6）
        assert out["report"]["no_participants"] is False
        assert calls == ["ca-1", "ca-2", "ca-f"]                 # ca-off/ca-9 未发起
        assert out["details"] == {
            "ca-1": {"category": "success", "detail": "已领取 +100"},
            "ca-2": {"category": "already_done", "detail": "今天已签到"},
            "ca-f": {"category": "failed", "detail": "验证码失败（业务码 3007）"}}
        # 结果落盘（顶栏红点同源；不含凭据）
        day = dt.datetime.now().strftime("%Y%m%d")
        lines = (gw.usage_dir / f"ops-results-{day}.jsonl").read_text(encoding="utf-8")
        assert '"ca-f"' in lines and "验证码失败" in lines and SECRET not in lines
        assert out["written"] is True

    async def test_capability_refusal_and_zero_action(self, vendor, make_gateway, client,
                                                      monkeypatch):
        """能力位 checkin=False → 400 + 可读原因；**零发起、零落盘**（不谎报跑过）。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("raccoon", "rc-1", {"access_token": SECRET})
        called: list[str] = []

        async def spy(cred, meta, *, precheck):
            called.append(meta["account"])
            return ClaimOutcome(category="success", detail="不该发生")

        monkeypatch.setitem(buddy._HOOKS, "claim", spy)
        r = await client.post(f"{gw.base_url}/admin/api/accounts/claim-all",
                              json={"product": "raccoon"})
        assert r.status_code == 400, r.text
        assert "checkin=False" in r.json()["error"]["message"]
        assert "Raccoon" in r.json()["error"]["message"]
        # 未登记产品同样 400（§22.6「未登记 = 不支持」）
        r2 = await client.post(f"{gw.base_url}/admin/api/accounts/claim-all",
                               json={"product": "codearts"})
        assert r2.status_code == 400 and "未登记的产品" in r2.json()["error"]["message"]
        assert called == []
        day = dt.datetime.now().strftime("%Y%m%d")
        assert not (gw.usage_dir / f"ops-results-{day}.jsonl").exists(), \
            "被拒的一键领取不得落任何报告（否则顶栏红点会显示从未发生的动作）"

    async def test_global_leg_enumerates_by_operation_declaration(self, vendor, make_gateway,
                                                                  client, monkeypatch):
        """全局腿（`product` 缺省）：按动作声明枚举 —— checkin=True 的产品参战、
        checkin=False（workbuddy）**不进名单也不被误跑**。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "ga-1", {"token": SECRET})
        _seed("trae", "ga-2", {"access_token": SECRET})
        _seed("workbuddy", "ga-3", {"token": SECRET})
        seen: list[str] = []

        async def fake_claim(cred, meta, *, precheck):
            seen.append(meta["account"])
            return ClaimOutcome(category="success", detail="ok")

        monkeypatch.setitem(buddy._HOOKS, "claim", fake_claim)
        monkeypatch.setitem(trae._HOOKS, "claim", fake_claim)
        r = await client.post(f"{gw.base_url}/admin/api/accounts/claim-all", json={})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["product"] is None
        assert out["participants"] == ["ga-1", "ga-2"]           # PRODUCT_IDS 顺序枚举
        assert sorted(out["report"]["success"]) == ["ga-1", "ga-2"]
        assert set(out["details"]) == {"ga-1", "ga-2"}
        assert seen == ["ga-1", "ga-2"]                          # ga-3 一次都没打钩子
        assert out["written"] is True
