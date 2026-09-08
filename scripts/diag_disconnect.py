"""诊断：客户端断连 → 网关 → FakeVendor 取消传播链路。"""
import asyncio
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
import httpx
import uvicorn.protocols.http.h11_impl as h11_impl

_orig_connection_lost = h11_impl.H11Protocol.connection_lost

def _traced_connection_lost(self, exc):
    try:
        sock = self.transport.get_extra_info("sockname")
        port = sock[1] if sock else "?"
    except Exception:
        port = "?"
    print(f"[trace][sock_port={port}] connection_lost exc={exc!r} response_complete={self.cycle.response_complete if self.cycle else '?'}", flush=True)
    return _orig_connection_lost(self, exc)

h11_impl.H11Protocol.connection_lost = _traced_connection_lost

# 追踪出站适配器的流关闭
from model_gateway.adapters import openai_out as _oo
_orig_stream = _oo.OpenAIOutAdapter.chat_stream

async def _traced_stream(self, key, vendor_model, body, timeout):
    print(f"[trace][adapter] chat_stream enter {key}", flush=True)
    try:
        agen = _orig_stream(self, key, vendor_model, body, timeout)
        try:
            async for chunk in agen:
                yield chunk
        finally:
            print("[trace][adapter] stream loop exiting → aclose", flush=True)
            await agen.aclose()
            print("[trace][adapter] aclose done", flush=True)
    except BaseException as e:
        print(f"[trace][adapter] chat_stream exc {type(e).__name__}", flush=True)
        raise
    finally:
        print("[trace][adapter] chat_stream exit", flush=True)

_oo.OpenAIOutAdapter.chat_stream = _traced_stream

from tests.integration.fakevendor import FakeVendor, start_fake_vendor, StreamOk, Ok
from model_gateway.main import create_app


async def main():
    # 1. FakeVendor
    v = FakeVendor()
    server, task, wait_ready = start_fake_vendor(v)
    v.port = await wait_ready()
    print(f"[vendor] started on {v.port}")

    # 2. Gateway
    cfg = {
        "providers": [{
            "id": "p1", "access_mode": "api", "protocol": "openai",
            "base_url": f"http://127.0.0.1:{v.port}/v1",
            "accounts": [{"id": "acc1", "keys": [{"id": "key_A", "value": "sk-A"}]}],
        }],
        "models": [{"name": "test-model", "endpoint": "chat",
                    "resources": [{"provider": "p1", "key": "key_A", "model": "vm-A"}]}],
        "gateway": {"heartbeat_seconds": 1},
    }
    tmp = Path("/tmp/mg-diag")
    tmp.mkdir(exist_ok=True)
    cfg_path = tmp / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    app = create_app(config_path=cfg_path, usage_dir=tmp / "usage", enums_path=tmp / "enums.yaml")
    gconfig = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    gserver = uvicorn.Server(gconfig)
    gtask = asyncio.get_running_loop().create_task(gserver.serve())
    for _ in range(500):
        if gserver.started:
            break
        await asyncio.sleep(0.01)
    gw_port = gserver.servers[0].sockets[0].getsockname()[1]
    print(f"[gateway] started on {gw_port}")

    # 3. 流式请求：FakeVendor 逐 chunk 延迟输出
    import time
    t0 = time.monotonic()
    def ts(): return f"{time.monotonic()-t0:6.2f}s"
    v.set("sk-A", StreamOk(chunks=["一", "二", "三", "四"], delay_between=0.6))
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), trust_env=False) as client:
        req = client.build_request("POST", f"http://127.0.0.1:{gw_port}/v1/chat/completions",
                                    json={"model": "test-model", "stream": True,
                                          "messages": [{"role": "user", "content": "hi"}]})
        resp = await client.send(req, stream=True)
        print(f"[{ts()}][client] status={resp.status_code}")
        received = b""
        async for chunk in resp.aiter_bytes():
            received += chunk
            print(f"[{ts()}][client] got chunk {len(chunk)}b, total={len(received)}")
            if received.count(b"data:") >= 3:
                break
        print(f"[{ts()}][client] closing (simulating disconnect)")
        await resp.aclose()

        await asyncio.sleep(3.0)

    print(f"[{ts()}][vendor] requests={[(r.key, r.cancelled) for r in v.requests]}")
    await app.state.runtime.events.queue.join()
    day_files = list((tmp / "usage").glob("events-*.jsonl"))
    for f in day_files:
        for line in f.read_text().splitlines():
            print(f"[event] {line[:200]}")

    gserver.should_exit = True
    await gtask
    server.should_exit = True
    await task


asyncio.run(main())
