"""结构化计费字段（`ModelInfo.free` / `ModelInfo.rate`）逐产品单测（2026-10-01）。

背景：此前只有 raccoon/loomy/cline 把计费倍率拼进**展示名**（`name`），其余产品直接丢弃；
管理端要展示「消耗规则 / 是否免费」需要**结构化字段**。本轮为 `accounts/types.py::ModelInfo`
补 `free`（True=免费 / False=有计费 / None=未取到）与 `rate`（展示文本，`""`=未提供），
逐产品把 DSH 参考源（`deepseek-harness-codearts/src/`）的判据搬进各产品模块。

🔴 全部用例**无网络**：纯函数喂 fixture（载荷形状逐条照抄 DSH 的**真实实测形态**）；
   只有 buddy/workbuddy 的两个用例经 `httpx.MockTransport` 走一遍钩子装配路径（仍是假上游）。
🔴 展示名**不得变化**：每处都顺带断言 `name` 仍是原来的「` · 免费` / ` · x…`」形态
   （结构化字段是**并列新增**，不是替换）。
🔴 口径（写进断言的「决定」）：
   - `rate` 恒为**数字形态文本**（含生效价 0 → `x0`）——「免费」由 `free=True` 表达，
     与 `x0.05` 一类字符串同构（DSH 展示层把 0 显示成「免费」，本层拆成两个字段）；
   - 免费促销（buddy `factor: 0`）展示层是 `x0.29→免费`，本层记 `free=True` + `x0.29→x0`；
   - 取不到计费字段（`credits` 空串 / `costMultiplier` 缺失 / 无 `consumption_rate`…）
     一律 `free=None` + `rate=""`，**不编造** `x1`（`21 §5.1-1`）。
"""

from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

import httpx

from model_gateway.accounts import net
from model_gateway.upstream.buddy import product as buddy
from model_gateway.upstream.cline import protocol as cline_p
from model_gateway.upstream.lobsterai import models as lobsterai_models
from model_gateway.upstream.loomy import models as loomy_models
from model_gateway.upstream.qoder import config as qoder_config
from model_gateway.upstream.raccoon import const as raccoon_c
from model_gateway.upstream.raccoon import protocol as raccoon_p
from model_gateway.upstream.trae import models as trae_models
from model_gateway.upstream.trae import protocol as trae_p
from model_gateway.upstream.workbuddy import product as workbuddy
from model_gateway.upstream.zcode import product as zcode

SH = ZoneInfo("Asia/Shanghai")
#: 固定注入时刻（`buddy.ts:626-629` 的 `now` 注入缝同构；避免用例依赖真实时钟）
NIGHT = dt.datetime(2026, 9, 21, 0, 43, tzinfo=SH)     # 23:00–7:50 窗口内
DAY = dt.datetime(2026, 9, 21, 12, 0, tzinfo=SH)       # 窗口外


def _install_upstream(monkeypatch, bodies_by_host: dict) -> list[httpx.Request]:
    """把 `accounts/net.py::make_client` 换成假上游（按 host 分发；记录请求）。"""
    seen: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = bodies_by_host.get(request.url.host)
        if body is None:
            return httpx.Response(404, json={"code": 404, "message": "no route"})
        return httpx.Response(200, json=body, request=request)

    def factory(**kwargs):
        kwargs.pop("follow_redirects", None)
        kwargs["timeout"] = httpx.Timeout(5.0)
        return httpx.AsyncClient(transport=httpx.MockTransport(responder), **kwargs)

    monkeypatch.setattr(net, "make_client", factory)
    return seen


# ============ raccoon（`raccoon.ts:219-262`）============

#: 远端目录 fixture（形状 = `model_catalog` 的 `categories[].models[]`，
#: `raccoon-auth.ts:137-182`；数值用 DSH README 的实测表：免费 / 促销 / 1 倍）
_RACCOON_CATALOG = {"code": 0, "data": {"categories": [{"type": "chat", "models": [
    {"name": "sn-sensenova-6-8-flash", "description": "SenseNova-6.8-Flash",
     "billing_effective_multiplier": 0, "billing_multiplier": 0.5},
    {"name": "sn-glm-5-3-flash", "description": "GLM-5-3-Flash",
     "billing_effective_multiplier": 0.1, "billing_multiplier": 0.2},
    {"name": "sn-kimi-k3", "description": "Kimi-K3",
     "billing_effective_multiplier": 1, "billing_multiplier": 1},
    {"name": "no-billing", "description": "NoBilling"},          # 计费字段缺失 → 未取到
]}]}}


