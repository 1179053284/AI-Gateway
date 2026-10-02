"""`zcode` 产品钩子对齐单测（M6-3；tech-design §22.3/§22.4 + `12 §④` + `18 §②`）。

🔴 假上游（`httpx.MockTransport`）：**无网络、无真实凭据**。逐条对应取证判据：

- 设备流：`/oauth/cli/init` → 浏览器 → `/oauth/cli/poll/{flow_id}`（`12 §④` 一手；
  DSH `zcode-login.ts` 2026-09-29 实测：`poll_interval_sec=2`、`status=pending`），
  `pending` **不是错误**；`ready` 必须 `token` + `{provider}.access_token` + `user.user_id`
  **三件齐全**（缺件不得当成功）；服务端 `expires_at` 已过 → `expired`（不空转）；
  HTTP 4xx（除 408/429）→ `failed`；5xx / 网络抖动 → `pending`；
- 设备身份：新账号**跨账号唯一**（§15.1 硬约束 1）、重登录**原样复用**（硬约束 2）；
- 凭据落盘：钩子层 `LoginOutcome.credentials` + **客户端数据根**
  `<账号>/data/.zcode/v2/credentials.json`（既有领取/额度/启动路径读它）；
- `meta` 通道（§22.3 ③）：`quota`/`claim`/`probe` 的身份取 `meta["account"]`/`meta["dir"]`，
  `cred["account"]` 只作向后兼容回退；
- 探活：`billing/balance` 的二维判定（200 → 通过 / 401 → 凭据被拒 / 3012 → 如实报风控 /
  网络失败 → 不可达；熔断中**不发起**）；
- 静态白名单：只列**实测可用**的两条（§22.4「静态白名单起步」）。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from model_gateway.upstream.zcode import dataroot, oauth
from model_gateway.upstream.zcode import product as zcode
from model_gateway.upstream.zcode import quota as zq

# ============ 假上游 ============


class FakeUpstream:
    """按路径分发的假上游（`httpx.MockTransport` handler 的薄封装，同 cline 用例）。

    路由值 = `httpx.Response`（可复用）｜`list[Response]`（按调用次序消费，最后一个复用）
    ｜`Exception` 实例（抛出，模拟传输层失败）；未登记路径 → 404。
    """

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = dict(routes)
        self.calls: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        route = self.routes.get(request.url.path)
        if route is None:
            return httpx.Response(404, json={"code": -1, "msg": "no route"})
        if isinstance(route, list):
            route = route.pop(0) if len(route) > 1 else route[0]
        if isinstance(route, Exception):
            raise route
        assert isinstance(route, httpx.Response)
        return route

    def paths(self) -> list[str]:
        return [request.url.path for request in self.calls]

    def requests_for(self, path: str) -> list[httpx.Request]:
        return [request for request in self.calls if request.url.path == path]

    def json_of(self, path: str) -> dict:
        return json.loads(self.requests_for(path)[0].content.decode())

    def headers_of(self, path: str) -> httpx.Headers:
        return self.requests_for(path)[0].headers


def _patch_client(monkeypatch, upstream: FakeUpstream, module) -> None:
    """把被测模块的 `make_client` 换成本用例的假上游（产品钩子只经它建客户端）。"""

    def factory(*, base_url="", headers=None, timeout=None, follow_redirects=True):
        return httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler),
                                 base_url=base_url, headers=headers or {})

    monkeypatch.setattr(module, "make_client", factory)


def _session(name: str = "acct-new") -> SimpleNamespace:
    """会话替身：钩子只许经 `session.state` 存私态（轮询密钥不进 Challenge/Outcome）。

    ⚠️ `last_delivery` 不是给钩子用的 —— 引擎的 `_deliver` 会写它（落定处置的输入），
    钩子面不碰，但替身要有这个属性才不会在属性写入时炸。
    """
    return SimpleNamespace(state={}, name=name, product="zcode", last_delivery="")


INIT_PATH = oauth.CLI_INIT_PATH
POLL_PATH = oauth.CLI_POLL_PATH.format(flow_id="FLOW-1")
TOKEN_PATH = oauth.TOKEN_PATH
#: 服务端给的**原样**授权地址（带它自己的回跳参数 `redirect` —— 必须被剥掉）
SERVER_AUTHORIZE_URL = ("https://bigmodel.cn/login?appId=zcode"
                        "&redirect=https%3A%2F%2Fbigmodel.cn%2Fcb&state=s1")
#: 探活端点（基址 = 配置缺省时的官方 Plan 基址；测试不读配置 → 恒定值）
BALANCE_PATH = "/api/v1/zcode-plan" + zcode.PROBE_PATH

READY_BODY = {
    "code": 0,
    "data": {
        "status": "ready",
        "token": "JWT-1",
        "user": {"user_id": "u-1", "email": "dev@example.test", "name": "Dev"},
        "bigmodel": {"access_token": "BM-1", "refresh_token": "BM-R1"},
    },
}


def _init_route(expires_at: float | None = None, *,
                authorize_url: str = SERVER_AUTHORIZE_URL) -> httpx.Response:
    data: dict = {"flow_id": "FLOW-1",
                  "authorize_url": authorize_url,
                  "poll_token": "PT-1", "poll_interval_sec": 2}
    if expires_at is not None:
        data["expires_at"] = expires_at
    return httpx.Response(200, json={"code": 0, "data": data})


def _query(url: str) -> dict[str, str]:
    """URL 查询参数（解码后，同键取首个）—— 断言回跳参数用，不比对整串编码。"""
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


@pytest.fixture
def accounts_root(tmp_path, monkeypatch):
    root = tmp_path / "zcode-accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    return root


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """🔴 兜底：**未被本用例显式替换**的 `make_client` 一律当场失败（零网络纪律）。

    本文件所述的全部上游交互都经各模块的 `make_client`；忘打桩时在这里立刻红，
    而不是悄悄连上真实 `zcode.z.ai` —— `--basetemp` 隔离得了磁盘，隔离不了网络。
    """

    def _forbidden(*a, **k):
        raise AssertionError("测试禁止真实网络：请用 FakeUpstream 替换本模块的 make_client")

    monkeypatch.setattr(oauth, "make_client", _forbidden)
    monkeypatch.setattr(zcode, "make_client", _forbidden)
    monkeypatch.setattr("model_gateway.accounts.net.make_client", _forbidden)


def _write_account(root: Path, name: str, *, mid: str, jwt: str = "") -> Path:
    """造一个账号目录（meta.json [+ 客户端数据根的 credentials.json]）。"""
    account_dir = root / name
    (account_dir / "data" / ".zcode" / "v2").mkdir(parents=True)
    (account_dir / "meta.json").write_text(json.dumps({"device_mid": mid}), encoding="utf-8")
    if jwt:
        (account_dir / "data" / ".zcode" / "v2" / "credentials.json").write_text(
            json.dumps({"zcodejwttoken": jwt}), encoding="utf-8")
    return account_dir


# ============ 登录：设备流 pending → success ============


async def test_device_login_pending_then_success(monkeypatch, accounts_root):
    """🔴 `pending` **不是错误** → 之后 `ready` 落两处凭据（钩子层 + 客户端数据根）。"""
    upstream = FakeUpstream({
        INIT_PATH: _init_route(),
        POLL_PATH: [httpx.Response(200, json={"code": 0, "data": {"status": "pending"}}),
                     httpx.Response(200, json=READY_BODY)],
    })
    _patch_client(monkeypatch, upstream, oauth)
    session = _session("acct-new")

    challenge = await zcode.login_start(session)

    # 🔴 交给用户的那条地址：服务端自己的 `redirect` 已被换成官方桥接页（判据见
    #    `test_authorize_url_handed_to_the_user_is_the_bridge_form`）
    assert challenge.url.startswith("https://bigmodel.cn/login?")
    assert _query(challenge.url)["redirect"].startswith(
        "https://zcode.z.ai/app/oauth/login?redirect=zcode%3A%2F%2Foauth%2Fcallback")
    # 🔴 私态（flow_id / 轮询密钥）**绝不进 Challenge**（§22.3：Challenge 只承载用户可见物）
    assert challenge.device_code == "" and challenge.qr_payload == "" and not challenge.sms_sent
    flow = session.state["flow"]
    assert isinstance(flow, oauth.DeviceFlow) and flow.flow_id == "FLOW-1"
    assert flow.flow_secret and len(flow.flow_secret) == 64
    # 发起请求形状：Bearer 是**本次自生成的会话密钥**（不是用户凭据），body = {provider}
    assert upstream.json_of(INIT_PATH) == {"provider": "bigmodel"}
    assert upstream.headers_of(INIT_PATH)["Authorization"] == f"Bearer {flow.flow_secret}"

    first = await zcode.login_poll(session)
    assert first.state == "pending", "pending 是正常业务状态，不得当失败（§22.3）"

    done = await zcode.login_poll(session)

    assert done.state == "success" and done.detail
    assert done.credentials["zcodejwttoken"] == "JWT-1"
    assert done.credentials["oauth:active_provider"] == "bigmodel"
    assert done.credentials["oauth:bigmodel:access_token"] == "BM-1"
    assert done.credentials["oauth:bigmodel:refresh_token"] == "BM-R1"
    # 🔴 user_info 必须是 **JSON 字符串**：ops 的凭据解析 `json.loads()` 它取 user_id
    #    （`ops/builtin/zcode_claim._credentials_of`）—— 存对象会静默取不到（激活事件体必需）
    info = json.loads(done.credentials["oauth:bigmodel:user_info"])
    assert info["user_id"] == "u-1"
    assert done.meta["device_mid"] and done.meta["provider"] == "bigmodel"
    assert done.meta["display_name"] == "Dev" and done.meta["user_id"] == "u-1"

    # 客户端数据根落地（既有领取/额度/启动路径读它）+ 遥测通道 ②
    v2 = dataroot.v2_dir_of(accounts_root, "acct-new")
    assert json.loads((v2 / "credentials.json").read_text(encoding="utf-8")) == done.credentials
    tele = json.loads((v2 / "telemetry-state.json").read_text(encoding="utf-8"))
    assert tele["deviceMid"] == done.meta["device_mid"]
    # 只写该账号自己的数据根（§15.3 整根隔离）：账号根下只有这一个账号
    assert [p.name for p in accounts_root.iterdir()] == ["acct-new"]


async def test_device_login_poll_request_carries_flow_secret(monkeypatch, accounts_root):
    """轮询请求带**本流程的会话密钥**（不是用户凭据）——`12 §④` 一手口径。"""
    upstream = FakeUpstream({
        INIT_PATH: _init_route(),
        POLL_PATH: httpx.Response(200, json={"code": 0, "data": {"status": "pending"}}),
    })
    _patch_client(monkeypatch, upstream, oauth)
    session = _session()
    await zcode.login_start(session)
    await zcode.login_poll(session)

    flow = session.state["flow"]
    headers = upstream.headers_of(POLL_PATH)
    assert headers["Authorization"] == f"Bearer {flow.flow_secret}"
    assert headers["User-Agent"].startswith("ZCode/")


async def test_ready_without_the_three_fields_is_not_success(monkeypatch, accounts_root):
    """缺件（user_id / access_token）不得当成功——半个响应落盘会得到"登录了却调不通"的账号。"""
    upstream = FakeUpstream({
        INIT_PATH: _init_route(),
        POLL_PATH: httpx.Response(200, json={"code": 0, "data": {
            "status": "ready", "token": "JWT-1", "bigmodel": {"access_token": "BM-1"},
            "user": {"email": "no-id@example.test"}}}),
    })
    _patch_client(monkeypatch, upstream, oauth)
    session = _session()

    await zcode.login_start(session)
    out = await zcode.login_poll(session)

    assert out.state == "failed" and "user.user_id" in out.detail
    assert not (accounts_root / "acct-new" / "data").exists(), "失败时不得落半成品凭据"


async def test_server_side_expiry_short_circuits_polling(monkeypatch, accounts_root):
    """服务端 `expires_at` 已过 → `expired`，**不再打上游**（不空转，DSH `:378-381`）。"""
    upstream = FakeUpstream({INIT_PATH: _init_route(expires_at=1.0)})
    _patch_client(monkeypatch, upstream, oauth)
    session = _session()
    await zcode.login_start(session)

    out = await zcode.login_poll(session)

    assert out.state == "expired" and "过期" in out.detail
    assert upstream.paths() == [INIT_PATH], "过期后不得继续打轮询端点"


async def test_poll_4xx_is_terminal_failure_and_5xx_stays_pending(monkeypatch, accounts_root):
    """4xx（除 408/429）= 终态失败；5xx = 继续等（官方原式，DSH `:261-270`）。"""
    upstream = FakeUpstream({INIT_PATH: _init_route(), POLL_PATH: [
        httpx.Response(500, json={"msg": "boom"}),
        httpx.Response(403, json={"msg": "denied"}),
    ]})
    _patch_client(monkeypatch, upstream, oauth)
    session = _session()
    await zcode.login_start(session)

    assert (await zcode.login_poll(session)).state == "pending"
    out = await zcode.login_poll(session)
    assert out.state == "failed" and "403" in out.detail


async def test_poll_network_error_is_pending_not_failed(monkeypatch, accounts_root):
    """网络抖动不是失败（继续等，会话 TTL 兜底）——否则一次闪断就让用户白重来。"""
    upstream = FakeUpstream({
        INIT_PATH: _init_route(),
        POLL_PATH: httpx.ConnectError("net down"),
    })
    _patch_client(monkeypatch, upstream, oauth)
    session = _session()
    await zcode.login_start(session)

    out = await zcode.login_poll(session)

    assert out.state == "pending" and "抖动" in out.detail


async def test_status_failed_and_unknown_are_handled(monkeypatch, accounts_root):
    """`status=failed`（用户拒绝）与无法识别的状态都要显式收口（不拿未知当成功）。"""
    upstream = FakeUpstream({INIT_PATH: _init_route(), POLL_PATH: [
        httpx.Response(200, json={"code": 0, "data": {"status": "failed"}}),
        httpx.Response(200, json={"code": 0, "data": {"status": "weird"}}),
    ]})
    _patch_client(monkeypatch, upstream, oauth)
    session = _session()
    await zcode.login_start(session)

    assert (await zcode.login_poll(session)).state == "failed"
    out = await zcode.login_poll(session)
    assert out.state == "failed" and "weird" in out.detail


async def test_poll_without_flow_fails_closed(accounts_root):
    """没走过 `login_start` 的会话 → 显式失败（不复用别的会话态）。"""
    out = await zcode.login_poll(_session())
    assert out.state == "failed" and "login_start" in out.detail


async def test_init_failure_raises_with_status(monkeypatch, accounts_root):
    """发起失败 → 抛异常（引擎不吞异常，§22.8-5）；文案带 HTTP 事实。"""
    upstream = FakeUpstream({INIT_PATH: httpx.Response(503, json={"msg": "维护中"})})
    _patch_client(monkeypatch, upstream, oauth)
    with pytest.raises(RuntimeError, match="503"):
        await zcode.login_start(_session())


# ============ 设备身份（§15.1 两路径）============


async def test_new_login_gets_device_mid_unique_across_accounts(monkeypatch, accounts_root):
    """硬约束 1：新账号的设备码**跨账号唯一**（不得与既有账号撞）。"""
    _write_account(accounts_root, "acct-old", mid="MID-OLD")
    upstream = FakeUpstream({
        INIT_PATH: _init_route(),
        POLL_PATH: httpx.Response(200, json=READY_BODY),
    })
    _patch_client(monkeypatch, upstream, oauth)
    session = _session("acct-new")

    await zcode.login_start(session)
    out = await zcode.login_poll(session)

    assert out.state == "success"
    assert out.meta["device_mid"] not in ("", "MID-OLD")
    from model_gateway.upstream.zcode import store

    by_name = {a.name: a.device_id for a in store.list_accounts()}
    # 钩子层还没 commit（commit 由会话引擎做）→ 旧账号仍在、新码不与它撞
    assert by_name["acct-old"] == "MID-OLD"


async def test_relogin_reuses_existing_device_mid(monkeypatch, accounts_root):
    """硬约束 2：重登录**原样复用**已持久化的设备码（重登换码 = 上游眼里"换设备"）。"""
    _write_account(accounts_root, "acct-old", mid="MID-KEEP")
    upstream = FakeUpstream({
        INIT_PATH: _init_route(),
        POLL_PATH: httpx.Response(200, json=READY_BODY),
    })
    _patch_client(monkeypatch, upstream, oauth)
    session = _session("acct-old")

    await zcode.login_start(session)
    out = await zcode.login_poll(session)

    assert out.meta["device_mid"] == "MID-KEEP"


async def test_client_store_write_failure_is_reported_not_swallowed(
        monkeypatch, accounts_root):
    """客户端数据根写不动 → `failed` 并说明原因（不谎报成功、不留下"半可用"账号）。"""
    upstream = FakeUpstream({
        INIT_PATH: _init_route(),
        POLL_PATH: httpx.Response(200, json=READY_BODY),
    })
    _patch_client(monkeypatch, upstream, oauth)

    def _boom(*a, **k):
        raise OSError("read-only fs")

    monkeypatch.setattr(oauth, "write_client_credentials", _boom)
    session = _session("acct-new")
    await zcode.login_start(session)

    out = await zcode.login_poll(session)

    assert out.state == "failed" and "read-only fs" in out.detail
    assert out.credentials == {}


# ============ meta 通道（§22.3 ③）：quota / claim ============


def _log_dir(account_dir: Path) -> Path:
    logs = account_dir / "data" / ".zcode" / "v2" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs


def _log_record(used: int = 1_000_000, available: int = 2_000_000) -> str:
    return json.dumps({
        "providerId": "zai",
        "data": {"code": 0, "plans": [{"user_plan_id": "up-1", "plan_id": "start-plan",
                                      "status": "active", "name": "Start Plan"}],
                 "balances": [{"user_plan_id": "up-1", "show_name": "GLM-5.3",
                               "total_units": 3_000_000, "used_units": used,
                               "available_units": available, "period": "daily"}]},
    }, ensure_ascii=False)


def _write_log(account_dir: Path, *records: str) -> None:
    ( _log_dir(account_dir) / "2026-09-26.log").write_text(
        "\n".join("billing/balance 请求完成 " + r for r in records) + "\n", encoding="utf-8")


def test_offline_snapshot_reads_identity_from_account_dir(accounts_root):
    """**离线面**：`read_account_snapshot(root, account)` 读的是**该账号自己**的日志目录。

    🔴 2026-10-02 迁移（方案 §7-5「消费方迁移必须列账」）：本用例原先打的是
    `zcode.quota()` 钩子 —— 钩子已改走**联网腿**（`billing.fetch_balance`），
    再看日志就没意义了。同一个断言换钉离线面函数（它仍是 `/admin/api/zcode/quota`
    与启动种的实现），**fixture 形状一字未动**（红线保护形状，见 §8.1-1）。
    """
    good = _write_account(accounts_root, "acct-a", mid="MID-A")
    _write_account(accounts_root, "acct-b", mid="MID-B")
    _write_log(good, _log_record(used=1_500_000, available=1_500_000))

    snap = zq.read_account_snapshot(accounts_root, "acct-a")

    assert snap.ok is True and snap.plan == "Start Plan"
    assert snap.buckets[0].available == 1_500_000


def test_offline_snapshot_tolerates_records_without_payload_wrapper(accounts_root):
    """🔴 旧形状日志（顶层 `data`、无 `payload` 包）必须**原样可读**。

    `_unwrap_log_record` 的容错分支就是为这条存在的：实盘记录带 `payload`（见
    【探针台账】§4「两条通道被混成一条」那行），而**全部既有夹具**与本用例都是老形状 —— 剥层器若写死
    `payload.data`，这里会静默得零桶（"修了 B2 反而把好的通道改坏"，方案 §3-2 点名的坑）。
    """
    good = _write_account(accounts_root, "acct-old", mid="MID-OLD")
    _write_log(good, _log_record(used=3_000_000, available=0))

    snap = zq.read_account_snapshot(accounts_root, "acct-old")

    assert snap.ok is True
    assert snap.buckets[0].available == 0          # 上游给了 0 = 确实是 0，不是"没给"


async def test_quota_hook_fails_closed_without_identity_or_credentials(accounts_root):
    """联网腿的两条**不发起**早退（接 `test_registry.py` 钉的「既不编造也不打上游」）。

    两条都用 `httpx` 计数 = 0 断言"真的没发请求"，而不是只看返回值 ——
    只看 `state` 的话，"发了请求但失败"与"根本没发"在断言上长得一样（方案 §6 第 6/9 格）。
    """
    calls = []

    async def _boom(*a, **kw):
        calls.append((a, kw))
        raise AssertionError("不该发起网络请求")

    from model_gateway.upstream.zcode import billing

    orig = billing._http_get_balance
    billing._http_get_balance = _boom
    try:
        no_identity = await zcode.quota({}, {})
        assert no_identity.state == "unknown" and "账号名" in no_identity.detail
        assert no_identity.reason == "no_identity"       # 🔴 机器可读档（合并写白名单里就有它）

        _write_account(accounts_root, "acct-quiet", mid="")   # 有账号名、无设备码
        no_creds = await zcode.quota({"account": "acct-quiet"},
                                     {"account": "acct-quiet",
                                      "dir": str(accounts_root / "acct-quiet")})
        assert no_creds.state == "unknown" and no_creds.reason == "no_credentials"
    finally:
        billing._http_get_balance = orig
    assert calls == []                                   # 两条都**未发起**


def test_offline_snapshot_without_logs_is_not_ok(accounts_root):
    """离线面无日志 → `ok=False`（它**不**产 `reason`：兜底腿的数据不配有确定性结论）。"""
    _write_account(accounts_root, "acct-quiet", mid="MID-Q")
    snap = zq.read_account_snapshot(accounts_root, "acct-quiet")
    assert snap.ok is False and "无可用日志记录" in snap.note


async def test_claim_delegates_with_meta_identity(monkeypatch, accounts_root):
    """`claim` 委托既有 ops 实现，并把 **meta 通道解析出的账号名**交给它。"""
    from model_gateway.ops.base import OpResult
    from model_gateway.ops.builtin import zcode_claim

    seen: list[str] = []

    async def fake_claim(account, **_kw):
        seen.append(account)
        return OpResult(account, "already_done", "该套餐已领取过")

    monkeypatch.setattr(zcode_claim, "claim", fake_claim)
    account_dir = _write_account(accounts_root, "acct-meta", mid="MID-M")

    out = await zcode.claim({"account": "acct-other"},
                            {"account": "acct-meta", "dir": str(account_dir)}, precheck=True)

    assert seen == ["acct-meta"], "必须用 meta 通道的账号名（不是 cred 的）"
    assert out.category == "already_done" and "已领取过" in out.detail


async def test_claim_derives_account_from_dir_and_fails_closed(monkeypatch, accounts_root):
    """只有 `dir`（无 `account`）→ 目录名即账号名；两者都缺 → `failed`（不编造）。"""
    from model_gateway.ops.builtin import zcode_claim

    seen: list[str] = []

    async def fake_claim(account, **_kw):
        from model_gateway.ops.base import OpResult

        seen.append(account)
        return OpResult(account, "success", "已领取")

    monkeypatch.setattr(zcode_claim, "claim", fake_claim)

    account_dir = _write_account(accounts_root, "acct-by-dir", mid="MID-D")
    out = await zcode.claim({}, {"dir": str(account_dir)}, precheck=False)
    assert seen == ["acct-by-dir"] and out.category == "success"

    missing = await zcode.claim({}, {}, precheck=False)
    assert missing.category == "failed" and "账号名" in missing.detail


# ============ 探活（billing/balance 二维判定）============


def _probe_headers(root: Path, name: str) -> tuple[dict, dict]:
    account_dir = _write_account(root, name, mid=f"MID-{name}", jwt=f"JWT-{name}")
    return {}, {"account": name, "dir": str(account_dir)}


async def test_probe_ok_maps_two_dimensions(monkeypatch, accounts_root):
    """200 + `code=0` → 两维都真；请求走 `billing/balance` 且带 Bearer + X-Device-Mid。"""
    upstream = FakeUpstream({BALANCE_PATH: httpx.Response(200, json={"code": 0, "data": {}})})
    _patch_client(monkeypatch, upstream, zcode)
    cred, meta = _probe_headers(accounts_root, "acct-p")

    out = await zcode.probe(cred, meta)

    assert out.ok and out.reachable and out.valid
    req = upstream.requests_for(BALANCE_PATH)[0]
    assert req.headers["Authorization"] == "Bearer JWT-acct-p"
    assert req.headers["X-Device-Mid"] == "MID-acct-p"
    assert req.url.params["app_version"] == oauth.DEFAULT_APP_VERSION


async def test_probe_reads_credentials_from_cred_body_first(monkeypatch, accounts_root):
    """设备流登录的账号：`zcodejwttoken` 在**凭据本体**（客户端数据根可为空）。"""
    upstream = FakeUpstream({BALANCE_PATH: httpx.Response(200, json={"code": 0})})
    _patch_client(monkeypatch, upstream, zcode)
    account_dir = _write_account(accounts_root, "acct-cred", mid="MID-C")   # 无客户端凭据

    out = await zcode.probe({"zcodejwttoken": "JWT-CRED"},
                            {"account": "acct-cred", "dir": str(account_dir)})

    assert out.ok
    req = upstream.requests_for(BALANCE_PATH)[0]
    assert req.headers["Authorization"] == "Bearer JWT-CRED"


async def test_probe_401_is_reachable_but_invalid(monkeypatch, accounts_root):
    """401 → **连通但凭据被拒**（两维分开，§22.3）。"""
    upstream = FakeUpstream({BALANCE_PATH:
                             httpx.Response(401, json={"code": 1000, "msg": "unauthorized"})})
    _patch_client(monkeypatch, upstream, zcode)
    cred, meta = _probe_headers(accounts_root, "acct-401")

    out = await zcode.probe(cred, meta)

    assert out.reachable and not out.valid and not out.ok and "401" in out.detail


async def test_probe_200_but_unrecognizable_body_is_not_a_pass(monkeypatch, accounts_root):
    """🔴 200 但**看不出是余额响应**（WAF 页 / 业务码非 0 且无 data）→ 不得宣布凭据有效。"""
    upstream = FakeUpstream({BALANCE_PATH: [
        httpx.Response(200, text="<html>waf</html>"),
        httpx.Response(200, json={"code": 1000, "msg": "permission denied"}),
    ]})
    _patch_client(monkeypatch, upstream, zcode)
    cred, meta = _probe_headers(accounts_root, "acct-waf")

    first = await zcode.probe(cred, meta)
    # 🔴 两次探活之间有 10s 节流（§17：与领取路径共用）；本用例不想真等 → 删掉状态文件
    #    （「文件不存在 = 熔断/节流已解除」是既有口径，`CooldownManager._read_disk`）
    zq.circuit_path().unlink(missing_ok=True)
    second = await zcode.probe(cred, meta)

    assert first.reachable and not first.valid and "未确认" in first.detail
    assert second.reachable and not second.valid and "code=1000" in second.detail


async def test_probe_3012_is_reported_as_risk_control(monkeypatch, accounts_root):
    """3012（风控）→ 如实报出、**不重试**（`18 §③`；熔断的接线点在领取路径）。"""
    upstream = FakeUpstream({BALANCE_PATH:
                             httpx.Response(200, json={"code": 3012,
                                                       "msg": "unusual activity"})})
    _patch_client(monkeypatch, upstream, zcode)
    cred, meta = _probe_headers(accounts_root, "acct-risk")

    out = await zcode.probe(cred, meta)

    assert out.reachable and not out.valid and "3012" in out.detail
    assert len(upstream.calls) == 1, "命中风控不得重试"


async def test_probe_network_failure_and_missing_credentials(monkeypatch, accounts_root):
    """网络失败 → `reachable=False`；缺凭据/缺设备码 → **不发请求**（不猜）。"""
    upstream = FakeUpstream({BALANCE_PATH: httpx.ConnectError("down")})
    _patch_client(monkeypatch, upstream, zcode)
    cred, meta = _probe_headers(accounts_root, "acct-net")
    out = await zcode.probe(cred, meta)
    assert not out.reachable and not out.valid and "不可达" in out.detail

    before = len(upstream.calls)
    assert not (await zcode.probe({}, {"account": "nobody", "dir": str(accounts_root / "nobody")})).reachable
    account_dir = _write_account(accounts_root, "acct-nomid", mid="")
    assert not (await zcode.probe({"zcodejwttoken": "JWT"},
                                  {"account": "acct-nomid", "dir": str(account_dir)})).reachable
    assert len(upstream.calls) == before, "缺凭据/缺设备码时不得打上游"


async def test_probe_skips_upstream_while_circuit_is_active(monkeypatch, accounts_root):
    """🔴 全局熔断中**不发起**探活（与领取路径共用闸门，§17）；原因必须如实给出。"""
    upstream = FakeUpstream({BALANCE_PATH: httpx.Response(200, json={"code": 0})})
    _patch_client(monkeypatch, upstream, zcode)
    cred, meta = _probe_headers(accounts_root, "acct-breaker")
    zq.get_circuit().enter("ZCode 风控熔断（30min，全局）")

    out = await zcode.probe(cred, meta)

    assert not out.reachable and not out.valid
    assert "熔断" in out.detail and "未发起" in out.detail
    assert upstream.calls == [], "熔断中不得打上游"


# ============ 静态白名单（§22.4「静态白名单起步」）============


async def test_list_models_is_the_static_whitelist():
    """只列**实测可用**的两条；能力字段抄上游（不按"同族应该一样"推断）。"""
    models = await zcode.list_models({}, zcode.meta())

    assert [m.id for m in models] == ["GLM-5.3-Flash", "GLM-5.3"]
    by_id = {m.id: m for m in models}
    for model in models:
        assert model.context_window == 1_000_000 and model.max_output == 128_000
        assert model.effort_levels == ("low", "high", "max")
        assert model.reasoning is True
        assert model.tool_call is None, "上游不声明工具能力 → 取不到不编造（21 §5.1-1）"
    # 上游 capabilities.vision 只有 Flash 为 true（DSH zcode-product.ts:119-135）
    assert by_id["GLM-5.3-Flash"].image_input is True
    assert by_id["GLM-5.3"].image_input is False
    # 目录来源登记必须是 static（registry 唯一事实源，§22.4）
    assert zcode.meta().models_source == "static"


# ============ 接线登记与骨架纪律 ============


def test_implemented_declaration_matches_wired_hooks():
    """`_IMPLEMENTED` = 已接线钩子面。

    ⚠️ **M7-D 起 `login_callback` 已接线**（回跳**副通道**：接收端投递 / 地址栏粘贴 →
    `oauth.cli_exchange` → 与轮询**同一个** `_settle_login` 收尾）：
    原「非 local_callback 型 → 刻意不列、必须显式 NotImplementedError」的登记已过期 ——
    本产品主通道仍是服务端中介的轮询（`registry.login="device_code"` 未翻案），
    但参考实现的两条证据把它变成了双通道：`oauth.rs:1698-1706,1835-1898`
    （轮询与回跳**赛跑** + 「flow is still mine」守卫）与
    `ZCode-Panel/main.js:1978-1986`（捕获同时接受深链与桥接页）。
    接收端形状的唯一真相源是 `_CALLBACK` 声明表，断言见
    `tests/integration/test_m7_callback_capture.py::test_zcode_real_arrival_exchanges_and_commits`。

    ⚠️ `build_out` 自 **M6-5c** 起已接线（`upstream/zcode/out.py::ZcodeOut`）→
    原「M6-5 TODO」护栏**按波次转正**（处置同 M6-5b 各产品）：`_IMPLEMENTED` 与
    `_HOOKS` 都含它；正向接线断言见后面那条用例，行为判据在
    `tests/integration/test_zcode_out.py`。
    """
    assert set(zcode._IMPLEMENTED) == {
        "login_start", "login_poll", "login_callback", "refresh", "probe", "quota", "claim",
        "list_models", "build_out"}
    assert set(zcode._HOOKS) == {
        "meta", "login_start", "login_poll", "login_callback", "refresh", "probe",
        "quota", "claim", "list_models", "build_out"}


async def test_callback_without_flow_fails_closed_and_hits_no_upstream(
        monkeypatch, accounts_root):
    """🔴 副通道同一条纪律：会话里没有流程 → `failed`，**一个上游请求都不发**。

    `accounts_root` + `_no_network` 是拦阻点：真打 `/oauth/token` 会当场红在替身上。
    """
    upstream = FakeUpstream({})
    _patch_client(monkeypatch, upstream, oauth)

    out = await zcode.login_callback(_session(), {"url": _zcode_callback_url(state="s1")})

    assert out.state == "failed" and "login_start" in out.detail
    assert upstream.calls == []


async def test_build_out_is_wired_to_the_zcode_adapter():
    """`build_out` 自 M6-5c 起接线（原 M6-5 TODO 护栏在此**按波次转正**）：
    返回 anthropic 族出站适配器 `ZcodeOut`（契约属性 + 产品标识就位）。

    行为判据（Plan/JWT 头锚点 / 验证码注入缝 / 错误映射 / 端到端）在
    `tests/integration/test_zcode_out.py`；本用例只钉「接线本身成立」。
    """
    from model_gateway.adapters.product_out import ProductAccount
    from model_gateway.upstream.zcode.out import ZcodeOut

    account = ProductAccount(product=zcode.PRODUCT, name="acc-1",
                             base_url="https://zcode.z.ai/api/v1/zcode-plan/anthropic")
    adapter = zcode.build_out(account)
    try:
        assert isinstance(adapter, ZcodeOut)
        assert (adapter.product, adapter.account_ref) == ("zcode", "acc-1")
        assert adapter.protocol == "anthropic"
        assert adapter.base_url == "https://zcode.z.ai/api/v1/zcode-plan/anthropic"
    finally:
        await adapter.aclose()


# ============ 协议层（oauth.parse_cli_init）============


def test_parse_cli_init_rejects_incomplete_payload():
    """缺 `flow_id` / 非 https 的 `authorize_url` → ValueError（**不猜、不返回半成品流程**）。"""
    with pytest.raises(ValueError, match="flow_id"):
        oauth.parse_cli_init({"code": 0, "data": {"authorize_url": "https://x/y"}})
    with pytest.raises(ValueError, match="authorize_url"):
        oauth.parse_cli_init({"code": 0, "data": {"flow_id": "f1", "authorize_url": "zcode://cb"}})


def test_parse_cli_init_defaults_and_bad_interval():
    """`poll_interval_sec` <1 / 非数字 → 兜底 2s；`expires_at` 非数字 → 0（= 不设本地截止）。"""
    flow = oauth.parse_cli_init({"data": {"flow_id": "f1",
                                          "authorize_url": "https://a/b?state=s",
                                          "poll_interval_sec": 0, "expires_at": "soon"}})
    assert flow.poll_interval_s == oauth.DEFAULT_POLL_INTERVAL_S
    assert flow.expires_at == 0.0 and not flow.expired()


# ============ 🔴 M7-D 需求①：授权地址改写 + state 取源（本轮缺陷本身）============


def test_authorize_url_handed_to_the_user_is_the_bridge_form():
    """🔴 **钉住本轮缺陷本身**（M7-D 需求 ①，参考 `oauth.rs:127-149`）：

    交给用户的那条 `authorize_url` 里，回跳参数必须是**官方桥接页**
    （`https://zcode.z.ai/app/oauth/login?redirect=zcode%3A%2F%2Foauth%2Fcallback&app_version=<ver>`），
    并且 `state` 必须是**从服务端给的 URL 里取到的**那个（不本地生成）。

    撤掉 `parse_cli_init` 里的改写与取源（把 `authorize_url` 原样返回、`state=""`）
    → 本用例两条断言**同时红**，红证输出见交付说明。
    """
    flow = oauth.parse_cli_init(
        {"code": 0, "data": {"flow_id": "f1", "authorize_url": SERVER_AUTHORIZE_URL,
                             "poll_interval_sec": 2}},
        provider="bigmodel")

    params = _query(flow.authorize_url)
    # ① 回跳参数已被换成桥接页（服务端原来那条 `redirect=https://bigmodel.cn/cb` 不再存在）
    assert params["redirect"] == ("https://zcode.z.ai/app/oauth/login"
                                  "?redirect=zcode%3A%2F%2Foauth%2Fcallback"
                                  f"&app_version={oauth.DEFAULT_APP_VERSION}"), params
    assert "bigmodel.cn/cb" not in flow.authorize_url
    # ② state 来自服务端 URL
    assert flow.state == "s1"


def test_rewrite_strips_only_the_provider_redirect_param():
    """剥哪一个是**按 provider 定**的（`oauth.rs:129-131`）：bigmodel=`redirect`、
    zai=`redirect_uri`；其余参数原序保留，未在册的 provider 一律不动（不猜参数名）。"""
    bigmodel = oauth.rewrite_authorize_url(
        "https://bigmodel.cn/login?appId=zcode&state=S&redirect=https%3A%2F%2Fold%2Fcb",
        "bigmodel")
    assert list(_query(bigmodel)) == ["appId", "state", "redirect"]     # 原序 + 追加在末尾
    assert _query(bigmodel)["appId"] == "zcode" and _query(bigmodel)["state"] == "S"
    assert _query(bigmodel)["redirect"].startswith("https://zcode.z.ai/app/oauth/login?")

    zai = oauth.rewrite_authorize_url(
        "https://chat.z.ai/api/oauth/authorize?response_type=code&client_id=c"
        "&state=S&redirect_uri=https%3A%2F%2Fold%2Fcb", "zai")
    assert list(_query(zai)) == ["response_type", "client_id", "state", "redirect_uri"]
    assert _query(zai)["redirect_uri"].startswith("https://zcode.z.ai/app/oauth/login?")

    assert oauth.rewrite_authorize_url("https://x/y?redirect=r", "who-knows") \
        == "https://x/y?redirect=r"


def test_parse_cli_init_requires_a_state_from_the_server():
    """服务端 URL 里没有 `state` → 整条流程判非法（`oauth.rs:150-157`）。

    本地造一个 state 是**更糟**的选项：服务端不认它，回跳换取 token 必然被拒，
    而界面已经把授权页打开了 —— 用户白点一次授权才知道。
    """
    with pytest.raises(ValueError, match="state"):
        oauth.parse_cli_init({"code": 0, "data": {
            "flow_id": "f1", "authorize_url": "https://bigmodel.cn/login?appId=zcode"}})


def test_the_state_we_match_against_is_the_servers_own():
    """🔴 钉住「state 取源」本身（协议层）：解析结果里的 state 必须是服务端 URL 的那个。

    为什么单独立一条：`test_subchannel_state_mismatch_never_reaches_the_upstream` 只钉住
    "不符就拒"。若实现改成**本地自造** state（`uuid4()` 之类），那条测试照样绿 ——
    伪造的回跳仍与本地值不符、仍被拒。但真实回跳带的是服务端的 `s1`，于是用户正常授权
    会被自己的接收端挡在门外（设备流轮询仍可能救回来，回跳副通道则永远 400）。
    本条把"取源"变成可证伪的判据。
    """
    flow = oauth.parse_cli_init({"code": 0, "data": {
        "flow_id": "FLOW-1", "authorize_url": SERVER_AUTHORIZE_URL,
        "poll_token": "PT-1", "poll_interval_sec": 2}})
    assert flow.state == "s1", f"state 必须取自服务端 URL，实得 {flow.state!r}"


async def test_login_start_publishes_the_servers_state_as_the_match_basis(
        monkeypatch, accounts_root):
    """会话私态里的 `state` = 接收端的比对基准（`_CALLBACK.secret_state_key`），
    必须是服务端下发的那个，且**不出现在 Challenge 里**（回跳关联串不是给用户看的）。"""
    upstream = FakeUpstream({INIT_PATH: _init_route(),
                             TOKEN_PATH: httpx.Response(200, json=_token_body())})
    _patch_client(monkeypatch, upstream, oauth)
    session = _session("acct-state")
    await zcode.login_start(session)

    assert session.state["state"] == "s1", session.state.get("state")
    challenge = session.state.get("challenge") or {}
    assert "s1" not in repr(challenge), "关联串不得外泄到 Challenge"
    # 正向闭环：带服务端那个 state 的回跳被接受（打到 /oauth/token），
    # 与 `test_subchannel_state_mismatch_never_reaches_the_upstream` 互为反向对照。
    out = await zcode.login_callback(session, {"url": _zcode_callback_url(state="s1")})
    assert out.state == "success", out.detail
    assert upstream.paths() == [INIT_PATH, TOKEN_PATH]


def test_parse_cli_init_rejects_an_interval_that_cannot_be_honoured():
    """轮询间隔 ≥ 流程剩余时间 = 永远轮不到结果 → 判非法（`oauth.rs:164`）。

    ⚠️ 与"服务端说已过期"是两回事：后者是一条**正常**响应配一条已死的流程，
    正确结局是 `expired`（`test_server_side_expiry_short_circuits_polling`），不是 ValueError。
    """
    now = 1_800_000_000.0
    with pytest.raises(ValueError, match="轮询间隔"):
        oauth.parse_cli_init({"code": 0, "data": {
            "flow_id": "f1", "authorize_url": "https://a/b?state=s",
            "expires_at": now + 1, "poll_interval_sec": 5}}, now_s=now)
    # 剩余时间比间隔长 → 采纳服务端下发的间隔
    ok = oauth.parse_cli_init({"code": 0, "data": {
        "flow_id": "f1", "authorize_url": "https://a/b?state=s",
        "expires_at": now + 120, "poll_interval_sec": 5}}, now_s=now)
    assert ok.poll_interval_s == 5.0


def test_parse_cli_init_honours_the_server_date_for_the_ttl():
    """🔴 时钟偏移安全的 TTL（`oauth.rs:56-72`）：`expires_at` 与 HTTP `Date` **共用服务端时钟**，
    可信的是**两者之差**；本机快 10 分钟时不得把一条还有 3 分钟的流程判成已过期。
    """
    server_now = 1_800_000_000.0
    local_now = server_now - 600.0                    # 本机慢 10 分钟（等价于服务端快 10 分钟）
    flow = oauth.parse_cli_init({"code": 0, "data": {
        "flow_id": "f1", "authorize_url": "https://a/b?state=s",
        "expires_at": server_now + 180, "poll_interval_sec": 2}},
        server_date_s=server_now, now_s=local_now)

    assert flow.expired(now_s=local_now) is False                 # 没被误判成过期
    assert flow.expires_at == pytest.approx(local_now + 180.0)    # 相对 TTL = 服务端差值
    assert flow.expired(now_s=local_now + 181) is True

    # 服务端 Date 与 expires_at 都说已过 → 立即过期（不空转）
    dead = oauth.parse_cli_init({"code": 0, "data": {
        "flow_id": "f1", "authorize_url": "https://a/b?state=s",
        "expires_at": server_now - 1, "poll_interval_sec": 2}},
        server_date_s=server_now, now_s=local_now)
    assert dead.expired(now_s=local_now) is True

    # Date 与 expires_at 差值离谱（> 2×5 分钟）→ 退回文档化的 5 分钟流程
    skewed = oauth.parse_cli_init({"code": 0, "data": {
        "flow_id": "f1", "authorize_url": "https://a/b?state=s",
        "expires_at": server_now + 86_400, "poll_interval_sec": 2}},
        server_date_s=server_now, now_s=local_now)
    assert skewed.expires_at == pytest.approx(local_now + oauth.FLOW_TIMEOUT_S)


# ============ 🔴 M7-D 需求②：全套客户端头 + 设备码前置 ============


async def test_init_and_poll_send_the_full_client_header_set(monkeypatch, accounts_root):
    """`cli/init` 与 `cli/poll` 都发**整套** z.ai 客户端头（`quota.rs:171-196`）。

    此前两处各只发五六个头（`X-Title`/`X-Release-Channel`/`X-Client-Timezone`/
    `X-Os-Category`/`X-Os-Version`/`X-Device-Mid`/`x-request-id` 全缺），且 `X-Device-Mid`
    要等轮询成功后才算（`product.py` 旧 `:232`）—— 上游据此看到的是"一个不像 ZCode 的客户端"。
    🔴 本用例同时钉住**需求②的可观察面**：设备码在 `login_start` 里定案后，
    init 与 poll 两次请求上的 `X-Device-Mid` 必须**已经是它**。
    """
    upstream = FakeUpstream({
        INIT_PATH: _init_route(),
        POLL_PATH: httpx.Response(200, json={"code": 0, "data": {"status": "pending"}}),
    })
    _patch_client(monkeypatch, upstream, oauth)
    session = _session("acct-hdr")

    await zcode.login_start(session)
    await zcode.login_poll(session)

    flow = session.state["flow"]
    required = {"Authorization", "User-Agent", "HTTP-Referer", "X-Title",
                "X-ZCode-App-Version", "X-Platform", "X-Release-Channel",
                "X-Client-Language", "X-Client-Timezone", "X-Os-Category",
                "X-Device-Mid", "x-request-id"}
    for path in (INIT_PATH, POLL_PATH):
        headers = upstream.headers_of(path)
        missing = sorted(k for k in required if not (headers.get(k) or "").strip())
        assert not missing, f"{path} 缺客户端头：{missing}"
        assert headers["X-Title"] == "Z Code@electron"
        assert headers["X-Release-Channel"] == "stable"
        assert headers["X-ZCode-App-Version"] == oauth.DEFAULT_APP_VERSION
        assert headers["User-Agent"] == f"ZCode/{oauth.DEFAULT_APP_VERSION}"
        assert headers["HTTP-Referer"] == oauth.ZCODE_ORIGIN
        # 🔴 两次请求同一个设备码，且就是最终进 `meta["device_mid"]` 的那个
        assert headers["X-Device-Mid"] == flow.device_mid == session.state["device_mid"]
    assert upstream.headers_of(INIT_PATH)["Authorization"] \
        == upstream.headers_of(POLL_PATH)["Authorization"] \
        == f"Bearer {flow.flow_secret}", "Bearer 必须是本次自生成的会话密钥"
    assert upstream.headers_of(INIT_PATH)["x-request-id"] \
        != upstream.headers_of(POLL_PATH)["x-request-id"], "每次请求一个新 request id"


async def test_device_mid_is_fixed_before_the_flow_and_carried_into_meta(
        monkeypatch, accounts_root):
    """🔴 设备码时序（需求②）：**发起之前**定案 → init/poll 都带 → 落盘的 `meta` 同一个值。

    反向判据：`X-Device-Mid` 若仍像修前那样"轮询成功后才算"，`login_start` 之后的
    那条 init 请求就没有该头（`missing` 会包含它）→ 本用例红。
    """
    upstream = FakeUpstream({
        INIT_PATH: _init_route(),
        POLL_PATH: httpx.Response(200, json=READY_BODY),
    })
    _patch_client(monkeypatch, upstream, oauth)
    session = _session("acct-mid")

    await zcode.login_start(session)
    mid_at_start = session.state["device_mid"]
    assert mid_at_start and upstream.headers_of(INIT_PATH)["X-Device-Mid"] == mid_at_start

    done = await zcode.login_poll(session)

    assert done.state == "success" and done.meta["device_mid"] == mid_at_start
    tele = json.loads((dataroot.v2_dir_of(accounts_root, "acct-mid")
                       / "telemetry-state.json").read_text(encoding="utf-8"))
    assert tele["deviceMid"] == mid_at_start
    # 🔴 定案之后不再重算：第二次轮询打的还是同一个码（两次上游请求同身份）
    assert upstream.headers_of(POLL_PATH)["X-Device-Mid"] == mid_at_start


# ============ 🔴 M7-D 需求③：回跳副通道 ============


def _zcode_callback_url(state: str = "s1", code: str = "CODE-CB-1") -> str:
    """一条**本机接收端重建**的回跳（`callback_server` 交来的就是这形状）。"""
    return (f"http://127.0.0.1:54321{oauth.CALLBACK_PATH}"
            f"?authCode={code}&state={state}")


def _token_body() -> dict:
    return {"code": 0, "data": {
        "token": "JWT-CB",
        "bigmodel": {"access_token": "BM-CB", "refresh_token": "BM-CB-R"},
        "user": {"user_id": "u-cb", "name": "回调用户"}}}


async def test_callback_channel_lands_the_same_credentials_as_the_poll(
        monkeypatch, accounts_root):
    """副通道换取成功 → 与轮询**同一份凭据 map**、同一个设备码、同一处客户端数据根。

    判据点：`POST /oauth/token` 的 body 必须带 `redirect_uri` = 桥接页地址
    （`oauth.rs:376-383`：换 token 时 `redirect_uri` 要与授权时**逐字一致**，否则被拒）。
    """
    upstream = FakeUpstream({
        INIT_PATH: _init_route(),
        TOKEN_PATH: httpx.Response(200, json=_token_body()),
    })
    _patch_client(monkeypatch, upstream, oauth)
    session = _session("acct-cb")
    await zcode.login_start(session)

    out = await zcode.login_callback(session, {"url": _zcode_callback_url()})

    assert out.state == "success", out.detail
    assert out.credentials == oauth.credential_map(
        provider="bigmodel", jwt="JWT-CB", access_token="BM-CB",
        refresh_token="BM-CB-R", user_info={"user_id": "u-cb", "name": "回调用户"})
    assert out.meta["device_mid"] == session.state["device_mid"]
    assert out.meta["user_id"] == "u-cb" and out.meta["display_name"] == "回调用户"
    v2 = dataroot.v2_dir_of(accounts_root, "acct-cb")
    assert json.loads((v2 / "credentials.json").read_text(encoding="utf-8")) == out.credentials
    body = upstream.json_of(TOKEN_PATH)
    assert body["code"] == "CODE-CB-1" and body["state"] == "s1"
    assert body["provider"] == "bigmodel"
    assert _query(body["redirect_uri"])["redirect"] == oauth.DEEP_LINK_PREFIX
    # 🔴 官方这条线**不带** Authorization（`oauth.rs:370-375` 逐字跳过该头）
    assert "authorization" not in upstream.headers_of(TOKEN_PATH)


async def test_callback_channel_accepts_the_flat_and_bridge_forms(monkeypatch, accounts_root):
    """三种投递形态同一判据（`Panel main.js:1978-1986`）：深链 / 桥接页 / 平铺 code+state。"""
    forms = [
        {"url": "zcode://oauth/callback?authCode=C-DEEP&state=s1"},
        {"url": "https://zcode.z.ai/app/oauth/login?code=C-BRIDGE&state=s1&utm_source=ad"},
        {"code": "C-FLAT", "state": "s1"},
    ]
    for form in forms:
        upstream = FakeUpstream({INIT_PATH: _init_route(),
                                 TOKEN_PATH: httpx.Response(200, json=_token_body())})
        _patch_client(monkeypatch, upstream, oauth)
        session = _session("acct-form")
        await zcode.login_start(session)

        out = await zcode.login_callback(session, form)

        assert out.state == "success", f"{form} → {out.detail}"
        assert upstream.json_of(TOKEN_PATH)["code"].startswith("C-")


async def test_subchannel_state_mismatch_never_reaches_the_upstream(
        monkeypatch, accounts_root):
    """🔴 `state` 不符 = 不是本次登录的回跳 → `failed` 且**不打上游**（不打一次注定被拒的换 token）。"""
    upstream = FakeUpstream({INIT_PATH: _init_route(),
                             TOKEN_PATH: httpx.Response(200, json=_token_body())})
    _patch_client(monkeypatch, upstream, oauth)
    session = _session("acct-forge")
    await zcode.login_start(session)

    out = await zcode.login_callback(session, {"url": _zcode_callback_url(state="FORGED")})

    assert out.state == "failed" and "不匹配" in out.detail
    assert upstream.paths() == [INIT_PATH], "串线的回跳不许打到 /oauth/token"
    assert not (accounts_root / "acct-forge").exists(), "失败不得落半成品凭据"


def test_parse_callback_url_accepts_every_shape_and_flags_attribution():
    """回跳解析器（协议层）：`authCode` 优先 `code` 兜底；只带归因参数要**认得出来**。"""
    deep = oauth.parse_callback_url("zcode://oauth/callback?code=C1&authCode=C2&state=S")
    assert (deep.code, deep.state) == ("C2", "S"), "官方 `authCode ?? code` 的优先级"
    bridge = oauth.parse_callback_url("https://zcode.z.ai/app/oauth/login?code=C1&state=S")
    assert (bridge.code, bridge.state) == ("C1", "S")
    loop = oauth.parse_callback_url(f"http://127.0.0.1:9/{oauth.CALLBACK_PATH}?code=C&state=S")
    assert (loop.code, loop.state) == ("C", "S")
    attr = oauth.parse_callback_url("https://zcode.z.ai/app/oauth/login?utm_source=ad")
    assert attr.attribution_only and not attr.code
    assert oauth.parse_callback_url("") .code == ""
    assert oauth.parse_callback_url("https://x/y?code=C").state == ""


# ============ 🔴 M7-D 需求④：轮询语义补口 ============


async def test_poll_business_code_3004_is_expired_not_pending(monkeypatch, accounts_root):
    """服务端 `code=3004`（流程已作废）→ `expired`（`oauth.rs:201-205`），**不是**继续空等。"""
    upstream = FakeUpstream({
        INIT_PATH: _init_route(),
        POLL_PATH: [httpx.Response(200, json={"code": 3004, "msg": "flow expired"}),
                    httpx.Response(404, json={"code": "3004", "msg": "flow gone"})],
    })
    _patch_client(monkeypatch, upstream, oauth)
    session = _session()
    await zcode.login_start(session)

    first = await zcode.login_poll(session)
    assert first.state == "expired" and "3004" in first.detail
    # 业务码是**字符串**形态也要认（上游两种形态都见过）
    assert (await zcode.login_poll(session)).state == "expired"


async def test_poll_408_and_429_stay_pending(monkeypatch, accounts_root):
    """408/429 是"暂时不行"，与其余 4xx 的终态拒绝**必须分开**（`oauth.rs:191-200`）。"""
    upstream = FakeUpstream({
        INIT_PATH: _init_route(),
        POLL_PATH: [httpx.Response(408, json={"msg": "timeout"}),
                    httpx.Response(429, json={"msg": "slow down"}),
                    httpx.Response(400, json={"msg": "bad request"})],
    })
    _patch_client(monkeypatch, upstream, oauth)
    session = _session()
    await zcode.login_start(session)

    assert (await zcode.login_poll(session)).state == "pending"
    assert (await zcode.login_poll(session)).state == "pending"
    assert (await zcode.login_poll(session)).state == "failed"



def test_credential_map_keys_are_the_client_ones():
    """凭据 map 的键名与官方客户端一致（读写同源：`build_credentials` 能解出 jwt/api_key）。"""
    creds = oauth.credential_map(provider="zai", jwt="J", access_token="A",
                                 refresh_token="R", user_info={"id": "u"})

    assert set(creds) == {"oauth:active_provider", "zcodejwttoken",
                          "oauth:zai:access_token", "oauth:zai:refresh_token",
                          "oauth:zai:user_info"}
    built = oauth.build_credentials(creds)
    assert (built.jwt, built.api_key, built.provider) == ("J", "A", "zai")
