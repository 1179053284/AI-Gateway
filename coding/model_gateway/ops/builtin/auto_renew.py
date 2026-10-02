"""**自动续期 / 批量续期**（2026-10-01 用户裁决三条之两条）。

裁决原文拆译：
1. 「有续期就应该知道当前登录态还有多久失效，在失效前 2h 就应该自动续期」
   → 定时腿（cron tick）在 claim / query_balance 两条腿之后加**续期腿**：
   登录态将在 `AUTO_RENEW_WITHIN_S` 内失效的账号逐个续期；
2. 「产品维度也应该增加批量续期操作，执行时对该产品下所有 5h 内失效的账号批量操作续期」
   → `POST /admin/api/accounts/{product}/refresh-due`（管理端卡头「批量续期」钮）。

🔴 四条纪律：
- **失效时刻的唯一解析器 = `accounts/credexp.credential_expiry_ms`**（各产品字段形态
  收敛在一处；本模块不各自解 JWT / 不各自认键名）；
- **取不到失效时刻 = 不续**（`skipped:"no-expiry"` 如实上报）——"没有到期信息"绝不
  被当成"快到期"去做写盘动作，与「未知不当零」同尺；
- **冷却 `RENEW_COOLDOWN_S`**：同一账号 30 分钟内只续一次（:8300 实测逼出来的：cline 令牌
  寿命 ~1h < 2h 窗口，无冷却就会逐轮空转轮换）；
- **终态不再重试**：钩子抛 `NotRefreshable`（如 raccoon 的 refresh_token 已死 / 业务码 200003）
  → 记 `terminal` 并停止自动重试，等用户重新登录（界面倒计时会显示"已过期，需重新登录"）。
  续期一旦成功就清掉终态标记。台账落在 `runtime.json` 的 `renew` 键。
- **启用位口径分开**：定时腿带 `enabled_of`（BD1：停用账号运营跳过）；手动「批量续期」
  **不传** = 与单账号续端点同一条 §22.6 正交语义（停用账号也可续）。

单账号续期的权威实现仍在 `api/admin_accounts.py::account_refresh`（409/502 契约与
既有测试钉着它）；本模块的 `refresh_one` 是**批量腿的内核**（不抛异常、逐账号隔离，
§22.8-6 同款），两者调的是同一个产品 `refresh` 钩子 + 同一个 `commit_login_async`。
"""

from __future__ import annotations

import datetime as dt
import logging
import time

from model_gateway.accounts import registry as account_registry
from model_gateway.accounts import store as accounts_store
from model_gateway.accounts.credexp import credential_expiry_ms
from model_gateway.accounts.types import NotRefreshable
from model_gateway.ops.builtin import product_hooks

logger = logging.getLogger("model_gateway.ops")

#: 定时腿阈值（秒）：登录态 2 小时内将失效 → 自动续期（用户裁决 2026-10-01）
AUTO_RENEW_WITHIN_S = 2 * 3600
#: 卡头「批量续期」默认窗口（秒）：5 小时内失效的账号批量续期（用户裁决 2026-10-01）
BATCH_RENEW_WITHIN_S = 5 * 3600
#: 同一账号两次续期的最小间隔（秒）——**实测逼出来的护栏**：
#: cline 的 access token 寿命只有 ~1h，小于 2h 窗口 → 续完立刻又"到期"，
#: :8300 真实盘上观察到 22:40:15 / 22:45:15 逐轮空转轮换令牌。冷却把"每轮一次"压成"每 30 分钟一次"。
RENEW_COOLDOWN_S = 1800

#: 续期台账写在 `runtime.json` 的 `renew` 键（运营态归运营态；`commit_login` 的不变式④
#: 保证续凭据落盘时不会洗掉它，反之本键也不碰凭据/额度键——读-改-写只动 `renew`）。


def _now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _age_s(iso: str) -> float:
    """`_now_iso()` 写出的本地时间距今秒数；解析不出 = 无穷大（当作"没续过"，保守放行）。"""
    try:
        return max(0.0, (dt.datetime.now()
                         - dt.datetime.fromisoformat(str(iso))).total_seconds())
    except (TypeError, ValueError):
        return float("inf")


def _renew_state(product: str, name: str) -> dict:
    """读 `runtime.json` 的续期台账；读不动 = 空台账（**不因此拒绝续期**，只少一层保护）。"""
    try:
        state = accounts_store.read_runtime(product, name).get("renew")
    except Exception as e:  # noqa: BLE001 — 台账读不动不该阻断运营动作
        logger.warning("续期台账读不动（%s/%s → 按空台账处理）：%s: %s",
                       product, name, type(e).__name__, e)
        return {}
    return state if isinstance(state, dict) else {}


def _patch_renew(product: str, name: str, patch: dict) -> None:
    """读-改-写 `runtime.json` 的 `renew` 键（只动这一个键）。"""
    try:
        current = accounts_store.read_runtime(product, name)
    except Exception as e:  # noqa: BLE001 — 文件坏了不覆盖（fail closed），记日志
        logger.warning("续期台账写入跳过（%s/%s 运行态读不动）：%s: %s",
                       product, name, type(e).__name__, e)
        return
    renew = dict(current.get("renew") or {})
    renew.update(patch)
    current["renew"] = renew
    try:
        accounts_store.write_runtime(product, name, current)
    except Exception as e:  # noqa: BLE001 — 台账写失败不影响本次动作结果，但必须留痕
        logger.warning("续期台账写入失败（%s/%s）：%s: %s", product, name, type(e).__name__, e)


