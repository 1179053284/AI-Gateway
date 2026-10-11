# 04 · 网关现状盘点与「API 对接模式 vs CLI 对接模式」调研（定稿）

> 类型：**调研输入（定稿）**，不是需求真相。
> 依据 `AGENTS.md` 铁律 4「无依据自创禁止」与 `mg-00-first-principles.mdc` 硬性要求 1/6：本报告的全部结论只是**候选方案与证据**，任何落地项（新配置字段 / 新端点 / 新 UI / 新模块）必须经用户确认后写入 `docs/specs/`，再进入实施。
> 代码事实：全部来自真实读取，逐条附 `文件路径:行号`；未验证项一律显式标注「**未验证**」。
> 业界事实：区分「一手（官方文档 / 官方仓库）」与「二手（社区帖 / 博客 / 媒体报道）」，逐条给可点击 URL 并标注抓取时间（本报告抓取日 **2026-09-22**）。
> 只读约束：本次调研**未修改** `Model-Gateway/` 下任何既有文件；原 draft 留痕于 `docs/research/drafts/04-网关现状与API-CLI双模式调研.md`。
> 修订依据：`docs/research/drafts/verify-04-gateway.md`（独立核验报告，可信度 B+，219 条引用零越界、23 条 URL 零编造）。

---

## 结论先行（摘要，≤15 行）

1. **网关现状 = 纯 HTTP 单进程 OpenAI/Anthropic 兼容网关**，对外 4 个 `/v1` 端点 + **14 个 `/admin/api` 端点** + `/health` + 静态界面；`/v1/*` 需 Bearer/x-api-key，`/admin/api/*` 与 `/health` 免鉴权（`api/auth.py:15-16`、`api/auth.py:42`）。
2. **领域模型是三层扁平**：`resources[]`（资源 = 厂商 + Key）→ `models[].resources[]`（映射条目 = 资源 id + 厂商模型 id + 可选资源级推理默认）→ `models[]`（系统模型 = 对外统一名，有序池 = 优先级）。调度状态挂在**映射条目** `(resource_id, vendor_model)` 上，展示/统计按**资源**聚合。
3. **参数三级优先级已落地**：`工具传参 > 网关设置(SystemModel.params) > 厂商内置`，实现在 `core/ir.py:58-70 apply_model_params`，由 `core/scheduler.py:223-232 _out_body` 每次尝试重算（切换资源后自动按新资源重算）。
4. **最关键的结构性发现（决定 CLI 模式怎么做）**：`adapters/base.py` **仅一段 docstring（5 行），无任何代码**，没有抽象基类/Protocol（`adapters/base.py:1-5`）；`anthropic_out.py` / `gemini_out.py` 各只有 1 行 docstring 占位；`Runtime._apply` 对**所有**资源一律构造 `OpenAIOutAdapter`（`main.py:95-105`），`resource.protocol` 字段**从未参与分发**（全仓 grep 仅见 schema/前端赋值，无消费点）。→ **抽象层在 spec 层面已声明、在代码层面缺失**（`tech-design.md:162-163` 已定 `call()/list_models()` 契约与「按资源 `protocol` 字段选择」，代码尚未落实）。
5. **命名冲突必须先行处理**：项目已用 `access_mode: api | plan` 表示**凭据类型**（按量 Key / 订阅套餐，`config/schemas.py:18,124`，UI 文案见 `web/static/js/pages/resources.js:240,779-780`）。用户诉求里的「API 对接模式 / CLI 对接模式」是**传输/通道轴**，二者不可复用同一字段，否则语义炸裂。
6. **B 段结论（已按核验修正）**：把「订阅账号授权 → 转成网关可调资源」这条路的风险，**核心不是协议易变，而是服务条款与账号风控**。Anthropic 官方文档原文禁止**第三方开发者**在自己的应用里提供 Claude.ai 登录、代表用户路由订阅凭据、或收集/存储/中转会话 token；**但同一页紧接着明确：不阻止终端用户在自己的机器上用未修改的官方二进制 + 自有订阅登录**。故「CLI 模式同样违规」是过度推断，准确表述见 §B.2。
7. **C 段结论**：业界**确实存在**「用 CLI 当模型接入层」的真实先例（CLIProxyAPI，包装 Claude Code/Codex/Grok/Gemini CLI 为 OpenAI 兼容 API）。但该先例恰恰是各家正在封堵的方向。**CLI 模式能改善「协议稳定性」，不能消除「合规/风控」风险**——这一点必须诚实告诉用户。
8. **C 段推荐**：主链路走「**网关自带本地 CLI 作为统一入口 + 复用现有 HTTP 入站**」（零客户端改造、最短路径），把「CLI 作为**上游**适配器」作为**受限可选**能力（仅在资源确有官方 CLI 且合规允许时启用）。
9. **D 段结论（最容易被忽视、但影响最大）**：Trae / Cherry Studio / Cursor 的自定义模型配置**基本都是"手填模型 ID"，不读 `/v1/models`**（Trae：**官方社区用户教程，二手**；Cherry Studio：官方文档，一手）。因此「下发清单」不能假设客户端会拉取——**必须同时提供人可复制的一页清单**。Claude Code 是唯一有官方开关的（`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY`，默认关闭，仅 Anthropic 兼容网关）。
10. **D 段机会点（低成本高收益）**：`EnumEntry` 已经存了 `context_window / max_output / image_input / video_input / audio_input / reasoning / effort_levels / params_default`（`enums/matcher.py:17-49`），但 `/v1/models` **一个都没下发**（只返回 `id/object/created/owned_by/endpoint/group`，`api/openai_compat.py:39-44`）。补齐扩展字段是**纯加法**（但其中 Anthropic 2 条属性未取证，须按 §E5 处理）。
11. **落地建议**：分四期——① 模型清单补齐（纯加法、零风险）；② 本地 CLI 入口（低风险）；③ 抽象层补齐（**落实 spec 既有契约，非自创**）；④ CLI 上游适配器（**合规 + 铁律 1 双重前置，默认不启用**）。**每条建议的铁律关系已在正文显式标注**。
12. **三个"必须先问用户"的决策点**：① 「账号授权提取内部模型」具体指哪家、哪种授权？（决定 B 段风险等级）；② 新增轴叫什么（建议 `transport: http|cli`，与 `access_mode` 解耦）；③ 是否接受"CLI 上游模式无法规避 ToS 风险"这个事实前提。
13. **不确定项**：Codex CLI `config.toml` 字段（二手多源一致，未在官方文档验证）；Cursor 是否真会拉 `/v1/models`（仅二手内容农场来源）；ACP 是否将定义模型清单（README 未定义，仅见 unstable `providers/*` 提交线索）；ACP「默认 stdio」（官方 README **未载明**）；Cherry Studio 部分版本是否有"获取模型列表"按钮（官方文档口径为手填）；`shutdown_date` 是否为"2026 新增"（字段存在已确认，新增时间无据）。
14. **一个与 `ACTIVE.md` 的冲突提示**：`docs/changes/ACTIVE.md:27` 记录「T6 项目无 git 仓库（`git status` → fatal）」，但实测 `git status` 正常返回 `On branch main … nothing to commit`，根目录实际存在 `.git/`（`ls -la` 实测：`.git/` 目录 mtime **2026-09-22**，`.git/index` mtime **2026-09-18**）。ACTIVE.md 该条已过期，建议一并校正（本报告未改任何文件）。
15. **铁律总览**：21 条落地建议中，**明确冲突 1 条（适配器接口签名，需翻案或改按 spec 契约）**、**潜在冲突 3 条（`mgw setup` 写入边界、CLI 上游凭据 vs 铁律 1、`/v1/models` 新增字段的程序性）**、**需用户翻案 1 条（模型级策略路由）**、其余 16 条相容。逐条见「落地建议与分期路线」。

---

## 修订记录

> 本节记录本定稿相对 draft 的全部修正。共 **27 条**（E1–E27），其中 P0 事实错误 6 条、P1 过度推断/依据不足 8 条、P2 瑕疵 6 条、遗漏 7 条；另含内部矛盾 4 条（C1–C4，与 E2/E5/E6/E17 同源）。来源：`verify-04-gateway.md`。
> **代码事实层未被改动**——核验确认 draft 的 219 条 `路径:行号` 引用零越界、网关端点/数据结构/故障切换/参数优先级描述准确、23 条外部 URL 零编造，本定稿予以保留。

| # | 修订条目 | 错误性质 | 修正要点 |
|---|---|---|---|
| E1 | `data/config.yaml` 系统模型数量 | **事实错误** | 「6 个系统模型」→「**7 个**」，补 `sensenova-u1.5-lite`（`data/config.yaml:122-130`，`endpoint: images`，`group: 图像生成`）。资源 1 个、令牌 2 个的描述正确，保留 |
| E2 | `/admin/api` 端点数（摘要 vs 表格自相矛盾） | **事实错误 / 内部矛盾** | 「15 个」→「**14 个**」（`api/admin.py` 实测 14 条路由）；`/health` 与 `/` 单列，不计入 `/admin/api` |
| E3 | PRD 术语表定位 | **事实错误** | `prd.md:113-123`（实为 FR-1.3~FR-1.8）→ **`prd.md:47-68`**（§2 术语与核心概念） |
| E4 | PRD 接入模式定义行号 | **事实错误** | `prd.md:31`（实为「首发厂商」）→ **`prd.md:30`**；归属由「术语表 §2」更正为「**§1.4**」 |
| E5 | 「内置 15 条…来源均为官方域取证」 | **事实错误 / 内部矛盾** | 条数与分厂商计数正确，但 `matcher.py:137` 注释明载 Anthropic 2 条「**属性未取证**」（仅 name/aliases/group/vendor）。补注；并新增「未取证条目应**省略字段**而非下发 null」的落地前置 |
| E6 | `adapters/base.py` 行数措辞 | **内部矛盾** | 「只有一行 docstring」→「**仅一段 docstring（5 行 = 4 行注释 + 1 空行），无任何代码**」。结论（无 ABC/Protocol）不变 |
| E7 | §B.2/§C.5 合规结论强于官方原文 | **过度推断（最需谨慎）** | **补引官方同页限定段**（"Nor does it prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription…"）；§B.2/§C.3/§C.5 结论全部改为「官方限制的是**第三方/网关代表用户中转订阅凭据**；**终端用户本机自用未修改官方二进制 + 自有订阅被明文允许**」 |
| E8 | §B.2 证据 3 选择性引用 | **过度推断 / 证据不完整** | 补引同源反向陈述（Anthropic 称文档变更为 "**docs clean up** that caused confusion"、"nothing was changing about Agent SDK usage with Max subscriptions"）；声明**不据此判定政策生效日** |
| E9 | §C.5「CLI 风控略优」未披露来源冲突 | **来源冲突未披露** | 该行改为「**方向存在来源冲突**」：`awesomeagents`（官方二进制身份校验可通过）↔ `woodchen §6.4`（非交互/自动化/高频画像本身是风控信号）。**无法判定孰强，标注未验证** |
| E10 | Trae 论坛帖分级 | **分级失当** | 「一手（官方社区官方教程）」→「**二手（官方社区用户教程，作者 `JasonShane` 头衔「社区捣蛋鬼」，非 TRAE 官方）**」；参考来源 #15 移入二手区。**内容本身全部核实无误，结论不变** |
| E11 | 「四家工具没有任何一个支持」 | **过度推断（无引证全称否定）** | → 「据本次调研所查文档，四者均未见此能力（**未穷尽验证**）」 |
| E12 | 「有意的宽进严出」 | **过度推断（意图归因）** | → 「该差异在代码中未见设计说明，**是否为有意设计需向用户确认**」 |
| E13 | ACP 段两处依据不足 | **过度推断** | (a)「默认 stdio」→「README **未载明**；据实现惯例推断，**未核实**」；(b) 删除非原文的 `"Zed-led model"`，改为官方原文「**Created by Zed**, grown by a community of editors and agents」（`zed.dev/acp`）+「developed openly by **JetBrains and Zed**」（`jetbrains.com/acp`） |
| E14 | 「2026 官方 schema 新增 `shutdown_date`」 | **过度推断（时间性断言无据）** | → 「官方**当前** schema 含 `shutdown_date`」（字段存在已核实，新增时间删除） |
| E15 | `.git/` mtime 实测值 | **事实错误** | 2026-09-18 是 `.git/index` 的 mtime；`.git/` 目录 mtime 为 **2026-09-22**。**核心矛盾成立**（ACTIVE.md T6 已过期） |
| E16 | `data/` 在 `.gitignore` 的依据 | **事实错误（依据错位）** | `config.example.yaml:3` → **`.gitignore:3`** |
| E17 | `data/config.yaml` 行区间截断 | **内部矛盾 / 瑕疵** | `1-120` → **`1-131`**（文件实测 131 行，`pricing: []` 收尾于 L131） |
| E18 | 页面命名过时 | **事实错误（命名）** | 「模型资源页」→「**资源池设置页**（原「系统模型」，`models.js:1` 自述，Q24 · 2026-09-05 定版）」；「模型资源」是 `resources.js` 对应的另一页 |
| E19 | grep 结论不完整 + 行号偏移 | **遗漏 / 瑕疵** | 补 `resources.js:1018`（`protocol: "openai",` 前端赋值）；附录行号 `1017` → **`1017-1018`** |
| E20 | 事件落盘 finally 引用不全 | **遗漏** | 补引 `scheduler.py:292-299`（非流式 `_execute` 的 `CancelledError → aborted` + `finally → _log`） |
| E21 | 扩展点分析漏 `config/presets.py` | **遗漏** | 新增扩展点条目：项目自述「新增厂商或 Plan 类型 = **仅加一条预设数据**」（`presets.py:6-8`、`tech-design.md:194`）→ 新增 `transport` 轴时预设注册表很可能需同步扩展 |
| E22 | 拟议适配器接口 vs `tech-design.md:163` | **铁律冲突（唯一明确冲突）** | `tech-design.md:163` **已声明** `async def call(resource, ir_request) -> IRResponse \| AsyncIterator[IREvent]` + `async def list_models(resource)`。草稿拟议 `chat_nonstream/chat_stream/images_generate/aclose` 与之不一致且未披露 → **改为落实 spec 既有契约**；若坚持草稿签名，须明确标注「**这是对 tech-design 的修订提案，需走 spec 变更流程并经用户翻案**」 |
| E23 | 低估既有依据 | **遗漏（表述偏保守）** | 补引 `tech-design.md:162`「`anthropic_out`（P1）/`gemini_out`（P2）：**按资源 `protocol` 字段选择**」→「补齐 protocol 消费点」属**落实既有设计**，非自创；同时修正 §A.5.1 判断为「**抽象层在 spec 层面存在、只在代码层面缺失**」 |
| E24 | 铁律检查表覆盖不全 | **遗漏** | 补 `mg-work-rules-redlines.mdc`（规矩 4 诚实必附证据 / 8 停手升层 / 12 零垃圾 / 13 Git 推送红线 / 14 提交前自检）与 `mg-directory-layout.mdc:10`（**AI 工具目录边界**）→ 直接补上冲突项 #8 的漏检 |
| E25 | CLI 上游凭据 vs 铁律 1 | **潜在铁律冲突（草稿未识别）** | 补入一致性检查表：CLI 上游天然依赖厂商 CLI 自持凭据（OAuth token / macOS 钥匙串 / `~/.codex/auth.json`），**不在网关明文配置或环境变量内** → 与铁律 1 存在张力。结论：「**若走厂商 CLI 自持凭据 → 冲突；若强制走环境变量 API Key（`--bare` 路径）→ 相容**」 |
| E26 | tech-design 与代码的校验缺口 | **遗漏** | 补记：`tech-design.md:191` 声明两项校验（资源 `preset` 须存在于预设注册表；资源 → vendor_model 须存在于配置或枚举池）——**`config/schemas.py:219-255` 实际均未实现**。属 doc/code 分歧，值得暴露 |
| E27 | 阶段 0.1 未处理"未取证条目下发语义" | **遗漏** | 新增前置条件：属性未取证条目（Anthropic 2 条）**省略字段**而非下发 `null`/空数组，避免客户端误判「不支持」 |

**内部矛盾（C1–C4）**：C1 = E2（端点数）、C2 = E6（base.py 行数）、C3 = E17（config.yaml 区间）、C4 = E5（取证范围）。均已在对应条目修正。

**核验反向确认（draft 的加分项，本定稿保留）**：无编造行号、无编造 URL、无把不存在文件/函数/字段当事实、无任何远程下发/自动更新/遥测类设计；对「未验证」的自标注整体诚实；已主动标注 #1/#6/#7/#14/#19 的程序性约束。

---

## A. 网关现状盘点

### A.0 一句话定位

单进程 asyncio 服务（FastAPI + uvicorn 单 worker），聚合多厂商多 Key 资源池，对外暴露**统一 OpenAI 兼容 + Anthropic 原生**入站 API，核心能力是**失败重试（m）→ 连续失败冷却（y）→ 切换续跑（同模型异资源）**，全明文配置、纯本地运行、无远程依赖。

运行形态（`tech-design.md:52-56`、`main.py:288-328`）：启动序列 = 加载配置校验 → 获取 `data/gateway.lock` 单实例锁 → 绑定端口；`/v1/*`、`/admin/api/*`、Web 界面**同端口分路径**（默认 `0.0.0.0:8300`）。

