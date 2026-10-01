"""M6 面板修复轮-2 · ops 侧单测（A-2 单一桥接 / A-3 retryable 口径）。

对应 `docs/changes/reviews/m6-panel-eng-a.md` 的 A-2（`ClaimOutcome→OpResult` 两处桥接
= 双账风险）与 A-3（`zcode_claim` 全异常 blanket `retryable=True` 与 7 产品两套口径）。

本文件的两条硬要求：

- **A-2**：归一化规则只住一处（`ops/bridge.py::outcome_to_op_result`）——用例先钉住
  "两处旧实现确实产出不同结果"（双账证据），再钉住多产品 `claim` 执行体真的经该桥接
  （monkeypatch 桥接为间谍函数，绕开即红）。
- **A-3**：业务异常 → `retryable=False` 且**批量执行器不重试**；传输异常 → `True` 且
  按 `MAX_ATTEMPTS_PER_ACCOUNT` 退避重试。撤修复对照（把判据换回"全异常可重试"）
  在同一文件里复现旧行为。
"""

from __future__ import annotations

import httpx

from model_gateway.accounts import store as accounts_store
from model_gateway.accounts.types import ClaimOutcome
from model_gateway.ops import bridge
from model_gateway.ops import runner as runner_mod
from model_gateway.ops.base import OpResult
from model_gateway.ops.builtin import OPERATIONS, product_claim, product_hooks, zcode_claim

CLAIM_OP = OPERATIONS[product_claim.OPERATION_ID]


async def _no_sleep(_s: float) -> None:
    return None


# ============ A-2：单一桥接（`ops/bridge.py`）============

def test_bridge_rule_table_covers_all_four_categories_and_the_type_guard():
    """🔴 桥接 = `ClaimOutcome` → `OpResult` 的**唯一归一化规则**（四类 + 类型守卫）。"""
    for category in ("success", "already_done", "inactive"):
        res = bridge.outcome_to_op_result(
            ClaimOutcome(category=category, detail="d", retryable=True), "acct")
        assert (res.account, res.category, res.detail) == ("acct", category, "d")
        assert res.retryable is None, f"{category}（非 failed）不得带 retryable 声明"

    assert bridge.outcome_to_op_result(
        ClaimOutcome(category="failed", detail="网络类", retryable=True),
        "acct").retryable is True
    assert bridge.outcome_to_op_result(
        ClaimOutcome(category="failed", detail="业务码 3007"),
        "acct").retryable is False          # 默认 False = 不重试（§22.3 加字段纪律）

    junk = bridge.outcome_to_op_result(object(), "acct")   # 钩子返回垃圾对象
    assert junk.category == "failed" and "类型异常" in junk.detail


def test_two_former_bridges_disagreed_and_are_now_one_rule():
    """🔴 A-2 红证：两处旧实现对**同一** outcome 产出不同 `retryable`（双账）。

    旧落点（逐行复刻，见 eng-a 报告）：
    - `ops/builtin/product_claim.py`（旧 130-132 行）：非 failed 归 `None`；
    - `api/admin_accounts.py::_claim_once`（旧 566-570 行）：原样透传。
    同一 `already_done + retryable=True` 在两条路径上分别得到 `None` / `True` ——
    收敛到 `ops/bridge.py` 后只允许一个答案（`None`，本行断言即钉死）。
    """
    outcome = ClaimOutcome(category="already_done", detail="今天已签到", retryable=True)

    def _old_ops_side(o: ClaimOutcome) -> OpResult:
        return OpResult("acct", o.category, o.detail,
                        retryable=(bool(o.retryable) if o.category == "failed" else None))

    def _old_api_side(o: ClaimOutcome) -> OpResult:
        return OpResult("acct", o.category, o.detail, retryable=o.retryable)

    assert _old_ops_side(outcome).retryable is None
    assert _old_api_side(outcome).retryable is True          # ← 双账：同一输入两种产出
    assert _old_ops_side(outcome).retryable != _old_api_side(outcome).retryable
    # 收敛后（唯一口径）：
    assert bridge.outcome_to_op_result(outcome, "acct").retryable is None


