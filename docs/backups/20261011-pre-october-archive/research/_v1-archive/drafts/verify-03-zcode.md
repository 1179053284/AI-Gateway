# 核验报告：`03-zcode-模型参数处理机制.md`

> 核验对象：`/Users/w/Desktop/Model-Gateway/docs/research/drafts/03-zcode-模型参数处理机制.md`（1894 行）
> 源码基准：`/Users/w/Desktop/01-关注的开源项目/ZCode/`（只读）+ 网关自身 `/Users/w/Desktop/Model-Gateway/`（只读）
> 核验方式：脚本化机械校验（191 条去重引用）+ 人工精读（7 条关键结论逐条回溯）+ 全量配置复算（119 条 map 逐条枚举）
> 核验时间：2026-09-22　核验人：调研质量审计（证伪导向）
> **本报告未修改草稿及任何源码文件。**

---

## 一、总体结论

### 1.1 可信度评级：**B-（基本可信，但有 6 处影响选型决策的实质性错误）**

**分层评价：**

| 层次 | 评价 | 说明 |
|---|---|---|
| **机械准确性（行号/文件）** | **A** | 191 条引用全部指向真实存在的文件，**零行号越界**。核心包（`model-option-map/src/*.ts`）的 100+ 条行号引用几乎逐条精确。 |
| **统计数字** | **A** | 478 / 119 / 21 / 4 / 52 / 6212 / 12 站点 / 17 次重复 —— **全部复算通过**，无一处偏差。 |
| **架构机制描述** | **A-** | 分层、编译时机、合并语义、冲突守卫、优先级链、三态 overlay 的描述与源码一致，引文逐字吻合。 |
| **语义归纳与结论** | **C** | 最核心的建议依据（"119 条 map 只用 3 种语义，引入 DSL 是过度设计"）**被证伪**：实际用到了 `\|\|`/`&&`/`!=`/链式三元/`false`，且归类表漏了 3 种 map（含一条 openai-responses 全局兜底）。 |
| **可核查硬数字** | **D** | "全库 144 个测试文件" 实为 **4** 个（差 36 倍）；"MIT 许可" 实为 **Apache-2.0**；"23 个内置模型" 实为 **24**。 |
| **完整性** | **C+** | 漏掉了 ZCode 的**第二条参数路径**（temperature/topP/stop/penalties 经 `ModelRequestSettings` 直通）、`resolver.ts:264-270` 的二次 resolve、远端同步/回落机制、`sources.ts`/`facades.ts` 上游层。 |

### 1.2 错误密度统计表

| 指标 | 数值 |
|---|---|
| 草稿总行数 | 1894 |
| 提取到的 `路径:行号` 引用（含重复） | 216 |
| 去重后引用 | **191** |
| 文件不存在 | **0** |
| 行号越界 | **0** |
| **行号/内容不吻合** | **23**（占 191 条的 **12.0%**） |
| 统计数字复算不符 | **2**（"144 个测试文件"、"23 个内置模型"） |
| 事实性断言错误（非行号） | **7**（含 1 处许可协议、1 处无源模型名 "Grok"、1 处未通读即下绝对断言） |
| 自相矛盾 | **4** |
| 关键机制遗漏 | **5** |
| **错误总数（去重后）** | **22** |
| 其中 🔴 严重（影响结论/决策） | **6** |
| 其中 🟡 中等（可追溯性受损） | **9** |
| 其中 🟢 轻微（措辞/精度） | **7** |
| 已核实正确的关键结论 | **39 组**（见第三节） |

**错误密度：22 / 1894 行 ≈ 每 86 行 1 处错误；引用层 12.0% 不吻合。**
草稿的**证据纪律很好**（几乎每条结论都带 file:line，且绝大多数准确），但**在"由证据到结论"的归纳步骤上出现了系统性过度推断**——这正是本报告需要重点证伪的部分。

---

## 二、必须修正的错误清单（按严重度排序）

### 🔴 严重错误（6 条，直接影响网关技术选型）

---

#### E1　【核心建议依据被证伪】"119 条 map 只用「对象字面量 + 三元 + `==`」，归纳后只有 3 个语义"

**草稿原文位置**
- §2.5「实际特性使用率」表（第 206-220 行）
- §11.4「关键论证」表（第 1512-1524 行）：`| 对象字面量 + 三元 + \`==\` | **100%** |`
- §14 第 2 条（第 1893 行）
- §0 第 2 条（第 12 行）："有 `?:`、`&&/||`、`==/!=`、`< <= > >=`、`+ - * / %`、`!`、数组/对象字面量"（这里承认了，但 §11.4 又说 100% 只用 `==`）

**源码真实情况**（对 `config/provider/zcode-builtin.json` 全部 119 条含 map 规则逐条枚举）

| 特性 | 草稿 | 实测（按 map 条数） | 判定 |
|---|---|---|---|
| `==` | 57 | 57 | ✅ |
| `?:` 三元 | 50 | 50 | ✅ |
| `{}` 空对象 | 8 | 8 | ✅ |
| `\|\|` | 2 | 2 | ✅ |
| `!=` | 1 | 1 | ✅ |
| `&&` | 1 | 1 | ✅ |
| `!`（一元） | 1 | **0** | ❌ 见 E13 |
| 数组 `[...]` | 0 | 0 | ✅ |
| 算术/比较/`null` | 0 | 0 | ✅ |
| **链式三元（≥2 个 `?`）** | **未列** | **4** | ❌ |
| **`false` 布尔字面量** | **未列** | **1** | ❌ |

**证据（file:line）**
- `config/provider/zcode-builtin.json:2514` —— openai-chat-completions 全局兜底，**同时**用到 `\|\|`、`!=`×2、`&&`：
  ```
  {"thinking":{"type": reasoningLevel == "disabled" || reasoningLevel == "none" ? "disabled" : "enabled"},
   "enable_thinking": reasoningLevel != "disabled" && reasoningLevel != "none", ...}
  ```
- `config/provider/zcode-builtin.json:2528` —— **openai-responses 全局兜底，链式三元**：
  ```
  {"reasoning":{"effort": reasoningLevel == "disabled" ? "none" : reasoningLevel == "enabled" ? "high" : reasoningLevel}}
  ```
- `config/provider/zcode-builtin.json` providerSiteRules `.*deepseek-v4[.-]1-flash` @ openrouter —— 含 `false` 字面量。

**修正建议**
1. §11.4 的 `100%` 改为 **`≈96%`**（119 条中 5 条用到 `\|\|`/`&&`/`!=`/链式三元/`false`），并把第二行"算术、比较、数组、`null` 删除 | 0%" 保留（这一行**是对的**）。
2. "归纳后只有 3 个语义" 应改为 **"3 个主语义 + 1 个布尔谓词语义"**：
   - ① 键名映射　② 档位词表翻译　③ 字段集合条件化　**④ 布尔谓词（档位 ∈ 集合 → true/false）**
3. **④ 无法用草稿建议的单一 `effort_words: dict` 表达**。`{"enable_thinking": reasoningLevel == "enabled"}`、`reasoningLevel != "disabled" && reasoningLevel != "none"` 需要的是"**目标字段 + 成员集合 + 正/负向**"三个概念，不是"档位 → 词"的映射。草稿 §11.4 建议 2 的数据结构（第 1491-1508 行的 `EffortWordMap` + YAML `effort_words`）**覆盖不了这一类**，需要补一个 `boolean_fields: {enable_thinking: {in: [enabled]}}` 之类的结构。
4. 链式三元（`a ? x : b ? y : z`）应显式承认——它是"词表翻译"的**多入口形式**（`disabled→none` 且 `enabled→high` 且其余透传），单个 `effort_words` dict 能表达，但草稿的表格没有把它列为一种结构，导致 §11.4 建议 2 的 7 个 `ReasoningDialect` 枚举成员**也不完整**。

---

