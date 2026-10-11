# 07 · DSH 插件（deepseek-harness-codearts）的接入形态与宿主契约

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

> ## 🟡 读本文前必读（结论已被 `09` 提炼，2026-09-22 补）
>
> **本文是"形态知识存档"。如果你只想知道结论，读 `09` 号文档就够了，不必读本文。**
>
> - **结论**：DSH 插件是 **L3「宿主进程内注册」**形态；**我们不为 DSH 写插件**（DSH 原生支持"添加自定义提供方"，零适配成本）。
> - **本文的价值**：当你要**理解"宿主是怎么识别一个本地/进程内模型提供方"**、或要**为某个"既无自定义 provider、又有插件 API"的宿主做瘦插件**时，本文提供了完整的宿主契约（`ctx.llm` / `LlmAdapter` / settings namespace / Jet Hub RPC）。
> - **读哪节**：结论看 §0；要做瘦插件看 §2~§6；**不要**为了"实现 DSH 接入"而读本文 —— 那条路不需要插件。
> - **合规提醒**：本文涉及的参考插件走的是**逆向形态**（提取客户端内部凭据）。**实施前必读 `05` 的合规结论与 `00` §六·零。**
>
> 完整的形态辨析与"该借鉴什么"见 `09-网关形态定位与本地LLM形态辨析.md`。

> 调研对象：`/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts`
> **原复核基线**：`git rev-parse HEAD` = `397972908855bc458ef240d39ed24c1922a3a751`（**已失效** —— 该 commit 现不在仓库历史中，仓库于 2026-09-22 被重建，详见文首「行号基线漂移声明」）
> **现行基线**：`d4613614f15884d1c7cd087e73a2aee6b17f2c0c`（2026-09-22 重锚，`git status` 干净）
> 调研方式：**只读**源码 + 注释 + 文档交叉核对；所有行号已脚本化校验（见附录 A）
> 证据分级：`【一手】` 源码可直接观测 · `【推断】` 从用法反推、无直接来源 · `【未找到】` 检索后无依据
>
> ⚠️ 关键前提：仓库**不含 `node_modules`**，`@deepseek-ai/*` 宿主包本地不存在（`package.json:55-61` 只声明 peer/dev 依赖）。
> 因此所有宿主侧签名（`ctx.llm`、`LlmAdapter` 基类、`connection`、`settings`）**只能从调用点与注释反推**，本文已逐条标注。
> 唯一的例外是 `@deepseek-ai/cordis` 的 `Context`：测试里直接 `new Context()` 构造真实实例（`tests/unit/plugin.spec.ts:96`），故 Cordis 侧部分结论有可运行证据。

### 修订记录（定稿前经独立核验员证伪审计后修正）

| # | 位置 | 原内容 | 修正后 | 依据 |
|---|---|---|---|---|
| 1 | §1.2 反证 A | "全仓 `createServer` 只出现 **3 处**"（表格漏列一处） | "`src/` 下 `createServer()` **调用**共 **5 处**"——补 `src/login.ts:287`；并补充说明 import / 类型标注（`login.ts:1/162/279/343`、`lobsterai-oauth.ts:22`、`trae-oauth.ts:20`）不计入。**结论方向不变**（全部是 OAuth 回调，与模型接入无关） | 核验报告 M1 |
| 2 | §4.4 结论后 | 无（与 `08` 的契约口径存在表述冲突） | 新增「口径说明」：本插件的"**必须实现 4 个方法**"是**插件自定的工程约定**（`docs/adding-a-new-provider.md:338-342`）；DSH 官方契约是"**仅 `stream()` 必需**"。两者不矛盾（`stream()` 官方必需，其余 3 个是让模型进选择器所必需的工程约定） | 核验报告 M3 |

### 第三批修订（用户指出"本地 LLM 形态"这一提问被误读后，按用户澄清重写）

> 背景：用户在追问中明确指出 —— "我让你调研的是**他是不是以本地 llm 形式对接给 DeepSeek Harness 的，如果是我们也需要借鉴学习这种对接模式**"。本节记录据此做的口径修正。

| # | 位置 | 原内容 | 修正后 | 依据 |
|---|---|---|---|---|
| 3 | §0.2 表格第 3 行 | "⚠️ **方向对、措辞错**" | "✅ **成立，需分层精确**"。原表述把讨论引向"本地是否指本地跑权重"的**纯语义问题**，反而盖掉了用户真正识别出的判断（这是**第三形态**）。改为**三层辨析**（L1 本地权重 / L2 本机端点服务 / L3 宿主进程内注册），判定插件落在 **L3** | 用户澄清；完整辨析见 `09` 号文档 §0.2 |
| 4 | §1.4 标题与正文 | 标题"为什么'本地 LLM'这个措辞会误导（重要）" | 标题改为"**'本地'的两种读法与本文的用词纪律**"，正文改为 L2 / L3 对照表 + 用词纪律声明 | 同上 |
| 5 | §0.3 | 三条含义（未含形态结论） | 扩为**四条**，新增第 4 条："**形态上我们不需要 L3 —— 我们已经是 L2**" | `09` 号文档 §2 / §3 |
| 6 | §1.3 表格"人机管理流"、§1.3 "不是 DSH 的 web 服务本身"、§7.2 | 三处引用写作 `（§9）` | 改为 `（§8）` —— Jet Hub RPC 是本文 **§8**，`§9` 是"宿主服务依赖清单"，原引用**指错了节** | 章节标题核对（本次发现并修正） |
| 7 | §7.2 | `（§9.4）` | 改为 `（§8.4）` —— "人机管理流量 vs 模型推理流量"是 **§8.4**，`§9.4` 是"依赖清单小结" | 同上 |

> 核验报告：`drafts/verify-07-08.md`（第一批，14 处问题：0 严重 / 4 中等 / 10 轻微，**无任何核心结论被证伪**）。
> 第三批（本次）共 5 处口径修正 + 2 处**指错节的引用**，核验报告见 `drafts/verify-09.md`。

---

## 0. 结论先行

### 0.1 一句话回答

**是"宿主进程内形态"，但不是"本地 LLM 形态"。**

准确术语应为：**DSH/Cordis 宿主进程内的原生 LLM Provider 插件（in-process native LLM provider plugin）**。

它的接入方式是**把一个 `LlmAdapter` 子类实例注册进宿主的 `llm` 服务**，让宿主在进程内以**函数调用**（`AsyncIterable<StreamChunk>`）方式消费它；模型推理本身**仍然全部在远端厂商**（华为云、腾讯、有道、阿里、字节），本地不加载任何模型权重。

### 0.2 用户判断的证实与**精确化**

> ⚠️ **本节初稿曾写作"方向对、措辞错"，这是学究式抬杠，已修正。**
> 它把讨论引向"本地是不是指本地跑权重"这个纯语义问题，反而把用户**真正识别出来的那个判断（这是既非 API 也非 CLI 的第三种形态）给盖掉了**。**用户的判断是对的。**
> "本地"在两种读法下都成立，只是**指向不同的层**。完整的三层辨析见 `09-网关形态定位与本地LLM形态辨析.md` §0.2。本节只做分层精确化，不再做措辞评判。

| 用户的判断 | 复核结论 | 依据 |
|---|---|---|
| "不是 API 形态" | ✅ **成立** | 插件不对外提供任何推理 HTTP 端点；`/api/jet-hub` 是挂在宿主 web 服务上的**管理**路由，不是插件自建的推理服务（§8） |
| "不是 CLI 形态" | ✅ **成立** | `package.json` 无 `bin` 字段（`package.json:1-83` 全文）；`spawn` 仅用于打开浏览器（`src/login.ts:135`） |
| "像是'本地 LLM 形式'接入" | ✅ **成立，需分层精确** | 它确实是**第三形态**，且是**最靠内**的一种：代码与宿主**同进程**，边界不是网络而是**函数调用**。准确落在 **L3「宿主进程内注册」**。需与 **L2「本机端点服务」**（Ollama 的 `/v1` 面、以及**我们网关自己**）区分 —— 两者都叫"本地"，但 L2 的边界是网络，L3 没有边界。**两种读法下模型推理都在远端**（`src/llm-adapter.ts:14`、`src/llm-adapter.ts:835`） |

### 0.3 对 Model-Gateway 的直接含义（四条）

1. **DSH 侧不存在可复用的推理 HTTP 端点。** 这个插件把厂商协议"翻译"成进程内函数，翻译结果只对 DSH 进程自己可见。外部客户端无法通过任何端口调用它。
2. **能被复用的是"协议知识"，不是"运行时"。** 仓库自己的定位就是这个：`docs/lobsterai-integration-plan.md:131-148` 明确否决了"跑 Go 反代 sidecar"的方案，理由是"本插件运行在 DSH 宿主进程内，`ctx.llm.registerAdapter()` 已经就是那一层"。
3. **两条流量路径必须分开设计。** 模型推理流量（宿主 → 厂商，进程内函数 + 出网 HTTPS）与人机管理流量（浏览器 → 宿主 `/api/jet-hub` → 账号池）**互不重叠**（§8.4）。
4. **形态上我们不需要 L3 —— 我们已经是 L2。** 网关的定位是"服务器上常驻、服务全机所有 AI 工具、不属于任何单个编程工具"，这**就是 L2「本机端点服务」的定义**（`09-网关形态定位与本地LLM形态辨析.md` §2）。L3 要求适配器代码住进某个具体宿主，与这条定位**互斥**（`09` §3）。

---

## 1. 形态定性：判定依据与反证

### 1.1 判定依据（正向证据链，5 条）

**依据 1 — 入口是 Cordis 插件，只有三个命名导出，无进程入口。**【一手】

`src/index.ts` 导出 `name`（`src/index.ts:25`）、`inject`（`src/index.ts:33`）、`apply`（`src/index.ts:121`）。全仓 `src/` 下**不存在 `export default`**（唯一两处 `export default` 在 `vitest.config.ts:3` 与 `vitest.e2e.config.ts:3`，是测试配置）。

`package.json` 的 `main` 指向 `lib/index.js`（`package.json:6`），`exports` 只有 `.` 与 `./client` 两个入口（`package.json:8-15`）——**没有 `bin`**。这排除了"独立可执行进程"的可能。

**依据 2 — 插件对外暴露模型能力的唯一方式是注册进宿主服务。**【一手】

五个注册函数全部是同构的两行：

```ts
ctx.llm.registerConfigurableProviders([
  { provider: PROVIDER, displayName: 'CodeArts Agent', settingsNs: 'llm-codearts', settingsPath: [] },
])
const adapter = new CodeArtsAdapter(options)
ctx.llm.registerAdapter([PROVIDER], adapter)
```

- `src/llm-adapter.ts:1454` / `src/llm-adapter.ts:1458`（codearts）
- `src/buddy-adapter.ts:1451` / `src/buddy-adapter.ts:1455`（buddy 系，一个类服务两个 provider）
- `src/lobsterai-adapter.ts:1318` / `src/lobsterai-adapter.ts:1322`
- `src/qoder-adapter.ts:473` / `src/qoder-adapter.ts:477`
- `src/trae-adapter.ts:1380` / `src/trae-adapter.ts:1384`

这是**服务注册**，不是端口监听、不是 `listen()`、不是 stdio 握手。

**依据 3 — 推理接口是进程内异步迭代器，不是字节流。**【一手】

核心方法是 `async *stream(options: GenerateOptions): AsyncIterable<StreamChunk>`（`src/llm-adapter.ts:835`）。它 `yield` 的是 JS 对象（如 `{ type: 'finish', reason }`，`src/llm-adapter.ts:1385`），调用方是**同进程内的宿主代码**。HTTP 或 stdio 形态必须在边界上做序列化，这里完全没有。

**依据 4 — 与宿主的耦合面全是"服务注入"，不是"网络/文件协议"。**【一手】

插件依赖的宿主能力：`credentials` / `commands` / `llm`（静态 `inject`，`src/index.ts:33`）、`settings`（`src/index.ts:57`、`src/account-pool.ts:146`）、`attachments`（`src/index.ts:105`）、`connection`（`src/jet-hub-rpc.ts:521`）、`slots`（客户端，`plugin-src/client/index.js:8`）。全部是 Cordis 上下文上的对象引用。

**依据 5 — 生命周期错误会"打挂整个 DSH 宿主"，证明同进程。**【一手】

`AGENTS.md:863-876` 记录了一个真实缺陷：OAuth 回调服务器的 `listen()` 失败没注册 `'error'` 处理器时，错误"逃过 RPC 层的 `try/catch`，成为**进程级 unhandled error**，把**整个 DSH 宿主**打挂"（`AGENTS.md:984`）。

这条是**最强的同进程证据**：如果插件是独立进程或 sidecar，它的 unhandled error 不可能杀死宿主。同时也说明"本地回调服务器"是唯一的例外（见 §1.2 反证 1）。

### 1.2 反证：为什么不是另外三种形态

**反证 A — 不是"插件自建的 HTTP 服务"。**【一手】

