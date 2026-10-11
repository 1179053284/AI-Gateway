# 08 · WorkBuddy 首次接入实测与「工具侧契约」

> **本文性质**：**实测记录**（不是调研推断）。所有结论均附可复跑的原始命令 / 原始输出 / `file:line`。
> **实测时间**：2026-09-24 22:47–23:05
> **实测人**：AI（经用户授权使用 `/Applications/WorkBuddy.app`）
> **解决了什么**：`07` §5.1 的 **B1（工具实际接入机制）** —— 从"推断"变成"实测"，并**端到端跑通**。

---

## 一、这次实测要回答什么

| # | 问题 | 上一版状态 | 本次状态 |
|---|---|---|---|
| Q1 | 网关能不能被**真实工具**消费？ | 只做过 curl | ✅ **端到端跑通**（工具 → 网关 → 商汤 → 回包） |
| Q2 | 工具到底把配置存在**哪个文件**、什么**格式**？ | 推断 | ✅ 实测拿到路径 + 格式 + 字段全集 |
| Q3 | 工具需要网关提供**哪些字段**？ | 推断（"能力位"） | ✅ 实测拿到**完整字段清单**（含 `caps` 子结构） |
| Q4 | 工具有没有会**悄悄改我们请求**的行为？ | 未考虑 | ⚠️ **有 3 处**，已逐条取证（见 §4.5） |
| Q5 | 工具怎么处理"思考强度"这个参数？ | 未考虑 | ✅ 实测拿到**完整归一化引擎**（7 档 + clamp + translate），见 §4.6 |
| Q6 | 接入的真实阻塞点在哪？ | 未知 | ✅ 已定位（见 §五） |

---

## 二、实测环境（可复现）

| 项 | 值 | 取证方式 |
|---|---|---|
| 网关 | `127.0.0.1:8300`，PID 19819，`python3.1` | `lsof -nP -iTCP:8300 -sTCP:LISTEN` |
| 网关配置 | `data/config.yaml`（108 行，`data/` 已 gitignore） | 直接读 |
| 工具（GUI） | `/Applications/WorkBuddy.app` v5.6.2，`com.tencent.workbuddy.mac` | `PlistBuddy` 读 `Info.plist` |
| 工具（CLI） | 同包内 `Contents/Resources/app.asar.unpacked/cli`，`@genie/agent-cli`，`--version` = **2.147.0** | 直接运行 `--version` |
| CLI 入口 | `cli/bin/codebuddy`（`bin` 映射 `codebuddy-code` / `codebuddy` / `cbc`） | `package.json` |
| CLI 主包 | `cli/dist/codebuddy-headless.js`（12,479,847 字符，单文件打包） | 静态读取 + 正则定位 |
| 上游厂商 | 商汤 TokenPlan `https://token.sensenova.cn/v1` | `data/config.yaml:43` |
| 参考项目只读约束 | 全程未修改 `/Applications/WorkBuddy.app` 内任何文件 | — |

---

## 三、网关侧实测

### 3.1 接入前：链路通、配置空 → 全部模型 503

```
$ curl -s -H "Authorization: Bearer <token>" http://127.0.0.1:8300/v1/models
→ 200，返回 7 个模型（含网关扩展字段 endpoint / group）
```

```
$ curl -s -X POST http://127.0.0.1:8300/v1/chat/completions \
    -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
    -d '{"model":"sensenova-6.8-flash-lite","messages":[{"role":"user","content":"只回复两个字：你好"}],"max_tokens":32}'
→ HTTP 503  耗时 0.0014s
{"error":{"message":"无可用资源；原因：无可用资源","type":"gateway_error",
          "code":"NO_RESOURCE","system_model":"sensenova-6.8-flash-lite"}}
```

**根因**（`data/config.yaml` 逐行核对）：7 个系统模型的 `resources` **全部为空数组**：

```
models[0].resources: []   # sensenova-6.8-flash-lite
models[1].resources: []   # deepseek-v4-flash
...  (7/7 全空)
resources: [ res-sensenova-main ]   # 只有 1 个资源，未被任何模型引用
```

> **这一条本身就是一个必须报告的发现**：网关**代码链路完全正常**（鉴权 ✓ / 模型列表 ✓ / 路由到调度器 ✓ / 错误结构规范可诊断 ✓），但**配置层零映射** → 所有模型不可用。
> 错误响应里的 `code: NO_RESOURCE` + `system_model` 字段让定位只花了 1 次请求 —— **错误设计是合格的**。

### 3.2 补齐映射后：4 个模型真实 200

**操作方式**：走网关自己的管理端 API（**不手改文件**，可回滚）：

```python
cfg = GET  /admin/api/config
for m in cfg["models"]:
    if not m["resources"]:
        m["resources"] = [{"resource": "res-sensenova-main", "model": m["name"]}]
PUT /admin/api/config          # → {"status":"ok","message":"配置已保存并生效"}
```

> 备份：`/tmp/mg-config-backup-20260924-224730.yaml`（改动前）

| 系统模型 | HTTP | 回复内容 | prompt / completion tokens |
|---|---|---|---|
| `sensenova-6.8-flash-lite` | 200 | `你好` | 87 / 23 |
| `deepseek-v4-flash` | 200 | `2`（+`reasoning_content`） | 11 / 40（含 reasoning 37） |
| `glm-5.2` | 200 | （见 §3.3 说明） | 17 / 32 |
| `kimi-k3` | 200 | `你好` | 91 / 31 |

### 3.3 推理模型行为：`reasoning_content` 透传

**非流式**原始响应（`deepseek-v4-flash`，`max_tokens=200`）：

```json
{"id":"a329e8a02d53478db299b61754a46c25","model":"deepseek-v4-flash",
 "object":"chat.completion",
 "choices":[{"index":0,
   "message":{"role":"assistant","content":"2",
              "reasoning_content":"我们需要回答用户问题…最终回答：2。"},
   "finish_reason":"stop"}],
 "usage":{"prompt_tokens":11,"completion_tokens":40,"total_tokens":51,
   "completion_tokens_details":{"reasoning_tokens":37},
   "prompt_tokens_details":{"cached_tokens":0}}}
```

**流式**同样透传（`stream:true` 的 SSE chunk）：

```
data: {"choices":[{"delta":{"reasoning_content":"我们需要"},"finish_reason":""}]}
```

> **⚠️ 对工具接入的关键含义**：`glm-5.2` 在 `max_tokens=32` 时**返回空 content** —— 不是 bug，是**思考 token 把预算吃满了**。下游工具若不认识 `reasoning_content`、又不给足 token 预算，用户看到的就是"模型不回话"。
> **这正是"网关必须声明 `supportsReasoning`"的实证理由**（工具据此调整预算与渲染方式）。

### 3.4 带前缀的模型名 → 404（一个必须处理的设计点）

