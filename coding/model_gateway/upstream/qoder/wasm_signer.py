"""Qoder 加密端点的 **WASM 签名器**（`out.SIGNER_FACTORY` 的生产实现）。

## 这块代码从哪儿来、不是什么

Qoder 的真实推理不走公开 OpenAI 兼容端点，而走 `api2.qoder.sh/algo/api/v2/service/
pro/sse/agent_chat_generation`：请求体要**加密**、`Authorization` 要**客户端 WASM 现签**
（`Bearer COSY.<载荷>.<签名>`）。签名算法在客户端自带的 `qoder-auth-wasm.wasm`（292 KB）里，
Python 侧没有 wasm 运行时 ⇒ 本模块**不重造密码学**，而是把客户端自带的 wasm 放进一个
**本机 Node 子进程**里跑（`qoder_bridge.mjs`，我方代码），拿它的产物：

| 面 | 主人 | 说明 |
|---|---|---|
| 明文请求体（`messages`/`tools`/`business`/目录 key…） | **本仓 `ask.py`** | 有 pytest；本桥只送它产出的那一份 |
| 加密 + COSY 签名 + 头 | **外部 wasm（运行时读取）** | 二进制**不入库**，只按路径读（铁律 1） |
| 信封 SSE 解包 | 本仓 `envelope.py` | 与签名无关，早已就位 |

## 外部依赖是「路径」而不是「仓库内容」

`MGW_QODER_WASM_GLUE` 指向一个**目录**，里面必须有 `qoder-wasm.js`（wasm-bindgen 桥）
与 `qoder-auth-wasm.wasm`。本机安装 Qoder 客户端、或任何一处已构建好的同形状产物都可以。
未设置 / 文件缺失 / 没有 `node` ⇒ `build_factory()` 返回 `None`，`out.SIGNER_FACTORY`
保持未注入 ⇒ 行为与接线前**逐字节一致**（请求前当场 fail closed，回 `NOT_WIRED_HINT`）。

🔴 **三条不解的边界**（写在这里以免被后来者当成"顺手就能补"）：

1. **不下载**：本模块永不联网取 wasm（铁律 1「无远程更新」）；
2. **不入库**：`*.wasm` 与第三方 `qoder-wasm.js` 一律不进仓库（根 `.gitignore` 已真加规则；
   先前这句写作"亦钉"时并**未核验过**，R2 实测 `git check-ignore` rc=1 后补的规则）；
3. **不改形状**：wasm 产物形状不认识就报错并说明缺哪个符号，绝不猜、绝不退回
   "让上游自己拼明文"（那等于把请求形态交给外部依赖，本仓的判据就成了一份没人测的副本）。

## 凭据

`uid` / `security_oauth_token` / `machine_id` 全部来自账号目录自己的凭据与 `meta.json`
（`flow.build_credentials` 写入），本模块**只在子进程 stdin 上 transient 传一次**，
不进日志、不进错误文案（`_scrub` 逐值剔除）；缺任何一项 ⇒ 可读失败，不伪造。
"""

from __future__ import annotations

import asyncio
import collections
import hashlib
import contextlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from model_gateway.core.errors import UpstreamError
from model_gateway.upstream.qoder.out import SignedRequest

#: 环境变量名（唯一配置面；值 = 含 `qoder-wasm.js` + `qoder-auth-wasm.wasm` 的目录）
GLUE_ENV = "MGW_QODER_WASM_GLUE"
#: 可选：node 可执行文件覆盖（默认 `PATH` 里的 `node`，再退 `/usr/local/bin/node`）
NODE_ENV = "MGW_QODER_NODE_BIN"
#: wasm 桥脚本（随本包分发，是我方代码，不含第三方产物）
BRIDGE_JS = Path(__file__).with_name("qoder_bridge.mjs")
#: 一次签名往返的等待上限（纯本地计算；超时 = 子进程异常，不是"上游慢"）
SIGN_TIMEOUT = 20.0
#: 协议帧的行上限。🔴 不能用 asyncio 默认的 64 KiB（`StreamReader` 超限直接
#: `ValueError: Separator is not found, and chunk exceed the limit` —— 已实测复现）：
#: 一帧里装的是**整份加密请求体**（含完整历史 + 工具 schema），真实 agent 会话轻松超 64 KB，
#: 一旦撑爆就是"读任务静默死亡 → 全部等待者挂 20 秒 → 每次请求再新起一个 node 进程"。
#: 4 MiB = 明文体量的实际上限之上（网关侧还有上下文承载校验挡在前面）。
BRIDGE_LINE_LIMIT = 4 * 1024 * 1024
#: 回显给用户的子进程 stderr 行数（排障用；已脱敏）
STDERR_TAIL = 6

