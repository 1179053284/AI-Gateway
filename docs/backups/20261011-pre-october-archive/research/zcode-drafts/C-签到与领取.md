# C · 签到与领取（R5）

> 调研对象：`zcode-switch` / `zcode-proxy` / `zcode2api` / `zcode-account-switcher`（全程只读）
> 证据分级：`【一手】`= 直接读到的代码（附 `文件:行号`）；`【推断】`= 未经代码证实；`【未验证】`= 卡住没证实

## 修订记录（据独立核验 `verify-CDE.md` 逐条修正）

| 原表述 | 修正后 | 类型 |
|---|---|---|
| 激活事件体「固定 **14** 字段」 | **16 字段**（`claim.rs:158-177` 逐键枚举：+`event_extra_detail`、+`mac_id`、+`marketing_params` 等） | **施工级数字错误（严重）** |
| 「`code!=0` 即中止报错」 | **Rust** `code != 0`（`claim.rs:210`）；**Go** `code != 0 && code != -1`（`activity.go:368`），`-1` 是"响应非 JSON"兜底码，**不中止** | 未标注实现差异 |
| 请求头「10 个」（称来自 `zai_billing_headers_with_mid`） | **13 个**，补 `HTTP-Referer`、`X-Title: Z Code@electron`、`X-Os-Version`；函数名应为 `zai_headers_with_version`（`quota.rs:180-201`，被 `zai_billing_headers_with_mid` 包装于 `:166-172`） | 清单不全 + 函数名不精确 |

---

## ① 结论先行

1. **ZCode 没有传统意义的「每日签到」端点。** 全仓 grep `签到/checkin/sign_in/reward/gift/兑换` 无任何命中（除 UI 文案与 tier 关键词）。所谓「签到」在 ZCode 里由**两件事合成**：`billing/claim` 领取活动套餐（`period=daily` 即每日额度）+ `event/report` 上报 `app_daily_active` 触发服务端授予。【一手】`activity.go:19-21`、`claim.rs:130-131`
2. **领取是「预览 → 验证码 → 提交」三段式**，且**强制阿里云无痕验证码**，无 `X-Aliyun-Captcha-Verify-Param` 直接拒。【一手】`claim.rs:281-283`、`activity.go:226-230`
3. **幂等靠业务码**：`1003`=已领取过、`1005`=今日名额已用完（回带下次可领时间）。无幂等键、无去重令牌。【一手】`activity.go:65-74`、`claim.rs:69-82`
4. **批量领取有完整实现**：`zcode-proxy` 用 5 段 cron 调度器 + 账号间随机延迟；`zcode-switch` 用前端顺序循环 + 每号独立虚拟设备号。二者都做了**账号级互斥**与**逐账号失败隔离**。【一手】`scheduler.go:14-17`、`activity.go:405-412`、`main.js:327-357`
5. **设备号与签到强相关但无轮换**：`zcode-switch` 给**每个账号派生独立 `virtual_device_mid`**（UUID v4，生成一次后永久固化）；`zcode-proxy` 从本机 telemetry 读取，OAuth 新账号会**共用同一 mid**（潜在风控点）。【一手】`store.rs:1015-1047`、`oauth.go:282`

---

## ② 领取类动作全表

| 动作 | 端点 | 方法 | 幂等/重复判据 | 证据 |
|---|---|---|---|---|
| 活动预览（检测可领） | `https://zcode.z.ai/api/v1/zcode-plan/billing/preview?app_version=&platform=` | GET | 无副作用，返回 `data.plans[]` | `claim.rs:9,225-229`；`activity.go:97` |
| 活动领取 | `https://zcode.z.ai/api/v1/zcode-plan/billing/claim` | POST `{"plan_id":...}` | `1003`=已领过；`1005`=今日名额用完 | `claim.rs:10,286-295`；`activity.go:238` |
| 激活事件上报（≈每日签到语义） | `https://zcode.z.ai/api/v1/event/report` | POST，两条事件 `app_launch` + `app_daily_active` | 事件 `event_id`=新 UUID，服务端按 user+日去重 | `claim.rs:130-131,187-215`；`activity.go:329` |
| 验证码配置 | `https://zcode.z.ai/api/v1/client/configs?version=&os=` | GET | 缓存 10 min | `claim.rs:11,315-337`；`captcha.go:284` |
| 配额重置·查状态 | `https://zcode.z.ai/api/v1/coding-plan/reset/status` | GET | 无副作用 | `reset.go:23,109-129` |
| 配额重置·执行 | `.../coding-plan/reset/use` | POST `{idempotency_key, reset_type}` | **有 `idempotency_key`（UUID）** | `reset.go:132-152` |
| 配额重置·申请机会 | `.../coding-plan/reset/opportunity` | POST `{idempotency_key}` | `3301`=机会授予；HTTP 429=限流 | `reset.go:155-181` |