`src/` 下 `createServer()` **调用**共 5 处，**全部是 OAuth 登录回调服务器**，与模型接入无关：

| 文件 | `createServer()` 调用点 | `listen` | 用途 |
|---|---|---|---|
| `src/login.ts` | `src/login.ts:170` | `src/login.ts:219`（`listen(0, '127.0.0.1')`，随机端口） | CodeArts 华为云 OAuth 回调 |
| `src/login.ts` | `src/login.ts:287` | （同文件第二处回调接收器） | 另一条 CodeArts 登录路径的回调 |
| `src/lobsterai-oauth.ts` | `src/lobsterai-oauth.ts:256` | `src/lobsterai-oauth.ts:348`（`listen(0, '127.0.0.1')`） | LobsterAI 本地回调 + authCode 换 token |
| `src/trae-oauth.ts` | `src/trae-oauth.ts:596`、`src/trae-oauth.ts:715` | `src/trae-oauth.ts:495` | TRAE 登录回调 |

> 除上述 5 处调用外，`createServer` 还作为**类型标注 / import** 出现在 `src/login.ts:1`、`:162`、`:279`、`:343`、`src/lobsterai-oauth.ts:22`、`src/trae-oauth.ts:20` —— 那些不是服务器实例。

这些回调服务器都绑定 **`127.0.0.1`**（`AGENTS.md:884-886` 解释了必须绑回环的安全原因：绑所有网卡会让同局域网机器投递伪造 `?code=`），生命周期只覆盖"一次登录"，用完即关。

> ⚠️ 这是本调研中最容易被误读的一点：插件**确实会起 HTTP 服务器**，但它是**登录流程的临时回调接收器**（人机交互），不是模型接入通道。把 `createServer` 的存在当作"HTTP 形态"证据是错的。

**反证 B — `src/openai-compat.ts` 的名字具有欺骗性。**【一手】

文件名像"OpenAI 兼容服务层"，实际是**客户端侧**的上游协议处理工具。其模块头写明：「OpenAI 兼容协议层的共享实现：消息序列化 + SSE 消费 + 错误归类」（`src/openai-compat.ts:2`），并说明它抽取自 `buddy-adapter` / `lobsterai-adapter` 的**同源逻辑**、供 **qoder 适配器**使用（`src/openai-compat.ts:12`）。

即：它在**消费**上游的 OpenAI 兼容协议（发请求、解析 SSE），而不是**提供** OpenAI 兼容端点。方向正好相反。

**反证 C — 不是 CLI 形态。**【一手】

- `package.json` 无 `bin` 字段。
- 全仓 `spawn` 只有一处，用于打开浏览器（`src/login.ts:135`：`spawn(cmd, [url], ...)`，`cmd` 为 `open`/`xdg-open`；Windows 分支见 `src/login.ts:125`）。属于 `openBrowser()`（`src/login.ts:116`）。
- README 里出现的 `dsh plugin --profile <name> add/install`（`README.md:46`、`README.md:59`）是**宿主的** CLI 命令，用于安装本插件，不是插件自带的 CLI。
- 插件确实注册了斜杠命令（`/codearts-login` 等，`src/index.ts:151`、`src/index.ts:166`、`src/index.ts:183`），但这是**宿主 CLI/TUI 内的命令**（`ctx.commands.register`，`src/index.ts:150`），运行在宿主进程里，不是独立可执行文件。

**反证 D — 不是 sidecar 代理。**【一手，且是仓库自己明确否决的】

`docs/lobsterai-integration-plan.md:131-148` 整节标题为「核心判断：不需要跑那个反代」，指出参考项目 `lobsterai2api` 的定位是"给任意 OpenAI SDK 客户端用的独立 HTTP 服务"，所以必须自己实现 `/v1/chat/completions`；而本插件"运行在 DSH 宿主进程内，`ctx.llm.registerAdapter()` **已经就是那一层**"（`docs/lobsterai-integration-plan.md:136`）。该节结论是把 Go 代码"当作协议说明书，翻译成本插件的 TypeScript 适配器"，收益第一条就是"少一个进程、少一个端口、少一份配置"（`docs/lobsterai-integration-plan.md:143-148`）。

**反证 E — 不是 MCP server。**【未找到】

全仓检索 `mcp` / `stdio` / JSON-RPC over stdio：**无任何 MCP 协议实现**。唯一的 `stdio` 出现在 `src/login.ts:125` 与 `src/login.ts:135`，是 `spawn` 的 `stdio: 'ignore'` 选项（丢弃子进程输出），与 MCP 无关。

### 1.3 形态的准确命名

| 维度 | 取值 |
|---|---|
| **准确术语** | 宿主进程内原生 LLM Provider 插件（in-process native LLM provider plugin） |
| 运行位置 | DSH/Cordis 宿主进程内（`AGENTS.md:984`） |
| 接入机制 | 服务注入 + 适配器注册（`ctx.llm.registerAdapter`） |
| 对外边界 | **无对外边界**——不监听端口、不开 socket、不暴露推理端点 |
| 推理数据流 | 进程内函数调用（`AsyncIterable<StreamChunk>`）→ 适配器内 `fetch` 出网到厂商 |
| 人机管理流 | 浏览器 → 宿主 `/api/jet-hub` → 账号池（§8） |
| 模型权重位置 | **远端厂商**，本地不加载（`src/llm-adapter.ts:14`、`src/models.ts:8`、`src/models.ts:16`） |

**它不是什么（逐条给理由）：**

- **不是 OpenAI 兼容 HTTP 服务** —— 无推理端点；`openai-compat.ts` 是客户端侧序列化（反证 B）。
- **不是子进程 CLI** —— 无 `bin`；`spawn` 只用于开浏览器（反证 C）。
- **不是 MCP server** —— 无 MCP/stdio 协议实现（反证 E）。
- **不是 sidecar 代理** —— 仓库显式否决（反证 D）。
- **不是"本地权重推理"** —— 适配器代码在本地进程内，但推理在远端（见 §1.4）。
- **不是 DSH 的 web 服务本身** —— 它只是**往**宿主的 web 服务注册了一条路由（§8）。

### 1.4 "本地"的两种读法与本文的用词纪律

> **本节初稿标题为"为什么'本地 LLM'这个措辞会误导"，是学究式抬杠，已改写。** 用户说的"本地"**没有说错**，只是需要分层。完整辨析见 `09-网关形态定位与本地LLM形态辨析.md` §0.2。

"本地 LLM"在业界有**两种读法**，本文必须把二者分开，否则会得出错误结论：

| 读法 | 含义 | 本插件符合？ |
|---|---|---|
| **L2 本机端点服务** | 本机有常驻服务，宿主**通过网络**指向它（Ollama 的 `/v1` 面、以及**我们网关自己**） | ❌ **不符合** |
| **L3 宿主进程内注册** | 代码与宿主**同进程**，**没有网络边界** | ✅ **符合** |

**本文后续凡称"本地"，一律指 L3 的"进程内"，不指 L1 的"本地权重"。**

按 L1（本地权重推理）理解，会得出"DSH 侧有一个本地推理后端可被网关调用"的错误结论。实际情况：

- 六个 provider 的推理端点**全部是远端 HTTPS**：
  - codearts → `https://snap-access.cn-north-4.myhuaweicloud.com/api/v2`（`src/llm-adapter.ts:14`）
  - 模型目录另有两个远端端点（`src/models.ts:8`、`src/models.ts:16`）
  - buddy / workbuddy / lobsterai / qoder / trae 各自的 `product.apiBase` / `endpoint` 常量
- 本地进程内**只有**：协议翻译代码、凭据管理、账号池、模型元数据表。
- 因此"本地"修饰的是**适配器的宿主位置**（L3），不是**推理的物理位置**（L1）。

对网关设计的推论：**DSH 插件的 L3 形态不产生任何可被网关复用为下游的东西**；但我们网关自己就是 **L2**（详见 `09` 号文档 §2）—— **我们不需要 L3，我们已经是 L2**。反过来，插件里沉淀的"厂商协议翻译 + 账号池 + 限流切换"是**协议知识资产**，可被网关**上游适配器**参考实现（与 `docs/lobsterai-integration-plan.md:140-141` 的定位一致）。

---

## 2. Cordis 插件契约

### 2.1 声明与加载

**声明面（三个命名导出，无默认导出）**【一手】

| 导出 | 值 / 签名 | 位置 |
|---|---|---|
| `name` | `'codearts-auth'` | `src/index.ts:25` |
| `inject` | `['credentials', 'commands', 'llm']` | `src/index.ts:33` |
| `apply` | `export function apply(ctx: Context): void` | `src/index.ts:121` |

**注意 `name` 的双重身份**：`src/index.ts:25` 的 `'codearts-auth'` 是**插件名**；`cordis.patch.yml:5` 的 `'dsh-codearts-auth'` 是**包名**（与 `package.json:2` 一致）。两者不等，不要混用。

**加载路径**【一手 + 推断】：

1. 包声明 `dsh.bundle.patch: "./cordis.patch.yml"`（`package.json:47-50`）。
2. `cordis.patch.yml` 内容是在**空配置根**上追加一行（`cordis.patch.yml:1-5`）：
   ```yaml
   - insert:
       - id: codearts-auth
         name: 'dsh-codearts-auth'
   ```
3. profile 的 layer 栈自动拾取该行 —— `README.md:73-75`：「该包声明了 `dsh.bundle` 补丁（`cordis.patch.yml`），因此 profile 的 layer 栈会自动拾取 `codearts-auth` 行。」
4. `id` 的作用：`cordis.patch.yml:2` 注释说明「后续配置补丁可通过 id 引用此行」【一手】。
5. `main` → `lib/index.js`（`package.json:6`），由 `tsc` 从 `src/` 编译（`package.json:21`、`tsconfig.json:11`）。`README.md:62-66` 警告：`dsh plugin install` 以 `link:` 方式安装时 pnpm 不跑 `prepare`，必须先手动 `pnpm build:all`，否则 `ERR_MODULE_NOT_FOUND`。

### 2.2 `inject` 的语义

**静态 `inject` = 硬依赖声明，缺服务则插件不激活（pending）。**【推断，但有直接注释证据】

`src/index.ts:25-31` 的注释直接陈述了失败链：

> `connection` 刻意不列入静态 inject：它只由 Web bundle（dsh-client-connection）提供，headless/CLI profile 里并不存在。静态 inject 会让本插件在那些 profile 里永久 pending，进而让整个 profile 以 `"plugin tree failed to load: 1 entry did not activate"` 启动失败 —— chicheng-cron 的 skill/agent 任务正是通过 `dsh --profile headless` 运行的，会因此全部 exit 1。

同一约束在 `src/jet-hub-rpc.ts:496-501` 与 `tests/unit/plugin.spec.ts:318-342` 重复出现，后者是**锁死该约束的回归测试**（`tests/unit/plugin.spec.ts:337` 断言 `inject` 不含 `connection`）。

> 【推断】的具体点：注释说明的是"不满足 → pending → profile 启动失败"这一**行为**，但 Cordis 内部如何实现 pending/activate 的状态机，本文无源码依据。

**惰性注入 = 软依赖。**【一手】

`ctx.inject(['connection'], (connectionCtx) => { ... })`（`src/jet-hub-rpc.ts:521`）——服务出现时才执行回调；不出现则回调永不执行，插件其余部分不受影响。

### 2.3 `ctx.effect` 的 cleanup 语义

**调用形状**【一手】：

```ts
ctx.effect(() => () => { clearInterval(refreshTimer); service.stop(); ... },
           'jet-hub: multi-account refresh scheduler')
```

- 位置：`src/index.ts:391-399`（定时器 + 六个服务 `stop()`）、`src/index.ts:404-411`（legacy 清理，只 `stop()`）。
- 客户端侧同款：`plugin-src/client/index.js:15`（`ctx.effect(() => installJetHubStyles(), 'jet-hub: install styles')`）。
- 文档侧确认：`docs/lobsterai-integration-plan.md:1290` 与 `docs/lobsterai-integration-plan.md:1299`（「`ctx.effect()` 注册清理钩子」）。

**语义**【推断】：`effect(callback, label)`，`callback` 立即执行并返回一个 **disposer 函数**；当所属 fiber 被 dispose 时，disposer 被调用。`label` 是诊断用的可读标签。

**证据（可运行）**：`tests/unit/plugin.spec.ts:186`、`tests/unit/plugin.spec.ts:214`、`tests/unit/plugin.spec.ts:313` 都是 `apply(ctx)` 后 `await ctx.fiber.dispose()`，然后断言各服务的 `stop()` 被调用（如 `tests/unit/plugin.spec.ts:185-187`）。这证明"dispose fiber → effect 的 disposer 执行"这条链路真实成立。

> 注意：`ctx.effect` 绑定的粒度是**当前 ctx 的 fiber**，不是"插件对象"。证据是 `src/index.ts:386` 的 effect 注册在一个 `pool.listAllAccounts().then(...)` 的**异步回调内部**，说明它是运行时按需注册到当时的 ctx 上的。

