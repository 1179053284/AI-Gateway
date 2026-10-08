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


# ============ 3012 防线（2026-10-07 P0 批次） ============

async def test_zcode_identity_blocks_injected_nonstream(
        anthropic_upstream, make_gateway, client):
    """**P0-1 契约**：转发请求的 system 必须是**官方身份块数组**——
    首块逐字 cliPrefix、次块 stable（2898 字符合计）、调用方 system 追加在最后、
    断点只在最后一块。缺身份块 = 405+3012（DSH 消融矩阵 `zcode-identity.ts:10-32`，
    2026-10-05/06 实盘 10 次 JSON 3012 的根因）。"""
    _login()
    gw = await make_gateway(_cfg(anthropic_upstream.port))

    body = _body(messages=[{"role": "system", "content": "调用方的系统提示"},
                           {"role": "user", "content": "hi"}])
    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=body)
    assert resp.status_code == 200, resp.text

    req = anthropic_upstream.requests[0]
    system = req["body"]["system"]
    assert isinstance(system, list), f"system 须为块数组，实测 {type(system)}"
    from model_gateway.upstream.zcode import identity as zid
    assert zid.has_official_identity(system), "首块不是官方 cliPrefix"
    assert system[0]["text"] == zid.OFFICIAL_CLI_PREFIX
    assert system[1]["text"] == "\n\n".join(zid.OFFICIAL_STABLE_SECTIONS)
    assert system[2]["text"] == "调用方的系统提示", "调用方 system 必须垫在官方块之后"
    assert zid.identity_chars(system) == 2898 + len("调用方的系统提示")
    # 断点只在最后一块（前缀式缓存语义；预算留给 tools）
    assert system[-1].get("cache_control") == {"type": "ephemeral"}
    assert sum(1 for b in system if b.get("cache_control")) == 1


async def test_zcode_identity_blocks_injected_stream(
        anthropic_upstream, make_gateway, client):
    """**P0-1 流式同判**：流式路径的 system 与非流式同形（`_prepare_payload`
    在两条腿的同一位置调用）。"""
    _login()
    gw = await make_gateway(_cfg(anthropic_upstream.port))

    body = _body(stream=True)
    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=body)
    assert resp.status_code == 200, resp.text

    from model_gateway.upstream.zcode import identity as zid
    system = anthropic_upstream.requests[-1]["body"]["system"]
    assert isinstance(system, list) and zid.has_official_identity(system)
    # 无调用方 system：只有官方两块（2898 字符），断点在 stable 上
    assert len(system) == 2 and zid.identity_chars(system) == 2898


async def test_zcode_risk_control_error_carries_marker(
        anthropic_upstream, make_gateway, client):
    """**P0-2 契约**：上游回 3012 信封 ⇒ `UpstreamError.risk_control=True`
    + `error_type=RISK_CONTROL_TYPE`（分类仍 RETRYABLE——换号语义保留；
    调度器按标记走「首试即 30min bench」而非计 C）。"""
    from model_gateway.core.errors import RISK_CONTROL_TYPE, UpstreamError
    from model_gateway.upstream.zcode.out import _as_risk_control

    e = _as_risk_control(UpstreamError(
        "upstream 405", status_code=405,
        error_body='{"code":3012,"msg":"request has been blocked due to unusual activity.",'
                   '"logid":"abc123"}'))
    assert e.risk_control is True
    assert e.error_type == RISK_CONTROL_TYPE

    # 3007（验证码一次性）同样带标记
    e2 = _as_risk_control(UpstreamError(
        "upstream 400", status_code=400,
        error_body='{"code":3007,"msg":"captcha verify failed"}'))
    assert e2.risk_control is True

    # 405 + WAF HTML（doctype 开头）走 405 兜底支也带标记
    e3 = _as_risk_control(UpstreamError(
        "upstream 405", status_code=405,
        error_body="<!doctype html><html lang=\"zh-cn\"><body>WAF</body></html>"))
    assert e3.risk_control is True

    # P1-5 诊断行：shape（3012-json vs waf-html）+ identity（注入状态+实测字符数）+ logid
    assert "shape=3012-json" in str(e.args[0]) and "logid=abc123" in str(e.args[0]), e.args
    assert "shape=waf-html" in str(e3.args[0]), e3.args  # WAF HTML 与 3012 JSON 可判
    from model_gateway.upstream.zcode.out import _IDENTITY_CHARS, _IDENTITY_INJECTED
    _IDENTITY_INJECTED.set(True)
    _IDENTITY_CHARS.set(3210)  # 模拟「官方 2898 + 调用方 system」的实测值
    e4 = _as_risk_control(UpstreamError("upstream 405", status_code=405,
        error_body='{"code":3012,"msg":"unusual activity"}'))
    assert "identity=已注入" in str(e4.args[0]), e4.args
    assert "3210 字符" in str(e4.args[0]), e4.args        # 实测值（非常量回显）
    assert "官方段" in str(e4.args[0]), e4.args           # 与官方预期并排
    _IDENTITY_INJECTED.set(False)
    _IDENTITY_CHARS.set(0)

    # 对照：普通 500 不带标记；401/403/404/408/429 不被风控归一化接管
    plain = _as_risk_control(UpstreamError("upstream 500", status_code=500))
    assert plain.risk_control is False
    own = _as_risk_control(UpstreamError("upstream 401", status_code=401))
    assert own.risk_control is False and own.error_type is None


