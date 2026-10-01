"""Loomy（讯飞）产品钩子（tech-design v2.0 §22.3 冻结签名；M6-3 实施）。

本产品证据面（§22.4 行 + `20 §2.6/§2.8/§3.1/§3.3`；`21 §1.1`）：

- 登录：**微信扫码（主）/ 短信（备）**（§22.4；`20 §2.8`）——实现见 `login.py` + `wechat.py`；
  短信两段经 `_ALT_HOOKS`（`sms_send` / `sms_submit`，§22.3 补入③），`login_callback`
  按「非 local_callback 型」显式失败（W3-fix 删掉了旧的 `action` 动作分派，与 raccoon 同款）
- 设备：**无设备标识**（`20 §2.7`）
- 额度 ✓ **两池**（`balance` 永久 / `dailyBalance` 每日赠送；`loomy-credits.ts:5-37`）
- 签到 ✓ = `POST /api/v1/points/first-login` —— 触发**每日赠送额度**，**不是 +5000**
  （`dailyBalance = dailyQuota − dailyConsumed`，消耗后不回补；`loomy-credits.ts:195-200`）
- 新手任务 ✓ 8 任务共 10000 分**一次性**（`loomy-onboarding.ts:46-55`）；⚠️ **不采信服务端 `earned`**，
  按本地 `LOOMY_TASK_POINTS` 现算（`:26-28`）→ `claim_onboarding` 钩子
- 模型：remote `GET /api/v1/models`（取 `type==='chat'`；**只认 `token` 头**）+ 8 条兜底表（`21 §1.1`）
- ⚠️ **不可续期**（`20 §2.6`：Loomy 无 refresh 端点）→ `refresh` 恒 `NotRefreshable`

## 两条口径的显式登记（防误读）

① **永久积分锁定不做成钩子**：它是**本地策略开关**（DSH 的 `credits.permanentLock` 只写本地
   store，`permanent-lock-store.ts`；不产生任何上游调用），而本网关的选路归 `core/resources.py`
   （§22.5-6「不建第二套调度」）→ 该策略的落点是能力位 `permanent_lock=True`（已在
   `accounts/registry.py` 登记）+ 后续入口/调度侧的本地开关，**不是**产品钩子（详见 `credits.py` 模块头）。
② **`Challenge.qr_payload` = 微信那张图片的 data URI（M7-C1 改口径）**：微信只给我们图片、
   不给内容串（DSH 同样只取图不取内容，`loomy-wechat.ts:198-221`）→ 本层**仍不编造内容串**，
   但改由**网关自己**带着铸出 uuid 的那组 UA + Referer 把 JPEG 取回来，编成
   `data:image/jpeg;base64,…` 放进 `qr_payload`（旧口径"`url` = 图片地址、让浏览器 `<img>`
   自己去取"实测必挂：跨域且带不上那两个头 → 用户看到的是一张加载失败的图）。
   `Challenge.url` 保留官方图片地址作为**可复制的展示文本**（§22.3 的「qr 型展示物」语义不变）。
   取图失败时 `qr_payload` 留空 + 原因由 `login_poll` 的 `detail` 如实播报（不给空 `<img>`）。

🔴 **实现全在 `loomy/` 的私有模块**（`constants` / `envelope` / `sign` / `wechat` / `api` /
   `login` / `credits` / `models`）；本文件只做薄接线（§22.1：不做通用 DSL，只做已证实的共性）。
🔴 `refresh` 用别名导出（不写 `async def refresh(`）：仓内死代码护栏
   `tests/unit/test_v2_cli_zcode.py:193-197` 对 `upstream/*/product.py` **之外**的文件做
   `def refresh(` 字面匹配，实现里的函数名因此是 `refresh_credential`（同 buddy 的处置）。
🔴 `build_out` **自 M6-5b 起已接线**（`upstream/loomy/out.py::LoomyOut`：标准 OpenAI 体、
`Authorization: Bearer` **加** 小写 `token` 双头，取证见该文件模块头）。
🔴 `claim_onboarding` 是 §22.3 的**可选**钩子（capability=onboarding 的产品才实现）→ 进 `_HOOKS`
   （入口层按表调度）；`tests/accounts/test_registry.py` 的契约表已加"可选钩子"容差（含签名断言）。
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
from model_gateway.upstream.loomy import credits as credits_mod
from model_gateway.upstream.loomy import login as login_mod
from model_gateway.upstream.loomy import models as models_mod

#: 本产品标识（§22.4；与 `accounts/registry.py` 的键、账号目录名一致）
PRODUCT = "loomy"


def meta() -> ProductMeta:
    """产品注册信息（唯一事实源 = `accounts/registry.py`，此处不重复填字段）。"""
    return registry_get(PRODUCT)


async def login_start(session) -> Challenge:
    """两步式第一步：微信扫码（拉授权页 → uuid → 二维码图片地址；`20 §2.8`）。

    ⚠️ **绝不索取手机号**（手机号在 `_ALT_HOOKS` 的 `sms_send` 步才需要）——
       规避 DSH 早期「start 要手机号、而表单等 start 返回 `loginMode:'sms'`」的顺序死锁
       （`jet-hub-rpc.ts:1063-1067`，详见 `login.py` 模块头）。
    """
    return await login_mod.start(session)


async def login_poll(session) -> LoginOutcome:
    """两步式第二步：微信长轮询 →（首次）绑手机号 → 凭据（`pending` 不是错误，§22.3）。"""
    return await login_mod.poll(session)


async def login_callback(session, params) -> LoginOutcome:
    """回跳粘贴（仅 local_callback 型产品，§22.3）。

    🔴 本产品是 **qr / sms_code 型**（`20 §2.8`）→ 入口层按 `ProductMeta.login` 只渲染
    二维码向导，本钩子**预期永不被调用**；短信两段走 `_ALT_HOOKS`（见下），保持显式失败，
    不写一个"看起来能用"的假实现（与 raccoon / cline / zcode 同款处置）。
    """
    raise NotImplementedError(
        "loomy.login_callback：本产品非 local_callback 型（扫码 / 短信，20 §2.8）")


async def sms_send(session, *, phone: str) -> LoginOutcome:
    """**备选形态（sms_code）第一步**：下发短信验证码（`login.py:send_sms_code`）。

    ⚠️ 本函数**不在 §22.3 的十钩子内**：`sms_code` 是备选通道（`ProductMeta.login_alt`），
    DSH 同样把它放在独立的 `login.sendSms` RPC（`jet-hub-rpc.ts:1363-1401`）而不是主登录通道
    → 入口层渲染短信 Tab 后经 `accounts/login.py::alt_call("loomy", session, "sms_send", …)`
    取用（与 raccoon 同形；kwarg：`phone`）。
    ⚠️ 返回 `LoginOutcome`（raccoon 回 `Challenge`）：可重试失败按 R-6 契约走 `pending`+detail。
    """
    return await login_mod.send_sms_code(session, phone=phone)


async def sms_submit(session, *, sms_code: str) -> LoginOutcome:
    """**备选形态第二步**：提交短信验证码完成登录（`login.py:submit_sms_code`）。

    与 DSH 的 `login.submitSms`（`jet-hub-rpc.ts:1408-1436`）同构：手机号取自上一步的会话态，
    未先发码 → `pending`「请先发送验证码」。同样不在 §22.3 十钩子内。
    """
    return await login_mod.submit_sms_code(session, sms_code=sms_code)


async def _refresh_impl(cred, meta) -> dict:
    """凭据续期（§22.3；**不可续期** → 恒 `NotRefreshable`，`20 §2.6`）。

    ⚠️ 别名导出：理由见模块头的护栏说明（`def refresh(` 的字面量只允许出现在
    `upstream/*/product.py`，实现里的名字是 `refresh_credential`）。
    """
    return await login_mod.refresh_credential(cred, meta)


#: §22.3 钩子名（保持冻结签名面；实现见 `_refresh_impl` 的说明）
refresh = _refresh_impl


async def probe(cred, meta) -> ProbeResult:
    """探活：连通 / 凭据有效两维分开（只读端点 `points/records`，`loomy-auth.ts:363-402`）。"""
    return await credits_mod.probe(cred, meta)


async def quota(cred, meta) -> QuotaSnapshot:
    """额度快照：两池（永久 / 每日赠送）合并成 `available|exhausted|unknown`（**未知不当零**，§22.3）。"""
    return await credits_mod.quota(cred, meta)


async def claim(cred, meta, *, precheck: bool) -> ClaimOutcome:
    """签到 = 触发每日赠送额度（幂等判据 `alreadyProcessed`；**不是**「+5000」）。"""
    return await credits_mod.claim(cred, meta, precheck=precheck)


async def claim_onboarding(cred, meta, *, precheck: bool) -> ClaimOutcome:
    """新手任务（§22.3 **可选**钩子）：8 任务共 10000 分一次性，按本地分值表现算（不采信服务端 `earned`）。"""
    return await credits_mod.claim_onboarding(cred, meta, precheck=precheck)


async def list_models(cred, meta) -> list[ModelInfo]:
    """模型目录：远端 `/api/v1/models`（取 `type==='chat'`）+ 8 条兜底表（`21 §1.1`）。"""
    return await models_mod.list_models(cred, meta)


def build_out(account) -> OutboundAdapter:
    """构造出站适配器（§22.3「出站适配」；M6-5b 接线）。

    - `account` = `adapters.product_out.ProductAccount`（product / 账号名 / 资源基址）；
    - 返回 `LoomyOut`（openai 族基类；端点 = `{base_url}/chat/completions`，
      基址已含 `/api/v1`，合起来即 `loomy-adapter.ts:483` 的取证路径）；
    - 延迟 import（`out.py` ↔ 本模块不互相在 import 期拉起，见 `product_out.py` 模块头 ⚠️）。
    """
    from model_gateway.upstream.loomy.out import LoomyOut
    return LoomyOut(account)


#: 骨架纪律护栏的**登记面**（`tests/accounts/test_registry.py::_implemented_hooks` 读它）：
#: 本产品已接线的钩子名。**刻意不列** `login_callback`（本产品非 local_callback 型 →
#: 显式失败）；`build_out` 自 **M6-5b** 起已接线（`upstream/loomy/out.py`）→ 进本表。
_IMPLEMENTED = ("login_start", "login_poll", "refresh", "probe",
                "quota", "claim", "claim_onboarding", "list_models", "build_out")


#: 备选登录形态（`login_alt=("sms_code",)`）的两步入口表（§22.3 补入③）——**不是** §22.3 的
#: 十钩子：入口层按 `ProductMeta.login_alt` 渲染短信 Tab 后经
#: `accounts/login.py::alt_call(product, session, name, **kw)` 取用（表与 `_HOOKS` 同形；
#: 缺项 → KeyError、未导出该表 → RuntimeError，不给字符串 `getattr` 留后门）。
_ALT_HOOKS = {
    "sms_send": sms_send,
    "sms_submit": sms_submit,
}


#: §22.3 契约表（入口层 `accounts/login.py::_hook` 与 M6-5 按名取用；缺项当场 KeyError）。
#: `claim_onboarding` = §22.3 的**可选**钩子（capability=onboarding 的产品才实现，本产品 ✓）；
#: 短信两段**刻意不在**本表（备选形态走 `_ALT_HOOKS`，§22.3 补入③）。
_HOOKS = {
    "meta": meta,
    "login_start": login_start,
    "login_poll": login_poll,
    "login_callback": login_callback,
    "refresh": refresh,
    "probe": probe,
    "quota": quota,
    "claim": claim,
    "claim_onboarding": claim_onboarding,
    "list_models": list_models,
    "build_out": build_out,
}
