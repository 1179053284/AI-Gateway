"""responses_compat.py — OpenAI Responses API 兼容面（`POST /v1/responses`）。

## 为什么要有它

新一代客户端（Codex CLI、以及各家「只认 Responses」的 agent）**不发** `messages` /
`max_tokens`，而是发 `input` / `instructions` / `max_output_tokens`，并且只解析
Responses 的 SSE 事件。协议外壳不同，往里塞 Chat Completions 是塞不进的。

PRD 依据：`docs/specs/prd.md` FR-11 表 `/v1/responses` 端点（OpenAI Responses API 透传）。
实现形态与既有 `/v1/chat/completions`、`/v1/messages` 完全同构 —— **只做形状翻译，
不做任何调度决策**：选路/重试/故障切换/计费/取消/断连监视全部复用同一条
`scheduler.execute_chat` / `scheduler.stream_chat` 链。

## 协议真值来源（本文件只认这两处，不凭印象）

1. **官方类型定义**：本地 OpenAI 官方 SDK `openai@6.26.0`
   （`resources/responses/responses.d.ts`）—— 事件名、字段名、可空字段、
   item 判别式联合类型逐条对齐；
2. **同类本地网关的成熟实现**（只读参考，未直接采用其代码）
   `deepseek-harness-codearts/src/openai-gateway/responses.ts`：其文件头与 43 条
   契约测试钉住了一批真实事故（见下「已吸收的教训」）。

## 三档字段处置（本文件最重要的口径，改之前先读）

**① 能 1:1 表达 → 忠实翻译**：`instructions` / `input` / `tools(function)` /
`tool_choice` / `temperature` / `top_p` / `max_output_tokens` / `parallel_tool_calls` /
`reasoning.effort` / `text.format`（→ chat `response_format`）。

**② 纯提示、遥测、缓存类 → 接受并忽略**（`store: false` / `include` / `prompt_cache_key` /
`prompt_cache_retention` / `prompt_cache_options` / `service_tier` / `safety_identifier` /
`metadata` / `user` / `truncation` / `max_tool_calls` / `stream_options` /
`context_management`）。理由是它们**不改变本次拿到的内容语义**，而转发给异构上游只会
多换一个 400；忽略不掉任何用户可感知的东西。

🔴 **③ 语义会变又做不到的 → 明确 400，绝不静默忽略**（`previous_response_id` /
`conversation` / `background: true` / **`store: true`** / `input_file` /
`input_image.file_id` / 未知 input item 类型）。「用户以为设置生效了」的失败是本项目明令禁止的
（AGENTS 铁律 5 / tech-design「消灭无报错的失败」）。错误 message 必须给出**可操作的
替代做法**，而不是只说「不支持」。

## 无状态：是需求口径，不是能力上限

PRD 写的是「**透传**」；`store` 为 true 也不能存储（`GET /v1/responses/{id}` 一律 404，
`store` 恒回 false）。真要做服务端会话库在结构上可行（本地明文 JSON + 保留策略），
但那是**新存储层的独立立项**，本轮不做 —— 登记在交付台账「可做未做」清单里。

## 工具：能表达的就摊平，表达不了的就丢弃并记日志（**不是报错**）

Codex 0.142+ 用私有 Responses 扩展声明工具：`{type:'namespace'}` 分组容器、
`{type:'custom'}` 自由文法、`{type:'tool_search'}` 延迟加载。把它们变成致命错误 =
「Codex 能不能用网关」取决于它这一版带了哪些运行时工具（参考实现的第一版就是这么
翻车的）。现在的口径：

- `namespace` 里的 function 子工具**摊平**成 `<namespace>__<child>`，响应侧再还原成
  `{name, namespace}`；
- `custom` / `tool_search` / 内置（web_search / file_search / mcp / …）→ 丢弃 +
  warning 日志 + 响应头 `X-GW-Dropped-Tools` 如实告知（不占协议字段、不污染响应体）；
- 重名**先到先得**，被丢弃者**不得进还原表**（否则上游对那个工具的调用会被静默误路由
  到另一个工具 —— 参考实现踩过的坑）。

## 已吸收的教训（逐条对应到实现点）

- **`sequence_number` 与 `event:` 名一个都不能少**：官方 SDK 按事件类型判别式解析，
  缺字段直接反序列化失败（用户看到的是「客户端崩了」）；
- **item 生命周期事件必须发全**：`output_item.added/done` 是客户端登记工具调用与
  文本项的依据，只发 delta 会让工具调用永远收不了尾；
- **`item_id` 必须稳定**：同一项的每个 delta 共用一个 id（逐帧随机 = 客户端对不上账）；
- **`usage.input_tokens` 含缓存命中**（官方口径），命中量单列
  `input_tokens_details.cached_tokens`；`total_tokens` 取 `max(上游报的, 输入+输出)`；
- **无 `[DONE]`**：那是 Chat Completions 的收尾约定，Responses 以
  `response.completed` / `response.failed` 结束；
- **延迟提交（§6）不许破**：首内容事件前零字节，窗口耗尽回非 200 JSON ——
  绝不「先 200 再 error」；
- **连续 assistant 项必须合并**：Responses 把「助手说话」与「助手发起工具调用」拆成
  两个 item，chat 放在同一条消息里；不合并会给上游留下两条连续 assistant
  （经 anthropic 协议资源出站时会被拒或行为异常）。

## 已知边界（诚实登记，未实现即未实现）

- 历史 `reasoning` 条目**丢弃**：它承载的是上游自家加密的思考内容
  （`encrypted_content`），网关没有解密通道也没有可回放的等价物；不影响轮次正确性；
- 内置工具（web_search / file_search / mcp / computer_use / code_interpreter / …）
  **不执行**，按上面的口径丢弃并上报；
- `input_file`（PDF/文件输入）**不翻译** → 400：chat 协议无对应内容块，
  静默丢文件会让模型在没有文档的情况下照常作答。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from model_gateway.api.openai_compat import (
    _endpoint_type_error,
    _openai_json_error,
    _resolve_model_or_404,
    _runtime,
    _watch_disconnects,
)
from model_gateway.core.ir import IRRequest, lift_reasoning_from_body
from model_gateway.core.scheduler import ERROR_EVENT, CallCtx, GatewayError

logger = logging.getLogger("model_gateway.api.responses")

router = APIRouter()

TEXT_EVENT = "text/event-stream"

# —— 事件名（官方 SDK ResponseStreamEvent 判别式字面量）——
E_CREATED = "response.created"
E_IN_PROGRESS = "response.in_progress"
E_ITEM_ADDED = "response.output_item.added"
E_ITEM_DONE = "response.output_item.done"
E_PART_ADDED = "response.content_part.added"
E_PART_DONE = "response.content_part.done"
E_TEXT_DELTA = "response.output_text.delta"
E_TEXT_DONE = "response.output_text.done"
E_RSN_PART_ADDED = "response.reasoning_summary_part.added"
E_RSN_PART_DONE = "response.reasoning_summary_part.done"
E_RSN_DELTA = "response.reasoning_summary_text.delta"
E_RSN_DONE = "response.reasoning_summary_text.done"
E_FC_DELTA = "response.function_call_arguments.delta"
E_FC_DONE = "response.function_call_arguments.done"
E_COMPLETED = "response.completed"
E_INCOMPLETE = "response.incomplete"
E_FAILED = "response.failed"

#: 丢弃工具的上报头（非标准协议字段；本项目已有 `X-GW-URL-Valid-Hours` 同款先例）
HDR_DROPPED_TOOLS = "X-GW-Dropped-Tools"

#: Responses function 工具的 `parameters` 缺省值（合法 JSON Schema；空 `{}` 会被部分
#: 供应商拒，`{"type":"object","properties":{}}` 是各家都认的最小形状）
_EMPTY_SCHEMA = {"type": "object", "properties": {}}

#: 规范 item 前缀（官方 id 形状；客户端按前缀识别条目类型）
_PREFIX_MESSAGE = "msg_"
_PREFIX_REASONING = "rs_"
_PREFIX_FUNCTION_CALL = "fc_"


class ResponsesRequestError(Exception):
    """请求翻译失败：可读 message + OpenAI 标准错误码（**不是** 500）。"""

    def __init__(self, message: str, *, status: int = 400,
                 code: str = "invalid_request_error",
                 err_type: str = "invalid_request_error") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.err_type = err_type

    def to_body(self) -> dict:
        return {"error": {"message": self.message, "type": self.err_type, "code": self.code}}


def _unsupported(message: str) -> ResponsesRequestError:
    """「语义会变但做不到」的统一出口（与参考实现同码：unsupported_parameter）。"""
    return ResponsesRequestError(message, code="unsupported_parameter",
                                 err_type="unsupported_parameter")


# ══════════════════════════════════════════════════════════════════════════
# 请求翻译：Responses → OpenAI chat
# ══════════════════════════════════════════════════════════════════════════


def _norm_tool_name(value: Any) -> str | None:
    """工具名清洗**唯一入口**：trim，空/纯空白 → None。

    摊平、还原表、历史回放三处必须同源：口径不一致会出现「发给上游的名字与还原表的
    键对不上」⇒ 客户端收到自己从没声明过的工具名（参考实现的三口径事故）。
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def flat_tool_name(namespace: str, name: str) -> str:
    """`<namespace>__<child>`；超 64 字符截断 + 8 位哈希防长名碰撞。

    请求侧摊平与响应侧还原**只能有这一份实现**（算法不一致 = 上游按 A 名字调用、
    网关按 B 名字还原）。
    """
    flat = f"{namespace}__{name}"
    if len(flat) <= 64:
        return flat
    digest = hashlib.sha256(flat.encode("utf-8")).hexdigest()[:8]
    return f"{flat[:55]}_{digest}"


