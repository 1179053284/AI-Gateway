"""INT 管理端扩展（INT-46 预设端点 / INT-47 事件 provider-account 冗余与 stats 维度）。

通用前置：网关（随机端口）+ FakeVendor（随机端口）+ 接入密钥（Q18-① 管理端免鉴权：
不带任何凭据直访 /admin/api/*；接入密钥仅用于 /v1/*）。
"""

from __future__ import annotations

from tests.integration.conftest import chat_res, gateway_config
from tests.integration.fakevendor import Ok

# 接入密钥（/v1/* 鉴权用）；管理端免鉴权（Q18-①），无需 allow_admin 分级
TOKENS = {"access_tokens": [
    {"id": "t-user", "value": "gw-user"},
]}

EXPECTED_DIMENSIONS = ["by_model", "by_resource", "by_token", "by_provider", "by_account"]


class TestPresetsEndpoint:
    """INT-46：GET /admin/api/presets（PRD FR-1.2 / FR-10.2；Q18-① 管理端免鉴权）。"""

    async def test_int_46_admin_gets_three_presets(self, vendor, make_gateway, client):
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")],
                                               gateway=TOKENS))
        resp = await client.get(f"{gw.base_url}/admin/api/presets")
        assert resp.status_code == 200
        presets = resp.json()["presets"]
        assert len(presets) == 3
        assert {p["id"] for p in presets} == {"sensenova-api", "sensenova-tokenplan", "custom"}
        # 字段完整（id/名称/接入模式/协议/base_url/计费口径/说明）+ billing_display 展示值
        for p in presets:
            assert {"id", "name", "mode", "protocol", "base_url",
                    "billing", "notes", "billing_display"} <= set(p)
        custom = next(p for p in presets if p["id"] == "custom")
        assert custom["billing"] == ""        # 原始口径保留（空）
        assert custom["billing_display"] == "—"  # 空口径降级展示

    async def test_int_46_admin_api_without_token(self, vendor, make_gateway, client):
        """Q18-①：管理端免鉴权——无任何凭据直访预设端点（原 403 分级已移除）。"""
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")],
                                               gateway=TOKENS))
        for path in ("/admin/api/presets", "/admin/api/config", "/admin/api/status"):
            resp = await client.get(f"{gw.base_url}{path}")
            assert resp.status_code == 200, f"{path} 应免鉴权可访问"


class TestProviderAccountDimensions:
    """INT-47：事件行 provider/account 冗余 + stats by_provider/by_account（PRD FR-6.1/FR-7.7）。

    Q18-②：provider = 资源厂商口径（preset → 预设名；无 preset → 资源备注），
    account = 资源次要备注字段。
    """

    async def test_int_47_event_fields_and_stats_buckets(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="hello"))
        cfg = gateway_config(vendor.port, models=[chat_res("AB")], gateway=TOKENS)
        # 资源 A 挂厂商预设与账号备注（provider → 预设名「商汤按量 API」；account → acc1）
        cfg["resources"][0]["preset"] = "sensenova-api"
        cfg["resources"][0]["account"] = "acc1"
        gw = await make_gateway(cfg)
        # 发一个 chat 请求（承接资源 res-A/vm-A → provider 商汤按量 API / account acc1）
        resp = await client.post(
            f"{gw.base_url}/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer gw-user"})
        assert resp.status_code == 200

        # ① 事件 JSONL：行含 provider/account 且与配置归属一致
        await gw.drain_events()
        events = gw.read_events()
        assert len(events) == 1
        ev = events[0]
        assert ev["final_resource"] == "资源A/vm-A"
        assert ev["provider"] == "商汤按量 API"  # preset → 预设展示名（Q18-② 口径）
        assert ev["account"] == "acc1"

        # ② stats：by_provider / by_account 桶值正确 + dimensions 五维齐备
        resp = await client.get(f"{gw.base_url}/admin/api/stats?days=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["dimensions"] == EXPECTED_DIMENSIONS
        assert set(data["by_provider"]) == {"商汤按量 API"}
        assert data["by_provider"]["商汤按量 API"]["requests"] == 1
        assert data["by_provider"]["商汤按量 API"]["success"] == 1
        assert set(data["by_account"]) == {"acc1"}
        assert data["by_account"]["acc1"]["requests"] == 1
        assert data["by_account"]["acc1"]["success"] == 1

    async def test_int_47_provider_fallback_to_resource_name(self, vendor, make_gateway, client):
        """Q18-② 降级口径：无 preset 的资源 → provider = 资源备注（conftest 默认无 preset）。"""
        vendor.set("sk-A", Ok(content="hello"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")],
                                               gateway=TOKENS))
        resp = await client.post(
            f"{gw.base_url}/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer gw-user"})
        assert resp.status_code == 200
        await gw.drain_events()
        ev = gw.read_events()[0]
        assert ev["provider"] == "资源A"  # 无 preset → 资源备注名
        assert ev["account"] is None      # 无账号备注 → 事件行 account 为 None


