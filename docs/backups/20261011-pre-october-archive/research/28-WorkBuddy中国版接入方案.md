# 28 · WorkBuddy（中国版）产品接入方案

> **本文性质**：**方案设计 + 实测证据**（不是纯推断）。凡「已实测」均附可复跑的原始命令 / 原始输出 / `file:line`；取不到的写「未验证」。
> **实测时间**：2026-10-10 13:4x–14:1x（本机 macOS，`/Applications/WorkBuddy.app` v5.6.2）
> **调研对象**：`/Users/w/Desktop/trae-helper`（第一手逆向：`AIWork_Helper/workbuddy.py`）、本机两个 WorkBuddy 客户端包、DSH 参考源 `deepseek-harness-codearts/src/product.ts`、网关既有 `upstream/buddy/` + `upstream/workbuddy/`
> **交付边界**：本文件 = **接入方案**（设计定稿候选）。**未落任何代码改动**（铁律 4：一切以需求真相与用户确认为唯一依据；方案经用户确认后再进实施波次）。
> **红线自查**：只读操作（读包内 `product.json` / `app.asar`、读本机凭据文件、对腾讯官方端点发只读请求）；**未改写任何被调研项目、未改动网关任何文件**。

---

## 0. 结论先行

**结论：WorkBuddy（中国版）可以接入，且属于「参数化新增」而非「第二份实现」——与 CodeBuddy（buddy）／WorkBuddy 国际版（workbuddy）共用同一套 `upstream/buddy/hooks.py` + `protocol.py`，本产品只声明差异参数。**

一句话概括三个产品的区别（**全部逐条实测**，见 §3）：

| | CodeBuddy（在册 `buddy`） | WorkBuddy 国际版（在册 `workbuddy`） | **WorkBuddy 中国版（本方案新增）** |
|---|---|---|---|
| 客户端 | `CodeBuddy CN.app` | `WorkBuddy AI.app` | **`WorkBuddy.app`** |
| bundle id | `com.tencent.codebuddycn` | `com.workbuddy.workbuddy-ai` | **`com.tencent.workbuddy.mac`** |
| 上游基址 | `https://copilot.tencent.com` | `https://www.workbuddy.ai` | **`https://www.workbuddy.cn`** |
| 认证 platform | `ide` | `workbuddy-ai` | **`workbuddy`** |
| `X-Product-Code` | `codebuddy` | `workbuddy` | **`workbuddy`** |
| UA（客户端形态） | `CodeBuddyIDE/1.106.1` | `WorkBuddy/5.5.2 WorkBuddy AI/5.5.2 CLI/5.5.2` | **`WorkBuddy/5.5.2 WorkBuddy/5.5.2 CLI/5.5.2`** |
| 登录 URL 附加参数 | 不追加 | 追加 `version` + `loginSessionId` | **追加 `version` + `loginSessionId`** |
| 额度 | ✓ | ✓ | **✓** |
| 签到 | ✓ | **✗（后端无签到端点）** | **✓（有签到端点）** |
| 首条必须 `system` | ✗ | **✓（否则 400 code 11128）** | **✗（实测首条 user 直接 200）** |
| 模型目录 | remote `/v3/config` + 兜底表(16) | remote `/v3/config` + 兜底表(23) | **remote `/v3/config` + 兜底表(16)** |

**三处与既有实现的关键差异**（也是本方案必须显式表态的地方）：

1. **签到能力位 `checkin=True`** —— 与国际版相反（国际版 False）。不能照抄国际版的档案。
2. **`system_first_text` 留空** —— 与 buddy 同、与国际版相反。**实测**中国版通道对首条非 system 的请求直接 200（§3.4），凭空注入引导文案就是给没这条脾气的通道加噪音。
3. **`_ATTRIBUTION_BY_PRODUCT` 必须补一行** —— `protocol.py` 的推理面归属头是**按 id 查表、缺项当场 `ValueError`**（`protocol.py:248-260`）；不补则 `build_out` 一调就炸（不是静默降级）。

**唯一需要用户拍板的外部因素**：中国版登录页 `platform=workbuddy` 会深链 `workbuddy://` 唤起本机 App —— 与并行会话 2026-10-10 已定位的国际版 `workbuddy-ai://` 问题**同源同形**（见 §7-R1、§9-D3）。

---

## 1. 调研：trae-helper 如何识别 WorkBuddy（中国版）登录态、如何自动化签到

调研对象：`/Users/w/Desktop/trae-helper/AIWork_Helper/workbuddy.py`（728 行，独立模块，2026-09-01 首版）+ `.pm/decisions.md` / `.pm/pitfalls.md` 的决策与坑位记录。

### 1.1 登录态识别（读凭据文件，不做网络握手）

| 项 | 值 | 出处 |
|---|---|---|
| 凭据文件 | `~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info` | `workbuddy.py:45-47` |
| 格式 | **明文 JSON**（`account` 节 + `auth` 节） | `workbuddy.py:8-11`、`.pm/decisions.md:292-297` |
| 路径推导 | `filePathService.sharedDataPath = Extension数据目录/Data/Public/auth/<认证 id>.info`；`<认证 id>` 取自 `cli/product.json` 的 `authentication.id` | `.pm/decisions.md:293-294` |
| 登录态判据 | 读文件 → `account.uid` 与 `auth.accessToken` **都非空** = 已登录；文件不存在 / 解析失败 / 任一为空 = 未登录 | `workbuddy.py:113-133`（`load_workbuddy_context`） |
| 有效期 | `accessToken` 60 天 / `refreshToken` 90 天 | `workbuddy.py:10`、`.pm/decisions.md:295` |
| 账号切换 | 写回该 `.info`（写前 `.bak`、写后读回校验 uid、失败回滚） | `workbuddy.py:435-466` |
| 备份账号发现 | 客户端切号时自动留历史 `.info`，`accounts/workbuddy/*.json` 即档案源 | `workbuddy.py:136-167`、`.pm/decisions.md:309-310` |

**关键点：识别登录态完全不发网络请求**——只看本地文件。这与网关的「凭据由自己 OAuth 登录取得、存在账号目录」是**两条完全不同的路子**（网关不读桌面端凭据文件，见 §4.7）。

**本机交叉验证**（2026-10-10 实读，token 已脱敏）：

