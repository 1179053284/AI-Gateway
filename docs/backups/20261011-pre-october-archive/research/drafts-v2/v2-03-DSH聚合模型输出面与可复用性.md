# v2-03 DSH 插件（deepseek-harness-codearts）聚合模型的输出面与可复用性

> 调研范围：**仅输出面 / 对接面**（聚合后的模型资源如何被消费）。
> 多产品接入、账号池选号、凭据续期属另一同事职责，本文只在必要时引用。
> 参考项目路径：`/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts`（只读）。
> 事实基准：`src/`（源码）。`lib/` 与 `node_modules/` 在本机**均不存在**（见「未验证清单」）。
> 行号均为实际读到的 `src/` 行号。

---

## 0. 结论先行

### A 问：聚合的模型资源怎么提供给 DeepSeek harness 内部对接使用？

**答案：插件把自己实现成一个 DSH 宿主进程内的 `LlmAdapter` 子类实例，通过 `ctx.llm.registerAdapter([providerId], adapter)` 注册进宿主的 LLM 运行时；六个 provider 各注册一个实例，宿主用「(provider, modelId) 二元组」寻址，模型响应以 `AsyncIterable<StreamChunk>` 的进程内异步生成器逐块交回宿主。全程没有任何网络端口、没有任何 OpenAI 兼容 HTTP 端点。**

三层精确机制：

1. **注册点**：`ctx.llm.registerConfigurableProviders([...])` + `ctx.llm.registerAdapter([provider], adapter)`（`src/llm-adapter.ts:1454-1458`、`src/buddy-adapter.ts:1455-1459`、`src/qoder-adapter.ts:478-482`、`src/lobsterai-adapter.ts:1322-1326`、`src/trae-adapter.ts:1387-1391`）。
2. **调用路径**：宿主 `LlmRuntime` 每轮请求先 `registration.adapter.prepareCall(provider, model, signal)` 拿 `{ model, stream }`，再对 `stream(options)` 做 `for await`（`src/buddy-adapter.ts:861-866` 的 shim 注释 + `src/llm-adapter.ts:824-833` 的实现）。
3. **数据结构**：目录侧 `listModels()` 返回 `{provider, id, name, inputModalities}`；解析侧 `resolveModel()` 返回 `LlmResolvedModelInfo`（含 `context.contextWindow` / `defaultMaxTokens` / `reasoning.efforts`）；响应侧 `stream()` 产出 `StreamChunk` 判别联合（`block-start` / `text-delta` / `reasoning-delta` / `tool-call-delta` / `block-end` / `usage` / `finish`）。

**「聚合」实际发生在宿主的 catalog 层，不在插件里**：插件只按 provider 贡献分组，宿主的会话控制器 `buildModelCatalog` 把各 provider 的 `listModels()` 汇总成统一模型目录（`src/account-pool.ts:717-722`、`src/jet-hub-rpc.ts:1193` 的注释 + `src/llm-adapter.ts:786-789` 的实现行为）。

### B 问：这种对接方式能否提供给别的工具使用？

**分情况，结论是「同宿主可复用、跨进程不可复用」。**

| 消费方 | 能否复用 | 依据 |
|---|---|---|
| **同一个 DSH 宿主里的另一个插件** | ✅ 可复用（走标准契约） | 任何插件都能 `ctx.llm.listModels(provider)`；本插件自己的 Jet Hub 就是这么读的（`src/jet-hub-rpc.ts:1204`）。另有 `ctx.provide('accountPool', pool)`（`src/index.ts:429`）与六个 cordis Service（`codeartsAuth` / `buddyAuth` / `workbuddyAuth` / `lobsteraiAuth` / `qoderAuth` / `traeAuth`，见 `src/service.ts:82`、`src/buddy-auth.ts:126`）可被同宿主其它插件 `ctx.get` 到。 |
| **任意第三方程序（Trae / Cursor / Cherry Studio）** | ❌ 不可复用 | 输出面是 **TS 类实例的进程内方法调用**，不是协议端点。第三方无法"调用"一个 JS 对象；全仓库无任何 `createServer`/`listen` 对外提供 chat 能力（唯一的 `node:http` 服务器是三个 OAuth 本地回调，绑 `127.0.0.1`：`src/login.ts:219,348`、`src/lobsterai-oauth.ts:348`、`src/trae-oauth.ts:495`）。 |
| **管理面 `/api/jet-hub`** | ⚠️ 形态上是 HTTP，但**仍不可给第三方用** | 它是宿主内嵌 RPC 通道，不是独立监听端口，只在 Web profile 存在（`src/index.ts:26-32`、`src/jet-hub-rpc.ts:499-501,521-525`）；信封格式是 DSH 专有（`src/jet-hub-rpc.ts:576-585`）；**全文件无任何鉴权代码**；且它**不提供任何 chat/completions 能力**，只有账号 / 积分 / 模型开关管理（方法清单见 §5）。 |

**要复用必须补的东西**：① 一个独立常驻 HTTP 服务进程（现在完全没有）；② OpenAI 兼容路由层 `/v1/chat/completions`（含流式与非流式）与 `/v1/models`；③ 从 `StreamChunk` 到 OpenAI SSE chunk 的**反向编码器**（现在只有正向：OpenAI SSE → `StreamChunk`，反向不存在）；④ 模型 ID 的扁平化命名空间策略（DSH 用 `provider` 字段分组，OpenAI 只有单一 `model` 字符串）；⑤ 鉴权（现在为 0）；⑥ 凭据与宿主 `ctx.credentials` 解耦。

---

## 1. 宿主契约与注册机制

### 1.1 插件如何向宿主注册

插件是一个标准 cordis 插件，导出三件套：

```ts
export const name = 'codearts-auth'                                  // src/index.ts:25
export const inject = ['credentials', 'commands', 'llm']             // src/index.ts:33
export function apply(ctx: Context): void { ... }                    // src/index.ts:121
```

`apply` 内做四类注册（`src/index.ts:121-430`）：

| 注册对象 | 代码位置 | 宿主侧名字 |
|---|---|---|
| 6 个 LLM provider 路由 + 适配器实例 | `src/index.ts:152,182,211,239,286,329` | `ctx.llm` 内 `codearts` / `buddy` / `workbuddy` / `lobsterai` / `qoder` / `trae` |
| 6 个 provider 的 settings namespace | `src/index.ts:129-131` | `llm-buddy` / `llm-workbuddy` / `llm-codearts` / `llm-lobsterai` / `llm-qoder` / `llm-trae` |
| 6 个 cordis Service 实例 | `src/service.ts:82`、`src/buddy-auth.ts:126`、`src/index.ts:210,238,285,328` | `codeartsAuth` / `buddyAuth` / `workbuddyAuth` / `lobsteraiAuth` / `qoderAuth` / `traeAuth` |
| Jet Hub 管理面 RPC 端点 | `src/index.ts:428` → `src/jet-hub-rpc.ts:556` | HTTP `POST /api/jet-hub` |
| 账号池（自定义服务名） | `src/index.ts:429` `ctx.provide('accountPool', pool)` | `accountPool` |

适配器注册函数体（以 codearts 为例，`src/llm-adapter.ts:1452-1462`）：

```ts
export function registerCodeArtsLlm(ctx: Context, options: CodeArtsAdapterOptions): CodeArtsAdapter {
  ctx.llm.registerConfigurableProviders([
    { provider: PROVIDER, displayName: 'CodeArts Agent', settingsNs: 'llm-codearts', settingsPath: [] },
  ])
  const adapter = new CodeArtsAdapter(options)
  ctx.llm.registerAdapter([PROVIDER], adapter)
  return adapter
}
```

Buddy 系同款但由产品配置驱动路由名（`src/buddy-adapter.ts:1453-1463`）：

```ts
ctx.llm.registerConfigurableProviders([
  { provider: product.id, displayName: product.displayName, settingsNs: `llm-${product.id}`, settingsPath: [] },
])
ctx.llm.registerAdapter([product.id], adapter)
```

> **关键**：`registerAdapter` 的返回值被**显式保留为局部变量**并向下传递，因为 `ctx.llm` **不透传自定义方法** —— 适配器额外提供的 `listAllModels()` 拿不到（`src/llm-adapter.ts:1459-1460`、`src/index.ts:415-416` 注释）。管理面需要它时只能由 `registerJetHubRpc` 的第 9 个参数手工注入（`src/index.ts:417-428`）。

### 1.2 `LlmAdapter` 契约的方法签名

⚠️ **`@deepseek-ai/dsh-llm` 的类型声明未能读到**（无 `node_modules`、无 `lib/`）。以下签名是**从 5 个适配器子类的实现**反推出的实际覆写集合（推断项已标注）。`LlmAdapter` 基类**可能还有未被子类覆写的方法，未验证**。

