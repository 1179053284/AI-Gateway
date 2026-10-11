# 核验报告：DSH 调研草稿 01 / 02

> 审计员角色：严格证伪。目标不是确认草稿「大体正确」，而是**逐条回溯源码**，找出错误、行号偏差、过度推断与编造。
> 被核验对象：
> - `docs/research/drafts/01-dsh-授权接入与模型转接.md`（1222 行）
> - `docs/research/drafts/02-dsh-签到与自动领取机制.md`（916 行）
>
> 源码基准（**只读，未修改任何文件**）：`/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts/`
> 核验日期：2026-09-22
> 核验方法：① 脚本化机械校验（提取全部 `路径:行号` 引用，比对文件存在性 / 行号范围 / 内容吻合度）；② 人工精读关键结论；③ 遗漏与矛盾检查。

---

## 一、总体结论

### 1.1 可信度评级

| 草稿 | 可信度 | 说明 |
|---|---|---|
| **01 · 授权接入与模型转接** | **B+（良）** | 架构结论、机制描述、绝大多数 `file:line` 经得起回溯。**引用纪律基本可靠**（`src/oauth.ts` 专用性、`RefreshScheduler`、账号池无租约、限流解析等核心结论全部核实为真）。失分点集中在**元数据与计数**（行数、字段数、参数个数、适配器个数）以及**一处引用块伪造源码片段**。未发现无中生有的机制。 |
| **02 · 签到与自动领取机制** | **B（良-）** | 协议细节的字段级描述**准确度很高**（四套签到协议、幂等矩阵、错误分类顺序、限流标记语义全部核实为真），且对「未验证」的标注诚实。失分点是**引用格式系统性错误**：多处把 `A 文件的实现` 与 `B 文件的行号` 拼在同一个引用串里（作者虽以 `of AGENTS.md` / `of jet-hub-rpc.ts` 标注了真实来源，但正文的 `路径:行号` 是错的），另有若干计数错误。 |

**两份草稿都没有出现「编造不存在的机制」这类致命错误。** 所有被抽查的机制级结论都能在源码中找到对应实现。主要问题属于**引用精度**与**计数准确性**。

### 1.2 错误密度统计表

**第一遍：机械校验（脚本，`/tmp/verify_refs2.py`）**

| 指标 | 数值 |
|---|---|
| 提取到的 `路径:行号` 引用总数 | **1027** |
| 引用文件不存在 | **0** |
| 行号越界（超出文件行数） | **10**（其中 **4** 为真实错误，**6** 为脚本归属误判，详见 §1.3） |
| 引用路径与行号归属不匹配（张冠李戴） | **4** |
| 内容不吻合（行号处内容与草稿描述无关） | **0** |
| 使用简写文件名（靠 basename 解析成功） | 23 |

**第二 / 三遍：人工精读**

| 类别 | 草稿 01 | 草稿 02 | 合计 |
|---|---|---|---|
| 严重错误（伪造引用 / 行号张冠李戴） | 1 | 4 | **5** |
| 中等错误（事实、计数、参数个数不符） | 5 | 3 | **8** |
| 轻微错误（行区间边界、弱引用、措辞不一致） | 3 | 4 | **7** |
| 草稿内部矛盾 | 2 | 2 | **4** |
| 过度推断（把推断写成事实） | 1 | 1 | **2** |

### 1.3 关于「10 处行号越界」的重要澄清

机械校验报出的 10 处越界中，**只有 4 处是草稿的真实错误**。另外 6 处是**脚本的归属误判**（不是草稿的错）：

草稿在同一段落里先提到文件 A，随后用**裸行号**（`:NNN-MMM`）引用当前章节的主题文件 B。脚本把裸行号归属到了最近出现的文件名 A，从而误报越界。经人工回溯，这 6 处裸行号的**真实归属与行号都是正确的**：

| 草稿位置 | 脚本误判归属 | 真实归属 | 核验结果 |
|---|---|---|---|
| `[02:294]` `:309-319,372-401,441-463` | `account-probe.ts` | `src/jet-hub-rpc.ts` | ✅ 正确（三个 `collect*` 的 try 块） |
| `[02:295]` `:282-283,328-330,415-417` | `account-probe.ts` | `src/jet-hub-rpc.ts` | ✅ 正确（「包含已停用账号」注释） |
| `[02:297]` `:248-259,367,378-393` | `account-probe.ts` | `src/jet-hub-rpc.ts` | ✅ 正确（`precheckStatus`） |
| `[02:299]` `:260-276` | `account-probe.ts` | `src/jet-hub-rpc.ts` | ✅ 正确（`fetcher` 注入说明） |
| `[02:527]` `:157-159` | `trae-errors.ts` | `src/lobsterai-errors.ts` | ✅ 正确（`recordsLobsteraiRateLimit`） |
| `[02:528]` `:169-171` | `trae-errors.ts` | `src/lobsterai-errors.ts` | ✅ 正确（`isLobsteraiTerminalError`） |

同理，草稿 01 的 `[01:702/703/705]`（`docs/adding-a-new-provider.md:...`）、`[01:709/713/714/715/716]`（`AGENTS.md:...`）、`[01:556]`（`src/qoder-adapter.ts:41-49`）、`[01:398]`（`src/lobsterai-auth.ts:8-12`）等看似「归属错误」的项，经逐条回溯后**内容与行号全部正确**，只是裸行号的归属需读者自行判断（见 §2.3 的「可读性」说明）。

**结论：机械校验的 96 个「可疑项」中，绝大多数是启发式假阳性；真实错误为 §2 所列的 20 条。**

---

## 二、必须修正的错误清单（按严重度排序）

### S1 · 严重：行号张冠李戴（4 处，全部在草稿 02）

这 4 处的共同特征是：**正文写的是「A 文件的实现」，但行号取自 B 文件**。作者在括号里用 `of AGENTS.md` / `of jet-hub-rpc.ts` 标注了真实来源，说明**作者知道真实来源**，但正文的 `路径:行号` 写错了。读者照着行号去 A 文件会**直接越界或读到无关内容**。

#### 错误 1 — `[02:130]`

- **草稿原文位置**：草稿 02 第 130 行
  > **三个实测字段坑**（`src/codearts-credits.ts:180-204,262-279,1172-1177` of AGENTS.md）：