### 2.4 生命周期在代码中的体现

| 阶段 | 代码位置 | 说明 |
|---|---|---|
| **加载** | 模块求值，导出 `name`/`inject`/`apply`（`src/index.ts:25`、`:34`、`:122`） | 由宿主按 `cordis.patch.yml` 加载 `lib/index.js` |
| **激活** | `apply(ctx)` 执行（`src/index.ts:121-430`） | 注册 settings namespace（`:130`）→ 建 6 个 auth 服务（`:133`、`:222`、`:251`、`:279`、`:326`、`:369`）→ 注册 3 个斜杠命令（`:150-197`）→ 注册 6 条 llm 路由（`:198-394`）→ 武装续期定时器（`:400-442`）→ 注册 Jet Hub RPC（`:469`）→ `ctx.provide('accountPool', pool)`（`:470`） |
| **运行** | 定时器每 30 分钟续期（`src/index.ts:386`、`:430`）；`stream()` 按需触发 | `refreshTimer.unref?.()`（`src/index.ts:390`）避免阻塞进程退出 |
| **卸载** | `ctx.fiber.dispose()` → 两个 effect 的 disposer 执行（`src/index.ts:391-399`、`:445-452`） | 清定时器 + 六个 `stop()` |

> 【一手】的观察点：`src/index.ts:386` 的定时器是**条件性**注册的——只有存在 `refreshable` 账号才起定时器。且注释（`src/index.ts:381`）记录了一个真实缺陷：早期写成 `a.refreshable && a.enabled`，导致"所有账号都被停用"时续期定时器**根本不启动**。
>
> 【推断】：`stop()` 在 dispose 时会被调用**两次**（`:434-439` 与 `:446-451` 都调用六个服务的 `stop()`）。两处 effect 都注册在同一 ctx 上，dispose 时都会触发。代码未做幂等保护，推测 `stop()` 本身是幂等的（但 `stop()` 实现未逐一核对）。

### 2.5 服务命名与冲突约束

`CodeArtsAuth extends Service`（`src/service.ts:64`），构造时 `super(ctx, 'codeartsAuth')`（`src/service.ts:93`）——**服务名由构造时显式传入**。其余五个服务名由 `product.id` 派生（`src/index.ts:248-249`、`:277`、`:324`、`:367` 的注释）。

`tests/unit/plugin.spec.ts:266-268` 记录了一条硬约束：cordis 的 `Service` 按名称注册，**同名第二次注册会抛 `service "buddyAuth" has been registered`**，导致 `apply()` 直接抛错、插件完全无法加载。因此 buddy 与 workbuddy 必须各占一个服务名（`tests/unit/plugin.spec.ts:269-279` 是回归测试）。

---

## 3. `ctx.llm` 服务 API 全集

### 3.1 全仓调用点清单（这是本节的全部事实基础）

检索式：`ctx.llm` / `ctx.get('llm')` / `llm.` 方法调用，覆盖 `src/`、`plugin-src/`、`tests/`、文档。

| # | 调用 | 位置 | 证据级 |
|---|---|---|---|
| 1 | `ctx.llm.registerConfigurableProviders([...])` | `src/llm-adapter.ts:1454` | 【一手】 |
| 2 | `ctx.llm.registerAdapter([PROVIDER], adapter)` | `src/llm-adapter.ts:1458` | 【一手】 |
| 3 | `ctx.llm.registerConfigurableProviders([...])` | `src/buddy-adapter.ts:1451` | 【一手】 |
| 4 | `ctx.llm.registerAdapter([product.id], adapter)` | `src/buddy-adapter.ts:1455` | 【一手】 |
| 5 | `ctx.llm.registerConfigurableProviders([...])` | `src/lobsterai-adapter.ts:1318` | 【一手】 |
| 6 | `ctx.llm.registerAdapter([product.id], adapter)` | `src/lobsterai-adapter.ts:1322` | 【一手】 |
| 7 | `ctx.llm.registerConfigurableProviders([...])` | `src/qoder-adapter.ts:473` | 【一手】 |
| 8 | `ctx.llm.registerAdapter([product.id], adapter)` | `src/qoder-adapter.ts:477` | 【一手】 |
| 9 | `ctx.llm.registerConfigurableProviders([...])` | `src/trae-adapter.ts:1380` | 【一手】 |
| 10 | `ctx.llm.registerAdapter([product.id], adapter)` | `src/trae-adapter.ts:1384` | 【一手】 |
| 11 | `ctx.get('llm')` → `{ listModels }` | `src/jet-hub-rpc.ts:488` | 【一手】 |
| 12 | `llm.listModels(req.provider)` | `src/jet-hub-rpc.ts:1189` | 【一手】 |
| 13 | `ctx.llm.registeredProviders` / `ctx.llm.providers` / `ctx.llm.adapters` | `tests/unit/plugin.spec.ts:223`、`:350`、`:420` | 【推断】测试替身字段，非宿主 API |

**文档侧引用（非调用点）**：`AGENTS.md:152`（`ctx.llm.registerProvider()`）、`README.md:565`（`ctx.llm.listModels()`）、`docs/adding-a-new-provider.md:404`、`docs/lobsterai-integration-plan.md:136`、`docs/lobsterai-integration-plan.md:1344`。

**⚠️ 只有 2 个方法 + 1 个读取路径。** 没有 `ctx.llm.resolveModel()`、没有 `ctx.llm.stream()`、没有 `ctx.llm.listAllModels()` 的调用点（§5.3 说明原因）。

### 3.2 方法签名（区分观测与推断）

#### `registerConfigurableProviders(entries)`

```ts
// 【一手】入参形状 —— 5 个调用点完全一致
entries: Array<{
  provider: string       // provider 路由 id，如 'codearts' / 'buddy'
  displayName: string    // 模型设置页展示名，如 'CodeArts Agent'
  settingsNs: string     // 配置 namespace，如 'llm-codearts'
  settingsPath: []       // 5 处调用点均为空数组
}>

// 【推断】返回值 —— 来自测试替身
{ replace: () => void }
```

- 入参【一手】：`src/llm-adapter.ts:1442`、`src/buddy-adapter.ts:1452`、`src/lobsterai-adapter.ts:1319`、`src/qoder-adapter.ts:474`、`src/trae-adapter.ts:1381`。
- 返回值【推断】：`tests/unit/plugin.spec.ts:62-70` 的 `FakeLlm.registerConfigurableProviders` 返回 `{ replace: () => {} }`。**这是测试作者对真实签名的建模，不是真实宿主的源码**，可能失真。
- 【未找到】：`settingsPath` 的语义。5 个调用点全部传 `[]`，仓库内无任何消费方，无注释解释。

#### `registerAdapter(providers, adapter)`

```ts
// 【一手】入参形状
providers: string[]        // 路由名数组，如 ['codearts'] / [product.id]
adapter: LlmAdapter        // 适配器实例（LlmAdapter 子类）

// 【推断】返回值
{ replace: () => void }
```

- 入参【一手】：`src/llm-adapter.ts:1458`、`src/buddy-adapter.ts:1455`、`src/lobsterai-adapter.ts:1322`、`src/qoder-adapter.ts:477`、`src/trae-adapter.ts:1384`。
- 返回值【推断】：同 `tests/unit/plugin.spec.ts:71-75`。
- **语义【推断】**：建立 `provider id → adapter 实例` 的路由表。证据是 `registerAdapter([PROVIDER], adapter)` 的 `PROVIDER` 与 `registerConfigurableProviders` 的 `provider` 字段取值一致（`src/llm-adapter.ts:1442` vs `:1445`，均为 `PROVIDER = 'codearts'`，定义于 `src/llm-adapter.ts:15`）。
- **入参是数组而非单值**：5 个调用点都传单元素数组，但类型是 `string[]`。推测支持一个 adapter 服务多个 provider 路由（但实际未使用）。

#### `listModels(provider)`

```ts
// 【一手】读取路径 —— src/jet-hub-rpc.ts:484-494 的显式类型断言
ctx.get('llm') as {
  listModels(provider: string): Promise<Array<{ id: string; name: string }>>
  listAllModels?(provider: string): readonly { id: string; name: string }[]
} | undefined
```

- 调用点：`src/jet-hub-rpc.ts:1189`。
- 返回形状【一手（由断言表达）】：`Promise<Array<{id, name}>>`。注意这里**没有** `provider` / `inputModalities` 字段——但适配器实现的 `LlmModelInfo` 有（§5.2）。说明这是**结构化子集**断言，宿主返回的对象实际更宽。
- 【推断】宿主内部实现是"按 provider 找到 adapter → 调 `adapter.listModels(provider)` → 汇总"。
- 【一手】语义旁证：`README.md:565` 说"模型列表来自 `ctx.llm.listModels()`，**即对话框模型选择器读取的同一份目录**"；`src/jet-hub-rpc.ts:1177-1178` 说"正是对话框模型选择器读的同一份数据（会话控制器的 buildModelCatalog）"。

#### `listAllModels?`（可选方法）

**这是插件自己的约定，不是宿主 API。** `src/jet-hub-rpc.ts:480-482` 注释：

> `listAllModels` 是本插件适配器额外提供的**不受用户黑名单影响**的完整目录（见各适配器的同名方法）。DSH 的 `llm` 服务只保证 `listModels`，故这里把它声明为可选。

因此 §3.1 表中没有 `ctx.llm.listAllModels()` 的调用点——插件改为**绕过服务、直接持有适配器实例**（`src/index.ts:417-426` 的 `modelAdapters` 映射，注释在 `src/index.ts:413-416`）。

### 3.3 服务方法全集（含不确定性声明）

| 方法 | 证据级 | 说明 |
|---|---|---|
| `registerConfigurableProviders(entries)` | 入参【一手】/ 返回【推断】 | 声明可配置 provider 目录项 |
| `registerAdapter(providers, adapter)` | 入参【一手】/ 返回【推断】 | 建立 provider → adapter 路由 |
| `listModels(provider)` | 【一手】 | 枚举 provider 的模型目录 |
| **是否存在其他方法** | 【未找到】 | 插件从未调用；`@deepseek-ai/dsh-llm` 本地不存在，无法读签名 |

> ⚠️ **诚实声明**：本文无法给出 `ctx.llm` 的完整方法集。只能说"**本插件用到了这 3 个**"。`ctx.llm` 是否还有 `resolveModel` / `stream` / `getAdapter` 等公共方法，**无依据**，不编造。

### 3.4 消费 `adapter` 的中间层：`LlmRuntime`【推断】

插件代码与测试注释多次提到 `LlmRuntime`：

- `src/qoder-adapter.ts:194-198`：新版 `LlmRuntime.prepareCall()` 会调用 `registration.adapter.prepareCall(...)`。
- `src/buddy-adapter.ts:856-861`：本仓库链接的 `dsh-llm` 副本（0.1.0-rc.6）的 `LlmAdapter` 基类**尚未提供** `prepareCall`。
- `tests/unit/buddy-adapter.spec.ts:513`：`dsh-llm 0.1.1-rc.2` 的 `LlmRuntime.prepareCall()` 会直接调用……
- `tests/unit/lobsterai-adapter.spec.ts:696`：`LlmRuntime`（dsh-llm `lib/index.js`）里按 `inputModalities` 决定要不要把图片投影成文本。
- `src/buddy-adapter.ts:822-823`：DSH 在 `resolveCallWithInfo` 里只在调用方未显式给值时用 `defaultMaxTokens` 兜底。

**推断的链路**：`ctx.llm`（服务）→ `LlmRuntime`（运行时，消费 adapter）→ `adapter.resolveModel()` / `adapter.prepareCall()` / `adapter.stream()`。

`LlmRuntime` 的内部实现**无源码**（`node_modules` 不存在），以上全部来自注释与测试命名。**这是本文不确定性最高的部分。**

---

## 4. `LlmAdapter` 基类契约

### 4.1 从 `@deepseek-ai/dsh-llm` 导入的符号（观测到的事实）

| 符号 | 类型 | 出现位置 | 含义【推断】 |
|---|---|---|---|
| `LlmAdapter` | 类（基类） | `src/llm-adapter.ts:5`、`src/qoder-adapter.ts:27`、`src/trae-adapter.ts:22` | 适配器基类 |
| `LlmError` | 类 | `src/llm-adapter.ts:5`、`src/openai-compat.ts:32`、`src/sse.ts:12` 等 | 规范化错误，携带错误码 |
| `ToolCallId` | 值（函数/构造器） | `src/llm-adapter.ts:8`、`src/buddy-adapter.ts:22`、`src/trae-adapter.ts:24` | 工具调用 id 的类型品牌化构造器 |
| `ReasoningEffortId` | 值 | `src/trae-adapter.ts:22`、`src/buddy-adapter.ts:845` | 推理档位 id 的品牌化构造器 |
| `createUserMessage` | 值（函数） | `src/account-probe.ts:33`、`tests/unit/lobsterai-adapter.spec.ts:12` | 构造 harness 用户消息 |
| `attributionHeaders` | 值（函数） | `src/llm-adapter.ts:4` | 生成归属请求头 |
| `CONTEXT_WINDOW_EXCEEDED_CODE` | 常量 | `src/llm-adapter.ts:4` | 上下文超限错误码 |
| `QUOTA_EXCEEDED_CODE` | 常量 | `src/llm-adapter.ts:5` | 配额超限错误码 |
| `isContextWindowExceededError` | 值（判定函数） | `src/llm-adapter.ts:4` | 错误分类 |
| `isQuotaExceededError` | 值（判定函数） | `src/llm-adapter.ts:5` | 错误分类 |

