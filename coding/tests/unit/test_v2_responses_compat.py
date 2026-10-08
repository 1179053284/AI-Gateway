"""`/v1/responses` 兼容面单元测试（请求翻译 / 响应组装 / SSE 编码）。

判据（协议真值 = 本地 OpenAI 官方 SDK `openai@6.26.0` 的
`resources/responses/responses.d.ts`；成熟实现参考 = `deepseek-harness-codearts`
`src/openai-gateway/responses.ts` 的 43 条契约，只读、未采用其代码）：

① **能 1:1 表达的必须忠实翻译**：instructions / input / tools(function) / tool_choice /
   temperature / top_p / max_output_tokens / parallel_tool_calls / reasoning.effort /
   text.format（→ `response_format`）；
② **纯提示类接受并忽略**（store/include/prompt_cache_key/metadata/user/truncation/
   service_tier/safety_identifier/…）：请求照常成功，字段不进 chat body；
③ 🔴 **语义会变又做不到的必须明确 400**（previous_response_id/conversation/
   background:true/input_file/file_id 图片/未知 input item）：绝不静默忽略；
④ **工具**：function 忠实翻译；namespace 摊平成 `ns__child` 且**响应侧还原**；custom/
   tool_search/内置工具**丢弃 + 上报**（绝不 400 —— 那是「整轮对话不可用」的代价）；
⑤ **SSE**：事件生命周期齐（created/in_progress/item.added/part/delta/done/item.done/
   终态）、`sequence_number` 连续、`item_id` 稳定、**不发 `[DONE]`**；
⑥ **usage 官方口径**：`input_tokens` 含缓存命中、命中单列 `cached_tokens`、
   `total_tokens` 取 `max(上游报的, 输入+输出)`；
⑦ **可空字段一个都不能少**（官方 SDK 按 schema 解析，缺键 = 客户端反序列化崩）。
"""

from __future__ import annotations

import json

import pytest

from model_gateway.api.responses_compat import (
    ReqMeta,
    ResponsesRequestError,
    ResponsesStreamEncoder,
    build_chat_request,
    flat_tool_name,
    translate_chat_result,
)
from model_gateway.core.ir import lift_reasoning_from_body, merge_reasoning


# ---------- 工具：摊平/还原/丢弃 ----------

def test_flat_tool_name_is_bounded_and_collision_resistant():
    assert flat_tool_name("mcp__files__", "read") == "mcp__files____read"
    long_a = flat_tool_name("ns" * 40, "child_a")
    long_b = flat_tool_name("ns" * 40, "child_b")
    assert len(long_a) <= 64 and len(long_b) <= 64
    assert long_a != long_b  # 截断后必须仍可区分（8 位哈希）


def test_namespace_tools_flattened_and_registered_for_restore():
    t = build_chat_request({
        "model": "m", "input": "hi",
        "tools": [{"type": "namespace", "name": "mcp__files__", "tools": [
            {"type": "function", "name": "read", "parameters": {"type": "object"}}]}]})
    assert [x["function"]["name"] for x in t.chat_body["tools"]] == ["mcp__files____read"]
    assert t.ns_map["mcp__files____read"] == ("mcp__files__", "read")
    assert t.dropped_tools == []


def test_function_tool_accepts_flat_and_nested_shapes():
    t = build_chat_request({"model": "m", "input": "hi", "tools": [
        {"type": "function", "name": "flat", "description": "d",
         "parameters": {"type": "object"}, "strict": True},
        {"type": "function", "function": {"name": "nested",
                                          "parameters": {"type": "object"}}},
    ]})
    tools = {x["function"]["name"]: x["function"] for x in t.chat_body["tools"]}
    assert set(tools) == {"flat", "nested"}
    assert tools["flat"]["strict"] is True          # 客户端显式声明 → 忠实转交
    assert tools["nested"]["description"] == ""


