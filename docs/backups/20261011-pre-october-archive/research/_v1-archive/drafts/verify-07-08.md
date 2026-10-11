# 独立核验报告 · 07 / 08 两份调研文档

> 核验对象
> 1. `docs/research/07-DSH插件本地LLM形态与宿主契约.md`（1178 行）
> 2. `docs/research/08-宿主原生Provider机制横向调研.md`（798 行）
>
> 核验方式：**证伪导向**（默认怀疑，逐条回源）
> 核验日期：2026-09-22
> 核验员立场：未参与撰写，独立复核

---

## 一、核验方式

| 手段 | 覆盖范围 | 工具 |
|---|---|---|
| **机械校验（脚本化）** | 两份文档中**全部** `文件:行号` 引用（含续行引用 `、`:122`` 形式） | `/tmp/verify_refs.py`（Python，写入 `/tmp`，未触碰参考仓） |
| **内容吻合度人工比对** | 391 条去重后的 `(文档行 → 引用) vs (实际文件行内容)` 对照 | `/tmp/pairs.py` → `/tmp/pairs.txt`（约 98KB 对照表，逐条通读） |
| **关键结论深核** | 07 的 5 条正向证据 + 5 条反证；08 的 DSH 原生自定义提供方结论；网关 compat 缺口 | 直接 Read / Grep 源码 |
| **外部来源逐条 WebFetch** | 08 附录 A 全部 28 条 URL（含二手） | WebFetch，**逐条亲自打开** |
| **铁律冲突检查** | 08 §3 全部落地建议 | 对照网关 AGENTS.md / README 铁律 |

### 仓库归属映射（关键，避免同名文件假阳性）

| 仓库根 | 路径 | 仅属该仓的前缀 |
|---|---|---|
| DSH 参考插件 | `/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts` | `src/`、`tests/`、`plugin-src/`、`scripts/`、`cordis.patch.yml`、`tsconfig.json`、`vitest*.config.ts`、`docs/adding-a-new-provider.md`、`docs/lobsterai-integration-plan.md` |
| 网关 | `/Users/w/Desktop/Model-Gateway` | `model_gateway/`、`config.example.yaml`、`README.zh-CN.md` |

**同名文件陷阱已处理**：`AGENTS.md` 与 `README.md` 在两仓都存在（DSH 侧 1260/1122 行，网关侧 35/142 行）。脚本按上表判定归属；初筛报出的 23 条"行号越界"**全部**是此陷阱造成的假阳性，按 DSH 归属校验后**全部通过**。

### 只读约束

```
$ cd "/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts"
$ git status --porcelain      # 无输出
$ git rev-parse HEAD
397972908855bc458ef240d39ed24c1922a3a751
```

与 07 文档声明的基线一致。核验全程只读，未对参考仓与网关仓做任何写入。

---

## 二、机械校验结果汇总

| 指标 | 数值 |
|---|---|
| 提取到的引用实例（含续行） | **582** |
| 去重后唯一 `(文档, 仓, 文件, 行范围)` | **391** |
| 文件不存在 | **0** |
| 行号越界（真） | **0** |
| 行号越界（假阳性，同名文件陷阱） | 23（已全部排除） |
| **行号正确但内容与文档描述不符** | **1**（08 的 `src/llm-adapter.ts:14`，见 M2） |
| 内容吻合（人工逐条比对通过） | 390 / 391 |

> 07 附录 A 自称"`ALL 139 OK`"，08 附录 B 自称"DSH 侧 41 条、网关侧 27 条"。我的独立提取覆盖面更大（07 的续行引用如 `:133`、`:222`、`:251` 等 07 未计入 139 条），结论一致：**引用体系整体可信**，仅 1 处内容错配。

---

## 三、逐条问题清单

### 🔴 严重（0 条）

**没有任何一条核心结论被证伪。** 详见 §四。

---

### 🟠 中等（4 条）

#### M1 · 07 §1.2 反证 A —— `createServer` 计数与表格均错

- **位置**：`07-DSH插件本地LLM形态与宿主契约.md:88`（"全仓 `createServer` 只出现 3 处"）及同节表格 `:90-94`
- **问题描述**：计数错误，且表格漏一处调用点
- **实际情况**（全仓 grep 实测）：

  | 位置 | 内容 | 07 是否列出 |
  |---|---|---|
  | `src/login.ts:170` | `const server = createServer((request, response) => {`（`startCallbackServer`，旧流程） | ✅ 已列 |
  | `src/login.ts:287` | `const server = createServer((request, response) => {`（`startOAuthCallbackServer`，新式 IAM OAuth） | ❌ **漏列** |
  | `src/lobsterai-oauth.ts:256` | `const server = createServer(...)` | ✅ 已列 |
  | `src/trae-oauth.ts:596` | `const server = createServer()` | ✅ 已列 |
  | `src/trae-oauth.ts:715` | `const server = createServer()` | ✅ 已列 |
  | `tests/unit/trae-oauth.spec.ts:55` | `const blocker = createServer()`（测试用占位服务器） | ❌ 未列 |

  → `src/` 下**实为 5 处**（非 3 处），含测试共 6 处。
- **影响**：**结论不变**——5 处全部是 OAuth 登录回调服务器，无一与模型接入相关；"插件不对外提供推理 HTTP 端点"的核心定性**成立**。但计数是反证 A 的论证起点，错数会削弱可信度，且漏掉的 `login.ts:287` 恰恰是"第二个 OAuth 回调服务器"，属于该反证需要的证据而非反例。
- **建议修正**：改为"`src/` 下共 5 处 `createServer`（`login.ts:170`/`:287`、`lobsterai-oauth.ts:256`、`trae-oauth.ts:596`/`:715`），另有 1 处测试替身；全部为 OAuth 回调服务器"。

#### M2 · 08 文首 + 附录 B —— `src/llm-adapter.ts:14` 内容错配，且 08 内部自相矛盾

- **位置**：
  - `08-宿主原生Provider机制横向调研.md:12`："（`src/llm-adapter.ts:14` 导入 `signRequestHuawei`，…）"
  - `08-宿主原生Provider机制横向调研.md:726`（附录 B）："`src/llm-adapter.ts:14` | `import { signRequestHuawei } from './sign.js'`（**出网签名 → 推理在远端**）"
  - 对照：`08-宿主原生Provider机制横向调研.md:796`（附录 C 自检）写的是 "`src/llm-adapter.ts:10`" ✅
- **问题描述**：行号正确、内容不符；且同一文档两处写 `:14`、一处写 `:10`，**内部矛盾**
- **实际情况**（`src/llm-adapter.ts` 逐行）：
  ```
   9  import { AccountPool } from './account-pool.js'
  10  import { signRequestHuawei } from './sign.js'          ← 真正的 import 行
  11  import { isTruncatedArguments, normalizeToolArguments, readWithIdleTimeout, resolveToolPairing } from './sse.js'
  12  import type { CodeArtsCredential } from './types.js'
  13
  14  export const CHAT_API_BASE = 'https://snap-access.cn-north-4.myhuaweicloud.com/api/v2'   ← :14 实为厂商端点常量
  ```
- **对比**：07 用 `:14` 指"codearts → `https://snap-access.cn-north-4.myhuaweicloud.com/api/v2`"（`07:147`）——**07 是对的**。
- **影响**：该引用是"推理在远端"这一术语纠偏的证据行之一。事实成立（`:10` 的 import + `:822` 的 `stream()` 出网 + `:14` 的远端端点常量，三者都指向远端），但行号张冠李戴，且暴露了内部不一致。
- **建议修正**：两处 `:14` 改为 `:10`；或改为"`src/llm-adapter.ts:10` 导入 `signRequestHuawei`、`:14` 定义远端 `CHAT_API_BASE`、`:822` 起 `stream()` 内出网"。

#### M3 · 07 §4.3 与 08 §1.7 对"基类必需方法"的表述不一致