```
// 已在本仓库内被覆写的方法（5 个适配器一致）
providerInfo(provider: string): LlmProviderInfo
    // src/llm-adapter.ts:746 / buddy-adapter.ts:582 / lobsterai-adapter.ts:624
    // / qoder-adapter.ts:126 / trae-adapter.ts:509
    // 返回 { id, name }；DSH 强制校验 info.id === provider

listModels(provider: string): Promise<readonly LlmModelInfo[]>
    // src/llm-adapter.ts:785 / buddy-adapter.ts:773 / lobsterai-adapter.ts:739
    // / qoder-adapter.ts:162 / trae-adapter.ts:687
    // 元素形如 { provider, id, name, inputModalities: readonly ('text'|'image')[] }

resolveModel(provider: string, model: string, signal?: AbortSignal): Promise<LlmResolvedModelInfo>
    // src/llm-adapter.ts:814 / buddy-adapter.ts:809 / lobsterai-adapter.ts:763
    // / qoder-adapter.ts:184 / trae-adapter.ts:726
    // 返回 { provider, id, name, inputModalities, context?: { contextWindow },
    //        defaultMaxTokens?, reasoning?: { efforts: {id,name}[], defaultEffort? } }

prepareCall(provider: string, model: string, signal?: AbortSignal):
    Promise<{ model: LlmResolvedModelInfo; stream: (options: GenerateOptions) => AsyncIterable<StreamChunk> }>
    // src/llm-adapter.ts:824-833；注释明确这是「兼容 0.1.1-rc.2」的 shim
    // （src/buddy-adapter.ts:861-866：新版 LlmRuntime.prepareCall() 会调用
    //  registration.adapter.prepareCall(...)，基类 0.1.0-rc.6 尚无此方法）

stream(options: GenerateOptions): AsyncIterable<StreamChunk>
    // src/llm-adapter.ts:835  async *stream(options: GenerateOptions): AsyncIterable<StreamChunk>

// 本插件自定义、非 LlmAdapter 契约（仅通过实例引用传播）
listAllModels(): readonly { id: string; name: string }[]
    // src/llm-adapter.ts:776 等 5 处；语义 = 不套用户黑名单的全量目录
```

`GenerateOptions` 被实际读取的字段（从 `src/llm-adapter.ts:835-918` 的消费点反推）：`messages`、`system`、`tools[{name,description,parameters}]`、`model`、`maxTokens`、`reasoningEffort`、`signal`。`LlmModelInfo` 被写入的字段：`provider`、`id`、`name`、`inputModalities`（`src/llm-adapter.ts:811`）。

### 1.3 宿主在什么时机调用适配器

从代码注释可还原的调用时机（注释是一手材料，非猜测，因为它描述的是宿主行为）：

| 时机 | 宿主动作 | 证据 |
|---|---|---|
| 会话启动 / 模型选择器刷新 | 汇总所有 provider 的 `listModels()` 构建目录 | `src/account-pool.ts:717-722`（`buildModelCatalog` 显式 `.filter(group => group.models.length > 0)`）、`src/jet-hub-rpc.ts:1193`（"会话控制器的 buildModelCatalog"） |
| 每轮请求开始 | `LlmRuntime.prepareCall()` → `registration.adapter.prepareCall(...)` | `src/buddy-adapter.ts:861-866`、`src/qoder-adapter.ts:199-203`、`src/lobsterai-adapter.ts:785-789`（三处独立注释同述） |
| 参数补全 | `resolveCallWithInfo` 在调用方未给 `maxTokens` 时用适配器声明的 `defaultMaxTokens` 兜底 | `src/buddy-adapter.ts:826-839` |
| 值校验 | `LlmRuntime.resolveModelInfoFor` 对 `defaultMaxTokens` 做硬校验（非安全整数或 ≤0 直接抛） | `src/buddy-adapter.ts:1434-1436` |
| 图片投影 | `LlmRuntime` 按适配器播报的 `inputModalities` 决定是否把图片投影成文本占位符 | `src/qoder-adapter.ts:219-220`、`src/lobsterai-adapter.ts:821` |
| 请求执行 | 对 `stream(options)` 做 `for await` 消费 | `src/llm-adapter.ts:824-833` 返回 `stream` 闭包；测试 `tests/unit/llm-adapter.spec.ts:141` 直接 `for await (const chunk of adapter.stream(...))` |

### 1.4 流式输出契约的形态

**结论：是进程内异步生成器（`AsyncIterable<StreamChunk>`），不是网络流。**

```ts
async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {   // src/llm-adapter.ts:835
  ...
  yield { type: 'text-delta', index: block.index, text }                // :1115
  yield { type: 'reasoning-delta', index: block.index, text: reasoning } // :1125
  yield { type: 'tool-call-delta', index, id, name, argumentsDelta }     // :1144-1150
  yield { type: 'block-end', index, block: { type: 'tool-call', id, name, arguments } } // :1367-1379
  yield { type: 'finish', reason }                                       // :1398
}
```

**`StreamChunk` 判别联合的完整成员**（从 `src/llm-adapter.ts:1112-1398` 与 `src/openai-compat.ts:443-553` 的产出点穷举）：

| `type` | 字段 | 语义 |
|---|---|---|
| `block-start` | `index`, `blockType: 'text' \| 'reasoning' \| 'tool-call'` | 新块开始 |
| `text-delta` | `index`, `text` | 正文增量 |
| `reasoning-delta` | `index`, `text` | 思考增量 |
| `tool-call-delta` | `index`, `id`（`ToolCallId` 品牌类型）, `name?`, `argumentsDelta` | 工具调用参数增量 |
| `block-end` | `index`, `block: {type:'text',text} \| {type:'reasoning',text} \| {type:'tool-call',id,name,arguments}` | 块收尾（含**已归一的完整 arguments**） |
| `usage` | `usage: { inputTokens, outputTokens, cacheReadTokens?, reasoningTokens? }` | 用量（仅 `openai-compat.ts:494-504` 产出） |
| `finish` | `reason: {kind:'stop'\|'tool-calls'\|'max-tokens'}` | 结束原因 |

**网络只在"上游方向"存在**：`stream()` 内部用 `fetch` 打各厂商 API，读 SSE；产出给宿主的那一侧完全是内存对象。证据链：`src/llm-adapter.ts:1153` `const reader = response.body.getReader()`（读上游）→ 解析 → `yield`（给宿主）。

**错误也是契约的一部分**：统一抛 `LlmError(message, code)`，code 取值有 `MISSING_CREDENTIAL`（`src/llm-adapter.ts:842`）、`TRANSPORT`（`:1183`）、`TIMEOUT`（`src/sse.ts:39`）、`AUTH` / `RATE_LIMIT` / `INVALID_REQUEST` / `SERVER`（`src/openai-compat.ts:257-263`）、`UNSUPPORTED_CONTENT`（`src/qoder-adapter.ts:230`）、`QUOTA_EXCEEDED`（`src/trae-adapter.ts:954`）。可重试性由 code 表达（`TIMEOUT` / `TRANSPORT` 可重试）。

---

## 2. 输出形态判定：进程内 vs 网络

### 2.1 判定表

| 面 | 形态 | 证据 |
|---|---|---|
| 模型目录（`listModels` / `resolveModel`） | 进程内函数调用 | `src/llm-adapter.ts:785,814` |
| 模型响应（`stream`） | 进程内 `AsyncIterable` | `src/llm-adapter.ts:835` |
| 管理面（Jet Hub） | **HTTP**，但由宿主 HTTP 服务器承载的内嵌 RPC 通道 | `src/jet-hub-rpc.ts:556-601` |
| 登录回调 | HTTP，`127.0.0.1` 临时端口，仅登录期存在 | `src/login.ts:219,348`、`src/lobsterai-oauth.ts:348`、`src/trae-oauth.ts:495` |
| OpenAI 兼容对外端点 | **不存在** | 全仓 grep 无 `/v1/chat/completions` 路由注册；`src/qoder-product.ts:34` 的同名串是**上游**路径常量 |

### 2.2 Jet Hub 是什么

**是 HTTP 端点，但不是独立进程的端口，而是注册进 DSH 宿主 HTTP 服务器的路由。**

```ts
export const JET_HUB_API_PATH = '/api/jet-hub'      // src/jet-hub-rpc.ts:95
const JET_HUB_ENDPOINT = 'jet-hub'                  // src/jet-hub-rpc.ts:97

export function registerJetHubRpc(...): void {
  ctx.inject(['connection'], (connectionCtx) => {   // src/jet-hub-rpc.ts:521
    registerJetHubEndpoints(connectionCtx as Context, ...)
  })
}

// 内部：
const connection = (ctx as any).connection ?? ctx.get('connection')   // :550
if (!connection || typeof connection.fetch?.register !== 'function') { // :551
  ctx.logger.warn('[jet-hub] connection.fetch not available, RPC endpoints not registered')
  return
}
connection.fetch.register({                                          // :556
  path: JET_HUB_API_PATH,
  methods: ['POST'],
  requestBody: 'buffered' as const,
  async fetch(request: Request): Promise<Response> { ... }
})
```

