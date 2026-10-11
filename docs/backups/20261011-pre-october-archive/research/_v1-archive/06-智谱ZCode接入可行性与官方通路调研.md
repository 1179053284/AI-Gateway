# 智谱（Z.ai / BigModel）接入可行性与官方通路调研

> 调研日期：2026-09-22
> 调研对象：智谱（北京智谱华章科技股份有限公司）旗下 **BigModel 国内版**（`bigmodel.cn` / `open.bigmodel.cn` / `docs.bigmodel.cn`）与 **Z.ai 国际版**（`z.ai` / `api.z.ai` / `docs.z.ai`），以及官方 AI 编程工作台 **ZCode**（`zcode.z.ai`）
> 调研问题：把智谱**账号 / Coding Plan 订阅**接入自建本地 LLM 网关，是否存在**官方支持的合规路径**？如果存在，是"官方 API Key"还是"账号凭据"？
> 取证方式：WebSearch + WebFetch，优先官方来源（官方协议页 / 官方文档 / 官方定价页）
> 证据标注约定：
> - **【一手】** = 平台官方发布的协议页、官方文档、官方定价页、官方公告
> - **【二手】** = 社区论坛、GitHub Issue、媒体报道、第三方镜像、第三方教程
> - **【推断】** = 本文基于已有证据的推理，**无直接来源支撑**，不得当作事实引用
> - **【未找到】** = 检索后未发现公开依据，**不编造**

---

## 一、结论先行

### 1.1 一句话判断

**智谱存在官方合规通路，但通路的形态是"标准按量计费 API Key"，不是"Coding Plan 订阅"。**

智谱（BigModel / Z.ai）对"开发者用官方 API Key 自由集成"是**明确欢迎**的——标准按量计费 API 就是这个用途；但对"把 Coding Plan 订阅额度拿去做自建应用 / 网关 / 中转"，官方**明文禁止**，且在协议里用了极其具体的措辞（"聚合转发""二次封装""服务中转""自建应用""SDK-based access"），并配有**真实生效的风控封号实践**（2026 年 4 月已有公开案例，封禁 30 天）。

### 1.2 分层结论表

| 接入形态 | 官方态度 | 合规风险 | 依据 |
|---|---|---|---|
| **标准按量计费 API Key → 自建本地网关（纯个人自用）** | ✅ 官方设计用途，欢迎开发者集成 | 🟢 **低**（残留一处模糊地带，见 §4.5） | 官方快速开始文档 + 用户协议第 3 节 7(7) 的"集成至自有产品"豁免 |
| **Coding Plan API Key → 自建本地网关** | ❌ **明文禁止** | 🔴 **高** | 《订阅及自动续费协议》六.2 原文明确禁止"在自建应用…中直接调用" |
| **Coding Plan 账号凭据（`zhipu-account` 型）→ 逆向私有接口** | ❌ 双重禁止（非授权工具 + 非授权访问方式） | 🔴 **极高** | 《用户协议》第 3 节 4 + 《订阅及自动续费协议》六.2 |
| **Coding Plan API Key → 官方指定工具（Claude Code / Cline / Kilo Code 等）** | ✅ 官方主动提供配置教程 | 🟢 低 | 官方 Claude Code 接入文档 |

### 1.3 与用户原计划的关系

用户原计划是"逆向各平台私有接口 + 授权登录"。对智谱而言：

- **不需要逆向，也不需要账号凭据**。智谱官方就提供 OpenAI 兼容 / Anthropic 兼容的**标准 API Key**，把它配到自建网关即可，这一步**完全在官方设计意图内**。
- **但必须用"标准 API Key"，不能用"Coding Plan Key"**。Coding Plan 看起来便宜（额度大、有 5 折低峰），却是**明确禁止用于自建应用**的产品形态——这是本次调研最关键、也最容易踩坑的一点。

---

## 二、代码库已核实事实（一手代码事实）

以下表格来自 ZCode 开源仓库（Apache-2.0）的 `config/provider/zcode-builtin.json`，为用户逐条解析后提供，本文视其为**一手代码事实**（但注意：代码事实 ≠ 条款事实，代码里声明了模板，不等于官方条款允许该用法）。

### 2.1 模板规则（templateRules）—— API Key 型

| templateId | 名称 | access.type | api.type | baseUrl | API Key 管理入口 |
|---|---|---|---|---|---|
| `zai-api` | Z.ai Coding Plan | `zhipu-coding-plan-api-key` | `anthropic-messages` | `https://api.z.ai/api/anthropic` | `https://z.ai/manage-apikey/apikey-list` |
| `zai-standard-api` | Z.ai API | `api-key` | `openai-chat-completions` | `https://api.z.ai/api/paas/v4` | `https://z.ai/manage-apikey/apikey-list` |
| `bigmodel-api` | BigModel Coding Plan | `zhipu-coding-plan-api-key` | `anthropic-messages` | `https://open.bigmodel.cn/api/anthropic` | `https://bigmodel.cn/coding-plan/personal/overview` |
| `bigmodel-standard-api` | BigModel API | `api-key` | `openai-chat-completions` | `https://open.bigmodel.cn/api/paas/v4` | `https://bigmodel.cn/usercenter/proj-mgmt/apikeys` |

> **本表已回源逐字段核对**（`config/provider/zcode-builtin.json` 第 8/30/77/99 行起；`bigmodel-standard-api` 定义见 `:99-112`）。四个模板**两两成对**：`*-api` 是 Coding Plan（订阅额度，`zhipu-coding-plan-api-key` + Anthropic 端点），`*-standard-api` 是标准按量计费（`api-key` + OpenAI 兼容端点 `/api/paas/v4`）。**两对的端点、凭据类型、额度池均不互通** —— 这与官方文档口径完全一致（见 §3.1、§3.4）。

> **代码事实的关键价值**：代码把厂商分成了**两类凭据**——`zhipu-coding-plan-api-key`（订阅套餐）与 `api-key`（标准按量计费）。这与官方文档完全吻合（见 §3.1、§3.4），说明智谱在 SDK / 工具层面对"套餐额度"与"标准 API 额度"是**分端点、分 Key** 处理的。

### 2.2 账号型（providerRules，`access.type = zhipu-account`）—— 8 条

`account:zai-individual-coding-plan`（mode=individual-coding-plan）、`account:zai-team-coding-plan`、`account:zai-start-plan`、`account:bigmodel-individual-coding-plan`、`account:bigmodel-team-coding-plan`、`account:bigmodel-start-plan`、`account:zai-offpeak-idle-plan`、`account:bigmodel-offpeak-idle-plan`。

其中 `start-plan` 与 `off-peak` 的 baseUrl 为 `https://zcode.z.ai/api/v1/zcode-plan/ant...` 与 `https://zcode.z.ai/api/v1/off-peak/anthr...`。

