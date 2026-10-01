"""`qoder` 产品钩子单测（M6-2 批 A；tech-design §22.3/§22.4 + `20 §1.2/§2.7/§3.1`）。

🔴 **无网络、无真实凭据**：假上游 = `httpx.MockTransport`（经 `flow._transport` 测试接缝注入），
   账号根与 `machine_token.json` 路径全部指向 `tmp_path`（不读开发机真实 Qoder 桌面端数据）。
🔴 判据逐条对应契约（每条给出照抄来源行号）：
  · `login_start`：PKCE/nonce/machine_id 只进 `session.state`；授权 URL 挂 `authBase`（`qoder.ts:109-118`）
  · `login_poll`：404 = pending（`qoder-oauth.ts:138-141`）→ 200 带 token = success（含 userinfo 补昵称）
  · `refresh`：`{refresh_token, machine_id}`；401/403 → `NotRefreshable`；500 → 可重试（`qoder-auth.ts:395-438`）
  · `probe`：连通 / 凭据有效两维分开（§22.3）
  · `quota`：`userQuota`+`addOnQuota` 求和（`qoder-credits.ts:27-29`）；**未知不当零**（`23 B2`）
  · `claim`：`replayed:true` → already_done；**无可领活动 → inactive**（不能报已领，
    `qoder-credits.ts:605-610`）；请求体必须空串（`:58-59`）
  · 串用：`requireQoderFamily` 语义（`jet-hub-rpc.ts:753-757`）+ 凭据区域标记 → 拒绝且**不打上游**
  · `list_models`：恒本地兜底表 17 条（`qoder-product.ts:362-436` 逐条）
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from model_gateway.accounts import store
from model_gateway.accounts.login import LoginEngine
from model_gateway.accounts.types import NotRefreshable
from model_gateway.upstream.qoder import flow
from model_gateway.upstream.qoder import product as qoder
from model_gateway.upstream.qoder.config import (
    FAMILY_KEY,
    QODER,
    QODER_MODELS,
    FamilyMismatchError,
    UnknownQoderFamilyError,
    require_qoder_family,
)

#: 国际版全部端点 host（假上游只应答这一站；CN 用例里出现即视为串用）
HOST = "openapi.qoder.sh"
REFRESH_PATH = "/api/v1/deviceToken/refresh"
POLL_PATH = "/api/v1/deviceToken/poll"
USERINFO_PATH = "/api/v1/userinfo"
USAGE_PATH = "/sash/api/v2/me/usage"
CAMPAIGNS_PATH = "/sash/api/v1/me/campaigns"


# ============ 假上游（httpx.MockTransport）============

class FakeUpstream:
    """按 `(method, path)` 路由的假上游；未登记路径 = 404 NotFound（照抄真实网关行为）。

    记录全部请求（含 headers/body）→ 用例可直接断言「打了哪些上游、没打哪些」。
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.replies: dict[tuple[str, str], tuple[int, Any]] = {}
        self.errors: set[tuple[str, str]] = set()

    def reply(self, method: str, path: str, *, body: Any = None, status: int = 200) -> None:
        self.replies[(method, path)] = (status, body)

    def fail(self, method: str, path: str) -> None:
        """登记传输层故障（httpx.ConnectError）。"""
        self.errors.add((method, path))

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handler)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path)
        if key in self.errors:
            raise httpx.ConnectError("fake network down", request=request)
        status, body = self.replies.get(key, (404, {"errorCode": "NotFound"}))
        return httpx.Response(status, json=body)

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def hosts(self) -> set[str]:
        return {r.url.host for r in self.requests}

    def body_of(self, path: str) -> Any:
        for request in reversed(self.requests):
            if request.url.path == path:
                return json.loads(request.content) if request.content else None
        raise AssertionError(f"没有打到 {path} 的请求：{self.paths()}")

    def headers_of(self, path: str) -> dict:
        for request in reversed(self.requests):
            if request.url.path == path:
                return dict(request.headers)
        raise AssertionError(f"没有打到 {path} 的请求：{self.paths()}")


