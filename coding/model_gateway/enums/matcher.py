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


# 参数档案（`EnumEntry.param_fields`）的合法元数据 —— 加载期硬校验，写错就别想启动。
PARAM_KINDS: frozenset[str] = frozenset(
    {"number", "integer", "boolean", "string", "string_list", "enum"})
#: 🔴 四档各是一种处置，不许折叠成两档：
#: `supported` 可设且生效 / `deprecated` 官方已标废弃（能发但随时会失效）/
#: `ignored` 官方明说设了被忽略（设了等于没设）/ `rejected` 官方明说传非默认值报错。
PARAM_AVAILABILITY: frozenset[str] = frozenset(
    {"supported", "deprecated", "ignored", "rejected"})
#: 参与 `params_default` 派生的档位（后三档即便官方给了缺省值也**不注入**：
#: 注入了也只是一个不被承认的形状，Q35 红线里"把门调绿"的那一类）。
PARAM_INJECTABLE: frozenset[str] = frozenset({"supported"})
#: 写面"只标不拦"的措辞（界面上是这一行的依据列，也是 PUT 回执里的 warning 文案）。
PARAM_ADVICE_LABEL: dict[str, str] = {
    "deprecated": "已标注废弃（Deprecated）",
    "ignored": "明确会忽略该参数（设了不生效）",
    "rejected": "对非默认值返回报错",
}


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
    vendor: str = ""  # 厂商（= 模型生产公司）归属；「网关模型管理」左栏按此分组。🔴 与 `Resource.vendor` **同名不同义**：那个字段承载**供应商名称**（接入方），这个字段承载**厂商**（生产公司）——判身份看它在哪一层。空 = 自定义/未归类
    context_window: int | None = None  # 最大上下文 tokens
    max_output: int | None = None  # 最大输出 tokens
    image_input: bool = False  # 图片输入（识别/理解）
    video_input: bool = False  # 视频输入
    audio_input: bool = False  # 音频输入
    reasoning: bool = False  # 支持深度推理
    effort_levels: list[str] = field(default_factory=list)  # 深度推理档位（官方枚举）
    params_default: dict = field(default_factory=dict)  # 官方默认参数（作网关初始值，Q24）
    #: 官方**参数档案**（2026-10-04 新增，L-B 目录层）：`参数名 → 事实 dict`。
    #: 🔴 为什么要有这一格：原先目录只有一格 `params_default`，它把两件事压成一件事——
    #:   「这个模型官方暴露哪些参数」与「这些参数官方缺省是多少」。于是"官方有这个参数、
    #:   只是没公布缺省 / 设了会被忽略 / 传非默认直接报错"这类事实**在界面上等于不存在**
    #:   （实盘 36 条里 22 条 `params_default` 为空 ⇒ 参数卡整张没有行）。
    #: 一个键的合法形状（`kind` / `availability` 必填，其余按 kind 取用）：
    #:   `kind`: number | integer | boolean | string | string_list | enum
    #:   `availability`: supported | deprecated | ignored | rejected   # 🔴 四档语义不同，不许折叠
    #:   `min` / `max`：number|integer 的官方取值范围；`values`：enum 的官方枚举
    #:   `default`：官方公布的缺省值，**没有就整个键别写 default**（`None` 不参与派生，也不显示成 0）
    #:   `inject`：缺省 True = 该缺省值进 `params_default`（作网关初始注入值，Q24-⑥②）；
    #:             `false` = 官方缺省**已知但网关这一项不写**（交给供应商通道），界面依据列会说明
    #:             这个区别 —— 2026-10-04 回填档案那一轮用它守住"补事实不改出站形状"这条边界
    #:   `note` / `source`：官方原话 + 取证 URL/日期（界面上是这一行的"依据"列）
    #: `params_default` 由本字段**派生**（只取 `availability=supported` 且有 `default` 的键）——
    #: 两者并存且不一致 ⇒ 加载期直接报错（两套真相是 Q33 一直在拆的形状）。
    param_fields: dict = field(default_factory=dict)
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
        self._sync_params_default()

    def _sync_params_default(self) -> None:
        """校验 `param_fields` 并把 `params_default` 改成**派生值**（2026-10-04 裁定 D2）。

        三条纪律：
        1. 档案写错（kind 不在册 / 缺省值与 kind 不匹配 / enum 没有 values）⇒ **加载期报错**，
           不许带着坏档案启动 —— 这份数据是界面"依据"列与写面警告的唯一上游；
        2. 有档案 ⇒ `params_default` 只取「`availability` 属可注入档 **且** 官方公布了缺省值」的键；
           构造方另外塞了一份不一致的 `params_default` ⇒ 直接拒（两套真相）；
        3. 没档案（未取证 / 用户 YAML 老条目）⇒ `params_default` 按给的值原样保留（零行为变化），
           界面据此显示"未取证"，不编造。
        """
        for key, spec in self.param_fields.items():
            where = f"目录条目 {self.name!r} 的参数档案 {key!r}"
            if not isinstance(spec, dict):
                raise ValueError(f"{where} 须为 dict（kind/availability/…），得到 {spec!r}")
            kind = spec.get("kind")
            if kind not in PARAM_KINDS:
                raise ValueError(f"{where} 的 kind={kind!r} 不在册（{sorted(PARAM_KINDS)}）")
            avail = spec.get("availability")
            if avail not in PARAM_AVAILABILITY:
                raise ValueError(
                    f"{where} 的 availability={avail!r} 不在册（{sorted(PARAM_AVAILABILITY)}）")
            inject = spec.get("inject", True)
            if not isinstance(inject, bool):
                raise ValueError(f"{where} 的 inject={inject!r} 须为布尔")
            if inject is False and (avail != "supported" or spec.get("default") is None):
                # `inject: false` 是一条**产品决定**（官方缺省已知，但网关刻意不写这一项、
                # 交给供应商通道），不是"顺手关掉"的开关：只有 supported + 有缺省值才谈得上它。
                raise ValueError(
                    f"{where} 的 inject=False 只在「官方公布了缺省值且该键可设」时成立"
                    f"（当前 availability={avail!r} default={spec.get('default')!r}）")
            if kind == "enum" and not spec.get("values"):
                raise ValueError(f"{where} 是 enum 但没有 values（有档可列才是事实，否则别写）")
            default = spec.get("default")
            dsrc = spec.get("default_source", "official")
            if dsrc not in ("official", "recommended"):
                raise ValueError(f"{where} 的 default_source={dsrc!r} 不在册"
                                 "（official = 官方公布的缺省值；recommended = 官方只给推荐值）")
            if default is not None:
                if kind in ("number", "integer") and (
                        isinstance(default, bool) or not isinstance(default, (int, float))):
                    raise ValueError(f"{where} 的 default={default!r} 与 kind={kind} 不匹配")
                if kind == "integer" and isinstance(default, float) and not default.is_integer():
                    raise ValueError(f"{where} 的 default={default!r} 不是整数")
                if kind == "boolean" and not isinstance(default, bool):
                    raise ValueError(f"{where} 的 default={default!r} 不是布尔")
                if kind == "string" and not isinstance(default, str):
                    raise ValueError(f"{where} 的 default={default!r} 不是字符串")
                if kind == "string_list" and not (
                        isinstance(default, str)
                        or (isinstance(default, list)
                            and all(isinstance(x, str) for x in default))):
                    raise ValueError(f"{where} 的 default={default!r} 须为字符串或字符串数组")
                if kind == "enum" and default not in spec.get("values", []):
                    raise ValueError(f"{where} 的 default={default!r} 不在官方 values 里")
        if not self.param_fields:
            return
        derived = {k: s["default"] for k, s in self.param_fields.items()
                   if s.get("availability") in PARAM_INJECTABLE
                   and s.get("default") is not None
                   and s.get("inject", True) is not False}
        if self.params_default and self.params_default != derived:
            raise ValueError(
                f"目录条目 {self.name!r} 的 params_default={self.params_default!r} 与由 "
                f"param_fields 派生的 {derived!r} 不一致（两个来源一套真相：请删掉前者）")
        self.params_default = derived

    def apply_param_fields(self, fields: dict) -> "EnumEntry":
        """装配后回填档案（内置目录用：条目本身保持可读，档案集中一处按厂商成组）。

        回填立刻重走一遍 `_sync_params_default()` —— 写坏的形状（含"派生值与已注入值不一致"）
        仍在**导入期**抛错，不因为绕开构造函数就放过。
        """
        self.param_fields = dict(fields)
        self._sync_params_default()
        return self

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
            "param_fields": self.param_fields,
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
#   采样参数 temperature/top_p/top_k 官方标 Deprecated；**逐模型缺省值只有 temperature 公布 =1.0**
#   （2026-10-04 档案轮回填；旧注「未公布」经 r1-A + r2-1 复核推翻）。"能不能设"按代次分两种：
#   Opus 4.6 之后只收 1.0、其余值 400；Haiku 4.5 三款都接受（但 temperature 与 top_p 不可同设）。
#   ⇒ 档案照记、`params_default` 仍留空（本轮不改任何一条出站形状；见下方 `_anthropic()`）。
# - OpenAI（2026-10-01 补入现行 Top5）：developers.openai.com——/api/docs/models 与各模型页
#   （gpt-6-astra / gpt-6.1-sol / gpt-6-luna / gpt-6-sol / gpt-5.6-sol：1.05M 上下文、128K 输出、
#   图片输入；reasoning.effort 官方枚举含 none；gpt-5.6 为 gpt-5.6-sol 别名）。
#   模型页与 Chat Completions 参考均未公布采样缺省值 → params_default 留空。
# - 腾讯混元（2026-10-04 补入主力 3 条）：cloud.tencent.com/document/product/1823——130051 模型列表
#   （ID/展示名/上下文/最大输入/最大输出/能力列）、131208 深度思考（thinking 与 reasoning_effort
#   枚举、默认 high、携 tools 时 low→high）、136956 图片理解（示例只有 hy-vision-2.0-instruct）、
#   132252 使用指南（逐字「混元语言模型不支持图片、视频等多模态输入」）；采样只有**平台级**默认表
#   （r1-D 取证 + r2-2 独立复核，推翻旧注「零表述」）⇒ 模型级无据 ⇒ params_default 不注入，
#   档案按 `inject:false` 把"官方给了平台级 1.0、我们为什么不写"这件事说明白。
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
    # 采样缺省：官方 135872 确有「默认值」列（temperature 1.0 / top_p 1.0 / 双惩罚 0 / n=1），但那是
    #   **平台级**表、同页三处写「以对应模型的能力为准」⇒ 模型级仍无表述 ⇒ 档案照记 `inject:false`、
    #   `params_default` 留空（拿平台级数字钉住每一条请求 = 把证据说重一档）。
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
    # 🔴 2026-10-04 数据更正：原注「top_p 0.90 取新版 OpenAPI 口径」读的是 description 正文，
    #   三份端点 schema 的 `top_p.default` 都是 **0.95**（r1-D 与 r2-2 独立同判、零推翻）⇒
    #   本条不再手填 `params_default`，改由下方档案派生（= 1.0 / 0.95）。
    #   ⚠️ 改的是"新建模型时带什么初始值"；`data/config.yaml` 里已落盘的 0.9 一字不动，
    #   要跟着官方请在参数卡改值或点「恢复官方配置」。
    # highspeed 官网**无独立营销名** ⇒ display 逐字用文档 ID，不得自创 "MiniMax M2.7 Highspeed"。
    EnumEntry("MiniMax-M2.7", "MiniMax M2.7", group="编程", vendor="MiniMax",
              context_window=204800, max_output=204800, reasoning=True),
    EnumEntry("MiniMax-M2.7-highspeed", "MiniMax-M2.7-highspeed", group="编程", vendor="MiniMax",
              context_window=204800, max_output=204800, reasoning=True),
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


