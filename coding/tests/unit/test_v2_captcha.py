"""v2.0 §16.5 验证码求解器单元测试（本轮 G3）。

真机能否过阿里云无痕**未实测**（§19 T7：需真实凭据 + 住宅代理）；
本文件验的是**接口纪律**：TTL 45s / 宽限期后台刷新 / 同进程串行 / 30s 超时 /
失败短熔断 / 未配代理与依赖缺失的文案与原因一致 / 配置接口挂掉走兜底。

浏览器与 `sleep`/`now` 全部注入 → 确定性、零网络、零真进程。
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from model_gateway.upstream.zcode import captcha as cap


class FakePage:
    def __init__(self, payloads: list[str], *, hang: bool = False):
        self._payloads = list(payloads)
        self._hang = hang
        self.exposed: dict = {}
        self.closed = False
        self.urls: list[str] = []

    async def expose_function(self, name, fn):
        self.exposed[name] = fn

    async def goto(self, url, **kw):
        self.urls.append(url)
        if not self._hang and self._payloads:
            self.exposed["__onCaptcha"](self._payloads.pop(0))

    async def set_content(self, html):
        self.html = html

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, pages):
        self._pages = list(pages)
        self.pages: list[FakePage] = []
        self.closed = False

    async def new_page(self, **kw):
        page = self._pages.pop(0) if self._pages else FakePage([])
        self.pages.append(page)
        return page

    async def close(self):
        self.closed = True


def make_solver(*, payloads=("param-1",), proxy="http://user:pp@127.0.0.1:8000",
                config=None, now=None, timeout_s=cap.SOLVE_TIMEOUT_S, hang=False,
                manual=False):
    """构造注入式求解器；返回 (solver, browser, clock)。"""
    clock = {"t": 0.0}
    now = now or (lambda: clock["t"])
    def encode(p):
        return p if str(p).startswith("{") else json.dumps({"event": "success", "param": p})

    pages = [FakePage([] if hang else [encode(p)])
             for p in (payloads if isinstance(payloads, tuple) else [payloads])]
    browser = FakeBrowser(pages)

    async def noop_sleep(_s):
        await asyncio.sleep(0)

    async def launcher():
        return browser

    solver = cap.CaptchaSolver(proxy=proxy, browser_launcher=launcher,
                               sleep=noop_sleep, now=now, timeout_s=timeout_s,
                               manual=manual)
    # 🔴 默认预置配置缓存：否则 fetch_config 会去**打真网络**（测试必须零网络）
    solver._config = dict(config if config is not None else cap.FALLBACK_CONFIG)
    solver._config_at = now()
    if config is not None and "enabled" in config:
        solver._config = dict(config)
    return solver, browser, clock


def run(coro):
    return asyncio.run(coro)


# ---------- 硬依赖与文案（IX S-1 的根因：文案必须与原因一致）----------

def test_no_proxy_raises_with_proxy_hint():
    """未配住宅代理 → 明确说"未配置住宅代理"并给出**两个**配置位置 + 手动出路。"""
    solver, browser, _ = make_solver(proxy="")
    with pytest.raises(cap.CaptchaUnavailable) as e:
        run(solver())
    msg = str(e.value)
    assert "未配置住宅代理" in msg
    assert "gateway.zcode.proxy" in msg and "MGW_ZCODE_PROXY" in msg
    assert "--manual" in msg
    assert browser.pages == []                  # 没配代理就绝不能白开浏览器


def test_manual_hint_does_not_loop_and_differs():
    """已加 `--manual` → 不得再叫用户加 `--manual`（上一轮踩过的文案循环）。"""
    solver, _, _ = make_solver(proxy="", manual=True)
    with pytest.raises(cap.CaptchaUnavailable) as e:
        run(solver())
    msg = str(e.value)
    assert "已指定 --manual" in msg and "也可加 --manual" not in msg


def test_playwright_missing_hint_is_actionable(monkeypatch):
    """依赖缺失 → 给出可执行安装命令，而不是静默降级成"不可用"。"""
    import builtins
    import sys

    real_import = builtins.__import__

    def blocked(name, *a, **kw):
        if name.startswith("playwright"):
            raise ImportError("no playwright")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", blocked)
    monkeypatch.setitem(sys.modules, "playwright.async_api", None)
    solver = cap.CaptchaSolver(proxy="http://p:8000", browser_launcher=None,
                               sleep=lambda s: asyncio.sleep(0))
    with pytest.raises(cap.CaptchaUnavailable) as e:
        run(solver._default_launcher())
    assert "playwright" in str(e.value) and "pip install" in str(e.value)


# ---------- 缓存 TTL / 宽限期 / 失败短熔断 ----------

def test_param_reused_within_ttl_and_refreshed_after():
    """§16.5：参数 TTL 45s —— 期内复用（不重复开浏览器），过期才重解。"""
    clock = {"t": 0.0}

    def now():
        return clock["t"]

    solver, browser, _ = make_solver(now=now)
    assert run(solver()) == "param-1"
    clock["t"] = 30_000
    assert run(solver()) == "param-1"
    assert solver.solve_calls == 1, "TTL 内重复求解 = 每次领取都开浏览器"

    # 越过 TTL + 宽限期 → 不再走"即回旧值"的宽限分支，必须同步重解一次
    browser._pages.append(FakePage([json.dumps({"event": "success", "param": "param-2"})]))
    clock["t"] = cap.CACHE_TTL_MS + cap.STALE_GRACE_MS + 1
    assert run(solver()) == "param-2"
    assert solver.solve_calls == 2


def test_stale_grace_returns_old_value_and_refreshes_in_background():
    """宽限期（TTL 之后 300s）：**先回旧值 + 后台刷新**，不让领取同步等一次开浏览器。"""
    clock = {"t": 0.0}
    solver, browser, _ = make_solver(now=lambda: clock["t"])
    assert run(solver()) == "param-1"
    browser._pages.append(FakePage([json.dumps({"event": "success", "param": "param-2"})]))

    clock["t"] = 46_000                            # 过 TTL、在宽限期内
    async def main():
        got = await solver()
        await asyncio.sleep(0.02)                  # 放后台任务跑完
        return got

    assert run(main()) == "param-1", "宽限期应当即回旧值"
    assert solver._param == "param-2", "后台刷新必须补上新值"


def test_failure_short_circuits_next_attempt():
    """🔴 失败短熔断：F001 这类必然失败的求解，60s 内不再重试
    （否则每个请求都白等 30s，把批量拖死 —— 参考实现为此专门做了失败缓存）。"""
    clock = {"t": 1_000.0}        # 非零起点：生产用 monotonic，恒 >0
    bad = json.dumps({"event": "fail", "reason": {"verifyCode": "F001", "msg": "risk"}})
    solver, browser, _ = make_solver(payloads=(bad,), now=lambda: clock["t"])

    with pytest.raises(cap.CaptchaUnavailable) as e:
        run(solver())
    assert "F001" in str(e.value) and "住宅代理" in str(e.value)
    calls_after_first = solver.solve_calls

    with pytest.raises(cap.CaptchaUnavailable) as e2:
        run(solver())
    msg2 = str(e2.value)
    assert "不重试" in msg2
    m = re.search(r"（(\d+)s 内不重试）", msg2)
    assert m and int(m.group(1)) >= 1, f"剩余时间必须是可读的正整数秒：{msg2}"
    assert solver.solve_calls == calls_after_first, "失败短熔断期内不得重开浏览器"

    clock["t"] += cap.FAIL_CACHE_MS + 1           # 熔断窗口过后允许再试
    browser._pages.append(FakePage([json.dumps({"event": "success", "param": "ok-2"})]))
    assert run(solver()) == "ok-2"


# ---------- 上游关闭验证 / 配置接口不可用 ----------

def test_disabled_captcha_returns_empty_without_browser():
    """`client/configs` 说 enabled=false（§19 T7：上游可能已放宽）→ 空参数直放，不开浏览器。"""
    solver, browser, _ = make_solver(config={"enabled": False})
    assert run(solver()) == ""
    assert solver.solve_calls == 0


def test_config_endpoint_failure_uses_fallback():
    """配置接口挂 → 用兜底值继续求解，**不得**当成"上游不需要验证码"而发空参数。"""
    solver, browser, _ = make_solver(config=None)
    solver.site_root = "http://127.0.0.1:1"          # 必然连不上
    assert run(solver()) == "param-1"
    page = browser.pages[0]
    assert page.urls == [cap.ORIGIN_URL], "必须先落到同源页（origin 真实性）"
    assert "initAliyunCaptcha" in page.html
    assert json.dumps(cap.FALLBACK_CONFIG["sceneId"]) in page.html


# ---------- 超时（§16.5：每次求解 30s）----------

def test_solve_timeout_is_wrapped_not_raised_raw():
    """浏览器迟迟不回 → 转成 CaptchaUnavailable（上层记 failed，不抛裸 TimeoutError）。"""
    solver, _, _ = make_solver(payloads=("{not-json",), hang=True, timeout_s=0.05)
    with pytest.raises(cap.CaptchaUnavailable):
        run(solver())


def test_lock_serializes_concurrent_solves():
    """§16.5 进程模型：同进程串行 —— 并发调用只开一次浏览器，其余等锁后命中缓存。"""
    clock = {"t": 0.0}
    solver, browser, _ = make_solver(now=lambda: clock["t"])
    browser._pages.append(FakePage([]))              # 若被误开第二次就会挂死

    async def main():
        return await asyncio.gather(solver(), solver(), solver())

    assert run(main()) == ["param-1"] * 3
    assert solver.solve_calls == 1


# ---------- 生产接线（上一轮"只有注入点、没人传"）----------

def test_production_client_always_gets_a_solver(monkeypatch):
    """🔴 装配事实：客户端的 `_captcha_solver` 必须非 None（否则等于没接，上一轮的缺陷）。"""
    from model_gateway.ops.builtin import zcode_claim

    seen: dict = {}

    def fake_get_solver(**kw):
        seen.update(kw)
        return object()

    monkeypatch.setattr(cap, "get_solver", fake_get_solver)
    monkeypatch.setattr(zcode_claim, "_plan_endpoint",
                        lambda: (zcode_claim.DEFAULT_PLAN_BASE, "http://p:8000",
                                 "https://zcode.z.ai"))
    client = zcode_claim._build_client("jwt-1", "mid-1", manual=True)

    assert seen["proxy"] == "http://p:8000"
    assert seen["site_root"] == "https://zcode.z.ai"
    assert seen["manual"] is True
    assert client._captcha_solver is not None, "求解器没接上 = 验证码路径整体是假的"
    assert client.proxy == "http://p:8000"


def test_production_client_wired_through_claim_entry(monkeypatch):
    """`claim()` 不注入 client_factory 时走的必须是 `_build_client`（同一装配事实）。"""
    from model_gateway.ops.builtin import zcode_claim

    built: list = []

    class _NoopClient:
        def __init__(self, *a, **kw):
            built.append(kw)

        async def preview(self):
            raise claim_stop()

        async def aclose(self):
            pass

    def claim_stop():
        class _Stop(Exception):
            pass
        return _Stop()

    monkeypatch.setattr(zcode_claim, "_credentials_of", lambda a: ("jwt", "mid", ""))
    monkeypatch.setattr(zcode_claim, "_build_client",
                        lambda jwt, mid, manual=False: _NoopClient(jwt, mid, manual=manual))
    res = asyncio.run(zcode_claim.claim("acct-a", manual=True))
    assert built and built[0]["manual"] is True
    assert res.category == "failed"        # 装配走通后被上游异常隔离为 failed