class _Session:
    """`login_start/login_poll` 的最小会话桩（引擎真实会话的 `state` 语义）。"""

    def __init__(self) -> None:
        self.state: dict = {}


@pytest.fixture(autouse=True)
def _hermetic_env(tmp_path, monkeypatch):
    """测试隔离：账号根 + machine_token 路径都指向 tmp（不依赖开发机装了哪个 Qoder 客户端）。"""
    monkeypatch.setenv("MGW_QODER_ACCOUNTS", str(tmp_path / "accounts"))
    monkeypatch.setenv("QODER_MACHINE_TOKEN_PATH", str(tmp_path / "absent-machine-token.json"))


@pytest.fixture()
def fake(monkeypatch) -> FakeUpstream:
    upstream = FakeUpstream()
    monkeypatch.setattr(flow, "_transport", upstream.transport())
    return upstream


def _cred(**overrides) -> dict:
    """一条合法凭据（形状 = `qoder.ts:144-164` + 本地区域标记）。"""
    cred = {
        "security_oauth_token": "T-1",
        "access_token": "T-1",
        "refresh_token": "R-1",
        "machine_id": "m-1",
        "uid": "u-1",
        "nickname": "小明",
        FAMILY_KEY: "qoder",
    }
    cred.update(overrides)
    return cred


# ============ 登录：start ============

async def test_login_start_builds_auth_url_and_keeps_secrets_in_session(fake):
    """PKCE/nonce/machine_id 是**私有态**（只进 `session.state`）；授权 URL 挂 `authBase`。"""
    session = _Session()
    challenge = await qoder.login_start(session)

    url = urlparse(challenge.url)
    assert url.hostname == "qoder.com" and url.path == "/device/selectAccounts"
    query = parse_qs(url.query)
    assert query["challenge_method"] == ["S256"]
    assert query["client_id"] == [QODER.client_id]              # 国际版 prod id（两站不同）
    assert query["nonce"][0] == session.state["nonce"]
    assert query["machine_id"][0] == session.state["machine_id"]
    # verifier 只用于轮询（私有态）：既不在 URL 里，也不进 Challenge 的其它字段
    assert session.state["pkce_verifier"] not in challenge.url
    assert challenge.device_code == "" and challenge.qr_payload == ""
    # 设备字段形态：uuid4 字符串（§22.2 不变式③ 走 generate_unique）
    assert len(session.state["machine_id"]) == 36
    assert fake.requests == [], "启动登录不应发任何上游请求（qoder-oauth.ts:205-215）"


# ============ 登录：poll ============

async def test_login_poll_pending_on_404_then_success(fake):
    """404 = 用户尚未完成授权 → `pending`（不是错误）；随后 200 带 token → `success`。"""
    session = _Session()
    await qoder.login_start(session)

    fake.reply("GET", POLL_PATH, status=404, body={"errorCode": "NotFound"})
    first = await qoder.login_poll(session)
    assert first.state == "pending" and "等待用户" in first.detail

    fake.reply("GET", POLL_PATH, body={
        "token": "T-9", "refresh_token": "R-9",
        "expires_at": 4102444800000, "user_id": "u-9",
    })
    fake.reply("GET", USERINFO_PATH, body={"name": " 真实昵称 "})
    second = await qoder.login_poll(session)
    assert second.state == "success"

    cred = second.credentials
    assert cred["security_oauth_token"] == cred["access_token"] == "T-9"   # 双写同值
    assert cred["refresh_token"] == "R-9" and cred["refresh_token"]
    assert cred["uid"] == "u-9" and cred["nickname"] == "真实昵称"
    assert cred["expire_time"] == 4102444800000                            # ISO/毫秒解析
    assert cred["machine_id"] == session.state["machine_id"]
    assert cred[FAMILY_KEY] == "qoder"                                     # 本地区域标记
    assert second.meta["machine_id"] == session.state["machine_id"]        # 设备字段 → meta.json

    # 轮询挂 openApiBase 且带 nonce+verifier；不挂 authBase（qoder.ts:120-134）
    poll = [r for r in fake.requests if r.url.path == POLL_PATH][-1]
    query = parse_qs(poll.url.query.decode("ascii"))     # httpx 的 `.query` 是 bytes
    assert query["nonce"][0] == session.state["nonce"]
    assert query["verifier"][0] == session.state["pkce_verifier"]
    assert fake.hosts() == {HOST}