### A.1 对外端点清单

#### A.1.1 业务端点（`/v1/*`，需鉴权）

| # | 路径 | 方法 | 协议 | 鉴权 | 代码位置 |
|---|---|---|---|---|---|
| 1 | `/v1/models` | GET | OpenAI | Bearer / x-api-key / x-goog-api-key | `api/openai_compat.py:36-44` |
| 2 | `/v1/chat/completions` | POST | OpenAI 兼容（流式 + 非流式） | 同上 | `api/openai_compat.py:101-144` |
| 3 | `/v1/images/generations` | POST | OpenAI images | 同上 | `api/openai_compat.py:238-286` |
| 4 | `/v1/messages` | POST | Anthropic 原生（含流式） | 同上 | `api/anthropic.py:316-366` |

鉴权规则（`api/auth.py:15-16, 37-64`）：
- 豁免前缀 `("/health", "/admin/")`；**只有 `/v1/` 开头才走鉴权**。
- 令牌来源优先级：`Authorization: Bearer <v>` → `x-api-key` → `x-goog-api-key`（`api/auth.py:66-79`）。
- **未配置任何 `access_tokens` 时 `/v1` 全放行**，启动打印警告（`main.py:174-175`）。
- 错误体按入站协议分形：`/v1/messages` 用 Anthropic 格式，其余 OpenAI 格式（`api/auth.py:81-92`）。
- 说明：无 `allow_admin`、无管理端令牌门（`Q18-①` 已推翻终审结论，见 `tech-design.md:111`）——**这意味着同网段任意进程可读写配置、停止网关**（风险已由项目自身在 `tech-design.md:573` 诚实标注）。

#### A.1.2 管理端点（`/admin/api/*`，免鉴权）

> **修正（E2）**：本节实列 **14** 条 `/admin/api` 路由（`api/admin.py` 全仓 grep `@router.` 实测 14 条），与下表编号 1–14 一致。`/health` 与 `/` 不属 `/admin/api` 命名空间，单列于表末供参考。

| # | 路径 | 方法 | 用途 | 代码位置 |
|---|---|---|---|---|
| 1 | `/admin/api/status` | GET | 轻量状态（顶栏 5s 轮询） | `api/admin.py:110` |
| 2 | `/admin/api/overview` | GET | 总览一次取齐 | `api/admin.py:122` |
| 3 | `/admin/api/stats?days=` | GET | 看板五维聚合 | `api/admin.py:184` |
| 4 | `/admin/api/logs/requests` | GET | 请求流水（可筛 model/status/token） | `api/admin.py:224` |
| 5 | `/admin/api/logs/switches` | GET | 切换事件流水 | `api/admin.py:247` |
| 6 | `/admin/api/resources/test` | POST | 单资源/草稿连通性测试 | `api/admin.py:260` |
| 7 | `/admin/api/config` | GET | 读配置（Key 默认脱敏，`?reveal=1` 明文） | `api/admin.py:363` |
| 8 | `/admin/api/config` | PUT | 保存配置（自动补 ID/密钥 → 校验 → 原子写 → 热重载） | `api/admin.py:384` |
| 9 | `/admin/api/config/reload` | POST | 手动重载 | `api/admin.py:426` |
| 10 | `/admin/api/enums` | GET | 读枚举池（`model-enums.yaml` 或内置） | `api/admin.py:455` |
| 11 | `/admin/api/enums` | PUT | 写枚举池（全量替换） | `api/admin.py:465` |
| 12 | `/admin/api/presets` | GET | 厂商预设注册表 | `api/admin.py:507` |
| 13 | `/admin/api/system/stop` | POST | 优雅停机 | `api/admin.py:520` |
| 14 | `/admin/api/system/restart` | POST | execv 自重启 | `api/admin.py:536` |
| — | `/health` | GET | 健康检查（含配置警告、调度参数、资源/模型计数）**非 `/admin/api`** | `main.py:186-203` |
| — | `/` | GET | 静态管理界面（`StaticFiles(html=True)`）**非 `/admin/api`** | `main.py:212-214` |

**没有的端点**（对 D 段很关键）：`GET /v1/models/{id}`（单模型详情）不存在；没有任何"模型清单导出"端点。

### A.2 核心领域模型

#### A.2.1 三层关系

```
resources[]                      models[] (SystemModel)
┌──────────────────────┐         ┌───────────────────────────────────────┐
│ Resource             │         │ SystemModel                           │
│  id: res-xxxxxxxx    │         │  name:  deepseek-v4-flash  ← 对外统一名│
│  vendor: "DeepSeek"  │         │  group: "编程"                        │
│  preset: sensenova-* │         │  endpoint: chat | images              │
│  access_mode: api|plan│        │  enabled: true                        │
│  protocol: openai|...│         │  params: {temperature: 1, ...}        │
│  base_url            │         │  resources: [ ModelResource, ... ]    │
│  api_key (明文)       │         │        │                              │
│  account: "主账号"    │         │        │  resource: res-xxxxxxxx ─────┼──┐
│  enabled: true       │◄────────┼────────┘  model: deepseek-v4-flash    │  │
└──────────────────────┘         │           reasoning: {enabled, effort}│  │
         │                       │      (列表顺序 = 优先级)              │  │
         │                       └───────────────────────────────────────┘  │
         │ 1 资源 × N 模型 = N 个「映射条目」                                 │
         ▼                                                                  │
  运行态注册表（内存，不落盘）                                               │
  registry[(resource_id, vendor_model)] = ResourceState ◄────────────────────┘
    status: active|cooldown|disabled|invalid
    C: 连续失败计数（跨请求累计，成功清零）
    cooldown_until / in_flight / last_error
```

#### A.2.2 数据结构（Pydantic v2）

| 模型 | 字段 | 位置 |
|---|---|---|
| `Resource` | `id`(必填, `res-` 前缀自动生成) / `name`(备注) / `vendor`(自定义厂商名) / `preset` / `access_mode: "api"\|"plan"` / `protocol: "openai"\|"anthropic"\|"gemini"` / `base_url` / `api_key`(min_length=1) / `account` / `enabled`(strict bool) | `config/schemas.py:109-129` |
| `ModelResource` | `resource`(资源 id) / `model`(厂商侧模型 ID) / `reasoning: ReasoningDefault \| None` | `config/schemas.py:132-137` |
| `SystemModel` | `name` / `group` / `endpoint: "chat"\|"images"` / `enabled`(strict bool, 默认 true) / `params: dict` / `resources: list[ModelResource]` | `config/schemas.py:150-191` |
| `AppConfig` | `gateway` / `scheduling` / `error_rules[]` / `resources[]` / `models[]` / `pricing[]` / `warnings`(不落盘) | `config/schemas.py:206-255` |
| `GatewayConfig` | `host` / `port`(8300) / `max_concurrent_requests`(0=不限) / `attempt_timeout_seconds`(60) / `request_total_budget_seconds`(300) / `heartbeat_seconds`(15) / `retention_days`(7) / `access_tokens[]` | `config/schemas.py:46-65` |
| `SchedulingConfig` | `max_active_per_model`(x=2) / `fail_threshold`(y=2) / `retry_per_request`(m=3) / `retry_backoff_seconds`(0) / `quota_retry`(2) / `quota_backoff_base_seconds`(1.0) / `cooldown_seconds`(60) / `cooldown_seconds_plan`(18000) | `config/schemas.py:68-81` |
| `AccessToken` | `id` / `name`(用途标注) / `value` / `enabled` / `quotas`(P1 预留) | `config/schemas.py:33-43` |
| `ErrorRule` | `http` / `type` / `class`(ErrorClass 六类) | `config/schemas.py:84-95` |

**跨节校验**（`config/schemas.py:219-255`）：资源 id 唯一性、token id 唯一性、模型名唯一性、`models[].resources[].resource` 必须存在于 `resources[]`、images 端点配 `reasoning` → 警告并置 None。
**数值边界**：`request_total_budget_seconds >= attempt_timeout_seconds`（`config/schemas.py:57-65`）。
**参数取值校验**：已知键范围 `temperature 0~2 / top_p 0~1 / frequency_penalty ±2 / presence_penalty ±2`，`max_tokens >= 1`，**未知键放行**（`config/schemas.py:142-191`）。

> **⚠️ doc/code 分歧（新增，E26）**：`tech-design.md:191` 声明的两项校验——① 「资源 `preset` 若非空必须存在于预设注册表」；② 「资源 → vendor_model 必须存在于配置或枚举池」——**在 `config/schemas.py:219-255` 实际均未实现**（代码只做了 id/名称唯一性、引用完整性、images+reasoning 警告）。本报告对**代码**的描述是准确的，此处如实标注与 spec 的差距，供用户决策是否补实现或降版 spec。

#### A.2.3 配置 schema 实样

`config.example.yaml:41-70` 给出权威示例；`data/config.yaml` 是**真实运行配置**（实测：1 个资源 `res-sensenova-main`（preset `sensenova-tokenplan`，`access_mode: plan`，`base_url: https://token.sensenova.cn/v1`），**7 个系统模型**：`sensenova-6.8-flash-lite / deepseek-v4-flash / deepseek-v4-pro / glm-5.2 / kimi-k3 / sensenova-u1-fast / sensenova-u1.5-lite`（后两者为 `endpoint: images`、`group: 图像生成`，见 `data/config.yaml:113-130`），2 个接入令牌）。

> **修正（E1）**：draft 记为「6 个系统模型」，**漏 `sensenova-u1.5-lite`**（`data/config.yaml:122-130`）。现更正为 7 个。资源数 1、令牌数 2 的描述经核验正确，未变。

> ⚠️ 注意：`data/config.yaml` 内含**明文 API Key**（设计使然，铁律 1「全明文配置」）。本报告不复制该 Key 值；`data/` 已在 `.gitignore` 中（**`.gitignore:3`**）。

> **修正（E16）**：draft 引 `config.example.yaml:3` 为 `.gitignore` 依据属**依据错位**；`config.example.yaml:3` 只是同口径的文字说明，规则本体在 `.gitignore:3`（`data/`）。

#### A.2.4 枚举池（模型目录）——D 段的"现成资产"

`EnumEntry`（`enums/matcher.py:17-49`）字段：

```
name / display / aliases[] / group / endpoint(chat|images)
response_format_url_hours / only_base64_image
vendor                        # 厂商归属（模型资源页按此分组）
context_window / max_output   # 上下文 / 最大输出
image_input / video_input / audio_input   # 模态能力
reasoning / effort_levels[]   # 推理支持与档位
params_default{}              # 官方默认参数（作网关初始值）
```

内置 15 条（`enums/matcher.py:67-142`，覆盖商汤 3 / DeepSeek 3 / 智谱 3 / Kimi 4 / Anthropic 2），来源注释见 `enums/matcher.py:52-66`。

> **修正（E5）**：draft 称「**来源均为官方域取证**」**不准确**。`enums/matcher.py:137` 的注释明确写「**跨协议族预置（Anthropic 原生 model id 别名，供 Claude Code 直连解析；属性未取证）**」，两条 Anthropic 条目（`claude-sonnet-4` L138-139、`claude-opus-4` L140-141）**只有 name/aliases/group/vendor**，`context_window` / `max_output` / 模态 / `reasoning` / `effort_levels` / `params_default` **全为空**。故准确表述为：「商汤 3 / DeepSeek 3 / 智谱 3 / Kimi 4 共 13 条来源为官方域取证；**Anthropic 2 条仅预置别名，属性未取证**」。
>
> **对 D 段的影响（E27）**：§D.1 与阶段 0.1 若把这些字段直接下发，对这两条会输出 `null`/空数组，客户端可能误判为「不支持」。→ **落地前置条件：属性未取证的条目应「省略字段」而非下发 null**（见阶段 0.1 与 0.6）。

匹配三级：精确(1.0) → 别名(0.9) → 规范化(0.7)（`enums/matcher.py:173-186`，`normalize_name` 处理大小写/分隔符/日期后缀，`enums/matcher.py:148-155`）。
请求模型解析：`系统模型精确 → 枚举池别名 → 规范化`（`enums/matcher.py:259-280`，被 `api/openai_compat.py:54` 与 `api/anthropic.py:326-327` 共用）。

> **已知缺口（`ACTIVE.md` T2 已备案）**：`normalize_name` **不剥离渠道前缀**（`deepseek/deepseek-v4-flash` 这类 OpenRouter 风格 ID 匹配不上），与 PRD FR-1.4「忽略厂商前缀」有实现差距。

### A.3 请求链路（`/v1/chat/completions` 全链路）

```
客户端 (Trae/Cursor/Cherry/Claude Code/curl)
  │  POST /v1/chat/completions   Authorization: Bearer mg-xxx
  ▼
[1] AuthMiddleware (纯 ASGI)                       api/auth.py:29-64
     ├ 豁免 /health /admin/  → 直通
     ├ 路径非 /v1/ 开头        → 直通
     └ 校验 Bearer/x-api-key → scope["state"]["token_id"] = tok id
  ▼
[2] chat_completions()                             api/openai_compat.py:101-144
     ├ body 非 dict → 400
     ├ 缺 model    → 400
     ├ _resolve_model_or_404 → 404 model_not_found(+candidates) / model_disabled
     ├ _endpoint_type_error  → 400 endpoint_mismatch
     ├ lift_reasoning_from_body(body)   ← 推理字段"提升"防双重注入  ir.py:73-91
     ├ body.pop("model")
     └ IRRequest(system_model, endpoint="chat", stream, body, reasoning)   ir.py:114-122
  ▼
[3] CallCtx.new(...) 绑定配置快照                  core/scheduler.py:116-128
     └ snapshot = runtime.config（在途请求不受热重载影响）
  ▼
[4] Scheduler.execute_chat / stream_chat           core/scheduler.py:462 / 496
     ┌──────────────── 外层：资源循环 ────────────────┐
     │ ① 断连探测 ctx.client_disconnected()           │  scheduler.py:317 / 520
     │ ② pick_and_acquire(system_model, exclude=tried)│  resources.py:120-144
     │    · 冷却懒恢复（到期归位）                     │  resources.py:133-135
     │    · 生效集 = 候选池[:x]                        │  resources.py:140
     │    · 集内 in_flight 最少者承接（平局取优先级高）│  resources.py:142-143
     │ ③ _out_body(ir, resource)  每次尝试重算         │  scheduler.py:223-232
     │    · body["model"] = resource.vendor_model      │
     │    · apply_model_params(...)  三级优先级         │  ir.py:58-70
     │    · merge_reasoning + inject_reasoning_into_body│ ir.py:28-55 / 94-111
     │ ④ adapter.chat_nonstream / chat_stream          │  adapters/openai_out.py:100 / 122
     │ ⑤ 成功 → note_success(C=0) → 返回 / yield        │
     │    失败 → UpstreamError                         │
     └────────────────────────────────────────────────┘
  ▼
[5] ErrorClassifier.classify(UpstreamError) → 六类之一   core/errors.py:84-127
     分类优先级：error_rules(type精确) > error_rules(仅HTTP)
                > VENDOR_TYPE_TABLE > HTTP 通用映射
  ▼
[6] 按类别处置（§5.2 统一判定，y 先判定）           core/scheduler.py:354-418
     ├ CANCELED(408)   → aborted，透传                scheduler.py:357-363
     ├ BAD_REQUEST     → 原样透传（不重试不切换）      scheduler.py:364-370
     ├ AUTH(401)       → disable(R) + 切下一资源       scheduler.py:371-376
     ├ NOT_FOUND(404)  → invalidate(R) + 切下一资源    scheduler.py:377-382
     ├ QUOTA(429)      → 指数退避重试 ≤ quota_retry    scheduler.py:383-394
     │                   耗尽 → bench(R) + 切          scheduler.py:390-393
     └ RETRYABLE       → note_failure → C+=1           scheduler.py:395-417
                          C >= y → bench(R)+冷却+当次切   ← y 先判定
                          attempt==m+1 → RETRY_EXHAUSTED → 切（R 不冷却）
                          no_failover → 仅同资源重试，不切   errors.py:54
  ▼
[7] 终止：无可用资源 / 预算耗尽                      core/scheduler.py:330-332 / 343-346
     → GatewayError(exhausted_reason, attempts[])     scheduler.py:452-458
     → to_openai_error() 统一 error 格式               scheduler.py:66-100
     → HTTP 状态码按兜底原因：BUDGET→503 /
       全 QUOTA→429 / 全 AUTH→401 / 全 NOT_FOUND→404  scheduler.py:234-244
  ▼
[8] 事件落盘（finally 保证成功/失败/取消各一行）      core/scheduler.py:282-283 / 719-722
     EventLogger 单写队列 → data/usage/events-YYYYMMDD.jsonl
     切换事件单独一行 → data/usage/switch-events-YYYYMMDD.jsonl
     stats/events.py:38-80 / scheduler.py:246-259
```

> **修正（E20）**：第 [8] 步的非流式路径 finally 实际在 `_execute`（`core/scheduler.py:292-299`）——其中 `295-297` 处理 `CancelledError → meta.status = "aborted"`，`298-299` 为 `finally → self._log(ctx, meta)`；`282-283` 只是 `_log` 方法本身。流式路径对应 `719-722`。**补引 `scheduler.py:292-299`**。

