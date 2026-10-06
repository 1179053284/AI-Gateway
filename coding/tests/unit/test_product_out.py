"""产品出站适配（§22.3 duck typing；M6-5a）：凭据自解 / 身份头 / 传输复用 / 分派与复用判据。

判据逐条对应 §22.3 与 §22.5-3：

· 形状 = 与 `openai_out.py` **同形**的 duck typing（属性 + 三个方法）；
· 凭据**只在本地账号目录**（铁律 1）：调度侧传进来的 `key` 对产品资源恒为空串，
  适配器从 `account_ref` 自解；配置里的 Key 值**不得**被使用；
· 缺凭据 → fail closed（**不发请求**，`UpstreamError` 可读）；
· `product` 分支优先于 `protocol`；复用判据含 `product + account_ref + 凭据指纹`
  —— **改绑账号 / 重新登录必须换适配器**（S-14 同族缺陷的红证）。

HTTP 全部走 `httpx.MockTransport`（无网络）；账号读取打桩在
`accounts.store.load_credentials` / `hook_meta`（适配器唯一读入口）。
"""

from __future__ import annotations

import asyncio
import json
import pathlib

import httpx
import pytest

from model_gateway.accounts import store
from model_gateway.adapters import build_adapter
from model_gateway.adapters.openai_out import OpenAIOutAdapter
from model_gateway.adapters.product_out import (
    FamilyOpenAIOut,
    ProductAccount,
    ProductOutAdapter,
    build_product_adapter,
)
from model_gateway.core.errors import UpstreamError
from model_gateway.upstream.buddy import product as buddy
from model_gateway.upstream.buddy.out import BuddyFamilyOut

BASE = "http://127.0.0.1:9"   # 与注册表同形：buddy 基址**不含**路径前缀（chat_path 自带 /v2）
CRED = {"access_token": "TOKEN-FROM-ACCOUNT", "user_id": "u-1",
        "enterprise_id": "ent-9", "token_type": "Bearer"}


def _install_store(monkeypatch, cred: dict | None = None, meta: dict | None = None):
    """把适配器的**唯一凭据读入口**换成固定值（返回记录以便断言"没被读"）。"""
    reads = {"cred": 0, "meta": 0}

    def _cred(product, name, *, root=None):
        reads["cred"] += 1
        return dict(cred if cred is not None else CRED)

    def _meta(product, name, root=None):
        reads["meta"] += 1
        return {"account": name, "dir": "/tmp/fake", **(meta or {})}

    monkeypatch.setattr(store, "load_credentials", _cred)
    monkeypatch.setattr(store, "hook_meta", _meta)
    return reads


def _adapter(monkeypatch, *, cred=None, meta=None, transport=None, product="buddy",
             name="acc-1", base_url=BASE, needs_base64=None, factory=buddy.build_out):
    _install_store(monkeypatch, cred, meta)
    account = ProductAccount(product=product, name=name, base_url=base_url,
                             needs_base64=needs_base64)
    adapter = factory(account)
    if transport is not None:
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    return adapter


def _capture(monkeypatch, *, response: dict | None = None, sse: str | None = None,
             status: int = 200, body: str = ""):
    """MockTransport 记录器：返回 (seen, handler)。"""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if sse is not None:
            return httpx.Response(200, text=sse, request=request,
                                  headers={"content-type": "text/event-stream"})
        if status != 200:
            return httpx.Response(status, text=body, request=request)
        return httpx.Response(200, json=response or _ok_json(), request=request)

    return seen, handler


def _ok_json(content: str = "hi") -> dict:
    return {"id": "cmpl-1", "object": "chat.completion", "model": "hy3",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2}}


