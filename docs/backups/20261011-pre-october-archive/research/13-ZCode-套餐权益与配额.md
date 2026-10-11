# B · 套餐 / 权益 / 配额 机制调研

> 调研对象：`/Users/w/Desktop/zcode相关管理软件/zcode-reverse-engineer/`（下称 `RE/`，`文件:行号` 均相对该目录）· 只读，未改动任何文件。
>
> **证据分级（我的判断）**：`【一手】`= 文档/代码直接写出；`【二手】`= 旁证（社区/同工作区他稿/其他项目）；`【推断】`= 未证实；`【未找到】`= 检索无果。
>
> **⚠️ 文档自身证据强度（重要）**：本仓库是**逆向文档**，其结论强度分三档，下表逐条标注：
> - `[实测]` = 真实 API 调用验证过（OAuth 全链路、`client/configs`、`subscription/list`、`quota/limit`）
> - `[反编译]` = 从 ASAR JS Bundle 直接读出（端点、函数、字段名可信；**响应体的具体数值/结构可能是文档作者"预期"而非实测**）
> - `[推测]` = 文档自己标注的推断或未验证

## 修订记录（据独立核验 `verify-AB.md` 逐条修正）

| 原表述 | 修正后 | 类型 |
|---|---|---|
| 「不存在客户端触发领取/claim 的 API 端点」 | **把 RE 文档的结论当成了全工作区结论**。同工作区 `zcode-switch/src-tauri/src/claim.rs:9-11` 已实现 `POST /billing/claim`（含 preview + 阿里云验证码，`:272-313`）。**"激活码"确实不存在，但"客户端 claim 计划"存在** | **跨稿冲突（严重）** |
| 模型目录「**21 个模型**」 | **20 个**（9+2+2+3+2+2）。`docs/index.md:151` 写 21，与 `catalog.md` 实际条目数不一致，以目录表为准 | 硬数字错误（原稿自相矛盾） |
| 「Pro Max 倍数两文档不一致（4倍 vs 20x Lite）」 | **数学等价**：`4×Pro`、`Pro=5×Lite` → 20×Lite。两文档基准不同，**非矛盾** | 虚构矛盾 |
| 「权威字段是 `capabilities[]`，**客户端不硬编码**」→ 引 `activation-protocol.md:22`、`client-configs.md:18` | 两处原文与该结论无关。换引 `activation-protocol.md:75`、`client-configs.md:76,83`；并把"不硬编码"**限定为模型权益**——**provider 清单是硬编码的**（`catalog.md:62-73`） | 引证不支持结论 |
| 「可**绕过登录**先探权益」 | `startPlanPreview` 是**账号无关的静态套餐定义**，**不能判定该账号是否被授予**。改为「可免登录拉**套餐定义（上限口径）**；**账号级 entitlement 仍需登录**」 | 过度推论 |
| 免费额度「不是同一个东西，是同一层语义的两种叫法」 | 自相矛盾。改为「**同一概念的不同叫法**：只有 `meter:"model_usage"` 的 token 配额，**无独立积分实体**」 | 表述自相矛盾 |
| 键名 `builtin:bigmodel-coding-plan` → `billing.md:63` | `:66` | 行号差 3 |
| 「Lite=3x Claude Pro」→ `billing.md:68` | `:71` | 行号差 3 |

---

## ① 结论先行

1. **RE 文档断言"没有激活这个动作"，但同工作区已有 claim 实现 → 两者冲突。**
   - RE 原文：**不存在客户端触发领取/claim/activate 的 API 端点**，Start Plan 由**服务端自动授予** → 【一手】`docs/auth/activation-protocol.md:22` `[反编译]`。
   - **但 `zcode-switch` 已实现完整的 claim 链路**：`claim.rs:9-11` 定义 `BILLING_PREVIEW_URL` / **`BILLING_CLAIM_URL = https://zcode.z.ai/api/v1/zcode-plan/billing/preview|claim`** / `CLIENT_CONFIGS_URL`；`:217` `preview_plans()`、`:272-313` `submit_claim()`（含 `X-Aliyun-Captcha-Verify-Param` 阿里云验证码头）、`:187` `report_activation_events()` → 【一手】
   - **裁决**：**"输入激活码/兑换码领权益"确实不成立**（全库无码格式）；**但"客户端主动 claim 计划"是存在的**，且**强制过阿里云验证码**。→ 施工时以 `claim.rs` 为准，RE 文档的"不存在"只对"激活码机制"成立。