> **本文对账号型的判断**：这些是 **ZCode 官方客户端自身的登录态通路**（域名 `zcode.z.ai`，是智谱官方 IDE），属于"官方客户端内部的账号登录"。**它们不是给第三方工具用的公开 API 通路**——官方文档中没有任何一处指导用户用账号凭据去第三方工具接入。**用它来喂自建网关 = 逆向官方客户端私有接口**，属于《用户协议》第 3 节 4 明文禁止的行为（见 §4.4）。

### 2.3 关键观察的验证结果

用户提出的关键观察——"账号型 baseUrl 与 API Key 型部分重合，协议都是 Anthropic Messages"——**部分成立**：

- ✅ **成立**：Anthropic Messages 确实是智谱 Coding Plan 对外的主协议之一（官方文档明确列出）。
- ⚠️ **需修正**：**协议相同 ≠ 通路相同**。官方文档明确区分了三个端点（见 §3.4），且 Coding Plan 端点（`/api/anthropic`、`/api/coding/paas/v4`）与标准 API 端点（`/api/paas/v4`）**是两个不同产品**，额度池不互通。官方快速开始文档甚至专门加了一句提示："使用 GLM Coding Plan 时，请按教程配置专属端点。"【一手】
- ❌ **不能反推**："端点协议相同"不能推出"账号型与 API Key 型可以互换使用"——恰恰相反，官方条款把这两条路的允许范围划得很清楚。

---

## 三、Coding Plan 官方通路分析

### 3.1 问题 A1：Coding Plan 是否官方提供 API Key？

**结论：是。官方明确提供，且入口在官方文档中写明。**【一手】

官方文档原文（`docs.bigmodel.cn/cn/guide/develop/claude`，"步骤二：配置 GLM Coding Plan"）：

