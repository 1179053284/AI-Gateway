# ZCode「模型参数处理机制」深度代码考古报告

> 调研对象：`/Users/w/Desktop/01-关注的开源项目/ZCode/`（只读，未修改任何文件）
> 权威源：`packages/model-option-map/src/*.ts`（8 个文件，共 866 行）+ `packages/provider/src/config/*.ts` + `config/provider/zcode-builtin.json`（6212 行）
> 所有结论均附 `文件路径:行号` 证据。凡未验证处已显式标注。

---

## 0. 结论先行（TL;DR）

1. **它不是一个"模型参数映射框架"，而是一台极窄的、单变量的表达式求值器**：只处理 **2 个**参数（`reasoningLevel` 字符串、`maxOutputTokens` 数字），且**每次求值只允许一个输入变量**（`RestrictedCelValue = string | number`，`types.ts:8`）。厂商差异靠"每个（模型 × API 协议 × 站点）组合各写一条 map 字符串"来穷举，不是靠通用规则推导。
2. **语言是自研的 "Restricted CEL"**——CEL（Common Expression Language）的裁剪子集：有 `?:`、`&&/||`、`==/!=`、`< <= > >=`、`+ - * / %`、`!`、数组/对象字面量，**但明确禁止成员访问（`.`）和函数调用**（`parser.ts:66`、`parser.ts:69`）。
3. **它的核心产物是"JSON 补丁"，不是"参数值"**：表达式求值必须返回一个 JSON object，该 object 被当作 **RFC 7386 JSON Merge Patch** 打到出站 HTTP 请求体上（`merge-patch.ts:63-78`）。这是整个设计最值得学的一点——**统一语义层收敛为「语义档位」，厂商方言在最后一跳（fetch 拦截器）才落地**。
4. **合并有冲突守卫**：多个 option map 若写入重叠 JSON 路径，直接抛错而不是"后者覆盖前者"（`merge-patch.ts:22-27`）。
5. **配置分层是 6 类规则 + 覆盖（overlay）语义**，优先级由数组顺序决定：`model`(正则) → `model-api` → `provider-site` → `template-model` → `provider-model`(精确)（`schema.ts:80-106` + `model-config.ts:390-421`）。
6. **DSL 在 schema 校验期就被编译**（`shared/model-config.ts:5-19`），语法错误 = 配置非法，写不进配置文件。
7. **真实规则库规模**：内置配置共 **119 条 map**，去重后 **21 种不同的 reasoningLevel 映射** + **4 种 maxOutputTokens 映射**；覆盖 3 种 API 协议 × 12 个站点。
8. **它不管的事**：不做参数改名白名单、不做取值域钳制（`max` 只是 advisory，由调用方 `Math.min` 自行钳制，如 `auxiliary-model-options.ts:12`）、不管 tool_call 格式、不管惩罚项、不管缓存参数、不做能力降级协商（只有 `enabled: false` 硬禁用）。

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

| 特性 | 出现次数 |
|---|---|
| `==` | 57 |
| `?:` 三元 | 50 |
| 空对象 `{}` | 8 |
| `\|\|` | 2 |
| `!=` | 1 |
| `&&` | 1 |
| `!` | 1 |
| 数组字面量 `[...]` | **0** |
| 算术 `+ - * / %`、比较 `< > <= >=`、`null` | **0** |

**结论：真实世界只用到了 CEL 的一个非常小的子集——对象字面量 + 三元 + 等值比较。** 数组与算术是完全未被使用的预留能力。这一点对我们是否要引入 DSL 的决策极其关键（见第 11 节）。

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
          message: error instanceof Error ? error.message : "Option map 无法编译",
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

**用户参数的插入点**：用户在 UI 上只能改**档位值**（`reasoningLevel`），**不能改 map**。`manual-model-config.ts:24-26` 明确限定手动配置可编辑的叶子：

```ts
optionSpecs: complete.optionSpecs.pick({ reasoningLevel: true }).extend({
  maxOutputTokens: complete.optionSpecs.shape.maxOutputTokens.pick({ max: true }),
}),
```

> 用户可改：`reasoningLevel`（整个，含 values + map）与 `maxOutputTokens.max`。
> 用户**不可**改：`maxOutputTokens.map`（这个 pick 只取了 `max`）。
> 注释也说明了原则（`manual-model-config.ts:5`）："手动模式只冻结产品明确开放的叶子；新增系统字段默认不属于个人手动配置。"

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

#### 类别 A：**档位→布尔开关**（2 种）

| 次数 | map | 说明 |
|---|---|---|
| 6 | `{"enable_thinking": reasoningLevel == "enabled"}` | Qwen 系（`qwen3.5-plus`、`qwen-plus`、`qwen-flash`、`qwen3-vl-plus` 等） |
| 1 | `{"reasoning": {"enabled": reasoningLevel == "enabled"}}` | OpenRouter 上的 Qwen |

> 语义损失：`low/high/max` 三档被压成一个布尔。这是**能力降级**的一种（下方类别 F 有更完整的讨论）。

