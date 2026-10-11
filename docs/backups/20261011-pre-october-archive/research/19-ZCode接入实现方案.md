# 19 · ZCode 接入实现方案（Q1–Q5 决策后 · 可施工版）

> **本文档的由来**：用户在 `11` §四 对 5 个待决策问题给出了答复（2026-09-26）。其中 **Q3 明确要求「先调研清楚实现方案，做的过程再去测试」** → 本文即该实现方案。
> **重点参考**（用户指定）：`ZCode-Panel` / `zcode-switch` / `zcode-switcher`
> 依据文档：`11`（总纲）/ `12`–`16`（机制详解）/ `17`–`18`（ZCode-Panel）
> 网关侧对照：`model_gateway/core/resources.py`、`model_gateway/core/scheduler.py`、`model_gateway/adapters/`、`model_gateway/config/schemas.py`

---

## 一、决策输入（Q1–Q5 已定，逐条回填）

| # | 问题 | **用户决策（2026-09-26）** | 对方案的约束 |
|---|---|---|---|
| **Q1** | 合规边界：逆向私有端点 / TLS 指纹伪装 / 验证码自动求解 / 设备指纹虚拟化，哪几项可接受？ | **都能接受** | ✅ 四项全部纳入方案，不再设限 |
| **Q2** | 免费额度走哪条通道？ | **都需要** | ✅ 双通道**都实现**（API Key 通道 + Plan 通道），不做取舍 |
| **Q3** | `billing/current` 的 401 根因（需实测） | **先调研清楚实现方案，做的过程再去测试**；重点参考 `ZCode-Panel` / `zcode-switch` / `zcode-switcher` | ✅ 本文给出**实现方案**，实测项列为 §八；**三项目已逐项精读**（见 §三） |
| **Q4** | 要不要领取/签到能力？ | **要签到和领取能力** | ✅ 三段式 claim + 激活事件 + 批量调度**全部纳入** |
| **Q5** | 设备指纹策略：是否与 `10` 的 Device Registry 合并？ | **「不知介入这两个产品，建议初期先独立开。后面接入多个产品运行有必要合并的话再合并」** | ⚠️ **初期各产品独立实现设备身份，不做统一 Device Registry**；设计上**预留**合并点但不实现 |

> ⚠️ **Q5 的理解需你确认**：我理解为「**ZCode 与 WorkBuddy 这两个产品，设备身份初期各自独立实现；等接入更多产品、确实有必要时再合并成公共表**」。
> 这**修正**了 `09` §三 / `10` §1.4 原本"建统一设备档案表"的建议 → 本方案按**独立实现**设计（见 §五 5.1）。

---

## 二、目标与范围

### 2.1 做什么

把 **ZCode** 接成网关的**一个上游资源**，实现：

| # | 能力 | 对应诉求 |
|---|---|---|
| 1 | **多账号接入**（OAuth + 导入），每账号**独立设备身份** | R1 / R8 |
| 2 | **账号管理**（列表 / 启用停用 / 健康检查） | R2 |
| 3 | **账号切换**（启动对应账号的数据根） | R3 |
| 4 | **套餐与权益识别**（Plan 通道 + API Key 通道双通道） | R4 |
| 5 | **签到与领取**（三段式 claim + 激活事件 + 批量） | R5 |
| 6 | **模型对接**（ZCode 的 Anthropic 风格上游 → 网关统一 API） | R6 |
| 7 | **多账号额度聚合**（对外暴露） | R7 |
| 8 | **每账号设备隔离**（整根隔离路线） | R8 |

### 2.2 不做什么（明确边界，防范围蔓延）

| 不做 | 原因 |
|---|---|
| 不做统一 Device Registry | Q5：初期各产品独立 |
| 不实现 Z.ai 邮箱注册 | 官方已关闭通道（`18` §⑥） |
| 不内置接码平台 / 临时邮箱 | `18` §⑥ 已确认 ZCode-Panel 也无；且本方案不需要（登录步骤由用户手动完成） |
| 不自己下载替换 ZCode 客户端 | 同 ZCode-Panel 的取舍（自替换型程序易被 Defender 拦） |
| 不做前端 UI（首期） | 先通链路；UI 沿用网关现有管理端模式，二期再定 |

---

## 三、参考项目选型（用户指定三项，逐项对比）