判定依据：

1. **没有 `listen` / `createServer`**：`connection.fetch.register` 是把 handler 交给宿主（`connection` 服务）挂载，端口由宿主决定。文件头注释自述「使用 DSH 的 `connection.fetch.register()` 模式注册 HTTP API 端点，与 dsh-im 的 registerManagementRpc 一致」（`src/jet-hub-rpc.ts:4-5`）。
2. **只在 Web profile 存在**：`connection` 服务由 Web bundle（`dsh-client-connection`）提供，headless / CLI profile 没有；因此用**惰性注入**而非静态 `inject`，否则整个 profile 启动失败（`src/index.ts:26-32`、`src/jet-hub-rpc.ts:499-501`）。
3. **协议是 DSH 专有 RPC 信封**，不是 REST：
   ```ts
   if (message.type !== 'client-request' || typeof message.rpcId !== 'string'
       || message.method !== JET_HUB_ENDPOINT
       || !call || typeof call.method !== 'string'
       || !Object.prototype.hasOwnProperty.call(call, 'payload')) {
     return reply(rpcId, { ok:false, error:{ code:'gateway/bad-request', ... } })
   }
   ```
   （`src/jet-hub-rpc.ts:576-585`）；响应体 `{ type:'server-response', rpcId, result }`（`src/jet-hub-rpc.ts:1285-1290`）。
4. **客户端侧对应调用**：`connection.rpc.call('/api', 'jet-hub', { method, payload }, signal)`（`plugin-src/management-rpc.mjs:26`）。

### 2.3 鉴权情况

**未发现任何鉴权。** 对 `src/jet-hub-rpc.ts` 全文 grep `authorization|bearer|api[_-]?key|x-dsh|session`，仅命中两处**注释**（`:630` 讲 WorkBuddy 登录 URL 参数、`:1136` 讲上游余额接口的 Bearer），**无一处是入站鉴权校验**。端点只校验 HTTP 方法（405）、`Content-Type: application/json`（415）、body 可解析（400）与 RPC 信封结构（`gateway/bad-request`）。→ 该端点的安全性完全依赖 DSH 宿主自身的会话/来源限制，**宿主侧是否加鉴权未验证**（本仓库内无证据）。

---

## 3. 聚合模型目录与命名空间

### 3.1 模型是怎么被枚举出来的

**三条路径并存，优先级 = 远端探测 → 磁盘缓存 → 产品静态兜底表**。各 provider 的实现策略不同：

| provider | 枚举方式 | 证据 |
|---|---|---|
| `codearts` | 远端探测两个端点 + 磁盘缓存 + 静态表兜底 | `src/models.ts:120-165`（`fetchCodeArtsRemoteModels`）拉 `opengw.developer.huaweicloud.com/api/v1/gateway/config`（`:8`）与 `snap-access.../v1/model/builtin`（`:16`）；缓存 `~/.cache/deveco/codearts_models.json`（`:19,167-204`）；静态 `DEFAULT_MODELS`（`src/llm-adapter.ts:24-29`） |
| `buddy` / `workbuddy` | 远端 `/v3/config` + 产品静态兜底表 | `src/product.ts:168-254`（`CODEBUDDY_FALLBACK_MODELS`）、`:283-355`（`WORKBUDDY_FALLBACK_MODELS`）；`src/buddy-adapter.ts:801-807`（`staticFallbackModels`） |
| `lobsterai` | 远端 + 兜底表 | `src/lobsterai-adapter.ts:635`（`ensureRemoteModels`）、`:719-733`（`staticFallbackModels`） |
| `trae` | 远端 + 兜底表 + 通道路由 | `src/trae-adapter.ts:515`（`ensureRemoteModels`）、`:656-676`（`staticFallbackModels`）、`:557-560`（`channelFor`） |
| `qoder` | **恒用本地兜底表，不发任何网络请求** | `src/qoder-adapter.ts:144-150` 注释：「模型列表端点需要 WASM 签名（`qoder_auth_wasm`），本插件不实现，故恒用产品兜底表」；`:158-160` `listAllModels()` 直接读 `this.product.fallbackModels` |

远端目录的刷新节奏：`MODEL_REFRESH_INTERVAL_MS = 2 * 3_600_000`（2 小时，`src/models.ts:25`），由 `CodeArtsAuth.refreshModels(pool)` 驱动（`src/service.ts:281`，在 `src/index.ts:174` 作为 `fetchRemoteModels` 注入）。

**懒加载**：`ensureRemoteModels()` 首次 `listModels` **或** `resolveModel` 时触发（`src/llm-adapter.ts:758-766`），注释明确「`resolveModel` 可能先于 `listModels` 被调用（如直接进入会话）」。

### 3.2 模型 ID 命名空间怎么设计

**核心结论：不做 ID 前缀化，而是用「(provider, id) 二元组」做命名空间。**

- `LlmModelInfo` 同时携带 `provider` 与 `id`：`return listed.map((m) => ({ provider: PROVIDER, id: m.id, name: m.name, inputModalities: ['text'] }))`（`src/llm-adapter.ts:811`）。
- 寻址时两段都要：`resolveModel(provider, model, signal)`（`src/llm-adapter.ts:814`）、`prepareCall(provider, model, signal)`（`:824`）。
- 宿主据此把模型目录**按 provider 分组**展示（`buildModelCatalog` 的 `group.models`，`src/account-pool.ts:717-722`）。
- 每个 provider 有稳定的路由名与展示名：`{ provider, displayName, settingsNs }`（`src/llm-adapter.ts:1455`、`src/buddy-adapter.ts:1456`）；qoder 的 `QODER.id`、trae 的 `TRAE.id`、lobsterai 的 `LOBSTERAI.id` 均来自各自 product 配置（`src/qoder-product.ts:127`、`src/trae-product.ts:52`、`src/lobsterai-product.ts:137`），且代码刻意**不写死字面量**以免改名后静默查不到账号（`src/index.ts:244-245,291-292`）。

**同一 provider 内部的同名模型消歧**（多产品同名问题实际出现在 provider 内而非 provider 间）：远端会给不同 id 配同一个 `name`（实测 `deepseek-v4.1-flash` 与 `deepseek-v4.1-flash-sg` 都叫 "Deepseek-V4.1-Flash"）。解法是把消歧标记拼进**展示名**（`name`），而不是改 id：

```ts
function displayNameFor(model, all) { return `${model.name} · ${displaySuffix(model, all)}` }   // src/buddy-adapter.ts:1382-1385
function variantLabelFor(model, all) {                                                          // :1410-1416
  const group = all.filter(c => c.name === model.name)
  if (group.length <= 1) return ''
  const prefix = commonPrefix(group.map(c => c.id))     // 公共前缀切分，非硬编码 -sg
  return model.id.slice(prefix.length).replace(/^-+/, '').toUpperCase()
}
```

同一套机制还承载**计费倍率**展示（`displaySuffix` 拼 `x0.03` / `x0.17→x0.50`，`src/buddy-adapter.ts:1387-1397`）。设计要点被明确写死：**必须进 `name` 而非 `description`**，因为模型切换菜单只渲染 `name`（`src/buddy-adapter.ts:1371-1374`）；且 `name` **纯展示**，选择与持久化只用 `id`（`:1376-1377`）。qoder 同款（`src/qoder-adapter.ts:177-179`）。

**TRAE 的额外一层命名空间**：模型必须发到「列出它的通道」，通道名来自远端目录的 `function` 字段（`src/trae-adapter.ts:557-560`），发错通道上游返回 `code=4001 param is invalid`。这是「同一 provider 内 model → 路由」的第二级映射。

### 3.3 `resolveModel` 如何解析模型名 → 产品 + 账号 + 上游模型 ID

**注意：`resolveModel` 只解析「模型元数据」，不解析账号。** 账号解析发生在 `stream()` 内部，且是**运行时选号**而非静态绑定。

三段链路：

**(1) resolveModel：model id → 元数据**（三级查找，`src/buddy-adapter.ts:809-857`）

