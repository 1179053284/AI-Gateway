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
    vendor: str = ""  # 厂商归属（「资源池设置」页按此分组卡片；空 = 自定义/未归类）
    context_window: int | None = None  # 最大上下文 tokens
    max_output: int | None = None  # 最大输出 tokens
    image_input: bool = False  # 图片输入（识别/理解）
    video_input: bool = False  # 视频输入
    audio_input: bool = False  # 音频输入
    reasoning: bool = False  # 支持深度推理
    effort_levels: list[str] = field(default_factory=list)  # 深度推理档位（官方枚举）
    params_default: dict = field(default_factory=dict)  # 官方默认参数（作网关初始值，Q24）

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
    # —— 跨协议族预置（Anthropic 原生 model id 别名，供 Claude Code 直连解析；属性未取证）——
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
                ))
        if entries:
            return EnumPool(entries)
    return EnumPool(list(BUILTIN_ENTRIES))


def resolve_request_model(
    requested: str,
    system_models: list,  # list[SystemModel]
    enum_pool: EnumPool,
) -> tuple[object | None, list[tuple[str, float]]]:
    """请求模型解析（tech §4.2）：系统模型精确 → 枚举池别名 → 规范化。

    返回 (SystemModel | None, 候选列表)。命中系统模型（含经由别名/规范化映射后
    名字与系统模型一致）返回该模型；否则返回 None + 候选（404 提示用）。
    """
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
