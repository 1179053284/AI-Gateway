"""旧账 #48：热重载**换下/删掉**的出站适配器必须被关掉，但不能在途就关（延迟排空）。

为什么需要这一组判据（2026-09-29 实测取证，见
`docs/changes/e2e-records/E2E-20260928-round5-fixes.md`「旧账 #48 取证」一节）：
`Runtime._apply` 是**同步**方法，`self.adapters = new_adapters` 一执行，被换下的适配器
就没人引用了；而 `httpx.AsyncClient` 只有被 `aclose()` 才释放连接池。原先整条路径没有
这一步，`Runtime.aclose()` 又只遍历**当前**字典 —— 实测「每改一次配置就漂一个 client
到进程退出」，而代码注释当时写的是「防在途连接泄漏」。

两个方向都要钉，缺一个就是半套：
① **要关**（否则泄漏照旧）；② **不能在宽限期内关**（否则截断在途请求 —— 这是当初
   没做这件事的真实理由，只测①会鼓励出"立刻关"那种更坏的修法）。
"""
from __future__ import annotations

import asyncio
import pathlib

import pytest

from model_gateway import main as M
from model_gateway.config.loader import load_config


class _FakeAdapter:
    """替身适配器：只关心 `base_url` / `protocol` 与"有没有被关过"。"""

    def __init__(self, base_url: str, protocol: str = "openai"):
        self.base_url = base_url
        self.protocol = protocol
        self.closed = False
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1
        self.closed = True


def _build_config(path: pathlib.Path, base_url: str, *, budget: int = 300) -> None:
    path.write_text(
        "gateway:\n"
        f"  request_total_budget_seconds: {budget}\n"
        "resources:\n"
        "  - id: res-a\n"
        "    name: 资源A\n"
        "    access_mode: api\n"
        "    protocol: openai\n"
        f"    base_url: {base_url}\n"
        "    api_key: sk-a\n",
        encoding="utf-8")


def _runtime(tmp_path: pathlib.Path, monkeypatch, *, base_url: str = "http://127.0.0.1:9/v1",
             grace: float | None = None) -> M.Runtime:
    """造一个只装配替身适配器的 Runtime（不碰网络、不建真 client）。"""
    made: list[_FakeAdapter] = []

    def _fake_build(protocol, base_url_, **_kw):
        a = _FakeAdapter(base_url_, protocol)
        made.append(a)
        return a

    monkeypatch.setattr(M, "build_adapter", _fake_build)
    cfg_path = tmp_path / "config.yaml"
    _build_config(cfg_path, base_url)
    rt = M.Runtime(load_config(cfg_path), cfg_path,
                   usage_dir=tmp_path / "usage",
                   enums_path=tmp_path / "model-enums.yaml",
                   dialects_path=tmp_path / "dialects.yaml")
    if grace is not None:
        monkeypatch.setattr(rt, "_drain_grace_seconds", lambda: grace)
    rt._made = made  # 供断言取用
    return rt


def _run(coro) -> object:
    return asyncio.run(coro)


def test_replaced_adapter_is_retired_not_dropped(tmp_path, monkeypatch):
    """换 base_url → 旧适配器必须进"待关"清单，而不是就地丢掉。"""
    rt = _runtime(tmp_path, monkeypatch, grace=0.02)
    first = rt.adapters["res-a"]
    assert first in rt._made and not first.closed

    async def scenario():
        _build_config(tmp_path / "config.yaml", "http://127.0.0.1:8/v1")
        ok, errors = await rt.reload_from_file()
        assert ok, errors
        return rt.adapters["res-a"]

    second = _run(scenario())
    assert second is not first, "换了端点却没重建适配器，判据失去对象"
    assert first in rt._pending_close, (
        f"被换下的适配器没进待关清单 = 依旧漂着没人关（旧账 #48 本体）；"
        f"pending={rt._pending_close}")
    _run(rt.aclose())


def test_grace_period_does_not_truncate_in_flight(tmp_path, monkeypatch):
    """宽限期内**不得**关：在途请求绑的是旧快照，立刻关会把它截断。

    这条与上一条是一对：只测"要关"会鼓励出"reload 时马上 aclose"那种更坏的修法。
    """
    rt = _runtime(tmp_path, monkeypatch, grace=30.0)  # 宽限期故意拉长
    first = rt.adapters["res-a"]

    async def scenario():
        _build_config(tmp_path / "config.yaml", "http://127.0.0.1:8/v1")
        ok, _ = await rt.reload_from_file()
        assert ok
        await asyncio.sleep(0.05)          # 远小于宽限期
        return first.closed

    assert _run(scenario()) is False, "宽限期未到就关了 = 会截断在途请求"
    assert first in rt._pending_close
    _run(rt.aclose())