```ts
const contextWindow = this.remoteContextWindows.get(model)
  ?? this.productFallbackContextWindows.get(model)
  ?? CONTEXT_WINDOWS.get(model)                       // :813-815  远端 → 产品兜底 → 通用静态
const resolved = { provider, id: model, name: ..., inputModalities: this.inputModalitiesFor(model) }
if (contextWindow !== undefined) resolved.context = { contextWindow }
const maxOutputTokens = positiveMaxTokens(remoteMeta.get(model)?.maxOutputTokens ?? productFallbackMeta.get(model)?.maxOutputTokens)
if (maxOutputTokens !== undefined) resolved.defaultMaxTokens = maxOutputTokens   // :836-839
resolved.reasoning = { efforts: [...], defaultEffort? }                          // :843-856
```

codearts 版本更简（只有 `CONTEXT_WINDOWS` 一张表，`src/llm-adapter.ts:814-822`）；qoder 版本纯本地兜底表（`src/qoder-adapter.ts:184-196`）。**未知模型一律不编造 `context`**（`src/qoder-adapter.ts:192-194` 注释："未知模型不编造 context"）。

**(2) stream()：provider + model → 账号 → 上游凭据**（`src/llm-adapter.ts:836-856`）

```ts
let credential = await this.options.resolveCredential()      // 闭包注入，实现在 index.ts
if (credential === undefined || Date.parse(credential.expires_at) <= Date.now()) {
  await this.options.refresh()                               // 过期先续期
  credential = await this.options.resolveCredential()
}
if (... !credential.access_key_id ...) throw new LlmError('codearts: no usable credential; log in first', 'MISSING_CREDENTIAL')
```

`resolveCredential` 的实现由 `src/index.ts` 注入，内部走账号池：`pool.getAvailableAccount('codearts', '')`（`src/index.ts:164`）。**model 作为参数传入 `getAvailableAccount` 以支持「按模型的限流标记」跳过受限账号**（trae 的调用点最清楚：`this.options.accountPool.getAvailableAccount(this.product.id, options.model, tried)`，`src/trae-adapter.ts:940-941`）。

**(3) model id → 上游请求体的 `model` 字段**：**不做重命名映射**，直接把 `options.model` 原样写进上游请求体（`src/llm-adapter.ts:894` `model: options.model`；`src/trae-adapter.ts:906` 经 `transformToSOLOBody` 后仍是同一 id 语义）。qoder 是唯一例外：它用目录 key（`qfmodel` 等）作为 `modelKey`，因为加密端点认的是目录 key（`src/qoder-adapter.ts:293-294`、`:263-265` 注释）。

> **对比我们网关**：我们 `config.models[].name`（系统模型名）→ `resources[].{vendor, vendor_model}` 是**静态映射表 + 资源池选路**（`model_gateway/core/resources.py:120-125` `pick_and_acquire(system_model, exclude)`）；DSH 是**运行时 provider 路由 + 账号池选号 + 同 id 直通上游**。DSH 的 id 即上游 id，因此没有「系统模型名 ↔ 厂商模型名」的映射层 —— 这是它的便利也是它的限制（同名模型无法合并成一个对外模型）。

### 3.4 模型元数据的来源

| 元数据 | 来源 | 证据 |
|---|---|---|
| 上下文窗口 | 远端 `maxInputTokens` / `max_context_window` → 产品兜底表 → 静态表 | `src/buddy-adapter.ts:813-815`、`src/trae-adapter.ts:569-575` |
| 单次输出上限 | 远端 `maxOutputTokens` → 兜底表；缺失则**保持 undefined** 交给宿主默认 | `src/buddy-adapter.ts:836-839` + `:823-835` 注释（"编造一个偏大的值会让服务端 400 拒绝"） |
| 是否支持图片 | **按模型**判定（兜底表 `supportsImages` / 远端 `multimodal`），未声明保守报 `['text']` | `src/qoder-adapter.ts:140-142`、`src/trae-adapter.ts:545-547`、`src/buddy-adapter.ts:718` |
| 思考档位 | 远端 `reasoning.supportedEfforts` → 兜底表 `reasoningEfforts`；无档位则不声明该字段 | `src/buddy-adapter.ts:727,740,843-856`、`src/qoder-product.ts:89` |
| 是否支持工具 | **不作为元数据播报**；由适配器在 `stream()` 内部按模型判定（codearts 的 DSML 模式） | `src/llm-adapter.ts:172-200` |
| 计费倍率 / 促销价 | 远端 `creditsRate` / `discountedCreditsRate` / `priceFactor` / `promotion`，仅进展示名 | `src/buddy-adapter.ts:1391`、`src/qoder-product.ts:64-88` |

**可见性门控（不是元数据，但决定目录内容）**：`listModels()` 先过两道闸：

```ts
if (!await providerCatalogVisible(this.options.accountPool, PROVIDER)) return []   // src/llm-adapter.ts:798
...
const disabled = this.options.accountPool?.disabledModelsFor(PROVIDER)            // :807
const listed = disabled?.size ? visible.filter(m => !disabled.has(m.id)) : visible
```

`providerCatalogVisible` 的语义：无已登录账号 → 返回 `false` → 整个 provider 分组从宿主目录隐藏；开关 `DSH_HIDE_MODELS_WITHOUT_ACCOUNT` **默认开启**，只有 `0/false/no/off` 才关（`src/account-pool.ts:744-771`）。**必须是返回 `[]` 而不是抛错**，因为宿主 `buildModelCatalog` 会把抛错归入 `failures`，界面上反而多一条 provider 报错（`src/llm-adapter.ts:786-789`、`src/account-pool.ts:717-722`）。黑名单语义是**黑名单制**：只有键存在且为 `true` 才隐藏，打开时**删除键**而非写 `false`（`src/account-pool.ts:225-240`）。

---

## 4. 请求转发与协议适配

### 4.1 `src/openai-compat.ts` 的真实用途（判定可复用性的关键）

**它不是 OpenAI 兼容服务端，而是「OpenAI 线格式 ↔ DSH `StreamChunk` 中间表示」的双向工具库中的"正向一半"（请求序列化 + SSE 消费）。它服务于插件内的适配器，不服务于任何外部工具。**

模块头注释（`src/openai-compat.ts:1-30`）自述动机：`buddy-adapter.ts` 与 `lobsterai-adapter.ts` 各自内联了一套**完全同源**的消息序列化（约 200 行）与 SSE 消费（约 230 行），差异只在 URL、请求头与少数厂商特有字段；第三个 OpenAI 兼容 provider（qoder）若再复制一份会分叉。**因此抽出本模块给 qoder 适配器使用。**

注释同时明确一个重要的**未重构事实**（`:14-16`）：

> 「既有适配器（buddy / lobsterai）**刻意不改用它**：那两份实现已被大量单测与线上流量验证过，重构它们属于与本任务无关的高风险改动。」

实际使用点只有一处：`src/qoder-adapter.ts:338` 调 `consumeOpenAiSse(unwrapQoderEnvelopeStream(response, 'qoder'), ...)`；`serializeMessages` 用于 `src/qoder-adapter.ts:266`。**codearts 适配器有自己的私有 `serializeMessages`**（`src/llm-adapter.ts:93-152`，差异是 `reasoning_content` 必须始终存在），trae 有 `transformToSOLOBody`。→ **同一仓库内存在 3 套消息序列化实现 + 3 套 SSE 消费实现**（openai-compat 一套、codearts 一套、trae 一套，buddy/lobsterai 各一套）。

模块导出的能力清单：

| 导出 | 行号 | 职责 |
|---|---|---|
| `contentToText` | `:37` | 内容块数组 → 纯文本 |
| `TOOL_RESULT_IMAGE_TEXT` | `:48` | 工具结果内嵌图片的载体文案 |
| `userContentParts` | `:62-105` | harness 内容块 → OpenAI 多模态 parts（图片必须 `{type:'image_url',image_url:{url}}`，`:53-54`） |
| `collectImages` | `:108-118` | 递归收集 `attachmentId`（含 `tool-result` 内层） |
| `serializeMessages` | `:135-232` | harness 消息 → OpenAI chat 线格式 |
| `errorMessage` / `errorDetail` / `httpErrorCode` / `isTransportError` | `:235-278` | 错误归类 |
| `consumeOpenAiSse` | `:302-554` | OpenAI SSE → `AsyncIterable<StreamChunk>` |

**它承载的实测教训**（每条都对应一个真实缺陷，是这份代码最值钱的部分，`:18-29` 与正文）：

