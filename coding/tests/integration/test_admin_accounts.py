"""INT 账号管理 API（tech-design v2.0 §22.7；M6-4a）。

判据逐条对应 §22.7 的 API 契约与 §22.6 的口径：

- 视图形状（产品元信息 / 账号列表含停用 / 设备字段 / 运行态摘要 / 额度缓存摘要）；
- 能力矩阵（前端按钮数据驱动，与 registry 同源）；
- 登录会话四端点：start→poll 成功**落盘**、callback 校验失败、alt 短信两段（**第二段落盘**，
  W3-fix 的引擎缺口在此端到端钉死）；
- 单账号操作：claim 四类（**复用 ops 出口**：停用跳过、报告落 `ops-results-*.jsonl`）、
  refresh（成功落盘 / `NotRefreshable` → 409 / 空返回值不覆盖 / 落盘失败 500）、
  probe（**假上游**：`net.make_client` + `httpx.MockTransport` 打真实产品代码）；
- enable / disable（写 meta `enabled` 位）/ delete（必须 `?confirm=1`）；
- import 的接受与拒绝分支（同名重复 / 设备身份冲突 = 交用户决策 / reuse、regenerate）；
- **响应 JSON 不含凭据**（每个用例都断言，另有专门扫尾用例）。

假上游：登录/callback/claim/refresh 经产品契约表 `_HOOKS` / `_ALT_HOOKS` 注入假钩子；
probe 走**真实产品代码** + `net.make_client` 桩（MockTransport，无网络）。
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import httpx
import pytest
import yaml

from model_gateway.accounts import login, store
from model_gateway.accounts import net as accounts_net
from model_gateway.accounts import registry as account_registry
from model_gateway.accounts.types import (
    Challenge,
    ClaimOutcome,
    LoginOutcome,
    NotRefreshable,
    ProbeResult,
    QuotaSnapshot,
)
from model_gateway.upstream.buddy import product as buddy
from model_gateway.upstream.loomy import product as loomy
from model_gateway.upstream.trae import product as trae
from tests.integration.conftest import chat_res, gateway_config

#: 全用例共用的"凭据不落 HTTP"探针值（出现在所有假凭据里，逐个响应对它断言）
SECRET = "SECRET-TOKEN-DO-NOT-LEAK-9f3a"

#: 接入密钥（管理端免鉴权，仅 gateway 段完整性所需）
TOKENS = {"access_tokens": [{"id": "t-user", "value": "gw-user"}]}


@pytest.fixture(autouse=True)
def _clean_shared_login_sessions():
    """共享登录引擎的会话表是**进程级**状态：用例之间必须互不留痕（TTL 600s）。"""
    yield
    login.shutdown_login()


def _cfg(port: int, *, extra_resources: list[dict] | None = None) -> dict:
    """最小网关配置（资源指向 FakeVendor；账号侧数据经 `store.product_root` 落在 tmp）。"""
    cfg = gateway_config(port, models=[chat_res("A")], gateway=TOKENS)
    cfg["resources"].extend(extra_resources or [])
    return cfg


def _seed(product: str, name: str, credentials: dict, meta: dict | None = None) -> None:
    """造一个账号（走生产同一条落盘入口 `store.commit_login`）。"""
    store.commit_login(product, name, credentials, meta or {})


def _meta_of(product: str, name: str) -> dict:
    return store.load_meta(store.product_root(product), name)


async def _post(client, gw, path: str, body: dict | None = None) -> httpx.Response:
    return await client.post(f"{gw.base_url}{path}", json=body if body is not None else {})


async def _view(client, gw) -> dict:
    resp = await client.get(f"{gw.base_url}/admin/api/accounts")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _product_of(view: dict, pid: str) -> dict:
    return next(p for p in view["products"] if p["id"] == pid)


# ============ 视图 / 能力矩阵 ============

class TestAccountsView:
    async def test_view_shape_counts_and_no_credentials(self, vendor, make_gateway, client):
        """视图形状：10 产品全列 + 账号（含停用）+ 设备字段 + 运行态摘要；**无凭据明文**。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-view-1", {"token": SECRET}, {"plan": "pro", "nickname": "N"})
        _seed("trae", "acc-view-2", {"access_token": SECRET},
              {"machine_id": "m" * 32, "device_id": "123456789012345"})
        _seed("buddy", "acc-view-3", {"token": SECRET}, {"enabled": False})
        _seed("raccoon", "acc-view-4", {"access_token": SECRET}, {})
        store.write_runtime("raccoon", "acc-view-4", {"cooldown_until": 0, "watermark": 7})
        # 坏 runtime.json：读不动 → fail closed（不得呈现为健康，§22.8-5）
        (store.product_root("raccoon") / "acc-view-4" / "runtime.json").write_text(
            "{not json", encoding="utf-8")

        resp = await client.get(f"{gw.base_url}/admin/api/accounts")
        assert resp.status_code == 200
        assert SECRET not in resp.text
        data = resp.json()

        assert [p["id"] for p in data["products"]] == list(account_registry.PRODUCT_IDS)
        # 产品数随注册表走（Q44 起 11）；accounts/enabled 只数本测试播种的 4 个假账号
        assert data["counts"] == {"products": 11, "accounts": 4, "enabled": 3, "disabled": 1}

        buddy_p = _product_of(data, "buddy")
        assert buddy_p["title"] == "CodeBuddy"
        assert buddy_p["login"] == "external_link" and buddy_p["login_alt"] == []
        assert buddy_p["capabilities"]["checkin"] is True
        assert buddy_p["device"] == {"fields": [], "derive": False}
        acc = next(a for a in buddy_p["accounts"] if a["name"] == "acc-view-1")
        assert acc["enabled"] is True and acc["status"] == "active"
        assert acc["device"] == {}                      # buddy 无设备身份
        assert acc["display"]["plan"] == "pro" and acc["display"]["nickname"] == "N"
        assert acc["display"]["via"] == "login"         # 展示白名单内的键（via/时间戳由落盘写入）
        assert acc["quota"]["state"] == "unknown"       # 未物化资源 → 未知不当零
        assert acc["runtime"] == {} and acc["runtime_ok"] is True
        # 状态查询**包含已停用账号**（§22.6）
        off = next(a for a in buddy_p["accounts"] if a["name"] == "acc-view-3")
        assert off["enabled"] is False and off["status"] == "disabled"
        # 设备字段进视图（trae：machine_id + device_id，权威副本在 meta.json）
        t = _product_of(data, "trae")["accounts"][0]
        assert t["device"] == {"machine_id": "m" * 32, "device_id": "123456789012345"}
        # 运行态：正常快照原样透出；读不动 → status=unknown + 可读原因
        r_ok = next(a for a in _product_of(data, "raccoon")["accounts"]
                    if a["name"] == "acc-view-4")
        assert r_ok["runtime_ok"] is False and r_ok["status"] == "unknown"
        assert "运行态文件读不动" in r_ok["runtime_error"] and r_ok["runtime"] == {}

    async def test_view_quota_cache_summary_tracks_runtime_pool(self, vendor, make_gateway, client):
        """额度缓存摘要：按物化资源关联（product + account/account_ref）读运行态额度池。"""
        gw = await make_gateway(_cfg(vendor.port, extra_resources=[{
            "id": "res-P", "name": "产品资源", "product": "buddy", "account": "acc-q1",
            "account_ref": "acc-q1",
            "protocol": "openai", "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-P"}]))
        _seed("buddy", "acc-q1", {"token": SECRET})
        gw.runtime.resources.set_quota("res-P", 42)

        data = await _view(client, gw)
        acc = next(a for a in _product_of(data, "buddy")["accounts"] if a["name"] == "acc-q1")
        assert acc["quota"]["state"] == "available"
        assert acc["quota"]["remaining"] == 42
        assert acc["quota"]["resources"] == ["res-P"]
        assert acc["quota"]["per_resource"]["res-P"] == {"remaining": 42, "reserved": 0}

        gw.runtime.resources.set_quota("res-P", 0)      # 上游快照耗尽
        data = await _view(client, gw)
        acc = next(a for a in _product_of(data, "buddy")["accounts"] if a["name"] == "acc-q1")
        assert acc["quota"]["state"] == "exhausted" and acc["quota"]["remaining"] == 0

    async def test_capabilities_matrix_matches_registry(self, vendor, make_gateway, client):
        """能力矩阵：10 产品全列，能力位与注册表**同源**（前端按钮数据驱动，§22.6）。"""
        gw = await make_gateway(_cfg(vendor.port))
        resp = await client.get(f"{gw.base_url}/admin/api/accounts/capabilities")
        assert resp.status_code == 200, resp.text
        matrix = {p["id"]: p for p in resp.json()["products"]}
        assert set(matrix) == set(account_registry.PRODUCT_IDS)
        for pid, p in matrix.items():
            assert p["capabilities"] == dict(vars(account_registry.PRODUCTS[pid].capabilities))
        # 逐条判据（§22.4 表：无签到端点的产品必须 False，否则按钮"点了必然失败"）
        assert matrix["workbuddy"]["capabilities"]["checkin"] is False
        assert matrix["cline"]["capabilities"]["checkin"] is False
        assert matrix["raccoon"]["capabilities"]["checkin"] is False
        assert matrix["raccoon"]["capabilities"]["onboarding"] is True
        assert matrix["loomy"]["capabilities"]["refresh"] is False
        assert matrix["zcode"]["capabilities"]["refresh"] is False
        assert matrix["trae"]["login_alt"] == []
        assert matrix["loomy"]["login_alt"] == ["sms_code"]
        assert matrix["raccoon"]["login_alt"] == ["sms_code"]


