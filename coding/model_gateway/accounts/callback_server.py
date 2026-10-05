"""会话级**本机回跳接收端**（loopback callback listener，需求 BD4）。

## 为什么必须有它（事故口径，别再写成"已实现"）

`local_callback` 型产品（trae / lobsterai）的登录页**以回跳结束**：浏览器被 302 到
`http://127.0.0.1:{port}/{path}?…凭据料…`。此前网关**只构造这个地址、从不监听它**
（实测：全包 `grep HTTPServer|socketserver|listen(|bind(` 零监听器；
`GET 127.0.0.1:18080/authorize` → connection refused；
`GET 127.0.0.1:8300/auth/callback` → 404），于是那两个产品只能靠人把地址栏整串粘回文本框。
本模块补的就是这条**投递通道**：真 URL → 真到达 → 交给**既有**校验/换凭据代码。

🔴 接收端**不做**任何凭据交换：它只做「绑定 → 收 URL → 交给调用方的异步 handler →
落定 → 关闭」。校验与换 token 一律复用产品层
（`upstream/trae/login.py::validate_callback` / `login_callback`、
`upstream/lobsterai/login.py::callback_code_state` / `exchange`）——
粘贴兜底与本通道**同一 handler、不同投递方式**，判据不会分叉。

## 逐条对齐参考实现（DSH，只读取证）

| 参考 | 本模块的落点 |
|---|---|
| `trae-oauth.ts:40` 首选端口 18080 | `preferred_port`（trae 传它；其余产品 0 = 随机） |
| `:499-503` **只绑 127.0.0.1**（"绑所有网卡会让同局域网机器投递伪造 ?code="） | `_HOST` 写死回环，无参数可改 |
| `:530-543` `EADDRINUSE`/`EACCES` → 回退 `listen(0)` | `_bind()` 的候选端口序列 |
| `:680-693` 登录 URL 用**实际**端口重建 | `start()` 先绑定、`port` 之后才可读（产品层据此拼 URL） |
| `:622,731` 只服务 `/authorize*`，其它 404 | `_path_matches()` + 噪音计数（404 **不**落定） |
| `:631-643`/`:739-748` **每个分支**都要 clearTimeout + respond + close + settle（原缺陷：`res.end()` 后直接 return，界面永远停在「认证中」） | `_settle()` 是唯一落定点：成功/无效/超时三条路径都经它 |
| `lobsterai-oauth.ts:95-97` 门户校验 `redirect_uri` 形状 `http://127.0.0.1:{port}/auth/callback` | 随机端口可以，**形状不可以** → 恒用 `_HOST` + 路径常量 |
| `:256-287` 前缀匹配否则 404；**`state` 不符 → 400 且继续监听** | `_correlation_problem()` + `secret_required` |
| `:276-286` exchange 在请求处理器**内部**完成，成功才回 200「登录成功」页 | `_serve_one()` 里 `await handler(capture)` 后才写页面 |
| `:348` `listen(0,'127.0.0.1')` | 同上（回退分支） |
| `codearts login.ts:339` 低端口被 IdP 拒 → 端口下限 10000 | `_MIN_CALLBACK_PORT` + `_BIND_RETRIES` |

## 端口口径（用户已裁决，不再讨论）

trae 首选 **18080**、拿不到就退系统分配；其余产品一律**随机 ≥10000**；
**任何情况下只绑 127.0.0.1**。绑定失败**不**让登录起不来：引擎记一条 warning，
`declared_port()` 回退到产品声明的端口 → 粘贴兜底照常可用（诚实降级，不是假成功）。

## 生命周期（与 `accounts/login.py` 的会话纪律同轴）

`start()` 绑定并起超时定时器（时长 = 会话 TTL）→ 期间只服务注册路径 →
**任一**终态（成功 / 无效 / 超时 / 引擎取消）都经 `_settle()`：取消定时器、
`server.close()`、通知引擎出表。`close()` 幂等，且**不截断在飞连接**的响应
（落定发生在处理器 `await` 期间时，监听套接字由最后一个连接负责关）。
"""

from __future__ import annotations

import asyncio
import html
import logging
import random
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import parse_qsl, urlsplit

from model_gateway.accounts.types import LoginOutcome

logger = logging.getLogger("model_gateway.accounts")

