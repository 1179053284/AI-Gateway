# 04 · 网关「CLI 对接模式」设计（定稿）

> **本文件回答用户问题三**：网关现在只有 API 模式；如果以后要对接「授权提取工具内部模型」这类上游，走 API 是不是风险大、不稳定？除了 API，是不是还应该有 CLI 对接模式，让任何工具装了 CLI 就能无缝衔接网关，以最直接最稳定最短路径调用网关聚合的模型资源？以及怎么把网关已生效的模型信息给到对接软件、支持在软件内切换模型？
>
> 事实基准：本仓库 `model_gateway/` 源码 + `data/config.yaml` + 网关实跑日志 `data/gateway.log`（104,749 行，截至 2026-09-24）+ **本机实测**（2026-09-24，网关正在运行于 `127.0.0.1:8300`）。
> 写作约定：**【代码】**= 直接读到的代码事实；**【实测】**= 本机实际运行观测；**【推断】**= 未经证实的推断；**【未验证】**= 卡住没证实。

---

## 0. 结论先行

### 0.1 必须先纠正的一个认知：「CLI 对接模式」不是一个方向，是两个正交方向

用户的这句话里其实混着两件事，**它们的答案完全相反**，必须拆开：

| 方向 | 含义 | 谁发起 | 用 CLI 是对的还是错的 |
|---|---|---|---|
| **下行**（下游） | 本机 AI 工具 → 网关 | 工具 | **只有少数工具需要**；多数工具填 `base_url` 就够了，加 CLI 反而**多一跳** |
| **上行**（上游） | 网关 → 厂商 | 网关 | **是真正的「最直接最短路径」**，但仅当该厂商**只提供 CLI、不提供 API** 时成立 |

**把这两个方向混在一起谈，会得出"CLI 更短更快"的错误结论。** 下面分开给结论。

### 0.2 逐条回答

| # | 问题 | 结论 |
|---|---|---|
| **a** | 走 API 对接「授权提取内部模型」是不是风险大、不稳定？ | **是，但根源不是「API 这个形态」，是「凭据与契约的来源」。** 逆向得到的内部 HTTP 接口**没有契约、随时可变**（证据见 §2.1）；而**厂商官方 API 恰恰是最稳定的形态**。所以正确做法不是「把 API 换成 CLI」，而是**按凭据来源分层**：官方 API 走 API，只有官方 CLI 的产品走 CLI 上游适配器。**换形态不能规避风险，换凭据来源才能。** |
| **b** | CLI 对接模式怎么设计，让任何工具装了 CLI 就能无缝衔接？ | **`mgw` 本地 CLI 作统一入口**：`mgw setup <tool>` 打印/写入该工具的接入配置；`mgw models` 打印可复制的模型表格；`mgw run` 提供 stdio 通道供「命令型 provider」的工具直接调用。**但必须说清：CLI 的真实价值是"覆盖那些不给你填 base_url 的工具"，不是"更短的路径"**（§3.1 有分类论证）。 |
| **c** | 「最直接最稳定最短路径」具体怎么实现？ | **对绝大多数工具，最短路径就是现状**：工具 → `http://127.0.0.1:8300/v1`（本机 loopback，一跳）。**加 CLI 只会变长**（多一次 fork/exec + 一次进程间通信）。唯一能真正缩短的是**传输层**：把 loopback TCP 换成 **Unix Domain Socket**（uvicorn 0.52.4 已支持 `uds` 参数，**实测确认**），省掉 TCP/IP 栈。**「最稳定」的关键不是换传输，是让网关别挂**（单实例锁 + 热重载 + 故障切换已具备）。 |
| **d** | 怎么把已生效的模型信息给对接软件、并在软件内切换？ | **三级下发**：① `GET /v1/models` 补元数据（现只有 6 个字段）；② `mgw models [--json\|--md]` 给人和脚本；③ `mgw setup <tool>` 直接写进工具配置。**⚠️ 但当前有一个必须先修的问题**：**实测 `/v1/models` 会下发 7 个「已启用但零资源」的模型，工具选中任一个都必然 `NO_RESOURCE` 失败**（§4.1 有完整实测证据）。**「已启用」≠「可服务」，下发前必须区分。** |