# ============ 登录会话（start / poll / callback / alt）============

class TestLoginSession:
    async def test_start_poll_success_stages_until_confirm(self, vendor, make_gateway,
                                                           client, monkeypatch):
        """🔴 M7-E 两阶段提交的 **API 级红证对**（本轮验收的核心形状）：

        (a) 没有确认调用时 —— 账号目录**不存在**、`GET /admin/api/accounts` 里**没有**它
            （列表来自磁盘，所以"未确认不出现"是自动成立的，这条把它钉死）；
        (b) 调 `login/commit`（「确定接入」）之后 —— 目录出现、账号在列表里；
        (c) 重复确认幂等（200 + committed True，不二次写）；再轮询 = expired；响应无凭据。
        """
        gw = await make_gateway(_cfg(vendor.port))
        calls = {"n": 0}

        async def fake_start(session):
            session.state["device_secret"] = SECRET          # 私有态：不得回显
            return Challenge(url="https://example.test/auth", device_code="ABCD-1234")

        async def fake_poll(session):
            calls["n"] += 1
            if calls["n"] == 1:
                return LoginOutcome(state="pending", detail="等待用户在浏览器完成授权")
            return LoginOutcome(state="success", credentials={"token": SECRET},
                                meta={"plan": "free"})

        monkeypatch.setitem(buddy._HOOKS, "login_start", fake_start)
        monkeypatch.setitem(buddy._HOOKS, "login_poll", fake_poll)

        r = await _post(client, gw, "/admin/api/accounts/login/start", {"product": "buddy"})
        assert r.status_code == 200, r.text
        assert SECRET not in r.text
        started = r.json()
        sid, name = started["session"], started["account"]
        assert name.startswith("buddy-") and started["kind"] == "external_link"
        assert started["challenge"] == {"url": "https://example.test/auth",
                                        "device_code": "ABCD-1234",
                                        "qr_payload": "", "sms_sent": False}

        pending = await _post(client, gw, "/admin/api/accounts/login/poll",
                              {"product": "buddy", "session": sid})
        assert pending.status_code == 200 and pending.json()["state"] == "pending"
        assert pending.json()["account"] == name and pending.json()["detail"]

        done = await _post(client, gw, "/admin/api/accounts/login/poll",
                           {"product": "buddy", "session": sid})
        assert done.status_code == 200, done.text
        assert done.json()["state"] == "success" and SECRET not in done.text

        # —— (a) 确认之前：磁盘无目录、视图无账号（红证对的上半）——
        assert not store.has_account(store.product_root("buddy"), name), \
            "success 只暂存：确认之前不许出现账号目录（M7-E）"
        data = await _view(client, gw)
        assert not any(a["name"] == name for a in _product_of(data, "buddy")["accounts"]), \
            "未确认的账号不得出现在账号列表里（列表来自磁盘）"

        # —— (b) 「确定接入」：落盘 + 出现在列表（红证对的下半）——
        commit = await _post(client, gw, "/admin/api/accounts/login/commit",
                             {"product": "buddy", "session": sid})
        assert commit.status_code == 200, commit.text
        assert commit.json()["committed"] is True and commit.json()["account"] == name, commit.text
        assert SECRET not in commit.text
        assert store.load_credentials("buddy", name) == {"token": SECRET}
        assert _meta_of("buddy", name)["plan"] == "free"
        data = await _view(client, gw)
        assert any(a["name"] == name for a in _product_of(data, "buddy")["accounts"])

        # —— (c) 幂等：重复确认 200 + committed True（走台账，不二次写）；再轮询 = expired ——
        again_commit = await _post(client, gw, "/admin/api/accounts/login/commit",
                                   {"product": "buddy", "session": sid})
        assert again_commit.status_code == 200
        assert again_commit.json()["committed"] is True, again_commit.text
        assert store.load_credentials("buddy", name) == {"token": SECRET}   # 内容未被重写
        again = await _post(client, gw, "/admin/api/accounts/login/poll",
                            {"product": "buddy", "session": sid})
        assert again.json()["state"] == "expired"

    async def test_commit_and_cancel_are_idempotent_never_404(self, vendor, make_gateway,
                                                              client, monkeypatch):
        """🔴 第二对红证：**成功后取消** → 账号目录不存在、视图无它、确认如实回报未落盘。

        另钉幂等纪律面：未知会话/空会话的 commit 与 cancel 都是 200（**永不 404**），
        并把 `{committed:false}` / `{cancelled:false}` 如实回报。
        """
        gw = await make_gateway(_cfg(vendor.port))

        async def fake_start(session):
            return Challenge(url="https://example.test/auth")

        async def fake_poll(session):
            return LoginOutcome(state="success", credentials={"token": SECRET}, meta={})

        monkeypatch.setitem(buddy._HOOKS, "login_start", fake_start)
        monkeypatch.setitem(buddy._HOOKS, "login_poll", fake_poll)

        started = (await _post(client, gw, "/admin/api/accounts/login/start",
                               {"product": "buddy"})).json()
        sid, name = started["session"], started["account"]
        done = await _post(client, gw, "/admin/api/accounts/login/poll",
                           {"product": "buddy", "session": sid})
        assert done.json()["state"] == "success"

        # 登录已成功（暂存）→ 用户取消（关窗/点取消）→ 暂存被丢弃
        cancel = await _post(client, gw, "/admin/api/accounts/login/cancel",
                             {"product": "buddy", "session": sid})
        assert cancel.status_code == 200 and cancel.json() == {"cancelled": True}
        assert not store.has_account(store.product_root("buddy"), name), \
            "成功后取消不许留下账号目录（确认步的意义）"
        # 落盘开关已失效：确认如实回报"未落盘"（不 404、不谎报）
        commit = await _post(client, gw, "/admin/api/accounts/login/commit",
                             {"product": "buddy", "session": sid})
        assert commit.status_code == 200
        assert commit.json()["committed"] is False and commit.json()["reason"], commit.text
        assert not store.has_account(store.product_root("buddy"), name)
        data = await _view(client, gw)
        assert not any(a["name"] == name for a in _product_of(data, "buddy")["accounts"])

        # 幂等面：未知 / 空会话的 commit 也是 200 + committed False（不是 404）
        for body in ({"session": "nope"}, {}, {"session": "nope", "product": "buddy"}):
            r = await _post(client, gw, "/admin/api/accounts/login/commit", body)
            assert r.status_code == 200, r.text
            assert r.json()["committed"] is False, r.text
        # 串线门与 poll/callback/cancel 一致：**活会话**配错产品当场 400
        # （已出表的会话无对象可比 → 与 cancel 同口径走 {committed:false}，不猜产品）
        live = (await _post(client, gw, "/admin/api/accounts/login/start",
                            {"product": "buddy"})).json()["session"]
        r = await _post(client, gw, "/admin/api/accounts/login/commit",
                        {"product": "trae", "session": live})
        assert r.status_code == 400 and "不匹配" in r.json()["error"]["message"]
        await _post(client, gw, "/admin/api/accounts/login/cancel",
                    {"product": "buddy", "session": live})

    async def test_login_cancel_is_idempotent_and_drops_the_session(
            self, vendor, make_gateway, client, monkeypatch):
        """BD2 取消路由：真取消 → 会话出表；重复取消/取消不存在的会话 → **不是错误**。

        🔴 为什么 `cancelled: false` 必须是 200：用户点「取消」与上游回跳到达是竞态关系，
        把"会话早已 settle/超时"呈现成一次失败 = 让用户以为界面坏了。监听器的实际关闭
        由 `LoginEngine._drop` 负责（端口级证据在 `test_m7_callback_capture.py::test_cancel_closes_the_listener`）。
        """
        gw = await make_gateway(_cfg(vendor.port))
        async def fake_start(session):
            return Challenge(url="https://example.test/auth")
        monkeypatch.setitem(buddy._HOOKS, "login_start", fake_start)

        sid = (await _post(client, gw, "/admin/api/accounts/login/start",
                           {"product": "buddy"})).json()["session"]
        r = await _post(client, gw, "/admin/api/accounts/login/cancel",
                        {"product": "buddy", "session": sid})
        assert r.status_code == 200 and r.json() == {"cancelled": True}, r.text
        # 出表证据：再轮询 = expired（引擎口径），再取消 = cancelled False 且仍 200
        assert (await _post(client, gw, "/admin/api/accounts/login/poll",
                            {"product": "buddy", "session": sid})).json()["state"] == "expired"
        r = await _post(client, gw, "/admin/api/accounts/login/cancel",
                        {"product": "buddy", "session": sid})
        assert r.status_code == 200 and r.json() == {"cancelled": False}, r.text
        # 从未存在过的会话同口径（幂等，不 404）
        r = await _post(client, gw, "/admin/api/accounts/login/cancel", {"session": "nope"})
        assert r.status_code == 200 and r.json() == {"cancelled": False}, r.text
        # 串线门与 poll/callback 一致：配错产品当场 400，不静默取消别人的会话
        other = (await _post(client, gw, "/admin/api/accounts/login/start",
                             {"product": "buddy"})).json()["session"]
        r = await _post(client, gw, "/admin/api/accounts/login/cancel",
                        {"product": "trae", "session": other})
        assert r.status_code == 400 and "不匹配" in r.json()["error"]["message"]
        assert (await _post(client, gw, "/admin/api/accounts/login/cancel",
                            {"product": "codearts", "session": other})).status_code == 400
        # 未登记产品 = 400，但**不因此把已存在的会话取消掉**
        assert (await _post(client, gw, "/admin/api/accounts/login/cancel",
                            {"session": other})).json() == {"cancelled": True}

    async def test_login_param_and_session_guards(self, vendor, make_gateway, client, monkeypatch):
        """未知产品 / 非法 kind / 缺参 / 会话不存在 / 跨产品会话 → 4xx + 可读原因。"""
        gw = await make_gateway(_cfg(vendor.port))
        async def fake_start(session):
            return Challenge(url="https://example.test/auth")
        monkeypatch.setitem(buddy._HOOKS, "login_start", fake_start)

        r = await _post(client, gw, "/admin/api/accounts/login/start", {"product": "codearts"})
        assert r.status_code == 400 and "未登记的产品" in r.json()["error"]["message"]
        r = await _post(client, gw, "/admin/api/accounts/login/start", {"product": ""})
        assert r.status_code == 400 and "product" in r.json()["error"]["message"]
        r = await _post(client, gw, "/admin/api/accounts/login/start",
                        {"product": "loomy", "kind": "device_code"})
        assert r.status_code == 400
        assert "登录方式 'device_code' 非法" in r.json()["error"]["message"]
        assert "'sms_code'" in r.json()["error"]["message"]     # 合法值可读

        started = (await _post(client, gw, "/admin/api/accounts/login/start",
                               {"product": "buddy"})).json()
        # 跨产品驱动会话：会话表是全局的，配错产品必须当场拒绝（与 alt_call 同口径）
        r = await _post(client, gw, "/admin/api/accounts/login/poll",
                        {"product": "trae", "session": started["session"]})
        assert r.status_code == 400 and "不匹配" in r.json()["error"]["message"]
        # 未知会话：poll/callback 走引擎状态机 → expired 状态（不是 500）
        r = await _post(client, gw, "/admin/api/accounts/login/poll",
                        {"product": "buddy", "session": "nope"})
        assert r.status_code == 200 and r.json()["state"] == "expired"
        # alt 必须拿到会话对象 → 未知会话 404；args 非对象 400；名字缺失 400
        r = await _post(client, gw, "/admin/api/accounts/login/alt",
                        {"product": "loomy", "session": "nope", "name": "sms_send", "args": {}})
        assert r.status_code == 404 and "会话不存在" in r.json()["error"]["message"]
        r = await _post(client, gw, "/admin/api/accounts/login/alt",
                        {"product": "buddy", "session": started["session"]})
        assert r.status_code == 400 and "name" in r.json()["error"]["message"]

    async def test_callback_validation_failure_is_readable(self, vendor, make_gateway,
                                                           client, monkeypatch):
        """回跳粘贴（trae 真钩子，零网络）：端口不符 → `failed` + 可读原因（不是 5xx）。"""
        gw = await make_gateway(_cfg(vendor.port))
        started = (await _post(client, gw, "/admin/api/accounts/login/start",
                               {"product": "trae"})).json()
        assert started["challenge"]["url"]                      # 零网络的登录页 URL
        sid = started["session"]

        bad = await _post(client, gw, "/admin/api/accounts/login/callback", {
            "product": "trae", "session": sid,
            "params": {"url": f"http://127.0.0.1:9999/authorize?code=x&loginTraceId=y"}})
        assert bad.status_code == 200, bad.text
        body = bad.json()
        assert body["state"] == "failed" and "回跳校验未通过" in body["detail"]
        assert "18080" in body["detail"] and SECRET not in bad.text
        assert not store.has_account(store.product_root("trae"), started["account"])

        # 平铺形态（不带 params 包裹）：空参数 → 解析失败（同一出口，仍 200 + failed）
        started2 = (await _post(client, gw, "/admin/api/accounts/login/start",
                                {"product": "trae"})).json()
        flat = await _post(client, gw, "/admin/api/accounts/login/callback",
                           {"product": "trae", "session": started2["session"]})
        assert flat.json()["state"] == "failed" and "回跳解析失败" in flat.json()["detail"]

    async def test_alt_sms_second_stage_stages_then_commit_persists(
            self, vendor, make_gateway, client, monkeypatch):
        """alt 短信两段（loomy）：第二段成功 → **认领暂存**（磁盘干净）→ `login/commit`
        落盘 → 视图可见。M7-E 起五型登录共用同一次确认（短信型不再绕过）。"""
        gw = await make_gateway(_cfg(vendor.port))
        sent: dict = {}

        async def fake_start(session):
            return Challenge(qr_payload="weixin://qr/abc")

        async def fake_send(session, *, phone: str):
            sent["phone"] = phone
            return LoginOutcome(state="pending", detail=f"验证码已发送至 {phone[:3]}****")

        async def fake_submit(session, *, sms_code: str):
            sent["code"] = sms_code
            return LoginOutcome(state="success", credentials={"token": SECRET},
                                meta={"nickname": "sms-user"}, detail="登录成功")

        monkeypatch.setitem(loomy._HOOKS, "login_start", fake_start)
        monkeypatch.setitem(loomy._ALT_HOOKS, "sms_send", fake_send)
        monkeypatch.setitem(loomy._ALT_HOOKS, "sms_submit", fake_submit)

        started = (await _post(client, gw, "/admin/api/accounts/login/start",
                               {"product": "loomy", "kind": "sms_code"})).json()
        assert started["kind"] == "sms_code"
        sid, name = started["session"], started["account"]

        r1 = await _post(client, gw, "/admin/api/accounts/login/alt",
                         {"product": "loomy", "session": sid, "name": "sms_send",
                          "args": {"phone": "13800138000"}})
        assert r1.status_code == 200, r1.text
        assert r1.json()["kind"] == "outcome" and r1.json()["state"] == "pending"
        assert sent["phone"] == "13800138000"
        assert not store.has_account(store.product_root("loomy"), name)   # 未成功不落盘

        r2 = await _post(client, gw, "/admin/api/accounts/login/alt",
                         {"product": "loomy", "session": sid, "name": "sms_submit",
                          "args": {"sms_code": "123456"}})
        assert r2.status_code == 200, r2.text
        assert SECRET not in r2.text                       # 凭据不回传
        assert r2.json()["state"] == "success" and r2.json()["account"] == name
        # 🔴 M7-E：第二段成功只暂存（磁盘干净），确认才落盘
        assert not store.has_account(store.product_root("loomy"), name), \
            "短信第二段成功也只暂存（与其它四型同一次确认）"
        commit = await _post(client, gw, "/admin/api/accounts/login/commit",
                             {"session": sid})
        assert commit.status_code == 200 and commit.json()["committed"] is True, commit.text
        assert store.load_credentials("loomy", name) == {"token": SECRET}
        assert _meta_of("loomy", name)["nickname"] == "sms-user"
        data = await _view(client, gw)
        assert any(a["name"] == name and a["status"] == "active"
                   for a in _product_of(data, "loomy")["accounts"])

    async def test_alt_unknown_name_and_missing_table_are_4xx(self, vendor, make_gateway,
                                                              client, monkeypatch):
        """`_ALT_HOOKS` 的表纪律经入口层同样生效：未知名字/未导出表 → 400（可读合法值）。"""
        gw = await make_gateway(_cfg(vendor.port))
        async def fake_start(session):
            return Challenge(qr_payload="x")
        monkeypatch.setitem(loomy._HOOKS, "login_start", fake_start)
        sid = (await _post(client, gw, "/admin/api/accounts/login/start",
                           {"product": "loomy", "kind": "sms_code"})).json()["session"]

        r = await _post(client, gw, "/admin/api/accounts/login/alt",
                        {"product": "loomy", "session": sid, "name": "sms_call", "args": {}})
        assert r.status_code == 400
        assert "sms_call" in r.json()["error"]["message"]
        assert "sms_send" in r.json()["error"]["message"]      # 合法值可读
        # buddy 没有备选形态（未导出 `_ALT_HOOKS`）→ 400，不是"点了必然失败"
        r2 = await _post(client, gw, "/admin/api/accounts/login/alt",
                         {"product": "buddy", "session": "whatever", "name": "sms_send",
                          "args": {}})
        assert r2.status_code == 400
        assert "_ALT_HOOKS" in r2.json()["error"]["message"]