# ==================== 内置目录的官方参数档案（2026-10-04 取证轮回填） ====================
# 数据依据 = r1 取证五路 + r2 独立复核两路 + 主 agent 自己按同一份官方导出复核
# （`docs/changes/reviews/20261004-param-fields/`，逐格带 URL 与原话；`docs/` 不入库，只落盘）。
# 三条落库纪律：
#  1. 🔴 **本轮不改出站形状**：官方缺省今天已注入的键 = `supported + inject:true`（派生值必须
#     等于在册值，否则导入期就报）；官方缺省今天**没**注入的键 = `inject:false` 或直接落在
#     `ignored/rejected` 档 ⇒ 派生仍是空，界面却把"为什么空"说清楚。要把某个官方缺省变成注入，
#     是一次单独裁定。
#  2. 未取证的键**不进档案**（档案只装核到的事实）；用户手动添加它们时界面写「未取证」。
#     OpenAI 五款整族未回填 = 那一路取证代理没跑完（见交付台账「未做」）。
#  3. `default_source="recommended"` = 官方给的是**推荐值**而不是缺省值（商汤那六键就是这种），
#     照旧注入以保持现网行为，但界面不许把它说成"官方缺省"。
def _pf(kind: str, availability: str, *, default=None, minimum=None, maximum=None,
        values=None, note: str = "", source: str = "", inject: bool = True,
        default_source: str = "official") -> dict:
    """造一条参数档案（只留有意义的键，别让十个 `null` 淹没可读性）。"""
    spec: dict = {"kind": kind, "availability": availability}
    if default is not None:
        spec["default"] = default
        if default_source != "official":
            spec["default_source"] = default_source
    if minimum is not None:
        spec["min"] = minimum
    if maximum is not None:
        spec["max"] = maximum
    if values:
        spec["values"] = list(values)
    if inject is False:
        spec["inject"] = False
    if note:
        spec["note"] = note
    if source:
        spec["source"] = source
    return spec


