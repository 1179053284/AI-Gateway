"""Loomy 积分：探活 / **两池**额度 / 每日签到 / 新手任务。

🗂 证据面（只读）：DSH `src/loomy-credits.ts`（两池与签到）、`src/loomy-onboarding.ts`
   （8 任务 10000 分）、`src/loomy-auth.ts:363-402`（探活端点）、`src/jet-hub-rpc.ts:1725-1847`
   （签到无独立状态端点 / 领取自带幂等判据）。

## 两个积分池（用户补充确认的机制；`loomy-credits.ts:5-37`）

- **永久积分**：注册奖励 5000 + 新手任务 10000（响应字段 `balance`）
- **每日赠送池**：每天 5000，**消耗后不回补**（响应字段 `dailyBalance` = `dailyQuota - dailyConsumed`）
- 实测（2026-09-26）：`balance: 15000`、`dailyBalance: 4992`、`availableBalance: 19992`（两者之和）

⚠️ `dailyQuota` **只在 `first-login` 的响应里**（`points/records` 不返回它）→ 未签到时该字段
   缺省，**不要硬编码 5000**（额度可能随活动变化，`loomy-credits.ts:25-28`）。

## 读与写严格分离（`loomy-credits.ts:30-37`）

| 动作 | 端点 | 性质 |
|---|---|---|
| 探活 / 查余额 | `GET /points/records` | **只读**，无副作用 |
| 一键签到 | `POST /points/first-login` | 写，幂等（判据 `alreadyProcessed`） |

这样「打开面板」不会悄悄触发签到。

## 永久积分锁定（**本波次不实现为钩子**，M6-3 口径登记）

「锁定永久积分」（只消耗每日池）在 DSH 是**本地策略开关**（`credits.permanentLock` RPC +
`permanent-lock-store.ts` 持久化），它不产生任何上游调用，只影响**选号/门控**。而本网关的
选路归 `core/resources.py`（§22.5-6：**不建第二套调度**）→ 该策略在本项目的落点不是产品钩子面，
而是能力位 `permanent_lock=True`（已在 `accounts/registry.py` 登记）+ 后续入口/调度侧的本地开关。
故本模块**没有** `permanent_lock` 钩子：本地策略不得伪装成上游调用（避免"点了必然失败"的按钮）。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import httpx

from model_gateway.accounts.registry import get as registry_get
from model_gateway.accounts.types import ClaimOutcome, ProbeResult, QuotaSnapshot
from model_gateway.upstream.loomy import api
from model_gateway.upstream.loomy import constants as C
from model_gateway.upstream.loomy import envelope

logger = logging.getLogger("model_gateway.accounts")

#: 本产品标识（与 `accounts/registry.py` 的键一致）
PRODUCT = "loomy"


# ── 请求基建（统一走 `api.py`；见其模块头的纪律）───────────────────────

def _checkin_supported() -> bool:
    """签到能力位（判据不是标签，§22.6：唯一事实源 = `accounts/registry.py`）。"""
    return registry_get(PRODUCT).capabilities.checkin


def _onboarding_supported() -> bool:
    """新手任务能力位（同上；`20 §3.1`：loomy / raccoon 为 ✓）。"""
    return registry_get(PRODUCT).capabilities.onboarding


# ── 探活（`loomy-auth.ts:363-402`）─────────────────────────────────────

async def probe(cred, meta) -> ProbeResult:
    """探活：连通 / 凭据有效两维分开（§22.3）。

    判据端点 = `GET /points/records`（`loomy-auth.ts:363-370`：最便宜的只读端点、
    **不消耗积分、无副作用**，且认证语义与其它业务端点一致）。
    ⚠️ 传输层失败**不能**判为终态（网络抖动不该让用户重新登录，`loomy-auth.ts:381-385`）→
       `reachable=False`；`100002` = 凭据失效（Loomy 无续期端点，只能重新登录，`:396-400`）。
    """
    del meta  # 形参按 §22.3 保留：本产品无设备身份、无私有文件（`20 §2.7`）
    token = api.access_token_of(cred)
    if not token:
        return ProbeResult(reachable=False, valid=False,
                           detail="凭据缺少 access_token（未登录，未发请求）")
    try:
        status, body = await api.request("GET", C.POINTS_RECORDS_PATH, token=token)
    except httpx.HTTPError as e:
        return ProbeResult(reachable=False, valid=False, detail=f"上游不可达：{e}")
    if not isinstance(body, dict):
        return ProbeResult(reachable=True, valid=False,
                           detail=f"响应不是 JSON（HTTP {status}），无法判定凭据状态")
    parsed = envelope.parse(body)
    if parsed.ok:
        return ProbeResult(reachable=True, valid=True, detail="凭据有效")
    if parsed.code == C.AUTH_ERROR_CODE:
        return ProbeResult(reachable=True, valid=False,
                           detail=f"凭证已失效，请重新登录（{parsed.message}；Loomy 无续期端点）")
    # 其余业务码：凭据状态未知 → fail closed（§22.8-5：不得把「读不懂」当「健康」）。
    return ProbeResult(reachable=True, valid=False,
                       detail=f"上游拒绝（业务码 {parsed.code}）：{parsed.message}")


# ── 两池额度（`loomy-credits.ts:109-152`）──────────────────────────────

@dataclass(frozen=True)
class PointsSummary:
    """两池明细（`loomy-credits.ts:52-66` 的 `LoomyCreditDetail` 的搬运形态）。"""

    #: 永久积分（`balance`）。
    permanent: int
    #: 每日赠送池余额（`dailyBalance`；缺失按 0 计，`loomy-credits.ts:138`）。
    daily: int
    #: 永久 + 每日（`availableBalance`，缺失时本地相加；`loomy-credits.ts:141`）。
    total: int
    #: 每日额度上限 —— **仅签到后可得**（`first-login` 专有字段）。
    daily_quota: int | None = None
    #: 今日已消耗 —— 仅签到后可得。
    daily_consumed: int | None = None
    #: 每日额度所属业务日（`YYYY-MM-DD`）—— 仅签到后可得。
    daily_cycle_date: str = ""


def _read_number(value: object) -> int | None:
    """把任意值读成有限数；非法返回 None（**不编造 0**；`loomy-credits.ts:109-113` 的 `Number()` + `isFinite`）。

    ⚠️ 显式排除 `bool`：JSON 的 `true/false` 不该被读成 1/0（DSH 的 `Number(true)` 会读成 1，
       那是 JS 的坑，不是我们要照抄的语义）。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)          # 与 JS `Number(value)` 同宽容（数字 + 数字串）
    except (TypeError, ValueError):
        return None
    return int(number) if math.isfinite(number) else None


