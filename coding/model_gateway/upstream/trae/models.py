"""TRAE 模型目录：远端 batch（按通道）+ 本地兜底表（§22.5-4；`21 §1.1`）。

协议（`trae-auth.ts:628-712` + `trae.ts:1191-1256`）::

    POST {AGENT_HOST}/api/ide/v1/batch_get_detail_param
    body {functions: [22 条 function], agent_type: "", current_config_info: {...},
          mode_type: 0, access_type: 0, ab_force_vids: "", ab_autotest_advanced_mode: 0,
          show_custom_model: true}
    → {function_configs: [{function, config_info_list: [{config_name, display_config,
         model_detail_list, context_window_tokens, reasoning_effort_config, usage, …}]}]}

- **每个 function 各自一套目录**，同一条目在不同通道的可用性/思考档位**可以不同**；
  合并规则与三条硬性过滤见 `protocol.parse_batch_models`（`trae.ts:1158-1256`）。
- 远端**整体失败**（未登录 / 非 2xx / 网络 / 结构不符）→ `options`：
  `const.FALLBACK_MODELS`（32 条，来源 `trae-product.ts:164-202` = Go 端 staticModels
  2026-08 实测快照；其中 4 条上游标记为隐藏条目，与远端路径的 `is_invisible_to_user`
  硬过滤同判据 → 不返回）。

🔴 **取不到不编造**（`21 §5.1-1`）：
   - `tool_call` 恒 `None`（远端**没有**逐模型的工具能力字段；DSH 也不播报它）；
   - `vendor` 留空（远端无「vendored by」语义字段）；
   - `max_output` 兜底路径留 `None`：DSH 的产品级 `fallbackMaxOutputTokens: 32_000`
     （`trae-product.ts:103-110,278`）是**本地收敛上限**而不是模型能力，其源注释明确
     写「不放进 fallbackModels 逐条声明是因为各模型真实值并不一致（4000 ~ 384000）」
     → 按同一理由不把它冒充成每条模型的 `max_output`；
   - 兜底表的 `context_window = 200_000` 是**照抄**（`trae-product.ts:34-37` 自注为估值、
     远端可用时完全采信远端）—— 这里如实带上并注明，不改写成 `None` 也不放大。
"""

from __future__ import annotations

import logging

import httpx

from model_gateway.accounts import net
from model_gateway.accounts.types import ModelInfo
from model_gateway.upstream.trae import const, protocol

logger = logging.getLogger("model_gateway.accounts")


def _rate_text(value: float) -> str:
    """倍率数字 → 展示文本（无尾随 0，不出现科学计数法；对齐 JS `x${0.08}` 的字符串形态）。

    实测形态是裸数字（`0.08` / `0.4` / `0`），`xf"{v:.10f}"` 再剥尾零对这类值稳定。
    """
    number = f"{value:.10f}".rstrip("0").rstrip(".")
    return f"x{number or '0'}"


def _billing_of(entry: protocol.RemoteEntry) -> tuple[bool | None, str]:
    """`RemoteEntry` 的计费字段 → `(free, rate)`（复刻 `traeDisplayName`，`trae-adapter.ts:570-581`）。

    - 无倍率（`consumption_rate.enable === false` / 未下发）→ `None` / `""`（**不编造** `x1`，
      `trae-adapter.ts:568`）；
    - `rate: 0` 是**合法**免费值（必须与「没有倍率」分开，`trae-adapter.ts:573-574`）
      → `free=True` + `rate="x0"`（DSH 同情形展示「免费」）；
    - 活动折扣只在解析层已判定「当前生效」时才有 `original_rate`（`trae.ts:1002-1042`）
      → `x原价→x折后价`（`trae-adapter.ts:576-579`）；折后价用 `consumption_rate` 的值。
    """
    if entry.rate is None:
        return None, ""
    current = "x0" if entry.rate == 0 else _rate_text(entry.rate)
    if entry.original_rate is not None and entry.original_rate > entry.rate:
        return False, f"{_rate_text(entry.original_rate)}→{current}"
    return entry.rate == 0, current


def _model_info(entry: protocol.RemoteEntry) -> ModelInfo:
    """一条远端条目 → `ModelInfo`（逐字段取用范围见模块头）。

    `reasoning` 三态：`support_thinking=false` → `False`（明确不支持）；
    声明了思考或给了档位 → `True`；两者都没有 → `None`（**未取到**，不当作 False）。
    `effort_levels` 只在**真能声明出档位**时给（`protocol.declares_reasoning` 判据，
    与 DSH 的 `declaresReasoningOptions` 同款：空档位不得冒充有档位）。
    `free` / `rate`（2026-10-01 补）见 `_billing_of`。
    """
    if entry.support_thinking is False:
        reasoning: bool | None = False
    elif entry.support_thinking is True or entry.reasoning_options:
        reasoning = True
    else:
        reasoning = None
    free, rate = _billing_of(entry)
    return ModelInfo(
        id=entry.id,
        name=entry.name,
        vendor="",
        context_window=entry.context_window,
        max_output=entry.max_output,
        tool_call=None,
        image_input=entry.multimodal,
        reasoning=reasoning,
        effort_levels=entry.reasoning_options if protocol.declares_reasoning(entry) else (),
        free=free,
        rate=rate,
    )


