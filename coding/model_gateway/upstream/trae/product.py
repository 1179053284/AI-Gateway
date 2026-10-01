"""Trae 产品钩子（tech-design v2.0 §22.3 冻结签名；**M6-3 批 B 实现**）。

本产品证据面（§22.4 行 + `20 §1.2/§2.7/§3.1/§3.5`；`21 §1.1`）：

- 登录：**local_callback** 两步式（`trae-oauth.ts:40,550-706`）——回跳接收端由公共层
  提供（BD4：`accounts/callback_server.py`，**只绑 127.0.0.1**，首选端口 18080 被占时
  回退随机端口、授权 URL 用实际端口重建），本产品的 `_CALLBACK` 表声明它的路径/端口/
  关联参数；接收端起不来时回退「地址栏粘贴」（同一 `login_callback`，见 `login.py` 模块头）
- 设备：`machine_id`（32hex 随机）+ `device_id`（**由 uid 确定性派生**，15 位数字）——
  9074 设备轮换代次机制**已废弃**（`20 R14/§3.5`），不实现代次
- 额度 ✓ = `POST /trae/api/v2/pay/ide_user_ent_usage`（`quota.py`）
- 签到 ✓ = `status` → `claim`；🔴 **幂等只能靠 status 端点的 `checked_in`**（claim 对已签到
  同样回 `{code:0,"success"}`，与真领取无法区分，`20 §3.1`/`jet-hub-rpc.ts:1801-1806`）
  → `claim(precheck=True)` **必须为 True**（§22.6 per-product 声明）
- 模型：remote batch 目录（按 `function` 通道查，`21 §1.1`）+ 32 条兜底表（`models.py`）

`login_poll` **显式 `NotImplementedError`**：本产品**没有轮询通道** —— 凭据只从回跳粘贴来
（DSH 同形：它 await 本地回调服务器，`trae-oauth.ts:604-671`，没有可轮询的对象）。
按契约表按名取用会在入口层暴露出「这里不存在轮询」，而不是静默 pending 一辈子
（与 buddy 对 `login_callback` 的处理同款、方向相反）。

🔴 `build_out` 自 **M6-5c** 起已接线（`upstream/trae/out.py::TraeOut`：SOLO 请求塑形 +
   自定义 SSE 成帧消费；通道映射取 `models.channel_for`，不重写一份）。
🔴 `_HOOKS` = 本模块对 §22.3 的**契约表**：入口层按名取用（不给字符串 `getattr` 留后门）。
🔴 `_IMPLEMENTED` = 已接线钩子名（`tests/accounts/test_registry.py::_implemented_hooks`
   的**首选口径**）：**不含 `login_poll`**（显式 NotImplementedError）—— 骨架纪律护栏
   对它继续生效，写一半的假实现拦得住。
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
from model_gateway.upstream.trae import claim as claim_mod
from model_gateway.upstream.trae import const, login, models, quota as quota_mod

#: 本产品标识（§22.4；与 `accounts/registry.py` 的键、账号目录名一致；
#: 字面量在 `const.py` 里只写一份，这里指向它）
PRODUCT = const.PRODUCT_ID

#: 已接线的钩子名（精确到钩子名；`login_poll` **不在本表** → 护栏仍生效；
#: `build_out` 自 M6-5c 起已接线）
_IMPLEMENTED = ("meta", "login_start", "login_callback", "refresh",
                "probe", "quota", "claim", "list_models", "build_out")


def meta() -> ProductMeta:
    """产品注册信息（唯一事实源 = `accounts/registry.py`，此处不重复填字段）。"""
    return registry_get(PRODUCT)


async def login_start(session) -> Challenge:
    """启动登录（§22.3 两步式的第一步）：**零网络**，返回登录页 URL。

    `machine_id` / 登录期 `device_id` / `login_trace_id` 进 `session.state`
    （**不进 Challenge**，§22.3：Challenge 只承载用户可见物）。
    🔴 回调地址里的端口 = 引擎已绑定的**回跳接收端实际端口**（BD4；`login_start` 里
       不起监听也不做网络调用 —— 绑定在引擎建会话时已完成，见 `accounts/login.py`）。
    """
    return await login.login_start(session)


async def login_poll(session) -> LoginOutcome:
    """**不适用**（本产品没有轮询通道）：显式 `NotImplementedError`，不伪装成 pending。

    理由（逐条可查）：TRAE 的凭据由登录页**直接回跳**到本机的回调接收端
    （`127.0.0.1:{实际端口}/authorize`，`trae-oauth.ts:239-243` 的实测回调形态），
    DSH 的做法是 await 本地回调服务器（`trae-oauth.ts:604-671`）——全流程没有任何
    "可以轮询的状态端点"，轮询永远只会返回 pending。本网关的推进通道有两条、**同一出口**：
    接收端投递（BD4，`accounts/callback_server.py`）与地址栏粘贴兜底（§22.7 向导），
    都只由 `login_callback` 落地；入口层按 `ProductMeta.login == "local_callback"`
    就不该发起轮询（M6-4 前端同源）。
    """
    raise NotImplementedError(
        "trae.login_poll：本产品为 local_callback 型，**无轮询通道** —— "
        "凭据只由 login_callback 落地（回跳接收端投递 / 地址栏粘贴兜底，同一入口；"
        "`trae-oauth.ts:239-243,604-671`）；"
        "入口层对 local_callback 产品不应发起轮询（§22.7 回跳粘贴向导）")


async def login_callback(session, params) -> LoginOutcome:
    """回跳落地（仅 local_callback 型，§22.3）：校验路径/端口/关联串 → ExchangeToken → 凭据。

    🔴 两条投递共用（BD4）：接收端送来的真 URL 与用户粘回来的整串地址都是
       `{"url": …}` —— 判据只有一份（见 `login.py` 模块头）。
    校验判据与失败语义见 `login.validate_callback`（DSH 回调处理器同源，`trae-oauth.ts:620-671`）。
    """
    return await login.login_callback(session, params)


async def refresh(cred, meta) -> dict:
    """凭据续期：`ExchangeToken`（refreshToken 轮换；`trae-auth.ts:378-431`）。

    终态（401/403、2xx 却无 token）→ `NotRefreshable`；网络/5xx/非 JSON → 可重试异常。
    设备字段**不改写**（`trae.ts:614-637`）；新 `expires_at` 回写 `meta.json`（!IKIRTT 教训）。
    """
    return await login.refresh_credential(cred, meta)


async def probe(cred, meta) -> ProbeResult:
    """探活：`GetUserInfo`（只读、不消耗额度；连通 / 凭据有效两维分开，§22.3）。"""
    return await login.probe(cred, meta)


async def quota(cred, meta) -> QuotaSnapshot:
    """额度快照：资源包合计（三态；**未知不当零**，§22.3 + `23 B2`）。"""
    return await quota_mod.quota(cred, meta)


async def claim(cred, meta, *, precheck: bool) -> ClaimOutcome:
    """签到：status 预检 → claim → **status 复核**（`precheck` 对本产品必须 True）。

    幂等判据、9074 已废弃的换设备重试、错误冷却表（12h/60s/-1/600s/300s）见 `claim.py` 模块头。
    """
    return await claim_mod.claim(cred, meta, precheck=precheck)


async def list_models(cred, meta) -> list[ModelInfo]:
    """产品模型目录：远端 batch（22 个 function）+ 32 条兜底表（取不到不编造，`21 §5.1-1`）。"""
    return await models.list_models(cred, meta)


def build_out(account) -> OutboundAdapter:
    """构造出站适配器（§22.3「出站适配」；M6-5c 接线）。

    - `account` = `adapters.product_out.ProductAccount`（product / 账号名 / 资源基址）；
    - 返回 `upstream/trae/out.py::TraeOut`：SOLO 请求塑形 + 自定义 SSE 成帧消费，
      凭据经账号目录自解（**不进 config**，铁律 1）；
    - 延迟 import（`out.py` ↔ 本模块不互相在 import 期拉起，见 out.py 模块头）。
    """
    from model_gateway.upstream.trae.out import TraeOut
    return TraeOut(account)


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

#: 回跳接收端声明（BD4；引擎 `accounts/login.py::_callback_plan` 读这张表，
#: 与 `_HOOKS`/`_ALT_HOOKS` 同样"表里有什么才用什么"，不给 `getattr` 猜字段的后门）。
#:
#: - `path`：接收端**只**服务这个路径（其余 404 且不消耗会话）= `const.CALLBACK_PATH`；
#: - `preferred_port`：首选端口 18080（`trae-oauth.ts:40`）；被占用时接收端自己回退
#:   随机端口（`:530-543`），授权 URL 用**实际**端口重建（`:680-693`）；
#: - `secret_state_key` / `secret_key`：关联串 = `login_trace_id`
#:   （`machineTraceId`，`trae-oauth.ts:71-76`；`login_start` 生成后写进会话态）；
#: - `secret_required=False`：TRAE **不保证**回传该参数（`:67-70`）→ 没带不判无效，
#:   带回且不一致才由接收端回 400 并继续监听（伪造回跳不该打死正在进行的登录）。
_CALLBACK = {
    "path": const.CALLBACK_PATH,
    "preferred_port": const.CALLBACK_PORT,
    "secret_state_key": "login_trace_id",
    "secret_key": "login_trace_id",
    "secret_required": False,
}
