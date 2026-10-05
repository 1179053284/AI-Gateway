"""zcode GLM flash 的**故障与跨账号**判据矩阵（2026-10-05 严格测试轮）。

被测形状 = 实盘那一套：`resources[]` 里 product=zcode 的账号侧资源、网关模型
`glm-5.3-flash`、供应商模型名 `GLM-5.3-Flash`、`access_mode: plan`、anthropic 协议、
Plan/JWT 通道（`Authorization: Bearer` + `X-Device-Mid`）。上游 = 本地假 ZCode
（**真实 HTTP**，全栈经 `/v1/chat/completions`，与 `test_zcode_out.py` 同一基建）。

每号的行为由 `X-Device-Mid` 分派 ⇒ 同一台假上游能演「一个号坏、其余号好」。

🔴 本文件的用例分两类，注释里逐条标明：
· **契约**（期望行为 = 需求）；
· **现状刻画**（断言的是**当前代码真实发生的事**，其中不合理的部分是**缺陷证据**，
  不是验收通过 —— 用例绿 ≠ 该行为可用）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from model_gateway.accounts import store

MODEL = "glm-5.3-flash"
VENDOR_MODEL = "GLM-5.3-Flash"
PATH = "/api/v1/zcode-plan/anthropic/v1/messages"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ6Yy0xIn0.c2ln"
ACCOUNTS = ["zc-1", "zc-2", "zc-3", "zc-4", "zc-5"]
MIDS = {a: f"mid-{i:08d}" for i, a in enumerate(ACCOUNTS)}


class FakeZcode:
    """假 ZCode Plan 通道：按 `X-Device-Mid` 分派行为，记录逐号命中与并发峰值。"""

    def __init__(self) -> None:
        self.behavior: dict[str, dict] = {}
        self.hits: list[dict] = []
        self.live_mids: set[str] = set()
        self.peak_accounts = 0
        self.app = Starlette(routes=[Route(PATH, self._messages, methods=["POST"])])

    def mids_hit(self) -> list[str]:
        return [h["mid"] for h in self.hits]

    def set_all(self, kind: str, **over) -> None:
        for mid in MIDS.values():
            self.behavior[mid] = {"kind": kind, **over}

    async def _messages(self, request: Request):
        mid = request.headers.get("x-device-mid", "")
        body = await request.json()
        self.hits.append({"mid": mid, "body": body,
                          "auth": request.headers.get("authorization", "")})
        self.live_mids.add(mid)
        self.peak_accounts = max(self.peak_accounts, len(self.live_mids))
        try:
            return await self._respond(mid, body)
        finally:
            self.live_mids.discard(mid)

    async def _empty_sse(self):
        """一条**零正文增量**的正常 SSE（模型把预算全花在思考上 / 上游只回空正文）。"""
        for name, data in _sse_events(""):
            if name == "content_block_delta":
                continue
            yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    async def _reasoning_only_sse(self):
        """只有 `thinking_delta`、没有 `text_delta` 的 SSE（带思考的模型正文为空的形状）。"""
        frames = [
            ("message_start", {"type": "message_start", "message": {
                "id": "m", "type": "message", "role": "assistant",
                "usage": {"input_tokens": 11, "output_tokens": 0}}}),
            ("content_block_start", {"type": "content_block_start", "index": 0,
                                     "content_block": {"type": "thinking", "thinking": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "thinking_delta", "thinking": "只思考"}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                               "usage": {"input_tokens": 11, "output_tokens": 9}}),
            ("message_stop", {"type": "message_stop"}),
        ]
        for name, data in frames:
            yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    async def _respond(self, mid: str, body: dict):
        beh = self.behavior.get(mid, {"kind": "ok"})
        kind = beh["kind"]
        if kind == "ok":
            await asyncio.sleep(beh.get("delay", 0))
            if body.get("stream"):
                return StreamingResponse(self._sse(), media_type="text/event-stream")
            return JSONResponse(_msg(body))
        if kind == "http":
            return JSONResponse(beh.get("payload") or {"code": 3012, "msg": "unusual activity"},
                                status_code=beh["status"])
        if kind == "envelope200":
            # 上游用 **200 + 自有信封** 表达风控（billing/product 两条腿读的正是这种）
            return JSONResponse({"code": beh.get("code", 3012), "msg": "unusual activity"})
        if kind == "slow":
            await asyncio.sleep(beh["seconds"])
            return JSONResponse(_msg(body))
        if kind == "abort_after_content":
            return StreamingResponse(self._aborting_sse(), media_type="text/event-stream")
        if kind == "empty_sse":
            return StreamingResponse(self._empty_sse(), media_type="text/event-stream")
        if kind == "reasoning_only_sse":
            return StreamingResponse(self._reasoning_only_sse(), media_type="text/event-stream")
        raise AssertionError(f"未知行为 {kind}")

    async def _sse(self):
        for name, data in _sse_events("你好"):
            yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    async def _aborting_sse(self):
        """先正常吐一个正文增量（客户端已收到字），再断流 = 提交后失败。"""
        yield (f"event: message_start\ndata: {json.dumps({'type':'message_start','message':{'id':'m','type':'message','role':'assistant','usage':{'input_tokens':7,'output_tokens':0}}})}\n\n")
        yield (f"event: content_block_start\ndata: {json.dumps({'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}})}\n\n")
        yield (f"event: content_block_delta\ndata: {json.dumps({'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':'已经'}})}\n\n")
        yield (f"event: error\ndata: {json.dumps({'type':'error','error':{'type':'api_error','message':'upstream aborted'}})}\n\n")


def _msg(body: dict) -> dict:
    return {"id": "msg_fake", "type": "message", "role": "assistant",
            "model": body["model"], "content": [{"type": "text", "text": "来自假 ZCode"}],
            "stop_reason": "end_turn", "usage": {"input_tokens": 11, "output_tokens": 5}}


def _sse_events(text: str) -> list[tuple[str, dict]]:
    return [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_fake", "type": "message", "role": "assistant",
            "usage": {"input_tokens": 11, "output_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                           "usage": {"input_tokens": 11, "output_tokens": 5}}),
        ("message_stop", {"type": "message_stop"}),
    ]


@pytest.fixture
async def zcode_upstream():
    fake = FakeZcode()
    import uvicorn

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


def _login_all() -> None:
    for acct in ACCOUNTS:
        store.commit_login("zcode", acct, {"zcodejwttoken": JWT,
                                           "device_mid": MIDS[acct]}, {})


def _cfg(port: int, *, x: int = 1, y: int = 2, m: int = 1,
         cooldown: int = 30, plan_cooldown: int = 45, quota_retry: int = 1,
         attempt_timeout: int = 5, budget: float = 30.0) -> dict:
    res = []
    models = []
    for i, acct in enumerate(ACCOUNTS):
        rid = f"res-z{i + 1}"
        res.append({"id": rid, "name": f"ZCode {acct}", "vendor": "ZCode",
                    "account": acct, "product": "zcode", "account_ref": acct,
                    "protocol": "anthropic", "preset": "",
                    "base_url": f"http://127.0.0.1:{port}/api/v1/zcode-plan/anthropic",
                    "api_key": "", "enabled": True, "access_mode": "plan"})
        models.append({"resource": rid, "model": VENDOR_MODEL, "enabled": True})
    return {
        "resources": res,
        "models": [{"name": MODEL, "endpoint": "chat", "enabled": True, "resources": models}],
        "scheduling": {"max_active_per_model": x, "fail_threshold": y,
                       "retry_per_request": m, "retry_backoff_seconds": 0.0,
                       "quota_retry": quota_retry, "quota_backoff_base_seconds": 0.0,
                       "cooldown_seconds": cooldown, "cooldown_seconds_plan": plan_cooldown},
        "gateway": {"attempt_timeout_seconds": attempt_timeout,
                    "request_total_budget_seconds": budget,
                    "access_tokens": []},
    }


def _body(**over) -> dict:
    data = {"model": MODEL, "messages": [{"role": "user", "content": "hi"}]}
    data.update(over)
    return data


async def _ask(client, gw, **over):
    return await client.post(f"{gw.base_url}/v1/chat/completions", json=_body(**over))


async def _event(gw):
    await gw.drain_events()
    return gw.read_events()[-1]


def _acct_of(mid: str) -> str:
    return {v: k for k, v in MIDS.items()}[mid]


# ============ ① 正常链路与跨账号轮转 ============

async def test_z1_happy_path_rotates_across_accounts(zcode_upstream, make_gateway, client):
    """**契约**：多号可用时，连续请求应换号承接（Q33-② 活跃组排空后换位）。"""
    _login_all()
    zcode_upstream.set_all("ok")
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1))

    served = []
    for _ in range(5):
        resp = await _ask(client, gw)
        assert resp.status_code == 200, resp.text
        assert resp.json()["choices"][0]["message"]["content"] == "来自假 ZCode"
        await gw.drain_events()
        served.append(gw.read_events()[-1]["final_resource"])
    assert len(set(served)) >= 4, f"5 次请求只用了 {sorted(set(served))} —— 轮转未发生"
    # 每号一次请求一次出站，无重复烧号
    assert len(zcode_upstream.hits) == 5


async def test_z2_concurrency_respects_active_group_cap(zcode_upstream, make_gateway, client):
    """**契约**（PRD FR-3.2/3.3）：x=2 ⇒ 任意时刻**最多 2 个资源**承接流量；
    超出 x 的并发请求复用组内最闲者（x 限的是承接者数，不是请求数）。"""
    _login_all()
    zcode_upstream.set_all("ok", delay=0.25)
    gw = await make_gateway(_cfg(zcode_upstream.port, x=2))

    resps = await asyncio.gather(*[_ask(client, gw) for _ in range(4)])
    assert all(r.status_code == 200 for r in resps), [r.status_code for r in resps]
    assert zcode_upstream.peak_accounts <= 2, (
        f"同时在途的资源数 {zcode_upstream.peak_accounts} 越出 x=2（活跃组上限失效）")
    await gw.drain_events()
    accounts = {e["final_resource"] for e in gw.read_events()[-4:]}
    assert len(accounts) >= 1


# ============ ② 风控/客户端类错误：是否换号 ============

async def test_z3_3012_in_http_400_does_not_switch_accounts(zcode_upstream, make_gateway, client):
    """**现状刻画 = 缺陷证据**：4 个好号 + 1 个号回 400/3012 ⇒ 命中该号的那次请求
    直接死掉，其余号一次都没被试过（`core/scheduler.py:500` BAD_REQUEST 原样透传）。"""
    _login_all()
    bad = MIDS["zc-1"]
    zcode_upstream.set_all("ok")
    zcode_upstream.behavior[bad] = {"kind": "http", "status": 400,
                                    "payload": {"code": 3012, "msg": "unusual activity"}}
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1))

    resp = await _ask(client, gw)
    assert resp.status_code == 400, f"当前实现把 4xx 原样透传，实际={resp.status_code}"
    assert len(zcode_upstream.hits) == 1, "换号发生了 —— 与本用例的判据对象不符"
    ev = await _event(gw)
    assert ev["status"] == "failed"
    assert ev["switch_count"] == 0
    st = gw.resource("res-z1", VENDOR_MODEL)
    assert st.C == 0 and st.status == "active", "BAD_REQUEST 不计 C、不冷却（F-4 原文）"


async def test_z4_3012_as_http_200_envelope(zcode_upstream, make_gateway, client):
    """**契约（S-1，2026-10-05 起生效）**：上游用 **200 + 自有信封** 表达风控（额度腿与探活腿
    读的是这种形状，`product.py:454`）时，转发腿必须把它当**故障**而不是正常回答——
    零内容按可重试抛出 ⇒ 计 C、达 y 冷却换号，其余号顶上；不再有「正文空 + success + 计数清零」
    的无报错失败（旧实现三条全中，本用例当时是缺陷证据）。"""
    _login_all()
    zcode_upstream.set_all("ok")
    zcode_upstream.behavior[MIDS["zc-1"]] = {"kind": "envelope200", "code": 3012}
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1))

    resp = await _ask(client, gw)
    assert resp.status_code == 200, resp.text
    assert resp.json()["choices"][0]["message"]["content"] == "来自假 ZCode"
    ev = await _event(gw)
    assert ev["status"] == "success"
    assert ev["switch_count"] >= 1, f"零内容未触发换号：{ev}"
    st = gw.resource("res-z1", VENDOR_MODEL)
    assert st.C >= 1, f"零内容未计入失败计数：C={st.C}"
    assert zcode_upstream.mids_hit().count(MIDS["zc-1"]) <= 2, (
        "同号重试上限 m+1=2 次内应换号（§5.2），不得反复撞同一号")


async def test_z4b_3012_envelope_under_stream_request(zcode_upstream, make_gateway, client):
    """**契约（S-1，2026-10-05 起生效）**：客户端要 `stream:true`、上游回 **200 + JSON 信封**
    （非 SSE）时，出站层零帧产出 ⇒ 调度层按「通道回空」可重试故障处理，其余号顶上；
    客户端拿到**正常回答**。旧实现在这条上先记 `success`、再把 `NameError`（`_sse()` 不存在）
    冒穿成未分类 500 —— 那条死分支与假成功一起修掉了（`openai_compat.py` 零内容分支现回
    503 `EMPTY_UPSTREAM_CONTENT`，且只有重试/换号全部失败才会到达）。"""
    _login_all()
    zcode_upstream.set_all("ok")
    zcode_upstream.behavior[MIDS["zc-1"]] = {"kind": "envelope200", "code": 3012}
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1))

    resp = await _ask(client, gw, stream=True)
    body = resp.text
    ev = await _event(gw)
    assert resp.status_code == 200, f"实际={resp.status_code} body={body[:200]}"
    assert "你好" in body  # 其余号顶上，正常内容帧
    assert "error" not in body, body[:300]
    assert ev["status"] == "success"
    assert ev["switch_count"] >= 1, f"零内容未触发换号：{ev}"
    assert len(zcode_upstream.hits) >= 2, "其余号未被派活"


async def test_z5_405_does_not_switch_accounts(zcode_upstream, make_gateway, client):
    """**现状刻画 = 缺陷证据**：405（`billing.py:59` 明确列为风控信号之一）同样落
    BAD_REQUEST ⇒ 不换号、不冷却。"""
    _login_all()
    zcode_upstream.set_all("ok")
    zcode_upstream.behavior[MIDS["zc-1"]] = {"kind": "http", "status": 405,
                                             "payload": {"code": 3012, "msg": "unusual activity"}}
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1))

    resp = await _ask(client, gw)
    assert resp.status_code == 405
    assert len(zcode_upstream.hits) == 1
    assert (await _event(gw))["switch_count"] == 0


# ============ ③ 可重试类错误：冷却与换号是否成立 ============

async def test_z6_429_benches_account_and_switches(zcode_upstream, make_gateway, client):
    """**契约**：429 → 额度类 ⇒ 原地退避后仍失败则冷却该号并换号，客户端拿到成功。"""
    _login_all()
    zcode_upstream.set_all("ok")
    zcode_upstream.behavior[MIDS["zc-1"]] = {"kind": "http", "status": 429,
                                            "payload": {"type": "error"}}
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1, plan_cooldown=60))

    resp = await _ask(client, gw)
    assert resp.status_code == 200, resp.text
    ev = await _event(gw)
    assert ev["switch_count"] >= 1, f"未换号：{ev}"
    st = gw.resource("res-z1", VENDOR_MODEL)
    assert st.status == "cooldown", f"429 的号未被冷却：{st.status}"
    assert zcode_upstream.mids_hit().count(MIDS["zc-1"]) <= 1 + 1  # 原地 quota_retry 上限


async def test_z7_5xx_reaches_fail_threshold_then_rotates(zcode_upstream, make_gateway, client):
    """**契约**：5xx 计 C；C 达 y=2 ⇒ 冷却该号并换号；后续请求不再落到被冷却的号。"""
    _login_all()
    zcode_upstream.set_all("ok")
    zcode_upstream.behavior[MIDS["zc-1"]] = {"kind": "http", "status": 503,
                                            "payload": {"type": "error"}}
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1, y=2, m=1))

    r1 = await _ask(client, gw)
    assert r1.status_code == 200, r1.text
    st = gw.resource("res-z1", VENDOR_MODEL)
    assert st.C == 0 or st.status == "cooldown"
    hits_before = len(zcode_upstream.hits)
    for _ in range(3):
        assert (await _ask(client, gw)).status_code == 200
    await gw.drain_events()
    assert st.status == "cooldown", f"y 次 5xx 后仍未冷却：C={st.C} status={st.status}"
    # 冷却期内不再被打
    assert zcode_upstream.mids_hit().count(MIDS["zc-1"]) <= 2
    assert len(zcode_upstream.hits) > hits_before


async def test_z8_timeout_rotates_to_next_account(zcode_upstream, make_gateway, client):
    """**契约**：尝试超时（`status_code=None` → RETRYABLE）⇒ 换号，客户端不应拿到 4xx。"""
    _login_all()
    zcode_upstream.set_all("ok")
    zcode_upstream.behavior[MIDS["zc-1"]] = {"kind": "slow", "seconds": 3}
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1, attempt_timeout=1, budget=25))

    resp = await _ask(client, gw)
    assert resp.status_code == 200, resp.text
    ev = await _event(gw)
    assert ev["switch_count"] >= 1, f"超时未换号：{ev}"


# ============ ④ 流式中途断 ============

async def test_z9_mid_stream_abort_after_commit_is_not_retried(zcode_upstream, make_gateway, client):
    """**现状刻画**：正文已吐给客户端后断流 ⇒ 只能在同一连接上发错误帧，不跨号重试
    （字节已出，重放会双份）。"""
    _login_all()
    zcode_upstream.set_all("ok")
    zcode_upstream.behavior[MIDS["zc-1"]] = {"kind": "abort_after_content"}
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1))

    resp = await _ask(client, gw, stream=True)
    assert resp.status_code == 200
    body = resp.text
    assert "已经" in body, body[:400]
    frames = [line for line in body.splitlines() if line.startswith("data: ")]
    assert any("error" in f for f in frames), f"未见错误帧：{frames[-3:]}"
    assert len(zcode_upstream.hits) == 1, "提交后仍发生了跨号重放"


async def test_z15_stream_with_zero_content_frames(zcode_upstream, make_gateway, client):
    """**契约（S-1，2026-10-05 起生效）**：上游正常回一条**零正文增量**的 SSE（只有角色帧、
    无内容/推理/工具调用）⇒ 按「通道回空」可重试故障处理，其余号顶上；不再静默把空回答
    记成 success（旧实现 200 + 空正文 + success + 不换号）。

    （真正的崩溃分支是 `api/openai_compat.py` 旧那条**不存在的 `_sse()`** —— 由 z4b
    （200 但不是 SSE）实测钉住过；S-1 后两条分支都已收口。）"""
    _login_all()
    zcode_upstream.set_all("ok")
    zcode_upstream.behavior[MIDS["zc-1"]] = {"kind": "empty_sse"}
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1))

    resp = await _ask(client, gw, stream=True)
    ev = await _event(gw)
    assert resp.status_code == 200, f"其余号应顶上：{resp.status_code} {resp.text[:200]}"
    assert "你好" in resp.text  # 其余号顶上，正常内容帧
    assert ev["status"] == "success"
    assert ev["switch_count"] >= 1, f"零内容未触发换号：{ev}"
    assert len(zcode_upstream.hits) >= 2


async def test_z16_stream_with_only_reasoning_frames(zcode_upstream, make_gateway, client):
    """**契约**：只有 `thinking_delta` 也算**有内容**（推理是内容的一种，`chunk_is_content`
    收 reasoning）⇒ 正常记 success，不触发换号——S-1 的零内容守卫不误伤这条。"""
    _login_all()
    zcode_upstream.set_all("ok")
    zcode_upstream.behavior[MIDS["zc-1"]] = {"kind": "reasoning_only_sse"}
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1))

    resp = await _ask(client, gw, stream=True)
    ev = await _event(gw)
    assert resp.status_code == 200, f"{resp.status_code} {resp.text[:200]}"
    assert ev["status"] == "success", ev
    assert ev["switch_count"] == 0, ev
    assert ev.get("output_tokens", 0) >= 1, "推理 token 未被吸收"


# ============ ⑤ 额度与熔断闸门 ============
async def test_z10_exhausted_account_is_never_dispatched(zcode_upstream, make_gateway, client):
    """**契约**：余量 0 的号不参与派发（`ResourceState.available()`）。"""
    _login_all()
    zcode_upstream.set_all("ok")
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1))
    gw.runtime.resources.set_quota("res-z1", 0)

    for _ in range(3):
        assert (await _ask(client, gw)).status_code == 200
    assert MIDS["zc-1"] not in zcode_upstream.mids_hit(), "额度 0 的号仍被派发"


async def test_z11_global_circuit_does_not_stop_forwarding(zcode_upstream, make_gateway, client):
    """**现状刻画 = 缺陷证据**：只建立 3012 全局熔断（`circuit.enter()`）时，**转发腿照旧出站**。
    熔断进派发态有两条路：① 领取腿命中时顺带 `bench_all_zcode()`（`ops/builtin/zcode_claim.py:125`）；
    ② `sync_circuit_to_runtime` —— 而它的触发点**只有启动一次**（`main.py:96-99` 原话）。
    转发腿自己既不查 `circuit_active()` 也不调用 `enter()`（F-4 的处置就是「如实标注、不加熔断」，
    `upstream/zcode/out.py:35-45`）⇒ 进程内因别的腿新起的风控，挡不住这条腿继续打同一批号。"""
    from model_gateway.upstream.zcode import quota as zq

    _login_all()
    zcode_upstream.set_all("ok")
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1))

    zq.get_circuit().enter("3012 风控（测试注入）")
    assert zq.get_circuit().active() is True
    resp = await _ask(client, gw)
    assert resp.status_code == 200, resp.text
    assert len(zcode_upstream.hits) == 1, "熔断真的挡住了转发腿 —— 判据需随实现改写"


async def test_z12_premise_gap_hides_model_but_still_dispatches(
        zcode_upstream, make_gateway, client):
    """**现状刻画 = 缺陷证据**：`_outbound_premise_gap`（zcode 验证码未注入 ⇒ D1 未验证）
    只把模型挡在 `/v1/models` 与 `mgw setup` 之外；`rebuild()`/`pick_and_acquire` 不查它
    ⇒ 直接按名字点模型时，仍然会带着未验证的前提真打上游。"""
    _login_all()
    zcode_upstream.set_all("ok")
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1))

    listing = await client.get(f"{gw.base_url}/v1/models")
    names = {d["id"] for d in listing.json()["data"]}
    assert MODEL not in names, f"该模型本应因前提缺口不对外声明，实际在册：{sorted(names)}"

    resp = await _ask(client, gw)
    assert resp.status_code == 200, resp.text      # 仍然派发并成功 = 判据只管声明
    assert len(zcode_upstream.hits) == 1


async def test_z13_single_bad_account_poisons_share_of_traffic(zcode_upstream, make_gateway, client):
    """**现状刻画 = 缺陷证据**：接 z1 的轮转事实做吞吐推演 —— 池中 1/5 的号回 4xx
    风控时，随轮转推进会有相应比例的请求**直接失败给用户**（不是被换号吸收）。"""
    _login_all()
    zcode_upstream.set_all("ok")
    for acct in ("zc-1", "zc-3"):
        zcode_upstream.behavior[MIDS[acct]] = {
            "kind": "http", "status": 400,
            "payload": {"code": 3012, "msg": "unusual activity"}}
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1))

    codes = [(await _ask(client, gw)).status_code for _ in range(5)]
    failed = codes.count(400)
    assert failed >= 1, f"坏号被完全吸收了？codes={codes}"


# ============ ⑥ 复核项：把结论打到实盘形状上 ============

async def test_z17_400_no_failover_holds_at_live_x_8(zcode_upstream, make_gateway, client):
    """**复核 D-1（按实盘形状）**：实盘 `x` 已于 2026-10-05 13:41 从 2 改成 **8** ⇒ 活跃组里
    同时坐着 8 个号。游标指向坏号时的**那一条请求**，其余 7 个健康号一个都不试。"""
    _login_all()
    zcode_upstream.set_all("ok")
    zcode_upstream.behavior[MIDS["zc-1"]] = {"kind": "http", "status": 400,
                                             "payload": {"code": 3012, "msg": "unusual activity"}}
    gw = await make_gateway(_cfg(zcode_upstream.port, x=8))
    for rid in ("res-z1", "res-z2", "res-z3", "res-z4", "res-z5"):
        gw.runtime.resources.set_quota(rid, 1_000_000)   # 排除额度维度，只留"号坏"这一个变量
    gw.runtime.resources._cursor[MODEL] = 0              # 实盘池序里 zcode 就在最前

    resp = await _ask(client, gw)
    assert resp.status_code == 400, f"被换号吸收了？codes={resp.status_code}"
    assert len(zcode_upstream.hits) == 1, (
        f"这条请求试了 {len(zcode_upstream.hits)} 个号，判据对象变了：{zcode_upstream.mids_hit()}")
    assert zcode_upstream.hits[0]["mid"] == MIDS["zc-1"]
    ev = await _event(gw)
    assert ev["switch_count"] == 0 and len(ev["resource_attempts"]) == 1
async def test_z18_bad_account_keeps_its_slot_forever(zcode_upstream, make_gateway, client):
    """**复核 D-1 的长期后果**：4xx 不计 C、不冷却 ⇒ 坏号**永远留在活跃组里占名额**，
    每一轮轮转都会再撞上它（不是「偶发」，是稳态）。"""
    _login_all()
    zcode_upstream.set_all("ok")
    zcode_upstream.behavior[MIDS["zc-1"]] = {"kind": "http", "status": 400,
                                             "payload": {"code": 3012, "msg": "unusual activity"}}
    gw = await make_gateway(_cfg(zcode_upstream.port, x=2))

    for _ in range(8):
        await _ask(client, gw)
    st = gw.resource("res-z1", VENDOR_MODEL)
    assert st.C == 0 and st.status == "active", f"坏号被移出了生效集：C={st.C} status={st.status}"
    assert zcode_upstream.mids_hit().count(MIDS["zc-1"]) >= 2, (
        f"只撞一次？不符合轮转稳态：{zcode_upstream.mids_hit()}")


async def test_z19_fake_success_resets_counter(zcode_upstream, make_gateway, client):
    """**契约（S-1，2026-10-05 起生效）**：200 空信封走**故障支路** ⇒ `note_failure` 把连续
    失败计数 +1、预留释放不结算 ⇒ 假成功不再清洗坏号的观测面。全部 4 个号都回空时
    （旧实现会把 4 个号都记成健康），客户端拿 503。"""
    _login_all()
    zcode_upstream.set_all("envelope200", code=3012)
    gw = await make_gateway(_cfg(zcode_upstream.port, x=1, y=2))

    st = gw.resource("res-z1", VENDOR_MODEL)
    st.C = 3                       # 白盒置一个"已经坏过三次"的起点
    resp = await _ask(client, gw)
    assert resp.status_code == 503, f"全部候选回空应 503 终局：{resp.status_code}"
    assert st.C >= 1, f"零内容未计入失败计数：C={st.C}"
    assert st.quota.reserved == 0, "预留未释放"


# ============ ⑦ 对照：D-3 那条死分支与协议无关 ============

async def test_z20_zero_chunk_stream_on_a_plain_openai_channel(vendor, make_gateway, client):
    """**对照实验（S-1 后更新）**：把「一帧内容都没吐」的形状打在**普通按 Key 接入的
    OpenAI 通道**上——零内容在**任何协议**上都按可重试故障走换号；全部候选回空时
    客户端拿 503 `EMPTY_UPSTREAM_CONTENT`（不再有 NameError 500 或 200 空流）。"""
    from tests.integration.conftest import chat_res, gateway_config
    from tests.integration.fakevendor import StreamOk

    vendor.set("sk-A", StreamOk(chunks=[]))
    gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
    resp = await client.post(f"{gw.base_url}/v1/chat/completions",
                             json={"model": "test-model", "stream": True,
                                   "messages": [{"role": "user", "content": "hi"}]})
    await gw.drain_events()
    ev = gw.read_events()[-1]
    print("\n[Z20 读数] http=%s body=%r event_status=%s"
          % (resp.status_code, resp.text[:160], ev.get("status")))
    assert resp.status_code == 503, f"实际={resp.status_code} body={resp.text[:200]}"
    assert "零内容" in resp.text  # 终局错误体必须如实说明「零内容」，不是无报错的失败
    assert ev["status"] == "failed"


async def test_z21_premise_gap_dispatched_inside_an_advertised_model(
        zcode_upstream, vendor, make_gateway, client):
    """**现状刻画 = 缺陷证据（实盘形状，Z12 的加强版）**：实盘 `glm-5.3-flash` 不是「只有 zcode」，
    而是 16 个 zcode 号排在**前面** + 12 个健康供应商在后面 ⇒ 模型照常被 `/v1/models` 声明，
    而**第一条请求仍然先打到前提未验证的 zcode 号**（Z12 用的是 zcode-only 模型，挡得住声明、
    挡不住这个真实形状）。"""
    from tests.integration.conftest import chat_res, gateway_config

    _login_all()
    zcode_upstream.set_all("ok")
    cfg = gateway_config(vendor.port, models=[chat_res(
        "A", resources=[{"resource": "res-z1", "model": VENDOR_MODEL, "enabled": True},
                        {"resource": "res-z2", "model": VENDOR_MODEL, "enabled": True},
                        {"resource": "res-A", "model": "vm-A", "enabled": True}])])
    cfg["resources"] += [
        {"id": "res-z1", "name": "ZCode zc-1", "vendor": "ZCode", "account": "zc-1",
         "product": "zcode", "account_ref": "zc-1", "protocol": "anthropic", "preset": "",
         "base_url": f"http://127.0.0.1:{zcode_upstream.port}/api/v1/zcode-plan/anthropic",
         "api_key": "", "enabled": True, "access_mode": "plan"},
        {"id": "res-z2", "name": "ZCode zc-2", "vendor": "ZCode", "account": "zc-2",
         "product": "zcode", "account_ref": "zc-2", "protocol": "anthropic", "preset": "",
         "base_url": f"http://127.0.0.1:{zcode_upstream.port}/api/v1/zcode-plan/anthropic",
         "api_key": "", "enabled": True, "access_mode": "plan"}]
    cfg["scheduling"] = {"max_active_per_model": 2, "fail_threshold": 2,
                         "retry_per_request": 1, "retry_backoff_seconds": 0.0,
                         "quota_retry": 1, "quota_backoff_base_seconds": 0.0,
                         "cooldown_seconds": 30, "cooldown_seconds_plan": 45}
    gw = await make_gateway(cfg)

    listing = await client.get(f"{gw.base_url}/v1/models")
    advertised = {d["id"] for d in listing.json()["data"]}
    assert "test-model" in advertised, "有健康供应商在场时模型应当照常对外声明：这才是实盘形状"

    resp = await client.post(f"{gw.base_url}/v1/chat/completions",
                             json={"model": "test-model",
                                   "messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200, resp.text
    assert len(zcode_upstream.hits) == 1, (
        f"首选承接者不是 zcode：zcode 命中 {len(zcode_upstream.hits)} 次")
    assert zcode_upstream.hits[0]["mid"] == MIDS["zc-1"]


async def test_z22_same_shape_rotates_once_reclassified(zcode_upstream, make_gateway, client):
    """**撤证 / 反证（同时验修法方向）**：与 Z3 完全同形，只把分类改一下
    （既有 `error_rules` 配置面：`{http:400, class:RETRYABLE}`）⇒ 同一批号立刻**会换号**、
    客户端拿到 200、坏号开始计 C。
    🔴 两点结论：① Z3 那条判据不是空转（判据对象真的会变）；② D-1 的正解在**分类**，
    不在「派活时跳过坏号」（Q35-③ 红线）。⚠️ 但按 HTTP 整码覆写会把**真正的客户端 400**
    也变成可重试 ⇒ 生产修法必须是**带 type 的精确覆写**（`ErrorRule.type` 非空那条支路，
    `core/errors.py:191-192`），所以还需要 `ZcodeOut` 先把信封里的 `code` 归一化成 error_type。"""
    _login_all()
    zcode_upstream.set_all("ok")
    zcode_upstream.behavior[MIDS["zc-1"]] = {"kind": "http", "status": 400,
                                             "payload": {"code": 3012, "msg": "unusual activity"}}
    cfg = _cfg(zcode_upstream.port, x=1)
    cfg["error_rules"] = [{"http": 400, "type": "", "class": "RETRYABLE"}]
    gw = await make_gateway(cfg)

    resp = await _ask(client, gw)
    assert resp.status_code == 200, f"改了分类仍不换号？{resp.status_code} {resp.text[:200]}"
    assert len(zcode_upstream.hits) >= 2, zcode_upstream.mids_hit()
    assert MIDS["zc-1"] in zcode_upstream.mids_hit()
    ev = await _event(gw)
    assert ev["switch_count"] >= 1, ev
