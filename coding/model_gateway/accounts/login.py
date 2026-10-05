"""两步式登录会话引擎（tech-design v2.0 §22.3「统一形状」+ §22.8-2、-3、-9）。

🔴 一切登录 = 两步式「start → 状态/凭据」（`20 §1.2/§2.1` 九种登录收敛后的唯一结论）：

    start(product, kind=…)             → LoginSession（其 `.challenge` 只含用户可见物）
    poll(product, session_id)          → LoginOutcome（pending **不是错误**）
    callback(product, session_id, ...) → LoginOutcome（声明了 `_CALLBACK` 的产品才有：
                                                   local_callback 型 = 主投递通道，
                                                   device_code 型（zcode）= 与轮询赛跑的
                                                   副通道，见下方「回跳投递通道」；
                                                   **回跳粘贴**与**接收端投递**两条通道
                                                   共用这一个入口与这一条 `_advance`）
    alt_call(product, session, name, …) → `_ALT_HOOKS` 辅助调用（备选形态，见下）

🔴 登录形态（§22.3 补入②）：`start(kind=None)` 缺省取 `ProductMeta.login`（主推形态），
    取值须在 `login ∪ login_alt` 内——非法值**当场** `ValueError`（列合法值，不静默回退）；
    选定值写进 `LoginSession.kind` 供钩子/入口层读取。
🔴 备选形态的辅助调用（§22.3 补入③）：产品模块可导出 `_ALT_HOOKS`（如短信两段
    `sms_send`/`sms_submit`）——**入口层专用**，与 `_HOOKS` 同形但**不进**十钩子冻结契约；
    统一经 `alt_call()` 取用（未知名字当场 `KeyError`，不给字符串 `getattr` 后门）。
🔴 会话纪律（§22.8-2）：
    - TTL 默认 600s（10 分钟）—— 超时即失效，**不续命**；
    - 显式取消；成功/失败/取消/超时 → 会话立即出表（内存有界，§22.8-9）；
    - **不创建后台轮询任务**（轮询由调用方驱动）→ 天然无孤儿任务；进程退出钩子
      （`atexit`）只清会话表**并关闭各会话的回跳接收端**（BD4 之后唯一的例外：
      `local_callback` 会话带一条 loopback 监听，它的生命周期 = 会话生命周期，
      出表即关，超时由监听自己的定时器落定，不需要有人来轮询它）。
    - 🔴 TTL/取消判定是**三条通道同一实现**（`_gate`）：`poll`/`callback`（经
      `_advance`）与 `alt_call` 都先过同一道闸 —— M6-6 收口（R1 F1）：修前
      `alt_call` 是纯派发，`expired=True` 的会话仍能走短信第二段完成登录并落盘凭据
      （§22.8-2 硬清单被整条绕开）。
🔴 会话 ↔ 产品配对（M6-6 收口，R1 F10）：`poll`/`callback` 与 `alt_call` 都在
    引擎层校验 `session.product == 入参 product`（会话表是全局的，入口层配错产品
    时不许拿 A 的钩子驱动 B 的会话）；错配 → **可读错误且不消耗会话**。
🔴 单飞（§22.8-3）：同一会话的并发 `poll` 复用**同一个在飞任务**，不对上游重复点击。
🔴 失败可见（§22.8-5 fail closed）：钩子里的**可预期失败**应由钩子折叠成
    `LoginOutcome(state="failed")`；引擎**不吞异常** —— 钩子抛出的异常原样冒到入口层
    （入口层记日志/返回 500），不伪装成"业务失败"。
🔴 凭据落盘 = **两阶段提交**（M7-E，用户裁决「接入向导：登录完毕后点『确定接入』
    才保存存储数据」；本节推翻此前"success 即落盘"的单段行为）：

    第一段（认领 + 暂存）  `success` 不再写盘：凭据 + meta 暂存到 `session.state["pending"]`
                          （`_stage_pending`，四路通道同一实现：`poll` / `callback`（粘贴）/
                          接收端投递（经 `callback`）/ `alt_call`）——**一个字节都不落盘**；
                          认领位 = `LoginSession.committed_via`（check-and-set 之间无 `await`，
                          多条通道同时成功时只有一个能暂存，其余让位）；会话**留在表里**
                          （confirm / cancel / TTL 三条既有路径负责处置它）。
    第二段（确认 + 落盘）  `commit_pending(session_id)`：用户点「确定接入」后经
                          `_commit_outcome` → `store.commit_login_async()` 落盘（写回自检 +
                          失败整体回滚；A-1 接线：等锁/写盘下放工作线程，事件循环不停摆）；
                          成功 → 清暂存 + 记台账（幂等）+ 会话出表；失败 → **不谎报成功**
                          （`committed=False` + 可读原因，暂存保留供重试）。
    🔴 丢弃纪律：**取消 / TTL 超时 / 失败出表** 一律丢弃暂存凭据（`_drop` 统一做，
    过期未确认 = 不落盘）——「确定接入」是唯一的落盘开关。
    ⚠️ `mgw zcode login`（CLI）**不**走本引擎的两阶段：它直接调 `store.commit_login`
    （`cli_zcode.py`），保持"命令行一次完成"的既有语义，不在本契约面内。

## 🔴 回跳投递通道（BD4，2026-09-30 补）：`local_callback` 型会话自带一个接收端

此前网关**只构造回跳地址、从不监听它**（需求书 §5/§6-BD4 的实测事故：
`curl 127.0.0.1:18080/authorize` → connection refused、`GET :8300/auth/callback` → 404，
全包零监听器），于是 trae / lobsterai 只能靠人把地址栏整串粘回文本框。现在：

    start(local_callback)      → 先 `CallbackListener.start()` **绑定 127.0.0.1**，
                                 实际端口交给产品 `login_start` 拼授权 URL
    浏览器被供应商 302 回本机端口 → 接收端把**整串回跳地址**灌进
                                 `_deliver()` → 与粘贴通道**同一条** `_single_flight`
                                 + `_advance` + `login_callback` 钩子（参数就是
                                 `{"url": 整串}`，校验/换 token 一行都不重复实现）
    成功 / 失败 / 取消 / TTL 超时 → 会话出表（`_drop`）时**一并关闭**接收端

🔴 接收端的声明表 = 产品模块的 `_CALLBACK`（`path` / `preferred_port` / `secret_*`），
   与 `_HOOKS`/`_ALT_HOOKS` 同一条"表里有什么才用什么"的纪律（§22.3）。
   🔴 **开不开监听取决于"有没有声明这张表"，不取决于登录形态**（M7-D）：
   `local_callback` 型（trae / lobsterai）以回跳为**主**通道；`device_code` 型但声明了
   该表的产品（zcode）以**轮询为主、回跳为副**，两条线赛跑 —— 裁决点在 `_advance`
   认领前的「flow is still mine」check-and-set（`LoginSession.committed_via`）：
   **同一次登录至多有一条通道能认领暂存**（`store.commit_login` 至多被调用一次，
   且发生在用户点「确定接入」之后），输家让位（对齐参考实现
   `lib.rs:1698-1706,1741,1755` 的 `flow_still_ours()` + `__superseded__`）。
🔴 起监听失败**不**让登录起不来：记一条 warning、`session.callback=None`，
   产品层按声明端口拼 URL → **地址栏粘贴兜底照常可用**（诚实降级，不是假成功）。
"""

