"""最小复现：Starlette StreamingResponse 在客户端断连时是否被取消。"""
import asyncio

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

state = {"cancelled": False, "completed": False, "sent": 0}


async def sse(request):
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


app = Starlette(routes=[Route("/sse", sse, methods=["GET"])])


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
        req = client.build_request("GET", f"http://127.0.0.1:{port}/sse")
        resp = await client.send(req, stream=True)
        got = b""
        async for chunk in resp.aiter_bytes():
            got += chunk
            if got.count(b"data:") >= 3:
                break
        await resp.aclose()  # 客户端断连
        await asyncio.sleep(3.0)

    print(f"sent={state['sent']} cancelled={state['cancelled']} completed={state['completed']}")
    server.should_exit = True
    await task


asyncio.run(main())
