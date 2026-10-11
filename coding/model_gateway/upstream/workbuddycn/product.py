"""WorkBuddy（中国版）产品钩子（tech-design v2.11 §22.3 冻结签名；Q44 实施）。

本产品证据面（§22.4 行 + 方案 `docs/changes/plans/20261011-workbuddycn-integration-plan.md`）：

- 登录：**同 buddy / workbuddy**（同族，`cli-external-link` 两步外链轮询；
  中国版 `cli/product.json` 的 `authentication.type` 一手取证）
- 设备：**无设备标识**（`product.json` 无设备字段；签到实测不带设备头成功）
- 额度 ✓（`get-user-resource` 2026-10-10 实调 code=0，31 包）
- 签到 **✓**（`checkin-activity-status` 2026-10-10 实调 `active=true`，**与国际版相反**；
  桌面端 `productFeatures.DisableCheckin=false`）→ 能力位 `checkin=True`
- 模型：remote `/v3/config`（中国版域名）+ 中国版兜底表（本文件 `_WORKBUDDYCN_FALLBACK_MODELS`）

🔴 与 buddy **共享全部实现**（`buddy/hooks.py` + `buddy/protocol.py`，§22.1）；
   本文件只声明差异：platform / X-Product-Code / UA / 登录 URL 附加参数 / 兜底表
   —— 差异**全部是参数**，没有第二份复制实现。
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
PRODUCT = "workbuddycn"

#: 兜底模型目录 —— 来源 = 中国版域名 `GET /v3/config` 的 `cli` agent 白名单
#: **剔除服务端别名 `auto` 后的 16 条**（2026-10-11 实测，逐条元数据同轮实读；
#: 方案 §4.5 / 待裁决点 D2 已用户拍板「不收 `auto`」——`protocol.is_auto_select_alias`
#: 把 `auto`/`default` 定为「服务端自行挑后端的内部别名，不是真实模型」，且远端解析恒把
#: 别名挡在目录外，兜底表收录它就成了别名进网关目录的唯一入口）。
#: **顺序即 IDE 展示顺序**（`cli` agent 白名单序），不得重排。`maxInputTokens`/
#: `maxOutputTokens`/`supportsImages`/`supportedEfforts` 全部来自 2026-10-11 对
#: `www.workbuddy.cn/v3/config` 的实测（⚠️ 2026-10-10 首测与本表 9 个模型的输入窗口不一致，
#: 以 10-11 复测为准，漂移处置见方案 §7-R8）。计费字段（`free`/`rate`）**不填**：
#: 兜底表不含计费（`merge_models` 口径），由远端 `/v3/config` 逐条覆盖。
_WORKBUDDYCN_FALLBACK_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(id="hy4-preview", name="Hy4 preview", context_window=960_000,
              max_output=64_000, image_input=True, effort_levels=("high",)),
    ModelInfo(id="hy3", name="Hy3", context_window=192_000, max_output=64_000,
              image_input=True, effort_levels=("low", "high")),
    ModelInfo(id="hy3-x", name="Hy3", context_window=192_000, max_output=64_000,
              image_input=True, effort_levels=("low", "high")),
    ModelInfo(id="space-bunny", name="Space-Bunny", context_window=1_000_000,
              max_output=128_000, image_input=True,
              effort_levels=("low", "medium", "high", "xhigh", "max")),
    ModelInfo(id="deepseek-v4.1-flash", name="Deepseek-V4.1-Flash", context_window=1_000_000,
              max_output=128_000, image_input=True, effort_levels=("low", "high", "max")),
    ModelInfo(id="glm-5.3", name="GLM-5.3", context_window=1_000_000, max_output=64_000,
              image_input=True, effort_levels=("low", "high", "max")),
    ModelInfo(id="glm-5.3-flash", name="GLM-5.3-Flash", context_window=1_000_000,
              max_output=131_072, image_input=True, effort_levels=("low", "high", "max")),
    ModelInfo(id="glm-5.2", name="GLM-5.2", context_window=1_000_000, max_output=64_000,
              image_input=True, effort_levels=("high", "xhigh")),
    ModelInfo(id="glm-5.1", name="GLM-5.1", context_window=200_000, max_output=48_000,
              image_input=True),
    ModelInfo(id="glm-5v-turbo", name="GLM-5v-Turbo", context_window=200_000, max_output=64_000,
              image_input=True),
    ModelInfo(id="minimax-m3", name="MiniMax-M3", context_window=512_000, max_output=64_000,
              image_input=True),
    ModelInfo(id="kimi-k3-1", name="Kimi-K3", context_window=1_000_000, max_output=32_000,
              image_input=True, effort_levels=("low", "high", "xhigh")),
    ModelInfo(id="kimi-k2.8-preview", name="Kimi-K2.8-Preview", context_window=1_000_000,
              max_output=64_000, image_input=True, effort_levels=("low", "high", "max")),
    ModelInfo(id="kimi-k2.7", name="Kimi-K2.7-Code", context_window=256_000, max_output=32_000,
              image_input=True),
    ModelInfo(id="kimi-k2.6", name="Kimi-K2.6", context_window=256_000, max_output=32_000,
              image_input=True),
    ModelInfo(id="deepseek-v4-pro", name="Deepseek-V4-Pro", context_window=1_000_000,
              max_output=128_000, image_input=True, effort_levels=("high", "xhigh")),
)

#: 本产品档案（差异全部收敛在这里；取证 = 本机 `/Applications/WorkBuddy.app` v5.6.2
#: `Contents/Resources/app.asar.unpacked/cli/product.json` + `app.asar`，2026-10-11 复验）。
#: ⚠️ UA 取中国版形态 `WorkBuddy/5.5.2 WorkBuddy/5.5.2 CLI/5.5.2`（DSH `product.ts:71`
#: `WORKBUDDY_UA_CN`；与在册国际版的 `WorkBuddy AI/5.5.2` 中段不同——腾讯后台按出站 UA
#: 归因「使用端」，用错产品线 UA 账单会显示为 `-`，`product.ts:93-99`）。
#: ⚠️ `append_session_params=True`：登录 URL 追加 `version` 与 `loginSessionId`
#: （判据 = 同族对齐 + 两参数无校验语义 + CN 登录页接受，`decorate_login_url`
#: 与 platform 取值无关；方案 §2.2/§4.3）。
#: ⚠️ `system_first_text` 缺省空 = **不注入**：中国版通道对首条非 system 的请求直接 200
#: （2026-10-10 实测，方案 §3.4；与国际版的 11128 脾气相反）——不给没这条限制的通道
#: 凭空注入（`buddy/out.py::_with_system_first` 对空文本原样返回）。
_PROFILE = ProductProfile(
    id=PRODUCT,
    platform="cli",                                       # 🔴 不是客户端声明的 "workbuddy"，见下
    product_code="workbuddy",                             # app.asar `X-Product-Code` 一手
    user_agent="WorkBuddy/5.5.2 WorkBuddy/5.5.2 CLI/5.5.2",  # = DSH WORKBUDDY_UA_CN（product.ts:71）
    fallback_models=_WORKBUDDYCN_FALLBACK_MODELS,
    append_session_params=True,
    plugin_version="5.5.2",
    # system_first_text 留空（缺省）：中国版无「首条须 system」限制（见上注）
)

# ── 登录 platform 为什么是 `cli` 而不是客户端声明的 `workbuddy`（Q44 定版）──
#
# 与 `upstream/workbuddy/product.py` 的 2026-10-10 修复**同根因同口径**（全文见该文件
# 同名注释块）：`platform` 是登录页判断「登录后把控制权交还给谁」的唯一开关——
# `{ide:'codebuddy://getStarted', workbuddy:'workbuddy://', workbuddy-ai:'workbuddy-ai://'…}`，
# 唯一被短路（不深链）的平台是 `cli`。本机 `/Applications/WorkBuddy.app` 的 `Info.plist`
# 注册的正是 `workbuddy` 协议（2026-10-11 实读 `CFBundleURLSchemes`）⇒ 照抄客户端声明值
# 会让浏览器在登录完成后唤起本机 App 而不是回到网关（国际版 `workbuddy-ai://` 同形问题的
# 用户报障先例）。`cli` 是官方为「没有可交还的客户端」准备的分支：登录照常完成、轮询照常
# 取到凭据，只是不深链。
#
# 已验证：`POST www.workbuddy.cn/v2/plugin/auth/state?platform=cli` → `code:0` +
# `authUrl: …/login?platform=cli&state=…`（2026-10-11 实测；`platform=workbuddy` 同样 200，
# 差别只在登录完成后的深链行为）。⚠️ 未端到端验证：完整登录（需真实中国版账号在浏览器
# 完成授权）——待真机复核（方案 §7-R1/R5）。


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
    """探活：连通 / 凭据有效两维（额度端点全族通用，`credits.ts:39-50`）。"""
    return await hooks.probe(_PROFILE, cred, meta)


async def quota(cred, meta) -> QuotaSnapshot:
    """额度快照（与 buddy 同端点，仅 baseURL 不同；中国版实测 31 包，方案 §3.3）。"""
    return await hooks.quota(_PROFILE, cred, meta)


async def claim(cred, meta, *, precheck: bool) -> ClaimOutcome:
    """签到：中国版**有签到端点**（能力位 checkin=True，与国际版相反）→ 真实签到腿。

    实际分支在 `buddy/hooks.py::claim`（能力位判据，§22.6）；本函数只做签名接线。
    """
    return await hooks.claim(_PROFILE, cred, meta, precheck=precheck)


async def list_models(cred, meta) -> list[ModelInfo]:
    """模型目录：远端 `/v3/config`（中国版域名）+ 中国版兜底表合并（方案 §3.2/§4.5）。"""
    return await hooks.list_models(_PROFILE, cred, meta)


#: 骨架纪律护栏的**登记面**（`tests/accounts/test_registry.py::_implemented_hooks` 读它）：
#: 本产品已接线的钩子名（`claim` 在内：checkin=True 走真实签到腿，**是已接线行为**）。
#: **刻意不列** `login_callback`（无本机回跳通道）—— `build_out` 自 M6-5a 起已接线。
_IMPLEMENTED = ("login_start", "login_poll", "refresh", "probe", "quota", "claim",
                "list_models", "build_out")


def build_out(account) -> OutboundAdapter:
    """构造出站适配器（§22.3「出站适配」）。

    与 buddy / workbuddy **共用同一实现**（`upstream/buddy/out.py::BuddyFamilyOut`）——
    中国版差异全在 `_PROFILE`（UA / 基址），没有第二份出站代码。
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