from __future__ import annotations

import asyncio
import atexit
import importlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from model_gateway.accounts import callback_server, store
from model_gateway.accounts.callback_server import CallbackCapture, CallbackListener
from model_gateway.accounts.store import CommitError
from model_gateway.accounts.types import Challenge, LoginKind, LoginOutcome

logger = logging.getLogger("model_gateway.accounts")

#: 会话 TTL 默认值（秒）—— §22.8-2「默认 10 分钟」
DEFAULT_SESSION_TTL_S = 600.0

#: 确认台账上限（M7-E）：`commit_pending` 成功后会话立即出表，重复确认（双击/陈旧页面）
#: 靠这张小台账如实回报账号名；只记最近 N 条（进程内有界，重启即失——重启后无从确认，
#: 诚实地报"会话不存在"）。
_COMMITTED_LEDGER_MAX = 64


@dataclass
class LoginSession:
    """一次登录会话（产品钩子 `login_start(session)` / `login_poll(session)` 的输入）。

    🔴 `challenge` 只承载**用户可见物**（§22.3）；设备码私钥、中间令牌、轮询游标等
       放进 `state` —— 引擎不解释它的内容，只保证它不回显给用户。
    """

    id: str
    product: str
    name: str
    #: 创建时刻（引擎时钟，默认 `time.monotonic`）
    created_at: float
    ttl_s: float
    #: 本次会话采用的登录形态（`LoginKind` 字面量；`start(kind=…)` 写入，§22.3 补入②）。
    #: 空串 = 直接构造的会话未指定（引擎路径恒非空）。钩子据此区分主/备选形态。
    kind: str = ""
    cancelled: bool = False
    challenge: Challenge | None = None
    #: 产品钩子的私有会话态（**绝不进 Challenge / LoginOutcome.detail**）。
    #: 引擎保留键：`"pending"` = 两阶段提交的暂存凭据（`{"credentials", "meta", "via"}`，
    #: 由 `_stage_pending` 写、`commit_pending` 或出表/取消/超时读或丢）。
    state: dict = field(default_factory=dict)
    #: 创建该会话的引擎账号根（`LoginEngine(root=…)`；`None` = 产品默认根）。
    #: `alt_call` 的调用形状固定为 `(product, session, name, **kw)`（§22.3 补入③），
    #: 拿不到引擎实例 —— 落盘锚点由此回传，否则自定义 root 的引擎在 alt 通道会写错目录。
    root: Path | None = None
    #: 创建该会话的引擎时钟（`LoginEngine(now=…)`；`None` = 直接构造的会话）。
    #: 与 `root` 同理由引擎在 `start` 时回传（`alt_call` 拿不到引擎实例）——
    #: 使 TTL 判定在 `_advance` 与 `alt_call` 两条通道落在**同一只钟**上；
    #: `None` 时回退 `time.monotonic`（引擎缺省钟）。
    now: Callable[[], float] | None = None
    #: 本机回跳接收端（BD4）：由**产品的 `_CALLBACK` 声明表**决定开不开（M7-D 起不再按
    #: 登录形态判定，见 `start()`），引擎在 `login_start` **之前**绑定，
    #: 产品 `login_start` 用它的**实际端口**拼授权 URL。`None` = 本产品未声明接收端 /
    #: 绑定失败 / 直接构造的会话 —— 一律回退「地址栏粘贴」（同一 handler，不同投递）。
    #: 🔴 生命周期 = 会话生命周期：终态出表 / 取消 / TTL 超时时由引擎 `close()`（幂等）。
    callback: CallbackListener | None = None
    #: 🔴 「flow is still mine」认领位 = **两阶段提交第一段**的守卫（M7-D 起，M7-E 扩为
    #: 四路通道）：本次会话的成功凭据**是否已被某条通道认领并暂存**（`state["pending"]`）。
    #: 认领是 check-and-set（之间不 `await`），于是 `poll` / `callback`（粘贴）/
    #: 接收端投递 / `alt_call` 四路里**只有第一个**能暂存，其余让位（软失败，不二次认领）。
    #: 落盘发生在用户点「确定接入」（`commit_pending`）—— 在此之前**一个字节都不写盘**。
    #: 对齐参考实现 `lib.rs:1698-1706,1741,1755` 的 `flow_still_ours()`：
    #: 赢家认领，输家一律 `__superseded__`。
    committed_via: str = ""
    #: 接收端最近一次投递的结局状态（`_deliver` 写；`_after_settled` 据此判断
    #: 「这次落定是不是**非终态**投递」—— 是则会话**不出表**，见那里）。空 = 没投过。
    last_delivery: str = ""

    def expired(self, now: float) -> bool:
        """是否已超时（超时判定用引擎时钟，便于测试注入）。"""
        return now - self.created_at >= self.ttl_s

    def cancel(self) -> None:
        """显式取消（幂等）—— 取消后一切 `poll` 都返回 `expired`。

        ⚠️ 两阶段提交（M7-E）：取消 = **丢弃暂存凭据**（由引擎 `_drop` 统一做）——
        登录成功但未点「确定接入」时取消，账号目录**不会**留下任何东西
        （这正是确认步的意义；红证见 `tests/integration/test_m7_callback_capture.py`）。
        """
        self.cancelled = True


