"""INT 流式链路（INT-08~12 / INT-21 / INT-24 / INT-30 / INT-35）。"""

from __future__ import annotations

import asyncio
import contextlib
import json

import httpx
import pytest

from tests.integration.conftest import chat_res, gateway_config
from tests.integration.fakevendor import Err, Ok, StreamOk

CHAT_URL = "/v1/chat/completions"


def _body(stream: bool = True, model: str = "test-model", **over) -> dict:
    d = {"model": model, "stream": stream, "messages": [{"role": "user", "content": "hi"}]}
    d.update(over)
    return d


async def _raw_connect(gw, path: str, body: dict):
    """裸 TCP 连接发送请求（响应未开始时模拟在途断连用；关闭 writer 即断连）。"""
    port = int(gw.base_url.rsplit(":", 1)[1])
    payload = json.dumps(body).encode("utf-8")
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        f"Content-Type: application/json\r\nContent-Length: {len(payload)}\r\n"
        f"Connection: close\r\n\r\n".encode() + payload
    )
    await writer.drain()
    return reader, writer


async def _sse_events(resp: httpx.Response) -> list[dict]:
    """解析 SSE data: 行为 dict 列表（跳过注释帧）。"""
    events = []
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            payload = line[6:]
            if payload.strip() == "[DONE]":
                events.append("[DONE]")
            else:
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    events.append({"_raw": payload})
    return events


class TestStreamBaseline:
    """流式成功基线 + INT-30 思考字段归一化。"""

    async def test_stream_success(self, vendor, make_gateway, client):
        vendor.set("sk-A", StreamOk(chunks=["你好", "世界"]))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{CHAT_URL}", json=_body())
        assert resp.status_code == 200
        events = await _sse_events(resp)
        contents = [c["choices"][0]["delta"].get("content")
                    for c in events if isinstance(c, dict) and c.get("choices")]
        assert "".join(x for x in contents if x) == "你好世界"
        assert events[-1] == "[DONE]"
        models = {c["model"] for c in events
                  if isinstance(c, dict) and "model" in c}
        assert models <= {"test-model"}  # 统一名替换（无 model 字段的帧如 usage 不受影响）

    async def test_thinking_field_normalized(self, vendor, make_gateway, client):
        """INT-30：thinking_content / reasoning_content 两风格统一为 reasoning_content。"""
        # A：V4 Pro 风格 thinking_content
        vendor.set("sk-A", StreamOk(chunks=["答"], reasoning_chunks=["想"],
                                     thinking_style="thinking_content"))
        # B：GLM 风格 reasoning_content
        vendor.set("sk-B", StreamOk(chunks=["答"], reasoning_chunks=["想"],
                                     thinking_style="reasoning_content"))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        resp = await client.post(f"{gw.base_url}{CHAT_URL}", json=_body())
        events = await _sse_events(resp)
        deltas = [c["choices"][0]["delta"] for c in events
                  if isinstance(c, dict) and c.get("choices")]
        assert any(d.get("reasoning_content") == "想" for d in deltas)  # A 统一后
        assert any(d.get("content") == "答" for d in deltas)

        # B 承接（A 已被第二个请求继续选？串行恒选 A——直接第二个请求打 B 需 A 冷却）
        vendor.set("sk-A", Err(500))
        resp2 = await client.post(f"{gw.base_url}{CHAT_URL}", json=_body())
        assert resp2.status_code == 200
        events2 = await _sse_events(resp2)
        deltas2 = [c["choices"][0]["delta"] for c in events2
                   if isinstance(c, dict) and c.get("choices")]
        assert any(d.get("reasoning_content") == "想" for d in deltas2)  # B 原生保留
        assert any(d.get("content") == "答" for d in deltas2)


