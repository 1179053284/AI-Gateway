"""实验3：完全复刻网关流式结构（starlette + queue/pull + body_stream + task.cancel in finally）。"""
import asyncio
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from tests.integration.fakevendor import FakeVendor, start_fake_vendor, StreamOk

# —— patch：追踪谁在 cancel 任务 ——
import asyncio as _aio_mod
from anyio._backends._asyncio import CancelScope as _ACS

_orig_scope_cancel = _ACS.cancel

def _traced_scope_cancel(self, reason=None):
    import asyncio as _aio2
    tasks = [t.get_name() for t in self._tasks]
    print(f"[anyio] scope {id(self):x} cancel() by {_aio2.current_task().get_name() if _aio2.current_task() else '?'} tasks={tasks} shield={self._shield} host={self._host_task.get_name() if self._host_task else None}", flush=True)
    return _orig_scope_cancel(self, reason)

_ACS.cancel = _traced_scope_cancel

_orig_scope_enter = _ACS.__enter__

def _traced_scope_enter(self):
    import asyncio as _aio2
    t = _aio2.current_task()
    r = _orig_scope_enter(self)
    print(f"[anyio] scope {id(self):x} enter by {t.get_name() if t else '?'} shield={self._shield} parent={id(self._parent_scope):x}" if self._parent_scope else f"[anyio] scope {id(self):x} enter by {t.get_name() if t else '?'} shield={self._shield} parent=None", flush=True)
    return r

_ACS.__enter__ = _traced_scope_enter

# —— patch httpcore：追踪连接关闭路径 ——
import httpcore._async.http11 as _h11mod
import traceback as _tb

_orig_conn_aclose = _h11mod.AsyncHTTP11Connection.aclose

async def _traced_conn_aclose(self):
    print(f"[httpcore] AsyncHTTP11Connection.aclose() called (state={self._state})", flush=True)
    return await _orig_conn_aclose(self)

_h11mod.AsyncHTTP11Connection.aclose = _traced_conn_aclose

_orig_bs_aclose = _h11mod.HTTP11ConnectionByteStream.aclose

async def _traced_bs_aclose(self):
    import asyncio as _aio
    t = _aio.current_task()
    print(f"[httpcore] byte-stream aclose: task={t.get_name()[:20] if t else None}", flush=True)
    try:
        result = await _orig_bs_aclose(self)
        print("[httpcore] byte-stream aclose DONE", flush=True)
        return result
    except BaseException as e:
        print(f"[httpcore] byte-stream aclose EXC: {type(e).__name__}", flush=True)
        raise

_h11mod.HTTP11ConnectionByteStream.aclose = _traced_bs_aclose

_orig_response_closed = _h11mod.AsyncHTTP11Connection._response_closed

async def _traced_response_closed(self):
    import asyncio as _aio
    t = _aio.current_task()
    print(f"[httpcore] _response_closed ENTER task={t.get_name() if t else None} cancelling={t.cancelling() if t else '?'} (our={self._h11_state.our_state}, their={self._h11_state.their_state})", flush=True)
    try:
        await _orig_response_closed(self)
        print(f"[httpcore] _response_closed DONE cancelling={t.cancelling() if t else '?'}", flush=True)
    except BaseException as e:
        import traceback as _t3
        print(f"[httpcore] _response_closed EXC: {type(e).__name__} cancelling={t.cancelling() if t else '?'} msg={e.args!r}", flush=True)
        if isinstance(e, asyncio.CancelledError):
            _t3.print_exception(type(e), e, e.__traceback__, limit=10)
        raise

_h11mod.AsyncHTTP11Connection._response_closed = _traced_response_closed

app = FastAPI()


@app.post("/v1/chat/completions")
async def chat():
    async def vendor_stream():
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            async with client.stream(
                "POST", "http://127.0.0.1:0/v1/chat/completions",  # placeholder replaced
            ) as resp:
                async for raw in resp.aiter_lines():
                    yield raw

    return None  # unreachable