def summarize_points(data: object) -> PointsSummary | None:
    """按两池口径归一化响应（`loomy-credits.ts:123-152`）。

    ⚠️ 永久池字段名**随端点不同**（都取自上游，不是猜的）：
       `points/records` 用 `balance`（`loomy-credits.ts:135`），`points/first-login` 用
       `permanentBalance`（`loomy-credits.ts:22-25` 的响应样例；同处还有 `currentBalance`）
       → 按 `balance → permanentBalance → currentBalance` 取第一个可读值。
    ⚠️ 三者都读不到 → 返回 `None`（**不编造数字**，上层映射成 `unknown`），
       与「余额真的为 0」严格区分（§22.3「未知不当零」）。
    """
    if not isinstance(data, dict):
        return None
    permanent = None
    for name in ("balance", "permanentBalance", "currentBalance"):
        permanent = _read_number(data.get(name))
        if permanent is not None:
            break
    if permanent is None:
        return None
    daily = _read_number(data.get("dailyBalance")) or 0
    available = _read_number(data.get("availableBalance"))
    cycle = data.get("dailyCycleDate")
    return PointsSummary(
        permanent=permanent,
        daily=daily,
        total=available if available is not None else permanent + daily,
        daily_quota=_read_number(data.get("dailyQuota")),
        daily_consumed=_read_number(data.get("dailyConsumed")),
        daily_cycle_date=cycle if isinstance(cycle, str) else "",
    )


def _pool_detail(summary: PointsSummary) -> str:
    """两池的人读明细（签到与额度共用；**分开列两个池**，不合并成一个数）。"""
    detail = f"永久积分 {summary.permanent} + 每日赠送 {summary.daily} = 可用 {summary.total}"
    if summary.daily_quota is not None:
        consumed = summary.daily_consumed if summary.daily_consumed is not None else 0
        detail += (f"（每日额度 {summary.daily_quota}，今日已消耗 {consumed}，"
                   f"业务日 {summary.daily_cycle_date or '未知'}）")
    return detail


