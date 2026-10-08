"""Anthropic Messages 出站适配（tech-design v2.0 §18 / PRD Q27-⑦）。

> v1.0 起 `adapters/anthropic_out.py` 一直是**空壳（仅 docstring）**，
> 而 PRD §1.4 的 P0 决策写「三大协议全支持（出站适配）」→ 本模块补齐**已承诺未交付**的部分。
> **ZCode 上游正是 Anthropic Messages 风格** → 不实现它，ZCode 接不进来（§18.1）。

契约（§18.2 ①，**与 `openai_out.py` 同形**的 duck typing 4 方法）::

    chat_nonstream(key, vendor_model, body, timeout) -> dict          # OpenAI 格式响应
    chat_stream(key, vendor_model, body, timeout)   -> AsyncIterator  # OpenAI 格式 chunk
    images_generate(...)                                              # Anthropic 无此能力
    aclose()

🔴 两个必须遵守的约定：
  ① **usage 必须在适配器内映射** —— `scheduler._usage_from` 只认 `prompt_tokens`/`completion_tokens`，
     而 Anthropic 是 `input_tokens`/`output_tokens`；不映射则 usage 恒走本地估算（§18.2 ③）。
  ② **2xx 但 Content-Type 非 JSON/SSE（WAF 挑战页 / 登录页 HTML）→ 抛 `UpstreamError(status_code=None)`** ——
     现有 `errors.classify()` 对 `status=200` 会落到 `BAD_REQUEST`（原样透传、不冷却），
     而 `status_code=None` 会落到 `RETRYABLE` → 自然进入 C 计数与冷却（§18.2 ⑤）。
"""

from __future__ import annotations

import contextlib
import json
from typing import Any, AsyncIterator, Callable

import httpx

from model_gateway.core.errors import ErrorClass, UpstreamError
from model_gateway.core.resources import normalize_base_url

#: Anthropic 版本头（官方固定值）
ANTHROPIC_VERSION = "2023-06-01"

#: OpenAI 有、Anthropic 无对应语义的字段（**丢弃**，不报错）
_DROPPED = ("n", "presence_penalty", "frequency_penalty", "logit_bias",
            "seed", "user", "response_format", "logprobs", "top_logprobs")

_STOP_REASON_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
}


# ============ 请求转换：OpenAI → Anthropic ============

def _data_uri_to_source(url: str) -> dict | None:
    """`data:<mime>;base64,<payload>` → Anthropic base64 image source。

    ⚠️ **仅支持 data-URI**：远程 http(s) 图片 URL **静默丢弃**（与参考实现一致，
    §18.2 ⑥；上游是否原生支持 `{type:"url"}` 未验证）。
    """
    if not isinstance(url, str) or not url.startswith("data:"):
        return None
    head, _, payload = url.partition(",")
    if ";base64" not in head:
        return None
    media_type = head[5:].split(";")[0] or "image/png"
    return {"type": "image", "source": {"type": "base64",
                                        "media_type": media_type, "data": payload}}


def _content_to_blocks(content: Any) -> list[dict]:
    """OpenAI `content`（string | parts）→ Anthropic typed block 数组。"""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if not isinstance(content, list):
        return []
    blocks: list[dict] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype == "text":
            blocks.append({"type": "text", "text": part.get("text") or ""})
        elif ptype == "image_url":
            iu = part.get("image_url")
            url = iu.get("url") if isinstance(iu, dict) else iu
            src = _data_uri_to_source(url or "")
            if src is not None:
                blocks.append(src)
            # 远程 URL → 静默丢弃（§18.2 ⑥）
    return blocks


def _tool_arguments_to_input(arguments: Any) -> dict:
    """`arguments`（JSON 字符串）→ Anthropic `input`（对象）。解析失败塞 `_raw_arguments`。"""
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str) and arguments.strip():
        try:
            parsed = json.loads(arguments)
            return parsed if isinstance(parsed, dict) else {"_raw_arguments": arguments}
        except json.JSONDecodeError:
            return {"_raw_arguments": arguments}
    return {}


def _map_tool_choice(tc: Any) -> dict | None:
    """OpenAI `tool_choice` 三态 → Anthropic。"""
    if tc is None:
        return None
    if isinstance(tc, str):
        if tc == "auto":
            return {"type": "auto"}
        if tc == "required":
            return {"type": "any"}
        if tc == "none":
            return None
        return None
    if isinstance(tc, dict):
        fn = tc.get("function")
        name = fn.get("name") if isinstance(fn, dict) else None
        if name:
            return {"type": "tool", "name": name}
    return None


