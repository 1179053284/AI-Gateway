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

## ✅ 已落地的 3012 防线（2026-10-07，P0 批次；取证见文末「3012 防线实施记录」）

## ⚠️ 已知缺口（本轮只登记，不在本层实现；详见 M6-5c 报告）

1. **system 身份块**：~~DSH 实测「缺官方身份块 → `3012 unusual activity`」
   （`zcode-identity.ts:1-30` 的准入矩阵）。本层**不做**请求体注入（那是产品策略、
   不是协议接线；且会覆盖调用方 system）——真实可用性待 D1 实测后裁决。~~
   **已裁决并实施（2026-10-07 P0-1）**：10-05/10-06 实盘 31 次 zcode 尝试
   （10× JSON 3012 + 21× WAF HTML）已把 D1 待裁决点**裁决完毕**——缺身份块的
   形状与 DSH 矩阵的 ✗ 行完全一致。本层经 `identity.build_identity_blocks()`
   注入官方块数组（`upstream/zcode/identity.py`），调用方 system 追加在最后。
   ✅ **D1 已实测通过（2026-10-07 21:55，:8300 真实上游）**：非流式 200 正文
   「收到」（prompt_tokens=622 ≈ 身份块量级）、流式 SSE 全链正常、事件流水
   attempts=1 / switch=0 / 零风控。读数存档 `E2E-20261007-zcode-3012-defense.md` §6。
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
import contextlib
import inspect
import json
from contextvars import ContextVar
from typing import AsyncIterator, Awaitable, Callable

import httpx

from model_gateway.adapters.anthropic_out import ANTHROPIC_VERSION, AnthropicOutAdapter
from model_gateway.adapters.product_out import ProductAccount, ProductOutAdapter
from model_gateway.core.errors import RISK_CONTROL_TYPE, UpstreamError
from model_gateway.upstream.zcode import auth, business_codes, identity, oauth
from model_gateway.upstream.zcode import product as zproduct
from model_gateway.upstream.zcode import quota as zquota

#: 3012 = 服务端风控 `unusual activity`；3007 = 验证码 param 被复用（一次性）
#: —— 两者都是"这条通道此刻不收"，换一条号有可能成功
_RISK_CODES = frozenset({zquota.CODE_RISK_CONTROL, 3007})
#: 这四个（含 403）状态码在 `errors.classify()` 里各有归属（AUTH / NOT_FOUND / CANCELED / QUOTA），
#: 风控归一化**不接管**它们，否则会把既有的终态判定（401→停用）改写成可重试。
_OWN_STATUS = frozenset({401, 403, 404, 408, 429})

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


def _risk_shape(body: str) -> str:
    """P1-5 诊断：错误体的 HTTP 形状 —— `3012-json`（应用层风控）/
    `waf-html`（前置 WAF/CDN 拦截，未到应用层）/ `other`。

    两层的处置与成因完全不同：WAF-HTML 指向**出口 IP / TLS 指纹 / 行为画像**
    （换号风暴的直接推手），3012-JSON 指向**请求体内容或账号标记** ——
    不区分则归因必然错一半。"""
    head = (body or "").lstrip()[:100].lower()
    if head.startswith("<!doctype") or head.startswith("<html"):
        return "waf-html"
    return "3012-json"