| 请求的 `model` | 网关响应 |
|---|---|
| `glm-5.2` | ✅ 200 |
| `custom:glm-5.2` | ❌ 404 `model_not_found` |
| `custom-local:glm-5.2` | ❌ 404 `model_not_found` |

**背景**：WorkBuddy CLI 的自定义模型 id 必须带前缀（`custom:` 或 `custom-local:`，见 §4.2），但 CLI **只会剥掉 `custom-local:`**，`custom:` 会原样发出。

**结论（设计建议）**：网关入站应**剥离 `custom:` / `custom-local:` 前缀**后再匹配模型名 —— 这是"入站别名归约"的一个具体实例（`06` §5.2 的同一思想）。

### 3.5 商汤 TokenPlan 是一个「聚合端点」（影响厂商归属模型）

```
$ curl -s -H "Authorization: Bearer <key>" https://token.sensenova.cn/v1/models
→ 共 9 条：
   deepseek-v4-flash · glm-5.2 · sensenova-u1-fast · sensenova-6.8-flash-lite
   sensenova-u1.5-lite · deepseek-v4-pro · kimi-k3 · deepseek-flash · deepseek-v4.1-flash
```

**三个结论**：

1. **同一个 Key 就能调 5 家厂商的模型** —— 商汤自己在做聚合。
2. **厂商侧模型名与系统模型名 1:1 同名**（7/7 命中）→ 映射可自动推导，不必手工填。
3. **"厂商归属"与"接入商"确实是两件事**（印证 `prd.md:546` 的 Q24-② 判断）：`deepseek-v4-flash` **经商汤接入**，但厂商归属是 **DeepSeek**。

> 这同时解释了为什么 `config.yaml` 里 7 个系统模型只挂了 1 个资源 —— 设计意图就是"一个商汤资源供全部模型"。

---

## 四、工具侧契约（从 CLI 代码实测，非推断）

> 取证方式：在 12.4 MB 单文件包 `cli/dist/codebuddy-headless.js` 里按关键字定位并提取上下文。
> 下文每条均附关键字，可复跑核验。

### 4.1 自定义模型文件：位置 + 格式

> **⚠️ 2026-09-24 23:10 更正**：本节初稿把路径写成了 `~/.workbuddy-ai/models.json`，**这是错的** —— 那是我当时被会话环境变量劫持到「WorkBuddy **AI**」目录的产物。**WorkBuddy 的正确路径是 `~/.workbuddy/models.json`**。下方为更正后的内容，并附两条独立证据。

**证据①：WorkBuddy 身份的历史日志**（`~/.workbuddy/logs/2026-09-02/__workbuddy_cli_host__*.log`，本次实测前就已存在）：

```
[CustomModelsProductProvider] productName=WorkBuddy, isWorkBuddy=true,
    userConfigPath=/Users/w/.workbuddy/models.json
```

**证据②：`getUserConfigPath` 的源码逻辑**（关键字 `getUserConfigPath`）：

```js
getUserConfigPath(productName, customUserDataDir) {
  // ① 环境变量优先（注意：WORKBUDDY_CONFIG_DIR 比 CODEBUDDY_CONFIG_DIR 更优先）
  let env = process.env.WORKBUDDY_CONFIG_DIR?.trim() || process.env.CODEBUDDY_CONFIG_DIR?.trim();
  if (env) return path.join(env, "models.json");
  // ② 否则：product 声明的 customUserDataDir → ③ productName 含 "workbuddy" 用 ".workbuddy" → ④ 否则 ".codebuddy"
  let dir = customUserDataDir?.trim()
            || (this.isWorkBuddyProduct(productName) ? ".workbuddy" : USER_DATA_DIR_NAME);
  return path.join(homedir(), dir, "models.json");
}
isWorkBuddyProduct(name) { return (name || "").toLowerCase().includes("workbuddy"); }
```

**`USER_DATA_DIR_NAME = ".codebuddy"`**（关键字 `USER_DATA_DIR_NAME=`）。

**结论**：

| 项 | 值 |
|---|---|
| **WorkBuddy 的全局文件** | **`~/.workbuddy/models.json`**（`dataFolderName: .workbuddy`）✅ |
| WorkBuddy AI 的全局文件 | `~/.workbuddy-ai/models.json`（`dataFolderName: .workbuddy-ai`） |
| 项目级文件 | `<cwd>/.codebuddy/models.json` |
| **格式** | **`{ "models": [...], "availableModels": ["id", ...] }`** —— **不是裸数组** |
| `availableModels` 作用 | 白名单过滤（`provide()` 里 `models.filter(...)`），不在表里的模型**不展示** |
| 环境变量 | `WORKBUDDY_CONFIG_DIR` > `CODEBUDDY_CONFIG_DIR` > `customUserDataDir` > productName 推断 |

**⚠️ 两个产品、两套 `dataFolderName`（对 `mgw setup` 的设计影响很大）**：

| | WorkBuddy（`WorkBuddy.app`） | WorkBuddy AI（`WorkBuddy AI.app`） |
|---|---|---|
| `productName` | `WorkBuddy` | `WorkBuddy AI` |
| `dataFolderName` | **`.workbuddy`** | **`.workbuddy-ai`** |
| `endpoint` | `https://www.workbuddy.cn` | `https://www.workbuddy.ai` |
| `darwinBundleIdentifier` | `com.tencent.workbuddy.mac` | `com.workbuddy.workbuddy-ai` |
| CLI 二进制 | 两者**共用同一份** `@genie/agent-cli`(2.147.0) | 同左 |

> **设计含义**：`mgw setup <tool>` **不能硬编码配置目录**，必须按「产品标识 → `dataFolderName`」解析；否则把 WorkBuddy 的模型写进 WorkBuddy AI 的目录（或反之）会导致**静默失效**。
>
> **另一个坑**：`isWorkBuddyProduct()` 用的是 `includes("workbuddy")`，**`"WorkBuddy AI"` 也会被判定为 WorkBuddy**，所以**不能靠这个函数区分两个产品**，必须读 product 声明里的 `dataFolderName`。

**代码取证**（关键字 `parseModelsJson`）—— 格式要求：**对象，不是裸数组**：

```js
function parseModelsJson(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return { models: [] };   // ← 裸数组直接丢弃
  return { models: Array.isArray(raw.models) ? raw.models : [],
           availableModels: Array.isArray(raw.availableModels) ? raw.availableModels.filter(x=>typeof x==="string") : undefined };
}
```

> **⚠️ 一个仍未完全查清的现象**：`~/.workbuddy/models.json` 在本次实测前是 **405 字节的裸数组**（含 1 条 `deepseek-flash-free` 自定义模型），实测过程中变成 **`[]`（空数组，2 字节）**。
> CLI 侧确有 `reconcileUserModelsJsonToPolicy(path, {warn})` 调用（会按策略重整该文件），但当时 CLI 因环境变量指向的是 `~/.workbuddy-ai/`，**不该改动 `~/.workbuddy/`**；且 `pgrep` 显示 **WorkBuddy.app 当时并未运行**（只有 WorkBuddy AI 在跑）。
> → **改动方未能定位，如实标注为未解决**。原始内容已存 `/tmp/mg-wb-models-original.json`，可恢复。

