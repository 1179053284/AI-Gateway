"""诊断 INT-24：延迟提交窗口内断连 → 上游取消传播。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import uvicorn
import yaml

from tests.integration.fakevendor import FakeVendor, start_fake_vendor, StreamOk
from model_gateway.main import create_app

# 追踪调度器生成器的取消链路
from model_gateway.adapters import openai_out as _oo

_orig_chat_stream = _oo.OpenAIOutAdapter.chat_stream

async def _traced_chat_stream(self, key, vendor_model, body, timeout):
    agen = _orig_chat_stream(self, key, vendor_model, body, timeout)
    try:
        async for chunk in agen:
            yield chunk
    except BaseException as e:
        print(f"[adapter] exc {type(e).__name__}", flush=True)
        raise
    finally:
        print("[adapter] finally → aclose_quiet", flush=True)
        try:
            await agen.aclose()
            print("[adapter] aclose done", flush=True)
        except BaseException as e:
            print(f"[adapter] aclose exc {type(e).__name__}", flush=True)

_oo.OpenAIOutAdapter.chat_stream = _traced_chat_stream


async def main():
    v = FakeVendor()
    server, task, wait_ready = start_fake_vendor(v)
    v.port = await wait_ready()
    print(f"[vendor] port={v.port}")

    cfg = {
        "providers": [{
            "id": "p1", "access_mode": "api", "protocol": "openai",
            "base_url": f"http://127.0.0.1:{v.port}/v1",
            "accounts": [{"id": "acc1", "keys": [
                {"id": "key_A", "value": "sk-A"}, {"id": "key_B", "value": "sk-B"}]}],
        }],
        "models": [{"name": "test-model", "endpoint": "chat",
                    "resources": [{"provider": "p1", "key": "key_A", "model": "vm-A"},
                                   {"provider": "p1", "key": "key_B", "model": "vm-B"}]}],
    }
    tmp = Path("/tmp/mg-diag-window")
    tmp.mkdir(exist_ok=True)
    cfg_path = tmp / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    app = create_app(config_path=cfg_path, usage_dir=tmp / "usage", enums_path=tmp / "enums.yaml")
    gconfig = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    gserver = uvicorn.Server(gconfig)
    gtask = asyncio.get_running_loop().create_task(gserver.serve())
    for _ in range(500):
        if gserver.started:
            break
        await asyncio.sleep(0.01)
    gw_port = gserver.servers[0].sockets[0].getsockname()[1]

    v.set("sk-A", StreamOk(chunks=["x"], delay_first=10.0))
    v.set("sk-B", StreamOk(chunks=["x"]))

    import time
    t0 = time.monotonic()
    def ts(): return f"{time.monotonic()-t0:6.2f}s"

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), trust_env=False) as client:
        req = client.build_request("POST", f"http://127.0.0.1:{gw_port}/v1/chat/completions",
                                   json={"model": "test-model", "stream": True,
                                         "messages": [{"role": "user", "content": "hi"}]})
        resp = await client.send(req, stream=True)
        print(f"[{ts()}][client] status={resp.status_code}")
        await asyncio.sleep(1.0)
        print(f"[{ts()}][client] closing (disconnect)")
        await resp.aclose()

        for _ in range(40):
            await asyncio.sleep(0.2)
            if v.cancelled_keys:
                break
        print(f"[{ts()}][vendor] cancelled_keys={v.cancelled_keys}")

    await asyncio.sleep(0.5)
    await app.state.runtime.events.queue.join()
    for f in sorted((tmp / "usage").glob("events-*.jsonl")):
        for line in f.read_text().splitlines():
            print(f"[event] {line[:260]}")

    gserver.should_exit = True
    await gtask
    server.should_exit = True
    await task


asyncio.run(main())
