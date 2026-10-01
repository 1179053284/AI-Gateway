"""§22.6 多产品 `claim` operation 的判据（修复轮 Fix-δ：R4-BL-3 / R1-F2）。

覆盖（全部**无网络**：假钩子，真账号目录/真 `hook_meta`）：

- 参与方**从能力矩阵推导**（红证：workbuddy / cline / raccoon 不进一轮）；
- 缺省枚举**跨产品**（红证：原实现只看 zcode 账号 → 新产品"注册了没人跑"）；
- 执行体的第二道守卫：未登记能力的产品即使被直接调用也不打产品钩子；
- 四类结果出口**不变**（`ClaimOutcome` → `OpResult` 1:1，detail 原样）；
- **重试判据结构化**（F2 红证）：网络类退避重试、业务码不重试，且判据与中文文案无关
  （断言用例里的文案在旧判据 `_looks_retryable` 下仍为 False —— 旧实现下本条必红）；
- `zcode_claim` 兼容别名 = 多产品 `claim` 收窄到 zcode 的**同一执行体**，
  `--manual` / `runtime` 原样到达（Q28-⑧ CLI 契约）；
- `precheck` 声明与 `api/admin_accounts._PRECHECK` 逐项相等（防两份分叉）。
"""

from __future__ import annotations

import httpx

from model_gateway.accounts import registry
from model_gateway.accounts import store as accounts_store
from model_gateway.accounts.types import ClaimOutcome
from model_gateway.ops import runner as runner_mod
from model_gateway.ops.base import OpResult
from model_gateway.ops.builtin import OPERATIONS, product_claim, product_hooks, zcode_claim

CLAIM_OP = OPERATIONS[product_claim.OPERATION_ID]

#: R1-F2 实测过的**真实产品文案**（旧判据 `_looks_retryable` 对它返回 False）
NETWORK_TEXT = "签到请求网络错误：ConnectError: refused"


async def _fake_sleep(_s: float) -> None:
    return None


def _seed(product: str, name: str) -> None:
    """落一个真账号（`meta.json` 是"算不算账号"的判据）；数据目录已被 conftest 隔离到 tmp。"""
    accounts_store.commit_login(product, name, {"access_token": "t0ken"}, {})


def _install_hook(monkeypatch, fn) -> None:
    """把产品钩子取用点换成假钩子（`product_hooks.hook_of` 是两个动作共用的唯一取用点）。"""
    monkeypatch.setattr(product_hooks, "hook_of", lambda product, hook: fn)


# ---------- 参与方：从能力矩阵推导 ----------

def test_claim_participants_derive_from_the_capability_matrix():
    """🔴 参与方 = 所有 `checkin=True` 的产品（**从表推导**，不硬编码渠道字面量）。"""
    expected = tuple(pid for pid in registry.PRODUCT_IDS
                     if registry.PRODUCTS[pid].capabilities.checkin)
    assert product_claim.SUPPORTED_PRODUCTS == expected
    assert "zcode" in expected                       # 含 zcode（§22.6 收敛后 claim 覆盖它）
    for pid in ("workbuddy", "cline", "raccoon"):
        assert registry.PRODUCTS[pid].capabilities.checkin is False
        assert pid not in expected
    assert CLAIM_OP.supported_products == product_claim.SUPPORTED_PRODUCTS


async def test_round_excludes_products_without_checkin(monkeypatch):
    """🔴 红证（参与方推导）：无签到端点产品的账号**不进** `claim` 的一轮（不报错、不误跑）。"""
    calls: list[str] = []

    async def spy(account, **kw):
        calls.append(account)
        return OpResult(account, "success")

    mapping = {"wb-1": "workbuddy", "rc-1": "raccoon"}
    report = await runner_mod.run_once(
        operation=CLAIM_OP, claim=spy, accounts=list(mapping),
        product_of=lambda a: mapping[a], sleep=_fake_sleep)

    assert calls == [], "checkin=False 的产品被跑了"
    assert report.no_participants is True and report.success == []
    assert len(report.skipped) == 2
    assert all("不在" in s for s in report.skipped)   # 跳过原因可读（谁不支持、支持什么）


