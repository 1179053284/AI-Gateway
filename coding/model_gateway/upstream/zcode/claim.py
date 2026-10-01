"""ZCode 签到 / 领取的 HTTP 交互（tech-design v2.0 §16.6 / §17 / `14` §③）。

🔴 **归属**（§16.6）：`upstream/` 负责"**怎么调上游**"，`ops/` 负责"什么时候调、怎么批量、结果怎么归类"。
本模块只做 HTTP 交互与上游语义解析；调度与四类结果分类在 `ops/`。

**三段式**（`14` §③）::

    1. GET  <base>/billing/preview   → data.plans[]（按 priority 降序取 [0]）
    2. GET  client/configs           → captcha 配置 → 阿里云无痕求解 → param
    3. POST <base>/billing/claim     → body {"plan_id"} + X-Aliyun-Captcha-Verify-Param

**激活事件**（≈签到语义）：`POST /api/v1/event/report`，两条 `app_launch` + `app_daily_active`，
**事件体固定 16 字段**（`claim.rs:158-177` 逐键枚举）。

**幂等业务码**（`14` §3.2）：`1003` 已领取过 / `1005` 今日名额用完（回带 `next_at`）。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from model_gateway.core.resources import normalize_base_url

#: 领取业务码（`14` §3.2）
CODE_OK = 0
CODE_PLAN_MISSING = 1001
CODE_ACTIVITY_ENDED = 1002
CODE_ALREADY_CLAIMED = 1003
CODE_NOT_ELIGIBLE = 1004
CODE_QUOTA_EXHAUSTED = 1005
# 其余观测到的码值（3001 参数错 / 3007 验证码失败）**有意不列常量**：
# 分类判据里它们都归 `failed`，列出未引用的常量 = 死代码（接线护栏会报）

#: 激活事件体的 16 个键（**一个都不能少**，`claim.rs:158-177`）
EVENT_KEYS = (
    "event_id", "client_timezone", "client_language", "element_name", "event_region",
    "event_type", "event_text", "event_extra_detail", "user_id", "screen_resolution",
    "app_version", "device_os_category", "device_os_version", "device_mid", "mac_id",
    "marketing_params",
)

SCREEN_RESOLUTION = "2560x1440"


@dataclass
class ClaimOutcome:
    """领取结果（上游语义层，未分类）。"""

    code: int
    message: str = ""
    plan_id: str = ""
    next_at: str = ""
    raw: dict | None = None


@dataclass
class PreviewPlan:
    plan_id: str
    priority: int = 0
    name: str = ""


class CaptchaUnavailable(RuntimeError):
    """验证码求解不可用（未配置住宅代理 / 求解失败）。

    🔴 用户侧落点（§16.5）：未配置住宅代理时**不静默失败** —— CLI 会据此给出明确提示。
    """


def _headers(token: str, device_mid: str = "", *, app_version: str = "3.11.2") -> dict:
    """ZCode 联网请求头（`14` §3.1 的 13 个头，本模块按需取子集）。

    鉴权头 + 通用客户端身份头由 `auth.build_headers` 统一给（§17：双通道鉴权归 auth），
    这里只补**领取/preview 接口额外要求的 ZCode 客户端字段** —— 不再各写一份 Bearer 判定。
    """
    from model_gateway.upstream.zcode.auth import Credentials, build_headers

    h = build_headers("jwt", Credentials(jwt=token, device_mid=device_mid),
                    app_version=app_version)
    h.update({
        "X-ZCode-App-Version": app_version,
        "X-Client-Timezone": _tz(),
        "X-Os-Category": os.sys.platform,
    })
    return h


def _tz() -> str:
    off = -dt.datetime.now().astimezone().utcoffset().total_seconds() / 3600  # type: ignore[union-attr]
    sign = "+" if off >= 0 else "-"
    return f"UTC{sign}{abs(int(off))}"


def pick_plan(preview_body: dict) -> PreviewPlan | None:
    """从 preview 响应取 priority 最高的 plan（`14` §⑥）。"""
    plans = ((preview_body or {}).get("data") or {}).get("plans") or []
    best: PreviewPlan | None = None
    for p in plans:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("plan_id") or "")
        if not pid:
            continue
        cand = PreviewPlan(plan_id=pid, priority=int(p.get("priority") or 0),
                           name=str(p.get("name") or ""))
        if best is None or (cand.priority, -ord(cand.plan_id[0])) > (best.priority, -ord(best.plan_id[0])):
            best = cand
    return best


def parse_claim(body: dict) -> ClaimOutcome:
    """解析 claim 响应（业务码 + 下次可领时间）。"""
    if not isinstance(body, dict):
        return ClaimOutcome(code=-1, message="响应不是对象")
    code = body.get("code")
    plan = ((body.get("data") or {}).get("plan") or {}) if isinstance(body.get("data"), dict) else {}
    return ClaimOutcome(
        code=int(code) if isinstance(code, int) else -1,
        message=str(body.get("msg") or body.get("message") or ""),
        plan_id=str(plan.get("plan_id") or ""),
        next_at=str(plan.get("ends_at") or ""),   # 1005 时作下次可领时间
        raw=body,
    )


def build_activation_event(*, element: str, user_id: str, device_mid: str,
                           app_version: str = "3.11.2") -> dict:
    """构造激活事件体（**固定 16 字段**，`claim.rs:158-177`）。"""
    return {
        "event_id": str(uuid.uuid4()),
        "client_timezone": _tz(),
        "client_language": "zh-CN",
        "element_name": element,
        "event_region": "app",
        "event_type": "view",
        "event_text": "",
        "event_extra_detail": {},
        "user_id": user_id,
        "screen_resolution": SCREEN_RESOLUTION,
        "app_version": app_version,
        "device_os_category": "macos",
        "device_os_version": "",
        "device_mid": device_mid,
        "mac_id": "",
        "marketing_params": "{}",
    }


class ZCodeClaimClient:
    """ZCode 领取客户端（三段式）。

    `captcha_solver` 可注入：生产用 Playwright 求解阿里云无痕；**未配置时抛
    `CaptchaUnavailable`**（由上层降级为 `failed` 并给出用户提示，§16.5）。
    """

    def __init__(self, base_url: str, token: str, device_mid: str = "",
                 client: httpx.AsyncClient | None = None,
                 captcha_solver=None, proxy: str = ""):
        # 归一化口径与 `core.resources.normalize_base_url` 同源（验收 S-26）
        self.base_url = normalize_base_url(base_url)
        self.token = token
        self.device_mid = device_mid
        self._client = client
        self._captcha_solver = captcha_solver
        #: 住宅代理（验证码求解必需，§16.5）；空 = 直连
        self.proxy = proxy

    def _http(self, timeout: float) -> httpx.AsyncClient:
        """构造客户端（每次调用独立，`proxy` 生效时走代理）。"""
        kw: dict = {"timeout": timeout}
        if self.proxy:
            kw["proxy"] = self.proxy
        return httpx.AsyncClient(**kw)

    async def _post(self, path: str, payload: dict, timeout: float = 20.0) -> dict:
        url = f"{self.base_url}{path}"
        h = _headers(self.token, self.device_mid)
        if self._client is not None:
            r = await self._client.post(url, json=payload, headers=h, timeout=timeout)
        else:
            async with self._http(timeout) as c:
                r = await c.post(url, json=payload, headers=h)
        try:
            return r.json()
        except ValueError:
            return {"code": -1, "msg": f"HTTP {r.status_code} 非 JSON"}

    async def _get(self, path: str, timeout: float = 20.0) -> dict:
        url = f"{self.base_url}{path}"
        h = _headers(self.token, self.device_mid)
        if self._client is not None:
            r = await self._client.get(url, headers=h, timeout=timeout)
        else:
            async with self._http(timeout) as c:
                r = await c.get(url, headers=h)
        try:
            return r.json()
        except ValueError:
            return {"code": -1, "msg": f"HTTP {r.status_code} 非 JSON"}

    async def preview(self) -> PreviewPlan | None:
        return pick_plan(await self._get("/billing/preview"))

    async def solve_captcha(self, *, manual: bool = False) -> str:
        """求解验证码（§16.5）。

        🔴 本方法**不判断"为什么不可用"**：原因只可能来自求解器（未配代理 / 依赖缺失 /
        超时 / 被风控拒），由它给出与原因一致的文案。上一轮这里是"求解器恒缺 →
        谎称未配置住宅代理"的发生地：配好代理的用户照提示查代理，永远查不出问题。
        求解器缺失属于**装配错误**，文案也照这个事实写。
        """
        if self._captcha_solver is None:
            raise CaptchaUnavailable(
                "验证码求解器未接入（装配错误）—— 请检查网关版本与 `gateway.zcode` 配置；"
                + ("已指定 --manual：请在客户端手动完成一次领取后重试" if manual
                   else "也可加 --manual 由人工完成验证码"))
        return await self._captcha_solver()

    async def claim(self, plan_id: str, *, manual: bool = False) -> ClaimOutcome:
        param = await self.solve_captcha(manual=manual)
        h_extra = {"X-Aliyun-Captcha-Verify-Param": param}
        url = f"{self.base_url}/billing/claim"
        h = {**_headers(self.token, self.device_mid), **h_extra}
        if self._client is not None:
            r = await self._client.post(url, json={"plan_id": plan_id}, headers=h, timeout=20.0)
        else:
            async with self._http(20.0) as c:
                r = await c.post(url, json={"plan_id": plan_id}, headers=h)
        try:
            return parse_claim(r.json())
        except ValueError:
            return ClaimOutcome(code=-1, message=f"HTTP {r.status_code} 非 JSON")

    async def report_activation(self, *, user_id: str) -> list[dict]:
        """上报激活事件（`app_launch` + `app_daily_active`，顺序上报）。

        🔴 上报前**自检 16 字段齐全** —— 缺字段会被服务端拒绝（施工级数字，`claim.rs:158-177`）。
        """
        out = []
        for element in ("app_launch", "app_daily_active"):
            body = build_activation_event(element=element, user_id=user_id,
                                          device_mid=self.device_mid)
            if not event_body_is_complete(body):
                raise ValueError(
                    f"激活事件体字段不齐（需 {len(EVENT_KEYS)} 个，实际 {len(body)}）—— "
                    "这属实现缺陷，拒绝上报以免污染服务端统计")
            out.append(await self._post("/api/v1/event/report", body))
        return out

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


def event_body_is_complete(body: dict) -> bool:
    """自检：激活事件体是否 16 字段齐全（**施工级数字**，缺字段会被服务端拒绝）。"""
    return all(k in body for k in EVENT_KEYS) and len(body) == len(EVENT_KEYS)