#### E2　【归类表漏 3 种 map，含一条全局兜底】"21 种 reasoningLevel map 按语义归类"

**草稿原文位置**　§6.2（第 619-703 行，标题写"21 种，按语义归类"）

**源码真实情况**　§6.2 的类别 A(2) + B(6) + C(4) + D(5) + E(1) = **18 种**，另有 **3 种未列**：

| # | 漏列的 map | 次数 | 归属（file:line 证据） |
|---|---|---|---|
| 1 | `{"thinking":{"type":"enabled"},"output_config":{"effort": reasoningLevel}}` | 2 | `zcode-builtin.json` modelApiRules `.*glm-5\.3(?:-flash)?` @ anthropic-messages；`.*qwen3\.8-(?:max\|flash)` @ anthropic-messages |
| 2 | `{"reasoning":{"effort": reasoningLevel == "disabled" ? "none" : reasoningLevel == "enabled" ? "high" : reasoningLevel}}` | **1** | `zcode-builtin.json:2528` —— **modelApiRules `modelMatch:"."*` @ openai-responses 全局兜底** |
| 3 | `reasoningLevel == "disabled" ? {"reasoning":{"enabled": false}} : {"reasoning":{"effort": reasoningLevel}}` | 1 | providerSiteRules `.*deepseek-v4[.-]1-flash` @ openai-chat-completions @ openrouter |

**额外问题**：§6.2 类别 C 表（第 645-650 行）第 3 行 `{"thinking":{"type":"adaptive"},"output_config":{"effort": reasoningLevel}}` 与类别 B 第 4 行是**同一条 map**（草稿自己注"见类别 B"），故类别 C 表头"（4 种）"实际只有 **3 种**。

**修正建议**
- 把 §6.2 标题与枚举对齐（18 + 3 = 21），或明确说明"另 3 种未归类"。
- **必须补上 `:2528` 这条 openai-responses 全局兜底**——草稿 §9.4 已经引了 anthropic（`:2500`）与 chat-completions（`:2514`）两条协议兜底，**唯独漏了 responses 兜底**，造成"3 种协议兜底"的叙述只覆盖 2 条 reasoning 兜底 + 3 条 maxOutputTokens 兜底，读者会误以为 responses 协议没有 reasoning 兜底。
- 第 3 条 map 其实就是草稿 §9.3「场景 B」引用的那条，说明作者见过它但忘了收进分类表——属于归类遗漏而非认知错误。

---

#### E3　【硬数字编造】"全库 144 个测试文件中无相关测试"

**草稿原文位置**　§12.1（第 1596 行）：
> "已用 `find . -name "*.test.ts" -o -name "*.spec.ts"`（排除 node_modules）全库搜索，该包下 0 命中；**全库 144 个测试文件中无相关测试**。"

**源码真实情况**
```bash
$ find . -type f \( -name "*.test.ts" -o -name "*.test.tsx" -o -name "*.spec.ts" -o -name "*.spec.tsx" \) -not -path "*/node_modules/*" | wc -l
4
```
全仓**仅 4 个**测试文件：
- `packages/ui/test/nonCliAcpRetirement.test.ts`
- `packages/services/test/importedClaudeRecovery.test.ts`
- `packages/services/test/nonCliAcpRetirement.test.ts`
- `packages/services/test/providerConfigMigration.test.ts`

`__tests__` 目录下 **0** 个；连最宽松的"文件名含 test/spec 的任意文件"口径也只有 89 个（且绝大多数是 `packages/web/dist/material-icons/folder-test.svg` 之类的图标资源与 `Update*` 文件名误匹配）。仓库根 `package.json` 无 `"test"` 脚本，无 `vitest.config.*` / `jest.config.*`。

**判定**：`144` 这个数字**无任何可能的口径支撑**，属编造。

**修正建议**：改为"全库仅 4 个测试文件（`packages/{ui,services}/test/`），均与 `model-option-map` 无关；`providerConfigMigration.test.ts` 亦未涉及 `optionSpecs`/`reasoningLevel`（已 grep 确认 0 命中）"。这一修正**不削弱**"零测试"的结论，反而让它更锋利。

---

#### E4　【未通读即下绝对断言】"它不管的：temperature / top_p / 惩罚项 / stop / 工具调用格式 / 缓存参数"

**草稿原文位置**
- §14 一页纸（第 1889 行）——**绝对断言**
- §0 第 8 条（第 18 行）——"不管惩罚项、不管缓存参数"
- §6.3 表（第 744-761 行）——"内置 119 条 map 中，以下维度完全没有出现"（**这个限定语是对的**）
- §12.6（第 1601 行）——"我 grep 过 `temperature` 未在 `model-option-map` 相关链路出现，**但不排除参数在 AI SDK 调用层（`runner-generate.ts` / `runner-options.ts`）以其他方式传递——这两个文件未通读**"（**诚实保留**）

**源码真实情况**　ZCode **存在第二条独立参数路径**，把这些参数原样透传给 AI SDK：

| 证据 | 内容 |
|---|---|
| `apps/zcode-cli/packages/contracts/src/model/index.ts:625-631` | `export interface ModelRequestSettings { temperature?: number; maxOutputTokens?: number; topP?: number; topK?: number; presencePenalty?: number; ... }` |
| `apps/zcode-cli/packages/adapters/src/model/runner-options.ts:73-79` | 逐字段透传：`temperature: input.request.temperature, topP: ..., topK: ..., presencePenalty: ..., frequencyPenalty: ..., stopSequences: ..., seed: ...` |
| `apps/zcode-cli/packages/adapters/src/model/runner-debug.ts:127 / :236 / :294` | 调试/遥测链路同样携带 `temperature` |
| `apps/zcode-cli/packages/contracts/src/model/index.ts:976` | `ModelRequest` 的 JSON Schema 含 `temperature` / `topP` / `topK` / `presencePenalty` |

**判定**：正确表述是——
> "**option map 机制**只归一化 2 个参数；`temperature`/`topP`/`topK`/惩罚项/`stopSequences`/`seed` 走 `ModelRequestSettings` → `runner-options.ts` 的**直通透传**，**不做任何厂商方言归一化**。"

**为什么这条很严重**：它**反转了 §11.2 的差距论证**。草稿 §11.2 说"我们只能 `body[k] = v`，无法表达条件字段集合"——但实际上 ZCode 对 temperature 也是 `body[k] = v` 式透传，**和我们网关的 `apply_model_params` 完全同级**。真正有差距的只有 reasoning/maxOutputTokens 这两个参数。§11.2 的 9 行对照表应重新校准，把"差距"限定在这两个参数上。

**同时这是内部矛盾**：§12.6 明确写了"未通读、不排除"，§14 却下了绝对断言。

**修正建议**：§14 改为"**option map 机制**不管的：…；这些参数由 `ModelRequestSettings` 直通透传（`runner-options.ts:73-79`），无厂商方言层"。§11.2 相应下调 #1/#2 的"严重度"或明确限定作用域。

---

#### E5　【许可协议错误】"它是 MIT/自有许可下的 866 行实现，移植成本低"

**草稿原文位置**　§11.4 建议 2 结尾（第 1526 行）

**源码真实情况**　`/Users/w/Desktop/01-关注的开源项目/ZCode/LICENSE` 首行：
```
                                 Apache License
                           Version 2.0, January 2004
```
仓库根另有 **1,975,825 字节** 的 `THIRD-PARTY-NOTICES.md`。

**修正建议**：改为 **Apache-2.0**。"移植成本低"的结论仍可成立（Apache-2.0 同样宽松），但必须补一句合规提示：**移植需保留 `LICENSE` 与 `NOTICE`/版权声明**（Apache-2.0 §4）。附带：866 行应为 **867** 行（见 E21）。

---

#### E6　【配置行号系统性错位 + 数字错】§13.7 前 4 行与"23 个内置模型"

