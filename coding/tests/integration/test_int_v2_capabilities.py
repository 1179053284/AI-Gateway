"""v2.0 §12 / §19 M3-1·M3-2·M3-4 / §21 集成测试。

覆盖：
- `/v1/models` 能力位 8 字段（原有 6 字段不删不改）
- `caps.thinkingLevelMap` **7 键齐全**、不支持档为 `null`
- 入站 `model` **前缀剥离**（`custom:` / `custom-local:`，PRD Q25-⑦）
- `/admin/api/overview` 的 **`warnings[]`** 两类告警（PRD Q25-⑧ / §21）
"""

from __future__ import annotations

import json

import httpx
import pytest
import yaml

from tests.integration.conftest import chat_res, gateway_config

pytestmark = pytest.mark.asyncio

LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"]


async def _models(gw) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{gw.base_url}/v1/models")
    assert r.status_code == 200
    return r.json()["data"]


# ---------- 能力位下发（§12.2 / M3-2）----------

async def test_models_keeps_original_six_fields(make_gateway):
    """🔴 原有 6 字段**不删不改**（向后兼容）。"""
    gw = await make_gateway(gateway_config(1, models=[chat_res("AB")]))
    try:
        m = (await _models(gw))[0]
        for k in ("id", "object", "created", "owned_by", "endpoint", "group"):
            assert k in m, f"原有字段 {k} 丢失"
        assert m["object"] == "model" and m["owned_by"] == "model-gateway"
    finally:
        await gw.stop()


async def test_models_adds_seven_capability_fields(make_gateway):
    """追加 7 个能力位字段（§12.2 映射表）。"""
    gw = await make_gateway(gateway_config(1, models=[chat_res("AB", name="glm-5.2")]))
    try:
        m = (await _models(gw))[0]
        for k in ("name", "vendor", "maxInputTokens", "maxOutputTokens",
                  "supportsToolCall", "supportsImages", "supportsReasoning"):
            assert k in m, f"能力位字段 {k} 缺失"
    finally:
        await gw.stop()


async def test_supports_tool_call_is_true_for_builtin_model(make_gateway):
    """🔴 `supportsToolCall` 必须为 true —— 否则工具侧会**删掉请求中的 tools**（静默降级）。"""
    gw = await make_gateway(gateway_config(1, models=[chat_res("AB", name="glm-5.2")]))
    try:
        m = (await _models(gw))[0]
        assert m["supportsToolCall"] is True
    finally:
        await gw.stop()


async def test_capability_values_come_from_builtin_directory(make_gateway):
    """能力位取自内置目录（非手填）。"""
    gw = await make_gateway(gateway_config(1, models=[chat_res("AB", name="glm-5.2")]))
    try:
        m = (await _models(gw))[0]
        assert m["name"] == "GLM-5.2"
        assert m["vendor"] == "智谱 GLM"
        assert m["maxInputTokens"] == 1048576
        assert m["supportsReasoning"] is True
    finally:
        await gw.stop()


async def test_custom_model_does_not_crash_models_list(make_gateway):
    """自定义模型（不在内置目录）→ 最小字段集，**不崩**（§12.3 兜底）。"""
    gw = await make_gateway(gateway_config(1, models=[chat_res("AB", name="my-own-model")]))
    try:
        m = (await _models(gw))[0]
        assert m["id"] == "my-own-model"
        assert m["maxInputTokens"] is None
    finally:
        await gw.stop()


# ---------- caps.thinkingLevelMap（§12.2a / M3-4）----------

async def test_caps_level_map_has_exactly_seven_keys(make_gateway):
    """🔴 7 键**齐全** —— 键缺失（undefined）≠ null，工具会把缺失键误判为"支持"。"""
    gw = await make_gateway(gateway_config(1, models=[chat_res("AB", name="glm-5.2")]))
    try:
        caps = (await _models(gw))[0]["caps"]
        lm = caps["thinkingLevelMap"]
        assert list(lm.keys()) == LEVELS
        assert len(lm) == 7
    finally:
        await gw.stop()


async def test_caps_unsupported_levels_are_explicit_null(make_gateway):
    """不支持的档 → **显式 `null`**（JSON 序列化后），不得省略键。"""
    gw = await make_gateway(gateway_config(1, models=[chat_res("AB", name="glm-5.2")]))
    try:
        lm = (await _models(gw))[0]["caps"]["thinkingLevelMap"]
        assert lm["minimal"] is None and "minimal" in lm
        assert lm["off"] is None and "off" in lm
        assert lm["max"] == "max"
    finally:
        await gw.stop()