def test_raccoon_remote_catalog_carries_structured_billing():
    """远端目录：生效价 0 → free=True；促销 → `x原价→x折后价`；1 倍 → `x1`（**不得省略**）；
    计费字段缺失 → `None` / `""`；展示名逐条**不变**（`raccoon.ts:225-262` 规则照旧）。"""
    models = {m.id: m for m in raccoon_p.parse_catalog(_RACCOON_CATALOG)}
    free = models["sn-sensenova-6-8-flash"]
    assert (free.name, free.free, free.rate) == ("SenseNova-6.8-Flash · 免费", True, "x0")
    promo = models["sn-glm-5-3-flash"]
    assert (promo.name, promo.free, promo.rate) == ("GLM-5-3-Flash · x0.2→x0.1", False, "x0.2→x0.1")
    one = models["sn-kimi-k3"]
    assert (one.name, one.free, one.rate) == ("Kimi-K3 · x1", False, "x1")
    missing = models["no-billing"]
    assert (missing.name, missing.free, missing.rate) == ("NoBilling", None, "")


def test_raccoon_fallback_table_carries_structured_billing():
    """兜底表 6 条：结构化字段与展示名后缀**逐条一致**（免费 → True；促销 → 箭头）。"""
    by_id = {m.id: m for m in raccoon_c.FALLBACK_MODELS}
    assert (by_id["sn-sensenova-6-8-flash"].free, by_id["sn-sensenova-6-8-flash-lite"].free) \
        == (True, True)
    assert by_id["sn-glm-5-3"].rate == "x0.75" and by_id["sn-glm-5-3"].free is False
    assert by_id["sn-kimi-k3"].rate == "x1"
    assert by_id["sn-glm-5-3-flash"].rate == "x0.2→x0.1"
    assert by_id["sn-deepseek-v4-1-flash"].rate == "x0.25"


# ============ loomy（`loomy.ts:125-160`：倍率在 name 字符串里）============


def test_loomy_rate_free_from_name_string():
    """倍率从 `name` 字符串拆出（本产品无独立计费字段）：`x0.0` → free=True；
    无倍率 → `None` / `""`；展示名仍是规范化形态（`split_rate` 幂等）。"""
    models = {m.id: m for m in loomy_models.parse_remote_models({"data": [
        {"id": "m1", "type": "chat", "name": "MiniMax M3 （x4.0）"},
        {"id": "m2", "type": "chat", "name": "Free Model(x0.0)"},
        {"id": "m3", "type": "chat", "name": "No Rate"},
        {"id": "img", "type": "image", "name": "Img Model (x9.0)"},     # 非 chat → 过滤
    ]})}
    assert (models["m1"].name, models["m1"].free, models["m1"].rate) == ("MiniMax M3 · x4.0", False, "x4.0")
    assert (models["m2"].free, models["m2"].rate) == (True, "x0.0")
    assert (models["m3"].free, models["m3"].rate) == (None, "")
    assert "img" not in models

    fallback = {m.id: m for m in loomy_models.fallback_models()}
    assert len(fallback) == 8
    assert (fallback["spark-x"].free, fallback["spark-x"].rate) == (False, "x0.1")
    assert fallback["MiniMax-M3"].rate == "x4.0"


# ============ cline（`cline-models.ts:20-36,85-94`：免费是布尔集合）============


