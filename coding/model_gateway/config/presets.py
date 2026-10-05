"""供应商预设注册表（tech-design §4.7；PRD FR-1.2，UT-26）。

模块级常量清单（明文数据，非 UI 分支）：接入向导预设下拉的数据源，
由 GET /admin/api/presets 返回（admin 层，M2）。

扩展原则：新增供应商或 Plan 类型 = 仅加一条预设数据（必要时新增协议适配器），
接入向导与 UI 框架零改动（tech-design §4.7）；billing 为可扩展枚举，
空/未知口径经 display_billing 优雅降级显示「—」。
"""

from __future__ import annotations

import copy

# 字段：id / name / mode(api|plan，custom 为空由用户填) / protocol /
#       base_url / billing(计费口径) / notes(说明文案)
PRESETS: list[dict] = [
    {
        "id": "sensenova-api",
        "name": "商汤按量 API",
        "mode": "api",
        "protocol": "openai-compat",
        "base_url": "https://api.sensenova.cn/compatible-mode/v2",
        "billing": "按量付费",
        "notes": "OpenAI 兼容按量端点，普通 API Key，按 token 用量计费。",
    },
    {
        "id": "sensenova-tokenplan",
        "name": "商汤 TokenPlan",
        "mode": "plan",
        "protocol": "openai-compat",
        "base_url": "https://token.sensenova.cn/v1",
        "billing": "积分制",
        "notes": "订阅套餐 Token 端点，积分计费（M1 实测定论可用端点）。",
    },
    {
        "id": "custom",
        "name": "自定义接入",
        "mode": "",
        "protocol": "openai-compat",
        "base_url": "",
        "billing": "",
        "notes": "空白模板：全部字段手动填写。",
    },
]


def list_presets() -> list[dict]:
    """返回预设清单（深拷贝，防外部篡改内部常量）。"""
    return copy.deepcopy(PRESETS)


def get_preset(preset_id: str) -> dict | None:
    """按 id 查预设（未命中返回 None）。"""
    return next((p for p in PRESETS if p["id"] == preset_id), None)


def preset_name(preset_id: str) -> str | None:
    """预设显示名（事件/统计的「按供应商」维度口径）：未设置或未知 → None（调用方降级 'custom'）。"""
    p = get_preset(preset_id)
    return p["name"] if p else None


def display_billing(preset: dict) -> str:
    """计费口径展示值：空/未知口径（缺失或空串）→「—」，否则原值（UT-26）。"""
    return preset.get("billing") or "—"
