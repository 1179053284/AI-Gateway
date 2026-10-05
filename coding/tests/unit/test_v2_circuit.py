"""v2.0 §17 · 3012 **全局熔断**与 10s 节流的单元测试（返工第 1 项）。

方案原文：「熔断 | 3012 风控 → **全局熔断 30 分钟**，节流 10s，状态落盘」（§17 关键决策，依据 `18` §③）。

三个必须被钉住的点：
1. **落盘用的必须是墙上时钟** —— 存 `time.monotonic()` 的状态跨重启无意义（单调钟基准是开机），
   熔断会永久生效或永不生效；
2. **全局** = 对**全部** ZCode 账号一并回写，不是只 bench 命中那一个号；
3. 熔断中**不得再打上游**（继续换号打只会延长风控），且用户要看得见"被什么挡住、还剩多久"。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from pathlib import Path

import pytest

from model_gateway.ops.builtin import zcode_claim
from model_gateway.upstream.zcode import claim as claim_mod
from model_gateway.upstream.zcode import quota as zq

ACCOUNT = "acct-a"


@pytest.fixture
def accounts_root(tmp_path, monkeypatch):
    root = tmp_path / "accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    from model_gateway.upstream.zcode.dataroot import v2_dir_of
    for name in ("acct-a", "acct-b"):
        v2 = v2_dir_of(root, name)
        v2.mkdir(parents=True, exist_ok=True)
        (root / name / "meta.json").write_text(json.dumps({"device_mid": f"mid-{name}"}),
                                               encoding="utf-8")
        (v2 / "credentials.json").write_text(json.dumps({
            "oauth:active_provider": "zai", "zcodejwttoken": f"jwt-{name}"}), encoding="utf-8")
    return root


class _Plan:
    plan_id = "p1"


class _Client:
    """记录上游是否真的被调用（熔断生效的判据就是"没被调用"）。"""

    def __init__(self, outcome=None):
        self._outcome = outcome or claim_mod.ClaimOutcome(code=0)
        self.previewed = 0

    async def preview(self):
        self.previewed += 1
        return _Plan()

    async def claim(self, plan_id, *, manual=False):
        return self._outcome

    async def report_activation(self, *, user_id=""):
        pass

    async def aclose(self):
        pass


def run_claim(account=ACCOUNT, outcome=None, *, runtime=None, client=None):
    client = client or _Client(outcome)
    res = asyncio.run(zcode_claim.claim(account, client_factory=lambda: client,
                                        runtime=runtime))
    return res, client


class _FakeMgr:
    def __init__(self):
        self.benched: list[tuple[str, str]] = []

    def bench(self, state, seconds) -> bool:
        """返回值必须与真实 `ResourceManager.bench() -> bool` 同契约（验收 S-16）。

        假件悄悄返回 None 时，任何依赖"是否取得冷却所有权"的生产分支
        在测试里都会走成假的那一边 —— 这类"假件契约不符"是判据空过的常见来源。
        """
        state.status = "cooldown"
        return True


class _FakeRuntime:
    """最小 runtime：只给 `config`（资源→账号映射来源）与 `resources.registry`。"""

    def __init__(self, resources: dict[str, str]):
        from model_gateway.config.schemas import AppConfig
        self.config = AppConfig.model_validate({
            "resources": [{"id": rid, "name": rid, "account": acct,
                           "base_url": "http://127.0.0.1:9/v1", "api_key": "sk"}
                          for rid, acct in resources.items()],
            # 注册表按 (资源, 供应商模型名) 建索引 —— 没有模型映射就没有 ResourceState，
            # bench 也就无从落点（这是 `apply_to_resource` 的遍历口径，不是笔误）
            "models": [{"name": "m", "endpoint": "chat", "resources": [
                {"resource": rid, "model": f"vm-{rid}"} for rid in resources]}]})
        self.resources = _FakeMgr()


# ---------- 1) 落盘时钟必须是 epoch ----------

def test_circuit_persists_wall_clock_not_monotonic(tmp_path: Path):
    """🔴 反证目标：把 `_epoch_ms` 换成 `time.monotonic` 这条必须红。

    熔断状态存在的意义就是"重启后仍知道自己在熔断"，
    而单调钟在重启后归零 —— 存它的值等于存随机数。
    """
    path = tmp_path / "cd.json"
    cm = zq.CooldownManager(path)
    cm.enter("risk")
    raw = json.loads(path.read_text(encoding="utf-8"))
    expected = time.time() * 1000 + zq.COOLDOWN_MS
    assert abs(raw["until_ms"] - expected) < 5000, (
        f"until_ms={raw['until_ms']} 不是墙上时钟口径（应为≈{expected}）")
    assert raw["until_ms"] > 1e12            # epoch 毫秒量级；monotonic 在本机是几小时~几天


def test_circuit_survives_new_instance_and_expires(tmp_path: Path):
    """新实例（模拟重启/另一进程）读到同一文件即视为熔断中；过 31 分钟后自动失效。"""
    path = tmp_path / "cd.json"
    base = time.time() * 1000
    zq.CooldownManager(path, now=lambda: base).enter("风控")
    assert zq.CooldownManager(path, now=lambda: base + 1000).active() is True
    assert zq.CooldownManager(path, now=lambda: base + zq.COOLDOWN_MS + 1000).active() is False


def test_active_is_live_read_from_disk(tmp_path: Path):
    """已在内存里建好的实例也要能看见**别的进程**刚写入的熔断（按 mtime 回读，不加 watcher）。"""
    path = tmp_path / "cd.json"
    first = zq.CooldownManager(path)
    second = zq.CooldownManager(path)
    assert first.active() is False
    second.enter("风控")
    assert first.active() is True, "跨进程写入的熔断状态没被读到"


# ---------- 2) 熔断中不得再打上游 ----------

def test_claim_skipped_while_circuit_active(accounts_root, monkeypatch):
    """熔断中：本轮**不发上游请求**，且告知剩余时间与原因（不得静默跳过）。"""
    zq.get_circuit().enter("ZCode 风控熔断（30min，全局）")
    client = _Client()
    res, client = run_claim(outcome=claim_mod.ClaimOutcome(code=0), client=client)
    assert res.category == "inactive"
    assert "熔断" in res.detail and "分钟" in res.detail
    assert client.previewed == 0, "熔断中仍打上游 = 风控只会继续延长"


def test_throttle_records_each_upstream_round(accounts_root):
    """10s 节流：每轮领取都要更新"上次调用时间"，否则节流形同虚设。"""
    cm = zq.get_circuit()
    assert cm.throttle_wait_ms() == 0          # 全新状态：从未调用
    run_claim(outcome=claim_mod.ClaimOutcome(code=0))
    assert cm.throttle_wait_ms() > 0, "调用后未记账 → 节流永不生效"


# ---------- 3) 命中 3012 → 全局熔断 + 全部账号回写 ----------

def test_risk_control_enters_circuit_and_benches_all_accounts(accounts_root, monkeypatch):
    """🔴 全局口径（§17）：一个号命中风控，**所有** ZCode 账号的资源一并 bench。"""
    rt = _FakeRuntime({"res-a": "acct-a", "res-b": "acct-b"})
    benched: list[str] = []

    def fake_bench_all(runtime, *, reason, seconds=None, only_accounts=None):
        benched.append(reason)
        return 2

    monkeypatch.setattr(zq, "bench_all_zcode", fake_bench_all)
    res, _ = run_claim(outcome=claim_mod.ClaimOutcome(code=zq.CODE_RISK_CONTROL,
                                                     message="unusual activity"),
                       runtime=rt)
    assert res.category == "failed"
    # 🔴 回写的原因串必须是 `enter()` 规范后的那条（带 `至 HH:MM`），不是裸常量。
    # 原先这里断的正是 `GLOBAL_BENCH_REASON` —— 等于把"实时命中的资源看不出几点恢复"
    # 钉成了标准（面板 S-6：§17 的可见性收益只在重启后出现，落在错的一半路径上）。
    assert len(benched) == 1
    assert benched[0] == zq.get_circuit().reason()
    assert benched[0].startswith(zcode_claim.GLOBAL_BENCH_REASON)
    assert re.search(r"，至 (?:明日 )?\d{2}:\d{2}$", benched[0]), benched[0]
    assert zq.get_circuit().active() is True


def test_risk_control_from_cli_posts_global_scope(accounts_root, monkeypatch):
    """CLI 腿（独立进程）：熔断状态自己写文件，但**资源回写**必须让网关来做，且要带全局口径。"""
    import model_gateway.core.local_admin as local_admin

    calls: list[dict] = []
    monkeypatch.setattr(local_admin, "admin_post",
                        lambda path, **kw: calls.append({"path": path, **kw}) or {"ok": True})
    run_claim(outcome=claim_mod.ClaimOutcome(code=zq.CODE_RISK_CONTROL,
                                             message="异常活动"), runtime=None)
    assert calls[0]["path"] == "/admin/api/zcode/bench"
    assert calls[0]["payload"]["scope"] == "global"
    # CLI 腿经 HTTP 让**网关**回写：带过去的 reason 同样必须已带恢复时刻
    assert re.search(r"，至 (?:明日 )?\d{2}:\d{2}$", calls[0]["payload"]["reason"]), calls[0]["payload"]
    assert zq.get_circuit().active() is True, "CLI 进程也必须落熔断状态（共享文件）"


def test_message_only_risk_control_still_trips_circuit(accounts_root, monkeypatch):
    """上游只把风控写在 message 里（码值漂移）时也要熔断 —— 判据是码**或**文案。"""
    import model_gateway.core.local_admin as local_admin

    monkeypatch.setattr(local_admin, "admin_post", lambda path, **kw: {"ok": True})
    run_claim(outcome=claim_mod.ClaimOutcome(code=-1, message="检测到 unusual activity"),
              runtime=None)
    assert zq.get_circuit().active() is True


def test_non_risk_failure_does_not_enter_circuit(accounts_root):
    """网络错/业务失败**不是**风控：不得误触发 30 分钟全局熔断（那会把好账号一起锁死）。"""
    res, _ = run_claim(outcome=claim_mod.ClaimOutcome(code=1005, message="今日名额已用完"))
    assert res.category == "inactive"
    assert zq.get_circuit().active() is False


def test_bench_all_zcode_returns_zero_when_no_accounts(accounts_root, monkeypatch):
    """账号根为空 → 全局回写返回 0，不抛（无账号时熔断仍要能记账）。"""
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(accounts_root / "nothing"))
    assert zq.bench_all_zcode(_FakeRuntime({}), reason="ZCode 风控熔断（30min，全局）") == 0


# ---------- 资源级「最近错误」的取谁（design-spec §2.1 要求的那一列）----------

class _S:
    """最小条目假件：`_rendered_last_error` 除 status/last_error/C 还要读 `cooldown_until`。

    🔴 假件契约必须跟着真实 `ResourceState` 长（验收 S-16）：判据改成"读时渲染"之后，
    少了 `cooldown_until` 就是拿一个生产里不存在的对象在测。
    """

    def __init__(self, status, last_error, C=0, cooldown_until=0.0):
        self.status, self.last_error, self.C = status, last_error, C
        self.cooldown_until = cooldown_until


def test_worst_error_prefers_the_non_healthy_entry():
    """同资源多映射时，取**最严重条目**的原因 —— 别让 active 条目的空值盖掉熔断说明。"""
    from model_gateway.core.resources import _rendered_last_error

    entries = [_S("active", "很久以前的普通失败", C=0),
               _S("cooldown", "ZCode 风控熔断（30min，全局）")]
    with _frozen_wallclock(0):
        got = _rendered_last_error(entries, "cooldown", 60_000)
        # 钟点本身跨时区不确定（本地化），此处只钉"冷却中必带且只带一个钟点"；
        # 跨午夜/到期后的具体读法由 `test_health_card_renders_the_clock_at_read_time` 钉
        assert got.startswith("ZCode 风控熔断（30min，全局），至 ")
        assert re.search(r"，至 (?:明日 )?\d{2}:\d{2}$", got or ""), got
    assert _rendered_last_error([_S("active", None)], "active", 0) is None
    assert _rendered_last_error([], "active", 0) is None


def test_worst_error_uses_severity_then_failure_count():
    from model_gateway.core.resources import _rendered_last_error

    # invalid 比 cooldown 严重（凭据已失效 ≠ 只是暂时冷却）
    assert _rendered_last_error([_S("cooldown", "冷却中"),
                                 _S("invalid", "Key 无效")], "invalid", 0) == "Key 无效"
    # 同严重度时取连续失败更多的（更接近用户要排查的那条）
    assert _rendered_last_error([_S("cooldown", "轻", C=1),
                                 _S("cooldown", "重", C=9)],
                                "cooldown", 0) == "重"


def test_health_card_renders_the_clock_at_read_time():
    """🔴 界面那一句话与 CLI 必须**同一把尺**（第七轮 B-1：S-21 只修了一半）。

    冻结三个读取时刻，同一个冷却对象给出的钟点必须一致：
    23:50 熔 30 分钟 → 23:55 读「至 明日 00:20」、00:05 读「至 00:20」；
    到期之后（S-15 定稿「最近错误」不清空）**不得**再挂一个过去的钟点。
    """
    from model_gateway.core.resources import _rendered_last_error, fmt_recovery_clock

    t2350 = _frozen_ms(2026, 9, 28, 23, 50) / 1000        # epoch **秒**（与 clock() 同单位）
    until = t2350 + 1800                                   # 00:20（次日）
    entry = _S("cooldown", "ZCode 风控熔断（30min，全局）", cooldown_until=until)

    with _frozen_wallclock((t2350 + 300) * 1000):
        at_2355 = _rendered_last_error([entry], "cooldown", 1500_000)
    assert at_2355.endswith("，至 明日 00:20"), at_2355
    with _frozen_wallclock((t2350 + 900) * 1000):
        at_0005 = _rendered_last_error([entry], "cooldown", 900_000)
    assert at_0005.endswith("，至 00:20") and "明日" not in at_0005, at_0005

    # 与 CLI 那一侧同源：`circuit.reason()` 走的也是 `fmt_recovery_clock`
    assert fmt_recovery_clock(until, t2350 + 900) == "00:20"
    assert fmt_recovery_clock(until, t2350 + 300) == "明日 00:20"

    # 冷却已到期：原因作为"历史线索"留着，但**不得**再说一个已经过去的钟点
    assert _rendered_last_error([_S("active", entry.last_error,
                                    cooldown_until=until)],
                                "active", 0) == "ZCode 风控熔断（30min，全局）"


def test_snapshot_exposes_last_error_for_the_health_card(accounts_root):
    """`snapshot_by_resource()` 必须带 `last_error` —— 它是熔断原因的唯一出口。

    🔴 本轮重做（面板 R5）：原写法手工把 `status` 设成 `"cooldown"`、`last_error` 手填，
    再断 `cooldown_remaining_ms >= 0`（恒真）—— 证的是测试自己搭的假数据，不是生产路径。
    现在走**真实回写函数** `quota.apply_to_resource`（管理端点 `/admin/api/zcode/bench`
    调的就是它），并断"原因串真的到快照里"。
    """
    rt = _RealMgrRuntime({"res-a": "acct-a"})
    n = zq.apply_to_resource(rt, ["res-a"], reason="ZCode 风控熔断（30min，全局）")

    assert n == 1
    row = rt.resources.snapshot_by_resource(rt.config)[0]
    assert row["last_error"].startswith("ZCode 风控熔断（30min，全局）")
    # 🔴 恢复时刻在**读时**由快照渲染（验收 S-23），所以这一列现在自带「，至 …」
    assert re.search(r"，至 (?:明日 )?\d{2}:\d{2}$", row["last_error"]), row["last_error"]
    assert row["status"] == "cooldown"
    assert row["cooldown_remaining_ms"] > 60_000        # 缺省 30 分钟，不是 0
    assert row["available"] is False


def test_terminal_states_are_not_revived_by_a_cooldown(accounts_root):
    """🔴 `invalid` / `disabled` 是终态：任何临时冷却都不得把它们改回可服务（面板 S-2）。

    tech-design:140 定义 `disabled`=手动/401 停用、`invalid`=404 模型无效；
    :452 的生效集口径是"跳过 cooldown/disabled/invalid"。原先 `bench()` 无条件
    覆盖 status → 被 401 判死的凭据一次额度 tick 后就重新被 `servable_models` 下发。
    """
    from model_gateway.core.resources import servable_models

    for terminal in ("invalid", "disabled"):
        rt = _RealMgrRuntime({"res-a": "acct-a"})
        st = next(iter(rt.resources.registry.values()))
        setattr(st, "status", terminal)
        assert servable_models(rt.config, rt.resources.registry) == set()

        snap = zq.QuotaSnapshot(account="acct-a", buckets=[
            zq.Bucket(show_name="通用", period="5h", total=100, used=100, available=0)])
        assert zq.apply_snapshot_to_runtime(rt, "acct-a", snap) == 1   # 额度池照样写
        assert st.status == terminal, f"{terminal} 被冷却覆盖成 {st.status}"
        # 🔴 原先这里断 `last_error is None`，而它**从来没被写过** —— 恒真的搭车断言。
        # 改成"先立一个原因，再要求短回写不得改写它"，才是 S-2/S-3 的完整语义。
        st.last_error = "上游返回 401：invalid_api_key"
        zq.apply_to_resource(rt, ["res-a"], reason="ZCode 额度耗尽", seconds=60.0)
        assert st.last_error == "上游返回 401：invalid_api_key", "终态原因被后到的短原因改写"
        assert st.status == terminal
        assert st.quota.remaining == 0
        assert servable_models(rt.config, rt.resources.registry) == set()


def test_changed_credential_clears_the_terminal_state(accounts_root):
    """🔴 恢复路径（面板 S-2「invalid/401 永不自愈」）：改过 Key/base_url = 新连接身份。

    原实现里 `invalid`/`disabled` **没有任何**恢复入口 —— 用户把失效的 Key 改对了，
    资源仍永远躺在生效集外，只能重启进程。tech §8-4 的"热重载保状态"保的是
    **同一条连接**的冷却计数，换凭据后保留旧判死结果没有意义。
    """
    from model_gateway.core.resources import servable_models

    rt = _RealMgrRuntime({"res-a": "acct-a"})
    st = next(iter(rt.resources.registry.values()))
    rt.resources.invalidate(st)
    st.last_error = "上游返回 401：invalid_api_key"
    rt.resources.rebuild(rt.config)                     # 同凭据重载 → 判死结果保留
    assert st.status == "invalid" and st.last_error

    rt.config.resources[0].api_key = "sk-new-key"       # 用户改了 Key
    rt.resources.rebuild(rt.config)
    assert st.status == "active", "改对凭据后仍判死 = 只能靠重启"
    assert st.last_error is None and st.C == 0 and st.cooldown_until == 0.0
    assert servable_models(rt.config, rt.resources.registry) == {"m"}


def test_same_credential_reload_keeps_runtime_state(accounts_root):
    """🔴 正向对照：凭据**没变**时热重载不得清空冷却/失败计数（tech §8-4）。"""
    rt = _RealMgrRuntime({"res-a": "acct-a"})
    st = next(iter(rt.resources.registry.values()))
    rt.resources.bench(st, 600.0)
    st.C = 3
    left = st.cooldown_until

    rt.resources.rebuild(rt.config)
    assert st.status == "cooldown" and st.cooldown_until == left and st.C == 3


# ---------- 5) IX-2：熔断的**用户可见出口**（文案带恢复时刻 + 重启后仍生效）----------


class _RealMgrRuntime:
    """给 `bench_all_zcode` 用的最小 runtime：真 `ResourceManager` + 配置里的账号映射。"""

    def __init__(self, resources: dict[str, str]):
        from model_gateway.config.schemas import AppConfig
        from model_gateway.core.resources import ResourceManager

        self.config = AppConfig.model_validate({
            "resources": [{"id": rid, "name": rid, "account": acct,
                           "access_mode": "api",
                           "base_url": "http://127.0.0.1:9/v1", "api_key": "sk"}
                          for rid, acct in resources.items()],
            # 注册表按 (资源, 供应商模型名) 建索引 —— 没有模型映射就没有 ResourceState，
            # bench 也就无从落点（这是 `apply_to_resource` 的遍历口径，不是笔误）
            "models": [{"name": "m", "endpoint": "chat", "resources": [
                {"resource": rid, "model": f"vm-{rid}"} for rid in resources]}]})
        self.resources = ResourceManager()
        self.resources.rebuild(self.config)


def test_enter_reason_carries_the_recovery_clock():
    """§17 字面要求 `ZCode 风控熔断（30min，至 HH:MM）`——只写时长要用户自己算起点。"""
    import re

    zq.get_circuit().enter("ZCode 风控熔断（30min，全局）")
    reason = zq.get_circuit().reason()
    assert "风控熔断" in reason
    m = re.search(r"至 (?:明日 )?(\d{2}):(\d{2})$", reason)
    assert m, f"文案缺恢复时刻：{reason}"
    expect = time.localtime((time.time() + zq.COOLDOWN_MS / 1000))
    assert (int(m.group(1)), int(m.group(2))) == (expect.tm_hour, expect.tm_min), reason


@contextlib.contextmanager
def _frozen_wallclock(until_ms: float):
    """把 `time.time` 冻住（渲染恢复时刻唯一可测的方式）。

    🔴 生产侧不再有 `wall_now` 这类"只为测试存在的参数"（第九轮 eng N-1）：
    那个参数一旦被调用方误传成 manager 自己的钟，S-28 那个假钟点就原地复活，
    而所有判据仍然全绿 —— 没有护栏的测试入口就是一个待爆的缺陷。
    """
    real = time.time
    time.time = lambda: until_ms / 1000
    try:
        yield
    finally:
        time.time = real


def _frozen_ms(y, mo, d, h, mi) -> float:
    """本地时刻冻结成 epoch 毫秒（时钟文案只能在固定时刻上判）。"""
    return time.mktime(time.struct_time((y, mo, d, h, mi, 0, 0, 0, -1))) * 1000


def test_recovery_clock_says_next_day_when_it_crosses_midnight(tmp_path):
    """🔴 23:50 熔 30 分钟要写"至 明日 00:20"（验收 S-21 / 用户裁决）。

    写"至 00:20"时，用户在 23:55 看到的那串钟点**已经在今天之前**了：
    读起来像"马上就好"，实际还要等到过了午夜 —— 这是会让人误判要不要重跑的一句。
    """
    cm = zq.CooldownManager(tmp_path / "c.json",
                            now=lambda: _frozen_ms(2026, 9, 28, 23, 50))
    cm.enter("ZCode 风控熔断（30min，全局）")
    assert cm.reason().endswith("，至 明日 00:20"), cm.reason()


def test_recovery_clock_stays_plain_clock_time_within_the_day(tmp_path):
    """🔴 正向对照（不许把"明日"改成恒加）：12:00 熔 30 分钟就是"至 12:30"。"""
    cm = zq.CooldownManager(tmp_path / "c.json",
                            now=lambda: _frozen_ms(2026, 9, 28, 12, 0))
    cm.enter("ZCode 风控熔断（30min，全局）")
    assert cm.reason().endswith("，至 12:30"), cm.reason()
    assert "明日" not in cm.reason()


def test_recovery_clock_is_recomputed_at_the_moment_of_reading(tmp_path):
    """🔴 同一条落盘熔断，午夜前/午夜后**各读各的**都成立（S-21：不许把时刻烘进文件）。

    23:50 熔的 30 分钟若在写入时就把"明日"钉进字符串，00:05 再读界面会显示
    "至 明日 00:20" —— 而那时 00:20 是**15 分钟后**。文件里只存裸原因，
    读的时候按当时的钟点拼，才可能两边都对。
    """
    path = tmp_path / "c.json"
    base = _frozen_ms(2026, 9, 28, 23, 50)
    zq.CooldownManager(path, now=lambda: base).enter("ZCode 风控熔断（30min，全局）")

    before_midnight = zq.CooldownManager(path, now=lambda: base + 5 * 60_000)
    assert before_midnight.reason().endswith("，至 明日 00:20"), before_midnight.reason()

    after_midnight = zq.CooldownManager(path, now=lambda: base + 15 * 60_000)
    assert after_midnight.reason().endswith("，至 00:20"), after_midnight.reason()
    assert "明日" not in after_midnight.reason()
    # 落盘的仍然是裸原因（跨进程读来即可重算，不依赖写入方的钟点）
    assert "明日" not in path.read_text(encoding="utf-8")


def test_recovery_clock_is_rendered_from_the_wall_clock_not_the_manager_clock():
    """🔴 时基回归（第八轮 PM 与 eng-8a **各自独立**打到）。

    `ResourceManager()` 生产默认钟是 `time.monotonic` —— 开机以来的秒数（本机约 70 万），
    拿它当 epoch 交给 `time.localtime` 渲染，界面那一行会写「至 10:53」而当时是 15:18、
    真实恢复 15:48；「明日」分支也因此几乎永不触发。
    S-23 上一轮把**公式**修对了、**时基**用错了，而全套判据当时全绿 ——
    原因是每条测试都注入了 epoch 钟。本用例**故意不注入**，用生产默认钟跑。
    """
    from model_gateway.config.schemas import AppConfig
    from model_gateway.core.resources import ResourceManager

    cfg = AppConfig.model_validate({
        "resources": [{"id": "res-a", "name": "A", "account": "a", "access_mode": "api",
                       "base_url": "http://127.0.0.1:9/v1", "api_key": "sk"}],
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": "res-a", "model": "vm"}]}]})
    mgr = ResourceManager()                 # ← 默认钟：time.monotonic
    assert mgr.clock.__name__ == "monotonic", "本用例的意义依赖于生产默认钟"
    mgr.rebuild(cfg)
    st = mgr.registry[("res-a", "vm")]
    assert mgr.bench(st, 1800.0)
    st.last_error = "ZCode 风控熔断（30min，全局）"

    row = mgr.snapshot_by_resource(cfg)[0]
    rem_s = row["cooldown_remaining_ms"] / 1000
    target = time.time() + rem_s
    want = time.strftime("%H:%M", time.localtime(target))
    # 🔴 跨午夜那一档必须按**渲染规则**算，不能只比 `%H:%M`（本轮复跑在 23:3x 抓到）：
    #    Q28-⑦① 定版「同日 `至 HH:MM` / 跨日 `至 明日 HH:MM`」，而旧写法在 23:30~00:00
    #    这半小时窗口里必然红 —— 1800s 冷却跨过午夜，界面写「至 明日 00:0x」，
    #    期望串却只算出「至 00:0x」。判据跟着被测口径走才算钉住，否则每天夜里假红一次。
    day_prefix = "明日 " if time.localtime(target).tm_mday != time.localtime().tm_mday else ""
    assert row["last_error"].endswith(f"，至 {day_prefix}{want}"), (row["last_error"], want)
    # 反向：单调钟的数值直接格式化会是 1970 年的某个清晨 —— 绝不能出现在界面上
    bogus = time.strftime("%H:%M", time.localtime(st.cooldown_until))
    assert not row["last_error"].endswith(bogus), row["last_error"]


def test_the_two_columns_never_disagree_about_the_recovery_instant():
    """🔴 「冷却剩余」列与「最近错误」列必须指**同一个瞬间**（第八轮 ix，S-31）。

    原先钟点取自"最严重条目"自己的到期时间，而剩余列取所有条目的最大值：
    同一行会出现「1800s 后自动回池」+「至 23:51」，用户必须自己裁决信哪个。
    现在两处都用聚合后的同一个 `cooldown_remaining_ms`。
    """
    from model_gateway.config.schemas import AppConfig
    from model_gateway.core.resources import ResourceManager

    cfg = AppConfig.model_validate({
        "resources": [{"id": "res-a", "name": "A", "account": "a", "access_mode": "api",
                       "base_url": "http://127.0.0.1:9/v1", "api_key": "sk"}],
        "models": [{"name": "m", "endpoint": "chat", "resources": [
            {"resource": "res-a", "model": "vm-fast"},
            {"resource": "res-a", "model": "vm-slow"}]}]})
    mgr = ResourceManager()
    mgr.rebuild(cfg)
    fast, slow = (mgr.registry[("res-a", "vm-fast")], mgr.registry[("res-a", "vm-slow")])
    mgr.bench(fast, 60.0)
    fast.last_error = "上游限流，冷却中"
    mgr.bench(slow, 1800.0)
    slow.last_error = "ZCode 风控熔断（30min，全局）"

    row = mgr.snapshot_by_resource(cfg)[0]
    assert row["status"] == "cooldown" and row["cooldown_remaining_ms"] > 1_700_000, row
    target = time.time() + row["cooldown_remaining_ms"] / 1000
    want = time.strftime("%H:%M", time.localtime(target))
    # 🔴 同上一条：跨午夜那半小时里渲染是「至 明日 HH:MM」，期望串必须跟渲染规则一起算，
    #    否则这个判据每天夜里假红一次（本轮 23:4x 复跑抓到，与本用例的立意无关）。
    day_prefix = "明日 " if time.localtime(target).tm_mday != time.localtime().tm_mday else ""
    assert row["last_error"].endswith(f"，至 {day_prefix}{want}"), row["last_error"]
    assert "60s" not in row["last_error"], row["last_error"]      # 不得用短冷却的钟点


def test_legacy_circuit_file_does_not_double_the_clock(tmp_path):
    """🔴 旧格式 `circuit.json`（时刻烘在 reason 里）读进来不得拼成两个时刻（第七轮 eng）。

    升级前留下的文件里 reason 已含「，至 14:38」；`reason()` 现在自己会追加一份，
    不剥旧尾巴就是「ZCode 风控熔断（30min，全局），至 14:38，至 15:38」——
    一行里两个钟点、且第一个是**已经过去**的时间，用户照着它判断何时重试必然判错。
    """
    p = tmp_path / "circuit.json"
    now_ms = _frozen_ms(2026, 9, 28, 15, 0)
    p.write_text(json.dumps({
        "until_ms": now_ms + 1_800_000,
        "reason": "ZCode 风控熔断（30min，全局），至 14:38",      # 旧版烘死的串
        "last_call_ms": now_ms - 60_000,
    }), encoding="utf-8")

    cm = zq.CooldownManager(p, now=lambda: now_ms)
    assert cm.active() is True
    reason = cm.reason()
    assert reason.count("至 ") == 1, f"拼出了两个恢复时刻：{reason}"
    assert "14:38" not in reason, reason
    assert reason.endswith("，至 15:30"), reason

    # 同一条原因被回写进资源态时也只有一份钟点（`apply_to_resource` 存裸串）
    rt = _RealMgrRuntime({"res-a": "acct-a"})
    zq.apply_to_resource(rt, ["res-a"], reason=reason)
    row = rt.resources.snapshot_by_resource(rt.config)[0]
    assert row["last_error"].count("至 ") == 1, row["last_error"]
    assert "14:38" not in row["last_error"]

    # 🔴 下一次写盘必须把旧格式**归一化**掉（`mark_called` 会整份重写状态文件）：
    #    读盘时不剥尾巴，这里就会把「，至 14:38」原样又存回去，旧格式永远出不干净。
    cm.mark_called()
    stored = json.loads(p.read_text(encoding="utf-8"))
    assert "14:38" not in stored["reason"], stored


def test_malformed_circuit_numbers_do_not_crash_the_cli(tmp_path):
    """🔴 状态文件里的数字坏掉（人手改过 / 半写）只能"当读不动"，不许 traceback（第八轮 S-26①）。

    `active()`/`reason()` 每次判定都会读这个文件；原实现 `float(...)` 直接抛
    `ValueError`/`TypeError` → `mgw zcode claim` 整条命令崩栈。
    第九轮 eng N-2 之后语义再收紧一步：**坏值不得顺手把熔断清零**（那会打开双领窗口），
    处理方式与"文件读不动"完全一致。
    """
    p = tmp_path / "circuit.json"
    p.write_text(json.dumps({"until_ms": "not-a-number", "reason": "X",
                             "last_call_ms": None}), encoding="utf-8")
    cm = zq.CooldownManager(p)
    # 🔴 方向由第十一轮 eng-A BLK-2 翻正：文件**在**而读不动 = 未知，未知按最坏处理
    #    （拒跑），不再是"新进程无内存态 → 按无熔断起"。原口径是 fail-open，
    #    而且放行之后 `mark_called()` 还会把别的进程留下的熔断凭据整盘覆盖掉。
    assert cm.active() is True, "读不动却放行 = fail open"
    assert "至 " not in cm.reason(), "时长未知时不许编一个钟点出来"
    assert "删除" in cm.reason() and "circuit.json" in cm.reason(), "必须给出可执行的手动出口"

    # 已经在熔的进程遇到坏文件：**保持熔断**，不许被清零
    good = tmp_path / "ok.json"
    armed = zq.CooldownManager(good)
    armed.enter("ZCode 风控熔断（30min，全局）")
    good.write_text(json.dumps({"until_ms": "坏值", "reason": "覆盖", "last_call_ms": 0}),
                    encoding="utf-8")
    assert armed.active() is True, "文件坏了就把熔断清了 = fail open"
    assert "风控熔断" in armed.reason()


def test_absurd_until_ms_is_not_shown_as_an_eternal_breaker(tmp_path, caplog):
    """🔴 天文数字的 `until_ms` 不得摆上界面，也不得借此清掉熔断（第八轮 E-4 + 第九轮 N-2）。

    照单全收时用户会看到「剩余几千万年」，除了把整块面板当不可信没有别的选择；
    而"归 0"这一版修法方向也错 —— 时钟回拨 >24h 时那等于把真熔断静默清零。
    """
    import logging

    p = tmp_path / "c.json"
    far = _frozen_ms(2026, 9, 28, 12, 0) + 30 * 86_400_000 * 1000     # 30 天后
    p.write_text(json.dumps({"until_ms": far, "reason": "X", "last_call_ms": 0}),
                 encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="model_gateway.zcode"):
        cm = zq.CooldownManager(p)
        assert "不合理" in "\n".join(r.getMessage() for r in caplog.records)
    assert cm.active() is True, "读不动 = 未知，未知按熔断拒跑（第十一轮 BLK-2 的方向）"
    assert "至 " not in cm.reason(), "荒谬时间戳仍被渲染成钟点 = 界面出现「剩余几千万年」"

    # 反向：已在熔的进程读到荒谬值 = 文件不可信，熔断必须还在
    armed = zq.CooldownManager(p)
    armed.enter("ZCode 风控熔断（30min，全局）")
    p.write_text(json.dumps({"until_ms": far, "reason": "覆盖", "last_call_ms": 0}),
                 encoding="utf-8")
    assert armed.active() is True, "坏文件把熔断抹掉了 = 双领窗口"


def __init__(self, resources: dict[str, str]):
        from model_gateway.config.schemas import AppConfig
        from model_gateway.core.resources import ResourceManager

        self.config = AppConfig.model_validate({
            "resources": [{"id": rid, "name": rid, "account": acct,
                           "access_mode": "api",
                           "base_url": "http://127.0.0.1:9/v1", "api_key": "sk"}
                          for rid, acct in resources.items()],
            # 注册表按 (资源, 供应商模型名) 建索引 —— 没有模型映射就没有 ResourceState，
            # bench 也就无从落点（这是 `apply_to_resource` 的遍历口径，不是笔误）
            "models": [{"name": "m", "endpoint": "chat", "resources": [
                {"resource": rid, "model": f"vm-{rid}"} for rid in resources]}]})
        self.resources = ResourceManager()
        self.resources.rebuild(self.config)


def test_sync_circuit_benches_resources_after_restart(accounts_root):
    """🔴 熔断**落盘**、资源态**在内存**：只重启一次，资源就恢复 active = §17 的出口空白。

    复现验收 IX-2 的实测场景：`circuit.json` 还剩 19 分钟，网关重启后
    总览「最近错误」列却是空的、模型转发照旧打向被风控的账号。
    """
    rt = _RealMgrRuntime({"res-a": "acct-a", "res-b": "acct-b"})
    zq.get_circuit().enter("ZCode 风控熔断（30min，全局）")

    benched, skipped = zq.sync_circuit_to_runtime(rt)

    assert (benched, skipped) == (2, 0), "两个账号对应的资源都要被 bench"
    for st in rt.resources.registry.values():
        assert st.status == "cooldown", st.status      # `bench()` 的落库状态名
        assert "风控熔断" in (st.last_error or "")
        # 🔴 内部存的是**裸原因**（验收 S-23）：时刻烘进 `last_error` 就是
        #    "午夜后仍在说一个过去的钟点"，渲染发生在快照里
        assert "至 " not in (st.last_error or ""), st.last_error
    rows = rt.resources.snapshot_by_resource(rt.config)
    assert len(rows) == 2
    for row in rows:
        assert re.search(r"，至 (?:明日 )?\d{2}:\d{2}$", row["last_error"]), row["last_error"]
        assert row["cooldown_remaining_ms"] > 0
        assert st.available() is False, "仍在风控观察期的资源不得进生效集"


def test_sync_circuit_cooldown_matches_remaining_time(accounts_root):
    """对齐时长必须 = **熔断剩余**，不是固定 30 分钟：否则资源先解冻、熔断还在。"""
    rt = _RealMgrRuntime({"res-a": "acct-a"})
    circuit = zq.get_circuit()
    circuit.enter("ZCode 风控熔断（30min，全局）")
    # 把时钟往前推 25 分钟 = "只剩 5 分钟"。
    # 🔴 不能再直接改 `circuit._cd.until_ms` 然后 `_save()`：`_save()` 现在按
    #    "盘上更长者胜"合并（第十一轮 BLK-2 —— 几毫秒前另一个进程刚建立的 30 分钟
    #    不许被本次节流写抹掉），直改内存会被盘上那份顶回来。
    base = circuit._now()
    circuit._now = lambda: base + 25 * 60 * 1000

    assert zq.sync_circuit_to_runtime(rt) == (1, 0)
    st = next(iter(rt.resources.registry.values()))
    remaining = st.cooldown_until - rt.resources.clock()
    assert 4 * 60 < remaining <= 5 * 60 + 1, f"资源冷却 {remaining/60:.1f} 分钟 ≠ 熔断剩余 5 分钟"


def test_sync_circuit_is_noop_when_breaker_expired(accounts_root):
    """未熔断/已到期 → 一个资源都不许 bench（否则把正常账号永久关进冷却）。"""
    rt = _RealMgrRuntime({"res-a": "acct-a"})
    assert zq.sync_circuit_to_runtime(rt) == (0, 0)
    assert [st.status for st in rt.resources.registry.values()] == ["active"]


# ---------- 6) S1：删除状态文件 = 熔断已解除（跨进程一致，且不得静默清态）----------

def test_deleting_the_circuit_file_releases_the_running_process(tmp_path: Path):
    """🔴 常驻进程必须看见"文件被删"。

    面板实测（PM + ix 各自复现）：`enter()` → `unlink()` → 老实现 `active()` 仍 True、
    `left_minutes()` 仍 30，而**新**进程读同一路径却是 False ——
    CLI 那句「或删除该文件以提前解除」既解不了当下，又抹掉了跨进程凭据
    （下一次重启在风控观察期内恢复领取）。
    """
    p = tmp_path / "circuit.json"
    cm = zq.CooldownManager(p)
    cm.enter("ZCode 风控熔断（30min，全局）")
    assert cm.active() is True

    p.unlink()
    assert cm.active() is False, "删文件后仍熔断 = CLI 的解除出口是假的"
    assert cm.left_minutes() == 0
    assert cm.reason() == ""
    # 解除后必须能再次进入（不是"一次性状态"）
    cm.enter("ZCode 风控熔断（30min，全局）")
    assert cm.active() is True and p.exists()


def test_cross_process_delete_is_visible_without_restart(tmp_path: Path):
    """另一个进程（CLI）删文件，网关进程下一次判定就要看到 —— 无需重启。"""
    p = tmp_path / "circuit.json"
    gw_side = zq.CooldownManager(p)
    gw_side.enter("ZCode 风控熔断（30min，全局）")

    p.unlink()                                     # 模拟 CLI 进程执行删除

    assert gw_side.active() is False, "跨进程删除不生效 = 出口只对写它的那个进程有用"


def test_corrupt_circuit_file_does_not_silently_clear(tmp_path: Path):
    """🔴 反向判据：**损坏 ≠ 解除**。文件在但读不出对象时保持内存态继续熔断，
    否则一次半写就把风控保护抹掉（与上面"文件不存在=解除"是两条不同路径）。"""
    p = tmp_path / "circuit.json"
    cm = zq.CooldownManager(p)
    cm.enter("ZCode 风控熔断（30min，全局）")
    p.write_text('{"until_ms": ', encoding="utf-8")          # 截断的 JSON
    assert cm.active() is True, "损坏文件被当成不存在 = 静默解除风控保护"

    p.write_text(json.dumps(["不是对象"]), encoding="utf-8")
    assert cm.active() is True, "结构不符被当成解除"


# ---------- 7) S-1：冷却只延长不缩短（一次额度 tick 剪不断 30 分钟熔断）----------

def test_bench_never_shortens_an_existing_cooldown():
    """`bench()` 的不变量：调用方语义是"至少冷却这么久"，没有任何一处需要把冷却改短。"""
    from model_gateway.core.resources import ResourceManager, ResourceState

    t = [1000.0]
    mgr = ResourceManager(clock=lambda: t[0])
    st = ResourceState("res-a", "vm-a", label="A", vendor="V", account="",
                       access_mode="api", enabled=True)
    mgr.registry[st.resource_id] = st

    mgr.bench(st, 1800.0)                       # 30 分钟（熔断）
    t[0] += 1.0
    mgr.bench(st, 60.0)                         # 60 秒（额度耗尽 tick）
    assert st.cooldown_until == 2800.0, "短冷却覆盖了长冷却 = 提前放行"
    assert mgr.bench(st, 3600.0) is True, "更长冷却必须仍被接受并回报所有权"
    assert st.cooldown_until == 4601.0


def test_quota_exhaustion_tick_does_not_shorten_the_breaker_bench(accounts_root):
    """🔴 面板实测的原始穿透路径：熔断 bench 30min → 一次额度 tick → 冷却变 60s。"""
    rt = _RealMgrRuntime({"res-a": "acct-a"})
    zq.get_circuit().enter("ZCode 风控熔断（30min，全局）")
    assert zq.sync_circuit_to_runtime(rt) == (1, 0)
    st = next(iter(rt.resources.registry.values()))
    assert (st.cooldown_until - rt.resources.clock()) > 29 * 60

    snap = zq.QuotaSnapshot(account="acct-a", buckets=[
        zq.Bucket(show_name="通用", period="5h", total=100, used=100, available=0)])
    zq.apply_snapshot_to_runtime(rt, "acct-a", snap)

    left = st.cooldown_until - rt.resources.clock()
    assert left > 29 * 60, f"额度 tick 把熔断冷却剪成 {left/60:.1f} 分钟，熔断仍剩 {zq.get_circuit().left_minutes()} 分钟"
    assert "风控熔断" in st.last_error, f"挡路原因被后到的短原因改写：{st.last_error}"


def test_exhaustion_reason_still_lands_when_no_longer_cooldown_is_held(accounts_root):
    """🔴 正向对照：**没有**更长冷却时，额度耗尽必须照写 `ZCode 额度耗尽`
    （否则上一条用例的"跳过"会变成吞掉所有回写的万能挡箭牌）。"""
    rt = _RealMgrRuntime({"res-a": "acct-a"})
    snap = zq.QuotaSnapshot(account="acct-a", buckets=[
        zq.Bucket(show_name="通用", period="5h", total=100, used=100, available=0)])
    zq.apply_snapshot_to_runtime(rt, "acct-a", snap)

    st = next(iter(rt.resources.registry.values()))
    assert st.status == "cooldown" and st.last_error == "ZCode 额度耗尽"
    assert 0 < st.cooldown_until - rt.resources.clock() <= 61


# ---------- 8) S-11：回写作用域必须认 `product`，不匹配要**可见**（eng-M-4 / ix-M-6）----------

def _cfg_two_products(account: str = "acct-a"):
    """两条资源同备注：一条声明 zcode、一条声明别的产品（+ 一条未声明，走旧行为）。"""
    from model_gateway.config.schemas import AppConfig
    from model_gateway.core.resources import ResourceManager

    cfg = AppConfig.model_validate({
        "resources": [
            {"id": "res-z", "name": "Z号", "account": account, "product": "zcode",
             "account_ref": account,
             "access_mode": "api", "base_url": "http://127.0.0.1:9/v1", "api_key": "sk"},
            {"id": "res-other", "name": "别的产品", "account": account, "product": "qoder",
             "account_ref": account,
             "access_mode": "api", "base_url": "http://127.0.0.1:9/v1", "api_key": "sk"},
            {"id": "res-legacy", "name": "未声明产品", "account": account,
             "access_mode": "api", "base_url": "http://127.0.0.1:9/v1", "api_key": "sk"},
        ],
        "models": [{"name": "m", "endpoint": "chat", "resources": [
            {"resource": rid, "model": "vm"} for rid in ("res-z", "res-other", "res-legacy")]}]})
    mgr = ResourceManager()
    mgr.rebuild(cfg)
    return cfg, mgr


def test_product_scoping_keeps_other_products_out_of_the_bench(accounts_root):
    """🔴 备注字符串恰好相同的**别的产品**资源不得被 ZCode 风控 bench。"""
    import types

    cfg, mgr = _cfg_two_products()
    rt = types.SimpleNamespace(config=cfg, resources=mgr, clock=mgr.clock)
    assert zq.resource_ids_of_account("acct-a", cfg) == ["res-z", "res-legacy"], \
        "product=qoder 的资源被纳入了 ZCode 熔断作用域"
    assert zq.sync_circuit_to_runtime(rt) == (0, 0), "未开熔断时不得 bench 任何东西"
    assert [x.status for x in mgr.registry.values()] == ["active"] * 3

    zq.get_circuit().enter("ZCode 风控熔断（30min，全局）")
    benched, skipped = zq.sync_circuit_to_runtime(rt)
    assert benched == 2 and skipped == 0, (benched, skipped)
    assert mgr.registry[("res-other", "vm")].status == "active", "别的产品被误 bench"
    assert mgr.registry[("res-z", "vm")].status == "cooldown"
    assert mgr.registry[("res-legacy", "vm")].status == "cooldown"   # 未声明 = 旧行为兼容


def test_only_mismatching_resources_reports_skipped(accounts_root):
    """🔴 唯一可见出口静默空转时必须报数（否则用户以为"熔断没生效"）。"""
    import types

    from model_gateway.config.schemas import AppConfig
    from model_gateway.core.resources import ResourceManager

    cfg = AppConfig.model_validate({
        "resources": [{"id": "res-x", "name": "产品不符", "account": "acct-a",
                       "product": "qoder", "account_ref": "acct-a", "access_mode": "api",
                       "base_url": "http://127.0.0.1:9/v1", "api_key": "sk"}],
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": "res-x", "model": "vm"}]}]})
    mgr = ResourceManager()
    mgr.rebuild(cfg)
    rt = types.SimpleNamespace(config=cfg, resources=mgr, clock=mgr.clock)
    zq.get_circuit().enter("ZCode 风控熔断（30min，全局）")

    assert zq.sync_circuit_to_runtime(rt) == (0, 1), "空转未被报出 → 界面上一片正常"
    assert mgr.registry[("res-x", "vm")].status == "active"


def test_sync_circuit_is_silent_noop_when_breaker_expired(accounts_root):
    """未熔断 → (0, 0)：不得因为"有资源"就 bench 任何东西。"""
    import types

    cfg, mgr = _cfg_two_products()
    rt = types.SimpleNamespace(config=cfg, resources=mgr, clock=mgr.clock)
    assert zq.sync_circuit_to_runtime(rt) == (0, 0)


def test_cosmetic_url_change_does_not_revive_a_dead_credential(accounts_root):
    """🔴 补/删一个尾斜杠不是"换了凭据"（验收 S-14）。

    原判据把 invalid/disabled 的唯一逃逸口做成"连接身份指纹变了"，而指纹用**原串**
    base_url —— 用户在界面上只是把 `.../v1/` 改成 `.../v1`，被 401 判死的资源
    就被放回生效集（真打上游 + 连续失败历史清零）。
    """
    import types

    from model_gateway.config.schemas import AppConfig
    from model_gateway.core.resources import ResourceManager

    cfg = AppConfig.model_validate({
        "resources": [{"id": "res-a", "name": "A", "account": "acct-a", "protocol": "openai",
                       "access_mode": "api", "base_url": "http://127.0.0.1:9/v1",
                       "api_key": "sk"}],
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": "res-a", "model": "vm-a"}]}]})
    mgr = ResourceManager()
    mgr.rebuild(cfg)
    st = mgr.registry[("res-a", "vm-a")]
    mgr.invalidate(st)
    st.C = 4

    cfg.resources[0].base_url = "http://127.0.0.1:9/v1/"      # 只加尾斜杠
    mgr.rebuild(cfg)
    assert st.status == "invalid", " cosmetic 改动复活了判死凭据"
    assert st.C == 4

    cfg.resources[0].protocol = "anthropic"                   # 真换了协议 = 新连接身份
    mgr.rebuild(cfg)
    assert st.status == "active", "协议变更不算新身份（与适配器复用口径不一致）"


def test_credential_change_still_revives_after_a_url_edit(accounts_root):
    """🔴 正向对照：改 Key 必须仍然复位（上面那条不许把逃逸口一并焊死）。"""
    from model_gateway.config.schemas import AppConfig
    from model_gateway.core.resources import ResourceManager

    cfg = AppConfig.model_validate({
        "resources": [{"id": "res-a", "name": "A", "account": "acct-a", "protocol": "openai",
                       "access_mode": "api", "base_url": "http://127.0.0.1:9/v1",
                       "api_key": "sk-old"}],
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": "res-a", "model": "vm-a"}]}]})
    mgr = ResourceManager()
    mgr.rebuild(cfg)
    st = mgr.registry[("res-a", "vm-a")]
    mgr.invalidate(st)
    cfg.resources[0].api_key = "sk-new"
    mgr.rebuild(cfg)
    assert st.status == "active"


def test_url_normalization_has_exactly_one_source(accounts_root):
    """🔴 归一化口径只有一份（验收 S-19 收尾）。

    S-14 只把**指纹**改成 `.strip().rstrip("/")`，`main.py` 判适配器复用仍写
    `.rstrip("/")`，适配器构造函数又自己剥一遍 —— 三份"看着一样"的实现。
    粘贴来带空格的 URL 时：运行态认为没变，复用判定认为变了（每次热重载重建连接）。
    现在三处都走 `normalize_base_url`，本用例钉的是"适配器存的已经是归一化后的值"
    （`main.py` 的 `old.base_url == normalize_base_url(...)` 只有在这个前提下才稳）。
    """
    import asyncio

    from model_gateway.adapters import build_adapter
    from model_gateway.core.resources import normalize_base_url

    raw = "  http://127.0.0.1:9/v1/  "
    for protocol in ("openai", "anthropic"):
        ad = build_adapter(protocol, normalize_base_url(raw))
        try:
            assert ad.base_url == "http://127.0.0.1:9/v1", protocol
            # 幂等：主循环把 `old.base_url` 再喂回判定，不幂等就会每轮热重载都重建客户端
            assert normalize_base_url(ad.base_url) == ad.base_url, protocol
        finally:
            asyncio.run(ad.aclose())

    # 直接构造（绕过 factory）也必须同一口径，否则新增适配器又会漂回 rstrip
    from model_gateway.adapters.anthropic_out import AnthropicOutAdapter
    from model_gateway.adapters.openai_out import OpenAIOutAdapter

    for cls in (OpenAIOutAdapter, AnthropicOutAdapter):
        ad = cls(raw)
        try:
            assert ad.base_url == normalize_base_url(raw), cls.__name__
        finally:
            asyncio.run(ad.aclose())



def test_base_url_normalization_has_no_second_implementation():
    """🔴 判"同一条连接"的归一化**只许有一份实现**（验收 S-26②）。

    S-14 修过一次分叉，S-19e 收了适配器与热重载两处，第七轮面板又找出
    `cli_probe.py`（带空格的 URL：网关能跑、probe 报 UnsupportedProtocol）与
    `upstream/zcode/claim.py` 两处各自 `rstrip("/")`。这类缺陷的形态是
    "每一处看着都对，两处的答案不一样" —— 所以判据不是测某处的行为，而是
    **全包扫一遍不许出现第二份写法**（新增一处即判红，逼作者共用 `normalize_base_url`）。
    """
    from pathlib import Path as _P

    pkg = _P(__file__).resolve().parents[2] / "model_gateway"
    offenders = []
    for path in sorted(pkg.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "base_url" in line and '.rstrip("/")' in line:
                offenders.append(f"{path.relative_to(pkg).as_posix()}:{n}")
    assert not offenders, f"出现了第二份 base_url 归一化实现：{offenders}"

    # 行为面：真用它归一化的两个客户端确实吃掉首尾空白
    from model_gateway.core.resources import normalize_base_url
    from model_gateway.upstream.zcode.claim import ZCodeClaimClient

    raw = "  https://zcode.example.com/api/  "
    client = ZCodeClaimClient(raw, token="t")
    assert client.base_url == normalize_base_url(raw), client.base_url

def test_whitespace_url_edit_does_not_revive_a_dead_credential(accounts_root):
    """🔴 与 S-14 同族的另一半：只是多了首尾空格，同样不算"换了凭据"。

    指纹用归一化值，`ResourceState.src_fp` 记下的也是归一化后的摘要 —— 一旦哪一处
    改回原串比较，用户在界面里重粘一次带空格的 URL 就会清掉连续失败历史并放回生效集。
    """
    from model_gateway.config.schemas import AppConfig
    from model_gateway.core.resources import ResourceManager

    cfg = AppConfig.model_validate({
        "resources": [{"id": "res-a", "name": "A", "account": "acct-a", "protocol": "openai",
                       "access_mode": "api", "base_url": "http://127.0.0.1:9/v1",
                       "api_key": "sk"}],
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": "res-a", "model": "vm-a"}]}]})
    mgr = ResourceManager()
    mgr.rebuild(cfg)
    st = mgr.registry[("res-a", "vm-a")]
    mgr.invalidate(st)
    st.C = 4

    cfg.resources[0].base_url = "  http://127.0.0.1:9/v1  "     # 只多了首尾空格
    mgr.rebuild(cfg)
    assert st.status == "invalid", "空白差异复活了判死凭据（口径又分叉了）"
    assert st.C == 4


def test_expired_breaker_reason_carries_no_past_clock(tmp_path):
    """🔴 已过点的熔断不得再说一个过去的钟点（第八轮 eng-8a 的 L-1）。

    快照侧在 S-23 就按"冷却中才配钟点"做了，而 `circuit.reason()` 原先无此约束：
    文件还在、但已过期时，CLI 会打「…，至 00:20」而界面只给裸原因 —— 两出口又打架。
    """
    base = _frozen_ms(2026, 9, 28, 12, 0)
    cm = zq.CooldownManager(tmp_path / "c.json", now=lambda: base)
    cm.enter("ZCode 风控熔断（30min，全局）")
    assert "至 " in cm.reason()
    cm._now = lambda: base + zq.COOLDOWN_MS + 1000          # 过点之后
    assert cm.active() is False
    assert "至 " not in cm.reason(), cm.reason()
    assert cm.reason() == "ZCode 风控熔断（30min，全局）"


def test_recovery_clock_renderer_has_no_injectable_wall_clock():
    """🔴 渲染入口不许留"只为测试存在"的时钟参数（第九轮 eng N-1）。

    S-23 一度给 `_rendered_last_error` 加了 `wall_now` 形参好让测试冻钟 ——
    但生产调用点只要有人把它传成 manager 自己的钟（`time.monotonic`），
    S-28 那个假钟点就原地复活，而且**所有判据仍然全绿**。
    没有护栏的测试入口 = 待爆的缺陷；冻钟改在测试侧 patch `time.time`。
    """
    import inspect

    from model_gateway.core.resources import _rendered_last_error

    params = inspect.signature(_rendered_last_error).parameters
    assert "wall_now" not in params, f"测试专用时钟参数被加回来了：{list(params)}"
    assert set(params) == {"entries", "status", "remaining_ms"}, list(params)


def test_missing_or_null_until_ms_keeps_the_running_breaker(tmp_path, caplog):
    """🔴 状态文件"读不动"的**每一种**形态都不得抹掉正在生效的熔断，且必须留痕。

    起因是 `float(raw or 0)` 把"没写这个字段"读成"值是 0"，于是常驻进程内存里熔着的熔断
    被一次坏写清零 —— 而这份文件唯一的用途就是让另一个进程也看得见风控。
    形态集按四轮面板的实测补齐（第十轮：缺键/`null`/`NaN`/字符串；第十一轮：布尔/非对象/
    非 JSON），处理口径统一为"文件读不动"：**保持内存态 + 记一条日志 + 拒绝整盘覆盖**。
    """
    import logging

    p = tmp_path / "circuit.json"
    armed = zq.CooldownManager(p)
    armed.enter("ZCode 风控熔断（30min，全局）")
    assert armed.active() is True

    bad_forms = ("{}", '{"reason": "覆盖"}', '{"until_ms": null, "reason": "覆盖"}',
                 '{"until_ms": NaN, "reason": "覆盖"}', '{"until_ms": "abc", "reason": "覆盖"}',
                 # 第十一轮 BLK-3：`float(True)==1.0` 是合法数值，布尔必须挡在判数之前
                 '{"until_ms": true, "reason": "覆盖"}', '{"until_ms": false, "reason": "覆盖"}',
                 # 第十二轮 PM B-12-1 / eng-A BLK-A：`float("1770…")` 同样合法 ——
                 # 带引号的时间戳（手改 / 别的序列化器 / 半写入残留）必须按读不动处理
                 '{"until_ms": "1770000000000", "reason": "覆盖"}',
                 '{"until_ms": "1", "reason": "覆盖"}',
                 # 重复键：`json.loads` 默认让后写的静默顶掉先写的，也要判坏
                 '{"until_ms": 1, "until_ms": 1790595896455.39}',
                 # 整份文件不是对象 / 根本不是 JSON：同样按"读不动"，不许当"没有熔断"
                 "[]", '"just-a-string"', "not json at all")
    for bad in bad_forms:
        p.write_text(bad, encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="model_gateway.zcode"):
            caplog.clear()
            assert armed.active() is True, f"坏文件把熔断抹掉了：{bad}"
            assert "风控熔断" in armed.reason(), bad
            # 形态不同 → 归因不同（盘上键集/类型名都在文案里），所以"变化时记一条"
            # 的去重不会把不同形态并成一条；PM 第十一轮批的正是"坏值路径零痕迹"
            assert any("读不动" in r.getMessage() for r in caplog.records), \
                f"坏文件却零日志：{bad}"

    # 手动出口不回退：删除文件仍然立刻放开（PRD Q28-⑥ 对用户承诺的那一条）
    p.unlink()
    assert armed.active() is False


def test_unreadable_breaker_file_blocks_instead_of_releasing(tmp_path):
    """🔴 第十一轮 eng-A BLK-2：新进程遇到读不动的文件 = **未知**，未知按熔断拒跑。

    原口径是"无内存态 → 按无熔断起"，那是 fail-open：文件还在、风控可能还在，
    而 CLI 会打「全部正常，无需处理」并以 rc=0 退出。方向按用户裁决 S-22
    （宁可拒跑也不冒险）翻正，并保证**给出可执行的手动出口**。
    """
    p = tmp_path / "circuit.json"
    p.write_text('{"until_ms": true, "reason": "ZCode 风控熔断（30min，全局）"}',
                 encoding="utf-8")     # 最常见的误改：数字被换成布尔
    fresh = zq.CooldownManager(p)
    assert fresh.active() is True, "读不动 = 未知，未知不得按『没有熔断』放行"
    assert fresh.untrusted, "未知必须可分辨（CLI/运营门要据此归因，不能说成『全部正常』）"
    why = fresh.reason()
    assert "至 " not in why, "时长未知时不得编钟点（界面会出现假恢复时刻）"
    assert "删除" in why and str(p) in why, f"必须给出手动出口：{why}"


def test_mark_called_never_destroys_a_breaker_it_cannot_read(tmp_path):
    """🔴 BLK-2 的第二半：`mark_called()` 只是记节流，**不许**因此把熔断凭据整盘抹掉。

    原实现 `_load()` 读不动 → 内存空态 → `mark_called()` → `_save()` 无条件覆盖，
    于是别的进程留下的 30 分钟熔断在一次节流写入后消失（且下一次判定也跟着清零）。
    """
    p = tmp_path / "circuit.json"
    keeper = zq.CooldownManager(p)
    keeper.enter("ZCode 风控熔断（30min，全局）")
    disk_before = p.read_text(encoding="utf-8")

    # 另一个进程（空内存态）碰上读不动的文件：它自己按熔断拒跑，也不得覆写盘上状态
    p.write_text("not json at all", encoding="utf-8")
    interloper = zq.CooldownManager(p)
    assert interloper.active() is True
    interloper.mark_called()
    assert p.read_text(encoding="utf-8") == "not json at all", "拒写没生效：盘上被覆盖了"

    # 熔着的进程自己仍然可以续写（它内存里有凭据，写的是"不缩短"的那份）
    p.write_text(disk_before, encoding="utf-8")
    keeper.mark_called()
    again = json.loads(p.read_text(encoding="utf-8"))
    assert again["until_ms"] == json.loads(disk_before)["until_ms"], "熔断时长被节流写改动了"
    assert again["last_call_ms"] > 0


def test_save_merges_the_longer_breaker_from_disk(tmp_path):
    """🔴 落盘按"盘上更长者胜"合并：本次写入不得缩短另一个进程刚建立的熔断。

    真实形态（与 `bench()` 的"只延长不缩短"同一族，只是这发生在**跨进程**）：
    B 进程先起（盘上还没有熔断），A 进程命中 3012 落了 30 分钟，B 随后只是记一次节流
    —— 不合并就会把 B 内存里那份"没有熔断"写回盘上，A 的凭据凭空消失。
    """
    p = tmp_path / "circuit.json"
    b = zq.CooldownManager(p)                      # B：空内存态
    a = zq.CooldownManager(p)
    a.enter("ZCode 风控熔断（30min，全局）")        # A：命中风控并落盘
    long_until = json.loads(p.read_text(encoding="utf-8"))["until_ms"]

    b.mark_called()                                # B：只想记节流
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["until_ms"] == long_until, "更长的熔断被后到的空状态剪掉了"
    assert "风控熔断" in saved["reason"], "原因串一起被抹掉 = 界面上查不到任何痕迹"
    assert saved["last_call_ms"] > 0, "本次节流没记上"


def test_untrusted_state_is_visible_on_the_ui_not_only_in_logs(tmp_path, accounts_root):
    """🔴 「文件读不动」必须有**界面出口**（第十轮 PM N-1 + 第十一轮 eng-A 同批）。

    项目自己写明"只写日志 = 用户看不见"（`main.py` 的 config_warnings 注释、
    `dashboard.js` 的告警横幅），所以这条新口径不能只落在日志里：
    §17 的回写要把这一档推到资源行的「最近错误」上，且时长未知时按整档熔断挡
    （bench 0 秒 = 什么都不做 = 文件里熔着、界面上毫无痕迹，正是 S-11 的静默空转）。
    """
    p = tmp_path / "circuit.json"
    rt = _RealMgrRuntime({"res-a": "acct-a"})
    zq._reset_circuit_for_tests(p)
    try:
        p.write_text('{"until_ms": true, "reason": "ZCode 风控熔断（30min，全局）"}',
                     encoding="utf-8")
        benched, skipped = zq.sync_circuit_to_runtime(rt)
        assert (benched, skipped) == (1, 0), "读不动时回写静默空转 = 界面上查不到任何痕迹"
        st = next(iter(rt.resources.registry.values()))
        assert st.status == "cooldown", st.status
        assert "读不动" in (st.last_error or ""), st.last_error
        left = st.cooldown_until - rt.resources.clock()
        # 未知档：**短周期挡住 + 每轮重挡**，不给人一个编造的 30 分钟恢复时刻
        assert 30 < left <= zq.UNKNOWN_STATE_BLOCK_S + 1, f"未知档挡住 {left:.0f}s"
    finally:
        zq._reset_circuit_for_tests()


def test_numeric_string_timestamp_cannot_shorten_or_wipe_the_breaker(tmp_path):
    """🔴 带引号的时间戳不许"能转成数就当它是数"（第十二轮 PM B-12-1 / eng-A BLK-A）。

    面板实测的完整坏链：A 正熔着 30 分钟 → B 读到 `until_ms` 是字符串 →
    `float("1770000000000")` 完全合法且落在过去 → B 判"没有熔断"（`untrusted` 是 None）
    → 于是"未知不许写盘"那层护栏根本不触发 → `mark_called()` 整盘覆盖，A 的凭据消失，
    全程零 WARNING。字符串形态与第十一轮的布尔形态是同一个根因的另一半。
    """
    p = tmp_path / "circuit.json"
    keeper = zq.CooldownManager(p)
    keeper.enter("ZCode 风控熔断（30min，全局）")
    long_until = json.loads(p.read_text(encoding="utf-8"))["until_ms"]

    bad = '{"until_ms": "1770000000000", "reason": "覆盖", "last_call_ms": 0}'
    p.write_text(bad, encoding="utf-8")
    reader = zq.CooldownManager(p)
    assert reader.untrusted, "数字串被判可信 = coerce 型 fail-open 仍在"
    assert reader.active() is True
    reader.mark_called()
    assert p.read_text(encoding="utf-8") == bad, "拒写没生效：A 的凭据被字符串状态顶掉了"
    # 熔着的那个进程不受影响（内存态在，且归因说的是字符串类型而不是"半写入"）
    assert keeper.active() is True
    assert "类型不对" in (keeper.untrusted or "") or "类型不对" in keeper.reason()


def test_duplicate_keys_are_not_silently_the_last_value(tmp_path):
    """🔴 JSON 重复键必须按"读不动"处理（第十二轮 eng-A BLK-A 的第二形态）。

    `json.loads` 默认让后写的键静默顶掉先写的：手改过一次、或半写入留下两份 `until_ms` 时，
    盘上"看起来是合法 JSON"却已经不是任何一次写入的意图 —— 这种文件不能当熔断凭据。
    """
    p = tmp_path / "circuit.json"
    keeper = zq.CooldownManager(p)
    keeper.enter("ZCode 风控熔断（30min，全局）")
    until = json.loads(p.read_text(encoding="utf-8"))["until_ms"]
    p.write_text('{"until_ms": 1, "until_ms": %r, "reason": "ZCode 风控熔断（30min，全局）"}'
                 % until, encoding="utf-8")
    fresh = zq.CooldownManager(p)
    assert fresh.untrusted and "重复键" in fresh.untrusted, fresh.untrusted
    assert fresh.active() is True


def test_save_failure_is_never_claimed_as_persisted(tmp_path, caplog):
    """🔴 落盘失败必须**可分辨**（第十二轮 eng-A BLK-B：这一档过去完全静默）。

    面板实测（目录 0555）：`enter()` 无异常、**零日志**、文件不存在 → 下一次判定读成
    "没有熔断" → 运营闸门开、下一轮继续打风控中的账号，而 CLI 还在打印
    「已建立全局熔断：」+ 空原因。现在：`_save()` 返回真假、失败记 WARNING，
    `unpersisted` 给出口一个可分辨的口径。
    """
    import logging
    import os

    state = tmp_path / "st"
    state.mkdir()
    p = state / "circuit.json"
    cm = zq.CooldownManager(p)
    os.chmod(state, 0o555)
    try:
        with caplog.at_level(logging.WARNING, logger="model_gateway.zcode"):
            caplog.clear()
            assert cm._save() is False, "目录不可写时 `_save()` 仍报告成功"
            cm.enter("ZCode 风控熔断（30min，全局）")
            assert cm.active() is True, "落盘失败不该影响本进程的内存态熔断"
            assert cm.unpersisted, "没落盘这件事必须可分辨（CLI 不能空口说\"已建立\"）"
            why = cm.reason()
            assert "未能写入状态文件" in why and "仅当前进程内存生效" in why, why
            assert str(p) in why, "要指到具体路径，用户才知道去修哪里的权限"
            assert any("落盘失败" in r.getMessage() for r in caplog.records), \
                "落盘失败零日志 = 静默 fail-open"
    finally:
        os.chmod(state, 0o755)


def test_concurrent_saves_never_expose_a_half_written_file(tmp_path):
    """🔴 第十一轮 eng-A BLK-1：固定名临时文件让并发落盘互相截断（实测 12 秒读到坏 JSON 20 万次）。

    面板的复现不需要人手改文件：cron 与 CLI 各领不同账号、同时命中 3012 即可。
    现在临时名由 `mkstemp` 给（`O_EXCL` 唯一）+ `fsync` + `os.replace` 原子改名，
    读者只能看到"旧的完整文件"或"新的完整文件"。
    """
    import threading

    p = tmp_path / "circuit.json"
    managers = [zq.CooldownManager(p) for _ in range(6)]
    bad: list[str] = []
    stop = threading.Event()

    def writer(m: zq.CooldownManager) -> None:
        while not stop.is_set():
            m._save()
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                bad.append(f"{type(exc).__name__}: {exc}")
                return

    threads = [threading.Thread(target=writer, args=(m,)) for m in managers]
    for t in threads:
        t.start()
    threading.Event().wait(1.5)
    stop.set()
    for t in threads:
        t.join(timeout=10)
    assert not bad, f"读到过半写/被截断的状态：{bad[:3]}"
    leftovers = [f.name for f in p.parent.iterdir()
                 if f.name.startswith(f".{p.name}.") or f.name == f"{p.name}.tmp"
                 or f.name == p.with_suffix(".tmp").name]
    assert not leftovers, f"临时文件残留：{leftovers}"


def test_breaker_fields_that_are_only_throttle_stay_benign(tmp_path):
    """🔴 反向对照：`last_call_ms` 坏掉**不该**把整份状态拒掉（否则 `reason` 一起丢）。

    节流字段最坏的后果只是"多打一次上游"，而拒绝整份状态会让界面显示"没有熔断"——
    那是更坏的降级方向。
    """
    p = tmp_path / "circuit.json"
    zq.CooldownManager(p).enter("ZCode 风控熔断（30min，全局）")
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["last_call_ms"] = "坏值"
    p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    cm = zq.CooldownManager(p)
    assert cm.active() is True
    assert "风控熔断" in cm.reason(), cm.reason()     # 原因仍然显示，没被整份拒收
    assert cm.throttle_wait_ms() == 0                  # 按"没有最近调用"处理