- **源码真实情况**：`src/codearts-credits.ts` 共 **655 行**（`wc -l`），**不存在 1172-1177**。
  - `:180-204` ✅ 正确（`CodeArtsOpsActivity` 接口：`campaignId` 为数字的注释在 `:183`、`status` 可能为 `null` 在 `:195`、`benefitAmount` 在 `:200`）
  - `:262-279` ✅ 正确（`readIdentifier`）
  - `:1172-1177` ❌ 真实来源是 **`AGENTS.md:1174-1176`**（「`campaignId` 是数字」「可领积分字段是 `benefitAmount`」「不可领取的活动 `status` 是 `null`」三条）
- **修正建议**：拆成两个引用：``（`src/codearts-credits.ts:180-204`、`:262-279`；`AGENTS.md:1174-1176`）``。不要在一个引用串里混两个文件的路径。

#### 错误 2 — `[02:216]`

- **草稿原文位置**：草稿 02 第 216 行
  > ⚠️ **claim 对「今天已签到」是幂等的**：实测重复领取同样返回 `{code:0,message:"success"}`，与真正成功**无法区分**（`src/trae-credits.ts:1042-1049` of jet-hub-rpc.ts）。
- **源码真实情况**：`src/trae-credits.ts` 共 **382 行**，**不存在 1042-1049**。真实来源是 **`src/jet-hub-rpc.ts:1039-1055`**，原文：
  > `// TRAE 的 claim 对「今天已签到」是**幂等**的：实测重复领取同样返回`
  > `// \`{code:0, message:"success"}\`，与真正领取成功**无法区分**。`
- **修正建议**：改为 `（\`src/jet-hub-rpc.ts:1039-1055\`）`。

#### 错误 3 — `[02:218]`

- **草稿原文位置**：草稿 02 第 218 行
  > **网络重试与业务失败严格分开**（`src/trae-credits.ts:236-255,962-963` of AGENTS.md）：只对 `httpStatus === 0`（传输层失败）重试，间隔 1s，`retryCount = 3`
- **源码真实情况**：
  - `:236-255` ✅ 正确（`claimTraeDailyCheckin` 内的 `doClaim` 重试循环：`if (result.httpStatus > 0) return lastError` 在 `:247-249`、`setTimeout(..., 1000)` 在 `:251`、`retryCount = 3` 默认值在 `:233`）
  - `:962-963` ❌ 真实来源是 **`AGENTS.md:961-964`**（「网络异常与业务失败必须分开」）
- **修正建议**：``（`src/trae-credits.ts:233-255`；`AGENTS.md:961-964`）``

#### 错误 4 — `[02:235]`

- **草稿原文位置**：草稿 02 第 235 行
  > ⚠️ **必须带 `require_usage: true`**：……（`src/trae-credits.ts:1220` of AGENTS.md）。
- **源码真实情况**：`src/trae-credits.ts` 仅 382 行，**不存在 1220**。真实来源是 **`AGENTS.md:1220`**（`⚠️ **必须带 \`require_usage: true\`**：不带时上游不返回 \`usage\` 明细……`）。代码侧对应位置是 `src/trae-credits.ts:314`（body 构造）与 `:347-350`（`usage.credits_amount` 读取）。
- **修正建议**：改为 `（\`AGENTS.md:1220\`；代码见 \`src/trae-credits.ts:314,347-350\`）`。

---

### S2 · 中等：事实 / 计数 / 引文错误（8 条）

#### 错误 5 — `[01:151]` 「三个适配器」与实际不符，且列举漏项

- **草稿原文位置**：草稿 01 第 151 行
  > 三个适配器都写了同款（`src/llm-adapter.ts:811-820`、`src/lobsterai-adapter.ts:793`、`src/qoder-adapter.ts:200-209`、`src/trae-adapter.ts:745`）。
- **源码真实情况**：`prepareCall` 在 **5 个适配器**中全部存在：`src/llm-adapter.ts:811`（CodeArts）、`src/buddy-adapter.ts:863`（Buddy/WorkBuddy）、`src/lobsterai-adapter.ts:787`、`src/qoder-adapter.ts:200`、`src/trae-adapter.ts:739`。
  - 句子说「三个」，却列了 4 个引用；
  - 且**漏掉了 `src/buddy-adapter.ts:863`**——而该文件正是本句前半段（`:856-860`）用来解释 shim 出处的那个文件。
  - `src/lobsterai-adapter.ts:793` 与 `src/trae-adapter.ts:745` 指向的是方法体内部行（`model: await this.resolveModel(...)`），不是方法定义行（分别为 `:787` / `:739`）。
- **修正建议**：改为「五个适配器都写了同款（`src/llm-adapter.ts:811`、`src/buddy-adapter.ts:863`、`src/lobsterai-adapter.ts:787`、`src/qoder-adapter.ts:200`、`src/trae-adapter.ts:739`）」。

#### 错误 6 — `[01:1218]` `AGENTS.md` 行数错误，且与草稿自身引用自相矛盾

- **草稿原文位置**：草稿 01 第 1218 行（参考文档索引）
  > | `AGENTS.md` | 969 行 | 缺陷复盘大全。§「续期不得按 enabled 过滤」（:136-154）、§「两步式登录」（:1082-1111）、§「同名模型消歧」（:400-430）、§「TRAE 协议要点」（:502-1022） |
- **源码真实情况**：`wc -l AGENTS.md` = **1260 行**（非 969）。
  - **草稿自身矛盾**：同一份草稿第 659 行引用 `AGENTS.md:1256`（「X-Domain 必须跟随产品」章节），第 912 行（草稿 02）引用 `AGENTS.md:1256-1260`。**1256 > 969**，行数与自引用不可能同时成立。
- **修正建议**：改为「1260 行」。

#### 错误 7 — `[01:287]` / `[01:1078]` TRAE 登录 URL 参数个数错误

- **草稿原文位置**：草稿 01 第 287 行「**登录 URL 是完整的 17 参数集**」；第 1078 行「TRAE 17 参数登录 URL」。
- **源码真实情况**：`src/trae-oauth.ts:105-125` 的 `URLSearchParams` 共 **18 个**键：
  `login_version` / `auth_from` / `login_channel` / `plugin_version` / `auth_type` / `client_id` / `redirect` / `login_trace_id` / `auth_callback_url` / `machine_id` / `device_id` / `x_device_id` / `x_machine_id` / `x_device_brand` / `x_device_type` / `x_os_version` / `x_app_version` / `x_app_type`。
  草稿自己在第 289-296 行列出的清单也是 **18 项**（与正文的「17」矛盾）。
- **修正建议**：两处均改为「18 参数」。

#### 错误 8 — `[01:106-109]` 产品接口「字段数」列多处偏差

