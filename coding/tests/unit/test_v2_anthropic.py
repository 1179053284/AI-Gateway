"""v2.0 §18 anthropic_out 单元测试：请求/响应转换、SSE 翻译、usage 映射。

判据（§18.2）：
① duck typing 4 方法与 `openai_out` 同形
③ usage **必须在适配器内映射**（input/output → prompt/completion），否则恒走本地估算
⑤ 2xx 非 JSON/SSE → `UpstreamError(status_code=None)`（现有分类器下会落到 RETRYABLE）
"""

from __future__ import annotations

import json

import pytest

from model_gateway.adapters.anthropic_out import (
    ANTHROPIC_VERSION,
    AnthropicOutAdapter,
    _StreamTranslator,
    anthropic_to_openai,
    openai_to_anthropic,
    parse_sse_line,
)


# ---------- ① 契约：4 方法与 openai_out 同形 ----------

def test_adapter_implements_duck_typing_methods():
    from model_gateway.adapters.openai_out import OpenAIOutAdapter
    a = AnthropicOutAdapter("http://127.0.0.1:9/v1")
    o = OpenAIOutAdapter("http://127.0.0.1:9/v1")
    for m in ("chat_nonstream", "chat_stream", "images_generate", "aclose"):
        assert callable(getattr(a, m)) and callable(getattr(o, m)), m


def test_url_and_headers():
    a = AnthropicOutAdapter("http://127.0.0.1:9/v1")
    assert a._url() == "http://127.0.0.1:9/v1/messages"
    h = AnthropicOutAdapter._headers("k")
    # Anthropic 用 x-api-key（不是 Bearer）+ 固定 anthropic-version
    assert h["x-api-key"] == "k"
    assert h["anthropic-version"] == ANTHROPIC_VERSION


def test_url_tolerates_base_without_v1():
    assert AnthropicOutAdapter("http://h/api")._url() == "http://h/api/v1/messages"


def test_images_generate_raises_no_failover():
    """Anthropic Messages 协议无图像生成 —— 明确报错（`no_failover` 防切资源重试）。"""
    from model_gateway.core.errors import UpstreamError
    a = AnthropicOutAdapter("http://h/v1")
    with pytest.raises(UpstreamError) as e:
        import asyncio
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            a.images_generate("k", "m", {}, 5))
    assert e.value.no_failover is True


# ---------- 请求转换：OpenAI → Anthropic ----------