#: **只绑回环**：本机浏览器才可能投递这个回跳（`trae-oauth.ts:499-503` 的教训）。
#: 私有常量、无入口参数 —— 暴露成配置项就等于允许有人把它绑到 0.0.0.0。
_HOST = "127.0.0.1"
#: 端口下限（`login.ts:339,341`：门户/IdP 会拒低端口，随机端口必须 ≥10000）。
_MIN_CALLBACK_PORT = 10_000
#: 回退重试轮次：首选 → 系统分配 → 显式随机高位端口（每轮各试一次）。
_BIND_RETRIES = 6
#: 单行读超时：慢速/半开客户端不许把接收端的连接槽挂住（回跳是浏览器 302，正常远快于此）。
_READ_TIMEOUT_S = 5.0
#: 请求行/头上限（字节）：TRAE 回调带 `userInfo`/`userJwt` 两段 JSON，比常规 URL 长。
_REQUEST_MAX_BYTES = 256 * 1024
#: 缺省等待时长（秒）——调用方**必须**按会话 TTL 覆盖它（引擎传 `session.ttl_s`）。
DEFAULT_TIMEOUT_S = 600.0

#: 落定原因（进日志与 `state`，**不进**回给浏览器的页面文案 —— 页面只说用户听得懂的话）
REASON_SUCCESS = "success"
REASON_TIMEOUT = "timeout"

_STATUS_REASONS = {200: "OK", 204: "No Content", 400: "Bad Request",
                   404: "Not Found", 414: "URI Too Long"}


@dataclass(frozen=True)
class CallbackCapture:
    """一次**真实到达**的回跳（接收端交给 handler 的全部事实）。

    🔴 `url` 是**完整可解析的回跳地址**（`http://127.0.0.1:{实际端口}{原始 target}`），
       与用户从地址栏粘回来的串**同形** → 产品层既有的解析器直接可用
       （`trae/protocol.py::callback_params` / `lobsterai/login.py::callback_code_state`），
       不需要为本通道另写一套解析。
    ⚠️ `url` 里**就是凭据料**（refreshToken / code）：绝不写进日志、绝不回显界面；
       日志只记路径 + 查询**键名**（`_describe()`）。
    """

    url: str
    path: str
    method: str
    #: 百分号解码后的查询参数（同键多值取首个，与产品层 `parse_qs(...)[0]` 口径一致）
    query: dict[str, str] = field(default_factory=dict)
    #: 原始（未解码）查询串：TRAE 的 `userInfo` 存在**双重编码**，产品层要拿原文再解一层
    raw_query: str = ""

    def _describe(self) -> str:
        """**脱敏**描述（只出路径与键名，永不出值）。"""
        return f"{self.method} {self.path}?{'&'.join(sorted(self.query))}"