_A_SRC = "platform.claude.com（llms-full 行 765075-765091·165429·165883，2026-10-04）"
_G_SRC = "ai.google.dev /gemini-api/docs/gemini3（行 447）+ /api/generate-content + Vertex 逐模型页（2026-10-04）"
_Z_SRC = "docs.z.ai /guides/overview/concept-param + /api-reference/llm/chat-completion（2026-10-04）"
_K_SRC = "platform.moonshot.cn /docs/api/chat（参数表逐字「传入其他值会报错」，2026-10-04）"
_D_SRC = "api-docs.deepseek.com /api/create-chat-completion + /guides/thinking_mode（2026-10-04）"
_S_SRC = "github.com/OpenSenseNova/SenseNova6.7 API_CN.md §5「推荐采样参数」（2026-10-04）"
_M_SRC = "platform.minimax.cn openapi-chat-openai.json / openapi-chat-anthropic.json（2026-10-04）"
_O_SRC = "developers.openai.com（.md 直发；宽版 + 窄版两份独立取证结论一致，2026-10-04）"
_H_SRC = "cloud.tencent.com/document/product/1823/135872 平台级「默认值」列 + 132252（2026-10-04）"


def _anthropic(new_gen: bool, cap: int) -> dict:
    """Anthropic 五款：官方把 temperature 标 Deprecated，且**按代次**分两种后果。"""
    return {
        "temperature": _pf(
            "number", "rejected" if new_gen else "supported", default=1.0,
            minimum=0.0, maximum=1.0, inject=new_gen,   # 新代次落在 rejected 档（不参与派生）；
            #                                              Haiku 可设但本轮不注入（出站形状不动）
            note=("官方：Claude Opus 4.6 之后的模型不支持设 temperature，只收 1.0（向后兼容），"
                  "其余值 400" if new_gen else
                  "官方：Haiku 4.5 接受 temperature/top_p/top_k；但 temperature 与 top_p "
                  "只能二选一，同设 400"), source=_A_SRC),
        "top_p": _pf("number", "rejected" if new_gen else "supported", minimum=0.0, maximum=1.0,
                     note=("同上四款：非默认值 400（页内未公布该值的具体缺省）" if new_gen
                           else "官方：值 ≥0.99 为向后兼容放行；开思考时只允许 0.95~1"),
                     source=_A_SRC),
        "top_k": _pf("integer", "rejected" if new_gen else "supported", minimum=0,
                     note="官方措辞更硬：新代次「do not accept top_k; any value will be rejected」（Haiku 4.5 在册可设）",
                     source=_A_SRC),
        "max_tokens": _pf("integer", "supported", minimum=1, maximum=cap,
                          note=f"官方：必填，无缺省值；该模型上限 {cap}", source=_A_SRC),
        "stop": _pf("string_list", "supported",
                    note="原生名 stop_sequences；官方未给条数上限", source=_A_SRC),
        "presence_penalty": _pf("number", "ignored",
                                note="原生 Messages API 无此键；OpenAI 兼容层官方标 Ignored（静默丢）",
                                source=_A_SRC),
        "frequency_penalty": _pf("number", "ignored",
                                 note="同上：原生不存在，兼容层 Ignored", source=_A_SRC),
    }