def test_unrepresentable_tools_dropped_with_report_never_400():
    """custom/tool_search/内置工具丢弃 + 上报，**请求仍然成功**（参考实现的血泪口径）。"""
    t = build_chat_request({"model": "m", "input": "hi", "tools": [
        {"type": "function", "name": "shell", "parameters": {"type": "object"}},
        {"type": "custom", "name": "apply_patch", "format": {"type": "grammar"}},
        {"type": "tool_search"},
        {"type": "web_search"},
    ]})
    assert [x["function"]["name"] for x in t.chat_body["tools"]] == ["shell"]
    assert t.dropped_tools == ["custom/apply_patch", "tool_search", "web_search"]


def test_tool_name_collision_first_wins_and_loser_not_restorable():
    """重名先到先得；**被丢弃者不得进还原表**（否则上游调用被静默误路由）。"""
    t = build_chat_request({"model": "m", "input": "hi", "tools": [
        {"type": "function", "name": "ns__dup", "parameters": {"type": "object"}},
        {"type": "namespace", "name": "ns", "tools": [
            {"type": "function", "name": "dup", "parameters": {"type": "object"}}]},
    ]})
    assert [x["function"]["name"] for x in t.chat_body["tools"]] == ["ns__dup"]
    assert "ns__dup" not in t.ns_map
    assert t.dropped_tools and "重名" in t.dropped_tools[0]


def test_blank_child_name_does_not_become_ghost_tool():
    t = build_chat_request({"model": "m", "input": "hi", "tools": [
        {"type": "namespace", "name": "ns", "tools": [
            {"type": "function", "name": "   ", "parameters": {}}]}]})
    assert "tools" not in t.chat_body
    assert t.ns_map == {}
    assert t.dropped_tools


def test_tool_name_is_trimmed_everywhere():
    t = build_chat_request({"model": "m", "input": "hi", "tools": [
        {"type": "namespace", "name": " ns ", "tools": [
            {"type": "function", "name": " read ", "parameters": {"type": "object"}}]}]})
    assert [x["function"]["name"] for x in t.chat_body["tools"]] == ["ns__read"]
    assert t.ns_map == {"ns__read": ("ns", "read")}


def test_empty_function_name_is_400():
    with pytest.raises(ResponsesRequestError) as e:
        build_chat_request({"model": "m", "input": "hi",
                            "tools": [{"type": "function", "name": "  "}]})
    assert e.value.status == 400


# ---------- tool_choice ----------

@pytest.mark.parametrize("raw,expected", [
    ("auto", "auto"), ("none", "none"), ("required", "required"),
    ({"type": "function", "name": "f"}, {"type": "function", "function": {"name": "f"}}),
])
def test_tool_choice_translated(raw, expected):
    t = build_chat_request({"model": "m", "input": "hi",
                            "tools": [{"type": "function", "name": "f"}],
                            "tool_choice": raw})
    assert t.chat_body["tool_choice"] == expected


def test_tool_choice_default_not_sent():
    t = build_chat_request({"model": "m", "input": "hi"})
    assert "tool_choice" not in t.chat_body


def test_tool_choice_unknown_type_is_400():
    with pytest.raises(ResponsesRequestError):
        build_chat_request({"model": "m", "input": "hi", "tool_choice": "banana"})


# ---------- input ----------

def test_input_string_form_is_user_message():
    t = build_chat_request({"model": "m", "input": "你好", "instructions": "系统"})
    assert t.chat_body["messages"] == [
        {"role": "system", "content": "系统"}, {"role": "user", "content": "你好"}]


def test_input_roles_images_and_assistant_merge():
    """developer→system、图片 → image_url part、连续 assistant 项合并成一条。"""
    t = build_chat_request({"model": "m", "input": [
        {"type": "message", "role": "developer", "content": "DEV"},
        {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "看图"},
            {"type": "input_image", "image_url": "data:image/png;base64,AAA"}]},
        {"type": "reasoning", "id": "rs_1", "summary": []},
        {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "我来调用"}]},
        {"type": "function_call", "call_id": "call_1", "name": "read", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_1", "output": "内容"},
    ]})
    msgs = t.chat_body["messages"]
    assert msgs[0] == {"role": "system", "content": "DEV"}
    assert msgs[1]["content"][1] == {"type": "image_url",
                                     "image_url": {"url": "data:image/png;base64,AAA"}}
    assert len(msgs) == 4                                   # reasoning 已丢弃
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool"]
    assert msgs[2]["role"] == "assistant"                   # 文本 + tool_call 合并
    assert msgs[2]["content"] == "我来调用"
    assert msgs[2]["tool_calls"][0]["id"] == "call_1"
    assert msgs[3] == {"role": "tool", "tool_call_id": "call_1", "content": "内容"}


