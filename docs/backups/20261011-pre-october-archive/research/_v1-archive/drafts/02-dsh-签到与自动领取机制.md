# DSH 插件「签到 / 自动领取额度 / 账号探活轮换」机制考古报告

> 目标项目（只读）：`/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts/`
> 考古时间：2026-09-22　方法：真实读源码 + 读测试 + 读项目内文档，全部结论附 `file:line`
> 凡未能在代码中找到确证的，一律在 §5「未验证 / 存疑」里明说，不做推断。

---

## 0. 结论先行

1. **不存在统一的 `CreditsProvider` 接口。** 只有三个**共享的数据类型**（`ClaimOutcome` / `CheckinStatus` / `CreditBalance`）和一层**共享的编排函数**（`collectClaimResults` / `collectCreditsStatus` / `collectCreditBalances`），协议实现是四个完全独立的文件，靠 `if (provider === ...)` 在 RPC 层分派（`src/jet-hub-rpc.ts:1007-1071`）。
2. **签到没有任何自动调度。** 全仓库唯一的签到入口是 Jet Hub 面板上用户手点的「一键领取积分」按钮 → `credits.claimAll` RPC（`plugin-src/client/jet-hub.js:646-651`）。项目自己的文档明确写着「签到没有定时任务」（`docs/lobsterai-integration-plan.md:1301`）。存在的定时器只有**凭据续期**（30 分钟）与**模型列表刷新**（2 小时）。
3. **幂等保护分四种完全不同的机制**：服务端业务码（buddy `10001`）、客户端幂等键 + 两步预检（lobsterai）、纯预检无幂等键（codearts）、**必须靠状态端点预检否则无法区分成功**（trae，claim 对已签到返回 `{code:0,"success"}`）。
4. **本地不持久化「今天领没领」**。全仓库 grep 无 `lastCheckin*` / `claimedDate` 之类字段；是否已领每次都是**问服务端**。持久化的只有账号条目本身与限流标记（`modelRateLimits`）。
5. **账号池只有两个状态维度**：用户手动的 `enabled` 开关 + 每模型的 `modelRateLimits[modelId] = resetAtMs` 时间戳。没有「账号级冷却」「账号级禁用」这套状态机 —— 这是相对参考实现（Go）的**有意取舍**（`src/lobsterai-errors.ts:9-19`）。
6. **限流判定语言无关优先**：先认结构化业务码 `6004`，再退回中英双语正则；重置时间从错误文案里**正则捕获真实时区**（不硬编码 UTC+8），抓不到才兜底「1 小时后」（`src/llm-adapter.ts:1457,1475-1476,1510,1513-1537`）。
7. **探活（retest）是手动 + 无副作用的**：真实发一次最小对话请求，只有实测通过的模型才清除限流标记；探测时**刻意不把 accountPool 传给适配器**，避免探测污染其他账号的标记（`src/account-probe.ts:24-29,115-120,221-224`）。
8. **轮换上限 3 个账号**（含首个），对齐 Go 的 `MaxRotate`；任何非 2xx 都轮换，但只有特定错误类别才写限流徽章（`src/lobsterai-adapter.ts:90,938-1003`；`src/trae-adapter.ts:133,917-947`）。
9. **能力矩阵是硬编码在前端的一张表**，默认关闭；未登记的 provider 视为两项能力全无（`plugin-src/client/credits-capabilities.js:48-65`）。
10. **对网关最有价值的三条**：①「查不到 ≠ 为 0」的语义纪律；②预检前置 + 单账号异常隔离的批处理编排；③把限流标记做成**每账号×每模型的时间戳**而不是账号级开关。

---

## 1. 各平台签到 / 领取协议对照表

### 1.1 总表

| 维度 | **buddy**（CodeBuddy 中国版） | **workbuddy**（WorkBuddy 国际版） | **codearts**（华为云 CodeArts） | **lobsterai**（有道龙虾） | **trae**（字节 TRAE） | **qoder** |
|---|---|---|---|---|---|---|
| 能力定性 | **签到**（两步） | **无签到** | **领取活动/任务奖励**（四步） | **签到**（三步） | **签到**（两步） | **仅查额度** |
| `balance` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `dailyCheckin` | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ |
| 状态/预检端点 | `POST /v2/billing/meter/checkin-activity-status` | — | `GET /snap-manager/v1/statistics/plugin`（账户类型）<br>`GET /v1/ops/delivery?channel=IDE`（活动列表） | `GET /api/client-activities/slot`<br>`GET /api/client-activities/{code}/context` | `POST /trae/api/v2/ug/checkin_credits/status` | — |
| 领取端点 | `POST /v2/billing/meter/daily-checkin` | — | `POST /v1/ops/claim` →（需确认时）`POST /v1/ops/confirm` | `POST /api/client-activities/{code}/actions/check_in` | `POST /trae/api/v2/ug/checkin_credits/claim` | — |
| 余额端点 | `POST /v2/billing/meter/get-user-resource` | 同左（仅 baseURL 不同） | `GET /snap-manager/v1/statistics/plugin`（与账户类型同一响应） | `GET /api/user/profile-summary` | `POST /trae/api/v2/pay/ide_user_ent_usage` | `GET /sash/api/v2/me/usage` |
| 认证方式 | `Bearer` + 腾讯系归属头族（`X-Domain`/`X-Product`/`X-Product-Code`/`X-User-Id`/`X-Enterprise-Id`） | 同左 | **`SDK-HMAC-SHA256` 签名**（AK/SK/security_token） | **纯 `Bearer`，无签名**（仅 4 个头） | `Cloud-IDE-JWT` + **约 20 个客户端头** | `Bearer` + `Cosy-ClientType` |
| 请求体 | 状态 `{}` / 领取 `{}` / 余额 `{}` | 同左 | 领取 `{campaignId, channel:'IDE'}`<br>确认 `{campaignId}` | 领取 `{configRevision, idempotencyKey, payload:{}}` | 状态 `{}` / 领取 `{}` / 余额 `{require_usage:true, req_source:2}` | GET 无体 |
| 成功判定 | `code === 0` | — | HTTP 2xx + 信封解包成功 | `code === 0` 信封 + `data` 为对象 | `code === 0`（兼容字符串 `"0"`） | HTTP 2xx + JSON 形状合法 |
| 已领取判定 | `code === 10001`（兼容 `1001`） | — | 活动 `claimable === false` 且 `status ∈ {CLAIMED,CONFIRMED,CONSUMED}` | `context.state.claimedToday === true` | **claim 无法区分** → 必须用 status 的 `checked_in` | — |
| 无资格/未开启判定 | `code === 1002`（无资格）/ `1003`（活动结束）→ `inactive` | — | 非积分账户 / 无 `USER_LOGIN` 活动 / `claimable=false` 且 status 非已领态 → `inactive` | `slotState !== 'available'` 或 `actions` 不含 `check_in` → `inactive` | 由 `enable` 字段体现（`active: body.enable === true`） | — |
| 幂等机制 | **服务端**业务码（重复领 = HTTP 400 + `code:10001`） | — | **仅客户端预检**（无幂等键、无「今日已领」业务码） | **客户端幂等键 `idempotencyKey`(UUID4) + 两步预检** | **服务端幂等但与成功不可区分** → 靠 status 预检 | — |
| 额度单位/口径 | `CycleCapacityRemainPrecise`（本周期，字符串精确值） | 同左 | `metrics[].package_credit_remain`（`usageTotalPackageCredit` 为总额） | `totalCreditsRemaining` + `creditItems[]` | `∑(credits_limit - credits_amount)` | `userQuota` + `addOnQuota` + `dedicatedResourcePackages` |
| 超时 | 30s | 30s | 30s | 30s | 30s | 15s |
| 实现文件 | `src/credits.ts` | 同左 | `src/codearts-credits.ts` | `src/lobsterai-credits.ts` | `src/trae-credits.ts` | `src/qoder-credits.ts` |

### 1.2 逐平台细节

#### A. buddy / workbuddy —— `src/credits.ts`

**端点常量**（`src/credits.ts:33,35,51`）：

```
状态查询  POST {product.endpoint}/v2/billing/meter/checkin-activity-status   body {}
领取      POST {product.endpoint}/v2/billing/meter/daily-checkin             body {}
余额      POST {product.endpoint}/v2/billing/meter/get-user-resource         body {}
```

**请求头**（`src/credits.ts:180-197`）：`Authorization: Bearer`、`Accept`、`Content-Type`、`X-Domain = product.apiDomain || credential.domain`、`X-Product = BUDDY_DEPLOYMENT_TYPE`、`X-Product-Code = product.productCode`、可选 `X-User-Id`、可选 `X-Enterprise-Id` + `X-Tenant-Id`、`User-Agent = product.userAgent`。

两个反直觉的实测结论（文件头注释 `src/credits.ts:9-20`）：
- **必须用 `checkin-activity-status`，不能用 `checkin-status`** —— 后者返回占位数据（`active:false`、`checkin_dates:null`），会误判为「活动未开启」。
- **不需要 `X-Device-Token`（图灵盾）** —— 实测不带该头真实领取成功，故不引入 native SDK。

**状态响应结构**（解析见 `src/credits.ts:310-322`，字段名转为 camelCase）：`data.{active, today_checked_in, streak_days, daily_credit, today_credit, is_streak_day, total_credits, checkin_dates[], activity_name, theme_name, end_time}`。

**领取响应结构**（`src/credits.ts:358-366`）：`data.{credit, streak_days, is_streak_day, message}`。

**判定逻辑**（`src/credits.ts:341-366`）：

```
code ∈ {10001, 1001} → already-claimed   // 常量定义见 :57-59
code ∈ {1002, 1003}  → inactive
code !== 0           → failed
code === 0 且 data 为对象 → claimed
code === 0 但 data 非对象 → failed('领取响应缺少 data 字段')
```

⚠️ **判定以响应体 `code` 为准，不能只看 HTTP 状态** —— 重复领取是 HTTP 400，只看状态码会把幂等情况误报为失败（`src/credits.ts:19-20,326-330`）。

**余额解析**（`src/credits.ts:439-476`）：`data.Response.Data.Accounts[]` —— **双层嵌套**，是「最容易解析错的地方」（`src/credits.ts:436-437`）。每个包的字段：

| 字段 | 口径 | 用途 |
|---|---|---|
| `CapacityRemainPrecise` | **终身**剩余（字符串精确值） | 不用 |
| `CycleCapacityRemainPrecise` | **本周期**剩余 | **用于总额**（`src/credits.ts:419`） |
| `CycleCapacitySize` / `CycleCapacityUsed` | 本周期总额/已用 | 展示 |
| `Status === 3` | 已过期 | 失效判定（`src/credits.ts:393,414`） |
| `ExpiredTime` | 包自身失效时间 | 与 Status 共同判定 |

总额 = **各有效包**的 `CycleCapacityRemain` 之和，`expiredTotal` 单独汇总（`src/credits.ts:468-475`）。**刻意不用 `TotalDosage`**：它是终身口径且取整（实测 `TotalDosage=655` 而 IDE 显示 `155.67`）（`src/credits.ts:154-156`）。

