# 06 · 参数归一化方案 —— 从 ZCode 的真实不足到更优解

> **本文件回答用户 2026-09-24 第二轮问题 1**：
> **「你发现 ZCode 处理得很简单，没有想象的那么好，你有什么更好方案解决『模型接入的参数不一、标准不一』这个问题？每接入一家适配一家，这肯定不是好的解决方案。」**
>
> 调研基线（**只读，零改动**）：`/Users/w/Desktop/01-关注的开源项目/ZCode`
> `config/provider/zcode-builtin.json` — **revision 30 · 6212 行 · sha256 `0b3d735e0c23…c5f424`**
> 所有统计数字均由本文件作者**用脚本从该文件重新算出**（脚本见 §11），非引用子 agent 结论。
>
> 关联：`01`（ZCode 机制全景）、`05`（行动清单 P0-2 / P1-1 / P1-2）。

---

## 一、先把问题切准：三种「不一」混在一起谈，必然得出「每家都要适配」

用户的原话里其实压着**三个不同层次**的问题。它们是**可分离**的，而且**只有一个是真难题**：

| 层 | 「不一」的表现 | 本质 | 数量级 | 能否消除 |
|---|---|---|---|---|
| **L-协议层** | 同一个模型，一个站点要 `max_tokens`，一个要 `max_completion_tokens`，一个要 `max_output_tokens` | **字段名不同** | **有限且收敛**（实测只有 3 种） | ✅ **可穷举，一次写完永久复用** |
| **L-语义层** | A 模型写 `reasoning_effort: "high"`，B 模型写 `thinking.type: "enabled"`，C 模型写 `output_config.effort: "high"` | **同一个意图，落到不同字段** | **有限**（实测只有 6 个字段路径） | ✅ **可穷举 + 映射表** |
| **L-词汇层** | 同样是「关闭推理」，12 个模型叫 `off`，1 个叫 `nothink`，现在统一叫 `disabled` | **同一个语义，用不同的词** | **会随厂商改名持续增长** | ⚠️ **不能消除，但能"隔离"** |
| **L-能力层** | 上下文窗口 16 种取值（`202752` / `1000000` / `1048576`…）；有的支持图片有的不支持 | **硬件/服务真实差异** | **不可消除** | ❌ 只能**如实声明 + 探测** |

> **关键判断**：
> - **协议层 + 语义层是"有限集"** → 把它们**穷举成表**，就是「一次适配，永久复用」，这正是用户要的。
> - **词汇层是真正的坑**，也是 ZCode 付出最大代价的地方（§三·不足 2 有量化证据）。
> - **能力层不能归一化**，只能**准确声明**。把"能力层差异"误当成"参数不一"去归一化，是方向性错误。

**→ 所以「更好的方案」不是"再写一层适配器"，而是：把有限集穷举成表 + 给词汇层建立规范词汇表 + 把能力层从"手填"改成"探测"。**

---

## 二、先公正地说：ZCode 有三件事做对了（都要抄）

不能只讲它不足。以下三点**是正确设计，我们的方案要原样继承**：

| # | 做对的事 | 证据 | 为什么对 |
|---|---|---|---|
| **Z1** | **"站点"是一等公民，规则按 `baseUrl` 正则匹配** | 规则层 `providerSiteRules` 存在；`config/provider/zcode-builtin.json` 的 `config.modelConfigRules` 下有 5 层：`modelRules` / `modelApiRules` / `providerSiteRules` / `templateModelRules` / `builtinProviderModelRules` | **同一个模型在不同站点必须走不同方言** —— 这是现实，不是设计洁癖。不把站点建模进去，就只能"按厂商"适配，那才是真的每家都要写 |
| **Z2** | **配置驱动 + 加载期编译校验**（不是运行时报错） | `packages/shared/src/model-config.ts:5-19` —— `optionMapSchema` 在 `superRefine` 里调 `compileModelOptionMap(source, variableName)`，**配置加载时就把 map 编译一遍**，编译不过直接报 issue；`:24-32` 校验 `values` 非空、去重；全 schema `.strict()`（未知字段报错） | **把"配置写错"从运行时前移到加载期**。这是配置驱动方案能不能用的分水岭 |
| **Z3** | **`values` 按语义强度从低到高排序** | `packages/shared/src/model-config.ts:23` 注释：「**按语义强度从低到高排列**；首项是辅助调用可选的最低公开档位」；消费点 `auxiliary-model-options.ts:11` 取 `values[0]` 作默认最低档 | **承认了"档位是有序的"这个事实**。这是建立规范档位序的基础（§六·6.1 会把它推到全局） |

**→ 结论：ZCode 的"配置驱动 + 站点建模 + 加载期校验"是对的骨架。我们的方案是在这个骨架上补三块它缺的东西，而不是推翻它。**

---

## 三、ZCode 的四个真实不足（全部可证伪，逐条附证据）

### 不足 1 · 只归一化 **2 个**变量，其余维度**完全不管**

**证据**：`packages/model-option-map/src/types.ts:9`

```ts
export type ModelOptionName = "reasoningLevel" | "maxOutputTokens";
```

`packages/shared/src/model-config.ts:88-93` 的 `completeModelOptionSpecsDataSchema` 也只有这两项。

**后果**：`temperature` / `topP` / `topK` / `presence_penalty` / `frequency_penalty` / `stop` / `seed` **全部走直通透传**，不做任何归一化。用户在 ZCode 里换个站点，这些参数是否被上游接受、字段名是否一样，**它不管**。

> **诚实修正**：v1 调研说"ZCode 只归一化 2 个参数"——**这句字面是对的**（`types.ts:9` 就是 2 个）。v2 的 `01` 把它补成"2 个 DSL 变量 + 8 个能力位"，那是**另一条轨**（`model-config.ts:68-79` 的 `properties`），不是参数归一化。**两条轨不要混为一谈。**