def _module(product: str):
    """按产品 id 取产品模块（**动态导入**：不把 10 个产品在导入期全拉起来）。

    未登记产品 → `registry.get` 抛 `KeyError`（显式失败，不静默当作"没实现"）。
    """
    from model_gateway.accounts.registry import get as registry_get

    registry_get(product)
    return importlib.import_module(f"model_gateway.upstream.{product}.product")


def _hook(product: str, hook: str):
    """按产品 id 取钩子。

    🔴 经产品模块的契约表 `_HOOKS` 取（§22.3 的 10 个模块级函数），**不用字符串
    `getattr(module, name)`**：表里没有的名字当场 `KeyError`（与"产品没实现这个钩子"
    区分得开），且表本身是接线护栏能看见的静态证据。
    """
    table = getattr(_module(product), "_HOOKS", None)
    if not isinstance(table, dict) or hook not in table:
        raise KeyError(f"{product} 未提供钩子 {hook!r}（§22.3 契约表 `_HOOKS` 缺项）")
    return table[hook]


def _resolve_kind(product: str, kind: str | None) -> LoginKind:
    """解析本次会话的登录形态（§22.3 补入②）。

    `kind=None` → `ProductMeta.login`（主推形态）；显式值必须在 `login ∪ login_alt` 内，
    非法值**当场** `ValueError`（消息列出该产品的全部合法值）——**不静默回退**到主形态
    （回退会让用户以为选了短信、实际走了扫码，且入口层无从察觉）。
    """
    from model_gateway.accounts.registry import get as registry_get

    meta = registry_get(product)
    legal = (meta.login, *meta.login_alt)
    if kind is None:
        return meta.login
    if kind not in legal:
        raise ValueError(
            f"登录方式 {kind!r} 非法：{product} 只支持 "
            f"{'、'.join(repr(k) for k in legal)}"
            f"（`ProductMeta.login` ∪ `login_alt`；缺省取主形态 {meta.login!r}）")
    return kind


def _gate(session: LoginSession, now: Callable[[], float]) -> LoginOutcome | None:
    """会话纪律闸门（§22.8-2）：取消 / TTL 超时 → 结构化 `expired` 终态。

    返回 `None` = 放行；否则返回**拒绝结局**。🔴 **三条通道同一实现**
    （`_advance` / `alt_call`，M6-6 收口 R1 F1）：TTL/取消判定不许各写一份 ——
    修前 `alt_call` 完全没有这道闸，过期会话仍能完成短信登录并落盘凭据。
    """
    if session.cancelled:
        return LoginOutcome(state="expired", detail="会话已被取消")
    if session.expired(now()):
        return LoginOutcome(state="expired", detail=f"会话超时（{int(session.ttl_s)}s）")
    return None


def _mismatch_outcome(session: LoginSession, product: str) -> LoginOutcome:
    """会话 ↔ 产品配对不符的可读结局（M6-6 收口 R1 F10；`alt_call` 侧抛 `ValueError`）。

    🔴 **不消耗会话**：错配是调用方配错产品（会话表是全局的），不是会话终态 ——
    会话留在表里，用正确的产品重试必须照常工作（纵深防御，护栏不让错配悄悄打到上游）。
    """
    return LoginOutcome(
        state="failed",
        detail=(f"会话与产品不匹配：会话属于 {session.product!r}，请求按 {product!r} "
                f"（入口层取会话/取产品时配错；会话未消耗，可用正确产品重试）"))


def _alt_hook(product: str, name: str):
    """按产品 id 取备选形态的辅助调用（§22.3 补入③的 `_ALT_HOOKS` 表）。

    表纪律与 `_hook` 同形：表里没有的名字当场 `KeyError`（消息列合法值），
    **不给字符串 `getattr` 后门**；产品未导出 `_ALT_HOOKS`（= 没有备选形态，合法）
    时给出可读错误——否则入口层只会拿到一个 `NoneType is not callable`。
    """
    table = getattr(_module(product), "_ALT_HOOKS", None)
    if not isinstance(table, dict):
        raise RuntimeError(
            f"{product} 未导出 `_ALT_HOOKS` 表（§22.3 补入③：备选登录形态的辅助调用须经"
            f"该表暴露；本产品没有备选形态时不提供该表就不该被调用）")
    if name not in table:
        legal = "、".join(sorted(table)) or "（空表）"
        raise KeyError(f"{product} 的 `_ALT_HOOKS` 无 {name!r}（合法值：{legal}）")
    return table[name]


def _callback_plan(product: str) -> dict | None:
    """取产品的**回跳接收端**声明（`product.py::_CALLBACK`；没有表 = 不起监听）。

    与 `_HOOKS` / `_ALT_HOOKS` 同一条纪律：产品事实写在产品模块的显式表里，引擎只读表、
    不猜字段名、不给 `getattr` 后门。表内键（缺省即按括号里的值）：

    - `path`（必填）：接收端**只**服务这个路径，其余一律 404 且不消耗会话；
    - `preferred_port`（0）：首选端口；0 = 随机 ≥10000。拿不到时回退随机端口，
      授权 URL 用**实际**端口（用户裁决：trae 保 18080 首选 + 随机兜底）；
    - `secret_state_key`：会话态里哪个字段是本次登录的关联串（`login_start` 才生成，
      故注册的是**取值函数**，到达时才读）；
    - `secret_key`（`state`）：回跳查询里哪个参数带它；
    - `secret_required`（True）：回跳**没带**该参数时是否直接判无效
      （lobsterai 的 portal 恒回传 `state`；TRAE 不保证回传 `login_trace_id`）。
    """
    plan = getattr(_module(product), "_CALLBACK", None)
    if not isinstance(plan, dict) or not plan.get("path"):
        return None
    return plan