class TestStreamFailover:
    """INT-10：流式首帧前切换无感（连接建立后未输出内容即断开）。"""

    async def test_preframe_switch_transparent(self, vendor, make_gateway, client):
        # A：首帧前网络中断（连接建立后无任何 chunk 即 abort）
        vendor.set("sk-A", StreamOk(chunks=["x"], abort_after=0))
        vendor.set("sk-B", StreamOk(chunks=["from", "B"]))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        resp = await client.post(f"{gw.base_url}{CHAT_URL}", json=_body())
        assert resp.status_code == 200
        events = await _sse_events(resp)
        contents = "".join(c["choices"][0]["delta"].get("content", "")
                           for c in events if isinstance(c, dict) and c.get("choices"))
        assert contents == "fromB"  # 完整流、无重复内容
        assert not any(isinstance(c, dict) and c.get("error") for c in events)
        await gw.drain_events()
        ev = gw.read_events()[0]
        assert ev["status"] == "success"
        assert ev["switch_count"] == 1

    async def test_preframe_error_switch(self, vendor, make_gateway, client):
        """首帧前 HTTP 错误同样切换无感（窗口期重试/切换零感知）。"""
        vendor.set("sk-A", Err(500))
        vendor.set("sk-B", StreamOk(chunks=["ok"]))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        resp = await client.post(f"{gw.base_url}{CHAT_URL}", json=_body())
        assert resp.status_code == 200
        events = await _sse_events(resp)
        assert not any(isinstance(c, dict) and c.get("error") for c in events)


class TestStreamMidwayFailure:
    """INT-11 / INT-12：committed 后中途失败两分支（不重放）。"""

    async def test_midway_unrecoverable_error_frame(self, vendor, make_gateway, client):
        """INT-11：输出 2 chunk 后返回 400 → error 帧携带厂商原始错误，无内容重复。"""
        vendor.set("sk-A", StreamOk(
            chunks=["一", "二"],
            err_after=Err(400, "invalid_request_error", "bad param")))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{CHAT_URL}", json=_body())
        assert resp.status_code == 200
        text = resp.text
        assert "一" in text and "二" in text  # 已收 2 chunk
        assert text.count("一") == 1  # 不自动重放（无内容重复）
        err_frames = [line for line in text.splitlines()
                      if line.startswith("data: ") and "invalid_request_error" in line]
        assert err_frames  # error 帧携带厂商原始错误（不修饰）
        assert "bad param" in text
        await gw.drain_events()
        ev = gw.read_events()[0]
        assert ev["status"] == "failed"
        assert gw.resource("res-A").C == 1  # C+1（中途失败也是失败）

    async def test_midway_network_abort_retryable(self, vendor, make_gateway, client):
        """INT-12：输出 2 chunk 后网络中断 → error 帧 + retryable 标注，不重放。"""
        vendor.set("sk-A", StreamOk(chunks=["一", "二"], abort_after=2))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
        resp = await client.post(f"{gw.base_url}{CHAT_URL}", json=_body())
        assert resp.status_code == 200
        text = resp.text
        assert "一" in text and "二" in text
        assert text.count("一") == 1  # 不重放
        error_payloads = [json.loads(l[6:]) for l in text.splitlines()
                          if l.startswith("data: ") and l[6:].startswith("{") and
                          json.loads(l[6:]).get("error")]
        assert error_payloads
        assert any(p["error"].get("retryable") for p in error_payloads)  # retryable 标注
        await gw.drain_events()
        assert gw.read_events()[0]["status"] == "failed"


class TestStreamWindowExhausted:
    """INT-35：流式窗口耗尽返回非 200（绝不能 200 + 内嵌 error）。"""

    async def test_window_exhausted_non_200(self, vendor, make_gateway, client):
        vendor.set("sk-A", Err(500))
        vendor.set("sk-B", Err(500))
        gw = await make_gateway(gateway_config(
            vendor.port, models=[chat_res("AB")],
            gateway={"request_total_budget_seconds": 2, "attempt_timeout_seconds": 1},
            scheduling={"fail_threshold": 99, "retry_backoff_seconds": 0.5}))
        resp = await client.post(f"{gw.base_url}{CHAT_URL}", json=_body())
        assert resp.status_code != 200  # 核心验证点：响应头状态码
        assert resp.status_code == 503
        err = resp.json()["error"]
        assert err["code"] == "BUDGET_EXHAUSTED"
        assert "test-model" in json.dumps(err, ensure_ascii=False)


