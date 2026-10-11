# E — 账号池与额度聚合（R7）+ 池化调度

> 调研对象（**全程只读**）：`zcode-proxy/`（Go，重点）、`zcode2api/`（Python）、`zcode-switcher/`（Rust）、`zcode-account-switcher/`（Node）。
> 证据分级：`【一手】`= 直接读到的代码；`【推断】`= 未经代码证实；`【未验证】`= 卡住未证实。
> 引用格式：`文件:行号`（行号均经 Read 核对）。

## 修订记录（据独立核验 `verify-CDE.md` 逐条修正）

| 原表述 | 修正后 | 类型 |
|---|---|---|
| 命中表称 `proxy.rs`（switcher）「**无任何锁**」 | 实为 `OnceLock<Mutex<Option<ProxyRuntime>>>`（`proxy.rs:5,84`，`:817/845/858/872` `.lock()`）——保护**本地代理服务生命周期**。该行"不用于转发选号 = ❌ 否"的**判定仍正确**，但"无任何锁"这句可被一行 grep 证伪 | 表述与事实相反（严重） |
| 负向断言的检索范围只列 3 棵树，而文档自述调研对象有 4 个项目 | 补检 `zcode-switch/`、`zcode-account-switcher/`、`ZCode-Panel/`：**均无转发选号逻辑**。结论不变，但把"范围缺口"变成"**范围覆盖证据**" | 证据链未闭合 |
| 命中表标题「命中与判定（**全部**）」仅列 7 行 | 补全至 10+ 处（`captcha.go`/`auth.go`/`config.go`/`oauth.go`/`zcode_api.go`/`scheduler.go`/`quota.py`/`store.py`/`database.go`），逐项判定一致。负向断言的价值在**穷尽** | 清单不全 |
| `pool.go:44` 的 `mu`「**只**保护 rotation 游标 map」 | 还保护 **`refreshFn` 注入**（`pool.go:65,117-119,158-160`） | 表述过窄 |

---

## ① 结论先行

1. **两套实现同源**：`zcode-proxy/pool.go` 明确写着"与 zcode2api models.py 一致"（`pool.go:14`），状态机、round-robin 选择、`is_selectable` 判定是同一套逻辑的 Go 移植（`pool.go:167`、`pool.go:192` ↔ `models.py:91-100`、`store.py:242-256`）。
2. **额度聚合目前只是"仪表盘数字"，不是对外能力**：`total_remaining = Σ 各账号 Remaining` 只在管理端 dashboard 返回（`api_handlers.go:122,131,139`）；zcode2api 的 `/status` 只返回**可选中账号数**（`admin_api.py:81-84`）。**对外 `/v1/*` 没有任何额度/积分查询端点**（`main.go:109-114`、`gateway.py:302-449` 逐条确认）。
3. **⭐ 账号选择路径没有并发租约（lease/in-flight）**。全量检索 `lease|reserve|in_flight|inflight|acquire|busy|TryLock|claimLockFor`（范围见 §④），命中项**全部是"领取/重置/计划"级别的互斥，与转发选号无关**。转发选号只做"读状态 → 返回指针"，不占位、不限并发。→ 这是我们要补的最大缺口。
4. **可复用的最有价值三块**：① 6 态账号状态机 + `is_selectable` 判定；② 失败码 → 状态迁移的映射表（401/403/429/402/3012）；③ 加密账号包 `zcb1:`（PBKDF2-120k + AES-256-GCM，跨机迁移）。
5. **额度重置（`reset.go`）是隐藏彩蛋**：Coding Plan 支持"5 小时窗口重置/周重置"把已耗尽的额度**恢复**（`reset.go:15-23,206-211`），聚合池可据此把 exhausted 账号拉回可用。

---

## ② 账号池数据结构

### 存储介质：SQLite（WAL）
- zcode-proxy：`modernc.org/sqlite` 纯 Go 驱动，`SetMaxOpenConns(1)` 单写，`journal_mode=WAL`、`busy_timeout=5000`（`database.go:8,154,158-164`）。
- zcode2api：`sqlite3` + `threading.RLock`，账号对象**常驻内存**（保证轮询游标实时），变更同步落库，启动时回读快照（`store.py:1-8,29,85-104`）。
- zcode-switcher：**JSON 文件**，非 SQLite —— `~/.zcode/account-profiles/proxy-account-pool.json`（`proxy_pool.rs:46-51,77-85`）。