def test_cline_free_flag_and_no_numeric_rate():
    """免费判定三来源并集（远端 free 集合 ∪ `:free` 后缀/`cline-free/` 前缀 ∪ 兜底表）；
    `free` 恒为布尔；`rate` 留空（本产品无数值倍率，**不编造** `x1`）。"""
    models = {m.id: m for m in cline_p.merge_models(
        free_ids=["remote-free-x"], entries=[], remote_ids=["paid-y", "org/model:free"])}
    assert (models["remote-free-x"].free, models["remote-free-x"].rate) == (True, "")
    # 展示名规则不变（`name_from_id` 派生名 + ` · 免费` 后缀，`cline-models.ts:96-118`）
    assert models["remote-free-x"].name == "Remote Free X · 免费"
    assert (models["paid-y"].free, models["paid-y"].rate) == (False, "")
    assert (models["cline-free/deepseek-v4.1-flash"].free,   # 兜底表 is_free 条目
            models["cline-free/deepseek-v4.1-flash"].rate) == (True, "")
    assert models["org/model:free"].free is True               # `:free` 后缀（id 来自远端大列表）


# ============ buddy / workbuddy（`buddy.ts:476-698`）============

#: `/v3/config` fixture（形状 = `buddy.ts:604-611` 的真实结构：促销是**独立活动数组**，
#: 按 `modelIds` 关联；`glm-5.2` 夜间/白天两条互补活动是 DSH 单测里的实测形态）
def _config_payload() -> dict:
    return {"code": 0, "data": {
        "agents": [{"name": "craft", "models": [
            "deepseek-v4.1-flash", "glm-5.2", "hy4-preview", "hy4-preview-f"]}],
        "models": [
            {"id": "deepseek-v4.1-flash", "name": "Deepseek-V4.1-Flash",
             "credits": "x0.03 credits"},                        # 带单位后缀的早期形态
            {"id": "glm-5.2", "name": "GLM-5.2", "credits": "x0.79"},
            {"id": "hy4-preview", "name": "Hy4 preview", "credits": "x0.29"},
            # hy4-preview-f **只在 agent 引用里**（实测只由 /v3/config 下发）→ 走尾部追加路径
        ],
        "modelPromotions": [
            {"id": "glm-52-night", "enabled": True, "priority": 100, "modelIds": ["glm-5.2"],
             "discount": {"discountedCredits": "0.50x", "factor": 0.5},
             "schedule": {"daily": [{"start": "23:00", "end": "7:50"}],
                          "timezone": "Asia/Shanghai"}},
            {"id": "glm-52-day", "enabled": True, "priority": 50, "modelIds": ["glm-5.2"],
             "schedule": {"daily": [{"start": "7:50", "end": "23:00"}],
                          "timezone": "Asia/Shanghai"}},
            {"id": "hy4-night-free", "enabled": True, "priority": 100,
             "modelIds": ["hy4-preview"],
             "discount": {"discountedCredits": "0x", "displayMode": "replace", "factor": 0},
             "schedule": {"daily": [{"start": "23:00", "end": "08:00"}],
                          "timezone": "Asia/Shanghai"}},
            # 限时免费变体：有效期已过（2026-08-06 截止）→ 不得展示
            {"id": "hy4f-window", "enabled": True, "priority": 100,
             "modelIds": ["hy4-preview-f"],
             "discount": {"discountedCredits": "0x", "factor": 0},
             "schedule": {"timezone": "Asia/Shanghai",
                          "validFrom": "2026-07-06T00:00:00+08:00",
                          "validUntil": "2026-08-06T00:00:00+08:00"}},
        ],
    }}


def test_buddy_credits_forms_and_promotion_windows_night():
    """夜间：促销生效 → `x0.79→x0.50`；`factor: 0` + 时段窗口 = **免费**（`free=True`）；
    `credits` 带 ` credits` 后缀照常解析。"""
    from model_gateway.upstream.buddy import protocol as buddy_p

    parsed = {m.id: m for m in buddy_p.parse_models_from_config(_config_payload(), NIGHT).models}
    assert (parsed["deepseek-v4.1-flash"].free, parsed["deepseek-v4.1-flash"].rate) \
        == (False, "x0.03")
    assert parsed["deepseek-v4.1-flash"].name == "Deepseek-V4.1-Flash"
    assert (parsed["glm-5.2"].free, parsed["glm-5.2"].rate) == (False, "x0.79→x0.50")
    assert (parsed["hy4-preview"].free, parsed["hy4-preview"].rate) == (True, "x0.29→x0")
    # 有效期已过（hy4-preview-f 的窗口在 8 月截止）→ 未取到（`credits` 也缺失）
    assert (parsed["hy4-preview-f"].free, parsed["hy4-preview-f"].rate) == (None, "")


