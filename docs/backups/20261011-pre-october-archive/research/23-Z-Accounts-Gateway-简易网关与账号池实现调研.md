# 23 · Z-Accounts-Gateway（独立副本）简易网关与账号池实现调研

> **材料**：`/Users/w/Desktop/zcode相关管理软件/Z-Accounts-Gateway-source-20260928`（**零既往调研，全新材料**）。
> 它是 Z-Accounts（Tauri2 + Rust 的 ZCode 多账号管理桌面工具）的**独立副本**，新增「登录账号 / 网关池」双模式；
> 网关池模式内置一个 Go 写的 `gateway-core`，只读已有账号快照中的 **Start Plan 通道**并提供本地 API。
> **阅读口径**：全程只读（Read/Grep/Glob），**未编译、未运行任何二进制/脚本**（本机 macOS 且无 Go 工具链）。
> 证据分级：**【代码】`file:line`**（本机静态核对）｜**【推断】**（由代码结构推出的结论）｜**【未验证】**（需运行才能确认）。
> 产物忽略：`release/`、`dist/`、`gateway-core/bin/`、`launcher/payload/`、`node_modules/`、`Z-Accounts-Gateway.exe`（只看文件名/大小，不读内容）。
> 对照基准：本项目 `docs/specs/tech-design.md`（§12–§21）/ `docs/specs/prd.md` v1.18（Q25–Q28）。

---

## 结论先行（TL;DR）

| # | 结论 | 关键证据 |
|---|---|---|
| 1 | **整体是"四件套"**：Tauri2(Rust) 桌面壳 + 原生 JS 前端（无框架）+ Go 单文件 launcher + Go `gateway-core`（协议转换网关）。双模式 = `mode.json` 一个文本文件；网关模式由 Rust 侧把 **内嵌** 的 gateway-core 二进制释放到 `runtime/` 并 spawn，登录模式 kill 之 | 【代码】`src-tauri/src/lib.rs:34-40, 247-277, 307-324, 525-561, 622-629` |
| 2 | **gateway-core 是"只读快照 + 单通道"的极简网关**：只读 `~/.zcode-switch/accounts/*.json`（不写），只收 `kind=anthropic` 且 baseURL **严格等于** `https://zcode.z.ai/api/v1/zcode-plan/anthropic` 的 provider；**Coding Plan 明确不进池**（连模型清单都在加载时裁剪为 Start Plan 三款） | 【代码】`gateway-core/accounts.go:90-151, 120-123, 162-210`、`config.go:173-187`、`server.go:442-445`、`accounts_test.go:108-165` |
| 3 | **调度 = 最少在途 + 最久未用（LRU），无额度维度**；租约式 `Pick/Release`，每成员在途上限 `max_in_flight_per_account`（默认 2），单请求最多换 `max_attempts`（默认 4）个号；冷却分 5 档 + 24h 通道封锁档，状态落盘 `state.json`（0600，tmp+rename） | 【代码】`pool.go:79-139, 192-228`、`config.go:59-79`、`server.go:305-399` |
| 4 | **出口面只有 6 个端点**：`GET /healthz`（无鉴权、只给计数）、`GET /v1/models`、`GET /status`、`GET /usage`、`POST /v1/chat/completions`、`POST /v1/messages`（Anthropic 原生）。鉴权 = Bearer / `X-API-Key` 常数时间比较；非回环监听强制 ≥16 字符 key | 【代码】`server.go:77-107, 118-162`、`config.go:188-190` |
| 5 | **协议转换是完整双向的 OpenAI ↔ Anthropic**：请求体（system/tool/tool_calls/image/stop/reasoning_effort→thinking）+ 响应体 + **流式 SSE 事件翻译**（含 usage 累加、tool_use→tool_calls 索引重映射、`[DONE]` 收尾） | 【代码】`translate.go:21-132, 261-330, 349-493`、`translate_test.go:11-134` |
| 6 | 🔴 **最大差异点：Start Plan 不走直连，桥接官方客户端的 `app-server`（stdio JSON-lines）**。作者注释断言"直连即使带合法验证码参数也被 405/3012 拦（2026-09-26 验证）"，故改为：spawn 官方 `zcode.cjs app-server --stdio` 子进程，由其代为发模型请求；验证码 token 用 CDP 在**官方渲染器内**现 mint | 【代码】`appserver.go:1-23, 124-190, 427-697`、`captcha.go:1-14, 389-472`（**作者自述的实测结论，我方未复验 → 【未验证】**） |
| 7 | **账号侧（登录模式）有 4 条高价值做法**：① 额度"**未知不当零**"（只有测到的余额才可行动）② 查询失败**保留旧数据并标 `stale`** ③ 自动切号**只对"已确认额度耗尽"动作**，405/3012（真风控）走隔离、429 只冷却不隔离，**都不触发切号** ④ 活动领取**默认关闭**、前端循环驱动、逐号冷却与"每账号上限" | 【代码】`quota.rs:279-333`、`main.js:224`、`lib.rs:2255-2357`、`health.rs:15-26, 267-284, 377-398`、`store.rs:158`、`main.js:1062-1132` |
| 8 | **明确不借鉴**（剪裁/缺口）：单上游单通道不做双通道（撞 Q27-②）；模型目录硬编码三款（我们靠目录/映射，Q24/§13）；**无模型映射、无 m/y/x 调度、无取消透传、无 images、无 admin API**（我们已定论要，§4/§5）；bridge 依赖"官方客户端可 spawn/可开调试端口"（我们不做 GUI 自动化，§20 #16）；`/status` 暴露账号名与失败原因（仅靠本地回环 + key 兜底） | 见 §4.2 逐条 |

---

## 1. 整体架构与双模式

### 1.1 四件套分工