**非 JSON 响应的处理**（`src/credits.ts:239-243,284-291`）：凭据失效时腾讯网关返回 **HTML 错误页**，`response.json()` 会抛 `Unexpected token '<' ...`。因此统一「先取文本再解析」，非 JSON 时 401/403 直接给「凭据已失效，请重新登录该账号」，其余带状态码 + 80 字符片段。

**workbuddy 差异**：只有 baseURL（`product.endpoint`）不同；签到能力为 false，因为国际版内核里连 `checkin-status` / `daily-checkin` 字面量都不存在（`src/credits.ts:43-46`）。**但余额查询两边都有**（`src/credits.ts:36-50`）。

---

#### B. codearts —— `src/codearts-credits.ts`

**四步流程**（`src/codearts-credits.ts:568-645`）：

```
1) GET  {snapEngine}/snap-manager/v1/statistics/plugin      → 账户类型（是否积分账户）
2) GET  {snapEngine}/v1/ops/delivery?channel=IDE            → 活动列表
3) POST {snapEngine}/v1/ops/claim   {campaignId, channel:'IDE'}
4) POST {snapEngine}/v1/ops/confirm {campaignId}            ← 仅当 3) 响应 id !== null
```

`snapEngine = https://snap-access.cn-north-4.myhuaweicloud.com`（`src/codearts-credits.ts:79`），与 `src/models.ts` 的 `SNAP_MODEL_BUILTIN_URL` **同域**。

**认证是签名，不是 Cookie**（关键结论，`src/codearts-credits.ts:33-43`）：官方文档给的 `codearts.huaweicloud.com/portal/...` 是 BFF 接口，依赖浏览器会话 Cookie，实测带 AK/SK 签名也只返回 IAM 登录跳转 HTML。**IDE 直连的 snap-access 端点接受 `SDK-HMAC-SHA256` 签名**，与 `src/sign.ts` 逐字一致。

⚠️ **`Agent-Type` / `X-Language` 必须在签名之后追加，绝不能参与签名计算**（`src/codearts-credits.ts:113-133,340-348`）。实测若作为 `signRequestHuawei` 的 `extraHeaders` 传入，服务端回 `401 APIG.0301 verify ak sk signature fail`；签名后追加则 200 并返回真实数据。

**判定顺序**（每一步对应一个对用户含义不同的结果，`src/codearts-credits.ts:554-567`）：

| 步 | 条件 | 结果 |
|---|---|---|
| 1 | 账户信息查询失败 | `failed`（带原因） |
| 1 | `package.is_credit_package !== true` | `inactive`（区分 Token 计费账户 / 非积分账户两种文案） |
| 2 | 活动列表查询失败 | `failed` |
| 2 | 无 `type === 'USER_LOGIN'` 的活动 | `inactive`（`CODEARTS_DAILY_LOGIN_TYPE`，`:100`） |
| 3 | `claimable === false` 且 `status ∈ {CLAIMED,CONFIRMED,CONSUMED}` | `already-claimed`（`CLAIMED_STATUSES`，`:108`） |
| 3 | `claimable === false` 且 status 非已领态 | `inactive` |
| 3 | `campaignId` 为空 | `failed` |
| 4 | claim 失败 | `failed` |
| 5 | 响应 `id !== null/undefined` | 补发 confirm（**confirm 失败不把整体判 failed**，因为积分已进待确认态，报 failed 会让用户重复点击，`:614-616`） |
| 6 | — | `claimed`（积分三级回退：claim 响应 `benefitAmount`→`credit`→`credits`→`creditAmount`→`amount`，再退回活动条目的 `amount`） |

**三个实测字段坑**（`src/codearts-credits.ts:180-204,262-279,1172-1177` of AGENTS.md）：
- `campaignId` 服务端下发的是**数字** `1` 而不是字符串 → 必须用 `readIdentifier`（兼容数字/字符串，`:274-279`）。用只收字符串的 `readString` 会得到空串并判 `failed`「活动缺少 campaignId」。
- 可领积分字段是 **`benefitAmount`**（`1000`），不是 `amount`（`:497`）。
- 不可领取的活动 `status` 是 **`null`**（不是字符串），`readString` 要能容忍。

**信封兼容**（`src/codearts-credits.ts:289-319`）：`ops/*` 返回 `{code, message, data}` 且 `code !== 0` 即失败；`statistics/plugin` **直接返回裸对象**（无 `data` 解包）。判定顺序：先看 `code`（存在且非 0 即失败），再取 `data`，没有 `data` 就认为 body 本身即数据。

**余额解析**（`src/codearts-credits.ts:390-430`）：总额取 `metrics[]` 中 `usageTotalPackageCredit` 的 `package_credit_remain`，**不累加**基础/按需/赠送分类明细（它们是总额构成项，相加会重复计算）。没有任何 credit metric 时返回 `undefined`（= 该账户没有积分口径），与 `total: 0`（有口径但为 0）**严格区分**（`:169-175`）。

---

#### C. lobsterai —— `src/lobsterai-credits.ts`

**三步流程**（来源 `lobsterai2api/sigin.py:51-67`）：

```
0) GET  {clientVersionApi} → data.value.version            ← 必填参数
1) GET  {apiBase}/api/client-activities/slot
        ?placement=desktop_sidebar&clientVersion={v}
        &containerApiVersion=2&platform=win32
2) GET  {apiBase}/api/client-activities/{activityCode}/context?configRevision={rev}
3) POST {apiBase}/api/client-activities/{activityCode}/actions/check_in
        body {configRevision, idempotencyKey: <UUID4>, payload: {}}
```

`apiBase = https://lobsterai-server.youdao.com`（`src/lobsterai-product.ts:63,203`）。

**请求头**：`Authorization: Bearer` + 3 个（`Accept` / `User-Agent` / 一个），共 4 个头。LobsterAI **不认** CodeBuddy 那套 `X-Domain` / `X-Product` / `X-IDE-*` 归属头（`src/lobsterai.ts:415-432`）。

**槽位查询的三个固定 query 参数照抄参考实现**（`src/lobsterai-credits.ts:42-52`）：`platform=win32` 是**伪装客户端形态**，即使跑在 macOS/Linux 上也照发，改了可能拿不到活动。

**判定顺序**（`src/lobsterai-credits.ts:225-233`）：

```
1. slot 查询失败                          → failed
2. slotState !== 'available' 或 code 空   → inactive
3. context 查询失败                       → failed
4. state.claimedToday === true            → already-claimed
5. actions 不含 'check_in'                → inactive
6. check_in 请求失败 / 信封异常            → failed
7. 成功                                   → claimed
```

**幂等是客户端保证的**（`src/lobsterai-credits.ts:21-27`）：请求带 `idempotencyKey`（`randomUUID()`，`:267`）+ 签到前先查 `claimedToday` 与 `actions`。**两步预检都要做** —— 只看 `claimedToday` 会漏掉「活动存在但今天不该领」的情形。

**积分字段三级回退**（`src/lobsterai-credits.ts:278-285`）：`creditsGranted` → `rewardCredits` → `credits`，不同活动/版本用不同字段名。

**余额端点用 `profile-summary` 而非 `quota`**（`src/lobsterai-credits.ts:297-305`）：`/api/user/quota` 只显示 `freeCreditsTotal=300`，**不含活动积分**（实测某账号 profile-summary 有 `5297.72`，quota 只有 `300`）。

**两个额外纪律**：
- `totalCreditsRemaining` 为 0 且 `creditItems` 为空 → 视为**查不到**而非「余额为 0」（`src/lobsterai-credits.ts:354-356`）—— 字段缺失时 `readNumber` 返回 0，会把解析失败伪装成 0 积分。
- 负数一律 clamp 到 0（`src/lobsterai-credits.ts:350-353,357-360`）—— 服务端在超额扣费/计量回滚下可能下发负值。

---

#### D. trae —— `src/trae-credits.ts`

**端点**（`src/trae.ts:59-63`），base 硬编码 `https://api.trae.cn`（`src/trae-credits.ts:154`）：

```
状态  POST /trae/api/v2/ug/checkin_credits/status        body {}
领取  POST /trae/api/v2/ug/checkin_credits/claim         body {}
余额  POST /trae/api/v2/pay/ide_user_ent_usage           body {"require_usage": true, "req_source": 2}
```

**请求头**：`traeCheckinHeaders` —— 约 20 个客户端头（`src/trae.ts:253-286`），含 `Authorization: Cloud-IDE-JWT <token>`、`X-Market-Client-Id`、`X-Market-User-Id`、`X-Device-Id`、`X-Lgw-Req-Sdk-Type: 3`、`Package-Type: stable_cn`、`X-Lscbd-Aid: 787976`、`X-Lscbd-Platform: windows`、`App-Version`、`X-Tt-Trace-Id`、`Vscode-Sessionid`、`X-Request-Id`、`Sec-Fetch-*`。

**设备身份是「每账号一套、稳定派生」**（关键，`src/trae.ts:288-309`）：

| 头 | 派生 | 说明 |
|---|---|---|
| `X-Device-Id` | `seededDigits(15, uid, 'devid')` | 15 位数字 |
| `X-Market-User-Id` | `seededStream(uid,'market',16)` 置 UUID v4 version/variant 位 | UUID v4 |
| `Vscode-Sessionid` | `seededStream(uid,'sess',32)` | 64 hex |

同一 `uid` 永远得到同一套值 → 多账号天然互异，规避服务端「每设备每天一次」配额（`src/trae.ts:290-295`）。

**状态响应**（`src/trae-credits.ts:196-208`）：`{checked_in, credits, enable}` → `active = enable===true`、`todayCheckedIn = checked_in===true`、`dailyCredit = credits`。其余字段（`streak_days` 等）如实置 0/空，不臆造。

**领取判定**（`src/trae-credits.ts:262-305`）：
- `readClaimCode` **兼容字符串 `"9074"`**（`src/trae-credits.ts:121-132`）—— 不能只 `typeof === 'number'`，后端在部分网关上以字符串返回，只认数字会误判为成功（code=0）。
- `code === 9074`（「签到人数过多」）→ `failed` + `errorType: 'BusinessError'` + `cooldownSecs: 300`（`src/trae-credits.ts:265-276`）。**不再换设备号重试** —— 设备身份已由 `uid` 确定性决定，旧前提不成立。
- `code === 0` → **补查一次 status 拿真实积分数**（`src/trae-credits.ts:280-296`）。

⚠️ **claim 响应不含积分数**（`src/trae-credits.ts:281-288`）：实测完整响应就是 `{"code":0,"message":"success"}`，没有 `credits` 字段。真实数值只在 **status 端点**的 `credits` 字段里（实测 `150`，与积分余额中「签到奖励」包的 `credits_limit:150` 吻合）。早期实现读 `body.credits` 恒为 0，界面显示「领取成功 +0 积分」。补查失败时 `credit` 为 0 但**仍是 claimed**。

⚠️ **claim 对「今天已签到」是幂等的**：实测重复领取同样返回 `{code:0,message:"success"}`，与真正成功**无法区分**（`src/trae-credits.ts:1042-1049` of jet-hub-rpc.ts）。因此 `credits.claimAll` 的 TRAE 分支**必须开启状态预检** —— 早期照抄 LobsterAI 传了 `precheckStatus: false`，于是已签到的账号被报成「领取成功」。