2. **兑换码 / 激活码格式：不存在。** 全仓库检索 `激活码|兑换|redeem` 无任何兑换端点或码格式定义；唯一带"码"的字段是支付参数 `invitationCode`（邀请码，非兑换码）→ 【一手】`docs/models/billing.md:103,232,244,253`。**若网关要靠"输入激活码领权益"，此路不通** → 【推断，基于全库检索无果】。
3. **有两条互不相干的请求通道，计费口径完全不同** → 【一手】`memory-notes/zcode-plan-auth-path.md:8-11`、`docs/models/free-quota.md:24-27` `[反编译]`：
   - **API Key 通道**：用户自有 BigModel/Z.ai Key，`x-api-key`，**按量计费**。
   - **Plan 通道**：Start Plan / Coding Plan 的**账号额度**，`Authorization: Bearer <zcode_jwt>`，base = `https://zcode.z.ai/api/v1/zcode-plan/anthropic`。
4. **免费额度的正确入口是 Plan 通道，不是 `api.z.ai`。** 文档点名中转站 `zcode-2api` 走 `api.z.ai/api/anthropic` + `x-api-key: JWT` **"不一定会扣免费额度"** → 【一手】`memory-notes/zcode-plan-auth-path.md:48-53` `[反编译+未实测]`。**这是对接网关最容易踩的坑。**
5. **免费额度 = 每日 token 配额，不是"积分"。** `startPlanPreview` 给出 GLM-5.3 **3,000,000 tokens/日** + GLM-5-Turbo **2,000,000 tokens/日**，`unitType: "token"`、`period: "daily"` → 【一手】`docs/models/client-configs.md:69-90,96-100` `[实测 2026-08-18]`。**全仓库没有"积分"这个词** → 【未找到】。
6. **额度数字与模型名解耦**：`showName` 官方可随时改（2026-06 是 GLM-5.2 → 2026-08 实测为 GLM-5.3），`grantUnits` 数字不变 → 【一手】`docs/models/client-configs.md:100` `[实测]`。**网关不要硬编码模型名。**

---

## ② 套餐类型全表

| 套餐 / 渠道 | 性质 | 额度来源 | 入口 | 证据 |
|---|---|---|---|---|
| **Start Plan** | 免费，登录即送，无需绑卡 | 每日 token 额度（3M+2M） | `zcode.z.ai/api/v1/zcode-plan/anthropic` + Bearer JWT | 【一手】`activation-protocol.md:11`；`client-configs.md:69-100` `[实测]` |
| **Coding Plan（付费订阅）** | 月订阅，BigModel / Z.AI 两套定价 | 订阅额度 | 同上 Plan 通道 | 【一手】`client-configs.md:111-128`；`billing.md:49-55` `[反编译]` |
| **API Key 渠道** | 用户自有 BigModel / Z.ai Key | 自有账户按量计费 | `open.bigmodel.cn/api/anthropic`、`api.z.ai/api/anthropic` + `x-api-key` | 【一手】`zcode-plan-auth-path.md:10`；`api-endpoints.md:68-71` `[反编译]` |
| **内置 provider** | 客户端预置 | 取决于所选 provider | 见 ⑦ | 【一手】`catalog.md:62-73` `[反编译]` |
| **自定义 / 第三方 provider** | 用户手配 baseURL+apiKey | 取决于上游 | `config.json` / `client-configs` | 【一手】`client-configs.md:51-57`；`catalog.md:62-73` `[反编译]` |
| **ZAPI（开发用）** | 动态发现模型 | — | `http://192.168.6.166:8080` + `/v1/models` | 【一手】`integration-subsystems.md:29,36-63` `[反编译]` |
| **激活码 / 兑换码套餐** | — | — | — | 【未找到】全库无 |

**套餐优先序**：已购 Coding Plan → 用 Coding Plan（Start Plan 不可选）；否则 Start Plan active → 用免费额度；都没有 → `coding_plan_not_entitled` → 【一手】`ANALYSIS_REPORT.md:762-773` `[反编译，文档自标 ⚠️推断]`。

**Coding Plan 定价**（两套渠道，价格不同）→ 【一手】`client-configs.md:111-128` `[反编译]`：

| 产品 | BigModel 渠道 | Z.AI 渠道 |
|---|---|---|
| GLM Coding Lite | ¥49/月 | ¥18/月 |
| GLM Coding Pro | ¥149/月 | ¥72/月 |
| GLM Coding Pro Max | ¥469/月 | — |

