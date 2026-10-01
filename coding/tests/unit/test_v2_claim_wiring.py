"""v2.0 §16.6 / §17 领取链路**接线**单元测试（本轮修复 R1 / R2）。

与 `test_v2_ops.py` 的分工：那边注入**假 claim** 验证批量执行器；
本文件走**生产函数** `ops/builtin/zcode_claim.claim()`（只把 HTTP 上游换成假客户端），
凭据/熔断/激活上报全部真实执行。

> 为什么必须这样：上一轮 462 条全绿，却漏了两个缺陷 ——
> `zcode_claim` 缺 `import json`（真实凭据下必 `NameError`）、
> CLI 进程的风控熔断静默不生效。**注入假 claim 的测试照不出这两类问题。**
"""

from __future__ import annotations

import asyncio
import json

import pytest

from model_gateway.ops import runner
from model_gateway.ops.builtin import zcode_claim
from model_gateway.upstream.zcode import captcha
from model_gateway.upstream.zcode import claim as claim_mod
from model_gateway.upstream.zcode import quota as zq
from model_gateway.upstream.zcode.dataroot import v2_dir_of

ACCOUNT = "acct-a"


@pytest.fixture
def accounts_root(tmp_path, monkeypatch):
    """隔离账号目录 + 一份**真实形状**的凭据（明文值；`crypto.decrypt` 原样返回）。"""
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(tmp_path))
    write_credentials(tmp_path, ACCOUNT)
    return tmp_path


def write_credentials(root, account: str, *, user_info: str = '{"id": 42, "name": "u"}',
                      jwt: str = "jwt-abc", mid: str = "mid-123") -> None:
    v2 = v2_dir_of(root, account)
    v2.mkdir(parents=True, exist_ok=True)
    (root / account / "meta.json").write_text(json.dumps({"device_mid": mid}),
                                              encoding="utf-8")
    body = {"oauth:active_provider": "zai", "zcodejwttoken": jwt}
    if user_info is not None:
        body["oauth:zai:user_info"] = user_info
    (v2 / "credentials.json").write_text(json.dumps(body), encoding="utf-8")


# ---------- R1：凭据解析（缺 `import json` 时这里直接 NameError）----------

def test_credentials_of_returns_jwt_mid_and_uid(accounts_root):
    jwt, mid, uid = zcode_claim._credentials_of(ACCOUNT)
    assert (jwt, mid) == ("jwt-abc", "mid-123")
    assert uid == "42"  # user_info.id 必须是字符串（激活事件体要求）


def test_credentials_of_tolerates_broken_user_info(accounts_root, tmp_path):
    """user_info 不是合法 JSON → uid 空串、**不抛**（少一次激活上报，不影响领取结论）。"""
    write_credentials(tmp_path, ACCOUNT, user_info="{ 这不是 JSON")
    jwt, _mid, uid = zcode_claim._credentials_of(ACCOUNT)
    assert jwt == "jwt-abc" and uid == ""


# ---------- 假上游（只替换 HTTP 边界）----------

class _FakePlan:
    plan_id = "p1"


class _FakeClient:
    def __init__(self, outcome):
        self._outcome = outcome
        self.activated: list[str] = []
        self.closed = False

    async def preview(self):
        return _FakePlan()

    async def claim(self, plan_id, *, manual=False):
        return self._outcome

    async def report_activation(self, *, user_id=""):
        self.activated.append(user_id)

    async def aclose(self):
        self.closed = True


def run_claim(account, outcome, *, runtime=None):
    client = _FakeClient(outcome)
    res = asyncio.run(zcode_claim.claim(account, client_factory=lambda: client,
                                        runtime=runtime))
    return res, client


class _Recorder:
    """替换 `quota.bench_account`（进程内回写）并记录调用。"""

    def __init__(self, monkeypatch, attr="bench_account", target=zq):
        self.calls = []

        def fake(runtime, account, *, reason, seconds=None):
            self.calls.append({"account": account, "reason": reason, "seconds": seconds})
            return 1

        monkeypatch.setattr(target, attr, fake)


def record_admin_post(monkeypatch):
    """替换跨进程出口 `local_admin.admin_post`（CLI 进程 → 让运行中的网关回写）。"""
    import model_gateway.core.local_admin as local_admin

    calls = []

    def fake(path, **kw):
        calls.append({"path": path, **kw})
        return {"ok": True}

    monkeypatch.setattr(local_admin, "admin_post", fake)
    return calls


# ---------- R2：风控熔断的**两条**入口都要生效 ----------