### 3.1 三项目的机制对照

| 维度 | **`ZCode-Panel`** | `zcode-switch` | `zcode-switcher` |
|---|---|---|---|
| **隔离方式** | ⭐ **整根隔离**：`ZCODE_DATA_BASE_DIR=<账号>/data` | **字段级**：覆写全局 `~/.zcode/v2/credentials.json` | 字段级 + 原地 truncate 写 |
| **切换是否覆写凭据** | ❌ **不覆写**（只改 `.current` + 换数据根重启） | ✅ 覆写 | ✅ 覆写（但用 truncate 保持 inode） |
| **设备身份** | 每账号 `--device-id` + `telemetry-state.json` 双通道 | `virtual_device_mid` 写 telemetry | `machine_id`/`device_id`（凭据内） |
| **免重启切换** | ❌ 无（重启） | ✅ `hot_switch`（写后读回校验 + 退避） | ✅ CDP 刷新（⚠️ **实现缺失**，见 3.2） |
| **凭据加密** | `enc:v1` AES-256-GCM | 同 | 同 |
| **额度读取** | ⭐ **三通道**（日志 + 两联网）+ 3012 熔断 30min | 双通道 | 双通道 |
| **平台** | Windows（Electron 33） | **Mac 已核实可用** | 跨平台分支 |
| **可编译性** | ✅ | ✅ | ⚠️ **缺 2 个文件**（见 3.2） |

### 3.2 🔴 一个必须报告的发现：`zcode-switcher` 当前**无法编译**

`zcode-switcher/src-tauri/src/lib.rs:11-12` 声明了 `mod zcode_cdp;` 与 `mod zcode_launcher;`，但**这两个文件在仓库中不存在**：

```
$ ls src-tauri/src/*.rs
captcha.rs  crypto.rs  custom_provider.rs  jwt.rs  lib.rs  main.rs
oauth.rs    profile.rs  proxy.rs  proxy_pool.rs  quota.rs  restart.rs
                ↑ 无 zcode_cdp.rs / 无 zcode_launcher.rs
```

**影响**：它那套 **CDP 无感切换**（不重启客户端、靠 `--remote-debugging-port=9229` 刷新）**看不到实现**，无法作为参考。`restart.rs`（385 行）与 `proxy.rs`（878 行）**在**，可参考。

> **方案取舍**：**免重启切换不作为首期目标**。理由：① 唯一实现了它的项目源码缺失；② ZCode-Panel 的整根隔离路线**本来就不需要免重启**（切换 = 换数据根重启，没有"中间态会被覆盖"的问题）。

### 3.3 选型结论

> **主线 = `ZCode-Panel` 的整根隔离**；**辅以 `zcode-switch` 的 Mac 进程控制**（`pgrep`/`pkill -x`/`open`，已核实可用）+ **`zcode-switch` 的热切换与原子写**作为可选优化；`zcode-switcher` 的 `write_in_place`（原地 truncate 骗过 `fs.watch`）作为**降级备选**。

理由：整根隔离**根本性消除**了"覆写凭据"这一整类故障（ZCode-Panel 代码注释：`main.js:1264-1275`「老架构要『把快照复制成全局 live』，既多了一层覆盖写，也是账号库一分家就互相认不出的根源。这里把它彻底去掉了。」）。

---

## 四、网关现状盘点（哪些已有、哪些要新建）

> ⚠️ 本节是**实测当前代码**所得，不是设计文档的声明。**发现一处与设计文档不符，已标注。**

| 能力 | 现状 | 证据 |
|---|---|---|
| 出站 OpenAI 适配 | ✅ **已实现** | `adapters/openai_out.py`（207 行） |
| 出站 **Anthropic** 适配 | 🔴 **空壳（仅 docstring，1 行）** | `adapters/anthropic_out.py` 只有 1 行 docstring；**全仓无任何 import** |
| 出站 Gemini 适配 | 🔴 **空壳** | `adapters/gemini_out.py` 同上 |
| 适配器接口 | ⚠️ **仅 docstring，未形式化为 Protocol/ABC** | `adapters/base.py`（5 行，纯注释） |
| 入站 Anthropic API | ✅ **已实现** | `api/anthropic.py`（455 行） |
| 入站 OpenAI API | ✅ 已实现 | `api/openai_compat.py`（286 行） |
| 资源池 + **并发租约** | ✅ **已实现（比参考项目强）** | `core/resources.py:120-148` `pick_and_acquire` / `release`；`:151` `bench`；`:156` `disable`；`:159` `invalidate` |
| 调度器（重试 / 切换 / 冷却） | ✅ 已实现 | `core/scheduler.py`（771 行） |
| 配置模型 | ✅ `Resource` = 厂商 + 账号 + Key | `config/schemas.py:109-129` |
| 内部 IR | ✅ 已实现 | `core/ir.py`（174 行） |
| 设备身份 | 🔴 **完全没有** | 全仓无 device 相关模块 |

