"""统一模型规格层（Q33-④）：把"两类接入"的模型规格并成网关一套标准，对外声明与出站默认都走它。

## 为什么要有这一层（调研轮实测，不是推测）

- 厂商侧（按量 Key）的规格住在**枚举池** `EnumEntry`；账号侧的规格住在各产品 `list_models`
  钩子的返回值里，**不落库、不进运行时** —— 唯一消费者是管理端弹窗，每次现调、零缓存。
- 于是 `/v1/models` 的 `maxInputTokens/maxOutputTokens` 与能力位**只按系统模型名查枚举池**
  （`core/capabilities.py`），产品规格完全不参与对外声明：同一个系统模型挂着
  buddy(1M/64K) 与 sensenova(262K/65K) 时，对外只能印一份数，另一份被抹平。
- 用户 2026-10-02 定的标准：**输入与输出上下文默认走"最大输入 / 最大输出"，固定最大标准**，
  并要求这套标准同时兼容两类接入。本模块就是这个"取数 + 合并"的唯一出口。

## 合并规则（每种字段一条明确规则，不靠"看情况"）

| 字段 | 规则 | 理由 |
|---|---|---|
| `max_input` / `max_output` | 池内**取最大**；无任何来源 = `None` | 用户定的"固定最大标准"；`None` 一律**不编造**（铁律 2），工具回退自身兜底 |
| `tool_call` / `image_input` / `reasoning` | 任一具备 ⇒ 具备；**全部来源都明说不具备** ⇒ 不具备；有来源沉默 ⇒ `None` | 与"最大"同向：承诺能力上限；但 `False` 会**删掉工具的 `tools`**（§12 实测），只有全否才是有据的否，混着沉默只能报"不知道" |
| `effort_levels` | **并集**，按规范档位序回排（规范外的档留在尾部） | 档位逐档声明；不支持的档由 `thinkingLevelMap` 显式写 `null`（§12.2a） |

## 数据来源与新鲜度

账号侧规格**只读本地目录缓存**（`accounts/catalog_cache.py`）⇒ 本模块在任何路径上
**零网络**（`tech-design §22.5-6`：请求期不查目录/余额）。缓存超 TTL 仍可用于兜底，`from_stale_cache` 已经把"陈旧"这件事算出来了，
但 🔴 **当前没有任何用户可见出口读它**（Q33 评审 R2-⑦：上一版注释把"打算做"写成"已做"）
⇒ 界面现在无法区分"实时规格"与"陈旧规格"，此项登记为未接线、下一波补。

## 三条消费腿的现状（2026-10-03 复验 R5/R8/R9 后更新，别再按"未接"重写一遍）

- **对外声明**（`/v1/models` 能力位、`mgw setup`）：读**模型级**合并结果（取大 = 承诺上限）；
  账号侧来源**逐号取**（按号缓存优先、产品级兜底）⇒ 只有按号目录时也能声明出数，
  不再一律 `null`（R5-F-1 的第三条后果）。这一份**带开关判据**（关着的映射不许顶上限）。
- **出站缺省**：读**这条资源自己**那份（`Runtime.resource_specs[(rid, vendor_model)]`
  = `resource_spec()`，🔴 不带开关也不带系统模型维度，评审 R8-B-1），
  缺省 `max_tokens` 用**这个号**的数，不再拿同产品别号的上限压给它
  （R5-F-1 的第二条后果 = 真实上游 400；判据 INT-80 第二腿专门造出"两资源两份不同的数"，
  否则改成池内最大照样绿 —— 评审 R9-OUTBODY）。
- **承载校验**：`core/scheduler.py:_capacity_reject` 在**非流与流式**两条选路循环里用同一判据：
  请求所需输出 > 该资源 `max_output` ⇒ 归还（成对还额度预留 + 在途）并换下一条，
  不记失败、不计 y；`max_output` 未知 ⇒ 不拦。判据读的就是上面那份**按号**规格 ⇒
  "超窗的号不被派活"在号级颗粒上才真的成立（R5-F-1 第一条后果）。
  终局原因：`ALL_OVER_CAPACITY` **只在**「拦过候选且一次都没真试」时才用，空池一律 `NO_RESOURCE`
  （评审 R5-F-2；文案只断言它真的知道的那部分，评审 R9-R2-续）。
仍未接线的一条：`from_stale_cache` 的用户可见出口（见上一节，欠账同台账 §7.2）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from typing import Callable

#: 账号侧目录缓存的读函数形状（装配侧注入，见 `product_spec`）：
#: `(product, root=..., account=...) -> 缓存视图 | None`。
#: 🔴 `account` 是**必传关键字**（空串 = 要产品级那一份；非空 = 要那个号自己的副本），
#:    R5-F-1 之后 core 恒带它调用；生产由 `main.py` 传 `accounts.catalog_cache.read_cache`，
#:    测试传的假读函数**形参必须同 arity**（少一个就是 `TypeError`，带 `**kw` 则会静默吞掉号）。
CatalogReader = Callable[..., dict[str, Any] | None]

#: 规范档位序（与 `core/dialects.py` 的 7 键同口径，§13.1）
CANONICAL_EFFORT = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")


@dataclass(frozen=True)
class ModelSpec:
    """一个**系统模型**在网关侧的合并规格（对外声明与出站默认的唯一来源）。

    三态纪律：`None` = 不知道（没有任何来源说过这件事）；`False`/`0` = 厂商明说不支持。
    两者绝不混写 —— 把"不知道"印成 0，工具会以为自己拿到了数。
    """

    max_input: int | None = None
    max_output: int | None = None
    tool_call: bool | None = None
    image_input: bool | None = None
    reasoning: bool | None = None
    effort_levels: tuple[str, ...] = ()
    #: 账号侧规格来自**陈旧**缓存（超 TTL）⇒ 调用方必须如实标注
    from_stale_cache: bool = False
    #: 参与合并的来源数（界面/排障用：0 = 这模型一份规格都没拿到）
    sources: int = 0


def _positive(value: Any) -> int | None:
    """目录里的数字字段读成正整数；None/0/负数/非数 ⇒ None（不参与"取最大"）。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _any_true(values: Iterable[Any]) -> bool | None:
    """三态并集：**任一 True ⇒ True**；**每个开过口的来源都是 False ⇒ False**；否则 `None`。

    🔴 为什么 `False` 要额外要求"没有来源沉默"（真机复验 R5-F-4 的下半句）：
    这一层的输出会被 `capabilities._merge_spec_maxima` 并进**对外承诺**。
    一个号明说 `tool_call=false`、另一个号的目录根本没说 ⇒ 若此处置 True 之外的 `False`，
    那个"没说话"的号若有此能力就对外被**误承诺成不支持**（`supportsToolCall !== true`
    会让工具直接删掉请求里的 `tools`，实测见 §12 头）。
    反过来全 False 才是有据的否：所有开过口的来源都说了"不行"。
    ⚠️ 厂商侧的"开过口"**含枚举目录的默认值**（评审 R8-报备 R-6，实测 `enums/matcher.py`：
    `tool_call` 默认 True、`image_input`/`reasoning` 默认 False 且是**非空 bool**）⇒
    用户扩展目录里没写这两个字段时，这里会当成"明说不支持"。这是 §12.3 **成文的目录默认值**，
    不是本轮三态改判要修的形状（改成三态 = 改 §12 字段契约，台账 §7.7 已登记待裁决）；
    账号侧不受此影响（钩子只产 `None` 或 `True`，实测无一处产 False）。
    """
    seen_all = list(values)
    seen = [v for v in seen_all if v is not None]
    if not seen:
        return None
    if any(bool(v) for v in seen):
        return True
    return False if len(seen) == len(seen_all) else None