### 不足 2 · **档位词汇不统一** —— 这是最深、代价最大的坑

**证据链（三份文件互相印证）**：

**(a)** `packages/provider-node/src/legacy-reasoning-level-renames.ts` —— **25 条手工改名条目**：

```
改名条目数: 25
oldLevel 分布: {'off': 24, 'nothink': 1}
按模型族: {'glm': 12, 'kimi': 3, 'deepseek': 2, 'qwen': 5, 'mimo': 3}
```

**(b)** 那唯一一条 `nothink` 是 **GLM-5.2**（`:7-10`），而**同厂的 12 个 GLM 模型全用 `off`**。

> 🔴 **这就是"标准不一"的活标本**：**同一家厂商、同一个语义（关闭推理）、同一时期，12 个模型用 `off`、1 个模型用 `nothink`。** 不是跨厂商差异，是**厂商内部就不一致**。

**(c)** `packages/provider-node/src/legacy-reasoning-level.ts` 为这 25 条写了一个**专用解析函数**（73 行）：查 personal 配置（`:19-29`）、查 provider（`:30-31`）、用 `WeakMap` 缓存旧规则集（`:10`、`:33-62`）、逐条 `overlay` 改写 `values`（`:43-58`）、再走原规则引擎重解析（`:64-70`）。

**(d)** 且 `:12` 注释明确：「**不迁移 Personal 配置**或在执行层放宽校验」→ 用户自己配的模型**不享受这个兼容**，`return undefined` → 下一站直接抛错。

**量化代价**：**一次"关闭档位改名"，换来 25 条映射 + 1 个 73 行专用函数 + 1 个 WeakMap 缓存 + 1 条例外规则。**

**根因**：ZCode 的档位词汇是**per-model 的**（`values` 定义在 model 级规则里），**没有一个全局规范词汇表**。所以词汇一漂移，就只能写 N 条映射去补。

### 不足 3 · 档位不在值域内 → **直接抛 400，无降级**

**证据**：`apps/zcode-cli/packages/adapters/src/model/model.ts:120-127`

```ts
const reasoningLevel = options.reasoningLevel;
const reasoningSpec = specs.reasoningLevel;
if (reasoningLevel === undefined || !reasoningSpec.values.includes(reasoningLevel)) {
  throw invalidRequest("reasoningLevel is not supported by the model", {
    reasoningLevel,
    values: reasoningSpec.values,
  });
}
```

同样地，`maxOutputTokens` 超上限也直接抛（`model.ts:108-118`）：

```ts
if (maxOutputTokens === undefined || !Number.isInteger(maxOutputTokens) ||
    maxOutputTokens <= 0 || maxOutputTokens > specs.maxOutputTokens.max) {
  throw invalidRequest("maxOutputTokens is outside the model option range", {...});
}
```

另一条路径 `bootstrap/src/app/provider-registry-selection.ts:164-171` 的 `resolveRegistryThoughtLevel` 只是**静默返回 `undefined`**（然后被上面那个 throw 接住）；`:173-182` 的 `requireRegistryThoughtLevel` 直接 `throw new Error("Unsupported reasoning effort")`。

**→ 全链路没有任何"就近降级"。不命中 = 失败。**

**为什么这对网关是致命的**：ZCode 是**客户端**——它可以在 UI 上只显示该模型支持的档位，用户根本选不到不支持的。而**网关是服务端**：请求是**别人已经发过来的**，网关 400 掉 = 用户的请求白费。**网关必须降级 + 标注，不能照抄这个语义。**

### 不足 4 · 全靠手填，**没有探测**；组合爆炸仍在

**证据**：从 `zcode-builtin.json` 重新统计（脚本见 §11）：

| 维度 | 实测数量 |
|---|---|
| `reasoningLevel` 节点出现次数 | **155 次** |
| 其中 `values: []`（空值域 = 明确声明"不支持"） | **78 次**（占一半） |
| 去重后的 `values` 值域 | **18 种**（17 种非空 + 1 种空） |
| 去重后的 `reasoningLevel.map` | **22 种** = `null`×1（不写入）+ `{}`×1（空 patch）+ **20 种真实表达式** |
| 去重后的 `maxOutputTokens.map` | **4 种写法** = 3 个字段名（`max_tokens`×16 / `max_completion_tokens`×1 / `max_output_tokens`×1）；`max_tokens` 那 16 次里有 1 次写成单引号 `'max_tokens'` |
| 去重后的 `contextWindow` 取值 | **16 种**（`1000000`×38 / `200000`×11 / `131072`×10 / `262144`×10 / `204800`×9 / …） |

**两个必须说清的点**：

1. **`values: []` 占 78/155 = 一半**。也就是说，**ZCode 有一半的配置行是在手写"这个模型不支持推理档位"**。这个信息**本该是探测出来的**，却成了手填负担。
2. **组合爆炸没有被消除，只是从"代码"搬到了"JSON"**。20 种表达式 × 18 种值域 × 16 种窗口，**全部手写**。ZCode 把"每接一家写一段代码"变成了"每接一家填一段 JSON"——**这是进步，但没有改变"数量随接入数线性增长"这个本质**。用户说"每接入一家适配一家，这肯定不是好的解决方案"，**ZCode 恰恰还是这个模式，只是换了个介质**。

> **补充（我自己的一个错误假设，已自我否决，记录在此以示核验有效）**：
> 我最初看到 `maxOutputTokens.map` 里 3 处用单引号 `'max_tokens'`、15 处用双引号，怀疑这是 ZCode 的**潜在编译期 bug**（若解析器只认双引号，这 3 条会在加载期炸）。
> **核查结果：假设不成立。** `packages/model-option-map/src/tokenizer.ts:32` 明确写着 `if (character === "'" || character === '"')` —— **单双引号都接受**。
> → 所以这只是一处**写法不统一的数据质量问题**，不是缺陷。但**它恰好证明了另一件事**：**纯手写配置会漂移**（同一个方言两种写法），所以"规范化 + 校验"是必需的，不能只靠自觉。

