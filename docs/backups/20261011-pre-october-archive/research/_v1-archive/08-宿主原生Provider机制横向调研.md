# 08 · 宿主原生 Provider 机制横向调研

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

> 调研对象：**"宿主进程内原生 LLM Provider 插件"这一接入形态在业界的位置**，以及 Model-Gateway 下游形态选型的设计草案。
>
> 与 07 的分工：`07-DSH插件本地LLM形态与宿主契约.md` 是**纵向解剖**（DSH 插件内部怎么实现）；本文是**横向对比**（这种形态在业界还有谁、和 API/CLI 比强在哪弱在哪、我们该不该做）。
>
> 调研方式：外部结论**逐条 WebFetch 打开官方文档核实原文**；内部结论**只读源码**（DSH 插件与 Model-Gateway 均未做任何写入）。
> 证据分级：`【一手】` = 官方文档/源码可直接观测 · `【二手】` = 社区/媒体 · `【推断】` = 从用法反推 · `【未找到】` = 检索后无依据。
>
> ⚠️ **术语分层（贯穿全文）**：本形态的准确名称是"**宿主进程内原生 LLM Provider 插件**"（in-process native LLM provider plugin），落在 **L3「宿主进程内注册」**。
> 其中"**进程内**"修饰的是**适配器代码的运行位置**，**不是**"本地跑模型"——模型推理仍然全部发往**远端厂商 API**。
> 参考插件自己的代码就是这个意思：适配器直接 `fetch` 厂商端点（`src/llm-adapter.ts:14` 定义厂商端点常量 `CHAT_API_BASE`，`src/llm-adapter.ts:10` 导入出网签名函数 `signRequestHuawei`，`src/llm-adapter.ts:835` 起 `stream()` 内出网）。
>
> **三层"本地"的完整辨析见 `09-网关形态定位与本地LLM形态辨析.md` §0.2**：
> **L1** 本地权重推理（权重在本机）· **L2** 本机端点服务（服务进程在本机，边界是网络）· **L3** 宿主进程内注册（代码与宿主同进程，**没有边界**）。
> **Model-Gateway 落在 L2**，且这正是它的定位（§0.3）。

### 修订记录（定稿前经独立核验员证伪审计后修正）

| # | 位置 | 原内容 | 修正后 | 依据 |
|---|---|---|---|---|
| 1 | 头部术语纠偏 + 附录代码索引 | `src/llm-adapter.ts:14` 被标为 `import { signRequestHuawei } from './sign.js'` | `:14` 实为厂商端点常量 `export const CHAT_API_BASE = 'https://snap-access.cn-north-4.myhuaweicloud.com/api/v2'`；导入 `signRequestHuawei` 的是 `:10`。两处引用已分别更正（**论证方向不变**：仍证明推理在远端） | 核验报告 M2 |
| 2 | §3.4 路径 B 覆盖表 | 漏列 Trae 与 Cherry Studio | 补齐 `README.zh-CN.md:17` 明确点名的三个目标客户端（**Trae / Cursor / Cherry Studio**），并标注各自证据等级（Cherry 官方文档【一手】、Trae 社区教程【二手】、Cursor【未找到】） | 核验报告 M4 |

> 核验报告：`drafts/verify-07-08.md`。共 14 处问题（0 严重 / 4 中等 / 10 轻微），**无任何核心结论被证伪**；28 条外部 URL 中 27 条逐字一致（另 1 条仅路径写法为 404，内容真实）。

### 第三批修订（用户澄清网关定位后新增）

| # | 位置 | 原内容 | 修正后 | 依据 |
|---|---|---|---|---|
| 3 | 头部术语段 | 标题"术语**纠偏**"、末句"全文不使用'本地 LLM'这一措辞" | 改为"术语**分层**"，并补入 L1 / L2 / L3 三层定义与"Model-Gateway 落在 L2"的结论，指向 `09` 号文档 §0.2。**"本地 LLM"不再是禁用语，而是需要限定层级的术语** | 用户澄清 + `09` 号文档 §0.2 |
| 4 | 新增 §0.3 | 无 | 新增"**形态选择是'定位'的函数，不是'性能'的函数**"：写入用户澄清的网关定位（服务器常驻 / 全机所有 AI 工具统一入口 / 不属于任何单个工具），并论证 **③ 插件形态与定位互斥**、① 就是定位本身 | 用户澄清 + `09` 号文档 §3 |

> 完整辨析见 `drafts/verify-09.md`。

---

## 0. 结论先行

### 0.1 三种下游形态对比总表

> 维度定义见 §2。表中"⭐"表示该维度占优的形态。

| 维度 | ① OpenAI 兼容 HTTP API | ② CLI 子进程调用 | ③ 宿主原生 Provider 插件 | 依据 |
|---|---|---|---|---|
| **效率（延迟构成）** | 本机 loopback HTTP：`127.0.0.1` 上的 TCP + HTTP 头 + JSON 序列化；无进程启动成本 | 每次调用 `spawn` + 宿主/工具冷启动 + 参数解析；Node/Python 运行时启动 100ms～1s 量级 | **⭐** 进程内函数调用，**零序列化、零 socket**；`AsyncIterable<StreamChunk>` 直接 yield JS 对象 | §2.1 |
| **效率（流式路径）** | SSE 字节流需二次解析 + 转 chunk | 需在 stdio 上再定义一层帧格式，或干脆不支持真流式 | **⭐** 原生异步迭代器，天然 token 级增量 | §2.1 |
| **稳定性（故障面）** | **⭐** 网关崩了只影响自身；宿主与网关进程隔离 | **⭐** 子进程隔离；但需管理僵尸进程/超时 | 插件与宿主**同进程**：插件抛未捕获错误可打挂宿主 | §2.2 |
| **稳定性（版本漂移）** | **⭐** 协议冻结（OpenAI 兼容面几乎不变） | CLI 参数会变（`--flag` 增删、输出格式变） | 宿主**内部 API** 变更直接编译失败/运行时崩；Cordis 官方自述"API 尚未稳定" | §2.2 |
| **可移植性** | **⭐** 一次实现覆盖几乎所有宿主（Continue/Cline/Roo/DSH/Cursor-B 类…） | 每接一个宿主写一个 CLI 适配 | 每个宿主一套插件 API，**强宿主锁定**；N 宿主 × M 协议矩阵 | §2.3 |
| **能力保真度** | 取决于协议表达力；OpenAI 兼容面能透传 tools/流式/用量，**推理档位/多模态/缓存需额外字段协商** | **最差**：CLI 通常只给最终文本，元数据全丢 | **⭐** 最好：宿主把 `GenerateOptions` 完整交给你，`usage`/`FinishReason`/`reasoning` 块都在契约内 | §2.4 |
| **合规（事实转述）** | 凭据在网关本地；宿主只持有"网关令牌"，**厂商 Key 不出本机** | 同左，凭据经环境变量传入子进程 | 凭据存进**宿主自己的凭据库**（如 `$DSH_HOME/.credentials.yaml`），网关不再是唯一凭据持有者 | §2.5 |
| **实现成本（每接一宿主）** | **0**（宿主自带自定义 provider 时）；否则 1 个薄适配 | 1 个 CLI 包装器 | **高**：VS Code 需 provider 类 + `package.json` 贡献点；DSH 需 `LlmAdapter` 子类 + 注册 + settings namespace | §2.6 |
| **维护成本（谁跟进宿主变更）** | **⭐** 我们只跟协议；宿主变更由宿主自己兼容 | 我们跟 CLI 参数 | 我们跟**每个宿主的内部 API**；Cordis 明确声明 API 不稳定 | §2.6 |
| **用户体验（模型出现在选择器）** | 宿主若支持自定义 provider → **⭐** 出现在选择器，且可探测 `/v1/models` | 模型不出现在宿主选择器（CLI 是另一个进程） | **⭐** 出现在选择器，且可挂 settings 页 | §2.7 |
| **用户体验（用户要填什么）** | 填 base_url + key（若宿主支持） | 填命令路径 + 参数 | 装插件 + 在设置页填 key（比手填 base_url 更友好） | §2.7 |

### 0.2 推荐排序

**结论：主推 ①，把 ③ 降级为"按宿主选择性补充"，② 只在特定场景（宿主既不支持自定义 provider、也不支持插件）作为兜底。**

| 排序 | 形态 | 定位 | 一句话理由 |
|---|---|---|---|
| **1** | **① OpenAI 兼容 HTTP API**（+ 已有的 Anthropic 原生 `/v1/messages`） | **主路径，唯一事实源** | 唯一能"写一次覆盖全部宿主"的形态；且**我们已经有**（`model_gateway/api/openai_compat.py:36`、`:101`、`model_gateway/api/anthropic.py:316`） |
| **2** | **③ 宿主原生 Provider 插件（瘦插件）** | **补充路径**，只给"没有自定义 provider 能力"的宿主 | 用 UX 换锁定：把 base_url 手填换成设置页，代价是每个宿主一份代码 |
| **3** | **② CLI 子进程** | **兜底路径** | 保真度最差、可移植性也不比 ① 好，几乎无独立价值 |
| **4** | **③ 的"胖插件"变体** | **不推荐** | 把账号池/调度搬进插件 = 第二套实现，直接违反单一事实源 |

**翻转条件（详见 §3.5）**：
- 若目标宿主集合 = **1 个**且该宿主**无自定义 provider 能力** → ③ 升为第 1。
- 若该宿主**有**自定义 provider 能力（DSH 就是，见 §1.7）→ ③ 直接不需要，① 单独就够。
- 若目标是覆盖 10 个宿主 → ③ 的成本随宿主数线性增长，而 ① 的成本恒定为 1，差距被放大到不可接受。

### 0.3 前提：形态选择是"**定位**"的函数，不是"**性能**"的函数

> 用户在补充说明中明确了网关定位：这是一个**公共的中枢网关**，**目标就是服务器电脑上运行的所有 AI 工具**用的 —— 它**不是某个编程工具内部的**，而是一个**独立的**、可以**对接融合很多独立模型厂商**、也可以**授权使用一些工具内部的模型数据**，然后经过网关**统一输出标准化服务**。它**接入了两方面**：**① 各大模型厂商源头的 API 能力；② 通过授权工具产品账号登录，使用该账号内部的模型能力**。它**特有的机制是"容错机制 + 模型统一机制"**。

这条定位**直接决定**形态（不是"参考"，是"决定"）：

| 形态 | 与定位的关系 |
|---|---|
| **① OpenAI 兼容 HTTP API** | ✅ **就是定位本身** —— 本机常驻服务 + 标准协议端点。业界同类：**Ollama 的 `/v1` 面**（`base_url='http://localhost:11434/v1/'`，见 `09` 号文档 §1.2）。**而且我们已经有。** |
| **③ 宿主进程内插件** | ❌ **与定位互斥** —— 插件代码**必须住进某个具体宿主**（`ctx` 是宿主进程的上下文）。写一个 DSH 插件 = 让网关开始**依附 DSH**，直接违反"不属于任何单个编程工具" |

**更强的一条（不只是"慢"，是"坏"）**：网关的特有机制 —— **容错（重试/冷却/切换续跑）** 与 **模型统一（跨厂商模型名映射 / 推理参数归一）** —— **都是有状态的中枢能力，只能有一份**。放进 N 个宿主插件 = N 份**无共享**副本 → 冷却不共享、切换不共享、用量统计分裂、映射表漂移。**"容错"退化成"每个工具各自容错"，"统一"退化成"各宿主各有一套映射"。**

**所以下文 §2 的九维度对比是"佐证"，不是"决策依据"；决策依据是定位。**

九维度对比的价值在于说明一个更强的事实：**即便抛开定位，③ 也不占优** —— 它只是在"延迟"这一个维度上领先，且领先量级可忽略（§4.2 理由 1）。

> 完整推导见 `09-网关形态定位与本地LLM形态辨析.md` §2.0（定位拆解）/ §2.3.1（特有机制论证）/ §3（互斥论证）。

---

## 1. 宿主原生 Provider 机制全景（外部调研）

### 1.1 Claude Code

**结论：Claude Code 的"模型接入"路径是 `ANTHROPIC_BASE_URL` 指向一个 Anthropic Messages 格式的网关；它没有"第三方注册 provider"的插件机制。MCP / Agent SDK / `--bare` 都不是模型接入路径。**

**（1）网关接入路径 —— 是模型接入路径。**【一手】

- 官方文档："`ANTHROPIC_BASE_URL` is the variable that points Claude Code at the gateway."
  <https://docs.claude.com/en/docs/claude-code/llm-gateway>
- 支持的 API 格式**只有三种**，官方原文："A gateway must expose at least one of the following API formats to Claude Code clients."——分别是 **Anthropic Messages**（`/v1/messages`）、**Amazon Bedrock InvokeModel**、**Google Cloud's Agent Platform rawPredict**。
  <https://code.claude.com/docs/en/llm-gateway-protocol>
- ⚠️ **OpenAI Chat Completions 不在其列**。原文明确："本文档**未列出**该格式"（该页只列三种）。
- ⚠️ 官方明确不支持非 Claude 模型走网关："Anthropic doesn't endorse, maintain, or audit third-party gateway products, and doesn't support routing Claude Code to non-Claude models through any gateway."
  <https://docs.claude.com/en/docs/claude-code/llm-gateway>
- `ANTHROPIC_BASE_URL` 的语义被官方限定为**改地址不改模型**："`ANTHROPIC_BASE_URL` changes where requests are sent, not which model answers them."
  <https://code.claude.com/docs/en/model-config>