def _gemini3(ignored_sampling: bool, top_k_fixed=None) -> dict:
    """Gemini 3.x 五款：`temperature` 家族级缺省 1.0 有原话，逐模型 topP/topK 只写 varies by model。

    `ignored_sampling=False`（= 3.1 Pro Preview）：官方两站都没说"设了被忽略/会报错"，
    所以采样三键按可设记录、penalty 两键干脆不入档案（未取证 = 界面走「未取证」那一档）。
    """
    avail = "ignored" if ignored_sampling else "supported"
    src_note = ("官方：3.6 Flash 及之后设这些参数被忽略（3.7/3.8 靠该句类级涵盖）"
                if ignored_sampling else "官方该页给 range，未说忽略或报错")
    out = {
        "temperature": _pf("number", avail, default=1.0, minimum=0.0, maximum=2.0,
                           inject=avail != "supported",   # ignored 档本来就不参与派生
                           note="官方：「all Gemini 3 models … at its default value of 1.0」；"
                                "低于 1.0 官方自警会 looping / 劣化。" + src_note,
                           source=_G_SRC),
        "top_p": _pf("number", avail, minimum=0.0, maximum=1.0,
                     note="逐模型缺省官方只写 varies by model（见 getModel）；" + src_note,
                     source=_G_SRC),
        "stop": _pf("string_list", "supported", maximum=5,
                    note="stopSequences：两站一致「Maximum 5 items in the list」", source=_G_SRC),
        "seed": _pf("integer", "supported", minimum=0,
                    note="官方：best effort，不保证结果确定性", source=_G_SRC),
        "max_tokens": _pf("integer", "supported", minimum=1, maximum=65536,
                          note="官方：含思考 token；超限即 incomplete 且仍计费", source=_G_SRC),
    }
    if top_k_fixed is None:
        out["top_k"] = _pf("integer", avail, minimum=0, note=src_note, source=_G_SRC)
        out["presence_penalty"] = _pf("number", "rejected", minimum=-2.0, maximum=2.0,
                                      note="官方：3.6 Flash 及之后传 penalty 会报错；范围两端 "
                                           "「up to but not including 2.0」与「[-2.0,2.0]」两说",
                                      source=_G_SRC)
        out["frequency_penalty"] = _pf("number", "rejected", minimum=-2.0, maximum=2.0,
                                       note="同上", source=_G_SRC)
    else:
        out["top_k"] = _pf("integer", "supported", default=top_k_fixed, minimum=0, inject=False,
                           note=f"官方该页写「{top_k_fixed} (fixed)」；是否可调无原话（fixed≠说了后果）",
                           source=_G_SRC)
    return out


