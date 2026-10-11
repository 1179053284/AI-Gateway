# ZCode「模型参数处理机制」深度代码考古报告（定稿）

> 调研对象：`/Users/w/Desktop/01-关注的开源项目/ZCode/`（只读，未修改任何文件）
> 权威源：`packages/model-option-map/src/*.ts`（8 个文件，共 867 行）+ `packages/provider/src/config/*.ts` + `config/provider/zcode-builtin.json`（6212 行）
> 所有结论均附 `文件路径:行号` 证据。凡未验证处已显式标注。
> **本文档已经过一轮独立核验（证伪导向）并按核验报告逐条修订，修订明细见「修订记录」。**

---

## 0. 结论先行（TL;DR）

1. **它不是一个"模型参数映射框架"，而是一台极窄的、单变量的表达式求值器**：option map 机制只处理 **2 个**参数（`reasoningLevel` 字符串、`maxOutputTokens` 数字），且**每次求值只允许一个输入变量**（`RestrictedCelValue = string | number`，`types.ts:8`）。厂商差异靠"每个（模型 × API 协议 × 站点）组合各写一条 map 字符串"来穷举，不是靠通用规则推导。
   > ⚠️ **注意作用域**：这只是 ZCode 参数处理的**其中一条轨道**。`temperature` / `topP` / `topK` / 惩罚项 / `stopSequences` / `seed` 走**另一条独立轨道**（`ModelRequestSettings` → `runner-options.ts:73-79` 直通透传，见 §4.5）。
2. **语言是自研的 "Restricted CEL"**——CEL（Common Expression Language）的裁剪子集：语法上具备 `?:`、`&&/||`、`==/!=`、`< <= > >=`、`+ - * / %`、`!`、数组/对象字面量，**但明确禁止成员访问（`.`）和函数调用**（`parser.ts:65-67`、`parser.ts:68-70`）。**内置 119 条 map 实际只用到其中一小部分**（详见 §2.5）。
3. **它的核心产物是"JSON 补丁"，不是"参数值"**：表达式求值必须返回一个 JSON object，该 object 被当作 **RFC 7386 JSON Merge Patch** 打到出站 HTTP 请求体上（`merge-patch.ts:63-78`）。这是整个设计最值得学的一点——**统一语义层收敛为「语义档位」，厂商方言在最后一跳（fetch 拦截器）才落地**。
4. **合并有冲突守卫**：多个 option map 若写入重叠 JSON 路径，直接抛错而不是"后者覆盖前者"（`merge-patch.ts:22-27`）。
5. **配置分层是 6 类规则 + 覆盖（overlay）语义**，优先级由数组顺序决定：`model`(正则) → `model-api` → `provider-site` → `template-model` → `provider-model`(精确)（`schema.ts:80-106` + `model-config.ts:387-423`）。
6. **DSL 在 schema 校验期就被编译**（`shared/model-config.ts:5-19`），语法错误 = 配置非法，写不进配置文件。
7. **真实规则库规模**：内置配置共 **478 条规则**、**119 条 map**，去重后 **21 种不同的 reasoningLevel 映射** + **4 种 maxOutputTokens 映射**；覆盖 3 种 API 协议 × 12 个站点。
8. **它不管的事（作用域须精确限定）**：**option map 机制**不做参数改名白名单、不做取值域钳制（`max` 只是 advisory，由调用方 `Math.min` 自行钳制，如 `auxiliary-model-options.ts:12`）、不管 tool_call 格式、不管缓存参数。至于 `temperature` / `topP` / 惩罚项 / `stop`——**它们不在 option map 内，但由第二条参数路径原样透传给 AI SDK**，并非"不管"，而是"不做厂商方言归一化"（见 §4.5 与 §14）。
   另需澄清：ZCode **确实存在**"能力降级"的两种形态——① 档位词表收缩（`values` 从 5 档收缩到 2 档，§6.2 类别 H-1）；② 模型硬禁用（`enabled: false`）。它**没有**的是"运行时按用户/负载动态协商降级"。
9. **参数处理是双轨制**：`option map 归一化轨`（2 个参数，走 DSL + merge patch）+ `直通透传轨`（其余参数，走 `ModelRequestSettings`）。只描述前者会把整个机制说小一半。

---

## 0.5 修订记录

> 本定稿由原草稿（`docs/research/drafts/03-zcode-模型参数处理机制.md`，1894 行）经独立核验后修订而成。
> 核验报告：`docs/research/drafts/verify-03-zcode.md`（577 行）。
> 核验共发现 **22 处错误**（其中 🔴 严重 6 处）、**4 处内部矛盾**、**5 处关键机制遗漏**；下表逐条列出修订情况。
> **原始草稿已保留在 `drafts/` 下作为留痕档案，未做任何修改。**

### 0.5.1 错误修正（E1–E22）

| 编号 | 位置 | 错误性质 | 修正要点 |
|---|---|---|---|
| **E1** 🔴 | §2.5 / §11.4 / §14 | **过度推断（核心结论依据失真）** | `100%` → **`≈96%`**（119 条中 5 条用到 `\|\|`/`&&`/`!=`/链式三元/`false`）；"3 个语义" → **"3 主语义 + 1 布尔谓词语义"**；**据比重写 §11.4 建议 2 的数据结构**——单一 `effort_words` dict 覆盖不了布尔谓词，补 `boolean_fields` |
| **E2** 🔴 | §6.2 | **遗漏** | 补 3 种未归类 map，**特别是 `zcode-builtin.json:2528` 的 openai-responses 全局兜底**；修正类别 C 表头"4 种"实为 **3 种**（第 3 行与类别 B 第 4 行是同一条 map）；给出完整算式 2+6+3+5+1+1+3 = 21 |
| **E3** 🔴 | §12.1 | **事实错误（硬数字编造）** | "全库 **144** 个测试文件中无相关测试" → 全库**仅 4 个**测试文件（`packages/{ui,services}/test/`），均与 `model-option-map` 无关 |
| **E4** 🔴 | §14 / §0 第 8 条 | **过度推断（未通读即下绝对断言）** | 绝对断言"它不管的：temperature / top_p / 惩罚项 / stop" → 限定作用域为"**option map 机制**不管"，并**补上第二条参数路径**（`ModelRequestSettings` → `runner-options.ts:73-79`）；同时**校准 §11.2 差距对照表**，把差距限定在 reasoning / maxOutputTokens 两个参数上 |
| **E5** 🔴 | §11.4 | **事实错误** | "它是 **MIT/自有许可**下的 866 行实现" → **Apache-2.0**（`LICENSE` 首行），并补合规提示（移植须保留 `LICENSE` 与 `NOTICE`，Apache-2.0 §4）；866 → **867** 行 |
| **E6** 🔴 | §13.7 | **行号偏差 + 事实错误** | 前 4 行行号 `6-31/33-96/98-120/122-…` → **`L7-29 / L29-75 / L76-97 / L98-145`**；"**23 个内置模型**" → **24**（`zai-standard-api.builtinModelIds.length = 24`） |
| **E7** | §10.1 阶段 1 | 行号偏差 | `config.validateComplete(path)   model-config.ts:122` → **`model-config.ts:324`**（L122 是 `Object.assign(this, input);`） |
| **E8** | §8.2 / §8.3 / §9.1 / §10.1 / §13.4 | 行号偏差（7 处） | `11`→`10`；`26-34`→`25-36`；`:28`→`:27`；`:31`→`:39`；`:38`→`:40`；`36-58`→`38-57`；`60-77`→`59-71` |
| **E9** | §12.3 / §13.4 | 行号偏差（3 处） | `13-60`→`13-72`；`24`→`18`（L24 是 `personal &&`）；`58-59`→`71`；renames 的 import 在 L8、使用在 L38-41 与 L51 |
| **E10** | §9.1 / §9.2 / §13.3 | 行号偏差（4 处） | `:37`→**L32 / L43**；`70-73`→**L55-62**；`76-88`→**L64-80**；`90-106`→**L83-99** |
| **E11** | §13.2 | 行号偏差（2 处） | `30-37`→**`34-40`**；`40-56`→**`43-60`** |
| **E12** | §7.1 标题 | 自相矛盾（笔误） | "36 行，仅 **5 个**实体" → **9 个**（标题与紧随其后的 9 个实体列表不符） |
| **E13** | §2.5 | 计数错误 | 一元 `!` 计数 **1 → 0**（字符级 `!` 共 2 处，全部来自 `!=`） |
| **E14** | §6.2 类别 B 首行 | **无源引入 + 泛化** | 删除无源的 "**Grok**"（全仓配置 0 命中）；`values=["low","high","max"]` → "**values 因站点而异**（`["max"]` / `["high","max"]` / `["none","high"]` / `["none","low","high"]` / 不声明）" |
| **E15** | §6.2 类别 C | 措辞失准 | "GLM-5/5.1/4.7 等 **27 个模型**" → "**27 条规则**（含重复 `modelMatch`），覆盖 glm / qwen / mimo / kimi 四族" |
| **E16** | §7.3 第 4 条 | 过度推断 | "`JsonObject` 是 `readonly` + `Object.create(null)`：**不可变** + 无原型" → "**求值结果深度冻结**；merge-patch 输出无原型但**未冻结**（`cloneJson` 用 `configurable/writable: true`）" |
| **E17** | §5.3 | **句内矛盾** | 删掉"不能改 map"，改为"**不能改 `maxOutputTokens.map`**"（`manual-model-config.ts:24` 的 `pick({reasoningLevel: true})` 允许用户改 reasoningLevel 的整个 map） |
| **E18** | §10.2 第 2 条 | 绝对化 | "fail-closed 而非 fail-open" → "对『**有 body 但非文本**』fail-closed；对『**取不到 body 文本**』（`model-option-map-fetch.ts:21`）仍会**静默透传**" |
| **E19** | §13.5 | 行号偏差 | `runner.ts \| 161-162 \| 推理遥测（requestedLevel）` → **`197-209`**（`requestedLevel` 实际写在 L205） |
| **E20** | §7.2 图注 | 行号偏差 | `compiler.ts:16/35` → **`types.ts:11-19`**（`compiler.ts:16` 是空行，`:35` 是 `compileModelOptionMap` 函数） |
| **E21** | §0 第 4 行 / §13.1 / §14 | 计数错误 | "8 个文件，共 **866** 行" → **867**（`wc -l packages/model-option-map/src/*.ts` = 867） |
| **E22** | §13.7 | 行号偏差 | `2561-2569 \| .*glm-5 @ anthropic` → **`2560-2569`**（起点偏 1） |

### 0.5.2 内部矛盾修正（M1–M4）

| 编号 | 矛盾点 | 处理 |
|---|---|---|
| **M1** | §2.5 表列出 `\|\|`=2、`!=`=1、`&&`=1，§11.4 表却称"只用 `==` = 100%" | **已随 E1 / E13 消解**：§11.4 改为 `≈96%`，并列出 5 条"非纯 `==`"map |
| **M2** | §12.6 自认"未通读、不排除 temperature 走 `runner-options.ts`"，§14 却下绝对断言 | **已随 E4 消解**：§14 限定作用域；§12.6 该条移入正文 §4.5 |
| **M3** | §5.3 "不能改 map" vs 同节"用户可改 reasoningLevel（整个，含 values + map）" | **已随 E17 消解**：统一为"不可改的只有 `maxOutputTokens.map`" |
| **M4** | §0 第 8 条"不做能力降级协商（只有 `enabled: false` 硬禁用）" vs §6.2 类别 F 承认的"档位词表收缩" | **已消解**：§0 第 8 条改为明确列出两种降级形态（词表收缩 + 硬禁用），并说明"没有的是运行时动态协商" |

### 0.5.3 关键机制补充（M5–M9）

| 编号 | 遗漏内容 | 补充位置 |
|---|---|---|
| **M5** 🔴 | ZCode 的**第二条参数路径**：`ModelRequestSettings`（`contracts/src/model/index.ts:625-631`）→ `runner-options.ts:73-79` 逐字段透传 `temperature`/`topP`/`topK`/`presencePenalty`/`frequencyPenalty`/`stopSequences`/`seed`；`runner-debug.ts:127/236/294` 调试链路同样携带 | 新增 **§4.5**；并据此校准 **§11.2** |
| **M6** | `resolver.ts:264-270` 的**二次 resolve**（同一 `(provider, model, apiType, baseUrl)` 解析两次：一次用"内置 + 个人精确规则"，一次**只用内置规则**），两者并存发布给 UI（`resolver.ts:285-286`） | 新增 **§5.4**（同时回答草稿 §12.5 悬置的"手动规则只改 `enabled` 时系统映射是否保留"——答案是**保留**） |
| **M7** | **远端配置同步 / 回落机制**：`zcode-builtin-remote-synchronizer.ts` 的六态结果、lease 租约、`nextEligibleAt` 退避、跳过原因；`endpoint-scoped-zcode-builtin-source.ts`、`zcode-builtin-download.ts`、`zcode-builtin-cache-paths.ts` | 新增 **§8.4**（并回答 §8.3"坏配置回退到哪一份"） |
| **M8** | `packages/provider/src/sources.ts`（`ProviderConfigSnapshot`，规则的实际来源容器）与 `facades.ts`（Settings/Selection 的 Registry 投影与写入边界）——L1→L2 之间的上游层 | 新增 **§8.2.1**，补进调用图 |
| **M9** | `legacyReasoningLevelRenames` 的**真实机制被说反了一半**：不是"`off`/`nothink` → `disabled` 的直接映射表"，而是"**把当前规则集回滚成历史值域、再用同一引擎判定旧值是否曾合法**" | **重写 §11.3 第 4 条**；并把 §12.3 从"未验证"移入正文 **§11.3.1** |

### 0.5.4 修订过程中的独立抽查

核验报告给出的行号在本次修订中**已用脚本与源码逐条复核**，结论一致。仅一处需说明：

- 核验报告 E10 给出 `providerApiDataSchema / completeProviderApiDataSchema` 的真实范围为 **L64-80**；实测这两个 schema 本身位于 **L64-76**，L78-80 是同文件的 `personalProviderApiDataSchema`。本定稿沿用核验报告的 **L64-80**（该范围完整包含所引用的两个 schema）。**不属于核验报告错误，仅为边界宽窄差异。**

其余 21 条错误、4 处矛盾、5 处遗漏的修正依据均与核验报告一致，无新增分歧。

---

## 1. 机制定位与总览

### 1.1 它到底解决什么问题

**问题**：同一个模型（如 DeepSeek-V4-Pro）经不同厂商/网关接入时，"思考强度"这个**语义**的**线格式**完全不同：

| 接入方 | 协议 | 实际字段 |
|---|---|---|
| 智谱 Z.AI | anthropic-messages | `thinking.type` + `output_config.effort` |
| DeepSeek 官方 | openai-responses | `reasoning.effort`（关闭用 `"none"`） |
| OpenRouter | openai-chat-completions | `reasoning.enabled` / `reasoning.effort` |
| Kimi K3 | openai-chat-completions | `reasoning_effort`（档位只有 low/high/max） |
| Qwen | openai-chat-completions | `enable_thinking`（布尔） |

ZCode 的解法：**上游（UI/业务）永远只说「语义档位」**（`reasoningLevel: "disabled" | "enabled" | "low" | "high" | "max" | ...`），**下游线格式由数据驱动的 map 表达式在 HTTP 出站前一刻生成**。

### 1.2 四层架构（自顶向下）

```
┌──────────────────────────────────────────────────────────────────────┐
│ L1 数据层  config/provider/zcode-builtin.json                        │
│    5 类模型规则 + 2 类厂商规则；规则内嵌 optionSpecs.{reasoningLevel, │
│    maxOutputTokens}.{values,max,map}                                 │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ parseZCodeBuiltinModelConfigRules (schema.ts:78)
                            │   └─ zod 校验 + map 字符串编译校验
                            ▼
┌──────────────────────────────────────────────────────────────────────┐
│ L2 配置层  packages/provider/src/config/*.ts                         │
│    ModelConfigRules.resolve(providerId, modelId, apiType, baseUrl)   │
│      → 按数组顺序 overlay 出「某个模型在该站点该协议下的完整配置」    │
│      → ModelConfig{ enabled, properties, optionSpecs }               │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ ProviderConfigResolver.resolve (resolver.ts:183)
                            ▼
┌──────────────────────────────────────────────────────────────────────┐
│ L3 Registry  packages/provider/src/registry.ts                       │
│    ProviderRegistry：发布 (providerId, modelId) → RegistryModelConfig │
│    + validateModelSelectionOptions 校验用户档位是否在 values 内       │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ AiSdkModelAdapter.createModel (runner.ts:138)
                            ▼
┌──────────────────────────────────────────────────────────────────────┐
│ L4 运行时  packages/model-option-map/src/*.ts                        │
│    compileModelOptionMaps(optionSpecs)   ← Model 创建时编译一次       │
│      reasoningLevel.map  →  Program (缓存)                           │
│      maxOutputTokens.map →  Program (缓存)                           │
│    请求期: program.evaluate(value) → patch → merge 进 request body   │
│    注入点: fetch 拦截器 createModelOptionMapFetch                     │
└──────────────────────────────────────────────────────────────────────┘
```

> **这张图只覆盖 option map 归一化轨（2 个参数）。** ZCode 另有一条与之**平行的**参数路径（`ModelRequestSettings` 直通透传，覆盖 `temperature`/`topP`/惩罚项/`stopSequences`/`seed`），它**不经过 L4**，直接进 AI SDK 的 `streamText/generateText` 参数对象。详见 §4.5。

### 1.3 一句话定性

> `model-option-map` = **受限 CEL 求值器**（parser/tokenizer/evaluator）
> + **有序 JSON Merge Patch 应用器**（merge-patch）
> + **两个 option 的编排器**（option-maps）
> = 一个**声明式、数据驱动、单变量、出站前补丁**的**窄域规则引擎**。

它**不是**：通用参数映射器、能力协商引擎、请求路由层、或网关。它是 ZCode 内部的一个 private 包（`package.json: "private": true`），唯一导出路径是 `./src/index.ts`。

---

## 2. 语法：Restricted CEL 详解

### 2.1 词法（`tokenizer.ts`）

**Token 种类**（`tokenizer.ts:3-9`）：`identifier | string | number | operator | punctuation | eof`

**运算符集合**（硬编码白名单，`tokenizer.ts:18-20`）：

```ts
const DOUBLE_OPERATORS = new Set(["&&", "||", "==", "!=", "<=", ">="]);
const SINGLE_OPERATORS = new Set(["+", "-", "*", "/", "%", "!", "<", ">"]);
const PUNCTUATION = new Set(["{", "}", "[", "]", "(", ")", ",", ":", "?", "."]);
```

注意 `.` **在 punctuation 集合里**——它能被词法切出来，但在语法层被显式拒绝（见 2.3）。这是"给出精确错误信息"而非"词法直接报错"的设计。

**字面量**：
- 字符串：单引号 `'` 或双引号 `"` 均可（`tokenizer.ts:32`），支持转义 `\' \" \\ \b \f \n \r \t` 与 `\uXXXX`（`tokenizer.ts:126-135`、`tokenizer.ts:112-120`），**字符串内不允许裸换行**（`tokenizer.ts:91-93`）。
- 数字：正则 `^(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?`（`tokenizer.ts:76`）——即无前导零、可选小数、可选科学计数法。
- 标识符：`[A-Za-z_][A-Za-z0-9_]*`（`tokenizer.ts:46-47`）。

### 2.2 语法（`parser.ts`）——递归下降，优先级从低到高

`parser.ts:79-110` 定义了完整优先级链：

```
parseConditional      ? :          (右结合, parser.ts:79-86)
  └ parseLogicalOr    ||
      └ parseLogicalAnd   &&
          └ parseEquality     == !=
              └ parseRelational   < <= > >=
                  └ parseAdditive     + -
                      └ parseMultiplicative  * / %
                          └ parseUnary       ! - +
                              └ parsePrimary 字面量/变量/()/[]/{}
```

AST 节点类型（`parser.ts:4-44`）共 7 种：
`literal` | `input` | `array` | `object` | `unary` | `binary` | `conditional`

### 2.3 刻意禁止的能力（安全边界）

| 禁止项 | 位置 | 错误信息 |
|---|---|---|
| 成员访问 `a.b` | `parser.ts:65-67` | `member access is not supported` |
| 函数调用 `f(x)` | `parser.ts:68-70`、`parser.ts:159-161` | `function calls are not supported` |
| 未知标识符 | `parser.ts:167-170` | `unknown identifier "foo"` |
| 对象 key 非字符串字面量 | `parser.ts:198-200` | `object keys must be string literals` |
| 对象重复 key | `parser.ts:201-206` | `duplicate object key "x"` |
| 非 JSON-safe 数字 | `parser.ts:151-153` | `number literal is not JSON-safe` |

**唯一允许的标识符**：`true` / `false` / `null` / **该 map 声明的那一个变量名**（`parser.ts:162`、`parser.ts:163-166`）。

```ts
// parser.ts:162
if (token.value === this.variableName) return { type: "input", offset: token.offset };
```

`variableName` 由 `compileModelOptionMap(source, variableName)` 传入，只可能是 `"reasoningLevel"` 或 `"maxOutputTokens"`（`types.ts:9`）。

### 2.4 真实语法示例（全部来自内置配置）

**例 1：最简——参数改名（键名映射）**
`config/provider/zcode-builtin.json:2503`
```
{'max_tokens': maxOutputTokens}
```
> 语义：把统一的 `maxOutputTokens` 写成 Anthropic 方言的 `max_tokens`。单引号 key 也被支持。

**例 2：档位→枚举转换（`values` 只有 low/high/max 时直接透传）**
`config/provider/zcode-builtin.json:2555`
```
{"reasoning_effort": reasoningLevel}
```

**例 3：条件三元 + 嵌套对象（覆盖三种字段形态）**
`config/provider/zcode-builtin.json:2514`（openai-chat-completions 兜底规则）
```
{
  "thinking": {
    "type": reasoningLevel == "disabled" || reasoningLevel == "none" ? "disabled" : "enabled"
  },
  "enable_thinking": reasoningLevel != "disabled" && reasoningLevel != "none",
  "reasoning_effort": reasoningLevel == "disabled" ? "none" : reasoningLevel == "enabled" ? "high" : reasoningLevel,
  "reasoning": {
    "effort": reasoningLevel == "disabled" ? "none" : reasoningLevel == "enabled" ? "high" : reasoningLevel
  }
}
```
> 语义：**一次写入 4 个字段**，兼容 Qwen 的 `enable_thinking`、部分网关的 `thinking`、以及 `reasoning_effort` / `reasoning.effort` 两种命名。这是"同一个语义档位，用多个厂商方言同时表达"的典型手法——让下游网关自己挑认得的那一个。
> **语法上这条 map 同时用到了 `||`、两个 `!=`、`&&`、两个链式三元**——是内置配置中表达力最强的一条，也是"只用 `==` + 三元"这一归纳的主要反例（见 §2.5 与 §11.4）。