def _as_risk_control(e: UpstreamError) -> UpstreamError:
    """把 ZCode 的**通道级风控形状**归一化成 `errors.RISK_CONTROL_TYPE`；认不出就原样返回。

    为什么必须在产品层做：ZCode 的错误住在信封里（`{"code":3012,"msg":"unusual activity"}`），
    既没有 `error.type`、HTTP 状态又可能是 4xx/405 ⇒ 按通用映射一律落 `BAD_REQUEST` ⇒
    不换号、不计 C、不冷却（本文件顶部 F-4 登记的老问题）。而它是**账号级状态**，与 429 同类：
    把事实判对之后，既有的 C / y / 冷却 / 换号机器自然会处理它
    （Q35-③ 红线：不许用"跳过它/隐藏它"回避 —— 这里不是跳过，是分类正确）。

    认得的形状（逐条有出处，不扩写）：
    · 信封 `code ∈ {3012 风控, 3007 验证码一次性}`（`quota.py:49`、`out.py` 顶部取证表）；
    · `quota.looks_like_risk_control(msg)` 命中的文案（与额度腿**同一把尺**）；
    · HTTP 405 —— `billing.py:59` 把 405 与 3012 并列为风控信号之一。

    🔴 只在「通用映射本来会把它落成 `BAD_REQUEST`」的那些状态码上接管：
    401/403/404/408/429 各有自己的既有语义（凭据被拒 / 模型名无效 / 上游取消 / 额度），
    抢过来会把 `test_zcode_401_disables_the_resource` 钉的终态判定改成可重试 ——
    那是换一种错，不是修这条。
    """
    if e.status_code in _OWN_STATUS:
        return e
    body = e.error_body or ""
    code: object = None
    msg = ""
    with contextlib.suppress(ValueError, TypeError):
        data = json.loads(body)
        if isinstance(data, dict):
            code = data.get("code")
            msg = str(data.get("msg") or data.get("message") or "")
    # 🔴 风控标记只在**真风控形状**上置位（2026-10-08 收紧）。三条判据，逐条有出处：
    #    ① 信封业务码 `code ∈ {3012, 3007}`（`quota.py:50` / `claim.py`，权威）；
    #    ② HTTP **405**（`billing.py:59` 把 405 与 3012 并列为风控信号）；
    #    ③ 响应体命中风控文案（`quota.looks_like_risk_control`，与额度腿同一把尺）。
    #
    # ⚠️ ③ 必须**限定在真有响应体**时（`body` 非空）：出站层归一化过的信封错误带
    # `error_body`，而网络类错误（`status_code=None`、无 body）不得因文案误判 ——
    # 否则一条 `{"code":2007,"msg":"unusual activity"}`（上游异常，官方归因
    # `server_error`）会被当成风控「首试即 bench 30min + 不换号」，
    # 而它本该走 RETRYABLE 重试/换号（2026-10-08 自测抓到）。
    risk_by_code = code in _RISK_CODES
    risk_by_text = bool(body) and zquota.looks_like_risk_control(msg)
    if risk_by_code or risk_by_text or e.status_code == 405:
        e.error_type = e.error_type or RISK_CONTROL_TYPE
        # 🔴 P0-2：置风控标记（分类仍走 RETRYABLE——2026-10-05 用户裁定
        # 「多次失败应排除出可用范围」的换号语义保留；处置由调度器按标记走
        # 「首试即 30min bench + 不重试同资源」，见 `core/errors.py` 字段注释）
        e.risk_control = True
        _attach_risk_diagnostics(e, body)
    return e


#: 本请求是否已注入官方身份块（P1-5 诊断：3012 时报告「身份块已注入」还是
#: 「未注入」——区分「请求形状问题」与「账号被标记」。ContextVar 与 captcha
#: 同一模式：适配器实例被并发共享，不能放实例属性）
_IDENTITY_INJECTED: ContextVar[bool] = ContextVar("zcode_identity_injected", default=False)
#: 本请求 system 的**实测**字符数（P1-5 诊断：读真实请求体形状，不是常量回显——
#: DSH 诊断行的立意就是「实测值 vs 官方预期」并排才可判形状漂移）
_IDENTITY_CHARS: ContextVar[int] = ContextVar("zcode_identity_chars", default=0)


