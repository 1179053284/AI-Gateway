# 01 · ZCode「模型参数 / 能力归一化机制」深度调研（定稿）

> **本文件回答用户问题一**：智谱 ZCode 内部那套机制 —— 同一个模型（如 DeepSeek V4 Pro）在不同提供商（商汤 / 字节 / 阿里）下参数协议不同、推理强度定义不同、上下文大小定义不同 —— 它是**靠什么把它统一成一套**的；以及这套机制**在我们网关怎么落地**。
> 调研对象：`/Users/w/Desktop/01-关注的开源项目/ZCode`（**全程只读，零改动**）
> 调研方法：源码精读 + 配置数据统计（对 `config/provider/zcode-builtin.json` 全量遍历）
> 写作约定：**【代码】**= 直接读到的代码事实；**【推断】**= 未经代码直接证实的推断；**【未验证】**= 卡住没证实
> 基线：`zcode-builtin.json` revision 30（6212 行）；行号均为实际读取所得
> 上一版（v1）结论有偏差，已被本文取代，原文归档在 `_v1-archive/03-ZCode模型参数处理机制.md`

---

## 0. TL;DR（结论先行）

**v1 的核心结论「ZCode 只归一化 2 个参数」在字面上对、在机制上严重不完整。**

准确表述应该是：

> ZCode 只有 **一条 DSL 归一化轨**（确实只覆盖 `reasoningLevel` / `maxOutputTokens` 两个**变量**），
> 但这条轨的**输出形态完全由配置驱动**——同一条轨可以为不同「模型 × 协议 × 站点」写出任意 JSON 路径、任意键名、任意嵌套结构。
> 再加上一条**独立的能力/元数据声明轨**（contextWindow / 模态 / 工具 / 结构化输出 等 8 个能力位，走的是「多层 overlay 求值」而不是 DSL），
> 以及一条**直通透传轨**（temperature / topP / topK / 惩罚项 / stop / seed），
> 三轨合起来才构成完整机制。

### 三条最关键的机制

| # | 机制 | 一句话 | 关键证据 |
|---|---|---|---|
| **M1** | **DSL 变量少 ≠ 归一化能力弱** | 变量只有 2 个，但**值域本身是可配置的**（17 种非空 `reasoningLevel.values` 值域 + 1 种空值域），且 **map 可输出任意 JSON 路径**（20 种真实推理表达式、3 种输出上限字段名）。变量少是为了让「用户可选档位」有确定语义，不是能力边界。 | `types.ts:9`；`zcode-builtin.json` 全量统计（口径见 §6 开头说明） |
| **M2** | **「站点」= baseUrl 正则，是一等公民** | 规则有 5 个层次：model → model×apiType → model×apiType×baseUrl → template×model → providerId×model。**baseUrl 参与匹配**，所以「同一个 DeepSeek V4 Pro，在 opencode 站 vs DeepSeek 官方站」会命中完全不同的规则。 | `model-config.ts:387-423`；`rule-data-schema.ts:35-38` |
| **M3** | **能力位（含 contextWindow）走 overlay 求值，且真的参与请求** | `contextWindow` / `inputFormat` / `supportsToolCall` / `supportsJsonSchemaOutput` … 是 8 个 schema 化字段，按 overlay 逐字段合并；**不是 UI 装饰**——contextWindow 驱动 auto-compact 阈值、inputFormat 驱动多模态降级、supportsToolCall/supportsJsonSchemaOutput 驱动请求前硬校验。 | `model-config.ts:177-244`；`compact/policy.ts:67-88`；`model.ts:155-185` |

### 对 v1 的三条更正

| v1 的说法 | 更正 |
|---|---|
| 「只归一化了 2 个参数」 | 只归一化了 2 个 **DSL 变量**；另有 **8 个能力位**走 schema+overlay 轨，以及 **contextWindow** 这一用户最关心的维度。总数是 **2 变量 + 8 能力位**，且这 2 个变量在 52 条站点规则 / 72 条协议规则下**行为各异**。 |
| 「上下文窗口不在其中」（v1 缺失） | contextWindow 定义在 `packages/shared/src/model-config.ts:71`，被 `modelRules`（81 次）与 `providerSiteRules`（26 次）覆写，共 **16 种不同取值**；并且**真的参与请求链路**（auto-compact 阈值分母，`compact.ts:194`）。 |
| 「建议不引入 DSL」 | DSL 的**语法确实极窄**（无成员访问、无函数调用、单标量入参），但它的价值不在语法而在**「把方言差异从代码挪进配置」**。我们网关的 `inject_reasoning_into_body` 硬编码单一方言（`ir.py:94-111`），接新厂商必须改代码——这是真实痛点，建议**引入「方言表」而非完整 DSL**（见 §11）。 |

---

## 1. 机制全景与四层架构

### 1.1 模块依赖方向（自底向上）

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ④ 执行层  apps/zcode-cli/packages/adapters/src/model/                   │
│    runner.ts ──► model-execution.ts ──► model-option-map-fetch.ts       │
│    model.ts（能力校验） runner-options.ts（采样参数透传）                 │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ 消费 ModelConfig（已求值）
┌──────────────────────────────▼──────────────────────────────────────────┐
│ ③ 求值层  packages/provider/src/                                        │
│    resolver.ts（ProviderConfigResolver）→ 产出 ResolvedProviderModel    │
│    config/model-config.ts（ModelConfigRules.resolve 多层 overlay）       │
│    registry.ts（validateModelSelectionOptions 档位校验）                 │
│    effective-model-selection.ts（含 legacy 别名恢复）                    │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ 消费规则数组
┌──────────────────────────────▼──────────────────────────────────────────┐
│ ② 契约层  packages/shared/src/model-config.ts（zod schema + 编译期校验） │
│           packages/model-option-map/src/（受限 CEL DSL）                 │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ 装载
┌──────────────────────────────▼──────────────────────────────────────────┐
│ ① 数据层  config/provider/zcode-builtin.json（6212 行，revision 30）     │
│           packages/provider-node/src/zcode-builtin-*.ts（远程同步/缓存）  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 `model-option-map` 包（8 个源文件，共 ~31KB）

| 文件 | 职责 | 关键导出 |
|---|---|---|
| `tokenizer.ts` | 受限 CEL 词法 | `tokenizeRestrictedCel` |
| `parser.ts` | 受限 CEL 语法（Pratt 式递归下降） | `parseRestrictedCel` |
| `evaluator.ts` | 求值（单标量入参） | `evaluateRestrictedCel` |
| `compiler.ts` | 编译 + 三级缓存 | `compileRestrictedCel` / `compileModelOptionMap` |
| `merge-patch.ts` | RFC7386 式 JSON Merge Patch + 路径冲突守卫 | `applyOrderedJsonMergePatches` |
| `option-maps.ts` | 把 2 个 map 组装成「body → body」 | `compileModelOptionMaps` |
| `types.ts` | 类型与错误 | `ModelOptionName` 等 |
| `index.ts` | barrel | — |

**【代码】** `types.ts:9`：
```ts
export type ModelOptionName = "reasoningLevel" | "maxOutputTokens";
```
**【代码】** `types.ts:8`：`export type RestrictedCelValue = string | number;`

→ 这就是「只有 2 个变量、且入参是单标量」的源头。**这是编译期常量，加第 3 个变量必须改这个包的源码**（不是配置能解决的）。**【推断】** 这是有意的产品约束：只有「用户可选档位」语义明确的参数才值得进 DSL。

### 1.3 `provider` / `provider-node` 的分工

- `packages/provider`：纯领域逻辑（无 IO）。`ProviderConfigResolver` 是唯一求值入口（`resolver.ts:182-344`）。
- `packages/provider-node`：Node 侧 IO——把 JSON 文件读成规则、远程同步、缓存、endpoint 隔离（`endpoint-scoped-zcode-builtin-source.ts:28-133`）。

**【代码】** `packages/provider/src/config/schema.ts:78-107` 定义规则数组的**装配顺序**（这直接决定优先级，见 §4）：
```
modelRules → modelApiRules → providerSiteRules → templateModelRules → builtinProviderModelRules
```

### 1.4 数据规模（`zcode-builtin.json` 实测）

| 分组 | 条数 | 能写什么 |
|---|---|---|
| `modelRules` | 84 | 纯按模型名正则（`contextWindow` / `optionSpecs` / 模态） |
| `modelApiRules` | 72 | 模型 × `apiType` |
| `providerSiteRules` | 52 | 模型 × `apiType` × `baseUrl` |
| `templateModelRules` | 244 | `templateId` × `modelId`，**只有 `enabled`** |
| `builtinProviderModelRules` | 26 | `providerId` × `modelId`，**只有 `enabled`** |

**【代码】** 用 Python 统计 `templateModelRules` 的字段分布 = `{'enabled': 244}`——确认这两个「精确层」只做开关，不做能力/参数覆写。

---

## 2. 语法 / 编译 / 求值：DSL 到底能做什么

### 2.1 词法（`tokenizer.ts`）

**【代码】** `tokenizer.ts:18-20`：
```ts
const DOUBLE_OPERATORS = new Set(["&&", "||", "==", "!=", "<=", ">="]);
const SINGLE_OPERATORS = new Set(["+", "-", "*", "/", "%", "!", "<", ">"]);
const PUNCTUATION = new Set(["{", "}", "[", "]", "(", ")", ",", ":", "?", "."]);
```
字面量：数字（含小数/科学计数）、单双引号字符串（含 `\uXXXX` 转义，`tokenizer.ts:106-121`）、标识符 `[A-Za-z_][A-Za-z0-9_]*`（`:46-51`）。**没有模板字符串、没有注释、没有分号。**

### 2.2 语法（`parser.ts`）

支持的表达式类型（`parser.ts:4-44`）：`literal` / `input` / `array` / `object` / `unary` / `binary` / `conditional`。

**明确不支持**（这三条是硬边界）：
```ts
// parser.ts:65-70
if (trailing.value === ".") throw new RestrictedCelError("member access is not supported", ...);
if (trailing.value === "(") throw new RestrictedCelError("function calls are not supported", ...);
```

### 2.3 求值环境：**独立复核 v1 的「只有一个标量输入」结论**

v1 说「只有一个标量输入」。我独立复核：**结论成立**，证据是三处独立的硬编码：

**(a) 变量名是编译期参数，只认一个标识符**
```ts
// parser.ts:158-171
if (token.kind === "identifier") {
  if (this.current().value === "(") throw new RestrictedCelError("function calls are not supported", ...);
  if (token.value === this.variableName) return { type: "input", offset: token.offset };
  if (token.value === "true" || token.value === "false") { ... }
  if (token.value === "null") return { type: "literal", value: null, offset: token.offset };
  throw new RestrictedCelError(`unknown identifier ${JSON.stringify(token.value)}`, token.offset);
}
```
→ 任何不在 `{变量名, true, false, null}` 里的标识符都抛错。**没有 `modelId`、没有 `provider`、没有 `apiType`、没有 `request`。**

**(b) 求值入口签名只有 `(expression, input)`**
```ts
// evaluator.ts:9-15
export function evaluateRestrictedCel(expression, input: RestrictedCelValue): JsonValue {
  assertRestrictedCelValue(input, expression.offset);
  return freezeJson(evaluate(expression, input));
}
// evaluator.ts:17-22 —— "input" 分支直接返回标量
case "input": return input;
```

**(c) 运行时断言入参只能是 string | number**
```ts
// evaluator.ts:168-178
function assertRestrictedCelValue(value: unknown, offset: number): asserts value is RestrictedCelValue {
  if (typeof value === "string") return;
  if (typeof value === "number") { assertNumber(value, offset); return; }
  throw new RestrictedCelError("input value must be a string or number", offset);
}
```

**所以 DSL 内部确实无法感知「当前是哪个模型/哪个站点」——但这个信息并不是丢掉了，而是被用在了「选规则」阶段（§4），而不是「算 map」阶段。** 这是理解整个机制的关键：**上下文由规则匹配层承担，DSL 只承担「值 → JSON 片段」的纯函数映射。**

**【推断】** 这是刻意的关注点分离：把「哪些参数、在什么场景」交给声明式规则（可热更新、可远程下发），把「值怎么变成 JSON」交给无副作用纯函数（可缓存、可审计、不会读到请求体）。

### 2.4 编译期校验（`compiler.ts`）