**网络重试与业务失败严格分开**（`src/trae-credits.ts:236-255,962-963` of AGENTS.md）：只对 `httpStatus === 0`（传输层失败）重试，间隔 1s，`retryCount = 3`；有状态码的业务失败**不重试**。

**签到错误分类与冷却**（`src/trae-credits.ts:53-100`，对齐 `trae-mate/cooldown.rs`）：

| 条件 | 类型 | 冷却 |
|---|---|---|
| HTTP 200 + `code=1005` | `PlanLimit` | 43200s（12h） |
| HTTP 429 | `SoftRate` | 60s |
| HTTP 401 | `SessionDead` | **-1 = 永久** |
| HTTP 404 | `NotFound` | 60s |
| 5xx | `Server` | 600s |
| 4xx（其余） | `Client` | 600s |
| 业务码非 0 | `BusinessError` | 300s |
| 成功/无码 | `Unknown` | 0（不冷却） |

**余额解析**（`src/trae-credits.ts:316-368`）：`user_entitlement_pack_list[]`，每项 `entitlement_base_info.quota.credits_limit` 为额度、`usage.credits_amount` 为已用；余额 = `∑(credits_limit - credits_amount)`；`credits_limit <= 0` 的条目跳过。

⚠️ **必须带 `require_usage: true`**：不带时上游不返回 `usage` 明细，`credits_amount` 恒缺省为 0，余额会等于额度总额（虚高）（`src/trae-credits.ts:1220` of AGENTS.md）。

---

#### E. qoder —— `src/qoder-credits.ts`（**只有查额度，无签到**）

```
GET {product.openApiBase}/sash/api/v2/me/usage
Authorization: Bearer <token>
Cosy-ClientType: 5
User-Agent: Qoder
```

- **不需要 WASM 签名**（与模型列表端点 `/api/v2/model/list` 不同）（`src/qoder-credits.ts:6-8`）。
- 响应：`{displayMode, qoderUsage: {userType, userQuota, addOnQuota, dedicatedResourcePackages[], expiresAt}}`。
- ⚠️ **余额不只在 `userQuota` 里**：实测该账号 `userQuota.remaining = 0` 而 `addOnQuota.remaining = 100`，只读 `userQuota` 会显示 0（`src/qoder-credits.ts:27-29`）。
- `displayMode === 'enterprise'` → 返回 `null`（企业版不提供额度数字，只给外部链接，报 0 会误导）（`src/qoder-credits.ts:108-111,149-150`）。
- **为什么不做签到**（`src/qoder-credits.ts:31-36`）：`/sash/api/v1/me/campaigns` 实测返回 `{"showCampaign":false,"claimable":false,"campaigns":[]}`，且逆向中**未发现签到动作端点**（只有活动查询）。⚠️ 全仓库 grep 确认该 campaigns 端点**只在注释里被引用，代码中未实现**。

---

## 2. 通用抽象与调度机制

### 2.1 三个共享数据类型（这才是真正的「抽象」）

`src/credits.ts` **不是**接口定义文件，而是 **CodeBuddy 的实现 + 三个被复用的类型**。文件头注释明说另两套协议「刻意分开」，硬合并只会让文件出现大量 `if (provider === 'lobsterai')` 分支（`src/lobsterai-credits.ts:3-7`）。

| 类型 | 定义 | 被谁复用 |
|---|---|---|
| `CheckinStatus` | `src/credits.ts:64-87` | buddy / workbuddy / trae（trae 只填部分字段，其余置 0，`src/trae-credits.ts:196-208`） |
| `ClaimOutcome` | `src/credits.ts:90-94` | **全部 5 个有签到能力的 provider** |
| `CreditBalance` / `CreditPackage` | `src/credits.ts:120-167` | **全部 6 个 provider** |
| `roundCredits()` | `src/credits.ts:488-490` | 导出供 `qoder-credits.ts` 复用（多包相加的浮点尾数噪声是所有 provider 的共同问题） |

`ClaimOutcome` 是判别联合（`src/credits.ts:90-94`）：

```ts
type ClaimOutcome =
  | { kind: 'claimed'; credit: number; streakDays: number; isStreakDay: boolean; delayedMessage?: string }
  | { kind: 'already-claimed'; message: string }
  | { kind: 'inactive'; message: string }
  | { kind: 'failed'; code: number; message: string }
```

设计要点：**`already-claimed` / `inactive` 与 `failed` 严格分开** —— 前者是正常业务状态，后者才是需要用户关注的问题。`computeClaimSummary` 把它们分别计数（`src/jet-hub-rpc.ts:171-203`），并有编译期穷尽性检查（`const exhaustive: never = outcome`，`:190-199`）。

### 2.2 编排层：三个泛型 `collect*` 函数

`src/jet-hub-rpc.ts` 抽出 `CreditsEndpointDeps`（`:217-277`），把「逐账号顺序执行、单账号失败不中断、凭据解析在 try 之内」这套**通用编排**与各协议的下钻函数解耦。泛型化让三个 `collect*` 只写一遍，各协议注入自己的实现（`:210-215`）。

| 函数 | 位置 | 作用 |
|---|---|---|
| `collectCreditsStatus` | `:290-323` | 逐账号查签到状态 |
| `collectClaimResults` | `:335-406` | 逐账号一键领取 |
| `collectCreditBalances` | `:421-472` | 逐账号查积分余额（**保留失败原因**，与 status 不同） |

**三条共同纪律**：

1. **顺序执行，不并发**（`:306,437`）—— 「并发易触发风控」。`account-probe.ts` 同样顺序执行（`:231-233`），理由是并发会触发真正想验证的限流，得到假阳性。
2. **单个账号失败不中断整批**，且**凭据解析也在 try 之内**（`:309-319,372-401,441-463`）。`credentialRef()` 会对名称做正则校验（非法名称抛 `TypeError`），若留在 try 之外，任一账号的异常都会冒泡到外层 catch，使整批请求以 `jet-hub/handler-failed` 失败。
3. **包含已停用账号**（`:282-283,328-330,415-417`）—— 停用只影响账号池的自动选择与限流切换，与「该账号今天领了没」无关。

**`precheckStatus` 开关**（`:248-259,367,378-393`）：默认 `true`（先查状态再领取，可短路活动未开/今日已领）。LobsterAI 与 CodeArts 传 `false`（它们流程自带预检）；**TRAE 必须保持 `true`**（因为 claim 幂等但与成功不可区分）。

⚠️ **`fetcher` 必须经 deps 注入**（`:260-276`）：真实签名是 `(credential, product, fetcher)`，而 `claim` 接口声明为 `(credential, product, entry)`。历史写法用 `as unknown as` 把签名不匹配压过去，调用点传的第三个实参 `entry` 落进 `fetcher` 位置，运行时抛 **`TypeError: fetcher is not a function`** —— 真实缺陷：用户一键领取 4 个 CodeBuddy 账号全部失败（`AGENTS.md:1115-1143`）。

### 2.3 RPC 分派（真正的「注册」机制）

**没有 provider 注册表。** `handleMethod` 里一串 `if (req.provider === ...)`：

| 方法 | buddy/workbuddy | codearts | lobsterai | qoder | trae |
|---|---|---|---|---|---|
| `credits.status` | 默认实现（`jet-hub-rpc.ts:994-1003`） | 如实返回 `null`（`:956-969`） | 如实返回 `null`（`:970-982`） | — | 如实返回 `null`（`:983-993`） |
| `credits.claimAll` | 默认实现（`:1062-1070`） | `precheckStatus:false` + 注入 `claim`（`:1010-1022`） | `precheckStatus:false` + 动态 `clientVersion`（`:1023-1036`） | 无分支 | 注入 `fetchStatus` + `claim`，保持预检（`:1037-1061`） |
| `credits.balances` | 默认实现（`:1164-1172`） | `fetchBalanceDetailed` 钩子（`:1081-1111`） | `fetchBalance`（`:1112-1119`） | **独立内联循环**（`:1120-1155`） | `fetchBalance`（`:1156-1163`） |

未登记的 provider → `{code:'bad-request', message:'unsupported provider: X'}`。

三个「如实返回 `null`」的分支很关键：CodeArts / LobsterAI / TRAE **没有与 `CheckinStatus` 同构的独立状态端点**（要么需要多步才能得到、要么语义不同），代码选择**如实返回 null 而不是臆造一份状态对象**（`:957-961,971-974,984-985`）。

`credits.balances` 的 qoder 分支**没有走 `collectCreditBalances` 泛型** —— 因为 `fetchQoderCreditBalance` 只吃 `QoderCredential`，不需要产品配置转发（`:1123-1124`）。这是泛型抽象的一处漏点。

### 2.4 触发时机与调度（**核心结论：签到无自动调度**）

| 动作 | 触发方式 | 频率 | 证据 |
|---|---|---|---|
| **签到/一键领取** | **仅用户手点按钮** | 手动 | `plugin-src/client/jet-hub.js:646-651`；`docs/lobsterai-integration-plan.md:1301` |
| 查签到状态 | 无前端消费者 | — | `README.md:476-478`（`credits.status` 仅供外部脚本或直接 RPC） |
| 查积分余额 | 面板挂载 + 「刷新积分」按钮 | 手动 | `plugin-src/client/jet-hub.js:617-627` |
| **凭据续期** | `setInterval` | **每 30 分钟** | `src/index.ts:398,427-442` |
| 模型列表刷新 | `setInterval` | 每 2 小时 | `src/models.ts:24`；`src/service.ts:355` |
| 限流重测/重置 | 用户点按钮 | 手动 | `src/jet-hub-rpc.ts:920-937` |
| 清理过期限流标记 | — | **无调用方**（死代码） | `src/account-pool.ts:622-637`；全仓库 grep 无调用 |

**续期调度的两个细节**：
- 判据**只看 `refreshable`，不看 `enabled`**（`src/index.ts:423-428`）。早期写成 `a.refreshable && a.enabled`，于是「所有账号都被停用」时续期定时器**根本不启动**，凭据一路过期到 refresh_token 失效（真实缺陷）。
- 启动时先检查是否有可续期账号，没有就不起定时器；`unref()` 避免阻塞进程退出；`ctx.effect()` 注册清理钩子（`docs/lobsterai-integration-plan.md:1295-1299`）。

**项目文档对「自动签到」的明确立场**（`docs/lobsterai-integration-plan.md:1303-1317`）：v1 **不做自动签到**，保持与 CodeBuddy 面板一致（只有按钮）。若确实要做，推荐：复用现有 30 分钟间隔定时器（**不做整点对齐**）、每小时最多尝试一次（模块内记 `lastCheckinAttemptMs`）、只对 `enabled` 账号执行、失败静默。⚠️ 这段只是**建议，未实现**。

参考实现（Go `lobsterai2api`）**有**定时任务（签到 9 点 / 21 点、keepalive 22 点，`docs/lobsterai-integration-plan.md:180,199`）—— 本插件**刻意没移植**。

### 2.5 幂等矩阵（四套机制，同一天重复领取的行为）

