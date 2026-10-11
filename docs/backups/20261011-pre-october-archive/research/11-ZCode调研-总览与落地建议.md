# 11 · ZCode 接入调研 · 总览与落地建议

> **用户原话（逐字抄录，2026-09-25）**：
>
> > 后面也可能会对接zcode，把它里面赠送的积分和模型权益通过网关对接聚合出来进行使用。
> > `/Users/w/Desktop/zcode相关管理软件` 这里是一些关于zcode签到、切换账号、账号接入、账号管理的一些相关的产品的项目。你都深度理解下，可以把zcode这个产品多账号接入、管理、切好、套餐对接、领取、内部模型对接使用、多账号同时提取内部积分进行聚合对外使用 这一些列流程、实现方式、逻辑等都充分调研梳理清楚。便于再实施时快速入手
>
> **我理解他要的是**：摸清这 9 个项目**分别是怎么做到**这些事的（**不是**评价它们好不好），把**可复用的机制、端点、字段、坑位**提炼成**施工参考** —— 将来把 ZCode 当作网关的**一个上游资源**接进来时能**快速动手**。
>
> **诉求编号**：**R1** 多账号接入 · **R2** 账号管理 · **R3** 账号切换 · **R4** 套餐对接 · **R5** 领取（签到）· **R6** 内部模型对接使用 · **R7** 多账号提取积分聚合对外

---

## 一、一页纸结论

| # | 诉求 | 一句话结论 | 详见 |
|---|---|---|---|
| **R1** | 多账号接入 | 两条 OAuth 流程（**CLI device flow** / **授权码 flow**），登录态落在 `~/.zcode/v2/credentials.json`（扁平 map，值为 `enc:v1:…`）。**9 个项目没有一个调 ZCode 的"账号接口"，全部自实现 `enc:v1` 解密**（AES-256-GCM，key=SHA256(机器绑定 secret)）直接读写文件 | `12` |
| **R2** | 账号管理 | 快照 = 整份 `credentials.json` + `config.json` 拷贝；去重键三套实现各不相同（凭据全文 hash / 邮箱 hash / JWT `user_id`）；健康检查是**纯本地静态**（能否解密、能否取到 token） | `12` |
| **R3** | 账号切换 | 本质 = **杀进程 → 覆写两个 JSON → 重启**。进阶两招：**热切换**（不杀进程 + 写后读回校验 + 退避重试）、**原地 truncate 写**（骗过客户端 `fs.watch` 自刷新）。🔴 **切号必须删 `coding-plan-cache.json` + 锁 `setting.json`**，否则权益/路由串号 | `12` |
| **R4** | 套餐对接 | **不存在"激活码/兑换码"机制**（全库无）。两条独立通道：**API Key 通道**（`x-api-key`，按量）vs **Plan 通道**（`Bearer JWT` → `zcode.z.ai/.../zcode-plan/anthropic`）。🔴 **免费额度的正确入口是 Plan 通道，走 `api.z.ai` 不一定扣免费额度** | `13` |
| **R5** | 领取（签到） | **没有传统"每日签到"端点**。所谓签到 = `billing/claim` 领活动套餐（`period=daily`）+ `event/report` 上报 `app_daily_active`。**三段式强制阿里云无痕验证码**；幂等靠**业务码**（`1003` 已领过 / `1005` 名额用完） | `14` |
| **R6** | 内部模型对接 | ZCode 内部协议是 **Anthropic Messages 风格，不是 OpenAI 兼容**。两个中转项目都做**"三协议一套内核"**（Anthropic 原生透传 + OpenAI Chat + OpenAI Responses），内核统一规范化为 Anthropic 再转发。🔴 **`zcode.z.ai` 前置 ESA WAF，需 utls 伪装 TLS 指纹并禁 h2** | `15` |
| **R7** | 积分聚合对外 | ⚠️ **参考项目只做到"管理端仪表盘数字"**（`total_remaining = Σ 各账号`，数据源是库内快照）。**对外 `/v1/*` 没有任何额度端点**。且 **转发选号路径完全没有并发租约** → 这两块**必须我们自研** | `16` |
| **R8** | **每账号设备隔离（防风控）** | 🆕 **`ZCode-Panel` 给出了比 R1–R3 那一批更干净的方案**：不覆写任何凭据，而是用 `ZCODE_DATA_BASE_DIR` 给每账号一个**独立数据根**，再加每账号独立 `--device-id`。代码注释点明关键：「服务端按它分组就能确定这些号来自同一台机器，**这不是统计推断而是精确匹配**」 | `17` `18` |

