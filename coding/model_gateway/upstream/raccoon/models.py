"""Raccoon 模型目录：远端 `model_catalog` + 兜底表（§22.5-4；**取不到不编造**）。

🗂 证据面：`src/raccoon-auth.ts:470-494`（`fetchModels`）、`:137-182`（单条归一）、
   `:622-652`（目录解析）、`src/raccoon-product.ts:196-263`（兜底表 + 取用规则）、
   `src/raccoon-adapter.ts:229-254`（远端优先、失败回退兜底表）；`docs/research/21 §1.1`。

**取用规则（照抄 DSH，逐条）**：

1. 有凭据 → `GET /api/web/llm/v2/model_catalog`，只取 `categories[].type == 'chat'`，
   过滤 `visible === false`（`:632-636`、`:140-141`）；
2. 远端**返回非空** → **以远端为准**（DSH 不把兜底表并进远端结果：`remoteModels ?? fallback`，
   `raccoon-adapter.ts:230`）—— 远端是活目录，兜底表只是它的取证快照；
3. 远端失败 / 返回空 / 形态不认识 / 无凭据 → **兜底表**（6 条，`const.FALLBACK_MODELS`，
   逐条照抄 DSH 实测快照）。

⚠️ 目录是**建议性数据**：远端抖动不得让整个产品报错（`raccoon-adapter.ts:243-247` 静默回退）
   → 本模块除"凭据缺失"外一律不抛，只记 warning。
"""

from __future__ import annotations

import logging

import httpx

from model_gateway.accounts import net
from model_gateway.accounts.types import ModelInfo
from model_gateway.upstream.raccoon import const as C
from model_gateway.upstream.raccoon import protocol as p

logger = logging.getLogger("model_gateway.upstream.raccoon")


async def list_models(cred: dict | None) -> list[ModelInfo]:
    """产品模型目录（远端优先，失败回退兜底表）。"""
    token = p.access_token_of(cred)
    if not token:
        logger.warning("[raccoon] 模型目录跳过远端：凭据缺 access_token（回退兜底表）")
        return list(C.FALLBACK_MODELS)
    try:
        async with net.make_client(base_url=C.API_BASE, timeout=C.REQUEST_TIMEOUT_S) as client:
            resp = await client.get(C.MODEL_CATALOG_PATH, headers=p.headers(cred))
            payload = _json_or_none(resp)
    except httpx.HTTPError as e:
        logger.warning("[raccoon] 模型目录远端不可用（回退兜底表）：%s", e)
        return list(C.FALLBACK_MODELS)
    if resp.status_code != 200:
        logger.warning("[raccoon] 模型目录 HTTP %s（回退兜底表）", resp.status_code)
        return list(C.FALLBACK_MODELS)
    remote = p.parse_catalog(payload)
    if remote is None:
        logger.warning("[raccoon] model_catalog 响应形态不认识（回退兜底表）")
        return list(C.FALLBACK_MODELS)
    if not remote:
        logger.warning("[raccoon] model_catalog 无可见模型（回退兜底表）")
        return list(C.FALLBACK_MODELS)
    return remote


# R2a-F-5（2026-10-06）：实现收编到 `upstream/_text.py`（一份实现，6 处同包抄写消灭）。
from model_gateway.upstream._text import json_or_none as _json_or_none  # noqa: F401 — 再导出