def _close_callback(session: LoginSession | None) -> None:
    """关闭会话的回跳接收端（**幂等**、永不抛：监听是没绑在会话表上的 OS 资源，
    会话出表/取消/退出都必须把它收掉，但它的异常不该改变登录结局）。"""
    listener = getattr(session, "callback", None) if session is not None else None
    if listener is None:
        return
    try:
        listener.close()
    except Exception:  # noqa: BLE001 — 见上：清理动作不升级成故障
        logger.exception("关闭回跳接收端时异常（已忽略）")


def _stage_pending(session: LoginSession, outcome: LoginOutcome, *,
                   channel: str) -> LoginOutcome | None:
    """两阶段提交**第一段**（M7-E，唯一实现）：认领成功凭据并**暂存**到会话上。

    返回 `None` = 认领并暂存成功；否则返回**让位结局**（另一条通道已先认领 ——
    软失败：不二次暂存、不落盘、不向用户报真错误）。四路通道（`poll` / `callback`
    （含粘贴与接收端投递）/ `alt_call`）都经这里，口径只有这一份。

    设计约束（逐条对应本轮裁决与任务书）：
    - 暂存物放 `session.state["pending"] = {"credentials", "meta", "via"}`，
      **绝不**进 `Challenge` / `LoginOutcome.detail`（§22.3：凭据不回显）；
    - 认领是 check-and-set，**之间无 `await`** → 并发通道里只有一个能暂存；
    - 凭据已到手 → **关闭回跳接收端**（幂等）：端口不空等 TTL，多余回跳自然绝迹；
    - **只暂存、不写盘**（一个字节都不落）：落盘 = 用户点「确定接入」后的
      `commit_pending`，取消 / 超时一律丢弃。
    """
    if session.committed_via:
        return LoginOutcome(
            state="expired",
            detail=(f"凭据已由 {session.committed_via} 通道认领并暂存（待「确定接入」落盘），"
                    f"{channel}通道让位（同一次登录不重复认领凭据）"))
    session.committed_via = channel
    session.state["pending"] = {
        "credentials": dict(outcome.credentials or {}),
        "meta": dict(outcome.meta or {}),
        "via": channel,
    }
    _close_callback(session)
    return None