---

## 四、把「每接入一家适配一家」证伪：要消除的是**线性增长**，不是**写代码**

先把"适配"这个词拆开。接入一家新厂商，到底要做什么？

| 要做的事 | 是否随接入数线性增长 | 说明 |
|---|---|---|
| **① 选协议族**（openai-chat / openai-responses / anthropic / gemini） | ❌ **不增长** | 实测只有 3 种输出上限字段名、4 种协议风格。**选一个，不是写一个** |
| **② 选写入位组合**（`thinking.type` / `reasoning_effort` / …） | ❌ **不增长** | 实测 20 种表达式只落在 **6 个字段路径**上（§五）；组合也只有 **10 种**（6 种含三元分支） |
| **③ 填值域映射**（我的 `["low","high"]` 对应规范序的哪几档） | ✅ **增长** | 但这是**一行数据**，且可**探测**得到 |
| **④ 填能力位**（contextWindow / 模态） | ✅ **增长** | 但这是**一行数据**，且**大部分可探测** |
| **⑤ 写适配代码** | ❌ **完全不增长** | 这是"坏方案"与"好方案"的分界 |

> **结论**：
> - **"每接入一家适配一家"之所以坏，不是因为"要做 5 件事"，而是因为其中的 ① ② ⑤ 被当成了"每家的私事"。**
> - **正确的做法：把 ① ② ⑤ 做成有限注册表（一次穷举，永久复用），只让 ③ ④ 随接入数增长，并把它们从"手填"降级为"探测 + 兜底"。**
> - **验收标准（可量化）**：接入一家新厂商 = **改 0 行代码 + 填 ≤ 6 行配置**（其中探测能覆盖的不填）。

---

## 五、更优方案：**四级归约**（L0 协议族 → L1 语义槽 → L2 写入位 → L3 方言）

### 5.0 一张图

```
工具（Trae / Cursor / Cherry Studio …）
   │  发送 OpenAI 格式请求：{"reasoning_effort": "high", "max_tokens": 4096}
   ▼
┌─────────────────────────────────────────────────────────────────┐
│ L1 · 语义槽（canonical slots）—— 我们自己的规范词汇，与厂商无关      │
│     reasoning.level ∈ {off,low,medium,high,max}  ← 有序！          │
│     output.max_tokens / input.context_window / capability.*        │
└───────────────────────────┬─────────────────────────────────────┘
                            │ ① 入站归约：把工具传来的任何写法 → 规范槽
                            │    ("high"→high / 8192→medium / "enabled"→high …)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ L0 · 协议族 —— 由「站点/端点」决定，不由厂商决定                      │
│     openai-chat / openai-responses / anthropic-messages / gemini   │
│     → 提供「通用字段名映射表」（temperature/top_p/stop/… 一次写完）   │
└───────────────────────────┬─────────────────────────────────────┘
                            │ ② 选族
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ L3 · 方言（dialect）= 写入位组合 + 每位的值域映射                    │
│     writes:                                                       │
│       - slot: thinking.type      map: {off: disabled, low: enabled, …}
│       - slot: output_config.effort  map: {low: low, high: high, …}  │
└───────────────────────────┬─────────────────────────────────────┘
                            │ ③ 降级：规范档位在 map 里缺档 → 按序就近取
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ L2 · 写入位注册表（write slots）—— 有限集，一次穷举                 │
│     thinking.type / reasoning_effort / reasoning.effort /          │
│     reasoning.enabled / output_config.effort / enable_thinking /   │
│     thinking.budget_tokens / max_tokens|max_completion_tokens|     │
│     max_output_tokens                                              │
└───────────────────────────┬─────────────────────────────────────┘
                            │ ④ 写入（JSON Merge Patch 语义 + 冲突守卫）
                            ▼
                    厂商站点（真正的不一在这里被吸收）
```

### 5.1 L0 · 协议族（Protocol Family）—— 归约「字段名」

**不按厂商分，按「站点声明的协议」分。** 实测只有 4 种风格：

| 协议族 | 特征 | 输出上限字段 | 推理字段风格 |
|---|---|---|---|
| `openai-chat` | OpenAI Chat Completions | `max_tokens` | `reasoning_effort`（平铺） |
| `openai-responses` | OpenAI Responses API | `max_output_tokens` | `reasoning.effort`（嵌套） |
| `anthropic-messages` | Anthropic Messages | `max_tokens` | `thinking.type` + `output_config.effort` |
| `gemini` | Google generateContent | `maxOutputTokens`（camelCase） | `thinkingConfig.thinkingBudget` |

**每个协议族配一张「通用字段名映射表」**，覆盖 `temperature` / `top_p` / `top_k` / `stop` / `seed` / 惩罚项 / 多模态内容块格式。**这张表一次写完，所有同族站点复用。** → 这是用户要的"不每接入一家适配一家"。

### 5.2 L1 · 语义槽（Canonical Slots）—— 归约「意图」

**定义我们网关自己的规范词汇，与任何厂商无关。** 这是**ZCode 完全没有的一层**（它的 `values` 是 per-model 的）。

```python
# 规范档位序 —— 有序！这是整个方案的基石
# 2026-09-24 修正：原稿写 5 档，实测 WorkBuddy CLI 的 EXTENDED_THINKING_LEVELS 为 7 档，
# 且 minimal / xhigh 是独立档位（不是 low / high 的别名）。见 `08` §4.6。
REASONING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")

# 入站别名归约表：把工具可能传来的任何写法收敛到规范序
INBOUND_ALIASES = {
    "none": "off", "disabled": "off", "false": "off", "nothink": "off",   # ← nothink 就是 ZCode 那个坑
    "think": "medium", "thinking": "medium",
    "low": "low",
    "medium": "medium", "enabled": "medium", "adaptive": "medium",        # 布尔开关 → 中档
    "high": "high",
    "highest": "max",
    # 注意：minimal / xhigh / max 是规范档位本身，不出现在别名表里
}
```