### 4.2 URL 归一化规则

```js
if (modelCfg?.useCustomProtocol) {
  finalUrl = modelCfg.url;                                    // 原样直通，不做任何改写
} else {
  finalUrl = isCustomModelRequest(id, modelCfg)
    ? normalizeChatCompletionsUrl(modelCfg.url)               // 自定义模型 → 补 /chat/completions
    : modelCfg.url;
}
```

```js
normalizeChatCompletionsUrl(url) {
  // 先剥离 ?query / #hash → 去掉尾部所有 "/" → 循环剥掉所有 "/chat/completions" → 补一个
  return `${stripped}/chat/completions${suffix}`;
}
```

**结论**：

| 配置 | 工具实际请求的 URL |
|---|---|
| `url: "http://127.0.0.1:8300/v1"` + `useCustomProtocol: false` | `http://127.0.0.1:8300/v1/chat/completions` ✅ |
| `url: "http://127.0.0.1:8300/v1/chat/completions"` + `useCustomProtocol: false` | 同上（**幂等**，不会变成 `…/chat/completions/chat/completions`） |
| `url: <任意>` + `useCustomProtocol: true` | **原样**（网关若要接 Anthropic 原生端点，用这个） |

### 4.3 自定义模型识别规则

```js
isCustomModelRequest(id, cfg) {
  const key = id || cfg?.id;
  return !!(key?.startsWith("custom-local:") || key?.startsWith("custom:"))
      || cfg?.trustLevel === "custom"
      || (Array.isArray(cfg?.tags) && cfg.tags.includes("custom"));
}
```

| 常量 | 值 |
|---|---|
| `CUSTOM_MODEL_ID_PREFIX` | `"custom:"` |
| `CUSTOM_LOCAL_MODEL_PREFIX` | `"custom-local:"` |
| `MODEL_TAG_CUSTOM` | `"custom"` |
| `ModelTrustLevel` | `unverified` / `custom` / `certified` |

**发请求前的前缀处理**（关键）：

```js
if (body && modelId) {
  const stripped = stripCustomLocalModelPrefix(modelId);   // 只剥 "custom-local:"
  if (stripped !== modelId && body.model === modelId) body.model = stripped;
}
```

> **实测推论**：`custom-local:glm-5.2` → 网关收到 **`glm-5.2`** ✅
> `custom:glm-5.2` → 网关收到 **`custom:glm-5.2`** ❌（除非网关自己剥前缀，见 §3.4）

### 4.4 模型条目字段全集（工具期望网关声明的东西）

从内置模型条目（`AUTO_TIER_MODELS`）+ 能力解析逻辑实测提取：

| 字段 | 类型 | 用途 | 网关现在给了吗 |
|---|---|---|---|
| `id` | string | 模型 ID（可带前缀） | ✅ `/v1/models` 有 |
| `name` | string | 显示名 | ⚠️ 无（`/v1/models` 只给 `id`） |
| `vendor` | string | 厂商 | ⚠️ 无 |
| `url` | string | 端点 | ✅ 工具侧自己配 |
| `apiKey` | string | 密钥 | ✅ 工具侧自己配 |
| `useCustomProtocol` | bool | URL 是否直通 | ✅ 工具侧自己配 |
| **`supportsToolCall`** | bool | **是否支持工具调用** | ❌ **无** |
| **`supportsImages`** | bool | 是否支持图片输入 | ❌ **无** |
| **`supportsReasoning`** | bool | 是否支持深度推理 | ❌ **无** |
| **`maxInputTokens`** | int | 上下文窗口（用于档位选择 + 展示） | ❌ **无** |
| **`maxOutputTokens`** | int | 最大输出 | ❌ **无** |
| `maxAllowedSize` | int | 允许的最大尺寸 | ❌ 无 |
| `tags` | string[] | 含 `"custom"` 即视为自定义模型 | ❌ 无 |
| `trustLevel` | enum | 信任级别 | ❌ 无 |
| `reasoning` | object | `{effort, summary}` | ❌ 无 |
| **`caps`** | object | **能力声明子结构（见下）** | ❌ **无** |

**`caps` 子结构全集**（关键字 `deriveFromCompat` / `thinkingLevelMap`）：

| 键 | 取值 | 作用 |
|---|---|---|
| `api` | `"openai-completions"` 等 | 协议族 |
| `maxTokensField` | `"max_tokens"` \| `"max_completion_tokens"` | 输出上限写哪个字段 |
| **`thinkingFormat`** | `openai` \| `openrouter` \| `deepseek` \| `together` \| `zai` \| `google-generative-ai` \| `google-vertex` | **思考参数写哪种"方言"** |
| **`thinkingLevelMap`** | `{off,minimal,low,medium,high,xhigh,max} → 厂商值 \| null` | **档位映射表**（`null` = 不支持该档） |
| `reasoning` | bool | 是否支持推理 |
| `supportsReasoningEffort` | bool | 是否接受 `reasoning_effort` |
| `requiresReasoningContentOnAssistantMessages` | bool | 历史消息是否必须带 `reasoning_content` |
| `requiresToolResultName` | bool | 工具结果是否必须带 `name` |
| `supportsImages` | bool | 图片输入 |

> **这是本次实测最有价值的一条**：**工具已经自带"参数归一化引擎"，它要的是网关给出正确的声明。**
> 换言之 —— **网关的职责不是自己去翻译参数，而是"把声明写对"。** 这直接改写了 `06` 的落点（见 §六）。

### 4.5 ⚠️ 工具会「悄悄改」我们请求的 3 处（必须知道）

| # | 触发条件 | 工具的行为 | 取证 |
|---|---|---|---|
| **M1** | 自定义模型 且 `supportsToolCall === false` | **删除** `body.tools` 和 `body.tool_choice` | 关键字 `supportsToolCall`：`delete eS.tools, delete eS.tool_choice` |
| **M2** | 自定义模型 且 **无** `caps.thinkingLevelMap` | **折叠掉** `reasoning_effort` 与 `reasoning.effort` | 关键字 `CustomModelFieldCleanupPlugin` / `LegacyXhighFallbackRule` |
| **M3** | 自定义模型 且 `supportsImages === false` | 把 `content` 数组**扁平化成纯文本**（图片块丢弃/降级为占位符） | 关键字 `supportsImages`：`Flattened array content to string for custom model` |

**后果与对策**：