def _glm() -> dict:
    return {
        "temperature": _pf("number", "supported", default=1.0, minimum=0.0, maximum=1.0,
                           note="官方分系列默认：GLM-5.3/5.2 = 1.0，范围 0~1（不是 OpenAI 的 0~2）",
                           source=_Z_SRC),
        "top_p": _pf("number", "supported", default=0.95, minimum=0.01, maximum=1.0,
                     note="官方默认 0.95，范围 0.01~1", source=_Z_SRC),
        "do_sample": _pf("boolean", "supported", default=True,
                         note="官方：false 时 temperature/top_p 均失效", source=_Z_SRC),
        "max_tokens": _pf("integer", "supported", default=65536, minimum=1, maximum=131072,
                          note="官方 concept-param 默认表 = 65536，参数上限 131072"
                               "（对外承诺是上限，缺省注入是默认值，两数不同属设计如此）",
                          source=_Z_SRC),
        "stop": _pf("string_list", "supported",
                    note="官方两处矛盾：正文「只支持 1 个」vs schema maxItems 4 ⇒ 条数不写死",
                    source=_Z_SRC),
    }


def _kimi(temp_default: float, extra_note: str) -> dict:
    """Kimi 四款：四个键官方都是**唯一合法值**（「传入其他值会报错，建议不要显式传入」）。

    🔴 记 `supported` 而不是 `rejected`：这里"不能改"的是**值域**（只有那一个值合法），
    而键本身可设 —— 记成 rejected 会把已在注入的四个键从派生里踢掉 = 静默改出站形状。
    """
    fix = _pf("number", "supported", minimum=0.0, maximum=1.0,
              note="官方：固定值，传入其他值会报错", source=_K_SRC)
    return {
        "temperature": {**fix, "default": temp_default,
                        "note": "官方：固定值，传入其他值会报错，建议不要显式传入。" + extra_note},
        "top_p": {**fix, "default": 0.95},
        "presence_penalty": {**fix, "default": 0},
        "frequency_penalty": {**fix, "default": 0},
        "max_tokens": _pf("integer", "supported", minimum=1,
                          note="官方 chat 端已标 deprecated，现役 max_completion_tokens；"
                               "K3 默认 131072 / k2.x 默认 32768（上限未逐款公布）",
                          source=_K_SRC),
        "stop": _pf("string_list", "supported", maximum=5, note="官方：最多 5 条、单条 ≤32B",
                    source=_K_SRC),
    }


def _deepseek() -> dict:
    return {
        "temperature": _pf("number", "supported", default=1.0, minimum=0.0, maximum=2.0,
                           note="官方：范围 0~2、默认 1；thinking 模式下该键无效（不报错、无效果）",
                           source=_D_SRC),
        "top_p": _pf("number", "supported", default=1.0, minimum=0.0, maximum=1.0,
                     note="官方：默认 1；thinking 模式有效域 0.95~1（低于 0.95 按 0.95 处理），"
                          "非思考模式固定 1.0（忽略传值）", source=_D_SRC),
        "max_tokens": _pf("integer", "supported", minimum=1, maximum=393216,
                          note="官方缺省按模式分档：非思考 8K / 思考 64K / effort=max 128K"
                               "⇒ 没有单一缺省值可注入，网关注册值 = 该条映射的规格 max_output",
                          source=_D_SRC),
        "presence_penalty": _pf("number", "ignored", minimum=-2.0, maximum=2.0,
                                note="官方：V4 已废弃，传入不生效", source=_D_SRC),
        "frequency_penalty": _pf("number", "ignored", minimum=-2.0, maximum=2.0,
                                 note="官方：V4 已废弃，传入不生效", source=_D_SRC),
        "stop": _pf("string_list", "supported", maximum=16, note="官方：最多 16 条序列",
                    source=_D_SRC),
    }