- 三级缓存：`programCache` / `optionMapCache` / `expressionCache`，cacheKey = `` `${variableName}\0${source}` ``（`compiler.ts:76-78`）。
- **编译期就断言返回值必须是对象**（`compiler.ts:80-88`）：
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
→ 三元的**两个分支都必须返回对象字面量**。这排除了「某分支返回 `{}`、某分支返回 `null`」之类的写法。

### 2.5 与 schema 的耦合：**配置加载期即编译**

**【代码】** `packages/shared/src/model-config.ts:5-19`：
```ts
function optionMapSchema(variableName: "reasoningLevel" | "maxOutputTokens") {
  return z.string().min(1).superRefine((source, context) => {
    try { compileModelOptionMap(source, variableName); }
    catch (error) { context.addIssue({ code: "custom", message: ... }); }
  });
}
```
→ **map 语法错误在配置解析阶段就被 zod 拒绝**，不会留到请求期。对应错误码 `invalid-option-spec`（`config-overlay.ts:7`，由 `schema-validation.ts:32-34` 在 `issue.path.includes("optionSpecs")` 时给出）。

---

## 3. 三层规则数据模型（这是「同模型不同标准」的载体）

### 3.1 `reasoningLevel` 的 spec 结构

**【代码】** `shared/src/model-config.ts:21-35`：
```ts
export const completeEnumOptionSpecDataSchema = z.object({
  /** 按语义强度从低到高排列；首项是辅助调用可选的最低公开档位。 */
  values: z.array(z.string().refine(v => v.trim().length > 0))
           .min(1, "reasoningLevel.values 不能为空")
           .refine(v => new Set(v).size === v.length, "reasoningLevel.values 不能重复")
           .readonly(),
  map: optionMapSchema("reasoningLevel"),
}).strict();
```

**三个语义要点：**
1. `values` **有序**——`provider-registry-selection.ts:196` 取 `defaultLevel: reasoning.values.at(-1)`，即**末项是默认档**（= 最高档）。
2. `values` **非空且去重**——所以「某站点不支持推理」不能靠空数组表达。**【代码】** 实测 `zcode-builtin.json` 里 `["enabled"]` 是最窄的值域（8 次），不是空数组。
3. `values` 与 `map` **可以分层覆写**：`modelRules` 给 `values`、`modelApiRules` 给 `map`，二者**字段级合并**（见 §3.4 实例）。

### 3.2 `maxOutputTokens` 的 spec 结构

**【代码】** `shared/src/model-config.ts:37-42`：
```ts
export const completeLimitOptionSpecDataSchema = z.object({
  max: z.number().int().positive(),
  map: optionMapSchema("maxOutputTokens"),
}).strict();
```
`max` 是**网关侧的上限校验值**（`model.ts:106-118` 会拒绝 `> max` 的请求），`map` 是**厂商方言**。二者同样是可分层覆写的两个字段。

### 3.3 8 个能力位（**v1 缺失的部分**）

**【代码】** `shared/src/model-config.ts:68-79`：
```ts
export const completeModelPropertiesDataSchema = z.object({
  requiresMfjsToolSchema: z.boolean(),
  contextWindow: z.number().int().positive(),          // ★ 上下文窗口在这里
  inputFormat: completeModelInputFormatDataSchema,      // 5 个模态位
  outputFormat: completeModelOutputFormatDataSchema,    // 1 个位
  supportsToolCall: z.boolean(),
  supportsJsonSchemaOutput: z.boolean(),
  supportsNativeWebSearch: z.boolean(),
  supportsMidConversationSystem: z.boolean(),
}).strict();
```
**【代码】** `shared/src/model-config.ts:51-60`：`inputFormat = {supportsText, supportsImage, supportsVideo, supportsAudio, supportsPdf}`（5 位），`outputFormat = {supportsText}`（1 位）。

合计 **7 + 5 + 1 = 13 个能力叶子**，全部是 `boolean` 或 `positive int`。

**【代码】** 每一层规则都能覆写任意子集（sparse），因为稀疏版本 schema 用 `sparseShape()` 生成（`shared/src/model-config.ts:80-86`）。**这就是「按站点覆写能力位」的机制来源。**

### 3.4 ★ 实例：同一模型的 `values` 与 `map` 来自不同层

**`qwen3.7-max` 在 opencode 站（anthropic-messages）** 的最终 spec 由 3 层拼成：

| 层 | 位置 | 贡献 |
|---|---|---|
| `modelRules[0]`（`.*` 兜底） | `zcode-builtin.json:866-898` | `values: ["disabled","enabled"]`、`map: "{}"`、`contextWindow: 200000`、`maxOutputTokens.max: 32000` |
| `modelApiRules[1]`（`.*` × anthropic-messages） | `zcode-builtin.json:2494-2507` | `map` = `thinking.type` + `output_config.effort` 方言；`maxOutputTokens.map` = `{'max_tokens': …}` |
| `providerSiteRules[20]`（qwen3.7-max × anthropic × opencode） | `zcode-builtin.json:3861-3887` | `values: ["disabled","enabled"]`、`contextWindow: 1000000`、`maxOutputTokens.max: 65536` |

→ 最终 `map` 来自第 2 层，`values` 来自第 3 层，**没有任何一层需要写全**。这是字段级 overlay 的直接体现。

---

## 4. 合并语义与优先级（**以代码为准，不照抄注释**）

### 4.1 优先级 = 规则数组顺序，**后者覆盖前者**

**【代码】** `packages/provider/src/config/model-config.ts:387-423`（`ModelConfigRules.resolve`）——顺序遍历，逐条 overlay：
```ts
resolve(input: ModelConfigRuleResolutionInput): ModelConfig {
  let result = ModelConfig.empty();
  const baseUrl = input.baseUrl == null ? undefined : normalizeBaseURLForRuleMatch(input.baseUrl);
  for (const rule of this.#rules) {
    if (isExactModelRule(rule)) {
      if (rule.providerId !== input.providerId || rule.modelId !== input.modelId) continue;
      result = (rule.type === "manual-provider-model"
          ? ModelConfig.fromData(clearManualModelConfig(result.toJSON()))
          : result).overlay(rule.config);
      continue;
    }
    if (rule.type === "template-model") {
      if (rule.templateId === input.templateId && rule.modelId === input.modelId)
        result = result.overlay(rule.config);
      continue;
    }
    if (!matchesRule(rule.modelMatch, input.modelId, true)) continue;
    if ((rule.type === "model-api" || rule.type === "provider-site") && rule.apiTypeMatch !== undefined) {
      if (input.apiType == null || !matchesRule(rule.apiTypeMatch, input.apiType)) continue;
    }
    if (rule.type === "provider-site" && (baseUrl === undefined || !matchesRule(rule.baseUrlMatch, baseUrl))) continue;
    result = result.overlay(rule.config);
  }
  return result;
}
```

**由此推出的真实优先级（低 → 高）：**

| 序 | 层 | 匹配键 | 位置 |
|---|---|---|---|
| 1 | `model` | `modelMatch`（**忽略大小写**） | `model-config.ts:408` |
| 2 | `model-api` | 上 + `apiTypeMatch`（**区分大小写**） | `model-config.ts:410-414` |
| 3 | `provider-site` | 上 + `baseUrlMatch`（**区分大小写**） | `model-config.ts:415-419` |
| 4 | `template-model` | `templateId` + `modelId` 精确 | `model-config.ts:402-406` |
| 5 | `provider-model`（builtin） | `providerId` + `modelId` 精确 | `model-config.ts:391-401` |
| 6 | `provider-model`（personal） | 同上 | `composeEffective:379-381` |
| 7 | `manual-provider-model`（personal 手动） | 同上 | 同上 |

**【代码】** `model-config.ts:544-546` 确认大小写语义：
```ts
function matchesRule(pattern: string, value: string, ignoreCase = false): boolean {
  return new RegExp(`^(?:${pattern})$`, ignoreCase ? "i" : undefined).test(value);
}
```
→ 调用点 `:408` 传 `true`（modelMatch 忽略大小写）；`:413`/`:417` 不传（apiType/baseUrl 区分大小写）。

**【代码】** `composeEffective`（`model-config.ts:379-381`）：个人规则只追加**精确规则**，不追加模式规则：
```ts
static composeEffective(builtin: ModelConfigRules, personal: ModelConfigRules): ModelConfigRules {
  return new ModelConfigRules([...builtin.rules(), ...personal.rules().filter(isExactModelRule)]);
}
```

### 4.2 三态语义：`undefined` / `null` / 有值

**【代码】** `packages/provider/src/config-overlay.ts:26-37`：
```ts
protected overlayValue<T>(base: T | undefined, next: T | undefined): T | undefined {
  return next === undefined ? base : next;          // undefined=继承；null/有值=替换
}
protected overlayConfig<T extends ConfigOverlay<T>>(base, next) {
  if (next === undefined) return base;              // undefined=继承
  if (next === null || base === null || base === undefined) return next;  // null=清空整棵子树
  return base.overlay(next);                        // 否则递归 overlay
}
```

| 写法 | 语义 |
|---|---|
| 字段**缺失**（`undefined`） | **继承**上一层 |
| 字段 = `null` | **显式清空**（标量清为 null；子树整体替换为 null） |
| 字段 = 有值 | 替换（标量）/ 递归合并（子树） |

**【代码】** 实测 `zcode-builtin.json` 里 `grep -c ": null"` = **0** → **内置数据完全没用到 `null` 清空路径**。**【推断】** 该能力是为「用户手动配置要抹掉系统默认」保留的（对应 `clearManualModelConfig`，见 §9），属于预留语义，内置库未使用。

### 4.3 冲突处理：**覆盖，不抛错**（与 option-map 层不同！）

**关键区分：两层有不同的冲突策略。**

- **规则层（ModelConfigRules.resolve）**：`overlay` 静默覆盖，**不抛错**。所以「后写的赢」是唯一规则。
- **option-map 层（`applyOrderedJsonMergePatches`）**：**写同一 JSON 路径直接抛错**（fail-closed）。

**【代码】** `packages/model-option-map/src/merge-patch.ts:13-33`：
```ts
export function applyOrderedJsonMergePatches(body, patches): JsonObject {
  const ownedPaths: OwnedPath[] = [];
  let result = cloneJson(body) as JsonObject;
  for (const namedPatch of patches) {
    const paths = collectWrittenPaths(namedPatch.patch);
    for (const path of paths) {
      const conflict = ownedPaths.find((owned) => pathsOverlap(owned.path, path));
      if (conflict) throw new ModelOptionMapError(
        `Model option maps write conflicting JSON path ${formatPath(path)}: ${conflict.option} and ${namedPatch.option}`);
      ownedPaths.push({ option: namedPatch.option, path });
    }
    result = mergeObject(result, namedPatch.patch);
  }
  return result;
}
```
**【代码】** `merge-patch.ts:51-57` `pathsOverlap` 把「前缀关系」也算冲突（`{"a":1}` vs `{"a":{"b":2}}` → 冲突）。

### 4.4 JSON Merge Patch 语义（`merge-patch.ts:63-78`）

```ts
function mergeObject(target, patch) {
  const result = cloneJson(target);
  for (const [key, patchValue] of Object.entries(patch)) {
    if (patchValue === null) { delete result[key]; continue; }   // ★ null = 删除键
    if (isJsonObject(patchValue)) { result[key] = mergeObject(...); continue; }
    result[key] = cloneJson(patchValue);
  }
  return result;
}
```
→ **`null` 在 patch 里表示「从请求体中删除该键」**，而不是「设为 null」。这比我们网关的 `apply_model_params`（`if body.get(k) is None: body[k] = v`，把显式 null 与缺失当同一件事，`ir.py:68`）语义更清晰。

### 4.5 注入点：**在 fetch 拦截器里**

**【代码】** `apps/zcode-cli/packages/adapters/src/model/model-option-map-fetch.ts:13-31`：
```ts
export function createModelOptionMapFetch(input: {capture?, fetch, maps, values}): ProviderFetch {
  return async (request, init) => {
    const bodyText = await readRequestBody(request, init);
    if (bodyText === undefined) return input.fetch(request, init);
    const body = parseJsonObject(bodyText);
    const patched = input.maps.apply(body, input.values);      // ★ 唯一注入点
    if (input.capture) input.capture.body = patched;
    const patchedBody = JSON.stringify(patched);
    if (request instanceof Request) return input.fetch(new Request(request, {...init, body: patchedBody}));
    return input.fetch(request, {...init, body: patchedBody});
  };
}
```

