"""zcode **承接资格闸门**的单元测试（2026-10-05 用户裁定：没额度的号不该进可用调用范围）。

判据分三层，缺一层就会漏：
① 上游答复 → 资格位的**翻译**（`entitled_from_snapshot`）；
② 资格位 → 派发**闸门**（`available()` / `reserve_quota()` / 共享池粒度）；
③ 风控 4xx 的**分类**（`RISK_CONTROL_TYPE` → RETRYABLE，且不抢 401/404/429/408 的既有归属）。
"""

from __future__ import annotations

from model_gateway.core.errors import (RISK_CONTROL_TYPE, ErrorClass, ErrorClassifier,
                                       UpstreamError)
from model_gateway.core.resources import QuotaPool, ResourceState, ResourceManager
from model_gateway.upstream.zcode import out as zout
from model_gateway.core import quota_policy
from model_gateway.upstream.zcode import quota as zq


class _Snap:
    def __init__(self, state="", reason="", remaining=None):
        self.state, self.reason, self.remaining = state, reason, remaining


# ---------- ① 翻译：只有 no_plan 算否认 ----------

def test_only_no_plan_denies_entitlement():
    assert quota_policy.entitled_for(_Snap("unknown", "no_plan")) is False


def test_positive_states_restore_entitlement():
    assert quota_policy.entitled_for(_Snap("available", "")) is True
    assert quota_policy.entitled_for(_Snap("exhausted", "")) is True


def test_unreadable_never_denies():
    """「没查到」四种 reason 一律 `None`（不动位）—— 一次网络抖动不许封掉整条通道。"""
    for reason in ("unreachable", "circuit", "expired", "no_credentials", "no_identity", ""):
        assert quota_policy.entitled_for(_Snap("unknown", reason)) is None, reason


# ---------- ② 闸门：按 rid 共享、进 available 与预留两条路 ----------
# 🔴 一律经 `rebuild`（生产构造路径）建运行态：手工拼 `ResourceState` 会拿到一个
# 与 `manager.quotas[rid]` **不是同一个对象**的池，那样的断言绿了也不证明生产行为
# （本轮第一版就是这么写的，`set_entitled` 返回 1/2 却没真的挡住派发 = 假阳性）。

def _mgr_two_mappings():
    from model_gateway.config.schemas import AppConfig

    cfg = AppConfig.model_validate({
        "resources": [{"id": "res-a", "name": "资源A", "vendor": "ZCode", "account": "a",
                       "product": "zcode", "account_ref": "a", "protocol": "anthropic",
                       "preset": "", "base_url": "https://x.example/anthropic",
                       "api_key": "", "enabled": True, "access_mode": "plan"}],
        "models": [{"name": "glm-5.3-flash", "endpoint": "chat", "enabled": True,
                    "resources": [{"resource": "res-a", "model": "GLM-5.3-Flash", "enabled": True},
                                  {"resource": "res-a", "model": "GLM-5.3", "enabled": True}]}]})
    mgr = ResourceManager()
    mgr._credential_fp = lambda r: ""
    mgr.rebuild(cfg)
    return mgr, sorted(mgr.registry.values(), key=lambda x: x.vendor_model)


def test_default_pool_is_permissive():
    """缺省必须宽松：没有任何上游证据时不许一接入就被封。"""
    assert QuotaPool().entitled is True


def test_set_entitled_blocks_dispatch_and_reservation():
    mgr, states = _mgr_two_mappings()
    st = states[0]
    assert st.available() is True
    assert mgr.reserve_quota(st) is True
    mgr.release_quota(st)

    assert mgr.set_entitled("res-a", False) == len(states)
    assert st.quota.entitled is False
    assert st.available() is False            # 选路侧
    assert mgr.reserve_quota(st) is False     # 原子闸门侧（防有路径绕过 available）


def test_entitlement_is_shared_per_rid_not_per_mapping():
    """共享池粒度 = rid：同账号两条映射必须同一个答案（否则"这条有资格那条没有"是第三套真相）。"""
    mgr, states = _mgr_two_mappings()
    assert states[0].quota is states[1].quota
    mgr.set_entitled("res-a", False)
    assert [s.available() for s in states] == [False, False]


def test_recover_flips_back():
    mgr, states = _mgr_two_mappings()
    mgr.set_entitled("res-a", False)
    assert mgr.set_entitled("res-a", True) == len(states)
    assert [s.available() for s in states] == [True, True]


# ---------- ③ 分类：风控归一化，但不抢既有归属 ----------

_cl = ErrorClassifier()


def _norm(status, body):
    return _cl.classify(zout._as_risk_control(
        UpstreamError(f"upstream {status}", status_code=status, error_body=body)))


def test_risk_control_400_is_retryable():
    assert _norm(400, '{"code":3012,"msg":"unusual activity"}') is ErrorClass.RETRYABLE


def test_captcha_reuse_3007_is_retryable():
    assert _norm(400, '{"code":3007,"msg":"captcha param used"}') is ErrorClass.RETRYABLE