async def test_login_poll_nickname_failure_does_not_fail_login(fake):
    """userinfo 拿不到昵称**不阻塞登录**（`qoder.ts:365-367`；昵称只是展示信息）。"""
    session = _Session()
    await qoder.login_start(session)
    fake.reply("GET", POLL_PATH, body={"token": "T-1", "refresh_token": "R-1"})
    fake.reply("GET", USERINFO_PATH, status=500, body={"error": "boom"})
    outcome = await qoder.login_poll(session)
    assert outcome.state == "success" and "nickname" not in outcome.credentials


async def test_login_poll_5xx_is_failed_and_transport_errors_are_tolerated(fake):
    """服务端 5xx → `failed`（不当"等用户"）；网络抖动 → `pending` 直到第 5 次（`qoder.ts:20`）。"""
    session = _Session()
    await qoder.login_start(session)

    fake.fail("GET", POLL_PATH)
    for expected in range(1, flow.POLL_MAX_FAILURES):
        outcome = await qoder.login_poll(session)
        assert outcome.state == "pending" and f"{expected}/5" in outcome.detail
    last = await qoder.login_poll(session)
    assert last.state == "failed" and "连续 5 次失败" in last.detail

    session2 = _Session()
    await qoder.login_start(session2)
    fake.errors.discard(("GET", POLL_PATH))
    fake.reply("GET", POLL_PATH, status=503, body={"error": "unavailable"})
    assert (await qoder.login_poll(session2)).state == "failed"


async def test_login_callback_is_folded_failure_not_exception(fake):
    """本族非 local_callback 型：回跳粘贴折成 `failed`（可预期失败不抛栈，§22.3）。

    🔴 M6-6 收口（R4 F4/BL-2）：折返**不是**护栏的豁免理由 —— 本钩子未接线，
    已在产品模块的 `_REFUSED_HOOKS` 里登记（理由 + 探针），编造 `success` 会被
    `tests/accounts/test_registry.py::assert_declared_refusal` 判红。
    """
    outcome = await qoder.login_callback(_Session(), {"code": "x"})
    assert outcome.state == "failed" and "不支持回跳粘贴" in outcome.detail
    assert not outcome.credentials and fake.requests == []


def test_wiring_declarations_are_precise_and_registered():
    """🔴 骨架纪律登记面（M6-6 收口 R4 §2.1/BL-2）：`_IMPLEMENTED` 精确到**已接线**的 9 个
    钩子（**不含** `login_callback` —— 它未接线，走 `_REFUSED_HOOKS` 的显式拒绝登记）：
    两份声明缺一个，护栏就无法把「已接线」与「编造 success」分开（修前正是如此）。"""
    assert set(qoder._IMPLEMENTED) == {
        "meta", "login_start", "login_poll", "refresh", "probe", "quota",
        "claim", "list_models", "build_out"}
    assert "login_callback" not in qoder._IMPLEMENTED
    assert set(qoder._REFUSED_HOOKS) == {"login_callback"}
    assert qoder._REFUSED_HOOKS["login_callback"].strip()       # 非空理由（评审要核验）


async def test_login_engine_end_to_end_commits_credentials(tmp_path, fake):
    """经 `LoginEngine` 走完整两步式：success → 认领暂存 →「确定接入」→ `store.commit_login` 落盘。"""
    fake.reply("GET", POLL_PATH, status=404, body={"errorCode": "NotFound"})
    engine = LoginEngine(root=tmp_path / "accounts")
    session = await engine.start("qoder")
    assert (await engine.poll("qoder", session.id)).state == "pending"

    fake.reply("GET", POLL_PATH, body={"token": "T-E2E", "refresh_token": "R-E2E"})
    fake.reply("GET", USERINFO_PATH, body={"name": "E2E 昵称"})
    outcome = await engine.poll("qoder", session.id)
    assert outcome.state == "success"
    assert not store.has_account(tmp_path / "accounts", session.name), \
        "success 只暂存（M7-E 两阶段提交）"
    assert (await engine.commit_pending(session.id))["committed"] is True
    assert store.load_credentials("qoder", session.name, root=tmp_path / "accounts")["access_token"] == "T-E2E"
    meta = store.load_meta(tmp_path / "accounts", session.name)
    assert meta["machine_id"] and meta["nickname"] == "E2E 昵称"


