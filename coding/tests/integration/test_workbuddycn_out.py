"""workbuddycn 出站**端到端**（Q44；照抄 `test_buddy_out.py` 同型，差异全在本产品档案）。

判据 = 「账号 → 资源 → `/v1/chat/completions`」全链路在**假上游**上跑通：

· 非流式 / 流式各一条：网关返回内容正常、`model` 被统一名替换；
· 假上游收到的**身份头**（Bearer=账号令牌、X-Product=**归属名 `WorkBuddy`**、
  X-IDE-Version=`5.5.2`、X-Product-Code=`workbuddy`、UA=中国版形态）逐项断言；
· 🔴 **不注入首条 system**（中国版通道没有国际版那条 11128 脾气，方案 §3.4 实测
  首条 user 直接 200）—— 客户端消息**一字不动**透传；
· 配置里的 `api_key` **绝不出现**在出站头里（铁律 1）；
· 「通道未获批」400 → 换号续跑（族共用判据，本产品同样受益）；普通 400 原样透传。

假上游 = 本文件自带的 Starlette 应用（只实现 `/v2/chat/completions`，记录请求）；
网关走 `make_gateway` 基建（随机端口 + 临时配置 + 临时 usage 目录）。
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

CONFIG_KEY = "sk-config-key-must-not-be-sent"
TOKEN = "TOKEN-FROM-WBCN-ACCOUNT-E2E"


class _FakeWbcnUpstream:
    """假 WorkBuddy 中国版上游：`POST /v2/chat/completions`（OpenAI 形状 + 标准 SSE）。

    🔴 与 `test_buddy_out.py` 的假件有一处**故意不同**：**不做**「首条须 system」的
    11128 判定 —— 中国版通道实测没有这条限制（方案 §3.4 变体 1：首条 user 直接 200）。
    假件若照抄国际版那条判定，「不注入 system」这条判据就永远没有对象（= 空判据）。
    """

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.app = Starlette(routes=[
            Route("/v2/chat/completions", self._chat, methods=["POST"])])

    async def _chat(self, request: Request):
        body = await request.json()
        self.requests.append({"path": request.url.path,
                              "headers": dict(request.headers), "body": body})
        token = request.headers.get("authorization", "")
        if token == "Bearer BAD-TOKEN":
            # 🔴 复刻本产品族的「该通道对这条模型未获批」400（判据同族共用，
            # `upstream/buddy/out.py::_UNAPPROVED_CHANNEL_MESSAGE`）—— 网关须据此换号续跑。
            return JSONResponse({"code": 11128,
                                 "msg": "Illegal API invocation from an unapproved channel",
                                 "requestId": "fake-wbcn"}, status_code=400)
        if not body.get("stream"):
            # 🔴 复刻真实通道的**唯一**接受形态：非流式一律 400 code 11101
            # （中国版 2026-10-10 实测同形，方案 §3.4 变体 A）。
            return JSONResponse({"code": 11101,
                                 "msg": "Non-stream chat request is currently not supported",
                                 "requestId": "fake-wbcn"}, status_code=400)
        return StreamingResponse(self._sse(), media_type="text/event-stream")

    async def _sse(self):
        frames = [
            {"id": "c", "object": "chat.completion.chunk", "model": "hy3",
             "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
            {"id": "c", "object": "chat.completion.chunk", "model": "hy3",
             "choices": [{"index": 0, "delta": {"content": "你"}, "finish_reason": None}]},
            {"id": "c", "object": "chat.completion.chunk", "model": "hy3",
             "choices": [{"index": 0, "delta": {"content": "好"}, "finish_reason": None}]},
            {"id": "c", "object": "chat.completion.chunk", "model": "hy3",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 5, "completion_tokens": 3}},
        ]
        for frame in frames:
            yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"


@pytest.fixture
async def wbcn_upstream():
    fake = _FakeWbcnUpstream()
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


def _cfg(port: int, *, account: str = "wbcn-acc-1", model_name: str = "wbcn-model",
         vendor_model: str = "hy3") -> dict:
    return {
        "resources": [{
            "id": "res-wbcn", "name": "中国版资源", "vendor": "", "preset": "",
            "account": account, "product": "workbuddycn", "account_ref": account,
            "protocol": "openai", "base_url": f"http://127.0.0.1:{port}",
            "api_key": CONFIG_KEY,        # 故意留着：出站必须**不用**它（铁律 1）
            "enabled": True, "access_mode": "api",
        }],
        "models": [{"name": model_name, "endpoint": "chat",
                    "resources": [{"resource": "res-wbcn", "model": vendor_model}]}],
    }


def _body(model: str = "wbcn-model", **over) -> dict:
    data = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    data.update(over)
    return data


def _sse_frames(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if payload == "[DONE]":
            continue
        out.append(json.loads(payload))
    return out


# ============ 非流式（内部聚合）+ 中国版身份头 + 不注入 system ============

async def test_wbcn_nonstream_end_to_end(wbcn_upstream, make_gateway, client):
    store.commit_login("workbuddycn", "wbcn-acc-1",
                       {"access_token": TOKEN, "user_id": "u9"}, {})
    gw = await make_gateway(_cfg(wbcn_upstream.port))

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "你好"
    assert data["model"] == "wbcn-model"
    assert data["usage"] == {"prompt_tokens": 5, "completion_tokens": 3}

    assert len(wbcn_upstream.requests) == 1
    req = wbcn_upstream.requests[0]
    assert req["path"] == "/v2/chat/completions"          # 族共用取证路径
    assert req["headers"]["authorization"] == f"Bearer {TOKEN}"
    assert CONFIG_KEY not in json.dumps(req["headers"])   # 配置 Key 绝不外发（铁律 1）
    assert req["headers"]["x-domain"] == "127.0.0.1"      # 与实际请求基址一致
    # 🔴 推理面归属头 = 中国版档案取值（X-Product/X-IDE-* = `WorkBuddy`，版本 5.5.2）
    assert req["headers"]["x-product"] == "WorkBuddy"
    assert req["headers"]["x-ide-name"] == "WorkBuddy"
    assert req["headers"]["x-ide-type"] == "WorkBuddy"
    assert req["headers"]["x-ide-version"] == "5.5.2"
    assert req["headers"]["x-agent-purpose"] == "conversation"
    assert req["headers"]["x-product-code"] == "workbuddy"
    assert req["headers"]["user-agent"] == "WorkBuddy/5.5.2 WorkBuddy/5.5.2 CLI/5.5.2"
    assert req["body"]["model"] == "hy3"
    assert req["body"]["stream"] is True                  # 通道只接受流式：网关内部改流式再聚合
    # 🔴 反向判据（本文件的核心差异）：中国版**收得下**首条非 system 的请求
    #    ⇒ 网关**不注入**引导文案，消息一字不动透传。
    #    撤证方向 = 给 `_PROFILE.system_first_text` 填值 ⇒ messages 首位被塞 system ⇒ 本用例必红。
    assert req["body"]["messages"] == [{"role": "user", "content": "hi"}]

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == "中国版资源/hy3"
    assert ev["input_tokens"] == 5 and ev["output_tokens"] == 3


async def test_wbcn_stream_end_to_end(wbcn_upstream, make_gateway, client):
    store.commit_login("workbuddycn", "wbcn-acc-1", {"access_token": TOKEN}, {})
    gw = await make_gateway(_cfg(wbcn_upstream.port))

    resp = await client.post(f"{gw.base_url}/v1/chat/completions",
                             json=_body(stream=True))
    assert resp.status_code == 200, resp.text
    assert "text/event-stream" in resp.headers["content-type"]
    frames = _sse_frames(resp.text)
    text = "".join(f["choices"][0]["delta"].get("content", "")
                   for f in frames if f.get("choices"))
    assert text == "你好"
    assert {f["model"] for f in frames if f.get("model")} == {"wbcn-model"}


async def test_client_system_message_passes_through_untouched(wbcn_upstream, make_gateway,
                                                              client):
    """客户端自己写了 system ⇒ 内容一字不改、位置不动（中国版根本没有补齐这回事）。"""
    store.commit_login("workbuddycn", "wbcn-acc-1", {"access_token": TOKEN}, {})
    gw = await make_gateway(_cfg(wbcn_upstream.port))

    mine = "本项目只在 staging 环境操作"
    body = _body(messages=[{"role": "user", "content": "hi"},
                           {"role": "system", "content": mine}])
    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=body)
    assert resp.status_code == 200, resp.text
    sent = wbcn_upstream.requests[-1]["body"]["messages"]
    assert sent == [{"role": "user", "content": "hi"},
                    {"role": "system", "content": mine}]   # 顺序与内容逐字未动


# ============ 资源级不可承接（通道未获批 400）→ 换号续跑（族共用判据）============

def _two_account_cfg(port: int, *, bad_token: str) -> dict:
    """两条资源（两个账号令牌）指向同一假上游；第一条用 `bad_token` 恒回 400，第二条健康。"""
    return {
        "resources": [
            {"id": "res-wbcn-bad", "name": "坏通道", "vendor": "", "preset": "",
             "account": f"wbcn-{bad_token.lower()}", "product": "workbuddycn",
             "account_ref": f"wbcn-{bad_token.lower()}",
             "protocol": "openai", "base_url": f"http://127.0.0.1:{port}",
             "api_key": "", "enabled": True, "access_mode": "api"},
            {"id": "res-wbcn-good", "name": "健康通道", "vendor": "", "preset": "",
             "account": "wbcn-good", "product": "workbuddycn", "account_ref": "wbcn-good",
             "protocol": "openai", "base_url": f"http://127.0.0.1:{port}",
             "api_key": "", "enabled": True, "access_mode": "api"},
        ],
        "models": [{"name": "wbcn-model", "endpoint": "chat",
                    "resources": [{"resource": "res-wbcn-bad", "model": "hy3"},
                                  {"resource": "res-wbcn-good", "model": "hy3"}]}],
    }


async def test_unapproved_channel_400_fails_over_and_never_disables(wbcn_upstream,
                                                                    make_gateway, client):
    """「通道未获批」400 对中国版同样 = 资源级不可承接（族共用 `_is_resource_scoped_rejection`）：
    换号续跑（客户端 200）、坏资源进冷却不计 C、只被打 1 次。"""
    store.commit_login("workbuddycn", "wbcn-bad-token", {"access_token": "BAD-TOKEN"}, {})
    store.commit_login("workbuddycn", "wbcn-good", {"access_token": "GOOD-TOKEN"}, {})
    gw = await make_gateway(_two_account_cfg(wbcn_upstream.port, bad_token="BAD-TOKEN"))

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 200, f"资源级 400 未换号：{resp.status_code} {resp.text[:200]}"
    assert resp.json()["choices"][0]["message"]["content"] == "你好"

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success"
    assert ev["final_resource"] == "健康通道/hy3"          # 换到第二条
    assert ev["switch_count"] == 1
    bad_calls = [r for r in wbcn_upstream.requests
                 if r["headers"]["authorization"] == "Bearer BAD-TOKEN"]
    assert len(bad_calls) == 1, f"坏资源只该被打 1 次：{len(bad_calls)}"

    st = gw.runtime.resources.registry.get(("res-wbcn-bad", "hy3"))
    assert st.status == "cooldown", f"坏号应进冷却而非判死：{st.status}"
    assert st.C == 0, f"资源级不可承接不该计 C：C={st.C}"
