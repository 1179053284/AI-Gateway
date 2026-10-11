"""v2.0 §16 运营批量执行器单元测试（tech-design §19 M5-1）。

判据（§19 M5-1）：
- 假上游注入 1003/1005/网络错 → **四类结果分类正确**
- **并发触发断言只领一次**（双层互斥生效）
- **空跑两情形**：有账号全无需动作 → `success`；**`N=0` → `inactive`**（不得报 success）
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path

import pytest

from model_gateway.ops.base import OpReport, OpResult
import model_gateway.ops.runner as runner_mod
from model_gateway.ops.runner import (
    AccountLocks,
    PlanLock,
    Scheduler,
    ack_reports,
    cron_matches,
    run_once,
    unread_failures,
    write_report,
)
from model_gateway.ops.builtin import zcode_claim


# ---------- 四类结果分类（§16.2 / §16.3 教训 2）----------

# ⚠️ 业务码判定**只有一份实现**（`zcode_claim.classify`）——
#    原 `runner.classify_http_error` / `is_retryable` 与它重复，已按"不过度设计"删除（验收修正）。


@pytest.mark.parametrize("code,expected", [
    (0, "success"),
    (1003, "already_done"),      # 已领取过 → **不是失败**
    (1005, "inactive"),          # 今日名额用完
    (1002, "inactive"),          # 活动结束
    (1001, "inactive"),          # 套餐不存在
    (3007, "failed"),            # 验证码失败
])
def test_business_code_classification(code, expected):
    """🔴 幂等**看响应体 code，不看 HTTP 状态**（§16.3 教训 2）。

    实测重复领取返回 `HTTP 400 + code 1003` —— 属 `already_done`，**不是失败**。
    若按 HTTP 400 判失败 → 重试 → 触发频控。
    """
    from model_gateway.upstream.zcode.claim import ClaimOutcome
    assert zcode_claim.classify(ClaimOutcome(code=code))[0] == expected


def test_business_failure_does_not_retry():
    """仅网络类退避重试；**业务失败不重试**（§16.4）—— 见 `_run_one` 的 `_looks_retryable`。"""
    from model_gateway.ops.runner import _looks_retryable

    assert _looks_retryable("network: ConnectError") is True
    assert _looks_retryable("timeout: read") is True
    assert _looks_retryable("upstream HTTP 503") is True
    assert _looks_retryable("业务码 3007") is False
    assert _looks_retryable("该套餐已领取过") is False


# ---------- 批量执行：四类结果 ----------

async def _fake_sleep(_s: float) -> None:
    return None


async def test_run_once_classifies_all_four_categories():
    """🔴 假上游注入 → 四类结果各自归位。"""
    async def claim(account: str, *, manual: bool = False, runtime=None) -> OpResult:
        return {
            "a": OpResult("a", "success"),
            "b": OpResult("b", "already_done", "已领取过"),
            "c": OpResult("c", "inactive", "无资格"),
            "d": OpResult("d", "failed", "验证码超时"),
        }[account]

    report = await run_once(accounts=["a", "b", "c", "d"], claim=claim, sleep=_fake_sleep)

    assert report.success == ["a"]
    assert report.already_done == ["b"]
    assert report.inactive == ["c"]
    assert report.failed == [("d", "验证码超时")]
    assert report.all_normal is False          # 有 failed → 需关注


async def test_already_done_is_not_a_failure():
    """`already_done` / `inactive` 是**正常业务状态**，不进 failed。"""
    async def claim(account: str, *, manual: bool = False, runtime=None) -> OpResult:
        return OpResult(account, "already_done", "已领取过")

    report = await run_once(accounts=["a", "b"], claim=claim, sleep=_fake_sleep)
    assert report.failed == []
    assert report.all_normal is True


# ---------- 空跑两情形（§16.4）----------

async def test_empty_accounts_reports_inactive_not_success():
    """🔴 **`N=0` → `inactive` + `no_participants` 标记**（**不得报 `success`**）。

    验收发现：原实现 `N=0` 直接返回空 report，CLI 打印「全部正常，无需处理」
    —— 与 §16.4「N=0 不得报 success」**直接相反**。现修正为显式标记。
    """
    report = await run_once(accounts=[], claim=None, sleep=_fake_sleep)

    assert report.no_participants is True
    assert report.success == []                    # ← 关键：不是 success
    assert report.inactive == ["（无账号参与）"]     # ← 明确说明，而非静默
    assert report.all_normal is True               # 但也不算失败（无失败项）


async def test_all_accounts_no_action_still_success_when_they_ran():
    """情形 ①：有账号参与但全部无需动作 → 仍记 `success`（避免 N/N 误报 failed）。"""
    async def claim(account: str, *, manual: bool = False, runtime=None) -> OpResult:
        return OpResult(account, "success")

    report = await run_once(accounts=["a"], claim=claim, sleep=_fake_sleep)
    assert report.success == ["a"]


async def test_disabled_accounts_are_skipped():
    """参与范围：运营类**跳过 `enabled=false`**（§16.4）。"""
    async def claim(account: str, *, manual: bool = False, runtime=None) -> OpResult:
        return OpResult(account, "success")

    report = await run_once(accounts=["a", "b"], enabled_of=lambda a: a == "a",
                            claim=claim, sleep=_fake_sleep)

    assert report.success == ["a"]
    assert report.skipped == ["b"]


# ---------- 失败隔离 ----------

async def test_single_account_failure_does_not_break_the_rest():
    """**逐账号失败隔离**：单账号失败不中断其余（§16.4）。"""
    seen: list[str] = []

    async def claim(account: str, *, manual: bool = False, runtime=None) -> OpResult:
        seen.append(account)
        if account == "b":
            return OpResult("b", "failed", "boom")
        return OpResult(account, "success")

    report = await run_once(accounts=["a", "b", "c"], claim=claim, sleep=_fake_sleep)

    assert seen == ["a", "b", "c"]           # 后续账号仍被执行
    assert report.success == ["a", "c"]
    assert report.failed == [("b", "boom")]


async def test_exception_in_claim_is_isolated():
    """claim 抛异常也被隔离（不炸整批）。"""
    async def claim(account: str, *, manual: bool = False, runtime=None) -> OpResult:
        if account == "a":
            raise RuntimeError("kaboom")
        return OpResult(account, "success")

    report = await run_once(accounts=["a", "b"], claim=claim, sleep=_fake_sleep)
    assert report.success == ["b"]
    assert len(report.failed) == 1 and "kaboom" in report.failed[0][1]


async def test_network_failure_retries_but_business_failure_does_not():
    """仅网络类退避重试；业务失败**不重试**（§16.4）。"""
    calls: list[str] = []

    async def claim(account: str, *, manual: bool = False, runtime=None) -> OpResult:
        calls.append(account)
        if account == "net":
            return OpResult("net", "failed", "network: ConnectError: refused")
        return OpResult(account, "failed", "业务码 3007")

    await run_once(accounts=["net", "biz"], claim=claim, sleep=_fake_sleep)

    assert calls.count("net") > 1            # 网络类重试
    assert calls.count("biz") == 1           # 业务失败不重试


# ---------- §22.6 R1-F2：真实产品钩子的网络类/5xx 失败必须被退避重试 ----------
#
# 上面两条用的是**注入的假 claim**；下面三条走**真实产品钩子**（buddy，经
# `product_claim.claim` 全通路）—— 折叠点有没有把 `ClaimOutcome.retryable` 置位，
# 只有真钩子能证明（R1-F2 的病根正是"钩子折叠成中文文案 → 旧判据对不上 → 从不重试"）。


def _install_fake_net(monkeypatch, handler) -> None:
    """把 `accounts/net.py::make_client` 换成 MockTransport 客户端（**无网络**）。

    与 `tests/accounts/test_buddy.py::_install_http` 同形：钩子只经这一工厂取客户端
    （§22.8-1，产品层的唯一客户端构造点），替换它即可整体注入假上游。
    """
    import httpx

    from model_gateway.accounts import net

    def factory(**kwargs):
        kwargs.pop("follow_redirects", None)     # MockTransport 不吃这个显式参数
        kwargs["timeout"] = httpx.Timeout(5.0)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(net, "make_client", factory)


def _seed_product_account(product: str, name: str) -> None:
    """落一个真账号（`meta.json` 是"算不算账号"的判据；数据目录由 conftest 隔离到 tmp）。"""
    from model_gateway.accounts import store as accounts_store

    accounts_store.commit_login(product, name, {"access_token": "t0ken"}, {})


async def test_real_product_hook_network_failure_is_retried_by_the_batch_runner(monkeypatch):
    """🔴 红证靶点（R1-F2）：真实产品钩子折叠的网络类失败 → 结构化 `retryable` → 退避重试。

    原实现：buddy 钩子把网络失败折叠成中文文案，旧判据 `_looks_retryable` 对它返回
    False → 产品通路的网络类失败**从不退避重试**（重试计数=1）。三段判据（缺一不可）：

    ① 用例前提：这条文案在旧判据下确实为 False（证明起作用的不是文案猜谜）；
    ② 折叠点已置位：`product_claim.claim` 返回 `retryable is True`；
    ③ 批量执行器因此重试到 `MAX_ATTEMPTS_PER_ACCOUNT` 次（退避真的发生）。
    """
    import httpx

    from model_gateway.ops import runner as runner_mod
    from model_gateway.ops.builtin import product_claim

    _seed_product_account("buddy", "buddy-net")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url.path))
        raise httpx.ConnectError("connection refused", request=request)

    _install_fake_net(monkeypatch, handler)
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    res = await runner_mod._run_one("buddy-net", lambda a: product_claim.claim(a),
                                    sleep=fake_sleep)

    assert res.category == "failed" and res.retryable is True, res.detail
    assert runner_mod._looks_retryable(res.detail) is False, (
        f"用例前提不成立：旧判据对这条文案已为 True（detail={res.detail!r}）")
    assert len(calls) == runner_mod.MAX_ATTEMPTS_PER_ACCOUNT, (
        f"网络类失败没有被退避重试（只发起 {len(calls)} 次）")
    assert slept, "一次退避都没睡"


async def test_real_product_hook_business_code_is_not_retried(monkeypatch):
    """对照（§16.4）：同一真实通路里的**业务码**失败不重试（判据看码，不看文案）。"""
    import httpx

    from model_gateway.ops import runner as runner_mod
    from model_gateway.ops.builtin import product_claim

    _seed_product_account("buddy", "buddy-biz")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url.path))
        return httpx.Response(400, json={"code": 40001, "msg": "业务拒绝"}, request=request)

    _install_fake_net(monkeypatch, handler)

    async def must_not_sleep(s: float) -> None:
        raise AssertionError("业务码失败不该退避")

    res = await runner_mod._run_one("buddy-biz", lambda a: product_claim.claim(a),
                                    sleep=must_not_sleep)
    assert res.category == "failed" and res.retryable is False and "40001" in res.detail
    assert len(calls) == 1, f"业务码失败被重试了（发起 {len(calls)} 次）"


async def test_real_product_hook_5xx_page_is_retried_but_a_4xx_page_is_not(monkeypatch):
    """5xx 折叠点（§22.6「退避仅网络/5xx」）：非 JSON 网关错误页按 HTTP 状态**结构化分档**。

    HTTP 5xx（服务端瞬时）→ 可重试；HTTP 4xx（凭据失效的 HTML 页）→ 不重试。
    实现是一条 `retryable=(status >= 500)`，判定与响应文案无关。
    """
    import httpx

    from model_gateway.ops import runner as runner_mod
    from model_gateway.ops.builtin import product_claim

    _seed_product_account("buddy", "buddy-503")
    calls_503: list[int] = []

    def handler_503(request: httpx.Request) -> httpx.Response:
        calls_503.append(1)
        return httpx.Response(503, text="<html>bad gateway</html>", request=request)

    _install_fake_net(monkeypatch, handler_503)

    async def fake_sleep(_s: float) -> None:
        return None

    res = await runner_mod._run_one("buddy-503", lambda a: product_claim.claim(a),
                                    sleep=fake_sleep)
    assert res.retryable is True and len(calls_503) == runner_mod.MAX_ATTEMPTS_PER_ACCOUNT

    _seed_product_account("buddy", "buddy-403")
    calls_403: list[int] = []

    def handler_403(request: httpx.Request) -> httpx.Response:
        calls_403.append(1)
        return httpx.Response(403, text="<html>forbidden</html>", request=request)

    _install_fake_net(monkeypatch, handler_403)

    async def must_not_sleep(s: float) -> None:
        raise AssertionError("4xx 错误页不该退避")

    res = await runner_mod._run_one("buddy-403", lambda a: product_claim.claim(a),
                                    sleep=must_not_sleep)
    assert res.retryable is False and len(calls_403) == 1


# ---------- 双层互斥（§16.4）----------

async def test_account_lock_prevents_double_claim():
    """🔴 **账号级互斥在生产路径生效**：并发触发时同一账号**只领一次**。

    ⚠️ 本用例**不传 `locks=`** —— 验收发现原实现在 `run_once` 内每次新建 `AccountLocks()`，
    导致 cron 与 CLI 各持一把锁、**互斥实际失效**。现改用**模块级共享锁**，
    本用例正是守这条：**不传锁也应互斥**。
    """
    entered = 0
    gate = asyncio.Event()

    async def claim(account: str, *, manual: bool = False, runtime=None) -> OpResult:
        nonlocal entered
        entered += 1
        await gate.wait()
        return OpResult(account, "success")

    async def one() -> OpReport:
        return await run_once(accounts=["lock-probe"], claim=claim, sleep=_fake_sleep)

    t1 = asyncio.create_task(one())
    await asyncio.sleep(0.01)          # 让 t1 先拿到锁
    t2 = asyncio.create_task(one())
    await asyncio.sleep(0.01)
    gate.set()
    r1, r2 = await asyncio.gather(t1, t2)

    assert entered == 1, "并发下同一账号被领取了多次（生产路径的账号级互斥失效）"
    assert (r1.success == ["lock-probe"]) != (r2.success == ["lock-probe"])
    assert len(r1.skipped) + len(r2.skipped) == 1


def test_account_locks_basic_semantics():
    locks = AccountLocks()
    assert locks.try_acquire("a") is True
    assert locks.try_acquire("a") is False    # 已持有 → 拿不到
    assert locks.try_acquire("b") is True     # 不同账号互不影响
    locks.release("a")
    assert locks.try_acquire("a") is True


def test_plan_lock_skips_when_held():
    """**plan 级互斥**：拿不到直接跳过本 tick（不排队）。"""
    lock = PlanLock()
    assert lock.try_acquire() is True
    assert lock.try_acquire() is False
    lock.release()
    assert lock.try_acquire() is True
    lock.release()          # 同进程持有集合是**进程级**的，测试必须自己收尾


# ---------- 结果出口（§16.6 / §21）----------

def test_write_report_appends_jsonl(tmp_path: Path):
    r = OpReport(success=["a"], already_done=["b"], inactive=["c"], failed=[("d", "err")])
    path = write_report(r, tmp_path)

    assert path is not None and path.name.startswith("ops-results-")
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1
    assert lines[0]["success"] == ["a"]
    assert lines[0]["failed"] == [{"account": "d", "reason": "err"}]


def test_unread_count_comes_from_the_jsonl_not_memory(tmp_path: Path):
    """🔴 红点的数以**落盘文件**为准（验收 S-5：内存计数器看不见另一个进程的写入）。

    判据形状 = 两条写入路径各写一轮：cron 腿（带 runtime）与 CLI 腿（不带 runtime）。
    只要两者都往同一个 jsonl 追加，未读数就必须一致 —— 这一条同时在挡
    "只给 cron 落盘"与"给内存计数器加分支"两种回退。
    """
    usage = tmp_path / "usage"
    write_report(OpReport(failed=[("a", "x"), ("b", "y")]), usage)
    assert unread_failures(usage) == 2

    write_report(OpReport(failed=[("c", "z")]), usage)       # 另一个进程写（CLI 腿）
    assert unread_failures(usage) == 3, "后写的失败没被算进未读"

    write_report(OpReport(success=["d"]), usage)             # 全正常的一轮不加数
    assert unread_failures(usage) == 3


def test_unread_survives_process_restart(tmp_path: Path):
    """未读失败是**事实**，不随网关进程存活与否消失（内存计数器重启即清零）。"""
    usage = tmp_path / "usage"
    write_report(OpReport(failed=[("a", "x")]), usage)

    assert unread_failures(usage) == 1
    assert unread_failures(usage) == 1        # 相当于"新进程重新读一次"


def test_write_report_failure_is_swallowed(tmp_path: Path):
    """落盘失败不抛（不因写日志失败而中断运营）。"""
    blocked = tmp_path / "f"
    blocked.write_text("x", encoding="utf-8")       # 用文件占住目录名
    assert write_report(OpReport(), blocked) is None


# ---------- 5 段 cron ----------

def test_cron_matches_basic():
    import datetime as dt
    t = dt.datetime(2026, 9, 26, 10, 30)     # 周六
    assert cron_matches("* * * * *", t) is True
    assert cron_matches("30 10 * * *", t) is True
    assert cron_matches("0 10 * * *", t) is False
    assert cron_matches("*/15 * * * *", t) is True
    assert cron_matches("0,30 10 * * *", t) is True


def test_cron_rejects_malformed():
    import datetime as dt
    t = dt.datetime(2026, 9, 26, 10, 30)
    assert cron_matches("", t) is False
    assert cron_matches("* * *", t) is False


# ---------- zcode_claim 业务码分类（薄适配器）----------

@pytest.mark.parametrize("code,expected", [
    (0, "success"),
    (1003, "already_done"),
    (1005, "inactive"),
    (1002, "inactive"),
    (3007, "failed"),
])
def test_zcode_claim_classify(code, expected):
    from model_gateway.upstream.zcode.claim import ClaimOutcome
    assert zcode_claim.classify(ClaimOutcome(code=code))[0] == expected


def test_zcode_claim_supported_products_declared():
    """能力必须 **per-operation 声明**（§16.4）。"""
    assert zcode_claim.SUPPORTED_PRODUCTS == ("zcode",)


# ---------- 失败计数清零出口（§21 / M-IX-2）----------

def test_ack_is_the_clear_exit_and_only_eats_acked_rows(tmp_path: Path):
    """🔴 清零出口 = 写"已确认水位"（原实现只增不减 → 红点永久常亮）。

    水位之后的新失败必须**重新计入**：否则"确认过一次"会变成永久消音器。
    """
    usage = tmp_path / "usage"
    write_report(OpReport(failed=[("a", "x"), ("b", "y")]), usage)
    assert ack_reports(usage) == 2
    assert unread_failures(usage) == 0
    assert ack_reports(usage) == 0                 # 幂等（没有新的未读）

    write_report(OpReport(failed=[("c", "z")]), usage)
    assert unread_failures(usage) == 1, "确认后新写入的失败被水位一起吃掉了"


def test_ack_is_empty_dir_safe(tmp_path: Path):
    """一次运营都没跑过时，确认动作返回 0 且不抛（红点本来就该是 0）。"""
    assert unread_failures(tmp_path / "never-written") == 0
    assert ack_reports(tmp_path / "never-written") == 0


def test_unread_ignores_yesterdays_file(tmp_path: Path):
    """未读只算**当日**文件（跨天后旧失败不得继续点亮红点，也不需要谁去清）。"""
    import datetime as dt

    usage = tmp_path / "usage"
    yesterday = (dt.datetime.now() - dt.timedelta(days=1)).strftime("%Y%m%d")
    usage.mkdir(parents=True, exist_ok=True)
    stale = usage / f"ops-results-{yesterday}.jsonl"
    stale.write_text(json.dumps({"failed": [{"account": "a", "reason": "旧"}]}) + "\n",
                     encoding="utf-8")

    assert unread_failures(usage) == 0


def test_report_dict_marks_no_participants():
    """`no_participants` 必须进落盘/返回体（供 CLI 与界面判断）。"""
    r = OpReport(no_participants=True, inactive=["（无账号参与）"])
    assert r.to_dict()["no_participants"] is True


# ---------- 共享锁是模块级单例（防"每次新建锁"回归）----------

def test_shared_locks_is_module_level_singleton():
    """🔴 回归护栏：锁必须是**模块级单例**，否则 cron 与 CLI 各持一把锁 → 互斥失效。"""
    from model_gateway.ops import runner as r1
    from model_gateway.ops import runner as r2
    assert r1._SHARED_LOCKS is r2._SHARED_LOCKS

    # 默认路径确实用到它：先占住，再跑 run_once 应被跳过
    assert r1._SHARED_LOCKS.try_acquire("shared-probe") is True
    try:
        rep = asyncio.run(run_once(accounts=["shared-probe"],
                                   claim=lambda a, **k: _ok(a), sleep=_fake_sleep))
        assert rep.skipped == ["shared-probe"]
    finally:
        r1._SHARED_LOCKS.release("shared-probe")


async def _ok(account: str) -> OpResult:
    return OpResult(account, "success")


# ---------- 🔴 跨进程互斥（§16.4 第二层，本轮修正 R4）----------
#
# 上一轮把锁改成"模块级单例"只解决了**进程内**：cron 在网关进程、`mgw zcode claim`
# 在 CLI 进程，两个进程各有一份内存 set → 同一账号仍可被双领。
# 这里的用例用**真实子进程**验证锁确实落到文件、且第二个进程拿不到。

import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

_LOCK_CHILD = """
import sys, time
sys.path.insert(0, {repo!r})
from model_gateway.ops.runner import AccountLocks
locks = AccountLocks({dir!r})
print("ACQUIRED" if locks.try_acquire({account!r}) else "DENIED", flush=True)
time.sleep(1.5)                      #  held 期间让父进程去抢
locks.release({account!r})
print("RELEASED", flush=True)
"""


def _spawn_holder(lock_dir: Path, account: str) -> subprocess.Popen:
    """起一个**独立进程**去持锁（模拟 cron 持锁、CLI 来抢）。"""
    code = _LOCK_CHILD.format(repo=str(Path(__file__).resolve().parents[2]),
                              dir=str(lock_dir), account=account)
    return subprocess.Popen([sys.executable, "-c", code],
                            stdout=subprocess.PIPE, text=True, bufsize=1)


def test_lock_file_is_written_and_removed(tmp_path: Path):
    """持锁期间锁文件存在且写着自己的 pid；释放后删除（幂等）。"""
    d = tmp_path / "locks"
    locks = AccountLocks(d)
    assert locks.try_acquire("acct-x") is True
    f = d / "acct-x.lock"
    assert f.exists()
    pid, token, _age = AccountLocks(d)._read_lock(f)
    assert pid == os.getpid(), "锁文件必须写 pid（跨进程判活依据）"
    assert len(token) >= 8, "必须写本进程令牌：pid 会被内核复用，只靠 pid 会误删他人锁（M-2 ⑤）"
    locks.release("acct-x")
    assert not f.exists()


def test_second_process_cannot_acquire_while_held(tmp_path: Path):
    """🔴 判据本体：另一个进程持锁时，本进程 `try_acquire` 必须 False（不排队、直接跳过）。"""
    d = tmp_path / "locks"
    child = _spawn_holder(d, "acct-shared")
    try:
        assert child.stdout.readline().strip() == "ACQUIRED"
        assert AccountLocks(d).try_acquire("acct-shared") is False, "跨进程互斥未生效"
    finally:
        child.wait(timeout=15)
    assert "RELEASED" in child.stdout.read()


def test_second_process_succeeds_after_holder_exits(tmp_path: Path):
    """持锁进程退出后（pid 已死）→ 陈旧锁回收，后来者可拿（不会永久卡死运营）。"""
    d = tmp_path / "locks"
    child = _spawn_holder(d, "acct-next")
    child.stdout.readline()
    child.wait(timeout=15)           # 子进程自己 release 了
    holder_only = d / "acct-next.lock"
    holder_only.write_text("999999", encoding="utf-8")   # 伪造一个**已死** pid
    assert AccountLocks(d).try_acquire("acct-next") is True


def test_fresh_unreadable_lock_is_not_stolen(tmp_path: Path):
    """🔴 TOCTOU（M-2 ②）：刚 `O_CREAT` 完、pid 还没写进去 → **不得**被第二个进程抢走。

    上一版把"空/损坏"一律当陈旧回收，等于在创建与写入之间留了一个可被抢的窗口。
    """
    d = tmp_path / "locks"
    d.mkdir(parents=True)
    (d / "acct-bad.lock").write_text("", encoding="utf-8")      # 正在被写
    assert AccountLocks(d).try_acquire("acct-bad") is False


def test_stale_corrupt_lock_is_reclaimed(tmp_path: Path):
    """损坏且**已过写宽限期**的锁 → 回收，不因此永久阻断运营。"""
    import time as _t

    d = tmp_path / "locks"
    d.mkdir(parents=True)
    f = d / "acct-bad.lock"
    f.write_text("not-a-pid", encoding="utf-8")
    old = _t.time() - (runner_mod.LOCK_WRITE_GRACE_S + 1)
    os.utime(f, (old, old))                                     # 伪造为陈旧
    assert AccountLocks(d).try_acquire("acct-bad") is True


def test_over_aged_lock_is_reclaimed_despite_live_pid(tmp_path: Path):
    """🔴 pid 复用兜底（M-2 ④）：持有者超 `LOCK_MAX_AGE_S` → 视为陈旧。

    只按"pid 是否存活"判定的话，一个死进程留下的锁一旦被内核把号复用到
    别的进程上，就会被**永久**误判为"别人在持有"，运营从此不再跑。
    """
    import time as _t

    d = tmp_path / "locks"
    d.mkdir(parents=True)
    f = d / "acct-old.lock"
    f.write_text(f"{os.getpid() + 1000} deadbeef", encoding="utf-8")
    old = _t.time() - (runner_mod.LOCK_MAX_AGE_S + 5)
    os.utime(f, (old, old))
    assert AccountLocks(d).try_acquire("acct-old") is True


def test_account_lock_name_is_path_safe(tmp_path: Path):
    """账号名来自磁盘目录，仍要过清洗：不得用 `../` 越出锁目录写文件。"""
    d = tmp_path / "locks"
    locks = AccountLocks(d)
    assert locks.try_acquire("../../escape") is True
    assert list(d.glob("*.lock")), "锁文件必须落在锁目录内"
    assert not (tmp_path / "escape.lock").exists()


def test_plan_lock_is_cross_process_too(tmp_path: Path):
    """plan 级同样落盘：CLI 与 cron 不会同时开跑一整轮批量。"""
    d = tmp_path / "locks"
    plan = PlanLock(d)
    assert plan.try_acquire() is True
    other_entry = AccountLocks(d)
    assert other_entry.try_acquire("__plan__") is False   # 别的入口拿不到
    plan.release()
    assert other_entry.try_acquire("__plan__") is True
    other_entry.release("__plan__")   # 同进程持有集是进程级的，测试必须收尾


def test_run_once_skips_account_held_by_another_process(tmp_path: Path, monkeypatch):
    """🔴 端到端一层：`run_once` 走的默认锁必须是**跨进程**那把。"""
    monkeypatch.setenv("MGW_OPS_LOCK_DIR", str(tmp_path / "locks"))
    child = _spawn_holder(tmp_path / "locks", "acct-batch")
    try:
        assert child.stdout.readline().strip() == "ACQUIRED"

        async def _never(account, **kw):        # 真被调用的话就会返回 success
            raise AssertionError("被其他进程占用的账号不得执行运营动作")

        rep = asyncio.run(run_once(accounts=["acct-batch"], claim=_never))
        assert rep.skipped == ["acct-batch"]
        assert rep.success == []
    finally:
        child.wait(timeout=15)


# ---------- 运营调度器触发时机（§16.4；本轮补：此前该类**零测试**）----------

def test_scheduler_waits_one_period_before_first_tick():
    """🔴 启动不得立刻跑第一轮：原来 `loop()` 先 tick 后 sleep
    → **每次重启网关都立即发起一次真实领取**（用户没要求，且会在重启风暴里连打上游）。"""
    async def main():
        calls: list[int] = []

        async def run():
            calls.append(1)

        sched = Scheduler(interval_s=0.2)
        sched.start(run)
        try:
            await asyncio.sleep(0.06)
            assert calls == [], "第一个周期未到就开了跑（启动即领取）"
            await asyncio.sleep(0.25)
            assert len(calls) >= 1, "等待一个周期后应至少跑一轮"
        finally:
            await sched.stop()

    asyncio.run(main())


def test_plan_lock_busy_skips_tick_and_does_not_queue():
    """plan 级 TryLock：拿不到就**跳过本 tick**（排队会把一轮轮堆积成连环领取）。"""
    async def main():
        lock = PlanLock()
        calls: list[int] = []

        async def run():
            calls.append(1)

        sched = Scheduler(plan_lock=lock)
        assert lock.try_acquire() is True
        await sched._tick(run)
        assert calls == []                     # 被别人持有 → 直接跳过

        lock.release()
        await sched._tick(run)
        assert calls == [1]                    # 空出来就正常跑
        assert lock.try_acquire() is True      # tick 结束后锁必须已释放
        lock.release()

    asyncio.run(main())


def test_cron_mode_uses_minute_granularity_not_interval():
    """cron 模式：轮询粒度固定 60s（同一分钟不得重复触发），不随 `interval_s` 变密。"""
    async def main():
        hits: list[int] = []

        async def run():
            hits.append(1)

        sched = Scheduler(cron="30 10 * * *")
        assert sched._should_fire(dt.datetime(2026, 9, 27, 10, 30)) is True
        assert sched._should_fire(dt.datetime(2026, 9, 27, 10, 31)) is False

        # 给了 interval_s=0.01 也**不生效**：cron 模式按分钟轮询，
        # 且当前时刻不匹配 cron → 一轮都不会跑
        sched2 = Scheduler(interval_s=0.01, cron="0 0 1 1 0")
        sched2.start(run)
        try:
            await asyncio.sleep(0.06)
        finally:
            await sched2.stop()
        assert hits == []
    asyncio.run(main())


# ---------- §16.4 能力声明：supported_products 必须是**真判据**（本轮 G4）----------

def _op(products, op_id="x_op"):
    from model_gateway.ops.base import AccountOperation

    async def _run(account, **kw):
        return OpResult(account, "success")

    return AccountOperation(id=op_id, title="测试动作",
                            supported_products=tuple(products), run=_run)


async def test_operation_filters_out_unsupported_products():
    """产品不在动作声明内 → **跳过并说明原因**，不得"顺手也跑一下"（§16.4）。"""
    calls = []

    async def claim(account, **kw):
        calls.append(account)
        return OpResult(account, "success")

    op = _op(["zcode"])
    report = await run_once(operation=op, claim=claim, accounts=["z1", "t1"],
                            product_of=lambda a: "zcode" if a == "z1" else "trae",
                            sleep=_fake_sleep)
    assert calls == ["z1"]
    assert report.success == ["z1"]
    assert len(report.skipped) == 1 and "trae" in report.skipped[0]
    assert "zcode" in report.skipped[0]          # 原因要说得清（谁不支持、支持什么）


async def test_all_accounts_filtered_out_counts_as_no_participants():
    """全被产品过滤掉 = **无人参与**（§16.4 不得报 success）——
    空跑判据必须排在过滤**之后**，否则用户会看到"全部正常，无需处理"。"""
    async def claim(account, **kw):     # 真被调用就该失败
        raise AssertionError("无人参与时不应执行任何动作")

    report = await run_once(operation=_op(["qoder"]), claim=claim, accounts=["t1"],
                            product_of=lambda a: "trae", sleep=_fake_sleep)
    assert report.no_participants is True
    assert report.success == []


async def test_operation_provides_the_default_claim_fn(tmp_path, monkeypatch):
    """生产入口只传 `operation=`：动作的 `run` 必须被自动接上（否则 CLI/cron 跑空）。

    §22.6 收敛后的接线条**逐段钉死**（不只看"注册表里有个函数"）：

    ① 别名条目 `zcode_claim.run` = 多产品 `claim` 的**同一执行体**（注册表接线）；
    ② zcode 账号在该执行体里走**直连分支** `zcode_claim.claim`（生产领取实现，
       `--manual` / `runtime` 契约挂在那里）——「等价」靠这条与 test_ops_claim_multi
       的同对象断言共同成立；
    ③ 账号目录隔离到 tmp 且**不预置凭据** → 走的是生产实现，结论应是
       "明确 failed + 指路"，而不是静默空报告。
    """
    from model_gateway.ops import builtin as ops_builtin
    from model_gateway.ops.builtin import product_claim
    from model_gateway.upstream.zcode import store as zstore

    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(tmp_path / "accounts"))
    op = ops_builtin.OPERATIONS["zcode_claim"]
    assert op.run is product_claim.claim, "注册表没指向多产品 claim 执行体（§22.6 别名接线）"
    assert product_claim._CLAIM_DIRECT["zcode"] is zcode_claim.claim, (
        "zcode 直连分支没指向生产领取实现（manual/runtime 契约会断）")

    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"name": "acct-a", "device_mid": "mid-a"}), encoding="utf-8")
    assert zstore.import_account(str(seed)).ok

    report = await run_once(operation=op, accounts=["acct-a"], sleep=_fake_sleep)
    assert report.failed and report.failed[0][0] == "acct-a"
    assert "mgw zcode" in report.failed[0][1]


def test_registry_declares_products_it_can_act_on():
    """注册表自检（§22.6 口径）：动作必须声明非空产品集，且**只声明在册产品**。

    产品全集 = `accounts/registry.py::PRODUCT_IDS`（在册 11 实例，Q44 起）。原判据写死
    `{zcode}` —— 随多产品收敛过期后，它会把合法的跨产品声明（如 claim 的 7 家）
    误判成"系统里不存在的产品"（判据对象错了，不是实现错了）。
    """
    from model_gateway.accounts import registry as account_registry
    from model_gateway.ops.builtin import OPERATIONS

    ACCOUNT_PRODUCTS = set(account_registry.PRODUCT_IDS)   # 系统里真实存在的产品集

    assert OPERATIONS, "运营动作注册表为空"
    assert "zcode" in ACCOUNT_PRODUCTS, "判据本身要有效：在册产品全集不得为空/失真"
    for op in OPERATIONS.values():
        assert op.supported_products, f"{op.id} 未声明支持产品（§16.4）"
        assert set(op.supported_products) <= ACCOUNT_PRODUCTS, (
            f"{op.id} 声明了系统里不存在的产品：{op.supported_products}")
        assert op.id and op.title and callable(op.run)


def test_product_of_account_maps_known_accounts(tmp_path, monkeypatch):
    """账号 → 产品 的映射来自各产品自己的账号目录（Q27-⑤：初期各产品独立）。"""
    from model_gateway.upstream.zcode import store as zstore
    from model_gateway.ops.runner import product_of_account

    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(tmp_path / "accounts"))
    assert product_of_account("nope") == ""            # 认不出 → 空串（由执行器显式跳过）
    p = tmp_path / "seed.json"
    p.write_text(json.dumps({"name": "acct-a", "device_mid": "mid-a"}), encoding="utf-8")
    assert zstore.import_account(str(p)).ok
    assert product_of_account("acct-a") == zstore.PRODUCT == "zcode"


def test_has_account_does_not_escape_root(tmp_path, monkeypatch):
    """账号名来自外部，判存在性时不得被 `../` 越出账号根。"""
    from model_gateway.upstream.zcode import store as zstore

    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(tmp_path / "accounts"))
    (tmp_path / "elsewhere" / "meta.json").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "elsewhere" / "meta.json").write_text("{}", encoding="utf-8")
    assert zstore.has_account("../elsewhere") is False


# ---------- 注册表：§22.6 收敛后的三个条目（多产品 claim + query_balance + zcode 别名）----------

def test_registry_has_the_22_6_operations_and_the_alias():
    """🔴 §22.6 收敛结论（supersede 原 §16.6「首批 2 个」）：注册表恰为三条，
    且 `zcode_claim` **是别名不是第二实现** —— `run` 与多产品 `claim` 同一函数对象、
    声明收窄到 zcode（id / 标题 / `mgw zcode claim` 退出码契约逐字不变，Q28-⑧）。
    """
    from model_gateway.ops import builtin as ops_builtin
    from model_gateway.ops.builtin import product_claim

    assert set(ops_builtin.OPERATIONS) == {"claim", "query_balance", "zcode_claim"}
    claim_op = ops_builtin.OPERATIONS["claim"]
    alias = ops_builtin.OPERATIONS["zcode_claim"]
    assert alias.run is claim_op.run is product_claim.claim, (
        "别名没有指向多产品 claim 的同一执行体（§22.6 等价性断）")
    assert alias.supported_products == ("zcode",)
    assert claim_op.supported_products == product_claim.SUPPORTED_PRODUCTS
    assert alias.supported_products != claim_op.supported_products, (
        "别名必须靠声明收窄（它是「多产品 claim 收窄到 zcode」，不是独立动作）")


def test_precheck_table_is_the_single_registry_source():
    """🔴 `precheck` per-product 声明**唯一表** = `accounts/registry.py::PRE_CHECK_PRODUCTS`。

    收敛前 ops 侧与管理端各持一份字面量（靠测试钉"两份相等"，改一漏一即分叉）；
    现两处都是对**同一对象**的引用。任一处再长出第二份副本/分叉值，本用例的
    身份断言（`is`）即红 —— 这比"两份 == 相等"强：它钉的是"只有一份"。
    """
    from model_gateway.accounts import registry as account_registry
    from model_gateway.api import admin_accounts
    from model_gateway.ops.builtin import product_claim

    table = account_registry.PRE_CHECK_PRODUCTS
    assert product_claim._PRECHECK is table, "ops 侧不是对唯一表的引用（出现第二份副本）"
    assert admin_accounts._PRECHECK is table, "管理端不是对唯一表的引用（出现第二份副本）"
    assert table.get("trae") is True, "trae 必须预检（幂等只能靠 status 端点判，`20 §3.1`）"
    assert set(table) <= set(account_registry.PRODUCT_IDS), "预检声明必须全是在册产品"


def _balance_root(tmp_path, monkeypatch, *, log_line: str | None):
    from model_gateway.upstream.zcode import store as zstore
    from model_gateway.upstream.zcode.dataroot import v2_dir_of

    root = tmp_path / "accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"name": "acct-a", "device_mid": "mid-a"}), encoding="utf-8")
    assert zstore.import_account(str(seed)).ok
    if log_line is not None:
        d = v2_dir_of(root, "acct-a") / "logs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "2026-09-27.log").write_text(log_line + "\n", encoding="utf-8")
    return root


async def test_query_balance_success_writes_quota_pool(tmp_path, monkeypatch):
    """取回带数值的快照 → `success`，且**同一个实现**把余量写进额度池（§17① 与 §19 M5-3）。

    🔴 2026-10-02 迁移（方案 §8.1-8 列明的"必然变红并给处置"三条之一）：
    旧实现是"ops 腿读账号目录里的客户端日志"，本轮改成 ops 腿只调产品 `quota` 钩子
    （联网腿），日志面降级为离线聚合 —— 所以旧夹具那行日志**不再是执行路径的一部分**，
    detail 文案也随 `items` 结构化改造换形（`"余 4"`/`"96/100"` 两个子串都是旧形状）。
    保留的判据内核**没变**：**数值真的进共享池**（这是当初为它保留私有通道的唯一理由）。
    """
    from model_gateway.ops.builtin import query_balance as qb
    from model_gateway.accounts.types import QuotaSnapshot
    from model_gateway.config.schemas import AppConfig
    from model_gateway.core.resources import ResourceManager

    _balance_root(tmp_path, monkeypatch, log_line=None)

    async def _hook(cred, meta):
        return QuotaSnapshot(state="available", source="zcode-billing",
                             detail="plan=Start Plan；可用余量 4（token 量纲）",
                             plan="Start Plan", remaining=4,
                             items=({"name": "通用", "unit": "token", "remaining": 4,
                                     "total": 100, "used": 96, "active": True,
                                     "expires_at": ""},))
    monkeypatch.setattr(qb.product_hooks, "hook_of", lambda product, kind: _hook)

    # 走真实 rebuild()：它才负责把 ResourceState.quota 接到按 rid 共享的池上
    mgr = ResourceManager()
    cfg = AppConfig.model_validate({
        "resources": [{"id": "res-z", "name": "Z", "account": "acct-a",
                       "base_url": "http://127.0.0.1:9/v1", "api_key": "sk"}],
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": "res-z", "model": "vm-a"}]}]})
    mgr.rebuild(cfg)
    st = mgr.registry[("res-z", "vm-a")]

    class _RT:
        resources = mgr
        config = cfg

    # `via="user"`：默认 `quota_net=false` 只挡 cron 腿（用户当场点的按钮必须真刷）
    res = await qb.run_for("zcode", "acct-a", runtime=_RT, via="user")
    assert res.category == "success"
    assert "可用余量 4" in res.detail          # 钩子原话进回执（不再由 ops 层自己拼旧文案）
    assert st.quota.remaining == 4            # 🔴 数值进池：这是私有通道当初存在的唯一理由


async def test_query_balance_without_credentials_is_inactive_not_failed(tmp_path, monkeypatch):
    """🔴 取不到额度 = `inactive`（正常业务态），**不是** `failed`。

    判 `failed` 会让顶栏红点每轮常亮，把真正需要关注的失败稀释掉（§21.3 原则 3）。
    旧用例钉的串是「账号目录不匹配」—— 那是**日志通道**的语义（目录里的日志属于谁），
    联网腿没有"账号目录匹配"这件事（凭据走 `hook_meta` 单一入口），故该串随旧通道退役。
    今天等价的事实是「缺凭据 → 未发起」，档位改钉 `reason=no_credentials`。
    """
    from model_gateway.ops.builtin import query_balance as qb

    _balance_root(tmp_path, monkeypatch, log_line=None)
    res = await qb.run_for("zcode", "acct-a", runtime=None, via="user")
    assert res.category == "inactive"
    assert "未发起" in res.detail             # 说清楚"没查"，而不是含糊的"查不到"


async def test_query_balance_hook_error_is_failed(tmp_path, monkeypatch):
    """执行体真抛（权限/解析/磁盘）→ `failed` 且异常类型进 detail 供排查。

    旧用例 monkeypatch 的是 `read_account_snapshot`（ops 腿今天已不调它）；
    同一判据换个落点继续有效：**钩子抛出的异常必须冒到类别上**，
    不能被"失败面返回快照不冒异常"那条规则顺手吞掉（吞掉 = 红点永不亮）。
    """
    from model_gateway.ops.builtin import query_balance as qb

    _balance_root(tmp_path, monkeypatch, log_line=None)

    async def boom(cred, meta):
        raise OSError("permission denied")

    monkeypatch.setattr(qb.product_hooks, "hook_of", lambda product, kind: boom)
    res = await qb.run_for("zcode", "acct-a", runtime=None, via="user")
    assert res.category == "failed"
    assert "OSError" in res.detail


async def test_query_balance_participates_only_for_its_products():
    """产品过滤对两个动作一视同仁（§16.4 判据是机制不是标签）。

    §22.6 后 `query_balance` 的参与方 = 全部 `balance=True` 产品（**从能力矩阵推导**，
    在册 10 个全 ✓）→ "不参与"的对照必须取**声明之外**的产品（`supports()` 只看声明的
    元组，未登记字符串同样被机制拦下，不改判据强度）。
    """
    from model_gateway.accounts import registry as account_registry
    from model_gateway.ops import builtin as ops_builtin

    op = ops_builtin.OPERATIONS["query_balance"]
    # 参与方声明 = 能力矩阵推导（不是硬编码名单）
    assert set(op.supported_products) == {
        pid for pid in account_registry.PRODUCT_IDS
        if account_registry.PRODUCTS[pid].capabilities.balance}

    # ① 声明内的产品真的参与（spy 被执行，而不是被过滤掉）
    seen: list[str] = []

    async def spy(account, **kw):
        seen.append(account)
        return OpResult(account, "success")

    inside = await run_once(operation=op, claim=spy, accounts=["trae-1"], sleep=_fake_sleep,
                            product_of=lambda a: "trae")
    assert seen == ["trae-1"] and inside.success == ["trae-1"]

    # ② 声明外的产品被**明确跳过并说明原因**；全被滤掉 = 无人参与（不得报 success）
    report = await run_once(operation=op, claim=spy, accounts=["ghost"], sleep=_fake_sleep,
                            product_of=lambda a: "not-registered")
    assert report.no_participants is True and report.skipped
    assert "query_balance" in report.skipped[0] and "not-registered" in report.skipped[0]


async def test_ops_tick_runs_both_registered_operations(tmp_path, monkeypatch):
    """🔴 接线判据：cron 的**一次 tick** 必须把注册表里两个动作都跑掉（§16.6 + §17①）。

    上一轮的教训就是"operation 写好了没人调"——所以这里不看函数存在，
    而是从生产装配入口 `main._maybe_start_ops` 抓到它交给调度器的那个 `run`，真跑一次。
    ⚠️ 动作 id 为多产品正名（M6-6 Fix-η）：cron 的 claim 原先借 `zcode_claim` 别名
    （声明收窄到 zcode，新产品账号在 cron 腿上"注册了但没人跑"）；别名保留给
    `mgw zcode claim` 的 CLI 契约。tick 语义不变（一次跑 claim + query_balance），
    只是 claim 现在按声明覆盖全部 checkin 产品。
    """
    import json as _json

    from model_gateway.config.schemas import AppConfig
    from model_gateway.core.resources import ResourceManager
    from model_gateway.main import _maybe_start_ops
    from model_gateway.ops import runner as runner_mod
    from model_gateway.upstream.zcode import store as zstore

    root = tmp_path / "accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    seed = tmp_path / "seed.json"
    seed.write_text(_json.dumps({"name": "acct-a", "device_mid": "mid-a"}), encoding="utf-8")
    assert zstore.import_account(str(seed)).ok

    ran: list[str] = []

    async def spy_run_once(*, operation=None, **kw):
        ran.append(operation.id if operation is not None else "(none)")
        return OpReport()

    captured: dict = {}

    def spy_start(self, run):
        captured["run"] = run

    monkeypatch.setattr(runner_mod, "run_once", spy_run_once)
    monkeypatch.setattr(runner_mod.Scheduler, "start", spy_start)

    cfg = AppConfig.model_validate({"resources": [], "models": [],
                                    "gateway": {"zcode": {"claim_interval_seconds": 60}}})

    class _RT:
        config = cfg
        usage_dir = tmp_path / "usage"
        resources = ResourceManager()
        ops_failed_unread = 0

    class _App:
        class state:
            runtime = _RT()

    _maybe_start_ops(_App())
    assert "run" in captured, "有账号却没把批量任务交给调度器"
    await captured["run"]()
    assert ran == ["claim", "query_balance"], f"tick 只跑了 {ran}"


# ---------- M-2 ①⑤ / M-9：退路、容错、plan 锁跨进程 ----------

def test_scheduler_survives_tick_exception(tmp_path):
    """🔴 单轮异常不得静默杀死定时器（M-2 ⑤）。

    原实现异常冒出 `loop()` → 任务结束 → **此后再也不跑**，
    而进程活着、界面正常，只有运营静默停摆 —— 最难查的一种故障。
    """
    async def main():
        calls: list[int] = []

        async def run():
            calls.append(len(calls))
            if len(calls) == 1:
                raise OSError("disk full")        # 第一轮炸

        sched = Scheduler(interval_s=0.02)
        sched.start(run)
        try:
            for _ in range(60):                    # 最多等 ~1.2s
                await asyncio.sleep(0.02)
                if len(calls) >= 2:
                    break
        finally:
            await sched.stop()

        assert len(calls) >= 2, f"第一轮异常后定时器就死了：{calls}"
        assert sched.errors >= 1
    asyncio.run(main())


def test_mid_round_write_failure_does_not_strand_the_locks(tmp_path):
    """🔴 跑到一半锁目录失写：释放失败**不得**冒出去，也不得把进程内锁卡死（第七轮 BLK-1）。

    面板实测的形态：跑完第一个账号后 `chmod 0o500` →
    ① `run_once` 抛 `PermissionError`（不返回 report、`ops-results` 一行不写、红点 0）；
    ② 同一个异常穿出 `Scheduler._tick` 的 `finally` 与 `loop()` → **定时器任务当场死亡**；
    ③ `PlanLock.release()` 里 `_files.release()` 先抛 → `_lock.release()` 永不执行，
      本进程的 plan 锁被自己永久占住。
    修好权限后 `usable()` 已经恢复 True，但运营再也不跑 —— 直到重启。
    这正是 S-22 要消灭的"停摆而看起来一切正常"，S-22 只堵住了"开跑前"那一半。
    """
    d = tmp_path / "locks"
    d.mkdir()
    locks = AccountLocks(d)

    # ① 持有之后目录变只读 → 释放**不得**抛（`unlink(missing_ok=True)` 只吞 FileNotFoundError）
    assert locks.try_acquire("acct-mid") is True
    os.chmod(d, 0o500)
    try:
        try:
            locks.release("acct-mid")
        except OSError as e:
            raise AssertionError(f"释放失败把异常顶穿了整轮：{e}") from e
    finally:
        os.chmod(d, 0o700)
    # 内存持有集已放开 → 同一账号可以再次领锁（残留文件由"自己的陈旧锁"回收路径处理）
    assert locks.try_acquire("acct-mid") is True
    locks.release("acct-mid")

    # ② 进程内 plan 锁：文件释放抛错时也必须放开 threading 锁
    plan = PlanLock(d)
    assert plan.try_acquire() is True

    def boom(_self, _account):
        raise OSError("disk went read-only")

    saved, AccountLocks._release_file = AccountLocks._release_file, boom
    try:
        with pytest.raises(OSError):
            plan.release()
    finally:
        AccountLocks._release_file = saved
    assert plan._lock.acquire(blocking=False) is True, "threading 锁被自己永久占住了"
    plan._lock.release()


def test_scheduler_task_survives_a_failing_lock_release(tmp_path, monkeypatch):
    """🔴 收尾动作炸了也不许终止调度任务（BLK-1 的第 ② 条，走真实 `Scheduler.start`）。"""
    d = tmp_path / "locks"
    d.mkdir()

    async def main():
        calls: list[int] = []

        async def run():
            calls.append(1)

        def boom(_self, _account):
            raise OSError("release exploded")

        monkeypatch.setattr(AccountLocks, "_release_file", boom)
        sched = Scheduler(interval_s=0.02, plan_lock=PlanLock(d))
        sched.start(run)
        try:
            for _ in range(60):
                await asyncio.sleep(0.02)
                if len(calls) >= 2:
                    break
        finally:
            alive = sched._task is not None and not sched._task.done()
            await sched.stop()
        assert len(calls) >= 2, f"一次释放失败就杀死了定时器：{calls}"
        assert alive, "任务已死却仍被当成'运营在跑'"
        assert sched.errors >= 1, "释放失败必须记账，不许静默"
    asyncio.run(main())


def test_unwritable_lock_dir_refuses_instead_of_granting(tmp_path):
    """🔴 锁目录不可写 → **拒跑**：不放行，也不退 `/tmp`（用户裁决 S-22，推翻第四轮的退路）。

    退路的毛病不是"会失败"而是**成功得可疑**：`/tmp` 本机人人可写、重启即清，
    而"数据目录不可写"本身已经说明这一轮的状态落不下去（熔断文件、`ops-results`
    同样会失败）—— 在这种环境里给用户一次"互斥成立、领取正常"的结果是谎报。
    """
    d = tmp_path / "ro-locks"
    d.mkdir()
    os.chmod(d, 0o500)                             # 只读目录
    locks = AccountLocks(d)
    try:
        assert locks.usable() is False
        assert locks.try_acquire("acct-fb") is False, "拿不到锁却放行了 = 双领"
        assert not (d / "acct-fb.lock").exists()
        # 退路函数一旦被加回来 = 裁决被悄悄改回去
        assert not hasattr(runner_mod, "fallback_lock_dir"), "/tmp 退路被恢复了"
    finally:
        os.chmod(d, 0o700)
    assert locks.usable() is True                  # 正向对照：恢复可写就正常
    assert locks.try_acquire("acct-fb") is True
    locks.release("acct-fb")
    assert not (d / "acct-fb.lock").exists()


def test_run_once_refuses_the_whole_round_when_locks_are_unusable(tmp_path):
    """🔴 互斥建立不起来 = 整轮一个账号都没发起，且**报成 failed**（S-22 的可见性）。

    记成 `skipped` 会被读成"这轮没事干"；只有 `failed` 才进 `ops-results` 落盘、
    点亮顶栏红点、让 `mgw zcode claim` 退出码非 0。
    """
    calls: list[str] = []

    async def fake_claim(account, *, manual=False, runtime=None):
        calls.append(account)
        return OpResult(account, "success")

    async def go():
        d = tmp_path / "ro"
        d.mkdir()
        os.chmod(d, 0o500)
        try:
            return await run_once(accounts=["acct-a", "acct-b"],
                                  locks=AccountLocks(d), claim=fake_claim)
        finally:
            os.chmod(d, 0o700)

    report = asyncio.run(go())
    assert calls == [], "锁没建立起来却照常发起领取"
    assert sorted(a for a, _ in report.failed) == ["acct-a", "acct-b"]
    assert all("不可写" in r for _, r in report.failed), report.failed
    assert report.skipped == [], "拒跑被记成 skipped = 用户以为一切正常"
    assert report.success == [] and report.inactive == []


def test_scheduler_tick_tells_unusable_lock_from_a_busy_one(tmp_path):
    """🔴 定时器：`try_acquire()` 返回 False 有**两种成因**，只有一种需要说出来（S-22）。

    "别人正持有"是设计内的静默跳过；"锁目录建不起来"会**每轮都跳过** =
    运营停摆而进程看着正常 —— 只有后者该计一次错误。
    """
    ran: list[int] = []

    async def the_run():
        ran.append(1)

    async def go():
        busy_dir = tmp_path / "busy"
        sched = Scheduler(plan_lock=PlanLock(busy_dir))
        assert sched.plan_lock.try_acquire() is True     # 同进程自己占着 = 正常忙碌
        await sched._tick(the_run)
        assert ran == [], "正被人持有时不得抢跑"
        assert sched.errors == 0, "正常占用被误报成故障"
        sched.plan_lock.release()
        await sched._tick(the_run)
        assert ran == [1], "释放后同一调度器必须能继续跑"

        ro = tmp_path / "ro"
        ro.mkdir()
        os.chmod(ro, 0o500)
        try:
            broken = Scheduler(plan_lock=PlanLock(ro))
            await broken._tick(the_run)
        finally:
            os.chmod(ro, 0o700)
        assert ran == [1], "锁不可用却继续跑了本轮"
        assert broken.errors == 1, "停摆被静默吞掉 = 每轮跳过而没人知道"

    asyncio.run(go())


def test_plan_lock_blocks_another_process(tmp_path):
    """🔴 plan 级互斥也要跨进程（M-9：cron 与 CLI 不能同时开跑一整轮批量）。"""
    code = (
        "import sys; sys.path.insert(0, {repo!r});"
        "from model_gateway.ops.runner import PlanLock;"
        "p = PlanLock({d!r}); print('HELD' if p.try_acquire() else 'DENIED', flush=True);"
        "import time; time.sleep(1.2); p.release(); print('RELEASED', flush=True)"
    ).format(repo=str(Path(__file__).resolve().parents[2]), d=str(tmp_path / "locks"))
    child = subprocess.Popen([sys.executable, "-c", code],
                             stdout=subprocess.PIPE, text=True, bufsize=1)
    try:
        assert child.stdout.readline().strip() == "HELD"
        parent_lock = PlanLock(tmp_path / "locks")
        assert parent_lock.try_acquire() is False, "plan 锁跨进程不成立 → 两个入口会各开一轮"
    finally:
        child.wait(timeout=15)
    assert "RELEASED" in child.stdout.read()


def test_lock_dir_that_cannot_be_created_denies_instead_of_granting(tmp_path):
    """🔴 连锁目录本身都创建不出来（父目录只读）→ 拒绝拿锁，绝不"拿不到就放行"。

    与 `test_unwritable_lock_dir_refuses_instead_of_granting` 分覆盖两种 OSError：
    那一条是"目录在、写不进"，本条是"`mkdir` 就失败"。放行等于双领，
    而双领正是这把锁存在的唯一理由（§16.4）—— 上一版 `except OSError: return True`
    就是这个方向上的错。
    """
    ro_parent = tmp_path / "roParent"
    ro_parent.mkdir()
    os.chmod(ro_parent, 0o500)
    locks = AccountLocks(ro_parent / "locks")
    try:
        assert locks.try_acquire("acct-zz") is False
        assert locks.usable() is False
    finally:
        os.chmod(ro_parent, 0o700)


def test_ack_does_not_swallow_a_row_appended_mid_ack(tmp_path, monkeypatch):
    """🔴 确认动作只推进到**它读过的那些行**（验收 S-13：两次读之间的新行会被吞）。

    复现真实交错：读文件之后、写水位之前，另一个进程（网关 cron 或另一台终端的 CLI）
    追加了一行失败。若"未读数"与"水位"分两次读，第二次多看到的那一行会被
    水位一起推进去 —— 用户从未见过它，却被记成"已看过"，且 `cleared` 报得比实际多。
    """
    import json as _json

    usage = tmp_path / "usage"
    write_report(OpReport(failed=[("a", "第一轮失败")]), usage)
    path = runner_mod._results_path(usage)
    real = runner_mod._report_rows
    state = {"appended": False}

    def spy(p):
        rows = real(p)
        if not state["appended"]:
            # 模拟并发写者：本次读完成后，文件里多出一行
            with p.open("a", encoding="utf-8") as f:
                f.write(_json.dumps({"ts": "x", "failed": [{"account": "b", "reason": "并发写入"}],
                                     "success": [], "already_done": [], "inactive": [],
                                     "skipped": [], "no_participants": False}) + "\n")
            state["appended"] = True
        return rows

    monkeypatch.setattr(runner_mod, "_report_rows", spy)

    assert ack_reports(usage) == 1, "只该清掉用户真见过的那一轮"
    assert unread_failures(usage) == 1, "并发追加的行被水位吞了（用户从未看过）"


async def test_ops_results_are_pruned_by_the_retention_policy(tmp_path):
    """🔴 `ops-results-<date>.jsonl` 纳入保留策略（验收 S-15：不清 = 用户目录里无限增长）。

    判据走**公开入口** `EventLogger.start()`（清理就挂在它里面），不直接调私有方法。
    """
    import datetime as dt

    from model_gateway.stats.events import EventLogger

    usage = tmp_path / "usage"
    usage.mkdir()
    today = dt.date.today()

    def day(name, offset, suffix=".jsonl"):
        d = (today - dt.timedelta(days=offset)).strftime("%Y%m%d")
        p = usage / f"{name}-{d}{suffix}"
        p.write_text('{"x": 1}\n' if suffix == ".jsonl" else '{"date":"%s"}' % d,
                     encoding="utf-8")
        return p

    stale_ops = day("ops-results", 10)
    fresh_ops = day("ops-results", 1)
    stale_events = day("events", 10)
    daily = usage / f"daily-{(today - dt.timedelta(days=30)).strftime('%Y%m%d')}.json"
    daily.write_text("[]", encoding="utf-8")
    stale_ack = usage / "ops-results-ack.json"
    stale_ack.write_text('{"date": "%s", "rows": 3}'
                         % (today - dt.timedelta(days=10)).strftime("%Y%m%d"), encoding="utf-8")

    EventLogger(usage, retention_days=7).start()
    await asyncio.sleep(0.05)

    assert not stale_ops.exists(), "过期 ops-results 未清理 → 每天一个文件无限增长"
    assert not stale_events.exists(), "原有 events 清理被改坏（回归）"
    assert fresh_ops.exists(), "未过期文件不得被删"
    assert daily.exists(), "daily 快照按方案保留"
    assert not stale_ack.exists(), "过期水位仍留着 = 一个没人再读的孤儿文件"


def test_locks_dying_mid_round_fails_the_remaining_accounts_not_skips_them(tmp_path):
    """🔴 本轮中途锁目录失去可写性 = 后面的账号一个都没发起（第八轮 eng-8b 阻塞）。

    开局探测（S-22）只守住"开跑前"；跑完第一个号才炸的磁盘/权限变更原先落进
    `report.skipped` —— 真实 CLI 于是打印"全部正常，无需处理"、退出码 0、红点不亮，
    而实际什么都没做。这与用户裁决「主目录不可写即拒跑本轮」正好相反。
    """
    d = tmp_path / "locks"
    d.mkdir()
    calls: list[str] = []
    locks = AccountLocks(d)

    async def flaky_claim(account, *, manual=False, runtime=None):
        calls.append(account)
        if len(calls) == 1:
            os.chmod(d, 0o500)          # 第一个号跑完，目录失去可写性
        return OpResult(account, "success")

    async def go():
        try:
            return await run_once(accounts=["acct-1", "acct-2", "acct-3"],
                                 locks=locks, claim=flaky_claim, delay_s=0)
        finally:
            os.chmod(d, 0o700)

    report = asyncio.run(go())
    assert calls == ["acct-1"], f"锁不可用之后还在发起：{calls}"
    failed = {a for a, _ in report.failed}
    assert {"acct-2", "acct-3"} <= failed, report.to_dict()
    assert all("中途不可写" in r for _, r in report.failed), report.failed
    assert report.skipped == [], "拒跑被记成 skipped = CLI 谎报『全部正常』"
    assert len(report.success) == 1, "第一个号是真跑完的，不该被一起抹掉"
