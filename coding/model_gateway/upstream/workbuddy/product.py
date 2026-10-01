"""WorkBuddy（国际版）产品钩子（tech-design v2.0 §22.3 冻结签名；M6-2 实施）。

本产品证据面（§22.4 行 + `20 §1.1/§3.1`；`21 §1.1`）：

- 登录：**同 buddy**（同族，共用同一后端协议与登录流程，`product.ts:1-30`）
- 设备：**无设备标识**（`20 §2.7`）
- 额度 ✓（`get-user-resource` **两产品通用**，只有 baseURL 不同，`credits.ts:39-50`）
- 签到 **✗** —— 国际版内核里连 `checkin-status` / `daily-checkin` 的字面量都不存在
  （`credits.ts:42-45`、`credits-capabilities.js:65`、`product.ts:378-380`）→ 能力位 `checkin=False`
- 模型：remote `/v3/config`（**国际版域名**）+ 兜底表（`WORKBUDDY_FALLBACK_MODELS`，`21 §1.1`）

🔴 与 buddy **共享全部实现**（`buddy/hooks.py` + `buddy/protocol.py`，§22.1）；
   本文件只声明差异：平台标识 / X-Product-Code / UA / 登录 URL 附加参数 / 兜底表
   —— 五个差异**全部是参数**，没有第二份复制实现。
"""

from __future__ import annotations

from model_gateway.accounts.registry import get as registry_get
from model_gateway.accounts.types import (
    Challenge,
    ClaimOutcome,
    LoginOutcome,
    ModelInfo,
    ProbeResult,
    ProductMeta,
    QuotaSnapshot,
)
from model_gateway.upstream.buddy import hooks
from model_gateway.upstream.buddy.protocol import ProductProfile

#: 本产品标识（§22.4；与 `accounts/registry.py` 的键、账号目录名一致）
PRODUCT = "workbuddy"