#: 签名器工厂的类型（契约本体写在 `out.py` 模块头）
SignerLike = Callable[..., Callable[[dict], Any]]

_GLUE_FILES = ("qoder-wasm.js", "qoder-auth-wasm.wasm")


def resolve_glue_dir(env: dict[str, str] | None = None) -> tuple[Path | None, str]:
    """解析 wasm 桥目录 → `(目录 | None, 一句话原因)`；None = 不可用（原因给界面/日志）。

    只判「路径在册 + 两个文件在位」，不 import、不执行 —— 真正的启动发生在第一次签名时。
    """
    raw = (os.environ if env is None else env).get(GLUE_ENV, "").strip()
    if not raw:
        return None, f"未设置 {GLUE_ENV}（qoder 加密端点需要本机客户端的 wasm 桥）"
    p = Path(raw).expanduser()
    if not p.is_dir():
        return None, f"{GLUE_ENV} 指向的目录不存在：{p}"
    missing = [f for f in _GLUE_FILES if not (p / f).is_file()]
    if missing:
        return None, f"{GLUE_ENV} 目录缺少 {'、'.join(missing)}：{p}"
    return p, ""


def resolve_node(env: dict[str, str] | None = None) -> str | None:
    e = os.environ if env is None else env
    override = (e.get(NODE_ENV) or "").strip()
    if override:
        return override if Path(override).is_file() else None
    return shutil.which("node") or ("/usr/local/bin/node"
                                    if Path("/usr/local/bin/node").is_file() else None)