> ⚠️ `billing.md:51-55` 与 `client-configs.md:117-121` 对 Pro Max 的倍数表述**基准不同但换算一致**：`4×Pro`、`Pro = 5×Lite` → 4×5 = **20×Lite**（两文档数学等价，非矛盾）。Z.AI 渠道 Pro Max 缺失 → 【一手】
> 另有 `codingPlanBillingDiscount` 限时 150% 额度活动文案 → 【一手】`client-configs.md:130-145` `[反编译]`。

---

## ③ "激活协议"（实为 OAuth + 权益查询）

**前置：OAuth 2.0 授权码模式，无 PKCE、无 client_secret** → 【一手】`oauth-flow.md:12,95-97` `[实测]`。

| 步骤 | 端点 | 请求体 | 响应关键字段 | 证据 |
|---|---|---|---|---|
| 1 授权 | `GET chat.z.ai/api/oauth/authorize` | query: `response_type=code, client_id=client_P8X5CMWmlaRO9gyO-KSqtg, redirect_uri, state` | 回调 `?code=...&state=...` | 【一手】`oauth-flow.md:113-127` `[实测]` |
| 2 换 token | `POST zcode.z.ai/api/v1/oauth/token` | `{provider:"zai", code, redirect_uri, state}` | `data.zai.access_token` | 【一手】`oauth-flow.md:243-269`；`zcode_auth.py:296-336` `[实测]` |
| 3 换业务 JWT | `POST api.z.ai/api/auth/z/login` | `{token:<access_token>}` | `data.access_token` = **zcodejwttoken** | 【一手】`oauth-flow.md:302-323`；`zcode_auth.py:339-363` `[实测]` |
| 4 用户信息 | `GET chat.z.ai/api/oauth/userinfo` | Header `Authorization: Bearer <access_token>` | `sub/name/email/picture` | 【一手】`oauth-flow.md:373-390` `[实测]` |

**JWT payload 实测**：`{user_type:"PERSONAL", user_id:8009570, customer_id:"...", customer:{channel:"Z_AI", userType, enableStatus:"ENABLE", betaTester}}` → 【一手】`oauth-flow.md:326-344` `[实测]`。`user_id` / `customer_id` 可作账号唯一标识 → 【一手】`zcode_auth.py:465-467,770-777`。

**错误码**（实测 + 文档整理）→ 【一手】`oauth-flow.md:456-466,548-556` `[实测]`：

| 错误 | 含义 | 处置 |
|---|---|---|
| `HTTP 500 code=2007` | 授权码过期 | 重新授权 |
| `HTTP 401 空 body` | `zcode.z.ai` 路径认证失败 / WAF | 换正确 token / 桌面端环境 |
| `code=500` `当前用户不存在coding plan` | 无付费套餐 | 查 Start Plan |
| `HTTP 429` + `error.code="1113"` `Insufficient balance or no resource package` | 无可用资源包 | 无额度 |
| `state mismatch` | CSRF 校验失败 | 重生成 state |

**⚠️ 未解开的卡点（文档自认）**：`billing/current` 直连一律 401，Playwright 无头浏览器也 401 → 文档结论**不是 WAF JS Challenge，而是缺 `data.token`（token 交换响应里的另一个字段）** → 【一手】`activation-protocol.md:203-237` `[实测 401 / 根因 ⚠️推测]`。文档给出的两条突破路径：Playwright 真实浏览器（`scripts/activate_playwright.py`）、重新 OAuth 完整捕获 `data.token` → `activation-protocol.md:241-258`。**注意 `oauth-flow.md:253-269` 的实测响应里并没有 `data.token` 字段** → 【推断：两文档对 `data.token` 存在性说法不一致，需实测**】。

---

## ④ 鉴权路径：登录后怎么判断"我有什么权益"

**四条查询端点**（全部 `Authorization: Bearer <zcode_jwt>`，除 configs 外）→ 【一手】`api-endpoints.md:57-64`：

