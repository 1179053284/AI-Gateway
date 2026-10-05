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
from model_gateway.upstream.zcode import quota as zq


class _Snap:
    def __init__(self, state="", reason="", remaining=None):
        self.state, self.reason, self.remaining = state, reason, remaining


# ---------- ① 翻译：只有 no_plan 算否认 ----------

def test_only_no_plan_denies_entitlement():
    assert zq.entitled_from_snapshot(_Snap("unknown", "no_plan")) is False


def test_positive_states_restore_entitlement():
    assert zq.entitled_from_snapshot(_Snap("available", "")) is True
    assert zq.entitled_from_snapshot(_Snap("exhausted", "")) is True


def test_unreadable_never_denies():
    """「没查到」四种 reason 一律 `None`（不动位）—— 一次网络抖动不许封掉整条通道。"""
    for reason in ("unreachable", "circuit", "expired", "no_credentials", "no_identity", ""):
        assert zq.entitled_from_snapshot(_Snap("unknown", reason)) is None, reason


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