### 账号表字段
**zcode-proxy `accounts` 表**（`database.go:186-224`；Go 结构体见 `database.go:17-57`）：

| 分组 | 字段 |
|---|---|
| 自然键 | `user_id` UNIQUE（JWT `user_id`/`user_info.id`，`database.go:19`） |
| 身份 | `email` `display_name` `provider`(zai\|bigmodel) `auth_type`(jwt\|apikey) `account_group` `remark` |
| 凭证 | `access_token` `refresh_token` `zcode_jwt` `api_key` `user_info` `device_mid`(设备指纹，重导入不覆盖) `creds_raw`(本地快照) |
| 状态 | `status` `enabled` `cooling_until` `last_error` |
| 额度快照 | `quota_json`(完整 QuotaOverview JSON) `plan_tier` `plan_expire` `total_units` `used_units` `remaining` `last_checked_at` |
| 计数 | `use_count` `fail_count` `last_used_at` |
| 活动 | `last_claim_at` `last_claim_plan` `last_claim_msg` |
| 时间 | `created_at` `updated_at` |

索引：`enabled` / `status` / `account_group`（`database.go:222-224`）。

**upsert 语义（重要）**：按 `user_id` 冲突更新，且 `device_mid`/`creds_raw`/凭证用 `COALESCE(NULLIF(excluded.x,''), accounts.x)` —— **新值为空则保留旧值**，避免重导入抹掉设备指纹（`database_accounts.go:13-14,22-38`）。`status` 特判：库内为 `disabled` 时不被覆盖（`database_accounts.go:34`）。

**zcode2api `accounts` 表**：瘦表 `id/provider/name/mode/status/enabled/created_at/data`，`data` 是整条 Account 的 JSON（`store.py:54-66`）。

**zcode-switcher 池条目**：只存引用 `profile_id + enabled + created_at + updated_at`，账号本体在 profile 体系里（`proxy_pool.rs:11-16`）。

---

## ③ 额度聚合

### 单账号额度怎么查（两个通道）
端点常量（`quota.go:21-29`）：
- **JWT 通道**（`zcode_jwt`）：`GET https://zcode.z.ai/api/v1/zcode-plan/billing/current?app_version=...`，失败回落 `/billing/balance`（`quota.go:220-264`）。
- **API Key 通道**（`api_key`）：`GET https://api.z.ai/api/monitor/usage/quota/limit` + `/api/biz/subscription/list`（`quota.go:267-295`）。
- 入口 `FetchQuotaRaw`：JWT 优先，鉴权失败且带 API Key 时回落 monitor（`quota.go:197-213`）。
- 鉴权头 `Authorization: Bearer <billingToken>`，`billingToken` 取 `ZCodeJWT` 否则 `APIKey`（`quota.go:91-96,118-123`）。

归一化产物 `QuotaOverview`：`total/used/remaining/percent_used + items[] + plans[]`，另带 `not_entitled`/`auth_failed`/`is_empty` 三个语义标志（`quota.go:57-71`）。字段别名极其防御（`total_units|total|limit|usage` 等，`quota.go:365-367`），并对三值做互推（`quota.go:374-386`）。

### 多账号怎么汇总
- **单账号内**：`balances[]` 逐条累加 → `totalSum/usedSum/remSum` 作为该账号的总数（`quota.go:355-398,416-424`）；再按 `plan_id` 归入套餐槽位并二次求和（`quota.go:443-478`）。
- **跨账号**：只有一处 —— dashboard 的 `total_remaining += a.Remaining`（`api_handlers.go:122,131,139`），数据源是**库里上次刷新的快照**，非实时拉取。
- zcode2api 的 `/admin/api/status` 返回 `quota_pool` = 每 provider 的**可选中账号数**（`admin_api.py:76-85`），不是额度数字。
- **【一手】不存在对外额度聚合端点**：zcode-proxy 对外仅 `/v1/messages|count_tokens|chat/completions|responses|models`（`main.go:109-114`）；zcode2api 仅 `/v1/models|messages|chat/completions|responses`（`gateway.py:302-449` 逐条列举）。→ R7 的"对外数字"需要我们自己造。

