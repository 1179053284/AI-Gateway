"""M6-6 Fix-η 复检护栏：重登后资源即时复活（B-2 残差）+ cron 按动作声明枚举产品。

两条修复各自的**撤修复红证**（撤掉对应实现后，本文件哪条转红）：

| 用例 | 修复 | 撤修复后的红态 |
|---|---|---|
| `test_relogin_revives_without_extra_actions` | `accounts/materialize.py::_nudge_reload` —— 命中既有资源（登录/续期成功、配置零变更）时前推配置 mtime，驱动既有 1s 热重载重算运行态 | 重登后 `status` 停在 `disabled`、模型不在 `/v1/models`（`_wait` 超时） |
| `test_ops_cron_covers_new_products_accounts` | `main.py::_maybe_start_ops` 的门与 claim 动作都按 `supported_products` 声明取 | `app.state.ops_scheduler is None`（zcode-only 门直接掐掉调度器，跑都没得跑） |

纪律：无网络（假上游 / 假钩子）、不碰仓库 `data/`（conftest 钉 MG_CONFIG）、
不碰 `127.0.0.1:8300`（本文件全部走随机端口实例）。
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import datetime as dt
import json
import types

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from model_gateway.accounts import login, store
from model_gateway.accounts.types import Challenge, LoginOutcome
from model_gateway.config.schemas import AppConfig
from model_gateway.core.resources import ResourceManager
from model_gateway.ops import builtin as ops_builtin
from model_gateway.ops import runner as ops_runner
from model_gateway.ops.base import OpResult
from model_gateway.upstream.buddy import product as buddy

#: 配置里的 Key 故意留着：产品资源出站**绝不用**它（铁律 1）——顺带断言它没被发出去
CONFIG_KEY = "sk-config-key-must-not-be-sent"


# ============ 基建：假 buddy 上游（401 / 200 可切）+ 网关 ============

class _FakeBuddyUpstream:
    """假 CodeBuddy 上游：`POST /v2/chat/completions`；`status` 可切成 401。"""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.status = 200
        self.app = Starlette(routes=[
            Route("/v2/chat/completions", self._chat, methods=["POST"])])

    async def _chat(self, request: Request):
        body = await request.json()
        self.requests.append({"path": request.url.path,
                              "headers": dict(request.headers), "body": body})
        if self.status != 200:
            return JSONResponse({"error": {"message": "token rejected"}},
                                status_code=self.status)
        return JSONResponse({
            "id": "chatcmpl-fake-buddy", "object": "chat.completion", "model": body["model"],
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "来自假上游"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        })


@pytest.fixture
async def buddy_upstream():
    fake = _FakeBuddyUpstream()
    server = uvicorn.Server(uvicorn.Config(fake.app, host="127.0.0.1", port=0,
                                           log_level="warning"))
    task = asyncio.get_running_loop().create_task(server.serve())
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.01)
    assert server.started, "假上游启动超时"
    fake.port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield fake
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=10)


@pytest.fixture(autouse=True)
def _clean_shared_login_sessions():
    """共享登录引擎的会话表是**进程级**状态（TTL 600s）：用例之间不得互留痕。"""
    yield
    login.shutdown_login()


def _buddy_cfg(port: int) -> dict:
    """网关配置：产品资源指向**假上游**，账号凭据另在账号目录（MG_CONFIG 派生）。"""
    return {
        "resources": [{
            "id": "res-cb", "name": "产品资源", "vendor": "", "preset": "",
            "account": "acc-1", "product": "buddy", "account_ref": "acc-1",
            "protocol": "openai", "base_url": f"http://127.0.0.1:{port}",
            "api_key": CONFIG_KEY, "enabled": True, "access_mode": "api"}],
        "models": [{"name": "cb-model", "endpoint": "chat",
                    "resources": [{"resource": "res-cb", "model": "hy3"}]}],
    }


def _body(model: str = "cb-model") -> dict:
    return {"model": model, "messages": [{"role": "user", "content": "hi"}]}


async def _wait(predicate, timeout: float = 8.0, interval: float = 0.05) -> bool:
    """轮询到条件成立（热重载 watcher 是 1s 轮询，必须给足时间窗）。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


async def _post(client, gw, path: str, body: dict) -> httpx.Response:
    return await client.post(f"{gw.base_url}{path}", json=body)