def _union_effort(values: Iterable[Iterable[Any]]) -> tuple[str, ...]:
    got = {str(x) for seq in values for x in (seq or ()) if x}
    ordered = [e for e in CANONICAL_EFFORT if e in got]
    ordered += sorted(got - set(CANONICAL_EFFORT))   # 规范外的档保留（开放可扩展，不丢值）
    return tuple(ordered)


def merge_specs(sources: list[dict[str, Any]]) -> ModelSpec:
    """把若干份来源规格并成一份（来源顺序不影响结果：全是 max / any / union）。"""
    ins = [_positive(s.get("context_window")) for s in sources]
    outs = [_positive(s.get("max_output")) for s in sources]
    effort = _union_effort([s.get("effort_levels") or () for s in sources])
    tool = _any_true([s.get("tool_call") for s in sources])
    image = _any_true([s.get("image_input") for s in sources])
    reasoning = _any_true([s.get("reasoning") for s in sources])
    return ModelSpec(
        max_input=max([v for v in ins if v], default=None),
        max_output=max([v for v in outs if v], default=None),
        tool_call=tool, image_input=image, reasoning=reasoning,
        effort_levels=effort,
        from_stale_cache=any(bool(s.get("_stale")) for s in sources),
        sources=len(sources),
    )


def _view(product: str, account: str, root, cache: "dict | None",
          reader: "CatalogReader") -> dict[str, Any] | None:
    """读一份目录缓存视图；`cache` 在场时按 `(产品, 号)` 记忆化（同一次热重载不重复读盘）。"""
    if cache is None:
        return reader(product, root=root, account=account)
    # 🔴 键含 `root`（评审 R8-报备 R-4）：`root` 这个形参存在的意义就是"同一次装配可能跨两棵树"
    #    （非默认数据根的实例 / 测试混用），键里不带它 ⇒ 第二个号读到的是**第一棵树**的缓存。
    key = (product, account, str(root or ""))
    if key not in cache:
        cache[key] = reader(product, root=root, account=account)
    return cache[key]


