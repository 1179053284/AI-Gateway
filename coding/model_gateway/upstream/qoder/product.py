"""Qoder 产品钩子（tech-design v2.0 §22.3 冻结签名；**M6-2 批 A 实现**）。

本产品证据面（§22.4 行 + `20 §1.2/§2.7/§3.1`；`21 §1.1`）：

- 登录：**device_code 轮询**（授权页 URL → `GET {openApiBase}/api/v1/deviceToken/poll`；
  404 = 用户还没点完，`qoder-oauth.ts:107-118`）
- 设备：`machine_id`（登录生成 → `meta.json` 与凭据双写；续期载荷必带，`20 §2.7`）
- 额度 ✓ = `GET /sash/api/v2/me/usage`（`qoder-credits.ts:278-340`）
- 签到 ✓ = `GET /sash/api/v1/me/campaigns` → 逐个 `POST …/{campaignId}/claim`
  （幂等 = 响应体 `replayed:true`；**「无可领活动」必须报 `inactive`**，`20 §3.1`/`qoder-credits.ts:605-610`）
- 模型：**恒本地兜底表**（远端目录端点需 WASM 签名，明确不实现，`21 §1.1`）

实现全部在 `qoder/flow.py`（**两站共用**；差异 = `qoder/config.py` 的区域配置值）；
`qodercn` 复用同一实现 —— 本文件只负责「用国际版配置接线」，**不得出现任何默认区域**。

🔴 `build_out` 自 **M6-5c** 起已接线（`upstream/qoder/out.py::QoderOut`）：信封解包 +
   明文请求构造已实现；**请求加密与 COSY 签名**由本机 wasm 桥提供
   （`wasm_signer.py`，按 `MGW_QODER_WASM_GLUE` 注入）→ 仍走 `SIGNER_FACTORY` 这条缝
   （未注入时请求当场 fail closed，**不伪造签名、不降级公开端点**）。
🔴 `_HOOKS` = 本模块对 §22.3 的**契约表**：入口层按名取用（不给字符串 `getattr` 留后门）。
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
from model_gateway.upstream.qoder import flow
from model_gateway.upstream.qoder.config import require_qoder_family

#: 本产品标识（§22.4；与 `accounts/registry.py` 的键、账号目录名一致）
PRODUCT = "qoder"

#: 本区域配置（`require_qoder_family` 取不到当场抛错 —— DSH `requireQoderFamily` 同语义）
_CONFIG = require_qoder_family(PRODUCT)


def meta() -> ProductMeta:
    """产品注册信息（唯一事实源 = `accounts/registry.py`，此处不重复填字段）。"""
    return registry_get(PRODUCT)


async def login_start(session) -> Challenge:
    """启动登录：生成 PKCE + nonce + machine_id，返回授权页 URL（`qoder-oauth.ts:205-215`）。"""
    return await flow.login_start(_CONFIG, session)


async def login_poll(session) -> LoginOutcome:
    """轮询登录状态（§22.3：**pending 不是错误**；404 = 用户尚未完成授权）。"""
    return await flow.login_poll(_CONFIG, session)


async def login_callback(session, params) -> LoginOutcome:
    """回跳粘贴 —— 本产品非 local_callback 型（device_code），只回报可预期失败。

    🔴 本钩子**未接线**（无本机回跳通道）但保留显式拒绝形态（`failed` + 可读原因），
    并在 `_REFUSED_HOOKS` 登记理由 —— 骨架护栏（`tests/accounts/test_registry.py`）
    对它的探针要求"非 success/pending、零凭据"，`success` 一律判红（M6-6 收口 R4 F4）。
    """
    return await flow.login_callback(_CONFIG, session, params)


async def refresh(cred, meta) -> dict:
    """凭据续期：`POST /api/v1/deviceToken/refresh`（载荷 `{refresh_token, machine_id}`）。

    终态（401/403、缺 token）→ `NotRefreshable`；网络/5xx → 可重试异常（`qoder-auth.ts:395-438`）。
    """
    return await flow.refresh_credential(_CONFIG, cred, meta)


async def probe(cred, meta) -> ProbeResult:
    """探活：`GET /api/v1/userinfo`（连通 / 凭据有效两维分开，§22.3）。"""
    return await flow.probe(_CONFIG, cred, meta)


async def quota(cred, meta) -> QuotaSnapshot:
    """额度快照：`GET /sash/api/v2/me/usage`（三态；**未知不当零**，§22.3）。"""
    return await flow.quota(_CONFIG, cred, meta)


async def claim(cred, meta, *, precheck: bool) -> ClaimOutcome:
    """签到/领取：campaigns → 逐个 claim（`replayed` 判幂等、无可领活动报 inactive，`20 §3.1`）。"""
    return await flow.claim(_CONFIG, cred, meta, precheck=precheck)


async def list_models(cred, meta) -> list[ModelInfo]:
    """**恒本地兜底表**（17 条，`qoder-product.ts:362-436` 照抄；零网络，`21 §1.1`）。"""
    return flow.list_models(_CONFIG)


def build_out(account) -> OutboundAdapter:
    """构造出站适配器（§22.3「出站适配」；M6-5c 接线）。

    - **区域配置显式注入**（本模块的 `_CONFIG` = `QODER`；qodercn 注入 `QODER_CN`）
      —— 两站 token/端点不通用（`20 §4.1`），这里不存任何默认区域；
    - 返回 `upstream/qoder/out.py::QoderOut`：响应信封解包 + 明文请求构造已实现；
      **请求加密与 COSY 签名走本机 wasm 桥**（`wasm_signer.py`）→ `out.SIGNER_FACTORY`
      注入缝；未配置时
      请求当场 fail closed（**不伪造签名、不降级公开端点**，见 out.py 模块头）；
    - 延迟 import（`out.py` ↔ 本模块不互相在 import 期拉起）。
    """
    from model_gateway.upstream.qoder.out import QoderOut
    return QoderOut(account, _CONFIG)


#: §22.3 契约表（入口层 `accounts/login.py::_hook` 与 M6-5 按名取用；缺项当场 KeyError）
#: 骨架纪律登记面（**私有约定**，只被 `tests/accounts/test_registry.py::_implemented_hooks`
#: 读取；不是 §22.3 冻结契约的一部分、也不被入口层读取）：
#: `_IMPLEMENTED` = **已接线**的钩子（有真实行为路径），精确到钩子名 —— 未列出的钩子仍受
#: 「未接线必须显式失败」约束（M6-6 收口 R4 §2.1/BL-2：修前本模块不声明任何接线面，
#: 被 filename 口径整体放行，往 `login_callback` 植入"编造 success"时护栏全绿）。
_IMPLEMENTED = frozenset({"meta", "login_start", "login_poll", "refresh", "probe",
                          "quota", "claim", "list_models", "build_out"})

#: **未接线但有显式拒绝行为**的钩子 → 理由（M6-6 同批收口；护栏用探针钉住其行为）：
#: `login_callback` 本产品非 local_callback 型（无本机回跳通道）→ 不抛 `NotImplementedError`，
#: 只回报**可预期失败**（`failed` 终态、零凭据）—— 比折返成异常对入口层更可读；
#: 探针见 `test_registry.py::assert_declared_refusal`（`success`/`pending`/任何凭据一律判红）。
_REFUSED_HOOKS = {
    "login_callback": "非 local_callback 型（device_code 轮询）——无本机回跳通道，只回报可预期失败",
}

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