**例 4：分支返回不同对象形状（顶层三元）**
`config/provider/zcode-builtin.json:2500`（anthropic-messages 兜底规则）
```
reasoningLevel == "disabled"
  ? {
      "thinking": {
        "type": "disabled"
      }
    }
  : {
      "thinking": {
        "type": "adaptive"
      },
      "output_config": {
        "effort": reasoningLevel == "enabled" ? "high" : reasoningLevel
      }
    }
```
> 语义：关闭时**只发 `thinking.type=disabled`**（不发 effort，避免厂商报"disabled 必须配 effort=none"）；开启时才发 `output_config.effort`，且把语义档位 `enabled` 翻译成厂商词表里的 `high`。

**例 5：空对象 = 不注入任何字段**
`config/provider/zcode-builtin.json:894`（`modelRules` 兜底规则）
```
{}
```
> 语义：`collectWrittenPaths({})` 返回空数组（`merge-patch.ts:40-47`），既不写字段也不占路径，等价于"这个模型的 reasoning 完全交给 SDK / 厂商默认处理"。默认规则用它，避免对未知模型乱注入。

**例 6：`null` 删除字段**
语法上支持（`parser.ts:166` 允许 `null` 字面量，`merge-patch.ts:66-69` 对 `null` 执行 `delete`），但**内置 119 条 map 中零使用**（已用脚本全量扫描确认）。属于保留能力。

### 2.5 实际特性使用率（对 119 条内置 map 全量扫描）

> 统计口径：按**含 map 的规则条数**计（119 条 = 101 条 reasoningLevel + 18 条 maxOutputTokens）。

| 特性 | 出现次数 |
|---|---|
| `==` | 57 |
| `?:` 三元 | 50 |
| 空对象 `{}` | 8 |
| **链式三元（≥2 个 `?`）** | **4** |
| `\|\|` | 2 |
| `!=` | 1 |
| `&&` | 1 |
| **`false` 布尔字面量** | **1** |
| 一元 `!` | **0** |
| 数组字面量 `[...]` | **0** |
| 算术 `+ - * / %`、比较 `< > <= >=`、`null` | **0** |

> **修订说明（E13 / E1）**：
> ① 一元 `!` 的计数由 `1` 改为 **`0`**——原草稿把 `!=` 中的 `!` 字符误计为一元运算符。字符级 `!` 全库共 2 处，**全部来自 `:2514` 的两个 `!=`**。
> ② 补列了原草稿漏统计的 **链式三元（4 条）** 与 **`false` 布尔字面量（1 条）**。

**结论（已修正）**：真实世界用到的 CEL 子集是"**对象字面量 + 三元 + 等值比较**"为主体，**但有 5 条 map（占 119 条的 4.2%）越出了这个子集**，用到了 `||` / `&&` / `!=` / 链式三元 / `false` 字面量。因此正确的表述是 **`≈96%` 的 map 只用"对象字面量 + 三元 + `==`"，而非 100%**。

数组与算术是完全未被使用的预留能力。这一点对我们是否要引入 DSL 的决策极其关键（见第 11 节），但**必须连带那 5 条例外一起看**——正是这 5 条决定了"纯表格"能否完全覆盖。

---

## 3. 编译：把什么编译成什么

### 3.1 编译目标：闭包（不是字节码、不是 AST 解释）

`compiler.ts:17-33`：

```ts
export function compileRestrictedCel(
  source: string,
  variableName: ModelOptionName,
): RestrictedCelProgram {
  const normalizedSource = normalizeSource(source);
  const cacheKey = createCacheKey(normalizedSource, variableName);
  const cached = programCache.get(cacheKey);
  if (cached) return cached;

  const expression = parseExpression(normalizedSource, variableName);
  const program: RestrictedCelProgram = Object.freeze({
    source: normalizedSource,
    evaluate: (input: RestrictedCelValue) => evaluateRestrictedCel(expression, input),
  });
  programCache.set(cacheKey, program);
  return program;
}
```

**"编译" = `tokenize → parse → 闭包捕获 AST`**。产物是一个 `{ source, evaluate }` 的冻结对象。求值时直接走 AST 递归（`evaluator.ts:17-50`），**没有做 AST→JS 代码生成、没有做常量折叠、没有做类型检查**。

### 3.2 为什么叫"编译"：三个目的

| 目的 | 证据 |
|---|---|
| **① 提前暴露语法错误**（fail-fast） | `assertObjectResultExpression`（`compiler.ts:80-88`）在编译期就递归检查"最终结果必须是 JSON object"，且**只在 `conditional` 的两支里递归**，因此 `a ? {} : 1` 这种在编译期就被拒。 |
| **② 缓存**（性能） | 三级缓存：`programCache`（`compiler.ts:13`）、`optionMapCache`（`compiler.ts:14`）、`expressionCache`（`compiler.ts:15`）。cache key = `` `${variableName}\0${source}` ``（`compiler.ts:76-78`）——用 `\0` 分隔避免变量名与表达式拼接歧义。 |
| **③ 结果形状契约**（运行时兜底） | `compileModelOptionMap` 的 `evaluate` 里还有一层运行时检查（`compiler.ts:49-52`）：结果不是 object 就抛 `model option map must return a JSON object`。 |

`assertObjectResultExpression` 的实现值得完整引用（`compiler.ts:80-88`）：

```ts
function assertObjectResultExpression(expression: RestrictedCelExpression): void {
  if (expression.type === "object") return;
  if (expression.type === "conditional") {
    assertObjectResultExpression(expression.whenTrue);
    assertObjectResultExpression(expression.whenFalse);
    return;
  }
  throw new RestrictedCelError("model option map must return a JSON object", expression.offset);
}
```

> 注意它**不递归进数组/一元/二元表达式**——所以 `(1+1) ? {} : {}` 这种"条件本身不是布尔"的错误要到**求值期**才暴露。这是编译期校验的一个已知窄口。

### 3.3 编译时机：**两次**，且都在请求之前

**第一次（配置校验期）**：`packages/shared/src/model-config.ts:5-19`

```ts
function optionMapSchema(variableName: "reasoningLevel" | "maxOutputTokens") {
  return z
    .string()
    .min(1)
    .superRefine((source, context) => {
      try {
        compileModelOptionMap(source, variableName);
      } catch (error) {
        context.addIssue({
          code: "custom",
          message: error instanceof Error ? error.message : "Option Map 无法编译",
        });
      }
    });
}
```

> **这是全链路最优雅的一点**：`map` 字段在 zod schema 里就是 `.string().superRefine(能编译通过)`。也就是说 —— **配置文件里不可能存在语法错误的 map**，因为 schema 校验会直接把它标为 `invalid-option-spec`（`schema-validation.ts:32-34`）。DSL 语法错误被提升为"配置数据错误"，与"JSON 少个字段"同级。

**第二次（Model 创建期）**：`apps/zcode-cli/packages/adapters/src/model/model-execution.ts:186-193`

```ts
bindModel(input: {...}): AiSdkBoundModelResolution {
  const snapshot = this.captureModelSnapshot(input);
  const optionMaps = compileModelOptionMaps(input.optionSpecs);   // ← 编译一次
  return {
    resolved: this.resolveSnapshot(snapshot, undefined, undefined, undefined),
    resolveRequest: ({ options, requestAuth }) =>
      this.resolveSnapshot(snapshot, requestAuth, optionMaps, options),
  };
}
```

注释也明说了设计意图（`option-maps.ts:19`）：
> `/** Model 创建时编译一次；每个请求只绑定本轮冻结的 Option value。 */`

即：**编译开销只在创建 Model 时付一次；请求期只做 AST 求值**。

---

## 4. 求值：模型与上下文

### 4.1 求值模型：纯函数，单输入，无环境

`evaluator.ts:9-15`：

```ts
export function evaluateRestrictedCel(
  expression: RestrictedCelExpression,
  input: RestrictedCelValue,
): JsonValue {
  assertRestrictedCelValue(input, expression.offset);
  return freezeJson(evaluate(expression, input));
}
```

**输入上下文的全部内容就是一个标量**（`evaluator.ts:168-178`）：

```ts
function assertRestrictedCelValue(
  value: unknown,
  offset: number,
): asserts value is RestrictedCelValue {
  if (typeof value === "string") return;
  if (typeof value === "number") {
    assertNumber(value, offset);
    return;
  }
  throw new RestrictedCelError("input value must be a string or number", offset);
}
```

配合 `types.ts:8`：`export type RestrictedCelValue = string | number;`

### 4.2 可用变量清单（这是最重要的发现）

**没有"上下文对象"**。没有 `model.id`、没有 `provider.name`、没有 `api.type`、没有能力位、没有用户设置——**这些全部在配置解析期（L2）就已经被"匹配"掉了**，到了求值期（L4）只剩一个变量。

| 求值期可用的名字 | 类型 | 来源 |
|---|---|---|
| `reasoningLevel` | `string` | 用户在 `ModelSelection.options.reasoningLevel` 里的选择 |
| `maxOutputTokens` | `number` | 调用方传入的 `ModelOptions.maxOutputTokens` |
| `true` / `false` / `null` | 字面量 | `parser.ts:163-166` |

"厂商/模型/协议/站点"这些维度**不是求值期变量，而是配置期规则匹配条件**（`modelMatch` / `apiTypeMatch` / `baseUrlMatch` / `templateId` / `providerId`），在 `ModelConfigRules.resolve` 里完成（`model-config.ts:387-423`）。

> **架构含义**：ZCode 用"**配置期正交组合爆炸（穷举规则）**"换取"**求值期极简（单标量）**"。119 条 map 就是这个策略的代价——规则的重复度极高（`{"reasoning_effort": reasoningLevel}` 一条就重复了 17 次）。

### 4.3 求值语义细节

- **`&&` / `||` 短路**（`evaluator.ts:63-72`）：
  ```ts
  if (expression.operator === "&&") {
    return requireBoolean(left, expression.left.offset)
      ? requireBoolean(evaluate(expression.right, input), expression.right.offset)
      : false;
  }
  ```
- **`+` 是重载的**（`evaluator.ts:80-85`）：两边都是 string → 字符串拼接；否则两边都必须是 number。**没有隐式类型转换**。
- **比较要求同类型**（`evaluator.ts:122-128`）：`comparison operands must have the same numeric or string type`。
- **`==` 是 JSON 深比较**（`evaluator.ts:180-199`），先 `Object.is`，再递归数组/对象。**因此 `1 == "1"` 为 false**（不同 `typeof`）。
- **数字全程 JSON-safe 守卫**（`evaluator.ts:161-166`）：非有限数、或整数但非 safe integer → 抛错。防止 `1e400`、`2^53` 之类悄悄进到请求体。
- **结果是深度冻结的**（`evaluator.ts:14`、`evaluator.ts:201-210`）：`freezeJson` 递归 `Object.freeze`，且对象用 `Object.create(null)` 创建（`evaluator.ts:26`）——**防原型污染**（`__proto__` 作为 key 不会污染原型链）。

### 4.4 求值结果 → 最终请求参数

这是全链路的关键跃迁：**求值结果不是"参数值"，而是"请求体补丁"**。

`option-maps.ts:20-34`：

```ts
export function compileModelOptionMaps(specs: ModelOptionMapSpecs): CompiledModelOptionMaps {
  const reasoningLevel = compileModelOptionMap(specs.reasoningLevel.map, "reasoningLevel");
  const maxOutputTokens = compileModelOptionMap(specs.maxOutputTokens.map, "maxOutputTokens");
  return Object.freeze({
    apply(body: JsonObject, values: ModelOptionValues): JsonObject {
      const patches: NamedJsonMergePatch[] = [];
      if (values.reasoningLevel === undefined) {
        throw new ModelOptionMapError("reasoningLevel requires an effective value");
      }
      patches.push(optionPatch("reasoningLevel", reasoningLevel, values.reasoningLevel));
      patches.push(optionPatch("maxOutputTokens", maxOutputTokens, values.maxOutputTokens));
      return applyOrderedJsonMergePatches(body, patches);
    },
  });
}
```

注意 `option-maps.ts:26-28`：**`reasoningLevel` 缺失是硬错误**（fail-closed），不是"跳过"。这与 `registry.ts:140-147` 的 `reasoning-level-missing` 校验形成双保险。

### 4.5 【本次新增 M5】第二条参数路径：`ModelRequestSettings` 直通透传

> **这是原草稿全文缺失、但与本报告标题直接相关的一处机制。** 补上它才能正确回答"ZCode 有没有一套完整的模型参数处理机制"。

**option map 机制之外，ZCode 还有一条与之平行的参数路径**：调用方（CLI / 工具 / 上层业务）在 `ModelRequestSettings` 上声明的采样与惩罚类参数，会被**逐字段原样透传**给 AI SDK，**不经过 option map、不做任何厂商方言归一化**。

**证据链**：

| 证据 | 内容 |
|---|---|
| `apps/zcode-cli/packages/contracts/src/model/index.ts:625-631` | `export interface ModelRequestSettings { temperature?: number; maxOutputTokens?: number; topP?: number; topK?: number; presencePenalty?: number; frequencyPenalty?: number; stopSequences?: string[]; seed?: number; }` |
| `apps/zcode-cli/packages/adapters/src/model/runner-options.ts:73-79` | 逐字段透传：`temperature: input.request.temperature, topP: ..., topK: ..., presencePenalty: ..., frequencyPenalty: ..., stopSequences: ..., seed: ...` |
| `apps/zcode-cli/packages/adapters/src/model/runner-debug.ts:127 / :236 / :294` | 调试/遥测链路同样携带 `temperature` |
| `apps/zcode-cli/packages/contracts/src/model/index.ts:976` | `ModelRequest` 的 JSON Schema 含 `temperature` / `topP` / `topK` / `presencePenalty` |

**两条轨道的对照**：

| 维度 | option map 归一化轨 | 直通透传轨 |
|---|---|---|
| 覆盖参数 | `reasoningLevel`、`maxOutputTokens` | `temperature`、`topP`、`topK`、`presencePenalty`、`frequencyPenalty`、`stopSequences`、`seed` |
| 载体 | `optionSpecs.{...}.map`（配置数据） | `ModelRequestSettings`（请求对象字段） |
| 处理方式 | 编译成 Program → 求值 → JSON Merge Patch → fetch 拦截器改写 body | `runner-options.ts` 里 `key: input.request.key` 直接赋值给 AI SDK 参数对象 |
| 厂商方言归一化 | **有**（这是它的全部价值） | **无**——不同厂商是否支持、字段名如何，完全交给 AI SDK 与厂商 |
| 与协议/SDK 解耦 | 解耦（fetch 层） | 耦合（AI SDK 参数层） |
| 能否表达"关闭时不发某字段" | 能（条件分支改变字段集合） | 不能（字段有值就发，无值就不发） |

> **对网关评估的意义**：直通透传轨的行为与我们网关的 `apply_model_params`（`model_gateway/core/ir.py:58-70`）**完全同级**——都是"字段有值就写进 body、没有就不写"的 `body[k] = v` 式写入。因此**ZCode 的参数层并非整体强于我们**；真正的差异只集中在 `reasoningLevel` / `maxOutputTokens` 这两个参数上（见 §11.2 的校准说明）。

---

## 5. 合并语义（`merge-patch.ts`）

### 5.1 是不是 RFC 7386？

**核心算法是 RFC 7386 JSON Merge Patch 的忠实实现，但外面套了一层非标准的"冲突守卫"。**

`merge-patch.ts:63-78`：

```ts
function mergeObject(target: JsonObject, patch: JsonObject): JsonObject {
  const result = cloneJson(target) as Record<string, JsonValue>;
  for (const [key, patchValue] of Object.entries(patch)) {
    if (patchValue === null) {
      delete result[key];          // ← RFC 7386: null 删除
      continue;
    }
    if (isJsonObject(patchValue)) {
      const targetValue = result[key];
      result[key] = mergeObject(isJsonObject(targetValue) ? targetValue : {}, patchValue);  // ← 递归
      continue;
    }
    result[key] = cloneJson(patchValue);   // ← 标量/数组整体替换
  }
  return result;
}
```

对照 RFC 7386 三条规则：
| RFC 7386 规则 | 实现 | 证据 |
|---|---|---|
| patch 值非 null 对象 → 递归 merge | ✅ | `merge-patch.ts:70-74` |
| patch 值 `null` → 删除 target 中的键 | ✅ | `merge-patch.ts:66-69` |
| patch 值其他（标量/数组）→ 整体替换 | ✅ | `merge-patch.ts:75`、数组由 `cloneJson` 整体拷贝（`merge-patch.ts:81`） |

**扩展 1（关键）**：**跨 patch 的路径冲突检测**。`merge-patch.ts:13-33`：

```ts
export function applyOrderedJsonMergePatches(
  body: JsonObject,
  patches: readonly NamedJsonMergePatch[],
): JsonObject {
  const ownedPaths: OwnedPath[] = [];
  let result = cloneJson(body) as JsonObject;
  for (const namedPatch of patches) {
    const paths = collectWrittenPaths(namedPatch.patch);
    for (const path of paths) {
      const conflict = ownedPaths.find((owned) => pathsOverlap(owned.path, path));
      if (conflict) {
        throw new ModelOptionMapError(
          `Model option maps write conflicting JSON path ${formatPath(path)}: ${conflict.option} and ${namedPatch.option}`,
        );
      }
      ownedPaths.push({ option: namedPatch.option, path });
    }
    result = mergeObject(result, namedPatch.patch);
  }
  return result;
}
```

`pathsOverlap` 判定的是**前缀关系**（`merge-patch.ts:51-57`）：

```ts
function pathsOverlap(left: readonly string[], right: readonly string[]): boolean {
  const sharedLength = Math.min(left.length, right.length);
  for (let index = 0; index < sharedLength; index += 1) {
    if (left[index] !== right[index]) return false;
  }
  return true;
}
```

即 `$.a.b` 与 `$.a` 算冲突，`$.a.b` 与 `$.a.c` 不算。

**扩展 2**：`collectWrittenPaths` 对**非空对象**继续下钻，对**空对象**视为叶子（`merge-patch.ts:42`：`Object.keys(value).length > 0`）。这是让 `map: "{}"` 能安全地"什么都不写"的关键。

### 5.2 冲突语义：**抛错，不是 last-write-wins**

> 这是 ZCode 一个非常"较真"的选择。两个 option map 若都想写 `max_tokens`，**整个请求直接失败**，而不是悄悄让后者覆盖前者。

为什么合理：`reasoningLevel` 与 `maxOutputTokens` 是**语义正交**的两个 option。如果它们写到了同一个 JSON 路径，说明**配置写错了**（例如 maxOutputTokens 的 map 被误写成 `{"thinking": {...}}`），此时静默覆盖会产出难以排查的错误请求。抛错 = 配置 bug 立刻暴露。

> ⚠️ **标注（设计意图推断，源码未注释）**：上述"为什么合理"的论证是对**设计动机**的合理推断，源码中没有对应注释。事实部分（抛错行为、前缀判定）有逐行证据；动机部分属推断。

### 5.3 优先级顺序：**不是"默认→厂商→模型→用户"**

这里必须纠正一个常见误解。ZCode 有**两条独立的优先级链**，且**不包含"用户参数覆盖厂商参数"这层**：

**链 A：配置合成（决定用哪个 map / 哪些 values）**

`model-config.ts:379-381`：

```ts
/** Built-in 保留原层次和组内顺序；个人只包含普通/手动精确规则。 */
static composeEffective(builtin: ModelConfigRules, personal: ModelConfigRules): ModelConfigRules {
  return new ModelConfigRules([...builtin.rules(), ...personal.rules().filter(isExactModelRule)]);
}
```

`model-config.ts:387-423`（`resolve` 主循环）——**数组顺序即优先级，后者 overlay 前者**：

```
低优先级 ────────────────────────────────────────────────────► 高优先级

  ① type="model"            modelMatch 正则匹配模型 ID
  ② type="model-api"        ① + apiTypeMatch 正则
  ③ type="provider-site"    ② + baseUrlMatch 正则
  ④ type="template-model"   templateId + modelId 精确
  ⑤ type="provider-model"   providerId + modelId 精确（内置）
  ⑥ type="manual-provider-model"  同上但来自用户手写（个人层，最高）
```

顺序由 `schema.ts:80-106` 的数组构造顺序固化：

```ts
return new ModelConfigRules([
  ...parsed.modelRules.map(... type: "model" ...),          // ①
  ...parsed.modelApiRules.map(... type: "model-api" ...),    // ②
  ...parsed.providerSiteRules.map(... type: "provider-site" ...), // ③
  ...parsed.templateModelRules.map(... type: "template-model" ...), // ④
  ...parsed.builtinProviderModelRules.map(... type:"provider-model" ...), // ⑤
]);
```

加上个人层（`composeEffective` 拼在后面）得到 ⑥。**这是一个"从泛到专"的排序**，越具体的规则越晚应用、越能覆盖。

**链 B：overlay 的字段级语义**

`config-overlay.ts:21-38` 定义了唯一的覆盖基类：

```ts
export abstract class ConfigOverlay<TSelf extends ConfigOverlay<TSelf>> {
  protected overlayValue<T>(base: T | undefined, next: T | undefined): T | undefined {
    return next === undefined ? base : next;      // 标量：next 有值就赢，undefined 视为"不表态"
  }

  protected overlayConfig<T extends ConfigOverlay<T>>(
    base: T | null | undefined,
    next: T | null | undefined,
  ): T | null | undefined {
    if (next === undefined) return base;          // 子配置：undefined = 继承
    if (next === null || base === null || base === undefined) return next;  // null = 整体重置
    return base.overlay(next);                    // 否则递归覆盖
  }
}
```

**三态语义**（这是设计精髓）：
- `undefined`（字段不存在）= **继承下层**
- `null` = **整体替换/重置**（不走递归合并）
- 有值 = **覆盖**

对应到 zod schema，靠 `sparseShape` 实现（`packages/shared/src/config-schema.ts:4-8`）：

```ts
export function sparseShape<T extends Record<string, z.ZodType>>(shape: T) {
  return Object.fromEntries(
    Object.entries(shape).map(([key, schema]) => [key, schema.nullable().optional()]),
  ) as { [K in keyof T]: z.ZodOptional<z.ZodNullable<T[K]>> };
}
```

> 即：**同一份字段定义生成两个 schema**——`complete*`（全部必填，用于"完整性证明"）与稀疏版（全部 optional+nullable，用于配置层）。这是 `validateComplete` 能区分"稀疏配置层"和"最终生效配置"的基础。

