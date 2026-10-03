"""Qoder **响应信封**的解包（`unwrapQoderEnvelopeStream` 的 Python 移植；M6-5c）。

加密端点 `agent_chat_generation` 的响应是 SSE，但**每帧多一层信封**：

```
data:{"headers":{...},"body":"{\\"choices\\":[{\\"delta\\":{\\"content\\":\\"Q\\"}}]}","statusCodeValue":200,"statusCode":"OK"}
                            ↑ 这里才是标准 OpenAI chunk（JSON 字符串）
```

🔴 **内层 `body` 并未加密** —— 只有**请求**体需要 WASM 加密（本层不涉及）。

失败时内层是**业务错误 JSON**（`{"code":"10605","message":"{…}"}` / `{"code":110,…}`），
必须**抛出而不是当成无内容**（DSH 真实缺陷：静默吞掉会表现为「没收到回复就终止」）。

🔴 **`code` 必须保真转发**（DSH 真实缺陷，`qoder-envelope.ts:23-29,124-135`）：
旧实现把内层 `{code,message}` 降级重组并**丢掉 `code` 字段** → 下游排队识别
（依赖顶层 `code === '10605'`）永远不命中，排队被误判成通用服务器错误。
故本层：**`code` 独立保留**（进异常属性）、`message` 原样，不拼后缀。

业务码语义（`model-queue.ts` 取证）：

| 码 | 含义 | 本层处置 |
|---|---|---|
| `10605` | 排队（model_queued，**暂时**受阻） | `QoderQueuedError`（可重试；`retry_after_seconds` 解析后带上） |
| `110` | 额度用尽（Billing daily count exceeded，**当天**耗尽） | `status_code=429` → QUOTA（冷却，不白重试） |
| 其它 | 未知业务错误 | 可重试错误（保留原始体） |
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from model_gateway.core.errors import UpstreamError

#: 排队业务码（客户端 obf 产物 `mRA`；`model-queue.ts:36`）。
QUEUE_BUSINESS_CODE = "10605"
#: 额度用尽业务码（`Billing daily count exceeded`；`model-queue.ts:73`）。
BILLING_BUSINESS_CODE = "110"
#: 🔴 额度类业务码的**全集**（信封内层 110 + 公开端点 HTTP 402 的 116）。
#: 116 取自 2026-10-04 的实读响应（探针存档
#: `docs/changes/e2e-records/E2E-20261004-qoder-quota-probe.md`）：额度为 0 的号打
#: `POST https://api2-v2.qoder.sh/model/v1/chat/completions` 回
#: `402 {"code":116,"error":"quota exceeded"}`。
#: ⚠️ **口径限定（验收 PA-1 抓出来的）**：这一支只认「JSON `code` 字段 = 116」，
#: **刻意不把 "quota exceeded" 加进下面的文案兜底** —— 文案判据扫的是整条响应体，
#: 会让 `401 + 一句含 "quota exceeded" 的 body`（认证腿也可能回显这种句子）从 AUTH 翻成 QUOTA。
#: 码表读的是结构化字段，不会误伤。同理**不宣称**「402 只可能是额度态」——那是从单个号
#: 外推不出的全称命题；全局 `402 → QUOTA` 只是按字面把 Payment Required 归到额度类，
#: 并且 `error_rules` 的 (http,type) 精确覆写排在它之前，将来要按厂商改回来是**有门的**。
_BILLING_CODES = (BILLING_BUSINESS_CODE, "116")
#: 额度文案兜底判据（**窄关键词**：泛词会误伤正文；`model-queue.ts:128-130`）。
#: 只在**没有可识别业务码**时兜底；词表保持原样（理由见上面那条"别加新词"）。
_BILLING_HINTS = ("billing daily count exceeded", "daily count exceeded", "billing_error")


class QoderBusinessError(UpstreamError):
    """信封内层业务错误（`code` 保真保留；`message` 原样）。"""

    def __init__(self, message: str, *, code: str = "", error_body: str = "",
                 status_code: int | None = None):
        super().__init__(message, status_code=status_code, error_body=error_body,
                         error_type="model_error")
        self.code = code


class QoderQueuedError(QoderBusinessError):
    """排队（`10605`）：暂时受阻，**值得重试**（DSH 精确等待 `retryAfterSeconds` 后重试）。

    ⚠️ 本网关**没有** DSH 那套「在适配器内按服务端延迟等待重试」的循环
    （§22.10 不做第二套调度）—— 这里把它判为**可重试错误**（`status_code=None`
    → `RETRYABLE`），交给既有重试/切换路径；`retry_after_seconds` 解析后随异常带上，
    供后续波次决定是否接队列等待（登记缺口，见 M6-5c 报告）。
    """

    def __init__(self, message: str, *, error_body: str = "", retry_after_seconds: int | None = None):
        super().__init__(message, code=QUEUE_BUSINESS_CODE, error_body=error_body)
        self.retry_after_seconds = retry_after_seconds


def inner_text_of(payload: str) -> str | None:
    """从信封 JSON 文本里取出内层帧文本；**不是信封 → `None`**（`innerTextOf`）。

    `body` 是字符串 → 原样；是对象 → `json.dumps`（与 DSH 的 `JSON.stringify` 同口径）。
    """
    try:
        envelope = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(envelope, dict) or "body" not in envelope:
        return None                      # 不是信封 → 调用方视为已是标准帧
    body = envelope["body"]
    if isinstance(body, str):
        return body
    return json.dumps(body, ensure_ascii=False)


def parse_queue_info(text: str) -> dict | None:
    """从响应体/错误帧文案里解析**排队信息**（`parseQueueError` 的移植，`model-queue.ts:189-232`）。

    - 两种入参形态都支持：外层整体 `{"code":"10605","message":"{…}"}` 与内层消息
      `{"isQueued":true,…,"retryAfterSeconds":30}`（内层**没有** `code` 字段）；
    - 广度优先展开 `data` / `result` / `message` / `body`（客户端 `lFc()` 的键集）；
    - 判据：命中 `code=10605` **或** 出现排队字段（`isQueued` / `serviceAvailable`）。
    """
    try:
        root: Any = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(root, dict):
        return None

    nodes: list[dict] = []
    queue: list[Any] = [root]
    seen: set[int] = set()
    while queue:
        node = queue.pop(0)
        if not isinstance(node, dict) or id(node) in seen:
            continue
        seen.add(id(node))
        nodes.append(node)
        for key in ("data", "result", "message", "body"):
            value = node.get(key)
            if isinstance(value, dict):
                queue.append(value)
            elif isinstance(value, str) and value:
                try:
                    queue.append(json.loads(value))
                except (json.JSONDecodeError, ValueError):
                    pass

    info = next((n for n in nodes
                 if n.get("isQueued") is not None or n.get("serviceAvailable") is not None), None)
    if info is None:
        return None
    code_hit = any(str(n.get("code") or "") == QUEUE_BUSINESS_CODE for n in nodes)
    if not code_hit and info.get("isQueued") is None:
        return None
    out: dict[str, Any] = {k: info[k] for k in ("isQueued", "serviceAvailable", "queueCount")
                           if isinstance(info.get(k), (bool, int))}
    for key in ("retryAfterSeconds", "waitTime", "retry_after_ms", "retryAfterMs"):
        value = info.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = int(value)
    return out


def retry_after_seconds_of(info: dict) -> int | None:
    """排队信息的延迟秒数（优先毫秒口径，`model-queue.ts:28-30` 的优先序）。"""
    ms = info.get("retry_after_ms", info.get("retryAfterMs"))
    if isinstance(ms, int):
        return max(0, ms // 1000)
    seconds = info.get("retryAfterSeconds")
    return seconds if isinstance(seconds, int) else None


def looks_like_billing_error(text: str) -> bool:
    """文案兜底：是否**额度类**错误（`looksLikeBillingError`，`model-queue.ts:128-130`）。"""
    low = text.lower()
    return any(hint in low for hint in _BILLING_HINTS)


def is_billing_code(code: Any) -> bool:
    """业务码是否额度类（`110` 信封内层 / `116` 公开端点 HTTP 402）。"""
    return str(code or "") in _BILLING_CODES


def is_business_error(text: str) -> bool:
    """响应体是不是 Qoder **可识别的业务错误**（排队 / 额度）—— 单一判据。

    🔴 为什么要有这个函数而不是让调用方各自比码：出站层（`out._try_business_error`）原先
    自己写了一遍 `code == 10605/110` 的硬编码比较，于是"新增一个额度码"要改两处 ——
    本轮加 `116` 时就是这样：`business_error` 认了，出站那支却只靠**文案兜底**才认上
    （撤证 M4 把文案关键词摘掉，出站立刻不认）。判据只有一份（本函数）+ 消费方一律走它。
    """
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        parsed = None
    code = str(parsed.get("code") or "") if isinstance(parsed, dict) else ""
    return (code == QUEUE_BUSINESS_CODE or is_billing_code(code)
            or parse_queue_info(text) is not None or looks_like_billing_error(text))


def _with_retry_after(inner_text: str, wait: int | None) -> str:
    """把解析出的 `retry_after_seconds` **增量**写进错误体（原键一个不改）。

    为什么：客户端可见的错误摘要取 `error_body`（`stats.events.error_summary`），
    「要等 30s」若只放异常 message 用户看不到（M6-5c 集成测试实测到）。
    "原字段保留 + 增量补充"是仓内既有约定（见 `ir.normalize_stream_chunk`）；
    解析不出对象（纯文本错误体）→ 原样返回。
    """
    if wait is None:
        return inner_text
    try:
        parsed = json.loads(inner_text)
    except (json.JSONDecodeError, ValueError):
        return inner_text
    if not isinstance(parsed, dict):
        return inner_text
    return json.dumps({**parsed, "retry_after_seconds": wait}, ensure_ascii=False)


def business_error(inner_text: str) -> UpstreamError:
    """内层业务错误文本 → 分类好的 `UpstreamError`（`code` 保真；见模块头表）。"""
    code = ""
    message = inner_text
    try:
        parsed = json.loads(inner_text)
    except (json.JSONDecodeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        if parsed.get("code") is not None:
            code = str(parsed["code"])
        if isinstance(parsed.get("message"), str):
            message = parsed["message"]

    info = parse_queue_info(inner_text)
    if code == QUEUE_BUSINESS_CODE or info is not None:
        wait = retry_after_seconds_of(info) if info else None
        text = f"qoder 排队中（code={code or QUEUE_BUSINESS_CODE}）"
        if wait is not None:
            text += f"，服务端建议等待 {wait}s"
        return QoderQueuedError(text, error_body=_with_retry_after(inner_text, wait),
                                retry_after_seconds=wait)
    if code in _BILLING_CODES or looks_like_billing_error(inner_text):
        return QoderBusinessError(
            f"qoder 额度用尽（code={code or BILLING_BUSINESS_CODE}）：{message}",
            code=code or BILLING_BUSINESS_CODE, error_body=inner_text, status_code=429)
    return QoderBusinessError(f"qoder 业务错误（code={code or '?'}）：{message}",
                              code=code, error_body=inner_text)


async def iter_chunks(lines: AsyncIterator[str]) -> AsyncIterator[dict]:
    """信封 SSE 行流 → **标准 OpenAI chunk 字典流**（`unwrapQoderEnvelopeStream` 语义）。

    - `data:` 行按 SSE 规范累积到空行成帧（与 `openai_out` 同一消费口径）；
    - 非信封帧原样透传（容错：万一服务端某天直接回标准帧）；
    - `[DONE]` 结束；
    - 内层是业务错误（非 `choices` 且非 `[DONE]`）→ **抛 `UpstreamError`**（不静默）。
    """
    data_lines: list[str] = []
    async for raw in lines:
        if raw == "":
            if not data_lines:
                continue
            payload = "\n".join(data_lines)
            data_lines = []
            payload = payload.strip()
            if payload == "[DONE]":
                return
            inner = inner_text_of(payload)
            if inner is None:
                chunk = _as_dict(payload)
                if chunk is not None:
                    yield chunk
                continue
            inner_stripped = inner.strip()
            if inner_stripped == "[DONE]":
                return
            if '"choices"' not in inner:
                raise business_error(inner)
            chunk = _as_dict(inner)
            if chunk is not None:
                yield chunk
            continue
        if raw.startswith("data:"):
            data_lines.append(raw[5:].strip())
        elif raw.startswith(":"):
            continue                      # 注释帧（keep-alive）
    if data_lines:                        # 流末未跟空行的残帧（服务端少发一个空行）
        payload = "\n".join(data_lines).strip()
        if payload and payload != "[DONE]":
            inner = inner_text_of(payload)
            text = inner if inner is not None else payload
            if '"choices"' in text:
                chunk = _as_dict(text)
                if chunk is not None:
                    yield chunk


def _as_dict(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None