**草稿原文位置**　§13.7（第 1833-1836 行）

| 草稿 | 真实（脚本精确定位） | 判定 |
|---|---|---|
| `6-31 \| templateRules[0] = zai-api` | `"templateRules": [` 在 **L6**、`"templateId": "zai-api"` 在 **L8**（条目约 L7–L29） | ⚠️ 边界含入下一条 |
| `33-96 \| templateRules[1] = zai-standard-api（openai-chat-completions，**23 个内置模型**）` | `"templateId": "zai-standard-api"` 在 **L30**（条目约 L29–L75）；`builtinModelIds` 长度 = **24** | ❌ 行号错 + 数字错 |
| `98-120 \| templateRules[2] = bigmodel-api` | `"templateId": "bigmodel-api"` 在 **L77**（约 L76–L97） | ❌ 行号错 |
| `122-… \| templateRules[3] = bigmodel-standard-api` | `"templateId": "bigmodel-standard-api"` 在 **L99**（约 L98–L145） | ❌ 行号错 |

**证据**：`config/provider/zcode-builtin.json` 顶层结构键位置 —— `"templateRules": [` L6、`"providerRules": [` L691、`"modelConfigRules"` L864、`"modelRules"` L865、`"modelApiRules"` L2484、`"providerSiteRules"` L3287、`"templateModelRules"` L4316、`"builtinProviderModelRules"` L6026。

**修正建议**：改为 `L7-29 / L29-75 / L76-97 / L98-145`；"23 个内置模型"改为 **24**。
（§13.7 后半部分 —— `894`、`2463-2482`、`2484-2535`、`2500`、`2503`、`2514`、`2517`、`2528`、`2531`、`2543`、`2555`、`2561-2569`、`2571-2580` —— **全部核实正确**，其中 `2463-2482` 的 mimo-v2-flash 规则行号**精确到行**。）

---

### 🟡 中等错误（9 条，损害可追溯性）

---

#### E7　`model-config.ts:122` 引用错误

- **草稿**：§10.1 阶段 1（第 1237 行）`└─ config.validateComplete(path)   model-config.ts:122`
- **真实**：`packages/provider/src/config/model-config.ts:324-326` 才是 `validateComplete`；**L122 是 `Object.assign(this, input);`（`ModelInputFormatConfig` 构造器内）**
- **注**：草稿 §13.3 表里另有 `324-326 | validateComplete → completeModelConfigDataSchema` —— **那一条是对的**，故 §10.1 的 122 是孤立笔误。
- **修正**：`model-config.ts:122` → `model-config.ts:324`

---

#### E8　`zcode-builtin-release.ts` 行号偏差 7 处

文件共 **75** 行。真实锚点：L10 `ZCODE_BUILTIN_RELEASE_SCHEMA_VERSION = 1`、L11 `RETIRED_ZAPI_PROVIDER_ID`、L25-36 `releaseSchema`、L27 `schemaVersion: z.literal(...)`、L28 `revision: z.number()...`、L38-57 `decodeZCodeBuiltinRelease`、L39 `releaseSchema.parse`、L40 `parseZCodeBuiltinProviderConfigRules`、L54 `parseZCodeBuiltinModelConfigRules`、L59-71 `encodeZCodeBuiltinRelease`。

| 草稿位置 | 草稿引用 | 真实 | 判定 |
|---|---|---|---|
| §13.4（第 1776 行） | `11 \| ZCODE_BUILTIN_RELEASE_SCHEMA_VERSION = 1` | **L10** | ❌ |
| §9.1（第 1034 行） | `schemaVersion` 硬版本 `z.literal(1)`（`:28`） | **L27**（L28 是 `revision`） | ❌ |
| §8.2 / §8.3（第 972 行） | `releaseSchema.parse()` 记 `:31` | **L39** | ❌ |
| §8.2（第 923 行） | `parseZCodeBuiltinProviderConfigRules(...) :38` | **L40** | ❌ |
| §13.4（第 1778 行） | `36-58 \| decodeZCodeBuiltinRelease` | **L38-57** | ❌ |
| §13.4（第 1780 行） | `60-77 \| encodeZCodeBuiltinRelease` | **L59-71** | ❌ |
| §10.1 阶段 0（第 1220 行） | `decodeZCodeBuiltinRelease() zcode-builtin-release.ts:31-58` | **L38-57** | ❌ |
| §13.4（第 1779 行） | `43-47 \| 拒绝已退役 Provider builtin:zapi` | L43-47 | ✅ |
| §13.4（第 1777 行） | `26-34 \| releaseSchema` | L25-36 | ⚠️ 可接受 |

---

#### E9　`legacy-reasoning-level.ts` 行号 3 处全错（文件共 72 行）

**草稿原文位置**　§13.4（第 1783-1785 行）、§12.3（第 1598 行）

| 草稿 | 真实 |
|---|---|
| `13-60 \| ★resolveLegacyReasoningLevel` | **L13-72** |
| `24 \| 只处理 "off" / "nothink"` | **L18**：`if (oldLevel !== "off" && oldLevel !== "nothink") return undefined;`；**L24 是 `personal &&`** |
| §12.3 "`legacy-reasoning-level.ts:24` 使用它把 `off`/`nothink` 映射回 `disabled`" | `renames` 的 **import 在 L8**，**使用在 L38-41 与 L51** |
| `58-59 \| values?.includes(oldLevel) ? "disabled" : undefined` | **L71** |

**附带事实修正（见 M9）**：`packages/provider-node/src/legacy-reasoning-level-renames.ts` **确实存在**（2218 字节，≥10 条 `{modelMatch, oldLevel}` 记录，`oldLevel` 取值为 `"off"` 或 `"nothink"`），草稿 §12.3 说"具体内容未读"是诚实的，但既然表就在那里、且草稿同时给出了 3 个错误行号，建议直接读掉并把 §12.3 从"未验证"移到正文。

---

#### E10　`provider-data-schema.ts` 引用 4 处错位

| 草稿位置 | 草稿引用 | 真实 | 判定 |
|---|---|---|---|
| §9.1（第 1038 行） | `config.access.type` = `api-key`/`zhipu-coding-plan-api-key`/`zhipu-account`（`:37`） | **L32** 是 `z.enum(["api-key","zhipu-coding-plan-api-key"])`，**L43** 是 `z.literal("zhipu-account")`；L37 是 `completeApiKeyAccessDataSchema` 起点 | ❌ |
| §9.2（第 1093 行） | "`access` 在完整 schema 里是 discriminated union（`provider-data-schema.ts:70-73`）" | discriminatedUnion 在 **L55-58（稀疏）/ L59-62（完整）**；L70-73 是 `providerApiDataSchema` 尾部 | ❌ |
| §13.3（第 1732 行） | `76-88 \| providerApiDataSchema / completeProviderApiDataSchema` | **L64-80** | ❌ |
| §13.3（第 1733 行） | `90-106 \| providerConfigDataSchema / completeProviderConfigDataSchema` | **L83-99**（L101-106 是 `providerTemplateNameMapDataSchema`） | ❌ |
| §13.3（第 1728-1731 行） | `4-8` / `9-13` / `37-46` / `49-63` | 逐条核对 | ✅ |

---

#### E11　`model-selection.ts` 行号 2 处错（文件共 61 行）

| 草稿（§13.2，第 1703-1704 行） | 真实 |
|---|---|
| `30-37 \| formatModelPickerValue（provider/model$level）` | **L34-40**（L30 是空行） |
| `40-56 \| parseModelPickerValue` | **L43-60**（L40 是 `}`） |
| `4-15 \| modelSelectionSchema` | ✅ L4-15 |

---

#### E12　`types.ts` 实体计数错