class LoginEngine:
    """登录会话表 + 产品钩子调度（§22.3 两步式）。

    `now` 可注入（默认 `time.monotonic`）——TTL 用例无需真的睡 10 分钟；
    `root` 可注入（默认各产品的 `store.product_root()`，测试用 `MG_CONFIG` 隔离即可）。
    """

    def __init__(self, *, ttl_s: float = DEFAULT_SESSION_TTL_S,
                 now: Callable[[], float] | None = None,
                 root: Path | None = None) -> None:
        self.ttl_s = ttl_s
        self._now = now or time.monotonic
        self._root = root
        self._sessions: dict[str, LoginSession] = {}
        #: 在飞任务表（单飞，§22.8-3）；任务结束即出表（内存有界）
        self._inflight: dict[str, asyncio.Task] = {}
        #: 已确认落盘的会话 → 账号名（**幂等回报**用的小台账，M7-E）：确认成功后会话
        #: 立即出表，重复确认（双击 / 陈旧页面）找不到会话对象时靠它如实回报
        #: `committed=True` + 账号名，而不是谎报"没落盘"。有界（只记最近 N 条）。
        self._committed: dict[str, str] = {}
        # 进程退出清理钩子（§22.8-2）：清会话表 + 取消残留任务（正常路径下没有任务）
        atexit.register(self.shutdown)

    # —— 对外的三步 API ——

    async def start(self, product: str, *, name: str = "", kind: LoginKind | None = None) -> LoginSession:
        """启动登录：定形态 → 建会话 →（产品声明了 `_CALLBACK` 才）**先绑回跳接收端** → 调产品 `login_start` → 拿 `Challenge`。

        - `kind` 缺省取 `ProductMeta.login`（主推形态）；非法值**当场** `ValueError`
          （§22.3 补入②，不静默回退）；选定值写进 `LoginSession.kind`。
        - 账号名缺省 = `{product}-{8hex}`（照抄 `20 §2.3` 的 `{provider}-{shortId()}` 形态），
          并保证不与既有账号重名（重名会覆盖别人的凭据目录）。
        - 🔴 BD4：回跳接收端**必须在 `login_start` 之前绑定** ——
          授权 URL 里要写的是**实际**端口（`trae-oauth.ts:680-693`：首选端口被占时
          回跳地址跟着回退，否则回跳打到别人家）。绑定失败不阻断登录：记 warning、
          `session.callback=None`，产品层按声明端口拼 URL → 粘贴兜底照常（诚实降级）。
        - 🔴 **开不开监听由产品的 `_CALLBACK` 声明表决定，不由登录形态决定**（M7-D）：
          `local_callback` 型（trae / lobsterai）照旧——回跳**就是**它的投递通道；
          `device_code` 型但**声明了**该表的产品（zcode）拿到一条 loopback 监听作为
          **副通道**（主通道仍是轮询），两条线在 `_advance` 的「flow is still mine」
          守卫下赛跑。未声明表的产品**一个端口都不开**（`_CALLBACK` 是"表里有什么
          才用什么"的纪律，与 `_HOOKS`/`_ALT_HOOKS` 同源）。
        - `login_start` 抛异常 → 已绑好的接收端**立刻关掉**（不留孤儿监听）。
        """
        self._sweep()
        chosen = _resolve_kind(product, kind)
        clean = self._resolve_name(product, name)
        session = LoginSession(id=secrets.token_hex(8), product=product, name=clean,
                               created_at=self._now(), ttl_s=self.ttl_s, kind=chosen,
                               root=self._root, now=self._now)
        if chosen == "local_callback" or _callback_plan(product) is not None:
            session.callback = await self._open_callback(product, session)
        try:
            challenge = await _hook(product, "login_start")(session)
        except BaseException:
            _close_callback(session)
            raise
        session.challenge = challenge
        self._sessions[session.id] = session
        return session

    async def poll(self, product: str, session_id: str) -> LoginOutcome:
        """轮询登录状态（单飞：并发轮询复用同一在飞任务）。"""
        return await self._single_flight(
            session_id, call=lambda: self._advance(product, session_id, None))

    async def callback(self, product: str, session_id: str, params: dict) -> LoginOutcome:
        """回跳**粘贴**（local_callback 型）：把用户粘回来的参数交给产品钩子。

        🔴 与接收端投递通道（`_deliver`）共用这条入口与同一条 `_advance`：
        粘贴的只是"人工投递"，判据/换 token/落盘完全同一份实现，不分叉。
        """
        return await self._single_flight(
            session_id, call=lambda: self._advance(product, session_id, params))

    def cancel(self, session_id: str) -> bool:
        """显式取消会话（返回是否找到并取消）。"""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session.cancel()
        self._drop(session_id)
        return True

    def get_session(self, session_id: str) -> LoginSession | None:
        """按 id 取会话（**公开读取口**：API/CLI 一律经此，不直捅 `_sessions`）。"""
        return self._sessions.get(str(session_id or "").strip())

    def shutdown(self) -> None:
        """清空会话表并关闭所有回跳接收端（进程退出钩子；**不取消任务**——正常情况下
        引擎不建轮询任务，监听器自己的连接任务随 `close()` 一起收）。

        🔴 两阶段提交（M7-E）：进程退出 = 一切未确认的暂存凭据**随会话表一起消失**
        （**不落盘**）——「确定接入」是唯一的落盘开关。
        """
        for session in list(self._sessions.values()):
            _close_callback(session)
        self._sessions.clear()
        self._inflight.clear()
        self._committed.clear()

    # —— 内部 ——

    def _resolve_name(self, product: str, name: str) -> str:
        if name:
            clean = store.sanitize_name(name)
            if clean != name:
                raise ValueError(f"账号名必须匹配 [A-Za-z0-9_-]{{1,32}}：{name!r}")
            return clean
        for _ in range(20):
            candidate = f"{product}-{secrets.token_hex(4)}"
            if candidate not in store.list_accounts(product, root=self._root):
                return candidate
        raise RuntimeError(f"无法为 {product} 生成不重名的默认账号名（尝试 20 次）")

    async def _single_flight(self, session_id: str, *, call) -> LoginOutcome:
        """单飞：同一会话的在飞调用只允许一个（§22.8-3「登录轮询按产品单飞」）。"""
        task = self._inflight.get(session_id)
        if task is not None and not task.done():
            return await task                    # 并发轮询 → 复用同一在飞任务，不重复点上游
        task = asyncio.create_task(call())
        self._inflight[session_id] = task
        try:
            return await task
        finally:
            if self._inflight.get(session_id) is task:
                self._inflight.pop(session_id, None)

    async def _advance(self, product: str, session_id: str, params: dict | None) -> LoginOutcome:
        session = self._sessions.get(session_id)
        if session is None:
            return LoginOutcome(state="expired", detail="会话不存在或已被取消")
        blocked = _gate(session, self._now)
        if blocked is not None:
            self._drop(session_id)                # 终态 → 出表（内存有界，§22.8-9）
            return blocked
        if session.product != product:
            return _mismatch_outcome(session, product)   # 错配不消耗会话（F10 纵深防御）
        if session.committed_via:
            # 🔴 两阶段提交第一段（M7-E）已完成：**不再打产品钩子** —— 授权料是一次性的，
            #    对一条已认领成功凭据的会话重复点上游，只会拿回失败/过期并把待确认的
            #    成功搅浑。如实告知"待确认接入"（幂等：不修改任何状态）。
            return LoginOutcome(
                state="success",
                detail=(f"登录已完成：凭据已由 {session.committed_via} 通道认领并暂存本机，"
                        f"请在「账号接入」向导点「确定接入」将其写入账号目录"
                        f"（会话失效前未确认则丢弃，需重新登录）。"))

        channel = "轮询" if params is None else "回跳"
        hook = "login_poll" if params is None else "login_callback"
        call = _hook(product, hook)
        outcome = await call(session) if params is None else await call(session, params)
        if outcome.state == "pending":
            return outcome                        # pending 不是错误：会话保留，等下一次轮询
        if outcome.state == "success":
            # 🔴 两阶段提交第一段（M7-E）：凭据**认领并暂存**（`state["pending"]`），
            #    **一个字节都不落盘** —— 落盘只发生在用户点「确定接入」（`commit_pending`）。
            #    「flow is still mine」认领位：check-and-set 之间**没有 await**，
            #    于是"谁先认领"是一个原子的裁决 —— 多条通道同时成功时只有一个能暂存，
            #    另一个让位并如实回报"另一通道已完成认领"。
            #    与参考实现同一形态：`lib.rs:1698-1706`（进落盘前查一次）+
            #    `:1741`（拿写锁后再查一次）+ `:1755`（赢家落盘后清空 pending flow）。
            superseded = _stage_pending(session, outcome, channel=channel)
            if superseded is not None:
                return superseded
            # 🔴 成功但**不出表**：会话留在表里等「确定接入」/取消/TTL（出表 = 丢弃暂存）。
            return outcome
        self._drop(session_id)                    # 终态（failed/expired）→ 出表（内存有界，§22.8-9）
        return outcome

    async def commit_pending(self, session_id: str) -> dict:
        """确认接入（两阶段提交**第二段**，M7-E）：把会话上暂存的凭据写入账号目录。

        返回 `{"committed": bool, "account": str, "reason": str}` —— **永不抛业务异常**，
        入口层据此回 200（与 `login_cancel` 同一幂等纪律，未知会话**不是 404**）：

        - 会话不存在（未知 id / 已出表 / 已取消 / 已超时被清）→ `committed=False` +
          可读原因；已确认过的会话靠有界台账如实回报 `committed=True` + 账号名
          （**幂等：不二次写盘**）；
        - 会话在表但 TTL 已过 / 已取消 → 丢弃暂存、`committed=False`（**超时不落盘**）；
        - 会话在表、没有暂存凭据（还没登录成功）→ `committed=False` + 可读原因；
        - 有暂存 → 走**既有唯一落盘路径**（`_commit_outcome` → `store.commit_login_async`，
          写回自检 + 失败整体回滚；等锁/写盘在**工作线程**里，事件循环不停摆，A-1）；
          失败 → `committed=False` + 原因（**不谎报成功**；暂存保留，可重试）；
          成功 → 清暂存 + 记台账 + 会话出表（关监听幂等）。
        """
        sid = str(session_id or "").strip()
        if not sid:
            return {"committed": False, "account": "", "reason": "缺少会话 id（session）"}
        session = self._sessions.get(sid)
        if session is None:
            known = self._committed.get(sid)
            if known:
                return {"committed": True, "account": known,
                        "reason": "该会话此前已确认落盘（幂等：不重复写盘）"}
            return {"committed": False, "account": "",
                    "reason": ("会话不存在或已过期（未落盘）。若刚才「确定接入」曾报成功，"
                               "凭据已在账号目录里，刷新列表即可看到；否则请重新发起登录。")}
        # TTL 判定与 `_advance`/`alt_call` 同源：优先用**会话自带的引擎钟**
        # （`session.now`，引擎 `start` 时写入；直构会话按其自带钟判，与 alt_call 逐字同口径）
        blocked = _gate(session, session.now or self._now)
        if blocked is not None:
            self._drop(sid)                       # 过期/取消出表 = 丢弃暂存（绝不落盘）
            return {"committed": False, "account": session.name, "reason": blocked.detail}
        pending = session.state.get("pending")
        if not isinstance(pending, dict) or not pending.get("credentials"):
            return {"committed": False, "account": session.name,
                    "reason": "本次会话没有待确认的凭据（尚未登录成功或凭据为空）"}
        outcome = LoginOutcome(state="success",
                               credentials=dict(pending.get("credentials") or {}),
                               meta=dict(pending.get("meta") or {}))
        await _commit_outcome(session, outcome, root=self._root)
        if outcome.state != "success":
            # 写回自检失败 / 拒写：把真实原因回给调用方（**不谎报成功**）；
            # 暂存保留 → 同一会话可再点一次「确定接入」重试。
            return {"committed": False, "account": session.name, "reason": outcome.detail}
        session.state.pop("pending", None)
        self._committed[sid] = session.name
        while len(self._committed) > _COMMITTED_LEDGER_MAX:      # 有界：只记最近 N 条
            self._committed.pop(next(iter(self._committed)))
        self._drop(sid)                           # 已落盘 → 会话出表（关监听幂等）
        return {"committed": True, "account": session.name, "reason": ""}

    async def _open_callback(self, product: str, session: LoginSession) -> CallbackListener | None:
        """为 `local_callback` 会话建并**绑定**回跳接收端（BD4）。

        🔴 时序：先 `start()` 绑定 → 拿到**实际端口** → 才让产品 `login_start` 拼授权
        URL（`trae-oauth.ts:680-693`）。首选端口被占/权限不足时 `_bind()` 自己回退随机端口，
        所以 URL 永远指向真的在听的那个端口。

        🔴 超时 = 会话 TTL（`timeout_s=session.ttl_s`）：监听不许比会话活得久，
        到点自己落定并回调 `_drop` 出表（`trae-oauth.ts:631-643` 那条"每个分支都要
        clearTimeout + close + 落定"的教训 —— 少一步就是界面永远停在「认证中」）。

        两种"不起监听"的出口都**如实记日志**、都**不**抛：
        ① 产品未声明 `_CALLBACK` 表（= 该产品没接接收端）；
        ② 绑定失败（端口全被占 / 无权限）。
        两者都退回「地址栏粘贴」这条既有通道（同一 handler、不同投递），登录仍可用。
        """
        plan = _callback_plan(product)
        if plan is None:
            logger.warning("%s：local_callback 型但未声明 `_CALLBACK` 接收端表 —— "
                           "本次登录不起监听，回退「地址栏粘贴」（§22.7 回跳粘贴通道）", product)
            return None
        state_key = str(plan.get("secret_state_key") or "")
        listener = CallbackListener(
            path=str(plan["path"]),
            preferred_port=int(plan.get("preferred_port") or 0),
            secret_key=str(plan.get("secret_key") or "state"),
            secret_required=bool(plan.get("secret_required", True)),
            # 关联串在 `login_start` 里才生成 → 注册**取值函数**（到达时才读，不固化空串）
            secret=(lambda: str(session.state.get(state_key) or "")) if state_key else "",
            timeout_s=session.ttl_s,
            handler=lambda capture: self._deliver(product, session.id, capture),
            on_settled=lambda listener: self._after_settled(session, listener),
        )
        try:
            await listener.start()
        except OSError as e:
            logger.warning("%s：回跳接收端起不来（%s）—— 本次登录不起监听，"
                           "回退「地址栏粘贴」（授权 URL 仍按声明端口 %s 拼）",
                           product, e, plan.get("preferred_port") or "随机")
            return None
        return listener

    async def _deliver(self, product: str, session_id: str,
                       capture: CallbackCapture) -> LoginOutcome:
        """接收端把**真实到达的回跳地址**灌进与粘贴通道同一条路（BD4 的接线点）。

        🔴 参数形态就是 `{"url": 整串地址}` —— 与用户从地址栏粘回来的东西**逐字节同形**，
           于是产品层的 `validate_callback` / `callback_code_state` / `parse_callback` /
           `exchange` 与引擎落盘**一行都不重复实现**（本任务书点名禁止的"复制换凭据逻辑"）。
        🔴 经 `callback()`（= 同一道 `_single_flight` + `_advance` 闸）而不是直连 `_advance`：
           单飞（§22.8-3）保证"浏览器已回跳 + 用户同时又点了一次粘贴"只换一次 token
           —— 授权料是一次性的，第二次必然失败，会把已经到手的成功打成 failed。
        ⚠️ 结果记在 `session.last_delivery`（M7-D）：**单飞会让这条投递"借用"另一条
           在飞调用的结果**（典型：回跳正好落在一次轮询的请求在飞那几十毫秒里 →
           拿回来的是轮询的 `pending`，本次回跳根本没被产品钩子看过）。
           这条事实必须由 `_after_settled` 看得见，否则接收端会把它当"投递失败"
           连带把会话踢出表 —— 一次碰撞就打死一本来能成功的登录。
        """
        session = self._sessions.get(session_id)
        outcome = await self.callback(product, session_id, {"url": capture.url})
        if session is not None:
            session.last_delivery = outcome.state
        return outcome

    def _after_settled(self, session: LoginSession, listener: CallbackListener) -> None:
        """接收端落定后的会话处置（M7-D 的赛跑安全项）。

        - `settled:success` / `settled:timeout` / 任何**终态**投递失败 → 出表（原行为）；
        - 🔴 `settled:failed:pending` = 这条投递的结局**不是终态**（借用轮询的 pending，
          或产品钩子自己说"还在等"）→ **会话留在表里**：等下一次 `poll` 由服务端中介的
          设备流收敛（zcode 的主通道就是轮询），出表与 TTL 仍由
          `_advance`→`_gate` / `_sweep` / `cancel` 这三条既有路径负责 ——
          本分支**不新建任何后台任务**（§22.8-2「不创建后台轮询任务」原样保持）。

        ⚠️ 已知取舍：监听此时已经关掉（一条捕获已被消费/丢弃），所以界面上那一页会显示
        "登录未完成"（文案来自 `callback_server._page`，本层不改它），但**下一次轮询仍会
        把凭据拿回来** —— 用户看到的是"页面说没完成、列表里账号却出现了"这一处不一致，
        比"整条登录被一次碰撞打死"轻得多。根治要把 `pending` 一路传到那个页面，
        需要改 `callback_server.py`（本轮不在改动面内，已上报）。

        🔴 两阶段提交（M7-E）：投递**成功并已认领暂存**（`state["pending"]` 在场）的会话
        **必须留在表里** —— 出表 = 丢弃暂存 = 用户永远点不到「确定接入」。
        确认后的出表由 `commit_pending` 负责；取消 / TTL 由既有路径负责。
        """
        if session.state.get("pending"):
            logger.info("%s：回跳已认领暂存（待用户点「确定接入」落盘），会话保留",
                        session.product)
            return
        if str(getattr(listener, "state", "")) == "settled:failed:pending" \
                and session.last_delivery == "pending":
            logger.info("%s：回跳投递未落定（会话仍在等待轮询），端口已收", session.product)
            return
        self._drop(session.id)

    def _drop(self, session_id: str) -> None:
        """会话出表 + **关闭其回跳接收端** + **丢弃暂存凭据**（BD4 / M7-E）。

        🔴 三件都要做：会话表是有界内存；监听是**OS 资源**（端口/套接字）——只出表不关
        监听 = 端口泄漏 + 会话终态后还能被回跳打进（僵尸接收端）；**暂存凭据必须随会话
        一起消失**（两阶段提交的丢弃纪律：取消 / 超时 / 失败终态绝不允许把暂存凭据
        再落盘 —— 「确定接入」是唯一的落盘开关，过期未确认 = 不落盘）。
        """
        session = self._sessions.pop(session_id, None)
        if session is not None and session.state.pop("pending", None) is not None:
            logger.info("%s：会话 %s 出表，暂存凭据已丢弃（未确认接入）",
                        session.product, session.id)
        _close_callback(session)

    def _sweep(self) -> int:
        """清掉已超时的会话（正常路径下由 `_advance` 清理；这里兜"启动后就没人再轮询"）。"""
        now = self._now()
        dead = [sid for sid, s in self._sessions.items() if s.expired(now)]
        for sid in dead:
            self._drop(sid)                       # 出表顺带关监听（含未被轮询的会话）
        return len(dead)


