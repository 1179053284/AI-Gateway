"""LobsterAI 每日签到 —— **三步**：slot → context → check_in。

协议（`src/lobsterai-credits.ts:8-27` 的三步说明 + `:163-295` 的实现）::

    0) 版本号（必填参数）：GET {clientVersionApi} → data.value.version
    1) 查活动槽位  GET  /api/client-activities/slot?placement=…&clientVersion=…
    2) 查活动上下文 GET /api/client-activities/{activityCode}/context?configRevision=…
    3) 签到        POST /api/client-activities/{activityCode}/actions/check_in

认证是**纯 Bearer、无签名**（`sigin.py:32-48`）。

## 幂等（**客户端幂等**，与 CodeBuddy 靠服务端 `code:10001` 不同）

两道都要做（`lobsterai-credits.ts:219-259`）：

- **预检**：`state.claimedToday` **且** `actions` 含 `check_in` —— 只看前者会漏掉
  「活动有但今天不该领」的情形；
- **幂等键**：签到请求体带 `idempotencyKey`（UUID4，`lobsterai-credits.ts:266`，
  对齐 Go `sigin.py:63` 的 uuid4），服务端据此去重。

## `precheck` 形参（§22.3 冻结签名 / §22.6 per-product 声明）

本产品**领取流程自身就是预检**（上面两个 GET 先判幂等）→ 两种取值行为一致；外部再查
一次状态纯属重复请求（`20 §3.2` 五条不变式第 5 条；DSH 对 lobsterai 显式传
`precheckStatus: false`，`jet-hub-rpc.ts:1782-1787`）。不在此处"支持 true 就多查一次"的
理由是**没有可查的对象**：本产品没有独立状态端点（`credits.status` 对 lobsterai 如实
返回 `null`，`jet-hub-rpc.ts:1688-1702`）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib.parse import quote, urlencode

from model_gateway.accounts.types import ClaimOutcome
from model_gateway.upstream.lobsterai import const, login, protocol


@dataclass(frozen=True)
class ActivitySlot:
    """活动槽位（第一步的 `data`；`ok=False` = 查询本身失败）。"""

    ok: bool
    state: str = ""
    code: str = ""
    revision: float = 0.0
    detail: str = ""
    #: 🔴 查询失败是否属**网络/5xx 类**（§22.6 失败退避的口径；由 `fetch_slot` 按
    #: 结构化事实置位：传输异常 → True；HTTP 5xx → True；业务码/凭据/结构 → False）。
    #: 只给批量执行器用；`detail` 仍是给人读的文案（重试判据**不看文案**）。
    retryable: bool = False


@dataclass(frozen=True)
class ActivityContext:
    """活动上下文（第二步的 `data`；`ok=False` = 查询本身失败）。"""

    ok: bool
    claimed_today: bool = False
    actions: tuple[str, ...] = ()
    detail: str = ""
    #: 同 `ActivitySlot.retryable`（网络/5xx 类失败的**结构化**声明）。
    retryable: bool = False


def _revision_text(value: float) -> str:
    """`configRevision` 的 query/body 取值（DSH 是 JS number：`12345` 而非 `12345.0`）。"""
    return f"{value:g}"


def _revision_value(value: float) -> int | float:
    """`configRevision` 进 JSON body 时保持整数形态（避免序列化成 `12345.0`）。"""
    return int(value) if float(value).is_integer() else value


async def fetch_slot(cred: dict, client_version: str) -> ActivitySlot:
    """第一步：查活动槽位（`lobsterai-credits.ts:163-191`）。

    三个固定 query 参数照抄真实客户端观察值（`placement=desktop_sidebar` 声明投放位、
    `containerApiVersion=2` 是容器协议版本、`platform=win32` 是**伪装客户端形态**）。
    返回 `ok=False` 表示查询失败（网络/信封/结构问题），与「无可用活动」
    （`ok=True` 且 `state != "available"`）**严格区分** —— 前者是异常、后者是正常业务状态。
    """
    query = urlencode({
        "placement": const.SLOT_PLACEMENT,
        "clientVersion": client_version,
        "containerApiVersion": const.SLOT_CONTAINER_API_VERSION,
        "platform": const.SLOT_PLATFORM,
    })
    result = await protocol.fetch_json(f"{const.API_BASE}{const.PATH_ACTIVITY_SLOT}?{query}",
                                       headers=protocol.auth_headers(cred))
    if not result.reachable:
        # 网络类（传输层失败）→ 可重试（只读 GET，重放安全）
        return ActivitySlot(ok=False, detail=f"网络失败：{result.error}", retryable=True)
    if not isinstance(result.body, dict):
        # 非 JSON（凭据失效的 HTML 页）→ 不重试；仅 HTTP 5xx 声明可重试
        return ActivitySlot(ok=False, detail=protocol.non_json_reason(result),
                            retryable=(result.status >= 500))
    envelope = protocol.parse_envelope(result.body)
    if not envelope.ok:
        # 信封业务码 → 不重试；仅 HTTP 5xx 兜底声明可重试
        return ActivitySlot(ok=False, detail=protocol.envelope_failure(
            result, envelope, "活动槽位查询失败"),
            retryable=(result.status >= 500))
    activity = envelope.data.get("activity")
    activity = activity if isinstance(activity, dict) else {}
    revision = protocol.read_num(activity, "configRevision")
    return ActivitySlot(ok=True,
                        state=protocol.read_str(envelope.data, "slotState"),
                        code=protocol.read_str(activity, "activityCode"),
                        revision=revision if revision is not None else 0.0)


async def fetch_context(cred: dict, slot: ActivitySlot) -> ActivityContext:
    """第二步：查活动上下文（今天领了没、有哪些可用动作，`lobsterai-credits.ts:198-217`）。"""
    path = f"{const.PATH_ACTIVITY_CONTEXT}/{quote(slot.code, safe='')}/context"
    query = urlencode({"configRevision": _revision_text(slot.revision)})
    result = await protocol.fetch_json(f"{const.API_BASE}{path}?{query}",
                                       headers=protocol.auth_headers(cred))
    if not result.reachable:
        # 网络类 → 可重试（只读 GET）
        return ActivityContext(ok=False, detail=f"网络失败：{result.error}", retryable=True)
    if not isinstance(result.body, dict):
        # 非 JSON：凭据类不重试；仅 HTTP 5xx 声明可重试
        return ActivityContext(ok=False, detail=protocol.non_json_reason(result),
                               retryable=(result.status >= 500))
    envelope = protocol.parse_envelope(result.body)
    if not envelope.ok:
        # 信封业务码 → 不重试；仅 HTTP 5xx 兜底声明可重试
        return ActivityContext(ok=False, detail=protocol.envelope_failure(
            result, envelope, "活动上下文查询失败"),
            retryable=(result.status >= 500))
    state = envelope.data.get("state")
    state = state if isinstance(state, dict) else {}
    return ActivityContext(ok=True,
                           claimed_today=protocol.read_bool(state, "claimedToday"),
                           actions=tuple(protocol.read_str_list(envelope.data, "actions")))


def _granted_credit(data: dict) -> float:
    """签到响应的积分三级回退：`creditsGranted` → `rewardCredits` → `credits`。

    不同活动/版本用不同字段名（`lobsterai-credits.ts:278-285`，对齐 `sigin.py:65-66`）。
    取不到 → 0（**不编造**：宁可显示 0 也不猜一个数）。
    """
    result = data.get("result")
    result = result if isinstance(result, dict) else {}
    for key in ("creditsGranted", "rewardCredits", "credits"):
        value = protocol.read_num(result, key)
        if value is not None:
            return value
    return 0.0


async def claim_daily(cred: dict, *, precheck: bool) -> ClaimOutcome:
    """执行每日签到领取（三步全流程；`claim` 钩子的实现）。

    判定顺序（把「业务正常状态」与「真失败」严格分开，`lobsterai-credits.ts:225-232`）：

    | 情形 | 结果类别 |
    |---|---|
    | 无 `access_token` | `failed`（凭据未配置，需用户处理） |
    | 槽位查询失败 | `failed` |
    | `slotState != available` 或无 activityCode | `inactive`（正常业务状态） |
    | 上下文查询失败 | `failed` |
    | `claimedToday` | `already_done`（正常业务状态） |
    | `actions` 不含 `check_in` | `inactive`（未开始 / 已结束 / 无资格） |
    | 领取请求失败或信封异常 | `failed` |
    | 成功 | `success`（积分取三级回退链） |

    `precheck` 的语义见模块头（本产品两种取值行为一致，因为流程自带预检）。
    """
    if not protocol.read_str(cred, "access_token"):
        # 凭据类：未发请求 → 不重试（`retryable=False` 缺省）
        return ClaimOutcome(category="failed", detail="凭据缺少 access_token，请重新登录")
    client_version = await login.client_version()
    slot = await fetch_slot(cred, client_version)
    if not slot.ok:
        # 重试性**继承查询阶段的结构化判据**（网络/5xx → True），不猜 `slot.detail` 文案
        return ClaimOutcome(category="failed", retryable=slot.retryable,
                            detail=f"活动槽位查询失败：{slot.detail}")
    if slot.state != "available" or not slot.code:
        return ClaimOutcome(category="inactive",
                            detail=f"无可用活动（slotState={slot.state}）")
    context = await fetch_context(cred, slot)
    if not context.ok:
        return ClaimOutcome(category="failed", retryable=context.retryable,
                            detail=f"活动上下文查询失败：{context.detail}")
    if context.claimed_today:
        return ClaimOutcome(category="already_done", detail="今天已签到")
    if "check_in" not in context.actions:
        return ClaimOutcome(category="inactive", detail="当前不可签到（未开始/已结束/无资格）")

    path = f"{const.PATH_ACTIVITY_CONTEXT}/{quote(slot.code, safe='')}/actions/check_in"
    result = await protocol.fetch_json(
        f"{const.API_BASE}{path}", method="POST", headers=protocol.auth_headers(cred),
        body={
            "configRevision": _revision_value(slot.revision),
            # 客户端幂等键（对齐 `sigin.py:63` 的 uuid4）：服务端据此去重。
            "idempotencyKey": str(uuid.uuid4()),
            "payload": {},
        })
    if not result.reachable:
        # 网络类（传输层失败）→ 可重试；签到带客户端幂等键 → 重放不改终态
        return ClaimOutcome(category="failed", retryable=True,
                            detail=f"签到请求网络失败：{result.error}")
    if not isinstance(result.body, dict):
        # 非 JSON：凭据类不重试；仅 HTTP 5xx 声明可重试
        return ClaimOutcome(category="failed", retryable=(result.status >= 500),
                            detail=protocol.non_json_reason(result))
    envelope = protocol.parse_envelope(result.body)
    if not envelope.ok:
        # 信封业务码 → 不重试；仅 HTTP 5xx 兜底声明可重试
        return ClaimOutcome(category="failed", retryable=(result.status >= 500),
                            detail=protocol.envelope_failure(
                                result, envelope, f"签到失败（code={envelope.code}）"))
    granted = _granted_credit(envelope.data)
    body = envelope.data.get("result")
    message = protocol.read_str(body if isinstance(body, dict) else {}, "message")
    detail = f"签到成功，获得 {granted:g} 积分"
    if message:
        detail = f"{detail}（{message}）"
    return ClaimOutcome(category="success", detail=detail)