类型导入：`GenerateOptions`、`LlmModelInfo`、`LlmProviderInfo`、`LlmResolvedModelInfo`、`StreamChunk`（`src/llm-adapter.ts:7`、`src/buddy-adapter.ts:23`、`src/lobsterai-adapter.ts:31`、`src/qoder-adapter.ts:28`、`src/trae-adapter.ts:23`）。

### 4.2 五个适配器类 × 六个 provider 路由

**⚠️ 关键计数细节：5 个类 → 6 个 provider。** `BuddyAdapter` 被实例化**两次**，分别服务 `buddy` 与 `workbuddy`（`src/index.ts:223` 传 `product: CODEBUDDY`，`src/index.ts:252` 传 `product: WORKBUDDY`），差异全部由 `product` 配置承载（`src/index.ts:246-248` 注释）。

| 类 | 定义 | 服务 provider | 注册函数 |
|---|---|---|---|
| `CodeArtsAdapter` | `src/llm-adapter.ts:726` | `codearts` | `registerCodeArtsLlm`（`src/llm-adapter.ts:1440`） |
| `BuddyAdapter` | `src/buddy-adapter.ts:531` | `buddy` + `workbuddy` | `registerBuddyLlm`（`src/buddy-adapter.ts:1449`） |
| `LobsteraiAdapter` | `src/lobsterai-adapter.ts:597` | `lobsterai` | `registerLobsteraiLlm`（`src/lobsterai-adapter.ts:1316`） |
| `QoderAdapter` | `src/qoder-adapter.ts:103` | `qoder` | `registerQoderLlm`（`src/qoder-adapter.ts:471`） |
| `TraeAdapter` | `src/trae-adapter.ts:485` | `trae` | `registerTraeLlm`（`src/trae-adapter.ts:1378`） |

### 4.3 方法实现矩阵

| 方法 | CodeArts | Buddy | Lobsterai | Qoder | Trae | 是否必须 |
|---|---|---|---|---|---|---|
| `providerInfo` | `:746` | `:582` | `:624` | `:126` | `:509` | **必须** |
| `listModels` | `:785` | `:773` | `:739` | `:162` | `:687` | **必须** |
| `resolveModel` | `:801` | `:805` | `:759` | `:179` | `:719` | **必须** |
| `stream` | `:822` | `:874` | `:808` | `:211` | `:750` | **必须** |
| `prepareCall` | `:811` | `:863` | `:787` | `:200` | `:739` | 建议（实际全实现） |
| `listAllModels` | `:776` | `:768` | `:734` | `:158` | `:677` | **插件自定义**（非基类） |

**5 个适配器 × 6 个方法全部实现，无遗漏。** 行号由检索式 `async *stream` 与 `^  (override |async )*(providerInfo|listModels|listAllModels|resolveModel|stream|prepareCall)\s*\(` 得到，已逐一核对。

### 4.4 文档 vs 实际代码的一致性核对（用户要求的核对项）

**`docs/adding-a-new-provider.md` 的契约说明与实际代码对比：**

| 文档陈述 | 位置 | 实际代码 | 一致？ |
|---|---|---|---|
| 必须实现 4 个方法：`providerInfo` / `listModels` / `resolveModel` / `stream` | `docs/adding-a-new-provider.md:338-342` | 5 个适配器均实现这 4 个 | ✅ 一致 |
| 建议实现 `prepareCall`（"兼容新版 DSH"） | `docs/adding-a-new-provider.md:344-346` | 5 个适配器**都**实现了 | ✅ 一致（措辞偏保守，实际已必需） |
| `stream(options: GenerateOptions): AsyncIterable<StreamChunk>` | `docs/adding-a-new-provider.md:342` | `src/llm-adapter.ts:835` 完全吻合 | ✅ 一致 |
| "本插件已集成了**四个** LLM Provider" | `docs/adding-a-new-provider.md:8` | 实际 **6 个** provider（`src/index.ts:131` 注册 6 个 settingsNs） | ❌ **文档过期** |
| provider 表只列 buddy / workbuddy / lobsterai 三个 | `docs/adding-a-new-provider.md:10-13` | 实际 6 个 | ❌ **文档过期** |
| "`registerDeepseekOfficialLlm` 最终调用 `ctx.llm.registerConfigurableProviders(...)` + `registerAdapter(...)`" | `docs/adding-a-new-provider.md:404` | 与 5 个实际注册函数一致 | ✅ 一致 |

**`AGENTS.md` 的契约说明与实际代码对比：**

| 文档陈述 | 位置 | 实际代码 | 一致？ |
|---|---|---|---|
| "LLM provider 通过 `ctx.llm.registerProvider()` 注册" | `AGENTS.md:152` | 实际是 `registerConfigurableProviders()` + `registerAdapter()` | ❌ **文档过期/错误**（方法名不存在） |
| "插件配置通过 `ctx.schema` 在 profile layer 栈中声明" | `AGENTS.md:123` | 代码中**未出现** `ctx.schema`；实际用 `ctx.get('settings').register(ns, schema)`（`src/index.ts:57`） | ❌ **存疑**（未找到 `ctx.schema` 调用点） |
| "插件使用 `@deepseek-ai/dsh` 的 `credentials`、`commands`、`llm` 服务注入" | `AGENTS.md:119` | 与 `src/index.ts:33` 一致 | ✅ 一致 |
| 入口 `lib/index.js`（宿主侧）、`lib/client/jet-hub.js`（客户端 bundle） | `AGENTS.md:87` | 与 `package.json:6`、`package.json:13` 一致 | ✅ 一致 |

**结论**：`docs/adding-a-new-provider.md` 的 `LlmAdapter` 契约部分**准确可用**，但 provider 计数已过期；`AGENTS.md:152` 的方法名**是错的**，不可作为契约依据。

> ⚠️ **口径说明（与 `08` 号文档的措辞对齐）**：本节的"**必须实现 4 个方法**"是**参考插件自定的工程约定**（`docs/adding-a-new-provider.md:338-342`），不是 DSH 官方的硬性契约。
> DSH 官方参考文档对 `LlmAdapter` 的表述是"**实现 `stream()`**……**The only required method.**"（<https://deepseek-harness.github.io/deepseek-harness/reference/subsystems/llm-streaming>）——即**官方只强制 `stream()`**。
> 两者不矛盾：**`stream()` 是官方必需**（基类抽象方法）；`providerInfo` / `listModels` / `resolveModel` 是**让模型出现在宿主选择器、并能正确解析元数据所必需**的工程约定（缺了不会编译失败，但模型选择器/元数据会不完整）。
> 本文 §4.3 的表格标题"必须"应理解为"**本插件约定的必须**"；若引用官方契约，请以"仅 `stream()` 必需"为准。

### 4.5 各方法签名与语义（从实现 + 注释反推）

#### `providerInfo(provider: string): LlmProviderInfo`【一手】

同步方法。返回 `{ id, name }`。

```ts
// src/llm-adapter.ts:746-749
providerInfo(provider: string): LlmProviderInfo {
  const id = typeof provider === 'string' && provider.length > 0 ? provider : PROVIDER
  return { id, name: 'CodeArts Agent' }
}
```

**宿主施加的约束（来自注释）**【一手】：
- DSH 会**强制校验 `info.id === provider`**（`src/buddy-adapter.ts:572`、`src/qoder-adapter.ts:121`）。
- `info.name` 必须是非空字符串（`src/buddy-adapter.ts:572`）。
- 模型设置页会用该 id 计算 `deriveKeyRef(provider)`，内部调 `provider.toUpperCase()`（`src/buddy-adapter.ts:573-577`）。

因此 5 个适配器都做了**防御性归一化**：入参不是非空字符串时回退到产品 id，避免 `undefined.toUpperCase is not a function`（`src/llm-adapter.ts:747`、`src/buddy-adapter.ts:583`、`src/qoder-adapter.ts:127`）。

#### `listModels(provider: string): Promise<readonly LlmModelInfo[]>`【一手】

异步方法。**注意所有实现都忽略了 `provider` 入参**（签名写作 `_provider`，如 `src/llm-adapter.ts:785`、`src/buddy-adapter.ts:773`）——因为一个适配器实例只服务一个 provider。

返回 `LlmModelInfo` 字段【一手，从对象字面量观测】：

```ts
// src/llm-adapter.ts:798
return listed.map((m) => ({ provider: PROVIDER, id: m.id, name: m.name, inputModalities: ['text'] as const }))
```

```ts
// src/trae-adapter.ts:709-716（带注释解释 inputModalities 逐模型判定）
return listed.map((model) => ({
  provider: this.product.id,
  id: model.id,
  name: model.name,
  inputModalities: this.inputModalitiesFor(model.id),
}))
```

**语义要点**【一手】：
- `listModels` **会应用用户黑名单**（用户在 Jet Hub 关闭的模型被过滤掉）。5 个实现都有 `this.options.accountPool?.disabledModelsFor(...)` 过滤（`src/llm-adapter.ts:794-797`、`src/buddy-adapter.ts:778-781`、`src/trae-adapter.ts:705-708`、`src/qoder-adapter.ts:164-168`）。
- 目录是**建议性的**：`src/llm-adapter.ts:791-793` 注释明确「只影响此处对外播报的模型目录，不改变 resolveModel/stream 的路由能力 —— 与 DSH 对 listModels 的约定一致（**目录是建议性的，缺省不构成拒绝**）」。
- `inputModalities` 是**准入闸门**：`src/qoder-adapter.ts:213-215` 注释「DSH 在 LlmRuntime 里按适配器播报的 `inputModalities` 决定要不要把图片投影成文本占位符，声明支持就必须真支持」；`src/trae-adapter.ts:713-714` 记录了一个真实缺陷——早期硬编码 `['text']` 导致「DSH 在附件准入阶段就拒掉图片（Issue #IKHDKC）」。

#### `resolveModel(provider, model, signal?): Promise<LlmResolvedModelInfo>`【一手】

第三个参数 `signal?: AbortSignal` 在 5 个实现中**都被忽略**（写作 `_signal`，如 `src/llm-adapter.ts:801`、`src/trae-adapter.ts:719`）。

**返回字段全集**【一手，从各实现的赋值点汇总】：

| 字段 | 类型 | 赋值点 | 语义 |
|---|---|---|---|
| `provider` | `string` | 5 处均直接透传入参 | provider 路由 id |
| `id` | `string` | 5 处均直接透传 `model` | 模型 id |
| `name` | `string` | `src/llm-adapter.ts:804`、`src/buddy-adapter.ts:815`、`src/trae-adapter.ts:725`、`src/qoder-adapter.ts:184` | 展示名，查不到时回退裸 id |
| `inputModalities` | `readonly ('text'\|'image')[]` | `src/buddy-adapter.ts:816`、`src/trae-adapter.ts:727`、`src/qoder-adapter.ts:185` | 输入模态，**按模型判定** |
| `context.contextWindow` | `number` | `src/llm-adapter.ts:807`、`src/buddy-adapter.ts:818`、`src/trae-adapter.ts:730`、`src/qoder-adapter.ts:189` | 上下文窗口（最大合并请求+响应 token 数，`src/llm-adapter.ts:32`） |
| `defaultMaxTokens` | `number` | `src/buddy-adapter.ts:835`、`src/trae-adapter.ts:732` | 单次输出上限 |
| `reasoning.efforts` | `Array<{id: ReasoningEffortId, name: string}>` | `src/buddy-adapter.ts:843-847` | 推理档位可选集 |
| `reasoning.defaultEffort` | `ReasoningEffortId` | `src/buddy-adapter.ts:848-850` | 默认档位 |

**`context` 只在有值时赋值**（`src/llm-adapter.ts:807` 的 `if (contextWindow !== undefined)`）——「未公开上下文容量，留 undefined 让后端默认裁剪」（`src/llm-adapter.ts:36`）。qoder 的注释更明确：「未知模型**不编造** context（宁可让 DSH 用默认值，也不要报一个假的窗口大小）」（`src/qoder-adapter.ts:187-189`）。

**`defaultMaxTokens` 的机制**【一手，`src/buddy-adapter.ts:822-831`】：DSH 在 `resolveCallWithInfo` 里**只在调用方未显式给值时**用 `defaultMaxTokens` 兜底；适配器不声明就等于把值永久交给网关默认（实测网关默认仅 32000），会导致大文件写入在 32000 处被截断成 `finish_reason:'length'`。但也不能编造偏大的值——「编造一个偏大的值会让服务端 400 拒绝（参考 codearts 131072 被拒的实测）」。

