"""ZCode **出站适配**（tech-design v2.0 §17/§18/§22.3；M6-5c 接线）。

本产品走 **Anthropic Messages** 协议（§17 的既有设计），故直接接
`adapters/anthropic_out.py::AnthropicOutAdapter`（传输 / SSE 事件翻译 / usage 映射
全部复用，**不复制第二份**），只覆盖三个产品差异：

| 项 | 本层 | 取证 |
|---|---|---|
| 鉴权头 | Plan/JWT 通道：`Authorization: Bearer <zcodejwttoken>` + `X-Device-Mid` —— **统一走 `auth.build_headers`** | §17 / `auth.py:53-71`；`zcode-adapter.ts:559-565` |
| 协议头 | `anthropic-version: 2023-06-01`（`auth.build_headers` 只覆盖 ZCode 自有头，协议头由本层补齐；常量与 `adapters/anthropic_out.py` **同源**） | `15 §②` 请求头清单（`agent.py:80-92`） |
| TLS 指纹 | **按配置** `gateway.zcode.fingerprint`（`curl_cffi` 不可用时 `auth.build_client` 内自动降级 httpx） | §17「TLS 指纹」表；`anthropic_out.py:456-461` |
| 每请求验证码 | 走 `CAPTCHA_PROVIDER` **注入缝**（见下） | `zcode-adapter.ts:494-495,553-565` |

## 🔴 验证码注入缝（`CAPTCHA_PROVIDER`）—— 为什么不直接接 `captcha.py`

- DSH 的 ZCode 推理是**每请求一个新鲜 captcha**（`zcode-adapter.ts:30-33`：
  param **一次性**，复用会再得 `3007`）；
- 而 §16.5 的 `captcha.py::CaptchaSolver` 是**为领取设计**的：45s **缓存** +
  宽限期后台刷新（`captcha.py:22-24`）——把带缓存的 solver 直接搬到转发路径上，
  第一次请求之后就会一直复用旧 param（正是 DSH 记录过的 `3007` 缺陷形态）；
- 故本层**不硬接**、也**不自己写一个"绕过"**（D1 直连实测前不编造）：
  定义 `CAPTCHA_PROVIDER`（无参协程，返回 param 字符串）+ 构造参数 `captcha=`，
  由后续波次按「每请求现产 + 住宅代理」的口径接入（**TODO**，见 M6-5c 报告）。
- **未注入时的行为 = §17 三级降级链的第二步「JWT 直连」**（`15 §⑧`）：
  不带验证码头直接发请求 —— 这是设计内的降级档，**不是**绕过；上游若强制验证码
  会回 `3007`，如实透传（可重试语义）。

## ⚠️ 已知缺口（本轮只登记，不在本层实现；详见 M6-5c 报告）

1. **system 身份块**：DSH 实测「缺官方身份块 → `3012 unusual activity`」
   （`zcode-identity.ts:1-30` 的准入矩阵）。本层**不做**请求体注入（那是产品策略、
   不是协议接线；且会覆盖调用方 system）——真实可用性待 D1 实测后裁决。
2. **3007 / 3012 的通道级细分**：现有分类按 HTTP 状态走（§22.5-5 明确
   「通道级 vs 账号级细分留待 D1 实测结论」），本层只保真透传原始错误体。
3. **流量路径的 3012 无护栏（F-4，M6-6 Fix-γ 登记）**：`circuit.enter()` 现有**两个**调用点
   —— **领取**路径（`ops/builtin/zcode_claim.py`）与**额度**路径（`upstream/zcode/product.py`
   的风控支，2026-10-02 联网腿落地时新增）；**转发**路径依旧只按 HTTP
   状态分类 —— 4xx（非 401/404/429/408）落 `BAD_REQUEST` → 原样透传、不计 C、不冷却
   （`core/scheduler.py` 的 BAD_REQUEST 分支）。而 DSH 实测该风控有**账号惩罚梯度**
   （`zcode-identity.ts:21-31`：30 分钟 / 24h 内 3 次→24h / **5 次停用**），且
   `docs/research/24 §2-D1` 明确「直连是否成立」仍是最高待裁决点 —— 用户重复重试
   可能烧号。**本波次的处置是诚实标注，不是绕过、也不是加一层熔断**：未注入验证码时
   zcode 模型不进 `/v1/models`，总览横幅写明「zcode 直连前提未验证（D1）」
   （`main.py::_outbound_premise_gap` + `config_warnings()` 的 ⑤ 条）。
   接线 / 放行前先走 D1 最小实测；交付话术不得写"zcode 模型转发可用"。

## 🔴 验证码缝的异常契约（F-3，M6-6 Fix-γ）

`CAPTCHA_PROVIDER` 是**本进程内的前置步骤**（Playwright 求解最可能超时），它抛出的
任何异常都**必须**在 `_mint_captcha` 处转成 `UpstreamError`：调度器的捕获面只有
`UpstreamError / CancelledError`（`core/scheduler.py:381-383,634-636`），裸异常会冒穿成
**500 Internal Server Error**（无分类、无事件行、无冷却、无提示）。包装语义 =
可读文案 + 可重试（`status_code=None` → RETRYABLE：换资源 / 重试都可能成功）。
"""

