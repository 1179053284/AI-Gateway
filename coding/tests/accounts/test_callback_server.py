"""`accounts/callback_server.py` 单测（BD4：本机回跳接收端）。

🔴 判据面 = 「**真实 HTTP 到达**」，不是"函数返回什么"：每个用例外都有一条
   打到实际端口的真连接（`httpx` 走 loopback 套接字，不出本机、不打供应商）。
   这条通道此前的盲点正是"手工造一条 URL 直接喂 `login_callback`"（
   `test_trae.py::…` / `test_lobsterai.py::…` 的老形态）—— 它测不出"没人监听"，
   于是"回跳地址构造出来了但打了就 connection refused"能一路全绿 shipping。
   投递路径的判据在 `tests/integration/test_m7_callback_capture.py`（引擎 + 落盘）。

覆盖：
  · 先绑定后报端口 / 只绑 127.0.0.1（非回环不可达）
  · 首选端口被占 → 回退随机端口；回退端口仍 ≥10000
  · 只服务注册路径：其它路径与 favicon 噪音 → 404 且**不落定**
  · `state`（关联串）不符 → **400 且继续监听**；必填缺失同样 400；可选缺失放行
  · OPTIONS 预检 → 204 + CORS 头，不消耗会话
  · 超时 → 落定 + 关闭；落定后连接被拒
  · **双落定不可能**：并发两条回跳只跑一次 handler
  · `close()` 幂等 / `start()` 幂等
  · 页面是**真 HTML**（成功页含「登录完成，可关闭此页」）且对不可信文案做转义
  · `declared_port()` 的兜底口径（没有接收端时按调用方声明的端口）
"""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from model_gateway.accounts import callback_server
from model_gateway.accounts.callback_server import CallbackCapture, CallbackListener
from model_gateway.accounts.types import LoginOutcome

PATH = "/authorize"


class Recorder:
    """handler 记录器：返回可配置的 `LoginOutcome`，并记下每次收到的 capture。"""

    def __init__(self, outcome: LoginOutcome | None = None) -> None:
        self.calls: list[CallbackCapture] = []
        self.outcome = outcome or LoginOutcome(state="success", detail="登录成功（测试）")
        self.error: Exception | None = None

    async def __call__(self, capture: CallbackCapture) -> LoginOutcome:
        self.calls.append(capture)
        if self.error is not None:
            raise self.error
        return self.outcome


def _listener(handler=None, **kwargs) -> CallbackListener:
    return CallbackListener(path=kwargs.pop("path", PATH),
                            handler=handler or Recorder(), **kwargs)


async def _get(listener: CallbackListener, target: str, *,
               method: str = "get") -> httpx.Response:
    """向**实际端口**发一条真请求（等价于浏览器被 302 之后落在这里）。"""
    async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
        return await getattr(client, method)(
            f"http://127.0.0.1:{listener.port}{target}")


async def _refused(port: int) -> bool:
    """端口是否已经不再受理连接（落定/关闭后的判据）。"""
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=1.0)
    except (OSError, asyncio.TimeoutError):
        return True
    writer.close()
    return False


# ============ 绑定与端口 ============

async def test_start_binds_first_and_reports_the_actual_port():
    """`start()` 先绑定；`port` 是**实际**监听端口（授权 URL 必须用它，BD4 的核心）。"""
    listener = _listener(preferred_port=0)
    try:
        port = await listener.start()
        assert port == listener.port > 0
        assert listener.url == f"http://127.0.0.1:{port}{PATH}"
        assert listener.state == "open" and listener.settled is False
        # 再 start 一次不许重绑（端口是会话的，换了就白声明了）
        assert await listener.start() == port
    finally:
        listener.close()


async def test_bound_to_loopback_only():
    """🔴 只绑 127.0.0.1：`sockets[0].getsockname()` 必须是回环，且非回环地址连不上。

    依据 `trae-oauth.ts:499-503`：绑所有网卡会让同局域网的别的机器往这个端口
    投递伪造 `?code=`，把攻击者的授权码写进用户凭据。
    """
    listener = _listener(preferred_port=0)
    try:
        port = await listener.start()
        host, bound_port = listener._server.sockets[0].getsockname()[:2]
        assert host == "127.0.0.1" and bound_port == port

        lan_ip = ""
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("127.0.0.1", 1))        # UDP connect 不发包，只让内核选路
            lan_ip = probe.getsockname()[0]
        except OSError:
            pass
        finally:
            probe.close()
        if lan_ip and lan_ip != "127.0.0.1":
            with pytest.raises(OSError):            # 同一端口在非回环地址上不存在
                _s = socket.create_connection((lan_ip, port), timeout=1.0)
                _s.close()
        else:
            pytest.skip("本机没有非回环 IPv4 地址，无法做非回环可达性对照")
    finally:
        listener.close()


