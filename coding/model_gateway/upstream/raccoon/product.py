"""Raccoon（商汤小浣熊）产品钩子（tech-design v2.0 §22.3 冻结签名；**M6-3 实现**）。

本产品证据面（§22.4 行 + `20 §2.7/§3.1/§4.1`；`21 §1.1`）：

- 登录：**扫码 / 短信**（主形态 `qr`，`login_alt=("sms_code",)`；页面承载方式见 `login.py` 模块头）
- 设备：`device_id?`（**可选**；DSH 自身从不生成、只透传 → 本实现**留空**并从请求头省略，
  见下方「设备语义」）
- 额度 ✓ = `GET /api/web/points/v1/balance`（只读，三个池分开）
- 签到 **✗** —— 每日 300 分**服务端按日自动发放**（账单 `biz_type: 'daily_grant'`），
  **没有可调用的签到端点** → 能力位 `checkin=False`，`claim` 返回 `inactive` 可读原因
  （做成按钮必然失败；`raccoon-credits.ts:12-18`、`credits-capabilities.js:117-121`、`20 §3.1`）
- **登录奖励 ✓** = `POST /api/web/desktop/v1/login/points/grant`（3000 分，**一次性幂等**，
  判据 = 响应体 `granted`；⚠️ **必需 `X-Client-Platform` 头**）→ `claim_onboarding`
- 模型：remote `GET /api/web/llm/v2/model_catalog`（过滤 `visible:false`）+ 6 条兜底表
  （兜底表逐条照抄 `raccoon-product.ts:218-263`）
- 协议：**标准 OpenAI 兼容 + 标准 SSE**（`raccoon-adapter.ts:6`）→ M6-5 出站适配

**实现面分工（本目录四文件；薄接线是本文件的全部职责）**：

| 文件 | 职责 |
|---|---|
| `const.py` | 端点 / 请求头取值 / 超时 / 兜底模型表（逐条 `file:line`） |
| `protocol.py` | 纯函数：信封、凭据归一、JWT 过期、请求头、展示名、手机号加密 |
| `login.py` | 扫码两步 + 短信两步 + 登录后补全（IO） |
| `models.py` / `credits.py` | 目录（IO）／积分面（IO，只读优先） |

**设备语义（`device_id?` 留空的依据，不是遗漏）**：`raccoon.ts:104-105,289-291` 只在凭据里
**确实有** `device_id` 时才发 `X-Client-Device-ID`；DSH 自己的登录链路从不生成它
（`raccoon-oauth.ts` 全链路无该字段，只透传导入的凭据）→ 按其语义**留空**。
`registry` 的 `DeviceSpec(fields=("device_id",), derive=False)` 是「该产品可能需要这个字段」的
登记（`20 §2.7`、`20 §4.1` 的 U6 待实测：字段语义与是否每账号互异尚未验证）——
**不编造一个自造设备号**（自造 = 替上游决定设备身份，风险高于收益）。

🔴 `build_out` **自 M6-5b 起已接线**（`upstream/raccoon/out.py::RaccoonOut`：标准 OpenAI 体、
chat 四头集 + `extra_body.thinking` 方言翻译，逐条取证见该文件模块头）。
🔴 `login_callback` **显式失败**：本产品是「扫码 / 短信」型，不存在本机回跳通道
   （`login` 的 `ProductMeta.login` 只渲染二维码向导；DSH 也绕开了官方的自定义协议回调）。
"""

from __future__ import annotations

import logging

import httpx

from model_gateway.accounts import net
from model_gateway.accounts.registry import get as registry_get
from model_gateway.accounts.types import (
    Challenge,
    ClaimOutcome,
    LoginOutcome,
    ModelInfo,
    NotRefreshable,
    ProbeResult,
    ProductMeta,
    QuotaSnapshot,
)
from model_gateway.upstream.raccoon import const as C
from model_gateway.upstream.raccoon import credits, login, models
from model_gateway.upstream.raccoon import protocol as p

logger = logging.getLogger("model_gateway.upstream.raccoon")