### 🔴 与设计文档不符的一处（必须报告）

**PRD §1.4 的 P0 决策写「三大协议全支持（出站适配）：OpenAI 兼容 + Anthropic 原生 + Google Gemini 原生」**，但**实测只有 OpenAI 出站适配实现了**，Anthropic / Gemini 出站适配**都是空壳**。

**对 ZCode 接入的直接影响**：ZCode 上游是 **Anthropic Messages 风格**（`15` §②）→ **必须先实现 `anthropic_out.py`**，否则 ZCode 接不进来。

> 这不是新增工作量，而是**PRD 已承诺但未交付的部分**。本方案把它列为 P0。

---

## 五、架构设计

### 5.1 模块划分（新增）

```
model_gateway/
├── adapters/
│   └── anthropic_out.py        🔴 从空壳 → 完整实现（§6.6）
├── upstream/                   🆕 上游产品接入层（与核心调度解耦）
│   ├── __init__.py
│   ├── base.py                 产品适配器接口（Protocol）
│   ├── zcode/                  ZCode 产品实现
│   │   ├── __init__.py
│   │   ├── crypto.py           enc:v1 加解密（§6.3）
│   │   ├── oauth.py            OAuth 双流程（§6.2）
│   │   ├── account.py          账号模型 + 列表管理（§6.2）
│   │   ├── dataroot.py         ⭐ 整根隔离：数据根管理 + 启动（§6.1）
│   │   ├── quota.py            额度三通道 + 3012 熔断（§6.4）
│   │   ├── claim.py            签到/领取（§6.5）
│   │   └── auth.py             双通道鉴权 + TLS 指纹（§6.7）
│   └── device.py               设备身份（**per-product 独立**，Q5）
└── ops/                        🆕 运营操作模块（与核心调度解耦，接续 `10` D13）
    ├── __init__.py
    ├── base.py                 AccountOperation 抽象
    └── runner.py               批量执行器（串行 + 隔离 + 四类结果）
```

**设计原则**：
- `upstream/` 与 `ops/` **不进** `core/scheduler.py` 主链路（`10` §2.4 的架构张力处置）
- 复用 `core/resources.py` 的**凭据与设备绑定**，但**不复用**其调度/限流/租约逻辑
- **设备身份 per-product 独立**（Q5）：`upstream/device.py` 只定义**接口**，各产品在自己的目录里实现

### 5.2 数据流

```
工具端 (OpenAI/Anthropic)
    ↓ POST /v1/chat/completions | /v1/messages
api/openai_compat.py | api/anthropic.py        ← 已实现
    ↓ 归一化为 IR
core/ir.py                                      ← 已实现
    ↓ 选路 + 租约
core/resources.py pick_and_acquire              ← 已实现（补额度预扣）
    ↓ 出站适配
adapters/anthropic_out.py                       ← 🔴 需实现（ZCode 上游）
    ↓ 双通道鉴权 + TLS 指纹
upstream/zcode/auth.py                          ← 🆕
    ↓ HTTPS
zcode.z.ai / api.z.ai
```

---

## 六、各模块实现方案

### 6.1 ⭐ 设备身份与整根隔离（R8 核心）

**路线**：抄 `ZCode-Panel` 的整根隔离（`17` §②）。

**目录布局**（每账号一套）：

```
<gateway_data>/upstream/zcode/accounts/<账号名>/
  data/.zcode/v2/     ← ZCODE_DATA_BASE_DIR       凭据/配置/日志/遥测/provider_config
  userdata/           ← ZCODE_DESKTOP_USER_DATA_DIR
  session/            ← ZCODE_DESKTOP_SESSION_DATA_DIR
  home/               ← ZCODE_DESKTOP_HOME_DIR
  meta.json           ← {device_mid, registered_at, switch_count, ...}
```

