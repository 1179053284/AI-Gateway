# 01 · DSH 插件的「多平台授权接入 → 调用平台内部模型 → 转接外部使用」机制

> ## ⚠️ 行号基线漂移声明（2026-09-22 发现并已处理）
>
> **本文 DSH 侧的行号锚定于提交 `397972908855bc458ef240d39ed24c1922a3a751`。该提交现已从仓库历史中消失。**
> 参考仓库于 2026-09-22 被**重建**（新 HEAD 提交信息：`snapshot: 上游 gitee master b3a95615c（经 API 重建，逐文件 blob sha 校验一致）`），
> 现行 HEAD 为 **`d4613614f15884d1c7cd087e73a2aee6b17f2c0c`**，且 `3979729` **不是** HEAD 的祖先（历史被重建，非快进）。
>
> **影响与处置**：
>
> | 文件 | 旧基线行数 | 现行行数 | 变化 | 已重锚的关键行 |
> |---|---|---|---|---|
> | `src/index.ts` | 471 | 430 | −41 | 26→**25** / 34→**33** / 122→**121** |
> | `src/llm-adapter.ts` | 约 1450 | 1550 | +100 | 822→**835** / 1441→**1454** / 1445→**1458**（10 / 14 / 726 **未变**） |
> | `AGENTS.md` | 1260 | 1379 | +119 | 874→**984** / 121→**152** |
> | `package.json` | 83 | 83 | 0 | 6 / 8 / 55 / 66 **未变** |
> | `README.md` | 1122 | 1161 | +39 | 46 / 59 **未变** |
> | `docs/lobsterai-integration-plan.md` | — | 1728 | — | 131 / 136 / 144 **未变** |
> | `docs/adding-a-new-provider.md` | — | 560 | — | 338–342 **未变** |
>
> ✅ **全部核心结论已在新基线上复核，实质未变** —— 远端端点常量（`CHAT_API_BASE`）、`stream()` 签名、两个注册调用（`registerConfigurableProviders` / `registerAdapter`）、Cordis 三导出、同进程事故记录**均仍在，仅行号位移**。
> ⚠️ **但本文其余 DSH 侧行号可能仍有偏移** —— 引用时请**按内容检索定位**（`grep -n '<关键词>' <文件>`），不要只信行号。
> 📌 **教训**：`git status` 干净 **≠** 基线未变 —— 必须比对 `git rev-parse HEAD` 与文档声明的基线。

> ## 🔴 读本文前必读（合规前置，2026-09-22 补）
>
> **本文描述的是"逆向形态"（即 `00` 号文档 §六·零 定义的 ②-b）的机制** —— 提取工具客户端**内部登录凭据**、**冒充官方客户端**调用其内部端点。
>
> **`05` 号文档已逐条判定：三家初期平台（CodeBuddy / WorkBuddy / TRAE）的 ToS 均明文禁止这种做法。** 照本文实施 = 条款违规。
>
> | 你想做的事 | 该读什么 |
> |---|---|
> | 了解"平台内部模型能力怎么被提取出来"的**机制原理** | ✅ 本文（知识参考） |
> | **实际接入** CodeBuddy / TRAE | ❌ **不要照本文做** → 走 **②-a 官方授权形态**（CodeBuddy 官方 API Key + Agent SDK；TRAE → 火山方舟）。见 `00` §六·零 |
> | **实际接入** 智谱 | ❌ 不要走逆向 → 走标准 API Key。见 `06` |
> | 确认合规边界 | **必读** `05`（§P1-2 / §P1-4 / §P1-6 是硬约束） |
>
> **本文的定位：机制知识资产，不是施工图。** 可复用的是"**适配器层如何吸收厂商协议差异 + 账号/凭据怎么管**"，不是"怎么逆向登录"。

> 研究对象：`/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts/`（包名 `dsh-codearts-auth`，只读分析，未修改任何文件）
> 分析日期：2026-09-22　｜　**定稿日期：2026-09-22（依 `verify-01-02-dsh.md` 核验报告修订）**
> 证据口径：所有结论均附 `文件:行号`。凡代码中无法确认的，明确标注「未验证」。
> 版本说明：本文件为**修订定稿**。原始草稿保留在 `docs/research/drafts/01-dsh-授权接入与模型转接.md`（未改动，留痕）。全部改动见下方「修订记录」。

---

## 结论先行（摘要）

1. **它不是网关，是宿主插件**。本插件把 6 个平台注册成 DSH 宿主（`@deepseek-ai/dsh`）的 LLM provider 路由，对外接口是 DSH 的 `LlmAdapter` 契约（`listModels` / `resolveModel` / `stream`），**不对外暴露任何 OpenAI 兼容 HTTP 端点**（`src/index.ts:121-430`、`src/llm-adapter.ts:1440-1449`）。要把它改造成独立网关，必须自己写 HTTP 层。
2. **「账号授权」是 5 套完全不同的协议**，共用的是**架构模式**而非代码：`codearts` = PKCE+DPoP 本地回调；`buddy`/`workbuddy` = external-link 轮询；`lobsterai` = 本地回调 + authCode 换 token；`qoder` = PKCE 设备码轮询；`trae` = 本地回调（端口 18080）直接回传 token + ExchangeToken 轮换。**没有任何通用 `oauth.ts` 抽象**——`src/oauth.ts` 只服务 CodeArts（`src/oauth.ts:5-16`）。
3. **真正可复用的抽象只有 4 个**：`RefreshScheduler`（`src/refresh.ts:43-114`）、`AccountPool`（`src/account-pool.ts:124-672`）、产品配置对象（每平台一个平行接口）、SSE/工具配对工具集（`src/sse.ts`、`src/openai-compat.ts`）。
4. **凭据与账号索引分离是核心设计**：凭据本体走 `ctx.credentials`（加密），账号索引/黑名单走 `ctx.settings` 的 `jet-hub` namespace，靠 `credentialRef` 字符串关联（`docs/adding-a-new-provider.md:78-87`、`src/account-pool.ts:114-115`、`src/types.ts:42-75`）。
5. **最重要的三条教训**（都是真实缺陷换来的）：① 续期**不得**按 `enabled` 过滤（`AGENTS.md:136-154`）；② 刷新必须刷「解析凭据时用的那个 ref」，否则刷到另一个凭据上（`src/index.ts:297-313`）；③ 新建账号必须**两步式**先返回 `loginUrl`（浏览器 transient activation 约束，`AGENTS.md:1082-1111`）。
6. **模型命名空间不存在跨平台前缀**：模型 ID 就是平台原生 ID，隔离靠 DSH 的 provider 路由名（`provider: this.product.id`），跨平台同名模型在 UI 层靠「展示名消歧」解决（`AGENTS.md:400-430`）。
7. **账号池没有租约（lease）机制**：`getAvailableAccount` 只是「过滤 + 取第一个」，并发请求会拿到同一个账号；防重复只靠「限流标记 + excludeAccountIds 逐轮换号」（`src/account-pool.ts:532-592`）。
8. **`trae` 与 `qoder` 是「私有协议适配」的两个极端样本**：trae 要 OpenAI→SOLO 请求体重写 + 自定义 SSE 解析（`src/trae.ts:1342-1374`、`:1511-1574`）；qoder 要 WASM 加密请求体 + 响应剥信封（`src/qoder-adapter.ts:286-310`、`src/qoder-envelope.ts:64-140`）。
9. **对我们网关最有价值的三件事**：账号池模型、`RefreshScheduler` 的失败分类与终态判定、两步式登录的 UI 交互契约。
10. **不建议照搬的**：DSH 宿主耦合（`ctx.llm` / `ctx.credentials` / `ctx.settings` / `ctx.connection`）、各平台逆向得来的私有常量与设备指纹伪造、WASM 加密链路。

---

## 修订记录

> 本定稿依据 `verify-01-02-dsh.md` 的核验报告逐条修订。核验的机械校验结论：提取 1027 条 `路径:行号` 引用，**文件不存在 0 条、内容不吻合 0 条**；**机制级结论全部核实为真**，错误集中在「引用的机械精度」「数字 vs 清单不一致」与少量过度推断。下表列出本定稿的全部改动（含核验报告未列、由本次「数字 vs 清单」交叉复核新增发现的自查项）。

### A. 引用与事实修正

| # | 修订条目（草稿原位） | 错误性质 | 修正要点 |
|---|---|---|---|
| A1 | §4.2 `[原 474-475]` 引用块 | **引用失实** | 删除引用块中的 `candidates.sort((a,b) => resetAtA - resetAtB)`。`src/account-pool.ts` 全文 grep `sort` **零命中**，注释仅以散文描述「早期实现如此」。改为对注释的**准确转述**，并显式说明「早期实现的具体写法未保留」 |
| A2 | §4.2 / §9.1 `[原 14、921]` | **引用失实（弱引用）** | 支撑「凭据与账号索引分离」的引用由 `src/account-pool.ts:19`（只有 `JET_HUB_NS` 常量）改为 `src/account-pool.ts:114-115`（`ctx.settings` / `ctx.credentials` 分工注释） |
| A3 | §3.2 `[原 398]` | **引用精度** | 裸行号 `:8-12` 补全为 `src/refresh.ts:8-12`，避免被误归到紧邻上一句的 `src/lobsterai-auth.ts` |
| A4 | §9.3 `[原 934]` | **核验存疑项（已排除）** | 核验报告 V11 对「`src/jet-hub-rpc.ts:1197-1214` 完整缺陷复盘」的措辞强度存疑。本次复读源码确认该区间**确为完整缺陷复盘**（「关掉后彻底找不到该模型」的根因分析），原文保留 |
| A5 | §3.1 `[原 354]` | **语义遗漏** | 补记 `findAccountIdByCredential` 会**跳过已停用账号**（`src/account-pool.ts:423` 的 `!entry.enabled`），与「续期不看 enabled」「探活不看 enabled」形成对照 |

### B. 数字 vs 清单 / 计数修正

| # | 修订条目（草稿原位） | 错误性质 | 修正要点 |
|---|---|---|---|
| B1 | §1.3 `[原 151]` | **数字不符 + 内部矛盾** | 「三个适配器」→ **五个**；引用由 4 条补全为 5 条，并补上被漏掉的 `src/buddy-adapter.ts:863`（该文件正是本句前半段用来解释 shim 出处的文件）。行号改为方法定义行（`:787` / `:739`，原为方法体内行） |
| B2 | §1.1 表 `[原 106-109]` | **数字不符** | 字段数按源码实测更正：`BuddyProduct` ~17 → **15**；`QoderProduct` 14 → **12**；`TraeProduct` 19 → **22**；`LobsteraiProduct` 10 ✅ 不变 |
| B3 | §2.6 `[原 287]`、证据附录 `[原 1078]` | **数字不符 + 内部矛盾** | 「17 参数集」→ **18 参数**（`src/trae-oauth.ts:105-125` 的 `URLSearchParams` 共 18 键，与草稿自列的 18 项清单一致） |
| B4 | §6.2 `[原 656]` | **数字不符**（自查新增） | 「两条注释记录的坑」后接 **3** 个条目 → 改为「三处」（并区分代码注释与 `AGENTS.md` 独立章节两个来源） |
| B5 | §5.1 `[原 542]` | **数字不符**（自查新增） | 「两种模式」后接 5 行 provider 表 → 明确为「两种模式（按下表 5 个 provider 归类）」 |
| B6 | §7.2 `[原 819]` | **数字不符**（自查新增） | 「RPC 端点清单（16 个）」与表格 14 行不直观对应 → 补注「表中 14 行覆盖 16 个端点，`retest`/`retestAll` 与 `reset`/`resetAll` 各合并为一行」 |
| B7 | 参考文档索引 `[原 1217-1222]` | **数字不符** | `docs/adding-a-new-provider.md` 561 → **560** 行；`AGENTS.md` 969 → **1260** 行（原值与草稿自身引用的 `AGENTS.md:1256` 自相矛盾）；`README.md`「1000+ 行」→ **1122** 行；补齐 `lobsterai-integration-plan.md` **1728** 行、`trae-integration-plan.md` **256** 行、`lobsterai-review-findings.md` **344** 行 |

### C. 保留不动的部分（核验已确认正确）

机制描述**逐条核实为真，本定稿一字未改**：`src/oauth.ts` 的 CodeArts 专用性、五套互不复用的认证协议、凭据与账号索引分离、账号池无租约机制、`RefreshScheduler` 的 generation 代号与结构化失效判定、`refresh()` 与 `refreshAccountCredential()` 分工、续期不按 `enabled` 过滤、两步式登录契约、限流解析（6004 + 中英双语正则 + 真实时区）、`listModels`/`listAllModels` 分离、RPC 16 端点单端点分派等。

### D. 定稿机械校验结论

修订完成后对本文档全部 `路径:行号` 引用重新跑了一遍机械校验（文件存在性 + 行号范围）：

| 指标 | 结果 |
|---|---|
| 提取引用总数 | 与草稿 02 合计 **1050** |
| 引用文件不存在 | **0** |
| 真实行号越界 | **0** |
| 脚本归属误判（启发式假阳性） | 1（`[01:19]` 的裸行号 `:1511-1574` 真实归属 `src/trae.ts`，1714 行，未越界） |

**修正后的行号全部可信。** 抽样复验的 15 条关键引用（`src/oauth.ts:5-16`、`src/refresh.ts:8-25`、`src/account-pool.ts:114-115`、`:548-557`、`src/trae-oauth.ts:105-125`、`src/trae-credits.ts:196-208`、`:233-255`、`src/jet-hub-rpc.ts:1039-1055`、`AGENTS.md:1174-1176`、`:1220`、`src/product.ts:74-144`、`src/trae-errors.ts:23-39`、`src/credits.ts:90-94`、`src/lobsterai-credits.ts:42-52`、`src/account-probe.ts:95-103`）均已逐条读源码确认行号与内容吻合。

---

## 架构总览

### 三层 + 账号池（官方口径）

`docs/adding-a-new-provider.md:57-76` 给出官方三层模型，代码完全对应：

```
┌──────────────┐      ┌───────────────┐      ┌────────────────┐
│ 产品配置层    │─────→│ 认证服务层     │─────→│ LLM 适配器层    │
│ product.ts   │      │ xxx-auth.ts   │      │ xxx-adapter.ts │
│ 差异收敛      │      │ 登录/续期/状态 │      │ 目录/解析/转发  │
└──────────────┘      └───────┬───────┘      └────────┬───────┘
                              │                       │
                              ↓                       ↓
                      ┌───────────────────────────────────┐
                      │ 账号池 AccountPool                │
                      │ 索引→ctx.settings(jet-hub)        │
                      │ 凭据→ctx.credentials              │
                      └───────────────────────────────────┘
```

依赖方向是**单向**的：`adapter` 通过**注入的回调**（`resolveCredential` / `refresh` / `fetchRemoteModels` / `readImage`）间接依赖 `auth` 与 `pool`，自己**不持有 `ctx`**（`src/llm-adapter.ts:54-65`、`src/buddy-adapter.ts:167-201`）。接线全部发生在 `src/index.ts`。

### 端到端链路（授权登录 → 外部系统拿到回复）

以「CodeBuddy + 多账号 + 流式回复」为例，实际链路如下（其余 provider 结构同形，仅节点不同）：