### 额度耗尽自动换号 + 阈值
- 判定：`AllExhausted()` = 所有切片 `remaining <= 0`（`quota.go:713-723`）；无 items 时看顶层 `remaining <= 0`。
- 主动路径：额度刷新后 `applyQuotaResult` → `MarkExhausted`（`zcode_api.go:53-62`）。
- 被动路径：转发遇 402/额度错误 → `MarkExhausted` + 异步刷额度 + `outcomeNextAccount` 换号（`relay.go:309-312`，错误识别 `relay.go:444-458`）。
- **阈值就是 `<= 0`，没有"预留水位"**（例如"低于 10% 就停用"）。【一手】未发现水位阈值配置项（`database.go:328-340` 默认设置清单里无此项）。
- 恢复：额度刷新发现有余量 → `exhausted/inactive/invalid/cooling到期` 全部回 `active`（`zcode_api.go:64-72`）。

---

## ④ 选路算法（含并发租约专项结论）

### 策略
三种，存 `settings.selection_strategy`，默认 `round_robin`（`database.go:332`，常量 `pool.go:32-36`）：
- `random`：`pool[rand.Intn(len(pool))]`（`pool.go:225-226`）
- `best_quota`：按 `Remaining` 降序取最大，未知(0)排后（`pool.go:227-232`）
- `round_robin`（默认）：游标 `rotation["group|provider"]` 取模递增（`pool.go:233-241`）

候选池过滤：`provider` 匹配 → `group` 匹配 → 未被本次请求 skip → `accountSelectable` → 有凭证（`pool.go:199-218`）。
`accountSelectable`：`enabled=false`/`disabled`/`invalid`/`exhausted`/`inactive` 一律不可选；`cooling` 需 `cooling_until<=0 || now>=cooling_until`（`pool.go:169-179`）。
另有 `EffectiveStatus` 做"冷却到期即视为 active"的展示态（`pool.go:182-187`）。

zcode2api 只有 round-robin，无策略开关（`store.py:242-256`）。zcode-switcher 是**有序列表 + 顺序 failover**，无游标（`proxy.rs:325-406` 构建、`proxy.rs:588` `for upstream in upstreams` 消费）。

### ⭐ 并发租约 / in-flight 专项结论

**检索范围（逐文件确认）**：
- `zcode-proxy/*.go` 全部 12 个目标文件 + 其余 Go 文件
- `zcode2api/app/**/*.py`（含 `routes/gateway.py`）
- `zcode-switcher/src-tauri/src/*.rs`
- ✅ **补检（核验时扩展）**：`zcode-switch/src-tauri/src/*.rs`、`zcode-account-switcher/**`、`ZCode-Panel/` —— 三者**均不含转发/选号逻辑**（grep `select|round_robin|rotation|upstream` 零命中），故下述负向结论**对全部项目成立**，而非只对"转发网关"三项目成立。

**检索关键词**：`lease`、`reserve`、`in_flight`、`inflight`、`acquire`、`busy`、`lock`、`mutex`、`TryLock`、`claimLockFor`。

**代表性命中与判定（全部为【一手】）**：

| 命中位置 | 用途 | 是否用于转发选号 |
|---|---|---|
| `activity.go:405-423` `claimLockFor` + `TryLock` | per-account mutex，防"UI 手动 + cron"重复**领取活动** | ❌ 否 |
| `reset.go:185-192` 同 `claimLockFor` | 防重复消耗**重置机会** | ❌ 否 |
| `scheduler.go:44,159,170` per-plan `TryLock` | 防同一计划并发执行 | ❌ 否 |
| `pool.go:44,234-240` `mu sync.Mutex` | 保护 **`rotation` 游标 map** + **`refreshFn` 注入**（`pool.go:65,117-119,158-160`）；临界区仅游标自增 | ❌ 否 |
| `store.py:29` `threading.RLock` | 保护内存账号字典 / 游标读写 | ❌ 否 |
| `captcha.py:116,159` `asyncio.Lock` | 验证码求解串行 | ❌ 否 |
| `proxy.rs:5,84,817…872`（switcher）`OnceLock<Mutex<Option<ProxyRuntime>>>` | 保护**本地代理服务的生命周期** | ❌ 否 |