1. `typeof x === 'string'` 而非 `!== undefined` —— 真实 SSE 里 `content` 与 `reasoning_content` **另一侧恒为 `null`**，只判 undefined 会让 `.length` 在 null 上崩溃（`:430-433`）。
2. **工具配对剔除**：孤儿 `tool_call`/`tool_result` 让后端 400，且坏历史被每次请求原样重放 → 会话彻底报废（`src/sse.ts:72-123` 的 `resolveToolPairing`）。
3. `function.name` 只允许**非空覆盖**：后续分片带空串会清空已解析的工具名 → `unknown tool ""`（`:472-476`）。
4. **残缺参数不补 `{}`**：那会伪造出合法外观，让 harness 报 schema 错误而非重试；正确做法是判 `max-tokens` 让宿主重试（`:523-528`、`:539-552`）。
5. `content` 为空且有 `tool_calls` 时**必须为 `null`**（OpenAI 规范，`:175-176`）。
6. 工具结果内嵌图片**不能留在 `role:'tool'` 消息里**，必须提升为其后的独立 `user` 消息（`:126-128`、`:142-150`）。
7. **空 Map 不能降级为 undefined**：图片存在但字节读取失败时，`[image unavailable]` 占位符会被静默跳过（`:130-133`）。

### 4.2 请求侧：入参形态 → 各家上游请求体

统一入口形态 = `GenerateOptions`（`{messages, system, tools, model, maxTokens, reasoningEffort, signal}`）。各 provider 的转换：

| provider | 转换要点 | 证据 |
|---|---|---|
| `codearts` | ① 内容块数组 → 纯文本（**只保留 `text` 块，丢弃图片**，端点会拒绝非 text 块）；② assistant 的 `tool-call` 块 → `tool_calls`，`reasoning` 块 → `reasoning_content`（**必须始终存在该字段**，缺失报 `Missing reasoning_content field`）；③ `tool-result` 展开为独立 `role:'tool'` 消息；④ `options.system` **unshift 进 messages**（后端只认 messages 里的 system）；⑤ 请求体附 `prompt_cache_key` / `include:['reasoning.encrypted_content']` / `reasoning_summary:'auto'` / `tool_stream:true` / `max_tokens` 默认 65536 | `src/llm-adapter.ts:93-152`、`:864-866`、`:893-918` |
| `codearts`（思考/工具特化） | deepseek-v4 系列**不发 `tools` 字段**，改为把工具 schema 注入 system 提示，让模型以 DSML 语法在 `delta.content` 里流式输出工具调用 —— 规避 APIG 网关 ~60s 空闲断连 | `src/llm-adapter.ts:172-200`、`:884-892`、`:462-704`（`DsmlContentExtractor`） |
| `buddy` / `workbuddy` | OpenAI 兼容；差异在 endpoint / UA / 归属头（由 product 配置承载） | `src/product.ts:74-144`、`:416-421`（`resolveUserAgent` 按模型族分档） |
| `lobsterai` | OpenAI 兼容（含 `image_url` data URL） | `src/index.ts:99-102` |
| `qoder` | ① 走**加密推理**端点，请求体需 WASM 签名；② 消息被拆成 `userText` + `history`；③ 图片 → data URL（`data:${mediaType};base64,...`）；④ 必填 `business:{type:'agent'}`（否则路由到故障节点）；⑤ 带 `displayName` / `maxInputTokens` | `src/qoder-adapter.ts:266-317` |
| `trae` | OpenAI → **SOLO** 一次性转换（messages 规范化、tools 序列化、`tool_choice` 归一化、`config_name` 注入）+ **按模型路由通道** | `src/trae-adapter.ts:906`、`src/trae.ts:1342`、`src/trae-adapter.ts:557-560` |

图片处理是**能力门控**的：`stream()` 先收集图片引用，再按适配器自己播报的 `inputModalities` 决定接受或抛 `UNSUPPORTED_CONTENT`（`src/qoder-adapter.ts:217-244`）—— 注释强调"声明支持就必须真支持"，因为宿主会按 `inputModalities` 决定是否把图片投影成文本占位符。

### 4.3 响应侧：各家 SSE → 统一 `StreamChunk`

| provider | 上游流格式 | 转换路径 | 证据 |
|---|---|---|---|
| `codearts` | OpenAI 兼容 SSE（`data: {...}` / `[DONE]`） | 适配器**内联**解析 → `StreamChunk`；额外含 DSML 标签提取（正文/思考/工具调用三通道分流） | `src/llm-adapter.ts:1153-1398`（消费）、`:1102-1152`（`emitDsmlFeed`） |
| `buddy` / `lobsterai` | OpenAI 兼容 SSE | 各自内联解析 → `StreamChunk` | `src/buddy-adapter.ts:1140`（`consumeSse`）、`src/lobsterai-adapter.ts:1061` |
| `qoder` | **信封套 OpenAI SSE**：每帧 `{"headers":...,"body":"<标准 OpenAI chunk 的 JSON 字符串>","statusCodeValue":200}`；**内层 body 未加密**，只有请求体需 WASM 加密 | `unwrapQoderEnvelopeStream`（TransformStream 剥信封）→ `consumeOpenAiSse` | `src/qoder-envelope.ts:1-140`、`src/qoder-adapter.ts:337-342` |
| `trae` | **自定义 SSE 事件格式（非 OpenAI 标准）**：`event:` + `data:` 跨行累积到空行才成帧 | `parseTraeSSELine` → 适配器内联状态机 → `StreamChunk` | `src/trae.ts:1540`、`src/trae-adapter.ts:1052-1130`（"SSE 事件累积状态（跨行累积 event + data）"） |

**`finish_reason` 的映射是一条硬规则**（两处实现一致）：`length` / 中途断流 / 参数残缺 → `max-tokens`；否则有工具调用 → `tool-calls`；否则 → `stop`。理由：报 `tool-calls` 会让宿主执行缺参调用并报 schema 错误，模型收到莫名错误后陷入重试循环；报 `max-tokens` 则丢弃并重试（`src/openai-compat.ts:539-552`、`src/llm-adapter.ts:1387-1398`）。

**超时分阶段**：首 token 用 `firstTokenTimeoutMs`（5min），收到首块后切 `chunkTimeoutMs`（10min），每次成功读取后重置；超时主动取消 reader 并抛可重试 `TIMEOUT`（`src/sse.ts:26-57`、`src/llm-adapter.ts:1155-1186`）。

**空响应的有条件重试**：TRAE 的 `consumeSse` 用 `sawAnyUpstreamEvent` 标记，**只在"一个上游事件都没收到"时才允许重试** —— 一旦已有 output/usage/tool_calls 事件，重放会重复计费并可能重复执行工具（`src/trae-adapter.ts:1070-1086`、`:966-983`）。

---

## 5. 管理面 / RPC 通道清单

### 5.1 通道定义

| 项 | 值 | 证据 |
|---|---|---|
| 路径 | `POST /api/jet-hub` | `src/jet-hub-rpc.ts:95,557` |
| 端点名 | `jet-hub` | `src/jet-hub-rpc.ts:97` |
| 客户端调用 | `connection.rpc.call('/api', 'jet-hub', {method, payload}, signal)` | `plugin-src/management-rpc.mjs:26` |
| 注册方式 | `ctx.connection.fetch.register({path, methods:['POST'], requestBody:'buffered', fetch})` | `src/jet-hub-rpc.ts:556-560` |
| 入站校验 | 405 方法 / 415 content-type / 400 非 JSON / `gateway/bad-request` 信封不合法 | `src/jet-hub-rpc.ts:561-585` |
| 鉴权 | **无** | §2.3 |
| 客户端 UI 挂载 | `ctx.slots.inject('settings.section', ...)`，id `jet-hub`，label "Jet Hub"，order 50 | `plugin-src/client/index.js:18-25` |
| 客户端 bundle 形态 | esbuild → CJS → `window.__ModuleLoader__.load({id:'dsh-codearts-auth', factory})` | `plugin-src/client/build.mjs:8,33-42` |

### 5.2 完整能力清单（16 个方法）

`handleMethod` 的 switch（`src/jet-hub-rpc.ts:604-1280`）：

| 方法 | 行号 | 入参 | 出参 / 作用 |
|---|---|---|---|
| `account.list` | `:606` | `{provider}` | `{accounts: ProviderAccountStatus[]}` |
| `account.create` | `:612` | `{provider}` | `{accountId, loginUrl}`；建占位条目 + 取登录 URL |
| `account.update` | `:797` | `{accountId, patch:{nickname?,enabled?}}` | 改昵称/启停 |
| `account.delete` | `:803` | `{accountId}` | 删账号 |
| `account.reorder` | `:811` | `{provider, orderedIds[]}` | 重排（顺序 = 自动选号优先级） |
| `account.refresh` | `:835` | `{accountId}` | `{success, error?}` 手动续期 |
| `login.poll` | `:894` | `{accountId, provider}` | `{done, success?, error?}` 轮询登录完成 |
| `account.retest` | `:909` | `{accountId}` | 重测限流标记（真实发探测消息） |
| `account.retestAll` | `:920` | `{provider}` | 重测该 provider 全部账号（**含已停用**） |
| `account.reset` | `:927` | `{accountId}` | 直接清除限流标记（不测试） |
| `account.resetAll` | `:933` | `{provider}` | 批量清除（**含已停用**） |
| `credits.status` | `:954` | `{provider}` | 各账号签到状态 |
| `credits.claimAll` | `:1007` | `{provider}` | 一键领取积分 + 汇总 |
| `credits.balances` | `:1093` | `{provider}` | 各账号积分余额（含包明细） |
| `model.list` | `:1196` | `{provider}` | `{models:[{id,name,disabled}]}` |
| `model.setDisabled` | `:1262` | `{provider, modelId, disabled}` | 写黑名单，返回最新黑名单 |
| *(default)* | `:1278` | — | `bad-request: unknown method` |