# —— input item → chat messages ——


def _content_parts_to_chat(parts: Any, *, where: str) -> tuple[str, list[dict] | None]:
    """Responses content parts → (纯文本, chat content parts | None)。

    图片（`input_image` 内联 data URL 或 http(s) URL）→ chat `image_url` part；
    `input_file` / `input_image.file_id` 无 chat 等价物 ⇒ 400（不许静默丢）。
    """
    if isinstance(parts, str):
        return parts, None
    if parts is None:
        return "", None
    if not isinstance(parts, list):
        raise ResponsesRequestError(f"{where} 的 content 必须是字符串或内容块数组")
    texts: list[str] = []
    rich: list[dict] = []
    for part in parts:
        if not isinstance(part, dict):
            raise ResponsesRequestError(f"{where} 的 content 含非法块（必须是对象）")
        ptype = part.get("type")
        if ptype in ("input_text", "output_text", "text"):
            text = part.get("text")
            if not isinstance(text, str):
                raise ResponsesRequestError(f"{where} 的 {ptype} 块缺少字符串 text")
            texts.append(text)
            rich.append({"type": "text", "text": text})
        elif ptype == "refusal":
            text = part.get("refusal")
            text = text if isinstance(text, str) else ""
            texts.append(text)
            rich.append({"type": "text", "text": text})
        elif ptype == "input_image":
            url = part.get("image_url")
            if not isinstance(url, str) or not url:
                raise _unsupported(
                    f"{where} 的 input_image 只支持内联 image_url（data URL 或 http(s) 链接）；"
                    "file_id 形态拿不到图片字节 —— 网关不静默丢图（那样模型会基于没看到的图作答）")
            rich.append({"type": "image_url", "image_url": {"url": url}})
        elif ptype == "input_file":
            raise _unsupported(
                f"{where} 含 input_file（文件输入）：chat 协议没有对应的内容块，"
                "网关无法转交文件内容 —— 请改用 input_text 提供文本，"
                "或把文件内容作为工具结果（function_call_output）回传")
        else:
            raise ResponsesRequestError(f"{where} 的内容块类型 {ptype!r} 不受支持")
    if not rich:
        return "".join(texts), None
    if all(p.get("type") == "text" for p in rich):
        return "".join(texts), None  # 全文本 → 用纯字符串形态（对上游兼容性最好）
    return "".join(texts), rich


def _push_assistant(messages: list[dict], *, text: str | None = None,
                    tool_calls: list[dict] | None = None) -> None:
    """追加/合并一条 assistant 消息（连续 assistant 项合并，见文件头）。"""
    if messages and messages[-1].get("role") == "assistant":
        last = messages[-1]
        if text:
            last["content"] = (last.get("content") or "") + text
        if tool_calls:
            last.setdefault("tool_calls", []).extend(tool_calls)
        return
    msg: dict[str, Any] = {"role": "assistant"}
    if text:
        msg["content"] = text
    else:
        msg["content"] = None
    if tool_calls:
        msg["tool_calls"] = list(tool_calls)
    messages.append(msg)