def test_buddy_promotion_placeholder_and_priority_skip():
    """白天：夜间活动不得生效（否则用户按折扣价预期、实际被按原价计费）；
    无时间窗口的 `0x` 是「已结束占位」→ 跳过；同模型多活动取 priority 最高者。"""
    from model_gateway.upstream.buddy import protocol as buddy_p

    day = {m.id: m for m in buddy_p.parse_models_from_config(_config_payload(), DAY).models}
    assert (day["glm-5.2"].free, day["glm-5.2"].rate) == (False, "x0.79")
    assert (day["hy4-preview"].free, day["hy4-preview"].rate) == (False, "x0.29")

    promotions = buddy_p.parse_promotions({"modelPromotions": [
        {"enabled": True, "priority": 10, "modelIds": ["m"],
         "discount": {"discountedCredits": "0.10x"}},
        {"enabled": True, "priority": 999, "modelIds": ["m"],
         "discount": {"discountedCredits": "0.90x"}},
        {"enabled": True, "priority": 100, "modelIds": ["placeholder"],
         "discount": {"discountedCredits": "0x"}},              # 无窗口 0x → 占位，跳过
    ]}, DAY)
    assert promotions["m"] == "x0.90" and "placeholder" not in promotions


def test_buddy_merge_keeps_remote_billing_and_unknown_for_fallback_only():
    """合并：远端有计费 → 逐字带上；只有兜底表条目的模型（远端无声明）→ 未取到。"""
    from model_gateway.upstream.buddy import protocol as buddy_p

    remote = buddy_p.parse_models_from_config(_config_payload(), NIGHT)
    merged = {m.id: m for m in buddy_p.merge_models(remote, buddy._PROFILE.fallback_models)}
    assert (merged["glm-5.2"].free, merged["glm-5.2"].rate) == (False, "x0.79→x0.50")
    # 兜底表条目（远端未声明计费）→ None / ""（不编造；`product.ts:32-51` 无 credits 字段）
    assert (merged["hy3"].free, merged["hy3"].rate) == (None, "")


async def test_buddy_and_workbuddy_share_billing_payload_path(monkeypatch):
    """两个产品**共用**同一份解析（`product.ts:1-30` 同源）：同一份 `/v3/config` 载荷
    经各自基址与档案（buddy `copilot.tencent.com` / workbuddy `www.workbuddy.ai`）
    都解析出同样的结构化计费 → 证明「载荷路径对两者都适用」。

    ⚠️ 本用例经钩子走真实时钟（`now=None`），故促销 fixture 用**时间无关**形态：
    `glm-5.2` 的折扣不带 `schedule`（恒生效）、`hy4-preview` 的限时免费用远期有效期窗口。
    """
    from model_gateway.upstream.buddy import protocol as buddy_p

    payload = {"code": 0, "data": {
        "agents": [{"name": "craft", "models": ["glm-5.2", "hy4-preview"]}],
        "models": [{"id": "glm-5.2", "name": "GLM-5.2", "credits": "x0.79"},
                   {"id": "hy4-preview", "name": "Hy4 preview", "credits": "x0.29"}],
        "modelPromotions": [
            {"enabled": True, "priority": 100, "modelIds": ["glm-5.2"],
             "discount": {"discountedCredits": "0.50x", "factor": 0.5}},      # 无 schedule → 恒生效
            {"enabled": True, "priority": 100, "modelIds": ["hy4-preview"],
             "discount": {"discountedCredits": "0x", "factor": 0},
             "schedule": {"timezone": "Asia/Shanghai",
                          "validFrom": "2026-01-01T00:00:00+08:00",
                          "validUntil": "2030-01-01T00:00:00+08:00"}},       # 远期窗口内
        ],
    }}
    seen = _install_upstream(monkeypatch, {
        "copilot.tencent.com": payload,
        "www.workbuddy.ai": payload,
    })
    cred = {"access_token": "AT-1"}
    for product in (buddy, workbuddy):
        models = {m.id: m for m in await product.list_models(cred, product.meta())}
        assert (models["glm-5.2"].free, models["glm-5.2"].rate) == (False, "x0.79→x0.50")
        assert (models["hy4-preview"].free, models["hy4-preview"].rate) == (True, "x0.29→x0")
    assert {r.url.host for r in seen} == {"copilot.tencent.com", "www.workbuddy.ai"}
    assert all(r.url.path == buddy_p.CONFIG_PATH for r in seen)