**启动时设置的环境变量 / 参数**（对照 `17` §2.2）：

| 名称 | 值 | 作用 |
|---|---|---|
| `ZCODE_DATA_BASE_DIR` | `<账号>/data` | 核心：重定向凭据/配置/日志/遥测 |
| `ZCODE_DESKTOP_USER_DATA_DIR` | `<账号>/userdata` | Chromium userData |
| `ZCODE_DESKTOP_SESSION_DATA_DIR` | `<账号>/session` | cookies / localStorage |
| `ZCODE_DESKTOP_HOME_DIR` | `<账号>/home` | shell HOME |
| `--device-id=<uuid>` | `meta.json.device_mid` | 设备码通道 ① |

**设备码**（对照 `17` §2.3）：

```python
def account_device_id(account_dir: Path) -> str:
    """读 meta.json.device_mid；缺失才生成。生成一次后永不重算。"""
    meta = read_json(account_dir / "meta.json") or {}
    mid = meta.get("device_mid")
    if not isinstance(mid, str) or not mid.strip():
        mid = str(uuid.uuid4())              # 标准 UUID v4
        meta["device_mid"] = mid
        write_json(account_dir / "meta.json", meta)
    return mid.strip()
```

**设备码双通道注入**（缺一不可，`17` §2.3）：
1. 命令行 `--device-id=<mid>`
2. `<账号>/data/.zcode/v2/telemetry-state.json` 的 `deviceMid`（启动前对齐，值相同则跳过写）

> 🔴 **必须补上参考项目的缺口**：`ZCode-Panel` 的导入**只校验 UUID 格式、不查跨账号唯一性**（`17` §⑤）。
> 我们的实现**必须加跨账号唯一性校验** —— 分配前查注册表，冲突则重新生成（有上限），
> 这是 `10` §1.4「三条硬约束」第 1 条的落地。

**隔离边界（诚实标注，不能宣称"完全隔离"）**：

| 例外 | 处置 |
|---|---|
| `setting.json` 不受重定向影响（客户端仍读写主 `~/.zcode/v2/`） | ⚠️ **需实测确认我们这版客户端是否同样**；若同样，代理设置需照旧写主目录 |
| `cli/` / `workspace/` / `plugin-workspace/` / `home/.zcode` 有意联回主目录 | 按需决定是否共享（共享则切号后项目列表不空） |
| ZCode 内置浏览器 session 跨账号共用 | ⚠️ 客户端用 `app.setPath` 覆盖，命令行 `--user-data-dir` 无效 → **这是已知破绽，首期接受** |

### 6.2 账号接入与管理

**OAuth 双流程**（`12` §④）：

| 流程 | 端点 | 适用 |
|---|---|---|
| 授权码 flow（主用） | `GET chat.z.ai/api/oauth/authorize` → 回调 `zcode://oauth/callback` → `POST zcode.z.ai/api/v1/oauth/token` | 交互式登录 |
| CLI device flow | `POST /oauth/cli/init` + `GET /oauth/cli/poll/{flow_id}` | ⚠️ `oauthCli.js:5-7` 称 2026-06 起 404，**需实测** |

**凭据文件结构**（`12` §②）：

```
credentials.json（扁平 map，值为 enc:v1 或明文）
  oauth:active_provider
  oauth:<provider>:access_token
  oauth:<provider>:refresh_token
  oauth:<provider>:user_info
  zcodejwttoken              ← 调计费/权益接口的唯一正确 token
config.json
  provider.<id>.options.apiKey（明文 JWT，含 user_id）
```

**refresh**：**直接移植** `zcode-reverse-engineer/zcode_auth.py:595-620`（`12` §4.5），不要自己写。

**账号去重键**（建议）：`credentials` 全文 hash（剔除易变键）+ identity 兜底（`12` §⑦ #7）。

**健康检查**（纯本地静态，不联网）：能否解密 → 能否取到 token → 能否解析 `user_id`，三档 `healthy/warning/error`（`12` §6.3）。

### 6.3 凭据加解密（`enc:v1`）