# ============ 单账号操作：claim（ops 四类出口）============

class TestClaimFourCategories:
    async def test_claim_four_categories_report_and_outlet(self, vendor, make_gateway,
                                                           client, monkeypatch):
        """claim 四类结果 + 报告落 `ops-results-*.jsonl` + meta 通道锚字段 + precheck 声明。"""
        gw = await make_gateway(_cfg(vendor.port))
        seen: list[dict] = []
        box = {"category": "success", "detail": "已领取"}

        async def fake_claim(cred, meta, *, precheck):
            seen.append({"cred": cred, "meta": meta, "precheck": precheck})
            return ClaimOutcome(category=box["category"], detail=box["detail"])

        monkeypatch.setitem(buddy._HOOKS, "claim", fake_claim)
        monkeypatch.setitem(trae._HOOKS, "claim", fake_claim)
        for name in ("acc-c1", "acc-c2", "acc-c3", "acc-c4"):
            _seed("buddy", name, {"token": SECRET})
        _seed("trae", "acc-c9", {"access_token": SECRET})
        _seed("buddy", "acc-off", {"token": SECRET}, {"enabled": False})

        cases = [("success", "acc-c1"), ("already_done", "acc-c2"),
                 ("inactive", "acc-c3"), ("failed", "acc-c4")]
        for category, name in cases:
            box.update(category=category, detail=f"原因-{category}")
            r = await _post(client, gw, f"/admin/api/accounts/buddy/{name}/claim")
            assert r.status_code == 200, r.text
            assert SECRET not in r.text
            body = r.json()
            assert body["category"] == category and body["detail"] == f"原因-{category}"
            assert body["report"][category] != [] or category == "failed"
            assert body["written"] is True
            if category == "failed":
                assert body["report"]["failed"] == [{"account": name, "reason": f"原因-{category}"}]

        # §22.3 补入①：meta 通道锚字段（账号名 + 绝对目录）——入口层不得自行拼 dict
        assert seen[0]["meta"]["account"] == "acc-c1"
        assert Path(seen[0]["meta"]["dir"]).is_absolute()
        assert Path(seen[0]["meta"]["dir"]).name == "acc-c1"
        assert seen[0]["cred"] == {"token": SECRET} and seen[0]["precheck"] is False

        # precheck 的 per-product 声明（§22.6 / `20 B6`）：trae **必须** True
        r = await _post(client, gw, "/admin/api/accounts/trae/acc-c9/claim")
        assert r.status_code == 200 and r.json()["precheck"] is True
        assert seen[-1]["precheck"] is True

        # 停用账号：**运营跳过**（§22.6）→ inactive + no_participants，且**不发产品钩子**
        before = len(seen)
        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-off/claim")
        body = r.json()
        assert body["category"] == "inactive" and "停用" in body["detail"]
        assert body["report"]["no_participants"] is True
        assert body["report"]["skipped"] == ["acc-off"]
        assert len(seen) == before

        # 结果出口：当日 `ops-results-*.jsonl`（顶栏红点同源；**不含凭据**，§22.8-8）
        day = dt.datetime.now().strftime("%Y%m%d")
        lines = (gw.usage_dir / f"ops-results-{day}.jsonl").read_text(encoding="utf-8")
        assert '"acc-c4"' in lines and "原因-failed" in lines
        assert SECRET not in lines

    async def test_claim_exception_is_failed_and_isolated(self, vendor, make_gateway,
                                                          client, monkeypatch):
        """claim 钩子抛异常 → 四类里的 `failed`（单账号失败不中断批量，§22.8-6）。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-x1", {"token": SECRET})

        async def boom(cred, meta, *, precheck):
            raise RuntimeError("上游炸了")

        monkeypatch.setitem(buddy._HOOKS, "claim", boom)
        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-x1/claim")
        assert r.status_code == 200, r.text
        assert r.json()["category"] == "failed" and "上游炸了" in r.json()["detail"]
        assert SECRET not in r.text

    async def test_claim_skips_when_account_locked(self, vendor, make_gateway, client,
                                                   monkeypatch):
        """账号级互斥（§16.4）：另一入口在飞 → 本次**不发起**，且原因说法与"停用"分开。"""
        from model_gateway.ops import runner as ops_runner

        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-l1", {"token": SECRET})
        called: list[str] = []

        async def fake_claim(cred, meta, *, precheck):
            called.append(meta["account"])
            return ClaimOutcome(category="success", detail="ok")

        monkeypatch.setitem(buddy._HOOKS, "claim", fake_claim)
        other = ops_runner.AccountLocks()               # "另一个入口"（CLI / 定时任务）
        assert other.try_acquire("acc-l1") is True
        try:
            r = await _post(client, gw, "/admin/api/accounts/buddy/acc-l1/claim")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["category"] == "inactive" and "另一处执行" in body["detail"]
            assert "停用" not in body["detail"]          # 不得把锁跳过谎报成停用
            assert body["report"]["skipped"] == ["acc-l1"]
            assert called == []                          # 未发起 = 没打产品钩子
        finally:
            other.release("acc-l1")

    async def test_claim_unknown_product_and_account_are_4xx(self, vendor, make_gateway, client):
        """未知产品 → 400；未知账号 → 404（都是可读原因，不是 500）。"""
        gw = await make_gateway(_cfg(vendor.port))
        r = await _post(client, gw, "/admin/api/accounts/codearts/x/claim")
        assert r.status_code == 400 and "未登记的产品" in r.json()["error"]["message"]
        r = await _post(client, gw, "/admin/api/accounts/buddy/ghost/claim")
        assert r.status_code == 404 and "账号不存在" in r.json()["error"]["message"]
        # 目录穿越/非法账号名 → 白名单当场拦下（%2E%2E 解码后为 ".."，不能经 httpx 归一化绕过）
        r = await _post(client, gw, "/admin/api/accounts/buddy/%2E%2E/claim")
        assert r.status_code == 400 and "账号名必须匹配" in r.json()["error"]["message"]
        r = await _post(client, gw, "/admin/api/accounts/buddy/bad%20name/claim")
        assert r.status_code == 400 and "账号名必须匹配" in r.json()["error"]["message"]


# ============ 单账号操作：refresh / probe ============

class TestRefreshAndProbe:
    async def test_refresh_success_not_refreshable_and_rollback(self, vendor, make_gateway,
                                                                client, monkeypatch):
        """续期：成功落盘（新值）/ `NotRefreshable` → 409 / 空返回值不覆盖 / 落盘失败 500。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-r1", {"token": "OLD", "refresh_token": "RT"}, {"plan": "free"})
        seen: dict = {}

        async def fake_refresh(cred, meta):
            seen.update({"cred": cred, "meta": meta})
            return {**cred, "token": SECRET}

        monkeypatch.setitem(buddy._HOOKS, "refresh", fake_refresh)
        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-r1/refresh")
        assert r.status_code == 200, r.text
        assert SECRET not in r.text
        assert store.load_credentials("buddy", "acc-r1") == {"token": SECRET, "refresh_token": "RT"}
        assert seen["cred"]["token"] == "OLD"                     # 传的是现值
        assert seen["meta"]["account"] == "acc-r1"                # meta 通道（§22.3 ①）
        assert Path(seen["meta"]["dir"]).is_absolute()
        assert _meta_of("buddy", "acc-r1")["via"] == "login"      # 重复落盘不改来源标记
        assert _meta_of("buddy", "acc-r1")["plan"] == "free"      # 既有 meta 键保留

        # NotRefreshable → 409「不可续期」（明确语义，**不是 500**）
        async def nor(cred, meta):
            raise NotRefreshable("无 refresh_token，请重新登录")
        monkeypatch.setitem(buddy._HOOKS, "refresh", nor)
        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-r1/refresh")
        assert r.status_code == 409, r.text
        assert "不可续期" in r.json()["error"]["message"]
        assert r.json()["error"]["refreshable"] is False

        # 空返回值 → 502 且**不覆盖**旧凭据（"不写回空令牌"纪律）
        async def empty(cred, meta):
            return {}
        monkeypatch.setitem(buddy._HOOKS, "refresh", empty)
        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-r1/refresh")
        assert r.status_code == 502 and "不覆盖旧凭据" in r.json()["error"]["message"]
        assert store.load_credentials("buddy", "acc-r1")["token"] == SECRET

        # 落盘自检失败（已回滚）→ 500 + 可读原因（不谎报成功）
        async def fresh(cred, meta):
            return {"token": "NEW-2"}
        monkeypatch.setitem(buddy._HOOKS, "refresh", fresh)

        def boom(*a, **k):
            from model_gateway.accounts.store import CommitError
            raise CommitError("写回自检：凭据键 'token' 读回不一致")
        monkeypatch.setattr(store, "commit_login", boom)
        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-r1/refresh")
        assert r.status_code == 500 and "已回滚" in r.json()["error"]["message"]

    async def test_refresh_ignores_enabled_flag(self, vendor, make_gateway, client, monkeypatch):
        """§22.6：**续期不看 enabled** —— 停用账号照常续期（与运营跳过停用是两回事）。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-r2", {"token": "OLD"}, {"enabled": False})

        async def fake_refresh(cred, meta):
            return {"token": SECRET}
        monkeypatch.setitem(buddy._HOOKS, "refresh", fake_refresh)
        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-r2/refresh")
        assert r.status_code == 200 and store.load_credentials("buddy", "acc-r2") == {"token": SECRET}
        assert _meta_of("buddy", "acc-r2")["enabled"] is False     # 停用位不受影响

    async def test_probe_real_product_code_against_fake_upstream(self, vendor, make_gateway,
                                                                 client, monkeypatch):
        """probe 走**真实产品代码**（raccoon）+ 假上游（MockTransport）：两维分开且无凭据回传。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("raccoon", "acc-p1", {"access_token": SECRET})
        box = {"status": 200, "payload": {"code": 0, "data": {"user_id": "u-1"}}}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.host == "xiaohuanxiong.com"
            assert request.url.path == "/api/web/auth/v1/user_info"
            assert request.headers.get("authorization") == f"Bearer {SECRET}"
            return httpx.Response(box["status"], json=box["payload"])

        def fake_make_client(*, base_url="", headers=None, timeout=None, follow_redirects=True):
            return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler),
                                     headers=headers or {}, timeout=timeout or 5.0,
                                     follow_redirects=follow_redirects)
        monkeypatch.setattr(accounts_net, "make_client", fake_make_client)

        r = await _post(client, gw, "/admin/api/accounts/raccoon/acc-p1/probe")
        assert r.status_code == 200, r.text
        assert SECRET not in r.text
        body = r.json()
        assert body["reachable"] is True and body["valid"] is True and body["ok"] is True

        box.update(status=401, payload={"code": 200003, "message": "登录态已过期"})
        r = await _post(client, gw, "/admin/api/accounts/raccoon/acc-p1/probe")
        body = r.json()
        assert body["reachable"] is True and body["valid"] is False and body["ok"] is False
        assert "重新登录" in body["detail"]

    async def test_probe_unknown_account_404(self, vendor, make_gateway, client):
        gw = await make_gateway(_cfg(vendor.port))
        r = await _post(client, gw, "/admin/api/accounts/buddy/ghost/probe")
        assert r.status_code == 404
        r = await _post(client, gw, "/admin/api/accounts/buddy/%2E%2E/refresh")
        assert r.status_code == 400 and "账号名必须匹配" in r.json()["error"]["message"]