- **M1 是最致命的**：编程 Agent 工具没有工具调用就退化成聊天机器人。→ **网关必须下发 `supportsToolCall: true`**（对支持的模型）。
- **M2 意味着**：**不下发 `thinkingLevelMap`，工具的推理档位功能就是哑的**（用户设了 `high` 也发不出去）。→ **必须下发。**
- **M3**：与 `06` §七的"能力位"设计直接对应 —— 声明 `supportsImages: false` 的模型，工具会主动降级而不是报错。**这是"声明即契约"的体现。**

> 另有一个产品开关 `SkipToolCallSupportCheck`（本机 = `false`）可以绕过 M1，但**不该依赖它** —— 那是工具的兜底，不是网关的设计。

### 4.6 工具侧的「思考强度归一化引擎」（完整实测）

**规范档位序（7 档，有序）**：

```js
EXTENDED_THINKING_LEVELS = ["off","minimal","low","medium","high","xhigh","max"]
```

**支持的档位怎么算**：

```js
function getSupportedThinkingLevels(cfg) {
  return cfg.reasoning
    ? EXTENDED_THINKING_LEVELS.filter(lv => {
        const v = cfg.thinkingLevelMap?.[lv];
        return v !== null && ( (lv !== "xhigh" && lv !== "max") || v !== undefined );
      })
    : ["off"];
}
```

> 规则：`reasoning` 为假 → 只有 `off`；为真 → 取映射表里**不是 `null`** 的档；其中 **`xhigh` / `max` 还必须"显式出现"**（`undefined` 不算）→ **高阶档必须显式声明才可用。**

**降级 = `clamp()`（就近取，优先向上）**：

```js
clamp(level, map) {
  const supported = getSupportedThinkingLevels({reasoning:true, thinkingLevelMap:map});
  if (supported.includes(level)) return level;
  const i = EXTENDED_THINKING_LEVELS.indexOf(level);
  for (let j = i+1; j < EXTENDED_THINKING_LEVELS.length; j++)
      if (supported.includes(EXTENDED_THINKING_LEVELS[j])) return EXTENDED_THINKING_LEVELS[j];   // ① 先向上
  for (let j = i-1; j >= 0; j--)
      if (supported.includes(EXTENDED_THINKING_LEVELS[j])) return EXTENDED_THINKING_LEVELS[j];   // ② 再向下
  return supported[0] ?? "off";                                                                  // ③ 兜底
}
```

**翻译 = `translate()`（查映射表）**：

```js
translate(level, map, lowerCase) {
  if (!EXTENDED_THINKING_LEVELS.includes(level)) return level;   // 不在规范序 → 原样透传
  const lv = clamp(level, map);
  if (lv === "off") return undefined;                            // off → 不发该字段
  const mapped = map[lv];
  const out = typeof mapped === "string" ? mapped : lv;          // 无映射 → 用规范名
  return lowerCase ? out.toLowerCase() : out;                    // gemini 族小写
}
```

**方言 = `thinkingFormat`（协议族开关）**：

| `thinkingFormat` | 工具实际写进请求体的字段 |
|---|---|
| `openai` / `openrouter` | `reasoning.effort = <值>`（openrouter）；`reasoning_effort = <off 字面量>`（仅当 off 有字符串映射） |
| `deepseek` | `thinking = {type: "enabled"}` / `{type: "disabled"}`，**并删除** `reasoning_effort` |
| `together` | `reasoning.enabled = <bool>` |
| `zai` | `thinking = {type:"enabled", clear_thinking:false}` |
| `google-generative-ai` / `google-vertex` | 值 **小写化** |

**其他两条相关规则**：

```js
// supportsReasoningEffort === false → 直接删字段
ReasoningEffortSupportRule.matches = cfg => cfg.caps?.supportsReasoningEffort === false;
// 无 thinkingLevelMap → 把 xhigh/max 塌陷成 high（保守降级）
LegacyXhighFallbackRule.collapse = (o,k) => { if (o[k]==="xhigh"||o[k]==="max") o[k]="high"; };
```

> **与 `06` 方案的对照结论**：工具的这套引擎 = `06` 的 **L1（规范档位序）+ L2（写入位）+ L3（方言映射表）**，**几乎逐条同构**。
> **差异 3 处**（已在 `06` 修正）：① 档位 **7 档**不是 5 档；② `clamp` **先上后下**（不是"只降不升"）；③ `thinkingFormat` 是**比 `protocol` 更细的"思考参数写法族"**。

### 4.7 端到端实测：CLI → 网关 → 商汤 → 回包

> **⚠️ 更正说明**：本节初稿的 4.7/4.8 两轮测试，CLI 都是被会话环境变量 `WORKBUDDY_CONFIG_DIR=/Users/w/.workbuddy-ai` 劫持到 **WorkBuddy AI** 目录跑的（虽然二进制取自 `WorkBuddy.app`）。
> **§4.9 是用 WorkBuddy 自己目录（`~/.workbuddy/`）重跑的正确版本** —— 那才是真正回答"WorkBuddy 能不能接网关"的证据。前两轮的**工具侧契约结论（§4.1–4.6，字段/URL/能力位/档位引擎）依然成立**，因为那些是同一份 CLI 代码的行为；**只有"配置文件路径"这一条被更正。**

**配置**（初稿误写入 `~/.workbuddy-ai/models.json`；正确路径见 §4.9）：

```json
{
  "models": [{
    "id": "custom-local:glm-5.2",
    "name": "Model-Gateway · GLM-5.2",
    "vendor": "Model-Gateway",
    "url": "http://127.0.0.1:8300/v1",
    "apiKey": "<网关访问令牌>",
    "useCustomProtocol": false,
    "supportsToolCall": true,
    "supportsImages": false,
    "supportsReasoning": true,
    "maxInputTokens": 1048576,
    "maxOutputTokens": 131072,
    "tags": ["custom"],
    "caps": {
      "api": "openai-completions",
      "thinkingFormat": "openai",
      "reasoning": true,
      "supportsReasoningEffort": true,
      "thinkingLevelMap": {"off":"off","minimal":null,"low":"low",
                           "medium":"medium","high":"high","xhigh":null,"max":null}
    }
  }],
  "availableModels": ["custom-local:glm-5.2"]
}
```

**测试 A · 纯对话**

```
$ node <cli>/bin/codebuddy -p "只回复两个字：你好" \
      --model "custom-local:glm-5.2" --output-format json --no-session-persistence
```

```json
{"type":"result","subtype":"success","is_error":false,"result":"你好",
 "duration_ms":4247,"duration_api_ms":4246,"num_turns":2,
 "usage":{"input_tokens":20606,"output_tokens":2,
          "cache_read_input_tokens":1024,"cache_creation_input_tokens":0}}
```

**测试 B · 带工具调用**

```
$ node <cli>/bin/codebuddy -p "用 Bash 工具执行 echo MGW-OK，然后告诉我输出内容" \
      --model "custom-local:glm-5.2" --debug api \
      --output-format json --no-session-persistence --dangerously-skip-permissions
```

**网关侧记录**（`data/usage/events-20260924.jsonl`，2 条）：