class CallbackListener:
    """一个登录会话一条回环监听（`asyncio.start_server`，零新依赖、零第三方 HTTP 库）。

    用法（引擎侧）::

        listener = CallbackListener(path="/authorize", handler=deliver, secret=…,
                                    secret_key="login_trace_id", secret_required=False,
                                    preferred_port=18080, timeout_s=session.ttl_s,
                                    on_settled=drop_session)
        port = await listener.start()          # 先绑定，端口之后才写进授权 URL
        …                                       # 浏览器回跳 → handler → 落定 → 自动关闭
        listener.close()                        # 取消/终态时兜底（幂等）
    """

    def __init__(self, *, path: str,
                 handler: Callable[[CallbackCapture], Awaitable[LoginOutcome | None]],
                 secret: str | Callable[[], str] = "",
                 secret_key: str = "state",
                 secret_required: bool = True,
                 preferred_port: int = 0,
                 timeout_s: float = DEFAULT_TIMEOUT_S,
                 on_settled: Callable[["CallbackListener"], None] | None = None) -> None:
        if not path.startswith("/"):
            raise ValueError(f"回调路径必须是绝对路径（以 / 开头）：{path!r}")
        self._path = path
        self._handler = handler
        self._secret = secret
        self._secret_key = secret_key
        self._secret_required = bool(secret_required)
        self._preferred_port = int(preferred_port or 0)
        self._timeout_s = float(timeout_s)
        self._on_settled = on_settled

        self._server: asyncio.Server | None = None
        self._port = 0
        self._timer: asyncio.TimerHandle | None = None
        self._inflight = 0            #: 正在处理的连接数（>0 时推迟 `server.close()`）
        self._settled = False
        self._reason = ""
        self._closed = False
        self._delivering = False      #: 已有一次投递在 `await` 里（防并发重复换 token）
        self._noise = 0               #: 404/噪音计数（诚实可查：证明"有别的程序在敲门"）

    # —— 对外 ——

    async def start(self) -> int:
        """绑定并返回**实际**端口（幂等：已绑过则直接回原值）。

        🔴 顺序是硬要求：**先绑定、后拼授权 URL**（`trae-oauth.ts:680-693`）——
           首选端口被占用时授权 URL 里写的是回退后的端口，否则回跳必然打到别人家。
        """
        if self._port:
            return self._port
        self._server, self._port = await self._bind()
        loop = asyncio.get_running_loop()
        self._timer = loop.call_later(self._timeout_s, self._on_timeout)
        logger.info("回调接收端已就绪：%s（路径 %s，等待 %.0fs，关联参数 %s%s）",
                    self.url, self._path, self._timeout_s, self._secret_key,
                    "" if self._secret_required else "/可选")
        return self._port

    @property
    def port(self) -> int:
        """实际监听端口（**未 start 或未成功 = 0**；产品层经 `declared_port()` 取用）。"""
        return self._port

    @property
    def url(self) -> str:
        """对外声明的回跳地址（门户校验的就是这个形状，`lobsterai-oauth.ts:95-97`）。"""
        return f"http://{_HOST}:{self._port}{self._path}"

    @property
    def settled(self) -> bool:
        """是否已落定（成功/无效/超时/关闭都算，落定后不再受理任何投递）。"""
        return self._settled

    @property
    def state(self) -> str:
        """可读状态（入口层/日志用）：`open` | `settled:<reason>` | `closed`。"""
        if self._settled:
            return f"settled:{self._reason}"
        return "closed" if self._closed else "open"

    def close(self) -> None:
        """**幂等**关闭：取消定时器 + 关监听（在飞连接的响应写完再关，不截断页面）。"""
        if self._closed:
            return
        self._closed = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._close_server()

    # —— 绑定 ——

    async def _bind(self) -> tuple[asyncio.Server, int]:
        """按端口策略绑定 127.0.0.1：首选 → 系统分配 → 显式随机高位端口。

        `EADDRINUSE`/`EACCES` 属**可恢复**（`trae-oauth.ts:530-543` 只对这两类回退；
        别的 OSError 说明机器有问题，重试也不会有结果）→ 继续试下一个候选。
        拿到的端口 < 10000 时**不采用**（低端口被门户拒，`login.ts:339`）：关掉再试。
        """
        candidates = [self._preferred_port] if self._preferred_port > 0 else []
        candidates.append(0)
        last: BaseException | None = None
        for _ in range(_BIND_RETRIES):
            for wanted in candidates:
                try:
                    server = await asyncio.start_server(
                        self._serve, _HOST, wanted, limit=_REQUEST_MAX_BYTES)
                except OSError as e:                       # EADDRINUSE / EACCES / …
                    last = e
                    continue
                port = int(server.sockets[0].getsockname()[1])
                if port >= _MIN_CALLBACK_PORT:
                    return server, port
                last = OSError(f"端口 {port} 低于门户下限 {_MIN_CALLBACK_PORT}")
                _shutdown_server(server)
            candidates = [random.randint(_MIN_CALLBACK_PORT, 65_535)]
        raise OSError(
            f"回调接收端无法在 127.0.0.1 上监听（首选端口 {self._preferred_port or '（无）'}，"
            f"已试 {_BIND_RETRIES} 轮）：{last}")

    # —— 连接处理 ——

    async def _serve(self, reader: asyncio.StreamReader,
                     writer: asyncio.StreamWriter) -> None:
        """一条连接：读完请求 → 路由 → 写响应 → 收摊（任何异常都不许掀掉会话）。"""
        self._inflight += 1
        try:
            await self._serve_one(reader, writer)
        except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError):
            pass                                          # 半开/提前断开的浏览器连接：忽略
        except Exception:                                   # noqa: BLE001 — 接收端不因脏连接崩
            logger.exception("回调接收端处理连接时异常（已忽略，不影响会话）")
        finally:
            self._inflight -= 1
            try:
                writer.close()
            except Exception:                               # noqa: BLE001
                pass
            if self._closed or self._settled:
                self._close_server()

    async def _serve_one(self, reader: asyncio.StreamReader,
                         writer: asyncio.StreamWriter) -> None:
        """路由与响应（只服务注册路径；其余噪音 404 且**不落定**）。"""
        request_line = await asyncio.wait_for(reader.readline(), _READ_TIMEOUT_S)
        if not request_line:
            return
        origin = ""
        try:
            method, target = _parse_request_line(request_line)
            origin = await self._drain_headers(reader)
        except ValueError:                                  # 畸形请求行 / 超长请求行
            await _send(writer, 414, _page("回跳地址无法解析",
                                           "请求过长或格式非法，本接收端未受理（会话未受影响）。"),
                         origin=origin)
            return

        split = urlsplit(target)
        path = split.path or "/"
        if method == "OPTIONS":
            # 供应商页面可能先发 CORS 预检；预检**不消耗**会话（204 + CORS 头）
            await _send(writer, 204, None, origin=origin)
            return
        if not _path_matches(path, self._path):
            self._noise += 1                               # favicon/扫描器/别的程序
            await _send(writer, 404, _page("无关请求",
                                           "这里不是该请求要找的地址（会话仍在等待）。"),
                        origin=origin)
            return
        if self._delivering:
            await _send(writer, 200, _page("本次回跳正在处理",
                                           "请勿重复刷新；处理结果会写在第一次打开的页面上。"),
                        origin=origin)
            return
        if self._settled:
            await _send(writer, 200, _page("登录已完成",
                                           "本次登录已经处理完毕，可以关闭此页面。"
                                           "若需要再次登录，请回到「接入账号资源」重新发起。"),
                        origin=origin)
            return
        if self._closed:
            # 会话已取消/出表，只是关闭被在飞连接推迟了一拍（`_close_server`）：
            # 不许再把回跳灌进一条已经作废的会话，给浏览器一句实话即可。
            await _send(writer, 200, _page("本次登录已结束",
                                           "接收端已关闭（会话被取消或已出表），"
                                           "请回到「接入账号资源」重新发起登录。"),
                        origin=origin)
            return

        query = dict(parse_qsl(split.query, keep_blank_values=True))
        capture = CallbackCapture(url=f"http://{_HOST}:{self._port}{target}",
                                  path=path, method=method, query=query,
                                  raw_query=split.query or "")
        problem = self._correlation_problem(capture)
        if problem:
            # 🔴 关联串不符 → 400 且**继续监听**（`lobsterai-oauth.ts:276-286`）：
            #    一条伪造/过期的回跳不该把用户正在进行的登录打死。
            logger.warning("回调接收端拒绝一条回跳（不落定，继续等待）：%s", capture._describe())
            await _send(writer, 400, _page("回跳与本次登录不匹配", problem), origin=origin)
            return

        self._delivering = True
        outcome = await self._deliver(capture)
        self._delivering = False
        ok = outcome.state == "success"
        await _send(writer, 200 if ok else 400,
                    _page("登录完成，可关闭此页" if ok else "登录未完成",
                          outcome.detail or ("已收到授权，凭据已写入本机账号目录。"
                                             if ok else "请回到「接入账号资源」页重新发起登录。")),
                    origin=origin)
        self._settle(REASON_SUCCESS if ok else f"failed:{outcome.state}")

    async def _drain_headers(self, reader: asyncio.StreamReader) -> str:
        """读完请求头（只为拿 `Origin` 回 CORS；**不消费请求体** —— 回跳只有 query）。

        返回 `Origin`（没有则空串）。头部行数不设硬上限但受整次读超时约束
        （`_READ_TIMEOUT_S`），慢速客户端只会在超时后被判噪音。
        """
        origin = ""
        while True:
            line = await asyncio.wait_for(reader.readline(), _READ_TIMEOUT_S)
            if line in (b"\r\n", b"\n", b""):
                return origin
            name, _, value = line.decode("latin-1", "replace").partition(":")
            if name.strip().lower() == "origin" and not origin:
                origin = value.strip()

    async def _deliver(self, capture: CallbackCapture) -> LoginOutcome:
        """把**原始回跳地址**交给调用方的异步 handler（引擎 → 产品既有校验/换凭据路径）。

        handler 抛异常 = 未预期故障：这里折叠成可读的 `failed` 结局并**记异常日志**，
        因为此刻正踩着一条浏览器连接 —— 不给它一个页面，用户看到的就是"一直转圈"
        （参考实现的原始缺陷：`res.end()` 之后 return，Promise 永不落定）。
        """
        logger.info("回调接收端收到回跳：%s", capture._describe())
        try:
            outcome = await self._handler(capture)
        except Exception as e:                               # noqa: BLE001
            logger.exception("回调处理器异常（产品层/引擎）")
            return LoginOutcome(state="failed",
                                detail=f"回跳处理失败（{type(e).__name__}），"
                                       f"请回到「接入账号资源」页重新发起登录")
        if not isinstance(outcome, LoginOutcome):
            logger.error("回调处理器返回类型异常：%s", type(outcome).__name__)
            return LoginOutcome(state="failed",
                                detail=f"回跳处理失败（处理器返回 {type(outcome).__name__}）")
        return outcome

    # —— 关联校验与落定 ——

    def _expected_secret(self) -> str:
        """本次会话的关联串（可以是常量，也可以是**取值函数** —— 会话态在
        `login_start` 之后才生成，绑定时读不到，故在到达时才读）。"""
        secret = self._secret
        return str(secret() if callable(secret) else (secret or ""))

    def _correlation_problem(self, capture: CallbackCapture) -> str:
        """回跳关联校验（返回失败原因，空串 = 放行）。

        三档语义（对齐两家参考实现，且**不**在此处做产品级凭据校验）：
        - 会话还没生成关联串 → 放行（交给产品层的 `validate_callback`，避免"两把闸互相等"）；
        - 带来了但不一致 → 拒绝（伪造/串线/过期）；
        - 没带：`secret_required` 才拒（lobsterai 的 `state` 恒回传），
          否则放行（TRAE 不保证回传 `login_trace_id`，`trae-oauth.ts:67-70`）。
        """
        expected = self._expected_secret()
        if not expected:
            return ""
        got = str(capture.query.get(self._secret_key) or "")
        if not got:
            return (f"回跳缺少 {self._secret_key} 参数，无法确认是本次登录" if self._secret_required
                    else "")
        if got != expected:
            return f"回跳与本次登录不匹配（{self._secret_key} 不一致），已拒绝"
        return ""

    def _settle(self, reason: str) -> None:
        """**唯一落定点**：成功 / 无效 / 超时三条路径都走这里（`trae-oauth.ts:631-643`）。

        落定 = 取消定时器 + 关闭监听 + 通知引擎出表，且**只发生一次**
        （重复落定直接返回 —— 双投递/落定后再取消都不可能有第二次副作用）。
        """
        if self._settled:
            return
        self._settled = True
        self._reason = reason
        self.close()
        logger.info("回调接收端已落定（%s）：%s（噪音请求 %d 次）",
                    reason, self.url, self._noise)
        if self._on_settled is not None:
            try:
                self._on_settled(self)
            except Exception:                                # noqa: BLE001 — 通知失败不许拖垮监听
                logger.exception("回调接收端的落定通知异常（会话状态由 TTL 兜底）")

    def _on_timeout(self) -> None:
        """TTL 到点：**必须**落定并关闭（否则界面永远停在「认证中」）。"""
        if self._settled:
            return
        self._settle(REASON_TIMEOUT)

    def _close_server(self) -> None:
        """关监听套接字；有在飞连接时**推迟**到最后一个连接收摊（保住已写的响应）。

        CPython 3.12.13 实测 `Server.close()` **不**取消在飞 handler（探针：handler 里
        先 `close()` 再写响应，客户端仍收全 5 字节正文），但不把正确性押在该语义上：
        连接计数归零时 `CallbackListener._serve` 的 `finally` 会再调一次本函数。
        """
        if self._server is None or self._inflight > 0:
            return
        server, self._server = self._server, None
        _shutdown_server(server)


