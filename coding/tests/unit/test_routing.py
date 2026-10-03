"""并发溢出生效集选路 UT（UT-22 七场景；纯内存，无网络）。"""

from __future__ import annotations

from tests.unit.conftest import build_runtime, chat_model, make_config


def _build(keys: str = "ABCD", x: int = 2):
    rt = build_runtime(make_config(
        models=[chat_model("test-model", keys)],
        scheduling={"max_active_per_model": x}), adapter=None)
    return rt


def _state(rt, key: str):
    return rt.resources.registry[(f"res-{key}", f"vm-{key}")]


class TestRoutingScenarios:
    """UT-22：池 [A,B,C,D]，x=2 —— 生效集 = top-x 可用资源；集内在途最少者承接。"""

    def test_s1_tie_picks_highest_priority(self):
        """① A/B 在途均 0 → 选 A（平局取优先级高）。"""
        rt = _build()
        r = rt.resources.pick_and_acquire("test-model", set())
        assert r.resource_id_str == "资源A/vm-A"
        rt.resources.release(r)

    def test_s2_overflow_to_least_busy(self):
        """② A 在途 1、B 在途 0 → 选 B（溢出到在途最少者）。"""
        rt = _build()
        _state(rt, "A").in_flight = 1
        r = rt.resources.pick_and_acquire("test-model", set())
        assert r.resource_id_str == "资源B/vm-B"
        rt.resources.release(r)

    def test_s3_all_busy_tie_picks_priority(self):
        """③ A/B 在途均 1 → 选 A（集内平局取优先级高）。"""
        rt = _build()
        _state(rt, "A").in_flight = 1
        _state(rt, "B").in_flight = 1
        r = rt.resources.pick_and_acquire("test-model", set())
        assert r.resource_id_str == "资源A/vm-A"
        rt.resources.release(r)

    def test_s4_cooldown_fills_standby(self):
        """④ A 冷却 → 生效集 {B,C}，选 B（候补补位生效）。"""
        rt = _build()
        rt.resources.bench(_state(rt, "A"), 60)
        r = rt.resources.pick_and_acquire("test-model", set())
        assert r.resource_id_str == "资源B/vm-B"
        rt.resources.release(r)
        # C 不越位承接（仍在生效集外，除非 B 也在途）
        _state(rt, "B").in_flight = 1
        r2 = rt.resources.pick_and_acquire("test-model", set())
        assert r2.resource_id_str == "资源C/vm-C"
        rt.resources.release(r2)

    def test_s5_x1_serial_concentration(self):
        """⑤ x=1 → 恒选 A（退化为纯顺序集中，不溢出）。"""
        rt = _build(x=1)
        _state(rt, "A").in_flight = 3
        r = rt.resources.pick_and_acquire("test-model", set())
        assert r.resource_id_str == "资源A/vm-A"  # 在途再多也集中
        rt.resources.release(r)

    def test_s6_all_cooldown_empty_set(self):
        """⑥ 全部冷却 → 空集（无可用资源）。"""
        rt = _build()
        for k in "ABCD":
            rt.resources.bench(_state(rt, k), 60)
        assert rt.resources.pick_and_acquire("test-model", set()) is None

    def test_s7_failover_target_excludes_tried(self):
        """⑦ 切换目标排除本请求已尝试资源（且不过已冷却集）。"""
        rt = _build()
        a = _state(rt, "A")
        # 已尝试 A（未冷却）：目标 ⊆ {B,C,D}
        r = rt.resources.pick_and_acquire("test-model", exclude={a.resource_id})
        assert r.resource_id_str == "资源B/vm-B"
        rt.resources.release(r)
        # A、B 均已尝试 → C
        b = _state(rt, "B")
        r2 = rt.resources.pick_and_acquire("test-model", exclude={a.resource_id, b.resource_id})
        assert r2.resource_id_str == "资源C/vm-C"
        rt.resources.release(r2)

    def test_acquire_and_release_roundtrip(self):
        """选路与在途 +1 在同一同步段（无 await 间隙）；release 归还。"""
        rt = _build()
        r = rt.resources.pick_and_acquire("test-model", set())
        assert r.in_flight == 1
        rt.resources.release(r)
        assert r.in_flight == 0

    def test_lazy_recovery_in_pick(self):
        """冷却到期懒恢复（UT-10 逻辑位）：到期后 A **回到候选集**并被轮到。

        🔴 Q33-③ 改判：原先这条断的是"到期后下一次选路立刻回到 A"（§5.3 集中调用）。
        号间轮转之后"立刻"不再成立 —— 游标已经走过 A 了，硬要立刻回 A 等于把轮转打掉。
        所以这里断的是**懒恢复这件事本身**：状态从 cooldown 归位 active，且在有限几轮内
        确实被选中一次（若到期不归位，A 会永远选不到，这条照样红）。
        """
        rt = _build()
        a = _state(rt, "A")
        rt.resources.bench(a, 60)
        assert rt.resources.pick_and_acquire("test-model", set()).resource_id_str == "资源B/vm-B"
        rt.resources.release(rt.resources.registry[("res-B", "vm-B")])
        a.cooldown_until = rt.resources.clock() - 1  # 到期
        seen = set()
        for _ in range(4):                            # 池 4 条 ⇒ 四轮内必轮到 A
            r = rt.resources.pick_and_acquire("test-model", set())
            assert r is not None
            seen.add(r.resource_id_str)
            rt.resources.release(r)
        assert "资源A/vm-A" in seen and a.status == "active"