```json
{"ts":"2026-09-24T22:58:53.314","system_model":"glm-5.2","status":"success",
 "duration_ms":1828,"input_tokens":20825,"output_tokens":25,
 "retry_count":0,"switch_count":0,"client_token_id":"trae-main","stream":true,
 "final_resource":"商汤 TokenPlan·主Key/glm-5.2","provider":"商汤 TokenPlan"}

{"ts":"2026-09-24T22:58:56.612","system_model":"glm-5.2","status":"success",
 "duration_ms":1940,"input_tokens":20888,"output_tokens":12,
 "retry_count":0,"switch_count":0,"client_token_id":"trae-main","stream":true,
 "final_resource":"商汤 TokenPlan·主Key/glm-5.2","provider":"商汤 TokenPlan"}
```

**网关访问日志**：

```
INFO:  127.0.0.1:50083 - "POST /v1/chat/completions HTTP/1.1" 200 OK
INFO:  127.0.0.1:50083 - "POST /v1/chat/completions HTTP/1.1" 200 OK
```

> **解读**：两轮请求 = 第 1 轮模型决定调工具（output 25 tokens = tool_call JSON），第 2 轮带工具结果再问（output 12 tokens）。
> → **证明：工具调用没有被剥离**（因为声明了 `supportsToolCall: true`，M1 未触发）。
>
> **⚠️ 诚实标注**：测试 B 的 CLI **进程未在合理时间内退出**（网关侧两轮都 success，但 CLI 的 stdout 没有落盘）—— 怀疑卡在 Bash 工具执行的权限/子进程环节（与网关无关）。**「工具调用已被模型正确发出、网关正确转发并成功返回」已由网关侧两条 success 记录证实；「CLI 完整跑完并把最终答案打印出来」未完成验证**，标记为未验证。

### 4.9 ✅ 正确版本：用 WorkBuddy 自己的目录重跑（2026-09-24 23:10）

**为什么必须重跑**：前两轮 CLI 被会话环境变量 `WORKBUDDY_CONFIG_DIR=/Users/w/.workbuddy-ai` 劫持到了 **WorkBuddy AI** 的目录（详见 §4.1 的两条证据）。用户明确指出要测的是 **WorkBuddy**，不是 WorkBuddy AI。

**根因**（`env` 实测）：

```
WORKBUDDY_CONFIG_DIR=[/Users/w/.workbuddy-ai]      ← 由 WorkBuddy AI 会话注入
CODEBUDDY_CONFIG_DIR=[]
```

`getUserConfigPath` 第一条就是读这个环境变量 → 无论 CLI 二进制取自哪个 app，都会跑到 `~/.workbuddy-ai/`。

**修正后的命令**（显式覆盖环境变量，指向 WorkBuddy 自己的目录）：

```
$ WORKBUDDY_CONFIG_DIR=/Users/w/.workbuddy \
      node /Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy \
      -p "只回复两个字：你好" --model "custom-local:glm-5.2" \
      --output-format json --no-session-persistence --debug api
```

**配置文件**：`~/.workbuddy/models.json`（WorkBuddy 自己的目录，内容与 §4.7 相同）

**CLI 输出**：

```json
{"type":"result","subtype":"success","is_error":false,"result":"你好",
 "uuid":"01a0d3f8-6fc9-701a-844a-c0654ad30782",
 "session_id":"01a0d3f8-4a76-7b0d-bd11-eda1eeb813cc",
 "duration_ms":2159,"duration_api_ms":2158,"num_turns":2,
 "total_cost_usd":0,
 "usage":{"input_tokens":20797,"output_tokens":2,
          "cache_creation_input_tokens":0,"cache_read_input_tokens":1280},
 "permission_denials":[]}
```

**网关访问日志**（基线后新增）：

```
INFO:  127.0.0.1:51814 - "POST /v1/chat/completions HTTP/1.1" 200 OK
INFO:  127.0.0.1:51938 - "POST /v1/chat/completions HTTP/1.1" 200 OK
```

**结论**：**WorkBuddy（`/Applications/WorkBuddy.app`，数据目录 `~/.workbuddy/`）端到端接入网关成功。** ✅

---

## 五、接入的真实阻塞点（诚实报告）

| # | 阻塞点 | 证据 | 性质 |
|---|---|---|---|
| **O1** | **工具自身的登录态** | 隔离配置目录首跑：CLI 日志 `hasSession=false hasAccessToken=false`；`restore auth error: Brokered file token requires approval`；进程存活 4 分钟、CPU 0%、**一次模型请求都没发** | **真实阻塞**（与网关无关） |
| **O2** | **🔴 环境变量会把 CLI 劫持到"另一个产品"的目录**（本次实测踩中） | 会话实测 `WORKBUDDY_CONFIG_DIR=/Users/w/.workbuddy-ai`（由 WorkBuddy AI 注入）→ 即使二进制取自 `WorkBuddy.app`，`getUserConfigPath` 第一条就命中该变量 → 跑到 WorkBuddy AI 目录。**初稿因此把路径写错** | **真实，且极隐蔽**：优先级 `WORKBUDDY_CONFIG_DIR` > `CODEBUDDY_CONFIG_DIR` > `customUserDataDir` > productName 推断。`mgw setup` **必须显式覆盖或显式尊重**这个变量，否则配到错误的目录 |
| **O3** | **模型 id 前缀语义分裂** | `custom-local:` 会被剥、`custom:` 不会（§4.2） | 真实（网关侧可一行修掉，见 §3.4） |
| **O4** | **`isWorkBuddyProduct()` 无法区分两个产品** | 实现是 `name.toLowerCase().includes("workbuddy")`，`"WorkBuddy AI"` 同样返回 `true` | 真实（必须读 product 声明的 `dataFolderName`，不能靠这个函数） |
| **O5** | **裸数组格式会被 CLI 静默丢弃** | `parseModelsJson` 对 `Array.isArray(raw)` 直接返回 `{models: []}` | 真实（写错格式 = 静默失效，无任何报错） |

> **O1 是最重要的发现**：**"工具接入"的第一道门不是网关配置，而是工具自身的账号体系。**
> 对 `mgw setup <tool>` 这个功能的含义：**它只能写配置，不能替用户登录**。文档里必须写明"先登录，再配网关"。
>
> **O2 是本次最"贵"的教训**：一个环境变量能让"看起来完全正确的接入"跑到错误的产品目录，而**日志里 productName 显示正常**（初稿日志显示 `productName=WorkBuddy` 但路径是 `.workbuddy-ai`），**极难察觉**。
> **判别方法**：不要只看日志里的 `productName`，要直接看 `userConfigPath` 这一行的实际路径。

---

## 六、对现有方案的影响（修正 3 处 + 新增 1 条设计原则）

### 6.1 修正 ①：规范档位是 **7 档**，不是 5 档