> 🆕 **R8 是本轮新增的发现**（2026-09-26）：`ZCode-Panel` 这个项目**上轮调研时已存在但我漏掉了**（我的项目循环用了硬编码的 9 项列表）。它的隔离方案**直接命中你之前提的需求①**，且比 DSH / zcode-switch 的"杀进程+覆写文件"路线**根本性更优**。详见 §二 R8。

### 🔴 五条最重要的"认知纠偏"（传闻 vs 实际）

| # | 直觉/传闻 | 实际（有代码证据） |
|---|---|---|
| 1 | ZCode 有"积分"，签到能领积分 | **全库没有"积分"实体**。额度就是 `meter:"model_usage"` 的 **token 配额**（`unitType:"token"`、`period:"daily"`，如 GLM-5.3 3M + GLM-5-Turbo 2M/日）。**"积分"是口语化说法** |
| 2 | 可以用激活码/兑换码领权益 | **不存在码格式**。但**"客户端主动 claim 计划"是存在的**（`claim.rs` 的 `POST /billing/claim`）——RE 逆向文档说"不存在 claim 端点"，**与同工作区实现冲突，以实现为准** |
| 3 | ZCode 内部是 OpenAI 兼容 | **是 Anthropic Messages 风格**（`system` / `content[].type` / `thinking` / SSE `content_block_delta`）。要做网关必须写 **OpenAI ↔ Anthropic 双向适配层** |
| 4 | 中转站走 `api.z.ai` 就能用免费额度 | ⚠️ 文档点名某中转站走 `api.z.ai/api/anthropic` + `x-api-key: JWT` **"不一定会扣免费额度"**。**Plan 通道才是正确入口**（`zcode-plan/anthropic` + `Bearer`） |
| 5 | 切号 = 换个 token 就行 | **不够**。还要：删 `coding-plan-cache.json`（否则显示旧账号权益）+ 锁 `setting.json` 的 `providerFamilyDomain`/`modelProviderFamilyModes`（否则路由到错误 provider）+ 切 `telemetry-state.json` 的 `deviceMid` |

---

## 二、R1–R7 逐条回答（结论 + 施工要点）

### R1 · 多账号接入

**凭据文件结构**（`12` §②，全部【一手】）：

```
~/.zcode/v2/credentials.json   ← 扁平 map，key 含冒号，value 均为 string
  oauth:active_provider          → enc("zai"|"bigmodel")
  oauth:<provider>:access_token  → enc(token)     ⚠️ 各项目语义不一致
  oauth:<provider>:refresh_token → enc(token)
  oauth:<provider>:user_info     → enc(JSON 串)
  zcodejwttoken                  → enc(JWT)   ← 调计费/权益接口的唯一正确 token
~/.zcode/v2/config.json        ← provider.<id>.options.apiKey（明文 JWT，含 user_id）
```

**解密**：`enc:v1:<b64url(nonce12)>.<b64url(tag16)>.<b64url(ct)>`，**AES-256-GCM**，`key = SHA256(secret)`，`secret = env ZCODE_CREDENTIAL_SECRET ?? "zcode-credential-fallback:${platform}:${homedir}:${username}"`。**Python 侧用 `cryptography` 约 20 行即可移植。**

> ⚠️ **坑**：secret 绑定 `平台+家目录+用户名` → **换机器/换用户名即解不开历史凭据**；且三份实现的 `username` 取值口径**各不相同**（`id -un` / `$USER` / `os.userInfo()`）。

**OAuth 两条流程**（`12` §④）：CLI device flow（`/oauth/cli/init` + `/oauth/cli/poll`）与授权码 flow（`/oauth/authorize` → 回调 `zcode://` → `/oauth/token`）。**refresh 在本稿 3 个项目里只存不用，但 `zcode-reverse-engineer/zcode_auth.py:595-620` 已实现，可直接移植。**

### R2 · 账号管理