```
workbuddy-desktop.info      → account.uid=db3c36d6-…, auth.domain=www.workbuddy.cn, expiresIn=2419200(28天)
workbuddy-desktop-ai.info   → account.uid=77091ff4-…, auth.domain=www.workbuddy.ai,  expiresIn=31446832
```
两个产品的凭据**同目录、不同文件名**（`workbuddy-desktop` vs `workbuddy-desktop-ai`），与各自 `product.json` 的 `authentication.id` 一一对应 —— **这是「认证 id 决定文件名」的直接证据**。

### 1.2 自动签到（接口直签，无设备签名）

| 项 | 值 | 出处 |
|---|---|---|
| 查活动状态 | `POST https://copilot.tencent.com/v2/billing/meter/checkin-activity-status` | `workbuddy.py:221-226` |
| 领取当日积分 | `POST https://copilot.tencent.com/v2/billing/meter/daily-checkin` | `workbuddy.py:330-350` |
| 查资源包余额 | `POST https://copilot.tencent.com/billing/meter/get-user-resource-summary`（**无 `/v2` 前缀**） | `workbuddy.py:229-254`、`API_BASE_RES` `:57` |
| 鉴权 | `Authorization: Bearer <accessToken>` + `X-User-Id: <uid>`，`-d '{}'` 空体 | `workbuddy.py:197-218` |
| 设备签名 | **不需要**（`X-Device-Token` 图灵盾可选，不带也成功） | `.pm/decisions.md:288-291`、`pitfalls.md:161-163` |
| 幂等 | 业务码 `0` = 成功；`10001` = 今日已签（**不是失败**） | `workbuddy.py:60-61,347-348` |
| 活动窗口 | `active=false` → 静默 `Skip`（文案「签到活动未开启」，不计失败） | `workbuddy.py:324-326` |
| 调度 | launchd 每日任务 `com.trae-helper.checkin.workbuddy`（默认 09:00，Web UI 可改）；另有「当日已执行」marker 防重 | `.pm/decisions.md:304-307`、`workbuddy.py:365-378` |

**本机实测复核**（2026-10-10，中国版账号 `db3c36d6`，**只读**）：

```
POST www.workbuddy.cn/v2/billing/meter/checkin-activity-status
→ {"code":0,"data":{"active":true,"today_checked_in":true,"streak_days":11,
     "daily_credit":100,"total_credits":1100,"theme_name":"Buddy加油站","season":10,
     "start_time":"2026-09-30 00:00:00","end_time":"2026-10-15 23:59:59", ...}}
```
→ **签到端点在中国版域名上真实存在且可用**，响应 schema 与 CodeBuddy（buddy）**完全同构**。

### 1.3 旁证：账号切换与会话跟随（说明产品形态，非本方案改动面）

`workbuddy.py:471-628` 的 `transfer_sessions` 覆盖五处本地数据（`workbuddy.db` 的 `sessions.user_id` / `automations.owner_user_id` / `automation_runs.metadata_json` / `app/sessions.json` / `memory/<uid>_memory.md`），提交后回读校验、失败恢复备份。**这是桌面端多账号运营的事**，与网关的「账号 = 一组凭据」模型不同轴 —— 本方案**不涉及**，仅说明 WorkBuddy 中国版是「双账号会话共存一库、按 uid 隔离」的产品形态。

### 1.4 诚实标注：trae-helper 的这套读法**正在失效**

- 本机**当前**的 `workbuddy-desktop.info`（2026-10-09 12:48 写）里 `auth.accessToken` 已是**加密信封** `{"$wbEncrypted":1,"envelope":{…}}`，`account.nickname` 同理 —— 客户端升级后**新增了本地加密**（trae-helper 已知 nickname 加密，`.pm/pitfalls.md:302-308`；accessToken 加密是本轮新观察，**未在 trae-helper 记录中出现**）。
- trae-helper 的 `_archived_token`（`workbuddy.py:71-82`）对 dict 型 token 会 `str(dict)` 出一个**假 token**，据此发请求必然 401。
- **它当前仍能用，靠的是 `accounts/workbuddy/*.json` 里的旧明文档案**（本机实测：`22daa8de`/`906d3629`/`db3c36d6` 三份的 `accessToken` 均为 `str`，len 1294–1460，`domain=www.workbuddy.cn`）。
- **对网关的启示**：网关**不走这条路**（不读桌面端凭据文件、不依赖本地明文），而是自己跑 `cli-external-link` OAuth 拿 token 存进账号目录（§4.7）⇒ **桌面端本地加密与网关无关**。这条只是「调研对象现状」的如实记录，同时**反向印证了网关路线更稳**。

---

## 2. 三个产品的身份对照（谁是谁 —— 证据逐条）

**为什么必须先把这件事钉死**：仓库里 `buddy` 的名字叫 CodeBuddy 但模块名是 `buddy`，`workbuddy` 的标题是「国际版」而 platform 是 `workbuddy-ai` —— 极易把「WorkBuddy 中国版」误当成 `buddy` 或 `workbuddy` 的别名。**它们是三个不同的产品**。

### 2.1 桌面端 `cli/product.json`（最权威的一手证据）

**`/Applications/WorkBuddy.app`（中国版，v5.6.2，`com.tencent.workbuddy.mac`）**：

```json
"productName": "WorkBuddy",
"endpoint": "https://www.workbuddy.cn",
"stagingEndpoint": "https://staging.workbuddy.cn",
"officialEndpoints": ["https://www.workbuddy.cn", "https://staging.workbuddy.cn",
                      "https://wb.tencentbuddy.com", "https://copilot.tencent.com", …],
"authentication": {
  "id": "workbuddy-desktop",            ← 凭据文件名 workbuddy-desktop.info 的来源
  "type": "cli-external-link",
  "attributes": {
    "usernameHeader": "X-User-Id", "tokenHeader": "Authorization", "tokenType": "bearerToken",
    "prefixPath": "/plugin",
    "internalDomain": ["copilot.tencent.com", "www.codebuddy.cn", "www.workbuddy.cn", …],
    "platform": "workbuddy"             ← 认证 platform
  }
}
```

**`/Applications/WorkBuddy AI.app`（国际版，v5.7.6，`com.workbuddy.workbuddy-ai`）**：

```json
"productName": "WorkBuddy AI",
"endpoint": "https://www.workbuddy.ai",
"authentication": { "id": "workbuddy-desktop-ai", "type": "cli-external-link",
                    "attributes": { "platform": "workbuddy-ai", "prefixPath": "/plugin", … } },
"config": { "customUserDataDir": ".workbuddy-ai" }     ← 只有国际版设了这个
```

