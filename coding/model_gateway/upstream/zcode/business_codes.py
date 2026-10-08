# -*- coding: utf-8 -*-
"""ZCode 业务错误码 → 网关错误类别（**转发路径**的归一化真相，2026-10-08）。

## 为什么需要本模块

ZCode 用 **`200` + 自有信封** 表达业务错误（`{"code":1005,"msg":"exceed quota limit"}`），
而 `anthropic_out._shape_error` 原先对**所有**这类信封一律 `status_code=None`
→ `RETRYABLE`。后果（2026-10-08 实盘）：

- `1005`（额度耗尽）被当成"网络抖动"⇒ **短冷却 + 计 C**，同一条额度尽的号被反复打
  （实测一轮换号连撞 6 个号、每个各 2 次），而正确动作是**长冷却**（官方
  `providerBusinessError.ts` 明写 `1005 → refresh-quota`；DSH `trae-credits.ts:65`
  同码 → 43200s）。
- `3007`（安全校验拒绝）、`3010`（模型并发上限）等同样各归各类，不能一律可重试。

⇒ 本模块把**官方归因表**逐字搬进来，让出站层按码翻译，而不是一律 `RETRYABLE`。

## 判据来源（逐字取证，不扩写）

1. **官方归因表**：`ZCode/packages/ui/src/lib/chatErrorAttributionEvidence.ts:20-57`
   （39 条 `code → failureReason`，含 `429`）；
2. **官方 HTTP 对照**：`ZCode/packages/ui/src/lib/providerBusinessError.ts:1-17`
   （`1006→200 跳登录` / `1005→200 禁用入口刷配额` / `3006→400 换模型` /
   `3001→400 查请求体` / `3007→403 联系支持` / `3010→429 升级横幅` / `3002·429→429 限流` /
   `3102→400 闲时票据到期` / `2007→500 可重试`）；
3. **DSH 处置**：`trae-credits.ts:65-78`（200+1005 → PlanLimit 43200s）、
   `model-gate.ts:15`（1005 = 额度用尽等到明天）。

## 分类口径（把官方 `failureReason` 翻成**该做什么**，不是照抄文案）

| 官方 reason | 我们的类别 | 动作 |
|---|---|---|
| `quota_exhausted` / `rate_limited` | `QUOTA` | 长冷却（额度）或短退避（限流）—— 既有 `QUOTA` 分支已区分 `quota_retry` |
| `auth_failed` | `AUTH` | 凭据问题 ⇒ 停用该资源（既有语义） |
| `model_not_found` | `NOT_FOUND` | 模型层问题 ⇒ invalidate（既有语义） |
| `plan_expired` / `plan_access_denied` | `RESOURCE_UNAVAILABLE` | 换号 + 冷却该条（不 disable、不计 C，见该类别定义） |
| `server_error` / `network_error` / `provider_overloaded` | `RETRYABLE` | 重试/换号（既有语义） |
| `invalid_request` / `context_exceeded` | `BAD_REQUEST` | 原样透传（换谁都不行） |

🔴 **`3012` 是唯一例外**：官方把它归 `invalid_request`（请求内容问题），但我们已实测
它由**缺身份块**触发、且带**账号惩罚梯度**（30min→24h→停用），故保留既有
`RISK_CONTROL_TYPE` 通道处置（首试即 30min bench + 不换号止损）。本表**不覆盖**它。
"""

from __future__ import annotations

from model_gateway.core.errors import ErrorClass

#: 官方归因表：业务码 → 官方 `failureReason`（`chatErrorAttributionEvidence.ts:20-57`）。
#: 逐字搬运，**不含** `3012`（见模块 docstring 的例外说明）。
OFFICIAL_FAILURE_REASONS: dict[int, str] = {
    1005: "quota_exhausted",
    1006: "auth_failed",
    1120: "server_error",
    1210: "invalid_request",
    1211: "model_not_found",
    1214: "model_not_found",
    1230: "server_error",
    1234: "network_error",
    1261: "context_exceeded",
    1301: "invalid_request",
    1302: "rate_limited",
    1303: "rate_limited",
    1304: "quota_exhausted",
    1305: "rate_limited",
    1308: "quota_exhausted",
    1309: "plan_expired",
    1310: "quota_exhausted",
    1311: "plan_access_denied",
    1312: "provider_overloaded",
    1313: "quota_exhausted",
    1314: "quota_exhausted",
    1315: "quota_exhausted",
    1316: "quota_exhausted",
    1317: "quota_exhausted",
    1318: "quota_exhausted",
    1319: "quota_exhausted",
    1320: "quota_exhausted",
    1321: "quota_exhausted",
    2007: "server_error",
    3001: "invalid_request",
    3002: "rate_limited",
    3006: "model_not_found",
    3007: "auth_failed",
    3008: "rate_limited",
    3009: "rate_limited",
    3010: "rate_limited",
    1213: "invalid_request",
}

#: 官方 `failureReason` → 网关 `ErrorClass`（口径见模块 docstring 的表）。
REASON_TO_CLASS: dict[str, ErrorClass] = {
    "quota_exhausted": ErrorClass.QUOTA,
    "rate_limited": ErrorClass.QUOTA,
    "auth_failed": ErrorClass.AUTH,
    "model_not_found": ErrorClass.NOT_FOUND,
    "plan_expired": ErrorClass.RESOURCE_UNAVAILABLE,
    "plan_access_denied": ErrorClass.RESOURCE_UNAVAILABLE,
    "server_error": ErrorClass.RETRYABLE,
    "network_error": ErrorClass.RETRYABLE,
    "provider_overloaded": ErrorClass.RETRYABLE,
    "invalid_request": ErrorClass.BAD_REQUEST,
    "context_exceeded": ErrorClass.BAD_REQUEST,
}


def classify_business_code(code: object) -> ErrorClass | None:
    """业务码 → 类别；**认不出返回 `None`**（调用方保持既有兜底，不猜）。

    `3012` 显式返回 `None`：它有自己的通道处置（`RISK_CONTROL_TYPE` +
    `risk_control` 标记），不从这里走（见模块 docstring 的例外说明）。
    """
    try:
        n = int(code)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if n == 3012:
        return None
    reason = OFFICIAL_FAILURE_REASONS.get(n)
    if reason is None:
        return None
    return REASON_TO_CLASS.get(reason)