- **草稿原文位置**：草稿 01 第 106-109 行的表格列「字段数」
- **源码真实情况**：

| 接口 | 草稿称 | 实际 | 证据 |
|---|---|---|---|
| `BuddyProduct` | ~17 | **15** | `src/product.ts:74-149` |
| `LobsteraiProduct` | 10 | **10** ✅ | `src/lobsterai-product.ts:136-157` |
| `QoderProduct` | 14 | **12** | `src/qoder-product.ts:126-205` |
| `TraeProduct` | 19 | **22** | `src/trae-product.ts:51-152` |

- **修正建议**：核实后改为实际值，或统一加「约」并注明「含可选字段」。

#### 错误 9 — `[02:547]` `trae-errors.ts` 类别数错误

- **草稿原文位置**：草稿 02 第 547 行
  > **`trae-errors.ts`** 同构，7 类：`none` / `hard-plan`(1005) / `soft-rate`(429 或 4011) / `session-dead`(401) / `quota-exceeded`(4008) / `not-found`(404) / `server` / `client`
- **源码真实情况**：`TraeErrorKind`（`src/trae-errors.ts:23-39`）共 **8 个**成员：`none`、`hard-plan`、`soft-rate`、`session-dead`、`quota-exceeded`、`not-found`、`server`、`client`。草稿列出的也正是 8 个，只是数字写成了 7。
  - 对照：`LobsteraiErrorKind`（`src/lobsterai-errors.ts:28-42`）才是 **7 个**（无 `quota-exceeded`）。草稿 02 第 525 行对 lobsterai 写的「7 类」是正确的。
- **修正建议**：改为「8 类」。

#### 错误 10 — `[02:207]` TRAE 状态字段描述不准确

- **草稿原文位置**：草稿 02 第 207 行
  > 其余字段（`streak_days` 等）如实置 0/空，不臆造。
- **源码真实情况**：`src/trae-credits.ts:196-208` 中 `streakDays` 与 `totalCredits` **是从响应体读取的**，不是置 0：
  ```ts
  streakDays: readNumber(body, 'streak_days') || 0,
  totalCredits: readNumber(body, 'total_credits') || 0,
  ```
  真正「置 0/空」的是 `todayCredit: 0` / `isStreakDay: false` / `checkinDates: []` / `activityName: ''` / `themeName: ''` / `endTime: ''`。
- **修正建议**：改为「`streak_days` / `total_credits` 有则读、无则 0；`today_credit` / `is_streak_day` / `checkin_dates` / `activity_name` / `theme_name` / `end_time` 如实置 0/空，不臆造」。

#### 错误 11 — `[02:265]` `ClaimOutcome` 复用范围多算 1 个 provider

- **草稿原文位置**：草稿 02 第 265 行
  > | `ClaimOutcome` | `src/credits.ts:90-94` | **全部 5 个有签到能力的 provider** |
- **源码真实情况**：按草稿 02 自己第 369-376 行的能力矩阵，`dailyCheckin` 为 `true` 的只有 **4 个**（`codearts` / `buddy` / `lobsterai` / `trae`）；`workbuddy` 与 `qoder` 均为 `false`。故应为 **4 个**。
- **修正建议**：改为「全部 4 个有签到能力的 provider（buddy / codearts / lobsterai / trae）」。

#### 错误 12 — `[01:474-475]` 引用块中夹带源码不存在的代码片段（**引文完整性问题**）

- **草稿原文位置**：草稿 01 第 474-475 行
  > `src/account-pool.ts:548-557` 记录了为什么**不要**重新引入「按限流重置时间重排」：
  > > 早期实现有 `candidates.sort((a,b) => resetAtA - resetAtB)`，它会让手动顺序形同虚设 —— ……
- **源码真实情况**：`src/account-pool.ts:548-557` 的注释原文是：
  > `// 候选顺序即**用户在 Jet Hub 拖拽设定的手动顺序**（\`reorderAccounts\` 写入）。`
  > `//`
  > `// 为什么不再按「限流重置时间最早到期」重排（早期实现如此）：`
  > `// 那个排序会让手动顺序形同虚设 —— 用户把某账号拖到首位，只要另一个`
  > `// 账号的限流重置时间更早，实际选中的仍是后者，拖拽变成纯 UI 装饰。`
  > `// 现在的语义是「手动顺序优先，限流豁免」……`
  - 注释中**只以散文描述**「早期实现如此」，**没有任何 `sort(...)` 代码片段**。
  - 全文件 grep `sort` / `resetAtA` / `resetAtB` **零命中**——`src/account-pool.ts` 中不存在任何排序调用。
  - 草稿用 `>` 引用块呈现，形式上等同于「引用源码原文」，但插入的 `candidates.sort((a,b) => resetAtA - resetAtB)` 在源码中不存在（也无法在 git 历史外验证）。语义结论（不该重引入排序）**是对的**，但**引用形式不诚实**。
- **修正建议**：改为「源码注释描述了早期实现曾按重置时间重排（未保留具体代码）」，或直接把引用块改为对注释的转述，去掉反引号包裹的伪代码。

---

### S3 · 轻微：行区间边界、弱引用与措辞（7 条）

#### 错误 13 — `[01:14]` / `[01:921]` `src/account-pool.ts:19` 是弱引用

- **草稿原文位置**：草稿 01 第 14 行与第 921 行，用 `src/account-pool.ts:19` 支撑「**凭据与账号索引分离**是核心设计」。
- **源码真实情况**：`src/account-pool.ts:19` 只有 `export const JET_HUB_NS = 'jet-hub'`——它能支撑「账号索引走 settings 的 jet-hub namespace」，但**不能**支撑「凭据与账号索引分离」。支撑该结论的是 `src/account-pool.ts:114-115`（`ctx.settings` / `ctx.credentials` 分工）与 `:313-317`（`addAccount` 只写索引、不写凭据）。
- **修正建议**：把 `src/account-pool.ts:19` 换成 `src/account-pool.ts:114-115`（草稿 02 第 867 行用的正是这个引用，是对的）。

#### 错误 14 — `[01:398]` 裸行号的归属易被误读

- **草稿原文位置**：草稿 01 第 396 行末以 `src/lobsterai-auth.ts:60-70` 结束，紧接着第 398 行
  > **异常网络判定**（`:8-12`）：`/fetch failed|ENOTFOUND|ECONNREFUSED|proxy|unresolved host|getaddrinfo/i`
