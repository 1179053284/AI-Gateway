"""qodercn 出站**端到端**（§22.3/§22.4/§22.5；M6-5c）。

判据 = 「账号 → 资源 → `/v1/chat/completions`」全链路在**假上游**（`httpx.MockTransport`）上跑通，
且区域实例必须是 **CN**（零复制复用 `qoder/out.py::QoderOut`，家族差异只有 `QODER_CN` 配置值）：

· **接线**（`qodercn/product.py::build_out`）：断言返回共享 `QoderOut` 且区域身份 = `QODER_CN`
  —— 这里串了区域 =「打错域名 + 用错 client_id」（`qoder-product.ts:592-612`）；
· **非流式 / 流式各一条**：响应是「信封套 OpenAI SSE」（`qoder-envelope.ts:8-12`），剥完即标准
  chunk；请求体 `model_config.key` = **目录 key**、`business` 必填（`qoder-adapter.ts:726-736`）；
  目录取 **CN 兜底表**——用同 id 两站异值的 `mmodel` 反证（CN：MiniMax-M2.7 / 200K / 未声明
  is_vl；国际：MiniMax-M3 / 1M / is_vl=true，`qoder-product.ts:435` vs `:580`）；
· **两站互不串用**（§22.4）：qodercn 资源挂国际版凭据（`family="qoder"`）→ 可读失败
  （503，`flow._guard_family` 同款判据、`no_failover`）+ **零次上游请求** + 签名器零调用；
  反向（qoder 资源挂 CN 凭据）同样被拒 —— 两个方向都锁；
· 请求加密与 COSY 签名生产走本机 wasm 桥；本文件走 `SIGNER_FACTORY` 注入缝
   （假签名器，见 `qoder/out.py` 模块头）：
  本文件注入**假签名器**验证「明文 ask → url/headers/body → 信封解包」全链路；
  假签名器**不模拟 WASM**，只证明本层交付的拼接契约正确。

假上游 = `httpx.MockTransport`（**零网络**：资源基址是 `.invalid` 域，签名器产物也只落在该域，
mock 不生效即 DNS 失败）；网关走 `make_gateway` 基建（独立实例 + 临时配置/usage 目录）。
"""

from __future__ import annotations

import json

import httpx

from model_gateway.accounts import store
from model_gateway.adapters.product_out import ProductAccount
from model_gateway.upstream.qoder import out as qoder_out
from model_gateway.upstream.qoder.config import QODER, QODER_CN
from model_gateway.upstream.qodercn import product as qodercn

CONFIG_KEY = "sk-config-key-must-not-be-sent"
CN_TOKEN = "QODERCN-TOKEN-FROM-ACCOUNT"
ACCOUNT = "cn-acc-1"
SYSTEM_MODEL = "cn-model"
VENDOR_MODEL = "mmodel"                       # CN 表：MiniMax-M2.7 / 200K / 未声明 is_vl
BASE = "https://qodercn-e2e.invalid"          # 资源基址（.invalid：mock 不生效必失败，零网络）
ENDPOINT_SUFFIX = "?FetchKeys=llm_model_result&AgentId=agent_common&Encode=1"


# ============ 假上游（MockTransport：记录请求 + 回信封 SSE）============


def _envelope(inner: dict | str) -> str:
    """把内层帧（OpenAI chunk 或业务错误）包成信封（`qoder-envelope.ts:8-12` 的形态）。"""
    body = inner if isinstance(inner, str) else json.dumps(inner, ensure_ascii=False)
    return json.dumps({"headers": {"content-type": "application/json"}, "body": body,
                       "statusCodeValue": 200, "statusCode": "OK"}, ensure_ascii=False)


def _chunk(**delta) -> dict:
    return {"id": "c-cn-1", "object": "chat.completion.chunk", "model": VENDOR_MODEL,
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}


def _handler(record: list[httpx.Request], bodies: list[dict | str]):
    """MockTransport handler：逐帧回信封 SSE（内层 = 标准 OpenAI chunk）。"""

    def handle(request: httpx.Request) -> httpx.Response:
        record.append(request)
        lines = [f"data: {_envelope(b)}\n\n" for b in bodies]
        return httpx.Response(200, text="".join(lines), request=request,
                              headers={"content-type": "text/event-stream"})

    return handle


async def _install(gw, res_id: str, handler) -> None:
    """把网关内该资源的适配器客户端换成 MockTransport（并关掉原客户端，防泄漏）。"""
    adapter = gw.runtime.adapters[res_id]
    old = adapter._client
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await old.aclose()


#: 假签名器记录的签名输入（用例断言区域注入用）
SIGNED: list[dict] = []