def product_spec(product: str, vendor_model: str, *, root=None, cache: dict | None = None,
                 reader: "CatalogReader | None" = None,
                 account: str = "") -> dict[str, Any] | None:
    """账号侧规格来源：**只读本地目录缓存**（零网络）。取不到 = 没有来源，不编造。

    🔴 **按号优先、产品级兜底**（真机复验 R5-F-1，本函数原来只读产品级那一份）：
    `account` 非空 ⇒ 先读这个号**自己**的目录缓存（`_catalog_cache.<号>-<哈希>.json`），
    没有才回落到产品级那份。理由不是"更精确"这种口味问题，而是**后果**：
    同产品不同号的套餐/上限可以不同，全部号共用产品级那一个数时
    ① 小上限的号照常被派活、并被注入大号的上限 ⇒ 真实上游回 400（我们主动制造的失败），
    ② 只有按号缓存的号对外一律 `null` ⇒ 规格明明取到了却不声明。
    兜底方向只能是这样（产品级 = "这个产品的目录说过"，弱证据但比没有强）；
    反过来"按号覆盖产品级"不能省，否则权益窄的号继续吃 400。
    ⚠️ 这条兜底在**承载判据**上的已知取舍（真机复验 R5 §3(c) 如实报过）：一个从没有过自己
    目录缓存的号，会被产品级那个数拦下（可能拦错方向 = 它其实装得下）。选"照拦"而不是"放行"
    的理由是后果不对称：拦错了只是这次不打它（别的号承接，全被拦时有显式终局码与中文措辞），
    而放行则是**我们主动**给一个已知上限更小的号发一个超限请求 ⇒ 真实 400 + 计入 y + 被冷却。
    翻案触发点 = 实盘出现「整池 `ALL_OVER_CAPACITY` 而某号的真实目录明明更宽」这类可见误拦
    ⇒ 那时改成"承载判据只认这个号自己的新鲜缓存"，声明与缺省注入仍保留产品级兜底。

    🔴 分层（复验轮 R1-§二 / 债务 Q33-债2）：`core/` 不再直接 `import accounts/` ——
    缓存的读法由**装配侧注入**（`main.py` 把 `accounts.catalog_cache.read_cache` 传进来）。
    与 `ResourceManager` 的 `circuit_active` / `credential_fingerprint` 完全同一个口径：
    core 只定义"要怎么取"，具体从哪棵树取由上层决定，可测性也在这里（注入假读函数即可）。
    没注入 = 账号侧**没有来源**（不冒充、不联网、不在 core 里自己找文件）。

    `root` 只为测试与"非默认数据根"的实例留的透传口；生产调用点一律不传 = 走默认产品根。
    """
    if reader is None:
        return None
    cache_view = None
    if account:
        cache_view = _view(product, account, root, cache, reader)
    if cache_view is None:
        cache_view = _view(product, "", root, cache, reader)
    if not cache_view:
        return None
    info = next((m for m in cache_view["models"] if m.id == vendor_model), None)
    if info is None:
        return None
    return {"context_window": info.context_window, "max_output": info.max_output,
            "tool_call": info.tool_call, "image_input": info.image_input,
            "reasoning": info.reasoning, "effort_levels": info.effort_levels,
            "_stale": bool(cache_view.get("stale"))}


