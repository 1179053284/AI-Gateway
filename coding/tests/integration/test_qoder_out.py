"""qoder / qodercn 出站**端到端**（§22.3/§22.4/§22.5；M6-5c）。

判据 = 「账号 → 资源 → `/v1/chat/completions`」全链路在**假信封上游**上跑通：

· **信封协议**：响应是 `{"headers":…,"body":"<OpenAI chunk 的 JSON 字符串>",…}` 套一层
  （`qoder-envelope.ts:8-12`）—— 剥完即标准 OpenAI SSE（`qoder-envelope.ts:60-64` 语义）；
· **加密推理端点认目录 key**：请求体 `model_config.key` / `chat_context.extra.modelConfig.key`
  = 目录 key（`qfmodel`），`business` 必填（`{"type":"agent"}` —— 缺它会被路由到故障节点，
  `qoder-adapter.ts:726-736`）；频道二义（§2.4）：业务码 `10605` **既可能走 HTTP 403、
  也可能出现在流内帧**，两条通道都必须识别并保留 `code`（`model-queue.ts:96-135`）；
· **请求加密与 COSY 签名**未移植 → 走 `out.SIGNER_FACTORY` 注入缝：
  本文件注入**假签名器**验证「明文 ask → url/headers/body → 信封解包」全链路；
  未注入时**fail closed**（可读失败 + 零次上游请求）；
· **两站互不串用**：qodercn 资源上挂国际版凭据（`family="qoder"`）→ 可读失败 + 零次上游请求。

假签名器把 `ask` 明文原样写进 body（假上游只解 `ask` 字段）——**它不模拟 WASM**，
只证明本层交付的拼接契约（url/headers/body 三件套）与信封解包是正确的。
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
from model_gateway.upstream.qoder import out as qoder_out

CONFIG_KEY = "sk-config-key-must-not-be-sent"
TOKEN = "QODER-TOKEN-FROM-ACCOUNT"
ENDPOINT_SUFFIX = "?FetchKeys=llm_model_result&AgentId=agent_common&Encode=1"


def _envelope(inner: dict | str) -> str:
    """把内层帧（OpenAI chunk 或业务错误）包成信封（`qoder-envelope.ts:8-12` 的形态）。"""
    body = inner if isinstance(inner, str) else json.dumps(inner, ensure_ascii=False)
    return json.dumps({"headers": {"content-type": "application/json"}, "body": body,
                       "statusCodeValue": 200, "statusCode": "OK"}, ensure_ascii=False)


def _chunk(**delta) -> dict:
    return {"id": "c1", "object": "chat.completion.chunk", "model": "qfmodel",
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}


class _FakeEnvelopeUpstream:
    """假 Qoder 加密端点：`POST /algo/api/v2/service/pro/sse/agent_chat_generation`。"""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        #: 内层帧序列（字符串 = 业务错误原文；dict = OpenAI chunk）
        self.bodies: list[dict | str] = [
            _chunk(role="assistant", content=""),
            _chunk(content="你"),
            _chunk(content="好"),
            _chunk(finish_reason="stop"),
        ]
        #: 非 200 响应（通道二义用）：(status, body)
        self.error_response: tuple[int, str] | None = None
        self.app = Starlette(routes=[
            Route("/algo/api/v2/service/pro/sse/agent_chat_generation",
                  self._chat, methods=["POST"])])

    async def _chat(self, request: Request):
        raw = await request.body()
        self.requests.append({"path": request.url.path, "query": request.url.query,
                              "headers": dict(request.headers),
                              "body": json.loads(raw.decode("utf-8"))})
        if self.error_response is not None:
            status, body = self.error_response
            return JSONResponse(json.loads(body), status_code=status)
        lines = [f"data: {_envelope(b)}\n\n" for b in self.bodies]

        async def gen():
            for line in lines:
                yield line

        return StreamingResponse(gen(), media_type="text/event-stream")


@pytest.fixture
async def qoder_upstream():
    fake = _FakeEnvelopeUpstream()
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


#: 假签名器记录的 ask（用例断言用）
SIGNED: list[dict] = []


def _install_fake_signer(monkeypatch):
    """注入假签名器（`SIGNER_FACTORY` 契约：与 DSH `prepareInfer` 同形）。"""
    SIGNED.clear()

    def factory(product_cfg, base_url, cred, meta):
        def sign(ask: dict):
            SIGNED.append({"region": product_cfg.id, "base_url": base_url,
                           "ask": ask, "token": cred.get("access_token")})
            return qoder_out.SignedRequest(
                url=f"{base_url}/algo/api/v2/service/pro/sse/agent_chat_generation"
                    f"{ENDPOINT_SUFFIX}",
                headers={"Authorization": "Bearer COSY.FAKE-PAYLOAD.FAKE-SIG",
                         "Content-Type": "application/json", "Cosy-Version": "1.1.49",
                         "X-Request-Id": "req-1"},
                body=json.dumps(ask, ensure_ascii=False))

        return sign

    monkeypatch.setattr(qoder_out, "SIGNER_FACTORY", factory)


def _cfg(port: int, *, product: str = "qoder", account: str = "qd-1",
         model_name: str = "qd-model", vendor_model: str = "qfmodel",
         scheduling: dict | None = None) -> dict:
    return {
        "resources": [{
            "id": f"res-{product}", "name": "产品资源", "vendor": "", "preset": "",
            "account": account, "product": product, "account_ref": account,
            "protocol": "openai", "base_url": f"http://127.0.0.1:{port}",
            "api_key": CONFIG_KEY,       # 故意留着：出站必须**不用**它（铁律 1）
            "enabled": True, "access_mode": "api",
        }],
        "models": [{"name": model_name, "endpoint": "chat",
                    "resources": [{"resource": f"res-{product}", "model": vendor_model}]}],
        **({"scheduling": scheduling} if scheduling else {}),
    }


def _body(model: str = "qd-model", **over) -> dict:
    data = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    data.update(over)
    return data


def _sse_frames(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if payload in ("[DONE]", ""):
            continue
        out.append(json.loads(payload))
    return out


# ============ 非流式（信封解包 + 目录 key）============

async def test_qoder_nonstream_end_to_end(qoder_upstream, make_gateway, client, monkeypatch):
    _install_fake_signer(monkeypatch)
    store.commit_login("qoder", "qd-1",
                       {"access_token": TOKEN, "security_oauth_token": TOKEN,
                        "machine_id": "m" * 32, "uid": "u-1", "family": "qoder"}, {})
    gw = await make_gateway(_cfg(qoder_upstream.port))

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "你好"     # 信封逐帧剥出后聚合
    assert data["model"] == "qd-model"

    assert len(qoder_upstream.requests) == 1
    req = qoder_upstream.requests[0]
    assert req["path"] == "/algo/api/v2/service/pro/sse/agent_chat_generation"
    assert req["query"] == "FetchKeys=llm_model_result&AgentId=agent_common&Encode=1"
    assert req["headers"]["authorization"] == "Bearer COSY.FAKE-PAYLOAD.FAKE-SIG"
    assert req["headers"]["cosy-version"] == "1.1.49"
    assert CONFIG_KEY not in json.dumps(req["headers"])            # 配置 Key 绝不外发
    assert len(SIGNED) == 1
    assert SIGNED[0]["region"] == "qoder" and SIGNED[0]["token"] == TOKEN
    ask = SIGNED[0]["ask"]
    assert ask["model_config"]["key"] == "qfmodel"                 # 加密端点认**目录 key**
    assert ask["chat_context"]["extra"]["modelConfig"]["key"] == "qfmodel"
    assert ask["business"] == {"type": "agent"}                    # 必填（qoder-adapter.ts:736）
    assert ask["session_type"] == "qodercli"                       # qoder-wasm.ts:297
    assert ask["stream"] is True and ask["tools"] == []
    assert ask["model_config"]["is_reasoning"] is True             # 目录 is_reasoning（M6-5c 回填）

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == "产品资源/qfmodel"


async def test_qoder_stream_end_to_end_with_passthrough_frame(qoder_upstream, make_gateway,
                                                              client, monkeypatch):
    """流式 + **信封边界**：非信封帧原样透传（`qoder-envelope.ts:107-112` 的容错）。"""
    _install_fake_signer(monkeypatch)
    store.commit_login("qoder", "qd-1", {"access_token": TOKEN, "family": "qoder"}, {})
    gw = await make_gateway(_cfg(qoder_upstream.port))
    # 中间插一帧**已经是标准 OpenAI chunk** 的裸帧（旧实现会当垃圾丢掉）
    qoder_upstream.bodies = [
        _chunk(role="assistant", content=""),
        _chunk(content="你"),
        {"id": "c2", "object": "chat.completion.chunk", "model": "qfmodel",
         "choices": [{"index": 0, "delta": {"content": "好"}, "finish_reason": None}]},
        _chunk(finish_reason="stop"),
    ]

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body(stream=True))
    assert resp.status_code == 200, resp.text
    frames = _sse_frames(resp.text)
    text = "".join(f["choices"][0]["delta"].get("content", "")
                   for f in frames if f.get("choices"))
    assert text == "你好"
    assert {f["model"] for f in frames if f.get("model")} == {"qd-model"}


# ============ 业务码的通道二义（§2.4）============

_QUEUE_INNER = json.dumps({"code": "10605",
                           "message": json.dumps({"isQueued": True, "modelKey": "qfmodel",
                                                  "retryAfterSeconds": 30})})


async def test_qoder_queue_code_in_stream_frame(qoder_upstream, make_gateway, client, monkeypatch):
    """通道一：**HTTP 200 + 流内信封帧里的 `10605`**（`model-queue.ts:10-11`）。"""
    _install_fake_signer(monkeypatch)
    store.commit_login("qoder", "qd-1", {"access_token": TOKEN, "family": "qoder"}, {})
    gw = await make_gateway(_cfg(qoder_upstream.port, scheduling={"retry_per_request": 0}))
    qoder_upstream.bodies = [_chunk(role="assistant", content=""), _QUEUE_INNER]

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 503, resp.text
    # `code` 保真 + 服务端建议的等待秒数**可见**（增量写进 error_body，见 envelope._with_retry_after）
    assert "10605" in resp.text and "retry_after_seconds" in resp.text
    await gw.drain_events()
    assert gw.read_events()[-1]["status"] == "failed"


async def test_qoder_queue_code_on_http_403(qoder_upstream, make_gateway, client, monkeypatch):
    """通道二：**HTTP 403 + 排队 JSON 体** —— 必须识别为排队而不是 AUTH（否则资源被停用）。

    证据：`qoder-adapter.ts:743-749`（三种 403 语义互不相同）。
    """
    _install_fake_signer(monkeypatch)
    store.commit_login("qoder", "qd-1", {"access_token": TOKEN, "family": "qoder"}, {})
    gw = await make_gateway(_cfg(qoder_upstream.port, scheduling={"retry_per_request": 0}))
    qoder_upstream.error_response = (403, _QUEUE_INNER)

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 503, resp.text                      # 可重试，而非 401/停用
    assert "10605" in resp.text
    await gw.drain_events()
    assert gw.read_events()[-1]["status"] == "failed"


async def test_qoder_billing_code_110_maps_to_quota(qoder_upstream, make_gateway, client,
                                                    monkeypatch):
    """额度码 `110`（Billing daily count exceeded）→ QUOTA（429，**不白重试**）。

    证据：`model-queue.ts:41-73`（10605 与 110 的语义差异是本质的）。
    """
    _install_fake_signer(monkeypatch)
    store.commit_login("qoder", "qd-1", {"access_token": TOKEN, "family": "qoder"}, {})
    gw = await make_gateway(_cfg(qoder_upstream.port, scheduling={"quota_retry": 0}))
    qoder_upstream.bodies = [_chunk(role="assistant", content=""),
                             json.dumps({"code": "110",
                                         "message": "Billing daily count exceeded"})]

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 429, resp.text
    assert "110" in resp.text
    assert len(qoder_upstream.requests) == 1                       # QUOTA 直接 bench，不重试


# ============ qodercn（区域显式注入）============

async def test_qodercn_uses_its_own_region_config(qoder_upstream, make_gateway, client,
                                                  monkeypatch):
    _install_fake_signer(monkeypatch)
    store.commit_login("qodercn", "cn-1", {"access_token": "CN-TOKEN", "family": "qodercn"}, {})
    gw = await make_gateway(_cfg(qoder_upstream.port, product="qodercn", account="cn-1",
                                 model_name="cn-model"))

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body("cn-model"))
    assert resp.status_code == 200, resp.text
    assert SIGNED[-1]["region"] == "qodercn"                       # 注入的是 CN 区域实例
    assert SIGNED[-1]["token"] == "CN-TOKEN"


async def test_qodercn_refuses_qoder_credential(qoder_upstream, make_gateway, client,
                                                monkeypatch):
    """两站互不串用（§22.4）：凭据带 `family="qoder"` 挂到 qodercn 资源 → 不打上游。"""
    _install_fake_signer(monkeypatch)
    store.commit_login("qodercn", "cn-1", {"access_token": TOKEN, "family": "qoder"}, {})
    gw = await make_gateway(_cfg(qoder_upstream.port, product="qodercn", account="cn-1",
                                 model_name="cn-model"))

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body("cn-model"))
    assert resp.status_code == 503, resp.text
    assert "不符" in resp.text and "qodercn" in resp.text
    assert qoder_upstream.requests == []                           # 零次上游请求
    assert SIGNED == []                                            # 也没到签名器


# ============ fail closed：未注入签名器 ============

async def test_qoder_without_signer_fails_closed(qoder_upstream, make_gateway, client):
    """未注入 `SIGNER_FACTORY` → 可读失败 + **零次上游请求**（不伪造签名、不降级公开端点）。"""
    store.commit_login("qoder", "qd-1", {"access_token": TOKEN, "family": "qoder"}, {})
    gw = await make_gateway(_cfg(qoder_upstream.port, scheduling={"retry_per_request": 0}))

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 503, resp.text
    assert "WASM" in resp.text and "SIGNER_FACTORY" in resp.text
    assert qoder_upstream.requests == []