async def test_zcode_fingerprint_end_to_end_stream_and_nonstream(
        anthropic_upstream, make_gateway, client, monkeypatch):
    """**P1-4 契约（2026-10-07 T5b 补全）**：`fingerprint=true` + curl_cffi 已装的
    完整转发路径（非流式 + 流式）—— 薄包装 `CurlCffiClient` 在适配器真实链路
    （`post(content=)` / `stream` 上下文 / `aiter_lines` bytes→str / `aclose`）
    全程工作。装上 curl_cffi 前该形状从未被真实执行过（降级掩盖）。"""
    pytest.importorskip("curl_cffi")
    from model_gateway.upstream.zcode.auth import CurlCffiClient

    class _ZcodeCfg:
        fingerprint = True

    class _Gw:
        zcode = _ZcodeCfg()

    class _Cfg:
        gateway = _Gw()

    monkeypatch.setattr("model_gateway.config.loader.load_config", lambda: _Cfg())
    _login()
    gw = await make_gateway(_cfg(anthropic_upstream.port))

    # 非流式
    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 200, resp.text
    assert resp.json()["choices"][0]["message"]["content"] == "来自假 ZCode"

    # 流式（SSE 经 aiter_lines bytes→str 归一）
    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body(stream=True))
    assert resp.status_code == 200, resp.text
    text = "".join(
        json.loads(l[6:])["choices"][0]["delta"].get("content", "")
        for l in resp.text.splitlines()
        if l.startswith("data: ") and l[6:].strip() not in ("", "[DONE]"))
    assert text == "你好", f"SSE 经 curl_cffi 包装后正文损坏：{text!r}"

    # 身份块在 fingerprint 路径同样注入
    from model_gateway.upstream.zcode import identity as zid
    system = anthropic_upstream.requests[-1]["body"]["system"]
    assert zid.has_official_identity(system)


async def test_curl_cffi_errors_are_translated_to_httpx_types():
    """**2026-10-07 23:10 实盘缺陷的回归判据**：curl_cffi 的异常树独立于 httpx，
    而 `anthropic_out` 只捕获 `httpx.TimeoutException`/`httpx.HTTPError` ⇒
    curl_cffi 的超时/网络异常会**裸穿**成无分类异常（实盘两条 21.3s 流式请求：
    `status=failed`、`errors=[]`、`error_summary` 空、`ttft_ms=null`、不换号）。
    包装层必须把两套异常统一成 httpx 等价类型，让调度器的分类/重试/换号照常工作。"""
    pytest.importorskip("curl_cffi")
    import httpx
    from curl_cffi.requests import exceptions as cex
    from model_gateway.upstream.zcode.auth import _translate_curl_error

    # 超时族 → httpx.ReadTimeout（TimeoutException + HTTPError 双命中 ⇒ RETRYABLE）
    for exc in (cex.ReadTimeout("read"), cex.ConnectTimeout("connect"),
                cex.Timeout("timeout")):
        out = _translate_curl_error(exc)
        assert isinstance(out, httpx.TimeoutException), (type(exc).__name__, type(out).__name__)
        assert isinstance(out, httpx.HTTPError)

    # 网络族 → httpx.TransportError（HTTPError ⇒ 适配器捕获得到）
    for exc in (cex.ConnectionError("reset"), cex.RequestException("generic")):
        assert isinstance(_translate_curl_error(exc), httpx.HTTPError), type(exc).__name__

    # 非 curl 异常原样透传（不吞业务异常）
    plain = ValueError("x")
    assert _translate_curl_error(plain) is plain


# ============ 自有信封业务码分类（2026-10-08） ============