def test_risk_control_benches_in_process(accounts_root, monkeypatch):
    """cron 腿（同进程持有 runtime）→ 直接回写 `ResourceState`。"""
    rec = _Recorder(monkeypatch)
    admin = record_admin_post(monkeypatch)
    res, _ = run_claim(ACCOUNT,
                       claim_mod.ClaimOutcome(code=zq.CODE_RISK_CONTROL,
                                              message="unusual activity"),
                       runtime=object())
    assert res.category == "failed"
    assert len(rec.calls) == 1 and rec.calls[0]["account"] == ACCOUNT
    assert "风控熔断" in rec.calls[0]["reason"]
    assert admin == []  # 有 runtime 时不走 HTTP


def test_risk_control_benches_from_cli_process(accounts_root, monkeypatch):
    """🔴 CLI 腿（`runtime=None`，独立进程）→ 必须经管理端点让**运行中的网关**回写。

    上一轮只接了 cron 一条腿：`cli_zcode` 调 `run_once` 不传 runtime，
    `_maybe_bench` 直接 return → 手动领取遇风控时熔断**静默不生效**。
    """
    rec = _Recorder(monkeypatch)
    admin = record_admin_post(monkeypatch)
    res, _ = run_claim(ACCOUNT,
                       claim_mod.ClaimOutcome(code=zq.CODE_RISK_CONTROL,
                                              message="unusual activity"),
                       runtime=None)
    assert res.category == "failed"
    assert rec.calls == []  # 独立进程改不到内存态
    assert len(admin) == 1, "runtime=None 时也必须触发熔断出口"
    assert admin[0]["path"] == "/admin/api/zcode/bench"
    assert admin[0]["payload"]["account"] == ACCOUNT


def test_risk_control_detected_by_message_not_only_code(accounts_root, monkeypatch):
    """上游把风控塞在 `message` 里（码值漂移）时也要熔断 —— 判据是**码或文案**二者之一。"""
    admin = record_admin_post(monkeypatch)
    run_claim(ACCOUNT, claim_mod.ClaimOutcome(code=-1, message="检测到 unusual activity"),
              runtime=None)
    assert len(admin) == 1


# ---------- 正常业务态不得熔断 ----------

def test_already_claimed_does_not_bench(accounts_root, monkeypatch):
    """`1003` 已领过 = `already_done`（正常业务态），不得熔断。"""
    rec = _Recorder(monkeypatch)
    admin = record_admin_post(monkeypatch)
    res, _ = run_claim(ACCOUNT,
                       claim_mod.ClaimOutcome(code=claim_mod.CODE_ALREADY_CLAIMED,
                                              message="该套餐已领取过"),
                       runtime=object())
    assert res.category == "already_done"
    assert rec.calls == [] and admin == []


def test_quota_exhausted_is_inactive_not_benched(accounts_root, monkeypatch):
    """`1005` 今日名额用完 → `inactive`（§16.2 正常业务态），不熔断。"""
    rec = _Recorder(monkeypatch)
    admin = record_admin_post(monkeypatch)
    res, _ = run_claim(ACCOUNT,
                       claim_mod.ClaimOutcome(code=claim_mod.CODE_QUOTA_EXHAUSTED,
                                             message="今日名额已用完",
                                             next_at="2026-09-27T00:00:00Z"),
                       runtime=object())
    assert res.category == "inactive"
    assert rec.calls == [] and admin == []


def test_success_reports_activation_event(accounts_root, monkeypatch):
    """签到 = `billing/claim` **+** `event/report`（§16.4）—— 只领不报等于没签到。"""
    record_admin_post(monkeypatch)
    res, client = run_claim(ACCOUNT, claim_mod.ClaimOutcome(code=0), runtime=object())
    assert res.category == "success"
    assert client.activated == ["42"]
    assert client.closed is True  # 客户端必须关闭（防连接泄漏）


def test_missing_credentials_fails_with_hint(accounts_root, tmp_path, monkeypatch):
    """凭据缺失 → failed 且文案指路（不得静默失败）。"""
    write_credentials(tmp_path, ACCOUNT, jwt="")
    record_admin_post(monkeypatch)
    res, _ = run_claim(ACCOUNT, claim_mod.ClaimOutcome(code=0), runtime=None)
    assert res.category == "failed"
    assert "mgw zcode" in res.detail


def test_network_error_is_isolated_as_failed(accounts_root, monkeypatch):
    """上游抛网络异常 → 该账号 failed（带 `network:` 前缀供退避重试），不抛给批量层。"""
    class _Boom:
        async def preview(self):
            raise OSError("connection reset")

        async def aclose(self):
            pass

    record_admin_post(monkeypatch)
    res = asyncio.run(zcode_claim.claim(ACCOUNT, client_factory=lambda: _Boom(), runtime=None))
    assert res.category == "failed"
    assert res.detail.startswith("network:")


