"""出站适配层（tech-design §4.4 / v2.0 §18 / §22.3）。

- openai_out：OpenAI 兼容出站（商汤首发）
- anthropic_out：Anthropic Messages 出站（**v2.0 从空壳补齐**，ZCode 上游用）
- gemini_out：P2（仍为空壳）
- product_out：**产品出站**（§22.3 duck typing；M6-5a）——按 `Resource.product` 分派，
  凭据从本地账号目录自解（不进 config）
- factory：`build_adapter` = **唯一分发点**（`product` 分支优先于 `protocol`，§22.5-3）
"""

from __future__ import annotations

from typing import Any, Callable

from model_gateway.adapters.anthropic_out import AnthropicOutAdapter
from model_gateway.adapters.openai_out import OpenAIOutAdapter
from model_gateway.adapters.product_out import build_product_adapter

def build_adapter(
    protocol: str,
    base_url: str,
    needs_base64: Callable[[str], bool] | None = None,
    *,
    fingerprint: bool = False,
    product: str = "",
    account_ref: str = "",
) -> Any:
    """按资源构造出站适配器（v2.0 §18.2 ② 分发点；M6-5a 追加产品分支）。

    > v1.0/v1.6 的 `main.py` **无条件**构造 `OpenAIOutAdapter`，`Resource.protocol`
    > 字段**完全未被使用** —— 本函数是补齐该分发点。

    🔴 **`product` 分支优先于 `protocol`**（§22.5-3）：`product` 非空 = 该资源由产品账号
    体系供给 → 走 `upstream/<product>/product.py::build_out(account)`（凭据经账号目录自解）；
    `custom` 产品（qoder/qodercn/trae）物化时 `Resource.protocol` 落 `"openai"` 仅为
    schema 字面量兼容，真正分派以 `product` 为准。

    `fingerprint=True`：**仅 anthropic 协议**生效（`zcode.z.ai` 前置 ESA WAF）。
    由 `gateway.zcode.fingerprint` 配置驱动，curl_cffi 不可用时适配器内自动降级。
    """
    if (product or "").strip():
        return build_product_adapter(product, account_ref, base_url,
                                     needs_base64=needs_base64)
    if protocol == "anthropic":
        return AnthropicOutAdapter(base_url, needs_base64=needs_base64,
                                   fingerprint=fingerprint)
    # openai / gemini（gemini 仍为空壳，暂回落 openai 兼容）
    return OpenAIOutAdapter(base_url, needs_base64=needs_base64)
