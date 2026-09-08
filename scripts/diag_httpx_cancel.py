"""最小实验：取消 httpx 流式消费任务 → FakeVendor 是否观测到连接中断。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import uvicorn

from tests.integration.fakevendor import FakeVendor, start_fake_vendor, StreamOk


async def main():
    v = FakeVendor()
    server, task, wait_ready = start_fake_vendor(v)
    v.port = await wait_ready()
    print(f"[vendor] port={v.port}")
    v.set("sk-A", StreamOk(chunks=["一", "二", "三", "四"], delay_between=0.6))

    client = httpx.AsyncClient(timeout=30.0, trust_env=False)

    async def consume():
        n = 0
        async with client.stream("POST", f"http://127.0.0.1:{v.port}/v1/chat/completions",
                                  headers={"Authorization": "Bearer sk-A"},
                                  json={"model": "vm", "stream": True, "messages": []}) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    n += 1
                    print(f"[consumer] line {n}: {line[:50]}")
                    if n >= 2:
                        break
        return n

    t = asyncio.create_task(consume())
    # 等 2 行收完后立即取消任务（模拟调度器取消 pull）
    await asyncio.sleep(0.3)
    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        print("[main] consume task cancelled")

    # 观察厂商侧：等待足够长时间看连接是否被关 / cancelled 是否置位
    for i in range(20):
        await asyncio.sleep(0.3)
        if v.cancelled_keys:
            print(f"[main] vendor cancelled after {(i+1)*0.3:.1f}s: {v.cancelled_keys}")
            break
    else:
        print("[main] vendor never observed cancellation")

    await client.aclose()
    server.should_exit = True
    await task


asyncio.run(main())