- **位置**：
  - `07:386-395`（§4.3 方法实现矩阵，列名"是否必须"）：`providerInfo` / `listModels` / `resolveModel` / `stream` 标为"**必须**"，`prepareCall` 标"建议"
  - `08:249`（§1.7(1)）："适配器契约原文：… 且 "**The only required method.**"（仅 `stream()` 必需）"
- **问题描述**：同一契约事实，两文表述冲突
- **实际情况**（亲自 WebFetch `https://deepseek-harness.github.io/deepseek-harness/reference/subsystems/llm-streaming`）：

  > `abstract stream(options: GenerateOptions): AsyncIterable<StreamChunk>;`
  > `/** Stream one model call as raw chunks. The only required method. ... */`

  官方基类中**只有 `stream()` 是 `abstract`**；`providerInfo` / `providerRetryPolicy` / `imageRequestPricing` / `listModels` / `resolveModel` / `prepareCall` **均有默认实现**。
- **07 的来源**：07 未联网，其"必须"取自仓库内 `docs/adding-a-new-provider.md:338-342`（"必须实现的 4 个方法"）。该文件确实这么写（已核实 `:338` = `// 必须实现的 4 个方法：`），所以 07 是**忠实转述仓库文档**——但把它当成"是否必须"的结论列在表头，且未声明这是仓库口径。
- **影响**：08 的 §3.3"最小接口清单"采信官方口径（item 8 标"**唯一必需方法**"），是**正确的**；07 的"必须"标注会误导插件作者以为 4 个方法缺一不可。两文若并存，读者会困惑。
- **建议修正**：07 §4.3 表头"是否必须"改为"仓库文档要求 / 官方基类"，并注明"官方仅 `stream()` 为 `abstract`，其余有默认实现，但仓库约定 4 个都实现"。

#### M4 · 08 §3.4 路径 B 覆盖表遗漏网关自认的主力目标客户端（Trae / Cherry Studio）

- **位置**：`08:567-576`（§3.4 路径 B 表）、`08:612`（§3.5 P0"覆盖 §3.4 表里 5/8 宿主"）
- **问题描述**：**该覆盖却漏掉**
- **实际情况**：网关 README 明文点名的目标客户端只有三家 —— `README.zh-CN.md:17`："只需把 **Trae、Cursor、Cherry Studio** 或任何 OpenAI 兼容客户端指向 `http://127.0.0.1:8300/v1` 一次"。08 §3.4 表列了 DSH / Continue / Cline / Roo Code / Claude Code / Cursor / Zed / VS Code 共 8 个宿主，**既无 Trae 也无 Cherry Studio**。
- **影响**：路径 B 是 08 的**主推路径**（P0），其覆盖率论证却把网关自己写进 README 的两个主力目标排除在外。§3.5 P0 的"5/8"分母因此可疑（真实分母至少 10）。
- **建议修正**：补 Trae、Cherry Studio 两行（标注其自定义 base_url 能力的核实结果或【未找到】），并同步修正 P0 的覆盖率数字。

---

### 🟡 轻微（10 条）

#### L1 · `exports` 条目计数少一个

- **位置**：`07:48`（"`exports` 只有 `.` 与 `./client` 两个入口（`package.json:8-15`）"）、`08:705`（附录 B 同款表述）
- **实际**：`package.json:8-15` 有**三个**键：`"."`（:9-12）、`"./client"`（:13）、`"./package.json"`（:14）
- **影响**：无——"无 `bin` 字段"这一核心结论不受影响（已 grep 确认全仓无 `"bin"`）
- **建议**：改为"`exports` 只有 `.` / `./client` / `./package.json`，**无 `bin`**"

#### L2 · 08 §1.1(2) 伪引号

- **位置**：`08:67`："⚠️ **OpenAI Chat Completions 不在其列**。原文明确："本文档**未列出**该格式"（该页只列三种）。"
- **实际**：`code.claude.com/docs/en/llm-gateway-protocol` **没有**这句话。该页只列三种格式（Anthropic Messages / Amazon Bedrock InvokeModel / Google Cloud's Agent Platform rawPredict），全文未出现 "OpenAI" 字样——**事实成立**，但"原文明确：…"是把作者概括放进了引号并冠以"原文明确"
- **建议**：改为"该页**未列出**该格式（全文未出现 OpenAI 字样）"，去掉引号

#### L3 · 08 §1.7(1) 引文归属错位

- **位置**：`08:248` 引用 "循环搬运的对话词汇——`Message`、`ContentBlock`、`StreamChunk`、模型请求——由 `packages/llm` 声明"，该 bullet 组唯一列出的来源是 `08:252` 的 **A21（llm-streaming 页）**
- **实际**：该句出自 **A22（`reference/subsystems/core`）**，原文完整为"循环搬运的对话词汇——`Message`、`ContentBlock`、`StreamChunk`、模型请求——由 `packages/llm` 声明，记录在 llm-streaming.md"（已 WebFetch 逐字确认）。08 附录 A22 的描述本身是**正确**的
- **影响**：引文真实、分级正确（【一手】），仅 URL 归属错位
- **建议**：该 bullet 补注 A22

#### L4 · 08 §1.6(3) Koishi 引文失真

- **位置**：`08:234`："自定义服务原文：`export default class Console extends Service { constructor(ctx, name) { super(ctx, 'console') } }`"
- **实际**（`koishi.chat/zh-CN/guide/plugin/service`）：
  ```ts
  export default class Console extends Service {
    constructor(ctx: Context) {
      super(ctx, 'console')
    }
  }
  ```
  子类签名只接收 `ctx`；`name` 是 `Service` 基类 `super()` 的第二个参数，不在子类形参里
- **建议**：照抄原文签名

#### L5 · 08 §3.1 内部交叉引用错（§3.5 → §3.6）

- **位置**：`08:468`："（**注意：这是设计建议，需先确认不违反"无依据自创禁止"——见 §3.5 待拍板项。**）"
- **实际**：待拍板项在 **§3.6**（`08:644`「3.6 待用户拍板的不确定项」）；§3.5 是"推荐排序与理由"。同文 `08:604` 已正确写"见 §3.6"
- **建议**：`:468` 的 §3.5 改为 §3.6

#### L6 · "DSH 探测只读 `id`" 属【推断】却写成事实

- **位置**：`08:280`（§1.7 表第 4 行"但 DSH 探测只读 `id`/`data`，收益有限"）、`08:468`（"DSH 探测只读 `id`，**零破坏**"）
- **实际**：DSH providers 页的探测节只说"探测读取的是常见网关公开的列表格式"；排错节只提到响应需含 **`data` 数组或 `models` 对象**。**未逐字段说明读取哪些字段**（逐字段清单 `id`/`display_name`/`description` 出现在 **Claude Code** 的 protocol 页，不是 DSH 页）
- **影响**：结论方向大概率正确（探测只取标识符），但证据级别应为【推断】。它被用来支撑"附加 `context_window` 字段零破坏"的设计建议，若 DSH 实际读取更多字段，该建议的前提会动摇
- **建议**：降级标注为【推断】，或改为"DSH 未公开探测的逐字段读取范围，需实测"

#### L7 · 08 附录 A3 描述把两件事并列

- **位置**：`08:663`（附录 A3）："…discovery 开关与 5 分钟缓存"
- **实际**：`llm-gateway-connect` 页的"5 分钟缓存"是 **`apiKeyHelper` 输出缓存**（`CLAUDE_CODE_API_KEY_HELPER_TTL_MS`，默认 5 分钟），与 model discovery **无关**。discovery 的缓存另有其说：结果缓存到 `~/.claude/cache/gateway-models.json`，"refreshed on each startup"
- **建议**：拆开写，或注明"5 分钟缓存指 `apiKeyHelper`"

#### L8 · 08 §2.1 未标注来源的量化估算 + "零序列化"简化

- **位置**：`08:25`（"Node/Python 运行时启动 100ms～1s 量级"）、`08:338`（"量级在**数百毫秒**"）、`08:25`/`:340`（"**零序列化、零 socket**"）
- **实际**：
  - 启动耗时估算**未给测量数据或来源**，属经验值；08 的证据分级体系里应归【推断】
  - "零序列化"是简化：进程内仍要做 SSE 解析、`StreamChunk` JS 对象构造、JSON 反序列化（07 §1.1 依据 3 的措辞更准确："HTTP 或 stdio 形态必须在边界上做序列化，这里完全没有"——指**边界**序列化）