def _sse() -> str:
    frames = [
        {"id": "c", "object": "chat.completion.chunk", "model": "hy3",
         "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "c", "object": "chat.completion.chunk", "model": "hy3",
         "choices": [{"index": 0, "delta": {"content": "你"}, "finish_reason": None}]},
        {"id": "c", "object": "chat.completion.chunk", "model": "hy3",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    out = "".join(f"data: {json.dumps(f, ensure_ascii=False)}\n\n" for f in frames)
    return out + "data: [DONE]\n\n"


def _sse_rich() -> str:
    """带 `reasoning_content` / 分片 `tool_calls` / `usage` 的 SSE（聚合判据的输入形状）。"""
    frames = [
        {"id": "c-rich", "created": 1776000000, "object": "chat.completion.chunk",
         "model": "hy3",
         "choices": [{"index": 0, "delta": {"reasoning_content": "先想"},
                      "finish_reason": None}]},
        {"id": "c-rich", "created": 1776000000, "object": "chat.completion.chunk",
         "model": "hy3",
         "choices": [{"index": 0, "delta": {"content": "你"}, "finish_reason": None}]},
        {"id": "c-rich", "created": 1776000000, "object": "chat.completion.chunk",
         "model": "hy3",
         "choices": [{"index": 0, "delta": {"content": "好", "tool_calls": [
             {"index": 0, "id": "call-1", "type": "function",
              "function": {"name": "lookup", "arguments": "{\"q\""}}]},
             "finish_reason": None}]},
        {"id": "c-rich", "created": 1776000000, "object": "chat.completion.chunk",
         "model": "hy3",
         "choices": [{"index": 0, "delta": {"tool_calls": [
             {"index": 0, "id": "", "type": "function",
              "function": {"name": "", "arguments": ": \"天气\"}"}}]},
             "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 11, "completion_tokens": 5}},
    ]
    out = "".join(f"data: {json.dumps(f, ensure_ascii=False)}\n\n" for f in frames)
    return out + "data: [DONE]\n\n"


class _PlainFamilyOut(FamilyOpenAIOut):
    """族基类**缺省形状**样本：`stream_only=False` + 默认 `prepare_body`（测缺省用）。"""

    def auth_headers(self, cred: dict, meta: dict, device: dict) -> dict:
        del cred, meta, device
        return {"authorization": "Bearer PLAIN"}


# ============ 形状（§22.3 duck typing）============

def test_adapter_shape_matches_the_duck_typing_contract(monkeypatch):
    adapter = _adapter(monkeypatch)
    assert isinstance(adapter, ProductOutAdapter)
    assert isinstance(adapter, OpenAIOutAdapter)
    assert (adapter.product, adapter.account_ref) == ("buddy", "acc-1")
    assert adapter.base_url == BASE and adapter.protocol == "openai"
    assert adapter.chat_path == "/v2/chat/completions"
    for method in ("chat_nonstream", "chat_stream", "aclose"):
        assert callable(getattr(adapter, method))
    asyncio.run(adapter.aclose())


def test_base_contract_methods_fail_loudly(monkeypatch):
    """直接继承契约类而不实现 → 首次调用即显式失败（不静默半实现，§22.3）。"""
    adapter = ProductOutAdapter(ProductAccount(product="p", name="n", base_url=BASE))
    with pytest.raises(NotImplementedError):
        asyncio.run(adapter.chat_nonstream("", "m", {}, 5.0))
    with pytest.raises(NotImplementedError):
        asyncio.run(adapter.chat_stream("", "m", {}, 5.0).__anext__())   # async generator 形态
    with pytest.raises(NotImplementedError):
        asyncio.run(adapter.aclose())


# ============ `stream_only`：只收流式的通道在族内聚合 ============

def test_stream_only_flag_matches_the_probed_channels():
    """置真的一律是**实测只收流式**的通道；直连非流式能通的产品（cline）必须保持缺省。

    取证（:8300 真实数据 `usage/events-20261004.jsonl`，2026-10-04）：
    buddy / workbuddy 的 `stream=false` **4/4** 回 `400 {"code":11101}`，
    cline 的 `stream=false` 200（`test_cline_out.py` 同钉）⇒ 一刀切改流式会把
    能直连的通道也拖进"必须读完整个流才回首字节"的延迟里。
    """
    from model_gateway.upstream.cline.out import ClineOut
    from model_gateway.upstream.lobsterai.out import LobsteraiOut
    from model_gateway.upstream.workbuddy import product as workbuddy

    assert BuddyFamilyOut.stream_only is True          # buddy 与 workbuddy 共用这一份实现
    wb = workbuddy.build_out(ProductAccount(product="workbuddy", name="acc-wb", base_url=BASE))
    assert isinstance(wb, BuddyFamilyOut) and wb.stream_only is True   # 国际版同一条腿
    asyncio.run(wb.aclose())
    assert LobsteraiOut.stream_only is True            # client.go:168-195
    assert ClineOut.stream_only is False               # 实测可直连非流式
    assert _PlainFamilyOut.stream_only is False        # 族基类缺省 = 不改动形态


def test_stream_only_aggregation_merges_reasoning_tools_usage(monkeypatch):
    """聚合语义 = 正文/思考按序拼接、工具按 `index` 合并、usage/finish 取上游末值。"""
    seen, handler = _capture(monkeypatch, sse=_sse_rich())
    adapter = _adapter(monkeypatch, transport=handler)
    data = asyncio.run(adapter.chat_nonstream("", "hy3", {"messages": []}, 10.0))
    asyncio.run(adapter.aclose())

    assert json.loads(seen[0].content)["stream"] is True     # 出站形态被改写（真实通道唯一能收的）
    assert data["object"] == "chat.completion"
    message = data["choices"][0]["message"]
    assert message["content"] == "你好"
    assert message["reasoning_content"] == "先想"
    # 🔴 后续分片带空 `id`/空 `name` 不许清空已解析出的工具名与参数
    assert message["tool_calls"] == [{"index": 0, "type": "function", "id": "call-1",
                                      "function": {"name": "lookup",
                                                   "arguments": '{"q": "天气"}'}}]
    assert data["choices"][0]["finish_reason"] == "stop"
    assert data["usage"] == {"prompt_tokens": 11, "completion_tokens": 5}
    assert data["id"] == "c-rich" and data["created"] == 1776000000
    assert data["model"] == ""                               # 由调度器替换为网关模型名


def test_stream_only_without_any_chunk_fails_closed(monkeypatch):
    """一帧未收到 ⇒ `UpstreamError`（不把"上游什么都没给"当成空内容成功，§22.8-5）。"""
    seen, handler = _capture(monkeypatch)        # 回 JSON：SSE 解析拿不到任何帧
    adapter = _adapter(monkeypatch, transport=handler)
    with pytest.raises(UpstreamError, match="流式响应为空"):
        asyncio.run(adapter.chat_nonstream("", "hy3", {}, 10.0))
    asyncio.run(adapter.aclose())
    assert len(seen) == 1


# ============ 首条 system 补齐（workbuddy 通道的形状要求）============

def test_with_system_first_covers_exactly_four_shapes():
    """四条分支各自唯一：没这条脾气 / 已经有了 / 有但不在首位 / 一条都没有。"""
    from model_gateway.upstream.buddy.out import _with_system_first

    user = {"role": "user", "content": "把日志清掉"}
    mine = {"role": "system", "content": "客户端自己的引导"}
    text = "固定引导"

    # ① 档案没登记这条 ⇒ 原样返回（buddy 实测收得下，不许凭空注入）
    assert _with_system_first({"messages": [user]}, "") == {"messages": [user]}
    # ② 首条已是 system ⇒ 一字不改（客户端写的引导比网关补的更该生效）
    assert _with_system_first({"messages": [mine, user]}, text) == {"messages": [mine, user]}
    # ③ 有 system 但不在首位 ⇒ 只**移动**，内容不动（通道只认位置）
    assert _with_system_first({"messages": [user, mine]}, text)["messages"] == [mine, user]
    # ④ 一条 system 都没有 ⇒ 首位补固定文案，用户那几条原样留在后面
    assert _with_system_first({"messages": [user]}, text)["messages"] == [
        {"role": "system", "content": text}, user]


def test_with_system_first_never_mutates_the_callers_list():
    """🔴 IR body 还要进事件行与日志：适配器不许就地改那份列表（否则"用户发了什么"两个真相）。"""
    from model_gateway.upstream.buddy.out import _with_system_first

    messages = [{"role": "user", "content": "hi"}]
    body = {"messages": messages, "temperature": 0.3}
    out = _with_system_first(body, "固定引导")
    assert messages == [{"role": "user", "content": "hi"}]   # 调用方那份没被动
    assert out is not body and out["temperature"] == 0.3
    assert len(out["messages"]) == 2 and out["messages"][1] is messages[0]


def test_workbuddy_profile_carries_the_text_and_buddy_keeps_it_empty():
    """文案只登记在**有这条脾气**的产品档案上（用户 2026-10-04 指定），buddy 留空。"""
    from model_gateway.upstream.buddy import product as buddy_product
    from model_gateway.upstream.workbuddy import product as wb_product

    assert buddy_product._PROFILE.system_first_text == ""
    text = wb_product._PROFILE.system_first_text
    assert "充分理解" in text and "沟通" in text and "才可以" in text


def test_workbuddy_adapter_injects_and_buddy_does_not(monkeypatch):
    """出站体的实际形状：workbuddy 无 system 的请求被补齐；buddy 同形请求一字不加。"""
    from model_gateway.upstream.workbuddy import product as wb

    seen, handler = _capture(monkeypatch, sse=_sse())
    adapter = _adapter(monkeypatch, transport=handler, product="workbuddy",
                       name="acc-wb", factory=wb.build_out)
    asyncio.run(adapter.chat_nonstream("", "hy3", {"messages": [
        {"role": "user", "content": "hi"}]}, 10.0))
    asyncio.run(adapter.aclose())
    sent = json.loads(seen[0].content)["messages"]
    assert sent[0]["role"] == "system"
    assert sent[0]["content"] == wb._PROFILE.system_first_text
    assert sent[1] == {"role": "user", "content": "hi"}

    seen2, handler2 = _capture(monkeypatch, sse=_sse())
    adapter2 = _adapter(monkeypatch, transport=handler2)     # 缺省 factory = buddy
    asyncio.run(adapter2.chat_nonstream("", "hy3", {"messages": [
        {"role": "user", "content": "hi"}]}, 10.0))
    asyncio.run(adapter2.aclose())
    assert json.loads(seen2[0].content)["messages"] == [{"role": "user", "content": "hi"}]


# ============ 凭据自解 + 身份头 ============

def test_chat_nonstream_resolves_credential_from_account_and_sends_family_headers(monkeypatch):
    seen, handler = _capture(monkeypatch, sse=_sse())
    adapter = _adapter(monkeypatch, transport=handler, base_url="http://127.0.0.1:9")
    body = {"messages": [{"role": "user", "content": "hi"}]}
    data = asyncio.run(adapter.chat_nonstream("", "hy3", body, 10.0))
    asyncio.run(adapter.aclose())

    # buddy 通道只收流式（`stream:false` 实盘 4/4 回 400 code 11101）：非流式由族基类
    # 改走 SSE 后**本地聚合**，所以假上游这里照真实形状回 SSE（回 JSON 就是 mock 绿）。
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "你"
    assert json.loads(seen[0].content)["stream"] is True     # 出站必为流式
    request = seen[0]
    assert request.url.path == "/v2/chat/completions"          # 取证路径（不是 /chat/completions）
    assert request.headers["authorization"] == "Bearer TOKEN-FROM-ACCOUNT"
    assert request.headers["x-domain"] == "127.0.0.1"          # 与实际请求基址一致（credits.ts:222-228）
    # ⚠️ 本行与并行会话的 buddy 推理面取证同步（`upstream/buddy/out.py` 的 F3 修正：
    #    推理面 `X-Product` 发**归属名**，`SaaS` 是计费面 `credits.ts:236` 的值，
    #    套到推理面正是 DSH 记录在案的「后台归因不到产品」历史 bug；集成测试
    #    `test_buddy_out.py` 已同步）。Fix-γ 只同步这一条断言，未改其它用例。
    assert request.headers["x-product"] == "CodeBuddy"         # buddy-adapter.ts:1577 + product.ts:278
    assert request.headers["x-product-code"] == "codebuddy"    # product.ts:274
    assert request.headers["user-agent"] == "CodeBuddyIDE/1.106.1"
    # ⚠️ 同上（并行会话 F3 修正）：`X-User-Id` / `X-Enterprise-Id` 属**计费面**
    #    （`credits.ts:238-244`），推理面 `send()`（`:1564-1581`）**不发** —— 混面正是
    #    F3 的形态；凭据里的这两个字段仍在（本用例的 CRED），只是不外发。
    assert "x-user-id" not in request.headers and "x-enterprise-id" not in request.headers
    assert request.headers["x-ide-name"] == "CodeBuddy"        # :1574 + product.ts:278
    assert request.headers["x-ide-type"] == "CodeBuddy"        # :1575
    assert request.headers["x-ide-version"] == "1.106.1"       # :1576 + product.ts:279
    assert request.headers["x-agent-purpose"] == "conversation"  # :1573
    assert json.loads(request.content)["model"] == "hy3"


def test_config_key_is_never_used_for_product_resources(monkeypatch):
    """🔴 铁律 1 的判据：调度侧传进来的配置 Key **不参与鉴权**（凭据只在账号目录）。"""
    seen, handler = _capture(monkeypatch, sse=_sse())
    adapter = _adapter(monkeypatch, transport=handler)
    asyncio.run(adapter.chat_nonstream("sk-config-key-must-not-leak", "hy3", {}, 10.0))
    asyncio.run(adapter.aclose())
    assert "sk-config-key-must-not-leak" not in seen[0].headers.get("authorization", "")


def test_missing_credentials_fail_closed_without_upstream_call(monkeypatch):
    """凭据缺失 → `UpstreamError` 且**不发请求**（§22.8-5 fail closed）。"""
    seen, handler = _capture(monkeypatch)
    adapter = _adapter(monkeypatch, cred={}, transport=handler)
    with pytest.raises(UpstreamError, match="无凭据"):
        asyncio.run(adapter.chat_nonstream("", "hy3", {}, 10.0))
    asyncio.run(adapter.aclose())
    assert seen == []


def test_credential_without_access_token_is_rejected_before_request(monkeypatch):
    seen, handler = _capture(monkeypatch)
    adapter = _adapter(monkeypatch, cred={"refresh_token": "rt"}, transport=handler)
    with pytest.raises(UpstreamError, match="access_token"):
        asyncio.run(adapter.chat_nonstream("", "hy3", {}, 10.0))
    asyncio.run(adapter.aclose())
    assert seen == []


def test_prepare_body_default_only_sets_vendor_model(monkeypatch):
    """默认体塑造 = 只落供应商模型名（不塞自创字段；采样/推理注入归 IR 层）。

    样本用 `_PlainFamilyOut`（族基类**缺省形状**：`stream_only=False`）—— buddy 现在
    自带"只收流式"这条产品事实，拿它测缺省塑造会把那条强制改写也算进"缺省"。
    """
    seen, handler = _capture(monkeypatch)
    adapter = _adapter(monkeypatch, transport=handler,
                       factory=lambda account: _PlainFamilyOut(account))
    asyncio.run(adapter.chat_nonstream("", "hy3", {"messages": [], "temperature": 0.3}, 10.0))
    asyncio.run(adapter.aclose())
    body = json.loads(seen[0].content)
    assert body == {"messages": [], "temperature": 0.3, "model": "hy3"}
    assert "stream" not in body                     # 非 stream_only 产品照旧直连非流式端点


def test_needs_base64_probe_flows_from_the_account_payload(monkeypatch):
    """资源级能力探针经 `ProductAccount` 注入（冻结签名不允许追加形参）。"""
    probe = lambda model: model == "kimi-only-b64"  # noqa: E731
    adapter = _adapter(monkeypatch, needs_base64=probe)
    assert adapter._needs_base64("kimi-only-b64") is True
    assert adapter._needs_base64("hy3") is False
    asyncio.run(adapter.aclose())


# ============ 传输复用（SSE / 错误映射）============

def test_chat_stream_reuses_openai_sse_parsing(monkeypatch):
    seen, handler = _capture(monkeypatch, sse=_sse())
    adapter = _adapter(monkeypatch, transport=handler)

    async def run() -> list[dict]:
        return [chunk async for chunk in adapter.chat_stream("", "hy3", {"stream": True}, 10.0)]

    chunks = asyncio.run(run())
    asyncio.run(adapter.aclose())
    assert seen[0].url.path == "/v2/chat/completions"
    assert json.loads(seen[0].content)["stream"] is True
    assert [c["choices"][0]["delta"].get("content") for c in chunks if c.get("choices")] \
        == [None, "你", None]


def test_upstream_error_status_and_body_are_preserved(monkeypatch):
    seen, handler = _capture(monkeypatch, status=429,
                             body='{"error": {"type": "rate_limit_error", "message": "slow down"}}')
    adapter = _adapter(monkeypatch, transport=handler)
    with pytest.raises(UpstreamError) as e:
        asyncio.run(adapter.chat_nonstream("", "hy3", {}, 10.0))
    asyncio.run(adapter.aclose())
    assert e.value.status_code == 429
    assert "rate_limit_error" in (e.value.error_body or "")
    assert len(seen) == 1


# ============ 分派（§22.5-3：product 优先于 protocol）============

def test_build_adapter_dispatches_to_the_product_branch(monkeypatch):
    _install_store(monkeypatch, CRED)
    adapter = build_adapter("anthropic", "http://127.0.0.1:9/v1", product="buddy",
                            account_ref="acc-1")            # protocol 故意与产品无关
    assert isinstance(adapter, BuddyFamilyOut)
    assert adapter.chat_path == "/v2/chat/completions"      # 以 product 为准
    asyncio.run(adapter.aclose())


def test_build_adapter_without_product_keeps_legacy_behavior():
    adapter = build_adapter("openai", "http://127.0.0.1:9/v1")
    assert type(adapter) is OpenAIOutAdapter
    asyncio.run(adapter.aclose())


def test_build_product_adapter_rejects_empty_account_ref():
    with pytest.raises(ValueError, match="account_ref"):
        build_product_adapter("buddy", "  ", "http://127.0.0.1:9/v1")


def test_build_product_adapter_unknown_product_fails_loudly():
    with pytest.raises(KeyError, match="未登记的产品"):
        build_product_adapter("codearts", "acc", "http://127.0.0.1:9/v1")


def _unwire_product(monkeypatch, product: str) -> None:
    """把某产品的 `build_out` 打回"未接线"态（人工构造 M6-5b 之前的状态）。

    🔴 为什么不拿真产品当样本（2026-09-30 guard-fix 改造）：十款产品现已**全部接线**
    （M6-5b/M6-5c），注册表里已不存在"未接线产品" —— 原来那条"断言某个真产品未接线"
    编码的是**当时的波次状态**，产品全接线后即过期。这里沿**真实分派路径**注入：
    `build_product_adapter` → `import model_gateway.upstream.<product>.product` →
    `build_out(account)`，让"显式失败 / 按资源降级"的判据继续被真实验证；
    monkeypatch 用完自动还原，不影响其它用例。
    """
    import importlib

    module = importlib.import_module(f"model_gateway.upstream.{product}.product")

    def _not_wired(account):  # 签名同 §22.3 冻结签名 `build_out(account)`
        raise NotImplementedError(f"{product}.build_out 未接线（本用例人工构造）")

    monkeypatch.setattr(module, "build_out", _not_wired)


def test_build_product_adapter_reports_unwired_products(monkeypatch):
    """未接线产品的 `build_out` 必须**显式失败**（不得返回半成品）——错误原样冒出。"""
    _unwire_product(monkeypatch, "cline")
    with pytest.raises(NotImplementedError, match="cline.build_out"):
        build_product_adapter("cline", "acc", "http://127.0.0.1:9/v1")


def test_custom_protocol_products_schema_literal_is_openai():
    """`custom` 协议族物化时 schema 落 `openai` 字面量（§22.5-3），分派仍以 product 为准。"""
    from model_gateway.accounts import registry as reg
    meta = reg.get("qoder")
    assert meta.protocol == "custom"
    from model_gateway.accounts.materialize import _schema_protocol
    assert _schema_protocol(meta.protocol) == "openai"


# ============ 复用判据（§22.5-3：改绑账号必须重建；S-14 同族红证）============

def _product_config(account_ref: str = "acc-a", *, base_url: str = BASE) -> dict:
    return {
        "resources": [{"id": "res-p1", "name": "产品资源", "vendor": "", "preset": "",
                       "account": account_ref, "product": "buddy", "account_ref": account_ref,
                       "protocol": "openai", "base_url": base_url, "api_key": "",
                       "enabled": True, "access_mode": "api"}],
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": "res-p1", "model": "hy3"}]}],
    }


def _runtime(tmp_path: pathlib.Path):
    import yaml

    from model_gateway.config.loader import load_config
    from model_gateway.main import Runtime

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(_product_config(), allow_unicode=True), encoding="utf-8")
    return Runtime(load_config(cfg_path), cfg_path,
                   usage_dir=tmp_path / "usage", enums_path=tmp_path / "enums.yaml",
                   dialects_path=tmp_path / "dialects.yaml"), cfg_path


def test_product_resource_gets_a_family_adapter(tmp_path):
    rt, _ = _runtime(tmp_path)
    assert isinstance(rt.adapters["res-p1"], BuddyFamilyOut)
    asyncio.run(rt.aclose())


def test_unchanged_product_resource_reuses_the_adapter(tmp_path):
    rt, _ = _runtime(tmp_path)
    first = rt.adapters["res-p1"]
    ok, errors = asyncio.run(rt.reload_from_file())
    assert ok, errors
    assert rt.adapters["res-p1"] is first, "无变更却重建了适配器（每轮热重载都漏一个 client）"
    asyncio.run(rt.aclose())


def test_rebinding_the_account_rebuilds_the_adapter(tmp_path):
    """🔴 改绑账号**必须**换适配器（否则请求带着旧账号的凭据/身份头打上游 —— S-14 同族）。"""
    import yaml

    store.commit_login("buddy", "acc-a", {"access_token": "TOKEN-A"}, {})
    store.commit_login("buddy", "acc-b", {"access_token": "TOKEN-B"}, {})
    rt, cfg_path = _runtime(tmp_path)
    first = rt.adapters["res-p1"]
    assert first.account_ref == "acc-a"

    cfg_path.write_text(yaml.safe_dump(_product_config("acc-b"), allow_unicode=True),
                        encoding="utf-8")
    ok, errors = asyncio.run(rt.reload_from_file())
    assert ok, errors
    second = rt.adapters["res-p1"]
    assert second is not first, "改绑账号却复用了旧适配器（S-14 同族缺陷）"
    assert second.account_ref == "acc-b"
    assert first in rt._pending_close, "被换下的适配器没进待关清单（旧账 #48 同族）"
    asyncio.run(rt.aclose())


def test_credential_change_rebuilds_the_adapter(tmp_path):
    """重新登录（凭据文件变更）→ 连接身份变了 → 适配器重建（复用判据含凭据指纹）。"""
    store.commit_login("buddy", "acc-a", {"access_token": "TOKEN-OLD"}, {})
    rt, _ = _runtime(tmp_path)
    first = rt.adapters["res-p1"]

    store.commit_login("buddy", "acc-a", {"access_token": "TOKEN-NEW"}, {})
    ok, errors = asyncio.run(rt.reload_from_file())
    assert ok, errors
    assert rt.adapters["res-p1"] is not first, "凭据换了却复用旧适配器"
    asyncio.run(rt.aclose())


def test_unwired_product_resource_is_skipped_not_fatal(tmp_path, monkeypatch):
    """未接线产品的资源：`_apply` **跳过它**，其余资源与热重载照常（不打死热重载）。

    场景为**人工构造**（十款产品已全部接线，见 `_unwire_product`）：把 cline 的
    `build_out` 打回未接线态后装进配置 —— 判据不变：只有该资源降级，别的照常。
    """
    import yaml

    from model_gateway.config.loader import load_config
    from model_gateway.main import Runtime

    _unwire_product(monkeypatch, "cline")
    cfg = _product_config()
    cfg["resources"].append({"id": "res-c", "name": "Cline 资源（未接线，人工构造）",
                             "account": "c-1", "product": "cline", "account_ref": "c-1",
                             "protocol": "openai", "base_url": BASE, "api_key": "",
                             "enabled": True, "access_mode": "api"})
    cfg["models"][0]["resources"].append({"resource": "res-c", "model": "c-model"})
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    rt = Runtime(load_config(cfg_path), cfg_path, usage_dir=tmp_path / "usage",
                 enums_path=tmp_path / "enums.yaml", dialects_path=tmp_path / "dialects.yaml")
    assert isinstance(rt.adapters["res-p1"], BuddyFamilyOut)   # 接线产品照常
    assert "res-c" not in rt.adapters                          # 未接线 → 按资源降级
    ok, errors = asyncio.run(rt.reload_from_file())            # 热重载不得被打死
    assert ok, errors
    asyncio.run(rt.aclose())


# ============ B-2（M6-6 Fix-γ）：终态资源必须能被"重新登录 / 改绑账号"复活 ============

def _terminal_state(rt):
    return rt.resources.registry[("res-p1", "hy3")]


def _make_it_dead(rt):
    """复刻 401 判死（终态）——出站 401 → `ResourceManager.disable`（scheduler 的落点）。"""
    st = _terminal_state(rt)
    rt.resources.disable(st, "upstream 401：凭据被上游拒绝")
    assert st.status == "disabled"
    assert rt.resources.pick_and_acquire("m", set()) is None, "判死后不得再进生效集"
    return st


def test_relogin_revives_a_dead_product_resource(tmp_path):
    """🔴 B-2：重新登录同一账号（凭据变化）= 新的连接身份 → 401 判死的资源回 active。

    产品资源的"Key"在**账号目录**里（配置里恒为空串），所以连接身份指纹必须含
    `product + account_ref + 凭据指纹` —— 否则用户按提示"重新登录"也永远 503
    （评审报告 B-2 的红证：reload=True、适配器重建，但 status 停在 disabled）。

    红证（撤修复）：`_conn_fingerprint` 不算凭据分量时，本用例的 status 停在 disabled。
    """
    store.commit_login("buddy", "acc-a", {"access_token": "TOKEN-OLD"}, {})
    rt, _ = _runtime(tmp_path)
    st = _make_it_dead(rt)

    store.commit_login("buddy", "acc-a", {"access_token": "TOKEN-NEW"}, {})
    ok, errors = asyncio.run(rt.reload_from_file())
    assert ok, errors
    assert st.status == "active", "重新登录后仍是 disabled —— 用户按提示操作却永远 503"
    assert st.C == 0 and st.cooldown_until == 0.0 and st.last_error is None
    assert rt.resources.pick_and_acquire("m", set()) is st, "复活后必须回到生效集"
    asyncio.run(rt.aclose())


def test_rebinding_the_account_also_revives_a_dead_product_resource(tmp_path):
    """🔴 B-2 的另一半：改绑到另一个账号同样是"新的连接身份" → 终态清零。

    红证（撤修复）：同上 —— 指纹不含 `account_ref` 时，改绑后仍 disabled。
    """
    import yaml

    store.commit_login("buddy", "acc-a", {"access_token": "TOKEN-A"}, {})
    store.commit_login("buddy", "acc-b", {"access_token": "TOKEN-B"}, {})
    rt, cfg_path = _runtime(tmp_path)
    st = _make_it_dead(rt)

    cfg_path.write_text(yaml.safe_dump(_product_config("acc-b"), allow_unicode=True),
                        encoding="utf-8")
    ok, errors = asyncio.run(rt.reload_from_file())
    assert ok, errors
    assert st.status == "active", "改绑账号后仍 disabled（改绑 = 换连接身份）"
    asyncio.run(rt.aclose())


def test_same_credentials_do_not_reset_the_terminal_state(tmp_path):
    """反向护栏：凭据**没变**的热重载不得把 401 判死清零（否则"判死"名存实亡）。"""
    store.commit_login("buddy", "acc-a", {"access_token": "TOKEN-SAME"}, {})
    rt, _ = _runtime(tmp_path)
    st = _make_it_dead(rt)

    ok, errors = asyncio.run(rt.reload_from_file())
    assert ok, errors
    assert st.status == "disabled", "连接身份没变却清掉了 401 判死 —— 反向红"
    asyncio.run(rt.aclose())


def test_fingerprint_flag_only_reaches_anthropic_key_adapter(monkeypatch):
    """D-5（2026-10-06 核验轮）：装配点 fingerprint 开关必须**只**作用于 anthropic
    协议的按 Key 资源——zcode 产品资源走 build_product_adapter 自建出站（开关本就
    不适用），openai 资源同理。旧条件 `protocol == "anthropic"` 的泛化在 main.py
    已收窄为 `product == "zcode"`；本条钉分发点的形状：开关不改写 openai 路径。"""
    import httpx

    from model_gateway.adapters import build_adapter
    from model_gateway.adapters.anthropic_out import AnthropicOutAdapter

    a = build_adapter("anthropic", "http://127.0.0.1:9", fingerprint=True)
    assert isinstance(a, AnthropicOutAdapter)
    assert a.fingerprint is True          # zcode 形状：开关到达

    b = build_adapter("openai", "http://127.0.0.1:9", fingerprint=True)
    assert isinstance(b, httpx.AsyncClient) or type(b).__name__ == "OpenAIOutAdapter"
    assert not isinstance(b, AnthropicOutAdapter)   # openai 不吃这个开关
    assert getattr(b, "fingerprint", None) in (None, False)