async def quota(cred, meta) -> QuotaSnapshot:
    """额度快照：`available` / `exhausted` / `unknown` —— **未知不当零**（§22.3 / `23 B2`）。

    两池合并成一个可用总量（`availableBalance`）；池间差异（每日会作废、永久不失效）在
    `detail` 里分开列。**池级分档/永久锁**是本地选路策略（见模块头的口径），不在本钩子。
    """
    del meta  # 形参按 §22.3 保留（同 probe 的说明）
    source = "loomy-points-records"
    token = api.access_token_of(cred)
    if not token:
        return QuotaSnapshot(state="unknown", source=source,
                             detail="凭据缺少 access_token（未登录，未发请求）")
    try:
        status, body = await api.request("GET", C.POINTS_RECORDS_PATH, token=token)
    except httpx.HTTPError as e:
        return QuotaSnapshot(state="unknown", source=source, detail=f"额度查询网络错误：{e}")
    if not isinstance(body, dict):
        return QuotaSnapshot(state="unknown", source=source,
                             detail=f"响应不是 JSON（HTTP {status}）")
    parsed = envelope.parse(body)
    if not parsed.ok:
        # ⚠️ 凭据失效 / 结构异常都只是「没查到」→ unknown（不得映射成 exhausted 让选路停用资源）。
        return QuotaSnapshot(state="unknown", source=source,
                             detail=f"业务码 {parsed.code}：{parsed.message}")
    summary = summarize_points(parsed.data)
    if summary is None:
        return QuotaSnapshot(state="unknown", source=source,
                             detail="响应缺少 balance/permanentBalance 字段（结构变更？）")
    # 两池即套餐表达（loomy-credits.ts:5-9）：永久积分 + 每日赠送（每日会作废的分桶）。
    items = ({"name": "永久积分", "unit": "积分", "remaining": summary.permanent,
              "total": None, "used": None, "active": True, "expires_at": ""},
             {"name": "每日赠送", "unit": "积分", "remaining": summary.daily,
              "total": summary.daily_quota, "used": summary.daily_consumed,
              "active": True, "expires_at": ""})
    return QuotaSnapshot(state="available" if summary.total > 0 else "exhausted",
                         source=source, detail=_pool_detail(summary), items=items)


# ── 签到：每日赠送额度（`loomy-credits.ts:195-244`）────────────────────

