"""v2.0 §19 M5-3 额度预扣单元测试（第二轮：粒度改为**资源级共享池**）。

🔴 本轮修正的三件事（验收 eng S-1 / M-3 / M-5）：
- **S-1** 额度记在 `(rid, vendor_model)` 每个状态上 → 同账号 N 个映射各放行 1 个，
  余量 1 也能并发超发 N 个。正确粒度是 **rid（一把凭据 = 一个额度桶）**。
- **M-5** `reserve_quota(amount=5)` 与 `settle/release`（硬编码减 1）不对称 → `reserved` 永久泄漏。
  现在**没有 amount 形参**，预留/结算/释放 1:1。
- **M-3** tick 刷新拿滞后快照把已消耗额度"复活" → 同窗口内只允许调低，`used` 变小才算窗口翻页。

判据本体（§19 M5-3「并发不超发」）用 `asyncio.gather` 真并发验，不用顺序 for 循环。
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from model_gateway.core.resources import (
    QuotaPool,
    ResourceManager,
    ResourceState,
)


def _state(rid: str = "res-a", vm: str = "vm-a", quota: QuotaPool | None = None) -> ResourceState:
    return ResourceState(rid, vm, label=rid, vendor="V", account="", access_mode="api",
                         enabled=True, quota=quota or QuotaPool())


def _mgr_with(*states: ResourceState, x: int = 2) -> ResourceManager:
    """造一个有生效池的 manager（走生产选路，不碰内部计数器）。

    `registry` / `pools` / `quotas` 三处都填 —— 真实 `rebuild()` 就是这三处同时写。
    """
    mgr = ResourceManager()
    mgr.pools["m"] = list(states)
    for s in states:
        mgr.registry[s.resource_id] = s
        mgr.quotas[s.rid] = s.quota
    mgr.x = x
    return mgr


# ---------- 未知额度 = 不做管控（向后兼容）----------

def test_unknown_quota_behaves_like_before():
    s = _state()
    assert s.quota.remaining is None
    assert s.has_quota() is True
    assert s.available() is True


def test_unknown_quota_reserve_always_succeeds():
    """不限额度时不记预留（记了也没意义），且反复选路都放行。"""
    s = _state()
    mgr = _mgr_with(s)
    for _ in range(100):
        assert mgr.reserve_quota(s) is True
    assert s.quota.reserved == 0


def test_set_quota_none_clears_management():
    """把额度设回 None → 恢复"不管控"（如账号切回按量 Key）。"""
    mgr = _mgr_with()
    s = _state()
    mgr.set_quota(s, 0)
    assert s.available() is False
    assert mgr.set_quota(s, None) is True
    assert s.available() is True


# ---------- 有额度时：事前预留 ----------

def test_quota_exhausted_makes_resource_unavailable():
    mgr = ResourceManager()
    s = _state()
    mgr.set_quota(s, 0)
    assert s.has_quota() is False
    assert s.available() is False


def test_reserve_blocks_when_no_remaining():
    mgr = ResourceManager()
    s = _state()
    mgr.set_quota(s, 1)
    assert mgr.reserve_quota(s) is True
    assert mgr.reserve_quota(s) is False
    assert s.available() is False


def test_settle_consumes_reserved_quota():
    """预留→结算：结算只归还预留，余量归上游快照说。"""
    mgr = ResourceManager()
    s = _state()
    mgr.set_quota(s, 5)
    assert mgr.reserve_quota(s) is True
    assert (s.quota.remaining, s.quota.reserved) == (5, 1)
    mgr.settle_quota(s)
    assert (s.quota.remaining, s.quota.reserved) == (5, 0)


def test_release_frees_reservation_without_consuming():
    mgr = ResourceManager()
    s = _state()
    mgr.set_quota(s, 1)
    assert mgr.reserve_quota(s) is True
    assert s.available() is False
    mgr.release_quota(s)
    assert s.available() is True
    assert mgr.reserve_quota(s) is True      # 额度还在，可再用


def test_settle_never_goes_negative():
    mgr = ResourceManager()
    s = _state()
    mgr.set_quota(s, 0)
    mgr.release_quota(s)                     # 无预留时释放不得把计数打成负
    assert s.quota.reserved == 0
    mgr.settle_quota(s)
    assert s.quota.remaining == 0


# ---------- 🔴 S-1：粒度必须是"一把凭据一个桶" ----------

def test_two_mappings_of_one_credential_share_a_single_quota_pool():
    """🔴 判据本体（上一版在此超发）：同 rid 两个厂商模型，余量 1 → 只放行 1 个。

    额度是**账号/凭据**侧的，一个资源可以同时映射多个模型；
    每个 `(rid, vendor_model)` 状态各记一份余量 = 有 N 个映射就能放行 N 个。
    """
    shared = QuotaPool()
    a = _state("res-z", "vm-a", quota=shared)
    b = _state("res-z", "vm-b", quota=shared)
    assert a.quota is b.quota                      # 必须是同一个池实例
    mgr = _mgr_with(a, b)
    mgr.set_quota("res-z", 1)                      # 按 rid 写一次

    first = mgr.pick_and_acquire("m", set())
    second = mgr.pick_and_acquire("m", set())
    assert first is not None
    assert second is None, f"超发：两次都获批（{first} / {second}）"
    assert shared.reserved == 1


def test_concurrent_two_mappings_cannot_double_spend():
    """真并发版：两个映射各自的 in_flight 都是 0，也不得同时拿到那 1 个单位。"""
    shared = QuotaPool()
    a = _state("res-z", "vm-a", quota=shared)
    b = _state("res-z", "vm-b", quota=shared)
    mgr = _mgr_with(a, b)
    mgr.set_quota("res-z", 1)

    async def worker():
        st = mgr.pick_and_acquire("m", set())
        if st is None:
            return "none"
        await asyncio.sleep(0.02)                  # 真实重叠
        mgr.release(st)
        mgr.release_quota(st)
        return "ok"

    results = asyncio.run(_gather(worker, 4))
    assert results.count("ok") == 1, f"并发超发：{results}"


async def _gather(fn, n):
    return await asyncio.gather(*[fn() for _ in range(n)])


# ---------- 选路层的预留 ----------

def test_successive_settles_do_not_drain_the_snapshot():
    """结算不扣余量（否则就有了第二本账，见 `QuotaPool` 的教训 ②）。

    余量归零只有两条路：上游快照报 0，或 §17 的额度耗尽回写把资源 bench 掉。
    """
    s = _state()
    mgr = _mgr_with(s)
    mgr.set_quota(s, 3)
    for _ in range(3):
        st = mgr.pick_and_acquire("m", set())
        assert st is s
        mgr.release(st)
        mgr.settle_quota(st)
    assert s.quota.remaining == 3 and s.quota.reserved == 0
    mgr.set_quota(s, 0)                        # 上游反映"真的用完了"
    assert mgr.pick_and_acquire("m", set()) is None


def test_exhausted_resource_is_skipped_and_backup_takes_over():
    a, b = _state("res-a"), _state("res-b")
    mgr = _mgr_with(a, b)
    mgr.set_quota(a, 0)
    mgr.set_quota(b, 5)
    picked = mgr.pick_and_acquire("m", set())
    assert picked is b
    assert b.quota.reserved == 1 and b.in_flight == 1


def test_reserve_happens_in_the_same_sync_segment_as_in_flight():
    """🔴 预留与在途 +1 必须同段：只 `in_flight += 1` 不预留 = 闸门形同虚设。"""
    s = _state()
    mgr = _mgr_with(s)
    mgr.set_quota(s, 2)
    first = mgr.pick_and_acquire("m", set())
    assert (first.in_flight, first.quota.reserved) == (1, 1)
    second = mgr.pick_and_acquire("m", set())
    assert (second.in_flight, second.quota.reserved) == (2, 2)
    assert mgr.pick_and_acquire("m", set()) is None


def test_reserve_settle_release_are_symmetric():
    """🔴 M-5 护栏：三个函数都必须**只接受 state**（无 amount 自由度）。

    上一版 `reserve_quota(amount=5)` 配 `settle_quota(consumed=1)` → 预留永久泄漏 4。
    这里直接把签名钉住：长出任何"预留 N / 结算 1"的不对称口子就红。
    """
    for fn in (ResourceManager.reserve_quota, ResourceManager.settle_quota,
               ResourceManager.release_quota):
        params = list(inspect.signature(fn).parameters)
        assert "amount" not in params and "consumed" not in params, f"{fn} 又长出了数量形参"
        assert params == ["self", "state"], f"{fn} 签名漂移：{params}"
    assert "amount" not in inspect.signature(ResourceManager.pick_and_acquire).parameters

    s = _state()
    mgr = _mgr_with(s)
    mgr.set_quota(s, 10)
    for _ in range(4):
        assert mgr.reserve_quota(s) is True
    assert s.quota.reserved == 4
    for _ in range(4):
        mgr.release_quota(s)
    assert s.quota.reserved == 0                  # 零泄漏


def test_unlimited_quota_resources_are_unaffected_by_selection():
    """`remaining=None`（按量 Key）→ 选路行为与 v1.6 逐字一致（向后兼容）。"""
    s = _state()
    mgr = _mgr_with(s)
    got = [mgr.pick_and_acquire("m", set()) for _ in range(5)]
    assert all(x is s for x in got)
    assert s.in_flight == 5 and s.quota.reserved == 0


# ---------- 🔴 M-3：滞后快照不得复活已消耗额度 ----------

def test_snapshot_is_the_single_authority():
    """🔴 上游快照是余量的唯一权威：变大（充值/翻页）与变小（真实消耗）都立即生效。

    这条用例同时钉死第三轮的两个严重缺陷：
    ① 单调守卫（只准变小）把充值永久拒收 → 资源自锁到进程重启；
    ② 结算时自增本地 `used` → 下一条**滞后**快照被误判成窗口翻页而复活已消耗量。
    本地既然没有权威数据，就不该有第二本账。
    """
    s = _state()
    mgr = _mgr_with(s)
    mgr.set_quota(s, 5)
    st = mgr.pick_and_acquire("m", set())
    mgr.release(st)
    mgr.settle_quota(st)
    assert s.quota.remaining == 5, "结算不得改动余量（否则就有了第二本账 → 复活）"

    assert mgr.set_quota(s, 0) is True          # 上游报耗尽
    assert mgr.pick_and_acquire("m", set()) is None
    assert mgr.set_quota(s, 5) is True          # 充值 / 新窗口：必须立刻恢复可服务
    assert mgr.pick_and_acquire("m", set()) is not None
    assert mgr.set_quota(s, 5) is False         # 同值重复快照不记为变更（刷新计数不虚增）


def test_window_reset_is_accepted():
    """`used` 变小 = 滚动窗口翻页（如 5 小时窗口重置）→ 全盘接受新快照。"""
    s = _state()
    mgr = _mgr_with(s)
    mgr.set_quota(s, 1)
    assert mgr.set_quota(s, 100) is True            # 充值 / 新窗口都立即生效
    assert s.quota.remaining == 100


def test_decreasing_snapshot_is_always_applied():
    """余量变小（上游真实消耗）必须照收 —— 否则闸门会长期放行已耗尽的资源。"""
    s = _state()
    mgr = _mgr_with(s)
    mgr.set_quota(s, 10)
    assert mgr.set_quota(s, 3) is True
    assert s.quota.remaining == 3


# ---------- 数据源接线 ----------

def test_refresh_writes_snapshot_into_shared_pool(monkeypatch, tmp_path):
    """🔴 `refresh_runtime_quotas` 必须把余量写进**共享池**（按 rid），不是每个状态一份。"""
    from model_gateway.upstream.zcode import quota as zq
    from model_gateway.config.schemas import AppConfig

    shared = QuotaPool()
    a = _state("res-z", "vm-a", quota=shared)
    b = _state("res-z", "vm-b", quota=shared)
    mgr = _mgr_with(a, b)
    cfg = AppConfig.model_validate({
        "resources": [{"id": "res-z", "name": "Z", "account": "acct-a",
                       "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-z"}],
        "models": [],
    })

    class _RT:
        resources = mgr
        config = cfg

    monkeypatch.setattr(zq, "read_account_snapshot",
                        lambda root, name, **kw: zq.QuotaSnapshot(
                            account=name, ok=True,
                            buckets=[zq.Bucket("通用", "5h", 100, 96, 4)]))
    assert zq.refresh_runtime_quotas(_RT(), accounts=["acct-a"]) == 1   # 一个 rid → 一次写入
    assert a.quota.remaining == 4 and b.quota.remaining == 4           # 同一个池
    assert a.quota is b.quota


def test_refresh_keeps_unknown_quota_unmanaged(monkeypatch):
    """读不到快照 → **保持旧值**（未知 ≠ 没额度），否则日志一缺失就误封全部资源。"""
    from model_gateway.upstream.zcode import quota as zq
    from model_gateway.config.schemas import AppConfig

    s = _state("res-z")
    mgr = _mgr_with(s)
    mgr.set_quota(s, 9)

    class _RT:
        resources = mgr
        config = AppConfig.model_validate({
            "resources": [{"id": "res-z", "name": "Z", "account": "acct-a",
                           "base_url": "http://127.0.0.1:9/v1", "api_key": "sk"}],
            "models": []})

    monkeypatch.setattr(zq, "read_account_snapshot",
                        lambda root, name, **kw: zq.QuotaSnapshot(account=name, ok=False))
    assert zq.refresh_runtime_quotas(_RT(), accounts=["acct-a"]) == 0
    assert s.quota.remaining == 9


def test_view_exposes_quota_for_diagnostics():
    s = _state()
    mgr = _mgr_with(s)
    mgr.set_quota(s, 7)
    assert (s.quota.remaining, s.quota.reserved) == (7, 0)


def test_inflight_reservations_gate_admission_even_with_a_stale_large_snapshot():
    """🔴 快照偏大时，防超发的职责由**在飞预留**承担（不再有本地消耗账）。

    快照说还有 2，但已有 2 个请求在飞 → 第 3 个不得再被派出去。
    """
    s = _state()
    mgr = _mgr_with(s)
    mgr.set_quota(s, 2)
    assert mgr.pick_and_acquire("m", set()) is not None
    assert mgr.pick_and_acquire("m", set()) is not None
    assert mgr.pick_and_acquire("m", set()) is None, "预留未被计数 → 快照偏大就直接超发"
    assert s.quota.reserved == 2


# ---------- 🔴 走**真实 rebuild()** 的接线判据（验收 eng-④：手工搭 registry 证不到那行）----------

def _cfg_with_two_models_on_one_resource():
    """一个资源被两个系统模型引用（两个厂商模型映射）—— 额度属于**资源**，不属于映射。"""
    from model_gateway.config.schemas import AppConfig

    return AppConfig.model_validate({
        "resources": [{"id": "res-z", "name": "Z", "access_mode": "api",
                       "base_url": "http://127.0.0.1:9/v1", "api_key": "sk"}],
        "models": [
            {"name": "m1", "endpoint": "chat",
             "resources": [{"resource": "res-z", "model": "vm-a"}]},
            {"name": "m2", "endpoint": "chat",
             "resources": [{"resource": "res-z", "model": "vm-b"}]},
        ]})


def test_rebuild_shares_one_pool_across_mappings_of_the_same_resource():
    """`rebuild()` 必须把两条映射接到**同一个** QuotaPool 实例上。

    撤掉 `ResourceState(..., quota=self._pool_for(rid))` 这行接线 → 每条映射各建一池
    → 同一次快照余量被两个模型各花一遍（超发）。本用例即该行的存在理由。
    """
    from model_gateway.core.resources import ResourceManager

    mgr = ResourceManager()
    mgr.rebuild(_cfg_with_two_models_on_one_resource())
    a = mgr.registry[("res-z", "vm-a")]
    b = mgr.registry[("res-z", "vm-b")]

    assert a.quota is b.quota, "两条映射各自持池 = 上游余量被花两次"
    assert mgr.set_quota("res-z", 1) is True
    assert mgr.reserve_quota(a) is True
    assert mgr.reserve_quota(b) is False, "已预留 1/1 仍放行 = 超发"
    mgr.release_quota(a)
    assert mgr.reserve_quota(b) is True, "预留必须可回收（否则一次失败永久占位）"


def test_rebuild_twice_does_not_reset_the_snapshot_authority():
    """热重载两次：额度是**运行态**，不得被配置重建抹回"未知"（未知 = 不管控 = 闸门形同虚设）。"""
    from model_gateway.core.resources import ResourceManager

    mgr = ResourceManager()
    cfg = _cfg_with_two_models_on_one_resource()
    mgr.rebuild(cfg)
    mgr.set_quota("res-z", 3)
    mgr.rebuild(cfg)                      # 同配置再来一次（mtime 热重载的真实形状）

    st = mgr.registry[("res-z", "vm-a")]
    assert (st.quota.remaining, st.quota.reserved) == (3, 0)


def test_rebuild_recycles_the_pool_when_the_resource_loses_all_references():
    """资源被删 → 池一并回收；**同名新资源不得继承旧余量**（防残留数据复活）。"""
    from model_gateway.core.resources import ResourceManager

    mgr = ResourceManager()
    cfg = _cfg_with_two_models_on_one_resource()
    mgr.rebuild(cfg)
    mgr.set_quota("res-z", 9)
    assert mgr.quotas["res-z"].remaining == 9

    cfg.resources = [r for r in cfg.resources if r.id != "res-z"]
    cfg.models = []
    mgr.rebuild(cfg)
    assert "res-z" not in mgr.quotas, "池未回收"
    mgr.rebuild(_cfg_with_two_models_on_one_resource())
    assert mgr.quotas["res-z"].remaining is None, "新资源继承了旧余量"


# ---------- §17：额度耗尽必须**同时**回写 status / last_error（验收 eng-③）----------

def _rt_one_resource(account: str = "acct-a", rid: str = "res-z", vm: str = "vm-a"):
    import types

    from model_gateway.config.schemas import AppConfig
    from model_gateway.core.resources import ResourceManager

    cfg = AppConfig.model_validate({
        "resources": [{"id": rid, "name": "Z", "account": account, "access_mode": "api",
                       "base_url": "http://127.0.0.1:9/v1", "api_key": "sk"}],
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": rid, "model": vm}]}]})
    mgr = ResourceManager()
    mgr.rebuild(cfg)
    return types.SimpleNamespace(config=cfg, resources=mgr,
                                 clock=mgr.clock)


def _snap(available: int | None):
    from model_gateway.upstream.zcode.quota import Bucket, QuotaSnapshot

    if available is None:
        return QuotaSnapshot(account="acct-a", buckets=[], ok=False, note="读不到")
    return QuotaSnapshot(account="acct-a", buckets=[
        Bucket(show_name="通用", period="5h", total=100, used=100 - available,
               available=available)])


def test_exhausted_snapshot_benches_with_the_documented_reason():
    """只写额度池不够：用户在总览要看到 `ZCode 额度耗尽`，否则"这模型为何不干活"只能猜。"""
    from model_gateway.upstream.zcode import quota as zq

    rt = _rt_one_resource()
    zq.apply_snapshot_to_runtime(rt, "acct-a", _snap(0))

    st = rt.resources.registry[("res-z", "vm-a")]
    assert st.status == "cooldown", st.status
    assert st.last_error == zq.QUOTA_EXHAUSTED_REASON == "ZCode 额度耗尽"
    assert (st.quota.remaining, st.quota.reserved) == (0, 0)
    assert rt.resources.pick_and_acquire("m", set()) is None, "耗尽后仍被选中 = 状态回写没生效"


def test_non_exhausted_snapshot_leaves_status_alone():
    """🔴 正向对照：有余量**不得** bench（否则每次刷新都把健康资源关一遍）。"""
    from model_gateway.upstream.zcode import quota as zq

    rt = _rt_one_resource()
    zq.apply_snapshot_to_runtime(rt, "acct-a", _snap(7))

    st = rt.resources.registry[("res-z", "vm-a")]
    assert st.status == "active" and st.last_error is None
    assert st.quota.remaining == 7


def test_unknown_snapshot_does_not_bench():
    """快照取不到 = **未知**，不是"没额度"：误 bench 会让一次日志缺失把全部资源踢出生效集。"""
    from model_gateway.upstream.zcode import quota as zq

    rt = _rt_one_resource()
    zq.apply_snapshot_to_runtime(rt, "acct-a", _snap(None))

    st = rt.resources.registry[("res-z", "vm-a")]
    assert st.status == "active" and st.last_error is None
    assert st.quota.remaining is None


def test_exhaustion_bench_lasts_one_refresh_cycle_and_self_heals():
    """时长 = 一个额度刷新周期：充值后下一次 tick 不再 bench，资源自动回池。"""
    from model_gateway.upstream.zcode import quota as zq

    rt = _rt_one_resource()
    zq.apply_snapshot_to_runtime(rt, "acct-a", _snap(0))
    st = rt.resources.registry[("res-z", "vm-a")]
    left = st.cooldown_until - rt.clock()
    assert 0 < left <= 60 + 1, f"bench 时长 {left:.0f}s 与默认 60s 刷新周期不符"

    zq.apply_snapshot_to_runtime(rt, "acct-a", _snap(5))   # 已充值
    assert st.status == "cooldown", "本次不 bench，但上一次冷却应自然到期（不续期）"
    assert st.quota.remaining == 5


def test_reservation_is_returned_even_if_quota_became_unknown():
    """🔴 预留归还**不受**额度是否已知影响（验收 L-2：闸门只会越挡越死）。

    真实形状：请求 A 预留时快照还是 5，中途 `set_quota(rid, None)`（读不到上游额度）
    → 结算若因 `remaining is None` 早退，`reserved` 就永久留下 1，
    此后所有请求都被"余量-预留<=0"挡住，而界面上看不出任何原因。
    """
    s = _state()
    mgr = _mgr_with(s)
    mgr.set_quota(s, 5)
    assert mgr.reserve_quota(s) is True
    assert s.quota.reserved == 1

    mgr.set_quota(s, None)                      # 中途变成"未知"
    mgr.settle_quota(s)
    assert s.quota.reserved == 0, "结算未归还预留 → 闸门永久收紧"

    mgr.set_quota(s, 1)
    assert mgr.reserve_quota(s) is True
    mgr.set_quota(s, None)
    mgr.release_quota(s)                        # 失败路径同样必须归还
    assert s.quota.reserved == 0