async def _model_ids(client, gw) -> list[str]:
    r = await client.get(f"{gw.base_url}/v1/models")
    assert r.status_code == 200, r.text
    return [m["id"] for m in r.json()["data"]]


# ============ ① B-2 残差：重登成功路径自身触发运行态重算 ============

async def test_relogin_revives_without_extra_actions(buddy_upstream, make_gateway, client,
                                                     monkeypatch):
    """🔴 401 判死（终态）→ **重登同一账号**（管理端登录向导，唯一动作）→ 回 active + 可调用。

    走用户真实路径：`login/start` + `login/poll`（引擎成功时经唯一落盘入口
    `store.commit_login` 保存新凭据并物化）→ **不做任何额外操作**（不保存配置、
    不重启、不手动 reload），只等既有热重载（1s）自行重算运行态。

    红证（撤 `materialize._nudge_reload`）：第 ② 步的 `_wait` 超时 ——
    `status` 停在 `disabled`、模型继续被 `/v1/models` 隐藏、调用 503。
    """
    gw = await make_gateway(_buddy_cfg(buddy_upstream.port))
    # 🔴 生产同形：物化/热重载看的是**同一份配置文件**。conftest 的 MG_CONFIG 指向别处，
    #    不重钉的话"重载信号"会打在网关看不见的文件上（测试环境的错位，不是产品行为）。
    monkeypatch.setenv("MG_CONFIG", str(gw.config_path))

    cred = {"v": "TOKEN-OLD"}

    async def fake_start(session):
        return Challenge(url="https://example.test/auth")

    async def fake_poll(session):
        return LoginOutcome(state="success", credentials={"access_token": cred["v"]},
                            meta={"plan": "free"})

    monkeypatch.setitem(buddy._HOOKS, "login_start", fake_start)
    monkeypatch.setitem(buddy._HOOKS, "login_poll", fake_poll)

    async def _login(name: str = "acc-1") -> None:
        started = await _post(client, gw, "/admin/api/accounts/login/start",
                              {"product": "buddy", "name": name})
        assert started.status_code == 200, started.text
        sid = started.json()["session"]
        done = await _post(client, gw, "/admin/api/accounts/login/poll",
                           {"product": "buddy", "session": sid})
        assert done.status_code == 200 and done.json()["state"] == "success", done.text
        # 🔴 M7-E 两阶段提交：`success` 只认领暂存；「确定接入」才经唯一落盘入口
        #    `store.commit_login` 落盘并触发运行态重算（物化/重载信号在这一步发出）
        commit = await _post(client, gw, "/admin/api/accounts/login/commit", {"session": sid})
        assert commit.status_code == 200 and commit.json()["committed"] is True, commit.text

    # ① 登录（凭据 TOKEN-OLD；网关此前无凭据，物化命中既有资源 → 发一次重载信号）
    adapter_before = gw.runtime.adapters.get("res-cb")
    await _login()
    assert store.load_credentials("buddy", "acc-1")["access_token"] == "TOKEN-OLD"
    # 等这次重算落地（**只为消除竞态**：先让运行态与 TOKEN-OLD 对齐，再制造 401，
    # 否则迟到的重算会把判死结果清掉）。触发失效时这里会耗完超时，由 ④ 转红。）
    await _wait(lambda: gw.runtime.adapters.get("res-cb") is not adapter_before)

    # ② 上游 401 → 判死（终态）+ 从 /v1/models 隐藏
    buddy_upstream.status = 401
    r1 = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert r1.status_code == 401, r1.text
    st = gw.runtime.resources.registry[("res-cb", "hy3")]
    assert st.status == "disabled", "401 必须判死（终态）"
    assert "cb-model" not in await _model_ids(client, gw), "判死的资源不得继续对外声明"

    # ③ 用户按提示"重新登录"（同一账号；唯一动作）——凭据换成 TOKEN-NEW
    cred["v"] = "TOKEN-NEW"
    await _login()
    assert store.load_credentials("buddy", "acc-1")["access_token"] == "TOKEN-NEW"

    # ④ 无需任何额外操作：既有热重载（1s 轮询）应自行把终态清零
    assert await _wait(lambda: st.status == "active"), \
        "重登后仍 disabled —— 用户按提示操作却永远 503（B-2 残差）"
    assert st.C == 0 and st.last_error is None
    assert "cb-model" in await _model_ids(client, gw), "复活后必须回到 /v1/models"

    # ⑤ 真调用：新凭据生效、配置 Key 不参与鉴权
    buddy_upstream.status = 200
    r2 = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert r2.status_code == 200, r2.text
    assert buddy_upstream.requests[-1]["headers"]["authorization"] == "Bearer TOKEN-NEW"
    assert CONFIG_KEY not in json.dumps(buddy_upstream.requests[-1]["headers"])
    await gw.drain_events()
    assert gw.read_events()[-1]["status"] == "success"