# ============ 续期（qoder-auth.ts:395-438）============

async def test_refresh_rotates_tokens_and_keeps_device_fields(fake):
    """续期载荷 = `{refresh_token, machine_id}`；响应未带的 `uid/nickname` 必须保留。"""
    fake.reply("POST", REFRESH_PATH, body={
        "device_token": "T-2", "refresh_token": "R-2", "expires_at": 4102444800000,
    })
    new = await qoder.refresh(_cred(), {"machine_id": "m-1"})

    assert new["security_oauth_token"] == new["access_token"] == "T-2"
    assert new["refresh_token"] == "R-2"
    assert new["machine_id"] == "m-1" and new["uid"] == "u-1" and new["nickname"] == "小明"
    assert new[FAMILY_KEY] == "qoder"

    request = fake.requests[-1]
    assert request.url.host == HOST and request.url.path == REFRESH_PATH
    assert fake.body_of(REFRESH_PATH) == {"refresh_token": "R-1", "machine_id": "m-1"}
    headers = fake.headers_of(REFRESH_PATH)
    assert headers["user-agent"] == "qoder/1.0.0" and "application/json" in headers["content-type"]


async def test_refresh_keeps_old_refresh_token_when_response_omits_it(fake):
    """响应不带新 refresh_token 时沿用旧的（避免把可续期凭据变成不可续期，`qoder.ts:332-335`）。"""
    fake.reply("POST", REFRESH_PATH, body={"device_token": "T-3"})
    new = await qoder.refresh(_cred(), {})
    assert new["refresh_token"] == "R-1" and new["access_token"] == "T-3"


async def test_refresh_terminal_vs_retryable(fake):
    """401/403/缺 token → `NotRefreshable`（终态）；5xx → 普通异常（可重试，不判终态）。"""
    fake.reply("POST", REFRESH_PATH, status=401, body={"error": "invalid_grant"})
    with pytest.raises(NotRefreshable, match="请重新登录"):
        await qoder.refresh(_cred(), {})

    fake.reply("POST", REFRESH_PATH, status=503, body={"error": "unavailable"})
    with pytest.raises(RuntimeError) as err:
        await qoder.refresh(_cred(), {})
    assert not isinstance(err.value, NotRefreshable), "5xx 不得判终态（qoder-auth.ts:408-412）"

    fake.reply("POST", REFRESH_PATH, body={"replayed": True})     # 200 但没有 token
    with pytest.raises(NotRefreshable, match="缺少访问令牌"):
        await qoder.refresh(_cred(), {})


async def test_refresh_without_refresh_token_or_machine_id_fails_closed(fake):
    """缺 `refresh_token` / 缺 `machine_id` → `NotRefreshable`，且**零上游请求**。"""
    with pytest.raises(NotRefreshable, match="refresh_token"):
        await qoder.refresh(_cred(refresh_token=""), {})
    with pytest.raises(NotRefreshable, match="machine_id"):
        await qoder.refresh(_cred(machine_id=""), {})
    assert fake.requests == []


async def test_refresh_transport_error_is_retryable(fake):
    """网络失败不是终态（`qoder-auth.ts:408-412`：网络抖动不该让用户重新登录）。"""
    fake.fail("POST", REFRESH_PATH)
    with pytest.raises(RuntimeError) as err:
        await qoder.refresh(_cred(), {})
    assert not isinstance(err.value, NotRefreshable) and "网络失败" in str(err.value)


# ============ 探活 ============

