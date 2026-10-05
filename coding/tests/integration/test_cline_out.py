"""cline 出站**端到端**（§22.3/§22.5；M6-5b 波次）。

判据 = 「账号 → 资源 → `/v1/chat/completions`」全链路在**假上游**（`httpx.MockTransport`）上跑通：

· 非流式 / 流式各一条：网关返回内容正常、`model` 被统一名替换；
· 假上游收到的**路径**（`/api/v1/chat/completions`，`cline-product.ts:301`：基址已含
  `/api/v1`，故族基类缺省 `chat_path="/chat/completions"` 恰好正确）、**身份头**
  （`Bearer workos:` **前缀保留**，`cline.ts:159-182`；客户端标识四头）、**请求体**逐项断言；
· 凭据落盘值**不带**前缀 → 出站幂等补齐；落盘值**已带**前缀 → 不重复叠加（防 `workos:workos:`）；
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
from model_gateway.upstream.cline import constants as C
from model_gateway.upstream.cline.out import ClineOut

CONFIG_KEY = "sk-config-key-must-not-be-sent"
TOKEN_BARE = "eyJhbGciOiJSUzI1NiJ9.acc"                 # 落盘形态：**不带** workos: 前缀
TOKEN_PREFIXED = f"{C.TOKEN_PREFIX}{TOKEN_BARE}"        # 落盘形态：**已带**前缀
ACCOUNT = "acc-cl"
BASE = "https://cline-e2e.invalid/api/v1"               # = registry 口径（基址含 /api/v1）
VENDOR_MODEL = "cline-free/deepseek-v4.1-flash"
SYSTEM_MODEL = "cl-model"


# ============ 假上游（MockTransport：记录请求 + 回 SSE / JSON）============


def _sse_text(model: str = VENDOR_MODEL) -> str:
    frames = [
        {"id": "chatcmpl-cl-1", "object": "chat.completion.chunk", "model": model,
         "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "chatcmpl-cl-1", "object": "chat.completion.chunk", "model": model,
         "choices": [{"index": 0, "delta": {"content": "你"}, "finish_reason": None}]},
        {"id": "chatcmpl-cl-1", "object": "chat.completion.chunk", "model": model,
         "choices": [{"index": 0, "delta": {"content": "好"}, "finish_reason": None}]},
        {"id": "chatcmpl-cl-1", "object": "chat.completion.chunk", "model": model,
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    out = "".join(f"data: {json.dumps(f, ensure_ascii=False)}\n\n" for f in frames)
    return out + "data: [DONE]\n\n"


def _handler(record: list[httpx.Request], *, mode: str = "json", status: int = 200,
             error_body: str = '{"error": {"type": "invalid_api_key", "message": "bad token"},'
                               ' "success": false}'):
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
            "id": "chatcmpl-cl-json", "object": "chat.completion", "model": body.get("model"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "来自假上游"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2}}, request=request)

    return handle


async def _install(gw, res_id: str, handler) -> None:
    """把网关内该资源的适配器客户端换成 MockTransport（并关掉原客户端，防泄漏）。"""
    adapter = gw.runtime.adapters[res_id]
    old = adapter._client
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await old.aclose()


def _cfg(*, res_id: str = "res-cl") -> dict:
    return {
        "resources": [{
            "id": res_id, "name": "Cline 资源", "vendor": "", "preset": "",
            "account": ACCOUNT, "product": "cline", "account_ref": ACCOUNT,
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


async def test_cline_nonstream_end_to_end(make_gateway, client):
    """非流式：标准 JSON 直通；头/体逐项断言（含 `workos:` 前缀幂等补齐）。"""
    store.commit_login("cline", ACCOUNT, {"access_token": TOKEN_BARE,
                                          "account_id": "usr-01M3", "email": "a@b.c"}, {})
    seen: list[httpx.Request] = []
    gw = await make_gateway(_cfg())
    await _install(gw, "res-cl", _handler(seen, mode="json"))

    resp = await _chat(client, gw, _body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "来自假上游"
    assert data["model"] == SYSTEM_MODEL                    # 统一名替换厂商名

    assert len(seen) == 1
    req = seen[0]
    assert req.url.path == "/api/v1/chat/completions"       # 取证路径（cline-product.ts:301）
    assert req.headers["authorization"] == f"Bearer {TOKEN_PREFIXED}"   # workos: 幂等补齐
    assert CONFIG_KEY not in json.dumps(dict(req.headers))  # 配置 Key 绝不外发（铁律 1）
    assert req.headers["http-referer"] == "https://cline.bot"          # cline-product.ts:269-274
    assert req.headers["x-title"] == "Cline"
    assert req.headers["x-is-multiroot"] == "false"
    assert req.headers["x-client-type"] == "cline-sdk"
    assert req.headers["accept"] == "text/event-stream"     # cline-adapter.ts:571-577
    payload = json.loads(req.content)
    assert payload["model"] == VENDOR_MODEL                 # 映射里的供应商模型名

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == f"Cline 资源/{VENDOR_MODEL}"
    assert ev["input_tokens"] == 5 and ev["output_tokens"] == 2


# ============ 非流式 · `{success, data}` 信封解包（2026-10-01 实网实测形）============


async def test_cline_nonstream_unwraps_success_data_envelope(make_gateway, client):
    """真实 cline 非流式响应 = `{success, data:{choices…}, model}` 信封 —— 必须解包。

    2026-10-01 :8300 实网取证：顶层键 `["data","success","model"]`，`choices/usage`
    全在 `data` 内；假上游此前只喂**标准体** → 全绿但真实通道对工具端破坏
    （修复前实测：客户端拿到的响应顶层无 `choices`，OpenAI SDK 直接解析失败）。
    """
    store.commit_login("cline", ACCOUNT, {"access_token": TOKEN_BARE,
                                          "account_id": "usr-01M3"}, {})
    gw = await make_gateway(_cfg())

    def envelope_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        inner = {"id": "gen-1790844839-KsMRJO1", "object": "chat.completion",
                 "model": "anthropic/claude-sonnet-5.5", "provider": "Anthropic",
                 "choices": [{"index": 0, "finish_reason": "stop",
                              "message": {"role": "assistant", "content": "成功"}}],
                 "usage": {"prompt_tokens": 8, "completion_tokens": 4}}
        return httpx.Response(200, json={"success": True, "data": inner,
                                         "model": body.get("model")}, request=request)

    await _install(gw, "res-cl", envelope_handler)
    resp = await _chat(client, gw, _body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "成功"   # 退壳后工具端可解析
    assert data["model"] == SYSTEM_MODEL                        # 统一名替换仍生效
    assert "success" not in data and "data" not in data         # 信封不残留

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["input_tokens"] == 8 and ev["output_tokens"] == 4  # usage 随退壳一并可见


def test_shape_response_is_identity_outside_the_envelope():
    """只有"顶层无 choices 且内层 data 含 choices"才退壳；其余形状原样返回（不吞不造）。"""
    adapter = ClineOut(ProductAccount(product="cline", name="acc-cl", base_url=BASE))

    standard = {"choices": [{"index": 0}], "id": "x"}
    assert adapter._shape_response(standard) is standard                 # 已是标准体
    business_error = {"success": False, "error": "x"}
    assert adapter._shape_response(business_error) is business_error     # 业务错误体
    not_choices = {"data": {"not_choices": 1}}
    assert adapter._shape_response(not_choices) is not_choices           # data 非 choices 体


# ============ 流式 ============


async def test_cline_stream_end_to_end(make_gateway, client):
    """流式请求：SSE 归一化 + 帧内 `model` 被统一名替换。"""
    store.commit_login("cline", ACCOUNT, {"access_token": TOKEN_BARE,
                                          "account_id": "usr-01M3"}, {})
    seen: list[httpx.Request] = []
    gw = await make_gateway(_cfg())
    await _install(gw, "res-cl", _handler(seen, mode="sse"))

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
    assert req.headers["authorization"] == f"Bearer {TOKEN_PREFIXED}"

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == f"Cline 资源/{VENDOR_MODEL}"


async def test_stored_token_with_prefix_is_not_double_prefixed(make_gateway, client):
    """凭据里**已带** `workos:` 前缀 → 出站不重复叠加（防 `workos:workos:`）。"""
    store.commit_login("cline", ACCOUNT, {"access_token": TOKEN_PREFIXED, "account_id": "usr-01M3"}, {})
    seen: list[httpx.Request] = []
    gw = await make_gateway(_cfg())
    await _install(gw, "res-cl", _handler(seen, mode="json"))

    resp = await _chat(client, gw, _body())
    assert resp.status_code == 200, resp.text
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN_PREFIXED}"


# ============ 错误映射（401 → disable 可识别；429/5xx → 可重试）============


def _adapter(handler) -> ClineOut:
    adapter = ClineOut(ProductAccount(product="cline", name=ACCOUNT, base_url=BASE))
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter


@pytest.mark.parametrize("status,expected", [
    (401, ErrorClass.AUTH),          # 上层据此 disable（终态）
    (429, ErrorClass.QUOTA),         # 冷却 + 短退避（§22.5-5）
    (503, ErrorClass.RETRYABLE),     # 可重试
])
def test_error_mapping_aligns_with_the_existing_classifier(status, expected):
    """错误形态与既有 `openai_out` 对齐：`UpstreamError(status_code, error_body)` 原样抛出。

    ⚠️ **403 不在本表**：本产品特有 —— 地域封锁/模型未开通即 403
    （`cline-adapter.ts:600-640` 的真实缺陷），分类器天然归 `BAD_REQUEST`
    （不 disable、不重试、原样透传），不得当凭据问题处理。
    """
    store.commit_login("cline", ACCOUNT, {"access_token": TOKEN_BARE, "account_id": "usr-01M3"}, {})
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


def test_403_region_block_is_not_treated_as_an_auth_error():
    """🔴 403 = 地域封锁/模型未开通（本产品特有）→ `BAD_REQUEST`，**绝不** disable
    （DSH 早期把 401/403 一律当凭据过期，界面显示「API 密钥无效」，真实原因被掩盖）。"""
    store.commit_login("cline", ACCOUNT, {"access_token": TOKEN_BARE, "account_id": "usr-01M3"}, {})
    seen: list[httpx.Request] = []
    adapter = _adapter(_handler(seen, mode="error", status=403, error_body=(
        '{"error":"access forbidden: cline-free/muse-spark-1.3-contributor'
        ' is not available in your region","success":false}')))

    async def run():
        with pytest.raises(UpstreamError) as e:
            await adapter.chat_nonstream("", VENDOR_MODEL, {"messages": []}, 10.0)
        await adapter.aclose()
        return e.value

    err = asyncio.run(run())
    assert err.status_code == 403
    assert "not available in your region" in (err.error_body or "")
    assert ErrorClassifier().classify(err) is ErrorClass.BAD_REQUEST


async def test_401_disables_the_resource_end_to_end(make_gateway, client):
    """401 → 分类器 `AUTH` → 上层 `disable`（不重试、切下一资源）—— 端到端红证。"""
    store.commit_login("cline", ACCOUNT, {"access_token": TOKEN_BARE, "account_id": "usr-01M3"}, {})
    cfg = _cfg()
    cfg["resources"].append({
        "id": "res-cl2", "name": "Cline 备用", "vendor": "", "preset": "",
        "account": ACCOUNT, "product": "cline", "account_ref": ACCOUNT,
        "protocol": "openai", "base_url": "https://cline-e2e-2.invalid/api/v1",
        "api_key": "", "enabled": True, "access_mode": "api",
    })
    cfg["models"][0]["resources"].append({"resource": "res-cl2", "model": "stealth/space-bunny-alpha"})
    seen_a: list[httpx.Request] = []
    seen_b: list[httpx.Request] = []
    gw = await make_gateway(cfg)
    await _install(gw, "res-cl", _handler(seen_a, mode="error", status=401))
    await _install(gw, "res-cl2", _handler(seen_b, mode="json"))

    resp = await _chat(client, gw, _body())
    assert resp.status_code == 200, resp.text
    assert resp.json()["choices"][0]["message"]["content"] == "来自假上游"

    await gw.drain_events()
    ev = gw.read_events()[0]
    assert ev["resource_attempts"][0]["attempts"] == 1        # 401 不重试
    assert gw.runtime.resources.registry.get(("res-cl", VENDOR_MODEL)).status == "disabled"
    assert gw.read_switches()[0]["reason_cls"] == "AUTH"
    assert len(seen_a) == 1 and len(seen_b) == 1