#: 进程级共享引擎（入口层直接用下面的门面；单实例 = 会话表只有一份）
_ENGINE = LoginEngine()


async def _commit_outcome(session: LoginSession, outcome: LoginOutcome, *,
                          root: Path | None = None) -> None:
    """把成功的凭据经 `store.commit_login_async` 落盘（写回自检 + 失败整体回滚，§22.3）。

    🔴 **唯一实现**：两阶段提交第二段（`LoginEngine.commit_pending`，即用户点
    「确定接入」）经这里落盘；校验/续期等其它路径不经此、也不得自建落盘实现。
    落盘失败 → 状态翻成 `failed`、原因进 `detail`、凭据**不留在 outcome**（**不谎报成功**）。
    🔴 **A-1 接线**：异步路径必须走 `commit_login_async` —— 同步版在调用线程里等
    跨进程写锁（`_LOCK_WAIT_S` ≤1.0s）会把**整个事件循环**停摆（eng-a 实测打点间隔
    1007ms）；async 版把等锁/写盘/自检/物化整段下放工作线程，语义与同步版逐字一致。
    """
    try:
        await store.commit_login_async(session.product, session.name, outcome.credentials,
                                       outcome.meta, root=root)
    except store.WriteLockError as e:
        # 🔴 拒写（§22.8-4 fail closed）与"自检未通过"是**两回事**：抛它时一个字节都没写、
        #    也谈不上回滚（`store.WriteLockError` 的 docstring 明确禁止套用那句"已回滚"文案）。
        #    原先它落在捕获面之外 → 异常上抛、`outcome.state` 停在 `"success"`（eng-a-2 §1.4
        #    登记的缺口），与"落盘失败 → 翻 failed"的承诺不一致。
        outcome.state = "failed"
        outcome.detail = f"凭据落盘失败：写盘锁不可用（未落盘，一个字节都未写）：{e}"
        outcome.credentials = {}
    except (CommitError, ValueError, OSError) as e:
        outcome.state = "failed"
        outcome.detail = f"凭据落盘自检未通过（已回滚）：{type(e).__name__}: {e}"
        outcome.credentials = {}


