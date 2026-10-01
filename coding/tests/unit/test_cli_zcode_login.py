"""`mgw zcode login` 设备授权流的 CLI 层判据（§17 / `12 §④`；W3-D 协议层接线）。

🔴 **无网络**：假上游（`httpx.MockTransport`）替换 `oauth.make_client`；未打桩时当场红
（与 `tests/accounts/test_zcode.py` 同一纪律）。`_wait` 注入缝把轮询间隔压成零时延，
同时记录每次等待秒数 —— 判据"间隔照 `oauth.py` 既有常量"由此可断言。

判据逐条：
- init → 打印**授权地址** + **设备码**（device_mid）+「在浏览器打开」指引；
- 轮询 pending 打点（含剩余时间）→ ready → 落账号 + 写客户端数据根（与 UI 向导同路径）；
- init 失败 / 授权被拒 / 流程过期 / 本地等待超时 → 退出码 1、零落盘；
- 账号名白名单（非法 → 退出码 1 且**不打上游**）；缺省名 = `zcode-<hex4>`；
- 重登录**复用既有设备码**（§15.1 硬约束 2）；
- `--help` 文案 = 设备流说明 + 退出码 0/1 + `--name`/`--provider`（旧"需浏览器/import"指引已下线）。
"""

from __future__ import annotations

import json
import re
import time

from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest

from model_gateway import cli_zcode
from model_gateway.accounts import login as accounts_login
from model_gateway.accounts import store as accounts_store
from model_gateway.cli import main
from model_gateway.upstream.zcode import dataroot, oauth

#: 🔴 **服务端给的原样**授权地址（M7-D 之前 CLI 直接把这串交给用户 = 缺陷本身：
#: 它自带的 `redirect` 指向厂商回调，授权完成后永远到不了捕获方。现在打印的是
#: 剥掉 `redirect`、重挂官方桥接页之后的那条 —— 判据见
#: `test_login_pending_then_success_commits_account_and_client_store`）
AUTHORIZE_URL = ("https://bigmodel.cn/login?appId=zcode"
                 "&redirect=https%3A%2F%2Fbigmodel.cn%2Fcb&state=s1")


def bridge_redirect_params(url: str) -> dict[str, list[str]]:
    """取那条 URL 的**回跳参数**，并把它的值（官方桥接页）按自己的 query 拆开。

    两步是必要的：外层 `redirect=` 的值是**一层百分号编码**的 URL（里面的 `?`/`&`/`=`
    都是 `%3F`/`%26`/`%3D`），直接对整串 `parse_qs` 会把内外两层一次解完而拆错归属
    （实测：对编码值 `parse_qs` 直接返回 `{}` —— 因为没有字面 `&`/`=` 可切）。
    """
    for chunk in urlsplit(url).query.split("&"):
        key, _, value = chunk.partition("=")
        if key == "redirect":
            return parse_qs(urlsplit(unquote(value)).query, keep_blank_values=True)
    return {}




