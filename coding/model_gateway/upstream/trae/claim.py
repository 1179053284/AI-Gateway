"""TRAE 每日签到（`POST /trae/api/v2/ug/checkin_credits/{status,claim}`）。

协议（`trae-credits.ts:16-33`）::

    POST {UG_HOST}/trae/api/v2/ug/checkin_credits/status → {}
    → {checked_in: bool, credits: int64, enable: bool, streak_days, total_credits}
    POST {UG_HOST}/trae/api/v2/ug/checkin_credits/claim  → {}
    → {code: 0, message: "success"}          ← ⚠️ 只有这两个字段，**不含积分数**

## 🔴 幂等**只能**靠 status 端点的 `checked_in`（本模块存在的唯一理由）

claim 对「今天已签到」是**幂等**的：实测重复领取同样返回 `{code:0, message:"success"}`，
与真正领取成功**无法区分**（`jet-hub-rpc.ts:1801-1806`，用户报障「显示成功但 +0 积分」）。
claim 响应里也没有 `credits` 字段（早期实现读它恒为 0，`trae-credits.ts:280-288`）——
真实数值只在 status 的 `credits` 里。故：

1. `precheck=True`（§22.6 对 trae 的**强制**取值）：先查 status —— `checked_in` → 直接
   报 `already_done`（**不再发 claim**）；`enable=false` → `inactive`；
2. **claim 成功（code 0）后必须复核 status**（`trae-credits.ts:288-295` 同款）：
   `checked_in=true` → `success`（并带上 status 里的积分数）；状态未更新 → **不谎报成功**。

## 错误分类与冷却（照抄 `trae-credits.ts:74-100`，逐条可查）

| 条件 | 类型 | 冷却 |
|---|---|---|
| HTTP 200 + code 1005 | PlanLimit（权益不足） | 43200s（12h） |
| HTTP 429 | SoftRate（软限流） | 60s |
| HTTP 401 | SessionDead（登录态失效） | **-1 = 永久**（需重新登录） |
| HTTP 404 | NotFound | 60s |
| HTTP 5xx | Server | 600s |
| HTTP 其它 4xx | Client | 600s |
| 业务码 ≠ 0 | BusinessError | 300s |
| 成功 / 无码 | Unknown | 0（不冷却） |

⚠️ **9074（「签到人数过多」）不再换设备号重试**（`20 R14`：设备轮换代次机制**已废弃**，
`trae-credits.ts:265-276` 注释原文「设备轮换已废弃，不再重试」）→ 按 BusinessError 报
失败（冷却 300s，与该文件 `:268-276` 的 explicit 返回值同值）。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from model_gateway.accounts import net
from model_gateway.accounts.registry import get as registry_get
from model_gateway.accounts.types import ClaimOutcome
from model_gateway.upstream.trae import const, protocol


@dataclass(frozen=True)
class CheckinError:
    """签到错误分类（`trae-credits.ts:56-59` 的 `TraeCheckinError`）。"""

    type: str
    #: 冷却秒数（`-1` = 永久，`0` = 不冷却）。
    cooldown_secs: int


def classify_checkin_error(http_status: int, code: int | None) -> CheckinError:
    """按 HTTP 状态码 + 业务码分类（**逐行移植** `trae-credits.ts:74-100`）。

    判定顺序即优先级（照抄）：PlanLimit → SoftRate → SessionDead → NotFound →
    Server → Client → BusinessError → Unknown。
    """
    if http_status == 200 and code == const.CODE_PLAN_LIMIT:
        return CheckinError("PlanLimit", const.COOLDOWN_PLAN_LIMIT_S)
    if http_status == 429:
        return CheckinError("SoftRate", const.COOLDOWN_SOFT_RATE_S)
    if http_status == 401:
        return CheckinError("SessionDead", const.COOLDOWN_PERMANENT_S)
    if http_status == 404:
        return CheckinError("NotFound", const.COOLDOWN_NOT_FOUND_S)
    if 500 <= http_status < 600:
        return CheckinError("Server", const.COOLDOWN_SERVER_S)
    if 400 <= http_status < 500:
        return CheckinError("Client", const.COOLDOWN_CLIENT_S)
    if code is not None and code != 0:
        return CheckinError("BusinessError", const.COOLDOWN_BUSINESS_S)
    return CheckinError("Unknown", 0)


def failure_detail(error: CheckinError, message: str) -> str:
    """可读失败文案（把冷却表**如实带出**，供 ops/用户判断何时可重试）。"""
    text = message or "签到失败"
    if error.cooldown_secs == const.COOLDOWN_PERMANENT_S:
        return f"签到失败（{error.type}：登录态已失效，需重新登录）：{text}"
    if error.cooldown_secs > 0:
        return f"签到失败（{error.type}，建议冷却 {error.cooldown_secs}s）：{text}"
    return f"签到失败（{error.type}）：{text}"


@dataclass(frozen=True)
class CheckinStatus:
    """签到状态（`trae-credits.ts:186-209` 的 `fetchTraeCheckinStatus`）。

    `ok=False` = **查询本身失败**（网络/结构/业务码非 0）→ 与「活动未开启」
    （`ok=True` 且 `active=False`）严格区分：前者是异常，后者是正常业务状态。
    """

    ok: bool
    active: bool = False
    checked_in: bool = False
    credits: int = 0
    streak_days: int = 0
    detail: str = ""


async def fetch_checkin_status(cred: dict, uid: str) -> CheckinStatus:
    """查签到状态（**幂等判据的唯一来源**）。`uid` 为空 → 不发请求（上游受不了空身份）。"""
    access_token = protocol.read_str(cred, "access_token")
    if not access_token:
        return CheckinStatus(ok=False, detail="凭据缺少 access_token（未登录，未发请求）")
    if not uid:
        return CheckinStatus(ok=False, detail="凭据缺少 uid（无法构造签到设备身份，未发请求）")
    try:
        async with net.make_client(timeout=const.REQUEST_TIMEOUT_S) as client:
            response = await client.post(
                f"{const.UG_HOST}{const.PATH_CHECKIN_STATUS}",
                headers=protocol.checkin_headers(access_token, uid),
                json={})
    except httpx.HTTPError as e:
        return CheckinStatus(ok=False, detail=f"签到状态查询网络错误：{e}")
    if response.status_code != 200:
        return CheckinStatus(ok=False, detail=f"签到状态查询 HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        return CheckinStatus(ok=False, detail="响应不是 JSON（凭据失效时网关会回 HTML 错误页）")
    if not isinstance(body, dict):
        return CheckinStatus(ok=False, detail="签到状态响应不是对象")
    code = protocol.read_code(body)
    if code != 0:
        # DSH 同判据（`trae-credits.ts:193-195`）：业务码非 0 → 状态不可用（不当作「未签到」）
        return CheckinStatus(
            ok=False,
            detail=f"签到状态业务码 {code}：{protocol.message_of(body) or '未知原因'}")
    credits = protocol.read_num(body, "credits")
    streak = protocol.read_num(body, "streak_days")
    return CheckinStatus(
        ok=True,
        active=body.get("enable") is True,
        checked_in=body.get("checked_in") is True,
        credits=int(credits) if credits is not None else 0,
        streak_days=int(streak) if streak is not None else 0,
        detail="签到状态已取回",
    )


async def _claim_once(cred: dict, uid: str) -> tuple[int, object | None]:
    """发一次领取请求（**不重试**：网络重试属调用方/ops 的职责，§22.8-10）。"""
    access_token = protocol.read_str(cred, "access_token")
    async with net.make_client(timeout=const.REQUEST_TIMEOUT_S) as client:
        response = await client.post(
            f"{const.UG_HOST}{const.PATH_CHECKIN_CLAIM}",
            headers=protocol.checkin_headers(access_token, uid),
            json={})
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, None


async def claim(cred: dict, meta: dict, *, precheck: bool) -> ClaimOutcome:
    """签到（§22.6：结果语义 = ops 四类；`precheck` per-product 显式声明）。

    `precheck` 取值差异（**本产品必须 True**，§22.6 / `20 §3.1`）：

    - `True`：先查 status，已签到/活动未开启则**不发** claim（省一次无效请求，
      且避免把「今天已签到」报成「领取成功」—— 那正是用户报障的形态）；
    - `False`（**off-contract**，仅为契约完整而保留）：跳过预检直接领取；因 claim
      对已签到同样回 code 0，**仍以 claim 后的 status 复核定论**（见下）。
    """
    if not registry_get(const.PRODUCT_ID).capabilities.checkin:
        # 能力位是**判据**不是标签（§22.6）：不支持就别打必然失败的请求
        return ClaimOutcome(category="inactive",
                            detail="TRAE 未登记签到能力（能力位 checkin=False）")
    access_token = protocol.read_str(cred, "access_token")
    uid = protocol.read_str(cred, "uid") or protocol.read_str(meta, "uid")
    if not access_token:
        return ClaimOutcome(category="failed", detail="凭据缺少 access_token（未登录，未发请求）")
    if not uid:
        return ClaimOutcome(category="failed",
                            detail="凭据缺少 uid（无法构造签到设备身份，未发请求）")

    if precheck:
        status = await fetch_checkin_status(cred, uid)
        if status.ok:
            if not status.active:
                # DSH 同款文案（`jet-hub-rpc.ts:510-511`）
                return ClaimOutcome(category="inactive", detail="签到活动未开启")
            if status.checked_in:
                # 🔴 幂等：**只有这里**能判定「今天已签到」（claim 自身区分不了）
                return ClaimOutcome(category="already_done",
                                    detail=f"今天已签到（今日签到积分 {status.credits}）"
                                    if status.credits else "今天已签到")
        # `ok=False`（状态查不到）时**仍然尝试领取**：无法确认不代表不能领，
        # 交给 claim 与随后的 status 复核定夺（`jet-hub-rpc.ts:514-517` 原文语义）

    try:
        http_status, body = await _claim_once(cred, uid)
    except httpx.HTTPError as e:
        # 网络类（连接/超时）→ 可重试（claim 幂等：重放回 code 0，再以 status 定论）
        return ClaimOutcome(category="failed", retryable=True,
                            detail=f"签到请求网络错误（可重试）：{e}")

    if not isinstance(body, dict):
        # 非 JSON：凭据类（网关错误页）不重试；仅 HTTP 5xx（Server 瞬时）声明可重试
        return ClaimOutcome(
            category="failed", retryable=(500 <= http_status < 600),
            detail=f"签到响应不是 JSON（HTTP {http_status}），请检查凭据是否有效")
    code = protocol.read_code(body)
    message = protocol.message_of(body)
    if code == const.CODE_CHECKIN_BUSY:
        # 业务码 9074「签到人数过多」：`20 R14` 明确不再换设备/退避重试 → 保持不重试
        error = classify_checkin_error(http_status, code)
        return ClaimOutcome(
            category="failed",
            detail=failure_detail(error, message or "签到人数过多，请稍后再试"))
    if code != 0:
        # 分类里的 Server（5xx）声明可重试；PlanLimit/SoftRate/Client/BusinessError 不重试
        error = classify_checkin_error(http_status, code)
        return ClaimOutcome(
            category="failed", retryable=(error.type == "Server"),
            detail=failure_detail(error, message or f"业务码 {code}"))
    if not 200 <= http_status < 300:
        # 业务码 0 但 HTTP 非 2xx：以 HTTP 为准（不把异常响应当成功）；Server=5xx 可重试
        error = classify_checkin_error(http_status, None)
        return ClaimOutcome(category="failed",
                            retryable=(error.type == "Server"),
                            detail=failure_detail(error, f"HTTP {http_status} 但业务码为 0"))

    # ── 复核：claim 的 code 0 不足以判成功（幂等不可区分）→ 以 status 定论 ──
    status = await fetch_checkin_status(cred, uid)
    if status.ok and status.checked_in:
        streak = f"，连续 {status.streak_days} 天" if status.streak_days > 0 else ""
        return ClaimOutcome(category="success",
                            detail=f"签到成功：今日签到积分 {status.credits}{streak}")
    if status.ok:
        # 协议/一致性类（claim 回成功但状态没跟上）：重试同一动作不会改变服务端状态 → 不重试
        return ClaimOutcome(
            category="failed",
            detail="签到响应为成功（code=0）但状态未更新（status.checked_in=false），"
                   "请稍后重试或在 TRAE 客户端内确认")
    return ClaimOutcome(
        category="failed",
        detail=f"签到响应为成功（code=0）但结果无法确认（{status.detail}），不谎报成功")