async def start_login(product: str, *, name: str = "",
                      kind: LoginKind | None = None) -> LoginSession:
    """启动登录（门面：`POST /admin/api/accounts/login/start` → `{product, kind?}`）。"""
    return await _ENGINE.start(product, name=name, kind=kind)


async def poll_login(product: str, session_id: str) -> LoginOutcome:
    """轮询登录状态（门面：`POST /admin/api/accounts/login/poll`）。

    ⚠️ 两阶段提交（M7-E）：`success` 只表示**凭据已认领并暂存**（未落盘）；落盘要经
    `commit_pending`（用户点「确定接入」）。
    """
    return await _ENGINE.poll(product, session_id)


async def callback_login(product: str, session_id: str, params: dict) -> LoginOutcome:
    """回跳粘贴（门面：`POST /admin/api/accounts/login/callback`）。"""
    return await _ENGINE.callback(product, session_id, params)


async def commit_pending(session_id: str) -> dict:
    """确认接入（门面：`POST /admin/api/accounts/login/commit`）。

    两阶段提交第二段：把 `session.state["pending"]` 的暂存凭据经唯一落盘路径
    （`_commit_outcome` → `store.commit_login_async`）写进账号目录。
    幂等且**永不抛业务异常**：返回 `{"committed": bool, "account": str, "reason": str}`
    （重复确认 / 会话已出表 / 写盘失败都如实回报，见 `LoginEngine.commit_pending`）。
    """
    return await _ENGINE.commit_pending(session_id)