def _map_tools(tools: Any) -> list[dict] | None:
    """OpenAI `tools[].function` → Anthropic `{name,description,input_schema}`。"""
    if not isinstance(tools, list):
        return None
    out: list[dict] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        fn = t.get("function") if t.get("type") == "function" else t
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        schema = fn.get("parameters") or fn.get("input_schema") or fn.get("schema")
        out.append({
            "name": fn["name"],
            "description": fn.get("description") or "",
            "input_schema": schema if isinstance(schema, dict)
            else {"type": "object", "properties": {}},
        })
    return out or None


def _strip_provider_prefix(model: str) -> str:
    """`provider/model` → `model`（§18.2 ⑥）。"""
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def openai_to_anthropic(body: dict, vendor_model: str) -> dict:
    """OpenAI Chat Completions 请求体 → Anthropic Messages 请求体。

    映射表见 tech-design §18.2 ⑥ / `19` §6.6。
    """
    system_parts: list[str] = []
    messages: list[dict] = []

    for msg in body.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")

        # system / developer → 顶层 `system`（多条用 \n\n 拼接成**单个字符串**）
        if role in ("system", "developer"):
            text = msg.get("content")
            if isinstance(text, str) and text:
                system_parts.append(text)
            elif isinstance(text, list):
                for b in text:
                    if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                        system_parts.append(b["text"])
            continue

        # tool 结果 → role:"user" + tool_result block
        if role == "tool":
            blocks = _content_to_blocks(msg.get("content"))
            messages.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id") or "",
                "content": blocks or [{"type": "text", "text": ""}],
            }]})
            continue

        # assistant 的 tool_calls → tool_use blocks（与 text 并列）
        if role == "assistant":
            blocks = _content_to_blocks(msg.get("content"))
            for tc in (msg.get("tool_calls") or []):
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id") or "",
                    "name": fn.get("name") or "",
                    "input": _tool_arguments_to_input(fn.get("arguments")),
                })
            if blocks:
                messages.append({"role": "assistant", "content": blocks})
            continue

        # 普通 user
        blocks = _content_to_blocks(msg.get("content"))
        if blocks:
            messages.append({"role": "user", "content": blocks})

    out: dict[str, Any] = {
        "model": _strip_provider_prefix(vendor_model),
        "messages": messages,
        # Anthropic `max_tokens` **必填**：优先 max_tokens > max_completion_tokens > 4096
        "max_tokens": (body.get("max_tokens")
                       or body.get("max_completion_tokens") or 4096),
    }
    if system_parts:
        out["system"] = "\n\n".join(system_parts)

    for k in ("temperature", "top_p"):
        if body.get(k) is not None:
            out[k] = body[k]

    # stop（string | array）→ stop_sequences（数组）
    stop = body.get("stop")
    if isinstance(stop, str) and stop:
        out["stop_sequences"] = [stop]
    elif isinstance(stop, list) and stop:
        out["stop_sequences"] = [s for s in stop if isinstance(s, str)]

    tools = _map_tools(body.get("tools"))
    if tools:
        out["tools"] = tools
    tc = _map_tool_choice(body.get("tool_choice"))
    if tc is not None:
        out["tool_choice"] = tc

    # 推理参数：IR 已在入站提升，这里按既有口径**原样透传**（不在适配器预断参数名，§18.2 ⑥）
    for k in ("thinking", "reasoning_effort"):
        if body.get(k) is not None:
            out[k] = body[k]

    # 显式丢弃无对应语义的字段（§18.2 ⑥）
    for k in _DROPPED:
        out.pop(k, None)

    if body.get("stream"):
        out["stream"] = True
    return out


# ============ 响应转换：Anthropic → OpenAI ============