from __future__ import annotations

import asyncio
import inspect
from contextvars import ContextVar
from typing import AsyncIterator, Awaitable, Callable

import httpx

from model_gateway.adapters.anthropic_out import ANTHROPIC_VERSION, AnthropicOutAdapter
from model_gateway.adapters.product_out import ProductAccount, ProductOutAdapter
from model_gateway.core.errors import UpstreamError
from model_gateway.upstream.zcode import auth, oauth
from model_gateway.upstream.zcode import product as zproduct

#: 验证码头（`zcode-upstream.ts:87-88`；`x-aliyun-captcha-verify-*`）
CAPTCHA_HEADER = "x-aliyun-captcha-verify-param"
CAPTCHA_REGION_HEADER = "x-aliyun-captcha-verify-region"
#: 验证码区域缺省（`zcode-adapter.ts:563` 的 `?? 'cn'`）
CAPTCHA_REGION_DEFAULT = "cn"

#: 验证码注入缝：无参协程 → param 字符串（空串 = 上游已关人机校验，正常放行）。
#: 生产默认 `None` = 不注入（= §17 降级链的「JWT 直连」档）。
CAPTCHA_PROVIDER: Callable[[], Awaitable[str]] | None = None

#: 当前请求的验证码 param（**每请求一次**）。用 ContextVar 而非实例属性：
#: 同一资源适配器被并发请求共享，实例属性会让 A 请求拿到 B 的 param
#: （param 一次性 → 必得 3007）；ContextVar 按「每请求一个 task」天然隔离。
_CAPTCHA_VAR: ContextVar[str] = ContextVar("zcode_captcha_param", default="")


def _fingerprint_enabled() -> bool:
    """`gateway.zcode.fingerprint`（配置不可用 → False，**不阻断**出站）。"""
    try:
        from model_gateway.config.loader import load_config

        return bool(getattr(getattr(load_config().gateway, "zcode", None),
                            "fingerprint", False))
    except Exception:  # noqa: BLE001 — 配置读不动不应让出站整体不可用
        return False