**【代码】** 装配在 `model-execution.ts:266-279`：option map fetch 包在 provider business-error fetch **外层**（先 patch body，再交给业务错误检测）。
```ts
const fetch = createProviderBusinessErrorFetch({ fetch: providerTransport, providerId, providerKind });
const optionFetch = optionMaps && optionValues
  ? createModelOptionMapFetch({ capture: rawRequestBodyCapture, fetch, maps: optionMaps, values: optionValues })
  : fetch;
```

**这意味着：AI SDK 已经序列化完 body（含它自己生成的 `reasoning` / `max_tokens` 等字段），ZCode 在最后一步把「用户选定的档位」翻译成该厂商的方言覆盖上去。** 一处生效，与 SDK 版本解耦。**【推断】** 这也是为什么它能同时兼容 openai / anthropic / openai-compatible 三种 SDK kind（`model-execution.ts:281-317`）而不用为每种写一套参数适配。

**fail-closed 语义**（`model-option-map-fetch.ts:33-45`）：
```ts
if (typeof init?.body === "string") return init.body;
// Option Map 是 reasoning/max-output 的唯一请求字段权威。若 SDK 改成非文本 Body 却静默
// 跳过 Patch，请求仍会发出但丢失两个 Option；因此有 Body 时必须 fail-closed。
if (init?.body !== undefined && init?.body !== null) {
  throw new Error("Model option maps require a JSON text request body.");
}
if (request instanceof Request) return request.clone().text();
return undefined;   // ← 既无 init.body 也不是 Request 时，静默跳过 patch
```
**【代码】** 注意最后一行：**「取不到 body 文本」时是静默跳过，不是抛错**。所以 fail-closed 只覆盖「有非文本 body」这一种情况。

---

## 5. 内置规则库实证：同一模型多站点差异（**用户最关心的核心证据**）

### 5.1 站点身份 = `baseUrlMatch` 正则

**【代码】** `packages/provider/src/config/rule-data-schema.ts:35-38`：
```ts
export const providerSiteMatchConfigRuleSchema = modelMatchConfigRuleSchema.extend({
  baseUrlMatch: patternSchema,
  apiTypeMatch: patternSchema.optional(),
});
```
**【代码】** baseUrl 匹配前会规范化（`model-config.ts:548-559`）：用 `URL` parser 去掉尾部斜杠、统一 host 大小写与默认端口，**但保留 path/query 大小写**。

**站点清单（`providerSiteRules` 覆盖的 baseUrl，共 52 条规则）：**

| 站点 baseUrl | 出现次数 | 备注 |
|---|---|---|
| `https://opencode.ai/zen/go/v1` | 26 | 单站覆盖 26 个模型（**最大的一块**） |
| `https://openrouter.ai/api` | 10 | 聚合站 |
| `https://api.deepseek.com` | 4 | DeepSeek 官方 |
| `https://api.z.ai/api/anthropic` | 3 | Z.ai |
| `https://open.bigmodel.cn/api/anthropic` | 3 | 智谱 |
| `https://zcode.z.ai/api/v1/zcode-plan/anthropic` | 3 | ZCode 平台网关 |
| `https://dashscope.aliyuncs.com/apps/anthropic` | 1 | 阿里云百炼（国内） |
| `https://dashscope-intl.aliyuncs.com/apps/anthropic` | 1 | 阿里云百炼（国际） |
| `https://api.anthropic.com/v1` | 1 | Anthropic 官方 |
| `https://api.moonshot.cn/anthropic` | 1 | 月之暗面 |
| `https://zcode.z.ai/api/v1/off-peak/anthropic` | 1 | 闲时 |

### 5.2 ★★ 证据 A：`deepseek-v4-pro` 在 **3 个不同站点/协议** 下的完整差异

**原文片段 1 —— opencode 站（openai-chat-completions），`zcode-builtin.json:3520-3548`：**
```json
{
  "modelMatch": "deepseek-v4-pro",
  "apiTypeMatch": "openai-chat-completions",
  "baseUrlMatch": "https://opencode\\.ai/zen/go/v1/?",
  "config": {
    "properties": {
      "contextWindow": 1000000,
      "inputFormat": { "supportsText": true, "supportsImage": false, "supportsVideo": false, "supportsPdf": false, "supportsAudio": false },
      "supportsJsonSchemaOutput": true,
      "supportsNativeWebSearch": false
    },
    "optionSpecs": {
      "reasoningLevel": {
        "values": ["high", "max"],
        "map": "{\"reasoning_effort\": reasoningLevel}"
      },
      "maxOutputTokens": { "max": 384000, "map": "{\"max_tokens\": maxOutputTokens}" }
    }
  }
}
```

**原文片段 2 —— DeepSeek 官方站（openai-responses），`zcode-builtin.json:4148-4162`：**
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

**原文片段 3 —— 模型层基线（与站点无关），`zcode-builtin.json:2045-2065`：**
```json
{
  "modelMatch": ".*deepseek-v4-pro(?:[.\\-:/\\[].*)?",
  "config": {
    "properties": {
      "contextWindow": 1000000,
      "inputFormat": { "supportsImage": false, "supportsVideo": false },
      "supportsJsonSchemaOutput": false
    },
    "optionSpecs": {
      "reasoningLevel": { "values": ["disabled", "low", "high", "max"] },
      "maxOutputTokens": { "max": 384000 }
    }
  }
}
```

**原文片段 4 —— 协议层（anthropic-messages），`zcode-builtin.json:2912-2922`：**
```json
{
  "modelMatch": ".*deepseek-v4-pro(?:[.\\-:/\\[].*)?",
  "apiTypeMatch": "anthropic-messages",
  "config": {
    "optionSpecs": {
      "reasoningLevel": {
        "map": "reasoningLevel == \"disabled\"\n  ? {\n      \"thinking\": {\n        \"type\": \"disabled\"\n      }\n    }\n  : {\n      \"thinking\": {\n        \"type\": \"enabled\"\n      },\n      \"output_config\": {\n        \"effort\": reasoningLevel\n      }\n    }"
      }
    }
  }
}
```

**原文片段 5 —— 协议层（openai-chat-completions），`zcode-builtin.json:2923-2933`：**
```json
{
  "modelMatch": ".*deepseek-v4-pro(?:[.\\-:/\\[].*)?",
  "apiTypeMatch": "openai-chat-completions",
  "config": {
    "optionSpecs": {
      "reasoningLevel": {
        "map": "reasoningLevel == \"disabled\"\n  ? {\n      \"thinking\": {\n        \"type\": \"disabled\"\n      }\n    }\n  : {\n      \"thinking\": {\n        \"type\": \"enabled\"\n      },\n      \"reasoning_effort\": reasoningLevel\n    }"
      }
    }
  }
}
```

**汇总表（同一个 `deepseek-v4-pro`）：**

| 站点 / 协议 | 可选档位 `values` | 出站字段形态 | contextWindow | maxOutput |
|---|---|---|---|---|
| **基线**（modelRules） | `disabled, low, high, max` | 未定义（由协议层补） | 1,000,000 | 384,000 |
| **opencode** / openai-chat | **`high, max`**（收窄） | `{"reasoning_effort": <level>}` | 1,000,000 | 384,000 |
| **DeepSeek 官方** / openai-responses | 继承基线 | `{"reasoning":{"effort": disabled→"none"}}` | 继承 1,000,000 | 继承 384,000 |
| **任意站** / anthropic-messages | 继承基线 | `{"thinking":{"type":…}, "output_config":{"effort":…}}` | 继承 | 继承 |
| **任意站** / openai-chat | 继承基线 | `{"thinking":{"type":…}, "reasoning_effort":…}` | 继承 | 继承 |

→ **「对接的参数协议不一样」= 同一模型在 3 种协议下写 3 种完全不同的 JSON；「推理强度怎么设不一样」= 同一模型在 opencode 站只有 2 档、在别处有 4 档。**

### 5.3 ★★ 证据 B：`glm-5.1` —— 站点同时改「上下文窗口」和「推理档位」

**原文片段 1 —— 模型层，`zcode-builtin.json:1009` 起**（`modelRules[8]`，pattern `.*glm-5\.1(?:[.\-:/\[].*)?`）：`contextWindow: 200000`、`values: ["disabled","enabled"]`（实测统计，见 §5.5 表）。

**原文片段 2 —— opencode 站，`zcode-builtin.json:3375-3400`：**
```json
{
  "modelMatch": "glm-5\\.1",
  "apiTypeMatch": "openai-chat-completions",
  "baseUrlMatch": "https://opencode\\.ai/zen/go/v1/?",
  "config": {
    "properties": {
      "contextWindow": 202752,
      "inputFormat": { "supportsText": true, "supportsImage": false, "supportsVideo": false, "supportsPdf": false, "supportsAudio": false },
      "supportsJsonSchemaOutput": false,
      "supportsNativeWebSearch": false
    },
    "optionSpecs": {
      "reasoningLevel": { "values": ["enabled"], "map": "{}" },
      "maxOutputTokens": { "max": 32768, "map": "{\"max_tokens\": maxOutputTokens}" }
    }
  }
}
```
→ 同一个 `glm-5.1`：**contextWindow 从 200000 变 202752；可选档位从 2 档收窄到只剩 `["enabled"]`；map 被显式覆盖为 `"{}"`（= 该站点不注入任何推理字段）。**

### 5.4 ★★ 证据 C：`kimi-k3` —— 站点把档位收窄到只剩 1 档

**原文片段 —— opencode 站，`zcode-builtin.json:3404-3429`：**
```json
{
  "modelMatch": "kimi-k3",
  "apiTypeMatch": "openai-chat-completions",
  "baseUrlMatch": "https://opencode\\.ai/zen/go/v1/?",
  "config": {
    "properties": {
      "contextWindow": 1048576,
      "inputFormat": { "supportsText": true, "supportsImage": true, "supportsVideo": true, "supportsPdf": false, "supportsAudio": false },
      "supportsJsonSchemaOutput": true,
      "supportsNativeWebSearch": false
    },
    "optionSpecs": {
      "reasoningLevel": { "values": ["max"], "map": "{\"reasoning_effort\": reasoningLevel}" },
      "maxOutputTokens": { "max": 131072, "map": "{\"max_tokens\": maxOutputTokens}" }
    }
  }
}
```
对比 `modelRules[41]`（`zcode-builtin.json:1666` 起）：`contextWindow: 1048576`、`values: ["low","high","max"]`。
→ **站点把 3 档收窄成 1 档（`["max"]`）**，同时把 `supportsImage` / `supportsVideo` 从模型层（默认 false）**放开为 true**——**站点既能收窄也能放宽能力位**。

### 5.5 ★ 证据 D：`deepseek-v4.1-flash` —— contextWindow 被站点改写

**原文片段 —— openrouter 站，`zcode-builtin.json:4214-4235`：**
```json
{
  "modelMatch": ".*deepseek-v4[.-]1-flash(?:[.\\-:/\\[].*)?",
  "apiTypeMatch": ".*",
  "baseUrlMatch": "https://openrouter\\.ai/api(?:/v1)?/?",
  "config": {
    "properties": { "contextWindow": 1048576, "supportsJsonSchemaOutput": true }
  }
},
{
  "modelMatch": ".*deepseek-v4[.-]1-flash(?:[.\\-:/\\[].*)?",
  "apiTypeMatch": "openai-chat-completions",
  "config": {
    "optionSpecs": {
      "reasoningLevel": {
        "map": "reasoningLevel == \"disabled\"\n  ? {\n      \"reasoning\": {\n        \"enabled\": false\n      }\n    }\n  : {\n      \"reasoning\": {\n        \"effort\": reasoningLevel\n      }\n    }"
      }
    }
  },
  "baseUrlMatch": "https://openrouter\\.ai/api(?:/v1)?/?"
}
```
对比 `modelRules[?]`（`zcode-builtin.json:2088` 起，pattern `.*deepseek-v4[.-]1-flash(?:[.\-:/\[].*)?`）：`contextWindow: 1000000`。
→ **同一个模型：模型层 1,000,000，openrouter 站 1,048,576**（后者 = 2^20，是真实物理值；前者是被上游站点声明值）。

### 5.6 全量方言统计（**穷举，可复现**）

用 Python 遍历 `zcode-builtin.json` 五个分组，统计 `optionSpecs` 的 `map` / `values` 去重结果：