### 0.3 一句话总纲

> **不要为了"看起来更短"去引入 CLI 通道；要用 CLI 去做那些 HTTP 做不到的事** —— 写配置、列模型、兜住不支持自定义 provider 的工具、以及在上游侧包住「只有 CLI 的产品」。

---

## 1. 先把两个方向拆开

```
        上行（上游）                                下行（下游）
   ┌──────────────────┐                    ┌──────────────────────┐
   │  厂商 / 平台      │                    │  本机 AI 工具         │
   │  · 官方 API       │◀── ① 官方 API ─────│  Trae / Cursor       │
   │  · 官方 CLI       │◀── ② CLI 上游 ─────│  Cherry Studio       │
   │  · 工具内部接口   │◀── ③ 逆向内部接口 ──│  DSH / Cline / Roo   │
   └──────────────────┘                    └──────────────────────┘
                    ▲                                  ▲
                    │                                  │
              ┌─────┴──────────────────────────────────┴─────┐
              │            Model-Gateway（中枢）              │
              │  调度 / 容错切换 / 冷却 / 统计 / 模型统一      │
              └──────────────────────────────────────────────┘
                    ▲                                  ▲
                    │  A. HTTP loopback（现状）         │
                    │  B. Unix Domain Socket（新增，可选）│
                    │  C. mgw CLI stdio（新增，补位）    │
                    └──────────────────────────────────┘
```

**用户说的「CLI 对接模式」，在这张图里对应三个不同的位置**：
- 位置 **②**（上行 CLI）：网关调厂商 CLI —— 这才是「最直接最短路径」成立的地方。
- 位置 **C**（下行 CLI）：工具调 `mgw` —— 这是「无缝衔接」的落点，但只在特定工具类型上需要。
- 位置 **B**（传输层）：把 HTTP 换成 UDS —— 这是唯一能真正缩短下行路径的改动。

---

## 2. 上行：API 与 CLI 的风险 / 稳定性对比（用户担忧的具体化）

### 2.1 用户担心的「风险与不稳定」，在代码里能对应到四类具体机制

这些不是泛泛而谈，每一条都有参考项目的代码证据（`03` 号文档 §4、§7.3）：

| # | 风险类型 | 具体表现（有代码证据） | 换 CLI 能否解决 |
|---|---|---|---|
| **R1** | **协议无契约、随时可变** | DSH 插件一个仓库里并存 **3 套消息序列化 + 5 套 SSE 消费**（`03` §7.3），因为每家产品的线格式都不同且会变：qoder 是「信封套 OpenAI SSE」（`src/qoder-envelope.ts:64-140`）、trae 是「非标准 SSE 事件格式，`event:` + `data:` 跨行累积」（`src/trae.ts:1540`）。连模型 id 都会漂移：`deepseek-v4-flash` 的 IDE 列表 id 与后端实际注册 id 不一致（`src/llm-adapter.ts:17-23` 注释） | ❌ **不能**。只要还在逆向内部 HTTP，协议就还在你手上维护 |
| **R2** | **凭据生命周期复杂** | OAuth token 需续期，DSH 里 `RefreshScheduler` + `refreshAll` 两套机制并存且互相脱节（`02` §3.3）；续期定时器只在启动时有可续期账号才创建，之后新登录的账号**永不自动续期**（`02` §9 补充） | ⚠️ **部分**。用厂商 CLI 时凭据由官方客户端自己管，但**网关就失去了对凭据的控制**（与铁律 1 冲突，见 §5） |
| **R3** | **风控画像** | 网关是**无人值守、非交互、高并发**的调用方；而账号风控恰恰把这种画像当信号 | ❌ **不能**。换成"调 CLI"如果仍是自动化高频，画像一样 |
| **R4** | **非技术性因素** | 条款约束等 —— **按用户 2026-09-24 指示，本次不纳入考量**，不作为方案取舍依据。此处仅保留「它会以什么技术形态出现」：账号被上游停用 → 表现为认证失败 → 由我们的失败计数 `C` 与冷却机制接管 | — **不评估**（用户指示） |

### 2.2 反过来：官方 API 恰恰是最稳定的形态

