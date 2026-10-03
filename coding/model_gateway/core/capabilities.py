"""能力位组装（tech-design v2.0 §12 / PRD Q25-②）。

把网关内部已有的目录属性（`EnumEntry`）组装成**工具侧契约**要求的 8 个字段。

🔴 为什么需要：实测（`08` §6.4）工具侧 `supportsToolCall !== true` 会**删除请求中的 tools**、
无 `thinkingLevelMap` 会让推理档位**变哑** —— 网关没做错什么，但工具行为被静默改变。

⚠️ **字段名以工具契约为准（camelCase）**，此处**修正 PRD Q25-② 的字面**
（PRD 写 snake_case + 顶层 `effort_levels`；实测工具要的是 camelCase + `caps.thinkingLevelMap`）。
"""

from __future__ import annotations

from typing import Any

from model_gateway.core.dialects import build_level_map


def _flag(entry_value: Any, *, tool_call: bool = False, endpoint: str = "chat") -> Any:
    """能力位的三态归一（Q33 复验轮 R3-F-3）。

    - 枚举条目**说过** ⇒ 照它的 bool（True=具备 / False=明确不具备）。
      目录侧三个字段本身是 `bool`（`EnumEntry.tool_call` 默认 True 是 Q28-⑤ 的有意定版，
      且 `__post_init__` 把非 chat 端点的 `tool_call` 一律压成 False ⇒ 那条不变量住在目录里，
      本函数不重复实现第二遍）；
    - **没有条目**（自定义/账号独有模型）或该字段为 `None` ⇒
      - `supportsToolCall` 且端点不是 chat ⇒ `False`：**有依据的否**（图像端点没有 tools 参数，
        与 `EnumEntry.__post_init__` 同一条不变量，这里只是把它用到"目录里没有这条模型"的场合）；
        同一条不变量由**唯一出口** `_enforce_endpoint()` 压（三条返回路径全过）——
        账号目录能把 `tool_call=True` 并进来、目录条目本身也可能是 chat 名而系统模型被改成
        images，只在某一条来源的算法里守就等于只拦了一半（评审 R8-报备 R-8 / R9-声明 6）。
      - 其余 ⇒ `None` = **不知道**，🔴 不得印成 `false`：`false` 是对工具的 affirmative 承诺
        "这个模型干不了这件事"，而我们并没有这个证据 —— 那正是 §12 要消灭的"无报错的失败"的
        另一半。工具侧 `!== true` 对 `null` 与 `false` 处理相同（照旧保守 ⇒ 零回归），
        差别在我们不说谎 —— 至于界面上那一格"未知"：目前 `models.js` 的 `yn()` 把 null 与 false
        一律渲染成"—"，**还没有区分**（要改就是随 §22.5-9 那条"陈旧规格标注"同一波一起做，
        本轮不冒充已做，也不在此用现在时宣称）。
    """
    if entry_value is not None:
        return bool(entry_value)
    if tool_call and endpoint != "chat":
        return False
    return None