def _parse_request_line(request_line: bytes) -> tuple[str, str]:
    """`b"GET /authorize?a=1 HTTP/1.1\\r\\n"` → `("GET", "/authorize?a=1")`。

    请求行按 latin-1 解（HTTP 头是字节透明；百分号编码的 UTF-8 在 query 里，
    由 `urlsplit`/`parse_qsl` 负责解码）。畸形（不足两段）→ `ValueError`。
    """
    parts = request_line.decode("latin-1", "replace").split()
    if len(parts) < 2:
        raise ValueError(f"请求行无法解析：{parts!r}")
    return parts[0].upper(), parts[1]


def _path_matches(path: str, expected: str) -> bool:
    """路径命中判定：**精确**或"注册路径 + `/` 子段"（参考实现的 `startsWith`
    会把 `/authorizeXYZ` 也算进来 —— 那是更宽的面，本层收窄）。"""
    return path == expected or path.startswith(expected.rstrip("/") + "/")


def _shutdown_server(server: asyncio.Server) -> None:
    """关监听套接字（`server.close()` 是同步的；不等 `wait_closed()` ——
    3.12 上它可能在半开连接上长挂，而我们只需要端口立刻不再受理新连接）。"""
    try:
        server.close()
    except Exception:                                       # noqa: BLE001
        logger.debug("回调接收端关闭监听时异常（已忽略）", exc_info=True)