def _entry_source(res: Any, vendor_model: str, pools: Any, *,
                  cache_root=None, cache: dict | None = None,
                  reader: "CatalogReader | None" = None) -> dict[str, Any] | None:
    """一条 `(资源, 厂商模型)` 的规格来源 —— **不含任何开关判断**（两类接入各查各的）。

    抽出来只有一份实现，是因为"这条资源装得了多大"与"这条映射现在进不进池"
    是**两个正交事实**：判据 `mapping_enabled` 管后者（进池/声明/规格上限的合并），
    而资源级规格管前者，且它的键是 `(rid, vendor_model)`（评审 R8-B-1 判死的正是把两者
    混在一次计算里：别名形状下另一头那个关着的开关会把生效这头的规格**覆盖成空壳**）。
    """
    product = str(getattr(res, "product", "") or "")
    if product:
        # 🔴 带上**这个号自己的名字**（R5-F-1）：资源级规格是"这条资源装得了多大"的判据，
        #    同产品不同号权益可以不同 ⇒ 只有按号取才谈得上"按实际选中资源校验承载"。
        return product_spec(product, vendor_model, root=cache_root, cache=cache,
                            reader=reader,
                            account=str(getattr(res, "account_ref", "") or ""))
    if pools is None:
        return None
    # 🔴 枚举池按**厂商模型 id** 索引（`EnumPool.get`），而规格描述的是"我们实际发给
    #    上游的那条模型" ⇒ 必须用 `entry.model` 取，不能用系统模型名。
    #    先前写的是 `pools.get(model.name)`：只有当系统模型名恰好等于厂商模型 id 时才成立
    #    （本网关多数映射确实同名），一旦改挂/别名（如系统模型 `test-model` →
    #    厂商 `sensenova-6.8-flash-lite`）就取不到 ⇒ 出站缺省与对外声明双双静默失去规格。
    #    这条是评审 R2-③「单元已测、接线未测」在真机上打出来的实测缺口。
    e = pools.get(vendor_model)
    if e is None:
        return None
    return {"context_window": e.context_window, "max_output": e.max_output,
            "tool_call": e.tool_call, "image_input": e.image_input,
            "reasoning": e.reasoning,
            "effort_levels": getattr(e, "effort_levels", ()), "_stale": False}