**冲突如何解决**：字段级 overlay，**不存在冲突报错**——就是"后者赢"。唯一的冲突报错发生在 L4 的 JSON 路径层（第 5.2 节）。

**用户参数的插入点**：用户在 UI 上可编辑的叶子由 `manual-model-config.ts:24-26` 的白名单限定：

```ts
optionSpecs: complete.optionSpecs.pick({ reasoningLevel: true }).extend({
  maxOutputTokens: complete.optionSpecs.shape.maxOutputTokens.pick({ max: true }),
}),
```

> 用户可改：`reasoningLevel`（**整个，含 `values` + `map`**）与 `maxOutputTokens.max`。
> 用户**不可**改：**`maxOutputTokens.map`**（这个 pick 只取了 `max`）。
> 注释也说明了原则（`manual-model-config.ts:5`）："手动模式只冻结产品明确开放的叶子；新增系统字段默认不属于个人手动配置。"

> **修订说明（E17 / M3）**：原草稿此处写"用户在 UI 上只能改**档位值**（`reasoningLevel`），**不能改 map**"，与其紧随其后的"用户可改：`reasoningLevel`（整个，含 values + map）"**直接矛盾**。按 `manual-model-config.ts:24` 的 `pick({ reasoningLevel: true })`，**用户确实可以改 `reasoningLevel` 的 map**；唯一不可改的是 `maxOutputTokens.map`。已按源码统一表述。

### 5.4 【本次新增 M6】同一模型被 resolve 两次：`effectiveModelRules` 与 `zcodeBuiltinModelRules`

`resolver.ts:257-270`：

```ts
const modelConfig = effectiveModelRules.resolve({
  providerId, templateId, modelId,
  apiType: config.api?.type,
  baseUrl: config.api?.baseUrl,
});
const effectiveBuiltinConfig = input.zcodeBuiltinModelRules.resolve({
  providerId, templateId, modelId,
  apiType: config.api?.type,
  baseUrl: config.api?.baseUrl,
});
```

**同一个 `(providerId, modelId, apiType, baseUrl)` 组合会被解析两次**：

| 变量 | 用哪套规则 | 含义 |
|---|---|---|
| `modelConfig` | `effectiveModelRules` = **内置 + 个人精确规则**（`composeEffective` 的产物） | 最终生效配置 |
| `effectiveBuiltinConfig` | `input.zcodeBuiltinModelRules` = **只用内置规则** | 系统基线配置 |

两者**并存**发布给 UI（`resolver.ts:285-286`）：

```ts
config: modelConfig,
effectiveBuiltinConfig,
```

> **为什么重要**：这回答了原草稿 §12.5 悬置的问题——"手动规则只改 `enabled` 时，系统映射（如 `maxOutputTokens.map`）是否保留？"
> **答案是保留。** 机制是：`clearManualModelConfig`（`manual-model-config.ts:37-41`）只清掉"**手动白名单内的叶子**"（配合 `:43-56 omitSchemaFields` 递归裁剪），而 `maxOutputTokens.map` 不在白名单内，因此**系统叶子不受影响**；同时 `effectiveBuiltinConfig` 单独留存，UI 可以精确对比"用户改了什么、系统原值是什么"。
> 这是一处**可核实但原草稿未做**的验证（核验报告 U7），现已补入正文。

---

## 6. 内置映射规则库分类清单

数据源：`config/provider/zcode-builtin.json`（`revision: 30`）。全量扫描 5 个规则组的 map 字段。

### 6.0 规则组规模

| 规则组 | 条数 | 匹配维度 |
|---|---|---|
| `modelRules` | 84 | `modelMatch`（正则，对模型 ID） |
| `modelApiRules` | 72 | `modelMatch` + `apiTypeMatch` |
| `providerSiteRules` | 52 | `modelMatch` + `apiTypeMatch` + `baseUrlMatch` |
| `templateModelRules` | 244 | `templateId` + `modelId` |
| `builtinProviderModelRules` | 26 | `providerId` + `modelId` |
| **合计** | **478** | |

其中含 `map` 的规则：**119 条**（101 条 reasoningLevel + 18 条 maxOutputTokens），去重后 **21 种 reasoningLevel map + 4 种 maxOutputTokens map**。

### 6.1 maxOutputTokens：4 种（纯粹的参数改名）

| 次数 | map | 目标方言 |
|---|---|---|
| 15 | `{"max_tokens": maxOutputTokens}` | Anthropic Messages |
| 1 | `{'max_tokens': maxOutputTokens}` | 同上（单引号写法，语义等价） |
| 1 | `{'max_completion_tokens': maxOutputTokens}` | OpenAI 新命名 |
| 1 | `{'max_output_tokens': maxOutputTokens}` | OpenAI Responses API |

**归类：参数改名（key rename）。零取值域转换。** 这是最简单的一类，也是最容易用声明式表格替代的一类。

### 6.2 reasoningLevel：21 种，按语义归类

> **修订说明（E2）**：原草稿本节标题写"21 种，按语义归类"，但正文只列了 A(2) + B(6) + C(4) + D(5) + E(1) = 18 条，且类别 C 的第 3 行与类别 B 第 4 行是**同一条 map**（草稿自己注了"见类别 B"），因此实际去重覆盖为 **17 种**。
> 本节现已补全全部 21 种，算式为 **2 + 6 + 3 + 5 + 1 + 1 + 3 = 21**（A / B / C / D / E / F 空补丁 / G 未归入模板）。

#### 类别 A：**档位→布尔开关**（2 种）

| 次数 | map | 说明 |
|---|---|---|
| 6 | `{"enable_thinking": reasoningLevel == "enabled"}` | Qwen 系（`qwen3.5-plus`、`qwen-plus`、`qwen-flash`、`qwen3-vl-plus` 等） |
| 1 | `{"reasoning": {"enabled": reasoningLevel == "enabled"}}` | OpenRouter 上的 Qwen |

> 语义损失：`low/high/max` 三档被压成一个布尔。这是**能力降级**的一种（下方类别 H-1 有更完整的讨论）。

#### 类别 B：**档位→厂商枚举（含特殊值翻译）**（6 种）

| 次数 | map | 特殊处理 |
|---|---|---|
| 17 | `{"reasoning_effort": reasoningLevel}` | 纯透传 |
| 9 | `{"reasoning": {"effort": reasoningLevel}}` | 纯透传（OpenAI Responses） |
| 5 | `{"output_config": {"effort": reasoningLevel}}` | 纯透传（Anthropic Messages 上的 Kimi K3 / GPT-5.6） |
| 3 | `{"thinking": {"type": "adaptive"}, "output_config": {"effort": reasoningLevel}}` | Claude 5 / GLM-X-Preview 系，固定 `adaptive` + 透传 effort |
| 3 | `{"reasoning": {"effort": reasoningLevel == "disabled" ? "none" : reasoningLevel}}` | **`disabled` → `"none"`**（DeepSeek 官方 Responses API 的方言） |
| 1 | `{"thinking": {"type": reasoningLevel == "disabled" ? "disabled" : "adaptive"}}` | minimax-m3 @ opencode |

> **修订说明（E14）**：第 1 行原写"纯透传（Kimi K3 / GPT-5.4 / Qwen3.8 / **Grok** 等，`values=["low","high","max"]`）"，有两处失准：
> ① **"Grok" 是凭空引入**——全仓 `config/provider/zcode-builtin.json` 中 `grok` **0 命中**。已删除。
> ② **`values=["low","high","max"]` 并非通用**。脚本全量列举这 17 条规则，`values` **因站点而异**：
> - `["max"]`（`kimi-k3` @ 站点规则）
> - `["high","max"]`（`glm-5.2`）
> - `["none","high"]`（`hy4-preview`）
> - `["none","low","high"]`（`hy3`）
> - 另有 7 条 `modelApiRules` 规则**不声明 `values`**（继承 `modelRules`）
>
> 覆盖的模型：`ox-alpha|glm-x-preview-f`、`kimi-k3`、`k3`、`k3-256k`、`qwen3.8-max/flash`、`gpt-5.4`、`qwen3.8-omni-flash`、`glm-5.3-flash`、`glm-5.3`、`glm-5.2`、`deepseek-v4.1-flash`、`deepseek-v4-pro`、`deepseek-v4-flash`、`deepseek-v4-flash-vision-exp`、`hy4-preview`、`hy3`。

#### 类别 C：**语义档位 → 厂商词表翻译**（`enabled`/`disabled` ↔ 厂商词表）（**3 种**）

这是**"统一语义档位"最核心的价值体现**：上游只有 `disabled|enabled` 两个档，下游词表千差万别。

| 次数 | map | 翻译规则 |
|---|---|---|
| 27 | `{"thinking": {"type": reasoningLevel == "enabled" ? "enabled" : "disabled"}}` | 二元开关 |
| 2 | `{"thinking": {"type": reasoningLevel == "disabled" ? "disabled" : "enabled"}}` | 同上（条件反向写法，语义等价） |
| 2 | `{"reasoning": {"effort": reasoningLevel == "disabled" ? "none" : "high"}}` | **`enabled` → `"high"`**（kimi-k2.7-code、qwen3.7/3.6 @ responses） |

> **修订说明（E2 / E15）**：
> ① 表头原写"（**4 种**）"，但第 3 行 `{"thinking":{"type":"adaptive"},"output_config":{"effort": reasoningLevel}}` 与类别 B 第 4 行是**同一条 map**（原草稿自己注了"见类别 B"），故实际只有 **3 种**。已删除该重复行并改正表头。
> ② 第 1 行原写"二元开关（GLM-5/5.1/4.7 等 **27 个模型** @ anthropic-messages）"，两处失准：
>    - **27 是规则条数，不是模型数**。该 27 条规则中存在重复 `modelMatch`（`kimi-k2.6`×2、`kimi-k2.5`×2、`mimo-v2.5`×2、`mimo-v2.5-pro`×2、`mimo-v2-flash`×2），**实际不同模型 < 27**。
>    - 构成是 **glm（11）+ qwen（6）+ mimo（7）+ kimi（4）** 的混合，"GLM-5/5.1/4.7 等"易被误读为全部是 GLM。
>    已改为"**27 条规则**（含重复 `modelMatch`），覆盖 **glm / qwen / mimo / kimi** 四族"。

#### 类别 D：**条件分支改变"字段集合"**（不是改值，而是改发哪些字段）（5 种）

这是**最有技术含量**的一类，直接解决"厂商对字段组合有约束"的问题。

**D-1**（1 次，全局兜底）`zcode-builtin.json:2500`
```
reasoningLevel == "disabled"
  ? { "thinking": { "type": "disabled" } }
  : { "thinking": { "type": "adaptive" },
      "output_config": { "effort": reasoningLevel == "enabled" ? "high" : reasoningLevel } }
```
> disabled 时**不发 `output_config`**。

**D-2**（5 次：GLM-5.2、DeepSeek-V4-Flash/Pro、deepseek-flash、deepseek-v4.1-flash @ anthropic-messages）
```
reasoningLevel == "disabled"
  ? { "thinking": { "type": "disabled" } }
  : { "thinking": { "type": "enabled" },
      "output_config": { "effort": reasoningLevel } }
```
> 与 D-1 的差别：非 disabled 时 `thinking.type` 用 `"enabled"` 而非 `"adaptive"`。

**D-3**（4 次：DeepSeek 系 @ openai-chat-completions）
```
reasoningLevel == "disabled"
  ? { "thinking": { "type": "disabled" } }
  : { "thinking": { "type": "enabled" },
      "reasoning_effort": reasoningLevel }
```
> 注意：字段名从 `output_config.effort` 换成了 `reasoning_effort`——**同一模型在两种协议下走两套完全不同的补丁**。

**D-4**（1 次，OpenRouter 兜底）`zcode-builtin.json` providerSiteRules
```
reasoningLevel == "disabled" || reasoningLevel == "none"
  ? { "thinking": { "type": "disabled" } }
  : { "thinking": { "type": "adaptive" },
      "output_config": { "effort": reasoningLevel == "enabled" ? "high" : reasoningLevel } }
```
> 比 D-1 多接受一个 `"none"` 别名。

**D-5**（1 次，OpenRouter 上的 GPT-5.4）
```
reasoningLevel == "none"
  ? { "thinking": { "type": "disabled" } }
  : { "output_config": { "effort": reasoningLevel } }
```
> **只认 `"none"`，不认 `"disabled"`**——档位词表本身就是站点相关的。

#### 类别 E：**多方言同时注入（广播）**（1 次）

`zcode-builtin.json:2514`（openai-chat-completions 全局兜底）——见 2.4 例 3。
> 一次写 4 个字段（`thinking` / `enable_thinking` / `reasoning_effort` / `reasoning`），**让下游网关挑它认得的那一个**。这是"我不知道对面是谁"时的防御式策略，也是**最应该被我们的网关警惕**的做法：它把不确定性推给了下游。

#### 类别 F：**空补丁**（1 种）

| 次数 | map | 归属 |
|---|---|---|
| 8 | `{}` | `modelRules` 兜底（`zcode-builtin.json:894`）等多处 |

> `collectWrittenPaths({})` 返回 `[]`（`merge-patch.ts:35-49`），既不写字段也不占路径——"这个模型的 reasoning 完全交给 SDK / 厂商默认"。**它是 21 种去重 map 中重复度第三高的一种（8 次），原草稿的分类表未收。**

#### 类别 G：**未归入上述模板的 3 种**（本次补全）

> **修订说明（E2）**：以下 3 种 map 在 `zcode-builtin.json` 中真实存在，但原草稿 §6.2 的归类表**全部漏列**。

| # | map | 次数 | 归属（file:line 证据） |
|---|---|---|---|
| G-1 | `{"thinking":{"type":"enabled"},"output_config":{"effort": reasoningLevel}}` | 2 | `modelApiRules` 中 `.*glm-5\.3(?:-flash)?` @ anthropic-messages；`.*qwen3\.8-(?:max\|flash)` @ anthropic-messages |
| G-2 | `{"reasoning":{"effort": reasoningLevel == "disabled" ? "none" : reasoningLevel == "enabled" ? "high" : reasoningLevel}}` | **1** | **`zcode-builtin.json:2528` —— `modelApiRules` `modelMatch:"."*` @ openai-responses 全局兜底** |
| G-3 | `reasoningLevel == "disabled" ? {"reasoning":{"enabled": false}} : {"reasoning":{"effort": reasoningLevel}}` | 1 | `providerSiteRules` `.*deepseek-v4[.-]1-flash` @ openai-chat-completions @ openrouter |

> **G-2 为什么必须补**：原草稿 §9.4 已经引用了 anthropic（`:2500`）与 chat-completions（`:2514`）两条**协议兜底**，**唯独漏了 responses 兜底**。这会造成"3 种协议兜底"的叙述只覆盖 2 条 reasoning 兜底 + 3 条 maxOutputTokens 兜底，读者会误以为 **openai-responses 协议没有 reasoning 兜底**。事实上 `:2528` 存在，且是**全库唯一使用链式三元的 reasoning 兜底**。
>
> **G-3 为什么必须补**：这条 map 其实就是原草稿 §9.3「场景 B」引用的那一条——作者见过它但忘了收进分类表，属**归类遗漏**而非认知错误。

### 6.3 未覆盖的维度（重要！）

**内置 119 条 map 中，以下维度完全没有出现：**

| 维度 | 是否覆盖 |
|---|---|
| `temperature` 范围/改名 | ❌ 不在 option map 内（但见下方注） |
| `top_p` / `top_k` | ❌ 同上 |
| 惩罚项 `frequency_penalty` / `presence_penalty` / `repetition_penalty` | ❌ 同上 |
| 工具调用格式（`tools` / `tool_choice` / 并行调用开关） | ❌ 由 AI SDK 层与 `strict-tool-schema.ts` 等处理，不走 option map |
| 缓存参数（`cache_control` / prompt caching） | ❌ |
| 停止词 `stop` / `stop_sequences` | ❌ 同上 |
| 结构化输出开关（`response_format` / `json_schema`） | ❌ 走 `supportsJsonSchemaOutput` 能力位 + SDK 装配（`model-execution.ts:313`） |
| 流式开关 | ❌ |
| 多模态字段形态 | ❌ |
| 参数删除（`null`） | ⚠️ 语言支持，配置零使用 |

> **注（E4 / M5）**：上表的限定语"**内置 119 条 map 中**"是准确的——这些维度确实不在 option map 里。但**不可由此推出"ZCode 不管这些参数"**：其中 `temperature` / `top_p` / `top_k` / 惩罚项 / `stop` 由**第二条参数路径**（`ModelRequestSettings` → `runner-options.ts:73-79`）直通透传给 AI SDK，只是**不做厂商方言归一化**。详见 §4.5。

> **这直接回答了"ZCode 有没有一套完整的模型参数处理机制"**：它有一套**极其完整的「两个参数的厂商方言归一化」机制**，一套**通用的「配置分层覆盖」机制**，以及一套**「其余参数的直通透传」机制**。三者经常被混为一谈。前两者由 option map 承载，第三者与 option map 无关。

### 6.4 非 map 的规则形态（与原草稿类别 F / G 对应）

#### 类别 H：**能力降级 / 硬禁用**（不属于 map，但属于同一规则表）

1. **档位词表收缩（= 能力降级的一种）**：`values` 从 `["disabled","enabled","low","high","max"]` 收缩到 `["disabled","enabled"]`。典型如 `modelRules` 里 `.*glm-5` 规则（`zcode-builtin.json` 中 `"values": ["disabled","enabled"]`）——**UI 上只给两个档**，用户选不到中间档，map 也不需要处理。
   > **修订说明（M4）**：原草稿 §0 第 8 条声称"不做能力降级协商（只有 `enabled: false` 硬禁用）"，与本条的"词表收缩"**自相矛盾**——`values` 从 5 档收缩到 2 档，**本身就是一种能力降级**。正确的表述是：ZCode **有**静态的能力降级（词表收缩 + 硬禁用），**没有的是**"运行时按用户/负载动态协商降级"。§0 第 8 条已据此改写。
2. **模型硬禁用**：`templateModelRules` 里 `config.enabled: false`。例如 GLM-4.6 全线禁用：
   ```json
   { "modelId": "GLM-4.6",  "templateId": "zai-standard-api",     "config": { "enabled": false } }
   { "modelId": "GLM-4.6",  "templateId": "bigmodel-standard-api", "config": { "enabled": false } }
   { "templateId": "openrouter", "modelId": "z-ai/glm-4.6",       "config": { "enabled": false } }
   ```
   生效点：`resolver.ts:278` `const modelEnabled = modelConfig.enabled === true;`，进而 `resolver.ts:279` 决定 `executable`，不可执行就不进 Registry、UI 里不可选。
3. **能力位降级**：`properties.supportsJsonSchemaOutput`、`supportsNativeWebSearch`、`supportsMidConversationSystem`、`contextWindow`、`inputFormat.supportsImage/Video/Audio/Pdf`。这些**不是参数**，但走**完全相同的规则表与优先级链**。例如 `providerSiteRules` 给 DeepSeek 官方站点打开原生搜索：
   ```json
   { "modelMatch": ".*", "apiTypeMatch": "anthropic-messages",
     "baseUrlMatch": "(?:https://api\\.deepseek\\.com/anthropic)",
     "config": { "properties": { "supportsNativeWebSearch": true,
                                 "supportsMidConversationSystem": true } } }
   ```

#### 类别 I：**站点级覆盖（同一模型，同一协议，不同网关）**

`providerSiteRules` 的 `baseUrlMatch` 分布（12 个站点）：

| 条数 | baseUrlMatch |
|---|---|
| 25 | `https://opencode\.ai/zen/go/v1/?` |
| 11 | `https://openrouter\.ai/api(?:/v1)?/?` |
| 4 | `https://api\.deepseek\.com(?:/.*)?` |
| 2 | `https://api\.z\.ai/api/anthropic/?` |
| 2 | `https://open\.bigmodel\.cn/api/anthropic/?` |
| 2 | `https://zcode\.z\.ai/api/v1/zcode-plan/anthropic/?` |
| 1 | `(?:https://api\.anthropic\.com/v1)` |
| 1 | `(?:https://api\.moonshot\.cn/anthropic)` |
| 1 | `(?:https://api\.deepseek\.com/anthropic)` |
| 1 | `https://zcode\.z\.ai/api/v1/off-peak/anthropic/?` |
| 1 | `https://dashscope\.aliyuncs\.com/apps/anthropic/?` |
| 1 | `https://dashscope-intl\.aliyuncs\.com/apps/anthropic/?` |

**这是"同一模型不同厂商标准不一致"最直接的证据**：`deepseek-v4-pro` 在 `api.deepseek.com`（`reasoning.effort`，`disabled→"none"`）和 `openrouter.ai`（`reasoning.enabled` / `reasoning.effort`）上的 map **完全不同**。

---

## 7. 类型体系（`types.ts` + 上下游）

### 7.1 `types.ts` 全部定义（36 行，9 个实体）

> **修订说明（E12）**：原草稿标题写"仅 **5 个**实体"，但同节的列表里实际列出了 **9 个**——属标题与内容的**自相矛盾笔误**。已改正。

```ts
export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | readonly JsonValue[];

export interface JsonObject {
  readonly [key: string]: JsonValue;
}

export type RestrictedCelValue = string | number;                    // ← 输入域
export type ModelOptionName = "reasoningLevel" | "maxOutputTokens";   // ← 唯一两个 option

export interface RestrictedCelProgram {
  readonly source: string;
  evaluate(input: RestrictedCelValue): JsonValue;
}

export interface ModelOptionMapProgram {
  readonly source: string;
  evaluate(input: RestrictedCelValue): JsonObject;    // ← 返回类型收紧为 object
}

export class RestrictedCelError extends Error {
  readonly offset: number;    // ← 带字符偏移，便于定位配置错误
  constructor(message: string, offset: number) {
    super(`${message} at offset ${offset}`);
    this.name = "RestrictedCelError";
    this.offset = offset;
  }
}

export class ModelOptionMapError extends Error { ... }
```

**9 个 export 实体及其行号**：`JsonPrimitive`（L1）、`JsonValue`（L2）、`JsonObject`（L4）、`RestrictedCelValue`（L8）、`ModelOptionName`（L9）、`RestrictedCelProgram`（L11）、`ModelOptionMapProgram`（L16）、`RestrictedCelError`（L21）、`ModelOptionMapError`（L31）。

### 7.2 类型关系图