> **兑换码 / 礼包**：无独立端点。礼包以「活动 plan」形式经 preview/claim 出现，tier 关键词含 `gift/promo/activity/体验` → 归类「体验」。【一手】`quota.go:622-626`、`quota.rs:1122-1126`

---

## ③ 签到流程详解

### 3.1 领取（claim）完整链路

```
GET  billing/preview      → data.plans[]（按 priority 降序取 [0]）
GET  client/configs       → data.configs.captcha{enabled,region,prefix,sceneId}
  ↓ 浏览器求解阿里云无痕 → param
POST billing/claim        → body {"plan_id"} + 验证码头
  ↓ code==0 → 成功；2s 后异步刷新额度
```

- **请求头**（函数 `zai_headers_with_version`，`quota.rs:180-201`；由 `zai_billing_headers_with_mid` 在 `quota.rs:166-172` 包装）：**共 13 个** —— `User-Agent: ZCode/<ver>`、`HTTP-Referer`、`X-Title: Z Code@electron`、`X-ZCode-App-Version`、`X-Platform`、`X-Release-Channel: stable`、`X-Client-Language: zh-CN`、`X-Client-Timezone`、`X-Os-Category`、**`X-Os-Version`**（有值才加）、`X-Device-Mid`（有值才加）、`Authorization: Bearer <token>`、`x-request-id: <uuid4>`。【一手】
- **验证码头**：`X-Aliyun-Captcha-Verify-Param`（必填）+ `X-Aliyun-Captcha-Verify-Region`（可选）。【一手】`claim.rs:290-293`、`activity.go:251-254`
- **凭据选择**：优先解密 `zcodejwttoken`（长度 >20 才算有效），否则退 `zai_billing_token`（start-plan 的 apiKey）。【一手】`claim.rs:101-113`、`quota.rs:494-521`
- **请求体**：仅 `{"plan_id": "<plan_id>"}`。【一手】`claim.rs:295`、`activity.go:238`
- **成功响应**：`data.plan{user_plan_id, plan_id, status, starts_at, ends_at}` + `data.server_time`（**秒**，各消费方 ×1000 转毫秒）。【一手】`activity.go:281-298`、`lib.rs:303-311`
- **preview 响应字段**：`data.plans[].{plan_id, name, description, priority, entitlements[]}`；`entitlements[]` 只保留 `meter=model_usage && unit_type=token && show_name非空` 的项，取 `grant_units/period/priority/capabilities/effective_at`。【一手】`activity.go:150-182`、`claim.rs:356-375`

### 3.2 业务错误码（幂等判定的唯一依据）

| code | 含义 | 证据 |
|---|---|---|
| 0 | 成功 | `activity.go:278`、`claim.rs:309` |
| 1001 | 套餐不存在 | `activity.go:66` |
| 1002 | 活动已结束或套餐暂不可领取 | `activity.go:67` |
| **1003** | **该套餐已经领取过** | `activity.go:67` |
| 1004 | 不符合领取条件 | `activity.go:68` |
| **1005** | **今日领取名额已用完**，回带 `data.plan.ends_at` 作 `next_at` | `activity.go:69,305-313`；`claim.rs:70-76` |
| 3001 | 领取参数错误 | `activity.go:71` |
| 3007 | 验证码校验失败 | `activity.go:72` |
| 401 | 未登录/凭证失效 | `activity.go:73` |