class Bridge:
    """一个常驻 Node 子进程 + NDJSON 往返（多账号共用，按 `accountKey` 各留一份上下文）。

    为什么要常驻：`QoderContext` 的构造代价在 wasm 里（一账号一份，官方口径同此），
    且每次请求重起 node + 重实例化 292 KB 模块会把一次签名变成一次冷启动。
    """

    def __init__(self, glue_dir: Path, node_bin: str) -> None:
        self.glue_dir = glue_dir
        self.node_bin = node_bin
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._seq = 0
        self._lock = asyncio.Lock()
        self._stderr_task: asyncio.Task | None = None
        #: 绑定事件循环：热重载/测试换 loop 时不能把旧循环的 task 带过去
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stderr: collections.deque[str] = collections.deque(maxlen=STDERR_TAIL)

    # —— 生命周期 ——

    def _alive(self) -> bool:
        return (self._proc is not None and self._proc.returncode is None
                and self._reader is not None and not self._reader.done())

    async def _ensure(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is not loop:                       # 换了循环：旧进程/任务一概不带过去
            await self._teardown()
        if self._alive():
            return
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self.node_bin, str(BRIDGE_JS), "--glue", str(self.glue_dir),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, limit=BRIDGE_LINE_LIMIT)
        except OSError as e:                             # node 不见了 / 不可执行
            raise UpstreamError(f"qoder 签名器起不动（{type(e).__name__}: {e}）",
                                no_failover=True) from e
        self._loop = loop
        self._pending.clear()
        self._reader = loop.create_task(self._pump())
        self._stderr_task = loop.create_task(self._drain_stderr(self._proc))

    async def _teardown(self) -> None:
        """收尾三件缺一不可（漏掉第三件 = `RuntimeError: Event loop is closed` 的孤儿任务）。

        🔴 只在**同一个循环**里 cancel：换了循环时旧 task 属于已关闭的循环，
        从新循环 cancel 它们是未定义行为 —— 那种情况下只把进程杀掉（信号是同步的），
        旧 task 随旧循环一起消失。
        """
        same_loop = self._loop is asyncio.get_running_loop()
        if same_loop:
            for task in (self._reader, self._stderr_task):
                if task is not None and not task.done():
                    task.cancel()
        self._reader = None
        self._stderr_task = None
        proc = self._proc
        if proc is not None and proc.returncode is None:
            proc.kill()
            if same_loop:
                # 等它真的退：不等的话解释器收尾时才回收子进程，
                # 测试里表现为"上一用例的桥在下一用例的循环上说话"。
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
        self._proc = None
        self._loop = None

    async def close(self) -> None:
        await self._teardown()

    async def _pump(self) -> None:
        """读 stdout 帧、按 id 派发。**协议帧之外的一律丢弃**（桥已把 console.log 改道）。

        🔴 整个循环包在 try 里：`readline()` 会因超限/半帧抛 `ValueError`，
        而 `int(frame["id"])` 会因桥自己的异常帧（`{"id": null}`）抛 `TypeError`。
        当年不设这道兜底的后果是**任务静默死亡**：pending 全挂到超时、错误文案把
        "我们的读循环崩了"说成"桥无响应"，排查方向从第一步就错（R1 B-1）。
        """
        proc = self._proc
        cause = ""
        try:
            assert proc is not None and proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    frame = json.loads(line)
                except json.JSONDecodeError:
                    continue
                fid = frame.get("id")
                fut = self._pending.pop(fid, None) if isinstance(fid, int) else None
                if fut is None or fut.done():
                    continue
                fut.set_result(frame)
        except Exception as e:                                    # noqa: BLE001
            cause = f"读循环异常 {type(e).__name__}: {e}"
        else:
            cause = "签名桥已退出"
        # 所有等待者一律可读写死（绝不静默悬挂）：崩溃原因 + stderr 尾巴一起给出
        err = UpstreamError(f"qoder {cause}（{self._stderr_tail()}）", no_failover=True)
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(err)
        self._pending.clear()
        # 🔴 三条收尾一件不落：桥可能还活着（异常路径下 stdout 没 EOF 也会走到这里），
        # 不 kill 就泄漏一个常驻 node 进程；`_loop` 不清零则下一次 `_ensure()` 认为
        # "同一个循环不用 teardown"，直接覆盖 `_proc` —— 旧进程从此没人管。
        if proc is not None and proc.returncode is None:
            proc.kill()
        self._proc = None
        self._loop = None

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> None:
        if proc.stderr is None:
            return
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            self._stderr.append(line.decode("utf-8", "replace").rstrip()[:300])

    def _stderr_tail(self) -> str:
        return " | ".join(str(x) for x in list(self._stderr)[-2:]) or "无 stderr 输出"

    # —— 一次往返 ——

    async def request(self, payload: dict, secrets: tuple[str, ...] = ()) -> dict:
        async with self._lock:                    # 只在"写+登记"这段互斥；等待可并发
            await self._ensure()
            proc = self._proc
            if proc is None or proc.stdin is None:
                raise UpstreamError("qoder 签名桥未就绪", no_failover=True)
            self._seq += 1
            rid = self._seq
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._pending[rid] = fut
            proc.stdin.write((json.dumps({"id": rid, **payload}) + "\n").encode())
            await proc.stdin.drain()
        try:
            frame = await asyncio.wait_for(fut, SIGN_TIMEOUT)
        except UpstreamError as e:
            # 读循环/退出面的文案里带着**子进程 stderr 原文**，而 stderr 不是我们的地盘
            # （R2 B-3）：真桥今天恰好不打印，但桥一有 `console.log`/被依赖方一抛异常，
            # `uid`/`machine_id` 就原文流进响应体与事件行。出口在这里，就在这里兜住。
            raise UpstreamError(_scrub(str(e), secrets), no_failover=True) from e
        except asyncio.TimeoutError as e:
            self._pending.pop(rid, None)
            raise UpstreamError(
                f"qoder 签名桥 {SIGN_TIMEOUT:g}s 无响应（本地子进程，非上游问题）",
                no_failover=True) from e
        if not frame.get("ok"):
            raise UpstreamError(_scrub(f"qoder 签名失败：{frame.get('error')}", secrets),
                                no_failover=True)
        return frame.get("result") or {}


