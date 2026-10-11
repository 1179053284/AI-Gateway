# 21 · DSH 插件「内部模型读取与输出面机制」复核 + 增量（2026-09-29 快照）

> 调研对象：`/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts`（gitee 上游 `iJetLi/deepseek-harness-codearts`）。
> **本文件快照**：本地 HEAD `a3fe5f2`＝上游 gitee master `f531c2984`（2026-09-29 同步）；**上一快照** `d461361`＝`b3a95615c`（2026-09-22）。
> 复核基准：`docs/research/03-DSH-聚合模型输出面与可复用性.md`（及其 v2 稿）；本文**只补差量并复核**，已归档到 PRD §9 Q25 的条目（能力位下发 / 7 档序 / 两层降级 / 探测优先 / 四表存储 / 前缀剥离 / 零映射告警 / setup 目录 / 不做清单）不再重复论证。
> 事实基准：`src/` 与 `plugin-src/` 源码（`node_modules/`、`lib/` 本机不存在，见「未验证清单」）。全程只读。
> 写作约定：**【代码】**＝直接读到的代码事实（附 `file:line`）；**【推断】**＝未获代码直证的推断；**【未验证】**＝卡住未证实。

---

## 0. 结论先行

### 0.1 四点用途的直达答案

| 用途 | 结论 | 关键依据 |
|---|---|---|
| ① 多产品多账号接入与管理 | 已从 6 provider 扩到 **11 个 provider 实例**（新增 qodercn / cline / loomy / raccoon / zcode），注册范式未变：`ctx.llm.registerConfigurableProviders` + `registerAdapter` | `src/index.ts:209-212,1209-1225` |
| ② 自动化签到/领取运营 | Jet Hub RPC 方法从 16 个扩到 **26 个**，新增 `login.sendSms` / `login.submitSms` / `onboarding.*` / `credits.permanentLock` / `model.setAllDisabled` / `backup.*` | `src/jet-hub-rpc.ts:818-2483`（case 行号见 §3.2） |
| ③ 产品内部模型读出并对外输出 | **读出机制更成熟**（全部 11 个 provider 实现 `listAllModels()` 全量目录 + 黑名单分离）；**对外输出面仍然为零** —— 无独立端口、无 OpenAI 兼容端点、无反向编码器；唯一 HTTP 面 `POST /api/jet-hub` 挂在 DSH 宿主内、无鉴权、**不含 chat 能力** | §3.1–3.4 |
| ④ 号池快速搭建与简易网关借鉴 | 可借鉴：产品配置对象化（`product.ts`/各 `*-product.ts`）、三级目录（远端→兜底→黑名单）、同名消歧、换号重试骨架、`sse.ts` 工具库；**不可**照搬：进程内 `AsyncIterable` 契约、`(provider,id)` 二元组寻址、无鉴权管理面 | §5 |

### 0.2 相对 `03` 的最大三条漂移（详见 §4）

1. **provider 数量翻倍**：6 → 11（`qoder` 拆国际/中国两实例；新增 cline / loomy / raccoon / zcode），`03` 的「5 个适配器 + 6 provider」表述已整体过期（`src/index.ts:233-1063`）。
2. **`openai-compat.ts` 的定位变了**：不再是「只给 qoder 用」；现在 **cline / loomy / raccoon / qoder 四个适配器共用**它消费 SSE（`src/cline-adapter.ts:553`、`src/loomy-adapter.ts:521`、`src/raccoon-adapter.ts:466`、`src/qoder-adapter.ts:846`），且头部注释仍写「给 qoder 适配器使用」（`src/openai-compat.ts:12`）——注释滞后于实现。
3. **管理面模型出口 `model.list` 的半边数据源从 settings 迁到插件自有文档** `$DSH_HOME/jet-hub/state.json`（0.1.7 起黑名单/账号索引不再经 settings 文档，`src/jet-hub-store.ts:302-345,396-428`）——这直接影响「别的工具能否监听/读取」的判定（§3.4）。

### 0.3 一句话判定（③ 的可行性）

> **「产品内部模型 → DSH 插件 → 网关 → 外部软件」这条链在插件侧是断的，但在进程外可绕行**：插件对外的唯一协议面是宿主内嵌 RPC（无 chat、无鉴权、非稳定），
> 而插件的**凭据与状态全部落明文磁盘**（`~/.dsh/.credentials.yaml` + `$DSH_HOME/jet-hub/state.json`，路径可被 `DSH_HOME` 覆盖），
> 且仓库内**已有进程外消费先例**：e2e 探针（普通 Node 进程）直接从 `.credentials.yaml` 读账号凭据、直连上游 API（`tests/e2e/workbuddy-credential.ts:28`、`tests/e2e/loomy-credential.ts:1-30`）。
> 因此网关侧可行的不是「接入插件」，而是**① 抄协议实现直连上游（推荐，证据充分）**或 **② 读盘拿凭据 + 复刻上游协议（可行但需自担字段/风控漂移）**；把插件当服务端接没有出路。

---

## 1. 内部模型读取：逐产品模型清单来源（以 src/ 为准）

### 1.1 总表（11 provider）