> **⚠️ 口径说明（重要，避免误读）**：本节统计的**口径**是「**非 null 的 map 写法**」。
> 全量去重结果是 **22 种**，拆分为：**`null`×1（= 根本没有 map，出现 54 次）** + **21 种非 null 写法**（下表）。
> 而这 21 种里，**`{}`（空 patch，8 次）不是"方言"** —— 它表示"显式不注入"。→ **真实表达式 = 20 种**。
> 值域同理：全量 **18 种** = **17 种非空**（下表）+ **1 种空值域 `[]`（出现 78 次，表示"该模型不支持推理档位"）**。
>
> 另：`maxOutputTokens.map` 去重 **4 种写法 = 3 个字段名**（`max_tokens` / `max_completion_tokens` / `max_output_tokens`），其中 `max_tokens` 有 1 次写成单引号 `'max_tokens'`（`tokenizer.ts:32` 确认单双引号都接受，**不是缺陷，是写法漂移**）。
>
> 上述数字均已纳入机械核验（`drafts-v2/verify-v2.py` 第四层「统计断言」19 条）；归约分析见 `06` §3·不足 4 与 §5.3。

**`reasoningLevel.map` 共 21 种非 null 写法（其中 20 种是真实表达式）：**

| 次数 | 方言（原样） | 归类 |
|---|---|---|
| 27 | `{"thinking":{"type": reasoningLevel == "enabled" ? "enabled" : "disabled"}}` | Anthropic 风格（boolean 二态） |
| 17 | `{"reasoning_effort": reasoningLevel}` | OpenAI 风格 |
| 9 | `{"reasoning":{"effort": reasoningLevel}}` | OpenAI Responses 风格 |
| 8 | `{}` | **不注入**（显式空 patch） |
| 6 | `{"enable_thinking": reasoningLevel == "enabled"}` | 通义/百川风格（boolean） |
| 5 | `reasoningLevel == "disabled" ? {"thinking":{"type":"disabled"}} : {"thinking":{"type":"enabled"},"output_config":{"effort":reasoningLevel}}` | Anthropic + effort 组合 |
| 5 | `{"output_config":{"effort": reasoningLevel}}` | 纯 effort |
| 4 | disabled→`thinking.type=disabled`；否则 `thinking.type=enabled` + `reasoning_effort` | 双写（thinking + reasoning_effort） |
| 3 | `{"thinking":{"type":"adaptive"},"output_config":{"effort": reasoningLevel}}` | **adaptive** 语义（Claude 4.8+） |
| 3 | `{"reasoning":{"effort": disabled → "none" : reasoningLevel}}` | disabled 映射为 `"none"` |
| 2 | `{"thinking":{"type":"enabled"},"output_config":{"effort": reasoningLevel}}` | — |
| 2 | `{"thinking":{"type": disabled ? "disabled" : "enabled"}}` | — |
| 2 | `{"reasoning":{"effort": disabled ? "none" : "high"}}` | 二态压成 effort |
| 1 | disabled→disabled；否则 `thinking.type=adaptive` + `output_config.effort = enabled→"high"` | — |
| 1 | **四键同时写**：`thinking.type` + `enable_thinking` + `reasoning_effort` + `reasoning.effort` | 兼容最大化 |
| 1 | `{"reasoning":{"effort": disabled ? "none" : enabled ? "high" : reasoningLevel}}` | — |
| 1 | `{"thinking":{"type": disabled ? "disabled" : "adaptive"}}` | — |
| 1 | `disabled \|\| none → thinking.type=disabled`；否则 `thinking.type=adaptive` + `output_config.effort` | — |
| 1 | `none → thinking.type=disabled`；否则 `output_config.effort` | — |
| 1 | `disabled → {"reasoning":{"enabled":false}}`；否则 `{"reasoning":{"effort":reasoningLevel}}` | — |
| 1 | `{"reasoning":{"enabled": reasoningLevel == "enabled"}}` | boolean |

**方言家族归纳（4 类字段名）：**
1. **`thinking.type`**（`enabled`/`disabled`/`adaptive`）— Anthropic 系
2. **`reasoning_effort`**（顶层字符串）— OpenAI / 商汤 / opencode 系
3. **`reasoning.effort` / `reasoning.enabled`**（嵌套对象）— OpenAI Responses 系
4. **`output_config.effort`**（嵌套）— Anthropic 新协议
5. **`enable_thinking`**（布尔）— 通义千问系

**`reasoningLevel.values` 共 17 种非空值域（另有 1 种空值域 `[]`，出现 78 次 = "不支持"）：**

| 次数 | 值域 |
|---|---|
| 31 | `["disabled","enabled"]` |
| 11 | `["low","high","max"]` |
| 8 | `["enabled"]`（**单档**） |
| 4 | `["disabled","low","high","max"]` |
| 3 | `["low","medium","high","xhigh"]` |
| 3 | `["low","medium","high","xhigh","max"]` |
| 3 | `["none","low","medium","high","xhigh"]` |
| 3 | `["low","medium","xhigh"]` |
| 2 | `["none","low","medium","high","xhigh","max"]` |
| 2 | `["high","max"]` |
| 1 | `["disabled","high","max"]` |
| 1 | `["medium","high","xhigh"]` |
| 1 | `["none","minimal","low","medium","high","xhigh","max"]`（**7 档最宽**） |
| 1 | `["max"]`（**单档**） |
| 1 | `["none","high"]` |
| 1 | `["none","low","high"]` |
| 1 | `["minimal","low","medium","high","xhigh"]` |

→ **「档位名称」本身不是标准**：有 `disabled/enabled`、`none/minimal/low/medium/high/xhigh/max`、`off/nothink`（历史名，见 §8）等等。

**`maxOutputTokens.map` 共 4 种方言：**

| 次数 | 方言 |
|---|---|
| 15 | `{"max_tokens": maxOutputTokens}` |
| 1 | `{'max_tokens': maxOutputTokens}`（单引号写法，**同一语义的第二种写法**） |
| 1 | `{'max_completion_tokens': maxOutputTokens}` |
| 1 | `{'max_output_tokens': maxOutputTokens}` |

**`maxOutputTokens.max` 共 13 种取值：** `1024, 4096, 16384, 32000, 32768, 64000, 65536, 98304, 128000, 131072, 262144, 384000, 500000`。

**`contextWindow` 共 16 种取值：** `8192, 16384, 32768, 65536, 131072, 200000, 202752, 204800, 256000, 262144, 400000, 500000, 1000000, 1024000, 1048576, 1050000`。
（覆写分布：`modelRules` 81 次、`providerSiteRules` 26 次、其余层 0 次。）

---

## 6. ★ 上下文窗口与能力位「在哪定义、在哪生效」（**v1 缺失章节**）

### 6.1 定义位置（三层，逐层收窄）

| 层 | 位置 | 作用 |
|---|---|---|
| **Schema 定义** | `packages/shared/src/model-config.ts:71` `contextWindow: z.number().int().positive()` | 类型 + 正数约束 |
| **类定义 / overlay** | `packages/provider/src/config/model-config.ts:179`（字段）、`:209`（overlay 调用） | 参与字段级合并 |
| **内置数据** | `config/provider/zcode-builtin.json`：`modelRules` 81 处 + `providerSiteRules` 26 处 | 真实取值 |
| **兜底默认** | `apps/zcode-cli/packages/core/src/compact/policy.ts:6` `DEFAULT_COMPACT_CONTEXT_WINDOW = 200_000` | 配置缺失时的运行时兜底 |

**【代码】** `model-config.ts:203-226` 确认 contextWindow 是**标量 overlay**（不是子树）：
```ts
overlay(next: ModelPropertiesConfig): ModelPropertiesConfig {
  return new ModelPropertiesConfig({
    requiresMfjsToolSchema: this.overlayValue(this.requiresMfjsToolSchema, next.requiresMfjsToolSchema),
    contextWindow: this.overlayValue(this.contextWindow, next.contextWindow),   // ★ 标量三态
    inputFormat: this.overlayConfig(this.inputFormat, next.inputFormat),        // ★ 子树递归
    ...
```

**所以：contextWindow 是「按模型声明 + 按站点覆写」的静态声明值，没有 provider 级覆写层。**【代码】`modelApiRules` 里 contextWindow 覆写次数 = 0；`templateModelRules` / `builtinProviderModelRules` 也是 0（实测）。**站点（baseUrl）是唯一能覆写 contextWindow 的第二层。**

### 6.2 消费路径 1：**auto-compact 阈值分母**（真的参与上下文裁剪）

**【代码】** `apps/zcode-cli/packages/core/src/runtime/methods/compact.ts:193-200`：
```ts
const config: AutoCompactPolicyConfig = {
  contextWindow: context.model.properties.contextWindow,   // ★ 来自已求值的 ModelConfig
  ...this.config.compact,
  maxOutputTokens: resolveNormalRequestMaxOutputTokens({
    modelMaxOutputTokens: context.model.optionSpecs.maxOutputTokens.max,
  }),
  modelContextBudgetStrategy: this.config.modelContextBudgetStrategy,
};
```
**【代码】** `apps/zcode-cli/packages/core/src/compact/policy.ts:67-88`：
```ts
export function getEffectiveContextWindowSize(config: AutoCompactPolicyConfig = {}): number {
  const contextWindow = positiveInt(config.contextWindow) ?? DEFAULT_COMPACT_CONTEXT_WINDOW;
  // provider 的 context window 是 input + output 共享窗口；自动压缩只能让出输入侧，
  // 因此阈值分母必须先扣掉当前模型允许的 output token，而不是继续吃完整 contextWindow。
  const reserve = Math.min(getAutoCompactOutputReserveTokens(config), contextWindow);
  return Math.max(0, contextWindow - reserve);
}
export function getAutoCompactOutputReserveTokens(config): number {
  const maxOutputTokens = positiveInt(config.maxOutputTokens);
  return Math.min(maxOutputTokens ?? DEFAULT_AUTOCOMPACT_OUTPUT_RESERVE_TOKENS, PREFLIGHT_AUTOCOMPACT_OUTPUT_RESERVE_TOKENS /* = 21_000 */);
}
export function getAutoCompactThreshold(config): number {
  const effectiveContextWindow = getEffectiveContextWindowSize(config);
  const buffer = positiveInt(config.bufferTokens) ?? AUTOCOMPACT_BUFFER_TOKENS;  // = 13_000
  return Math.max(0, effectiveContextWindow - buffer);
}
```
**【代码】** `compact/policy.ts:90-155` `shouldAutoCompact()`：`tokenCount >= threshold` → `shouldCompact: true, reason: "above_threshold"`。

→ **结论：`contextWindow` 与 `maxOutputTokens.max` 共同决定「什么时候自动压缩上下文」。** 如果站点声明的 contextWindow 偏大（例如 1,000,000 vs 真实 202,752），压缩会被推迟——**【推断】** 这是把「厂商声明值」直接当预算用的已知风险。

**【代码】** `microcompact.ts:40` 同样消费 `context.model.properties.contextWindow`。

### 6.3 消费路径 2：`inputFormat` → **多模态请求降级**

**【代码】** `apps/zcode-cli/packages/core/src/runtime/helpers/media-capability.ts:29-80` `projectMessagesForInputFormat(messages, inputFormat)`：若 `supportsImage/Video/Pdf` 有 false，则把不支持的媒体块**替换为文本占位**（`unsupportedMediaReplacement`），而不是让请求失败。

**【代码】** `apps/zcode-cli/packages/adapters/src/model/media-transform-policy.ts:10-13` 在适配层做同类投影。

**【代码】** `read-pdf.ts:57-62` 用 `inputFormat.supportsPdf` / `supportsImage` **动态切换工具 schema**（能不能用 ReadPdf 工具）。

### 6.4 消费路径 3：能力位 → **请求前硬校验（抛错）**

**【代码】** `apps/zcode-cli/packages/adapters/src/model/model.ts:155-185`：
```ts
function validateRequestProperties(properties: ModelProperties, request: ModelRequest): void {
  if (request.tools && request.tools.length > 0 && !properties.supportsToolCall)
    throw invalidRequest("Model does not support tool calls");
  if (request.responseJsonSchema && !properties.supportsJsonSchemaOutput)
    throw invalidRequest("Model does not support structured output");
  for (const message of request.messages) {
    ...
    if (block.type === "image" && !properties.inputFormat.supportsImage)
      throw invalidRequest("Model does not support image input");
    if (block.type === "file" && mediaType === "application/pdf" && !properties.inputFormat.supportsPdf)
      throw invalidRequest("Model does not support PDF input");
    if (block.type === "file" && mediaType.startsWith("video/") && !properties.inputFormat.supportsVideo)
      throw invalidRequest("Model does not support video input");
  }
}
```
**【代码】** 调用点 `model.ts:81-93` `prepareRequest()` —— 在 executor 之前，**每次 generate/stream 都跑**。