def test_system_messages_joined_into_single_system_string():
    """多条 system/developer → **单个** `system` 字符串（`\n\n` 拼接）。"""
    body = {"messages": [
        {"role": "system", "content": "你是助手"},
        {"role": "developer", "content": "用中文"},
        {"role": "user", "content": "hi"},
    ]}
    out = openai_to_anthropic(body, "claude-sonnet-4")

    assert out["system"] == "你是助手\n\n用中文"
    assert out["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


def test_string_content_becomes_text_block():
    out = openai_to_anthropic({"messages": [{"role": "user", "content": "hi"}]}, "m")
    assert out["messages"][0]["content"] == [{"type": "text", "text": "hi"}]


def test_tool_result_message_mapped():
    """`role:"tool"` + tool_call_id → `role:"user"` + `tool_result` block。"""
    body = {"messages": [
        {"role": "tool", "tool_call_id": "c1", "content": "结果"},
    ]}
    out = openai_to_anthropic(body, "m")
    blk = out["messages"][0]["content"][0]

    assert out["messages"][0]["role"] == "user"
    assert blk["type"] == "tool_result" and blk["tool_use_id"] == "c1"


def test_assistant_tool_calls_become_tool_use_blocks():
    body = {"messages": [{"role": "assistant", "content": "",
                          "tool_calls": [{"id": "t1", "type": "function",
                                          "function": {"name": "f", "arguments": '{"a":1}'}}]}]}
    out = openai_to_anthropic(body, "m")
    blk = out["messages"][0]["content"][0]

    assert blk["type"] == "tool_use" and blk["id"] == "t1" and blk["name"] == "f"
    assert blk["input"] == {"a": 1}       # arguments（JSON 串）→ input（对象）


def test_tool_arguments_that_fail_to_parse_are_kept_raw():
    out = openai_to_anthropic({"messages": [{"role": "assistant",
                                             "tool_calls": [{"id": "t", "function": {
                                                 "name": "f", "arguments": "not-json"}}]}]}, "m")
    assert out["messages"][0]["content"][0]["input"] == {"_raw_arguments": "not-json"}


def test_base64_image_mapped_and_remote_url_dropped():
    """🔴 **仅** data-URI 生效；远程 http(s) 图片 URL **静默丢弃**（§18.2 ⑥）。"""
    body = {"messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
        {"type": "text", "text": "看图"},
    ]}]}
    blocks = openai_to_anthropic(body, "m")["messages"][0]["content"]

    assert blocks[0] == {"type": "image",
                         "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}
    assert len(blocks) == 2 and blocks[1]["type"] == "text"     # 远程 URL 被丢弃


def test_max_tokens_priority_and_default():
    assert openai_to_anthropic({"messages": [], "max_tokens": 10}, "m")["max_tokens"] == 10
    out = openai_to_anthropic({"messages": [], "max_completion_tokens": 20}, "m")
    assert out["max_tokens"] == 20
    # Anthropic max_tokens **必填** → 缺省 4096
    assert openai_to_anthropic({"messages": []}, "m")["max_tokens"] == 4096


def test_stop_sequences_from_string_and_list():
    assert openai_to_anthropic({"messages": [], "stop": "x"}, "m")["stop_sequences"] == ["x"]
    assert openai_to_anthropic({"messages": [], "stop": ["a", "b"]}, "m")["stop_sequences"] == ["a", "b"]


def test_tool_choice_three_states():
    assert openai_to_anthropic({"messages": [], "tool_choice": "auto"}, "m")["tool_choice"] == {"type": "auto"}
    assert openai_to_anthropic({"messages": [], "tool_choice": "required"}, "m")["tool_choice"] == {"type": "any"}
    out = openai_to_anthropic({"messages": [], "tool_choice": {"function": {"name": "f"}}}, "m")
    assert out["tool_choice"] == {"type": "tool", "name": "f"}


def test_tools_map_parameters_to_input_schema():
    body = {"messages": [], "tools": [
        {"type": "function", "function": {"name": "f", "description": "d",
                                          "parameters": {"type": "object"}}}]}
    out = openai_to_anthropic(body, "m")["tools"][0]

    assert out["name"] == "f" and out["input_schema"] == {"type": "object"}


def test_tools_without_schema_get_empty_object():
    body = {"messages": [], "tools": [{"type": "function", "function": {"name": "f"}}]}
    assert openai_to_anthropic(body, "m")["tools"][0]["input_schema"] == {
        "type": "object", "properties": {}}


def test_provider_prefix_stripped():
    assert openai_to_anthropic({"messages": []}, "openai/gpt-4")["model"] == "gpt-4"


def test_sampling_params_passthrough():
    out = openai_to_anthropic({"messages": [], "temperature": 0.7, "top_p": 0.9}, "m")
    assert out["temperature"] == 0.7 and out["top_p"] == 0.9


def test_openai_only_fields_are_dropped():
    """OpenAI 有、Anthropic 无对应语义的字段 → **丢弃**（§18.2 ⑥）。"""
    out = openai_to_anthropic({"messages": [], "presence_penalty": 0.5, "seed": 1,
                               "response_format": {"type": "json_object"}}, "m")
    for k in ("presence_penalty", "seed", "response_format"):
        assert k not in out


# ---------- 响应转换：Anthropic → OpenAI ----------

def test_thinking_block_becomes_reasoning_content():
    """🔴 `thinking` block → `reasoning_content`（对齐 DeepSeek 风格客户端）。"""
    resp = {"content": [{"type": "thinking", "thinking": "让我想想"},
                        {"type": "text", "text": "答案"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 11, "output_tokens": 22}}
    out = anthropic_to_openai(resp, "m")

    assert out["choices"][0]["message"]["content"] == "答案"
    assert out["choices"][0]["message"]["reasoning_content"] == "让我想想"


def test_tool_use_block_becomes_openai_tool_call():
    resp = {"content": [{"type": "tool_use", "id": "t1", "name": "f", "input": {"a": 1}}],
            "stop_reason": "tool_use", "usage": {"input_tokens": 1, "output_tokens": 2}}
    tc = anthropic_to_openai(resp, "m")["choices"][0]["message"]["tool_calls"][0]

    assert tc["id"] == "t1" and tc["function"]["name"] == "f"
    assert json.loads(tc["function"]["arguments"]) == {"a": 1}   # arguments 是 **JSON 字符串**
    assert resp  # 保留引用（无副作用检查）


@pytest.mark.parametrize("stop,expect", [("end_turn", "stop"), ("max_tokens", "length"),
                                         ("tool_use", "tool_calls"), ("stop_sequence", "stop")])
def test_stop_reason_mapping(stop, expect):
    out = anthropic_to_openai({"content": [], "stop_reason": stop}, "m")
    assert out["choices"][0]["finish_reason"] == expect


def test_usage_mapped_to_openai_names():
    """🔴 **必须在适配器内映射**（③）—— 否则 `scheduler._usage_from` 读不到，恒走本地估算。"""
    out = anthropic_to_openai({"content": [], "usage": {"input_tokens": 30, "output_tokens": 12}}, "m")

    assert out["usage"]["prompt_tokens"] == 30
    assert out["usage"]["completion_tokens"] == 12
    assert out["usage"]["total_tokens"] == 42


def test_usage_missing_is_zero_not_none():
    assert anthropic_to_openai({"content": []}, "m")["usage"]["prompt_tokens"] == 0


# ---------- SSE 解析与翻译 ----------

def test_parse_sse_line_event_and_data():
    assert parse_sse_line("event: content_block_delta") == ("content_block_delta", {})
    assert parse_sse_line('data: {"type":"text_delta","text":"hi"}') == (
        "data", {"type": "text_delta", "text": "hi"})
    assert parse_sse_line(": keep-alive") is None
    assert parse_sse_line("data: not-json") is None


def test_stream_emits_role_first_then_text():
    """首个增量前补发 `{"role":"assistant","content":""}`（OpenAI 客户端期望）。"""
    t = _StreamTranslator("m")
    chunks = t.feed("message_start", {"type": "message_start",
                                      "message": {"usage": {"input_tokens": 5}}})
    chunks += t.feed("content_block_delta",
                     {"type": "content_block_delta", "index": 0,
                      "delta": {"type": "text_delta", "text": "hi"}})

    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    assert chunks[-1]["choices"][0]["delta"] == {"content": "hi"}


def test_stream_thinking_delta_to_reasoning_content():
    t = _StreamTranslator("m")
    t.feed("message_start", {"type": "message_start", "message": {"usage": {}}})
    chunks = t.feed("content_block_delta",
                    {"type": "content_block_delta", "index": 0,
                     "delta": {"type": "thinking_delta", "thinking": "…"}})
    assert chunks[-1]["choices"][0]["delta"] == {"reasoning_content": "…"}


def test_stream_tool_call_index_mapping():
    """Anthropic `content block index` → OpenAI `tool_calls index`（源块 idx ≠ 工具序号时尤其重要）。"""
    t = _StreamTranslator("m")
    t.feed("message_start", {"type": "message_start", "message": {"usage": {}}})
    start = t.feed("content_block_start",
                   {"type": "content_block_start", "index": 3,
                    "content_block": {"type": "tool_use", "id": "t1", "name": "f"}})
    delta = t.feed("content_block_delta",
                   {"type": "content_block_delta", "index": 3,
                    "delta": {"type": "input_json_delta", "partial_json": '{"a"'}})

    tc = start[-1]["choices"][0]["delta"]["tool_calls"][0]
    assert tc["index"] == 0                      # 工具序号 0，而非块索引 3
    assert tc["function"]["name"] == "f"
    assert delta[-1]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"] == '{"a"'


def test_stream_message_delta_finish_reason_and_usage():
    t = _StreamTranslator("m")
    t.feed("message_start", {"type": "message_start", "message": {"usage": {}}})
    chunks = t.feed("message_delta",
                    {"type": "message_delta",
                     "delta": {"stop_reason": "max_tokens"},
                     "usage": {"output_tokens": 7}})
    c = chunks[-1]["choices"][0]

    assert c["finish_reason"] == "length"
    assert chunks[-1]["usage"]["completion_tokens"] == 7


def test_stream_error_event_raises():
    """流内 `error` 事件**不吞** —— 必须抛（§18.2 / 参考实现的"不假装成功"）。"""
    from model_gateway.core.errors import UpstreamError
    t = _StreamTranslator("m")
    with pytest.raises(UpstreamError, match="stream error"):
        t.feed("error", {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})


# ---------- ⑤ 2xx 非 JSON/SSE ----------

def test_non_json_error_uses_none_status_code():
    """🔴 `status_code=None` → 分类器落 `RETRYABLE`（进入 C 计数 + 冷却）。

    若传 200，分类器会落 `BAD_REQUEST`（原样透传、不冷却），语义就散了（§18.2 ⑤）。
    """
    err = AnthropicOutAdapter._non_json_error(200, "text/html", "<html>WAF</html>")
    assert err.status_code is None
    assert "non-json" in str(err)


def test_error_type_extracted_from_anthropic_body():
    from model_gateway.adapters.anthropic_out import _extract_anthropic_error_type
    assert _extract_anthropic_error_type('{"error":{"type":"invalid_request_error"}}') == \
        "invalid_request_error"
    assert _extract_anthropic_error_type("not json") == ""


# ---------- 双通道鉴权头（§17 / Q27-② · 验收修正的功能缺口）----------

def _jwt() -> str:
    """形似 JWT 的三段点分串（本函数不解析 claims，只按形状判定）。"""
    return "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiMSJ9.abc-signature"


def test_jwt_credential_uses_bearer():
    """🔴 **Plan 通道用 `Authorization: Bearer <jwt>`**（验收发现的功能缺口）。

    原实现一律发 `x-api-key` → ZCode Plan 通道**必然 401**。
    """
    h = AnthropicOutAdapter._headers(_jwt())
    assert "Authorization" in h and h["Authorization"].startswith("Bearer ")
    assert "x-api-key" not in h


def test_plain_key_uses_x_api_key():
    """API Key 通道仍用 `x-api-key`（不改变既有行为，向后兼容）。"""
    h = AnthropicOutAdapter._headers("sk-plain-key")
    assert h["x-api-key"] == "sk-plain-key"
    assert "Authorization" not in h


def test_device_mid_header_when_present():
    h = AnthropicOutAdapter._headers("k", "mid-1")
    assert h["X-Device-Mid"] == "mid-1"


def test_anthropic_version_header_always_present():
    for key in ("sk-a", _jwt()):
        assert AnthropicOutAdapter._headers(key)["anthropic-version"] == ANTHROPIC_VERSION