async def test_envelope_business_codes_map_to_official_classes():
    """**2026-10-08 实盘缺陷的回归判据**：ZCode 用 `200 + 自有信封` 表达业务错误，
    基类原先对**所有**这类信封一律 `status_code=None` ⇒ `RETRYABLE` ⇒ `1005`
    （额度耗尽）被当成"网络抖动"：短冷却 + 计 C，同一条额度尽的号被反复打
    （实盘一轮换号连撞 6 个号各 2 次）。正确动作是**长冷却**（官方
    `providerBusinessError.ts` 明写 `1005 → refresh-quota`；DSH `trae-credits.ts:65`
    同码 → 43200s）。

    判据 = 官方归因表（`chatErrorAttributionEvidence.ts:20-57`）逐码落到正确类别。"""
    from model_gateway.core.errors import ErrorClass, ErrorClassifier
    from model_gateway.upstream.zcode.out import ZcodeOut

    inst = object.__new__(ZcodeOut)      # 只验信封分类链，不跑 __init__
    clf = ErrorClassifier()

    def cls_of(code: int):
        return clf.classify(inst._shape_error(200, "application/json",
                                              '{"code":%d,"msg":"x"}' % code))

    # 额度族 → QUOTA（长冷却，不再当网络抖动）
    for code in (1005, 1304, 1310, 1313, 3002, 3008, 3009, 3010):
        assert cls_of(code) is ErrorClass.QUOTA, f"{code} 应归 QUOTA"
    # 凭据族 → AUTH（既有语义：停用该资源）
    assert cls_of(1006) is ErrorClass.AUTH
    assert cls_of(3007) is ErrorClass.AUTH
    # 模型族 → NOT_FOUND
    assert cls_of(1211) is ErrorClass.NOT_FOUND
    assert cls_of(3006) is ErrorClass.NOT_FOUND
    # 套餐族 → RESOURCE_UNAVAILABLE（换号续跑，不 disable、不计 C）
    assert cls_of(1309) is ErrorClass.RESOURCE_UNAVAILABLE
    assert cls_of(1311) is ErrorClass.RESOURCE_UNAVAILABLE
    # 服务端/网络族 → RETRYABLE
    assert cls_of(1120) is ErrorClass.RETRYABLE
    assert cls_of(2007) is ErrorClass.RETRYABLE
    # 请求族 → BAD_REQUEST（原样透传）
    assert cls_of(3001) is ErrorClass.BAD_REQUEST
    assert cls_of(1261) is ErrorClass.BAD_REQUEST

    # 🔴 认不出的码保持既有兜底（不猜、不改语义）
    assert cls_of(9999) is ErrorClass.RETRYABLE

    # 🔴 3012（风控）**不从这条腿走** —— 它有自己的通道处置（risk_control 标记）
    e3012 = inst._shape_error(200, "application/json", '{"code":3012,"msg":"unusual activity"}')
    assert clf.classify(e3012) is ErrorClass.RETRYABLE
    assert e3012.error_class is None, "3012 不得被信封翻译接管"

    # 非信封形状（无 code）⇒ 不设类别，走既有兜底
    e_plain = inst._shape_error(200, "application/json", '{"foo":"bar"}')
    assert e_plain.error_class is None
    assert clf.classify(e_plain) is ErrorClass.RETRYABLE


async def test_envelope_class_respects_error_rules_override():
    """用户的 `error_rules` 覆写**永远优先于**出站层判断（铁律 4）。

    出站层给出 `1005 → QUOTA`，但配置把它覆写成 BAD_REQUEST ⇒ 必须听配置的。"""
    from model_gateway.core.errors import ErrorClass, ErrorClassifier, UpstreamError
    from model_gateway.upstream.zcode.out import ZcodeOut

    inst = object.__new__(ZcodeOut)

    class _Rule:                       # ErrorRule 同形（http/type/error_class）
        # 🔴 `http=0` = 「无 HTTP 状态码」哨兵：信封类错误的 `status_code=None`
        #    必须能被用户配置覆写（否则"配置覆写一切"这条红线对这类错误结构性失效）。
        http = 0
        type = ""
        error_class = ErrorClass.BAD_REQUEST

    clf = ErrorClassifier([_Rule()])
    e = inst._shape_error(200, "application/json", '{"code":1005,"msg":"exceed quota limit"}')
    assert clf.classify(e) is ErrorClass.BAD_REQUEST, "配置覆写必须赢过出站层判断"
    # 对照：无规则时按出站层判断
    assert ErrorClassifier().classify(e) is ErrorClass.QUOTA
    # 对照：`http=0` 规则**不得**接管有真实状态码的错误（如 429）
    e429 = UpstreamError("upstream 429", status_code=429, error_body="{}")
    assert clf.classify(e429) is ErrorClass.QUOTA, "哨兵规则不许越界接管真实状态码"