| 端点 | 用途 | 状态 | 证据 |
|---|---|---|---|
| `GET zcode.z.ai/api/v1/zcode-plan/billing/current?app_version=` | **Start Plan 账单/权益** | ⚠️ 直连 401 | 【一手】`free-quota.md:52-53`；`activation-protocol.md:141-146` `[实测 401]` |
| `GET zcode.z.ai/api/v1/zcode-plan/billing/balance` | Start Plan 余额 | ⚠️ 同上 | 【一手】`free-quota.md:54` `[反编译]` |
| `GET api.z.ai/api/biz/subscription/list` | Coding Plan 订阅 | ✅ 可用，免费用户返回 `{"code":200,"data":[]}` | 【一手】`oauth-flow.md:412-427`；`free-quota.md:60` `[实测]` |
| `GET api.z.ai/api/monitor/usage/quota/limit` | 用量配额 | ✅ 可用，免费用户 `{"code":500,"msg":"当前用户不存在coding plan"}` | 【一手】`oauth-flow.md:429-443`；`free-quota.md:61` `[实测]` |
| `GET zcode.z.ai/api/v1/client/configs?app_version=` | **客户端配置（免认证）** | ✅ 可用 | 【一手】`client-configs.md:9-13,63-65` `[实测]` |

**判定逻辑（反编译）**：
- `billing/current` → `data.plans[].status === "active"` 且 `plan_id/name` 含 `start-plan` → Start Plan 可用 → 【一手】`activation-protocol.md:149-162` `[反编译]`。
- 无额度时 `billing/current` 返回 `kind:"unavailable", reason:"coding_plan_not_entitled"` → 【一手】`zcode-plan-auth-path.md:44` `[反编译]`。
- `fetchZaiPlanEntitlementState` **并行**查 `billing/current`(start) 与 `subscription/list`(coding)，返回 `{authenticated, startEntitled, codingEntitled}` → 【一手】`activation-protocol.md:165-175` `[反编译]`。
- **可免登录拉取"套餐定义"（额度上限口径）**：`client/configs` 免认证，`data.configs.startPlanPreview` 直接给免费额度配置，**登录与否返回一致** → 【一手】`client-configs.md:65,107` `[实测]`。
  ⚠️ **但注意**：`startPlanPreview` 是**账号无关的静态套餐定义**，**不能判定某账号是否真的被授予了额度** —— **账号级 entitlement 仍需登录**（查 `billing/current`）。前者可作额度池的**元数据/上限**，后者才是**该账号的真实可用量**。
  → **这是网关最省事的一手数据源（拿定义），但不是账号额度的替代品。**

---

## ⑤ 积分 / 配额体系

### 5.1 额度的真实形态：**token 计数，不是积分**

`client/configs` → `data.configs.startPlanPreview` 实测响应 → 【一手】`client-configs.md:69-90` `[实测]`：

```json
{ "entitlements": [
    {"grantUnits":3000000,"meter":"model_usage","period":"daily","showName":"GLM-5.3","unitType":"token"},
    {"grantUnits":2000000,"meter":"model_usage","period":"daily","showName":"GLM-5-Turbo","unitType":"token"} ],
  "name":"Start Plan", "planId":"zcode-v3-start-plan" }
```

| 问题 | 答案 | 证据 |
|---|---|---|
| 积分的种类 | **文档无"积分"概念**；唯一额度单位是 token（`unitType:"token"`、`meter:"model_usage"`） | 【一手】`client-configs.md:69-90`；【未找到】"积分"字样 |
| 查询端点 | 免认证：`client/configs`→`startPlanPreview`；带 JWT：`billing/current`→`plans[]`、`billing/balance`→`balances[]` | 【一手】`free-quota.md:50-54` |
| 响应结构 | `plans[]: {plan_id,status,total_units,used_units,available_units,period_end,capabilities[]}`；`balances[]: {entitlement_id,total_units,used_units,available_units}` | 【一手】`activation-protocol.md:63-85`；`ANALYSIS_REPORT.md:741-760` `[反编译，数值为示例]` |
| 有效期 / 重置 | `period:"daily"`，**每日重置**；`period_end` 为下次重置时间戳 | 【一手】`client-configs.md:96-100`；`activation-protocol.md:74` |
| 免费额度 = 积分吗 | **同一概念的不同叫法**：文档中额度实体只有 `meter:"model_usage"` 的 **token 配额**，**无独立"积分"实体**（用户侧可能把 token 额度口语化为"积分"） | 【推断，基于 `client-configs.md:69-100` 无积分实体】 |