async def test_caps_overrides_from_yaml_wins(make_gateway):
    """`caps_overrides`（YAML 手改）优先级最高（§12.3 逃生口）。"""
    model = chat_res("AB", name="glm-5.2")
    model["caps_overrides"] = {"thinkingLevelMap": {"max": "ultra"}}
    gw = await make_gateway(gateway_config(1, models=[model]))
    try:
        lm = (await _models(gw))[0]["caps"]["thinkingLevelMap"]
        assert lm["max"] == "ultra"
    finally:
        await gw.stop()


# ---------- 入站前缀剥离（§19 M3-1 / Q25-⑦）----------

@pytest.mark.parametrize("prefix", ["custom:", "custom-local:"])
async def test_request_model_prefix_is_stripped(make_gateway, prefix, vendor):
    """🔴 工具侧会带 `custom:` / `custom-local:` 前缀 —— 网关必须剥离，
    否则会误判为"模型不存在"404（PRD Q25-⑦）。"""
    gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{gw.base_url}/v1/chat/completions",
                             json={"model": f"{prefix}test-model",
                                   "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 200, f"带前缀 {prefix} 的模型名应能解析，实际 {r.status_code}"
    finally:
        await gw.stop()


async def test_unprefixed_model_still_works(make_gateway, vendor):
    """无前缀照常工作（剥离是幂等的）。"""
    gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{gw.base_url}/v1/chat/completions",
                             json={"model": "test-model",
                                   "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 200
    finally:
        await gw.stop()


async def test_unknown_model_still_404_after_stripping(make_gateway):
    """剥离后仍无命中 → 正常 404（剥离不掩盖真实的不存在）。"""
    gw = await make_gateway(gateway_config(1, models=[chat_res("AB")]))
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{gw.base_url}/v1/chat/completions",
                             json={"model": "custom:nope",
                                   "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "model_not_found"
    finally:
        await gw.stop()


# ---------- §21 用户可见出口：overview warnings ----------

async def _overview(gw) -> dict:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{gw.base_url}/admin/api/overview")
    assert r.status_code == 200
    return r.json()


async def test_overview_exposes_warnings_field(make_gateway):
    """🔴 告警必须走**接口**而非只写日志 —— 启动脚本 nohup + 自动关窗，写日志用户看不见。"""
    gw = await make_gateway(gateway_config(1, models=[chat_res("AB")]))
    try:
        assert "warnings" in await _overview(gw)
    finally:
        await gw.stop()


async def test_warning_for_enabled_model_without_resource(make_gateway):
    """① 模型已启用但 `resources` 为空 → 调用必返 503，**必须告警**。"""
    cfg = gateway_config(1, models=[chat_res("AB")])
    cfg["models"].append({"name": "orphan-model", "endpoint": "chat", "resources": []})
    gw = await make_gateway(cfg)
    try:
        ws = (await _overview(gw))["warnings"]
        kinds = [w["kind"] for w in ws]
        assert "model_without_resource" in kinds
        msg = next(w["message"] for w in ws if w["kind"] == "model_without_resource")
        assert "503" in msg and "orphan-model" in msg
    finally:
        await gw.stop()


async def test_warning_for_enabled_resource_without_model(make_gateway):
    """② 资源已启用但无任何模型引用 → 配置冗余，**必须告警**（两类措辞不同）。"""
    cfg = gateway_config(1, models=[chat_res("A")])   # 只引用 res-A，B/C/D 成为孤儿
    gw = await make_gateway(cfg)
    try:
        ws = (await _overview(gw))["warnings"]
        kinds = [w["kind"] for w in ws]
        assert "resource_without_model" in kinds
        msg = next(w["message"] for w in ws if w["kind"] == "resource_without_model")
        assert "未被任何网关模型引用" in msg
    finally:
        await gw.stop()


async def test_no_warnings_when_config_is_complete(make_gateway):
    """配置完整 → `warnings` 为空（不制造噪音告警）。"""
    cfg = gateway_config(1, models=[chat_res("ABCD")])   # 4 资源全被引用
    gw = await make_gateway(cfg)
    try:
        assert (await _overview(gw))["warnings"] == []
    finally:
        await gw.stop()


async def test_two_warning_kinds_have_distinct_wording(make_gateway):
    """两类告警**措辞不同**（PRD Q25-⑧ 明确要求区分）。"""
    cfg = gateway_config(1, models=[chat_res("A")])
    cfg["models"].append({"name": "empty-one", "endpoint": "chat", "resources": []})
    gw = await make_gateway(cfg)
    try:
        ws = {w["kind"]: w["message"] for w in (await _overview(gw))["warnings"]}
        assert ws["model_without_resource"] != ws["resource_without_model"]
        assert "503" in ws["model_without_resource"]
        assert "引用" in ws["resource_without_model"]
    finally:
        await gw.stop()


# ---------- §21 status 失败计数 ----------

async def test_status_exposes_ops_failed_counter(make_gateway):
    """`/admin/api/status` 暴露运营未读失败数（顶栏红点用；复用既有 5s 轮询）。"""
    gw = await make_gateway(gateway_config(1, models=[chat_res("AB")]))
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{gw.base_url}/admin/api/status")
        assert r.status_code == 200
        assert r.json()["ops_failed_unread"] == 0
    finally:
        await gw.stop()


# ---------- 枚举池**双向一致**（验收 P3-2：`tool_call` 曾在 PUT 侧被丢掉）----------

async def test_enums_round_trip_preserves_tool_call(make_gateway):
    """GET→把某条 `tool_call` 改成 false→PUT→再 GET 与 `/v1/models`，三处必须同一结论。

    判据取自**真接口往返**而不是直接构造 `EnumEntry`：`to_dict()` 会导出这个键，
    但 PUT 若不读回来，用户在枚举池页编辑一次就把 `tool_call: false` 抹回默认值。
    """
    gw = await make_gateway(gateway_config(1, models=[chat_res("AB", name="glm-5.2")]))
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            entries = (await c.get(f"{gw.base_url}/admin/api/enums")).json()["entries"]
            assert entries, "枚举池为空 → 本用例失去意义"
            assert {e["name"] for e in entries} >= {"glm-5.2"}
            for e in entries:
                if e["name"] == "glm-5.2":
                    e["tool_call"] = False
            r = await c.put(f"{gw.base_url}/admin/api/enums", json={"entries": entries})
            assert r.status_code == 200, r.text
            back = (await c.get(f"{gw.base_url}/admin/api/enums")).json()["entries"]
            assert next(e for e in back if e["name"] == "glm-5.2")["tool_call"] is False
            models = (await c.get(f"{gw.base_url}/v1/models")).json()["data"]
        row = next(m for m in models if m["id"] == "glm-5.2")
        assert row["supportsToolCall"] is False, "文件里已改，但下发仍按默认 True"
    finally:
        await gw.stop()


# ---------- L-3：枚举池"清空"必须是**可见的拒绝**，不是静默无效 ----------

async def test_enums_put_rejects_empty_list_and_reports_source_honestly(make_gateway, client):
    """🔴 空清单 → 400 + 说清为什么；GET 的 `source` 必须与**实际生效来源**一致。

    上一版：`PUT {"entries": []}` 回"已保存并生效"，文件写成空，
    而 `load_enum_pool` 见空回落内置目录 —— 用户以为清空了，实际一条没变。
    """
    gw = await make_gateway(gateway_config(1, models=[chat_res("AB")]))
    try:
        r = await client.put(f"{gw.base_url}/admin/api/enums", json={"entries": []})
        assert r.status_code == 400, r.status_code
        body = r.json()
        assert body["status"] == "rejected"
        assert "回落" in body["errors"][0] and "删除该文件" in body["errors"][0], body

        got = (await client.get(f"{gw.base_url}/admin/api/enums")).json()
        assert got["source"] == "builtin", got["source"]
        assert got["entries"], "拒绝保存后枚举池必须还是内置那份"

        # 手工放一个**空**文件（绕过端点）：source 仍不得谎报 file
        gw.config_path.parent.joinpath("enums-empty.yaml").write_text("entries: []\n",
                                                                      encoding="utf-8")
        from model_gateway.enums.matcher import load_enum_pool

        assert load_enum_pool(gw.config_path.parent / "enums-empty.yaml").entries, \
            "空文件应回落内置目录（与 GET 的 source 口径一致）"
    finally:
        await gw.stop()
