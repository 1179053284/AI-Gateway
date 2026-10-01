"""Qoder（中国版） 产品钩子（tech-design v2.0 §22.3 冻结签名；**M6-2 批 A 实现**）。

本产品证据面（§22.4 行 + `20 §1.1/§4.1`；`21 §1.1`）：

- 登录：同 qoder（**设备码轮询**；`QoderProduct.id` 联合类型，`qoder-product.ts:172-181`）
- 设备：`machine_id`（同国际版，`20 §2.7`）
- 额度 ✓ / 签到 ✓（`credits-capabilities.js:85` 显式登记 `qodercn` 两项；CN 端点零凭据实测
  与国际版逐字节同形，`qoder-credits.js` 段注释）
- 模型：同国际版形态（`QODER_CN_FALLBACK_MODELS`，14 条，`qoder-product.ts:480-581`）
- ⚠️ **两站 token 不通用**：`authBase`/`openApiBase`/`clientId`/加密端点四项全不同
  （`qoder-product.ts:592-612`）；串用由 `flow` 的 `_guard_family`（凭据区域标记）拒绝 ——
  DSH 侧对应 `requireQoderFamily` 按 provider 取实例（`jet-hub-rpc.ts:744-757,1287-1295`）

实现全部复用 `qoder/flow.py`（**零复制**；差异 = `qoder/config.py` 的 `QODER_CN` 区域值）。

🔴 `build_out` 自 **M6-5c** 起已接线（复用 `qoder/out.py::QoderOut`，区域配置注入 `QODER_CN`；
   加密/签名走注入缝，未接线时请求即显式失败 —— 见 `qoder/out.py` 模块头）。
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
PRODUCT = "qodercn"

#: 本区域配置（中国版；取不到当场抛错 —— DSH `requireQoderFamily` 同语义）
_CONFIG = require_qoder_family(PRODUCT)


def meta() -> ProductMeta:
    """产品注册信息（唯一事实源 = `accounts/registry.py`，此处不重复填字段）。"""
    return registry_get(PRODUCT)


async def login_start(session) -> Challenge:
    """启动登录：同国际版流程，但用 **CN 的 authBase/clientId**（`qoder-product.ts:592,609`）。"""
    return await flow.login_start(_CONFIG, session)


async def login_poll(session) -> LoginOutcome:
    """轮询登录状态（挂 CN 的 `openApiBase`；pending 不是错误）。"""
    return await flow.login_poll(_CONFIG, session)


async def login_callback(session, params) -> LoginOutcome:
    """回跳粘贴 —— 本产品非 local_callback 型（device_code），只回报可预期失败。

    🔴 本钩子**未接线**（无本机回跳通道）但保留显式拒绝形态（`failed` + 可读原因），
    并在 `_REFUSED_HOOKS` 登记理由 —— 骨架护栏（`tests/accounts/test_registry.py`）
    对它的探针要求"非 success/pending、零凭据"，`success` 一律判红（M6-6 收口 R4 F4）。
    """
    return await flow.login_callback(_CONFIG, session, params)


async def refresh(cred, meta) -> dict:
    """凭据续期（挂 CN 的 `openApiBase`）。

    🔴 **绝不允许交叉使用国际版的刷新逻辑**：本函数只走 `QODER_CN` 配置；若凭据带
    `family="qoder"` 标记 → `FamilyMismatchError`（**不打上游**；`20 §4.1` 的串用注释）。
    """
    return await flow.refresh_credential(_CONFIG, cred, meta)


async def probe(cred, meta) -> ProbeResult:
    """探活：CN 的 `/api/v1/userinfo`（连通 / 凭据有效两维分开，§22.3）。"""
    return await flow.probe(_CONFIG, cred, meta)


async def quota(cred, meta) -> QuotaSnapshot:
    """额度快照：CN 的 `/sash/api/v2/me/usage`（三态；**未知不当零**）。"""
    return await flow.quota(_CONFIG, cred, meta)


async def claim(cred, meta, *, precheck: bool) -> ClaimOutcome:
    """签到/领取（CN 的 campaigns/claim 端点）；语义同国际版契约（`replayed` 判幂等）。"""
    return await flow.claim(_CONFIG, cred, meta, precheck=precheck)


async def list_models(cred, meta) -> list[ModelInfo]:
    """**恒本地兜底表**（14 条，`qoder-product.ts:480-581` 照抄；不含国际版独有模型）。"""
    return flow.list_models(_CONFIG)


def build_out(account) -> OutboundAdapter:
    """构造出站适配器（§22.3「出站适配」；M6-5c 接线）。

    - **区域配置显式注入**（本模块的 `_CONFIG` = `QODER_CN`）：CN 的加密端点为
      `gateway.qoder.com.cn`（`qoder-product.ts:604`），与国际版**不共用**；
      出站前还有 `flow._guard_family` 同款凭据区域标记检查（不符 → 不打上游）；
    - 加密/签名走 `out.SIGNER_FACTORY` 注入缝（未注入 → 请求时 fail closed）；
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