- **影响**：08 自己在 `:346` 已诚实指出"③ 省下的只是本地一跳的开销…**不要为了延迟选 ③**"，方向无误
- **建议**：量化值标注【推断】；"零序列化"改为"无跨边界序列化"

#### L9 · 08 附录 A26 URL 形式 404

- **位置**：`08:686`（附录 A26）：`https://github.com/microsoft/vscode-extension-samples/blob/main/chat-model-provider-sample`
- **实际**：该 URL 返回 **404: Not Found**（GitHub 目录需用 `tree/` 而非 `blob/`）。改用 `tree/main/chat-model-provider-sample` 可正常打开，示例工程**确实存在**（含 `src/extension.ts`、`src/provider.ts`，演示 `LanguageModelChatProvider`）
- **说明**：该 URL 是 VS Code 官方文档**自身给出的链接**（原文 "You can get started with a [basic example project](https://github.com/microsoft/vscode-extension-samples/blob/main/chat-model-provider-sample)"），08 属忠实转抄
- **建议**：改为 `tree/` 形式，或注明"官方文档链接形式"

#### L10 · 08 §2.4 "Continue 有 `prompt_cache_key` 之类字段"无来源

- **位置**：`08:386`（§2.4 表"提示缓存"行）
- **实际**：该行的 Continue 断言**无来源链接**；我 WebFetch 了 `docs.continue.dev/customize/model-providers/top-level/openai`，该页**未出现** `prompt_cache_key`（Continue 的缓存相关字段在该页未涉及）。该行其余部分（DSH 侧 `docs/adding-a-new-provider.md:354`）已核实正确
- **建议**：补来源，或改为"各客户端缓存字段非标准、需逐个核实"

---

### 附：非 07/08 的问题（供参考，不计入）

- `AGENTS.md:865`（被 07/08 引用处）写"`startTraeLoginFlow` / `startCallbackServer`（`src/trae-oauth.ts`）里"，但 `startCallbackServer` 实际定义在 `src/login.ts:158`。这是**被引文档自身**的瑕疵，07/08 转述无误。

---

## 四、关键结论深核结果

### 4.1 07 的核心定性 —— ✅ **已核实正确**

**结论**："是宿主进程内形态，但不是本地 LLM 形态；准确术语为 DSH/Cordis 宿主进程内的原生 LLM Provider 插件"。

**5 条正向证据逐条复核**：

| # | 证据 | 复核结果 |
|---|---|---|
| 1 | 入口是 Cordis 插件，三个命名导出，无进程入口 | ✅ `src/index.ts:26` = `export const name = 'codearts-auth'`；`:34` = `export const inject = ['credentials','commands','llm']`；`:122` = `export function apply(ctx: Context): void {`。全仓 `export default` 仅 `vitest.config.ts:3` 与 `vitest.e2e.config.ts:3` —— **grep 实测完全一致** |
| 2 | 唯一暴露模型能力的方式是注册进宿主服务 | ✅ 5 组 `registerConfigurableProviders` + `registerAdapter` 全部命中（`llm-adapter.ts:1441/1445`、`buddy-adapter.ts:1451/1455`、`lobsterai-adapter.ts:1318/1322`、`qoder-adapter.ts:473/477`、`trae-adapter.ts:1380/1384`），行内容逐条吻合 |
| 3 | 推理接口是进程内异步迭代器 | ✅ `src/llm-adapter.ts:822` = `async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {`；`:1385` = `yield { type: 'finish', reason }` |
| 4 | 耦合面全是服务注入 | ✅ `src/index.ts:58`（`ctx.get('settings')`）、`src/account-pool.ts:146`、`src/index.ts:108`（`ctx.get('attachments')`）、`src/jet-hub-rpc.ts:521`（`ctx.inject(['connection'], …)`）、`plugin-src/client/index.js:8`（`export const inject = ['slots','connection']`）全部命中 |
| 5 | 生命周期错误会"打挂整个 DSH 宿主" | ✅ **逐字核实**。`AGENTS.md:863` = `### ⚠️ 本地回调服务器：listen 失败必须先注册 \`error\`，否则崩掉整个宿主`；`AGENTS.md:874` = `- 成为**进程级 unhandled error**，把**整个 DSH 宿主**打挂；`。这是仓库自述的**真实缺陷**（含用户报障、堆栈、修法三段），属【一手】。**同进程推断成立** |

**5 条反证逐条复核**：

| 反证 | 复核结果 |
|---|---|
| A · 不是自建 HTTP 服务 | ⚠️ **结论成立，但计数与表格有误**（见 M1）。`createServer` 确实**全部**是 OAuth 回调（`login.ts:170/287`、`lobsterai-oauth.ts:256`、`trae-oauth.ts:596/715`），三处 `listen` 均绑 `127.0.0.1`（`login.ts:219`、`lobsterai-oauth.ts:348`、`trae-oauth.ts:495`），全部命中 |
| B · `openai-compat.ts` 名字有欺骗性 | ✅ `src/openai-compat.ts:2` = `* OpenAI 兼容协议层的共享实现：消息序列化 + SSE 消费 + 错误归类。`；`:12` = `* 因此本模块把这部分抽出来给 **qoder 适配器**使用。` —— 方向是**消费**上游而非**提供**端点，判定正确 |
| C · 不是 CLI | ✅ `package.json` **无 `bin`**（grep 确认）；`spawn(` 全仓**仅 2 处**且都在 `openBrowser()`（`src/login.ts:125` Windows 分支、`:135` POSIX 分支）——07 说"全仓 `spawn` 只有一处"是**按 `spawn(cmd, [url])` 语义计**，两处同属一个函数，可接受；`README.md:46`/`:59` 确为宿主 CLI 命令；`:150/:151/:166/:183` 确为 `ctx.commands.register` |
| D · 不是 sidecar（仓库显式否决） | ✅ `docs/lobsterai-integration-plan.md:131` = `### 0.3 核心判断：不需要跑那个反代`；`:136` = `而本插件运行在 DSH 宿主进程内，\`ctx.llm.registerAdapter()\` **已经就是那一层**。`；`:140-141` = `所以推荐做法是：**把 \`lobsterai2api\` 的 Go 代码当作协议说明书，翻译成本插件的…` —— **逐字吻合** |
| E · 不是 MCP server | ✅ 全仓 grep `modelcontextprotocol|mcp`（大小写不敏感）**零命中**；`stdio` 仅出现在 `spawn` 的 `stdio: 'ignore'` 选项 |

**额外核实（07 对仓库自身文档失真的指认）**：

| 07 的指认 | 复核结果 |
|---|---|
| `AGENTS.md:121` 写 `ctx.llm.registerProvider()`，**该方法名在代码中不存在** | ✅ **正确**。`AGENTS.md:121` = `- LLM provider 通过 \`ctx.llm.registerProvider()\` 注册`；全仓 grep `registerProvider\b` **零命中**。实际是 `registerConfigurableProviders()` + `registerAdapter()` |
| `AGENTS.md:123` 写 `ctx.schema`，代码中无调用点 | ✅ **正确**。`AGENTS.md:123` 确有该句；全仓 grep `ctx.schema` **零命中** |
| `docs/adding-a-new-provider.md:8` 写"四个 LLM Provider"，实际 6 个 | ✅ **正确**。`:8` = `本插件已集成了四个 LLM Provider，属于**两种不同的架构脉系**：`；`:10-13` 表只列 buddy/workbuddy/lobsterai；`src/index.ts:131` 实为 6 个 namespace |
| `docs/adding-a-new-provider.md:338-346` 的 `LlmAdapter` 契约部分**准确** | ⚠️ **对仓库文档而言准确，但与官方基类口径不同**（见 M3） |

**07 其他已核实正确的定量断言**：