```
                          ┌─────────────────────┐
                          │  JsonValue (union)  │
                          └──────────┬──────────┘
              ┌────────────────┬─────┴──────┬──────────────┐
              ▼                ▼            ▼              ▼
      JsonPrimitive      JsonObject   readonly        (递归)
    string|number|        {[k]:        JsonValue[]
    boolean|null          JsonValue}
              │
              ▼
   ┌──────────────────────┐
   │ RestrictedCelValue   │  string | number      ← 求值输入域（只有标量！）
   └──────────┬───────────┘
              │ 是 JsonValue 的真子集
              ▼
   ┌──────────────────────┐
   │  ModelOptionName     │  "reasoningLevel" | "maxOutputTokens"
   └──────────┬───────────┘
              │ 决定 parser 里唯一合法的变量名
              ▼
   ┌──────────────────────────────────────────────────────────┐
   │ RestrictedCelToken  { kind, value, offset, end }         │  tokenizer.ts:11
   │   kind: identifier|string|number|operator|punctuation|eof│
   └──────────┬───────────────────────────────────────────────┘
              │ tokenizeRestrictedCel(source)
              ▼
   ┌──────────────────────────────────────────────────────────┐
   │ RestrictedCelExpression (AST, 7 变体)                    │  parser.ts:4-44
   │   literal | input | array | object | unary | binary |    │
   │   conditional                                            │
   └──────────┬───────────────────────────────────────────────┘
              │ parseRestrictedCel(tokens, variableName)
              ▼
   ┌──────────────────────┐        ┌──────────────────────────┐
   │ RestrictedCelProgram │        │ ModelOptionMapProgram    │
   │ { source,            │◄───────│ { source,                │
   │   evaluate(v):       │  收紧   │   evaluate(v):           │
   │     JsonValue }      │  返回型 │     JsonObject }         │  types.ts:11-19
   └──────────────────────┘        └──────────┬───────────────┘
                                              │ compileModelOptionMap
                                              ▼
   ┌──────────────────────────────────────────────────────────┐
   │ CompiledModelOptionMaps                                  │  option-maps.ts:15
   │   apply(body: JsonObject, values: ModelOptionValues)     │
   │     : JsonObject                                         │
   └──────────┬───────────────────────────────────────────────┘
              │ 组合两个 program
              ▼
   ┌──────────────────────┐   ┌───────────────────────────────┐
   │ ModelOptionMapSpecs  │   │ ModelOptionValues             │  option-maps.ts:5/10
   │ { reasoningLevel:    │   │ { reasoningLevel: string      │
   │     { map: string }, │   │   maxOutputTokens: number }   │
   │   maxOutputTokens:   │   └───────────────────────────────┘
   │     { map: string } }│
   └──────────────────────┘
              ▲                                   ▲
              │ 来自配置                            │ 来自用户选择/调用方
   ┌──────────────────────┐   ┌───────────────────────────────┐
   │ ModelOptionSpecs     │   │ ModelOptions                  │
   │ Config（provider 侧） │   │ { reasoningLevel?,            │  contracts/model/model.ts:26
   │ EnumOptionSpec{      │   │   maxOutputTokens? }          │
   │   values, map }      │   └───────────────────────────────┘
   │ LimitOptionSpec{     │
   │   max, map }         │
   └──────────────────────┘

   ┌──────────────────────┐   ┌───────────────────────────────┐
   │ NamedJsonMergePatch  │   │ ModelConfigRule (6 变体)      │  model-config.ts:345
   │ { option, patch }    │   │  provider-model | manual-     │
   └──────────────────────┘   │  provider-model | template-   │
                              │  model | model | model-api |  │
                              │  provider-site                │
                              └───────────────────────────────┘

   ┌──────────────────────┐
   │ ConfigOverlay<T>     │  ← 覆盖基类，ModelConfig / ProviderConfig /
   │  overlayValue        │    EnumOptionSpecConfig 等全部继承
   │  overlayConfig       │  config-overlay.ts:21
   └──────────────────────┘
```

> **修订说明（E20）**：原图注在 `RestrictedCelProgram` / `ModelOptionMapProgram` 处标 `compiler.ts:16/35`，两处均错——`compiler.ts:16` 是**空行**，`compiler.ts:35` 是 `compileModelOptionMap` **函数**而非接口。两个接口的定义实际在 **`types.ts:11-14` / `types.ts:16-19`**。已改为 `types.ts:11-19`。

### 7.3 类型设计上值得注意的点

1. **`RestrictedCelValue = string | number` 是最强的约束表达**：它用类型系统宣告"求值期没有对象、没有布尔、没有数组"。想引入富上下文（如 `ctx.apiType`）必须改这个类型——**改动成本被刻意做得很高**，防止上下文无序膨胀。
2. **`ModelOptionMapProgram` 只收紧了返回类型**（`JsonObject` 而非 `JsonValue`），没有引入新概念。这是"最小扩展"的范例。
3. **`RestrictedCelError` 带 `offset`**：错误信息形如 `member access is not supported at offset 5`（`types.ts:25`），可直接在配置编辑 UI 里定位到第 5 个字符。
4. **`JsonObject` 是 `readonly` + `Object.create(null)`**（`evaluator.ts:26`、`merge-patch.ts:83`）：**求值结果深度冻结**（`evaluator.ts:14` 的 `freezeJson`）且**无原型**。
   > **修订说明（E16）**：原草稿写"`readonly` + `Object.create(null)`：**不可变** + 无原型"，其中"不可变"**过度泛化**。按源码：
   > - **求值结果**确实深度冻结（`evaluator.ts:14` → `freezeJson`，`evaluator.ts:201-210` 递归 `Object.freeze`）；
   > - **`merge-patch.ts:80-93` 的 `cloneJson`** 用 `Object.create(null)` 创建，但 `Object.defineProperty` 时设的是 `configurable: true, writable: true`，**且不调用 freeze**——因此 `applyOrderedJsonMergePatches` 的**返回值是可变的**。
   >
   > 正确表述：**求值结果深度冻结；merge-patch 输出无原型但未冻结。**（这也是它必须 `cloneJson` 拷贝而不是直接复用求值结果的原因之一。）

---

## 8. `provider/config` 各模块协同关系

### 8.1 职责矩阵

| 文件 | 行数 | 职责 | 关键导出 |
|---|---|---|---|
| `ids.ts` | 3 | 品牌类型别名（`ProviderId`/`ProviderTemplateId`/`ModelId` = `string`） | 3 个 type |
| `schema.ts` | 160 | **反序列化入口**：把磁盘 JSON 变成内存类实例 | `parseZCodeBuiltinModelConfigRules`（`:78`）、`parseZCodeBuiltinProviderConfigRules`（`:44`）、`parsePersonalModelConfigRules`（`:109`） |
| `rule-data-schema.ts` | 185 | **规则的 zod 数据合同**（6 类模型规则 + 2 类厂商规则） | `builtinModelConfigRulesSchema`（`:55`）、`personalModelConfigRulesSchema`（`:64`） |
| `provider-data-schema.ts` | 113 | **厂商/模板/API 的 zod 数据合同** | `providerConfigDataSchema`、`completeProviderConfigDataSchema`、`providerApiTypeDataSchema` |
| `manual-model-config.ts` | 69 | **用户可编辑叶子的白名单**（手动模式） | `manualModelConfigSchema`（`:6`）、`clearManualModelConfig`（`:37`）、`extractManualModelConfig`（`:32`） |
| `model-config.ts` | 581 | **模型配置领域类 + 规则引擎**（overlay + resolve） | `ModelConfig`、`ModelConfigRules`（`:366`）、`ModelOptionSpecsConfig`（`:248`）、`EnumOptionSpecConfig`（`:43`）、`LimitOptionSpecConfig`（`:80`）、`ModelPropertiesConfig`（`:177`） |
| `provider-config.ts` | 513 | **厂商配置领域类**（access/api/group/logo/modelIds） | `ProviderConfig`（`:173`）、`ProviderApiConfig`（`:131`）、`ApiKeyAccessConfig`（`:36`）、`ZhipuAccountAccessConfig`（`:76`）、`ProviderConfigMap`（`:383`）、`ProviderTemplateMap`（`:310`） |
| `schema-validation.ts` | 43 | **zod issue → 产品错误协议**的翻译层 | `validateConfigSchema`（`:5`） |
| `../config-overlay.ts` | 46 | **覆盖语义基类 + 错误码枚举** | `ConfigOverlay`（`:21`）、`ConfigValidationIssue`（`:1`） |

### 8.2 调用关系（谁调谁）

#### 8.2.1 【本次新增 M8】上游来源层：`sources.ts` / `facades.ts`

> 原草稿的调用图从 `config/provider/zcode-builtin.json` **直接跳到** `provider-node/src/zcode-builtin-release.ts`，**略过了 `ProviderConfigSnapshot` 这一层**。真实链路中它是规则的实际来源容器。

`packages/provider/src/sources.ts:13-25`：

```ts
export interface ProviderConfigSnapshot {
  readonly revision: string;
  readonly zcodeBuiltinRevision: string;
  readonly personalRevision: string;
  readonly zcodeBuiltinProviders: ProviderConfigMap;
  readonly zcodeBuiltinProviderTemplates: ProviderTemplateMap;
  readonly personalProviders: ProviderConfigMap;
  readonly zcodeBuiltinModelRules: ModelConfigRules;   // ← §5.4 二次 resolve 用的就是它
  readonly personalModels: ModelConfigRules;
  readonly personalProviderOrder?: readonly string[];
}
```

`packages/provider/src/facades.ts`（688 行）承载 Settings / Selection 的 **Registry 投影与写入边界**（引用 `ModelConfig`、`ModelConfigRules`、`parseModelConfig`、`serializeRegistryModelConfig`）。

> **注意**：`sources.ts` 与 `facades.ts` **不含** `optionSpecs` / `reasoningLevel` 字面量（grep 0 命中），因此**不属于"参数映射机制"本身**，但属于**规则链上游**。若要画完整 L1→L2 数据流，这一层不应省略。
> 尤其注意：`ProviderConfigSnapshot.zcodeBuiltinModelRules`（`:20`）正是 §5.4 中 `resolver.ts:264` 二次 resolve 的输入。

#### 8.2.2 主调用链

```
                       ┌────────────────────────────────────┐
                       │ config/provider/zcode-builtin.json │
                       └────────────────┬───────────────────┘
                                        │ JSON.parse
                                        ▼
        ┌───────────────────────────────────────────────────────────┐
        │ provider-node/src/zcode-builtin-release.ts                │
        │  decodeZCodeBuiltinRelease()                              │
        │   ① releaseSchema.parse(input)  → 校验 schemaVersion/rev  │  :25-36 / :39
        │   ② parseZCodeBuiltinProviderConfigRules(...)             │  :40
        │   ③ parseZCodeBuiltinModelConfigRules(...)                │  :54
        │   ④ 拒绝已退役 Provider（builtin:zapi）                    │  :43-47
        └────────────────┬──────────────────────────────────────────┘
                         │  → ProviderConfigSnapshot（sources.ts:13-25）★本次补
        ┌────────────────┴──────────────────────────────────────────┐
        │ packages/provider/src/config/schema.ts                    │
        │  parseZCodeBuiltinModelConfigRules(input)                 │  :78
        │    builtinModelConfigRulesSchema.parse(input)             │  ← rule-data-schema.ts:55
        │      └─ 每条 rule.config 走 modelConfigDataSchema          │  ← shared/model-config.ts:109
        │           └─ optionSpecs.{reasoningLevel,maxOutputTokens}  │
        │                └─ optionMapSchema(variableName)            │  ← shared/model-config.ts:5
        │                     └─ compileModelOptionMap(source,var)   │  ★ DSL 编译校验发生在这里
        │    → 按固定顺序 new ModelConfigRules([...])                │  :80-106
        └────────────────┬──────────────────────────────────────────┘
                         │
        ┌────────────────┴──────────────────────────────────────────┐
        │ packages/provider/src/resolver.ts                        │
        │  ProviderConfigResolver.resolve(input)                    │  :183
        │    ModelConfigRules.composeEffective(builtin, personal)   │  ← model-config.ts:379
        │    for each provider:                                     │
        │      rule.config 与 template overlay → effectiveProvider  │  :192-197
        │      for each modelId:                                    │
        │        effectiveModelRules.resolve({...})   ★第 1 次 resolve│  :257-263
        │        zcodeBuiltinModelRules.resolve({...}) ★第 2 次 resolve│  :264-270（本次补 M6）
        │          → effectiveBuiltinConfig 与 config 并存发布        │  :285-286
        │        createRegistryModelConfig(modelConfig, path)       │  :271
        │          → config.validateComplete(path)                  │  ← model-config.ts:324
        │            → validateConfigSchema(complete..., value, path)│ ← schema-validation.ts:5
        │        executable = providerExecutable && enabled && noIssues │ :279
        │    → registryProviders: readonly Provider[]                │  :325-333
        └────────────────┬──────────────────────────────────────────┘
                         │
        ┌────────────────┴──────────────────────────────────────────┐
        │ packages/provider/src/registry.ts                         │
        │  ProviderRegistry.replace(providers, reason)              │  :94
        │  validateSelection(selection)                             │  :74
        │    └─ validateModelSelectionOptions(model, selection)      │  :129
        │         reasoningSpec.values.includes(reasoningLevel)      │  :148
        │         → { ok:false, code:"reasoning-level-not-supported" │  :150-156
        │             supportedLevels }                              │
        └───────────────────────────────────────────────────────────┘
```

### 8.3 schema 校验在什么时候跑、失败怎么办

**共 3 个校验时机，策略各不相同：**

| 时机 | 位置 | 校验什么 | 失败后果 |
|---|---|---|---|
| **① 反序列化（硬失败）** | `zcode-builtin-release.ts:39` `releaseSchema.parse()`；`schema.ts:79` `builtinModelConfigRulesSchema.parse()` | 整份 Release 的结构 + 每个字段的类型 + **map 能否编译** | **抛异常**（zod `.parse`）。上游 `decodeZCodeBuiltinRelease` 抛错 → Source 回落到兼容候选（注释 `zcode-builtin-release.ts:43-45`："拒绝整份不兼容 Release，让 Source 回落到兼容候选"）。**即：坏配置不会半生效，整份回退。** |
| **② 完整性校验（软失败，收集 issues）** | `model-config.ts:324` `validateComplete()` → `schema-validation.ts:5` `validateConfigSchema`（用 `safeParse`） | 覆盖后的配置是否满足 `complete*` schema（全部必填） | **返回 `ConfigValidationIssue[]`**，不抛。`resolver.ts:271-279` 把 issues 记到该 model 上，`executable=false`，**该模型不进 Registry（UI 里看不到、选不了）**，但**其他模型照常可用**。 |
| **③ 请求期档位校验（硬失败）** | `registry.ts:129-159` `validateModelSelectionOptions` | 用户选的 `reasoningLevel` 是否在 `values` 里 | 返回 `{ok:false, code:"reasoning-level-missing" / "reasoning-level-not-supported", supportedLevels}`。调用方拒绝该请求。 |

**`validateConfigSchema` 的错误码映射逻辑**（`schema-validation.ts:22-41`）值得单独看——它把 zod 的通用 issue 翻译成产品语义：

```ts
const missing =
  ((issue.code === "invalid_type" || issue.code === "invalid_value") && fieldValue == null) ||
  (issue.code === "custom" && issue.params?.configIssueCode === "required-field-missing");
const invalidUrl = issue.code === "invalid_format" && issue.format === "url";
return {
  code: missing
    ? "required-field-missing"
    : invalidUrl
      ? "invalid-url"
      : optionSpec || issue.path.includes("optionSpecs")
        ? "invalid-option-spec"        // ← DSL 编译错误归到这里
        : "invalid-config",
  path: issuePath,
  message: missing
    ? `缺少必填配置 ${issuePath.join(".")}`
    : invalidUrl
      ? `配置 ${issuePath.join(".")} 必须是有效 URL`
      : issue.message,
};
```

> **`invalid-option-spec` 是 DSL 语法错误的最终归宿**：因为 `optionMapSchema` 的 `superRefine` 用的是 `code: "custom"`（`shared/model-config.ts:13-16`），而 `validateConfigSchema` 通过 `issue.path.includes("optionSpecs")` 把它分类为 `invalid-option-spec`。**UI 可以据此高亮"这条 map 写错了"并展示 `RestrictedCelError.message`（含 offset）。**

**发现的瑕疵**：`config-overlay.ts:1-14` 的错误码联合类型声明了 9 个成员，但 `invalid-reasoning-mapping`（`:8`）与 `invalid-pattern`（`:9`）**在全仓库没有任何生产点**（已 grep 全量 `.ts` 确认）。`invalid-pattern` 的语义被 `rule-data-schema.ts:14-24` 的 `patternSchema.refine(new RegExp(...))` 吸收，但 refine 的默认 message 会被归类为 `invalid-config`。属于历史遗留的未清理枚举（原设计意图**无法核实**，见 §12）。

### 8.4 【本次新增 M7】远端配置同步与回落机制

> 原草稿 §12.4 只承认"`zcode-builtin-remote-synchronizer.ts` 的远端同步/回落策略我只读到注释，**未读实现细节**"，**正文完全没有该机制的位置**。
> 但 §8.3 的结论"**坏配置不会半生效，整份回退**"——"回退到哪一份、怎么判定坏、多久重试"——全部由这个模块回答。本节补齐。

**涉及文件**（`packages/provider-node/src/`）：

| 文件 | 行数 | 职责 |
|---|---|---|
| `zcode-builtin-remote-synchronizer.ts` | 217 | 刷新调度：租约、退避、六态结果 |
| `endpoint-scoped-zcode-builtin-source.ts` | 148 | 按 endpoint 隔离配置源 |
| `zcode-builtin-download.ts` | 128 | 远端 Release 下载 |
| `zcode-builtin-cache-paths.ts` | 67 | 缓存路径（`zcode-builtin.json` 活跃文件 + `zcode-builtin-refresh.json` 控制文件，`:38-40`） |

**六态结果**（`zcode-builtin-remote-synchronizer.ts:9-15`）：

```ts
export type ZCodeBuiltinRefreshResult =
  | "updated" | "unchanged" | "stale" | "missing" | "skipped" | "disposed";
```

**跳过原因**（`:35`）：`"lease-held" | "not-due" | "endpoint-changed"`

**租约与控制文件**（`:39-46`）：

```ts
interface RefreshControl {
  readonly schemaVersion: 1;
  readonly endpointKey: string;
  readonly leaseId?: string;
  readonly leaseUntil: number;
  readonly nextEligibleAt: number;
  readonly failureCount: number;
}
```

**退避参数**（`:27-30`）：`successIntervalMs`、`leaseDurationMs`、`failureBaseDelayMs`、`failureMaxDelayMs`。

**退避算法**（`:151-159`）——成功用固定间隔，失败用**指数退避 + 封顶**：

```ts
const delay =
  success === "cancelled"
    ? 0
    : success
      ? (this.#options.successIntervalMs ?? HOUR_MS)
      : Math.min(
          (this.#options.failureBaseDelayMs ?? 60_000) * 2 ** Math.max(0, failureCount - 1),
          this.#options.failureMaxDelayMs ?? HOUR_MS,
        );
```

即：成功 → 默认 1 小时后再刷新；失败 → `60s × 2^(n-1)`，封顶 1 小时。租约默认 30 秒（`:96`）。

**"回退到哪一份"**（`zcode-builtin-provider-config-source.ts:64-84`）：

```ts
async applyRemoteRelease(release: ZCodeBuiltinRelease): Promise<ApplyZCodeBuiltinReleaseResult> {
  // ...
  if (release.revision < current.revision) return "stale" as const;
  if (release.revision === current.revision) {
    if (serializeZCodeBuiltinRelease(release) === serializeZCodeBuiltinRelease(current)) {
      return "unchanged" as const;
    }
    throw new Error(`ZCode Built-in 相同 revision ${release.revision} 对应不同内容`);
  }
  await this.#writeActiveLocked(release);
  // ...
  return "updated" as const;
}
```

配合 `#readAndMaterializeLocked()`（`:100-104`）同时读取 **bundled（随包内置）** 与 **active（已落盘的最新）** 两个候选，取可用者。

> **机制小结（回答 §8.3 的问题）**：
> - **判定"坏"**：`decodeZCodeBuiltinRelease` 的反序列化硬失败（zod `.parse` 抛错）→ 该候选被拒；或远端 revision 低于本地 → `stale`；或同 revision 但内容不同 → 抛错（**拒绝静默覆盖**）。
> - **回退到哪一份**：**本地已落盘的 `active` 文件**；若 active 不可用则回退到**随包内置的 bundled**。**绝不半生效**——整份 Release 原子替换。
> - **多久重试**：成功 1 小时；失败 60s 起指数退避、封顶 1 小时；多进程用文件锁 + 租约（30s）互斥，网络请求期间**不持有文件锁**（`:48` 注释）。

---

## 9. 真实配置数据剖析（`config/provider/zcode-builtin.json`）

### 9.1 文件骨架

```json
{
  "schemaVersion": 1,
  "revision": 30,
  "config": {
    "providerConfigRules": {
      "templateRules": [ ... ],   // 厂商模板（可复用的 baseUrl / api type / access type）
      "providerRules":  [ ... ]   // 8 个具体厂商
    },
    "modelConfigRules": {
      "modelRules":                [ 84 ],
      "modelApiRules":             [ 72 ],
      "providerSiteRules":         [ 52 ],
      "templateModelRules":        [ 244 ],
      "builtinProviderModelRules": [ 26 ]
    }
  }
}
```

字段语义：

| 字段 | 含义 |
|---|---|
| `schemaVersion` | 硬版本，`z.literal(1)`（`zcode-builtin-release.ts:27`），不匹配直接拒整份 |
| `revision` | 单调递增的配置版本号，进 Registry 的 revision（`zcode-builtin-provider-config-source.ts:213`：`` `zcode-builtin:${release.revision}:${sourceKey}` ``） |
| `templateRules[].templateId` | 模板 ID，被 `providerRules[].templateId` 引用 |
| `providerRules[].providerId` | 厂商 ID；`account:` 前缀 = 账号型（access.type=`zhipu-account`） |
| `config.access.type` | `api-key` / `zhipu-coding-plan-api-key`（`provider-data-schema.ts:32`）/ `zhipu-account`（`provider-data-schema.ts:43`） |
| `config.api.type` | `anthropic-messages` / `openai-chat-completions` / `openai-responses`（`provider-data-schema.ts:4-8`）★ **这个枚举是 `apiTypeMatch` 的取值域** |
| `config.api.baseUrl` | ★ **这个值是 `baseUrlMatch` 的匹配对象** |
| `config.builtinModelIds` | 该厂商内置的模型 ID 列表（有序） |