**`model.list` 是本插件唯一"把聚合模型目录往外暴露"的出口**，其数据源设计值得单独记：

```ts
models = await llm.listModels(req.provider)          // :1204  权威目录（已被黑名单过滤）
const disabledMap = pool.listDisabledModels(req.provider)   // :1211
const all = modelAdapters?.[req.provider]?.listAllModels()  // :1230-1231  不套黑名单的全量目录
catalog = all !== undefined ? [...all] : [ ...models, ...filteredOut.map(id => ({id, name:id})) ]
```

注释给出了一个真实缺陷的根因（`:1212-1217`）：若直接用被过滤后的 `listModels()` 结果回填 `disabled`，会形成闭环矛盾 —— 被关闭的模型连同它的开关一起从设置页消失，**用户再也无法重新打开**。因此设置页必须用**未过滤**的全量目录。这也是 `listAllModels()` 这个非契约方法存在的唯一理由（`src/llm-adapter.ts:776-783`）。

### 5.3 管理面能不能被"别的工具"用

**不能。**

1. **不是独立监听端口**：由宿主 `connection` 服务挂载（`src/jet-hub-rpc.ts:550-556`）。第三方必须先进 DSH 宿主。
2. **只在 Web profile 存在**：headless / CLI profile 下该端点**根本不注册**（`src/index.ts:26-32`、`src/jet-hub-rpc.ts:499-501`）。
3. **协议是宿主专有**：RPC 信封 `{type:'client-request', rpcId, method:'jet-hub', payload:{method,payload}}` + `{type:'server-response', rpcId, result}`（`src/jet-hub-rpc.ts:576-585,1285-1290`）。它**不是稳定对外协议**，字段随 DSH 版本演进。
4. **无鉴权**（§2.3）。
5. **不含任何 chat 能力**：16 个方法全是账号/积分/模型开关（§5.2），**没有** `chat.completions` 之类的方法。

---

## 6. 可复用性判定矩阵

### 6.1 矩阵

| 消费方 | 可复用？ | 复用什么 | 前提 / 缺口 |
|---|---|---|---|
| **同 DSH 宿主的另一插件** | ✅ 是 | ① `ctx.llm.listModels(provider)` 读聚合目录；② 经宿主 `LlmRuntime` 走 `prepareCall` → `stream` 发起对话（与插件自身适配器同一条路径）；③ `ctx.get('accountPool')`（`src/index.ts:429`）拿账号池做选号/限流；④ `ctx.get('buddyAuth')` 等 6 个 Service 做登录/续期 | 必须与插件加载在同一宿主进程、同一 profile；`accountPool` 是**本插件自定义服务名**，非 DSH 标准契约，跨插件用属**非稳定接口**；适配器实例的 `listAllModels()` **拿不到**（`ctx.llm` 不透传自定义方法，`src/index.ts:415-416`），只能像 Jet Hub 那样由插件作者手工传出 |
| **任意第三方程序（Trae / Cursor / Cherry Studio）** | ❌ 否 | — | 输出面是 TS 对象方法 + `AsyncIterable`，跨不了进程；无 OpenAI 兼容端点；唯一 HTTP 面是宿主内嵌 RPC 且无 chat 能力、无鉴权、非稳定协议 |
| **另一个独立网关（如我们 Model-Gateway）** | ❌ 直接复用不行；**代码级可大量借鉴** | 见 §7 清单 | 需自建 HTTP 服务 + OpenAI 兼容层 + 反向编码器 |

### 6.2 若要复用，需要补什么

| # | 缺口 | 现状 | 要补的东西 |
|---|---|---|---|
| 1 | 独立服务进程 | 无（唯一 `node:http` 服务器是 OAuth 回调） | 常驻 HTTP 服务，绑定端口 |
| 2 | OpenAI 兼容路由 | 无 | `POST /v1/chat/completions`（stream + non-stream）、`GET /v1/models` |
| 3 | **反向编码器** | 只有 `OpenAI SSE → StreamChunk`（`consumeOpenAiSse`）；**不存在** `StreamChunk → OpenAI SSE` | 新写：把 `block-start/text-delta/reasoning-delta/tool-call-delta/block-end/usage/finish` 编码为 `chat.completion.chunk` |
| 4 | 模型 ID 扁平化 | 靠 `provider` 字段分组 | OpenAI 只有单一 `model` 字符串 → 需命名策略（如 `qoder/qfmodel`、`codearts/deepseek-v4-pro`），并处理同名消歧（可复用 `variantLabelFor`） |
| 5 | 鉴权 | 0（§2.3） | 入站 API Key / Bearer 校验 |
| 6 | 凭据与宿主解耦 | 全部走 `ctx.credentials` + `ctx.settings` | 独立凭据存储与配置（或导入导出） |
| 7 | 宿主服务依赖 | `inject = ['credentials','commands','llm']`，`connection` 惰性注入 | 去掉 cordis 依赖，改为独立进程内的依赖注入 |

---

## 7. 可直接抽取复用的代码清单

### 7.1 可直接复用（纯函数 / 弱依赖，仅需 `LlmError`、`ToolCallId`、`StreamChunk` 三个类型的等价物）

| 文件 / 函数 | 行号 | 复用价值 | 剥离成本 |
|---|---|---|---|
| `src/sse.ts` → `resolveToolPairing` | `:91-123` | ⭐⭐⭐ 孤儿工具配对自愈，防会话永久报废 | 零依赖，纯函数 |
| `src/sse.ts` → `normalizeToolArguments` | `:125-138` | ⭐⭐⭐ 空串 → `{}`，非对象 → `{}` | 零依赖 |
| `src/sse.ts` → `isTruncatedArguments` | `:158-167` | ⭐⭐⭐ 区分「无参数」与「分片丢失」 | 零依赖 |
| `src/sse.ts` → `readWithIdleTimeout` | `:26-57` | ⭐⭐ 空闲超时 + 取消 reader + 可重试错误 | 依赖 `LlmError` → 换成自有异常 |
| `src/openai-compat.ts` → `serializeMessages` | `:135-232` | ⭐⭐⭐ harness 块 IR → OpenAI 线格式（工具配对 + 图片提升 + content null 规范） | 依赖 `resolveToolPairing` / `normalizeToolArguments` / `contentToText` / `userContentParts` |
| `src/openai-compat.ts` → `userContentParts` / `collectImages` | `:62-118` | ⭐⭐⭐ 多模态 parts 构造 + 递归收集 | 零外部依赖 |
| `src/openai-compat.ts` → `consumeOpenAiSse` | `:302-554` | ⭐⭐⭐ OpenAI SSE → 结构化块事件（含 null 容错、`data:` 无空格容错、usage 归一） | 依赖 `StreamChunk` 类型 → 换成自有 dataclass |
| `src/openai-compat.ts` → `errorDetail` / `httpErrorCode` / `isTransportError` | `:241-278` | ⭐⭐ 错误归类 | 零依赖 |
| `src/qoder-envelope.ts` → `unwrapQoderEnvelopeStream` | `:64-140` | ⭐⭐ 用 `TransformStream` 剥信封（对任何"套壳 SSE"厂商通用） | 依赖 `LlmError` |
| `src/models.ts` → `normalizeModelId` | `:41-49` | ⭐⭐ 去日期版本后缀（`-0731`），规避"IDE 列表 id ≠ 后端注册 id" | 零依赖 |
| `src/models.ts` → `fetchCodeArtsRemoteModels` 的合并去重骨架 | `:120-165` | ⭐⭐ 多端点拉取 + 去重 + 失败不阻断 | 依赖 `signRequestHuawei`（华为 AK/SK 签名，`src/sign.ts`） |
| `src/product.ts` → `BuddyProduct` 配置模型 + `resolveUserAgent` | `:74-144`、`:416-421` | ⭐⭐⭐「一产品一配置对象，差异全部收敛」的范式 | 零依赖 |
| `src/buddy-adapter.ts` → `displayNameFor` / `variantLabelFor` / `commonPrefix` | `:1382-1421` | ⭐⭐⭐ 同名模型消歧 + 倍率展示 | 零依赖 |
| `src/trae.ts` → `transformToSOLOBody` / `parseTraeSSELine` | `:1342`、`:1540` | ⭐ 逆向所得的非标准协议转换，仅当要接 TRAE 时有用 | 需剥离 trae 特有常量 |
| `src/account-pool.ts` → 选号与限流标记算法 | 类 `AccountPool` | ⭐⭐ `getAvailableAccount(provider, model, exclude)` + `updateModelRateLimit` | 强依赖 `ctx.settings`/`ctx.credentials`，需改存储层 |