**两个模型独立计算、每日重置**；文档**明确否定**了早先"5 小时 prompt 池"的猜测 → 【一手】`client-configs.md:99` `[实测]`。
**注意矛盾**：`ANALYSIS_REPORT.md:714-723` 仍列了「Prompt 池 5 小时 / 每周额度 / MCP 每月额度」四个维度（来源为官网用量页文案）→ 【二手，官网文案】；与 `client-configs.md:99` 的实测结论冲突，**以后者为准** → 【推断】。

### 5.2 扣减时机

免费额度**由服务端在模型调用时自动授予并扣减**，不体现在 `billing/current` 里；`billing/current` 401 通常只是 JWT 过期，**不代表没有免费额度** → 【一手】`free-quota.md:18,65`；`client-configs.md:105` `[反编译+实测说明]`。

---

## ⑥ 模型权益与目录

### 6.1 某账号能用哪些模型（权益侧）

- `billing/current` → `plans[].capabilities = ["model:glm-5.1","model:glm-5-turbo"]` → 【一手】`activation-protocol.md:75` `[反编译，文档标为"预期响应"，未实测]`。
- `startPlanPreview.entitlements[].showName` 给出免费档可用模型名（GLM-5.3 / GLM-5-Turbo）→ 【一手】`client-configs.md:76,83` `[实测]`。
- **结论**：判断**某账号可用哪些模型**的权威字段是 `capabilities[]` + `entitlements[].showName`，**都来自服务端**（`activation-protocol.md:75`、`client-configs.md:76,83`）→ 【一手】。
  ⚠️ **但限定范围**：这里说的是**模型权益**不硬编码；**provider 清单是硬编码的**（`catalog.md:62-73` 的 `PRESET_PROVIDERS` 就写死在客户端）。两者不要混为一谈。

### 6.2 模型目录（能力侧）

- 来源文件 `resources/model-providers/models_catalog_*.json`，Schema `zcode.model-providers.v1`，**20 个模型** → 【一手】`catalog.md:9-55`；`ANALYSIS_REPORT.md:45,491-493` `[反编译，完整解析]`。
  ⚠️ **数字口径说明**：`docs/index.md:151` 写"21个模型"，但 `catalog.md` 逐条枚举为 **20**（9+2+2+3+2+2），**以目录表为准**（index 页的 21 与实际条目数不一致）。
- 分组：GLM 9 个（glm-5.1/-highspeed/glm-5/glm-5-turbo/glm-4.7/-flash/glm-4.6/glm-4.5/glm-4.6v）、DeepSeek 2（v4-flash/pro，1M 上下文）、Kimi 2（k2.6/k2.5）、Qwen 3（3.5-plus/flash、3-max）、MiniMax 2（M3/M2.7）、小米 MiMo 2（v2.5-pro/v2.5）→ 【一手】`catalog.md:9-55` `[反编译]`。
- 每条含 `上下文 / 最大输出 / 推理开关`，部分模型标 `❌ off`（如 glm-4.6v、qwen3-max、MiniMax）→ 【一手】`catalog.md:19,41,47-48`。
- **目录是本地静态 JSON，非远端端点拉取**（`client/configs` 不含模型列表）→ 【推断，基于 `client-configs.md:51-57` 配置项清单无模型目录】。

---

## ⑦ provider 配置

**内置 provider（`PRESET_PROVIDERS`，10 条）** → 【一手】`catalog.md:62-73`；`ANALYSIS_REPORT.md:474-489` `[反编译]`：

| id | name | baseURL |
|---|---|---|
| `bigmodel` | Bigmodel - API Key | `https://open.bigmodel.cn/api/anthropic` |
| `zai` | Z.ai - API Key | `https://api.z.ai/api/anthropic` |
| `zaiStartPlan` | Z.ai - Coding Plan | （运行时由 env/origin 构建） |
| `bigmodelStartPlan` | BigModel - Coding Plan | 同上 |
| `claude` / `glm` / `codex` / `opencode` / `gemini` | 直连/本地引擎 | 无硬编码 baseURL |
| `zapi` | ZAPI | `http://192.168.6.166:8080`（**开发环境内网地址**） |

**鉴权头决策（关键）** → 【一手】`zcode-plan-auth-path.md:24-30`；`free-quota.md:40-48` `[反编译]`：

```js
let g = i?.providerId && jt(i.providerId)
    ? { Authorization: `Bearer ${a}` }   // 走订阅/免费额度 → JWT
    : { "x-api-key": a };                // 走 API Key → 密钥
// jt = providerId ∈ {zaiCodingPlan, zaiStartPlan, bigmodelCodingPlan, bigmodelStartPlan, zapi}（TX 集合）
```

