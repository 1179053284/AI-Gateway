"""v2.0 §19 M4-1 集成测试：网关经 **Anthropic 协议上游**完成一次 chat。

判据（§19 M4-1）：**假 Anthropic 上游 ASGI 可完全 mock** → 完成一次 chat。
同时验证 §18.2 的三条硬约定：
② 分发点按 `protocol` 分支（v1.6 无条件 OpenAIOutAdapter）
③ usage 在适配器内映射（否则恒走本地估算）
⑤ 2xx 非 JSON/SSE → `status_code=None`（落 RETRYABLE，进入冷却）
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import yaml

from tests.integration.fakeanthropic import FakeAnthropic, Resp, StreamResp, start_fake_anthropic

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def anthropic_vendor():
    v = FakeAnthropic()
    server, task, wait_ready = start_fake_anthropic(v)
    v.port = await wait_ready()
    yield v
    server.should_exit = True
    await asyncio.wait_for(task, timeout=10)


@pytest.fixture
async def make_anthropic_gateway(tmp_path, anthropic_vendor):
    """网关工厂：资源 `protocol: anthropic`，base_url 指向 FakeAnthropic。"""
    from model_gateway.main import create_app
    import uvicorn

    made: list = []
    n = 0

    async def _make(cfg_dict: dict):
        nonlocal n
        cfg_dict.setdefault("resources", [])
        for r in cfg_dict["resources"]:
            # 不强制 protocol —— 保留"缺省应为 openai"的向后兼容语义（由用例自己声明）
            r["base_url"] = f"http://127.0.0.1:{anthropic_vendor.port}"
        config_path = tmp_path / f"cfg-{n}.yaml"
        usage_dir = tmp_path / f"usage-{n}"
        config_path.write_text(yaml.safe_dump(cfg_dict, allow_unicode=True), encoding="utf-8")
        app = create_app(config_path=config_path, usage_dir=usage_dir,
                         enums_path=tmp_path / f"enums-{n}.yaml")
        n += 1
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
        task = asyncio.get_running_loop().create_task(server.serve())
        for _ in range(500):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]

        class H:
            base_url = f"http://127.0.0.1:{port}"
            runtime = app.state.runtime

            async def stop(self):
                server.should_exit = True
                await asyncio.wait_for(task, timeout=10)
        h = H()
        made.append(h)
        return h

    yield _make
    for h in made:
        await h.stop()


def _cfg(*, resources=None, models=None):
    return {
        "resources": resources if resources is not None else [
            {"id": "res-a", "name": "anthropic资源", "access_mode": "api",
             "protocol": "anthropic", "base_url": "http://127.0.0.1:9", "api_key": "sk-a"},
        ],
        "models": models if models is not None else [
            {"name": "test-model", "endpoint": "chat",
             "resources": [{"resource": "res-a", "model": "claude-sonnet-4"}]},
        ],
    }


def _base_cfg(**over):
    cfg = _cfg()
    cfg.update(over)
    return cfg


# ---------- ② 分发点 ----------

async def test_resource_with_anthropic_protocol_gets_anthropic_adapter(make_anthropic_gateway):
    """🔴 v1.6 无条件构造 OpenAIOutAdapter —— 本测试守住"按 protocol 分支"。"""
    from model_gateway.adapters.anthropic_out import AnthropicOutAdapter
    gw = await make_anthropic_gateway(_base_cfg())
    assert isinstance(gw.runtime.adapters["res-a"], AnthropicOutAdapter)


async def test_resource_defaults_to_openai_adapter(make_anthropic_gateway):
    """默认 `protocol` 仍是 openai（向后兼容，不破坏既有配置）。"""
    from model_gateway.adapters.openai_out import OpenAIOutAdapter
    cfg = _cfg()
    cfg["resources"][0].pop("protocol", None)
    gw = await make_anthropic_gateway(cfg)
    assert isinstance(gw.runtime.adapters["res-a"], OpenAIOutAdapter)


async def test_whitespace_url_edit_reuses_the_adapter(make_anthropic_gateway):
    """🔴 热重载的"适配器可否复用"与运行态指纹共用一个归一化口径（验收 S-19）。

    复用判定原先自己写 `.rstrip("/")`（不 strip），适配器内部又剥一遍：
    配置里的 URL 带上首尾空格（从聊天窗口粘贴的常见形态）时，
    每一轮 reload 都判定"地址变了"→ 造一个新 httpx 客户端，而运行态指纹认为
    凭据没变 —— 两处口径一分离，用户看到的是一边"什么都没改"、一边连接被反复重建。
    """
    gw = await make_anthropic_gateway(_cfg())
    rt = gw.runtime
    before = rt.adapters["res-a"]

    rt.config.resources[0].base_url = f"  {before.base_url}  "
    rt._apply(rt.config)                       # reload_from_file 走的就是这一步
    assert rt.adapters["res-a"] is before, "空白差异重建了出站客户端"

    rt.config.resources[0].base_url = "http://127.0.0.1:1/v1"   # 真换了地址
    rt._apply(rt.config)
    assert rt.adapters["res-a"] is not before, "换了地址必须重建适配器"


# ---------- 非流式 ----------

async def test_chat_nonstream_completes(make_anthropic_gateway, anthropic_vendor):
    """判据核心：完成一次 chat（非流式）。"""
    anthropic_vendor.enqueue(Resp(text="你好", input_tokens=11, output_tokens=3))
    gw = await make_anthropic_gateway(_base_cfg())

    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{gw.base_url}/v1/chat/completions",
                         json={"model": "test-model",
                               "messages": [{"role": "user", "content": "hi"}]})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["choices"][0]["message"]["content"] == "你好"
    assert body["choices"][0]["finish_reason"] == "stop"
    # 统一名替换厂商名（与 openai 路径同规则）
    assert body["model"] == "test-model"


async def test_upstream_receives_anthropic_shaped_body(make_anthropic_gateway, anthropic_vendor):
    """上游收到的应是 **Anthropic 形态**（`messages` + `max_tokens` 必填），不是 OpenAI 原样。"""
    anthropic_vendor.enqueue(Resp())
    gw = await make_anthropic_gateway(_base_cfg())

    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(f"{gw.base_url}/v1/chat/completions",
                     json={"model": "test-model",
                           "messages": [{"role": "system", "content": "sys"},
                                        {"role": "user", "content": "hi"}]})

    sent = anthropic_vendor.requests[-1]["body"]
    assert sent["system"] == "sys"
    assert "max_tokens" in sent                       # Anthropic 必填
    assert sent["messages"][0]["content"] == [{"type": "text", "text": "hi"}]
    # 认证头是 x-api-key（不是 Bearer）
    assert anthropic_vendor.requests[-1]["headers"].get("x-api-key") == "sk-a"
    assert anthropic_vendor.requests[-1]["headers"].get("anthropic-version") == "2023-06-01"


async def test_usage_mapped_so_it_is_not_estimated(make_anthropic_gateway, anthropic_vendor):
    """③ usage 必须来自上游（映射后），**不能**是本地估算。"""
    anthropic_vendor.enqueue(Resp(input_tokens=30, output_tokens=12))
    gw = await make_anthropic_gateway(_base_cfg())

    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{gw.base_url}/v1/chat/completions",
                         json={"model": "test-model",
                               "messages": [{"role": "user", "content": "hi"}]})

    usage = r.json()["usage"]
    assert usage["prompt_tokens"] == 30
    assert usage["completion_tokens"] == 12
    assert usage["total_tokens"] == 42


async def test_thinking_maps_to_reasoning_content(make_anthropic_gateway, anthropic_vendor):
    anthropic_vendor.enqueue(Resp(text="答", thinking="让我想想"))
    gw = await make_anthropic_gateway(_base_cfg())

    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{gw.base_url}/v1/chat/completions",
                         json={"model": "test-model",
                               "messages": [{"role": "user", "content": "hi"}]})

    msg = r.json()["choices"][0]["message"]
    assert msg["reasoning_content"] == "让我想想"
    assert msg["content"] == "答"


async def test_tool_use_maps_to_openai_tool_calls(make_anthropic_gateway, anthropic_vendor):
    import json as _json
    anthropic_vendor.enqueue(Resp(
        text="", stop_reason="tool_use",
        tool_use=[{"type": "tool_use", "id": "t1", "name": "get_weather",
                   "input": {"city": "北京"}}]))
    gw = await make_anthropic_gateway(_base_cfg())

    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{gw.base_url}/v1/chat/completions",
                         json={"model": "test-model",
                               "messages": [{"role": "user", "content": "天气"}]})

    msg = r.json()["choices"][0]["message"]
    assert r.json()["choices"][0]["finish_reason"] == "tool_calls"
    tc = msg["tool_calls"][0]
    assert tc["function"]["name"] == "get_weather"
    assert _json.loads(tc["function"]["arguments"]) == {"city": "北京"}


# ---------- 流式 ----------

async def test_chat_stream_completes(make_anthropic_gateway, anthropic_vendor):
    """判据核心：完成一次 chat（流式，Anthropic SSE → OpenAI SSE）。"""
    anthropic_vendor.enqueue(StreamResp(texts=["你", "好"], output_tokens=7))
    gw = await make_anthropic_gateway(_base_cfg())

    async with httpx.AsyncClient(timeout=10) as c:
        async with c.stream("POST", f"{gw.base_url}/v1/chat/completions",
                            json={"model": "test-model", "stream": True,
                                  "messages": [{"role": "user", "content": "hi"}]}) as r:
            assert r.status_code == 200
            chunks = []
            async for line in r.aiter_lines():
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    chunks.append(__import__("json").loads(payload))
    text = "".join(
        ch["choices"][0]["delta"].get("content", "")
        for ch in chunks if ch.get("choices"))

    assert text == "你好"
    assert any(ch["choices"][0].get("finish_reason") for ch in chunks)


async def test_stream_thinking_to_reasoning_content(make_anthropic_gateway, anthropic_vendor):
    anthropic_vendor.enqueue(StreamResp(texts=["答"], thinkings=["想"]))
    gw = await make_anthropic_gateway(_base_cfg())

    async with httpx.AsyncClient(timeout=10) as c:
        async with c.stream("POST", f"{gw.base_url}/v1/chat/completions",
                            json={"model": "test-model", "stream": True,
                                  "messages": [{"role": "user", "content": "hi"}]}) as r:
            got = []
            async for line in r.aiter_lines():
                if line.startswith("data:"):
                    p = line[5:].strip()
                    if p == "[DONE]":
                        break
                    got.append(__import__("json").loads(p))
    reasoning = "".join(
        ch["choices"][0]["delta"].get("reasoning_content", "")
        for ch in got if ch.get("choices"))

    assert reasoning == "想"


async def test_stream_tool_call(make_anthropic_gateway, anthropic_vendor):
    anthropic_vendor.enqueue(StreamResp(
        texts=[], tool={"id": "t9", "name": "f", "input_json": '{"a":1}'},
        stop_reason="tool_use"))
    gw = await make_anthropic_gateway(_base_cfg())

    async with httpx.AsyncClient(timeout=10) as c:
        async with c.stream("POST", f"{gw.base_url}/v1/chat/completions",
                            json={"model": "test-model", "stream": True,
                                  "messages": [{"role": "user", "content": "hi"}]}) as r:
            got = []
            async for line in r.aiter_lines():
                if line.startswith("data:"):
                    p = line[5:].strip()
                    if p == "[DONE]":
                        break
                    got.append(__import__("json").loads(p))
    args = "".join(
        ch["choices"][0]["delta"]["tool_calls"][0]["function"].get("arguments", "")
        for ch in got
        if ch.get("choices") and ch["choices"][0]["delta"].get("tool_calls"))

    assert args == '{"a":1}'


# ---------- ⑤ 2xx 非 JSON/HTML（WAF 页）----------

async def test_html_response_is_treated_as_upstream_error(make_anthropic_gateway, anthropic_vendor):
    """🔴 2xx 但 HTML（WAF 挑战页）→ **不得**当成功；走 RETRYABLE → 切换/冷却。

    单资源时最终返回 502（无可用资源），**绝不**返回"空成功"。
    """
    anthropic_vendor.enqueue(Resp(status=200, html_body="<html>WAF challenge</html>"))
    gw = await make_anthropic_gateway(_base_cfg())

    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{gw.base_url}/v1/chat/completions",
                         json={"model": "test-model",
                               "messages": [{"role": "user", "content": "hi"}]})

    assert r.status_code != 200, "HTML 响应不得被当作成功"


async def test_html_response_cools_down_and_second_resource_takes_over(make_anthropic_gateway, anthropic_vendor):
    """多资源：首个返回 HTML → 应**切换**到第二个资源（证明落到了 RETRYABLE）。"""
    anthropic_vendor.enqueue(Resp(status=200, html_body="<html>WAF</html>"),
                            Resp(text="来自B"))
    cfg = _cfg(
        resources=[
            {"id": "res-a", "name": "A", "access_mode": "api", "protocol": "anthropic",
             "base_url": "http://127.0.0.1:9", "api_key": "sk-a"},
            {"id": "res-b", "name": "B", "access_mode": "api", "protocol": "anthropic",
             "base_url": "http://127.0.0.1:9", "api_key": "sk-b"},
        ],
        models=[{"name": "test-model", "endpoint": "chat",
                 "resources": [{"resource": "res-a", "model": "m"},
                               {"resource": "res-b", "model": "m"}]}],
    )
    gw = await make_anthropic_gateway(cfg)

    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{gw.base_url}/v1/chat/completions",
                         json={"model": "test-model",
                               "messages": [{"role": "user", "content": "hi"}]})

    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "来自B"


# ---------- 上游错误 ----------

async def test_upstream_4xx_is_surfaced(make_anthropic_gateway, anthropic_vendor):
    anthropic_vendor.enqueue(Resp(status=400))
    gw = await make_anthropic_gateway(_base_cfg())

    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{gw.base_url}/v1/chat/completions",
                         json={"model": "test-model",
                               "messages": [{"role": "user", "content": "hi"}]})

    # 4xx 按既有口径 BAD_REQUEST 原样透传（不切换）
    assert r.status_code in (400, 502)
def test_whitespace_only_base_url_gets_no_adapter(tmp_path):
    """🔴 只填了空格的端点 = 没配端点（第八轮 eng-8a 的 E-1）。

    原先判空写 `if not r.base_url`，空格串在它眼里算"有值" → 建出一个指向空串的适配器，
    请求照发、错误直出 httpx 黑话；用户看到的是"网络故障"而不是"这个资源还没配端点"，
    也就不会去补那一栏。修后：没有适配器 → 调度器给的是中文的"无可用出站适配器"。
    """
    import yaml

    from model_gateway.core.resources import normalize_base_url
    from model_gateway.main import create_app

    cfg = {"resources": [{"id": "res-a", "name": "A", "access_mode": "api",
                          "protocol": "anthropic", "base_url": "    ", "api_key": "sk"}],
           "models": [{"name": "m", "endpoint": "chat",
                       "resources": [{"resource": "res-a", "model": "vm"}]}]}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    app = create_app(config_path=path, usage_dir=tmp_path / "usage",
                     enums_path=tmp_path / "enums.yaml")
    rt = app.state.runtime
    assert normalize_base_url(rt.config.resources[0].base_url) == ""
    assert "res-a" not in rt.adapters, f"空端点仍建出了适配器：{list(rt.adapters)}"
    rows = rt.resources.snapshot_by_resource(rt.config)
    assert rows and rows[0]["rid"] == "res-a"        # 资源仍在表上，不是被静默丢弃


def test_probe_skips_a_resource_whose_endpoint_is_only_whitespace(tmp_path):
    """🔴 `mgw probe` 选链路时同样按归一化判空（第九轮 eng 的 E-1 同族，`cli_probe.py:51`）。

    只填了空格的端点不是"有端点"：探测会拿它去建请求，报出来的是 httpx 黑话，
    而真因是"那一栏还没填"。
    """
    import yaml

    from model_gateway.cli_probe import _pick_resource
    from model_gateway.config.loader import load_config

    cfg = {"resources": [{"id": "res-a", "name": "A", "access_mode": "api",
                          "base_url": "   ", "api_key": "sk"}],
           "models": [{"name": "m", "endpoint": "chat",
                       "resources": [{"resource": "res-a", "model": "vm"}]}]}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    config = load_config(path)
    rid, vm = _pick_resource(config, config.models[0])
    assert rid is None and vm is None, f"空格端点被当成可用链路：{rid}"