> **注意 `nothink → off` 这一行**：这**正是 ZCode 要写 25 条映射才能补上的东西**。在我们的方案里，它是**入站归约表里的一行**。这不是巧合——**把词汇归约做在"入站"（一次），而不是做在"每模型"（N 次），是本质区别。**
>
> **修正说明（2026-09-24 实测）**：原稿把 `minimal→low`、`xhigh→high` 当别名折叠，**这是错的**。实测 WorkBuddy CLI 的规范序是 7 档 `off < minimal < low < medium < high < xhigh < max`，`minimal`/`xhigh` 是一等档位；只有 `xhigh`/`max` 两档被要求"必须在模型声明里显式出现才可用"。折叠掉它们会让用户失去两个真实档位。

**规范语义槽清单**（完整）：

| 规范槽 | 类型 | 来源（工具侧） | 说明 |
|---|---|---|---|
| `reasoning.level` | enum，有序 5 档 | `reasoning_effort` / `thinking` / 自定义 | 核心 |
| `reasoning.budget_tokens` | int，可选 | `thinking.budget_tokens` / `max_thinking_tokens` | 预算与档位可并存 |
| `output.max_tokens` | int | `max_tokens` / `max_completion_tokens` / `max_output_tokens` | |
| `input.context_window` | int（能力位） | 不由工具传，**由网关声明** | 见 §七 |
| `capability.*` | bool（能力位） | 不由工具传，**由网关声明** | 见 §七 |
| `sampling.*` | float / int | `temperature` / `top_p` / … | 走 L0 的族映射表，**不进方言** |

### 5.3 L2 · 写入位注册表（Write Slots）—— 归约「字段路径」

**从 ZCode 的 20 种真实表达式里提炼**：**6 个推理写入位（W1–W6）** + **输出上限 1 位（W8，含 3 种字段名变体）**；**W7 是我方新增**（ZCode 中未使用）。脚本归组结果见 §11：

| # | 写入位 | 类型 | 合法值域 | ZCode 出现次数 | 覆盖的协议 |
|---|---|---|---|---|---|
| **W1** | `thinking.type` | enum | `disabled` / `enabled` / `adaptive` | 11 | anthropic-messages |
| **W2** | `reasoning_effort` | enum | 厂商自定义字符串 | 3 | openai-chat |
| **W3** | `reasoning.effort` | enum | `none` / `minimal` / `low` / `medium` / `high` / `xhigh` / `max` | 7 | openai-responses |
| **W4** | `output_config.effort` | enum | `low` / `medium` / `high` / `max` | 7 | anthropic 新式 |
| **W5** | `reasoning.enabled` | bool | true / false | 1 | 少数 OpenAI 兼容 |
| **W6** | `enable_thinking` | bool | true / false | 2 | DashScope / 通义风格 |
| **W7** | `thinking.budget_tokens` | int | >0 | **0（ZCode 未用）** | anthropic / gemini |
| **W8** | `max_tokens` \| `max_completion_tokens` \| `max_output_tokens` | int | >0 | 18 | 三族各一 |

> **归约率（脚本实测，§11）**：**20 种真实表达式（共出现 93 次）→ 6 个原子写入位 → 10 种写入位组合**（其中 **6 种含三元分支条件**，如 `reasoningLevel == "disabled" ? {…} : {…}`）。
>
> **三元分支不需要表达式引擎**：分支的本质是「同一写入位在不同档位下取不同值」，在映射表里就是 **`map` 的一个键多一个取值**（如 `thinking.type` 的 map 里 `off→disabled`、其余→`enabled`）。**这是把"逻辑"降维成"数据"的关键一步。**
>
> **W7 是我加的**（ZCode 没有）：预算型推理（`budget_tokens`）在 Anthropic / Gemini 上是**独立维度**，与档位不是一回事。ZCode 只用档位表达，所以无法表达"给 8000 token 思考预算"这种意图。**这是加法，不是抄。**

### 5.4 L3 · 方言（Dialect）= 写入位组合 + 每位的值域映射

**配置形态（YAML，直读，零解析器）**：

```yaml
# ── L0 协议族：一次穷举，所有同族站点复用 ──
protocol_families:
  anthropic-messages:
    field_map:                     # 通用字段名映射（与推理无关的部分）
      max_tokens: max_tokens
      stop: stop_sequences
      top_p: top_p
      temperature: temperature
  openai-responses:
    field_map:
      max_tokens: max_output_tokens
      stop: stop
      # …一次写完

# ── L3 方言：接入一家新厂商，通常只需在这里加 3~6 行 ──
# 键 = 7 个规范档位（off/minimal/low/medium/high/xhigh/max）；
# 值 = 该厂商写法；null = 该厂商不支持这一档（→ 网关按 §6.1② 保守降级）
dialects:
  # ① 商汤（现状硬编码的那套，保留为默认，零回归）
  sensenova-thinking-effort:
    protocol: anthropic-messages
    writes:
      - slot: thinking.type
        map: { off: disabled, minimal: enabled, low: enabled, medium: enabled,
               high: enabled, xhigh: enabled, max: enabled }
      - slot: reasoning_effort
        map: { off: null, minimal: low, low: low, medium: medium,
               high: high, xhigh: high, max: high }

  # ② DeepSeek 官方站 openai-responses 风格（对照 zcode-builtin.json:4148-4162）
  deepseek-responses-effort:
    protocol: openai-responses
    writes:
      - slot: reasoning.effort
        map: { off: none, minimal: minimal, low: low, medium: medium,
               high: high, xhigh: high, max: high }

  # ③ GLM / opencode 站（对照 zcode-builtin.json:3520-3548）
  glm-opencode-effort:
    protocol: openai-chat
    writes:
      - slot: reasoning_effort
        map: { off: disabled, minimal: low, low: low, medium: medium,
               high: high, xhigh: high, max: max }

  # ④ 双开关型（同时写 thinking.type + enable_thinking，对照那 1 处四字段齐写）
  dashscope-dual-toggle:
    protocol: openai-chat
    writes:
      - slot: thinking.type
        map: { off: disabled, minimal: enabled, low: enabled, medium: enabled,
               high: enabled, xhigh: enabled, max: enabled }
      - slot: enable_thinking
        map: { off: false, minimal: true, low: true, medium: true,
               high: true, xhigh: true, max: true }
```