> `1005` 是**限流式幂等**：不是「今天签过了」，而是「今天的名额被抢完」，所以 `next_at` 指向**当前 plan 的 ends_at**（下次窗口开放），调度器据此设冷却。【一手】`claim.rs:70-76`、`main.js:453`

### 3.3 激活（≈每日签到）链路

- 事件体**固定 16 字段**：`event_id`(uuid4)、`client_timezone`、`client_language`、`element_name`、`event_region:"app"`、`event_type:"view"`、`event_text:""`、`event_extra_detail:{}`、`user_id`、`screen_resolution:"2560x1440"`、`app_version`、`device_os_category`、`device_os_version`、`device_mid`、`mac_id:""`、`marketing_params:"{}"`。【一手】`claim.rs:158-177`（`activation_event_body`，16 键）、`activity.go:330-347`。
  ⚠️ `device_os_version` 在非 Windows 下为空串 → 【一手】`client.go:107-110`
- `element_name` 取 `app_launch` / `app_daily_active` 两条，顺序上报。**`code` 判定两实现不同**：Rust 为 `code != 0` 即中止（`claim.rs:210`）；**Go 为 `code != 0 && code != -1`**（`activity.go:368`）——`-1` 是"响应非 JSON"的兜底码，**Go 侧不中止**。【一手】`claim.rs:131,192-213`
- `user_id` 取自 `oauth:<provider>:user_info` 的 `id`/`user_id`，兜底解 JWT payload。【一手】`claim.rs:135-156`、`activity.go:379-400`
- 上报后 **sleep 1.5s** 再查额度确认套餐生效（`PlanTier` 非空即算成功）。【一手】`activity.go:509-524`

---

## ④ 批量领取与结果分类

### 4.1 zcode-proxy：cron 调度器（后端主力实现）

- **调度**：`time.NewTicker(1 * time.Minute)`，每分钟扫 `ListClaimPlans()`。【一手】`scheduler.go:71-85,127-151`
- **cron 解析**：自研 5 段（分 时 日 月 周），支持 `*`、`*/n`、`a,b`、`a-b`、`a-b/n`；`ValidateCronExpr` 校验；`NextRunTime` 供前端展示。【一手】`scheduler.go:307-491`
- **任务类型**：`detect`（只检测）/ `claim`（一键领取）/ `activate` / `reset`。【一手】`scheduler.go:15,291-302`
- **目标解析**：`all_accounts` | `single_account` | `group`；`filterRunnable` 过滤掉未启用、`invalid/disabled`、无 JWT 且无 APIKey 的账号。【一手】`scheduler.go:249-288`
- **双层互斥**：plan 级 `TryLock`（拿不到直接跳过，不排队）+ 账号级 `claimLockFor`（防 UI 与 cron 并发双领）。【一手】`scheduler.go:168-173`、`activity.go:405-423`
- **分钟级去重**：`executePlan` 开始即写 `last_run_at`，同分钟重复触发直接 `continue`。【一手】`scheduler.go:141-148,175-176`
- **防风控节流**：账号间隔 `delay_seconds + rand.Intn(delay_seconds/2+1)`（0~50% 抖动）。【一手】`scheduler.go:205-211`
- **失败隔离**：`for` 循环内逐账号执行，**单账号失败不中断**，仅计入 `failCount`。【一手】`scheduler.go:204-227`
- **结果分类汇总**：
  - 状态：`successCount == 0 → "failed"`，否则 `"success"`。【一手】`scheduler.go:229-232`
  - 汇总串：`"N/M 成功: name: msg; name: msg; ..."`，截断 900 字符。【一手】`scheduler.go:233-236`
  - 落两条记录：`UpdateClaimPlanRun`（计划最新态）+ `InsertPlanRunRecord`（历史，含 total/success/fail/duration_ms）。【一手】`scheduler.go:238-244`
  - 实时进度 `PlanRunState{Total,Done,Success,Fail,CurrentAccount}` 供前端轮询。【一手】`scheduler.go:20-30,196-226`