**`reasoning` 的机制**【一手，`src/buddy-adapter.ts:836-838`】：这是"思考强度"选择器出现在模型选择里的**唯一入口**——composer 读取 `resolveModel().reasoning`；无等级可选的模型不声明该字段，UI 显示"当前模型未提供推理等级"。

#### `prepareCall(provider, model, signal?): Promise<{ model, stream }>`【一手】

```ts
// src/llm-adapter.ts:811-820
async prepareCall(provider, model, signal?): Promise<{
  model: LlmResolvedModelInfo
  stream: (options: GenerateOptions) => AsyncIterable<StreamChunk>
}> {
  return {
    model: { ...await this.resolveModel(provider, model, signal), inputModalities: ['text'] as const },
    stream: (options: GenerateOptions) => this.stream(options),
  }
}
```

**语义**【一手 + 推断】：把"模型解析"与"流式分发"绑定到**同一个适配器实例**，返回一个闭包。5 个实现都是 `model: await this.resolveModel(...)` + `stream: (options) => this.stream(options)`（`src/buddy-adapter.ts:863-872`、`src/lobsterai-adapter.ts:787`、`src/qoder-adapter.ts:200-209`、`src/trae-adapter.ts:739-748`）。

**为什么必须有它（真实缺陷）**【一手】：`src/buddy-adapter.ts:856-861` 注释——「本仓库链接的 dsh-llm 副本（0.1.0-rc.6）的 `LlmAdapter` 基类**尚未提供该方法**，缺少时会在每轮请求开始时抛 `registration.adapter.prepareCall is not a function`」。这是**基类契约随版本演进**的直接证据。

#### `stream(options: GenerateOptions): AsyncIterable<StreamChunk>`【一手】

核心推理入口。`GenerateOptions` 的字段（从消费点观测）：

| 字段 | 使用位置 | 语义 |
|---|---|---|
| `options.messages` | `src/llm-adapter.ts:845` | harness 对话消息数组（`{role, content}`，content 为块数组） |
| `options.system` | `src/llm-adapter.ts:851-853` | 独立系统提示（如标题生成的 systemPrompt、agent 的 persona） |
| `options.tools` | `src/llm-adapter.ts:856-863` | 工具定义（`{name, description, parameters}`） |
| `options.model` | `src/llm-adapter.ts:871`、`:881` | 模型 id |

`StreamChunk` 的字段（从 `yield` 点观测）：

```ts
// src/llm-adapter.ts:1380-1385
const reason = finishReason === 'length' ? { kind: 'max-tokens' as const }
  : finishReason === 'tool_calls' || toolOrder.length > 0 ? { kind: 'tool-calls' as const }
  : { kind: 'stop' as const }
yield { type: 'finish', reason }
```

**语义要点**【一手】：
- `system` 必须**显式插入 messages 数组**，否则模型看不到（`src/llm-adapter.ts:846-853` 记录实测：session 标题变成了 prompt 回显）。
- `stream` 内部自行做凭据解析与过期续期（`src/llm-adapter.ts:823-830`）：先 `resolveCredential()`，过期则 `refresh()` 后重取，仍无则抛 `LlmError('...', 'MISSING_CREDENTIAL')`。

### 4.6 `listAllModels` 的归属（用户特别关注的问题）

**结论：是插件自己加的，不是基类方法。**

三条证据：

1. **直接注释声明**【一手】——`src/jet-hub-rpc.ts:480-482`：
   > `listAllModels` 是本插件适配器额外提供的**不受用户黑名单影响**的完整目录（见各适配器的同名方法）。**DSH 的 `llm` 服务只保证 `listModels`**，故这里把它声明为可选。

2. **`ctx.llm` 上不存在该方法的调用点**【一手】——全仓只有 `ctx.llm.listModels()`（`src/jet-hub-rpc.ts:1189`），没有 `ctx.llm.listAllModels()`。

3. **插件改为绕过服务、直接持有适配器实例**【一手】——`src/index.ts:413-426`：

```ts
// provider → 适配器实例：Jet Hub「显示列表」需要 `listAllModels()`（不受用户
// 黑名单影响的全量目录，带最终展示名/倍率）。DSH 的 `ctx.llm` 只保证
// `listModels`，不透传自定义方法，故这里显式把实例传下去。
const modelAdapters: Record<string, { listAllModels(): readonly { id: string; name: string }[] }> = {
  codearts, buddy: buddyAdapter, workbuddy: workbuddyAdapter,
  lobsterai: lobsteraiAdapter, qoder: qoderAdapter, trae: traeAdapter,
}
```

`registerJetHubRpc` 的最后一个参数（`src/index.ts:428`）即该映射；接口用**结构化类型** `ModelCatalogSource` 声明，避免依赖具体适配器类（`src/jet-hub-rpc.ts:528-535`）。

**为什么需要它（真实缺陷）**【一手，`src/jet-hub-rpc.ts:1197-1213`】：`llm.listModels()` 返回的目录**已被适配器过滤掉黑名单**。若直接对该结果回填 `disabled`，会形成闭环矛盾——`disabledMap` 里的键恰好是 `models` 中已被移除的元素，`.map()` 永远匹配不到，被关闭的模型连同开关一起从设置页消失，用户**再也无法重新打开**（只能手工编辑 settings.yaml）。用户报障原文：「关闭的就没有显示倍率，关闭的应该也显示倍率」。

因此设置页目录必须以**未过滤**的全量为准：优先 `listAllModels()`，缺失时退化为"listModels 结果 + 黑名单补回裸 id"（`src/jet-hub-rpc.ts:1215-1229`）。

---

## 5. 模型解析链路

### 5.1 路由：宿主如何把模型标识送到 adapter

**这是"注册 + 路由表"机制，不是"字符串解析"机制。**【推断，证据充分】

```
① 激活期注册：
   ctx.llm.registerConfigurableProviders([{provider:'codearts', displayName, settingsNs, settingsPath}])
      → 宿主登记"有一个可配置 provider 叫 codearts"
   ctx.llm.registerAdapter(['codearts'], adapterInstance)
      → 宿主登记"codearts 的适配器是这个实例"
   【一手】src/llm-adapter.ts:1441 / :1445

② 运行期消费（推断）：
   宿主拿到 (provider, model) 二元组
      → 按 provider 查路由表得 adapter
      → adapter.resolveModel(provider, model, signal)  得元信息
      → adapter.prepareCall(provider, model, signal)   得 { model, stream }
      → stream(options) 产出 AsyncStream
   【推断】依据：src/qoder-adapter.ts:194-198（"LlmRuntime.prepareCall() 会调用
   registration.adapter.prepareCall(...)"）
```

**关键认识：`resolveModel` 不做路由。** 路由由 `registerAdapter` 的 `providers: string[]` 建立；`resolveModel` 只负责**补元数据**。5 个实现里 `provider` 与 `id` 都是**原样透传**入参（`src/llm-adapter.ts:806`、`src/buddy-adapter.ts:812-813`、`src/trae-adapter.ts:722-724`、`src/qoder-adapter.ts:181-183`），只有 `name` / `context` / `inputModalities` / `defaultMaxTokens` / `reasoning` 是查表补出来的。

### 5.2 `resolveModel` 具体做了什么（以 TraeAdapter 为例，字段最全）

```ts
// src/trae-adapter.ts:719-737
async resolveModel(provider, model, _signal?): Promise<LlmResolvedModelInfo> {
  await this.ensureRemoteModels()                    // ① 懒加载远端目录（若未加载）
  const remoteName = this.remoteMeta.get(model)?.name
  const resolved: LlmResolvedModelInfo = {
    provider, id: model,
    name: remoteName ?? this.fallbackIndex.get(model)?.name ?? model,   // ② 展示名三级回退
    inputModalities: this.inputModalitiesFor(model),                     // ③ 按模型判定模态
  }
  const contextWindow = this.contextWindowFor(model)
  if (contextWindow !== undefined) resolved.context = { contextWindow }  // ④ 有才写，不编造
  const maxTokens = this.maxOutputTokensFor(model)
  if (maxTokens !== undefined) resolved.defaultMaxTokens = maxTokens     // ⑤ 同上
  const reasoning = this.reasoningFor(model)
  if (reasoning !== undefined) resolved.reasoning = reasoning            // ⑥ 档位
  return resolved
}
```

**共性模式（5 个实现一致）**：

| 步骤 | 行为 | 证据 |
|---|---|---|
| ① 懒加载远端目录 | `await this.ensureRemoteModels()` —— **`resolveModel` 可能先于 `listModels` 被调用**（如直接进入会话），此时同样触发远端拉取 | `src/llm-adapter.ts:755-758`、`src/buddy-adapter.ts:592-595`、`src/trae-adapter.ts:720` |
| ② 展示名回退 | 远端 → 产品兜底表 → 裸 id | `src/llm-adapter.ts:804`、`src/buddy-adapter.ts:815`、`src/trae-adapter.ts:725` |
| ③ 模态按模型判定 | 未声明时**保守报 `['text']`**（"宁可少报能力，也不要报一个服务端不认的模态"） | `src/qoder-adapter.ts:134-141` |
| ④⑤⑥ 有值才写 | 不编造 | `src/llm-adapter.ts:36`、`src/qoder-adapter.ts:187-189` |

**上下文窗口的三级查找**【一手，`src/buddy-adapter.ts:807-811`】：远端 `maxInputTokens` → 产品兜底表 → 通用静态表。codearts 则只有静态表（`src/llm-adapter.ts:805`，`CONTEXT_WINDOWS` 定义于 `src/llm-adapter.ts:38-43`）。

**远端与兜底表的权威性权衡**【一手，`src/buddy-adapter.ts:618-689`】：`reconcileWithFallback()` 做**白名单式重建**——只保留兜底表声明的 id、补齐兜底表有而远端缺的模型，但**例外**：被 agent 引用的模型即使不在兜底表也保留（判据 `agentReferenced`，即服务端自己声明"对话里可选"）。注释记录的真实原因：实测 `hy4-preview-f` 只由 `/v3/config` 下发且被 `craft`/`ask`/`plan` 三个 agent 引用，白名单重建会把它丢掉。

### 5.3 三个信息结构的字段对照

| 结构 | 字段 | 证据 |
|---|---|---|
| `LlmProviderInfo` | `id`（= provider）、`name`（展示名） | `src/llm-adapter.ts:748`、`src/buddy-adapter.ts:584` |
| `LlmModelInfo` | `provider`、`id`、`name`、`inputModalities` | `src/llm-adapter.ts:798`、`src/buddy-adapter.ts:782-787`、`src/trae-adapter.ts:709-716`、`src/qoder-adapter.ts:169-176` |
| `LlmResolvedModelInfo` | `provider`、`id`、`name`、`inputModalities`、`context.contextWindow`、`defaultMaxTokens`、`reasoning.efforts`、`reasoning.defaultEffort` | 见 §4.5 表格 |

**`LlmModelInfo` 与 `LlmResolvedModelInfo` 的差别**：
- `LlmModelInfo` = **目录项**（用于模型选择器渲染列表），**不含** `context` / `defaultMaxTokens` / `reasoning`。
- `LlmResolvedModelInfo` = **已解析的调用目标**（用于发起请求），含全部运行时元数据。
- 这个差别是**观测结论**：`listModels` 的返回对象字面量里从不出现 `context`/`reasoning`（4 处实现），而 `resolveModel` 里频繁出现。

**模态的枚举取值**【一手】：`'text' | 'image'`（`src/qoder-adapter.ts:140` 的返回类型 `readonly ('text' | 'image')[]`）。

---

## 6. settings namespace 与"模型设置页"

### 6.1 两个 namespace 体系

插件用了**两套互不相同的** settings namespace：

| namespace | 命名模式 | 用途 | 注册位置 |
|---|---|---|---|
| `llm-<providerId>` | 每个 provider 一个 | 供**宿主的模型设置页**读取该 provider 的配置 | `src/index.ts:129` |
| `jet-hub` | 单例 | 插件自己的账号索引 + 模型黑名单 | `src/account-pool.ts:19`、`src/account-pool.ts:152` |

**`llm-*` 的六个值**【一手，`src/index.ts:129`】：

```ts
registerProviderSettings(
  ctx, 'llm-buddy', 'llm-workbuddy', 'llm-codearts', 'llm-lobsterai', 'llm-qoder', 'llm-trae',
)
```

与 `registerXxxLlm` 里 `settingsNs: \`llm-${product.id}\`` 一一对应（`src/llm-adapter.ts:1442` 是硬编码 `'llm-codearts'`；`src/buddy-adapter.ts:1452`、`src/lobsterai-adapter.ts:1319`、`src/qoder-adapter.ts:474`、`src/trae-adapter.ts:1381` 是模板派生）。

`src/index.ts:124-129` 的注释说明了这个映射关系，并明确「漏注册会让模型设置页在 `refFor → deriveKeyRef(provider)` 处以 `provider.toUpperCase is not a function` 崩溃」。