```
[用户] 点 Jet Hub「+ 新建账号」
   │
   ├─(1) 前端 RPC: account.create {provider:'buddy'}
   │       plugin-src/client/jet-hub.js:701
   │      HTTP POST /api/jet-hub  {type:'client-request', method:'jet-hub',
   │                              payload:{method:'account.create', payload:{...}}}
   │       src/jet-hub-rpc.ts:556-601 (connection.fetch.register)
   │
   ├─(2) 宿主分派 account.create 分支                     src/jet-hub-rpc.ts:612-665
   │      ├─ POST {endpoint}/v2/plugin/auth/state?platform=ide → {state, authUrl}
   │      │   src/buddy-oauth.ts:137-167
   │      ├─ 先写「占位账号条目」（无凭据）到 settings      src/jet-hub-rpc.ts:638-646
   │      └─ 立即 return {accountId, loginUrl}  ← 不等授权！
   │
   ├─(3) 前端 window.open(loginUrl)                       jet-hub.js:717
   │      后台异步：runBuddyLoginFlow({state})              src/jet-hub-rpc.ts:648
   │        loopGetToken 轮询 GET /v2/plugin/auth/token?state=...
   │          1s 间隔 / 5min 超时 / code=11217 继续轮询     src/buddy-oauth.ts:178-222
   │        getAccount 轮询 GET /v2/plugin/login/account?state=...
   │          code=12151 继续轮询                          src/buddy-oauth.ts:231-277
   │        buildCredential → JSON.stringify
   │      写 ctx.credentials.set(BUDDY_ACCOUNT_XXXX, json) src/jet-hub-rpc.ts:649
   │      回填昵称/过期/refreshable 到账号条目             src/jet-hub-rpc.ts:653-659
   │
   ├─(4) 前端 1s 轮询 login.poll → 查 credentials 是否已写入
   │       src/jet-hub-rpc.ts:894-904  → done:true
   │
   └─(5) 用户在对话框选模型 → DSH 调 adapter
          resolveModel(provider, model)   → 展示名/上下文/思考档/输出上限
          stream({provider, model, messages, tools, signal})
            ├─ resolveCredential() → pool.getAvailableAccount('buddy','')
            │                        src/index.ts:225-238 → account-pool.ts:532-592
            ├─ serializeMessages()   src/buddy-adapter.ts:229-...（孤儿工具调用清理）
            ├─ 构造 body（prompt_cache_key / reasoning_effort / max_tokens）
            ├─ POST {endpoint}/v2/chat/completions
            │    Headers: Authorization: Bearer、X-Domain、X-Product-Code、
            │             X-IDE-Name/Type/Version、X-Product、UA（按模型族分档）
            │    src/buddy-adapter.ts:1089-1126
            ├─ consumeSse()：SSE → StreamChunk（text-delta/reasoning-delta/
            │   tool-call-delta/usage/finish）   src/buddy-adapter.ts:1136+
            └─ 限流(6004) → updateModelRateLimit + getAvailableAccount 换号重试
                src/buddy-adapter.ts:... / src/llm-adapter.ts:982-1003
```

---

## §1 整体架构：各层职责与依赖方向

### 1.1 产品配置层

每个脉系一个**平行**接口（刻意不合并，避免联合类型收窄）：

| 接口 | 文件 | 字段数 | 承载的差异 |
|---|---|---|---|
| `BuddyProduct` | `src/product.ts:74-144` | 15 | endpoint / platform / productCode / UA（含按模型族分档）/ 归属头名 / 兜底模型表 / `appendSessionParams` |
| `LobsteraiProduct` | `src/lobsterai-product.ts:136-157` | 10 | portalBase / apiBase / 版本号接口 / UA / `clientCapabilities` / 兜底模型表 |
| `QoderProduct` | `src/qoder-product.ts:126-205` | 12 | authBase / openApiBase / inferBase / **encryptedInferBase** / clientId / clientMetadata / 兜底模型表 |
| `TraeProduct` | `src/trae-product.ts:51-152` | 22 | agentHost / ugHost / oauthHost / consoleHost / clientId / appId / ideVersion / **channels（通道列表）** / maxMode |

> 「字段数」为接口声明的**全部属性**个数（含可选属性与 `@deprecated` 保留字段），按 `src/product.ts` / `src/*-product.ts` 的 interface 声明逐个数出。

为什么必须平行而非复用：`src/lobsterai-product.ts:4-20` 明确列出 `BuddyProduct` 里对 LobsterAI 无意义的字段（`productCode` / `apiDomain` / `userAgentByModelFamily` / `appendSessionParams` 等），并指出 `BuddyProduct.id` 是字面量联合 `'buddy' | 'workbuddy'`，加第三个值会牵动 `productById` / `registerBuddyLlm` / `reconcileWithFallback` 一串调用点。

**同源产品共享一套代码的机制**：`CODEBUDDY` 与 `WORKBUDDY` 同型（`src/product.ts:256-396`），`BuddyAuth` 按 `product.id` 派生服务名（`src/buddy-auth.ts:126` → `buddyAuth` / `workbuddyAuth`），`registerBuddyLlm` 按 `product.id` 派生路由名与 `settingsNs`（`src/buddy-adapter.ts:1451-1456`）。`src/index.ts:251-272` 只是 new 了第二个 `BuddyAuth` 实例。

一个易踩的坑（有注释记录）：**`endpoint` 必须随产品切换，不能当全局常量**——两版的路径与响应解析完全相同，差异只在 endpoint 决定的模型池（`src/product.ts:14-18`）。

### 1.2 认证服务层

`CodeArtsAuth` / `BuddyAuth` / `LobsteraiAuth` / `QoderAuth` / `TraeAuth` 全部继承 `cordis/Service`，统一接口（`AGENTS.md:127-134`）：

| 方法 | 语义 | 关键约束 |
|---|---|---|
| `login(options?)` | 阻塞式完整登录 | 成功后必须 `scheduleRefresh()` + `pool.addAccount()` |
| `startLogin(options?)` | **两步式**：立即返回 `{loginUrl, result, close}` | 不打开浏览器、不等用户 |
| `status()` | `{configured, source, expiresAt, refreshable, refreshError?}` | |
| `refresh()` | 刷**默认单凭据 ref** | 不得触碰 `refreshTokenInvalid` / 调度器之外的账号 |
| `refreshAccountCredential(refName)` | 刷**指定账号的 ref** | **不触碰**失效状态与调度器 |
| `refreshAll(pool)` | 批量续期 | **只看 `refreshable`，不看 `enabled`** |
| `logout()` / `stop()` | 清凭据 / 只停调度 | 先置 `active=false` 再清，防在途刷新复活 |
| `scheduleRefresh()` | 按已有凭据武装调度 | |
| `fetchModels(pool?)` | 拉远端模型目录 | 部分 provider 不实现（qoder 恒用静态表） |

`refresh()` 与 `refreshAccountCredential()` 的**分工**是本项目最重要的设计决策之一，`src/index.ts:297-313` 有完整的原因说明：

> `resolveCredential` 优先从账号池取 `LOBSTERAI_ACCOUNT_XXX` 的凭据，而 `lobsterai.refresh()` 读写的是 `LOBSTERAI_ACCESS_TOKEN`。两者错配的后果是 —— 适配器检测到池凭据过期 → 调 refresh → 成功回写到**另一个** ref → 再 resolve 仍取到那份未更新的过期凭据 → 带着过期 token 发请求 → 401。用户看到的是「刚在 Jet Hub 登录好，却一直认证失败」，而日志里续期全是成功的，极难排查。

因此 `src/index.ts:297-313`（lobsterai）、`:344-357`（qoder）、`:383-387`（trae）都把 `refresh` 回调写成「先 `getAvailableAccount` 取到当前账号 → `refreshAccountCredential(entry.credentialRef)` → 取不到才回退 `refresh()`」。

### 1.3 LLM 适配器层

全部继承 `LlmAdapter`，实现 4 个必需方法 + 1 个建议方法：

```ts
providerInfo(provider): LlmProviderInfo
listModels(provider): Promise<readonly LlmModelInfo[]>      // 播报目录（应用黑名单）
resolveModel(provider, model, signal?): Promise<LlmResolvedModelInfo>
stream(options: GenerateOptions): AsyncIterable<StreamChunk>
prepareCall(provider, model, signal?)                        // 兼容新版 DSH 的 shim
```

`prepareCall` 是**兼容 shim**：`src/buddy-adapter.ts:856-860` 说明本仓库链接的 dsh-llm 副本（0.1.0-rc.6）基类没有该方法，缺少时每轮请求抛 `registration.adapter.prepareCall is not a function`。**五个适配器**都写了同款（`src/llm-adapter.ts:811`、`src/buddy-adapter.ts:863`、`src/lobsterai-adapter.ts:787`、`src/qoder-adapter.ts:200`、`src/trae-adapter.ts:739`）。

**每个适配器额外暴露一个非契约方法 `listAllModels()`**（`src/llm-adapter.ts:776-783`、`src/buddy-adapter.ts:768-771`、`src/qoder-adapter.ts:158-160`）。原因：设置页必须渲染**被关闭**的模型（否则用户无法重新打开），而 `listModels` 会按黑名单过滤掉它们；RPC 层只能凭裸 id 补回，展示名（含倍率）随之丢失（`src/jet-hub-rpc.ts:1197-1214` 有完整缺陷复盘）。DSH 的 `ctx.llm` 不透传自定义方法，所以 `src/index.ts:417-426` 显式把适配器实例传给 RPC 层。

### 1.4 账号池

`AccountPool`（`src/account-pool.ts:124-672`）不是 Service，是普通类，`src/index.ts:134` new 出来，`:470` 通过 `ctx.provide('accountPool', pool)` 暴露。

职责（`src/account-pool.ts:111-123`）：
- 账号列表 CRUD（索引存 settings，凭据存 credentials）
- `getAvailableAccount(provider, modelId, excludeAccountIds?)` 选号
- 限流标记读写（`updateModelRateLimit` / `clearModelRateLimits` / `sweepExpiredRateLimits`）
- 模型黑名单读写
- 拖拽排序（`reorderAccounts`）

---

## §2 认证协议细节（逐平台）

先给结论表，再逐条展开。

| 平台 | 流程类型 | 回调/轮询 | 关键端点 | 超时 | 终态判定 |
|---|---|---|---|---|---|
| `codearts` | PKCE(S256) + DPoP(ES256) 授权码，本地回调 | 本地 `127.0.0.1:{≥10000}/oauth/callback` | portal `/authorize` → STS `/v1/oauth2/tokens` | 180s | `invalid_grant` / `ExpiredRefreshToken` / `InvalidDPoPHeader` |
| `buddy` / `workbuddy` | external-link-v2 轮询 | 不起服务器，轮询后端 | `/v2/plugin/auth/state` → `/v2/plugin/auth/token` → `/v2/plugin/login/account` | 5min（1s 间隔） | HTTP 401/403 或 code 401/403 或 msg 含 expired/invalid |
| `lobsterai` | 本地回调 + authCode 换 token | `127.0.0.1:{随机}/auth/callback` | portal `#/login` → `/api/auth/exchange` | 10min | `classifyLobsteraiError` 的 `session-dead`（40100/40101） |
| `qoder` | PKCE(S256) 设备码轮询 | 不起服务器，轮询 `/api/v1/deviceToken/poll` | `qoder.com/device/selectAccounts` → `openapi.qoder.sh/api/v1/deviceToken/poll` | 5min（1s 间隔，连续失败 5 次放弃） | refresh 接口判定（未细读，见「未验证」） |
| `trae` | 本地回调，**直接回传 token**（非 OAuth code） | `127.0.0.1:18080/authorize`（占用则随机） | `www.trae.cn/authorization` → `/cloudide/api/v3/trae/oauth/ExchangeToken` | 10min | refresh 接口判定（未细读） |

### 2.1 `oauth.ts` 是否是通用抽象？——不是

`src/oauth.ts` 的全部内容都是 **CodeArts 专用**：`CLIENT_ID = 'codearts-agent'`、`REDIRECT_PATH = '/oauth/callback'`、`STS_TOKEN_ENDPOINT = 'sts.cn-north-4.myhuaweicloud.com/v1/oauth2/tokens'`（`src/oauth.ts:5-16`）。

它导出的可复用件是**协议级工具**而非平台抽象：
- `generatePkcePair()`（`:58-62`）：verifier = `randomBytes(48).base64url`，challenge = `sha256(verifier).base64url`
- `generateDpopKeyPair()` / `signDpopJws()`（`:65-85`）：ES256 P-256，用 `jose` 签发 `typ: 'dpop+jwt'`，payload 含 `htm`/`htu`/`iat`/`jti`
- `requestToken()`（`:96-138`）：带 DPoP 头的 form-urlencoded POST
- `RefreshTokenExpiredError`（`:88-93`）

各 `xxx-oauth.ts` **不复用** `oauth.ts`，而是各自独立实现。它们复用的是一个**模式**：`startXxxLoginFlow()` 立即返回 `{loginUrl, result, close}` + `runXxxLoginFlow()` 阻塞版（`src/login.ts:393-437`、`src/lobsterai-oauth.ts:232-337`、`src/qoder-oauth.ts:205-255`、`src/trae-oauth.ts:583-698`）。

### 2.2 CodeArts：PKCE + DPoP + 本地回调（双流程）

**主流程（新式 IAM OAuth）**：
1. `generatePkcePair()` + `generateDpopKeyPair()`，起本地回调服务器（`src/login.ts:393-397`）
2. 构造 portal URL（`src/login.ts:262-271`）：
   ```
   https://codearts.huaweicloud.com/portal/authorize
     ?theme=2&locale=zh-cn&uri_scheme=codearts-agent&client_id=codearts-agent
     &port={port}&code_challenge={S256}&code_challenge_method=SHA-256
     &ticket_id={hex}&plugin-name=snap_AIIDE&plugin-version=5.2.0
   ```
   ⚠️ 两个逆向细节（都有注释）：`code_challenge_method` 必须写 **`SHA-256`**（非 RFC 标准 `S256`，错值会回退旧 ticket 流程）；URL **不含** `auth_callback_url`（portal 仅凭 `port` 构造回调，多加参数会被视为异常）。
3. 回调端口必须 **≥10000**（`src/login.ts:337-364`），低端口会被 portal 拒绝；先 `listen(0)`，若分配到的端口 < 10000 则关闭后用 `[10000, 65535]` 随机端口重试。
4. 收 `?code=` → `exchangeAuthorizationCode()` → `sts.cn-north-4.myhuaweicloud.com/v1/oauth2/tokens`
5. 凭据含 `refresh_token` + `code_verifier` + `dpop_private_key_jwk`（`src/oauth.ts:173-188`），三者缺一不可续期

**回退流程（旧 ticket）**：`runLoginFlow()`（`src/login.ts:228-241`），回调带 `secret` 时 307 重定向 + 后台轮询 `snap-access.../snap-manager/v1/login/ticket`（`src/login.ts:77-113`，120 次 × 1s）。ticket 凭据**没有** `refresh_token`，不可静默续期（`README.md:139-141`）。

**终态判定**（`src/oauth.ts:122-136`）：`error === 'invalid_grant'` 或 `error_code` 含 `ExpiredRefreshToken` / `InvalidDPoPHeader` → 抛 `RefreshTokenExpiredError`（注释说明：避免 `InvalidDPoPHeader` 每 10 分钟无限重试）。

### 2.3 CodeBuddy / WorkBuddy：external-link-v2 轮询

