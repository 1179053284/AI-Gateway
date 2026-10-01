"""trae 出站**端到端**（§22.3/§22.4/§22.5；M6-5c）。

判据 = 「账号 → 资源 → `/v1/chat/completions`」全链路在**假 SOLO 上游**上跑通：

· 非流式 / 流式各一条：SOLO 自定义 SSE（跨行 `event:`+`data:`）→ OpenAI chunk；
· 假上游收到的**路径**（`/api/agent/v3/llm_utils_chat`，`trae.ts:44`）、**头**
  （`Cloud-IDE-JWT` / `X-Cloudide-Token` / `X-Ide-Token` 三处同值 + `X-Uid`，`trae.ts:210-228`）
  与**请求体**形态（`stream:true` 强制 / `config_name`+`model` 双字段 / `messages.content`
  数组化 / `tools.parameters` 序列化，`trae.ts:1529-1560`）逐项断言；
· **通道映射取产品目录**（`function` = `models.channel_for`，数据面 `trae-adapter.ts:656-661`）——
  本文件用目录解析结果（`protocol.parse_batch_models`）喂映射，**不重写一份表**；
· 流内 `event:error` 保留业务码：1005/4008/4011 → 429（§22.5-5 冷却）；4001 → 可读提示；
· 空响应（HTTP 200 却零事件）→ 可重试失败，**不谎报空回复**（`trae-adapter.ts:1546-1559`）；
· 配置里的 `api_key` **绝不出现**在出站头里（铁律 1）＋ 缺凭据 fail closed + 零次上游请求。
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route

from model_gateway.accounts import store
from model_gateway.upstream.trae import models as trae_models
from model_gateway.upstream.trae import protocol as trae_protocol

CONFIG_KEY = "sk-config-key-must-not-be-sent"
TOKEN = "TRAE-TOKEN-FROM-ACCOUNT"
UID = "4056564292660009"


def _solo_stream(frames: list[tuple[str, str]]) -> list[str]:
    """SOLO SSE 文本行（`event:` 与 `data:` 成帧；空行分隔）。"""
    out: list[str] = []
    for event, data in frames:
        out.append(f"event:{event}\n")
        out.append(f"data:{data}\n")
        out.append("\n")
    return out


class _FakeSoloUpstream:
    """假 TRAE SOLO 上游：`POST /api/agent/v3/llm_utils_chat`。

    `script` 为可编程帧序列；默认 = 文本「你」「好」+ usage + done。
    """

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.frames: list[tuple[str, str]] | None = None
        self.raw_lines: list[str] | None = None
        self.app = Starlette(routes=[
            Route("/api/agent/v3/llm_utils_chat", self._chat, methods=["POST"])])

    async def _chat(self, request: Request):
        body = await request.json()
        self.requests.append({"path": request.url.path,
                              "headers": dict(request.headers), "body": body})
        lines = self.raw_lines
        if lines is None:
            frames = self.frames if self.frames is not None else [
                ("output", json.dumps({"response": "你", "reasoning_content": "想"},
                                      ensure_ascii=False)),
                ("output", json.dumps({"response": "好"}, ensure_ascii=False)),
                ("token_usage", json.dumps({"prompt_tokens": 21, "completion_tokens": 142})),
                ("done", json.dumps({"finish_reason": "stop"})),
            ]
            lines = _solo_stream(frames)

        async def gen():
            for line in lines:
                yield line

        return StreamingResponse(gen(), media_type="text/event-stream")


@pytest.fixture
async def solo_upstream():
    # 🔴 通道缓存是**进程级**（`models._CHANNELS`）且会被**其它测试文件**经生产路径
    # （`fetch_models` → `remember_channels`）填充：`tests/accounts/test_trae.py:604` 的目录
    # 用例把 glm-5.2 按规则③记为 `solo_agent_remote`。只在 teardown 清会让**首个**用例
    # 继承"热缓存"，令冷缓存回退断言（`const.FUNCTION` = solo_work_lite）失真 ——
    # 故进用例前也清一次（本文件单独跑恒绿，连跑才暴露，是测试隔离缺陷而非产品缺陷）。
    trae_models.reset_channels_for_tests()
    fake = _FakeSoloUpstream()
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
        trae_models.reset_channels_for_tests()       # 用例间不留痕（通道缓存是进程级）


def _cfg(port: int, *, account: str = "tr-1", model_name: str = "trae-model",
         vendor_model: str = "glm-5.2", scheduling: dict | None = None) -> dict:
    return {
        "resources": [{
            "id": "res-trae", "name": "Trae 资源", "vendor": "", "preset": "",
            "account": account, "product": "trae", "account_ref": account,
            "protocol": "openai", "base_url": f"http://127.0.0.1:{port}",
            "api_key": CONFIG_KEY,       # 故意留着：出站必须**不用**它（铁律 1）
            "enabled": True, "access_mode": "api",
        }],
        "models": [{"name": model_name, "endpoint": "chat",
                    "resources": [{"resource": "res-trae", "model": vendor_model}]}],
        **({"scheduling": scheduling} if scheduling else {}),
    }


def _body(model: str = "trae-model", **over) -> dict:
    data = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    data.update(over)
    return data


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


def _cred() -> dict:
    return {"access_token": TOKEN, "refresh_token": "RT", "uid": UID,
            "machine_id": "m" * 32, "login_device_id": "d" * 32}


# ============ 非流式 ============

async def test_trae_nonstream_end_to_end(solo_upstream, make_gateway, client):
    store.commit_login("trae", "tr-1", _cred(), {})
    gw = await make_gateway(_cfg(solo_upstream.port))

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "你好"        # SOLO output 聚合
    assert data["choices"][0]["message"]["reasoning_content"] == "想"
    assert data["model"] == "trae-model"                            # 统一名替换厂商名
    assert data["choices"][0]["finish_reason"] == "stop"

    assert len(solo_upstream.requests) == 1
    req = solo_upstream.requests[0]
    assert req["path"] == "/api/agent/v3/llm_utils_chat"            # trae.ts:44
    assert req["headers"]["authorization"] == f"Cloud-IDE-JWT {TOKEN}"
    assert req["headers"]["x-cloudide-token"] == TOKEN              # 三处同值（trae.ts:196-198）
    assert req["headers"]["x-ide-token"] == TOKEN
    assert req["headers"]["x-uid"] == UID
    assert req["headers"]["x-app-id"] == "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8"
    assert req["headers"]["x-machine-id"] == "m" * 32               # 设备头取凭据
    assert req["headers"]["x-device-id"] == "d" * 32
    assert CONFIG_KEY not in json.dumps(req["headers"])             # 配置 Key 绝不外发（铁律 1）
    assert req["body"]["stream"] is True                            # SOLO 强制流式
    assert req["body"]["model"] == "glm-5.2" and req["body"]["config_name"] == "glm-5.2"
    assert req["body"]["function"] == "solo_work_lite"              # 默认通道（trae.ts:1447）
    assert req["body"]["messages"][0]["content"] == [{"type": "text", "text": "hi"}]

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == "Trae 资源/glm-5.2"
    assert ev["input_tokens"] == 21 and ev["output_tokens"] == 142  # SOLO token_usage 直通


async def test_trae_solo_body_shapes(solo_upstream, make_gateway, client):
    """工具与多步历史的 SOLO 塑形（`trae.ts:1566-1693` 的五条改写规则）。"""
    store.commit_login("trae", "tr-1", _cred(), {})
    gw = await make_gateway(_cfg(solo_upstream.port))

    body = _body(tools=[{"type": "function", "function": {
        "name": "read_file", "description": "读文件",
        "parameters": {"type": "object", "properties": {"p": {"type": "string"}}}}}])
    body["messages"] = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
    ]
    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=body)
    assert resp.status_code == 200, resp.text

    wire = solo_upstream.requests[-1]["body"]
    # assistant 的 tool_calls 字段名改为 SOLO 的 function_call
    assistant = wire["messages"][1]
    assert assistant["tool_calls"][0]["function_call"]["name"] == "read_file"
    assert "function" not in assistant["tool_calls"][0]
    # tools[].function.parameters object → JSON 字符串（SOLO 要求）
    params = wire["tools"][0]["function"]["parameters"]
    assert isinstance(params, str) and json.loads(params)["type"] == "object"


# ============ 流式（跨行成帧）============

async def test_trae_stream_end_to_end_with_split_data_line(solo_upstream, make_gateway, client):
    """流式 + **成帧边界**：`data:` 跨行拼接（`trae-adapter.ts:1520` 的消费口径）。"""
    store.commit_login("trae", "tr-1", _cred(), {})
    gw = await make_gateway(_cfg(solo_upstream.port))

    # 把第二条 output 的 JSON 拆成两行 data（跨行累积 + 空行才成帧）
    first = json.dumps({"response": "你"}, ensure_ascii=False)
    whole = json.dumps({"response": "好"}, ensure_ascii=False)
    cut = len(whole) // 2
    solo_upstream.raw_lines = [
        "event:output\n", f"data:{first}\n", "\n",
        "event:output\n", f"data:{whole[:cut]}\n", f"data:{whole[cut:]}\n", "\n",
        "event:done\n", 'data:{"finish_reason":"stop"}\n', "\n",
    ]

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body(stream=True))
    assert resp.status_code == 200, resp.text
    assert "text/event-stream" in resp.headers["content-type"]
    frames = _sse_frames(resp.text)
    text = "".join(f["choices"][0]["delta"].get("content", "")
                   for f in frames if f.get("choices"))
    assert text == "你好"
    assert {f["model"] for f in frames if f.get("model")} == {"trae-model"}

    await gw.drain_events()
    ev = gw.read_events()[-1]
    assert ev["status"] == "success" and ev["final_resource"] == "Trae 资源/glm-5.2"


# ============ 通道映射（产品目录 = 单一来源）============

async def test_trae_channel_mapping_comes_from_catalog(solo_upstream, make_gateway, client):
    """`function` 必须取该模型所属通道（`channelFor`，`trae-adapter.ts:650-661`）。

    映射数据面 = 产品目录解析结果（`protocol.parse_batch_models` → `models.remember_channels`），
    本文件**不写任何通道表**。校验用一条**目录声称在 `solo_agent_remote`** 的模型：
    发错通道上游会回流内 4001（`trae-adapter.ts:653-655`），故这里必须断言发对。
    """
    store.commit_login("trae", "tr-1", _cred(), {})
    gw = await make_gateway(_cfg(solo_upstream.port, vendor_model="glm-5.1"))

    catalog = {"function_configs": [{"function": "solo_agent_remote", "config_info_list": [
        {"config_name": "glm-5.1", "display_config": {"multimodal": False}},
    ]}]}
    trae_models.remember_channels(trae_protocol.parse_batch_models(catalog))
    assert trae_models.channel_for("glm-5.1") == "solo_agent_remote"
    assert trae_models.channel_for("不在目录里的模型") == "solo_work_lite"   # 回退默认通道

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body("trae-model"))
    assert resp.status_code == 200, resp.text
    assert solo_upstream.requests[-1]["body"]["function"] == "solo_agent_remote"


# ============ 流内错误（业务码保留）============

async def test_trae_stream_quota_error_maps_to_429(solo_upstream, make_gateway, client):
    """流内 `event:error` 1005（plan 额度）→ 429（QUOTA → 冷却；`trae-adapter.ts:1497-1505`）。"""
    store.commit_login("trae", "tr-1", _cred(), {})
    gw = await make_gateway(_cfg(solo_upstream.port, scheduling={"quota_retry": 0}))
    solo_upstream.frames = [
        ("error", json.dumps({"code": 1005, "message": "plan limit"})),
    ]

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 429, resp.text
    assert len(solo_upstream.requests) == 1                 # QUOTA 不重试（bench 后无资源可切）

    await gw.drain_events()
    assert gw.read_events()[-1]["status"] == "failed"


async def test_trae_model_not_callable_4001_gives_actionable_hint(solo_upstream, make_gateway, client):
    """4001（模型仅可见不可调用）→ 可读提示（`hint` 增量字段），**不换号重试**。

    证据：`trae-adapter.ts:533-538,1502`。提示进 `error_body.hint` 是**刻意的**——
    `error_summary` 只截 `error_body`，提示若只放异常 message 用户看不到（本轮实测）。
    """
    store.commit_login("trae", "tr-1", _cred(), {})
    gw = await make_gateway(_cfg(solo_upstream.port, scheduling={"retry_per_request": 0}))
    solo_upstream.frames = [("error", json.dumps({"code": 4001, "message": "param is invalid"}))]

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 503, resp.text
    assert "不被上游接受" in resp.text, resp.text
    assert "4001" in resp.text and "param is invalid" in resp.text  # 原始码/文案保真


async def test_trae_empty_stream_is_a_retryable_failure(solo_upstream, make_gateway, client):
    """HTTP 200 却零事件 → **可重试失败**（`trae-adapter.ts:1546-1559`），绝不谎报空回复。"""
    store.commit_login("trae", "tr-1", _cred(), {})
    gw = await make_gateway(_cfg(solo_upstream.port, scheduling={"retry_per_request": 0}))
    solo_upstream.frames = []

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 503, resp.text
    assert len(solo_upstream.requests) >= 1

    await gw.drain_events()
    assert gw.read_events()[-1]["status"] == "failed"


# ============ fail closed ============

async def test_trae_missing_credential_fails_closed_without_upstream_call(
        solo_upstream, make_gateway, client):
    """账号没登录（凭据文件缺失）→ 可读失败 + **零次上游请求**（不拿空令牌打上游）。"""
    gw = await make_gateway(_cfg(solo_upstream.port))      # 刻意不 commit_login

    resp = await client.post(f"{gw.base_url}/v1/chat/completions", json=_body())
    assert resp.status_code == 503, resp.text
    assert "无凭据" in json.dumps(resp.json(), ensure_ascii=False)
    assert solo_upstream.requests == []