> 中国版**没有** `customUserDataDir` ⇒ 数据目录取默认 `.workbuddy`；国际版显式 `.workbuddy-ai`。这与 PRD Q25-⑨（`prd.md:649`）「按产品标识 → dataFolderName 解析」逐字一致。

### 2.2 中国版 `app.asar` 内的请求身份（mmap 定位，逐条）

```js
// 计费/消息中心：X-Product-Code 恒为 workbuddy
this.productHeaders = { headers: { "X-Product-Code": "workbuddy" } };

// 推理面身份头（与网关 inference_headers 同形）
headers["X-IDE-Type"] = "WorkBuddy";
headers["X-IDE-Name"] = "WorkBuddy";
headers["X-IDE-Version"] = appVersion;
headers["X-Private-Data"] = "true";
headers["User-Agent"] = [`WorkBuddy/${appVersion}`, `WorkBuddy/${appVersion}`,
                         ...cliVersion ? [`CLI/${cliVersion}`] : []].join(" ");
headers.set("X-Agent-Purpose", "conversation");
// 另有网关未发的 X-Agent-Intent: craft / x-codebuddy-request: 1 / X-Request-ID 等
```

```js
// 登录 URL 装饰：version 恒追加；loginSessionId 仅当 platform === "workbuddy"
url.searchParams.append("version", version);
if (globalLoginSessionId && platform?.toLowerCase() === "workbuddy")
    url.searchParams.set("loginSessionId", globalLoginSessionId);
```

→ **`platform === "workbuddy"` 正好是中国版** ⇒ 中国版**需要** `version` + `loginSessionId`（`append_session_params=True`）。

```js
// 计费前缀（Desktop 子类覆写；基类为空串）
get billingPrefix() { return "/v2"; }      // 老接口 get-user-resource / checkin-* 走 /v2
get resourcePrefix() { return ""; }        // summary / paid-packages / free-packages 无前缀
```

→ 与网关既有常量**逐字吻合**：`protocol.py:47-51` 的 `CHECKIN_ACTIVITY_STATUS_PATH`/`DAILY_CHECKIN_PATH`/`USER_RESOURCE_PATH` 都带 `/v2` ⇒ **共享实现原样可用**。

### 2.3 DSH 参考源 `src/product.ts` 的对照

```ts
// product.ts:70-71
const WORKBUDDY_UA_INTL = 'WorkBuddy/5.5.2 WorkBuddy AI/5.5.2 CLI/5.5.2'
const WORKBUDDY_UA_CN   = 'WorkBuddy/5.5.2 WorkBuddy/5.5.2 CLI/5.5.2'   ← 中国版形态

// product.ts:268-284  CODEBUDDY:  platform 'ide',          endpoint copilot.tencent.com
// product.ts:381-408  WORKBUDDY:  platform 'workbuddy-ai', endpoint www.workbuddy.ai
//                     userAgentByModelFamily: gpt-/gemini-/claude- → INTL；glm-/hy/kimi-/minimax- → **CN**
```

**三条结论**：
1. DSH **没有**中国版产品实例（`ALL_PRODUCTS = [CODEBUDDY, WORKBUDDY]`），但其常量表里**已经写下了中国版 UA**（`WORKBUDDY_UA_CN`），且注明「国内系模型（glm/hy/kimi/minimax）虽在国际版池中也可见，但仍沿用国内客户端形态」—— 说明中国版形态是**已被识别的真实存在**。
2. 网关的 `workbuddy` 档案取的是 `WORKBUDDY_UA_INTL`（`upstream/workbuddy/product.py:114`）⇒ 确认在册 `workbuddy` = **国际版**。
3. 中国版的新档案应取 `WORKBUDDY_UA_CN`。

### 2.4 与网关注册表现状的对齐

`accounts/registry.py:78` 的注释早已写明：

> `title="WorkBuddy（国际版）"` — 2026-09-30 用户反馈：与参考程序 `jet-hub.js` 的标签同口径，**避免与「国内 WorkBuddy（workbuddy.cn）」混淆**

→ **本方案补的正是这条注释里点名的那个产品**。不是新发现，是既有认知的补齐。

---

## 3. 本机实测证据（2026-10-10，可复跑）

> 复跑前置：取一份中国版明文 token。**只读**（`GET /v3/config`、`POST checkin-activity-status`、`POST get-user-resource*`）—— 全程**未调用 `daily-checkin`**（不产生任何领取动作）。

### 3.1 域名与端点存活（免认证）

```
GET  https://www.workbuddy.cn/v3/config                        → HTTP 200 application/json
POST https://www.workbuddy.cn/v2/billing/meter/checkin-activity-status → HTTP 401（需鉴权）
GET  https://copilot.tencent.com/v3/config                     → HTTP 200 application/json
GET  https://www.workbuddy.ai/v3/config                        → HTTP 200 application/json
```
→ 中国版域名**真实承载**同一套 API 面（`/v3/config`、`/v2/billing/meter/*`）。

### 3.2 模型目录（带认证）

```
GET https://www.workbuddy.cn/v3/config    (Bearer + X-Domain: www.workbuddy.cn
                                           + X-Product-Code: workbuddy + UA_CN)
→ code=0，data.models **55 条**；data.agents[0].name = "cli"（modelTags=["craft"]）
```
- **`copilot.tencent.com/v3/config` 用同一 token 返回**逐条相同**的 55 条**（`workbuddy.cn 独有 = []`、`copilot 独有 = []`、交集 55）⇒ 两域名同一后端；**取基址用产品声明值 `www.workbuddy.cn` 是对的**（不跟 `copilot.tencent.com` 走，避免身份标识发到另一区域，`protocol.py:118-120` 的口径）。
- **`cli` agent 白名单 17 条**（= IDE 输入框实际可选的清单）：