| provider（路由名） | 模型清单来源 | 远端端点 | 兜底表（静态目录） | 证据 |
|---|---|---|---|---|
| `codearts` | 远端双端点 + 磁盘缓存 + 静态表 | `opengw.../api/v1/gateway/config`（benefit）+ `snap-access.../v1/model/builtin`（常规） | `DEFAULT_MODELS` 9 条 | `src/models.ts:9,17,159-227`；`src/llm-adapter.ts:31-37` |
| `buddy`（CodeBuddy） | 远端 `/v3/config` + 产品兜底表 | 产品配置 `apiDomain` + `/v3/config` | `CODEBUDDY_FALLBACK_MODELS`（约 14 条，含 hy4/hy3/deepseek-v4.x/glm/kimi/minimax） | `src/product.ts:180-283`；`src/buddy-adapter.ts:1037,1060-1066` |
| `workbuddy` | 同上（同源后端） | 同上（国际版域名） | `WORKBUDDY_FALLBACK_MODELS`（含 gpt-6-astra / gpt-5.6-* 系列） | `src/product.ts:295-355`；`src/index.ts:220-228` |
| `lobsterai` | 远端 `/api/models/available` + 兜底表 | `GET {apiBase}/api/models/available`（带 keyfrom query） | `LOBSTERAI.fallbackModels` | `src/lobsterai-adapter.ts:250-292,302-312,823-829` |
| `qoder` / `qodercn` | **恒用本地兜底表，零网络** | 无（目录端点需 WASM 签名，不实现） | `QODER_FALLBACK_MODELS`（:362-458）/ `QODER_CN_FALLBACK_MODELS`（:480-630）各一张 | `src/qoder-adapter.ts:512-550`；`src/qoder-product.ts:362-458,480-630` |
| `trae` | 远端 batch 目录（按通道查）+ 兜底表 | `batch_get_detail_param` 按 `function` 通道；`display_config` 决定可用性 | `TRAE.fallbackModels`（约 25 条，带 `isHidden`） | `src/trae-adapter.ts:616-620,782-790`；`src/trae-product.ts:82-102,170-188` |
| `cline` | **远端两端点合并** + 兜底表 | `GET /api/v1/ai/cline/recommended-models`（免费集合，免认证）+ `GET /api/v1/models`（460 条 id，需认证） | `CLINE.fallbackModels`（含 5 免费） | `src/cline-models.ts:1-36,192-235,256-312`；`src/cline-adapter.ts:239-287` |
| `loomy` | 远端 `GET /api/v1/models`（token 头）+ 兜底表 | `{apiBase}/models`（`token:` 头，非 Bearer） | `LOOMY.fallbackModels` | `src/loomy-adapter.ts:131-172,259-275`；`src/index.ts:828-850` |
| `raccoon` | 远端 `GET /api/web/llm/v2/model_catalog` + 兜底表（6 条） | auth 侧 `fetchModels()`，过滤 `visible===false`，倍率进展示名 | `RACCOON_FALLBACK_MODELS`（:218-288） | `src/raccoon-auth.ts:171-180,470,620`；`src/raccoon-product.ts:197-288` |
| `zcode` | **静态白名单（2 条）**，不枚举远端 | 无（上游池含实测返回空响应的模型，故不拉） | `ZCODE_FALLBACK_MODELS`（glm-5.3-flash 等） | `src/zcode-product.ts:139-196`；`src/index.ts:1056-1058` |

**统一读取路径**（每个适配器三处一致）：
`listModels()`（门控 → ensureRemoteModels → 兜底 → 黑名单过滤 → 播报）/ `listAllModels()`（全量、不套黑名单，供设置页）/ `resolveModel()`（元数据三级查找）。逐适配器行号见 §2.3 表。

### 1.2 元数据字段来源（逐字段）

| 字段 | 来源与优先级 | 证据 |
|---|---|---|
| 上下文窗口 `context.contextWindow` | 远端 `maxInputTokens`/`context_length`/`max_input_tokens` → 产品兜底表 → 通用静态表；**未知一律不编造** | `src/buddy-adapter.ts:1070-1074`；`src/qoder-adapter.ts:569-571`；`src/loomy-adapter.ts:314-318` |
| 单次输出上限 `defaultMaxTokens` | 远端 `maxOutputTokens`/`max_tokens` → 兜底表；非法/缺失保持 undefined（编造偏大值会被上游 400） | `src/buddy-adapter.ts:1095-1098`；`src/zcode-adapter.ts:311-312` |
| 图片 `inputModalities` | 按模型判定：兜底表 `supportsImage` / 远端 `multimodal` / `capabilities.input_modalities` / `tags` 含 vision；**未声明保守报 `['text']`** | `src/buddy-adapter.ts:977-985`；`src/loomy-adapter.ts:122-129,161`；`src/raccoon-auth.ts:180`；`src/trae-adapter.ts:825-827` |
| 思考档位 `reasoning.efforts` | 远端（`reasoning_efforts` / `thinking_config.enabled.efforts` / `reasoning_effort_config` / `reasoning.levels`）→ 兜底表；**`defaultEffort` 必须落在 efforts 内**否则不发 | `src/loomy-adapter.ts:55-68,339-352`；`src/qoder-adapter.ts:572-590`；`src/zcode-adapter.ts:330-350`；`src/trae-adapter.ts:714-742` |
| 工具支持 | **不作为模型元数据播报**；`supportsToolCall` 一类字段在 DSH 契约里不存在（由 harness 直接下发 tools 字段），codearts 的 DSML 模式是适配器内部行为 | `src/llm-adapter.ts:167-200`（DSML）；无任何 `LlmModelInfo` 工具字段产出点 |
| 计费倍率/免费标记 | 只进**展示名 `name`**（` · x0.75` / ` · 免费`），`description` 仅 `/model` 弹窗用；`resolveModel().name` 刻意**不带**倍率 | `src/buddy-adapter.ts:2138-2187`；`src/trae-adapter.ts:570`；`src/cline-models.ts:96-109`；`src/zcode-adapter.ts:227-229` |
| 目录门控（非元数据） | `providerCatalogVisible`：无已登录账号 → 整个 provider 分组隐藏；`DSH_HIDE_MODELS_WITHOUT_ACCOUNT` 默认开（仅 `0/false/no/off` 关） | `src/account-pool.ts:892-919`；`src/llm-adapter.ts:798-812` |

### 1.3 模型开关与过滤（黑名单制）