**流式专属边界**（`core/scheduler.py:496-722` + `api/openai_compat.py:147-213`）：
- **延迟提交**：首个内容事件到达前**不发送任何字节**（含响应头）；窗口内失败可无感重试/切换（`openai_compat.py:158-169`）。
- **committed 后失败**：不重放，yield `_error` 事件 → 编码层转 SSE error 帧并标 `retryable`（`scheduler.py:600-622`、`openai_compat.py:196-198`、`225-235`）。
- **心跳**：上游静默超 `heartbeat_seconds` 发 `: keep-alive`（`openai_compat.py:190-193`）。
- **取消透传**：`CancelledError` 必须 re-raise（`scheduler.py:295-297, 715-718`、`core/cancel.py:1-6`）；断连探测在每次尝试边界 + 退避分段（`scheduler.py:261-270`）。

**故障切换（fallback）实现位置与判定条件汇总**：

| 判定 | 条件 | 动作 | 位置 |
|---|---|---|---|
| AUTH 切换 | 401 / 凭据类 403 | `disable(R)` + 切 | `scheduler.py:371-376, 638-643` |
| NOT_FOUND 切换 | 404 | `invalidate(R)` + 切 | `scheduler.py:377-382, 644-649` |
| QUOTA 切换 | 429 退避耗尽 | `bench(R, cooldown)` + 切 | `scheduler.py:383-394, 650-661` |
| RETRYABLE_Y 切换 | `C >= y`（默认 2） | `bench(R, cooldown)` + 当次立即切 | `scheduler.py:407-412, 673-678` |
| RETRY_EXHAUSTED 切换 | 同资源已试 m+1 次且 `C < y` | 切下一资源，**R 不冷却** | `scheduler.py:413-415, 679-681` |
| 预算耗尽终止 | `now > deadline` | 终止整链 → 503 | `scheduler.py:343-346, 546-549` |
| 无资源终止 | `pick_and_acquire` 返回 None | 终止 → `NO_RESOURCE` | `scheduler.py:330-332, 533-535` |
| no_failover 终止 | URL 下载失败类，m 耗尽 | 终止 → `RETRY_EXHAUSTED` | `scheduler.py:399-403, 664-669` |

### A.4 参数处理：三级优先级的精确落地

**用户口径**：`工具传参 > 网关设置 > 厂商内置`（`AGENTS.md:31` Q24-③、`tech-design.md` §4.7）。

**代码落地**（两条独立链路，都是"字段级注入"）：

| 链路 | 网关设置来源 | 注入函数 | 调用点 | 作用域 |
|---|---|---|---|---|
| **采样参数**（temperature/top_p/max_tokens/…） | `SystemModel.params` → `Runtime.model_params`（`main.py:93`） | `apply_model_params(body, params)`：`if body.get(k) is None: body[k] = v`（`ir.py:58-70`） | `scheduler.py:229`（`_out_body` 内，仅 `endpoint=="chat"`） | 每次尝试重算 |
| **推理参数**（thinking / reasoning_effort） | `ModelResource.reasoning`（资源级，非模型级）→ `Runtime.resource_reasoning`（`main.py:85-91`） | `merge_reasoning()` + `inject_reasoning_into_body()`（`ir.py:28-55, 94-111`） | `scheduler.py:230-231`（同一 `_out_body`） | 每次尝试重算（切换资源后按新资源默认重算） |

关键语义（`ir.py:59-70` 注释与实现）：
- 请求体**已含该键且非 null** → 保留（工具传参最高优先）；
- **缺省或显式 null** → 注入网关设置值；
- 网关未配置该键 → **不注入**（走厂商内置默认）；
- `params` 为**开放 dict**，已知键范围校验、未知键放行（`schemas.py:169-191`）。

入站"提升"防双重注入：`lift_reasoning_from_body` 把 `reasoning_effort` / `thinking` 从透传 body **取出**为 IR 显式字段（`ir.py:73-91`，调用点 `openai_compat.py:122`）；Anthropic 入站同理由 `anthropic_to_openai` 返回 `ReasoningSpec`（`anthropic.py:157-161`）。

> **注意**：`SystemModel.params` 里的 `params_default`（官方默认）是**配置初始化值**（`AGENTS.md:31` Q24-③「官方默认直接写入 config.yaml 作初始值」），运行期不存在"第三级自动查表注入"——厂商内置默认由厂商侧生效。若未来要真正做"厂商内置"这一级，需要在 `_out_body` 再插一层 `enum_pool.params_default` 兜底。

### A.5 扩展点分析：要新增"CLI 对接模式"，哪些地方需要动？

> **修正（E23）**：本节判断需补一条关键前提——**`resource.protocol` 的分派设计在 spec 层面已存在**：`tech-design.md:162` 明载「`anthropic_out`（P1）/ `gemini_out`（P2）：**按资源 `protocol` 字段选择**」，`tech-design.md:163` 明载适配器接口 `call()/list_models()`。**故准确表述是「抽象层在 spec 层面存在、只在代码层面缺失」**，而非「项目没有可挂载新模式的抽象层」。

#### A.5.1 现有可复用/可挂载的结构

| 位置 | 现状 | 能否挂载新对接模式 |
|---|---|---|
| `adapters/base.py:1-5` | **仅一段 docstring（5 行），无任何代码**（无 ABC/Protocol） | ❌ 代码层无契约可挂载——**需按 spec 已声明的 `call()/list_models()` 落实**（见 A.5.2） |
| `adapters/openai_out.py:42-207` | 具体类，方法 `chat_nonstream` / `chat_stream` / `images_generate` / `list_models` | ✅ 可作为 `call()` 契约的既有实现，签名可提炼为接口 |
| `Resource.protocol`（`schemas.py:19,125`） | 枚举 `openai\|anthropic\|gemini` | ⚠️ **字段存在但无消费点**（全仓 grep：`schemas.py:125` 定义 + `resources.js:505`、**`resources.js:1018`** 前端赋值，其余为测试/文档）——**spec 已声明应有消费点**（`tech-design.md:162`），属「设计已定、实现缺失」 |
| `Runtime._apply`（`main.py:95-105`） | **对所有资源一律构造 `OpenAIOutAdapter`**，仅按 `base_url` 变更决定是否重建 | ❌ 代码层无协议分发（spec 层面已有设计） |
| `Scheduler._adapter`（`scheduler.py:211-215`） | 按 `resource.rid` 从 `runtime.adapters` 取，取不到抛 `GatewayError("protocol 未实现")` | ⚠️ 错误信息暗示有协议分发，**实际不存在** |
| `Runtime.adapters: dict[str, OpenAIOutAdapter]`（`main.py:64`） | 类型注解写死具体类 | ⚠️ 需泛化 |
| 资源状态机（`resources.py:32-64`） | `access_mode` 仅影响冷却时长（`resources.py:170-174`） | ✅ 新轴可平行插入 |
| `ErrorClassifier`（`errors.py:84-127`） | 输入 `UpstreamError(status_code, error_body, error_type)` | ✅ CLI 适配器只需把 CLI 退出码/stderr 映射成 `UpstreamError` 即可复用全部重试/切换逻辑 |
| **`config/presets.py`（厂商预设注册表）** | 模块级常量清单，3 条预设（`presets.py:17-45`），字段 `id/name/mode/protocol/base_url/billing/notes` | ⚠️ **新增，E21**：项目自述「扩展原则：新增厂商或 Plan 类型 = **仅加一条预设数据**（必要时新增协议适配器），接入向导与 UI 框架零改动」（`presets.py:6-8`、`tech-design.md:194`）→ **新增 `transport` 轴时预设注册表很可能需同步扩展字段**，否则「CLI 资源」无法从预设带入。draft 的扩展点清单完全未提此项，属不完整 |

> **修正（E19）**：draft 的 grep 结论漏了 `resources.js:1018`（`protocol: "openai",`）。补入上表。

#### A.5.2 结论：需要改动的清单（按"必须/建议"分级）

> **修正（E22 · 唯一的明确铁律冲突）**：draft 在此处拟议的适配器接口为 `chat_nonstream / chat_stream / images_generate / aclose`，但 **`tech-design.md:163` 已声明**的接口是：
> ```python
> async def call(resource, ir_request) -> IRResponse | AsyncIterator[IREvent]   # 非流式/流式两形态
> async def list_models(resource)
> ```
> 两者**不一致**，且 draft 未披露该差异 → **触碰铁律 4「无依据自创禁止」**。
> **处理方式（二选一，本定稿采用方案 a）**：
> - **a（推荐，相容）**：按 spec 已声明的 `call() / list_models()` 契约落实——把 `OpenAIOutAdapter` 现有的 `chat_nonstream / chat_stream / images_generate` 作为**内部实现**，由 `call()` 按 `ir_request.stream` 与 `endpoint` 分派。**这不属自创，属落实既有设计。**
> - **b（需翻案）**：若坚持 draft 的扁平签名，则必须**明确标注「这是对 `tech-design.md:163` 的修订提案，需走 spec 变更流程并经用户翻案」**，并在同一批次同步升版 tech-design。

**必须（否则新模式无法成立）**：

1. `adapters/base.py` 补**真实接口**，**按 `tech-design.md:163` 已声明契约**定义 `call()` + `list_models()`（`Protocol` 或 ABC）；`chat_nonstream / chat_stream / images_generate / aclose` 作为具体适配器的内部方法保留。
   - **铁律关系：相容**（落实 spec 既有设计，非自创）。若改用扁平签名 → **明确冲突需翻案**。
2. `main.py:95-105` `_apply` 增加**按资源分派适配器**的逻辑（当前硬编码 `OpenAIOutAdapter`）。
   - **铁律关系：相容**——`tech-design.md:162` 已声明「按资源 `protocol` 字段选择」，属落实既有设计（draft 列为「需用户确认」偏保守，E23）。
3. `main.py:64` `Runtime.adapters` 类型泛化为 `dict[str, AdapterProtocol]`。**铁律关系：相容。**
4. `config/schemas.py` 增加**新轴字段**（见 A.5.3），并接入 `Resource` 校验与 UI 表单；**同步评估 `config/presets.py` 预设字段扩展**（E21）。
   - **铁律关系：潜在冲突（程序性）**——属「无依据自创」，**须先经用户确认写入 PRD**。

**建议（否则会留下隐患）**：

5. `scheduler.py:214` 的错误信息改为"资源 X 的适配器未注册（transport=…, protocol=…）"，避免误导。**铁律关系：相容。**
6. 新增适配器的 `UpstreamError` 映射规范（CLI 退出码 → 六类），否则 `ErrorClassifier` 会把 CLI 的"命令不存在"当成 RETRYABLE 无限重试。**铁律关系：相容。**
7. `resource.protocol` 的**分发消费点补齐**（或明确删除该字段，避免"看起来支持实则不支持"）。**铁律关系：相容**（`tech-design.md:162` 已声明该分发）。

#### A.5.3 命名冲突：必须由用户裁决的第一个决策点

现状字段语义（**已被 UI 占用**）：

| 字段 | 取值 | 语义 | UI 文案 |
|---|---|---|---|
| `access_mode` | `api` \| `plan` | **凭据类型**（按量 Key / 订阅套餐） | 「API（按量计费）」「Plan（订阅 / 积分制）」`resources.js:240,779-780` |
| `protocol` | `openai` \| `anthropic` \| `gemini` | **上游协议族** | 未在 UI 暴露（`resources.js:505`、`1018` 仅透传） |

用户诉求的「API 对接模式 / CLI 对接模式」是**第三条轴：传输方式**。三个候选方案：

| 方案 | 形式 | 优点 | 代价 |
|---|---|---|---|
| **A（推荐）新增独立轴** | `resources[].transport: "http" \| "cli"`（默认 `http`，向后兼容） | 语义正交、不破坏现有字段、可热重载 | 需新增 schema 字段 + UI 表单 + 校验（属"无依据自创"，**须先经用户确认写入 PRD**） |
| B 扩展 `access_mode` | `api \| plan \| cli` | 字段少 | **语义污染**：`plan` 与 `cli` 不在同一维度（一个是计费、一个是传输），组合爆炸（"plan + cli"无法表达）；`cooldown_seconds_for` 的 plan 判定会失效（`resources.py:170-174`） |
| C 用 `protocol` 承载 | `protocol: "cli-xxx"` | 复用现有字段 | `protocol` 语义是"协议族"，塞传输方式同样污染；且 `protocol` 目前无消费点，语义未固化，风险中等 |

→ **建议 A**，并在 PRD 中显式声明「`access_mode` 语义不变，`transport` 为新增正交轴」。

---

## B. API 模式风险分析

### B.0 先澄清前提（否则整段会答错）

用户原话：「后面我们如果对接了各个软件授权提取内部模型使用，通过 API 调用是不是存在较大风险和不稳定因素」。

这句话里的「API 模式」**不是**项目现有的 `access_mode: api`（按量 API Key，合规且稳定）。它指的是另一条路：

> **通过"软件账号授权"（订阅套餐 / 客户端登录态 / OAuth token）把某个软件内部的模型能力"提取"出来，用 API 调用的方式接入网关。**

这条路的风险画像与"买按量 API Key"完全不同。下面 B.2 逐条展开，全部围绕这条路径。

### B.1 风险清单（概率 / 影响 / 缓解）

| # | 风险 | 发生概率 | 影响面 | 可缓解手段 | 依据等级 |
|---|---|---|---|---|---|
| R1 | **服务条款明确禁止**：第三方开发者不得提供 Claude.ai 登录 / 代表用户路由订阅凭据 / 收集中转会话 token | **高（已发生）** | 致命：账号封禁 + 通道整体失效 | 无技术缓解；只能改用官方 API Key 或走厂商授权的商业合作 | **一手（官方文档原文）**，但**有限定段**（见 B.2） |
| R2 | **平台主动技术拦截**：OAuth token 在非官方客户端被拒 | **高（已发生，2026-01 起）** | 致命：鉴权直接失败 | 无稳定缓解；任何"伪装成官方客户端"的手段都在对抗升级 | **一手（官方文档）+ 二手（报道）** |
| R3 | **账号风控/封号**：设备指纹、行为遥测、时区/网络异常综合判定 | **高** | 高：账号资产损失、可能连带支付方式 | 降低并发、单账号单通道、不共享凭据；但**不能消除** | 二手（多源报道，**未验证**具体机制） |
| R4 | **凭据共享/中转被明令禁止**：不得收集、存储、中转官方登录凭据或会话 token | **高** | 高：合规风险 + 封禁 | 网关不落盘任何 OAuth 凭据、不代理登录流程 | **一手（官方文档原文）** |
| R5 | **速率限制与额度耗尽**：订阅套餐有滚动窗口额度（非按量） | **高** | 中：请求被拒 → 触发网关 QUOTA 冷却 | 项目已内置：`quota_retry=2` 指数退避 + `cooldown_seconds_plan=18000`（对齐滚动 5h 窗口，`schemas.py:81`） | 一手（项目实现）+ 项目自身取证 |
| R6 | **协议逆向易变**：非公开接口无兼容承诺，平台改版即失效 | **中高** | 中高：需持续跟进维护，无 SLA | 只对接官方公开端点；把 `base_url` 与 `protocol` 做成可配置（**已具备**，`schemas.py:125-126`） | 一手（项目实证：商汤自身就存在"按量 API / TokenPlan"两套 Key 与端点体系，需双端点实测才能定论，见 `decisions.md:9`） |
| R7 | **错误语义不标准 → 分类器失效** | **中高** | 中：误判 RETRYABLE → 误计 C → 误冷却/误切换，或误判 BAD_REQUEST → 该切不切 | `error_rules` 可覆写（`schemas.py:84-95`、`errors.py:107-110`）；但逆向接口若不返回标准 `{"error":{"type":...}}` 结构，`extract_error_type` 会返回 None（`errors.py:67-81`）→ 退化为纯 HTTP 码映射 | 一手（代码事实） |
| R8 | **Token 刷新失败**：OAuth 刷新需登录态/设备绑定，无法在无头环境稳定续期 | **中高** | 高：需人工重新登录，网关无人值守能力丧失 | 无；只能接受人工介入 | 二手 + 逻辑推断（**部分未验证**） |
| R9 | **并发画像异常**：订阅按"普通个人使用"设计，网关聚合多工具并发放大到非个人画像 | **中高** | 中高：触发风控 | 限流（`max_concurrent_requests` 目前 0=不限，`schemas.py:50`）；但限流会牺牲网关的核心价值 | **一手（官方原文："Advertised usage limits for Pro and Max plans assume ordinary, individual usage"）** |
| R10 | **审计与可观测性缺失**：逆向通道的用量/错误数据不可信 | 中 | 中：统计与成本估算失真（`pricing` 表依赖官方口径） | 事件流水已完整（`stats/events.py`），但 `usage_source` 可能长期为 `estimated`（`scheduler.py:272-280`） | 一手（代码事实） |
| R11 | **维护成本与合规成本**：无文档、无 SLA、法务风险 | 中高 | 中高：长期隐性成本 | 明确标注为"实验性、默认关闭" | 判断（非证据） |

### B.2 一手证据（关键四条，原文引用）