> **完整命中清单（核验补充，共 10+ 处，逐项判定均与选号无关）**：
> `captcha.go:61,66,78,120,152-168`（`solveSem` 容量 1 信号量 + `mu`）、`auth.go:38,43,108,122,141,187,213,388`（`RWMutex`/`failMu`）、`config.go:32,58`（配置热重载）、`oauth.go:58,100…304`（OAuth 流程）、`zcode_api.go:23-24`（`claimMu`+`claimLocks`）、`scheduler.go:40,43,99,109,119`（`runMu`/`execMu`）、`quota.py:439`（`Semaphore(8)` 额度刷新并发）、`zcode-switcher/oauth.rs:40,122-129,250…`、`captcha.rs:58,258,280`、`store.py:42`/`database.go:162`（SQLite `busy_timeout`）。
> 负向断言的价值在于**穷尽**，故此处补全；**逐项判定结论一致：全部与转发选号无关**。

**结论【一手】**：
1. **转发选号路径 `pool.Select`（`pool.go:192-242`）/ `store.select`（`store.py:242-256`）/ `choose_upstreams`（`proxy.rs:325`）完全没有 in-flight 标记、没有租约、没有"占位/释放"**。选号函数只做"过滤 → 返回 `*Account` 指针"，不写回任何占用状态。
2. 账号状态的更新**只发生在请求失败或成功之后**（`relay.go:254,261,286,302,310,323`），即"事后记账"，不是"事前占位"。
3. 因此**并发请求可以命中同一账号**。round-robin 游标递增（`pool.go:239`）在并发下只能"近似摊开"，无法保证不撞；`random`/`best_quota` 策略下撞号概率更高（`pool.go:225-232` 无任何去重）。若候选池只剩 1 个账号，必然全撞。
4. **没有 per-account 并发上限**（如"单账号最多 N 个 in-flight"）。`use_count` 是累计计数，不是当前并发数（`database_accounts.go:184-191`）。
5. 唯一"事后纠偏"是失败迁移：撞号导致上游 429 时，该账号进 cooling 30s（`relay.go:302`），下一轮请求才会绕开它。

**→ 给 Model-Gateway 的施工含义【推断】**：若要对外做额度聚合 + 高并发，必须自建 `lease/reserve` 层（`acquire(account) -> token` / `release(token)`），并把"额度扣减"从事后快照改成事前预留。参考项目**没有可抄的实现**，只能借鉴其状态机与失败映射。

### 冷却 / 限流重置
- 默认冷却 60s（`pool.go:254-265` 注释"429 多为瞬时 RPM 峰值"）。
- 实际调用点各不相同：连接失败 60s（`relay.go:254`）、3xx WAF 120s（`relay.go:261`）、429 30s（`relay.go:302`）、风控 3012 全通道失败 120s（`relay.go:219-221`）。
- zcode2api 默认 `COOLING_SECONDS=300`（`settings.py:99`），但 429 显式传 60（`gateway.py:1441`），连接失败走默认 300（`gateway.py:1399` + `gateway.py:237`）。
- 冷却到期**自动恢复可选**，无需人工（`pool.go:174-177`）。

---

## ⑤ 账号生命周期