#: 本产品标识（§22.4；与 `accounts/registry.py` 的键、账号目录名一致）
PRODUCT = "raccoon"

#: **已接线**钩子名（M6-3；`build_out` 自 M6-5b 起进表）。⚠️ 私有约定，只为
#: `tests/accounts/test_registry.py` 的「M6-1 骨架纪律」护栏**收窄作用面**：
#: `login_callback`（本产品无回跳通道）仍必须显式 `NotImplementedError`。
_IMPLEMENTED = frozenset({
    "login_start", "login_poll", "refresh", "probe", "quota", "claim",
    "claim_onboarding", "list_models", "build_out",
})


def meta() -> ProductMeta:
    """产品注册信息（唯一事实源 = `accounts/registry.py`，此处不重复填字段）。"""
    return registry_get(PRODUCT)


# ==================== 登录（扫码主形态；短信见 sms_send / sms_submit）====================


async def login_start(session) -> Challenge:
    """扫码登录第一步：本地生成 `qrcode_code` → 内容进 `Challenge.url` +
    **服务端出的 PNG data URI** 进 `Challenge.qr_payload`（`login.py:start` / `accounts/qr.py`）。
    """
    return await login.start(session)


async def login_poll(session) -> LoginOutcome:
    """扫码登录第二步：轮询 `login_with_qrcode_code`（`login.py:poll_qr`）。

    🔴 `pending` 是**正常业务状态**（`pending`/`logging`/未知状态都归它），不是错误（§22.3）。
    """
    return await login.poll_qr(session)


async def login_callback(session, params) -> LoginOutcome:
    """回跳粘贴（仅 local_callback 型产品，§22.3）。

    🔴 本产品是 **qr / sms_code 型**（`20 §4.1`：本地页承载微信扫码 / 短信）→ 入口层按
    `ProductMeta.login` 只渲染二维码（+短信 Tab）向导，本钩子**预期永不被调用**；
    保持显式失败，不写一个"看起来能用"的假实现。
    """
    raise NotImplementedError(
        "raccoon.login_callback：本产品非 local_callback 型（扫码 / 短信，20 §4.1）")


async def sms_send(session, *, phone: str, captcha_param: str = "") -> Challenge:
    """**备选形态（sms_code）第一步**：下发短信验证码（`login.py:send_sms`）。

    ⚠️ 本函数**不在 §22.3 的十钩子内**（`LoginKind` 的 `sms_code` 备选通道）：DSH 同样把它
    放在独立的 `login.sendSms` RPC 里（`jet-hub-rpc.ts:1363-1401`），而不是主登录通道
    —— 入口层按 `ProductMeta.login_alt` 渲染短信 Tab 后调用（UI 接线属 M6-4）。
    失败（含图形验证码未过）→ 抛 `RuntimeError`（可读原因回给向导，用户可重试）。
    """
    return await login.send_sms(session, phone=phone, captcha_param=captcha_param)


async def sms_submit(session, *, sms_code: str) -> LoginOutcome:
    """**备选形态第二步**：提交短信验证码完成登录（`login.py:submit_sms`）。

    与 DSH 的 `login.submitSms`（`jet-hub-rpc.ts:1408-1436`）同构：手机号取自上一步的会话态，
    未先发码 → `failed`「请先获取手机验证码」。同样不在 §22.3 十钩子内。
    """
    return await login.submit_sms(session, sms_code=sms_code)


# ==================== 续期（`raccoon-oauth.ts:281-319`）====================