### 6.2 `settingsNs` 的作用与失败机制

**作用（两层）**【一手，来自注释 + 测试】：

1. **让模型设置页能定位该 provider 的配置** —— 设置页拿到 `settingsNs` 后去 settings 服务读该 namespace。
2. **让设置页能算出凭据 ref** —— 通过 `refFor → deriveKeyRef(provider)`，其内部调用 `provider.toUpperCase()`（`src/index.ts:41-42`、`src/buddy-adapter.ts:573`、`tests/unit/plugin.spec.ts:241-242`）。

**失败链 1：namespace 未注册 → 设置页崩溃**【一手，`src/index.ts:37-41`】：

> `registerConfigurableProviders` 声明的 `settingsNs` 必须真实存在于 settings 服务中，否则模型设置页读到 undefined 的 namespace，在 `refFor → deriveKeyRef(provider)` 处会以 `provider.toUpperCase is not a function` 崩溃。

回归测试：`tests/unit/plugin.spec.ts:243-249`（workbuddy）、`tests/unit/plugin.spec.ts:363-369`（lobsterai）。

**失败链 2：schema 不是 schemastery 对象 → 所有 settings 界面崩溃**【一手，`src/index.ts:43-48`】：

> 注意：`settings.register()` 要求 schemastery schema —— `describe()` 会对每个注册项无条件调用 `schema.toJSON()` 与 `redactSecrets(schema, value)`。传入裸函数（`(value) => ...`）会让 `describe()` 抛 `TypeError: registration.schema.toJSON is not a function`，进而使**所有**依赖 settings 的界面（模型设置页、主题、sidebar 的 settings.get/shell.get）**全部失败**。因此这里必须用 `Schema.object({...})` 构造。

**为什么必须是 schemastery 对象而不是裸函数**【一手 + 推断】：
- 【一手】事实：`describe()` 会无条件调 `schema.toJSON()` 与 `redactSecrets(schema, value)`；裸函数没有 `toJSON`。
- 【推断】"裸函数"在这个生态里可能是另一种合法的校验器形式（否则不会有人这么写），但 `describe()` 的路径只认 schemastery。仓库未解释这一点，只陈述了后果。

**为什么必须回读 `describe()`**【一手，`src/index.ts:75-78`】：

> 回读确认：模型设置页要求 `settingsNs` 真实存在于 `describe()` 中。注意：`describe()` 会遍历**所有**已注册 namespace 并调用各自 schema 的 `toJSON()`/`redactSecrets()`，**任一注册项的 schema 不合规都会让整条调用抛错**。因此这里必须把异常打出来，而不是静默吞掉。

**这解释了"回读"的真正动机**：不是"确认自己注册成功"（注册是同步的），而是**探测整条 `describe()` 链路是否健康**——因为别人注册的坏 schema 也会让"我"的设置页挂掉。所以 `src/index.ts:87-92` 用 `ctx.logger.error` 打印完整 stack。

**实现细节**【一手，`src/index.ts:52-93`】：
- 共用同一个宽松 schema（`src/index.ts:50-52`）：
  ```ts
  const providerSettingsSchema = Schema.object({
    providers: Schema.dict(Schema.any()).default({}),
  })
  ```
  注释解释："两者都只需承接一个可选的 `providers` 映射，故共用同一宽松 schema"（`src/index.ts:43`）。
- 注册失败时 `catch` 并 `warn`，不抛（`src/index.ts:69-73`）。
- settings 服务本身缺失时 `warn` 后直接返回（`src/index.ts:64-67`）。

**`jet-hub` namespace 的 schema**【一手，`src/account-pool.ts:64-75】：

```ts
const jetHubSchema = Schema.object({
  accounts: Schema.array(Schema.any()).default([]),
  disabledModels: Schema.dict(Schema.any()).default({}),
})
```

两条设计决策有注释解释：
- 用 `Schema.dict(Schema.any())` 而非 `Schema.array(...)`：让 settings 的 schema 校验"不把动态结构（任意 provider、任意模型 id）拒之门外"（`src/account-pool.ts:68-70`）。
- 必须带 `.default({})`：否则 namespace 首次注册时 `scope.get()` 返回 undefined，读取处需层层判空（`src/account-pool.ts:72-73`）。

**注册失败降级**【一手，`src/account-pool.ts:151-156`】：重复注册（如插件热重载）时 `catch` 并降级为内存态，`scope` 保持 undefined，后续写入只改内存并 `warn`（`src/account-pool.ts:193-195`、`:246-248`）。

**settings 的读写语义**【一手，`src/account-pool.ts:184-198`】：`replace()` 是**整体替换**，因此写账号列表时必须**连同黑名单一起写回**，否则会抹掉同一 namespace 下的另一个字段。`src/account-pool.ts:250-251` 有对称的注释。

**进程内权威副本**【一手，`src/account-pool.ts:127-141`】：`AccountPool` 不直接依赖 `scope.get()`，理由是"settings 服务的 resolved 快照在 `replace()` 后未必立即更新，而本类的每次写入都是'读 → 改 → 整体 replace'"，以滞后快照为读源会导致并发写入互相覆盖（典型表现：settings.yaml 里一条 `modelRateLimits` 都没有）。

### 6.3 模型设置页是宿主的界面，不是插件的

【一手】`README.md:98`：「登录后在 dsh **Models 页面**选择该 provider 即可」。该页面由宿主提供，通过 `settingsNs` 读取插件注册的 namespace。插件只提供**目录数据**（`registerConfigurableProviders`）与**适配器**。

---

## 7. Web 客户端 bundle

### 7.1 `plugin-src/client/` 是什么

**它是插件在宿主 Web UI 里的前端部分**——一个注册进 `settings.section` slot 的 React 页面。**它不参与模型推理**，只负责账号管理的人机交互（§8.4）。

| 文件 | 行数 | 职责 |
|---|---|---|
| `plugin-src/client/index.js` | 29 | 客户端插件入口：导出 `name`/`inject`/`apply`，注册 slot |
| `plugin-src/client/jet-hub.js` | 1079 | React 页面主体（`JetHubPage` + 各 provider 面板 + 账号卡片 + 模型开关弹窗） |
| `plugin-src/client/jet-hub-styles.js` | 181 | 注入 CSS（`const STYLES`，`plugin-src/client/jet-hub-styles.js:5`） |
| `plugin-src/client/credits-capabilities.js` | 84 | 积分能力矩阵（`CREDITS_CAPABILITIES`，`plugin-src/client/credits-capabilities.js:54`） |
| `plugin-src/client/account-order.js` | 67 | 拖拽排序纯逻辑（`orderAfterDrop`，`plugin-src/client/account-order.js:41`） |
| `plugin-src/client/build.mjs` | 42 | esbuild 构建脚本 |
| `plugin-src/management-rpc.mjs` | 45 | RPC 调用封装（`callManagementRpc`，`plugin-src/management-rpc.mjs:29`） |

### 7.2 客户端插件契约（与宿主侧同构）

```js
// plugin-src/client/index.js:7-8
export const name = 'jet-hub-client'
export const inject = ['slots', 'connection']

// plugin-src/client/index.js:14-29
export function apply(ctx) {
  ctx.effect(() => installJetHubStyles(), 'jet-hub: install styles')
  const rpcCall = async (endpoint, payload, signal) => {
    const raw = await callManagementRpc(ctx.connection, JET_HUB_RPC_CHANNEL, endpoint, payload, signal)
    return unwrapRpcResult(raw)
  }
  ctx.slots.inject('settings.section', () => ctx.slots.register({
    name: 'settings.section',
    id: 'jet-hub',
    order: 50,
    label: () => 'Jet Hub',
    inject: () => ({ rpcCall }),
  }, JetHubPage))
}
```

**观测事实**【一手】：
- 客户端插件同样导出 `name` / `inject` / `apply`（与宿主侧同构，但 `name` 不同：`'jet-hub-client'`）。
- `inject: ['slots', 'connection']` —— 两个都是**宿主客户端侧**的服务。
- 注册进 `settings.section` slot，`id: 'jet-hub'`，`order: 50`，`label: () => 'Jet Hub'`。
- 通过 `inject: () => ({ rpcCall })` 把 RPC 能力注入组件（组件从 props 收到 `rpcCall`，`plugin-src/client/jet-hub.js:1036` 的 `JetHubPage({ close, rpcCall })` 确认）。
- `close` prop 由 slot 框架注入（`plugin-src/client/jet-hub.js:1051-1054` 渲染"关闭"按钮）—— 推测这是**弹窗/模态**形态。

**渲染位置**【一手 + 推断】：渲染在宿主设置的 **"Jet Hub" 区块**内（`label: () => 'Jet Hub'`，`order: 50`）。页面结构是左侧 provider 导航栏 + 右侧面板（`plugin-src/client/jet-hub-styles.js:12-16` 注释"布局：对齐 dsh-im 的两栏"）。

六个 provider 面板（`plugin-src/client/jet-hub.js:69-76`）：`codearts` / `buddy` / `workbuddy` / `lobsterai` / `qoder` / `trae`。

### 7.3 打包与加载

**打包**【一手，`plugin-src/client/build.mjs`】：

```js
const outputPath = resolve(packageRoot, 'lib/client/jet-hub.js')   // :8
const loaderId = 'dsh-codearts-auth'                               // :9
const result = await build({                                       // :11
  entryPoints: [resolve(sourceDirectory, 'index.js')],
  bundle: true, format: 'cjs', platform: 'browser', target: ['chrome100'],
  charset: 'utf8',                          // :20 —— 保留中文原文，加载器按 utf8 解码
  external: ['react', 'react-dom'],         // :21 —— React 由宿主提供
  write: false,
  minify: process.env.NODE_ENV === 'production',
  legalComments: 'none',
})
const wrapped = `window.__ModuleLoader__.load({                 // :29
  id: ${JSON.stringify(loaderId)},
  factory: (require) => { var module = { exports: {} }; var exports = module.exports;
${bundled}
    return module.exports; },
});`
```

**关键点**【一手】：
- `loaderId` = **包名** `'dsh-codearts-auth'`（`plugin-src/client/build.mjs:9`），不是插件名 `'jet-hub-client'`。
- 产物是 **CJS**，但包在 `window.__ModuleLoader__.load({id, factory})` 里（`plugin-src/client/build.mjs:29-38`）——这是宿主的客户端模块加载协议。
- `react` / `react-dom` 是 **external**（`plugin-src/client/build.mjs:21`）——由宿主提供，插件不打包。`plugin-src/client/account-order.js:5` 的注释印证："组件本身无法在本仓库单测里渲染（**react 不在依赖内**）"。
- `charset: 'utf8'`（`plugin-src/client/build.mjs:20`）有明确理由：默认 ascii 会把中文转义成 `\uXXXX`，使"用 includes 校验产物文案"的做法失效；加载器按 utf8 解码所以安全。

**构建脚本编排**【一手，`package.json:20-26`】：
```
build        = tsc -p tsconfig.json          （宿主侧 → lib/index.js）
build:client = node plugin-src/client/build.mjs  （客户端 → lib/client/jet-hub.js）
build:assets = node scripts/copy-assets.mjs
build:all    = build && build:assets && build:client
prepare      = build:all
```

**`dsh.client.platform: "web"` 的含义**【一手 + 推断】：
- 【一手】声明位置：`package.json:51-53`。
- 【一手】暴露入口：`exports["./client"] = "./lib/client/jet-hub.js"`（`package.json:13`）。
- 【推断】语义：声明客户端 bundle 的目标平台是 **web**（浏览器 UI），而非 TUI/终端。宿主据此决定是否加载该 bundle。仓库未解释该字段的其他取值。

**为什么不参与推理**【一手】：
- 客户端 bundle 的所有 RPC 调用都是管理方法（`account.list` / `account.create` / `login.poll` / `credits.*` / `model.list` / `model.setDisabled` 等），见 `plugin-src/client/jet-hub.js:377`、`:406`、`:546`、`:588`、`:651`、`:701`、`:729`、`:754`、`:764`、`:790`、`:876-879`。
- 客户端**没有**任何直接调用模型推理的代码路径。

---

## 8. Jet Hub RPC 的真实性质（关键节）

### 8.1 结论

**`/api/jet-hub` 不是插件自己起的 HTTP 服务器，而是插件挂在宿主 web 服务上的一条路由。**

### 8.2 机制证据链

**① 注册方式：`register`，不是 `listen`**【一手，`src/jet-hub-rpc.ts:556-601`】

```ts
connection.fetch.register({
  path: JET_HUB_API_PATH,            // '/api/jet-hub'  （src/jet-hub-rpc.ts:95）
  methods: ['POST'],                 // src/jet-hub-rpc.ts:558
  requestBody: 'buffered' as const,
  async fetch(request: Request): Promise<Response> {
    if (request.method !== 'POST') return new Response('method not allowed', { status: 405 })
    const contentType = ...; if (contentType !== 'application/json') return new Response(..., { status: 415 })
    let message; try { message = await request.json() } catch { return new Response('body is not JSON', { status: 400 }) }
    ...
    const result = await handleMethod(call.method as string, call.payload, request.signal)
    return reply(rpcId, result)
  },
})
```

**这是 Web 标准 `Request → Response` 的 handler 注册**（`request.json()`、`request.headers.get()`、`request.signal` 都是标准 API），由**宿主**的 HTTP 服务器在匹配到该 path 时调用。插件自己从未调用 `createServer` / `listen`（§1.2 反证 A）。

模块头也直接说明【一手，`src/jet-hub-rpc.ts:4-6`】：「使用 DSH 的 `connection.fetch.register()` 模式注册 HTTP API 端点，与 dsh-im 的 `registerManagementRpc` 一致。通道名 jet-hub → 路径 /api/jet-hub」。

**② `connection` 服务由宿主 Web bundle 提供**【一手，`src/index.ts:27-28`】：

> `connection` 刻意不列入静态 inject：它只由 **Web bundle（dsh-client-connection）** 提供，headless/CLI profile 里并不存在。

**③ 挂载方式：惰性注入**【一手，`src/jet-hub-rpc.ts:521-525`】：

```ts
ctx.inject(['connection'], (connectionCtx) => {
  registerJetHubEndpoints(connectionCtx as Context, pool, codearts, buddy, workbuddy,
                          lobsterai, qoder, trae, modelAdapters)
})
```

`src/jet-hub-rpc.ts:496-501` 注释："`connection` 服务只存在于 Web bundle；这里用**惰性注入**而非插件级静态 `inject`，因此在 headless / CLI profile 下本模块正常加载、只是不注册端点，而不是把整个插件树卡在 pending（那会让 profile 启动直接失败）。"

**④ 双保险的可用性检查**【一手，`src/jet-hub-rpc.ts:550-554`】：

```ts
const connection = (ctx as any).connection ?? ctx.get('connection')
if (!connection || typeof connection.fetch?.register !== 'function') {
  ctx.logger.warn('[jet-hub] connection.fetch not available, RPC endpoints not registered')
  return
}
```

**⑤ 客户端调用路径**【一手，`plugin-src/management-rpc.mjs:24-30`】：

```js
export function callManagementRpc(connection, channel, method, payload, signal) {
  // mountPoint = '/api', endpoint = 'jet-hub'
  return connection.rpc.call('/api', ENDPOINT, { method, payload }, signal)
}
```

模块头（`plugin-src/management-rpc.mjs:7-9`）说明：「Host 注册：`/api/jet-hub`；Client 调用：`connection.rpc.call('/api', 'jet-hub', { method, payload }, signal)`」。即宿主侧 `path` 与客户端侧 `(mountPoint, endpoint)` 是**同一路由的两种表达**。

### 8.3 为什么 headless / CLI profile 下不存在

**链路**【一手 + 推断】：

```
headless/CLI profile 不加载 Web bundle（dsh-client-connection）
  → connection 服务不 provide
  → ctx.inject(['connection'], cb) 的回调永不执行（src/jet-hub-rpc.ts:521）
  → Jet Hub RPC 端点未注册
  → 但插件其余部分（六个 provider 的 llm 路由、凭据续期）正常加载