# ============ lobsterai（`lobsterai-adapter.ts:145-158,286`）============


def test_lobsterai_cost_multiplier_bare_number_forms():
    """`costMultiplier` 是**裸数字**（跟 buddy 的字符串形态不同）：`0.05` → `x0.05`；
    `20` → `x20`（最短形态）；`0` → free=True（DSH 只收正数，本层把 0 如实结构化）；
    缺失 → `None` / `""`。"""
    models = {m.id: m for m in lobsterai_models.parse_models({"code": 0, "data": [
        {"modelId": "a", "modelName": "A", "costMultiplier": 0.05},
        {"modelId": "b", "modelName": "B", "costMultiplier": 20},
        {"modelId": "c", "modelName": "C", "costMultiplier": 0},
        {"modelId": "d", "modelName": "D"},
    ]})}
    assert (models["a"].free, models["a"].rate) == (False, "x0.05")
    assert (models["b"].free, models["b"].rate) == (False, "x20")
    assert (models["c"].free, models["c"].rate) == (True, "x0")
    assert (models["d"].free, models["d"].rate) == (None, "")


# ============ trae（`trae.ts:968-1042` / `trae-adapter.ts:570-581`）============

#: 固定「现在」（`trae.ts:1003-1004` 的 `nowSec` 注入缝同构）
TRAE_NOW = 1_789_905_263


def _dc(**sections) -> dict:
    """`display_contact_config` 是**JSON 字符串**（必须二次解析，`trae.ts:953-957`）。"""
    entry: dict = {"config_name": "test-model", "display_config": {"display_name": "Test"}}
    entry["display_contact_config"] = json.dumps(sections)
    return entry


def test_trae_consumption_rate_forms():
    """倍率三态：`0.08` → 有计费；`0` → **免费**（`> 0` 过滤会恰好漏掉免费模型）；
    `enable: false` → 视为无倍率（**不是**当成 0）；非法 JSON → 未取到。"""
    ok = trae_p.parse_entry(_dc(consumption_rate={"enable": True, "data": {"rate": 0.08}}),
                            "solo_work_lite", TRAE_NOW)
    assert (ok.rate, trae_models._billing_of(ok)) == (0.08, (False, "x0.08"))
    zero = trae_p.parse_entry(_dc(consumption_rate={"enable": True, "data": {"rate": 0}}),
                              "solo_work_lite", TRAE_NOW)
    assert trae_models._billing_of(zero) == (True, "x0")
    disabled = trae_p.parse_entry(
        _dc(consumption_rate={"enable": False, "data": {"rate": 0.5}}), "solo_work_lite", TRAE_NOW)
    assert (disabled.rate, trae_models._billing_of(disabled)) == (None, (None, ""))
    bad = dict(_dc(consumption_rate={"enable": True, "data": {"rate": 0.08}}))
    bad["display_contact_config"] = "{not json"
    parsed_bad = trae_p.parse_entry(bad, "solo_work_lite", TRAE_NOW)
    assert (parsed_bad.rate, trae_models._billing_of(parsed_bad)) == (None, (None, ""))


