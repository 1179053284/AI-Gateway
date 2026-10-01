"""v2.0 §17 领取三段式与激活事件单元测试（tech-design §19 M5-1 / `14` §③）。

覆盖：preview 取最高优先级 plan、验证码缺失时**明确报错**（不静默）、
幂等码解析、**激活事件体 16 字段**（施工级数字）。
"""

from __future__ import annotations

import pytest

from model_gateway.upstream.zcode import claim as C


# ---------- preview：取 priority 最高的 plan ----------

def test_pick_plan_highest_priority():
    body = {"data": {"plans": [
        {"plan_id": "p-low", "priority": 1},
        {"plan_id": "p-high", "priority": 9},
        {"plan_id": "p-mid", "priority": 5},
    ]}}
    assert C.pick_plan(body).plan_id == "p-high"


def test_pick_plan_empty_returns_none():
    assert C.pick_plan({"data": {"plans": []}}) is None
    assert C.pick_plan({}) is None
    assert C.pick_plan({"data": {}}) is None


def test_pick_plan_skips_entries_without_id():
    body = {"data": {"plans": [{"priority": 99}, {"plan_id": "ok", "priority": 1}]}}
    assert C.pick_plan(body).plan_id == "ok"


# ---------- claim 响应解析 ----------

def test_parse_claim_success():
    out = C.parse_claim({"code": 0, "data": {"plan": {"plan_id": "p1", "ends_at": "T"}}})
    assert out.code == 0 and out.plan_id == "p1"


def test_parse_claim_already_claimed():
    assert C.parse_claim({"code": 1003, "msg": "该套餐已经领取过"}).code == 1003


def test_parse_claim_quota_exhausted_carries_next_at():
    """`1005` 回带 `data.plan.ends_at` 作**下次可领时间**（天然冷却依据，`14` §3.2）。"""
    out = C.parse_claim({"code": 1005, "data": {"plan": {"ends_at": "2026-09-27T00:00:00Z"}}})
    assert out.code == 1005
    assert out.next_at == "2026-09-27T00:00:00Z"


def test_parse_claim_non_dict_is_minus_one():
    out = C.parse_claim("nope")  # type: ignore[arg-type]
    assert out.code == -1 and out.message


def test_business_codes_are_the_documented_ones():
    """码值必须与调研一致（`14` §3.2）—— 写错会判错 `already_done`。"""
    assert C.CODE_OK == 0
    assert C.CODE_ALREADY_CLAIMED == 1003
    assert C.CODE_QUOTA_EXHAUSTED == 1005
    assert C.CODE_ACTIVITY_ENDED == 1002
    # 🔴 3007（验证码失败）/ 3001（参数错）在调研里有记录，但 `classify()` 用不到它们
    #    —— 未列常量、按**行为**钉住："文档未穷举的码一律归 failed"（原先这里断一个
    #    只被本用例引用的死常量，等于用测试替死代码续命）
    from model_gateway.ops.builtin.zcode_claim import classify

    assert classify(C.parse_claim({"code": 3007, "msg": "验证码校验失败"})) == (
        "failed", "验证码校验失败")
    assert classify(C.parse_claim({"code": 3001})) == ("failed", "业务码 3001")


# ---------- 激活事件体：16 字段（施工级） ----------

def test_activation_event_has_exactly_sixteen_fields():
    """🔴 **固定 16 字段**（`claim.rs:158-177` 逐键枚举）。

    原调研稿曾写 14 —— 按错的数字实现会**缺字段导致服务端拒绝**。
    """
    body = C.build_activation_event(element="app_daily_active",
                                    user_id="u1", device_mid="mid-1")
    assert len(body) == 16
    assert C.event_body_is_complete(body) is True
    assert set(body) == set(C.EVENT_KEYS)


def test_activation_event_key_set():
    """16 个键的**确切清单**（少一个都会被服务端拒）。"""
    expected = {
        "event_id", "client_timezone", "client_language", "element_name", "event_region",
        "event_type", "event_text", "event_extra_detail", "user_id", "screen_resolution",
        "app_version", "device_os_category", "device_os_version", "device_mid", "mac_id",
        "marketing_params",
    }
    assert set(C.EVENT_KEYS) == expected
    assert len(C.EVENT_KEYS) == 16