class FakeUpstream:
    """按路径分发的假上游（`httpx.MockTransport` handler 的薄封装）。

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


def _patch_upstream(monkeypatch, upstream: FakeUpstream) -> None:
    """把 `oauth` 的 `make_client` 换成本用例的假上游（协议层唯一建客户端处）。"""

    def factory(*, base_url="", headers=None, timeout=None, follow_redirects=True):
        return httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler),
                                 base_url=base_url, headers=headers or {})

    monkeypatch.setattr(oauth, "make_client", factory)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """兜底：**未被本用例显式替换**的 `make_client` 一律当场失败（零网络纪律）。"""

    def _forbidden(*a, **k):
        raise AssertionError("测试禁止真实网络：请用 FakeUpstream 替换 oauth.make_client")

    monkeypatch.setattr(oauth, "make_client", _forbidden)
    monkeypatch.setattr("model_gateway.accounts.net.make_client", _forbidden)


@pytest.fixture(autouse=True)
def poll_waits(monkeypatch) -> list[float]:
    """轮询等待注入缝：零时延 + 记录间隔（断言"间隔照既有常量"）。"""
    waits: list[float] = []

    async def fake_wait(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(cli_zcode, "_wait", fake_wait)
    return waits


@pytest.fixture
def accounts_root(tmp_path, monkeypatch):
    root = tmp_path / "zcode-accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    return root


INIT_PATH = oauth.CLI_INIT_PATH
POLL_PATH = oauth.CLI_POLL_PATH.format(flow_id="FLOW-1")

READY_BODY = {
    "code": 0,
    "data": {
        "status": "ready",
        "token": "JWT-1",
        "user": {"user_id": "u-1", "email": "dev@example.test", "name": "Dev"},
        "bigmodel": {"access_token": "BM-1", "refresh_token": "BM-R1"},
    },
}


def _init_route(expires_at: float | None = None, *, interval: float | None = 2) -> httpx.Response:
    data: dict = {"flow_id": "FLOW-1", "authorize_url": AUTHORIZE_URL, "poll_token": "PT-1"}
    if interval is not None:
        data["poll_interval_sec"] = interval
    if expires_at is not None:
        data["expires_at"] = expires_at
    return httpx.Response(200, json={"code": 0, "data": data})


def _pending() -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "data": {"status": "pending"}})


# ============ 正常路径：pending → ready → 落账号 + 客户端数据根 ============


def test_login_pending_then_success_commits_account_and_client_store(
        monkeypatch, accounts_root, capsys, poll_waits):
    """🔴 判据主链：打印授权地址/设备码/指引 → pending 打点 → ready 落两处凭据；退出码 0。"""
    upstream = FakeUpstream({INIT_PATH: _init_route(), POLL_PATH: [_pending(),
                                                                  httpx.Response(200, json=READY_BODY)]})
    _patch_upstream(monkeypatch, upstream)

    rc = main(["zcode", "login", "--name", "acct-new"])
    out = capsys.readouterr().out

    assert rc == 0, out
    cred = accounts_store.load_credentials("zcode", "acct-new", root=accounts_root)
    meta = accounts_store.load_meta(accounts_root, "acct-new")
    # ① init 的输出：授权地址 + 在浏览器打开指引 + 设备码（device_mid）
    # 🔴 打印的地址**不是**服务端原样给的那条：它自带的 `redirect` 已被剥掉、
    #    重挂成官方桥接页（`oauth.rs:127-149`），否则授权完成后永远到不了捕获方。
    printed = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("https://")][-1]
    assert printed != AUTHORIZE_URL and "&state=s1" in printed, printed
    assert printed.startswith("https://bigmodel.cn/login?appId=zcode&state=s1&redirect="), printed
    assert "bigmodel.cn%2Fcb" not in printed, "服务端自己的回调地址没被剥掉"
    bridge = bridge_redirect_params(printed)
    assert bridge["redirect"] == ["zcode://oauth/callback"], bridge
    assert bridge["app_version"] == [oauth.DEFAULT_APP_VERSION], bridge
    assert "在浏览器打开" in out, out
    assert f"设备码（device_mid）：{meta['device_mid']}" in out, out
    # ② 账号落盘（§22.2 唯一入口）：凭据本体 + 设备/展示元信息
    assert cred["zcodejwttoken"] == "JWT-1"
    assert cred["oauth:active_provider"] == "bigmodel"
    assert cred["oauth:bigmodel:access_token"] == "BM-1"
    assert meta["device_mid"] and meta["provider"] == "bigmodel"
    assert meta["display_name"] == "Dev" and meta["user_id"] == "u-1"
    # ③ 客户端数据根（与 UI 向导同路径；既有领取/额度/launch 读它）
    v2 = dataroot.v2_dir_of(accounts_root, "acct-new")
    assert json.loads((v2 / "credentials.json").read_text(encoding="utf-8")) == cred
    tele = json.loads((v2 / "telemetry-state.json").read_text(encoding="utf-8"))
    assert tele["deviceMid"] == meta["device_mid"]
    # ④ pending 打点含状态与剩余时间；间隔 = 服务端下发值（2s）
    assert "等待用户在浏览器完成授权" in out and "剩余约" in out, out
    assert poll_waits == [2.0], f"轮询间隔必须用 flow.poll_interval_s：{poll_waits}"
    # 请求形状：init 一次 + poll 两次（pending 一次、ready 一次）
    assert upstream.paths() == [INIT_PATH, POLL_PATH, POLL_PATH]
    assert "✓ 已新增账号 acct-new" in out, out


def test_poll_interval_falls_back_to_module_constant(monkeypatch, accounts_root, poll_waits):
    """服务端不给 `poll_interval_sec` → 间隔 = `oauth.DEFAULT_POLL_INTERVAL_S`（既有常量）。"""
    upstream = FakeUpstream({INIT_PATH: _init_route(interval=None),
                             POLL_PATH: [_pending(), httpx.Response(200, json=READY_BODY)]})
    _patch_upstream(monkeypatch, upstream)

    assert main(["zcode", "login", "--name", "acct-i"]) == 0
    assert poll_waits == [oauth.DEFAULT_POLL_INTERVAL_S], poll_waits


def test_local_wait_budget_matches_session_ttl():
    """本地上界常量与 §22.8-2 的会话 TTL 同源（改一处不改另一处 → 本用例红）。"""
    assert cli_zcode.LOGIN_MAX_WAIT_S == accounts_login.DEFAULT_SESSION_TTL_S


def test_login_default_name_is_zcode_hex4(monkeypatch, accounts_root):
    """缺省账号名 = `zcode-<hex4>`，且落在白名单字符集内（可被后续 CLI/运营路径寻址）。"""
    upstream = FakeUpstream({INIT_PATH: _init_route(), POLL_PATH: httpx.Response(200, json=READY_BODY)})
    _patch_upstream(monkeypatch, upstream)

    assert main(["zcode", "login"]) == 0
    names = accounts_store.list_accounts("zcode", root=accounts_root)
    assert len(names) == 1
    assert re.fullmatch(r"zcode-[0-9a-f]{4}", names[0]), names


def test_login_provider_flag_reaches_the_upstream(monkeypatch, accounts_root):
    """`--provider zai`：值真的进 init 请求体，凭据按该 provider 作用域落盘（不是写死 bigmodel）。"""
    ready = {"code": 0, "data": {"status": "ready", "token": "JWT-Z",
                                 "user": {"user_id": "u-z"},
                                 "zai": {"access_token": "ZAI-1"}}}
    upstream = FakeUpstream({INIT_PATH: _init_route(),
                             POLL_PATH: httpx.Response(200, json=ready)})
    _patch_upstream(monkeypatch, upstream)

    assert main(["zcode", "login", "--name", "acct-zai", "--provider", "zai"]) == 0
    assert json.loads(upstream.calls[0].content.decode()) == {"provider": "zai"}
    cred = accounts_store.load_credentials("zcode", "acct-zai", root=accounts_root)
    assert cred["oauth:active_provider"] == "zai"
    assert cred["oauth:zai:access_token"] == "ZAI-1"


def test_relogin_reuses_existing_device_mid(monkeypatch, accounts_root, capsys):
    """🔴 §15.1 硬约束 2：重登录**原样复用**该账号既有设备码（换码 = 上游眼里"换设备"）。"""
    accounts_store.commit_login("zcode", "acct-relog", {"zcodejwttoken": "OLD"},
                                {"device_mid": "MID-KEEP"})
    upstream = FakeUpstream({INIT_PATH: _init_route(), POLL_PATH: httpx.Response(200, json=READY_BODY)})
    _patch_upstream(monkeypatch, upstream)

    assert main(["zcode", "login", "--name", "acct-relog"]) == 0
    out = capsys.readouterr().out
    assert "MID-KEEP" in out, out
    assert accounts_store.load_meta(accounts_root, "acct-relog")["device_mid"] == "MID-KEEP"
    assert accounts_store.load_credentials(
        "zcode", "acct-relog", root=accounts_root)["zcodejwttoken"] == "JWT-1"


# ============ 失败路径：一律退出码 1、零落盘 ============


def test_login_init_http_failure_exits_1(monkeypatch, accounts_root, capsys):
    """init 被上游拒（HTTP 500）→ 退出码 1 + 可读原因；账号目录不得出现。"""
    upstream = FakeUpstream({INIT_PATH: httpx.Response(500, json={"msg": "boom"})})
    _patch_upstream(monkeypatch, upstream)

    rc = main(["zcode", "login", "--name", "acct-x"])
    err = capsys.readouterr().err
    assert rc == 1, err
    assert "登录失败" in err and "HTTP 500" in err, err
    assert not (accounts_root / "acct-x").exists()


def test_login_init_transport_failure_exits_1(monkeypatch, accounts_root, capsys):
    """传输层失败（连接错误）→ 退出码 1（异常折叠成可读原因，不冒栈）。"""
    upstream = FakeUpstream({INIT_PATH: httpx.ConnectError("connection refused")})
    _patch_upstream(monkeypatch, upstream)

    rc = main(["zcode", "login", "--name", "acct-x"])
    err = capsys.readouterr().err
    assert rc == 1 and "登录失败" in err and "connection refused" in err, err
    assert "Traceback" not in err, err
    assert not (accounts_root / "acct-x").exists()


def test_login_init_malformed_body_exits_1(monkeypatch, accounts_root, capsys):
    """init 响应缺 `flow_id` → `ValueError` 折叠成退出码 1（**不猜**、不假装发起成功）。"""
    upstream = FakeUpstream({INIT_PATH: httpx.Response(200, json={"code": 0, "data": {}})})
    _patch_upstream(monkeypatch, upstream)

    rc = main(["zcode", "login", "--name", "acct-x"])
    err = capsys.readouterr().err
    assert rc == 1 and "缺 flow_id" in err, err


def test_login_authorization_refused_exits_1(monkeypatch, accounts_root, capsys):
    """用户在授权页拒绝（服务端 status=failed）→ 退出码 1、不打第三轮、零落盘。"""
    upstream = FakeUpstream({INIT_PATH: _init_route(),
                             POLL_PATH: httpx.Response(200, json={
                                 "code": 0, "data": {"status": "failed"}})})
    _patch_upstream(monkeypatch, upstream)

    rc = main(["zcode", "login", "--name", "acct-x"])
    err = capsys.readouterr().err
    assert rc == 1 and "登录失败" in err and "拒绝" in err, err
    assert upstream.paths() == [INIT_PATH, POLL_PATH]
    assert not (accounts_root / "acct-x").exists()


def test_login_flow_expired_exits_1(monkeypatch, accounts_root, capsys):
    """服务端 `expires_at` 已过 → `expired` 终态、退出码 1（不空转、零上游轮询请求）。"""
    upstream = FakeUpstream({INIT_PATH: _init_route(expires_at=time.time() - 5),
                             POLL_PATH: _pending()})
    _patch_upstream(monkeypatch, upstream)

    rc = main(["zcode", "login", "--name", "acct-x"])
    err = capsys.readouterr().err
    assert rc == 1 and "过期" in err, err
    assert upstream.paths() == [INIT_PATH], "已过期 → 连一次轮询都不该发"


def test_login_local_wait_timeout_exits_1(monkeypatch, accounts_root, capsys):
    """上游不给 `expires_at` → 用本地上界兜底；预算耗尽（注入负值）即失败，退出码 1。"""
    monkeypatch.setattr(cli_zcode, "LOGIN_MAX_WAIT_S", -1.0)
    upstream = FakeUpstream({INIT_PATH: _init_route(), POLL_PATH: _pending()})
    _patch_upstream(monkeypatch, upstream)

    rc = main(["zcode", "login", "--name", "acct-x"])
    err = capsys.readouterr().err
    assert rc == 1 and "超时" in err, err
    assert not (accounts_root / "acct-x").exists()


def test_login_ctrl_c_cancels_cleanly(monkeypatch, accounts_root, capsys):
    """Ctrl+C 中断轮询 → 可读"已取消" + 退出码 1（**不冒 KeyboardInterrupt 栈**）。

    轮询提示里承诺了"Ctrl+C 可取消"（长驻等待的用户唯一出口）——承诺与行为必须一致。
    """
    upstream = FakeUpstream({INIT_PATH: _init_route(), POLL_PATH: _pending()})
    _patch_upstream(monkeypatch, upstream)

    async def interrupted(seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_zcode, "_wait", interrupted)
    rc = main(["zcode", "login", "--name", "acct-x"])
    err = capsys.readouterr().err
    assert rc == 1 and "已取消" in err, err
    assert "Traceback" not in err, err
    assert not (accounts_root / "acct-x").exists()


def test_login_rejects_bad_name_before_any_request(monkeypatch, accounts_root, capsys):
    """🔴 账号名白名单：[A-Za-z0-9_-]{1,32} —— 非法名**在发起授权之前**拒绝（不白跑上游）。"""
    upstream = FakeUpstream({})
    _patch_upstream(monkeypatch, upstream)

    rc = main(["zcode", "login", "--name", "../evil"])
    err = capsys.readouterr().err
    assert rc == 1, err
    assert "账号名必须匹配" in err, err
    assert upstream.calls == [], "非法名不得发起任何上游请求"
    assert not (accounts_root / "evil").exists()


def test_login_write_lock_refusal_exits_1_and_persists_nothing(
        monkeypatch, accounts_root, tmp_path, capsys):
    """落盘被拒（写盘锁被别的进程持有，§22.8-4 fail closed）→ 退出码 1 + 零落盘。

    这是 `mgw zcode login` 与 `store.commit_login` 的真实接缝：拒写必须走**可读失败**
    而不是冒栈（CLI 面不抛 traceback）。
    """
    lock_dir = tmp_path / "locks"
    monkeypatch.setenv(accounts_store.ACCOUNTS_LOCK_DIR_ENV, str(lock_dir))
    monkeypatch.setattr(accounts_store, "_LOCK_WAIT_S", 0.05)
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / accounts_store.ACCOUNTS_LOCK_NAME).write_text("1 " + "f" * 16, encoding="utf-8")

    upstream = FakeUpstream({INIT_PATH: _init_route(), POLL_PATH: httpx.Response(200, json=READY_BODY)})
    _patch_upstream(monkeypatch, upstream)

    rc = main(["zcode", "login", "--name", "acct-x"])
    err = capsys.readouterr().err
    assert rc == 1 and "登录失败" in err and "WriteLockError" in err, err
    assert not (accounts_root / "acct-x").exists(), "拒写 = 一个字节都不落"


# ============ `--help` 文案（旧"需浏览器/import"指引下线，改设备流说明）============


def test_login_help_documents_the_device_flow(monkeypatch, capsys):
    """`mgw zcode login --help`：设备流说明 + 退出码 0/1 + `--name`/`--provider`；import 备用。"""
    monkeypatch.setenv("COLUMNS", "200")               # 防 argparse 换行拆散判据 token
    with pytest.raises(SystemExit) as e:
        main(["zcode", "login", "--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out

    for token in ("设备授权流", "在浏览器完成授权", "--name", "--provider",
                  "0 = 登录成功", "1 = 登录失败", "mgw zcode import"):
        assert token in out, f"login --help 缺 {token!r}：\n{out}"