| 维度 | 官方 API | 逆向内部接口 | 厂商官方 CLI |
|---|---|---|---|
| 契约 | ✅ 版本化、有文档、有变更通知 | ❌ 无契约，随客户端版本变 | 🟡 有，但 CLI 的 stdout 格式**不是稳定契约** |
| 认证 | ✅ 明文 API Key，长期有效 | ❌ OAuth token 需续期 | 🟡 凭据在客户端内部 |
| 限流 | ✅ 明确配额 | ❌ 隐藏风控 | 🟡 隐藏 |
| 与铁律 1 相容 | ✅ 明文 Key 存本地 YAML | ⚠️ 凭据形态复杂 | ⚠️ **凭据在 CLI 自持 → 网关无法明文配置**（工程约束，非合规） |

**→ 结论：风险与不稳定的根源是「凭据来源 + 契约来源」，不是「API 这个形态」。**
**所以「除了 API 还要有 CLI」这个方向对，但定位必须修正**：CLI 上游适配器**不是 API 的更优替代**，而是**API 不存在时的唯一补位**。

### 2.3 上行 CLI 适配器的定位（建议）

| 项 | 设计 |
|---|---|
| 落点 | `model_gateway/adapters/cli_out.py`（与 `openai_out.py` 同层，**新增第三个协议族适配器**） |
| 触发条件 | **仅当**某厂商「只提供 CLI、不提供官方 API」，且**该 CLI 支持 headless / 非交互模式** |
| 默认状态 | **默认关闭**（`Resource.transport = "api"` 为默认；`transport = "cli"` 需显式配置） |
| 凭据 | **优先走环境变量注入的 API Key**；若该 CLI 只认自持凭据，需先明确它落在铁律 1「本地明文配置或环境变量」的哪一侧，再决定是否启用 |
| 与现有架构的接缝 | 已就绪：`adapters/base.py` 是空的抽象层（只有 5 行 docstring，**无 ABC**），`Resource.protocol` 字段**全仓无消费点**（v1 已登记为缺陷 B2）；`main.py:95-105` 对所有资源一律构造 `OpenAIOutAdapter`。→ 加 `cli_out.py` 需要**同时补上适配器分派**（这是既有欠债，不是本次新增） |

**⚠️ 诚实评估**：CLI 上游**并不比 API 更稳定**。它同样面对协议易变、风控、额度耗尽；它只是把「协议逆向」换成「stdout 解析」，把不稳定的位置挪了个地方。它唯一的真实价值是**覆盖那些不提供公开 API 的平台**。

---

## 3. 下行：CLI 作统一入口的设计

### 3.1 先做分类：哪些工具真的需要 CLI？

「任何工具安装了 CLI 无缝衔接」这句话要成立，前提是工具**有能力调用外部命令**。按接入机制把本机 AI 工具分成四类：

| 类型 | 接入机制 | 是否需要 `mgw` CLI | 最短路径 |
|---|---|---|---|
| **A. 自定义 OpenAI 兼容 base_url** | 在设置里填 `base_url` + Key | ❌ **不需要**。填 `http://127.0.0.1:8300/v1` 就是最短路径（一跳 loopback） | HTTP loopback |
| **B. 只能改环境变量** | 如 `ANTHROPIC_BASE_URL` / `*_API_KEY` | ❌ 不需要。但**需要 CLI 帮你把环境变量写对**（`mgw setup` 的价值） | HTTP loopback |
| **C. 支持「命令型 / 脚本型 provider」** | 配置一个 shell 命令作为模型来源 | ✅ **需要**。这是 CLI 唯一不可替代的场景 | 工具 → spawn `mgw` → 网关 |
| **D. 只支持自家内置 provider** | 无外部 provider 接口 | ❌ CLI 也救不了。唯一路径是宿主插件（**形态不同，属另一议题**） | — |

**⚠️【未验证】**：A/B/C/D 各类具体有哪些工具、各自的确切配置字段 —— **本次未做实测取证**（用户要求非必要不取网络资料，且本机无法逐工具验证）。**在落地 `mgw setup` 前，必须先对目标工具逐个实测其接入机制**，否则会写出错的配置片段。