# ============ ② cron：账号枚举按动作声明的 supported_products ============

def _ops_runtime(tmp_path) -> types.SimpleNamespace:
    """`_maybe_start_ops` 需要的最小运行时（真 ResourceManager + 私有 usage_dir）。"""
    cfg = AppConfig.model_validate({
        "resources": [], "models": [],
        "gateway": {"zcode": {"claim_interval_seconds": 60}},
    })
    return types.SimpleNamespace(config=cfg, usage_dir=tmp_path / "usage",
                                 resources=ResourceManager())


async def test_ops_cron_covers_new_products_accounts(tmp_path, monkeypatch):
    """🔴 只接**新产品**（trae，无任何 zcode 账号）时：调度器要起，且 cron 轮次真的跑到它。

    修前两行都写死 zcode（门 = `upstream.zcode.store.list_accounts()`；claim 动作 =
    `zcode_claim` 别名，声明 `("zcode",)`）→ 新产品的账号在 cron 腿上"注册了但没人跑"。
    本用例从生产装配入口 `main._maybe_start_ops` 拿它交给调度器的那段 `run`，**真跑一轮**
    （枚举/过滤走真实 `run_once`，只有产品的网络执行体换成假的记录器）。

    红证（撤修复 = 门/动作回到 zcode-only）：`app.state.ops_scheduler is None`，
    这条断言即红（调度器根本没起来）。
    """
    from model_gateway.main import _maybe_start_ops

    # 只接新产品：一个 trae 账号，没有任何 zcode 账号
    store.commit_login("trae", "tr-1", {"access_token": "T-TRAE"}, {})
    assert store.list_accounts("trae") == ["tr-1"]
    assert store.list_accounts("zcode") == []

    real_claim = ops_builtin.OPERATIONS["claim"]
    assert "trae" in real_claim.supported_products, "判据取真实声明（不是测试自己编的）"

    claims: list[str] = []

    async def fake_claim(account, *, manual=False, runtime=None):
        claims.append(account)
        return OpResult(account, "success")

    async def fake_balance(account, *, manual=False, runtime=None):
        return OpResult(account, "inactive", "（测试假体，不触网）")

    # 只换执行体、**保留真实声明**（枚举与被测的那道门同源）
    monkeypatch.setitem(ops_builtin.OPERATIONS, "claim",
                        dataclasses.replace(real_claim, run=fake_claim))
    monkeypatch.setitem(ops_builtin.OPERATIONS, "query_balance",
                        dataclasses.replace(ops_builtin.OPERATIONS["query_balance"],
                                            run=fake_balance))

    captured: dict = {}

    def spy_start(self, run):
        captured["sched"] = self
        captured["run"] = run

    monkeypatch.setattr(ops_runner.Scheduler, "start", spy_start)

    app = types.SimpleNamespace(state=types.SimpleNamespace(runtime=_ops_runtime(tmp_path)))
    _maybe_start_ops(app)

    assert getattr(app.state, "ops_scheduler", None) is not None, \
        "只接新产品时调度器没起来 —— cron 门还写死 zcode（新产品注册了但没人跑）"
    assert "run" in captured, "没把批量任务交给调度器"
    await captured["run"]()                      # 真跑一轮 tick（枚举 = 真实 run_once）
    assert claims == ["tr-1"], f"cron 轮次没覆盖新产品账号：{claims}"
    # 结果照常落盘（红点的事实源），且 usage_dir 用的是运行时给的那个
    results = tmp_path / "usage" / f"ops-results-{dt.date.today():%Y%m%d}.jsonl"
    assert results.exists(), "cron 轮次的结果没有落盘（红点的事实源丢了）"
    assert json.loads(results.read_text(encoding="utf-8").splitlines()[0])["success"] == ["tr-1"]