- **黑名单语义：只有键存在且为 `true` 才隐藏；打开时删键**（不写 `false`），因此表中出现的模型默认可见。`src/account-pool.ts:162-243`（`disabledModelsFor` / `listDisabledModels` / `setModelDisabled` / `setModelsDisabled` / `clearDisabledModels`）。
- 存储：`$DSH_HOME/jet-hub/state.json` 的 `disabledModels: Record<provider, Record<modelId, true>>`（0.1.7 起；≤0.1.6 仍在 settings 文档）。`src/jet-hub-store.ts:45-82,302-345`。
- 过滤点唯一：各适配器 `listModels()` 内实时 `filter(m => !disabled.has(m.id))`（**不改变 resolveModel/stream 的路由能力**——目录是建议性的）。`src/llm-adapter.ts:817-824`。
- 管理面读全量目录（含被关闭项）走 `listAllModels()`，否则被关闭模型连同开关一起消失、用户无法重开。`src/jet-hub-rpc.ts:2303-2340`（注释即该缺陷根因）。
- **`plugin-src/client/model-filter.js` 与 `model-bulk.js` 不是黑名单**：前者是 UI 搜索/状态筛选纯函数（`filterModels`/`normalizeStatusFilter`，`model-filter.js:38-105`），后者是「打开全部/关闭全部」按钮的禁用判定（`model-bulk.js:22-33`），二者供 `plugin-src/client/jet-hub.js:804-813` 使用。
- 批量开关：`model.setAllDisabled`，语义刻意不对称（关=按当前目录逐项入黑名单；开=清空该 provider 全部键，不读目录，`src/jet-hub-rpc.ts:2376-2393`）。

### 1.4 归一化数据结构

**宿主契约侧（来自 `@deepseek-ai/dsh-llm`，仍无类型文件可读，字段从产出/消费点反推）**：
- `LlmModelInfo`：`{ provider, id, name, inputModalities }`（部分适配器还带 `description`，如 cline `src/cline-adapter.ts:334`）。
- `LlmResolvedModelInfo`：`{ provider, id, name, inputModalities, context?: {contextWindow}, defaultMaxTokens?, reasoning?: {efforts:{id,name}[], defaultEffort?} }`（如 `src/buddy-adapter.ts:1075-1116`）。
- `StreamChunk`：判别联合 `block-start / text-delta / reasoning-delta / tool-call-delta / block-end / usage / finish`（产出点 `src/openai-compat.ts:727,757,796,801,843-868,936,1015,1036,1176` 与 `src/llm-adapter.ts:1215-1729`）。
- 本插件自有类型：`ProviderAccountEntry`（含 `modelRateLimits`、`traeCheckinDeviceGeneration`）在 `src/types.ts:42-76`；`JetHubState` / `ModelDisableMap` / `PermanentLockMap` 在 `src/jet-hub-store.ts:45-82`；备份载荷 `BackupPayload`/`BACKUP_FORMAT` 在 `src/types.ts:603-665`。

**产品配置对象（每个 provider 一个，是「目录 + 能力」的静态快照）**：
`BuddyProduct`（`src/product.ts:74-144`）、`QoderProduct`（`src/qoder-product.ts:305`附近）、`TraeProduct`、`LobsteraiProduct`、`ClineProduct`、`LoomyProduct`、`RaccoonProduct`、`ZcodeProduct`。字段族一致：`id/displayName/apiBase/defaultCredentialRef/fallbackModels/…`。

---

## 2. 提供给 dsh 的机制链

### 2.1 插件注册（cordis）

- 插件条目：`cordis.patch.yml` → `id: codearts-auth` / `name: 'dsh-codearts-auth'`；`package.json:62-64` 的 `dsh.bundle.patch` 指向它。
- 三件套：`name='codearts-auth'`（`src/index.ts:47`）、`inject=['credentials','commands','llm']`（`src/index.ts:55`，`connection` 刻意惰性注入，`src/index.ts:48-54` 是真实启动失败复盘）、`apply(ctx)`（`src/index.ts:193`）。
- 每个 provider 的注册函数（9 个文件、11 次调用）：`registerCodeArtsLlm`（`src/llm-adapter.ts:1783-1800`）、`registerBuddyLlm`（`src/buddy-adapter.ts:2211-2221`）、`registerLobsteraiLlm`（`src/lobsterai-adapter.ts:1706-1716`）、`registerQoderLlm`（`src/qoder-adapter.ts:1130-1140`，qoder 与 qodercn 共用）、`registerTraeLlm`（`src/trae-adapter.ts:1817-1828`）、`registerClineLlm`（`src/cline-adapter.ts:683-693`）、`registerLoomyLlm`（`src/loomy-adapter.ts:551-561`）、`registerRaccoonLlm`（`src/raccoon-adapter.ts:496-506`）、`registerZcodeLlm`（`src/zcode-adapter.ts:688-698`）。
- 服务注册：每个产品的 `XxxAuth extends Service`（`ctx.codeartsAuth` / `buddyAuth` / `workbuddyAuth` / `lobsteraiAuth` / `qoderAuth` / `qoderCnAuth` / `traeAuth` / `clineAuth` / `loomyAuth` / `raccoonAuth` / `zcodeAuth`）。
- 自定义服务：`ctx.provide('accountPool', pool)`（`src/index.ts:1226`）；适配器实例另经 `modelAdapters` 手工传给 Jet Hub（`src/index.ts:1209-1225`），因为 `ctx.llm` **不透传自定义方法**（`listAllModels` 只能这样传出，`src/index.ts:1206-1208`）。

### 2.2 调用路径（宿主 → 适配器）