async def _send(writer: asyncio.StreamWriter, status: int, body: str | None, *,
                origin: str = "") -> None:
    """写出一个**最小 HTTP/1.1 响应**（`Connection: close` + CORS 头）并 flush。

    🔴 CORS：供应商页面可能对本地回跳发预检/跨源请求，故必须回 CORS 头。
       `Access-Control-Allow-Credentials` **刻意不发** —— 回环接收端不接受第三方
       带凭据的请求，任何源都只能读到这一个页面（`trae-oauth.ts` / `login.ts` 的
       `CORS_HEADERS` 同款取舍）。`origin` 存在就**反射**它（`*` 与凭据型请求不兼容），
       并带 `Vary: Origin`。
    ⚠️ `await drain()` 是必要的：落定发生在响应之后，缓冲区没排空就关监听会把
       用户看到的页面截成"连接被重置"。
    """
    payload = (body or "").encode("utf-8")
    allow = origin or "*"
    lines = [
        f"HTTP/1.1 {status} {_STATUS_REASONS.get(status, 'OK')}",
        "Connection: close",
        "Cache-Control: no-store",
        f"Access-Control-Allow-Origin: {allow}",
        "Access-Control-Allow-Methods: GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers: content-type",
        "Access-Control-Max-Age: 600",
        "Vary: Origin",
    ]
    if body is not None:
        # 204 按 RFC 不带实体，也不写 Content-Length（写了会被某些客户端当成畸形）
        lines.insert(1, "Content-Type: text/html; charset=utf-8")
        lines.insert(2, f"Content-Length: {len(payload)}")
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
    writer.write(head + (payload if body is not None else b""))
    await writer.drain()