async def test_preferred_port_in_use_falls_back_to_another_port():
    """首选端口被别的程序占着 → 回退到**另一个**端口，而不是报错（`trae-oauth.ts:530-543`）。"""
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    occupied = blocker.getsockname()[1]
    listener = _listener(preferred_port=occupied)
    try:
        port = await listener.start()
        assert port != occupied and port >= 10_000
        assert listener.port == port               # 端口以实际绑定值为准
    finally:
        listener.close()
        blocker.close()


async def test_every_allocated_port_is_at_least_10000():
    """随机端口也**不得低于 10000**（`login.ts:339`：低端口会被门户/IdP 拒）。"""
    seen = []
    for _ in range(3):
        listener = _listener(preferred_port=0)
        try:
            seen.append(await listener.start())
        finally:
            listener.close()
    assert all(port >= 10_000 for port in seen), seen


def _occupy_a_low_port() -> int:
    """在 127.0.0.1 上找一个**可绑的低位端口**（用来验"低端口不接受"这条判据）。

    特权端口（<1024）在非 root 下绑不上，绑上了就跳过 —— 该用例的价值在于
    "系统真分配了一个 <10000 的端口时，接收端不用它"，环境不配合就如实 skip。
    """
    for candidate in range(1024, 10_000):
        try:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", candidate))
            return candidate
        except OSError:
            continue
    raise pytest.skip("本机找不到可绑的非特权低位端口，无法构造该场景")


async def test_low_bound_port_is_rejected_and_reallocated():
    """`listen(0)` 拿到低于 10000 的端口时**不采用**：关掉重分配到 ≥10000。"""
    occupied = _occupy_a_low_port()
    listener = _listener(preferred_port=occupied)
    try:
        port = await listener.start()
        assert port != occupied and port >= 10_000, (port, occupied)
    finally:
        listener.close()


# ============ 只服务注册路径 ============

async def test_unknown_path_is_404_and_does_not_touch_the_session():
    """别的路径（含 favicon / 前缀相似的 `/authorizeX`）→ 404，会话**继续等**真回跳。"""
    recorder = Recorder()
    listener = _listener(recorder, secret="S-1", secret_key="state")
    try:
        await listener.start()
        for target in ("/favicon.ico", "/authorizeX?state=S-1", "/?state=S-1", "/auth/callback"):
            response = await _get(listener, target)
            assert response.status_code == 404, target
        assert listener.state == "open" and listener.settled is False
        assert recorder.calls == [], "噪音请求不该被当成回跳"
        # 404 之后真回跳照样受理（"不杀会话"的具体含义）
        ok = await _get(listener, "/authorize?state=S-1&refreshToken=RT")
        assert ok.status_code == 200
        assert len(recorder.calls) == 1
    finally:
        listener.close()


async def test_nested_path_under_the_registered_one_is_served():
    """注册路径的**子段**（`/authorize/x`）按参考实现的 startsWith 口径受理。"""
    recorder = Recorder()
    listener = _listener(recorder, secret="")
    try:
        await listener.start()
        response = await _get(listener, "/authorize/x?refreshToken=RT")
        assert response.status_code == 200
        assert recorder.calls[0].path == "/authorize/x"
    finally:
        listener.close()


async def test_options_preflight_answers_cors_without_consuming_the_session():
    """供应商页面的 CORS 预检：204 + 允许头，**不**跑 handler、**不**落定。"""
    recorder = Recorder()
    listener = _listener(recorder, secret="S-1", secret_key="state")
    try:
        await listener.start()
        response = await _get(listener, "/authorize", method="options")
        assert response.status_code == 204
        assert response.headers["access-control-allow-methods"] == "GET, HEAD, OPTIONS"
        assert response.headers["access-control-allow-origin"] == "*"
        # 🔴 不发 `Allow-Credentials`：回环接收端不接受带凭据的跨源请求
        assert "access-control-allow-credentials" not in response.headers
        assert listener.state == "open" and recorder.calls == []
    finally:
        listener.close()