def test_consecutive_assistant_items_never_produce_two_assistant_messages():
    """🔴 连续 assistant 项**必须**合并成一条。

    Responses 把「助手说话」与「助手发起工具调用」拆成两个 item，chat 把两者放在同一条
    assistant 消息里。照 item 一一映射会让**每一个用过工具的会话**给上游留下连续两条
    assistant —— 经 anthropic 协议资源出站时（`anthropic_out.openai_to_anthropic`）
    Anthropic 要求 user/assistant 交替，这类历史会被上游拒绝或行为异常。
    """
    t = build_chat_request({"model": "m", "input": [
        {"type": "message", "role": "user", "content": "hi"},
        {"type": "message", "role": "assistant", "content": "先说一句"},
        {"type": "function_call", "call_id": "c1", "name": "f", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "r"},
        {"type": "message", "role": "assistant", "content": "再补一句"},
        {"type": "message", "role": "assistant", "content": "又一句"},
    ]})
    roles = [m["role"] for m in t.chat_body["messages"]]
    assert roles == ["user", "assistant", "tool", "assistant"]
    merged = t.chat_body["messages"][1]
    assert merged["content"] == "先说一句" and merged["tool_calls"][0]["id"] == "c1"
    assert t.chat_body["messages"][3]["content"] == "再补一句又一句"


def test_replayed_namespace_function_call_maps_back_to_flat_name():
    """历史 function_call 带 namespace → 必须换回扁平名（否则上游认为模型调了没声明过的工具）。"""
    t = build_chat_request({"model": "m", "input": [
        {"type": "message", "role": "user", "content": "hi"},
        {"type": "function_call", "call_id": "c1", "name": "read",
         "namespace": "mcp__files__", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "x"},
    ]})
    assert t.chat_body["messages"][1]["tool_calls"][0]["function"]["name"] == \
        "mcp__files____read"


def test_input_tool_output_with_image_parts_is_passed_through():
    t = build_chat_request({"model": "m", "input": [
        {"type": "message", "role": "user", "content": "hi"},
        {"type": "function_call_output", "call_id": "c1", "output": [
            {"type": "input_text", "text": "截图"},
            {"type": "input_image", "image_url": "data:image/png;base64,AAA"}]},
    ]})
    assert t.chat_body["messages"][1]["content"][1]["type"] == "image_url"


@pytest.mark.parametrize("bad,needle", [
    ({"input": [{"type": "item_reference", "id": "x"}]}, "item_reference"),
    ({"input": [{"type": "mcp_call", "id": "x"}]}, "mcp_call"),
    ({"input": [{"type": "message", "role": "user",
                 "content": [{"type": "input_file", "file_id": "f"}]}]}, "input_file"),
    ({"input": [{"type": "message", "role": "user",
                 "content": [{"type": "input_image", "file_id": "img"}]}]}, "file_id"),
    ({"input": [{"type": "message", "role": "robot", "content": "x"}]}, "角色"),
])
def test_unsupported_input_items_are_400_with_actionable_message(bad, needle):
    with pytest.raises(ResponsesRequestError) as e:
        build_chat_request({"model": "m", **bad})
    assert e.value.status == 400
    assert needle in str(e.value)


def test_input_without_user_or_tool_is_400():
    with pytest.raises(ResponsesRequestError):
        build_chat_request({"model": "m", "input": [
            {"type": "message", "role": "assistant", "content": "只有助手话"}]})


# ---------- 三档字段处置 ----------

