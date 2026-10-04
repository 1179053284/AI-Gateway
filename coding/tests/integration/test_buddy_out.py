"""buddy / workbuddy 出站**端到端**（§22.3/§22.5；M6-5a 试点）。

判据 = 「账号 → 资源 → `/v1/chat/completions`」全链路在**假上游**上跑通：

· 非流式 / 流式各一条：网关返回内容正常、`model` 被统一名替换；
· 假上游收到的**路径**（`/v2/chat/completions`，取证值）、**身份头**
  （Bearer=账号令牌、X-Domain=实际基址主机、X-Product=**归属名**（`buddy-adapter.ts:1577`）、
  X-Product-Code、X-IDE-Name/Type/Version、X-Agent-Purpose、UA）与**请求体**
  （model=映射里的厂商模型名）逐项断言；
· 配置里的 `api_key` **绝不出现**在出站头里（铁律 1：凭据只在账号目录）；
· 缺凭据 → fail closed + **零次上游请求** + 可读错误；
· 重新登录后**不重启**网关，下一次请求即用新令牌（不缓存凭据）。

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
TOKEN = "TOKEN-FROM-ACCOUNT-E2E"


class _FakeBuddyUpstream:
    """假 CodeBuddy 上游：`POST /v2/chat/completions`（OpenAI 形状 + 标准 SSE）。"""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.app = Starlette(routes=[
            Route("/v2/chat/completions", self._chat, methods=["POST"])])

    async def _chat(self, request: Request):
        body = await request.json()
        self.requests.append({"path": request.url.path,
                              "headers": dict(request.headers), "body": body})
        if not body.get("stream"):
            # 🔴 复刻真实通道的**唯一**接受形态：非流式一律 400 code 11101
            # （:8300 真实两号 4/4 命中，2026-10-04，`usage/events-20261004.jsonl`）。
            # 假上游若照收 `stream:false` 回 JSON，就是把"产品只发流式"这条事实
            # 用 mock 遮掉的经典 mock 绿 —— 适配器漏掉聚合时本用例必红。
            return JSONResponse({"code": 11101,
                                 "msg": "Non-stream chat request is currently not supported",
                                 "requestId": "fake-buddy"}, status_code=400)
        return StreamingResponse(self._sse(), media_type="text/event-stream")

    async def _sse(self):
        frames = [
            {"id": "c", "object": "chat.completion.chunk", "model": "hy3",
             "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
            {"id": "c", "object": "chat.completion.chunk", "model": "hy3",
             "choices": [{"index": 0, "delta": {"content": "你"}, "finish_reason": None}]},
            {"id": "c", "object": "chat.completion.chunk", "model": "hy3",
             "choices": [{"index": 0, "delta": {"content": "好"}, "finish_reason": None}]},
            # usage 在末帧给出（实测：buddy/workbuddy 流式成功的事件 `usage_source=vendor`
            # 且 token 非零 ⇒ 流式里确实带 usage，聚合后的非流式统计才有依据）
            {"id": "c", "object": "chat.completion.chunk", "model": "hy3",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 7, "completion_tokens": 3}},
        ]
        for frame in frames:
            yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"


@pytest.fixture
async def buddy_upstream():
    fake = _FakeBuddyUpstream()
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


def _cfg(port: int, *, product: str = "buddy", account: str = "acc-1",
         model_name: str = "cb-model", vendor_model: str = "hy3") -> dict:
    return {
        "resources": [{
            "id": "res-cb", "name": "产品资源", "vendor": "", "preset": "",
            "account": account, "product": product, "account_ref": account,
            "protocol": "openai", "base_url": f"http://127.0.0.1:{port}",
            "api_key": CONFIG_KEY,        # 故意留着：出站必须**不用**它（铁律 1）
            "enabled": True, "access_mode": "api",
        }],
        "models": [{"name": model_name, "endpoint": "chat",
                    "resources": [{"resource": "res-cb", "model": vendor_model}]}],
    }


def _body(model: str = "cb-model", **over) -> dict:
    data = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    data.update(over)
    return data


async def _chat(client, gw, body: dict):
    return await client.post(f"{gw.base_url}/v1/chat/completions", json=body)


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


# ============ 非流式 ============

async def test_buddy_nonstream_end_to_end(buddy_upstream, make_gateway, client):
    store.commit_login("buddy", "acc-1", {"access_token": TOKEN, "user_id": "u9"}, {})
    gw = await make_gateway(_cfg(buddy_upstream.port))

    resp = await _chat(client, gw, _body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # 客户端要的是非流式一条完整回答；通道只收流式 ⇒ 网关内部聚合（不甩 11101 给客户端）
    assert data["choices"][0]["message"]["content"] == "你好"
    assert data["model"] == "cb-model"                    # 统一名替换厂商名
    assert data["usage"] == {"prompt_tokens": 7, "completion_tokens": 3}

    assert len(buddy_upstream.requests) == 1
    req = buddy_upstream.requests[0]
    assert req["path"] == "/v2/chat/completions"          # 取证路径（不是标准 /chat/completions）
    assert req["headers"]["authorization"] == f"Bearer {TOKEN}"
    assert CONFIG_KEY not in json.dumps(req["headers"])   # 配置 Key 绝不外发（铁律 1）
    assert req["headers"]["x-domain"] == "127.0.0.1"      # 与实际请求基址一致
    # 🔴 推理面归属头（M6-F3 修正）：`X-Product` = **归属名**（`buddy-adapter.ts:1577`
    # + `product.ts:278`），不是计费面的部署类型 `SaaS`（`credits.ts:236`，那是另一面）；
    # 缺这组头上游后台「使用端」显示 `-`（`:1570`）
    assert req["headers"]["x-product"] == "CodeBuddy"
    assert req["headers"]["x-ide-name"] == "CodeBuddy"     # :1574 + product.ts:278
    assert req["headers"]["x-ide-type"] == "CodeBuddy"     # :1575
    assert req["headers"]["x-ide-version"] == "1.106.1"    # :1576 + product.ts:279
    assert req["headers"]["x-agent-purpose"] == "conversation"   # :1573
    assert req["headers"]["x-product-code"] == "codebuddy"
    assert req["headers"]["user-agent"] == "CodeBuddyIDE/1.106.1"
    assert req["body"]["model"] == "hy3"                  # 映射里的厂商模型名
    assert req["body"]["stream"] is True                  # 通道只接受流式：网关内部改流式再聚合

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == "产品资源/hy3"
    assert ev["input_tokens"] == 7 and ev["output_tokens"] == 3   # 假上游 usage 直通


# ============ 流式 ============

async def test_buddy_stream_end_to_end(buddy_upstream, make_gateway, client):
    store.commit_login("buddy", "acc-1", {"access_token": TOKEN}, {})
    gw = await make_gateway(_cfg(buddy_upstream.port))

    resp = await _chat(client, gw, _body(stream=True))
    assert resp.status_code == 200, resp.text
    assert "text/event-stream" in resp.headers["content-type"]
    frames = _sse_frames(resp.text)
    text = "".join(f["choices"][0]["delta"].get("content", "")
                   for f in frames if f.get("choices"))
    assert text == "你好"
    assert {f["model"] for f in frames if f.get("model")} == {"cb-model"}

    req = buddy_upstream.requests[-1]
    assert req["path"] == "/v2/chat/completions" and req["body"]["stream"] is True

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == "产品资源/hy3"


# ============ 产品参数化（同族零复制）============

async def test_workbuddy_uses_the_international_profile(buddy_upstream, make_gateway, client):
    """workbuddy = 同一份出站实现 + 国际版档案（X-Product / X-Product-Code / UA 随产品变）。"""
    store.commit_login("workbuddy", "wb-1", {"access_token": "WB-TOKEN"}, {})
    gw = await make_gateway(_cfg(buddy_upstream.port, product="workbuddy", account="wb-1",
                                 model_name="wb-model", vendor_model="gpt-5.5"))

    resp = await _chat(client, gw, _body("wb-model"))
    assert resp.status_code == 200, resp.text
    req = buddy_upstream.requests[-1]
    assert req["path"] == "/v2/chat/completions"
    assert req["headers"]["authorization"] == "Bearer WB-TOKEN"
    assert req["headers"]["x-product"] == "WorkBuddy"              # product.ts:401
    assert req["headers"]["x-ide-version"] == "5.5.2"              # product.ts:402
    assert req["headers"]["x-product-code"] == "workbuddy"          # product.ts:387
    assert req["headers"]["user-agent"].startswith("WorkBuddy/")    # product.ts:70,389
    assert req["body"]["model"] == "gpt-5.5"


# ============ fail closed ============

async def test_missing_credential_fails_closed_without_upstream_call(buddy_upstream,
                                                                    make_gateway, client):
    """账号没登录（凭据文件缺失）→ 可读失败 + **零次上游请求**（不拿空令牌打上游）。"""
    gw = await make_gateway(_cfg(buddy_upstream.port))     # 刻意不 commit_login

    resp = await _chat(client, gw, _body())
    assert resp.status_code == 503, resp.text
    payload = resp.json()
    assert "无凭据" in json.dumps(payload, ensure_ascii=False)
    assert buddy_upstream.requests == []

    await gw.drain_events()
    assert gw.read_events()[-1]["status"] == "failed"


# ============ 凭据新鲜度（重新登录不重启）============

async def test_relogin_is_picked_up_without_restart(buddy_upstream, make_gateway, client):
    """凭据**每次出站重读**（不做跨请求缓存）：重新登录后下一个请求即用新令牌。"""
    store.commit_login("buddy", "acc-1", {"access_token": "OLD-TOKEN"}, {})
    gw = await make_gateway(_cfg(buddy_upstream.port))
    assert (await _chat(client, gw, _body())).status_code == 200

    store.commit_login("buddy", "acc-1", {"access_token": "NEW-TOKEN"}, {})
    assert (await _chat(client, gw, _body())).status_code == 200

    tokens = [r["headers"]["authorization"] for r in buddy_upstream.requests]
    assert tokens == ["Bearer OLD-TOKEN", "Bearer NEW-TOKEN"], tokens