| provider | 幂等载体 | 重复领取时的实际行为 | 本地是否记录 |
|---|---|---|---|
| buddy/workbuddy | **服务端业务码** | HTTP 400 + `code:10001` → `already-claimed` | ✗ |
| lobsterai | **客户端幂等键 + 两步预检** | `claimedToday:true` → `already-claimed`（不发领取请求） | ✗ |
| codearts | **仅活动列表预检** | `claimable:false` + `status ∈ 已领态` → `already-claimed` | ✗ |
| trae | **服务端幂等但与成功不可区分** | claim 仍回 `{code:0,"success"}` → **必须靠 status 的 `checked_in` 区分** | ✗ |

**全仓库 grep 无 `lastCheckin` / `lastClaim` / `claimedDate` / `checkinRecord` 之类字段**（唯一命中是 `docs/lobsterai-integration-plan.md:1314` 的**建议** `lastCheckinAttemptMs`，未实现）。即：**「今天领没领」从不落地本地，每次都问服务端。**

### 2.6 持久化

| 数据 | 存储位置 | 证据 |
|---|---|---|
| 账号条目（`ProviderAccountEntry[]`） | `ctx.settings` 的 namespace `jet-hub` → 配置文件 | `src/account-pool.ts:19,64-75` |
| 凭据本体 | `ctx.credentials`（与账号列表**各自独立**） | `src/account-pool.ts:114-115,313-317` |
| 每模型限流重置时间 | 账号条目的 `modelRateLimits[modelId] = resetAtMs` | `src/types.ts:59-60`；`src/account-pool.ts:602-619` |
| TRAE 签到设备代次 | 账号条目的 `traeCheckinDeviceGeneration` | `src/types.ts:61-74`；`src/account-pool.ts:648-671` |

**`ProviderAccountEntry` 完整字段**（`src/types.ts:42-75`）：`id`（`{provider}-{shortid}`）、`provider`、`nickname`、`enabled`、`credentialRef`（`{PROVIDER}_ACCOUNT_{UUID_SHORT}`）、`createdAt`、`expiresAt?`、`refreshable`、`modelRateLimits?`、`traeCheckinDeviceGeneration?`。

**两个关键的持久化纪律**：
1. **进程内权威副本**（`src/account-pool.ts:127-136`）：不直接依赖 `scope.get()`，因为 settings 的 resolved 快照在 `replace()` 后未必立即更新，而每次写入都是「读 → 改 → 整体 replace」。若以滞后快照为读源，并发/连续的 `updateModelRateLimit` 会互相覆盖（典型表现：多个账号触发限流后，settings 里一条 `modelRateLimits` 都没有）。
2. **整体 replace 必须携带全部字段**（`src/account-pool.ts:184-198,242-252`）：`writeAccounts` 必须连同 `disabledModels` 一起写回，`writeModels` 必须连同 `accounts` 一起写回，否则会把同一 namespace 下的另一字段抹掉。

### 2.7 能力上报（`credits-capabilities.js`）

**这是一张硬编码在前端的静态表，不是服务端下发的。**

```js
// plugin-src/client/credits-capabilities.js:54-65
export const CREDITS_CAPABILITIES = Object.freeze({
  codearts:  Object.freeze({ balance: true,  dailyCheckin: true  }),
  buddy:     Object.freeze({ balance: true,  dailyCheckin: true  }),
  workbuddy: Object.freeze({ balance: true,  dailyCheckin: false }),
  lobsterai: Object.freeze({ balance: true,  dailyCheckin: true  }),
  qoder:     Object.freeze({ balance: true,  dailyCheckin: false }),
  trae:      Object.freeze({ balance: true,  dailyCheckin: true  }),
})
```

两个查询函数 `supportsCreditBalance(provider)` / `supportsDailyCheckin(provider)`（`:73-84`）。

**四条设计要点**（`plugin-src/client/credits-capabilities.js:1-51` + `AGENTS.md:1249-1254`）：
1. **两项能力彼此独立，不能互相推断** —— 不能因为「国际版没有签到」就推断「也查不到余额」。
2. **判定一律默认关闭**：未登记的 provider 视为两项全无。这样将来新增 provider 忘登记时，最坏结果是「暂时看不到积分」，而不是「每次打开面板都发一个必然失败的请求」。
3. **门控在发起请求之前，不是 UI 上吞错误**：`loadCredits` / `claimCredits` 函数内部各有一道守卫（`:585,647`），「按钮不渲染只是 UI 便利，不是安全边界」。
4. **改动能力矩阵必须同步 `PROVIDERS` 列表**：单测有一条断言锁死两者条目集合相等（`tests/unit/credits-capabilities.spec.ts`，由 `AGENTS.md:1254` 描述）。

**历史缺陷**（`plugin-src/client/credits-capabilities.js:9-14`）：客户端在面板挂载时对**所有** provider 无条件调用 `credits.balances`，当时 CodeArts 无积分能力，于是每打开一次 CodeArts 面板都会在控制台留一条必然失败的报错，并把账号卡片的「积分」渲染成「查询失败」。**修法不是在 UI 上吞掉错误，而是不发起这个请求。**

---

## 3. 探活 / 限流 / 轮换

### 3.1 额度与限流解析（`rate-limit-parser.spec.ts` 对应的实现）

测试文件是 `tests/unit/rate-limit-parser.spec.ts`，被测实现是 **`src/llm-adapter.ts`**（不是独立模块）：

| 导出 | 位置 | 作用 |
|---|---|---|
| `RATE_LIMIT_BUSINESS_CODE = 6004` | `src/llm-adapter.ts:1457` | CodeBuddy 系「用量超出频率限制」业务码 |
| `RATE_LIMIT_PATTERN` | `:1475-1476` | 中英双语正则兜底 |
| `hasRateLimitBusinessCode()` | `:1485-1494` | 只认 JSON 顶层 `code`，兼容 `6004` / `"6004"` |
| `isRateLimited()` | `:1497-1499` | `hasRateLimitBusinessCode(body) \|\| RATE_LIMIT_PATTERN.test(body)` |
| `RESET_TIME_PATTERN` | `:1510` | 捕获**真实时区** |
| `parseRateLimitError()` | `:1513-1537` | 返回 `{modelId, resetTimeMs}` |

```ts
// src/llm-adapter.ts:1475-1476
const RATE_LIMIT_PATTERN =
  /频率限制|频率超出|使用量已超出|重置|rate.?limit|frequency limit|usage exceeds|too many requests/i

// src/llm-adapter.ts:1510
const RESET_TIME_PATTERN = /(?:将在|reset at)\s+([\d-]+\s+[\d:]+)\s+(UTC[+-]\d+(?::\d+)?)/i
```

**三个关键设计决策**：

1. **结构化 code 优先于文案**（`:1454-1456`）：code 与语言无关，且不受服务端改文案影响。但**不采用「全文包含 6004」** —— `requestId` 是 UUID，任意数字子串都可能偶然出现，文本匹配会产生假阳性；只认 JSON 顶层的 `code` 字段（`:1481-1483`）。
2. **中英双语必须都列全**（`:1459-1473`）：历史缺陷（用户报障，**仅国际版暴露**）—— 早期只有中文词，而国际版 WorkBuddy 返回英文 `usage exceeds frequency limit ... your usage will reset at <时间> UTC+8`。结果 `isRateLimited` 恒为 false → 适配器**跳过整个账号切换分支**，直接抛原始 6004 JSON；错误码也因 HTTP 400 退化成 `INVALID_REQUEST` 而非 `QUOTA_EXCEEDED`。国内版返回中文，所以该缺陷长期潜伏。
3. **不硬编码 UTC+8**（`:1502-1509`）：用捕获到的真实时区拼接。早期只列中文句式，导致国际版即使判定为限流也只能走「1 小时后重试」的兜底，丢掉服务端给出的真实重置时刻（UI 限流徽章显示错误时间）。

**重置时间的两级取值**：

```ts
// src/llm-adapter.ts:1517-1536
const data = JSON.parse(body)
const resetMatch = RESET_TIME_PATTERN.exec(data.msg)
if (resetMatch) {
  const resetMs = Date.parse(`${resetMatch[1]} ${resetMatch[2]}`)
  if (!Number.isNaN(resetMs)) return { modelId: currentModel, resetTimeMs: resetMs }
}
if (isRateLimited(body)) {
  return { modelId: currentModel, resetTimeMs: Date.now() + 3_600_000 }  // fallback: 1 小时后
}
return null
```

**测试锁定的契约**（`tests/unit/rate-limit-parser.spec.ts`）：
- 国内版中文 6004 → `isRateLimited === true`，重置时间解析为 `Date.parse('2026-09-11 18:08:17 UTC+8')`（`:25-40`）
- 国际版英文 6004 → 必须识别 + **必须解析出服务端真实重置时间，不能退化成 fallback 的「1 小时后」**（`:45-55`）
- 裸英文文案（无 JSON 包裹）也能兜底识别（`:57-61`）
- 业务码可解析但文案无法解析 → 仍判限流并兜底（`:63-70`）
- 字符串形式 `"6004"` 同样识别（`:72-74`）
- **6 个反例不得误判**（`:76-90`）：`model not found`、`401 invalid token`、`unsupported parameter`、`11102 service info not found`、`context length exceeded`、`internal server error`
- 非 JSON 且无限流措辞 → 返回 null 不抛错（`:92-95`）
- 尊重捕获到的真实时区（`UTC+0` 不被改写成 UTC+8）（`:97-101`）

**限流信息如何影响账号池调度**：解析出的 `resetTimeMs` 写入 `accountPool.updateModelRateLimit(accountId, modelId, resetTimeMs)`，成为该账号**该模型**的豁免时间；`getAvailableAccount` 在选号时跳过 `resetAt > now` 的账号（`src/account-pool.ts:540-546`）。

**另一处错误码归一化**（`src/llm-adapter.ts:386-392`）：

```
HTTP 401/403            → 'AUTH'
body 命中 quota 措辞     → QUOTA_EXCEEDED_CODE
HTTP 429                → 'RATE_LIMIT'
HTTP 400 + 上下文超限    → CONTEXT_WINDOW_EXCEEDED_CODE
HTTP 400 其余           → 'INVALID_REQUEST'
```

### 3.2 账号探活（`src/account-probe.ts`）

**探活做什么**：对每个**带限流标记的模型**真实发一次最小对话请求，只有请求正常完成才清除该模型的标记（`src/account-probe.ts:9-15,221-224`）。

- 探测提示语：`'只回答两个字：收到'`（`:51`，与 e2e 探针保持一致以最大化可比性）
- 单次超时：`PROBE_TIMEOUT_MS = 120_000`（`:61`）。理由：CodeArts 适配器排队时会以 10 秒间隔重试、最长 30 分钟，设置页按钮不能等那么久；**宁可保守留标记，也不要因为等太久让 UI 卡死**。
- **频率：无定时，纯手动**（RPC `account.retest` / `retestAll` / `reset` / `resetAll`，`src/jet-hub-rpc.ts:920-937`）

**两个关键设计**（`src/account-probe.ts:22-29`）：