**→ 由此得出 `mgw` 的真实价值排序（诚实版）**：

| 价值 | 层 | 说明 |
|---|---|---|
| ⭐⭐⭐ | **配置注入** | `mgw setup <tool>` —— 这是「无缝衔接」的真正落点，对 A/B/C/D 全类型都有用 |
| ⭐⭐⭐ | **模型目录** | `mgw models` —— 把「网关已生效模型」变成人可复制 / 机器可读的清单 |
| ⭐⭐ | **诊断** | `mgw doctor` —— 自检端口、配置、令牌、**可服务模型数**（能提前发现 §4.1 那个坑） |
| ⭐ | **stdio 通道** | `mgw run` —— 只对类型 C 有用；对 A/B 是**增加一跳**，不应推荐 |
| ❌ | **"更快的通道"** | **不存在**。见 §3.3 |

### 3.2 `mgw` 命令面设计

**现状【代码】**：`pyproject.toml` **没有 `[project.scripts]`** 段 → 目前项目**没有任何命令入口**，只能 `python -m model_gateway.main`。

建议新增：

```toml
[project.scripts]
mgw = "model_gateway.cli:main"
```

命令面（全部只依赖标准库 + 已有的 `httpx`/`pyyaml`，不引入新依赖）：

| 命令 | 作用 | 读什么 | 写什么 |
|---|---|---|---|
| `mgw status` | 网关状态、版本、资源数、**可服务模型数**、在途请求 | `GET /health` + `GET /admin/api/status` | — |
| `mgw models [--json\|--md\|--csv] [--servable-only]` | 模型清单（默认人可复制的 Markdown 表格） | `GET /v1/models`（**需令牌**）或 `GET /admin/api/config` | — |
| `mgw setup <tool> [--write]` | 打印（默认）/ 写入（`--write`）该工具的接入配置片段 | `GET /admin/api/config`（取端口/令牌） | **默认只打印**；`--write` 才落盘，且**仅写用户家目录**（见 §5 铁律冲突） |
| `mgw run [--model M] [--stream]` | stdio 通道：stdin 收 OpenAI 请求 JSON，stdout 吐 OpenAI 响应/SSE | `POST /v1/chat/completions` | — |
| `mgw serve` | 前台启动网关（等价 `python -m model_gateway.main`） | — | — |
| `mgw doctor` | 自检：端口可达 / 配置校验 / 令牌有效 / **每个模型是否可服务** | 全部 | — |

**关键设计约束**：
1. **`mgw` 不承载调度**。它必须是**瘦客户端**，所有请求转发给网关。理由见 §3.4。
2. **默认只读**。除 `mgw serve` 和 `mgw setup --write` 外，全部命令不写任何文件。
3. **退出码与 `model_gateway.main` 对齐**（0 正常 / 2 配置校验失败 / 3 已有实例）。

### 3.3 传输层：HTTP loopback 还是 Unix Domain Socket？

| 方案 | 路径长度 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| **A. HTTP loopback（现状）** | 工具 → TCP 127.0.0.1 → uvicorn | 零改动、全工具兼容、`curl` 可调试 | 过一遍 TCP/IP 栈 | ✅ **保持默认** |
| **B. Unix Domain Socket** | 工具 → UDS → uvicorn | 省掉 TCP/IP 栈；不占端口；文件权限可控 | **多数工具不支持自定义 socket 路径** | ✅ **作为可选增强**（`mgw` 与网关节点的本地通道用它，对外仍开 HTTP） |
| **C. `mgw` stdio** | 工具 → fork/exec → `mgw` → (A 或 B) → 网关 | 覆盖类型 C 工具 | **比 A 多一跳 + 一次进程启动** | ⚠️ **仅在类型 C 用** |
| **D. 自定义二进制协议** | — | — | 新增故障面、不可调试、违背「纯本地明文」的简洁性 | ❌ **不做** |

**B 方案的可行性【实测确认】**：`uvicorn` 版本 `0.52.4`，`uvicorn.Config.__init__` 签名**包含 `uds: str | None = None` 参数**（本机 `inspect.signature` 实测）。→ 只需在 `main.py` 的 `uvicorn.Config(...)` 增加一个可选 `uds` 参数即可，**改动量约 3 行**。