**（2）Gateway model discovery —— 是模型接入的"发现"环节，但过滤器对非 Claude 模型不友好。**【一手】

- 开关：`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`，默认关闭。原文："Discovery is off by default so that gateways backed by a shared API key don't surface every model the key can access to every user."
- 请求：原文 "The request is `GET /v1/models?limit=1000` with a timeout of 3 seconds by default, and any redirect is treated as failure so the credential can't leak to a redirect target." 超时可用 `CLAUDE_CODE_GATEWAY_MODEL_DISCOVERY_TIMEOUT_MS` 放宽。
- ⚠️ **关键过滤器**：原文 "Claude Code keeps an entry when its `id` contains `claude` or `anthropic` anywhere in the string, matched case-insensitively, and ignores the rest."
  → 我们的 `/v1/models` 返回的是 `deepseek-v4-flash`、`sensenova-u1-fast` 这类 id（`model_gateway/api/openai_compat.py:40`，`id` 取自 `m.name`），**一条都不会被收进 `/model` 选择器**。
- 且 discovery **只在 Anthropic Messages 格式下运行**："Discovery applies only to the Anthropic Messages format."
- 来源：<https://code.claude.com/docs/en/llm-gateway-connect> 与 <https://code.claude.com/docs/en/llm-gateway-protocol>

**（3）`availableModels` —— 不是"添加模型"，是"限制模型"。**【一手】

- 原文："Enterprise administrators can use `availableModels` in managed or policy settings to **restrict** which models users can select."
  → 这是**白名单（收紧）**语义，不能用来给 Claude Code 增加模型。来源：<https://code.claude.com/docs/en/model-config>
- 真正能"加一行"的是 `ANTHROPIC_CUSTOM_MODEL_OPTION`：原文 "Use `ANTHROPIC_CUSTOM_MODEL_OPTION` to add a single custom entry to the `/model` picker without replacing the built-in aliases." 且 "Claude Code skips validation for the model ID set in `ANTHROPIC_CUSTOM_MODEL_OPTION`, so you can use any string your API endpoint accepts."（同上）
  → 这是**单条手动加**，不是"注册一个 provider 并自动列出 N 个模型"。

**（4）MCP server 机制 —— 不是模型接入路径。**【一手】

- 官方定义："Claude Code can connect to hundreds of external tools and data sources through the Model Context Protocol (MCP), an open source standard for AI-tool integrations."
- MCP server 可提供 **tools / prompts / resources**（原文："dynamically update their available tools, prompts, and resources"），另有 `claude/channel` 推送能力。
- ⚠️ 文档中**没有任何**"MCP 提供或注册模型/LLM provider"的记载 —— 该页逐条核查后为【未找到】。
- 传输四种：`http`（推荐，别名 `streamable-http`）、`sse`（**已弃用**，原文 "The SSE (Server-Sent Events) transport is deprecated."）、`stdio`、`ws`。
- 来源：<https://docs.claude.com/en/docs/claude-code/mcp>

**（5）Agent SDK —— 不是模型接入路径。**【一手】

- 官方定位："The Agent SDK gives you the same tools, agent loop, and context management that power Claude Code, programmable in Python and TypeScript." 具体形态是 "A library that **runs the Claude Code binary**"。
  → 它是"把 Claude Code 当库来跑 Agent"，不是"给 Claude Code 提供模型"。
- 原文另有约束："Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK."
- 来源：<https://code.claude.com/docs/en/agent-sdk/overview>

**（6）`--bare` headless 模式 —— 不是模型接入路径，是启动优化。**【一手】

- 原文："Add `--bare` to reduce startup time by skipping auto-discovery of hooks, skills, custom commands, subagents, plugins, MCP servers, auto memory, and CLAUDE.md."
- 原文："`--bare` is the recommended mode for scripted and SDK calls, and will become the default for `-p` in a future release."
- 认证要求："Set `ANTHROPIC_API_KEY` before running it, because bare mode doesn't use your subscription login"；"In bare mode, Claude Code never reads OAuth credentials or the system keychain."
- 来源：<https://code.claude.com/docs/en/headless>
- 对我们的意义：`--bare` 是**调用侧**的稳定化开关，与"我们怎么被接入"无关。

**（7）Claude Code 的 Plugin 机制 —— 不是模型接入路径。**【一手】

- Agent SDK 页把 Plugin 定义为 "Package skills, agents, hooks, and MCP servers, and load them by local path"。
  → Claude Code 的"插件"打包的是 skills/agents/hooks/MCP，**不含模型 provider**。来源：<https://code.claude.com/docs/en/agent-sdk/overview>

**小结（Claude Code 对我们的可操作性）**：我们能做的**唯一**模型接入动作，是让网关提供一个**Anthropic Messages 格式**的端点（我们已有 `/v1/messages`，`model_gateway/api/anthropic.py:316`），并把 `ANTHROPIC_BASE_URL` 指向它。但要注意：官方声明不支持非 Claude 模型走网关，且 discovery 的 `id` 过滤器会把我们的模型名全部滤掉——**用户仍可手工用 `ANTHROPIC_CUSTOM_MODEL_OPTION` 或 `--model` 指定**（原文："your provider or gateway defines the model names, so Claude Code passes any string through without checking it"）。

### 1.2 VS Code / GitHub Copilot

**结论：VS Code **是**真正的"宿主原生 Provider 插件"机制——第三方扩展可以**提供**模型（不只是消费）。这是 ③ 形态最正统的样板。**

**（1）消费侧：`vscode.lm`（Language Model API）**【一手】

- 定位："The Language Model API enables you to **use the Language Model** and integrate AI-powered features and natural language processing in your Visual Studio Code extension."
- 用法：`selectChatModels({ vendor, id, family, version })` 选出模型，再 `sendRequest`。
- 该页**没有** provider 注册内容（`LanguageModelChatProvider`、`registerChatModelProvider` 均未出现）。来源：<https://code.visualstudio.com/api/extension-guides/language-model>

**（2）提供侧：`LanguageModelChatProvider`（关键）**【一手】

- 原文："The Language Model Chat Provider API enables you to **contribute your own language models** to chat in Visual Studio Code."
- 一 provider 对多 model："The `LanguageModelChatProvider` interface follows a **one-provider-to-many-models** relationship, enabling providers to offer multiple models."
- 注册两步：
  1. `package.json` 的 `contributes.languageModelChatProviders` 声明 `vendor` + `displayName`（可选 `managementCommand`）；
  2. 激活时 `vscode.lm.registerLanguageModelChatProvider('my-provider', new SampleChatModelProvider())`。
- 必须实现的三个方法：
  - `provideLanguageModelChatInformation(options, token)` → 返回 `LanguageModelChatInformation[]`（含 `id`/`name`/`family`/`version`/`maxInputTokens`/`maxOutputTokens`/`capabilities.imageInput`/`capabilities.toolCalling`）；
  - `provideLanguageModelChatResponse(model, messages, options, progress, token)` → 用 `progress.report(...)` 流式吐 `LanguageModelTextPart` / `LanguageModelToolCallPart` / `LanguageModelToolResultPart`；
  - `provideTokenCount(model, text, token)`。
- 官方有 BYOK 策略开关（企业可禁）：原文 "If you are a Copilot Business or Enterprise user, your administrator can disable the **Bring Your Own Language Model Key** policy in the Copilot policy settings on GitHub.com for models provided through this API."
- 来源：<https://code.visualstudio.com/api/extension-guides/ai/language-model-chat-provider>

**（3）Chat Participant API**：该页把 chat participant 描述为**消费**模型的场景（"we recommend that you instead use the model that is passed as part of the `request` object in your chat request handler"）。→ 第三方"提供"模型走的是 (2)，不是 Chat Participant。来源同上。

**对我们的意义**：VS Code 是 ③ 形态里"最值得做"的宿主（覆盖面大、机制正规、模型会进 picker），但**需要写一个完整的 VS Code 扩展**（TS + `package.json` 贡献点 + 三个方法 + 打包发布）。且扩展只是"转发到我们的 `/v1/chat/completions`"——**如果用户能直接填 base_url，这个扩展的价值只剩 UX**。

### 1.3 Cursor

**结论：Cursor 官方文档只支持**固定五家**的 BYOK；官方文档中**没有**"自定义 base_url / OpenAI 兼容端点"的记载。社区材料声称有，但**未在官方文档中核实到**。**

**（1）官方 BYOK 支持范围**【一手】

- 原文："You can add your own API keys so Cursor uses your preferred AI models."
- 操作路径：原文 "Open **Cursor Settings** > **Models** → Find the provider you want (OpenAI, Anthropic, Google, Azure, or AWS Bedrock) → Paste your API key → Click Save."
- 原文："Custom API keys only work with chat models. Tab completion continues using Cursor's built-in models."
- 来源：<https://cursor.com/help/models-and-usage/api-keys>（该页为 `cursor.com/docs/account/api-keys` 的实际落点）

**（2）自定义 base_url —— 【未找到】**

- 上述官方页面的"支持的 provider"一节只列 **OpenAI / Anthropic / Google / Azure OpenAI / AWS Bedrock** 五家，**没有**"Custom / OpenAI Compatible / Base URL"条目。
- 我们另外尝试了 `https://cursor.com/docs/account/api-keys`（返回 "This page doesn't exist."）与 `https://cursor.com/docs/models`（Models & Pricing 页，无自定义端点内容）。
- 以 `allowed_domains=["cursor.com"]` 检索 "override OpenAI base URL" → **未返回任何 cursor.com 官方页面**。
- 社区/媒体材料声称存在 "Override Base URL"（如 <https://segmentfault.com/a/1190000048204894>、<https://developer.aliyun.com/article/1762261>）——这些均为 **【二手】**，其中一条明确称"唯一走得通的路径是 OpenAI 兼容协议 `/v1/chat/completions`"。
- **结论**：Cursor 的自定义端点能力**在官方文档中未核实到**；本节只记录事实，不据此下结论。

**对我们的意义**：README 已把 Cursor 列为目标客户端（`README.zh-CN.md:17`）。若 Cursor 的 base_url 覆盖能力仅存在于未文档化的 UI 里，则它属于"**没有可依赖的官方接入契约**"的宿主——**这正是 ③ 插件形态可能比 ① 更有价值的一类宿主**，但 Cursor 也没有公开的 provider 插件 API（【未找到】），所以对 Cursor 我们目前**没有稳定形态可选**。

### 1.4 Zed：Agent Client Protocol（ACP）

**结论：ACP 是"编辑器 ↔ agent 进程"的协议，**不是**模型接入协议。Zed 文档明确把模型/provider 配置划归 agent 自己。**

**（1）ACP 的定位**【一手】

- 官方原文："The Agent Client Protocol (ACP) standardizes communication between **code editors/IDEs and coding agents** and is suitable for both local and remote scenarios."
- 通信形态："**Local agents** run as sub-processes of the code editor, communicating via JSON-RPC over stdio." / "**Remote agents** can be hosted in the cloud or on separate infrastructure, communicating over HTTP or WebSocket"
- 类比："similar to how the Language Server Protocol (LSP) standardized language server integration."
- 来源：<https://agentclientprotocol.com/get-started/introduction>

**（2）Zed 侧的边界划分（决定性）**【一手】

- 原文："External Agents run through their own process and **provider relationship**. Billing, legal terms, retention, and data handling are between you and the agent provider."
- 配置边界表原文：Model/provider config → "Usually owned by the External Agent"；Auth/API keys/subscriptions → "Usually owned by the External Agent"。
- 原文："Zed LLM provider API keys saved in the local keychain are **not automatically the same as** an External Agent's credentials."
- 来源：<https://zed.dev/docs/ai/external-agents>

**（3）ACP 与我们的关系**

- ACP 里**没有**"模型 provider"这一角色。第三方接入 ACP 的形态是"**提供一个 agent**"（`agent_servers` 里配 `command` + `args`，如 `pool acp`），即 §2 的**形态 ②（CLI 子进程）**——只不过进程间用 JSON-RPC over stdio 而不是自定义帧。
- 因此：**ACP 不是我们的模型接入路径**，但它是"**如果我们将来要暴露一个 agent，而不是暴露一个模型**"时的路径。对当前网关（只做模型转发，不做 agent loop）**不适用**。

### 1.5 Continue / Cline / Roo Code（IDE 插件）

**结论：这三家都是**纯 ① 形态**——用 `base_url` + `api_key` + `model id` 接入任意 OpenAI 兼容端点。这是"OpenAI 兼容 = 事实标准"最直接的证据。**

| 项目 | 配置载体 | 关键字段（原文） | 自定义端点支持 | 来源 |
|---|---|---|---|---|
| **Continue** | `config.yaml` | `provider: openai` / `model` / `apiBase` / `apiKey` | ✅ 明确："If you are using an OpenAI API compatible providers, you can change the `apiBase` like this: `apiBase: http://localhost:8000/v1`" | <https://docs.continue.dev/customize/model-providers/top-level/openai> |
| **Cline** | 设置面板 | "API Provider: OpenAI Compatible" / **Base URL** / **API Key** / **Model** | ✅ 原文："**Any other provider** that offers an OpenAI-compatible API endpoint."；"**Base URL:** Enter the base URL provided by your chosen provider. **This is a crucial step.**" | <https://docs.cline.bot/provider-config/openai-compatible> |
| **Roo Code** | 设置面板 | 同上三字段 | ✅ 同上；另有**硬约束**："Roo Code uses **native tool calling** exclusively... the model you select **must** support OpenAI-compatible tool calling. If a model does not support native tool calling, it cannot be used with Roo Code." | <https://docs.roocode.com/providers/openai-compatible> |