def _blocks_to_message(blocks: list[dict]) -> dict:
    """Anthropic content blocks → OpenAI `message`（content + reasoning_content + tool_calls）。"""
    texts: list[str] = []
    thinking: list[str] = []
    tool_calls: list[dict] = []

    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        btype = b.get("type")
        if btype == "text":
            texts.append(b.get("text") or "")
        elif btype == "thinking":
            thinking.append(b.get("thinking") or b.get("text") or "")
        elif btype == "tool_use":
            tool_calls.append({
                "id": b.get("id") or "",
                "type": "function",
                "function": {
                    "name": b.get("name") or "",
                    "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False),
                },
            })

    msg: dict[str, Any] = {"role": "assistant", "content": "".join(texts)}
    if thinking:
        msg["reasoning_content"] = "".join(thinking)
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _usage_to_openai(usage: Any) -> dict:
    """🔴 Anthropic `input_tokens`/`output_tokens` → OpenAI `prompt_tokens`/`completion_tokens`。

    **必须在适配器内映射**，否则 `scheduler._usage_from` 读不到 → usage 恒走本地估算（§18.2 ③）。
    """
    u = usage if isinstance(usage, dict) else {}
    prompt = int(u.get("input_tokens") or 0)
    completion = int(u.get("output_tokens") or 0)
    return {"prompt_tokens": prompt, "completion_tokens": completion,
            "total_tokens": prompt + completion}


def anthropic_to_openai(resp: dict, system_model: str) -> dict:
    """Anthropic Messages 响应 → OpenAI Chat Completions 响应。"""
    blocks = resp.get("content") if isinstance(resp.get("content"), list) else []
    message = _blocks_to_message(blocks)
    stop_reason = resp.get("stop_reason")
    return {
        "id": resp.get("id") or "chatcmpl-anthropic",
        "object": "chat.completion",
        "created": 0,
        "model": system_model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": _STOP_REASON_MAP.get(stop_reason or "", "stop"),
        }],
        "usage": _usage_to_openai(resp.get("usage")),
    }


def parse_sse_line(line: str) -> tuple[str, dict] | None:
    """解析一行 Anthropic SSE。

    返回 `(event_type, data)`；非数据行返回 `None`。
    Anthropic 用 `event: <type>` + `data: <json>` 两行成对（与 OpenAI 只有 data 行不同）。
    """
    if not line or line.startswith(":"):
        return None
    if line.startswith("event:"):
        return line[6:].strip(), {}
    if line.startswith("data:"):
        payload = line[5:].strip()
        if not payload:
            return None
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return "data", data if isinstance(data, dict) else {}
    return None