**端点**（`src/buddy.ts:29-39`）：
| 用途 | 方法 | 路径 |
|---|---|---|
| 取 state + authUrl | POST | `/v2/plugin/auth/state?platform={platform}` |
| 轮询 token | GET | `/v2/plugin/auth/token?state=` |
| 轮询账户 | GET | `/v2/plugin/login/account?state=` |
| 刷新 token | POST | `/v2/plugin/auth/token/refresh` |
| 云端配置（模型） | GET | `/v3/config` |
| 企业模型（含元数据） | GET | `/console/enterprises/personal/models` |

**流程**：`fetchAuthState`（`src/buddy-oauth.ts:137-167`，带 `X-No-Authorization: true` 等四个 `X-No-*` 头）→ 打开浏览器 → `loopGetToken`（`:178-222`）→ `getAccount`（`:231-277`）。

**轮询容错**（关键）：
- 错误码 `11217`（`CODE_TOKEN_NOT_READY`）= token 未就绪 → **继续轮询**（`src/buddy.ts:55`、`src/buddy-oauth.ts:219`）
- 错误码 `12151`（`CODE_ACCOUNT_NOT_READY`）= 账户未就绪 → **继续轮询**（`src/buddy.ts:57`、`src/buddy-oauth.ts:274`）
- 网络错误同样 continue（`src/buddy-oauth.ts:207-210`），不中断登录
- 超时 5min（`LOGIN_TIMEOUT_MS`，`src/buddy.ts:44`），间隔 1s（`POLL_INTERVAL_MS`，`:46`）

**产品差异**（全部收敛在 `BuddyProduct`）：
- `platform`：`ide`（中国版）/ `workbuddy-ai`（国际版）
- 登录 URL 是否追加参数：`decorateLoginUrl()`（`src/buddy-oauth.ts:525-538`）——国际版需加 `version` + `loginSessionId`（每次随机 UUID，仅日志追踪用，无校验语义）
- 请求身份头：`X-Product-Code` + `User-Agent`（`src/buddy-oauth.ts:348-364`）
- ⚠️ 注释反复强调：**`product` 必须由调用方传入**，否则 WorkBuddy 会携带 CodeBuddy 的身份标识（`src/buddy-oauth.ts:175-177`、`:344-347`）

### 2.4 LobsterAI：本地回调 + authCode 换 token

**登录 URL**（`src/lobsterai-oauth.ts:104-116`）：
```
https://lobsterai.youdao.com/portal#/login?source=electron&redirect_uri=http%3A%2F%2F127.0.0.1%3A{port}%2Fauth%2Fcallback&state={uuid}
```
`redirect_uri` 必须是 `http://127.0.0.1:{port}/auth/callback` 形态，登录页会校验；`state` 是防 CSRF 的一次性随机串，回调时比对（`src/lobsterai-oauth.ts:262-269`，不匹配回 400）。

**换 token**（`src/lobsterai-oauth.ts:130-185`）：`POST {apiBase}/api/auth/exchange`，**无需 Authorization 头**，请求体必含 5 字段：
```json
{ "authCode", "firstKeyfrom", "latestKeyfrom", "uuid", "version" }
```
`uuid`（安装 UUID）与 `firstKeyfrom` 由**客户端**生成并贯穿账号生命周期，必须随凭据持久化——**丢了就续期失败，只能重新登录**（`src/lobsterai.ts:72-78`）。

**续期**（`src/lobsterai.ts:262-270`）：`POST /api/auth/refresh`，请求体 = keyfrom 载荷 + `refreshToken`，同样无 Authorization。
⚠️ `latestKeyfrom` **刻意不更新为当前时刻**（虽然字段名叫「最近活动」），严格对齐 Go 参考实现（`src/lobsterai.ts:385-390`）。这类「服务端可能有校验、不能自作聪明」的判断标注了「需实测支撑」。

**错误分类**（`src/lobsterai-errors.ts:100-117`）：判定顺序即优先级——
```
402 → hard-credit
body 含 hard 关键词（中英双语列表）→ hard-credit
body 含 session-dead 标记（40100/40101）→ session-dead
429 → soft-rate ; 404 → not-found ; ≥500 → server ; ≥400 → client ; 否则 none
```
为什么 body 关键词排在状态码之前（除 402）：实测上游用 **400 + 中文「积分不足」**表达余额耗尽，只按状态码会误判成可重试的 `client`，于是反复重试一个永远不会成功的账号（`src/lobsterai-errors.ts:89-95`）。
为什么 session-dead 排在 429/404 之前：会话已死时任何「换号重试」都没意义（`:93-95`）。

### 2.5 Qoder：PKCE 设备码轮询

**不起本地监听端口**，因此没有端口泄漏与回调伪造问题（`src/qoder-oauth.ts:4-9`）。

**授权 URL**（`src/qoder.ts:109-118`）：
```
https://qoder.com/device/selectAccounts?challenge={S256}&challenge_method=S256&nonce={uuid}&machine_id={uuid}&client_id={prod clientId}
```
⚠️ `client_id` 必须用 **prod 的 `J_a`**（`e883ade2-...`），不是 `G_a`。源码是 `client_id: i ? J_a : G_a`，第 4 参是 `isProd()`；初版误读为「useIdeClientId」，导致授权回调阶段被拒（页面报「参数无效」）。**只靠入口 302 检查发现不了**——`/device/selectAccounts` 对任一 client_id（含全零 UUID）都返回 302（`AGENTS.md:37-39`、`src/qoder-product.ts:155-176`）。

**PKCE 细节**（`src/qoder.ts:56-69`）：verifier 长度 `43 + floor(86*random)`，字符集为 RFC 7636 unreserved 66 字符；challenge 必须**去掉 base64 padding**（带 `=` 服务端校验失败）。

**轮询**（`src/qoder-oauth.ts:119-164`）：`GET {openApiBase}/api/v1/deviceToken/poll?nonce&verifier&challenge_method=S256`
- ⚠️ **`404` 表示「用户尚未完成授权」，必须继续轮询**。实测依据：该端点返回 404 而任意不存在的路径返回 401，说明它被网关豁免认证、由业务层报「会话未就绪」（`src/qoder-oauth.ts:110-114`）
- 轮询 host 是 `openapi.qoder.sh`，`qoder.com` 的同名路径返回 401（`src/qoder.ts:121-126`）
- 连续网络失败上限 5 次（源码 3，本实现放宽，`src/qoder.ts:19-20`）
- 其它非 2xx（如 5xx）立即抛错——那是服务端异常，不是「等用户」

**`machine_id` 是自造的**：Qoder 官方用 `@napi-rs` 取 SMBIOS UUID 再哈希，不可移植；本插件改为随机 UUID 并持久化，续期时原样回传（`src/qoder.ts:71-79`，风险在 `:78` 标注见设计文档 §8）。

### 2.6 TRAE：本地回调直接回传 token

**登录 URL 是完整的 18 参数集**（`src/trae-oauth.ts:105-125`）：
```
https://www.trae.cn/authorization
  ?login_version=1&auth_from=solo&login_channel=native_ide&plugin_version=2.3.62834
  &auth_type=local&client_id=en1oxy7wnw8j9n&redirect=0
  &login_trace_id={machineId+deviceId 尾16}
  &auth_callback_url=http://127.0.0.1:{port}/authorize   ← 参数名是 auth_callback_url！
  &machine_id=&device_id=&x_device_id=&x_machine_id=
  &x_device_brand=PC&x_device_type=PC&x_os_version=1.0
  &x_app_version=0.1.52&x_app_type=stable
```
⚠️ 注释记录的真实缺陷：早期只发 5 个参数（且回调参数名写成 `callback_url`），TRAE 拿不到回调地址，登录页**永远停在授权中**（`src/trae-oauth.ts:84-98`）。

**回调解析**（`src/trae-oauth.ts:273-345`）：
- ⚠️ **回调没有 `?code=`，直接回传 token**：`?refreshToken=...&userInfo={json}&userJwt={json}`。早期按 OAuth 惯例找 `code`，`parseAuthCode` 恒返回 undefined → 回 400 → 结果 Promise 永不落定 → 前端永远「认证中」（`:237-248`）
- ⚠️ 但**带 `code` 的回调不是无效回调**：TRAE 授权页并存两套流程（新流程 PKCE 回带 `authCodeInfo`，老流程直传 `refreshToken`）。本实现对两种形态都返回结果，PKCE 形态明确报「本实现暂不支持该流程」（`:249-261`、`:326-344`）
- `userInfo` 中文昵称存在**双重编码乱码**（实测 `Óû§8847309959`），需 `fixNicknameMojibake()` 尝试 latin1 回转（`:209-232`）
- 回调字段名是 **`TenantID`**（不是 `EnterpriseID`）（`:141`）

**换凭据**（`src/trae-oauth.ts:365-440`）：有 `refreshToken` 走 `POST {oauthHost}/cloudide/api/v3/trae/oauth/ExchangeToken`（**refreshToken 会轮换**）；无则用 `userJwt.Token` 兜底。随后 `GetUserInfo` 补齐 uid/昵称，**失败不阻塞**（回退回调 `userInfo`）。

**回调端口**：默认 `18080`，被占用时**自动回退随机端口**（`src/trae-oauth.ts:522-535`），因为 `auth_callback_url` 由我们构造并随登录 URL 发出、服务端原样回跳。⚠️ `listen()` 失败是通过 `'error'` **事件**异步抛出的，不属于 Promise 链——不先注册 `'error'` 会变成进程级 unhandled error 直接崩掉宿主（`src/trae-oauth.ts:443-505` 有完整复盘与修法）。

### 2.7 超时与失败处理汇总

| 机制 | 值 | 位置 |
|---|---|---|
| CodeArts OAuth 回调等待 | 180s | `src/login.ts:337` |
| CodeArts 回调端口下限 | 10000 | `src/login.ts:339` |
| CodeArts ticket 轮询 | 120 次 × 1s | `src/login.ts:83` |
| Buddy 登录轮询 | 5min，1s 间隔 | `src/buddy.ts:44-46` |
| Buddy auth/state 请求 | 5s | `src/buddy.ts:48` |
| Buddy 其余控制面 | 60s | `src/buddy.ts:50` |
| LobsterAI 登录窗口 | 10min | `src/lobsterai.ts:52` |
| LobsterAI 控制面请求 | 30s | `src/lobsterai.ts:50` |
| Qoder 登录 | 5min，1s 间隔，连续失败 5 次 | `src/qoder.ts:16-20` |
| TRAE 登录 | 10min | `src/trae.ts:70` |
| TRAE 控制面请求 | 30s | `src/trae.ts:68` |

**所有定时器都 `unref()`**（如 `src/login.ts:411`、`src/lobsterai-oauth.ts:306`、`src/trae-oauth.ts:610`），不让登录超时定时器独占事件循环。

---

## §3 凭据存储与续期

### 3.1 存储位置与格式

**「双文档系统与凭据分离」的确切含义**（`docs/adding-a-new-provider.md:78-87`）：

```
凭据本体: ctx.credentials（加密存储）    ← 令牌 / refresh_token / 私钥 JWK
账号索引: ctx.settings → 'jet-hub' ns    ← 账号列表 / 模型黑名单 / 顺序
两者通过 credentialRef 字段关联
```

- 凭据写入：`ctx.credentials.set(credentialRef('BUDDY_ACCOUNT_XXXX'), JSON.stringify(credential))`（`src/service.ts:145`、`src/buddy-auth.ts:148`）
- 账号条目：`src/types.ts:42-75` 的 `ProviderAccountEntry`，含 `id` / `provider` / `nickname` / `enabled` / `credentialRef` / `createdAt` / `expiresAt` / `refreshable` / `modelRateLimits` / `traeCheckinDeviceGeneration`
- settings schema：`jetHubSchema`（`src/account-pool.ts:64-75`），用 `Schema.array(Schema.any())` 承接动态结构

**为什么必须分离**：`ctx.credentials` 是宿主提供的加密存储，`ctx.settings` 是明文配置文件（YAML）。凭据里含 refresh_token、DPoP 私钥、设备指纹，不能落明文；而账号列表需要被 UI 频繁读写与手工编辑。

⚠️ **`settings.replace()` 是整体替换**——`writeAccounts` 必须连同黑名单一起写回，否则会抹掉 `disabledModels`；`writeModels` 对称（`src/account-pool.ts:184-198`、`:242-252`）。

**ref 命名约定**：
- 单凭据（无账号池回退）：`{PROVIDER}_ACCESS_TOKEN`（如 `CODEARTS_ACCESS_TOKEN`、`BUDDY_ACCESS_TOKEN`、`WORKBUDDY_ACCESS_TOKEN`、`LOBSTERAI_ACCESS_TOKEN`、`QODER_ACCESS_TOKEN`、`TRAE_ACCESS_TOKEN`）
- 账号池条目：`{PROVIDER}_ACCOUNT_{8位大写hex}`（`src/jet-hub-rpc.ts:616-617`）

**凭据结构必须含 `access_token`**：`AccountPool.findAccountIdByCredential` 对非 `codearts` 的 provider 统一取 `access_token` 作身份标识，`codearts` 取 `access_key_id`（`src/account-pool.ts:419-421`）。选错字段会导致匹配恒失败，限流记录无法归属账号。

⚠️ 该方法**会跳过已停用账号**（`src/account-pool.ts:423` 的 `!entry.enabled`）。这一点值得单独记住，因为它与本文反复强调的「`enabled` 语义边界」形成对照：**续期不看 `enabled`**（§3.3）、**探活不看 `enabled`**（§4.4），但**凭据反查账号 id 看 `enabled`** —— 停用账号无法通过凭据被反查到。

**`expires_at` 统一存毫秒时间戳字符串**：便于一套 `credentialExpiresAtMs` 解析逻辑通用（`src/buddy.ts:142-162`、`src/lobsterai.ts:185-206`、`src/trae.ts:131-150`）。解析兼容毫秒/秒/ISO 三种形态，且都有一条 JWT `exp` 后备路径（`src/buddy.ts:168-178`）。

⚠️ 一个细节：`readStringField` 会剔除 CR/LF——CodeBuddy 的 `scope` 字段有时返回多行文本，这些换行落盘到 `.credentials.yaml` 时会被当作多行标量，破坏 JSON 结构，重新读取时 `JSON.parse` 失败（表现为「有效期/昵称等字段丢失」，实际是整个凭据无法解析）（`src/buddy.ts:229-241`）。

### 3.2 `RefreshScheduler`（`src/refresh.ts`）

```ts
class RefreshScheduler {
  arm(expiresAtMs, nowMs?)   // 安排下次刷新
  stop()                     // 取消，并让在途 run() 失败后不再重试
  refreshOnce()              // 立即执行一次
  private async run()        // 一次触发 + 失败重试
}
```

**常量**（`src/refresh.ts:1-6`）：
- `REFRESH_LEAD_MS = 3_600_000`（提前 1 小时触发）
- `REFRESH_RETRY_MS = 600_000`（普通失败后 10 分钟重试）
- `REFRESH_ABNORMAL_NETWORK_RETRY_MS = 60_000`（异常网络 1 分钟）

**触发时刻计算**（`:32-40`）：
```
距过期 ≤1h → 立即（delay=0）
否则       → trigger = now + 1h，再叠加 0-59 秒随机偏移
```
随机偏移用于避免多账号/多进程同时刷新造成尖峰。

