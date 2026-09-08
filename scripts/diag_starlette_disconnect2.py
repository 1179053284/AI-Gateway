"""逐步逼近网关形态：FastAPI + POST + json body + StreamingResponse。"""
import asyncio

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

state = {"cancelled": False, "completed": False, "sent": 0, "is_disconnected_polls": 0}

app = FastAPI()


@app.post("/v1/chat")
async def chat(request: Request):
    body = await request.json()  # 消费请求体（同网关）
    print(f"[dbg] body={body}", flush=True)

    async def gen():
        try:
            for i in range(10):
                yield f"data: {i}\n\n"
                state["sent"] += 1
                await asyncio.sleep(0.3)
            state["completed"] = True
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    return StreamingResponse(gen(), media_type="text/event-stream")


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

    print(f"RESULT sent={state['sent']} cancelled={state['cancelled']} completed={state['completed']}")
    server.should_exit = True
    await task


asyncio.run(main())