**证据 1 · Anthropic 官方合规页（一手，抓取 2026-09-22）**

> "OAuth authentication is intended exclusively for purchasers of Claude Free, Pro, Max, Team, and Enterprise subscription plans and is designed to support ordinary use of Claude Code and other native Anthropic applications."
>
> "Developers building products or services that interact with Claude's capabilities, including those using the Agent SDK, should use API key authentication through Claude Console or a supported cloud provider. **Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, or Max plan credentials on behalf of their users. Moreover, developers may not collect, store, or intermediate Claude.ai credentials or session tokens** — sign-in to a Claude account must complete through Anthropic's own flow."
>
> "Anthropic reserves the right to take measures to enforce these restrictions and **may do so without prior notice**."
>
> 另： "Advertised usage limits for Pro and Max plans assume **ordinary, individual usage** of Claude Code and the Agent SDK."

**证据 1-b · 同页紧接的限定段落（一手，draft 遗漏，本次补引 —— E7）**

> "This does not restrict how customers provision and manage their own API keys or third-party inference provider credentials — for example, configuring an API key in a development environment, secrets manager, or machine image for use by the customer's own authorized users — provided the resulting usage is billed to the key owner… **Nor does it prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription**, including where a platform hosts Claude Code…"

> 来源：<https://code.claude.com/docs/en/legal-and-compliance>（官方，2026-09-22 抓取）

**基于证据 1 + 1-b 的准确结论（修正 draft 的过度推断 —— E7）**

官方限制的对象是**「谁在做什么」**，不是**「用什么形态调用」**：

| 行为 | 官方口径 | 依据 |
|---|---|---|
| 第三方开发者在自己应用里提供 Claude.ai 登录 | ❌ 禁止 | 证据 1 |
| 通过网关/第三方"**代表用户**"路由 Free/Pro/Max 订阅凭据 | ❌ 禁止 | 证据 1 |
| 网关**收集、存储、中转** Claude.ai 凭据或会话 token | ❌ 禁止 | 证据 1 |
| 客户管理**自己的 API Key / 第三方推理凭据**（如放在 secrets manager 供自有授权用户使用），**且用量计费给 Key owner** | ✅ 不限制 | 证据 1-b |
| **终端用户**在自己的机器上、用**未修改的官方 Claude Code 二进制** + **自有订阅**登录（**即使有平台托管 Claude Code**） | ✅ **明文不阻止** | 证据 1-b |

> **因此 draft 的「CLI 模式同样违规且更明确被禁止」是过度推断，本定稿更正为**：
>
> **CLI 模式规避的是「网关存储/中转订阅凭据」这一点**（因为凭据留在厂商 CLI 自持的存储里、网关不接触），**但它并不规避「把订阅凭据喂给非官方客户端」这条限制**——如果网关把 CLI 当**上游**、由**网关进程**去驱动 CLI 完成"代表用户发请求"，那仍落入证据 1 的禁止区（"route requests through … plan credentials on behalf of their users"）。
>
> **反过来说**：如果是**终端用户自己**在**本机**用**未修改的官方 CLI** 连到网关（网关只做**按量 API Key** 的转发），或用户**直接使用原版客户端 + 自有订阅**，官方明文说**不阻止**。
>
> **这个区别对方案选型是关键**：决定合规性的不是「API 还是 CLI」，而是 ① **谁代表谁**（第三方/网关代他人 vs 用户自用）；② **凭据存在哪**（网关存储/中转 vs 厂商客户端自持）；③ **是否修改了官方二进制**。

**证据 2 · 同一页面的商用条款（一手）**
> "**The Claude Code binary must not be modified.** Claude Code must be installed and run as published by Anthropic, and customers may not remove, disable, or restrict any authentication method built into it."
>
> "**Customers may not pay for, resell, or intermediate Claude usage on their end users' behalf.**"
>
> 来源：同上

**证据 3 · 技术拦截已实际发生（二手，多源一致，标注未验证细节；含同源反向陈述 —— E8）**
> "Enforcement began blocking Max OAuth access in third-party clients on January 9, 2026. A documentation update on February 19 then clarified that using OAuth tokens from consumer plans in third-party tools violates Anthropic's terms."
>
> "Anthropic says Free, Pro, and Max OAuth tokens cannot be used in third-party tools or the Agent SDK."
>
> **同源反向陈述（draft 遗漏，本次补引）**：
> "Anthropic later described the documentation changes as a '**docs clean up** that caused confusion' and said **nothing was changing about Agent SDK usage with Max subscriptions**."
>
> 来源：<https://winbuzzer.com/2026/02/19/anthropic-bans-claude-subscription-oauth-in-third-party-apps-xcxwbn/>（**二手媒体**，2026-02-19 发布，2026-09-22 抓取；该报道与证据 1 的官方原文互相印证，可信度高）

> **修正（E8）**：同一篇文章既报道「新增禁令」方向，又载明官方把文档变更解释为 "docs clean up that caused confusion"、称 "nothing was changing about Agent SDK usage with Max subscriptions"。**两个方向自相矛盾**。→ **本报告不据此判定政策生效日**，仅把「2026-01-09 起存在实际拦截」作为**现象**记录（该现象另有 `awesomeagents` 来源印证）。
>
> **另一条无法核实的引文（如实记录）**：`winbuzzer` 与 `awesomeagents` 均引述过 "Using OAuth tokens obtained through Claude Free, Pro, or Max accounts in any other product, tool, or service…"（标注 "via Claude Code Docs"），但**当前 `legal-and-compliance` 页面不含该句**（可能在 Consumer Terms 或页面已改版）。draft 未引该句（无过），本定稿亦不引，**若要强化论证须先定位一手出处**。

**证据 4 · 国内封号现象（二手，仅作现象参考，机制未验证）**
- <https://zhuanlan.zhihu.com/p/2055601319893786836>（个人订阅封号现象自述）
- <https://woodchen.ink/archives/claude-code-封号机制深度探查报告>（声称"Device ID + 40+ 维环境指纹 + 640+ 行为遥测"，**未验证**；该报告基于"已泄露源代码"，按 `decisions.md:13` 不可作为机制依据）
- <https://cloud.tencent.com/developer/article/2624427>（腾讯云社区：逆向中转产业链乱象）

> ⚠️ 按项目取证纪律（`decisions.md:13`：外部资料仅采信官方文档与 GitHub 实际项目代码，搜索引擎二手内容不作为依据），上列二手来源**只用于说明"现象存在"**，不作为机制结论。
>
> **注意（E9）**：`woodchen` 报告 §6.4「自动化滥用检测」明确把 `is_ci: true` / `is_interactive: false` / `entrypoint: "sdk"` / 高频调用 + 大 token 消耗列为**自动化滥用嫌疑**，§9.2 建议「CI/CD 中大规模使用 → 使用 API Key 而非 OAuth」——**而网关正是"无人值守、非交互、高并发"的调用方**。这条**反方向**证据在 §C.5 必须一并披露。

### B.3 结论：用户担心的"风险和不稳定因素"具体是什么

| 用户的直觉 | 更准确的表述 |
|---|---|
| 「通过 API 调用存在较大风险」 | **风险不在 API 这个技术形态，而在"凭据来源"与"谁代表谁"**。用按量 API Key 走 API 是完全合规且稳定的（这正是项目现有 `access_mode: api`）；用**订阅账号授权**由**第三方/网关代表用户**去路由，才违规。**终端用户在本机用原版客户端 + 自有订阅，官方明文不阻止**（证据 1-b）。 |
| 「不稳定因素」 | 具体是四件事：① 平台可**随时**改协议或直接拦截（无 SLA）；② OAuth token 刷新依赖登录态/设备绑定，无头环境难维持；③ 错误语义不标准导致网关的**重试/切换判定失效**；④ 订阅额度是滚动窗口制，与按量额度语义不同（项目已用 `cooldown_seconds_plan=18000` 部分应对）。 |
| 「所以需要 CLI 模式」 | 见 §C.5——**CLI 模式能改善①②的一部分**（协议稳定性确实更优），**但它规避的是"网关存储/中转凭据"这一点，并不规避"把订阅凭据喂给非官方客户端"**。合规与否取决于**谁代表谁**，不取决于用 API 还是 CLI。 |

---

## C. CLI 对接模式设计

### C.0 先拆题：用户诉求里其实有两条不同的"CLI 对接"

用户原话包含两个方向，必须分开设计：

| 方向 | 原话 | 技术含义 |
|---|---|---|
| **上游（出站）** | 「对接了各个软件授权提取内部模型使用……通过 API 调用是不是存在较大风险」 | 网关**调用上游**时，用厂商 CLI 替代逆向 API |
| **下游（入站）** | 「让任何工具安装了 CLI 无缝衔接网关系统，以最直接最稳定最短路径去调用我们网关集成进来的各种模型资源」 | 网关**对外提供**一个 CLI 入口，任何工具装上即可接 |

两条方向的风险画像、技术难度、收益完全不同，**不能混为一谈**（下面 C.3 给出 4+1 个方案，逐一对号入座）。

### C.1 调研：主流工具是否支持"指向自定义网关 / 自定义 base_url"？

| 工具 | 支持自定义 base_url | 支持模型清单自动发现 | 模型 ID 如何提供 | 依据等级 |
|---|---|---|---|---|
| **Claude Code** | ✅ `ANTHROPIC_BASE_URL`（"Override the API endpoint to route requests through a proxy or gateway"）+ `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY` | ✅ **有官方开关**：`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` 从网关 `/v1/models` 填充 `/model` 选择器；**默认关闭**（官方理由：共享 Key 的网关会让每个用户看到该 Key 能访问的全部模型）；仅限 Anthropic 兼容网关 | 另有 `ANTHROPIC_CUSTOM_MODEL_OPTION`(+`_NAME`/`_DESCRIPTION`/`_SUPPORTED_CAPABILITIES`) 手工加自定义模型条目 | **一手**：<https://code.claude.com/docs/en/env-vars> |
| **Codex CLI** | ✅ `~/.codex/config.toml` 的 `model_providers` + `base_url` + `wire_api` | ⚠️ 未见于官方文档 | 配置内手写 `model` | **二手（多源一致）**：<https://airelayrank.com/zh/guides/codex-cli-api-relay-config/>、<https://devpress.csdn.net/v1/article/detail/162196259>（**未在官方文档验证**） |
| **Cursor** | ✅ BYOK + Override OpenAI Base URL | ⚠️ 有"Auto-detect models from provider"相关报错线索，说明**会**请求 `/v1/models`；但模型名必须与 `data[].id` **完全一致**，否则报 `Named Models` | 手工填写，须与 `/v1/models` 返回的 id 一致 | **二手（内容农场式文章，不足以支撑结论）**：<https://www.php.cn/faq/2930693.html>（**未验证**）；官方文档站抓取失败 |
| **Trae** | ✅ 自定义模型：选"自定义配置"→ 协议选 OpenAI/Anthropic → 填请求地址（多数厂商需自己补 `/chat/completions`，或开"完整 URL"） | ❌ **不自动发现**。教程明确要求"**模型 ID 请自己去查询**"，并反复强调这是最高频的配置失败原因 | 手填模型 ID + 手填上下文长度（默认 200K，官方拆 184K 输入 / 16K 输出）+ 手填多模态开关 + 工具调用轮次 | **二手（官方社区用户教程）**：<https://forum.trae.cn/t/topic/11480> |
| **Cherry Studio** | ✅ 自定义服务商：填 `API 地址`(Base URL) + `API 密钥` | ❌ **不自动发现**。官方文档："点击「+ 添加」按钮，**手动添加**此提供商下您想要使用的模型 ID" | 手填模型 ID | **一手（官方文档）**：<https://docs.cherry-studio-ai.com/pre-basic/providers/zi-ding-yi-fu-wu-shang> |
| **通用结论** | **"指向自定义 base_url"是 OpenAI/Anthropic 兼容生态的事实标准，覆盖率很高** | **"从网关自动发现模型清单"覆盖率很低**：多数工具要手填模型 ID | — | — |

> **修正（E10 · 分级失当）**：draft 把 Trae 论坛帖标为「**一手（官方社区官方教程）**」并归入「一手（官方）」。核验实测该帖标题《添加自定义模型服务模型教程 v4.0版本(2026.05.15更新)》，**作者 = `JasonShane`，头衔「社区捣蛋鬼」**（社区用户，**非 TRAE 官方**），发布在 TRAE 官方中文社区。按项目取证纪律（`decisions.md:13`「外部资料仅采信**官方文档**与 GitHub 实际项目代码」），**应归「二手」**。
> **重要**：该帖**内容全部核实无误**（模型 ID 手填、184K/16K 拆分、多模态手查、工具调用轮次 200、完整 URL 开关），**结论不变**；本次仅更正**分级**。

> **这条结论直接决定 D 段的优先级**：不要指望"下发清单"被客户端自动消费；**人可复制的一页清单才是真正可用的交付形态**。

### C.2 业界先例与协议（联网取证）

#### C.2.1 Agent Client Protocol（ACP）——**不是模型接入协议，是编辑器↔Agent 协议**

- 定义（一手，官方仓库 README）："The Agent Client Protocol (ACP) standardizes communication between **code editors** ... and **coding agents** ..."
- 传输：JSON-RPC 信封；**默认 stdio**（由客户端启动 agent 子进程）——**修正（E13a）**：官方 README **未载明 stdio**，此为据实现惯例推断，**未核实**；并有社区 HTTP/WebSocket bridge（`acp_rpc_bridge`、`ACP Remote`）。
- 协议版本：当前稳定版 `1`，通过 `initialize` 的 `protocolVersion` 协商。
- **模型选择/模型清单：官方 README 未定义**。仅有提交线索 `providers/list`、`providers/set`、`providers/disable`，且标注为 **unstable**（**未验证**）。
- 客户端生态（一手，官方 Clients 页）覆盖极广：Zed、JetBrains、VS Code、Neovim、Emacs、Obsidian、Sublime、Qt Creator、Unity、Visual Studio，以及大量 CLI/TUI/桌面/Web/移动端客户端；其中 **"ACP Pro（兼容 Cursor/Windsurf/Trae）"** 这类扩展存在。
- 治理：**修正（E13b）**——draft 写的 `"Zed-led model"` **不是官方原文**。官方页原文为：`zed.dev/acp` → "**Created by Zed**, grown by a community of editors and agents."；`jetbrains.com/acp` → "The ACP is **developed openly by JetBrains and Zed** to support a multi-editor, multi-agent ecosystem."。准确表述：**由 Zed 创建，JetBrains 与 Zed 共同开发**。
- 来源：<https://github.com/agentclientprotocol/agent-client-protocol>、<https://zed.dev/acp>、<https://www.jetbrains.com/acp/>、<https://agentclientprotocol.com/overview/clients>

> **对本题的意义**：ACP 解决的是"编辑器怎么调用一个 coding agent"，**不解决"agent 怎么拿到模型清单"**。把网关做成 ACP Agent 是**范畴错配**（网关是模型网关，不是编码 agent）。→ 不推荐作为 CLI 对接模式的主方案（见 C.3 方案 5）。

#### C.2.2 Model Context Protocol（MCP）——**"本地 CLI 作为传输"的最标准现成范式**

- 一手规范（2026-07-28 版）：MCP 用 **JSON-RPC**，定义两种标准传输：
  1. **stdio**："newline-delimited messages over the standard streams of a **client-launched subprocess**"
  2. **Streamable HTTP**："each message is an HTTP POST to a single MCP endpoint; replies arrive as a JSON object or a **request-scoped SSE stream**"
- 取消：stdio 用 `notifications/cancelled`；Streamable HTTP 关闭请求的响应流。
- **自定义传输被显式允许**，且规范建议："Custom transports that run over a reliable bidirectional byte stream (e.g., **Unix domain sockets** or TCP) **SHOULD reuse the stdio framing** rather than defining a new one."
- 来源：<https://modelcontextprotocol.io/specification/2026-07-28/basic/transports>

> **对本题的意义**：如果要做"本地 CLI 无缝接网关"，MCP 的 **stdio framing（换行分隔 JSON-RPC，客户端启动子进程）** 是业界已验证的形态，可直接借鉴；但 MCP 的**消息语义**（tools/resources/prompts）不是 chat completions，**不能直接当模型调用协议用**。

#### C.2.3 CLIProxyAPI——**"CLI 作为模型接入层"的真实先例（也是反例）**

- 定位（一手，仓库 README）："A proxy server that provides **OpenAI/Gemini/Claude/Codex/Grok compatible API interfaces for CLI**."
- 包装对象：Claude Code（OAuth）、OpenAI Codex（OAuth）、Grok Build（OAuth）、Gemini/Antigravity、Kimi；支持**多账号 round-robin 负载均衡**。
- 暴露形态：OpenAI 兼容（含 Responses API）/ Gemini / Claude 端点；支持流式/非流式/WebSocket；函数调用；多模态输入；局域网 DNS-SD 发现（`_ai-gateway._tcp`）。
  - **未逐项验证**（核验范围：定位、包装对象、round-robin、DNS-SD、OAuth、赞助商已核实；WebSocket / 函数调用 / 多模态三项**未逐项核实**）。
- 凭据：**OAuth 登录**（第三方工具描述为 "No API keys needed, just OAuth"）。
- 来源：<https://github.com/router-for-me/CLIProxyAPI>（另有 UI 变体 <https://github.com/Senselegend/CLIProxyAPI-UI>）