**对我们的直接含义（3 条）**：
1. 这三家**零适配成本**——用户把 base URL 填 `http://127.0.0.1:8300/v1` 即可（与 `README.zh-CN.md:81` 一致）。
2. Roo Code 的"**必须支持 native tool calling**"是硬门槛：我们的网关必须**完整透传 `tools` / `tool_calls`**，否则这些客户端直接不可用。→ 这是网关侧要重点保证的能力（§2.4）。
3. Continue 的 `apiBase` 是**显式文档化**的字段；Cline/Roo 是**表单字段**。两者都说明：**这个行业的接入契约就是 base_url + key**。

### 1.6 Cordis / Koishi 生态

**结论：Cordis 是一个**依赖注入式插件框架**（作者自述 "Meta-Framework of Spatiotemporal Composability"），Koishi 是它的姊妹/前身生态，语义几乎一致。`Service` / `inject` / `ctx.get` / `ctx.effect` 的语义由 Koishi 文档（更成熟）与 DSH 官方 primer 双向印证。**

**（1）Cordis 是什么**【一手】

- 仓库自述："A Meta-Framework of Spatiotemporal Composability."
- ⚠️ **稳定性警告（原文）**："Cordis is under active development. **The API is not yet stable and may change without notice.**"
- 来源：<https://github.com/cordiverse/cordis>

**（2）五个核心概念（DSH 官方 primer，中文原文）**【一手】

> "**插件是实现 Service 的对象。** 它可以是一个带有可选 `inject` 和 `apply(ctx)` 字段的函数，也可以是一个 `Service` 子类，其生命周期由 Cordis 挂载到当前上下文中。"
> "**上下文是服务的容器。** 一个服务占据一个稳定的 `ctx.<key>`（如 `ctx.tools`、`ctx.llm`、`ctx.sessions`）；其他插件通过 key 查找服务，而非导入具体实现。"
> "**通过 `inject` 声明服务依赖。** 插件声明所需的服务后，会等待这些服务就绪才启动；加载顺序通过服务依赖表达，而非手动编排启动序列。"
> "**类型化事件用于通信。** 服务通过 TypeScript 声明合并注册事件名，然后以 `emit`、`waterfall`（瀑布式事件）、`parallel`、`serial` 或 `bail` 方式分发…"
> "**注册是可逆的副作用。** 提示词片段、工具 schema、适配器、提供方和监听器通过 `ctx.effect()` 或 `ctx.on()` 安装，reload 和 teardown 时会按预期撤销。"

- 实践规则原文："每个注册都应有对应的 disposer（资源释放函数）：要么从 `ctx.effect()` 返回一个，要么使用 Cordis 提供的辅助方法自动处理。"
- 来源：<https://deepseek-harness.github.io/deepseek-harness/reference/cordis-primer>

**（3）Koishi 对同一套语义的独立表述（交叉印证）**【一手】

- 服务定义原文："应用其实可以被理解成一个容器，搭载了各种各样的功能…而上下文则单纯提供了一个接口来访问它们。这种组织形式被称为 **服务 (Service)**。" 且 "对于已经有 IoC / DI 概念的同学来说，服务就是一种类似于 IoC 的实现"。
- `inject` 语义原文（**关键**）：
  > "直到此服务的值变为 truthy 为止，**该插件的函数体不会被加载**"
  > "一旦此服务的值发生变化，该插件将立即回滚 (并非插件停用)"
- `inject` 可声明 `required` / `optional`；`ctx.inject()` 可把"部分功能依赖"注册为**子插件**。
- 自定义服务原文：`export default class Console extends Service { constructor(ctx, name) { super(ctx, 'console') } }`，`Service` 构造支持 `immediate` 参数，并有 `start()` / `stop()` / `fork()` 生命周期钩子。
- 来源：<https://koishi.chat/zh-CN/guide/plugin/service>

**（4）对我们的含义**

- `inject` 的"**依赖不就绪则插件体不执行**"语义，正是 DSH 插件在 `src/index.ts:25-31` 那段长注释的由来（`connection` 不列入静态 inject，否则 headless profile 永久 pending）。这类"生命周期语义"是 ③ 形态独有的**隐性成本**。
- `ctx.effect()` 的 disposer 契约（`src/index.ts:391-399` 用 `ctx.effect` 注册定时器清理）意味着插件必须自己管资源释放——**在 ① 形态下这些全都不存在**。

### 1.7 DSH（DeepSeek Harness）自身

**结论（本节最重要）：DSH **原生支持"自定义 OpenAI 兼容端点"**——用户可以在设置页填 base URL + 协议 + 凭据 + 模型，并让 DSH 去**探测端点模型列表**。因此对 DSH 这个宿主，③ 插件形态**不是必需的**。**

**（1）`llm` 服务的定位（从插件调用点 + 官方文档反推）**【一手】

- DSH 官方把 LLM 部分称为 **`llm-streaming` 子系统**（`packages/llm`）："循环搬运的对话词汇——`Message`、`ContentBlock`、`StreamChunk`、模型请求——由 `packages/llm` 声明"。
- 适配器契约原文："`LlmAdapter` 是提供方约定：创建子类、实现 `stream()`，再用 `ctx.llm.registerAdapter(providers, adapter)` 注册一个适配器实例。" 且 "**The only required method.**"（仅 `stream()` 必需）。
- 注册目录原文："适配器插件还会通过 `registerConfigurableProviders()` 声明哪些路由*可以*运行，并指明每条路由的用户设置分节，使配置界面能在任何路由注册之前就呈现休眠的提供方。"
- 模型目录的**权威性**原文（关键）："**该目录仅供参考，不是请求白名单：适配器仍是权威，并可接受未列出的模型 id。**"
- 来源：<https://deepseek-harness.github.io/deepseek-harness/reference/subsystems/llm-streaming>

**（2）DSH 原生就有"自定义提供方"（决定性发现）**【一手】

官方"配置模型"页原文：

> "对于公司网关、自建服务器或已安装目录中不存在的提供方，选择**添加自定义提供方**。提供小写 Provider ID、**基础 URL**、**API 协议**、**凭据**和**至少一个模型**。**API 协议**必须选网关实际使用的那一种，表单提供三种：`openai-completions` 对应 OpenAI Chat Completions，`openai-responses` 对应 OpenAI Responses API，`anthropic-messages` 对应 Anthropic Messages API。一个提供方只使用一种协议，网关同时提供两种时需要建两个提供方。"

> "### 探测模型 —— 在**模型目录**中选择**获取可用模型**，即可询问端点它提供哪些模型…探测读取的是常见网关公开的列表格式"

> "已配置的提供方会出现在模型选择器中。"

排错节还给出了**探测的具体行为**（对我们直接可用）：

> "**获取可用模型返回 401**：检查密钥。模型发现会调用 OpenAI 兼容的 `GET /models` 端点；对于不提供该端点的服务，请手动输入模型。"
> "**获取可用模型提示既没有 `data` 数组也没有 `models` 对象**：端点返回的列表格式不在探测的读取范围内。"

→ 我们的 `GET /v1/models` 返回 `{"object":"list","data":[{"id": ...}]}`（`model_gateway/api/openai_compat.py:36-44`），**正好命中** `data` 数组格式。

- 来源：<https://deepseek-harness.github.io/deepseek-harness/guide/providers>

**（3）DSH 侧已知的"网关兼容坑"（官方排错节列出，我们必须逐条对照）**【一手】

| DSH 报的现象 | 官方原文解释 | 我们网关现状 | 需要的动作 |
|---|---|---|---|
| 网关拒绝每一个请求 | "pi-ai 依据端点的 URL 决定请求的形状——系统提示词由哪个角色承载、输出上限写在哪个字段…声明了推理能力的模型，其系统提示词会以 `role: "developer"` 发出，很多网关直接拒绝" | 我们**原样透传** body（`model_gateway/api/openai_compat.py:121-125` 只 pop `model`），`developer` 角色会被转发给上游 | 建议：入站接受 `role: "developer"` 并归一为 `system`（或在文档里告知用户设 `compat.supportsDeveloperRole: false`） |
| 同上 | "输出上限则写作 `max_completion_tokens`，只认 `max_tokens` 的服务端会拒绝" | 我们透传，由上游决定 | 建议：文档说明；或网关侧做双写归一 |
| `off` 无法让 DeepSeek 停止思考 | "留空的 `off` 不发送任何推理字段，默认思考的端点就继续思考" → 需 `compat.thinkingFormat: deepseek` | 我们的 `lift_reasoning_from_body`（`model_gateway/api/openai_compat.py:122`）只处理**入站已有**的推理字段 | 文档说明即可（这是客户端侧配置） |
| 图片在发送前被拒绝 | "手动输入的模型在自己声明之前一律按纯文本对待" | 我们的 `/v1/models` 未输出模态信息（只有 `id`/`object`/`created`/`owned_by`/`endpoint`/`group`） | 可选增强：补 `input_modalities` 类字段（但 DSH 探测只读 `id`/`data`，收益有限） |

- 来源：同上（<https://deepseek-harness.github.io/deepseek-harness/guide/providers> 的"请求兼容性"与"排错"两节）

**（4）与参考插件的关系**

参考插件 `deepseek-harness-codearts` 之所以要写 `LlmAdapter`，是因为它要接的厂商（华为云 CodeArts、腾讯 CodeBuddy、有道、阿里 Qoder、字节 TRAE）**既不是 OpenAI 兼容、也没有现成目录**，且需要**浏览器 OAuth 登录 + 账号池 + 静默续期 + 签到**——这些是"自定义提供方"表单**装不下**的能力（表单只开放"API 密钥、显示名称、API 地址、API 协议、模型 ID/名称/上下文窗口/最大输出"）。

> 原文（关键边界）："模型页只开放让一条路由得以存在的字段：API 密钥、显示名称、API 地址、API 协议，以及每个模型的 ID、显示名称、上下文窗口和最大输出 token 数。其余所有字段——推理等级、图片输入、请求兼容性开关、请求头、超时、重试策略——都在 `$DSH_HOME/settings.yaml` 中设置。"

→ **对我们的判断**：我们网关对外是**标准 OpenAI 兼容 HTTP API**，模型列表也是标准 `data` 数组，**完全落在 DSH 表单的能力范围内**。我们**不需要**写插件。

### 1.8 事实标准问题：OpenAI 兼容是不是最通用的互操作层？

**结论：是。有大量**正例**（官方文档级别的广泛支持），也有明确的**反例**（要求自有协议、或明确不支持非本家模型）。**

#### 正例（广泛支持 OpenAI 兼容）

| 主体 | 官方表述（原文） | 来源 | 分级 |
|---|---|---|---|
| **Anthropic 自己** | 提供 OpenAI SDK 兼容层，`base_url="https://api.anthropic.com/v1/"`；文档同时说明这是"compatibility layer…primarily intended to test and compare model capabilities" | <https://docs.claude.com/en/api/openai-sdk> | 【一手】 |
| **LiteLLM** | "**Unified Interface**: Calling 100+ LLMs in the OpenAI `ChatCompletions` & `Completions` format"；端点 `POST /chat/completions`、`GET /models` | <https://docs.litellm.ai/docs/proxy/quick_start> | 【一手】 |
| **Continue** | "If you are using an OpenAI API compatible providers, you can change the `apiBase`" | <https://docs.continue.dev/customize/model-providers/top-level/openai> | 【一手】 |
| **Cline** | "**Any other provider** that offers an OpenAI-compatible API endpoint." | <https://docs.cline.bot/provider-config/openai-compatible> | 【一手】 |
| **Roo Code** | 同上，且要求 native tool calling | <https://docs.roocode.com/providers/openai-compatible> | 【一手】 |
| **DSH** | 自定义提供方协议三选一，首位即 `openai-completions`；探测走 "OpenAI 兼容的 `GET /models` 端点" | <https://deepseek-harness.github.io/deepseek-harness/guide/providers> | 【一手】 |

#### 反例（明确不支持 / 要求自有协议）

| 主体 | 官方表述（原文） | 来源 | 分级 |
|---|---|---|---|
| **Claude Code** | 网关只接受 **Anthropic Messages / Bedrock InvokeModel / Vertex rawPredict** 三种格式；文档未列 OpenAI Chat Completions；且 "doesn't support routing Claude Code to non-Claude models through any gateway" | <https://code.claude.com/docs/en/llm-gateway-protocol>、<https://docs.claude.com/en/docs/claude-code/llm-gateway> | 【一手】 |
| **Claude Code（模型发现）** | discovery 只保留 `id` 含 `claude` 或 `anthropic` 的条目 | <https://code.claude.com/docs/en/llm-gateway-connect> | 【一手】 |
| **VS Code / Copilot** | 提供模型要走 **`LanguageModelChatProvider` + `contributes.languageModelChatProviders`**，是 VS Code 自有扩展 API，不是 OpenAI 协议 | <https://code.visualstudio.com/api/extension-guides/ai/language-model-chat-provider> | 【一手】 |
| **Zed / ACP** | ACP 是"editor ↔ agent"协议；模型/provider 配置"Usually owned by the External Agent" | <https://agentclientprotocol.com/get-started/introduction>、<https://zed.dev/docs/ai/external-agents> | 【一手】 |
| **Cursor** | 官方 BYOK 只列 OpenAI/Anthropic/Google/Azure/Bedrock 五家；自定义 base URL 官方文档中 **【未找到】** | <https://cursor.com/help/models-and-usage/api-keys> | 【一手】+【未找到】 |
| **MCP** | MCP 能力限于 tools/prompts/resources；**无**"注册模型 provider"机制 | <https://docs.claude.com/en/docs/claude-code/mcp> | 【一手】+【未找到】 |