- **源码真实情况**：`:8-12` 的真实归属是 **`src/refresh.ts:8-12`**（本小节的标题即 `### 3.2 \`RefreshScheduler\`（\`src/refresh.ts\`）`），内容与草稿一致 ✅。但紧邻的上一句刚提到另一个文件，读者极易误归到 `lobsterai-auth.ts`。
- **修正建议**：补全为 `src/refresh.ts:8-12`。

#### 错误 15 — `[02:197]` 行区间未覆盖表格第三行

- **草稿原文位置**：草稿 02 第 197 行，`src/trae.ts:288-309` 支撑「设备身份是每账号一套、稳定派生」表（三行：`X-Device-Id` / `X-Market-User-Id` / `Vscode-Sessionid`）。
- **源码真实情况**：`deriveDeviceId15` 在 `:296`、`deriveMarketUserId` 在 `:303`、**`deriveSessionId` 在 `:314-322`**（超出 309）。
- **修正建议**：改为 `src/trae.ts:288-322`。

#### 错误 16 — `[02:71]` 常量引用区间不足

- **草稿原文位置**：草稿 02 第 71 行「code ∈ {1002, 1003} → inactive // 常量定义见 :57-59」
- **源码真实情况**：`1001` 在 `:59`、`1002`（`CODE_NO_QUALIFICATION`）在 `:60`、`1003`（`CODE_ACTIVITY_ENDED`）在 `:61`。`:57-59` 覆盖不到 1002/1003。
- **修正建议**：改为 `:57-61`。

#### 错误 17 — `[01:1217]` `docs/adding-a-new-provider.md` 行数

- **草稿原文位置**：草稿 01 第 1217 行「561 行」
- **源码真实情况**：`wc -l` = **560 行**。
- **修正建议**：改为 560（或加「约」）。

#### 错误 18 — `[02:525]` 「三个策略函数」与表格 4 行不符

- **草稿原文位置**：草稿 02 第 525 行「**`lobsterai-errors.ts` 的三个策略函数**：」后接 4 行表格（`classifyLobsteraiError` / `shouldRotateLobsteraiAccount` / `recordsLobsteraiRateLimit` / `isLobsteraiTerminalError`）。
- **源码真实情况**：4 个函数确实都在（`:100-117` / `:139-141` / `:157-159` / `:169-171`）✅，只是「三个」与表格行数不一致。
- **修正建议**：改为「三个策略函数 + 一个分类函数」，或把表格首行拆出。

#### 错误 19 — `[02:11]` 与 `[02:264-267]` 类型计数不一致

- **草稿原文位置**：草稿 02 第 11 行「只有**三个共享的数据类型**（`ClaimOutcome` / `CheckinStatus` / `CreditBalance`）」；第 264-267 行的表列出 **4 个**共享项（含 `CreditPackage`）。
- **源码真实情况**：`CreditPackage` 确实被 5 个 `*-credits.ts` 共同复用（如 `src/qoder-credits.ts:38` 与 `src/lobsterai-credits.ts:34` 均导入）。第 11 行漏了它。
- **修正建议**：第 11 行补上 `CreditPackage`。

#### 错误 20 — `[02:18]` 「轮换上限 3」的过度概括

- **草稿原文位置**：草稿 02 第 18 行（结论先行）
  > **轮换上限 3 个账号**（含首个），对齐 Go 的 `MaxRotate`；……
- **源码真实情况**：显式上限只存在于两处：`LOBSTERAI_MAX_ROTATE = 3`（`src/lobsterai-adapter.ts:90`，循环 `maxRotate = 3 - 1 = 2`，`:951`）与 `TRAE_MAX_ROTATE = 3`（`src/trae-adapter.ts:133`）。**buddy（`src/buddy-adapter.ts:1046` 的 `for (;;)`）与 codearts（`src/llm-adapter.ts:991` 的 `rateLimitTried` 集合）没有显式次数上限**，靠「每个账号只试一次」收敛。
  - 草稿 02 第 493-498 行的表格已正确区分这一点，因此是**结论先行段落的过度概括**。
- **修正建议**：改为「lobsterai / trae 轮换上限 3 个账号（含首个）；buddy / codearts 无显式上限，靠 `tried` 集合保证每账号只试一次」。

---

## 三、已核实正确的关键结论清单

以下为**逐条回溯源码后确认无误**的核心结论（均给出源码证据）：

### 3.1 架构与授权（草稿 01）