**generation 代号防「僵尸调度」**（`:43-113`，这是本文件最精妙的部分）：
- `arm()` / `stop()` 都先 `this.generation++`
- 在途 `run()` 捕获到 generation 变化 → 放弃失败后的重试武装，避免登出后调度器复活
- 在途期间若已被新 `arm()`（`this.timer` 指向新定时器 T2），失败路径先 `clearTimeout` 再设新定时器，避免 T2 沦为孤儿

**失效判定是结构化的，不是 `instanceof`**（`:14-25`，注释给出原因）：
```ts
function isRefreshTokenExpired(error) {
  if (!(error instanceof Error)) return false
  if (error.name === 'RefreshTokenExpiredError') return true
  return /refresh[_ ]?token/i.test(error.message)
}
```
原因：`oauth.ts`、`buddy-oauth.ts`、`lobsterai-auth.ts` 各自导出**同名但不同 identity** 的 `RefreshTokenExpiredError` 类，用 `instanceof` 会让其中一个 provider 的失效信号穿透为「可重试」而无限重试。因此 `src/lobsterai-auth.ts:60-70` 也刻意保证 `error.name` 恰为 `'RefreshTokenExpiredError'`。

**异常网络判定**（`src/refresh.ts:8-12`）：`/fetch failed|ENOTFOUND|ECONNREFUSED|proxy|unresolved host|getaddrinfo/i`

### 3.3 `refreshAll` 与批量续期

`src/index.ts:400-419` 定义 `refreshAllCredentials()`，逐个 provider 调 `xxx.refreshAll(pool)`，每个都 `try/catch` 静默。

`refreshAll` 的实现口径统一（`src/buddy-auth.ts:308-343`、`src/service.ts:272-318`、`src/lobsterai-auth.ts`、`src/qoder-auth.ts`、`src/trae-auth.ts`）：
```ts
for (const entry of await pool.listAccounts(this.product.id)) {
  if (!entry.refreshable) continue          // ← 只看 refreshable，不看 enabled
  try {
    // resolve → 换 token → set → updateAccount({expiresAt, refreshable})
  } catch (error) {
    if (error instanceof RefreshTokenExpiredError) {
      await pool.updateAccount(entry.id, { refreshable: false })   // 标记不可续期
    }
    // 单账号失败不中断循环
  }
}
```

**调度器启动判据**（`src/index.ts:386`）：
```ts
pool.listAllAccounts().then(accounts => {
  const hasRefreshable = accounts.some(a => a.refreshable)   // ← 不看 enabled
  if (hasRefreshable) {
    const refreshTimer = setInterval(() => void refreshAllCredentials(), 30 * 60 * 1000)
    refreshTimer.unref?.()
    ...
  }
})
```

**真实缺陷复盘**（`AGENTS.md:136-154`、`README.md:146-163`）：早期两处都按 `enabled` 过滤——
- `refreshAll()` 里 `if (!entry.enabled || !entry.refreshable) continue` → 停用期间 refresh_token 一路放到失效
- `src/index.ts` 的 `accounts.some(a => a.refreshable && a.enabled)` → **所有账号都停用时续期定时器根本不启动**

用户重新启用后拿到的是死凭据，只能重新登录。更糟的是停用账号仍会出现在 Jet Hub 并参与积分领取，用过期凭据打腾讯接口 → 服务端回 HTML 错误页 → 前端报 `Unexpected token '<'`。

### 3.4 登出竞态保护

`logout()` / `stop()` 都先置 `this.active = false` **再**清凭据/停调度（`src/service.ts:321-334`、`src/buddy-auth.ts:346-357`）。在途刷新完成后检查 `if (!this.active) return`，跳过凭据回写与调度武装，避免已登出的凭据被在途刷新复活（`src/service.ts:213-215`、`src/buddy-auth.ts:234-236`）。

---

## §4 账号池（`account-pool.ts`）

### 4.1 注册

账号注册发生在**登录成功回填**时，而非登录发起时（占位条目除外）：

- `AuthService.login()` 内：`if (options.accountId && options.pool) await pool.addAccount({...})`（`src/buddy-auth.ts:154-165`、`src/service.ts:152-164`）
- 两步式路径：先 `addAccount`（占位，`refreshable: false`），后台登录成功后再 `updateAccount` 回填昵称/过期/refreshable（`src/jet-hub-rpc.ts:638-664`）
- 后台登录失败 → `pool.removeAccount(id)` **删除占位条目**，不留幽灵账号（`src/jet-hub-rpc.ts:662-664`）

`addAccount` 只是 append（`src/account-pool.ts:314-317`），没有去重。`provider` 字段区分归属。

### 4.2 选择（`getAvailableAccount`）

`src/account-pool.ts:532-592`：

```ts
const candidates = this.readAccounts()
  .filter(a => a.provider === provider && a.enabled)                    // ① 只认启用
  .filter(a => excludeAccountIds === undefined || !excludeAccountIds.has(a.id))  // ② 排除已试
  .filter(a => {                                                        // ③ 模型级限流过滤
    if (modelId.length === 0) return true
    if (!a.modelRateLimits) return true
    const resetAt = a.modelRateLimits[modelId]
    return resetAt === undefined || resetAt === 0 || Date.now() >= resetAt
  })
if (candidates.length === 0) return null
// 逐个尝试解析凭据，跳过占位/损坏条目
for (const entry of candidates) { ... return { entry, credential } }
```

**关键设计**：候选顺序**就是数组顺序**，即用户在 Jet Hub 拖拽设定的手动顺序。`src/account-pool.ts:548-557` 的注释解释了为什么**不要**重新引入「按限流重置时间重排」。以下为**对注释内容的转述**（原文为散文式注释，不含任何代码片段）：

候选顺序即用户在 Jet Hub 拖拽设定的**手动顺序**（由 `reorderAccounts` 写入）。之所以不再按「限流重置时间最早到期」重排（**注释称早期实现如此，但其具体写法未在代码中保留**）：那个排序会让手动顺序形同虚设 —— 用户把某账号拖到首位，只要另一个账号的限流重置时间更早，实际选中的仍是后者，拖拽变成纯 UI 装饰。现在的语义是「**手动顺序优先，限流豁免**」：顺序完全由用户决定，而当前正处于限流期的账号已被上面的 filter 排除，不会选到。注释最后指出：`candidates` 来自 `readAccounts()` 的 `filter`，而 `filter` 保持原数组顺序，故这里天然就是手动顺序，**无需任何排序**。

⚠️ 需特别说明：`src/account-pool.ts` 全文中**不存在任何排序调用**（grep `sort` 零命中），注释里也没有保留早期实现的具体代码片段。上述「早期实现按重置时间重排」是注释作者的**历史追述**，无法从当前代码（或 git 历史之外）独立验证。

`modelId` 为空串时不做限流过滤——调用方（provider 的 `resolveCredential` 入口）此时还不知道要发哪个模型，只能退化为「任取一个启用账号」（`src/account-pool.ts:513-517`）。

`excludeAccountIds` 的存在理由（`:521-530`）：调用方在「请求级轮换」时逐个换号重试，必须能拿到**下一个**账号。当失败类别**不写限流标记**时（如 5xx），刚失败的账号仍是排序第一，不排除就会原地打转。在池这一层排除（而非让调用方自己跳过）是必要的：调用方只能拿到「池认为最优的一个」，无法枚举候选自己去重。

### 4.3 轮换

轮换是**请求级**的，由适配器驱动：

**CodeArts**（`src/llm-adapter.ts:982-1003`）：
```ts
if (this.options.accountPool && isRateLimited(errorText)) {
  const parsed = parseRateLimitError(errorText, options.model)
  if (parsed) {
    if (currentAccountId) await pool.updateModelRateLimit(currentAccountId, parsed.modelId, parsed.resetTimeMs)
    const next = await pool.getAvailableAccount('codearts', options.model)
    if (next && !rateLimitTried.has(next.entry.id)) {
      rateLimitTried.add(next.entry.id); credential = next.credential; continue
    }
    throw new LlmError(`codearts: 模型 ${options.model} 所有账号均受限，请稍后再试`, 'QUOTA_EXCEEDED')
  }
}
```
注释说明：用 `tried` 集合保证每个账号只尝试一次，试完才判定「全部受限」——避免只试一个就下结论。

**LobsterAI**（`src/lobsterai-adapter.ts:934-1004`）：策略更完整——
- 换号次数上限 `LOBSTERAI_MAX_ROTATE - 1`（**减 1**：本适配器在进入循环前已用首个凭据发过一次请求，不减会多一次，`src/lobsterai-adapter.ts:942-951`）
- 只有 `recordsLobsteraiRateLimit(kind)` 的三类（`hard-credit` / `soft-rate` / `not-found`）才记限流徽章——「徽章的含义必须是『这个模型受限』，而不是『这个账号出过错』」（`src/lobsterai-errors.ts:157-159`）
- 必须把 `tried` 传给池，否则换号形同虚设（`src/lobsterai-adapter.ts:973-976`）
- ⚠️ 一个隐蔽 bug 的修法：`status` / `kind` / `body` 必须**成组更新**，否则会出现「A 账号的 kind 配 B 账号的 status/body」——实测 A=402（积分不足）→ B=503 时最终 code 变成 SERVER，用户看不到真实原因，且会给 B 写上虚假的限流徽章（`src/lobsterai-adapter.ts:922-930`）

### 4.4 标记失效与恢复

失效标记**不是**账号级，而是**账号 × 模型**级的重置时间：`ProviderAccountEntry.modelRateLimits: Record<modelId, resetAtMs>`（`src/types.ts:60`）。

- **写标记**：`updateModelRateLimit(accountId, modelId, resetAtMs)`（`src/account-pool.ts:602-619`）
- **选号过滤**：`resetAt === undefined || resetAt === 0 || Date.now() >= resetAt` 才可用（`:545`）
- **清理过期**：`sweepExpiredRateLimits()`（`:622-637`）
- **主动重测**（`account-probe.ts`）：对每个带标记的模型**真实发一次最小请求**（提示语 `只回答两个字：收到`，`src/account-probe.ts:51`），正常返回才清除标记
- **主动重置**：不发请求，直接清除（`src/account-probe.ts:254-272`）

**重测的两个关键设计**（`src/account-probe.ts:22-29`）：
1. **不传 `accountPool` 给适配器**——适配器只在拿到 accountPool 时才切换账号、写限流标记；探测必须只针对指定账号且无副作用，否则「重测 A」会顺带污染其他账号的标记
2. **停用账号也要能重测**——凭据解析走 `resolveCredentialForAccount`（按 id，**不检查 enabled**），而非 `getAvailableAccount`（`src/account-pool.ts:453-469`）

**「重置」vs「重测」的语义区分**：标记只反映「上一次 429 时的快照」，服务端常在重置时间前提前放行，于是出现「显示超额使用但发消息正常回复」。设计哲学是「如实展示 + 用户可主动验证」，因此**刻意不移植** Go 版的自动冷却状态机（`Cooldown(12h)` / `Disable(uid)`）——那会让账号被静默停用，与这套 UI 语义冲突（`src/lobsterai-errors.ts:6-20`）。

### 4.5 并发下如何避免多请求打到同一账号

**结论：没有租约/占位机制。** 我通读了 `account-pool.ts` 全文（672 行），`getAvailableAccount` 没有任何 in-flight 标记或互斥；两个并发请求会拿到同一个账号（若它是最优候选）。

现有的防护只有三层：
1. `enabled` 过滤
2. 模型级限流标记过滤（只在**收到 429 之后**才写入，即滞后一轮）
3. `excludeAccountIds`（只在**同一请求内**的换号重试时使用）

**并发安全的另一半是「不丢更新」，这个做对了**：`writeAccounts()` 在**第一个 await 之前**同步执行 `this.cache = accounts`（`src/account-pool.ts:190-198`），而所有读-改-写序列在 `await` 之前都是同步的。加上 `readAccounts()` 读的是**进程内权威副本**而非 `scope.get()`（`:127-141` 的注释解释：settings 的 resolved 快照在 `replace()` 后未必立即更新，若以滞后快照为读源，并发/连续的 `updateModelRateLimit` 会互相覆盖——典型表现是多个账号触发限流后 settings.yaml 里一条 `modelRateLimits` 都没有），因此不会出现「写 A 的限流 → 读旧快照 → 写 B 的限流」把 A 抹掉。

对我们的网关：如果需要「并发请求尽量分散到不同账号」，必须自己加租约层（本插件没有）。

---

## §5 模型目录与解析

### 5.1 `listModels` 如何从各平台「播报」模型

**两种模式**（按下表 5 个 provider 归类：「远端优先 + 兜底」与「恒用静态表」）：

| provider | 模式 | 数据源 |
|---|---|---|
| `codearts` | 远端优先 + 静态兜底 | 两个端点合并（`src/models.ts:120-165`） |
| `buddy`/`workbuddy` | 远端优先 + 产品兜底表 | scoped 端点 + `/v3/config` **取并集**（`src/buddy-oauth.ts:376-395`） |
| `lobsterai` | 远端优先 + 静态兜底 | `GET /api/models/available` |
| `qoder` | **恒用静态表** | `QoderProduct.fallbackModels`，**不发任何网络请求**（`src/qoder-adapter.ts:145-150`） |
| `trae` | 远端优先 + 静态兜底 | `POST /api/ide/v1/batch_get_detail_param`（多通道） |

**CodeArts 的双端点合并**（`src/models.ts`）：
1. `opengw.developer.huaweicloud.com/api/v1/gateway/config` → `result.models`（benefit 免费额度模型）
2. `snap-access.../v1/model/builtin` → `builtinModels`（常规模型），带 `Agent-Type: PromptCenter` + `X-Language: zh-cn` 头（**不参与签名**）

`normalizeModelId()`（`:41-49`）去掉末尾 4 位日期后缀：`deepseek-v4-flash-0731` → `deepseek-v4-flash`。原因：远端 gateway/config 返回带日期后缀的 id，但 chat 端点只认不带后缀的 id（否则 `InferHub.002002009.404 model is not registered`）。仅匹配末尾 `-NNNN`，避免误去 `glm-5.3-flash`。

还有一条硬过滤：id 含 `-VL-` 或以 `-VL` 结尾的多模态模型被隐藏（上下文小、不支持工具调用，不适合当 agent 主模型）（`:55-58`）。

缓存：内存 → 磁盘 `~/.cache/deveco/codearts_models.json` → 空，定时 2 小时刷新（`src/models.ts:18-25`、`:206-223`；`src/service.ts:348-366`）。

**CodeBuddy 系的双端点取并集**（`src/buddy-oauth.ts:376-395`）——这里有一段很有价值的缺陷复盘：
> scoped 端点 → `hy4-preview`、`hy4-preview-x`（30 个模型）
> `/v3/config` → **`hy4-preview-f`**（22 个模型）
> 而「限时免费」促销的 `modelIds` 只写着 `["hy4-preview-f"]` —— 挂在**我们没有采用**的那个 id 上。早期实现只返回 scoped，于是该促销永远对不上，界面显示 `x0.29` 而 IDE 显示免费。

修法：`mergeRemoteModels(primary=scoped, extra=config)`——同 id 以 scoped 为准（带更完整元数据），config 独有的 id 追加在后，同时取其促销表（`src/buddy-oauth.ts:418-470`）。

**三级回退**：scoped 端点 → `/v3/config` → 调用方静态兜底表（`src/buddy-oauth.ts:366-408`）。