- **草稿**：§7.1 标题（第 767 行）"`types.ts` 全部定义（**36 行，仅 5 个实体**）"
- **真实**：36 行 ✅；但 export 实体共 **9 个**：`JsonPrimitive`、`JsonValue`（L1-2）、`JsonObject`（L4）、`RestrictedCelValue`、`ModelOptionName`（L8-9）、`RestrictedCelProgram`（L11）、`ModelOptionMapProgram`（L16）、`RestrictedCelError`（L21）、`ModelOptionMapError`（L31）
- **注**：草稿在同一节里把 9 个实体**全列出来了**（第 770-799 行），只是标题的"5 个"与内容不符 —— **属自相矛盾的笔误**。
- **修正**：改为"9 个实体"。

---

#### E13　§2.5 特性使用率表：一元 `!` 计数错

- **草稿**：`| \`!\` | 1 |`
- **真实**：一元 `!` 在 119 条 map 中 **0 次**。字符级 `!` 共 2 处，**全部来自 `!=`**（`:2514` 的 `reasoningLevel != "disabled" && reasoningLevel != "none"`），同属 1 条 map。
- **修正**：一元 `!` 改为 **0**（与"数组/算术/比较/null 均 0"同列）。否则该行与上一行 `!=` = 1 构成同一来源的重复计数。

---

#### E14　§6.2 类别 B 首行两处失准（无源模型名 + 泛化 values）

- **草稿**（第 634 行）：`| 17 | \`{"reasoning_effort": reasoningLevel}\` | 纯透传（Kimi K3 / GPT-5.4 / Qwen3.8 / **Grok** 等，\`values=["low","high","max"]\`） |`
- **真实（脚本全量列举这 17 条）**：
  `ox-alpha|glm-x-preview-f`、`kimi-k3`、`k3`、`k3-256k`、`qwen3.8-max/flash`、`gpt-5.4`、`qwen3.8-omni-flash`、`glm-5.3-flash`、`glm-5.3`、`glm-5.2`、`kimi-k3`(站点)、`deepseek-v4.1-flash`、`deepseek-v4-pro`、`deepseek-v4-flash`、`deepseek-v4-flash-vision-exp`、`hy4-preview`、`hy3`
- **问题 1**：**没有 Grok**。"Grok" 属无源引入（全仓 `grok` 在 `config/provider/zcode-builtin.json` 中 0 命中）。
- **问题 2**：`values=["low","high","max"]` 并非通用 —— `kimi-k3`(站点) 是 `["max"]`、`glm-5.2` 是 `["high","max"]`、`hy4-preview` 是 `["none","high"]`、`hy3` 是 `["none","low","high"]`，另有 7 条 modelApiRules 规则**不声明 `values`**（继承 modelRules）。
- **修正**：删除 "Grok"；把 values 描述改为"values 因站点而异（`["max"]` / `["high","max"]` / `["none","high"]` / `["none","low","high"]` / 不声明）"。

---

#### E15　§6.2 类别 C "27 个模型" 措辞失准

- **草稿**（第 647 行）："二元开关（GLM-5/5.1/4.7 等 **27 个模型** @ anthropic-messages）"
- **真实**：27 是**规则条数**，其中存在重复 `modelMatch`（`kimi-k2.6`×2、`kimi-k2.5`×2、`mimo-v2.5`×2、`mimo-v2.5-pro`×2、`mimo-v2-flash`×2），**实际不同模型 < 27**；且构成是 glm（11）+ qwen（6）+ mimo（7）+ kimi（4）混合，"GLM-5/5.1/4.7 等"易误读为全部是 GLM。
- **修正**：改为"27 条规则（含重复 modelMatch），覆盖 glm / qwen / mimo / kimi 四族"。

---

### 🟢 轻微问题（7 条）

| # | 草稿位置 | 问题 | 修正 |
|---|---|---|---|
| **E16** | §7.3 第 4 条（第 891 行）"`JsonObject` 是 `readonly` + `Object.create(null)`：**不可变** + 无原型" | "无原型" ✅（`evaluator.ts:26`、`merge-patch.ts:83`）；但"**不可变**"只对求值结果成立（`evaluator.ts:14 freezeJson`）。`merge-patch.ts:80-93` 的 `cloneJson` 用 `configurable:true, writable:true` 创建且**不 freeze**，`applyOrderedJsonMergePatches` 的返回值**可变** | 改为"求值结果深度冻结；merge-patch 输出无原型但**未冻结**" |
| **E17** | §5.3（第 577 行 vs 第 585 行） | **句内自相矛盾**："用户在 UI 上只能改档位值（`reasoningLevel`），**不能改 map**" vs 紧随其后"用户可改：`reasoningLevel`（**整个，含 values + map**）"。按 `manual-model-config.ts:24` 的 `pick({ reasoningLevel: true })`，**用户可改 reasoningLevel 的 map**；不可改的只有 `maxOutputTokens.map`（`:25` 只 `pick({max:true})`） | 删掉"不能改 map"，改为"不能改 `maxOutputTokens.map`" |
| **E18** | §10.2 第 2 条（第 1325-1333 行）"**fail-closed 而非 fail-open**" | 绝对化。`model-option-map-fetch.ts:21` 有早退分支 `if (bodyText === undefined) return input.fetch(request, init);`（配合 `:44 return undefined`）——**取不到 body 文本时会静默跳过 patch**。fail-closed 只覆盖 `init.body` 为非字符串非 null 的情形 | 改为"对『有 body 但非文本』fail-closed；对『取不到 body 文本』仍会静默透传" |
| **E19** | §13.5（第 1810 行）`runner.ts \| 161-162 \| 推理遥测（requestedLevel）` | `requestedLevel` 实际写在 **L205**（`...(selectedReasoningLevel ? { requestedLevel: selectedReasoningLevel } : {})`）；L161-162 是 `shouldAttachReasoningTelemetry` / `selectedReasoningLevel` 取值 | 改为 `197-209 \| 推理遥测（requestedLevel 在 L205）` |
| **E20** | §7.2 图注（第 842 行）`compiler.ts:16/35` | `compiler.ts:16` 是**空行**；`RestrictedCelProgram` / `ModelOptionMapProgram` 两个接口实际在 **`types.ts:11-14` / `types.ts:16-19`**；`compiler.ts:35` 是 `compileModelOptionMap` 函数而非接口 | 改为 `types.ts:11-19` |
| **E21** | §0 第 4 行、§13.1 标题（第 4、1609 行）"8 个文件，共 **866** 行" | `wc -l packages/model-option-map/src/*.ts` = **867** | 改为 867 |
| **E22** | §13.7（第 1848 行）`2561-2569 \| .*glm-5 @ anthropic` | 该规则实际 **L2560-2569**（modelMatch L2561、map L2566），起点偏 1。同表 `2571-2580 \| .*GLM-5\.2` 实际 L2571-2581，可接受 | 改为 2560-2569 |

---

## 三、已核实正确的关键结论清单

> 以下每一条都经源码/数据逐条回溯，**确认草稿表述准确**。这是草稿的真正价值所在。

### 3.1 第 1 条关键结论：参数范围与求值输入域 —— ✅ **已核实正确**

| 断言 | 证据 | 判定 |
|---|---|---|
| 只处理 2 个 option | `types.ts:9` `export type ModelOptionName = "reasoningLevel" \| "maxOutputTokens";` | ✅ 逐字吻合 |
| `option-maps.ts` 结构与之一致 | `option-maps.ts:5-8 ModelOptionMapSpecs`、`10-13 ModelOptionValues`、`15-17 CompiledModelOptionMaps` | ✅ |
| 求值期只有一个标量输入 | `types.ts:8 RestrictedCelValue = string \| number`；`evaluator.ts:168-178 assertRestrictedCelValue` 只接受 string/number，其余抛 `input value must be a string or number` | ✅ |
| 无上下文对象（无 `model.id` / `provider.name` / `api.type`） | `parser.ts:162` 唯一合法变量名；`evaluator.ts:17-50` 的 `evaluate` 只接收 `(expression, input)` 两个参数，无 env 参数 | ✅ |
| `temperature`/`top_p`/惩罚项/`stop`/工具格式不在 option map 内 | `grep -rn "temperature" packages/model-option-map/src/` → **0 命中**；119 条 map 中这些键 0 次 | ✅（但见 **E4**：ZCode 另有直通路径，草稿 §14 的绝对表述需修正） |