async def test_probe_two_dimensions(fake):
    """连通 / 凭据有效分开：200 通过；401 是「可达但凭据失效」；网络故障只影响可达性。"""
    fake.reply("GET", USERINFO_PATH, body={"name": "n"})
    result = await qoder.probe(_cred(), {})
    assert result.ok and result.reachable and result.valid

    fake.reply("GET", USERINFO_PATH, status=401, body={"code": "TOKEN_INVALID"})
    result = await qoder.probe(_cred(), {})
    assert result.reachable and not result.valid and not result.ok

    fake.fail("GET", USERINFO_PATH)
    result = await qoder.probe(_cred(), {})
    assert not result.reachable and not result.valid and "网络不可达" in result.detail


async def test_probe_without_token_fails_closed(fake):
    result = await qoder.probe({"family": "qoder"}, {})
    assert not result.ok and "缺访问令牌" in result.detail
    assert fake.requests == []


# ============ 额度 ============

async def test_quota_sums_all_layers_with_sash_headers(fake):
    """余额 = `userQuota` + `addOnQuota`（只读前者会漏掉"资源包 100"，`qoder-credits.ts:27-29`）。"""
    fake.reply("GET", USAGE_PATH, body={
        "displayMode": "qoder",
        "qoderUsage": {
            "userType": "personal_standard",
            "userQuota": {"total": 0, "used": 0, "remaining": 0, "unit": "credits"},
            "addOnQuota": {"total": 100, "used": 0, "remaining": 100, "unit": "credits"},
        },
    })
    snapshot = await qoder.quota(_cred(), {})
    assert snapshot.state == "available"
    assert snapshot.source == "qoder-usage" and "100 credits" in snapshot.detail

    headers = fake.headers_of(USAGE_PATH)
    assert headers["authorization"] == "Bearer T-1"
    assert headers["cosy-clienttype"] == "10"      # 桌面 app 身份（缺了服务端不下发活动）
    assert headers["user-agent"] == "Qoder"
    assert "cosy-machinetoken" not in headers      # 本机没有 machine_token → 保守降级


async def test_quota_machine_headers_attached_when_file_present(tmp_path, fake, monkeypatch):
    """读得到 `machine_token.json` → 两个 machine 头**成对**附加（缺一即无效，`qoder-machine.ts:28-40`）。"""
    token_file = tmp_path / "machine_token.json"
    token_file.write_text(json.dumps({"token": "MT-1", "type": "TYPE-1"}), encoding="utf-8")
    monkeypatch.setenv("QODER_MACHINE_TOKEN_PATH", str(token_file))
    fake.reply("GET", USAGE_PATH, body={"qoderUsage": {"addOnQuota": {"remaining": 5, "unit": "credits"}}})
    assert (await qoder.quota(_cred(), {})).state == "available"
    headers = fake.headers_of(USAGE_PATH)
    assert headers["cosy-machinetoken"] == "MT-1" and headers["cosy-machinetype"] == "TYPE-1"


async def test_quota_unknown_never_zero(fake):
    """三态判据（`23 B2`）：非 2xx / 企业版 / 形状非法 → `unknown`；真的为 0 → `exhausted`。"""
    fake.reply("GET", USAGE_PATH, status=500, body={"error": "boom"})
    assert (await qoder.quota(_cred(), {})).state == "unknown"

    fake.reply("GET", USAGE_PATH, body={"displayMode": "enterprise"})
    assert (await qoder.quota(_cred(), {})).state == "unknown"

    fake.reply("GET", USAGE_PATH, body={"displayMode": "qoder"})
    assert (await qoder.quota(_cred(), {})).state == "unknown"

    fake.reply("GET", USAGE_PATH, body={"qoderUsage": {"userQuota": {"total": 10, "used": 10}}})
    snapshot = await qoder.quota(_cred(), {})
    assert snapshot.state == "exhausted" and snapshot.detail.startswith("余额 0")

    fake.fail("GET", USAGE_PATH)
    assert (await qoder.quota(_cred(), {})).state == "unknown"


