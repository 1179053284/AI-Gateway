"""§22.6 / §22.5-6 多产品 `query_balance` operation 的判据（修复轮 Fix-δ：R1-F6）。

判据（全部**无网络**：假 `quota` 钩子，真账号目录 + 真 `ResourceManager`）：

- 参与方 = 所有 `balance=True` 的产品（**从注册表推导**）；
- 钩子快照 → ①`runtime.json` 三态缓存（`store.write_runtime`）②已物化资源 `set_quota`；
- **未知不当零**：`unknown` 既不写 0、也不把已知值洗成不限；`available` 回到"未知/不限"
  （把上一轮的 0 清掉）；`exhausted` 写 0（确定耗尽 → 预留闸门拦截）；
- 额度池只写"本产品 + 本账号"的自己人；落盘失败→ `failed`（不谎报成功）。
"""

from __future__ import annotations

from model_gateway.accounts import registry
from model_gateway.accounts import store as accounts_store
from model_gateway.accounts.types import QuotaSnapshot
from model_gateway.config.schemas import AppConfig
from model_gateway.core.resources import ResourceManager
from model_gateway.ops.builtin import query_balance, product_hooks


def _seed(product: str, name: str) -> None:
    accounts_store.commit_login(product, name, {"access_token": "t0ken"}, {})


def _runtime(resources: list[dict]) -> tuple[object, ResourceManager]:
    """真 `ResourceManager`：按配置 rebuild 后才有按 rid 共享的额度池（与生产同路径）。"""
    mgr = ResourceManager()
    cfg = AppConfig.model_validate({
        "resources": resources,
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": r["id"], "model": "vm"}
                                  for r in resources]}]})
    mgr.rebuild(cfg)

    class _RT:
        manager = mgr
        config = cfg
        resources = mgr

    return _RT, mgr


def _buddy_resource(account: str = "acct-1") -> dict:
    return {"id": "res-b", "name": "B", "product": "buddy", "account_ref": account,
            "base_url": "http://127.0.0.1:9/v1", "api_key": ""}


def _install_quota(monkeypatch, snap: QuotaSnapshot) -> None:
    async def hook(cred, meta):
        return snap

    monkeypatch.setattr(product_hooks, "hook_of", lambda product, name: hook)


# ---------- 参与方：从余额能力矩阵推导 ----------

def test_query_balance_participants_derive_from_the_balance_matrix():
    """🔴 参与方 = 所有 `balance=True` 的产品（**从表推导**；在册 10 个全 ✓，含 zcode）。"""
    expected = tuple(pid for pid in registry.PRODUCT_IDS
                     if registry.PRODUCTS[pid].capabilities.balance)
    assert query_balance.SUPPORTED_PRODUCTS == expected
    assert set(expected) == set(registry.PRODUCT_IDS)


# ---------- 三态：缓存 + 额度池 ----------

async def test_quota_hook_result_lands_in_runtime_cache_and_pools(monkeypatch):
    """🔴 F6 红证：新产品额度经 `quota` 钩子上线 —— 写 `runtime.json` 缓存 + 资源额度池。

    三态逐档断言（§22.3「未知不当零」）：
    - `available` → 池 = `None`（未知/不限：没有数量可写；同时清掉上一轮的 0，
      否则充值成功后资源会被旧 0 **永久**挡住）；
    - `exhausted` → 池 = `0`（确定耗尽，预留闸门拦截）；
    - `unknown` → 池**一个字节都不动**（不把未知洗成 0，也不把已知值洗成不限）。
    """
    _seed("buddy", "acct-1")
    RT, mgr = _runtime([_buddy_resource()])
    pool = mgr.quotas["res-b"]

    pool.remaining = 0
    _install_quota(monkeypatch, QuotaSnapshot(state="available", source="buddy-billing",
                                              detail="有效包 2 个，本周期剩余 100 credits"))
    res = await query_balance.query_balance("acct-1", runtime=RT)
    assert res.category == "success" and "额度可用" in res.detail
    assert pool.remaining is None, "available 没有把上一个耗尽周期写下的 0 清掉"
    cache = accounts_store.read_runtime("buddy", "acct-1")
    assert cache["quota"]["state"] == "available"
    assert cache["quota"]["source"] == "buddy-billing"
    assert cache["quota"]["detail"].startswith("有效包")

    _install_quota(monkeypatch, QuotaSnapshot(state="exhausted", source="buddy-billing",
                                              detail="有效包 0 个"))
    res = await query_balance.query_balance("acct-1", runtime=RT)
    assert res.category == "success" and "额度已耗尽" in res.detail
    assert pool.remaining == 0
    assert accounts_store.read_runtime("buddy", "acct-1")["quota"]["state"] == "exhausted"

    pool.remaining = 7
    _install_quota(monkeypatch, QuotaSnapshot(state="unknown", source="buddy-billing",
                                              detail="余额查询网络错误：boom"))
    res = await query_balance.query_balance("acct-1", runtime=RT)
    assert res.category == "inactive" and "未知不当零" in res.detail
    assert pool.remaining == 7, "unknown 被写成了 0 / 洗掉了已知值（未知不当零）"
    assert accounts_store.read_runtime("buddy", "acct-1")["quota"]["state"] == "unknown"


