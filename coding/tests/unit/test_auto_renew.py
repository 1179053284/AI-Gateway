"""`ops/builtin/auto_renew` 的判据（2026-10-01 用户裁决：失效前 2h 自动续期 + 产品级批量续期）。

钉四条：
1. 参与面 = 能力位 `refresh=True` 的产品（**从注册表推导**，loomy/zcode 天然不进）；
2. **窗口判据**：只有登录态在 `within_s` 内失效的账号被续；远期账号一个字节都不动；
3. **未知不续**：解析不出失效时刻 → 列入回执并标 `skipped:"no-expiry"`，**不发起写盘**；
4. `enabled_of`（定时腿）跳过停用账号；不传（手动批量按钮）= 与 §22.6 正交语义一致；
   单账号失败（钩子抛错 / 空返回值）**不中断批量**（§22.8-6 失败隔离）。
"""

from __future__ import annotations

import time

from model_gateway.accounts import store
from model_gateway.accounts.types import NotRefreshable
from model_gateway.ops.builtin import auto_renew, product_hooks


def _seed(product: str, name: str, cred: dict, meta: dict | None = None) -> None:
    store.commit_login(product, name, cred, meta or {})


def _ms_ahead(seconds: float) -> str:
    return str(int((time.time() + seconds) * 1000))


def _install(monkeypatch, calls: list, *, fail: str = "", empty: str = "") -> None:
    async def hook(cred, meta):
        if fail and meta.get("account") == fail:
            raise RuntimeError("上游炸了")
        if empty and meta.get("account") == empty:
            return {}
        calls.append(meta.get("account"))
        return {**cred, "token": "NEW"}

    monkeypatch.setattr(product_hooks, "hook_of", lambda product, name: hook)


def test_participants_derive_from_the_refresh_matrix():
    got = auto_renew.refreshable_products()
    assert "buddy" in got and "trae" in got
    assert "loomy" not in got and "zcode" not in got, "不可续期产品混进批量腿 = 每轮白跑"


async def test_window_selection_unknown_not_renewed_and_enabled_leg(monkeypatch):
    calls: list = []
    _install(monkeypatch, calls)
    _seed("buddy", "due-1h", {"token": "A", "expires_at": _ms_ahead(3600)}, {})
    _seed("buddy", "far-10d", {"token": "B", "expires_at": _ms_ahead(10 * 86400)}, {})
    _seed("buddy", "no-expiry", {"token": "C"}, {})
    _seed("buddy", "off-due", {"token": "D", "expires_at": _ms_ahead(600)}, {"enabled": False})

    # 定时腿（带 enabled_of）：停用账号跳过
    results = await auto_renew.refresh_due(
        within_s=auto_renew.AUTO_RENEW_WITHIN_S, product="buddy",
        enabled_of=lambda name: name != "off-due")
    assert calls == ["due-1h"], f"窗口/停用判据失真：{calls}"
    assert {r["account"] for r in results} == {"due-1h", "no-expiry"}, "未知要如实列出"
    skipped = [r for r in results if r["account"] == "no-expiry"][0]
    assert skipped["skipped"] == "no-expiry" and skipped["ok"] is True
    assert store.load_credentials("buddy", "far-10d")["token"] == "B", "窗口外被误续"
    assert store.load_credentials("buddy", "no-expiry")["token"] == "C", "未知被当成到期"
    assert store.load_credentials("buddy", "due-1h")["token"] == "NEW"

    # 手动批量腿（不传 enabled_of）：停用账号也续（§22.6 与启用位正交）；
    # 但 due-1h 刚被上一腿续过 → 进冷却（`RENEW_COOLDOWN_S`，:8300 实测 cline 逐轮空转逼出的护栏）
    calls.clear()
    results = await auto_renew.refresh_due(within_s=auto_renew.AUTO_RENEW_WITHIN_S,
                                           product="buddy")
    assert calls == ["off-due"], f"正交语义/冷却护栏失真：{calls}"
    cooled = [r for r in results if r.get("skipped") == "cooldown"]
    assert [r["account"] for r in cooled] == ["due-1h"], f"冷却未生效：{results}"