**黑名单过滤统一在适配器的 `listModels` 内**：`accountPool.disabledModelsFor(this.product.id)`（`src/llm-adapter.ts:794-797`、`src/buddy-adapter.ts:778-781`、`src/qoder-adapter.ts:164-168`）。黑名单是**黑名单制**——只有键存在且为 `true` 的模型被隐藏，未记录的一律默认打开，这样服务端新增模型时无需任何配置即自动可见（`src/account-pool.ts:21-28`）。

### 5.2 `resolveModel` 如何解析模型名

**关键结论：`resolveModel` 不解析到账号。** 它只做三件事：
1. 找到该模型的元数据（展示名、上下文窗口、输入模态、思考档位、默认输出上限）
2. 返回 `LlmResolvedModelInfo`
3. 懒加载远端目录（可能先于 `listModels` 被调用）

账号选择发生在**更下游**：`stream()` 开头调 `resolveCredential()`，其实现里才 `pool.getAvailableAccount(...)`（`src/index.ts:225-238`）。

`resolveModel` 的元数据查找链（以 buddy 为例，`src/buddy-adapter.ts:805-854`）：
```
contextWindow:  remoteContextWindows → productFallbackContextWindows → CONTEXT_WINDOWS
name:           remoteMeta → productFallbackIndex → model（原样）
inputModalities: IMAGE_CAPABILITY_OVERRIDES → remoteMeta.supportsImages → productFallbackMeta → IMAGE_MODELS
defaultMaxTokens: remoteMeta.maxOutputTokens → productFallbackMeta.maxOutputTokens
reasoning:      effortsFor(model)（remote → productFallback → 通用静态表）
```

**为什么 `defaultMaxTokens` 必须声明**（`src/buddy-adapter.ts:819-835` 的注释）：
> DSH 在 `resolveCallWithInfo` 里只在调用方未显式给值时用 `defaultMaxTokens` 兜底，适配器不声明就等于把这个值永久交给网关默认（实测网关默认仅 32000）。结果是大文件写入/长回答在 32000 处被截断成 `finish_reason:'length'`。

且有明确的「不编造」原则：远端与兜底表都没有该模型的值时**保持 undefined**——「编造一个偏大的值会让服务端 400 拒绝（参考 codearts 131072 被拒的实测），偏小则无谓截断用户输出」。

### 5.3 模型 ID 命名空间

**没有跨平台前缀命名空间。** 机制是：

1. 每个 provider 是一个 DSH **路由名**：`ctx.llm.registerAdapter([product.id], adapter)`（`src/buddy-adapter.ts:1455`、`src/llm-adapter.ts:1458`、`src/trae-adapter.ts:1384`）
2. `listModels` 返回的每条都带 `provider: this.product.id`（`src/buddy-adapter.ts:783`、`src/llm-adapter.ts:798`）
3. 模型 `id` **就是平台原生 id**（如 `deepseek-v4-flash`、`qfmodel`、`DeepSeek-V4-Flash-Official`），不做任何改写
4. `resolveModel(provider, model)` 拿到的 `model` 是原生 id

**跨平台同名模型如何区分**：靠 `provider` 字段（路由维度），不靠 id 前缀。而在 **UI 展示层**，同名模型需要消歧——`AGENTS.md:400-430` 的「同名模型必须消歧（`buildDisplayNames`）」章节，把消歧标记写进 `name` 而不是 `description`（因为 composer 的模型切换菜单只渲染 `name`，`src/qoder-adapter.ts:172-174`）。

**为什么不能用「加前缀」的朴素做法**：模型 id 要原样发给上游（`options.model` 直接进请求体），改 id 就要双向映射，而各平台的模型池是服务端动态下发的、随时变化——维护映射表不现实。

**对我们网关的启示**：如果要暴露 OpenAI 兼容 API，`model` 字段必须承载「平台 + 原生 id」两段信息（如 `buddy/deepseek-v4-flash` 或 `buddy:deepseek-v4-flash`），然后在网关侧拆开。本插件把这个维度交给了宿主的 `provider` 路由参数，所以不需要前缀。

---

## §6 请求转发与协议适配

### 6.1 对外接口形态（最重要的一节）

**本插件不对外暴露任何 HTTP 端点给「外部系统」使用。** 它的对外接口是 **DSH 宿主的内部契约**：

- `ctx.llm.registerConfigurableProviders([{provider, displayName, settingsNs, settingsPath}])`
- `ctx.llm.registerAdapter([provider], adapter)`

（`src/llm-adapter.ts:1440-1449`、`src/buddy-adapter.ts:1449-1457`、`src/trae-adapter.ts:1378-1389`）

唯一的 HTTP 端点是 **Jet Hub 管理面**：`POST /api/jet-hub`（`src/jet-hub-rpc.ts:95`、`:556-601`），走的是宿主的 `connection.fetch.register()`，且**只做账号/模型管理，不做推理转发**。

**所以：外部请求 → 各平台私有协议的「转接」能力，在本插件里是「宿主调 `adapter.stream()` → adapter 转成平台私有协议」**。方向是：
```
宿主（会话/agent）  →  adapter.stream(GenerateOptions)  →  平台私有 HTTP/SSE
```
`GenerateOptions` 是 DSH 的会话形态（`messages: [{role, content: blocks[]}]`、`system`、`tools`、`reasoningEffort`、`maxTokens`、`signal`），**不是** OpenAI 的 `chat/completions` 请求体。适配器负责把它序列化成各平台的私有格式。

### 6.2 请求头与签名

**CodeArts：华为云 SDK-HMAC-SHA256**（`src/sign.ts:28-68`）
```
CanonicalRequest = method \n uri \n query \n sorted(headers) \n \n SignedHeaders \n payloadHash
StringToSign     = "SDK-HMAC-SHA256\n" + dateStamp + "\n" + sha256(canonicalRequest)
Authorization    = "SDK-HMAC-SHA256 Access={ak},SignedHeaders={list},Signature={hmac}"
```
必需头：`host` / `x-sdk-date` / `x-sdk-content-sha256` / `x-security-token`（`:44-48`）。
**额外的签名头参与 canonical 计算**：`glm-5.3-flash` 必须带 `maas_type: benefit` 且该头**参与签名**，否则后端返回 `InferHub.002002009.404 model is not registered`（`src/llm-adapter.ts:45-52`、`:923-940`）。
推理请求还带 `Chat-Id` / `Session-Id` / `lang: en`（`:942-944`）。

**CodeBuddy 系：Bearer + 归属头族**（`src/buddy-adapter.ts:1094-1111`）
```
Authorization: Bearer {access_token}
Accept: text/event-stream
X-Domain: {credential.domain ?? product.apiDomain}
X-Product-Code: {product.productCode}
X-Agent-Purpose: conversation
X-IDE-Name / X-IDE-Type: {product.attributionName}
X-IDE-Version: {product.clientVersion}
X-Product: {product.attributionName}      ← 是归属名，不是部署类型！
User-Agent: resolveUserAgent(product, model)  ← 按模型族分档
```
⚠️ 三处注释记录的坑（前两条来自代码注释，第三条来自 `AGENTS.md` 的独立章节）：
- `X-Product` 是**用量归属名**（产品名），历史实现把它发成 `SaaS`（部署类型语义）导致后台归因不到产品，显示为 `-`（`src/product.ts:112-117`、`src/buddy-adapter.ts:1100-1102`）
- **UA 必须含产品品牌字样**，否则腾讯后台「使用端」列显示为 `-`（`src/product.ts:93-98`）；且必须**按模型族分档**——国际版同一账号下走 `gpt-*` 与 `glm-*` 的官方客户端形态并不一致（`src/product.ts:100-111`、`:70-71`、`:378-388`）
- **`X-Domain` 必须跟随产品，而非凭据**（`AGENTS.md:1256`）——这是一个独立章节的坑

**LobsterAI：Bearer + 两个私有头**（`src/lobsterai.ts:446-456`）
```
Authorization: Bearer {access_token}
Accept: text/event-stream, application/json
User-Agent: LobsterAI/0.1.0
X-LobsterAI-Client-Capabilities: kimi-k3-agentic-v1,thinking-level-control-v1
X-LobsterAI-Client-Version: {动态真值}
```
⚠️ 这两个头**不是可选的元数据**（`src/lobsterai.ts:458-473`、`src/lobsterai-product.ts:100-117`）：
- `kimi-k3-agentic-v1` 是**模型列表的准入条件**——不带该头时 `/api/models/available` 只返回 25 个模型且**没有 `kimi-k3`**
- `thinking-level-control-v1` 是**思考档位协议的前提**——`reasoning_effort: "off"`（关闭思考）在不带该能力时服务端直接 HTTP 500

`X-LobsterAI-Client-Version` 用**动态真值**（从更新接口拉取，12h 缓存，`src/lobsterai.ts:547-604`），而 `User-Agent` 刻意保持 `LobsterAI/0.1.0` 不跟着改——「若同时改两处，一旦服务端行为变化将无法归因是哪一个导致的」（`src/lobsterai-product.ts:119-129`）。

**Qoder：Bearer + 请求 ID**（`src/qoder.ts:303-317`）
```
Authorization: Bearer {security_oauth_token ?? access_token}
Accept: text/event-stream
X-Request-ID / X-Session-ID / User-Agent: qoder/1.0.0
```

**TRAE：Cloud-IDE-JWT + 十余个 X-\* 身份头**（`src/trae.ts:176-208`）
```
Authorization: Cloud-IDE-JWT {access_token}
X-Cloudide-Token / X-Ide-Token: {access_token}    ← 三处同值，缺任一可能被拒
X-Uid / X-App-Id / X-App-Version / X-Ide-Version / X-Ide-Version-Code
X-App-Version-Code / X-Ide-Version-Type / X-Device-Type / X-OS-Version
X-Device-Brand / Request-Traffic-Type / X-Machine-Id / X-Device-Id
```

### 6.3 SSE 流式响应转换

**三种 SSE 形态**：

| provider | SSE 形态 | 消费实现 |
|---|---|---|
| `codearts` / `buddy` / `lobsterai` | 标准 OpenAI SSE | 各适配器内联（3 份同源实现） |
| `qoder` | OpenAI SSE + **每帧一层信封** | `unwrapQoderEnvelopeStream` → `consumeOpenAiSse` |
| `trae` | **SOLO 自定义事件**（`output`/`token_usage`/`done`/`error`） | 自行解析并转成 OpenAI chunk |

**共享工具 `src/sse.ts`**（`docs/adding-a-new-provider.md:358-362` 列了 4 个）：
- `readWithIdleTimeout(reader, timeoutMs, label, signal, phase)`（`:26-57`）——带空闲超时的流读取。**首 token 与 chunk 间用不同超时**（`SsePhase = 'first-token' | 'chunk'`）。超时抛可重试的 `LlmError('TIMEOUT')` 并 `reader.cancel()` 释放连接。注释说明：网关会在连接空闲一段时间后静默掐断，不主动检测空闲则 `reader.read()` 无限期挂起，generator 永不返回，web 端表现为「后续指令无响应」。
- `resolveToolPairing(messages)`（`:91-123`）——剔除无法配对的工具调用/结果。**这是一条救命机制**：工具执行失败时 harness 会把 assistant 的 tool_calls 持久化却写不回结果消息，这条坏历史随后被**每次请求原样重放**，后端对之后每一条用户消息都返回 400——表现为「任务突然中断，此后发送任何内容都没有回复」，整个会话报废。适配器是最后一道防线。
- `normalizeToolArguments(raw)`（`:125-138`）——空串/截断/非对象 → `'{}'`
- `isTruncatedArguments(raw)`（`:158-167`）——**只把「非空但无法解析」视为截断**。区分对待很重要：空串是无参数工具的合法形态（补 `{}` 即可）；非空无法解析说明分片丢失，绝不能补 `{}`——那等于伪造一个「看起来合法」的调用，harness 报 `missing required property` 而真正的病因被掩盖。正确做法是报告 `max-tokens` 让 dsh 重试。

**`openai-compat.ts` 是共享的 OpenAI 协议层**（`src/openai-compat.ts:1-30`）：
- 只服务 **qoder** 适配器；`buddy-adapter` / `lobsterai-adapter` **刻意不改用它**——那两份实现已被大量单测与线上流量验证，重构属于与本任务无关的高风险改动（`AGENTS.md:76-80`）
- `serializeMessages`（`:135-232`）：处理孤儿工具调用清理、正文为空且有 tool_calls 时 `content` 必须为 `null`、工具结果内嵌图片提升为独立 user 消息（`role:'tool'` 的 content 只能是字符串且必须紧跟其 assistant tool_call）
- `consumeOpenAiSse`（`:302-554`）：完整的 SSE → StreamChunk 转换

**承载的实测教训（都有真实缺陷背景）**：
- **`typeof x === 'string'` 而非 `!== undefined`**：真实 SSE 里一个模型要么走 `content`、要么走 `reasoning_content`，**另一侧恒为 `null`**。只判 undefined 会让 `.length` 在 null 上崩溃（每轮对话第一帧就报 `Cannot read properties of null`）（`:20-23`、`:430-432`）
- **`function.name` 只允许非空覆盖**：后续分片带空串 `""` 会清空已解析出的工具名 → `unknown tool ""`（`:26-27`、`:472-476`）
- **Qoder 风格错误帧**：不是 OpenAI 的 `{error:{message}}`，而是顶层 `{code, message, type}` + 独立 `event: error` 行。只判 `data.error` 会让整帧被当成「无内容」静默丢弃，用户看到「没回复就终止」（`:361-376`、`:408-421`）
- **`finish_reason` 映射**（`:539-552`）：三种「不完整」都必须报告 `max-tokens` 而非 `tool-calls`——`'length'`（显式截断）、未收到 `finish_reason`（中途断流）、参数无法解析（分片丢失）。报告 `tool-calls` 会让 harness 执行缺参调用并报 schema 错误，模型收到莫名错误后陷入重试循环。

**TRAE 的自定义 SSE**（`src/trae.ts:1511-1574`）：
```ts
type TraeSSEEventType = 'metadata' | 'timing_cost' | 'output' | 'extra_info'
                      | 'token_usage' | 'done' | 'error'
```
`parseTraeSSELine(eventName, dataLine)` 按事件名分派；`output` 事件的 `tool_calls` 需要 `function_call → function` 字段改名并清理 SOLO 专属字段（`namespace` / `partial_arguments`）（`:1581-1598`）；`buildOpenAIChunk`（`:1605-1633`）反向生成标准 OpenAI chunk。

### 6.4 思考/推理字段与工具调用字段

**思考字段的处理是「一平台一策」，不能通用化**：

| provider | 处理 | 依据 |
|---|---|---|
| `codearts` | `include: ['reasoning.encrypted_content']` + `reasoning_summary: 'auto'`；assistant 历史必须携带 `reasoning_content`，缺失报 `Missing reasoning_content field` | `src/llm-adapter.ts:889-890`、`:84-92` |
| `buddy` | **主动补档**：composer 未选档位时补 `reasoning_effort = defaultEffortFor(model)`，因为 deepseek 系不带档位 = 不思考。实测「`reasoning_effort` 是真正的开关，`thinking` 字段单独不生效」 | `src/buddy-adapter.ts:996-1021` |
| `lobsterai` | **只透传，不主动补档**——「buddy 那套是针对腾讯后端的实测，未在 LobsterAI 上验证，照搬会造成非法参数 400」 | `src/lobsterai-adapter.ts:899-904` |
| `qoder` | 走 WASM 加密请求体 | `src/qoder-adapter.ts:286-310` |

