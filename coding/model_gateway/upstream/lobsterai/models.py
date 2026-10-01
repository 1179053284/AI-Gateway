"""LobsterAI 模型目录：远端 `GET /api/models/available` + 本地兜底表（§22.5-4 / `21 §1.1`）。

两条纪律：

① **远端优先、空则兜底**（照抄 `lobsterai-auth.ts:688-713`）：远端失败/未登录 → 空表 →
   调用方回退 `fallback_models()`。DSH 的适配器对「空表」正是这样处理的。
② **取不到不编造**（`21 §5.1-1`）：远端没给的字段一律 `None`（序列化时不写），
   不拿估计值充数 —— 编造偏大值会被上游 400。

⚠️ 与 DSH 兜底表的一处**有意分歧**：DSH 的 `LOBSTERAI_FALLBACK_MODELS` 每条带
   `contextWindow: 131072`，其源注释明确写着这是**桥接层的本地估计值、非远端权威**
   （全部 19 条统一填 131072，实测远端多数模型返回 `1000000`，见 `lobsterai-product.ts:40-53`）。
   本项目规则是「取不到不编造」，故兜底表**只保留 id/name**、`context_window` 留 `None`
   （远端可用时才有权威值）。这不会丢信息：远端成功时 `contextWindow` 照收。
"""

from __future__ import annotations

from urllib.parse import urlencode

from model_gateway.accounts.types import ModelInfo
from model_gateway.upstream.lobsterai import const, protocol

#: 兜底模型目录（19 条；顺序**照抄原表**不重排，`lobsterai-product.ts:183-203`——
#: 那是实测时的返回顺序，重排会让「与上游对比」失去可比性）。
#: 来源：`lobsterai2api/internal/server/handler.go:94-114` 的 `staticModels`
#: （注释标明「2026-08-06 从 `GET /api/models/available` 实测拉取」）。
FALLBACK_MODELS: tuple[tuple[str, str], ...] = (
    ("deepseek-v4-flash", "deepseek-v4-flash"),
    ("deepseek-v4-pro", "deepseek-v4-pro"),
    ("MiniMax-M3", "MiniMax-M3"),
    ("MiniMax-M2.7", "MiniMax-M2.7"),
    ("qwen3.7-max", "qwen3.7-max"),
    ("qwen3.7-plus", "qwen3.7-plus"),
    ("qwen3.6-plus", "qwen3.6-plus"),
    ("qwen3.5-plus-2026-04-20", "qwen3.5-plus-2026-04-20"),
    ("kimi-k2.7-code", "kimi-k2.7-code"),
    ("kimi-k2.7-code-highspeed", "kimi-k2.7-code-highspeed"),
    ("kimi-k2.6", "kimi-k2.6"),
    ("kimi-k2.5", "kimi-k2.5"),
    ("doubao-seed-2-1-pro-260628", "doubao-seed-2-1-pro-260628"),
    ("doubao-seed-2-1-turbo-260628", "doubao-seed-2-1-turbo-260628"),
    ("doubao-seed-2-0-code-preview-260215", "doubao-seed-2-0-code-preview-260215"),
    ("glm-5.2", "glm-5.2"),
    ("glm-5.1", "glm-5.1"),
    ("glm-5v-turbo", "glm-5v-turbo"),
    ("glm-5", "glm-5"),
)

#: 产品侧思考档位名的合法取值（远端 `level` 字段，`lobsterai-adapter.ts:174`）——
#: 与 tech-design §13.1 的**规范 7 档序**逐字一致（`off < minimal < low < medium < high < xhigh < max`）。
_LEVELS = frozenset({"off", "minimal", "low", "medium", "high", "xhigh", "max"})
#: wire 侧档位（远端 `openclawLevel`，**无 `max`**，`lobsterai-adapter.ts:176`）。
_WIRE_LEVELS = frozenset({"off", "minimal", "low", "medium", "high", "xhigh"})


def _thinking_levels(config: object) -> tuple[str, ...]:
    """从 `thinkingConfig` 提取可选思考档位（校验照抄 `lobsterai-adapter.ts:190-216`）。

    严格性照抄（**丢弃而不是解析出半截**）：`options` 必须是非空数组、每项都有合法
    `level` 与 `openclawLevel`、两者「是否 off」必须一致、不许重复、`defaultLevel`
    必须落在 options 里。只有 `off` 一档 → 视为无档位可选（返回空）。
    """
    if not isinstance(config, dict):
        return ()
    options = config.get("options")
    if not isinstance(options, list) or not options:
        return ()
    levels: list[str] = []
    wire_seen: set[str] = set()
    for entry in options:
        if not isinstance(entry, dict):
            return ()
        level = protocol.read_str(entry, "level")
        wire = protocol.read_str(entry, "openclawLevel")
        if level not in _LEVELS or wire not in _WIRE_LEVELS:
            return ()
        if level in levels or wire in wire_seen:
            return ()
        if (level == "off") != (wire == "off"):
            return ()
        levels.append(level)
        wire_seen.add(wire)
    if levels == ["off"]:
        return ()
    if protocol.read_str(config, "defaultLevel") not in levels:
        return ()
    return tuple(levels)