- 快照布局三套（`12` §2.5）：整文件 JSON / meta+snap 分离 / 索引+副本。
- **去重键**：建议用 **`credentials` 全文 hash（剔除易变键）+ identity 兜底**（`store.rs:185-200`）—— 比 `user_id` 更稳，能识别"同账号换了 token"。
- **健康检查**是纯本地静态的（不联网）：能否解密 → 能否取到 token → 能否解析 `user_id`，三档 `healthy/warning/error`（`12` §6.3）。

### R3 · 账号切换

**核心闭环**（`12` §⑤）：`kill → 覆写 credentials.json + config.json → 删 plan cache → 锁 setting 路由 → 写 deviceMid → 重启`。

**Mac 进程控制**（唯一可行路径，`store.rs:275-341`）：`pgrep -x zcode` 探测 → `pkill -x` → 等 4s → `pkill -9 -x` → `open` 启动。
🔴 **必须杀全 5 个进程**（`ZCode` + 4 个 `Helper`），**漏杀 Helper 会导致登录态被回写覆盖**。

**两个免重启技巧**：热切换（写后读回校验 + 250ms 递增退避，`store.rs:882-920`）；原地 truncate 写（不换 inode，让客户端 `fs.watch` 认作"同文件 modify"，`profile.rs:620-636`）。

### R4 · 套餐对接

**套餐优先序**：已购 Coding Plan → 用 Coding Plan（Start Plan 不可选）；否则 Start Plan active → 用免费额度；都没有 → `coding_plan_not_entitled`。

**免认证即可拉套餐定义**：`GET zcode.z.ai/api/v1/client/configs` → `data.configs.startPlanPreview`（**登录与否返回一致**）。
⚠️ **但它是账号无关的静态定义，不能判定该账号是否被授予** —— **账号级 entitlement 仍需登录**。

### R5 · 领取（签到）

**三段式**：`GET billing/preview`（取 priority 最高的 plan）→ **阿里云无痕验证码求解** → `POST billing/claim {plan_id}` + `X-Aliyun-Captcha-Verify-Param`。

**幂等业务码**（唯一依据）：`1003` 已领过；`1005` 今日名额用完（回带 `data.plan.ends_at` 作 `next_at`，**天然冷却依据**）。

**激活事件体固定 16 字段**（`claim.rs:158-177` 逐键枚举）—— 这是最接近"签到"的动作。
⚠️ **`code` 判定两实现不同**：Rust `!=0` 即中止；**Go 容忍 `-1`**（"响应非 JSON"兜底码）。

**批量实现可直接抄**（`14` §④）：5 段 cron + **双层互斥**（plan 级 `TryLock` + 账号级 `claimLockFor`）+ 账号间随机抖动 + **逐账号失败隔离** + 空跑算成功。

### R6 · 内部模型对接

**端点**：`https://zcode.z.ai/api/v1/zcode-plan/anthropic/v1/messages`（Plan/JWT 通道，`Authorization: Bearer`）。

**三协议一套内核**：对外同时给 Anthropic `/v1/messages` + OpenAI `/v1/chat/completions` + `/v1/responses` + `/v1/models`，内核**统一规范化成 Anthropic 格式**再转发。
- `thinking_delta → reasoning_content`（对齐 DeepSeek 风格客户端）
- `stop_reason`：`max_tokens→length`、`tool_use→tool_calls`
- 远程图片 URL **静默丢弃**（只支持 `data:` base64）
- 流内 `error` 事件**不吞**（→ 502 / `response.failed`），避免"假装成功"

**TLS 指纹**：`zcode.z.ai` 前置 ESA WAF，Go 默认 ClientHello **易被**识别为机器程序 → 用 `utls` 模拟 Chrome + 禁 h2。⚠️ **是"强默认项"而非硬约束**（保留 `off` 模式），实际拦截率未测。

### R7 · 积分聚合对外

**参考项目只做到两件事**（`16` §③）：
1. 管理端仪表盘 `total_remaining = Σ 各账号 Remaining` —— **数据源是库内快照，非实时**。
2. **对外 `/v1/*` 没有任何额度端点**（已逐条确认）。

🔴 **转发选号路径完全没有并发租约**（`16` §④，**已用 L3 负向断言穷尽检索确认**）：`pool.Select` 只做"过滤 → 返回指针"，不占位；状态更新只发生在请求成功/失败**之后**（事后记账）。**并发请求会撞同一账号。**