#: 目录响应 → `ModelInfo` 列表的**唯一**调用点 = `fetch_models`（内联在它里面，
#: 因为解析结果还要过 `remember_channels` 去喂通道缓存 —— 单一来源，不另开包装函数）。
#: [guard-fix 2026-09-30] 原先此处还有一个 `parse_models(body)` 包装函数：全仓零调用方
#: （grep 证实；`fetch_models` 自己 parse 一次即可），按 §20 反过度设计删除。


# ── 模型 → 通道（出站请求体的 `function`；`trae-adapter.ts:656-661`）──
#
# 🔴 **映射表只有一份**：数据面 = 产品目录（远端 batch 的每条 `function`）。
#    出站适配器**不另写**任何通道表；它只调 `channel_for(model)` 取值。
#    缓存随最近一次成功目录刷新（DSH 同款：`remoteMeta` 由目录加载填充，
#    查不到回退产品默认通道 `TRAE_FUNCTION`，`trae-adapter.ts:658-661`）。

_CHANNELS: dict[str, str] = {}


def remember_channels(entries) -> None:
    """用一次成功解析的目录条目刷新「模型 → 通道」映射（进程内缓存）。"""
    for entry in entries:
        channel = str(getattr(entry, "channel", "") or "").strip()
        model_id = str(getattr(entry, "id", "") or "").strip()
        if model_id and channel:
            _CHANNELS[model_id] = channel


def channel_for(model: str) -> str:
    """该模型所属通道（`channelFor`，`trae-adapter.ts:658-661`）。

    ⚠️ **模型只在列出它的通道里可调用**：发错通道上游回流内
    `code=4001 param is invalid`（实测 `glm-5.1` 在 `solo_work_lite` 报错、
    在 `solo_agent_remote` 正常；`glm-5-turbo` 恰好相反，`trae-adapter.ts:650-657`）。
    目录**尚未加载**（或该模型不在缓存里）→ 回退默认通道 `const.FUNCTION`
    （DSH 同款回退）——**不编造**，也不让请求直接失败。
    """
    return _CHANNELS.get(str(model or "").strip()) or const.FUNCTION


def reset_channels_for_tests() -> None:
    """测试注入：清空通道缓存（生产不调用；用例间不得留痕）。"""
    _CHANNELS.clear()


def fallback_models() -> list[ModelInfo]:
    """本地兜底目录（28 条；4 条上游隐藏条目按 `is_invisible_to_user` 同判据剔除）。"""
    return [
        ModelInfo(id=model_id, name=name, context_window=context_window)
        for model_id, name, context_window, hidden in const.FALLBACK_MODELS
        if not hidden
    ]


async def fetch_models(cred: dict, meta: dict) -> list[ModelInfo]:
    """远端目录（**失败/未登录 → 空表**，由调用方回退兜底表）。

    ⚠️ 请求头是 SOLO 族（`traeSOLOHeaders`，`trae-auth.ts:695`）：`X-Uid` 取凭据 uid、
    `X-Machine-Id`/`X-Device-Id` 取设备字段（登录时写入 meta，缺则不发该头）。
    设备字段**以 `meta` 为正式通道**（§22.3 ③）—— 导入的账号凭据里未必带设备字段，
    但 `meta.json` 里有（导入面按 §22.2 落那里）；凭据里的同名字段作为兜底（登录路径双写）。
    未登录（无 `access_token`）**不发请求** —— 打出去必然 401，徒增风控可见性。

    成功解析后**顺带缓存模型 → 通道**（`remember_channels`）：出站请求体里的
    `function` 必须与该模型所属通道一致（`trae-adapter.ts:656-661` 的 `channelFor`）。
    """
    if not protocol.read_str(cred, "access_token"):
        return []
    headers_input = dict(cred)
    if isinstance(meta, dict):
        for key in ("machine_id", "login_device_id", "device_id"):
            value = meta.get(key)
            if isinstance(value, str) and value and not headers_input.get(key):
                headers_input[key] = value
    try:
        async with net.make_client(timeout=const.REQUEST_TIMEOUT_S) as client:
            response = await client.post(
                f"{const.AGENT_HOST}{const.PATH_BATCH_MODELS}",
                headers=protocol.solo_headers(headers_input, stream=False),
                json=protocol.models_body())
    except httpx.HTTPError as e:
        logger.warning("[trae] 模型目录远端不可用（回退兜底表）：%s", e)
        return []
    if response.status_code != 200:
        # 非 2xx 是真实故障（凭据失效 / 上游异常）—— 如实记录一次（`trae-auth.ts:700-703`）
        logger.warning("[trae] 模型目录 HTTP %s（回退兜底表）", response.status_code)
        return []
    try:
        body = response.json()
    except ValueError:
        logger.warning("[trae] 模型目录响应不是 JSON（回退兜底表）")
        return []
    entries = protocol.parse_batch_models(body)
    remember_channels(entries)
    models = [_model_info(entry) for entry in entries]
    if not models:
        logger.warning("[trae] batch_get_detail_param 未解析出模型（回退兜底表）")
    return models


async def list_models(cred: dict, meta: dict) -> list[ModelInfo]:
    """产品模型目录：远端优先，**取不到整体回退**兜底表（§22.5-4）。"""
    remote = await fetch_models(cred, meta)
    return remote if remote else fallback_models()