def build_model_caps(model: Any, enum_pool: Any, dialects: Any = None, *, spec: Any = None
                    ) -> dict[str, Any]:
    """组装单个系统模型的**能力位**（在原有 6 字段之外追加的部分）。

    返回 8 个键（`caps` 单独在 `build_caps_block` 里组装，便于 M3-2/M3-4 分期）：
    `name` / `vendor` / `maxInputTokens` / `maxOutputTokens` /
    `supportsToolCall` / `supportsImages` / `supportsReasoning` / `specStale`

    **自定义系统模型**（不在内置目录，Q19-② 允许就地新建）→ 走最小字段集，**不崩**；
    能力位此时是 `null`（= 不知道），不是 `false`（= 明确不支持）—— 见 `_flag`。
    **目录缺某属性**（如 `claude-sonnet-4` 无 `context_window`）→ 输出 `None`，
    工具回退自身兜底值，**与现状等价，不臆造数值**。

    🔴 `spec`（Q33-④，`core/model_spec.ModelSpec`）= 这个模型**在所有生效资源上**合并出来的
    规格。传进来时按「固定最大标准」合并：
      - 数值（输入/输出）取**较大值** —— 同一系统模型挂着 1M 窗口的账号与 262K 窗口的
        按量 Key 时，对外承诺的是 1M（用户 2026-10-02 定的口径）；
      - 布尔位取**并**（任一资源具备即具备），且**能把 `null`（不知道）升成 `true`**；
        规格说得出 `false`（= 每个开过口的来源都明说不具备）时也能把 `null` 落成 `false`；
      - 两边都是"没说"才输出 `null`（不知道 ≠ 不支持，绝不印 0/false 冒充有据）；
      - 🔴 端点不变量在合并**之后**再压一次：非 chat 端点的 `supportsToolCall` 只能是 `false`
        （图像端点没有 `tools` 参数，账号目录说 `true` 也不许并出承诺）。
    不传 `spec` 时数值腿与改动前**逐字一致**（旧调用点零风险）。
    `specStale`（债务 Q33-债8 第①条）：这条声明里**至少有一个数取自超 TTL 的目录缓存**时为 `true`；
    没有合并规格参与声明 ⇒ `false`（不是"不知道"—— 这件事只有目录缓存来源会说，而它说了没说过是可判定的）。
    """
    entry = enum_pool.get(model.name) if enum_pool is not None else None
    endpoint = str(getattr(model, "endpoint", "") or "chat")
    if entry is None and spec is None:
        return _enforce_endpoint({
            "name": model.name,
            "vendor": "",
            "maxInputTokens": None,
            "maxOutputTokens": None,
            "supportsToolCall": _flag(None, tool_call=True, endpoint=endpoint),
            "supportsImages": _flag(None),
            "supportsReasoning": _flag(None),
            "specStale": False,
        }, endpoint)
    base = {"name": (entry.display if entry is not None else "") or model.name,
            "vendor": entry.vendor if entry is not None else "",
            "maxInputTokens": entry.context_window if entry is not None else None,
            "maxOutputTokens": entry.max_output if entry is not None else None,
            "supportsToolCall": _flag(entry.tool_call if entry is not None else None,
                                      tool_call=True, endpoint=endpoint),
            "supportsImages": _flag(entry.image_input if entry is not None else None),
            "supportsReasoning": _flag(entry.reasoning if entry is not None else None),
            # 🔴 债务 Q33-债8 第①条的出口（用户批准的契约扩展之一）：这一条声明里的数
            #    **有没有取自陈旧目录缓存**。以前 `ModelSpec.from_stale_cache` 算出来了却没有
            #    任何消费方 ⇒ 界面上"昨天取到的数"和"实时取到的数"长得一模一样，用户以为
            #    看到的是当下事实。口径：`spec is None`（没有合并规格参与声明）⇒ `False`。
            "specStale": False}
    return _enforce_endpoint(base if spec is None else _merge_spec_maxima(base, spec), endpoint)


def _enforce_endpoint(caps: dict[str, Any], endpoint: str) -> dict[str, Any]:
    """非 chat 端点的 `supportsToolCall` 只能是 `false` —— **在唯一出口**压一次。

    🔴 评审 R8-报备 R-8：这条不变量原先只压在合并腿（`spec` 在场）上，而"目录里有同名条目
    但系统模型是 images 端点 + 没传规格"那条路（`entry.tool_call=True` 直出 `base`）根本没经过它 ⇒
    对外承诺了一句图像端点做不到的事。不变量属于**出口**，不属于某一条来源的计算方式。
    """
    if endpoint != "chat":
        caps["supportsToolCall"] = False
    return caps