### 3.2 第 2 条关键结论：RFC 7386 + fetch 注入点 —— ✅ **已核实正确**

| 断言 | 证据 | 判定 |
|---|---|---|
| mergeObject 是 RFC 7386 三条规则 | `merge-patch.ts:63-78`：`null`→`delete`（L66-69）；object→递归（L70-74）；其余→整体替换（L75），数组由 `cloneJson` 整体拷贝（L81） | ✅ 逐字吻合 |
| **非标准扩展 1**：跨 patch 路径冲突检测 | `merge-patch.ts:13-33 applyOrderedJsonMergePatches`，`ownedPaths` + `pathsOverlap` 前缀判定（L51-57） | ✅ |
| **非标准扩展 2**：空对象视为叶子 | `merge-patch.ts:42` `if (isJsonObject(value) && Object.keys(value).length > 0)` | ✅ 逐字吻合 |
| 注入点在 fetch 拦截器 | `model-option-map-fetch.ts:13-31 createModelOptionMapFetch`，`input.maps.apply(body, input.values)` 在 **L23**；装配点在 `model-execution.ts:271-279` | ✅ |
| 与 SDK/协议解耦（3 种协议共用一个 patch 点） | `model-execution.ts:286`（openai-responses 兼容包装）、`:296`（anthropic 兼容包装）、`:307`（openai-compatible）三条分支都把 `optionFetch` 作为 `fetch` 注入 | ✅ |
| 代价：每请求一次 `JSON.parse` + `JSON.stringify` | `model-option-map-fetch.ts:22` / `:25` | ✅ |
| `rawRequestBodyCapture` 暴露补丁后 body | `model-option-map-fetch.ts:9-11`、`:24`；`model-execution.ts:234` | ✅ |

### 3.3 第 3 条关键结论：重叠路径抛错 —— ✅ **已核实正确**

- 草稿：`merge-patch.ts:22-27`
- 真实：L22 `const conflict = ownedPaths.find(...)`、L23 `if (conflict) {`、**L24-26 `throw new ModelOptionMapError(...)`**、L27 `}`
- 判定：**引用范围正确**（throw 落在 22-27 内）。`pathsOverlap` 前缀判定（`$.a.b` 与 `$.a` 冲突、`$.a.b` 与 `$.a.c` 不冲突）与 `merge-patch.ts:51-57` 一致 ✅
- 草稿对"为什么合理"的论证（语义正交的 option 若写同一路径 = 配置 bug，静默覆盖会产出难排查的错误请求）是**合理推断**，已标注为设计动机而非源码事实 ✅

### 3.4 第 5 条关键结论：统计数字 —— ✅ **全部复算通过（0 偏差）**

| 断言 | 草稿 | 复算 | 判定 |
|---|---|---|---|
| `modelRules` | 84 | 84 | ✅ |
| `modelApiRules` | 72 | 72 | ✅ |
| `providerSiteRules` | 52 | 52 | ✅ |
| `templateModelRules` | 244 | 244 | ✅ |
| `builtinProviderModelRules` | 26 | 26 | ✅ |
| **合计** | **478** | **478** | ✅ |
| 含 map 规则 | 119 | **119**（101 reasoningLevel + 18 maxOutputTokens） | ✅ |
| 去重 reasoningLevel map | 21 | **21** | ✅ |
| 去重 maxOutputTokens map | 4 | **4** | ✅ |
| `zcode-builtin.json` 行数 | 6212 | 6212 | ✅ |
| `schemaVersion` / `revision` | 1 / 30 | 1 / 30 | ✅ |
| `providerSiteRules` 站点数 | 12 | **12** | ✅ |
| 站点分布（25/11/4/2/2/2/1/1/1/1/1/1） | 逐条列出 | **逐条吻合** | ✅ |
| maxOutputTokens 4 种（15/1/1/1） | 逐条列出 | **逐条吻合** | ✅ |
| `{"reasoning_effort": reasoningLevel}` 重复 17 次 | 17 | **17** | ✅ |
| 空对象 `{}` 8 次 | 8 | 8 | ✅ |

### 3.5 第 6 条关键结论：`model-option-map` 零测试 —— ✅ **已核实正确**

- `find packages/model-option-map -type f -not -path "*/node_modules/*" | grep -Ei "test|spec"` → **空**
- 全库 4 个测试文件均与该包无关；`providerConfigMigration.test.ts` 中 `optionSpecs|reasoningLevel|model-option-map` **0 命中**
- 判定：**"零测试"结论成立**（草稿的"144"数字错，见 E3，但不影响结论）

### 3.6 第 7 条关键结论：配置结构描述 —— ✅ **抽查 3 组全部吻合**

| 抽查对象 | 判定 |
|---|---|
| **§9.2 片段 1**：`templateRules[0] = zai-api`（`anthropic-messages @ https://api.z.ai/api/anthropic`、`access.type = zhipu-coding-plan-api-key`、`builtinModelIds = ["GLM-5.3","GLM-5.3-Flash"]`）；`providerRules[0] = account:zai-individual-coding-plan`（`group: zai-family`、`access.type = zhipu-account`、`mode: individual-coding-plan`、`accountType: zai`） | ✅ **与真实文件逐字一致** |
| **§9.3 三个场景**：A（`deepseek-v4-pro` @ openai-responses @ `api\.deepseek\.com`，map = `reasoning.effort` + `disabled→none`）；B（`.*deepseek-v4[.-]1-flash` @ openai-chat-completions @ openrouter，map = `disabled ? reasoning.enabled=false : reasoning.effort`）；C（`.*(?:glm-\|deepseek-\|kimi-k2\|qwen\|mimo-).*` @ anthropic-messages @ openrouter，map = `disabled\|none → thinking.type=disabled`，`enabled→high`） | ✅ **三段 JSON 逐字一致** |
| **§9.5 catch-all**：modelRules `.*`（`contextWindow:200000`、`inputFormat.supportsImage=false`、`maxOutputTokens.max:32000`、`reasoningLevel.values:["disabled","enabled"]`、`map:"{}"`） | ✅ **逐字一致**；`map:"{}"` 在 L894 ✅ |
| **§6.3 类别 F**：GLM-4.6 三条 `enabled:false`（`zai-standard-api` / `bigmodel-standard-api` / `openrouter` + `z-ai/glm-4.6`）；DeepSeek 站点 `supportsNativeWebSearch` + `supportsMidConversationSystem` 规则 | ✅ **逐条存在且字段一致** |
| **`providerRules` 全部 8 条均为 `account:` 前缀** | ✅ |

### 3.7 其他已核实正确的关键结论