def test_trae_activity_discount_validity_and_arrow():
    """活动折扣只在**当前确实生效**时展示：`limited` 型（带未到期 `end_at`）→
    `x0.8→x0.08`；`discount_type: "none"`（实测 off_peak 陷阱）→ 不展示；
    已过 `end_at` → 不展示。"""
    limited = trae_p.parse_entry(_dc(
        consumption_rate={"enable": True, "data": {"rate": 0.08}},
        activity_discount={"enable": True, "data": {
            "current": {"discount_type": "limited", "before_consumption_rate": 0.8,
                        "consumption_rate": 0.08, "discount": 10},
            "limited": {"end_at": TRAE_NOW + 100}}}), "solo_work_lite", TRAE_NOW)
    assert trae_models._billing_of(limited) == (False, "x0.8→x0.08")

    off_peak = trae_p.parse_entry(_dc(
        consumption_rate={"enable": True, "data": {"rate": 0.13}},
        activity_discount={"enable": True, "data": {
            "current": {"discount_type": "none", "before_consumption_rate": 0.13,
                        "consumption_rate": 0.13, "discount": 100}}}), "solo_work_lite", TRAE_NOW)
    assert trae_models._billing_of(off_peak) == (False, "x0.13")

    expired = trae_p.parse_entry(_dc(
        consumption_rate={"enable": True, "data": {"rate": 0.08}},
        activity_discount={"enable": True, "data": {
            "current": {"discount_type": "limited", "before_consumption_rate": 0.8,
                        "consumption_rate": 0.08},
            "limited": {"end_at": TRAE_NOW - 10}}}), "solo_work_lite", TRAE_NOW)
    assert trae_models._billing_of(expired) == (False, "x0.08")
    # 兜底目录（`trae-product.ts:164-202`）不含计费字段 → 默认未取到（不编造）
    assert all(m.free is None and m.rate == "" for m in trae_models.fallback_models())


# ============ qoder / qodercn（`qoder-adapter.ts:1042-1119`）============


def test_qoder_billing_windows_are_locally_computed():
    """`price_factor: 0` → 免费；错峰窗口**本地推算**（不采信目录 `active` 快照）：
    窗口内 `x0.5→x0.2`，窗口外只显示原价 `x0.5`；无促销 → `x{price_factor}`。"""
    by_id = {m.id: m for m in qoder_config.QODER_MODELS}
    assert qoder_config.billing_info(by_id["qfmodel"], DAY) == (True, "x0")
    assert qoder_config.billing_info(by_id["qmodel_38max"], NIGHT) == (False, "x0.5→x0.2")
    assert qoder_config.billing_info(by_id["qmodel_38max"], DAY) == (False, "x0.5")
    assert qoder_config.billing_info(by_id["qmodel"], NIGHT) == (False, "x0.1→x0.04")
    assert qoder_config.billing_info(by_id["kmodel_latest"], DAY) == (False, "x1.4")
    # 窗口边界：终点不含（08:00 已出窗）、起点含（22:00 已入窗）
    eight = dt.datetime(2026, 9, 21, 8, 0, tzinfo=SH)
    ten_pm = dt.datetime(2026, 9, 21, 22, 0, tzinfo=SH)
    assert qoder_config.billing_info(by_id["qmodel_38max"], eight) == (False, "x0.5")
    assert qoder_config.billing_info(by_id["qmodel_38max"], ten_pm) == (False, "x0.5→x0.2")
    # 目录 `active: false` 是**下发那一刻的快照** → 窗口内仍应按窗口推算（DST 的坑位注释）
    stale = qoder_config.QoderModel(
        "stale", "Stale", 1_000, price_factor=0.5,
        promotion=qoder_config.QoderPromotion(
            active=False, discount_factor=0.5, before_promotion_price_factor=1.0,
            window_start="22:00", window_end="08:00"))
    assert qoder_config.billing_info(stale, NIGHT) == (False, "x1→x0.5")


def test_qoder_price_fields_present_in_both_tables():
    """两张静态表（国际 17 条 / CN 14 条）逐条带上定价字段；CN 独有条目同口径。"""
    assert all(m.price_factor is not None for m in qoder_config.QODER_MODELS)
    assert all(m.price_factor is not None for m in qoder_config.QODER_CN_MODELS)
    intl = {m.id: m for m in qoder_config.QODER_MODELS}
    cn = {m.id: m for m in qoder_config.QODER_CN_MODELS}
    assert intl["smodel"].price_factor == 8 and intl["qmodel"].price_factor == 0.04
    assert intl["qfmodel"].price_factor == 0 and intl["qfmodel"].original_price_factor == 0.1
    assert cn["gm51model"].price_factor == 0.6 and cn["q37fmodel"].price_factor == 0.1


# ============ zcode（token 额度语义，无倍率字段）============


def test_zcode_models_leave_billing_unset():
    """zcode 按 token 额度计费（免费额度 1 亿 token/日），目录无 credits 类字段 →
    `free` / `rate` 保持默认（**不编造**）。"""
    assert all(m.free is None and m.rate == "" for m in zcode._MODELS)