async def test_product_claim_routes_through_the_shared_bridge(monkeypatch):
    """🔴 A-2 结构红证：多产品 `claim` 执行体**必须**经 `ops/bridge.py`。

    把桥接换成间谍函数：仍在本地自写归一化（旧形态）时本用例必红（间谍零调用）。
    """
    accounts_store.commit_login("buddy", "acct-1", {"access_token": "t0ken"}, {})
    seen: list[str] = []
    real = bridge.outcome_to_op_result          # 先取原实现（spy 里不能再查模块属性）

    def spy(outcome, account):
        seen.append(account)
        return real(outcome, account)

    monkeypatch.setattr(bridge, "outcome_to_op_result", spy)

    async def hook(cred, meta, *, precheck):
        return ClaimOutcome(category="success", detail="已触发每日额度")

    monkeypatch.setattr(product_hooks, "hook_of", lambda product, hook_name: hook)
    res = await product_claim.claim("acct-1")
    assert (res.category, res.detail) == ("success", "已触发每日额度")
    assert seen == ["acct-1"], "多产品 claim 没走 ops/bridge.py（本地又写了一份归一化？）"


# ============ A-3：zcode_claim 的 retryable 与 7 产品同一把尺 ============

class _RaisingClient:
    """假 zcode 客户端：`preview()` 按注入异常抛错（装配/凭据走真，见 `_zcode_stub`）。"""

    def __init__(self, exc: BaseException):
        self.exc = exc
        self.attempts = 0
        self.closed = False

    async def preview(self):
        self.attempts += 1
        raise self.exc

    async def aclose(self):
        self.closed = True


def _zcode_stub(monkeypatch, exc: BaseException) -> _RaisingClient:
    """凭据换成假值、客户端换成 `_RaisingClient`（其余装配走生产实现）。

    ⚠️ 同时把 10s 节流闸门关掉（`throttle_wait_ms → 0`）：`claim()` 每次都会
    `mark_called()`，重试路径之间会真睡满节流窗口（本文件是判据测试，不测节流）。
    """
    from model_gateway.upstream.zcode import quota as zq

    monkeypatch.setattr(zq.CooldownManager, "throttle_wait_ms", lambda self: 0)
    monkeypatch.setattr(zcode_claim, "_credentials_of",
                        lambda account: ("jwt-fake", "mid-fake", "42"))
    return _RaisingClient(exc)


async def test_business_exception_is_not_retryable_and_not_retried(monkeypatch):
    """🔴 A-3 红证：zcode 业务异常（非传输类）→ `retryable=False`，批量执行器**不重试**。

    撤修复（旧 blanket `retryable=True`）→ 本用例 `attempts` 变成
    `MAX_ATTEMPTS_PER_ACCOUNT`（对注定失败的业务错误退避重试 3 轮）。
    """
    client = _zcode_stub(monkeypatch, ValueError("业务码 3007：验证码失败"))
    res = await runner_mod._run_one(
        "zc-1", lambda a: zcode_claim.claim(a, client_factory=lambda: client),
        sleep=_no_sleep)

    assert res.category == "failed"
    assert res.retryable is False, "业务异常被声明成可重试（旧 blanket 口径残留在）"
    assert client.attempts == 1, f"业务失败被重试了 {client.attempts} 次（退避只留给网络类）"
    assert not res.detail.startswith("network:"), "非传输类异常不得被打上 network: 前缀"
    assert client.closed is True                # 失败路径仍必须关客户端（防泄漏）


async def test_transport_exception_stays_retryable(monkeypatch):
    """正向对照：传输类异常（httpx 网络错误）仍是 `retryable=True` 且真的退避重试。"""
    client = _zcode_stub(monkeypatch, httpx.ConnectError("connection refused"))
    res = await runner_mod._run_one(
        "zc-1", lambda a: zcode_claim.claim(a, client_factory=lambda: client),
        sleep=_no_sleep)

    assert res.retryable is True
    assert client.attempts == runner_mod.MAX_ATTEMPTS_PER_ACCOUNT, \
        f"传输类失败没有按退避序列重试（{client.attempts} 次）"
    assert res.detail.startswith("network:")    # 旧调用方的可读约定保留


async def test_revert_to_the_blanket_rule_reproduces_the_old_retry(monkeypatch):
    """撤修复对照（红证成立性）：判据换回"全异常可重试"→ 业务异常被重试 3 轮。"""
    monkeypatch.setattr(zcode_claim.product_hooks, "is_transport_failure", lambda e: True)
    client = _zcode_stub(monkeypatch, ValueError("业务码 3007：验证码失败"))
    res = await runner_mod._run_one(
        "zc-1", lambda a: zcode_claim.claim(a, client_factory=lambda: client),
        sleep=_no_sleep)

    assert res.retryable is True and client.attempts == runner_mod.MAX_ATTEMPTS_PER_ACCOUNT, \
        "撤修复后未复现旧行为 —— 上一条用例的红证不成立（判据没被真正钉住）"