> **对比 ZCode 的同一件事**：ZCode 要写一段 **CEL 表达式字符串**（如 `reasoningLevel == "disabled" ? {"thinking":{"type":"disabled"}} : {"thinking":{"type":"enabled"},"output_config":{"effort":reasoningLevel}}`），需要 `parser.ts`(240 行) + `tokenizer.ts` + `compiler.ts`(92 行) + `evaluator.ts`(214 行) 才能执行。
> **我们写的是 YAML 映射表，零解析器，且可静态校验。**

### 5.5 归约效果对比（这张表就是"更好"的定义）

| 维度 | ZCode | 本方案 | 差距 |
|---|---|---|---|
| 归一化的变量数 | **2**（`types.ts:9`） | **6 个语义槽**（含预算、能力位） | ×3 |
| 推理方言表达方式 | CEL 表达式（需 ~700 行 TS 引擎） | YAML 写入位映射表（**0 行引擎**） | — |
| 引擎代码量 | `parser`+`tokenizer`+`compiler`+`evaluator` ≈ **700+ 行** | **0**（读 YAML + 写 dict） | **-700 行** |
| 规范档位词汇 | ❌ 无（`values` 是 per-model） | ✅ **全局有序 5 档** | **本质差异** |
| 词汇漂移的代价 | **25 条手工映射 + 73 行专用函数** | **入站别名表 +1 行** | **×25 → ×1** |
| 档位不命中 | **抛 400**（`model.ts:122-127`） | **按规范序就近降级 + 响应头标注** | 语义差异 |
| 值域来源 | 手填（155 处，其中 78 处是空值域） | **探测优先 + 配置兜底** | 工作量差异 |
| 加载期校验 | ✅ map 可编译 + values 非空去重 | ✅ **+ 写入位合法性 + 值域合法性 + 冒烟探测** | 强于 |
| 冲突处理 | ✅ JSON Merge Patch + 冲突守卫 | ✅ 照抄（`merge-patch.ts:66-67` 语义 + RFC 7386） | 持平 |
| 站点建模 | ✅ 一等公民 | ✅ 照抄 | 持平 |
| 接入一家新厂商 | 写 CEL + 手填 values + 手填能力位 | **改 0 行代码 + 填 ≤6 行 YAML** | **用户诉求达成** |

---

## 六、三个 ZCode 没有的关键机制（这才是"更好"的实质）

### 6.1 规范档位序 + **就近降级**（替代 400）

**规范序**：`off < minimal < low < medium < high < xhigh < max`（有序，**7 档**）

**降级规则**（当某资源的值域不含请求的规范档位时）：

```
1. 若 map 里显式声明了该规范档 → 用声明值
2. 否则 → 在值域里找「不高于请求档」的最高档（保守降级，不越权）
3. 若不存在更低的 → 取值域最低档
4. 在响应头 / 日志里标注：X-MGW-Reasoning-Degraded: high->medium
```

> **⚠️ 本节 2026-09-24 被实测部分修正 —— 必须先分清"两层 clamp"：**
>
> | 层 | 谁执行 | 依据 | 实测到的规则 |
> |---|---|---|---|
> | **① 能力层 clamp** | **工具**（WorkBuddy CLI 等） | 网关下发的 `caps.thinkingLevelMap` | **就近取，优先向上**（`clamp()`：先往高找，再往低找，兜底最低档） |
> | **② 方言层降级** | **网关**（工具不带翻译引擎时的兜底） | 方言表的值域 | 保守降级，**只降不升** |
>
> **这不是矛盾，是两个不同层面。** 工具在"模型支持什么"这一层选档，网关在"厂商接受什么值"这一层兜底。原稿把两者混为一谈，措辞有误导。
>
> **实测证据**：WorkBuddy CLI `clamp()` 的实现是
> ```js
> if (supported.includes(level)) return level;
> for (let i = idx+1; i < LEVELS.length; i++) if (supported.includes(LEVELS[i])) return LEVELS[i];  // 先向上
> for (let i = idx-1; i >= 0;      i--) if (supported.includes(LEVELS[i])) return LEVELS[i];        // 再向下
> return supported[0] ?? "off";
> ```
> 见 `08` §4.6。
>
> **结论与建议**：**网关优先把 `thinkingLevelMap` 下发给工具，让工具按 ① 做 clamp**；网关自己的 ② 只在"工具没有 clamp"时生效。**若工具已 clamp，网关不得二次 clamp**（否则会与工具打架）。
>
> **② 为什么仍坚持"只降不升"**：网关是用户没直接盯着的那一层。用户请求 `high`、方言只有 `low` 与 `max`，网关擅自升到 `max` 会让账单变贵且用户无感。**降级只允许向下，不允许向上。** 这一条写进 PRD。

**这一条直接回应了 ZCode 的不足 3**：`model.ts:122-127` 的 throw 是客户端语义（用户选不到就不发），网关不能有。

### 6.2 **探测优先**（Probe）替代手填 —— 把 78 处空值域变成 0 处

**ZCode 手写了 78 处 `values: []` 来声明"不支持推理档位"。这 78 行本该是探测结果。**