| # | id | name | ctx | max_out | img | supportedEfforts |
|---|---|---|---|---|---|---|
| 1 | `auto` | Auto | 256000 | 32000 | ✓ | —（`reasoning.effort=high`） |
| 2 | `hy4-preview` | Hy4 preview | 300000 | 64000 | ✓ | high |
| 3 | `hy3` | Hy3 | 192000 | 64000 | ✓ | low, high |
| 4 | `hy3-x` | Hy3 | 192000 | 64000 | ✓ | low, high |
| 5 | `space-bunny` | Space-Bunny | 1000000 | 128000 | ✓ | low, medium, high, xhigh, max |
| 6 | `deepseek-v4.1-flash` | Deepseek-V4.1-Flash | 300000 | 128000 | ✓ | low, high, max |
| 7 | `glm-5.3` | GLM-5.3 | 300000 | 64000 | ✓ | low, high, max |
| 8 | `glm-5.3-flash` | GLM-5.3-Flash | 300000 | 131072 | ✓ | low, high, max |
| 9 | `glm-5.2` | GLM-5.2 | 300000 | 64000 | ✓ | high, xhigh |
| 10 | `glm-5.1` | GLM-5.1 | 200000 | 48000 | ✓ | —（effort=medium） |
| 11 | `glm-5v-turbo` | GLM-5v-Turbo | 200000 | 64000 | ✓ | —（effort=medium） |
| 12 | `minimax-m3` | MiniMax-M3 | 300000 | 64000 | ✓ | —（effort=medium） |
| 13 | `kimi-k3-1` | Kimi-K3 | 300000 | 32000 | ✓ | low, high, xhigh |
| 14 | `kimi-k2.8-preview` | Kimi-K2.8-Preview | 300000 | 64000 | ✓ | low, high, max |
| 15 | `kimi-k2.7` | Kimi-K2.7-Code | 256000 | 32000 | ✓ | —（effort=medium） |
| 16 | `kimi-k2.6` | Kimi-K2.6 | 256000 | 32000 | ✓ | —（effort=medium） |
| 17 | `deepseek-v4-pro` | Deepseek-V4-Pro | 300000 | 128000 | ✓ | high, xhigh |

- **与在册 `buddy` 兜底表（16 条）的关系**：CodeBuddy 的 16 条**全部**出现在这 55 条里；中国版白名单相对它**多 `auto`/`space-bunny`、少 `deepseek-v4-flash`**。⇒ **不能直接照抄 buddy 的表**（§4.5 给出本产品的表）。
- **`auto` 是服务端别名**：网关 `protocol.is_auto_select_alias("auto") == True`（`protocol.py:848-854`），远端解析会**主动跳过**它。兜底表是否收录 = **待裁决点 D2**（§9）。

### 3.3 签到与额度

```
POST www.workbuddy.cn/v2/billing/meter/checkin-activity-status
→ code=0；active=true / today_checked_in=true / streak_days=11 / daily_credit=100
  / total_credits=1100 / theme_name="Buddy加油站" / season=10
  / start_time=2026-09-30 00:00:00 / end_time=2026-10-15 23:59:59

POST www.workbuddy.cn/billing/meter/get-user-resource-summary     → code=0
→ {"Packages":[{"PackageCode":"TCACA_code_007_…","CycleTotalCapacity":"5900",
                "CycleRemainCapacity":"1284.46000047","CycleUsedCapacity":"4615.53999953",
                "CapacityUnit":"credits","TotalCount":30}, …],
   "SubscriptionPackageName":"体验版","IsPaidUser":false}

POST www.workbuddy.cn/v2/billing/meter/get-user-resource          → code=0
→ data.Response.Data.Accounts **31 条**（CapacityUnit=credits，含 CapacityType 1/4 两种）
```

**路径可用性矩阵**（决定共享实现能否原样复用）：

| 路径 | `www.workbuddy.cn` | 网关既有常量 |
|---|---|---|
| `/v2/billing/meter/get-user-resource` | ✅ code=0 | **就是这一条**（`protocol.py:51`） |
| `/billing/meter/get-user-resource-summary` | ✅ code=0 | 未使用（trae-helper 用的这条） |
| `/v2/billing/meter/get-user-resource-summary` | ❌（404/非 JSON） | — |
| `/billing/meter/get-user-resource` | ✅ code=0 | — |

→ **共享实现的三条计费路径在中国版域名上逐条可用**，零改动。

### 3.4 通道行为（**两处关键差异**）

**① `stream:false` 被拒**（与全族一致）：

```
POST /v2/chat/completions  {"model":"hy3","messages":[{"role":"user","content":"hi"}],
                            "max_tokens":16,"stream":false}
→ HTTP 400 {"code":11101,"msg":"Non-stream chat request is currently not supported", …}
```
⇒ 中国版 **也是 SSE-only**，`BuddyFamilyOut.stream_only = True` 对它是正确取值。

**② 首条**不**要求 `system`**（**与国际版相反**）：

```
变体 1（首条 user）：
  POST /v2/chat/completions {"model":"hy3","messages":[{"role":"user","content":"say hi"}],…,"stream":true}
  → 200 SSE：data: {…"delta":{"role":"assistant","content":"Hi","reasoning_content":""…}…}
变体 2（首条 system）：同样 200 SSE
```
⇒ 中国版**没有** `400 code 11128` 那条脾气 ⇒ **`system_first_text` 必须留空**。若照抄国际版档案把引导文案带过来，就是给不需要的通道凭空注入（正是 `out.py:19` 反对的形态）。

> 说明：变体 1/2 用的是 **免费模型 `hy3`（`credits=x0.00`）**，零成本；两轮各 16 token 上限、无会话持久化。

### 3.5 登录握手（免认证）

```
POST https://www.workbuddy.cn/v2/plugin/auth/state?platform=workbuddy
     (X-Domain: www.workbuddy.cn + 四个 X-No-* + UA_CN)
→ HTTP 200 {"code":0,"data":{"state":"36164f18-…",
             "authUrl":"https://www.workbuddy.cn/login?platform=workbuddy&state=36164f18-…"}}
```
⇒ 与全族同形（`hooks.start_login` 原样可用），`platform` 取 **`workbuddy`**。

### 3.6 复跑命令（脱敏模板）

```bash
TOK=$(python3 -c "import json;print(json.load(open('/Users/w/Desktop/trae-helper/accounts/workbuddy/db3c36d6-cd10-4eeb-ab12-12fdadaa639a.json',encoding='utf-8-sig'))['info']['auth']['accessToken'])")
UA='WorkBuddy/5.5.2 WorkBuddy/5.5.2 CLI/5.5.2'
curl -s https://www.workbuddy.cn/v3/config \
  -H "Authorization: Bearer $TOK" -H "X-Domain: www.workbuddy.cn" \
  -H "X-Product-Code: workbuddy" -H "User-Agent: $UA" | head -c 400
curl -s -X POST https://www.workbuddy.cn/v2/billing/meter/checkin-activity-status \
  -H "Authorization: Bearer $TOK" -H "X-User-Id: <uid>" -H "X-Domain: www.workbuddy.cn" \
  -H "X-Product: SaaS" -H "X-Product-Code: workbuddy" -H "User-Agent: $UA" -d '{}'
```

