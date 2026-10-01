"""TRAE **出站适配**（tech-design v2.0 §22.3/§22.4；M6-5c 接线）。

本产品是 `custom` 协议（§22.4）：**请求体与响应流都不是 OpenAI 形状**，
所以不复用 `FamilyOpenAIOut`，而是直接实现 `ProductOutAdapter` 的 duck typing
三方法（§22.3）:

- 请求：`POST {base_url}/api/agent/v3/llm_utils_chat`（`trae.ts:44` / `trae-adapter.ts:1175`），
  体 = **SOLO 形态**（`protocol.solo_body`，`stream:true` 强制 + `config_name`/`function`）；
- 响应：**SOLO 自定义 SSE**（跨行 `event:` + `data:` 成帧，`trae-adapter.ts:1280-1523`）
  → 逐事件转成 OpenAI `chat.completion.chunk`（`protocol.parse_solo_event`）；
- 凭据：从账号目录自解（`ProductOutAdapter.resolve_context`，铁律 1 —— `key` 恒为空串），
  SOLO 头用 `protocol.solo_headers`（`Authorization: Cloud-IDE-JWT …` + 三个同值 token 头，
  `trae.ts:204-236`）。

🔴 **通道映射不重写**：请求体的 `function` 取 `models.channel_for(vendor_model)`
   （数据面 = 产品目录，单一来源；`trae-adapter.ts:656-661` 的 `channelFor`）。

🔴 **三处取舍（逐条附证据，不编造）**：

| 项 | 处置 | 证据 |
|---|---|---|
| 非流式 | 本地聚合（SOLO 上游**只发 SSE**，`stream:true` 是强制改写） | `trae.ts:1534-1538`（`stream: true`）、`trae-adapter.ts:1223`（只实现流消费） |
| 空响应（0 事件） | 抛可重试错误（**不谎报空回复**） | `trae-adapter.ts:1546-1559`（"empty response" 判为可重试瞬时故障） |
| 流内 `event:error` | 保留业务码抛错：1005/4008/4011 = 额度/限流（→ QUOTA 冷却），4001 = 模型不可调用（给出可操作提示） | `trae-adapter.ts:1497-1507,210-212,533-538` |
| 流内错误**已产出内容**后 | 如实抛错、**不重放**（防重复计费/重复执行工具） | `trae-adapter.ts:1483-1501` |

⚠️ 本模块**不 import `accounts` 与产品 `product.py` 于模块级**（`product.build_out`
   延迟 import 本模块；反向引用会成环，见 `adapters/product_out.py` 模块头 ⚠️）。
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

import httpx

from model_gateway.adapters.product_out import ProductAccount, ProductOutAdapter
from model_gateway.core.errors import UpstreamError
from model_gateway.upstream.trae import const, models, protocol

#: 流内可换号（额度/限流）业务码（`trae-adapter.ts:210-212`）。
_ROTATABLE_CODES = (1005, 4008, 4011)
#: 模型不可调用业务码（`trae-adapter.ts:533-538`）。
_CODE_MODEL_NOT_CALLABLE = 4001
#: 默认 finish 映射：SOLO 直接发 `stop|tool_calls|length`（`trae.ts:1752-1754`），
#: 缺失时按 OpenAI 口径回 `stop`。
_DEFAULT_FINISH = "stop"


def _stream_error(code: int, message: str, model: str) -> UpstreamError:
    """流内 `event:error` → `UpstreamError`（分类口径见模块头表）。

    - 1005 / 4008 / 4011 → `status_code=429`（`errors.classify` → QUOTA →
      按 `access_mode` 冷却 + 短退避，§22.5-5）；
    - 4001 → 可读提示（模型「仅可见不可调用」，换账号无意义——DSH 同判据）；
    - 其余 → `status_code=None`（RETRYABLE：交给既有重试/切换）。

    🔴 `error_body` 保真：**原 `code` / `message` 字段一个不改**；4001 只**追加**一个
    `hint` 键（"原字段保留 + 增量补充"是仓内既有约定，见 `ir.normalize_stream_chunk`）
    —— 否则该提示会被 `stats.events.error_summary` 截掉，用户只看到
    `{"code":4001,"message":"param is invalid"}` 这种无法行动的原始码。
    """
    text = f"trae: {message} (code={code})"
    body: dict[str, Any] = {"code": code, "message": message}
    if code in _ROTATABLE_CODES:
        return UpstreamError(text, status_code=429,
                             error_body=json.dumps(body, ensure_ascii=False))
    if code == _CODE_MODEL_NOT_CALLABLE:
        body["hint"] = (f"模型「{model}」不被上游接受：它通常是「仅可见但不可调用」的"
                        "自定义模型（需先在 TRAE IDE 内自行配置供应商），请改用其它模型")
        text += f" —— {body['hint']}"
    return UpstreamError(text, error_body=json.dumps(body, ensure_ascii=False))


class TraeOut(ProductOutAdapter):
    """TRAE 出站适配器（custom 协议；§22.3 三方法 + `aclose`）。"""

    #: 对话端点（相对资源基址；`trae.ts:44`，挂 `AGENT_HOST`）
    chat_path = const.PATH_CHAT

    def __init__(self, account: ProductAccount, *, client: httpx.AsyncClient | None = None,
                 timeout: float = 60.0) -> None:
        super().__init__(account, protocol="custom")
        if client is not None:
            self._client = client
        else:
            from model_gateway.adapters.openai_out import _is_local_target
            # 公网厂商走环境代理（既有口径）；本机/私网假上游直连
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout), trust_env=not _is_local_target(self.base_url))

    async def aclose(self) -> None:
        await self._client.aclose()

    # —— 请求构造 ——

    def _solo_headers(self, cred: dict) -> dict:
        """SOLO 族请求头（`protocol.solo_headers`，`stream=True`）。

        凭据缺 `access_token` → fail closed（**绝不发 `Cloud-IDE-JWT ` 空令牌**）。
        """
        if not protocol.read_str(cred, "access_token"):
            raise UpstreamError(
                f"Trae 账号 {self.account_ref} 的凭据缺少 access_token"
                "（请重新登录该账号）")
        return protocol.solo_headers(cred, stream=True)

    async def _events(self, vendor_model: str, body: dict,
                      timeout: float) -> AsyncIterator[protocol.SoloEvent]:
        """发一次请求并逐条产出 SOLO 事件（**跨行 `event:`+`data:` 成帧**）。

        成帧口径照抄 `trae-adapter.ts:1324-1522`：
        - 空行 = 事件分隔符 → 解析累积的 `event` + `data`；
        - `data:` 行**跨行拼接**（SOLO 的 data 可能被拆成多行，`:1520`）；
        - 其它行（注释等）忽略。
        """
        cred, _meta, _device = self.resolve_context()
        payload = protocol.solo_body(body, vendor_model,
                                     models.channel_for(vendor_model))
        try:
            async with self._client.stream(
                "POST", f"{self.base_url}{self.chat_path}",
                headers=self._solo_headers(cred),
                content=json.dumps(payload, ensure_ascii=False),
                timeout=timeout,
            ) as resp:
                if resp.status_code != 200:
                    text = (await resp.aread()).decode("utf-8", "replace")
                    raise UpstreamError(
                        f"upstream {resp.status_code}", status_code=resp.status_code,
                        error_body=text)
                current_event = ""
                current_data = ""
                saw_any = False
                async for raw in resp.aiter_lines():
                    if raw.strip() == "":
                        if not current_event:
                            continue
                        event, data = current_event, current_data
                        current_event, current_data = "", ""
                        saw_any = True
                        yield protocol.parse_solo_event(event, data)
                        continue
                    line = raw.strip()
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                    elif line.startswith("data:"):
                        current_data += line[5:]
                if not saw_any:
                    # 上游「HTTP 200 却一个事件都不发」= 可重试的瞬时故障
                    # （`trae-adapter.ts:1546-1559`：**不能**当成空回复）
                    raise UpstreamError("trae: upstream returned no events (empty response)")
        except UpstreamError:
            raise
        except httpx.TimeoutException as e:
            raise UpstreamError(f"timeout: {e}") from e
        except httpx.HTTPError as e:
            raise UpstreamError(f"network: {type(e).__name__}: {e}") from e

    # —— 流式（SSE → OpenAI chunk）——

    async def chat_stream(self, key: str, vendor_model: str, body: dict,
                          timeout: float) -> AsyncIterator[dict]:
        del key  # 产品资源的凭据从账号目录自解（§22.3；配置里的空 Key 不使用）
        chunk_id = f"chatcmpl-trae-{int(time.time() * 1000)}"
        started = False
        finish = _DEFAULT_FINISH
        async for ev in self._events(vendor_model, body, timeout):
            if ev.event == "output":
                delta: dict[str, Any] = {}
                if ev.response:
                    delta["content"] = ev.response
                if ev.reasoning:
                    delta["reasoning_content"] = ev.reasoning
                if ev.tool_calls:
                    delta["tool_calls"] = ev.tool_calls
                if not delta and not started:
                    continue                      # 空 output 事件不占首帧
                if not started:
                    delta["role"] = "assistant"   # OpenAI 客户端期望首个增量带 role
                    started = True
                yield protocol.openai_chunk(delta, chunk_id=chunk_id, model=vendor_model)
            elif ev.event == "token_usage":
                if ev.usage:
                    yield protocol.openai_chunk({}, usage=dict(ev.usage),
                                                chunk_id=chunk_id, model=vendor_model)
            elif ev.event == "done":
                if ev.finish_reason:
                    finish = ev.finish_reason
                yield protocol.openai_chunk({}, finish_reason=finish,
                                            chunk_id=chunk_id, model=vendor_model)
            elif ev.event == "error":
                if ev.code is not None:
                    raise _stream_error(ev.code, ev.message, vendor_model)
                raise UpstreamError(f"trae: stream error: {ev.message or 'unknown'}",
                                    error_body=ev.message or "")
            # metadata / timing_cost / extra_info 等事件：无 OpenAI 对应语义，跳过

    # —— 非流式（本地聚合 SOLO 事件，`trae.ts:1534` 强制 stream）——

    async def chat_nonstream(self, key: str, vendor_model: str, body: dict,
                             timeout: float) -> dict:
        del key
        text: list[str] = []
        reasoning: list[str] = []
        tool_calls: dict[int, dict] = {}
        usage: dict | None = None
        finish = _DEFAULT_FINISH
        async for ev in self._events(vendor_model, body, timeout):
            if ev.event == "output":
                if ev.response:
                    text.append(ev.response)
                if ev.reasoning:
                    reasoning.append(ev.reasoning)
                for call in ev.tool_calls or []:
                    if not isinstance(call, dict):
                        continue
                    idx = call.get("index")
                    idx = idx if isinstance(idx, int) and not isinstance(idx, bool) else len(tool_calls)
                    slot = tool_calls.setdefault(idx, {
                        "id": "", "type": "function",
                        "function": {"name": "", "arguments": ""}})
                    if call.get("id"):
                        slot["id"] = str(call["id"])
                    fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                    if fn.get("name"):
                        slot["function"]["name"] = str(fn["name"])
                    if isinstance(fn.get("arguments"), str):
                        slot["function"]["arguments"] += fn["arguments"]
            elif ev.event == "token_usage":
                if ev.usage:
                    usage = dict(ev.usage)
            elif ev.event == "done":
                if ev.finish_reason:
                    finish = ev.finish_reason
            elif ev.event == "error":
                if ev.code is not None:
                    raise _stream_error(ev.code, ev.message, vendor_model)
                raise UpstreamError(f"trae: stream error: {ev.message or 'unknown'}",
                                    error_body=ev.message or "")

        message: dict[str, Any] = {"role": "assistant", "content": "".join(text)}
        if reasoning:
            message["reasoning_content"] = "".join(reasoning)
        if tool_calls:
            message["tool_calls"] = [tool_calls[k] for k in sorted(tool_calls)]
            if not finish or finish == "stop":
                finish = "tool_calls"     # 有工具调用但上游未标 finish → 按 OpenAI 口径兜底
        return {
            "id": f"chatcmpl-trae-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": vendor_model,         # 调度器统一替换为系统模型名（scheduler §5.1）
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": usage if usage is not None else {},
        }
