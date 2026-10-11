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
#: 首条 system 的补齐文案（= 用户 2026-10-04 指定的原话，逐句保留语义）。
#: 🔴 触发条件：WorkBuddy 通道对**首条不是 system** 的推理请求回
#: `400 {"code":11128,"msg":"first message is not system prompt"}`（:8300 真实两号命中，
#: 同形请求落 CodeBuddy 为 200 ⇒ 这是本产品的通道限制，不是客户端写错了）。
#: 只在"这条请求一条 system 都没有"时补；客户端自己写了 system ⇒ 内容一字不改、只挪到首位。
#: 反转触发条件 = 若上游不再要求首条 system，或用户改口换文案 ⇒ 把档案里这一行置空即可。
_SYSTEM_FIRST = (
    "你是被执行任务的助手。收到用户提示词后，先充分理解其内容，确保完全理解后再执行；"
    "如果任务本身有问题或信息不足，先与用户沟通清楚，"
    "只有在确认你能足够完美地执行、不会有任何问题时，才可以开始执行。"
)

_PROFILE = ProductProfile(
    id=PRODUCT,
    platform="cli",                                       # 🔴 不是 product.ts:383 的 workbuddy-ai，见下
    product_code="workbuddy",                             # product.ts:387
    user_agent="WorkBuddy/5.5.2 WorkBuddy AI/5.5.2 CLI/5.5.2",  # product.ts:70,389
    fallback_models=_WORKBUDDY_FALLBACK_MODELS,
    append_session_params=True,                           # product.ts:405
    plugin_version="5.5.2",                               # product.ts:406
    system_first_text=_SYSTEM_FIRST,                      # 通道要求首条 system（见上注）
)

# ── 登录 platform 为什么是 `cli` 而不是客户端的 `workbuddy-ai`（2026-10-10 修）──
#
# 🔴 根因：`platform` 是登录页判断「**登录后把控制权交还给谁**」的唯一开关，不是
#    渠道标识。官方 web 登录页（`LoginSuccess-*.js`）登录成功后按 platform 做一次
#    **深链跳转**：
#      {ide:'codebuddy://getStarted', workbuddy:'workbuddy://',
#       workbuddy-ai:'workbuddy-ai://', learnbuddy:'learnbuddy://'}，缺省 'vscode://'
#    而 `/login/started` 的判定是 `!l && !f && (window.location.href = S)`，其中
#      `l = (platform === 'cli')`  ← **唯一**被短路（不深链）的平台。
#    本机实测 `/Applications/WorkBuddy AI.app` 的 Info.plist 注册的正是
#    `workbuddy-ai` 协议 ⇒ 用 `workbuddy-ai` 登录后浏览器会把控制权交给本地 App
#    （用户报障「不是回调到网关，是直接打开本地程序」）。
#
# 🔴 为什么照抄 DSH 的 `workbuddy-ai` 是错的：`workbuddy-ai` 是**桌面客户端**
#    （`/Applications/WorkBuddy AI.app/.../cli/product.json` 的
#    `applicationName` / `authentication.attributes.platform`）自己的平台值。
#    网关与 DSH 插件都不是那个桌面客户端 —— DSH 之所以"看起来没弹本地 App"，
#    是因为它把登录页开在**宿主受控窗口**（Electron 窗口默认不把未知协议交给
#    系统 shell）里把那一跳吞掉了，**不是**它的登录逻辑做了处理
#    （`jet-hub.js:2355` 就是一句 `window.open`，与网关逐字同形）。
#    网关用系统浏览器弹窗，没有宿主可吞 ⇒ 必须改用语义相符的平台值。
#    `cli` 是官方为「**没有可交还的客户端**」准备的分支：换 token 的
#    `/console/auth/login` 照常执行（登录照常完成、轮询照常取到凭据），
#    只是不再深链，页面上显示「返回 CLI 继续使用」。
#
# 🔴 已验证（2026-10-10 实机）：
#    · `POST /v2/plugin/auth/state?platform=cli` 返回 `code:0` 与正常 authUrl；
#    · 无头 Chrome 渲染 `?platform=cli` → 与 `?platform=workbuddy-ai` **同一套
#      国际版登录页**（`login-iframe` 承载 OIDC，DOM 结构一致）⇒ 登录交互不变；
#    · `profile.platform` 全仓**只**用于 `auth/state` 查询串
#      （`buddy/hooks.py::start_login`），不影响 UA / X-Product-Code / 出站链路。
# ⚠️ 未端到端验证：完整登录（需真实 WorkBuddy 国际版账号在浏览器完成授权）
#    —— 换 token 仍走同一条 `/console/auth/login`，待真机复核。
# 🟡 同型待办：buddy（CodeBuddy）的 `platform="ide"` 同样会深链
#    `codebuddy://getStarted`；本机**没有** App 注册 `codebuddy`（CodeBuddy CN
#    注册的是 `codebuddycn`）⇒ 当前静默失败、无感。换过 platform 会动到已在跑的
#    中国版账号归因，本轮不动，单独报备。


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
