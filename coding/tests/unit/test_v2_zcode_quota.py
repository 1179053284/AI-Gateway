"""v2.0 §17 额度三通道与 3012 熔断单元测试（tech-design §19 M4-4）。

覆盖：日志通道（括号配对 + 尾读 + 串号防护）、联网归一化、跨账号聚合、
3012 熔断 30min + 节流 10s + 状态落盘、熔断回写资源状态。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from model_gateway.upstream.zcode import quota

LOG_MARKER = "billing/balance 请求完成 "


def _log_record(*, user_plan_id: str = "up-1", show: str = "GLM-5.3",
                total: int = 3_000_000, used: int = 1_000_000,
                available: int | None = 2_000_000) -> str:
    bal: dict = {"user_plan_id": user_plan_id, "show_name": show,
                 "total_units": total, "used_units": used, "period": "daily"}
    if available is not None:
        bal["available_units"] = available
    return json.dumps({
        "providerId": "zai",
        "data": {"code": 0, "plans": [{"user_plan_id": user_plan_id,
                                       "plan_id": "start-plan", "status": "active"}],
                 "balances": [bal]},
    }, ensure_ascii=False)


def _write_log(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "2026-09-26.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# ---------- 日志通道 ----------

def test_parse_log_tail_extracts_last_record(tmp_path: Path):
    p = _write_log(tmp_path, [
        "noise line",
        LOG_MARKER + _log_record(used=100),
        "more noise",
        LOG_MARKER + _log_record(used=200),      # 取最后一条
    ])
    rec = quota.parse_log_tail(p)

    assert rec is not None
    assert rec["data"]["balances"][0]["used_units"] == 200


def test_parse_log_tail_uses_bracket_pairing_not_regex(tmp_path: Path):
    """🔴 payload 里带引号文案时，粗暴正则会把配对判错（`18` §②）。"""
    tricky = json.dumps({"data": {"msg": 'he said "}" ok', "balances": []}},
                        ensure_ascii=False)
    p = _write_log(tmp_path, [LOG_MARKER + tricky])

    rec = quota.parse_log_tail(p)
    assert rec is not None
    assert rec["data"]["msg"] == 'he said "}" ok'


def test_parse_log_tail_missing_file_returns_none(tmp_path: Path):
    assert quota.parse_log_tail(tmp_path / "nope.log") is None


def test_parse_log_tail_no_marker_returns_none(tmp_path: Path):
    p = _write_log(tmp_path, ["just noise", "nothing here"])
    assert quota.parse_log_tail(p) is None


def test_parse_log_tail_serial_mismatch_returns_none(tmp_path: Path):
    """🔴 **串号防护**：`expect_user_plan_id` 匹配不上 → 返回 None
    （**绝不把别人的额度顶上来**，`18` §②）。"""
    p = _write_log(tmp_path, [LOG_MARKER + _log_record(user_plan_id="someone-else")])

    assert quota.parse_log_tail(p, expect_user_plan_id="mine") is None
    assert quota.parse_log_tail(p, expect_user_plan_id="someone-else") is not None


def test_parse_log_tail_only_reads_tail_bytes(tmp_path: Path):
    """只读文件尾（4 MiB）—— 前面的记录不参与（大日志不 OOM）。"""
    p = tmp_path / "big.log"
    big_noise = "x" * (quota.TAIL_BYTES + 1024)
    p.write_text(big_noise + "\n" + LOG_MARKER + _log_record(used=777) + "\n",
                 encoding="utf-8")

    rec = quota.parse_log_tail(p)
    assert rec is not None and rec["data"]["balances"][0]["used_units"] == 777


# ---------- 归一化 ----------

def test_normalize_remote_maps_balances_to_buckets():
    snap = quota.normalize_remote(json.loads(_log_record()), account="a")

    assert snap.ok is True
    assert len(snap.buckets) == 1
    b = snap.buckets[0]
    assert b.show_name == "GLM-5.3"
    assert (b.total, b.used, b.available) == (3_000_000, 1_000_000, 2_000_000)
    assert snap.totals == (1_000_000, 3_000_000)


def test_normalize_remote_never_treats_total_as_available():
    """🔴 `available_units` 缺省时**绝不能拿总量当可用**（`18` §④）。"""
    rec = json.loads(_log_record(available=None))
    snap = quota.normalize_remote(rec)

    assert snap.buckets[0].available == 2_000_000     # = total - used，不是 3_000_000


def test_normalize_remote_non_dict_is_not_ok():
    snap = quota.normalize_remote("nope")  # type: ignore[arg-type]
    assert snap.ok is False and snap.note


def test_normalize_remote_field_alias_tolerance():
    """字段别名防御（不同通道键名不同）。"""
    snap = quota.normalize_remote({"data": {"balances": [
        {"showName": "X", "total_units": 10, "used_units": 4}]}})
    assert snap.buckets[0].show_name == "X"
    assert snap.buckets[0].available == 6


# ---------- 跨账号聚合 ----------

def test_aggregate_sums_across_accounts():
    """`{accounts: [...], aggregated: {used, total}}`（§19 M5-2）。"""
    s1 = quota.normalize_remote(json.loads(_log_record(used=100, total=1000)), account="a")
    s2 = quota.normalize_remote(json.loads(_log_record(used=200, total=2000)), account="b")

    out = quota.aggregate([s1, s2])
    assert out["aggregated"] == {"used": 300, "total": 3000}
    assert [a["account"] for a in out["accounts"]] == ["a", "b"]


def test_aggregate_empty():
    assert quota.aggregate([])["aggregated"] == {"used": 0, "total": 0}


# ---------- 3012 熔断 ----------

def test_risk_control_code_is_3012():
    """3012 = 服务端风控 `unusual activity`（`18` §③）。"""
    assert quota.CODE_RISK_CONTROL == 3012


def test_cooldown_is_thirty_minutes():
    assert quota.COOLDOWN_MS == 30 * 60 * 1000


def test_throttle_is_ten_seconds():
    assert quota.THROTTLE_MS == 10 * 1000


def test_cooldown_enters_and_expires(tmp_path: Path):
    """到期靠**墙钟**懒失效。

    🔴 判据改走注入的时钟而不是手改 `_cd`（验收 S-26⑤）：`_load()` 现在每次判定都
    回读文件，改内存态会被读盘覆盖 —— 而"改不动内存态"正是我们要的行为。
    """
    clock = {"now": time.time() * 1000}
    cm = quota.CooldownManager(tmp_path / "cd.json", now=lambda: clock["now"])
    cm.enter("3012 风控")

    assert cm.active() is True
    assert cm.left_ms() == pytest.approx(quota.COOLDOWN_MS, rel=0.01)
    assert "3012" in cm.reason()
    clock["now"] += quota.COOLDOWN_MS + 1          # 过点：自动失效，无需人工/定时器
    assert cm.active() is False


def test_cooldown_state_persists_across_restart(tmp_path: Path):
    """🔴 状态**落盘**防重启丢失（`18` §③：打包后只读目录会导致熔断状态存不下来）。"""
    p = tmp_path / "cd.json"
    quota.CooldownManager(p).enter("3012 风控")

    assert p.exists()
    reloaded = quota.CooldownManager(p)
    assert reloaded.active() is True
    assert "3012" in reloaded.reason()


def test_throttle_blocks_rapid_calls(tmp_path: Path):
    """节流 10s：刚调用过 → 需等待（同样走注入时钟，不改内存态）。"""
    clock = {"now": time.time() * 1000}
    cm = quota.CooldownManager(tmp_path / "cd.json", now=lambda: clock["now"])
    cm.mark_called()
    assert cm.throttle_wait_ms() > 0            # 刚调用过 → 还需等待

    clock["now"] += quota.THROTTLE_MS + 1
    assert cm.throttle_wait_ms() == 0            # 已过 10s → 放行


def test_breaker_written_within_the_same_second_is_still_seen(tmp_path: Path):
    """🔴 同一秒内的跨进程改写也必须看见（验收 S-26⑤）。

    原实现用 `mtime == self._loaded_mtime` 去重读盘。时间戳只到秒的卷上
    （HFS+/NFS/网络盘都常见），另一个进程第二次写的状态落在同一秒 → 常驻进程
    **永远读不到新熔断**，而这份文件正是跨进程看 3012 的唯一凭据。
    """
    p = tmp_path / "circuit.json"
    stamp = 1_700_000_000.0
    writer = quota.CooldownManager(p)
    writer.enter("第一次风控")
    os.utime(p, (stamp, stamp))                 # 把 mtime 钉死成同一个值
    watcher = quota.CooldownManager(p)
    assert "第一次" in watcher.reason()

    writer.enter("第二次风控（同一秒内改写）")
    os.utime(p, (stamp, stamp))
    assert "第二次" in watcher.reason(), "mtime 相同就跳过回读 → 跨进程状态看不见"


def test_cooldown_corrupt_file_blocks_instead_of_releasing(tmp_path: Path):
    """半写损坏的状态文件 = **未知**，按熔断拒跑（第十一轮 eng-A BLK-2 翻正的方向）。

    原断言是 `active() is False`（"读不动就当没熔断"）—— 那正是被面板判为 fail-open 的口径，
    而且放行后的一次 `mark_called()` 还会把盘上的熔断凭据整盘抹掉。
    """
    p = tmp_path / "cd.json"
    p.write_text("{bad", encoding="utf-8")
    cm = quota.CooldownManager(p)
    assert cm.active() is True, "读不动却放行 = 把风控窗口打开"
    assert cm.untrusted, "未知必须可分辨（不许说成『全部正常』）"
    assert "删除" in cm.reason(), "必须给可执行的手动出口"


def test_risk_control_text_detection():
    """风控文案识别（`unusual activity` / 中文「风控」）。"""
    assert quota.looks_like_risk_control("unusual activity detected") is True
    assert quota.looks_like_risk_control("检测到异常活动") is True
    assert quota.looks_like_risk_control("rate limit exceeded") is False
    assert quota.looks_like_risk_control(None) is False


# ---------- 熔断回写资源状态（§17：否则熔断形同虚设）----------

class _FakeState:
    """最小 ResourceState 替身（需 `resource_id` 元组 + `last_error`）。"""

    def __init__(self, rid: str):
        self.resource_id = (rid, "vendor-model")
        self.status = "active"
        self.last_error = ""


class _FakeResources:
    """⚠️ `bench` 必须与**真实签名一致**（`resources.py:151` 需 `seconds`）。

    验收发现：原 fake 写 `bench(self, state)` 少了 `seconds`，
    **掩盖了生产代码 `mgr.bench(state)` 的 TypeError** —— 接线即崩却测不出来。
    此处严格对齐真实签名，让同类问题无法再被掩盖。
    """

    def __init__(self, states: dict):
        self.registry = states
        self.benched: list = []
        self.bench_seconds: list[float] = []

    def bench(self, state, seconds: float) -> bool:
        """返回值也是契约的一部分（`bench()` 用它裁决"谁 owns 这条冷却"）。

        真实实现在"已有更长冷却"时返回 False；fake 不做时间算术，
        一律返回 True = "本次取得所有权"，因此生产侧的写原因路径会被完整走到。
        """
        state.status = "cooldown"
        self.benched.append(state)
        self.bench_seconds.append(seconds)
        return True


class _FakeRuntime:
    def __init__(self, rids):
        self.states = {r: _FakeState(r) for r in rids}
        self.resources = _FakeResources(self.states)
        self.config = type("C", (), {"resources": [
            type("R", (), {"id": r})() for r in rids]})()


def test_apply_to_resource_benches_and_writes_reason():
    """🔴 熔断必须**回写 `ResourceState`**（用 `bench` + 写 `last_error` 原因）——
    否则一个刚被 3012 熔断的账号仍会被模型转发路径选中（§17）。"""
    rt = _FakeRuntime(["res-a", "res-b"])
    n = quota.apply_to_resource(rt, ["res-a", "res-b"], reason="ZCode 风控熔断")

    assert n == 2
    for rid in ("res-a", "res-b"):
        st = rt.states[rid]
        assert st.status == "cooldown"
        assert "风控熔断" in st.last_error


def test_apply_to_resource_uses_bench_not_disable():
    """统一用 `bench`（临时冷却）而非 `disable`（停用）—— 两者对用户心理预期差别很大。"""
    rt = _FakeRuntime(["res-a"])
    quota.apply_to_resource(rt, ["res-a"], reason="额度耗尽")

    assert rt.states["res-a"].status == "cooldown"    # 不是 disabled
    assert len(rt.resources.benched) == 1


def test_apply_to_resource_passes_seconds_to_bench():
    """🔴 **接线缺陷回归护栏**：`bench` 需要 `seconds`（`resources.py:151`）。

    验收发现：原实现 `mgr.bench(state)` 少传参数 → **一旦接线立即 TypeError**，
    而单测的 fake 也少了该参数，**掩盖了缺陷**。本用例守住这条。
    """
    rt = _FakeRuntime(["res-a"])
    quota.apply_to_resource(rt, ["res-a"], reason="3012 风控")

    assert rt.resources.bench_seconds == [quota.COOLDOWN_MS / 1000]   # 30 分钟
    # 可显式指定时长
    rt2 = _FakeRuntime(["res-a"])
    quota.apply_to_resource(rt2, ["res-a"], reason="x", seconds=5)
    assert rt2.resources.bench_seconds == [5]


def test_bench_account_is_the_wiring_point(monkeypatch):
    """🔴 **熔断接线点**：`bench_account` 把账号名解析成资源 id 后 bench。

    验收发现：`apply_to_resource` / `CooldownManager` 此前**零生产调用点**
    → 3012 熔断**永不生效**。`bench_account` 是接线入口（由 `zcode_claim` 调用）。
    """
    rt = _FakeRuntime(["res-a", "res-b"])
    monkeypatch.setattr(quota, "resource_ids_of_account",
                    lambda acc, cfg=None: ["res-a"])
    n = quota.bench_account(rt, "acct-x", reason="ZCode 风控熔断（30min）")

    assert n == 1
    assert rt.states["res-a"].status == "cooldown"
    assert rt.states["res-b"].status == "active"        # 未映射的不受影响
    assert "风控熔断" in rt.states["res-a"].last_error


def test_bench_account_no_mapping_is_noop(monkeypatch):
    """账号未映射到任何资源 → 静默跳过（不报错）。"""
    rt = _FakeRuntime([])
    monkeypatch.setattr(quota, "resource_ids_of_account",
                    lambda acc, cfg=None: [])
    assert quota.bench_account(rt, "acct-y", reason="x") == 0


def test_apply_to_resource_ignores_unknown_ids():
    rt = _FakeRuntime(["res-a"])
    assert quota.apply_to_resource(rt, ["nope"], reason="x") == 0