- **空跑不算失败**：`len(plans)==0` 时 `record.Success=true`、`Message="当前无可领取活动"`，避免调度统计 0/N 误报 failed。【一手】`activity.go:434-440,482-487`

### 4.2 zcode-switch：前端顺序 + 自动轮询

- `claimAll`：只挑「有可领 plan」的账号，顺序 `await claim_start` → `waitForClaimResult(id, 120000)`，账号间 **1.2s** 间隔；超时则 `claim_cancel`；单个抛错 `continue`。【一手】`main.js:327-357`
- `autoClaimTick`（每 **10 分钟**一次，`setInterval`）：每号**单轮最多 5 次尝试**（`AUTO_CLAIM_PER_ACCOUNT_CAP`），成功后刷新预览再试，账号间 **5s** 间隔。【一手】`main.js:19-24,459-529,984`
- **冷却分类**：`code==1005 && nextAt` → 用 `nextAt`；`code>=1000` 或 `"interactive"`（需人工验证码）→ 冷却 1 小时；其余 → `AUTO_CLAIM_INTERVAL_MS`(10 min)。【一手】`main.js:451-457`
- CLI 批量预览：`claim-preview` 遍历全部账号（可 `--id` 过滤），逐号 `ensure_virtual_device_mid` + `preview_plans`，返回 `{anyClaimable, accounts[]}`，**单号失败写 error 字段不影响其他号**。【一手】`cli.rs:161-192`

---

## ⑤ 设备 ID 与签到的关系

- **存在「一号一设备」的强诉求，实现方式是虚拟设备号**：`zcode-switch` 的 `Account.virtual_device_mid` 字段，`ensure_virtual_device_mid` 保证非空，空则 `Uuid::new_v4()` 生成并**立即持久化**。【一手】`store.rs:89,1015-1047`
- **首次绑定时「抢注」本机 mid**：`adopt_virtual_device_mid` 先读本机 `telemetry-state.json` 的 `deviceMid`，**若已被其他账号占用则改发新 UUID**——这正是「同一设备不能给多账号用」的规避手法。【一手】`store.rs:1064-1085`
- **无轮换 / 无派生**：`virtual_device_mid` 生成一次后永不重建（只有为空才生成），全仓无 rotate/derive 逻辑。切换账号时会把该账号的 mid 写回本机 telemetry（`write_live_device_mid`）。【一手】`store.rs:1049-1062`；【推断】服务端可能按 mid 聚合「设备维度」限制
- **zcode-proxy 的差异（风险点）**：导入本地账号时 mid 直接读本机 telemetry（多账号可能同值）；OAuth 新账号硬编码 `DeviceMid: LocalDeviceMid()`，**必然与本机同值**。DB 用 `COALESCE(NULLIF(excluded.device_mid,''), accounts.device_mid)` 保证重导入不覆盖。【一手】`account_manager.go:113-122,165`、`oauth.go:282`、`database.go:30`、`database_accounts.go:32`
- mid 通过 `X-Device-Mid` 头传递；为空时才回退读本机 telemetry。【一手】`client.go:199-204,246-247`

---

## ⑥ 活动与额度查询

### 6.1 活动类型与状态

- 类型 = preview 返回的 `ActivityPlan`：`{plan_id, name, description, priority, grants[], grant_items[]}`。【一手】`activity.go:34-41`
- `grant_items[].period ∈ {one_time, daily, weekly, monthly}`，中文映射「一次性/每日/每周/每月」。**`daily` 即「每日可领」的签到型额度**。【一手】`activity.go:27,186-196`、`claim.rs:379-384`
- 状态查询 = 调 preview：`code==0` 且有 `data.plans` 即「有可领活动」；`plans` 为空 = 无可领；`data` 缺失返回 nil。【一手】`activity.go:108-114`、`claim.rs:258-266`
- 排序：`priority` 降序，同优先级按 `plan_id` 升序，取 `[0]` 提交。【一手】`activity.go:126-131`、`claim.rs:268`

### 6.2 额度查询双通道