def _translate_input_items(input_items: Any, ns_map: dict[str, tuple[str, str]]) -> list[dict]:
    """ResponseItem 数组 → chat messages。"""
    if not isinstance(input_items, list):
        raise ResponsesRequestError("input 必须是字符串、或 item 数组")
    messages: list[dict] = []
    for item in input_items:
        if not isinstance(item, dict):
            raise ResponsesRequestError("input 的元素必须是对象（ResponseItem）")
        item_type = item.get("type") or "message"

        if item_type == "message":
            role = item.get("role") or "user"
            if role not in ("user", "assistant", "system", "developer"):
                raise ResponsesRequestError(f"不支持的消息角色：{role!r}")
            chat_role = "system" if role == "developer" else role
            text, rich = _content_parts_to_chat(item.get("content"),
                                                where=f"{chat_role} 消息")
            if chat_role == "assistant":
                if rich is not None:
                    raise _unsupported(
                        "assistant 消息不支持图片内容（chat 协议里 assistant 只能发文本）")
                if text:
                    _push_assistant(messages, text=text)
                continue
            if chat_role == "system":
                if rich is not None:
                    raise _unsupported(
                        "system 消息不支持图片内容（chat 协议里 system 只能发文本）")
                messages.append({"role": "system", "content": text})
                continue
            messages.append({"role": "user",
                             "content": rich if rich is not None else text})

        elif item_type == "function_call":
            call_id = item.get("call_id") or item.get("id")
            raw_name = _norm_tool_name(item.get("name"))
            if not isinstance(call_id, str) or not call_id or not raw_name:
                raise ResponsesRequestError(
                    "function_call 条目缺少 call_id 或 name")
            arguments = item.get("arguments")
            if not isinstance(arguments, str):
                raise ResponsesRequestError("function_call 条目的 arguments 必须是字符串")
            namespace = _norm_tool_name(item.get("namespace"))
            # 历史回放：工具当初是以 `ns__child` 声明给上游的，历史若还留两段，
            # 上游会认为模型调了一个从没见过的工具
            name = flat_tool_name(namespace, raw_name) if namespace else raw_name
            _push_assistant(messages, tool_calls=[{
                "id": call_id, "type": "function",
                "function": {"name": name, "arguments": arguments},
            }])

        elif item_type == "function_call_output":
            call_id = item.get("call_id")
            if not isinstance(call_id, str) or not call_id:
                raise ResponsesRequestError("function_call_output 条目缺少 call_id")
            output = item.get("output")
            if output is None:
                content: Any = ""
            elif isinstance(output, str):
                content = output
            elif isinstance(output, list):
                _text, rich = _content_parts_to_chat(output, where="function_call_output")
                content = rich if rich is not None else _text
            else:
                raise ResponsesRequestError(
                    "function_call_output 的 output 必须是字符串或内容块数组")
            messages.append({"role": "tool", "tool_call_id": call_id, "content": content})

        elif item_type == "reasoning":
            # 刻意丢弃：加密思考内容无解密通道，也没有可回放的等价物（不影响轮次正确性）
            logger.debug("[responses] 历史 reasoning 条目已丢弃（无回放通道）")
            continue

        else:
            raise _unsupported(
                f"input 条目类型 {item_type!r} 不受支持：本网关是无状态转发，"
                "既不保存历史 item（item_reference / *_call_output 之类别名），"
                "也不执行内置工具 —— 请只发送 message / function_call / "
                "function_call_output 三类条目")

    return messages


# —— tools ——


def _translate_tools(tools: Any, ns_map: dict[str, tuple[str, str]],
                     dropped: list[str], *, where: str = "tools") -> list[dict] | None:
    """Responses tools → chat tools（function 忠实翻译；namespace 摊平；其余丢弃+上报）。"""
    if tools is None:
        return None
    if not isinstance(tools, list):
        raise ResponsesRequestError(f"{where} 必须是数组")
    out: list[dict] = []
    seen: set[str] = set()

    def _add_function(fn: dict, *, label: str) -> None:
        name = _norm_tool_name(fn.get("name"))
        if not name:
            raise ResponsesRequestError(f"{label} 工具缺少非空 name")
        parameters = fn.get("parameters")
        if parameters is None:
            parameters = dict(_EMPTY_SCHEMA)
        if not isinstance(parameters, dict):
            raise ResponsesRequestError(f"{label} 工具的 parameters 必须是 JSON 对象")
        if name in seen:
            dropped.append(f"{name}（重名，先到先得）")
            logger.warning("[responses] 工具名重复，后者已丢弃：%s", name)
            return
        seen.add(name)
        chat_fn: dict[str, Any] = {
            "name": name,
            "description": fn.get("description") if isinstance(fn.get("description"), str) else "",
            "parameters": parameters,
        }
        if isinstance(fn.get("strict"), bool):
            chat_fn["strict"] = fn["strict"]  # 客户端显式声明 → 忠实转交
        out.append({"type": "function", "function": chat_fn})

    for tool in tools:
        if not isinstance(tool, dict):
            raise ResponsesRequestError(f"{where} 的元素必须是对象")
        ttype = tool.get("type")
        if ttype == "function":
            # 兼容两种形状：Responses 扁平 `{type,name,...}` 与 chat 嵌套
            # `{type,function:{...}}`（有些客户端把 chat 的 tools 原样发来）
            fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
            _add_function(fn, label="function")
        elif ttype == "namespace":
            ns = _norm_tool_name(tool.get("name"))
            if not ns:
                raise ResponsesRequestError("namespace 工具缺少非空 name")
            children = tool.get("tools")
            if not isinstance(children, list):
                raise ResponsesRequestError("namespace 工具的 tools 必须是数组")
            for child in children:
                if not isinstance(child, dict):
                    raise ResponsesRequestError("namespace 的子工具必须是对象")
                if child.get("type") != "function":
                    dropped.append(f"{ns}/{child.get('type')!r}")
                    continue
                raw = _norm_tool_name(child.get("name"))
                if not raw:
                    # 空名子工具绝不能拼成 `ns____` 幽灵工具（模型会调一个客户端
                    # 从没声明过的工具）
                    dropped.append(f"{ns}/（空名子工具）")
                    continue
                flat = flat_tool_name(ns, raw)
                before = len(out)
                _add_function({**child, "name": flat}, label=f"namespace {ns} 的")
                if len(out) > before:
                    ns_map[flat] = (ns, raw)
        else:
            # custom / tool_search / web_search / file_search / mcp / computer_use /
            # code_interpreter / image_generation / 未知或缺失 type ⇒ 丢弃 + 上报。
            # 绝不 400：把「整轮对话不可用」当成本太贵（参考实现的报障原文）。
            label = ttype if isinstance(ttype, str) else "（缺 type）"
            name = _norm_tool_name(tool.get("name"))
            dropped.append(f"{label}{f'/{name}' if name else ''}")
    return out or None