> 2 获取API Key
> - 个人版套餐的用户，通过 [个人编程套餐 > 套餐概览](https://bigmodel.cn/coding-plan/personal/overview)，新建 API Key
> - 团队版套餐的成员，通过 [团队编程套餐 > 我的套餐](http://bigmodel.cn/coding-plan?z_plan=team)，获取 API Key（**团队套餐 Key 与平台其他 API Key 不通用，使用团队额度请务必使用团队套餐 Key**）
>
> 请妥善保管您的 API Key，不要泄露给他人，也不要直接硬编码在代码中。

国际版官方文档（`docs.z.ai/devpack/quick-start`，"3 Obtain API Key"）原文：

> After subscribing, Individual Plan users can create an API Key under [Individual Coding Plan > Plan Overview](https://z.ai/manage-apikey/apikey-list). Team Plan members can obtain their API Key under [Team Coding Plan > My Plan](https://z.ai/manage-apikey/team/my-plan). **The Team Plan Key is not interchangeable with other Z.AI's API Keys.** To use your Team Plan quota, make sure to use the Team Plan Key.
> Safeguard your API Key by keeping it confidential and avoiding hard-coding it in your code.

**关键含义**：Coding Plan Key 是**专用于套餐额度的独立凭据**，与平台其他 API Key（标准按量计费 Key）**不通用**。这解释了代码库中 `zhipu-coding-plan-api-key` 与 `api-key` 两种 `access.type` 的区分。

### 3.2 问题 A2（最关键）：该 API Key 是否被官方明确允许在第三方工具中使用？

**结论：允许——但仅限"官方指定工具清单"内的第三方工具；清单外的工具（含自建网关）明确禁止。这是"白名单式允许"，不是"开放式允许"。**【一手】

这是本次调研**最关键**的一条。官方文档在"适用工具"页（`docs.bigmodel.cn/cn/coding-plan/tool/others`）开篇即给出总括性限制：

> ## 一、适用工具
> **GLM Coding Plan 仅限在以下官方支持的指定工具与产品环境中使用，用户不得将订阅权益用于以下范围之外的工具或场景。**【一手】

官方 `套餐概览` 页（`docs.bigmodel.cn/cn/coding-plan/overview`）再次强调：

> 套餐仅限在官方支持的 [指定工具与产品环境] 中使用。**在除规定工具外调用 API，不可享用 Coding 套餐的额度。**【一手】

`使用须知` 页（`docs.bigmodel.cn/cn/coding-plan/usage-notes`）第三次强调：

> **仅限指定工具使用**：GLM Coding Plan 仅限在[指定工具与产品环境]中使用，用于非支持工具将被限制权益。【一手】

**那么"指定工具"具体包含哪些？** 官方工具清单页（`tool/others`）分为两类：

1. **Coding Agent 工具**：文档以卡片形式列出（页面正文未以纯文本完整罗列，需进入各子文档），官方 `套餐概览` 页给出的示例为：
   > 支持 Claude Code、Kilo Code、OpenClaw、OpenCode、TRAE、CodeBuddy 等主流编码工具【一手】
2. **通用 Agent 工具**：文中明确出现的为 **Hermes Agent**；`套餐概览` 页另提到 **OpenClaw**（并注明采用次级调度与尽力交付策略）。

国际版 `z.ai/subscribe` 页面展示的工具图标包含：**ZCode、AutoClaw、Claude Code、Codex、WorkBuddy、TraeWork、CodeBuddy、TraeCode、OpenCode、Cursor、OpenClaw**，并称 "Supports 20+ agent tools"。【一手】

> **注意**：上述清单中**没有任何一项是"自建应用 / 自建网关 / 通用 SDK 调用"**。官方另有 Cline、Kilo Code 的详细配置教程（以 Cline 为例，官方给出 `OpenAI Compatible` + `https://open.bigmodel.cn/api/coding/paas/v4` 的完整配置步骤）【一手】。

**所以，问题 A2 的准确答案是：**

| 场景 | 官方是否允许 | 依据 |
|---|---|---|
| Coding Plan Key → Claude Code / Cline / Kilo Code / Cursor 等官方清单内工具 | ✅ 明确允许，官方出教程 | 官方接入文档【一手】 |
| Coding Plan Key → 自建应用 / 自建网关 / 通用 SDK 直连 | ❌ **明文禁止** | 《订阅及自动续费协议》六.2【一手】 |

**这就意味着：用户"把 Coding Plan 接入自建本地网关"的形态，不属于官方允许的第三方工具使用，而是被明文禁止的"自建应用直接调用"。** 详见 §4。

### 3.3 问题 A3：Coding Plan 套餐档位、额度与速率限制

#### 国内版（BigModel）—— 官方文档口径【一手】

官方 `套餐概览` 页给出的积分额度（这是最权威的数字）：

| 套餐类型 | 5 小时积分 | 每周积分 |
|---|---|---|
| Lite | 2,000 | 10,000 |
| Pro | 12,000 | 60,000 |
| Max | 28,000 | 140,000 |

积分抵扣公式（官方原文）：

> 模型消耗积分数 =（输入 Token × Input 抵扣系数 + 缓存命中 Token × Cached Input 抵扣系数 + 输出 Token × Output 抵扣系数） / 10000

抵扣系数（官方原文）：

| 产品类型 | 产品名称 | Input 抵扣系数 | Cached Input 抵扣系数 | Output 抵扣系数 |
|---|---|---|---|---|
| 模型 | GLM-5.3 | 6.9 | 1.7 | 24 |
| 模型 | GLM-5.3-Flash（含视觉理解 MCP） | 2.3 | 0.5 | 68 |
| MCP 工具 | 联网搜索 / 网页读取 / 开源仓库 | — | — | 1.2 |

低峰折扣（官方原文）：

> **非高峰时段内，模型调用按基础积分消耗的 50% 抵扣。**
> **高峰时段：每周一至周五的 14:00～18:00（UTC+8）。**

**关于 off-peak / start-plan（用户问的"低峰闲时套餐"）**：

- **【未找到】** 官方文档中**没有**一个名为 "off-peak plan / 低峰闲时套餐" 的**独立订阅档位**。低峰（off-peak）是**积分折扣机制**（50% 抵扣），不是独立套餐。
- 代码库中的 `account:zai-offpeak-idle-plan` / `account:bigmodel-offpeak-idle-plan` 指向 `https://zcode.z.ai/api/v1/off-peak/...`，即 **ZCode 客户端专属**的低峰活动通路。【推断】
- 官方确实有**限时活动**与之对应：`套餐概览` 页头部公告"**夜间畅用活动**来袭：9 月 3 日至 10 月 7 日，每日 23:00～次日 09:00，套餐用户在 [ZCode](https://zcode.z.ai/cn) 端调用 GLM-5.3-Flash 无限畅蹬，在其他 Agent 额度翻倍！"【一手】——**注意该活动明确限定在 ZCode 端或"其他 Agent"（即指定工具）内**。
- 另有"庆双节活动：9 月 25 日至 10 月 7 日，全天按非高峰时段规则消耗额度。"【一手】
- **`start-plan` 对应的官方产品【未找到】**。代码库中有 `zai-start-plan` / `bigmodel-start-plan`，baseUrl 指向 `zcode.z.ai/api/v1/zcode-plan/...`，推测为 ZCode 的入门级套餐，但**未检索到官方文档或定价页**。

#### 定价（国内版，人民币）—— 【二手】

官方控制台定价页需登录，本次未能直接抓取。二手来源给出的数字**彼此一致**：

| 档位 | 连续包月 | 来源 |
|---|---|---|
| Lite | ¥118/月 | 新浪财经 2026-09-02（"个人版 Lite 月付 118 元"）【二手-媒体】；codingplan.org【二手】 |
| Pro | ¥538/月 | codingplan.org【二手】 |
| Max | ¥1078/月 | codingplan.org【二手】 |
| 团队版 | ¥598 起 | 新浪财经 2026-09-02（"团队版 598 元"）【二手-媒体】 |
| 包年 | 约 7 折，低至 ¥94.4/月 | codingplan.org【二手】 |

> ⚠️ **上述人民币价格均为二手来源，未经官方定价页直接验证**。请以 `bigmodel.cn/coding-plan/personal/overview` 登录后页面为准。

#### 定价（国际版，美元）—— 【一手】

来自 `z.ai/subscribe`（年付价 / 月付价）：

| 档位 | 年付 | 月付 | 额度（官方表述） |
|---|---|---|---|
| **Lite** | $12.6/月 | $18/月 | 10,000 Credits/week |
| **Pro** | $56/月 | $80/月 | 6× Lite usage |
| **Max** | $117.6/月 | $168/月 | 14× Lite usage |

国际版同样有 5 小时 / 每周双额度，且数字与国内版一致（Lite 2,000 / 10,000；Pro 12,000 / 60,000；Max 28,000 / 140,000），国际版峰值时段表述为 "Monday to Friday, 14:00–18:00 Singapore Standard Time (UTC+8)"。【一手】

#### 速率/并发限制【一手】

官方 `使用须知` 页原文：

> 速率（并发数）限制与您的套餐等级相关，平台会根据资源进行动态调整，基本原则 **Max > Pro > Lite**。每个项目开发可使用 Subagent 等方式并发模型调用，我们的推荐使用项目数量如下：
> - Lite ： 建议同时进行单个项目的开发
> - Pro ： 建议同时进行 1-2 个项目的开发
> - Max ：建议同时进行 2+ 个项目的开发
> 套餐用户在低峰期将享有更高的并发权益（动态提升），能够支撑更高数量的项目开发。

> **注意**：官方**未公布具体并发数字**（如"X 并发/秒"），只给出相对关系和"建议项目数"。【未找到】精确并发数值。

### 3.4 问题 A4：两个 Anthropic 兼容端点是否有官方文档？是否面向普通用户开放？

**结论：有官方文档，且面向所有 Coding Plan 订阅用户开放——但仅限在"官方指定工具"中使用。**【一手】

官方 `接入工具` 页（`docs.bigmodel.cn/cn/coding-plan/tool/others`）"二、编程端点"章节原文：

> GLM Coding Plan 支持 Anthropic 协议和 OpenAI 协议两种接入方式，接入时请注意配置正确的 `Base URL`：
>
> | 协议类型 | Base URL |
> |---|---|
> | Anthropic Message 协议 | `https://open.bigmodel.cn/api/anthropic` |
> | OpenAI Chat Completion 协议 | `https://open.bigmodel.cn/api/coding/paas/v4` |
> | OpenAI Response 协议 | `https://open.bigmodel.cn/api/v1` |
>
> **核心步骤**
> 1. 根据您的工具选择适配的协议（Anthropic Message 协议或 OpenAI Chat Completion 协议）
> 2. 配置正确的 Base URL
> 3. 输入 API Key 并选择 GLM 模型
>
> 请根据您使用的工具选择正确的端点地址。**错误配置端点将导致无法使用 GLM Coding Plan 套餐额度。**

国际版对应端点（`docs.z.ai/devpack/quick-start`）【一手】：

| 协议 | Base URL |
|---|---|
| Anthropic Messages | `https://api.z.ai/api/anthropic` |
| OpenAI Chat Completions | `https://api.z.ai/api/coding/paas/v4` |
| OpenAI Responses | `https://api.z.ai/api/v1` |

> **重要区分**：Coding Plan 的 OpenAI 兼容端点是 **`/api/coding/paas/v4`**（带 `coding` 段），而**标准按量计费 API 端点是 `/api/paas/v4`**（不带 `coding`）。二者是**不同产品、不同额度池**。官方快速开始文档在标准 API 示例后专门加注："使用 GLM Coding Plan 时，请按教程配置专属端点。"【一手】

**端点是否"面向普通用户开放"？** —— 端点是公开文档化的，任何 Coding Plan 订阅用户都能拿到 Key 并用。但**用在哪里**受 §3.2 的工具白名单约束。**"端点可访问" ≠ "用途被允许"。**

---

## 四、服务条款逐条命中分析

本节是合规判断的核心。**共命中两份协议、多条条款**，且措辞高度具体。

### 4.1 《订阅及自动续费协议》—— 最直接的命中

- **URL**：https://docs.bigmodel.cn/cn/terms/subscription-agreement
- **签署方**：北京智谱华章科技股份有限公司
- **最新版本生效日期：2026 年 7 月 6 日**【一手】

#### 4.1.1 六、使用规范 → 2. 使用场景限制（**决定性条款**）

原文逐字【一手】：

> - 您理解并同意，GLM Coding Plan 为一项订阅服务，其调用额度仅限于在[智谱官方支持的工具](https://docs.bigmodel.cn/cn/coding-plan/tool/others)中使用；**如通过非官方工具或未授权方式使用，平台有权对相关权益进行限制、暂停或封禁处理。**
> - **您不得将 GLM Coding Plan 的调用额度用于上述工具以外的通用 API 接入或其他场景，包括但不限于在自建应用、机器人、网站、SaaS 产品或其他系统中直接调用相关模型接口，除非您与智谱另行签署书面协议。**
> - 除非另有书面约定，您不得将 GLM Coding Plan 以**转售、代售、转包装、聚合转发**等方式向任何第三方提供，亦不得利用 GLM Coding Plan 为第三方提供付费或免费的模型能力服务。

**命中分析**：

| 用户计划的形态 | 命中的条款 | 判定 |
|---|---|---|
| Coding Plan Key 配到自建本地网关 | "不得将调用额度用于…**通用 API 接入**或其他场景，包括但不限于在**自建应用**…中直接调用相关模型接口" | 🔴 **明文禁止**（"自建应用"四字直接命中） |
| 网关对外暴露给他人/其他工具 | "不得以…**聚合转发**等方式向任何第三方提供" | 🔴 明文禁止 |
| 用账号凭据逆向私有接口 | "如通过**非官方工具或未授权方式**使用" | 🔴 明文禁止 |

> ⚠️ **特别注意**：这一条**没有"个人自用可豁免"的表述**。禁止范围是"通用 API 接入或其他场景"本身，**不以是否对外提供服务为条件**。也就是说，**即使网关只服务用户自己一个人、单实例、纯本地，仍然落在"自建应用中直接调用"的禁止范围内**。这是与《用户协议》7(7)（见 §4.2，那条以"向第三方提供"为要件）的**关键差异**。

#### 4.1.2 六、使用规范 → 3. 个人使用限制

原文逐字【一手】：

> - GLM Coding Plan 订阅以单一账号为单位，仅授权与该账号绑定的自然人个人使用。
> - 您不得以**共享账号、出租、出借、转让、转授权**或其他任何方式，使他人（包括但不限于您的同事、朋友、客户或任何组织）实际使用您的 GLM Coding Plan 调用额度。
> - 如智谱合理怀疑您存在**账号共享、批量调用、代为提供服务、代买、转售访问权限**等可能损害平台公平使用秩序或第三方合法权益的行为，智谱有权采取包括但不限于限制部分功能、降低或限制调用额度、冻结或终止服务、回收剩余额度等措施，并可根据本协议及适用法律追究相应责任。

> **注**："**批量调用**"是明确列举的怀疑情形之一。自建网关天然是"一个出口、多路请求汇聚"的形态，在风控特征上**与"批量调用"高度相似**。【推断】

#### 4.1.3 其他相关条款

- 三、费用与支付 → 退款政策：冷静期 7 天内且未产生任何用量可全额退；**7 天后原则上不退**；"订阅服务一经购买即视为确认，不支持退款"（`使用须知` 页表述）【一手】
- 七、责任限制：总直接责任不超过"最近一个自然月的消费总额"【一手】
- 九、法律适用：适用中华人民共和国法律，争议提交智谱所在地有管辖权的法院【一手】

### 4.2 《智谱AI用户协议》—— 兜底命中（标准 API 场景适用）

- **URL**：https://docs.bigmodel.cn/cn/terms/user-agreement
- **最新版本生效日期：2026 年 9 月 4 日**【一手】

#### 4.2.1 第三节 7. 使用要求 第 (7) 项（**核心条款，且带豁免**）

原文逐字【一手】：

> **(7) 未经智谱事先书面同意，您不得通过出租、出借、出售、分销、转售、转让、共享账号、转授权、二次封装、服务中转、聚合中转或其他变相方式，向任何第三方提供大模型开放平台服务，或提供与本服务相关的 API Key、API Token、访问凭证、账号权限或其他服务能力。为免疑义，您将本服务依法合规集成至您自有产品、应用或功能中，并向该等产品、应用或功能的终端用户提供服务的，不视为前述受限行为，但您应确保该等使用符合本协议及智谱不时发布的产品规则、订阅规则。**

**逐字解析**：

| 要素 | 原文 | 对用户计划的意义 |
|---|---|---|
| 禁止行为 | 出租/出借/出售/分销/转售/转让/共享账号/转授权/**二次封装**/**服务中转**/**聚合中转** | "服务中转""聚合中转"在措辞上**贴近"网关"语义** |
| 禁止要件 | **"向任何第三方提供"** | ⚠️ **要件是"向第三方"** |
| 明确豁免 | "将本服务依法合规**集成至您自有产品、应用或功能中**，并向该等…终端用户提供服务的，**不视为前述受限行为**" | ✅ **自建集成本身被明确豁免** |

> **这是本次调研最重要的"利好"发现**：与 Coding Plan 协议不同，《用户协议》7(7) **明文豁免了"集成至自有产品/应用"的行为**，禁止的只是"向第三方提供"。因此——
>
> - **标准按量计费 API Key → 自建本地网关（纯个人自用、不服务任何第三方）**：落在"集成至自有应用"的豁免范围内，**合规风险低**。✅
> - **一旦网关对任何第三方（他人、其他用户、对外服务）开放**：立即落入"向任何第三方提供 / 服务中转 / 聚合中转"的禁止范围。🔴
>
> **分界线就是"是否服务第三方"**，而不是"是否自建"。这是标准 API 路径可行、Coding Plan 路径不可行的**条款级原因**：Coding Plan 协议**没有这条豁免**，反而额外加了一条"不得用于自建应用"的正面禁止。

#### 4.2.2 第三节 4.（**反向工程 / 非授权工具接入的禁止**）

原文逐字【一手】（节选与本任务相关部分）：

> **4.您不应以以下方式不当使用大模型开放平台：**
> - 以任何方式试图从大模型开放平台中**提取数据、参数或代码**；
> - …对大模型开放平台进行**反向工程、反向汇编、反向编译**，或者以其他方式尝试发现大模型开放平台的源代码；
> - …您不得对大模型开放平台或者大模型开放平台运行过程中释放到任何终端内存中的数据、软件运行过程中客户端与服务器端的交互数据，以及大模型开放平台运行所必需的系统数据，进行复制、修改、增加、删除、挂接运行或创作任何衍生作品，形式包括但不限于使用**插件、外挂或非经智谱授权的第三方工具/服务接入**大模型开放平台和相关系统；
> - 通过修改或伪造软件运行中的指令、数据，增加、删减、变动软件的功能或运行效果…；
> - 通过**非智谱开发、授权的第三方软件、插件、外挂、系统，登录或使用智谱软件及服务**，或制作、发布、传播上述工具；
> - 自行或者授权他人、第三方软件对大模型开放平台及其组件、模块、数据进行**干扰**；
> - …其他未经智谱明示授权的行为和其他可能损害智谱利益的使用方式。

> **命中**：用户原计划的"逆向各平台私有接口 + 授权登录"，**被本节多条直接覆盖**——"反向工程""非经智谱授权的第三方工具/服务接入""非智谱开发、授权的第三方软件…登录或使用"。
>
> **注**：协议原文中**未出现"爬虫"或"自动化批量调用"的字面表述**；最接近的是上述"提取数据、参数或代码""非授权第三方工具/服务接入""干扰"等条款。【一手核实】

#### 4.2.3 第三节 7.(7) 之外的凭据条款

- 第七节 知识产权 第 3 条 ①：未经书面同意，不得"复制、转让、出售、出租、出借、许可、提供他人使用或以任何智谱明示同意之外的商业化方式使用…权限密钥…API 接口…"；**豁免**："您可以在按照…规则支付费用后，按相应产品的规则商业化使用平台内模型及其生成的内容。"【一手】
- 第二节 3. 账户安全："您的大模型开放平台账户仅限您本人使用。未经大模型开放平台同意，您直接或间接授权第三方使用您大模型开放平台账户或获取您账户项下信息的行为无效。"【一手】
- 第二节 2. 账户注册："如有证据证明…您存在不当注册或**不当使用多个大模型开放平台账户**的情形，大模型开放平台可采取冻结或关闭账户、拒绝提供服务等措施。"【一手】

#### 4.2.4 第十三节 违约责任（**罚则最重的条款**）

原文逐字【一手】：

> ② 如您存在**违规转售或变相转售平台服务、API Key** 的，智谱有权采取以下一种或多种措施追究您的责任：**立即暂停或终止向您提供服务，限制或封禁相关账号，要求您承担违规转售期间累计消耗金额的 5 倍作为违约金，已支付/充值的金额不予退换，赔偿由此给智谱造成的全部损失（包括但不限于律师费、公证费、鉴定费、差旅费等）。**

> ⚠️ **"5 倍违约金 + 余额不退"** 是本次调研中见到的**最严厉的罚则**。若自建网关被判定为"变相转售"（例如对外提供能力），后果远超"封号"。

### 4.3 国际版《Subscriptions, Fees, and Payment》—— 与国内版一致，且**额外点名 SDK**

- **URL**：https://docs.z.ai/legal-agreement/subscription-terms
- **生效日期**：页面未标注明确日期【未找到】

原文逐字【一手】：

> **2. Usage Scenario Restrictions**
> - You understand and agree that the usage quota under GLM Coding Plan is only used within [officially supported tools](https://docs.z.ai/devpack/tool/others). **If the system detects usage through unauthorized or unsupported tools (such as SDK-based access or other third-party integrations), some subscription benefits may be restricted** to ensure fairness and service stability.
> - You shall not use the GLM Coding Plan quota for general-purpose API access or any scenarios outside such tools, **including but not limited to directly invoking model APIs from your own applications, bots, websites, SaaS products or other systems**, unless you have entered into a separate written agreement with Z.ai.
> - Unless otherwise agreed in writing, you may not **resell, sub-resell, repackage, aggregate, proxy** or otherwise provide the GLM Coding Plan to any third party, whether on a paid or free basis, nor may you use the GLM Coding Plan to provide model capabilities as a service to third parties.
>
> **3. Personal-Use Only**
> - The GLM Coding Plan subscription is tied to a single account and is licensed only to the individual natural person associated with such account.
> - You shall not share your account or subscription, or allow any other person … to use your GLM Coding Plan quota, whether by sharing credentials, renting, lending, transferring, sublicensing or by any other means.
> - If Z.ai reasonably suspects that you are engaging in **account sharing, bulk or automated usage on behalf of others, resale of access**, or any other conduct that may harm the platform's fair-use order …, Z.ai is entitled to take measures including … restricting certain features, reducing or limiting your usage quota, suspending or terminating the service, reclaiming any remaining quota …

> **国际版的两点额外发现**：
> 1. **明文点名 `SDK-based access`**——"若系统检测到通过未授权工具使用（**例如基于 SDK 的接入**或其他第三方集成），部分订阅权益可能被限制"。自建网关通常就是 SDK/HTTP 直连形态，**这一句几乎是对网关形态的点名**。
> 2. **明文点名 `aggregate` 与 `proxy`**——"聚合"与"代理"，网关语义的英文对应词。**"proxy" 一词直接命中"网关"的核心功能**。

### 4.4 命中条款汇总表

| # | 协议 / 文档 | 条款位置 | 命中内容 | 对"自建网关"的影响 | 来源 |
|---|---|---|---|---|---|
| 1 | 订阅及自动续费协议（CN，2026-07-06） | 六.2 | 不得用于"自建应用…中直接调用" | 🔴 **直接禁止（含个人自用）** | 一手 |
| 2 | 订阅及自动续费协议（CN） | 六.2 | 不得"聚合转发"给第三方 | 🔴 禁止 | 一手 |
| 3 | 订阅及自动续费协议（CN） | 六.3 | 单一账号、仅限自然人个人使用；怀疑"批量调用"即可处置 | 🔴 网关特征高度相似 | 一手 |
| 4 | 订阅及自动续费协议（国际版） | 4.2 | 禁止 `general-purpose API access` / `your own applications` | 🔴 禁止 | 一手 |
| 5 | 订阅及自动续费协议（国际版） | 4.2 | 检测到 **`SDK-based access`** 即限制权益 | 🔴 点名 SDK 直连 | 一手 |
| 6 | 订阅及自动续费协议（国际版） | 4.2 | 禁止 `aggregate, proxy` | 🔴 **"proxy" 直接命中网关** | 一手 |
| 7 | 用户协议（CN，2026-09-04） | 三.7(7) | 禁止"向任何第三方提供…服务中转、聚合中转"；**豁免"集成至自有产品/应用"** | 🟡 **个人自用可豁免；对外服务则禁止** | 一手 |
| 8 | 用户协议（CN） | 三.4 | 禁止反向工程、非授权第三方工具/服务接入 | 🔴 覆盖"逆向私有接口" | 一手 |
| 9 | 用户协议（CN） | 十三 | 违规转售 → **5 倍违约金 + 余额不退** | 🔴 罚则极重 | 一手 |
| 10 | 使用须知（CN） | 账号使用规范 | "套餐仅限订阅人专享：禁止账号共享或多人共用" | 🔴 禁止 | 一手 |
| 11 | 使用须知（CN） | 账号使用规范 | "仅限指定工具使用…用于非支持工具将被限制权益" | 🔴 禁止 | 一手 |
| 12 | 使用须知（CN） | 永久封禁说明 | 对"倒卖、**中转**、套利"执行永久封禁 | 🔴 **"中转"明文列入永久封禁事由** | 一手 |

> **第 12 条特别值得单独摘出**，官方 `使用须知` 页"永久封禁说明"原文：
>
> > 永久封禁属于平台最高等级处置。**平台会秉持审慎原则，在证据充分、风险特征明确，并确认账号存在倒卖、中转、套利等严重违规行为时执行**。永久封禁不会因单一指标触发，我们会综合多个风险信号，并结合必要的人工复核作出处置决定。
>
> **"中转"二字被官方直接列为永久封禁事由之一。** 这是对"网关/中转"形态最直接的官方否定表述。【一手】

### 4.5 残留模糊地带（诚实标注）

即使走"标准按量计费 API Key + 纯个人自用"，仍有以下**未完全澄清**之处，需要标注：

1. **【推断】**《用户协议》7(7) 的豁免写的是"集成至您自有产品、应用或功能中，**并向该等…终端用户提供服务**"。一个**纯个人自用、不向任何终端用户提供服务**的本地网关，是否落入豁免？从文义看，"不向第三方提供"这一点是满足的（因为不存在第三方），但豁免句的表述偏向"有终端用户的集成场景"。**是否存在更精确的官方解释，未找到。**
2. **【推断】**"服务中转""聚合中转"的**判定标准未公开**。一个纯本地、单用户、不外发的网关，与"中转"在客观特征上（多路汇聚、单一出口）存在相似性。官方**未公开**如何区分"个人集成"与"中转"。**这一判定权在平台方。**
3. **【未找到】**官方是否有针对"个人本地自建集成"的**正面澄清文档或 FAQ**。
4. **【未找到】**标准 API 场景下，是否存在**独立于《用户协议》的使用规范页**（类似 Coding Plan 的 `使用须知`）。

---

## 五、与前三家平台的横向对比

### 5.1 合规通路有无

| 平台 | 是否有官方合规通路 | 通路形态 | 对本项目（本地网关）的可用性 |
|---|---|---|---|
| **腾讯 CodeBuddy（中国版）** | ✅ **有，且完整** | 官方 API Key + Agent SDK + HTTP API | ✅ 可直接用 |
| **智谱 BigModel / Z.ai** | ✅ **有（标准按量 API）**<br>❌ 无（Coding Plan 路径被禁） | 官方标准 API Key（OpenAI / Anthropic 兼容双端点） | ✅ **可用**（走标准 API）<br>🔴 不可用（走 Coding Plan） |
| **字节 TRAE** | ❌ 自身无 | 需改用**火山方舟**按量计费 API | ⚠️ 需跨产品替代 |
| **腾讯 WorkBuddy（国际版）** | ❌ 无 | 未找到面向个人的模型推理 API | ❌ 不可用 |

> **智谱的独特之处**：它**同时**存在"明确可用的合规通路"（标准 API）与"明确禁止的诱惑通路"（Coding Plan）。用户如果因为 Coding Plan 便宜而选它接网关，**正好踩在最红的线上**。

### 5.2 条款严格度

按"对自建网关/中转形态的条款明确程度"排序（越靠前越严格）：

| 排名 | 平台 | 严格度 | 关键措辞 | 罚则 |
|---|---|---|---|---|
| **1** | **智谱（Coding Plan 场景）** | 🔴 **最严格（明文点名）** | "自建应用"、"聚合转发"、"服务中转"、"二次封装"、**"中转"列入永久封禁**、国际版点名 **`SDK-based access`** 与 **`proxy`** | **5 倍违约金** + 余额不退 + 永久封禁 |
| 2 | 腾讯 WorkBuddy | 🔴 高 | "检测规避措施 / 识别未授权程序"（据 05 号文档） | 封号 |
| 3 | 字节 TRAE | 🔴 高 | 禁止"自动化程序接入" + 2 设备上限 + 24h 风控（据 05 号文档） | 封号 |
| 4 | 腾讯 CodeBuddy | 🔴 高（条款）但 🟢 低（有官方替代） | 条款禁止，但官方提供完整 API Key 通路 | — |
| — | **智谱（标准 API 场景）** | 🟢 **最宽松** | 明文豁免"集成至自有产品/应用" | — |

> **结论**：**智谱在 Coding Plan 场景下的条款是四家中最严格、最具体的**——它不只是"兜底条款覆盖"，而是**逐词点名**了网关/中转的每一种形态（含英文 `proxy`、`SDK-based access`），并给出了**最重的罚则（5 倍违约金）**。这比 CodeBuddy/TRAE/WorkBuddy 的"兜底禁止"要**明确和严厉得多**。
>
> **但反过来**：**智谱在标准 API 场景下的条款是四家中最宽松的**——它是唯一一家**明文写出"集成至自有产品/应用不视为受限"豁免**的平台。这个"豁免 + 明确边界"的写法，实际上比含糊的兜底条款对用户**更友好**。

### 5.3 风控案例有无

| 平台 | 公开风控/封号案例 | 证据强度 |
|---|---|---|
| **智谱** | ✅ **有，且案例较多（2026-04 集中爆发）** | 【二手】多帖 + 媒体报道 |
| 腾讯 WorkBuddy | ✅ 有（据 05 号文档） | 【二手】 |
| 字节 TRAE | ✅ 有（设备风控） | 【二手】 |
| 腾讯 CodeBuddy | 未在 05 号文档中列为重点 | — |

> 智谱的风控案例详见 §6。

---

## 六、风控与封号实践

### 6.1 官方自述的风控机制【一手】

来自 `docs.bigmodel.cn/cn/coding-plan/usage-notes`：

> **违规处置**：违反[订阅及自动续费协议](https://docs.bigmodel.cn/cn/terms/subscription-agreement)将可能触发风控，会被进行**限流、冻结**等处置。**3 次以上违规可能会被封禁账号**。如命中风控策略，可在控制台[套餐概览](https://www.bigmodel.cn/coding-plan/personal/overview)查看风控提示并发起申诉。

> **永久封禁说明**：永久封禁属于平台最高等级处置。平台会秉持审慎原则，在证据充分、风险特征明确，并确认账号存在**倒卖、中转、套利**等严重违规行为时执行。永久封禁不会因单一指标触发，我们会综合多个风险信号，并结合必要的人工复核作出处置决定。由于风控证据涉及平台风控机制和用户隐私细节，我们不会公开披露完整判定逻辑或后台日志。

**官方处置阶梯（本文归纳）**：限流 → 冻结 → 封禁（3 次以上）→ 永久封禁（倒卖/中转/套利）。

### 6.2 公开案例

#### 案例 1：2026-04 智谱 Coding Plan 集中封号【二手】

- **来源**：LINUX DO 论坛帖《智谱 coding plan 正式开始封号！》https://linux.do/t/topic/1977810 （2026-04-16）
- **内容**：帖主称"飞书群里看到的，这几天风控非常严，开启乱杀模式，**直接封号 30 天**！"
- **帖子中援引的原始工单反馈**（转引自 LINUX DO 另一帖 `topic/1969391`）：
  > 再更新一下，**工单回复了，说是因为使用了 API。问题是！tmd api，是tmd glm官方文档里自己写的可以用的啊！**
  > 4.16更新：昨天还显示是两天的，今天变成30天了
- **社区对检测维度的描述**（帖内用户发言，非官方）："智谱主要检测就是: **禁止分享, 禁止龙虾**"（"龙虾"为社区对某类工具的代称，具体所指未获官方确认【未找到】）
- **证据强度**：社区帖子 + 用户自述工单截图，**未见官方公告确认**【二手】

#### 案例 2："合规使用 Claude Code 仍被封"【二手】

- **来源**：80aj.com 报道《智谱AI"误伤"开发者？合规使用Claude Code仍遭封禁，风控机制引争议》https://www.80aj.com/2026/04/20/ai-clude-ban-controversy/ （2026-04-20）
- **原文**：
  > 近日有开发者爆料，在完全合规使用智谱AI GLM Coding Plan对接Anthropic Claude Code时，**短时间内遭遇连续三次封禁**。该用户表示，尽管其严格遵循官方文档配置、使用官方推荐API端点且用量正常，仍被智谱风控系统判定为"**非官方许可范围内使用**"，导致服务中断。用户排查了插件来源、网络环境及请求头后确认无误，且官方文档明确支持该集成，但客服未能给出具体违规原因。
- **原文链接**：指向 LINUX DO `topic/2005895`
- **证据强度**：媒体转述社区爆料，**未见智谱官方回应**【二手】

#### 案例 3：智谱 GLM Coding Plan 致歉信【二手-媒体报道官方公告】

- **来源**：IT之家《智谱发布 GLM Coding Plan 致歉信：规则透明度不够、GLM-5 灰度节奏太慢…》https://www.ithome.com/0/922/755.htm （2026-02-21）
- **内容**：智谱就 Coding Plan 发布致歉信，自陈"主要犯了三个错：规则透明度不够、GLM-5 灰度节奏太慢、老用户…"
- **意义**：说明**官方自己承认早期"规则透明度不够"**，侧面印证用户对规则边界的困惑有官方背书。【二手】

### 6.3 风控实践对用户计划的含义

| 观察 | 对本项目的含义 |
|---|---|
| 官方明确"3 次以上违规可能封号" | 若用 Coding Plan 接网关，属"违规"，**存在累积封号风险** |
| 官方明确"中转"属永久封禁事由 | 网关形态**直接对应"中转"语义** |
| 已有"合规配置 Claude Code 仍被封"案例 | 即使自认合规，**风控误伤确实存在**，申诉渠道不透明 |
| 国际版点名 `SDK-based access` | 网关常见的 SDK/HTTP 直连形态**被点名** |
| 社区称风控"开启乱杀模式" | 【二手】风控强度可能随资源紧张波动 |

> **【推断】** 从社区反馈看，智谱 2026 年的风控是**行为特征驱动 + 人工复核**的组合，且**对"额度消耗模式"敏感**（如是否有明显的多路汇聚、非典型工具 UA、异常调用节奏）。一个本地网关若保持单用户、低频、仅自用，**被误判概率相对较低**，但**这不是合规依据，只是概率判断**。

---

## 七、未找到公开依据的事项清单（诚实标注）

以下事项经中英文检索后**未找到公开依据**，本文不做任何推测性断言：

| # | 事项 | 状态 |
|---|---|---|
| 1 | `account:zai-start-plan` / `account:bigmodel-start-plan` 对应的**官方产品名称、定价、权益** | 【未找到】官方文档与定价页均无 |
| 2 | "off-peak-idle-plan"作为**独立订阅档位**的官方定义 | 【未找到】官方仅有"非高峰时段 50% 抵扣"机制，非独立套餐 |
| 3 | Coding Plan 各档位的**精确并发数值**（如 QPS） | 【未找到】官方只给相对关系 |
| 4 | 国内版 Coding Plan 的**官方人民币定价页直接原文**（本次仅取到二手一致数字） | 【未找到】官方页需登录 |
| 5 | 官方是否发布过**针对"个人本地自建集成"的正面澄清或 FAQ** | 【未找到】 |
| 6 | 标准 API 场景下是否有**独立的使用规范页** | 【未找到】 |
| 7 | "服务中转 / 聚合中转"的**官方判定标准** | 【未找到】官方明确表示"不会公开披露完整判定逻辑" |
| 8 | 智谱对 2026-04 封号潮的**官方正式回应**（仅见 2026-02 致歉信） | 【未找到】 |
| 9 | 社区所称"禁止龙虾"中"龙虾"的**确切所指** | 【未找到】官方无对应表述 |
| 10 | 国际版订阅协议（`subscription-terms`）的**生效/更新日期** | 【未找到】页面未标注 |
| 11 | 是否存在"禁止将订阅用于第三方工具"的**独立专门条款**（现有条款是嵌在"使用场景限制"内） | 【未找到】独立条款；但现有条款已足够覆盖 |
| 12 | 官方是否提供**企业/团队场景下允许自建集成**的书面协议模板 | 【未找到】协议多次提及"除非另行签署书面协议"，但未见模板 |

---

## 八、参考来源清单

### 8.1 一手来源（官方）

| # | 标题 | URL | 用途 | 日期 |
|---|---|---|---|---|
| 1 | 使用须知 — 智谱AI开放文档 | https://docs.bigmodel.cn/cn/coding-plan/usage-notes | 账号使用规范、违规处置、永久封禁说明、并发限制、退款政策 | — |
| 2 | 订阅及自动续费协议 — 智谱AI开放文档 | https://docs.bigmodel.cn/cn/terms/subscription-agreement | **决定性条款**：六.2 使用场景限制、六.3 个人使用限制 | 生效 2026-07-06 |
| 3 | 智谱AI用户协议 — 智谱AI开放文档 | https://docs.bigmodel.cn/cn/terms/user-agreement | 三.7(7) 账号/凭据转让 + 豁免、三.4 禁止访问方式、十三 违约责任（5 倍违约金） | 生效 2026-09-04 |
| 4 | 接入工具 — 智谱AI开放文档 | https://docs.bigmodel.cn/cn/coding-plan/tool/others | 适用工具白名单、三个编程端点、Cline 配置示例 | — |
| 5 | 套餐概览 — 智谱AI开放文档 | https://docs.bigmodel.cn/cn/coding-plan/overview | 档位积分额度、抵扣系数、低峰 50%、夜间畅用活动 | — |
| 6 | Claude Code — 智谱AI开放文档 | https://docs.bigmodel.cn/cn/guide/develop/claude | 官方 Claude Code 接入教程、API Key 入口、环境变量 | — |
| 7 | 快速开始 — 智谱AI开放文档 | https://docs.bigmodel.cn/cn/guide/start/quick-start | 标准 API Key 入口、标准端点 `/api/paas/v4`、"Coding Plan 请配置专属端点"提示 | — |
| 8 | API 定价 — 智谱AI开放文档 | https://docs.bigmodel.cn/cn/guide/start/pricing | 标准按量计费全量价目表（GLM-5.3 等） | — |
| 9 | Subscriptions, Fees, and Payment — Z.AI | https://docs.z.ai/legal-agreement/subscription-terms | **国际版条款**：4.2 使用场景限制（点名 `SDK-based access` / `aggregate` / `proxy`） | 未标注 |
| 10 | Overview (devpack) — Z.AI | https://docs.z.ai/devpack/overview | 国际版额度表、抵扣系数、低峰 50% | — |
| 11 | Quick Start (devpack) — Z.AI | https://docs.z.ai/devpack/quick-start | 国际版 API Key 入口、三端点、工具白名单 | — |
| 12 | GLM Coding Plan 订阅页 — Z.ai | https://z.ai/subscribe | **国际版定价**（$18/$80/$168）、支持工具图标清单 | — |
| 13 | Z.ai Pricing | https://z.ai/pricing | 国际版按量计费定价入口 | — |
| 14 | Team Plan — Z.AI | https://docs.z.ai/devpack/teamplan | 团队版权益 | — |

### 8.2 二手来源

| # | 标题 | URL | 用途 | 日期 |
|---|---|---|---|---|
| 1 | 智谱 coding plan 正式开始封号！— LINUX DO | https://linux.do/t/topic/1977810 | 封号案例、工单反馈、"因使用了API被封" | 2026-04-16 |
| 2 | 智谱AI"误伤"开发者？合规使用Claude Code仍遭封禁 — 80aj | https://www.80aj.com/2026/04/20/ai-clude-ban-controversy/ | 合规使用仍被封案例（连续三次） | 2026-04-20 |
| 3 | 智谱发布 GLM Coding Plan 致歉信 — IT之家 | https://www.ithome.com/0/922/755.htm | 官方承认"规则透明度不够" | 2026-02-21 |
| 4 | 智谱的coding plan风控有人成功解除过吗 — LINUX DO | https://linux.do/t/topic/1936025 | 风控申诉讨论 | 2026-04-10 |
| 5 | GLM Coding Plan 多少钱？智谱三档价格 — codingplan.org | https://codingplan.org/plans/zhipu | 国内版人民币定价（Lite ¥118 / Pro ¥538 / Max ¥1078） | 2026-08-31 |
| 6 | 智谱在天猫开店卖token：个人版每月118元起 — 新浪财经 | https://t.cj.sina.com.cn/articles/view/5182171545/134e1a99902002j6qk | 个人版 Lite ¥118、团队版 ¥598 | 2026-09-02 |
| 7 | 智谱GLM Coding Plan个人版和团队版套餐哪个划算 — zestp | https://blog.zestp.com/archives/152525 | 个人版/团队版对比 | 2026-06-26 |
| 8 | Claude Code 配置智谱 coding plan — CSDN | https://blog.csdn.net/hamisay/article/details/159766216 | 社区配置经验 | 2026-07-20 |

### 8.3 关键原文引用速查（合规判断可直接引用）

| 主题 | 原文（逐字） | 出处 |
|---|---|---|
| **Coding Plan 禁止自建** | "您不得将 GLM Coding Plan 的调用额度用于上述工具以外的通用 API 接入或其他场景，包括但不限于在**自建应用**、机器人、网站、SaaS 产品或其他系统中直接调用相关模型接口，除非您与智谱另行签署书面协议。" | 订阅及自动续费协议 六.2【一手】 |
| **Coding Plan 禁止聚合转发** | "除非另有书面约定，您不得将 GLM Coding Plan 以转售、代售、转包装、**聚合转发**等方式向任何第三方提供" | 订阅及自动续费协议 六.2【一手】 |
| **"中转"入永久封禁** | "在证据充分、风险特征明确，并确认账号存在倒卖、**中转**、套利等严重违规行为时执行" | 使用须知 · 永久封禁说明【一手】 |
| **国际版点名 SDK** | "If the system detects usage through unauthorized or unsupported tools (such as **SDK-based access** or other third-party integrations), some subscription benefits may be restricted" | Z.AI subscription-terms 4.2【一手】 |
| **国际版点名 proxy** | "you may not resell, sub-resell, repackage, **aggregate, proxy** or otherwise provide the GLM Coding Plan to any third party" | Z.AI subscription-terms 4.2【一手】 |
| **标准 API 集成豁免** | "为免疑义，您将本服务依法合规**集成至您自有产品、应用或功能中**，并向该等产品、应用或功能的终端用户提供服务的，**不视为前述受限行为**" | 用户协议 三.7(7)【一手】 |
| **禁止向第三方提供** | "您不得通过出租、出借、出售、分销、转售、转让、共享账号、转授权、**二次封装、服务中转、聚合中转**或其他变相方式，**向任何第三方提供**大模型开放平台服务" | 用户协议 三.7(7)【一手】 |
| **禁止逆向** | "通过**非智谱开发、授权的第三方软件、插件、外挂、系统，登录或使用智谱软件及服务**" | 用户协议 三.4【一手】 |
| **5 倍违约金** | "要求您承担违规转售期间累计消耗金额的 **5 倍**作为违约金，已支付/充值的金额不予退换" | 用户协议 十三【一手】 |
| **仅限指定工具** | "GLM Coding Plan 仅限在以下官方支持的指定工具与产品环境中使用，**用户不得将订阅权益用于以下范围之外的工具或场景**。" | 接入工具 一、适用工具【一手】 |

---

## 附录：本报告对用户决策的三条直接建议

> 以下为本文基于上述证据的**推断性建议**，不构成法律意见。

1. **接智谱必须走"标准按量计费 API Key"**，端点用 `https://open.bigmodel.cn/api/paas/v4`（国内）或 `https://api.z.ai/api/paas/v4`（国际），Key 从 `https://bigmodel.cn/usercenter/proj-mgmt/apikeys` 获取。**这是官方设计用途，且被用户协议 7(7) 明文豁免。**
2. **绝对不要用 Coding Plan Key 接网关**。即使价格看起来更划算（低峰 5 折、额度大），它在协议里被**逐词点名禁止**（"自建应用"），且已有**真实封号案例**与**5 倍违约金**罚则。这是本次调研中**风险收益比最差的一条路**。
3. **不要用 `zhipu-account` 型账号凭据逆向 `zcode.z.ai` 私有接口**。ZCode 是智谱官方 IDE，其账号登录态属"官方客户端内部通路"，用其喂第三方工具 = 双重违反（非授权工具 + 非授权访问方式）。
4. **保持网关"纯个人自用"边界**。用户协议 7(7) 的豁免以"不向第三方提供"为要件；一旦网关对外暴露给任何他人或其他系统，即刻从"合规"翻转为"服务中转/聚合中转"，并触发最高 5 倍违约金。**这条线必须守住。**

---

*报告完成时间：2026-09-22*
*调研执行：WebSearch + WebFetch，共取证 14 个一手官方来源 + 8 个二手来源*