async def test_origin_is_reflected_on_real_responses():
    """带 `Origin` 的回跳响应反射该源（浏览器才肯读页面），并带 `Vary: Origin`。"""
    listener = _listener(Recorder(), secret="")
    try:
        await listener.start()
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
            response = await client.get(f"http://127.0.0.1:{listener.port}{PATH}?a=1",
                                        headers={"Origin": "https://www.trae.cn"})
        assert response.headers["access-control-allow-origin"] == "https://www.trae.cn"
        assert response.headers["vary"] == "Origin"
    finally:
        listener.close()


# ============ 关联串（state） ============

async def test_wrong_state_is_400_and_keeps_listening():
    """🔴 关联串不符 → **400 且继续监听**（`lobsterai-oauth.ts:276-286`）。

    伪造/过期的一条回跳不该把用户正在进行的登录打死：400 之后真回跳必须还能进来。
    """
    recorder = Recorder()
    listener = _listener(recorder, secret="STATE-1", secret_key="state")
    try:
        await listener.start()
        bad = await _get(listener, "/auth?x=1")  # 先证路径判据在前
        assert bad.status_code == 404
        wrong = await _get(listener, "/authorize?code=C&state=OTHER")
        assert wrong.status_code == 400, wrong.text
        assert "不匹配" in wrong.text and "STATE-1" not in wrong.text, "不许把关联串回显出去"
        assert listener.state == "open" and recorder.calls == []

        # 缺 state（必填）→ 同样 400 且不落定
        missing = await _get(listener, "/authorize?code=C")
        assert missing.status_code == 400 and listener.state == "open"

        # 真回跳随后仍然受理 → 会话没被打死
        good = await _get(listener, "/authorize?code=C&state=STATE-1")
        assert good.status_code == 200 and recorder.calls[0].query["code"] == "C"
    finally:
        listener.close()


async def test_optional_secret_absent_is_handed_to_the_handler():
    """TRAE 口径（`secret_required=False`）：**没带**关联串也放行，交给产品层判据。

    依据 `trae-oauth.ts:67-70`（上游不保证回传）；带回且不一致才拒（400 + 继续监听）。
    """
    recorder = Recorder()
    listener = _listener(recorder, secret="TRACE-1", secret_key="login_trace_id",
                         secret_required=False)
    try:
        await listener.start()
        mismatch = await _get(listener, f"{PATH}?refreshToken=RT&login_trace_id=NOPE")
        assert mismatch.status_code == 400
        assert listener.state == "open" and recorder.calls == []

        absent = await _get(listener, "/authorize?refreshToken=RT")
        assert absent.status_code == 200
        assert recorder.calls[0].url.endswith(f"{PATH}?refreshToken=RT")
    finally:
        listener.close()


async def test_secret_is_read_lazily_from_a_provider():
    """关联串在 `login_start` 之后才生成 → 注册的是**取值函数**，到达时才读。"""
    holder: dict = {}
    recorder = Recorder()
    listener = _listener(recorder, secret=lambda: holder.get("state", ""),
                         secret_key="state")
    try:
        await listener.start()
        # 还没生成关联串时不拦（产品层的 validate 负责后面的判据）
        early = await _get(listener, "/authorize?code=EARLY")
        assert early.status_code == 200 and len(recorder.calls) == 1
        holder["state"] = "STATE-9"
        assert listener.state == "settled:success"
    finally:
        listener.close()


async def test_empty_secret_policy_defers_entirely_to_the_handler():
    """没注册关联串 = 接收端不做关联校验（粘贴兜底/无 state 的产品仍可复用本层）。"""
    recorder = Recorder()
    listener = _listener(recorder, secret="")
    try:
        await listener.start()
        response = await _get(listener, "/authorize?refreshToken=RT")
        assert response.status_code == 200 and len(recorder.calls) == 1
    finally:
        listener.close()


# ============ 落定 / 关闭 / 超时 ============