class TestHeartbeat:
    """INT-21：SSE 心跳注释帧。"""

    async def test_heartbeat_during_silence(self, vendor, make_gateway, client):
        """INT-21：静默期心跳。注：延迟提交窗口（首内容事件前）不发送任何字节（tech §4.5），
        故静默须构造在首内容事件之后——首 chunk 输出后 vendor 静默 2.5s 再续。"""
        vendor.set("sk-A", StreamOk(chunks=["first", "late"], delay_between=2.5))
        gw = await make_gateway(gateway_config(
            vendor.port, models=[chat_res("A")],
            gateway={"heartbeat_seconds": 1}))
        req = client.build_request("POST", f"{gw.base_url}{CHAT_URL}", json=_body())
        resp = await client.send(req, stream=True)
        assert resp.status_code == 200
        raw = b""
        deadline = asyncio.get_event_loop().time() + 10
        got_content = False
        got_done = False
        async for chunk in resp.aiter_bytes():
            raw += chunk
            if b"late" in raw:
                got_content = True
            if b"[DONE]" in raw:
                got_done = True
                break
            if asyncio.get_event_loop().time() > deadline:
                break
        await resp.aclose()
        text = raw.decode("utf-8", "replace")
        assert got_content and got_done
        assert ": keep-alive" in text  # 已提交后的静默期收到心跳注释帧


class TestClientDisconnect:
    """INT-08 / INT-09 / INT-24 / INT-32：取消透传与语义保护。"""

    async def test_stream_cancel_propagates(self, vendor, make_gateway, client):
        """INT-08/09：流式收到 2 chunk 后断连 → 上游取消、aborted、C=0、无切换。"""
        vendor.set("sk-A", StreamOk(chunks=["一", "二", "三", "四"],
                                     delay_between=0.6))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        req = client.build_request("POST", f"{gw.base_url}{CHAT_URL}", json=_body())
        resp = await client.send(req, stream=True)
        assert resp.status_code == 200
        received = b""
        # 读完前 2 个 chunk 后断开
        async for chunk in resp.aiter_bytes():
            received += chunk
            if received.count(b"data:") >= 3:  # role + 2 内容 chunk
                break
        await resp.aclose()  # 客户端断连
        assert b"\xe4\xb8\x80" in received or "一" in received.decode("utf-8", "replace")

        # 等待上游取消传播 + 事件落盘
        for _ in range(60):
            await asyncio.sleep(0.2)
            if vendor.cancelled_keys:
                break
        assert "sk-A" in vendor.cancelled_keys  # FakeVendor 收到连接取消
        await gw.drain_events()
        ev = gw.read_events()[0]
        assert ev["status"] == "aborted"
        assert ev["switch_count"] == 0
        assert gw.resource("res-A").C == 0  # INT-09：CancelledError 未被吞成失败
        assert gw.resource("res-A").status == "active"
        assert gw.resource("res-A").in_flight == 0

    async def test_nonstream_cancel_propagates(self, vendor, make_gateway, client):
        """INT-32：非流式响应延迟中断连 → 上游取消、aborted、C=0。

        响应未开始时 httpx send 会阻塞到响应头，无法用 resp.aclose() 模拟
        在途断连 → 用裸连接断开（模拟 1s 后客户端断连）。
        """
        vendor.set("sk-A", Ok(delay=5.0))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        reader, writer = await _raw_connect(gw, CHAT_URL, _body(stream=False))
        await asyncio.sleep(1.0)  # 请求已在途（FakeVendor 延迟中）
        writer.close()  # 客户端断连
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        for _ in range(40):
            await asyncio.sleep(0.2)
            if vendor.cancelled_keys:
                break
        assert "sk-A" in vendor.cancelled_keys
        await gw.drain_events()
        ev = gw.read_events()[0]
        assert ev["status"] == "aborted"
        assert gw.resource("res-A").C == 0

    async def test_delayed_commit_window_disconnect(self, vendor, make_gateway, client):
        """INT-24：延迟提交窗口内断连 → 整链中止、不再重试/切换。

        延迟提交窗口内网关不发送任何字节（响应头也未发），httpx send 阻塞到
        首内容事件 → 用裸连接在窗口内断开。
        """
        vendor.set("sk-A", StreamOk(chunks=["x"], delay_first=10.0))
        vendor.set("sk-B", StreamOk(chunks=["x"]))
        gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
        reader, writer = await _raw_connect(gw, CHAT_URL, _body())
        await asyncio.sleep(1.0)  # 窗口内等待首帧（A 静默 10s）
        writer.close()  # 窗口内断连
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        for _ in range(40):
            await asyncio.sleep(0.2)
            if vendor.cancelled_keys:
                break
        assert "sk-A" in vendor.cancelled_keys  # 上游请求被取消
        await gw.drain_events()
        ev = gw.read_events()[0]
        assert ev["status"] == "aborted"
        assert ev["switch_count"] == 0  # 不再继续重试/切换
        assert all(r.key != "sk-B" for r in vendor.requests)  # B 从未被触达
        assert gw.resource("res-A").C == 0