@pytest.mark.parametrize("field,value", [
    ("previous_response_id", "resp_1"), ("conversation", "conv_1"),
    ("background", True),
    # 显式 store:true：同类上游处置相反（DeepSeek 静默忽略 = 它自己是终局；智谱 GLM 真多轮），
    # 网关恒回 store:false / GET 恒 404 ⇒ 接受它 = 纯粹的静默降级 ⇒ 必须 400。
    ("store", True),
])
def test_state_semantics_is_400(field, value):
    with pytest.raises(ResponsesRequestError) as e:
        build_chat_request({"model": "m", "input": "hi", field: value})
    assert e.value.code == "unsupported_parameter"
    assert e.value.status == 400


@pytest.mark.parametrize("field,value", [
    ("store", False), ("include", ["reasoning.encrypted_content"]),
    ("prompt_cache_key", "k"), ("prompt_cache_retention", "24h"),
    ("service_tier", "auto"), ("safety_identifier", "s"),
    ("metadata", {"a": "b"}), ("user", "u"), ("truncation", "auto"),
    ("max_tool_calls", 3), ("stream_options", {"include_obfuscation": False}),
])
def test_hint_fields_accepted_and_not_forwarded(field, value):
    """② 档：不改变本次内容语义 ⇒ 接受并忽略（不进 chat body，请求照常成功）。"""
    t = build_chat_request({"model": "m", "input": "hi", field: value})
    assert field not in t.chat_body


def test_background_false_is_accepted():
    t = build_chat_request({"model": "m", "input": "hi", "background": False})
    assert t.chat_body["messages"][-1]["content"] == "hi"


def test_sampling_and_limits_forwarded():
    t = build_chat_request({"model": "m", "input": "hi", "temperature": 0.3,
                            "top_p": 0.9, "max_output_tokens": 128,
                            "parallel_tool_calls": False,
                            "tools": [{"type": "function", "name": "f"}]})
    body = t.chat_body
    assert body["temperature"] == 0.3
    assert body["top_p"] == 0.9
    assert body["max_tokens"] == 128
    assert body["parallel_tool_calls"] is False
    assert t.meta.max_output_tokens == 128


def test_text_format_maps_to_response_format():
    t = build_chat_request({"model": "m", "input": "hi", "text": {"format": {
        "type": "json_schema", "name": "s", "strict": True,
        "schema": {"type": "object", "properties": {}}}}})
    assert t.chat_body["response_format"] == {"type": "json_schema", "json_schema": {
        "name": "s", "schema": {"type": "object", "properties": {}}, "strict": True}}


def test_text_format_plain_text_does_not_add_response_format():
    t = build_chat_request({"model": "m", "input": "hi", "text": {"format": {"type": "text"}}})
    assert t.chat_body.get("response_format") == {"type": "text"}


def test_reasoning_effort_goes_through_ir_lift():
    """reasoning.effort 用 ir 的同一口径：lift 提取显式值，关闭档由 merge_reasoning 判定。"""
    t = build_chat_request({"model": "m", "input": "hi",
                            "reasoning": {"effort": "none"}})
    assert t.chat_body["reasoning_effort"] == "none"
    spec = lift_reasoning_from_body(t.chat_body)
    assert spec is not None and spec.effort == "none"
    assert "reasoning_effort" not in t.chat_body      # 提升后出站不重复注入（Q15）
    merged = merge_reasoning(spec, None)
    assert merged is not None and merged.enabled is False   # `none` 族 = 显式关闭
    high = merge_reasoning(lift_reasoning_from_body({"reasoning_effort": "high"}), None)
    assert high is not None and high.enabled is True


# ---------- 非流式响应 ----------

