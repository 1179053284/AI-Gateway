"""`accounts/login.py` 单测（tech-design v2.0 §22.3 两步式 + §22.8-2/-3/-9）。

🔴 判据逐条对应契约：
  · TTL（默认 600s）与**显式取消**；超时/取消 → `expired` 且会话出表
  · **`pending` 不是错误**（不得当失败），会话保留等下一次轮询
  · 回调路径（`login_callback`）真的被调度、参数真的传到产品钩子
  · 登录形态（§22.3 补入②）：`start(kind=…)` 缺省主形态 / 备选形态 / **非法值当场 ValueError**
  · 备选形态辅助调用（§22.3 补入③）：`alt_call` 按 `_ALT_HOOKS` 派发、未知名字 KeyError、
    未导出该表 → 可读 RuntimeError
  · **会话纪律三通道同源**（M6-6 收口 R1 F1）：过期/取消的会话走 `alt` 同样被拒
    （`expired`、不派发钩子、不落盘）
  · **引擎层「会话 ↔ 产品」配对**（M6-6 收口 R1 F10）：`poll`/`callback` 错配 →
    可读 `failed`、不消耗会话、不打产品钩子
  · **M7-E 两阶段提交**（2026-10-01 用户裁决）：`success` 只**认领暂存**（`state["pending"]`，
    一个字节都不落盘）；`commit_pending`（「确定接入」）才经 `store.commit_login` 落盘，
    幂等（重复确认/未知会话如实回报，不二次写）。取消/TTL 丢弃暂存（绝不落盘）；
    落盘自检失败与**写盘锁不可用**（§22.8-4 拒写）都在确认步如实回报（不谎报成功）
  · 单飞：同一会话并发 `poll` **只打上游一次**
  · 未登记产品 / 契约表缺项 → 显式 `KeyError`（不静默当作"没实现"）

产品钩子经 `_HOOKS` 契约表调度（`accounts/login.py::_hook`）→ 用例用
`monkeypatch.setitem(模块._HOOKS, 名, 假钩子)` 注入。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from model_gateway.accounts import login, store
from model_gateway.accounts.login import LoginEngine, LoginSession
from model_gateway.accounts.store import CommitError
from model_gateway.accounts.types import Challenge, LoginOutcome
from model_gateway.upstream import buddy as _buddy_pkg  # noqa: F401  （触发产品包导入，与生产同路）
from model_gateway.upstream.buddy import product as buddy
from model_gateway.upstream.lobsterai import product as lobsterai
from model_gateway.upstream.loomy import product as loomy
from model_gateway.upstream.raccoon import product as raccoon


def _patch(module, name: str, fn, monkeypatch) -> None:
    """替换产品契约表里的钩子（引擎按表调度，patch 的是**真实取用点**）。"""
    monkeypatch.setitem(module._HOOKS, name, fn)


# ============ 启动 / 挑战载荷 ============

async def test_start_returns_session_and_challenge_only_user_visible(tmp_path, monkeypatch):
    """`Challenge` 只承载用户可见物；钩子的私有态留在 `session.state`（不回显给用户）。"""
    async def fake_start(session):
        session.state["device_secret"] = "S3CRET"          # 私有态：不得进 Challenge
        return Challenge(url="https://example.test/auth", device_code="ABCD-1234")

    _patch(buddy, "login_start", fake_start, monkeypatch)
    engine = LoginEngine(root=tmp_path / "accounts")
    session = await engine.start("buddy")

    assert session.id and session.name.startswith("buddy-")
    assert session.challenge is not None and session.challenge.url.endswith("/auth")
    assert session.challenge.device_code == "ABCD-1234"
    # Challenge 只允许 §22.3 列的四个用户可见字段（私有态一律不进）
    assert set(vars(session.challenge)) == {"url", "device_code", "qr_payload", "sms_sent"}
    assert "S3CRET" not in json.dumps(vars(session.challenge))
    assert session.state["device_secret"] == "S3CRET"   # 私有态确实在会话里，只是不回显


async def test_default_name_is_whitelisted_and_unique(tmp_path, monkeypatch):
    """默认账号名 = `{product}-{8hex}`（`20 §2.3`），且**不与既有账号重名**。"""
    async def fake_start(session):
        return Challenge(url="u")

    _patch(buddy, "login_start", fake_start, monkeypatch)
    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)
    session = await engine.start("buddy")
    assert session.name.startswith("buddy-") and len(session.name) == len("buddy-") + 8

    store.commit_login("buddy", session.name, {"t": "1"}, {}, root=root)
    other = await engine.start("buddy")
    assert other.name != session.name


async def test_invalid_explicit_name_is_rejected(tmp_path, monkeypatch):
    """显式给的名字非法 → 显式拒绝（不静默改名后写进别人的目录）。"""
    _patch(buddy, "login_start", lambda session: None, monkeypatch)
    engine = LoginEngine(root=tmp_path / "accounts")
    with pytest.raises(ValueError, match="账号名必须匹配"):
        await engine.start("buddy", name="../evil")


# ============ pending 不是错误 ============

async def test_pending_is_not_an_error_and_session_survives(tmp_path, monkeypatch):
    """🔴 `pending` = 正常业务状态：会话保留，下一次轮询还能拿 `success`（暂存）。

    M7-E 两阶段提交：`success` 之后凭据在会话上（`state["pending"]`），
    「确定接入」（`commit_pending`）才落盘。
    """
    calls = {"n": 0}

    async def fake_poll(session):
        calls["n"] += 1
        if calls["n"] == 1:
            return LoginOutcome(state="pending", detail="等待用户在浏览器完成授权")
        return LoginOutcome(state="success", credentials={"token": "T"},
                            meta={"plan": "free"})

    async def fake_start(session):
        return Challenge(url="u")

    _patch(buddy, "login_start", fake_start, monkeypatch)
    _patch(buddy, "login_poll", fake_poll, monkeypatch)
    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)
    session = await engine.start("buddy")

    first = await engine.poll("buddy", session.id)
    assert first.state == "pending" and first.detail

    second = await engine.poll("buddy", session.id)
    assert second.state == "success"
    assert session.state["pending"]["credentials"] == {"token": "T"}
    assert not (root / session.name).exists(), "success 只暂存，不落盘（M7-E）"
    assert (await engine.commit_pending(session.id))["committed"] is True
    assert store.load_credentials("buddy", session.name, root=root) == {"token": "T"}
    assert json.loads((root / session.name / "meta.json").read_text())["plan"] == "free"


async def test_success_keeps_session_until_confirm_then_drops(tmp_path, monkeypatch):
    """终态纪律（M7-E 修订）：**成功不立即出表** —— 会话要留下等「确定接入」
    （出表 = 丢弃暂存 = 用户永远确认不了）；确认落盘后才出表，再轮询是 `expired`。

    确认之前对同一会话再轮询 → 入口短路如实回报"已暂存待确认"（**不再打产品钩子**：
    授权料一次性，重复点只会把成功搅浑）。
    """
    calls = {"n": 0}

    async def fake_start(session):
        return Challenge(url="u")

    async def fake_poll(session):
        calls["n"] += 1
        return LoginOutcome(state="success", credentials={"t": "1"}, meta={})

    _patch(buddy, "login_start", fake_start, monkeypatch)
    _patch(buddy, "login_poll", fake_poll, monkeypatch)
    engine = LoginEngine(root=tmp_path / "accounts")
    session = await engine.start("buddy")
    assert (await engine.poll("buddy", session.id)).state == "success"
    assert calls["n"] == 1
    assert engine.get_session(session.id) is not None, "待确认的会话必须留表"

    again = await engine.poll("buddy", session.id)
    assert again.state == "success" and "暂存" in again.detail, again.detail
    assert calls["n"] == 1, "已认领的会话不许再打产品钩子（入口短路）"

    assert (await engine.commit_pending(session.id))["committed"] is True
    assert engine.get_session(session.id) is None, "确认落盘后出表"
    late = await engine.poll("buddy", session.id)
    assert late.state == "expired" and "会话不存在" in late.detail


# ============ 回调路径 ============

async def test_callback_path_dispatches_with_params(tmp_path, monkeypatch):
    """local_callback 型：`callback` 调 `login_callback(session, params)` 并认领暂存；
    「确定接入」把凭据落盘（M7-E 两阶段提交）。"""
    seen: dict = {}

    async def fake_start(session):
        return Challenge(url="http://127.0.0.1:9999/cb")

    async def fake_callback(session, params):
        seen.update(params)
        return LoginOutcome(state="success", credentials={"token": "C"},
                            meta={"uuid": "u-1"})

    _patch(lobsterai, "login_start", fake_start, monkeypatch)
    _patch(lobsterai, "login_callback", fake_callback, monkeypatch)
    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)
    session = await engine.start("lobsterai")
    outcome = await engine.callback("lobsterai", session.id, {"code": "xyz"})

    assert seen == {"code": "xyz"} and outcome.state == "success"
    assert session.state["pending"]["credentials"] == {"token": "C"}
    assert not (root / session.name).exists(), "回调只暂存，不落盘（M7-E）"
    assert (await engine.commit_pending(session.id))["committed"] is True
    assert store.load_credentials("lobsterai", session.name, root=root) == {"token": "C"}


# ============ TTL / 取消 ============

async def test_ttl_expiry_is_enforced(tmp_path, monkeypatch):
    """🔴 会话 TTL（§22.8-2）：超时即失效、**不续命**，且会话出表。"""
    async def fake_start(session):
        return Challenge(url="u")

    async def fake_poll(session):                      # pragma: no cover —— 不该被调到
        raise AssertionError("超时会话不得再打产品钩子")

    _patch(buddy, "login_start", fake_start, monkeypatch)
    _patch(buddy, "login_poll", fake_poll, monkeypatch)
    clock = {"t": 1000.0}
    engine = LoginEngine(root=tmp_path / "accounts", now=lambda: clock["t"])
    session = await engine.start("buddy")
    clock["t"] += 601
    outcome = await engine.poll("buddy", session.id)
    assert outcome.state == "expired" and "超时" in outcome.detail
    assert engine.cancel(session.id) is False, "超时会话应已出表"


async def test_explicit_cancel(tmp_path, monkeypatch):
    """显式取消：取消后轮询返回 `expired`；重复取消返回 False。"""
    async def fake_start(session):
        return Challenge(url="u")

    _patch(buddy, "login_start", fake_start, monkeypatch)
    engine = LoginEngine(root=tmp_path / "accounts")
    session = await engine.start("buddy")
    assert engine.cancel(session.id) is True
    outcome = await engine.poll("buddy", session.id)
    assert outcome.state == "expired" and "取消" in outcome.detail
    assert engine.cancel(session.id) is False


async def test_shutdown_clears_sessions(tmp_path, monkeypatch):
    """进程退出钩子：清空会话表（**不建后台任务**，无孤儿可取消）。"""
    async def fake_start(session):
        return Challenge(url="u")

    _patch(buddy, "login_start", fake_start, monkeypatch)
    engine = LoginEngine(root=tmp_path / "accounts")
    session = await engine.start("buddy")
    engine.shutdown()
    assert (await engine.poll("buddy", session.id)).state == "expired"


# ============ 登录形态（§22.3 补入②）============

async def test_start_kind_defaults_to_primary_and_accepts_alt(tmp_path, monkeypatch):
    """`start(kind=…)`：缺省取 `ProductMeta.login`（主形态）；`login_alt` 内的值被接受并写进会话。"""
    async def fake_start(session):
        return Challenge(url="u")

    _patch(loomy, "login_start", fake_start, monkeypatch)
    engine = LoginEngine(root=tmp_path / "accounts")

    primary = await engine.start("loomy")
    assert primary.kind == "qr" == loomy.meta().login          # 缺省 = 主推形态
    alt = await engine.start("loomy", kind="sms_code")         # `login_alt=("sms_code",)`
    assert alt.kind == "sms_code" and alt.id != primary.id


async def test_start_kind_illegal_value_fails_loudly(tmp_path, monkeypatch):
    """非法 `kind` **当场** `ValueError`（消息列合法值）——**不静默回退**到主形态。"""
    async def fake_start(session):                             # pragma: no cover —— 不该被调到
        raise AssertionError("非法 kind 不得再打产品钩子")

    _patch(loomy, "login_start", fake_start, monkeypatch)
    engine = LoginEngine(root=tmp_path / "accounts")
    with pytest.raises(ValueError, match="登录方式 'device_code' 非法") as err:
        await engine.start("loomy", kind="device_code")
    assert "'qr'" in str(err.value) and "'sms_code'" in str(err.value)


# ============ `_ALT_HOOKS` 派发（§22.3 补入③）============

def _session(product: str, name: str = "acc-1", *,
             root=None, created_at: float = 1.0, ttl_s: float = 60.0,
             now=None) -> LoginSession:
    """直构会话（钩子只经 `session.state` 存私态；形态字段 = `kind`）。

    `root` 可选：`alt_call` 的落盘锚点从会话回传（引擎创建的会话带 root）。
    `now` 可选：与引擎同源的 TTL 时钟（`LoginSession.now`，M6-6）——缺省给一个与
    `created_at` 自洽的常量钟（会话视为"刚创建、未过期"；TTL 用例自注入时钟）。
    """
    return LoginSession(id="s-fix", product=product, name=name,
                        created_at=created_at, ttl_s=ttl_s, kind="sms_code",
                        root=root, now=now or (lambda: created_at))


async def test_alt_call_dispatches_by_table_with_kwargs(monkeypatch):
    """`alt_call` 按 `_ALT_HOOKS` 表取钩子（不 `getattr`）：`session` 位置传 + 其余 kwarg。"""
    seen: dict = {}

    async def fake_send(session, *, phone: str):
        seen["session"] = session
        seen["phone"] = phone
        return LoginOutcome(state="pending", detail="验证码已发送")

    monkeypatch.setitem(loomy._ALT_HOOKS, "sms_send", fake_send)
    session = _session("loomy")
    outcome = await login.alt_call("loomy", session, "sms_send", phone="13800138000")
    assert seen == {"session": session, "phone": "13800138000"}
    assert outcome.state == "pending"


async def test_alt_call_unknown_name_and_missing_table_fail_loudly():
    """未知名字当场 `KeyError`（列合法值）；未导出 `_ALT_HOOKS` → 可读 `RuntimeError`。"""
    session = _session("loomy")
    with pytest.raises(KeyError) as err:
        await login.alt_call("loomy", session, "sms_call")
    assert "sms_call" in str(err.value) and "sms_send" in str(err.value)   # 合法值可读

    with pytest.raises(RuntimeError, match="_ALT_HOOKS"):
        await login.alt_call("buddy", _session("buddy"), "sms_send", phone="13800138000")
    with pytest.raises(KeyError, match="未登记的产品"):          # 与 `_hook` 同口径
        await login.alt_call("codearts", _session("codearts"), "sms_send")


async def test_alt_call_rejects_cross_product_session():
    """防串线：会话表是全局的，入口层配错产品 → 当场 `ValueError`（不拿 A 的钩子驱动 B 的会话）。"""
    with pytest.raises(ValueError, match="不匹配"):
        await login.alt_call("loomy", _session("raccoon"), "sms_send", phone="13800138000")


async def test_alt_call_success_stages_and_confirm_persists(tmp_path, monkeypatch):
    """🔴 备选形态第二段成功 → **只认领暂存**（M7-E 两阶段提交）；「确定接入」（`commit_pending`）
    经与 poll/callback 同一条 `_commit_outcome` 落盘（写回自检 + 失败回滚）。

    修前缺陷（W3-fix）是"第二段成功不落盘"；M7-E 把落盘点移到确认步 —— 五型登录统一由
    向导的**唯一一次**「确定接入」落盘（短信型不再绕过确认，与用户裁决逐字一致）。
    返回 `Challenge` 的钩子（raccoon `sms_send`）无凭据可认领 → 不得触碰落盘路径。
    """
    async def fake_submit(session, *, sms_code: str):
        return LoginOutcome(state="success", credentials={"token": "SMS-T"},
                            meta={"nickname": "n"})

    async def fake_send(session, *, phone: str, captcha_param: str = ""):
        return Challenge(sms_sent=True)

    def _boom(*a, **k):                                    # pragma: no cover —— 不该被调到
        raise AssertionError("Challenge 结果不得走落盘路径")

    monkeypatch.setitem(loomy._ALT_HOOKS, "sms_submit", fake_submit)
    monkeypatch.setitem(raccoon._ALT_HOOKS, "sms_send", fake_send)
    with pytest.MonkeyPatch.context() as mp:               # 局部桩：只为钉"Challenge 不落盘"
        mp.setattr(login.store, "commit_login", _boom)
        sent = await login.alt_call("raccoon", _session("raccoon"), "sms_send",
                                    phone="13800138000")
    assert isinstance(sent, Challenge) and sent.sms_sent is True

    root = tmp_path / "accounts"                           # success 的落盘锚点 = 会话 root
    session = _session("loomy", root=root)
    outcome = await login.alt_call("loomy", session, "sms_submit", sms_code="123456")
    assert outcome.state == "success"
    assert session.state["pending"]["credentials"] == {"token": "SMS-T"}
    assert not (root / "acc-1").exists(), "第二段成功也只暂存，不落盘（M7-E）"
    # 直构会话手工登记进引擎（生产路径由 `engine.start` 登记）——确认步按会话 id 找对象
    engine = LoginEngine(root=root)
    engine._sessions[session.id] = session
    assert (await engine.commit_pending(session.id))["committed"] is True
    assert store.load_credentials("loomy", "acc-1", root=root) == {"token": "SMS-T"}
    assert json.loads((root / "acc-1" / "meta.json").read_text())["nickname"] == "n"


async def test_alt_call_confirm_failure_is_reported_and_not_faked(tmp_path, monkeypatch):
    """alt 通道的**确认落盘**自检失败 → `committed=False` + 可读原因（**不谎报成功**，§22.3）；
    暂存保留（可重试），磁盘上没有任何半成品。"""
    async def fake_submit(session, *, sms_code: str):
        return LoginOutcome(state="success", credentials={"t": "1"}, meta={})

    def boom(*a, **k):
        raise CommitError("写回自检：凭据键 't' 读回不一致")

    monkeypatch.setitem(loomy._ALT_HOOKS, "sms_submit", fake_submit)
    monkeypatch.setattr(login.store, "commit_login", boom)
    root = tmp_path / "accounts"
    session = _session("loomy", root=root)
    outcome = await login.alt_call("loomy", session, "sms_submit", sms_code="1")
    assert outcome.state == "success" and outcome.credentials == {"t": "1"}, \
        "第一段只认领：outcome 原样（凭据不回显给入口层，但对象上还在）"

    engine = LoginEngine(root=root)
    engine._sessions[session.id] = session
    res = await engine.commit_pending(session.id)
    assert res["committed"] is False and "落盘" in res["reason"], res
    assert session.state["pending"]["credentials"] == {"t": "1"}, "失败时暂存保留（可重试）"
    assert not (root / "acc-1").exists(), "自检失败 = 已回滚，不许留半成品"


# ============ `alt` 通道的会话纪律（M6-6 收口 R1 F1）============

async def test_alt_call_refuses_expired_session_and_persists_nothing(tmp_path, monkeypatch):
    """🔴 过期会话走 `alt` 必须被拒：`expired`、**零钩子调用、零落盘**（R1 F1）。

    修前 `alt_call` 是纯派发：`expired=True` 的会话仍能走完短信第二段并写出
    `credentials.json`（§22.8-2「会话 TTL 与取消」硬清单被整条绕开）。
    TTL 判定必须与 `_advance` 同源（会话自带的引擎钟，而不是另一只钟）——
    正向对照用远小于真 `monotonic` 的注入钟钉住这一点。
    """
    calls: list[str] = []

    async def fake_start(session):
        return Challenge(url="u")

    async def fake_submit(session, *, sms_code: str):     # pragma: no cover —— 第二段不该被调到
        calls.append(sms_code)
        return LoginOutcome(state="success", credentials={"token": "SMS-OK"}, meta={})

    _patch(loomy, "login_start", fake_start, monkeypatch)
    monkeypatch.setitem(loomy._ALT_HOOKS, "sms_submit", fake_submit)
    root = tmp_path / "accounts"
    clock = {"t": 5.0}
    engine = LoginEngine(root=root, now=lambda: clock["t"])

    live = await engine.start("loomy", kind="sms_code")   # 正向对照：TTL 内照常派发
    ok = await login.alt_call("loomy", live, "sms_submit", sms_code="1")
    assert ok.state == "success" and calls == ["1"]

    expired = await engine.start("loomy", kind="sms_code")
    clock["t"] += 601                                     # 越过 TTL（600s）→ 不续命
    outcome = await login.alt_call("loomy", expired, "sms_submit", sms_code="2")
    assert outcome.state == "expired" and "超时" in outcome.detail
    assert outcome.credentials == {}
    assert calls == ["1"], "过期会话不得再打到产品钩子"
    assert not (root / expired.name / "credentials.json").exists(), "过期会话不得落盘凭据"


async def test_alt_call_refuses_cancelled_session_and_persists_nothing(tmp_path, monkeypatch):
    """🔴 已取消会话走 `alt` 同样被拒：`expired`、零钩子调用、零落盘（R1 F1；与 `_advance` 同闸）。"""
    calls: list[str] = []

    async def fake_start(session):
        return Challenge(url="u")

    async def fake_submit(session, *, sms_code: str):     # pragma: no cover —— 不该被调到
        calls.append(sms_code)
        return LoginOutcome(state="success", credentials={"token": "X"}, meta={})

    _patch(loomy, "login_start", fake_start, monkeypatch)
    monkeypatch.setitem(loomy._ALT_HOOKS, "sms_submit", fake_submit)
    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)
    session = await engine.start("loomy", kind="sms_code")
    assert engine.cancel(session.id) is True              # 出表；对象仍被本用例持有（旧对象）

    outcome = await login.alt_call("loomy", session, "sms_submit", sms_code="3")
    assert outcome.state == "expired" and "取消" in outcome.detail
    assert outcome.credentials == {}
    assert calls == [], "取消会话不得再打到产品钩子"
    assert not (root / session.name / "credentials.json").exists(), "取消会话不得落盘凭据"


# ============ 引擎层「会话 ↔ 产品」配对（M6-6 收口 R1 F10）============

async def test_poll_and_callback_refuse_cross_product_session(tmp_path, monkeypatch):
    """🔴 引擎层纵深防御：`poll`/`callback` 校验会话产品配对（错配 → 可读 `failed`、**不消耗会话**）。

    入口层已有 400 校验，但 `LoginEngine` 是公共层公开类型 —— 约束不能只靠调用方自觉
    （`alt_call` 早就有这层校验，家族内一致性）。
    """
    calls: list[str] = []

    async def fake_start(session):
        return Challenge(url="u")

    async def fake_poll(session):
        calls.append("poll")
        return LoginOutcome(state="success", credentials={"t": "1"}, meta={})

    _patch(buddy, "login_start", fake_start, monkeypatch)
    _patch(buddy, "login_poll", fake_poll, monkeypatch)
    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)
    session = await engine.start("buddy")

    wrong = await engine.poll("lobsterai", session.id)
    assert wrong.state == "failed" and "不匹配" in wrong.detail
    wrong_cb = await engine.callback("lobsterai", session.id, {"code": "x"})
    assert wrong_cb.state == "failed" and "不匹配" in wrong_cb.detail
    assert calls == [], "错配不得打到产品钩子"

    ok = await engine.poll("buddy", session.id)           # 会话未被错配消耗
    assert ok.state == "success" and calls == ["poll"]
    assert (await engine.commit_pending(session.id))["committed"] is True
    assert store.load_credentials("buddy", session.name, root=root) == {"t": "1"}


# ============ 单飞（§22.8-3）============

async def test_concurrent_poll_is_single_flight(tmp_path, monkeypatch):
    """🔴 同一会话并发轮询 → 复用同一在飞任务，**只打上游一次**。"""
    calls = {"n": 0}

    async def fake_start(session):
        return Challenge(url="u")

    async def fake_poll(session):
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return LoginOutcome(state="pending", detail="等待")

    _patch(buddy, "login_start", fake_start, monkeypatch)
    _patch(buddy, "login_poll", fake_poll, monkeypatch)
    engine = LoginEngine(root=tmp_path / "accounts")
    session = await engine.start("buddy")

    got = await asyncio.gather(*(engine.poll("buddy", session.id) for _ in range(3)))
    assert calls["n"] == 1, f"并发轮询重复点了上游：{calls['n']} 次"
    assert {o.state for o in got} == {"pending"}


# ============ 确认落盘失败可见（不谎报成功；M7-E 把失败点移到确认步）============

async def test_commit_failure_is_reported_at_confirm_and_not_faked(tmp_path, monkeypatch):
    """确认落盘自检失败（已回滚）→ `committed=False` + 可读原因（**不谎报成功**）；
    第一段的 `success`/暂存不受影响（写盘只发生在确认步），暂存保留可重试。"""
    async def fake_start(session):
        return Challenge(url="u")

    async def fake_poll(session):
        return LoginOutcome(state="success", credentials={"t": "1"}, meta={})

    def boom(*a, **k):
        raise CommitError("写回自检：凭据键 't' 读回不一致")

    _patch(buddy, "login_start", fake_start, monkeypatch)
    _patch(buddy, "login_poll", fake_poll, monkeypatch)
    monkeypatch.setattr(login.store, "commit_login", boom)
    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)
    session = await engine.start("buddy")
    outcome = await engine.poll("buddy", session.id)
    assert outcome.state == "success", "第一段只认领暂存，写盘失败不该在这里出现"
    assert not (root / session.name).exists()

    res = await engine.commit_pending(session.id)
    assert res["committed"] is False and "落盘" in res["reason"], res
    assert session.state["pending"]["credentials"] == {"t": "1"}, "失败可重试（暂存保留）"
    assert not (root / session.name).exists()


# ============ 拒写（`WriteLockError`）与自检失败同档（eng-a-2 §1.4 登记缺口收口）============

def _hold_foreign_write_lock(tmp_path, monkeypatch) -> None:
    """伪造"另一个进程正持有账号写锁"：锁文件写 `<pid=1> <token>`（launchd/init 恒存活）。

    与 `test_store.py` 的 §22.8-4 用例同一手法：`pid=1` 命中"持有者存活且未超龄"分支
    （非 root 下 `os.kill(1, 0)` 抛 PermissionError → 判活）；等锁预算压到 0.05s
    （`store._LOCK_WAIT_S`），用例不必真等 1 秒。
    """
    lock_dir = tmp_path / "locks"
    monkeypatch.setenv(store.ACCOUNTS_LOCK_DIR_ENV, str(lock_dir))
    monkeypatch.setattr(store, "_LOCK_WAIT_S", 0.05)
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / store.ACCOUNTS_LOCK_NAME).write_text(f"1 {'f' * 16}", encoding="utf-8")


async def test_write_lock_refusal_is_reported_at_confirm(tmp_path, monkeypatch):
    """🔴 拒写必须在**确认步**如实回报：`committed=False`、reason 写明"写盘锁不可用（未落盘）"、
    账号目录不存在（"落盘失败 → 不谎报成功"这句在 M7-E 后落在 `commit_pending` 的出口上）。

    修前：`WriteLockError` 落在 `except (CommitError, ValueError, OSError)` 之外 →
    **原样上抛**（HTTP 层 500），引擎侧 `outcome.state` 停在 `"success"`（eng-a-2 §1.4 登记）；
    M7-E 后写盘只发生在确认步，本用例把拒写的**如实回报**钉在那一步。
    """
    async def fake_start(session):
        return Challenge(url="u")

    async def fake_poll(session):
        return LoginOutcome(state="success", credentials={"t": "1"}, meta={"plan": "free"})

    _patch(buddy, "login_start", fake_start, monkeypatch)
    _patch(buddy, "login_poll", fake_poll, monkeypatch)
    _hold_foreign_write_lock(tmp_path, monkeypatch)

    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)
    session = await engine.start("buddy")
    outcome = await engine.poll("buddy", session.id)
    assert outcome.state == "success", "第一段成功（暂存）；拒写只应出现在确认步"

    res = await engine.commit_pending(session.id)
    assert res["committed"] is False, f"拒写不得报成功：{res}"
    assert "写盘锁不可用" in res["reason"] and "未落盘" in res["reason"], res["reason"]
    # 🔴 归因必须是"一个字都没写"（不是"写坏了已回滚"）——`store.WriteLockError` 的
    #    docstring 明确禁止套用自检那句文案（两者处置完全不同）
    assert "已回滚" not in res["reason"], res["reason"]
    assert not (root / session.name).exists(), "拒写 = 一个字节都不落（账号目录不得出现）"


async def test_alt_call_write_lock_refusal_is_reported_at_confirm(tmp_path, monkeypatch):
    """同一判据走 `alt` 通道（两条通道共用同一条确认落盘路径，不得各有一份口径）。"""
    async def fake_submit(session, *, sms_code: str):
        return LoginOutcome(state="success", credentials={"t": "2"}, meta={})

    monkeypatch.setitem(loomy._ALT_HOOKS, "sms_submit", fake_submit)
    _hold_foreign_write_lock(tmp_path, monkeypatch)

    root = tmp_path / "accounts"
    session = _session("loomy", root=root)
    outcome = await login.alt_call("loomy", session, "sms_submit", sms_code="1")
    assert outcome.state == "success", "第一段成功（暂存）"

    engine = LoginEngine(root=root)
    engine._sessions[session.id] = session
    res = await engine.commit_pending(session.id)
    assert res["committed"] is False, f"拒写不得报成功：{res}"
    assert "写盘锁不可用" in res["reason"] and "未落盘" in res["reason"], res["reason"]
    assert not (root / "acc-1").exists(), "拒写 = 一个字节都不落"


# ============ 显式失败 ============

async def test_unknown_product_and_missing_hook_fail_loudly(tmp_path, monkeypatch):
    """未登记产品 → KeyError（`codearts` 已排除）；契约表缺项 → KeyError（不静默）。"""
    engine = LoginEngine(root=tmp_path / "accounts")
    with pytest.raises(KeyError, match="未登记的产品"):
        await engine.start("codearts")

    monkeypatch.delitem(buddy._HOOKS, "login_start")
    with pytest.raises(KeyError, match="契约表"):
        await engine.start("buddy")


# ============ 门面（入口层直接用这三个）============

async def test_module_facades_drive_the_shared_engine(tmp_path, monkeypatch):
    """门面 `start_login`/`poll_login`/`cancel_login` 走进程级共享引擎，能端到端跑通。"""
    async def fake_start(session):
        return Challenge(qr_payload="data:image/png;base64,AAAA")

    async def fake_poll(session):
        return LoginOutcome(state="pending", detail="等待扫码")

    _patch(buddy, "login_start", fake_start, monkeypatch)
    _patch(buddy, "login_poll", fake_poll, monkeypatch)
    session = await login.start_login("buddy")
    try:
        assert session.challenge.qr_payload.startswith("data:image/png")
        assert (await login.poll_login("buddy", session.id)).state == "pending"
    finally:
        assert login.cancel_login(session.id) is True
    login.shutdown_login()