`LlmRuntime.prepareCall(provider, model, signal)` → 适配器 `prepareCall` 返回 `{ model: LlmResolvedModelInfo, stream: (options)=>AsyncIterable<StreamChunk> }` → 宿主 `for await` 消费。
11 个适配器全部实现同一组方法（覆写集）：`providerInfo` / `listModels` / `resolveModel` / `prepareCall` / `stream`，行号见 §2.3；`prepareCall` 是「兼容 0.1.1-rc.2」的 shim（如 `src/cline-adapter.ts:371-387` 注释），当前仍全部保留。
响应侧：`stream()` 内部 fetch 上游、解析 SSE、`yield StreamChunk`；给宿主的一侧**全是内存对象**，无序列化边界（`src/openai-compat.ts:400-1176`、`src/llm-adapter.ts:848-1729`）。

### 2.3 `resolveModel`：模型名 → 产品 + 账号 + 上游模型 id

- **只解析元数据，不解析账号**。provider 即「产品」（由注册时的路由名决定，`product.id` 或常量 `PROVIDER`）。
- 元数据三级查找示例：`remote → productFallback → 通用静态`（`src/buddy-adapter.ts:1070-1074`）；纯兜底表版本见 `src/qoder-adapter.ts:561-592`、`src/zcode-adapter.ts:292-352`。
- **上游模型 id 直通，不做重命名映射**：`model: options.model` 原样进请求体（trae `src/trae-adapter.ts:955`、zcode `:511,515`、raccoon `:389`、loomy `:459`、cline `:440`）；qoder 用 `modelKey: options.model`（加密端点认目录 key，`src/qoder-adapter.ts:712`）；trae 额外有「model → 通道」二级映射 `channelFor()`（`src/trae-adapter.ts:658-669`）。
- 账号在 `stream()` 内运行时解析：由 `src/index.ts` 注入的 `resolveCredential(modelId)` 闭包 → `pool.getAvailableAccount(product.id, modelId, exclude)`（`src/index.ts:366-390`（buddy）、`411-434`（workbuddy）、`453-468`（lobsterai）、`519-542`（qoder）、`585-598`（qodercn）、`629-643`（trae）；loomy 为分档选号 `:755-817`）。`modelId` **必须透传**，否则模型级限流过滤短路（`src/account-pool.ts:666-672`；各调用点均有注释，如 `src/index.ts:378-381`）。

### 2.4 排队 / 限流 / 账号降级（用户点名「model-queue」的真实语义）

⚠️ **`src/model-queue.ts` 不是并发队列/限流器**，而是 **Qoder 上游「排队业务码 10605」的解析与等待策略**（`src/model-queue.ts:1-33` 头部注释）：
- 常量：`QUEUE_BUSINESS_CODE='10605'`、`BILLING_BUSINESS_CODE='110'`、`QUEUE_MAX_DELAY_MS=10_000`、`QUEUE_MAX_ATTEMPTS=180`（`:36,73,138,141`）；
- `parseQueueError` 二次解析 `message` JSON 字符串（`:188-237`）、`queueDelayMs` 取值优先序并封顶 10s（`:248-255`）、`nextUtc8DayStartMs` 固定 UTC+8 日界（`:109-115`）。
- 消费方：`openai-compat.ts` 的 SSE 消费器（HTTP 200 + 流内 `{code:10605}` 帧 → 抛 `ModelQueuedError`，`src/openai-compat.ts:331-346`）与 `qoder-adapter.ts` 的 HTTP 403 分支（`src/qoder-adapter.ts:791-816,846-895`）。

**真正的限流/降级机制分四层**：

| 层 | 机制 | 证据 |
|---|---|---|
| L1 选号过滤 | `getAvailableAccount(provider, model, exclude)`：`enabled` → 排除 `exclude` → 排除 `modelRateLimits[model]` 未过期的账号；**候选顺序 = 用户拖拽顺序**（不再按到期时间重排） | `src/account-pool.ts:658-718,674-684` |
| L2 失败记账 | 上游限流 → `updateModelRateLimit(账号, 模型, 重置时刻)`；解析不到重置时刻用兜底窗口（`TRAE_RATE_LIMIT_FALLBACK_MS` / `LOBSTERAI_RATE_LIMIT_FALLBACK_MS` / `CLINE_RATE_LIMIT_FALLBACK_MS` 均 1h：`src/trae-adapter.ts:174`、`src/lobsterai-adapter.ts:89`、`src/cline-adapter.ts:595`）；buddy 另有「安全策略拦截」冷却 `BUDDY_POLICY_BLOCK_COOLDOWN_MS = 30min`（`src/buddy-adapter.ts:436-459,515-516`） | 同左 |
| L3 换号重试 | 适配器内 `for(;;)`：记账 → `getAvailableAccount(..., tried)` 取下一个 → 重发；`tried` 保证每账号只试一次，试完才报「所有账号均受限」（`QUOTA_EXCEEDED`）。buddy `src/buddy-adapter.ts:1462-1550`；trae `src/trae-adapter.ts:1045-1132`；qoder `switchAccountOnQuota` `src/qoder-adapter.ts:918-953`（额度标记到 UTC+8 当日 24:00）；codearts `src/llm-adapter.ts:1024-1050` | 见左 |
| L4 余额分档选号 | buddy：按「15 天内到期积分」优先（锁定永久积分时只允许快到期积分），60s 缓存**原料**、每次重新分桶，失败条目 5s 短 TTL；loomy：今日额度 → 永久积分 → 未知，`unknown` 与 `exhausted` 必须分开报 | `src/buddy-balance-selector.ts:1-60`；`src/loomy-balance-selector.ts:188`（`select()`）；`src/index.ts:730-807` |

**CodeArts 另有一套「并发排队」**（会话并发上限 `TM.00001041`）：轮询/直接重试 chat，间隔 10s、上限 180 次（30 分钟），期间**静默不产出 chunk**（`src/llm-adapter.ts:249-260,936-1070`）；SSE 流内限流码（`81111/TPM/429`）同样归入排队重试（`:358-368`）。
**刷新时机**：续期调度 30 分钟一轮 + 启动立即跑一轮（只对距过期 <1h 的账号发请求，其余本地对账；`src/index.ts:1098-1187`，判据在 `src/expiry-sync.ts`）。