> ✅ **对我们的意义**：`02` 已确认**我们自己的网关有 `pick_and_acquire` 租约**（`resources.py:120-148`，选路同一同步段完成 `in_flight += 1`）—— **这块我们比参考项目强，不要退化**。缺的只是"额度预扣"（把事后快照改成事前预留）。

### R8 · 每账号设备隔离（🆕 `ZCode-Panel` 的独立方案）

**这是本轮最有价值的发现**：`ZCode-Panel` 用了一条**与 R1–R3 那批项目完全不同**的路线。

| 维度 | `zcode-switch` 等（R1–R3） | **`ZCode-Panel`（R8）** |
|---|---|---|
| 切换方式 | 杀进程 → **覆写** `~/.zcode/v2/credentials.json` + `config.json` → 重启 | **不覆写任何凭据**，只改 `.current` 标记 + 用**新数据根**重启 |
| 数据位置 | 全局 `~/.zcode/v2/`（所有账号共用一份，靠覆写切换） | 每账号 `<账号>/data/.zcode/v2/`（**各自独立，互不干扰**） |
| 设备隔离 | `virtual_device_mid` 写进 `telemetry-state.json` | **双通道**：`--device-id=<uuid>`（CLI 参数）+ `telemetry-state.json.deviceMid` |
| 隔离支点 | 无（靠文件覆写） | **`ZCODE_DATA_BASE_DIR`** 环境变量（`main.js:1204`） |

**核心机制（`17` §②）**：

```
accounts/<账号名>/
  data/.zcode/v2/     ← ZCODE_DATA_BASE_DIR   凭据/配置/日志/遥测/provider_config
  userdata/           ← ZCODE_DESKTOP_USER_DATA_DIR   Chromium userData
  session/            ← ZCODE_DESKTOP_SESSION_DATA_DIR  cookies/localStorage
  home/               ← ZCODE_DESKTOP_HOME_DIR     agent 的 shell HOME
  meta.json           ← 注册时间 / 设备码 / 切换计数
```

启动时设这**四组环境变量** + `--device-id=<meta.json.device_mid>`。

**设备码**（`main.js:1135-1145`）：`accountDeviceId()` 读 `meta.json.device_mid`，缺失才 `crypto.randomUUID()`；**生成一次永不重算**。代码注释给出的理由很硬：

> 「不隔离的话，同一台机器上所有账号上报的是同一个设备码 —— 服务端按它分组就能确定这些号来自同一台机器，**这不是统计推断而是精确匹配**。」（`main.js:1131-1133`）

**隔离不是全覆盖**（诚实标注，`17` §③）：
- `setting.json` **仍读写主 `~/.zcode/v2/`**（实测：只写账号目录时客户端日志仍是 `mode=direct`）
- `cli/` / `workspace/` / `plugin-workspace/` / `home/.zcode` **有意联回主目录**（否则切号后项目列表空白）
- ZCode **内置浏览器 session 跨账号共用**（客户端用 `app.setPath` 覆盖，命令行 `--user-data-dir` 无效）

> 🔴 **对我们的设计含义**：这印证了 `10` 里定的「设备档案表」方向，而且给出了**比 DSH 更彻底的做法**——DSH 只隔离"设备码字段"，ZCode-Panel 隔离的是**整个数据根**（凭据+浏览器数据+HOME）。**建议 `10` 的 D9–D11 参考这条路线重估**：若我们的上游也是"每账号一个客户端实例"的形态，整根隔离比字段级隔离更干净。

---

## 三、分期落地建议