def _translate_tool_choice(tool_choice: Any) -> Any:
    """Responses tool_choice → chat tool_choice（None = 不下发）。"""
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        if tool_choice in ("auto", "none", "required"):
            return tool_choice
        raise ResponsesRequestError(
            f"tool_choice {tool_choice!r} 不受支持（可用：auto / none / required / "
            "{\"type\":\"function\",\"name\":…}）")
    if isinstance(tool_choice, dict):
        ttype = tool_choice.get("type")
        if ttype == "function":
            name = _norm_tool_name(tool_choice.get("name"))
            if not name:
                raise ResponsesRequestError("tool_choice.function 缺少非空 name")
            return {"type": "function", "function": {"name": name}}
        raise _unsupported(f"tool_choice 类型 {ttype!r} 不受支持（本网关只提供 function 工具）")
    raise ResponsesRequestError("tool_choice 必须是字符串或对象")


def _translate_text_format(text: Any) -> dict | None:
    """`text.format` → chat `response_format`（1:1 可表达，故不 400）。"""
    if text is None:
        return None
    if not isinstance(text, dict):
        raise ResponsesRequestError("text 必须是对象")
    fmt = text.get("format")
    if fmt is None:
        return None
    if not isinstance(fmt, dict):
        raise ResponsesRequestError("text.format 必须是对象")
    ftype = fmt.get("type")
    if ftype in (None, "text"):
        return {"type": "text"}
    if ftype == "json_object":
        return {"type": "json_object"}
    if ftype == "json_schema":
        schema = fmt.get("schema")
        name = fmt.get("name")
        if not isinstance(schema, dict):
            raise ResponsesRequestError("text.format.json_schema 缺少 schema 对象")
        inner: dict[str, Any] = {
            "name": name if isinstance(name, str) and name else "response",
            "schema": schema,
        }
        if isinstance(fmt.get("strict"), bool):
            inner["strict"] = fmt["strict"]
        return {"type": "json_schema", "json_schema": inner}
    raise _unsupported(
        f"text.format 类型 {ftype!r} 不受支持（可用：text / json_object / json_schema）")


# —— 顶层请求 ——


@dataclass
class ReqMeta:
    """响应里要回显的原始请求字段（官方 SDK 要求这些键**存在**，哪怕是 null）。"""

    instructions: str | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    tools_raw: list = field(default_factory=list)
    tool_choice_raw: Any = None
    parallel_tool_calls: bool = True
    reasoning_effort_raw: Any = None
    truncation: str = "disabled"
    metadata: dict = field(default_factory=dict)
    user: str | None = None
    tool_choice_effective: Any = None


@dataclass
class TranslatedRequest:
    chat_body: dict
    meta: ReqMeta
    ns_map: dict[str, tuple[str, str]] = field(default_factory=dict)
    dropped_tools: list[str] = field(default_factory=list)


#: 「接受并忽略」的字段（理由见文件头第 ② 档）。出现即记一条 debug，便于排障。
#: ⚠️ `store` 只对 `false` / 缺省生效 —— 显式 `true` 在第 ③ 档先被 400 拦掉（见 `build_chat_request`）。
_IGNORED_FIELDS = (
    "store", "include", "prompt_cache_key", "prompt_cache_retention",
    "prompt_cache_options", "service_tier", "safety_identifier", "metadata",
    "user", "truncation", "max_tool_calls", "stream_options", "context_management",
)