**【代码】** `runner-options.ts:69-70` 把 `requiresMfjsToolSchema` / `supportsNativeWebSearch` 传给 `toAiSdkTools`；`tool-transform.ts:100` / `:260` 据此**增删工具定义**。

**【代码】** `model-execution.ts:302-315`：`supportsJsonSchemaOutput` 被冻结进 AI SDK factory 的 `supportsStructuredOutputs`，注释明确「使用 binding 冻结的模型事实，不按供应商或实时 Registry 另查一套能力」。

### 6.5 消费路径 4：**档位校验（用户可选值必须命中 `values`）**

**【代码】** `packages/provider/src/registry.ts:128-159`：
```ts
export function validateModelSelectionOptions(model, selection): ModelSelectionValidation {
  const reasoningLevel = selection.options?.reasoningLevel;
  const reasoningSpec = model.config.optionSpecs.reasoningLevel;
  if (reasoningLevel === undefined)
    return { ok: false, code: "reasoning-level-missing", ... };
  if (!reasoningSpec.values.includes(reasoningLevel))
    return { ok: false, code: "reasoning-level-not-supported", ..., supportedLevels: [...reasoningSpec.values] };
  return { ok: true };
}
```
**【代码】** `packages/provider/src/effective-model-selection.ts:50-61`：若校验失败且错误码是 `reasoning-level-not-supported`，会尝试 `resolveLegacyReasoningLevel` 把历史档位名（`off`/`nothink`）映射回当前值域；成功则用映射后的选择。

**【代码】** `apps/zcode-cli/packages/adapters/src/model/model.ts:106-130` `validateOptions()` 做**第二次**校验（运行时兜底），超范围抛 `invalidRequest("maxOutputTokens is outside the model option range")`。

→ **同一份「可选档位」事实被校验三次**：UI 选择时（registry）、有效选择解析时（effective-model-selection）、执行前（model.ts）。**【推断】** 这是「纵深防御」，但也意味着新增档位语义要改多处。

### 6.6 消费路径 5：UI / telemetry 展示

**【代码】** `apps/zcode-cli/packages/bootstrap/src/app/provider-registry-selection.ts:184-203`：
```ts
function toModelOption(provider, model): ZCodeModelOption {
  const properties = model.config.properties;
  const optionSpecs = model.config.optionSpecs;
  const reasoning = optionSpecs.reasoningLevel;
  return {
    ref: { providerId: provider.providerId, modelId: model.modelId },
    contextWindow: properties.contextWindow,
    maxOutputTokens: optionSpecs.maxOutputTokens.max,
    reasoning: {
      levels: reasoning.values.map((level) => ({ value: level, label: level })),
      defaultLevel: reasoning.values.at(-1),        // ★ 末项 = 默认档
    },
    properties: { inputFormat: properties.inputFormat, outputFormat: properties.outputFormat },
  };
}
```
**【代码】** `contextWindow` 还进入 session usage 展示链路：`session-mapper.ts:717-774`（contextUsage 分母）、`product-projection.ts:644-693`。

---

## 7. 其余参数的处理路径（**「直通透传轨」的证据**）

### 7.1 采样参数：**完全不做方言归一化**

**【代码】** `apps/zcode-cli/packages/contracts/src/model/index.ts:625-634`：
```ts
export interface ModelRequestSettings {
  temperature?: number;
  maxOutputTokens?: number;
  topP?: number;
  topK?: number;
  presencePenalty?: number;
  frequencyPenalty?: number;
  stopSequences?: string[];
  seed?: number;
}
```
**【代码】** `apps/zcode-cli/packages/adapters/src/model/runner-options.ts:73-79`（generate）与 `:134-140`（stream）：
```ts
temperature: input.request.temperature,
topP: input.request.topP,
topK: input.request.topK,
presencePenalty: input.request.presencePenalty,
frequencyPenalty: input.request.frequencyPenalty,
stopSequences: input.request.stopSequences,
seed: input.request.seed,
```
→ **逐字段原样塞进 AI SDK options，没有任何重命名/映射/条件逻辑。** 这两个对象字面量里也没有任何按 `providerKind` 分支的方言处理（对比同一函数内 `:191-207` 的 `withNativeGenerateOutputFormat` 确实按 `providerKind === "anthropic"` 做了结构化输出分支——说明**该分支就分支，该透传就透传**）。

**【推断】** 这是有意的：AI SDK 自己负责把它翻译成各 provider 的字段名；ZCode 不重复一层。**对我们的意义：`apply_model_params`（`ir.py:58-70`）与 ZCode 的这条轨完全同级——不是差距。**

**注意一处例外**：`maxOutputTokens` 同时存在于 `ModelRequestSettings`（直通轨，`:626`）与 `optionSpecs.maxOutputTokens`（DSL 轨）。**【代码】** 从 `runner.ts:195` `maxOutputTokens: request.options.maxOutputTokens` 看，走的是 `ModelOptions`（DSL 轨）；`ModelRequestSettings.maxOutputTokens` 是 AI SDK 层的另一个入口。**【未验证】** 二者在什么情况下分别生效，我没有追到 AI SDK 内部。

### 7.2 工具调用：能力位门控 + schema 变形（不是方言归一化）

- `supportsToolCall` 为 false 且有 tools → 抛错（`model.ts:156-158`）。
- `requiresMfjsToolSchema` → 工具 schema 变形（`tool-transform.ts:100`）。
- `supportsNativeWebSearch` → 决定是否暴露原生 web search 工具（`tool-transform.ts:260`）。

### 7.3 多模态：能力位 → 降级投影

见 §6.3。**不是「把图片转成厂商 A 的格式」，而是「该厂商不支持就把图片换成文本占位」**。

### 7.4 结构化输出

`supportsJsonSchemaOutput` 三处消费：请求前抛错（`model.ts:159-161`）、AI SDK factory 的 `supportsStructuredOutputs`（`model-execution.ts:313`）、anthropic 的 `structuredOutputMode: "outputFormat"`（`runner-options.ts:200-206`）。

### 7.5 小结：三条轨的边界

| 轨 | 覆盖 | 机制 | 是否归一化方言 |
|---|---|---|---|
| **DSL 轨** | `reasoningLevel`, `maxOutputTokens` | 受限 CEL map + merge patch + 路径冲突守卫 | ✅ 完全 |
| **能力位轨** | contextWindow + 12 个 boolean | zod schema + 多层 overlay + 消费点校验/降级 | ✅ 声明式（按站点/协议） |
| **直通轨** | temperature / topP / topK / 惩罚项 / stop / seed | 逐字段透传给 AI SDK | ❌ 不归一化 |
| **（第 4 轨）** | 历史档位别名 | `legacy-reasoning-level.ts` 把 `off`/`nothink` 映射回当前 `values` | ✅ 单向兼容 |

---

## 8. 求值能力边界（**独立复核 v1 的「只有一个标量输入」**）

**复核结论：v1 的说法成立**（证据见 §2.3 的三处硬编码）。但要补三点 v1 没说清的：

### 8.1 DSL 的「变量少」由「值域可配置」补偿

变量只有 2 个，但：
- `reasoningLevel.values` 有 **17 种非空值域**（+ 1 种空值域 = "不支持"）→ 「能选什么」是配置驱动的
- `reasoningLevel.map` 有 **21 种非 null 写法**（其中 **20 种是真实表达式**，另 1 种是 `{}` 空 patch）→ 「选了之后变成什么」是配置驱动的
- map 可写**任意嵌套 JSON 路径**（`output_config.effort`、`reasoning.effort`、`thinking.type` …）

→ **DSL 的表达力瓶颈不在变量数，而在「值域必须是非空去重字符串数组」这一条**（`shared/src/model-config.ts:26-32`）。**【推断】** 这意味着无法表达「档位 A 比档位 B 强但不可比」这类偏序，只能靠数组顺序。

### 8.2 历史档位别名机制（**第 4 轨**）

**【代码】** `packages/provider-node/src/legacy-reasoning-level-renames.ts:1-103`：一份 25 条的一次性改名清单，把历史档位名 `off` / `nothink` 关联到具体模型正则。例如：
```ts
{ modelMatch: ".*glm-5(?:\.[\-:/\[].*)?",     oldLevel: "off" },
{ modelMatch: ".*GLM-5\.2(?:[.\-:/\[].*)?",   oldLevel: "nothink" },
{ modelMatch: ".*deepseek-v4-pro(?:[.\-:/\[].*)?", oldLevel: "off" },
```

**【代码】** `packages/provider-node/src/legacy-reasoning-level.ts:13-72`：只在「历史 selection 用了 `off`/`nothink`」且「个人配置未覆盖该模型的 reasoningLevel」时，**临时构造一份把 `disabled` 改名为 `oldLevel` 的规则副本**，用同一套 `resolve()` 求值，若命中则把旧档位翻译为 `disabled`。
```ts
const oldLevel = selection.options?.reasoningLevel;
if (oldLevel !== "off" && oldLevel !== "nothink") return undefined;
...
return values?.includes(oldLevel) ? "disabled" : undefined;
```
**【代码】** `legacy-reasoning-level.ts:37-38` 的关键约束注释：「必须是已裁决的原始无站点/无 API 限制规则；新增同名站点规则不能误继承旧别名」——**别名映射只在 `type === "model"` 层做**。

**【推断】** 这是一个很值得学的模式：**「档位改名」不是数据迁移，而是在求值层做一次投影**。我们网关若未来改档位名（如把 `effort` 的 `none` 改名），可以借鉴这个「不改库、加一层投影」的做法。

### 8.3 明确不能做的事

| 不能做 | 证据 |
|---|---|
| 读 `modelId` / `provider` / `apiType` / 请求体 | `parser.ts:167-170` 未知标识符抛错 |
| 成员访问 `obj.field` | `parser.ts:65-67` |
| 函数调用 `f(x)` | `parser.ts:68-70`、`:159-161` |
| 返回非对象 | `compiler.ts:80-88` |
| 对字符串做比较以外的事（无 `.includes()` / 无正则） | `tokenizer.ts:20` 无正则字面量；`evaluator.ts` 无字符串方法 |
| 新增第 3 个变量（不改源码） | `types.ts:9` 编译期联合类型 |

**可用能力**：字面量、数组、对象、`+ - * / %`、`! < <= > >= == !=`、`&& ||`、三元 `?:`、括号、JSON 相等（`evaluator.ts:180-199` 深比较）。**够用**——20 种真实表达式全部只用到了这些。

---

## 9. 用户可编辑面（`manual-model-config.ts`）

**【代码】** `packages/provider/src/config/manual-model-config.ts:5-27`：
```ts
const complete = completeModelConfigDataSchema.shape;
// 手动模式只冻结产品明确开放的叶子；新增系统字段默认不属于个人手动配置。
export const manualModelConfigSchema = completeModelConfigDataSchema
  .pick({ enabled: true })
  .extend({
    enabled: modelConfigDataSchema.shape.enabled,
    properties: complete.properties
      .pick({
        contextWindow: true,
        supportsJsonSchemaOutput: true,
        supportsNativeWebSearch: true,
        supportsMidConversationSystem: true,
      })
      .extend({
        inputFormat: complete.properties.shape.inputFormat.pick({
          supportsImage: true,
          supportsVideo: true,
          supportsPdf: true,
        }),
      }),
    optionSpecs: complete.optionSpecs.pick({ reasoningLevel: true }).extend({
      maxOutputTokens: complete.optionSpecs.shape.maxOutputTokens.pick({ max: true }),
    }),
  });
```

**用户可改的叶子（白名单，共 9 个）：**

| 叶子 | 可改 | 不可改（系统保留） |
|---|---|---|
| `enabled` | ✅ | — |
| `properties.contextWindow` | ✅ | — |
| `properties.supportsJsonSchemaOutput` | ✅ | — |
| `properties.supportsNativeWebSearch` | ✅ | — |
| `properties.supportsMidConversationSystem` | ✅ | — |
| `properties.inputFormat.supportsImage` | ✅ | `supportsText`、`supportsAudio` |
| `properties.inputFormat.supportsVideo` | ✅ | — |
| `properties.inputFormat.supportsPdf` | ✅ | — |
| `optionSpecs.reasoningLevel`（整个 spec：values + map） | ✅ | — |
| `optionSpecs.maxOutputTokens.max` | ✅ | `optionSpecs.maxOutputTokens.map`（**系统保留**） |
| — | ❌ | `requiresMfjsToolSchema`、`outputFormat`、`supportsToolCall` |

**三条关键规则：**