### 2.5 流式归一化（StreamChunk ← 各家 SSE）

| 适配器 | 上游流格式 | 转换路径 | 证据 |
|---|---|---|---|
| codearts | OpenAI SSE（+ DSML 三通道分流） | 适配器内联 | `src/llm-adapter.ts:1291-1729` |
| buddy | OpenAI SSE（含 `reasoning_content`） | 适配器内联 `consumeSse` | `src/buddy-adapter.ts:1606` |
| lobsterai | OpenAI SSE | 适配器内联 `consumeSse` | `src/lobsterai-adapter.ts:1207` |
| trae | 自定义 SSE（跨行 event+data 成帧） | 适配器内联 `consumeSse` | `src/trae-adapter.ts:1223` |
| qoder/qodercn | 信封套 OpenAI SSE | `unwrapQoderEnvelopeStream` → `consumeOpenAiSse` | `src/qoder-adapter.ts:846-855` |
| cline / loomy / raccoon | OpenAI SSE | `consumeOpenAiSse` | `src/cline-adapter.ts:553`；`src/loomy-adapter.ts:521`；`src/raccoon-adapter.ts:466` |
| zcode | **Anthropic Messages SSE** | `consumeAnthropicSse`（`src/zcode-anthropic.ts:362`） | `src/zcode-adapter.ts:607` |

**共享工具库 `src/sse.ts`（1181 行，已从「SSE 读取」扩为「响应归一化工具集」）**：`readWithIdleTimeout`:28（机制在此，**超时值逐适配器自定**：codearts 300s/600s（`src/llm-adapter.ts:288-293`），buddy/cline/qoder/loomy/raccoon/trae/lobsterai 均 120s/120s（`src/buddy-adapter.ts:682-687`、`src/cline-adapter.ts:136-141`、`src/qoder-adapter.ts:374-378`、`src/loomy-adapter.ts:531-539`、`src/raccoon-adapter.ts:476-484`、`src/trae-adapter.ts:166-171`、`src/lobsterai-adapter.ts:693-698`），各自有 `DSH_<PROVIDER>_SSE_*` 环境变量可覆写——**`03` 的「首 token 5min / chunk 10min」只对 codearts 成立**）、`resolveToolPairing`:244、`normalizeToolArguments`:291、`isTruncatedArguments`:324、`hasUsableToolName`:81、`createReasoningLoopDetector`:481（思考/正文**两实例**，正文只截断不 cancel 以保住后续 tool-call）、`splitThinkTaggedContent`:768、`stripCourseLeak*`:924-1069、`createBlankReasoningSuppressor`:159、`resolveEmptyResponseReason`:132。
**`message-shape.ts`（新增，146 行）**：把 DSH 0.1.7 的「工具结果 = 一等 `role:'tool'` 消息」**降级**回 ≤0.1.6 的 `tool-result` 包裹块，否则五个序列化实现的判据恒不命中 → 工具调用被整体剔除（实测 512 条工具调用在 0.1.7 形状下保留 0 条）。`src/message-shape.ts:1-40,82-146`。`StreamChunk` 产出方向**逐字节未变**（`:12-14`）。

### 2.6 错误映射词表（仍由 `LlmError.code` 表达）

`MISSING_CREDENTIAL` / `AUTH` / `RATE_LIMIT` / `INVALID_REQUEST` / `SERVER` / `TRANSPORT` / `TIMEOUT` / `UNSUPPORTED_CONTENT` / `QUOTA_EXCEEDED` / `EMPTY_RESPONSE` / `QUEUE`（本插件新增，`src/openai-compat.ts:341`）/ `CONTEXT_WINDOW_EXCEEDED` / `REASONING_LOOP`（`src/sse.ts:367`）。域名映射见各 `*-errors.ts`（如 `src/lobsterai-errors.ts`、`src/trae-adapter.ts:508-515`）与 `src/openai-compat.ts:299-330`。

---

## 3. 对外可用性（Jet Hub / management-rpc）与进程边界

### 3.1 通道与鉴权（复核：结论未变）

- 路径 `POST /api/jet-hub`（`src/jet-hub-rpc.ts:144,768-771`），由 `ctx.connection.fetch.register` 交给宿主挂载（`:653-659,719-723`），**只在 Web profile 存在**，headless 下只打一条 warn 不注册（`:625-627`）。
- 入站校验仅四道：405 方法 / 415 content-type / 400 非 JSON / RPC 信封结构（`:773-797`）。**无任何鉴权代码**（`03` 的该结论仍成立；全文 grep `authorization|bearer|api key` 无入站校验点）。
- 信封：请求 `{type:'client-request', rpcId, method:'jet-hub', payload:{method,payload}}`，响应 `{type:'server-response', rpcId, result}`（`:790-796` + `reply()`）；客户端封装 `connection.rpc.call('/api','jet-hub',{method,payload})`（`plugin-src/management-rpc.mjs:26`）。

### 3.2 方法清单（26 个，`handleMethod` switch）

`account.list`:818 / `account.create`:824 / `account.update`:1216 / `account.delete`:1222 / `account.reorder`:1230 / `account.refresh`:1254 / `login.poll`:1341 / `login.sendSms`:1363 / `login.submitSms`:1383 / `onboarding.status`:1437 / `credits.permanentLock`:1502 / `loomy.permanentLock`:1507 / `onboarding.claim`:1558 / `account.retest`:1627 / `account.retestAll`:1638 / `account.reset`:1645 / `account.resetAll`:1651 / `credits.status`:1672 / `credits.claimAll`:1750 / `credits.balances`:1958 / `model.list`:2287 / `model.setDisabled`:2358 / `model.setAllDisabled`:2393 / `backup.export`:2448 / `backup.import`:2460 / `backup.status`:2479。
**仍然不含任何 chat/completions**；无 `chat.*` 方法（对照 `03` §5.2 的 16 个 → 现 26 个，全部是账号/运营/模型开关/备份）。
⚠️ 注意文件头注释（`:1-13`）只列了 18 个方法——**注释清单本身已滞后**（漂移点）。