| 优先级 | 事项 | 依据 | 与铁律关系 |
|---|---|---|---|
| **P0** | `enc:v1` 解密 + 凭据读取（Python ~20 行） | `12` §3.1 | ✅ 相容（纯本地读文件） |
| **P0** | 账号列表聚合（多账号 → 统一视图） | `12` §2.5 | ✅ 相容 |
| **P0** | **整根隔离方案评估**：`ZCODE_DATA_BASE_DIR` 式"一账号一数据根" | **`17` §②** | ✅ 相容；**建议优先于 `10` 的字段级设备档案**（见 R8 的设计含义） |
| **P1** | OAuth 接入流程 + refresh（**移植 RE 现成实现**） | `12` §④ | ✅ 相容 |
| **P1** | 模型目录拉取（`client/configs`，免认证） | `15` §⑤ | ✅ 相容 |
| **P1** | OpenAI ↔ Anthropic 双向适配层 | `15` §③ | ⚠️ 工作量较大（映射表约 15 组） |
| **P1** | TLS 指纹（若走 `zcode.z.ai`） | `15` §⑦ | 🔴 **需决策**（见 §四 Q1） |
| **P2** | 领取/签到（三段式 + 验证码求解） | `14` §③ | 🔴 **需决策**（验证码需真实 Chrome + 住宅代理，部署成本高） |
| **P2** | 额度聚合对外端点（自研） | `16` §③ | ✅ 相容 |
| **P2** | 并发租约 + 额度预扣（自研） | `16` §④ | ✅ 相容（我们已有租约雏形） |
| **P2** | 额度读取三通道（日志尾解析 + 联网兜底 + 3012 熔断） | `18` §②③ | ✅ 相容；日志通道**绕开签名风控**，是最稳的一手数据源 |

---

## 四、待用户决策清单（✅ **已全部决策，2026-09-26**）

| # | 问题 | ✅ **用户决策** | 落地 |
|---|---|---|---|
| **Q1** | **合规边界**：逆向私有端点 / TLS 指纹伪装 / 验证码自动求解 / 设备指纹虚拟化，哪几项可接受？ | **都能接受**（四项全接受） | 四项全部纳入方案，不再设限 |
| **Q2** | **免费额度走哪条通道**（`api.z.ai` vs `zcode-plan/anthropic`） | **都需要**（双通道都实现，不做取舍） | `19` §6.7 双通道 + 三级降级链 |
| **Q3** | **`billing/current` 的 401 根因** | **先调研清楚实现方案，做的过程中再去测试**；重点参考 `ZCode-Panel` / `zcode-switch` / `zcode-switcher` | → **新建 `19-ZCode接入实现方案.md`**；实测项列成 §八 九项清单 |
| **Q4** | **要不要"领取/签到"能力** | **要签到和领取能力** | `19` §6.5 三段式 + 激活事件 + 批量执行器 |
| **Q5** | **设备指纹策略**（是否与 `10` 的 Device Registry 合并） | **「不知介入这两个产品，建议初期先独立开。后面接入多个产品运行有必要合并的话再合并」** | ⚠️ **初期各产品独立实现设备身份，不做统一表**；预留合并点 → `19` §五 5.1 |

> ⚠️ **Q5 的理解需你确认**：我理解为「**ZCode 与 WorkBuddy 这两个产品的设备身份，初期各自独立实现；等接入更多产品、确有必要时再合并成公共表**」。
> 这**修正**了 `09` §三 / `10` §1.4 原本"建统一设备档案表"的建议 → 已按**独立实现**调整（`10` §1.6 与 `19` §五）。
>
> **Q3 的产出** → `19-ZCode接入实现方案.md`（可施工版，含 29 条 D 编号施工清单 + 9 项待实测）。

---

## 五、调研产出清单