```
格式：enc:v1:<b64url(nonce 12B)>.<b64url(authTag 16B)>.<b64url(ciphertext)>
算法：AES-256-GCM
key  = SHA256(secret)
secret = env ZCODE_CREDENTIAL_SECRET
         ?? f"zcode-credential-fallback:{platform}:{homedir}:{username}"
```

Python 侧用 `cryptography` 约 20 行（`12` §⑦ #1）。**非 `enc:v1` 前缀的值原样返回**。

> ⚠️ **两个坑**：① secret 绑定 `平台+家目录+用户名` → 换机器/换用户名即解不开历史凭据；
> ② 三份实现的 `username` 取值口径**各不相同**（`id -un` / `$USER` / `os.userInfo()`）→ **必须实测我们这台机器上哪个对**。

### 6.4 额度聚合（三通道 + 熔断）

**通道优先级**（`18` §②，**日志优先**）：

| 优先级 | 通道 | 端点 / 来源 | 备注 |
|---|---|---|---|
| **1（主用）** | **客户端日志** | `<账号>/data/.zcode/v2/logs/YYYY-MM-DD.log` 尾 **4 MiB**，标记 `billing/balance 请求完成` + **括号配对**抠 JSON | ⭐ **绕开签名风控**（客户端请求带 `X-Client-Sig/Nonce/Pow` 私钥握手 + PoW，脚本无法复刻） |
| 2 | 联网（Plan） | `GET zcode.z.ai/api/v1/zcode-plan/billing/balance?app_version=` + `Bearer <jwt>` + **`X-Device-Mid`** | 缺 `X-Device-Mid` 会 400 code=3001 |
| 3 | 联网（API Key） | `open.bigmodel.cn` 的 `/api/biz/account/query-customer-account-report` 等 | 不同维度（余额/资源包，非额度桶） |

**串号防护（必须抄）**：按 `expectUserPlanId` 精确匹配；匹配不上则**退回该账号自己的旧快照**并标 `stale`，**绝不把别人的额度顶上来**（`18` §②）。

**3012 熔断**（`18` §③）：`3012` = 服务端风控 `unusual activity` → **全局熔断 30 分钟**，节流 **10s**，状态**落盘**防重启丢失。

**聚合与对外**：参考项目**只做到管理端仪表盘数字**（`16` §③）→ **对外端点需我们自研**。
建议：`GET /admin/api/upstream/zcode/quota`（管理端）+ 二期再定是否对外。

### 6.5 签到与领取

**三段式**（`14` §③）：

```
1. GET  <base>/billing/preview          → data.plans[]（按 priority 降序取 [0]）
2. GET  client/configs                  → data.configs.captcha{enabled,region,prefix,sceneId}
   ↓ 阿里云无痕验证码求解 → param
3. POST <base>/billing/claim            → body {"plan_id"} + X-Aliyun-Captcha-Verify-Param
   ↓ code==0 → 成功；2s 后异步刷新额度
```

**幂等业务码**（唯一依据，`14` §3.2）：`1003` 已领过 / `1005` 今日名额用完（回带 `data.plan.ends_at` 作 `next_at` → **天然冷却依据**）。

**激活事件**（≈签到语义）：`POST /api/v1/event/report`，两条事件 `app_launch` + `app_daily_active`，**事件体固定 16 字段**（`claim.rs:158-177` 逐键枚举）。
⚠️ **`code` 判定**：Rust `!=0` 即中止；**Go 容忍 `-1`**（"响应非 JSON"兜底码）→ **我们取 Go 的宽容策略**（避免非 JSON 响应导致误判失败）。

**批量执行器**（`14` §④ + `10` §2.3）：
- 5 段 cron 调度（分钟 tick）+ **双层互斥**（plan 级 `TryLock` + 账号级 `claimLockFor`）
- 账号间**随机抖动**（`delay + rand.Intn(delay/2+1)`）
- **逐账号失败隔离**；空跑算成功（避免 0/N 误报 failed）
- **结果四类**：`success` / `already_done` / `inactive` / `failed`（只有 `failed` 需关注）
- ⚠️ **运营类跳过 `enabled=false` 账号；续期类不看 `enabled`**（两个独立开关，`10` §2.2 教训 3）