### 3.3 模型目录出口 `model.list` 的数据源（复核 + 变化点）

`models = await llm.listModels(provider)`（已过滤黑名单）→ `disabledMap = pool.listDisabledModels(provider)` → **优先用适配器 `listAllModels()` 的全量目录**，缺失才退化为「listModels + 黑名单裸 id 补回」→ 合成 `{id,name,disabled}`（`src/jet-hub-rpc.ts:2287-2349`）。
变化点：`llmServiceOf(ctx)` 走 `ctx.get('llm')`（`:610-619`），模型目录与「设置页显示的集合」始终同源；写入黑名单后必须 `emit('llm/adapters-updated')` 广播，否则客户端缓存（`ModelCatalogDirectory` 的 `status==='ready'` 短路）不会刷新（`:670-699,2367-2368`）——这是 `03` 没有的机制（当时黑名单还在 settings 文档、写 settings 会触发客户端事件）。

### 3.4 判定：能否被「别的工具」消费

| 消费方 | 能/否 | 依据 |
|---|---|---|
| 同宿主另一插件 | 能（进程内） | `ctx.llm.listModels(provider)`；`ctx.get('accountPool')`（`src/index.ts:1226`，非标准契约）；11 个 `XxxAuth` Service |
| 任意第三方程序（Trae/Cursor/Cherry Studio） | **不能（协议面）** | 输出面是 TS 对象 + `AsyncIterable`；无 OpenAI 端点；全仓唯一对外路由是 `/api/jet-hub`（无 chat）；`createServer/listen` 仅存在于三个 OAuth 本地回调（`src/login.ts:219,348`、`src/lobsterai-oauth.ts:348`、`src/trae-oauth.ts:503,604,723`，均绑 `127.0.0.1`） |
| 另一个独立网关（我们） | **不能直接接；但可绕行** | 见 §3.5 |

### 3.5 「产品内部模型 → 网关 → 外部软件」的三条可行路径

1. **复刻上游协议直连（推荐）**：插件对每家上游的协议逆向量已极完整（每产品一个 `*-product.ts` 描述基址/头/路径/模型表/风控常量），照抄即可在 Python 网关侧直连，不需要插件运行。先例：仓库 e2e 探针就是普通 Node 进程直连上游（`tests/e2e/*-probe.e2e.spec.ts`，26 个探针 / e2e 共 32 个 spec）。
2. **读盘拿凭据 + 复刻协议**：插件把凭据明文存 `~/.dsh/.credentials.yaml`（`tests/e2e/workbuddy-credential.ts:28`），账号索引/黑名单存 `$DSH_HOME/jet-hub/state.json`（`src/jet-hub-store.ts:302-345,396-404`，`DSH_HOME`/profile home 可覆盖）。e2e 探针已按此路径读取 `QODER_ACCOUNT_*` / `LOOMY_ACCOUNT_*` 等 ref 并发真实请求（`tests/e2e/qoder-credential.ts:97`、`tests/e2e/loomy-credential.ts:71`）——**「进程外消费」在本仓库已有既成事实**。代价：凭据刷新由 DSH 宿主完成，网关只能搭便车；插件升级会改 ref/字段形态。
3. **把 Jet Hub RPC 当管理面**（仅探索性）：需要伪造 DSH Web 会话进宿主，无 chat、无鉴权、非稳定协议，**不建议**。

> **给网关的结论**：不要设计「DSH 插件 → 网关」的在线对接；应把 DSH 当作**协议情报与运营逻辑的来源**，在网关侧自建适配器（对齐 ①），必要时提供一次性导入工具读盘移植账号（对齐 ②，属本地个人使用场景，无远程下发）。

---

## 4. 增量与漂移（相对 `03`）

### 4.1 已漂移 / 需修订的结论

| # | `03` 的结论 | 2026-09-29 事实 | 依据 |
|---|---|---|---|
| 1 | 「6 个 provider / 5 个适配器」 | **11 provider / 9 个适配器类**（qoder+qodercn 共类、buddy+workbuddy 共类）；新增 cline/loomy/raccoon/zcode | `src/index.ts:209-212,233-1063` |
| 2 | `openai-compat.ts`「实际使用点只有 qoder 一处」 | **4 处**：qoder / cline / loomy / raccoon；头部注释仍写「给 qoder 使用」 | `src/cline-adapter.ts:553`、`src/loomy-adapter.ts:521`、`src/raccoon-adapter.ts:466`、`src/qoder-adapter.ts:846` |
| 3 | 「3 套消息序列化 + 5 套 SSE 消费」（技术债） | 序列化仍 3 套（openai-compat / codearts 内联 / trae 内联）；SSE 消费仍 5 套（+4 个走 openai-compat 的适配器），**但 `sse.ts` 已升格为共享工具库并被 openai-compat 与 codearts 同时引用**——技术债正在被收敛而非扩大 | `src/openai-compat.ts:39-57`、`src/llm-adapter.ts:14` |
| 4 | 管理面「无鉴权、只在 Web、专有信封、不含 chat」 | **全部仍成立**；新增：备份导出经 RPC 返回**全量明文凭据**（客户端再做口令加密下载，`plugin-src/client/backup-crypto.js:1-16,26-42`） | `src/jet-hub-rpc.ts:768-813,2448-2483`；`src/backup.ts:77-113` |
| 5 | 模型目录「远端→缓存→兜底」三级 | 结构不变；**新增 provider 用「合并」而非「回退」**（cline：远端 free 集合 + 兜底 + 460 条远端 id 四段合并，兜底表排在远端大列表之前） | `src/cline-models.ts:180-235` |
| 6 | 「同一 provider 内同名消歧」 | 机制保留（buddy `displayNameFor/variantLabelFor`，`src/buddy-adapter.ts:2138-2187`）；**新增免费/倍率标记族**（cline「· 免费」、raccoon「· x原价→x折后价」、trae「x0.80→x0.08」） | 同左 + `src/trae-adapter.ts:570-583` |
| 7 | `listAllModels()` 是「非契约方法，唯一理由=设置页显示被关闭模型」 | 结论不变；**理由扩为两条**：显示被关闭模型 + 保留倍率/免费标记的最终展示名（11 个适配器全部实现） | `src/jet-hub-rpc.ts:2303-2320`；`src/cline-adapter.ts:289-306` |
| 8 | 管理面方法 16 个 | **26 个**（新增 sms 登录两段式、onboarding、permanentLock×2、setAllDisabled、backup×3） | `src/jet-hub-rpc.ts` case 清单 §3.2 |
| 9 | 「空闲超时 = 首 token 5min / chunk 10min」 | **只对 codearts 成立**（300s/600s）；其余 7 家默认 **120s/120s**，且各家有独立 `DSH_<PROVIDER>_SSE_*` 环境变量 | `src/llm-adapter.ts:288-293` vs `src/buddy-adapter.ts:682-687` 等（见 §2.5） |