1. **不传 `accountPool` 给适配器**（`:115-120`）。适配器只在拿到 `accountPool` 时才会切换账号、写限流标记；探测必须只针对**指定账号**且不能产生副作用，否则「重测 A 账号」会顺带污染其他账号的标记。同时 `refresh` 设为 no-op（探测不应触发全局续期流程）。
2. **停用账号也要能重测**。凭据解析走 `resolveCredentialForAccount`（按 id，**不检查 enabled**，`src/account-pool.ts:453-469`），而非 `getAvailableAccount`（自动选择，只认启用账号）。

**判定标准**（`src/account-probe.ts:95-103,169-176`）：

| 探测结果 | 判定 | 标记处理 |
|---|---|---|
| 流正常消费完（即使正文为空） | `ok: true` | **清除**该模型标记 |
| 失败且属限流（`RATE_LIMIT` / `QUOTA_EXCEEDED` / `QUOTA`，或文案命中） | `ok: false`，文案「仍受限：…」 | **保留** |
| 失败但不属限流（鉴权过期、网络中断） | `ok: false`，文案「无法确认：…」 | **保留** |
| 凭据不可用 | `ok: false`，文案「无法确认：凭据不可用」 | **保留** |

`isRateLimitFailure` 同时认三种 code：buddy/codearts 用字面量 `'QUOTA_EXCEEDED'`，harness 常量 `QUOTA_EXCEEDED_CODE` 是 `'QUOTA'` —— 两者都认，避免因词汇差异把限流误判成「未知错误」（`:96-100`）。

**适配器选择按产品判定**（`src/account-probe.ts:131-154`）：`productById(provider)` 命中 → `BuddyAdapter`；`lobsteraiProductById(provider)` 命中 → `LobsteraiAdapter`；否则 → `CodeArtsAdapter`。⚠️ 注释明确警告：历史上这里只判断 `provider === 'buddy'`，导致 workbuddy 落入 else 分支、用华为云 HMAC 签名去发 WorkBuddy 凭据而必然失败；lobsterai 若不加分支会重蹈覆辙。回归测试见 `tests/unit/account-probe-adapter.spec.ts:68-87`。

**reset（重置）与 retest 语义严格区分**（`src/account-probe.ts:13-15`）：`reset` **不做任何网络请求**，直接清除标记，用于用户已知额度已恢复、只想清掉显示的情况。

**触发原因**：账号卡片上的「限额重置」只是**一次 429 事件的快照** —— 它记录的是服务端当时给出的「预计恢复时间」，而不是该账号此刻的真实可用性。服务端常在重置时间到达前提前放行，于是出现「显示超额使用但发消息正常回复」（`src/account-probe.ts:3-7`）。

### 3.3 轮换与耗尽

**触发条件**：请求收到非 2xx 后，按 provider 各自的策略判断是否换号。

| provider | 触发条件 | 换号上限 | 是否把 `tried` 传给池 | 证据 |
|---|---|---|---|---|
| buddy | `isRateLimited(errorText)` | 无显式上限（用 `tried` 集合保证每账号一次） | ✓ | `src/buddy-adapter.ts:1042-1074` |
| codearts | `isRateLimited(errorText)` + `parseRateLimitError` 非 null | 无显式上限（`rateLimitTried` 集合） | ✗ **只传 2 参** | `src/llm-adapter.ts:982-1002` |
| lobsterai | `shouldRotateLobsteraiAccount(kind)` = `kind !== 'none'` | `LOBSTERAI_MAX_ROTATE = 3`，循环 `maxRotate = 2` | ✓ | `src/lobsterai-adapter.ts:90,938-1003` |
| trae | `shouldRotateTraeAccount(kind)` = `kind !== 'none'` | `TRAE_MAX_ROTATE = 3`，循环 `maxRotate = 2` | ✓ | `src/trae-adapter.ts:133,917-947` |

⚠️ **「减 1」的原因**（`src/lobsterai-adapter.ts:947-950`）：Go 的循环计数**包含首个账号**（每次迭代都 `PickExcluding` 取一个号），而适配器在进入循环**之前**已经用首个凭据发过一次请求。若不减，总请求数会变成 `1 + MaxRotate = 4`，比 Go 多一次。

⚠️ **为什么必须把 `tried` 传给池**（`src/lobsterai-adapter.ts:973-976`）：失败类别为 5xx / 请求错误时**不写限流标记**（它们不是限流，不该留徽章），刚失败的账号仍是池里排序第一；不排除就会拿回同一个账号、命中 `tried.has` 而**立即 break** —— 换号形同虚设。对齐 Go 的 `PickExcluding(tried)`。

⚠️ **codearts 分支的差异**：`getAvailableAccount('codearts', options.model)` 只传 2 个参数（`src/llm-adapter.ts:990`），靠调用方自己的 `rateLimitTried.has(next.entry.id)` 检查兜底（`:991`）。因为 codearts 分支在每次限流时都会先 `updateModelRateLimit`（写标记 → 该账号被 filter 排除），实际不会原地打转。**这是三套实现里唯一不传 `tried` 的**。

**耗尽的处理**（全部失败后）：

| provider | 行为 | 证据 |
|---|---|---|
| lobsterai | 抛 `LlmError('lobsterai: 模型 X 所有账号均不可用（<最后一次真实原因>）', lastKind === 'hard-credit' ? 'QUOTA_EXCEEDED' : httpErrorCode(lastStatus), {status: lastStatus})` | `src/lobsterai-adapter.ts:998-1003` |
| codearts | 抛 `LlmError('codearts: 模型 X 所有账号均受限，请稍后再试', 'QUOTA_EXCEEDED')` | `src/llm-adapter.ts:998-1001` |

**`lastStatus` / `lastKind` / `errorText` 必须成组更新**（`src/lobsterai-adapter.ts:922-932,989-996`）。历史缺陷（S3/S4）：单把 `kind` 留在循环外，会出现「A 账号的 kind 配 B 账号的 status/body」—— 实测 A=402(积分不足) → B=503 时最终 code 变成 `SERVER`，用户完全看不到「积分不足」这个真实原因；且会拿 A 的 kind 去判断「要不要给 B 记限流徽章」，给 B 写上「该模型限流 1 小时」这种**虚假信息**。回归测试见 `tests/unit/lobsterai-rotation-exhaustion.spec.ts:42-76`（断言最终错误必须带**最后一次**的真实原因）。

另一个回归点：**耗尽后不重复消费已 drain 的响应体**（`tests/unit/lobsterai-rotation-exhaustion.spec.ts:78-111`）—— 换号循环里 `await response.text()` 会 drain 响应体；若退出循环后又对同一个 response 调用 `text()`/`json()`，会抛 `TypeError: Body is unusable`，把真实错误掩盖成解析异常。

### 3.4 错误分类（`lobsterai-errors.ts` / `trae-errors.ts`）

**两个文件都是纯函数，无副作用**，设计哲学是「只移植分类，不移植自动冷却状态机」（`src/lobsterai-errors.ts:7-19`；`src/trae-errors.ts:7-12`）。Go 参考实现会在分类后自动执行 `Cooldown(CoolHard, 12h)` / `Disable(uid)` —— 表现为账号被**静默停用**。本插件刻意不这样做：账号池只有 `modelRateLimits` 与用户手动的 `enabled` 开关，面板上有具体的限流徽章与「重测 / 重置」按钮。设计哲学是「**如实展示 + 用户可主动验证**」。

**`lobsterai-errors.ts` 的三个策略函数**：

| 函数 | 位置 | 语义 |
|---|---|---|
| `classifyLobsteraiError(status, body)` | `:100-117` | HTTP 码 + 响应体 → 7 类 |
| `shouldRotateLobsteraiAccount(kind)` | `:139-141` | `kind !== 'none'` —— **任何非 2xx 都换号** |
| `recordsLobsteraiRateLimit(kind)` | `:157-159` | 只有 `hard-credit` / `soft-rate` / `not-found` 记徽章 |
| `isLobsteraiTerminalError(kind)` | `:169-171` | 只有 `session-dead` 是终态 |

**判定顺序即优先级**（`:78-95`，不可重排）：

```
1. 402                     → hard-credit     （状态码最权威）
2. body 含 hard 关键词      → hard-credit     （★ 排在 429/404 之前）
3. body 含 session-dead 标记 → session-dead    （★ 排在 429/404 之前）
4. 429                     → soft-rate
5. 404                     → not-found
6. >= 500                  → server
7. >= 400                  → client
8. 否则                     → none
```

- **为什么 body 关键词要排在状态码之前（除 402）**：实测上游用 **400 + 中文「积分不足」**表达余额耗尽，只按状态码会把这类错误误判成 `client`（可重试），于是反复重试一个永远不会成功的账号（`:89-91`）。
- **为什么 session-dead 要排在 429/404 之前**：`40100`/`40101` 可能与 4xx 同时出现，会话已死时任何「换号重试」都没意义（该账号需重新登录）（`:93-95`）。
- 余额不足关键词**中英双通道**（`:54-59`）：`insufficient credit` / `no credit` / `credit exhausted` / `out of credit` / `quota exceeded` / `payment required` / `freecreditsused` / **积分不足** / **额度不足** / **余额不足** / **积分用完** / **额度用尽** / **没有积分** / **积分耗尽**。

**`trae-errors.ts`** 同构，7 类：`none` / `hard-plan`(1005) / `soft-rate`(429 或 4011) / `session-dead`(401) / `quota-exceeded`(4008) / `not-found`(404) / `server` / `client`（`src/trae-errors.ts:23-39,80-126`）。

⚠️ **`quota-exceeded`（4008）必须排在 `soft-rate`（4011）之前**（`src/trae-errors.ts:90-98`；`AGENTS.md:898-902`）：两者可能同时出现在一个响应体里（网关把多个错误码拼在 msg 中）。`quota-exceeded` 需长冷却，`soft-rate` 只需短冷却 —— 让较轻的类别抢先命中，会让一个已耗尽额度的账号在 60 秒后被反复重试，用户看到的却是「稍后再试」。**真实缺陷**，`tests/unit/trae-errors.spec.ts` 已锁死该顺序。

**`recordsTraeRateLimit`**（`src/trae-errors.ts:148-150`）：`hard-plan` / `soft-rate` / `not-found` / `quota-exceeded` 记徽章；`session-dead` / `server` / `client` **不记** —— 「徽章的含义必须是『这个模型受限』，而不是『这个账号出过错』」（`src/lobsterai-errors.ts:152-155`）。

**冷却时长的落点**：`classifyTraeCheckinError` 返回的 `cooldownSecs` 供**调用方**决定冷却（`src/trae-credits.ts:53-100`）。而 chat 路径的限流标记实际写入值来自 `parseRateLimitError`，抓不到时用 `LOBSTERAI_RATE_LIMIT_FALLBACK_MS = 3_600_000`（1 小时）兜底（`src/lobsterai-adapter.ts:74-80,962-971`）。⚠️ **注意**：`lobsterai-errors.ts` 里描述的 12h / 60s 是 **Go 参考实现的策略值**，本插件实际写入的是「服务端声明值或 1 小时」，两者不一致（这是有意的：本插件的标记是「快照 + 可主动重测」，不是冷却状态机）。

### 3.5 凭据续期（`src/refresh.ts`）

虽不是签到机制，但与账号池稳定性直接相关：