**验证码求解**（Q1 已接受）：
- 参考 `zcode-proxy/captcha.go`（rod）+ `zcode2api/app/captcha.py`（Playwright）
- 缓存 TTL 45s + 宽限期后台刷新
- ⚠️ **数据中心 IP 会被风控 `F001` 拒绝，需住宅代理**（`18` §②）
- Python 侧建议：Playwright（与 `zcode2api` 同栈，可复用其求解逻辑）

### 6.6 模型对接（🔴 需实现 `anthropic_out.py`）

**ZCode 上游协议是 Anthropic Messages 风格**（`15` §②）：

```
端点：https://zcode.z.ai/api/v1/zcode-plan/anthropic/v1/messages   （Plan 通道，Bearer）
      https://api.z.ai/api/anthropic/v1/messages                    （API Key 通道，x-api-key）
      https://open.bigmodel.cn/api/anthropic/v1/messages            （BigModel 通道，x-api-key）
头：  anthropic-version: 2023-06-01
      Authorization: Bearer <jwt>  或  x-api-key: <key>
      X-ZCode-App-Version / X-Platform / X-Client-Language / X-Client-Timezone / X-Os-Category
      X-Device-Mid: <该账号 device_mid>       ← 设备隔离在此落地
      User-Agent: ZCode/<ver>
```

**要实现的映射**（`15` §③，约 15 组）：IR ↔ Anthropic Messages
- `messages[].role=system` → `system`（多条用 `\n\n` 拼成**单个字符串**）
- `content: string` → `[{type:"text",text}]`
- `role:"tool"` + `tool_call_id` → `role:"user"` + `[{type:"tool_result",...}]`
- `assistant.tool_calls[].function.{name,arguments}` → `[{type:"tool_use",id,name,input}]`（`arguments` 做 `json.loads`）
- `image_url` = `data:*;base64,...` → `{type:"image",source:{type:"base64",...}}`（**仅 data-URI**，远程 URL 丢弃）
- `max_tokens` / `temperature` / `top_p` / `stop`→`stop_sequences` / `tools`→`input_schema` / `tool_choice` 三态
- 响应侧：`thinking` block → `reasoning_content`；`stop_reason` 映射 `finish_reason`
- 流式：SSE `message_start` / `content_block_delta` / `message_delta` / `message_stop`；`thinking_delta → reasoning_content`

**流式策略**：**OpenAI 入站路径内部强制 `stream:true` 再聚合**（`15` §①#3）；**Anthropic 入站路径保持客户端 stream 意图**（`relay.go:232`）。

**两个必抄的实测坑**（`15` §⑥）：
1. `api.z.ai` 通道把最终 `input_tokens` 放在 `message_delta`（`message_start` 为 0）→ 取 max 累积
2. 2xx 但 `Content-Type` 非 JSON/SSE（WAF 挑战页/登录页 HTML）**按上游错误处理**并冷却账号，不要当成功

### 6.7 双通道鉴权 + TLS 指纹（Q1 已接受）

**双通道**（`15` §⑧，Q2 决定"都需要"）：

| 通道 | 凭证 | 目标端点 |
|---|---|---|
| **Plan / JWT** | `Authorization: Bearer <zcodejwttoken>` | `zcode.z.ai/.../zcode-plan/anthropic/v1/messages` |
| **API Key** | `x-api-key: <key>` | `api.z.ai/api/anthropic/v1/messages` |

**三级降级链**（`15` §⑧）：JWT + 验证码 → JWT 直连 → API Key 回退。

**状态判定**：401/403 → `invalid`；429 → `cooling`（尊重 `Retry-After`）；402/余额不足 → `exhausted`；**3012 风控单列**（不立即冷却整号）。

**TLS 指纹**（`15` §⑦）：
- `zcode.z.ai` 前置 ESA WAF，Go 默认 ClientHello **易被**识别为机器程序
- 参考实现用 `utls` 模拟 Chrome + **禁 h2**（ESA WAF 不支持 h2 ALPN）
- **Python 侧方案**：`curl_cffi`（自带浏览器指纹模拟，支持 `impersonate="chrome"`）
  → ⚠️ 但 `curl_cffi` 的指纹与 `utls` 的 Chrome 预设**不完全等同**，**需实测是否被 WAF 放行**
- **降级备选**：若 `curl_cffi` 不通过，改用 `httpx` + 自定义 ClientHello（成本高）或**接受只走 API Key 通道**（`api.z.ai` 不需指纹伪装）