async def test_quota_requires_token(fake):
    assert (await qoder.quota({"family": "qoder"}, {})).state == "unknown"
    assert fake.requests == []


# ============ 每日领取 ============

def _campaigns(*items: dict) -> dict:
    return {"showCampaign": True, "claimable": True, "campaigns": list(items)}


def _claimable(cid: str, amount: float = 100) -> dict:
    return {"campaignId": cid, "campaignKey": "act-1", "actionType": "CLAIM_BENEFIT",
            "claimStatus": "CLAIMABLE", "benefit": {"kind": "CREDITS", "amount": amount}}


async def test_claim_success_posts_empty_body_and_reports_amount(fake):
    """领取成功：请求体必须空串（`qoder-credits.ts:58-59`）；金额取 `benefit.amount`。"""
    fake.reply("GET", CAMPAIGNS_PATH, body=_campaigns(_claimable("c-1")))
    fake.reply("POST", f"{CAMPAIGNS_PATH}/c-1/claim", body={
        "grantId": "g-1", "status": "CLAIMED", "replayed": False,
        "benefit": {"kind": "CREDITS", "amount": 100},
    })
    outcome = await qoder.claim(_cred(), {}, precheck=False)
    assert outcome.category == "success" and "100" in outcome.detail

    claim_request = [r for r in fake.requests if r.url.path.endswith("/claim")][-1]
    assert claim_request.url.path == f"{CAMPAIGNS_PATH}/c-1/claim"
    assert claim_request.content == b""                    # 空串，不是 "{}"
    assert fake.headers_of(f"{CAMPAIGNS_PATH}/c-1/claim")["cosy-clienttype"] == "10"


async def test_claim_replayed_true_is_already_done(fake):
    """🔴 幂等判据是响应体 `replayed:true`（重复领取同样 HTTP 200，`qoder-credits.ts:53-57`）。"""
    fake.reply("GET", CAMPAIGNS_PATH, body=_campaigns(_claimable("c-1")))
    fake.reply("POST", f"{CAMPAIGNS_PATH}/c-1/claim", body={
        "status": "CLAIMED", "replayed": True, "campaignId": "c-1", "claimedAt": "2026-09-18T00:00:00Z",
    })
    outcome = await qoder.claim(_cred(), {}, precheck=False)
    assert outcome.category == "already_done" and "已领取" in outcome.detail


async def test_claim_no_claimable_is_inactive_not_already_claimed(fake):
    """🔴 **「无可领活动」必须 `inactive`**（`qoder-credits.ts:605-610`：误报已领是真实缺陷）。"""
    fake.reply("GET", CAMPAIGNS_PATH, body=_campaigns(
        {"campaignId": "c-v", "actionType": "VIEW_DETAILS", "claimStatus": "CLAIMABLE"}))
    fake.reply("GET", USAGE_PATH, body={"qoderUsage": {"addOnQuota": {"total": 100, "remaining": 100}}})
    outcome = await qoder.claim(_cred(), {}, precheck=False)
    assert outcome.category == "inactive" and "没有可领取的活动" in outcome.detail
    assert not any(r.url.path.endswith("/claim") for r in fake.requests)


async def test_claim_not_activated_reports_inactive_with_actionable_hint(fake):
    """未开通（无 `CLAIM_BENEFIT` + 用量缺 `addOnQuota` 字段）→ `inactive` + 可操作提示。"""
    fake.reply("GET", CAMPAIGNS_PATH, body={"showCampaign": False, "claimable": False, "campaigns": []})
    fake.reply("GET", USAGE_PATH, body={"qoderUsage": {"userQuota": {"total": 0, "remaining": 0}}})
    outcome = await qoder.claim(_cred(), {}, precheck=False)
    assert outcome.category == "inactive" and "官方客户端" in outcome.detail


async def test_claim_already_claimed_campaign_is_already_done(fake):
    """有「已领」的领分类活动且当前无可领 → `already_done`（`qoder-credits.ts:623-632`）。"""
    fake.reply("GET", CAMPAIGNS_PATH, body=_campaigns(
        {"campaignId": "c-1", "actionType": "CLAIM_BENEFIT", "claimStatus": "CLAIMED",
         "benefit": {"amount": 100}}))
    outcome = await qoder.claim(_cred(), {}, precheck=False)
    assert outcome.category == "already_done"