| 结论 | 源码证据 | 核验 |
|---|---|---|
| `src/oauth.ts` **完全**是 CodeArts 专用，不是通用抽象 | `CLIENT_ID='codearts-agent'`（`:6`）、`REDIRECT_PATH='/oauth/callback'`（`:8`）、`STS_TOKEN_ENDPOINT='sts.cn-north-4.myhuaweicloud.com/v1/oauth2/tokens'`（`:10`）、导入 `CodeArtsCredential`（`:3`）、错误文案 `CodeArts token request...`（`:122`） | ✅ |
| 五个平台是**五套互不复用的协议** | codearts：`src/login.ts:393`（本地回调+PKCE+DPoP）；buddy：`src/buddy-oauth.ts:137,178,231`（external-link-v2 轮询）；lobsterai：`src/lobsterai-oauth.ts:232`（本地回调 + `:130` authCode 换 token）；qoder：`src/qoder-oauth.ts:119,205`（设备码轮询，不起监听端口，`:4-9`）；trae：`src/trae-oauth.ts:99,273,365,583`（本地回调直传 token + `ExchangeToken`） | ✅ |
| 凭据本体走 `ctx.credentials`、账号索引走 `ctx.settings` 的 `jet-hub` namespace | `src/account-pool.ts:19`（`JET_HUB_NS`）、`:114-115`、`:313-317`；`src/service.ts:145`、`src/buddy-auth.ts:148`（`ctx.credentials.set`） | ✅ |
| **账号池无租约机制**，并发请求会拿到同一账号 | `src/account-pool.ts:532-592` 全文无 in-flight 标记/互斥；只有 `enabled` 过滤（`:538`）、模型级限流过滤（`:540-546`）、`excludeAccountIds`（`:539`） | ✅ |
| `RefreshScheduler` 的 generation 代号防「僵尸调度」 | `src/refresh.ts:43-114`；`arm()`/`stop()` 均 `generation++` | ✅ |
| 失效判定是**结构化**（`error.name` + 正则）而非 `instanceof` | `src/refresh.ts:14-25`；原因注释在 `:16-20`（跨模块同名类 identity 不同） | ✅ |
| `refresh()` 与 `refreshAccountCredential()` 分工，`refresh` 回调必须刷「解析时那个账号」 | `src/index.ts:297-313`（lobsterai 完整原因说明）、`:344-357`（qoder）、`:383-387`（trae） | ✅ |
| `refreshAll` 与调度器启动判据**只看 `refreshable`，不看 `enabled`** | `src/index.ts:423-428`（`accounts.some(a => a.refreshable)`）、`:424-426`（早期缺陷复盘） | ✅ |
| 两步式登录：先返回 `loginUrl`、先写占位条目、失败删占位 | `src/jet-hub-rpc.ts:636-646`（占位）、`:665`（立即返回）、`:648-659`（后台回填）、`:660-664`（失败 `removeAccount`） | ✅ |
| `ref` 命名 `{PROVIDER}_ACCOUNT_{8位大写hex}` | `src/jet-hub-rpc.ts:615-617`；`shortId()` 为 8 位 hex（`:99-104`） | ✅ |
| `findAccountIdByCredential`：非 codearts 取 `access_token`，codearts 取 `access_key_id` | `src/account-pool.ts:417-429`（`identifierKey` 在 `:421`） | ✅ |
| 选号顺序 = 手动拖拽顺序，**不**按限流重置时间重排 | `src/account-pool.ts:548-557` | ✅ |
| `excludeAccountIds` 必须在池层排除 | `src/account-pool.ts:521-530` | ✅ |
| 黑名单制（未记录默认打开） | `src/account-pool.ts:21-28` | ✅ |
| `listModels` 与 `listAllModels` 分离 | 5 个适配器均有 `listAllModels`（`src/llm-adapter.ts:776`、`src/buddy-adapter.ts:768`、`src/lobsterai-adapter.ts:734`、`src/qoder-adapter.ts:158`、`src/trae-adapter.ts:677`） | ✅ |
| CodeArts 双端点合并 + `normalizeModelId` 去日期后缀 + VL 过滤 + 磁盘缓存路径 | `src/models.ts:120-165`（双端点）、`:41-49`（normalize）、`:55-58`（VL）、`:18-19`（`codearts_models.json`）、`:25`（2 小时） | ✅ |
| 限流解析：`6004` 优先 + 中英双语正则兜底 + 捕获真实时区 | `src/llm-adapter.ts:1457`（`6004`）、`:1475-1476`（双语正则）、`:1485-1494`（只认顶层 `code`）、`:1510`（`RESET_TIME_PATTERN`）、`:1513-1537`（fallback 1 小时） | ✅ |
| 本插件**不对外暴露推理 HTTP 端点**，唯一 HTTP 端点是 Jet Hub 管理面 | `src/llm-adapter.ts:1440-1449`（`registerConfigurableProviders` + `registerAdapter`）、`src/jet-hub-rpc.ts:95`（`/api/jet-hub`）、`:556-601` | ✅ |
| RPC 端点共 **16 个** | `handleMethod` 的 case 分支：`:606,612,797,803,811,835,894,909,920,927,933,954,1007,1078,1181,1247` = 16 | ✅ |
| `sse.ts` 四个共享工具的行号 | `readWithIdleTimeout` `:26-57`、`resolveToolPairing` `:91-123`、`normalizeToolArguments` `:125-138`、`isTruncatedArguments` `:158-167` | ✅ |
| `prepareCall` 是兼容 0.1.0-rc.6 基类缺失的 shim | `src/buddy-adapter.ts:857-861`（「兼容 0.1.1-rc.2……本仓库链接的 dsh-llm 副本（0.1.0-rc.6）」）——**版本号引用准确** | ✅ |
| LobsterAI 两个能力头的作用 | `src/lobsterai-product.ts:100-117`（`kimi-k3-agentic-v1` → 25 个模型无 `kimi-k3`；`thinking-level-control-v1` → `reasoning_effort:"off"` 否则 500）、`src/lobsterai.ts:464-468` | ✅ |
| 包名 `dsh-codearts-auth` | `package.json` | ✅ |

### 3.2 签到 / 探活 / 轮换（草稿 02）