async def test_success_page_is_real_html_and_then_the_port_is_gone():
    """成功 = 真 HTML 页（「登录完成，可关闭此页」）+ 落定 + 关端口（不再受理第二次）。"""
    recorder = Recorder()
    listener = _listener(recorder, secret="")
    await listener.start()
    port = listener.port
    response = await _get(listener, f"{PATH}?refreshToken=RT-CB")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in response.text and "登录完成，可关闭此页" in response.text
    assert listener.settled and listener.state == "settled:success"

    listener.close()                          # 引擎的出表路径也会关一次（幂等）
    listener.close()
    assert await _refused(port), "落定+关闭后端口必须不再受理（否则就是端口泄漏）"


async def test_timeout_settles_and_closes_without_any_request():
    """🔴 超时**必须**落定并关闭（参考实现的原始缺陷：只 `res.end()` 不落定 →
    界面永远停在「认证中」）。这里没人来请求，也要自己收摊。"""
    settled: list[str] = []
    recorder = Recorder()
    listener = _listener(recorder, secret="", timeout_s=0.2,
                         on_settled=lambda l: settled.append(l.state))
    await listener.start()
    port = listener.port
    await asyncio.sleep(0.45)                 # 等定时器到点（不是等请求）
    assert listener.settled and listener.state == "settled:timeout"
    assert settled == ["settled:timeout"], "引擎得收到落定通知（据此把会话出表）"
    assert recorder.calls == []
    assert await _refused(port)


async def test_invalid_outcome_also_settles_and_closes():
    """handler 判失败（回跳解析不出料）→ 也要 respond + 落定 + 关闭，一条都不能少。"""
    recorder = Recorder(LoginOutcome(state="failed", detail="回跳未携带凭据料"))
    listener = _listener(recorder, secret="")
    await listener.start()
    port = listener.port
    response = await _get(listener, f"{PATH}?nothing=1")
    assert response.status_code == 400 and "回跳未携带凭据料" in response.text
    assert "登录未完成" in response.text
    assert listener.state == "settled:failed:failed"
    assert await _refused(port)


async def test_handler_exception_still_answers_a_page_and_settles():
    """handler 抛未预期异常 → 浏览器拿到可读页面（不是转圈/连接重置），异常记日志。"""
    recorder = Recorder()
    recorder.error = RuntimeError("内部炸了")
    listener = _listener(recorder, secret="")
    await listener.start()
    port = listener.port
    response = await _get(listener, f"{PATH}?a=1")
    assert response.status_code == 400 and "回跳处理失败" in response.text
    assert listener.settled and await _refused(port)


async def test_double_settle_is_impossible_and_the_handler_runs_once():
    """🔴 并发两条回跳（浏览器双发 / 开两个标签）：handler **只跑一次**、只落定一次。

    授权料是一次性的 —— 跑第二次会把已经到手的成功打成 failed（单飞在引擎层，
    本层再加一道"投递闸门"，两条通道都不许重复换 token）。

    现场留一条**只连不发**的连接：`_inflight > 0` 时关闭被推迟（不截断正在写响应
    的连接），于是"已落定但未关端口"这段窗口可以被确定性地测到。
    """
    started = asyncio.Event()

    class Slow(Recorder):
        async def __call__(self, capture):      # type: ignore[override]
            self.calls.append(capture)
            started.set()
            await asyncio.sleep(0.2)             # 模拟 exchange 的耗时
            return LoginOutcome(state="success", detail="登录成功")

    recorder = Slow()
    listener = _listener(recorder, secret="")
    await listener.start()
    port = listener.port
    _holder_reader, holder_writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        first = asyncio.create_task(_get(listener, f"{PATH}?code=A"))
        await started.wait()
        second = await _get(listener, f"{PATH}?code=B")      # 处理中的第二条
        assert second.status_code == 200 and "正在处理" in second.text
        assert (await first).status_code == 200
        assert len(recorder.calls) == 1, "同一次登录不许换两次 token"
        assert listener.state == "settled:success"

        third = await _get(listener, f"{PATH}?code=C")       # 已落定（端口还被在飞连接顶着）
        assert third.status_code == 200 and "登录已完成" in third.text
        assert len(recorder.calls) == 1, "落定后不许再跑 handler"
    finally:
        holder_writer.close()
        await asyncio.sleep(0.05)                # 让最后一条连接的 finally 关端口
    assert await _refused(port), "在飞连接散尽后端口必须释放（否则就是监听泄漏）"