async def refresh(cred, meta) -> dict:
    """凭据续期：`POST /api/web/auth/v1/refresh`（`refresh_token` 轮换）→ **新的**凭据本体。

    ```
    body: {"refresh_token": <refresh_token>}
    → data: {access_token, refresh_token?}
    ```

    终态判定（`raccoon-oauth.ts:289-319`）：

    - 无 `refresh_token` → `NotRefreshable`（**不是故障**、不触发冷却，§22.3）；
    - HTTP **401** 或业务码 **`200003`** → `NotRefreshable`（登录态过期，需重新登录）；
    - 其余非零业务码 → `RuntimeError`（**可重试**，交给调用方按退避策略重试）；
    - 200 却缺 `access_token` → `RuntimeError`（**不写回空令牌**——那会把好凭据覆盖成死值）。

    返回值只承载**新凭据**；落盘唯一入口是 `store.commit_login`（§22.2 不变式⑤）。
    """
    del meta  # 形参按 §22.3 保留：本产品无设备身份读写、无私有文件
    credential = dict(cred or {})
    if not p.is_refreshable(credential):
        raise NotRefreshable("凭据无 refresh_token（Raccoon 续期必需），请重新登录")
    try:
        async with net.make_client(base_url=C.API_BASE, timeout=C.REQUEST_TIMEOUT_S) as client:
            resp = await client.post(C.REFRESH_PATH, json={
                "refresh_token": p.read_str(credential, "refresh_token").strip()})
            payload = _json_or_none(resp)
    except httpx.HTTPError as e:
        raise RuntimeError(f"Raccoon 续期网络错误（可重试）：{e}") from e
    envelope = p.parse_envelope(payload, resp.status_code)
    if resp.status_code == 401 or envelope.code == C.CODE_SESSION_EXPIRED:
        raise NotRefreshable(
            f"Raccoon 登录态已过期（refresh_token 失效，HTTP {resp.status_code}"
            f"／业务码 {envelope.code}），请重新登录")
    if not envelope.ok:
        raise RuntimeError(f"Raccoon 续期失败（HTTP {resp.status_code}）："
                           f"{envelope.error_text('服务端未给原因')}")
    if not p.read_str(envelope.data, "access_token"):
        raise RuntimeError("Raccoon 续期响应缺少 access_token（不写回空令牌）")
    return p.apply_refresh(credential, envelope.data)


# ==================== 探活（§22.3「连通 / 凭据有效」两维）====================


async def probe(cred, meta) -> ProbeResult:
    """探活：连通（拿到了 HTTP 响应）+ 凭据有效（上游认可该凭据）**两维分开**。

    判据端点 = `GET /api/web/auth/v1/user_info`（**只读**；`raccoon-oauth.ts:330-359`，
    DSH 用它做登录后补全 → 天然是"凭据可用性"的最小代价通道）。
    ⚠️ DSH 自身对 raccoon **未接线**独立探活（`account.retest` 走适配器真实请求）；本层用该
    只读端点做**凭据级**判定，避免为探活烧额度（同 buddy/cline 的取舍）。
    """
    del meta  # 形参按 §22.3 保留（同 refresh 的说明）
    if not p.access_token_of(cred):
        return ProbeResult(reachable=False, valid=False,
                           detail="凭据缺少 access_token（未登录，未发请求）")
    try:
        async with net.make_client(base_url=C.API_BASE, timeout=C.REQUEST_TIMEOUT_S) as client:
            resp = await client.get(C.USER_INFO_PATH, headers=p.headers(cred))
            payload = _json_or_none(resp)
    except httpx.HTTPError as e:
        return ProbeResult(reachable=False, valid=False, detail=f"上游不可达：{e}")
    if resp.status_code in (401, 403):
        return ProbeResult(reachable=True, valid=False,
                           detail=f"凭据已失效（HTTP {resp.status_code}），请重新登录")
    if payload is None:
        # 200 但非 JSON：网关异常时会回 HTML 页面 —— **不得**当成「凭据有效」
        return ProbeResult(reachable=True, valid=False,
                           detail="响应不是 JSON（凭据失效时网关会回 HTML 错误页）")
    envelope = p.parse_envelope(payload, resp.status_code)
    if envelope.code == C.CODE_SESSION_EXPIRED:
        return ProbeResult(reachable=True, valid=False,
                           detail=f"凭据已失效（业务码 {envelope.code}），请重新登录")
    if resp.status_code == 200 and envelope.ok:
        return ProbeResult(reachable=True, valid=True, detail="凭据有效")
    return ProbeResult(reachable=True, valid=False,
                       detail=f"凭据有效性未确认（HTTP {resp.status_code}／业务码 {envelope.code}）")