| 结论 | 源码证据 | 核验 |
|---|---|---|
| **签到无任何自动调度**；唯一定时器是续期（30 min）与模型刷新（2 h） | grep `setInterval`：`src/index.ts:430`（续期）、`src/service.ts:355`（模型）、`plugin-src/client/jet-hub.js:727`（登录轮询）；`src/` 内无 `cron`、无签到定时器 | ✅ |
| **本地不持久化「今天领没领」** | grep `lastCheckin` / `claimedDate` / `lastClaim` / `checkinRecord`：唯一命中是 `docs/lobsterai-integration-plan.md:1314` 的**建议** `lastCheckinAttemptMs`（未实现） | ✅ |
| **TRAE claim 对「已签到」幂等但与成功不可区分** | `src/jet-hub-rpc.ts:1039-1055`（注释 + `precheckStatus` 默认 true，不传 false）、`AGENTS.md:951-957`；`src/trae-credits.ts:280-296`（`code===0` 时补查 status） | ✅ |
| 四套签到协议的步骤数与端点 | buddy 两步（`src/credits.ts:33,35`）；codearts 四步（`src/codearts-credits.ts:82,84,86,88`，`claim`→`confirm` 在 `:614-616`）；lobsterai 三步（`src/lobsterai-credits.ts:36,38,40`）；trae 两步（`src/trae.ts:59,61,63`） | ✅ |
| buddy 幂等靠服务端业务码 `10001`（兼容 `1001`），重复领是 HTTP 400 | `src/credits.ts:9-20`（文件头注释）、`:57-61`（常量）、`:345-347`（判定） | ✅ |
| buddy 必须用 `checkin-activity-status`、不需要 `X-Device-Token` | `src/credits.ts:11-21` | ✅ |
| buddy 余额 `data.Response.Data.Accounts[]` 双层嵌套；用 `CycleCapacityRemain` 而非 `TotalDosage` | `src/credits.ts:436-437`、`:419`、`:154-156`；`PACKAGE_STATUS_EXPIRED = 3` 在 `:393`、判定在 `:414` | ✅ |
| codearts 认证是签名而非 Cookie；`Agent-Type`/`X-Language` **必须签名后追加** | `src/codearts-credits.ts:33-43`、`:113-133`、`:340-348`（实测 `401 APIG.0301`） | ✅ |
| codearts `campaignId` 是数字（需 `readIdentifier`）、可领积分字段是 `benefitAmount`、`status` 可为 `null` | `src/codearts-credits.ts:183`、`:200`、`:195`、`:274-279` | ✅ |
| codearts 无 credit metric 时返回 `undefined`（≠ `total:0`） | `src/codearts-credits.ts:169-175`、`:387-388`、`:425` | ✅ |
| lobsterai 幂等靠**客户端** `idempotencyKey`(UUID4) + 两步预检 | `src/lobsterai-credits.ts:21-27`、`:267` | ✅ |
| lobsterai 判定顺序 7 步 | `src/lobsterai-credits.ts:223-233`（注释）与 `:234-295`（实现） | ✅ |
| lobsterai 槽位查询的 `platform=win32` 是伪装客户端形态 | `src/lobsterai-credits.ts:42-52` | ✅ |
| lobsterai 余额用 `profile-summary` 而非 `quota`；`total===0 && packages.length===0 → null`；负数 clamp | `src/lobsterai-credits.ts:297-305`、`:354-356`、`:350-353,357-360` | ✅ |
| trae 设备身份每账号确定性派生（15 位数字 + UUID v4 + 64 hex） | `src/trae.ts:296`（`deriveDeviceId15`）、`:303`（`deriveMarketUserId`，置 v4/variant 位）、`:314`（`deriveSessionId`） | ✅ |
| trae `readClaimCode` 兼容字符串 `"9074"` | `src/trae-credits.ts:121-132` | ✅ |
| trae 9074 → `failed` + `BusinessError` + `cooldownSecs:300`，不再换设备号 | `src/trae-credits.ts:265-276` | ✅ |
| trae claim 响应不含积分数，须补查 status | `src/trae-credits.ts:281-296`（实测 `{"code":0,"message":"success"}`） | ✅ |
| trae `require_usage: true` 必须带 | `AGENTS.md:1220`；`src/trae-credits.ts:314,347-350` | ✅ |
| trae 签到错误分类 8 档（1005→43200s、429→60s、401→-1、404→60s、5xx→600s、4xx→600s、业务码→300s、无码→0） | `src/trae-credits.ts:74-100` | ✅ |
| trae `traeCheckinDeviceGeneration` 链路**已废弃但未清理**（`claimTraeDailyCheckin` 接收 `generation`/`onRotate` 但不用） | `src/trae-credits.ts:230-231`（形参）与函数体（无引用）；`src/jet-hub-rpc.ts:1055-1056`（仍在传）；`AGENTS.md:965-967` | ✅ **作者这条发现很到位** |
| qoder **无签到能力**（`campaigns` 端点只在注释里） | `src/qoder-credits.ts:31-36`；grep `campaigns` 仅命中注释/文档，无实现 | ✅ |
| qoder 余额需读 `addOnQuota`；`displayMode==='enterprise'` → `null` | `src/qoder-credits.ts:27-29`、`:150` | ✅ |
| qoder 用量端点**不需要 WASM 签名** | `src/qoder-credits.ts:6-8` | ✅ |
| 三态语义「查不到 ≠ 为 0」 | `src/credits.ts:432-434`、`src/lobsterai-credits.ts:354-356`、`src/codearts-credits.ts:387-388`、`src/qoder-credits.ts:174-176` | ✅ |
| `CreditsEndpointDeps` 泛型化 + `precheckStatus` 语义 + `fetcher` 必须经 deps 注入 | `src/jet-hub-rpc.ts:217-277`（`:230` claim 签名声明为 `(credential, product, entry)`；`:264-270` 记录 `TypeError: fetcher is not a function` 真实缺陷） | ✅ |
| `computeClaimSummary` 的编译期穷尽性检查 | `src/jet-hub-rpc.ts:171-203`（`const exhaustive: never = outcome` 在 `:193`） | ✅ |
| `credits.status` 对 codearts / lobsterai / trae **如实返回 `null`** | `src/jet-hub-rpc.ts:956-969`（codearts）、`:970-982`（lobsterai）、`:983-993`（trae）、`:994-1003`（buddy 默认） | ✅ |
| `sweepExpiredRateLimits` **无生产调用方**（死代码） | 定义在 `src/account-pool.ts:622`；唯一调用是 `tests/unit/account-pool.spec.ts:190` | ✅ |
| 探活（retest）**不传 accountPool**、`refresh` 设 no-op | `src/account-probe.ts:115-120`、`:138` | ✅ |
| 探活凭据解析走 `resolveCredentialForAccount`（**不检查 enabled**） | `src/account-probe.ts:182`、`src/account-pool.ts:453-469` | ✅ |
| 探活提示语 `'只回答两个字：收到'`、超时 120s | `src/account-probe.ts:51`、`:61` | ✅ |
| 探活适配器按产品选择（buddy 系 / lobsterai / 其余 codearts） | `src/account-probe.ts:131-154`（含历史缺陷注释 `:127-130`） | ✅ |
| 探活顺序执行（避免触发真正想验证的限流） | `src/account-probe.ts:228-233`、`:241-243` | ✅ |
| lobsterai 换号上限「减 1」的理由 | `src/lobsterai-adapter.ts:947-951`（`maxRotate = LOBSTERAI_MAX_ROTATE - 1`） | ✅ |
| 必须把 `tried` 传给池，否则换号形同虚设 | `src/lobsterai-adapter.ts:973-979`；`src/buddy-adapter.ts:1058-1063` | ✅ |
| codearts 是唯一**不传** `tried` 的实现（只传 2 参） | `src/llm-adapter.ts:990`（`getAvailableAccount('codearts', options.model)`），靠调用方 `rateLimitTried.has` 兜底（`:991`） | ✅ |
| `status`/`kind`/`errorText` 必须**成组更新** | `src/lobsterai-adapter.ts:922-932`（初始化）、`:989-996`（循环内覆盖） | ✅ |
| `lobsterai-errors.ts` 判定顺序（402 → hard 关键词 → session-dead → 429 → 404 → ≥500 → ≥400 → none） | `src/lobsterai-errors.ts:78-95`（注释）、`:100-117`（实现） | ✅ |
| `recordsLobsteraiRateLimit` 三类、`isLobsteraiTerminalError` 一类 | `src/lobsterai-errors.ts:157-159`、`:169-171` | ✅ |
| trae **4008 必须排在 4011 之前** | `src/trae-errors.ts:90-98` | ✅ |
| `recordsTraeRateLimit` 四类 | `src/trae-errors.ts:148-150` | ✅ |
| 签到能力矩阵硬编码、默认关闭、门控在发请求之前 | `plugin-src/client/credits-capabilities.js:54-65`、`:73-84`、`:48-50`；`plugin-src/client/jet-hub.js:585,647` | ✅ |
| 能力矩阵改动须同步 `PROVIDERS`（单测锁死） | `AGENTS.md:1254`；`tests/unit/credits-capabilities.spec.ts` | ✅ |
| `docs/lobsterai-integration-plan.md` 的「签到没有定时任务」与「自动签到建议（未实现）」 | `:1301`、`:1303-1317`；参考实现定时任务在 `:180`、`:199` | ✅ |
| `README.md` 的 `credits.status` 无前端消费者 | `README.md:476-478` | ✅ |