| | 原稿（`06` §5.2） | 实测 |
|---|---|---|
| 档位序 | `off < low < medium < high < max`（5 档） | `off < minimal < low < medium < high < xhigh < max`（**7 档**） |
| `minimal` | 当 `low` 的别名折叠 | **一等档位** |
| `xhigh` | 当 `high` 的别名折叠 | **一等档位**（且必须显式声明才可用） |

→ 已修正 `06` §5.2 与 §5.4 的方言表（键从 5 个扩到 7 个）。

### 6.2 修正 ②：降级是「两层」，不是一条规则

| 层 | 谁做 | 规则 | 依据 |
|---|---|---|---|
| ① **能力层 clamp** | **工具** | 就近取，**优先向上** | 网关下发的 `caps.thinkingLevelMap` |
| ② **方言层降级** | **网关** | 保守降级，**只降不升** | 方言表值域 |

**新增设计原则（重要）**：

> **网关优先把 `thinkingLevelMap` 下发给工具，让工具按 ① 自己 clamp；网关的 ② 只在"工具没有 clamp 能力"时生效。若工具已 clamp，网关不得二次 clamp。**

→ 已修正 `06` §6.1。

### 6.3 修正 ③：网关的落点变了 —— 从「翻译参数」改为「**把声明写对**」

**原方案**：网关自己做 L0→L3 四级归约，把入站参数翻译成厂商方言。
**实测发现**：主流工具（WorkBuddy CLI）**已经自带这套引擎**，它要的是**正确的声明**。

**修正后的双层设计**：

```
【声明式（优先）】
  网关 → 下发 caps（含 thinkingLevelMap / thinkingFormat / 能力位）
  工具 → 用自己的引擎翻译
  网关 → 不介入

【归约式（兜底）】
  工具不带引擎（老工具 / 裸 curl / 简单客户端）
  网关 → 执行 06 的 L0→L3 归约
```

> **这不是推翻 `06`，是给它划清适用边界**：`06` 的引擎**必须有**（兜底 + 网关自己也要调上游），但**优先级低于"把声明写好"**。

### 6.4 新增：`/v1/models` 的下发面缺口（**最重要的落地项**）

**实测结论**：工具需要的 **8 个能力位**（`supportsToolCall` / `supportsImages` / `supportsReasoning` / `maxInputTokens` / `maxOutputTokens` / `name` / `vendor` / `caps`），**网关一个都没给**：

```
GET /v1/models 实测返回：
{"id":"glm-5.2","object":"model","created":0,"owned_by":"model-gateway",
 "endpoint":"chat","group":"编程"}          ← 只有 6 个字段，0 个能力位
```

**而网关内部其实全都有**（`model_gateway/enums/matcher.py:67-140`，`EnumEntry`）：

| 工具要的字段 | 网关内部已有 | 映射关系 |
|---|---|---|
| `maxInputTokens` | `context_window` ✅ | 直映射 |
| `maxOutputTokens` | `max_output` ✅ | 直映射 |
| `supportsImages` | `image_input` ✅ | 直映射 |
| `supportsReasoning` | `reasoning` ✅ | 直映射 |
| `thinkingLevelMap` 的可用档 | `effort_levels` ✅ | 如 `["low","high","max"]` |
| `name` | `display` ✅ | 直映射 |
| `vendor` | `vendor` ✅ | 直映射 |

→ **这是一个"只差最后一步暴露"的缺口**：数据齐备，只是没下发。

**两条下发路径（都需要）**：

| 路径 | 形态 | 适合 | 实测支持 |
|---|---|---|---|
| **A · 文件下发** | 生成/导出一份 `models.json` | WorkBuddy CLI（**只读文件，不调 `/v1/models`**） | ✅ 已验证 |
| **B · API 下发** | 扩展 `/v1/models` 响应（加非标准字段，保持 OpenAI 兼容） | Trae / Cursor / Cherry Studio 等会调 `/v1/models` 的 | ⏳ 待验证 |

---

## 七、给网关的可执行改动清单（本次实测直接导出）

| # | 改动 | 位置（建议） | 依据 |
|---|---|---|---|
| **D1** | `/v1/models` 响应增加能力位字段（`name` / `vendor` / `max_input_tokens` / `max_output_tokens` / `supports_tool_call` / `supports_images` / `supports_reasoning` / `effort_levels`） | `model_gateway/api/openai_compat.py`（模型列表处） | §6.4 |
| **D2** | 入站 `model` 剥离 `custom:` / `custom-local:` 前缀后再匹配 | 入站解析处 | §3.4 / §4.2 |
| **D3** | 新增导出命令：把系统模型 + 能力位写成工具可读的 `models.json`——**目标目录必须按「产品标识 → `dataFolderName`」解析**（WorkBuddy=`.workbuddy`，WorkBuddy AI=`.workbuddy-ai`），**并且要处理 `WORKBUDDY_CONFIG_DIR` 环境变量** | `scripts/` 或 `mgw setup` | §4.1 / §5 O2 / §6.4 |
| **D4** | 配置校验加一条：**模型有映射但资源未启用** / **资源启用但无任何模型引用** → 启动告警 | 配置加载处 | §3.1 |
| **D5** | `SystemModel` 增加 `caps` 覆盖位（默认从内置目录推导，可手工覆盖） | `config/schemas.py` | §6.3 |

> **D4 是本次实测最"便宜"的收益**：一个零映射的配置能让全部模型静默不可用，而现状**启动时没有任何提示**。

---

## 八、未验证 / 风险（诚实标注）

| # | 未验证项 | 影响 | 怎么解 |
|---|---|---|---|
| U1 | **CLI 工具调用轮次未完整跑完**（网关侧 2 轮 success，但 CLI 进程未退出） | 不影响"网关侧链路正确"的结论，但"CLI 端到端完整闭环"未证实 | 换一个不涉及子进程的 tool（如 Read）重试 |
| U2 | Trae / Cursor / Cherry Studio 的接入机制 | 决定 `mgw setup` 能覆盖几家 | 同法实测（用 `~/.trae-cn`、`~/.cursor` 等已存在的目录） |
| U3 | 网关 `/v1/models` 加非标准字段后，是否被某些工具**严格模式**拒绝 | 影响 D1 的实现方式（可能需开关） | 拿 2~3 个工具实测 |
| U4 | `caps.thinkingLevelMap` 各家的**具体厂商值**（如商汤写 `thinking.type` 还是 `reasoning_effort`） | 影响方言表内容 | 拿 1 家做探测（= `07` 门④） |
| U5 | GUI（非 CLI）走哪条模型路径 | 影响"文件下发"的目标文件选择 | 在 GUI 里加一个自定义模型，观察哪个文件变化 |
| U6 | 网关 `attempt_timeout_seconds: 60` 对**长思考模型 + 大上下文**是否够 | 20606 input tokens 时实测 4.2s，充裕；但 `max_tokens` 拉满时未知 | 压测 |
| **U7** | **🔴 `~/.workbuddy/models.json` 的原始内容被清空，改动方未定位** | 原 405 字节（含 1 条 `deepseek-flash-free` 自定义模型）在实测过程中变成 `[]`。CLI 有 `reconcileUserModelsJsonToPolicy`，但当时 CLI 指向的是 `.workbuddy-ai`，且 `WorkBuddy.app` 未运行（`pgrep` 确认只有 WorkBuddy AI 在跑）→ **改动方未能定位** | 原内容已存 `/tmp/mg-wb-models-original.json`，**需用户确认是否恢复**；后续做 `mgw setup` 前必须先把"目标文件已存在"的情况处理掉（备份 or 合并），不能覆盖 |