# ==================== 额度（`raccoon-credits.ts:129-163`）====================


async def quota(cred, meta) -> QuotaSnapshot:
    """余额快照（**只读**端点，三态 available/exhausted/unknown；**未知不当零**）。"""
    del meta  # 形参按 §22.3 保留（同 refresh 的说明）
    return await credits.quota(cred)


# ==================== 签到（本产品无此能力）/ 登录奖励（onboarding）====================


async def claim(cred, meta, *, precheck: bool) -> ClaimOutcome:
    """签到/领取 —— **本产品无签到端点**（`Capabilities.checkin=False`；`20 §3.1`）。

    🔴 依据（三条独立证据）：① 账单里每日 300 分的 `biz_type` 是 `daily_grant`（服务端按日
    **自动发放**，实测注册后 1 分钟即到账）；② 客户端能力矩阵把 raccoon 登记为
    `{balance:true, onboardingTasks:true}`、**没有** `dailyCheckin`（`credits-capabilities.js`）；
    ③ 于是"做成按钮必然失败"。
    故这里返回 `inactive`（**正常业务状态**，不是 failed）+ 可读原因，而不是打一个必然失败的
    上游请求 —— 照抄 DSH 的工程习惯：对 cline/raccoon/workbuddy 三个「没有签到端点」的产品回
    **可读的业务性错误**，而非泛化的 `unsupported provider`（后者会让排查者以为是"provider
    没注册"，而真相是"该产品无此能力"，`jet-hub-rpc.ts:1857-1888`）。
    这也是「能力矩阵是判据不是标签」（§22.6）在服务端的落点：入口层按 `Capabilities`
    不渲染签到按钮，本钩子只是**最后一道**不谎报的防线。
    """
    del cred, meta, precheck
    if registry_get(PRODUCT).capabilities.checkin:
        # 护栏：注册表若哪天翻成 True，本实现必须同步换成真实端点（否则会静默谎报 inactive）
        raise NotImplementedError(
            "raccoon.claim：注册表 capability.checkin=True，但尚无已取证的签到端点实现")
    return ClaimOutcome(
        category="inactive",
        detail="Raccoon 无每日签到端点：每日 300 分由服务端按日自动发放（20 §3.1）；"
               "一次性登录奖励请走 claim_onboarding")


async def claim_onboarding(cred, meta, *, precheck: bool) -> ClaimOutcome:
    """**一次性登录奖励**（3000 分，每号一次）：`POST /api/web/desktop/v1/login/points/grant`。

    🔴 **必需 `X-Client-Platform` 头**（发送点 `raccoon-credits.ts:87-90`、要求 `:171-173`；
    取值按宿主平台解析，`raccoon-product.ts:175-183`）——猜错会被拒。
    🔴 **判据 = 响应体 `granted`**（重复领取同样 HTTP 200 + `granted:false`，`:197-200`）
    → `granted !== true` 映射为 `already_done`（不是 failed，也不是 success：后者会让用户
    以为每天都真的加了额度）。
    🔴 `precheck=True` → 先**只读**反查账单确认是否已领（`raccoon-credits.ts:228-258`）；
    反查查不到（`None`）时**仍然尝试领取** —— 服务端幂等，宁可让用户多点一次，也不要误报
    「已领」让他真的错过（`:225-226`）。

    ⚠️ 本钩子**不在 `_HOOKS` 表**：§22.3 把它列为**可选**钩子（`capability=onboarding` 的产品
    才实现，`loomy`/`raccoon`；`_HOOKS` 是十钩子的冻结契约，见 `tests/accounts/test_registry.py`）→
    入口层按 `Capabilities.onboarding` 判断后经模块级本函数调用（UI 接线属 M6-4）。
    """
    del meta
    if not registry_get(PRODUCT).capabilities.onboarding:
        return ClaimOutcome(category="inactive",
                            detail="Raccoon 未登记一次性登录奖励能力（§22.6）")
    if not p.access_token_of(cred):
        # 凭据类：未发请求 → 不重试（`retryable=False` 缺省）
        return ClaimOutcome(category="failed", detail="凭据缺少 access_token（未登录，未发请求）")
    if precheck:
        status = await credits.onboarding_status(cred)
        if status is not None and status.claimed:
            return ClaimOutcome(
                category="already_done",
                detail=f"该账号已领取过桌面端登录奖励（每号一次；账单反查 {status.points} 积分）")
        if status is None:
            logger.info("[raccoon] 登录奖励状态反查不可用 → 仍然尝试领取（服务端幂等）")
    return await credits.grant_login_reward(cred)