---

## 4. 接入方案（落地设计）

### 4.1 产品标识（id 命名）

**建议 id = `workbuddycn`**，理由三条：

1. **与既有命名法同构**：`qoder`（国际）/ `qodercn`（中国版）已是本仓先例（`registry.py:41-44`）。
2. **避免账号目录前缀冲突**：账号目录名 = `f"{product}-{secrets.token_hex(4)}"`（`accounts/login.py:440`），落在 `data/upstream/<product>/accounts/`。若取 `workbuddy-cn`，其目录名 `workbuddy-cn-xxxxxxxx` 会**前缀包含** `workbuddy-`；取 `workbuddycn` 则天然不冲突。
3. **`X-Product-Code` 与 id 解耦**：id 是本仓的键，`product_code` 是上游头取值 —— 两者本来就不必同名（在册 `workbuddy` 的 `product_code` 也是 `workbuddy`，与 id 巧合相同）。**id 叫 `workbuddycn`，`product_code` 仍取 `workbuddy`**（上游实测值，§2.2）。

**标题**：`WorkBuddy（中国版）`（与 `Qoder（中国版）` 同款括号风格；与在册 `WorkBuddy（国际版）` 对称）。

**排序**：`PRODUCT_IDS` 里紧跟 `workbuddy` 之后（= UI 左子侧栏顺序，把同族产品排在一起）。

### 4.2 注册表行（`accounts/registry.py`）

```python
# —— workbuddycn：WorkBuddy 中国版（workbuddy.cn；与 workbuddy 同族共用实现）——
# 登录 external_link 轮询（platform="workbuddy"）；额度 ✓；**签到 ✓**（与国际版相反）；
# 无设备标识；模型 remote `/v3/config` + 中国版兜底表。
"workbuddycn": ProductMeta(
    id="workbuddycn", title="WorkBuddy（中国版）",
    login="external_link",
    protocol="openai",
    # 基址 = 中国版 `cli/product.json` 的 `endpoint`（本机 WorkBuddy.app v5.6.2 实读）。
    base_url="https://www.workbuddy.cn",
    device=_NO_DEVICE,
    capabilities=Capabilities(balance=True, checkin=True,
                              onboarding=False, permanent_lock=True, refresh=True),
    models_source="remote",
),
```

**逐字段判据**：

| 字段 | 取值 | 判据 |
|---|---|---|
| `login` | `external_link` | `product.json.authentication.type = "cli-external-link"`；`auth/state` 实调 200（§3.5） |
| `protocol` | `openai` | 推理面标准 OpenAI SSE（含 `reasoning_content`，§3.4） |
| `base_url` | `https://www.workbuddy.cn` | 中国版 `endpoint`（一手）；不取 `copilot.tencent.com`（那是 CodeBuddy 的声明值） |
| `device` | `_NO_DEVICE` | `product.json` 无设备字段；签到实测不带设备头成功（§1.2/§3.3） |
| `balance` | `True` | `get-user-resource` / `-summary` 实调 code=0（§3.3） |
| `checkin` | `True` | `checkin-activity-status` 实调 active=true（§3.3）；桌面端 `productFeatures.DisableCheckin=false` |
| `onboarding` | `False` | 无一次性新手任务端点（`20 §3.1` 口径） |
| `permanent_lock` | `True` | 与同族 buddy/workbuddy 同判（`20 §3.3`）；⚠️ 见 §7-R3 |
| `refresh` | `True` | 同族共用 `auth/token/refresh`（`buddy-oauth.ts:289-329`） |
| `models_source` | `remote` | `/v3/config` 实调返回 55 条（§3.2） |
| `credentials_from` | `"store"`（缺省） | 与 buddy/workbuddy 同（网关自持凭据，非整根隔离） |
| `login_alt` | `()`（缺省） | 只有外链一种形态 |

`PRE_CHECK_PRODUCTS` **不加**本产品：同族 buddy 不预检（`registry.py:56` 只登记 trae），中国版 `daily-checkin` 幂等回 `10001`（§1.2），预检只是省一次请求、非正确性前提。

### 4.3 产品模块（新增 `upstream/workbuddycn/product.py`）

**结构完全照抄 `upstream/workbuddy/product.py`**（薄接线：只声明档案 + 抄兜底表 + 按冻结签名接线），差异只有 `_PROFILE` 的取值：

```python
PRODUCT = "workbuddycn"

_WORKBUDDYCN_FALLBACK_MODELS: tuple[ModelInfo, ...] = ( ... )   # §4.5

_PROFILE = ProductProfile(
    id=PRODUCT,
    platform="workbuddy",                                   # 中国版认证 platform（product.json 一手）
    product_code="workbuddy",                               # app.asar X-Product-Code 一手
    user_agent="WorkBuddy/5.5.2 WorkBuddy/5.5.2 CLI/5.5.2",  # = DSH WORKBUDDY_UA_CN（product.ts:71）
    fallback_models=_WORKBUDDYCN_FALLBACK_MODELS,
    append_session_params=True,                             # platform=="workbuddy" ⇒ 追加 version+loginSessionId
    plugin_version="5.5.2",
    system_first_text="",                                   # 🔴 留空：实测中国版无 11128 脾气（§3.4）
)
```

其余十个钩子（`meta` / `login_start` / `login_poll` / `login_callback` / `refresh` / `probe` / `quota` / `claim` / `list_models` / `build_out`）**逐字照抄 workbuddy 模块的薄接线**（都是 `return await hooks.xxx(_PROFILE, …)`），`_IMPLEMENTED` 与 `_HOOKS` 契约表同形（含 `build_out`，**不列 `login_callback`** —— 它按族契约显式拒绝，同 `workbuddy` 的登记口径）。

> 🔴 **零复制纪律**（本仓既有护栏）：本模块**不得**出现 `httpx`、`make_client`、或任何端点字面量（`/v2/plugin`、`/v2/billing`、`/v3/config`）—— 判据见 `tests/accounts/test_workbuddy.py:193-216` 的同型护栏，新模块照抄一份。

### 4.4 共享实现需要的**最小**改动（唯一一处）

`upstream/buddy/protocol.py` 的推理面归属头是**按 id 查表、缺项当场 `ValueError`**（`:248-260`，刻意不猜不降级）。**必须补一行**：