### 7.2 必须重写（形态绑定 DSH，无法抽取）

| 对象 | 原因 |
|---|---|
| 5 个 `XxxAdapter extends LlmAdapter` 本体 | `stream()` 的 `yield` 形态、`providerInfo`/`listModels`/`resolveModel`/`prepareCall` 全是 DSH 契约；基类来自 `@deepseek-ai/dsh-llm` |
| 所有 `registerXxxLlm(ctx, options)` 注册函数 | 依赖 `ctx.llm.registerConfigurableProviders` / `registerAdapter` |
| `src/jet-hub-rpc.ts` 整个文件 | 依赖 `ctx.connection.fetch.register` + DSH RPC 信封 |
| `src/index.ts` 的 `apply()` 与 `ctx.effect` / `ctx.provide` / `ctx.inject` | cordis 生命周期 |
| `plugin-src/client/*` 全部 | DSH Web UI 的 `slots` / `__ModuleLoader__` 机制 |
| 各 auth/oauth/credits 模块 | 依赖 `ctx.credentials` 与宿主登录流程（属另一同事范围） |

### 7.3 「同源实现分叉」的警示

同一仓库内并存 **3 套消息序列化**（`openai-compat.ts:135`、`llm-adapter.ts:93`、`trae.ts:1342`）与 **5 套 SSE 消费**（`openai-compat.ts:302`、`llm-adapter.ts:1153`、`buddy-adapter.ts:1140`、`lobsterai-adapter.ts:1061`、`trae-adapter.ts:1052`）。`openai-compat.ts:14-16` 明确承认这是**有意的技术债**（"刻意不改用它…重构它们属于与本任务无关的高风险改动"）。→ 如果我们网关要做多 provider，**必须一开始就定好单一 IR + 单一协议适配层**，否则会复现同样的分叉。

---

## 8. 对照我们网关（Model-Gateway）的借鉴建议

已读对照文件：`model_gateway/core/ir.py`（174 行）、`model_gateway/adapters/openai_out.py`（207 行）、`model_gateway/core/resources.py`（选路）、`model_gateway/adapters/`（`base.py` / `openai_out.py` / `anthropic_out.py` / `gemini_out.py`）。

### 8.1 值得借鉴（按价值排序）

**(1) 统一 IR 用「结构化块事件」而非「OpenAI chunk 字典」** ⭐⭐⭐

- 现状：`ir.py:161-174` 的 `normalize_stream_chunk` 只做**字段补充**（`thinking_content`/`reasoning` → 补 `reasoning_content`），保留 OpenAI chunk 字典形态。
- DSH 的做法：`StreamChunk` 是带 **`index` + 显式 `block-start`/`block-end`** 的块事件（`src/openai-compat.ts:443,446,455,458,469,479,516,533,553`）。好处：① 工具调用参数的**跨分片累积**有明确归属（`index` + 局部 `block.text += fragment`）；② 块收尾时一次性给出**已归一的完整 arguments**；③ UI 可按块渲染，不必自己维护状态机。
- 建议：`ir.py` 增加一层可选的块事件表示（至少为 tool_call 引入 `index` 与显式收尾），出站编码时再降回 OpenAI chunk。**注意**：我们的 IR 是"透传优先"，加块事件要保证不丢原始字段（DSH 是入向 IR，可以自由重塑；我们是双向，需保守）。

**(2) 工具配对自愈（`resolveToolPairing`）** ⭐⭐⭐

- 现状：`ir.py` 注释明写"透传优先"，`openai_out.py` 直接 `dict(body)` 透传 messages。客户端历史里若有孤儿 `tool_call`/`tool_result`，上游会 400 且**每次请求原样重放** → 该会话永久失败。
- DSH 的做法：发出前剔除无法配对的条目（`src/sse.ts:91-123`），代价是丢一轮工具上下文，换来会话自愈。
- 建议：在出站适配层（`openai_out.py` 的 `_prepare_body` 之前）加一道可开关的配对清洗。这是**低风险高收益**的改动。

**(3) 截断参数 → `max-tokens` 而非 `tool-calls`** ⭐⭐⭐

- DSH 的硬规则（`src/openai-compat.ts:539-552`）：`length` / 中途断流 / 参数残缺 一律报 `max-tokens`，让宿主丢弃残缺调用并重试；报 `tool-calls` 会让宿主执行半截 JSON 并陷入错误循环。
- 我们的网关目前无此语义（透传 `finish_reason`）。若我们未来做 agent 场景，这是必须的。

**(4) 「模型目录 = 远端探测 → 本地兜底表 → 用户黑名单」三级结构** ⭐⭐

- 现状：我们 `config.models[].name` + `resources[].vendor_model` 是**纯静态映射**，`resources.py:113` 从 config 构建 `system_models` 集合。
- DSH 的做法：`listModels()` = `providerCatalogVisible` 门控 → `ensureRemoteModels()` 懒加载远端 → 兜底表 → 黑名单过滤（`src/llm-adapter.ts:785-812`）。兜底表存在的原因很实际：**服务端按认证上下文下发的模型池未必完整**（`src/product.ts:126-135` 注释："实测 WorkBuddy 国际版经 CLI token 只能拿到 13 个别名，拿不到 GPT 系列"）。
- 建议：可选加"远端 `/models` 探测 + 本地兜底表"的目录机制，用于 provider 侧模型上线的自动发现。**但注意**：我们已有 `openai_out.list_models`（`openai_out.py:183-191`），只是目前看起来未接入目录构建。

**(5) 同名模型消歧（`variantLabelFor` 的公共前缀法）** ⭐⭐

- 我们如果聚合多个 vendor 且有同名模型（如两个 vendor 都有 `glm-5.2`），客户端展示会撞车。DSH 用**公共前缀切分**得到变体标记（`src/buddy-adapter.ts:1410-1416`），而不是硬编码后缀或取 id 最后一段。可直接移植。

**(6) 分阶段空闲超时 + 可重试错误分类** ⭐⭐

- DSH：首 token 5min / chunk 间 10min，超时主动 cancel reader 并抛可重试 `TIMEOUT`；传输级错误映射为 `TRANSPORT`（`src/sse.ts:26-57`、`src/llm-adapter.ts:1155-1186`）。
- 我们：`openai_out.py:53` 单一 60s timeout。对"模型长思考 / 大工具参数"场景过短。建议按阶段拆分。

**(7) 「一 provider 一适配器 + 协议库复用」的组合范式** ⭐⭐

- DSH 的 `BuddyProduct`（`src/product.ts:74-144`）把 endpoint / platform / productCode / UA / 归属头 / 兜底模型表 / 凭据 ref 全部收敛成一个配置对象，使 CodeBuddy 与 WorkBuddy **共用同一套实现**（`src/index.ts:206-207` 注释："与 CodeBuddy 同源（同后端、同协议），差异全部由 product 配置承载"）。
- 我们目前是「一协议一适配器」（`openai_out` / `anthropic_out` / `gemini_out`）。两者是**正交**的：协议适配器管线格式，product/channel 配置管渠道差异。建议在现有协议适配器之上补一层"渠道配置对象"，把 base_url / key / 模型映射 / 特殊头 / 兜底模型表收敛进去 —— 这样加一家 OpenAI 兼容厂商就不用改代码。

**(8) 「把厂商 hack 收敛在适配器内部」** ⭐⭐

DSH 里塞了大量逆向所得的特化：DSML 工具模式（`src/llm-adapter.ts:172-200`）、`maas_type: benefit` 签名头（`:52,940`）、TRAE 通道路由（`src/trae-adapter.ts:557`）、`business:{type:'agent'}`（`src/qoder-adapter.ts:315`）。这些 hack 全部**封装在各自适配器内，不泄漏到调度层**。这个边界纪律值得照搬。

### 8.2 不能照搬的形态