| 操作 | zcode-proxy | zcode2api |
|---|---|---|
| 增（本地导入） | 解密 `~/.zcode/v2/credentials.json` → 取 JWT/access_token/user_info + `config.json` 的 coding-plan apiKey + telemetry 的 `deviceMid`（`account_manager.go:40-50,55-191`） | 粘贴 token 行（`admin_api.py:89-116`） |
| 增（粘贴） | JWT 形状判定 → 解 payload 取 `user_id`；否则 `sha256(provider:secret)[:8]` 当自然键（`account_manager.go:196-235`） | 同（`models.py:24-27,74-85`） |
| 增（OAuth） | 环回回调 + 手动粘贴兜底（`main.go:117`、`api_handlers.go:272-310`） | `loopback`/`manual` 双模式（`admin_api.py:244-318`） |
| 改 | `UpdateAccountFields`（group/remark/enabled），**enabled 联动 status**：`enabled=0 → disabled`、`enabled=1 → active`（`database_accounts.go:139-148`） | `set_enabled` 同语义（`store.py:228-239`） |
| 查 | `ListAccounts`/`GetAccount`/`GetAccountByUserID`（`database_accounts.go:88-130`） | `list_accounts`/`find`/`find_any`（`store.py:166-188`） |
| 删 | `DeleteAccount`（`database_accounts.go:133-136`） | `remove_account`（`store.py:213-221`） |
| 额度刷新 | 手动 `RefreshOne`（`pool.go:157-165`）/ API `POST /api/accounts/{id}/refresh`（`api_handlers.go:312-329`） | `POST /admin/api/accounts/refresh`（支持 all/ids，`admin_api.py:178-188`） |
| **额度重置** | `reset.go` 全套：查状态 → 选 `five_hour` 优先否则 `week` → `POST /reset/use` → 刷额度（`reset.go:183-236`）；状态结构 `ResetStatus`（`reset.go:35-42`） | 无 |
| 一键切回本地 | 快照备份 → `enc:v1` 重加密写回 `credentials.json` → 改 `config.json` → 删 `coding-plan-cache.json` → 可选杀进程（`account_manager.go:274-376`）；撤销用快照还原（`account_manager.go:411-444`） | 无 |
| 导出 | `zcb1:` 加密包，可按 id 子集（`export_bundle.go:44-99`）；导入按 `user_id` upsert（`export_bundle.go:102-153`） | `GET /admin/api/export`，**明文 secret**（`store.py:259-271`） |

状态统计：`CountAccountsByStatus`（`database_accounts.go:240-255`）↔ `stats` 计数（`admin_api.py:64-72`）。

---

## ⑥ 失败切换

**重试上限（两套一致）**：`maxAccountAttempts = 5`、`maxCaptchaRetries = 3`（`relay.go:22-26` ↔ `gateway.py:30-31`）。

**换号循环**：`for attempt < 5 { a = Select(provider, group, tried); if a==nil break; tried[a.ID]=true; ... }`（`relay.go:110-124` ↔ `gateway.py:1285-1296`）。`tried` 是**请求级** skip 集，保证一次请求内不重复选同号。

**状态码映射（`relay.go:284-313`，Python 版 `gateway.py:1434-1449`）**：

| 上游信号 | 动作 | 是否换号 |
|---|---|---|
| 401 / 403 | `MarkInvalid`（凭证失效，需人工） | ✅ 换号 |
| 429 | 请求内退避重试 1 次（尊重 `Retry-After`，上限 5s）→ 仍失败 `MarkCooling(30)` | ✅ 换号 |
| 402 / 余额类文案 | `MarkExhausted` + 异步刷额度 | ✅ 换号 |
| 3012 / `unusual activity`（风控） | **不立即冷却整号**，先试本账号其余路径（api.z.ai 独立服务）；全路径失败才 `MarkCooling(120)` | ✅ 换号 |
| 连接失败 / 3xx WAF | `MarkCooling(60 / 120)` | ✅ 换号 |
| 验证码被拒 | 失效缓存 → 重解 → 带新参数重试本路径；用尽 → 下一条路径（`relay.go:270-282`） | 路径级 |
| 2xx 但非 JSON/SSE（WAF 页） | `MarkCooling(120)`，不算成功（`relay.go:329-336`） | ✅ |
| 其它 4xx/5xx | `MarkFailed` + 按客户端协议回传，**终止**（`relay.go:315-320`） | ❌ 不换号 |

**单账号降级链**：JWT+验证码 → JWT 直连 → API Key 回退（api.z.ai）（`relay.go:151-224`；Python `gateway.py:1310-1367`）。

**全部失败**：503 + `type=no_available_account`；若因冷却导致，附"约 N 秒后自动恢复"（`relay.go:126-145`，`CoolingInfo` 见 `pool.go:302-325`）。

**成功后**：`MarkUsed`（+use_count，冷却/耗尽态回 active，`pool.go:284-292`）+ 30s 节流的额度刷新（`relay.go:701-712`）。