class _StreamTranslator:
    """Anthropic 事件流 → OpenAI chunk 流（有状态）。

    Anthropic 事件族：`message_start` / `content_block_start` / `content_block_delta` /
    `content_block_stop` / `message_delta` / `message_stop` / `error`。
    """

    def __init__(self, system_model: str, chunk_id: str = "chatcmpl-anthropic"):
        self.system_model = system_model
        self.id = chunk_id
        self.role_sent = False
        #: Anthropic content block index → OpenAI tool_calls index
        self.tool_index: dict[int, int] = {}
        self._next_tool = 0

    def _chunk(self, delta: dict, finish_reason: str | None = None,
               usage: dict | None = None) -> dict:
        out: dict[str, Any] = {
            "id": self.id, "object": "chat.completion.chunk", "created": 0,
            "model": self.system_model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        if usage is not None:
            out["usage"] = usage
        return out

    def _ensure_role(self) -> dict | None:
        """首个增量前补发 `{"role":"assistant","content":""}`（OpenAI 客户端期望）。"""
        if self.role_sent:
            return None
        self.role_sent = True
        return self._chunk({"role": "assistant", "content": ""})

    def feed(self, event: str, data: dict) -> list[dict]:
        """喂一个 Anthropic 事件，返回 0..N 个 OpenAI chunk。"""
        out: list[dict] = []
        etype = data.get("type") or event

        if etype == "message_start":
            msg = data.get("message") or {}
            pre = self._ensure_role()
            if pre:
                out.append(pre)
            usage = _usage_to_openai(msg.get("usage"))
            if usage["prompt_tokens"] or usage["completion_tokens"]:
                out.append(self._chunk({}, usage=usage))
            return out

        if etype == "content_block_start":
            idx = int(data.get("index") or 0)
            block = data.get("content_block") or {}
            btype = block.get("type")
            if btype == "tool_use":
                pre = self._ensure_role()
                if pre:
                    out.append(pre)
                ti = self._next_tool
                self._next_tool += 1
                self.tool_index[idx] = ti
                out.append(self._chunk({"tool_calls": [{
                    "index": ti, "id": block.get("id") or "",
                    "type": "function",
                    "function": {"name": block.get("name") or "", "arguments": ""},
                }]}))
            return out

        if etype == "content_block_delta":
            idx = int(data.get("index") or 0)
            delta = data.get("delta") or {}
            dtype = delta.get("type")
            if dtype == "text_delta":
                pre = self._ensure_role()
                if pre:
                    out.append(pre)
                out.append(self._chunk({"content": delta.get("text") or ""}))
            elif dtype == "thinking_delta":
                pre = self._ensure_role()
                if pre:
                    out.append(pre)
                # 🔴 thinking_delta → reasoning_content（对齐 DeepSeek 风格客户端）
                out.append(self._chunk({"reasoning_content": delta.get("thinking") or ""}))
            elif dtype == "input_json_delta":
                ti = self.tool_index.get(idx, 0)
                out.append(self._chunk({"tool_calls": [{
                    "index": ti,
                    "function": {"arguments": delta.get("partial_json") or ""},
                }]}))
            return out

        if etype == "message_delta":
            d = data.get("delta") or {}
            stop = d.get("stop_reason")
            # ⚠️ 实测坑：`api.z.ai` 把最终 input_tokens 放在 message_delta
            #    （message_start 为 0）→ 取 max 累积由调用方处理；此处透传 usage
            usage = _usage_to_openai(data.get("usage")) if data.get("usage") else None
            out.append(self._chunk(
                {}, finish_reason=_STOP_REASON_MAP.get(stop or "", "stop"), usage=usage))
            return out

        if etype == "error":
            err = data.get("error") or {}
            raise UpstreamError(
                f"stream error: {err.get('message') or err}",
                error_type=str(err.get("type") or ""),
            )
        return out


# ============ 适配器 ============

class AnthropicOutAdapter:
    """Anthropic Messages 出站适配（与 `OpenAIOutAdapter` **同形**的 duck typing 接口）。"""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None,
                 needs_base64: Callable[[str], bool] | None = None,
                 *, fingerprint: bool = False):
        from model_gateway.adapters.openai_out import _is_local_target
        # 与 `OpenAIOutAdapter` 同形：入站即按 `normalize_base_url` 归一化（验收 S-19）
        self.base_url = normalize_base_url(base_url)
        self.fingerprint = fingerprint
        if client is not None:
            self._client = client
        elif fingerprint:
            # 🔴 TLS 指纹客户端**统一由 auth 模块提供**（§17 / P1-8），不在本处自造。
            #    `zcode.z.ai` 前置 ESA WAF，普通 httpx ClientHello 易被识别为机器程序。
            #    curl_cffi 不可用时自动降级为普通 httpx（§19 T5a/T5b 待实测）。
            from model_gateway.upstream.zcode.auth import build_client
            self._client = build_client(fingerprint=True, timeout=60.0)
        else:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0), trust_env=not _is_local_target(self.base_url)
            )
        self._needs_base64 = needs_base64 or (lambda _m: False)

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _headers(key: str, device_mid: str = "") -> dict:
        """构造鉴权头（**双通道**，§17 / Q27-②）。

        🔴 关键：ZCode 的 **Plan 通道用 `Authorization: Bearer <jwt>`**，
        而 **API Key 通道用 `x-api-key`** —— 两者不能混。
        判定靠**凭据形状**（JWT = 三段点分），不解析 claims（`auth.looks_like_jwt`）。

        原实现一律发 `x-api-key` → **Plan 通道必然 401**（验收发现的功能缺口）。
        """
        from model_gateway.upstream.zcode.auth import looks_like_jwt

        h = {
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        if looks_like_jwt(key):
            h["Authorization"] = f"Bearer {key}"
        else:
            h["x-api-key"] = key
        if device_mid:
            # 联网额度接口缺此头 → 400 code=3001；转发路径带上无害
            h["X-Device-Mid"] = device_mid
        return h

    def _url(self) -> str:
        """Anthropic 端点：`{base}/messages`。

        兼容 base_url 已含 `/v1` 或已含 `/anthropic/v1` 的两种配置形态。
        """
        base = self.base_url
        if base.endswith("/v1"):
            return f"{base}/messages"
        return f"{base}/v1/messages"

    @staticmethod
    def _non_json_error(status: int, content_type: str, text: str) -> UpstreamError:
        """🔴 2xx 但非 JSON/SSE（WAF 挑战页 / 登录页 HTML）→ `status_code=None`。

        为什么传 `None` 而不是 `200` 或 `502`：`errors.classify()` 对 `status=200`
        会落到 `BAD_REQUEST`（原样透传、不冷却）；`status_code=None` 落到 `RETRYABLE`
        → 自然进入 C 计数与冷却（§18.2 ⑤）。
        """
        return UpstreamError(
            f"upstream {status} non-json (content-type={content_type or '?'}): {text[:160]}",
            status_code=None,
        )

    def _envelope_error_class(self, data: dict) -> ErrorClass | None:
        """**自有信封**（2xx + `{code,msg}`）的业务码 → 错误类别；**认不出返回 `None`**。

        基类缺省 = `None`（不认识任何产品的码表，保持中性）；产品子类按**取证过的**
        官方归因表覆写（ZCode 见 `upstream/zcode/business_codes.py`）。

        🔴 为什么必须有这个钩子（2026-10-08 实盘）：`_shape_error` 原先对**所有**
        「200 + 自有信封」一律 `status_code=None` ⇒ `RETRYABLE`。而 ZCode 的 `1005`
        （额度耗尽）在该路径下变成"网络抖动"⇒ 短冷却 + 计 C，同一条额度尽的号被反复打
        （实测一轮换号连撞 6 个号各 2 次）；正确动作是**长冷却**（官方
        `providerBusinessError.ts` 明写 `1005 → refresh-quota`，DSH `trae-credits.ts:65`
        同码 → 43200s）。**不区分的"一律可重试"与"一律不可重试"是同一类错误**。
        """
        return None

    def _shape_error(self, status: int, content_type: str, text: str) -> UpstreamError:
        """🔴 2xx 且是 JSON，但**看不出是一条 Anthropic 消息**（`{code:…, msg:…}` 这类自有信封）
        → 错误（默认 `status_code=None` = RETRYABLE），而不是当成功返回空正文。

        与上面 `_non_json_error` 同一条立意（§18.2 ⑤ / §22.8-5「状态码 200 ≠ 取到了」）：
        2026-10-05 实盘审计的形状是「上游用 200 + 自有信封表达风控/错误」，旧实现把它当正常回答 ⇒
        客户端拿到 `content:""` + `finish_reason=stop`、事件行记 `success`、`note_success` 还把连续
        失败计数**清零**（= 一条永远健康的僵尸通道）。落 `None` 才进 C 计数与冷却、才换号。

        🔴 2026-10-08：**按信封业务码细分**（`_envelope_error_class` 钩子）——
        额度耗尽（1005）与网络抖动不是一回事，前者要长冷却、后者要短重试。
        认不出业务码时保持既有兜底（`status_code=None` → RETRYABLE），不猜。
        """
        cls: ErrorClass | None = None
        with contextlib.suppress(ValueError, TypeError):
            data = json.loads(text)
            if isinstance(data, dict) and "code" in data:
                cls = self._envelope_error_class(data)
        return UpstreamError(
            f"upstream {status} 非消息形状 (content-type={content_type or '?'}): {text[:160]}",
            status_code=None,
            error_body=text,
            # 显式类别（不是把类别名编进字符串再解析 —— 那是绕路）。
            # 分类器第 1.5 步直接采信；`error_rules` 的用户覆写仍排在它前面。
            error_class=cls,
        )

    def _prepare_payload(self, payload: dict) -> dict:
        """出站前对 Anthropic 形状 payload 的加工钩子（默认原样返回）。

        子类按产品差异覆写（ZCode 身份块注入 `upstream/zcode/out.py`）。
        必须在 `openai_to_anthropic` **之后**调用 —— 产品的准入判据看的是
        Anthropic 请求体的最终形状，不能在 OpenAI 形状的 body 上加工。
        """
        return payload

    # —— chat 非流式 ——
    async def chat_nonstream(self, key: str, vendor_model: str, body: dict,
                             timeout: float) -> dict:
        payload = openai_to_anthropic(body, vendor_model)
        payload = self._prepare_payload(payload)
        payload.pop("stream", None)
        try:
            resp = await self._client.post(
                self._url(), headers=self._headers(key),
                content=json.dumps(payload, ensure_ascii=False), timeout=timeout,
            )
        except httpx.TimeoutException as e:
            raise UpstreamError(f"timeout: {e}") from e
        except httpx.HTTPError as e:
            raise UpstreamError(f"network: {type(e).__name__}: {e}") from e

        ctype = resp.headers.get("content-type", "")
        if resp.status_code != 200:
            raise UpstreamError(
                f"upstream {resp.status_code}", status_code=resp.status_code,
                error_body=resp.text,
                error_type=_extract_anthropic_error_type(resp.text),
            )
        if "json" not in ctype.lower():
            raise self._non_json_error(resp.status_code, ctype, resp.text)
        try:
            data = resp.json()
        except ValueError:
            raise self._non_json_error(resp.status_code, ctype, resp.text) from None
        if not _looks_like_message(data):
            # 200 + JSON，但形状不是消息（`{code:3012,msg:"unusual activity"}` 这类自有信封）
            # ⇒ 这是**上游在说话**，不是一次空回答。旧实现返回 `content:""` 并被记成 success。
            raise self._shape_error(resp.status_code, ctype, resp.text)
        return anthropic_to_openai(data, vendor_model)

    # —— chat 流式 ——
    async def chat_stream(self, key: str, vendor_model: str, body: dict,
                          timeout: float) -> AsyncIterator[dict]:
        payload = openai_to_anthropic(body, vendor_model)
        payload["stream"] = True
        payload = self._prepare_payload(payload)
        translator = _StreamTranslator(vendor_model)
        try:
            async with self._client.stream(
                "POST", self._url(), headers=self._headers(key),
                content=json.dumps(payload, ensure_ascii=False), timeout=timeout,
            ) as resp:
                ctype = resp.headers.get("content-type", "")
                if resp.status_code != 200:
                    text = (await resp.aread()).decode("utf-8", "replace")
                    raise UpstreamError(
                        f"upstream {resp.status_code}", status_code=resp.status_code,
                        error_body=text,
                        error_type=_extract_anthropic_error_type(text),
                    )
                if "event-stream" not in ctype.lower() and "json" not in ctype.lower():
                    text = (await resp.aread()).decode("utf-8", "replace")
                    raise self._non_json_error(resp.status_code, ctype, text)
                if "json" in ctype.lower() and "event-stream" not in ctype.lower():
                    # 流式请求被回了一条**非 SSE 的 JSON**（自有信封的错误，或整块消息）：
                    # 逐行按 SSE 解析必然一帧都出不来 ⇒ 旧形状是「空流 + 事件行 success」，
                    # 再叠上入站层那条不存在的 `_sse()` 就直接 500。这里显式判失败，
                    # 让调度按可重试去换号（与上面 `_non_json_error` 同一立意）。
                    text = (await resp.aread()).decode("utf-8", "replace")
                    raise self._shape_error(resp.status_code, ctype, text)

                pending_event = ""
                async for raw in resp.aiter_lines():
                    parsed = parse_sse_line(raw)
                    if parsed is None:
                        continue
                    etype, data = parsed
                    if etype == "data":
                        for chunk in translator.feed(pending_event, data):
                            yield chunk
                        pending_event = ""
                    else:
                        pending_event = etype
        except UpstreamError:
            raise
        except httpx.TimeoutException as e:
            raise UpstreamError(f"timeout: {e}") from e
        except httpx.HTTPError as e:
            raise UpstreamError(f"network: {type(e).__name__}: {e}") from e

    # —— images（Anthropic Messages 协议无图像生成能力）——
    async def images_generate(self, key: str, vendor_model: str, body: dict,
                              timeout: float) -> dict:
        raise UpstreamError(
            "anthropic protocol has no images/generations endpoint",
            no_failover=True,
        )


def _extract_anthropic_error_type(text: str) -> str:
    """从 Anthropic 错误体抠 `error.type`（供 `errors.classify()` 用）。"""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return ""
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return str(err.get("type") or "")
    return ""


def _looks_like_message(data) -> bool:
    """这条 JSON **是不是一条 Anthropic 消息**（§18.2 ⑤ 的形状判据，不看状态码）。

    认不出消息就认不出成功 —— 上游用自有信封（`{"code":3012,"msg":"unusual activity"}`、
    `{"success":false,…}`）回错误时，旧实现会把它翻译成一条**空正文的成功**。
    """
    if not isinstance(data, dict):
        return False
    if data.get("type") == "message":
        return True
    return isinstance(data.get("content"), list)