- 方法矩阵 30 个行号（5 适配器 × 6 方法）**全部命中**：`providerInfo` = `746/582/624/126/509`、`listModels` = `785/773/739/162/687`、`listAllModels` = `776/768/734/158/677`、`resolveModel` = `801/805/759/179/719`、`prepareCall` = `811/863/787/200/739`、`stream` = `822/874/808/211/750` ✅
- 客户端文件行数表（29/1079/181/84/67/42/45）✅ 逐项吻合（`build.mjs` 42 行亦确认）
- Jet Hub RPC "16 个方法" ✅ 逐个数出：account.list/create/update/delete/reorder/refresh/retest/retestAll/reset/resetAll、login.poll、credits.status/claimAll/balances、model.list/setDisabled = **16**
- `ctx.effect` 双注册（`src/index.ts:432-441` + `:445-452`，各调 6 个 `stop()`）✅；且 `:427` 的 effect 确实注册在 `pool.listAllAccounts().then(...)` 回调内部 ✅
- `resolveModel` 的 `context` 只在有值时赋值 ✅（`llm-adapter.ts:807`、`buddy-adapter.ts:818`、`trae-adapter.ts:730`、`qoder-adapter.ts:189` 逐条命中）
- `listAllModels` 是插件自定义、非基类方法 ✅（`src/jet-hub-rpc.ts:480-482` 注释直陈"DSH 的 `llm` 服务只保证 `listModels`"）

### 4.2 08 的决定性发现 —— ✅ **已核实正确（逐字级）**

**结论**："DSH 原生支持'添加自定义提供方'，因此对 DSH 不需要写插件。"

**亲自 WebFetch `https://deepseek-harness.github.io/deepseek-harness/guide/providers`（标题：配置模型 | DeepSeek Harness）**，逐项对照：

| 08 的断言 | 页面原文 | 判定 |
|---|---|---|
| ① 有"添加自定义提供方" | 「## 添加自定义提供方」整节存在："对于公司网关、自建服务器或已安装目录中不存在的提供方，选择**添加自定义提供方**。" | ✅ **逐字一致** |
| ② 填 Provider ID + 基础 URL + API 协议 + 凭据 + 模型 | "提供小写 Provider ID、基础 URL、API 协议、凭据和至少一个模型。" | ✅ **逐字一致** |
| ③ API 协议三选一含 `openai-completions` | "表单提供三种：`openai-completions` 对应 OpenAI Chat Completions，`openai-responses` 对应 OpenAI Responses API，`anthropic-messages` 对应 Anthropic Messages API。一个提供方只使用一种协议，网关同时提供两种时需要建两个提供方。" | ✅ **逐字一致** |
| ④ 探测调用 OpenAI 兼容 `GET /models` | "**获取可用模型返回 401**：检查密钥。模型发现会调用 OpenAI 兼容的 `GET /models` 端点；对于不提供该端点的服务，请手动输入模型。" | ✅ **逐字一致** |
| ④' 响应格式要求 | "**获取可用模型提示既没有 `data` 数组也没有 `models` 对象**：端点返回的列表格式不在探测的读取范围内。" | ✅ **逐字一致** |
| ⑤ 模型页只开放少数字段、其余在 `$DSH_HOME/settings.yaml` | "模型页只开放让一条路由得以存在的字段：API 密钥、显示名称、API 地址、API 协议，以及每个模型的 ID、显示名称、上下文窗口和最大输出 token 数。其余所有字段——推理等级、图片输入、请求兼容性开关、请求头、超时、重试策略——都在 `$DSH_HOME/settings.yaml` 中设置，也就是模型页写入的同一份文档。" | ✅ **逐字一致** |
| ⑥ `compat.supportsDeveloperRole` / `maxTokensField` / `thinkingFormat` | "声明了推理能力的模型，其系统提示词会以 `role: "developer"` 发出，很多网关直接拒绝；输出上限则写作 `max_completion_tokens`，只认 `max_tokens` 的服务端会拒绝。表单里没有这两个字段；请在 `$DSH_HOME/settings.yaml` 的路由上更正"（示例给出 `compat: supportsDeveloperRole: false` / `maxTokensField: max_tokens`）。"对于「不明确关闭就会思考」的模型——例如 OpenAI 兼容网关后面的 DeepSeek V4——需要 `compat.thinkingFormat: deepseek`：它让 `off` 发送 `thinking: {type: disabled}`" | ✅ **逐字一致** |
| ⑦ "已配置的提供方会出现在模型选择器中" | "已配置的提供方会出现在模型选择器中。选择模型也会将其设为新会话的默认值。" | ✅ **逐字一致** |
| ⑧ 图片"发送前被拒绝" | "手动输入的模型在自己声明之前一律按纯文本对待，因为没有任何环节能去询问端点接受哪些模态。给这类模型附加图片，会在发送前就被拒绝，并点名该模型。" | ✅ **逐字一致** |

**额外发现（08 未提但支持其结论）**：页面明确"网关并不提供推理能力的内置提供方模型"与"内置提供方一律由已安装目录作答，即使其 API 地址指向网关也是如此，要查看网关实际提供的模型，请通过自定义提供方探测"——进一步印证对 DSH 无需插件。

**结论：08 §1.7 的决定性发现完全成立，无任何夸大或转述失真。** 这是本次核验中质量最高的一节。

### 4.3 网关 compat 缺口 —— ✅ **断言正确，证据链已补全**

**问题**：网关是否处理 `role: "developer"` 与 `max_completion_tokens`？

**第一步：全仓 grep（排除 docs/）**

```
$ grep -rn "developer" model_gateway/ tests/ scripts/ config.example.yaml
[零命中]
$ grep -rn "max_completion_tokens" model_gateway/ tests/ scripts/
[零命中]
```

✅ **确认零命中**（`developer` 全仓仅出现在 `docs/research/*` 与 `README.md:15` 的英文 "individual developers" 中，与 role 无关）。

**第二步：源码证据链（`role: "developer"` 的完整命运）**

| 层 | 位置 | 对 `messages[].role` 做了什么 |
|---|---|---|
| **入站** | `model_gateway/api/openai_compat.py:104` | `body = await request.json()`；`:105` 仅校验 `isinstance(body, dict)` |
| **入站** | `:121-125` | `stream = bool(body.get("stream", False))`；`reasoning = lift_reasoning_from_body(body)`；`body.pop("model", None)`；`ir = IRRequest(..., body=body, reasoning=reasoning)` —— **`messages` 未被触碰** |
| **IR 层** | `model_gateway/core/ir.py:114-122` | `IRRequest.body: dict[str, Any]  # 原始请求体（model 已移除、推理字段已提升）` —— **纯容器**。`ir.py` 全文 grep `messages`/`role` **零命中** |
| **调度层** | `model_gateway/core/scheduler.py:223-232` | `_out_body()`：`body = dict(ir.body)` → 设 `model` → `apply_model_params()` → `merge_reasoning()`/`inject_reasoning_into_body()` —— **不触碰 `messages`** |
| **出站** | `model_gateway/adapters/openai_out.py:92-97` | `_prepare_body()`：`out = dict(body)` → 设 `model` → 条件性 `_convert_images_to_base64(out)` —— **不触碰 role** |
| **出站（唯一遍历 messages 处）** | `adapters/openai_out.py:66` | `for msg in body.get("messages", []) or []:` —— 只处理 `content[].image_url`（图片转 base64），**不读不改 `role`** |
| **统计（另一处遍历）** | `stats/aggregate.py:73` | `for m in body.get("messages", []) or []:` —— 只读 `content` 拼文本做本地 token 估算，**忽略 `role`** |

**结论（`role: "developer"`）**：**原样透传**。网关既**不归一**也不**报错**，`role: "developer"` 会**逐字转发给上游厂商**。08 的表述"我们**原样透传** body（`model_gateway/api/openai_compat.py:121-125` 只 pop `model`），`developer` 角色会被转发给上游" —— **✅ 已核实正确**。