class TestVendorCustomName:
    """INT-50：厂商名称自定义（Q20-①，resources[].vendor）。

    - vendor 自由输入；round-trip 保存不丢失；
    - 事件 provider / 统计 by_provider 优先取 vendor（压过 preset 预设展示名）。
    """

    async def test_int_50_vendor_custom_wins_over_preset(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="hello"))
        cfg = gateway_config(vendor.port, models=[chat_res("A")], gateway=TOKENS)
        cfg["resources"][0]["preset"] = "sensenova-api"  # 预设存在，但自定义厂商名应优先
        cfg["resources"][0]["vendor"] = "我的厂商"
        gw = await make_gateway(cfg)

        # ① 事件 provider = 自定义厂商名（压过预设「商汤按量 API」）
        resp = await client.post(
            f"{gw.base_url}/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer gw-user"})
        assert resp.status_code == 200
        await gw.drain_events()
        assert gw.read_events()[0]["provider"] == "我的厂商"

        # ② stats by_provider = 自定义厂商名
        data = (await client.get(f"{gw.base_url}/admin/api/stats?days=1")).json()
        assert set(data["by_provider"]) == {"我的厂商"}

    async def test_int_50_vendor_roundtrip_through_config(self, vendor, make_gateway, client):
        """PUT 保存 vendor 字段不丢失（前端表单落 resources[].vendor）。"""
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")],
                                               gateway=TOKENS))
        cfg = (await client.get(f"{gw.base_url}/admin/api/config")).json()
        cfg["resources"][0]["vendor"] = "自研厂商"
        resp = await client.put(f"{gw.base_url}/admin/api/config", json=cfg)
        assert resp.status_code == 200, resp.text
        data = (await client.get(f"{gw.base_url}/admin/api/config")).json()
        assert data["resources"][0]["vendor"] == "自研厂商"