_BRIDGE: Bridge | None = None


async def shutdown() -> None:
    """随应用收尾：杀掉签名桥子进程并作废单例。

    🔴 这不是"顺手加的清理"：常驻 Node 子进程**不会**随 FastAPI 退出而消失
    （`execv` 重启时尤其明显 —— 旧桥会变成孤儿进程，占着一份 wasm 上下文与 STDIN）。
    """
    global _BRIDGE
    if _BRIDGE is not None:
        await _BRIDGE.close()
        _BRIDGE = None


def _bridge(glue_dir: Path, node_bin: str) -> Bridge:
    global _BRIDGE
    if _BRIDGE is None or _BRIDGE.glue_dir != glue_dir or _BRIDGE.node_bin != node_bin:
        _BRIDGE = Bridge(glue_dir, node_bin)
    return _BRIDGE


def _scrub(text: str, secrets: tuple[str, ...]) -> str:
    """凭据绝不进错误文案/日志（§22.2 不变式②）：按值逐个剔除，剔不净就整段折成指纹。"""
    out = str(text or "")
    for s in secrets:
        v = str(s or "")
        if len(v) >= 6:
            out = out.replace(v, "***")
    return out[:400]


#: `ask.py` 明文里携带目录 key 的位置：签名时 wasm 的 `key` 参数与请求体**必须同源**，
#: 主取 `model_config.key`，回落 `chat_context.extra.modelConfig.key`（两处官方都读）。
def _payload_model_key(payload: dict) -> str:
    mc = payload.get("model_config")
    key = mc.get("key") if isinstance(mc, dict) else None
    if key:
        return str(key)
    ctx = payload.get("chat_context")
    extra = ctx.get("extra") if isinstance(ctx, dict) else None
    cfg = extra.get("modelConfig") if isinstance(extra, dict) else None
    return str(cfg.get("key") or "") if isinstance(cfg, dict) else ""


def _payload_source(payload: dict) -> str:
    mc = payload.get("model_config")
    src = mc.get("source") if isinstance(mc, dict) else None
    return str(src) if src else "system"


def make_signer(product_cfg: Any, base_url: str, cred: dict, meta: dict, *,
                glue_dir: Path, node_bin: str) -> Callable[[dict], SignedRequest]:
    """按 `out.SIGNER_FACTORY` 的契约造一个签名器（`payload → SignedRequest`）。

    `base_url` **故意不用**：URL 由 `product_cfg.encrypted_infer_base` 现算 —— 资源里
    填公开端点（`api2-v2.qoder.sh`）时若跟着走，wasm 会签出一个 404 的 host
    （两站/两端的差异是 §22.4 的第一条；DSH `qoder-wasm.ts:617-619` 同判）。
    """
    del base_url
    uid = str(cred.get("uid") or "").strip()
    token = str(cred.get("security_oauth_token") or cred.get("access_token") or "").strip()
    machine_id = str(meta.get("machine_id") or cred.get("machine_id") or "").strip()
    missing = [n for n, v in (("uid", uid), ("security_oauth_token", token),
                              ("machine_id", machine_id)) if not v]
    if missing:
        # 🔴 缺身份字段是**这一个号**的数据问题 ⇒ 给到能定位的文案，但**不置 no_failover**
        # （R1 B-4）：调度器应继续换池里的健康号补位。置 True 的后果正是今天刚归档的
        # Q35-③ 那条红线——一个残缺号终止整条请求，"三个成员能答"被"第一个成员的残缺"盖掉。
        # 对照：签名器整体不可用（没 glue / 没 node / 读循环崩）才是"换号无帮助"，那几处保留 True。
        raise UpstreamError(
            "qoder 凭据缺少加密签名所需字段：" + "、".join(missing)
            + "（该号需要重新登录或重新导入；签名器不会伪造身份字段）")

    secrets = (uid, token, machine_id)
    # 🔴 键里必须带**令牌指纹**（R1 B-2）：wasm 上下文在构造时就把身份材料
    # （`encrypt_user_info`/`key`）算进去了，而本仓的 qoder 号会**续期**
    # （`flow.apply_refresh`）—— 只按 `区域:uid:machine_id` 缓存的话，续期之后这个号
    # 会永久用**旧令牌**签，症状是 AUTH 失败并被调度器停用，运维读到的是"号自己关了"。
    # 用指纹而不是令牌本身：键会进内存/诊断，凭据按 §22.2 只以短哈希出现。
    token_fp = hashlib.sha256(token.encode()).hexdigest()[:12]
    account_key = f"{getattr(product_cfg, 'id', '?')}:{uid}:{machine_id}:{token_fp}"
    metadata = dict(getattr(product_cfg, "client_metadata", {}) or {})
    host = str(getattr(product_cfg, "encrypted_infer_base", "") or "")

    async def sign(payload: dict) -> SignedRequest:
        bridge = _bridge(glue_dir, node_bin)
        result = await bridge.request({
            "op": "prepare", "accountKey": account_key,
            "user": {"uid": uid, "securityOauthToken": token},
            "machineId": machine_id, "metadata": metadata, "host": host,
            "payload": payload, "modelKey": _payload_model_key(payload),
            "source": _payload_source(payload),
        }, secrets=secrets)
        url = str(result.get("url") or "")
        headers = result.get("headers") or {}
        body = str(result.get("body") or "")
        if not url or not isinstance(headers, dict) or not body:
            raise UpstreamError(_scrub(
                f"qoder 签名产物不完整（url/headers/body 任一为空：url={bool(url)} "
                f"headers={isinstance(headers, dict)} body={bool(body)}）", secrets),
                no_failover=True)
        # 🔴 头**原样透传**：`Authorization: Bearer COSY.<载荷>.<签名>` 一旦被
        # 普通 Bearer 覆盖，上游回 `403 Signature invalid`（DSH `qoder-adapter.ts:743`）。
        return SignedRequest(url=url, headers={str(k): str(v) for k, v in headers.items()},
                             body=body)

    return sign