> 一处措辞精度：`:121-125` 除 `pop("model")` 外还 pop 了 `reasoning_effort`/`thinking`（由 `lift_reasoning_from_body`），并在出站由 `inject_reasoning_into_body` 按三级合并**重新注入**。所以"只 pop `model`"略欠精确，但"其余原样透传"的语义**成立**（推理字段走的是等价往返，非丢弃）。

**结论（`max_completion_tokens`）**：**原样透传**，由上游决定是否接受。网关无任何键名映射。

> **补充发现（08 未提，建议纳入）**：`model_gateway/config/schemas.py:182` 允许管理员在 `models[].params` 里配置 `max_tokens`（校验为 ≥1 整数），`ir.py:58-70` 的 `apply_model_params()` 会**在客户端未给该键时注入**。因此若管理员配置了 `params.max_tokens`，而客户端发的是 `max_completion_tokens`，出站请求会**同时带 `max_tokens` 与 `max_completion_tokens` 两个字段**——这既不是"透传"也不是"归一"，而是一种**隐式的双写**。08 §3.6 item 1 讨论"是否允许双写归一"时，应说明该路径**已部分存在**（以配置形式），并评估其与上游的兼容性。

### 4.4 07 §0.2 用户判断的证实与修正 —— ✅ **已核实正确**

| 07 的结论 | 复核 |
|---|---|
| "不是 API 形态" ✅ 证实 | ✅ `/api/jet-hub` 确为 `connection.fetch.register({path: JET_HUB_API_PATH, ...})`（`src/jet-hub-rpc.ts:556`），`JET_HUB_API_PATH = '/api/jet-hub'`（`:95`），是**宿主** web 服务上的路由注册，非插件 `listen()` |
| "不是 CLI 形态" ✅ 证实 | ✅ 无 `bin`；`spawn` 仅用于 `openBrowser()` |
| "像是本地 LLM 形态" ⚠️ 方向对、措辞错 | ✅ 模型确实全在远端：`src/llm-adapter.ts:14` = `CHAT_API_BASE = 'https://snap-access.cn-north-4.myhuaweicloud.com/api/v2'`；`src/models.ts:8` = `OPENGW_GATEWAY_CONFIG_URL = 'https://opengw.developer.huaweicloud.com/api/v1/gateway/config'`；`src/models.ts:16` = `SNAP_MODEL_BUILTIN_URL = 'https://snap-access.cn-north-4.myhuaweicloud.com/v1/model/builtin'` |
| §8.4 "100% 人机管理流量，0% 模型推理流量" | ✅ 16 个 RPC 方法逐一核对，无一涉及对话补全；唯一交叉点 `model.list`（`:1181`→`:1189`）只读目录 |

---

## 五、外部来源逐条核对结果（08 附录 A · 28 条）

**全部 28 条均已亲自 WebFetch 打开。** 结果：

| # | URL | 可达 | 转述一致性 | 备注 |
|---|---|---|---|---|
| A1 | docs.claude.com/…/llm-gateway | ✅（→ code.claude.com/…/llm-gateway） | ✅ 逐字一致 | "Anthropic doesn't endorse, maintain, or audit third-party gateway products, and doesn't support routing Claude Code to non-Claude models through any gateway." ✅；"a developer's claude.ai subscription isn't used" ✅；"`ANTHROPIC_BASE_URL` is the variable that points Claude Code at the gateway." ✅ |
| A2 | code.claude.com/…/llm-gateway-protocol | ✅ | ✅ 一致 | 三种格式 ✅；`HEAD /api/hello` ✅；"Discovery applies only to the Anthropic Messages format." ✅；`GET /v1/models?limit=1000` / 3s 超时 / redirect 视为失败 ✅（均逐字）；**"Discovery is off by default…" 与 id 过滤器两句实在本页**（08 同时列了 A2+A3，归属可接受） |
| A3 | code.claude.com/…/llm-gateway-connect | ✅ | ✅ 基本一致 | `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_API_KEY`/`apiKeyHelper` 与头映射 ✅；discovery 开关 `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` ✅。**"Discovery is off by default…" 不在本页**（在 A2）；"5 分钟缓存"指 `apiKeyHelper`（见 L7） |
| A4 | code.claude.com/…/model-config | ✅ | ✅ 逐字一致 | `availableModels` = "Enterprise administrators can use `availableModels` in managed or policy settings to **restrict** which models users can select." ✅；`ANTHROPIC_CUSTOM_MODEL_OPTION` "add a single custom entry to the `/model` picker" + "skips validation" ✅；`ANTHROPIC_BASE_URL` "changes where requests are sent, not which model answers them." ✅ |
| A5 | code.claude.com/…/headless | ✅ | ✅ 逐字一致 | `--bare` 跳过清单 ✅；"recommended mode for scripted and SDK calls, and will become the default for `-p`" ✅；"bare mode doesn't use your subscription login" ✅；"never reads OAuth credentials or the system keychain" ✅；SIGTERM → 143 ✅；`--permission-prompts` 需 v2.1.259+ ✅ |
| A6 | docs.claude.com/…/mcp | ✅ | ✅ 一致 | MCP 定义 ✅；"dynamically update their available tools, prompts, and resources" ✅；"The SSE (Server-Sent Events) transport is deprecated." ✅；四传输 http/streamable-http/sse/stdio/ws ✅；**无模型注册机制** ✅（逐条核查确认） |
| A7 | code.claude.com/…/agent-sdk/overview | ✅ | ✅ 逐字一致 | SDK 定位 ✅；"A library that runs the Claude Code binary" ✅；"Anthropic does not allow third party developers to offer claude.ai login or rate limits…" ✅；Plugin = "Package skills, agents, hooks, and MCP servers, and load them by local path" ✅；品牌条款（允许 "Claude Agent" / "{YourAgentName} Powered by Claude"，禁止 "Claude Code"）✅ |
| A8 | docs.claude.com/en/api/openai-sdk | ✅ | ✅ 逐字一致 | "compatibility layer" ✅；`base_url="https://api.anthropic.com/v1/"` ✅；"primarily intended to test and compare model capabilities" ✅ |
| A9 | code.visualstudio.com/…/language-model | ✅ | ✅ 逐字一致 | 定位句 ✅；`selectChatModels({vendor,id,family,version})` ✅；**`LanguageModelChatProvider` / `registerChatModelProvider` 均未出现** ✅；chat participant 建议用 `request` 里的 model ✅ |
| A10 | code.visualstudio.com/…/language-model-chat-provider | ✅ | ✅ 逐字一致 | "contribute your own language models" ✅；"one-provider-to-many-models" ✅；注册两步 ✅；三方法 ✅；BYOK 策略 ✅ |
| A11 | cursor.com/help/models-and-usage/api-keys | ✅ | ✅ 逐字一致 | "You can add your own API keys…" ✅；五家 provider（OpenAI/Anthropic/Google/Azure OpenAI/AWS Bedrock）✅；"Custom API keys only work with chat models. Tab completion continues using Cursor's built-in models." ✅；ZDR 不适用 ✅；key 随每次请求发到 Cursor 后端 ✅ |
| A12 | cursor.com/docs/models | ✅（→ /docs/models-and-pricing） | ✅ 一致 | 确为 Models & Pricing 页，**无自定义端点内容** ✅ |
| A13 | agentclientprotocol.com/…/introduction | ✅ | ✅ 逐字一致 | ACP 定位 ✅；Local agents = 子进程 + JSON-RPC over stdio ✅；Remote = HTTP/WebSocket ✅；LSP 类比 ✅；**无"模型 provider"角色** ✅ |
| A14 | zed.dev/docs/ai/external-agents | ✅ | ✅ 逐字一致 | "External Agents run through their own process and provider relationship…" ✅；配置边界表 "Model/provider config → Usually owned by the External Agent" ✅、"Auth/API keys/subscriptions → Usually owned by the External Agent" ✅；keychain 凭据不同源 ✅；`agent_servers` 配 `command`+`args`（`pool acp`）✅ |
| A15 | docs.continue.dev/…/openai | ✅ | ✅ 逐字一致 | "If you are using an OpenAI API compatible providers, you can change the `apiBase` like this:" ✅；`provider: openai`/`model`/`apiBase`/`apiKey` ✅ |
| A16 | docs.cline.bot/…/openai-compatible | ✅ | ✅ 逐字一致 | "**Any other provider** that offers an OpenAI-compatible API endpoint." ✅；"**Base URL:** Enter the base URL provided by your chosen provider. **This is a crucial step.**" ✅ |
| A17 | docs.roocode.com/…/openai-compatible | ✅ | ✅ 逐字一致 | "Roo Code uses **native tool calling** exclusively." ✅；"the model you select **must** support OpenAI-compatible tool calling. If a model does not support native tool calling, it cannot be used with Roo Code." ✅ |
| A18 | github.com/cordiverse/cordis | ✅ | ✅ **逐字一致** | "A Meta-Framework of Spatiotemporal Composability." ✅；"**Cordis is under active development. The API is not yet stable and may change without notice.**" ✅ |
| A19 | deepseek-harness…/cordis-primer | ✅ | ✅ 逐字一致 | 五个核心概念全文 ✅；"每个注册都应有对应的 disposer（资源释放函数）：要么从 `ctx.effect()` 返回一个，要么使用 Cordis 提供的辅助方法自动处理。" ✅ |
| A20 | koishi.chat/zh-CN/guide/plugin/service | ✅ | ⚠️ 一处引文失真 | 服务定义 ✅；IoC/DI 表述 ✅；"直到此服务的值变为 truthy 为止，该插件的函数体不会被加载" ✅；"一旦此服务的值发生变化，该插件将立即回滚 (并非插件停用)" ✅；`required`/`optional` ✅；`ctx.inject()` 子插件 ✅；`immediate` + `start/stop/fork` ✅。**自定义服务示例签名失真**（见 L4） |
| A21 | deepseek-harness…/llm-streaming | ✅ | ✅ 一致 | "The only required method." ✅；`registerAdapter` 的 `DUPLICATE_ADAPTER` all-or-nothing ✅；"该目录仅供参考，不是请求白名单：适配器仍是权威，并可接受未列出的模型 id。" ✅；StreamChunk 封闭联合 + `assertNever` ✅（逐字）；"`usage` 在 `finish` 之前" ✅；工具参数保持原始 JSON 字符串 ✅；"一次适配器调用就是一次提供方尝试。适配器禁用库重试。" ✅ |
| A22 | deepseek-harness…/subsystems/core | ✅ | ✅ 逐字一致 | "循环搬运的对话词汇——`Message`、`ContentBlock`、`StreamChunk`、模型请求——由 `packages/llm` 声明，记录在 llm-streaming.md。" ✅（**正文归属见 L3**） |
| A23 | deepseek-harness…/guide/providers | ✅ | ✅ **全项逐字一致** | 见 §4.2（8 项断言全部命中） |
| A24 | deepseek-harness…/guide/quickstart | ✅ | ✅ 一致 | "打开**设置 → 模型**" ✅ |
| A25 | docs.litellm.ai/docs/proxy/quick_start | ✅ | ✅ 一致 | "**Unified Interface**: Calling 100+ LLMs … in the OpenAI `ChatCompletions` & `Completions` format" ✅；`POST /chat/completions` ✅；`GET /models` ✅ |
| A26 | github.com/…/blob/main/chat-model-provider-sample | ⚠️ **404** | ✅ 内容真实 | `blob/` 形式 404（GitHub 目录需 `tree/`）；示例工程**存在**，演示 `LanguageModelChatProvider`（见 L9） |
| A27 | segmentfault.com/a/1190000048204894 | ✅ | ✅ 一致 | 标题《Cursor 如何接入自定义模型：Override Base URL 完整配置与四类踩坑速查》，**确为二手**，确实讨论 Override Base URL |
| A28 | developer.aliyun.com/article/1762261 | ✅ | ✅ 一致 | **原文确有**"想在 Cursor 里接第三方渠道跑 Claude，唯一走得通的路径是 OpenAI 兼容协议 `/v1/chat/completions`" ✅——08 的"其中一条明确称…"归属正确 |