> **修订说明（E8 / E10）**：`schemaVersion` 的 `z.literal` 在 **`:27`**（原写 `:28`，实为 `revision` 定义行）；`config.access.type` 的取值域分居 **L32（`z.enum`）与 L43（`z.literal("zhipu-account")`）** 两处（原写 `:37`，实为 `completeApiKeyAccessDataSchema` 起点）。

### 9.2 片段 1：厂商模板 + 账号型厂商（Z.AI Coding Plan）

`zcode-builtin.json:7-29`（templateRules[0]，`templateId` 在 L8）：

```json
{
  "templateId": "zai-api",
  "templateNameMap": {
    "zh-CN": "Z.ai Coding Plan",
    "en-US": "Z.ai Coding Plan"
  },
  "config": {
    "access": {
      "type": "zhipu-coding-plan-api-key",
      "apiKeyManagementUrl": "https://z.ai/manage-apikey/apikey-list"
    },
    "api": {
      "type": "anthropic-messages",
      "baseUrl": "https://api.z.ai/api/anthropic"
    },
    "builtinModelIds": ["GLM-5.3", "GLM-5.3-Flash"],
    "logo": { "type": "builtin", "key": "zai" }
  }
}
```

`zcode-builtin.json`（providerRules[0]）：

```json
{
  "providerId": "account:zai-individual-coding-plan",
  "providerName": "Z.AI Individual Coding Plan",
  "config": {
    "group": "zai-family",
    "builtinModelIds": ["GLM-5.3", "GLM-5.3-Flash"],
    "access": {
      "type": "zhipu-account",
      "mode": "individual-coding-plan",
      "accountType": "zai"
    },
    "api": {
      "type": "anthropic-messages",
      "baseUrl": "https://api.z.ai/api/anthropic"
    },
    "logo": { "type": "builtin", "key": "zai" }
  }
}
```

> 字段含义：`group: "zai-family"` 参与 `resolveProviderOrder` 的排序分组（`resolver.ts:355-376`，family 排最前）；`access.type=zhipu-account` 意味着 API Key 由账号服务在请求期注入（`runner.ts:163-189` 的 `requestAuth` 逻辑），配置里**不存 Key**（`rule-data-schema.ts:115-123` 甚至用 `superRefine` 禁止个人层给 `account:` Provider 写 access）。
> 注意 `access` 在完整 schema 里是 discriminated union（稀疏版 **`provider-data-schema.ts:55-58`**，完整版 **`:59-62`**），`zhipu-account` 分支的 `entitled` 字段是**运行时权益**而非静态配置——所以 `builtinProviderConfigRuleSchema` 允许它缺省，由 `resolver.ts:250` 判定 `accessEntitled`。
> **修订说明（E10）**：原草稿此处引用 `provider-data-schema.ts:70-73`，实为 `providerApiDataSchema` 尾部；discriminatedUnion 的正确位置是 **L55-58 / L59-62**。

### 9.3 片段 2：**同一个模型、不同站点 → 完全不同的参数标准**（本报告最核心的证据）

**场景 A：`deepseek-v4-pro` 走 DeepSeek 官方站点（openai-responses）**

`zcode-builtin.json` providerSiteRules：

```json
{
  "modelMatch": "deepseek-v4-pro",
  "apiTypeMatch": "openai-responses",
  "baseUrlMatch": "https://api\\.deepseek\\.com(?:/.*)?",
  "config": {
    "properties": { "supportsJsonSchemaOutput": true },
    "optionSpecs": {
      "reasoningLevel": {
        "map": "{\n  \"reasoning\": {\n    \"effort\": reasoningLevel == \"disabled\" ? \"none\" : reasoningLevel\n  }\n}"
      }
    }
  }
}
```
→ 线格式：`{"reasoning": {"effort": "none" | <level>}}`

**场景 B：`deepseek-v4.1-flash` 走 OpenRouter（openai-chat-completions）**

`zcode-builtin.json` providerSiteRules：

```json
{
  "modelMatch": ".*deepseek-v4[.-]1-flash(?:[.\\-:/\\[].*)?",
  "apiTypeMatch": "openai-chat-completions",
  "baseUrlMatch": "https://openrouter\\.ai/api(?:/v1)?/?",
  "config": {
    "optionSpecs": {
      "reasoningLevel": {
        "map": "reasoningLevel == \"disabled\"\n  ? {\n      \"reasoning\": {\n        \"enabled\": false\n      }\n    }\n  : {\n      \"reasoning\": {\n        \"effort\": reasoningLevel\n      }\n    }"
      }
    }
  }
}
```
→ 线格式：关闭时 `{"reasoning": {"enabled": false}}`，开启时 `{"reasoning": {"effort": <level>}}`。**同一个语义，关闭用的字段名都不一样。**
> 这条 map 即 §6.2 类别 G-3（原草稿 §6.2 分类表漏列的那一条）。

**场景 C：`deepseek-v4-pro` 走 OpenRouter 的 anthropic-messages 入口**

`zcode-builtin.json` providerSiteRules（OpenRouter 兜底规则，`modelMatch` 用字符类覆盖多厂商）：
```json
{
  "modelMatch": ".*(?:glm-|deepseek-|kimi-k2|qwen|mimo-).*",
  "apiTypeMatch": "anthropic-messages",
  "baseUrlMatch": "https://openrouter\\.ai/api(?:/v1)?/?",
  "config": {
    "optionSpecs": {
      "reasoningLevel": {
        "map": "reasoningLevel == \"disabled\" || reasoningLevel == \"none\"\n  ? {\n      \"thinking\": {\n        \"type\": \"disabled\"\n      }\n    }\n  : {\n      \"thinking\": {\n        \"type\": \"adaptive\"\n      },\n      \"output_config\": {\n        \"effort\": reasoningLevel == \"enabled\" ? \"high\" : reasoningLevel\n      }\n    }"
      }
    }
  }
}
```
→ 线格式：`thinking.type` + `output_config.effort`，且 `enabled` → `"high"`。

> **三个场景，同一族模型，三种完全不同的字段结构。这就是 ZCode 要解决的问题，也是我们网关的核心痛点。**

### 9.4 片段 3：`maxOutputTokens` 的三种方言

```json
// anthropic-messages 兜底（modelApiRules，zcode-builtin.json:2503）
{ "modelMatch": ".*", "apiTypeMatch": "anthropic-messages",
  "config": { "optionSpecs": { "maxOutputTokens": { "map": "{'max_tokens': maxOutputTokens}" } } } }

// openai-chat-completions 兜底（zcode-builtin.json:2517）
{ "modelMatch": ".*", "apiTypeMatch": "openai-chat-completions",
  "config": { "optionSpecs": { "maxOutputTokens": { "map": "{'max_completion_tokens': maxOutputTokens}" } } } }

// openai-responses 兜底（zcode-builtin.json:2531）
{ "modelMatch": ".*", "apiTypeMatch": "openai-responses",
  "config": { "optionSpecs": { "maxOutputTokens": { "map": "{'max_output_tokens': maxOutputTokens}" } } } }
```

> **这三条规则是整个机制最直白的价值证明**：`max_tokens` vs `max_completion_tokens` vs `max_output_tokens`，ZCode 用三行声明式数据解决，而不是三处 `if apiType == ...`。
> 另外注意 `providerSiteRules` 里站点级规则会**覆盖**这三条兜底（例如 opencode 站点重新声明 `{"max_tokens": maxOutputTokens}` + `max: 131072`），体现优先级链的作用。

**同组的 reasoning 兜底（补全，见 §6.2 类别 G-2）**：

```json
// openai-responses 兜底 reasoning map（zcode-builtin.json:2528）★本次补全
{ "modelMatch": ".*", "apiTypeMatch": "openai-responses",
  "config": { "optionSpecs": { "reasoningLevel": {
    "map": "{\n  \"reasoning\": {\n    \"effort\": reasoningLevel == \"disabled\" ? \"none\" : reasoningLevel == \"enabled\" ? \"high\" : reasoningLevel\n  }\n}"
  } } } }
```

> 原草稿 §9.4 只列了 maxOutputTokens 的 3 条协议兜底，**未列 reasoning 的 openai-responses 兜底**。补上后，"3 种协议各有 reasoning 兜底"这一叙述才完整：anthropic（`:2500`）、chat-completions（`:2514`）、responses（`:2528`）。

### 9.5 片段 4：默认兜底规则（`modelRules` 的 `.*`）

`zcode-builtin.json` modelRules（catch-all）：

```json
{
  "modelMatch": ".*",
  "config": {
    "enabled": true,
    "properties": {
      "contextWindow": 200000,
      "inputFormat": {
        "supportsText": true, "supportsImage": false, "supportsVideo": false,
        "supportsAudio": false, "supportsPdf": false
      },
      "outputFormat": { "supportsText": true },
      "supportsToolCall": true,
      "supportsJsonSchemaOutput": false,
      "supportsNativeWebSearch": false,
      "supportsMidConversationSystem": false,
      "requiresMfjsToolSchema": false
    },
    "optionSpecs": {
      "maxOutputTokens": { "max": 32000 },
      "reasoningLevel": { "values": ["disabled", "enabled"], "map": "{}" }
    }
  }
}
```

> **这是"未知模型的保守默认值"**：`enabled: true`（默认可用）、`supportsJsonSchemaOutput: false`（默认不信）、`maxOutputTokens.max: 32000`（保守上限）、`reasoningLevel.map: "{}"`（**不注入任何推理字段**）。同时 `values: ["disabled","enabled"]` 定义了**全局默认档位词表**。
> 注意 `properties` 全部必填——这就是为什么 `resolver.ts:271` 的 `validateComplete` 能成功：catch-all 规则补齐了所有叶子。**这是"稀疏配置层 + 兜底规则 = 完整配置"的落地方式**，非常值得借鉴。

---

## 10. 端到端链路：从"用户选模型 + 传参"到"发往厂商的请求体"

### 10.1 完整时序（带 file:line）

```
【阶段 0】启动期：配置加载
  config/provider/zcode-builtin.json
    → decodeZCodeBuiltinRelease()                  zcode-builtin-release.ts:38-57
        ├─ releaseSchema.parse (schemaVersion/revision)     :39
        ├─ parseZCodeBuiltinProviderConfigRules             :40
        └─ parseZCodeBuiltinModelConfigRules                :54
              └─ builtinModelConfigRulesSchema.parse        schema.ts:79
                    └─ optionMapSchema.superRefine
                          └─ compileModelOptionMap()  ★DSL 语法在此一次性验证  shared/model-config.ts:11
        └─ ④ 拒绝已退役 Provider builtin:zapi               :43-47

【阶段 1】启动期：规则合成 + 完整化
  ProviderConfigResolver.resolve()                   resolver.ts:183
    ├─ ModelConfigRules.composeEffective(builtin, personal)   model-config.ts:379
    ├─ 每个 provider：template.overlay(concrete)              resolver.ts:196
    └─ 每个 (provider, model)：
          effectiveModelRules.resolve({providerId, templateId,
              modelId, apiType, baseUrl})                    resolver.ts:257
            └─ 6 类规则按序 overlay → ModelConfig               model-config.ts:387-423
          zcodeBuiltinModelRules.resolve({...})               resolver.ts:264-270  ★第 2 次 resolve（M6）
          createRegistryModelConfig(config, path)
            └─ config.validateComplete(path)                   model-config.ts:324
                  └─ validateConfigSchema(complete*, ...)      schema-validation.ts:5
          executable = providerExecutable && enabled && !issues resolver.ts:279
    → registryProviders: Provider[]                    resolver.ts:325-333
    → ProviderRegistry.replace(providers, reason)      registry.ts:94

【阶段 2】用户选模型（UI）
  ProviderRegistry.validateSelection(selection)        registry.ts:74
    └─ validateModelSelectionOptions(model, selection) registry.ts:129
          reasoningSpec.values.includes(reasoningLevel) registry.ts:148
    → ModelSelection {
        providerId, modelId,
        options: { reasoningLevel: "high" }            shared/model-selection.ts:4-15
      }

【阶段 3】创建 Model 实例（每 (provider,model) 一次）
  AiSdkModelAdapter.createModel(options)               runner.ts:138
    └─ this.execution.bindModel({
         providerId, modelId, providerConfig,
         supportsJsonSchemaOutput,
         optionSpecs: options.modelConfig.optionSpecs  runner.ts:144   ★ 两个 map 字符串在此进入
       })
       └─ AiSdkModelExecution.bindModel(input)          model-execution.ts:176
            ├─ captureModelSnapshot(input)              model-execution.ts:196
            │    └─ 冻结 baseURL / headers / apiKey / providerOptions
            └─ compileModelOptionMaps(input.optionSpecs)  model-execution.ts:187
                 └─ compileModelOptionMap(map, "reasoningLevel")  option-maps.ts:21
                 └─ compileModelOptionMap(map, "maxOutputTokens") option-maps.ts:22
                       → CompiledModelOptionMaps { apply(body, values) }

【阶段 4】发请求（每次请求）
  Model.streamText(request) / generateText(request)     contracts/model/model.ts:44
    → runner.ts toLegacyRequest(request)               runner.ts:155
        maxOutputTokens: request.options.maxOutputTokens   runner.ts:195
        + 推理遥测（requestedLevel 在 L205）                runner.ts:197-209
    → resolveForRequest(legacyRequest, optionValues)   runner.ts:223
        requireMaxOutputTokens(optionValues)           runner.ts:331  ★ undefined 直接抛错
        boundResolution.resolveRequest({ options: { maxOutputTokens,
                                    reasoningLevel } })  runner.ts:232-238
          └─ AiSdkModelExecution.resolveSnapshot(...)   model-execution.ts:225
              └─ createFactory(..., optionMaps, optionValues, ...)  model-execution.ts:235
                   └─ createModelOptionMapFetch({
                        capture, fetch,
                        maps: optionMaps,       model-execution.ts:273
                        values: optionValues }) model-execution.ts:276
                        ↓ 作为 AI SDK 的 fetch 注入
                      createOpenAICompatible({ fetch: optionFetch, ... }) model-execution.ts:307
                      createOpenAI({ fetch: createOpenAIResponsesJsonCompatFetch(optionFetch) }) model-execution.ts:286
                      createAnthropic({ fetch: createAnthropicCompatFetch(optionFetch) }) model-execution.ts:296

【阶段 5】出站拦截：唯一注入点  ★★★
  AI SDK 序列化 body → 调用 optionFetch(request, init)
    createModelOptionMapFetch 的返回函数                model-option-map-fetch.ts:19-30
      ├─ readRequestBody(request, init)                :20 / :33
      │    取不到 body 文本（非 Request 且无 init.body）→ 静默透传   :21 / :44
      │    有 body 但非 string → 直接抛错（fail-closed）  :40-42
      ├─ parseJsonObject(bodyText)                     :22 / :47
      ├─ input.maps.apply(body, input.values)          :23   ★★★ 补丁在此落地
      │    └─ CompiledModelOptionMaps.apply            option-maps.ts:24-32
      │         ├─ reasoningLevel undefined → 抛错      option-maps.ts:26-28
      │         ├─ optionPatch("reasoningLevel", prog, "high")
      │         │    └─ prog.evaluate("high")           compiler.ts:29 → evaluator.ts:9
      │         │         → {"output_config":{"effort":"high"},
      │         │            "thinking":{"type":"adaptive"}}
      │         ├─ optionPatch("maxOutputTokens", prog, 8192)
      │         │    → {"max_tokens": 8192}
      │         └─ applyOrderedJsonMergePatches(body, patches)  merge-patch.ts:13
      │              ├─ collectWrittenPaths(patch1) → [["output_config","effort"],["thinking","type"]]
      │              ├─ collectWrittenPaths(patch2) → [["max_tokens"]]
      │              ├─ pathsOverlap 检查 → 无冲突             :22
      │              └─ mergeObject(body, patch) 两次           :30 / :63
      ├─ capture.body = patched                        :24（供调试/遥测）
      ├─ JSON.stringify(patched)                       :25
      └─ 用新 body 重新构造 Request 并转发              :26-29

【阶段 6】后续 fetch 链
  optionFetch
    → createProviderBusinessErrorFetch（业务错误识别）   model-execution.ts:266
        → createOfficialCodingPlanGatewayFetch（官方套餐走平台网关）  model-execution.ts:517
            → createNetworkProxyFetch（用户 HTTP 代理）    model-execution.ts:508
                → globalThis.fetch → 厂商
```

> **注**：以上链路只覆盖 **option map 归一化轨**。`temperature` / `topP` / `topK` / 惩罚项 / `stopSequences` / `seed` **不在此链路中**——它们在阶段 4 由 `runner-options.ts:73-79` 直接写进 AI SDK 的参数对象，随后由 SDK 自行序列化进 body，**不经过阶段 5 的补丁逻辑**（见 §4.5）。

### 10.2 关键设计点（这条链路上最值得学的）

1. **注入点在 fetch 拦截器，而不是业务代码**（`model-option-map-fetch.ts:19`）。
   > 意义：**与 SDK / 协议无关**。无论 AI SDK 内部怎么构造 body（OpenAI Responses / Anthropic Messages / OpenAI Compatible 三种形态），补丁都在最后一跳统一生效。这就是它能同时覆盖 3 种协议的根本原因。
   > 代价：每次请求多一次 `JSON.parse` + `JSON.stringify`（`model-option-map-fetch.ts:22`、`:25`）。

2. **fail-closed 而非 fail-open**（`model-option-map-fetch.ts:38-42`）：
   ```ts
   // Option Map 是 reasoning/max-output 的唯一请求字段权威。若 SDK 改成非文本 Body 却静默
   // 跳过 Patch，请求仍会发出但丢失两个 Option；因此有 Body 时必须 fail-closed。
   if (init?.body !== undefined && init.body !== null) {
     throw new Error("Model option maps require a JSON text request body.");
   }
   ```
   > 注释写得非常好：**如果 patch 静默失效，请求还是会成功发出（只是少了两个参数）**——这种 bug 极难发现。所以宁可让请求失败。这是"静默降级比报错更危险"的经典体现，我们网关应该照抄这个态度。

   > **修订说明（E18）**：原草稿把这一条写成"**fail-closed 而非 fail-open**"的**无条件断言**，属绝对化。按 `model-option-map-fetch.ts:33-45` 的完整实现：
   > - `:37` 若 `init.body` 是 string → 直接返回该文本（正常路径）；
   > - `:40-42` 若 `init.body` **有值但不是 string** → **抛错（fail-closed）**；
   > - `:43` 若 `request instanceof Request` → 从 Request 克隆读出文本；
   > - `:44` 否则（既无 `init.body`，`request` 也不是 `Request` 对象）→ **返回 `undefined`**。
   >
   > 而调用方 `:21` 是 `if (bodyText === undefined) return input.fetch(request, init);` —— **取不到 body 文本时，会静默跳过 patch 直接转发**。
   >
   > 正确表述：**对「有 body 但非文本」fail-closed；对「取不到 body 文本」仍会静默透传。** fail-closed 的覆盖面比原草稿描述的要窄。

3. **`rawRequestBodyCapture` 把补丁后的 body 暴露给调试链路**（`model-option-map-fetch.ts:24`、`model-execution.ts:234`），便于"我明明配了参数，为什么没生效"的排查。

4. **`assertSameBoundModel`**（`runner.ts:230`）：每次请求都校验"当前 Model 绑定没被热更新换掉"，保证一个 Model 实例的 provider 事实（endpoint/协议/API Key）在整个生命周期内冻结（注释 `model-execution.ts:232-233`）。

---

## 11. 对照我们网关的借鉴评估

### 11.1 我们的现状（已读代码确认）

| 项 | 我们的实现 | 位置 |
|---|---|---|
| 参数配置载体 | `SystemModel.params: dict[str, Any]`（开放 dict） | `model_gateway/config/schemas.py:166` |
| 已知键校验 | `PARAM_RANGES` 做数值范围校验，未知键放行 | `model_gateway/config/schemas.py:169-190` |
| 注入实现 | `apply_model_params(body, params)`：字段级，`body.get(k) is None` 才注入 | `model_gateway/core/ir.py:58-70` |
| 优先级 | 工具传参 > 网关设置 > 厂商内置（三级） | `model_gateway/core/ir.py:59-62` |
| 注入时机 | `Scheduler._out_body`，**仅 `endpoint == "chat"`** | `model_gateway/core/scheduler.py:223-232` |
| 推理参数 | 独立模型：`ReasoningSpec{enabled, effort}` + `merge_reasoning` + `lift_reasoning_from_body` + `inject_reasoning_into_body` | `model_gateway/core/ir.py:28-111` |
| 推理线格式 | **硬编码单一方言**：`thinking: {type: enabled\|disabled}` + `reasoning_effort` | `model_gateway/core/ir.py:94-111` |
| 层级 | 系统模型级 `params` + 资源级 `resource_reasoning`（两级） | `model_gateway/core/scheduler.py:229-230` |

### 11.2 ZCode 强在哪（逐条对照）

> **⚠️ 本节已按核验报告校准（E4 / M5）。请先读下面这段，再看表。**

**校准说明：ZCode 的参数处理是双轨制**

| 参数 | ZCode 走哪条轨 | 与我们网关的对比 |
|---|---|---|
| `reasoningLevel` | option map 归一化轨（DSL + merge patch） | **我们确有差距**（见下表 #1 / #2 / #6 / #9） |
| `maxOutputTokens` | option map 归一化轨 | **我们确有差距**（同上） |
| `temperature` / `topP` / `topK` / `presencePenalty` / `frequencyPenalty` / `stopSequences` / `seed` | **直通透传轨**（`ModelRequestSettings` → `runner-options.ts:73-79`，**无厂商方言归一化**） | **两边同级**——都是 `body[k] = v` 式字段级写入，ZCode 并不比我们强 |

> **因此下表 #1 / #2 的"差距"只对 `reasoningLevel` 与 `maxOutputTokens` 这两个参数成立**，不可外推为"ZCode 的参数层整体强于我们"。原草稿未区分这两条轨，导致差距被夸大。