| 通道 | 端点 | 证据 |
|---|---|---|
| JWT | `zcode.z.ai/api/v1/zcode-plan/billing/current?app_version=` → 失败退 `/billing/balance` | `quota.go:22,220-264`；`quota.rs:22,425` |
| APIKey | `api.z.ai/api/monitor/usage/quota/limit` + `api.z.ai/api/biz/subscription/list` | `quota.go:23-24,267-295` |
| APIKey（zcode-switch 版） | `open.bigmodel.cn/api/monitor/usage/quota/limit` + `open.bigmodel.cn/api/biz/subscription/list` | `quota.rs:20-21` |

> ⚠️ 两个参考项目对 APIKey 通道用的**主机不同**（`api.z.ai` vs `open.bigmodel.cn`），需实测确认哪个现行有效。【未验证】

- **归一化**：解包 `data/result`（最多 4 层）→ `plans[]` 建槽位、`balances[]` 逐模型切片 → 三值互推（total/used/remaining）→ 按 `plan_id` 归槽 → 槽位求和 → `tier_rank` 选主切片。字段名做多重别名防御（`total_units|total|limit|usage` 等）。【一手】`quota.go:178-192,311-484,634-648`
- **生效验证**：领取成功后 `go func(){ sleep 2s; RefreshAccountQuota }`；激活后 `sleep 1500ms` 后查额度。【一手】`activity.go:463-469,509-517`、`reset.go:231-234`
- 未激活/无资格识别：错误消息含 `不存在coding plan` / `没有资格` → `NotEntitled=true`，不报错。【一手】`quota.go:257-259,281-283`、`quota.rs:490-492`
- 后台周期刷新：`QuotaMonitor._loop` 读 `store.quota_refresh_interval()`，`interval<=0` 视为关闭（仍每 30s 回看设置），并发上限 `Semaphore(8)`。【一手】`quota.py:435-497`

---

## ⑦ 失败处理

| 场景 | 处理 | 证据 |
|---|---|---|
| 网络失败 | 包成 `ClaimError{code:-1}` 或 `ClaimResult{Code:-1}`，不影响其他账号 | `claim.rs:296-306`、`activity.go:257-261` |
| HTTP 429 限流 | 退避重试 `[500,1500,4000]ms`（共 3 次），用尽后返回限流文案 | `quota.rs:338,372-380` |
| 429（reset/opportunity） | 直接返回「重置机会请求被限流」不重试 | `reset.go:163-165` |
| 401/403 HTTP | 置 `AuthFailed=true` 并返回鉴权失败 | `quota.go:226-232,245-247,272-274` |
| 业务码 401 | 单独识别为令牌失效 | `quota.rs:368-369`、`quota.go:230-232` |
| 凭据过期（全部 token 401） | 先 sleep 1.5s 用首个 token 重试一次，仍失败才报「凭证已失效」 | `quota.rs:474-480` |
| JWT 失效但有 APIKey | 自动回退 monitor 通道 | `quota.go:203-207` |
| 验证码求解失败 | 该出口代理维度冷却 60s，期间直接拒绝不重试 | `captcha.go:34,135-138,229-233` |
| 验证码无头失败 | 连续 2 次失败 → 升级有头窗口人工过，成功后回到无头 | `captcha.go:216-223,202-227` |
| 验证码缓存过期 | 45s TTL，之后 300s 宽限期「先用旧值 + 后台刷新」 | `captcha.go:31-33,120-133` |
| 领取响应非 JSON | `unwrap_or(Value::String(resp))` 兜底，code 视为 -1 | `claim.rs:257,307` |
| 上游拒绝验证码 | 调 `InvalidateFor` 失效该代理缓存 | `captcha.go:235-240` |

---

## ⑧ 可复用点清单