| 常量/函数 | 值/位置 | 说明 |
|---|---|---|
| `REFRESH_LEAD_MS` | `3_600_000`（1h），`src/refresh.ts:2` | 在过期前 1 小时触发 |
| `REFRESH_RETRY_MS` | `600_000`（10min），`:4` | 普通失败重试 |
| `REFRESH_ABNORMAL_NETWORK_RETRY_MS` | `60_000`（1min），`:6` | 异常网络重试 |
| `computeFirstRefreshDelayMs` | `:32-40` | 触发点 = now + 1h，再叠加 **0-59 秒随机偏移**（防惊群） |
| `RefreshScheduler` | `:43-114` | `arm` / `stop` / `refreshOnce` / `run` |
| `isRefreshTokenExpired` | `:21-25` | **结构化判定**（`error.name === 'RefreshTokenExpiredError'` 或消息含 refresh_token），不用 `instanceof` |

⚠️ **为什么用结构化判定而非 `instanceof`**（`:16-20`）：CodeArts（`oauth.ts`）与 Buddy（`buddy-oauth.ts`）各自导出同名 `RefreshTokenExpiredError`，跨模块 identity 不同，用 `instanceof` 会让其中一个 provider 的失效信号穿透为「可重试」而无限重试。

**`generation` 代号机制**（`:46-47,55-57,69-72,93-96`）：`stop()`/`arm()` 都会推进它，用于让在途 `run()` 放弃失败后的重试武装，避免登出后调度器复活。

---

## 4. 可迁移到我们网关的设计清单

### 4.1 强烈建议直接借鉴（与平台无关的工程纪律）

| # | 机制 | 为什么值得抄 | 证据 |
|---|---|---|---|
| **T1** | **「查不到 ≠ 为 0」三态语义**：`null` = 查询失败 / `0` = 真实为 0 / `>0` = 有额度。UI 与日志必须能区分，否则网络故障会显示成「额度被清空」 | 所有 provider 都遵守；`fetchLobsteraiCreditBalance` 甚至专门加了一条「total 为 0 且明细为空 → 返回 null」的兜底 | `src/credits.ts:432-434`；`src/lobsterai-credits.ts:304-306,354-356`；`src/codearts-credits.ts:169-175` |
| **T2** | **失败必须带原因**，不能压成笼统文案 | 「签名头位置错」「AK 限流」「凭据过期」处置方式完全不同，压成「查询失败」会让排查无从下手 | `src/codearts-credits.ts:214-235,454-460`；`src/credits.ts:222-227` |
| **T3** | **非 2xx 先取文本再解析 JSON** | 凭据失效时网关常返回 HTML 错误页，`response.json()` 抛 `Unexpected token '<'` 对用户毫无意义 | `src/credits.ts:236-275`；`AGENTS.md:912` |
| **T4** | **判定优先用结构化业务码，文案只作兜底** | code 与语言无关、不受服务端改文案影响 | `src/llm-adapter.ts:1454-1456,1485-1494` |
| **T5** | **批处理：顺序执行 + 单条异常隔离 + 凭据解析也在 try 之内** | 并发易触发风控；单账号失败不该中断整批；凭据解析抛错若在 try 外会让整批以框架错误失败 | `src/jet-hub-rpc.ts:290-323,335-406,421-472` |
| **T6** | **「正常业务状态」与「失败」必须分成不同枚举值** | `already-claimed` / `inactive` 不是错误；把它们计成 `failed` 会让用户去排查不存在的问题 | `src/credits.ts:90-94`；`src/jet-hub-rpc.ts:171-203` |
| **T7** | **穷尽性检查**：判别联合新增分支时用 `const x: never = outcome` 强制作者显式决定归类 | 防止新 provider/新结果类型被静默漏计 | `src/jet-hub-rpc.ts:190-199` |
| **T8** | **金额累加后统一规整两位小数**，并 clamp 负值 | 服务端精确值本身带浮点噪声（`55.67000031`），多包相加会显式化；超额扣费/计量回滚会下发负值 | `src/credits.ts:466-490`；`src/qoder-credits.ts:70-88`；`src/lobsterai-credits.ts:350-353` |
| **T9** | **区分「终身额度」与「本周期额度」两个口径** | 实测同一响应里 `TotalDosage=655` 而 IDE 显示 `155.67`，用错口径数字凭空多出一大截且用户无从核对 | `src/credits.ts:106-118,154-156,402-403` |
| **T10** | **能力矩阵默认关闭 + 门控在发请求之前** | 未登记平台最坏结果是「看不到」，而不是「每次打开页面发一个必然失败的请求」 | `plugin-src/client/credits-capabilities.js:48-50,73-84` |
| **T11** | **刷新时间从错误文案里正则捕获真实时区，不硬编码** | 服务端给的是权威恢复时刻，兜底值会显示错误时间 | `src/llm-adapter.ts:1502-1531` |
| **T12** | **轮换时把「已试过的账号集合」传进选号函数**，而不是让调用方自己跳过 | 否则不写限流标记的失败（5xx / 请求错误）会原地打转，换号形同虚设 | `src/account-pool.ts:510-531`；`src/lobsterai-adapter.ts:973-976` |
| **T13** | **换号循环里的 `status` / `kind` / `errorText` 必须成组更新** | 否则会出现「A 账号的 kind 配 B 账号的 status」→ 错误码错配 + 给错误账号写限流徽章 | `src/lobsterai-adapter.ts:922-932,989-996` |
| **T14** | **探测（探活）必须无副作用**：不把账号池传给适配器，凭据解析按 id 且不检查 enabled | 否则「重测 A」会污染其他账号的标记；停用账号也需要能探测 | `src/account-probe.ts:22-29,115-120` |
| **T15** | **标记是「快照 + 可主动验证」，不是「自动冷却状态机」** | 服务端常在重置时间到达前提前放行；自动禁用会让用户看不到真实状态、也无法主动验证 | `src/account-probe.ts:3-15`；`src/lobsterai-errors.ts:7-19` |
| **T16** | **凭据续期的终态判定要用结构化依据，不能 `instanceof` 跨模块同名异常** | 跨模块 identity 不同会让失效信号穿透为「可重试」而无限重试 | `src/refresh.ts:16-25` |
| **T17** | **凭据续期判据不能按 `enabled` 过滤** | 否则「所有账号都被停用」时续期定时器不启动，凭据一路过期到 refresh_token 失效 | `src/index.ts:423-428` |
| **T18** | **签名类平台：附加头必须在签名之后追加** | 参与 canonical request 会验签失败（实测 `401 APIG.0301`） | `src/codearts-credits.ts:113-133,340-348` |
| **T19** | **字段类型容错**：ID 类字段兼容数字/字符串；业务码兼容 `"9074"`/`9074` | 同一语义字段服务端类型不一致是常态 | `src/codearts-credits.ts:262-279`；`src/trae-credits.ts:121-132` |
| **T20** | **「设备身份每账号确定性派生」** | 规避服务端「每设备每天一次」配额；多账号天然互异，无需持久化随机值 | `src/trae.ts:288-309` |

### 4.2 不建议迁移（或需改造）

| # | 机制 | 为什么不迁移 |
|---|---|---|
| **N1** | **`if (provider === ...)` 的 RPC 分派** | 6 个平台就已经是一串 40 行的 `if`，几十个平台会失控。**应改为注册表 / 插件化 provider**（见 §4.3） |
| **N2** | **能力矩阵硬编码在前端 JS** | 能力集合随平台变化，硬编码在前端意味着「加平台要改前端 + 重新打包」。网关应把能力**随账号条目或 provider 元数据一起下发** |
| **N3** | **`credits.status` 对 3 个平台如实返回 `null`** | 这是「不臆造」的好纪律，但代价是前端拿不到状态、只能靠 claimAll 内部预检。网关可以定义**更通用的状态模型**（`canClaim` / `claimedToday` / `nextResetAt` / `reason`），让无状态端点的平台由预检结果填充 |
| **N4** | **无本地「今天领没领」持久化** | 对本插件（用户手点、单机、低频）没问题；对**网关**是问题：几十个平台 × 几十个账号 × 每天一次，若每次都靠网络预检，请求量与风控风险都会放大。**应持久化「最近一次领取结果 + 日期」并做本地短路** |
| **N5** | **`credits.claimAll` 无并发、无速率控制** | 手动触发时顺序执行是对的；自动调度下需要**平台级串行 + 全局令牌桶**，否则一次全量签到会瞬间打出几十个请求 |
| **N6** | **签到无自动调度** | 本插件是「用户主动、有 UI」的产品形态；网关的核心诉求恰恰是**无人值守自动领取**，必须新增调度层 |
| **N7** | **限流标记只按「账号 × 模型」** | 网关需要的是「账号可用性」维度（是否可发请求），而不是「某模型是否受限」。应扩展为 `(account, scope)` 二元组，scope 可以是 `model:xxx` / `endpoint:checkin` / `account` |
| **N8** | **`sweepExpiredRateLimits` 是死代码** | 定义了但全仓库无调用（`src/account-pool.ts:622-637`）。网关必须有真正的过期清理任务，否则存储会无限增长 |
| **N9** | **`CreditsEndpointDeps` 的 `claim(credential, product, entry)` 与真实签名 `(credential, product, fetcher)` 不一致** | 这个不一致直接导致过 `TypeError: fetcher is not a function` 的真实缺陷。网关的 provider 协议应统一为「依赖注入对象」而非位置参数 |

### 4.3 面向「几十个平台账号池 + 自动领取」的数据结构与调度模型建议

#### 数据结构

```
PlatformProvider（平台元数据，静态配置）
  id                  str    # 'codearts' | 'lobsterai' | ...
  display_name        str
  base_url            str
  auth_kind           enum   # bearer | hmac_sha256 | jwt_header | cookie
  capabilities        { balance: bool, checkin: bool, campaign_claim: bool }
  # ★ 关键：能力放在平台元数据里，随平台注册下发，不硬编码在前端
  checkin_flow        enum   # two_step | three_step | multi_campaign | none
  rate_limit_hints    { business_codes: [...], patterns: [...] }  # 可覆盖默认解析

Account
  id                  str    # f'{platform}-{shortid}'
  platform_id         str
  nickname            str
  credential_ref      str    # 凭据外置，与账号索引分离（沿用 DSH 的做法）
  enabled             bool   # 用户手动开关
  auto_checkin        bool   # ★ 新增：是否参与自动领取
  created_at          ts
  expires_at          ts | None
  refreshable         bool
  # ── 状态字段（均带时间戳，可判定新鲜度）──
  last_claim_at       ts | None
  last_claim_date     str | None   # ★ 本地短路用（'2026-09-22'）
  last_claim_result   enum | None  # claimed / already / inactive / failed
  last_claim_error    str | None
  last_probe_at       ts | None
  consecutive_failures int         # ★ 用于指数退避

RateLimit（独立表，而非塞进 Account 的 JSON 字段）
  account_id          str
  scope               str    # 'model:xxx' | 'endpoint:checkin' | 'account'
  reset_at            ts
  source              enum   # 'server_declared' | 'local_fallback' | 'classified'
  kind                str    # 'hard-credit' | 'soft-rate' | 'quota-exceeded' | ...
  observed_at         ts
  PRIMARY KEY (account_id, scope)      # ★ 天然幂等，便于过期清理与查询

ClaimAttempt（审计流水，可选但强烈建议）
  id, account_id, platform_id, attempted_at, outcome, credit, error_kind, raw_error_snippet
```