def test_activation_event_values():
    body = C.build_activation_event(element="app_launch", user_id="u9", device_mid="mid-9")

    assert body["element_name"] == "app_launch"
    assert body["event_region"] == "app"
    assert body["event_type"] == "view"
    assert body["event_text"] == ""
    assert body["event_extra_detail"] == {}
    assert body["user_id"] == "u9"
    assert body["device_mid"] == "mid-9"
    assert body["mac_id"] == ""
    assert body["marketing_params"] == "{}"
    assert body["screen_resolution"] == C.SCREEN_RESOLUTION


def test_activation_event_id_is_unique_per_call():
    a = C.build_activation_event(element="x", user_id="u", device_mid="m")
    b = C.build_activation_event(element="x", user_id="u", device_mid="m")
    assert a["event_id"] != b["event_id"]


def test_event_completeness_check_rejects_missing_key():
    body = C.build_activation_event(element="x", user_id="u", device_mid="m")
    body.pop("mac_id")
    assert C.event_body_is_complete(body) is False


# ---------- 验证码：未配置时**不静默**（§16.5）----------

async def test_missing_captcha_solver_raises_with_user_guidance():
    """🔴 未配置住宅代理 → **明确报错并给用户落点**（不静默失败，§16.5）。

    ⚠️ 本轮修正（验收 IX S-1）：客户端**不再猜原因**。
    上一轮这里恒抛"未配置住宅代理"，而真实原因是求解器压根没接上 ——
    配好代理的用户照提示去查代理，永远查不出问题。**"为什么不可用"由知道的一方（求解器）说。**
    """
    client = C.ZCodeClaimClient("http://127.0.0.1:9", "jwt")

    with pytest.raises(C.CaptchaUnavailable) as e:
        await client.solve_captcha()

    msg = str(e.value)
    assert "求解器未接入" in msg
    assert "未配置住宅代理" not in msg, "装配错误不得谎称是用户的配置问题"
    assert "--manual" in msg                   # 仍要给出路


async def test_manual_hint_does_not_loop():
    """🔴 已加 `--manual` 时**不得再叫用户加 `--manual`**（验收发现的文案循环）。"""
    client = C.ZCodeClaimClient("http://127.0.0.1:9", "jwt")

    with pytest.raises(C.CaptchaUnavailable) as e:
        await client.solve_captcha(manual=True)

    msg = str(e.value)
    assert "已指定 --manual" in msg
    # 不得重复建议加 --manual
    assert "也可加 --manual" not in msg


def test_config_key_actually_exists():
    """🔴 回归护栏：提示里提到的配置键**必须真实存在**于 schema。"""
    from model_gateway.config.schemas import GatewayConfig

    cfg = GatewayConfig()
    assert hasattr(cfg, "zcode")
    assert hasattr(cfg.zcode, "proxy")
    assert hasattr(cfg.zcode, "plan_base_url")
    assert hasattr(cfg.zcode, "claim_interval_seconds")


def test_effective_proxy_prefers_config_then_env(monkeypatch):
    """`effective_proxy()`：配置项优先，其次环境变量。"""
    from model_gateway.config.schemas import ZcodeUpstreamConfig

    monkeypatch.setenv("MGW_ZCODE_PROXY", "http://env:8080")
    assert ZcodeUpstreamConfig().effective_proxy() == "http://env:8080"
    assert ZcodeUpstreamConfig(proxy="http://cfg:9090").effective_proxy() == "http://cfg:9090"


async def test_captcha_solver_is_injectable():
    client = C.ZCodeClaimClient("http://127.0.0.1:9", "jwt",
                                captcha_solver=lambda: _async("param-xyz"))
    assert await client.solve_captcha() == "param-xyz"


async def _async(v):
    return v


# ---------- 请求头（13 个头的子集）----------

def test_headers_include_auth_and_device_mid():
    h = C._headers("tok", "mid-1")
    assert h["Authorization"] == "Bearer tok"
    assert h["X-Device-Mid"] == "mid-1"
    assert h["X-Platform"] == "darwin"
    assert "X-Client-Timezone" in h


def test_headers_omit_device_mid_when_absent():
    assert "X-Device-Mid" not in C._headers("tok", "")


def test_timezone_format():
    tz = C._tz()
    assert tz.startswith("UTC+") or tz.startswith("UTC-")
