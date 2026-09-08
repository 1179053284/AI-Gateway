"""诊断 INT-12：流式中途网络中断 → error 帧 + retryable 标注。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import uvicorn
import yaml

from tests.integration.fakevendor import FakeVendor, start_fake_vendor, StreamOk
from model_gateway.main import create_app


async def main():
    v = FakeVendor()
    server, task, wait_ready = start_fake_vendor(v)
    v.port = await wait_ready()
    print(f"[vendor] port={v.port}")

    cfg = {
        "providers": [{
            "id": "p1", "access_mode": "api", "protocol": "openai",
            "base_url": f"http://127.0.0.1:{v.port}/v1",
            "accounts": [{"id": "acc1", "keys": [{"id": "key_A", "value": "sk-A"}]}],
        }],
        "models": [{"name": "test-model", "endpoint": "chat",
                    "resources": [{"provider": "p1", "key": "key_A", "model": "vm-A"}]}],
    }
    tmp = Path("/tmp/mg-diag-midway")
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

    v.set("sk-A", StreamOk(chunks=["一", "二"], abort_after=2))
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), trust_env=False) as client:
        resp = await client.post(f"http://127.0.0.1:{gw_port}/v1/chat/completions",
                                 json={"model": "test-model", "stream": True,
                                       "messages": [{"role": "user", "content": "hi"}]})
        print(f"[client] status={resp.status_code}")
        text = resp.text
        print(f"[client] response text ({len(text)} chars):")
        print(repr(text))

    await asyncio.sleep(1.0)
    await app.state.runtime.events.queue.join()
    for f in sorted((tmp / "usage").glob("events-*.jsonl")):
        for line in f.read_text().splitlines():
            print(f"[event] {line[:300]}")

    gserver.should_exit = True
    await gtask
    server.should_exit = True
    await task


asyncio.run(main())