---

## ⑦ 对外接口

**zcode-proxy 对外（`main.go:105-121`）**：
- `POST /v1/messages`（+`/`）、`/v1/messages/count_tokens`、`/v1/chat/completions`、`/v1/responses`、`GET /v1/models`
- `GET /health`、`/web`（内嵌 UI）、`/oauth/callback`（免认证）
- 未知 `/api/*`、`/v1/*` 显式 404（`main.go:154-158`）

**zcode-proxy 管理 API（`api_handlers.go:37-110`，全量清单）**：账号 CRUD/导入/导出/OAuth/refresh/claim/detect/activate/reset/reset-status/switch-back/restore-local、计划 CRUD+run+running、记录（claim/usage/stats）、设置 GET/PUT、代理 CRUD+test+system+probe-ports、验证码 status/invalidate/solve、指纹、模型 list/sync/catalog。

**关键管理动作**：
- 账号脱敏视图（token 任意长度都脱敏）（`api_handlers.go:149-188`）
- 设置白名单：`selection_strategy`/`quota_refresh_interval`/`upstream_proxy`/`fingerprint`/`custom_ja3`/`captcha_mode`/`gateway_models`（`api_handlers.go:661-665`），且服务端校验策略枚举与间隔范围（`api_handlers.go:695-708`）
- 指纹/代理变更 → 关闭上游连接池（`api_handlers.go:726-732`）

**zcode2api 管理 API（`admin_api.py` 全量）**：`/verify`、`/captcha/check`、`/accounts`(GET/POST/DELETE)、`/accounts/{id}`(PUT)、`/accounts/{id}/enabled`、`/accounts/refresh`、`/accounts/{id}/refresh`、`/login/{start,poll,finish}`、`/proxy`(GET/PUT)、`/proxy/test`、`/proxy/subscription`、`/settings`(GET/PUT)、`/export`、`/import`。

**【一手】两套都没有额度聚合对外端点**（无 `/v1/quota`、`/v1/credits`、`/v1/balance` 之类）。

---

## ⑧ 加密与代理

### 凭据加密 `credential_crypto.go`（与 ZCode 客户端逐字节兼容）
- 格式：`enc:v1:` + `b64url(nonce12) + "." + b64url(tag16) + "." + b64url(ciphertext)`（`credential_crypto.go:17-23`）
- 算法：**AES-256-GCM**，密钥 = `SHA-256(secret)`（`credential_crypto.go:61-64,96-110`）
- 密钥来源：环境变量 `ZCODE_CREDENTIAL_SECRET`，否则回退 `zcode-credential-fallback:{平台}:{home}:{用户名}`（`credential_crypto.go:39-59`）
- 兼容细节：Rust aes-gcm 输出 `ct||tag`，Go GCM `Open` 同样期望 `ct||tag`，故直接拼接（`credential_crypto.go:104-106`）
- JWT payload 解码**不验签**（`credential_crypto.go:135-150`）

### 账号包 `export_bundle.go`
- 格式：`zcb1:` + `base64(salt16 || nonce12 || ciphertext)`（`export_bundle.go:16-21`）
- 算法：**PBKDF2-SHA256(password, salt, 120000, 32) → AES-256-GCM**（`export_bundle.go:23,86-95`）
- 包内含 JWT/API Key/device_mid/creds_raw（`export_bundle.go:26-41`）；导入按 `user_id` upsert，跳过无凭证项（`export_bundle.go:135-151`）

### 出口代理 `egress_proxy.go`（**为什么需要代理出口**）
解析优先级：**组绑定代理 → 默认代理 → 全局 `upstream_proxy` 设置 → 直连**（`egress_proxy.go:39-61`，组查找 `database_ops.go:279-302`）。
原因（代码注释 + 逻辑）：
1. **风控按 IP 判定**：验证码求解与上游请求共用代理，"数据中心 IP 会被阿里云风控 F001 拒绝"（`zcode2api/settings.py:134-136`），故需要住宅代理。
2. **多账号需 IP 隔离**：代理按 `account_group` 绑定（`egress_proxy.go:54-59`），同一组账号走同一出口，天然做账号↔IP 关联，降低"多账号同 IP"被识别为批量操作的风险。
3. **健康检查**：`TestProxyExitIP` 打 `api.ipify.org`/`ipinfo.io` 取出口 IP（`egress_proxy.go:74-108`）；`ProbeLocalProxyPorts` 探测 9 个常见本机代理端口（Clash/v2rayN/sing-box 等，`egress_proxy.go:171-223`）。
4. 验证码求解器也复用同一出口（`main.go:78-79` `captchaProxyHook`）。

