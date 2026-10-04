"""Qoder **入站 body → 加密端点请求形态**这一段的判据（`upstream/qoder/ask.py`）。

为什么单独一支文件（R3 的 8 条零红变异里有 5 条落在这里）：
「逐键等价」那条网把我方 `build_infer_payload` 的产物与参考实现比，但喂给参考侧的
`history`/`tools` 正是**我方派生出来的同一份** ⇒ `history_of` / `tools_of` / `content_parts`
派生错成什么样都不会红（结构性空判据）。这些形态又全是**别人踩过的真坑**
（DSH 台账里逐条带"用户报障"字样），所以按形状逐条钉死在这里。

对照的源码位置（只读参考 `/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts`）：
`qoder-adapter.ts:276-309`（`qoderContentParts`）、`:332-364`（`buildQoderHistory`）、
`:211-223`（`buildQoderTools`）、`:234-246`（`qoderContentText`）。
"""

from __future__ import annotations

from model_gateway.upstream.qoder import ask


def _msg(role, content, **over):
    return {"role": role, "content": content, **over}


# ------------------------------------------------------------------ 系统提示 ——

def test_system_stays_in_history_when_it_arrives_as_a_message():
    """OpenAI 客户端把系统提示放在 `messages[]` ⇒ **留在历史里**，不搬顶层。

    🔴 这是一条**推翻同日早前一次改动**的判据（详见 `ask.system_prompt_of` 的头注）：
    参考实现 `qoder-adapter.ts:672-674` 的 `systemText` 只取 `options.system`，
    而 `buildQoderHistory` 不过滤 `role=="system"`。现网没有一次加密端点 200 能裁定
    "住顶层才生效"，所以按有真实流量的参考实现来。
    """
    payload = ask.build_infer_payload({"messages": [_msg("system", "你是助手"),
                                                    _msg("user", "你好")]}, "qfmodel")
    assert payload["system"] == []
    assert [m["role"] for m in payload["messages"]] == ["system", "user"]


def test_top_level_system_field_goes_to_the_system_array():
    payload = ask.build_infer_payload({"system": "  只做翻译  ",
                                       "messages": [_msg("user", "hi")]}, "qfmodel")
    assert payload["system"] == [{"type": "text", "text": "只做翻译"}]
    assert [m["role"] for m in payload["messages"]] == ["user"]


# -------------------------------------------------------------------- 图片 ——

def test_multimodal_content_stays_an_array_and_keeps_the_image():
    """🔴 图片的正确通道是 `messages[].content` 的多模态数组，**不是** `imageUrls`。

    官方 `Hyc()` 把 `chat_context.imageUrls` **恒置 null**；早期实现把 content 压成
    纯文本，导致图片在下游全部消失（DSH 侧记为真实缺陷、用户报障）。
    """
    parts = [{"type": "text", "text": "看看这张"},
             {"type": "image_url", "image_url": {"url": "https://cdn/x.png", "detail": "high"}}]
    payload = ask.build_infer_payload({"messages": [_msg("user", parts)]}, "qfmodel")
    sent = payload["messages"][0]["content"]
    assert isinstance(sent, list) and sent[1]["image_url"]["url"] == "https://cdn/x.png"
    assert sent[1]["image_url"]["detail"] == "high"
    assert payload["chat_context"]["imageUrls"] is None
    # 提问文本也要从数组里取出来（否则模型收到"一张没有配文的图"）
    assert payload["chat_context"]["text"] == "看看这张"


def test_image_only_message_is_not_dropped():
    """只发一张图、不带文字 ⇒ 不能被当成"空消息"丢弃（DSH `:349-355` 同一判空口径）。"""
    parts = [{"type": "image_url", "image_url": {"url": "https://cdn/y.png"}}]
    payload = ask.build_infer_payload({"messages": [_msg("user", parts)]}, "qfmodel")
    assert len(payload["messages"]) == 1
    assert payload["messages"][0]["content"][0]["type"] == "image_url"


def test_blank_text_block_is_dropped_but_image_kept():
    parts = [{"type": "text", "text": ""},
             {"type": "image_url", "image_url": {"url": "https://cdn/z.png"}}]
    payload = ask.build_infer_payload({"messages": [_msg("user", parts)]}, "qfmodel")
    assert [b["type"] for b in payload["messages"][0]["content"]] == ["image_url"]