| 机制 | 文件:行号 | 我们能不能用 |
|---|---|---|
| 三段式领取（preview→captcha→claim） | `claim.rs:217-313`、`activity.go:224-316` | ✅ 直接照搬；注意 `plan_id` 取 priority 最高 |
| 业务码幂等表（1003/1005 等） | `activity.go:65-74`、`claim.rs:421-442` | ✅ 照抄，`1005.next_at` 是天然冷却依据 |
| `app_daily_active` 激活事件 | `claim.rs:130-177`、`activity.go:318-376` | ✅ 这是最接近「签到」的动作，**字段需 16 项齐全**（`claim.rs:158-177`） |
| 阿里云无痕验证码求解（rod/Playwright） | `captcha.go:87-110,188-227`、`zcode2api/app/captcha.py:70-77` | ⚠️ 可用但重（要本机真 Chrome + 持久 profile），需评估部署成本 |
| 验证码缓存 + 宽限期 + 后台刷新 | `captcha.go:113-170` | ✅ 强烈建议复用，避免每号都开浏览器 |
| cron 5 段调度 + 分钟去重 | `scheduler.go:71-151,307-491` | ✅ 照搬；`NextRunTime` 可直接给前端 |
| 双层互斥（plan + account） | `scheduler.go:168-173`、`activity.go:405-423` | ✅ 必须复用，否则双领 |
| 账号间延迟 + 0~50% 抖动 | `scheduler.go:205-211` | ✅ 防风控关键，照搬 |
| 逐账号失败隔离 + 结果三分类 | `scheduler.go:204-244` | ✅ 照搬；「空跑算成功」的语义要保留 |
| 每账号独立 `virtual_device_mid` | `store.rs:1015-1085` | ✅ 建议采纳（比 zcode-proxy 共用本机 mid 更安全） |
| mid「抢注本机值，占用则新发」 | `store.rs:1078-1081` | ✅ 巧妙的去重手法 |
| 429 退避 `[500,1500,4000]ms` | `quota.rs:338,372-380` | ✅ 照搬 |
| token 全 401 时 sleep 1.5s 重试一次 | `quota.rs:474-480` | ✅ 可复用 |
| 额度双通道 + `NotEntitled` 识别 | `quota.go:197-264`、`quota.rs:490-492` | ✅ 照搬，注意主机差异待验证 |
| `reset/use` 的 `idempotency_key` | `reset.go:132-152` | ✅ 唯一带幂等键的写接口，值得学 |
| 领取后 2s 异步刷新额度 | `activity.go:463-469` | ✅ 照搬（固定延迟够用） |
| `filterRunnable` 账号可执行性过滤 | `scheduler.go:276-288` | ✅ 照搬 |

---

## ⑨ 未解决项

1. **【未验证】APIKey 通道主机到底是 `api.z.ai` 还是 `open.bigmodel.cn`** —— `quota.go:23-24` 与 `quota.rs:20-21` 互相矛盾，需实测。
2. **【未验证】服务端是否真的按 `device_mid` 限制「同设备多账号签到」** —— 代码只体现「刻意让每号 mid 不同」的规避意图，未见任何 403/业务码因 mid 重复而拒绝。`store.rs:1064-1085` 的做法是【推断】而非证实的必要动作。
3. **【未验证】`app_daily_active` 是否每日必报、重复报是否被拒** —— 代码每次调用都发新 `event_id`，无本地日去重，服务端行为未知。`claim.rs:192-213`
4. **【未验证】preview 返回的 `plans[]` 是否可能一次有多个可领** —— 两个项目都只取 `[0]`（priority 最高），未实现「一次领多个 plan」。`activity.go:441`、`main.js:338`
5. **【未验证】验证码是否真的强制** —— 存在 `captcha_mode=off` 直连分支（`captcha.go:114-117`）与 `cc.Enabled=false` 跳过分支（`captcha.go:195-197`），说明上游可能已放宽；需实测。
6. **【推断】zcode2api 未实现任何领取流程** —— 全仓 grep `claim/领取/签到` 仅命中 `captcha`，`admin_api.py` 只有 `/captcha/check`。其定位是「验证码 + 额度」，领取逻辑未落地。【一手】`admin_api.py:41-48`
7. **【未验证】`billing/preview` 是否需要 `X-Device-Mid` 才有正确结果** —— 代码总是带上（`claim.rs:249`），但不带的行为未测。
