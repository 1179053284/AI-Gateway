"""逐步逼近网关形态：first-frame await + queue/pull 结构 + watcher。"""
import asyncio

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

state = {"cancelled": False, "completed": False, "sent": 0, "pull_cancelled": False}

app = FastAPI()


@app.post("/v1/chat")
async def chat(request: Request):
    body = await request.json()
    heartbeat = 1.0

    async def sched_gen():
        """模拟调度器生成器：0.3s 一个事件。"""
        try:
            for i in range(10):
                yield {"n": i}
                await asyncio.sleep(0.3)
            state["completed"] = True
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    # —— watcher（模拟网关 _watch_disconnects）——
    async def watch():
        while True:
            await asyncio.sleep(0.2)
            d = await request.is_disconnected()
            if d:
                print("[dbg] watcher detected disconnect", flush=True)
                return

    watcher = asyncio.get_running_loop().create_task(watch())

    # —— first frame await（延迟提交）——
    first = await sched_gen().__anext__()
    print(f"[dbg] first frame: {first}", flush=True)
    watcher.cancel()

    async def body_stream():
        queue: asyncio.Queue = asyncio.Queue()
        END = object()

        async def pull():
            try:
                await queue.put(first)
                async for ev in sched_gen():
                    await queue.put(ev)
            finally:
                queue.put_nowait(END)

        task = asyncio.create_task(pull())
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if ev is END:
                    break
                yield f"data: {ev}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            print(f"[dbg] body_stream finally (pull done={task.done()})", flush=True)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                state["pull_cancelled"] = True
            print(f"[dbg] pull awaited cancelled={task.cancelled()}", flush=True)

    return StreamingResponse(body_stream(), media_type="text/event-stream")


async def main():
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.get_running_loop().create_task(server.serve())
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]

    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        req = client.build_request("POST", f"http://127.0.0.1:{port}/v1/chat",
                                    json={"model": "m", "messages": []})
        resp = await client.send(req, stream=True)
        got = b""
        async for chunk in resp.aiter_bytes():
            got += chunk
            if got.count(b"data:") >= 3:
                break
        await resp.aclose()  # 客户端断连
        await asyncio.sleep(3.0)

    print(f"RESULT sent={state['sent']} gen_cancelled={state['cancelled']} "
          f"completed={state['completed']} pull_cancelled={state['pull_cancelled']}")
    server.should_exit = True
    await task


asyncio.run(main())