| # | 断言 | 证据 | 判定 |
|---|---|---|---|
| C3 | 禁止成员访问 / 函数调用 | `parser.ts:65-67`（`member access is not supported`）、`parser.ts:68-70` + `parser.ts:159-161`（`function calls are not supported`）；`.` 在 `tokenizer.ts:20` 的 `PUNCTUATION` 中 | ✅ 逐字吻合 |
| C4 | 唯一合法标识符 | `parser.ts:162`（变量名）、`163-166`（`true`/`false`/`null`） | ✅ |
| C11 | 编译期结果形状契约只递归 `conditional` 两支 | `compiler.ts:80-88 assertObjectResultExpression`；因此 `a ? {} : 1` 编译期被拒，而 `(1+1) ? {} : {}` 求值期才暴露 | ✅ 草稿对"已知窄口"的分析成立 |
| C11b | 运行时兜底 | `compiler.ts:49-52` | ✅ |
| C12 | 三级缓存 + cache key 用 `\0` 分隔 | `compiler.ts:13-15`、`:76-78` `${variableName}\0${source}` | ✅ |
| C13 | DSL 在 schema 校验期编译 | `packages/shared/src/model-config.ts:5-19` **逐字吻合**；`code:"custom"` 在 `:13-16` | ✅ |
| C14 | DSL 错误归类为 `invalid-option-spec` | `schema-validation.ts:32-34` `optionSpec \|\| issue.path.includes("optionSpecs") ? "invalid-option-spec"` | ✅ |
| C15 | 两个错误码无生产点 | 全仓 `.ts` 仅 `config-overlay.ts:8-9` 声明 + `dist/config-overlay.d.ts:2` | ✅ 草稿的 grep 结论成立 |
| C16 | 优先级 = 数组顺序 | `schema.ts:80-106` 五组按 model→model-api→provider-site→template-model→provider-model 拼接；`model-config.ts:387-423` 主循环顺序 overlay；`composeEffective` `model-config.ts:379-381` **逐字吻合** | ✅ |
| C17 | overlay 三态语义 | `config-overlay.ts:21-38` **逐字吻合**（`undefined`=继承 / `null`=重置 / 有值=覆盖）；`sparseShape` `config-schema.ts:4-8` ✅ | ✅ |
| C18 | 手动配置可编辑叶子白名单 | `manual-model-config.ts:24-26` **逐字吻合**；注释 `:5` 逐字吻合 | ✅（但见 E17 的表述矛盾） |
| C19 | `index.ts` 未导出 `parser` | `packages/model-option-map/src/index.ts:1-5` 只有 compiler / merge-patch / option-maps / tokenizer / types | ✅ |
| C20 | `config/index.ts` 未导出 `rule-data-schema` / `schema-validation` | `config/index.ts:1-5` | ✅ |
| C21 | §8.1 各文件行数 | schema 160 / rule-data-schema 185 / provider-data-schema 113 / manual-model-config 69 / model-config 581 / provider-config 513 / schema-validation 43 / config-overlay 46 | ✅ **全部正确** |
| C22 | §8.1 关键导出行号 | `ModelConfigRules:366`、`ModelOptionSpecsConfig:248`、`EnumOptionSpecConfig:43`、`LimitOptionSpecConfig:80`、`ModelPropertiesConfig:177`、`ProviderConfig:173`、`ProviderApiConfig:131`、`ApiKeyAccessConfig:36`、`ZhipuAccountAccessConfig:76`、`ProviderConfigMap:383`、`ProviderTemplateMap:310`、`ids.ts` 3 行 3 类型 | ✅ **全部正确** |
| C23 | 三个校验时机 | ① 反序列化硬失败（`zcode-builtin-release.ts:39`、`schema.ts:79`）② `validateComplete` 软失败收集 issues（`model-config.ts:324`、`schema-validation.ts:5`）③ 请求期档位硬失败（`registry.ts:129-159`）；`resolver.ts:271-279` 把 issues 记到 model 上、`executable=false` | ✅ |
| C24 | `resolver.ts:221` 账号型强制 enabled | `const enabled = config.access?.type === "zhipu-account" \|\| (rule.enabled ?? true);`；注释 L220"账号不再支持总禁用" | ✅ 逐字吻合 |
| C25 | `resolver.ts:250` accessEntitled | `config.access?.type !== "zhipu-account" \|\| config.access.entitled === true;` | ✅ |
| C26 | §10.1 阶段 2-6 的全部 file:line | `registry.ts:74/129/148`、`runner.ts:138/144/155/195/223/230/232-238/331`、`model-execution.ts:176/186-187/196/225/235/266/273/276/286/296/307/313/508/517`、`model-option-map-fetch.ts:19-30/22/23/24/25/26-29/38-42` | ✅ **逐条正确** |
| C27 | `requireMaxOutputTokens` undefined 抛错 | `runner.ts:331-339` | ✅ 逐字吻合 |
| C28 | §13.1 核心包全部行号 | `tokenizer.ts` / `parser.ts` / `evaluator.ts` / `compiler.ts` / `merge-patch.ts` / `option-maps.ts` 的 60+ 条行号引用 | ✅ **逐条正确**（唯一例外 E20） |
| C29 | §7.1 `types.ts` 逐行引用 | `1-6` / `8` / `9` / `11-14` / `16-19` / `21-29` / `31-36` | ✅ **全部正确** |
| C30 | §11.1 网关现状 8 行 | `schemas.py:166/169-190`、`ir.py:58-70/59-62/28-111/94-111`、`scheduler.py:223-232/229-230` | ✅ **全部正确** |
| C31 | §13.8 网关引用 | `schemas.py:150-190/154-155/166/169-190`、`ir.py:28-55/58-70/65-66/68-69/73-91/94-111/99-102/114-122`、`scheduler.py:223-232/228-229/230-231/246`、`main.py:67/93`、`tests/unit/test_ir.py:136-161` | ✅ **全部正确** |
| C32 | **§11.2 第 6 条"现存覆盖隐患"真实存在** | `_out_body`（`scheduler.py:223-232`）先 `apply_model_params` 再 `inject_reasoning_into_body`；后者在 `ir.py:111` 无条件 `body["reasoning_effort"] = spec.effort` → params 里配的 `reasoning_effort` 会被覆盖 | ✅ **真实隐患，草稿判断正确** |
| C33 | 各辅助文件行号 | `auxiliary-model-options.ts:12`、`websearch.ts:98`、`read-session-context.ts:339-341`、`modelThoughtOption.ts:5-33/16/24-27`、`contracts/model/model.ts:26-29/31-37/41-54`、`zcode-builtin-cache-paths.ts:39-40`、`zcode-builtin-provider-config-source.ts:213` | ✅ **全部正确** |
| C34 | §6.1 maxOutputTokens 4 种 map 及归属方言 | 15×`{"max_tokens"}` / 1×`{'max_tokens'}` / 1×`{'max_completion_tokens'}` / 1×`{'max_output_tokens'}` | ✅ 逐条吻合 |
| C35 | §6.2 类别 A / D-1..D-5 / E 的 map 与归属模型 | `{"reasoning":{"enabled":...}}`×1 @ openrouter qwen3.7 ✅；`disabled→none`×3 @ deepseek 官方 responses（v4-flash/v4-pro/flash）✅；`enabled→high`×2 @ kimi-k2.7-code + qwen3.7 ✅；`minimax-m3` @ opencode ✅；D-5 只认 `"none"` @ openrouter gpt-5.4 ✅ | ✅ |
| C36 | §2.4 例 6：`null` 删除语法支持但配置零使用 | `parser.ts:166` 允许 `null`；`merge-patch.ts:66-69` 执行 delete；119 条 map 中 `null` **0 次** | ✅ |
| C37 | §1.1 五种接入方的方言对照表 | 智谱 anthropic `thinking.type`+`output_config.effort` ✅；DeepSeek 官方 responses `reasoning.effort`（`disabled→"none"`）✅；OpenRouter chat `reasoning.enabled`/`reasoning.effort` ✅；Kimi K3 chat `reasoning_effort`（modelRules values = `["low","high","max"]`）✅；Qwen `enable_thinking`（布尔）✅ | ✅ |
| C38 | `package.json` `private: true`、导出路径 `./src/index.ts` | `packages/model-option-map/package.json` | ✅ 逐字吻合 |
| C39 | `collectWrittenPaths({})` 返回空数组 | `merge-patch.ts:35-49` 循环体在 40-47，空对象不进循环 → 返回 `[]` | ✅ |

---

## 四、遗漏与矛盾

### 4.1 草稿内部矛盾（4 处）