def _install_fake_signer(monkeypatch):
    """注入假签名器（`SIGNER_FACTORY` 契约：与 DSH `prepareInfer` 同形）。

    产物 URL 落在**资源基址**（`.invalid`，见模块头）；另记录本区域的
    `encrypted_infer_base` 供「域名注入正确」断言（CN 的加密端点是
    `gateway.qoder.com.cn`，与国际版不共用，`qoder-product.ts:604`）。
    """
    SIGNED.clear()

    def factory(product_cfg, base_url, cred, meta):
        def sign(ask: dict):
            SIGNED.append({"region": product_cfg.id,
                           "encrypted_base": product_cfg.encrypted_infer_base,
                           "base_url": base_url, "ask": ask,
                           "token": cred.get("access_token")})
            return qoder_out.SignedRequest(
                url=f"{base_url}/algo/api/v2/service/pro/sse/agent_chat_generation"
                    f"{ENDPOINT_SUFFIX}",
                headers={"Authorization": "Bearer COSY.FAKE-PAYLOAD.FAKE-SIG",
                         "Content-Type": "application/json", "Cosy-Version": "1.1.49",
                         "X-Request-Id": "req-cn-1"},
                body=json.dumps(ask, ensure_ascii=False))

        return sign

    monkeypatch.setattr(qoder_out, "SIGNER_FACTORY", factory)


def _cfg(*, product: str = "qodercn", account: str = ACCOUNT,
         model_name: str = SYSTEM_MODEL, vendor_model: str = VENDOR_MODEL) -> dict:
    return {
        "resources": [{
            "id": f"res-{product}", "name": f"{product} 资源", "vendor": "", "preset": "",
            "account": account, "product": product, "account_ref": account,
            "protocol": "openai", "base_url": BASE,
            "api_key": CONFIG_KEY,       # 故意留着：出站必须**不用**它（铁律 1）
            "enabled": True, "access_mode": "api",
        }],
        "models": [{"name": model_name, "endpoint": "chat",
                    "resources": [{"resource": f"res-{product}", "model": vendor_model}]}],
    }


def _body(model: str = SYSTEM_MODEL, **over) -> dict:
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


# ============ 接线（零复制的唯一差异点 = 区域实例）============


async def test_build_out_injects_cn_region_instance():
    """`qodercn/product.py::build_out` → 共享 `QoderOut` + **`QODER_CN` 区域配置**。

    两站 token 不通用（§22.4）：区域串用在这里就发生（域名 / client_id / 签名端点
    三项全不同）——本用例把"注入的必须是中国版实例"钉死在接线处。
    """
    adapter = qodercn.build_out(ProductAccount(product="qodercn", name=ACCOUNT, base_url=BASE))
    try:
        assert type(adapter) is qoder_out.QoderOut        # 复用同一实现（零复制）
        assert adapter.region == "qodercn"
        assert adapter._cfg is QODER_CN
        assert adapter._cfg is not QODER
        assert adapter._cfg.encrypted_infer_base == "https://gateway.qoder.com.cn"  # :604
    finally:
        await adapter.aclose()


# ============ 非流式（信封解包 + 目录 key + CN 兜底表）============


async def test_qodercn_nonstream_end_to_end(make_gateway, client, monkeypatch):
    """非流式全链路：CN 账号 → 资源 → 信封逐帧剥出聚合；目录取 CN 表（`mmodel` 异值反证）。"""
    _install_fake_signer(monkeypatch)
    store.commit_login("qodercn", ACCOUNT,
                       {"access_token": CN_TOKEN, "security_oauth_token": CN_TOKEN,
                        "machine_id": "cn-machine-id", "family": "qodercn"}, {})
    seen: list[httpx.Request] = []
    gw = await make_gateway(_cfg())          # vendor_model = mmodel（同 id 两站异值）
    await _install(gw, "res-qodercn", _handler(seen, [
        _chunk(role="assistant", content=""),
        _chunk(content="你"),
        _chunk(content="好"),
        _chunk(finish_reason="stop"),
    ]))

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "你好"     # 信封逐帧剥出后聚合
    assert data["model"] == SYSTEM_MODEL                          # 统一名替换厂商名

    assert len(seen) == 1
    req = seen[0]
    assert req.url.host == "qodercn-e2e.invalid"                  # mock 生效（零网络）
    assert req.url.path == "/algo/api/v2/service/pro/sse/agent_chat_generation"
    assert req.url.query.decode() == "FetchKeys=llm_model_result&AgentId=agent_common&Encode=1"
    assert req.headers["authorization"] == "Bearer COSY.FAKE-PAYLOAD.FAKE-SIG"
    assert req.headers["cosy-version"] == "1.1.49"
    assert CONFIG_KEY not in json.dumps(dict(req.headers))        # 配置 Key 绝不外发（铁律 1）

    assert len(SIGNED) == 1
    assert SIGNED[0]["region"] == "qodercn"                       # 注入的是 CN 区域实例
    assert SIGNED[0]["encrypted_base"] == QODER_CN.encrypted_infer_base
    assert SIGNED[0]["encrypted_base"] != QODER.encrypted_infer_base   # 不是国际版域名
    assert SIGNED[0]["base_url"] == BASE                          # 资源基址按契约传给工厂
    assert SIGNED[0]["token"] == CN_TOKEN
    ask = SIGNED[0]["ask"]
    assert ask["model_config"]["key"] == VENDOR_MODEL             # 加密端点认**目录 key**
    assert ask["chat_context"]["extra"]["modelConfig"]["key"] == VENDOR_MODEL
    assert ask["business"] == {"type": "agent"}                   # 必填（qoder-adapter.ts:736）
    assert ask["session_type"] == "qodercli"
    assert ask["stream"] is True and ask["tools"] == []
    # CN 兜底表（不是国际版的表）：mmodel 在 CN = 200K / 未声明 is_vl（国际 = 1M / true）
    assert ask["model_config"]["max_input_tokens"] == 200_000
    assert ask["model_config"]["is_vl"] is False
    assert ask["model_config"]["is_reasoning"] is False

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == f"qodercn 资源/{VENDOR_MODEL}"


