"""Raccoon 积分面：余额（三态）/ 一次性登录奖励 / 已领状态反查。

🗂 证据面：`src/raccoon-credits.ts` 全文（`:129-163` 余额、`:176-212` 登录奖励、
   `:228-258` 已领状态）、`src/jet-hub-rpc.ts:1437-1500`（`onboarding.status`）、
   `:1553-1600`（`onboarding.claim` 的 `earned` 语义）、`:1873-1888`（无签到端点的可读错误）；
   `docs/research/20 §3.1`（「每日 300 分服务端自动发放、无可调用签到端点」）。

🔴 **只读优先**（`raccoon-credits.ts:20-25`）：余额查询走**只读**的 `GET /points/v1/balance`；
   写端点（`login/points/grant`）只由 `claim_onboarding` 触发，绝不在"打开面板/探活"这类
   高频路径上顺带调用（Loomy 的 `first-login` 就踩过「打开面板即意外触发签到」的坑）。
🔴 三态语义（§22.3 / `23 B2`）：查不到 → `unknown`（**绝不写成 0** —— 那是"已用光"的语义）。
🔴 本模块不抛业务异常：积分面属"尽力而为"，批量操作时单账号失败不得中断其余账号
   （`raccoon-credits.ts:71-76` 的 `requestJson` 同样不抛）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from model_gateway.accounts import net
from model_gateway.accounts.types import ClaimOutcome, QuotaSnapshot
from model_gateway.upstream.raccoon import const as C
from model_gateway.upstream.raccoon import protocol as p

logger = logging.getLogger("model_gateway.upstream.raccoon")

#: 额度数据来源标识（`QuotaSnapshot.source`）
QUOTA_SOURCE = "raccoon-points"


@dataclass(frozen=True)
class OnboardingStatus:
    """一次性登录奖励的**已领状态**（`raccoon-credits.ts:228-258`）。"""

    claimed: bool
    #: 该奖励的积分数（账单里取到则用账单值，取不到用 `LOGIN_REWARD_POINTS`）
    points: int = C.LOGIN_REWARD_POINTS


async def quota(cred: dict | None) -> QuotaSnapshot:
    """余额快照：`GET /api/web/points/v1/balance`（只读，`raccoon-credits.ts:129-163`）。

    核心字段 `available_points`（缺它就说明响应形状不对 → `unknown`，`：145-147`）；
    分项池 `reward_points` / `daily_points` / `monthly_points`（>0 才列）/ `topup_points`
    （`:148-155`）。

    ⚠️ 会话栈里的 `daily_points` 是「每日积分池剩余」—— 它的充值是**服务端按日自动发放**的
    （无签到端点，`：12-18`），本函数**只读**、不触发发放。
    """
    token = p.access_token_of(cred)
    if not token:
        return QuotaSnapshot(state="unknown", source=QUOTA_SOURCE,
                             detail="凭据缺少 access_token（未登录，未发请求）")
    try:
        async with net.make_client(base_url=C.API_BASE, timeout=C.REQUEST_TIMEOUT_S) as client:
            resp = await client.get(C.BALANCE_PATH, headers=p.headers(cred))
            payload = _json_or_none(resp)
    except httpx.HTTPError as e:
        return QuotaSnapshot(state="unknown", source=QUOTA_SOURCE,
                             detail=f"积分余额查询网络错误：{e}")
    # 业务码与 HTTP 状态**合并判定**（照抄 DSH：`parseEnvelope` 把非 2xx 折进 code，
    # `raccoon-credits.ts:52-64,141`）——这样 200 却带非零 code 也能拿到服务端原因
    envelope = p.parse_envelope(payload, resp.status_code)
    if not envelope.ok or envelope.data is None:
        return QuotaSnapshot(state="unknown", source=QUOTA_SOURCE,
                             detail=f"积分余额查询失败（HTTP {resp.status_code}）："
                                    f"{envelope.error_text('响应不是合法信封')}")
    available = p.read_number(envelope.data, "available_points")
    if available is None:
        return QuotaSnapshot(state="unknown", source=QUOTA_SOURCE,
                             detail="响应缺少 available_points（形状变更？）")
    pools: list[str] = []
    items: list[dict] = []
    for key, label in (("reward_points", "奖励积分"), ("daily_points", "每日积分"),
                       ("monthly_points", "会员积分"), ("topup_points", "充值积分")):
        value = p.read_number(envelope.data, key)
        if value is None:
            continue
        # 会员池为 0 时不列（`raccoon-credits.ts:154`：`monthly > 0` 才 push）
        if key == "monthly_points" and value <= 0:
            continue
        pools.append(f"{label} {_num(value)}")
        items.append({"name": label, "unit": "积分", "remaining": value,
                      "total": None, "used": None, "active": True, "expires_at": ""})
    detail = f"可用 {_num(available)} 积分"
    detail += f"（构成：{' / '.join(pools)}）" if pools else "（服务端未给分项）"
    # 无套餐概念，分池即套餐表达（raccoon-credits.ts:148-155）；daily 池 = 每日刷新分桶。
    return QuotaSnapshot(state="available" if available > 0 else "exhausted",
                         source=QUOTA_SOURCE, detail=detail, items=tuple(items))


async def onboarding_status(cred: dict | None) -> OnboardingStatus | None:
    """登录奖励是否已领：`GET /points/v1/bills` 反查（`raccoon-credits.ts:228-258`）。

    判据 = 账单里存在 `biz_type == 'reward_grant'` **且** `event_name == '桌面端登录奖励'`
    的记录（`:249-255`）。

    ⚠️ **不能靠余额推断**（余额是多来源合计，`:220-222`）；
    ⚠️ **不能只按 `biz_type` 判定**（「新人注册礼包」也是 `reward_grant`，`:221-224`）；
    ⚠️ **服务端没有单独的奖励状态端点**（实测），故只能查账单明细（`:224`）。

    返回 `None` = **查不到**（网络/非 200/形状不认识）—— 调用方据此"仍然尝试领取"
    （服务端幂等，宁可让用户多点一次，也不要误报"已领"让他真的错过，`:225-226`）。
    """
    if not p.access_token_of(cred):
        return None
    params = {"paging.limit": "50", "paging.offset": "0"}
    try:
        async with net.make_client(base_url=C.API_BASE, timeout=C.REQUEST_TIMEOUT_S) as client:
            resp = await client.get(C.BILLS_PATH, headers=p.headers(cred), params=params)
            payload = _json_or_none(resp)
    except httpx.HTTPError as e:
        logger.warning("[raccoon] 账单反查网络错误（按未领取处理）：%s", e)
        return None
    envelope = p.parse_envelope(payload, resp.status_code)
    if not envelope.ok or envelope.data is None:
        return None
    items = envelope.data.get("items")
    if not isinstance(items, list):
        return None
    for raw in items:
        if not isinstance(raw, dict):
            continue
        if raw.get("biz_type") != C.BILL_BIZ_REWARD_GRANT:
            continue
        if raw.get("event_name") != C.LOGIN_REWARD_EVENT_NAME:
            continue
        points = p.read_number(raw, "points")
        return OnboardingStatus(
            claimed=True,
            points=int(points) if points is not None and points > 0 else C.LOGIN_REWARD_POINTS)
    return OnboardingStatus(claimed=False)


async def grant_login_reward(cred: dict | None) -> ClaimOutcome:
    """领取「桌面端登录奖励」：`POST /api/web/desktop/v1/login/points/grant`（`raccoon-credits.ts:176-212`）。

    🔴 **必需 `X-Client-Platform` 头**（`raccoon-credits.ts:87-90,171-173`；值见
    `raccoon-product.ts:175-183`）——猜错会被拒。
    🔴 **幂等判据 = 响应体 `granted`**（重复领取同样 HTTP 200 + `granted:false`，`:197-200`）；
    故 `granted !== true` → `already_done`（**不是** `failed`：它不是错误，是正常状态；也不是
    `success`——那会让用户以为每天都真的加了额度）。
    """
    token = p.access_token_of(cred)
    if not token:
        # 凭据类：未发请求 → 不重试
        return ClaimOutcome(category="failed", detail="凭据缺少 access_token（未登录，未发请求）")
    headers = p.headers(cred, platform=C.client_platform(), version=C.CLIENT_VERSION)
    try:
        async with net.make_client(base_url=C.API_BASE, timeout=C.REQUEST_TIMEOUT_S) as client:
            resp = await client.post(C.LOGIN_POINTS_GRANT_PATH, headers=headers)
            payload = _json_or_none(resp)
    except httpx.HTTPError as e:
        # 网络类（连接/超时）→ 可重试；服务端幂等（granted 判据）→ 重放不改终态
        return ClaimOutcome(category="failed", retryable=True,
                            detail=f"登录奖励领取网络错误：{e}")
    if payload is None:
        # 非 JSON：凭据类（网关 HTML 错误页）不重试；仅 HTTP 5xx 声明可重试
        return ClaimOutcome(category="failed", retryable=(resp.status_code >= 500),
                            detail=f"登录奖励响应不是 JSON（HTTP {resp.status_code}），"
                                   "请检查凭据是否有效")
    envelope = p.parse_envelope(payload, resp.status_code)
    if not envelope.ok:
        # 信封业务码（无 code 字段时按 HTTP 状态兜底）→ 5xx 兜底可重试；其余不重试
        return ClaimOutcome(
            category="failed", retryable=(resp.status_code >= 500),
            detail=f"登录奖励领取失败（HTTP {resp.status_code}）："
                   f"{envelope.error_text('服务端未给原因')}")
    data = envelope.data if isinstance(envelope.data, dict) else {}
    if data.get("granted") is not True:
        return ClaimOutcome(category="already_done",
                            detail="该账号已领取过桌面端登录奖励（每号一次）")
    popup = data.get("popup") if isinstance(data.get("popup"), dict) else {}
    points = p.read_number(popup, "points")
    amount = int(points) if points is not None and points > 0 else C.LOGIN_REWARD_POINTS
    return ClaimOutcome(category="success", detail=f"已领取桌面端登录奖励 {amount} 积分")


def _num(value: float) -> str:
    """数值展示（整数不带小数点，照 buddy 的 `:g` 口径）。"""
    return f"{value:g}"


# R2a-F-5（2026-10-06）：实现收编到 `upstream/_text.py`（一份实现，6 处同包抄写消灭）。
from model_gateway.upstream._text import json_or_none as _json_or_none  # noqa: F401 — 再导出
