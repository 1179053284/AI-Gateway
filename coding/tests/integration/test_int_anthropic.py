"""INT Anthropic 入站 /v1/messages（INT-16 / INT-28 / INT-33）。

覆盖（真实商汤 E2E 实测暴露的两个缺口回归）：
- INT-16：非流式（content 块/stop_reason/usage 映射）+ 流式事件语义
  （块生命周期：同类 delta 连续同块、异类 stop+start、message_delta 收尾）
- 出站体必须携带 stream:true（缺失时供应商返回非流式 JSON → SSE 解析零事件 → 空流）
- INT-28：流式中途断连 → 上游取消、aborted、不计失败、不切换（同 INT-08 语义）
- INT-33：Claude Code 风格 model id 别名（claude-sonnet-4-20250514）命中网关模型
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import httpx
import pytest

from tests.integration.conftest import chat_res, gateway_config
from tests.integration.fakevendor import Err, Ok, StreamOk

MESSAGES_URL = "/v1/messages"


def _abody(stream: bool = False, model: str = "test-model", **over) -> dict:
    d = {"model": model, "max_tokens": 64, "stream": stream,
         "messages": [{"role": "user", "content": "hi"}]}
    d.update(over)
    return d


def _headers() -> dict:
    return {"x-api-key": "mg-test", "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"}


def _parse_sse(resp: httpx.Response) -> list[dict]:
    """解析 Anthropic SSE（event/data 对 → [{"event":..,"data":..}]）。"""
    out: list[dict] = []
    event = None
    for line in resp.text.splitlines():
        if line.startswith("event: "):
            event = line[7:].strip()
        elif line.startswith("data: "):
            payload = line[6:]
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {"_raw": payload}
            out.append({"event": event, "data": data})
            event = None
    return out


class TestAnthropicNonStream:
    """INT-16 非流式：content 块 / stop_reason / usage 映射。"""

    async def test_nonstream_text_and_thinking(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="答案", reasoning="思考",
                              thinking_style="thinking_content"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{MESSAGES_URL}",
                                 json=_abody(), headers=_headers())
        assert resp.status_code == 200
        d = resp.json()
        assert d["type"] == "message"
        assert d["role"] == "assistant"
        assert d["model"] == "test-model"  # 统一名（非厂商 model）
        kinds = [b["type"] for b in d["content"]]
        assert kinds == ["thinking", "text"]  # thinking 在前、text 在后
        assert d["content"][0]["thinking"] == "思考"
        assert d["content"][1]["text"] == "答案"
        assert d["stop_reason"] == "end_turn"  # stop → end_turn
        assert d["usage"] == {"input_tokens": 10, "output_tokens": 5}

    async def test_nonstream_unknown_model_404(self, vendor, make_gateway, client):
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{MESSAGES_URL}",
                                 json=_abody(model="no-such-model"), headers=_headers())
        assert resp.status_code == 404
        body = resp.json()
        assert body["type"] == "error"  # Anthropic 错误形态
        assert body["error"]["type"] == "invalid_request_error"

    async def test_nonstream_auth_switch(self, vendor, make_gateway, client):
        """A 401（AUTH）→ disable → 切 B 成功（调度链路对 Anthropic 入站同样生效）。"""
        vendor.set("sk-A", Err(status=401, err_type="authentication_error", message="bad key"))
        vendor.set("sk-B", Ok(content="B的答案"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        resp = await client.post(f"{gw.base_url}{MESSAGES_URL}",
                                 json=_abody(), headers=_headers())
        assert resp.status_code == 200
        d = resp.json()
        assert d["content"] == [{"type": "text", "text": "B的答案"}]
        assert gw.resource("res-A").status == "disabled"
        switches = gw.read_switches()
        assert switches and switches[0]["reason_cls"] == "AUTH"


class TestAnthropicStream:
    """INT-16 流式：事件语义 + 出站 stream 标志回归 + INT-28 取消。"""

    async def test_stream_event_semantics(self, vendor, make_gateway, client):
        """块生命周期：thinking 连续同块 → stop → text 块 → stop → message_delta/stop。"""
        vendor.set("sk-A", StreamOk(chunks=["你", "好"],
                                    reasoning_chunks=["想一", "想二"],
                                    thinking_style="thinking_content"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{MESSAGES_URL}",
                                 json=_abody(stream=True), headers=_headers())
        assert resp.status_code == 200
        evs = _parse_sse(resp)
        names = [e["event"] for e in evs]

        assert names[0] == "message_start"  # 首事件
        assert names[-1] == "message_stop"
        assert evs[0]["data"]["message"]["model"] == "test-model"

        # thinking 块：单 start、连续 delta（同块不重复 start）、单 stop
        t_start = [i for i, e in enumerate(evs)
                   if e["event"] == "content_block_start"
                   and e["data"]["content_block"]["type"] == "thinking"]
        assert len(t_start) == 1
        i0 = t_start[0]
        thinking_deltas = [e["data"]["delta"]["thinking"] for e in evs
                           if e["event"] == "content_block_delta"
                           and e["data"]["delta"]["type"] == "thinking_delta"]
        assert "".join(thinking_deltas) == "想一想二"

        # text 块：thinking stop 之后才 start（块序正确）
        x_start = [i for i, e in enumerate(evs)
                   if e["event"] == "content_block_start"
                   and e["data"]["content_block"]["type"] == "text"]
        assert len(x_start) == 1
        t_stop = [i for i, e in enumerate(evs)
                  if e["event"] == "content_block_stop"]
        assert len(t_stop) == 2  # 两块各一个 stop
        assert t_stop[0] < x_start[0]  # 先关 thinking 再开 text
        text_deltas = [e["data"]["delta"]["text"] for e in evs
                       if e["event"] == "content_block_delta"
                       and e["data"]["delta"]["type"] == "text_delta"]
        assert "".join(text_deltas) == "你好"

        # message_delta：stop_reason + usage（OpenAI usage 帧的 completion_tokens）
        m_delta = [e for e in evs if e["event"] == "message_delta"]
        assert len(m_delta) == 1
        assert m_delta[0]["data"]["delta"]["stop_reason"] == "end_turn"
        assert m_delta[0]["data"]["usage"]["output_tokens"] == 5

    async def test_stream_outbound_body_carries_stream_flag(
            self, vendor, make_gateway, client):
        """回归（E2E 实测 Bug）：出站体缺失 stream:true → 供应商返回非流式 → 空流。"""
        vendor.set("sk-A", StreamOk(chunks=["好"]))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{MESSAGES_URL}",
                                 json=_abody(stream=True), headers=_headers())
        assert resp.status_code == 200
        assert vendor.bodies_for("sk-A")[0].get("stream") is True
        evs = _parse_sse(resp)
        assert any(e["event"] == "content_block_delta" for e in evs)  # 有内容事件

    async def test_stream_cancel_propagates(self, vendor, make_gateway, client):
        """INT-28：流式中途断连 → 上游取消、aborted、C=0、无切换（同 INT-08 语义）。"""
        vendor.set("sk-A", StreamOk(chunks=["一", "二", "三", "四"],
                                    delay_between=0.6))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        req = client.build_request("POST", f"{gw.base_url}{MESSAGES_URL}",
                                   json=_abody(stream=True), headers=_headers())
        resp = await client.send(req, stream=True)
        assert resp.status_code == 200
        received = b""
        async for chunk in resp.aiter_bytes():
            received += chunk
            if received.count(b"data:") >= 3:
                break
        await resp.aclose()  # 客户端断连

        for _ in range(60):
            await asyncio.sleep(0.2)
            if vendor.cancelled_keys:
                break
        assert "sk-A" in vendor.cancelled_keys  # 取消透传到上游
        await gw.drain_events()
        ev = gw.read_events()[0]
        assert ev["status"] == "aborted"
        assert ev["switch_count"] == 0
        assert gw.resource("res-A").C == 0
        assert gw.resource("res-A").status == "active"


class TestAnthropicErrorBodyFidelity:
    """🔴 2026-10-10 修：上游 4xx 的**完整**错误体必须原样到客户端（非流式 + 流式两条腿）。

    旧实现两条腿都用 `str(e.args[0])`，而 `BAD_REQUEST` 路径的 `args[0]` 是
    `stats.events.error_summary(...)` —— **截断 160 字**（`stats/events.py:33-54`）。
    用户实测后果：上游 `400 {"code":11128,"msg":"Illegal API invocation from an
    unapproved channel","requestId":"…","displayMsg":{…"TraceID":…}}` 到客户端只剩
    `…"displayMsg":{"en":"Request blocked.` 就被切断 ⇒ `requestId`/`TraceID` 丢失，
    既无法向上游报障也无法自查。OpenAI 入站本就透传完整 body，此处补齐不对称。

    撤证方向：把 `api/anthropic.py::_gw_error_message` 改回 `str(e.args[0])`
    ⇒ 本类两条用例必红（错误体只剩 160 字摘要、尾部 TraceID 丢失）。
    """

    #: 上游诊断串（>160 字，尾部带 TraceID）—— 复刻用户实测被截断的形状。
    _TAIL = "TraceID=32cf2cd9-a58e-4820-8fb2-e629254ced5e"

    def _long_message(self) -> str:
        return ("Illegal API invocation from an unapproved channel; "
                + "filler " * 40 + self._TAIL)

    async def test_nonstream_bad_request_keeps_full_upstream_body(
            self, vendor, make_gateway, client):
        vendor.set("sk-A", Err(status=400, err_type="invalid_request_error",
                               message=self._long_message()))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{MESSAGES_URL}",
                                 json=_abody(), headers=_headers())
        assert resp.status_code == 400
        body = resp.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == "invalid_request_error"
        msg = body["error"]["message"]
        assert len(msg) > 160, f"错误体被截断成摘要（{len(msg)} 字）：{msg}"
        assert self._TAIL in msg, f"上游诊断字段丢失：{msg}"

    async def test_stream_bad_request_keeps_full_upstream_body(
            self, vendor, make_gateway, client):
        vendor.set("sk-A", Err(status=400, err_type="invalid_request_error",
                               message=self._long_message()))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{MESSAGES_URL}",
                                 json=_abody(stream=True), headers=_headers())
        assert resp.status_code == 400
        msg = resp.json()["error"]["message"]
        assert len(msg) > 160, f"流式错误体被截断成摘要（{len(msg)} 字）：{msg}"
        assert self._TAIL in msg, f"上游诊断字段丢失：{msg}"


class TestAnthropicAlias:
    """INT-33：Claude Code 风格 model id 别名命中网关模型。"""

    async def test_alias_model_id_resolves(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="ok"))
        gw = await make_gateway(gateway_config(
            vendor.port, models=[chat_res("A", name="claude-sonnet-4")]))
        resp = await client.post(f"{gw.base_url}{MESSAGES_URL}",
                                 json=_abody(model="claude-sonnet-4-20250514"),
                                 headers=_headers())
        assert resp.status_code == 200
        d = resp.json()
        assert d["model"] == "claude-sonnet-4"  # 响应体为规范网关模型名
        assert d["content"] == [{"type": "text", "text": "ok"}]
        # 出站到厂商的是资源声明的供应商模型名（vm-A），而非别名
        assert vendor.bodies_for("sk-A")[0]["model"] == "vm-A"