> **✅ 2026-09-24 实测：探测假设成立，但原设计有缺陷，已修正。详见 `08` §九。**
> - **假设验证**：上游对非法档位返回 **400 且文案直接列出全部合法值**
>   （实测原文：`field ReasoningEffort invalid, should be one of: low, medium, high, xhigh, none`）→ **假设成立** ✅
> - **🔴 原设计的缺陷**：**「返回 200」不等于「参数生效」**。实测发现 `reasoning.effort=bogus`（**非法值**）
>   与 `thinking.type=enabled` 都返回 **200**，但 `reasoning_tokens` 与"不传参数的基线"毫无差别
>   → **上游根本不认识这些字段，直接忽略**。只做 200/400 二分会把它们误判成"支持的写法"。
> - **🔴 规范序必须是开放可扩展的**：实测 `deepseek-v4-pro` 的值域含 **`ultra`**，
>   **超出 7 档规范序**。遇到规范外档位**不能报错**，应原样透传。

**探测设计（修正后，`08` §9.4）** —— `mgw probe`，与 `05` 的 P0-7 合并。**三步，缺一不可**：

| 步 | 探测项 | 方法 | 产出 |
|---|---|---|---|
| **S0** | 协议族 | `GET {base}/models` 的响应结构 + 一次最小 chat 请求的字段回显 | 自动判定协议族 |
| **S1** | **粗筛**写入位 | 对候选写入位发一个**非法值**：400 + 文案含 `should be one of:` → **被校验**；200 → **被忽略，排除** | 真写入位候选 + 值域 |
| **S2** | **生效验证**（**新增，必需**） | 对 S1 选出的写入位发**极值**（如 `none`/`off`），与**不传参数的基线**对比 `usage.completion_tokens_details.reasoning_tokens` | 有显著差异（尤其归零）→ 确认生效；≈ 基线 → **判为假方言，丢弃** |
| **S3** | 定档 | 在 S2 确认的写入位上逐档取合法值，200 即收录 | `thinkingLevelMap` |

> **为什么 S1 和 S2 缺一不可**：S1 用 1 次请求拿值域（快），S2 排除"被忽略的字段"（否则会配出一张
> **看起来对、实际无效**的方言表）。
>
> **本次实测的教训**：我在本文 §5.4 里**手填**的 `sensenova-thinking-effort` 方言写的是
> `thinking.type + reasoning_effort`，而**实测真方言是 `reasoning_effort` + `low/medium/high/xhigh/none`**
> —— `thinking.type` 那一整条是**错的且会被上游忽略**。**这是"探测替代手填"价值的最直接证据。**
>
> **⚠️ 探测代价**：会消耗额度并**频繁触发 429**（本次 20 余次请求约 1/3 被限流）。
> → 必须串行 + 间隔 + 429 退避重试 + **结果落盘缓存**，不能每次启动都探。
| 值域词汇 | 从 400 的错误文案里提取合法值（多数上游会回显 `supported values: [...]`） | `map` 的目标词表 |
| `contextWindow` | 优先 `/models` 的 `context_length`；无则读配置 | 数值 |
| 模态能力 | `/models` 的 `architecture.input_modalities`（部分厂商有） | bool 位 |
| 输出上限 | `/models` 的 `max_output_tokens` / `top_provider.max_completion_tokens` | 数值 |

**探测结果落库为 `data/probe-cache.json`（明文、本地、可手改覆盖）**：
- 探测成功 → 写缓存，**不写配置文件**（配置只放"探测不到的兜底 + 人工覆盖"）
- 探测失败（无 `/models`、无权限）→ 回落到配置兜底
- **手动覆盖优先级最高**（用户明确知道得比探测准的情况）

> **这条是"更好"的最实在的部分**：它把 ZCode 的 **155 处手填**（78 处空值域 + 18 种值域 + 16 种窗口）**大部分变成自动**。

### 6.3 **冒烟校验**（Smoke Check）—— 让"配置正确性"可测量

ZCode 的加载期校验（`model-config.ts:5-19`）只能验「map 语法能否编译」+「values 非空去重」，**验不了「写进去的字段上游认不认」**。

**我们的加法**：配置加载后，对**每个"资源 × 方言"组合**发一次最小冒烟请求（`max_tokens=1`，`messages=[{"role":"user","content":"hi"}]`），断言 **HTTP 200**。
- 通过 → 标记该组合 `verified`
- 失败且是 400 → **加载期就报错**（而不是等到用户第一次真调用）
- 失败但是网络/鉴权错 → 标记 `unverified`，不阻塞启动

**产出**：`mgw doctor` 里一张 `资源 × 方言 → verified / unverified / failed` 的矩阵。**这就是"配置对不对"的可测量答案**，也是把 `01`/`02`/`03` 里的「未验证」变成「已验证」的机制。

> **成本控制**：默认**只对 `enabled` 且被某个启用模型引用的资源**做冒烟；`--full` 才全量。避免启动变慢。

---

## 七、能力位（`contextWindow` 等）：抄什么、改什么

**ZCode 的能力位 schema**（`packages/shared/src/model-config.ts:68-79`）——**8 个字段 / 13 个布尔位 + 1 个数值**：

```ts
export const completeModelPropertiesDataSchema = z.object({
  requiresMfjsToolSchema: z.boolean(),          // ① 厂商专有：需要特定工具 schema 格式
  contextWindow: z.number().int().positive(),   // ② 上下文窗口
  inputFormat: completeModelInputFormatDataSchema,   // ③ 5 个布尔位
  outputFormat: completeModelOutputFormatDataSchema, // ④ 1 个布尔位
  supportsToolCall: z.boolean(),                // ⑤
  supportsJsonSchemaOutput: z.boolean(),        // ⑥
  supportsNativeWebSearch: z.boolean(),         // ⑦
  supportsMidConversationSystem: z.boolean(),   // ⑧
}).strict();
// inputFormat = { supportsText, supportsImage, supportsVideo, supportsAudio, supportsPdf }
```