class ZcodeOut(AnthropicOutAdapter, ProductOutAdapter):
    """ZCode 出站适配器（Plan/JWT 通道 + anthropic 协议；§17/§18）。"""

    def __init__(self, account: ProductAccount, *, client: httpx.AsyncClient | None = None,
                 fingerprint: bool | None = None,
                 captcha: Callable[[], Awaitable[str]] | None = None) -> None:
        if fingerprint is None:
            fingerprint = _fingerprint_enabled()
        # 基序 = (AnthropicOutAdapter, ProductOutAdapter)：chat_* / aclose 取 anthropic 实现
        # （transport / SSE / usage 映射全部复用），契约属性由 ProductOutAdapter 提供。
        AnthropicOutAdapter.__init__(self, account.base_url, client=client,
                                     fingerprint=fingerprint)
        ProductOutAdapter.__init__(self, account, protocol="anthropic")
        self._captcha = captcha

    # —— 凭据与请求头（产品差异只在这里）——

    def _headers(self, key: str) -> dict:
        """Plan/JWT 通道鉴权头（覆盖基类的静态 `x-api-key`/Bearer 二选一）。

        🔴 凭据从账号目录自解（§22.3）：调度侧传进来的 `key` 对产品资源恒为空串，
        这里**忽略**它（避免"两处凭据"的分叉面，与 `FamilyOpenAIOut._headers` 同口径）。
        """
        del key
        cred, meta, _device = self.resolve_context()
        jwt, device_mid = zproduct.outbound_credentials(cred, meta)
        if not jwt:
            raise UpstreamError(
                f"ZCode 账号 {self.account_ref} 的凭据缺少 zcodejwttoken"
                "（凭据本体与客户端数据根都没有）—— 请重新登录或导入该账号")
        headers = auth.build_headers("jwt", auth.Credentials(jwt=jwt, device_mid=device_mid),
                                     app_version=oauth.DEFAULT_APP_VERSION)
        # 🔴 Anthropic 协议版本头：`auth.build_headers` 只覆盖 ZCode 自有头
        # （UA / 设备 / 平台 / 语言），anthropic-version 由本层补齐 —— 缺它 = 畸形请求
        # （`15 §②` 请求头清单 `agent.py:80-92`：`anthropic-version: 2023-06-01`）。
        headers["anthropic-version"] = ANTHROPIC_VERSION
        param = _CAPTCHA_VAR.get()
        if param:
            headers[CAPTCHA_HEADER] = param
            headers[CAPTCHA_REGION_HEADER] = CAPTCHA_REGION_DEFAULT
        return headers

    async def _mint_captcha(self) -> None:
        """本请求现产一个 captcha param（未注入 → 空串 = JWT 直连档，不多发任何头）。

        🔴 F-3（M6-6 Fix-γ）：**任何 provider 异常都在这里转成 `UpstreamError`** ——
        调度器的捕获面只有 `UpstreamError / CancelledError`（`core/scheduler.py` 的
        非流式 / 流式两条错误分支），Playwright 超时之类的裸异常否则会冒穿成
        500 Internal Server Error（无分类、无事件行、无冷却、无提示）。
        包装语义 = 可读文案 + **可重试**（不传 status_code → 分类器归 RETRYABLE）：
        captcha 求解是本进程内的前置步骤，失败与"上游不可达"同类，换资源/重试都可能成功。
        `CancelledError`（停机 / 断连）与已是 `UpstreamError` 的异常原样冒（不重复包装）。
        """
        provider = self._captcha if self._captcha is not None else CAPTCHA_PROVIDER
        if provider is None:
            _CAPTCHA_VAR.set("")
            return
        try:
            param = provider()
            if inspect.isawaitable(param):
                param = await param
        except asyncio.CancelledError:
            raise                      # 取消语义照传（不得包成上游错误）
        except UpstreamError:
            raise                      # 已是契约异常（分类/文案由抛出方负责）
        except Exception as e:  # noqa: BLE001 — 见 docstring：调度器只认 UpstreamError
            raise UpstreamError(
                f"验证码生成失败（{type(e).__name__}: {e}）—— 本请求需要验证码通道，"
                "求解器在本进程内前置步骤失败（可重试）；请检查验证码求解器与网络后重试，"
                "或暂时停用该 ZCode 资源") from e
        _CAPTCHA_VAR.set(str(param or ""))

    # —— chat：wrappers 只做「先取验证码，再走基类」——

    async def chat_stream(self, key: str, vendor_model: str, body: dict,
                          timeout: float) -> AsyncIterator[dict]:
        await self._mint_captcha()
        async for chunk in super().chat_stream(key, vendor_model, body, timeout):
            yield chunk

    async def chat_nonstream(self, key: str, vendor_model: str, body: dict,
                             timeout: float) -> dict:
        await self._mint_captcha()
        return await super().chat_nonstream(key, vendor_model, body, timeout)