**本次实测留下的环境痕迹（可清理）**：

| 路径 | 说明 | 是否建议保留 |
|---|---|---|
| `~/.workbuddy/models.json` | **当前 = 网关接入配置**（CLI 对象格式）。⚠️ 原内容（1 条 `deepseek-flash-free`）已被清空，原件存 `/tmp/mg-wb-models-original.json` | **需你决定**：保留 = WorkBuddy 已接网关；如需恢复原模型，用原件 |
| ~~`~/.workbuddy-ai/models.json`~~ | 初稿误写，**已删除** ✅ | 无需处理 |
| `/tmp/mg-config-backup-20260924-224730.yaml` | 网关配置改动前备份 | 建议保留至确认无误 |
| `data/config.yaml` | 已补 7 条模型映射（走管理端 API，非手改） | **保留**（否则模型不可用） |
| `/tmp/mg-cli-test/` | 隔离测试目录 | 可删 |

---

## 九、探测可行性实测（`07` 门④ / B2）——已验证，但**原设计有缺陷，已修正**

> **背景**：`06` §6.2 提出"**探测优先**替代手填"（把 ZCode 那 78 处手写的"不支持"变成 0 处），
> 但这**完全依赖一个未验证的假设**：「上游会对不支持的档位返回 400，且错误文案可解析」。
> `07` 把它列为 **B2 阻塞项**。本节是 2026-09-24 的实测结果。

### 9.1 假设验证：**成立** ✅

对 `token.sensenova.cn/v1`（商汤 TokenPlan）发一个**非法值**，上游返回：

```
HTTP 400
field ReasoningEffort invalid, should be one of: low, medium, high, xhigh, none
```

→ **400 ✅ + 错误文案直接列出全部合法值 ✅**。正则 `should be one of:\s*(...)` 即可提取。
**一次请求拿到完整值域，假设成立。**

### 9.2 实测拿到的各家值域（**每个模型都不一样**）

| 模型 | 上游回显的合法值 | 档位数 |
|---|---|---|
| `deepseek-v4-flash` | `low, medium, high, xhigh, none` | 5 |
| `sensenova-6.8-flash-lite` | `low, medium, high, xhigh, none` | 5 |
| `glm-5.2` | `none, minimal, low, medium, high, xhigh, max` | 7 |
| `kimi-k3` | `none, minimal, low, medium, high, xhigh, max` | 7 |
| **`deepseek-v4-pro`** | `none, minimal, low, medium, high, xhigh, max, **`ultra`**` | **8** |

> **🔴 重要发现：`deepseek-v4-pro` 有 `ultra` 档，超出了 7 档规范序**（`off/minimal/low/medium/high/xhigh/max`）。
> → **规范序必须是"开放可扩展"的**：遇到规范外档位**不能报错**，应原样透传（它是厂商的真实能力）。
> 这一条要写进 PRD。

### 9.3 🔴 但原探测设计有缺陷：**「返回 200」不等于「参数生效」**

原设计（`06` §6.2）写的是：

> 「**二分探测**：对规范序各档各发一次 `max_tokens=1` 的最小请求，看 **200 / 400 / 400-文案**」

**实测证明这不够。** 同一模型同一问题，不同写法的结果：

| # | 写法 | HTTP | `reasoning_tokens` | 判定 |
|---|---|---|---|---|
| ① | **不传任何推理参数（基线）** | 200 | **43** | 默认开推理 |
| ③ | `reasoning_effort=none` | 200 | **0** | ✅ **真写入位**（明确关闭） |
| ④ | `reasoning.effort=high` | 200 | 23 | ≈ 基线 → 存疑 |
| ⑤ | `reasoning.effort=bogus`（**非法值**） | **200** | 22 | ❌ **被忽略**（非法值也通过） |
| ⑥ | `thinking.type=enabled` | 200 | 38 | ❌ **被忽略**（≈ 基线，无差别） |
| ⑦ | `reasoning_effort=low` | 200 | 61 | 有变化，但方向反了（见下） |

**两个结论**：

1. **`reasoning.effort`（对象式）与 `thinking.type` 在这个端点上是"假方言"** —— 上游**不认识这些字段，直接忽略**，
   所以**连非法值都返回 200**。若只做 200/400 二分，会被误判为"支持的写法"。
2. **`reasoning_effort`（扁平式）是真写入位** —— `none` 把 `reasoning_tokens` 从 43 打到 **0**，是明确开关信号。

> **⚠️ 另一个实测观察：推理 token 数本身波动很大**（同一模型同一问题，基线跑出 22 / 23 / 38 / 43 / 61）。
> → **生效判定不能看绝对值**，只能看**极端开关差异**（如 `none` → 0）或**多次取平均**。

### 9.4 修正后的探测设计（**三步，代替原来的二分**）

| 步 | 做什么 | 判据 | 产出 |
|---|---|---|---|
| **S1 · 粗筛** | 对候选写入位发一个**非法值** | 400 + 文案含 `should be one of:` → 该写入位**被校验**；200 → **被忽略**（排除） | 真写入位候选 + 值域 |
| **S2 · 生效验证**（**新增，必需**） | 对 S1 选出的写入位发**极值**（如 `none`/`off`），与**不传参数的基线**对比 `usage.completion_tokens_details.reasoning_tokens` | 与基线**有显著差异**（尤其是归零）→ 确认生效；≈ 基线 → **判为假方言，丢弃** | 确认生效的写入位 |
| **S3 · 定档** | 在 S2 确认的写入位上，逐档取合法值 | 200 即收录 | `thinkingLevelMap` |

> **S1 与 S2 缺一不可**：S1 拿值域（快，1 次请求），S2 排除"被忽略的字段"（否则会配出一张看起来对、实际无效的方言表）。
>
> **对照本次实测的教训**：我在 `06` §5.4 里**手填**的 `sensenova-thinking-effort` 方言写的是
> `thinking.type: {off: disabled, ...}` + `reasoning_effort`，而**实测的真方言是 `reasoning_effort` + 值域 `low/medium/high/xhigh/none`**
> —— `thinking.type` 那一整条是**错的、且会被上游忽略**。**这正是"探测替代手填"价值的最直接证据。**

