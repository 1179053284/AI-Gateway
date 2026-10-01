"""v2.0 §12.1「消灭静默降级」/ BUG-1 · BUG-2 集成测试（本轮修复）。

**BUG-1**：`/v1/models` 与 `mgw setup` 曾把**必然失败**的模型下发给工具
（只按 `enabled` 过滤，不看有没有可用资源）→ 工具选中即 `NO_RESOURCE`，
无报错的失败。修正后：**只声明可服务的模型**，且被隐藏者必须有横幅说明去向
（隐藏而不解释 = 换一种静默）。

**BUG-2**：按 PRD FR-3.16（Q15）的定序**不动**（请求级 > 资源级默认 > 参数卡），
只把「参数卡字段被资源级默认覆盖」这件事变得可见。
"""

from __future__ import annotations

import httpx
import pytest

from tests.integration.conftest import chat_res, gateway_config

pytestmark = pytest.mark.asyncio


async def _ids(gw) -> list[str]:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{gw.base_url}/v1/models")
    assert r.status_code == 200
    return [m["id"] for m in r.json()["data"]]


async def _warnings(gw) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{gw.base_url}/admin/api/overview")
    return r.json()["warnings"]


# ---------- BUG-1：清单过滤 ----------

async def test_model_with_no_usable_resource_is_not_published(make_gateway):
    """资源全部停用 → 该模型**不出现在 /v1/models**（原先会出现，调用即失败）。"""
    cfg = gateway_config(1, models=[chat_res("AB", name="needs-resource")])
    cfg["resources"][0]["enabled"] = False
    cfg["resources"][1]["enabled"] = False
    gw = await make_gateway(cfg)
    try:
        assert "needs-resource" not in await _ids(gw)
    finally:
        await gw.stop()


async def test_model_with_one_enabled_resource_is_published(make_gateway):
    """只要有一条可用映射就照常声明（不得过度隐藏）。"""
    cfg = gateway_config(2, models=[chat_res("AB", name="half-alive")])
    cfg["resources"][0]["enabled"] = False
    gw = await make_gateway(cfg)
    try:
        assert "half-alive" in await _ids(gw)
    finally:
        await gw.stop()


async def test_invalid_credential_model_is_hidden_but_explained(make_gateway):
    """🔴 凭据失效（运行态 invalid）→ 隐藏 **且** 给横幅：不能让用户觉得模型凭空消失。"""
    cfg = gateway_config(3, models=[chat_res("AB", name="dead-key")])
    gw = await make_gateway(cfg)
    try:
        gw.resource("res-A", "vm-A").status = "invalid"
        gw.resource("res-B", "vm-B").status = "disabled"
        assert "dead-key" not in await _ids(gw)
        kinds = {w["kind"]: w["message"] for w in await _warnings(gw)}
        assert "model_unservable" in kinds
        assert "dead-key" in kinds["model_unservable"]
        assert "/v1/models" in kinds["model_unservable"]
    finally:
        await gw.stop()


async def test_cooldown_model_stays_published(make_gateway):
    """冷却是**临时**态：隐藏它会让模型在工具里无故消失并促使用户改配置 → 不得隐藏。"""
    cfg = gateway_config(4, models=[chat_res("AB", name="cooling")])
    gw = await make_gateway(cfg)
    try:
        st = gw.resource("res-A", "vm-A")
        st.status = "cooldown"
        st.cooldown_until = gw.runtime.resources.clock() + 60
        gw.resource("res-B", "vm-B").status = "cooldown"
        assert "cooling" in await _ids(gw)
        assert not [w for w in await _warnings(gw) if w["kind"] == "model_unservable"]
    finally:
        await gw.stop()


async def test_hidden_models_do_not_break_the_capability_fields(make_gateway):
    """过滤只减条目：留下的模型能力位字段必须仍然齐全（不得因新逻辑而退化）。"""
    cfg = gateway_config(5, models=[chat_res("AB", name="glm-5.2")])
    gw = await make_gateway(cfg)
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{gw.base_url}/v1/models")
        m = r.json()["data"][0]
        assert m["maxInputTokens"] and "thinkingLevelMap" in m["caps"]
        assert len(m["caps"]["thinkingLevelMap"]) == 7
    finally:
        await gw.stop()


# ---------- BUG-2：优先级不动，但覆盖必须可见 ----------

async def test_params_card_shadowing_is_warned(make_gateway):
    """参数卡配 `reasoning_effort` + 资源级也配了推理默认 → 告警说明谁生效。"""
    cfg = gateway_config(6, models=[chat_res("AB", name="mixer",
                                            params={"reasoning_effort": "max"},
                                            resources=[
                                                {"resource": "res-A", "model": "vm-A",
                                                 "reasoning": {"enabled": True,
                                                               "effort": "low"}},
                                                {"resource": "res-B", "model": "vm-B"},
                                            ])])
    gw = await make_gateway(cfg)
    try:
        kinds = {w["kind"]: w["message"] for w in await _warnings(gw)}
        assert "param_shadowed" in kinds
        msg = kinds["param_shadowed"]
        assert "reasoning_effort" in msg
        assert "资源A" in msg          # 指名是哪条映射把它盖了
        assert "请求级" in msg          # 说清生效序，不让人猜
    finally:
        await gw.stop()


async def test_no_shadow_warning_when_no_resource_reasoning(make_gateway):
    """资源级没配推理 → 参数卡的值正常生效，**不得**制造噪音告警。

    （三级合并本身的端到端断言在 `test_int_chat.py::TestModelParamsInjection`，
    那里直接验出站请求体 —— 本文件只管"可见性"这一维。）
    """
    cfg = gateway_config(7, models=[chat_res("AB", name="clean",
                                            params={"reasoning_effort": "max"})])
    gw = await make_gateway(cfg)
    try:
        assert not [w for w in await _warnings(gw) if w["kind"] == "param_shadowed"]
    finally:
        await gw.stop()