### 6.8 账号池与并发租约（我们已有优势，补预扣）

**现状**：`core/resources.py:120-148` 的 `pick_and_acquire` **在选路同一同步段完成 `in_flight += 1`**，`release` 对称递减 → **比参考项目强**（参考项目完全没有租约，`16` §④ L3 负向断言确认）。

**要补的**：
- **额度预扣**：把"事后快照"改成"事前预留"（当前 `ResourceState.available` 只看冷却/禁用，不看额度）
- **per-account 并发上限**（可选，二期）

**失败切换**（`16` §⑥）：复用现有 `note_failure` / `bench` / `disable` / `invalidate` + `cooldown_seconds_for`；参考项目的 `maxAccountAttempts = 5` 与请求级 `tried` skip 集可直接对齐。

---

## 七、分阶段实施

| 阶段 | 内容 | 交付判据 |
|---|---|---|
| **P0-1** | `enc:v1` 加解密 + 账号读取（只读，不改任何文件） | 能列出本机 ZCode 账号与设备码 |
| **P0-2** | **`anthropic_out.py` 实现**（从空壳到可用） | 网关能经 ZCode 上游完成一次 `chat/completions` |
| **P0-3** | 整根隔离：数据根管理 + 启动（`ZCODE_DATA_BASE_DIR` 四件套） | 两个账号各自启动，主 `~/.zcode` 不被写 |
| **P0-4** | 设备码生成 + **跨账号唯一性校验**（补参考项目缺口） | 冲突时拒绝并报错，不静默 |
| **P1-1** | OAuth 接入 + refresh（移植 RE 实现） | 新账号可登录并落盘 |
| **P1-2** | 额度三通道（日志优先 + 联网兜底 + 3012 熔断） | 多账号额度可查、可聚合 |
| **P1-3** | 双通道鉴权 + 降级链 | JWT/API Key 都能打通 |
| **P1-4** | TLS 指纹（`curl_cffi`） | `zcode.z.ai` 可访问（**实测项**） |
| **P2-1** | 签到 / 领取（三段式 + 验证码求解） | 单账号可领；批量可跑 |
| **P2-2** | 批量执行器（cron + 双层互斥 + 四类结果） | 多账号批量领取，失败隔离 |
| **P2-3** | 额度聚合对外端点 | 管理端可见聚合数字 |

---

## 八、待实测项（Q3 的"做的过程中再测试"清单）

| # | 待实测 | 为什么必须实测 | 参考 |
|---|---|---|---|
| **T1** | **免费额度走哪条通道**（`api.z.ai` vs `zcode-plan/anthropic` 是否都扣额度） | RE 文档明确写"需实测确认"（`zcode-plan-auth-path.md:53`）；**这是 Q2"都需要"能否成立的前提** | `13` §③ |
| **T2** | **`billing/current` 的 401 根因** | RE 文档内部自相矛盾（推测缺 `data.token`，但同仓实测响应里没有该字段） | `13` §③ |
| **T3** | **`enc:v1` 的 `username` 取值口径** | 三份实现各不相同（`id -un` / `$USER` / `os.userInfo()`），错了就解不开凭据 | `12` §3.1 |
| **T4** | **`setting.json` 是否同样不受重定向** | ZCode-Panel 的实测结论是 v3.14.x；我们这版可能不同 | `17` §③ |
| **T5** | **`curl_cffi` 能否通过 `zcode.z.ai` 的 WAF** | Python 侧无 `utls`；不通过则需降级方案 | `15` §⑦ |
| **T6** | **CLI device flow 是否仍可用** | `oauthCli.js:5-7` 称 2026-06 起 404，与 zcode-switch 的实际使用矛盾 | `12` §④ |
| **T7** | **验证码是否真的强制** | 存在 `captcha_mode=off` 直连分支，上游可能已放宽 | `14` §⑨ |
| **T8** | **3012 的具体触发阈值** | 只知"命中即熔断 30min"，不知服务端判定门槛 | `18` §③ |
| **T9** | **RE 文档时效**（最新实测 2026-08-18，模型名已 GLM-5.2 → 5.3） | 接入前必须重跑一次 `client/configs` + 一次真实模型调用 | `13` §⑩ |

---

