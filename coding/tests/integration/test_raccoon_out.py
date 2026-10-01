"""raccoon 出站**端到端**（§22.3/§22.5；M6-5b 波次）。

判据 = 「账号 → 资源 → `/v1/chat/completions`」全链路在**假上游**（`httpx.MockTransport`）上跑通：

· 非流式 / 流式各一条：网关返回内容正常、`model` 被统一名替换；
· 假上游收到的**路径**（`/api/web/llm/v2/chat/completions`，`raccoon-adapter.ts:427`：基址已含
  `/api/web/llm/v2`，故族基类缺省 `chat_path="/chat/completions"` 恰好正确）、**chat 头集**
  （`Authorization` / `X-Org-Code` / `X-Raccoon-Language` / `X-Client-Platform`，
  `raccoon-adapter.ts:414-421`）、**请求体**逐项断言；
· **思考方言**：网关 IR 注入的顶层 `thinking` / `reasoning_effort` 对上游**无效**
  （`raccoon-product.ts:55-70` 实测表）→ 适配器翻译成 `extra_body.thinking.{type}`；
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
from model_gateway.upstream.raccoon import const as C
from model_gateway.upstream.raccoon.out import RaccoonOut

CONFIG_KEY = "sk-config-key-must-not-be-sent"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.raccoon"                  # JWT 形态访问令牌（不验签）
OFFICE = "org-9f2c"
ACCOUNT = "acc-rc"
BASE = "https://raccoon-e2e.invalid/api/web/llm/v2"      # = registry 口径（基址含推理前缀）
VENDOR_MODEL = "sn-kimi-k3"
SYSTEM_MODEL = "rc-model"


# ============ 假上游（MockTransport：记录请求 + 回 SSE / JSON）============


def _sse_text(model: str = VENDOR_MODEL) -> str:
    frames = [
        {"id": "chatcmpl-rc-1", "object": "chat.completion.chunk", "model": model,
         "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "chatcmpl-rc-1", "object": "chat.completion.chunk", "model": model,
         "choices": [{"index": 0, "delta": {"content": "你"}, "finish_reason": None}]},
        {"id": "chatcmpl-rc-1", "object": "chat.completion.chunk", "model": model,
         "choices": [{"index": 0, "delta": {"content": "好"}, "finish_reason": None}]},
        {"id": "chatcmpl-rc-1", "object": "chat.completion.chunk", "model": model,
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    out = "".join(f"data: {json.dumps(f, ensure_ascii=False)}\n\n" for f in frames)
    return out + "data: [DONE]\n\n"


def _handler(record: list[httpx.Request], *, mode: str = "json", status: int = 200,
             error_body: str = '{"code": 200003, "message": "登录态已过期"}'):
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
            "id": "chatcmpl-rc-json", "object": "chat.completion", "model": body.get("model"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "来自假上游"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2}}, request=request)

    return handle


async def _install(gw, res_id: str, handler) -> None:
    """把网关内该资源的适配器客户端换成 MockTransport（并关掉原客户端，防泄漏）。"""
    adapter = gw.runtime.adapters[res_id]
    old = adapter._client
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await old.aclose()


def _cfg(*, res_id: str = "res-rc") -> dict:
    return {
        "resources": [{
            "id": res_id, "name": "Raccoon 资源", "vendor": "", "preset": "",
            "account": ACCOUNT, "product": "raccoon", "account_ref": ACCOUNT,
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


def _login() -> None:
    store.commit_login("raccoon", ACCOUNT,
                       {"access_token": TOKEN, "refresh_token": "rt-1", "office_identity": OFFICE},
                       {})


# ============ 非流式 ============


async def test_raccoon_nonstream_end_to_end(make_gateway, client):
    """非流式：标准 JSON 直通；头/体逐项断言（chat 四头集）。"""
    _login()
    seen: list[httpx.Request] = []
    gw = await make_gateway(_cfg())
    await _install(gw, "res-rc", _handler(seen, mode="json"))

    resp = await _chat(client, gw, _body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "来自假上游"
    assert data["model"] == SYSTEM_MODEL                    # 统一名替换厂商名

    assert len(seen) == 1
    req = seen[0]
    # 取证路径（raccoon-adapter.ts:427；registry 基址已含 /api/web/llm/v2）
    assert req.url.path == "/api/web/llm/v2/chat/completions"
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    assert req.headers["x-org-code"] == OFFICE              # raccoon-adapter.ts:418
    assert req.headers["x-raccoon-language"] == C.LANGUAGE  # raccoon.ts:281
    assert req.headers["x-client-platform"] == C.client_platform()   # raccoon-product.ts:279-281
    assert req.headers["accept"] == "text/event-stream"     # raccoon-adapter.ts:415
    assert CONFIG_KEY not in json.dumps(dict(req.headers))  # 配置 Key 绝不外发（铁律 1）
    payload = json.loads(req.content)
    assert payload["model"] == VENDOR_MODEL                 # 映射里的厂商模型名
    assert "extra_body" not in payload                      # 未指定思考档 → 不发该字段

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == f"Raccoon 资源/{VENDOR_MODEL}"
    assert ev["input_tokens"] == 4 and ev["output_tokens"] == 2


# ============ 流式 ============


async def test_raccoon_stream_end_to_end(make_gateway, client):
    """流式请求：SSE 归一化 + 帧内 `model` 被统一名替换。"""
    _login()
    seen: list[httpx.Request] = []
    gw = await make_gateway(_cfg())
    await _install(gw, "res-rc", _handler(seen, mode="sse"))

    resp = await _chat(client, gw, _body(stream=True))
    assert resp.status_code == 200, resp.text
    assert "text/event-stream" in resp.headers["content-type"]
    frames = _sse_frames(resp.text)
    text = "".join(f["choices"][0]["delta"].get("content", "")
                   for f in frames if f.get("choices"))
    assert text == "你好"
    assert {f["model"] for f in frames if f.get("model")} == {SYSTEM_MODEL}

    req = seen[-1]
    assert req.url.path == "/api/web/llm/v2/chat/completions"
    assert json.loads(req.content)["stream"] is True

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == f"Raccoon 资源/{VENDOR_MODEL}"


# ============ 思考方言（extra_body.thinking）============


@pytest.mark.parametrize("over,expected_type,why", [
    ({"reasoning_effort": "off"}, "disabled", "档位 off → 真关闭（raccoon-product.ts:74-77）"),
    ({"reasoning_effort": "on"}, "enabled", "档位 on → 开启"),
    ({"thinking": {"type": "disabled"}}, "disabled", "IR 注入的顶层 thinking 被翻译进 extra_body"),
    ({"reasoning_effort": "banana"}, "enabled", "未登记档位 → 按开启（宁可多思考）"),
    ({}, None, "未指定 → 不发该字段（保持服务端默认 = 开启）"),
])
async def test_thinking_dialect_is_translated_into_extra_body(make_gateway, client, over,
                                                             expected_type, why):
    """🔴 唯一有效的思考通道 = `extra_body.thinking`（`raccoon-product.ts:55-70`）。

    顶层 `thinking` / `reasoning_effort` 对上游**无效**（前者被忽略、后者实测无效果），
    故翻译后必须**移除**它们 —— 留着只会制造「控制生效了」的假象。
    """
    _login()
    seen: list[httpx.Request] = []
    gw = await make_gateway(_cfg())
    await _install(gw, "res-rc", _handler(seen, mode="json"))

    resp = await _chat(client, gw, _body(**over))
    assert resp.status_code == 200, resp.text
    payload = json.loads(seen[-1].content)
    assert "thinking" not in payload and "reasoning_effort" not in payload   # 无效字段已清
    if expected_type is None:
        assert "extra_body" not in payload, why
    else:
        assert payload["extra_body"]["thinking"] == {"type": expected_type}, why


# ============ 错误映射（401 → disable 可识别；429/5xx → 可重试）============


def _adapter(handler) -> RaccoonOut:
    adapter = RaccoonOut(ProductAccount(product="raccoon", name=ACCOUNT, base_url=BASE))
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter


@pytest.mark.parametrize("status,expected", [
    (401, ErrorClass.AUTH),          # 上层据此 disable（终态）
    (429, ErrorClass.QUOTA),         # 冷却 + 短退避（§22.5-5）
    (503, ErrorClass.RETRYABLE),     # 可重试
])
def test_error_mapping_aligns_with_the_existing_classifier(status, expected):
    """错误形态与既有 `openai_out` 对齐：`UpstreamError(status_code, error_body)` 原样抛出。"""
    _login()
    seen: list[httpx.Request] = []
    adapter = _adapter(_handler(seen, mode="error", status=status))

    async def run():
        with pytest.raises(UpstreamError) as e:
            await adapter.chat_nonstream("", VENDOR_MODEL, {"messages": []}, 10.0)
        await adapter.aclose()
        return e.value

    err = asyncio.run(run())
    assert err.status_code == status
    assert "200003" in (err.error_body or "")               # 原始体保留（透传）
    assert ErrorClassifier().classify(err) is expected


async def test_401_disables_the_resource_end_to_end(make_gateway, client):
    """401 → 分类器 `AUTH` → 上层 `disable`（不重试、切下一资源）—— 端到端红证。"""
    _login()
    cfg = _cfg()
    cfg["resources"].append({
        "id": "res-rc2", "name": "Raccoon 备用", "vendor": "", "preset": "",
        "account": ACCOUNT, "product": "raccoon", "account_ref": ACCOUNT,
        "protocol": "openai", "base_url": "https://raccoon-e2e-2.invalid/api/web/llm/v2",
        "api_key": "", "enabled": True, "access_mode": "api",
    })
    cfg["models"][0]["resources"].append({"resource": "res-rc2", "model": "sn-glm-5-3"})
    seen_a: list[httpx.Request] = []
    seen_b: list[httpx.Request] = []
    gw = await make_gateway(cfg)
    await _install(gw, "res-rc", _handler(seen_a, mode="error", status=401))
    await _install(gw, "res-rc2", _handler(seen_b, mode="json"))

    resp = await _chat(client, gw, _body())
    assert resp.status_code == 200, resp.text
    assert resp.json()["choices"][0]["message"]["content"] == "来自假上游"

    await gw.drain_events()
    ev = gw.read_events()[0]
    assert ev["resource_attempts"][0]["attempts"] == 1        # 401 不重试
    assert gw.runtime.resources.registry.get(("res-rc", VENDOR_MODEL)).status == "disabled"
    assert gw.read_switches()[0]["reason_cls"] == "AUTH"
    assert len(seen_a) == 1 and len(seen_b) == 1