def _sensenova() -> dict:
    """商汤 6.8-flash-lite：官方只给「推荐采样参数」，且按模式×任务给**四组不同值**。

    🔴 六键照旧注入（现网行为不变），但 `default_source=recommended` ⇒ 界面写"厂商推荐值"，
    不再把它说成官方缺省；presence 官方四组值 = 1.5/0.0/1.5/2.0，在册这一份取 1.5。
    """
    def rec(v, **over):
        return _pf(over.pop("kind", "number"), "supported", default=v,
                   default_source="recommended", source=_S_SRC, **over)
    return {
        "temperature": rec(1.0, minimum=0.0, note="官方 §5 推荐值（非缺省）"),
        "top_p": rec(0.95, maximum=1.0, note="官方 §5 推荐值（非缺省）"),
        "top_k": rec(20, kind="integer", minimum=0, note="官方 §5 推荐值（非缺省）"),
        "min_p": rec(0.0, minimum=0.0, maximum=1.0, note="官方 §5 推荐值（非缺省）"),
        "presence_penalty": rec(1.5, minimum=-2.0, maximum=2.0,
                                note="官方 §5 按模式×任务给四组：1.5 / 0.0 / 1.5 / 2.0；在册取 1.5"),
        "repetition_penalty": rec(1.0, minimum=0.0, note="官方 §5 推荐值（非缺省）"),
    }


def _minimax() -> dict:
    """MiniMax：三份 OpenAPI 的 `temperature.default`=1、`top_p.default`=0.95（含 M2.7 系）。

    🔴 与在册种子值的差异（本轮按官方改回，见交付台账「数据更正」一条）：
    M2.7 / M2.7-highspeed 原注 0.90 出自 description 文字，三份 schema 的 `default` 都是 0.95。
    改的是**新建模型时的初始值**；`data/config.yaml` 里已落盘的 0.9 不受影响，
    要让它跟着官方，得在参数卡改值或点「恢复官方配置」。
    """
    return {
        "temperature": _pf("number", "supported", default=1.0, minimum=0.0, maximum=2.0,
                           note="三份端点 schema 一致 default=1；Responses 端正文写 (0,1] "
                                "与同字段 minimum:0 自相矛盾 ⇒ 下界未取证",
                           source=_M_SRC),
        "top_p": _pf("number", "supported", default=0.95, minimum=0.0, maximum=1.0,
                     note="官方 schema default 统一 0.95（旧注 0.90 只在 description 文字里，"
                          "无 default 支撑）", source=_M_SRC),
        "max_tokens": _pf("integer", "deprecated", minimum=1, maximum=524288,
                          note="Chat 端官方标弃用；Anthropic 端仍收 max_tokens；"
                               "Responses 端键名 max_output_tokens。M3 上限 524288（推荐 131072）、"
                               "M2.7 系 204800（推荐 65536），思考 token 计入上限",
                          source=_M_SRC),
    }


def _hunyuan() -> dict:
    """腾讯混元：官方只有**平台级**默认值表（同页三处写「以对应模型的能力为准」）。

    ⇒ 全部 `inject:false`：把平台级数字写进派生 = 拿"可能不适用于该模型"的数去钉所有请求；
    但档案要有，界面才说得出"官方给了 1.0，我们为什么不注入"。
    """
    return {
        "temperature": _pf("number", "supported", default=1.0, minimum=0.0, maximum=2.0,
                           inject=False, note="平台级默认表；页首逐字「公共调用指南…以对应模型的能力为准」"
                           "⇒ 没有模型级缺省，本轮不注入", source=_H_SRC),
        "top_p": _pf("number", "supported", default=1.0, minimum=0.0, maximum=1.0, inject=False,
                     note="平台级默认表（0→归一为 null）", source=_H_SRC),
        "presence_penalty": _pf("number", "supported", default=0, minimum=-2.0, maximum=2.0,
                                inject=False, note="平台级默认表", source=_H_SRC),
        "frequency_penalty": _pf("number", "supported", default=0, minimum=-2.0, maximum=2.0,
                                 inject=False, note="平台级默认表", source=_H_SRC),
        "repetition_penalty": _pf("number", "ignored",
                                  note="官方明列：客户端设置会被静默忽略", source=_H_SRC),
        "stop": _pf("string_list", "supported", maximum=4, note="官方：最多 4 条，超出直接拒",
                    source=_H_SRC),
        "seed": _pf("integer", "supported", minimum=0, note="官方：任意整数，未给缺省值",
                    source=_H_SRC),
        "n": _pf("integer", "supported", default=1, minimum=1, inject=False,
                 note="平台级默认表 n=1", source=_H_SRC),
    }