def _attach_risk_diagnostics(e: UpstreamError, body: str) -> None:
    """P1-5 诊断行：3012/WAF 时在错误消息尾部追加可观测上下文。

    形态（照 DSH `zcode-diagnostics.ts` 的立意，但只取本层拿得到的事实）：
    `〔风控诊断 shape=3012-json identity=已注入(实测 3210 字符) logid=…〕`
    - `shape` = 应用层 JSON vs WAF HTML（两层处置不同，必须可判）；
    - `identity` = 本请求是否带官方身份块 + system **实测**字符数
      （DSH 记录过「身份块达标仍 3012」的残例，账号标记 vs 形状问题的唯一现场证据）；
    - `logid` = 上游错误体里的 logid 字段（有则带，无则省）。
    不含凭据、不含 Authorization —— 文本经 `scrub_upstream_text` 出门。
    """
    shape = _risk_shape(body)
    injected = _IDENTITY_INJECTED.get()
    chars = _IDENTITY_CHARS.get()
    # 实测 vs 官方预期并排（identity_chars 含调用方 system，恒 ≥ 官方 2898 才正常；
    # 低于预期 = 身份块被截断/丢失 —— 形状漂移的唯一现场判据）
    expect = identity.OFFICIAL_IDENTITY_CHARS
    if injected:
        diag = (f"〔风控诊断 shape={shape} identity=已注入"
                f"({chars} 字符,官方段≥{expect})")
    else:
        diag = f"〔风控诊断 shape={shape} identity=未注入"
    with contextlib.suppress(ValueError, TypeError):
        data = json.loads(body)
        if isinstance(data, dict) and data.get("logid"):
            diag += f" logid={data['logid']}"
    e.args = (f"{e.args[0]} {diag}〕",) if e.args else (f"{diag}〕",)


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

    # —— chat：wrappers 只做「先取验证码，再走基类」；身份块经 `_prepare_payload` 注入 ——

    def _envelope_error_class(self, data: dict):
        """**自有信封**（`200 + {"code":…,"msg":…}`）的业务码 → 错误类别（2026-10-08）。

        ZCode 用 `200 + 信封` 表达业务错误（`1005` 额度耗尽 / `3007` 安全校验 /
        `3010` 并发上限 …），HTTP 状态本身**没有信息量**。基类原先一律
        `status_code=None` ⇒ RETRYABLE ⇒ 额度耗尽的号被当"网络抖动"反复打
        （实测一轮换号连撞 6 个号各 2 次）。

        码表与口径**逐字取自官方归因表**（出处见 `business_codes.py` 模块头）；
        本方法只做"认了就给类别、没认就返回 None 交回既有逻辑"。

        ⚠️ `3012`（风控）在 `business_codes` 里显式返回 `None` —— 它有自己的通道处置
        （`_as_risk_control` + `risk_control` 标记），不从这条腿走。
        """
        return business_codes.classify_business_code(data.get("code"))

    def _prepare_payload(self, payload: dict) -> dict:
        """给 Anthropic 形状 payload 注入官方身份块（P0-1；缺它 = 405+3012）。

        🔴 这里的「覆盖」是**垫前缀**不是替换：`openai_to_anthropic` 把调用方
        system 拼成单串（`anthropic_out.py:212-213`），这里取出它、作为最后一块
        追加在官方身份块之后 —— 上游检查看的是**前缀结构**（首块逐字 cliPrefix），
        调用方内容必须落在身份块之后（DSH `zcode-identity.ts:98-101`）。

        幂等：payload 已带官方身份块（重复包装防御）时原样返回。
        同步置位 `_IDENTITY_INJECTED` / `_IDENTITY_CHARS`（P1-5 诊断行读它们）。
        """
        caller = payload.get("system")
        if isinstance(caller, list) and identity.has_official_identity(caller):
            _IDENTITY_INJECTED.set(True)  # 已带官方块（防御重复包装 / 外部已注入）
            _IDENTITY_CHARS.set(identity.identity_chars(caller))
            return payload
        caller_text = None
        if isinstance(caller, str) and caller.strip():
            caller_text = caller
        payload = dict(payload)
        payload["system"] = identity.build_identity_blocks(caller_text)
        _IDENTITY_INJECTED.set(True)
        _IDENTITY_CHARS.set(identity.identity_chars(payload["system"]))
        return payload

    async def chat_stream(self, key: str, vendor_model: str, body: dict,
                          timeout: float) -> AsyncIterator[dict]:
        _IDENTITY_INJECTED.set(False)   # 每请求复位（P1-5 诊断事实位）
        _IDENTITY_CHARS.set(0)
        await self._mint_captcha()
        try:
            async for chunk in super().chat_stream(key, vendor_model, body, timeout):
                yield chunk
        except UpstreamError as e:
            raise _as_risk_control(e) from e

    async def chat_nonstream(self, key: str, vendor_model: str, body: dict,
                             timeout: float) -> dict:
        _IDENTITY_INJECTED.set(False)   # 每请求复位（P1-5 诊断事实位）
        _IDENTITY_CHARS.set(0)
        await self._mint_captcha()
        try:
            return await super().chat_nonstream(key, vendor_model, body, timeout)
        except UpstreamError as e:
            raise _as_risk_control(e) from e