1. **白名单制**：`pick` 显式列举，注释明确「新增系统字段默认不属于个人手动配置」——**默认关闭，避免新字段自动变成用户可改面**。
2. **`map` 对用户开放（reasoningLevel），`maxOutputTokens.map` 不开放**：用户能改「有哪些档位」，但改不了「档位怎么翻译成厂商字段」。**【推断】** 这是安全边界：`map` 能写任意 JSON 路径，开放给用户等于让用户改请求体结构。
3. **手动规则会清空累积结果里的手动叶子**（`model-config.ts:396-398`）：
```ts
result = (rule.type === "manual-provider-model"
    ? ModelConfig.fromData(clearManualModelConfig(result.toJSON()))
    : result).overlay(rule.config);
```
**【代码】** `manual-model-config.ts:37-41`：
```ts
/** 保留独立 enabled 和系统叶子；恢复智能配置及规则合成都使用同一字段归属。 */
export function clearManualModelConfig(input) {
  return modelConfigDataSchema.parse(
    omitSchemaFields(manualModelConfigSchema.omit({ enabled: true }), input));
}
```
→ **手动配置是「替换」而非「叠加」**：一旦用户对手动叶子做了配置，系统内置的同名叶子（如 contextWindow）会被**先清掉**再应用用户值。但 `enabled` 与系统叶子（如 `supportsToolCall`）**保留**。

**【代码】** 校验约束 `rule-data-schema.ts:70-84`：同一 Provider/Model **不能同时存在智能规则与手动规则**。

---

## 10. 端到端链路（带 file:line）

```
[1] 用户选模型
    ModelSelection { providerId, modelId, options?: { reasoningLevel } }
    └ shared/src/model-selection.ts:4-15

[2] 有效选择解析（含账号归属 + 历史档位别名恢复）
    resolveEffectiveModelSelection()
    └ provider/src/effective-model-selection.ts:17-77
        ├ :44-48   provider/model 存在性检查
        ├ :50-61   档位校验失败 → resolveLegacyReasoningLevel 兜底
        └ registry.ts:128-159  validateModelSelectionOptions（值域校验）

[3] 配置装载（一次性，启动时 + 热更新）
    zcode-builtin.json
    └ provider/src/config/schema.ts:78-107  parseZCodeBuiltinModelConfigRules
        （数组顺序 = 优先级：model → model-api → provider-site → template-model → provider-model）
    └ provider-node/src/zcode-builtin-release.ts:54
    └ provider-node/src/endpoint-scoped-zcode-builtin-source.ts:28-133（endpoint 隔离缓存）

[4] Provider 求值
    ProviderConfigResolver.resolve()
    └ provider/src/resolver.ts:182-344
        ├ :192-197  template.overlay(concrete)   ← Provider 级
        ├ :208      effectiveBuiltinProviders.overlay(templatePersonalProviders)
        ├ :209-212  ModelConfigRules.composeEffective(builtin, personal)
        └ :256-292  逐模型 resolve（传 providerId/templateId/modelId/apiType/baseUrl）

[5] Model 级规则求值（★ 核心）
    ModelConfigRules.resolve({providerId, templateId, modelId, apiType, baseUrl})
    └ provider/src/config/model-config.ts:387-423
        逐条 overlay：overlayValue（标量）/ overlayConfig（子树）
        └ config-overlay.ts:26-37

[6] 产出冻结的 ModelConfig（含 contextWindow / 8 能力位 / 2 个 optionSpec）

[7] 创建可执行 Model
    runner.createModel()
    └ adapters/src/model/runner.ts:138-145
        └ model-execution.ts:176-194  bindModel({ optionSpecs })  → compileModelOptionMaps
            └ model-option-map/src/option-maps.ts:20-34（编译一次，缓存）

[8] 每次请求：绑定 option values
    runner.ts:223-257 resolveForRequest({ options: {maxOutputTokens, reasoningLevel} })
    └ model-execution.ts:225-253 resolveSnapshot(...) → createFactory(...)
        └ model-execution.ts:266-279  optionFetch = createModelOptionMapFetch({maps, values})

[9] 请求前能力校验
    model.ts:81-93 prepareRequest()
    ├ :82  validateRequestProperties（tools/jsonSchema/image/pdf/video 硬门控）
    └ :90  validateOptions（reasoningLevel ∈ values；maxOutputTokens ≤ max）

[10] AI SDK 序列化请求体
     runner-options.ts:58-99（采样参数直通；messages/tools 经 transform）

[11] ★ 出站 fetch 拦截：DSL 注入
     model-option-map-fetch.ts:19-30
     ├ :20  readRequestBody（非文本 body → fail-closed 抛错）
     ├ :22  parseJsonObject
     ├ :23  maps.apply(body, values)
     │       └ option-maps.ts:24-32
     │           ├ reasoningLevel 未定义 → 抛 ModelOptionMapError（:26-28）
     │           ├ compileModelOptionMap(specs.reasoningLevel.map).evaluate(value)
     │           ├ compileModelOptionMap(specs.maxOutputTokens.map).evaluate(value)
     │           └ merge-patch.ts:13-33 applyOrderedJsonMergePatches（路径冲突 → 抛错）
     └ :27/:29  用 patchedBody 重建请求

[12] 发往厂商
     providerKind 决定 SDK：openai / anthropic / openai-compatible
     └ model-execution.ts:281-317（由 providerConfig.api.type 决定，:363-371）

[13] 响应侧：流事件归一化（思考字段补 reasoning_content）
     core/ir 侧由 core 负责；适配层 media 投影在 transform.ts
```

**关键结论：整个「参数协议差异」的适配集中在 [11] 一个 fetch 拦截器里，配置在 [5] 一个 resolve 循环里。** 两者都不碰 SDK、不碰业务代码。

---

## 11. 对照我们网关的可迁移设计（**已先读我们代码**）

### 11.1 现状对照（先确认我理解对了）

| 维度 | 我们网关 | ZCode | 差距 |
|---|---|---|---|
| 推理参数模型 | `ReasoningSpec{enabled, effort}`（`core/ir.py:17-25`） | `reasoningLevel` 单枚举 + per-rule `values` + `map` | 🔴 **大** |
| 档位值域 | `ReasoningDefault.effort` 是 **opaque 字符串，不做枚举强校验**（`config/schemas.py:101-106`） | 每个「模型×协议×站点」声明 `values`，**三处强校验** | 🔴 **大** |
| 出站方言 | **硬编码单一方言**（商汤口径）：`thinking.type` + `reasoning_effort`（`core/ir.py:94-111`） | 20 种真实表达式，配置驱动 | 🔴 **大** |
| 输出上限方言 | 只有 `max_tokens`（`config/schemas.py:182-188` 校验 `max_tokens`；注入走 `params` 直通） | 4 种方言（`max_tokens`/`max_completion_tokens`/`max_output_tokens`） | 🟡 中 |
| 采样参数 | `apply_model_params`：`if body.get(k) is None: body[k] = v`（`ir.py:58-70`） | `runner-options.ts:73-79` 逐字段透传 | ✅ **同级** |
| 上下文窗口 | **不存在该概念** | 8 能力位 + contextWindow，按站点覆写，驱动 auto-compact | 🔴 **大（完全没有）** |
| 能力位 | 无（只有 `endpoint: chat/images`，`schemas.py:17`） | 13 个能力叶子，按站点覆写，消费于校验/降级/工具 | 🔴 **大（完全没有）** |
| 层级 | `资源级 reasoning 默认` + `模型级 params`（`main.py:66-67, 91, 93`） | 5 层规则 + 个人手动层 | 🟡 中 |
| 注入点 | `_out_body`（`scheduler.py:223-232`），手写、按 endpoint 分支 | fetch 拦截器，一处生效、协议无关 | 🟡 中 |
| 路径冲突 | 无守卫（`apply_model_params` 与 `inject_reasoning_into_body` 可能互相覆盖） | 冲突直接抛错（`merge-patch.ts:22-27`） | 🔴 **真实 bug 风险** |

### 11.2 建议落地（按优先级，每条都给具体落点）

#### P0-1｜推理方言表（替代 `inject_reasoning_into_body` 的硬编码）

**问题**：`inject_reasoning_into_body`（`core/ir.py:94-111`）硬编码了 `thinking` + `reasoning_effort` 两字段，接新厂商（如只认 `reasoning.effort` 的 OpenAI Responses 系、只认 `output_config.effort` 的 Anthropic 新协议）必须改代码。

**落地**：
1. `model_gateway/config/schemas.py` 新增 `ReasoningDialect` 枚举 + 字段映射表：
   ```python
   class ReasoningDialect(BaseModel):
       # 字段路径用点号表达嵌套：'thinking.type' / 'reasoning.effort' / 'output_config.effort'
       enabled_path: str | None = None      # 写 bool 的路径，如 'thinking.type'（值由 on/off 决定）
       enabled_on: str = "enabled"
       enabled_off: str = "disabled"
       effort_path: str | None = None       # 写 effort 字符串的路径
       effort_map: dict[str, str] = {}      # 档位名 → 厂商词（如 {'max': 'high'}）
       disable_effort_value: str | None = "none"   # 关闭时是否补 effort（现有配对归一化）
   ```
2. `Resource` 增加 `reasoning_dialect: str = ""`（引用预设方言 id），或直接在 `Resource` 内联。
3. `core/ir.py` 新增 `inject_reasoning_by_dialect(body, spec, dialect)`，把 `ir.py:94-111` 的硬编码改成按 dialect 写路径。**保留现有函数作为 `sensenova` 预设方言的默认实现**，避免回归。
4. 落点：`core/ir.py` 新增函数；`core/scheduler.py:231` 改成传 dialect；`config/schemas.py` 加 schema。

**收益**：接新厂商只改 YAML；商汤 400（「only be disabled when reasoning effort is none」）的配对约束变成 dialect 的一个字段，而不是代码里的特例。

#### P0-2｜参数写入冲突守卫（修现有隐患）

**问题**：`apply_model_params`（`ir.py:58-70`）先跑，`inject_reasoning_into_body`（`ir.py:94-111`）后跑，后者**无条件** `body["reasoning_effort"] = spec.effort`（`ir.py:111`）→ 若用户在 `params` 里配了 `reasoning_effort`，会被静默覆盖。

**落地**：新增 `model_gateway/core/param_patch.py`：
```python
@dataclass(frozen=True)
class NamedPatch:
    source: str            # 'model_params' | 'reasoning' | 'dialect'
    patch: dict            # 该来源要写的字段集合

def apply_ordered_patches(body: dict, patches: list[NamedPatch]) -> dict:
    owned: dict[str, str] = {}      # 顶层键 → 来源
    for p in patches:
        for k in p.patch:
            if k in owned:
                raise GatewayError(f"参数写入冲突：键 '{k}' 同时被 {owned[k]} 与 {p.source} 写入")
            owned[k] = p.source
        body.update(p.patch)
    return body
```
**注意**：ZCode 的守卫是**路径级**（`merge-patch.ts:51-57` 连前缀关系都算冲突）。我们目前只需顶层键级就够（我们的写入都是顶层键），但**如果 P1 引入嵌套路径（如 `thinking.type`），必须升级为路径级**。**【推断】** 这是 P1 的前置条件。

**落点**：`core/ir.py` 或新文件；`core/scheduler.py:229-231` 改为先收集两个 patch 再统一 apply。

#### P1-1｜上下文窗口与能力位（**全新，v1 完全没提**）

**问题**：我们网关完全没有 contextWindow 概念，也没有任何能力位。用户的真实痛点是「上下文大小怎么定义也不一样」——**我们现在对此毫无表达**。

**落地**（分两步，避免一次做太大）：

**第一步（最小可用）**：`config/schemas.py` 的 `SystemModel` 增加：
```python
class ModelCapabilities(BaseModel):
    context_window: int | None = Field(default=None, ge=1)
    supports_image: bool | None = None
    supports_pdf: bool | None = None
    supports_video: bool | None = None
    supports_tool_call: bool | None = None
    supports_json_schema: bool | None = None
```
并在 `SystemModel` 加 `capabilities: ModelCapabilities | None = None`。

**第二步（关键：按资源覆写）**：`ModelResource` 增加同名 `capabilities` 字段（因为**能力位差异的载体是「资源」，不是「模型」**——同一个系统模型挂在商汤/字节/阿里三个资源上，能力可能不同）。

**求值语义（照搬 ZCode 的字段级 overlay）**：`resolve_capabilities(model.capabilities, resource.capabilities)` → 资源级非 None 覆盖模型级。