def _openai() -> dict:
    """OpenAI 五款：官方**未公布**任何采样缺省值（r1-B 两份独立取证：宽版全量检索零命中）。

    但两处官方表述必须让界面说得出，否则用户只会看到"空"：
    1. Chat Completions 端 `max_tokens` 逐字判**废弃**，现役键是 `max_completion_tokens`
       （Responses 端又叫 `max_output_tokens`）—— 记 `deprecated` 而不是假装没这个键；
    2. GPT-6 四款官方写着「effort ≠ none 时请移除 temperature/top_p」（5.6 Sol 页零此表述），
       而 6 Astra 传 `none` 直接 400 ⇒ 这些是**后果说明**，不是"官方缺省是多少"。
    """
    rm = "GPT-6 系官方：effort 不为 none 时应移除该参数（5.6 Sol 页无此表述）"
    return {
        "temperature": _pf("number", "supported", minimum=0.0, maximum=2.0,
                           note="官方未公布缺省值；" + rm, source=_O_SRC),
        "top_p": _pf("number", "supported",
                     note="官方未公布缺省值，也未给取值区间；" + rm, source=_O_SRC),
        "max_tokens": _pf("integer", "deprecated", minimum=1, maximum=128000,
                          note="Chat Completions 端官方逐字判废弃 ⇒ 现役 max_completion_tokens；"
                               "Responses 端键名 max_output_tokens。上限 = 模型页 128,000"
                               "（含 reasoning token），无缺省", source=_O_SRC),
        "max_completion_tokens": _pf("integer", "supported", minimum=1, maximum=128000,
                                     note="官方：现役输出上限键（含 reasoning token）；未公布缺省",
                                     source=_O_SRC),
        "stop": _pf("string_list", "supported", note="官方未公布缺省", source=_O_SRC),
        "n": _pf("integer", "supported", minimum=1, note="官方未公布缺省", source=_O_SRC),
        "seed": _pf("integer", "supported", minimum=0,
                    note="官方：Chat Completions 已不保证确定性", source=_O_SRC),
    }


#: 模型 → 官方参数档案。没在列的条目（两条 images、两款 legacy）= 本轮未取证。
PARAM_FIELDS_BY_MODEL: dict[str, dict] = {
    "claude-fable-5-1": _anthropic(True, 128000),
    "claude-opus-5-5": _anthropic(True, 128000),
    "claude-sonnet-5-5": _anthropic(True, 128000),
    "claude-sonnet-5": _anthropic(True, 128000),
    "claude-haiku-4-5": _anthropic(False, 64000),
    "gemini-3.8-flash": _gemini3(True),
    "gemini-3.7-flash": _gemini3(True),
    "gemini-3.6-flash": _gemini3(True),
    "gemini-3.5-flash-lite": _gemini3(True),
    "gemini-3.1-pro-preview": _gemini3(False, top_k_fixed=64),
    "glm-5.2": _glm(), "glm-5.3": _glm(), "glm-5.3-flash": _glm(),
    "kimi-k3": _kimi(1.0, ""),
    "kimi-k2.7-code": _kimi(1.0, ""),
    "kimi-k2.7-code-highspeed": _kimi(1.0, ""),
    # 🔴 k2.6 官方是**双值**：思考 1.0 / 非思考 0.6；在册单值 1.0 + 关思考的组合级后果无原话
    "kimi-k2.6": _kimi(1.0, "另：官方 k2.6 为思考 1.0 / 非思考 0.6 双值"),
    "deepseek-v4-flash": _deepseek(),
    "deepseek-v4-pro": _deepseek(),
    "deepseek-v4-flash-vision-exp": _deepseek(),
    "sensenova-6.8-flash-lite": _sensenova(),
    "MiniMax-M3": _minimax(),
    "MiniMax-M2.7": _minimax(),
    "MiniMax-M2.7-highspeed": _minimax(),
    "gpt-6-astra": _openai(), "gpt-6.1-sol": _openai(), "gpt-6-luna": _openai(),
    "gpt-6-sol": _openai(), "gpt-5.6-sol": _openai(),
    "hy4-preview": _hunyuan(),
    "hy3": _hunyuan(),
    "hy-vision-2.0-instruct": _hunyuan(),
}