| DSH 形态 | 为什么我们不能照搬 |
|---|---|
| `AsyncIterable<StreamChunk>` 作为对外契约 | 我们是**独立常驻进程 + HTTP 端点**，必须有序列化边界。DSH 的契约只在同一 Node 进程内成立。 |
| 模型寻址用 `(provider, model)` 二元组 | OpenAI 兼容面只有**单一 `model` 字符串**（`api/openai_compat.py`）。必须扁平化命名（建议 `vendor/model` 前缀法），并在 `/v1/models` 里如实列出扁平名。 |
| 管理面无鉴权 | 我们是对外端点，`api/auth.py` 的鉴权是硬要求。DSH 的无鉴权是因为它跑在用户本机的宿主进程内。 |
| 凭据绑定 `ctx.credentials` | 我们的 key 在 `config` 里，且有资源池/多 key 语义（`resources.py`）。 |
| 「模型 id 即上游 id」直通 | 我们需要「系统模型名 → 多厂商多资源」的映射层（`ir.py:118` 的 `system_model`），这是聚合网关的核心价值；DSH 不做这层映射。 |
| 进程内 `ctx.provide('accountPool', pool)` 做跨插件共享 | 我们的等价物是内部模块单例 + HTTP 管理面，不是服务容器。 |
| 大量依赖宿主 profile（Web vs headless）的条件注册 | 我们是单一形态，不需要这种分支；但**可以借鉴它的教训**：一个可选依赖不应让整个服务启动失败（`src/index.ts:26-32` 的注释就是一个真实故障复盘）。 |

---

## 9. 未验证清单

| # | 未验证项 | 卡点 | 影响 |
|---|---|---|---|
| 1 | `@deepseek-ai/dsh-llm` 的 `LlmAdapter` 基类**完整**方法集 | 项目无 `node_modules/`、无 `lib/`（`ls` 确认）；类型声明只存在于 peerDependencies 声明中（`package.json:63-69`），实体不在本机 | §1.2 的方法签名是**从 5 个子类实现反推**的"实际覆写集"，非基类全集。基类可能另有未被子类覆写的方法（如 provider 列表、能力查询） |
| 2 | `GenerateOptions` / `LlmModelInfo` / `LlmResolvedModelInfo` / `StreamChunk` 的**字段声明** | 同上 | 本文的字段清单来自**消费点/产出点**，可能遗漏从未被本插件使用的字段 |
| 3 | `ToolCallId` / `ReasoningEffortId` 等品牌类型的构造语义 | 同上（只见到调用形式 `ToolCallId(string)`、`ReasoningEffortId(id)`） | 不影响结论 |
| 4 | `connection.fetch.register` 的完整签名（是否有 auth / 中间件参数） | `@deepseek-ai/dsh-connection` 不在本机 | §2.3 的"无鉴权"仅指**本仓库内无鉴权代码**；宿主是否在更外层加鉴权未验证 |
| 5 | `ctx.provide(name, value)` 的 cordis 语义（是否等价 `ctx.set`） | cordis 包不在本机 | §1.1 / §6.1 对"跨插件可复用"的判定基于其命名意图与用法，语义细节未验证 |
| 6 | `buildModelCatalog` / `LlmRuntime` / `resolveCallWithInfo` / `resolveModelInfoFor` 的实际实现 | 属宿主包（`dsh-api-session-controller` 等），不在本机 | §1.3 的调用时机来自**本插件注释的描述**，未与宿主源码对拍 |
| 7 | `tests/unit/*.spec.ts` 中对契约的补充证据 | 测试文件 import 真实 `@deepseek-ai/dsh-llm`（`tests/unit/llm-adapter.spec.ts:1`），无 `vi.mock`，本机无法运行 | 可能另有未读到的契约断言 |
| 8 | `src/index.ts` 之外是否还有其它注册入口（如 `lib/` 编译产物中的差异） | `lib/` 不存在 | 已按任务要求以 `src/` 为准 |

**方法说明**：所有结论均来自 `src/` 与 `plugin-src/` 的实际代码阅读；凡属推断（如宿主行为）均已在正文显式标注为"注释描述"或"推断"。未从网络获取任何资料。

---

## 10. 证据附录

### 10.1 关键代码索引（按主题）

**宿主契约**
- `src/index.ts:25,33,121` — 插件三件套（`name` / `inject` / `apply`）
- `src/index.ts:129-131` — 6 个 settings namespace 注册
- `src/index.ts:152-176,182-203,211-231,239-278,286-320,329-353` — 6 个 provider 的注册调用
- `src/index.ts:415-429` — 适配器实例收集 + `registerJetHubRpc` + `ctx.provide('accountPool')`
- `src/llm-adapter.ts:726,746,776,785,814,824,835` — `CodeArtsAdapter` 类与全部契约方法
- `src/llm-adapter.ts:1452-1462` — 注册函数
- `src/buddy-adapter.ts:861-866` — `prepareCall` shim（宿主调用时机的一手说明）
- `src/buddy-adapter.ts:826-839,1434-1436` — `defaultMaxTokens` 契约
- `src/service.ts:75-83` — `CodeArtsAuth extends Service`，`super(ctx,'codeartsAuth')`
- `src/buddy-auth.ts:117-126` — 服务名由 product.id 派生

**流式契约**
- `src/llm-adapter.ts:1112,1115,1122,1125,1143-1150,1367-1379,1382,1385,1398` — `StreamChunk` 各成员产出点
- `src/openai-compat.ts:443,446,455,458,469,479-485,494-504,516-530,533,537,553` — 同上（qoder 路径）
- `src/llm-adapter.ts:1387-1398` — `finish` 原因映射
- `tests/unit/llm-adapter.spec.ts:119-145` — `prepareCall` / `stream` 的测试断言

**模型目录**
- `src/llm-adapter.ts:24-29,38-43,52` — 静态模型表 / 上下文窗口 / benefit 模型集
- `src/models.ts:8,16,19,25,41-49,120-165,167-204,210-223` — 远端端点 / 缓存 / id 归一化 / 拉取合并 / 缓存读写
- `src/product.ts:74-144,168-254,283-355,398-421` — 产品配置模型 / 两个兜底模型表 / UA 分档
- `src/qoder-product.ts:55-91,127,199-213` — 倍率字段 / provider id / 加密端点说明
- `src/qoder-adapter.ts:144-150,158-182` — 恒用本地目录的说明与实现
- `src/buddy-adapter.ts:809-857,1368-1421` — `resolveModel` 三级查找 / 展示名与消歧
- `src/trae-adapter.ts:545-597` — 模态 / 通道 / 上下文 / Max 模式
- `src/account-pool.ts:206-240,717-722,744-771` — 黑名单读写 / catalog 隐藏语义 / 可见性门控

**协议适配**
- `src/openai-compat.ts:1-30` — 模块动机与实测教训清单（本文件最有价值的部分）
- `src/openai-compat.ts:37-278,302-554` — 全部导出能力
- `src/sse.ts:26-57,91-123,125-138,158-167` — 空闲读 / 工具配对 / 参数归一 / 截断判定
- `src/llm-adapter.ts:93-152,172-200,462-704,893-918,1102-1152,1153-1398` — codearts 的序列化 / DSML / 请求体 / SSE 消费
- `src/qoder-envelope.ts:1-140` — 信封剥除
- `src/qoder-adapter.ts:263-342,365-370` — 加密请求构造 / 信封消费 / 头发送
- `src/trae.ts:1342,1540` — SOLO 转换 / 自定义 SSE 解析
- `src/trae-adapter.ts:880-983,1052-1130` — 请求体构造 / 空响应重试 / SSE 状态机

**管理面**
- `src/jet-hub-rpc.ts:1-13,94-97,495-601` — 通道定义 / 端点注册
- `src/jet-hub-rpc.ts:604-1280` — 16 个方法
- `src/jet-hub-rpc.ts:1285-1290` — 响应信封
- `plugin-src/management-rpc.mjs:22-37` — 客户端调用与解包
- `plugin-src/client/index.js:11-25` — UI slot 挂载
- `plugin-src/client/build.mjs:8,33-42` — bundle 形态

### 10.2 判定依据：不存在 OpenAI 兼容对外端点

执行过的检索（只读）：全仓 `grep -rnE "createServer|\.listen\(|http\.Server|/v1/chat/completions|/v1/models|openai/v1" src/ plugin-src/`，命中项全部为：

| 命中 | 性质 |
|---|---|
| `src/trae-oauth.ts:20,447,495,596,715` | OAuth 本地回调服务器（`127.0.0.1`） |
| `src/lobsterai-oauth.ts:22,256,348` | 同上 |
| `src/login.ts:1,162,170,219,279,287,343,348` | 同上 |
| `src/qoder-product.ts:34,199,213` | **上游**路径常量（`model/v1/chat/completions`），非本插件提供的路由 |
| `src/lobsterai-product.ts:41` | **上游**路径常量（`POST /api/proxy/v1/chat/completions`） |

→ 本插件**没有**任何对外提供 chat 能力的 HTTP 路由。唯一由本插件注册的 HTTP 路由是 `POST /api/jet-hub`（`src/jet-hub-rpc.ts:95,557`），能力集见 §5.2。