#### 类别 B：**档位→厂商枚举（含特殊值翻译）**（6 种）

| 次数 | map | 特殊处理 |
|---|---|---|
| 17 | `{"reasoning_effort": reasoningLevel}` | 纯透传（Kimi K3 / GPT-5.4 / Qwen3.8 / Grok 等，`values=["low","high","max"]`） |
| 9 | `{"reasoning": {"effort": reasoningLevel}}` | 纯透传（OpenAI Responses） |
| 5 | `{"output_config": {"effort": reasoningLevel}}` | 纯透传（Anthropic Messages 上的 Kimi K3 / GPT-5.6） |
| 3 | `{"thinking": {"type": "adaptive"}, "output_config": {"effort": reasoningLevel}}` | Claude 5 / GLM-X-Preview 系，固定 `adaptive` + 透传 effort |
| 3 | `{"reasoning": {"effort": reasoningLevel == "disabled" ? "none" : reasoningLevel}}` | **`disabled` → `"none"`**（DeepSeek 官方 Responses API 的方言） |
| 1 | `{"thinking": {"type": reasoningLevel == "disabled" ? "disabled" : "adaptive"}}` | minimax-m3 @ opencode |

#### 类别 C：**语义档位 → 厂商词表翻译**（`enabled`/`disabled` ↔ 厂商词表）（4 种）

这是**"统一语义档位"最核心的价值体现**：上游只有 `disabled|enabled` 两个档，下游词表千差万别。

| 次数 | map | 翻译规则 |
|---|---|---|
| 27 | `{"thinking": {"type": reasoningLevel == "enabled" ? "enabled" : "disabled"}}` | 二元开关（GLM-5/5.1/4.7 等 27 个模型 @ anthropic-messages） |
| 2 | `{"thinking": {"type": reasoningLevel == "disabled" ? "disabled" : "enabled"}}` | 同上（条件反向写法，语义等价） |
| 1 | `{"thinking": {"type": "adaptive"}, "output_config": {"effort": reasoningLevel}}` | 见类别 B |
| 1 | `{"reasoning": {"effort": reasoningLevel == "disabled" ? "none" : "high"}}` | **`enabled` → `"high"`**（kimi-k2.7-code、qwen3.7/3.6 @ responses） |

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

#### 类别 F：**能力降级 / 硬禁用**（不属于 map，但属于同一规则表）

1. **档位降级**：`values` 从 `["disabled","enabled","low","high","max"]` 收缩到 `["disabled","enabled"]`。典型如 `modelRules` 里 `.*glm-5` 规则（`zcode-builtin.json` 中 `"values": ["disabled","enabled"]`）——**UI 上只给两个档**，用户选不到中间档，map 也不需要处理。
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

#### 类别 G：**站点级覆盖（同一模型，同一协议，不同网关）**

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

### 6.3 未覆盖的维度（重要！）

**内置 119 条 map 中，以下维度完全没有出现：**

| 维度 | 是否覆盖 |
|---|---|
| `temperature` 范围/改名 | ❌ 完全没有 |
| `top_p` / `top_k` | ❌ |
| 惩罚项 `frequency_penalty` / `presence_penalty` / `repetition_penalty` | ❌ |
| 工具调用格式（`tools` / `tool_choice` / 并行调用开关） | ❌ 由 AI SDK 层与 `strict-tool-schema.ts` 等处理，不走 option map |
| 缓存参数（`cache_control` / prompt caching） | ❌ |
| 停止词 `stop` / `stop_sequences` | ❌ |
| 结构化输出开关（`response_format` / `json_schema`） | ❌ 走 `supportsJsonSchemaOutput` 能力位 + SDK 装配（`model-execution.ts:313`） |
| 流式开关 | ❌ |
| 多模态字段形态 | ❌ |
| 参数删除（`null`） | ⚠️ 语言支持，配置零使用 |

> **这直接回答了"ZCode 有没有一套完整的模型参数处理机制"**：**没有**。它有一套**极其完整的「两个参数的厂商方言归一化」机制**，以及一套**通用的「配置分层覆盖」机制**。前者很窄，后者很通用。这两者经常被混为一谈。

---

## 7. 类型体系（`types.ts` + 上下游）

### 7.1 `types.ts` 全部定义（36 行，仅 5 个实体）

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
   │     JsonValue }      │  返回型 │     JsonObject }         │  compiler.ts:16/35
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
   │ NamedJsonMergePatch  │   │ ModelConfigRule (6 变体)      │  model-config.ts:346
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

### 7.3 类型设计上值得注意的点

1. **`RestrictedCelValue = string | number` 是最强的约束表达**：它用类型系统宣告"求值期没有对象、没有布尔、没有数组"。想引入富上下文（如 `ctx.apiType`）必须改这个类型——**改动成本被刻意做得很高**，防止上下文无序膨胀。
2. **`ModelOptionMapProgram` 只收紧了返回类型**（`JsonObject` 而非 `JsonValue`），没有引入新概念。这是"最小扩展"的范例。
3. **`RestrictedCelError` 带 `offset`**：错误信息形如 `member access is not supported at offset 5`（`types.ts:25`），可直接在配置编辑 UI 里定位到第 5 个字符。
4. **`JsonObject` 是 `readonly` + `Object.create(null)`**（`evaluator.ts:26`、`merge-patch.ts:83`）：不可变 + 无原型。

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