for _e in BUILTIN_ENTRIES:                       # 内置目录条目保持"一行一个模型"的可读形状
    _fields = PARAM_FIELDS_BY_MODEL.get(_e.name)
    if _fields:
        _e.apply_param_fields(_fields)           # 回填即重走校验（坏形状/两套真相 → 导入期抛错）


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

    def param_advice(self, entry_name: str, params: dict) -> list[str]:
        """拿「用户为某网关模型设的参数」对一遍该条目的官方档案，返回**只标不拦**的说明句。

        🔴 三条纪律：
        1. **不拒写**：Q24 定论「未知键放行 = 开放可扩展」，且写面一拦就会把
           「上游真回 400 ⇒ 界面红」那条路径变成永远走不到（v2 门 M15 的同一条契约）；
        2. **无档案就不评**：条目不在目录、或该键没在册 ⇒ 返回空（我们没资格说人家的值不对）；
        3. **每句带官方出处**：这些话直接显示给用户，凭"我觉得"没资格说"官方会报错"。
        """
        entry = self.entries.get(entry_name)
        if entry is None or not entry.param_fields:
            return []
        out: list[str] = []
        for key, val in (params or {}).items():
            spec = entry.param_fields.get(key)
            if spec is None:
                continue
            avail = spec.get("availability", "supported")
            if avail in PARAM_ADVICE_LABEL:
                note = str(spec.get("note") or "").strip()
                src = str(spec.get("source") or "").strip()
                out.append(f"{key}={val!r}：厂商官方{PARAM_ADVICE_LABEL[avail]}"
                           + (f"（{note}" + ("，" if note and src else "") + (src or "") + "）"
                              if (note or src) else ""))
                continue
            kind = spec.get("kind")
            if kind in ("number", "integer") and isinstance(val, (int, float)) \
                    and not isinstance(val, bool):
                lo, hi = spec.get("min"), spec.get("max")
                if (lo is not None and val < lo) or (hi is not None and val > hi):
                    out.append(f"{key}={val!r} 超出官方公布范围"
                               f"（{'' if lo is None else lo}~{'' if hi is None else hi}）")
            elif kind == "enum" and spec.get("values") and str(val) not in \
                    [str(v) for v in spec["values"]]:
                out.append(f"{key}={val!r} 不在官方枚举里（{spec['values']}）")
        return out


def load_enum_pool(path: Path | str | None = None) -> EnumPool:
    """加载枚举池（S-3，2026-10-05 架构审计）：**内置目录打底 + 用户文件增量覆写**。

    🔴 旧实现「文件存在 ⇒ 整池替换内置」有两个静默失败：
    ① 代码升级新增的目录项对该安装永久不生效（用户看不见，也不会报错）；
    ② 缺省注入/规格来源读不到条目 = 什么都不注入，界面退化（R1-F-3 实算 36→1）。
    现语义：`model-enums.yaml` 是**覆写/新增层** —— 同名条目按用户值整体覆盖（改显示名、
    别名、参数档案是受支持的自定义）；文件里多出来的条目**追加**进池（自定义模型）；
    删除内置条目不受支持（要下线一条内置模型请在该条目来源侧停用，而不是删目录）。
    空文件/坏形状的回落行为不变（⇒ 纯内置目录）。
    """
    base = {e.name: e for e in BUILTIN_ENTRIES}
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
                    # 用户 YAML 里写的参数档案原样读回（写错的形状在 EnumEntry 校验期就报）
                    param_fields={str(k): dict(v) for k, v in
                                  (item.get("param_fields") or {}).items()},
                    # 不读这行，用户在 YAML 里写的 `tool_call: false` 就会被静默丢掉，
                    # 下发的 `supportsToolCall` 恒为 True（验收 P3-2）
                    tool_call=bool(item.get("tool_call", True)),
                ))
        if entries:
            # 增量覆写：用户值优先，内置目录永不丢失
            for e in entries:
                base[e.name] = e
    return EnumPool(list(base.values()))


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
    """请求模型解析（tech §4.2）：**剥前缀** → 网关模型精确 → 枚举池别名 → 规范化。

    返回 (SystemModel | None, 候选列表)。命中网关模型（含经由别名/规范化映射后
    名字与网关模型一致）返回该模型；否则返回 None + 候选（404 提示用）。
    """
    requested = strip_model_prefix(requested)  # v2.0：入站统一剥前缀（Q25-⑦）
    by_name = {m.name: m for m in system_models}
    if requested in by_name:
        return by_name[requested], []
    canonical, _conf = enum_pool.match(requested)
    if canonical and canonical in by_name:
        return by_name[canonical], []
    # 规范化直接对网关模型名匹配（自定义模型不在枚举池时）
    norm = normalize_name(requested)
    for m in system_models:
        if normalize_name(m.name) == norm:
            return m, []
    return None, enum_pool.candidates(requested)