def sources_for_entries(config: Any, model: Any, entries: Any, pools: Any = None, *,
                        cache_root=None, cache: dict | None = None,
                        reader: "CatalogReader | None" = None
                        ) -> list[dict[str, Any]]:
    """若干映射条目各自的规格来源（厂商侧查枚举池，账号侧查**注入的**目录缓存读函数；**零网络**）。

    这一份**带开关判据**（`mapping_enabled` + 号启用位）：它服务的是"这个系统模型对外承诺多大"，
    关着的映射不该把自己的大窗口"顶上去"。资源级那份请用 `resource_spec()`（不带开关）。
    """
    out: list[dict[str, Any]] = []
    by_id = {r.id: r for r in getattr(config, "resources", None) or []}
    for entry in entries or []:
        res = by_id.get(entry.resource)
        if res is None or not res.enabled:
            continue
        # 映射关的条目不参与规格（与调度同一判据：关着的资源不该把能力"顶上去"）
        if hasattr(config, "mapping_enabled") and not config.mapping_enabled(res, entry, model.name):
            continue
        src = _entry_source(res, entry.model, pools, cache_root=cache_root,
                            cache=cache, reader=reader)
        if src is not None:
            out.append(src)
    return out


def sources_for_model(config: Any, model: Any, pools: Any = None, *, cache_root=None,
                      cache: dict | None = None,
                      reader: "CatalogReader | None" = None) -> list[dict[str, Any]]:
    """一个系统模型的全部**生效映射**各自的规格来源。"""
    return sources_for_entries(config, model, getattr(model, "resources", None) or [],
                               pools, cache_root=cache_root, cache=cache, reader=reader)


def resolve(config: Any, model: Any, pools: Any = None, *, cache_root=None,
            cache: dict | None = None,
            reader: "CatalogReader | None" = None) -> ModelSpec:
    """合并出一个系统模型的网关级规格；一份来源都没有时返回 `sources=0` 的空壳。

    🔴 这一份只用于**对外声明**（"这个模型最高能到多大" = 池内最大）。
    出站默认与承载校验必须用 `resource_spec()`（实际选中**那条资源自己**的那一份，不带开关维度），
    否则会把窗口小的号打到 400（Q33 评审 R1-⑤ 判死；R8-B-1 又判死"带了系统模型维度"那一版）。
    """
    return merge_specs(sources_for_model(config, model, pools, cache_root=cache_root,
                                          cache=cache, reader=reader))


def resource_spec(resource: Any, vendor_model: str, pools: Any = None, *,
                  cache_root=None, cache: dict | None = None,
                  reader: "CatalogReader | None" = None) -> ModelSpec:
    """这条 `(资源 × 厂商模型)` **自己**的规格 —— 出站缺省注入与承载判据都按这份走。

    🔴 **不带开关、也不带系统模型维度**（评审 R8-B-1 判死的原因，实测红证见
    `test_q33_two_level_switch_api.py::TestPerAccountSpecWiring::test_another_system_model_switch_cannot_erase_this_resources_spec`）：
    `Runtime.resource_specs` 的键是 `(rid, vendor_model)`，而值若由"**某个系统模型**的映射
    是否生效"算出来，那么同一组合被**别名**挂到第二个系统模型上（`schemas.py` 的去重明确
    只在同一系统模型内、跨模型别名是既有设计，UT-84 还专门留了反证腿）而那一头关着时，
    空壳会**覆盖**掉生效那一份 ⇒ 承载判据不再拦、缺省注入也不再注，方向是 fail-open
    （= 我们主动给小上限的号发超限请求，真实上游 400），而且**红不红取决于配置里的书写顺序**。
    "进不进池"由 `mapping_enabled` 在 `sources_for_entries` / `resources.rebuild` 那侧决定，
    与"这条资源装得了多大"是两个正交事实 —— 一份计算里混两个事实就是这次的根因。
    """
    src = _entry_source(resource, vendor_model, pools, cache_root=cache_root,
                        cache=cache, reader=reader)
    return merge_specs([src] if src is not None else [])