---

## ⑨ 定时任务

| 任务 | 实现 | 频率 |
|---|---|---|
| **额度刷新循环** | `AccountPool.refreshLoop`（`pool.go:80-98`） | 启动后等 5s，之后每 `quota_refresh_interval` 秒，**默认 60**，显式 `0` = 关闭（`pool.go:100-113`，`database.go:333`）。刷新时并发 4 + 每账号随机延迟 0-2s 防风控（`pool.go:115-154`）；跳过 disabled/invalid/无凭证/冷却中（`pool.go:131-140`） |
| **活动计划调度器** | `CronScheduler`（`scheduler.go:33-45`） | `time.NewTicker(1 * time.Minute)`，每分钟检查（`scheduler.go:71-85`）；5 段 cron（分 时 日 月 周）+ 分钟级去重（`scheduler.go:127-151`，`shouldRun` `scheduler.go:304-317`，`NextRunTime` `scheduler.go:481-491`） |
| 计划任务类型 | `detect` / `claim` / `activate` / `reset`（`scheduler.go:13-17,290-302`） | 按 cron |
| 账号间节流 | `delay_seconds` 固定延迟 + `0~50%` 随机抖动（`scheduler.go:204-211`） | — |
| 计划并发控制 | per-plan `TryLock`，拿不到直接跳过本 tick（不排队）（`scheduler.go:44,159-165,170-173`） | — |
| 配置热重载 | `cfg.StartHotReload(30 * time.Second)`（`main.go:48`） | 30s |
| zcode2api 额度监控 | `QuotaMonitor._loop`（`quota.py:451-497`） | 启动后等 5s，之后每 `quota_refresh_interval` 秒（默认 60，`settings.py:97`）；`refresh_accounts` 并发 8（`quota.py:435-448`） |
| 成功请求后补刷 | `RefreshAccountQuotaThrottled`（`relay.go:701-712`）↔ `_safe_refresh`（`gateway.py:1503-1515`） | 30s 节流 |

启动顺序：`pool.Start()`（`main.go:59`）→ `scheduler.Start()`（`main.go:96`）。

---

## ⑩ 可复用点清单

