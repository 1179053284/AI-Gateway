"""IX-2（第四轮验收）：网关**启动时**必须重新看见落盘的 3012 全局熔断。

缺陷场景（验收原话）：`circuit.json` 里还剩 19 分钟，网关重启后
总览资源健康卡显示 `active` + 「最近错误」为空 —— §17 指定的唯一可见出口一片空白，
而模型转发照旧把请求派给仍在风控观察期里的账号。

熔断状态是**跨进程落盘**的（可能由 `mgw zcode claim` 在另一个进程里写下），
资源态是**内存**的（按配置重建）→ 两边必须在启动时对账一次。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import httpx
import pytest

from model_gateway.upstream.zcode import quota as zq
from tests.integration.conftest import chat_res, gateway_config

pytestmark = pytest.mark.asyncio

ACCOUNT = "acct-boot"


def _make_account(root: Path, name: str) -> None:
    """最小账号目录（`store.list_accounts()` / `has_account()` 只认 meta.json）。"""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps({"device_mid": f"mid-{name}"}), encoding="utf-8")


async def test_startup_rebenches_resources_while_breaker_is_active(make_gateway, tmp_path,
                                                                   monkeypatch):
    """🔴 真启动路径（`create_app` → startup 事件）后，资源必须仍是冷却态且带原因。"""
    root = tmp_path / "accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    _make_account(root, ACCOUNT)

    cfg = gateway_config(9, models=[chat_res("A", name="zcode-model")])
    cfg["resources"][0]["account"] = ACCOUNT        # 资源↔账号的既有约定（Q20-③ 备注）
    zq.get_circuit().enter("ZCode 风控熔断（30min，全局）")   # 先于建 app：模拟"重启前就熔着"

    gw = await make_gateway(cfg)
    try:
        states = list(gw.runtime.resources.registry.values())
        assert states, "注册表为空 —— 本用例失去意义"
        assert all(s.status == "cooldown" for s in states), \
            [(s.status, s.last_error) for s in states]
        assert all("风控熔断" in (s.last_error or "") for s in states)
        # 🔴 内存里存的是**裸原因**，恢复时刻只在渲染时拼（验收 S-23）：
        #    烘死的那份钟点到了午夜后就是"已经过去的时间"，界面上留着它等于说谎。
        assert all("至 " not in (s.last_error or "") for s in states), \
            [s.last_error for s in states]

        # 生效集里不得有它 —— 否则"模型转发自动绕开"（§17 / M4-4）不成立
        async with httpx.AsyncClient(timeout=10) as c:
            rows = (await c.get(f"{gw.base_url}/admin/api/overview")).json()
        mine = [r for r in rows["resources"] if r["rid"] == "res-A"]
        assert mine and mine[0]["available"] is False, mine
        # 「最近错误」列（用户真正读到的那一句）必须自带**当下成立**的恢复时刻
        assert re.search(r"，至 (?:明日 )?\d{2}:\d{2}$",
                        mine[0].get("last_error") or ""), mine[0]
        assert "风控熔断" in (mine[0].get("last_error") or "")
    finally:
        await gw.stop()


async def test_startup_leaves_resources_alone_when_no_breaker(make_gateway, tmp_path,
                                                              monkeypatch):
    """🔴 正向对照：没有落盘熔断时，启动**不得**凭空 bench 任何资源。"""
    root = tmp_path / "accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    _make_account(root, ACCOUNT)
    assert not zq.get_circuit().active()

    cfg = gateway_config(9, models=[chat_res("A", name="zcode-model")])
    cfg["resources"][0]["account"] = ACCOUNT
    gw = await make_gateway(cfg)
    try:
        states = list(gw.runtime.resources.registry.values())
        assert states
        assert [s.status for s in states] == ["active"] * len(states)
        assert all(s.last_error is None for s in states)
    finally:
        await gw.stop()


def _warn_lines(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)


async def test_startup_does_not_claim_a_breaker_that_is_not_there(make_gateway, tmp_path,
                                                                 monkeypatch, caplog):
    """🔴 `(0, 0)` 不等于"熔着但没对上号"（验收 S-19）：未熔断时不得打「仍在生效」。

    这条日志是用户判断"要不要动这些资源"的依据，谎报一次就等于凭空制造一次风控焦虑；
    同一处的空括号 `（）` 是同一根因的可见症状（未熔断时 `reason()` 是空串）。
    """
    root = tmp_path / "accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    _make_account(root, ACCOUNT)          # 号在、资源也配了，但**没有熔断**
    assert not zq.get_circuit().active()

    cfg = gateway_config(9, models=[chat_res("A", name="zcode-model")])
    cfg["resources"][0]["account"] = ACCOUNT
    with caplog.at_level(logging.WARNING, logger="model_gateway"):
        gw = await make_gateway(cfg)
    try:
        text = _warn_lines(caplog)
        assert "全局风控" not in text, f"未熔断却报风控仍在生效：{text}"
        assert "（）" not in text, text
    finally:
        await gw.stop()


async def test_empty_account_match_while_breaker_active_still_leaves_a_trace(
        make_gateway, tmp_path, monkeypatch, caplog):
    """🔴 反向对照（不许把上一条修成"静音"）：熔着却没人对上号时**必须**留痕，且原因非空。

    ix-M-6 的原缺陷就是"文件里熔着、界面上毫无变化"看起来像熔断没生效；
    加判据必须同时钉住两侧，否则下一次改动会朝另一边倒回去。
    """
    root = tmp_path / "accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))   # 故意不建账号目录
    zq.get_circuit().enter("ZCode 风控熔断（30min，全局）")

    cfg = gateway_config(9, models=[chat_res("A", name="zcode-model")])
    cfg["resources"][0]["account"] = "另一个号"
    with caplog.at_level(logging.WARNING, logger="model_gateway"):
        gw = await make_gateway(cfg)
    try:
        text = _warn_lines(caplog)
        assert "全局风控仍在生效" in text, "熔断空转却完全无声"
        assert "ZCode 风控熔断" in text, text          # 原因必须写出来，不能空括号
    finally:
        await gw.stop()