async def test_close_before_any_capture_is_idempotent_and_not_settled():
    """引擎取消（用户关向导）→ `close()` 后端口即释放；`state` 如实说 closed。"""
    listener = _listener(Recorder(), secret="")
    await listener.start()
    port = listener.port
    listener.close()
    listener.close()
    assert listener.settled is False and listener.state == "closed"
    assert await _refused(port)


async def test_arrival_after_cancel_but_before_the_port_dies_gets_an_honest_page():
    """关闭被在飞连接推迟时，迟到的回跳**不许**再灌进已作废的会话 —— 给一句实话。

    （引擎 `_drop` 先出表再关监听；这条窗口里的请求如果继续投递，只会得到
    `expired` 的空转，不如直接告诉用户"登录已结束"。）
    """
    recorder = Recorder()
    listener = _listener(recorder, secret="")
    await listener.start()
    _holder, holder_writer = await asyncio.open_connection("127.0.0.1", listener.port)
    try:
        await asyncio.sleep(0.05)               # 等 accept 回调把这条连接计成在飞
        assert listener._inflight == 1
        listener.close()                        # 取消：关闭被在飞连接推迟（端口还开着）
        page = await _get(listener, f"{PATH}?code=late")
        assert page.status_code == 200 and "本次登录已结束" in page.text
        assert recorder.calls == [], "已取消的会话不得再被投递"
    finally:
        holder_writer.close()


async def test_malformed_and_oversized_requests_are_refused_without_killing_us():
    """畸形请求行（不是 `METHOD TARGET VERSION`）→ 414，会话**不落定**。"""
    listener = _listener(Recorder(), secret="")
    try:
        await listener.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", listener.port)
        writer.write(b"NOT-HTTP\r\n\r\n")
        await writer.drain()
        head = (await asyncio.wait_for(reader.readline(), 2.0)).decode()
        assert "414" in head, head
        while True:                                  # 读到空行为止（吃掉整个响应）
            line = await asyncio.wait_for(reader.readline(), 2.0)
            if line in (b"\r\n", b""):
                break
        writer.close()
        assert listener.state == "open"
        later = await _get(listener, f"{PATH}?x=1")
        assert later.status_code == 200
    finally:
        listener.close()


# ============ 页面与脱敏 ============

async def test_page_escapes_untrusted_detail_text():
    """失败文案里可能带**回跳可控**片段 → 页面必须转义（不许在本机端口上开反射点）。"""
    recorder = Recorder(LoginOutcome(state="failed",
                                     detail='回跳校验未通过：<script>alert("xss")</script>'))
    listener = _listener(recorder, secret="")
    try:
        await listener.start()
        response = await _get(listener, f"{PATH}?x=1")
        assert "<script>" not in response.text and "&lt;script&gt;" in response.text
    finally:
        listener.close()


async def test_logs_and_pages_never_echo_the_captured_url():
    """🔴 捕获到的 URL 里**就是凭据料**：日志只许出路径与查询**键名**。"""
    recorder = Recorder()
    listener = _listener(recorder, secret="")
    try:
        await listener.start()
        await _get(listener, f"{PATH}?refreshToken=SUPER-SECRET&state=S1")
        assert recorder.calls[0].url.endswith(f"{PATH}?refreshToken=SUPER-SECRET&state=S1")
        described = recorder.calls[0]._describe()
        assert "SUPER-SECRET" not in described and "refreshToken" in described
    finally:
        listener.close()


# ============ declared_port 的兜底口径 ============

def test_declared_port_falls_back_to_the_caller_default():
    """没有接收端（直接构造的会话 / 起监听失败）→ 回调用方声明的端口，粘贴兜底照旧。"""
    class _Bare:
        pass

    class _WithPort:
        class callback:                       # duck typing：只读 `.port`
            port = 21211

    assert callback_server.declared_port(_Bare()) == 0
    assert callback_server.declared_port(None, default=18080) == 18080
    assert callback_server.declared_port(_Bare(), default=18080) == 18080
    assert callback_server.declared_port(_WithPort(), default=18080) == 21211


def test_listener_rejects_a_relative_path():
    """注册路径必须是绝对路径：相对路径会让"只服务这一条"的判据形同虚设。"""
    with pytest.raises(ValueError, match="绝对路径"):
        CallbackListener(path="authorize", handler=Recorder())
