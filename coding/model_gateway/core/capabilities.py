"""能力位组装（tech-design v2.0 §12 / PRD Q25-②）。

把网关内部已有的目录属性（`EnumEntry`）组装成**工具侧契约**要求的 8 个字段。

🔴 为什么需要：实测（`08` §6.4）工具侧 `supportsToolCall !== true` 会**删除请求中的 tools**、
无 `thinkingLevelMap` 会让推理档位**变哑** —— 网关没做错什么，但工具行为被静默改变。

⚠️ **字段名以工具契约为准（camelCase）**，此处**修正 PRD Q25-② 的字面**
（PRD 写 snake_case + 顶层 `effort_levels`；实测工具要的是 camelCase + `caps.thinkingLevelMap`）。
"""

from __future__ import annotations

from typing import Any

from model_gateway.core.dialects import build_level_map


def build_model_caps(model: Any, enum_pool: Any, dialects: Any = None) -> dict[str, Any]:
    """组装单个系统模型的**能力位**（在原有 6 字段之外追加的部分）。

    返回 7 个键（`caps` 单独在 `build_caps_block` 里组装，便于 M3-2/M3-4 分期）：
    `name` / `vendor` / `maxInputTokens` / `maxOutputTokens` /
    `supportsToolCall` / `supportsImages` / `supportsReasoning`

    **自定义系统模型**（不在内置目录，Q19-② 允许就地新建）→ 走最小字段集，**不崩**。
    **目录缺某属性**（如 `claude-sonnet-4` 无 `context_window`）→ 输出 `None`，
    工具回退自身兜底值，**与现状等价，不臆造数值**。
    """
    entry = enum_pool.get(model.name) if enum_pool is not None else None
    if entry is None:
        return {
            "name": model.name,
            "vendor": "",
            "maxInputTokens": None,
            "maxOutputTokens": None,
            "supportsToolCall": False,
            "supportsImages": False,
            "supportsReasoning": False,
        }
    return {
        "name": entry.display or model.name,
        "vendor": entry.vendor,
        "maxInputTokens": entry.context_window,
        "maxOutputTokens": entry.max_output,
        "supportsToolCall": entry.tool_call,
        "supportsImages": entry.image_input,
        "supportsReasoning": entry.reasoning,
    }


def build_caps_block(model: Any, enum_pool: Any, dialects: Any = None) -> dict[str, Any]:
    """组装 `caps` 块（§12.2a / §13.1）—— 含 `thinkingLevelMap`（**7 键齐全**）与 `thinkingFormat`。

    - `thinkingLevelMap`：规范序 7 键**必须全部出现**，不支持的档**显式写 `None`**（JSON 后为 `null`）。
      键缺失（`undefined`）≠ `null` —— 工具对非高阶档会把缺失键判为"支持"→ 上游静默忽略。
    - `thinkingFormat`：**从方言表取**（L-C 层，§14.1），**不在 `EnumEntry` 上取**（它没有该字段）。
    - 用户手改的 `model.caps_overrides` **优先级最高**（目录/探测不准时的逃生口）。
    """
    entry = enum_pool.get(model.name) if enum_pool is not None else None
    ov = getattr(model, "caps_overrides", None) or {}
    supported = list(getattr(entry, "effort_levels", None) or []) if entry else []
    level_map = build_level_map(supported, ov.get("thinkingLevelMap"))

    fmt = ov.get("thinkingFormat")
    if not fmt and dialects is not None:
        fmt = dialects.thinking_format_of(model.name)
    return {"thinkingLevelMap": level_map, "thinkingFormat": fmt or ""}
