"""统一模型名枚举池与自动匹配（tech-design §4.7 / PRD FR-1.4）。

- 匹配三级：精确命中 → 别名（含跨协议族原生 model id）→ 规范化（忽略大小写/日期后缀/分隔符差异）
- 无命中给出候选与置信度（供 404 提示与 M2 手动修正沉淀）
- 枚举池来源：data/model-enums.yaml（用户可扩展）；文件缺失时用内置默认（商汤实测清单）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class EnumEntry:
    name: str
    display: str = ""
    aliases: list[str] = field(default_factory=list)
    group: str = ""
    endpoint: str = "chat"  # chat | images（辅助字段）
    response_format_url_hours: int | None = None  # 图像 URL 有效期（终审确认点 8）
    only_base64_image: bool = False  # 仅支持 base64 图片输入（如 kimi-k3）
    # —— 模型目录属性（Q24，2026-09-05）：厂商归属 + 能力 + 官方默认参数，仅官方文档取证 ——
    vendor: str = ""  # 厂商归属（「网关模型管理」页按此分组卡片；空 = 自定义/未归类）
    context_window: int | None = None  # 最大上下文 tokens
    max_output: int | None = None  # 最大输出 tokens
    image_input: bool = False  # 图片输入（识别/理解）
    video_input: bool = False  # 视频输入
    audio_input: bool = False  # 音频输入
    reasoning: bool = False  # 支持深度推理
    effort_levels: list[str] = field(default_factory=list)  # 深度推理档位（官方枚举）
    params_default: dict = field(default_factory=dict)  # 官方默认参数（作网关初始值，Q24）
    # —— 工具调用能力（v2.0 §12.3）：工具侧 `supportsToolCall !== true` 会**删除请求中的 tools** ——
    # ⚠️ 默认 True 是**有意偏离** tech-design §12.3 字面（该处写 False）：
    #    实测字段缺失与 false 对工具**行为相同**（都会删 tools）→ 默认 False 会让"静默删 tools"
    #    这个 bug 原样保留，而消灭它正是 §12.1 的立项目标。默认 True 后，若某模型确实不支持工具，
    #    失败是**上游可见的 400**（可发现），而非静默降级（不可发现）。
    tool_call: bool = True

    def __post_init__(self) -> None:
        # 🔴 不变量：只有对话端点能声明工具调用。`images` 端点（`/v1/images/generations`）
        #    没有 tools 参数可言，若照默认值把 `supportsToolCall: true` 发下去，
        #    工具会把这个**文生图模型**列进"可用于 Agent 的模型"。
        #    写在 dataclass 而不是调用方：内置目录与用户 YAML 两条入口都经过这里。
        if self.endpoint != "chat":
            self.tool_call = False

    def to_dict(self) -> dict:
        return {
            "name": self.name, "display": self.display, "aliases": self.aliases,
            "group": self.group, "endpoint": self.endpoint,
            "response_format_url_hours": self.response_format_url_hours,
            "only_base64_image": self.only_base64_image,
            "vendor": self.vendor,
            "context_window": self.context_window, "max_output": self.max_output,
            "image_input": self.image_input, "video_input": self.video_input,
            "audio_input": self.audio_input,
            "reasoning": self.reasoning, "effort_levels": self.effort_levels,
            "params_default": self.params_default,
            "tool_call": self.tool_call,
        }


# 内置默认枚举池 = 模型目录（Q24 · 2026-09-05 官网取证）：
# 属性/参数来源（全部官方域）：
# - 商汤：token.sensenova.cn/v1/models 第一方实测（ctx/out/模态/特性）+ 官方 API 文档
#   github.com/OpenSenseNova/SenseNova6.7 API_CN.md §5 推荐采样参数（全组合已实测 200）
# - DeepSeek：api-docs.deepseek.com（/quick_start/pricing、/guides/thinking_mode、
#   /api/create-chat-completion、/news/news260424）。注意：V4 的 frequency_penalty /
#   presence_penalty 已废弃（传入不生效），stop / max_tokens 无固定默认 → 官方默认仅
#   temperature 1 / top_p 1 两项，其余归推理体系（thinking 默认 enabled / effort 默认 high）。
# - 智谱 GLM：docs.z.ai（/guides/llm/glm-5.2|glm-5.3、/guides/vlm/glm-5.3-flash、
#   /guides/overview/concept-param、/api-reference/llm/chat-completion——分系列默认：
#   GLM-5.3/5.2 temperature 1.0、top_p 0.95、do_sample true）
# - Moonshot Kimi：platform.moonshot.cn（/docs/models、/docs/api/models-overview——
#   temperature 固定 1.0、top_p 固定 0.95、双惩罚固定 0、/docs/guide/use-reasoning-effort、
#   /docs/pricing/chat-k3）
# - Anthropic（2026-10-01 补入现行 Top5）：platform.claude.com——models/overview 在售对照表
#   （Fable 5.1 / Opus 5.5 / Sonnet 5.5 / Haiku 4.5 的 API ID、1M·200K 上下文、128K·64K 输出、
#   全系文本+图片输入）、pricing、models/sonnet-5（legacy 在售，补第 5 条）、
#   build-with-claude/effort（档位 low/medium/high/xhigh/max；Haiku 4.5 不支持 effort）、
#   models/haiku-4-5（快照 claude-haiku-4-5-20251001 + 短别名 claude-haiku-4-5）。
#   采样参数 temperature/top_p/top_k 官方已标 Deprecated 且非默认值返回 400 → params_default 留空。
# - OpenAI（2026-10-01 补入现行 Top5）：developers.openai.com——/api/docs/models 与各模型页
#   （gpt-6-astra / gpt-6.1-sol / gpt-6-luna / gpt-6-sol / gpt-5.6-sol：1.05M 上下文、128K 输出、
#   图片输入；reasoning.effort 官方枚举含 none；gpt-5.6 为 gpt-5.6-sol 别名）。
#   模型页与 Chat Completions 参考均未公布采样缺省值 → params_default 留空。
# - 腾讯混元（2026-10-04 补入主力 3 条）：cloud.tencent.com/document/product/1823——130051 模型列表
#   （ID/展示名/上下文/最大输入/最大输出/能力列）、131208 深度思考（thinking 与 reasoning_effort
#   枚举、默认 high、携 tools 时 low→high）、136956 图片理解（示例只有 hy-vision-2.0-instruct）、
#   132252 使用指南（逐字「混元语言模型不支持图片、视频等多模态输入」）；采样缺省官方零表述 → 不注入。
# - MiniMax（2026-10-04 补入主力 3 条）：platform.minimax.cn（模型页/参数表 schema default/发布记录）
#   ——M3 1M 上下文·输出参数上限 524,288（推荐 131,072，思考 token 计入上限）、M2.7 族 204,800；
#   temperature 1.0 全站、top_p 分档 0.95/0.90 为官方 schema `default` 在册值 → 写入 params_default；
#   reasoning_effort 仅 M3.1 生效 ⇒ 其余档位留空；M3.1-Flash-Preview 因「仅 M Plan/MiniMax Code」未入。
# - Google Gemini（2026-10-04 补入主力 5 条）：ai.google.dev（模型索引、/docs/thinking 档位表、
#   /docs/openai 兼容层「Reasoning cannot be turned off for Gemini 2.5 Pro or 3 models」）+
#   Vertex 各模型页（1,048,576 / 65,536、模态、退役计划）；采样数字官方只写「varies by model」
#   且 3.5-lite/3.6/3.7/3.8 设置被忽略 → params_default 留空；`none` 不入档位。
# 官方未给缺省值的键不写入（未核实不注入）；推理开关/档位归推理参数体系，不入 params_default。
BUILTIN_ENTRIES: list[EnumEntry] = [
    # —— 商汤 SenseNova（tokenplan 在售 8 项，见 /v1/models 实测记录）——
    EnumEntry("sensenova-6.8-flash-lite", "SenseNova 6.8 Flash Lite",
              aliases=["sensenova-6.7-flash-lite"], group="通用",
              vendor="商汤 SenseNova", context_window=262144, max_output=65536,
              image_input=True, reasoning=True,
              params_default={"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0,
                              "presence_penalty": 1.5, "repetition_penalty": 1.0}),
    EnumEntry("sensenova-u1-fast", "SenseNova U1 Fast", group="图像生成", endpoint="images",
              response_format_url_hours=1, vendor="商汤 SenseNova",
              context_window=262144, max_output=65536),
    EnumEntry("sensenova-u1.5-lite", "SenseNova U1.5 Lite", group="图像生成", endpoint="images",
              response_format_url_hours=24, vendor="商汤 SenseNova",
              context_window=262144, max_output=65536),
    # —— DeepSeek（2026 在售：V4-Flash-0731 / V4-Pro-0813 / V4-Flash-Vision-Exp）——
    EnumEntry("deepseek-v4-flash", "DeepSeek V4 Flash",
              aliases=["deepseek-v4-flash-0731"], group="编程",
              vendor="DeepSeek", context_window=1048576, max_output=65536,
              reasoning=True, effort_levels=["low", "high", "max"],
              params_default={"temperature": 1.0, "top_p": 1.0}),
    EnumEntry("deepseek-v4-pro", "DeepSeek V4 Pro",
              aliases=["deepseek-v4-pro-0813"], group="编程",
              vendor="DeepSeek", context_window=1048576, max_output=65536,
              reasoning=True, effort_levels=["low", "high", "max"],
              params_default={"temperature": 1.0, "top_p": 1.0}),
    EnumEntry("deepseek-v4-flash-vision-exp", "DeepSeek V4 Flash Vision (Exp)",
              group="编程", vendor="DeepSeek", context_window=1048576, max_output=65536,
              image_input=True, reasoning=True, effort_levels=["low", "high", "max"],
              params_default={"temperature": 1.0, "top_p": 1.0}),
    # —— 智谱 GLM（2026 在售：glm-5.2 / glm-5.3 / glm-5.3-flash）——
    # API 参考分系列默认：GLM-5.3/5.2 temperature 1.0（范围 0~1）/ top_p 0.95 / do_sample true；
    # max_tokens 默认 65536（concept-param 默认表，上限 131072）
    EnumEntry("glm-5.2", "GLM-5.2", group="编程", vendor="智谱 GLM",
              context_window=1048576, max_output=131072,
              reasoning=True, effort_levels=["max", "high", "low"],
              params_default={"temperature": 1.0, "top_p": 0.95, "do_sample": True,
                              "max_tokens": 65536}),
    EnumEntry("glm-5.3", "GLM-5.3", group="编程", vendor="智谱 GLM",
              context_window=1048576, max_output=131072,
              reasoning=True, effort_levels=["max", "high", "low"],
              params_default={"temperature": 1.0, "top_p": 0.95, "do_sample": True,
                              "max_tokens": 65536}),
    EnumEntry("glm-5.3-flash", "GLM-5.3 Flash", group="编程", vendor="智谱 GLM",
              context_window=1048576, max_output=131072,
              image_input=True, video_input=True,
              reasoning=True, effort_levels=["max", "high", "low"],
              params_default={"temperature": 1.0, "top_p": 0.95, "do_sample": True,
                              "max_tokens": 65536}),
    # —— Moonshot Kimi（2026 在售：k3 / k2.7-code(+highspeed) / k2.6；k2.5 与更早已下线）——
    # 参数参考：temperature 固定 1.0 / top_p 固定 0.95 / 双惩罚固定 0（传入其他值报错）
    EnumEntry("kimi-k3", "Kimi K3", group="编程", only_base64_image=True,
              vendor="Moonshot Kimi", context_window=1048576, max_output=65536,
              reasoning=True, effort_levels=["low", "high", "max"],
              params_default={"temperature": 1.0, "top_p": 0.95,
                              "presence_penalty": 0, "frequency_penalty": 0}),
    EnumEntry("kimi-k2.7-code", "Kimi K2.7 Code", group="编程",
              vendor="Moonshot Kimi", context_window=262144, max_output=None,
              reasoning=True,
              params_default={"temperature": 1.0, "top_p": 0.95,
                              "presence_penalty": 0, "frequency_penalty": 0}),
    EnumEntry("kimi-k2.7-code-highspeed", "Kimi K2.7 Code Highspeed", group="编程",
              vendor="Moonshot Kimi", context_window=262144, max_output=None,
              reasoning=True,
              params_default={"temperature": 1.0, "top_p": 0.95,
                              "presence_penalty": 0, "frequency_penalty": 0}),
    EnumEntry("kimi-k2.6", "Kimi K2.6", group="编程",
              vendor="Moonshot Kimi", context_window=262144, max_output=None,
              reasoning=True,
              params_default={"temperature": 1.0, "top_p": 0.95,
                              "presence_penalty": 0, "frequency_penalty": 0}),
    # —— Anthropic（2026-10-01 现行 Top5：Fable 5.1 / Opus 5.5 / Sonnet 5.5 / Sonnet 5 / Haiku 4.5）——
    # 4.6 代起为无日期 ID（即快照本身）；thinking 均可开（前四款 Adaptive，Haiku 为 manual extended），
    # effort 五档 low/medium/high/xhigh/max（Haiku 不支持 effort）；采样参数不注入（官方 Deprecated）。
    EnumEntry("claude-fable-5-1", "Claude Fable 5.1", group="编程", vendor="Anthropic",
              context_window=1000000, max_output=128000, image_input=True,
              reasoning=True, effort_levels=["low", "medium", "high", "xhigh", "max"]),
    EnumEntry("claude-opus-5-5", "Claude Opus 5.5", group="编程", vendor="Anthropic",
              context_window=1000000, max_output=128000, image_input=True,
              reasoning=True, effort_levels=["low", "medium", "high", "xhigh", "max"]),
    EnumEntry("claude-sonnet-5-5", "Claude Sonnet 5.5", group="编程", vendor="Anthropic",
              context_window=1000000, max_output=128000, image_input=True,
              reasoning=True, effort_levels=["low", "medium", "high", "xhigh", "max"]),
    EnumEntry("claude-sonnet-5", "Claude Sonnet 5", group="编程", vendor="Anthropic",
              context_window=1000000, max_output=128000, image_input=True,
              reasoning=True, effort_levels=["low", "medium", "high", "xhigh", "max"]),
    EnumEntry("claude-haiku-4-5", "Claude Haiku 4.5", aliases=["claude-haiku-4-5-20251001"],
              group="通用", vendor="Anthropic", context_window=200000, max_output=64000,
              image_input=True, reasoning=True),
    # —— OpenAI（2026-10-01 现行 Top5：Astra / 6.1 Sol / 6 Luna / 6 Sol / 5.6 Sol）——
    # reasoning.effort 官方枚举按模型收录（Luna/6 Sol/5.6 Sol 官方含 none）；采样参数不注入
    # （模型页与 Chat Completions 参考均未公布缺省值）。
    EnumEntry("gpt-6-astra", "GPT-6 Astra", group="编程", vendor="OpenAI",
              context_window=1050000, max_output=128000, image_input=True,
              reasoning=True, effort_levels=["low", "medium", "high", "xhigh", "max"]),
    EnumEntry("gpt-6.1-sol", "GPT-6.1 Sol", group="编程", vendor="OpenAI",
              context_window=1050000, max_output=128000, image_input=True,
              reasoning=True, effort_levels=["low", "medium", "high", "xhigh", "max"]),
    EnumEntry("gpt-6-luna", "GPT-6 Luna", group="通用", vendor="OpenAI",
              context_window=1050000, max_output=128000, image_input=True,
              reasoning=True, effort_levels=["none", "low", "medium", "high", "xhigh", "max"]),
    EnumEntry("gpt-6-sol", "GPT-6 Sol", group="编程", vendor="OpenAI",
              context_window=1050000, max_output=128000, image_input=True,
              reasoning=True, effort_levels=["none", "low", "medium", "high", "xhigh", "max"]),
    EnumEntry("gpt-5.6-sol", "GPT-5.6 Sol", aliases=["gpt-5.6"], group="编程", vendor="OpenAI",
              context_window=1050000, max_output=128000, image_input=True,
              reasoning=True, effort_levels=["none", "low", "medium", "high", "xhigh", "max"]),
    # —— 腾讯混元（2026-10-04 官网取证：TokenHub 模型列表 130051、深度思考 131208、
    # 图片理解 136956、下线公告；国内 cloud.tencent.com 与国际站 ID 同串）——
    # 官方逐字「本文中的混元语言模型不支持图片、视频等多模态输入」⇒ hy4/hy3 图/视频 = False；
    # 音频官方全篇未提 ⇒ 记 False 只表示"无在册依据支持"，不冒充官方否定。
    # 采样缺省官方零表述（示例里的 temperature 0.9 不是缺省值）⇒ params_default 一律留空。
    # ctx 两页分别写 `1M` 与 `1024k`（官方从未给确切整数）⇒ 取较小读法 10^6：
    #   写小只会保守换号一次，写大是 fail-open 去挨上游 400。
    EnumEntry("hy4-preview", "Hy4 preview", group="编程", vendor="腾讯混元",
              context_window=1000000, max_output=64000,
              reasoning=True, effort_levels=["none", "high"]),
    # effort 无 `low`（官方枚举只有 high / none，默认 high）；`hy3-preview` 2026-08-31 下线、
    # 官方公告逐字「请求自动路由至 Hy3」⇒ 作别名；`hy3-202608` 是 Token Plan 页的快照 ID，非别名。
    # 🔴 官方坑：携 `tools` 时 `low` 被 API **静默升为 high**（不是报错）。
    EnumEntry("hy3", "Hy3", aliases=["hy3-preview"], group="编程", vendor="腾讯混元",
              context_window=256000, max_output=128000,
              reasoning=True, effort_levels=["none", "low", "high"]),
    # 混元族**唯一**在册图输入出口（136956 图片理解示例只有它；hy3/hy4 两串在该页零出现）。
    # 官方多模态理解表**没有能力列** ⇒ `tool_call` 取 EnumEntry 默认 True（依据级别=默认，
    # 不是官方声明）；视频理解另有 `hunyuan-turbos-vision-video-20250728`（未入目录）。
    EnumEntry("hy-vision-2.0-instruct", "HY-Vision-2.0-Instruct", group="通用",
              vendor="腾讯混元", context_window=44000, max_output=16000, image_input=True),
    # —— MiniMax（2026-10-04 官网取证：platform.minimax.cn 模型页/参数表/发布记录，
    # 国内 `api.minimax.cn` 与国际 `api.minimax.io` ID 逐字相同；M 系无日期快照别名）——
    # 🔴 `max_output` = 官方**参数上限**（M3 推荐 131,072 / M2.7 族推荐 65,536），且官方逐字
    #   「思考 token 也计入此上限」；网关按 Q33-④ 把 max_output 当缺省 `max_tokens` 注入
    #   （`core/ir.py::apply_spec_defaults`）⇒ 取上限是"不拦合法请求"的口径，推荐值差异记此备查。
    # `reasoning_effort` 官方仅 M3.1 生效 ⇒ M3/M2.7 的 effort_levels 留空（有档可列就是编数）。
    # `MiniMax-M3.1-Flash-Preview` **未入目录**：官方「暂时仅通过 M Plan 和 MiniMax Code 提供」
    #   + 按量价目表/发布记录三处零命中 ⇒ 普通 Key 不可达；放开按量即补一条（反转触发）。
    EnumEntry("MiniMax-M3", "MiniMax M3", group="编程", vendor="MiniMax",
              context_window=1000000, max_output=524288,
              image_input=True, video_input=True, reasoning=True,
              params_default={"temperature": 1.0, "top_p": 0.95}),
    # ctx 与 max_output 同值（204,800）⇒ 承载校验对本条几乎永不触发（如实注记）；
    # top_p 取新版 OpenAPI 口径 0.90（旧 text-post 页写 0.95，冲突已裁）；
    # highspeed 官网**无独立营销名** ⇒ display 逐字用文档 ID，不得自创 "MiniMax M2.7 Highspeed"。
    EnumEntry("MiniMax-M2.7", "MiniMax M2.7", group="编程", vendor="MiniMax",
              context_window=204800, max_output=204800, reasoning=True,
              params_default={"temperature": 1.0, "top_p": 0.90}),
    EnumEntry("MiniMax-M2.7-highspeed", "MiniMax-M2.7-highspeed", group="编程", vendor="MiniMax",
              context_window=204800, max_output=204800, reasoning=True,
              params_default={"temperature": 1.0, "top_p": 0.90}),
    # —— Google Gemini（2026-10-04 官方域取证：ai.google.dev 模型索引 / thinking / OpenAI 兼容页
    # + Vertex 各模型页；Gemini API 与 Vertex 的 model ID 逐字相同，3.x 系无日期快照）——
    # 五款共同：1,048,576 上下文；65,536 = 官方 "Output token limit"（"含思考"只见于 pricing 的
    #   计费口径「Output price (including thinking tokens)」，不是字段语义）；图/视/音输入全 ✅。
    # 🔴 `none` 一律不进档位：官方「Reasoning cannot be turned off for Gemini 2.5 Pro or 3 models」，
    #   且 ThinkingLevel 枚举只有 UNSPECIFIED/MINIMAL/LOW/MEDIUM/HIGH。
    # params_default 全留空：ai.google.dev 从不公布逐模型数字（写「default varies by model，
    #   见 getModel」），且 3.5-flash-lite/3.6/3.7/3.8 设了 temperature/topP/topK 会被忽略、
    #   penalty 类直接报错 ⇒ 内置目录不得带这些键。
    EnumEntry("gemini-3.8-flash", "Gemini 3.8 Flash", group="通用", vendor="Google Gemini",
              context_window=1048576, max_output=65536,
              image_input=True, video_input=True, audio_input=True,
              reasoning=True, effort_levels=["low", "medium", "high"]),
    # 3.8 / 3.7 传 `minimal` 会**报错**（三处原文，含 Vertex「will return an API validation error」）
    # ⇒ 档位不含 minimal；3.6 的 minimal 只有 thinking 页**单源**在册（模型页与 Vertex 页均不列）。
    EnumEntry("gemini-3.7-flash", "Gemini 3.7 Flash", group="通用", vendor="Google Gemini",
              context_window=1048576, max_output=65536,
              image_input=True, video_input=True, audio_input=True,
              reasoning=True, effort_levels=["low", "medium", "high"]),
    EnumEntry("gemini-3.6-flash", "Gemini 3.6 Flash", group="通用", vendor="Google Gemini",
              context_window=1048576, max_output=65536,
              image_input=True, video_input=True, audio_input=True,
              reasoning=True, effort_levels=["minimal", "low", "medium", "high"]),
    # 官方默认档 = **minimal**，且官方自警：minimal 会让多步 agentic 任务的工具调用提前终止。
    EnumEntry("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", group="通用",
              vendor="Google Gemini", context_window=1048576, max_output=65536,
              image_input=True, video_input=True, audio_input=True,
              reasoning=True, effort_levels=["minimal", "low", "medium", "high"]),
    # display 取官方索引表写法 `Gemini 3.1 Pro`（模型页/pricing 另有两种写法，全表统一取一种）；
    # Preview 未 GA、官方无关停日期；`-customtools` 是**独立端点**（同价）不并入别名。
    EnumEntry("gemini-3.1-pro-preview", "Gemini 3.1 Pro", group="通用", vendor="Google Gemini",
              context_window=1048576, max_output=65536,
              image_input=True, video_input=True, audio_input=True,
              reasoning=True, effort_levels=["low", "medium", "high"]),
    # —— 历史预置（Anthropic 原生 model id 别名，供 Claude Code 旧版直连解析；属性未取证）——
    EnumEntry("claude-sonnet-4", "Claude Sonnet 4",
              aliases=["claude-sonnet-4-20250514"], group="编程", vendor="Anthropic"),
    EnumEntry("claude-opus-4", "Claude Opus 4",
              aliases=["claude-opus-4-20250514"], group="编程", vendor="Anthropic"),
]


_DATE_SUFFIX = re.compile(r"-(\d{4,8})$")  # -0731(MMDD) / -202507 / -20250514 日期后缀


def normalize_name(name: str) -> str:
    """规范化：小写、去日期后缀、统一分隔符（- _ . 空格 → -）、去首尾分隔符。"""
    s = name.strip().lower()
    for ch in " _.":
        s = s.replace(ch, "-")
    s = re.sub(r"-+", "-", s).strip("-")
    s = _DATE_SUFFIX.sub("", s)
    return s


class EnumPool:
    def __init__(self, entries: list[EnumEntry]):
        self.entries = {e.name: e for e in entries}
        self._alias: dict[str, str] = {}
        self._norm: dict[str, str] = {}
        for e in entries:
            self._norm.setdefault(normalize_name(e.name), e.name)
            for a in e.aliases:
                self._alias.setdefault(a, e.name)
                norm_a = normalize_name(a)
                if norm_a != e.name:  # 自引用别名（normalize 后=规范名）无意义，跳过
                    self._alias.setdefault(norm_a, e.name)
                self._norm.setdefault(norm_a, e.name)

    # —— 匹配 ——
    def match(self, name: str) -> tuple[str | None, float]:
        """返回 (规范名, 置信度)。精确=1.0 / 别名=0.9 / 规范化=0.7 / 未命中=(None,0)。"""
        if name in self.entries:
            return name, 1.0
        if name in self._alias:
            return self._alias[name], 0.9
        # 别名（大小写不敏感）
        low = name.lower()
        if low in self._alias:
            return self._alias[low], 0.9
        norm = normalize_name(name)
        if norm in self._norm:
            return self._norm[norm], 0.7
        return None, 0.0

    def candidates(self, name: str, limit: int = 5) -> list[tuple[str, float]]:
        """无命中时的候选建议（按前缀/包含/编辑距离粗排）。"""
        norm = normalize_name(name)
        scored: list[tuple[float, str]] = []
        for cand_norm, canonical in self._norm.items():
            score = 0.0
            if cand_norm == norm:
                score = 1.0
            elif cand_norm.startswith(norm) or norm.startswith(cand_norm):
                score = 0.6
            elif norm in cand_norm or cand_norm in norm:
                score = 0.4
            else:
                # 简易重叠字符比例
                common = len(set(norm) & set(cand_norm))
                score = common / max(len(set(norm) | set(cand_norm)), 1) * 0.3
            if score > 0.15:
                scored.append((score, canonical))
        scored.sort(key=lambda t: (-t[0], t[1]))
        seen: set[str] = set()
        out: list[tuple[str, float]] = []
        for s, c in scored:
            if c not in seen:
                seen.add(c)
                out.append((c, round(s, 2)))
            if len(out) >= limit:
                break
        return out

    def get(self, name: str) -> EnumEntry | None:
        return self.entries.get(name)

    def url_valid_hours(self, vendor_model: str) -> int | None:
        e = self.entries.get(vendor_model)
        return e.response_format_url_hours if e else None

    def needs_base64_image(self, vendor_model: str) -> bool:
        e = self.entries.get(vendor_model)
        return bool(e and e.only_base64_image)


def load_enum_pool(path: Path | str | None = None) -> EnumPool:
    """加载枚举池：data/model-enums.yaml 存在则用之（用户可扩展），否则内置默认。"""
    if path is not None and Path(path).exists():
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        entries = []
        for item in raw.get("entries", []):
            if isinstance(item, dict) and item.get("name"):
                entries.append(EnumEntry(
                    name=item["name"],
                    display=item.get("display", ""),
                    aliases=list(item.get("aliases", [])),
                    group=item.get("group", ""),
                    endpoint=item.get("endpoint", "chat"),
                    response_format_url_hours=item.get("response_format_url_hours"),
                    only_base64_image=bool(item.get("only_base64_image", False)),
                    vendor=item.get("vendor", ""),
                    context_window=item.get("context_window"),
                    max_output=item.get("max_output"),
                    image_input=bool(item.get("image_input", False)),
                    video_input=bool(item.get("video_input", False)),
                    audio_input=bool(item.get("audio_input", False)),
                    reasoning=bool(item.get("reasoning", False)),
                    effort_levels=[str(x) for x in item.get("effort_levels", [])],
                    params_default=dict(item.get("params_default", {})),
                    # 不读这行，用户在 YAML 里写的 `tool_call: false` 就会被静默丢掉，
                    # 下发的 `supportsToolCall` 恒为 True（验收 P3-2）
                    tool_call=bool(item.get("tool_call", True)),
                ))
        if entries:
            return EnumPool(entries)
    return EnumPool(list(BUILTIN_ENTRIES))


# —— 入站前缀剥离（v2.0 §19 M3-1 / PRD Q25-⑦）——
# 工具侧会把自定义模型写成 `custom:` / `custom-local:` 前缀（WorkBuddy CLI 实测：
# `custom-local:` 发请求前被剥、`custom:` 不剥 → 网关收到带前缀名会 404）。
# 网关侧统一剥掉，避免"工具行为差异"变成"模型不存在"。
_MODEL_PREFIXES = ("custom-local:", "custom:")


def strip_model_prefix(requested: str) -> str:
    """剥离入站 model 的前缀（`custom-local:` / `custom:`）。无前缀原样返回。"""
    s = (requested or "").strip()
    for p in _MODEL_PREFIXES:
        if s.startswith(p):
            return s[len(p):].strip()
    return s


def resolve_request_model(
    requested: str,
    system_models: list,  # list[SystemModel]
    enum_pool: EnumPool,
) -> tuple[object | None, list[tuple[str, float]]]:
    """请求模型解析（tech §4.2）：**剥前缀** → 系统模型精确 → 枚举池别名 → 规范化。

    返回 (SystemModel | None, 候选列表)。命中系统模型（含经由别名/规范化映射后
    名字与系统模型一致）返回该模型；否则返回 None + 候选（404 提示用）。
    """
    requested = strip_model_prefix(requested)  # v2.0：入站统一剥前缀（Q25-⑦）
    by_name = {m.name: m for m in system_models}
    if requested in by_name:
        return by_name[requested], []
    canonical, _conf = enum_pool.match(requested)
    if canonical and canonical in by_name:
        return by_name[canonical], []
    # 规范化直接对系统模型名匹配（自定义模型不在枚举池时）
    norm = normalize_name(requested)
    for m in system_models:
        if normalize_name(m.name) == norm:
            return m, []
    return None, enum_pool.candidates(requested)