async def claim(cred, meta, *, precheck: bool) -> ClaimOutcome:
    """一键签到：`POST /points/first-login` 触发每日赠送额度（§22.6 四类结果）。

    ⚠️ 语义**不是**「+5000 积分」：`dailyBalance = dailyQuota − dailyConsumed`，消耗后不回补
       （`loomy-credits.ts:195-200`、`loomy.js` 的 `LOOMY_DAILY_QUOTA_DESCRIPTION`）。
    ⚠️ 幂等判据 = 响应体 `alreadyProcessed`（重复调用同样 HTTP 200）→ 已处理映射成
       `already_done` 而**不是** success（后者会让用户以为每天都真的加了额度，`:202-204`）。
    ⚠️ `precheck`：本产品**两种取值行为一致** —— 领取流程自带幂等判据，**不做额外预检**
       （`jet-hub-rpc.ts:1826-1827`「领取流程自带幂等判据（alreadyProcessed），故不做额外预检」；
       且本产品**没有**独立的签到状态端点，`:1725-1730`）。不在此处"支持 true 就多查一次"的
       假动作（同 lobsterai 的口径）。
    """
    del meta, precheck  # 形参按 §22.3 保留；`precheck` 语义见上（两取值一致）
    if not _checkin_supported():
        return ClaimOutcome(
            category="inactive",
            detail="Loomy 未登记签到能力（能力位 checkin=False，`20 §3.1`）")
    token = api.access_token_of(cred)
    if not token:
        return ClaimOutcome(category="failed", detail="凭据缺少 access_token（未登录，未发请求）")
    try:
        status, body = await api.request("POST", C.POINTS_FIRST_LOGIN_PATH, token=token, body={})
    except httpx.HTTPError as e:
        # 网络类（连接/超时）→ 可重试；签到自身幂等（alreadyProcessed）→ 重放不改终态
        return ClaimOutcome(category="failed", retryable=True,
                            detail=f"签到请求网络错误：{e}")
    if not isinstance(body, dict):
        # 非 JSON：凭据类（网关错误页）不重试；仅 HTTP 5xx（服务端瞬时）声明可重试
        return ClaimOutcome(category="failed", retryable=(status >= 500),
                            detail=f"签到响应不是 JSON（HTTP {status}），请检查凭据是否有效")
    parsed = envelope.parse(body)
    if not parsed.ok:
        # 业务码类：重试同一次请求不会改变码的语义 → 不重试
        return ClaimOutcome(category="failed",
                            detail=f"业务码 {parsed.code}：{parsed.message or '签到失败'}")
    data = parsed.data if isinstance(parsed.data, dict) else {}
    summary = summarize_points(data)
    if data.get("alreadyProcessed") is True:
        tail = f"（{_pool_detail(summary)}）" if summary is not None else ""
        return ClaimOutcome(category="already_done", detail=f"今日额度已初始化{tail}")
    if summary is None:
        return ClaimOutcome(category="success",
                            detail=f"已触发{C.DAILY_QUOTA_DESCRIPTION}（响应未下发分值字段，不折算具体分值）")
    # 首次处理：本次新发放额度 = dailyQuota − dailyConsumed（服务端不直接给这个差值，
    # `loomy-credits.ts:236-241`）；两者缺一时不折算（不编造）。
    if summary.daily_quota is not None and summary.daily_consumed is not None:
        granted = max(0, summary.daily_quota - summary.daily_consumed)
        return ClaimOutcome(
            category="success",
            detail=(f"已触发{C.DAILY_QUOTA_DESCRIPTION}（本次发放 {granted} 分 = "
                    f"dailyQuota {summary.daily_quota} − dailyConsumed {summary.daily_consumed}）"))
    return ClaimOutcome(
        category="success",
        detail=f"已触发{C.DAILY_QUOTA_DESCRIPTION}（响应未下发 dailyQuota/dailyConsumed，不折算具体分值）")


# ── 新手任务：8 个 10000 分一次性（`loomy-onboarding.ts`）───────────────

def normalize_tasks(raw: object) -> dict[str, bool]:
    """把服务端下发的 tasks 按本地表归一（缺的补 False、多余的忽略；`loomy-onboarding.ts:99-109`）。"""
    source = raw if isinstance(raw, dict) else {}
    return {key: source.get(key) is True for key in C.TASK_POINTS}


def local_earned(tasks: dict[str, bool]) -> int:
    """按**本地**分值表现算已领积分（不采信服务端 `earned`；`loomy-onboarding.ts:94-97`）。"""
    return sum(points for key, points in C.TASK_POINTS.items() if tasks.get(key) is True)


def _task_label(key: str) -> str:
    """任务的人读标签 `key（标题）`（标题表 = `loomy-onboarding.ts:58-67`；失败文案用）。"""
    title = C.TASK_TITLES.get(key)
    return f"{key}（{title}）" if title else key