> **双重意义**：
> ① **技术可行性已被证明**——"把 CLI 的订阅会话包装成 OpenAI 兼容 API"是能跑通的工程路径，且已有成熟开源实现。项目的 CLI 上游适配器可以直接参考其架构（不是抄代码）。
> ② **它同时是反面教材**——核验确认其赞助商构成含**低价 API 中转（PackyCode / AICodeMirror / APIKEY.FUN / PatewayAI）、住宅代理（Bestproxy / Swiftproxy / RapidProxy）、账号售卖（CyberPay）**，与 §B.2 证据 1 的官方禁令形成鲜明对照。**这条路正是平台在封的方向**。

#### C.2.4 网关侧"模型清单下发"的成熟范式（为 D 段取证）

| 范式 | 形态 | 来源 |
|---|---|---|
| **OpenRouter** | `GET /api/v1/models` 返回 14 个字段/模型：`id / canonical_slug / name / created / description / context_length / architecture{input_modalities,output_modalities,tokenizer,instruct_type} / pricing{...} / top_provider{context_length,max_completion_tokens,is_moderated} / per_request_limits / supported_parameters[] / default_parameters / expiration_date / benchmarks`；另有 `GET /api/v1/model/{author}/{slug}` 单模型查询 | 一手：<https://openrouter.ai/docs/guides/overview/models> |
| **LiteLLM Proxy** | `GET /v1/models`（标准清单）+ `GET /model/info`（含映射成本、上下文、以及**任意自定义 `model_info` 字段**透传）；`model_info` 是"标注自有元数据"的官方机制 | 一手：<https://docs.litellm.ai/docs/proxy/model_management> |
| **OpenAI 官方** | `GET /v1/models` 的 Model 对象：`id / object("model") / created / owned_by / shutdown_date`（**修正 E14**：官方**当前** schema 含 `shutdown_date`；draft 称"2026 官方 schema 新增"**页面无法证实**，已删去时间性断言） | 一手：<https://developers.openai.com/api/reference/resources/models/methods/list> |

### C.3 方案对比（4 + 1 个方案）

**评价维度**：`最直接`（调用方心智负担）、`最稳定`（故障面）、`最短路径`（端到端跳数与改造量）、`实现成本`、`兼容性代价`。

#### 方案 1 · 网关内置本地 CLI，工具通过它调用（shell-out 模式）

形态：网关发行一个 `mgw` 命令；工具调用时执行 `mgw chat --model deepseek-v4-flash --stream`，CLI 负责与网关通信并输出结果。

| 维度 | 评价 |
|---|---|
| 最直接 | ⚠️ 中：对**人**很直接，对**工具**不直接——工具需要认识"调用外部命令"这个契约 |
| 最稳定 | ⚠️ 中：多一层进程，多一层退出码/编码/stdout 解析歧义 |
| 最短路径 | ❌ 差：链路变长（工具 → 子进程 → 网关 → 上游），且无法复用 SSE 流式的现成能力 |
| 实现成本 | 中（CLI 本体不难，难在**工具侧改造**） |
| 兼容性代价 | ❌ **极高**：据本次调研所查文档，Trae / Cursor / Cherry Studio / Claude Code **均未见**"把模型调用委派给外部命令"的能力（**未穷尽验证**）。要让它们支持，等于要求每家工具改代码。 |
| 结论 | **不成立**（除非用户自己写工具）。用户诉求里的"任何工具"若指现成商业工具，这条路走不通。 |

> **修正（E11）**：draft 原文为「**没有任何一个**支持…」——属**无来源支撑的否定性全称断言**。已降级为「据本次调研所查文档，均未见此能力（**未穷尽验证**）」。结论方向不变。

#### 方案 2 · 本地 CLI 作为**统一入口 / 启动器**，工具仍走 HTTP 入站（推荐）

形态：网关发行 `mgw` CLI，但它**不承载模型流量**，只做三件事：
1. `mgw start|stop|restart|status` —— 启停与健康检查（封装 `启动网关.command` 与 `/admin/api/system/*`）；
2. `mgw models [--format openai|table|md]` —— **拉取并打印当前生效模型清单**（解决 D 段的"手填 ID"痛点）；
3. `mgw setup <trae|cursor|cherry|claude-code|codex>` —— 生成并打印该工具的接入配置片段（base_url + token + 模型名），把"最短路径"落在**配置阶段**；
   - **铁律边界（新增，E24 · 潜在冲突）**：`mg-directory-layout.mdc:10` 明令 `.claude/`、`.trae/`、`.workbuddy/` 等其它 `.xxx` 工具目录「**一律不维护、不更新、不写入**」。**若 `mgw setup` 写入项目内这些目录即违规** → 须限定为「**仅打印，或仅写用户家目录的工具配置；绝不写项目内 `.xxx` 目录**」。
   另可选 `mgw serve --socket <path>`：在**保留 HTTP 入站**的前提下，额外开一个本地 Unix socket（复用 MCP stdio framing 思路）供**自研工具**使用。

| 维度 | 评价 |
|---|---|
| 最直接 | ✅ 高：工具侧零改造（继续用 OpenAI/Anthropic 兼容 base_url，这是生态事实标准，见 C.1） |
| 最稳定 | ✅ 高：复用已验证的 HTTP/SSE 链路与全部调度/重试/切换/取消逻辑，不新增故障面 |
| 最短路径 | ✅ 高：对现成工具而言，`base_url` + `token` 就是最短路径；CLI 把"找 base_url / 找 token / 找模型 ID"三步压成一条命令 |
| 实现成本 | **低**：CLI 是新增独立入口，**零改动现有网关内核** |
| 兼容性代价 | ✅ 无：不改变任何既有协议 |
| 铁律关系 | ⚠️ **`mgw setup` 的"写入"部分为潜在冲突**（见上）；"仅打印"版本**相容** |
| 结论 | **推荐为"下游 CLI 对接"的主方案** |

> 关键洞察：**"CLI 无缝接网关"的正解不是"让工具通过 CLI 调用网关"，而是"CLI 让工具能一键配好网关"**。因为工具认的是 base_url，不是命令。

#### 方案 3 · 网关实现 MCP Server（stdio + Streamable HTTP）

形态：网关暴露 MCP server，工具（支持 MCP 的）通过 MCP 访问。

| 维度 | 评价 |
|---|---|
| 语义匹配 | ❌ **错配**：MCP 的语义是 tools / resources / prompts，**不是 chat completions**。MCP 客户端（如 Claude Code、Cursor）把 MCP server 当"工具提供方"，**不会**把它当 LLM 后端 |
| 最稳定 | ✅ 高（stdio framing 已被规范固化） |
| 实现成本 | 中（要写 MCP server + 会话管理） |
| 兼容性代价 | ⚠️ 高：现有工具**没有**"从 MCP 拿模型"的用法 |
| 结论 | **不推荐**作为模型接入层。但 MCP 的 **stdio framing 规范**可作为方案 2 中 Unix socket 通道的实现参考（规范明确建议 Unix socket 复用 stdio framing）。 |

#### 方案 4 · 网关新增 **CLI 上游适配器**（"CLI 模式"的上游方向）

形态：`Resource.transport = "cli"` 时，网关不走 HTTP，而是**调用厂商官方 CLI 的 headless 模式**（如 `claude -p ... --output-format stream-json`、`codex exec`）并把结果归一化为 OpenAI chunk。

| 维度 | 评价 |
|---|---|
| 技术可行性 | ✅ **已被 CLIProxyAPI 证明**（C.2.3） |
| 协议稳定性 | ✅ **确实更优**：跟随官方客户端，厂商维护协议兼容性，无需逆向（这是 CLI 模式**唯一真实优势**） |
| 合规/风控 | ⚠️ **取决于形态，draft 原判断（"同样违规且更明确被禁止"）已被更正 —— E7**：官方禁止的是「**第三方/网关代表用户**路由订阅凭据」与「**网关收集/存储/中转**会话 token」；官方**明文不阻止**「终端用户在本机用**未修改**官方二进制 + **自有**订阅」。故：**若网关进程驱动 CLI 代用户发请求 → 落入禁止区；若 CLI 以用户自有凭据在本机由用户自己驱动、网关不经手凭据 → 不落入该禁止区**。另注：CLI 的 `--bare`（官方推荐用于脚本/SDK）**明确不读取 OAuth 凭据或系统钥匙串**，需 `ANTHROPIC_API_KEY`（一手，<https://code.claude.com/docs/en/headless>）——即"官方给脚本化用的那条路"要求你用 API Key，而不是订阅 |
| 最稳定（运行时） | ❌ 引入新故障面：进程启动开销、CLI 版本漂移、stdout/JSON 解析脆弱、**无真流式粒度**（只能按事件粒度）、**并发能力受限**（每请求一进程）、无法复用现有 `CancelRegistry` 的 httpx 取消语义 |
| 实现成本 | 中高（适配器 + 进程池 + 输出解析 + 错误码映射 + 版本探测） |
| 铁律关系 | ❌ **潜在冲突（E25）**：CLI 上游天然依赖厂商 CLI **自持凭据**（OAuth token / macOS 钥匙串 / `~/.codex/auth.json`），该凭据**不在网关的明文配置或环境变量内** → 与铁律 1「密钥只存本地明文配置或环境变量」（`AGENTS.md:12`）存在张力。**若强制走环境变量 API Key（`--bare` 路径）→ 相容；若走 CLI 自持凭据 → 冲突，需用户决策** |
| 结论 | **受限可选能力，默认关闭**。仅在"资源确实只有官方 CLI、且用户确认合规、且凭据路径与铁律 1 相容"时启用；必须在文档中显式标注合规风险。 |

#### 方案 5 · 网关实现 ACP Agent

| 维度 | 评价 |
|---|---|
| 语义匹配 | ❌ **范畴错配**：ACP 是"编辑器 ↔ coding agent"，网关不是 coding agent |
| 客户端覆盖 | ✅ 极广（C.2.1）——但覆盖的是"agent 入口"，不是"模型入口" |
| 结论 | **不推荐**。若未来用户想要"在 Zed/JetBrains 里直接用网关模型"，应走方案 2（那些编辑器也都支持自定义 base_url），而不是实现 ACP。 |

#### 方案对比总表

| 方案 | 方向 | 最直接 | 最稳定 | 最短路径 | 实现成本 | 兼容性代价 | 铁律关系 | 推荐 |
|---|---|---|---|---|---|---|---|---|
| 1 · CLI shell-out 调用 | 入站 | 中 | 中 | 差 | 中 | **极高** | 相容 | ❌ |
| **2 · CLI 作为统一入口/启动器 + 复用 HTTP** | 入站 | **高** | **高** | **高** | **低** | **无** | ⚠️ 潜在冲突（`mgw setup` 写入边界） | ✅ **主方案**（限定"仅打印"） |
| 3 · MCP Server | 入站 | 低 | 高 | 中 | 中 | 高 | 相容 | ❌（仅借鉴 framing） |
| **4 · CLI 上游适配器** | 出站 | 中 | 运行时低 / 协议高 | 中 | 中高 | 中（需新增 `transport` 轴） | ⚠️ 潜在冲突（凭据 vs 铁律 1）+ 程序性 | ⚠️ **受限可选** |
| 5 · ACP Agent | 入站 | 低 | 中 | 中 | 中高 | 高 | 相容 | ❌ |

### C.4 推荐方案（组合）

```
┌─ 下游（入站）─────────────────────────────────────────────────────┐
│ 方案 2：`mgw` CLI = 统一入口/启动器（不承载模型流量）              │
│   mgw setup trae|cursor|cherry|claude-code|codex   → 打印接入配置  │
│        ⚠️ 铁律边界：仅打印 / 仅写用户家目录；绝不写项目内 .xxx 目录  │
│   mgw models [--format table|md|openai]            → 打印生效清单  │
│   mgw start|stop|restart|status                    → 封装现有端点  │
│   工具仍走现有 HTTP：/v1/chat/completions（OpenAI 兼容，事实标准） │
│   自研工具可选：mgw serve --socket（Unix socket，借鉴 MCP stdio framing）│
└───────────────────────────────────────────────────────────────────┘
                              │
┌─ 网关内核（现有，零改动）─────▼───────────────────────────────────┐
│  auth → IR → scheduler(x/y/m) → adapters → stats                  │
└───────────────────────────────────────────────────────────────────┘
                              │
┌─ 上游（出站）─────────────────▼───────────────────────────────────┐
│ 方案 4：CLI 上游适配器（默认关闭，合规 + 铁律 1 双前置）             │
│   前置条件：① 用户确认该资源合规可用；② 已建 adapters/base 抽象      │
│            （按 tech-design.md:163 的 call()/list_models() 契约）； │
│            ③ 已加 resources[].transport 轴（须入 PRD）；            │
│            ④ 凭据路径与铁律 1 相容（强制环境变量 API Key）           │
│   优先级：低于"官方按量 API Key"与"官方 CLI + 官方 API Key"        │
└───────────────────────────────────────────────────────────────────┘
```

### C.5 诚实评估：CLI 模式是否真的更稳定？（本节是全文最重要的诚实声明）

> **本节已按核验 E7 / E9 全面修正**：draft 原表把「服务条款合规」「技术拦截」判为「**平局（都不行）**」，把「账号风控」判为「CLI 略优」。核验确认这些判断**强于官方原文**且**未披露来源冲突**，现更正如下。

| 风险类别 | API 模式（逆向/订阅授权） | CLI 模式（官方 CLI headless） | 结论 |
|---|---|---|---|
| **协议稳定性** | ❌ 差：平台改私有接口即失效，无 SLA | ✅ 好：跟随官方客户端，厂商自己维护兼容 | **CLI 胜** |
| **服务条款合规** | ❌ 违规（由第三方/网关代表用户路由订阅凭据） | ⚠️ **取决于形态**：由**网关/第三方代表用户**驱动 CLI 中转订阅凭据 → **违规**；**终端用户在本机**用**未修改**官方二进制 + **自有**订阅 → **官方明文不阻止**（证据 1-b） | **取决于「谁代表谁 + 凭据存哪」，不是「API vs CLI」** |
| **技术拦截** | ❌ 已发生（OAuth 在第三方客户端被拒） | ⚠️ 拦的是**凭据 + 客户端身份**，不是调用形态：官方二进制身份校验可能通过（`awesomeagents`），但**非交互/自动化/高频画像本身是风控信号**（`woodchen §6.4`） | **无法判定孰强，需标注未验证** |
| **账号风控** | ❌ 有 | ⚠️ **方向存在来源冲突（E9）**：`awesomeagents` 称拦截机制是"确认真实客户端身份、拒绝非官方二进制"（→ 支持"官方二进制指纹更干净"）；但 `woodchen §6.4` 明确把 `is_interactive: false` / `entrypoint: "sdk"` / 高频 + 大 token 列为**自动化滥用嫌疑**，§9.2 建议此类场景**用 API Key 而非 OAuth**（→ 反对）。而网关正是无人值守、非交互、高并发调用方 | **来源方向相反，未披露即偏颇；本报告不判定孰强，标注为未验证** |
| **凭据处理** | ❌ 需要提取/存储 token | ⚠️ **取决于凭据存哪**：若凭据留在厂商 CLI 自持存储、**网关不接触** → 不落入"collect, store, or intermediate"禁止；若网关为驱动 CLI 而**读取/落盘/中转** token → **同样违规** | **取决于实现，不是"都不行"** |
| **运行时稳定性** | ✅ 好：httpx 流式、并发、取消透传均已验证 | ❌ 差：进程开销、版本漂移、输出解析脆弱、无真流式、并发受限 | **API 胜** |
| **可观测性** | ⚠️ 中：逆向接口错误语义可能不标准 → 分类器退化 | ⚠️ 中：CLI 退出码/stderr 需自行映射，映射表本身是维护负担 | **平局** |
| **实现/维护成本** | 中 | 中高（需跟随 CLI 版本） | **API 胜** |
| **铁律 1 相容性** | ✅ 相容（凭据在明文配置/环境变量） | ⚠️ **潜在冲突**：CLI 自持凭据不在网关明文配置内；强制走环境变量 API Key 则相容 | **取决于凭据路径，需用户决策** |

> **必须明确告知用户的结论（已按 E7 修正）**：
>
> **① CLI 模式不能一概而论地"更违规"，也不能一概而论地"规避合规风险"。** 决定合规性的是三个变量，而不是「API 还是 CLI」：
> - **谁代表谁**：第三方/网关**代他人**路由订阅凭据 → 禁止；**用户自用**自己的订阅 → 明文允许。
> - **凭据存在哪**：网关**收集/存储/中转**会话 token → 禁止；凭据留在厂商客户端自持存储、网关不经手 → 不落入该禁止。
> - **是否修改官方二进制**：修改 → 禁止（证据 2）；未修改 → 允许。
>
> **② CLI 模式真正规避的是「网关存储/中转订阅凭据」这一点，并不规避「把订阅凭据喂给非官方客户端」这条限制。** 如果网关把 CLI 当**上游**、由**网关进程**去驱动 CLI 完成"代表用户发请求"，那仍落入证据 1 的禁止区。这个区别对方案选型**很关键**。
>
> **③ CLI 模式真正值得引入的理由是「协议稳定性」和「某些厂商只提供 CLI 不提供 API」这一客观事实，而不是"绕过风控"。** 运行时稳定性、并发能力、可观测性、维护成本四个维度上 CLI 均**劣于** API。
>
> **④ 如果用户的目标是"稳定合法地调用各家模型"，正解是：用各家官方的按量 API Key（这正是项目现有 `access_mode: api` 的定位），或走各家官方的商业/企业合作渠道。** 网关的价值（多资源聚合 + 故障切换 + 统一入口）在这个前提下**完全成立且无风险**；一旦引入"由网关代表用户中转订阅凭据"，网关就从"提高稳定性"变成"放大违规面"——因为它把单账号的违规使用放大成多账号、高并发的自动化流量。