```python
_ATTRIBUTION_BY_PRODUCT: dict[str, tuple[str, str]] = {
    "buddy": ("CodeBuddy", "1.106.1"),
    "workbuddy": ("WorkBuddy", "5.5.2"),
    "workbuddycn": ("WorkBuddy", "5.5.2"),      # ← 新增；中国版 X-IDE-Name/Type/Product = "WorkBuddy"
}
```

**判据**：中国版 `app.asar` 逐字取证 `X-IDE-Type = X-IDE-Name = "WorkBuddy"`、`X-Product = "WorkBuddy"`（§2.2）；`X-IDE-Version = appVersion`，取 `5.5.2`（与 DSH `WORKBUDDY.clientVersion` 及 `WORKBUDDY_UA_CN` 同源；⚠️ 见 §7-R4）。

**除此之外 `buddy/hooks.py` / `buddy/protocol.py` / `buddy/out.py` 零改动** —— 这正是「参数化新增」的证明。

### 4.5 兜底模型表（`_WORKBUDDYCN_FALLBACK_MODELS`）

**来源**：§3.2 实测的 `cli` agent 白名单（17 条）+ 同次 `/v3/config` 的逐条元数据。**顺序即 IDE 展示顺序**，不得重排。

**建议收录 16 条（剔除 `auto`）**，理由：`protocol.is_auto_select_alias` 已把 `auto`/`default` 明确定为「服务端自行挑后端的内部别名，**不是真实模型**」（`protocol.py:848-854`）；兜底表是网关的**可用模型目录**，收进别名会让它可被映射/转发。**这是本方案唯一一处「不照抄上游清单」的地方，故单列待裁决点 D2（§9）**。

```
hy4-preview        Hy4 preview        300000  64000  img  [high]
hy3                Hy3                192000  64000  img  [low, high]
hy3-x              Hy3                192000  64000  img  [low, high]
space-bunny        Space-Bunny       1000000 128000  img  [low, medium, high, xhigh, max]
deepseek-v4.1-flash Deepseek-V4.1-Flash 300000 128000 img  [low, high, max]
glm-5.3            GLM-5.3            300000  64000  img  [low, high, max]
glm-5.3-flash      GLM-5.3-Flash      300000 131072  img  [low, high, max]
glm-5.2            GLM-5.2            300000  64000  img  [high, xhigh]
glm-5.1            GLM-5.1            200000  48000  img  —
glm-5v-turbo       GLM-5v-Turbo       200000  64000  img  —
minimax-m3         MiniMax-M3         300000  64000  img  —
kimi-k3-1          Kimi-K3            300000  32000  img  [low, high, xhigh]
kimi-k2.8-preview  Kimi-K2.8-Preview  300000  64000  img  [low, high, max]
kimi-k2.7          Kimi-K2.7-Code     256000  32000  img  —
kimi-k2.6          Kimi-K2.6          256000  32000  img  —
deepseek-v4-pro    Deepseek-V4-Pro    300000 128000  img  [high, xhigh]
```

- `rate` / `free` **不填**（兜底表不含计费字段 —— 与 `merge_models` 的既有口径一致，`:1026-1029`；计费由远端 `/v3/config` 逐条覆盖）。
- `tool_call` 恒 `None`（两个端点都不声明工具能力，取不到不编造）。
- 元数据是**某个「体验版」账号**看到的池；**付费账号可能看到更多** ⇒ 兜底表按「保守可用集」定位，远端可达时以远端为准（`merge_models` 的白名单式重建，`:999-1040`）。

### 4.6 出站适配（零新增）

`build_out` → `BuddyFamilyOut(account, _PROFILE)`（`buddy/out.py`），**不写第二份**。继承的行为逐条对本产品成立：

| 行为 | 取值 | 对中国版的判据 |
|---|---|---|
| `chat_path` | `/v2/chat/completions` | §3.4 实调命中 |
| `stream_only` | `True` | §3.4 变体 A 回 400 code 11101 |
| 首条 system 补齐 | **不触发**（`system_first_text=""`） | §3.4 变体 B：首条 user 直接 200 |
| `_is_resource_scoped_rejection` | 认 `400 + "Illegal API invocation from an unapproved channel"` | 全族共用；中国版未见反例，**保持不动**（多认一条无害） |
| 身份头 | `inference_headers`（`X-Product`=归属名 `WorkBuddy`） | §2.2 逐字取证 |

### 4.7 逐钩子落点（全表）

| 钩子 | 落点 | 中国版实测/判据 |
|---|---|---|
| `meta` | `registry.get("workbuddycn")` | §4.2 |
| `login_start` | `hooks.start_login` → `POST {base}/v2/plugin/auth/state?platform=workbuddy` | §3.5 实调 200 |
| `login_poll` | `hooks.poll_login` → `GET /v2/plugin/auth/token` + `/v2/plugin/login/account` | 全族共用，未逐端点实测（**未验证**，见 §7-R5） |
| `login_callback` | 显式拒绝（非 local_callback 型） | 全族同形 |
| `refresh` | `hooks.refresh_credential` → `POST /v2/plugin/auth/token/refresh` | 全族共用（**未验证**） |
| `probe` | `hooks.probe` → `POST /v2/billing/meter/get-user-resource` | §3.3 实调 code=0 |
| `quota` | `hooks.quota` → 同上 | §3.3 实调 code=0（31 包） |
| `claim` | `hooks.claim`（能力位 True）→ `checkin-activity-status` + `daily-checkin` | §3.3 status 实调；**`daily-checkin` 未实调**（只读纪律），幂等码 10001 同族同判 |
| `list_models` | `hooks.list_models` → `GET /v3/config` + 兜底表 | §3.2 实调 55 条 |
| `build_out` | `BuddyFamilyOut` | §4.6 |

### 4.8 前端与图标

- **产品清单/能力位/登录向导全部数据驱动**：`api/admin_accounts.py:632-656` 遍历 `registry.PRODUCT_IDS`；前端按 `p.id` 渲染（`accounts.js:284-287`）⇒ **注册表加一行即全站生效，前端零硬编码改动**。
- **图标**：需新增 `web/static/img/products/workbuddycn.png`（≥64px 边长，PNG 魔数校验；`tests/unit/test_v2_product_icons.py` 会钉「代码要的扩展名 ↔ 磁盘文件」一一对应）。
  - **来源建议**：`/Applications/WorkBuddy.app/Contents/Resources/` 内的官方图标资产（与既有 10 枚「官方 icon」的口径一致：`accounts.js:277-283` 注明全部换成了官方资产）。
  - `ICON_SVG` 分派表**两处**（`accounts.js` / `dashboard.js`）**都要**保持 `workbuddycn` 不在集合内（= 用 png）；两处漂移会被 `test_two_dispatch_tables_are_identical` 判红。