async def claim_onboarding(cred, meta, *, precheck: bool) -> ClaimOutcome:
    """一次性新手任务：8 任务共 10000 分（§22.3 可选钩子，capability=onboarding）。

    ⚠️ 服务端**不校验前置行为**（决定性实测，`loomy-onboarding.ts:4-14`）：8 个任务逐个
       `POST /complete` 全部返回成功，**没有真的发对话/生成 PPT/装技能** —— 完成条件全在
       客户端本地判定，服务端只做「幂等置位 + 加分」→ 本实现是**纯 API 直领**，不花一个 token。
    ⚠️ 幂等判据是响应体的 `alreadyCompleted`（**不是** HTTP 码、**不是** `code`）；
       重复调用**视为成功**（`loomy-onboarding.ts:180-200`）。
    ⚠️ **不采信服务端 `earned`**，按本地 `TASK_POINTS` 现算（`loomy-onboarding.ts:26-28`：
       官方自己也这么做，`:177-183` 明说不信任）。
    ⚠️ `precheck`：本产品**两种取值行为一致** —— 状态查询是**流程必需**（要据此跳过已完成项、
       避免对已完成任务发必然重放的请求），DSH 也是无条件先查状态（`loomy-onboarding.ts:209-237`）。
    ⚠️ 收到 `100002`（凭据失效）**立即中断**，不再对后续任务发请求（否则是一串必然失败的请求，
       `loomy-onboarding.ts:204-207`）；已领的部分如实报在 detail 里（不谎报全成）。
    """
    del meta, precheck  # 形参按 §22.3 保留；`precheck` 语义见上（两取值一致）
    if not _onboarding_supported():
        return ClaimOutcome(
            category="inactive",
            detail="Loomy 未登记新手任务能力（能力位 onboarding=False，`20 §3.1`）")
    token = api.access_token_of(cred)
    if not token:
        # 凭据类：未发请求 → 不重试
        return ClaimOutcome(category="failed", detail="凭据缺少 access_token（未登录，未发请求）")

    try:
        status, body = await api.request("GET", C.ONBOARDING_TASKS_PATH, token=token)
    except httpx.HTTPError as e:
        # 网络类 → 可重试（状态查询是只读 GET，重放安全）
        return ClaimOutcome(category="failed", retryable=True,
                            detail=f"新手任务状态查询网络错误：{e}")
    if not isinstance(body, dict):
        # 非 JSON：凭据类不重试；仅 HTTP 5xx 声明可重试
        return ClaimOutcome(category="failed", retryable=(status >= 500),
                            detail=f"新手任务状态响应不是 JSON（HTTP {status}）")
    parsed = envelope.parse(body)
    if not parsed.ok:
        # 业务码类（含 100002 凭据失效）→ 不重试：重放只会得到同一串业务拒绝
        return ClaimOutcome(category="failed",
                            detail=f"新手任务状态查询失败：业务码 {parsed.code}：{parsed.message}")
    data = parsed.data if isinstance(parsed.data, dict) else {}
    tasks = normalize_tasks(data.get("tasks"))
    pending = [key for key in C.TASK_POINTS if not tasks[key]]
    if not pending:
        return ClaimOutcome(
            category="already_done",
            detail=(f"8 个新手任务已全部领取（本地分值表现算 "
                    f"{local_earned(tasks)}/{C.ONBOARDING_TOTAL} 分）"))

    claimed: list[str] = []
    claimed_points = 0
    for key in pending:
        try:
            step_status, step_body = await api.request(
                "POST", C.ONBOARDING_COMPLETE_PATH, token=token, body={"key": key})
        except httpx.HTTPError as e:
            # 网络类 → 可重试（单任务 `/complete` 幂等：重放回 alreadyCompleted 同样算成功）
            return ClaimOutcome(
                category="failed", retryable=True,
                detail=(f"已完成 {len(claimed)} 个任务（{claimed_points} 分）后中断："
                        f"任务 {_task_label(key)}请求网络错误：{e}"))
        if not isinstance(step_body, dict):
            # 非 JSON：凭据类不重试；仅 HTTP 5xx 声明可重试
            return ClaimOutcome(
                category="failed", retryable=(step_status >= 500),
                detail=(f"已完成 {len(claimed)} 个任务（{claimed_points} 分）后中断："
                        f"任务 {_task_label(key)}响应不是 JSON（HTTP {step_status}）"))
        step = envelope.parse(step_body)
        if not step.ok:
            # 业务码类（含 100002 凭据失效）→ 不重试：后续任务同样会被拒
            return ClaimOutcome(
                category="failed",
                detail=(f"已完成 {len(claimed)} 个任务（{claimed_points} 分）后中断："
                        f"任务 {_task_label(key)}失败（业务码 {step.code}：{step.message}）；"
                        f"凭据失效时请重新登录后再领"))
        # 无论服务端回 alreadyCompleted 与否都记为已领（幂等重放同样算成功）。
        claimed.append(key)
        claimed_points += C.TASK_POINTS[key]

    next_tasks = {**tasks, **{key: True for key in claimed}}
    return ClaimOutcome(
        category="success",
        detail=(f"已领取 {len(claimed)} 个新手任务共 {claimed_points} 分"
                f"（本地分值表现算，未采信服务端 earned；累计 "
                f"{local_earned(next_tasks)}/{C.ONBOARDING_TOTAL} 分，"
                f"此前已完成 {len(pending) - len(claimed)} 个）"))
