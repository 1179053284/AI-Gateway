"""学习轮 V1 实证复现件（**临时文件，不是收编判据**）。

目的：把调研报告 `docs/research/27-DSH插件网关与模型清单调研-结论.md` §3 的 L1 / L4
两条断言从"读码推断"升级为"行为实测"。本文件**只观察、只打印、只断言当前真实行为**，
不修改任何生产源码与既有测试。

跑法：
    cd coding && .venv/bin/python -m pytest -q tests/verify_v1_stream_repro.py -s

三条上游形状（L1）：
  A. 只发几个 chunk 就**干净收尾**（既不发 finish_reason、也不发 `data: [DONE]`）
  B. 发了 finish_reason 但**从不发** `[DONE]`（现实里确有这类厂商 ⇒ 误杀风险的对象）
  C. 发了 `[DONE]` 但**整条流没有** finish_reason（反向形状）
外加 trae / qoder 两处 `_DEFAULT_FINISH` 的直接复现（D / E）。

L4：请求 `reasoning_effort=high` 打到目录只声明 `low/medium` 的资源 ⇒ 打印
最终出站 body、事件日志、返回给客户端的体，另配两条对照组。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import AsyncIterator

import httpx
import pytest
import uvicorn
import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from tests.integration.conftest import GatewayHandle

CHAT_URL = "/v1/chat/completions"


# ─────────────────────────────────────────────────────────────────────────────
# 可编程假上游（本文件自带；不动 tests/integration/fakevendor.py）
# ─────────────────────────────────────────────────────────────────────────────

#: 每种形状对应一个 api key（网关按 key 出站 ⇒ 用 key 选形状，天然隔离）
SHAPES = ("A_eof_no_finish", "B_finish_no_done", "C_done_no_finish",
          "D_role_only_eof", "ECHO_BODY")


class ShapeVendor:
    """按 Bearer key 分派 SSE 形状的假上游；记录收到的出站 body。"""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.app = Starlette(routes=[
            Route("/v1/chat/completions", self._chat, methods=["POST"]),
        ])

    def bodies_for(self, shape: str) -> list[dict]:
        return [b for k, b in self.requests if k == f"sk-{shape}"]

    @staticmethod
    def _line(payload) -> str:
        if isinstance(payload, str):
            return f"data: {payload}\n\n"
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def _chunk(self, delta: dict, finish=None) -> dict:
        return {"id": "chatcmpl-shape", "object": "chat.completion.chunk",
                "model": "vendor-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

    async def _chat(self, request: Request) -> Response:
        key = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        body = await request.json()
        self.requests.append((key, body))
        shape = key.removeprefix("sk-")

        if shape == "ECHO_BODY":
            # 非流式：把**出站 body** 原样回显进响应，供 L4 读"最终发出去的是什么"
            return JSONResponse({
                "id": "chatcmpl-echo", "object": "chat.completion", "model": "vendor-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "echo_upstream_body": body,
            })

        async def gen():
            yield self._line(self._chunk({"role": "assistant"}))
            if shape == "D_role_only_eof":
                # 🔴 一个内容字节都没有就干净收尾（trae 适配器对这种情况明确抛错，
                # 通用 OpenAI 兼容路径没有这一层 —— 见 L1-D2）
                return
            yield self._line(self._chunk({"content": "第一部"}))
            if shape == "A_eof_no_finish":
                # 🔴 干净收尾：不抛异常、不发 finish、不发 usage、不发 [DONE]
                yield self._line(self._chunk({"content": "第二部"}))
                return
            yield self._line(self._chunk({"content": "第二部"}))
            if shape == "B_finish_no_done":
                yield self._line(self._chunk({}, finish="stop"))
                yield self._line({"id": "chatcmpl-shape",
                                  "usage": {"prompt_tokens": 10, "completion_tokens": 7}})
                return  # 没有 [DONE]
            # C_done_no_finish
            yield self._line("[DONE]")

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})


@pytest.fixture
async def shape_vendor():
    v = ShapeVendor()
    config = uvicorn.Config(v.app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.get_running_loop().create_task(server.serve())
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.01)
    assert server.started, "ShapeVendor 启动超时"
    v.port = server.servers[0].sockets[0].getsockname()[1]
    yield v
    server.should_exit = True
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(task, timeout=10)


# ─────────────────────────────────────────────────────────────────────────────
# 网关侧脚手架（与 tests/integration/conftest.py 同形，但 enums 可控）
# ─────────────────────────────────────────────────────────────────────────────

def cfg_for(port: int, *, triples: list[tuple[str, str, str]]) -> dict:
    """triples: [(资源后缀, 上游形状 key, 供应商模型名)] ⇒ 单资源单引用一条网关模型。

    🔴 资源后缀 / 上游形状 / 供应商模型名三者**分开**：形状靠 Bearer key 选，
    目录档位靠供应商模型名查（`enum_pool.get(vendor_model)`），混用一个名字会串。
    """
    resources, refs = [], []
    for suffix, shape, vm in triples:
        resources.append({"id": f"res-{suffix}", "name": f"资源{suffix}",
                          "access_mode": "api", "protocol": "openai",
                          "base_url": f"http://127.0.0.1:{port}/v1",
                          "api_key": f"sk-{shape}"})
        refs.append({"resource": f"res-{suffix}", "model": vm})
    return {
        "resources": resources,
        "models": [{"name": "gw-model", "endpoint": "chat", "resources": refs}],
        "scheduling": {"fail_threshold": 2, "retry_backoff_seconds": 0},
    }


@pytest.fixture
async def make_gw(tmp_path):
    from model_gateway.main import create_app

    made: list[GatewayHandle] = []
    n = 0

    async def _make(cfg_dict: dict, enums: dict | None = None) -> GatewayHandle:
        nonlocal n
        config_path = tmp_path / f"v1cfg-{n}.yaml"
        usage_dir = tmp_path / f"v1usage-{n}"
        config_path.write_text(yaml.safe_dump(cfg_dict, allow_unicode=True),
                               encoding="utf-8")
        enums_path = tmp_path / f"v1enums-{n}.yaml"
        if enums is not None:
            enums_path.write_text(yaml.safe_dump(enums, allow_unicode=True),
                                  encoding="utf-8")
        app = create_app(config_path=config_path, usage_dir=usage_dir,
                         enums_path=enums_path)
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        server = uvicorn.Server(config)
        task = asyncio.get_running_loop().create_task(server.serve())
        for _ in range(500):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started, "网关启动超时"
        port = server.servers[0].sockets[0].getsockname()[1]
        made.append(GatewayHandle(f"http://127.0.0.1:{port}", config_path, usage_dir,
                                  app, server, task))
        n += 1
        return made[-1]

    yield _make
    for gw in made:
        gw._server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(gw._task, timeout=10)


@pytest.fixture
async def hclient():
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), trust_env=False) as c:
        yield c


def _sse_lines(text: str) -> list:
    out = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload.strip() == "[DONE]":
            out.append("[DONE]")
        else:
            with contextlib.suppress(json.JSONDecodeError):
                out.append(json.loads(payload))
    return out


def _report(title: str, obj) -> None:
    print(f"\n===== {title} =====\n{json.dumps(obj, ensure_ascii=False, indent=2)}")


# ─────────────────────────────────────────────────────────────────────────────
# L1 —— 流式终态
# ─────────────────────────────────────────────────────────────────────────────

async def _run_stream(shape: str, make_gw, hclient, vendor, *, remaining: int | None = None):
    gw = await make_gw(cfg_for(vendor.port, triples=[(shape, shape, shape)]))
    state = gw.resource(f"res-{shape}", shape)
    quota_before: dict | None = None
    if remaining is not None:
        # 只动**我自己这台临时网关**的运行态（不碰源码/配置）：让额度余量"已知"，
        # 以便读清"成功结算"到底扣了什么
        gw.runtime.resources.set_quota(state, remaining)
        quota_before = {"reserved": state.quota.reserved, "remaining": state.quota.remaining}
    resp = await hclient.post(f"{gw.base_url}{CHAT_URL}", json={
        "model": "gw-model", "stream": True,
        "messages": [{"role": "user", "content": "hi"}]})
    await gw.drain_events()
    events = _sse_lines(resp.text)
    finishes = [c["choices"][0].get("finish_reason") for c in events
                if isinstance(c, dict) and c.get("choices")
                and c["choices"][0].get("finish_reason")]
    content = "".join((c["choices"][0].get("delta") or {}).get("content") or ""
                      for c in events if isinstance(c, dict) and c.get("choices"))
    err_frames = [c for c in events if isinstance(c, dict) and c.get("error")]
    ev = gw.read_events()[0] if gw.read_events() else None
    out = {
        "http_status": resp.status_code,
        "客户端收到帧序": [("[DONE]" if c == "[DONE]" else "chunk") for c in events],
        "客户端可见 content": content,
        "客户端可见 finish_reason": finishes,
        "客户端可见 error 帧": err_frames,
        "事件日志 status": (ev or {}).get("status"),
        "事件日志 error_summary": (ev or {}).get("error_summary"),
        "事件日志 output_tokens": (ev or {}).get("output_tokens"),
        "事件日志 usage_source": (ev or {}).get("usage_source"),
        "事件日志 switch_count": (ev or {}).get("switch_count"),
        "资源连续失败计数 C": state.C,
        "资源状态": state.status,
        "额度池 reserved": state.quota.reserved,
        "额度池 remaining": state.quota.remaining,
    }
    if quota_before is not None:
        out["额度池 请求前"] = quota_before
        out["额度池 变化"] = {"reserved": state.quota.reserved - quota_before["reserved"],
                          "remaining": state.quota.remaining - quota_before["remaining"]}
    return out


async def test_L1_A_upstream_eof_without_finish_or_done(make_gw, hclient, shape_vendor):
    """形状 A：上游只发内容就干净收尾 ⇒ 我方现在报的是什么（额度余量刻意设为已知）。"""
    got = await _run_stream("A_eof_no_finish", make_gw, hclient, shape_vendor, remaining=10)
    _report("L1-A 上游 EOF（无 finish_reason / 无 [DONE]）", got)
    # 🔴 当前行为（实测钉住，非期望行为）：
    assert got["http_status"] == 200
    assert got["客户端可见 finish_reason"] == [], "上游没说过终止原因"
    assert got["客户端收到帧序"][-1] == "[DONE]", "网关替上游补发了 [DONE]"
    assert got["客户端可见 error 帧"] == [], "没有任何 incomplete_stream/error 帧"
    assert got["事件日志 status"] == "success"
    assert got["事件日志 error_summary"] is None
    assert got["资源连续失败计数 C"] == 0, "note_success 已把 C 清零"
    # 结算语义实测：settle_quota 只归还预留，**不动 remaining**（本地没烧额度这回事）
    assert got["额度池 变化"] == {"reserved": 0, "remaining": 0}


async def test_L1_B_finish_without_done(make_gw, hclient, shape_vendor):
    """形状 B：上游发了 finish_reason 但不发 [DONE]（现实存在的厂商形状）。"""
    got = await _run_stream("B_finish_no_done", make_gw, hclient, shape_vendor)
    _report("L1-B 上游有 finish_reason、无 [DONE]", got)
    assert got["事件日志 status"] == "success"
    assert got["客户端可见 finish_reason"] == ["stop"], "终止原因是上游自己说的"


async def test_L1_C_done_without_finish(make_gw, hclient, shape_vendor):
    """形状 C：上游发了 [DONE] 但整条流没有 finish_reason。"""
    got = await _run_stream("C_done_no_finish", make_gw, hclient, shape_vendor)
    _report("L1-C 上游有 [DONE]、无 finish_reason", got)
    assert got["客户端可见 finish_reason"] == []
    assert got["事件日志 status"] == "success"


async def test_L1_D2_zero_content_eof(make_gw, hclient, shape_vendor):
    """形状 D2：上游只发了 role 帧就干净收尾（零内容 EOF）。

    🔴 判据随 S-1 前进（2026-10-05 架构审计）：零内容不再记 success——按可重试故障
    走换号，全部候选回空 ⇒ 客户端 503、事件 failed。旧形状（200 空流 + success）是
    被修掉的缺陷，原断言见 git 历史。
    """
    got = await _run_stream("D_role_only_eof", make_gw, hclient, shape_vendor)
    _report("L1-D2 上游零内容 EOF（只有 role 帧）", got)
    assert got["http_status"] == 503, "零内容应 503 终局（换号后仍回空）"
    assert got["事件日志 status"] == "failed", "零内容不得记 success"


# ── D / E：适配器层"缺失即补 stop"的直接复现（不涉及网络） ──

def test_L1_D_trae_default_finish_is_a_real_fabrication():
    """trae：上游发了 `done` 事件但没带 finish_reason ⇒ 我方替它写 "stop"。

    对照 `upstream/trae/out.py:49` `_DEFAULT_FINISH = "stop"` 与 `:190-192`。
    反向对照：上游**根本没发 done 事件**（EOF）时，本适配器不补终态帧。
    """
    from model_gateway.upstream.trae import protocol
    from model_gateway.upstream.trae.out import TraeOut

    class Stub(TraeOut):
        def __init__(self, events):  # 跳过 ProductOutAdapter.__init__（不读凭据）
            self._events_list = events

        async def _events(self, vendor_model, body, timeout) -> AsyncIterator:
            for e in self._events_list:
                yield e

    async def collect(events):
        out = []
        async for chunk in Stub(events).chat_stream("k", "vm", {}, 5.0):
            out.append(chunk)
        return out

    # D-1：done 事件不带 finish_reason
    with_finish = asyncio.run(collect([
        protocol.SoloEvent(event="output", response="一段"),
        protocol.SoloEvent(event="done", finish_reason=""),
    ]))
    # D-2：上游 EOF，连 done 都没有
    no_done = asyncio.run(collect([
        protocol.SoloEvent(event="output", response="一段"),
    ]))
    _report("L1-D trae：done 事件不带 finish_reason", {
        "末帧": with_finish[-1], "末帧 finish_reason":
            (with_finish[-1].get("choices") or [{}])[0].get("finish_reason"),
        "上游 EOF 无 done 时的末帧": no_done[-1],
        "上游 EOF 无 done 时是否补了终态帧":
            bool((no_done[-1].get("choices") or [{}])[0].get("finish_reason")),
    })
    assert (with_finish[-1]["choices"][0]["finish_reason"]) == "stop", "编造发生"
    assert no_done[-1]["choices"][0].get("finish_reason") is None, "EOF 路径不编造"


def test_L1_E_qoder_nonstream_finish_or_stop():
    """qoder：流里没有 finish_reason ⇒ 聚合出的**非流式**响应写 finish_reason="stop"。

    对照 `upstream/qoder/out.py:221` `finish or "stop"`。
    """
    from model_gateway.upstream.qoder.out import QoderOut

    class Stub(QoderOut):
        def __init__(self, chunks):  # 跳过 __init__（不签名、不读凭据）
            self._chunks = chunks

        async def chat_stream(self, key, vendor_model, body, timeout):
            for c in self._chunks:
                yield c

    chunks = [
        {"id": "x", "object": "chat.completion.chunk",
         "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "x", "object": "chat.completion.chunk",
         "choices": [{"index": 0, "delta": {"content": "半句"}, "finish_reason": None}]},
    ]
    got = asyncio.run(Stub(chunks).chat_nonstream("k", "vm", {}, 5.0))
    _report("L1-E qoder：流无 finish_reason 时的非流式聚合", {
        "content": got["choices"][0]["message"]["content"],
        "finish_reason": got["choices"][0]["finish_reason"],
    })
    assert got["choices"][0]["finish_reason"] == "stop", "编造发生（上游从未说过）"


# ─────────────────────────────────────────────────────────────────────────────
# L4 —— 档位改写可见性
# ─────────────────────────────────────────────────────────────────────────────

ENUM_LOW_MED = {"entries": [{
    "name": "vm-lowmed", "display": "低中档模型", "vendor": "测试厂商",
    "endpoint": "chat", "reasoning": True, "effort_levels": ["low", "medium"],
    "context_window": 200000, "max_output": 8000,
}]}

ENUM_NO_LEVELS = {"entries": [{
    "name": "vm-unknown", "display": "无档位信息模型", "vendor": "测试厂商",
    "endpoint": "chat", "context_window": 200000, "max_output": 8000,
}]}


async def _one_shot(eums, asked_effort, vendor_model, make_gw, hclient, shape_vendor):
    gw = await make_gw(cfg_for(shape_vendor.port, triples=[("X", "ECHO_BODY", vendor_model)]),
                      enums=eums)
    body = {"model": "gw-model", "stream": False,
            "messages": [{"role": "user", "content": "hi"}]}
    if asked_effort is not None:
        body["reasoning_effort"] = asked_effort
    resp = await hclient.post(f"{gw.base_url}{CHAT_URL}", json=body)
    await gw.drain_events()
    sent = shape_vendor.bodies_for("ECHO_BODY")[-1]
    ev = gw.read_events()[0]
    return {
        "入站请求 reasoning_effort": asked_effort,
        "出站 body（上游实际收到）": sent,
        "出站 body 里的 reasoning_effort": sent.get("reasoning_effort"),
        "返回给客户端的体里有无改写标注": [
            k for k in resp.json() if "effort" in k.lower() or "degrad" in k.lower()],
        "事件日志键集合": sorted(ev.keys()),
        "事件日志 status": ev["status"],
        "事件日志里有无 effort 痕迹": ("effort" in json.dumps(ev).lower()),
        "目录声明的档位": (ENUM_LOW_MED if vendor_model == "vm-lowmed"
                       else ENUM_NO_LEVELS)["entries"][0].get("effort_levels", []),
    }


async def test_L4_high_to_low_medium_resource(make_gw, hclient, shape_vendor):
    """L4 主证：请求 high，资源只声明 low/medium ⇒ 出站被改成什么、哪里看得见。"""
    got = await _one_shot(ENUM_LOW_MED, "high", "vm-lowmed", make_gw, hclient, shape_vendor)
    _report("L4 主证（high → 只支持 low/medium 的资源）", got)
    assert got["出站 body 里的 reasoning_effort"] == "medium", "静默降级已发生"
    assert got["事件日志里有无 effort 痕迹"] is False, "事件日志零痕迹"


async def test_L4_control_supported_effort_passthrough(make_gw, hclient, shape_vendor):
    """对照 1：请求 medium（在支持表内）⇒ 原样透传，不该有任何改写。"""
    got = await _one_shot(ENUM_LOW_MED, "medium", "vm-lowmed", make_gw, hclient, shape_vendor)
    _report("L4 对照 1（medium，支持表内）", got)
    assert got["出站 body 里的 reasoning_effort"] == "medium"


async def test_L4_control_unknown_catalog(make_gw, hclient, shape_vendor):
    """对照 2：目录没有档位信息 ⇒ 不臆断、原样透传 high（这半是对的）。"""
    got = await _one_shot(ENUM_NO_LEVELS, "high", "vm-unknown", make_gw, hclient, shape_vendor)
    _report("L4 对照 2（目录无档位信息）", got)
    assert got["出站 body 里的 reasoning_effort"] == "high"