| 文件 | 行数 | 内容 |
|---|---|---|
| `11-ZCode调研-总览与落地建议.md` | 本文件 | 总纲：一页纸结论 / R1–R7 逐条 / 分期建议 / 待决策 |
| `12-ZCode-账号接入与切换.md` | ~310 | R1/R2/R3：凭据结构 / `enc:v1` 加密 / OAuth 双流程 / 切换闭环 / 设备身份 / 健康检查 |
| `13-ZCode-套餐权益与配额.md` | ~240 | R4：套餐类型 / 权益查询端点 / 额度体系 / 模型权益 / provider 配置 |
| `14-ZCode-签到与领取.md` | ~200 | R5：领取类动作全表 / 三段式流程 / 业务码幂等 / 批量调度 / 设备号与签到 |
| `15-ZCode-内部模型对接.md` | ~280 | R6：Anthropic 协议 / 字段差异全表 / 三协议对外 / 请求响应流式转换 / TLS 指纹 / 鉴权链 |
| `16-ZCode-账号池与额度聚合.md` | ~300 | R7：账号池数据结构 / 额度聚合 / **选路与并发租约专项** / 失败切换 / 加密与出口代理 |
| `17-ZCode-Panel-数据隔离与账号切换.md` | ~235 | **R8**：`ZCODE_DATA_BASE_DIR` 整根隔离 / 四组环境变量 / 设备码双通道 / 隔离边界例外 / 切换流程 / 导入 / 会话索引 / 自动探测 |
| `18-ZCode-Panel-登录额度与套餐.md` | ~154 | R8 补充：额度三通道（日志 + 两联网）/ 3012 熔断 30min / OAuth 与 `enc:v1` / 登录驱动人机分工 / 代理分流 |
| **`19-ZCode接入实现方案.md`** | ~380 | **✅ Q1–Q5 决策后的可施工方案**：三项目选型 / **网关现状盘点（发现 `anthropic_out.py` 是空壳）** / 架构设计 / 8 个模块实现方案 / 分阶段实施 / **9 项待实测清单** / 风险对策 / **D16–D29 施工清单** |
| `zcode-drafts/` | — | **过程留痕**：7 份子 agent 原始草稿 + `_verify/` 3 份独立核验报告 |

**质量流程说明**：
- **Stage 0 需求框架复核**：用户原话逐字抄录 + "我理解他要的是 ____" + 诉求编号 R1–R7（防框架漂移）
- **Stage 1 并行调研**：5 个方向各 1 个独立子 agent，同批发起
- **Stage 2 独立核验**：2 个**未参与撰写**的子 agent 证伪导向核验（L2 正向内容断言 / L3 负向断言 / L4 统计重算）
- **Stage 3 修订定稿**：逐条落实 36 处修正，每份定稿文首附「修订记录」表
- **Stage 4 主 agent 终检**：L1 机械校验（见 §六）

---

## 六、核验与可信度说明

### 只读基线（各仓库 HEAD，2026-09-25 记录）

| 项目 | HEAD | 状态 |
|---|---|---|
| `zcode-switch` | `6df5c096deaa` | dirty=4（既有，非本次） |
| `zcode-account-switcher` | `64f50888c969` | dirty=2（既有） |
| `zcode-switcher` | `7ae0e48a5fbc` | clean |
| `zcode-reverse-engineer` | `b662479ccddc` | dirty=1（既有） |
| `zcode2api` | `e2119afd5769` | clean |
| `zcode-proxy` | `720a7228a59f` | clean |
| `zemote` | `150462e8f6a3` | clean |
| `ZCode-Deploy` | `82a578be4c06` | clean |
| `Zcode-register` | `b90f8e075518` | dirty=1（既有） |
| **`ZCode-Panel`**（2026-09-26 补研） | **`84f2a2fc4088`** | clean |

> ⚠️ **补研说明**：`ZCode-Panel` 在首轮调研时**已存在但被漏掉**（首轮的项目循环用了硬编码的 9 项列表，而目录实际有 10 项）。2026-09-26 补齐调研，产出 `17`/`18`。

> **本次调研全程只读**，未写入/重命名/格式化任何参考项目文件。所有脚本落在 `/tmp/`。

### 核验发现（两轮共 46 处，含 7 条严重）

| 核验层 | 方法 | 结果 |
|---|---|---|
| **L1 引用可解析** | 脚本抽取全部 `文件:行号`，校验存在性 + 越界 | **3624 条引用，我的 ZCode 交付物 0 问题**；检查器自测 **8/8** 通过（含植入的"文件不存在"/"行号越界"/"缩写路径跳过"/"跨草稿引用"用例） |
| **L2 正向内容断言** | 独立 agent 逐条读具体行区间，确认"真的写了那句话" | 抓出 **4 处行号偏移**（差 1–3）、**1 处引用方向相反**（`profile.rs:895-907` 是 `apikey` 分支，语义与文档相反）、**1 处引用不支持结论**、**1 处函数名张冠李戴** |
| **L3 负向断言** | 对"某能力不存在"类结论穷尽检索 | 抓出 **4 处断言范围 > 检索范围**：① "refresh 全仓无调用"（漏了 RE 已有实现）；② "proxy.rs 无任何锁"（有锁，但不参与选号）；③ "主 `~/.zcode` 唯一写入是 setting.json"（**漏了 tasks-index.sqlite 回写**）；④ "接码关键词 0 命中"（`style.css:123` 有死注释） |
| **L4 统计断言** | 数字独立重算 | 抓出 **3 处硬数字错误**：模型数 21→**20**；事件体字段 14→**16**（施工级）；"零文件复制"（凭据成立、会话索引不成立） |