```
                       ┌────────────────────────────────────┐
                       │ config/provider/zcode-builtin.json │
                       └────────────────┬───────────────────┘
                                        │ JSON.parse
                                        ▼
        ┌───────────────────────────────────────────────────────────┐
        │ provider-node/src/zcode-builtin-release.ts                │
        │  decodeZCodeBuiltinRelease()                              │
        │   ① releaseSchema.parse(input)  → 校验 schemaVersion/rev  │  :26-34
        │   ② parseZCodeBuiltinProviderConfigRules(...)             │  :38
        │   ③ parseZCodeBuiltinModelConfigRules(...)                │  :54
        │   ④ 拒绝已退役 Provider（builtin:zapi）                    │  :44-47
        └────────────────┬──────────────────────────────────────────┘
                         │
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
        │        effectiveModelRules.resolve({providerId,templateId,│  :257-263
        │          modelId, apiType, baseUrl})                      │  ← model-config.ts:387
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
| **① 反序列化（硬失败）** | `zcode-builtin-release.ts:31` `releaseSchema.parse()`；`schema.ts:79` `builtinModelConfigRulesSchema.parse()` | 整份 Release 的结构 + 每个字段的类型 + **map 能否编译** | **抛异常**（zod `.parse`）。上游 `decodeZCodeBuiltinRelease` 抛错 → Source 回落到兼容候选（注释 `zcode-builtin-release.ts:43-45`："拒绝整份不兼容 Release，让 Source 回落到兼容候选"）。**即：坏配置不会半生效，整份回退。** |
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

**发现的瑕疵**：`config-overlay.ts:1-14` 的错误码联合类型声明了 9 个成员，但 `invalid-reasoning-mapping`（`:8`）与 `invalid-pattern`（`:9`）**在全仓库没有任何生产点**（已 grep 全量 `.ts` 确认）。`invalid-pattern` 的语义被 `rule-data-schema.ts:14-24` 的 `patternSchema.refine(new RegExp(...))` 吸收，但 refine 的默认 message 会被归类为 `invalid-config`。属于历史遗留的未清理枚举。

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
| `schemaVersion` | 硬版本，`z.literal(1)`（`zcode-builtin-release.ts:28`），不匹配直接拒整份 |
| `revision` | 单调递增的配置版本号，进 Registry 的 revision（`zcode-builtin-provider-config-source.ts:213`：`` `zcode-builtin:${release.revision}:${sourceKey}` ``） |
| `templateRules[].templateId` | 模板 ID，被 `providerRules[].templateId` 引用 |
| `providerRules[].providerId` | 厂商 ID；`account:` 前缀 = 账号型（access.type=`zhipu-account`） |
| `config.access.type` | `api-key` / `zhipu-coding-plan-api-key` / `zhipu-account`（`provider-data-schema.ts:37`） |
| `config.api.type` | `anthropic-messages` / `openai-chat-completions` / `openai-responses`（`provider-data-schema.ts:4-8`）★ **这个枚举是 `apiTypeMatch` 的取值域** |
| `config.api.baseUrl` | ★ **这个值是 `baseUrlMatch` 的匹配对象** |
| `config.builtinModelIds` | 该厂商内置的模型 ID 列表（有序） |

### 9.2 片段 1：厂商模板 + 账号型厂商（Z.AI Coding Plan）

`zcode-builtin.json:6-31`（templateRules[0]）：

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

> 字段含义：`group: "zai-family"` 参与 `resolveProviderOrder` 的排序分组（`resolver.ts:360-363`，family 排最前）；`access.type=zhipu-account` 意味着 API Key 由账号服务在请求期注入（`runner.ts:163-189` 的 `requestAuth` 逻辑），配置里**不存 Key**（`rule-data-schema.ts:115-123` 甚至用 `superRefine` 禁止个人层给 `account:` Provider 写 access）。
> 注意 `access` 在完整 schema 里是 discriminated union（`provider-data-schema.ts:70-73`），`zhipu-account` 分支的 `entitled` 字段是**运行时权益**而非静态配置——所以 `builtinProviderConfigRuleSchema` 允许它缺省，由 `resolver.ts:250` 判定 `accessEntitled`。

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
    → decodeZCodeBuiltinRelease()                  zcode-builtin-release.ts:31-58
        ├─ releaseSchema.parse (schemaVersion/revision)     :31
        ├─ parseZCodeBuiltinProviderConfigRules             :38
        └─ parseZCodeBuiltinModelConfigRules                :54
              └─ builtinModelConfigRulesSchema.parse        schema.ts:79
                    └─ optionMapSchema.superRefine
                          └─ compileModelOptionMap()  ★DSL 语法在此一次性验证  shared/model-config.ts:11

【阶段 1】启动期：规则合成 + 完整化
  ProviderConfigResolver.resolve()                   resolver.ts:183
    ├─ ModelConfigRules.composeEffective(builtin, personal)   model-config.ts:379
    ├─ 每个 provider：template.overlay(concrete)              resolver.ts:196
    └─ 每个 (provider, model)：
          effectiveModelRules.resolve({providerId, templateId,
              modelId, apiType, baseUrl})                    resolver.ts:257
            └─ 6 类规则按序 overlay → ModelConfig               model-config.ts:387-423
          createRegistryModelConfig(config, path)
            └─ config.validateComplete(path)                   model-config.ts:122
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
        options: { reasoningLevel: "high" }            shared/model-selection.ts:7-15
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
        + 推理遥测（requestedLevel）                        runner.ts:197-209
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
      │    非 string body 且有 body → 直接抛错（fail-closed）  :40-42
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

| # | ZCode 的做法 | 我们的差距 | 严重度 |
|---|---|---|---|
| 1 | **参数注入是"请求体补丁"，不是"参数值覆盖"**。可以一次写多个字段、嵌套结构、按条件改变字段集合 | 我们只能 `body[k] = v`，**无法表达"关闭时不发 effort"** 这类条件 | 🔴 高 |
| 2 | **按 (模型 × 协议 × 站点) 三维匹配规则**，同一模型不同厂商走不同 map | 我们 `params` 只挂在 `SystemModel` 上，**没有协议/站点维度**；`SystemModel` 有多个 resource 时无法区分 | 🔴 高 |
| 3 | **注入点在出站 fetch 层**，与 SDK/协议解耦，一处生效 | 我们在 `_out_body` 里手写，`endpoint` 分支处理 | 🟡 中 |
| 4 | **配置期就把 DSL 编译校验**，语法错误进不了配置文件 | 我们只有 `PARAM_RANGES` 数值校验，**没有语义校验**（比如"这个厂商根本不支持 `max_tokens`"检测不出来） | 🟡 中 |
| 5 | **分层覆盖 + 兜底规则**：稀疏规则层 + `.*` catch-all 补齐 → 完整配置 | 我们只有模型级 dict，**没有"从泛到专"的规则链** | 🟡 中 |
| 6 | **路径冲突守卫**：两个 option 写同一路径直接报错 | 无。我们 `apply_model_params` 和 `inject_reasoning_into_body` 可能互相覆盖（例如 params 里配了 `reasoning_effort`，又被 reasoning 注入覆盖）——**这是一个真实的现存 bug 风险** | 🔴 高 |
| 7 | **fail-closed**：patch 失效宁可请求失败 | 我们 `apply_model_params` 静默跳过（`if body.get(k) is None`），配置写错只会"参数不生效"，**无告警** | 🟡 中 |
| 8 | **能力位（properties）与参数（optionSpecs）走同一套规则表** | 我们 `SystemModel.params` 与能力声明分离 | 🟢 低 |
| 9 | **档位词表（values）与线格式（map）解耦**：UI 只认 values，map 只认线格式 | 我们 `ReasoningSpec.effort` 是 opaque 字符串，**没有词表概念**，UI/工具可以传任意值 | 🟡 中 |

### 11.3 ZCode 复杂在哪（要付的代价）

1. **规则表爆炸**：119 条 map、478 条规则、6212 行 JSON，其中大量重复（`{"reasoning_effort": reasoningLevel}` 重复 17 次）。**这是因为求值期上下文太窄**，只能靠配置期穷举。
2. **求值期几乎无表达力**：单标量输入 → 任何"依赖两个以上输入"的逻辑（如 `if thinking_enabled and max_tokens > 4096`）都表达不了。
3. **没有测试**：`packages/model-option-map/` 下**零测试文件**（已全库搜索 `*.test.ts` / `*.spec.ts`，该包无任何测试）。119 条 map 的正确性依赖人工与端到端验证。**这是它最大的工程缺陷**——DSL 这么核心的组件没有单元测试，说明维护者靠"配置是数据、改错了容易发现"来兜底。
4. **无版本化迁移的 DSL**：`schemaVersion: 1` 只保护外层结构，`map` 字符串一旦语义变更（如改掉变量名），所有历史配置同时失效。`legacy-reasoning-level.ts` 就是在打这个补丁（用 `legacyReasoningLevelRenames` 硬编码旧档位别名 `off` / `nothink` → `disabled`）。
5. **两层 patch 语义容易混淆**：配置层 overlay 是"后者覆盖前者、undefined=继承"，请求层 merge patch 是"null=删除、路径冲突报错"。两套规则，学习成本不低。
6. **引入了一门语言**：虽然禁止了函数调用和成员访问，但它仍是一门需要词法/语法/求值三件套的语言。**对只有 2 个参数的系统来说，这是一个偏重的选择。**

### 11.4 落地建议（具体、分级、可执行）

> 核心判断：**不建议照搬 DSL。建议借鉴「三层结构 + 补丁语义 + 冲突守卫 + fail-closed」，用纯声明式规则表实现。**

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

**改法**：把 ZCode 的 21 种 map **降维成纯数据表格**——因为实测只有 3 种结构，用枚举即可，无需表达式求值：

```python
# model_gateway/config/reasoning_dialect.py（新增）
from enum import Enum

