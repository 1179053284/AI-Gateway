"""Loomy 模型目录：远端 `/api/v1/models` + 8 条兜底表。

🗂 证据面（只读）：DSH `src/loomy-adapter.ts:138-172`（远端解析）、`:174-189`（兜底表转形）、
   `src/loomy.ts:106-160`（倍率拆分与展示名规范化）、`src/index.ts:832-849`（拉取与失败回退）。

⚠️ **拉取端点只认 `token` 头**（业务端点），带 `Authorization: Bearer` 会得到
   `100002 缺少 token`，表现为「模型列表永远停在兜底表」（`index.ts:830-833` 的真实缺陷复盘）。
⚠️ chat 端点相反（只认 Bearer）—— 那条链路归 M6-5 的出站适配器，不在本模块。

## 兜底策略（`loomy-adapter.ts:258-275`）

远端可用 → 用远端（其 `name` 经倍率规范化）；远端整体失败 / 返回空 → 用兜底表（8 条，
`loomy-product.ts:104-113`）。**取不到不编造**（`21 §5.1-1`）：兜底表没有的字段一律 `None`，
不写 `False`（`False` = 明确不支持，与「未取到」语义不同，见 `accounts/types.py::ModelInfo`）。
"""

from __future__ import annotations

import logging
import re

import httpx

from model_gateway.accounts.types import ModelInfo
from model_gateway.upstream.loomy import api
from model_gateway.upstream.loomy import constants as C

logger = logging.getLogger("model_gateway.accounts")

#: 倍率形态 1：末尾括号（全角/半角都认，括号前后空格可有可无；`loomy.ts:130`。
#: 实测三种风格混用：`MiniMax M3 （x4.0）` / `Qwen 3.8 Max (x12.0)` / `GLM 5.3 Flash(x0.8)`）。
_BRACKETED_RATE = re.compile(r"^(.*?)\s*[（(]\s*(x\s*[\d.]+)\s*[)）]\s*$", re.IGNORECASE)
#: 倍率形态 2：已规范化的 `{name} · x1.0`（`loomy.ts:140`）——兜底表存的就是这个形态，
#: **必须支持**，否则兜底表的名字无法去掉倍率。
_NORMALIZED_RATE = re.compile(r"^(.*?)\s*·\s*(x\s*[\d.]+)\s*$", re.IGNORECASE)


def split_rate(raw_name: str) -> tuple[str, str]:
    """从展示名抽出倍率（`loomy.ts:125-148`）。

    ⚠️ 本函数**幂等**：`split_rate(display_name(x)) == split_rate(x)`（`loomy.ts:118-121`；
       DSH 单测锁死了这一点）。只认**末尾**的倍率（中间的括号属于模型名本身）。
    返回 `(name, rate)`，`rate` 为空串表示该模型无倍率（如生图模型）。
    """
    original = raw_name.strip() if isinstance(raw_name, str) else ""
    if not original:
        return "", ""
    for pattern in (_BRACKETED_RATE, _NORMALIZED_RATE):
        found = pattern.match(original)
        if found is None:
            continue
        name = found.group(1).strip()
        rate = re.sub(r"\s+", "", found.group(2)).lower()
        # 主体为空说明整个 name 就是个括号（畸形数据）：原样保留，不产出空名字。
        if name:
            return name, rate
        return original, ""
    return original, ""


def display_name(raw_name: str) -> str:
    """最终展示名：`MiniMax M3 · x4.0`（`loomy.ts:150-160`）。

    ⚠️ 倍率必须拼进 `name`（**不是** `description`）：DSH 的模型切换菜单只渲染 `name`
       （`loomy.ts:152-155`）；无倍率时不追加分隔符，避免出现「模型名 · 」这种孤立分隔符。
    """
    name, rate = split_rate(raw_name)
    return f"{name} · {rate}" if rate else name


def free_of_rate(rate: str) -> bool | None:
    """`rate` 文本 → `free` 三态（`loomy.ts:125-148` 的倍率数字部分）。

    - 无倍率（空串）→ `None`（**未取到**，不当作计费）；
    - 倍率解析为 0（如 `x0.0`）→ `True`（免费）；
    - 其余 → `False`（有计费）。
    ⚠️ 解析不出数字时回 `None` 而不是 `False` —— 「取不到」与「明确有计费」语义不同
       （`accounts/types.py::ModelInfo` 的告示）。
    """
    if not rate:
        return None
    try:
        return float(rate[1:]) == 0
    except ValueError:
        return None


def _is_chat_model(entry: object) -> bool:
    """是否为可对话的 chat 模型（`loomy.ts:162-174`）。

    ⚠️ 判据是 `type === 'chat'`。**不要**改用 `output_modalities` —— 实测 5 个 chat 模型的
       `input_modalities` 含 `image`（能看图），那是输入多模态，与「是不是生图模型」无关。
    """
    if not isinstance(entry, dict):
        return False
    entry_id = entry.get("id")
    return isinstance(entry_id, str) and bool(entry_id.strip()) and entry.get("type") == "chat"


def _read_efforts(entry: dict) -> tuple[str, ...]:
    """把 `reasoning_efforts` 读成去重后的元组（非法项丢弃；`loomy-adapter.ts:107-120`）。"""
    raw = entry.get("reasoning_efforts")
    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item and item not in out:
            out.append(item)
    return tuple(out)