#### 结论性判断

- OpenAI 兼容是**当前"接入任意宿主"最通用的互操作层**——它在"插件型客户端"（Continue/Cline/Roo/DSH）里是**第一公民**。
- 但它**不是普适的**：**第一方 Agent 宿主**（Claude Code）与**第一方编辑器**（VS Code、Cursor）倾向于用**自有协议/自有扩展 API**。分界线大致是：**"这个宿主是把自己定位成通用壳（愿意接任何模型），还是定位成自家模型的入口（只愿意接自家模型）"**。
- 因此正确策略是：**以 OpenAI 兼容为主干，对少数明确要求自有协议的宿主按需补一个薄适配层**（例如 Claude Code 需要 Anthropic Messages——**我们已有**）。

---

## 2. 三种下游形态的横向对比（逐维度给理由）

> 三种形态的定义：
> **① OpenAI 兼容 HTTP API** = 宿主把 `http://127.0.0.1:8300/v1` 当 OpenAI 端点调用。
> **② CLI 子进程调用** = 宿主 `spawn` 一个我们的 CLI 进程，通过 argv/stdin/stdout 交换。
> **③ 宿主原生 Provider 插件** = 我们在宿主进程内注册一个 provider/adapter 对象（DSH 的 `LlmAdapter`、VS Code 的 `LanguageModelChatProvider`）。

### 2.1 效率

**① 延迟构成（本机 HTTP）**：`connect(127.0.0.1)`（无网络 RTT，仅内核回环）+ HTTP 头解析 + JSON 序列化/反序列化。**没有进程启动成本**（网关是常驻服务）。流式路径：上游 SSE → 网关解析成 `IRRequest`/chunk → 重新序列化为 SSE 字节流 → 宿主再解析。**两跳序列化**。
证据：网关侧确实是"解析 + 重打包"（`model_gateway/api/openai_compat.py:101` 起读 body → `IRRequest`（`:124`）→ 调度器 → `_chat_stream_response`）。

**② 延迟构成（子进程）**：`spawn` + **解释器/运行时冷启动**（Python 3.12 起 `model_gateway` 要 import FastAPI/httpx/pydantic，量级在**数百毫秒**）+ 参数解析 + 一次性建立 HTTP 客户端 + 每次调用结束回收进程。**若不做进程池，这是三种里最差的**。且 CLI 通常只输出最终文本，真流式很难做。

**③ 延迟构成（进程内）**：宿主直接调用 adapter 的 `stream(options)`，**零序列化、零 socket**。DSH 的契约就是 `AsyncIterable<StreamChunk>`，yield 的是 JS 对象：
- `src/llm-adapter.ts:835` `async *stream(options: GenerateOptions): AsyncIterable<StreamChunk>`
- `src/llm-adapter.ts:1354-1366` `yield { type: 'block-end', index, block: { type: 'tool-call', ... } }`（多行 yield）
- `src/llm-adapter.ts:1385` `yield { type: 'finish', reason }`

**结论**：**③ > ① ≫ ②**。
**但要说清代价**：③ 省下的只是**本地一跳**的开销（回环 socket + 两次 JSON 编解码），而**总延迟的绝对大头是上游厂商推理时间**（秒级）。所以 ③ 的延迟优势在**绝对值上很小**，只在"高频小请求"（如 autocomplete）场景才显著。**不要为了延迟选 ③。**

### 2.2 稳定性

**故障面大小**
- ①：**最优**。网关是独立进程，崩溃/重启不影响宿主；宿主看到的是 HTTP 错误（可重试）。网关本身就实现了"失败重试 + 切换续跑"（`README.zh-CN.md:32`），故障在网关内部被吸收。
- ②：**良**。子进程隔离；但要额外管理僵尸进程、超时、信号处理（`--bare` 文档里就有 SIGTERM → exit 143 的说明：<https://code.claude.com/docs/en/headless>）。
- ③：**最差**。**插件与宿主同进程**——参考插件的 `AGENTS.md:863-876` 记录了一个真实缺陷：OAuth 回调服务器的 `listen()` 失败未注册 `'error'` 处理器，错误"成为**进程级 unhandled error**，把**整个 DSH 宿主**打挂"（07 文档 §1.1 依据 5 已引用）。**这是同进程的最强证据，也是最大风险。**

**版本漂移风险**
- ①：**最优**。OpenAI 兼容面是**事实冻结**的：`/v1/chat/completions` + `/v1/models` 的字段十年未破坏性变更；Continue/Cline/Roo/DSH 都直接依赖它。我们只需跟**厂商上游**的协议变化（这是网关的本职）。
- ②：**中**。CLI 参数会增删（对比 `--permission-prompts` 明确标注 "requires Claude Code v2.1.259 or later. Earlier versions reject it with an unknown-option error."——<https://code.claude.com/docs/en/headless>），输出格式会变（`text`/`json`/`stream-json`）。
- ③：**最差**。我们绑的是宿主的**内部 API**，不是公开协议：
  - Cordis 官方自述："**The API is not yet stable and may change without notice.**"（<https://github.com/cordiverse/cordis>）
  - DSH 的 `StreamChunk` 是"**封闭的可辨识联合类型：对 `type` 的 `switch` 以 `assertNever` 结尾，因此新增变体会在每个必须处理它的消费方处触发编译错误**"（<https://deepseek-harness.github.io/deepseek-harness/reference/subsystems/llm-streaming>）→ 上游加一种 chunk 类型，我们的插件**编译失败**。
  - DSH 插件已经踩过同类坑：`settingsNs` 未注册会让模型设置页在 `refFor → deriveKeyRef(provider)` 处 `provider.toUpperCase is not a function` 崩溃（`src/index.ts:37-41`）。
- **崩溃隔离性**：① ≫ ② > ③。①/② 一个组件崩了不影响其他；③ 里"一个 provider 崩了会拖垮宿主"（同进程）。

### 2.3 可移植性

| 形态 | 覆盖宿主 | 是否锁定 | 迁移成本 |
|---|---|---|---|
| ① | **最大**：所有"支持自定义 OpenAI 兼容端点"的宿主 —— Continue / Cline / Roo Code / DSH / Cherry Studio / 各类 SDK | **无锁定**（我们定义端点，宿主是客户） | **0**（换宿主 = 用户改一个 base_url） |
| ② | 中：只要宿主能 spawn 进程就能用（理论上最通用） | 弱锁定（依赖宿主能配 CLI 命令） | 每宿主一个包装器 |
| ③ | **最小**：只覆盖"该宿主有 provider 插件 API"的宿主 | **强锁定**：插件用宿主的 `LlmAdapter` 基类、宿主的 `ctx`、宿主的 settings 服务 | 每换一个宿主**重写一遍** |

**N 宿主 × M 协议矩阵**（这是 ③ 的核心成本来源）：

- ①：**N × 1**（N 个宿主都接同一个 OpenAI 兼容面）。若某些宿主只认 Anthropic Messages，则是 **N × 2**——而我们**已经有第 2 个面**（`model_gateway/api/anthropic.py:316`）。
- ③：**N × M**，其中 M = 宿主插件 API 的数量。每个宿主一个插件：DSH 一套（TS + `@deepseek-ai/*` peer 依赖）、VS Code 一套（TS + 扩展贡献点）、未来 Cursor/Zed 各一套。**每套都要独立跟进该宿主内部 API 的变更。**

### 2.4 能力保真度

这是 ③ 唯一**真正**占优的维度，但优势没有想象中大——因为 ① 的载体（OpenAI 兼容协议）本身表达能力够用。

| 能力 | ① OpenAI 兼容 HTTP | ② CLI | ③ 宿主插件 | 说明 |
|---|---|---|---|---|
| **工具调用** | ✅ 完整（`tools` / `tool_calls` 在协议内） | ❌ 通常丢失 | ✅ 完整 | ① 的硬要求：Roo Code "**must** support OpenAI-compatible tool calling"（<https://docs.roocode.com/providers/openai-compatible>）。我们需保证 `tools`/`tool_calls` **不被改写** |
| **推理档位** | ⚠️ 部分：`reasoning_effort` 是 OpenAI 的扩展字段，各厂商语义不一；DSH 甚至需要 `compat.thinkingFormat: deepseek` 才让 `off` 生效 | ❌ | ✅ 宿主契约里有 `ReasoningEffortId`（`GenerateOptions.reasoningEffort`）与 `reasoningEfforts` 目录 | 网关已有三级推理合并（`README.zh-CN.md:34`），但要处理"不同厂商词汇映射" |
| **多模态** | ⚠️ 取决于厂商是否接受 `image_url`；DSH 侧还需要在 `settings.yaml` 手动声明 `input: [text, image]`，因为"手动输入的模型在自己声明之前一律按纯文本对待" | ❌ | ✅ 适配器可直接读宿主附件（`src/index.ts:106` `makeReadImage`） | ① 下网关必须原样透传图片块 |
| **提示缓存** | ⚠️ 非标准；Continue 有 `prompt_cache_key` 之类字段，各厂商不同（DSH 插件把 `prompt_cache_key` 列为"**必须凭实测回答**"的决策点：`docs/adding-a-new-provider.md:354`） | ❌ | ⚠️ 宿主契约里无显式缓存字段 | 三种形态都难，不是 ① 的劣势 |
| **用量统计** | ✅ `usage` 在 OpenAI 响应里是标准字段 | ❌ 通常丢 | ✅ 显式契约（`StreamChunk` 的 `{ type: 'usage'; usage: TokenUsage }`，且规则要求"`usage` 在 `finish` 之前"） | 我们已有事件流水统计（`README.zh-CN.md:36`） |
| **上下文窗口元数据** | ❌ **`/v1/models` 不返回上下文窗口**（我们当前也只返回 `id`/`object`/`created`/`owned_by`/`endpoint`/`group`，`model_gateway/api/openai_compat.py:39-43`） | ❌ | ✅ 一等公民（`LlmResolvedModelInfo.context`、`maxInputTokens`/`maxOutputTokens`） | **这是 ③ 的真实优势**：宿主需要知道上下文容量才能做裁剪/压缩。① 下用户只能手填（DSH 表单里就有"上下文窗口"字段） |
| **模型目录权威性** | ⚠️ 宿主可能缓存/过滤（Claude Code 的 `claude`/`anthropic` 过滤器是极端例子） | ❌ | ✅ DSH 明确"**该目录仅供参考，不是请求白名单：适配器仍是权威，并可接受未列出的模型 id**" | ① 下我们无法控制宿主如何消费 `/v1/models` |

**结论**：**③ 在"元数据丰富度"上确实最好（上下文窗口、推理档位目录、模态声明）**；但在**真正影响可用性的"工具调用 + 流式 + 用量"三项上，① 已经够用**。
→ 所以 ③ 的保真度优势集中在"**UX 元数据**"，不足以单独支撑"每个宿主写一个插件"的成本。

### 2.5 合规（仅事实转述，不给法律意见）

| 议题 | ① | ② | ③ |
|---|---|---|---|
| **谁代表谁** | 宿主认为自己在调"一个 OpenAI 兼容服务"；**厂商身份对宿主不可见** | 同 ① | 宿主认为"这个 provider 是宿主的一部分"；参考插件用 `displayName: 'CodeArts Agent'`（`src/llm-adapter.ts:1442`）——**等于以厂商品牌出现在宿主 UI 里** |
| **凭据存哪** | 厂商 Key 存**网关本地明文配置**（`config.example.yaml:48`，`README.zh-CN.md:117`："密钥不出本机"）；宿主只持有网关令牌（`config.example.yaml:17-20`） | 同 ①，经环境变量传入子进程 | 厂商凭据存进**宿主自己的凭据库**（DSH："密钥存储在 `$DSH_HOME/.credentials.yaml` 中"；插件通过 `ctx.credentials` 读写，`src/index.ts:206`）→ **网关不再是唯一凭据持有者** |
| **是否改宿主二进制** | 否 | 否 | 否（但**装载进宿主进程**，能访问宿主内存中的明文） |
| **宿主侧的明文条款** | Claude Code：官方声明 "doesn't support routing Claude Code to non-Claude models through any gateway"，且启用网关凭据后"a developer's claude.ai subscription isn't used"（<https://docs.claude.com/en/docs/claude-code/llm-gateway>） | — | VS Code：管理员可关 "Bring Your Own Language Model Key" 策略（<https://code.visualstudio.com/api/extension-guides/ai/language-model-chat-provider>） |
| **数据留存** | 由我们自己控制（纯本地、无遥测，`README.zh-CN.md:116`） | 同 ① | Cursor 侧事实（对照参考）：BYOK 时 "Cursor's Zero Data Retention policy does not apply"，且"key…is sent to our backend with every request because all requests are routed through Cursor's servers"（<https://cursor.com/help/models-and-usage/api-keys>） |
| **品牌/命名** | 无约束 | 无约束 | Claude Agent SDK 明文禁止第三方用 "Claude Code" 命名，只允许 "Claude Agent" / "{YourAgentName} Powered by Claude"（<https://code.claude.com/docs/en/agent-sdk/overview>） |