def test_405_is_risk_signal():
    assert _norm(405, '{"code":0}') is ErrorClass.RETRYABLE


def test_plain_400_stays_bad_request():
    """真正的客户端错误**不许**被顺手放宽（FR-3.13 不变）。"""
    assert _norm(400, '{"error":{"type":"invalid_request_error"}}') is ErrorClass.BAD_REQUEST
    assert _norm(400, '{"code":0,"msg":"model name is required"}') is ErrorClass.BAD_REQUEST


def test_401_404_429_408_keep_their_own_class():
    assert _norm(401, '{"code":3012,"msg":"unusual activity"}') is ErrorClass.AUTH
    assert _norm(404, '{"code":3012}') is ErrorClass.NOT_FOUND
    assert _norm(429, '{"code":3012}') is ErrorClass.QUOTA
    assert _norm(408, '{"code":3012}') is ErrorClass.CANCELED


def test_risk_type_is_the_normalized_marker():
    e = zout._as_risk_control(UpstreamError("upstream 400", status_code=400,
                                            error_body='{"code":3012,"msg":"unusual activity"}'))
    assert e.error_type == RISK_CONTROL_TYPE


# ---------- ④ 量纲阈值（用户 2026-10-05 补的规则：积分 <50、token <1万 ⇒ 自动剔出） ----------

def _pkg(name, unit, remaining, active=True):
    return {"name": name, "unit": unit, "remaining": remaining, "active": active}


def _s(items=(), state="available", reason=""):
    return type("S", (), {"items": tuple(items), "state": state,
                          "reason": reason, "remaining": None})()


def test_token_floor_is_10000():
    """token 制：`< 10000` 剔出，`== 10000` 留（阈值是"少于"，不是"少于等于"）。"""
    assert quota_policy.entitled_for(_s([_pkg("GLM-5.3-Flash", "token", 9_999)])) is False
    assert quota_policy.entitled_for(_s([_pkg("GLM-5.3-Flash", "token", 10_000)])) is True
    assert quota_policy.entitled_for(_s([_pkg("GLM-5.3-Flash", "token", 1_000_000)])) is True


def test_credit_floor_is_50_and_accepts_floats():
    """积分制：`< 50` 剔出。实盘积分**是小数**（`trae 472.1868`、`lobsterai 293.94`），
    所以阈值比较不许假定整数。"""
    assert quota_policy.entitled_for(_s([_pkg("资源包", "credits", 49.99)])) is False
    assert quota_policy.entitled_for(_s([_pkg("资源包", "credits", 50)])) is True
    assert quota_policy.entitled_for(_s([_pkg("新用户赠送", "积分", 293.94)])) is True
    assert quota_policy.entitled_for(_s([_pkg("Bonus Pack", "credit", 0.0)])) is False


def test_any_package_above_floor_keeps_the_account():
    """多包时 = **至少一个没触底**就保留（消耗按上游自己的包序扣，本地不猜哪个先见底）。"""
    mixed = [_pkg("快见底", "token", 5_000), _pkg("还有积分", "credits", 60)]
    assert quota_policy.entitled_for(_s(mixed)) is True
    all_low = [_pkg("token 见底", "token", 500), _pkg("积分见底", "积分", 12)]
    assert quota_policy.entitled_for(_s(all_low)) is False


def test_unknown_unit_never_gets_a_threshold():
    """认不出量纲（空串 / 次数 / 美元）**不设阈值** —— 拿 50 去卡一个单位是"次"的号属于编造事实。
    实盘形状：`cline` 的「余额」项 `unit=""`、`remaining=490189.0`。

    🔴 阈值没有意见时**回落到三态**那条判据（不是"一律放行"也不是"一律剔出"）：
    上游说 `available` ⇒ 有资格；上游根本没说话（`unreachable`）⇒ 闸门一位都不动。
    """
    only_unknown = [_pkg("余额", "", 0.5)]
    assert quota_policy.entitled_for(_s(only_unknown, state="available")) is True
    assert quota_policy.entitled_for(_s(only_unknown, state="unknown",
                                        reason="unreachable")) is None


def test_negative_balance_drains_regardless_of_unit():
    """🔴 P2-6（2026-10-11）：**负余量（透支）与量纲无关** —— 实盘 cline-8881b795 的
    余额包 `{remaining: -33270.0, unit: ""}` 旧逻辑因"认不出量纲 ⇒ 无权判定"落到三态
    `exhausted=True`，闸门开着放行、靠上游 403 ENTITLEMENT_ERROR 兜底白跑往返。
    负数在任何量纲下都不可能达标 ⇒ 直接计触底；`reason_of` 要把这件事说成
    "负余量"而不是沉默。0 与正数仍不判（无换算依据不编造，宽松方向不变）。"""
    drained = [_pkg("余额", "", -33270.0)]
    assert quota_policy.entitled_for(_s(drained, state="exhausted")) is False
    assert quota_policy.entitled_for(_s(drained, state="available")) is False
    assert "余量为负" in quota_policy.reason_of(_s(drained))
    # 阈值触底与负余量两种证据并存时原因分开写，不揉成一句"额度不足"
    mixed_reason = [_pkg("余额", "", -1.0), _pkg("包", "credits", 3)]
    text = quota_policy.reason_of(_s(mixed_reason))
    assert "余量为负" in text and "credits<50" in text
    # 多包时 = 至少一个活着就保留（与阈值条同判向）
    assert quota_policy.entitled_for(
        _s([_pkg("余额", "", -10.0), _pkg("包", "credits", 60)])) is True
    # 0 与正数仍走三态（负数才动位）
    assert quota_policy.entitled_for(_s([_pkg("余额", "", 0.0)], state="available")) is True