def _merge_spec_maxima(caps: dict[str, Any], spec: Any) -> dict[str, Any]:
    """把统一规格并进能力位（数值取大、布尔三态取并、`None` 不参与取大也不冒充布尔）。"""
    out = dict(caps)
    for cap_key, spec_key in (("maxInputTokens", "max_input"),
                              ("maxOutputTokens", "max_output")):
        a, b = caps.get(cap_key), getattr(spec, spec_key, None)
        if a is None:
            out[cap_key] = b
        elif b is not None and b > a:
            out[cap_key] = b
    for cap_key, spec_key in (("supportsToolCall", "tool_call"),
                              ("supportsImages", "image_input"),
                              ("supportsReasoning", "reasoning")):
        flag = getattr(spec, spec_key, None)
        if flag:
            out[cap_key] = True           # 并集上半句：任一来源说"具备" ⇒ 具备
        elif flag is False and caps.get(cap_key) is None:
            # 🔴 并集**下半句**（真机复验 R5-F-4 缺口①）：规格说得出 `False` 时，它已经是
            #    "每个开过口的来源都说不具备"（`model_spec._any_true` 保证），那是**有据的否**，
            #    继续印 `null` 就是把这条证据丢掉 —— 目录侧能给 false、账号侧只能给 null 也不对称。
            out[cap_key] = False
        # 两边都没说 ⇒ 保持 `None`（不知道）。**不得**在这里把"不知道"写成 False ——
        # 那一步就是 R3-F-3 登记的"三态外泄"原缺陷。
    # 🔴 端点不变量不在这里压 —— 由唯一出口 `_enforce_endpoint()` 统一压（评审 R8-报备 R-8：
    #    原先只有"合并腿"守得住，而 `spec=None` + 目录条目 `tool_call=True` 那条路根本不经过这里，
    #    `endpoint=images` 的系统模型照样对外承诺 `supportsToolCall: true`。）
    # 陈旧标注：合并规格里**至少有一个数**来自超 TTL 的目录缓存 ⇒ 声明侧如实带上这件事。
    out["specStale"] = bool(getattr(spec, "from_stale_cache", False))
    return out


def build_caps_block(model: Any, enum_pool: Any, dialects: Any = None, *, spec: Any = None
                     ) -> dict[str, Any]:
    """组装 `caps` 块（§12.2a / §13.1）—— 含 `thinkingLevelMap`（**7 键齐全**）与 `thinkingFormat`。

    - `thinkingLevelMap`：规范序 7 键**必须全部出现**，不支持的档**显式写 `None`**（JSON 后为 `null`）。
      键缺失（`undefined`）≠ `null` —— 工具对非高阶档会把缺失键判为"支持"→ 上游静默忽略。
    - `thinkingFormat`：**从方言表取**（L-C 层，§14.1），**不在 `EnumEntry` 上取**（它没有该字段）。
    - 用户手改的 `model.caps_overrides` **优先级最高**（目录/探测不准时的逃生口）。
    """
    entry = enum_pool.get(model.name) if enum_pool is not None else None
    ov = getattr(model, "caps_overrides", None) or {}
    supported = list(getattr(entry, "effort_levels", None) or []) if entry else []
    if spec is not None:
        # 🔴 Q33-④：账号侧目录合并出的档位必须真的进 `thinkingLevelMap`（R3 F-2：
        #    上一版把 effort_levels 算进 ModelSpec 却没人消费 ⇒ 自定义名/账号独有模型的
        #    七键全是 null，工具侧推理档位变哑 —— 与 §12 实测过的原缺陷同一种病）。
        #    规范序与"规范外档位原样保留"由 `_union_effort` 保证，这里只做并集。
        merged = list(dict.fromkeys(supported + list(getattr(spec, "effort_levels", ()) or [])))
        supported = merged
    level_map = build_level_map(supported, ov.get("thinkingLevelMap"))

    fmt = ov.get("thinkingFormat")
    if not fmt and dialects is not None:
        fmt = dialects.thinking_format_of(model.name)
    return {"thinkingLevelMap": level_map, "thinkingFormat": fmt or ""}