```

**⚠️ 这个设计的动机是"避免插件加载失败"，不是"避免 RPC 不可用"。**【一手，`src/index.ts:25-31`】：

> 静态 `inject` 会让本插件在那些 profile 里永久 pending，进而让整个 profile 以 `"plugin tree failed to load: 1 entry did not activate"` 启动失败 —— **chicheng-cron 的 skill/agent 任务正是通过 `dsh --profile headless` 运行的，会因此全部 exit 1**。

**这条是本调研中最有工程价值的发现之一**：它证明**模型推理能力在 headless profile 下是必需的**（cron 任务靠它跑 agent），而**人机管理界面是 Web 专属的**。这正好把两条流量路径的边界钉死了（§8.4）。

**回归测试**【一手，`tests/unit/plugin.spec.ts:318-342`】：该测试注释说「这条断言锁住的是『**能不能加载**』而非某个功能细节，所以即便日后有人为了 UI 更"直接"而把 connection 加回静态 inject，也必须先看到这里失败。」

### 8.4 承载的是"人机管理流量"还是"模型推理流量"？

**结论：100% 人机管理流量，0% 模型推理流量。**

**证据 1 — 端点方法清单全是管理操作**【一手，`src/jet-hub-rpc.ts:7-11`】：

```
account.list / account.create / account.update / account.delete /
account.reorder / account.refresh / account.retest / account.retestAll /
account.reset / account.resetAll / login.poll /
credits.status / credits.claimAll / credits.balances /
model.list / model.setDisabled
```

16 个方法，无一涉及对话补全。分派器 `handleMethod` 的 `switch` 在 `src/jet-hub-rpc.ts:604` 起。

**证据 2 — 推理走的是完全不同的通道**【一手】：

| | 模型推理流量 | 人机管理流量 |
|---|---|---|
| 入口 | `adapter.stream(options)` 被宿主调用 | `connection.fetch` 的 handler |
| 触发者 | 宿主内部的 agent/session 逻辑 | 浏览器里的 React 页面 |
| 传输 | **进程内函数调用**（`AsyncIterable<StreamChunk>`） | 宿主 web 服务上的 HTTP POST `/api/jet-hub` |
| 出网 | 适配器内直接 `fetch` 厂商 HTTPS 端点（`src/llm-adapter.ts:835`） | 由账号池/凭据服务间接出网（积分、续期等） |
| 依赖 `connection` | **不依赖**（headless 下照常工作） | **依赖**（headless 下无此端点） |
| 依赖 `llm` | 是（注册适配器） | 仅 `model.list` 读取目录（`src/jet-hub-rpc.ts:1189`） |

**证据 3 — `model.list` 是唯一的"交叉点"，且只读目录**：

`case 'model.list'`（`src/jet-hub-rpc.ts:1181`）调 `llm.listModels(req.provider)`（`src/jet-hub-rpc.ts:1189`）读模型目录，用于设置页渲染开关。这是**读取元数据**，不是发起推理。而且它是通过 `ctx.get('llm')` 惰性获取的（`src/jet-hub-rpc.ts:488`），注释说明"llm 服务缺失时账号面板仍应可用，只是「显示列表」按钮报错"（`src/jet-hub-rpc.ts:477-478`）。

**证据 4 — 客户端登录用 `window.open` 而非任何推理通道**【一手，`plugin-src/client/jet-hub.js:717`】：

```js
const loginWindow = window.open(loginUrl, '_blank', 'width=800,height=600')
...
const pollRes = await rpcCall('login.poll', { accountId, provider })   // :729
```

**两条路径的完整图示：**

```
【模型推理流量】—— 进程内，无 HTTP 边界
  宿主 agent/session
    └─ ctx.llm 路由表 → adapter.resolveModel() / prepareCall() → stream(options)
         └─ 适配器内 fetch() → 厂商 HTTPS（华为云/腾讯/有道/阿里/字节）
              └─ SSE 解析 → yield StreamChunk → 回到宿主
   ※ 全程不经过 /api/jet-hub，不需要 connection，headless profile 下照常工作

【人机管理流量】—— HTTP，Web profile 专属
  浏览器 React（JetHubPage）
    └─ connection.rpc.call('/api', 'jet-hub', {method, payload})
         └─ 宿主 web 服务 → path === '/api/jet-hub' → connection.fetch handler
              └─ handleMethod(method, payload)
                   ├─ account.*  → AccountPool / 各 Auth 服务
                   ├─ credits.*  → 各厂商积分端点
                   └─ model.list → ctx.get('llm').listModels()  【唯一交叉点，只读】
   ※ 需要 connection，headless profile 下整条不存在