class ReasoningDialect(str, Enum):
    """实测归纳：ZCode 的 21 种 map 可归入 6 个结构模板。"""
    # ① thinking.type = enabled|disabled，不配 effort
    ANTHROPIC_BINARY      = "anthropic_binary"
    # ② thinking.type = enabled|disabled + output_config.effort（disabled 时 effort 省略）
    ANTHROPIC_EFFORT      = "anthropic_effort"
    # ③ thinking.type = adaptive + output_config.effort（disabled 时只发 thinking）
    ANTHROPIC_ADAPTIVE    = "anthropic_adaptive"
    # ④ reasoning.effort（disabled → "none"）
    OPENAI_RESPONSES      = "openai_responses"
    # ⑤ reasoning_effort 裸字段（低/中/高档位直接透传）
    OPENAI_CHAT_EFFORT    = "openai_chat_effort"
    # ⑥ enable_thinking 布尔
    QWEN_BOOLEAN          = "qwen_boolean"
    # ⑦ 不注入（ZCode 的 map: "{}"）
    NONE                  = "none"

class EffortWordMap:
    """语义档位 → 厂商词表。ZCode 的 'enabled'→'high'、'disabled'→'none' 就是这个表。"""
```

配合配置：

```yaml
# config.example.yaml 片段
system_models:
  - name: glm-4.6
    params: { temperature: 0.6 }
    reasoning:
      dialect: anthropic_effort      # ← 取代硬编码
      levels: [disabled, enabled, low, high, max]   # ← ZCode 的 values
      effort_words:                  # ← 语义档位 → 厂商词表（ZCode 的 enabled→high）
        enabled: high
        disabled: null               # null = 不填 effort