### 3.3 关于测试引用

草稿 02 §6 引用的测试文件行号**全部正确**（抽查）：`tests/unit/rate-limit-parser.spec.ts:23-102`、`tests/unit/lobsterai-rotation-exhaustion.spec.ts:41-111`、`tests/unit/lobsterai-rotation-realpool.spec.ts:85-105`、`tests/unit/jet-hub-rpc.spec.ts:228-272`、`tests/unit/account-probe-adapter.spec.ts:68-87`、`tests/unit/account-probe.spec.ts:73-208`、`tests/unit/trae-errors.spec.ts`。

---

## 四、遗漏与矛盾

### 4.1 草稿内部矛盾

| # | 矛盾点 | 说明 |
|---|---|---|
| C1 | **草稿 01：`AGENTS.md` 行数 vs 自引用** | 第 1218 行称「969 行」，但第 659 行引用 `AGENTS.md:1256`、草稿 02 第 912 行引用 `AGENTS.md:1256-1260`。1256 > 969。（见 §2 错误 6） |
| C2 | **草稿 01：TRAE 参数个数 vs 自列清单** | 第 287 行称「17 参数集」，第 289-296 行自己列了 18 项。（见 §2 错误 7） |
| C3 | **草稿 01：「三个适配器」vs 列举 4 个文件** | 第 151 行。且实际有 5 个适配器。（见 §2 错误 5） |
| C4 | **草稿 02：类型计数** | 第 11 行「三个共享数据类型」，§2.1 表列 4 个（含 `CreditPackage`）。（见 §2 错误 19） |
| C5 | **草稿 02：能力/复用计数** | 第 265 行「全部 5 个有签到能力的 provider」，但第 369-376 行自己的能力矩阵只有 4 个 `dailyCheckin: true`。（见 §2 错误 11） |
| C6 | **草稿 02：「7 类」vs 列出 8 项** | 第 547 行。（见 §2 错误 9） |

> 注：C1/C2/C6 是**同一类失误**——正文的「计数词」与紧随其后的「枚举清单」不一致。建议在定稿前统一做一遍「数字 vs 清单」的交叉检查。

### 4.2 覆盖缺口（该覆盖但未覆盖 / 覆盖不足）

| # | 缺口 | 影响评估 |
|---|---|---|
| G1 | **`src/lobsterai-auth.ts`（603 行）未逐行核验** | 草稿 01 第 404 行只以文件名（无行号）提到它的 `refreshAll`。该文件是 5 个 auth 服务中最大者，草稿 02 §3.5 也只覆盖了 `refresh.ts`。**中等影响**：LobsterAI 续期链路的完整实现未被审计。 |
| G2 | **`src/qoder-auth.ts`（481 行）/ `src/trae-auth.ts`（546 行）未精读** | 草稿 01 第 1202 行**已明确标注「未逐行精读」**——属**诚实披露**，非隐瞒。**低影响**。 |
| G3 | **`docs/lobsterai-review-findings.md`（344 行）未读** | 草稿 01 第 1222 行标注「未读」；草稿 02 第 916 行引用了 `:26-180`（S1-S4）。**低影响**：草稿 02 实际用了它，草稿 01 没用。 |
| G4 | **`plugin-src/client/` 其余模块未覆盖** | 草稿 01/02 覆盖了 `index.js`、`management-rpc.mjs`、`jet-hub.js`、`credits-capabilities.js`、`build.mjs`；但**未提及 `account-order.js`（3014 B）与 `jet-hub-styles.js`（16505 B）**。**低影响**（与调研主题弱相关），但「管理面」章节声称覆盖客户端侧时宜说明范围。 |
| G5 | **`docs/trae-integration-plan.md`（256 行）仅在草稿 02 §6.5 以行号索引形式引用**，未在正文展开 | 草稿 01 第 1221 行只写「TRAE 的集成方案」。**低影响**。 |
| G6 | **`docs/lobsterai-integration-plan.md`（1728 行）**：草稿 02 引用充分（§6.5 列了 7 个引用点），草稿 01 只在索引里提了一行。**低影响**。 |
| G7 | **`src/buddy.ts`（910 行）的解析函数（`parseTokenData` / `parseModelsFromConfig` / `parsePromotions`）未逐行核验** | 草稿 01 第 1206 行**已披露**。**低影响**。 |
| G8 | **`findAccountIdByCredential` 会跳过已停用账号（`:423` 的 `!entry.enabled`）**，草稿 01 第 354 行描述该函数时未提及 | 这是一个**语义细节遗漏**：该方法本身按 `enabled` 过滤，与「续期不看 enabled」「探活不看 enabled」形成对比。**低影响**，但值得补一句，因为它与草稿反复强调的「enabled 语义边界」直接相关。 |

### 4.3 过度推断（把推断写成事实）

| # | 位置 | 问题 | 修正 |
|---|---|---|---|
| I1 | 草稿 01 第 474-475 行 | 用引用块呈现 `candidates.sort((a,b) => resetAtA - resetAtB)`，暗示其为源码原文。**源码中不存在任何 `sort`**。（见 §2 错误 12） | 改为转述，或明确标注「早期实现的具体写法未保留」 |
| I2 | 草稿 02 第 18 行 | 「轮换上限 3 个账号（含首个）」写成**通用结论**，实际只适用于 lobsterai / trae。（见 §2 错误 20） | 限定适用范围 |

> **正面评价（仍需记录）**：草稿 02 §5「未验证 / 存疑」的 10 条（U1-U10）质量很高，特别是 U5（TRAE 设备代次链路已废弃但未清理）与 U6（qoder 无签到仅基于单账号实测）——这两条都是**主动暴露自身证据边界**，是本次两份草稿中最好的调研纪律体现。草稿 01 §「未验证 / 存疑事项」的 9 条同样如实（含「未评估法律与合规风险」）。

---

## 五、无法核实的条目

以下条目**我无法从代码或仓库内文档确证**，既不能判为正确也不能判为错误：