# ============ enable / disable / delete ============

class TestEnableDisableDelete:
    async def test_enable_disable_roundtrip_and_view(self, vendor, make_gateway, client):
        """enable/disable 写 meta `enabled` 位：幂等、视图同步、凭据本体原样保留。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-e1", {"token": SECRET}, {"plan": "free"})

        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-e1/disable")
        # 🔴 键集逐字钉住（Q33-①② 后两条腿同键）：`reload` = 启停是否**即时**落到运行态
        #    （R3 F-4 实测原实现有 ≥3s 窗口照常派发流量，界面必须能如实说"已生效/待生效"）。
        assert r.status_code == 200 and r.json() == {"status": "ok", "product": "buddy",
                                                     "account": "acc-e1", "enabled": False,
                                                     "changed": True, "reload": True,
                                                     "mapping_skipped": []}
        assert SECRET not in r.text
        assert _meta_of("buddy", "acc-e1")["enabled"] is False
        assert _meta_of("buddy", "acc-e1")["via"] == "login"       # 来源标记不被改写
        assert store.load_credentials("buddy", "acc-e1") == {"token": SECRET}

        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-e1/disable")
        assert r.json()["changed"] is False                        # 幂等

        data = await _view(client, gw)
        acc = next(a for a in _product_of(data, "buddy")["accounts"] if a["name"] == "acc-e1")
        assert acc["enabled"] is False and acc["status"] == "disabled"

        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-e1/enable")
        assert r.json()["enabled"] is True and r.json()["changed"] is True
        data = await _view(client, gw)
        acc = next(a for a in _product_of(data, "buddy")["accounts"] if a["name"] == "acc-e1")
        assert acc["status"] == "active"

    async def test_enable_after_stale_meta_still_works(self, vendor, make_gateway, client,
                                                       monkeypatch):
        """P-B1 回归（API 面）：`updated_at` 与上一次写入**不同秒**时 disable 仍 200。

        真机复现（Fix-4 在 8399 独立实例 curl）：对"已写过的账号"enable/disable 必 500
        「写回自检：元信息键 'updated_at' 读回不一致」。根因与修法见
        `store.py::_verify_written`（比较基准改为 `merged`）。
        """
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-e2", {"token": SECRET})
        monkeypatch.setattr(store, "_now", lambda: "2099-01-01T00:00:00")   # 模拟"隔秒"
        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-e2/disable")
        assert r.status_code == 200, r.text
        meta = _meta_of("buddy", "acc-e2")
        assert meta["enabled"] is False
        assert meta["updated_at"] == "2099-01-01T00:00:00"
        assert store.load_credentials("buddy", "acc-e2") == {"token": SECRET}

    async def test_delete_requires_confirm(self, vendor, make_gateway, client):
        """delete 是破坏性操作：缺省拒绝（400 且不动盘）；`?confirm=1` 才删；重复删 404。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-d1", {"token": SECRET}, {"plan": "free"})
        root = store.product_root("buddy")

        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-d1/delete")
        assert r.status_code == 400 and "confirm=1" in r.json()["error"]["message"]
        assert store.has_account(root, "acc-d1")                  # 未确认 → 一个字节都没动
        assert SECRET not in r.text

        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-d1/delete?confirm=1")
        assert r.status_code == 200 and r.json()["deleted"] is True
        assert not store.has_account(root, "acc-d1")
        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-d1/delete?confirm=1")
        assert r.status_code == 404

    async def test_delete_disables_linked_resources(self, vendor, make_gateway, client):
        """§22.5-1：删除账号 → 其关联资源置 `enabled=false` **保留**（先停用、后删目录）。

        资源停用经物化面 `accounts/materialize.py::disable_resource`，落点是**生效配置**
        （本用例 = conftest 钉住的 `MG_CONFIG`）；条目本体保留（统计与历史不丢）。
        """
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-d2", {"token": SECRET})
        cfg_path = Path(os.environ["MG_CONFIG"])                  # 物化面的落盘路径
        cfg_path.write_text(yaml.safe_dump({"resources": [
            {"id": "res-Z", "name": "账号资源", "product": "buddy", "account_ref": "acc-d2",
             "account": "acc-d2", "protocol": "openai",
             "base_url": "http://127.0.0.1:9/v1", "api_key": "", "enabled": True},
        ], "models": []}, allow_unicode=True), encoding="utf-8")

        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-d2/delete?confirm=1")
        assert r.status_code == 200, r.text
        assert r.json()["resources_disabled"] is True
        assert not store.has_account(store.product_root("buddy"), "acc-d2")
        saved = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        assert len(saved["resources"]) == 1                       # 保留条目，不是删除
        assert saved["resources"][0]["id"] == "res-Z"
        assert saved["resources"][0]["enabled"] is False