### 4.2 仍然成立的结论（复核通过）

- 「聚合发生在宿主的 catalog 层，不在插件里」——插件只按 provider 贡献分组，宿主的 `buildModelCatalog` 汇总（`src/account-pool.ts:550,865-870`、`src/llm-adapter.ts:798-802` 注释仍在；⚠️ `03` 所引 `account-pool.ts:717-722` 的行号已漂移）。
- 输出面 = 进程内 `AsyncIterable`；网络只在上游方向。
- `model id 即上游 id`（无重命名映射层）——除 qoder 的 `modelKey` 与 trae 的通道二级映射。
- 管理页面板与对话框模型选择器同源（都读 `listModels`），但**客户端的目录缓存必须靠 `emit('llm/adapters-updated')` 主动失效**，否则开关只写进磁盘、界面一直显示旧目录（`src/jet-hub-rpc.ts:670-699,2367-2368`，真实缺陷复盘）；`providerCatalogVisible` 的「必须返回 `[]` 不能抛错」等设计约束逐条仍在。
- `StreamChunk` 判别联合的成员集合未变（0.1.5→0.1.7 逐字节未变，`src/message-shape.ts:12-14` 明述）。

---

## 5. 可借鉴 / 不可借鉴（对照我们的 /v1/models 能力位、调度选路、出站适配器）

### 5.1 可借鉴

| # | 借鉴点 | DSH 做法（证据） | 对我们（Model-Gateway）的落点 |
|---|---|---|---|
| 1 | **能力位 = 适配器自播报，未知不编造** | 每个适配器在 `resolveModel()` 里声明 `context/defaultMaxTokens/reasoning`，未知字段**留空**交给宿主默认；理由注释「编造偏大值会被上游 400 拒绝」 | Q25-② 能力位下发口径一致（camelCase + `caps.thinkingLevelMap`）；补一条纪律：**取不到就不写该字段**，不填猜测值 |
| 2 | **黑名单制 + 全量目录双出口** | `listModels`（过滤）/ `listAllModels`（全量，供管理页）；打开=删键 | 我们的 `/v1/models` 只下发可服务模型（Q28-② 已定）；管理页需另设「全量目录」读口，否则「关闭的模型再也开不回来」——这条缺陷在 DSH 是真实用户报障 |
| 3 | **展示名承载运营信息，`id` 保持纯协议值** | 倍率/免费/变体标记拼进 `name`（` · 免费`、`x0.75→x0.1`），`resolveModel().name` 不带；选择与持久化只用 `id` | 我们 `/v1/models` 的 `name` 可显示倍率/免费标记而不污染 `model` 字段；同名 vendor 消歧用公共前缀法（`commonPrefix`） |
| 4 | **目录三段式：远端探测 → 磁盘缓存 → 本地兜底** | codearts 有 2h 刷新 + `~/.cache/deveco/*.json` 缓存 + 静态兜底（`src/models.ts:57-58,159-227`） | 我们已有 `BUILTIN_ENTRIES` 目录层（Q25-① L-B）；可补「远端 `/models` 探测 + 落盘缓存」以自动发现厂商新模型，失败不阻断 |
| 5 | **选号顺序 = 用户拖拽顺序，限流豁免** | 「手动顺序优先，限流豁免」（`src/account-pool.ts:674-684`）——早期按重置时间重排会让拖拽形同虚设 | 我们资源池选路（`resources.py pick_and_acquire`）可评估同一语义：顺序显式可控 + 失效/受限资源自动跳过 |
| 6 | **换号重试骨架**：`tried` 集合 + 每账号只试一次 + 试完才报错 + 非限流错误分类抛出 | buddy `1462-1550`（含「安全策略拦截也要继续换号」的真实缺陷复盘）、qoder `918-953`（标记落到「本次实际使用的账号」） | 与我们 fallback（失败 N 次切换）同类；两点可直接抄：① 换号时**必须排除刚失败的账号**；② 标记要落「本次实际使用的资源」而非「池的默认资源」 |
| 7 | **写盘纪律：整份快照 + 读-改-写 + 原子写（tmp+rename）** | `src/jet-hub-store.ts:336-345`、`src/account-pool.ts:720-745`（并发更新会互相覆盖的真实教训） | 与我们 `data/` 的配置写盘/热重载纪律对齐（Q25-⑥ 合规提示已吸收） |
| 8 | **`sse.ts` 工具库可整段移植**（Python 重写） | 工具配对自愈、参数截断判定、空思考抑制、死循环守卫（正文只截断不 cancel）、`think` 标签跨帧切分 | 出站/入站解析共用；其中「残缺参数不补 `{}` → 判 max-tokens 让上层重试」对我们 agent 场景价值最高 |
| 9 | **产品配置对象化**（一产品一 `*-product.ts`，差异全收敛） | 11 个 provider 里同类协议（buddy/workbuddy、qoder/qodercn）零复制实现 | 我们「加一家 OpenAI 兼容厂商不改代码」的渠道配置层可直接对照该范式 |
| 10 | **e2e 探针 = 进程外直连上游的最小实现** | `tests/e2e/*-credential.ts` 从 `.credentials.yaml` 读参、`*-chat-probe` 直发请求 | 若我们做「导入 DSH 账号」，这些文件就是现成的字段映射与握手参照（属导入工具，不是在线对接） |

