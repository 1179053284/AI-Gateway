"""loomy 出站**端到端**（§22.3/§22.5；M6-5b 波次）。

判据 = 「账号 → 资源 → `/v1/chat/completions`」全链路在**假上游**（`httpx.MockTransport`）上跑通：

· 非流式 / 流式各一条：网关返回内容正常、`model` 被统一名替换；
· 假上游收到的**路径**（`/api/v1/chat/completions`，`loomy-adapter.ts:483`：基址已含
  `/api/v1`，故族基类缺省 `chat_path="/chat/completions"` 恰好正确）、**双鉴权头**
  （`Authorization: Bearer` **与** 小写 `token`，`loomy.ts:217-232`）、**请求体**逐项断言；
· 配置里的 `api_key` **绝不出现**在出站头里（铁律 1：凭据只在账号目录）；
· 401 → `AUTH`（上层 `disable`，端到端见 401 用例）；429 → `QUOTA`；5xx → `RETRYABLE`。

假上游 = `httpx.MockTransport`（**零网络**：资源基址是 `.invalid` 域，若 mock 不生效必失败）；
网关走 `make_gateway` 基建（随机端口 + 临时配置 + 临时 usage 目录）。
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from model_gateway.accounts import store
from model_gateway.adapters.product_out import ProductAccount
from model_gateway.core.errors import ErrorClass, ErrorClassifier, UpstreamError
from model_gateway.upstream.loomy.out import LoomyOut

CONFIG_KEY = "sk-config-key-must-not-be-sent"
TOKEN = "3f2c1a9e5b7d4c8a0e6f1b3d9c2a5e70"              # 讯飞 session（32 位小写 hex）
ACCOUNT = "acc-lm"
BASE = "https://loomy-e2e.invalid/api/v1"               # = registry 口径（基址含 /api/v1）
VENDOR_MODEL = "Kimi-k2.6"
SYSTEM_MODEL = "lm-model"


# ============ 假上游（MockTransport：记录请求 + 回 SSE / JSON）============


def _sse_text(model: str = VENDOR_MODEL) -> str:
    frames = [
        {"id": "chatcmpl-lm-1", "object": "chat.completion.chunk", "model": model,
         "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "chatcmpl-lm-1", "object": "chat.completion.chunk", "model": model,
         "choices": [{"index": 0, "delta": {"content": "你"}, "finish_reason": None}]},
        {"id": "chatcmpl-lm-1", "object": "chat.completion.chunk", "model": model,
         "choices": [{"index": 0, "delta": {"content": "好"}, "finish_reason": None}]},
        {"id": "chatcmpl-lm-1", "object": "chat.completion.chunk", "model": model,
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    out = "".join(f"data: {json.dumps(f, ensure_ascii=False)}\n\n" for f in frames)
    return out + "data: [DONE]\n\n"


def _handler(record: list[httpx.Request], *, mode: str = "json", status: int = 200,
             error_body: str = '{"code": "100002", "desc": "缺少 token"}'):
    """MockTransport handler：`json` = 非流式 OpenAI 体；`sse` = SSE；`error` = 错误帧。"""

    def handle(request: httpx.Request) -> httpx.Response:
        record.append(request)
        if mode == "error":
            return httpx.Response(status, text=error_body, request=request,
                                  headers={"content-type": "application/json"})
        if mode == "sse":
            return httpx.Response(200, text=_sse_text(), request=request,
                                  headers={"content-type": "text/event-stream"})
        body = json.loads(request.content or b"{}")
        return httpx.Response(200, json={
            "id": "chatcmpl-lm-json", "object": "chat.completion", "model": body.get("model"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "来自假上游"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 6, "completion_tokens": 3}}, request=request)

    return handle


async def _install(gw, res_id: str, handler) -> None:
    """把网关内该资源的适配器客户端换成 MockTransport（并关掉原客户端，防泄漏）。"""
    adapter = gw.runtime.adapters[res_id]
    old = adapter._client
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await old.aclose()


def _cfg(*, res_id: str = "res-lm") -> dict:
    return {
        "resources": [{
            "id": res_id, "name": "Loomy 资源", "vendor": "", "preset": "",
            "account": ACCOUNT, "product": "loomy", "account_ref": ACCOUNT,
            "protocol": "openai", "base_url": BASE,
            "api_key": CONFIG_KEY,        # 故意留着：出站必须**不用**它（铁律 1）
            "enabled": True, "access_mode": "api",
        }],
        "models": [{"name": SYSTEM_MODEL, "endpoint": "chat",
                    "resources": [{"resource": res_id, "model": VENDOR_MODEL}]}],
    }


def _body(model: str = SYSTEM_MODEL, **over) -> dict:
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


async def test_loomy_nonstream_end_to_end(make_gateway, client):
    """非流式：标准 JSON 直通；头/体逐项断言（Bearer 与 `token` **两个都发**）。"""
    store.commit_login("loomy", ACCOUNT, {"access_token": TOKEN, "userid": "123456789012345678"}, {})
    seen: list[httpx.Request] = []
    gw = await make_gateway(_cfg())
    await _install(gw, "res-lm", _handler(seen, mode="json"))

    resp = await _chat(client, gw, _body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "来自假上游"
    assert data["model"] == SYSTEM_MODEL                    # 统一名替换厂商名

    assert len(seen) == 1
    req = seen[0]
    assert req.url.path == "/api/v1/chat/completions"       # 取证路径（loomy-adapter.ts:483）
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    assert req.headers["token"] == TOKEN                    # ⚠️ 小写 token 头（loomy.ts:225-231）
    assert CONFIG_KEY not in json.dumps(dict(req.headers))  # 配置 Key 绝不外发（铁律 1）
    assert req.headers["accept"] == "text/event-stream"     # loomy.ts:227
    payload = json.loads(req.content)
    assert payload["model"] == VENDOR_MODEL                 # 映射里的厂商模型名

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == f"Loomy 资源/{VENDOR_MODEL}"
    assert ev["input_tokens"] == 6 and ev["output_tokens"] == 3


# ============ 流式 ============


async def test_loomy_stream_end_to_end(make_gateway, client):
    """流式请求：SSE 归一化 + 帧内 `model` 被统一名替换。"""
    store.commit_login("loomy", ACCOUNT, {"access_token": TOKEN, "userid": "123456789012345678"}, {})
    seen: list[httpx.Request] = []
    gw = await make_gateway(_cfg())
    await _install(gw, "res-lm", _handler(seen, mode="sse"))

    resp = await _chat(client, gw, _body(stream=True))
    assert resp.status_code == 200, resp.text
    assert "text/event-stream" in resp.headers["content-type"]
    frames = _sse_frames(resp.text)
    text = "".join(f["choices"][0]["delta"].get("content", "")
                   for f in frames if f.get("choices"))
    assert text == "你好"
    assert {f["model"] for f in frames if f.get("model")} == {SYSTEM_MODEL}

    req = seen[-1]
    assert req.url.path == "/api/v1/chat/completions"
    assert json.loads(req.content)["stream"] is True
    assert req.headers["token"] == TOKEN

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == f"Loomy 资源/{VENDOR_MODEL}"


# ============ 错误映射（401 → disable 可识别；429/5xx → 可重试）============


def _adapter(handler) -> LoomyOut:
    adapter = LoomyOut(ProductAccount(product="loomy", name=ACCOUNT, base_url=BASE))
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter


@pytest.mark.parametrize("status,expected", [
    (401, ErrorClass.AUTH),          # 上层据此 disable（终态；本产品无续期端点）
    (429, ErrorClass.QUOTA),         # 冷却 + 短退避（§22.5-5）
    (503, ErrorClass.RETRYABLE),     # 可重试
])
def test_error_mapping_aligns_with_the_existing_classifier(status, expected):
    """错误形态与既有 `openai_out` 对齐：`UpstreamError(status_code, error_body)` 原样抛出。

    ⚠️ 业务失败的 HTTP 200 + 信封（`code=100002`）是**控制面**口径（`loomy.ts:80-104`）：
    推理端点是标准 OpenAI 形态，走 HTTP 状态码映射；流内业务错误帧由调度器既有路径兜住。
    """
    store.commit_login("loomy", ACCOUNT, {"access_token": TOKEN, "userid": "123456789012345678"}, {})
    seen: list[httpx.Request] = []
    adapter = _adapter(_handler(seen, mode="error", status=status))

    async def run():
        with pytest.raises(UpstreamError) as e:
            await adapter.chat_nonstream("", VENDOR_MODEL, {"messages": []}, 10.0)
        await adapter.aclose()
        return e.value

    err = asyncio.run(run())
    assert err.status_code == status
    assert "100002" in (err.error_body or "")               # 原始体保留（透传）
    assert ErrorClassifier().classify(err) is expected


async def test_401_disables_the_resource_end_to_end(make_gateway, client):
    """401 → 分类器 `AUTH` → 上层 `disable`（不重试、切下一资源）—— 端到端红证。"""
    store.commit_login("loomy", ACCOUNT, {"access_token": TOKEN, "userid": "123456789012345678"}, {})
    cfg = _cfg()
    cfg["resources"].append({
        "id": "res-lm2", "name": "Loomy 备用", "vendor": "", "preset": "",
        "account": ACCOUNT, "product": "loomy", "account_ref": ACCOUNT,
        "protocol": "openai", "base_url": "https://loomy-e2e-2.invalid/api/v1",
        "api_key": "", "enabled": True, "access_mode": "api",
    })
    cfg["models"][0]["resources"].append({"resource": "res-lm2", "model": "GLM-5.3-Flash"})
    seen_a: list[httpx.Request] = []
    seen_b: list[httpx.Request] = []
    gw = await make_gateway(cfg)
    await _install(gw, "res-lm", _handler(seen_a, mode="error", status=401))
    await _install(gw, "res-lm2", _handler(seen_b, mode="json"))

    resp = await _chat(client, gw, _body())
    assert resp.status_code == 200, resp.text
    assert resp.json()["choices"][0]["message"]["content"] == "来自假上游"

    await gw.drain_events()
    ev = gw.read_events()[0]
    assert ev["resource_attempts"][0]["attempts"] == 1        # 401 不重试
    assert gw.runtime.resources.registry.get(("res-lm", VENDOR_MODEL)).status == "disabled"
    assert gw.read_switches()[0]["reason_cls"] == "AUTH"
    assert len(seen_a) == 1 and len(seen_b) == 1