| # | 矛盾点 | 位置 |
|---|---|---|
| **M1** | §2.5 表列出 `\|\|`=2、`!=`=1、`&&`=1、`!`=1，§11.4 表却称"对象字面量 + 三元 + `==` = **100%**" | 第 208-218 行 vs 第 1516 行 |
| **M2** | §12.6 诚实保留"不排除 temperature 在 `runner-options.ts` 以其他方式传递——未通读"，§14 却断言"它不管的：temperature / top_p / 惩罚项 / stop" | 第 1601 行 vs 第 1889 行 |
| **M3** | §5.3 "用户在 UI 上只能改档位值，**不能改 map**" vs 紧随其后"用户可改：`reasoningLevel`（**整个，含 values + map**）" | 第 577 行 vs 第 585 行 |
| **M4** | §0 第 8 条"不做能力降级协商（只有 `enabled: false` 硬禁用）" vs §6.2 类别 A/F 自己承认的"档位降级（`values` 从 5 档收缩到 2 档）"——**values 收缩本身就是能力降级** | 第 18 行 vs 第 626-628、707 行 |

### 4.2 关键机制遗漏（5 处）

#### M5　【最重要】ZCode 的第二条参数路径：`ModelRequestSettings` 直通

- 草稿全文未提。这是与"模型参数处理机制"标题**直接相关**的机制。
- 证据：`apps/zcode-cli/packages/contracts/src/model/index.ts:625-631`（`ModelRequestSettings`）、`apps/zcode-cli/packages/adapters/src/model/runner-options.ts:73-79`（逐字段透传）、`runner-debug.ts:127/236/294`。
- **为什么必须补**：它证明 ZCode 的参数处理是**双轨制** —— "option map 归一化轨（2 个参数）" + "直通透传轨（其余参数）"。草稿只描述了前者的 1/2，把整个机制说成"只管 2 个参数"，会让读者误判 ZCode 的参数层设计。而且**直通轨的行为与我们网关的 `apply_model_params` 完全同级**，直接影响 §11.2 的差距论证。

#### M6　`resolver.ts:264-270` 的"二次 resolve"

```ts
const modelConfig = effectiveModelRules.resolve({ providerId, templateId, modelId, apiType, baseUrl });
const effectiveBuiltinConfig = input.zcodeBuiltinModelRules.resolve({ providerId, templateId, modelId, apiType, baseUrl });
```
- 同一 `(provider, model, apiType, baseUrl)` 会被**解析两次**：一次用"内置 + 个人精确规则"（`effectiveModelRules`），一次**只用内置规则**（`input.zcodeBuiltinModelRules`）。两者**并存**发布给 UI（`resolver.ts:285-286`）。
- 草稿 §12.5 说"`manual-provider-model` 分支的边界情况（如手动规则只改 `enabled` 时系统映射是否保留）**未逐路径验证**" —— 但答案就在这两行：`clearManualModelConfig` 只清掉"手动白名单内的叶子"（`manual-model-config.ts:37-41` + `:43-56 omitSchemaFields`），**系统叶子（如 `maxOutputTokens.map`）保留**；同时 `effectiveBuiltinConfig` 单独留存，UI 可以对比"用户改了什么"。这是 §5.3 和 §12.5 都想回答但没答的问题，源码就在 6 行里。

#### M7　远端配置同步 / 回落机制完全缺席

- 草稿 §12.4 只承认"`zcode-builtin-remote-synchronizer.ts` 的远端同步/回落策略我只读到注释，**未读实现细节**"，**正文完全没有该机制的位置**。
- 真实存在的机制（`packages/provider-node/src/`）：
  - `zcode-builtin-remote-synchronizer.ts` —— 六态结果 `"updated" \| "unchanged" \| "stale" \| "missing" \| "skipped" \| "disposed"`；lease 租约（`leaseId`/`leaseUntil`）、`nextEligibleAt`、`failureCount`、退避参数 `failureBaseDelayMs`/`failureMaxDelayMs`/`successIntervalMs`；跳过原因 `"lease-held" \| "not-due" \| "endpoint-changed"`
  - `endpoint-scoped-zcode-builtin-source.ts`（按 endpoint 隔离配置源）
  - `zcode-builtin-download.ts`
  - `zcode-builtin-cache-paths.ts:38-41`（`zcode-builtin.json` 活跃文件 + `zcode-builtin-refresh.json` 控制文件）
- **为什么必须补**：它直接回答草稿 §8.3 的论断"坏配置不会半生效，整份回退"——回退到哪一份、怎么判定"坏"、多久重试，全在这个模块里。草稿把结论写对了但机制缺失。

#### M8　`packages/provider/src/sources.ts` / `facades.ts` 被跳过

- 草稿 §8.2 的调用图从 `config/provider/zcode-builtin.json` 直接跳到 `provider-node/src/zcode-builtin-release.ts`，**略过了 `ProviderConfigSnapshot` 这一层**。
- 真实：`sources.ts:13-25` 定义 `ProviderConfigSnapshot { revision, zcodeBuiltinRevision, personalRevision, zcodeBuiltinProviders, zcodeBuiltinProviderTemplates, personalProviders, zcodeBuiltinModelRules, personalModels, personalProviderOrder }` —— **规则的实际来源容器**；`facades.ts` 承载 Settings/Selection 的 Registry 投影与写入边界（引用 `ModelConfig`、`ModelConfigRules`、`parseModelConfig`、`serializeRegistryModelConfig`）。
- 二者**不含** `optionSpecs`/`reasoningLevel` 字面量（grep 0 命中），故不属于"参数映射机制"本身，但属于**规则链上游**。草稿若要画完整 L1→L2 的数据流，这一层不应省略。

#### M9　`legacyReasoningLevelRenames` 的真实作用被说反了一半

- **草稿**（§11.3 第 4 条）："`legacy-reasoning-level.ts` 就是在打这个补丁（用 `legacyReasoningLevelRenames` 硬编码旧档位别名 `off` / `nothink` → `disabled`）"
- **真实机制**（`legacy-reasoning-level.ts:35-62`）：
  1. `legacy-reasoning-level-renames.ts` 是一张 **`{ modelMatch, oldLevel }`** 表（≥10 条，`oldLevel ∈ {"off","nothink"}`），按 **modelMatch 精确匹配内置规则**
  2. 用这张表**重建一份新规则集**：把内置规则里 `values` 中的 `"disabled"` **替换成 `oldLevel`**（`:50-52`，即 `disabled → "off"/"nothink"`，**方向是反向的**）
  3. 用**原规则引擎**（`oldRules.resolve(...)`，`:64-70`）重放匹配，得到"历史值域"
  4. `:71` 判断 `values?.includes(oldLevel) ? "disabled" : undefined`
- **即**：不是"off→disabled 的直接映射表"，而是"**把当前规则集回滚成历史值域、再用同一引擎判定旧值是否曾合法**"的兼容层。注释 `:12` 明确其边界："只为历史 Selection 恢复已知 Built-in 旧值域；**不迁移 Personal 配置或在执行层放宽校验**"，`:23-29` 还特意排除"个人层声明过 reasoningLevel 的情况"。
- **修正**：§11.3 第 4 条应改写机制描述；§12.3 可从"未验证"移入正文（表就在 `legacy-reasoning-level-renames.ts`，2218 字节，完全可读）。

### 4.3 "推断写成事实"的检查结果

草稿整体**标注纪律良好**：§12「未验证 / 存疑事项」列了 8 条，且多处用"推测""无法确认"限定。但仍有 **4 处**把推断写成了事实：