def _read_input_modalities(entry: dict) -> list[str] | None:
    """读 `capabilities.input_modalities`（小写化）；**缺字段返回 None**（= 未取到）。

    返回 `None` 而不是空列表：`ModelInfo.image_input` 的 `None`（未取到）与 `False`
    （明确不支持）语义不同（`accounts/types.py::ModelInfo` 的告示）。
    """
    capabilities = entry.get("capabilities")
    if not isinstance(capabilities, dict) or "input_modalities" not in capabilities:
        return None
    raw = capabilities.get("input_modalities")
    if not isinstance(raw, list):
        return None
    return [item.lower() for item in raw if isinstance(item, str)]


def _read_reasoning(entry: dict) -> bool | None:
    """读 `capabilities.reasoning` → `reasoning`（`loomy-adapter.ts:162` 的 `supportsThinking`）。

    字段缺失 → `None`（未取到）；存在 → `is True`（照 DSH：`capabilities.reasoning === true`）。
    """
    capabilities = entry.get("capabilities")
    if not isinstance(capabilities, dict) or "reasoning" not in capabilities:
        return None
    return capabilities.get("reasoning") is True


def parse_remote_models(payload: object) -> list[ModelInfo]:
    """解析远端 `GET /models` 响应，只保留 `type === 'chat'` 的条目（`loomy-adapter.ts:138-172`）。

    接受**裸数组**与 `{data: [...]}` 两种形态（`loomy-adapter.ts:139-144`）。
    """
    if isinstance(payload, list):
        entries: list = payload
    elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
        entries = payload["data"]
    else:
        return []
    models: list[ModelInfo] = []
    for item in entries:
        if not _is_chat_model(item):
            continue
        entry = item
        model_id = str(entry.get("id")).strip()
        raw_name = entry.get("name")
        name = display_name(raw_name) if isinstance(raw_name, str) and raw_name else model_id
        # 结构化计费（2026-10-01 补）：倍率就在 `name` 字符串里（本产品无独立字段，
        # 实测搜 credit/multiplier/price/factor/rate 全部 0 命中，`loomy.ts:125-148`），
        # 故与展示名同源拆分：`split_rate` 的 rate 即展示的 `x{n}` 文本。
        rate = split_rate(raw_name)[1] if isinstance(raw_name, str) and raw_name else ""
        context = entry.get("context_length")
        context_window = int(context) if isinstance(context, (int, float)) \
            and not isinstance(context, bool) and context > 0 else None
        modalities = _read_input_modalities(entry)
        models.append(ModelInfo(
            id=model_id,
            name=name,
            #: `vendor` / `max_output` / `tool_call`：远端目录不声明 → 一律 None（取不到不编造）
            context_window=context_window,
            image_input=(("image" in modalities) if modalities is not None else None),
            reasoning=_read_reasoning(entry),
            effort_levels=_read_efforts(entry),
            free=free_of_rate(rate),
            rate=rate,
        ))
    return models


def fallback_models() -> list[ModelInfo]:
    """兜底模型目录（8 个 chat 模型；`loomy-product.ts:104-113`）。

    ⚠️ 兜底表**不声明**图片能力与思考能力（`loomy-adapter.ts:174-189` 的 `fallbackToRemote`
       只给"宁可少报"的保守值）→ 本函数把这两项留 `None`（= 未取到）。
       `effort_levels` 用实测常量 `LOOMY_EFFORTS`（`loomy-product.ts:92`）。
    ⚠️ `default_reasoning_effort`（DSH 用 `high`）**不搬运**：`ModelInfo` 冻结类型没有该字段
       （登记缺口，同 buddy 的 `defaultReasoningEffort` 口径）。
    ⚠️ 兜底表的倍率同样在 `name` 里（` · x{n}`），故 `free` / `rate` 从 `split_rate` 拆出
       （与远端路径同源；`free=True` 仅当倍率解析为 0）。
    """
    out: list[ModelInfo] = []
    for model in C.FALLBACK_MODELS:
        rate = split_rate(model.name)[1]
        out.append(ModelInfo(id=model.id, name=model.name, context_window=model.context_window,
                             effort_levels=C.LOOMY_EFFORTS,
                             free=free_of_rate(rate), rate=rate))
    return out


async def list_models(cred, meta) -> list[ModelInfo]:
    """产品模型目录（§22.5-4；**取不到不编造**，`21 §5.1-1`）。

    取不到凭据 / 远端失败 / 解析为空 → **兜底表**（`loomy-adapter.ts:258-275`：远端失败
    静默回退，「模型目录是展示信息，不该让整个 provider 报错」）。
    """
    del meta  # 形参按 §22.3 保留：本产品无设备身份、无私有文件（`20 §2.7`）
    token = api.access_token_of(cred)
    if not token:
        return fallback_models()
    try:
        status, body = await api.request("GET", C.MODELS_PATH, token=token,
                                         timeout=C.MODELS_TIMEOUT_S)
    except httpx.HTTPError as e:
        logger.warning("[loomy] 模型目录远端不可用（回退兜底表）：%s", e)
        return fallback_models()
    if status != 200:
        logger.warning("[loomy] 模型目录 HTTP %s（回退兜底表）", status)
        return fallback_models()
    remote = parse_remote_models(body)
    if not remote:
        logger.warning("[loomy] /models 未解析出 chat 模型（回退兜底表）")
        return fallback_models()
    return remote