| # | 条目 | 草稿位置 | 为何无法核实 |
|---|---|---|---|
| V1 | `ctx.credentials` 的物理存储位置与加密算法 | 01:1201 | 本仓库只调用宿主 API（`set`/`resolve`/`describe`/`unset`），未实现存储。`AGENTS.md:120` 与 `docs/adding-a-new-provider.md:81` 只说是「加密存储」，`src/buddy.ts:229-241` 提到落盘为 `.credentials.yaml`。**需查 DSH 宿主仓库**。 |
| V2 | qoder 加密推理的 WASM 调用约定与请求体字段结构 | 01:1203 | `AGENTS.md:26` 明确要求先读**不入库**的 `docs/qoder-encryption-notes.md`——该文件不在仓库中。`src/qoder-wasm.ts`（613 行）未精读。 |
| V3 | `trae` 的 `channelFor(model)` 通道归属映射算法 | 01:1204 | 只看到 `src/trae-adapter.ts:557` 的方法签名与 `src/trae-product.ts:88-102` 的 `channels` 说明，未读实现。 |
| V4 | 各平台「活动重置时间」的时区 / 整点规律 | 02:755（U7） | 全仓库**没有任何**声明或推断重置时区的代码。唯一日期语义是服务端下发的 `end_time` / `cycle_end_time` 字符串，仅作展示。**必须自行实测**。 |
| V5 | buddy / workbuddy 是否真的完全不需要 `X-Device-Token` | 02:749（U1） | 代码注释声称「实测三种请求头组合全部 200」（`src/credits.ts:15-17`），且有单测断言不发送该头（`tests/unit/credits.spec.ts:161-172`）。但**注释所引用的实测本身无法在仓库内验证**。 |
| V6 | `CODE_ALREADY_CLAIMED_ALT = 1001` / `1002` / `1003` 是否为真实服务端取值 | 02:750（U2） | 源码注释明确写着这是「静态分析列出的备选码表」（`src/credits.ts:58`），**非实测值**。 |
| V7 | codearts 的 `.com` → `.cn` 域名回退分支的可达性 | 02:751（U3） | 源码明确写「刻意不照搬，理由是无法在本机实测」（`src/codearts-credits.ts:74-78`）。 |
| V8 | `benefitAmount` 是否出现在 claim 响应里 | 02:752（U4） | 源码取值链把 `benefitAmount` 排首位，理由是「大概率同源」（`src/codearts-credits.ts:628-632`）——**这是推测**，作者已用「大概率」标注。 |
| V9 | qoder 是否**完全**没有签到能力 | 02:754（U6） | 依据是**某一个账号**的 `campaigns` 返回 `claimable:false`（`src/qoder-credits.ts:33-35`）+ 逆向未发现动作端点。其他账号/时段未验证。 |
| V10 | `lobsterai` / `trae` 的 `MAX_ROTATE=3` 在真实多账号池下的表现 | 02:758（U10） | 有单测覆盖（`tests/unit/lobsterai-rotation-realpool.spec.ts:85-105`），但用的是**替身池**。 |
| V11 | 草稿 01 第 934 行引用的 `src/jet-hub-rpc.ts:1197-1214`「完整缺陷复盘」 | 01:934 | 该区间内容为 `model.list` 的 `listAllModels` 使用说明（`:1205-1216`），与「缺陷复盘」的措辞强度不完全匹配；但结论（管理面必须用 `listAllModels`）正确。**无法判定是引用偏差还是措辞夸张**。 |
| V12 | 草稿 01 第 106 行 `BuddyProduct` 的「~17 字段」 | 01:106 | 实际可数出 15 个字段，但「~」使该数字具备模糊性；无法确定作者的计数口径（是否含注释中提到的迁移字段）。 |

---

## 六、核验方法与可复现性说明

1. **脚本化机械校验**：临时脚本置于 `/tmp/`（`verify_refs.py`、`verify_refs2.py`、`suspect.py`），**未写入项目目录**，**未修改任何源码或草稿文件**。
2. **核验基准**：`/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts/` 工作区快照（文件 mtime 均为 2026-09-21 14:34）。
3. **已核验文件行数（`wc -l`，用于判定越界）**：

   | 文件 | 行数 | 文件 | 行数 |
   |---|---|---|---|
   | `src/oauth.ts` | 196 | `src/jet-hub-rpc.ts` | 1275 |
   | `src/account-pool.ts` | 672 | `src/login.ts` | 437 |
   | `src/refresh.ts` | 114 | `src/buddy.ts` | 910 |
   | `src/credits.ts` | 490 | `src/buddy-oauth.ts` | 589 |
   | `src/trae-credits.ts` | 382 | `src/models.ts` | 223 |
   | `src/lobsterai-credits.ts` | 372 | `src/llm-adapter.ts` | 1537 |
   | `src/codearts-credits.ts` | **655** | `src/trae.ts` | 1714 |
   | `src/qoder-credits.ts` | 187 | `src/qoder.ts` | 342 |
   | `src/lobsterai-errors.ts` | 171 | `src/types.ts` | 377 |
   | `src/trae-errors.ts` | 157 | `src/index.ts` | 471 |
   | `src/account-probe.ts` | 272 | `src/sse.ts` | 167 |
   | `AGENTS.md` | **1260** | `src/openai-compat.ts` | 554 |

4. **未做的事**（明确声明）：未运行测试套件；未执行插件；未访问网络；未评估法律与合规风险（与草稿 01 的自我声明一致）。

---

## 七、给作者的修订优先级建议

1. **先修 4 处行号张冠李戴（§2 错误 1-4）**——这是读者会**照着行号翻错页**的错误，成本最低、收益最高。
2. **再修引文完整性问题（§2 错误 12）**——把引用块里的伪代码改为转述。这条关系到调研报告最核心的资产：**「我说的话能不能被逐字回溯」**。
3. **统一做一遍「数字 vs 清单」交叉检查**（§4.1 的 C1-C6）——6 处矛盾里 4 处是同一类失误。
4. **补 G1（`src/lobsterai-auth.ts`）**——5 个 auth 服务中唯一未审计的一个，而草稿 01 §1.2 正好以它为例讲解 `refresh` 分工。
5. 其余轻微项（§2 错误 13-20）可在终稿一次性清理。

**整体判断：这两份草稿是可信的工程考古成果，机制层面的结论几乎全部经得起回溯；失分几乎全部集中在「引用的机械精度」上。修完上述 5 项后，可提升至 A- 级别。**