# ============ 导入 ============

class TestImport:
    async def test_import_ok_duplicate_and_conflict_flow(self, vendor, make_gateway, client):
        """import：成功落盘（无凭据回传）/ 同名拒绝 / 设备身份冲突 409 交用户决策。"""
        gw = await make_gateway(_cfg(vendor.port))
        payload = {"credentials": {"token": SECRET}, "meta": {"plan": "x"}}

        r = await _post(client, gw, "/admin/api/accounts/import",
                        {"product": "buddy", "name": "acc-i1", "payload": payload})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ok" and r.json()["account"] == "acc-i1"
        assert SECRET not in r.text
        assert store.load_credentials("buddy", "acc-i1") == {"token": SECRET}
        assert _meta_of("buddy", "acc-i1")["via"] == "import"

        # 同名重复：拒绝（不覆盖既有账号）
        r = await _post(client, gw, "/admin/api/accounts/import",
                        {"product": "buddy", "name": "acc-i1", "payload": payload})
        assert r.status_code == 400 and "已存在" in r.json()["error"]["message"]
        assert store.load_credentials("buddy", "acc-i1") == {"token": SECRET}

        # trae 设备身份（machine_id + device_id）：第二份同身份载荷 → 409 + 两条出路
        base = {"credentials": {"access_token": SECRET},
                "meta": {"machine_id": "M" * 32, "device_id": "D" * 15}}
        r = await _post(client, gw, "/admin/api/accounts/import",
                        {"product": "trae", "name": "acc-i2", "payload": base})
        assert r.status_code == 200, r.text
        assert r.json()["device_values"] == ["M" * 32, "D" * 15]
        r = await _post(client, gw, "/admin/api/accounts/import",
                        {"product": "trae", "name": "acc-i3", "payload": base})
        assert r.status_code == 409, r.text
        err = r.json()["error"]
        assert err["conflict"] is True and err["conflict_with"] == "acc-i2"
        assert "reuse" in err["hint"] and "regenerate" in err["hint"]
        assert not store.has_account(store.product_root("trae"), "acc-i3")
        # reuse：复用冲突账号的设备身份 → 接受
        r = await _post(client, gw, "/admin/api/accounts/import",
                        {"product": "trae", "name": "acc-i3", "payload": base, "reuse": "acc-i2"})
        assert r.status_code == 200 and r.json()["device_values"] == ["M" * 32, "D" * 15]
        # regenerate：重新生成一套完整身份 → 接受且与既有不同
        r = await _post(client, gw, "/admin/api/accounts/import",
                        {"product": "trae", "name": "acc-i4", "payload": base,
                         "regenerate": True})
        assert r.status_code == 200, r.text
        assert r.json()["device_values"][0] != "M" * 32
        assert _meta_of("trae", "acc-i4")["machine_id"] == r.json()["device_values"][0]

    async def test_import_rejection_branches(self, vendor, make_gateway, client):
        """拒绝分支：未登记产品 / 缺导入源 / payload 非对象 / 坏路径 —— 全是 4xx 且不落盘。"""
        gw = await make_gateway(_cfg(vendor.port))
        r = await _post(client, gw, "/admin/api/accounts/import",
                        {"product": "codearts", "payload": {"token": SECRET}})
        assert r.status_code == 400 and "未登记的产品" in r.json()["error"]["message"]
        r = await _post(client, gw, "/admin/api/accounts/import", {"product": "buddy"})
        assert r.status_code == 400 and "导入源" in r.json()["error"]["message"]
        r = await _post(client, gw, "/admin/api/accounts/import",
                        {"product": "buddy", "payload": ["not", "an", "object"]})
        assert r.status_code == 400 and "payload" in r.json()["error"]["message"]
        r = await _post(client, gw, "/admin/api/accounts/import",
                        {"product": "buddy", "path": "/nonexistent/nope.json"})
        assert r.status_code == 400 and "凭据不可用" in r.json()["error"]["message"]
        assert store.list_accounts("buddy") == []
        assert SECRET not in r.text