**消费点（照搬 ZCode 的用法，只做最必要的两个）**：
- **contextWindow**：暴露到 `/v1/models` 响应与统计事件；`scheduler.py` 里若请求体 `messages` 估算 token 超窗口，记 WARN（**先不做自动压缩**，我们没有 compact 机制）。
- **能力位**：出站前校验——若请求含 `image_url` 且 `supports_image is False` → 返回 400 而不是把错误透传给厂商。**这直接解决「同一模型在不同资源上能力不同」导致的随机 400。**

**落点**：`config/schemas.py`（schema）、`core/resources.py`（`ResourceState` 增加 `capabilities` 快照字段，`rebuild()` 时填充）、`core/scheduler.py`（`_out_body` 之后加一个 `_validate_capabilities`）。

#### P1-2｜档位值域校验

**问题**：`ReasoningDefault.effort` 是 opaque 字符串（`schemas.py:101-106`），用户配错只会「厂商 400」，没有本地校验。

**落地**：`ModelResource.reasoning` 增加 `allowed_efforts: list[str] | None`；`scheduler.py` 在 `merge_reasoning` 之后校验 `merged.effort in allowed_efforts`，否则记 WARN 并按 `default_effort` 回退（或直接 400）。**【推断】** 若做了 P0-1 的 dialect（含 `effort_map`），这一步可以合并进去：`effort_map` 的键集就是值域。

#### P1-3｜档位改名投影（可选，借鉴 §8.2）

若我们未来把 `effort` 的 `none` 改名或引入 `off`/`disabled` 同义词，**不要做数据迁移**，而是在 `merge_reasoning` 之前加一层 `normalize_legacy_effort(request_spec)`，用一张 `{旧名: 新名}` 表投影。落点：`core/ir.py`。

#### P2｜不做的事（明确排除）

| ZCode 的做法 | 我们不做的理由 |
|---|---|
| 完整受限 CEL DSL | 语法（三元/对象字面量/字符串比较）我们可以用 Python dict 直接表达，不需要表达式引擎。**我们需要的是「方言表」，不是「表达式语言」。** |
| JSON Merge Patch 的 `null = 删除` | 我们 `apply_model_params` 的语义（`body.get(k) is None` 才注入）已经够用；引入 `null=删除` 反而会与「显式 null = 不注入」的现有语义冲突。**但如果做 P1-2 的嵌套路径，需要重新考虑。** |
| 远程下发 + endpoint 隔离缓存 | 我们的配置是本地 YAML（铁律 1：密钥仅存本地），引入远程同步会破坏这个前提。 |
| 5 层规则 | 我们 2 层（模型级 + 资源级）已经覆盖「同模型不同资源」这个核心场景。**层数不是目标。** |

### 11.3 迁移优先级汇总

| 优先级 | 事项 | 落点文件 | 改动量 | 风险 |
|---|---|---|---|---|
| **P0** | 推理方言表 | `core/ir.py`、`config/schemas.py`、`core/scheduler.py:231` | 中 | 需回归全部已支持厂商（现有 E2E 可覆盖） |
| **P0** | 参数写入冲突守卫 | `core/param_patch.py`（新）、`core/scheduler.py:229-231` | 低 | 低（纯新增） |
| **P1** | contextWindow + 能力位 | `config/schemas.py`、`core/resources.py`、`core/scheduler.py` | 中 | 低（新增字段默认 None，不影响现有行为） |
| **P1** | 档位值域校验 | 合并进 P0 方言表 | 低 | 低 |
| **P2** | 档位改名投影 | `core/ir.py` | 低 | 低（按需） |

---

## 12. 风险与成本

### 12.1 许可证：**Apache-2.0（不是 MIT）**

**【代码】** `LICENSE:2`：
```
                                 Apache License
                           Version 2.0, January 2004
```
**【代码】** `package.json:5`：`"license": "Apache-2.0",`

**【代码】** 全仓 `grep -rn "MIT License" --include="LICENSE*"` 只命中一处：`apps/zcode-cli/packages/superpowers-plugin/LICENSE:1`（第三方插件，与主项目无关）。

→ **结论：ZCode 主项目是 Apache-2.0。** Apache-2.0 允许商用、允许修改、允许闭源分发，但要求：保留版权与许可声明、标注修改、附带 NOTICE 文件（`NOTICE.md` 存在，含大量安全边界说明）。**【推断】** 若我们只借鉴「机制设计」而不复制代码，许可证风险极低；若直接移植 `model-option-map` 的 TS 代码，需附带 Apache-2.0 声明。

### 12.2 测试覆盖：**几乎没有**

**【代码】** 全仓 `*.test.ts` 共 **4 个文件**：
```
packages/ui/test/nonCliAcpRetirement.test.ts
packages/services/test/importedClaudeRecovery.test.ts
packages/services/test/nonCliAcpRetirement.test.ts
packages/services/test/providerConfigMigration.test.ts
```
- `packages/model-option-map/` **无测试目录**（`find` 结果只有 `src/` + `dist/` + `package.json` + `tsconfig.json`）。
- `packages/provider/` **无测试目录**。
- `packages/provider-node/` **无测试目录**。
- **grep `RestrictedCel|compileModelOptionMap` 在测试文件中零命中。**

→ **结论：这条归一化链路（DSL + 多层规则 + merge patch）在我们能看到的开源部分里没有单元测试。** 这既是风险（我们无法用它的测试当行为规格），也是机会（我们落地方案可以自己写测试，不受它的测试结构约束）。

**【推断】** 缺失测试的可能原因：核心行为规格在内部测试集或 CI 私有部分；或者规则库的行为靠「配置数据本身 + 线上回归」保障。**我们迁移时不能假设它的边界行为已经被验证过——20 种真实表达式里每种的正确性，只能靠我们自己接厂商实测。**

### 12.3 边界语义风险（迁移时要注意的坑）

| # | 风险 | 证据 | 影响 |
|---|---|---|---|
| R1 | **`reasoningLevel` 未定义时直接抛错** | `option-maps.ts:26-28` `if (values.reasoningLevel === undefined) throw` | 若我们的调用点可能传 None，必须先在调用侧补齐默认档 |
| R2 | **档位默认 = `values` 末项（最高档）** | `provider-registry-selection.ts:196` `values.at(-1)` | 与我们「不注入走厂商默认」的哲学相反。**我们不应照搬这条。** |
| R3 | **规则层静默覆盖、option-map 层抛错** | `model-config.ts:420` vs `merge-patch.ts:24` | 两层策略不一致；我们若做统一 guard，要明确选哪种 |
| R4 | **`matchesRule` 用正则全匹配 + 用户可控 pattern** | `model-config.ts:544-546`、`rule-data-schema.ts:14-24`（`patternSchema` 用 `new RegExp` 校验合法性） | 存在 ReDoS 面。**【未验证】** 未发现对正则复杂度的额外限制 |
| R5 | **modelMatch 忽略大小写，apiType/baseUrl 区分大小写** | `model-config.ts:408`（`true`）vs `:413`/`:417`（默认 `false`） | 配置作者容易踩坑；我们做规则匹配时要显式定义 |
| R6 | **`readRequestBody` 取不到 body 时静默跳过 patch** | `model-option-map-fetch.ts:44` `return undefined` | fail-closed 不完整；我们若做同类拦截要注意 |
| R7 | **contextWindow 用「厂商声明值」当压缩预算** | `compact/policy.ts:68` | 站点声明偏大（1,000,000）会导致压缩推迟、真超窗 |
| R8 | **`values` 非空约束导致无法表达「无推理档位」** | `shared/src/model-config.ts:30` `.min(1, ...)` | 用 `["enabled"]` + `map: "{}"` 变通（实测 8 次）——语义晦涩 |
| R9 | **无测试** | §12.2 | 行为规格不可信 |

### 12.4 成本估算（我们侧）

| 事项 | 代码量（估） | 说明 |
|---|---|---|
| P0-1 方言表 | ~150 行（schema + 注入函数 + 4~6 个预设方言） | 需回归现有全部厂商 |
| P0-2 冲突守卫 | ~40 行 | 纯新增 |
| P1-1 能力位 | ~120 行（schema + ResourceState 字段 + 校验函数 + /v1/models 暴露） | 不动现有路径 |
| P1-2 值域校验 | ~30 行（合并进 P0-1） | — |
| 测试 | ~200 行 | 建议先补 P0-2 与 P0-1 的单测 |

**【推断】** 总计约 500 行代码 + 测试，属于「一次迭代可完成」的量级。

---

## 13. 未验证清单

| # | 未验证项 | 卡在哪 |
|---|---|---|
| U1 | `ModelRequestSettings.maxOutputTokens`（直通轨，`contracts/model/index.ts:625-627`）与 `ModelOptions.maxOutputTokens`（DSL 轨，`model.ts:27`）的**实际优先级** | 需追进 AI SDK 内部；ZCode 侧 `runner.ts:195` 只用了 DSL 轨，直通轨的调用方没找到 |
| U2 | `zcode-builtin.json` 的**远程同步来源**（`zcode-builtin-remote-synchronizer.ts` 未逐行读） | 只读了 `endpoint-scoped-zcode-builtin-source.ts` 的装配逻辑，没读同步协议 |
| U3 | `personalModelConfigRules` 的**个人配置文件格式与写入路径** | 只读了 schema（`rule-data-schema.ts:64-84`）与 `toPersonalJSON`（`model-config.ts:518-524`），没追磁盘 IO |
| U4 | **UI 侧如何渲染 18 种值域（17 非空 + 1 空）**（是否有档位名本地化映射） | `ProviderModelMetadata.tsx` 只扫到 `contextWindow` 相关，没通读档位渲染 |
| U5 | `legacy-reasoning-level.ts` 的**别名清单是否与当前数据完全同步**（25 条 vs 84 条 modelRules） | 未逐条比对；`legacy-reasoning-level.ts:37` 的注释暗示「新增同名站点规则不能误继承旧别名」，说明这是维护负担 |
| U6 | ZCode 是否有**内部测试集**覆盖这条链路 | 仓库内 `*.test.ts` 只有 4 个，无法确认是否有未公开的测试 |
| U7 | `requiresMfjsToolSchema` 的 `mfjs` **具体指什么** | 只看到它影响工具 schema（`tool-transform.ts:100`），没找到定义 |
| U8 | 我们网关 `PARAM_RANGES`（`config/schemas.py:142-147`）与 ZCode 的**取值范围是否冲突** | 我们 `temperature: [0,2]` / `top_p: [0,1]`；ZCode 不做范围校验（直接透传给 SDK）。**【推断】** ZCode 更宽松，我们更严格——这是我们的优势而非差距 |

---

## 14. 证据附录（file:line 清单）

### 14.1 `packages/model-option-map/src/`

| 文件 | 行 | 内容 |
|---|---|---|
| `types.ts` | 8 | `RestrictedCelValue = string \| number` |
| `types.ts` | 9 | `ModelOptionName = "reasoningLevel" \| "maxOutputTokens"` |
| `types.ts` | 11-19 | `RestrictedCelProgram` / `ModelOptionMapProgram` |
| `tokenizer.ts` | 18-20 | 运算符与标点集合 |
| `tokenizer.ts` | 83-124 | 字符串转义 |
| `parser.ts` | 4-44 | 表达式类型联合 |
| `parser.ts` | 65-67 | member access 不支持 |
| `parser.ts` | 68-70 | function call 不支持 |
| `parser.ts` | 158-171 | 标识符解析（只认变量名/true/false/null） |
| `evaluator.ts` | 9-15 | 求值入口（单标量） |
| `evaluator.ts` | 168-178 | ★ 入参断言（string\|number） |
| `evaluator.ts` | 180-199 | JSON 深比较 |
| `compiler.ts` | 13-15 | 三级缓存 |
| `compiler.ts` | 80-88 | ★ 编译期断言返回对象 |
| `merge-patch.ts` | 13-33 | ★ 路径冲突守卫 |
| `merge-patch.ts` | 51-57 | 前缀关系也算冲突 |
| `merge-patch.ts` | 63-78 | merge 语义（null=删除） |
| `option-maps.ts` | 5-8 | `ModelOptionMapSpecs` |
| `option-maps.ts` | 20-34 | `compileModelOptionMaps` |
| `option-maps.ts` | 26-28 | reasoningLevel 未定义抛错 |

### 14.2 `packages/shared/src/`