def _chat_result(**over):
    base = {"choices": [{"index": 0, "message": {"role": "assistant", "content": "答案"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 12}}
    base.update(over)
    return base


def test_response_object_has_every_nullable_field():
    """⑦ 可空字段一个都不能少（官方 SDK 按 schema 解析）。"""
    d = translate_chat_result(_chat_result(), "resp_1", "gw", ReqMeta(), {})
    for key in ("id", "object", "created_at", "status", "background", "error",
                "incomplete_details", "instructions", "max_output_tokens", "model",
                "output", "parallel_tool_calls", "previous_response_id", "reasoning",
                "store", "temperature", "text", "tool_choice", "tools", "top_p",
                "truncation", "usage", "user", "metadata", "completed_at"):
        assert key in d, key
    assert d["object"] == "response" and d["store"] is False
    assert d["previous_response_id"] is None and d["error"] is None
    assert d["text"] == {"format": {"type": "text"}}
    assert d["output"][0]["type"] == "message"
    assert d["output"][0]["content"][0] == {"type": "output_text", "text": "答案",
                                            "annotations": []}


def test_response_usage_official_semantics():
    """⑥ input 含缓存命中；命中单列 cached；total 取 max（少算会让客户端自动压缩永不触发）。"""
    d = translate_chat_result(_chat_result(usage={
        "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 12,
        "prompt_tokens_details": {"cached_tokens": 8},
        "completion_tokens_details": {"reasoning_tokens": 2}}),
        "resp_1", "gw", ReqMeta(), {})
    assert d["usage"] == {"input_tokens": 10,
                          "input_tokens_details": {"cached_tokens": 8},
                          "output_tokens": 5,
                          "output_tokens_details": {"reasoning_tokens": 2},
                          "total_tokens": 15}


def test_response_missing_usage_is_null_not_zero():
    d = translate_chat_result(_chat_result(usage=None), "resp_1", "gw", ReqMeta(), {})
    assert d["usage"] is None


def test_response_length_finish_is_incomplete():
    d = translate_chat_result(_chat_result(choices=[{
        "index": 0, "message": {"role": "assistant", "content": "截断"},
        "finish_reason": "length"}]), "resp_1", "gw", ReqMeta(), {})
    assert d["status"] == "incomplete"
    assert d["incomplete_details"] == {"reason": "max_output_tokens"}
    assert "completed_at" not in d


def test_response_tool_call_restores_namespace_amid_reasoning():
    d = translate_chat_result(_chat_result(choices=[{
        "index": 0, "finish_reason": "tool_calls",
        "message": {"role": "assistant", "content": None, "reasoning_content": "想",
                    "tool_calls": [{"id": "call_9", "type": "function",
                                    "function": {"name": "ns__read", "arguments": "{}"}}]}}]),
        "resp_1", "gw", ReqMeta(), {"ns__read": ("ns", "read")})
    assert [i["type"] for i in d["output"]] == ["reasoning", "function_call"]
    fc = d["output"][1]
    assert fc["name"] == "read" and fc["namespace"] == "ns" and fc["call_id"] == "call_9"
    assert "ns__read" not in json.dumps(d, ensure_ascii=False)  # 扁平名绝不漏给客户端


def test_response_empty_output_gets_empty_message():
    d = translate_chat_result(_chat_result(choices=[{
        "index": 0, "message": {"role": "assistant", "content": ""},
        "finish_reason": "stop"}]), "resp_1", "gw", ReqMeta(), {})
    assert len(d["output"]) == 1 and d["output"][0]["content"][0]["text"] == ""


# ---------- 流式编码 ----------

def _events(frames: list[str]) -> list[tuple[str, dict]]:
    out = []
    for frame in frames:
        lines = frame.split("\n")
        out.append((lines[0][len("event: "):], json.loads(lines[1][len("data: "):])))
    return out


def _absorb_all(enc: ResponsesStreamEncoder, chunks: list[dict]) -> list[str]:
    frames: list[str] = []
    for c in chunks:
        frames += enc.absorb(c)
    return frames


def test_stream_full_lifecycle_and_sequence():
    """⑤ 生命周期齐、序号连续、无 [DONE]。"""
    enc = ResponsesStreamEncoder("resp_t", "gw", ReqMeta(), {})
    frames = _absorb_all(enc, [
        {"choices": [{"index": 0, "delta": {"role": "assistant"}}]},
        {"choices": [{"index": 0, "delta": {"reasoning_content": "想"}}]},
        {"choices": [{"index": 0, "delta": {"content": "你"}}]},
        {"choices": [{"index": 0, "delta": {"content": "好"}, "finish_reason": "stop"}]},
        {"usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}},
    ])
    frames += enc.finish()
    evs = _events(frames)
    names = [n for n, _ in evs]
    assert names[0] == "response.created" and names[1] == "response.in_progress"
    assert names[-1] == "response.completed"
    assert [d["sequence_number"] for _, d in evs] == list(range(len(evs)))
    assert "response.output_item.done" in names
    assert "response.output_text.done" in names
    assert not any("[DONE]" in f for f in frames)
    completed = evs[-1][1]["response"]
    assert [i["type"] for i in completed["output"]] == ["reasoning", "message"]
    assert completed["output"][1]["content"][0]["text"] == "你好"
    assert completed["usage"]["input_tokens"] == 3


def test_stream_delta_item_ids_are_stable():
    """⑤ 同一项的每个 delta 共用一个 item_id（逐帧随机 = 客户端对不上账）。"""
    enc = ResponsesStreamEncoder("resp_t", "gw", ReqMeta(), {})
    frames = _absorb_all(enc, [
        {"choices": [{"index": 0, "delta": {"content": "a"}}]},
        {"choices": [{"index": 0, "delta": {"content": "b"}}]},
        {"choices": [{"index": 0, "delta": {"reasoning_content": "x"}}]},
        {"choices": [{"index": 0, "delta": {"reasoning_content": "y"}}]},
    ])
    evs = _events(frames)
    assert len({d["item_id"] for n, d in evs if n == "response.output_text.delta"}) == 1
    assert len({d["item_id"] for n, d in evs
                if n == "response.reasoning_summary_text.delta"}) == 1
    added = [d for n, d in evs if n == "response.output_item.added"]
    assert len({i["item"]["id"] for i in added}) == 2


def test_stream_tool_call_events_and_namespace_restore():
    enc = ResponsesStreamEncoder("resp_t", "gw", ReqMeta(),
                                  {"ns__read": ("ns", "read")})
    frames = _absorb_all(enc, [
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "id": "call_a", "type": "function",
             "function": {"name": "ns__read", "arguments": "{\"p\""}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": ":1}"}}]},
            "finish_reason": "tool_calls"}]},
    ])
    frames += enc.finish()
    evs = _events(frames)
    names = [n for n, _ in evs]
    assert names.count("response.function_call_arguments.delta") == 2
    done = [d for n, d in evs if n == "response.function_call_arguments.done"][0]
    assert done["name"] == "read" and done["namespace"] == "ns"
    assert done["arguments"] == '{"p":1}'
    item = [d for n, d in evs if n == "response.output_item.done"][0]["item"]
    assert item["call_id"] == "call_a" and item["name"] == "read"
    assert "response.completed" == names[-1]