def test_remaining_none_is_not_below_floor():
    """包在、余量没给 ⇒ 这条包**无权判定**（与 `remaining_units()` 的「未知不当 0」同纪律），
    同样回落到三态。"""
    no_number = [_pkg("套餐额度", "credits", None)]
    assert quota_policy.entitled_for(_s(no_number, state="available")) is True
    assert quota_policy.entitled_for(_s(no_number, state="unknown", reason="no_plan")) is False


def test_expired_packages_do_not_contribute_nor_condemn():
    """`active=False` 的包既不贡献"还有余量"，也不参与触底判定 ——
    一个号只剩过期包 = 没有包，交给三态那条判据，不该由阈值说了算。"""
    expired = [_pkg("上月包", "token", 0, active=False), _pkg("本月包", "token", 3_000_000)]
    assert quota_policy.entitled_for(_s(expired)) is True
    only_expired = [_pkg("上月包", "token", 0, active=False)]
    assert quota_policy.entitled_for(_s(only_expired, state="available")) is True


def test_no_plan_outranks_an_untouched_floor():
    """① 上游明确说"没套餐"排在阈值前面：哪怕某个包数字上还很大，也不给资格。"""
    assert quota_policy.entitled_for(_s([_pkg("GLM", "token", 99_000_000)],
                                        state="unknown", reason="no_plan")) is False


def test_zcode_bucket_shape_uses_the_same_floors():
    """离线面/额度面另一种证据形状（`buckets` 的 `unit_type`/`available`）走同一张阈值表，
    不许出现"两种形状两套判据"。"""
    b = type("B", (), {"unit_type": "token", "available": 500, "show_name": "GLM-5.3-Flash"})()
    snap = type("S", (), {"items": (), "buckets": [b], "state": "available", "reason": ""})()
    assert quota_policy.entitled_for(snap) is False


def test_floors_are_one_source():
    """阈值只有一份常量（界面/闸门/日志读同一个数）。"""
    assert (quota_policy.TOKEN_FLOOR, quota_policy.CREDIT_FLOOR) == (10_000, 50)
    assert quota_policy.unit_floor("Tokens") == ("token", 10_000)
    assert quota_policy.unit_floor(" 积分 ") == ("credits", 50)
    assert quota_policy.unit_floor("times") is None


def test_reason_of_names_the_two_exclusion_causes_separately():
    """关闭资格的原因串必须**分档**：「上游说没套餐」与「包快见底」是两种完全不同的处置，
    混成一句"额度不足"就又回到"为什么这个号不干活还得猜"。"""
    no_plan = type("S", (), {"state": "unknown", "reason": "no_plan",
                             "items": (), "remaining": None})()
    assert "无套餐" in quota_policy.reason_of(no_plan)

    low = _s([_pkg("GLM-5.3-Flash", "token", 5_000)])
    assert quota_policy.reason_of(low) == "全部在册额度包均低于量纲阈值（token<10000）"

    credits_low = _s([_pkg("体验包", "credits", 3.0)])
    assert "credits<50" in quota_policy.reason_of(credits_low)

    # 没被关闭 ⇒ 不给原因（避免"什么都没发生却写了一句判据"）
    assert quota_policy.reason_of(_s([_pkg("体验包", "credits", 900)])) == ""


def test_closure_leaves_a_log_line(caplog):
    """一条号从可用范围消失**必须留痕**（关闭 = warn、恢复 = info）。
    额度腿是后台刷新，用户侧只会看见"这个模型不干活"；没有这一行就又是一次没有报错的失败。"""
    import logging

    mgr, states = _mgr_two_mappings()
    with caplog.at_level(logging.INFO, logger="model_gateway"):
        mgr.set_entitled("res-a", False, reason="全部在册额度包均低于量纲阈值（token<10000）")
        mgr.set_entitled("res-a", True)
    text = " | ".join(r.getMessage() for r in caplog.records)
    assert "承接资格关闭" in text and "token<10000" in text, text
    assert "承接资格恢复" in text, text
    # 同一状态重复写不留痕（一 tick 一账号一条，否则 60s 一轮会把日志刷满）
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="model_gateway"):
        mgr.set_entitled("res-a", True)
    assert "承接资格恢复" not in " ".join(r.getMessage() for r in caplog.records)