| # | ZCode 的做法 | 我们的差距 | 严重度 |
|---|---|---|---|
| 1 | **（仅限 reasoning / maxOutputTokens）** 参数注入是"请求体补丁"，不是"参数值覆盖"。可以一次写多个字段、嵌套结构、按条件改变字段集合 | 在这两个参数上，我们只能 `body[k] = v`，**无法表达"关闭时不发 effort"** 这类条件 | 🔴 高 |
| 2 | **（仅限 reasoning / maxOutputTokens）** 按 (模型 × 协议 × 站点) 三维匹配规则，同一模型不同厂商走不同 map | 我们这两个参数（含 `ReasoningSpec`）只挂在 `SystemModel` 上，**没有协议/站点维度**；`SystemModel` 有多个 resource 时无法区分 | 🔴 高 |
| 3 | **注入点在出站 fetch 层**，与 SDK/协议解耦，一处生效 | 我们在 `_out_body` 里手写，`endpoint` 分支处理 | 🟡 中 |
| 4 | **配置期就把 DSL 编译校验**，语法错误进不了配置文件 | 我们只有 `PARAM_RANGES` 数值校验，**没有语义校验**（比如"这个厂商根本不支持 `max_tokens`"检测不出来） | 🟡 中 |
| 5 | **分层覆盖 + 兜底规则**：稀疏规则层 + `.*` catch-all 补齐 → 完整配置 | 我们只有模型级 dict，**没有"从泛到专"的规则链** | 🟡 中 |
| 6 | **路径冲突守卫**：两个 option 写同一路径直接报错 | 无。我们 `apply_model_params` 和 `inject_reasoning_into_body` 可能互相覆盖（例如 params 里配了 `reasoning_effort`，又被 reasoning 注入覆盖）——**这是一个真实的现存 bug 风险**（`ir.py:68` vs `ir.py:111`） | 🔴 高 |
| 7 | **fail-closed**（限定：有 body 但非文本时抛错；取不到 body 文本时仍静默透传，见 §10.2-2） | 我们 `apply_model_params` 静默跳过（`if body.get(k) is None`），配置写错只会"参数不生效"，**无告警** | 🟡 中 |
| 8 | **能力位（properties）与参数（optionSpecs）走同一套规则表** | 我们 `SystemModel.params` 与能力声明分离 | 🟢 低 |
| 9 | **档位词表（values）与线格式（map）解耦**：UI 只认 values，map 只认线格式 | 我们 `ReasoningSpec.effort` 是 opaque 字符串，**没有词表概念**，UI/工具可以传任意值 | 🟡 中 |

### 11.3 ZCode 复杂在哪（要付的代价）

1. **规则表爆炸**：119 条 map、478 条规则、6212 行 JSON，其中大量重复（`{"reasoning_effort": reasoningLevel}` 重复 17 次）。**这是因为求值期上下文太窄**，只能靠配置期穷举。
2. **求值期几乎无表达力**：单标量输入 → 任何"依赖两个以上输入"的逻辑（如 `if thinking_enabled and max_tokens > 4096`）都表达不了。
3. **没有测试**：`packages/model-option-map/` 下**零测试文件**（已全库搜索 `*.test.ts` / `*.spec.ts`，该包无任何测试）。119 条 map 的正确性依赖人工与端到端验证。**这是它最大的工程缺陷**——DSL 这么核心的组件没有单元测试，说明维护者靠"配置是数据、改错了容易发现"来兜底。
4. **无版本化迁移的 DSL**：`schemaVersion: 1` 只保护外层结构，`map` 字符串一旦语义变更（如改掉变量名），所有历史配置同时失效。`legacy-reasoning-level.ts` 就是在打这个补丁——**但它的真实机制不是"别名映射表"，见下方 §11.3.1**。
5. **两层 patch 语义容易混淆**：配置层 overlay 是"后者覆盖前者、undefined=继承"，请求层 merge patch 是"null=删除、路径冲突报错"。两套规则，学习成本不低。
6. **引入了一门语言**：虽然禁止了函数调用和成员访问，但它仍是一门需要词法/语法/求值三件套的语言。**对只有 2 个参数的系统来说，这是一个偏重的选择。**
7. **参数处理被切成两轨，语义不统一**：`reasoningLevel` / `maxOutputTokens` 有方言归一化，其余参数直通。调用方必须知道"哪些参数享受方言归一化、哪些不享受"，这个边界在文档里没有集中说明（原草稿也没写清，本定稿 §4.5 补上）。

#### 11.3.1 【本次重写 M9 / E9】`legacy-reasoning-level.ts` 的真实机制

> **原草稿 §11.3 第 4 条的表述是**："`legacy-reasoning-level.ts` 就是在打这个补丁（用 `legacyReasoningLevelRenames` 硬编码旧档位别名 `off` / `nothink` → `disabled`）"。
> **这个描述把机制说反了一半**：它**不是**一张"`off`/`nothink` → `disabled` 的直接映射表"。

**真实机制**（`legacy-reasoning-level.ts:35-71`，文件共 72 行）：

1. `legacy-reasoning-level-renames.ts`（2218 字节）是一张 **`{ modelMatch, oldLevel }`** 表（≥10 条，`oldLevel ∈ {"off","nothink"}`），按 **`modelMatch` 精确匹配内置规则**（`:38-41`）。
2. 用这张表**重建一份新规则集**：把内置规则里 `values` 中的 `"disabled"` **替换成 `oldLevel`**（`:50-52`）——即 `disabled → "off"` / `"nothink"`，**方向是反向的**：
   ```ts
   values: values.map((value) => (value === "disabled" ? rename.oldLevel : value)),
   ```
3. 用**原规则引擎**重放匹配（`oldRules.resolve(...)`，`:64-70`），得到"**历史值域**"。
4. `:71` 判定：`values?.includes(oldLevel) ? "disabled" : undefined`。

**即**：不是"旧值 → 新值的映射表"，而是"**把当前规则集回滚成历史值域、再用同一引擎判定旧值是否曾合法**"的兼容层。

注释也明确了边界：
- `:12`："只为历史 Selection 恢复已知 Built-in 旧值域；**不迁移 Personal 配置或在执行层放宽校验**。"
- `:23-29`：特意排除"个人层声明过 `reasoningLevel` 的情况"（`personal && (...)` 即返回 `undefined`，不介入）。
- `:37`："必须是已裁决的原始无站点/无 API 限制规则；**新增同名站点规则不能误继承旧别名**。"

> **为什么这个细节重要**：它说明 ZCode 的兼容策略是"**复用同一套匹配引擎 + 回滚数据**"，而不是"**加一层 if-else 别名判断**"。后者会随规则增长而失控，前者天然继承了正则匹配、大小写归一、站点/API 覆盖等全部既有语义（`:63` 注释明说"不复制第二套匹配逻辑"）。**这是我们在做网关版本兼容时值得学的模式。**

**行号修正（E9）**：

| 原草稿引用 | 真实 |
|---|---|
| `13-60 \| resolveLegacyReasoningLevel` | **`13-72`** |
| `24 \| 只处理 "off" / "nothink"` | **`18`**（`if (oldLevel !== "off" && oldLevel !== "nothink") return undefined;`）；L24 是 `personal &&` |
| `:24` "使用它把 `off`/`nothink` 映射回 `disabled`" | renames 的 **import 在 L8**，**使用在 L38-41 与 L51** |
| `58-59 \| values?.includes(oldLevel) ? "disabled" : undefined` | **`71`** |

### 11.4 落地建议（具体、分级、可执行）

> 核心判断（**已按核验结果校准**）：**不建议照搬 DSL。建议借鉴「三层结构 + 补丁语义 + 冲突守卫 + fail-closed」，用纯声明式规则表实现——但表格必须覆盖 4 个语义（含布尔谓词），不能只有 3 个。**

#### 建议 1（🔴 最高优先级）：把「参数注入」升级为「声明式补丁表 + 冲突守卫」

**问题**：`apply_model_params` 与 `inject_reasoning_into_body` 各自写字段，互相不知道对方写了什么。当前 `params` 里若配了 `reasoning_effort`，`inject_reasoning_into_body` 会覆盖它（`ir.py:111` 无条件 `body["reasoning_effort"] = spec.effort`）。

**改法**：引入统一的补丁应用器，把"谁写了哪些路径"显式记录。

```python
# model_gateway/core/param_patch.py（新增）
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class NamedPatch:
    """一个语义源产出的请求体补丁。source 用于冲突报错定位。"""
    source: str          # "gateway_params" | "reasoning" | "vendor_builtin"
    patch: dict[str, Any]


class ParamConflictError(Exception):
    """两个语义源写入重叠路径 —— 与 ZCode merge-patch.ts:24 同语义。"""

def _collect_paths(patch: dict, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """与 ZCode merge-patch.ts:35-49 等价：非空 dict 下钻，其余为叶子。"""
    out: list[tuple[str, ...]] = []
    for k, v in patch.items():
        path = prefix + (k,)
        if isinstance(v, dict) and v:
            out.extend(_collect_paths(v, path))
        else:
            out.append(path)
    return out

def _overlap(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """前缀关系即冲突（ZCode merge-patch.ts:51-57）。"""
    return a[:min(len(a), len(b))] == b[:min(len(a), len(b))]

def apply_patches(body: dict, patches: list[NamedPatch]) -> dict:
    """有序应用 JSON Merge Patch（RFC 7386）+ 跨源路径冲突守卫。"""
    owned: list[tuple[str, tuple[str, ...]]] = []
    for np in patches:
        for path in _collect_paths(np.patch):
            for owner, owned_path in owned:
                if _overlap(owned_path, path):
                    raise ParamConflictError(
                        f"参数补丁路径冲突 $.{'.'.join(path)}：{owner} 与 {np.source}"
                    )
            owned.append((np.source, path))
        body = _merge_object(body, np.patch)
    return body

def _merge_object(target: dict, patch: dict) -> dict:
    """RFC 7386：null 删除 / dict 递归 / 其余整体替换。"""
    result = dict(target)
    for k, v in patch.items():
        if v is None:
            result.pop(k, None)
        elif isinstance(v, dict):
            base = result.get(k)
            result[k] = _merge_object(base if isinstance(base, dict) else {}, v)
        else:
            result[k] = v
    return result
```

然后把 `_out_body` 改成（`model_gateway/core/scheduler.py:223`）：

```python
def _out_body(self, ir: IRRequest, resource) -> dict:
    body = dict(ir.body)
    body["model"] = resource.vendor_model
    patches: list[NamedPatch] = []
    if ir.endpoint == "chat":
        if gp := self.runtime.model_params.get(ir.system_model):
            patches.append(NamedPatch("gateway_params", gp))
        merged = merge_reasoning(ir.reasoning, self.runtime.resource_reasoning.get(resource.resource_id))
        if rp := reasoning_to_patch(merged, self.runtime.reasoning_dialect(resource)):
            patches.append(NamedPatch("reasoning", rp))
    return apply_patches(body, patches)
```

> **收益**：配置错误立刻 400 报错而不是静默产出畸形请求；`reasoning_effort` 被两边写的问题变成显式错误。

#### 建议 2（🔴 最高优先级）：为推理参数引入「方言表」（**不要引入 DSL**）

**问题**：`inject_reasoning_into_body` 硬编码了商汤/OpenAI 兼容口径（`ir.py:94-111`）。接新厂商必须改代码。

**改法**：把 ZCode 的 21 种 map **降维成纯数据表格**——用枚举 + 词表 + 布尔谓词表即可，无需表达式求值。

> **⚠️ 本次重写（E1）**：原草稿此处只给了 `effort_words`（单个 dict）**一个**数据结构，并声称"3 个语义用 3 个数据字段就能完全覆盖"。核验证明**这是不成立的**：
> - 实测 119 条 map 中有 **5 条（4.2%）** 越出"对象字面量 + 三元 + `==`"，用到 `||` / `&&` / `!=` / 链式三元 / `false` 字面量；
> - 归纳出的语义是 **4 个**而非 3 个——第 4 个是 **布尔谓词**（`{"enable_thinking": reasoningLevel == "enabled"}`、`reasoningLevel != "disabled" && reasoningLevel != "none"`），它需要的是"**目标字段 + 成员集合 + 正/负向**"三个概念，**不是"档位 → 词"的映射**，单个 `effort_words` dict **表达不了**；
> - 链式三元（`a ? x : b ? y : z`，4 条）是"词表翻译"的**多入口形式**（`disabled→none` 且 `enabled→high` 且其余透传），单个 dict 能表达，但必须显式承认它的存在，否则会误判所需表达力。

**修正后的数据结构**：

```python
# model_gateway/config/reasoning_dialect.py（新增）
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class ReasoningDialect(str, Enum):
    """实测归纳：ZCode 的 21 种 map 可归入 7 个结构模板（原草稿为 6 个，漏了 G-1 那一类）。"""
    # ① thinking.type = enabled|disabled，不配 effort
    ANTHROPIC_BINARY      = "anthropic_binary"
    # ② thinking.type = enabled|disabled + output_config.effort（disabled 时 effort 省略）
    ANTHROPIC_EFFORT      = "anthropic_effort"
    # ③ thinking.type = adaptive + output_config.effort（disabled 时只发 thinking）
    ANTHROPIC_ADAPTIVE    = "anthropic_adaptive"
    # ④ reasoning.effort（disabled → "none"；链式三元需 effort_words 配 3 项）
    OPENAI_RESPONSES      = "openai_responses"
    # ⑤ reasoning_effort 裸字段（低/中/高档位直接透传）
    OPENAI_CHAT_EFFORT    = "openai_chat_effort"
    # ⑥ enable_thinking 布尔（含 Qwen 的 enable_thinking 与 OpenRouter 的 reasoning.enabled）
    QWEN_BOOLEAN          = "qwen_boolean"
    # ⑦ 不注入（ZCode 的 map: "{}"，8 次）
    NONE                  = "none"


@dataclass(frozen=True)
class BooleanPredicate:
    """★语义④ 布尔谓词：目标字段 = (档位 ∈ 集合) 或 (档位 ∉ 集合)。

    对应 ZCode：
      {"enable_thinking": reasoningLevel == "enabled"}                    → in_set={"enabled"}
      {"reasoning": {"enabled": reasoningLevel == "enabled"}}             → in_set={"enabled"}
      {"enable_thinking": reasoningLevel != "disabled" && reasoningLevel != "none"}
                                                                          → in_set={"disabled","none"}, negated=True
    这是原草稿建议的单一 effort_words dict 覆盖不了的一类。
    """
    target: str                       # JSON 路径，如 "enable_thinking" / "reasoning.enabled"
    in_set: frozenset[str]            # 成员集合（档位词表）
    negated: bool = False             # True = "档位 ∉ 集合"（ZCode 的 != ... && != ... 写法）


@dataclass(frozen=True)
class ReasoningDialectSpec:
    """一个 (模型 × 协议 × 站点) 组合的完整推理参数方言描述。

    四个语义字段与 ZCode 的 4 类表达力一一对应：
      ① 键名映射        → max_tokens_field
      ② 档位词表翻译    → effort_words（含链式三元的"多入口"）
      ③ 字段集合条件化  → dialect（7 个模板）+ effort_words 中的 None（= 省略该字段）
      ④ 布尔谓词        → boolean_fields
    """
    dialect: ReasoningDialect
    levels: list[str]                                  # ← ZCode 的 values（档位词表）
    effort_words: dict[str, Optional[str]] = field(default_factory=dict)
    #   ↑ 语义②：语义档位 → 厂商词表；value 为 None 表示"该档位不写这个字段"（语义③）
    boolean_fields: list[BooleanPredicate] = field(default_factory=list)
    #   ↑ 语义④：布尔谓词目标字段（原草稿缺失，必须补）
    passthrough: bool = False                          # 未命中 effort_words 的档位是否原样透传
    max_tokens_field: str = "max_tokens"               # 语义①：maxOutputTokens 的键名
```

配合配置：

```yaml
# config.example.yaml 片段
system_models:
  # 例 1：DeepSeek 官方 responses —— 语义② + 链式三元（disabled→none, enabled→high, 其余透传）
  - name: deepseek-v4-pro
    params: { temperature: 0.6 }
    reasoning:
      dialect: openai_responses
      levels: [disabled, enabled, low, high, max]    # ← ZCode 的 values
      effort_words:                                  # ← 语义②：语义档位 → 厂商词表
        disabled: none
        enabled: high                                # 其余档位走 passthrough
      passthrough: true
      max_tokens_field: max_output_tokens            # ← 语义①

  # 例 2：Qwen —— 语义④ 布尔谓词（原草稿的 effort_words 覆盖不了这一例）
  - name: qwen3.5-plus
    reasoning:
      dialect: qwen_boolean
      levels: [disabled, enabled]
      boolean_fields:                                # ← 语义④：目标字段 + 成员集合 + 极性
        - target: enable_thinking
          in_set: [enabled]                          # reasoningLevel ∈ {enabled} → true

  # 例 3：openai-chat-completions 兜底 —— 语义④ 的"负向"写法（对应 :2514）
  - name: openai-chat-fallback
    reasoning:
      dialect: openai_chat_effort
      levels: [disabled, enabled, low, high, max]
      effort_words: { disabled: none, enabled: high }
      passthrough: true
      boolean_fields:
        - target: enable_thinking
          in_set: [disabled, none]
          negated: true                              # 档位 ∉ {disabled, none} → true
```

**关键论证：为什么不要 DSL？（数据已修正）**

用第 2.5 节的实测数据说话——ZCode 内置 119 条 map 里：

| 需要的表达力 | 实测占比 |
|---|---|
| 对象字面量 + 三元 + `==`（**不含** `\|\|`/`&&`/`!=`/链式三元/`false`） | **≈96%**（114 / 119） |
| 用到 `\|\|` / `&&` / `!=` / 链式三元 / `false` 的 map | **4.2%**（5 / 119） |
| 算术、比较、数组、`null` 删除 | **0%** |

> **修订说明（E1）**：原草稿此处写 `100%`，**被证伪**。那 5 条例外是：
> `:2514`（`||` + 两个 `!=` + `&&` + 两个链式三元）、`:2528`（链式三元）、`D-4` OpenRouter 兜底（`||` + 链式三元）、`D-1` 全局兜底（链式三元）、`deepseek-v4[.-]1-flash @ openrouter`（`false` 布尔字面量）。

而三元 + `==` 的全部用途，归纳下来是 **3 个主语义 + 1 个布尔谓词语义**：

1. **键名映射**（`max_tokens` / `max_completion_tokens` / `max_output_tokens`）→ 一个字符串字段（`max_tokens_field`）
2. **档位词表翻译**（`enabled`→`high`、`disabled`→`none`，含链式三元的"多入口"形式）→ 一个 dict（`effort_words`）
3. **字段集合条件化**（disabled 时不发 effort）→ 一个枚举（7 种结构模板）+ `effort_words` 中的 `None`
4. **布尔谓词**（档位 ∈ / ∉ 集合 → true/false）→ **一个 `boolean_fields` 列表**（`target` + `in_set` + `negated`）

**这 4 个语义用 4 个数据字段就能完全覆盖，不需要词法分析、语法分析、求值器。**

> **原草稿说"3 个语义用 3 个数据字段就能完全覆盖"——这一结论在修正后依然成立，但必须补上第 4 个语义与对应的 `boolean_fields` 结构。** 若按原草稿只实现 `effort_words`，遇到 Qwen 的 `{"enable_thinking": reasoningLevel == "enabled"}`（内置配置中出现 6 次）与 `:2514` 的负向谓词时会**无法表达**，只能退回硬编码——这正是我们要避免的结局。

> **结论（修正后仍然成立，且依据更硬）：引入 DSL 是过度设计。** ZCode 之所以用 DSL，是因为它要处理 **478 条规则 × 多站点 × 多协议**的组合爆炸，且必须支持"配置热更新不改代码"。我们网关的规模（系统模型数量级小、厂商数可控）用**声明式表格 + 枚举 + 布尔谓词表**性价比高得多——**代价是要多写一个 `boolean_fields` 字段，而不是多写一门语言**。
> **等规则真的膨胀到几百条、且非工程师需要改参数时，再考虑引入 DSL**——那时可以照抄 ZCode 的 `parser.ts` / `evaluator.ts`（**Apache-2.0 许可**下的 **867 行**实现，移植成本低）。
> ⚠️ **合规提示（E5）**：ZCode 采用 **Apache-2.0**（`LICENSE` 首行："Apache License, Version 2.0, January 2004"），仓库根另有 **1,975,825 字节**的 `THIRD-PARTY-NOTICES.md`。Apache-2.0 属宽松许可，移植可行，但**须遵守 Apache-2.0 §4**：保留 `LICENSE` 副本、保留 `NOTICE` 文件内容与版权声明、对修改过的文件标注变更。**不可删除或合并 NOTICE 内容。**（原草稿称"MIT/自有许可"，属事实错误。）

#### 建议 3（🟡 中优先级）：引入「站点/协议」维度的参数覆盖

**问题**：`SystemModel.params` 只按模型名查（`scheduler.py:229`）。但同一 `SystemModel` 下可能有多个 resource 走不同厂商（比如 GLM-4.6 同时接智谱官方和某个中转站），两者的参数标准可能不同。

**改法**：在 resource 级增加 `params_override`，形成四级优先级：

```
工具传参  >  resource.params_override  >  SystemModel.params  >  厂商内置
             （新增，最贴近实际出站目标）      （网关级默认）        （不注入）
```

理由：ZCode 的 `providerSiteRules`（按 `baseUrlMatch` 匹配，52 条规则）证明了**"站点"是一个真实存在的、必要的区分维度**——`api.deepseek.com` 和 `openrouter.ai` 上的 DeepSeek 就是两套标准。

#### 建议 4（🟡 中优先级）：把「静默跳过」改为「配置期校验 + 运行期告警」

ZCode 的做法分两层：
- **配置期**：`optionMapSchema.superRefine(编译)` → 语法错误进不了配置文件
- **运行期**：`readRequestBody` 非文本 body → 直接抛错（fail-closed；注意其覆盖面有限，见 §10.2-2）

**我们的改法**：
1. **配置期**：把 `PARAM_RANGES` 扩展成 `PARAM_SPEC`，加"厂商/协议支持矩阵"校验。例如：
   ```python
   PARAM_SPEC = {
       "max_tokens":           {"aliases": {"openai-responses": "max_output_tokens",
                                            "anthropic-messages": "max_tokens"}},
       "max_completion_tokens": {"aliases": {"openai-chat-completions": "max_completion_tokens"}},
       "reasoning_effort":     {"requires": {"thinking"}},   # 配对约束（我们已实测过商汤约束）
   }
   ```
   加载时校验：`params` 里的键是否被该 `SystemModel` 下所有 resource 的协议支持；不支持的**启动即报错**（而不是等请求 400）。
2. **运行期**：`apply_model_params` 若发现 `params` 里的键被上游显式 `null` 掉，记一条 WARN（当前 `ir.py:68` 的 `body.get(k) is None` 会把显式 `null` 和"缺省"当同一件事——ZCode 的 `mergeObject` 把 `null` 定义为**删除**，语义更清晰）。

#### 建议 5（🟢 低优先级，但值得做）：借鉴 `properties` 与 `optionSpecs` 分离

ZCode 把「能力位」（`supportsToolCall` / `supportsJsonSchemaOutput` / `contextWindow` / `inputFormat`）和「参数映射」（`optionSpecs`）分成两个字段，但**走同一套规则表和优先级链**。

