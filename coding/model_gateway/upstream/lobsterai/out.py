"""LobsterAI **出站适配**（tech-design v2.0 §22.3；M6-5b 接线）。

本模块是 `FamilyOpenAIOut` 的产品族实现：传输 / SSE 解析 / 错误映射全部继承
（`adapters/openai_out.py`），本类只声明**本产品取证到的三处差异**：

| 项 | 取值 | 取证 | 处置 |
|---|---|---|---|
| 推理路径 | `/api/proxy/v1/chat/completions`（挂 `API_BASE`） | `lobsterai.ts:17,45`（`LOBSTERAI_CHAT_PATH`） | 落 `chat_path` |
| 鉴权 | `Authorization: Bearer <access_token>` | `lobsterai.ts:492-503`（只四个基础头） | 复用 `protocol.auth_headers` |
| 身份头 | `User-Agent`（`LobsterAI/0.1.0`）+ 两个 `X-LobsterAI-Client-*` | `lobsterai.ts:517-530`；取值 `lobsterai-product.ts:116-129` | 复用 `protocol.client_headers` |
| `Accept` | `text/event-stream, application/json` | `lobsterai.ts:529` | 同上（accept 形参） |
| 请求体 | **`stream` 恒为 `true`** —— 上游只支持 SSE，`stream:false` 返回 **500** | `client.go:168-195`（DSH 照抄该结论，`lobsterai-adapter.ts:996-1001`） | `prepare_body` 强制改写；非流式走**聚合**（见下） |
| `prompt_cache_key` | **不发** —— 那是腾讯后端的前缀缓存机制，本产品未实测支持 | `lobsterai-adapter.ts:20` 差异表 | 不注入该字段（工具带来时原样透传，网关不做字段级删改） |
| 图片 | DSH 侧 `inputModalities` 恒 `['text']`（本适配器不额外声明） | `lobsterai-adapter.ts:19` 差异表 | 能力位归目录（`list_models`），出站不造字段 |

⚠️ **不设** CodeBuddy 系归属头（`X-Domain` / `X-Product*` / `X-IDE-*`）：`lobsterai.ts:492-503`
明确「LobsterAI 不认那套头，带上可能让服务端按错误的客户端形态归因」。

🔴 **非流式 = SSE 聚合**（`LobsterAI` 特有）：上游只接受 `stream:true`，故 `chat_nonstream`
在本类内把 `chat_stream`（继承来的 SSE 解析 + 思考字段归一化）的 chunk 聚合成一条
OpenAI 形状 `chat.completion`；其余产品走基类直连非流式端点。聚合只搬上游出现过的字段
（内容 / `reasoning_content` / `tool_calls` / `finish_reason` / `usage`），**不编造**。

⚠️ 本模块**无网络副作用**：只构造适配器；请求由 `core/scheduler` 驱动（§22.8-1）。
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from model_gateway.adapters.product_out import FamilyOpenAIOut
from model_gateway.core.errors import UpstreamError
from model_gateway.upstream.lobsterai import const, login, protocol


class LobsteraiOut(FamilyOpenAIOut):
    """LobsterAI 出站适配器（openai 族基类 + 本产品身份头 / 体差异）。"""

    #: 推理端点：`POST {base}/api/proxy/v1/chat/completions`（`lobsterai.ts:45`）。
    #: `Resource.base_url` = `API_BASE`（`registry.py` 的 lobsterai 块，不含路径前缀）。
    chat_path = "/api/proxy/v1/chat/completions"

    # —— 子类钩子 ——

    def auth_headers(self, cred: dict, meta: dict, device: dict) -> dict:
        """身份头（§22.3 钩子；**必装**）。

        - 凭据缺 `access_token` → `UpstreamError`（fail closed：绝不发 `Bearer ` 空令牌）；
        - `X-LobsterAI-Client-Version` 取**进程内缓存**（`login.client_version_cached`）：
          头钩子是同步函数，不能 await 网络（§22.8-1）；缓存未命中回退兜底常量
          （Go 侧长期发假值 `0.1.0` 未被拒 —— 服务端不强校验版本，`lobsterai.ts:545-550`）；
        - `meta` / `device` 本族当前不用（无设备身份；`uuid` 只参与登录标识）——形参按契约保留。
        """
        del meta, device
        if not protocol.read_str(cred, "access_token"):
            raise UpstreamError(
                f"LobsterAI 账号 {self.account_ref} 的凭据缺少 access_token（请重新登录该账号）")
        # Accept 用 chat 端点的取证值（`lobsterai.ts:529`）；Content-Type 由族基类补。
        version = login.client_version_cached()
        return protocol.client_headers(cred, version, accept="text/event-stream, application/json")

    def prepare_body(self, body: dict, *, vendor_model: str, cred: dict,
                     meta: dict, device: dict) -> dict:
        """体塑造：只落厂商模型名 + **强制 `stream:true`**（取证见模块头）。

        其余字段（采样 / 思考 / 工具）由网关 IR 层按既有口径注入，本层不重复不做删改。
        """
        del cred, meta, device
        return {**body, "model": vendor_model, "stream": True}

    # —— 非流式：聚合（LobsterAI 上游只支持 SSE）——

    async def chat_nonstream(self, key: str, vendor_model: str, body: dict,
                             timeout: float) -> dict:
        """非流式 = 消费 `chat_stream` 并聚合为 `chat.completion`（模块头 🔴 的落地）。

        - 传输 / SSE 解析 / 错误映射全部走继承实现（`_prepare_body` 已把 `stream` 改真）；
        - 首帧前的失败照旧抛 `UpstreamError`（调度器据此重试 / 切换 / 停用）；
        - **一帧未收到** → `UpstreamError`（fail closed，§22.8-5：不得把"上游什么都没给"
          当成"空内容成功"返回给客户端）；
        - 聚合语义：`content` 与 `reasoning_content` 按序拼接，`tool_calls` 按 `index`
          合并（`id`/`name` 只允许**非空覆盖** —— 后续分片带空串，直接覆盖会清空工具名，
          `lobsterai-adapter.ts:1218-1226` 的实测防坑），`finish_reason` / `usage` 取
          上游最后出现的值；上游没给的字段**不编造**。
        """
        chunks = [chunk async for chunk in
                  self.chat_stream(key, vendor_model, body, timeout)]
        if not chunks:
            raise UpstreamError("lobsterai：上游流式响应为空（未收到任何 SSE 帧）")
        return _aggregate(chunks)


#: 头钩子的**显式登记**（供接线护栏核验，与 buddy 的 `_HEADER_HOOK` 同一性质）：
#: 纯 AST 判据看不见"子类覆盖 + 基类多态调起"，登记一行让"真的有人用"可见。
_HEADER_HOOK = LobsteraiOut.auth_headers

#: 体钩子的**显式登记**（同上）：`FamilyOpenAIOut._prepare_body` 按属性名多态调起
#: `self.prepare_body(...)`，覆盖点在新文件里没有 `.prepare_body` 属性访问可被 AST 看见。
_BODY_HOOK = LobsteraiOut.prepare_body

#: 非流式覆盖的**显式登记**（同上）：`chat_nonstream` 由 `Scheduler.execute_chat`
#: 多态调起，跨文件 AST 判据因名字全包不唯一而看不见本类的覆盖。
_NONSTREAM_HOOK = LobsteraiOut.chat_nonstream


def _aggregate(chunks: list[dict]) -> dict:
    """把归一化 chunk 聚合成一条非流式 `chat.completion`（LobsterAI 专用，见模块头）。

    - 聚合只搬上游出现过的字段；`id`/`created` 在上游从未给出时才用本地值兜底
      （客户端 SDK 期望这两个字段存在）；
    - `message.content` 恒为字符串（无正文 = `""`），与 OpenAI 非流式形态一致。
    """
    content: list[str] = []
    reasoning: list[str] = []
    tools: dict[int, dict] = {}
    finish_reason: Any = None
    usage: dict | None = None
    last_id = ""
    created = 0
    for chunk in chunks:
        if isinstance(chunk.get("id"), str) and chunk["id"]:
            last_id = chunk["id"]
        value = chunk.get("created")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            created = int(value)
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            if isinstance(choice.get("finish_reason"), str):
                finish_reason = choice["finish_reason"]
            for delta in (choice.get("delta"), choice.get("message")):
                if not isinstance(delta, dict):
                    continue
                piece = delta.get("content")
                if isinstance(piece, str) and piece:
                    content.append(piece)
                think = delta.get("reasoning_content")
                if isinstance(think, str) and think:
                    reasoning.append(think)
                for call in delta.get("tool_calls") or []:
                    _merge_tool_call(tools, call)
    message: dict[str, Any] = {"role": "assistant", "content": "".join(content)}
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    if tools:
        message["tool_calls"] = [tools[index] for index in sorted(tools)]
    out: dict[str, Any] = {
        "id": last_id or f"chatcmpl-{secrets.token_hex(12)}",
        "object": "chat.completion",
        "created": created or int(time.time()),
        "model": "",           # 由调度器按系统模型名替换（`execute_chat` 末尾）
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
    }
    if usage is not None:
        out["usage"] = usage
    return out


def _merge_tool_call(tools: dict[int, dict], call: Any) -> None:
    """把一片 `tool_calls` 增量并进按 `index` 键控的累加器。

    🔴 `id` / `function.name` **只允许非空覆盖**：上游后续分片会带空串，
    直接覆盖会清空已解析出的工具名（`unknown tool ""`，`lobsterai-adapter.ts:1218-1226`）。
    """
    if not isinstance(call, dict):
        return
    raw_index = call.get("index")
    index = raw_index if isinstance(raw_index, int) and not isinstance(raw_index, bool) else 0
    entry = tools.setdefault(index, {"index": index, "type": "function",
                                     "id": "", "function": {"name": "", "arguments": ""}})
    call_id = call.get("id")
    if isinstance(call_id, str) and call_id:
        entry["id"] = call_id
    function = call.get("function")
    if isinstance(function, dict):
        name = function.get("name")
        if isinstance(name, str) and name:
            entry["function"]["name"] = name
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            entry["function"]["arguments"] += arguments
    if isinstance(call.get("type"), str) and call["type"]:
        entry["type"] = call["type"]