**关于"6 个 builtin provider"**：主对象仓库**未找到** 6 条 builtin 清单 → 【未找到】。仅见一处键名 `"builtin:bigmodel-coding-plan"` → 【一手】`billing.md:66`。旁证（同工作区 A 稿，非本对象）列出 6 条：`builtin:zai` / `-start-plan` / `-coding-plan` / `builtin:bigmodel` / `-start-plan` / `-coding-plan` → 【二手】`docs/research/zcode-drafts/A-账号接入与切换.md:54-55`。**结论：命名规律是 `builtin:<family>[-<tier>]`，6 条说法有旁证但主对象未覆盖，需以客户端 `config.json` 实测为准** → 【推断】。

**第三方 / 自定义 provider**：`client/configs` 是免认证的配置源（含 `codingPlanStaticProducts`、`codingPlanBillingDiscount`、`captcha`、`feedbackUrl`），客户端 1 小时缓存、15s 超时 → 【一手】`client-configs.md:19-20,51-57`。`PRESET_PROVIDERS` 外可加自定义（A 稿显示落在 `~/.zcode/v2/config.json` 的 `provider.<id>`，`source:"custom"`）→ 【二手】`A-账号接入与切换.md:40-57`。
`codingPlanStaticProducts` 结构：`{"builtin:bigmodel-coding-plan":[{productId, productName, monthlyPayAmount, priceCurrency, priceUnit, productEquityList[]}]}` → 【一手】`billing.md:62-85` `[反编译]`。

**格式映射** → 【一手】`catalog.md:80-86`：claude=`anthropic`；glm=`anthropic,responses,openai`；codex=`responses,openai`；opencode/gemini=`openai`；zai/bigmodel=`anthropic,openai`。

---

## ⑧ 计费口径

| 问题 | 答案 | 证据 |
|---|---|---|
| 按 token 还是按次？ | **按 token**：额度字段 `unitType:"token"`、`meter:"model_usage"`、`total_units/used_units/available_units` | 【一手】`client-configs.md:69-90`；`activation-protocol.md:77-82` |
| 有按次/按条计费吗？ | 【未找到】无次数计费字段 | — |
| 付费套餐怎么计费？ | **按月订阅**（`priceUnit:"month"`、`monthlyPayAmount`），非按量 | 【一手】`billing.md:71-75` |
| 支付渠道 | 支付宝/微信（`/pay/create-sign`）、Stripe（`/stripe/*`）、PayPal（`/paypal/*`） | 【一手】`billing.md:166-192` |
| 订阅激活后的状态串 | `coding_plan_zai_overseas_payment_required` / `not_auth` / `auth_failed` / `not_entitled` / `oauth_provider_inactive` | 【一手】`billing.md:263-269`；`ANALYSIS_REPORT.md:559-568` |
| token 单价 / 汇率 | 【未找到】文档无 token 定价表；只给了"Lite=3x Claude Pro 用量"这类相对口径 | 【一手】`billing.md:71` |

---

## ⑨ 可复用点清单