| # | 位置 | 问题 |
|---|---|---|
| 1 | §11.4（第 1526 行） | "它是 **MIT/自有许可**下的 866 行实现" —— 许可协议是**可核查的硬事实**，写错了（Apache-2.0）。见 E5 |
| 2 | §6.2（第 634 行） | "（Kimi K3 / GPT-5.4 / Qwen3.8 / **Grok** 等）" —— Grok 在配置中 **0 命中**，属无源引入。见 E14 |
| 3 | §14（第 1889 行） | "它不管的：temperature / top_p / 惩罚项 / stop / …" —— 在 §12.6 自认未通读的前提下下了绝对断言。见 E4 |
| 4 | §5.2（第 491-493 行） | "为什么合理：… 说明**配置写错了**…抛错 = 配置 bug 立刻暴露" —— 这是对**设计意图**的推断（源码无注释支持）。草稿用了"为什么合理"的论证式表述而非"源码注释说明"，**边界基本清晰**，但建议显式标注"（设计意图推断，源码未注释）" |

---

## 五、无法核实的条目

| # | 条目 | 状态 | 说明 |
|---|---|---|---|
| **U1** | `revision: 30` 的实际发布节奏 | 无法核实 | 草稿 §12.4 已自认。需要远端 Release 服务的历史数据，本地不可得 |
| **U2** | `invalid-reasoning-mapping` / `invalid-pattern` 的原设计意图 | 无法核实 | 我只能**确认**这两个枚举成员在全仓 `.ts` 中无生产点（仅 `config-overlay.ts:8-9` 声明 + `dist/config-overlay.d.ts:2` 编译产物），**无法确认**是"历史遗留"还是"预留未实现"。草稿 §12.2 的判断是合理推测，建议保留"推测"字样 |
| **U3** | 性能（三级缓存收益、每请求 `parse+stringify` 开销） | 无法核实 | 无 benchmark。草稿 §12.8 已自认。定性分析（`model-option-map-fetch.ts:22/25` 每请求各一次）成立 |
| **U4** | `dist/` 编译产物与 `src/` 是否完全同步 | **部分核实** | 我抽查了 `packages/provider/dist/config-overlay.d.ts:2` 与 `src/config-overlay.ts:1-14` 一致 ✅；但**未逐文件比对** `packages/model-option-map/dist/*.js` 与 `src/*.ts`。草稿引用 dist 路径仅此 1 处，影响面小 |
| **U5** | §10.1 阶段 6 fetch 链的**运行时**行为 | **部分核实** | 我核对了调用点 `model-execution.ts:508`（`createNetworkProxyFetch`）、`:517`（`createOfficialCodingPlanGatewayFetch`）、`:266`（`createProviderBusinessErrorFetch`）**行号正确** ✅；但**未读这三个工厂的实现**，故"官方套餐走平台网关 / 用户 HTTP 代理"的语义描述无法逐行验证 |
| **U6** | `packages/shared/src/model-execution.ts` 是否与参数处理相关 | 未核实 | 该文件存在（24 行），草稿未引用，我也未展开（超出本次核验范围） |
| **U7** | 草稿 §12.5 提到的"手动规则只改 `enabled` 时系统映射是否保留" | **可核实但草稿未做** | 见 M6 —— 源码 `model-config.ts:395-399` + `manual-model-config.ts:37-56` 已给出答案（系统叶子保留）。这不是"无法核实"，而是**草稿漏做了** |

---

## 六、核验方法与可复现性

本次核验使用的临时脚本（**均在 `/tmp/`，未写入任何项目目录**）：

| 脚本 | 作用 |
|---|---|
| `/tmp/verify_zcode_refs.py` | 提取草稿全部 `路径:行号` 引用，检查文件存在性 / 行号越界 / 打印该行实际内容 |
| `/tmp/verify_zcode_refs2.py` | 上者改进版：basename 后缀加权消歧 + 纳入网关仓库基准；输出明细 `/tmp/verify_zcode_refs.tsv` |
| `/tmp/verify_zcode_config.py` | 复算 `zcode-builtin.json` 规则规模、119 条 map 全量枚举、特性使用率、站点分布 |

关键结论均可用单条命令复现，例如：
```bash
# 复算 478 / 119 / 21 / 4
python3 /tmp/verify_zcode_config.py

# 确认零测试
find packages/model-option-map -type f -not -path "*/node_modules/*" | grep -Ei "test|spec"   # 空

# 确认全库测试文件数（草稿称 144，实为 4）
find . -type f \( -name "*.test.ts" -o -name "*.spec.ts" \) -not -path "*/node_modules/*" | wc -l

# 确认许可
head -3 LICENSE        # Apache License Version 2.0

# 确认 temperature 直通路径
sed -n '73,79p' apps/zcode-cli/packages/adapters/src/model/runner-options.ts
```

**核验边界声明**：
- 本报告只核验草稿对 **ZCode 源码与配置**、以及**网关自身代码**的事实性断言，不评价草稿的**建议本身**是否合理（那是产品决策）。
- 例外：当草稿的建议**建立在错误事实之上**时（E1 / E4 / E5），本报告必须指出，因为那属于"论证前提失真"。

---

## 七、给草稿作者的最小修改清单（按优先级）

| 优先级 | 动作 | 对应错误 |
|---|---|---|
| P0 | 修正 §11.4 的 `100%` → `≈96%`，把"3 个语义"改为"3 主语义 + 1 布尔谓词语义"，并据此补全 §11.4 建议 2 的数据结构（`effort_words` 单 dict 不够） | E1 |
| P0 | 补全 §6.2 漏列的 3 种 map，**特别是 `zcode-builtin.json:2528` 的 openai-responses 全局兜底** | E2 |
| P0 | 修正 §14 对 temperature 等的绝对断言，补 §M5 的第二条参数路径（`ModelRequestSettings` → `runner-options.ts:73-79`），并据此校准 §11.2 的差距表 | E4 / M5 |
| P1 | 修正"144 个测试文件" → 4 个 | E3 |
| P1 | 修正"MIT 许可" → Apache-2.0（+ 合规提示） | E5 |
| P1 | 修正 §13.7 前 4 行行号与"23 → 24 个内置模型" | E6 |
| P2 | 修正 `model-config.ts:122` → `:324` | E7 |
| P2 | 修正 `zcode-builtin-release.ts` 7 处行号 | E8 |
| P2 | 修正 `legacy-reasoning-level.ts` 3 处行号，并把 M9 的真实机制写进 §11.3 / §12.3 | E9 / M9 |
| P2 | 修正 `provider-data-schema.ts` 4 处行号 | E10 |
| P2 | 修正 `model-selection.ts` 2 处行号 | E11 |
| P3 | 修正 `types.ts` "5 个实体" → 9；一元 `!` 计数 → 0；删除 "Grok"；"27 个模型" → "27 条规则" | E12 / E13 / E14 / E15 |
| P3 | 修正 E16-E22（`JsonObject` 不可变、§5.3 句内矛盾、fail-closed 绝对化、`runner.ts:161-162`、`compiler.ts:16/35`、866→867、`2561-2569`） | E16-E22 |
| P3 | 补充 M6（二次 resolve）、M7（远端同步/回落）、M8（`sources.ts`/`facades.ts`）；修正 M1-M4 的内部矛盾 | M1-M8 |

---

## 八、总体判断（一句话）

> 草稿是一份**证据密度极高、行号纪律优秀、统计数字全对**的深度报告，其"机制描述层"（分层、编译时机、RFC 7386 合并、冲突守卫、三态 overlay、优先级链）**基本可信、可以放心引用**；
> 但其"**语义归纳层**"存在系统性过度推断——把 119 条真实规则简化成"3 个语义、100% 只用 `==`"，漏掉了 `\|\|`/`&&`/`!=`/链式三元与 3 种未归类 map，**直接导致最核心的"不要引入 DSL"建议的数据支撑失真**；
> 同时有 3 个可核查硬数字/事实错误（144 个测试文件、MIT 许可、23 个内置模型）和 1 处"未通读即下绝对断言"（temperature），以及 5 处关键机制遗漏（最严重的是 ZCode 的第二条参数路径 `ModelRequestSettings`）。
> **修正上述 6 处严重错误后，本报告可作为网关参数层设计的可靠输入；未修正前，§11.4 与 §14 的结论不应直接用于技术选型决策。**