# ==================== 模型目录（远端 + 兜底表；§22.5-4）====================


async def list_models(cred, meta) -> list[ModelInfo]:
    """产品模型目录：远端 `model_catalog` 优先，失败/为空回退 6 条兜底表（`models.list_models`）。"""
    del meta  # 形参按 §22.3 保留（同 refresh 的说明）
    return await models.list_models(cred)


# ==================== 出站适配（M6-5）====================


def build_out(account) -> OutboundAdapter:
    """构造出站适配器（§22.3「出站适配」；M6-5b 接线）。

    - `account` = `adapters.product_out.ProductAccount`（product / 账号名 / 资源基址）；
    - 返回 `RaccoonOut`（openai 族基类；端点 = `{base_url}/chat/completions`，
      基址已含 `/api/web/llm/v2`，合起来即 `raccoon-adapter.ts:427` 的取证路径）；
    - 头集与体方言（`extra_body.thinking`）见 `out.py` 模块头，逐条附实测取证；
    - 延迟 import（`out.py` ↔ 本模块不互相在 import 期拉起，见 `product_out.py` 模块头 ⚠️）。
    """
    from model_gateway.upstream.raccoon.out import RaccoonOut
    return RaccoonOut(account)


# ==================== 内部工具 ====================


# R2a-F-5（2026-10-06）：实现收编到 `upstream/_text.py`（一份实现，6 处同包抄写消灭）。
from model_gateway.upstream._text import json_or_none as _json_or_none  # noqa: F401 — 再导出


#: 可选钩子表（§22.3：`claim_onboarding` 是**可选**钩子，`capability=onboarding` 的产品才实现；
#: `loomy`/`raccoon` 两家）。与 `_HOOKS` 同形给出**唯一发现点**（不给字符串 `getattr` 留后门），
#: 但**不进** `_HOOKS` —— 那张表是**十钩子**的冻结契约（`test_registry.py` 逐字比对）。
#: 入口层按 `Capabilities.onboarding` 判断后经本表取用（UI 接线属 M6-4）。
_OPTIONAL_HOOKS = {
    "claim_onboarding": claim_onboarding,
}

#: 备选登录形态（`login_alt=("sms_code",)`）的两步入口表 —— **不是 §22.3 的十钩子**：
#: DSH 同样把短信两步放在独立的 `login.sendSms` / `login.submitSms` 两条 RPC 里
#: （`jet-hub-rpc.ts:1363-1436`），而不混进主登录通道。入口层按 `ProductMeta.login_alt`
#: 渲染短信 Tab 后经本表取用（UI 接线属 M6-4；表与 `_HOOKS` 同形，缺项当场 KeyError）。
_ALT_HOOKS = {
    "sms_send": sms_send,
    "sms_submit": sms_submit,
}

#: §22.3 契约表（入口层 `accounts/login.py::_hook` 与 M6-5 按名取用；缺项当场 KeyError）。
#: ⚠️ `claim_onboarding` **刻意不在表内**：§22.3 把它列为可选钩子，而本表是**十钩子**的
#: 冻结契约（`tests/accounts/test_registry.py::test_hooks_table_covers_the_frozen_contract`
#: 逐字比对）；入口层按 `Capabilities.onboarding` 发现它（模块级同名函数）。
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