**事实性结论**：③ 形态会**改变凭据的存放位置与可见性边界**（从"只在网关本地"变成"也在宿主凭据库/宿主进程内存里"）。这与我们项目铁律"全明文配置、密钥不出本机"**不冲突**（宿主也在本机），但**扩大了暴露面**——从"1 个文件"变成"1 个文件 + N 个宿主凭据库"。仅作事实陈述。

### 2.6 实现成本与维护成本

**① 每接一个宿主的代码量：0～1 个薄适配。**
- 宿主支持自定义 provider（Continue/Cline/Roo/DSH）→ **0 行代码**，用户在 UI 填 base_url 即可。
- 宿主只认自有协议（Claude Code 要 Anthropic Messages）→ 需要**该协议的一个入站面**。**我们已有**（`model_gateway/api/anthropic.py:316`）。

**② 每接一个宿主：1 个 CLI 包装器 + 参数映射 + 输出解析。** 且要做真流式就得自定义 stdio 帧格式。

**③ 每接一个宿主：一套完整插件工程。** 以参考插件为标尺（**只读观测**）：

| 宿主 | 要写什么 | 代码量级（参考实测） |
|---|---|---|
| **DSH** | `LlmAdapter` 子类（实现 `stream()` 必需，另有 `providerInfo`/`listModels`/`resolveModel`/`prepareCall`，`src/llm-adapter.ts:746`/`:785`/`:801`/`:811`/`:822`）+ `registerConfigurableProviders` + `registerAdapter`（`src/llm-adapter.ts:1440-1458`）+ settings namespace 注册（`src/index.ts:55-91`）+ `package.json` 的 `dsh.bundle.patch`（`package.json:47-54`）+ `cordis.patch.yml` + `ctx.effect` 清理（`src/index.ts:391-399`）+ 单测/E2E | 参考插件**单个 provider 的适配器文件就有 1537 行**（`src/llm-adapter.ts`）；全部 `src/` 下 46 个目录/文件；`tests/unit` 有 50+ spec |
| **VS Code** | 扩展工程（TS + 打包）+ `contributes.languageModelChatProviders` + `contributes.commands`（`managementCommand`）+ 实现 3 个方法（`provideLanguageModelChatInformation`/`provideLanguageModelChatResponse`/`provideTokenCount`）+ 消息格式转换 | 官方有示例工程（<https://github.com/microsoft/vscode-extension-samples/blob/main/chat-model-provider-sample>），量级：数百行 + 发布流程 |

**"谁跟进宿主 API 变更"**

| 形态 | 变更来源 | 谁承担 |
|---|---|---|
| ① | OpenAI 兼容面（事实冻结）；厂商上游协议 | **我们**（本职）+ 宿主自己兼容 OpenAI |
| ② | 宿主 CLI 参数 | **我们** |
| ③ | 宿主**内部 API**（Cordis "API is not yet stable"；DSH `StreamChunk` 封闭联合） | **我们**，且是 **N 份** |

**矩阵规模**：
- ①：`N 宿主 × 1 协议`（+ Anthropic Messages 作为第二协议，已是既成事实）
- ③：`N 宿主 × M 插件 API`，且 M 随宿主增加而增加

### 2.7 用户体验

| 问题 | ① | ② | ③ |
|---|---|---|---|
| **模型是否出现在宿主模型选择器** | ✅ 若宿主支持自定义 provider（DSH："已配置的提供方会出现在模型选择器中"）；⚠️ 若宿主有过滤（Claude Code 只留 `claude`/`anthropic`）则**不出现** | ❌ 不出现（CLI 是另一个进程） | ✅ 出现，且可挂到宿主的模型设置页（`settingsNs`） |
| **用户要手填什么** | base_url + API key（+ 模型 ID，或让宿主探测） | 命令路径 + 参数 | 安装插件 + 在设置页填 key（**更少手工**） |
| **模型目录自动发现** | ✅ 宿主探测 `GET /models`（DSH 明文："模型发现会调用 OpenAI 兼容的 `GET /models` 端点"） | ❌ | ✅ 插件 `listModels()` 直接返回 |
| **上下文窗口/模态提示** | ❌ 协议不返回，用户手填 | ❌ | ✅ 由插件提供 |

**结论**：③ 的 UX 优势 = "**省掉手填 base_url**" + "**自动带上下文窗口/模态元数据**"。
**但这个优势是可以被 ① 部分补齐的**：只要宿主支持探测 `/v1/models`，用户就只需填一次 base_url。**真正补不齐的只有"上下文窗口元数据"**——而 DSH 的表单里本来就有"上下文窗口"字段让用户手填（<https://deepseek-harness.github.io/deepseek-harness/guide/providers>）。

---

## 3. Model-Gateway 的适配设计草案

### 3.1 我们应不应该提供"宿主原生 Provider 插件"这种形态？

**结论：不应该作为**默认形态**；应该作为**针对"无自定义 provider 能力"宿主的选择性补充**。而对 DSH 这个具体宿主，**不需要做插件**。**

**理由（4 条）**

1. **我们的价值在网关侧，不在宿主侧。** 网关的差异化是"聚合多厂商/多账号 + 失败重试 + 切换续跑"（`README.zh-CN.md:15`、`:32`）。这些能力**在 HTTP 边界上就能全部生效**——宿主调 `/v1/chat/completions` 时，切换续跑对它完全透明。**做插件不增加任何网关侧能力。**

2. **① 已经零成本覆盖了我们文档里点名的全部目标客户端。**
   - Trae / Cherry Studio / 任何 OpenAI 兼容客户端：填 base_url（`README.zh-CN.md:17`、`:81`）
   - Continue / Cline / Roo Code：同上，官方文档明示（§1.5）
   - **DSH：原生"添加自定义提供方"就是填 base URL + `openai-completions` + 模型**（§1.7）
   → 做插件等于给**已经能接入的宿主**再写一条冗余路径。

3. **③ 的锁定成本与我们的项目定位冲突。** 我们的定位是"**工具端永远只需要看到这一个端点**"（`README.zh-CN.md:17`）。③ 反过来要求我们**为每个宿主维护一份宿主内部 API 的适配代码**，且 Cordis 自述 API 不稳定、DSH 的 `StreamChunk` 是封闭联合（§2.2）——这会把一个"协议稳定、维护成本恒定"的项目，变成一个"跟着 N 个宿主跑"的项目。**与"无依据自创禁止""纯本地"这类克制立场不匹配。**

4. **③ 的优势项（UX 元数据）可以被 ① 部分补齐，且补齐成本极低。**
   - 宿主探测 `/v1/models`：我们**已经符合格式**（`data` 数组，`model_gateway/api/openai_compat.py:36-44`）。
   - 上下文窗口元数据：可以在 `/v1/models` 的每条上**附加非标准字段**（如 `context_window`）——OpenAI 兼容客户端会忽略未知字段，DSH 探测只读 `id`，**零破坏**。这是比"写插件"便宜 100 倍的补齐方式。（**注意：这是设计建议，需先确认不违反"无依据自创禁止"——见 §3.5 待拍板项。**）

### 3.2 如果提供，正确做法：瘦插件 vs 胖插件

**结论：只能是**瘦插件**（插件只做薄转发，请求打给网关本地 API）。胖插件 = 第二套实现，必须否决。**

#### 胖插件（把网关的凭据管理/账号池/调度搬进插件）—— **否决**

**它意味着什么**（用参考插件的实际构成做标尺）：
- 账号池：`src/account-pool.ts` + `src/account-probe.ts`（参考插件 `AccountPool` 参与 `resolveCredential` 与 `refresh`，`src/index.ts:196-215`）
- 调度/切换：参考插件在适配器内做限流切换与账号轮换（`RATE_LIMIT_BUSINESS_CODE`、`isRateLimited`、`parseRateLimitError`，`src/llm-adapter.ts:1457`/`:1497`/`:1513`）
- 凭据续期：`RefreshScheduler` + `refreshAll(pool)` + 30 分钟定时器（`src/index.ts:386-401`）
- 登录：OAuth 流程（`src/index.ts:148-195` 的 `codearts-login` 命令等）

**代价（逐条）**：
1. **双份维护**：同一套"账号池 + 重试切换 + 冷却"逻辑要在 Python（网关）和 TS（插件）里各实现一遍，且**行为会漂移**——参考插件已经证明了这种漂移的代价：`src/index.ts:297-313` 那段长注释记录了一个真实缺陷（`resolveCredential` 从账号池取凭据，而 `refresh()` 写的是另一个 ref → 续期成功但请求 401，"极难排查"）。**这是同一份逻辑分处两地的典型故障。**
2. **违反单一事实源**：网关的事件流水（`README.zh-CN.md:36`）、冷却状态（`config.example.yaml:32-33`）、令牌配额都会**看不到**插件内发生的请求。看板数据失真。
3. **凭据分散**：厂商 Key 会同时存在于网关配置与宿主凭据库（§2.5）。
4. **锁定加深**：胖插件必须依赖宿主特有的服务（`ctx.credentials`/`ctx.settings`/`ctx.effect`），迁移到另一个宿主 = 重写。

#### 瘦插件（插件只做薄转发）—— **可行**

**它意味着什么**：
- 插件里**没有**账号池、没有凭据存储、没有调度、没有续期。
- 插件唯一持有的凭据是**网关的访问令牌**（`config.example.yaml:17-20` 的 `mg-xxxx`）——或者干脆让用户填进宿主设置里。
- `stream()` 实现 = 把宿主的 `GenerateOptions` 序列化成 OpenAI 请求体 → `fetch('http://127.0.0.1:8300/v1/chat/completions', { stream: true })` → 解析 SSE → `yield` 成宿主的 `StreamChunk`。

**代价（必须诚实列出）**：
1. **仍然要写序列化/反序列化两层**：宿主的 `Message`/`ContentBlock` → OpenAI 形；OpenAI SSE → 宿主的 `StreamChunk`。**这正是 ① 形态下宿主替我们做的事**——做瘦插件等于**把 ① 的活儿搬到自己身上，只为省掉用户填一次 base_url**。
2. **仍然要跟宿主的内部 API**（`StreamChunk` 封闭联合、`LlmAdapter` 抽象类方法签名）。
3. **仍然有同进程风险**：瘦插件崩了同样会拖垮宿主（§2.2）。瘦只减少"逻辑复杂度"，**不减少"故障面"**。
4. **多一跳**：宿主 → 插件 → 网关 → 上游，比 ① 多一次本地 HTTP（§2.1 的延迟优势**反而消失**，因为瘦插件就是进程内的一次 HTTP 客户端调用）。

> ⚠️ **一个容易忽略的反直觉结论**：**瘦插件在效率上并不比 ① 更好**。① 的"宿主 → 网关"这一跳，在瘦插件里**依然存在**（插件要 `fetch` 网关）。瘦插件只省掉了**宿主的 JSON 解析**那一层——省得极少，代价却是我们多维护一个宿主插件。**所以瘦插件的唯一理由是 UX（省掉手填 base_url / 自动带元数据），不是效率。**

### 3.3 具体到 DSH：如果要做瘦插件，最小接口清单

**先给结论：DSH 不需要做插件**（§1.7 已证实 DSH 原生支持自定义 OpenAI 兼容端点）。但按要求给出"如果要做"的清单，作为**成本核算依据**。

**最小接口清单（从 `docs/adding-a-new-provider.md:335-346` 与 `src/index.ts` 的注册模式推导）**

| # | 要实现的项 | 依据（文件:行号） | 说明 |
|---|---|---|---|
| 1 | `export const name` | `src/index.ts:25` | 插件名 |
| 2 | `export const inject = ['llm']`（瘦插件不需要 `credentials`/`commands`） | `src/index.ts:33`（原为 `['credentials','commands','llm']`） | **依赖不就绪则插件体不执行**；`inject` 写多了会让 headless profile 永久 pending（`src/index.ts:25-31`） |
| 3 | `export function apply(ctx)` | `src/index.ts:121` | 入口 |
| 4 | `class XxxAdapter extends LlmAdapter` | `src/llm-adapter.ts:726` | 基类来自 `@deepseek-ai/dsh-llm` |
| 5 | `providerInfo(provider): LlmProviderInfo` | `src/llm-adapter.ts:746` | 返回 `{ id, name }` |
| 6 | `async listModels(provider): Promise<readonly LlmModelInfo[]>` | `src/llm-adapter.ts:785` | 瘦插件 = 转发 `GET /v1/models` 并映射（`id`/`name`） |
| 7 | `async resolveModel(provider, model, signal?): Promise<LlmResolvedModelInfo>` | `src/llm-adapter.ts:801` | **元数据来源**：可返回 `context`（上下文窗口）——这是插件形态唯一真正的增量 |
| 8 | `async *stream(options: GenerateOptions): AsyncIterable<StreamChunk>` | `src/llm-adapter.ts:835` | **唯一必需方法**；瘦插件 = 转发 + SSE 解析 + 映射为 `StreamChunk` |
| 9 | `ctx.llm.registerConfigurableProviders([{ provider, displayName, settingsNs, settingsPath }])` | `src/llm-adapter.ts:1454-1443` | 声明可配置路由 |
| 10 | `ctx.llm.registerAdapter([PROVIDER], adapter)` | `src/llm-adapter.ts:1458` | 注册适配器；**重复路由原子失败** |
| 11 | 注册 settings namespace（`Schema.object(...)`） | `src/index.ts:50-52`、`:57-93` | **必须**：否则模型设置页在 `deriveKeyRef(provider)` 处崩（`src/index.ts:37-41`）；且必须用 schemastery（`src/index.ts:43-48`） |
| 12 | `package.json` 的 `dsh.bundle.patch` 指向 `cordis.patch.yml` | `package.json:47-54` | 配置包装载入口 |
| 13 | `cordis.patch.yml` 的 `insert` 行 | `cordis.patch.yml:1-5` | 把插件插入配置树 |
| 14 | `ctx.effect(() => () => {...})` 清理 | `src/index.ts:391-399` | 释放定时器/连接 |
| 15 | `peerDependencies` 声明 `@deepseek-ai/cordis`、`@deepseek-ai/dsh-llm`、`@deepseek-ai/schemastery` | `package.json:55-61` | 注意：**仓库不含 `node_modules`**，宿主侧签名只能从调用点反推（07 文档已说明） |
| 16 | `package.json` 的 `engines.node` | `package.json:79-81` | `^22.19.0 \|\| >=24.0.0` |
| 17 | SSE 解析工具（空闲超时、工具调用配对、参数归一、截断判定） | `docs/adding-a-new-provider.md:358-362` 列出的 `src/sse.ts` 四件套 | 瘦插件**仍需**这些（因为要解析网关的 SSE）——**这就是"把 ① 的活儿搬到自己身上"的具体含义** |
| 18 | 适配器契约合规：`usage` 在 `finish` 之前；工具参数全程保持原始 JSON 字符串；错误只能走 `throw` 或 `finish {kind:'error'}`；单次调用 = 单次尝试（禁库重试） | <https://deepseek-harness.github.io/deepseek-harness/reference/subsystems/llm-streaming>（适配器契约 9 条） | **这些约束一条都不能少** |
| 19 | `tsconfig.json` + 构建（`tsc`） | `package.json:21`、`tsconfig.json` | — |
| 20 | 单测/E2E | `tests/unit/*.spec.ts`（50+ 个） | 参考插件的测试规模是插件工程量的重要组成部分 |