#: 兜底模型目录 —— **逐条照抄** DSH `WORKBUDDY_FALLBACK_MODELS`（`product.ts:295-367`，23 条）。
#: 来源（`product.ts:286-298`）：IDE 本地缓存 `~/.workbuddy-ai/local_storage/*.info`
#: （`WorkbuddyAuthProductCoordinator` 写入的 ProductManager 合并结果），即 IDE 模型选择器
#: 实际展示的清单；`maxOutputTokens` 全部来自 2026-09-19 对国际版 `/v3/config` 的实测。
#: **顺序即 IDE 展示顺序**（`cli` agent 白名单顺序），不得重排（`product.ts:293`）。
#: `gpt-5.3-codex` 远端未下发 maxOutputTokens → 保持不填（不臆造数值，`product.ts:348-350`）。
#: 搬运映射同 buddy（`buddy/product.py` 的注释）；`defaultReasoningEffort` 不搬运（冻结类型无该字段）。
_WORKBUDDY_FALLBACK_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(id="default-model", name="Auto", context_window=176_000, max_output=24_000,
              image_input=True),
    ModelInfo(id="fast-model", name="Fast", context_window=200_000, max_output=32_000,
              image_input=True, effort_levels=("medium",)),
    ModelInfo(id="balanced-model", name="Balanced", context_window=256_000, max_output=32_000,
              image_input=True, effort_levels=("medium",)),
    ModelInfo(id="primary-model", name="Primary", context_window=272_000, max_output=72_000,
              image_input=True, effort_levels=("high",)),
    ModelInfo(id="deep-model", name="Deep", context_window=176_000, max_output=24_000,
              image_input=True),
    ModelInfo(id="hy4-preview-f", name="Hy4 preview", context_window=1_000_000,
              max_output=64_000, image_input=True, effort_levels=("high",)),
    ModelInfo(id="hy4-preview", name="Hy4 preview", context_window=1_000_000, max_output=64_000,
              image_input=True, effort_levels=("high",)),
    ModelInfo(id="hy3", name="Hy3", context_window=192_000, max_output=64_000,
              image_input=True, effort_levels=("low", "high")),
    ModelInfo(id="deepseek-v4.1-flash", name="Deepseek-V4.1-Flash", context_window=1_000_000,
              max_output=128_000, image_input=True, effort_levels=("high",)),
    # 新加坡区同代模型（-sg 后缀），远端下发且实测能看图（`product.ts:319-323`）
    ModelInfo(id="deepseek-v4.1-flash-sg", name="Deepseek-V4.1-Flash", context_window=1_000_000,
              max_output=128_000, image_input=True, effort_levels=("high",)),
    ModelInfo(id="gpt-6-astra", name="GPT-6-Astra", context_window=1_000_000, max_output=128_000,
              image_input=True, effort_levels=("low", "medium", "high", "xhigh", "max")),
    ModelInfo(id="gpt-5.6-sol", name="GPT-5.6-Sol", context_window=1_000_000, max_output=128_000,
              image_input=True, effort_levels=("low", "medium", "high", "xhigh", "max")),
    ModelInfo(id="gpt-5.6-terra", name="GPT-5.6-Terra", context_window=1_000_000,
              max_output=128_000, image_input=True,
              effort_levels=("low", "medium", "high", "xhigh", "max")),
    ModelInfo(id="gpt-5.6-luna", name="GPT-5.6-Luna", context_window=1_000_000, max_output=128_000,
              image_input=True, effort_levels=("low", "medium", "high", "xhigh", "max")),
    ModelInfo(id="gpt-5.5", name="GPT-5.5", context_window=1_000_000, max_output=128_000,
              image_input=True, effort_levels=("low", "medium", "high", "xhigh")),
    ModelInfo(id="gpt-5.4", name="GPT-5.4", context_window=272_000, max_output=72_000,
              image_input=True, effort_levels=("low", "medium", "high", "xhigh")),
    ModelInfo(id="gpt-5.3-codex", name="GPT-5.3-Codex", context_window=272_000,
              image_input=True, effort_levels=("medium",)),
    ModelInfo(id="gemini-3.5-flash", name="Gemini-3.5-Flash", context_window=1_000_000,
              max_output=65_536, image_input=True, effort_levels=("medium",)),
    ModelInfo(id="glm-5.3", name="GLM-5.3", context_window=1_000_000, max_output=48_000,
              image_input=True, effort_levels=("low", "high", "max")),
    ModelInfo(id="glm-5.2", name="GLM-5.2", context_window=1_000_000, max_output=48_000,
              image_input=True, effort_levels=("high", "xhigh")),
    ModelInfo(id="kimi-k3", name="Kimi-K3", context_window=1_000_000, max_output=32_000,
              image_input=True, effort_levels=("medium",)),
    ModelInfo(id="kimi-k2.8-preview", name="Kimi-K2.8-Preview", context_window=1_000_000,
              max_output=32_000, image_input=True, effort_levels=("low", "high", "max")),
    ModelInfo(id="kimi-k2.6", name="Kimi-K2.6", context_window=256_000, max_output=32_000,
              image_input=True, effort_levels=("medium",)),
)

#: 本产品档案（差异全部收敛在这里，`product.ts:381-408`）。
#: ⚠️ UA 取国际版形态 `WorkBuddy/5.5.2 WorkBuddy AI/5.5.2 CLI/5.5.2`（`product.ts:70,389`）：
#: 腾讯后台按出站 UA 归因「使用端」，用错产品线 UA 账单会显示为 `-`（`product.ts:93-99`）。
#: ⚠️ `append_session_params=True`：国际版登录 URL 需追加 `version` 与 `loginSessionId`
#: （`product.ts:137-141,405-406`；`buddy-oauth.ts:525-538`）。
_PROFILE = ProductProfile(
    id=PRODUCT,
    platform="workbuddy-ai",                              # product.ts:383
    product_code="workbuddy",                             # product.ts:387
    user_agent="WorkBuddy/5.5.2 WorkBuddy AI/5.5.2 CLI/5.5.2",  # product.ts:70,389
    fallback_models=_WORKBUDDY_FALLBACK_MODELS,
    append_session_params=True,                           # product.ts:405
    plugin_version="5.5.2",                               # product.ts:406
)