```

---

## 9. 宿主服务依赖清单

### 9.1 硬依赖（静态 `inject`，缺则插件不激活）

`src/index.ts:33`：`export const inject = ['credentials', 'commands', 'llm']`

| 服务 | 用途 | 调用点 |
|---|---|---|
| `credentials` | 凭据存取（令牌 / refresh_token 的加密存储） | `credentialRef()` 构造 ref（`src/index.ts:199`、`:224`）；`ctx.credentials.resolve()`（`src/index.ts:206`、`:231`）；`ctx.credentials.set()`（`src/service.ts:145`）；`ctx.credentials.describe()`（`tests/unit/plugin.spec.ts:40`） |
| `commands` | 注册宿主斜杠命令 | `ctx.commands.register({name, description, handler})`（`src/index.ts:150`、`:165`、`:182`） |
| `llm` | 注册 provider 路由与适配器 | `ctx.llm.registerConfigurableProviders()` + `ctx.llm.registerAdapter()`（`src/llm-adapter.ts:1454`/`:1445` 等 5 组） |

**缺了会怎样**【一手注释，`src/index.ts:25-31` + `tests/unit/plugin.spec.ts:318-342`】：该 profile 下插件**永久 pending** → 整个 profile 以 `"plugin tree failed to load: 1 entry did not activate"` **启动失败** → 该 profile 下所有任务 exit 1。

> 【推断】：以上"pending → 启动失败"是注释的直接陈述，但 Cordis 的具体实现机制无源码依据。

### 9.2 软依赖（`ctx.get` / `ctx.inject` 惰性获取，缺则降级）

| 服务 | 用途 | 获取方式 | 缺失后果 |
|---|---|---|---|
| `settings` | ① `llm-*` provider namespace（供模型设置页）② `jet-hub` namespace（账号索引 + 模型黑名单） | `ctx.get('settings')`（`src/index.ts:57`、`src/account-pool.ts:146`） | ① `warn` 后跳过注册，模型设置页相关功能失效（`src/index.ts:64-67`）② 账号列表仅存内存，不持久化（`src/account-pool.ts:147-149`、`:193-195`） |
| `attachments` | 把持久化图片读成原始字节供适配器内联 | `ctx.get('attachments')`（`src/index.ts:105`） | 收到图片时抛 `UNSUPPORTED_CONTENT`（`src/index.ts:110-115`） |
| `connection` | 挂载 Jet Hub 管理 RPC 端点 | `ctx.inject(['connection'], cb)`（`src/jet-hub-rpc.ts:521`）+ 双保险检查（`src/jet-hub-rpc.ts:550`） | 不注册端点，其余功能正常（`src/jet-hub-rpc.ts:552`） |
| `slots` | **仅客户端**：注册 `settings.section` slot | `inject = ['slots','connection']`（`plugin-src/client/index.js:8`） | 页面无法挂载（客户端侧硬依赖） |

`src/index.ts:96-105` 的注释解释了为什么 `attachments` 用 `ctx.get` 而非 `inject`：「用 `ctx.get` 而非 `inject` —— 附件服务缺失时 provider 仍可正常加载，只是收到图片时报 `UNSUPPORTED_CONTENT`。」

### 9.3 插件对外 provide 的能力（反向）

| 名称 | 位置 | 说明 |
|---|---|---|
| `accountPool` | `src/index.ts:429` | `ctx.provide('accountPool', pool)` —— 供同进程其他插件使用 |
| `codeartsAuth` | `src/service.ts:93`（`super(ctx, 'codeartsAuth')`） | `Service` 子类，构造时按名注册 |
| `buddyAuth` / `workbuddyAuth` | `src/index.ts:248-249` 注释说明由 `product.id` 派生 | 两个独立实例，各读自己的凭据 ref |
| `lobsteraiAuth` | `src/index.ts:277` 注释 | 由 `product.id` 派生 |
| `qoderAuth` | `src/index.ts:324` 注释 | 由产品 id 派生 |
| `traeAuth` | `src/index.ts:367` 注释 | 由 `product.id` 派生 |

六个 Auth 服务遵循统一接口（`AGENTS.md:127-134`）：`login` / `status` / `refresh` / `logout` / `refreshAccountCredential(refName)` / `fetchModels` / `refreshAll(pool)`。

### 9.4 依赖清单小结（一张表）

| 服务 | 类型 | 硬/软 | 服务于哪条流量 |
|---|---|---|---|
| `credentials` | 宿主 base | **硬** | 推理（签名）+ 管理（登录） |
| `commands` | 宿主 base | **硬** | 管理（斜杠命令，仅 codearts 保留） |
| `llm` | 宿主 base | **硬** | **推理**（注册适配器） |
| `settings` | 宿主 base | 软 | 管理（账号索引）+ 宿主模型设置页 |
| `attachments` | 宿主插件（如 `dsh-attachment-local`） | 软 | 推理（图片内联） |
| `connection` | 宿主 **Web bundle** | 软 | **管理**（Jet Hub RPC） |
| `slots` | 宿主 **Web bundle** | 软（客户端） | 管理（页面挂载） |

---

## 10. 与 "API / CLI / sidecar" 三种形态的边界对照

| 形态 | 本插件是？ | 理由（带证据） | 该形态的典型特征（本插件**没有**） |
|---|---|---|---|
| **OpenAI 兼容 HTTP 服务** | ❌ 不是 | 无推理端点；`openai-compat.ts` 是客户端侧序列化（`src/openai-compat.ts:2`）；`createServer` 仅用于 OAuth 回调（`src/login.ts:170`） | `/v1/chat/completions` 路由、监听端口、SSE 响应、API Key 鉴权 |
| **子进程 CLI** | ❌ 不是 | `package.json` 无 `bin`；`spawn` 只用于 `openBrowser()`（`src/login.ts:135`）；斜杠命令是宿主内的（`src/index.ts:150`） | 可执行文件、argv 解析、stdout 协议、`--help` |
| **MCP server** | ❌ 不是 | 全仓无 MCP 协议实现；`stdio` 仅出现在 `spawn` 选项（`src/login.ts:125`、`:135`） | JSON-RPC over stdio/SSE、`initialize`/`tools/list`、tool schema 协商 |
| **sidecar 代理** | ❌ 不是（仓库显式否决） | `docs/lobsterai-integration-plan.md:131-148`：不需要跑反代，`ctx.llm.registerAdapter()` 已经就是那一层 | 独立进程、独立端口、`config.json`、`auths/` 目录 |
| **宿主进程内原生 LLM Provider 插件** | ✅ **是** | `src/index.ts:25`/`:34`/`:122`（Cordis 插件）；`src/llm-adapter.ts:1458`（注册适配器）；`src/llm-adapter.ts:835`（进程内 `AsyncIterable`）；`AGENTS.md:984`（同进程崩溃） | —— |

**与"本地 LLM"（本地权重推理）的区别（再强调一次）：**

| | 本插件 | 真正的"本地 LLM"（如 ollama / llama.cpp 后端） |
|---|---|---|
| 模型权重位置 | **远端厂商**（`src/llm-adapter.ts:14` 等） | 本地磁盘 |
| 本地算力消耗 | 仅协议翻译 + JSON/SSE 处理 | GPU/CPU 推理 |
| 本地进程内是否有推理引擎 | ❌ 无 | ✅ 有 |
| "本地"修饰的是 | **适配器代码的宿主位置** | **推理的物理位置** |
| 断网后能否推理 | ❌ 不能 | ✅ 能 |

---

## 11. 不确定项与文档失真清单

### 11.1 明确的不确定项（诚实声明）

| # | 不确定项 | 为何不确定 | 影响 |
|---|---|---|---|
| 1 | `registerConfigurableProviders` / `registerAdapter` 的**真实返回值** | `@deepseek-ai/dsh-llm` 不存在，只能读测试替身（`tests/unit/plugin.spec.ts:62-75`） | 低（插件不使用返回值） |
| 2 | `ctx.llm` 的**完整方法集** | 同上；插件只用了 3 个 | 中（若有其他方法可能改变形态判断，但可能性低） |
| 3 | `LlmRuntime` 的内部实现 | 无源码，只有注释（`src/qoder-adapter.ts:194-198`、`tests/unit/buddy-adapter.spec.ts:513`） | 中（§5.1 的路由链是推断） |
| 4 | `LlmAdapter` 基类**提供了哪些方法** | 无源码。已知它**不提供** `prepareCall`（0.1.0-rc.6 版本，`src/buddy-adapter.ts:856-861`） | 中（无法确定基类是否提供 `listModels` 默认实现等） |
| 5 | `ctx.effect` 的精确语义（是否立即执行 callback、disposer 调用时机） | Cordis 源码不可读；只有调用形状（`src/index.ts:391`）+ 测试行为（`tests/unit/plugin.spec.ts:186`） | 低 |
| 6 | `settingsPath: []` 的语义 | 5 处调用点全传空数组，无消费方，无注释 | 低 |
| 7 | `dsh.client.platform: "web"` 的其他合法取值 | 仓库未说明 | 低 |
| 8 | `ctx.schema` 是否存在 | `AGENTS.md:123` 提到但代码中无调用点 | 低（文档可能过期） |
| 9 | `stop()` 是否幂等 | dispose 时会调用两次（`src/index.ts:393-398`、`:446-451`），未逐一核对实现 | 低 |
| 10 | 宿主如何校验 `info.id === provider` | 注释陈述（`src/buddy-adapter.ts:572`），无源码 | 低 |

### 11.2 文档失真清单（用户要求核对"文档可能过期"）

| 文档 | 位置 | 问题 | 严重度 |
|---|---|---|---|
| `AGENTS.md` | `AGENTS.md:152` | 写 `ctx.llm.registerProvider()`，**该方法名在代码中不存在**；实际是 `registerConfigurableProviders()` + `registerAdapter()` | **高**（会误导实现者） |
| `AGENTS.md` | `AGENTS.md:123` | 写"插件配置通过 `ctx.schema` 在 profile layer 栈中声明"，代码中**无 `ctx.schema` 调用点** | 中 |
| `docs/adding-a-new-provider.md` | `docs/adding-a-new-provider.md:8` | 写"已集成了**四个** LLM Provider"，实际 **6 个** | 中 |
| `docs/adding-a-new-provider.md` | `docs/adding-a-new-provider.md:10-13` | provider 表只列 3 个（buddy/workbuddy/lobsterai），缺 codearts/qoder/trae | 中 |
| `docs/adding-a-new-provider.md` | `docs/adding-a-new-provider.md:338-346` | **`LlmAdapter` 契约部分准确**：4 个必须方法 + `prepareCall` 建议实现，与代码一致 | ✅ 无问题 |
| `docs/adding-a-new-provider.md` | `docs/adding-a-new-provider.md:404` | 写 `registerConfigurableProviders` + `registerAdapter`，**与代码一致** | ✅ 无问题 |

**结论**：`LlmAdapter` 的方法契约以 `docs/adding-a-new-provider.md:338-346` 为准（准确）；但 **`ctx.llm` 的方法名以源码为准**（`AGENTS.md:152` 是错的）。

---

## 12. 参考来源

### 12.1 一手源码（宿主侧 `src/`）

| 文件 | 关键内容 |
|---|---|
| `src/index.ts` | 插件入口：`name`/`inject`/`apply`；settings namespace 注册；六个 provider 装配；续期调度；Jet Hub RPC 挂载 |
| `src/llm-adapter.ts` | `CodeArtsAdapter`；`registerCodeArtsLlm`；DSML 工具模式；限流判定工具 |
| `src/buddy-adapter.ts` | `BuddyAdapter`（服务 buddy + workbuddy）；`registerBuddyLlm` |
| `src/lobsterai-adapter.ts` | `LobsteraiAdapter`；`registerLobsteraiLlm` |
| `src/qoder-adapter.ts` | `QoderAdapter`；`registerQoderLlm` |
| `src/trae-adapter.ts` | `TraeAdapter`；`registerTraeLlm` |
| `src/jet-hub-rpc.ts` | Jet Hub 管理 RPC 端点注册与 16 个方法分派 |
| `src/account-pool.ts` | `AccountPool`；`jet-hub` settings namespace；模型黑名单 |
| `src/service.ts` | `CodeArtsAuth extends Service`；`ctx.credentials` 用法 |
| `src/openai-compat.ts` | 客户端侧 OpenAI 协议层（**不是**服务端） |
| `src/login.ts` / `src/lobsterai-oauth.ts` / `src/trae-oauth.ts` | 三处本地 OAuth 回调服务器 |
| `src/models.ts` | CodeArts 远端模型目录拉取 |

### 12.2 一手源码（客户端 `plugin-src/`）

| 文件 | 关键内容 |
|---|---|
| `plugin-src/client/index.js` | 客户端插件入口；`settings.section` slot 注册 |
| `plugin-src/client/jet-hub.js` | `JetHubPage` React 页面 |
| `plugin-src/client/build.mjs` | esbuild 打包 + `window.__ModuleLoader__` 包装 |
| `plugin-src/management-rpc.mjs` | `connection.rpc.call('/api', 'jet-hub', ...)` |
| `plugin-src/client/credits-capabilities.js` | 积分能力矩阵 |
| `plugin-src/client/account-order.js` | 拖拽排序纯逻辑 |
| `plugin-src/client/jet-hub-styles.js` | CSS 注入 |

### 12.3 配置与契约

| 文件 | 关键内容 |
|---|---|
| `package.json` | `dsh.bundle.patch`；`dsh.client.platform`；`exports["./client"]`；peerDependencies；无 `bin` |
| `cordis.patch.yml` | bundle 补丁：向空配置根 insert 插件行 |
| `tsconfig.json` | 宿主侧编译配置（`src/` → `lib/`） |
| `pnpm-workspace.yaml` | 作为 DSH 插件安装（allowBuilds） |

### 12.4 测试（可运行的契约证据）

| 文件 | 关键内容 |
|---|---|
| `tests/unit/plugin.spec.ts` | 宿主服务替身（`FakeCredentials`/`FakeCommands`/`FakeLlm`/`FakeSettings`）；`new Context()` 真实构造；`ctx.fiber.dispose()` 生命周期；`inject` 不含 `connection` 的回归测试；settingsNs 一致性测试 |

### 12.5 文档

| 文件 | 关键内容 | 可信度 |
|---|---|---|
| `docs/adding-a-new-provider.md` | `LlmAdapter` 4 个必须方法 + `prepareCall`；注册流程 | 契约部分可信，provider 计数过期 |
| `docs/lobsterai-integration-plan.md` | §0.3「不需要跑那个反代」（`docs/lobsterai-integration-plan.md:131-148`）—— 形态定性的一手依据 | 高 |
| `AGENTS.md` | 项目结构；DSH 插件契约（`AGENTS.md:117-123`，**部分失真**）；本地回调服务器崩溃宿主（`AGENTS.md:863-896`） | 需交叉核对 |
| `README.md` | 安装/构建；bundle patch 拾取机制（`README.md:73-75`）；provider 说明 | 高 |

---

## 附录 A · 行号校验记录

本文所有 `文件:行号` 引用已通过脚本校验（脚本位于 `/tmp/verify_lines.mjs`，**未写入参考仓**）。

校验方式：对每个 `(文件, 行号, 期望子串)` 三元组，读取该文件第 N 行，断言包含期望子串。

```
$ node /tmp/verify_lines.mjs
ALL 139 OK
```

覆盖：`package.json`(6) · `cordis.patch.yml`(2) · `src/index.ts`(14) · `src/llm-adapter.ts`(16) · `src/buddy-adapter.ts`(10) · `src/lobsterai-adapter.ts`(8) · `src/qoder-adapter.ts`(8) · `src/trae-adapter.ts`(8) · `src/jet-hub-rpc.ts`(11) · `src/account-pool.ts`(5) · `src/service.ts`(3) · `src/login.ts`(5) · `src/lobsterai-oauth.ts`(3) · `src/trae-oauth.ts`(2) · `src/openai-compat.ts`(2) · `src/models.ts`(2) · `plugin-src/*`(13) · `tests/unit/plugin.spec.ts`(7) · `AGENTS.md`(4) · `README.md`(4) · `docs/*`(4)

**参考仓状态确认**：

```
$ git status
On branch master
Your branch is up to date with 'origin/master'.
nothing to commit, working tree clean
$ git rev-parse HEAD
397972908855bc458ef240d39ed24c1922a3a751      ← 原基线（2026-09-22 调研时）
```

> ⚠️ **上述输出是调研当时的快照，现已失效。** 2026-09-22 晚发现参考仓库被**重建**：
> 现行 HEAD = `d4613614f15884d1c7cd087e73a2aee6b17f2c0c`，且 `3979729` **不再是 HEAD 的祖先**。
> **本文行号已按新基线重锚**（详见文首「行号基线漂移声明」）。
> **注意 `git status` 干净只证明"未写入"，不能证明"基线未变"** —— 必须比对 `git rev-parse HEAD`。

调研全程只读，未对参考仓做任何写入 / 修改 / 格式化 / 重命名 / 移动操作。

---

## 附录 B · 给 Model-Gateway 的三条落地建议（基于本文结论）

1. **不要指望"复用 DSH 插件的推理端点"** —— 它不存在。§1.2 反证 A 与 §8.4 证据 2 已证明：推理是进程内函数调用，不经过任何 HTTP 边界。

2. **要复用的是"协议知识"，落地方式应是移植而非代理** —— 这与仓库自身的判断一致（`docs/lobsterai-integration-plan.md:140-141`）：把厂商协议翻译代码移植到网关，而不是把 DSH 插件当上游跑起来。网关需要自己的 `/v1/chat/completions` 层，这一层在 DSH 侧由 `ctx.llm.registerAdapter` 充当，在网关侧必须自建。

3. **账号池与限流切换逻辑值得单独抽象** —— 插件在 `AccountPool`（`src/account-pool.ts:124`）+ 适配器限流分支（`src/llm-adapter.ts:1457-1537` 的 `isRateLimited` / `parseRateLimitError`）里沉淀了"多账号 + 限流识别 + 重置时间解析"的完整实现，且带真实缺陷教训（中英文文案都要列全、结构化业务码优先于文案匹配）。这部分与"进程内 vs 进程外"无关，可直接参考。