### 附：Cursor 官方文档"无自定义端点"结论的独立复核

08 §1.3 声称"以 `allowed_domains=["cursor.com"]` 检索 "override OpenAI base URL" → **未返回任何 cursor.com 官方页面**"。我**以同样方式独立复现**：

```
WebSearch: query="Cursor \"Override OpenAI Base URL\" official documentation custom model endpoint"
           allowed_domains=["cursor.com"]
→ 返回 5 条结果，全部为第三方站点（oschina / jishuzhan / segmentfault / bettertoken / 2048ai）
→ 无任何 cursor.com 官方页面
```

✅ **08 的【未找到】分级成立且有据**。同时 `cursor.com/help/models-and-usage/api-keys` 的"支持的 provider"节确实只列五家、无 Custom/Base URL 条目。

**外部来源总评**：28 条中 **27 条完全可达且转述一致**，1 条（A26）URL 形式 404 但内容真实。**无任何一条"打不开或内容不符"的严重问题。** 未发现把社区来源标成"一手"的分级失当：A27/A28 明确标【二手】并在正文中标注"仅二手，未在官方文档核实"。

---

## 六、遗漏与矛盾

### 6.1 文档内部矛盾

| # | 位置 | 矛盾内容 | 严重度 |
|---|---|---|---|
| 1 | `08:12` / `08:726` vs `08:796` | 同一 import 语句，两处写 `src/llm-adapter.ts:14`、一处写 `:10`（真相为 `:10`） | 🟠 见 M2 |
| 2 | `07:395`（"5 个适配器 × 6 个方法全部实现，无遗漏"）vs `07:406`（"实际 6 个 provider"） | 非矛盾：07 在 `:374` 已明确交代"**5 个类 → 6 个 provider**"（`BuddyAdapter` 实例化两次），三处口径自洽 | ✅ 无问题 |
| 3 | `07:211`（`docs/lobsterai-integration-plan.md:1290` 与 `:1299` 为文档侧确认） | 非矛盾：`:1290` 是代码块示例、`:1299` 是文字条目，07 已用"与"并列 | ✅ 无问题 |

**结论：仅 1 处内部矛盾（M2），且不影响任何结论。**

### 6.2 07 与 08 之间的交叉矛盾

| # | 事实点 | 07 的表述 | 08 的表述 | 判定 |
|---|---|---|---|---|
| 1 | `LlmAdapter` 必需方法 | 4 个"必须" + `prepareCall`"建议"（`07:386-395`） | "**The only required method.**"（仅 `stream()`）（`08:249`） | 🟠 **不一致**（M3）——08 与官方一致，07 与仓库文档一致 |
| 2 | 形态命名 | "宿主进程内原生 LLM Provider 插件"（`07:20`） | 同（`08:10`） | ✅ 一致 |
| 3 | "本地 LLM"措辞纠偏 | 纠正为"本地修饰适配器位置，非推理位置"（`07:151`） | 同，且"全文不使用'本地 LLM'这一措辞"（`08:13`） | ✅ 一致 |
| 4 | DSH 侧无可复用推理端点 | `07:1174` | `08:786`（引用 07） | ✅ 一致 |
| 5 | `AGENTS.md:863-876` 同进程证据 | `07:80` 引用 | `08:353` 引用 07 | ✅ 一致 |
| 6 | `src/llm-adapter.ts:14` 语义 | 指 CHAT_API_BASE（**正确**） | 指 `signRequestHuawei` import（**错误**） | 🟠 **不一致**（M2） |

**结论：2 处交叉不一致，均为行号/契约口径问题，不动摇形态定性。**

### 6.3 该覆盖却漏掉的关键问题