**关于「最直接最稳定最短路径」的诚实量化**：以本机 loopback 为例，一次 HTTP 往返的开销在**亚毫秒级**；而网关端到端延迟由**上游厂商 API 主导（几百毫秒～数秒）**——相差 2～3 个数量级。**所以「缩短传输路径」对用户感知几乎没有影响。**「最稳定」的达成方式不是换传输，而是**让网关别挂**：单实例锁（`core/instance_lock.py`）、配置热重载失败保留旧快照（`main.py:107-115`）、请求内故障切换续跑（`core/scheduler.py`）——**这些都已经有了**。

### 3.4 一条硬约束：`mgw` 绝不能自己跑调度

**不能**让 `mgw run` 直接 import 网关的调度内核、在 CLI 进程内独立完成选路/重试/切换。原因：

网关的核心资产是**有状态的中枢能力**——冷却状态、连续失败计数 `C`、在途计数 `in_flight`、跨请求切换历史、用量统计。这些状态**只能有一份**：

- `ResourceManager.registry`（`core/resources.py:70`）按 `(rid, vendor_model)` 全局唯一；
- `pick_and_acquire` 的「集内在途最少者承接」依赖 `in_flight` 的**原子递增**（`resources.py:143`，同一同步段完成，无 `await`）；
- `C` 是**跨请求累计**的（`resources.py:162-165`），成功才清零。

**如果 `mgw` 进程内再跑一套调度，就等于出现第二份 `C` / `in_flight` / 冷却状态** → 「容错」退化成「每个进程各自容错」，「模型统一」退化成「每个入口各有一套映射」。

**→ 结论：`mgw` 一律走 HTTP/UDS 转发到唯一的中枢进程。这是硬约束，不是性能取舍。**

---

## 4. 模型信息下发与软件内切换

### 4.1 ⚠️ 先修一个当前正在发生的真实问题（本机实测）

**实测命令**（2026-09-24，网关运行中）：

```bash
$ curl -s http://127.0.0.1:8300/health
{"status":"ok","version":"0.1.0",...,"resources":1,"system_models":7,"access_tokens":2}

$ curl -s http://127.0.0.1:8300/v1/models -H "Authorization: Bearer <tok>"
{"object":"list","data":[
  {"id":"sensenova-6.8-flash-lite",...,"endpoint":"chat","group":"通用"},
  {"id":"deepseek-v4-flash",...},{"id":"deepseek-v4-pro",...},
  {"id":"glm-5.2",...},{"id":"kimi-k3",...},
  {"id":"sensenova-u1-fast",...,"endpoint":"images","group":"图像生成"},
  {"id":"sensenova-u1.5-lite",...,"endpoint":"images","group":"图像生成"}]}

$ curl -s -X POST http://127.0.0.1:8300/v1/chat/completions \
    -H "Authorization: Bearer <tok>" -H 'Content-Type: application/json' \
    -d '{"model":"deepseek-v4-pro","messages":[{"role":"user","content":"hi"}],"max_tokens":8}'
{"error":{"message":"无可用资源；原因：无可用资源","type":"gateway_error",
          "code":"NO_RESOURCE","system_model":"deepseek-v4-pro"}}
```

**对照配置【代码】**：`data/config.yaml` 里 `resources` 只有 **1 条**，而 7 个 `models` 的 `resources` 数组**全部为空**。

| 观测 | 含义 |
|---|---|
| `/v1/models` 下发 **7 个模型** | 端点只按 `m.enabled` 过滤（`api/openai_compat.py:42`），**不看该模型有没有可用资源** |
| 调用任一模型 → `NO_RESOURCE` | `ResourceManager.pools[name]` 为空（`resources.py:125-127`） |
| 结论 | **`/v1/models` 下发的是一份「选中即失败」的清单** |

**→ 这就是用户诉求「把网关开启生效的模型信息提供给对接软件」当前会踩的坑**：软件拿到的清单里每一个都是死路。**必须先区分「已启用」与「可服务」。**