---

## D. 模型清单下发与软件内模型切换

### D.1 `/v1/models` 现状与建议返回结构

**现状**（`api/openai_compat.py:36-44`）：

```python
data = [
    {"id": m.name, "object": "model", "created": 0, "owned_by": "model-gateway",
     "endpoint": m.endpoint, "group": m.group}
    for m in runtime.config.models if m.enabled   # FR-2.3：仅返回启用模型
]
return {"object": "list", "data": data}
```

**现状问题（代码事实）**：

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| 1 | `created` 硬编码 `0` | `openai_compat.py:40` | 个别客户端按 `created` 排序/展示会异常 |
| 2 | **`EnumEntry` 的丰富元数据一个都没下发**（`context_window / max_output / image_input / video_input / audio_input / reasoning / effort_levels / params_default / vendor / display`） | 对比 `enums/matcher.py:17-49` | 客户端无法自动填上下文长度（Trae 教程要求手填，是最高频失败点）、无法判断是否支持多模态/工具调用 |
| 3 | 只反映**模型开关**，不反映**资源可用性** | `openai_compat.py:42`（只过滤 `m.enabled`） | 某模型全部资源冷却中时，`/v1/models` 仍列出它 → 客户端会选到"暂时不可用"的模型 |
| 4 | 无 `aliases` 下发 | 对比 `enums/matcher.py:39` | 客户端不知道同一模型可用的别名（虽然网关侧能解析） |
| 5 | 无单模型详情端点 | — | 客户端只能全量拉取 |

**建议的返回结构**（**纯加法**：新增字段不破坏任何现有客户端；OpenAI 规范下客户端应忽略未知字段）：

```jsonc
{
  "object": "list",
  "data": [
    {
      // —— OpenAI 官方字段（对齐官方当前 schema）——
      "id": "deepseek-v4-flash",
      "object": "model",
      "created": 1757000000,          // 建议：由配置 mtime 或首次加载时间派生，替换硬编码 0
      "owned_by": "model-gateway",
      "shutdown_date": null,          // 对齐官方当前 schema（"2026 新增"之说无据，已删）

      // —— 网关扩展：展示与检索 ——
      "display_name": "DeepSeek V4 Flash",
      "aliases": ["deepseek-v4-flash-0731"],
      "group": "编程",
      "vendor": "DeepSeek",
      "endpoint": "chat",

      // —— 网关扩展：能力元数据（来源：EnumEntry，已是现成资产）——
      "context_window": 1048576,
      "max_output": 65536,
      "input_modalities": ["text", "image"],   // 由 image_input/video_input/audio_input 派生
      "output_modalities": ["text"],
      "capabilities": {
        "tools": true,            // 注：EnumEntry 目前无该字段，需新增或按 group 推断（未验证）
        "reasoning": true,
        "vision": true,
        "audio": false,
        "video": false
      },
      "reasoning_effort_levels": ["low", "high", "max"],
      "default_params": {"temperature": 1.0, "top_p": 1.0},

      // —— 网关扩展：运行态（现有 snapshot_by_resource 已能算，属纯组合）——
      "gateway": {
        "params_source": "gateway",     // 网关级参数是否生效（SystemModel.params 非空）
        "resources_total": 3,
        "resources_available": 3,
        "status": "active"              // active | degraded | unavailable
      }
    }
  ]
}
```

> **⚠️ 前置条件（新增，E5 + E27）**：`EnumEntry` 中 **Anthropic 2 条**（`claude-sonnet-4` / `claude-opus-4`，`enums/matcher.py:138-141`）**属性未取证**，上述字段对其全为空。**下发策略必须是「未取证的字段省略（不出现该 key）」，而不是输出 `null` / `[]`** —— 否则客户端会把"未取证"误判为"不支持"。该策略须写入实现与 PRD。

**可选兼容层**（若希望被"读 OpenRouter 格式"的客户端识别，**建议但不强制**）：
额外镜像 `architecture.input_modalities` / `architecture.output_modalities` 与 `supported_parameters[]`（OpenRouter 约定，来源 C.2.4）。**注**：此条属"无依据自创"，需先经用户确认。

**同时建议新增**：`GET /v1/models/{id}` 单模型详情（对齐 OpenRouter 的 `/api/v1/model/{author}/{slug}`），供客户端按需查询。

### D.2 各客户端如何获取模型列表（关键警示）

| 客户端 | 是否读 `/v1/models` | 实际行为 | 依据 |
|---|---|---|---|
| **Claude Code** | ✅ **会，但需显式开启** | `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` → 从网关 `/v1/models` 填充 `/model` 选择器；**默认关闭**；仅限 Anthropic 兼容网关；超时默认 3000ms（`CLAUDE_CODE_GATEWAY_MODEL_DISCOVERY_TIMEOUT_MS`）；"Discovered models are still filtered by an `availableModels` allowlist" | 一手 <https://code.claude.com/docs/en/env-vars> |
| **Trae** | ❌ **不读** | 教程要求**手填模型 ID**（并反复强调"无数的人都挂在 ID 上，请自己去查询"）+ 手填上下文长度 + 手填多模态开关 | **二手**（官方社区用户教程，作者非官方）<https://forum.trae.cn/t/topic/11480> |
| **Cherry Studio** | ❌ **不读** | 官方文档："点击「+ 添加」按钮，**手动添加**此提供商下您想要使用的模型 ID" | 一手 <https://docs.cherry-studio-ai.com/pre-basic/providers/zi-ding-yi-fu-wu-shang> |
| **Cursor** | ⚠️ **可能读**（未验证） | 二手来源称有"Auto-detect models from provider"开关，且模型名必须与 `/v1/models` 返回的 `data[].id` 一致，否则报 `Named Models` | 二手 <https://www.php.cn/faq/2930693.html>（**内容农场式文章，不足以支撑结论；未验证**） |
| **Codex CLI** | ⚠️ 未见于官方文档 | 配置内手写 `model` | 二手（多源一致，**未验证**） |

> **修正（E10）**：Trae 行依据等级由「一手（官方社区官方教程）」更正为「**二手（官方社区用户教程，作者 `JasonShane` 非 TRAE 官方）**」。**行为描述（不自动发现、需手填）经核验逐字吻合，结论不变。**

> **🔴 本报告最重要的 D 段结论**：
> **不能假设对接软件会自动读取 `/v1/models`。** 在 Trae 与 Cherry Studio（用户实际在用的两个）上，模型清单**必须由人手工填写**。
>
> 因此"把网关已生效的模型清单提供给对接软件"这件事，正确的交付形态是**三个并存**：
> 1. **机器可读**：`GET /v1/models`（补齐 D.1 扩展字段）——服务 Claude Code 等会读的客户端，以及自研工具；
> 2. **人可复制**：`GET /admin/api/models/export?format=md|csv|json`（**建议新增**）或 `mgw models --format md`，输出一张"模型 ID │ 显示名 │ 上下文 │ 模态 │ 推理档位"的表格，用户直接照着填进 Trae / Cherry Studio；
> 3. **一键配置**：`mgw setup trae` 之类，直接生成该工具需要的配置片段（见 C.4；**注意铁律边界：仅打印 / 仅写用户家目录**）。
>
> 另：**模型 ID 的稳定性至关重要**。因为客户端会把它写进本地配置，网关侧一旦改名/删除，客户端就报 `model_not_found`。→ 建议：
> - 系统模型 `name` 视为**对外契约**，改名走"新增 + 别名保留"而非原地改名（现有别名机制 `enums/matcher.py:163-170` 已支持，成本极低）；
> - `/v1/models` 的 `id` 与 `resolve_request_model` 的可解析集合存在差异（`/v1/models` 只输出规范名，`resolve_request_model` 支持别名与规范化）。**修正（E12）**：draft 断言这是「**有意的**宽进严出」——代码中**未见任何设计说明**，属**意图归因**。→ 更正为：「**该差异是否为有意设计，需向用户确认**；建议在文档中写明实际行为」。

### D.3 值得下发的模型元数据（业界约定对比）

| 元数据 | 网关现有资产 | OpenRouter 字段 | LiteLLM 字段 | 建议网关字段 |
|---|---|---|---|---|
| 上下文窗口 | ✅ `EnumEntry.context_window` | `context_length` | `model_info.max_input_tokens` | `context_window` |
| 最大输出 | ✅ `EnumEntry.max_output` | `top_provider.max_completion_tokens` | `model_info.max_output_tokens` | `max_output` |
| 输入模态 | ✅ `image_input / video_input / audio_input` | `architecture.input_modalities[]` | `model_info.supports_vision` | `input_modalities[]` + `capabilities.vision/audio/video` |
| 输出模态 | ⚠️ 隐含（都是 text；images 端点例外） | `architecture.output_modalities[]` | — | `output_modalities[]` |
| 工具调用 | ❌ **缺失**（EnumEntry 无该字段） | `supported_parameters` 含 `tools` | `model_info.supports_function_calling` | `capabilities.tools`（**需新增取证字段**） |
| 推理支持 | ✅ `EnumEntry.reasoning` | `supported_parameters` 含 `reasoning` | `model_info.supports_reasoning` | `capabilities.reasoning` |
| 推理档位 | ✅ `EnumEntry.effort_levels[]` | — | — | `reasoning_effort_levels[]` |
| 官方默认参数 | ✅ `EnumEntry.params_default{}` | `default_parameters` | — | `default_params{}` |
| 定价 | ⚠️ 有 `pricing[]` 配置节（P1 预留，`schemas.py:194-203`） | `pricing{prompt,completion,...}` | 映射自 model cost map | `pricing{}`（P1 启用后） |
| 内容审核 | ❌ 无 | `top_provider.is_moderated` | — | 不建议（本地自用无意义） |
| 端点类型 | ✅ `SystemModel.endpoint` | — | `mode`(chat/completion/embedding) | `endpoint`（已下发） |
| 模型别名 | ✅ `EnumEntry.aliases[]` | `canonical_slug` | — | `aliases[]` |
| 运行态可用性 | ✅ 可由 `snapshot_by_resource` 组合（`resources.py:183-218`） | — | — | `gateway.resources_available` |

> **注意**：`capabilities.tools`（是否支持函数调用）**当前数据源不存在**——`EnumEntry` 无对应字段，`BUILTIN_ENTRIES` 也没取证（`enums/matcher.py:67-142`）。若要下发，需按项目取证纪律（`decisions.md:13`、`AGENTS.md:31` Q24-④）**逐条从官方文档取证回填**，不能凭印象写。
>
> **另注（E5）**：上表「网关现有资产」列对 **Anthropic 2 条不成立**（属性全空）。下发时须按 D.1 的「未取证字段省略」策略处理。

### D.4 模型切换的用户体验方案

三个候选（可组合）：

#### 方案 A · 客户端侧切换（**推荐为主**）

形态：网关把每个"已启用系统模型"作为一个独立 `id` 下发；用户在 Trae / Cherry Studio / Cursor 的模型下拉里直接选。

| 维度 | 评价 |
|---|---|
| 网关改动 | **零**（现状即此形态，`/v1/models` 只返回 `enabled=true`，`openai_compat.py:42`） |
| 用户体验 | ✅ 直观：用户看到的模型名就是网关统一名，切换即选另一个 `id` |
| 稳定性 | ✅ 最高：不引入任何新路由语义；模型选择行为完全可预测 |
| 局限 | 用户需要在**每个工具里各配一遍**（Trae 手填、Cherry 手填）→ 这正是 D.2 的痛点，由 `mgw setup` / 导出清单缓解 |
| 依赖 | 需要"模型清单可见"（D.1 扩展 + D.2 的三种交付形态） |
| 铁律关系 | ✅ **相容**（零改动） |

#### 方案 B · 网关侧路由（虚拟模型名 + 策略）

形态：网关暴露少量**虚拟模型名**（如 `mg-auto` / `mg-fast` / `mg-strong`），由网关按策略决定实际调用哪个系统模型。

| 维度 | 评价 |
|---|---|
| 用户体验 | ✅ 极简：用户永远只选一个模型，网关自动选最合适的 |
| 网关改动 | ❌ **大**：现有 `resources.py` 的池是**资源级**（同一系统模型的多个资源，`resources.py:72, 82-105`），**不存在"模型级路由"能力**。要做需要在 `SystemModel` 之上再加一层"模型组 / 路由策略"，属于架构级新增 |
| 稳定性 | ⚠️ 中：虚拟模型的实际行为随网关策略变化，用户难以预测；策略 bug 会静默影响所有工具 |
| 可观测性 | ⚠️ 需要新增"策略决策"事件（现有事件行的 `system_model` 字段记录的是最终模型，`scheduler.py:181`） |
| 铁律关系 | ⚠️ **需用户翻案**：与 Q18-③「调度参数全局唯一·一套机制管控所有模型」（`tech-design.md:648`、`prd.md:500`）及 Q23-②「配置参数范围维持现状四类」（`AGENTS.md:31`）**有张力**；且属"无依据自创"，须先入 PRD |
| 结论 | **缓做**。等方案 A 跑顺、且有明确的"用户不想选模型"需求时再评估。**这条需要用户决策**。 |

#### 方案 C · 分组/档位别名（**推荐为辅**）

形态：利用现有 `group` 字段（`schemas.py:161`）与别名机制（`enums/matcher.py:163-170`），额外注册"档位模型名"作为**指向某系统模型的别名**，例如 `mg-fast` → `deepseek-v4-flash`、`mg-strong` → `deepseek-v4-pro`。

| 维度 | 评价 |
|---|---|
| 网关改动 | ✅ **极小**：`resolve_request_model` 已支持别名解析（`enums/matcher.py:272-274`）；只需在枚举池/别名表中登记 |
| 用户体验 | ✅ 好：既保留"选具体模型"的自由，又提供"按档位选"的便利 |
| 稳定性 | ✅ 高：别名解析失败会走 404 + 候选提示（`openai_compat.py:62-63`），行为可预测 |
| 局限 | 别名与目标模型是**静态映射**，不是动态策略（动态策略见方案 B）。**另注（E-提示）**：别名**不会出现在 `/v1/models`**，客户端仍需手填 |
| 铁律关系 | ✅ **相容**（复用既有别名机制，非自创） |
| 结论 | **推荐作为方案 A 的补充**；成本极低，可先做验证用户是否真的需要"档位选择" |

#### 推荐组合

```
阶段 1（必做）：方案 A + D.1 元数据补齐 + D.2 三种交付形态（清单导出 / mgw models / mgw setup）
阶段 2（低成本试点）：方案 C 档位别名（登记 2-3 个，观察用户是否使用）
阶段 3（待确认）：方案 B 网关侧策略路由（架构级新增，需用户确认需求 + 明确翻案 Q18-③）
```

---

## 落地建议与分期路线

> 前置声明：以下全部为**建议**，须经用户确认后写入 `docs/specs/`（PRD 为主）方可实施。
> **铁律关系标注口径**（本项目的硬约束，不可绕过）：
> - ✅ **相容** = 与铁律 1/4 及既有约定无冲突，可直接进入 spec 流程；
> - ⚠️ **潜在冲突需确认** = 不必然违规，但存在边界条件，**必须由用户明确边界后才能实施**；
> - ❌ **明确冲突需翻案** = 与已声明的 spec 或铁律直接冲突，**必须先经用户翻案 + 同步升版 spec**，否则不得实施。

### 决策点（必须先问用户，否则后续全是空转）

| # | 决策点 | 为什么必须先问 |
|---|---|---|
| **Q1** | 「对接了各个软件授权提取内部模型使用」**具体指哪家、哪种授权**？（Claude 订阅？Cursor 订阅？某国内厂商的 CodingPlan？） | **直接决定 B 段风险等级，必须保留为前置待确认项。** 若答案是"各家官方按量 API Key"，则 B 段风险几乎归零，C 段 CLI 上游模式**根本不需要做**；若是"订阅账号授权 + 由网关代用户路由"，则落入官方禁止区（证据 1）。 |
| **Q2** | 新增轴叫什么？建议 `resources[].transport: "http" \| "cli"`，与现有 `access_mode: api\|plan` **解耦** | 现有 `access_mode` 已被 UI 占用表示"凭据类型"（`resources.js:240,779-780`），复用会导致语义污染（A.5.3）。**铁律关系：潜在冲突（程序性）**——新字段属"无依据自创"，须先入 PRD。 |
| **Q3** | 是否接受"CLI 上游模式**不能一概而论**地规避 ToS 风险——合规与否取决于**谁代表谁 + 凭据存哪**"这个事实前提？ | §C.5 的核心结论（已按 E7 修正）。若用户不接受，则 C 段方案 4 应直接砍掉。 |
| **Q4** | 是否需要"模型清单导出"与"一键配置"？（D.2 的三种交付形态） | Trae/Cherry Studio 手填模型 ID 是实际最高频痛点，但这是**新增功能**，须用户确认。**铁律关系：`mgw setup` 的"写入"部分为潜在冲突**（见 1.2）。 |
| **Q5** | 是否需要"档位别名"（方案 C）或"网关侧策略路由"（方案 B）？ | 方案 B 是架构级新增且与 Q18-③ 有张力，**需用户明确翻案**；方案 C 成本极低、相容。 |
| **Q6** | **`adapters/base.py` 的接口签名：按 `tech-design.md:163` 既有的 `call()/list_models()`，还是采用 draft 的 `chat_nonstream/chat_stream/...`？** | **本报告唯一的明确铁律冲突（E22）**。选前者 = 落实既有设计（相容）；选后者 = **对 tech-design 的修订提案，需走 spec 变更流程并经用户翻案**。 |