| # | 漏项 | 说明 | 建议 |
|---|---|---|---|
| 1 | **Trae / Cherry Studio 的 base_url 能力未调研** | `README.zh-CN.md:17` 点名的三大目标客户端中的两个，在 08 §3.4 路径 B 覆盖率表中缺席（见 M4） | 补两行（含【未找到】标注） |
| 2 | **`models[].params` 已可注入 `max_tokens`** | 见 §4.3 补充发现。这使 §3.6 item 1 的"双写归一"讨论不完整——该能力**以配置形式已存在**，且会产生"`max_tokens` + `max_completion_tokens` 并存"的出站体 | 在 §3.4 路径 E / §3.6 item 1 补充该交互 |
| 3 | **08 未回填 07 的开放不确定项** | 07 §11.1 列了 10 项"无源码"的不确定项，其中第 2 项（`ctx.llm` 完整方法集）、第 4 项（基类提供了哪些方法）已由 08 抓到的官方 llm-streaming 页**部分解答**（基类含 `providerInfo`/`providerRetryPolicy`/`imageRequestPricing`/`listModels`/`resolveModel`/`prepareCall`，注册返回 `AdapterRegistrationHandle`/`DirectoryRegistrationHandle`） | 08 可加一节"对 07 开放项的补充回答"，提升两文合力 |
| 4 | **08 未讨论 `developer` 角色归一后的语义风险** | 若把 `developer` 归一为 `system`，会改变多轮对话中 developer 消息的**位置语义**（OpenAI 的 `developer` 可穿插在对话中；Anthropic 侧文档也提到"System/developer messages are hoisted and concatenated to the beginning"）。08 §3.4 只列了"入站归一 `developer` → `system`"而未提示位置语义变化 | 在 §3.6 item 1 的风险列里补充 |

### 6.4 把【推断】写成"事实"的地方

| # | 位置 | 问题 | 严重度 |
|---|---|---|---|
| 1 | `08:280`、`08:468` | "DSH 探测只读 `id`" —— DSH 官方页未逐字段说明 | 🟡 L6 |
| 2 | `08:25`、`08:338` | 进程启动耗时量化值（100ms~1s / 数百毫秒）无来源 | 🟡 L8 |
| 3 | `08:67` | "原文明确：'本文档未列出该格式'" —— 伪引号 | 🟡 L2 |
| 4 | `08:386` | "Continue 有 `prompt_cache_key` 之类字段"无来源 | 🟡 L10 |

**分级失当检查**：**未发现**把社区来源标成"一手（官方）"的情况。A27/A28 明确标【二手】；【未找到】的四处（Cursor 自定义 base URL、Cursor 插件 API、MCP 模型注册、ACP 模型角色）均已独立复核成立。

### 6.5 08 "三形态对比"的逐维度论证完整性

08 §0.1 表列了 10 个维度，§2.1~§2.7 逐维度展开：

| 维度 | 是否给了理由 | 证据/来源 |
|---|---|---|
| 效率（延迟构成） | ✅ 给了（§2.1，含 ③ 的两跳/零跳分析） | 代码行号 + 量化估算（估算无来源，见 L8） |
| 效率（流式路径） | ✅ 给了 | DSH `AsyncIterable` 契约 |
| 稳定性（故障面） | ✅ 给了 | `AGENTS.md:863-876` 真实缺陷 |
| 稳定性（版本漂移） | ✅ 给了 | Cordis 自述 + DSH `assertNever` |
| 可移植性 | ✅ 给了 | N×1 vs N×M 矩阵 |
| 能力保真度 | ✅ 给了（7 项能力逐项列表 + 结论） | 含 Roo Code 硬要求、DSH 契约 |
| 合规（事实转述） | ✅ 给了（5 议题表，全为官方原文） | 明确"不给法律意见" |
| 实现成本（每接一宿主） | ✅ 给了（含 20 项最小接口清单） | 参考插件实测行数 |
| 维护成本（谁跟进） | ✅ 给了 | 变更来源 × 承担方矩阵 |
| 用户体验（模型出现在选择器） | ✅ 给了 | DSH 原文 + Claude Code 过滤器反例 |
| 用户体验（用户要填什么） | ✅ 给了 | 三形态对比 |

**结论：每个维度都给了理由，无"只给结论"的情况。** 08 附录 C 自检的这一项成立。

### 6.6 08 的"翻转条件"完整性

§3.5 给出 5 条翻转条件（宿主数量 / 是否支持自定义 base_url / 宿主产品立场 / 侵入性边界 / 外部依赖风险），并明确条件 5 为"DSH 未来关闭自定义提供方表单"的外部风险。**论证完整，且主动暴露了自身结论的外部依赖。** 这是加分项。

---

## 七、铁律冲突检查表（仅针对 08）

网关铁律：**纯本地运行 · 全明文配置 · 无远程更新 · 无依据自创禁止**

| # | 08 的建议 | 位置 | 判定 | 理由 |
|---|---|---|---|---|
| 1 | **主推 ① OpenAI 兼容 HTTP API**（唯一事实源） | §0.2、§3.5 P0 | ✅ **相容** | 端点已存在；不引入外部依赖、不改配置模型、不新增自创协议 |
| 2 | **把 ① 打磨到"零摩擦"**：文档给出各宿主 base_url 填法 | §3.5 P0 | ✅ **相容** | 纯文档工作 |
| 3 | **确认 `/v1/models` 能被 DSH 探测**（base URL 是否带 `/v1`），必要时加 `/models` 别名 | §3.4 路径 D、§3.5 P0 | ⚠️ **潜在冲突** | 新增 `/models` 路由属**新增对外接口**，落在"无依据自创禁止"的边界；08 已自标"先做文档，再评估是否加别名路由"，处理得当。**补充**：DSH 官方 YAML 示例已给出 `baseURL: https://gateway.example/v1`，带 `/v1` 是官方约定，别名路由的必要性因此下降 |
| 4 | **补齐 `tools`/`tool_calls` 完整透传保证** | §3.5 P1 | ✅ **相容** | 属"透传优先"的**加强**，与铁律同向 |
| 5 | **评估 `/v1/models` 附加 `context_window` 等非标准字段** | §3.1 理由 4、§3.5 P2 | ⚠️ **潜在冲突** | 属**协议自创**。08 **主动标注**"需先确认不违反'无依据自创禁止'"并列入 §3.6 待拍板。处理得当，**不构成翻案理由** |
| 6 | **网关侧归一 `developer` → `system`、`max_completion_tokens` → `max_tokens`** | §3.4 路径 E、§3.6 item 1 | ⚠️ **潜在冲突** | 与"透传优先"（`model_gateway/api/anthropic.py:3` 明示"透传优先，只做协议间必需的语义映射"）**直接冲突**；08 **主动标注**"与'无依据自创禁止'直接冲突…需要用户拍板"。处理得当。**补充风险**：`developer` 归一还涉及**消息位置语义**变化（见 §6.3 #4），风险高于 08 的描述 |
| 7 | **不主动做 ③ 插件**（三个条件同时成立才逐个评估） | §3.5 P3 | ✅ **相容** | 与"纯本地""克制立场"一致；08 §3.5 条件 4 明确"建议把'不写宿主插件'作为**默认立场**" |
| 8 | **② CLI 子进程：不实现** | §3.5 P4 | ✅ **相容** | 无新增依赖 |
| 9 | **③ 胖插件：否决** | §3.2、§3.5 ❌ | ✅ **相容** | 明确"违反单一事实源" |
| 10 | **③ 瘦插件（若做）**：插件只持网关令牌、无账号池/凭据存储 | §3.2 | ✅ **相容**（网关侧） | 网关侧配置模型不变；但 08 §2.5 已诚实指出 ③ 形态会**扩大凭据暴露面**（网关本地 + N 个宿主凭据库）。注意：DSH 的 `$DSH_HOME/.credentials.yaml` 是否满足"全明文"是**宿主侧**议题，不构成网关铁律违反 |
| 11 | **Cursor 暂不支持**（官方文档【未找到】自定义端点） | §3.4 路径 B、§3.6 item 4 | ✅ **相容** | 保守立场，且我已独立复现其检索结论 |
| 12 | **Claude Code 标注"实验性支持"待拍板** | §3.6 item 5 | ✅ **相容** | 不擅自承诺支持 |
| 13 | **MCP 桥接：明确不推荐用于模型接入** | §3.4 路径 C | ✅ **相容** | 避免引入嵌套 LLM 调用 |
| 14 | **是否新增 `/models` 别名路由** | §3.6 item 3 | ⚠️ **潜在冲突**（同 #3） | 已自标待拍板 |
| 15 | **"实验性支持"的文档措辞** | §3.6 item 6 | ✅ **相容** | 只给事实不给结论 |