**LobsterAI 的思考档位有一个 wire 值 vs 展示值的分离**（`src/lobsterai-adapter.ts:53-110`、`:674-701`）：
- **`id` = `openclawLevel`（wire 值）**：DSH 会把选中的 id 原样写进请求体的 `reasoning_effort`，故必须是服务端认的取值。⚠️ wire 侧**没有 `max`**——实测直接发 `reasoning_effort: 'max'` 与不带参数**无差异**
- **`name` 用 `level`（产品侧值）**：远端把 `level: 'max'` 映射到 `openclawLevel: 'xhigh'`，用户在产品侧看到的就是 **Max**
- 历史缺陷（Issue #IKHCZF）：早期用 `openclawLevel` 同时查两个表，最强档显示成了 `XHigh` 而不是 `Max`

**工具调用字段的差异**：
- OpenAI 系（codearts / buddy / lobsterai / qoder）：`tools: [{type:'function', function:{name, description, parameters}}]`，assistant 历史的 `tool_calls` 同形
- **TRAE 需要重写**（`src/trae.ts:1342-1374` 的 `transformToSOLOBody`）：
  1. `messages.content` 字符串 → `[{type:"text",text:...}]`（已是数组则透传）
  2. `stream` 强制 `true`
  3. `model` → `config_name` + `model` **双字段**
  4. `function` 取 `channel`（缺省 `solo_work_lite`）—— **同一模型只在列出它的通道里可调用**（`AGENTS.md:539-612`）
  5. `tools` / `tool_choice` 归一化（`"none"` 删 tools；`auto`/`required` 保留；`{type:'function'}` 提取 name）
  6. assistant 消息中 `tool_calls.function` → **`function_call`**（SOLO 字段名）
  7. `tools[].parameters` 的 object → **JSON string**（SOLO 要求）

**Qoder 的加密推理**（`src/qoder-adapter.ts:286-310`）：
```
POST {encryptedInferBase}/algo/api/v2/service/pro/sse/agent_chat_generation
     ?FetchKeys=llm_model_result&AgentId=agent_common&Encode=1
body: <WASM 加密>
```
⚠️ **`business: { type: 'agent' }` 必填**——缺了服务端会把请求路由到故障节点 `oa_qwen-plus-2025-04-28` 并返回 `[FAIL]node:... msg:Execution failed`。`qfmodel` 曾因此被误判为「服务端故障」（而 IDE 里同一模型完全正常）。
⚠️ 响应**无需解密**，只在每帧外套一层信封，由 `src/qoder-envelope.ts:64-140` 剥离。签名头必须**原样透传**，用普通 Bearer 覆盖会被判签名无效（`AGENTS.md:25`）。

### 6.5 图片输入

统一形态是 OpenAI 的 `{type:'image_url', image_url:{url}}` data URL（`src/openai-compat.ts:50-105`）：
- `{type:'image'}` 与裸 base64 字符串都返回 HTTP 500（`:52-54`）
- 图片字节由宿主桥接：`makeReadImage(ctx)` → `ctx.attachments.readImage()`（`src/index.ts:103-116`）
- ⚠️ **读不到字节必须抛错，绝不静默丢弃**——早期契约允许返回 undefined 表示「读不到」，调用方据此 `continue`，正是静默丢图的源头（`src/buddy-adapter.ts:177-188`、`:930-950`）
- 模态按**模型**判定，不是按 provider 一刀切：`inputModalitiesFor(model)`（`src/buddy-adapter.ts:714-724`）
- `IMAGE_CAPABILITY_OVERRIDES` 是个显式白名单（目前只有 `glm-5.1`），因为 scoped 端点对它误报 `supportsImages=false` 而实测能看图。为什么用白名单而不是「兜底表 true 优先」的通用规则：通用规则会让兜底表永久压过远端，一旦某模型真的下线或能力变更，用户会被放行后被上游 400 拒绝——错误更晚、更难懂（`:700-712`）

---

## §7 RPC 与 UI 通道

### 7.1 管理面如何暴露给 UI

**Host 侧注册 HTTP 端点**（`src/jet-hub-rpc.ts:556-601`）：
```ts
connection.fetch.register({
  path: '/api/jet-hub',
  methods: ['POST'],
  requestBody: 'buffered',
  async fetch(request) { ... }
})
```
信封格式：
```json
// 请求
{ "type": "client-request", "rpcId": "...", "method": "jet-hub",
  "payload": { "method": "account.create", "payload": { "provider": "buddy" } } }
// 响应
{ "type": "server-response", "rpcId": "...",
  "result": { "ok": true, "value": {...} } }
// 或错误
{ "type": "server-response", "rpcId": "...",
  "result": { "ok": false, "error": { "code": "...", "message": "...", "details": {} } } }
```
（`src/jet-hub-rpc.ts:569-599`、`:1270-1275`）

⚠️ 错误必须返回**规范的 RPC 错误响应**而不是裸 500 文本，否则客户端 `unwrapRpcResult` 无法识别错误，表现为「点击无反应」（`src/jet-hub-rpc.ts:590-599`）。

**惰性注入而非静态 inject**（`src/jet-hub-rpc.ts:499-526`、`src/index.ts:25-31`）：`connection` 服务只存在于 Web bundle，headless/CLI profile 里并不存在。静态 `inject` 会让插件在那些 profile 里永久 pending，进而让整个 profile 以 `plugin tree failed to load: 1 entry did not activate` 启动失败。所以用 `ctx.inject(['connection'], ...)`，其余 profile 只是不注册该端点。

**Client 侧**（`plugin-src/client/index.js:14-29`）：
```js
export const inject = ['slots', 'connection']
export function apply(ctx) {
  const rpcCall = async (endpoint, payload, signal) => {
    const raw = await callManagementRpc(ctx.connection, JET_HUB_RPC_CHANNEL, endpoint, payload, signal)
    return unwrapRpcResult(raw)
  }
  ctx.slots.inject('settings.section', () => ctx.slots.register({
    name: 'settings.section', id: 'jet-hub', order: 50,
    label: () => 'Jet Hub', inject: () => ({ rpcCall }),
  }, JetHubPage))
}
```
`callManagementRpc` 走 `connection.rpc.call('/api', 'jet-hub', {method, payload}, signal)`（`plugin-src/management-rpc.mjs:24-30`）。

### 7.2 RPC 端点清单（16 个）

> 下表 14 行覆盖 **16 个**端点：`account.retest` / `account.retestAll` 合并为一行，`account.reset` / `account.resetAll` 合并为一行。端点全集对应 `handleMethod` 的 16 个 `case` 分支（`src/jet-hub-rpc.ts:606,612,797,803,811,835,894,909,920,927,933,954,1007,1078,1181,1247`）。

| 端点 | 语义 | 位置 |
|---|---|---|
| `account.list` | 列某 provider 账号（含 `source`） | `src/jet-hub-rpc.ts:606-610` |
| `account.create` | 新建账号（两步式，立即返回 `loginUrl`） | `:612-795` |
| `account.update` | 改昵称 / enabled | `:797-801` |
| `account.delete` | 删账号 + 清凭据 | `:803-807` |
| `account.reorder` | 拖拽排序（顺序 = 选号优先级） | `:811-833` |
| `account.refresh` | 刷新**指定账号**的凭据 | `:835-892` |
| `login.poll` | 轮询登录是否完成（查凭据是否已写入） | `:894-904` |
| `account.retest` / `account.retestAll` | 限流标记重测（发真实请求） | `:909-925` |
| `account.reset` / `account.resetAll` | 限流标记重置（不发请求） | `:927-937` |
| `credits.status` | 签到状态 | `:954-1005` |
| `credits.claimAll` | 一键领取积分 | `:1007-1076` |
| `credits.balances` | 积分余额（含包明细） | `:1078-1176` |
| `model.list` | 设置页模型列表（**走 `listAllModels`，不套黑名单**） | `:1181-1243` |
| `model.setDisabled` | 模型开关 | `:1247-1261` |

`account.create` 的分派结构（`:612-795`）：
```ts
const product = productById(provider)
if (product !== undefined) { /* buddy / workbuddy 共用同一分支 */ }
else if (provider === 'codearts') { ... }
else if (provider === LOBSTERAI.id) { ... }
else if (provider === QODER.id) { ... }
else if (provider === TRAE.id) { ... }
else { return bad-request: unknown provider }
```
注意 `buddy` / `workbuddy` 靠 `productById()` 统一处理（这是同源产品的收益），其余四个各一分支。

### 7.3 对「网关管理面」的借鉴

1. **单端点 + 方法分派**（`POST /api/jet-hub` + `payload.method`），而不是 16 个 REST 路径。好处：新增能力不改路由、鉴权与信封统一、前端只有一个调用函数。
2. **统一信封 + 规范化错误对象**，且错误码分两类：传输层（`gateway/bad-request`）与处理器层（`jet-hub/handler-failed`）。前端 `unwrapRpcResult` 一个函数搞定。
3. **能力矩阵前置门控**（`plugin-src/client/credits-capabilities.js:54-65`）：`CREDITS_CAPABILITIES` 声明每个 provider 的 `balance` / `dailyCheckin`，前端在**发请求之前**判定。理由（`:4-14`）：历史缺陷是「对不支持的 provider 无条件发请求」，每打开一次面板就留一条必然失败的控制台报错、把每个账号卡片的积分渲染成「查询失败」。**修法不是在 UI 上吞掉错误，而是不发起这个请求。** 判定一律**默认关闭**——忘登记时最坏结果是「暂时看不到积分」，而不是「每次打开面板都发一个必然失败的请求」。
4. **两步式异步任务 + 轮询**：`account.create` 立即返回 `{accountId, loginUrl}`，前端 `window.open` 后 1s 轮询 `login.poll`（最多 5 分钟，`plugin-src/client/jet-hub.js:727-738`）。轮询判据是「凭据是否已写入」（`src/jet-hub-rpc.ts:899-903`），简单且不依赖后台任务状态机。
5. **前端不得有破坏性兜底**（`plugin-src/client/jet-hub.js:710-725`）：弹窗被拦截时展示**可点击链接**（`loginUrlForManual`），绝不 `window.location.href = loginUrl`——那会把整个设置页导航走。且有源码级单测锁死这条（`AGENTS.md:1109-1111`）。

---

## §8 扩展点：新增一个 provider 需要改哪些文件

官方指南 `docs/adding-a-new-provider.md` 给出两条路径。**注意：该文档只覆盖 4 个 provider（写于 qoder/trae 之前），实际现有 6 个。** 我按代码现状补全。

### 路径 A：同源产品（如再加一个腾讯系 IDE 产品）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `src/product.ts` | 加 `BuddyProduct` 常量（`id` 不能与现有重复；`defaultCredentialRef` 用大写前缀；`fallbackModels` **必须实测**，不能照抄）；把常量加进 `ALL_PRODUCTS`（`:399`） |
| 2 | `src/index.ts` | ① `registerProviderSettings(ctx, ..., 'llm-{id}')`（`:130-132`）；② `new BuddyAuth(ctx, {product})`（`:251`）；③ `registerBuddyLlm(ctx, {...product})`（`:252`）；④ 加进 `refreshAllCredentials()`（`:400-419`）；⑤ 加进 `modelAdapters`（`:458-467`）；⑥ 加进 `registerJetHubRpc` 参数（`:469`）；⑦ 加进 `ctx.effect` cleanup（`:432-441`） |
| 3 | `src/jet-hub-rpc.ts` | ① `account.create` 走 `productById` 分支**无需改动**，但 `registerJetHubRpc` 签名要加参数（`:503-520`）；② `account.refresh` 的 switch 加 case（`:860-881`）；③ `credits.*` 各端点加分支（如该产品有积分能力） |
| 4 | `plugin-src/client/credits-capabilities.js` | 登记 `{balance, dailyCheckin}`（`:54-65`）；两项能力彼此独立 |
| 5 | `plugin-src/client/jet-hub.js` | 加进 `PROVIDERS` 数组（`:69-76`），含 icon |
| 6 | 测试 | 纯函数单测 + auth 单测 + adapter 单测 + E2E |

**注**：`src/buddy.ts:1-16` 与 `src/product.ts:20-29` 记录了「常量从 buddy.ts 迁移到 product.ts」的**未完成迁移**——两处目前必须手工保持一致。

### 路径 B：全新脉系

| # | 文件 | 参考模板 | 必需内容 |
|---|---|---|---|
| 1 | `src/xxx-product.ts` | `lobsterai-product.ts` / `qoder-product.ts` / `trae-product.ts` | 平行接口 + 常量 + `fallbackModels` + `xxxProductById()` |
| 2 | `src/xxx.ts` | `lobsterai.ts` / `trae.ts` | 端点常量、超时、**凭据结构（必含 `access_token`）**、纯函数（过期判定 / 请求头构造 / 信封解析 / 响应解析） |
| 3 | `src/xxx-oauth.ts` | `lobsterai-oauth.ts` / `qoder-oauth.ts` | `startXxxLoginFlow()`（立即返回 `loginUrl`）+ `runXxxLoginFlow()`（阻塞版） |
| 4 | `src/xxx-auth.ts` | `buddy-auth.ts`（推荐，最完整） | `Service` 子类；`login` / `startLogin` / `status` / `refresh` / `refreshAccountCredential` / `refreshAll` / `logout` / `stop` / `scheduleRefresh` / `fetchModels` |
| 5 | `src/xxx-adapter.ts` | `qoder-adapter.ts`（最简洁） | `LlmAdapter` 子类；`providerInfo` / `listModels` / `listAllModels` / `resolveModel` / `prepareCall` / `stream`；`registerXxxLlm(ctx, options)` |
| 6 | `src/xxx-errors.ts`（可选） | `lobsterai-errors.ts` | 错误分类纯函数 + `shouldRotateXxx` / `recordsXxxRateLimit` / `isXxxTerminalError` |
| 7 | `src/xxx-credits.ts`（可选） | `lobsterai-credits.ts` / `trae-credits.ts` | 签到 / 余额 |
| 8 | `src/index.ts` | — | 7 处接线（同路径 A 的第 2 项） |
| 9 | `src/jet-hub-rpc.ts` | — | 4 处（`account.create` 分支、`account.refresh` case、`credits.*` 分支、签名参数） |
| 10 | `plugin-src/client/credits-capabilities.js` + `jet-hub.js` | — | 能力矩阵 + PROVIDERS |
| 11 | 测试 + 文档 | — | 单测 / E2E / 更新 `product.ts` module header + README |

### 官方检查清单（`docs/adding-a-new-provider.md:479-537`）

最值得内化的 6 条：
- [ ] `refreshAll()` **只按 `refreshable` 过滤，不看 `enabled`**
- [ ] `refreshAccountCredential()` 读写指定 ref，**不碰默认单凭据 ref**
- [ ] `getAvailableAccount` 调用时传 `this.product.id`（**不写死字面量**，WorkBuddy 踩过坑）
- [ ] `account.create` 分支**立即返回 `loginUrl`**；先登记占位条目；失败时删除占位条目
- [ ] 非 `codearts` 的 provider 凭据含 `access_token`；`expires_at` 统一毫秒字符串
- [ ] 续期请求体所需的特殊字段（如 LobsterAI 的 `firstKeyfrom` / `latestKeyfrom` / `uuid`）**在凭据中持久化**，不每次重新生成

### 可复用的「基类」情况