### 5.2 不可借鉴

| DSH 形态 | 为什么不适用 | 证据 |
|---|---|---|
| 进程内 `AsyncIterable<StreamChunk>` 作为对外契约 | 我们是独立进程 + HTTP，必须有序列化边界；且反向编码器（StreamChunk→OpenAI SSE）在其仓库**不存在** | `src/llm-adapter.ts:848`；全仓无 `chat.completion.chunk` 产出 |
| `(provider, modelId)` 二元组寻址 | OpenAI 兼容面只有单一 `model` 字符串；我们必须有「系统模型名 → 多厂商资源」映射层（这正是网关价值） | `src/llm-adapter.ts:798,824` |
| 管理面无鉴权、挂宿主内嵌路由 | 我们的管理端虽在本机，但已有 `api/auth.py` 硬要求；且宿主 profile 依赖不可复制 | `src/jet-hub-rpc.ts:773-797` |
| 凭据绑 `ctx.credentials` + 明文 YAML | 我们要求密钥只存本地明文配置/环境变量且**不入库**；DSH 的 `.credentials.yaml` 可读只是一个「本机导入」事实，不是可以照抄的存储设计 | `tests/e2e/workbuddy-credential.ts:28` |
| profile 条件注册（Web vs headless） | 我们单一形态；但要记住其教训：**可选依赖不得让整个服务启动失败**（`connection` 惰性注入的复盘） | `src/index.ts:48-54` |
| 依赖宿主客户端缓存语义（`llm/adapters-updated` 广播） | 我们的前端是本仓静态页 + 明确刷新契约，不需要复制事件总线 | `src/jet-hub-rpc.ts:670-699` |

---

## 6. 未验证清单

| # | 未验证项 | 卡点 | 影响 |
|---|---|---|---|
| 1 | `@deepseek-ai/dsh-llm` 的 `LlmAdapter` 基类完整方法集与 `LlmModelInfo`/`LlmResolvedModelInfo`/`StreamChunk` 的**类型声明** | `node_modules/`、`lib/` 本机均不存在（`ls` 确认）；peerDependencies 只声明 `^0.1.2-rc.1 \|\| ^0.1.7-rc.2 \|\| ^0.2.0-rc.1`（`package.json:70-76`） | 字段清单来自 11 个适配器的产出/消费点反推；可能存在未被任何适配器使用的字段（如工具能力位） |
| 2 | DSH 宿主在 0.1.7/0.2 下是否给 `connection.fetch` 加统一鉴权/来源限制 | 宿主包不在本机 | §3.1「无鉴权」仅指**本仓库内无鉴权代码** |
| 3 | `connection.fetch.register` 是否支持中间件/auth 参数 | 同上 | 同上 |
| 4 | `.credentials.yaml` 的真实路径解析（profile home / `DSH_HOME`）在 e2e 之外的行为 | e2e 硬编码 `~/.dsh`（`tests/e2e/workbuddy-credential.ts:23-28`），未处理 `DSH_HOME` 覆盖；`jet-hub-store.ts:396-404` 的四级优先级只在插件侧实现 | §3.5 路径 2 的落盘位置需以实机 `ls` 核实（本轮只读未跑） |
| 5 | zcode 的「静态白名单 2 条」是否覆盖用户全部可用模型 | `src/index.ts:1056-1057` 注释说明上游池含实测返回空响应的条目，故不枚举 | 影响 zcode 接入时的模型数（可作 2 条起） |
| 6 | qoder 目录端点「需 WASM 签名」的结论在 2026-09-29 版本上是否仍成立 | 本轮未复核 `src/qoder-wasm.ts` 与 `qoder-machine.ts` 的完整逻辑（只看了 `qoder-adapter.ts:512-550`） | 若网关要接 qoder，需另立一篇（qoder 是唯一未接远端目录的大户） |
| 7 | 各 provider 远端目录的**真实响应字段全集** | 只读代码，未发任何网络请求（硬约束） | 元数据字段以代码解析点为准；字段可能有余量 |
| 8 | 26 个 RPC 方法的入参/出参**逐字段** | 仅抽读 `model.list` / 注册段 / 方法行号；运营类（onboarding/credits）留给 `research/20` 号文档 | 本文不对运营面出结论 |

**方法说明**：所有结论来自 `src/`、`plugin-src/`、`tests/e2e/`（只读）与两次快照的 `git diff`；未运行其代码/测试，未发网络请求。凡涉宿主行为处均标注为注释描述或推断。

---

## 7. 零改动证明

> 材料目录全程只读（仅 Read/Grep/Glob/ls/git 只读命令）；未运行其代码/测试，未发任何网络请求。Model-Gateway 侧本次仅新建本文件（未改源码/测试/`data/`，未访问 127.0.0.1:8300）。结束前执行：

```
$ git -C "/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts" status --porcelain
（无输出）

$ git -C "/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts" rev-parse HEAD
a3fe5f2d820f9e790723e5956b3307af709ddaa3
```
