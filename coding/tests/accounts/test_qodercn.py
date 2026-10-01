"""`qodercn` 产品钩子单测（M6-2 批 A；tech-design §22.4 + `20 §1.1/§4.1`）。

本文件专测**与 qoder 的差异面**（复用同一实现，差异 = 区域常量 + 防串用）：
  · 区域参数必须显式：授权页/轮询/续期全部挂 **CN 域名与 CN client_id**（`qoder-product.ts:592-612`）
  · **两站 token 不通用**：CN 钩子拿到国际版凭据 → 拒绝且零上游（`20 §4.1` 串用注释）
  · CN 兜底目录 14 条（`qoder-product.ts:480-581`）：**不含**国际版独有模型，含 CN 独有两条
  · 额度/领取语义同国际版契约（同一实现 → 只做通路径验证，语义细节见 `test_qoder.py`）

🔴 无网络、无真实凭据（`httpx.MockTransport` + tmp 账号根）。
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from model_gateway.accounts import registry, store
from model_gateway.accounts.login import LoginEngine
from model_gateway.accounts.types import NotRefreshable
from model_gateway.upstream.qoder import flow
from model_gateway.upstream.qodercn import product as qodercn
from model_gateway.upstream.qoder.config import (
    FAMILY_KEY,
    QODER,
    QODER_CN,
    QODER_CN_MODELS,
    QODER_MODELS,
    FamilyMismatchError,
    require_qoder_family,
)

#: 中国版全部端点 host（假上游只应答这一站；国际版 host 出现即视为串用）
HOST = "openapi.qoder.com.cn"
INTL_HOST = "openapi.qoder.sh"
POLL_PATH = "/api/v1/deviceToken/poll"
REFRESH_PATH = "/api/v1/deviceToken/refresh"
USERINFO_PATH = "/api/v1/userinfo"
USAGE_PATH = "/sash/api/v2/me/usage"
CAMPAIGNS_PATH = "/sash/api/v1/me/campaigns"


class FakeUpstream:
    """按 `(method, path)` 路由的假上游；未登记路径 = 404（照抄真实网关行为）。"""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.replies: dict[tuple[str, str], tuple[int, Any]] = {}

    def reply(self, method: str, path: str, *, body: Any = None, status: int = 200) -> None:
        self.replies[(method, path)] = (status, body)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handler)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, body = self.replies.get((request.method, request.url.path),
                                        (404, {"errorCode": "NotFound"}))
        return httpx.Response(status, json=body)

    def hosts(self) -> set[str]:
        return {r.url.host for r in self.requests}

    def body_of(self, path: str) -> Any:
        for request in reversed(self.requests):
            if request.url.path == path:
                return json.loads(request.content) if request.content else None
        raise AssertionError(f"没有打到 {path} 的请求")


class _Session:
    def __init__(self) -> None:
        self.state: dict = {}


@pytest.fixture(autouse=True)
def _hermetic_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MGW_QODERCN_ACCOUNTS", str(tmp_path / "accounts"))
    monkeypatch.setenv("QODER_MACHINE_TOKEN_PATH", str(tmp_path / "absent-machine-token.json"))


@pytest.fixture()
def fake(monkeypatch) -> FakeUpstream:
    upstream = FakeUpstream()
    monkeypatch.setattr(flow, "_transport", upstream.transport())
    return upstream


def _cred(**overrides) -> dict:
    cred = {
        "security_oauth_token": "CN-T-1",
        "access_token": "CN-T-1",
        "refresh_token": "CN-R-1",
        "machine_id": "cn-m-1",
        "uid": "cn-u-1",
        FAMILY_KEY: "qodercn",
    }
    cred.update(overrides)
    return cred


# ============ 注册表与区域接线 ============

def test_registry_row_and_module_wired_to_cn_config():
    """注册表行（base_url 取证回填）+ 模块必须接**CN** 配置（不是国际版的拷贝粘贴）。"""
    meta = registry.get("qodercn")
    assert meta.id == "qodercn" and meta.title == "Qoder（中国版）"
    assert meta.login == "device_code" and meta.protocol == "custom"
    assert meta.base_url == "https://gateway.qoder.com.cn"        # qoder-product.ts:604
    assert meta.device.fields == ("machine_id",) and meta.capabilities.refresh
    assert qodercn._CONFIG is QODER_CN and qodercn.meta() == meta
    assert qodercn._CONFIG is not QODER
    assert set(qodercn._HOOKS) == {
        "meta", "login_start", "login_poll", "login_callback", "refresh",
        "probe", "quota", "claim", "list_models", "build_out"}


def test_wiring_declarations_are_precise_and_registered():
    """🔴 骨架纪律登记面（M6-6 收口 R4 §2.1/BL-2）：`_IMPLEMENTED` 精确到**已接线**的 9 个
    钩子（**不含** `login_callback` —— 它未接线，走 `_REFUSED_HOOKS` 的显式拒绝登记）：
    两份声明缺一个，护栏就无法把「已接线」与「编造 success」分开（修前正是如此：
    护栏整体让位 → 编造 success 时 483 用例全绿）。"""
    assert set(qodercn._IMPLEMENTED) == {
        "meta", "login_start", "login_poll", "refresh", "probe", "quota",
        "claim", "list_models", "build_out"}
    assert "login_callback" not in qodercn._IMPLEMENTED
    assert set(qodercn._REFUSED_HOOKS) == {"login_callback"}
    assert qodercn._REFUSED_HOOKS["login_callback"].strip()     # 非空理由（评审要核验）


async def test_login_callback_is_a_declared_refusal(fake):
    """本族非 local_callback 型：回跳粘贴折成 `failed`（显式拒绝，不抛栈、零上游）。

    🔴 M6-6 收口（R4 F4/BL-2）：折返**不是**护栏的豁免理由 —— 本钩子未接线，已在
    `_REFUSED_HOOKS` 登记（理由 + 探针）；编造 `success` 会被
    `tests/accounts/test_registry.py::assert_declared_refusal` 判红。
    """
    outcome = await qodercn.login_callback(_Session(), {"code": "x"})
    assert outcome.state == "failed" and "不支持回跳粘贴" in outcome.detail
    assert not outcome.credentials and fake.requests == []


def test_require_qoder_family_separates_two_regions():
    """`require_qoder_family` 是**取实例**的唯一入口（DSH `requireQoderFamily`，`:753-757`）。"""
    assert require_qoder_family("qodercn") is QODER_CN
    assert QODER_CN.client_id != QODER.client_id                   # 两站 client_id 不同
    assert QODER_CN.auth_base != QODER.auth_base
    assert QODER_CN.open_api_base != QODER.open_api_base
    assert QODER_CN.encrypted_infer_base != QODER.encrypted_infer_base


# ============ 登录（CN 域名 / CN client_id）============

async def test_login_start_uses_cn_domains_and_client_id(fake):
    """授权页必须挂 `qoder.cn` 且带 **CN** 的 client_id（用错 id 的症状见 `qoder-product.ts:606-608`）。"""
    session = _Session()
    challenge = await qodercn.login_start(session)

    url = urlparse(challenge.url)
    assert url.hostname == "qoder.cn" and url.path == "/device/selectAccounts"
    query = parse_qs(url.query)
    assert query["client_id"] == [QODER_CN.client_id]
    assert query["machine_id"][0] == session.state["machine_id"]
    assert fake.requests == []


async def test_login_poll_and_credentials_carry_cn_family(fake):
    """轮询挂 CN 的 openApiBase；凭据区域标记 = `qodercn`（防串用的写入侧）。"""
    session = _Session()
    await qodercn.login_start(session)
    fake.reply("GET", POLL_PATH, status=404, body={"errorCode": "NotFound"})
    assert (await qodercn.login_poll(session)).state == "pending"

    fake.reply("GET", POLL_PATH, body={"token": "CN-T-9", "refresh_token": "CN-R-9", "user_id": "cn-u-9"})
    fake.reply("GET", USERINFO_PATH, body={"name": "CN 昵称"})
    outcome = await qodercn.login_poll(session)
    assert outcome.state == "success"
    assert outcome.credentials["access_token"] == "CN-T-9"
    assert outcome.credentials[FAMILY_KEY] == "qodercn"
    assert outcome.credentials["nickname"] == "CN 昵称"
    assert outcome.meta["machine_id"] == session.state["machine_id"]
    assert fake.hosts() == {HOST}, f"登录流程只能打 CN 站，实际：{fake.hosts()}"


async def test_login_engine_end_to_end_commits_cn_account(tmp_path, fake):
    """经 `LoginEngine`：CN 登录成功（暂存）→「确定接入」→ 凭据落 CN 账号目录。"""
    fake.reply("GET", POLL_PATH, body={"token": "CN-E2E", "refresh_token": "CN-R"})
    fake.reply("GET", USERINFO_PATH, body={"name": "n"})
    engine = LoginEngine(root=tmp_path / "accounts")
    session = await engine.start("qodercn")
    outcome = await engine.poll("qodercn", session.id)
    assert outcome.state == "success"
    assert not store.has_account(tmp_path / "accounts", session.name), \
        "success 只暂存（M7-E 两阶段提交）"
    assert (await engine.commit_pending(session.id))["committed"] is True
    saved = store.load_credentials("qodercn", session.name, root=tmp_path / "accounts")
    assert saved["access_token"] == "CN-E2E" and saved[FAMILY_KEY] == "qodercn"


# ============ 续期（CN 端点；绝不走国际版）============

async def test_refresh_hits_cn_endpoint_only(fake):
    """🔴 续期只打 CN 的 `openApiBase`（`20 §4.1`：不许图省事写 qoder 的刷新逻辑）。"""
    fake.reply("POST", REFRESH_PATH, body={"device_token": "CN-T-2", "refresh_token": "CN-R-2"})
    new = await qodercn.refresh(_cred(), {"machine_id": "cn-m-1"})
    assert new["access_token"] == "CN-T-2" and new["refresh_token"] == "CN-R-2"
    assert new[FAMILY_KEY] == "qodercn" and new["machine_id"] == "cn-m-1"
    assert fake.hosts() == {HOST}
    assert INTL_HOST not in fake.hosts()
    assert fake.body_of(REFRESH_PATH) == {"refresh_token": "CN-R-1", "machine_id": "cn-m-1"}


async def test_cn_hook_refuses_intl_credentials_without_upstream_call(fake):
    """🔴 **两站串用被拒**：CN 钩子拿到 `family="qoder"` 的凭据 → `FamilyMismatchError`，零上游。"""
    with pytest.raises(FamilyMismatchError, match="两站 token 不通用"):
        await qodercn.refresh(_cred(**{FAMILY_KEY: "qoder"}), {})
    with pytest.raises(FamilyMismatchError):
        await qodercn.probe(_cred(**{FAMILY_KEY: "qoder"}), {})
    with pytest.raises(FamilyMismatchError):
        await qodercn.quota(_cred(**{FAMILY_KEY: "qoder"}), {})
    with pytest.raises(FamilyMismatchError):
        await qodercn.claim(_cred(**{FAMILY_KEY: "qoder"}), {}, precheck=False)
    assert fake.requests == [], "串用必须在**发请求之前**被拦住"

    # 反向也成立：国际版钩子拒绝 CN 凭据（test_qoder.py 已断言，这里只锁 CN 侧）
    with pytest.raises(NotRefreshable, match="refresh_token"):
        await qodercn.refresh(_cred(refresh_token=""), {})


# ============ 额度 / 领取（CN 通路径，语义同国际版契约）============

async def test_quota_on_cn_endpoint(fake):
    fake.reply("GET", USAGE_PATH, body={
        "qoderUsage": {"addOnQuota": {"total": 100, "used": 0, "remaining": 100, "unit": "credits"}}})
    snapshot = await qodercn.quota(_cred(), {})
    assert snapshot.state == "available" and snapshot.source == "qodercn-usage"
    assert fake.hosts() == {HOST}


async def test_claim_replayed_on_cn_is_already_done(fake):
    """CN 领取同样以**响应体 `replayed:true`** 判幂等（两站协议同形，`credits-capabilities.js:85`）。"""
    fake.reply("GET", CAMPAIGNS_PATH, body={"showCampaign": True, "claimable": True, "campaigns": [
        {"campaignId": "cn-c-1", "actionType": "CLAIM_BENEFIT", "claimStatus": "CLAIMABLE",
         "benefit": {"amount": 100}}]})
    fake.reply("POST", f"{CAMPAIGNS_PATH}/cn-c-1/claim", body={"status": "CLAIMED", "replayed": True})
    outcome = await qodercn.claim(_cred(), {}, precheck=False)
    assert outcome.category == "already_done"
    assert fake.hosts() == {HOST}


# ============ CN 兜底目录（14 条）============

async def test_cn_model_table_differs_from_intl(fake):
    """CN 表 14 条：含 CN 独有两条、不含国际版独有五条；`mmodel` 是 M2.7 且 200K 档。"""
    models = await qodercn.list_models({}, {})
    assert fake.requests == [], "恒本地兜底表：零网络"
    ids = [m.id for m in models]
    assert ids == [m.id for m in QODER_CN_MODELS]
    assert len(models) == 14

    # CN 独有（国际版目录无这两条 key）
    assert "q37fmodel" in ids and "gm51model" in ids
    # 国际版独有（CN 端点根本不认）→ 不得出现在 CN 表
    assert not {"ultimate", "performance", "efficient", "smodel", "cmodel"} & set(ids)

    by_id = {m.id: m for m in models}
    assert by_id["mmodel"].name == "MiniMax-M2.7" and by_id["mmodel"].context_window == 200_000
    assert by_id["mmodel"].image_input is False     # CN 的 mmodel 未声明 is_vl（qoder-product.ts:577）
    assert all(m.tool_call is None and m.max_output is None for m in models)

    # 两张表确有实质差异（不是同一份拷贝）：
    # ① 同 id 的默认档不同（`qmodel_38max`：国际 xhigh / CN medium，qoder-product.ts:402 vs :535）
    # ② 同 id 的版本与档位表不同（`mmodel`：国际 MiniMax-M3 1M / CN MiniMax-M2.7 200K，:435 vs :580）
    intl_by_id = {m.id: m for m in QODER_MODELS}
    cn_by_id = {m.id: m for m in QODER_CN_MODELS}
    assert intl_by_id["qmodel_38max"].default_effort == "xhigh"
    assert cn_by_id["qmodel_38max"].default_effort == "medium"
    assert intl_by_id["mmodel"].name == "MiniMax-M3"
    assert intl_by_id["mmodel"].context_window == 1_000_000
    assert cn_by_id["mmodel"].name == "MiniMax-M2.7"
    assert cn_by_id["mmodel"].context_window == 200_000