**为什么 `RateLimit` 要独立成表**：DSH 把 `modelRateLimits` 塞进账号条目的 JSON 字段，导致每次写入都要「读整个账号列表 → 改一条 → 整体 replace」（`src/account-pool.ts:602-619`）。几十个平台 × 几十个账号时这个模式会频繁整体重写，且并发写容易互相覆盖（DSH 已经踩过：`src/account-pool.ts:127-136` 的注释描述了「多个账号触发限流后一条都没写进去」的真实缺陷）。独立表 + `(account_id, scope)` 主键可以做到单行 upsert。

**为什么 `last_claim_date` 值得持久化**：DSH 完全不记（§2.5），每次靠网络预检。但它是**成本最低、收益最高**的一层短路 —— 同一天内重复触发时直接返回 `already-claimed`，不发任何请求。注意：**只能作为优化，不能作为唯一真相**（服务端才是权威；用户可能手动领过），所以短路后仍应允许「强制重查」开关。

#### 调度模型（分层）

```
┌─ L0 平台级令牌桶（每平台一个）
│    限制对同一平台的并发与速率。风控是按平台算的，不是按账号。
│    例：lobsterai ≤ 1 req/s，codearts ≤ 0.5 req/s
│
├─ L1 账号级串行队列（每账号一个）
│    同一账号的签到/领取/探测请求严格串行 —— DSH 的「顺序执行」纪律（src/jet-hub-rpc.ts:306）
│
├─ L2 每日签到调度器（cron 类）
│    触发时机建议：
│      · 平台重置时间之后的随机窗口内（如重置后 0-60 分钟随机），
│        避免所有账号在同一秒打出请求（DSH 的续期调度用了 0-59 秒随机偏移，
│        见 src/refresh.ts:36-38，是同一个思路）
│      · 若平台未声明重置时间，用「本地时间凌晨 + 随机偏移」兜底
│    每个 (account, platform) 每天最多调度一次（由 last_claim_date 保证）
│
├─ L3 失败重试（指数退避）
│    分类决定策略（复用 DSH 的分类函数思路，见 §3.4）：
│      · already-claimed / inactive  → 不重试，标记完成
│      · soft-rate / not-found       → 短退避（60s × 2^n）
│      · hard-credit / quota-exceeded → 长退避（12h），当天不再尝试
│      · session-dead               → 终态，标记需重新登录，不重试
│      · server / client / 传输失败  → 中等退避
│    ★ 关键：先判更严重的类别（trae-errors.ts:90-98 的教训）
│
├─ L4 账号可用性探测（独立于签到）
│    只在「有活跃限流标记」时触发（对齐 DSH：retest 只测带标记的模型，
│    src/account-probe.ts:204-212）
│    探测必须无副作用：不走轮换逻辑、不写标记（src/account-probe.ts:115-120）
│    探测成功才清标记；失败保留并记录原因
│
└─ L5 凭据续期（与签到完全解耦）
     提前 1 小时触发 + 0-59s 随机偏移（src/refresh.ts:32-40）
     ★ 不按 enabled 过滤（src/index.ts:423-428）
     终态判定用结构化依据（src/refresh.ts:16-25）
```

**自动领取的执行流程**（建议）：

```
for account in accounts.where(auto_checkin=True, enabled=True):
    if account.last_claim_date == today and account.last_claim_result in (claimed, already, inactive):
        continue                                    # L0 本地短路，零网络开销
    if ratelimit.exists(account.id, scope='endpoint:checkin', reset_at > now):
        continue                                    # 平台级冷却中
    with platform_bucket(account.platform_id), account_queue(account.id):
        result = provider.claim(account.credential)  # 内部自带预检
    persist(last_claim_at, last_claim_date, last_claim_result, credit)
    apply_ratelimit_policy(result)                   # 按分类写/不写限流
```

**平台接入的最小抽象**（Python 伪码）：

```python
class PlatformProvider(Protocol):
    id: str
    capabilities: Capabilities          # balance / checkin / campaign_claim

    async def fetch_balance(self, cred) -> Balance | None: ...
    async def fetch_checkin_status(self, cred) -> CheckinStatus | None: ...  # 无独立端点返回 None
    async def claim(self, cred) -> ClaimOutcome: ...                          # 自带预检，幂等
    def classify_error(self, http_status: int, body: str) -> ErrorKind: ...   # 纯函数，可单测
    def records_ratelimit(self, kind: ErrorKind) -> bool: ...                 # 纯函数，可单测
    def should_rotate(self, kind: ErrorKind) -> bool: ...                     # 纯函数，可单测
```

`classify_error` / `records_ratelimit` / `should_rotate` **必须是纯函数且可单测** —— DSH 的 `lobsterai-errors.ts` / `trae-errors.ts` 正是这样组织的，`tests/unit/lobsterai-errors.spec.ts` / `tests/unit/trae-errors.spec.ts` 直接断言分类与顺序。这是把「策略声明」与「实际行为」分开的关键（`src/lobsterai-adapter.ts:934-937` 明确警告：不要内联条件，否则两处分叉、后续维护必然互相误导）。

**必须写进测试的回归项**（都是从 DSH 的真实缺陷里提炼的）：
1. 同一错误体在中文 / 英文两种文案下都必须被识别（`tests/unit/rate-limit-parser.spec.ts:45-61`）
2. 错误分类的顺序不能重排 —— 严重类别必须先判（`src/trae-errors.ts:90-98`）
3. 耗尽后抛出的错误必须带**最后一次**的真实原因（`tests/unit/lobsterai-rotation-exhaustion.spec.ts:42-76`）
4. 单账号凭据损坏不得中断整批（`tests/unit/jet-hub-rpc.spec.ts:228-272`）
5. 余额为 0 与查询失败必须能区分（各 provider 的 `-credits.spec.ts`）
6. 探测不得产生副作用（`tests/unit/account-probe.spec.ts:105-135`）

---

## 5. 未验证 / 存疑

| # | 事项 | 状态 |
|---|---|---|
| U1 | **buddy / workbuddy 的 `checkinHeaders` 是否真的完全不需要 `X-Device-Token`** | 代码注释声称「实测三种请求头组合全部 200，完全不带该头的请求真实领取成功」（`src/credits.ts:15-17`）。我**没有**独立验证该实测结论，只是如实转述代码注释 |
| U2 | **`CODE_ALREADY_CLAIMED_ALT = 1001` / `1002` / `1003` 是否为真实服务端取值** | 代码注释明确写着这是「静态分析列出的备选码表」（`src/credits.ts:58`），**不是实测值**。实测确认的只有 `10001` |
| U3 | **codearts 的 `.com` → `.cn` 域名回退** | IDE 的 `PackageInfoService.getFallbackUrls` 实现了该回退，但本插件**刻意不照搬**，理由是「无法在本机实测」（`src/codearts-credits.ts:74-78`）。该分支的可达性与响应形态**未验证** |
| U4 | **`benefitAmount` 是否同时出现在 claim 响应里** | 代码的取值链把 `benefitAmount` 排在首位，理由是「活动列表用的就是这个字段名，领取响应大概率同源」（`src/codearts-credits.ts:628-632`）—— 这是**推测**，注释里也用了「大概率」。若 claim 响应不含该字段，实际发放积分数会退回活动条目的 `amount` |
| U5 | **trae 的 `traeCheckinDeviceGeneration` 轮换链路** | 代码注释明确说「**保留但不再被调用**，仅为兼容既有账号条目」（`AGENTS.md:965-967`）。但 `src/jet-hub-rpc.ts:1055-1056` 仍在向 `claimTraeDailyCheckin` 传 `generation` 与 `onRotate`，而 `claimTraeDailyCheckin` 内部**不再使用**这两个参数（`src/trae-credits.ts:230-231` 接收后未引用）。这是一处**已废弃但未清理**的残留 |
| U6 | **`qoder` 是否真的完全没有签到能力** | 依据是 `/sash/api/v1/me/campaigns` 在**某一个账号**上返回 `claimable:false`（`src/qoder-credits.ts:33-35`），以及「逆向中未发现签到动作端点」。**其他账号 / 其他时段是否有可领活动，未验证** |
| U7 | **各平台「活动重置时间」是否固定在某个时区/整点** | 全仓库**没有任何**平台声明或推断重置时区的代码。唯一的日期语义是服务端返回的 `end_time` / `cycle_end_time` 字符串，本插件只做展示，不做调度。若网关要做自动调度，**必须自己实测各平台的重置时刻** |
| U8 | **`credits.status` 无前端消费者** | 由 `README.md:476-478` 与全仓库 grep 确认（只有 `jet-hub.js` 调 `claimAll` 与 `balances`）。但**不能排除**外部脚本 / 直接 RPC 调用的存在 |
| U9 | **`sweepExpiredRateLimits` 无调用方** | 全仓库 grep 只命中定义处（`src/account-pool.ts:622`）。我**未发现**任何调用点，但也无法排除通过反射 / 动态分发调用 —— 该文件没有这类机制，故判定为死代码 |
| U10 | **lobsterai / trae 的 `MAX_ROTATE = 3` 在真实多账号池下的实际表现** | 有单测（`tests/unit/lobsterai-rotation-realpool.spec.ts:85-105`）覆盖「A=500 → B=200 应当换到 B」，但那是**替身池**，不是真实多账号。真实风控下的表现未验证 |

---

## 6. 证据附录（`file:line` 清单）

### 6.1 签到 / 领取协议