**修复建议（最小改动）**：`api/openai_compat.py:36-44` 的列表构造，改为按「该模型在当前配置下**至少有一个 available 资源**」过滤，或保留但**显式标注**：

```python
data = []
for m in runtime.config.models:
    if not m.enabled:
        continue
    pool = runtime.resources.pools.get(m.name) or []
    servable = any(r.available() for r in pool)
    data.append({..., "servable": servable})   # 或：只下发 servable=True 的
```

> ⚠️ **程序性提醒**：`/v1/models` 的响应字段属于**对外契约**，按铁律 4「无依据自创禁止」，新增字段前需先入 PRD。

### 4.2 三级下发设计

| 级 | 形态 | 面向 | 内容 | 现状 |
|---|---|---|---|---|
| **L1** | `GET /v1/models` | 支持模型发现的客户端 | OpenAI 标准字段 + **可服务标记** + 元数据（`context_window` / `max_output` / 模态 / 推理档位 / 默认参数） | ⚠️ **只有 6 个字段**（`id`/`object`/`created`/`owned_by`/`endpoint`/`group`），元数据一个都没下发；而 `EnumEntry`（`enums/matcher.py:17-49`）**已经存了 16 个字段** |
| **L2** | `mgw models [--json\|--md\|--csv]` | 人 + 脚本 | 同上，人可复制的表格 / 机器可读 JSON | ❌ 不存在 |
| **L3** | `mgw setup <tool> [--write]` | 工具配置 | 直接生成该工具的配置片段（含 `base_url`、令牌、**模型 id 列表**） | ❌ 不存在 |

**L1 的元数据来源已就绪**（`enums/matcher.py:26-35`）：`vendor` / `context_window` / `max_output` / `image_input` / `video_input` / `audio_input` / `reasoning` / `effort_levels` / `params_default`。**只是端点没往外发。**

**⚠️ 一个必须遵守的规则**：枚举池里有**未取证条目**（属性为 `None`），下发时应**省略字段**而不是输出 `null` —— 否则客户端可能把 `null` 误判为「不支持」。

### 4.3 软件内切换模型

用户诉求「在软件内使用时候可以需要切换不同模型」，落地方式取决于工具类型：

| 工具类型 | 切换机制 | 网关侧要提供什么 |
|---|---|---|
| A / C（支持模型下拉） | 客户端自己拉 `/v1/models` 渲染下拉 | **L1 修好 + 元数据补全**（否则下拉里是死模型） |
| B（只能配环境变量） | 没有下拉，只能改配置重启 | **L2 表格**（人可复制）+ `mgw setup` 重写环境变量 |
| 全部类型 | 网关侧「默认模型」 | 可选：`mgw use <model>` 写本地默认，供 `mgw run` 不带 `--model` 时使用 |

**关于网关侧的「虚拟模型名 / 策略路由」**：不建议。与既有定论 Q18-③「调度参数全局唯一·一套机制管控所有模型」及 Q23-②「配置参数范围维持现状四类、零新增字段」有张力，需先翻案。

---

## 5. 与项目铁律的一致性检查

| 建议 | 铁律 1（全明文配置·纯本地·无远程更新） | 铁律 4（无依据自创禁止） | 判定 |
|---|---|---|---|
| `mgw` CLI（瘦客户端） | ✅ 纯本地，无远程 | ⚠️ 新增对外命令面 → 需先入 PRD | ⚠️ 程序性 |
| UDS 传输（`uvicorn uds=`） | ✅ 纯本地，且**更彻底**（不出网卡） | ⚠️ 需入 PRD | ✅ 相容 |
| `mgw setup --write` 写工具配置 | ✅ 明文 | ⚠️ **`mg-directory-layout.mdc` 明令项目内 `.claude/` `.trae/` `.workbuddy/` 等 `.xxx` 目录"一律不维护、不更新、不写入"** → **只能限定为「仅打印」或「仅写用户家目录」** | 🔴 **须限定边界** |
| `adapters/cli_out.py`（上行 CLI） | 🔴 **凭据必须走环境变量 API Key**；若读厂商 CLI 自持凭据 → 与铁律 1 直接冲突 | ⚠️ 需入 PRD | 🔴 **潜在冲突** |
| `/v1/models` 增加 `servable` / 元数据字段 | ✅ | ⚠️ 对外契约字段须先入 PRD | ⚠️ 程序性 |
| `mgw` 进程内跑调度 | — | — | ❌ **一律不做**（§3.4） |