- **登录页 iframe 注意事项**：中国版登录页 `https://www.workbuddy.cn/login` 实测未发框禁头（`login.js:272-273` 已记录该域名），与 `qodercn` 的 `SAMEORIGIN` 情形不同 ⇒ 可 iframe。

### 4.9 `mgw setup` 的命名重叠（**必须知道，不是冲突**）

`setup_tools.py:39` 的 **tool** 键 `workbuddy` → `dataFolderName=".workbuddy"` —— **那正是中国版桌面端的数据目录**（中国版无 `customUserDataDir`，默认 `.workbuddy`）。

⇒ 两个「workbuddy」是**两个轴**：
- `mgw setup workbuddy`（**tool**）= 往**中国版桌面端**目录写 `models.json`（已有功能，不动）；
- 本方案新增 `workbuddycn`（**网关产品**）= 把**中国版账号**接成上游资源（本方案）。

**本方案不改 `setup_tools.py`**；但在文档/UI 上要避免让用户以为「接了中国版产品 = 中国版 App 已接网关」。**建议登记为命名澄清项**（§9-D4）。

### 4.10 明确**不需要**改的面（防止误改）

| 面 | 为什么不用改 |
|---|---|
| `buddy/hooks.py` / `buddy/protocol.py` / `buddy/out.py` | 全族共用实现，本产品纯参数化（唯一例外 = §4.4 的归属表补一行） |
| `upstream/workbuddy/*`（国际版） | 另一产品，不动 |
| `accounts/login.py` / `store.py` / `materialize.py` / `device.py` | 全部按 `product` 字符串动态寻址 |
| `ops/builtin/*`（claim/query_balance/auto_renew） | 全部从 `registry.PRODUCT_IDS` 推导（`product_claim.py:50`、`query_balance.py:51`、`auto_renew.py:98`） |
| `main.py` 的 `prod in ("qoder","qodercn")` 前提判据 | 那是 qoder 族签名腿专用（`main.py:271`）；本产品无签名前提 |
| 前端产品清单 | 数据驱动（§4.8） |

---

## 5. 改动清单（逐文件）

**新增（5）**

| # | 路径 | 内容 |
|---|---|---|
| 1 | `coding/model_gateway/upstream/workbuddycn/__init__.py` | 与 `workbuddy/__init__.py` 同形 |
| 2 | `coding/model_gateway/upstream/workbuddycn/product.py` | §4.3（档案 + 兜底表 + 薄接线） |
| 3 | `coding/tests/accounts/test_workbuddycn.py` | 照抄 `test_workbuddy.py` 的判据骨架，断言中国版参数（domain=workbuddy.cn / platform=workbuddy / product_code=workbuddy / UA_CN / checkin=True / system_first="" / 兜底表 16 条 / 零复制护栏） |
| 4 | `coding/tests/integration/test_workbuddycn_out.py` | 出站：SSE-only、身份头归属名 `WorkBuddy`、**不注入 system**、unapproved-channel 400 → 资源级不可承接（照抄 `test_buddy_out.py` 同型） |
| 5 | `coding/model_gateway/web/static/img/products/workbuddycn.png` | 官方图标（§4.8） |

**修改（6）**

| # | 路径 | 改动 |
|---|---|---|
| 6 | `coding/model_gateway/accounts/registry.py` | `PRODUCT_IDS` 加 `"workbuddycn"`（紧跟 `workbuddy`）+ §4.2 的 `ProductMeta` 行 |
| 7 | `coding/model_gateway/upstream/buddy/protocol.py` | `_ATTRIBUTION_BY_PRODUCT` 加 `"workbuddycn": ("WorkBuddy", "5.5.2")`（§4.4） |
| 8 | `coding/tests/accounts/test_registry.py` | `test_registry_has_the_ten_products_and_no_codearts`（改 11 项元组 + 改名）、`test_matrix_login_and_models_source` / `test_matrix_protocol` / `test_matrix_device_fields` / `test_matrix_capabilities_from_research_3_1` 各加一行；`test_no_checkin_products_are_marked_unavailable` 的集合**不变**（本产品 checkin=True） |
| 9 | `coding/tests/unit/test_v2_product_icons.py` | 无代码改动（自动纳入新产品），但**必须**有第 5 项图标文件在位，否则该门判红 |
| 10 | `docs/specs/tech-design.md` | §22.0 产品数 10→11；§22.4 矩阵加 `workbuddycn` 行；版本史加一行 |
| 11 | `docs/specs/prd.md` + `docs/specs/frontend-spec.md` | PRD 补一条 Q 条目（Q29 增补或新 Q##，**待用户裁定编号**）；frontend-spec 产品清单加一行 |

> **存证不改写**（铁律 6 的旧文处置）：`docs/changes/**` 台账、各 spec 的版本史行、既有 Q 条目原文**一律不动**，只追加。

---

## 6. 测试与验收门

| 门 | 判据 | 备注 |
|---|---|---|
| 产品契约 | `tests/accounts/test_registry.py` 全绿（11 产品、10 钩子签名、能力位/设备/协议/登录/目录逐条） | 需同步改 4 个硬编码矩阵 |
| 产品单测 | `tests/accounts/test_workbuddycn.py` 全绿 | 全 MockTransport，无网络、无真实凭据 |
| 出站集成 | `tests/integration/test_workbuddycn_out.py` 全绿 | 重点：**不注入 system**（反向撤证 = 给 `_PROFILE.system_first_text` 填值必红） |
| 图标门 | `tests/unit/test_v2_product_icons.py` 全绿 | 两处分派表一致 + 文件在位 |
| 全量 | `pytest -q`（当前基线 2349 passed / 3 skipped，`AGENTS.md`） | 新增用例后数字会变，README 双语同步（既有 `test_readme_test_counts_are_not_stale` 钉住） |
| 真机（用户驱动） | `:8300` 重启后：登录向导走通中国版 → 账号出现在「账号接入」→ 额度/签到按钮可见且可点 → `/v1/models` 出现中国版模型 → 一次真实推理 200 | **未实测，不得写成已完成**（Q29-⑤ 纪律） |

---

## 7. 风险与未验证项（诚实清单）