# ============ 凭据不回传（扫尾）============

class TestNoCredentialLeak:
    async def test_no_credential_in_any_response(self, vendor, make_gateway, client, monkeypatch):
        """全端点扫尾：凭据明文不出现在任何响应体里（§22.7 硬约束）。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-leak", {"token": SECRET, "refresh_token": SECRET},
              {"plan": "free", "nickname": "n"})

        async def fake_start(session):
            session.state["private_state"] = SECRET          # 会话私态：同样不得回显
            return Challenge(url="https://example.test/auth", device_code="DC")

        async def fake_poll(session):
            return LoginOutcome(state="success", credentials={"token": SECRET},
                                meta={"plan": "p"})

        async def fake_alt_submit(session, *, sms_code: str):
            return LoginOutcome(state="success", credentials={"token": SECRET}, meta={})

        async def fake_refresh(cred, meta):
            return {"token": SECRET, "refresh_token": SECRET}

        async def fake_claim(cred, meta, *, precheck):
            return ClaimOutcome(category="success", detail="ok")

        async def fake_probe(cred, meta):
            return ProbeResult(reachable=True, valid=True, detail="凭据有效")

        monkeypatch.setitem(buddy._HOOKS, "login_start", fake_start)
        monkeypatch.setitem(buddy._HOOKS, "login_poll", fake_poll)
        monkeypatch.setitem(buddy._HOOKS, "refresh", fake_refresh)
        monkeypatch.setitem(buddy._HOOKS, "claim", fake_claim)
        monkeypatch.setitem(buddy._HOOKS, "probe", fake_probe)
        monkeypatch.setitem(loomy._HOOKS, "login_start", fake_start)
        monkeypatch.setitem(loomy._ALT_HOOKS, "sms_submit", fake_alt_submit)

        start = await _post(client, gw, "/admin/api/accounts/login/start", {"product": "buddy"})
        poll = await _post(client, gw, "/admin/api/accounts/login/poll",
                           {"product": "buddy", "session": start.json()["session"]})
        loomy_start = await _post(client, gw, "/admin/api/accounts/login/start",
                                  {"product": "loomy", "kind": "sms_code"})
        alt = await _post(client, gw, "/admin/api/accounts/login/alt",
                          {"product": "loomy", "session": loomy_start.json()["session"],
                           "name": "sms_submit", "args": {"sms_code": "1"}})
        assert poll.json()["state"] == "success" and alt.json()["state"] == "success"

        responses = [
            await client.get(f"{gw.base_url}/admin/api/accounts"),
            await client.get(f"{gw.base_url}/admin/api/accounts/capabilities"),
            await _post(client, gw, "/admin/api/accounts/buddy/acc-leak/claim"),
            await _post(client, gw, "/admin/api/accounts/buddy/acc-leak/refresh"),
            await _post(client, gw, "/admin/api/accounts/buddy/acc-leak/probe"),
            await _post(client, gw, "/admin/api/accounts/buddy/acc-leak/disable"),
            await _post(client, gw, "/admin/api/accounts/import",
                        {"product": "buddy", "name": "acc-leak-2",
                         "payload": {"credentials": {"token": SECRET}}}),
            start, poll, loomy_start, alt,
            await _post(client, gw, "/admin/api/accounts/login/alt",
                        {"product": "buddy", "session": "x", "name": "sms_send", "args": {}}),
        ]
        for resp in responses:
            assert SECRET not in resp.text, f"凭据泄露到响应：{resp.request.url} → {resp.text}"
        # 视图的 `display` 白名单不含凭据本体之外的键（meta.json 私有键一律不出）
        view = (await client.get(f"{gw.base_url}/admin/api/accounts")).json()
        acc = next(a for a in _product_of(view, "buddy")["accounts"] if a["name"] == "acc-leak")
        assert set(acc["display"]) <= {"via", "created_at", "updated_at", "expires_at",
                                       "plan", "nickname", "phone", "email"}


# ============ 写方法来源校验（M6-6 / R3-P4：CSRF 收敛）============

class TestWriteOriginGuard:
    """`/admin/api/*` 写方法的来源校验：挡跨源网页（CSRF），放行本机脚本（无 Origin）与同源页面。

    R3-P4 真 PoC 形态 = 从异源页面 `fetch(POST, no-cors)` 打免鉴权端点 → 服务端真实执行；
    本类逐条钉死修复口径（跨源 403 且零落库 / 同源与无 Origin 照常）。
    """

    async def test_cross_origin_write_403_and_nothing_persisted(self, vendor, make_gateway, client):
        """异源 Origin（同回环族、异端口 = R3 PoC 形态；及任意跨站域）→ 403 且不落库。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-o1", {"token": SECRET})
        evil = {"Origin": "http://127.0.0.1:9"}          # 同回环族、不同端口 → 不同源
        r = await client.post(f"{gw.base_url}/admin/api/accounts/buddy/acc-o1/disable",
                              json={}, headers=evil)
        assert r.status_code == 403, r.text
        assert "同源" in r.json()["detail"]               # 403 + 可读文案
        assert _meta_of("buddy", "acc-o1").get("enabled", True) is True   # 403 = 零落库
        assert store.load_credentials("buddy", "acc-o1") == {"token": SECRET}

        # 破坏性端点同样够不着（跨站域 Origin；不带 confirm 或带 confirm 都到不了业务层）
        for origin in ("http://evil.example.com", "http://127.0.0.1:8300"):
            r = await client.post(
                f"{gw.base_url}/admin/api/accounts/buddy/acc-o1/delete?confirm=1",
                json={}, headers={"Origin": origin})
            assert r.status_code == 403, (origin, r.text)
        assert store.has_account(store.product_root("buddy"), "acc-o1")

        # 读方法不受影响（来源校验只覆盖写方法；异源 GET 照常）
        r = await client.get(f"{gw.base_url}/admin/api/accounts", headers=evil)
        assert r.status_code == 200

    async def test_sec_fetch_site_cross_site_403_without_origin(self, vendor, make_gateway, client):
        """`Sec-Fetch-Site: cross-site` 一律拒（即便无 Origin）；`same-origin` 放行。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-o2", {"token": SECRET})
        r = await client.post(f"{gw.base_url}/admin/api/accounts/buddy/acc-o2/disable",
                              json={}, headers={"Sec-Fetch-Site": "cross-site"})
        assert r.status_code == 403, r.text
        assert _meta_of("buddy", "acc-o2").get("enabled", True) is True

        r = await client.post(f"{gw.base_url}/admin/api/accounts/buddy/acc-o2/disable",
                              json={}, headers={"Origin": gw.base_url,
                                                "Sec-Fetch-Site": "same-origin"})
        assert r.status_code == 200, r.text
        assert _meta_of("buddy", "acc-o2")["enabled"] is False

    async def test_same_origin_and_loopback_family_allowed(self, vendor, make_gateway, client):
        """同源 Origin（浏览器自身页面）与回环族互换（localhost ↔ 127.0.0.1，端口一致）放行。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-o3", {"token": SECRET})
        port = gw.base_url.rsplit(":", 1)[1]
        r = await client.post(f"{gw.base_url}/admin/api/accounts/buddy/acc-o3/disable",
                              json={}, headers={"Origin": f"http://localhost:{port}"})
        assert r.status_code == 200, r.text
        assert _meta_of("buddy", "acc-o3")["enabled"] is False

    async def test_no_origin_allowed_for_local_scripts(self, vendor, make_gateway, client):
        """无 Origin（curl / node 脚本 / CLI `admin_post`）→ 照常放行（不引入必填头）。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-o4", {"token": SECRET})
        r = await client.post(f"{gw.base_url}/admin/api/accounts/buddy/acc-o4/disable", json={})
        assert r.status_code == 200, r.text
        assert _meta_of("buddy", "acc-o4")["enabled"] is False

    async def test_origin_null_and_junk_rejected(self, vendor, make_gateway, client):
        """`Origin: null`（file:// 等）与畸形 Origin → 403（不算同源）。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-o5", {"token": SECRET})
        for origin in ("null", "not-a-url", "ftp://127.0.0.1", "http://127.0.0.1:99999999"):
            r = await client.post(f"{gw.base_url}/admin/api/accounts/buddy/acc-o5/disable",
                                  json={}, headers={"Origin": origin})
            assert r.status_code == 403, (origin, r.text)
        assert _meta_of("buddy", "acc-o5").get("enabled", True) is True

    async def test_admin_router_writes_also_guarded(self, vendor, make_gateway, client):
        """挂载面全覆盖：admin.py 自身写端点（PUT /admin/api/config）同样受来源校验。"""
        gw = await make_gateway(_cfg(vendor.port))
        before = Path(gw.config_path).read_bytes()
        r = await client.put(f"{gw.base_url}/admin/api/config", json={"models": "bad"},
                             headers={"Origin": "http://127.0.0.1:9"})
        assert r.status_code == 403, r.text
        assert Path(gw.config_path).read_bytes() == before      # 403 = 配置零改动
        # 同源 Origin → 放行到业务层（坏体由 Pydantic 400 拒绝，说明已越过来源校验）
        r = await client.put(f"{gw.base_url}/admin/api/config", json={"models": "bad"},
                             headers={"Origin": gw.base_url})
        assert r.status_code == 400, r.text