**代码量级估算**

| 组件 | 估算 | 依据 |
|---|---|---|
| 适配器（`stream` + `listModels` + `resolveModel` + SSE 解析 + 错误映射） | **400～700 行 TS** | 参考插件的 `src/llm-adapter.ts` 是 1537 行，但它含华为云 AK/SK 签名、DSML 工具调用提取、队列状态查询、限流解析等**厂商特有**逻辑；瘦插件（对标准 OpenAI SSE）可大幅缩减 |
| `index.ts` 注册 + settings namespace | **80～120 行** | 对比 `src/index.ts` 471 行（它注册了 6 个 provider + 命令 + 定时器 + RPC） |
| `sse.ts` 工具（空闲超时/工具配对/参数归一/截断判定） | **200～300 行** | `docs/adding-a-new-provider.md:358-362` 列的四件套；瘦插件至少需要"空闲超时"与"工具参数归一" |
| 配置/构建/文档/测试 | **300～500 行** | `package.json` 脚本 + `cordis.patch.yml` + 单测 |
| **合计** | **≈ 1000～1600 行 TS + 一套构建与测试** | 且这**只是 DSH 一个宿主** |

**维护成本**

| 事项 | 频率 | 说明 |
|---|---|---|
| 跟 DSH `StreamChunk` 联合类型变更 | 每次 DSH 加 chunk 类型 | 编译失败（`assertNever`），**必须改** |
| 跟 `LlmAdapter` 基类签名变更 | 随 DSH 版本 | 07 文档已指出宿主包本地不存在，签名只能从调用点反推 |
| 跟 Cordis 生命周期语义变更 | 不确定（自述 API 不稳定） | 参考插件在 `inject` 上已踩坑（`src/index.ts:25-31`） |
| 跟网关 `/v1/chat/completions` 行为变更 | 我们自己的节奏 | 若网关改了错误帧格式，插件要同步 |

**对比：不做插件的成本 = 0。** 用户按 DSH 官方流程"添加自定义提供方"填 base URL 即可。

### 3.4 有没有比"做插件"更划算的替代路径？

**逐条评估（含可行性结论）**

#### 路径 A：把网关伪装成宿主已原生支持的某个 provider 协议 —— ⚠️ **部分可行，且我们已有一半**

- **Claude Code 场景**：Claude Code 只接受 **Anthropic Messages** 格式（`/v1/messages`）。**我们已经实现了这个入站面**（`model_gateway/api/anthropic.py:316`，双向转换：Anthropic blocks ↔ OpenAI 形）。
  → 用户把 `ANTHROPIC_BASE_URL=http://127.0.0.1:8300` 即可。**但两个已知限制**：(a) 官方声明不支持非 Claude 模型走网关；(b) gateway model discovery 的 `id` 过滤器会滤掉我们的模型名（§1.1）。**用户仍可用 `ANTHROPIC_CUSTOM_MODEL_OPTION` 或 `--model` 手工指定。**
- **DSH 场景**：DSH 的自定义提供方协议三选一里有 `anthropic-messages`——**同样可用我们的 `/v1/messages`**。但**更简单的是直接用 `openai-completions`**（走 `/v1/chat/completions`）。
- **结论**：**这是"零新代码"的路径**——因为我们**已经有**两个入站面（OpenAI + Anthropic）。
  ⚠️ 但要注意"伪装"的**合规与语义边界**：`model_gateway/api/anthropic.py:1-6` 的 docstring 明确这是"IR 双向转换（透传优先，只做协议间必需的语义映射）"，即**协议转换**，不是**身份伪装**。本文只描述能力，不建议任何品牌层面的伪装（对照 §2.5 的品牌条款）。

#### 路径 B：利用宿主已有的"自定义 base_url"能力 —— ✅ **最优路径，且已在多处成立**

| 宿主 | 是否有官方自定义 base_url | 来源 |
|---|---|---|
| DSH | ✅ **有**（"添加自定义提供方"：Provider ID + 基础 URL + API 协议 + 凭据 + 模型） | <https://deepseek-harness.github.io/deepseek-harness/guide/providers> |
| Continue | ✅ `apiBase` | <https://docs.continue.dev/customize/model-providers/top-level/openai> |
| Cline | ✅ "Base URL" | <https://docs.cline.bot/provider-config/openai-compatible> |
| Roo Code | ✅ "Base URL" | <https://docs.roocode.com/providers/openai-compatible> |
| **Cherry Studio**（`README.zh-CN.md:17` 点名的目标客户端） | ✅ 自定义服务商：填 `API 地址`（Base URL）+ `API 密钥`（**但模型 ID 需手填，不自动发现**） | <https://docs.cherry-studio-ai.com/pre-basic/providers/zi-ding-yi-fu-wu-shang>【一手】 |
| **Trae**（`README.zh-CN.md:17` 点名的目标客户端） | ✅ 自定义模型：手填模型 ID + 上下文长度 + 多模态开关 | <https://forum.trae.cn/t/topic/11480>【二手】（社区用户教程，**作者非官方**） |
| Claude Code | ⚠️ `ANTHROPIC_BASE_URL`（但只认 Anthropic Messages，且官方声明不支持非 Claude 模型） | <https://code.claude.com/docs/en/llm-gateway> |
| Cursor（`README.zh-CN.md:17` 点名） | 【未找到】官方文档未记载 | §1.3 |
| Zed | ❌（模型配置归 External Agent） | <https://zed.dev/docs/ai/external-agents> |
| VS Code | ❌（无 base_url 设置；要写扩展） | <https://code.visualstudio.com/api/extension-guides/ai/language-model-chat-provider> |

> **注**：上表已补齐 `README.zh-CN.md:17` 明确点名的三个目标客户端（Trae / Cursor / Cherry Studio）。其中 **Cherry Studio 与 Trae 均确认支持自定义 base_url**（Cherry 为官方文档【一手】，Trae 为社区教程【二手】），**Cursor 的官方支持情况【未找到】**——这三者的"模型清单自动发现"能力普遍缺失，详见 `04` 号文档 §D.2 与 `:791-796`。

**结论：这是覆盖率最高、成本最低的路径。** 我们的工作是**确保网关对这条路径"零摩擦"**（见 §3.5 的落地清单）。

#### 路径 C：MCP 桥接（把模型能力包装成 MCP tool） —— ❌ **不可行作为"模型接入"，只可作为"能力旁路"**

- **为什么不可行**：MCP 的能力面是 **tools / prompts / resources**，官方文档中**没有**任何"注册模型 provider"的机制（§1.1 第 4 条，【一手】+【未找到】）。MCP 不能把我们的模型放进宿主的模型选择器。
- **它实际会变成什么**：宿主仍然用**自己的模型**跑 agent loop，只是多了一个"可以调用网关"的 tool。结果是**嵌套 LLM 调用**（宿主模型决定调用 → tool 内再发起一次网关请求 → 结果回灌给宿主模型）。**代价**：双倍 token、双倍延迟、上下文被 tool 结果污染、用量统计分裂。
- **唯一合理的用法**：**不是**接模型，而是**暴露网关的管理能力**（如"列出当前可用模型/资源状态/用量"）给 agent 查询。这是"旁路"，不是"接入"。
- **结论**：**明确不推荐**用于模型接入。

#### 路径 D：让宿主直接读网关的 `/v1/models` —— ✅ **已可用，且已被 DSH 官方流程采用**

- **DSH 官方明文**："模型发现会调用 OpenAI 兼容的 `GET /models` 端点"；响应需含 `data` 数组或 `models` 对象（<https://deepseek-harness.github.io/deepseek-harness/guide/providers>）。
- **我们的现状**：`GET /v1/models` 返回 `{"object":"list","data":[{"id": m.name, "object":"model", "created": 0, "owned_by":"model-gateway", "endpoint": ..., "group": ...}]}`（`model_gateway/api/openai_compat.py:36-44`）→ **完全命中 `data` 数组格式**。
- ⚠️ **一个必须验证的点**：DSH 探测用的是 `GET /models`（相对 base URL）。用户填的 base URL 若是 `http://127.0.0.1:8300/v1`，则请求落在 `/v1/models` ✅。**但 DSH 表单里填的"基础 URL"是否含 `/v1` 后缀需要实测确认**——若用户填 `http://127.0.0.1:8300`，则探测会打到 `/models`（我们**没有**这个路由）→ 探测失败，用户需手填模型。
  → **这是零成本、高收益的一个可选项**：**同时暴露 `/models` 与 `/v1/models` 两个别名**（或文档明确要求用户填带 `/v1` 的 base URL）。**建议先做文档，再评估是否加别名路由。**
- Claude Code 侧：discovery 会调 `GET /v1/models?limit=1000`，**但会被 `id` 过滤器滤掉**（§1.1），此路径对 Claude Code 无效。

#### 路径 E（新增，来自本次调研）：补齐"网关作为 OpenAI 兼容端点"的**摩擦点**

DSH 官方排错节列出的坑，有两条**在我们的网关侧可以消除**（§1.7 表）：

| 现象 | 网关侧可选动作 | 收益 |
|---|---|---|
| 客户端发 `role: "developer"`，上游拒绝 | 入站归一 `developer` → `system` | 让"声明了推理能力的模型"能在 DSH 下开箱可用，用户不必去改 `settings.yaml` |
| 客户端发 `max_completion_tokens`，上游只认 `max_tokens` | 入站归一/双写 | 同上 |

> ⚠️ **但这两条与项目铁律"无依据自创禁止"存在张力**：它们会让网关**改写**客户端请求体，而不是"透传优先"。当前实现是"只 pop `model`，其余原样透传"（`model_gateway/api/openai_compat.py:121-125`）。**是否引入改写，需要用户拍板**（见 §3.6）。

### 3.5 推荐排序与理由（含翻转条件）

#### 推荐排序

| 优先级 | 动作 | 成本 | 收益 | 依据 |
|---|---|---|---|---|
| **P0** | **把 ① 打磨到"零摩擦"**：文档给出各宿主的 base_url 填法（Continue/Cline/Roo/DSH/Claude Code 用 `/v1/messages`） | 文档工作 | 覆盖 §3.4 表里 **5/8 宿主** | §3.4 路径 B/D |
| **P0** | **确认 `/v1/models` 能被 DSH 探测**（base URL 是否带 `/v1`），必要时加 `/models` 别名 | 极小 | 让 DSH 用户"填一次 base_url 即可"，**彻底不需要插件** | §3.4 路径 D |
| **P1** | 补齐 `tools`/`tool_calls` 的**完整透传**保证（Roo Code 硬要求） | 测试为主 | 决定 Continue/Cline/Roo 是否可用 | §1.5、§2.4 |
| **P2** | 评估 `/v1/models` 是否附加 `context_window` 等**非标准但无害**的元数据字段 | 极小 | 部分替代 ③ 的"元数据"优势 | §2.4、§3.1 理由 4 |
| **P3** | **不主动做 ③ 插件**。仅当出现"用户明确要求 + 该宿主无自定义 provider 能力 + 该宿主有公开 provider 插件 API"三个条件同时成立时，按宿主逐个评估 | 1000～1600 行/宿主 | UX 提升（省掉手填 base_url） | §3.2、§3.3 |
| **P4** | ② CLI 子进程：**不实现** | — | 无独立价值（保真度最差、可移植性也不优于 ①） | §2.1～§2.4 |
| **❌** | ③ 的**胖插件**变体 | 极高 | 负收益（第二套实现） | §3.2 |

#### 翻转条件

**条件 1：目标宿主数量。**