def meta() -> ProductMeta:
    """产品注册信息（唯一事实源 = `accounts/registry.py`，此处不重复填字段）。"""
    return registry_get(PRODUCT)


async def login_start(session) -> Challenge:
    """两步式第一步：取外链授权页（与 buddy 同族，`buddy-oauth.ts:137-167`）。"""
    return await hooks.start_login(_PROFILE, session)


async def login_poll(session) -> LoginOutcome:
    """两步式第二步：轮询 token → 账户（`pending` 不是错误，§22.3）。"""
    return await hooks.poll_login(_PROFILE, session)


async def login_callback(session, params) -> LoginOutcome:
    """本产品为 external_link 轮询型 → 无本机回跳通道（显式拒绝，不伪造成功）。"""
    return await hooks.login_callback(_PROFILE, session, params)


async def _refresh_impl(cred, meta) -> dict:
    """静默续期（§22.3；返回**新的**凭据本体；不可续期 → `NotRefreshable`）。"""
    return await hooks.refresh_credential(_PROFILE, cred, meta)


#: §22.3 钩子名（`def refresh(` 的字面量只允许出现在 `upstream/*/product.py`，见 buddy 同款说明）
refresh = _refresh_impl


async def probe(cred, meta) -> ProbeResult:
    """探活：连通 / 凭据有效两维（额度端点两产品通用，`credits.ts:39-50`）。"""
    return await hooks.probe(_PROFILE, cred, meta)


async def quota(cred, meta) -> QuotaSnapshot:
    """额度快照（与 buddy 同端点，仅 baseURL 不同 → 本产品的「签到 ✗」不影响余额）。"""
    return await hooks.quota(_PROFILE, cred, meta)


async def claim(cred, meta, *, precheck: bool) -> ClaimOutcome:
    """签到：本产品**无签到端点**（能力位 checkin=False）→ `inactive` + 可读原因。

    实际分支在 `buddy/hooks.py::claim`（能力位判据，§22.6）；本函数只做签名接线。
    """
    return await hooks.claim(_PROFILE, cred, meta, precheck=precheck)


async def list_models(cred, meta) -> list[ModelInfo]:
    """模型目录：远端 `/v3/config`（国际版域名）+ 国际版兜底表合并（`21 §1.1`）。"""
    return await hooks.list_models(_PROFILE, cred, meta)


#: 骨架纪律护栏的**登记面**（`tests/accounts/test_registry.py::_implemented_hooks` 读它）：
#: 本产品已接线的钩子名（`claim` 在内：它按能力位返回 `inactive`，**是已接线行为**）。
#: **刻意不列** `login_callback`（无本机回跳通道）—— `build_out` 自 M6-5a 起已接线。
_IMPLEMENTED = ("login_start", "login_poll", "refresh", "probe", "quota", "claim",
                "list_models", "build_out")


def build_out(account) -> OutboundAdapter:
    """构造出站适配器（§22.3「出站适配」；M6-5a 试点）。

    与 buddy **共用同一实现**（`upstream/buddy/out.py::BuddyFamilyOut`）——国际版差异
    全在 `_PROFILE`（UA / X-Product-Code / 基址），没有第二份出站代码。
    """
    from model_gateway.upstream.buddy.out import BuddyFamilyOut
    return BuddyFamilyOut(account, _PROFILE)


#: §22.3 契约表（入口层 `accounts/login.py::_hook` 与 M6-5 按名取用；缺项当场 KeyError）
_HOOKS = {
    "meta": meta,
    "login_start": login_start,
    "login_poll": login_poll,
    "login_callback": login_callback,
    "refresh": refresh,
    "probe": probe,
    "quota": quota,
    "claim": claim,
    "list_models": list_models,
    "build_out": build_out,
}