| # | 项 | 性质 | 处置建议 |
|---|---|---|---|
| **R1** | **登录页深链会唤起本机 App** | 中国版 `platform=workbuddy` ⇒ 登录页按 platform 深链 `workbuddy://` ⇒ 浏览器把控制权交给 `/Applications/WorkBuddy.app`（**本机已注册该协议**）。与并行会话 2026-10-10 定位的国际版 `workbuddy-ai://` 问题**同源同形** | 两条路（与那轮同款）：**A** 档案 `platform` 改 `cli`（登录页对 cli 不深链）；**B** 前端改 iframe 嵌入式登录（`embed=iframe&parent_origin=…`）。**必须与那轮统一口径**，不要两个产品两种做法 |
| **R2** | `daily-checkin` 未实调 | 只读纪律下未做领取动作；端点存在性由 app.asar 字面量 + trae-helper 实测 + 同族 buddy 同端点共同支撑 | 实施后由用户驱动真机点一次（幂等，重复点回 10001） |
| **R3** | `permanent_lock=True` 未逐证据 | 按同族 buddy/workbuddy 同判（`20 §3.3`）；中国版 `get-user-resource` 里可见 `CapacityType` 1/4 两类包，但**未确认哪类是「永久包」** | 若用户在意，实施时用 `credits.ts:437-443` 的 `DeductionEndTime` 口径核一次；不确认就把该位标 False（**宁少一个按钮，不给点了必然失败的按钮**，§22.6） |
| **R4** | `clientVersion` 取 5.5.2 而非本机 5.6.2 | 本机中国版 App 是 v5.6.2，DSH `WORKBUDDY_UA_CN`/`clientVersion` 是 5.5.2 | 取 5.5.2（与 DSH 一手常量同源、与在册国际版同族）；**登记为「随版本同步」维护项**。`X-IDE-Version` 只影响上游后台归因展示，不影响可用性 |
| **R5** | `login_poll` / `refresh` 两腿未对中国版逐端点实测 | 全族共用实现，中国版 `product.json` 同 `cli-external-link` 协议 | 实施后真机走一次登录 + 等一次续期；未实测前**不得写成已完成** |
| **R6** | 兜底表基于**体验版**账号所见池 | 付费账号可能看到更多模型 | 兜底表按保守集定位；远端可达时以远端为准（既有 `merge_models` 语义天然覆盖） |
| **R7** | 中国版 `v3/config` 与 `copilot.tencent.com` 返回**逐条相同**的 55 条 | 说明两域名同一后端 | 基址仍取产品声明值 `www.workbuddy.cn`（`protocol.py:118-120`：`X-Domain` 必须与请求 baseURL 一致） |

---

## 8. 实施步骤（可执行任务分解）

> 每步一提交、每步可回滚；**R4 锚耦合**：`registry` 行 + `protocol` 归属表 + 产品模块 + 单测是**一个原子单元**（缺任一，`build_out` 或注册表门必红）。

| 步 | 动作 | 完成判据 |
|---|---|---|
| S1 | 新增 `upstream/workbuddycn/`（`__init__.py` + `product.py`） | `python -c "from model_gateway.upstream.workbuddycn import product; print(product._PROFILE)"` 可跑 |
| S2 | `registry.py` 加 `PRODUCT_IDS` + `ProductMeta` 行 | `registry.get("workbuddycn")` 返回正确 meta |
| S3 | `protocol.py::_ATTRIBUTION_BY_PRODUCT` 补一行 | `product.build_out(...).auth_headers(...)` 不再 `ValueError` |
| S4 | 新增 `tests/accounts/test_workbuddycn.py` + 更新 `test_registry.py` | `pytest tests/accounts/test_workbuddycn.py tests/accounts/test_registry.py -q` 全绿 |
| S5 | 新增 `tests/integration/test_workbuddycn_out.py` | 全绿；**撤证**：给 `system_first_text` 填值 → 必红 |
| S6 | 新增图标 `workbuddycn.png` | `pytest tests/unit/test_v2_product_icons.py -q` 全绿 |
| S7 | 全量 `pytest -q` + README 双语计数同步 | 全绿、计数一致 |
| S8 | 文档：tech-design §22.0/§22.4、PRD Q 条目、frontend-spec 清单 | 版本史追加（不改旧文） |
| S9 | **用户驱动真机**：登录 → 额度 → 签到 → 映射 → `/v1/models` → 推理 | 逐条留证（台账 `docs/changes/e2e-records/`） |

---

## 9. 待用户裁决点

| # | 事项 | 建议 | 备选 |
|---|---|---|---|
| **D1** | 交付范围 | 本文件 = 方案（当前）；确认后进实施波次 | 若要求「方案 + 直接实施」，请明示，我按 §8 逐步落地 |
| **D2** | 兜底表是否收录 `auto` | **不收录**（16 条）—— 尊重 `is_auto_select_alias` 的既有判断 | 收录（17 条，与 CN App 选择器一致，但会把服务端别名暴露成可映射模型） |
| **D3** | 登录深链（R1）走 A 还是 B | **与并行会话的国际版处置统一**（同源问题不该两个答案） | A=档案 platform 改 `cli`（1 行）；B=前端 iframe 嵌入式登录 |
| **D4** | `mgw setup` 的 tool 键 `workbuddy`（=中国版 App）与新产品 `workbuddycn` 命名澄清 | 在 UI/文档加一句澄清 | 或把 tool 键改名为 `workbuddy-cn`（**会动既有配置**，不建议） |
| **D5** | PRD 条目编号（Q29 增补 or 新 Q##） | 由你定 | — |

---

## 10. 一句话回答

> **WorkBuddy 中国版 = 腾讯 WorkBuddy 桌面端（`workbuddy.cn` / platform `workbuddy`），与在册的 CodeBuddy（buddy）和 WorkBuddy 国际版（workbuddy）同族同实现，差异全在参数：基址、platform、UA、兜底表、`checkin=True`、`system_first` 留空。**
> **接入 = 新增 1 个产品模块 + 注册表 1 行 + 共享实现 1 行归属表 + 1 张图标 + 单测/集成/文档；`hooks.py`/`protocol.py`/`out.py` 主体零改动。**
> **本机实测已把三件事钉死**：额度/签到端点在中国版域名上真实可用（§3.3）、通道 SSE-only 但**不要求首条 system**（§3.4）、登录握手 platform=`workbuddy` 可用（§3.5）。
> **唯一外部变数**是登录页深链唤起本机 App（R1）—— 与并行会话已定位的国际版问题同源，需与那一轮统一口径后再实施。