async def test_default_enumeration_is_cross_product():
    """🔴 红证（枚举面）：`accounts=None` 时按动作声明的产品**跨产品枚举**。

    原实现写死 zcode 账号枚举 → 即便 operation 声明了全部产品，批量路径也看不见
    新产品账号（R4-BL-3 的"最后一公里"）。
    """
    _seed("buddy", "buddy-1")
    _seed("trae", "trae-1")
    _seed("workbuddy", "wb-1")                       # 无签到能力 → 不参与，也不该被枚举进来

    calls: list[str] = []

    async def spy(account, **kw):
        calls.append(account)
        return OpResult(account, "success")

    report = await runner_mod.run_once(operation=CLAIM_OP, claim=spy, accounts=None,
                                       sleep=_fake_sleep)

    assert sorted(calls) == ["buddy-1", "trae-1"], f"跨产品枚举没生效：{calls}"
    assert sorted(report.success) == ["buddy-1", "trae-1"]


async def test_exec_body_refuses_unregistered_capability(monkeypatch):
    """执行体第二道守卫：绕过 `run_once` 过滤直接调用，也不打产品钩子（不误跑）。"""
    monkeypatch.setattr(runner_mod, "product_of_account", lambda a: "raccoon")

    def _must_not_be_called(*_a, **_k):
        raise AssertionError("未登记签到能力却调了产品钩子")

    monkeypatch.setattr(product_hooks, "hook_of", _must_not_be_called)
    res = await product_claim.claim("rc-1")
    assert res.category == "inactive" and "checkin=False" in res.detail


# ---------- 四类结果出口不变 ----------

async def test_outcomes_pass_through_the_four_categories(monkeypatch):
    """四类出口**不变**：钩子 `ClaimOutcome` → `OpResult` 1:1（detail 原样带出）。"""
    _seed("buddy", "acct-1")
    state: dict = {}

    async def hook(cred, meta, *, precheck):
        state["account"] = meta.get("account")       # §22.3 补入① 锚字段
        return ClaimOutcome(category=state["category"], detail=state["detail"])

    _install_hook(monkeypatch, hook)
    for category, detail in (("success", "已触发每日额度"),
                             ("already_done", "今天已签到"),
                             ("inactive", "签到活动未开启"),
                             ("failed", "业务码 3007：验证码失败")):
        state.update(category=category, detail=detail)
        res = await product_claim.claim("acct-1")
        assert (res.category, res.detail) == (category, detail)
    assert state["account"] == "acct-1"


# ---------- 重试判据：结构化（F2 红证）----------

async def test_network_class_failure_retries_but_business_code_does_not(monkeypatch):
    """🔴 F2 红证：批量执行器按**结构化声明**退避重试，不再猜中文文案。

    用例前提也钉在断言里：这条真实产品文案在旧判据下是 False —— 也就是说，
    在"猜文案"的实现上本用例必红（网络类失败的重试计数会是 1）。
    """
    _seed("buddy", "acct-1")
    slept: list[float] = []

    async def _sleep(s: float) -> None:
        slept.append(s)

    calls: list[str] = []

    async def net_hook(cred, meta, *, precheck):
        calls.append("net")
        return ClaimOutcome(category="failed", detail=NETWORK_TEXT, retryable=True)

    _install_hook(monkeypatch, net_hook)
    await runner_mod._run_one("acct-1", lambda a: product_claim.claim(a), sleep=_sleep)

    assert runner_mod._looks_retryable(NETWORK_TEXT) is False, "用例前提：文案对不上旧前缀判据"
    assert len(calls) > 1, "网络类失败（结构化声明 retryable=True）没有被退避重试"
    assert slept, "退避序列一秒都没睡"

    calls.clear()
    slept.clear()

    async def biz_hook(cred, meta, *, precheck):
        calls.append("biz")
        return ClaimOutcome(category="failed", detail="业务码 3007：验证码失败")

    _install_hook(monkeypatch, biz_hook)
    res = await runner_mod._run_one("acct-1", lambda a: product_claim.claim(a), sleep=_sleep)

    assert res.category == "failed" and res.retryable is False
    assert calls == ["biz"], "业务码失败被重试了（退避只留给网络/5xx）"
    assert slept == []