**没有真正的基类。** 只有 4 个共享模块：
- `src/refresh.ts` → `RefreshScheduler`（唯一被 5 个 auth 服务共用的类）
- `src/sse.ts` → 4 个纯函数
- `src/openai-compat.ts` → 序列化 + SSE 消费（**只服务 qoder**，明确不要扩散）
- `src/sign.ts` → 华为签名（只有 codearts 用）

`AccountPool` 被所有适配器以**注入回调**方式使用，不是基类。

---

## §9 可迁移到我们网关的设计清单

### 9.1 强烈建议直接借鉴（含理由）

| # | 设计 | 位置 | 为什么值得借鉴 |
|---|---|---|---|
| 1 | **凭据与账号索引分离** | `docs/adding-a-new-provider.md:78-87`、`src/account-pool.ts:114-115` | 凭据是敏感且不可手工编辑的（refresh_token / 私钥 / 设备指纹），账号元数据需要 UI 频繁读写与手工编辑。分开存储后，导出/备份账号配置不会泄漏凭据。我们用 Python 可映射为「加密的凭据表 + 明文的账号配置表」，靠 `credential_ref` 字符串关联 |
| 2 | **`RefreshScheduler` 的 generation 代号** | `src/refresh.ts:43-113` | 解决「登出后调度器复活」这类难复现的竞态。任何带「定时任务 + 可取消」的组件都该抄 |
| 3 | **失败分类 + 终态判定** | `src/refresh.ts:8-25`、`src/lobsterai-errors.ts:100-171` | 三层：异常网络（1min 重试）→ 普通失败（10min 重试）→ 终态（停止并提示重新登录）。且失效判定用**结构化判据**（`error.name` + message 正则）而非异常类型，避免跨模块异常 identity 问题 |
| 4 | **提前量 + 随机抖动** | `src/refresh.ts:32-40` | 「过期前 1 小时触发，触发时刻叠加 0-59 秒随机偏移」。多账号场景下避免刷新尖峰 |
| 5 | **账号 × 模型级限流标记（而非账号级禁用）** | `src/types.ts:60`、`src/account-pool.ts:602-619` | 同一账号对不同模型的限额不同；账号级禁用会损失可用容量。且标记是**快照**，需配「重测 / 重置」两个主动操作 |
| 6 | **重测/重置的语义严格区分** | `src/account-probe.ts:1-30`、`:254-272` | 重测 = 发真实请求验证；重置 = 直接清除。且重测必须**不产生副作用**（不传 accountPool，避免污染其他账号标记） |
| 7 | **拖拽顺序即选号优先级** | `src/account-pool.ts:373-406`、`:548-557` | 让用户对选号有确定性控制。关键是**不要**在选号时按其他维度重排，否则手动顺序形同虚设 |
| 8 | **`excludeAccountIds` 在池层排除** | `src/account-pool.ts:521-530` | 换号重试的必需能力。调用方只能拿到「池认为最优的一个」，无法枚举候选自己去重，所以排除必须在池层做 |
| 9 | **换号次数上限** | `src/lobsterai-adapter.ts:942-951` | 防雪崩：账号池很大时若逐个试完，一次用户请求会打出 N 个上游请求。且注意「计数是否包含首个账号」这个 off-by-one |
| 10 | **进程内权威副本 + 同步提交** | `src/account-pool.ts:127-141`、`:190-198` | 解决「配置存储的读取快照滞后于写入」导致的丢更新。要点：读源用进程内副本，写时**在第一个 await 之前**同步更新副本 |
| 11 | **`settings` 整体替换必须携带全部字段** | `src/account-pool.ts:184-198`、`:242-252` | 如果我们的配置存储也是「整体替换」语义，必须显式携带未修改的字段，否则静默清空 |
| 12 | **两步式登录契约** | `AGENTS.md:1082-1111`、`src/jet-hub-rpc.ts:612-795` | 「创建账号」接口必须在用户授权完成**之前**返回 `loginUrl`，先登记占位条目，失败时删除占位条目。这是浏览器 transient activation 的硬约束，任何「点按钮 → 弹登录窗」的网关管理面都适用 |
| 13 | **模型黑名单制（而非白名单）** | `src/account-pool.ts:21-28` | 「只有显式关闭的才隐藏，未记录的一律默认打开」——服务端新增模型时无需任何配置即自动可见。白名单会把新模型静默挡在门外 |
| 14 | **`listModels` 与 `listAllModels` 分离** | `src/jet-hub-rpc.ts:1197-1214` | 管理面需要「全量目录（含被关闭项）」，业务面需要「过滤后目录」。若管理面复用过滤后的结果，被关闭的模型会连同开关一起消失，用户**再也无法重新打开** |
| 15 | **工具调用配对清理 + 截断判定** | `src/sse.ts:91-123`、`:158-167` | 这是 agent 网关的刚需。孤儿 tool_call/tool_result 会让上游 400 且坏历史被每次请求重放，会话彻底报废。而「空串」与「非空但无法解析」必须区分对待 |
| 16 | **SSE 空闲超时（首 token / chunk 间分档）** | `src/sse.ts:26-57` | 不主动检测空闲则 `read()` 无限期挂起，网关表现为「请求永不结束」。且必须 `reader.cancel()` 释放底层连接 |
| 17 | **`finish_reason` 映射规则** | `src/openai-compat.ts:539-552` | 「截断/断流/参数残缺」一律报告 `max-tokens` 让上游重试，而不是报告 `tool-calls` 让调用方执行残缺调用 |
| 18 | **能力矩阵前置门控 + 默认关闭** | `plugin-src/client/credits-capabilities.js:48-65` | 「未登记的 provider 视为不支持」。忘登记时最坏结果是「暂时看不到」，而不是「每次打开都发一个必然失败的请求」 |
| 19 | **`product` 配置必须由调用方显式传入** | `src/buddy-oauth.ts:175-177`、`src/index.ts:285-287` | 同源产品的最大坑：默认值 + 忘记传参 = 静默携带另一个产品的身份。且**不要写死字面量**（用 `LOBSTERAI.id` 而非 `'lobsterai'`） |
| 20 | **`maxOutputTokens` 必须下发给上游** | `AGENTS.md:191-223`、`src/buddy-adapter.ts:983-995` | 远端下发的输出上限是权威值，适配器必须消费并写进请求体，同时在 `resolveModel` 里声明为默认值。不声明就等于交给网关默认（实测仅 32000） |
| 21 | **对「未验证」保持诚实** | 全项目 | 大量注释写着「实测」「需实测支撑」「不能从代码推理」。凡涉及服务端校验行为的判断，一律标注证据来源 |

### 9.2 部分借鉴（需要改造）

| 设计 | 改造点 |
|---|---|
| 产品配置对象模式 | 我们的「平台配置」用 Pydantic / dataclass 表达更自然；核心思想（**差异收敛到单一真相源**）可直接用 |
| 账号池选号算法 | 需要补一个**租约层**：并发请求分散到不同账号（本插件没有）。可用 Redis/内存的 `SETNX account_id TTL=request_timeout` |
| 错误码词表 | 本插件的 `LlmError` code 集（`MISSING_CREDENTIAL` / `TIMEOUT` / `TRANSPORT` / `AUTH` / `RATE_LIMIT` / `QUOTA_EXCEEDED` / `SERVER` / `INVALID_REQUEST` / `EMPTY_RESPONSE` / `UNSUPPORTED_CONTENT` / `CONTEXT_WINDOW_EXCEEDED`）值得对齐，但需映射到我们网关的错误体系 |
| SSE → 统一 chunk 的转换 | `consumeOpenAiSse` 的产物是 DSH 的 `StreamChunk`（`block-start` / `text-delta` / `reasoning-delta` / `tool-call-delta` / `block-end` / `usage` / `finish`）。我们要输出 OpenAI 兼容 SSE，需要再写一层映射（其实更简单，因为上游多已是 OpenAI 格式） |
| RPC 管理面 | 我们的网关可以直接用 FastAPI 的 REST + WebSocket，不必照搬 `connection.fetch.register` 的宿主契约。但「单端点 + 方法分派」和「统一信封」值得保留 |

### 9.3 不建议迁移（本插件特有 / 不可迁移）

| 项 | 原因 |
|---|---|
| **DSH 宿主耦合** | `ctx.llm` / `ctx.credentials` / `ctx.settings` / `ctx.connection` / `ctx.attachments` / `ctx.commands` / `cordis.Service` / `schemastery`——都是 DSH 框架的私有契约。我们的网关是独立进程，必须自建这几层 |
| **各平台的逆向常量** | `client_id` / `plugin_version` / `machine_id` 生成算法 / `x_*` 伪装头 / 设备指纹派生（`src/trae.ts:1096-1194`、`src/qoder.ts:71-95`）——这些是「冒充官方客户端」的产物，随上游版本变化而失效。且**法律与合规风险**需要我们单独评估（见下） |
| **WASM 加密链路** | `src/qoder-wasm.ts` + `src/qoder-auth-wasm.wasm`（298KB）。虽然注释强调「不是破解密码学——WASM 自己导出了成对编解码函数，我们只是调用它」，但它是特定客户端版本的产物，升级需重跑提取脚本（`scripts/extract-qoder-wasm.mjs`）并实测签名仍被接受 |
| **华为云 SDK-HMAC-SHA256 签名** | `src/sign.ts` 是通用算法，但 `maas_type: benefit` 这类「必须参与签名的业务头」是 CodeArts 特有 |
| **同名模型的展示名消歧** | `AGENTS.md:400-430`、`buildDisplayNames`——是 DSH composer 只渲染 `name` 字段导致的 UI 层补丁。我们有自己的 UI，可以做得更干净 |
| **`openai-compat.ts` 的三份同源实现现状** | `src/openai-compat.ts:13-16` 明确写着「既有适配器（buddy / lobsterai）刻意不改用它」——这是**技术债**而非设计。我们从头做时应只有一份实现 |
| **积分/签到（credits）整套** | `src/credits.ts` / `lobsterai-credits.ts` / `codearts-credits.ts` / `trae-credits.ts` 是四套互不相同的签到协议，对「模型转接」目标无关 |
| **TRAE 的 Max 模式 / 通道机制** | `src/trae-product.ts:102-132`、`src/trae.ts:1305-1322`——是 TRAE 特有的计费与路由语义 |

### 9.4 迁移路线建议（按依赖顺序）

```
第 1 步：抽象层
  ├─ 平台配置对象（每平台一个 dataclass，含 endpoint / 认证类型 / 头族 / 兜底模型表）
  ├─ 凭据模型（统一 expires_at 毫秒字符串 + refreshable 判据）
  └─ 错误码词表 + 失败分类（异常网络 / 可重试 / 终态）

第 2 步：认证层
  ├─ 通用 RefreshScheduler（generation 代号 + 提前量 + 抖动 + 三档重试）
  ├─ 每个平台的 login 实现（先做 1 个跑通，再复制模式）
  └─ 凭据存储（加密凭据表 + 明文账号表 + credential_ref 关联）

第 3 步：账号池
  ├─ CRUD + 顺序 + 模型黑名单
  ├─ getAvailableAccount（filter + 取第一 + excludeAccountIds）
  └─ 【新增】租约层（本插件没有，我们并发场景必需）

第 4 步：适配器层
  ├─ listModels / resolveModel / stream 契约
  ├─ OpenAI 兼容的序列化 + SSE 消费（一份实现，不分叉）
  └─ 逐平台私有协议转换

第 5 步：对外 API + 管理面
  ├─ OpenAI 兼容 HTTP 层（本插件完全没有，必须自建）
  │   model 字段需承载「平台 + 原生 id」
  └─ 管理面（单端点 + 方法分派 + 能力矩阵门控 + 两步式登录契约）
```

---

## 证据附录：关键 file:line 清单

### 架构与入口
| 内容 | 位置 |
|---|---|
| 三层模型图 | `docs/adding-a-new-provider.md:57-76` |
| 双文档系统与凭据分离 | `docs/adding-a-new-provider.md:78-87` |
| 续期不得按 enabled 过滤 | `docs/adding-a-new-provider.md:89-96`、`AGENTS.md:136-154`、`README.md:146-163` |
| 两步式登录（浏览器约束） | `docs/adding-a-new-provider.md:98-105`、`AGENTS.md:1082-1111` |
| `apply()` 全量接线 | `src/index.ts:121-430` |
| `inject` 声明（`connection` 刻意不列入） | `src/index.ts:25-31` |
| 六个 settingsNs 注册 | `src/index.ts:129` |
| `refreshAllCredentials()` | `src/index.ts:400-419` |
| 续期定时器启动判据（不看 enabled） | `src/index.ts:386` |
| `modelAdapters` 传递（`listAllModels`） | `src/index.ts:417-426` |
| `registerJetHubRpc` 调用 | `src/index.ts:428` |
| `ctx.provide('accountPool')` | `src/index.ts:429` |
| WorkBuddy 旧版账号清理 | `src/index.ts:136-148`、`src/account-pool.ts:289-311` |

### 产品配置层
| 内容 | 位置 |
|---|---|
| `BuddyProduct` 接口 | `src/product.ts:74-144` |
| `CODEBUDDY` / `WORKBUDDY` | `src/product.ts:256-272` / `:369-396` |
| 同源产品的 endpoint 差异说明 | `src/product.ts:14-18` |
| UA 按模型族分档 | `src/product.ts:100-111`、`:70-71`、`:378-388` |
| `resolveUserAgent()` | `src/product.ts:416-421` |
| `LobsteraiProduct` 为何不复用 BuddyProduct | `src/lobsterai-product.ts:4-20` |
| `LOBSTERAI_CLIENT_CAPABILITIES` 的两个能力 | `src/lobsterai-product.ts:100-117` |
| `QoderProduct` 的两条推理路径 | `src/qoder-product.ts:8-12`、`:135-154` |
| `clientId` 的 `J_a` / `G_a` 语义 | `src/qoder-product.ts:155-183` |
| `TraeProduct` 的通道机制 | `src/trae-product.ts:88-102`、`:204-227` |
| `TRAE` 常量 | `src/trae-product.ts:263-286` |