async def test_claim_precheck_skips_claim_request_when_already_claimed(fake):
    """`precheck=True`：已领 → 直接 `already_done`，**不发 claim 请求**（先查可省一次无效领取）。"""
    fake.reply("GET", CAMPAIGNS_PATH, body=_campaigns(
        {"campaignId": "c-1", "actionType": "CLAIM_BENEFIT", "claimStatus": "CLAIMED"}))
    outcome = await qoder.claim(_cred(), {}, precheck=True)
    assert outcome.category == "already_done"
    assert not any(r.url.path.endswith("/claim") for r in fake.requests)


async def test_claim_precheck_reuses_single_campaigns_get(fake):
    """`precheck=True` 且确有可领 → 直接领取，**活动列表只查一次**（不重复 GET）。"""
    fake.reply("GET", CAMPAIGNS_PATH, body=_campaigns(_claimable("c-1")))
    fake.reply("POST", f"{CAMPAIGNS_PATH}/c-1/claim",
               body={"status": "CLAIMED", "replayed": False, "benefit": {"amount": 100}})
    outcome = await qoder.claim(_cred(), {}, precheck=True)
    assert outcome.category == "success"
    assert fake.paths().count(CAMPAIGNS_PATH) == 1, f"重复查询了活动列表：{fake.paths()}"


async def test_claim_multiple_campaigns_and_partial_failure(fake):
    """多个可领活动逐个领取（顺序执行）；有成功即 `success`，失败数写进 detail。"""
    fake.reply("GET", CAMPAIGNS_PATH, body=_campaigns(_claimable("c-1", 100), _claimable("c-2", 20)))
    fake.reply("POST", f"{CAMPAIGNS_PATH}/c-1/claim",
               body={"status": "CLAIMED", "replayed": False, "benefit": {"amount": 100}})
    fake.reply("POST", f"{CAMPAIGNS_PATH}/c-2/claim", status=500, body={"error": "boom"})
    outcome = await qoder.claim(_cred(), {}, precheck=False)
    assert outcome.category == "success" and "100" in outcome.detail and "失败" in outcome.detail


async def test_claim_all_failed_reports_failed(fake):
    """全部失败 → `failed`（唯一需要用户关注的类别）。"""
    fake.reply("GET", CAMPAIGNS_PATH, body=_campaigns(_claimable("c-1")))
    fake.reply("POST", f"{CAMPAIGNS_PATH}/c-1/claim", status=500, body={"error": "boom"})
    outcome = await qoder.claim(_cred(), {}, precheck=False)
    assert outcome.category == "failed" and "HTTP 500" in outcome.detail


async def test_claim_campaign_list_failure_is_failed(fake):
    """活动列表查不到 → `failed`（**不猜**「没活动」，`qoder-credits.ts:617-620`）。"""
    fake.fail("GET", CAMPAIGNS_PATH)
    outcome = await qoder.claim(_cred(), {}, precheck=True)
    assert outcome.category == "failed" and "活动列表查询失败" in outcome.detail


# ============ 防串用（requireQoderFamily 语义）============

async def test_require_qoder_family_and_mismatch_guard(fake):
    """两站是**两个实例**：未知 id 拒绝；国际版钩子拿到中国版凭据 → 拒绝且零上游请求。"""
    assert require_qoder_family("qoder") is QODER
    assert require_qoder_family("qodercn").open_api_base.endswith("qoder.com.cn")
    with pytest.raises(UnknownQoderFamilyError, match="Unknown Qoder family provider"):
        require_qoder_family("trae")

    with pytest.raises(FamilyMismatchError, match="两站 token 不通用"):
        await qoder.refresh(_cred(**{FAMILY_KEY: "qodercn"}), {})
    with pytest.raises(FamilyMismatchError):
        await qoder.probe(_cred(**{FAMILY_KEY: "qodercn"}), {})
    with pytest.raises(FamilyMismatchError):
        await qoder.quota(_cred(**{FAMILY_KEY: "qodercn"}), {})
    with pytest.raises(FamilyMismatchError):
        await qoder.claim(_cred(**{FAMILY_KEY: "qodercn"}), {}, precheck=True)
    assert fake.requests == [], "串用必须在**发请求之前**被拦住"