def build_factory(env: dict[str, str] | None = None
                  ) -> tuple[SignerLike | None, str]:
    """`(factory | None, 不可用原因)`；None = 保持未注入（与接线前同一份行为）。

    这里**不启进程**：目录/文件/node 三项在位即可注入，真正的启动失败发生在第一次
    签名时并当场回报（避免"装配期静默、运行期 500"）。
    """
    glue_dir, why = resolve_glue_dir(env)
    if glue_dir is None:
        return None, why
    if not BRIDGE_JS.is_file():
        return None, f"签名桥脚本缺失：{BRIDGE_JS}"
    if resolve_node(env) is None:
        return None, "本机没有 node 可执行文件（qoder 的 wasm 签名需要它；可用 " + NODE_ENV + " 指定）"
    return factory, ""


def factory(product_cfg: Any, base_url: str, cred: dict, meta: dict) -> Callable[[dict], Any]:
    """`out.SIGNER_FACTORY` 的实现（契约见 `out.py` 模块头）。"""
    glue_dir, why = resolve_glue_dir()
    if glue_dir is None:
        raise UpstreamError(f"qoder 签名器不可用：{why}", no_failover=True)
    node_bin = resolve_node()
    if node_bin is None:
        raise UpstreamError(f"qoder 签名器不可用：找不到 node（可用 {NODE_ENV} 指定）",
                            no_failover=True)
    return make_signer(product_cfg, base_url, cred, meta, glue_dir=glue_dir, node_bin=node_bin)


def install(env: dict[str, str] | None = None) -> str:
    """按环境注入 `out.SIGNER_FACTORY`；返回**空串 = 已注入**，否则 = 未注入的原因。

    装配期调用（`main.create_app`）。未注入时 `out.py` 继续走 `NOT_WIRED_HINT`
    fail closed，且 `main._outbound_premise_gap` 会把 qoder 资源继续排除出对外声明
    ——「签名没就位」在盘上只有一个真相：`SIGNER_FACTORY is None`。
    """
    from model_gateway.upstream.qoder import out as qoder_out

    impl, why = build_factory(env)
    if impl is None:
        return why
    qoder_out.SIGNER_FACTORY = impl
    return ""
