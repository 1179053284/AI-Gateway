"""阿里云**无痕验证码**求解（tech-design v2.0 §16.5 / PRD Q27-①，用户已接受）。

方案落点（§16.5 表逐条）：

| 项 | 落地 |
|---|---|
| 实现 | `playwright.async_api` 跑官方无头浏览器 + 阿里云无痕 SDK（与参考实现同栈） |
| 进程模型 | **同进程 + `asyncio.Lock` 串行**（同一时刻只跑一个求解，其余等锁后命中缓存） |
| 超时 | 每次求解 `asyncio.wait_for(..., timeout=30s)` |
| 浏览器生命周期 | **进程级复用**，退出时 `aclose()` |
| 缓存 | 参数 TTL 45s；过期后 300s **宽限期内先回旧值 + 后台刷新** |
| 🔴 硬依赖 | **住宅代理**（数据中心 IP 被风控 `F001` 拒绝） |

**为什么不是"重试几次就行"**（`18` §② / 参考实现踩坑）：求解结果是一次性的短时效凭证，
每号都开一次浏览器既慢又会被风控盯上；而失败短时熔断能避免"每个请求都白等 30s"。

⚠️ **未实测口径**：真机能否过无痕、`client/configs` 的字段时效（§19 T7/T9）均需
真实凭据 + 住宅代理，本机无法验证。本模块只保证**接口纪律与降级可见**。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Awaitable, Callable

#: 求解结果缓存（§16.5：TTL 45s + 宽限期后台刷新）
CACHE_TTL_MS = 45_000
STALE_GRACE_MS = 300_000
#: 失败短熔断：数据中心 IP 被 F001 拒时，不让每个请求都重跑一次注定失败的 30s 求解
FAIL_CACHE_MS = 60_000
#: `client/configs` 结果缓存（该接口本身不随账号变化，§19 T9 关注其时效）
CONFIG_CACHE_MS = 600_000

#: §16.5 明确的单次求解超时
SOLVE_TIMEOUT_S = 30.0

CONFIG_PATH = "/api/v1/client/configs"
CAPTCHA_SDK_URL = "https://o.alicdn.com/captcha-frontend/aliyunCaptcha/AliyunCaptcha.js"
ORIGIN_URL = "https://zcode.z.ai/"

#: 配置接口不可用时的兜底值（与参考实现 `captcha.py:150-152` 同一组，**不自己发明**）
FALLBACK_CONFIG = {"enabled": True, "prefix": "no8xfe", "region": "cn",
                   "sceneId": "11xygtvd"}

#: 无头浏览器伪装口径（参考实现：自带 Chromium 会被识别，优先复用本机真实 Chrome/Edge）
_CHROME_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

SOLVER_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<script src="__SDK__"></script>
</head><body><div id="cap"></div><button id="btn"></button>
<script>
window.initAliyunCaptcha({
  SceneId: __SCENE__, mode: 'popup', region: __REGION__, prefix: __PREFIX__,
  element: '#cap', button: '#btn', captchaLogoImg: '', showErrorTip: false,
  getInstance: function (inst) {
    var fn = inst.startTracelessVerification || inst.show;
    try { fn.call(inst); } catch (e) {
      window.__onCaptcha(JSON.stringify({event: 'starterr', message: String(e && e.message || e)}));
    }
  },
  success: function (p) { window.__onCaptcha(JSON.stringify({event:'success', param:p})); },
  fail: function (m) { window.__onCaptcha(JSON.stringify({event:'fail', reason:m})); },
  onError: function (m) { window.__onCaptcha(JSON.stringify({event:'error', reason:m})); }
});
</script></body></html>"""

#: 用户侧文案（§16.5「未配置时不静默失败」）—— **必须与实际原因一致**，
# 上一轮的缺陷是：求解器压根没接上，却告诉用户"未配置住宅代理"。
NO_PROXY_HINT = (
    "未配置住宅代理，验证码求解不可用 —— "
    "请配置 gateway.zcode.proxy（或环境变量 MGW_ZCODE_PROXY）；也可加 --manual 由人工完成验证码")
MANUAL_HINT = (
    "已指定 --manual：请在已登录的 ZCode 客户端里手动完成一次领取后重试；"
    "若要自动求解请配置住宅代理 gateway.zcode.proxy")
PLAYWRIGHT_HINT = (
    "验证码求解需要 Playwright 与浏览器内核："
    '`pip install "model-gateway[captcha]" && python -m playwright install chromium`；'
    "也可加 --manual 由人工完成验证码")


# 🔴 异常类**只有一份**：`claim.CaptchaUnavailable`。
# 原先本模块另定义了一个同名类，而 `zcode_claim` 捕获的是 claim 那份 ——
# 于是求解器的失败落到 `except Exception` 兜底分支，被打上 `network:` 前缀，
# 触发对一次注定失败的求解做 3 轮退避重试（真打 3 次 preview）。
from model_gateway.upstream.zcode.claim import CaptchaUnavailable  # noqa: E402,F401