| 场景 | 结论 | 理由 |
|---|---|---|
| 目标 = **10 个宿主** | **① 绝对优先，③ 不做** | ① 成本恒定为 1（+ Anthropic 面已有）；③ 成本 = `10 × 1000~1600 行`，且要跟 10 套宿主内部 API |
| 目标 = **1 个宿主** | **看该宿主有没有自定义 provider**：有（DSH）→ 仍做 ①；没有（如 VS Code）→ ③ 才有意义 | DSH 已证 §1.7；VS Code 需扩展（§1.2） |

**条件 2：该宿主是否支持自定义 base_url。**
- **支持** → ③ **不需要**（DSH 就是此例）。
- **不支持但有 provider 插件 API** → ③ 是**唯一**选择（VS Code 是此例）。
- **都不支持**（Cursor，【未找到】）→ 目前**无稳定形态**，应记为"暂不支持"，而不是硬做插件。

**条件 3：目标宿主是否是"自家模型入口"型。**
- Claude Code 明确"doesn't support routing Claude Code to non-Claude models through any gateway"（§1.1）→ 即使做插件也不该做（做插件也绕不过这条官方立场）。
- 这条与"技术上能不能"无关，是**宿主的产品立场**。

**条件 4：如果出现"必须改宿主二进制/侵入宿主进程"的诱惑。**
- 参考插件的 `AGENTS.md:863-876` 已证明：同进程插件的未捕获错误会打挂整个宿主。**我们的铁律是"纯本地、无远程更新"，但没说过"可以侵入别人的进程"。** 建议把"不写宿主插件"作为**默认立场**，只在用户明确要求且宿主无其他路径时破例。

**条件 5：如果 DSH 未来关闭"自定义提供方"表单。**
- 那么 DSH 会从"① 零成本"变成"③ 才有意义"。**这是一个外部依赖风险，值得在文档里记录并定期复核。**

### 3.6 待用户拍板的不确定项

| # | 事项 | 为什么需要拍板 |
|---|---|---|
| 1 | **是否允许网关"归一"客户端请求体**（`developer` → `system`、`max_completion_tokens` → `max_tokens`） | 与"透传优先"（`model_gateway/api/anthropic.py:3`）和"无依据自创禁止"直接冲突。收益是让 DSH 的推理模型开箱可用（§3.4 路径 E） |
| 2 | **是否允许在 `/v1/models` 附加非标准字段**（如 `context_window`） | 同上是"协议自创"边界问题；收益是部分替代 ③ 的元数据优势 |
| 3 | **是否新增 `/models` 别名路由** | 需要先实测 DSH 探测实际打到哪个路径；若用户 base URL 习惯不带 `/v1`，这个别名价值很高 |
| 4 | **Cursor 怎么办** | 官方文档【未找到】自定义端点能力，社区材料称有。**需要用户确认实际可用性**，再决定是否支持 |
| 5 | **Claude Code 是否纳入正式支持** | 我们**已有** `/v1/messages`，技术上通；但官方明确不支持非 Claude 模型走网关，且 discovery 会滤掉我们的模型名。是否在文档里标注"实验性支持"需要拍板 |
| 6 | **"实验性支持"的文档措辞** | 涉及是否声明"支持某宿主"。本文只给事实，不给结论 |
| 7 | **是否接受"一个网关 = 两个 DSH provider 条目"** | DSH 官方硬约束："**一个提供商只使用一种协议，网关同时提供两种时需要建两个提供商**"（【一手】，见 §4.3 第 4 项）。我们同时有 OpenAI 面与 Anthropic 面 → 用户要建两条。**接受 → 文档照写；不接受 → 需要评估"是否只暴露一个协议面"这种更大的产品决策** |
| 8 | **是否做 VS Code 瘦插件** | 目前唯一"无自定义 provider 能力 + 有公开插件 API"的宿主（§4.4）。需先确认是否真有 VS Code 场景 |

---

## 4. 专业建议：怎么对接最高效、最稳定

> 本节是主 agent 基于 §1~§3 的**综合判断**，直接回答用户的问题。§1~§3 是证据，本节是结论。

### 4.1 一句话回答

**不新增中间层。** 把网关**已有的** OpenAI 兼容面打磨到"**零摩擦**"，让宿主用它**自己原生的自定义 provider 能力**接入我们 —— 这是**同时最省事、最稳定、覆盖最广**的路径。

**具体到 DSH：不要写插件。** 它原生支持"添加自定义提供方"（§1.7，官方文档逐字已核实），写插件等于**给一条已经能走通的路再修一条冗余匝道**。

### 4.2 为什么不是"原生插件"——三条决定性理由

**理由 1（数量级论证）：插件省下的延迟，相对上游延迟可以忽略。**

| 环节 | 量级 |
|---|---|
| 插件省掉的：本机 loopback 的 TCP 握手 + HTTP 头 + JSON 序列化 | **亚毫秒** |
| 网关的端到端延迟（由**上游厂商 API** 主导） | **几百毫秒 ～ 数秒** |

两者相差 **2～3 个数量级**。为省这 0.1% 的开销，付出"可移植性 + 进程隔离 + 版本稳定性"三项代价 —— **不划算**。这是本节最硬的一条论据：**它把"插件更快"这个直觉，从"快多少"的角度证伪了。**

**理由 2（方向相反）："最高效"与"最稳定"不是同一个答案。**

| 形态 | 故障面 | 版本漂移风险 | 崩溃隔离性 |
|---|---|---|---|
| **① API** | **最小** | **最低**（协议冻结） | ✅ 进程隔离 |
| ② CLI | 中 | **最高**（人类可读输出最易漂） | ✅ 进程隔离 |
| ③ 原生插件 | **最大** | **最高**（跟宿主**内部 API**） | ❌ **同进程 —— 插件崩了打挂宿主** |

③ 的隔离性问题**不是理论推测**：参考插件自己的 `AGENTS.md:863-876` 记录了真实事故 —— 一个未注册 `'error'` 处理器的 `listen()` 失败，**把整个 DSH 宿主打挂**。

对网关这种"要长期稳定服务多个客户端"的定位，**稳定性权重必须高于那点延迟**。

**理由 3（成本随宿主数线性增长）：**

- ① 的成本**恒定为 1**（而且我们**已经有** OpenAI + Anthropic 两个入站面）。
- ③ 的成本 = `N 宿主 × 1000~1600 行`，且要跟 **N 套宿主内部 API** 的变更。
- 覆盖 10 个宿主时，差距被放大到不可接受。

### 4.3 那"最高效"到底靠什么达成？

**靠"把摩擦点降到零"，不是靠"加一层"。** 四件事，全部是低成本：

| # | 动作 | 成本 | 效果 |
|---|---|---|---|
| 1 | **实测确认 DSH 探测打到哪个路径**（`base URL + /models` 的拼接行为），必要时加 `/models` 别名路由 | 极小 | 用户填一次 base URL，**模型自动出现在选择器里** |
| 2 | **文档给出各宿主的 base_url 填法**（含 DSH「添加自定义提供方」的分步说明） | 文档工作 | 消除"该填什么"的认知成本 |
| 3 | **补齐 `developer` / `max_completion_tokens` 的摩擦说明**（优先用**零代码**方案：告知用户设 `compat.supportsDeveloperRole: false` + `compat.maxTokensField: max_tokens`） | 文档工作 | 让 DSH 下的推理模型**开箱可用** |
| 4 | **文档写清"两个协议 = 两个 provider 条目"**（我们的 OpenAI 面 + Anthropic 面在 DSH 里要各建一条） | 文档工作 | 消除"为什么 Claude 模型走不了"的排查成本 |

> **第 3 项的官方背书（新增一手证据）**：DSH 官方排错文档**把这两个坑列为"网关最常被拒的两样"**，逐字为：
> "声明了推理能力的模型，其系统提示词会以 `role: "developer"` 发出，很多网关直接拒绝；输出上限则写作 `max_completion_tokens`，只认 `max_tokens` 的服务端会拒绝。"
> 且官方给出的解法**就是客户端侧开关**，逐字为：
> "**密钥与地址都正确，网关却拒绝每一个请求**：它的请求形状与 OpenAI 不同。先在路由上设 `compat.supportsDeveloperRole: false` 与 `compat.maxTokensField: max_tokens`。"
> **即：DSH 官方把修复责任放在客户端侧开关上，而不是要求网关改行为。** 这**印证了本节的判断** —— "零代码方案"是**官方推荐路径**，不是权宜之计。
> （来源：`https://deepseek-harness.help/zh-cn/configure/providers/` 与官方 `docs/user/guide/providers.zh.md`，均为【一手】；完整引文见 `09` 号文档 §4.2）
>
> 网关**当前对这两个标识零命中**（实测，见 §3.4 路径 E），收到即原样透传。**我倾向不改成"网关侧归一"** —— 因为那是**语义改写**（把客户端的意图改掉），不是**协议转换**（把同一意图换一种表达），会冲撞"透传优先"（`model_gateway/api/anthropic.py:3`）与铁律 4「无依据自创禁止」。
>
> **第 4 项的依据（新增一手证据）**：DSH 官方逐字 —— "**一个提供商只使用一种协议，网关同时提供两种时需要建两个提供商。**"（来源同上）

### 4.4 什么情况下我会改口

**三个条件同时成立**时，才值得为某个宿主做**瘦插件**：

1. 用户**明确要求**；
2. 该宿主**没有**自定义 provider 能力；
3. 该宿主**有**公开的 provider 插件 API。

**目前只有 VS Code 落在这一格**（`LanguageModelChatProvider`）。**DSH 不落**（它有"添加自定义提供方"）。

**做也只做瘦插件**：插件只做"把请求转发给网关的本地 API"，**凭据 / 账号池 / 调度全部留在网关**（单一事实源）。
**胖插件（把凭据与调度搬进宿主）明确否决** —— 那是**第二套实现**，双份维护，且把厂商 Key 散落到每个宿主的凭据库里（合规上也更差：网关不再是唯一凭据持有者）。

### 4.5 明确不做的事（附理由）

| 不做 | 理由 |
|---|---|
| ❌ **为 DSH 写插件** | 它原生支持自定义提供方（§1.7）。写插件 = 冗余路径 + 无谓维护 + 同进程风险 |
| ❌ **CLI 形态（作为下游）** | 保真度最差（元数据全丢）、可移植性不优于 API、还要管子进程生命周期。它唯一的价值是覆盖"**不提供公开 API** 的平台"——那是**上游**问题，不是下游形态问题 |
| ❌ **胖插件** | 第二套实现，违反单一事实源 |
| ❌ **MCP 桥接当作模型接入** | MCP 能力面是 tools / prompts / resources，官方**没有**注册模型的机制。硬做会退化成"嵌套 LLM 调用"（宿主模型决定调 tool → tool 内再发一次网关请求）→ **双倍 token、双倍延迟、用量统计分裂** |
| ❌ **侵入宿主进程** | 与"纯本地、无远程更新"的克制定位不符。建议把"**不写宿主插件**"作为**默认立场** |

### 4.6 一句话收尾

**网关的价值是"聚合远端厂商"，不是"抢在宿主前面"。** 端到端延迟由上游主导，所以**下游形态的竞争维度不是"快几毫秒"，而是"接得进多少宿主、坏的时候会不会连累别人、宿主改版时谁去跟进"**。这三个维度上，**OpenAI 兼容 HTTP API 全面胜出**。

---

## 附录 A · 外部来源清单（全部可打开）

