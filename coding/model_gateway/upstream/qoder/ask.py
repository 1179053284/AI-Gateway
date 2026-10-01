"""Qoder 加密推理端点的**明文请求构造**（`agent_chat_generation`；M6-5c）。

🔴 **本模块只造明文**（`buildQoderInferPayload` 的 Python 移植）——**加密与
   COSY 签名不在这里**，也不在 Python 任何地方（见 `out.py` 的 `SIGNER_FACTORY` 注入缝）。

取证（DSH `deepseek-harness-codearts/src/`）：

| 本模块 | DSH 对应 | 行号 |
|---|---|---|
| `build_infer_payload` | `buildQoderInferPayload` | `qoder-wasm.ts:245-326` |
| `history_of` | `buildQoderHistory` + `qoderContentText`/`qoderContentParts` | `qoder-adapter.ts:234-362` |
| `tools_of` | `buildQoderTools` | `qoder-adapter.ts:211-223` |
| `last_user_text` | `stream()` 的 userText 取法 | `qoder-adapter.ts:675-688` |

三条**实测结论**必须保留（改动前先读注释）：

1. `business` **必填**（`{"type": "agent"}`）：不带它时 `qfmodel` 恒被路由到故障节点
   → `[FAIL]node:... msg:Execution failed`（`qoder-adapter.ts:726-736` 的实测记录）；
2. `chat_context.extra.modelConfig.key` = **目录 key**（`qfmodel`/`dmodel`…）；
   该端点**只认目录 key**，公开端点只认通用名（发错回 `Unsupported model`）；
3. `tools` 是**顶层数组**（缺省 `[]`，键恒在）：不下发时模型只能用正文 XML 臆造
   工具调用（`qoder-wasm.ts:217-227`、`qoder-adapter.ts:693-696`）。
"""

from __future__ import annotations

import uuid
from typing import Any

#: 加密端点固定字段（`buildQoderInferPayload` 返回体的常量部分）。
AGENT_ID = "agent_common"
TASK_ID = "common"
PROTOCOL_VERSION = "3"
SOURCE_DEFAULT = "system"
FORMAT_DEFAULT = "openai"
#: `business` 取值（**必填**；`qoder-adapter.ts:736` 用的是 `{"type": "agent"}`，
#: 源码依据 `MPi(A)`：`sec_scan` → security 池，其余 → 默认池）。
BUSINESS_AGENT: dict[str, str] = {"type": "agent"}
#: `session_type` 缺省：国际版 = `qodercli`（`qoder-wasm.ts:196-202` 的 `swe`）。
#: ⚠️ CN 源码分支是 `qoder_work`（`l7A`），但 DSH 的适配器**对两站都不覆盖**
#: （`ask.sessionType ?? 'qodercli'`）→ 本层同样只发缺省值；CN 是否需改待实测（登记缺口）。
SESSION_TYPE_DEFAULT = "qodercli"
#: `contextWindow` 缺失时的 `model_config.max_input_tokens` 兜底（`qoder-wasm.ts:311`）。
DEFAULT_MAX_INPUT_TOKENS = 200_000