| 结论 | 证据 |
|---|---|
| buddy 状态/领取/余额端点 | `src/credits.ts:33`、`:35`、`:51` |
| buddy 请求头构造 | `src/credits.ts:180-197` |
| buddy 幂等业务码 10001 | `src/credits.ts:57-61`、`:345-347` |
| buddy 判定顺序 | `src/credits.ts:341-366` |
| buddy 状态响应字段 | `src/credits.ts:310-322` |
| buddy 余额双层嵌套 | `src/credits.ts:436-437`、`:448-456` |
| buddy 周期口径优先 | `src/credits.ts:106-118`、`:402-403`、`:419` |
| buddy 失效包判定 Status=3 | `src/credits.ts:386-393`、`:414` |
| buddy 非 JSON 处理 | `src/credits.ts:236-275`、`:284-291` |
| workbuddy 无签到但有余额 | `src/credits.ts:36-50` |
| codearts 四个端点 | `src/codearts-credits.ts:79`、`:82`、`:84`、`:86`、`:88` |
| codearts 活动类型 USER_LOGIN | `src/codearts-credits.ts:94-100` |
| codearts 已领态集合 | `src/codearts-credits.ts:102-108` |
| codearts 附加头签名后追加 | `src/codearts-credits.ts:113-133`、`:340-348` |
| codearts 账户类型检测 | `src/codearts-credits.ts:45-53`、`:476`、`:577-584` |
| codearts 六步判定顺序 | `src/codearts-credits.ts:551-567`、`:568-645` |
| codearts campaignId 是数字 | `src/codearts-credits.ts:180-188`、`:262-279`、`:490` |
| codearts benefitAmount | `src/codearts-credits.ts:196-204`、`:497` |
| codearts confirm 补发 | `src/codearts-credits.ts:614-626` |
| codearts 双信封兼容 | `src/codearts-credits.ts:289-319` |
| codearts 积分 metric 口径 | `src/codearts-credits.ts:135-150`、`:390-430` |
| lobsterai 三个端点 | `src/lobsterai-credits.ts:36`、`:38`、`:40` |
| lobsterai 槽位固定参数 | `src/lobsterai-credits.ts:42-52`、`:169-174` |
| lobsterai 三步判定顺序 | `src/lobsterai-credits.ts:219-233`、`:234-295` |
| lobsterai 幂等键 | `src/lobsterai-credits.ts:21-27`、`:267` |
| lobsterai 积分三级回退 | `src/lobsterai-credits.ts:278-285` |
| lobsterai 余额端点选择理由 | `src/lobsterai-credits.ts:297-305` |
| lobsterai 负数 clamp / 空值判定 | `src/lobsterai-credits.ts:350-360` |
| lobsterai 纯 Bearer 四头 | `src/lobsterai.ts:415-432` |
| lobsterai clientVersion 解析与缓存 | `src/lobsterai.ts:547-604`、`src/lobsterai-product.ts:98` |
| qoder 余额端点 | `src/qoder-credits.ts:42-43` |
| qoder 无需 WASM 签名 | `src/qoder-credits.ts:6-8` |
| qoder addOnQuota 坑 | `src/qoder-credits.ts:27-29`、`:157-172` |
| qoder enterprise 返回 null | `src/qoder-credits.ts:108-111`、`:149-150` |
| qoder 无签到及理由 | `src/qoder-credits.ts:31-36` |
| trae 三个端点 | `src/trae.ts:59`、`:61`、`:63` |
| trae 完整客户端头 | `src/trae.ts:238-286` |
| trae 设备身份派生 | `src/trae.ts:288-309` |
| trae 状态字段解析 | `src/trae-credits.ts:186-209` |
| trae claim body `{}` | `src/trae-credits.ts:240` |
| trae 业务码兼容字符串 | `src/trae-credits.ts:121-132` |
| trae 9074 处理 | `src/trae-credits.ts:102-107`、`:265-276` |
| trae claim 无积分数→补查 status | `src/trae-credits.ts:280-296` |
| trae 网络重试 vs 业务失败 | `src/trae-credits.ts:236-255` |
| trae 签到错误分类表 | `src/trae-credits.ts:53-100` |
| trae 余额 body 必须带 require_usage | `src/trae-credits.ts:316-327` |
| trae 余额计算 | `src/trae-credits.ts:330-368` |

### 6.2 通用抽象与调度

| 结论 | 证据 |
|---|---|
| `ClaimOutcome` 判别联合 | `src/credits.ts:89-94` |
| `CheckinStatus` | `src/credits.ts:63-87` |
| `CreditBalance` / `CreditPackage` | `src/credits.ts:96-167` |
| `roundCredits` 复用 | `src/credits.ts:478-490` |
| 无统一接口、刻意分开 | `src/lobsterai-credits.ts:3-7`、`src/codearts-credits.ts:4-15` |
| `CreditsEndpointDeps` 泛型化 | `src/jet-hub-rpc.ts:205-277` |
| `collectCreditsStatus` | `src/jet-hub-rpc.ts:279-323` |
| `collectClaimResults` | `src/jet-hub-rpc.ts:325-406` |
| `collectCreditBalances` | `src/jet-hub-rpc.ts:408-472` |
| `computeClaimSummary` 穷尽性检查 | `src/jet-hub-rpc.ts:166-203` |
| `precheckStatus` 语义 | `src/jet-hub-rpc.ts:248-259`、`:366-393` |
| `fetcher` 注入的真实缺陷 | `src/jet-hub-rpc.ts:260-276`、`AGENTS.md:1115-1143` |
| RPC `credits.status` 分派 | `src/jet-hub-rpc.ts:939-1004` |
| RPC `credits.claimAll` 分派 | `src/jet-hub-rpc.ts:1006-1071` |
| RPC `credits.balances` 分派 | `src/jet-hub-rpc.ts:1073-1173` |
| TRAE 必须开预检 | `src/jet-hub-rpc.ts:1040-1049` |
| 前端只调 claimAll | `plugin-src/client/jet-hub.js:646-651` |
| 签到无定时任务 | `docs/lobsterai-integration-plan.md:1301` |
| 自动签到的建议（未实现） | `docs/lobsterai-integration-plan.md:1303-1317` |
| 参考实现有定时签到 | `docs/lobsterai-integration-plan.md:180`、`:199` |
| 30 分钟续期定时器 | `src/index.ts:398`、`:427-442` |
| 续期不看 enabled | `src/index.ts:423-428` |
| 模型列表 2 小时刷新 | `src/models.ts:24`、`src/service.ts:348-360` |
| RPC 注册方式 | `plugin-src/management-rpc.mjs:24-30` |
| 能力矩阵 | `plugin-src/client/credits-capabilities.js:54-65` |
| 能力查询函数 | `plugin-src/client/credits-capabilities.js:73-84` |
| 门控在发请求之前 | `plugin-src/client/jet-hub.js:569-571`、`:584-585`、`:646-647` |
| 能力默认关闭 | `plugin-src/client/credits-capabilities.js:48-50` |
| 能力矩阵设计要点 | `AGENTS.md:1228-1254` |

### 6.3 持久化与账号池

| 结论 | 证据 |
|---|---|
| settings namespace `jet-hub` | `src/account-pool.ts:18-19` |
| schema（必须 schemastery） | `src/account-pool.ts:49-75` |
| 进程内权威副本及理由 | `src/account-pool.ts:127-143`、`:159-182` |
| 整体 replace 必须携带全字段 | `src/account-pool.ts:184-198`、`:242-252` |
| `ProviderAccountEntry` 字段 | `src/types.ts:41-75` |
| `getAvailableAccount` 过滤与顺序 | `src/account-pool.ts:510-592` |
| 手动顺序 = 选号优先级 | `src/account-pool.ts:548-557`、`README.md:510-521` |
| `updateModelRateLimit` | `src/account-pool.ts:594-619` |
| `clearModelRateLimits` | `src/account-pool.ts:471-508` |
| `sweepExpiredRateLimits`（无调用方） | `src/account-pool.ts:621-637` |
| `reorderAccounts` 校验 | `src/account-pool.ts:343-406` |
| `pruneAccountsWithForeignDomain` | `src/account-pool.ts:276-311` |
| `resolveCredentialForAccount` 不查 enabled | `src/account-pool.ts:453-469` |
| 凭据与账号索引分离 | `src/account-pool.ts:114-115`、`:313-317` |
| TRAE 设备代次读写 | `src/account-pool.ts:639-671` |

### 6.4 限流解析 / 探活 / 轮换

| 结论 | 证据 |
|---|---|
| 限流业务码 6004 | `src/llm-adapter.ts:1451-1457` |
| 中英双语正则 | `src/llm-adapter.ts:1459-1476` |
| 结构化判定只认顶层 code | `src/llm-adapter.ts:1478-1494` |
| `isRateLimited` | `src/llm-adapter.ts:1496-1499` |
| 重置时间正则捕获时区 | `src/llm-adapter.ts:1501-1510` |
| `parseRateLimitError` 与 fallback | `src/llm-adapter.ts:1512-1537` |
| 限流解析测试契约 | `tests/unit/rate-limit-parser.spec.ts:23-102` |
| 错误码归一化 | `src/llm-adapter.ts:384-392` |
| 探活模块设计意图 | `src/account-probe.ts:1-30` |
| 探测提示语与超时 | `src/account-probe.ts:50-61` |
| 限流失败判定 | `src/account-probe.ts:88-103` |
| 探测无副作用（不传 pool） | `src/account-probe.ts:105-154`、`:115-120` |
| `retestAccount` 只清实测通过项 | `src/account-probe.ts:190-226` |
| `retestAllAccounts` 顺序执行 | `src/account-probe.ts:228-248` |
| `resetAccount` / `resetAllAccounts` | `src/account-probe.ts:250-272` |
| 探活 RPC 分派 | `src/jet-hub-rpc.ts:920-937` |
| 探活适配器选择测试 | `tests/unit/account-probe-adapter.spec.ts:68-87` |
| 探活行为测试 | `tests/unit/account-probe.spec.ts:73-208` |
| buddy 轮换 | `src/buddy-adapter.ts:1042-1074` |
| codearts 轮换 | `src/llm-adapter.ts:978-1003` |
| lobsterai 轮换与上限 | `src/lobsterai-adapter.ts:82-90`、`:934-1003` |
| trae 轮换与上限 | `src/trae-adapter.ts:133`、`:917-947` |
| `tried` 必须传池 | `src/account-pool.ts:510-531`、`src/lobsterai-adapter.ts:973-976` |
| 耗尽错误带最后一次原因 | `tests/unit/lobsterai-rotation-exhaustion.spec.ts:41-76` |
| 耗尽不二次消费响应体 | `tests/unit/lobsterai-rotation-exhaustion.spec.ts:78-111` |
| 非限流错误也换号 | `tests/unit/lobsterai-rotation-realpool.spec.ts:85-105` |
| lobsterai 错误分类 | `src/lobsterai-errors.ts:28-171` |
| trae 错误分类 | `src/trae-errors.ts:23-157` |
| trae 分类顺序（4008 先于 4011） | `src/trae-errors.ts:90-98`、`AGENTS.md:898-902` |
| 「只移植分类不移植冷却」 | `src/lobsterai-errors.ts:7-19`、`src/trae-errors.ts:7-12` |
| 续期常量与随机偏移 | `src/refresh.ts:1-40` |
| `RefreshScheduler` generation 机制 | `src/refresh.ts:42-114` |
| 终态结构化判定 | `src/refresh.ts:14-25` |

### 6.5 项目内文档（本次考古引用）

| 文档 | 引用点 |
|---|---|
| `AGENTS.md` | `:73`（qoder 无签到）、`:898-902`（分类顺序）、`:904-912`（续期终态）、`:914-967`（TRAE 签到全节）、`:1113-1226`（积分领取全节）、`:1228-1254`（能力矩阵）、`:1256-1260`（X-Domain 跟随产品） |
| `README.md` | `:465-479`（面板与 RPC）、`:481-508`（两步式登录）、`:510-521`（拖拽排序语义）、`:610`（能力门控历史缺陷） |
| `docs/lobsterai-integration-plan.md` | `:22`（协议三问）、`:180,199`（参考实现定时任务）、`:1044-1100`（签到协议与 sigin.py 对照）、`:1103-1110`（协议差异表）、`:1280-1317`（调度方案与「签到无定时任务」）、`:1476-1482`（签到端点表） |
| `docs/trae-integration-plan.md` | `:127-137`（错误码表）、`:138-148`（签到协议）、`:150-159`（余额协议） |
| `docs/lobsterai-review-findings.md` | `:26-180`（S1-S4 严重缺陷，含换号错配与限流徽章写错账号） |
