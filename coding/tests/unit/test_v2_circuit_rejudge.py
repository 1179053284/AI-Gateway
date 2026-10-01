"""**熔断「读时重判」**判据（2026-09-29 用户裁决）。

产品口径：全局风控熔断落盘在 `circuit.json`，§17 要求它回写到资源运行态
（总览「资源健康」那一行 `cooldown` +「最近错误」写熔断原因）。用户**手动删掉那个文件**
是官方给的唯一出口（CLI 文案明说"删除该文件可立即放开后续领取"），但删完之后
界面那一行原先仍按写死的 `cooldown_until` 冻结（最长 30 分钟）且毫无反馈。
裁决：改成**读时重判** —— 谁读（出快照 / 选路决定生效集）时，若熔断已经不成立，
就把**它当初按住的那些**资源状态当场放回生效集。不做跨进程通知、不加 watcher。

三条红线（本项目既有定稿，本文件的反向判据就是钉它们的）：
1. **只放"熔断按住的"那一类冷却**：额度耗尽 / 429 退避与熔断共用同一条 `bench` 链，
   笼统地"不成立就抬起来"= 用一次删文件动作把别人的观察期提前放行；
2. `invalid` / `disabled` 是**终态**（PRD Q28-⑥③），本改动不得有任何路径把它们变回 active；
3. 恢复后「最近错误」**保留但不配钟点**（PRD Q28-⑦①，实现见 `_rendered_last_error`）。

时间一律注入 `manager.clock` 的假钟（生产默认钟是 `time.monotonic`，
与熔断的墙钟是两个时基，见 `test_recovery_clock_is_rendered_from_the_wall_clock…`），
不真 sleep。
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest
import yaml

from model_gateway.config.schemas import AppConfig
from model_gateway.core.resources import ResourceManager, ResourceState, servable_models
from model_gateway.upstream.zcode import quota as zq

ACCOUNT = "acct-a"
BREAKER_REASON = "ZCode 风控熔断（30min，全局）"
COOLDOWN_S = zq.COOLDOWN_MS / 1000          # 30 分钟，与生产同值


# ---------- 骨架 ----------

@pytest.fixture
def accounts_root(tmp_path, monkeypatch):
    """ZCode 账号根（`bench_all_zcode` / `sync_circuit_to_runtime` 的作用域来源）。"""
    root = tmp_path / "zcode-accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    for name in (ACCOUNT, "acct-b"):
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text(json.dumps({"device_mid": f"mid-{name}"}),
                                     encoding="utf-8")
    return root


def _config() -> AppConfig:
    """两条资源（一条 ZCode 账号、一条别的产品）+ 各挂一个 chat 系统模型。

    🔴 两条映射**各自成池**（`m-z` 只有 res-z）：选路类判据要能断"这条被绕开了"，
    混在一个模型里就会被另一条资源顶掉，断言变成恒真。
    """
    return AppConfig.model_validate({
        "resources": [
            {"id": "res-z", "name": "Z号", "account": ACCOUNT, "product": "zcode",
             "account_ref": ACCOUNT,
             "access_mode": "api", "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-1"},
            {"id": "res-p", "name": "别的产品", "account": "acct-q", "product": "qoder",
             "account_ref": "acct-q",
             "access_mode": "plan", "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-2"},
        ],
        "models": [
            {"name": "m-z", "endpoint": "chat",
             "resources": [{"resource": "res-z", "model": "vm-z"}]},
            {"name": "m-p", "endpoint": "chat",
             "resources": [{"resource": "res-p", "model": "vm-p"}]},
        ],
        "gateway": {"zcode": {"claim_interval_seconds": 0}},     # 不起运营定时器
    })


def _runtime(cfg: AppConfig, *, start: float = 1_000_000.0, wire: bool = True):
    """最小 runtime + **真** `ResourceManager`（假钟）。

    `wire=True` 复刻 `main.py` 的装配缝（`Runtime._wire_circuit_rejudge`）：
    判据取**调用时**的单例，不在启动时绑死实例。`wire=False` = 没接判据的进程
    （CLI 独立进程 / 未装配的单测）。
    """
    t = [start]
    mgr = ResourceManager(clock=lambda: t[0])
    if wire:
        mgr.circuit_active = lambda: zq.get_circuit().active()
    mgr.rebuild(cfg)
    rt = types.SimpleNamespace(config=cfg, resources=mgr)
    rt.advance = lambda seconds: t.__setitem__(0, t[0] + seconds)
    return rt


def _breaker_armed(path: Path | None = None) -> zq.CooldownManager:
    """熔断**落盘**（等价于 CLI/cron 命中 3012 后的 `enter()`）。"""
    cm = zq.get_circuit() if path is None else zq.CooldownManager(path)
    cm.enter(BREAKER_REASON)
    return cm


def _row(rt, rid: str) -> dict:
    return next(r for r in rt.resources.snapshot_by_resource(rt.config) if r["rid"] == rid)


def _state(rt, rid: str, vendor_model: str) -> ResourceState:
    return rt.resources.registry[(rid, vendor_model)]


# ---------- 1) 裁决本体：删掉文件 → 下一次出快照就放开 ----------

def test_deleting_the_breaker_file_releases_the_row_on_the_next_snapshot(accounts_root):
    """🔴 主判据（用户看得见的那一幕）：熔断回写后删文件，**同一次读**就回到 active。

    撤掉修复的哪一行都会让它红：`bench()` 里的成因登记（标记永远不为真 → 永不释放）、
    `reconcile_expired` 里的第二个释放条件（快照仍按旧钟点冻结）、
    `main.py` 的判据接线（未接判据 → 不重判）。
    """
    rt = _runtime(_config())
    breaker_path = zq.circuit_path()
    _breaker_armed()

    assert zq.bench_all_zcode(rt, reason=zq.get_circuit().reason()) == 1
    held = _row(rt, "res-z")
    assert held["status"] == "cooldown", held
    assert held["cooldown_remaining_ms"] == pytest.approx(COOLDOWN_S * 1000, rel=0.01), held
    assert held["last_error"].startswith(BREAKER_REASON)
    assert "，至 " in held["last_error"], held          # 熔断期内**该**带恢复时刻

    breaker_path.unlink()                                # 用户执行官方给的手动出口

    free = _row(rt, "res-z")
    assert free["status"] == "active", f"删完文件仍冻结到旧钟点 = 官方出口没有反馈：{free}"
    assert free["available"] is True, free
    assert free["cooldown_remaining_ms"] == 0, free
    # 🔴 红线 3：「最近错误」留着当历史线索，但**不再配任何钟点**
    assert free["last_error"] == BREAKER_REASON, free
    assert "至 " not in free["last_error"], free
    # 别的产品不受牵连（作用域仍然是账号→资源那条老尺）
    assert _row(rt, "res-p")["status"] == "active"


def test_snapshot_keeps_the_row_cooled_while_the_breaker_still_holds(accounts_root):
    """🔴 反向（防"重判把还在观察期的资源放出去"）：熔断**仍在生效**时读快照必须还是冷却。

    撤掉 `_lift_if_circuit_cleared` 里 `circuit_cleared` 这一半前提（变成"读到就抬"）→ 这条红。
    """
    rt = _runtime(_config())
    _breaker_armed()
    zq.bench_all_zcode(rt, reason=zq.get_circuit().reason())

    row = _row(rt, "res-z")
    assert row["status"] == "cooldown" and row["cooldown_remaining_ms"] > 0, row
    assert _state(rt, "res-z", "vm-z").available() is False, "观察期内不得进生效集"


def test_unwired_manager_never_rejudges(accounts_root):
    """没接判据的进程（CLI 独立进程 / 未装配单测）行为与改动前**逐字节一致**：不重判。

    🔴 分层护栏：core 不得自己去 import upstream 拿熔断；判据只能由装配侧注入。
    把 `ResourceManager._circuit_cleared()` 改成"判据缺失就当作没熔断"→ 这条红。
    """
    rt = _runtime(_config(), wire=False)
    assert rt.resources.circuit_active is None
    _breaker_armed()
    with rt.resources.circuit_hold():
        st = _state(rt, "res-z", "vm-z")
        assert rt.resources.bench(st, COOLDOWN_S) is True
    assert st.circuit_held is True

    zq.circuit_path().unlink()
    assert _row(rt, "res-z")["status"] == "cooldown", "未注入判据却重判 = core 越过了分层"


# ---------- 2) 第 1 号坑：只放熔断按住的那一类 ----------

def test_quota_exhaustion_cooldown_survives_the_breaker_delete(accounts_root):
    """🔴 额度耗尽造成的 cooldown，删熔断文件**不得**影响它（两类成因共用一条 bench 链）。

    撤掉 `bench()` 的成因登记之外的任何"按 rid 一律标记"写法、或把释放条件
    从 `circuit_held` 放宽成"任何 cooldown" → 这条红。
    """
    rt = _runtime(_config())
    _breaker_armed()
    snap = zq.QuotaSnapshot(account=ACCOUNT, buckets=[
        zq.Bucket(show_name="通用", period="5h", total=100, used=100, available=0)])
    assert zq.apply_snapshot_to_runtime(rt, ACCOUNT, snap) == 1   # 额度耗尽回写（非熔断作用域）

    st = _state(rt, "res-z", "vm-z")
    assert st.status == "cooldown" and st.last_error == zq.QUOTA_EXHAUSTED_REASON, st
    assert st.circuit_held is False, "额度耗尽的冷却被登记成了熔断成因"

    zq.circuit_path().unlink()
    row = _row(rt, "res-z")
    assert row["status"] == "cooldown", f"删熔断文件把额度冷却一起放开了：{row}"
    assert row["cooldown_remaining_ms"] > 0, row


def test_backoff_cooldown_survives_the_breaker_delete(accounts_root):
    """🔴 429/连续失败退避（调度器就是这句 `resources.bench(state, seconds)`）同理不受影响。"""
    rt = _runtime(_config())
    _breaker_armed()
    st = _state(rt, "res-p", "vm-p")
    assert rt.resources.bench(st, 600.0) is True          # 调度器侧的退避 bench
    assert st.circuit_held is False

    zq.circuit_path().unlink()
    assert _row(rt, "res-p")["status"] == "cooldown", "退避观察期被删文件动作提前放行"


def test_a_longer_backoff_after_the_breaker_is_not_released(accounts_root):
    """🔴 所有权换手（最尖的一刀）：熔断按住 1800s 之后，一条**更长**的退避接管 →
    成因归退避 → 删熔断文件**不得**把它放开。

    这条钉的是 `bench()` 的不变量三"成因标记随所有权一起换"。
    只在那一行做"取得所有权时写标记"而漏掉"换手时改回假"，此用例即红。
    """
    rt = _runtime(_config())
    _breaker_armed()
    zq.bench_all_zcode(rt, reason=zq.get_circuit().reason())
    st = _state(rt, "res-z", "vm-z")
    assert st.circuit_held is True

    rt.advance(1.0)
    assert rt.resources.bench(st, 18_000.0) is True       # plan 档退避比熔断更长 → 接管
    assert st.circuit_held is False and st.cooldown_until == pytest.approx(
        1_000_001.0 + 18_000.0), (st.circuit_held, st.cooldown_until)

    zq.circuit_path().unlink()
    row = _row(rt, "res-z")
    assert row["status"] == "cooldown", f"18000s 的退避被一次删文件动作剪掉了：{row}"


def test_shorter_backoff_does_not_take_the_breaker_ownership(accounts_root):
    """🔴 正向对照（不许把上一条当成"万能挡箭牌"）：更短的退避**没**取得所有权 →
    成因仍是熔断 → 删文件后照样放开。"""
    rt = _runtime(_config())
    _breaker_armed()
    zq.bench_all_zcode(rt, reason=zq.get_circuit().reason())
    st = _state(rt, "res-z", "vm-z")

    rt.advance(1.0)
    assert rt.resources.bench(st, 60.0) is False          # 不取得所有权（冷却只延长）
    assert st.circuit_held is True, "更短的退避偷走了熔断的所有权"

    zq.circuit_path().unlink()
    assert _row(rt, "res-z")["status"] == "active"


# ---------- 3) 红线：终态不被放开 ----------

@pytest.mark.parametrize("terminal", ("invalid", "disabled"))
def test_terminal_states_are_never_reopened_by_the_rejudge(accounts_root, terminal):
    """🔴 PRD Q28-⑥③：`invalid`/`disabled` 是终态，删熔断文件后读多少次都不许回 active。

    撤掉 `_lift_if_circuit_cleared` 里 `state.status != "cooldown"` 这一道闸 → 这条红
    （标记在判死之前已经打上了，光看标记会把判死的凭据放回生效集）。
    """
    rt = _runtime(_config())
    _breaker_armed()
    zq.bench_all_zcode(rt, reason=zq.get_circuit().reason())
    st = _state(rt, "res-z", "vm-z")
    assert st.circuit_held is True
    setattr(st, "status", terminal)                       # 判死（终态优先于冷却）

    zq.circuit_path().unlink()
    for _ in range(3):                                    # 反复读也不许翻转
        assert _row(rt, "res-z")["status"] == terminal
        assert st.status == terminal
        assert rt.resources.pick_and_acquire("m-z", set()) is None, \
            f"{terminal} 被重判放回了生效集（终态必须一直挡着）"
    assert st.circuit_held is True, "终态上不得被重判悄悄清掉标记（它本来就不可释放）"


def test_terminal_state_reached_while_the_breaker_holds_is_still_terminal(accounts_root):
    """组合面：判死**之后**才发生的熔断回写也不得把终态改成 cooldown（`bench()` 不变量二）。"""
    rt = _runtime(_config())
    st = _state(rt, "res-z", "vm-z")
    rt.resources.disable(st, "上游返回 401：invalid_api_key")
    _breaker_armed()

    assert zq.bench_all_zcode(rt, reason=zq.get_circuit().reason()) == 0
    assert st.status == "disabled" and st.circuit_held is False, (st.status, st.circuit_held)
    zq.circuit_path().unlink()
    assert _row(rt, "res-z")["status"] == "disabled"


# ---------- 4) fail-closed：状态读不动时一律不释放 ----------

def test_untrusted_breaker_file_is_never_released(accounts_root):
    """🔴 Q28-⑧① 同向：文件**在而读不动** = 未知 = 按熔断拒跑，重判不得放开。

    撤掉 `_circuit_cleared()` 的 fail-closed（或改用 `left_ms()==0` 之类"能算就当没熔断"
    的判据）→ 这条红。
    """
    rt = _runtime(_config())
    path = zq.circuit_path()
    _breaker_armed()
    assert zq.bench_all_zcode(rt, reason=zq.get_circuit().reason()) == 1
    assert _state(rt, "res-z", "vm-z").circuit_held is True

    path.write_text('{"until_ms": true, "reason": "覆盖"}', encoding="utf-8")   # 布尔坏值
    assert zq.get_circuit().untrusted, "本用例的前提是文件读不动（未知档）"
    row = _row(rt, "res-z")
    assert row["status"] == "cooldown", f"未知档被放开 = fail open：{row}"

    path.unlink()                                        # 用户按提示删掉坏文件 → 这才叫已解除
    assert zq.get_circuit().active() is False
    assert _row(rt, "res-z")["status"] == "active"


def test_a_predicate_that_raises_fails_closed(accounts_root):
    """判据本身抛错（ZCode 子模块坏了 / 目录权限）→ 一律不释放。"""
    rt = _runtime(_config())
    st = _state(rt, "res-z", "vm-z")
    with rt.resources.circuit_hold():
        rt.resources.bench(st, COOLDOWN_S)
    assert st.circuit_held is True

    def _boom() -> bool:
        raise RuntimeError("熔断判据崩了")

    rt.resources.circuit_active = _boom
    assert _row(rt, "res-z")["status"] == "cooldown"


# ---------- 5) 生效集（选路）这一处读取 ----------

def test_selection_releases_the_breaker_held_resource_only_when_the_breaker_is_gone(
        accounts_root):
    """🔴 第二处读路径：`pick_and_acquire`。删文件后**下一次选路**就能选中它，
    不必等人打开界面出一次快照；熔断还在时选路**必须**继续绕开。

    撤掉 `pick_and_acquire` 里的重判接线 → 这条红（快照那条用例照样绿，
    因为两处是各自独立的读取入口）。
    """
    rt = _runtime(_config())
    path = zq.circuit_path()
    _breaker_armed()
    zq.bench_all_zcode(rt, reason=zq.get_circuit().reason())

    assert rt.resources.pick_and_acquire("m-z", set()) is None, "观察期内被放进了生效集"

    path.unlink()
    picked = rt.resources.pick_and_acquire("m-z", set())
    assert picked is not None and picked.rid == "res-z", f"删完文件选路仍绕开它：{picked}"
    assert picked.status == "active" and picked.circuit_held is False


# ---------- 6) 跨进程：另一个进程删文件，本进程下一次读就重判 ----------

def test_other_process_deleting_the_file_is_visible_without_restart(accounts_root):
    """🔴 不测成"必须重启"：CLI 进程（另一个 `CooldownManager` 实例，同一个文件）删掉它，
    网关进程下一次读就重判 —— 靠的是 `active()` 每次回读磁盘的既有机制。
    """
    path = zq.circuit_path()
    gateway_side = _breaker_armed()                       # 网关进程这边熔着（同一份文件）
    rt = _runtime(_config())
    assert zq.bench_all_zcode(rt, reason=gateway_side.reason()) == 1
    assert _row(rt, "res-z")["status"] == "cooldown"

    cli_side = zq.CooldownManager(path)                   # 另一个进程（独立实例）
    assert cli_side.active() is True
    path.unlink()                                         # CLI 执行用户要的"删除该文件"

    assert gateway_side.active() is False, "跨进程删除不生效 = 出口只对写它的那个进程有用"
    assert _row(rt, "res-z")["status"] == "active", "本进程没重启就看不见别的进程解除的熔断"


def test_a_new_breaker_written_by_another_process_blocks_the_rejudge(accounts_root):
    """🔴 反向同族：放开之后**另一个进程**又写下新熔断 → 下一次读必须继续挡着
    （重判不是" Once released, forever released"，它每次读都重新问一遍盘）。"""
    path = zq.circuit_path()
    rt = _runtime(_config())
    st = _state(rt, "res-z", "vm-z")
    with rt.resources.circuit_hold():
        rt.resources.bench(st, COOLDOWN_S)
    assert not path.exists() and _row(rt, "res-z")["status"] == "active"

    zq.CooldownManager(path).enter(BREAKER_REASON)        # 另一个进程重新熔上
    assert zq.bench_all_zcode(rt, reason=zq.get_circuit().reason()) == 1
    assert st.circuit_held is True
    assert _row(rt, "res-z")["status"] == "cooldown", "刚写下的新熔断被上一次的重判顶掉了"
    path.unlink()
    assert _row(rt, "res-z")["status"] == "active"


# ---------- 7) 标记的清理（不许残留成假阳性） ----------

def test_a_bench_written_while_the_breaker_is_absent_is_never_registered(accounts_root):
    """🔴 登记只在**熔断真的成立**时发生（`circuit_hold_scope` 里问 `active()`）。

    这条钉的是既有判据 `test_overview_surfaces_circuit_reason`（§17 的接口出口）与新机制
    的交界处：CLI 腿经 `/admin/api/zcode/bench` 回写、而**状态文件不在**（手删过 /
    另一进程没写成功）时，这次冷却就没有"熔断按住"的凭据 —— 若照样登记，
    下一次读立刻把它放开，界面上永远读不到熔断那一行，§17 的可见出口又变空转。
    """
    rt = _runtime(_config())
    assert not zq.circuit_path().exists() and zq.get_circuit().active() is False

    assert zq.bench_all_zcode(rt, reason=BREAKER_REASON) == 1   # 全局回写，但没有熔断凭据
    st = _state(rt, "res-z", "vm-z")
    assert st.status == "cooldown" and st.circuit_held is False, (st.status, st.circuit_held)

    assert _row(rt, "res-z")["status"] == "cooldown", "没有熔断背书的冷却被「重判」放开了"


def test_startup_alignment_registers_the_persisted_breaker(accounts_root):
    """🔴 重启对齐那条路（`sync_circuit_to_runtime`，§17 唯一的启动出口）也要登记成因。

    复现验收 IX-2 的真实场景：熔断在进程外被写下（文件剩 30 分钟）→ 重启后资源被 bench；
    用户随后删文件 → 下一次读就放开。**撤掉这个作用域**（只留 `bench_all_zcode` 那条）
    → 本用例红：文件删了，那一行还要冻满 30 分钟。
    """
    rt = _runtime(_config())
    _breaker_armed()
    assert zq.sync_circuit_to_runtime(rt) == (1, 0)
    st = _state(rt, "res-z", "vm-z")
    assert st.status == "cooldown" and st.circuit_held is True, (st.status, st.circuit_held)
    assert _row(rt, "res-z")["status"] == "cooldown", "熔断仍在，不许放开"

    zq.circuit_path().unlink()
    row = _row(rt, "res-z")
    assert row["status"] == "active", f"重启对齐出来的冷却没被重判：{row}"
    assert row["last_error"] == BREAKER_REASON and "至 " not in row["last_error"], row


def test_no_reset_path_leaves_the_marker_behind(accounts_root):
    """🔴 三条归位/清零路径之后 `circuit_held` 必须为假：
    ① 读时重判解除；② 冷却到期归位；③ 凭据变更把运行态清零（PRD Q28-⑥⑤）。

    残留标记 = 下一条**别的原因**的冷却会被当成"熔断按住的"提前放开（第 1 号坑）。
    逐条撤掉三处清理各自红一次。
    """
    # ① 解除
    rt = _runtime(_config())
    _breaker_armed()
    zq.bench_all_zcode(rt, reason=zq.get_circuit().reason())
    st = _state(rt, "res-z", "vm-z")
    zq.circuit_path().unlink()
    assert _row(rt, "res-z")["status"] == "active"
    assert st.circuit_held is False, "解除后标记残留 = 假阳性"
    assert st.cooldown_until == 0.0, "解除后仍留着熔断那份旧钟点"

    # ② 到期归位
    rt2 = _runtime(_config())
    _breaker_armed()
    zq.bench_all_zcode(rt2, reason=zq.get_circuit().reason())
    st2 = _state(rt2, "res-z", "vm-z")
    assert st2.circuit_held is True
    rt2.advance(COOLDOWN_S + 1)                           # 假钟走过恢复时刻
    assert _row(rt2, "res-z")["status"] == "active"
    assert st2.circuit_held is False, "到期归位后标记残留 = 下一条短冷却会被提前放行"

    # ③ 凭据变更（运行态清零那条路）
    cfg = _config()
    rt3 = _runtime(cfg)
    _breaker_armed()
    zq.bench_all_zcode(rt3, reason=zq.get_circuit().reason())
    st3 = _state(rt3, "res-z", "vm-z")
    assert st3.circuit_held is True and st3.status == "cooldown"
    cfg.resources[0].api_key = "sk-rotated"
    rt3.resources.rebuild(cfg)
    assert (st3.status, st3.cooldown_until, st3.last_error) == ("active", 0.0, None), st3
    assert st3.circuit_held is False, "凭据变更清零后标记残留"


def test_released_cooling_can_be_held_by_the_breaker_again(accounts_root):
    """解除必须可逆：熔断重新建立 → 再次按住 → 再删文件 → 再放开（不是"一次性状态"）。"""
    rt = _runtime(_config())
    path = zq.circuit_path()
    _breaker_armed()
    zq.bench_all_zcode(rt, reason=zq.get_circuit().reason())
    path.unlink()
    assert _row(rt, "res-z")["status"] == "active"

    zq.get_circuit().enter(BREAKER_REASON)                # 新一轮风控
    assert zq.bench_all_zcode(rt, reason=zq.get_circuit().reason()) == 1
    assert _row(rt, "res-z")["status"] == "cooldown"
    path.unlink()
    assert _row(rt, "res-z")["status"] == "active"


# ---------- 8) 机制事实：`/v1/models` 不是释放点（对简报的一处纠正） ----------

def test_breaker_cooldown_never_hid_the_model_from_the_listing(accounts_root):
    """🔴 钉住机制事实：`servable_models` 只把 `disabled`/`invalid` 判为不可服务，
    `cooldown`（熔断回写的落点）**一直是可服务** —— 所以"模型被 /v1/models 隐藏"
    不是本缺陷的表现，这条读路径也不需要接重判（接了只是多一次磁盘回读）。

    若哪天有人把熔断改成 `disable`（隐藏模型），这条会红，逼作者重新对齐口径。
    """
    rt = _runtime(_config())
    _breaker_armed()
    zq.bench_all_zcode(rt, reason=zq.get_circuit().reason())
    registry = rt.resources.registry
    assert _state(rt, "res-z", "vm-z").status == "cooldown"
    assert servable_models(rt.config, registry) == {"m-z", "m-p"}, \
        "熔断期内模型被隐藏（与 BUG-1 口径冲突）"
    zq.circuit_path().unlink()
    assert _row(rt, "res-z")["status"] == "active"
    assert servable_models(rt.config, registry) == {"m-z", "m-p"}


# ---------- 9) 端到端：真实装配的网关（管理端点 + 总览接口） ----------

def test_running_gateway_rejudges_after_the_user_deletes_the_file(tmp_path, accounts_root):
    """🔴 真 `create_app` 一条链：CLI 腿经 `/admin/api/zcode/bench` 回写 →
    总览接口显示 cooldown → 删文件 → **同一次运行**里下一次读就是 active。

    这条同时钉住三处接线，任何一处撤掉都红：
    ① `main.py` 的 `Runtime._wire_circuit_rejudge`（判据注入）；
    ② `api/admin.py` 的成因声明（`circuit_hold_scope`）；
    ③ `snapshot_by_resource` 的第二个释放条件。
    """
    from fastapi.testclient import TestClient

    from model_gateway.main import create_app

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "resources": [{"id": "res-z", "name": "Z号", "account": ACCOUNT,
                       "product": "zcode", "account_ref": ACCOUNT, "access_mode": "api",
                       "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-1"}],
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": "res-z", "model": "vm-z"}]}],
        "gateway": {"zcode": {"claim_interval_seconds": 0}},
    }, allow_unicode=True), encoding="utf-8")
    app = create_app(config_path=cfg_path, usage_dir=tmp_path / "usage",
                     enums_path=tmp_path / "enums.yaml")
    runtime = app.state.runtime
    assert runtime.resources.circuit_active is not None, "装配侧没接熔断判据 = 本用例白跑"

    with TestClient(app) as client:
        zq.get_circuit().enter(BREAKER_REASON)            # 熔断已在状态文件里（CLI 侧写的）
        benched = client.post("/admin/api/zcode/bench",
                              json={"scope": "global"}).json()
        assert benched["benched"] == 1 and benched["circuit_held"] is True, benched

        row = _http_row(client)
        assert row["status"] == "cooldown" and row["cooldown_remaining_ms"] > 0, row
        assert row["last_error"].startswith(BREAKER_REASON), row

        zq.circuit_path().unlink()                        # 用户执行手动出口
        free = _http_row(client)
        assert free["status"] == "active", f"接口仍按旧钟点冻结：{free}"
        assert free["cooldown_remaining_ms"] == 0, free
        assert free["last_error"] == BREAKER_REASON, free   # 历史线索留着，不带钟点


def test_endpoint_can_declare_a_non_breaker_cause(tmp_path, accounts_root):
    """🔴 成因由调用方**显式**声明：带 `"circuit": false` 的回写不属于熔断，
    删文件不得放开它（端点侧不靠 `reason` 文案猜成因）。"""
    from fastapi.testclient import TestClient

    from model_gateway.main import create_app

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "resources": [{"id": "res-z", "name": "Z号", "account": ACCOUNT,
                       "product": "zcode", "account_ref": ACCOUNT, "access_mode": "api",
                       "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-1"}],
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": "res-z", "model": "vm-z"}]}],
        "gateway": {"zcode": {"claim_interval_seconds": 0}},
    }, allow_unicode=True), encoding="utf-8")
    app = create_app(config_path=cfg_path, usage_dir=tmp_path / "usage",
                     enums_path=tmp_path / "enums.yaml")
    with TestClient(app) as client:
        zq.get_circuit().enter(BREAKER_REASON)
        body = client.post("/admin/api/zcode/bench",
                           json={"scope": "global", "circuit": False,
                                 "reason": "手工挡一段"}).json()
        assert body["benched"] == 1 and body["circuit_held"] is False, body
        st = next(iter(app.state.runtime.resources.registry.values()))
        assert st.status == "cooldown" and st.circuit_held is False, (st.status, st.circuit_held)

        zq.circuit_path().unlink()
        row = _http_row(client)
        assert row["status"] == "cooldown", f"非熔断成因被删文件动作放开：{row}"


def _http_row(client) -> dict:
    payload = client.get("/admin/api/status").json()
    row = next((r for r in payload["resources"] if r["rid"] == "res-z"), None)
    assert row is not None, payload
    return row