### 分期路线

#### 阶段 0 · 零风险修补（不依赖任何决策点，纯加法）

| 项 | 内容 | 触及文件 | 风险 | 铁律关系 |
|---|---|---|---|---|
| 0.1 | `/v1/models` 补齐 `EnumEntry` **已取证**元数据（`context_window / max_output / input_modalities / capabilities.reasoning / reasoning_effort_levels / default_params / aliases / display_name / vendor`）+ `created` 替换硬编码 0 + `shutdown_date: null`。**前置（E5/E27）：属性未取证的条目（Anthropic 2 条）必须「省略字段」而非下发 null** | `api/openai_compat.py:36-44` | 极低（纯加法） | ⚠️ **潜在冲突（程序性）**：新增**对外契约字段**须先入 PRD（铁律 4） |
| 0.2 | `/v1/models` 增加 `gateway.resources_total / resources_available / status`（复用 `snapshot_by_resource`，`resources.py:183-218`） | 同上 | 极低 | ✅ 相容（纯组合，无新增契约语义） |
| 0.3 | 新增 `GET /v1/models/{id}` 单模型详情 | `api/openai_compat.py` | 极低 | ⚠️ **潜在冲突（程序性）**：新端点须先入 PRD；鉴权由 `/v1/` 前缀自动覆盖（`api/auth.py:42`） |
| 0.4 | 新增模型清单导出端点（`/admin/api/models/export?format=md\|csv\|json`） | `api/admin.py` | 低 | ⚠️ **潜在冲突（程序性）**：新端点须先入 PRD。管理端免鉴权是项目**已定论**的取舍（`tech-design.md:573` 风险 #24），非本建议引入 |
| 0.5 | `normalize_name` 补"渠道前缀剥离"（`ACTIVE.md` T2 已备案的实现缺口；PRD FR-1.4 已要求「忽略厂商前缀」） | `enums/matcher.py:148-155` | 低（需补测试） | ✅ **相容，且非自创**（落实 PRD FR-1.4） |
| 0.6 | `capabilities.tools` 逐条官方取证回填 `EnumEntry`（或明确标"未取证"不下发） | `enums/matcher.py` | 低（须遵守取证纪律） | ✅ 相容（须逐条官方域取证，`decisions.md:13`） |
| 0.7 | **（新增，E26）** 对账 `tech-design.md:191` 声明的两项校验（preset 存在于注册表 / vendor_model 存在于配置或枚举池）与 `config/schemas.py:219-255` 的实现差距 → 决定"补实现"或"降版 spec" | `config/schemas.py`、`docs/specs/tech-design.md` | 低 | ⚠️ **潜在冲突（程序性）**：涉及 spec 与代码对账，须用户裁决方向 |

#### 阶段 1 · 下游 CLI 入口（方案 2，低风险高收益）

| 项 | 内容 | 依赖 | 铁律关系 |
|---|---|---|---|
| 1.1 | 新增 `scripts/` 或独立 `mgw` 入口（建议放 `scripts/mgw.py` 或 `model_gateway/cli.py`，**须先与用户确认目录归属**——`mg-directory-layout.mdc:16-20` 规定 `model_gateway/` 只放源码、`scripts/` 放脚本） | — | ✅ **相容（有条件）**：draft 已主动标注"须先确认目录归属"，核验认定为**加分项**，予以保留 |
| 1.2 | `mgw status` / `mgw models` / `mgw setup <tool>` | 阶段 0.4 | ⚠️ **潜在冲突需确认（E24）**：`mg-directory-layout.mdc:10` 明令 `.claude/`、`.trae/`、`.workbuddy/` 等 `.xxx` 工具目录「**一律不维护、不更新、不写入**」。**`mgw setup` 必须限定为「仅打印，或仅写用户家目录的工具配置；绝不写项目内 `.xxx` 目录」**——**这条边界需要用户确认后才能实施** |
| 1.3 | 文档：在 `docs/specs/` 增加"CLI 接入指引"，在管理界面「API 接入」页补 CLI 入口说明 | 1.2 | ✅ 相容（`docs/specs/` 正是 `mg-directory-layout.mdc:11` 规定的需求真相目录） |

#### 阶段 2 · 抽象层补齐（为任何新对接模式铺路，见 A.5）

| 项 | 内容 | 依赖 | 铁律关系 |
|---|---|---|---|
| 2.1 | `adapters/base.py` 补真实 `Protocol`/ABC。**（E22 修正）默认按 `tech-design.md:163` 已声明契约**：`async def call(resource, ir_request) -> IRResponse \| AsyncIterator[IREvent]` + `async def list_models(resource)`；`chat_nonstream/chat_stream/images_generate/aclose` 作为具体适配器内部方法保留。**若用户坚持 draft 的扁平签名 → 必须标注「对 tech-design 的修订提案，需走 spec 变更流程」** | Q6 | ✅ **相容**（按 spec 契约，落实既有设计）<br>❌ **明确冲突需翻案**（若采用 draft 签名且不升版 spec —— 触碰铁律 4） |
| 2.2 | `Runtime._apply` 改为按资源分派适配器；`Runtime.adapters` 类型泛化 | 2.1 | ✅ **相容，且非自创（E23）**：`tech-design.md:162` 已声明「按资源 `protocol` 字段选择」，属落实既有设计 |
| 2.3 | `resource.protocol` 补齐消费点（或删除该字段，消除"看似支持实则不支持"） | 2.2 | ✅ **相容，且非自创（E23）**：同 2.2，`tech-design.md:162` 已声明该分发设计 |
| 2.4 | 补"适配器未注册"的明确错误语义（替换 `scheduler.py:214` 的误导性文案） | 2.2 | ✅ 相容（文案修正） |
| 2.5 | **（新增，E21）** 评估 `config/presets.py` 预设字段扩展（新增 `transport` 轴时，预设注册表很可能需同步扩展，否则"CLI 资源"无法从预设带入） | Q2 | ⚠️ **潜在冲突（程序性）**：涉及预设数据契约变更，须先入 PRD |

#### 阶段 3 · 上游 CLI 适配器（方案 4，**合规 + 铁律 1 双前置，默认关闭**）

| 项 | 内容 | 前置条件 | 铁律关系 |
|---|---|---|---|
| 3.1 | 新增 `resources[].transport: "http" \| "cli"` + `resources[].cli{command, args, ...}`（**须经用户确认写入 PRD**） | Q2 / Q3 | ⚠️ **潜在冲突（程序性）**：属"无依据自创"，须先入 PRD。与铁律 1/2/3 无直接冲突 |
| 3.2 | `adapters/cli_out.py`：调用厂商 CLI headless 模式，把 stdout 归一化为 OpenAI chunk；退出码/stderr → `UpstreamError` 映射表 | 阶段 2 | ❌ **潜在冲突需用户决策（E25）**：CLI 上游天然依赖厂商 CLI **自持凭据**（OAuth token / macOS 钥匙串 / `~/.codex/auth.json`），**不在网关明文配置或环境变量内** → 与铁律 1「密钥只存本地明文配置或环境变量」（`AGENTS.md:12`）**存在张力**。<br>**结论：若强制走环境变量 API Key（`--bare` 路径）→ 相容；若走 CLI 自持凭据 → 冲突，需用户决策** |
| 3.3 | 合规开关：默认关闭 + 启用时 UI 显式二次确认 + 文档标注风险 | Q3 | ✅ 相容 |
| 3.4 | 进程池与超时/取消语义适配（现有 `CancelRegistry` 基于 httpx task，进程取消需另做） | 3.2 | ✅ 相容 |

### 与项目既有约定的一致性检查（已按 E22/E24/E25 补齐）

| 项目铁律 / 约定 | 本方案是否冲突 | 说明 |
|---|---|---|
| 全明文配置（`AGENTS.md:12`） | ⚠️ **阶段 3.2 潜在冲突** | `transport` / `cli` 字段本身走 YAML 明文 ✅；但 **CLI 上游若走厂商 CLI 自持凭据（钥匙串 / OAuth 文件）→ 违反"密钥只存本地明文配置或环境变量"** → **需用户决策凭据路径（E25）** |
| 纯本地运行 / 无远程更新（`AGENTS.md:12`） | ✅ 无冲突 | `mgw` 是本地命令；模型清单由客户端本地拉取，无远程下发 |
| 无远程下发机制 | ✅ 无冲突 | 建议的导出端点/CLI 都是**本地主动拉取**，非推送 |
| 无依据自创禁止（`mg-00-first-principles.mdc:11`、`AGENTS.md:15`） | ⚠️ **程序性，必须遵守** | 本报告所有新增字段/端点/UI 均为**建议**，须用户确认后写入 `docs/specs/`。**唯一的实质违反是 E22（适配器接口签名）**，已按 spec 契约修正 |
| **AI 工具目录边界（`mg-directory-layout.mdc:10`）** | ⚠️ **潜在冲突（E24，draft 漏检）** | `.claude/`、`.trae/`、`.workbuddy/` 等其它 `.xxx` 工具目录「**一律不维护、不更新、不写入**」→ **`mgw setup` 的"写入"行为必须限定为「仅打印 / 仅写用户家目录」** |
| 目录分流（`mg-directory-layout.mdc:16-20`） | ✅ 相容（有条件） | `mgw` 入口须先确认放 `scripts/` 还是 `model_gateway/`；draft 已主动标注 ✅ |
| 调度参数全局唯一（Q18-③ / Q23-②） | ⚠️ **需用户翻案** | 方案 B（模型级路由策略）会引入"模型级行为差异"，与"一套机制管控所有模型"的既有定论**有张力**，须用户明确翻案（`tech-design.md:648`、`prd.md:500`、`AGENTS.md:31`） |
| 证据纪律（`decisions.md:13`） | ⚠️ **需注意** | `capabilities.tools` 等新增元数据必须逐条官方取证，不能凭印象填 |
| **规矩 4 诚实必附证据（`mg-work-rules-redlines.mdc:11,24`）** | ✅ 已遵守 | 本报告所有结论附 `file:line` 或 URL；未验证项显式标注。**修正 E7/E8/E9/E10 正是为满足该规矩** |
| **规矩 8 同问题 2 次未解决即停手升层（`mg-work-rules-redlines.mdc:12,28`）** | ✅ 无冲突 | 本报告为调研，未进入实施迭代 |
| **规矩 12 零垃圾红线（`mg-work-rules-redlines.mdc:32`）** | ✅ 无冲突 | 本定稿为文档产出，未在源码目录留下任何残留 |
| **规矩 13 Git 推送红线（`mg-work-rules-redlines.mdc:17,33`）** | ✅ 无冲突 | 本次调研**未执行任何 git 操作**（含 commit / push） |
| **规矩 14 提交前自检（`mg-work-rules-redlines.mdc:34`）** | ✅ 无冲突 | 本次未提交任何改动；`docs/research/` 与 `docs/research/drafts/` 均属文档目录 |

> **汇总（对应结论先行第 15 条）**：21 条落地建议中 —— **明确冲突 1 条（2.1 若采用 draft 签名，需翻案）**、**潜在冲突 3 条（1.2 `mgw setup` 写入边界、3.2 CLI 上游凭据 vs 铁律 1、0.1/0.3/0.4/2.5 的程序性入 PRD）**、**需用户翻案 1 条（方案 B 模型级策略路由 vs Q18-③）**、其余 16 条与铁律相容。
> **draft 自己已正确标注了 #1/#6/#7/#14/#19 的程序性约束（加分项，本定稿保留）；draft 漏的是 #8（`mgw setup` 边界）、#10（适配器接口）、#15（CLI 凭据）——本定稿已全部补上。**

> **另需提示（`mg-directory-layout.mdc:17`）**：`docs/` 只允许「需求/架构/设计真相（specs）+ 活跃任务（changes）」，`docs/research/` 不在列举内。本报告与既有 `01/02/03` 调研同属**既有安排**（非本报告新增），仅供用户知悉。

---

## 参考来源清单

> 抓取时间：**2026-09-22**（除标注外）。一手 = 官方文档 / 官方仓库；二手 = 社区帖 / 博客 / 媒体报道（按项目取证纪律 `decisions.md:13`，二手仅作现象参考，不作机制结论）。
> **核验结论**：23 条 URL **全部可达，零编造**；分级已按 E10 修正 1 条。

### 一手（官方）

| # | 来源 | 用途 |
|---|---|---|
| 1 | <https://code.claude.com/docs/en/env-vars> | `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY` / `ANTHROPIC_CUSTOM_MODEL_OPTION` 等（C.1、D.2） |
| 2 | <https://code.claude.com/docs/en/legal-and-compliance> | OAuth 第三方使用禁令原文、**限定段落（E7 补引）**、Claude Code 二进制不可修改、不得中转（B.2） |
| 3 | <https://code.claude.com/docs/en/headless> | `-p/--print`、`--output-format text\|json\|stream-json`、`--bare`（不读 OAuth）(C.3 方案 4、C.5) |
| 4 | <https://github.com/agentclientprotocol/agent-client-protocol> | ACP 定义 / JSON-RPC / 版本 1 / 未定义模型清单（C.2.1）。**注：README 未载明 stdio，亦无 "Zed-led" 表述（E13）** |
| 5 | <https://zed.dev/acp> | ACP 官方站："Created by Zed, grown by a community…"（C.2.1） |
| 6 | <https://www.jetbrains.com/acp/> | ACP "developed openly by JetBrains and Zed"（C.2.1） |
| 7 | <https://agentclientprotocol.com/overview/clients> | ACP 客户端生态清单（C.2.1） |
| 8 | <https://modelcontextprotocol.io/specification/2026-07-28/basic/transports> | MCP stdio / Streamable HTTP / 自定义传输 / Unix socket 复用 stdio framing（C.2.2） |
| 9 | <https://github.com/router-for-me/CLIProxyAPI> | CLI→API 先例（C.2.3）。**注：WebSocket / 函数调用 / 多模态三项未逐项核实** |
| 10 | <https://github.com/Senselegend/CLIProxyAPI-UI> | 同上（UI 变体，确为 fork） |
| 11 | <https://openrouter.ai/docs/guides/overview/models> | 模型元数据字段全集（C.2.4、D.3） |
| 12 | <https://developers.openai.com/api/reference/resources/models/methods/list> | `/v1/models` 官方 schema 含 `shutdown_date`（C.2.4、D.1）。**注："2026 新增"无据（E14）** |
| 13 | <https://docs.litellm.ai/docs/proxy/model_management> | LiteLLM `/v1/models` + `/model/info` + `model_info` 自定义元数据（C.2.4、D.3） |
| 14 | <https://docs.cherry-studio-ai.com/pre-basic/providers/zi-ding-yi-fu-wu-shang> | Cherry Studio 自定义服务商 = 手填模型 ID（C.1、D.2） |

### 二手（现象参考，未验证）

| # | 来源 | 用途 | 置信度 |
|---|---|---|---|
| 15 | <https://forum.trae.cn/t/topic/11480> | Trae 自定义模型教程 v4.0：手填模型 ID / 上下文 / 多模态（C.1、D.2）。**修正（E10）：由「一手（官方）」移入二手——作者 `JasonShane` 为社区用户，非 TRAE 官方；内容经核验逐字吻合** | **中高（内容核实无误，但作者非官方）** |
| 16 | <https://winbuzzer.com/2026/02/19/anthropic-bans-claude-subscription-oauth-in-third-party-apps-xcxwbn/> | Anthropic OAuth 拦截时间线（2026-01-09 起拦截、2026-02-19 文档澄清）。**同文含反向陈述（E8 已补引）** | 中高（与来源 2 官方原文互相印证；**但政策口径自相矛盾**） |
| 17 | <https://awesomeagents.ai/news/claude-code-oauth-policy-third-party-crackdown/> | 印证 2026-01-09 服务端拦截 + 封号；载明拦截机制为"确认真实客户端身份、拒绝非官方二进制" | 中 |
| 18 | <https://zhuanlan.zhihu.com/p/2055601319893786836> | 国内订阅封号现象 | 低（个人自述） |
| 19 | <https://woodchen.ink/archives/claude-code-封号机制深度探查报告> | 声称的封号机制（设备指纹/遥测）；**§6.4 自动化滥用检测反方向支持"网关画像高危"（E9）** | **低（未验证，基于已泄露源代码，不可作机制依据）** |
| 20 | <https://cloud.tencent.com/developer/article/2624427> | 逆向中转产业链乱象 | 中（现象层面） |
| 21 | <https://www.php.cn/faq/2930693.html> | Cursor `Named Models` 报错与 `/v1/models` 关系 | **低（内容农场式文章，不足以支撑结论；未验证）** |
| 22 | <https://airelayrank.com/zh/guides/codex-cli-api-relay-config/> | Codex CLI `config.toml` `model_providers` 字段 | 中（多源一致，未在官方文档验证） |
| 23 | <https://devpress.csdn.net/v1/article/detail/162196259> | 同上 | 中 |