async def main():
    v = FakeVendor()
    server, vtask, wait_ready = start_fake_vendor(v)
    v.port = await wait_ready()
    print(f"[vendor] port={v.port}")
    v.set("sk-A", StreamOk(chunks=["一", "二", "三", "四"], delay_between=0.6))

    client = httpx.AsyncClient(timeout=30.0, trust_env=False)

    async def upstream_gen():
        try:
            async with client.stream(
                "POST", f"http://127.0.0.1:{v.port}/v1/chat/completions",
                headers={"Authorization": "Bearer sk-A"},
                json={"model": "vm", "stream": True, "messages": []},
            ) as resp:
                print("[upstream] stream opened")
                try:
                    async for raw in resp.aiter_lines():
                        print(f"[upstream] line: {raw[:40]}")
                        yield raw
                except BaseException as e:
                    print(f"[upstream] aiter exc: {type(e).__name__}")
                    raise
        except BaseException as e:
            print(f"[upstream] outer exc: {type(e).__name__}")
            raise
        finally:
            print("[upstream] finally (will __aexit__ close stream)")
            try:
                print("[upstream] gen done")
            except Exception:
                pass

    gen = upstream_gen()

    async def _close_gen_chain(g):
        """detached 关闭：在干净任务里关闭上游生成器链（httpx async-with __aexit__ → TCP close）。"""
        try:
            await g.aclose()
            print("[closer] gen.aclose done")
        except BaseException as e:
            print(f"[closer] gen.aclose exc: {type(e).__name__}")

    async def body_stream():
        queue: asyncio.Queue = asyncio.Queue()
        END = object()

        async def pull():
            try:
                async for ev in gen:
                    await queue.put(ev)
            except BaseException as e:
                print(f"[pull] exc: {type(e).__name__}")
                raise
            finally:
                print("[pull] finally → put END")
                queue.put_nowait(END)

        task = asyncio.create_task(pull())
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if ev is END:
                    break
                yield f"{ev}\n\n"
            yield "data: [DONE]\n\n"
        except BaseException as e:
            print(f"[body_stream] exc: {type(e).__name__} cancelling={asyncio.current_task().cancelling()}")
            raise
        finally:
            print(f"[body_stream] finally → task.cancel() (pull cancelling={task.cancelling()})")
            task.cancel()
            # 候选修复：间接等待（不直接 await task，防 host 再取消经 _fut_waiter 转发进 pull）
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait([task], timeout=5.0)
            print("[body_stream] pull awaited indirectly (asyncio.wait)")

    # 起一个真实 uvicorn 服务这个 body_stream（与网关同构）
    from starlette.applications import Starlette
    from starlette.routing import Route

    async def sse(request):
        return StreamingResponse(body_stream(), media_type="text/event-stream")

    gw_app = Starlette(routes=[Route("/sse", sse, methods=["POST"])])
    config = uvicorn.Config(gw_app, host="127.0.0.1", port=0, log_level="warning")
    gserver = uvicorn.Server(config)
    gtask = asyncio.get_running_loop().create_task(gserver.serve())
    for _ in range(500):
        if gserver.started:
            break
        await asyncio.sleep(0.01)
    gw_port = gserver.servers[0].sockets[0].getsockname()[1]
    print(f"[gw] port={gw_port}")

    # 客户端：读 3 帧后断连
    async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
        req = c.build_request("POST", f"http://127.0.0.1:{gw_port}/sse", json={})
        resp = await c.send(req, stream=True)
        print(f"[client] status={resp.status_code}")
        received = b""
        async for chunk in resp.aiter_bytes():
            received += chunk
            if received.count(b"data") >= 3:
                break
        print("[client] closing")
        await resp.aclose()

    for i in range(20):
        await asyncio.sleep(0.3)
        if v.cancelled_keys:
            print(f"[main] vendor cancelled after {(i+1)*0.3:.1f}s: {v.cancelled_keys}")
            break
    else:
        print("[main] vendor NEVER observed cancellation")

    gserver.should_exit = True
    await gtask
    await client.aclose()
    server.should_exit = True
    await vtask


asyncio.run(main())