| 机制 | 文件:行号 | 我们能不能用 |
|---|---|---|
| **免认证拉免费额度配置**（`client/configs` → `startPlanPreview`） | 【一手】`client-configs.md:9-13,69-90` | ✅ **能，最优先**。不碰登录、不碰 WAF，直接拿 3M+2M 日额度配置做额度池元数据 |
| **JWT 三连交换**（code→access_token→business JWT） | 【一手】`oauth-flow.md:243-323`；`zcode_auth.py:294-363` | ✅ 能。Python 已实现，可移植为网关账号导入流程 |
| **JWT 双用法**：`Bearer`（权益）/ `x-api-key`（AI） | 【一手】`oauth-flow.md:346-354` | ✅ 能。网关按上游类型切 header |
| **provider→鉴权头决策表**（TX 集合） | 【一手】`zcode-plan-auth-path.md:24-30` | ✅ 能。直接抄这张"哪些 provider 用 Bearer"的映射 |
| **Plan 通道 base + Bearer**（免费额度正确入口） | 【一手】`zcode-plan-auth-path.md:11,48-53` | ⚠️ 能，但**文档标注"需实测确认"**：`zcode.z.ai/api/v1/zcode-plan/anthropic/v1/messages` + Bearer 是否对免费号返回响应、是否扣额度，均未实测 |
| **权益判定逻辑**（`plans[].status==="active"` + plan_id 含 `start-plan`） | 【一手】`activation-protocol.md:149-162` | ✅ 能。判定函数可 1:1 复刻 |
| **额度结构解析**（plans/balances/capabilities/period_end） | 【一手】`activation-protocol.md:63-85`；`ANALYSIS_REPORT.md:741-760` | ⚠️ 能，但**结构来自"预期响应"，实测被 401 挡住**，字段名可信、数值形态待验证 |
| **`entitlements[]` 校验函数**（5 字段类型检查） | 【一手】`client-configs.md:182-208` | ✅ 能。直接复用做响应校验 |
| **免认证配置缓存策略**（1h 缓存 + 请求去重 + 15s 超时） | 【一手】`client-configs.md:19-20,22-44` | ✅ 能。网关侧限频参考 |
| **模型目录 JSON**（21 模型 + 上下文/输出/推理开关） | 【一手】`catalog.md:9-55` | ✅ 能。可直接作网关模型元数据（注意是静态快照，会过期） |
| **capabilities 判可用模型** | 【一手】`activation-protocol.md:75` | ⚠️ 能，但未实测 |
| **Coding Plan 订阅查询**（免费用户空数组判据） | 【一手】`free-quota.md:60`；`oauth-flow.md:419-427` | ✅ 能。`data==[]` 即免费用户 |
| **额度预检接口**（`quota/limit` 的 500 文案判据） | 【一手】`free-quota.md:61`；`zcode_auth.py:700-707` | ✅ 能。用文案 `不存在coding plan` 判无付费套餐（脆，建议同时看 code） |
| **Coding Plan 定价表 / 产品 ID 结构** | 【一手】`client-configs.md:111-128`；`billing.md:62-85` | ⚠️ 仅供参考，网关不需要卖套餐 |
| **领取权益端点**（preview / claim / configs） | 【一手】`zcode-switch/src-tauri/src/claim.rs:9-11`（`BILLING_CLAIM_URL`） | ✅ **能**（`A-账号接入与切换.md` ⑦#20 已记）。⚠️ 注意 RE 文档断言"不存在 claim 端点"（`activation-protocol.md:22`），**与实现冲突，以实现为准**；且 claim **强制过阿里云无痕验证码** |
| **激活码 / 兑换码机制** | — | ❌ **不存在**，【未找到】，不要按此设计 |
| **`data.token` 字段** | 【一手】`activation-protocol.md:236`（推测）/ 与 `oauth-flow.md:253-269` 实测矛盾 | ❓ **必须先实测确认**，是打通 `billing/current` 的关键未知数 |
| **ZAPI 动态模型发现**（`GET /v1/models`） | 【一手】`integration-subsystems.md:36-63` | ❌ 内网开发地址，无实用价值 |

---

## ⑩ 未解决项

1. **`billing/current` 的 401 根因未闭合**：文档推测缺 `data.token`，但同仓库 `oauth-flow.md` 的实测响应体里没有该字段 → 需重新 OAuth 抓完整响应确认。【关键阻塞点】
2. **`plans[]` / `balances[]` 真实响应结构未实测**：现结构是文档"预期响应"，字段名可信、数值与 `capabilities` 形态待验证。
3. **Plan 通道（`zcode-plan/anthropic`）对免费号是否真扣免费额度**：文档明确写"需实测确认" → `zcode-plan-auth-path.md:53`。
4. **免费额度是否有除 daily 外的维度**（5h prompt 池 / 周额度 / MCP 月额度）：两文档结论冲突（`client-configs.md:99` vs `ANALYSIS_REPORT.md:714-723`）。
5. **"积分"是否存在**：全库无该概念，但用户侧可能把 token 额度口语化为"积分" → 需与产品口径对齐。
6. **6 个 builtin provider 的权威清单**：主对象未覆盖，仅有旁证 A 稿与一个 `builtin:bigmodel-coding-plan` 键名。
7. **`coding_plan_not_entitled` 之外的 reason 枚举**：只见这一个，其余未知。
8. **额度扣减的计量精度**：input/output token 如何折算成 `used_units`、是否含缓存命中折扣 → 文档未涉及。
9. **文档时效**：主对象最新实测为 2026-08-18（`free-quota.md:3`），模型名已从 GLM-5.2 漂到 5.3，**接入前必须重跑一次 `client/configs` 与一次真实模型调用**。