def content_text(content: Any) -> str:
    """消息 content → 字符串（`qoderContentText`，`qoder-adapter.ts:234-246`）。

    字符串原样；数组取 `type=="text"` 块拼接；`null`/畸形 → 空串。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return ""


def content_parts(content: Any) -> list[dict] | None:
    """含图消息 → **多模态 parts**（`qoderContentParts`，`qoder-adapter.ts:276-309`）。

    ⚠️ 图片的正确通道是 `messages[].content` 的多模态数组（**不是**
    `chat_context.imageUrls` —— 官方实现把那个字段恒置 `null`）；无图 → `None`
    （调用方继续用字符串形态，保持与既有请求逐字节一致）。
    """
    if not isinstance(content, list):
        return None
    parts: list[dict] = []
    has_image = False
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = str(block.get("text") or "")
            if text:
                parts.append({"type": "text", "text": text})
        elif btype == "image_url":
            iu = block.get("image_url")
            url = iu.get("url") if isinstance(iu, dict) else None
            if not (isinstance(url, str) and url):
                continue
            item: dict[str, Any] = {"url": url}
            detail = iu.get("detail") if isinstance(iu, dict) else None
            if isinstance(detail, str) and detail:
                item["detail"] = detail
            parts.append({"type": "image_url", "image_url": item})
            has_image = True
    return parts if has_image else None


def history_of(messages: Any) -> list[dict]:
    """wire 消息 → 加密端点的 `messages[]`（`buildQoderHistory`，`qoder-adapter.ts:332-362`）。

    🔴 **必须保留** assistant 的 `tool_calls` 与 `tool` 消息的 `tool_call_id`：
    早期实现「只留 content 为字符串的消息」会让**多步工具调用彻底坏掉**
    （模型看不到自己调用过什么，只能反复重调或编造结果）。
    三者皆空的消息跳过（不发出「空 assistant」）。
    """
    out: list[dict] = []
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict) or not isinstance(message.get("role"), str):
            continue
        parts = content_parts(message.get("content"))
        content: Any = parts if parts is not None else content_text(message.get("content"))
        tool_calls = message.get("tool_calls")
        tool_calls = tool_calls if (isinstance(tool_calls, list) and tool_calls) else None
        tool_call_id = message.get("tool_call_id")
        tool_call_id = tool_call_id if isinstance(tool_call_id, str) else None
        is_empty = len(content) == 0
        if is_empty and tool_calls is None and tool_call_id is None:
            continue
        item: dict[str, Any] = {"role": message["role"], "content": content}
        if tool_calls is not None:
            item["tool_calls"] = tool_calls
        if tool_call_id is not None:
            item["tool_call_id"] = tool_call_id
        out.append(item)
    return out


def tools_of(tools: Any) -> list[dict]:
    """OpenAI `tools` → 顶层 `tools`（`buildQoderTools`，`qoder-adapter.ts:211-223`）。

    形态：`{type:'function', function:{name, description?, parameters?}}`；
    `description` / `parameters` 缺省时**该键不出现**（不填空串/空对象）。无工具 → `[]`。
    """
    out: list[dict] = []
    for tool in tools if isinstance(tools, list) else []:
        if not isinstance(tool, dict):
            continue
        fn = tool.get("function") if tool.get("type") == "function" else tool
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "")
        if not name:
            continue
        entry: dict[str, Any] = {"name": name}
        description = fn.get("description")
        if isinstance(description, str) and description:
            entry["description"] = description
        parameters = fn.get("parameters")
        if parameters is not None:
            entry["parameters"] = parameters
        out.append({"type": "function", "function": entry})
    return out


def last_user_text(body: dict) -> str:
    """本轮提问文本 = 最后一条 user 消息（`qoder-adapter.ts:675-688`）。

    ⚠️ 带图消息的 `content` 是多模态数组 —— 只判 `isinstance(str)` 会让
    `chat_context.text` 退化成空串（模型收到「一张没有配文的图」）。
    """
    text = ""
    for message in body.get("messages") if isinstance(body.get("messages"), list) else []:
        if isinstance(message, dict) and message.get("role") == "user":
            value = message.get("content")
            text = content_text(value) if not isinstance(value, str) else value
    return text


def build_infer_payload(body: dict, vendor_model: str, *, is_reasoning: bool = False,
                        is_vl: bool = True, display_name: str = "",
                        max_input_tokens: int | None = None,
                        session_type: str = SESSION_TYPE_DEFAULT,
                        request_id: str | None = None) -> dict:
    """构造 `agent_chat_generation` 的**明文请求体**（`buildQoderInferPayload` 的移植）。

    `vendor_model` = **目录 key**（`qfmodel` / `dmodel` …；§22.4「加密端点认目录 key」）。
    `request_id` 可注入（测试求确定性）；`session_id` 恒随机（与 DSH 一致）。
    """
    rid = request_id or str(uuid.uuid4())
    text = last_user_text(body)
    messages = history_of(body.get("messages"))
    if not messages:
        messages = [{"role": "user", "content": text}]
    system_text = body.get("system")
    context_window = max_input_tokens or DEFAULT_MAX_INPUT_TOKENS

    parameters: dict[str, Any] = {}
    max_tokens = body.get("max_tokens") or body.get("max_completion_tokens")
    if isinstance(max_tokens, int) and not isinstance(max_tokens, bool):
        parameters["max_tokens"] = max_tokens
    effort = body.get("reasoning_effort")
    if isinstance(effort, str) and effort:
        parameters["reasoning_effort"] = effort
        parameters["enable_thinking"] = effort != "none"

    return {
        "request_id": rid,
        "request_set_id": rid,
        "chat_record_id": rid,
        "session_id": str(uuid.uuid4()),
        "stream": True,
        "chat_task": "FREE_INPUT",
        "chat_context": {
            "text": text,
            "features": [],
            "extra": {
                "context": [],
                "modelConfig": {"key": vendor_model, "is_reasoning": is_reasoning},
                "originalContent": text,
            },
            "chatPrompt": "",
            # ⚠️ 恒 null：官方 `Hyc()` 就是这么写的（图片走 messages[].content）
            "imageUrls": None,
        },
        "is_reply": True,
        "is_retry": False,
        "source": 1,
        "version": PROTOCOL_VERSION,
        "agent_id": AGENT_ID,
        "task_id": TASK_ID,
        "session_type": session_type,
        "aliyun_user_type": "",
        "model_config": {
            "key": vendor_model,
            "display_name": display_name or "",
            "model": "",
            "format": FORMAT_DEFAULT,
            "is_vl": is_vl,
            "is_reasoning": is_reasoning,
            "api_key": "",
            "url": "",
            "source": SOURCE_DEFAULT,
            "max_input_tokens": context_window,
        },
        "custom_model": None,
        "system": ([{"type": "text", "text": system_text}]
                   if isinstance(system_text, str) and system_text else []),
        "messages": messages,
        "tools": tools_of(body.get("tools")),
        "parameters": parameters,
        "business": dict(BUSINESS_AGENT),
    }