我们可以照做：`SystemModel` 增加 `capabilities: dict`（如 `supports_reasoning: bool`、`max_context: int`、`supports_json_schema: bool`），与 `params` 并列、同样支持 resource 级覆盖。收益：**"这个模型不支持 json_schema，别给它发 response_format"这类判断有地方可查**，而不是散落在适配器代码里。

#### 建议 6（🟢 低优先级）：补一个「补丁可观测性」出口

ZCode 的 `rawRequestBodyCapture`（`model-option-map-fetch.ts:9-11`、`:24`）把补丁后的 body 留给调试链路。我们可以在 `_out_body` 返回时（`scheduler.py:223`）把 `(ir.system_model, resource.rid, patches_applied, final_body)` 写进已有的 `events` 流（`scheduler.py:246` 附近已有 `_emit_switch` 模式），便于排查"我配的参数为什么没生效"。

### 11.5 明确**不建议**借鉴的部分

| ZCode 的做法 | 为什么不适合我们 |
|---|---|
| 自研 DSL（tokenizer + parser + evaluator） | 实测表达力需求只有 4 个语义（含 1 个布尔谓词）；引入语言 = 引入词法/语法/求值/错误定位/版本迁移的长期维护成本。**除非规则数量增长 10 倍以上。** |
| 求值期只用单标量输入 | 我们完全可以用 `context: dict`（含 `api_type` / `vendor` / `model` / `user_options`），比 ZCode 更灵活且不需要穷举规则 |
| 478 条规则的穷举式配置 | 那是"求值期无上下文"的补偿措施。我们有了上下文就不需要这么多规则 |
| 用 `templateId + modelId` 精确匹配 244 条 | 我们的模型数量级不支持这种写法；用前缀/正则匹配 + 少量精确覆盖即可 |
| `map: "{}"` 表示"不注入" | 我们直接不配 `params` 就行（`apply_model_params` 已经 `if not params: return body`，`ir.py:65-66`），语义更直白 |
| 一次注入 4 个方言字段（`zcode-builtin.json:2514`） | 这是"不知道对面是谁"的防御式广播，**会把不确定性推给下游、放大 400 风险**。我们应该精确匹配 resource 的协议，只发一种 |
| 参数处理分两轨、边界不集中说明 | 调用方需要知道"哪些参数享受方言归一化"。我们应**在配置文档里显式声明每个参数的归属轨道** |

### 11.6 优先级排序的行动清单

| 顺序 | 动作 | 产出 | 风险 |
|---|---|---|---|
| 1 | 新增 `core/param_patch.py`：`NamedPatch` + `apply_patches` + 冲突守卫 | 消除 params/reasoning 互相覆盖的现存隐患 | 低（纯新增，`_out_body` 改 3 行） |
| 2 | 推理方言表：`ReasoningDialect` 枚举 + `effort_words` + **`boolean_fields`** 三件套，替换 `inject_reasoning_into_body` 的硬编码 | 接新厂商只改 YAML | 中（需回归全部已支持厂商，但现有 E2E 测试可覆盖） |
| 3 | `resource.params_override` 四级优先级 | 同模型多厂商可区分 | 中（schema 变更 + 文档） |
| 4 | `PARAM_SPEC` 配置期支持矩阵校验 + 启动即报错 | 配置错误前移 | 低 |
| 5 | `capabilities` 字段与 `params` 并列 | 能力判断集中化 | 低 |
| 6 | 补丁可观测性事件 | 可排查性 | 低 |

> **决策结论（对"我们网关要不要引入 DSL"）**：**不引入。** 核验修正后的数据显示，ZCode 的 119 条 map 中有 **≈96%** 落在"对象字面量 + 三元 + `==`"，归纳为 **3 个主语义 + 1 个布尔谓词语义**；后 4 者用 `dialect` 枚举 + `effort_words` + `boolean_fields` + `max_tokens_field` 四个纯数据字段即可完全覆盖。**引入 DSL 是过度设计；但"3 个字段就够"的原始结论也必须修正为"4 个字段"——这正是本次核验最关键的产出。**

---

## 12. 未验证 / 存疑事项（诚实清单）

> **本节已按核验报告第五节更新**：原 U1–U7 中已核实掉的部分，已移入正文并在下表中标注去处；无法核实/部分核实的条目**保留**。

### 12.1 仍无法核实 / 存疑

| # | 条目 | 状态 | 说明 |
|---|---|---|---|
| 1 | `packages/model-option-map/` **无任何测试** | **已核实（结论成立）** | 全库仅 **4 个**测试文件（`packages/{ui,services}/test/`），**均与该包无关**；`providerConfigMigration.test.ts` 中 `optionSpecs` / `reasoningLevel` / `model-option-map` **0 命中**。**因此 DSL 的边界行为（如 `1 == "1"`、`pathsOverlap` 的极端情况）我依据源码推断，未经测试验证。** <br>⚠️ **风险提示：`model-option-map` 零测试，意味着任何"照抄它的语义"的实现都没有参考测试集可对齐——这是本报告最重要的风险提示。** |
| 2 | `invalid-reasoning-mapping` / `invalid-pattern` 两个错误码无生产点 | **部分核实** | 可确认：全仓 `.ts` 中无生产点（仅 `config-overlay.ts:8-9` 声明 + `dist/config-overlay.d.ts:2` 编译产物）。**无法确认**是"历史遗留"还是"预留未实现"——**原设计意图不可得**。本文档相关表述均保留"推测"字样。 |
| 3 | `config/provider/zcode-builtin.json` 的 `revision: 30` 对应的实际发布节奏 | **无法核实** | 需要远端 Release 服务的历史数据，本地不可得。 |
| 4 | `providerConfigRules` 里 `enabled` 与 `modelConfigRules` 里 `enabled` 的优先级关系 | **未逐路径验证** | `resolver.ts:221` 对 `zhipu-account` 类型强制 `enabled=true`（"账号不再支持总禁用"）这一分支已理解，但两个 `enabled` 的完整交互未逐路径验证。 |
| 5 | 性能数据未实测 | **无法核实** | `compiler.ts` 的三级缓存、以及 fetch 层每请求 `parse+stringify` 的开销，只做了源码层面的定性分析，**没有 benchmark**。定性结论（`model-option-map-fetch.ts:22/25` 每请求各一次）成立。 |
| 6 | `dist/` 编译产物与 `src/` 是否完全同步 | **部分核实** | 抽查 `packages/provider/dist/config-overlay.d.ts:2` 与 `src/config-overlay.ts:1-14` **一致** ✅；但**未逐文件比对** `packages/model-option-map/dist/*.js` 与 `src/*.ts`。本文档引用 dist 路径仅 1 处，影响面小。 |
| 7 | §10.1 阶段 6 fetch 链的**运行时**行为 | **部分核实** | 调用点行号已核对正确（`model-execution.ts:508` / `:517` / `:266`）✅；但**未读这三个 fetch 工厂的实现**，故"官方套餐走平台网关 / 用户 HTTP 代理"的语义描述无法逐行验证。 |
| 8 | `packages/shared/src/model-execution.ts` 是否与参数处理相关 | **未核实** | 该文件存在（24 行），本文档未引用，核验时也未展开（超出范围）。 |

### 12.2 已在本次修订中核实并移入正文的条目

> 以下条目原属"未验证/存疑"，核验报告已给出可核实证据，现已在正文中给出结论。

| 原编号 | 原条目 | 结论 | 现位置 |
|---|---|---|---|
| 原 §12.3 | `legacyReasoningLevelRenames` 的具体内容未读 | **已读透**：`legacy-reasoning-level-renames.ts`（2218 字节）是 `{modelMatch, oldLevel}` 表（≥10 条，`oldLevel ∈ {"off","nothink"}`）；机制为"**回滚值域 + 同引擎重放**"，非别名映射表 | **§11.3.1**（含完整机制描述与 4 步流程） |
| 原 §12.4（后半） | `zcode-builtin-remote-synchronizer.ts` 的远端同步/回落策略未读实现细节 | **已读透**：六态结果、租约（30s）、指数退避（60s × 2^(n-1)，封顶 1h）、成功间隔 1h、三种跳过原因、"整份替换 + bundled/active 双候选回落" | **§8.4** |
| 原 §12.5 | `manual-provider-model` 分支的边界情况（手动规则只改 `enabled` 时系统映射是否保留）未逐路径验证 | **答案：保留**。`clearManualModelConfig` 只清"手动白名单内的叶子"，`maxOutputTokens.map` 等系统叶子不受影响；且 `effectiveBuiltinConfig` 单独留存供 UI 对比 | **§5.4** |
| 原 §12.6 | ZCode 是否有其他参数（temperature 等）的处理机制；`runner-options.ts` 未通读 | **答案：有第二条路径**。`ModelRequestSettings` → `runner-options.ts:73-79` 逐字段直通透传 `temperature`/`topP`/`topK`/惩罚项/`stopSequences`/`seed`，**无厂商方言归一化** | **§4.5**（并已据此校准 §11.2、修正 §14） |

---

## 13. 证据附录（file:line 清单）

### 13.1 `packages/model-option-map/src/`（核心，**867 行**）

> **修订说明（E21）**：原写"866 行"，`wc -l packages/model-option-map/src/*.ts` 实测为 **867**。
> 分文件行数：`compiler.ts` 92 / `evaluator.ts` 214 / `index.ts` 5 / `merge-patch.ts` 97 / `option-maps.ts` 42 / `parser.ts` 240 / `tokenizer.ts` 141 / `types.ts` 36。

| 文件 | 行 | 内容 |
|---|---|---|
| `types.ts` | 1-6 | `JsonPrimitive` / `JsonValue` / `JsonObject` 定义 |
| `types.ts` | 8 | `RestrictedCelValue = string \| number`（★求值输入域只有标量） |
| `types.ts` | 9 | `ModelOptionName = "reasoningLevel" \| "maxOutputTokens"`（★只有两个 option） |
| `types.ts` | 11-14 | `RestrictedCelProgram` 接口 |
| `types.ts` | 16-19 | `ModelOptionMapProgram`（返回型收紧为 `JsonObject`） |
| `types.ts` | 21-29 | `RestrictedCelError`（带 `offset`） |
| `types.ts` | 31-36 | `ModelOptionMapError` |
| `tokenizer.ts` | 3-9 | `RestrictedCelTokenKind` 六种 |
| `tokenizer.ts` | 11-16 | `RestrictedCelToken` |
| `tokenizer.ts` | 18-20 | ★运算符/标点白名单 |
| `tokenizer.ts` | 22-73 | `tokenizeRestrictedCel` 主循环 |
| `tokenizer.ts` | 32-37 | 字符串字面量（单/双引号） |
| `tokenizer.ts` | 39-44 | 数字字面量 |
| `tokenizer.ts` | 46-51 | 标识符 |
| `tokenizer.ts` | 53-68 | 双字符/单字符运算符、标点 |
| `tokenizer.ts` | 69 | 未支持字符 → 抛错 |
| `tokenizer.ts` | 76 | 数字正则（无前导零） |
| `tokenizer.ts` | 83-124 | 字符串读取 + 转义 |
| `tokenizer.ts` | 91-93 | 字符串内换行 → 抛错 |
| `tokenizer.ts` | 112-120 | `\uXXXX` |
| `tokenizer.ts` | 126-135 | `SIMPLE_ESCAPES` 表 |
| `parser.ts` | 4-44 | ★AST 7 变体定义 |
| `parser.ts` | 46-51 | `parseRestrictedCel` 入口（接收 `variableName`） |
| `parser.ts` | 61-77 | `parse()`：trailing token 检查 |
| `parser.ts` | 65-67 | ★禁止成员访问 `.` |
| `parser.ts` | 68-70 | ★禁止函数调用 `(` |
| `parser.ts` | 79-86 | 三元条件（右结合） |
| `parser.ts` | 88-110 | 六级二元优先级链 |
| `parser.ts` | 112-128 | `parseBinary` 通用实现 |
| `parser.ts` | 130-145 | 一元 `! - +` |
| `parser.ts` | 147-180 | `parsePrimary` |
| `parser.ts` | 151-153 | 数字 JSON-safe 检查 |
| `parser.ts` | 158-171 | 标识符处理（★`input` / 布尔 / null / 未知） |
| `parser.ts` | 159-161 | 再次禁止函数调用 |
| `parser.ts` | 162 | ★`token.value === this.variableName` → `input` 节点 |
| `parser.ts` | 182-190 | 数组字面量 |
| `parser.ts` | 192-214 | 对象字面量（key 必须字符串、禁重复） |
| `evaluator.ts` | 9-15 | ★`evaluateRestrictedCel` 入口 |
| `evaluator.ts` | 17-50 | `evaluate` 主 switch |
| `evaluator.ts` | 26-35 | 对象构造（`Object.create(null)`，防原型污染） |
| `evaluator.ts` | 52-56 | 一元求值 |
| `evaluator.ts` | 58-105 | 二元求值 |
| `evaluator.ts` | 63-72 | ★`&&` / `\|\|` 短路 |
| `evaluator.ts` | 80-85 | `+` 重载（string 拼接 / number 相加） |
| `evaluator.ts` | 122-145 | `compare`：要求同类型 |
| `evaluator.ts` | 161-166 | `assertNumber` JSON-safe |
| `evaluator.ts` | 168-178 | ★`assertRestrictedCelValue`：只接受 string/number |
| `evaluator.ts` | 180-199 | `jsonEquals` 深比较 |
| `evaluator.ts` | 201-210 | `freezeJson` 深度冻结 |
| `compiler.ts` | 13-15 | ★三级缓存（program / optionMap / expression） |
| `compiler.ts` | 17-33 | `compileRestrictedCel` |
| `compiler.ts` | 35-57 | `compileModelOptionMap` |
| `compiler.ts` | 49-52 | 运行时结果形状兜底检查 |
| `compiler.ts` | 59-65 | `normalizeSource`（trim + 空检查） |
| `compiler.ts` | 76-78 | cache key = `` `${variableName}\0${source}` `` |
| `compiler.ts` | 80-88 | ★`assertObjectResultExpression`（编译期结果形状校验） |
| `merge-patch.ts` | 3-6 | `NamedJsonMergePatch` |
| `merge-patch.ts` | 13-33 | ★`applyOrderedJsonMergePatches`（含冲突守卫） |
| `merge-patch.ts` | 22-27 | ★路径冲突抛错 |
| `merge-patch.ts` | 35-49 | `collectWrittenPaths`（空 dict 视为叶子） |
| `merge-patch.ts` | 42 | ★`Object.keys(value).length > 0` 下钻判据 |
| `merge-patch.ts` | 51-57 | `pathsOverlap`（前缀即重叠） |
| `merge-patch.ts` | 59-61 | `formatPath`（`$.a.b`） |
| `merge-patch.ts` | 63-78 | ★`mergeObject`（RFC 7386 实现） |
| `merge-patch.ts` | 66-69 | `null` → `delete` |
| `merge-patch.ts` | 80-93 | `cloneJson`（含 `Object.create(null)`；**用 `configurable/writable: true` 创建，不 freeze**） |
| `option-maps.ts` | 5-8 | `ModelOptionMapSpecs`（两个 map 字符串） |
| `option-maps.ts` | 10-13 | `ModelOptionValues` |
| `option-maps.ts` | 15-17 | `CompiledModelOptionMaps` |
| `option-maps.ts` | 19 | ★注释："Model 创建时编译一次；每个请求只绑定本轮冻结的 Option value" |
| `option-maps.ts` | 20-34 | `compileModelOptionMaps` |
| `option-maps.ts` | 26-28 | ★`reasoningLevel` 缺失 → 抛错（fail-closed） |
| `option-maps.ts` | 36-42 | `optionPatch` |
| `index.ts` | 1-5 | 5 个 re-export（★注意：未导出 `parser`） |

### 13.2 `packages/shared/src/`

| 文件 | 行 | 内容 |
|---|---|---|
| `model-config.ts` | 2 | `import { compileModelOptionMap } from "@zcode/model-option-map"` |
| `model-config.ts` | 5-19 | ★`optionMapSchema`：zod `superRefine` 内编译校验 |
| `model-config.ts` | 21-35 | `completeEnumOptionSpecDataSchema`（`values` + `map`） |
| `model-config.ts` | 24-31 | `values` 校验：非空字符串、≥1 项、不重复 |
| `model-config.ts` | 37-42 | `completeLimitOptionSpecDataSchema`（`max` + `map`） |
| `model-config.ts` | 44-49 | 稀疏版（`sparseShape`） |
| `model-config.ts` | 68-86 | `completeModelPropertiesDataSchema` / 稀疏版（★能力位 8 项） |
| `model-config.ts` | 88-100 | `completeModelOptionSpecsDataSchema` / 稀疏版 |
| `model-config.ts` | 102-115 | `completeModelConfigDataSchema` / 稀疏版 |
| `config-schema.ts` | 4-8 | ★`sparseShape`：`nullable().optional()` |
| `model-selection.ts` | 4-15 | `modelSelectionSchema`（`options.reasoningLevel`） |
| `model-selection.ts` | **34-40** | `formatModelPickerValue`（`provider/model$level`） |
| `model-selection.ts` | **43-60** | `parseModelPickerValue` |

> **修订说明（E11）**：`formatModelPickerValue` 原引 `30-37`，实为 **L34-40**（L30 是空行）；`parseModelPickerValue` 原引 `40-56`，实为 **L43-60**（L40 是 `}`；文件共 60 行）。

### 13.3 `packages/provider/src/`

| 文件 | 行 | 内容 |
|---|---|---|
| `config-overlay.ts` | 1-14 | `ConfigValidationIssue`（9 个错误码，2 个无生产点） |
| `config-overlay.ts` | 21-38 | ★`ConfigOverlay` 基类（`overlayValue` / `overlayConfig` 三态语义） |
| `config/ids.ts` | 1-3 | 品牌类型别名 |
| `config/index.ts` | 1-5 | 导出清单（★未导出 `rule-data-schema` / `schema-validation`） |
| `config/schema-validation.ts` | 5-43 | ★`validateConfigSchema`（zod issue → 产品错误码） |
| `config/schema-validation.ts` | 32-34 | ★`optionSpecs` 路径 → `invalid-option-spec` |
| `config/schema.ts` | 32-57 | `parseProviderConfigMap` / `parseZCodeBuiltinProviderConfigRules` / `parsePersonalProviderConfigMap` |
| `config/schema.ts` | 74-76 | `parseModelConfig` |
| `config/schema.ts` | 78-107 | ★`parseZCodeBuiltinModelConfigRules`（★规则数组顺序 = 优先级） |
| `config/schema.ts` | 109-123 | `parsePersonalModelConfigRules` |
| `config/schema.ts` | 158-160 | `createModelConfig` → `ModelConfig.fromData` |
| `config/rule-data-schema.ts` | 13-24 | `idSchema` / `patternSchema`（正则合法性 refine） |
| `config/rule-data-schema.ts` | 26-38 | 3 个匹配型规则 schema（model / model-api / provider-site） |
| `config/rule-data-schema.ts` | 39-53 | 3 个精确型规则 schema（template / provider / manual-provider） |
| `config/rule-data-schema.ts` | 55-63 | ★`builtinModelConfigRulesSchema`（5 个数组） |
| `config/rule-data-schema.ts` | 64-84 | `personalModelConfigRulesSchema` + 智能/手动互斥校验 |
| `config/rule-data-schema.ts` | 70-84 | ★`superRefine`：同一 Provider/Model 不能同时声明智能与手动 |
| `config/rule-data-schema.ts` | 115-123 | ★禁止个人层给 `account:` Provider 写 access |
| `config/provider-data-schema.ts` | 4-8 | ★`providerApiTypeDataSchema`（3 种协议） |
| `config/provider-data-schema.ts` | 9-13 | `providerGroupDataSchema`（3 个分组） |
| `config/provider-data-schema.ts` | **32** | `apiKeyAccessDataSchema` 的 `type: z.enum(["api-key","zhipu-coding-plan-api-key"])` |
| `config/provider-data-schema.ts` | 37-39 | `completeApiKeyAccessDataSchema` |
| `config/provider-data-schema.ts` | **43** | `completeZhipuAccountAccessDataSchema` 的 `type: z.literal("zhipu-account")` |
| `config/provider-data-schema.ts` | 49-54 | `zhipuAccountAccessDataSchema`（稀疏版） |
| `config/provider-data-schema.ts` | **55-58** | `providerAccessDataSchema`（稀疏版 discriminatedUnion） |
| `config/provider-data-schema.ts` | **59-62** | `completeProviderAccessDataSchema`（完整版 discriminatedUnion） |
| `config/provider-data-schema.ts` | **64-80** | `completeProviderApiDataSchema` / `providerApiDataSchema` / `personalProviderApiDataSchema` |
| `config/provider-data-schema.ts` | **83-99** | `providerConfigDataSchema` / `completeProviderConfigDataSchema` |
| `config/provider-data-schema.ts` | 101-106 | `providerTemplateNameMapDataSchema` |
| `config/model-config.ts` | 43-76 | `EnumOptionSpecConfig`（`values` + `map`） |
| `config/model-config.ts` | 80-107 | `LimitOptionSpecConfig`（`max` + `map`） |
| `config/model-config.ts` | 122 | `Object.assign(this, input);`（`ModelInputFormatConfig` 构造器内 —— **不是** `validateComplete`） |
| `config/model-config.ts` | 177-244 | `ModelPropertiesConfig`（★能力位） |
| `config/model-config.ts` | 248-276 | `ModelOptionSpecsConfig` |
| `config/model-config.ts` | 285-335 | `ModelConfig`（`enabled` / `properties` / `optionSpecs`） |
| `config/model-config.ts` | **324-326** | ★`validateComplete` → `completeModelConfigDataSchema` |
| `config/model-config.ts` | 345-352 | ★`ModelConfigRule` 六变体联合类型 |
| `config/model-config.ts` | 379-381 | ★`composeEffective`（builtin + personal） |
| `config/model-config.ts` | 387-423 | ★★`resolve()`：规则匹配 + 有序 overlay |
| `config/model-config.ts` | 390-421 | 主循环（顺序即优先级） |
| `config/model-config.ts` | 396-399 | `manual-provider-model` 分支（`clearManualModelConfig`） |
| `config/model-config.ts` | 408 | `matchesRule(rule.modelMatch, input.modelId, true)`（忽略大小写） |
| `config/model-config.ts` | 544-546 | `matchesRule`：`new RegExp("^(?:pattern)$")` |
| `config/model-config.ts` | 548-559 | `normalizeBaseURLForRuleMatch`（URL 归一化） |
| `config/manual-model-config.ts` | 6-27 | ★`manualModelConfigSchema`（用户可编辑叶子白名单） |
| `config/manual-model-config.ts` | 24-26 | ★`optionSpecs.pick({reasoningLevel}).extend({maxOutputTokens: pick({max})})` |
| `config/manual-model-config.ts` | 32-34 | `extractManualModelConfig` |
| `config/manual-model-config.ts` | 37-41 | `clearManualModelConfig` |
| `config/manual-model-config.ts` | 43-56 | `omitSchemaFields`（递归裁剪白名单外字段） |
| `resolver.ts` | 25-35 | `RegistryProviderAccessConfig` / `RegistryProviderConfig` |
| `resolver.ts` | 72-74 | `RegistryModelConfig`（= `ModelConfig & complete*`） |
| `resolver.ts` | 76-102 | `serializeRegistryModelConfig` |
| `resolver.ts` | 104-126 | `createRegistryProviderConfig` / `createRegistryModelConfig` |
| `resolver.ts` | 183-343 | ★`ProviderConfigResolver.resolve` |
| `resolver.ts` | 192-197 | 模板 overlay 具体厂商 |
| `resolver.ts` | 209-212 | `ModelConfigRules.composeEffective` |
| `resolver.ts` | 221 | ★账号型强制 `enabled` |
| `resolver.ts` | 250-255 | `accessEntitled` / `providerExecutable` |
| `resolver.ts` | 256-292 | ★每个 model 的 resolve + 完整性校验 |
| `resolver.ts` | 257-263 | ★第 1 次 resolve：`effectiveModelRules.resolve({providerId, templateId, modelId, apiType, baseUrl})` |
| `resolver.ts` | **264-270** | ★第 2 次 resolve：`input.zcodeBuiltinModelRules.resolve({...})`（本次补 M6） |
| `resolver.ts` | 271-275 | `createRegistryModelConfig` |
| `resolver.ts` | 278-280 | ★`modelEnabled` / `executable` / `selectable` |
| `resolver.ts` | **285-286** | ★`config: modelConfig` 与 `effectiveBuiltinConfig` 并存发布 |
| `resolver.ts` | 355-376 | `resolveProviderOrder`（family 优先） |
| `registry.ts` | 9-35 | `ModelSelectionValidation`（含 `reasoning-level-*` 两种） |
| `registry.ts` | 74-92 | `validateSelection` |
| `registry.ts` | 129-159 | ★`validateModelSelectionOptions` |
| `registry.ts` | 140-147 | `reasoning-level-missing` |
| `registry.ts` | 148-157 | `reasoning-level-not-supported` + `supportedLevels` |
| `sources.ts` | **13-25** | ★`ProviderConfigSnapshot`（本次补 M8；`:20` 的 `zcodeBuiltinModelRules` 即 §5.4 二次 resolve 的输入） |
| `sources.ts` | 9-12 | `ProviderSource<TSnapshot>` 接口 |
| `facades.ts` | 全文 688 行 | Settings / Selection 的 Registry 投影与写入边界（本次补 M8） |

