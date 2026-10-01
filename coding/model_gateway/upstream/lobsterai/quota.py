"""LobsterAI 额度（余额）与探活：同一个端点 `GET /api/user/profile-summary`。

为什么两件事放一个模块：它们打的是**同一个只读端点**（`src/lobsterai-credits.ts:40`
`LOBSTERAI_PROFILE_SUMMARY_PATH`），分开写会让端点/请求头/解析各分叉一份
（该文件自己的注释就记录了「两处各定义一份同名常量」的教训，`lobsterai.ts:37-44`）。

## 三条口径

① **未知不当零**（§22.3 三态 / `23 B2`）：`unknown`（查不到）与 `exhausted`（确实为 0）
   **必须分开** —— 前者不能据此停用资源，后者选路可跳过。照抄 DSH 的
   `fetchLobsteraiCreditBalance` 语义：`totalCreditsRemaining` 为 0 **且**拿不到明细
   → 视为「查不到」而不是「余额为 0」（`lobsterai-credits.ts:384-390`：该字段缺失时
   `readNumber` 返回 0，会把「解析失败」伪装成「0 积分」）。
② 负数一律 **clamp 到 0**（照抄 Go `client.go:303-308`）：超额扣费/计量回滚等异常下
   上游可能下发负值，原样透出会让界面显示「-12.5 积分」，既无意义又误导。
③ 探活只验「连通 / 凭据有效」两个维度（§22.3），**不烧额度**：用这个只读端点而不是
   DSH 的对话探活（`account-probe.ts:208-214` 会发真实对话请求，会消费积分）。
"""

from __future__ import annotations

from dataclasses import dataclass

from model_gateway.accounts.types import ProbeResult, QuotaSnapshot
from model_gateway.upstream.lobsterai import const, protocol

#: 余额数据的来源标签（写进 `QuotaSnapshot.source`：事后能判断结论出自哪个通道）
SOURCE = "profile-summary"


@dataclass(frozen=True)
class Balance:
    """余额解析结果。`known=False` = **查不到**（与「余额为 0」严格区分）。"""

    known: bool
    total: float = 0.0
    item_count: int = 0
    detail: str = ""


def _round2(value: float) -> float:
    """规整到两位小数（服务端可能给 `55.67000031` 这类浮点表示，`lobsterai-credits.ts:398-406`）。"""
    return round(value, 2)


def _balance_from(data: dict) -> Balance:
    """从 `profile-summary` 的 `data` 判余额三态（判定顺序见模块头 ①②）。"""
    raw_total = protocol.read_num(data, "totalCreditsRemaining")
    raw_items = data.get("creditItems")
    items = [item for item in raw_items if isinstance(item, dict)] \
        if isinstance(raw_items, list) else None
    item_sum = sum(
        max(0.0, protocol.read_num(item, "creditsRemaining") or 0.0)
        for item in (items or []))
    numeric = raw_total if raw_total is not None else (item_sum if items else None)
    if numeric is None:
        return Balance(known=False,
                       detail="响应既无 totalCreditsRemaining 也无可用 creditItems（视作查不到）")
    total = _round2(max(0.0, numeric))
    if total == 0 and not items:
        # 照抄 DSH：0 且拿不到明细 → 查不到，**不当 0**（`lobsterai-credits.ts:384-390`）。
        return Balance(known=False, detail="余额为 0 且无积分明细（照 DSH 口径视作查不到，不当 0）")
    return Balance(known=True, total=total, item_count=len(items or []))


async def fetch_balance(cred: dict) -> Balance:
    """查询账号积分余额（`lobsterai-credits.ts:310-396`）。

    ⚠️ 端点用 `profile-summary` 而非 `/api/user/quota`：后者只显示 `freeCreditsTotal=300`、
    **不含活动积分**（实测某账号 profile-summary 5297.72 / quota 300）。
    """
    result = await protocol.fetch_json(f"{const.API_BASE}{const.PATH_PROFILE_SUMMARY}",
                                       headers=protocol.auth_headers(cred))
    if not result.reachable:
        return Balance(known=False, detail=f"余额查询网络失败：{result.error}")
    if not isinstance(result.body, dict):
        return Balance(known=False, detail=protocol.non_json_reason(result))
    envelope = protocol.parse_envelope(result.body)
    if not envelope.ok:
        return Balance(known=False,
                       detail=protocol.envelope_failure(result, envelope, "余额查询失败"))
    return _balance_from(envelope.data)


async def quota_snapshot(cred: dict) -> QuotaSnapshot:
    """额度快照（§22.3 三态 + `source`；**未知不当零**）→ `quota` 钩子的实现。"""
    balance = await fetch_balance(cred)
    if not balance.known:
        return QuotaSnapshot(state="unknown", source=SOURCE, detail=balance.detail)
    items = f"（{balance.item_count} 个积分包）" if balance.item_count else ""
    state = "exhausted" if balance.total <= 0 else "available"
    return QuotaSnapshot(state=state, source=SOURCE,
                         detail=f"余额 {balance.total:g} 积分{items}")


async def probe_credential(cred: dict) -> ProbeResult:
    """探活（§22.3：连通 / 凭据有效**两个维度分开**）→ `probe` 钩子的实现。

    四条判定（顺序即优先级）：
    1. 凭据里没有 `access_token` → 不发请求（`reachable=False`，别把本地缺凭据报成"网络不通"）；
    2. 传输层失败 → `reachable=False`（连通不成立）；
    3. HTTP 401/403 或响应体命中会话终止标记 → `reachable=True, valid=False`（凭据被拒）；
    4. 信封 `code:0` 且 `data` 是对象 → 两维都过（**上游以业务成功认可了该凭据**）。
    其余（非 JSON / 非终态业务失败）→ `reachable=True, valid=False` 并带原因：
    没拿到业务成功就**不宣称凭据有效**（方向与 §22.8-5 fail closed 一致）。
    """
    if not protocol.read_str(cred, "access_token"):
        return ProbeResult(reachable=False, valid=False,
                           detail="凭据缺少 access_token（未发起请求）")
    result = await protocol.fetch_json(f"{const.API_BASE}{const.PATH_PROFILE_SUMMARY}",
                                       headers=protocol.auth_headers(cred))
    if not result.reachable:
        return ProbeResult(reachable=False, valid=False, detail=f"连通失败：{result.error}")
    if result.status in (401, 403):
        return ProbeResult(reachable=True, valid=False,
                           detail=f"凭据被拒（HTTP {result.status}）")
    if not isinstance(result.body, dict):
        return ProbeResult(reachable=True, valid=False, detail=protocol.non_json_reason(result))
    envelope = protocol.parse_envelope(result.body)
    if not envelope.ok:
        if protocol.is_session_dead(result.text):
            return ProbeResult(reachable=True, valid=False,
                               detail=f"会话已终止（需重新登录）：{envelope.message}")
        return ProbeResult(reachable=True, valid=False,
                           detail=f"上游未以业务成功响应：{envelope.message}")
    return ProbeResult(reachable=True, valid=True, detail=f"{SOURCE} 正常")