def build_chat_request(body: dict) -> TranslatedRequest:
    """ResponsesApiRequest → chat request（含回显元数据与工具还原表）。

    校验顺序对齐官方：明显的形状错误先报，语义做不到的其次（保证同一坏请求
    永远拿到同一条错误，便于用户排障）。
    """
    # ① 语义会变又做不到 → 明确 400 + 可操作替代做法
    if body.get("previous_response_id") is not None:
        raise _unsupported(
            "previous_response_id 不被支持：本网关是无状态转发，不保存历史响应。"
            "请把完整对话放进 input 一起发过来（会话状态由客户端自己维护）")
    if body.get("conversation") is not None:
        raise _unsupported(
            "conversation 不被支持：本网关是无状态转发，没有服务端会话库。"
            "请把完整对话放进 input 一起发过来")
    if body.get("background") is True:
        raise _unsupported("background 不被支持：本网关只做同步转发（响应即到即回）")
    if body.get("store") is True:
        # 🔴 显式 `store:true` 属「语义会变」档，**不许静默忽略**。取证（2026-10-07 官方文档调研）：
        #    同类上游的处置正好相反 —— DeepSeek 静默忽略 `store`（它自己就是上游终局，
        #    静默降级不掉任何它能给的东西）；智谱 GLM 的 `store:true` + `previous_response_id`
        #    是**真多轮**（7 天有效期）。网关两者都不是：本网关恒回 `store:false`、
        #    `GET /v1/responses/{id}` 恒 404、`previous_response_id` 一律 400，
        #    所以「接受 store:true 却什么都不存」是纯粹的静默降级 ⇒ 明确拒绝。
        raise _unsupported(
            "store: true 不被支持：本网关是无状态转发，不保存响应"
            "（响应里的 store 恒为 false，GET /v1/responses/{id} 恒 404）。"
            "需要保留上下文请在客户端保存对话并放进 input 重发；"
            "只需要「不要存」的语义请显式传 store: false")

    for key in _IGNORED_FIELDS:
        if body.get(key) is not None:
            logger.debug("[responses] 字段 %s 已接受并忽略（无状态转发）", key)

    meta = ReqMeta()
    meta.instructions = body.get("instructions") if isinstance(body.get("instructions"), str) else None
    if body.get("instructions") is not None and not isinstance(body.get("instructions"), str):
        raise ResponsesRequestError(
            "instructions 必须是字符串（数组形态的 developer 消息请直接放进 input）")

    raw_max = body.get("max_output_tokens")
    if raw_max is not None:
        if isinstance(raw_max, bool) or not isinstance(raw_max, int) or raw_max <= 0:
            raise ResponsesRequestError("max_output_tokens 必须是正整数")
        meta.max_output_tokens = raw_max

    for fld in ("temperature", "top_p"):
        value = body.get(fld)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ResponsesRequestError(f"{fld} 必须是数字")
        setattr(meta, fld, float(value))

    raw_parallel = body.get("parallel_tool_calls")
    if raw_parallel is not None and not isinstance(raw_parallel, bool):
        raise ResponsesRequestError("parallel_tool_calls 必须是布尔值")
    meta.parallel_tool_calls = True if raw_parallel is None else raw_parallel

    if isinstance(body.get("metadata"), dict):
        meta.metadata = body["metadata"]
    if isinstance(body.get("user"), str):
        meta.user = body["user"]
    if isinstance(body.get("truncation"), str):
        meta.truncation = body["truncation"]

    # ② 工具（先于 input：工具名还原表要在响应侧用）
    ns_map: dict[str, tuple[str, str]] = {}
    dropped: list[str] = []
    chat_tools = _translate_tools(body.get("tools"), ns_map, dropped)
    meta.tool_choice_raw = body.get("tool_choice")
    chat_tool_choice = _translate_tool_choice(body.get("tool_choice"))
    meta.tool_choice_effective = chat_tool_choice
    if isinstance(body.get("tools"), list):
        meta.tools_raw = body["tools"]
    if dropped:
        logger.warning("[responses] 无法用 chat 协议表达的工具已丢弃：%s", "、".join(dropped))

    # ③ input + instructions → messages
    messages: list[dict] = []
    if meta.instructions:
        messages.append({"role": "system", "content": meta.instructions})
    raw_input = body.get("input")
    if isinstance(raw_input, str):
        messages.append({"role": "user", "content": raw_input})
    elif raw_input is None:
        raise ResponsesRequestError("缺少必填字段 input（字符串或 item 数组）")
    else:
        messages.extend(_translate_input_items(raw_input, ns_map))
    if not messages:
        raise ResponsesRequestError("input 没有产出任何可用消息（input 为空数组？）")
    if not any(m.get("role") in ("user", "tool") for m in messages):
        raise ResponsesRequestError(
            "input 里没有任何 user / function_call_output 内容 —— 模型没有可回答的输入")

    chat: dict[str, Any] = {"messages": messages}
    if chat_tools:
        chat["tools"] = chat_tools
    if chat_tool_choice is not None:
        chat["tool_choice"] = chat_tool_choice
    if raw_parallel is not None:
        chat["parallel_tool_calls"] = raw_parallel
    if meta.max_output_tokens is not None:
        chat["max_tokens"] = meta.max_output_tokens
    if meta.temperature is not None:
        chat["temperature"] = meta.temperature
    if meta.top_p is not None:
        chat["top_p"] = meta.top_p

    response_format = _translate_text_format(body.get("text"))
    if response_format is not None:
        chat["response_format"] = response_format

    if body.get("stream") is True:
        # 🔴 出站体必须**显式**带 stream:true（供应商按 body 判定协议；缺失时回非流式 JSON，
        #    SSE 解析零事件 → 空流。chat 入站能带是因为客户端原样把它放在 body 里，
        #    Responses 的 stream 在顶层，翻译时必须自己落进出站体 —— 同 anthropic.py:129 的实测结论）
        chat["stream"] = True

    reasoning = body.get("reasoning")
    if reasoning is not None:
        if not isinstance(reasoning, dict):
            raise ResponsesRequestError("reasoning 必须是对象（如 {\"effort\":\"low\"}）")
        effort = reasoning.get("effort")
        if effort is not None:
            if not isinstance(effort, str) or not effort:
                raise ResponsesRequestError("reasoning.effort 必须是非空字符串")
            # 走 ir.lift 的同一口径：显式 effort 隐含开关意图，`none/off` 族
            # 由 merge_reasoning 判成显式关闭（core/ir.py:50-55）
            chat["reasoning_effort"] = effort
            meta.reasoning_effort_raw = effort
        if reasoning.get("summary") is not None:
            logger.debug("[responses] reasoning.summary 已接受并忽略（chat 无对应通道）")

    return TranslatedRequest(chat_body=chat, meta=meta, ns_map=ns_map,
                             dropped_tools=dropped)


# ══════════════════════════════════════════════════════════════════════════
# 响应组装：chat → Responses
# ══════════════════════════════════════════════════════════════════════════


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


def _restore_namespace(ns_map: dict[str, tuple[str, str]], name: str) -> tuple[str, str | None]:
    """扁平名 → `(bare_name, namespace|None)`（还原表未命中 = 原样）。"""
    hit = ns_map.get(name)
    if hit is None:
        return name, None
    return hit[1], hit[0]


def _resp_usage(usage: Any) -> dict | None:
    """chat usage → Responses usage（官方口径：input 含缓存命中）。"""
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion = usage.get("completion_tokens", usage.get("output_tokens"))
    if not isinstance(prompt, int) or isinstance(prompt, bool):
        prompt = 0
    if not isinstance(completion, int) or isinstance(completion, bool):
        completion = 0
    details_in = usage.get("prompt_tokens_details")
    details_out = usage.get("completion_tokens_details")
    cached = 0
    if isinstance(details_in, dict) and isinstance(details_in.get("cached_tokens"), int):
        cached = details_in["cached_tokens"]
    reasoning = 0
    if isinstance(details_out, dict) and isinstance(details_out.get("reasoning_tokens"), int):
        reasoning = details_out["reasoning_tokens"]
    total = usage.get("total_tokens")
    if not isinstance(total, int) or isinstance(total, bool) or total < prompt + completion:
        # 有的上游报的总数不含缓存命中 ⇒ 取大（只会多算，绝不漏算；客户端按
        # `input_tokens - cached` 反解上下文占用，少算会让自动压缩永不触发）
        total = prompt + completion
    return {
        "input_tokens": prompt,
        "input_tokens_details": {"cached_tokens": cached},
        "output_tokens": completion,
        "output_tokens_details": {"reasoning_tokens": reasoning},
        "total_tokens": total,
    }