# ============ 流式（含信封边界外的裸帧容错）============


async def test_qodercn_stream_end_to_end(make_gateway, client, monkeypatch):
    """流式全链路：信封帧逐帧剥出 → 网关 SSE；`model` 被统一名替换。"""
    _install_fake_signer(monkeypatch)
    store.commit_login("qodercn", ACCOUNT, {"access_token": CN_TOKEN, "family": "qodercn"}, {})
    seen: list[httpx.Request] = []
    gw = await make_gateway(_cfg())
    await _install(gw, "res-qodercn", _handler(seen, [
        _chunk(role="assistant", content=""),
        _chunk(content="你"),
        # 中间插一帧**已经是标准 OpenAI chunk** 的裸帧（信封容错，`qoder-envelope.ts:107-112`）
        {"id": "c-cn-2", "object": "chat.completion.chunk", "model": VENDOR_MODEL,
         "choices": [{"index": 0, "delta": {"content": "好"}, "finish_reason": None}]},
        _chunk(finish_reason="stop"),
    ]))

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body(stream=True))
    assert resp.status_code == 200, resp.text
    assert "text/event-stream" in resp.headers["content-type"]
    frames = _sse_frames(resp.text)
    text = "".join(f["choices"][0]["delta"].get("content", "")
                   for f in frames if f.get("choices"))
    assert text == "你好"
    assert {f["model"] for f in frames if f.get("model")} == {SYSTEM_MODEL}

    assert len(seen) == 1 and seen[0].url.host == "qodercn-e2e.invalid"
    assert SIGNED[0]["region"] == "qodercn"
    await gw.drain_events()
    assert gw.read_events()[-1]["status"] == "success"


# ============ 两站互不串用（§22.4：两个方向都锁）============


async def test_qodercn_refuses_qoder_credential_end_to_end(make_gateway, client, monkeypatch):
    """qodercn 资源挂国际版凭据（`family="qoder"`）→ 可读失败 + **零次上游请求** + 签名器零调用。"""
    _install_fake_signer(monkeypatch)
    store.commit_login("qodercn", ACCOUNT, {"access_token": "INTL-TOKEN", "family": "qoder"}, {})
    seen: list[httpx.Request] = []
    gw = await make_gateway(_cfg())
    await _install(gw, "res-qodercn", _handler(seen, [_chunk(content="不该出现")]))

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 503, resp.text
    assert "不符" in resp.text and "qodercn" in resp.text          # flow._guard_family 同款判据
    assert "两站 token 不通用" in resp.text
    assert seen == []                                              # 零次上游请求
    assert SIGNED == []                                            # 也没到签名器

    await gw.drain_events()
    assert gw.read_events()[-1]["status"] == "failed"


async def test_qoder_refuses_qodercn_credential_mirror(make_gateway, client, monkeypatch):
    """反向：qoder 资源挂 CN 凭据（`family="qodercn"`）→ 同样被拒（同一份护栏，两个方向都锁）。"""
    _install_fake_signer(monkeypatch)
    store.commit_login("qoder", "qd-1", {"access_token": "CN-TOKEN", "family": "qodercn"}, {})
    seen: list[httpx.Request] = []
    gw = await make_gateway(_cfg(product="qoder", account="qd-1",
                                 model_name="qd-model", vendor_model="qfmodel"))
    await _install(gw, "res-qoder", _handler(seen, [_chunk(content="不该出现")]))

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body("qd-model"))
    assert resp.status_code == 503, resp.text
    assert "不符" in resp.text and "qodercn" in resp.text
    assert seen == [] and SIGNED == []
