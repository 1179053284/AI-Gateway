"""参数归一化与方言表（tech-design v2.0 §13 / PRD Q25-③④⑤）。

三件事：
1. **规范档位序（7 档，开放可扩展）** —— 规范外档位（如 `ultra`）原样透传，不报错。
2. **降级分两层且不得叠加** —— 工具层自己 clamp（就近取、优先向上）；网关层只降不升，
   且**工具已 clamp 时网关不得二次 clamp**。
3. **方言表** —— `data/dialects.json`，由 `mgw probe` 三步探测得出，硬编码作 fallback。

设计要点（§13.1 裁决）：`thinkingLevelMap` 的**键固定为 7 个规范档**；
`ultra` 等规范外档位**不新增键**，只作为 `max` 的映射值，或在入站透传时原样放行。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# —— 规范档位序（7 档，升序）——
# 🔴 开放可扩展：规范外档位（实测 deepseek-v4-pro 含 `ultra`）**原样透传、不报错**，
#    网关不得因档位不在本序内而拒绝（§13.1）。
LEVELS: tuple[str, ...] = ("off", "minimal", "low", "medium", "high", "xhigh", "max")

# 关闭语义的档位（S2 生效验证的可靠锚点：这些值应把 reasoning_tokens 打到 0）
CLOSED_LEVELS: frozenset[str] = frozenset({"off", "none", "disabled"})


def is_closed(level: str | None) -> bool:
    """该档位是否表示"关闭推理"。"""
    return level is not None and level.strip().lower() in CLOSED_LEVELS


def build_level_map(
    supported: list[str] | None,
    overrides: dict[str, str | None] | None = None,
) -> dict[str, str | None]:
    """组装 `caps.thinkingLevelMap` —— **7 键齐全，不支持的档显式写 `null`**（§12.2a）。

    🔴 键缺失（`undefined`）≠ `null`：工具对非高阶档（`minimal`/`medium` 等）会把
    **缺失键判为"支持"** → 发出去 → 上游静默忽略 → 正是要消灭的"静默降级"。
    因此**必须 7 键齐全**，不支持的显式写 `None`（JSON 序列化后为 `null`）。

    `supported` 来自 `EnumEntry.effort_levels`（`list[str]`，官方枚举）；
    `overrides` 来自 `SystemModel.caps_overrides.thinkingLevelMap`（用户手改，最高优先）。
    """
    sup = set(supported or ())
    out: dict[str, str | None] = {lv: (lv if lv in sup else None) for lv in LEVELS}
    if overrides:
        out.update(overrides)
    return out


def degrade_effort(effort: str, supported: list[str] | None) -> str:
    """网关层兜底降级：**只降不升**，就近取值（§13.2）。

    ⚠️ 仅在**工具未 clamp** 时调用 —— 工具已 clamp 时网关**不得二次 clamp**。
    调用方通过 `already_clamped` 参数声明；本函数只负责纯函数式的就近降级。

    - 目标档在支持列表内 → 原样返回（含**规范外档位**：实测 `ultra` 属合法值）
    - 否则 → 在规范序内找**不超过目标**的最近支持档（向下就近）
    - 无更低档可用 → 返回 `None`（调用方决定是否丢弃该参数）
    """
    sup = list(supported or ())
    if not sup:
        return effort
    if effort in sup:
        return effort  # 含规范外档位，原样透传（开放可扩展）

    key = effort.strip().lower()
    # 🔴 关闭档没有"强度"可言 ⇒ 不参与就近升降（向上取最近会把"关推理"的请求升成厂商最高档）。
    #    它在厂商表里该写成哪个词（`none`/`disabled`），由调度层按**那张表自己在册的**关闭词归一。
    if is_closed(effort) and effort not in sup:
        return effort
    # 🔴 规范外档位**原样透传**（§13.1 开放可扩展）。旧写法把它当成"高于 max"取 `len(LEVELS)`
    #    当下标 ⇒ `LEVELS[idx]` IndexError（实测 `degrade_effort("none", ["low","high"])` 直接抛），
    #    且"向上取最近"那一支会把**关闭推理**的请求升成厂商表里的最高档（A3-P0：客户端发
    #    `reasoning_effort:"off"` ⇒ 出站 `thinking:enabled + reasoning_effort:high`）。
    #    七档序排不进这个词 ⇒ 没有任何"向下就近"的依据，不许拿升降当依据。
    if key not in LEVELS:
        return effort
    idx = LEVELS.index(key)
    # 向下就近：从 idx 往下找第一个受支持的规范档
    for i in range(idx, -1, -1):
        if LEVELS[i] in sup:
            return LEVELS[i]
    # 向下无可用 → 向上取最近（宁可多给一点推理预算，也不静默丢失该参数）
    for i in range(idx + 1, len(LEVELS)):
        if LEVELS[i] in sup:
            return LEVELS[i]
    return effort


@dataclass
class Dialect:
    """单个模型的方言记录（由 `mgw probe` 三步探测得出）。"""

    model: str
    #: 真写入位（S2 生效验证通过者），如 `reasoning_effort` / `thinking.type`
    write_field: str = ""
    #: 该写入位的合法值域（S1 从 400 文案抠出）
    values: list[str] = field(default_factory=list)
    #: 方言族（`thinkingFormat`）：openai / openrouter / deepseek / together / zai / anthropic …
    thinking_format: str = ""
    #: 是否经 S2 生效验证（False = 仅 S1 粗筛，不可信）
    verified: bool = False
    #: 探测时的证据摘要（便于人工复核）
    note: str = ""


@dataclass
class DialectTable:
    """方言表：探测结果优先，硬编码 fallback 兜底（§13.4）。"""

    entries: dict[str, Dialect] = field(default_factory=dict)
    path: Path | None = None

    @classmethod
    def load(cls, path: Path | str | None) -> "DialectTable":
        """加载方言表。文件缺失/损坏 → 空表（安全降级，走硬编码 fallback）。"""
        p = Path(path) if path else None
        if p is None or not p.exists():
            return cls(entries={}, path=p)
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(entries={}, path=p)
        entries: dict[str, Dialect] = {}
        for model, d in (raw.get("dialects") or {}).items():
            if not isinstance(d, dict):
                continue
            entries[model] = Dialect(
                model=model,
                write_field=str(d.get("write_field") or ""),
                values=[str(v) for v in (d.get("values") or [])],
                thinking_format=str(d.get("thinking_format") or ""),
                verified=bool(d.get("verified")),
                note=str(d.get("note") or ""),
            )
        return cls(entries=entries, path=p)

    def save(self) -> None:
        """落盘（原子写，与既有纪律同口径）。"""
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "levels": list(LEVELS),
            "dialects": {
                m: {
                    "write_field": d.write_field,
                    "values": d.values,
                    "thinking_format": d.thinking_format,
                    "verified": d.verified,
                    "note": d.note,
                }
                for m, d in self.entries.items()
            },
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, model: str) -> Dialect | None:
        return self.entries.get(model)

    def thinking_format_of(self, model: str) -> str:
        d = self.entries.get(model)
        return d.thinking_format if d else ""