---

## 6. 分期落地

### P0 — 立即可做（纯加法 / 修缺陷）

| # | 动作 | 落点 | 依据 |
|---|---|---|---|
| P0-1 | **修 `/v1/models` 下发死模型**：增加「可服务」判定（过滤或标注） | `api/openai_compat.py:36-44` | §4.1 本机实测 |
| P0-2 | **新增 `mgw` 命令入口**（`pyproject.toml` 加 `[project.scripts]`）+ `mgw status` / `mgw doctor` | `pyproject.toml`、新建 `model_gateway/cli.py` | 现状无任何命令入口 |
| P0-3 | **`mgw models`（L2 表格）**：人可复制 + `--json` | 同上 | 客户端不保证读 `/v1/models` |
| P0-4 | **`/v1/models` 补元数据**（`context_window`/`max_output`/模态/推理档位/默认参数），**未取证条目省略字段不下发 null** | `api/openai_compat.py`（源：`enums/matcher.py:17-49`） | 元数据已存但没发 |
| P0-5 | **实测目标工具的接入机制**（A/B/C/D 分类落地），产出真实配置片段 | `docs/changes/` 实测记录 | §3.1【未验证】 |

### P1 — 架构准备

| # | 动作 | 落点 | 依据 |
|---|---|---|---|
| P1-1 | **`mgw setup <tool>`（L3）**，默认只打印；`--write` 仅限用户家目录 | `model_gateway/cli.py` | §5 铁律冲突 |
| P1-2 | **UDS 可选监听**（`uvicorn.Config(uds=...)`），默认关闭 | `main.py:307-308` | uvicorn 0.52.4 实测支持 |
| P1-3 | **补适配器抽象层（既有欠债）**：`adapters/base.py` 目前只有 5 行 docstring、无 ABC；`Resource.protocol` 字段全仓无消费点；`main.py:95-105` 一律构造 `OpenAIOutAdapter` | `adapters/base.py`、`main.py:95-105` | v1 已登记为缺陷 B2 |
| P1-4 | **`mgw run`（stdio 通道）**，仅供类型 C 工具 | `model_gateway/cli.py` | §3.1 |

### P2 — 需用户决策

| # | 动作 | 卡点 |
|---|---|---|
| P2-1 | **`adapters/cli_out.py` 上行 CLI 适配器** | 🔴 凭据必须走环境变量 API Key；默认关闭；需先确认目标平台「是否只提供 CLI」 |
| P2-2 | 是否允许网关做「虚拟模型名 / 策略路由」 | 与 Q18-③ / Q23-② 定论有张力，**需翻案** |

---

## 7. 未验证清单（诚实标注）

| # | 项 | 卡在哪 |
|---|---|---|
| 1 | 目标工具（Trae / Cursor / Cherry Studio / Claude Code / DSH 等）各自的确切接入机制分类（A/B/C/D）与配置字段 | **未实测**。用户要求非必要不取网络资料；本机无法逐工具验证。**P0-5 必须先补这一课** |
| 2 | 各工具是否真的「不读 `/v1/models`」 | v1 用网络资料得出该结论，**本次未独立复核**；`data/gateway.log` 只能证明**本机从未有工具读过**（0 次调用），不能证明工具**不支持**读 |
| 3 | 类型 C（命令型 provider）具体是哪些工具、其 stdio 契约是什么 | **完全未验证**。`mgw run` 的 stdio 格式需要按目标工具的真实契约来定，不能自创 |
| 4 | UDS 方案在 macOS 上的实际收益（相对 loopback TCP） | 未做基准测试。**推断**收益在亚毫秒级，对用户感知无影响 |
| 5 | `mgw setup` 要写的目标文件路径（各工具的配置位置） | 未验证；且受 `mg-directory-layout.mdc` 约束，**必须先确定边界** |

---

## 8. 证据附录

### 8.1 本仓库代码（一手）