**最严重的 4 条（已全部修正）**：
1. **A/B 跨稿冲突**：B 稿说"不存在 claim 端点"（引 RE 文档），但 A 稿引的 `zcode-switch/claim.rs:9-11` 就有 `POST /billing/claim` → **B 把单仓库结论当成了全工作区结论**
2. **C 稿事件体字段数写错**（14→16）→ 按错的数字实现会被服务端拒绝
3. **A 稿引用方向相反**（把 `apikey` 分支当成"锁 oauth"）→ 照做会得到相反行为
4. **F1 稿"主 `~/.zcode` 唯一写入是 setting.json"** → 漏了会话索引回写，且**与原稿自身另一节自相矛盾**

### 已知边界（诚实标注）

| # | 无法核实项 | 性质 |
|---|---|---|
| 1 | **`~/.zcode/v2/` 运行期凭据文件不可读** | 按策略审批超时，**未重试、未推测**。所有凭据结构结论均**从项目源码反推** |
| 2 | 9 个项目中 `zemote`（Flutter）/`zcode-proxy`（Go）/`ZCode-Deploy`（Windows）在本机**不可运行** | 只做**静态代码阅读**，未实测运行 |
| 3 | `zcode-switcher` 的 `zcode_cdp.rs` / `zcode_launcher.rs` **在副本中缺失**（`lib.rs:11-12` 有 `mod` 声明） | CDP 无感切号的具体报文**无法证实** |
| 4 | RE 文档的时效 | 最新实测为 **2026-08-18**，模型名已从 GLM-5.2 漂到 **5.3** → **接入前必须重跑一次 `client/configs` + 一次真实模型调用** |
| 5 | 上游服务端行为（是否按 `device_mid` 限流、风控 3012 触发条件、封号阈值） | **只有客户端代码，没有服务端** → 全部标【未验证】 |

---

## 七、参考来源

### ⚠️ 先分清：ZCode 相关有**三个位置**（别混）

| 位置 | 是什么 | 已覆盖于 |
|---|---|---|
| `/Users/w/Desktop/01-关注的开源项目/ZCode` | **ZCode 客户端源码**（Electron 应用本体） | 既有 **`01-ZCode-模型参数与能力归一化机制.md`** —— 研究**它内部怎么归一化模型参数/能力**（DSH 式 DSL 轨 + overlay 能力轨） |
| `/Users/w/Desktop/zcode相关管理软件/` | **9 个第三方管理工具**（账号切换/中转/逆向文档） | **本批 `11`–`16`** —— 研究**怎么把 ZCode 接成上游** |
| `~/.zcode/v2/` | **运行期状态**（凭据/配置/日志） | ⚠️ **按策略不可读**（见下） |

> **`01` 与本批是互补关系，不重复**：`01` 回答"**ZCode 自己怎么做参数归一化**"（用来改我们的参数处理），本批回答"**怎么把 ZCode 当资源接进来**"（账号/套餐/领取/模型对接/额度聚合）。

### 来源清单

| 类型 | 来源 |
|---|---|
| **一手（本机磁盘）** | 9 个项目的源码与文档，路径 `/Users/w/Desktop/zcode相关管理软件/`，基线见 §六 |
| **一手（其中 RE 是逆向文档）** | `zcode-reverse-engineer/docs/`（`[实测]` / `[反编译]` / `[推测]` 三档已在 `13` 逐条标注） |
| **未使用** | 无外部网络来源；本调研**全部基于本机磁盘的代码与文档**，未引用社区帖/媒体 |

> ⚠️ **注意**：`zcode-reverse-engineer` 的文档本身是**逆向产物**，其结论强度已在 `13` 逐条标注（`[实测]` = 真实 API 调用验证过；`[反编译]` = 从 ASAR 读出，**响应体数值可能是"预期"而非实测**；`[推测]` = 文档自标推断）。**不要把"文档说"直接当成"事实"。**