def test_image_url_without_url_is_ignored():
    """畸形图片块不能把整条消息带崩（缺 url ⇒ 这条不算图，纯文本消息保持字符串形态）。"""
    parts = [{"type": "image_url", "image_url": {"url": ""}}, {"type": "text", "text": "只有字"}]
    payload = ask.build_infer_payload({"messages": [_msg("user", parts)]}, "qfmodel")
    assert payload["messages"][0]["content"] == "只有字"


# ------------------------------------------------------------------ 工具链 ——

def test_assistant_tool_calls_and_tool_result_id_survive():
    """🔴 丢了 assistant 的 `tool_calls` 或 tool 的 `tool_call_id`，多步工具调用**彻底坏掉**
    （模型看不到自己调用过什么，只能反复重调或编造结果）。"""
    calls = [{"id": "c1", "type": "function",
              "function": {"name": "get_time", "arguments": "{}"}}]
    messages = [_msg("user", "几点"),
                {**_msg("assistant", None), "tool_calls": calls},
                _msg("tool", "09:00", tool_call_id="c1"),
                _msg("user", "谢谢")]
    history = ask.history_of(messages)
    assert [m["role"] for m in history] == ["user", "assistant", "tool", "user"]
    assert history[1]["tool_calls"] == calls
    assert history[2]["tool_call_id"] == "c1"
    assert history[1]["content"] == ""          # content 为 null 的 assistant 不丢（有 tool_calls）


def test_empty_assistant_is_not_sent():
    """三者皆空（无 content / 无 tool_calls / 无 tool_call_id）的 assistant 没有承载意义。"""
    assert ask.history_of([_msg("assistant", "")]) == []


def test_tools_keep_parameters_and_omit_blank_description():
    tools = [{"type": "function", "function": {
        "name": "get_time", "description": "", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "no_params"}}]
    out = ask.tools_of(tools)
    assert out[0] == {"type": "function",
                      "function": {"name": "get_time", "parameters": {"type": "object"}}}
    assert out[1] == {"type": "function", "function": {"name": "no_params"}}
    # 🔴 `parameters` 是模型**唯一**能学到函数 schema 的通道，丢了就只能用正文 XML 臆造调用


def test_tools_default_is_an_empty_array_and_key_always_present():
    payload = ask.build_infer_payload({"messages": [_msg("user", "hi")]}, "qfmodel")
    assert payload["tools"] == []


def test_unnamed_or_malformed_tools_are_skipped_not_half_sent():
    assert ask.tools_of([{"function": {"name": ""}}, "x", {"type": "function"}]) == []


# ------------------------------------------------------------- 参数与常量位 ——

def test_effort_none_turns_thinking_off_and_keeps_the_tier():
    payload = ask.build_infer_payload({"messages": [_msg("user", "hi")],
                                       "reasoning_effort": "none"}, "qfmodel",
                                      is_reasoning=True)
    assert payload["parameters"]["reasoning_effort"] == "none"
    assert payload["parameters"]["enable_thinking"] is False


def test_effort_absent_writes_neither_key():
    payload = ask.build_infer_payload({"messages": [_msg("user", "hi")]}, "qfmodel")
    assert "reasoning_effort" not in payload["parameters"]
    assert "enable_thinking" not in payload["parameters"]


def test_business_is_always_present_and_is_the_agent_pool():
    """`business` 缺失时 `qfmodel` 恒被路由到故障节点（实测结论，`qoder-adapter.ts:726-736`）。"""
    payload = ask.build_infer_payload({"messages": [_msg("user", "hi")]}, "qfmodel")
    assert payload["business"] == {"type": "agent"}


def test_directory_key_lands_in_both_places_the_endpoint_reads():
    payload = ask.build_infer_payload({"messages": [_msg("user", "hi")]}, "dmodel")
    assert payload["model_config"]["key"] == "dmodel"
    assert payload["chat_context"]["extra"]["modelConfig"]["key"] == "dmodel"


def test_ids_are_stable_when_injected_and_session_is_not():
    a = ask.build_infer_payload({"messages": [_msg("user", "hi")]}, "qfmodel", request_id="R-1")
    b = ask.build_infer_payload({"messages": [_msg("user", "hi")]}, "qfmodel", request_id="R-1")
    assert a["request_id"] == a["request_set_id"] == a["chat_record_id"] == "R-1"
    assert a["session_id"] != b["session_id"], "session_id 恒随机（与 DSH 一致）"


def test_last_user_text_takes_the_latest_user_turn_not_the_first():
    body = {"messages": [_msg("user", "第一问"), _msg("assistant", "答"), _msg("user", "第二问")]}
    assert ask.last_user_text(body) == "第二问"