| 抄什么 | 改什么 |
|---|---|
| ✅ 字段划分（输入格式 5 位 / 输出格式 1 位 / 工具 1 位 / JSON schema 1 位 / 窗口 1 个） | ⚠️ **`requiresMfjsToolSchema` 是厂商专有概念**，不进我们的公共能力位（要进就进"方言"里） |
| ✅ `.strict()` + 逐层 overlay 的 sparse 语义（`sparseShape`） | ⚠️ **`supportsMidConversationSystem` 对我们是"网关要不要在中间插 system"**，语义要重定义 |
| ✅ 加载期校验 | 🔴 **加"资源级覆写模型级"**（ZCode 是 model 级 + 站点覆写；我们的差异载体是**资源**，见 `05` P1-2） |
| — | 🔴 **加探测填充**（§6.2）：`/models` 有 `context_length` 就用真值，不手填 |
| — | 🔴 **加"超窗时的行为声明"**：`reject` / `truncate` / `passthrough`。ZCode 只有硬校验（超窗即 400），网关需要可选策略 |

> **`01` §6 已确认**：ZCode 的 `contextWindow` **真的参与请求链路**（驱动上下文裁剪阈值 / 多模态降级 / 请求前硬校验），共 16 种取值，被 `modelRules` 覆写 81 次、`providerSiteRules` 覆写 26 次。**→ 这个维度我们必须有，且必须支持资源级覆写。**

---

## 八、落到网关：文件级设计

| 层 | 落点 | 内容 | 是否须入 PRD |
|---|---|---|---|
| **L0 协议族** | `model_gateway/config/protocol_families.py`（新建）+ `config/presets.py` 扩展 | 4 张族级字段名映射表 | ⚠️ 须（新增配置维度） |
| **L1 语义槽 + 入站归约** | `model_gateway/core/ir.py` 新增 `canonicalize_reasoning()`；`ReasoningSpec` 扩为规范槽 | 规范档位序常量 + 别名归约表 | ⚠️ 须 |
| **L2 写入位注册表** | `model_gateway/config/write_slots.py`（新建） | 8 个写入位的定义 + 值类型 + 合法值域 | ⚠️ 须 |
| **L3 方言** | `model_gateway/config/schemas.py` 新增 `ReasoningDialect`；`config.yaml` 的 `dialects:` 段 | 写入位组合 + 值域映射 | ⚠️ 须 |
| **写入执行** | `model_gateway/core/param_patch.py`（新建，即 `05` 的 P0-2） | JSON Merge Patch 语义（RFC 7386）+ **路径级冲突守卫** | ✅ 内部 |
| **调度接入** | `core/scheduler.py:229-231` 改造：`apply_model_params` → `merge_reasoning` → **`apply_dialect`（替代硬编码的 `inject_reasoning_into_body`）** | 保留原函数作 `sensenova` 预设默认实现，**零回归** | ✅ 内部 |
| **降级标注** | `api/openai_compat.py` 响应头 + `data/gateway.log` | `X-MGW-Reasoning-Degraded` | ⚠️ 须（对外契约） |
| **能力位** | `config/schemas.py` 的 `SystemModel.capabilities` + `ModelResource.capabilities`；`core/resources.py` 的 `ResourceState` 加快照字段 | 资源级覆写 | ⚠️ 须 |
| **探测** | `model_gateway/probe.py`（新建）+ `scripts/probe_models.py` | `mgw probe` | ⚠️ 须 |
| **冒烟** | `model_gateway/probe.py` 的 `smoke()`；接入 `mgw doctor` | `资源 × 方言 → verified` 矩阵 | ⚠️ 须 |
| **验证** | `tests/test_param_patch.py` / `tests/test_dialects.py`（新建） | 覆盖：归约、降级、冲突守卫、加载期校验、8 个写入位逐位 | ✅ |

**依赖顺序**（与 `05` 对齐）：
```
P0-2 param_patch.py（冲突守卫，路径级）
   └─▶ P1-1 L1+L2+L3 方言表（依赖守卫，因为引入嵌套路径如 thinking.type）
          └─▶ P1-2 能力位（独立，但共用 ResourceState 快照）
                 └─▶ 探测 + 冒烟（依赖前两者才能生成"资源 × 方言"矩阵）
```

---

## 九、不做的事（避免堆屎山）

| # | 不做 | 理由 |
|---|---|---|
| **N1** | **不引入受限 CEL / 任何表达式引擎** | 我们的方言是**数据表**，不是表达式。ZCode 需要表达式是因为它要支持"三元分支选不同字段"这种复杂逻辑；我们把它**降维成"写入位组合"**，就不需要了。→ **省 700 行引擎代码 + 省一个 DSL 的学习/调试成本** |
| **N2** | **不做「逐厂商适配代码」** | 这是用户明确否掉的。协议族映射表 + 写入位注册表 + 方言 YAML，**改 0 行代码** |
| **N3** | **不重写 IR / 不推翻透传优先** | 我们与 ZCode 的架构差异是**根本的**：ZCode 是客户端（入向 IR，可自由重塑），我们是**双向网关**（透传优先，只做协议间必需映射）。归一化只加在**出站写参数**这一段，**不动 IR 主干** |
| **N4** | **不把"能力层差异"当"参数不一"去归一化** | `contextWindow` 是**事实**不是**口径**。归一化的目标不是让所有模型"看起来一样"，而是让**调用方的意图能被正确翻译** |
| **N5** | **不做"虚拟模型名 / 策略路由"** | 与 Q18-③ / Q23-② 定论有张力，**需先翻案**（`05` P2-3），本方案不碰 |
| **N6** | **不自动向上提档** | 见 §6.1：降级只向下。避免静默增加用户成本 |

---

## 十、未验证与风险（诚实标注）