def _message_item(item_id: str, text: str) -> dict:
    return {
        "id": item_id, "type": "message", "status": "completed", "role": "assistant",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _reasoning_item(item_id: str, text: str) -> dict:
    return {
        "id": item_id, "type": "reasoning",
        "summary": [{"type": "summary_text", "text": text}] if text else [],
    }


def _function_call_item(item_id: str, call_id: str, name: str, arguments: str,
                        namespace: str | None = None) -> dict:
    item: dict[str, Any] = {
        "id": item_id, "type": "function_call", "status": "completed",
        "call_id": call_id, "name": name, "arguments": arguments,
    }
    if namespace is not None:
        item["namespace"] = namespace
    return item


def _response_object(resp_id: str, model: str, meta: ReqMeta,
                     output: list[dict], *, status: str,
                     usage: dict | None, error: dict | None = None,
                     created_at: int | None = None) -> dict:
    """完整 response 对象。

    🔴 **可空字段一个都不能少**：官方 SDK 按 schema 解析，缺键直接反序列化失败
    （用户看到「客户端崩了」，根因只是网关少发了一个 null）。
    """
    now = created_at if created_at is not None else int(time.time())
    obj: dict[str, Any] = {
        "id": resp_id,
        "object": "response",
        "created_at": now,
        "status": status,
        "background": False,
        "error": error,
        "incomplete_details": ({"reason": "max_output_tokens"} if status == "incomplete" else None),
        "instructions": meta.instructions,
        "max_output_tokens": meta.max_output_tokens,
        "model": model,
        "output": output,
        "parallel_tool_calls": meta.parallel_tool_calls,
        "previous_response_id": None,
        "reasoning": ({"effort": meta.reasoning_effort_raw, "summary": None}
                      if meta.reasoning_effort_raw is not None else None),
        "store": False,
        "temperature": meta.temperature,
        "text": {"format": {"type": "text"}},
        "tool_choice": (meta.tool_choice_raw if meta.tool_choice_raw is not None else "auto"),
        "tools": meta.tools_raw,
        "top_p": meta.top_p,
        "truncation": meta.truncation,
        "usage": usage,
        "user": meta.user,
        "metadata": meta.metadata,
    }
    if status == "completed":
        obj["completed_at"] = now
    return obj


def translate_chat_result(chat_result: dict, resp_id: str, model: str,
                          meta: ReqMeta, ns_map: dict[str, tuple[str, str]]) -> dict:
    """非流式：chat completion → Responses response 对象。"""
    choices = chat_result.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}

    output: list[dict] = []
    reasoning_text = message.get("reasoning_content") or message.get("thinking_content") \
        or message.get("reasoning")
    if isinstance(reasoning_text, str) and reasoning_text:
        output.append(_reasoning_item(_new_id(_PREFIX_REASONING), reasoning_text))

    text = message.get("content")
    if isinstance(text, str) and text:
        output.append(_message_item(_new_id(_PREFIX_MESSAGE), text))
    elif isinstance(text, list):  # 少数上游回 parts 形态
        joined = "".join(p.get("text", "") for p in text
                         if isinstance(p, dict) and p.get("type") == "text")
        if joined:
            output.append(_message_item(_new_id(_PREFIX_MESSAGE), joined))

    for tc in message.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        name, namespace = _restore_namespace(ns_map, str(fn.get("name") or ""))
        output.append(_function_call_item(
            _new_id(_PREFIX_FUNCTION_CALL), str(tc.get("id") or _new_id("call_")),
            name, str(fn.get("arguments") or ""), namespace))

    if not output:  # 客户端不认空的 output[]
        output.append(_message_item(_new_id(_PREFIX_MESSAGE), ""))

    finish = choice.get("finish_reason")
    status = "incomplete" if finish == "length" else "completed"
    return _response_object(resp_id, model, meta, output, status=status,
                            usage=_resp_usage(chat_result.get("usage")))


# ══════════════════════════════════════════════════════════════════════════
# 流式编码：chat chunk 流 → Responses SSE
# ══════════════════════════════════════════════════════════════════════════


@dataclass
class _StreamItem:
    kind: str  # message | reasoning | function_call
    index: int
    id: str
    call_id: str = ""
    name: str = ""
    namespace: str | None = None
    arguments: str = ""
    text: str = ""
    opened: bool = False

    def output_json(self) -> dict:
        if self.kind == "message":
            return _message_item(self.id, self.text)
        if self.kind == "reasoning":
            return _reasoning_item(self.id, self.text)
        return _function_call_item(self.id, self.call_id, self.name, self.arguments,
                                   self.namespace)