# ============ 批量续期（2026-10-01 用户裁决：产品维度 5h 窗口 + 登录态倒计时）============

class TestRefreshDue:
    async def test_refresh_due_window_and_view_field(self, vendor, make_gateway, client,
                                                     monkeypatch):
        """窗口判据 = `credexp` 解析的登录态失效时刻：5h 内到期才续，远期不列，未知不续；
        视图字段 `credential_expires_at` 与凭据里的毫秒值同刻（**响应零凭据**）。"""
        import time as _t

        from model_gateway.accounts import credexp

        gw = await make_gateway(_cfg(vendor.port))
        due_ms = int((_t.time() + 3600) * 1000)          # 1h 后失效 → 在 5h 窗口内
        far_ms = int((_t.time() + 10 * 86400) * 1000)    # 10d 后失效 → 不在窗口
        _seed("buddy", "acc-due", {"token": "OLD", "expires_at": str(due_ms)}, {})
        _seed("buddy", "acc-far", {"token": "OLD", "expires_at": str(far_ms)}, {})
        _seed("buddy", "acc-unknown", {"token": "OLD"}, {})

        # 视图字段：到期时刻出 ISO、未知出空串（不判定、不猜）
        view = await _view(client, gw)
        entries = {a["name"]: a for p in view["products"] if p["id"] == "buddy"
                   for a in p["accounts"]}
        assert credexp.credential_expires_at_iso({"expires_at": str(due_ms)}) \
            == entries["acc-due"]["credential_expires_at"]
        assert entries["acc-far"]["credential_expires_at"] != ""
        assert entries["acc-unknown"]["credential_expires_at"] == ""

        async def fake_refresh(cred, meta):
            return {"token": SECRET, "expires_at": str(int((_t.time() + 86400) * 1000))}
        monkeypatch.setitem(buddy._HOOKS, "refresh", fake_refresh)
        r = await _post(client, gw, "/admin/api/accounts/buddy/refresh-due", {})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["renewed"] == 1 and body["failed"] == 0
        assert body["skipped"]["no-expiry"] == 1
        assert body["skipped"]["cooldown"] == 0 and body["skipped"]["terminal"] == 0
        listed = {x["account"] for x in body["results"]}
        assert listed == {"acc-due", "acc-unknown"}, "远期账号不得进回执；未知失效时刻要如实列出"
        assert store.load_credentials("buddy", "acc-due")["token"] == SECRET
        assert store.load_credentials("buddy", "acc-far")["token"] == "OLD", "窗口外被误续"
        assert store.load_credentials("buddy", "acc-unknown")["token"] == "OLD", "未知被当成到期"
        assert SECRET not in r.text

    async def test_refresh_due_capability_gate_and_param_range(self, vendor, make_gateway,
                                                               client):
        """能力位 `refresh=False` → 400 前置拒绝（界面本就不渲染钮）；`within_hours` 只收数。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("loomy", "acc-nr", {"token": "OLD"}, {})
        r = await _post(client, gw, "/admin/api/accounts/loomy/refresh-due", {})
        assert r.status_code == 400 and "不可续期" in r.json()["error"]["message"]
        r = await _post(client, gw, "/admin/api/accounts/buddy/refresh-due",
                        {"within_hours": "abc"})
        assert r.status_code == 400 and "不是数" in r.json()["error"]["message"]
        r = await _post(client, gw, "/admin/api/accounts/buddy/refresh-due",
                        {"within_hours": 0})
        assert r.status_code == 400 and "范围" in r.json()["error"]["message"]


# ============ 「刷新额度」两条腿（2026-10-02 指令 2：账号维度 + 产品维度）============

class TestQuotaEndpoints:
    """`POST /admin/api/accounts/{p}/{name}/quota` 与 `POST .../quota-all` 的契约。

    真机门（`bianyiandhuanjing/scripts/verify_accounts_ui_live.py` 的 QL/QC 段）已经在浏览器里
    把这两颗钮各点通过一次并核过 Δtrace，那证的是**行为**；本段钉的是**回执算术**，
    尤其"三段计数必须穷举"那一条：9 个非 zcode 产品的失败腿 `reason=""`，
    按方案 §5-3 的字面枚举会同时掉出 N 和 J ⇒ "点了产品级刷新、回执三个 0"
    （本轮实现期抓到并修掉的偏差，见 `admin_accounts.py::_quota_receipt` 的 ⚠️ 段）。
    """

    def _stub_quota(self, monkeypatch, box: dict, seen: list | None = None):
        """把 buddy 的 `quota` 钩子换成可编程的假实现（无网络、形状仍是公共 `QuotaSnapshot`）。"""
        import dataclasses

        async def fake_quota(cred, meta):
            if seen is not None:
                seen.append(meta.get("account"))
            return dataclasses.replace(box["snap"])

        monkeypatch.setitem(buddy._HOOKS, "quota", fake_quota)
        return box

    async def test_account_quota_returns_reason_and_writes_cache(self, vendor, make_gateway,
                                                                client, monkeypatch):
        """账号级：类别 + 机器可读 `reason` 一起回，且快照落 `runtime.json`（界面下一轮读它）。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-q1", {"token": SECRET}, {})
        seen: list = []
        box = {"snap": QuotaSnapshot(state="available", source="buddy-credits",
                                     detail="剩余 100", remaining=100, plan="Pro")}
        self._stub_quota(monkeypatch, box, seen)

        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-q1/quota")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["category"] == "success" and body["reason"] == ""
        assert body["written"] is True and SECRET not in r.text
        assert seen == ["acc-q1"]                      # meta 通道经 `store.hook_meta` 组装
        cache = store.read_runtime("buddy", "acc-q1")["quota"]
        assert cache["state"] == "available" and cache["remaining"] == 100
        assert cache["reason"] == "" and "checked_at" in cache

        # 同一颗钮换成"熔断中"这一格：类别 inactive、`reason` 如实带出、**合并写不洗旧数值**
        box["snap"] = QuotaSnapshot(state="unknown", source="buddy-credits",
                                    detail="全局风控熔断中", reason="circuit")
        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-q1/quota")
        body = r.json()
        assert body["category"] == "inactive" and body["reason"] == "circuit"
        after = store.read_runtime("buddy", "acc-q1")["quota"]
        assert after["remaining"] == 100 and after["state"] == "unknown"

    async def test_quota_all_receipt_counts_blank_reason_as_not_fired(self, vendor,
                                                                     make_gateway, client,
                                                                     monkeypatch):
        """🔴 反证那条偏差：9 个非 zcode 产品的失败腿（`inactive + reason=""`）**必须进 J**。

        撤证 = 把 `not_fired` 改回"只数表内四档" ⇒ 本条三个数变成 0/0/0 而当场红。
        """
        gw = await make_gateway(_cfg(vendor.port))
        for name in ("acc-b1", "acc-b2", "acc-b3"):
            _seed("buddy", name, {"token": SECRET}, {})
        box = {"snap": QuotaSnapshot(state="unknown", source="buddy-credits",
                                     detail="积分余额查询失败（HTTP 401）")}
        self._stub_quota(monkeypatch, box)

        r = await _post(client, gw, "/admin/api/accounts/buddy/quota-all")
        assert r.status_code == 200, r.text
        rc = r.json()["receipt"]
        assert rc == {"refreshed": 0, "failed": 0, "not_fired": 3,
                      "not_participating": 0,
                      "by_reason": {"acc-b1": "", "acc-b2": "", "acc-b3": ""}}
        # 三段穷举（参与者一个都不许从回执里消失）
        assert rc["refreshed"] + rc["failed"] + rc["not_fired"] == 3

    async def test_quota_all_receipt_mixes_all_four_buckets(self, vendor, make_gateway,
                                                           client, monkeypatch):
        """四段一次配齐：N=取到事实（含 `no_plan`）· K=失败 · J=未发起 · **停用的号照样刷**。

        🔴 与领取腿的参与口径**不同**且是有意的：`run_once` 只有在调用方传 `enabled_of` 时才
        跳过停用账号（`runner.py:408/423`，§22.6「运营执行跳过停用」），而额度是**只读视图**——
        停用的号也要看得见还剩多少，否则"为什么停用它"失去依据。两个端点都不传 `enabled_of`
        （`admin_accounts.py:1003-1005/1042-1043`），本条把它钉成判据而不是注释。
        """
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-ok", {"token": SECRET}, {})
        _seed("buddy", "acc-noplan", {"token": SECRET}, {})
        _seed("buddy", "acc-circ", {"token": SECRET}, {})
        _seed("buddy", "acc-boom", {"token": SECRET}, {})
        _seed("buddy", "acc-off", {"token": SECRET}, {"enabled": False})

        want = {"acc-ok": QuotaSnapshot(state="available", source="buddy-credits",
                                        detail="剩余 9", remaining=9),
                "acc-noplan": QuotaSnapshot(state="unknown", source="buddy-credits",
                                            detail="上游返回空套餐列表", reason="no_plan"),
                "acc-circ": QuotaSnapshot(state="unknown", source="buddy-credits",
                                          detail="熔断中", reason="circuit"),
                "acc-off": QuotaSnapshot(state="available", source="buddy-credits",
                                         detail="停用号也有数", remaining=3),
                "acc-boom": QuotaSnapshot(state="unknown", source="buddy-credits",
                                          detail="不该被用到")}

        async def fake_quota(cred, meta):
            import dataclasses

            name = meta.get("account")
            if name == "acc-boom":
                raise RuntimeError("钩子炸了")
            return dataclasses.replace(want[name])

        monkeypatch.setitem(buddy._HOOKS, "quota", fake_quota)
        r = await _post(client, gw, "/admin/api/accounts/buddy/quota-all")
        assert r.status_code == 200, r.text
        rc = r.json()["receipt"]
        assert rc["refreshed"] == 3          # success(2，含停用的 acc-off) + no_plan(1)
        assert rc["failed"] == 1             # 钩子异常
        assert rc["not_fired"] == 1          # circuit
        assert rc["not_participating"] == 0  # 🔴 停用的号**不算**未参与（只读视图）
        assert rc["by_reason"]["acc-boom"] == ""
        assert rc["refreshed"] + rc["failed"] + rc["not_fired"] == 5   # 穷举
        assert store.read_runtime("buddy", "acc-off")["quota"]["remaining"] == 3

    async def test_quota_endpoints_bind_user_via_and_product(self, vendor, make_gateway,
                                                            client, monkeypatch):
        """两条腿都必须 `via="user"`（开关 `quota_net=false` 只管 cron）且 product 取自路径。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-v1", {"token": SECRET}, {})
        _seed("buddy", "acc-v2", {"token": SECRET}, {})
        calls: list = []

        from model_gateway.ops.builtin import query_balance as qb

        async def spy(product, account, *, manual=False, runtime=None,
                      via="cron", reasons_out=None):
            calls.append({"product": product, "account": account, "via": via,
                          "manual": manual})
            if reasons_out is not None:
                reasons_out[account] = ""
            from model_gateway.ops.result import OpResult

            return OpResult(account, "inactive", "哨兵：本用例只查闭包绑的参数")

        monkeypatch.setattr(qb, "run_for", spy)
        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-v1/quota")
        assert r.status_code == 200, r.text
        assert calls[0] == {"product": "buddy", "account": "acc-v1",
                            "via": "user", "manual": False}
        r = await _post(client, gw, "/admin/api/accounts/buddy/quota-all")
        assert r.status_code == 200, r.text
        assert {c["product"] for c in calls} == {"buddy"}
        assert {c["account"] for c in calls} == {"acc-v1", "acc-v2"}
        assert all(c["via"] == "user" for c in calls)

    async def test_quota_capability_false_is_preflight_400(self, vendor, make_gateway,
                                                          client, monkeypatch):
        """`balance=False` → 400 前置拒绝，**一次钩子都不发**（§22.6「能力矩阵是判据不是标签」）。

        ⚠️ 诚实标注：10 个产品今天 `balance` 全 True ⇒ 真机构造不出这一档，
        本条只做 monkeypatch 覆盖（真机门同理只能断"钮在位与能力位同相"）。
        """
        import dataclasses

        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "acc-cap", {"token": SECRET}, {})
        meta = account_registry.get("buddy")
        no_balance = dataclasses.replace(
            meta, capabilities=dataclasses.replace(meta.capabilities, balance=False))
        monkeypatch.setitem(account_registry.PRODUCTS, "buddy", no_balance)

        seen: list = []
        box = {"snap": QuotaSnapshot(state="available", source="buddy-credits", detail="x")}
        self._stub_quota(monkeypatch, box, seen)

        r = await _post(client, gw, "/admin/api/accounts/buddy/acc-cap/quota")
        assert r.status_code == 400 and "balance" in r.json()["error"]["message"]
        r = await _post(client, gw, "/admin/api/accounts/buddy/quota-all")
        assert r.status_code == 400 and "未发起" in r.json()["error"]["message"]
        assert seen == []                                   # 一条钩子都没发
        assert "quota" not in store.read_runtime("buddy", "acc-cap")