async def alt_call(product: str, session: LoginSession, name: str, /, **kwargs):
    """调用产品的**备选形态辅助钩子**（§22.3 补入③；入口层 `POST /admin/api/accounts/login/alt`）。

    示例：`await alt_call("raccoon", session, "sms_send", phone=..., captcha_param=...)`。

    - 表纪律：只认产品模块导出的 `_ALT_HOOKS`（**不给字符串 `getattr` 后门**）——
      未知名字当场 `KeyError`（消息列合法值）；产品未导出该表 → 可读 `RuntimeError`
      （本产品没有备选形态，不该被这样调用）。
    - 防串线：`session.product` 与 `product` 必须一致（会话表是全局的，入口层按 id 取到
      的会话可能配错产品 → 用 A 产品的钩子驱动 B 产品的会话只会得到无意义的 pending）。
    - 🔴 **会话纪律闸门（M6-6 收口，R1 F1）**：入口先过与 `_advance` **同一实现**
      （`_gate`）的取消/TTL 判定 —— 过期或已取消的会话返回
      `LoginOutcome(state="expired")`，**不派发钩子、不落盘凭据**。修前本函数是纯派发：
      `expired=True` 的会话仍能走完短信第二段并写出 `credentials.json`，
      §22.8-2「会话 TTL 与取消」这条硬清单被整条绕开。
    - 🔴 **成功只暂存、不落盘**（M7-E 两阶段提交）：钩子返回
      `LoginOutcome(state="success")` 时走**与 poll/callback 相同的认领暂存**
      （`_stage_pending` → `session.state["pending"]`，凭据一个字节都不写盘）——
      短信第二段（`sms_submit`）成功与其它四型一样，统一由向导的**唯一一次**
      「确定接入」（`commit_pending`）落盘；修前这里直接 `_commit_outcome` 落盘，
      会让短信型绕过确认步（与用户裁决相悖）。让位结局（另一通道已认领）如实返回。
      返回 `Challenge` 的钩子（如 raccoon `sms_send`）无凭据可认领，原样返回。
    - ⚠️ 本函数仍**不触碰会话表**（会话状态机归 `poll`/`callback` 的 `_advance`）：
      终态出表由后续确认/轮询/取消驱动，不由本函数代劳；过期会话的清理由
      `_sweep`/下一次 `poll` 完成（内存仍有界，TTL 判定不会因出表时机放宽）。
    """
    if session.product != product:
        raise ValueError(
            f"会话与产品不匹配：会话属于 {session.product!r}，却按 {product!r} 调用 "
            f"{name!r}（入口层取会话时配错了产品）")
    blocked = _gate(session, session.now or time.monotonic)
    if blocked is not None:
        return blocked                           # 过期/取消：不派发、不暂存（§22.8-2）
    result = await _alt_hook(product, name)(session, **kwargs)
    if isinstance(result, LoginOutcome) and result.state == "success":
        superseded = _stage_pending(session, result, channel=f"辅助调用（{name}）")
        if superseded is not None:
            return superseded
    return result


def cancel_login(session_id: str) -> bool:
    """取消登录会话（用户关掉向导弹窗时调用）。

    🔴 两阶段提交（M7-E）：取消 = 出表 + 关监听 + **丢弃暂存凭据** —— 登录成功但未点
    「确定接入」时取消，账号目录**不会**留下任何东西（`_drop` 统一做）。
    """
    return _ENGINE.cancel(session_id)


def get_session(session_id: str) -> LoginSession | None:
    """按会话 id 取会话对象（找不到 → None；入口层据此给可读 404）。"""
    return _ENGINE.get_session(session_id)


def shutdown_login() -> None:
    """清空共享引擎的会话表（进程退出钩子；`atexit` 已自动挂上）。"""
    _ENGINE.shutdown()


atexit.register(shutdown_login)