# ---------- 验证码不可用：必须由**真实求解器**产生（第四轮：异常类只有一份）----------
#
# 上一轮这里的用例是"手工抛一个 claim 侧异常"——**自己造答案**：求解器另定义了
# 一个同名 `CaptchaUnavailable`，`zcode_claim` 捕获的却是 claim 那份，于是求解失败
# 落到 `except Exception` 兜底、被打上 `network:` 前缀，批量执行器据此对一次注定
# 失败的求解退避重试 3 次。现在的断言一律**不注入假 claim、不自造异常**：
# 只把 HTTP 边界换掉，装配（`_build_client`）与求解器（`captcha.get_solver`）走真的。


class _Resp:
    def __init__(self, body: dict):
        self._body = body
        self.status_code = 200

    def json(self) -> dict:
        return self._body


class _FakeUpstream:
    """假 HTTP 边界：按 URL 返回真实形状响应，并记录各接口被打了几次。"""

    def __init__(self):
        self.previews = 0
        self.claims = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kw):
        assert url.endswith("/billing/preview"), url
        self.previews += 1
        return _Resp({"data": {"plans": [{"plan_id": "p1", "priority": 1, "name": "每日"}]}})

    async def post(self, url, **kw):
        assert url.endswith("/billing/claim"), url
        self.claims += 1
        return _Resp({"code": 0, "data": {}})


@pytest.fixture
def no_proxy_config(monkeypatch, tmp_path):
    """确定性配置：`MG_CONFIG` 指向不存在的路径 → 内置默认（`zcode.proxy` 为空）。"""
    monkeypatch.setenv("MG_CONFIG", str(tmp_path / "no-such-config.yaml"))
    monkeypatch.delenv("MGW_ZCODE_PROXY", raising=False)
    captcha.reset_solver_for_tests()
    yield
    captcha.reset_solver_for_tests()


@pytest.fixture
def fake_upstream(monkeypatch):
    up = _FakeUpstream()

    def _http(self, timeout):               # noqa: ANN001 — 同步返回异步上下文管理器（与被换者同形）
        return up

    monkeypatch.setattr(claim_mod.ZCodeClaimClient, "_http", _http)
    return up


def test_client_is_always_assembled_with_a_solver(no_proxy_config):
    """`_build_client` 必须把求解器接上（§16.5）—— 撤掉 `captcha_solver=` 这条就红。"""
    client = zcode_claim._build_client("jwt-abc", "mid-123")
    assert isinstance(client._captcha_solver, captcha.CaptchaSolver)
    assert client._captcha_solver.proxy == ""


def test_solver_reason_reaches_the_user_verbatim(accounts_root, no_proxy_config, fake_upstream):
    """未配住宅代理 → 用户看到的是**求解器给的原因**，且**不带 `network:` 前缀**。

    前缀是"网络类、可重试"的暗号：带上它一次配置问题会被重试 3 轮，
    并且把"去配代理"这条唯一出路混进"网络抖动、等会儿自愈"里。
    """
    res = asyncio.run(zcode_claim.claim(ACCOUNT, runtime=None))
    assert res.category == "failed"
    assert "未配置住宅代理" in res.detail
    assert not res.detail.startswith("network:")
    assert fake_upstream.previews == 1      # 打了 1 次 preview，之后卡在验证码
    assert fake_upstream.claims == 0


def test_solver_reason_for_manual_mode_is_not_the_proxy_hint(
        accounts_root, no_proxy_config, fake_upstream):
    """`--manual` 时文案换成"去客户端手动领" —— 配了 --manual 还让人查代理是误导。"""
    res = asyncio.run(zcode_claim.claim(ACCOUNT, manual=True, runtime=None))
    assert res.category == "failed"
    assert "手动" in res.detail
    assert "未配置住宅代理" not in res.detail
    assert not res.detail.startswith("network:")


def test_batch_executor_does_not_retry_a_captcha_failure(
        accounts_root, no_proxy_config, fake_upstream):
    """🔴 红证：把异常类改回两份 → 这里 `previews` 变成 3（对同一配置问题重试 3 轮）。"""
    slept: list[float] = []

    async def _sleep(s: float) -> None:
        slept.append(s)

    async def _claim(acct: str):
        return await zcode_claim.claim(acct, runtime=None)

    res = asyncio.run(runner._run_one(ACCOUNT, _claim,
                                      attempts=runner.MAX_ATTEMPTS_PER_ACCOUNT,
                                      sleep=_sleep))
    assert res.category == "failed"
    assert fake_upstream.previews == 1, f"重试了 {fake_upstream.previews} 次"
    assert slept == []                      # 网络退避一秒都不该睡
    assert runner._looks_retryable(res.detail) is False