### 认证层
| 内容 | 位置 |
|---|---|
| `oauth.ts` 是 CodeArts 专用 | `src/oauth.ts:5-16` |
| PKCE 生成 | `src/oauth.ts:58-62` |
| DPoP 密钥对 + JWS 签发 | `src/oauth.ts:65-85` |
| `requestToken` 与终态判定 | `src/oauth.ts:96-138` |
| 凭据组装（含 refresh_token / code_verifier / dpop JWK） | `src/oauth.ts:173-188` |
| CodeArts portal URL 构造 | `src/login.ts:262-271` |
| 回调端口 ≥10000 | `src/login.ts:337-364` |
| `startOAuthFlow`（两步式） | `src/login.ts:393-420` |
| ticket 轮询（旧流程） | `src/login.ts:77-113` |
| Buddy 端点常量 | `src/buddy.ts:29-39` |
| Buddy 错误码 11217 / 12151 | `src/buddy.ts:55-57` |
| Buddy 请求头常量 | `src/buddy.ts:61-71` |
| `BuddyCredential` | `src/buddy.ts:97-120` |
| `credentialExpiresAtMs` + JWT 后备 | `src/buddy.ts:142-178` |
| `fetchAuthState` | `src/buddy-oauth.ts:137-167` |
| `loopGetToken` | `src/buddy-oauth.ts:178-222` |
| `getAccount` | `src/buddy-oauth.ts:231-277` |
| `refreshToken`（X-Refresh-Token 头） | `src/buddy-oauth.ts:289-329` |
| `fetchModels` 双端点取并集 | `src/buddy-oauth.ts:348-424` |
| `decorateLoginUrl`（国际版追加参数） | `src/buddy-oauth.ts:525-538` |
| LobsterAI 端点常量 | `src/lobsterai.ts:32-47` |
| `LobsteraiCredential`（含 uuid / keyfrom） | `src/lobsterai.ts:79-114` |
| 统一信封解析 | `src/lobsterai.ts:162-181` |
| 续期请求体（身份字段） | `src/lobsterai.ts:234-270` |
| uid 四级回退 | `src/lobsterai.ts:313-335` |
| LobsterAI 请求头（含两个私有头） | `src/lobsterai.ts:446-484` |
| 版本号解析器（12h 缓存） | `src/lobsterai.ts:547-604` |
| LobsterAI 登录 URL | `src/lobsterai-oauth.ts:104-116` |
| authCode 换 token（5 字段） | `src/lobsterai-oauth.ts:130-185` |
| `startLobsteraiLoginFlow` | `src/lobsterai-oauth.ts:232-313` |
| Qoder 端点常量 | `src/qoder.ts:14-31` |
| PKCE（去 padding） | `src/qoder.ts:56-69` |
| 设备会话（machineId 自造） | `src/qoder.ts:71-95` |
| 授权 URL / 轮询 URL | `src/qoder.ts:109-134` |
| `QoderCredential`（双写 token） | `src/qoder.ts:144-164` |
| 续期请求体（refresh_token + machine_id） | `src/qoder.ts:288-293` |
| `applyQoderRefresh`（保留 uid/machine_id） | `src/qoder.ts:325-342` |
| `pollQoderDeviceToken`（404 = 继续轮询） | `src/qoder-oauth.ts:119-164` |
| `startQoderLoginFlow` | `src/qoder-oauth.ts:205-236` |
| TRAE 端点常量 | `src/trae.ts:44-70` |
| `TraeCredential`（machine_id / device_id） | `src/trae.ts:89-127` |
| TRAE 完整请求头族 | `src/trae.ts:176-208` |
| TRAE 签到请求头 | `src/trae.ts:219-262` |
| `exchangeTraeCallback` | `src/trae-oauth.ts:365-440` |
| TRAE 18 参数登录 URL | `src/trae-oauth.ts:99-127` |
| `parseTraeCallbackDetailed`（无 code / PKCE 探测） | `src/trae-oauth.ts:273-345` |
| `listenOrReject`（必须先知 error） | `src/trae-oauth.ts:471-505` |
| `listenWithFallback`（18080 → 随机） | `src/trae-oauth.ts:522-535` |
| `startTraeLoginFlow` | `src/trae-oauth.ts:583-698` |
| machineId / deviceId 派生 | `src/trae.ts:1096-1194` |

### 凭据与续期
| 内容 | 位置 |
|---|---|
| `RefreshScheduler` | `src/refresh.ts:43-114` |
| 三档重试常量 | `src/refresh.ts:1-6` |
| 异常网络判定 | `src/refresh.ts:8-12` |
| 失效判定（结构化，非 instanceof） | `src/refresh.ts:14-25` |
| 首次刷新延迟 + 抖动 | `src/refresh.ts:32-40` |
| `CodeArtsAuth` 全量 | `src/service.ts:64-383` |
| `persistLogin`（login / startLogin 共用） | `src/service.ts:140-172` |
| `refresh` vs `refreshAccountCredential` | `src/service.ts:202-261` |
| `refreshAll` | `src/service.ts:272-318` |
| `BuddyAuth` 全量 | `src/buddy-auth.ts:87-406` |
| `saveCredential`（后台登录回填） | `src/buddy-auth.ts:179-194` |
| `refreshAccountCredential` 的注释（为何不能用 refresh） | `src/buddy-auth.ts:270-291` |
| `refreshAll` 的缺陷复盘 | `src/buddy-auth.ts:293-343` |
| `refresh` 回调必须刷「解析时那个账号」 | `src/index.ts:297-313`（lobsterai）、`:344-357`（qoder）、`:383-387`（trae） |
| CodeArts 凭据结构 | `src/types.ts:332-349` |

### 账号池
| 内容 | 位置 |
|---|---|
| `JET_HUB_NS` | `src/account-pool.ts:19` |
| 黑名单制说明 | `src/account-pool.ts:21-28` |
| settings schema | `src/account-pool.ts:64-75` |
| 进程内权威副本的理由 | `src/account-pool.ts:127-141` |
| `ensureLoaded` | `src/account-pool.ts:160-176` |
| `writeAccounts`（同步提交 + 必须带黑名单） | `src/account-pool.ts:184-198` |
| `disabledModelsFor` | `src/account-pool.ts:206-212` |
| `setModelDisabled`（关闭写 true / 打开删键） | `src/account-pool.ts:232-240` |
| `reorderAccounts`（只动本 provider 下标 + 集合校验） | `src/account-pool.ts:373-406` |
| `findAccountIdByCredential`（字段选择） | `src/account-pool.ts:417-429` |
| `resolveCredentialForAccount`（不检查 enabled） | `src/account-pool.ts:453-469` |
| `getAvailableAccount`（核心选号） | `src/account-pool.ts:532-592` |
| 「不要重引入按重置时间排序」 | `src/account-pool.ts:548-557` |
| `updateModelRateLimit`（局部合并） | `src/account-pool.ts:602-619` |
| `sweepExpiredRateLimits` | `src/account-pool.ts:622-637` |
| TRAE 签到设备代次 | `src/account-pool.ts:648-671` |
| `ProviderAccountEntry` | `src/types.ts:42-75` |
| `JetHubConfig` | `src/types.ts:86-94` |
| 账号顺序 = 选号优先级 | `AGENTS.md:168-189` |

### 模型目录与解析
| 内容 | 位置 |
|---|---|
| CodeArts 双端点 + 缓存 | `src/models.ts:8-25`、`:120-165`、`:206-223` |
| `normalizeModelId`（去日期后缀） | `src/models.ts:41-49` |
| VL 模型过滤 | `src/models.ts:55-58` |
| `listModels` / `listAllModels`（codearts） | `src/llm-adapter.ts:776-799` |
| `resolveModel`（codearts） | `src/llm-adapter.ts:801-809` |
| `resolveModel`（buddy，三级查找） | `src/buddy-adapter.ts:805-854` |
| `maxOutputTokens` 必须声明 | `src/buddy-adapter.ts:819-835`、`AGENTS.md:191-223` |
| 图片能力白名单 | `src/buddy-adapter.ts:700-724` |
| Qoder 恒用静态表 | `src/qoder-adapter.ts:144-177` |
| 同名模型消歧 | `AGENTS.md:400-430` |
| 倍率写进 `name` | `src/qoder-adapter.ts:170-174` |

### 适配器与协议转换
| 内容 | 位置 |
|---|---|
| `CodeArtsAdapter` | `src/llm-adapter.ts:726-1437` |
| CodeArts 请求体（prompt_cache_key / include / tool_stream） | `src/llm-adapter.ts:880-905` |
| CodeArts 签名 + 头 | `src/llm-adapter.ts:923-951` |
| CodeArts 限流换号 | `src/llm-adapter.ts:982-1003` |
| `registerCodeArtsLlm` | `src/llm-adapter.ts:1440-1449` |
| `isRateLimited`（6004 + 中英文文案） | `src/llm-adapter.ts:1451-1499` |
| `registerBuddyLlm` | `src/buddy-adapter.ts:1449-1457` |
| Buddy 请求头族 | `src/buddy-adapter.ts:1089-1126` |
| Buddy `reasoning_effort` 补档 | `src/buddy-adapter.ts:996-1021` |
| `registerLobsteraiLlm` / LobsterAI 请求头 | `src/lobsterai-adapter.ts:1024-1040` |
| LobsterAI 换号循环 | `src/lobsterai-adapter.ts:934-1004` |
| LobsterAI 思考档位 wire vs 展示 | `src/lobsterai-adapter.ts:53-110`、`:674-701` |
| Qoder 加密推理 | `src/qoder-adapter.ts:286-310` |
| Qoder 信封剥离 | `src/qoder-envelope.ts:64-140` |
| TRAE OpenAI→SOLO 转换 | `src/trae.ts:1342-1418` |
| TRAE tool_choice 归一化 | `src/trae.ts:1428-1470` |
| TRAE Max 模式字段 | `src/trae.ts:1305-1322` |
| TRAE SOLO SSE 解析 | `src/trae.ts:1511-1598` |
| TRAE OpenAI chunk 生成 | `src/trae.ts:1605-1633` |
| `registerTraeLlm` | `src/trae-adapter.ts:1378-1389` |
| SSE 共享工具（4 个） | `src/sse.ts:26-57`、`:91-123`、`:125-138`、`:158-167` |
| `serializeMessages`（openai-compat） | `src/openai-compat.ts:135-232` |
| `consumeOpenAiSse` | `src/openai-compat.ts:302-554` |
| 图片 parts 构造 | `src/openai-compat.ts:62-118` |
| `httpErrorCode` | `src/openai-compat.ts:257-263` |
| `isTransportError` | `src/openai-compat.ts:270-278` |
| 华为签名 | `src/sign.ts:28-68` |

### RPC 与 UI
| 内容 | 位置 |
|---|---|
| `JET_HUB_API_PATH` | `src/jet-hub-rpc.ts:95` |
| `registerJetHubRpc` | `src/jet-hub-rpc.ts:503-526` |
| 端点注册 + 信封校验 | `src/jet-hub-rpc.ts:538-601` |
| `handleMethod` 分派 | `src/jet-hub-rpc.ts:604-1265` |
| `account.create`（五分支 + 两步式） | `src/jet-hub-rpc.ts:612-795` |
| `account.refresh`（按 entry.provider 分派） | `src/jet-hub-rpc.ts:835-892` |
| `login.poll`（查凭据是否已写入） | `src/jet-hub-rpc.ts:894-904` |
| `model.list`（必须走 `listAllModels`） | `src/jet-hub-rpc.ts:1181-1243` |
| `model.setDisabled` | `src/jet-hub-rpc.ts:1247-1261` |
| `reply()` 信封 | `src/jet-hub-rpc.ts:1270-1275` |
| 限流重测/重置 | `src/account-probe.ts:194-272` |
| LobsterAI 错误分类 | `src/lobsterai-errors.ts:100-171` |
| Client `apply` + slot 注册 | `plugin-src/client/index.js:14-29` |
| `callManagementRpc` / `unwrapRpcResult` | `plugin-src/management-rpc.mjs:24-45` |
| `JET_HUB_RPC_CHANNEL` / `PROVIDERS` | `plugin-src/client/jet-hub.js:6`、`:69-76` |
| `createAccount` + 轮询 | `plugin-src/client/jet-hub.js:695-750` |
| 能力矩阵 | `plugin-src/client/credits-capabilities.js:54-65` |
| 客户端打包（`__ModuleLoader__`） | `plugin-src/client/build.mjs:29-38` |

---

## 未验证 / 存疑事项

以下内容我**没有**在代码中确证，报告中相应位置已标注，此处汇总。**本节 9 条原样保留**——「主动标注证据边界」是本文档价值的一部分。凡后续核验报告（`verify-01-02-dsh.md`）已核实或已排除的条目，在条目末尾以 `〔核验更新〕` 标注，不删除原表述。

1. **`ctx.credentials` 的物理存储位置与加密算法**。本仓库只调用宿主 API（`set` / `resolve` / `describe` / `unset`），没有实现。`AGENTS.md:120` 只说「凭据存储使用 `ctx.credentials` 模块」，`docs/adding-a-new-provider.md:81` 说「加密存储」，`src/buddy.ts:229-241` 提到落盘为 `.credentials.yaml`。**具体加密方式、密钥来源、文件路径需查 DSH 宿主仓库，未验证。**
2. **`qoder` 与 `trae` 的续期终态判定细节**。我只精读了 `buddy-oauth.ts` / `oauth.ts` / `lobsterai-errors.ts` 的终态判定；`qoder-auth.ts`（481 行）与 `trae-auth.ts`（546 行）的 `refresh` / `refreshAll` 实现**未逐行精读**，只从 `src/index.ts` 的接线与调用点确认了接口形态。它们的 `RefreshTokenExpiredError` 判定条件可能有额外细节。
3. **`qoder` 加密推理的 WASM 调用约定**。`AGENTS.md:26` 明确说「改这个文件前先读**不入库**的 `docs/qoder-encryption-notes.md`」——该文件不在仓库里，所以我无法了解 glue 约定与请求体字段结构。`src/qoder-wasm.ts`（613 行）未精读。
4. **`trae` 的通道归属映射**。`channelFor(model)` 如何决定某个模型属于哪个 channel，我只看到 `src/trae-adapter.ts:557` 的方法签名，未读实现。`AGENTS.md:539-612` 说「模型只在列出它的通道里可调用（发错通道 → 流内 4001）」，因此这个映射是正确性关键。
5. **`src/codearts-credits.ts`（655 行）与 `src/credits.ts`（490 行）** 完全未读——与本任务（模型转接）无关。
6. **`src/qoder-auth.ts` / `src/trae-auth.ts` / `src/buddy.ts` 剩余部分**（`parseTokenData` / `parseModelsFromConfig` / `parsePromotions` 等解析函数的字段级细节）未逐行读。
7. **`plugin-src/client/jet-hub.js`（1079 行）** 只读了关键片段（PROVIDERS / createAccount / 轮询），完整 UI 结构未读。
8. **并发场景下的实际行为**。我通过阅读代码推断「账号池无租约机制」，但没有运行测试验证。`tests/unit/account-pool.spec.ts` 是否覆盖并发场景未检查。
9. **合规风险未评估**。本插件大量使用「逆向官方客户端 + 伪造客户端身份头 + 设备指纹」的技术手段。我在报告中如实描述机制，但**不评估其法律与合规风险**——这需要专门判断，且不属于「代码考古」的范围。〔核验更新〕核验报告明确声明同样「未评估法律与合规风险」，此项仍是**公开缺口**。

---

## 参考文档索引

| 文档 | 行数 | 与本报告的关系 |
|---|---|---|
| `docs/adding-a-new-provider.md` | 560 行 | **架构总纲**。三层模型、双文档系统、扩展点清单。⚠️ 只覆盖 4 个 provider（早于 qoder/trae） |
| `AGENTS.md` | 1260 行 | 缺陷复盘大全。§「续期不得按 enabled 过滤」（:136-154）、§「两步式登录」（:1082-1111）、§「同名模型消歧」（:400-430）、§「TRAE 协议要点」（:502-1022）、§「X-Domain 必须跟随产品」（:1256-1260） |
| `README.md` | 1122 行 | 面向用户的能力说明。§凭证（:121-128）、§续期（:130-176）、§工作原理（:209-218） |
| `docs/lobsterai-integration-plan.md` | 1728 行 | LobsterAI 的集成方案与设计决策（含「凭据不落文件」的对比表，:566-580） |
| `docs/trae-integration-plan.md` | 256 行 | TRAE 的集成方案 |
| `docs/lobsterai-review-findings.md` | 344 行 | LobsterAI 的 review 结论（本报告未读；草稿 02 引用了其 S1-S4） |
