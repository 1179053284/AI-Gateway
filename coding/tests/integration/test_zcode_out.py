"""zcode 出站**端到端**（§17/§18/§22.3；M6-5c）。

判据 = 「账号 → 资源 → `/v1/chat/completions`」全链路在**假 Anthropic 上游**上跑通，
且 §17 的三条接线逐项成立：

· **协议复用**：走 `AnthropicOutAdapter`（Anthropic Messages 请求/SSE 事件/usage 映射），
  端点 = `{资源基址}/v1/messages`（产品注册表 `base_url` =
  `https://zcode.z.ai/api/v1/zcode-plan/anthropic`，§17 表）；
· **Plan/JWT 通道**：`Authorization: Bearer <zcodejwttoken>` + `X-Device-Mid`
  （**统一走 `auth.build_headers`**，不另写一份；`auth.py:53-71`）；
· **验证码注入缝**：注入 → 头 `x-aliyun-captcha-verify-param` **每请求现产**
  （两次请求两个 param —— param 一次性，复用必得 3007，`zcode-adapter.ts:30-33,494-495`）；
  **未注入 → 不带该头**（= §17 降级链的「JWT 直连」档，**不编造 param**）；
· **TLS 指纹按配置**：`gateway.zcode.fingerprint` 驱动（curl_cffi 缺失时自适应降级）。
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
from model_gateway.upstream.zcode import out as zcode_out

CONFIG_KEY = "sk-config-key-must-not-be-sent"
#: JWT 形状（三段点分；`auth.looks_like_jwt` 同口径）
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ6Yy0xIn0.c2ln"
DEVICE_MID = "mid-0123456789abcdef"
PATH = "/api/v1/zcode-plan/anthropic/v1/messages"


class _FakeAnthropicUpstream:
    """假 ZCode Plan 通道（Anthropic Messages；**全路径**与生产同形）。"""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.status = 200
        self.app = Starlette(routes=[Route(PATH, self._messages, methods=["POST"])])

    async def _messages(self, request: Request):
        body = await request.json()
        self.requests.append({"path": request.url.path, "headers": dict(request.headers),
                              "body": body})
        if self.status != 200:
            return JSONResponse({"code": 3012, "msg": "unusual activity"},
                                status_code=self.status)
        if body.get("stream"):
            return StreamingResponse(self._sse(), media_type="text/event-stream")
        return JSONResponse({
            "id": "msg_fake", "type": "message", "role": "assistant",
            "model": body["model"], "content": [{"type": "text", "text": "来自假 ZCode"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 11, "output_tokens": 5},
        })

    async def _sse(self):
        events = [
            ("message_start", {"type": "message_start", "message": {
                "id": "msg_fake", "type": "message", "role": "assistant",
                "usage": {"input_tokens": 11, "output_tokens": 0}}}),
            ("content_block_start", {"type": "content_block_start", "index": 0,
                                     "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "text_delta", "text": "你"}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "thinking_delta", "thinking": "想"}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "text_delta", "text": "好"}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_delta", {"type": "message_delta",
                               "delta": {"stop_reason": "end_turn"},
                               "usage": {"input_tokens": 11, "output_tokens": 5}}),
            ("message_stop", {"type": "message_stop"}),
        ]
        for name, data in events:
            yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@pytest.fixture
async def anthropic_upstream():
    fake = _FakeAnthropicUpstream()
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


def _cfg(port: int, *, account: str = "zc-1", model_name: str = "zc-model",
         vendor_model: str = "GLM-5.3") -> dict:
    return {
        "resources": [{
            "id": "res-zcode", "name": "ZCode 资源", "vendor": "", "preset": "",
            "account": account, "product": "zcode", "account_ref": account,
            "protocol": "anthropic",
            # 与注册表同形：基址到 `/anthropic`，适配器再拼 `/v1/messages`
            "base_url": f"http://127.0.0.1:{port}/api/v1/zcode-plan/anthropic",
            "api_key": CONFIG_KEY,       # 故意留着：出站必须**不用**它（铁律 1）
            "enabled": True, "access_mode": "plan",
        }],
        "models": [{"name": model_name, "endpoint": "chat",
                    "resources": [{"resource": "res-zcode", "model": vendor_model}]}],
    }


def _body(model: str = "zc-model", **over) -> dict:
    data = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    data.update(over)
    return data


def _login(account: str = "zc-1", jwt: str = JWT) -> None:
    """造一个账号（走生产同一条落盘入口；凭据 = 设备流登录写的那份）。"""
    store.commit_login("zcode", account, {"zcodejwttoken": jwt, "device_mid": DEVICE_MID}, {})


def dataroot_root():
    """zcode 账号根（与 `_resolved_credentials` 兜底腿用的**同一个**解析口）。"""
    from model_gateway.upstream.zcode import product as _zp

    return _zp._account_root_of(None)


# ============ 非流式 ============

async def test_zcode_nonstream_end_to_end(anthropic_upstream, make_gateway, client):
    _login()
    gw = await make_gateway(_cfg(anthropic_upstream.port))

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "来自假 ZCode"
    assert data["model"] == "zc-model"

    assert len(anthropic_upstream.requests) == 1
    req = anthropic_upstream.requests[0]
    assert req["path"] == PATH                                    # Plan 通道全路径
    assert req["headers"]["authorization"] == f"Bearer {JWT}"     # Plan/JWT 通道
    assert req["headers"]["x-device-mid"] == DEVICE_MID           # 缺它回 400/3001
    assert req["headers"]["anthropic-version"] == "2023-06-01"
    assert "x-api-key" not in req["headers"]                      # 两通道不混用
    assert CONFIG_KEY not in json.dumps(req["headers"])           # 配置 Key 绝不外发
    assert "x-aliyun-captcha-verify-param" not in req["headers"]  # 未注入 → JWT 直连档
    assert req["body"]["model"] == "GLM-5.3"                      # 目录官方大小写直通
    assert "stream" not in req["body"] or req["body"]["stream"] is False

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == "ZCode 资源/GLM-5.3"
    assert ev["input_tokens"] == 11 and ev["output_tokens"] == 5  # usage 在适配器内映射（§18.2③）


# ============ 流式（Anthropic 事件 → OpenAI chunk）============

async def test_zcode_stream_end_to_end(anthropic_upstream, make_gateway, client):
    _login()
    gw = await make_gateway(_cfg(anthropic_upstream.port))

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body(stream=True))
    assert resp.status_code == 200, resp.text
    frames = []
    for line in resp.text.splitlines():
        if line.startswith("data: ") and line[6:].strip() not in ("", "[DONE]"):
            frames.append(json.loads(line[6:]))
    text = "".join(f["choices"][0]["delta"].get("content", "")
                   for f in frames if f.get("choices"))
    think = "".join(f["choices"][0]["delta"].get("reasoning_content", "")
                    for f in frames if f.get("choices"))
    assert text == "你好" and think == "想"
    assert {f["model"] for f in frames if f.get("model")} == {"zc-model"}
    assert anthropic_upstream.requests[-1]["body"]["stream"] is True


# ============ 验证码注入缝 ============

async def test_zcode_captcha_seam_mints_a_fresh_param_per_request(
        anthropic_upstream, make_gateway, client, monkeypatch):
    """注入 provider → 头带 param；**每请求一个**（param 一次性，复用必 3007）。"""
    minted: list[str] = []

    async def provider() -> str:
        minted.append(f"param-{len(minted) + 1}")
        return minted[-1]

    monkeypatch.setattr(zcode_out, "CAPTCHA_PROVIDER", provider)
    _login()
    gw = await make_gateway(_cfg(anthropic_upstream.port))

    assert (await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())).status_code == 200
    assert (await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())).status_code == 200

    headers = [r["headers"] for r in anthropic_upstream.requests]
    assert headers[0]["x-aliyun-captcha-verify-param"] == "param-1"
    assert headers[1]["x-aliyun-captcha-verify-param"] == "param-2"   # 不复用（**关键**）
    assert headers[0]["x-aliyun-captcha-verify-region"] == "cn"       # zcode-adapter.ts:563


# ============ TLS 指纹按配置（§17）============

async def test_zcode_fingerprint_follows_config(monkeypatch):
    """`gateway.zcode.fingerprint` 驱动适配器开关；`curl_cffi` 缺失时自动降级 httpx。"""
    from model_gateway.adapters.product_out import ProductAccount

    class _ZcodeCfg:
        fingerprint = True

    class _Gw:
        zcode = _ZcodeCfg()

    class _Cfg:
        gateway = _Gw()

    monkeypatch.setattr("model_gateway.config.loader.load_config", lambda: _Cfg())
    adapter = zcode_out.ZcodeOut(ProductAccount(product="zcode", name="zc-1",
                                                base_url="https://zcode.z.ai"))
    try:
        assert adapter.fingerprint is True                    # 配置生效
    finally:
        await adapter.aclose()


# ============ fail closed 与错误通道 ============

async def test_zcode_missing_credential_fails_closed(anthropic_upstream, make_gateway, client):
    """两条落点都没有凭据 → 可读失败 + **零次上游请求**（fail-closed 不变）。

    🔴 判据随 2026-10-05 D1 轮**改写而非放宽**：`credentials_from="product"` 之后，
    判死的位置从公共层（`resolve_context` 读空即 503）挪到产品层（两条落点都取不到才 503），
    所以文案里那句「无凭据（未登录或凭据文件缺失）」换成了点名**两处**的可读原因 ——
    "凭据本体与客户端数据根都没有"。这里钉的仍然是同一件事：**没凭据就绝不打上游**，
    外加一条新判据：原因必须说清是**两处**都没有（旧文案把"整根隔离布局是常态"误报成
    "你没登录"，正是这条腿对 16 个导入号结构性死亡却无人察觉的原因）。
    """
    gw = await make_gateway(_cfg(anthropic_upstream.port))      # 刻意不 _login()

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 503, resp.text
    blob = json.dumps(resp.json(), ensure_ascii=False)
    assert "凭据缺少 zcodejwttoken" in blob and "客户端数据根" in blob, blob
    assert anthropic_upstream.requests == [], "凭据缺失仍发起了上游请求"


async def test_zcode_401_disables_the_resource(anthropic_upstream, make_gateway, client):
    """JWT 被拒（401）→ 资源停用（§22.5-5「401 → disable（终态）」），错误如实透传。"""
    _login(jwt="eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJvbGQifQ.c2ln")
    gw = await make_gateway(_cfg(anthropic_upstream.port))
    anthropic_upstream.status = 401

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 401, resp.text
    assert len(anthropic_upstream.requests) == 1                # 单个资源、不重试
    await gw.drain_events()
    assert gw.read_events()[-1]["status"] == "failed"


async def test_zcode_credentials_only_in_client_root_still_forward(
        anthropic_upstream, make_gateway, client, tmp_path):
    """**2026-10-05 D1 轮的根因判据**：实盘 16 个 zcode 号的凭据**只**落在
    `<账号>/data/.zcode/v2/credentials.json`（`mgw zcode import` 的整根隔离布局），
    公共层 `credentials.json` 一个都没有 —— 旧实现在 `resolve_context` 读空就判死，
    ⇒ 转发腿对每个导入号结构性 503，而额度腿/探活腿用产品层兜底读法照常工作
    （事件流水里 zcode 承接 0 行的真因）。现在必须能出词。"""
    from model_gateway.upstream.zcode import oauth as zoauth

    from model_gateway.upstream.zcode import dataroot

    account = "zc-imported"
    # 公共层凭据留空、meta 里带设备码 —— 与实盘 16 个导入号逐字同形
    store.commit_login("zcode", account, {}, {"device_mid": DEVICE_MID})
    # 🔴 必须写进**读取侧同一个根**：`store.account_dir("zcode", name)` 不带 root 时返回的是
    # 相对名（`zcode/<name>`），照着它写就写进了一个游离目录 ⇒ 判据空转（第一版就是这么"假失败"的）。
    v2 = dataroot.v2_dir_of(dataroot_root(), account)
    v2.mkdir(parents=True, exist_ok=True)
    (v2 / "credentials.json").write_text(
        json.dumps({"zcodejwttoken": JWT, "deviceMid": DEVICE_MID}), encoding="utf-8")

    cfg = _cfg(anthropic_upstream.port, account=account)
    gw = await make_gateway(cfg)
    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 200, resp.text
    assert resp.json()["choices"][0]["message"]["content"] == "来自假 ZCode"
    assert len(anthropic_upstream.requests) == 1
    req = anthropic_upstream.requests[0]
    assert req["headers"]["authorization"] == f"Bearer {JWT}"
    assert req["headers"]["x-device-mid"] == DEVICE_MID    # meta.json 里那份设备码