async def test_escaped_transport_exception_is_declared_retryable(monkeypatch):
    """钩子没折叠、让传输异常逃出来 → 执行体按**异常类**声明可重试；其余异常不重试。"""
    _seed("buddy", "acct-1")
    calls: list[str] = []

    async def net_hook(cred, meta, *, precheck):
        calls.append("net")
        raise httpx.ConnectError("connection refused")

    _install_hook(monkeypatch, net_hook)
    res = await runner_mod._run_one("acct-1", lambda a: product_claim.claim(a),
                                    sleep=_fake_sleep)
    assert res.category == "failed" and res.retryable is True
    assert len(calls) == runner_mod.MAX_ATTEMPTS_PER_ACCOUNT

    calls.clear()

    async def bug_hook(cred, meta, *, precheck):
        calls.append("bug")
        raise ValueError("响应结构变了")

    _install_hook(monkeypatch, bug_hook)
    res = await runner_mod._run_one("acct-1", lambda a: product_claim.claim(a),
                                    sleep=_fake_async_boom)
    assert res.retryable is False
    assert calls == ["bug"], "非传输类异常被重试了（重试只留给网络/5xx）"


async def _fake_async_boom(_s: float) -> None:
    raise AssertionError("非网络类失败不该退避睡眠")


# ---------- `zcode_claim` 兼容别名（Q28-⑧）----------

def test_zcode_claim_alias_is_the_claim_op_narrowed_to_zcode():
    """§22.6：别名 = 多产品 `claim` 的**同一执行体** + 收窄声明；id / 标题契约不变。"""
    alias = OPERATIONS[zcode_claim.OPERATION_ID]
    assert alias.id == zcode_claim.OPERATION_ID == "zcode_claim"
    assert alias.run is CLAIM_OP.run, "别名没有指向多产品 claim 的执行体"
    assert alias.supported_products == ("zcode",)
    assert product_claim._CLAIM_DIRECT["zcode"] is zcode_claim.claim
    assert set(OPERATIONS) == {"claim", "query_balance", "zcode_claim"}


async def test_alias_keeps_manual_and_runtime_for_the_zcode_executor(monkeypatch):
    """🔴 CLI 契约（Q28-⑧）：`--manual` 与 `runtime`（§17 熔断回写）必须原样到达 zcode 执行器。"""
    captured: dict = {}

    async def spy(account, *, manual=False, runtime=None):
        captured.update(account=account, manual=manual, runtime=runtime)
        return OpResult(account, "success")

    monkeypatch.setattr(runner_mod, "product_of_account", lambda a: "zcode")
    monkeypatch.setitem(product_claim._CLAIM_DIRECT, "zcode", spy)
    sentinel = object()
    res = await OPERATIONS[zcode_claim.OPERATION_ID].run("zc-1", manual=True, runtime=sentinel)

    assert res.category == "success"
    assert captured == {"account": "zc-1", "manual": True, "runtime": sentinel}


# ---------- precheck 声明只此一份语义 ----------

def test_precheck_table_matches_the_admin_endpoint():
    """`precheck` per-product 声明两处必须**逐项相等**（§22.6 / `20 B6`；防两份分叉）。"""
    from model_gateway.api import admin_accounts

    assert product_claim._PRECHECK == admin_accounts._PRECHECK
    assert product_claim._PRECHECK.get("trae") is True     # trae 必须预检（幂等只能靠 status）