### 13.4 `packages/provider-node/src/`

| 文件 | 行 | 内容 |
|---|---|---|
| `zcode-builtin-release.ts` | **10** | `ZCODE_BUILTIN_RELEASE_SCHEMA_VERSION = 1` |
| `zcode-builtin-release.ts` | 11 | `RETIRED_ZAPI_PROVIDER_ID = "builtin:zapi"` |
| `zcode-builtin-release.ts` | **25-36** | `releaseSchema`（`schemaVersion` literal @ **:27** + `revision` @ **:28**） |
| `zcode-builtin-release.ts` | **38-57** | ★`decodeZCodeBuiltinRelease`（`releaseSchema.parse` @ **:39**；`parseZCodeBuiltinProviderConfigRules` @ **:40**；`parseZCodeBuiltinModelConfigRules` @ **:54**） |
| `zcode-builtin-release.ts` | 43-47 | ★拒绝已退役 Provider `builtin:zapi` |
| `zcode-builtin-release.ts` | **59-71** | `encodeZCodeBuiltinRelease` |
| `zcode-builtin-cache-paths.ts` | 38-40 | 缓存文件路径（`zcode-builtin.json` 活跃文件 + `zcode-builtin-refresh.json` 控制文件） |
| `zcode-builtin-provider-config-source.ts` | 64-84 | ★`applyRemoteRelease`（stale / unchanged / updated 判定；本次补 M7） |
| `zcode-builtin-provider-config-source.ts` | 100-104 | `#readAndMaterializeLocked`（bundled + active 双候选回落） |
| `zcode-builtin-provider-config-source.ts` | 213 | revision 形如 `` `zcode-builtin:${revision}:${sourceKey}` `` |
| `zcode-builtin-remote-synchronizer.ts` | 9-15 | ★六态结果 `updated\|unchanged\|stale\|missing\|skipped\|disposed`（本次补 M7） |
| `zcode-builtin-remote-synchronizer.ts` | 27-30 | 退避参数 `successIntervalMs` / `leaseDurationMs` / `failureBaseDelayMs` / `failureMaxDelayMs` |
| `zcode-builtin-remote-synchronizer.ts` | 33-37 | `ZCodeBuiltinRefreshEvent`（`reason: lease-held\|not-due\|endpoint-changed`） |
| `zcode-builtin-remote-synchronizer.ts` | 39-46 | `RefreshControl`（`leaseId` / `leaseUntil` / `nextEligibleAt` / `failureCount`） |
| `zcode-builtin-remote-synchronizer.ts` | 86-105 | 租约获取（`:90` lease-held、`:91` not-due） |
| `zcode-builtin-remote-synchronizer.ts` | 151-159 | ★指数退避算法 |
| `endpoint-scoped-zcode-builtin-source.ts` | 全文 148 行 | 按 endpoint 隔离配置源 |
| `zcode-builtin-download.ts` | 全文 128 行 | 远端 Release 下载 |
| `legacy-reasoning-level.ts` | **13-72** | ★`resolveLegacyReasoningLevel` |
| `legacy-reasoning-level.ts` | **18** | 只处理 `"off"` / `"nothink"` |
| `legacy-reasoning-level.ts` | 23-29 | 排除"个人层声明过 reasoningLevel"的情况 |
| `legacy-reasoning-level.ts` | 38-41 | `renames.find(...)`（按 `modelMatch` 精确匹配） |
| `legacy-reasoning-level.ts` | 50-52 | ★把 `values` 中的 `"disabled"` 替换成 `oldLevel`（**反向回滚**） |
| `legacy-reasoning-level.ts` | 64-70 | 用原规则引擎 `oldRules.resolve(...)` 重放 |
| `legacy-reasoning-level.ts` | **71** | `values?.includes(oldLevel) ? "disabled" : undefined` |
| `legacy-reasoning-level-renames.ts` | 全文 2218 字节 | `{modelMatch, oldLevel}` 表（≥10 条） |

> **修订说明（E8）**：原草稿在本文件的 7 处行号有偏差，已逐条校正（`11`→`10`；`26-34`→`25-36`；`:28`→`:27`；`:31`→`:39`；`:38`→`:40`；`36-58`→`38-57`；`60-77`→`59-71`）。
> **修订说明（E9）**：`legacy-reasoning-level.ts` 的 3 处行号已校正（`13-60`→`13-72`；`24`→`18`；`58-59`→`71`），并补入了此前未列的 L23-29 / L38-41 / L50-52 / L64-70。

### 13.5 `apps/zcode-cli/packages/`

| 文件 | 行 | 内容 |
|---|---|---|
| `adapters/src/model/model-option-map-fetch.ts` | 9-11 | `RawRequestBodyCapture` |
| `adapters/src/model/model-option-map-fetch.ts` | 13-31 | ★★`createModelOptionMapFetch`（唯一注入点） |
| `adapters/src/model/model-option-map-fetch.ts` | **21** | ★取不到 body 文本 → **静默透传**（fail-closed 的例外） |
| `adapters/src/model/model-option-map-fetch.ts` | 23 | ★`input.maps.apply(body, input.values)` |
| `adapters/src/model/model-option-map-fetch.ts` | 24 | `capture.body = patched` |
| `adapters/src/model/model-option-map-fetch.ts` | 26-29 | 重新构造 Request 转发 |
| `adapters/src/model/model-option-map-fetch.ts` | 33-45 | `readRequestBody`（`:37` string 直返；`:40-42` fail-closed；`:44` 返回 undefined） |
| `adapters/src/model/model-option-map-fetch.ts` | 38-42 | ★fail-closed 抛错（**仅覆盖"有 body 但非文本"**） |
| `adapters/src/model/model-option-map-fetch.ts` | 47-53 | `parseJsonObject` |
| `adapters/src/model/model-execution.ts` | 176-194 | ★`bindModel`（编译入口） |
| `adapters/src/model/model-execution.ts` | 186-187 | `captureModelSnapshot` + `compileModelOptionMaps` |
| `adapters/src/model/model-execution.ts` | 196-223 | `captureModelSnapshot` |
| `adapters/src/model/model-execution.ts` | 225-253 | `resolveSnapshot` |
| `adapters/src/model/model-execution.ts` | 255-318 | `createFactory` |
| `adapters/src/model/model-execution.ts` | 271-279 | ★`createModelOptionMapFetch` 装配 |
| `adapters/src/model/model-execution.ts` | 281-317 | 3 种 provider kind 分支 |
| `adapters/src/model/model-execution.ts` | 313 | `supportsStructuredOutputs: supportsJsonSchemaOutput` |
| `adapters/src/model/model-execution.ts` | 350-372 | `toAiSdkProviderConfig`（协议 → SDK kind） |
| `adapters/src/model/runner.ts` | 138-145 | ★`createModel` → `bindModel` |
| `adapters/src/model/runner.ts` | 155-222 | `toLegacyRequest` |
| `adapters/src/model/runner.ts` | **197-209** | ★推理遥测（`requestedLevel` 在 **L205**；L161-162 是 `shouldAttachReasoningTelemetry` / `selectedReasoningLevel` 取值） |
| `adapters/src/model/runner.ts` | 223-257 | ★`resolveForRequest` |
| `adapters/src/model/runner.ts` | 331-339 | ★`requireMaxOutputTokens`（undefined 抛错） |
| **`adapters/src/model/runner-options.ts`** | **73-79** | ★★**第二条参数路径**：`temperature` / `topP` / `topK` / `presencePenalty` / `frequencyPenalty` / `stopSequences` / `seed` 逐字段直通透传（本次补 M5） |
| **`adapters/src/model/runner-debug.ts`** | **127 / 236 / 294** | 调试/遥测链路同样携带 `temperature`（本次补 M5） |
| `contracts/src/model/index.ts` | **625-631** | ★★`ModelRequestSettings`（本次补 M5） |
| `contracts/src/model/index.ts` | **976** | `ModelRequest` 的 JSON Schema 含 `temperature` / `topP` / `topK` / `presencePenalty`（本次补 M5） |
| `contracts/src/model/model.ts` | 26-29 | `ModelOptions { reasoningLevel?, maxOutputTokens? }` |
| `contracts/src/model/model.ts` | 31-37 | `ModelRequest` |
| `contracts/src/model/model.ts` | 41-54 | `Model` 接口（`bind` / `generateText` / `streamText`） |
| `core/src/model/auxiliary-model-options.ts` | 12 | ★`Math.min(AUXILIARY_MAX_OUTPUT_TOKENS, model.optionSpecs.maxOutputTokens.max)` |
| `core/src/tool/handlers/read-session-context.ts` | 339-341 | ★`Math.min(..., model.optionSpecs.maxOutputTokens.max)` |
| `core/src/tool/handlers/websearch.ts` | 98 | ★`Math.min(4096, model.optionSpecs.maxOutputTokens.max)` |

> **修订说明（E19）**：原引 `runner.ts \| 161-162 \| 推理遥测（requestedLevel）`，实为 **L197-209**，`requestedLevel` 写在 **L205**。

### 13.6 `packages/ui/src/`

| 文件 | 行 | 内容 |
|---|---|---|
| `lib/modelThoughtOption.ts` | 5-33 | ★`resolveModelThoughtOption`（UI 从 `optionSpecs.reasoningLevel.values` 生成下拉） |
| `lib/modelThoughtOption.ts` | 16 | `if (!reasoning || reasoning.values.length === 0) return null` |
| `lib/modelThoughtOption.ts` | 24-27 | ★注释："Reasoning 没有默认档位；空字符串表示模型已选但用户尚未选择 reasoning" |

### 13.7 配置数据（`config/provider/zcode-builtin.json`，6212 行）

**顶层结构键位置**（脚本精确定位）：`"templateRules": [` **L6**、`"providerRules": [` **L691**、`"modelConfigRules"` **L864**、`"modelRules"` **L865**、`"modelApiRules"` **L2484**、`"providerSiteRules"` **L3287**、`"templateModelRules"` **L4316**、`"builtinProviderModelRules"` **L6026**。

| 行 | 内容 |
|---|---|
| 1-3 | `schemaVersion: 1` / `revision: 30` |
| **7-29** | `templateRules[0]` = `zai-api`（`templateId` @ **L8**；anthropic-messages @ api.z.ai） |
| **29-75** | `templateRules[1]` = `zai-standard-api`（`templateId` @ **L30**；openai-chat-completions，**24 个内置模型**） |
| **76-97** | `templateRules[2]` = `bigmodel-api`（`templateId` @ **L77**） |
| **98-145** | `templateRules[3]` = `bigmodel-standard-api`（`templateId` @ **L99**） |
| 894 | ★`modelRules` catch-all：`"map": "{}"` |
| 2463-2482 | `modelRules` 中的 `mimo-v2-flash` 规则（`values: ["disabled","enabled"]`，`max: 65536`） |
| 2484-2535 | ★`modelApiRules` 三条协议兜底（anthropic / chat-completions / responses） |
| 2500 | ★anthropic-messages 兜底 map（三元 + `output_config.effort`） |
| 2503 | ★`{'max_tokens': maxOutputTokens}` |
| 2514 | ★openai-chat-completions 兜底 map（**一次写 4 个方言字段**；含 `\|\|` / `!=` / `&&` / 链式三元） |
| 2517 | ★`{'max_completion_tokens': maxOutputTokens}` |
| **2528** | ★**openai-responses 兜底 reasoning map**（链式三元 `disabled→none` / `enabled→high` / 其余透传）——本次补全 E2 |
| 2531 | ★`{'max_output_tokens': maxOutputTokens}` |
| 2543 | `ox-alpha` / `glm-x-preview-f` @ anthropic（`values: ["low","high","max"]`） |
| 2555 | ★`{"reasoning_effort": reasoningLevel}` |
| **2560-2569** | `.*glm-5` @ anthropic → `thinking.type` 二元开关（`modelMatch` @ L2561、`map` @ L2566） |
| 2571-2581 | `.*GLM-5\.2` @ anthropic → 条件分支 + `output_config.effort` |

> **修订说明（E6）**：前 4 行行号由 `6-31 / 33-96 / 98-120 / 122-…` 校正为 **`7-29 / 29-75 / 76-97 / 98-145`**；"**23 个内置模型**"改为 **24**（`zai-standard-api.config.builtinModelIds.length = 24`）。
> **修订说明（E22）**：`2561-2569 \| .*glm-5 @ anthropic` 的起点偏 1，改为 **`2560-2569`**；同表 `2571-2580` 实为 L2571-2581（可接受，已同步更新）。
> §13.7 后半部分（`894`、`2463-2482`、`2484-2535`、`2500`、`2503`、`2514`、`2517`、`2531`、`2543`、`2555`、`2571-2580`）**经核验全部正确**。

### 13.8 我们网关（`/Users/w/Desktop/Model-Gateway/`）

| 文件 | 行 | 内容 |
|---|---|---|
| `model_gateway/config/schemas.py` | 150-190 | ★`SystemModel`（`params` + `_validate_params`） |
| `model_gateway/config/schemas.py` | 154-155 | ★注释：优先级 = 工具调用传参 > 此处 > 厂商内置 |
| `model_gateway/config/schemas.py` | 166 | `params: dict[str, Any]` |
| `model_gateway/config/schemas.py` | 169-190 | `PARAM_RANGES` 范围校验（未知键放行） |
| `model_gateway/core/ir.py` | 28-55 | `merge_reasoning`（三级合并 + 矛盾防护） |
| `model_gateway/core/ir.py` | 58-70 | ★`apply_model_params`（字段级注入，`body[k] = v` 式） |
| `model_gateway/core/ir.py` | 65-66 | `if not params: return body` |
| `model_gateway/core/ir.py` | 68-69 | `if body.get(k) is None: body[k] = v` |
| `model_gateway/core/ir.py` | 73-91 | `lift_reasoning_from_body`（入站提升） |
| `model_gateway/core/ir.py` | 94-111 | ★`inject_reasoning_into_body`（硬编码单一方言；L111 无条件覆盖 `reasoning_effort`） |
| `model_gateway/core/ir.py` | 99-102 | 注释：商汤配对约束实测 |
| `model_gateway/core/ir.py` | 114-122 | `IRRequest` |
| `model_gateway/core/scheduler.py` | 223-232 | ★`_out_body`（唯一出站注入点） |
| `model_gateway/core/scheduler.py` | 228-229 | `if ir.endpoint == "chat": apply_model_params(...)` |
| `model_gateway/core/scheduler.py` | 230-231 | `merge_reasoning` + `inject_reasoning_into_body` |
| `model_gateway/main.py` | 67 | `self.model_params` |
| `model_gateway/main.py` | 93 | `self.model_params = {m.name: dict(m.params) ...}` |
| `tests/unit/test_ir.py` | 136-161 | `apply_model_params` 已有单测 |

---

## 14. 一页纸总结

**ZCode 的模型参数处理机制 = 双轨制。**

**轨道一：option map 归一化轨**——一个 **867 行**的私有包，做三件事：

1. **定义一门极窄的语言**（Restricted CEL）：只能引用**一个**标量变量（`reasoningLevel` 或 `maxOutputTokens`），必须返回一个 JSON object，禁止成员访问和函数调用。
2. **把语言编译成闭包并缓存**：`tokenize → parse → 捕获 AST 的 evaluate 闭包`，三级缓存；编译在 **schema 校验期**（配置写错就进不了文件）和 **Model 创建期**（每 Model 一次）各跑一次。
3. **把求值结果当 RFC 7386 JSON Merge Patch 打到出站请求体上**：注入点在 fetch 拦截器，与协议/SDK 完全解耦；多个补丁写入重叠路径时**抛错而非覆盖**。

**轨道二：直通透传轨**——`temperature` / `topP` / `topK` / `presencePenalty` / `frequencyPenalty` / `stopSequences` / `seed` 经 `ModelRequestSettings`（`contracts/src/model/index.ts:625-631`）→ `runner-options.ts:73-79` **逐字段原样透传**给 AI SDK，**不做任何厂商方言归一化**。这条轨与我们网关的 `apply_model_params`（`ir.py:58-70`）**完全同级**。

**它解决"同一模型不同厂商标准不一致"的方式是：**
- **语义层统一**：上游只说 `reasoningLevel: "disabled" | "enabled" | "low" | "high" | "max"`
- **方言层穷举**：478 条配置规则，按 `modelMatch`(正则) × `apiTypeMatch` × `baseUrlMatch` 三维匹配，119 条 map 覆盖 21 种 reasoning 方言 + 4 种 max_tokens 方言
- **优先级**：`model` → `model-api` → `provider-site` → `template-model` → `provider-model` → `manual-provider-model`（越具体越晚应用、越优先），字段级 overlay（`undefined`=继承 / `null`=重置）

**它的作用域必须精确限定（本次修订的核心）**：
- **option map 机制**只归一化 **`reasoningLevel` 与 `maxOutputTokens`** 两个参数。
- **`temperature` / `topP` / `topK` / 惩罚项 / `stopSequences` / `seed`** 走**直通透传轨**，**不做方言归一化**——并非"不管"。
- **工具调用格式 / 缓存参数 / 多模态字段形态** 确实不在这两条轨内（由 AI SDK 层与能力位 `properties` 处理）。
- ZCode **有**静态能力降级（档位词表收缩 + `enabled: false` 硬禁用），**没有**运行时动态协商降级。

**给我们网关的三条最有价值的借鉴（按优先级）：**
1. **把"参数注入"升级为"命名补丁 + 路径冲突守卫"** —— 立即消除 `params` 与 `reasoning` 互相覆盖的现存隐患（`ir.py:68` vs `ir.py:111`）。
2. **把推理方言从硬编码改为数据表**（7 个结构模板 + 档位词表 dict + **布尔谓词表**），**但不要引入 DSL** —— 实测 119 条 map 中 **≈96%** 只用"对象字面量 + 三元 + `==`"，归纳后是 **3 个主语义 + 1 个布尔谓词语义**；用 `dialect` 枚举 + `effort_words` + `boolean_fields` + `max_tokens_field` **四个纯数据字段**即可完全覆盖。**注意：必须包含 `boolean_fields`——原草稿的单一 `effort_words` dict 覆盖不了 Qwen 的 `enable_thinking` 布尔谓词（内置配置出现 6 次）与 `:2514` 的负向谓词。**
3. **引入 resource 级参数覆盖 + 配置期支持矩阵校验 + fail-closed** —— 用 ZCode 的 `providerSiteRules`（52 条站点规则）证明"站点/协议"是必须的区分维度。

> **最终结论（对"要不要引入 DSL"）**：**不引入。** ZCode 用 DSL 是因为要处理 478 条规则 × 多站点 × 多协议的组合爆炸，且必须支持配置热更新不改代码；我们网关的规模用**声明式表格 + 枚举 + 布尔谓词表**性价比高得多。**修正后的数据把"3 个字段"改成"4 个字段"，但结论方向不变——引入 DSL 是过度设计。**
> 若未来规则真的膨胀到几百条、且非工程师需要改参数，可再考虑照抄 ZCode 的 `parser.ts` / `evaluator.ts`（**Apache-2.0** 许可下的 **867 行**实现；移植须遵守 Apache-2.0 §4，保留 `LICENSE` 与 `NOTICE`）。

---

## 15. 免责与核验边界

- 本报告只核验 ZCode 源码与配置、以及网关自身代码的**事实性断言**，不评价**建议本身**是否合理（那是产品决策）。
- 例外：当建议**建立在错误事实之上**时（本次的 E1 / E4 / E5），报告必须指出，因为那属于"论证前提失真"。
- **核验边界声明**：本次核验未覆盖的条目已全部列在 §12.1（含 `model-option-map` **零测试**这一重要风险提示——DSL 边界行为无测试保障）。
- 原始草稿保留于 `docs/research/drafts/03-zcode-模型参数处理机制.md`，核验报告保留于 `docs/research/drafts/verify-03-zcode.md`，二者均未修改。