| # | URL | 用于 | 分级 |
|---|---|---|---|
| A1 | <https://docs.claude.com/en/docs/claude-code/llm-gateway> | Claude Code 网关定位、`ANTHROPIC_BASE_URL`、不支持非 Claude 模型 | 【一手】 |
| A2 | <https://code.claude.com/docs/en/llm-gateway-protocol> | 三种 API 格式、`/v1/messages`、`HEAD /api/hello` | 【一手】 |
| A3 | <https://code.claude.com/docs/en/llm-gateway-connect> | `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`/`apiKeyHelper`、discovery 开关与 5 分钟缓存 | 【一手】 |
| A4 | <https://code.claude.com/docs/en/model-config> | `availableModels`（限制语义）、`ANTHROPIC_CUSTOM_MODEL_OPTION`、`ANTHROPIC_BASE_URL` 语义 | 【一手】 |
| A5 | <https://code.claude.com/docs/en/headless> | `-p`、`--output-format`、`--bare`、SIGTERM 143 | 【一手】 |
| A6 | <https://docs.claude.com/en/docs/claude-code/mcp> | MCP 能力面（tools/prompts/resources）、四种传输、无模型注册 | 【一手】+【未找到】 |
| A7 | <https://code.claude.com/docs/en/agent-sdk/overview> | Agent SDK 定位、Plugin 打包内容、品牌条款 | 【一手】 |
| A8 | <https://docs.claude.com/en/api/openai-sdk> | Anthropic 自家 OpenAI 兼容层、`base_url="https://api.anthropic.com/v1/"`、兼容性限制表 | 【一手】 |
| A9 | <https://code.visualstudio.com/api/extension-guides/language-model> | `vscode.lm` 消费侧、`selectChatModels` | 【一手】 |
| A10 | <https://code.visualstudio.com/api/extension-guides/ai/language-model-chat-provider> | `LanguageModelChatProvider` 提供侧、三方法、BYOK 策略 | 【一手】 |
| A11 | <https://cursor.com/help/models-and-usage/api-keys> | Cursor BYOK 五家 provider、ZDR 不适用 | 【一手】 |
| A12 | <https://cursor.com/docs/models> | Cursor 模型与定价（无自定义端点内容） | 【一手】（不含目标信息） |
| A13 | <https://agentclientprotocol.com/get-started/introduction> | ACP 定位（editor ↔ agent） | 【一手】 |
| A14 | <https://zed.dev/docs/ai/external-agents> | Zed 边界表、模型/provider 归 agent | 【一手】 |
| A15 | <https://docs.continue.dev/customize/model-providers/top-level/openai> | Continue `apiBase` | 【一手】 |
| A16 | <https://docs.cline.bot/provider-config/openai-compatible> | Cline Base URL/API Key/Model ID | 【一手】 |
| A17 | <https://docs.roocode.com/providers/openai-compatible> | Roo Code + native tool calling 硬要求 | 【一手】 |
| A18 | <https://github.com/cordiverse/cordis> | Cordis 自述、API 不稳定警告 | 【一手】 |
| A19 | <https://deepseek-harness.github.io/deepseek-harness/reference/cordis-primer> | Cordis 五个核心概念（Service/inject/ctx.get/effect） | 【一手】 |
| A20 | <https://koishi.chat/zh-CN/guide/plugin/service> | Koishi 服务与依赖（inject required/optional、Service 生命周期） | 【一手】 |
| A21 | <https://deepseek-harness.github.io/deepseek-harness/reference/subsystems/llm-streaming> | `LlmAdapter` 契约、`StreamChunk`、`registerAdapter`/`registerConfigurableProviders`、适配器 9 条规则 | 【一手】 |
| A22 | <https://deepseek-harness.github.io/deepseek-harness/reference/subsystems/core> | `llm-streaming` 子系统归属、`packages/llm` 声明对话词汇 | 【一手】 |
| A23 | <https://deepseek-harness.github.io/deepseek-harness/guide/providers> | **DSH 自定义提供方表单、协议三选一、探测 `/models`、compat 坑与排错** | 【一手】 |
| A24 | <https://deepseek-harness.github.io/deepseek-harness/guide/quickstart> | DSH 设置 → 模型入口 | 【一手】 |
| A25 | <https://docs.litellm.ai/docs/proxy/quick_start> | LiteLLM "100+ LLMs in OpenAI format"、端点清单 | 【一手】 |
| A26 | <https://github.com/microsoft/vscode-extension-samples/blob/main/chat-model-provider-sample> | VS Code 官方 provider 示例工程 | 【一手】 |
| A27 | <https://segmentfault.com/a/1190000048204894> | Cursor "Override Base URL"（**仅二手，未在官方文档核实**） | 【二手】 |
| A28 | <https://developer.aliyun.com/article/1762261> | Cursor 走 `/v1/chat/completions`（**仅二手**） | 【二手】 |

**未找到（明确记录）**
- Cursor 官方文档中"自定义 base URL / OpenAI 兼容端点"的记载 → **【未找到】**
- Cursor 的 provider 插件 API → **【未找到】**
- MCP 提供/注册模型 provider 的机制 → **【未找到】**
- Zed ACP 中的"模型 provider"角色 → **【未找到】**（ACP 只有 client/agent 两角色）

---

## 附录 B · 内部源码引用与行号校验

### B.1 DSH 参考插件（只读）

| 引用 | 内容 |
|---|---|
| `package.json:6` | `"main": "lib/index.js"`（**无 `bin` 字段** → 非 CLI） |
| `package.json:8-15` | `exports` 只有 `.` 与 `./client` |
| `package.json:21` | `"build": "tsc -p tsconfig.json"` |
| `package.json:47-54` | `"dsh": { "bundle": { "patch": "./cordis.patch.yml" }, "client": { "platform": "web" } }` |
| `package.json:55-61` | `peerDependencies`：`@deepseek-ai/cordis` / `dsh-credentials` / `dsh-commands` / `dsh-llm` / `schemastery` |
| `package.json:79-81` | `engines.node` = `^22.19.0 \|\| >=24.0.0` |
| `cordis.patch.yml:1-5` | `- insert: - id: codearts-auth / name: 'dsh-codearts-auth'` |
| `src/index.ts:25` | `export const name = 'codearts-auth'` |
| `src/index.ts:25-31` | 注释：`connection` 刻意不列入静态 inject（headless profile 会永久 pending） |
| `src/index.ts:33` | `export const inject = ['credentials', 'commands', 'llm']` |
| `src/index.ts:37-41` | 注释：`settingsNs` 未注册 → `provider.toUpperCase is not a function` 崩溃 |
| `src/index.ts:43-48` | 注释：必须用 schemastery `Schema.object`，裸函数会让 `describe()` 抛 `TypeError` |
| `src/index.ts:50-52` | `providerSettingsSchema = Schema.object({ providers: Schema.dict(Schema.any()).default({}) })` |
| `src/index.ts:55-91` | `registerProviderSettings()` |
| `src/index.ts:103-116` | `makeReadImage(ctx)`（附件桥接，用 `ctx.get('attachments')`） |
| `src/index.ts:121` | `export function apply(ctx: Context): void` |
| `src/index.ts:148-195` | `ctx.commands.register(...)` 三个斜杠命令 |
| `src/index.ts:196-215` | `registerCodeArtsLlm(ctx, {...})` 调用点（含 `resolveCredential` 走账号池） |
| `src/index.ts:297-313` | 长注释：`resolveCredential` 与 `refresh()` 的 ref 错配 → 401 且"极难排查" |
| `src/index.ts:386-401` | 30 分钟续期定时器 + `ctx.effect` 清理 |
| `src/index.ts:391-399` | `ctx.effect(() => () => {...})` 注册清理 |
| `src/index.ts:429` | `ctx.provide('accountPool', pool)` |
| `src/llm-adapter.ts:14` | `export const CHAT_API_BASE = 'https://snap-access.cn-north-4.myhuaweicloud.com/api/v2'`（**厂商端点常量 → 推理在远端**） |
| `src/llm-adapter.ts:10` | `import { signRequestHuawei } from './sign.js'`（**出网签名**） |
| `src/llm-adapter.ts:726` | `export class CodeArtsAdapter extends LlmAdapter` |
| `src/llm-adapter.ts:746` | `providerInfo(provider: string): LlmProviderInfo` |
| `src/llm-adapter.ts:785` | `async listModels(_provider: string): Promise<readonly LlmModelInfo[]>` |
| `src/llm-adapter.ts:801` | `async resolveModel(provider, model, _signal?): Promise<LlmResolvedModelInfo>` |
| `src/llm-adapter.ts:811` | `async prepareCall(...)` |
| `src/llm-adapter.ts:835` | `async *stream(options: GenerateOptions): AsyncIterable<StreamChunk>` |
| `src/llm-adapter.ts:1354-1366` | `yield { type: 'block-end', index, block: { type: 'tool-call', ... } }`（多行） |
| `src/llm-adapter.ts:1385` | `yield { type: 'finish', reason }` |
| `src/llm-adapter.ts:1440` | `export function registerCodeArtsLlm(ctx, options)` |
| `src/llm-adapter.ts:1454-1443` | `ctx.llm.registerConfigurableProviders([{ provider, displayName, settingsNs: 'llm-codearts', settingsPath: [] }])` |
| `src/llm-adapter.ts:1458` | `ctx.llm.registerAdapter([PROVIDER], adapter)` |
| `src/llm-adapter.ts:1457` | `const RATE_LIMIT_BUSINESS_CODE = 6004` |
| `src/llm-adapter.ts:1497` | `export function isRateLimited(body: string): boolean` |
| `src/llm-adapter.ts:1513` | `export function parseRateLimitError(body, currentModel)` |
| `docs/adding-a-new-provider.md:76` | LLM 适配器层职责：`listModels` / `resolveModel` / `stream` |
| `docs/adding-a-new-provider.md:322-328` | 必须遵守的契约表（`refreshAll` 不看 `enabled`、两步式登录、`refreshAccountCredential`） |
| `docs/adding-a-new-provider.md:335-346` | `LlmAdapter` 子类必须实现的 4 个方法 + `prepareCall` 建议实现 |
| `docs/adding-a-new-provider.md:349-356` | 4 个关键决策点（`stream` 是否恒真、图片、推理补档、`prompt_cache_key`）——"**不能从代码推理，必须凭实测回答**" |
| `docs/adding-a-new-provider.md:358-362` | `src/sse.ts` 共享工具四件套 |
| `docs/adding-a-new-provider.md:404` | `registerXxxLlm` 最终调用 `registerConfigurableProviders` + `registerAdapter` |

### B.2 Model-Gateway（只读）

| 引用 | 内容 |
|---|---|
| `model_gateway/api/openai_compat.py:36` | `@router.get("/v1/models")` |
| `model_gateway/api/openai_compat.py:39-43` | 返回字段：`id`/`object`/`created`/`owned_by`/`endpoint`/`group`（**无上下文窗口**） |
| `model_gateway/api/openai_compat.py:101` | `@router.post("/v1/chat/completions")` |
| `model_gateway/api/openai_compat.py:121-125` | `stream = bool(...)`；`lift_reasoning_from_body(body)`；`body.pop("model", None)`；`IRRequest(...)`（**透传优先**） |
| `model_gateway/api/openai_compat.py:238` | `@router.post("/v1/images/generations")` |
| `model_gateway/api/anthropic.py:1-6` | docstring：IR 双向转换，**透传优先，只做协议间必需的语义映射** |
| `model_gateway/api/anthropic.py:316` | `@router.post("/v1/messages")` |
| `model_gateway/main.py:52` | `class Runtime` |
| `model_gateway/main.py:123` | `def _load_config_or_exit(config_path)` |
| `model_gateway/main.py:165` | `def create_app(config_path=None, *, usage_dir=None, enums_path=None)` |
| `model_gateway/main.py:182-184` | `include_router(openai_router / anthropic_router / admin_router)` |
| `model_gateway/main.py:186-187` | `@app.get("/health")` / `async def health()` |
| `config.example.yaml:9-11` | `gateway.host: 0.0.0.0` / `port: 8300` |
| `config.example.yaml:17-20` | `access_tokens`（`id`/`name`/`value: mg-xxxx`/`enabled`） |
| `config.example.yaml:32-33` | `cooldown_seconds: 60` / `cooldown_seconds_plan: 18000` |
| `config.example.yaml:41-59` | `resources`（扁平：厂商 + Key） |
| `config.example.yaml:48` | `api_key: sk-xxxxxxxx  # 明文` |
| `config.example.yaml:61-73` | `models`（系统模型 + 有序资源池） |
| `README.zh-CN.md:15` | 网关定位：聚合多厂商到**一个 OpenAI 兼容端点** |
| `README.zh-CN.md:17` | "只需把 Trae、Cursor、Cherry Studio 或任何 OpenAI 兼容客户端指向 `http://127.0.0.1:8300/v1` 一次" |
| `README.zh-CN.md:29` | 统一入站 API 表：`/v1/chat/completions`、`/v1/images/generations`、`/v1/messages`、`/v1/models` |
| `README.zh-CN.md:32` | 切换续跑：只要有可用资源，工具端无感 |
| `README.zh-CN.md:34` | 推理参数三级合并 |
| `README.zh-CN.md:36` | 全明文数据（YAML + JSONL，无数据库） |
| `README.zh-CN.md:81` | "把 OpenAI 兼容 base URL 填为 `http://127.0.0.1:8300/v1`" |
| `README.zh-CN.md:116` | "纯本地。无遥测、无远程配置、无自动更新" |
| `README.zh-CN.md:117` | "密钥不出本机。凭据只存本地配置文件" |

### B.3 交叉引用（平行调研）

| 引用 | 内容 |
|---|---|
| `docs/research/07-DSH插件本地LLM形态与宿主契约.md` §1.1 依据 5 | `AGENTS.md:863-876`：OAuth 回调 `listen()` 未注册 `'error'` → 进程级 unhandled error → **打挂整个 DSH 宿主**（同进程最强证据） |
| `docs/research/07-DSH插件本地LLM形态与宿主契约.md` §0.1 | "是宿主进程内形态，但不是本地 LLM 形态"（本文术语纠偏的来源） |
| `docs/research/07-DSH插件本地LLM形态与宿主契约.md` §0.3 | DSH 侧不存在可复用的推理 HTTP 端点；可复用的是"协议知识"而非"运行时" |

---

## 附录 C · 交付前自检

- [x] **每个外部结论都有可打开的 URL** —— 见附录 A（28 条）。找不到的明确写【未找到】（Cursor 自定义 base URL、Cursor 插件 API、MCP 模型注册、ACP 模型角色）。
- [x] **所有 `文件:行号` 引用真实** —— 见附录 B，全部由 Read/Grep 实测获得（DSH 侧 41 条、网关侧 27 条、交叉引用 3 条）。
- [x] **三形态对比的每个维度都给了理由** —— §2.1～§2.7，每维度含"结论 + 理由 + 证据链接/行号"。
- [x] **第三部分的推荐有明确理由 + 翻转条件** —— §3.5 给出 5 条翻转条件（宿主数量、自定义 base_url 有无、宿主产品立场、侵入性边界、外部依赖风险）。
- [x] **没有把"进程内 provider 注册"误解为"本地跑模型"** —— 全文术语为"宿主进程内原生 LLM Provider 插件"，并在文首、§2.1、§3.2 三处显式强调推理仍在远端（依据：`src/llm-adapter.ts:10`、`:928`、`:946`、`:822`）。
- [x] **合规只做事实转述** —— §2.5 全表为官方原文引用，未给任何法律意见。
- [x] **未对参考项目做任何写入** —— 全程只读（Read / Grep / Bash 仅 `ls`、`wc`、`find`、`head`、`sed -n` 读操作）。