class ResponsesStreamEncoder:
    """chat chunk → Responses SSE 事件（有状态、纯函数式产出帧字符串）。

    事件序列（官方事件集，客户端按 `type` 判别式解析）：

        response.created → response.in_progress
        → 每项 response.output_item.added（+ 对应的 part.added）
        → 各自的 delta 事件
        → 流结束时逐项收尾（*_done → part.done → output_item.done）
        → 终态 response.completed / response.incomplete / response.failed

    🔴 不发 `data: [DONE]`（那是 Chat Completions 的约定）。
    """

    def __init__(self, resp_id: str, model: str, meta: ReqMeta,
                 ns_map: dict[str, tuple[str, str]]) -> None:
        self.resp_id = resp_id
        self.model = model
        self.meta = meta
        self.ns_map = ns_map
        self.created_at = int(time.time())
        self._seq = 0
        self._items: list[_StreamItem] = []
        self._open: dict[str, _StreamItem] = {}
        self._started = False
        self._usage: dict | None = None
        self.finish_reason: str | None = None

    # —— 帧工厂 ——

    def _frame(self, event_type: str, **payload: Any) -> str:
        body = {"type": event_type, "sequence_number": self._seq, **payload}
        self._seq += 1
        return f"event: {event_type}\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"

    def _snapshot(self, status: str, error: dict | None = None) -> dict:
        return _response_object(self.resp_id, self.model, self.meta,
                                [it.output_json() for it in self._items],
                                status=status, usage=self._usage, error=error,
                                created_at=self.created_at)

    # —— 项管理 ——

    def _ensure(self, key: str, kind: str, *, call_id: str = "", name: str = "") -> tuple[_StreamItem, list[str]]:
        frames: list[str] = []
        item = self._open.get(key)
        if item is not None:
            return item, frames
        item = _StreamItem(kind=kind, index=len(self._items), id=_new_id(
            {"message": _PREFIX_MESSAGE, "reasoning": _PREFIX_REASONING,
             "function_call": _PREFIX_FUNCTION_CALL}[kind]),
            call_id=call_id, name=name)
        if kind == "function_call":
            _bare, ns = _restore_namespace(self.ns_map, name) if name else (name, None)
            item.name, item.namespace = _bare, ns
        self._items.append(item)
        self._open[key] = item
        item.opened = True
        if kind == "message":
            frames.append(self._frame(E_ITEM_ADDED, output_index=item.index, item={
                "id": item.id, "type": "message", "status": "in_progress",
                "role": "assistant", "content": []}))
            frames.append(self._frame(E_PART_ADDED, item_id=item.id,
                                      output_index=item.index, content_index=0,
                                      part={"type": "output_text", "text": "",
                                            "annotations": []}))
        elif kind == "reasoning":
            frames.append(self._frame(E_ITEM_ADDED, output_index=item.index, item={
                "id": item.id, "type": "reasoning", "summary": []}))
            frames.append(self._frame(E_RSN_PART_ADDED, item_id=item.id,
                                      output_index=item.index, summary_index=0,
                                      part={"type": "summary_text", "text": ""}))
        else:
            added: dict[str, Any] = {
                "id": item.id, "type": "function_call", "status": "in_progress",
                "call_id": item.call_id, "name": item.name, "arguments": ""}
            if item.namespace is not None:
                added["namespace"] = item.namespace
            frames.append(self._frame(E_ITEM_ADDED, output_index=item.index, item=added))
        return item, frames

    # —— 输入 ——

    def begin(self) -> list[str]:
        """created + in_progress（无内容也先发这两条，客户端据此建立响应上下文）。"""
        if self._started:
            return []
        self._started = True
        return [
            self._frame(E_CREATED, response=self._snapshot("in_progress")),
            self._frame(E_IN_PROGRESS, response=self._snapshot("in_progress")),
        ]

    def absorb(self, chunk: dict) -> list[str]:
        frames = self.begin()
        if isinstance(chunk.get("usage"), dict):
            self._usage = _resp_usage(chunk["usage"]) or self._usage
        choices = chunk.get("choices")
        if not (isinstance(choices, list) and choices):
            return frames
        choice = choices[0] if isinstance(choices[0], dict) else {}
        if choice.get("finish_reason"):
            self.finish_reason = choice["finish_reason"]
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            return frames

        reasoning = delta.get("reasoning_content") or delta.get("thinking_content") \
            or delta.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            item, extra = self._ensure("reasoning", "reasoning")
            frames += extra
            item.text += reasoning
            frames.append(self._frame(E_RSN_DELTA, item_id=item.id,
                                      output_index=item.index, summary_index=0,
                                      delta=reasoning))

        content = delta.get("content")
        if isinstance(content, list):  # 少数上游按 parts 增量下发
            content = "".join(p.get("text", "") for p in content
                              if isinstance(p, dict) and p.get("type") == "text")
        if isinstance(content, str) and content:
            item, extra = self._ensure("message", "message")
            frames += extra
            item.text += content
            frames.append(self._frame(E_TEXT_DELTA, item_id=item.id,
                                      output_index=item.index, content_index=0,
                                      delta=content, logprobs=[]))

        for tc in delta.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            index = tc.get("index", 0)
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            key = f"fc:{index}"
            existing = self._open.get(key)
            if existing is None:
                # 工具的 call_id/name 只在首帧出现 ⇒ 项必须延迟到这一帧才开
                # （`output_item.added` 发出去就改不了，必须当帧就带齐）
                item, extra = self._ensure(
                    key, "function_call",
                    call_id=str(tc.get("id") or ""), name=str(fn.get("name") or ""))
                frames += extra
            else:
                item = existing
                if tc.get("id") and not item.call_id:
                    item.call_id = str(tc["id"])
                # name 迟到帧（少数上游把 name 放进后续帧）：补进 item ——
                # `output_item.added` 已发出去改不了，但 done 与最终 output 以准值收口
                late_name = _norm_tool_name(fn.get("name"))
                if late_name and not item.name:
                    bare, ns = _restore_namespace(self.ns_map, late_name)
                    item.name, item.namespace = bare, ns
            if fn.get("arguments"):
                item.arguments += str(fn["arguments"])
                frames.append(self._frame(E_FC_DELTA, item_id=item.id,
                                          output_index=item.index,
                                          delta=str(fn["arguments"])))
        return frames

    def finish(self, *, failed: bool = False, error: dict | None = None) -> list[str]:
        """收尾：逐项 done 事件 + 终态事件。"""
        frames = self.begin()
        for item in list(self._items):
            if not item.opened:
                continue
            item.opened = False
            if item.kind == "message":
                frames.append(self._frame(E_TEXT_DONE, item_id=item.id,
                                          output_index=item.index, content_index=0,
                                          text=item.text, logprobs=[]))
                frames.append(self._frame(E_PART_DONE, item_id=item.id,
                                          output_index=item.index, content_index=0,
                                          part={"type": "output_text", "text": item.text,
                                                "annotations": []}))
            elif item.kind == "reasoning":
                frames.append(self._frame(E_RSN_DONE, item_id=item.id,
                                          output_index=item.index, summary_index=0,
                                          text=item.text))
                frames.append(self._frame(E_RSN_PART_DONE, item_id=item.id,
                                          output_index=item.index, summary_index=0,
                                          part={"type": "summary_text", "text": item.text}))
            else:
                done_payload: dict[str, Any] = {
                    "item_id": item.id, "output_index": item.index,
                    "name": item.name, "arguments": item.arguments}
                if item.namespace is not None:
                    done_payload["namespace"] = item.namespace
                frames.append(self._frame(E_FC_DONE, **done_payload))
            frames.append(self._frame(E_ITEM_DONE, output_index=item.index,
                                      item=item.output_json()))
        self._open.clear()
        if failed:
            frames.append(self._frame(E_FAILED, response=self._snapshot("failed", error)))
        elif self.finish_reason == "length":
            frames.append(self._frame(E_INCOMPLETE, response=self._snapshot("incomplete")))
        else:
            frames.append(self._frame(E_COMPLETED, response=self._snapshot("completed")))
        return frames


# ══════════════════════════════════════════════════════════════════════════
# 端点
# ══════════════════════════════════════════════════════════════════════════


def _dropped_tools_header(dropped: list[str]) -> dict[str, str]:
    if not dropped:
        return {}
    return {HDR_DROPPED_TOOLS: ", ".join(dropped)[:512]}


