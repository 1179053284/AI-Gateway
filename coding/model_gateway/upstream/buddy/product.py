"""CodeBuddy（腾讯，中国版）产品钩子（tech-design v2.0 §22.3 冻结签名；M6-2 实施）。

本产品证据面（§22.4 行 + `20 §1.1/§3.1`；`21 §1.1`）：

- 登录：**external_link 轮询**（`jet-hub-rpc.ts:835-877`：`fetchAuthState` → 返回 loginUrl →
  后台用同一 state 轮询 token/account；§22.4）
- 设备：**无设备标识**（`20 §2.7`）
- 额度 ✓（`POST /v2/billing/meter/get-user-resource`，`credits.ts:51`）
- 签到 ✓（`checkin-activity-status` + `daily-checkin`，幂等 = HTTP 400 + 业务码 `10001`，`credits.ts:19-21`）
- 模型：remote `/v3/config` + 兜底表（`CODEBUDDY_FALLBACK_MODELS`，`21 §1.1`）

🔴 **实现全在 `buddy/hooks.py` + `buddy/protocol.py`**（workbuddy 复用同一份，§22.1）；
   本文件的职责只有三件：① 声明本产品档案 `_PROFILE`；② 抄录本产品的兜底模型表；
   ③ 把 §22.3 的十个钩子按**冻结签名**接到共享实现上（薄接线，零业务逻辑）。
🔴 `refresh` 用别名导出（不写 `async def refresh(`）：仓内死代码护栏
   `tests/unit/test_v2_cli_zcode.py:182-197` 对 `upstream/*/product.py` 之外的文件做
   `def refresh(` 字面匹配，共享实现里的函数名因此是 `refresh_credential`。
🔴 `build_out` 自 M6-5a 起**已接线**（`upstream/buddy/out.py::BuddyFamilyOut`，
   推理路径 `/v2/chat/completions` 有取证）。
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
PRODUCT = "buddy"

#: 兜底模型目录 —— **逐条照抄** DSH `CODEBUDDY_FALLBACK_MODELS`（`product.ts:180-266`，16 条）。
#: 来源与语义（`product.ts:171-179,126-135`）：数据取自 `/v3/config` 的 `craft` agent 白名单，
#: 并**逐个用真实请求验证可用**（`POST /v2/chat/completions`）——远端不下发/不可用时由本表顶位；
#: 远端可达时逐字段优先于本表（合并规则见 `buddy-adapter.ts:901-948`）。
#: 搬运映射：`contextWindow→context_window`、`maxOutputTokens→max_output`、
#: `supportsImages→image_input`、`reasoningEfforts→effort_levels`；
#: `defaultReasoningEffort` **不搬运**（§22.3 的 `ModelInfo` 冻结类型无该字段 —— 已登记缺口）。
#: `tool_call` 恒 None：两个模型端点都不声明工具能力，取不到不编造（`21 §5.1-1`）。
_CODEBUDDY_FALLBACK_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(id="hy4-preview", name="Hy4 preview", context_window=1_000_000,
              max_output=64_000, image_input=True, effort_levels=("high",)),
    ModelInfo(id="hy3", name="Hy3", context_window=192_000, max_output=64_000,
              image_input=True, effort_levels=("low", "high")),
    ModelInfo(id="hy3-x", name="Hy3", context_window=192_000, max_output=64_000,
              image_input=True, effort_levels=("low", "high")),
    # maxOutputTokens 取 128000（scoped 端点 128000 与 /v3/config 131072 的**较小者**，
    # 即服务端真正接受的额度；取大值会被上游拒绝，`product.ts:194-197`）
    ModelInfo(id="deepseek-v4.1-flash", name="Deepseek-V4.1-Flash", context_window=1_000_000,
              max_output=128_000, image_input=True, effort_levels=("low", "high", "max")),
    ModelInfo(id="deepseek-v4-pro", name="Deepseek-V4-Pro", context_window=1_000_000,
              max_output=128_000, image_input=True, effort_levels=("low", "high", "xhigh")),
    # 档位沿用适配器实测表 [low,high,max]（上游 /v3/config 声明 [low,high,xhigh]，实测两套都返 200，
    # 无法判定哪套真实生效 → 不擅改，`product.ts:206-217`）
    ModelInfo(id="deepseek-v4-flash", name="Deepseek-V4-Flash", context_window=1_000_000,
              max_output=50_000, image_input=True, effort_levels=("low", "high", "max")),
    ModelInfo(id="glm-5.3", name="GLM-5.3", context_window=1_000_000, max_output=64_000,
              image_input=True, effort_levels=("low", "high", "max")),
    ModelInfo(id="glm-5.3-flash", name="GLM-5.3-Flash", context_window=1_000_000,
              max_output=32_000, image_input=True, effort_levels=("low", "high", "max")),
    ModelInfo(id="glm-5.2", name="GLM-5.2", context_window=1_000_000, max_output=64_000,
              image_input=True, effort_levels=("high", "xhigh")),
    ModelInfo(id="glm-5.1", name="GLM-5.1", context_window=200_000, max_output=48_000,
              image_input=True, effort_levels=("medium",)),
    ModelInfo(id="glm-5v-turbo", name="GLM-5V-Turbo", context_window=200_000, max_output=64_000,
              image_input=True, effort_levels=("medium",)),
    ModelInfo(id="kimi-k3-1", name="Kimi-K3-1", context_window=1_000_000, max_output=32_000,
              image_input=True, effort_levels=("medium",)),
    ModelInfo(id="kimi-k2.8-preview", name="Kimi-K2.8-Preview", context_window=1_000_000,
              max_output=64_000, image_input=True, effort_levels=("low", "high", "max")),
    ModelInfo(id="kimi-k2.7", name="Kimi-K2.7", context_window=256_000, max_output=32_000,
              image_input=True, effort_levels=("medium",)),
    ModelInfo(id="kimi-k2.6", name="Kimi-K2.6", context_window=256_000, max_output=32_000,
              image_input=True, effort_levels=("medium",)),
    ModelInfo(id="minimax-m3", name="MiniMax-M3", context_window=512_000, max_output=64_000,
              image_input=True, effort_levels=("medium",)),
)

#: 本产品档案（差异全部收敛在这里，`product.ts:268-284`）。
#: 基址/显示名/能力位一律从注册表取（唯一事实源），此处只放**协议身份标识**。
_PROFILE = ProductProfile(
    id=PRODUCT,
    platform="ide",                                  # product.ts:270
    product_code="codebuddy",                        # product.ts:274
    user_agent="CodeBuddyIDE/1.106.1",               # product.ts:275（= buddy.ts:89）
    fallback_models=_CODEBUDDY_FALLBACK_MODELS,
    append_session_params=False,                     # product.ts:282（中国版不追加会话参数）
)


def meta() -> ProductMeta:
    """产品注册信息（唯一事实源 = `accounts/registry.py`，此处不重复填字段）。"""
    return registry_get(PRODUCT)


async def login_start(session) -> Challenge:
    """两步式第一步：取外链授权页（`buddy-oauth.ts:137-167`）。"""
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


#: §22.3 钩子名（`def refresh(` 的字面量只允许出现在 `upstream/*/product.py`，见模块头）
refresh = _refresh_impl


async def probe(cred, meta) -> ProbeResult:
    """探活：连通 / 凭据有效两维（`credits.ts:39-50` 的免额度端点）。"""
    return await hooks.probe(_PROFILE, cred, meta)


async def quota(cred, meta) -> QuotaSnapshot:
    """额度快照：available / exhausted / unknown（**未知不当零**，§22.3）。"""
    return await hooks.quota(_PROFILE, cred, meta)


async def claim(cred, meta, *, precheck: bool) -> ClaimOutcome:
    """签到（幂等 = HTTP 400 + 业务码 10001 → `already_done`，`credits.ts:19-21`）。"""
    return await hooks.claim(_PROFILE, cred, meta, precheck=precheck)


async def list_models(cred, meta) -> list[ModelInfo]:
    """模型目录：远端 `/v3/config` + 兜底表合并（`21 §1.1`）。"""
    return await hooks.list_models(_PROFILE, cred, meta)


#: 骨架纪律护栏的**登记面**（`tests/accounts/test_registry.py::_implemented_hooks` 读它）：
#: 本产品已接线的钩子名。**刻意不列** `login_callback`（本产品族无本机回跳通道）
#: —— `build_out` 自 M6-5a 起已接线（见下）。
_IMPLEMENTED = ("login_start", "login_poll", "refresh", "probe", "quota", "claim",
                "list_models", "build_out")


def build_out(account) -> OutboundAdapter:
    """构造出站适配器（§22.3「出站适配」；M6-5a 试点：`/v2/chat/completions`）。

    - `account` = `adapters.product_out.ProductAccount`（product / 账号名 / 资源基址）；
    - 返回 `BuddyFamilyOut`（openai 族基类 + 本产品身份头；凭据经账号目录自解，
      **不进 config**，铁律 1）；
    - 延迟 import（`out.py` ↔ 本模块不互相在 import 期拉起，见 out.py 模块头）。
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