```

**关键论证：为什么不要 DSL？**

用第 2.5 节的实测数据说话——ZCode 内置 119 条 map 里：

| 需要的表达力 | 实测占比 |
|---|---|
| 对象字面量 + 三元 + `==` | **100%** |
| 算术、比较、数组、`null` 删除 | **0%** |

而三元 + `==` 的全部用途，归纳下来只有 **3 个语义**：
1. **键名映射**（`max_tokens` / `max_completion_tokens` / `max_output_tokens`）→ 一个字符串字段
2. **档位词表翻译**（`enabled`→`high`、`disabled`→`none`）→ 一个 dict
3. **字段集合条件化**（disabled 时不发 effort）→ 一个枚举（6 种结构模板）

**这 3 个语义用 3 个数据字段就能完全覆盖，不需要词法分析、语法分析、求值器。**

> **结论：引入 DSL 是过度设计。** ZCode 之所以用 DSL，是因为它要处理 **478 条规则 × 多站点 × 多协议**的组合爆炸，且必须支持"配置热更新不改代码"。我们网关的规模（系统模型数量级小、厂商数可控）用**声明式表格 + 枚举**性价比高得多。**等规则真的膨胀到几百条、且非工程师需要改参数时，再考虑引入 DSL**——那时可以照抄 ZCode 的 `parser.ts`/`evaluator.ts`（它是 MIT/自有许可下的 866 行实现，移植成本低）。

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
- **运行期**：`readRequestBody` 非文本 body → 直接抛错（fail-closed）

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
| 自研 DSL（tokenizer + parser + evaluator） | 实测表达力需求只有 3 个语义；引入语言 = 引入词法/语法/求值/错误定位/版本迁移的长期维护成本。**除非规则数量增长 10 倍以上。** |
| 求值期只用单标量输入 | 我们完全可以用 `context: dict`（含 `api_type` / `vendor` / `model` / `user_options`），比 ZCode 更灵活且不需要穷举规则 |
| 478 条规则的穷举式配置 | 那是"求值期无上下文"的补偿措施。我们有了上下文就不需要这么多规则 |
| 用 `templateId + modelId` 精确匹配 244 条 | 我们的模型数量级不支持这种写法；用前缀/正则匹配 + 少量精确覆盖即可 |
| `map: "{}"` 表示"不注入" | 我们直接不配 `params` 就行（`apply_model_params` 已经 `if not params: return body`，`ir.py:65-66`），语义更直白 |
| 一次注入 4 个方言字段（`zcode-builtin.json:2514`） | 这是"不知道对面是谁"的防御式广播，**会把不确定性推给下游、放大 400 风险**。我们应该精确匹配 resource 的协议，只发一种 |

### 11.6 优先级排序的行动清单

| 顺序 | 动作 | 产出 | 风险 |
|---|---|---|---|
| 1 | 新增 `core/param_patch.py`：`NamedPatch` + `apply_patches` + 冲突守卫 | 消除 params/reasoning 互相覆盖的现存隐患 | 低（纯新增，`_out_body` 改 3 行） |
| 2 | 推理方言表：`ReasoningDialect` 枚举 + `effort_words` 映射表，替换 `inject_reasoning_into_body` 的硬编码 | 接新厂商只改 YAML | 中（需回归全部已支持厂商，但现有 E2E 测试可覆盖） |
| 3 | `resource.params_override` 四级优先级 | 同模型多厂商可区分 | 中（schema 变更 + 文档） |
| 4 | `PARAM_SPEC` 配置期支持矩阵校验 + 启动即报错 | 配置错误前移 | 低 |
| 5 | `capabilities` 字段与 `params` 并列 | 能力判断集中化 | 低 |
| 6 | 补丁可观测性事件 | 可排查性 | 低 |

---

## 12. 未验证 / 存疑事项（诚实清单）

1. **`packages/model-option-map/` 无任何测试**。已用 `find . -name "*.test.ts" -o -name "*.spec.ts"`（排除 node_modules）全库搜索，该包下 0 命中；全库 144 个测试文件中无相关测试。**因此 DSL 的边界行为（如 `1 == "1"`、`pathsOverlap` 的极端情况）我依据源码推断，未经测试验证。**
2. **`invalid-reasoning-mapping` 与 `invalid-pattern` 两个错误码无生产点**（已 grep 全库确认只在 `config-overlay.ts:8-9` 声明、`dist/config-overlay.d.ts:2` 编译产物中出现）。推测为历史遗留或"预留未实现"，**无法确认原设计意图**。
3. **`legacyReasoningLevelRenames` 的具体内容未读**（`packages/provider-node/src/legacy-reasoning-level-renames.ts`）。我只确认了 `legacy-reasoning-level.ts:24` 使用它把 `off` / `nothink` 映射回 `disabled`，但**映射表的完整内容未验证**。
4. **`config/provider/zcode-builtin.json` 的 `revision: 30` 对应的实际发布节奏未验证**；`packages/provider-node/src/zcode-builtin-remote-synchronizer.ts` 的远端同步/回落策略我只读到注释，**未读实现细节**。
5. **`ModelConfigRules.resolve` 在个人层与内置层之间的确切交互**我只验证了 `composeEffective`（`model-config.ts:379-381`）与 `resolve` 主循环（`:390-421`）；`manual-provider-model` 分支的 `clearManualModelConfig` 语义（`:396-399`）注释说明了意图，**但边界情况（如手动规则只改 `enabled` 时系统映射是否保留）未逐路径验证**。
6. **ZCode 是否有其他参数（temperature 等）的处理机制**：本报告结论是"option map 只处理 2 个参数"。我 grep 过 `temperature` 未在 `model-option-map` 相关链路出现，**但不排除参数在 AI SDK 调用层（`runner-generate.ts` / `runner-options.ts`）以其他方式传递**——这两个文件未通读。
7. **`enabled` 字段的完整语义**：`resolver.ts:221` 对 `zhipu-account` 类型强制 `enabled=true`（"账号不再支持总禁用"），我理解了这个分支，但**`providerConfigRules` 里 `enabled` 与 `modelConfigRules` 里 `enabled` 的优先级关系未逐路径验证**。
8. **性能数据未实测**：`compiler.ts` 的三级缓存、以及 fetch 层每请求 `parse+stringify` 的开销，我只做了源码层面的定性分析，**没有 benchmark**。

---

## 13. 证据附录（file:line 清单）

### 13.1 `packages/model-option-map/src/`（核心，866 行）

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
| `merge-patch.ts` | 80-93 | `cloneJson`（含 `Object.create(null)`） |
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
| `model-selection.ts` | 30-37 | `formatModelPickerValue`（`provider/model$level`） |
| `model-selection.ts` | 40-56 | `parseModelPickerValue` |

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
| `config/provider-data-schema.ts` | 37-46 | `apiKeyAccessDataSchema` / `completeApiKeyAccessDataSchema` |
| `config/provider-data-schema.ts` | 49-63 | `zhipuAccountAccessDataSchema` |
| `config/provider-data-schema.ts` | 76-88 | `providerApiDataSchema` / `completeProviderApiDataSchema` |
| `config/provider-data-schema.ts` | 90-106 | `providerConfigDataSchema` / `completeProviderConfigDataSchema` |
| `config/model-config.ts` | 43-76 | `EnumOptionSpecConfig`（`values` + `map`） |
| `config/model-config.ts` | 80-107 | `LimitOptionSpecConfig`（`max` + `map`） |
| `config/model-config.ts` | 177-244 | `ModelPropertiesConfig`（★能力位） |
| `config/model-config.ts` | 248-276 | `ModelOptionSpecsConfig` |
| `config/model-config.ts` | 285-335 | `ModelConfig`（`enabled` / `properties` / `optionSpecs`） |
| `config/model-config.ts` | 324-326 | `validateComplete` → `completeModelConfigDataSchema` |
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
| `resolver.ts` | 257-263 | `effectiveModelRules.resolve({providerId, templateId, modelId, apiType, baseUrl})` |
| `resolver.ts` | 271-275 | `createRegistryModelConfig` |
| `resolver.ts` | 278-280 | ★`modelEnabled` / `executable` / `selectable` |
| `resolver.ts` | 355-376 | `resolveProviderOrder`（family 优先） |
| `registry.ts` | 9-35 | `ModelSelectionValidation`（含 `reasoning-level-*` 两种） |
| `registry.ts` | 74-92 | `validateSelection` |
| `registry.ts` | 129-159 | ★`validateModelSelectionOptions` |
| `registry.ts` | 140-147 | `reasoning-level-missing` |
| `registry.ts` | 148-157 | `reasoning-level-not-supported` + `supportedLevels` |

### 13.4 `packages/provider-node/src/`

| 文件 | 行 | 内容 |
|---|---|---|
| `zcode-builtin-release.ts` | 11 | `ZCODE_BUILTIN_RELEASE_SCHEMA_VERSION = 1` |
| `zcode-builtin-release.ts` | 26-34 | `releaseSchema`（`schemaVersion` literal + `revision`） |
| `zcode-builtin-release.ts` | 36-58 | ★`decodeZCodeBuiltinRelease` |
| `zcode-builtin-release.ts` | 43-47 | ★拒绝已退役 Provider `builtin:zapi` |
| `zcode-builtin-release.ts` | 60-77 | `encodeZCodeBuiltinRelease` |
| `zcode-builtin-cache-paths.ts` | 39-40 | 缓存文件路径（`zcode-builtin.json`） |
| `zcode-builtin-provider-config-source.ts` | 213 | revision 形如 `` `zcode-builtin:${revision}:${sourceKey}` `` |
| `legacy-reasoning-level.ts` | 13-60 | ★`resolveLegacyReasoningLevel`（`off` / `nothink` → `disabled`） |
| `legacy-reasoning-level.ts` | 24 | 只处理 `"off"` / `"nothink"` |
| `legacy-reasoning-level.ts` | 58-59 | `values?.includes(oldLevel) ? "disabled" : undefined` |

### 13.5 `apps/zcode-cli/packages/`

| 文件 | 行 | 内容 |
|---|---|---|
| `adapters/src/model/model-option-map-fetch.ts` | 9-11 | `RawRequestBodyCapture` |
| `adapters/src/model/model-option-map-fetch.ts` | 13-31 | ★★`createModelOptionMapFetch`（唯一注入点） |
| `adapters/src/model/model-option-map-fetch.ts` | 23 | ★`input.maps.apply(body, input.values)` |
| `adapters/src/model/model-option-map-fetch.ts` | 24 | `capture.body = patched` |
| `adapters/src/model/model-option-map-fetch.ts` | 26-29 | 重新构造 Request 转发 |
| `adapters/src/model/model-option-map-fetch.ts` | 33-45 | `readRequestBody` |
| `adapters/src/model/model-option-map-fetch.ts` | 38-42 | ★fail-closed 抛错 |
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
| `adapters/src/model/runner.ts` | 161-162 | 推理遥测（`requestedLevel`） |
| `adapters/src/model/runner.ts` | 223-257 | ★`resolveForRequest` |
| `adapters/src/model/runner.ts` | 331-339 | ★`requireMaxOutputTokens`（undefined 抛错） |
| `contracts/src/model/model.ts` | 26-29 | `ModelOptions { reasoningLevel?, maxOutputTokens? }` |
| `contracts/src/model/model.ts` | 31-37 | `ModelRequest` |
| `contracts/src/model/model.ts` | 41-54 | `Model` 接口（`bind` / `generateText` / `streamText`） |
| `core/src/model/auxiliary-model-options.ts` | 12 | ★`Math.min(AUXILIARY_MAX_OUTPUT_TOKENS, model.optionSpecs.maxOutputTokens.max)` |
| `core/src/tool/handlers/read-session-context.ts` | 339-341 | ★`Math.min(..., model.optionSpecs.maxOutputTokens.max)` |
| `core/src/tool/handlers/websearch.ts` | 98 | ★`Math.min(4096, model.optionSpecs.maxOutputTokens.max)` |

### 13.6 `packages/ui/src/`

| 文件 | 行 | 内容 |
|---|---|---|
| `lib/modelThoughtOption.ts` | 5-33 | ★`resolveModelThoughtOption`（UI 从 `optionSpecs.reasoningLevel.values` 生成下拉） |
| `lib/modelThoughtOption.ts` | 16 | `if (!reasoning || reasoning.values.length === 0) return null` |
| `lib/modelThoughtOption.ts` | 24-27 | ★注释："Reasoning 没有默认档位；空字符串表示模型已选但用户尚未选择 reasoning" |

### 13.7 配置数据（`config/provider/zcode-builtin.json`，6212 行）

| 行 | 内容 |
|---|---|
| 1-3 | `schemaVersion: 1` / `revision: 30` |
| 6-31 | `templateRules[0]` = `zai-api`（anthropic-messages @ api.z.ai） |
| 33-96 | `templateRules[1]` = `zai-standard-api`（openai-chat-completions，23 个内置模型） |
| 98-120 | `templateRules[2]` = `bigmodel-api` |
| 122-… | `templateRules[3]` = `bigmodel-standard-api` |
| 894 | ★`modelRules` catch-all：`"map": "{}"` |
| 2463-2482 | `modelRules` 中的 `mimo-v2-flash` 规则（`values: ["disabled","enabled"]`，`max: 65536`） |
| 2484-2535 | ★`modelApiRules` 三条协议兜底（anthropic / chat-completions / responses） |
| 2500 | ★anthropic-messages 兜底 map（三元 + `output_config.effort`） |
| 2503 | ★`{'max_tokens': maxOutputTokens}` |
| 2514 | ★openai-chat-completions 兜底 map（**一次写 4 个方言字段**） |
| 2517 | ★`{'max_completion_tokens': maxOutputTokens}` |
| 2528 | openai-responses 兜底 map |
| 2531 | ★`{'max_output_tokens': maxOutputTokens}` |
| 2543 | `ox-alpha` / `glm-x-preview-f` @ anthropic（`values: ["low","high","max"]`） |
| 2555 | ★`{"reasoning_effort": reasoningLevel}` |
| 2561-2569 | `.*glm-5` @ anthropic → `thinking.type` 二元开关 |
| 2571-2580 | `.*GLM-5\.2` @ anthropic → 条件分支 + `output_config.effort` |

### 13.8 我们网关（`/Users/w/Desktop/Model-Gateway/`）

| 文件 | 行 | 内容 |
|---|---|---|
| `model_gateway/config/schemas.py` | 150-190 | ★`SystemModel`（`params` + `_validate_params`） |
| `model_gateway/config/schemas.py` | 154-155 | ★注释：优先级 = 工具调用传参 > 此处 > 厂商内置 |
| `model_gateway/config/schemas.py` | 166 | `params: dict[str, Any]` |
| `model_gateway/config/schemas.py` | 169-190 | `PARAM_RANGES` 范围校验（未知键放行） |
| `model_gateway/core/ir.py` | 28-55 | `merge_reasoning`（三级合并 + 矛盾防护） |
| `model_gateway/core/ir.py` | 58-70 | ★`apply_model_params`（字段级注入） |
| `model_gateway/core/ir.py` | 65-66 | `if not params: return body` |
| `model_gateway/core/ir.py` | 68-69 | `if body.get(k) is None: body[k] = v` |
| `model_gateway/core/ir.py` | 73-91 | `lift_reasoning_from_body`（入站提升） |
| `model_gateway/core/ir.py` | 94-111 | ★`inject_reasoning_into_body`（硬编码单一方言） |
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

**ZCode 的模型参数处理机制 = 一个 866 行的私有包，做三件事：**

1. **定义一门极窄的语言**（Restricted CEL）：只能引用**一个**标量变量（`reasoningLevel` 或 `maxOutputTokens`），必须返回一个 JSON object，禁止成员访问和函数调用。
2. **把语言编译成闭包并缓存**：`tokenize → parse → 捕获 AST 的 evaluate 闭包`，三级缓存；编译在 **schema 校验期**（配置写错就进不了文件）和 **Model 创建期**（每 Model 一次）各跑一次。
3. **把求值结果当 RFC 7386 JSON Merge Patch 打到出站请求体上**：注入点在 fetch 拦截器，与协议/SDK 完全解耦；多个补丁写入重叠路径时**抛错而非覆盖**。

**它解决"同一模型不同厂商标准不一致"的方式是：**
- **语义层统一**：上游只说 `reasoningLevel: "disabled" | "enabled" | "low" | "high" | "max"`
- **方言层穷举**：478 条配置规则，按 `modelMatch`(正则) × `apiTypeMatch` × `baseUrlMatch` 三维匹配，119 条 map 覆盖 21 种 reasoning 方言 + 4 种 max_tokens 方言
- **优先级**：`model` → `model-api` → `provider-site` → `template-model` → `provider-model` → `manual-provider-model`（越具体越晚应用、越优先），字段级 overlay（`undefined`=继承 / `null`=重置）

**它不管的**：temperature / top_p / 惩罚项 / stop / 工具调用格式 / 缓存参数 / 多模态字段形态。

**给我们网关的三条最有价值的借鉴（按优先级）：**
1. **把"参数注入"升级为"命名补丁 + 路径冲突守卫"** —— 立即消除 `params` 与 `reasoning` 互相覆盖的现存隐患（`ir.py:68` vs `ir.py:111`）。
2. **把推理方言从硬编码改为数据表**（6 个结构模板 + 档位词表 dict），**但不要引入 DSL** —— 实测 119 条 map 只用到"对象字面量 + 三元 + `==`"，归纳后只有 3 个语义，用枚举+dict 完全覆盖。
3. **引入 resource 级参数覆盖 + 配置期支持矩阵校验 + fail-closed** —— 用 ZCode 的 `providerSiteRules`（52 条站点规则）证明"站点/协议"是必须的区分维度。