| 文件 | 行 | 内容 |
|---|---|---|
| `model-config.ts` | 5-19 | ★ 配置加载期编译 map |
| `model-config.ts` | 21-35 | ★ `completeEnumOptionSpecDataSchema`（values 有序/非空/去重） |
| `model-config.ts` | 37-42 | `completeLimitOptionSpecDataSchema` |
| `model-config.ts` | 51-60 | input/output format |
| `model-config.ts` | 68-79 | ★ 8 个能力位（含 contextWindow） |
| `model-config.ts` | 88-100 | optionSpecs |
| `model-selection.ts` | 4-15 | `ModelSelection` schema |
| `model-selection.ts` | 20-29 | `EffectiveModelSelectionResult` |
| `model-provider-types.ts` | 2-14 | 内置 provider id |
| `official-glm-model-id.ts` | 2-33 | 官方 GLM 规范 ID |

### 14.3 `packages/provider/src/`

| 文件 | 行 | 内容 |
|---|---|---|
| `config-overlay.ts` | 1-14 | 校验问题码（含 `invalid-reasoning-mapping`） |
| `config-overlay.ts` | 26-28 | ★ `overlayValue`（undefined=继承） |
| `config-overlay.ts` | 30-37 | ★ `overlayConfig`（null=清空） |
| `config/model-config.ts` | 43-76 | `EnumOptionSpecConfig` |
| `config/model-config.ts` | 80-107 | `LimitOptionSpecConfig` |
| `config/model-config.ts` | 113-149 | `ModelInputFormatConfig` |
| `config/model-config.ts` | 177-244 | ★ `ModelPropertiesConfig`（`:179` contextWindow；`:209` overlay） |
| `config/model-config.ts` | 248-276 | `ModelOptionSpecsConfig` |
| `config/model-config.ts` | 285-335 | `ModelConfig` |
| `config/model-config.ts` | 366-538 | ★ `ModelConfigRules` |
| `config/model-config.ts` | 379-381 | `composeEffective` |
| `config/model-config.ts` | 387-423 | ★★ `resolve()`（优先级来源） |
| `config/model-config.ts` | 396-398 | 手动规则清空手动叶子 |
| `config/model-config.ts` | 544-546 | `matchesRule`（正则全匹配 + ignoreCase） |
| `config/model-config.ts` | 548-559 | baseUrl 规范化 |
| `config/rule-data-schema.ts` | 26-53 | 规则 schema |
| `config/rule-data-schema.ts` | 55-84 | builtin/personal schema |
| `config/rule-data-schema.ts` | 70-84 | 智能/手动互斥校验 |
| `config/manual-model-config.ts` | 5-27 | ★★ 用户可编辑白名单（9 叶） |
| `config/manual-model-config.ts` | 37-41 | `clearManualModelConfig` |
| `config/schema.ts` | 78-107 | ★ 内置规则数组装配顺序 |
| `config/schema-validation.ts` | 5-43 | zod issue → 问题码 |
| `resolver.ts` | 182-344 | ★ `ProviderConfigResolver.resolve` |
| `resolver.ts` | 192-208 | provider overlay 链 |
| `resolver.ts` | 209-212 | `composeEffective` 调用 |
| `resolver.ts` | 256-292 | 逐模型 resolve |
| `registry.ts` | 128-159 | ★★ `validateModelSelectionOptions` |
| `effective-model-selection.ts` | 17-77 | 有效选择解析 |
| `effective-model-selection.ts` | 50-61 | legacy 档位兜底 |
| `config/provider-config.ts` | 173-264 | `ProviderConfig`（含 api.baseUrl） |

### 14.4 `packages/provider-node/src/`

| 文件 | 行 | 内容 |
|---|---|---|
| `legacy-reasoning-level.ts` | 13-72 | ★ 历史档位投影 |
| `legacy-reasoning-level.ts` | 37-38 | 只在 model 层做别名 |
| `legacy-reasoning-level-renames.ts` | 1-103 | 25 条别名清单 |
| `endpoint-scoped-zcode-builtin-source.ts` | 28-133 | endpoint 隔离缓存 |
| `zcode-builtin-release.ts` | 54 | 规则装载入口 |

### 14.5 `apps/zcode-cli/packages/adapters/src/model/`

| 文件 | 行 | 内容 |
|---|---|---|
| `model-option-map-fetch.ts` | 13-31 | ★★ 唯一注入点（fetch 拦截器） |
| `model-option-map-fetch.ts` | 33-45 | fail-closed（不完整） |
| `model-execution.ts` | 176-194 | `bindModel` |
| `model-execution.ts` | 225-253 | `resolveSnapshot` |
| `model-execution.ts` | 255-318 | `createFactory`（`:266-279` optionFetch） |
| `model-execution.ts` | 350-372 | `api.type` → SDK kind |
| `model-execution.ts` | 302-315 | `supportsStructuredOutputs` |
| `runner.ts` | 138-145 | `createModel` + bindModel |
| `runner.ts` | 223-257 | `resolveForRequest` |
| `model.ts` | 36-94 | `ExecutableModel` |
| `model.ts` | 106-130 | ★ `validateOptions` |
| `model.ts` | 155-185 | ★★ `validateRequestProperties` |
| `runner-options.ts` | 73-79 | ★★ 采样参数直通（generate） |
| `runner-options.ts` | 134-140 | ★★ 采样参数直通（stream） |
| `runner-options.ts` | 69-70 | 能力位传给工具变换 |
| `tool-transform.ts` | 100 / 260 | `requiresMfjsToolSchema` / `supportsNativeWebSearch` |
| `media-transform-policy.ts` | 10-13 | 媒体能力投影 |
| `../../contracts/src/model/index.ts` | 625-634 | ★ `ModelRequestSettings` |
| `../../contracts/src/model/model.ts` | 27-39 | `ModelOptions` / `ModelRequest` |

### 14.6 `apps/zcode-cli/packages/core/src/` 与 `bootstrap/`

| 文件 | 行 | 内容 |
|---|---|---|
| `core/src/compact/policy.ts` | 6-14 | 默认常量 |
| `core/src/compact/policy.ts` | 67-88 | ★★ contextWindow → 压缩阈值 |
| `core/src/compact/policy.ts` | 90-155 | `shouldAutoCompact` |
| `core/src/runtime/methods/compact.ts` | 193-214 | ★ contextWindow 注入 policy |
| `core/src/runtime/methods/microcompact.ts` | 40 | 同 |
| `core/src/runtime/methods/model.ts` | 128-139 | contextWindow 日志 |
| `core/src/runtime/helpers/media-capability.ts` | 29-80 | ★ 多模态降级 |
| `core/src/tool/handlers/read-pdf.ts` | 57-62 | 能力位驱动工具 schema |
| `bootstrap/src/app/provider-registry-selection.ts` | 164-182 | 档位解析/强制 |
| `bootstrap/src/app/provider-registry-selection.ts` | 184-203 | ★★ `toModelOption`（暴露给 UI） |

### 14.7 配置数据 `config/provider/zcode-builtin.json`（6212 行，revision 30）

| 行 | 内容 |
|---|---|
| 5 | `providerConfigRules` |
| 6 | `templateRules` 起始 |
| 691 | `providerRules` 起始（8 条） |
| 864 | `modelConfigRules` |
| 865-866 | `modelRules` 起始（84 条） |
| **866-898** | ★★ `modelRules[0]` `.*` 兜底（contextWindow 200000 / values disabled,enabled / map "{}" / max 32000） |
| 977-996 | `modelRules[6]` `.*glm-5\.3(?:-flash)?` |
| 2045-2065 | ★ `modelRules[62]` `.*deepseek-v4-pro`（values 4 档） |
| 2088-2107 | `.*deepseek-v4[.-]1-flash` |
| 2484-2485 | `modelApiRules` 起始（72 条） |
| **2494-2507** | ★★ `modelApiRules[1]` `.*` × anthropic-messages（thinking + output_config） |
| **2508-2521** | ★★ `modelApiRules[2]` `.*` × openai-chat-completions（4 键同写） |
| **2522-2534** | ★★ `modelApiRules[3]` `.*` × openai-responses（reasoning.effort） |
| 2912-2922 | `.*deepseek-v4-pro` × anthropic-messages |
| 2923-2933 | `.*deepseek-v4-pro` × openai-chat-completions |
| 3287 | `providerSiteRules` 起始（52 条） |
| **3375-3400** | ★★ `glm-5.1` × opencode（cw 202752 / values ["enabled"] / map "{}"） |
| **3404-3429** | ★★ `kimi-k3` × opencode（values ["max"] / 放开 image+video） |
| **3520-3548** | ★★ `deepseek-v4-pro` × opencode（values ["high","max"] / cw 1000000 / max 384000） |
| **3861-3887** | ★★ `qwen3.7-max` × opencode × anthropic（cw 1000000 / values 2 档 / max 65536） |
| 3998 起 | `.*(?:glm-\|deepseek-\|kimi-k2\|qwen\|mimo-).*` × openrouter × anthropic |
| **4148-4162** | ★★ `deepseek-v4-pro` × api.deepseek.com × openai-responses |
| **4214-4224** | ★★ `.*deepseek-v4[.-]1-flash` × openrouter（**cw 1048576**） |
| 4225-4236 | 同模型 × openrouter × openai-chat（reasoning.enabled / reasoning.effort） |
| 4273-4282 | `.*qwen3\.7-(?:max\|plus\|flash)` × dashscope（国内） |
| 4283-4292 | 同 × dashscope-intl（国际） |
| 4316-4317 | `templateModelRules` 起始（244 条，仅 enabled） |
| 6026-6027 | `builtinProviderModelRules` 起始（26 条，仅 enabled） |

### 14.8 许可证与测试

| 路径 | 行 | 内容 |
|---|---|---|
| `LICENSE` | 2 | `Apache License` / `Version 2.0` |
| `package.json` | 5 | `"license": "Apache-2.0"` |
| `apps/zcode-cli/packages/superpowers-plugin/LICENSE` | 1 | 唯一一处 `MIT License`（第三方插件） |
| `packages/ui/test/nonCliAcpRetirement.test.ts` | — | 全仓 4 个测试之一 |
| `packages/services/test/providerConfigMigration.test.ts` | — | 全仓 4 个测试之一 |

### 14.9 我们网关（对照用）

| 文件 | 行 | 内容 |
|---|---|---|
| `model_gateway/core/ir.py` | 17-25 | `ReasoningSpec` |
| `model_gateway/core/ir.py` | 28-55 | `merge_reasoning`（三级合并 + 矛盾防护） |
| `model_gateway/core/ir.py` | 58-70 | `apply_model_params`（字段级注入） |
| `model_gateway/core/ir.py` | 73-91 | `lift_reasoning_from_body` |
| `model_gateway/core/ir.py` | 94-111 | ★ `inject_reasoning_into_body`（硬编码单方言；L111 无条件覆盖） |
| `model_gateway/core/scheduler.py` | 214 | 无可用适配器时抛错 |
| `model_gateway/core/scheduler.py` | 223-232 | ★★ `_out_body`（唯一出站注入点） |
| `model_gateway/core/scheduler.py` | 228-229 | 仅 chat 注入 params |
| `model_gateway/core/scheduler.py` | 230-231 | `merge_reasoning` + `inject_reasoning_into_body` |
| `model_gateway/core/resources.py` | 32-64 | `ResourceState` |
| `model_gateway/core/resources.py` | 76-117 | `rebuild`（热重载保状态） |
| `model_gateway/config/schemas.py` | 98-106 | `ReasoningDefault`（effort opaque） |
| `model_gateway/config/schemas.py` | 109-129 | `Resource` |
| `model_gateway/config/schemas.py` | 132-137 | `ModelResource` |
| `model_gateway/config/schemas.py` | 142-147 | `PARAM_RANGES` |
| `model_gateway/config/schemas.py` | 150-191 | `SystemModel` + `params` 校验 |
| `model_gateway/main.py` | 66-67 | `Runtime.resource_reasoning` / `model_params` |
| `model_gateway/main.py` | 91 / 93 | 两表的填充 |
| `model_gateway/api/openai_compat.py` | 122 | `lift_reasoning_from_body` 调用点 |
| `model_gateway/adapters/openai_out.py` | 1-207 | 唯一有实现的出站适配器 |
| `model_gateway/adapters/anthropic_out.py` | 1 | 仅 docstring（P1 未实现） |
| `model_gateway/adapters/gemini_out.py` | 1 | 仅 docstring（P2 未实现） |
| `model_gateway/adapters/base.py` | 1-5 | 仅 docstring（接口未落地） |

---

*文档版本：v2-01 · 完成于 2026-09-24*