class TestAdminConfigAutogen:
    """INT-48：PUT /admin/api/config 自动生成与脱敏还原（Q18-②/④）。

    - 新资源 id 空 → 服务端补齐 res-xxxxxxxx；
    - 新接入密钥 id/value 空 → 服务端补齐 tok-xxxxxxxx / mg-<32hex>；
    - 已存资源传回脱敏 Key 值 → 还原明文（未变更不损坏）。
    """

    async def test_int_48_autogen_resource_and_token(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="hello"))
        base = gateway_config(vendor.port, models=[chat_res("A")])
        gw = await make_gateway(base)

        # UI 形态的保存：新增资源（id 空）+ 新增密钥（id/value 空）+ 既有模型引用新资源
        cfg = (await client.get(f"{gw.base_url}/admin/api/config")).json()
        new_res = {"id": "", "name": "新资源", "preset": "sensenova-api",
                   "access_mode": "api", "protocol": "openai",
                   "base_url": f"http://127.0.0.1:{vendor.port}/v1",
                   "api_key": "sk-Z", "account": "accZ", "enabled": True}
        cfg["resources"].append(new_res)
        cfg["models"].append({"name": "new-model", "endpoint": "chat",
                              "resources": [{"resource": "", "model": "vm-Z"}]})
        cfg["gateway"]["access_tokens"].append({"id": "", "name": "Trae", "value": "",
                                                "enabled": True})
        # 模型引用在保存前无法指向未知 id → 先不带引用保存，服务端生成后再改
        cfg["models"].pop()

        resp = await client.put(f"{gw.base_url}/admin/api/config", json=cfg)
        assert resp.status_code == 200, resp.text

        # 保存后：资源 id / 密钥 id+value 均已生成（GET 默认脱敏 → 按备注名定位新资源）
        data = (await client.get(f"{gw.base_url}/admin/api/config")).json()
        z = next(r for r in data["resources"] if r["name"] == "新资源")
        assert z["id"].startswith("res-") and len(z["id"]) == len("res-") + 8
        tok = data["gateway"]["access_tokens"][-1]
        assert tok["name"] == "Trae"
        assert tok["id"].startswith("tok-")
        assert tok["value"].startswith("mg-") and len(tok["value"]) == 3 + 32

        # 生成的密钥立即可用于 /v1 鉴权（热重载已生效；test-model 路由至 res-A）
        resp = await client.post(
            f"{gw.base_url}/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {tok['value']}"})
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "hello"

    async def test_int_48_masked_key_roundtrip(self, vendor, make_gateway, client):
        """PUT 传回脱敏 Key → 还原明文；真实修改则按新值保存。"""
        vendor.set("sk-A", Ok(content="hello"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")],
                                               gateway=TOKENS))
        cfg = (await client.get(f"{gw.base_url}/admin/api/config")).json()
        masked = cfg["resources"][0]["api_key"]
        assert "****" in masked  # 前置：GET 默认脱敏

        # ① 原样传回（改备注不动 Key）→ 保存后明文保留（调用仍成功）
        cfg["resources"][0]["name"] = "资源A-改名"
        resp = await client.put(f"{gw.base_url}/admin/api/config", json=cfg)
        assert resp.status_code == 200
        data = (await client.get(f"{gw.base_url}/admin/api/config")).json()
        assert data["resources"][0]["name"] == "资源A-改名"
        assert data["resources"][0]["api_key"] == masked  # 仍是脱敏形态（未变更）
        resp = await client.post(
            f"{gw.base_url}/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer gw-user"})
        assert resp.status_code == 200  # 明文未被脱敏值覆盖

        # ② 显式改 Key → 按新值保存并生效
        cfg = (await client.get(f"{gw.base_url}/admin/api/config")).json()
        cfg["resources"][0]["api_key"] = "sk-NEW"
        resp = await client.put(f"{gw.base_url}/admin/api/config", json=cfg)
        assert resp.status_code == 200
        data = (await client.get(f"{gw.base_url}/admin/api/config")).json()
        assert data["resources"][0]["api_key"] != "sk-NEW"  # 保存后仍脱敏展示
        full = (await client.get(f"{gw.base_url}/admin/api/config?reveal=1")).json()
        assert full["resources"][0]["api_key"] == "sk-NEW"  # reveal 明文 = 新值
        vendor.set("sk-NEW", Ok(content="new-key-works"))
        resp = await client.post(
            f"{gw.base_url}/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer gw-user"})
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "new-key-works"

    async def test_int_49_placeholder_resource_ref(self, vendor, make_gateway, client):
        """INT-49：占位资源 id（@new-*）→ 生成真实 id 并改写模型映射引用（Q19-②）。

        资源弹窗内即配模型映射：新资源映射条目引用占位 id，保存时服务端
        统一解析为生成的 res-xxxxxxxx（一次 PUT 完成资源 + 映射落库）。
        """
        vendor.set("sk-A", Ok(content="hello"))
        vendor.set("sk-B", Ok(content="from-new-res"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")],
                                               gateway=TOKENS))

        # UI 形态的保存：新资源（占位 id）+ 新系统模型（映射引用占位 id）
        cfg = (await client.get(f"{gw.base_url}/admin/api/config")).json()
        cfg["resources"].append({"id": "@new-1", "name": "新资源", "preset": "sensenova-api",
                                 "access_mode": "api", "protocol": "openai",
                                 "base_url": f"http://127.0.0.1:{vendor.port}/v1",
                                 "api_key": "sk-B", "account": "", "enabled": True})
        cfg["models"].append({"name": "new-sys", "group": "通用", "endpoint": "chat",
                              "enabled": True,
                              "resources": [{"resource": "@new-1", "model": "vm-B",
                                             "reasoning": None}]})
        resp = await client.put(f"{gw.base_url}/admin/api/config", json=cfg)
        assert resp.status_code == 200, resp.text

        # 保存后：占位 id 已替换为真实 res- id，映射引用同步改写
        data = (await client.get(f"{gw.base_url}/admin/api/config")).json()
        z = next(r for r in data["resources"] if r["name"] == "新资源")
        assert z["id"].startswith("res-") and not z["id"].startswith("@")
        m = next(x for x in data["models"] if x["name"] == "new-sys")
        assert m["resources"][0]["resource"] == z["id"]
        assert m["resources"][0]["model"] == "vm-B"

        # 新映射即刻可调用（热重载生效；new-sys → 新资源/vm-B）
        resp = await client.post(
            f"{gw.base_url}/v1/chat/completions",
            json={"model": "new-sys", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer gw-user"})
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "from-new-res"