def test_stream_failure_closes_items_before_failed_terminal():
    enc = ResponsesStreamEncoder("resp_f", "gw", ReqMeta(), {})
    frames = _absorb_all(enc, [{"choices": [{"index": 0, "delta": {"content": "部分"}}]}])
    frames += enc.finish(failed=True, error={"code": "server_error", "message": "炸了"})
    evs = _events(frames)
    names = [n for n, _ in evs]
    assert names[-1] == "response.failed"
    assert names.index("response.output_item.done") < names.index("response.failed")
    failed = evs[-1][1]["response"]
    assert failed["status"] == "failed"
    assert failed["error"] == {"code": "server_error", "message": "炸了"}
    assert failed["output"][0]["content"][0]["text"] == "部分"  # 部分产出仍如实回传


def test_stream_length_maps_to_incomplete():
    enc = ResponsesStreamEncoder("resp_i", "gw", ReqMeta(), {})
    frames = _absorb_all(enc, [{"choices": [{"index": 0, "delta": {"content": "截"},
                                             "finish_reason": "length"}]}])
    frames += enc.finish()
    assert _events(frames)[-1][0] == "response.incomplete"


def test_stream_zero_content_still_emits_created_and_terminal():
    """无内容帧（只有 usage）：created/in_progress + completed，事件序列仍然完整。"""
    enc = ResponsesStreamEncoder("resp_z", "gw", ReqMeta(), {})
    frames = _absorb_all(enc, [{"usage": {"prompt_tokens": 1, "completion_tokens": 0}}])
    frames += enc.finish()
    names = [n for n, _ in _events(frames)]
    assert names == ["response.created", "response.in_progress", "response.completed"]