@router.post("/v1/responses")
async def responses(request: Request):
    runtime = _runtime(request)
    try:
        body = await request.json()
    except Exception:
        return _openai_json_error(400, {"error": {
            "message": "请求体必须是合法 JSON", "type": "invalid_request_error"}})
    if not isinstance(body, dict):
        return _openai_json_error(400, {"error": {
            "message": "请求体必须是 JSON 对象", "type": "invalid_request_error"}})

    try:
        translated = build_chat_request(body)
    except ResponsesRequestError as e:
        return _openai_json_error(e.status, e.to_body())

    model_name = body.get("model")
    if not isinstance(model_name, str) or not model_name:
        return _openai_json_error(400, {"error": {
            "message": "缺少必填字段 model", "type": "invalid_request_error"}})
    model_def, err = _resolve_model_or_404(request, model_name)
    if err is not None:
        return err
    assert model_def is not None
    err = _endpoint_type_error(model_name, model_def, "chat")
    if err is not None:
        return err

    chat_body = dict(translated.chat_body)
    stream = body.get("stream") is True
    reasoning = lift_reasoning_from_body(chat_body)  # 防出站双重注入（Q15）
    ir = IRRequest(system_model=model_def.name, endpoint="chat", stream=stream,
                   body=chat_body, reasoning=reasoning)
    token_id = request.scope.get("state", {}).get("token_id")

    scheduler = runtime.scheduler
    snapshot = runtime.config
    ctx = CallCtx.new(token_id, model_def.name, "chat", stream, snapshot,
                      check_disconnected=request.is_disconnected)
    watcher = _watch_disconnects(request, runtime.cancel_registry, ctx.request_id)
    resp_id = _new_id("resp_")
    headers = _dropped_tools_header(translated.dropped_tools)

    try:
        if stream:
            return await _responses_stream_response(
                request, scheduler, ir, ctx, watcher, resp_id, model_def.name,
                translated, headers)
        result, _meta = await scheduler.execute_chat(ir, ctx)
        payload = translate_chat_result(result, resp_id, model_def.name,
                                        translated.meta, translated.ns_map)
        return JSONResponse(content=payload, headers=headers)
    except asyncio.CancelledError:
        raise
    except GatewayError as e:
        return _openai_json_error(e.status_code, e.to_openai_error())
    finally:
        watcher.cancel_sync()
        runtime.cancel_registry.unregister(ctx.request_id)


async def _responses_stream_response(request: Request, scheduler, ir, ctx, watcher,
                                     resp_id: str, model_name: str,
                                     translated: TranslatedRequest, headers: dict):
    """流式端点（§6 延迟提交同 /v1/chat/completions）：

    - 首内容事件前**零字节**；窗口内耗尽 → 非 200 JSON（绝不「先 200 再 error」）
    - 提交后 SSE；心跳 = 静默超 `heartbeat_seconds` 发注释帧
    - 中途失败 → 逐项收尾 + `response.failed`（不重放、不发 [DONE]）
    """
    runtime = _runtime(request)
    heartbeat = runtime.config.gateway.heartbeat_seconds
    encoder = ResponsesStreamEncoder(resp_id, model_name, translated.meta,
                                     translated.ns_map)
    gen = scheduler.stream_chat(ir, ctx)

    first: dict | None = None
    try:
        first = await gen.__anext__()
    except StopAsyncIteration:
        # 零内容：调度层已按 502 可重试走完重试/换号仍回空 ⇒ 如实报错，不伪造 completed
        watcher.cancel_sync()
        return _openai_json_error(503, {
            "message": "上游通道回空（未产生任何内容帧，重试与换号后仍无内容）",
            "type": "gateway_error", "code": "EMPTY_UPSTREAM_CONTENT"})
    except GatewayError as e:
        watcher.cancel_sync()
        return _openai_json_error(e.status_code, e.to_openai_error())
    if isinstance(first, dict) and first.get("type") == ERROR_EVENT:
        # 首帧即错误帧：还没写任何字节 ⇒ 仍按非 200 JSON 如实回（不先 200 再 error）
        watcher.cancel_sync()
        err = first.get("error") if isinstance(first.get("error"), dict) else {}
        status = first.get("status_code") or 502
        return _openai_json_error(status, {"error": {
            "message": str(err.get("message") or "上游流在首帧前失败"),
            "type": "gateway_error",
            "code": err.get("code") or "upstream_failed",
            "retryable": bool(first.get("retryable")),
        }})

    watcher.cancel_sync()  # 首帧已到，断连职责移交 StreamingResponse（starlette）

    async def body_stream() -> AsyncIterator[str]:
        queue: asyncio.Queue = asyncio.Queue()
        END = object()

        async def pull() -> None:
            try:
                if first is not None:
                    await queue.put(first)
                async for ev in gen:
                    await queue.put(ev)
            finally:
                queue.put_nowait(END)

        task = asyncio.create_task(pull())
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # 心跳注释帧（FR-3.11）
                    continue
                if ev is END:
                    break
                if isinstance(ev, dict) and ev.get("type") == ERROR_EVENT:
                    err = ev.get("error") if isinstance(ev.get("error"), dict) else {}
                    for frame in encoder.finish(failed=True, error={
                            "code": "server_error",
                            "message": str(err.get("message") or "上游流中断")}):
                        yield frame
                    return
                for frame in encoder.absorb(ev):
                    yield frame
            for frame in encoder.finish():
                yield frame
        finally:
            task.cancel()
            # 不能直接 `await task`：客户端断连时 Starlette 会向本生成器反复投递取消；
            # 直接 await 会把取消转发进 pull 任务本体，打断 httpcore 的 shielded 连接
            # 关闭 → 上游 TCP 永不关闭 → 取消无法透传（INT-08 根因，同 chat/messages）。
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait([task], timeout=5.0)

    return StreamingResponse(body_stream(), media_type=TEXT_EVENT,
                             headers={**_sse_headers(), **headers})


def _sse_headers() -> dict:
    return {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.get("/v1/responses/{response_id}")
async def retrieve_response(response_id: str):
    """无状态网关：不保存历史响应 ⇒ 一律 404（附可操作说明，不静默装死）。"""
    return _openai_json_error(404, {"error": {
        "message": f"响应 '{response_id}' 不存在：本网关是无状态转发，不保存历史响应。"
                   "会话状态由客户端自己维护（请把完整对话放进 input 重发）",
        "type": "invalid_request_error",
        "code": "not_found",
    }})