## 九、风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| **上游接口变更**（逆向所得，非公开契约） | 接入随时可能失效 | ① 端点/字段集中配置化，不散落；② 保留 API Key 通道作为稳定回退；③ 加"接口健康探针" |
| **风控升级**（3012 / F001 / 封号） | 账号不可用 | ① 熔断 30min + 节流 10s；② 账号间随机抖动；③ 住宅代理；④ **不追求高并发** |
| **`zcode.z.ai` WAF 拦截** | Plan 通道不通 | ① `curl_cffi` 指纹；② 降级 API Key 通道；③ 最坏情况**只用免认证的 `client/configs`** 拿静态套餐定义 |
| **验证码求解不稳定** | 领取失败 | ① 缓存 + 宽限期；② 失败退避；③ **领取能力做成可选模块**，失败不影响模型转发 |
| **设备隔离破绽**（内置浏览器 session 共用） | 风控可能识别 | ① 首期接受并标注；② 二期研究客户端 `app.setPath` 是否可绕 |
| **`anthropic_out.py` 工作量超预期** | P0-2 延期 | 参考 `zcode2api/app/proxy.py` + `zcode-proxy/convert.go` 的**逐函数对应**实现（`15` §⑥：`convert.go` 是 `gateway.py` 的 Go 移植，可反向对照） |

---

## 十、施工清单（接续 `10` 的 D1–D15）

| # | 动作 | 落点 | 优先级 | 依据 |
|---|---|---|---|---|
| **D16** | `enc:v1` 加解密（Python，`cryptography`） | `upstream/zcode/crypto.py` | **P0** | `12` §3.1 |
| **D17** | **实现 `anthropic_out.py`**（从空壳到可用） | `adapters/anthropic_out.py` | **P0** | §四 / `15` §③ |
| **D18** | 整根隔离：数据根 + 四件套环境变量 + 启动 | `upstream/zcode/dataroot.py` | **P0** | `17` §② |
| **D19** | 设备码生成 + **跨账号唯一性校验**（补参考项目缺口） | `upstream/device.py` | **P0** | `17` §⑤ |
| **D20** | Mac 进程控制（`pgrep` / `pkill -x` / `open`） | `upstream/zcode/dataroot.py` | **P0** | `12` §⑤ |
| **D21** | OAuth 双流程 + refresh（移植 RE） | `upstream/zcode/oauth.py` | P1 | `12` §④ |
| **D22** | 额度三通道 + 3012 熔断 + 串号防护 | `upstream/zcode/quota.py` | P1 | `18` §②③ |
| **D23** | 双通道鉴权 + 三级降级链 | `upstream/zcode/auth.py` | P1 | `15` §⑧ |
| **D24** | TLS 指纹（`curl_cffi`） | `upstream/zcode/auth.py` | P1 | `15` §⑦ |
| **D25** | `AccountOperation` 抽象 + 四类结果 | `ops/base.py` | P2 | `10` D13 |
| **D26** | 批量执行器（cron + 双层互斥 + 隔离） | `ops/runner.py` | P2 | `10` D14 |
| **D27** | 签到/领取（三段式 + 验证码求解） | `ops/builtin/zcode_claim.py` | P2 | `14` §③ |
| **D28** | 额度聚合对外端点 | `api/admin.py` | P2 | `16` §③ |
| **D29** | 额度预扣（把事后快照改事前预留） | `core/resources.py` | P2 | `16` §④ |

> **与 `10` D9–D11 的关系**：因 Q5 决定"初期各产品独立"，**D9（统一设备注册表）暂缓**；D18/D19 是**ZCode 专属的设备身份实现**。等接入多产品且确有必要时，再把各产品的实现**提升**为公共层。

---

## 十一、一句话总结

> **方案主线 = `ZCode-Panel` 的整根隔离**（一账号一数据根 + 独立设备码，不覆写任何凭据），
> **辅以 `zcode-switch` 的 Mac 进程控制**（已核实可用）。
> **首期最大工作量不是"接 ZCode"，而是补上 PRD 已承诺但未交付的 `anthropic_out.py`** ——
> 实测发现它和 `gemini_out.py` **都还是空壳（仅 1 行 docstring）**，全仓无处 import。
> **9 项待实测**已列成清单（§八），按你的要求"做的过程中再测"。