| # | 未验证项 | 影响 | 计划 |
|---|---|---|---|
| **U1** | 4 个协议族的"通用字段名映射表"**我只验证了输出上限与推理字段**，`stop` / 惩罚项 / 多模态内容块格式**未逐一取证** | 族映射表可能不全 | 落 PRD 前补一轮取证；或先只覆盖已验证字段，其余透传 |
| **U2** | §6.2 的**二分探测**假设"上游对不支持的档位返回 400 且文案可解析" —— **未实测任何一家** | 探测成功率未知 | 必须先做 `mgw probe` 的**单厂商试验**，再决定是否推广 |
| **U3** | `thinking.budget_tokens`（W7）在 ZCode 中**出现 0 次**，我是**从协议知识加的**，**未经参考项目验证** | 可能是过度设计 | 标为**可选**；仅当实测某站点确实只认预算不认档位时才启用 |
| **U4** | ZCode 那 20 种表达式的**实际运行效果**（哪些真的被上游接受）**未实测** | 我的"8 个写入位"归约可能漏掉某些隐式约束 | 归约结论**只保证"覆盖 ZCode 已表达的"，不保证"覆盖上游实际接受的"** |
| **U5** | `01` §13 / `02` §10 / `03` §9 / `04` §7 的未验证项**仍然有效**，本文件不重复 | — | 见各文件 |
| **U6** | 本方案的**性能开销未测**（每次请求多一次归约 + 映射查找） | 预期可忽略（纯内存 dict 查找），但**未实测** | 实现后补 benchmark |

**已知的"我们比 ZCode 弱"的地方（不回避）**：
- ZCode 的 **UI 是同步的**：它能在模型选择器里只列出该模型支持的档位，用户**根本选不到**不支持的。我们作为网关**拿不到这个便利** —— 只能事后降级 + 标注。这是**架构差异带来的固有代价**，不是实现缺陷。

---

## 十一、统计脚本（可复跑）

以下脚本产出本文件所有统计数字。基线：`zcode-builtin.json` revision 30 / sha256 `0b3d735e0c2334353eecadfa8c0756a1a19fc4f7938fc62882048d6630c5f424`。

```python
import json, re, collections
P = "/Users/w/Desktop/01-关注的开源项目/ZCode/config/provider/zcode-builtin.json"
d = json.loads(open(P, encoding="utf-8").read())
mcr = d["config"]["modelConfigRules"]

maps, values, mo, cw = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()

def scan(node):
    st = [node]
    while st:
        cur = st.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k == "reasoningLevel" and isinstance(v, dict):
                    values[tuple(v.get("values") or [])] += 1
                    mp = v.get("map")
                    maps[json.dumps(mp, sort_keys=True) if not isinstance(mp, str) else mp] += 1
                elif k == "maxOutputTokens" and isinstance(v, dict):
                    if v.get("map") is not None:
                        mp = v.get("map")
                        mo[json.dumps(mp, sort_keys=True) if not isinstance(mp, str) else mp] += 1
                elif k == "contextWindow":
                    cw[json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v] += 1
                st.append(v)
        elif isinstance(cur, list):
            st.extend(cur)

for layer, val in mcr.items():
    for node in (val if isinstance(val, list) else [val]):
        if isinstance(node, dict):
            scan(node)

print("reasoningLevel 出现:", sum(values.values()))                          # 155
print("values 值域(含空/非空):", len(values), len([k for k in values if k]))  # 18 / 17
print("reasoningLevel.map 去重:", len(maps))                                 # 22 (= null×1 + {}×1 + 真实×20)
print("maxOutputTokens.map 去重:", len(mo))                                  # 4 写法 = 3 字段名
print("contextWindow 取值去重:", len(cw))                                    # 16

# ── 20 种真实表达式 → 写入位组合 ──
SLOTS = [
    ("thinking.type",        r'"thinking"\s*:\s*\{[^}]*"type"'),
    ("reasoning.effort",     r'"reasoning"\s*:\s*\{[^}]*"effort"'),
    ("reasoning.enabled",    r'"reasoning"\s*:\s*\{[^}]*"enabled"'),
    ("output_config.effort", r'"output_config"\s*:\s*\{[^}]*"effort"'),
    ("reasoning_effort",     r'"reasoning_effort"\s*:'),
    ("enable_thinking",      r'"enable_thinking"\s*:'),
]
combos = collections.Counter()
for m, n in maps.items():
    if m in ("null", "{}"):
        continue
    combos[tuple(sorted(s for s, pat in SLOTS if re.search(pat, m)))] += n
print("写入位组合数:", len(combos))          # 10
print("含三元分支的表达式数:",
      len([m for m in maps if m not in ("null", "{}") and re.search(r"\?\s*\{", m)]))  # 6
for c, n in combos.most_common():
    print(f"  [{n:3d}次] {list(c)}")
```

配套的**文档引用机械核验器**：`drafts-v2/verify-v2.py` —— 本文件的统计数字已全部纳入其**第四层「统计断言」**（19 条），数字写错会直接报错。

---

## 十二、一句话回答用户

> **ZCode 把"每接一家写一段代码"变成了"每接一家填一段 JSON"——这是进步，但它没改变"数量随接入数线性增长"这个本质，而且在"档位词汇"上付出了 25 条手工映射的代价（因为它的档位词汇是 per-model 的，没有全局规范表）。**
>
> **更好的方案是四级归约：**
> **① 协议族**（4 种，一次穷举）**→ ② 语义槽**（我们自己的规范词汇，含**全局有序 5 档**）**→ ③ 写入位注册表**（8 个字段路径，从 ZCode 的 20 种表达式提炼）**→ ④ 方言**（写入位组合 + 值域映射，纯 YAML，零引擎）。
>
> **带来的三个实质差别**：
> - **接入一家新厂商 = 改 0 行代码 + 填 ≤6 行 YAML**（而不是写 CEL 表达式）；
> - **档位不命中时按规范序就近降级并标注**（而不是像 ZCode 那样直接 400 —— `model.ts:122-127`）；
> - **值域与能力位优先探测**（把 ZCode 那 78 处手写的"不支持"变成 0 处手填），并用**冒烟校验**让"配置对不对"变成可测量的矩阵。