#: 完成页样式：**极简**（无外链资源：接收端不该去拉 CDN，铁律 1「纯本地」）
_PAGE_TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>{title}</title><style>
html{{--bg:#fff;--fg:#171b22;--muted:#5b6472;--line:#eef1f3}}
@media (prefers-color-scheme:dark){{html{{--bg:#171b22;--fg:#f5f6f7;--muted:#a4abb5;--line:#252a33}}}}
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);
color:var(--fg);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",
"PingFang SC","Microsoft YaHei",sans-serif}}
.card{{max-width:520px;padding:32px 28px;border:1px solid var(--line);border-radius:14px}}
h1{{margin:0 0 10px;font-size:20px;font-weight:600}}
p{{margin:0;color:var(--muted)}}
</style></head><body><div class="card"><h1>{title}</h1><p>{message}</p></div></body></html>
"""


def _page(title: str, message: str) -> str:
    """给浏览器的**真实页面**（成功/失败都有正文，绝不把用户丢在错误页上抄地址）。

    🔴 一律 `html.escape`：`message` 里可能出现供应商回跳带回来的路径/主机等
       **攻击者可控**片段（校验文案就带这些），不转义等于在本机端口上开一个反射点。
    """
    return _PAGE_TEMPLATE.format(title=html.escape(title, quote=True),
                                 message=html.escape(message, quote=True))


def declared_port(session, *, default: int = 0) -> int:
    """本会话回跳接收端的**实际**端口（产品层拼授权 URL 用）。

    `default` 用于两种"没有接收端"的场景（**都必须继续可用**）：
    ① 直接构造的会话 / 引擎起监听失败 → 回退到产品声明的端口，粘贴兜底照常；
    ② 尚无接收端（未 start）→ 0/默认值，调用方按未就绪处理。
    """
    listener = getattr(session, "callback", None)
    port = int(getattr(listener, "port", 0) or 0)
    return port or int(default or 0)