def test_retired_adapter_actually_closes_after_grace(tmp_path, monkeypatch):
    """过了宽限期必须真的关掉（"进清单"不等于"关掉了"）。"""
    rt = _runtime(tmp_path, monkeypatch, grace=0.02)
    first = rt.adapters["res-a"]

    async def scenario():
        _build_config(tmp_path / "config.yaml", "http://127.0.0.1:8/v1")
        ok, _ = await rt.reload_from_file()
        assert ok
        await asyncio.sleep(0.2)           # > 宽限期，且给排空任务留出跑完的时间
        return first.closed, list(rt._pending_close)

    closed, pending = _run(scenario())
    assert closed is True, "过了宽限期仍未关闭 = 排空任务没接上"
    assert pending == [], f"排空后待关清单应清空，实得 {pending}"


def test_deleted_resource_adapter_is_also_retired(tmp_path, monkeypatch):
    """资源被**删掉**（不是换端点）同样要排空 —— 两条路都别留孤儿 client。"""
    rt = _runtime(tmp_path, monkeypatch, grace=0.02)
    first = rt.adapters["res-a"]

    async def scenario():
        (tmp_path / "config.yaml").write_text(
            "gateway:\n  request_total_budget_seconds: 300\nresources: []\n",
            encoding="utf-8")
        ok, errors = await rt.reload_from_file()
        assert ok, errors
        await asyncio.sleep(0.2)
        return "res-a" in rt.adapters, first.closed

    still_listed, closed = _run(scenario())
    assert still_listed is False, "资源删了但适配器还在字典里，判据失去对象"
    assert closed is True, "删掉资源后其适配器没被关（泄漏的第二条路径）"


def test_shutdown_closes_pending_even_if_grace_never_elapses(tmp_path, monkeypatch):
    """停机兜底：宽限期还没到也要关（进程都退了，等下去没有意义）。"""
    rt = _runtime(tmp_path, monkeypatch, grace=3600.0)
    first = rt.adapters["res-a"]

    async def scenario():
        _build_config(tmp_path / "config.yaml", "http://127.0.0.1:8/v1")
        ok, _ = await rt.reload_from_file()
        assert ok
        assert first in rt._pending_close, "前置条件不成立：没进待关清单"
        await rt.aclose()
        return first.closed

    assert _run(scenario()) is True, "aclose() 没兜住待清单项 = 兜底路径是假的"
    assert rt._pending_close == []


def test_grace_is_derived_from_request_budget_not_a_magic_number(tmp_path, monkeypatch):
    """宽限期口径 = `gateway.request_total_budget_seconds`（Q16/§5.5），不是拍出来的常数。

    为什么钉这个：只有"≥ 请求总预算"才谈得上"不可能截断任何合法在途请求"；
    写死一个数以后没人知道它和预算的关系，改预算也带不动它。
    """
    rt = _runtime(tmp_path, monkeypatch)          # 配置里是 300
    assert rt._drain_grace_seconds() == 300.0
    rt.config.gateway.request_total_budget_seconds = 90
    assert rt._drain_grace_seconds() == 90.0, "宽限期不跟随请求总预算 = 口径是硬编码"
    # 坏值退回**更保守**的一侧（等更久），而不是更快关
    rt.config.gateway.request_total_budget_seconds = 0
    assert rt._drain_grace_seconds() == 300.0


def test_schedule_without_event_loop_keeps_them_for_shutdown(tmp_path, monkeypatch):
    """没有事件循环时不能"丢掉就算关过"：必须留在待关清单里等停机兜底。

    （`_apply` 是同步方法，非 asyncio 环境下的 reload/测试装配会走到这条路。）
    """
    rt = _runtime(tmp_path, monkeypatch)
    first = rt.adapters["res-a"]
    second = _FakeAdapter("http://127.0.0.1:8/v1")
    rt.adapters = {"res-a": second}
    rt._retire_adapters([first])                  # 无 running loop 的场景
    assert first in rt._pending_close
    assert first.closed is False
    _run(rt.aclose())
    assert first.closed is True, "无循环时挂不上任务可以，但停机必须补关"