async def test_single_account_failure_is_isolated(monkeypatch):
    """一个账号抛错 / 返回空 → 只记它自己的失败，其余照常续（§22.8-6）。"""
    calls: list = []
    _install(monkeypatch, calls, fail="bad-boom", empty="bad-empty")
    _seed("buddy", "bad-boom", {"token": "X", "expires_at": _ms_ahead(60)}, {})
    _seed("buddy", "bad-empty", {"token": "Y", "expires_at": _ms_ahead(60)}, {})
    _seed("buddy", "good", {"token": "Z", "expires_at": _ms_ahead(60)}, {})
    results = await auto_renew.refresh_due(within_s=3600, product="buddy")
    by = {r["account"]: r for r in results}
    assert by["bad-boom"]["ok"] is False and "RuntimeError" in by["bad-boom"]["detail"]
    assert by["bad-empty"]["ok"] is False and "不覆盖旧凭据" in by["bad-empty"]["detail"]
    assert by["good"]["ok"] is True
    assert store.load_credentials("buddy", "bad-empty")["token"] == "Y", "空返回值覆盖了旧凭据"


async def test_not_refreshable_is_reported_not_raised(monkeypatch):
    async def nor(cred, meta):
        raise NotRefreshable("本产品凭据不可续期")
    monkeypatch.setattr(product_hooks, "hook_of", lambda product, name: nor)
    _seed("buddy", "nr-1", {"token": "T", "expires_at": _ms_ahead(60)}, {})
    results = await auto_renew.refresh_due(within_s=3600, product="buddy")
    assert results[0]["ok"] is False and "不可续期" in results[0]["detail"]


async def test_terminal_not_refreshable_stops_retrying(monkeypatch):
    """🔴 终态（refresh_token 已死 / 业务码 200003）：记 `terminal` 后**不再逐轮撞 401**，
    直到某次续期成功才清标记（:8300 实测 raccoon 两号即此形态）。"""
    hits: list = []

    async def nor(cred, meta):
        hits.append(meta.get("account"))
        raise NotRefreshable("Raccoon 登录态已过期（refresh_token 失效），请重新登录")
    monkeypatch.setattr(product_hooks, "hook_of", lambda product, name: nor)
    _seed("buddy", "dead-token", {"token": "T", "expires_at": _ms_ahead(60)}, {})

    first = await auto_renew.refresh_due(within_s=3600, product="buddy")
    assert first[0]["ok"] is False and "不可续期" in first[0]["detail"]
    assert len(hits) == 1
    second = await auto_renew.refresh_due(within_s=3600, product="buddy")
    assert second[0]["skipped"] == "terminal" and len(hits) == 1, "终态账号被逐轮重试"
    assert "重新登录" in second[0]["detail"]

    # 成功续期清掉终态标记 → 下一轮重新纳入
    async def ok(cred, meta):
        return {"token": "NEW"}
    monkeypatch.setattr(product_hooks, "hook_of", lambda product, name: ok)
    assert (await auto_renew.refresh_one("buddy", "dead-token"))["ok"] is True
    third = await auto_renew.refresh_due(within_s=3600, product="buddy")
    assert [r for r in third if r.get("skipped") == "terminal"] == []


def test_renew_ledger_lives_in_runtime_json_and_survives_quota_writes():
    """台账写 `runtime.json` 的 `renew` 键；额度腿读-改-写只动 `quota`，两者互不洗掉。"""
    _seed("buddy", "ledger-1", {"token": "T"}, {})
    auto_renew._patch_renew("buddy", "ledger-1", {"attempted_at": auto_renew._now_iso()})
    from model_gateway.accounts import store as st
    rt = st.read_runtime("buddy", "ledger-1")
    assert rt["renew"]["attempted_at"]
    rt["quota"] = {"state": "available"}
    st.write_runtime("buddy", "ledger-1", rt)
    again = st.read_runtime("buddy", "ledger-1")
    assert again["renew"]["attempted_at"] and again["quota"]["state"] == "available"