| 事实 | 位置 |
|---|---|
| 无 `[project.scripts]`（无命令入口） | `pyproject.toml`（全文 32 行，无 `scripts` 段） |
| `/v1/models` 仅 6 字段、只按 `enabled` 过滤 | `api/openai_compat.py:36-44` |
| 模型解析 404 / 禁用 404 逻辑 | `api/openai_compat.py:47-72` |
| 枚举池 16 字段（元数据已存） | `enums/matcher.py:17-49` |
| `/v1/*` 需令牌；`/health`、`/admin/*` 免鉴权 | `api/auth.py:15,42-44` |
| 管理端免鉴权（Q18-①） | `api/admin.py:14` |
| 适配器抽象层为空 | `adapters/base.py:1-5` |
| 一律构造 `OpenAIOutAdapter` | `main.py:95-105` |
| `uvicorn.Server` 化启动（可加 `uds`） | `main.py:307-310` |
| 资源池选路 + 原子 `in_flight` | `core/resources.py:120-144` |
| `C` 跨请求累计 / 成功清零 | `core/resources.py:162-168` |
| 注册表按 `(rid, vendor_model)` 全局唯一 | `core/resources.py:70` |
| 出站体构造（参数注入 + 推理注入） | `core/scheduler.py:223-232` |
| 推理三级合并 | `core/ir.py:28-55` |
| 推理注入硬编码单方言（商汤口径） | `core/ir.py:94-111` |
| `apply_model_params`（工具传参 > 网关设置 > 厂商内置） | `core/ir.py:58-70` |
| `Resource` 字段（含 `protocol` / `access_mode`） | `config/schemas.py:109-129` |
| `SystemModel` 字段（含 `params` / `resources[]`） | `config/schemas.py:150-191` |
| 调度参数 x/y/m 全局唯一 | `config/schemas.py:68-81` |

### 8.2 本机实测（2026-09-24）

| 观测 | 命令 / 来源 | 结果 |
|---|---|---|
| 网关运行中 | `curl /health` | `{"status":"ok","version":"0.1.0","resources":1,"system_models":7,"access_tokens":2}` |
| `/v1/models` 下发 7 模型 | `curl /v1/models -H "Authorization: Bearer <tok>"` | 7 条，字段仅 6 个 |
| 7 模型全部不可服务 | `curl -X POST /v1/chat/completions ... model=deepseek-v4-pro` | `{"code":"NO_RESOURCE"}` |
| 配置：1 资源 / 7 模型 / 全部 `resources: []` | `data/config.yaml` | 已确认 |
| `/v1/models` 历史调用 **0 次** | `data/gateway.log`（104,749 行）逐行统计 | `"GET /v1/models"` **零命中** |
| `/v1/chat/completions` 历史调用 **2 次** | 同上 | 仅 2 次 |
| 管理面 `/admin/api/status` **32,583 次** | 同上 | 占全部请求流量第一 |
| 静态 UI 资源各 5,429 次 | 同上 | 说明流量几乎全是管理界面自己 |
| uvicorn 支持 `uds` | `inspect.signature(uvicorn.Config.__init__)` | `uds: 'str \| None' = None`，版本 `0.52.4` |

> **实测推论**：网关**至今没有任何外部 AI 工具真正接入过**（`/v1/models` 0 次、`/v1/chat/completions` 2 次、其余全是管理界面自用）。→ 所以「CLI 对接模式」的优先级应排在**「先把第一个外部客户端端到端接通」之后**；在接通之前，本文件的价值是**设计就绪**，不是立即施工。

### 8.3 跨文档引用

| 引用 | 内容 |
|---|---|
| `02` §3.3 / §9 | 凭据续期机制的两套并存与脱节缺陷 |
| `03` §4.1 / §4.3 / §7.3 | 各产品协议差异、SSE 转换、同源实现分叉 |
| `03` §6 | 可复用性判定矩阵 |
| `_v1-archive/08-宿主原生Provider机制横向调研.md` | 宿主 provider 机制横向对比（**v1 材料，含网络来源，引用前须复核**） |
| — | 三家 ToS / 条款取证已按用户指示**不纳入考量**，本文件不再引用 |
