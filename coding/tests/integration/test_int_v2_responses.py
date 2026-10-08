"""INT `/v1/responses` 兼容面端到端（FakeVendor 假上游，真调度链）。

覆盖目标 —— 这个端点是**翻译层**，所以判据分两组：

**A. 协议形状**（客户端能不能用）
- INT-121 非流式：`output[]` item 形状 / usage 官方口径 / `model` = 网关模型名
- INT-122 流式：SSE 事件生命周期（created→item/part/delta→done→completed）、
  `sequence_number` 连续、**无 `[DONE]`**、出站体带 `stream:true`
- INT-123 工具：`function_call` item 的 `call_id`/`arguments`，namespace 摊平后在响应侧**还原**
- INT-124 `GET /v1/responses/{id}` → 404（无状态，附可操作说明）

**B. 复用既有链路**（不许另起一条管线）
- INT-125 模型解析：未定义 404 `model_not_found`、禁用 404 `model_disabled`、images 模型 400
- INT-126 401 故障切换：A 401 → 禁 A 切 B，客户端拿到 200（切换链对 Responses 入站同样生效）
- INT-127 语义做不到的参数 **400 且不触达上游**（`previous_response_id`）
- INT-128 丢弃工具如实上报（响应头 `X-GW-Dropped-Tools`），**请求仍然成功**（绝不 400）
- INT-129 首字节前失败 = 非 200 JSON（延迟提交语义）；中途失败 = `response.failed` 收尾
- INT-130 流式断连 → 上游取消透传、`aborted`、C=0、不切换（同 INT-08/INT-28 语义）
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from tests.integration.conftest import chat_res, gateway_config
from tests.integration.fakevendor import Err, Ok, StreamOk

RESPONSES_URL = "/v1/responses"


def _rbody(**over) -> dict:
    d = {"model": "test-model", "input": "hi"}
    d.update(over)
    return d


def _parse_sse(resp: httpx.Response) -> list[tuple[str, dict]]:
    """解析 Responses SSE（`event:` 名 + `data:` 单行 JSON）。"""
    out: list[tuple[str, dict]] = []
    event = None
    for line in resp.text.splitlines():
        if line.startswith("event: "):
            event = line[7:].strip()
        elif line.startswith("data: "):
            out.append((event, json.loads(line[6:])))
            event = None
    return out


class TestResponsesNonStream:
    """INT-121 / INT-123 / INT-125。"""

    async def test_text_output_and_usage(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="答案", usage_extra={
            "total_tokens": 12, "prompt_tokens_details": {"cached_tokens": 4},
            "completion_tokens_details": {"reasoning_tokens": 2}}))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{RESPONSES_URL}", json=_rbody())
        assert resp.status_code == 200
        d = resp.json()
        assert d["object"] == "response" and d["status"] == "completed"
        assert d["model"] == "test-model"          # 规范网关模型名（非厂商 model）
        assert d["store"] is False and d["previous_response_id"] is None
        assert [i["type"] for i in d["output"]] == ["message"]
        part = d["output"][0]["content"][0]
        assert part == {"type": "output_text", "text": "答案", "annotations": []}
        assert d["usage"] == {"input_tokens": 10,
                              "input_tokens_details": {"cached_tokens": 4},
                              "output_tokens": 5,
                              "output_tokens_details": {"reasoning_tokens": 2},
                              "total_tokens": 15}   # max(上游 12, 10+5)
        # 请求侧翻译真的进了出站体
        sent = vendor.bodies_for("sk-A")[0]
        assert sent["messages"] == [{"role": "user", "content": "hi"}]
        assert sent.get("stream") is not True    # 非流式请求不得带 stream:true

    async def test_instructions_and_reasoning_and_tools_translated(
            self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="ok"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{RESPONSES_URL}", json=_rbody(
            instructions="你是助手",
            temperature=0.2, max_output_tokens=64,
            reasoning={"effort": "low"},
            tools=[{"type": "function", "name": "shell",
                    "parameters": {"type": "object"}}],
            tool_choice="auto"))
        assert resp.status_code == 200
        sent = vendor.bodies_for("sk-A")[0]
        assert sent["messages"][0] == {"role": "system", "content": "你是助手"}
        assert sent["temperature"] == 0.2 and sent["max_tokens"] == 64
        assert sent["reasoning_effort"] == "low"
        assert sent["tools"][0]["function"]["name"] == "shell"
        assert sent["tool_choice"] == "auto"

    async def test_reasoning_item_and_function_call_output(self, vendor, make_gateway, client):
        """INT-123：思考 → reasoning item；工具调用 → function_call item 且还原 namespace。"""
        vendor.set("sk-A", Ok(content=None, reasoning="想一想", thinking_style="reasoning_content",
                              tool_calls=[{"id": "call_1", "name": "mcp__files____read",
                                           "arguments": '{"p":1}'}]))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{RESPONSES_URL}", json=_rbody(
            tools=[{"type": "namespace", "name": "mcp__files__", "tools": [
                {"type": "function", "name": "read", "parameters": {"type": "object"}}]}]))
        assert resp.status_code == 200
        d = resp.json()
        assert [i["type"] for i in d["output"]] == ["reasoning", "function_call"]
        fc = d["output"][1]
        assert fc["call_id"] == "call_1" and fc["name"] == "read"
        assert fc["namespace"] == "mcp__files__" and fc["arguments"] == '{"p":1}'
        assert "mcp__files____read" not in resp.text      # 扁平名绝不漏给客户端
        # 发给上游的是摊平名
        assert vendor.bodies_for("sk-A")[0]["tools"][0]["function"]["name"] == \
            "mcp__files____read"

    async def test_unknown_model_404(self, vendor, make_gateway, client):
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{RESPONSES_URL}",
                                 json=_rbody(model="no-such-model"))
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "model_not_found"

    async def test_disabled_model_404(self, vendor, make_gateway, client):
        gw = await make_gateway(gateway_config(
            vendor.port, models=[chat_res("A", enabled=False)]))
        resp = await client.post(f"{gw.base_url}{RESPONSES_URL}", json=_rbody())
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "model_disabled"

    async def test_images_model_endpoint_mismatch_400(self, vendor, make_gateway, client):
        gw = await make_gateway(gateway_config(
            vendor.port, models=[chat_res("A", endpoint="images")]))
        resp = await client.post(f"{gw.base_url}{RESPONSES_URL}", json=_rbody())
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "endpoint_mismatch"

    async def test_auth_switch(self, vendor, make_gateway, client):
        """INT-126：401 → 禁 A → 切 B 成功（Responses 入站走同一条选路/切换链）。"""
        vendor.set("sk-A", Err(status=401, err_type="authentication_error", message="bad key"))
        vendor.set("sk-B", Ok(content="B的答案"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        resp = await client.post(f"{gw.base_url}{RESPONSES_URL}", json=_rbody())
        assert resp.status_code == 200
        assert resp.json()["output"][0]["content"][0]["text"] == "B的答案"
        assert gw.resource("res-A").status == "disabled"
        switches = gw.read_switches()
        assert switches and switches[0]["reason_cls"] == "AUTH"

    async def test_retrieve_is_404(self, vendor, make_gateway, client):
        """INT-124：无状态网关不保存响应 ⇒ 一律 404（不静默装死）。"""
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.get(f"{gw.base_url}{RESPONSES_URL}/resp_abc")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "not_found"


class TestResponsesStream:
    """INT-122 / INT-129 / INT-130。"""

    async def test_stream_event_lifecycle(self, vendor, make_gateway, client):
        vendor.set("sk-A", StreamOk(chunks=["你", "好"], reasoning_chunks=["想"],
                                    thinking_style="reasoning_content"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{RESPONSES_URL}",
                                 json=_rbody(stream=True))
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        evs = _parse_sse(resp)
        names = [n for n, _ in evs]
        assert names[0] == "response.created"
        assert names[1] == "response.in_progress"
        assert names[-1] == "response.completed"
        for required in ("response.output_item.added", "response.content_part.added",
                         "response.output_text.delta", "response.output_text.done",
                         "response.content_part.done", "response.output_item.done",
                         "response.reasoning_summary_text.delta",
                         "response.reasoning_summary_text.done"):
            assert required in names, required
        assert [d["sequence_number"] for _, d in evs] == list(range(len(evs)))
        assert "[DONE]" not in resp.text          # Responses 不以 [DONE] 收尾
        completed = evs[-1][1]["response"]
        assert [i["type"] for i in completed["output"]] == ["reasoning", "message"]
        assert completed["output"][1]["content"][0]["text"] == "你好"
        assert completed["usage"]["input_tokens"] == 10
        # 出站体必须显式带 stream:true（否则供应商回非流式 → 空流）
        assert vendor.bodies_for("sk-A")[0]["stream"] is True

    async def test_stream_tool_call_and_namespace_restore(self, vendor, make_gateway, client):
        vendor.set("sk-A", StreamOk(chunks=[], tool_call_chunks=[
            {"index": 0, "id": "call_a", "name": "mcp__files____read",
             "arguments": '{"p"'},
            {"index": 0, "arguments": ':1}'}]))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{RESPONSES_URL}", json=_rbody(
            stream=True,
            tools=[{"type": "namespace", "name": "mcp__files__", "tools": [
                {"type": "function", "name": "read", "parameters": {"type": "object"}}]}]))
        assert resp.status_code == 200
        evs = _parse_sse(resp)
        names = [n for n, _ in evs]
        assert names.count("response.function_call_arguments.delta") == 2
        done = [d for n, d in evs if n == "response.function_call_arguments.done"][0]
        assert done["name"] == "read" and done["namespace"] == "mcp__files__"
        assert done["arguments"] == '{"p":1}'
        completed = evs[-1][1]["response"]
        assert completed["output"][0]["type"] == "function_call"
        assert completed["output"][0]["call_id"] == "call_a"
        assert "mcp__files____read" not in resp.text

    async def test_stream_failure_before_first_byte_is_json(self, vendor, make_gateway, client):
        """INT-129 上半：首内容事件前耗尽 ⇒ 非 200 JSON（绝不「先 200 再 error」）。"""
        vendor.set("sk-A", Err(status=500, message="boom"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{RESPONSES_URL}", json=_rbody(stream=True))
        assert resp.status_code >= 500
        assert resp.headers["content-type"].startswith("application/json")
        assert "error" in resp.json()
        assert "response.created" not in resp.text

    async def test_stream_midway_failure_ends_with_response_failed(
            self, vendor, make_gateway, client):
        """INT-129 下半：committed 之后失败 ⇒ 逐项收尾 + response.failed（不重放）。"""
        vendor.set("sk-A", StreamOk(chunks=["一", "二"],
                                    err_after=Err(status=400, message="midstream")))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{RESPONSES_URL}", json=_rbody(stream=True))
        assert resp.status_code == 200
        evs = _parse_sse(resp)
        names = [n for n, _ in evs]
        assert names[-1] == "response.failed"
        assert names.index("response.output_item.done") < names.index("response.failed")
        failed = evs[-1][1]["response"]
        assert failed["status"] == "failed" and failed["error"]["code"] == "server_error"
        assert failed["output"][0]["content"][0]["text"] == "一二"  # 部分产出如实回传
        await gw.drain_events()
        assert gw.read_events()[0]["status"] == "failed"

    async def test_stream_cancel_propagates(self, vendor, make_gateway, client):
        """INT-130：中途断连 → 上游取消、aborted、C=0、不切换（同 INT-08/INT-28）。"""
        vendor.set("sk-A", StreamOk(chunks=["一", "二", "三", "四"], delay_between=0.6))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        req = client.build_request("POST", f"{gw.base_url}{RESPONSES_URL}",
                                   json=_rbody(stream=True))
        resp = await client.send(req, stream=True)
        assert resp.status_code == 200
        received = b""
        async for chunk in resp.aiter_bytes():
            received += chunk
            if received.count(b"response.output_text.delta") >= 2:
                break
        await resp.aclose()  # 客户端断连

        for _ in range(60):
            await asyncio.sleep(0.2)
            if vendor.cancelled_keys:
                break
        assert "sk-A" in vendor.cancelled_keys
        await gw.drain_events()
        ev = gw.read_events()[0]
        assert ev["status"] == "aborted" and ev["switch_count"] == 0
        assert gw.resource("res-A").C == 0 and gw.resource("res-A").status == "active"


class TestResponsesGuards:
    """INT-127 / INT-128：做不到的语义 400 且零出站；能表达的丢弃必须如实上报。"""

    @pytest.mark.parametrize("field,value", [
        ("previous_response_id", "resp_1"), ("conversation", "conv_1"),
        ("background", True), ("store", True),
    ])
    async def test_unsupported_state_param_is_400_without_upstream(
            self, vendor, make_gateway, client, field, value):
        vendor.set("sk-A", Ok(content="不该被调用"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{RESPONSES_URL}",
                                 json=_rbody(**{field: value}))
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "unsupported_parameter"
        assert vendor.requests == []          # 零出站（不烧额度）
        await gw.drain_events()
        assert gw.read_events() == []         # 不落请求日志（没有真实调用）

    async def test_dropped_tools_reported_and_request_succeeds(
            self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="ok"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{RESPONSES_URL}", json=_rbody(
            tools=[{"type": "function", "name": "shell", "parameters": {"type": "object"}},
                   {"type": "custom", "name": "apply_patch"},
                   {"type": "web_search"}]))
        assert resp.status_code == 200       # 绝不因工具形状让整轮对话不可用
        header = resp.headers.get("X-GW-Dropped-Tools", "")
        assert "custom/apply_patch" in header and "web_search" in header
        sent = vendor.bodies_for("sk-A")[0]
        assert [t["function"]["name"] for t in sent["tools"]] == ["shell"]
