"""lobsterai 出站**端到端**（§22.3/§22.5；M6-5b 波次）。

判据 = 「账号 → 资源 → `/v1/chat/completions`」全链路在**假上游**（`httpx.MockTransport`）上跑通：

· 非流式 / 流式各一条：网关返回内容正常、`model` 被统一名替换；
· 假上游收到的**路径**（`/api/proxy/v1/chat/completions`，取证 `lobsterai.ts:45`）、
  **身份头**（Bearer=账号令牌、UA、两个 `X-LobsterAI-Client-*`）与**请求体**
  （`model` = 映射里的厂商模型名、**`stream` 恒为 true**，`client.go:168-195`）逐项断言；
· 非流式响应由本适配器**聚合 SSE** 得到（上游只支持流式）—— 含 `reasoning_content` 与 `usage`；
· 配置里的 `api_key` **绝不出现**在出站头里（铁律 1：凭据只在账号目录）；
· 401 → 可分类为 `AUTH`（上层 `disable` 语义可识别，端到端见 401 用例）；429/5xx 归可重试。

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
from model_gateway.upstream.lobsterai import const, login
from model_gateway.upstream.lobsterai.out import LobsteraiOut

CONFIG_KEY = "sk-config-key-must-not-be-sent"
TOKEN = "TOKEN-FROM-ACCOUNT-E2E"
ACCOUNT = "acc-li"
BASE = "https://lobsterai-e2e.invalid"          # 不可解析域：mock 不生效则必失败（无网络证明）
VENDOR_MODEL = "kimi-k3"
SYSTEM_MODEL = "li-model"


# ============ 假上游（MockTransport：记录请求 + 回 SSE / JSON）============


def _sse_text(model: str = VENDOR_MODEL) -> str:
    """标准 OpenAI SSE（含 reasoning_content 与 usage 帧；`lobsterai.ts:15-23` 的协议表）。"""
    frames = [
        {"id": "chatcmpl-li-1", "object": "chat.completion.chunk", "created": 1_776_000_000,
         "model": model, "choices": [{"index": 0, "delta": {"role": "assistant"},
                                      "finish_reason": None}]},
        {"id": "chatcmpl-li-1", "object": "chat.completion.chunk", "created": 1_776_000_000,
         "model": model, "choices": [{"index": 0, "delta": {"reasoning_content": "先想"},
                                      "finish_reason": None}]},
        {"id": "chatcmpl-li-1", "object": "chat.completion.chunk", "created": 1_776_000_000,
         "model": model, "choices": [{"index": 0, "delta": {"content": "你"},
                                      "finish_reason": None}]},
        {"id": "chatcmpl-li-1", "object": "chat.completion.chunk", "created": 1_776_000_000,
         "model": model, "choices": [{"index": 0, "delta": {"content": "好"},
                                      "finish_reason": None}]},
        {"id": "chatcmpl-li-1", "object": "chat.completion.chunk", "created": 1_776_000_000,
         "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 9, "completion_tokens": 4}},
    ]
    out = "".join(f"data: {json.dumps(f, ensure_ascii=False)}\n\n" for f in frames)
    return out + "data: [DONE]\n\n"


def _handler(record: list[httpx.Request], *, mode: str = "sse", status: int = 200,
             error_body: str = '{"error": {"type": "invalid_api_key", "message": "bad token"}}'
             ):
    """MockTransport handler：`sse` = 回 SSE（本产品**唯一**的上游响应形态）；`error` = 回错误。"""

    def handle(request: httpx.Request) -> httpx.Response:
        record.append(request)
        if mode == "error":
            return httpx.Response(status, text=error_body, request=request,
                                  headers={"content-type": "application/json"})
        return httpx.Response(200, text=_sse_text(), request=request,
                              headers={"content-type": "text/event-stream"})

    return handle


async def _install(gw, res_id: str, handler) -> None:
    """把网关内该资源的适配器客户端换成 MockTransport（并关掉原客户端，防泄漏）。"""
    adapter = gw.runtime.adapters[res_id]
    old = adapter._client
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await old.aclose()


def _cfg(*, account: str = ACCOUNT, res_id: str = "res-li") -> dict:
    return {
        "resources": [{
            "id": res_id, "name": "LobsterAI 资源", "vendor": "", "preset": "",
            "account": account, "product": "lobsterai", "account_ref": account,
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


# ============ 非流式（= 本适配器的 SSE 聚合路径）============


async def test_lobsterai_nonstream_end_to_end(make_gateway, client):
    """非流式请求：网关把上游 SSE 聚合为 `chat.completion`（上游只认 `stream:true`）。"""
    login._reset_client_version_cache()          # 版本号头取兜底常量（确定性）
    store.commit_login("lobsterai", ACCOUNT,
                       {"access_token": TOKEN, "uid": "u-9", "uuid": "dev-uuid-1"}, {})
    seen: list[httpx.Request] = []
    gw = await make_gateway(_cfg())
    await _install(gw, "res-li", _handler(seen))

    resp = await _chat(client, gw, _body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "你好"
    assert data["choices"][0]["message"]["reasoning_content"] == "先想"
    assert data["choices"][0]["finish_reason"] == "stop"
    assert data["model"] == SYSTEM_MODEL                    # 统一名替换厂商名
    assert data["usage"] == {"prompt_tokens": 9, "completion_tokens": 4}

    assert len(seen) == 1
    req = seen[0]
    assert req.url.path == "/api/proxy/v1/chat/completions"   # 取证路径（lobsterai.ts:45）
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    assert CONFIG_KEY not in json.dumps(dict(req.headers))    # 配置 Key 绝不外发（铁律 1）
    assert req.headers["user-agent"] == const.USER_AGENT
    assert req.headers["x-lobsterai-client-capabilities"] == const.CLIENT_CAPABILITIES
    assert req.headers["x-lobsterai-client-version"] == const.FALLBACK_CLIENT_VERSION
    assert req.headers["accept"] == "text/event-stream, application/json"
    payload = json.loads(req.content)
    assert payload["model"] == VENDOR_MODEL                  # 映射里的厂商模型名
    assert payload["stream"] is True                         # 🔴 强制改写（client.go:168-195）

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == "LobsterAI 资源/kimi-k3"
    assert ev["input_tokens"] == 9 and ev["output_tokens"] == 4


# ============ 流式 ============


async def test_lobsterai_stream_end_to_end(make_gateway, client):
    """流式请求：SSE 直通（归一化思考字段），帧内 `model` 被统一名替换。"""
    login._reset_client_version_cache()
    store.commit_login("lobsterai", ACCOUNT, {"access_token": TOKEN, "uuid": "dev-uuid-1"}, {})
    seen: list[httpx.Request] = []
    gw = await make_gateway(_cfg())
    await _install(gw, "res-li", _handler(seen, mode="sse"))

    resp = await _chat(client, gw, _body(stream=True))
    assert resp.status_code == 200, resp.text
    assert "text/event-stream" in resp.headers["content-type"]
    frames = _sse_frames(resp.text)
    text = "".join(f["choices"][0]["delta"].get("content", "")
                   for f in frames if f.get("choices"))
    reasoning = "".join(f["choices"][0]["delta"].get("reasoning_content", "")
                        for f in frames if f.get("choices"))
    assert text == "你好" and reasoning == "先想"
    assert {f["model"] for f in frames if f.get("model")} == {SYSTEM_MODEL}

    req = seen[-1]
    assert req.url.path == "/api/proxy/v1/chat/completions"
    assert json.loads(req.content)["stream"] is True

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == "LobsterAI 资源/kimi-k3"


# ============ 错误映射（401 → disable 可识别；429/5xx → 可重试）============


def _adapter(handler) -> LobsteraiOut:
    adapter = LobsteraiOut(ProductAccount(product="lobsterai", name=ACCOUNT, base_url=BASE))
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter


@pytest.mark.parametrize("status,expected", [
    (401, ErrorClass.AUTH),          # 上层据此 disable（终态）
    (429, ErrorClass.QUOTA),         # 冷却 + 短退避（§22.5-5）
    (503, ErrorClass.RETRYABLE),     # 可重试
])
def test_error_mapping_aligns_with_the_existing_classifier(status, expected):
    """错误形态与既有 `openai_out` 对齐：`UpstreamError(status_code, error_body)` 原样抛出。"""
    store.commit_login("lobsterai", ACCOUNT, {"access_token": TOKEN, "uuid": "dev-uuid-1"}, {})
    seen: list[httpx.Request] = []
    adapter = _adapter(_handler(seen, mode="error", status=status))

    async def run():
        with pytest.raises(UpstreamError) as e:
            await adapter.chat_nonstream("", VENDOR_MODEL, {"messages": []}, 10.0)
        await adapter.aclose()
        return e.value

    err = asyncio.run(run())
    assert err.status_code == status
    assert "invalid_api_key" in (err.error_body or "")      # 原始体保留（透传）
    assert ErrorClassifier().classify(err) is expected


async def test_empty_upstream_stream_fails_closed(make_gateway, client):
    """上游 200 却**一帧未给** → `UpstreamError`（不得把"什么都没给"当成空内容成功）。

    fail closed 判据（§22.8-5）；单资源前提下客户端拿到错误响应而不是 HTTP 200 空正文。
    """
    login._reset_client_version_cache()
    store.commit_login("lobsterai", ACCOUNT, {"access_token": TOKEN, "uuid": "dev-uuid-1"}, {})
    seen: list[httpx.Request] = []

    def empty_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="", request=request,
                              headers={"content-type": "text/event-stream"})

    gw = await make_gateway(_cfg())
    await _install(gw, "res-li", empty_handler)

    resp = await _chat(client, gw, _body())
    assert resp.status_code != 200 and "空" in resp.text
    assert len(seen) >= 1                  # 空流按可重试处理（同资源重试由调度器决定次数）
    await gw.drain_events()
    assert gw.read_events()[-1]["status"] == "failed"


async def test_401_disables_the_resource_end_to_end(make_gateway, client):
    """401 → 分类器 `AUTH` → 上层 `disable`（不重试、切下一资源）—— 端到端红证。"""
    login._reset_client_version_cache()
    store.commit_login("lobsterai", ACCOUNT, {"access_token": TOKEN, "uuid": "dev-uuid-1"}, {})
    cfg = _cfg()
    cfg["resources"].append({
        "id": "res-li2", "name": "LobsterAI 备用", "vendor": "", "preset": "",
        "account": ACCOUNT, "product": "lobsterai", "account_ref": ACCOUNT,
        "protocol": "openai", "base_url": "https://lobsterai-e2e-2.invalid",
        "api_key": "", "enabled": True, "access_mode": "api",
    })
    cfg["models"][0]["resources"].append({"resource": "res-li2", "model": "glm-5.1"})
    seen_a: list[httpx.Request] = []
    seen_b: list[httpx.Request] = []
    gw = await make_gateway(cfg)
    await _install(gw, "res-li", _handler(seen_a, mode="error", status=401))
    # ⚠️ 备用资源也回 SSE：本产品上游**只支持流式**（`stream:false` → 500），
    #    非流式由适配器聚合 —— 回 JSON 体不是本产品的真实形态。
    await _install(gw, "res-li2", _handler(seen_b, mode="sse"))

    resp = await _chat(client, gw, _body())
    assert resp.status_code == 200, resp.text
    assert resp.json()["choices"][0]["message"]["content"] == "你好"

    await gw.drain_events()
    ev = gw.read_events()[0]
    assert ev["resource_attempts"][0]["attempts"] == 1        # 401 不重试
    assert gw.runtime.resources.registry.get(("res-li", VENDOR_MODEL)).status == "disabled"
    assert gw.read_switches()[0]["reason_cls"] == "AUTH"
    assert len(seen_a) == 1 and len(seen_b) == 1