### 9.5 探测的代价（诚实标注）

| 项 | 实测 |
|---|---|
| 单次探测耗时 | 1~2 秒（但**触发限流频繁**：本次 20 余次请求中约 1/3 返回 429 `rpm/tpm exhausted`） |
| 成本 | `max_tokens=1` 时极低 |
| **风险** | **会消耗额度和触发限流**。→ 探测必须：① 串行 + 间隔；② 429 退避重试；③ **结果落盘缓存**，不每次启动都探 |

---

## 十、附：账号存储方案评估（回应你的第 2 点）

> **你的原话**：「账号基本信息我认为可以采用**一张公共表**，但是**每个产品特有的凭证类 / 特有的一些是不是分开处理会更好一些**，因为每个产品调用模型使用的参数标识信息可能不一致、数据更新调整规则可能也不一致。具体你来评估。」
>
> **评估结论：你的判断成立，建议采纳。** 理由不是"听起来合理"，而是**你让我调研的那个 DSH 插件，实测就是这么做且踩过具体的坑**。

### 9.1 DSH 的实际做法（`02` §3.1 / §2.4 原文取证）

```
┌──────────── ctx.settings (namespace 'jet-hub') ────────────┐
│  accounts: ProviderAccountEntry[]     ← 公共表（非密）      │
│    { id, provider, nickname, enabled, credentialRef,       │
│      createdAt, expiresAt, refreshable, modelRateLimits,   │
│      traeCheckinDeviceGeneration }                         │
│  disabledModels: Record<provider, Record<modelId, true>>   │
└────────────────────────────────────────────────────────────┘
                    │ credentialRef（字符串指针，非外键约束）
                    ▼
┌──────────── ctx.credentials（按产品分存）─────────────────┐
│  'CODEARTS_ACCOUNT_A1B2C3D4' → '{"access_key_id":"...",   │
│                                  "refresh_token":"..."}'   │
│  'BUDDY_ACCOUNT_XXXXXXXX'    → '{"access_token":"...",    │
│                                  "refresh_token":"..."}'   │
└────────────────────────────────────────────────────────────┘
```

**对照你的判断**：

| 你的判断 | DSH 的实际做法 | 是否一致 |
|---|---|---|
| 账号基本信息用**一张公共表** | `accounts[]` 是**一个全局数组**（`account-pool.ts:352-356`），**靠 `provider` 字段区分**，不是每产品一个数组 | ✅ 一致 |
| 公共表里放"每个产品都有"的 | 放的是 `id` / `nickname` / `enabled` / `expiresAt` / `refreshable` —— **跨产品语义完全一致的字段** | ✅ 一致 |
| **产品特有的凭证分开处理** | 凭据本体存 `ctx.credentials`，**按 `credentialRef` 独立寻址**，命名 `{PROVIDER}_ACCOUNT_{8位HEX}` | ✅ 一致 |
| 理由："每个产品的参数标识可能不一致" | **实测确认**：六种产品的凭据字段**完全不同** —— Buddy 用 `access_token`/`refresh_token`；Qoder 用 `security_oauth_token`/`uid`/`machine_id`；Trae 用 `access_token`/`uid`/`machine_id`/`device_id`/`api_host`；CodeArts 用 `access_key_id`/`secret_access_key`/`security_token`/`domain_id`/`dpop_private_key_jwk` | ✅ **你的判断被实测证实** |
| 理由："数据更新调整规则可能不一致" | **实测确认**：续期规则也不同 —— TRAE 的续期是 ExchangeToken **轮换**（旧 `refresh_token` 即刻失效，`trae-auth.ts:10-11`）；CodeArts 是 ISO 串 + `security_token`；过期时间格式 DSH 特意统一成"毫秒时间戳字符串"来复用同一套解析逻辑（`trae.ts:97-99`） | ✅ 一致 |

### 9.2 DSH 用这套结构踩过的 3 个坑（**必须抄走**）

| # | 坑 | DSH 的应对 | 我们要怎么做 |
|---|---|---|---|
| **K1** | `settings.replace()` 是**整体替换** —— 只写账号会把模型黑名单冲掉 | 每次写账号**必须连同黑名单一起写回**（`account-pool.ts:187-189` 与 `:250-251` 两处对称注释） | 我们的配置写盘要**做整份快照替换 + 读-改-写**，不能"只改一个字段就落盘" |
| **K2** | 读源用了**滞后的 settings 快照** → 并发更新互相覆盖（表现：多个账号限流后，配置里一条限流记录都没有） | 改用**进程内权威副本**做读源（`account-pool.ts:128-134` 注释自认了这个坑） | 账号/限流状态的读源 = 内存权威副本，**不直接读文件快照** |
| **K3** | 把**运行时状态混进凭据本体**（`CodeArtsCredential.model_rate_limits`），续期时必须手动搬运 | DSH 自己标注这是"坏味道"（`types.ts:347-348`） | **运行时状态（限流/冷却/用量）一律不进凭据**，也不进公共表的账号条目 —— 单独一张表 |

### 9.3 建议的落地形态（三张表）

```
① products          产品注册表      { id, name, kind, auth_mode, endpoint_hints, config_schema }
② accounts          公共账号表      { id, product, nickname, enabled, expires_at, refreshable, credential_ref }
                                    ← 只放"跨产品语义一致"的字段
③ credentials       凭据表（按产品）  key = credential_ref
                                    value = 该产品特有的 JSON（字段由 ① 的 config_schema 声明）
   （另）runtime_state 运行时状态表    { account_id, rate_limits, cooldown_until, last_error }
                                    ← K3：不与 ②③ 混放
```

**与现有扁平资源模型的兼容路径（分两阶段，避免一次大改）**：

| 阶段 | 动作 | 兼容性 |
|---|---|---|
| **一** | 现有 `Resource`（厂商 + 账号 + Key）**加一列 `product`**（默认空 = 旧行为） | ✅ 向后兼容，旧配置零改动 |
| **二** | 把 `Resource.api_key` 抽成 `credentials` 条目，`Resource` 只留 `credential_ref` | ⚠️ 需迁移脚本；建议加**双读期**（两种形态都能读） |

> **判断**：你的方案在**第一阶段就能带来实际收益**（同一厂商多账号不再靠"备注字符串"区分），**第二阶段才有复杂度**。建议**先做一，看实际使用再决定要不要做二**。

---

## 十一、一句话回答

> **网关能不能被真实工具用？能 —— 已经端到端跑通了。**
> **但真正的发现是：工具自己就有参数归一化引擎，网关要做的是"把声明写对"（能力位 + 档位映射表），而不是自己去翻译参数。**
> **而网关现在 8 个能力位一个都没下发 —— 数据全都有，只差最后一步暴露。**
> **账号存储：你的「公共表 + 产品特有分开」判断与 DSH 的实际做法完全一致，建议采纳（先做"加一列"这一阶段）。**