async def test_pools_are_scoped_to_this_accounts_own_resources(monkeypatch):
    """额度池只写"本产品 + 本账号"物化的资源；别家账号 / 别家产品的池不动。"""
    _seed("buddy", "acct-1")
    RT, mgr = _runtime([
        _buddy_resource("acct-1"),
        {**_buddy_resource("acct-2"), "id": "res-b2", "name": "B2"},
        {"id": "res-t", "name": "T", "product": "trae", "account_ref": "trae-1",
         "base_url": "http://127.0.0.1:9/v1", "api_key": ""},
    ])
    for rid in ("res-b", "res-b2", "res-t"):
        mgr.quotas[rid].remaining = 5

    _install_quota(monkeypatch, QuotaSnapshot(state="exhausted", source="buddy-billing",
                                              detail="有效包 0 个"))
    await query_balance.query_balance("acct-1", runtime=RT)

    assert mgr.quotas["res-b"].remaining == 0
    assert mgr.quotas["res-b2"].remaining == 5, "写到了别的账号的资源池（串账号）"
    assert mgr.quotas["res-t"].remaining == 5, "写到了别的产品的资源池"


async def test_cache_write_failure_is_failed_not_success(monkeypatch):
    """🔴 落盘失败**不许谎报成功**（§22.8-5 / S-26④）：类别 = `failed`，原因可读。"""
    _seed("buddy", "acct-1")
    RT, _mgr = _runtime([_buddy_resource()])
    _install_quota(monkeypatch, QuotaSnapshot(state="available", source="buddy-billing",
                                              detail="有效包 2 个"))

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(accounts_store, "write_runtime", boom)
    res = await query_balance.query_balance("acct-1", runtime=RT)
    assert res.category == "failed"
    assert "缓存写入失败" in res.detail and "OSError" in res.detail


async def test_quota_cache_persists_plan_and_items(monkeypatch):
    """2026-10-01 加字段：快照的 `plan`/`items` 原样落 `runtime.json`（账号页套餐余粮列的数据源）。"""
    _seed("buddy", "acct-items")
    RT, _mgr = _runtime([])
    _install_quota(monkeypatch, QuotaSnapshot(
        state="available", source="buddy-billing", detail="d", plan="CodeBuddy个人体验版",
        items=({"name": "CodeBuddy个人体验版", "unit": "credits", "remaining": 5,
                "total": 10, "used": 5, "active": True, "expires_at": ""},)))
    res = await query_balance.query_balance("acct-items", runtime=RT)
    assert res.category == "success"
    cache = accounts_store.read_runtime("buddy", "acct-items")["quota"]
    assert cache["plan"] == "CodeBuddy个人体验版"
    assert cache["items"] == [{"name": "CodeBuddy个人体验版", "unit": "credits",
                               "remaining": 5, "total": 10, "used": 5,
                               "active": True, "expires_at": ""}]


# ---------- 量纲阈值（2026-10-05 用户补的规则：积分 <50、token <1万 ⇒ 自动剔出） ----------

async def test_credit_floor_excludes_a_non_zcode_account(monkeypatch):
    """🔴 阈值**不只接在 zcode 那条腿上**：buddy 是积分制产品，走的是 `_apply_quota_to_pools`
    的**通用体**（此前它只写三态、从不写资格位）。49 积分 ⇒ 剔出；升到 51 ⇒ 回池。

    实盘依据：`coding/data/upstream/buddy/accounts/*/runtime.json` 的 items 单位就是
    `credits` 且余量是小数（`500.0`、`472.1868`）。
    """
    _seed("buddy", "acct-1")
    RT, mgr = _runtime([_buddy_resource()])
    st = None

    def _snap(remaining):
        return QuotaSnapshot(state="available", source="buddy-billing", detail="逐包读数",
                             items=({"name": "CodeBuddy个人体验版", "unit": "credits",
                                     "remaining": remaining, "total": 500.0,
                                     "active": True, "expires_at": ""},))

    _install_quota(monkeypatch, _snap(49.0))
    await query_balance.query_balance("acct-1", runtime=RT)
    st = mgr.registry[("res-b", "vm")]
    assert st.quota.entitled is False, "49 积分仍被当成可承接"
    assert st.available() is False and mgr.reserve_quota(st) is False

    _install_quota(monkeypatch, _snap(51.0))
    await query_balance.query_balance("acct-1", runtime=RT)
    assert st.quota.entitled is True, "升到 51 没回池（阈值成了永久黑名单）"
    assert st.available() is True


async def test_unknown_state_does_not_touch_the_floor_gate(monkeypatch):
    """`unknown`（没查到）时**一位都不动**：阈值判据不许把"查询失败"变成"这号没资格"。"""
    _seed("buddy", "acct-1")
    RT, mgr = _runtime([_buddy_resource()])
    _install_quota(monkeypatch, QuotaSnapshot(state="available", source="buddy-billing",
                                              detail="有包"))          # 先建立一个"有资格"的起点
    await query_balance.query_balance("acct-1", runtime=RT)
    st = mgr.registry[("res-b", "vm")]
    assert st.quota.entitled is True

    _install_quota(monkeypatch, QuotaSnapshot(state="unknown", source="buddy-billing",
                                              detail="余额查询网络错误：boom"))
    await query_balance.query_balance("acct-1", runtime=RT)
    assert st.quota.entitled is True, "unknown 把资格位洗掉了（未知不当没资格）"