**汇总**：✅ 相容 **11** 项 · ⚠️ 潜在冲突 **4** 项 · 🔴 需翻案 **0** 项。

**4 项 ⚠️ 全部被 08 自己标注为"待用户拍板"或"需先确认"**，说明 08 对铁律边界有自觉。**无需翻案的建议。**

> 唯一建议加强的一处：⚠️ #6 的风险描述应补上"`developer` 归一为 `system` 会改变消息位置语义（OpenAI 的 developer 消息可穿插对话，system 语义更受限）"，使拍板信息更完整。

---

## 八、已核实正确的结论清单

以下是**经独立复核确认正确**的关键结论，可直接采信：

### 07 文档

1. ✅ **核心定性**：DSH 插件是"宿主进程内原生 LLM Provider 插件"，**不是**本地 LLM 形态（模型全在远端）。5 条正向证据 + 5 条反证全部成立（反证 A 计数有误但结论成立）
2. ✅ **同进程最强证据**：`AGENTS.md:874` 的"打挂整个 DSH 宿主"逐字属实，且为仓库自述的真实缺陷
3. ✅ **不是 API / CLI / sidecar / MCP**：四条否定全部有据（`createServer` 仅 OAuth、无 `bin`、`spawn` 仅开浏览器、仓库显式否决反代、零 MCP 实现）
4. ✅ **`package.json` 无 `bin` 字段**（grep 确认）
5. ✅ **`createServer` 全部是 OAuth 回调、全部绑 `127.0.0.1`**（计数有误，结论正确）
6. ✅ **`AGENTS.md:121` 的 `ctx.llm.registerProvider()` 方法名不存在**（全仓零命中 `registerProvider\b`）——07 对仓库文档失真的指认**正确**
7. ✅ **`AGENTS.md:123` 的 `ctx.schema` 无代码调用点**（全仓零命中）
8. ✅ **`docs/adding-a-new-provider.md` provider 计数过期**（文档写 4，实际 6）
9. ✅ **5 个适配器类 → 6 个 provider 路由**（`BuddyAdapter` 实例化两次）
10. ✅ **方法矩阵 30 个行号全部命中**；`listAllModels` 确为插件自定义、非基类方法
11. ✅ **`ctx.llm` 只被用到 2 个注册方法 + 1 个读取路径**；07 对"无法给出完整方法集"的诚实声明成立
12. ✅ **Jet Hub RPC 16 个方法、100% 管理流量、唯一交叉点 `model.list` 只读目录**
13. ✅ **`/api/jet-hub` 是宿主 web 服务上的路由注册，非插件自建服务器**
14. ✅ **客户端 bundle 不参与推理**
15. ✅ **客户端文件行数表（29/1079/181/84/67/42/45）逐项吻合**

### 08 文档

16. ✅ **DSH 原生支持"添加自定义提供方"** —— 8 项断言**全部逐字核实**（`openai-completions` 三选一、探测 `GET /models`、`data` 数组、模型页字段清单、三个 compat 开关原文）
17. ✅ **因此对 DSH 不需要写插件** —— 结论成立
18. ✅ **网关 compat 缺口断言正确**：`role: "developer"` 与 `max_completion_tokens` 在网关代码中**零命中**，且**原样透传**给上游（已给出完整源码证据链，见 §4.3）
19. ✅ **`/v1/models` 返回 `data` 数组，字段为 `id`/`object`/`created`/`owned_by`/`endpoint`/`group`**（无上下文窗口）
20. ✅ **网关已有 OpenAI + Anthropic 双入站面**（`openai_compat.py:36`/`:101`、`anthropic.py:316`）
21. ✅ **网关"透传优先"原则**（`anthropic.py:3` 原文）
22. ✅ **Claude Code 只接受三种格式、不支持非 Claude 模型、discovery 只留 `claude`/`anthropic`** —— 全部逐字核实
23. ✅ **`availableModels` 是收紧语义、`ANTHROPIC_CUSTOM_MODEL_OPTION` 是单条手动加**
24. ✅ **VS Code 是真正的"宿主原生 Provider 插件"样板**（`LanguageModelChatProvider` + 三方法 + `contributes.languageModelChatProviders`）
25. ✅ **ACP 是 editor↔agent 协议，不是模型接入协议；无"模型 provider"角色**
26. ✅ **Continue / Cline / Roo Code 均为纯 ① 形态**（`apiBase` / Base URL）；Roo Code 硬要求 native tool calling
27. ✅ **Cordis "The API is not yet stable and may change without notice."** 逐字属实；Koishi 的 `inject` 语义逐字属实
28. ✅ **DSH `StreamChunk` 是封闭可辨识联合、以 `assertNever` 结尾**（版本漂移风险论证成立）
29. ✅ **Cursor 官方文档确实未记载自定义 base URL** —— 我独立复现了 08 的检索（`allowed_domains=["cursor.com"]` 零官方命中）
30. ✅ **OpenAI 兼容是当前最通用的互操作层，但第一方 Agent/编辑器宿主倾向自有协议** —— 正反例表全部有据
31. ✅ **三形态对比每个维度都给了理由**（§2.1~§2.7 逐维度含结论+理由+证据）
32. ✅ **推荐排序与 5 条翻转条件完整，且主动暴露外部依赖风险**
33. ✅ **合规部分只做事实转述**（§2.5 全为官方原文，未给法律意见）
34. ✅ **对 Cursor 的处理（【未找到】+ 二手明确标注）分级诚实**

---

## 九、总体可信度评级

| 文档 | 评级 | 说明 |
|---|---|---|
| **07** | **A-（可信，可直接用于决策）** | 391 条引用零失效、零越界；核心定性（同进程原生 Provider 插件、非本地 LLM）**完全成立**；对仓库自身文档失真的指认（`AGENTS.md:121`/`:123`）**全部正确**——这是难得的自检质量。扣分项：`createServer` 计数错（M1，中等）、"必须 4 方法"与官方口径不一致（M3，中等）、`exports` 计数（轻微） |
| **08** | **A（可信，质量最高的是外部来源核验）** | 28 条外部 URL **全部亲自打开、27 条完全一致**；决定性发现（DSH 原生自定义提供方）**8 项断言全部逐字核实**；compat 缺口断言经我补全源码链后**成立**；三形态对比逐维度给理由；推荐含翻转条件且主动暴露外部依赖；铁律冲突**零翻案**、4 项 ⚠️ 全部自标待拍板。扣分项：`llm-adapter.ts:14` 内容错配 + 内部矛盾（M2，中等）、遗漏 Trae/Cherry Studio（M4，中等）、若干【推断】写成事实（轻微） |
| **两文交叉** | **A-** | 2 处交叉不一致（M2 行号、M3 契约口径），均不动摇任何核心结论 |

### 结论

- **错误总数：14 条**（严重 **0** / 中等 **4** / 轻微 **10**）
- **没有任何一条核心结论被证伪。** 两文的技术选型建议（主推 ①、DSH 不需要插件、② 不实现、③ 仅选择性补充且只做瘦插件）**证据充分、方向正确、可支撑架构决策**。
- **最高风险点不是结论错误，而是 M3 的契约口径不一致**：07 说 4 个方法"必须"、08 说仅 `stream()` 必需。若有人按 07 的清单评估工作量，会高估插件成本（4 个方法 vs 1 个 abstract）；若按 08 的实现，则低估（其余方法虽非 abstract，但有默认实现不代表能省）。建议两文统一口径后再作为选型依据。
- **4 条中等问题的修订成本都很低**（改计数、改 2 处行号、补表头、补 2 行表格），建议**在进入架构决策前完成修订**。
- 参考仓只读约束已遵守（`git status` 干净，HEAD 未变）。