| 机制 | 文件:行号 | 我们能不能用 |
|---|---|---|
| 6 态账号状态机（+inactive） | `pool.go:22-29` | ✅ 直接照搬，字段名可复用 |
| `is_selectable` 判定（含冷却到期） | `pool.go:169-179` | ✅ 直接照搬 |
| round-robin 游标 `rotation[group\|provider]` | `pool.go:44,233-241` | ✅ 照搬；但需补 lease |
| 三种选路策略 + 设置开关 | `pool.go:32-36,223-241` | ✅ 照搬枚举与默认值 |
| **并发租约 / in-flight 占位** | — **不存在**（§④ 已检索确认） | ❌ 需自研，参考项目无实现 |
| 额度三值互推 + 字段别名防御 | `quota.go:359-386` | ✅ 高价值，直接照搬 |
| `balances[]` 逐条求和 → 单账号总额 | `quota.go:355-398,416-424` | ✅ 聚合基础，照搬 |
| 跨账号 `total_remaining` 求和 | `api_handlers.go:122,131,139` | ✅ 仅展示；要对外需加端点 |
| 失败码 → 状态迁移映射表 | `relay.go:284-313`、`gateway.py:1434-1449` | ✅ 照搬（含 3012 风控特判） |
| 请求级 `tried` skip 集 + 最多 5 次换号 | `relay.go:110-124`、`gateway.py:1285-1296` | ✅ 照搬 |
| 429 尊重 `Retry-After` + 请求内退避 | `relay.go:288-303` | ✅ 照搬 |
| 冷却默认 60s / 风控 120s / 429 30s | `pool.go:254-265`、`relay.go:302,261,220` | ✅ 阈值可直接用 |
| 额度重置（five_hour/week 拉回 exhausted） | `reset.go:15-23,183-236` | ✅ 高价值，聚合池可用它"续命" |
| 单账号降级链（JWT+验证码→JWT→API Key） | `relay.go:151-224` | ⚠️ 依赖验证码服务，按需 |
| 账号级互斥 `claimLockFor` + `TryLock` | `activity.go:405-423`、`reset.go:185-192` | ✅ 可借鉴为 lease 的雏形（per-account mutex） |
| 计划级互斥 + 分钟级去重 | `scheduler.go:44,127-151,170-173` | ✅ 照搬 |
| 账号间随机延迟防风控（并发4 + 0-2s） | `pool.go:115-154` | ✅ 照搬 |
| `upsert` COALESCE 保留 device_mid/creds | `database_accounts.go:13-14,22-38` | ✅ 照搬（防重导入抹指纹） |
| `enc:v1` AES-256-GCM 凭据加密 | `credential_crypto.go:17-23,61-64` | ⚠️ 仅当要与 ZCode 客户端互操作时 |
| `zcb1:` PBKDF2-120k 加密账号包 | `export_bundle.go:16-23,44-99` | ✅ 跨机迁移照搬 |
| 出口代理按组绑定 + 出口 IP 健康检查 | `egress_proxy.go:39-61,74-108` | ✅ 多账号 IP 隔离必备 |
| 5 段 cron 解析器（自研，无依赖） | `scheduler.go:304-491` | ✅ 可直接移植 |
| 额度快照落库（quota_json + 三数字列） | `database_accounts.go:174-181` | ✅ 照搬 |
| 管理端脱敏视图（token 全长度脱敏） | `api_handlers.go:149-158` | ✅ 照搬 |
| 设置白名单 + 服务端枚举校验 | `api_handlers.go:661-665,695-708` | ✅ 照搬 |
| 额度耗尽 `<=0` 判定（无预留水位） | `quota.go:713-723` | ⚠️ 建议我们加水位阈值 |
| zcode2api 明文导出 secret | `store.py:259-271` | ❌ 反面教材，勿学 |

---

## ⑪ 未解决项

1. **【未验证】多账号并发压测数据**：参考项目未提供"并发下同账号撞号率"的实测。§④ 的撞号风险是代码结构推断，未跑压测证实。
2. **【未验证】zcode-proxy 是否存在未纳入检索的并发控制**：检索覆盖 `*.go` 关键词命中，但未做 AST 级调用图分析；理论上存在通过 channel 实现的隐式串行（未发现）。
3. **【未验证】`quota.go` 各字段的真实上游语义**：`total_units` 在 Coding Plan 下是"次数"还是"token"未证实（`unitLabel` 对 API Key 通道映射为"每 N 小时/每天/每月"，`quota.go:579-594`，但 JWT 通道的 `unit_type` 语义未确认）。
4. **【未验证】跨 provider（zai + bigmodel）额度是否可加总**：`total_remaining` 直接对全部账号求和（`api_handlers.go:131`），但 zai 与 bigmodel 的额度单位是否同质、能否相加，代码未做单位归一。
5. **【推断】`best_quota` 策略依赖的 `Remaining` 是快照值**：`pool.go:229-231` 读的是 `Account.Remaining`（上次刷新落库值，`database_accounts.go:174-181`），在刷新间隔内会失真；未找到"选号前实时刷新"的逻辑。
6. **【未验证】ZCode 上游对"同账号并发"的实际容忍度**：参考项目靠 429→冷却 事后纠偏（`relay.go:302`），但上游是否会在 429 前直接封号，未证实。
7. **【未验证】`reset.go` 重置机会的获取上限与周期**：`AvailableFiveHourResets`/`AvailableWeekResets` 的发放规则（几个/多久）未在代码中体现，只有"用掉"逻辑（`reset.go:206-211`）。
8. **【一手但需注意】zcode2api `export` 明文返回 secret**（`store.py:259-271`）—— 若我们要做导入导出，必须用 `zcb1:` 那套加密，不要照抄这条。