def refreshable_products() -> tuple[str, ...]:
    """能力位 `refresh=True` 的产品（**从注册表推导**，与界面按钮同一判据）。"""
    return tuple(pid for pid in account_registry.PRODUCT_IDS
                 if account_registry.get(pid).capabilities.refresh)


async def refresh_one(product: str, name: str) -> dict:
    """续期一个账号：`refresh` 钩子 → `commit_login_async(via="refresh")`。

    返回 `{"account","product","ok","skipped"?,"detail"}`；**不抛**（批量逐账号隔离）。
    空返回值不覆盖旧凭据（与单账号端点同一纪律）。
    成败都写续期台账（`attempted_at` 供冷却；`NotRefreshable` 是**终态** → 记 `terminal`
    并停止后续自动重试，直到用户重新登录——实测 raccoon 的 refresh_token 已死，
    不记终态就会每 60s 撞一次 401）。
    """
    entry = {"account": name, "product": product}
    try:
        cred = accounts_store.load_credentials(product, name)
        meta = accounts_store.hook_meta(product, name)
        new_cred = await product_hooks.hook_of(product, "refresh")(cred, meta)
    except NotRefreshable as e:
        _patch_renew(product, name, {"terminal": str(e), "attempted_at": _now_iso()})
        return {**entry, "ok": False, "detail": f"不可续期：{e}"}
    except Exception as e:  # noqa: BLE001 — 单账号失败隔离（§22.8-6）
        _patch_renew(product, name, {"attempted_at": _now_iso(), "last_error": f"{type(e).__name__}: {e}"})
        return {**entry, "ok": False, "detail": f"{type(e).__name__}: {e}"}
    if not isinstance(new_cred, dict) or not new_cred:
        _patch_renew(product, name, {"attempted_at": _now_iso(), "last_error": "续期未返回新凭据"})
        return {**entry, "ok": False, "detail": "续期未返回新凭据（不覆盖旧凭据）"}
    try:
        await accounts_store.commit_login_async(product, name, new_cred, {}, via="refresh")
    except Exception as e:  # noqa: BLE001 — 落盘失败必须留痕，不谎报成功
        _patch_renew(product, name, {"attempted_at": _now_iso(), "last_error": str(e)})
        return {**entry, "ok": False, "detail": f"续期已取回但落盘失败：{type(e).__name__}: {e}"}
    # 成功：清掉终态标记（重新登录/上游恢复后自动续期腿要能再工作）
    _patch_renew(product, name, {"attempted_at": _now_iso(), "terminal": "", "last_error": ""})
    return {**entry, "ok": True, "detail": "凭据已续期并落盘"}


async def refresh_due(*, within_s: int = BATCH_RENEW_WITHIN_S,
                      product: str | None = None,
                      enabled_of=None) -> list[dict]:
    """批量续期窗口内的账号：`product=None` = 全部可续期产品；给出 = 只该产品。

    窗口判据 = `credential_expiry_ms ≤ now + within_s`；**不在窗口内的账号不列入结果**
    （按钮回执只说"动了谁"，不刷全量清单）。三类**不发起动作但如实上报**：
    `no-expiry`（失效时刻取不到，不猜）、`terminal`（上游判不可续期，等重新登录）、
    `cooldown`（`RENEW_COOLDOWN_S` 内刚续过，防逐轮空转）。
    """
    products = (product,) if product else refreshable_products()
    deadline_ms = time.time() * 1000 + within_s * 1000
    out: list[dict] = []
    for pid in products:
        if not account_registry.get(pid).capabilities.refresh:
            continue
        for name in accounts_store.list_accounts(pid):
            if enabled_of is not None and not enabled_of(name):
                continue
            try:
                cred = accounts_store.load_credentials(pid, name)
            except Exception as e:  # noqa: BLE001 — 凭据读不动 = 该账号失败隔离
                out.append({"account": name, "product": pid, "ok": False,
                            "detail": f"凭据读不动：{type(e).__name__}: {e}"})
                continue
            expiry = credential_expiry_ms(cred)
            if expiry is None:
                out.append({"account": name, "product": pid, "ok": True,
                            "skipped": "no-expiry",
                            "detail": "登录态失效时间未知（不猜、不续）"})
                continue
            if expiry > deadline_ms:
                continue
            state = _renew_state(pid, name)
            if state.get("terminal"):
                out.append({"account": name, "product": pid, "ok": True,
                            "skipped": "terminal",
                            "detail": f"上游判不可续期，需重新登录：{state['terminal']}"})
                continue
            if _age_s(state.get("attempted_at") or "") < RENEW_COOLDOWN_S:
                out.append({"account": name, "product": pid, "ok": True,
                            "skipped": "cooldown",
                            "detail": f"{RENEW_COOLDOWN_S // 60} 分钟内已续期过，本轮跳过"})
                continue
            out.append(await refresh_one(pid, name))
    return out