| 件 | 位置 | 职责 | 证据 |
|---|---|---|---|
| **Tauri2 + Rust 桌面壳** | `src-tauri/`（`Cargo.toml` tauri 2；`src/lib.rs` 101 KB 主逻辑） | 账号库/OAuth/额度/健康隔离/领取/CLI/**网关进程管理**；模块 `store/oauth/quota/health/claim/cipher/zcrypto/model_status/mailpool/driver/graph/i18n/cli` | 【代码】`src-tauri/src/lib.rs:1-14`、目录清单 |
| **前端（原生 ESM，无框架）** | `src/*.js`（`main.js` 108 KB 单文件渲染）+ `index.html`/`settings.html`/**`captcha.html`** 三窗口 | 仪表盘/账号库/邮箱池/网关页；全部数据经 `invoke` 拿；验证码在独立窗口里跑 SDK | 【代码】`package.json`（依赖仅 `@tauri-apps/api`）、`src/main.js:145-147, 1484-1548`、`src/captcha.js:44-127` |
| **Go 单文件 launcher** | `launcher/main.go`（`//go:build windows`，embed `payload/*.exe` + WebView2Loader.dll） | 把桌面 exe 解压到 `%LOCALAPPDATA%\ZAccountsGatewayEdition\desktop-runtime\<sha256前16>` 再启动；先按路径杀残留旧实例（升级后旧进程驻留托盘导致"没生效"） | 【代码】`launcher/main.go:1, 17-31, 38-45, 55-76` |
| **Go gateway-core** | `gateway-core/*.go`（~11 个源文件；唯一第三方依赖 `github.com/coder/websocket`，CDP 用） | 独立进程的本地网关：只读账号快照 → 账号池 → OpenAI/Anthropic 出口 | 【代码】`gateway-core/go.mod`、`gateway-core/README.md:1-5` |

**双平台化的痕迹**（与本项目相关）：`lib.rs` 为 Windows/macOS(arm64+x86_64) 三份 `include_bytes!`（`lib.rs:34-40`）、`gateway-core/bin/` 下确有 3 个平台二进制（只看文件名）、`tauri.macos.conf.json` 追加 `bundle.targets=["app","dmg"]` —— 这份副本已被扩成 macOS 可构建。
**【未验证】**：macOS 二进制是否可用、macOS 上 CDP/桥接是否成立（作者 macOS 侧行为无注释说明）。

### 1.2 「登录账号 / 网关池」双模式如何切换

```
前端 mode-switch 两按钮（main.js:1933-1936）
  → invoke("set_operation_mode", {mode})（main.js:446-455）
  → Rust：save_edition_mode（写 mode.json）＋ gateway/stop 或 start（lib.rs:622-629）
  → app.emit("state-changed") → 前端重拉 get_gateway_state（main.js:2150-2153）
```

- **持久化**：`<Base>/ZAccountsGatewayEdition/mode.json`，内容 `login\n` / `gateway\n`；读侧容错，非法值回落 `login`（`lib.rs:265-277`）。
- **启动自恢复**：app setup 末尾若 `edition_mode()=="gateway"` 自动 `gateway_start_internal()`（`lib.rs:2474-2476`）；托盘退出才真正退出（`gateway_stop_internal` 只被显式调用/切换模式时调用，`lib.rs:563-570`）。
- **网关页给用户看什么**：模式状态灯、Base URL/Key（默认打码，可显隐/重置/复制）、配置文件路径、**单次换号策略 `max_attempts` 输入 + "尝试全部 Provider"**、模型列表（不可用置灰）、"测试 API"（跑 `只回复 OK` 极小请求并显示耗时/上游原因）、今日与近 7 天用量、账号池路由表（状态点 + 成功/失败计数）、**局域网/Tailscale 分享地址 + netsh 防火墙命令**（`main.js:1484-1548`、`lib.rs:584-692`）。
- **登录模式**：账号切换 = 改写 ZCode 本地登录状态（`README.md:48`）。**与我们 Q27-⑥ 整根隔离（不覆写凭据 + 换数据根）路线不同** → 见 §4.2。

### 1.3 数据落盘位置与格式

| 内容 | 位置 | 格式 | 证据 |
|---|---|---|---|
| 模式标记 | `<Base>/ZAccountsGatewayEdition/mode.json` | 纯文本一行 | `lib.rs:265-277` |
| `<Base>` | Win `%LOCALAPPDATA%` ／ macOS `~/Library/Application Support` ／ Linux `XDG_DATA_HOME\|~/.local/share` | — | `lib.rs:247-263` |
| 网关配置 | `<Base>/ZAccountsGatewayEdition/config.json` | 由 `gateway-core/config.example.json` 模板生成：随机 `sk-zaccounts-<uuid>`、`listen=127.0.0.1:7865`、`account_dir=<账号库>`、state/usage 指到 `data/` | `lib.rs:279-301`、`gateway-core/config.example.json` |
| 网关运行时 | `<Base>/ZAccountsGatewayEdition/runtime/zcode-gateway[.exe]` | 内嵌二进制按字节比较后落盘（unix 补 0755） | `lib.rs:303-324` |
| 池状态 | `<Base>/ZAccountsGatewayEdition/data/state.json` | `{ "<memberKey>": {cooldown_until, disabled_until, last_error, last_used, successes, failures} }` | `pool.go:12-19, 192-228`、`config.go:29-30` |
| 网关用量 | `data/usage.json`（README 亦注明，`README.md:14`） | `{ "YYYY-MM-DD": {prompt_tokens, completion_tokens, total_tokens, requests, errors} }` | `usage.go:11-23, 39-53` |
| 账号库（登录模式主数据，网关只读） | `%USERPROFILE%\.zcode-switch\`（`store_dir`）＋ `accounts\*.json` | `Account` JSON：`id/name/hash/credentials/config{provider{...}}/virtual_device_mid/enabled` | `store.rs:93-94, 108-129`、`README.md:53` |
| bridge 注入物 | `data/zcode-builtin-inject.json`、`data/provider_config.json`、`data/agent-workspace/` | 官方 provider 表副本 + 空工作区 | `appserver.go:135-152, 163-164` |
| 仪表盘用量快照 | WebView 本地存储 | `README.md:53`（【未验证】键名/结构未在源码定位） |  |

> `ZCODE_DATA_BASE_DIR` / `HOME` 等可改变 ZCode 数据根；账号库路径**不迁移**（`README.md:53`、`store.rs:45, 85`）。

---

## 2. gateway-core 全解（逐文件）

### 2.1 `main.go`（43 行）：入口

- `-config` 指定配置（默认 `config.json`）、`-version`；启动前 `os.Stat(cfg.AccountDir)` 不存在即 fatal（**先探测账号目录**）（`main.go:15-28`）。
- `http.Server`：`ReadHeaderTimeout=10s`、`IdleTimeout=120s`、`MaxHeaderBytes=1MB`；**无优雅停机/信号处理**（进程由 Tauri 侧 kill，`lib.rs:563-570`）【代码】`main.go:30-41`。
- 日志两行：监听地址 + `accounts=<dir> (read-only)`（`main.go:37-38`）。

### 2.2 `config.go`（261 行）：配置面与默认值

- `CooldownConfig` 五档：`rate_limit 600s / quota 3600s / auth 3600s / captcha 1800s / transient 15s`；`MaxAttempts=4`、`MaxInFlightPerAccount=2`、`RequestTimeoutSeconds=300`、`models=[glm-5.3-flash, glm-5.2, glm-5-turbo]`、`allowed_upstream_hosts=["zcode.z.ai"]`（`config.go:16-79`）。
- 派生与兜底：`account_dir` 缺省 `~/.zcode-switch/accounts`；`credential_home` 探测 `ZCODE_SWITCH_HOME/USERPROFILE/HOME`；`zcode_live_credentials` 缺省 `~/.zcode/v2/credentials.json`；`zcode_cjs_path` 按三个候选路径探测（`config.go:99-159, 214-224`）。
- **Route F（app-server 桥）默认开**：`appserver_disabled != true` 即启用；**排除当前登录账号默认开**（`config.go:125-137`）。
- **模型清单在加载时裁剪为 Start Plan 三款**：`normalizeModel` + `isStartPlanModel` 过滤去重，空则报错（"models must include a Start Plan model"）——旧配置里的 Coding Plan 模型被静默剔除（`config.go:173-187`、`config_test.go:10-22` 断言 `glm-5.3` 被删、大小写/重复归一）。
- **非回环监听必须有强 key**：空 / `CHANGE_ME` / <16 字符 → 启动报错（`config.go:188-190, 246-249`；`config_test.go:24-35` 断言回环判别含 `localhost`、`[::1]`，`0.0.0.0`/`:7864` 不算回环）。
- 环境变量只覆盖 5 项：`listen/api_key/account_dir/credential_home/max_attempts`（`config.go:194-212`）——与铁律 1「本地明文/环境变量」同向。

### 2.3 `server.go`（618 行）：端点面、鉴权、错误语义、调度外壳

**端点面（6 个，无 admin API）**：`GET /healthz`（**不鉴权**）、`GET /v1/models`、`GET /status`、`GET /usage`、`POST /v1/chat/completions`、`POST /v1/messages`；外层 `recoverAndLog` 捕获 panic → 500 `internal_error` + 逐请求日志（`server.go:77-86, 566-578`）。

- **鉴权**：`Authorization: Bearer` 或 `X-API-Key` 二选一，`crypto/subtle.ConstantTimeCompare`；失败 401 `invalid_api_key`；通过后统一 `Cache-Control: no-store`（`server.go:92-107`）。
- **每次请求前重刷账号池**：`catalog.Load()` → `pool.Sync(members)`（/healthz、/status、/v1/models、每个模型请求都刷）→ **账号快照改动 ≤1 请求内生效**，无热重载定时器（`server.go:109-116, 306-308`）。
- `/healthz`：200/503（账号目录不可读→503）+ `{service, healthy, total, warnings, captcha_mint?}`——**不含 token、不含账号名**（`server.go:118-135`）。
- `/status`：账号数组（含 name/provider/state/in_flight/successes/failures/**last_error**）+ `counts` + `warnings` + `reload_error`；始终 200（`server.go:137-145`、`pool.go:141-190`）。
- `/v1/models`：只列配置里的三款；`available` 判定 = 存在状态**非 disabled/excluded** 的成员支持该模型 → **冷却中仍算 available**（与我们的 Q28-②「冷却中仍算可服务」同向）（`server.go:147-162`）。
- `/v1/chat/completions`：16MB body 上限 → `openAIToAnthropic` → 模型白名单（未配置 → 400 `model_not_found`）→ `callUpstream`；流式 = 逐事件翻译回 OpenAI SSE 并用翻译器返回的 token 记用量（失败记 errors）；非流式 = 32MB 上限读回 → `anthropicToOpenAI` + 从 `usage` 记 token（`server.go:164-212`）。
- `/v1/messages`：模型 normalize + 白名单后**原样透传**（只改 `model` 字段）；响应**全量读入后一次写出**（`io.ReadAll` 上限 32MB + `WriteHeader(StatusCode)` + 单次 Write）→ 🔴 **Anthropic 流式在此路径没有增量转发**（【推断】TTFT=整包时间、中途失败无法在出站侧区分、取消透传退化为"读到一半断开"）【代码】`server.go:214-253` ｜ 对照：`/v1/chat/completions` 流式是真流式。
- **错误体分协议**：`writeOpenAIError`（`{error:{message,type,code}}`）用于 chat 路径与 `writeFailure`；`writeAnthropicError`（`{type:"error",error:{type,message}}`）用于 messages 路径（`server.go:525-548`）。

**`callUpstream`（换号循环）**（`server.go:305-399`）：

- `attempt < max_attempts`，每轮 `pool.Pick(model, tried)`；**picked 后立刻 `tried[key]=true`**（请求内不重复用同一成员）。
- **两条上游路径**：① `useBridge = bridge.Enabled() && isStartPlanBaseURL(member.BaseURL)` → 走 app-server 桥（§2.9）；② 否则"legacy 直连"：先 `mint.Get()` 拿验证码（40s 预算，失败则 skip 该成员、记 `captcha_mint_unavailable`）→ `doUpstream` 直连 `{base}/v1/messages`（`server.go:319-336, 401-440`）。
- 桥失败：`bridgeFailureCooldown` 映射冷却（401→Auth 3600s+**禁用**；quota→3600s；start_plan_client_blocked→**24h**；captcha→1800s；rate_limit→600s；其余 15s）；非重试类**立刻返回**，重试类继续下一成员；传输错 → 15s 冷却继续（`server.go:58-75, 337-362`）。
- 🔴 **桥路径与直连路径的重试语义不同（易被忽略）**：桥的 `turn.failed` 只有 `quota_exhausted`（1005/1113）与 `model_not_allowed`（3006）标 `Retryable`，**401/429/3007/3012 都不重试**（`appserver.go:638-665`）——即"换号"主要服务于"这个号没额度了"，风控/限流/验证码失败不会在请求内换号（与 §4.1 作者合规姿态一致）。
- 直连失败：`classifyFailure` 后重试或返回（见下）；传输错 → 15s 继续；客户端已断开（`ctx.Err()!=nil`）→ break（`server.go:363-388`）。
- 全部尝试完 → 503：`account_pool_empty`（池空/目录错）或 `account_pool_exhausted`（带 last upstream error 摘要）；mint 不可用则附"restart the official ZCode client from this app so it exposes its debug port"提示（`server.go:389-398`）。

**`classifyFailure` 分类表**（`server.go:447-486`，`pool_test.go:9-43` 有断言）：

| 上游表现 | code | 冷却 | 置 disabled | 可重试 |
|---|---|---|---|---|
| 数字码 3012 / "unusual activity"，**start-plan 域** | `start_plan_client_blocked` | **24h** | 否 | ✅ |
| 同上但 **coding-plan 域**（本网关池外，保留分支） | `unusual_activity_blocked` | 24h | ✅ | 否 |
| 401 | `upstream_auth_error` | 3600s | ✅ | ✅ |
| 429 | `rate_limit_exceeded` | `Retry-After` 或 600s | 否 | ✅ |
| 402 / 含 quota\|credit\|balance\|额度\|余额\|exhausted\|insufficient | `quota_exhausted` | 3600s | 否 | ✅ |
| 3007 或含 captcha | `start_plan_captcha_rejected` | 1800s | 否 | ✅ |
| 403 | `upstream_forbidden` | 600s | 否 | ✅ |
| ≥500 | `upstream_unavailable` | 15s | 否 | ✅ |
| 400 | `invalid_request_error` | — | 否 | ❌（透传） |

> 🔴 **已知未处理分支**：`unusual_activity_blocked`（coding-plan 3012）只在**直连**路径可达，而池成员一律是 start-plan URL（`accounts.go:169`），故这条**在当前池内是死代码**——作者保留它以备多通道（`server.go:456-465`、`accounts_test.go:29-33` 单测仍覆盖）。

### 2.4 `pool.go`（238 行）：选号与租约

- 成员状态 = `persistedMemberState{cooldown_until, disabled_until, last_error, last_used, successes, failures}` + 内存 `InFlight`（**在途不落盘**，重启归零）（`pool.go:12-25`）。
- `Sync`：按 key 更新/新增成员，**移除已消失且 InFlight==0 的成员**（在途的保留到请求结束）（`pool.go:40-57`）。
- `Pick(model, tried)` 过滤：未试过 → `Supports(model)` → `InFlight < maxInFlight` → **非 Excluded** → 不在 cooldown/disabled；排序 **InFlight 升序 → LastUsed 升序（最久未用）→ Key 字典序**；命中即 `InFlight++ / LastUsed=now`；返回 `Lease`（`Release` 用 `sync.Once` 保证幂等减计数）（`pool.go:59-112`）。
- `Success`：successes++ / 清 last_error / **清冷却**（成功即恢复）；`Failure`：failures++ / last_error 截断 300 字符 / 写 cooldown 或 disabled（`pool.go:114-139`）。
- 状态标签：`disabled > excluded > cooling > busy > healthy`（优先级顺序）——`busy`= 在途打满（`pool.go:169-178`）。
- 落盘：`state.json` 目录 0700 / 文件 0600 / **tmp + rename 原子替换**；读取失败静默（`pool.go:192-228`）。
- 【推断】与我们的对照：这是**无优先级、无 y 阈值、无总量预算**的"最少在途 + LRU"，靠"每成员在途上限 2 + 最多换 4 个号"做并发分散；**没有**我们 §5.3 的"生效集/溢出"与 §5.2 的 C(R)/y 语义。

### 2.5 `accounts.go`（268 行）：快照 → 账号池成员（**Start Plan 唯一通道**）

- 快照结构：`id/name/enabled/credentials{}/config.provider{<id>:{name,kind,enabled,options{apiKey,baseURL}}}/virtual_device_mid`；`enabled` 缺省 true；无 id 时用文件名（`accounts.go:32-45, 113-118`）。
- 载入循环（`accounts.go:90-151`）：只读 `*.json`（目录不递归）→ JSON 解析失败记 warning 跳过 → **`enabled=false` 整个跳过** → 逐 provider 过滤：`enabled && kind=="anthropic" && apiKey 非空 && isStartPlanBaseURL(baseURL)` → **解密凭据** → `makeMember` → 去重。
- **Start Plan URL 是精确白名单**：必须 `https` + host `zcode.z.ai` + 无端口/无 user/无 query/无 fragment + path 恰为 `/api/v1/zcode-plan/anthropic`（`server.go:442-445`，`accounts_test.go:150-165` 断言端口/query/子路径全拒绝）。
- `makeMember`（`accounts.go:162-194`）：apiKey ≥16 字符；host 必在 `allowed_upstream_hosts`；**fingerprint = SHA256(apiKey) 前 6 字节 hex**（12 hex，用于日志/去重，不泄露 key）；`models` 由 `providerModels(baseURL)` 给出——**来源是硬编码**：start-plan 固定三款 `glm-5.3-flash/5.2/5-turbo` 再与配置求交（`accounts.go:196-210`）。
- 兜底通道（老快照无 provider 配置）：`credentials.zcodejwttoken` 解密成功 → 合成 `credential:zcode-start-plan` 成员（`accounts.go:135-144`）。
- 去重：`baseURL + "\x00" + fingerprint`（同账号同 key 的多 provider 只留一条）（`accounts.go:153-160`）。
- **`decryptCredential`（`enc:v1`）**：`AES-256-GCM`，key=`SHA256(secret)`，secret = `ZCODE_CREDENTIAL_SECRET` 环境变量，否则 `zcode-credential-fallback:<平台>:<home>:<用户名>`；密文格式 `enc:v1:<nonce>.<tag>.<ciphertext>`（RawURL base64）；非 `enc:v1:` 前缀视为明文（`accounts.go:212-258`；与 Rust `zcrypto.rs:10-93` 同构）。
- 【推断】**只读承诺有测试**：`accounts_test.go:14-57` 断言加载后快照文件逐字节不变。

### 2.6 `liveaccount.go`（113 行）：当前登录账号不参与路由

- 动机（文件头注释）：用户自己的官方客户端正在用那个账号，"一个账号同时服务两个客户端"正是风控要打的形态 → 池**永不路由到它**（`liveaccount.go:1-7`）。
- 实现：读 `zcode_live_credentials`（默认 `~/.zcode/v2/credentials.json`）→ 把每个可解密字符串归约成信号集：**凭证值本身**（`tok:<plaintext>`）+ `user_info` 里的 `email`/`id`（`liveaccount.go:77-113`）；与快照凭据信号求交，命中即 `Excluded`。
- **缓存以 mtime+size+1s** 为键（每请求刷池也不贵）（`liveaccount.go:51-75`）；文件缺失/不可解析 → 不排除任何人（fail-open）（`liveaccount.go:40-41`、`liveaccount_test.go:97-102`）。
- 测试不变量（作者明确在意）：**JWT 已刷新（值不同）但 email/id 相同 → 仍判为同一账号**（`liveaccount_test.go:52-83`）；**live 明文 token 与快照加密 token 相同 → 命中**（`85-95`）。
- Excluded 成员**保留在 `/status`**（state=excluded）但 `Pick` 跳过（`pool.go:88-90, 172-173`）→ 只读可观测性。

### 2.7 `translate.go`（494 行）：OpenAI ↔ Anthropic 双向 + 流式

- 模型名归一小写并剥离 `z-ai/`、`zai/` 前缀（`translate.go:14-19`）。
- **请求方向**（`openAIToAnthropic`，`translate.go:21-132`）：`system/developer` → `system` 块；`tool` → `user.tool_result`（按 `tool_call_id` 对）；`assistant.tool_calls` → `tool_use`（arguments 解析失败降级 `{raw:...}`）；连续同 role 合并；`max_tokens` 取 `max_completion_tokens>max_tokens>4096`；`stop` → `stop_sequences`；`tools[].function` → `{name,input_schema,description}`；`tool_choice none/required/auto/function` 映射；**`reasoning_effort`（非 none/disabled）→ `thinking:{type:"adaptive"} + output_config:{effort}`**；`metadata` 透传；图片 `image_url`（data URI 校验 base64，否则 url 型 source）。
- **响应方向**（`anthropicToOpenAI`，`translate.go:261-330`）：text 拼接、`tool_use`→`tool_calls`（arguments 重新序列化）、`thinking`→`reasoning_content`、`stop_reason`→`finish_reason`（max_tokens→length/tool_use→tool_calls/content_filter 直传/其余 stop）、`usage.input_tokens/output_tokens`→prompt/completion/total。
- **流式翻译**（`translateAnthropicStreamWithUsage`，`translate.go:349-493`）：手写 SSE 解析（64KB→16MB 行缓冲）；`message_start` 取 id/model/输入 token 并发首块；`content_block_start/delta` 映射 text/thinking/tool_use（**工具块 index 重映射**：Anthropic 全局块 index → OpenAI 顺序 tool index）；`message_delta` 给 finish_reason + 输出 token；`message_stop` →（可选 `include_usage` 尾块）→ `[DONE]`；上游 `error` 事件 → 以 SSE error 收尾；**未收到 stop 也补 `[DONE]`**（`translate.go:396-399`）。
- 测试不变量：tool 轮往返、usage 合计、流式含 `role/content/total_tokens/[DONE]`、**桥流必须先写 `message_stop` 再关 pipe**（`translate_test.go:99-134`）。

### 2.8 `usage.go`（81 行）：用量口径

- 按**天**聚合：`prompt_tokens / completion_tokens / total_tokens / requests / errors`；`Add(prompt, completion, failed)`；`Snapshot()` 返回 `today` + `days` + `updated_at`（`usage.go:11-63`）。
- 落盘同 pool（0700/0600/tmp+rename）（`usage.go:65-80`）。
- 【推断】**没有**按模型/资源/令牌/厂商维度，也没有 TTFT/重试/切换计数 —— 与 FR-6 的四维看板不是一个量级（见 §4.2）。

### 2.9 `captcha.go`（473 行）：验证码用在哪一步、怎么用

- **用途**：z.ai 服务端风控（405/3012 "unusual activity"）会拒绝"不是在官方客户端 webview 里 mint 的"验证码参数 —— 作者断言在多种传输/浏览器画像上实验确认 → 于是**借官方渲染器环境**：网关经 CDP 连上官方 ZCode 渲染页，注入同款无痕验证，产出**一次性** token（`captcha.go:1-14`，**作者自述实验结论 → 【未验证】**）。
- `MintService`：串行 mint（SDK 只支持一次一验证）+ **预热缓冲 1 个 token**（TTL 90s，`Get` 绝不重复发放同一 token；并发请求等待同一次 mint 而不是失败；后台 `prefetch` 把稳态延迟藏进上一个请求）（`captcha.go:56-160`）。
- 场景参数来自 `GET /api/v1/client/configs?app_version=...&platform=win32-x64` 的 `data.configs.captcha`（sceneId/region/prefix），缓存 10 分钟，失败回落硬编码常量（`captcha.go:28-37, 181-221`）。
- 本机观测口：`http://127.0.0.1:7866/param`（发 token）与 `/health`（计数/最后错误）；**启动失败不影响网关启动**，问题按请求暴露（`captcha.go:242-267`）；`/healthz` 回读其 Status（`server.go:131-133`）。
- CDP 细节：`/json/list` 里优先 `renderer/index.html` 页；`Runtime.evaluate`（`awaitPromise + returnByValue + userGesture`）；**故意不开 `Runtime.enable`**（避免超大 console 事件涌进连接）；读限 64MB（`captcha.go:277-387`）。
- `mintScript`（`captcha.go:416-472`）：页内动态加载 `AliyunCaptcha.js` → 建隐藏容器与按钮 → `initAliyunCaptcha({SceneId,mode:"popup",getInstance→startTracelessVerification, success/fail/onError})` → 返回 `captchaVerifyParam`，30s 超时。
- 桥侧还有二次过滤（见 §2.10）：`isPassShapedParam` 丢弃"success 回调里其实是短失败 token"，200 字符 + isSign + securityToken>100 才算合格（`appserver.go:900-912`）。

### 2.10 `appserver.go`（913 行）：Route F —— 用官方 app-server 当上游（**本材料最特别的一层**）

- **动机（文件头）**：由官方宿主进程自己发模型请求（它带自己的传输/头/账号凭据），是"风控唯一接受的形态"；直连即使带合法验证码参数也会 405/3012（**作者 2026-09-26 验证 → 【未验证】**）（`appserver.go:1-23`）。
- **协议**：与官方 `zcode app-server --stdio` 之间的**行分隔 JSON**（无 `jsonrpc` 字段）：下行 `session/create|setModel|subscribe|send|close`、`provider/updateAccountConfig`；上行**请求**（字符串 id，如 `server-3`）：`session/requestRuntimePreferences`、`interaction/requestProviderRuntimeHeaders`（**验证码就在这里要**）、`interaction/requestPermission`；上行**通知**：`session/event`（`model.streaming` / `turn.completed` / `turn.failed`）、`state.updated` 等（`appserver.go:10-23, 42-51, 192-259`）。
- **进程管理**：`exec.Command(node, <官方 zcode.cjs>, "app-server", "--stdio")`，env 注入 `ZCODE_BUILTIN_PROVIDER_CONFIG_FILE`（官方内置 provider 表被复制到 data 目录）与 `ZCODE_PERSONAL_PROVIDER_CONFIG_FILE`；工作区 `data/agent-workspace`；**启动后固定等 1.2s** 再发首个 RPC（`appserver.go:124-190`）。
- **多路复用**：`maxConcurrentTurns=4` 信号量；每个 turn 独立 `session/create`；**故意不 `session/close`**（宿主销毁 runtime 会让后续 turn 全挂）（`appserver.go:93-102, 479-500`）。
- **账号快照推送**：`provider/updateAccountConfig` 把内置表里 `access.type=="zhipu-account"` 的规则改写成 `entitled = (mode=="start-plan" && accountType=="zai")` 的**静态快照**（桌面应用会周期性推自己的 `entitled:false` 快照覆盖它 → 因此**每 30s 限频重推 + setModel 失败时强制重推**）（`appserver.go:335-402, 504-529`）。
- **turn 生命周期**：`session/create` → `setModel(providerId:"account:zai-start-plan", reasoningLevel:"high")`（最多 4 次重试，失败先强推快照再重试）→ `session/subscribe` → `session/send(纯文本 prompt)`；**prompt 是把 Anthropic 请求"拍平"成对话文本**（`[System instructions]…User:…Assistant:…`+固定收尾句）——即**丢弃了原生 messages/tools 结构，工具能力被禁用**（`server.go:264-303`、`appserver.go:819-851` 里 `requestPermission` 一律 `rejected`）。
- **事件消费**：`model.streaming.text_delta` → 合成 Anthropic `content_block_delta`（流式）；`turn.completed` 带 usage/response → 结束；`turn.failed` 映射：`1005/1113`→402 `quota_exhausted`（可换号重试）、`3006`→403 `model_not_allowed`、`3012`→405 `start_plan_client_blocked`、`3007`→400 `start_plan_captcha_rejected`、attribution 401/429 → 401/429；turn 计时器 = `TurnTimeout`（默认 300s）→ 504 `upstream_timeout`；客户端断开 → 499 `client_disconnected`（`appserver.go:594-668`）。
- **验证码注入点**：宿主每次问 runtime headers → 桥现 mint（15s 预算、3 次、必须 pass-shaped）并回 `{headersApplied:true, requestAuth:{apiKey:<账号 JWT>, headers:{X-Aliyun-Captcha-Verify-Param/-Region}}}`；mint 拿不到时**空手回**（让该 turn 快速失败后换号）（`appserver.go:828-876`）。
- 失败后置钩子：`OnTurnFailure` → server 侧 `pool.Failure`（流式已交给客户端后的中途失败也照记冷却）（`appserver.go:50-53, 719-723`）。
- 【推断】代价与风险：需要本机官方 ZCode 安装路径/node 可执行、需要 CDP 调试端口、每 turn 绑死一个共享宿主进程（`maxConcurrentTurns=4` 是全局并发上限）、**非流式路径下 turn 必须整轮跑完才返回**。

### 2.11 各 `*_test.go` 提取的"作者自认不变量"

| 文件 | 不变量 |
|---|---|
| `config_test.go:10-22` | Coding Plan-only 模型必须被配置加载裁剪掉；大小写/重复归一 |
| `config_test.go:24-35` | 只有 127.0.0.1/localhost/[::1] 算回环；非回环必须有强 key |
| `accounts_test.go:14-57` | 快照**只读**（逐字节不变）；`enc:v1` 可解；`virtual_device_mid` 带出 |
| `accounts_test.go:59-106` | `enabled=false` 快照整体跳过 |
| `accounts_test.go:108-148` | **Coding Plan provider 不进池**（同账号里 start-plan 进、coding-plan 出） |
| `accounts_test.go:150-165` | Start Plan URL 必须精确匹配（端口/query/子路径全拒） |
| `liveaccount_test.go:52-83` | JWT 刷新后仍按 email/id 判同一账号 |
| `liveaccount_test.go:85-95` | live 明文 token vs 快照密文 token 可匹配 |
| `liveaccount_test.go:97-102` | live 文件缺失 → 不排除任何账号（fail-open） |
| `pool_test.go:45-68` | 轮换为"最少在途 + 最久未用"；冷却成员被跳过 |
| `pool_test.go:70-84` | 模型不支持/在途打满时不可选 |
| `pool_test.go:9-43` | 3012 在 start-plan 域=通道封锁（长冷却可重试）、在 coding 域=账号级（disable）；**429 不得被误判为 start-plan 封锁** |
| `translate_test.go:11-49` | OpenAI 请求→Anthropic：system 提块、tool_calls→tool_use、tools 定义映射 |
| `translate_test.go:51-67` | 响应：stop_reason→finish_reason、usage 合计 |
| `translate_test.go:69-97` | 流式：role/chunk/total_tokens/[DONE] |
| `translate_test.go:99-134` | **桥的流式收尾必须在关 pipe 之前**（防 OpenAI 翻译器拿不到 finish_reason） |

## 3. 账号侧能力（Tauri/Rust + 前端）

### 3.1 账号库与快照格式

- 账号库路径：`<home>/.zcode-switch/accounts/*.json`（`store.rs:93-94`；README 明确"沿用历史路径，升级/改名**不迁移**"，`README.md:53`）；每个账号一个 JSON：`{id, name, created_at, updated_at, hash, credentials{}, config?, virtual_device_mid?, virtual_arms_uid?, enabled?}`（`store.rs:108-125`）。
- `enabled` 语义（注释原文）：**`None`/`true` = 参与网关池与自动切号；`false` = 停用（不出现在池子里）**（`store.rs:122`）→ 同一个开关被登录模式与网关模式共用。
- 健康隔离状态另存 `~/.zcode-switch/health.json`（账号目录的父目录）（`health.rs:109-111`）；前端另存 `acctQuota[id]`、`claimable[id]` 等短期缓存。
- 附：本副本还有"邮箱池"页（`mailpool.rs`，Outlook 授权，失效标记 invalid）——与网关池无耦合，本次不展开。

### 3.2 OAuth 添加账号

- `oauth.rs`：`init_flow(provider, mid)` 拿 authorize_url + poll_token（带虚拟设备 mid 头）→ 用户在外部浏览器授权 → `poll_flow_once` 轮询或 `parse_callback` 解析回调 → `exchange_token`（`TOKEN_URL=https://zcode.z.ai/api/v1/oauth/token`）→ `extract_user_profile` / `fetch_userinfo` / `extract_refresh_token` → `assemble_credentials_with_token` 写 `zcodejwttoken` / `oauth:*:access_token` / `user_info`（`oauth.rs:6, 52-175, 187-256, 364-508`）。
- 也支持 `auth_proxy`（代理开关 + URL）与 `parse_proxy_url`（`oauth.rs:329-360`、`store.rs:139-141, 162-168`）。
- 【推断】OAuth 是"加新账号"的唯一自动化路径；README 同时给出"官方登录后回工具点『保存登录』"的兜底（`README.md:46-48`）。

### 3.3 额度查询：多通道 + 失败标记旧数据 + 「未知额度不当零」

- **通道选择**（`quota.rs:638-695` 的 `pick_channels`）：
  - `Channel::Monitor` = BigModel 监控接口（`bigmodel.cn/api/monitor`，额度 + 订阅两个请求）；
  - `Channel::ZaiBilling` = `zcode.z.ai` 余额接口（`BILLING_BALANCE_URL?app_version=`，以 Plan/JWT 为主）。
  - 来源：`config.provider[].options.apiKey`（enabled 优先排序）+ **加密的账号级** `account-provider:coding-plan:*:api-key` 凭据兜底 + `zcodejwttoken` + `oauth:{provider}:access_token`（`quota.rs:348-427, 609-695`）。
- **执行与合并**（`quota.rs:722-855`）：逐通道请求；`business_ok` 才归一化入 parts；"不存在 coding plan/没有资格"→ 记 no-plan；全空且有 no-plan → 返回 `source:"no_plan"` 的空总览；否则 `best_err`；`merge_parts` 按 `(tier, name)` 去重、按档位 rank 选主 plan、`source` 拼接为 `"a + b"`。
- **token 级回退**（`quota.rs:560-597`）：逐 token 试；"有效 token 但空响应"与"部分内容"分离保留；**全部 401 时 sleep 1.5s 重试首个 token**（防瞬时抖动误判过期）。
- **429 退避**：`[500, 1500, 4000]ms`（`quota.rs:429-441`）——与 `tech-design.md` §16.6 写明的退避序列**逐值一致**（互证）。
- 🔴 **未知不当零**（作者注释原文："Only a measured balance is actionable. A grant without current usage is not proof that the account can chat, and a failed/incomplete response is not proof that it has run out."）：`conversation_availability` 分三态 `Available/Exhausted/Unknown`——`required_depleted`（BigModel 的 prompt_count/duration 两项必备额度为 0）→ Exhausted；`required_unknown` → Unknown；有正余额 → Available；**"有零值但也有 unknown" → Unknown 而不是 Exhausted**（`quota.rs:263-333`，测试名 `quota.rs:1610`）。
- **查询失败 → 保留旧数据并标 stale**：前端 `acctQuota[id] = { data: cur.data || null, err: String(e), busy:false, stale: !!cur.data }`（失败时旧 `data` 保留、`stale=true`）（`main.js:224`）；汇总行用 `refreshed_at` 取最新时间（`main.js:1348`）。
- 【推断】额度只用于**展示 + 自动切号判据**，**不参与网关池选号**（`pool.go` 无额度字段；网关页池 token 汇总见 §3.8 脏点 1）。

### 3.4 自动切号判据（只对"已确认额度耗尽"动作；风控/限流都不动作）

`lib.rs:2255-2357`（`start_auto_switch_monitor`，10s tick / 90s 检查间隔，设置开关默认关）：

1. 前置：`auto_switch` 开；无待处理领取；活动账号存在；**ZCode 正在运行**且账号数 ≥2（`lib.rs:2266-2282`）。
2. **判据 = `conversation_availability(live_quota) == Exhausted`**（即"已测得余额耗尽"），并要求**连续两次 tick 同一账号同样结论**（`exhausted_once` 消抖）（`lib.rs:2283-2292`）。
3. 选目标：从活动账号往后循环找 `has_config && enabled && 未被隔离` 且额度 `Available` 的账号（`lib.rs:2294-2305`）；找不到 → emit `no-candidate`，仅提示一次。
4. 执行前**重读状态再校验**（防"手动切换/关掉开关后被陈旧的监控轮次覆盖"）→ `switch_to(..., restart=true)`（`lib.rs:2314-2326`）。

**405/3012 与 429 明确不动作**（README:37 的口径，代码落点 = 健康检查分类，与自动切号是两条链）：

| 上游表现 | `RiskKind` | 处置 |
|---|---|---|
| Coding Plan 405/3012（真风控） | `Blocked` | **隔离**该账号（从切号候选与测试中排除，90s 后可自动解除/10min 复测） |
| 429 / rate limit | `RateLimited` | **冷却不隔离**（仅限制复测时间） |
| Start Plan 域 3007 或 3012（通道级封锁） | `StartPlanBlocked` | **不计失败、不改隔离状态**；"纯通道封锁不算账号失败"（`health.rs:355-357, 377-381`） |

（`health.rs:15-26, 267-284, 330-360, 377-398, 459-467`；前端 `main.js:995-1009` 批量体检时把"已隔离/通道封锁/真失败"分三类计数。）
> 【推断】这与作者"不借 405/3012/429 绕过服务端限制"的合规姿态一致：**只对"能证明账号额度用完"的情况换号**。

### 3.5 活动额度查询与领取（默认关闭）

- 后端：`claim.rs`——`BILLING_CLAIM_URL=https://zcode.z.ai/api/v1/zcode-plan/billing/claim`；`fetch_captcha_config` 读 `/api/v1/client/configs` 的 `data.configs.captcha`（`enabled/region/prefix/sceneId`）（`claim.rs:10, 315-337`）；`submit_claim` 必须带 `captchaVerifyParam`，否则直接报"no_captcha"（`claim.rs:272-286`）；业务码映射表含 `1003/1005/3001/3007/401` 等（`claim.rs:427-436`）。
- **默认关闭**：`Settings.auto_claim` 缺省 false（`store.rs:158`），UI 一个开关（`main.js:1965-1969`）。
- **前端循环执行**（`main.js:1062-1132`）：逐账号串行 → 每账号先 `claim_refresh` 刷新可领列表 → 循环领取（**每账号尝试上限** + 每轮 1.2s 间隔 + 账号间 gap）→ 失败/超时/`interactive` 记**逐账号冷却**（`1005` 用服务端 `nextAt`；`≥1000` 的业务码与 `interactive` 都记 1 小时；其余默认间隔）（`main.js:1054-1060, 1114-1116, 1124-1126`）。
- 验证码交互：独立窗口 `captcha.html`+`src/captcha.js` 加载阿里云 SDK；先试**无痕**（8s 超时）→ 失败 emit `captcha://interactive` 转人工点击（`captcha.js:6-7, 93-121`）。**没有** Playwright/无头浏览器。

### 3.6 CLI 子命令

`--cli <cmd>`（`cli.rs:75-300`）：`list` / `switch --id [--restart]` / `quota [--id]` / `model-status` / `export --id --out` / `export-all --out` / `import --file` / `setpath` / `launch` / 设置类命令；密码优先走 `ZSW_PASSWORD` 环境变量（`README.md:69-77`）。
> 注：本副本 CLI **没有** gateway 相关子命令——网关只由桌面壳管理（【代码】`cli.rs` 全量分支未见 gateway）。

### 3.7 加密备份 `.zsb` 的跨设备边界（诚实披露范本）

- 格式：`cipher.rs` —— 信封 `{format:"zsw-accounts-bundle", version:1, kdf:{pbkdf2-hmac-sha256, 100000 iters, salt}, cipher:{aes-256-gcm, nonce, tag, data}}`；`is_sealed` 要求 kdf+cipher 同时存在（`cipher.rs:11-72`）；CLI `import` **拒绝明文信封**（非 sealed / 非本 format → 退出码 2）（`cli.rs:266-271`）。
- 🔴 边界（README 原文要点）：导入成功**只代表解密并写入账号库，不代表目标机拿到有效登录**；导出会**保留 ZCode 原始凭据**，其中部分字段用**原机器的用户环境**加密 → 换机后需**逐账号在官方客户端重新登录**（`README.md:51`）。
- 保密纪律：`.zcodeignore`/`.gitignore` 明确"永不提交账号导出"（`*.zsb`、`credentials.json`、`.zcode-switch/` 等）。

### 3.8 观察到的问题点（诚实报告，供对照时避坑）

| # | 问题 | 证据 | 影响 |
|---|---|---|---|
| 1 | 前端读取 `a.remaining_tokens` 汇总"池 token"，但 Go 侧 `PoolStatus` **没有该字段** | `main.js:1501` vs `pool.go:141-156` | 池 token 汇总恒为 0（死字段）；说明"池内额度聚合"只停留在 UI 构想 |
| 2 | 凭据 fallback secret = `zcode-credential-fallback:<平台>:<home>:<用户名>` 可推导 | `accounts.go:233-241`、`zcrypto.rs:42-60` | 同机同用户名可解；多用户机器上等于弱保护（README 已披露换机不可解） |
| 3 | gateway-core 并非"零写入"：桥会向 data 目录写注入表/工作区 | `appserver.go:135-152, 163-164` | "只读账号快照"成立，但"只读进程"不成立 |
| 4 | `/status` 返回账号名/上游错误/指纹（`/healthz` 才刻意脱敏） | `server.go:137-145`、`pool.go:179-186` | 谁能拿到 key 就能读到账号明细（局域网分享场景需注意） |
| 5 | 无优雅停机/信号处理；父进程直接 kill | `main.go:30-41`、`lib.rs:563-570` | 在途请求被硬断（池状态已原子落盘，损失有限） |
| 6 | `/v1/messages` 流式为"全量缓冲后一次写出"；桥并发上限 4 | `server.go:214-253`、`appserver.go:93` | Claude Code 类客户端 TTFT 变差；并发被宿主限制 |
| 7 | 看板"今日 Token" = 额度快照差值 + 网关 usage 两口径相加 | `README.md:7,42`、`main.js:1327-1354` | 官方口径不一致时无法对账（作者已在 README 自陈"估算值"） |

## 4. 与我们对照：值得借鉴 / 明确不借鉴

对照基准：`tech-design.md` §4（端点/IR/调度/适配/流式/取消/配置/统计）、§5（m/y/x 与总预算）、§14（配置三层与账号存储）、§15–§16（设备身份/运营）、§17（ZCode 上游 + 熔断回写）、§18（`anthropic_out`）、§20（不做清单）；`prd.md` FR-3/FR-5/FR-6/FR-10、Q26/Q27/Q28。

### 4.1 值得借鉴（按优先级）

| # | 维度 | 它的做法（证据） | 我方现状与依据 | 建议 |
|---|---|---|---|---|
| **B1** | 错误语义 | **通道级封锁 vs 账号级风控**显式二分：Start Plan 域 `3007/3012` 判为"通道限制，不隔离账号、不计失败"；Coding Plan 域 `3012` 才是账号级（`health.rs:15-26, 267-284, 355-357`；`server.go:456-465`） | 我方 §17 写"3012 风控 → **全局熔断 30 分钟** + 回写 `bench`"；§20 #20 明确"统一 bench 不加维度" | **只借鉴分类维度，不动动作幅度**：评估是否在 §17 熔断判据里区分"通道级（短冷却 + 换 token/通道，不降账号信用）"与"账号级（回写 bench）"。属**新增细分**，需用户裁决；与 Q28-⑦/⑧ 的状态机口径不冲突 |
| **B2** | 额度与用量口径 | **"未知不当零"**：三态 `Available/Exhausted/Unknown`，必备额度 unknown → 整体 Unknown；`required_*` 才判耗尽（`quota.rs:263-333`）；**多通道合并**带 `source` 拼接与去重（`quota.rs:696-855`） | M5-2 额度聚合接口尚未实现（§19 M5-2）；§21 已立"消灭静默降级" | 直接把"未知 ≠ 0 + `source` 标注 + 必备通道判定"移植进 `upstream/zcode/quota.py` 的归一化层（M4-4/M5-2 判据可加断言） |
| **B3** | 错误语义 | **429 退避序列 `[500,1500,4000]ms`** 写死并单测覆盖；429 与 405/3012 严格分离，测试断言"429 不得被误判为通道封锁"（`quota.rs:429-441`、`pool_test.go:36-42`） | §16.6 已定退避序列同为 `[500,1500,4000]ms`（**互证**）；§4.3 分类要求"自定义品 400+码"的幂等分表 | 无需改动；把 `pool_test.go` 的"误判回归测试"形态加入我方 test-cases（防 405/3012 与 429 语义漂移） |
| **B4** | 账号池与凭据处理 | **只读快照 + 逐字节断言**：加载账号快照不改文件，测试断言加载前后逐字节一致（`accounts_test.go:14-57`）；指纹 = `SHA256(apiKey)[:6]`（日志/去重用，不泄露 key）（`accounts.go:172-173`） | §17 落点 `upstream/zcode/crypto.py` + 账号导入（Q26 复用原设备 ID 不重算）；FR-10.4 要求 Key 全程脱敏 | ① 我方"导入路径绝不改写源缓存"加同型测试；② 事件行/日志里的凭据标识沿用"短哈希指纹"形态（避免把 key 尾号写进日志） |
| **B5** | 账号池与凭据处理 | **当前登录账号从池中排除**：用"解密后的凭证值 + user_info 的 email/id"做信号，**以 live 文件 mtime+size 缓存**；live 文件缺失则 fail-open（`liveaccount.go:1-7, 51-113`；测试 `liveaccount_test.go:52-102`） | Q27-⑥ 整根隔离：官方客户端与网关**可以同时运行**（不同数据根），此时"同一账号被两个客户端同时使用"仍是风控形态（`liveaccount.go:1-7` 的论证对我们也成立） | 若实现期确认"官方客户端 + 网关并存"是常见场景 → 评估在 `upstream/zcode` 增加"live 账号识别/排除"，**复用其 email/id 信号（抗 JWT 刷新）+ fail-open 缓存策略** |
| **B6** | 端点面（安全） | **分层暴露**：`/healthz` 无鉴权只给计数；`/status`、`/usage` 需 key（常数时间比较）（`server.go:92-145`） | Q18-① 定"管理端免鉴权"（本地单机）；FR-10.1 允许监听 `0.0.0.0` 并展示局域网地址 | 评估点（**需用户裁决**）：一旦监听面扩到局域网，`/admin/api/*` 免鉴权即成短板 —— 其"诊断口脱敏 + 运行态口加令牌"的最小切分是最便宜的对策 |
| **B7** | 双模式切换/运行控制 | 判活 = **带 key 请求 `/status`** 而非端口探测；启动前清掉端口占用者；子进程退出后状态自愈（`lib.rs:482-489, 494-523, 525-561`） | FR-12.2 单实例锁 + 自重启（同一 PID `os.execv`，§4.10/§4.11）已覆盖大部分；但"端口被**遗留进程**占用导致新实例起不来"的处置值得查漏 | 实现期对 `bind` 失败给出"端口被占（可能是陈旧实例）"的明确处置路径（或复用其 kill-by-port 思路的本地版本） |
| **B8** | 运营（领取） | 领取**默认关闭** + 逐账号冷却（服务端 `nextAt` 优先、业务码退避）+ 每账号尝试上限 + 人工兜底窗口（`store.rs:158`、`main.js:1062-1132, 1054-1060`、`captcha.js:93-121`） | §16.5 的验证码方案（Playwright + 住宅代理 + `--manual` 兜底）；§16.4 串行 + 抖动 + 双层互斥 | 其"逐账号冷却表 + 服务端 nextAt 优先"细节与 §16.3 教训 2 同向，建议并入 `ops/runner` 的冷却实现；"默认关闭 + 人工兜底"与我方 `--manual` 一致 |
| **B9** | 边界披露 | `.zsb` 跨设备真实性披露（"导入成功 ≠ 有效登录"）、导出保留原机加密字段（`README.md:51`） | FR-8.4 导入导出（P1）；§21 用户可见出口纪律 | 我方 P1 导出功能沿用同款披露措辞（避免用户误以为"导入即生效"） |
| **B10** | 上游路线（**最高优先级报告项**） | 作者断言：**直连 zcode.z.ai 即使带合法验证码参数也被 405/3012 拦（2026-09-26 验证）**，唯一被接受的形态是"由官方宿主进程自己发请求"（`appserver.go:1-23`） | §17 的核心未决项正是 **T5a（curl_cffi 能否过 WAF）/ T5b（async SSE 是否可用）**，且 M4-3 判据本来就是"需真实凭据 + WAF → 手工"（§19 M4-3） | **不改定论、先提风险**：在 M4-3 实施前把"直连被 405/3012 拦截"作为**首要证伪/证实目标**（最小实测）；若证实，把"CDP mint / 官方宿主桥"作为 Plan B 交用户裁决 |

### 4.2 明确不借鉴（含冲突点）

| # | 维度 | 它的做法（证据） | 为什么不适用 / 与哪条定论冲突 |
|---|---|---|---|
| **N1** | 账号池与凭据处理 | **只收 Start Plan 通道，Coding Plan 凭据整体不进池**；模型清单在配置加载时裁剪为 Start Plan 三款（`accounts.go:196-210`、`config.go:173-187`、`accounts_test.go:108-148`） | 🔴 **直接冲突 Q27-②**（"双通道都需要"，API Key + Plan 都实现）与 §17"双通道都实现 + 三级降级链"；我们还要接多厂商，池成员不可能只有一条通道 |
| **N2** | 端点面 | **无模型映射、无枚举池、无能力位、无参数归一化**（`model` 只在三款硬编码模型里做小写/前缀归一，`translate.go:14-19`） | 冲突 §12（能力位下发）/§13（参数归一化与方言表）/Q28-①；我们的 `/v1/models` 要按 Q28-② 只下发可服务模型并带 caps |
| **N3** | 调度与选号 | **无 m/y/x、无总预算、无优先级**；选号 = 最少在途 + 最久未用，冷却靠固定档位（`pool.go:79-112`、`config.go:59-79`） | 冲突 FR-3.2/3.3/3.4/3.5/3.7/3.15（x 生效集、m/y、总预算 300s）；我们的调度是**全局唯一一套参数且请求级计数** |
| **N4** | 调度与选号 | **取消/中止处置不完整**：直连路径靠 Go `r.Context()` 天然取消上游 HTTP，但**桥路径**客户端断开只把本地 turn 标 499 结束、**不向宿主发任何取消**（且刻意不 `session/close`）；`/v1/messages` 又是"缓冲后一次写出"，断开只能在大块读完后才被察觉（`appserver.go:583-585, 496-500`、`server.go:241-252`） | 冲突 FR-3.11/3.12、§4.6（取消透传 P0：必须"先取消上游再退出"）与 §6（首帧边界）——我们要求 Stop 生成能真正止损上游 |
| **N5** | 端点面 | **无 images、无 admin API、无静态管理界面**（`server.go:77-86`） | 冲突 FR-5.3（`/v1/images/generations` P0）、FR-7（七页 Web 界面）、§4.1 端点表 |
| **N6** | 错误语义/统计 | 用量只有"天 × 5 个数字"，**无模型/资源/令牌/厂商/账号维度、无 TTFT/重试/切换计数**（`usage.go:11-63`）；看板还合并"额度差值"与"网关 usage"两口径（`README.md:7,42`、`main.js:1327-1354`） | 冲突 FR-6.1/6.2（5 维 + TTFT + 重试/切换）；§4.8 事件流水 JSONL 是我方唯一口径 |
| **N7** | 双模式切换/账号存储 | **登录模式 = 覆写 ZCode 全局登录态**（`README.md:48`）；账号库是单一 `~/.zcode-switch` 目录 | 冲突 Q27-⑥ 整根隔离（不覆写凭据、`.current` 标记 + 换数据根重启）与 §15.3；也不做"双运行形态"（我们只有网关模式） |
| **N8** | 账号池与凭据处理 | **bridge 把请求外包给官方客户端宿主**：spawn `zcode.cjs app-server --stdio`、CDP 连官方渲染器 mint 验证码、依赖安装路径/调试端口/固定 1.2s 启动等待、全局并发 ≤4（`appserver.go:124-190, 93-102`、`captcha.go:277-308`） | 与 §20 #16"不做 GUI 自动化"的**边界需要用户裁决**：它是"借用官方渲染器执行 JS"，不是纯接口调用；且与 §17 直连 + TLS 指纹（`curl_cffi`，T5a/T5b）路线**互斥**。**但**若 T5a/T5b 实测失败，它是材料里**唯一有作者验证记录的备选路径** → 见 B10/§4.3 |
| **N9** | 端点面（暴露面） | **非回环分享**：自动加防火墙规则、扫描 LAN/Tailscale 地址生成分享 URL、`/status`（含账号名与错误）与 `/v1/*` 同一把 key（`lib.rs:447-478`、分享面板 `main.js:1531-1548`） | 与我方"纯本地运行"精神（铁律 1）张力大；FR-10.1 虽允许 `0.0.0.0`，但**管理面（账号明细）不应随监听面一起外扩**。不借鉴其"分享面板 + 自动放行"形态 |
| **N10** | 前端工程 | 单文件 10 万行字符串拼接渲染（`src/main.js`），无组件层 | 我方已有 `frontend-spec.md` 逐像素组件规范与双模板（v2.1）；不采纳其渲染方式 |

### 4.3 与已定论的冲突点（必须显式写明）

| 冲突对象 | 冲突内容 | 处置建议 |
|---|---|---|
| **§16.5 验证码全方案**（Playwright + **住宅代理** + 45s 缓存 + `--manual`） | 材料给出了**不需要住宅代理**的另一条路：在官方客户端渲染器内 CDP mint（`captcha.go:1-14, 416-472`），或干脆把整个 turn 外包给官方宿主（`appserver.go`）。若作者"官方环境外一律 405/3012"的断言成立，则 §16.5 的"住宅代理"前提被挑战（【未验证】） | **不擅自改定论**（§20 #19 已被用户裁决走完整方案）。把"CDP mint / 官方宿主桥"登记为 §16.5 的**备选路径 B**，与 T5a/T5b 一起实测；若实测证明直连可行，两者都无需上；若不可行，交用户裁决 A/B |
| **§17 熔断回写**（3012 → 全局熔断 30min + `bench` 回写；Q28-⑦/⑧ 的读写口径） | 材料把 3012 区分为"通道级（24h **通道冷却**、不隔离账号）"与"账号级（disable）"（`server.go:456-465`、`health.rs:267-284`） | 借鉴其**分类维度**（B1），动作幅度保持我方定论（bench、不用 disable）；24h 长冷却不照搬（我们按 30min + 可配评估） |
| **Q27-② 双通道** | 材料**只做 Start Plan 单通道**并从池里剔除 Coding Plan（N1） | 明确不借鉴；反向印证我们"双通道 + 三级降级"是更完整的需求（保持） |
| **Q27-⑥ 整根隔离** | 材料是"覆写全局登录态"的切换路线（N7） | 明确不借鉴；但 **B5（live 账号排除）** 可作为整根隔离路线的**补强**（官方客户端与网关并用场景） |
| **Q28-② `/v1/models` 只下发可服务模型** | 材料不隐藏，只在列表里给 `available:false` 标记（冷却中仍算 available）（`server.go:147-162`） | 语义细节**同向**（B3 互证点：冷却中仍可服务），但过滤 vs 标记的**呈现**保持我方定论（隐藏 + 总览横幅解释，Q28-②） |
| **§20 #16 不做 GUI 自动化** | CDP mint 属于"在官方渲染器内执行 JS"，是否算 GUI 自动化需定性 | 列为待裁决项；未裁决前不得采用（B10 只做风险登记） |
| **FR-3 调度优先级** | 材料用"每请求最多换 `max_attempts` 个号"做切换预算（`config.go:63-64`、UI 可改），无 y 阈值概念 | 不借鉴其参数语义；但我方"总预算 300s + m/y"与之不冲突（不同轴），保持 |

## 5. 未验证清单

> 本机 macOS、无 Go/Rust 工具链、**未编译未运行**（只读静态阅读）。以下均为"读得到、但没跑过"的项。

| # | 未验证项 | 为什么重要 |
|---|---|---|
| 1 | gateway-core / Tauri / launcher 的**可编译性与运行行为**（含 `bin/` 下三平台二进制是否可用） | 所有"实现结论"均基于源码阅读 |
| 2 | 作者断言 A：直连 `zcode.z.ai`（带合法 captcha 参数）被 405/3012 拦，只有官方宿主形态被接受（`appserver.go:5-8`，声称 2026-09-26 验证） | **直接影响我方 §17 T5a/T5b 与 §16.5 路线取舍**（B10） |
| 3 | 作者断言 B：CDP 在官方渲染器内 mint 的 token 与官方自用无差别（`captcha.go:8-13`） | 决定"备选路径 B"是否可行 |
| 4 | macOS 上 bridge/CDP 是否成立：`zcode_cjs_path` 三个候选路径全是 Windows（`config.go:146-159`），`zcode_node_path` 默认 `node`；`X-Platform: win32-x64`、`X-Os-Version: 10.0.26200` 等头部为硬编码（`server.go:414-428`） | 副本已含 macOS 二进制与 macOS 打包配置，但平台相关适配未在代码里体现 |
| 5 | `remaining_tokens`（`main.js:1501`）是否曾由旧版 pool 返回、当前是否为死字段 | 影响"池内额度聚合"结论的强度（本报告按"当前 PoolStatus 无此字段"记） |
| 6 | "今日 Token = 额度快照差值 + 网关 usage"的合并口径准确性（跨天/额度重置/活动赠额） | 与 FR-6 对账口径相关（README 自陈为估算） |
| 7 | `.zsb` 中被"原机用户环境加密"的字段清单（README 只写"部分字段"） | 影响我方导入导出（FR-8.4）的披露措辞与兼容性设计 |
| 8 | `AppServerBridge` 长稳表现（宿主进程崩溃后的恢复、1.2s 启动等待是否足够、4 路并发下的账号快照推送竞态） | 若走 Plan B 需评估工程风险 |
| 9 | 自动切号的实际效果（连续两次确认、隔离/冷却交互、切换后登录态） | `lib.rs:2255-2357` 只做了静态阅读 |
| 10 | 前端交互（模式切换后的状态一致性、网关页在 0 账号/网关未启动时的降级） | `main.js` 只做了关键分支阅读 |

## 6. 网关侧借鉴点（落地建议）

> 与 §4.1 的 B1–B10 一一对应，这里只给"落到哪个文件/判据"的建议；**均需用户裁决后才实施**（本调研不改任何定论）。

| 优先级 | 建议 | 落点 | 判据（可验证） |
|---|---|---|---|
| **P0** | **先证伪 B10**：在真实凭据 + WAF 上跑最小直连测试（带/不带 captcha 参数各一组），判定 §17 直连路线是否成立 | M4-3 前置实测（`docs/specs/tech-design.md:1418`） | 记录 HTTP 状态 + 业务码；若 ≥1 组出现 405/3012 → 触发"备选路径 B"用户裁决 |
| **P0** | **额度聚合"未知不当零"（B2）**：三态 + `required_*` 必备通道 + `source` 拼接去重 | `model_gateway/upstream/zcode/quota.py`（§17 落点） | 假响应 fixture 单测：必备额度 unknown → `Unknown`（不得判 `depleted`）；两通道同名 plan 只算一次 |
| **P0** | **只读导入 + 指纹脱敏（B4）** | `upstream/zcode/account.py` / 日志 | ① 导入前后源文件逐字节一致断言；② 事件行/日志中凭据仅出现短哈希指纹 |
| **P1** | **通道级 vs 账号级封锁细分（B1）**：在 §17 熔断判据增加"是否通道级"维度（动作仍 bench） | `upstream/zcode/quota.py` + `core/resources.py` 回写点 | 假响应注入 start-plan 域 3007/3012 → 断言"不 disable、只短冷却 + 可换通道"；注入 coding 域 3012 → bench 回写 |
| **P1** | **live 账号排除（B5）**：整根隔离下官方客户端与网关并存时，把当前登录账号从调度池临时排除 | `upstream/zcode/`（新增小模块或扩 `dataroot.py`） | 用加密快照 + 明文 live 文件两面构造用例（含"JWT 已刷新但 email 相同"）→ 断言排除；live 文件缺失 → 断言不排除（fail-open） |
| **P1** | **监听面分级（B6）**：若监听面扩到局域网，管理面与运行态口分级 | `model_gateway/api/` + `config.yaml` | 需要用户先裁决 Q18-① 是否按"绑定地址"分级；未裁决前只写风险，不改 |
| **P2** | 429 退避与 405/3012 误判回归用例（B3） | `tests/` | 复用其 `pool_test.go:9-43` 的断言形态 |
| **P2** | 领取逐账号冷却 + 服务端 `nextAt` 优先（B8） | `model_gateway/ops/runner.py` | 假响应注入 1005 + nextAt → 断言冷却取 nextAt 而非默认间隔 |
| **P2** | 单实例"端口被遗留进程占用"的处置路径（B7） | `model_gateway/`（FR-12.2 现状查漏） | 先查现状是否已有明确报错；无则补"端口占用 = 疑似陈旧实例"的提示与手册 |

**明确不落地（防过度设计）**：材料里的双模式（`mode.json`）、官方宿主桥（在 §17 定论未推翻前）、非回环分享面板、单通道池、池状态落盘（我方已有 `circuit.json` + 事件流水）——理由见 §4.2。
