"""实验2：通过 agen.aclose()（GeneratorExit 路径）关闭 httpx 流 → 厂商是否观测到中断。

这是网关调度器的实际路径：CancelledError 打在调度器生成器的 yield 挂起点，
随后 finally 中 await aclose_quiet(agen) 关闭出站流。
"""
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

    async def vendor_stream():
        """模拟出站适配器生成器（与 openai_out.chat_stream 同构）。"""
        try:
            async with client.stream(
                "POST", f"http://127.0.0.1:{v.port}/v1/chat/completions",
                headers={"Authorization": "Bearer sk-A"},
                json={"model": "vm", "stream": True, "messages": []},
            ) as resp:
                async for raw in resp.aiter_lines():
                    if raw.startswith("data:"):
                        yield raw
        except BaseException as e:
            print(f"[adapter] exc {type(e).__name__}")
            raise

    async def scheduler_gen():
        """模拟调度器：消费出站流并转发。"""
        agen = vendor_stream()
        try:
            n = 0
            async for chunk in agen:
                n += 1
                print(f"[sched] chunk {n}")
                yield chunk
                if n >= 2:
                    break
        finally:
            print("[sched] finally → aclose_quiet(agen)")
            try:
                await agen.aclose()
            except Exception:
                pass

    async def consumer():
        gen = scheduler_gen()
        n = 0
        async for c in gen:
            n += 1
            print(f"[consumer] {n}")
            if n >= 2:
                break
        # 模拟 body_stream finally 的 task.cancel()：直接关闭底层生成器链
        print("[consumer] closing generator chain")
        await gen.aclose()

    await asyncio.wait_for(consumer(), timeout=10)

    for i in range(20):
        await asyncio.sleep(0.3)
        if v.cancelled_keys:
            print(f"[main] vendor cancelled after {(i+1)*0.3:.1f}s: {v.cancelled_keys}")
            break
    else:
        print("[main] vendor NEVER observed cancellation (connection kept alive / drained)")

    await client.aclose()
    server.should_exit = True
    await task


asyncio.run(main())