def _rate_text(value: float) -> str:
    """倍率数字 → 展示文本 `x{number}`，**最短数字形态**（无尾随 0）。

    `lobsterai-adapter.ts:286` 的 `costMultiplier` 是裸数字（实测 `0.05` / `1.08` / `20`）；
    本地不存在现成格式化器（其余产品各有各的形态），故此处自写：
    `0.05` → `x0.05`、`20` → `x20`、`0` → `x0`（免费；`free=True` 才是权威信号）。
    """
    number = f"{value:.10f}".rstrip("0").rstrip(".")
    return f"x{number or '0'}"


def _model_info(record: dict) -> ModelInfo | None:
    """一条远端模型 → `ModelInfo`（`lobsterai-adapter.ts:258-292` 的字段取用范围）。

    - `modelId` 必需（缺 → 丢弃该条），`modelName` 缺省回退 id；
    - `provider` / `apiFormat` / `runtimeProfile` **刻意不取**：前两者是上游内部字段，
      后者是 IDE 内置 agent 内核的编排概念，对 OpenAI 兼容转发没有意义
      （`lobsterai-adapter.ts:252-254`）；
    - `vendor` 留空：远端没有「vendored by」语义的字段，**不编造**；
    - `tool_call` 留 `None`（远端未声明该维度）；
    - `free` / `rate`（2026-10-01 补）= `costMultiplier`（**裸数字**，`:286` 的取用注释：
      「只在为正数时带上（0 在业务上无意义）」→ 本层把 0 如实结构化：`free=True`）；
      缺失/非法 → `None` / `""`（**未取到，不编造**）。
    """
    model_id = protocol.read_str(record, "modelId")
    if not model_id:
        return None
    context = protocol.read_num(record, "contextWindow")
    max_output = protocol.read_num(record, "maxTokens")
    image_input = record.get("supportsImage")
    reasoning = record.get("supportsThinking")
    multiplier = protocol.read_num(record, "costMultiplier")
    if multiplier is not None and multiplier >= 0:
        free: bool | None = multiplier == 0
        rate = _rate_text(multiplier)
    else:
        # 缺失 / 负数（上游不该出现）→ 未取到，不编造倍率
        free, rate = None, ""
    return ModelInfo(
        id=model_id,
        name=protocol.read_str(record, "modelName") or model_id,
        context_window=int(context) if context is not None and context > 0 else None,
        max_output=int(max_output) if max_output is not None and max_output > 0 else None,
        tool_call=None,
        image_input=image_input if isinstance(image_input, bool) else None,
        reasoning=reasoning if isinstance(reasoning, bool) else None,
        effort_levels=_thinking_levels(record.get("thinkingConfig")),
        free=free,
        rate=rate,
    )


def _model_array(body: dict) -> list:
    """取出模型数组，兼容上游**两种**形状（`lobsterai-adapter.ts:218-247`）。

    - **单层**（2026-09-17 实测的真实形态）：`{code:0, message:'success', data:[{modelId,…}]}`；
    - **双层**（`internal/upstream/client.go:254-278` 记录的形态）：`{code:0, msg:'OK', data:{data:[…]}}`。

    ⚠️ **刻意不复用 `parse_envelope`**：那个信封要求 `data` 必须是对象（用于把「凭据失效
    返回 `data:null`」判成失败），而本端点的真实 `data` 恰是**数组**。复用会让信封恒定
    失败 → 整个模型列表恒空 → 静默回退兜底表，症状是「远端已上线的新模型看不到且不报错」。
    """
    data = body.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        nested = data.get("data")
        if isinstance(nested, list):
            return nested
    return []


def parse_models(body: object) -> list[ModelInfo]:
    """解析 `GET /api/models/available` 的响应（`code != 0` 或结构不符 → 空表）。"""
    if not isinstance(body, dict):
        return []
    code = protocol.read_num(body, "code")
    if code is None or int(code) != 0:
        return []
    out: list[ModelInfo] = []
    for item in _model_array(body):
        if not isinstance(item, dict):
            continue
        info = _model_info(item)
        if info is not None:
            out.append(info)
    return out


def fallback_models() -> list[ModelInfo]:
    """本地兜底目录（远端不可用时用；`context_window` 留 `None`，见模块头 ⚠️）。"""
    return [ModelInfo(id=model_id, name=name) for model_id, name in FALLBACK_MODELS]


async def fetch_models(cred: dict, client_version: str) -> list[ModelInfo]:
    """远端模型列表；**失败/未登录 → 空表**（由调用方回退兜底表）。

    🔴 两处都不能省（`lobsterai-auth.ts:688-713` 的实测结论）：
    - query 是**身份载荷**（keyfrom）—— 发错身份会让服务端返回错误的模型集合；
    - `X-LobsterAI-Client-Capabilities` 决定 `kimi-k3` 是否在返回里（25 vs 26 个）。
    """
    if not protocol.read_str(cred, "access_token"):
        return []
    query = urlencode(protocol.keyfrom_query(cred, client_version))
    url = f"{const.API_BASE}{const.PATH_MODELS}" + (f"?{query}" if query else "")
    result = await protocol.fetch_json(url, headers=protocol.client_headers(cred, client_version))
    if not result.reachable or not 200 <= result.status < 300 or not isinstance(result.body, dict):
        return []
    return parse_models(result.body)