async def test_unmarked_legacy_credentials_still_work(fake):
    """无标记（DSH 侧导入的旧凭据）不拦 —— 保持导入可用性（标记只由本层写入）。"""
    fake.reply("GET", USAGE_PATH, body={"qoderUsage": {"userQuota": {"remaining": 1}}})
    cred = _cred()
    cred.pop(FAMILY_KEY)
    assert (await qoder.quota(cred, {})).state == "available"


# ============ 模型目录（恒本地兜底表）============

async def test_list_models_returns_static_table_with_verified_fields(fake):
    """17 条逐条照抄 `qoder-product.ts:362-436`；**零网络**；字段语义逐条可证。"""
    models = await qoder.list_models({}, {})
    assert fake.requests == [], "模型目录恒本地兜底表：不得发任何请求（21 §1.1）"
    assert [m.id for m in models] == [m.id for m in QODER_MODELS]
    assert len(models) == 17
    assert models[0].id == "auto" and models[-1].id == "mmodel"

    by_id = {m.id: m for m in models}
    # 档位表最大档 = 1M（不是 max_input_tokens）；`auto` 无档位表 → 200K
    assert by_id["qfmodel"].context_window == 1_000_000
    assert by_id["auto"].context_window == 200_000
    # supportsDisable 追加 none（「关闭思考」，qoder-adapter.ts:152-156）
    assert by_id["qfmodel"].effort_levels == ("xhigh", "low", "medium", "none")
    assert by_id["qmodel_latest"].effort_levels == ("none",)
    assert by_id["qmodel_latest"].reasoning is True
    # smodel/cmodel 有档位但无 disabled 分支 → 不能关闭思考
    assert "none" not in by_id["smodel"].effort_levels
    # auto 无档位、不能关闭 → 不声明 reasoning（UI 显示「未提供推理等级」）
    assert by_id["auto"].effort_levels == () and by_id["auto"].reasoning is False
    # 未取到 / 不编造：DSH 不播报工具支持、兜底表无 max output
    assert by_id["auto"].tool_call is None and by_id["auto"].max_output is None
    assert all(m.tool_call is None and m.max_output is None for m in models)
    assert all(m.vendor == "" for m in models)     # DSH 兜底表无厂商字段 → 不编造


async def test_hooks_table_is_complete(fake):
    """契约表齐全（§22.3）。"""
    assert set(qoder._HOOKS) == {
        "meta", "login_start", "login_poll", "login_callback", "refresh",
        "probe", "quota", "claim", "list_models", "build_out"}
    assert qoder._HOOKS["build_out"] is qoder.build_out


async def test_build_out_is_wired_to_the_qoder_envelope_adapter(fake):
    """`build_out` 自 **M6-5c** 起接线（原「M6-5 TODO」护栏按波次转正）：

    返回 `QoderOut`（**区域配置显式注入**：本模块 = `QODER`，qodercn 注入它自己的）——
    两站 token/端点不通用，这里不存任何默认区域（`20 §4.1`）。行为判据（信封解包/
    签名缝 fail-closed）在 `tests/integration/test_qoder_out.py`；本用例只钉接线成立。
    """
    from model_gateway.accounts import registry as account_registry
    from model_gateway.adapters.product_out import ProductAccount
    from model_gateway.upstream.qoder.out import QoderOut

    account = ProductAccount(product=qoder.PRODUCT, name="acc-q1",
                             base_url=account_registry.get("qoder").base_url)
    adapter = qoder.build_out(account)
    assert isinstance(adapter, QoderOut)
    assert (adapter.product, adapter.account_ref) == ("qoder", "acc-q1")
    await adapter.aclose()