def _now_ms() -> float:
    return time.monotonic() * 1000        # 进程内计时：单调钟，不受系统时间调整影响


class CaptchaSolver:
    """求解器（可注入 `browser_launcher` / `sleep` / `now` 以便单测确定性验证）。

    `proxy` 为空 → 直接 `CaptchaUnavailable`（§16.5 硬依赖，不假装能跑）。
    """

    def __init__(self, *, proxy: str, site_root: str = "https://zcode.z.ai",
                 browser_launcher: Callable | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 now: Callable[[], float] = _now_ms,
                 timeout_s: float = SOLVE_TIMEOUT_S,
                 manual: bool = False):
        self.proxy = (proxy or "").strip()
        self.site_root = site_root.rstrip("/")
        self._browser_launcher = browser_launcher
        self._sleep = sleep
        self._now = now
        self.timeout_s = timeout_s
        self.manual = manual

        self._lock = asyncio.Lock()
        self._param: str | None = None
        self._param_at = 0.0
        self._failed_at = 0.0
        self._failed_err = ""
        self._refreshing = False
        self._config: dict | None = None
        self._config_at = 0.0
        self._browser = None
        self.solve_calls = 0              # 诊断/测试用：真正开了几次浏览器

    # ---------- 配置 ----------

    async def fetch_config(self) -> dict:
        """`GET {site}/api/v1/client/configs` → `data.configs.captcha`。

        取不到用 `FALLBACK_CONFIG`（参考实现同口径）—— 配置接口挂掉时宁可多验一次，
        也不能"以为上游关了验证码"而直接空参数被拒。
        """
        now = self._now()
        if self._config and now - self._config_at < CONFIG_CACHE_MS:
            return self._config
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15, proxy=self.proxy or None) as c:
                r = await c.get(f"{self.site_root}{CONFIG_PATH}",
                                params={"version": "3.11.2", "os": "darwin"})
            captcha = ((r.json().get("data") or {}).get("configs") or {}).get("captcha")
            if isinstance(captcha, dict):
                self._config, self._config_at = captcha, now
                return captcha
        except Exception:  # noqa: BLE001 — 配置读取失败走兜底，不阻断领取
            pass
        return dict(FALLBACK_CONFIG)

    # ---------- 求解（缓存 + 串行 + 宽限期）----------

    async def __call__(self) -> str:
        """返回 `X-Aliyun-Captcha-Verify-Param`；上游关闭人机校验时返回空串。"""
        if not self.proxy:
            raise CaptchaUnavailable(MANUAL_HINT if self.manual else NO_PROXY_HINT)

        now = self._now()
        if self._param and now - self._param_at < CACHE_TTL_MS:
            return self._param
        # 宽限期：先回旧值，后台刷新 —— 避免领取请求同步等一次开浏览器
        if self._param and now - self._param_at < CACHE_TTL_MS + STALE_GRACE_MS \
                and not self._refreshing:
            self._refreshing = True
            asyncio.create_task(self._refresh_background())
            return self._param
        if self._failed_at and now - self._failed_at < FAIL_CACHE_MS:
            # 向上取整且至少 1 秒：显示"0s 内不重试"等于没告诉用户要等多久
            left = int(max(1, -(-(FAIL_CACHE_MS - (now - self._failed_at)) // 1000)))
            raise CaptchaUnavailable(f"验证码求解失败（{left}s 内不重试）：{self._failed_err}")

        async with self._lock:                       # 同进程串行（§16.5）
            now = self._now()
            if self._param and now - self._param_at < CACHE_TTL_MS:
                return self._param                    # 等锁期间已被别人填好
            if self._failed_at and now - self._failed_at < FAIL_CACHE_MS:
                raise CaptchaUnavailable(f"验证码求解失败（短时内不重试）：{self._failed_err}")
            config = await self.fetch_config()
            if config.get("enabled") is False:
                return ""                             # 上游已关闭人机校验 → 空参数放行
            try:
                param = await self._solve(config)
            except Exception as e:                    # noqa: BLE001
                self._failed_at = self._now()
                self._failed_err = str(e)[:300]
                raise CaptchaUnavailable(str(e)) from e
            self._param, self._param_at, self._failed_at = param, self._now(), 0.0
            return param

    async def _refresh_background(self) -> None:
        try:
            async with self._lock:
                config = await self.fetch_config()
                if config.get("enabled") is False:
                    return
                self._param, self._param_at = await self._solve(config), self._now()
        except Exception:  # noqa: BLE001 — 后台刷新失败继续用旧参数，不打断领取
            pass
        finally:
            self._refreshing = False

    async def _solve(self, config: dict) -> str:
        scene = str(config.get("sceneId") or FALLBACK_CONFIG["sceneId"])
        region = str(config.get("region") or FALLBACK_CONFIG["region"])
        prefix = str(config.get("prefix") or FALLBACK_CONFIG["prefix"])
        self.solve_calls += 1
        # §16.5：每次求解 30s 超时；超时/异常一律转 CaptchaUnavailable
        return await asyncio.wait_for(self._run_browser(scene, region, prefix),
                                      timeout=self.timeout_s)

    async def _run_browser(self, scene: str, region: str, prefix: str) -> str:
        html = (SOLVER_HTML.replace("__SDK__", CAPTCHA_SDK_URL)
                .replace("__SCENE__", json.dumps(scene))
                .replace("__REGION__", json.dumps(region))
                .replace("__PREFIX__", json.dumps(prefix)))
        received: list[str] = []

        launcher = self._browser_launcher
        if launcher is None:
            launcher = await self._default_launcher()
        browser = await self._ensure_browser(launcher)

        page = await browser.new_page(user_agent=_CHROME_UA,
                                      viewport={"width": 1280, "height": 720})
        try:
            await page.expose_function("__onCaptcha",
                                       lambda payload: received.append(payload))
            # 先落到同源页再替换内容：让 origin / localStorage 环境真实（参考实现同法）
            await page.goto(ORIGIN_URL, wait_until="domcontentloaded")
            await page.set_content(html)
            while True:
                if received:
                    msg = _loads(received[0])
                    event = msg.get("event")
                    if event == "success" and msg.get("param"):
                        return str(msg["param"])
                    raise CaptchaUnavailable(_format_reject(msg))
                await self._sleep(0.2)
        finally:
            # 页必须关，浏览器留着重用（§16.5 进程级复用）
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass

    async def _default_launcher(self):
        """惰性导入 Playwright；缺失时给出**可操作**提示（不静默降级）。"""
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:                      # pragma: no cover — 依赖缺失路径
            raise CaptchaUnavailable(PLAYWRIGHT_HINT) from e

        async def launch():
            pw = await async_playwright().start()
            kwargs: dict = {"headless": True, "args": [
                "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"]}
            channel = _detect_browser_channel()
            if channel:
                kwargs["channel"] = channel
            if self.proxy:
                kwargs["proxy"] = {"server": self.proxy}
            return await pw.chromium.launch(**kwargs)

        return launch

    async def _ensure_browser(self, launcher):
        if self._browser is None:
            self._browser = await launcher()
        return self._browser

    async def aclose(self) -> None:
        """退出时释放浏览器（§16.5 进程级复用的对称收尾）。"""
        browser, self._browser = self._browser, None
        if browser is not None:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass


def _loads(text: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError:
        return {"event": "error", "reason": text}
    return data if isinstance(data, dict) else {"event": "error", "reason": text}


def _format_reject(msg: dict) -> str:
    """风控拒绝要**说清是哪一类**，否则用户无从下手（参考实现同口径）。"""
    reason = msg.get("reason")
    code = reason.get("verifyCode") if isinstance(reason, dict) else None
    hints = {
        "F001": "出口 IP / 运行环境被风控识别（云服务器与数据中心 IP 几乎必现）"
                "→ 换住宅代理后重试",
        "T001": "验证参数已过期 → 网关会自动刷新重试",
        "T002": "验证参数已被使用 → 网关会自动刷新重试",
    }
    text = json.dumps(msg, ensure_ascii=False)[:300]
    hint = hints.get(str(code or ""))
    return f"风控拒绝({code}): {hint}。原始信息: {text}" if hint \
        else f"验证码未通过: {text}"


def _detect_browser_channel() -> str | None:
    """优先用本机真实 Chrome/Edge（自带 Chromium 更易被识破，参考实现结论）。"""
    import sys
    from pathlib import Path

    if sys.platform == "darwin":
        if Path("/Applications/Google Chrome.app").exists():
            return "chrome"
        if Path("/Applications/Microsoft Edge.app").exists():
            return "msedge"
        return None
    import shutil

    for exe, channel in (("google-chrome", "chrome"), ("google-chrome-stable", "chrome"),
                         ("microsoft-edge", "msedge"), ("chromium", None)):
        if shutil.which(exe):
            return channel or "chromium"
    return None


#: 进程内单例（浏览器复用要求它必须跨账号、跨 tick 存活）
_SOLVER: CaptchaSolver | None = None


def get_solver(*, proxy: str, site_root: str = "https://zcode.z.ai",
               manual: bool = False) -> CaptchaSolver:
    """取/建求解器；代理或 manual 变化时重建（代理是硬依赖参数，不能沿用旧值）。"""
    global _SOLVER
    if _SOLVER is None or _SOLVER.proxy != (proxy or "").strip() or _SOLVER.manual != manual:
        _SOLVER = CaptchaSolver(proxy=proxy, site_root=site_root, manual=manual)
    return _SOLVER


def reset_solver_for_tests() -> None:
    """测试注入：丢弃单例（生产不调用）。"""
    global _SOLVER
    _SOLVER = None