---

## 证据附录（file:line 清单）

### 项目文档（一手）

| 主题 | 位置 |
|---|---|
| 项目定位 / 铁律 / 上下文装配 | `AGENTS.md:5-31` |
| 铁律 1 全明文·纯本地·无远程更新 | `AGENTS.md:12` |
| 铁律 4 无依据自创禁止 | `AGENTS.md:15` |
| 第一性原理（唯一依据=需求真相+用户确认；先判层；诚实验收） | `.cursor/rules/mg-00-first-principles.mdc:11-19` |
| 目录分流与信息源边界 | `.cursor/rules/mg-directory-layout.mdc:8-23` |
| **AI 工具目录边界（`.xxx` 目录不写）** | `.cursor/rules/mg-directory-layout.mdc:10` |
| **工作红线（规矩 4 诚实必附证据 / 8 停手升层 / 12 零垃圾 / 13 Git 红线 / 14 提交前自检）** | `.cursor/rules/mg-work-rules-redlines.mdc:11-34` |
| 关键决策（模式二分 api/plan；商汤双端点；取证纪律；Q24 三级优先级） | `.cursor/memory/decisions.md:5-22` |
| 坑位表（官网取证：优先 `curl -sL` 直取官方域；第一方 `/v1/models` 是金矿） | `.cursor/memory/pitfalls.md:28` |
| 活跃待办（T1 模型目录合一 / T2 渠道前缀剥离 / T4 厂商 /models 拉取 / **T6 无 git（已过期）**） | `docs/changes/ACTIVE.md:1-40`（T6 在 `:27`） |
| 架构分层图 / 运行形态 | `docs/specs/tech-design.md:14-56` |
| 请求生命周期十步 | `docs/specs/tech-design.md:75-90` |
| 入站端点表 | `docs/specs/tech-design.md:96-112` |
| IR 设计原则（透传优先） | `docs/specs/tech-design.md:114-128` |
| 调度核心 / 错误分类表 | `docs/specs/tech-design.md:130-155` |
| 出站适配层 / **适配器接口（`call()`/`list_models()` 契约）** / **按资源 `protocol` 分派** | `docs/specs/tech-design.md:157-163`（接口在 `:163`，分派在 `:162`） |
| 配置中心 / 校验规则（**含两项未实现的校验，E26**） / 模型开关 / 资源开关 / 预设注册表 / 运行参数表 | `docs/specs/tech-design.md:186-219`（校验声明在 `:191`，预设扩展原则在 `:194`） |
| 统计与日志（事件行格式） | `docs/specs/tech-design.md:221-247` |
| Web 管理界面七页 | `docs/specs/tech-design.md:249-261` |
| 系统运行控制与单实例锁 | `docs/specs/tech-design.md:263-315` |
| 调度精确语义 §5.2 伪代码 / §5.3 生效集 / §5.5 超时预算 | `docs/specs/tech-design.md:346-474` |
| 流式边界（首帧转发判定） | `docs/specs/tech-design.md:478-489` |
| 代码目录结构 | `docs/specs/tech-design.md:493-542` |
| 风险表（含 #24 管理端免鉴权暴露面） | `docs/specs/tech-design.md:546-573` |
| 确认点记录（含 Q18-① 推翻管理鉴权；**Q18-③ 调度参数全局唯一**） | `docs/specs/tech-design.md:643-656`（Q18-③ 在 `:648`） |
| PRD 接入模式定义（api/plan） | **`docs/specs/prd.md:30`（§1.4）** |
| PRD 术语与核心概念（资源 / 映射条目 / 系统模型） | **`docs/specs/prd.md:47-68`（§2）** |
| PRD 统一 API 端点 | `docs/specs/prd.md:73` |
| PRD FR-1.4 忽略厂商前缀 | `docs/specs/prd.md:115` |
| PRD 模型启用开关与 `/v1/models` | `docs/specs/prd.md:144-145, 205, 500` |
| PRD 配置 schema 示意 | `docs/specs/prd.md:374-378` |
| 样例配置（权威示例） | `config.example.yaml:41-70` |
| **`.gitignore` 的 `data/` 规则** | **`.gitignore:3`** |
| 真实运行配置（含明文 Key，勿外泄；**131 行**） | **`data/config.yaml:1-131`** |
| **`data/config.yaml` 第 7 个系统模型（images）** | **`data/config.yaml:122-130`** |

### 源码（一手）

| 主题 | 位置 |
|---|---|
| 包版本 | `model_gateway/__init__.py:6` |
| 应用装配 / 路由注册 / 中间件 / 静态挂载 | `main.py:165-214` |
| 路由注册三行 | `main.py:182-184` |
| `/health` 返回结构 | `main.py:186-203` |
| 中间件注册（Auth + StaticNoCache） | `main.py:206-208` |
| `Runtime` 聚合 | `main.py:52-74` |
| `Runtime._apply`（资源重建 / 参数映射 / 适配器构建） | `main.py:76-105` |
| **适配器硬编码 OpenAIOutAdapter** | `main.py:95-105` |
| 热重载 mtime 轮询 | `main.py:237-255` |
| `main()` 启动序列 + 单实例锁 + execv 重启 | `main.py:288-328` |
| 鉴权豁免前缀 / Anthropic 前缀 | `api/auth.py:15-16` |
| 鉴权主流程 | `api/auth.py:37-64` |
| 令牌提取（Bearer / x-api-key / x-goog-api-key） | `api/auth.py:66-79` |
| 鉴权错误体分形 | `api/auth.py:81-92` |
| **`GET /v1/models`** | `api/openai_compat.py:36-44` |
| 模型解析（404 / model_disabled / candidates） | `api/openai_compat.py:47-72` |
| 端点类型校验（400 endpoint_mismatch） | `api/openai_compat.py:75-86` |
| **`POST /v1/chat/completions`** | `api/openai_compat.py:101-144` |
| 流式延迟提交 + 心跳 + error 帧 | `api/openai_compat.py:147-235` |
| **`POST /v1/images/generations`** | `api/openai_compat.py:238-286` |
| Anthropic 请求转换 | `api/anthropic.py:55-161` |
| Anthropic 非流式响应转换 | `api/anthropic.py:166-199` |
| Anthropic 流式编码器 | `api/anthropic.py:204-311` |
| **`POST /v1/messages`** | `api/anthropic.py:316-366` |
| 管理端点全集（**14 条**，行号见 A.1.2 表） | `api/admin.py:110/122/184/224/247/260/363/384/426/455/465/507/520/536` |
| ID/密钥自动生成 | `api/admin.py:314-360` |
| 配置读（脱敏） | `api/admin.py:363-372` |
| 配置写（校验→原子写→热重载） | `api/admin.py:384-423` |
| `GatewayError` 与统一 error 格式 | `core/scheduler.py:40-100` |
| `CallCtx`（请求绑定配置快照） | `core/scheduler.py:103-139` |
| `Scheduler._adapter`（误导性错误文案） | `core/scheduler.py:211-215` |
| **`_out_body`（参数注入 + 每次尝试重算）** | `core/scheduler.py:223-232` |
| 兜底状态码选择 | `core/scheduler.py:234-244` |
| 切换事件落盘 | `core/scheduler.py:246-259` |
| 退避可打断 sleep | `core/scheduler.py:261-270` |
| usage 口径（vendor / estimated） | `core/scheduler.py:272-280` |
| `_log` 方法本体 | `core/scheduler.py:282-283` |
| **非流式 finally 收尾（`CancelledError → aborted` + `finally → _log`，E20 补引）** | **`core/scheduler.py:292-299`** |
| **非流式统一执行 `_execute_inner`** | `core/scheduler.py:301-458` |
| 六类错误的处置分支 | `core/scheduler.py:354-418` |
| `execute_chat` | `core/scheduler.py:462-474` |
| `execute_images` | `core/scheduler.py:476-492` |
| **`stream_chat`（延迟提交 / committed 边界）** | `core/scheduler.py:496-722` |
| 流式 usage/文本累积 + model 名替换 | `core/scheduler.py:726-744` |
| 资源展示名口径 | `core/resources.py:20-29` |
| `ResourceState`（状态 / C / cooldown / in_flight） | `core/resources.py:32-64` |
| `ResourceManager` + `rebuild`（状态按 resource_id 保留） | `core/resources.py:67-117` |
| **`pick_and_acquire`（生效集 + 在途最少）** | `core/resources.py:120-144` |
| bench / disable / invalidate / note_failure / note_success | `core/resources.py:151-168` |
| 冷却时长按 access_mode 取 | `core/resources.py:170-174` |
| `snapshot_by_resource`（资源级聚合视图） | `core/resources.py:183-218` |
| `ReasoningSpec` + `merge_reasoning`（三级合并） | `core/ir.py:17-55` |
| **`apply_model_params`（工具传参 > 网关设置 > 厂商内置）** | `core/ir.py:58-70` |
| `lift_reasoning_from_body`（入站提升防双注入） | `core/ir.py:73-91` |
| `inject_reasoning_into_body`（出站注入 + 配对归一化） | `core/ir.py:94-111` |
| `IRRequest` | `core/ir.py:114-122` |
| `chunk_is_content`（首帧判定） | `core/ir.py:149-158` |
| `normalize_stream_chunk`（思考字段归一化） | `core/ir.py:161-174` |
| ErrorClass 六类 + 厂商 type 表 | `core/errors.py:17-35` |
| `UpstreamError`（含 `no_failover`） | `core/errors.py:38-64` |
| `extract_error_type` | `core/errors.py:67-81` |
| **`ErrorClassifier.classify`（四级优先级）** | `core/errors.py:84-127` |
| 取消注册表 + 断连探测 | `core/cancel.py:13-76` |
| 单实例锁写/获取/释放 | `core/instance_lock.py:52-64, 78-108, 111-115` |
| 枚举字面量（Endpoint / AccessMode / Protocol / ErrorClass） | `config/schemas.py:17-22` |
| `GatewayConfig`（运行参数） | `config/schemas.py:46-65` |
| `SchedulingConfig`（x/y/m/冷却） | `config/schemas.py:68-81` |
| `ErrorRule` | `config/schemas.py:84-95` |
| `ReasoningDefault` | `config/schemas.py:98-106` |
| **`Resource`（access_mode / protocol 定义）** | `config/schemas.py:109-129` |
| `ModelResource` | `config/schemas.py:132-137` |
| `PARAM_RANGES` + `SystemModel` + `_validate_params` | `config/schemas.py:142-191` |
| `Pricing`（P1 预留） | `config/schemas.py:194-203` |
| `AppConfig` + 跨节校验（**含 E26 的两项未实现校验**） | `config/schemas.py:206-255` |
| 厂商预设注册表（3 条 + **扩展原则 `presets.py:6-8`**，E21） | `config/presets.py:6-8, 17-45` |
| 配置加载 / 校验错误格式化 | `config/loader.py:33-54` |
| 配置原子写 | `config/loader.py:57-75` |
| **`EnumEntry`（含 Q24 七类元数据）** | `enums/matcher.py:17-49` |
| 内置 15 条模型目录 + 取证来源注释 | `enums/matcher.py:52-142` |
| **Anthropic 2 条「属性未取证」注释（E5）** | `enums/matcher.py:137-141` |
| `normalize_name`（**缺渠道前缀剥离**） | `enums/matcher.py:148-155` |
| `EnumPool.match`（精确/别名/规范化） | `enums/matcher.py:158-186` |
| `load_enum_pool` | `enums/matcher.py:229-256` |
| `resolve_request_model` | `enums/matcher.py:259-280` |
| **`adapters/base.py` 仅一段 docstring（5 行），无任何代码** | `adapters/base.py:1-5` |
| `adapters/anthropic_out.py` 仅 1 行 docstring | `adapters/anthropic_out.py:1` |
| `adapters/gemini_out.py` 仅 1 行 docstring | `adapters/gemini_out.py:1` |
| 适配器接口说明（docstring 声明） | `adapters/__init__.py:1-6` |
| 出站适配器构造（trust_env 策略） | `adapters/openai_out.py:42-58` |
| `chat_nonstream` | `adapters/openai_out.py:100-119` |
| `chat_stream`（SSE 解析） | `adapters/openai_out.py:122-161` |
| `images_generate` | `adapters/openai_out.py:164-181` |
| `list_models`（**已有但未被任何调用点使用**） | `adapters/openai_out.py:183-191` |
| Key 脱敏 / 错误摘要 | `stats/events.py:19-35` |
| 事件单写队列 / 保留策略 | `stats/events.py:38-96` |
| UI 接入模式文案（"API（按量计费）/ Plan（订阅 / 积分制）"） | `web/static/js/pages/resources.js:240, 779-780` |
| UI 资源草稿默认值（access_mode/protocol） | **`web/static/js/pages/resources.js:193, 505, 822, 826, 1017-1018`**（`1018` 为 `protocol`，E19 补） |
| **资源池设置页（原「系统模型」，Q24 · 2026-09-05 定版）** | `web/static/js/pages/models.js:1-12, 21-50` |

### 关键「未验证 / 缺口」清单

| # | 事项 | 状态 |
|---|---|---|
| 1 | `resource.protocol` 字段是否应删除（当前无消费点，但 `tech-design.md:162` 已声明应有分派） | **需用户裁决** |
| 2 | `capabilities.tools`（函数调用支持）数据源 | **不存在，需官方取证回填** |
| 3 | Codex CLI `config.toml` 字段名 | 二手多源一致，**未在官方文档验证** |
| 4 | Cursor 是否真的拉取 `/v1/models` | 仅二手（**内容农场式文章**），**未验证**（官方文档站抓取失败） |
| 5 | Cherry Studio 部分版本是否有"获取模型列表"按钮 | 官方文档口径为手填，**未验证其它版本** |
| 6 | ACP 是否将正式定义模型清单 | README 未定义；仅有 unstable `providers/*` 提交线索，**未验证** |
| 7 | **用户实际使用的订阅账号类型与厂商** | **未知，必须问**（决定 B 段风险等级）——**Q1，必须保留** |
| 8 | `ACTIVE.md` T6「项目无 git 仓库」 | **与实测冲突**（`ACTIVE.md:27` vs `git status` 正常返回 + 根目录存在 `.git/`） |
| 9 | 商汤 `plan` 模式的额度窗口精确语义 | 项目以 `cooldown_seconds_plan=18000`（5h）近似，**官方口径未在本报告验证** |
| 10 | 网关自身的 `mgw` CLI 应放在 `model_gateway/` 还是 `scripts/` | **需用户裁决**（受 `mg-directory-layout.mdc:16-20` 约束） |
| 11 | **ACP「默认 stdio」** | **无法核实**：官方 README 未载明；据实现惯例推断（E13a） |
| 12 | **`shutdown_date` 是否为"2026 官方 schema 新增"** | **无法核实**：字段存在已确认，新增时间无据（E14） |
| 13 | **Anthropic 引文「Using OAuth tokens…in any other product, tool, or service」** | **部分无法核实**：出现在两篇二手报道中并标注 "via Claude Code Docs"，但**当前 `legal-and-compliance` 页面不含该句**（可能属 Consumer Terms 或页面已改版） |
| 14 | **Anthropic 对文档变更的官方口径** | **存在冲突**（"docs clean up" vs "新增禁令"），**无法判定** → 本报告不据此判定政策生效日（E8） |
| 15 | CLIProxyAPI 的 WebSocket / 函数调用 / 多模态支持 | **未逐项核实**（已核实：定位、包装对象、round-robin、DNS-SD、OAuth、赞助商） |
| 16 | **`/v1/models` 只输出规范名、`resolve_request_model` 支持别名** 是否为有意设计 | **代码无设计说明，需向用户确认**（E12） |
| 17 | **`tech-design.md:191` 两项校验（preset 存在性 / vendor_model 存在性）代码未实现** | **doc/code 分歧已确认**，需用户裁决补实现或降版 spec（E26） |
| 18 | **CLI 上游凭据路径**（厂商 CLI 自持 vs 环境变量 API Key） | **需用户决策**：直接决定是否与铁律 1 冲突（E25） |
| 19 | **`adapters/base.py` 接口签名采用哪一版** | **需用户决策**：`tech-design.md:163` 的 `call()/list_models()`（相容）vs draft 的扁平签名（需翻案）（E22） |

---

*报告结束。本文件为定稿（`docs/research/`），任何结论在用户确认并写入 `docs/specs/` 之前不构成需求依据。原始 draft 与核验报告留痕于 `docs/research/drafts/`，本次修订未修改其中任何文件，也未修改项目其它任何既有文件。*
