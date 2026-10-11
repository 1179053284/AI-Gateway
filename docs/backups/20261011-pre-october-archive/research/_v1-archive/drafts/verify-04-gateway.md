# 核验报告 · 04-网关现状与API-CLI双模式调研

> 核验角色：独立审计员（唯一职责 = 证伪）
> 核验对象：`docs/research/drafts/04-网关现状与API-CLI双模式调研.md`（1005 行）
> 源码基准：`/Users/w/Desktop/Model-Gateway/`（只读；本次核验**未修改**任何项目文件，临时脚本置于 `/tmp/`）
> 核验日期：2026-09-22
> 方法：① 脚本化提取全部 `路径:行号` 引用并校验存在性/越界；② 逐条回源码/官方来源精读比对内容；③ 外部来源逐个 WebFetch 打开核实原文

---

## 一、总体结论

**可信度评级：B+（良好，但含 6 处必须修正的事实错误与 8 处过度推断）**

这是一份**引用纪律显著高于平均水平**的调研草稿：219 条 `路径:行号` 引用**零文件不存在、零行号越界**，且我抽查的 60+ 条实质引用的**行号几乎全部精确命中**（含 `api/admin.py` 14 个端点的行号、`core/scheduler.py` 六类错误分支的双位置引用、`core/errors.py`/`core/ir.py`/`core/resources.py` 的函数区间，逐条吻合）。外部来源 23 条中我实测打开 23 条，**全部可达**，Claude Code 官方页的 4 段引文、MCP 规范 3 段引文、OpenRouter 14 字段清单、Trae/Cherry Studio 的关键句**均逐字吻合**。

主要问题不在"编造行号"，而在三处：
1. **数量/命名类事实错误**（`data/config.yaml` 系统模型数、`/admin/api` 端点数、PRD 章节定位）；
2. **对外部来源的选择性引用与过度推断**（§B.2/§C.5 的合规结论强于官方原文，遗漏了官方同页的限定段落与同一篇报道的反向陈述）；
3. **落地建议与项目铁律的冲突检查不完整**（`adapters/base.py` 拟议接口与 `tech-design.md` 已声明接口冲突；`mgw setup` 写入边界；CLI 上游凭据与铁律 1 的张力）。

### 1.1 错误密度统计表

| 校验维度 | 数量 | 说明 |
|---|---|---|
| 唯一 `路径:行号` 引用总数 | **219** | 脚本提取（去重后） |
| 文件不存在 | **0** | — |
| 行号越界 | **0** | 全部落在文件行数范围内 |
| 行号正确但**内容描述不吻合/不精确** | **7** | 见 E3/E4/E16/E17/E18/E19/E20 |
| 非行号类**事实错误**（数量/命名/分类） | **6** | 见 E1/E2/E5/E6/E10/E15 |
| **过度推断 / 依据不足**（推断写成事实） | **8** | 见 E7/E8/E9/E11/E12/E13/E14 + E22 |
| **内部自相矛盾** | **3** | E2（端点数）、E6（base.py 行数）、E17（config.yaml 区间） |
| **该覆盖却漏掉** | **5** | 见 E21/E23/E24/E25 + presets 校验缺口 |
| 外部来源实测可达 | **23 / 23** | 逐条 WebFetch 打开 |
| 外部来源**内容不符/选择性引用** | **2** | E7（遗漏官方限定段）、E8（遗漏同源反向陈述） |
| 外部来源**分级不当** | **1** | E10（Trae 社区帖标为"一手官方"） |

**一句话**：引用机械精度 A，内容吻合度 B，外部证据纪律 C+，与项目铁律的一致性检查 C。

---

## 二、必须修正的错误清单（按严重度排序）

### P0 · 事实性错误（必须改，否则误导实施）

#### E1 · `data/config.yaml` 系统模型数量错误（漏 1 个）
- **草稿位置**：§A.2.3（草稿 L127）
- **草稿原文**：「`data/config.yaml` 是**真实运行配置**（实测：1 个资源 `res-sensenova-main`…，**6 个系统模型**：`sensenova-6.8-flash-lite / deepseek-v4-flash / deepseek-v4-pro / glm-5.2 / kimi-k3 / sensenova-u1-fast`，2 个接入令牌）」
- **真实情况**：`data/config.yaml:47-130` 实为 **7 个系统模型**，草稿遗漏 `sensenova-u1.5-lite`（`data/config.yaml:122-130`，`endpoint: images`，`group: 图像生成`）。资源 1 个、令牌 2 个的描述正确。
- **修正建议**：改为「7 个系统模型：`sensenova-6.8-flash-lite / deepseek-v4-flash / deepseek-v4-pro / glm-5.2 / kimi-k3 / sensenova-u1-fast / sensenova-u1.5-lite`（后两者为 images 端点）」。

#### E2 · `/admin/api` 端点数自相矛盾（摘要 vs 表格）
- **草稿位置**：摘要第 1 条（草稿 L13）vs §A.1.2 表（草稿 L58-75）
- **草稿原文**：「对外 4 个 `/v1` 端点 + **15 个 `/admin/api` 端点**」
- **真实情况**：`api/admin.py` 共 **14** 个路由（`status`/`overview`/`stats`/`logs/requests`/`logs/switches`/`resources/test`/`config GET`/`config PUT`/`config/reload`/`enums GET`/`enums PUT`/`presets`/`system/stop`/`system/restart`），草稿自己的 A.1.2 表编号 1–14 也正是 14 条；表内 15/16 行是 `/health` 与 `/`，不属 `/admin/api`。
- **修正建议**：摘要改为「14 个 `/admin/api` 端点 + `/health` + 静态界面」。

#### E3 · PRD 术语表定位错误
- **草稿位置**：证据附录（草稿 L883）
- **草稿原文**：「PRD 资源/映射/系统模型术语 | `docs/specs/prd.md:113-123`（§2 术语表）」
- **真实情况**：`prd.md:47` 才是「## 2. 术语与核心概念」，术语表为 `prd.md:47-68`（含「资源 Resource」L53、「映射条目 Model-Resource Entry」L57、「系统模型 System Model」L58）。草稿所指 `prd.md:113-123` 是 **FR-1.3~FR-1.8**（枚举池 / 厂商模型录入 / Key 管理 / 信息汇总视图 / 状态标识 / 商汤首发接入清单），**不是术语表**。
- **修正建议**：改为 `docs/specs/prd.md:47-68`。

#### E4 · PRD 接入模式定义行号偏移 1 行
- **草稿位置**：证据附录（草稿 L880）
- **草稿原文**：「PRD 接入模式定义（api/plan） | `docs/specs/prd.md:31`（术语表 §2）」
- **真实情况**：`prd.md:30` 才是「接入模式（P0）| **两大类接入方式**：**API 模式**…与 **Plan 模式**…」；`prd.md:31` 是「首发厂商（P0）」。另「（术语表 §2）」标注亦误（该表属 §1.4 已确认的关键需求决策）。
- **修正建议**：改为 `docs/specs/prd.md:30`（§1.4）。

#### E5 · 「内置 15 条…来源均为官方域取证」不准确
- **草稿位置**：§A.2.4（草稿 L145）
- **草稿原文**：「内置 15 条（`enums/matcher.py:67-142`，覆盖商汤 3 / DeepSeek 3 / 智谱 3 / Kimi 4 / Anthropic 2），**来源均为官方域取证**（注释见 `enums/matcher.py:52-66`）」
- **真实情况**：条数与分厂商计数**正确**（商汤 3 / DeepSeek 3 / 智谱 3 / Kimi 4 / Anthropic 2 = 15）；但 `enums/matcher.py:137` 的注释明确写「**跨协议族预置（Anthropic 原生 model id 别名，供 Claude Code 直连解析；属性未取证）**」，两条 Anthropic 条目（`claude-sonnet-4` L138-139、`claude-opus-4` L140-141）**只有 name/aliases/group/vendor**，`context_window` / `max_output` / 模态 / `reasoning` / `effort_levels` / `params_default` **全为空**。故"来源均为官方域取证"不成立。
- **影响**：草稿 §D.1 与阶段 0.1 建议把 `context_window / max_output / input_modalities / capabilities.reasoning / reasoning_effort_levels / default_params` 下发到 `/v1/models`——对这两条会**下发 null/空值**，客户端可能误判为"不支持"。
- **修正建议**：§A.2.4 补注「Anthropic 2 条仅预置别名，属性未取证」；阶段 0.1 补一条前置「未取证条目应省略字段而非下发 null」。

#### E6 · `adapters/base.py` 行数自相矛盾
- **草稿位置**：摘要第 4 条（草稿 L16）
- **草稿原文**：「`adapters/base.py` **只有一行 docstring，没有任何抽象基类/Protocol**（`adapters/base.py:1-5`）」
- **真实情况**：`base.py` 共 5 行 = 4 行 docstring（L1-4）+ 1 空行（L5），无任何代码。**结论（无 ABC/Protocol）正确**，但"只有一行 docstring"与自引 `:1-5` 矛盾。
- **修正建议**：改为「仅一段 docstring（5 行），无任何代码」。

### P1 · 过度推断 / 依据不足（必须改表述，否则结论方向可能误导用户决策）

#### E7 · §B.2/§C.5 的合规结论**强于官方原文**（遗漏官方同页限定段落）
- **草稿位置**：§B.2 证据 1 结论（草稿 L348）、§C.3 方案 4（L508/L511）、§C.5（L560-563、L570）
- **草稿原文**：「这条直接命中用户诉求的三个动作：① 用订阅凭据接入第三方工具 → 不允许；② 通过网关"代表用户"发请求 → 不允许；③ 网关存储/中转会话 token → 不允许。」「CLI 模式…**同样违规，且被官方点名**」
- **真实情况（已实测打开 `https://code.claude.com/docs/en/legal-and-compliance`）**：草稿引用的 4 段原文**逐字吻合** ✅。但官方在同一小节紧接着有一段**限定段落**草稿完全未引：
  > "This does not restrict how customers provision and manage their own API keys or third-party inference provider credentials — for example, configuring an API key in a development environment, secrets manager, or machine image for use by the customer's own authorized users — provided the resulting usage is billed to the key owner… **Nor does it prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription**, including where a platform hosts Claude Code…"
- **判定**：官方原文禁止的是「**第三方开发者**在自己的应用里提供 Claude.ai 登录 / 代表用户路由订阅凭据」；对「**最终用户在自己机器上用未修改的官方二进制 + 自有订阅**」官方明文说**不禁止**。草稿把"单用户本地网关调用未修改的官方 CLI"直接判为"同样违规且更明确被禁止"，**是过度推断**。
- **修正建议**：§B.2 补引该限定段落；§C.5「服务条款合规」行改为「⚠️ 取决于形态：由第三方/网关代表用户中转订阅凭据 → 违规；用户本机自用未修改官方二进制 + 自有订阅 → 官方明文不禁止（但网关若做多账号/代他人中转则落入禁止区）」。

#### E8 · §B.2 证据 3 选择性引用（同一来源含反向陈述）
- **草稿位置**：§B.2 证据 3（草稿 L357-362）
- **真实情况（已实测打开 winbuzzer 原文，2026-02-19 发布）**：草稿引的两句**逐字吻合** ✅。但**同一篇文章**还写：
  > "Anthropic later described the documentation changes as a **'docs clean up' that caused confusion** and said **nothing was changing about Agent SDK usage with Max subscriptions**."
- **判定**：草稿只引"新增禁令"方向，未引同源的反向陈述，使时间线单向化。这不构成"编造"，但违反"证据完整性"。
- **修正建议**：补引该句，并说明"官方对'文档澄清是否等于政策变更'的表述存在反复，故本报告不据此判定政策生效日"。

#### E9 · §C.5「CLI 风控略优」与草稿自引来源方向相反
- **草稿位置**：§C.5 表「账号风控」行（草稿 L562）
- **草稿原文**：「CLI 模式：⚠️ 可能略低（用的是官方二进制，指纹更"干净"）」
- **真实情况**：草稿自己在 §B.2 证据 4 引用的 `woodchen.ink` 报告（`docs/research/drafts/04-…md:366`）恰恰**反方向**：其 §6.4「自动化滥用检测」明确列出 `is_ci: true` / `is_interactive: false` / `entrypoint: "sdk"` / 高频调用 + 大 token 消耗 → **自动化滥用嫌疑**；§9.2 建议「CI/CD 中大规模使用 → 中风险 → **使用 API Key 而非 OAuth**」。而网关作为**无人值守、非交互、高并发**的调用方，正是该报告指出的高危画像。
- **判定**：草稿在"账号风控"维度只取了对自己结论有利的方向（另：`awesomeagents.ai` 来源称 Anthropic 的拦截机制是"确认真实客户端身份、拒绝非官方二进制"，这一条反而**支持**草稿的"官方二进制指纹更干净"）。**两个来源方向相反，草稿未披露冲突**。
- **修正建议**：该行改为「⚠️ 方向存在来源冲突：官方二进制身份校验可通过（awesomeagents），但非交互/自动化/高频画像本身是风控信号（woodchen §6.4）→ **无法判定孰强，需标注为未验证**」。

#### E10 · Trae 论坛帖被标为「一手（官方）」
- **草稿位置**：§C.1 表 Trae 行（草稿 L401）、§D.2 表（L659）、参考来源清单 #15（L834）
- **草稿原文**：「**一手（官方社区官方教程）**：<https://forum.trae.cn/t/topic/11480>」；清单中归入「### 一手（官方）」
- **真实情况（已实测打开）**：帖子标题《添加自定义模型服务模型教程 v4.0版本(2026.05.15更新)》，**作者 = `JasonShane`，头衔「社区捣蛋鬼」**（社区用户/版主），发布在 TRAE 官方中文社区。**内容全部核实无误**（见第四节），但**作者不是 TRAE 官方**，该帖不是官方文档。
- **判定**：按项目自身取证纪律（`.cursor/memory/decisions.md:13`「外部资料仅采信**官方文档**与 GitHub 实际项目代码；搜索引擎二手内容不作为依据」），论坛用户教程应归「社区帖」，不能进"一手（官方）"。
- **修正建议**：改标「**二手（官方社区用户教程，作者为社区用户非 TRAE 官方）**」，并将参考来源清单 #15 移入二手区。结论本身（Trae 需手填模型 ID）仍成立。

#### E11 · 无引证的绝对否定断言
- **草稿位置**：§C.3 方案 1 兼容性代价（草稿 L466）
- **草稿原文**：「Trae / Cursor / Cherry Studio / Claude Code **没有任何一个**支持"把模型调用委派给外部命令"」
- **判定**：这是**否定性全称断言**，无任何来源支撑（属于"以未观察到当作不存在"）。结论方向大概率成立，但表述越界。
- **修正建议**：改为「据本次调研所查文档，四者均未见此能力（**未穷尽验证**）」。

#### E12 · 推断写成事实
- **草稿位置**：§D.2 末（草稿 L674）
- **草稿原文**：「`/v1/models` 的 `id` 与 `resolve_request_model` 的可解析集合必须**保持一致**（当前…只输出规范名——这是**有意的宽进严出**，建议在文档中写明）」
- **真实情况**：代码事实（`/v1/models` 只输出系统模型名；`resolve_request_model` 支持别名与规范化）**正确**（`api/openai_compat.py:39-43`、`enums/matcher.py:259-280`）。但"**有意的**"是设计意图归因，**无任何需求/文档依据**。
- **修正建议**：改为「这一差异在代码中未见设计说明，**是否为有意设计需向用户确认**」。

#### E13 · ACP 段两处依据不足
- **草稿位置**：§C.2.1（草稿 L412、L416）
- **（a）**「传输：JSON-RPC 信封；**默认 stdio**（由客户端启动 agent 子进程）」——已实测打开官方 README：定义句与「稳定版 `1`」「`initialize` 的 `protocolVersion` 协商」**均逐字吻合** ✅，但 **README 未载明 stdio**（草稿自标"一手，官方仓库 README"）。→ 应标「README 未载明；据实现惯例推断，**未核实**」。
- **（b）**「治理：**Zed 主导**（"Zed-led model"）」——官方 README **无此表述**；`zed.dev/acp` 原文为 "**Created by Zed**, grown by a community of editors and agents."；`jetbrains.com/acp` 原文为 "developed openly by **JetBrains and Zed**"。引号内的 `"Zed-led model"` **不是原文**。
- **修正建议**：改为「由 Zed 创建、JetBrains 与 Zed 共同开发（zed.dev / jetbrains.com 官方页原文）」。

#### E14 · 「2026 官方 schema 新增 `shutdown_date`」
- **草稿位置**：§C.2.4（草稿 L450）、§D.1（L613）
- **真实情况**：已实测打开 `developers.openai.com/.../models/methods/list`，Model 对象字段为 `id / created / object / owned_by / shutdown_date` ✅，`shutdown_date` 说明为 "The date when the model will shut down, or null if not announced." ✅。但"**2026 新增**"这一时间性断言**页面无法证实**。
- **修正建议**：删去"2026 官方 schema 新增"，改为「官方当前 schema 含 `shutdown_date`」。

### P2 · 小瑕疵（建议改，不影响结论）

#### E15 · `.git/` mtime 实测值与草稿不符
- **草稿位置**：摘要第 14 条（草稿 L26）、未验证清单 #8（L999）
- **草稿原文**：「根目录实际存在 `.git/`（`ls -la` 实测，**mtime 2026-09-18**）」
- **真实情况**：`ls -la` 实测根目录 `.git/` 目录 mtime = **2026-09-22 13:58**；`2026-09-18 16:47` 是 `.git/index` 的 mtime。**核心矛盾成立**：`git status` 正常返回（`On branch main … nothing to commit`），`ACTIVE.md:27` 的「T6 项目无 git 仓库」确已过期 ✅。
- **修正建议**：mtime 改为「`.git/` 目录 mtime 2026-09-22；`.git/index` mtime 2026-09-18」。

#### E16 · 依据错位
- **草稿位置**：§A.2.3 注（草稿 L129）
- **草稿原文**：「`data/` 已在 `.gitignore` 中（`config.example.yaml:3`）」
- **真实情况**：`.gitignore:3` 才是 `data/` 规则；`config.example.yaml:3` 只是同口径的文字说明。
- **修正建议**：改引 `.gitignore:3`。

#### E17 · `data/config.yaml` 行区间截断
- **草稿位置**：证据附录（草稿 L886）
- **草稿原文**：「真实运行配置（含明文 Key，勿外泄） | `data/config.yaml:1-120`」
- **真实情况**：文件实际 **131** 行（`pricing: []` 收尾在 L131）。区间未越界但不完整。
- **修正建议**：改为 `data/config.yaml:1-131`。

#### E18 · 页面命名过时
- **草稿位置**：证据附录（草稿 L986）
- **草稿原文**：「**模型资源页**（厂商分组卡片 / 属性 / 参数配置） | `web/static/js/pages/models.js:1-12, 21-50`」
- **真实情况**：`models.js:1` 自述「资源池设置（原「系统模型」，Q24 · 2026-09-05 定版）」——该页在 Q24 已更名「**资源池设置**」；「模型资源」是 `resources.js` 对应的另一页（AGENTS.md:31、prd.md §9-Q24 均如此命名）。
- **修正建议**：改为「**资源池设置**页（原系统模型页）」。

#### E19 · grep 结论不完整 + 行号偏移 1
- **草稿位置**：§A.5.1 表（草稿 L266）、证据附录（L985）
- **草稿原文**：「⚠️ **字段存在但无消费点**（全仓 grep 仅见 schema 定义与前端赋值 `resources.js:505`）」；附录「UI 资源草稿默认值…`resources.js:193, 505, 822, 826, 1017`」
- **真实情况**：**核心结论正确** —— 全仓 grep `protocol` 确认：`schemas.py:125` 定义、`presets.py` 是另一数据结构、`resources.js:505` 与 **`resources.js:1018`** 前端赋值、其余均为测试/文档。**草稿漏了 `resources.js:1018`**（`protocol: "openai",`）；附录写 `1017` 实为 `access_mode` 所在行。
- **修正建议**：补 `resources.js:1018`；附录行号改为 `193, 505, 822, 826, 1017-1018`。

#### E20 · 事件落盘 finally 引用不全
- **草稿位置**：§A.3 第 [8] 步（草稿 L212）
- **草稿原文**：「事件落盘（finally 保证成功/失败/取消各一行）`core/scheduler.py:282-283 / 719-722`」
- **真实情况**：非流式路径的 finally 在 `_execute`（`core/scheduler.py:292-299`，其中 295-297 处理 `CancelledError` → `aborted`，298-299 `finally` → `_log`）；`282-283` 只是 `_log` 方法本身。
- **修正建议**：补引 `scheduler.py:292-299`。

### P1-结构 · 遗漏（见第五节 E21–E25）

---

## 三、落地建议 × 项目铁律 冲突检查表

> 铁律依据：`AGENTS.md:12`（铁律 1 全明文·纯本地·无远程更新）、`AGENTS.md:15`（铁律 4 无依据自创禁止）、`mg-00-first-principles.mdc:11/16/27`、`mg-directory-layout.mdc:10/16-20`、`mg-work-rules-redlines.mdc:14/17/32`、`decisions.md:13`（取证纪律）

| # | 草稿的落地建议 | 是否与铁律冲突 | 结论 |
|---|---|---|---|
| 1 | **0.1** `/v1/models` 补齐 `EnumEntry` 元数据（纯加法） | ⚠️ 程序性 | 无技术冲突；但**新增对外契约字段**须先入 PRD（铁律 4）。且 E5：Anthropic 2 条属性未取证，直接下发会输出 null → **须先取证或省略字段** |
| 2 | **0.2** `/v1/models` 增 `gateway.resources_*`（复用 `snapshot_by_resource`） | ❌ 不冲突 | 可行（纯组合，`resources.py:183-218` 已具备） |
| 3 | **0.3** 新增 `GET /v1/models/{id}` | ❌ 不冲突 | 可行；`AuthMiddleware` 按 `/v1/` 前缀自动覆盖鉴权（`api/auth.py:42`） |
| 4 | **0.4** 新增 `/admin/api/models/export?format=md\|csv\|json` | ❌ 不冲突 | 可行；管理端免鉴权是项目**已定论**的取舍（`tech-design.md:573` 风险 #24），非本建议引入 |
| 5 | **0.5** `normalize_name` 补渠道前缀剥离 | ❌ 不冲突（**且非自创**） | 可行；PRD FR-1.4 已要求「忽略厂商前缀」（`prd.md:115`），`ACTIVE.md:20` T2 已备案 ✅ 草稿标注正确 |
| 6 | **0.6** `capabilities.tools` 官方取证回填 | ❌ 不冲突 | 可行；但必须逐条官方域取证（`decisions.md:13`）✅ 草稿已标注 |
| 7 | **1.1** `mgw` 入口放 `scripts/mgw.py` 或 `model_gateway/cli.py` | ❌ 不冲突（有条件） | 与 `mg-directory-layout.mdc:16-20` 相容 ✅ **草稿已主动标注"须先与用户确认目录归属"——这是加分项** |
| 8 | **1.2** `mgw setup <trae\|cursor\|cherry\|claude-code\|codex>`「生成并打印/**写入**该工具的接入配置片段」 | ⚠️ **潜在冲突** | `mg-directory-layout.mdc:10` 明令：`.claude/`、`.trae/`、`.workbuddy/` 等其它 `.xxx` 工具目录「**一律不维护、不更新、不写入**」。若 `mgw setup` 写入**项目内**这些目录即违规。**草稿未声明该边界** → 须限定为「仅打印，或仅写用户家目录的工具配置；**绝不写项目内 `.xxx` 目录**」 |
| 9 | **1.3** 文档 + 管理界面「API 接入」页补 CLI 入口说明 | ❌ 不冲突 | 可行（纯本地文档/UI） |
| 10 | **2.1** `adapters/base.py` 补 `Protocol`/ABC，签名 `chat_nonstream / chat_stream / images_generate / aclose` | ⚠️ **明确冲突** | `tech-design.md:163` **已声明**适配器接口：`async def call(resource, ir_request) -> IRResponse \| AsyncIterator[IREvent]` + `async def list_models(resource)`。草稿拟议的接口与之**不一致**，却列为"必须"项且只在依赖列写"用户确认"，**未披露该差异** → 触碰铁律 4（无依据自创）。**须改为：落实 spec 既有 `call()/list_models()` 契约，或明确提请用户翻案并同步升版 tech-design** |
| 11 | **2.2** `Runtime._apply` 按资源分派 + `Runtime.adapters` 类型泛化 | ❌ 不冲突（**非自创**） | `tech-design.md:162` 已声明「`anthropic_out`（P1）/`gemini_out`（P2）：按资源 `protocol` 字段选择」→ 属**落实既有设计**，不是自创。草稿把它列在"阶段 2 依赖用户确认"略偏保守 |
| 12 | **2.3** `resource.protocol` 补齐消费点（或删除该字段） | ❌ 不冲突（**非自创**） | 同 #11；`tech-design.md:162` 已声明该分发设计。草稿未引此依据（见 E23） |
| 13 | **2.4** 替换 `scheduler.py:214` 误导性错误文案 | ❌ 不冲突 | 可行（文案修正） |
| 14 | **3.1** 新增 `resources[].transport` + `resources[].cli{command,args}` | ⚠️ 程序性 | 与铁律 1/2/3 无直接冲突，但属**无依据自创**，须先入 PRD ✅ 草稿已标注。**补充**：应同步评估 `config/presets.py` 预设字段是否需扩展（见 E21） |
| 15 | **3.2** `adapters/cli_out.py` 调用厂商 CLI headless 模式 | ⚠️ **潜在冲突（草稿未识别）** | CLI 上游依赖厂商 CLI **自身凭据存储**（OAuth token / macOS 钥匙串 / `~/.codex/auth.json`），该凭据**不在网关的明文配置或环境变量内** → 与铁律 1「密钥只存本地明文配置或环境变量」（`AGENTS.md:12`）存在张力。草稿 §C.3 方案 4 已提到 `--bare` 不读 OAuth、需 `ANTHROPIC_API_KEY`（此路径合规），但**未把该张力写入一致性检查表**。须补充：「CLI 上游若走厂商 CLI 自持凭据 → 与铁律 1 冲突；若强制走环境变量 API Key → 与铁律 1 相容」 |
| 16 | **3.3** 合规开关（默认关闭 + UI 二次确认 + 文档标注） | ❌ 不冲突 | 可行 |
| 17 | **3.4** 进程池 / 超时 / 取消语义适配 | ❌ 不冲突 | 可行 |
| 18 | 方案 2 的 `mgw serve --socket <path>`（Unix socket） | ❌ 不冲突 | 纯本地 socket，无远程依赖；与 `mg-00-first-principles.mdc:27`「无远程配置/遥测/自动更新」相容 |
| 19 | 方案 B 网关侧策略路由（虚拟模型名 `mg-auto` 等） | ⚠️ **需用户翻案** | 与 Q18-③「调度参数全局唯一·一套机制管控所有模型」（`tech-design.md:648`、`prd.md:500`）及 Q23-②「配置参数范围维持现状四类」（`AGENTS.md:31`）有张力 ✅ **草稿已主动标注该张力——加分项** |
| 20 | 方案 C 档位别名（`mg-fast` → `deepseek-v4-flash`） | ❌ 不冲突 | 技术可行：`EnumPool._alias` + `resolve_request_model` 的 canonical→系统模型检查（`enums/matcher.py:163-170, 272-274`）确实支持 ✅ 草稿引用正确。**提示**：别名不会出现在 `/v1/models`，客户端仍需手填 |
| 21 | 建议新增 `docs/specs/` 内「CLI 接入指引」 | ❌ 不冲突 | `docs/specs/` 正是 `mg-directory-layout.mdc:11` 规定的需求真相目录 ✅ |
| — | **本报告草稿自身位置** `docs/research/drafts/` | ⚠️ 轻微（既有约定，非本报告新增） | `mg-directory-layout.mdc:17` 规定 `docs/` 只允许「需求/架构/设计真相（specs）+ 活跃任务（changes）」；`docs/research/` 不在列举内。属既有安排，仅供提示 |

**汇总**：21 条建议中 —— 明确冲突 **1** 条（#10）、潜在冲突 **3** 条（#8、#15 + #1 的程序性）、需用户翻案 **1** 条（#19）、其余 **16** 条与铁律相容。草稿自己已正确标注了 #1/#6/#7/#14/#19 的程序性约束（这五点做得比一般草稿好），**漏的是 #8、#10、#15**。

---

## 四、已核实正确的关键结论清单

### 4.1 用户给定校准基准（草稿全部一致 ✅）

| 校准项 | 草稿表述 | 判定 |
|---|---|---|
| `adapters/base.py` 共 5 行，仅 docstring，无 ABC/Protocol | 「只有一行 docstring，无抽象基类/Protocol」（`base.py:1-5`） | ✅ 结论一致（措辞见 E6） |
| `anthropic_out.py` / `gemini_out.py` 各 1 行 | 「各只有 1 行 docstring 占位」 | ✅ **完全一致** |
| `main.py:95-105` 一律构造 `OpenAIOutAdapter`，未按 `protocol` 分派 | 「对所有资源一律构造 `OpenAIOutAdapter`…仅按 `base_url` 变更决定是否重建」 | ✅ **完全一致** |
| `api/openai_compat.py:36-44` 只返回 6 字段、无元数据 | 「只返回 `id/object/created/owned_by/endpoint/group`」 | ✅ **完全一致** |
| `schemas.py:125` `protocol: Protocol = "openai"`；`resources.py:52` `access_mode = api \| plan` | 均正确引用 | ✅ **完全一致** |
| `scheduler.py:223-232` `_out_body`：229 → 230 → 231 | 三级优先级表逐行吻合 | ✅ **完全一致** |

### 4.2 源码事实（精读后确认无误，抽样 60+ 条）

- **端点清单与行号**：`api/admin.py` 14 个端点的行号（110/122/184/224/247/260/363/384/426/455/465/507/520/536）**逐条精确**；`/v1` 四端点（`openai_compat.py:36-44 / 101-144 / 238-286`、`anthropic.py:316-366`）**逐条精确**；`/health`（`main.py:186-203`）、静态挂载（`main.py:212-214`）**精确**。
- **鉴权**：豁免前缀 `("/health", "/admin/")`（`auth.py:15`）、仅 `/v1/` 走鉴权（`auth.py:42`）、令牌三级来源（`auth.py:66-79`）、错误体分形（`auth.py:81-92`）、未配置令牌全放行 + 启动警告（`main.py:174-175`）——**全部逐行吻合**。
- **领域模型**：`Resource`(109-129) / `ModelResource`(132-137) / `SystemModel`(150-191) / `AppConfig`(206-255) / `GatewayConfig`(46-65) / `SchedulingConfig`(68-81) / `AccessToken`(33-43) / `ErrorRule`(84-95) 字段与默认值**逐条吻合**；跨节校验（219-255）与数值边界（57-65）、`PARAM_RANGES`（142-147）**吻合**。
- **调度与故障切换**：§A.3 故障切换表 8 行判定（`scheduler.py:371-376/638-643`、`377-382/644-649`、`383-394/650-661`、`407-412/673-678`、`413-415/679-681`、`343-346/546-549`、`330-332/533-535`、`399-403/664-669`）**逐条精确**；`no_failover`（`errors.py:54`）、`y` 先判定、`RETRY_EXHAUSTED` 不冷却、`C` 跨请求累计（`resources.py:162-168`）、冷却按 `access_mode` 取（`resources.py:170-174`）**全部吻合**。
- **参数三级优先级**：`apply_model_params`（`ir.py:58-70`）字段级语义（非空保留 / 缺省或显式 null 注入 / 未配置不注入）**逐行吻合**；`merge_reasoning`（`ir.py:28-55`）+ `inject_reasoning_into_body`（`ir.py:94-111`）+ `lift_reasoning_from_body`（`ir.py:73-91`）**吻合**；「运行期不存在第三级自动查表注入」的判断**正确且诚实**。
- **流式边界**：延迟提交（`openai_compat.py:158-169`）、心跳（`190-193`）、error 帧（`196-198`、`225-235`）、committed 后失败（`scheduler.py:600-622`）、`CancelledError` re-raise（`295-297`、`715-718`、`cancel.py:1-6`）**全部吻合**。
- **枚举池**：`EnumEntry` 16 字段（`matcher.py:17-49`）**吻合**；内置 15 条及分厂商计数（商汤 3 / DeepSeek 3 / 智谱 3 / Kimi 4 / Anthropic 2）**计数正确**（取证范围问题见 E5）；三级匹配置信度 1.0/0.9/0.7（`173-186`）**吻合**；`normalize_name` 不剥离渠道前缀（`148-155`）**吻合**，且与 `ACTIVE.md:20` T2 备案一致 ✅。
- **扩展点判断**：`resource.protocol` 无消费点（全仓 grep 确认）✅；`Scheduler._adapter` 错误文案「protocol 未实现」暗示有分发而实际不存在（`scheduler.py:211-215`）✅；`list_models` 方法已实现但无任何调用点（`openai_off.py:183-191`，全仓 grep 仅定义处命中）✅ —— 三条判断**均成立**。
- **文档引用**：`tech-design.md` 的 14 个区间（14-56 / 52-56 / 75-90 / 96-112 / 114-128 / 130-155 / 157-163 / 186-219 / 221-247 / 249-261 / 263-315 / 346-474 / 478-489 / 493-542 / 546-573 / 643-656）**章节边界全部正确**；`prd.md:73 / 144-145 / 205 / 500 / 374-378` **全部正确**；`AGENTS.md:12/15/31`、`decisions.md:5-22/9/13`、`pitfalls.md:28`、`mg-00-first-principles.mdc:11-19`、`mg-directory-layout.mdc:8-23/16-20` **全部正确**。
- **UI 引用**：`resources.js:240 / 779-780`（UI 文案「API（按量计费）」「Plan（订阅 / 积分制）」）、`193 / 505 / 822 / 826` **逐行精确**。
- **其他**：`__init__.py:6`（`__version__ = "0.1.0"`）、`config/loader.py:33-54 / 57-75`、`core/instance_lock.py:52-64 / 78-108 / 111-115`、`stats/events.py:19-35 / 38-96`、`config/presets.py:17-45`（3 条预设）**全部精确**。
- **T6 矛盾真实存在** ✅：`ACTIVE.md:27` 记「项目无 git 仓库（`git status` → fatal）」，实测 `git status` 正常返回 `On branch main … nothing to commit`，根目录存在 `.git/`（内含 2269 objects / refs / HEAD）→ 该条**确已过期**（mtime 细节见 E15）。

### 4.3 外部来源（23 条逐个实测，全部可达）

| # | 来源 | 实测结果 |
|---|---|---|
| 1 | `code.claude.com/docs/en/env-vars` | ✅ 可达；`ANTHROPIC_BASE_URL`（"Override the API endpoint to route requests through a proxy or gateway"）、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_API_KEY`、`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY`（"Set to `1` to populate the `/model` picker from your gateway's `/v1/models`… **Off by default**…Anthropic-compatible gateway…**filtered by an `availableModels` allowlist**"）、`CLAUDE_CODE_GATEWAY_MODEL_DISCOVERY_TIMEOUT_MS`（**default: 3000**）、`ANTHROPIC_CUSTOM_MODEL_OPTION`(+`_NAME`/`_DESCRIPTION`/`_SUPPORTED_CAPABILITIES`) —— **草稿引用逐字吻合** ✅ |
| 2 | `code.claude.com/docs/en/legal-and-compliance` | ✅ 可达；4 段引文**逐字吻合**（OAuth 专属订阅者 / 第三方开发者禁令 / "may do so without prior notice" / "ordinary, individual usage"）；证据 2 两段**逐字吻合**（"binary must not be modified"、"may not pay for, resell, or intermediate"）—— ⚠️ **但遗漏同页限定段（E7）** |
| 3 | `code.claude.com/docs/en/headless` | ✅ 可达；"In bare mode, Claude Code **never reads OAuth credentials or the system keychain**. For the Anthropic API, set `ANTHROPIC_API_KEY`…"、"`--bare` is the recommended mode for scripted and SDK calls"、`-p/--print`、`--output-format text\|json\|stream-json` —— **草稿引用逐字吻合** ✅ |
| 4 | `github.com/agentclientprotocol/agent-client-protocol` | ✅ 可达；定义句**逐字吻合**、"The current stable ACP protocol version is `1`"、`initialize` 的 `protocolVersion` 协商、JSON-RPC envelope —— ✅；但 **README 未载明 stdio 与 "Zed-led"**（E13） |
| 5 | `zed.dev/acp` | ✅ 可达；"**Created by Zed**, grown by a community of editors and agents." —— 与草稿"Zed 主导"方向一致但**非原文措辞** |
| 6 | `jetbrains.com/acp` | ✅ 可达；"The ACP is **developed openly by JetBrains and Zed** to support a multi-editor, multi-agent ecosystem." —— **草稿"JetBrains + Zed 共建"完全成立** ✅ |
| 7 | `agentclientprotocol.com/overview/clients` | ✅ 可达；Zed / JetBrains / VS Code / Neovim / Emacs / Obsidian / Sublime / Qt Creator / Unity / Visual Studio **全部在列** ✅；**"ACP Pro Extension … VS Code–compatible IDEs (Cursor, Windsurf, Trae,..)" 逐字存在** ✅；`acp_rpc_bridge`、`ACP Remote` 均在 Connectors 区 ✅ |
| 8 | `modelcontextprotocol.io/specification/2026-07-28/basic/transports` | ✅ 可达；版本 `2026-07-28`；stdio "newline-delimited messages over the standard streams of a client-launched subprocess"；Streamable HTTP "each message is an HTTP POST to a single MCP endpoint; replies arrive as a JSON object or a request-scoped SSE stream"；取消（stdio `notifications/cancelled` / HTTP 关闭响应流）；"Custom transports that run over a reliable bidirectional byte stream (e.g., Unix domain sockets or TCP) **SHOULD reuse the stdio framing**" —— **草稿引用逐字吻合，全部成立** ✅ |
| 9 | `github.com/router-for-me/CLIProxyAPI` | ✅ 可达；定位句吻合（原文以 "CLIProxyAPI is a proxy server…" 开头）；Claude Code / Codex / Grok Build / Gemini / Antigravity / Kimi **全部在列**；"Multiple accounts with round-robin load balancing" ✅；`_ai-gateway._tcp` DNS-SD ✅（提交 3428110d，2026-09-14）；OAuth 登录 ✅；**赞助商确含低价 API 中转（PackyCode/AICodeMirror/APIKEY.FUN/PatewayAI）、住宅代理（Bestproxy/Swiftproxy/RapidProxy）、账号售卖（CyberPay）** —— 草稿"反面教材"判断**成立** ✅ |
| 10 | `github.com/Senselegend/CLIProxyAPI-UI` | ✅ 可达；确为 CLIProxyAPI fork（`fork/webui` 分支 + custom UI）✅ |
| 11 | `openrouter.ai/docs/guides/overview/models` | ✅ 可达；Model 对象 **14 字段**与草稿列举**完全一致**（含 `architecture{input_modalities,output_modalities,tokenizer,instruct_type}`、`top_provider{context_length,max_completion_tokens,is_moderated}`、`supported_parameters`、`default_parameters`、`expiration_date`、`benchmarks`）；`GET /api/v1/model/{author}/{slug}` 单模型端点**存在** ✅ |
| 12 | `developers.openai.com/api/reference/resources/models/methods/list` | ✅ 可达；Model 对象 = `id / created / object / owned_by / shutdown_date` ✅（"2026 新增"无法证实，E14） |
| 13 | `docs.litellm.ai/docs/proxy/model_management` | ✅ 可达；`GET /model/info` "Returns the full model list with API keys masked" ✅；"You can attach arbitrary `model_info` fields… they pass straight through to `GET /model/info` alongside the mapped cost and context data. **That is the mechanism for annotating models with your own metadata**" —— **草稿引用吻合** ✅ |
| 14 | `docs.cherry-studio-ai.com/.../zi-ding-yi-fu-wu-shang` | ✅ 可达；「点击"+ 添加"按钮，**手动添加**此提供商下您想要使用的模型ID」**逐字吻合** ✅；页面**无任何"自动获取模型列表"功能** ✅；字段 = 提供商名称/类型/API 密钥/API 地址/模型管理 ✅ |
| 15 | `forum.trae.cn/t/topic/11480` | ✅ 可达；「模型ID！！！！！无数的人都挂在ID上，**请自己去查询**！！！」**逐字吻合** ✅；「默认模板是200K，被拆分成输入184K，输出是16K」**逐字吻合** ✅；「多模态按钮，同理自己去查」✅；「工具调用轮次…保持默认200次」✅；「选自定义配置，API格式选择OpenAI」+「完整URL按钮」✅；**无任何自动发现模型列表功能** ✅ —— 内容全部成立，**仅分级不当（E10）** |
| 16 | `winbuzzer.com/2026/02/19/...` | ✅ 可达（2026-02-19 发布）；「Enforcement began blocking Max OAuth access in third-party clients on **January 9, 2026**. A documentation update on **February 19** then clarified…」**逐字吻合** ✅；「Anthropic says Free, Pro, and Max OAuth tokens cannot be used in third-party tools or the Agent SDK」✅ —— ⚠️ **但同文含反向陈述（E8）** |
| 17 | `awesomeagents.ai/news/claude-code-oauth-policy-third-party-crackdown/` | ✅ 可达（2026-02-18，更新 02-26）；印证 2026-01-09 服务端拦截 + 封号；并载明拦截机制为"确认真实客户端身份、拒绝非官方二进制" —— **"同上"标注成立** ✅ |
| 18 | `zhuanlan.zhihu.com/p/2055601319893786836` | ✅ 可达；《Claude‑Code大面积封号真相：时区检测+隐写追踪…》，含个人自述（"我本人两个订阅账号已经封禁一个"）—— 「国内订阅封号现象」标注成立 ✅ |
| 19 | `woodchen.ink/archives/claude-code-封号机制深度探查报告` | ✅ 可达（2026-04-08）；核心结论原文「Device ID（永久标识）+ 环境指纹（40+ 维度）+ 行为遥测（640+ 事件类型）」**逐字吻合** ✅；草稿标「**低（未验证）**」**恰当**（该报告基于"已泄露源代码"，按 `decisions.md:13` 不可作为机制依据） |
| 20 | `cloud.tencent.com/developer/article/2624427` | ✅ 可达（2026-01-27）；《对逆向中转API说"不！"》—— 「逆向中转产业链乱象」标注成立 ✅ |
| 21 | `php.cn/faq/2930693.html` | ✅ 可达（2026-08-03）；确含 "Auto-detect models from provider" 开关与 `Named Models` ↔ `/v1/models` 的 `data[].id` 关系 ✅ —— 但**该页为内容农场式文章**（AI 生成痕迹、`fixture-key-not-real` 示例、"把 Model 字段留空或填占位符"等不可靠建议），**不足以支撑结论**；草稿标「二手/未验证/低置信度」**处理得当** |
| 22 | `airelayrank.com/zh/guides/codex-cli-api-relay-config/` | ✅ 可达；`~/.codex/config.toml` 的 `[model_providers.*]` 含 `base_url` / `env_key` / `wire_api = "responses"\|"chat"` + `model = "provider-model-id"` **吻合** ✅ |
| 23 | `devpress.csdn.net/v1/article/detail/162196259` | ✅ 可达（2026-06-22）；`~/.codex/config.toml` `model_providers` + `base_url` + `wire_api` **吻合** ✅ |

**外部来源小结**：23/23 可达，**无一条编造 URL**；引文与原文的吻合度很高（Claude Code 官方页、MCP 规范、OpenRouter、LiteLLM、Trae、Cherry Studio 均逐字级吻合）。扣分集中在**证据完整性**（E7/E8 选择性引用）与**分级纪律**（E10）。

---

## 五、遗漏与矛盾

### 5.1 草稿内部自相矛盾

| # | 矛盾 | 位置 |
|---|---|---|
| C1 | 摘要「15 个 `/admin/api` 端点」 vs A.1.2 表实列 14 条 | L13 vs L58-75（= E2） |
| C2 | 「`adapters/base.py` 只有一行 docstring」 vs 自引 `base.py:1-5`（实为 5 行） | L16（= E6） |
| C3 | 附录「`data/config.yaml:1-120`」 vs §A.2.3 引用的内容延伸至 L130 之后的 `pricing` 节；文件实为 131 行 | L886 vs L127（= E17） |
| C4 | §A.2.4「内置 15 条…来源均为官方域取证」 vs 同节自引「未验证/缺口清单」精神，且与 `matcher.py:137`「属性未取证」冲突 | L145（= E5） |

### 5.2 该覆盖却漏掉

| # | 遗漏项 | 证据与影响 |
|---|---|---|
| **E21** | **`config/presets.py`（厂商预设注册表）未纳入扩展点分析** | 项目自己声明「扩展原则：新增厂商或 Plan 类型 = **仅加一条预设数据**（必要时新增协议适配器），接入向导与 UI 框架零改动」（`config/presets.py:6-8`；`tech-design.md:194`）。新增 `transport` 轴时，预设很可能需同步扩展字段（否则"CLI 资源"无法从预设带入）。草稿 §A.5.1/§A.5.2 完全未提 presets.py（仅在附录引用其行号）→ **扩展点清单不完整** |
| **E22** | **拟议适配器接口与 `tech-design.md` 已声明接口不一致且未披露** | 见冲突表 #10。`tech-design.md:163` 已定 `async def call(resource, ir_request) -> IRResponse \| AsyncIterator[IREvent]` + `list_models(resource)`；草稿拟 `chat_nonstream/chat_stream/images_generate/aclose`。这是**唯一的明确铁律冲突**，也是最影响后续实施的一条 |
| **E23** | **低估既有依据：`resource.protocol` 分派是 spec 已声明的 P1/P2 设计** | `tech-design.md:162`：「`anthropic_out`（P1）/ `gemini_out`（P2）：**按资源 `protocol` 字段选择**」。草稿把"补齐消费点"列为需用户确认的新增项，未引该依据 → 表述偏保守，也削弱了 §A.5.1「不存在可挂载新模式的抽象层」这一判断的完整性（**抽象层在 spec 层面存在、只在代码层面缺失**） |
| **E24** | **铁律检查表遗漏 `mg-work-rules-redlines.mdc` 与 `mg-directory-layout.mdc:10`** | 草稿只引 `AGENTS.md` + `mg-00-first-principles.mdc` + `decisions.md`，未覆盖 `mg-work-rules-redlines.mdc`（规矩 4 诚实必附证据 / 8 停手升层 / 12 零垃圾 / 13 Git 推送红线 / 14 提交前自检）与 `mg-directory-layout.mdc:10`（AI 工具目录边界）→ 直接导致冲突表 #8 的漏检 |
| **E25** | **CLI 上游适配器与铁律 1（密钥只存本地明文配置或环境变量）的张力未识别** | 见冲突表 #15。`AGENTS.md:12` 铁律 1 限定凭据位置；CLI 上游天然依赖厂商 CLI 自持凭据（钥匙串 / OAuth 文件）。草稿 §C.3 方案 4 提到 `--bare` 需 `ANTHROPIC_API_KEY`（合规路径），但未把该约束上升为铁律检查项 |
| **E26** | **未指出 tech-design 与代码的校验缺口** | `tech-design.md:191` 声明两项校验：「资源 `preset` 若非空必须存在于预设注册表」「资源 → vendor_model 必须存在于配置或枚举池」——**`config/schemas.py:219-255` 实际均未实现**（只做了 id/名称唯一性、引用完整性、images+reasoning 警告）。一份"网关现状盘点"报告本应暴露该 doc/code 分歧（草稿 §A.2.2 对代码的描述是正确的，但未与 tech-design 对账） |
| **E27** | 阶段 0.1 未处理"未取证条目的下发语义" | 见 E5：Anthropic 2 条属性为空，建议结构里会输出 `context_window: null` 等；应明确"空值省略字段"策略 |

### 5.3 反向确认：**没有**发现的问题

- 未发现任何**编造的行号**（219 条引用 0 越界）；
- 未发现任何**编造的 URL**（23 条全部可达）；
- 未发现**把不存在的文件/函数/字段当作事实陈述**；
- 未发现草稿建议中**任何远程下发 / 自动更新 / 遥测**类设计（草稿的一致性检查结论在这一点上正确）；
- 草稿对"未验证"的自标注整体诚实（Codex config.toml、Cursor 是否读 `/v1/models`、ACP providers/*、Cherry Studio 其它版本、商汤 plan 窗口语义 —— 均如实标注）。

---

## 六、无法核实的条目

| # | 事项 | 状态与原因 |
|---|---|---|
| 1 | ACP「默认 stdio」 | **无法核实**。官方 README 未载明；schema/v1 与 docs/ 子路径未逐页打开。草稿应降级为"未核实"（E13a） |
| 2 | ACP `providers/list` / `providers/set` / `providers/disable` 提交线索及 `unstable` 标注 | **无法核实**。README 无此内容；草稿已自标"未验证"✅ 处理得当 |
| 3 | Cursor 是否真会读 `/v1/models` | **无法核实**。唯一来源 `php.cn/faq/2930693.html` 为内容农场式文章；Cursor 官方文档站本次未打开（草稿亦称"官方文档站抓取失败"）。草稿标"未验证"✅ 恰当 |
| 4 | Codex CLI `config.toml` 官方字段名 | **无法在官方文档核实**。两个二手来源（airelayrank / devpress）互相一致，草稿标"未在官方文档验证"✅ 恰当 |
| 5 | Cherry Studio 部分版本是否有"获取模型列表"按钮 | **无法核实**。官方文档口径为手填；其它版本行为未验证。草稿已标注 ✅ |
| 6 | `shutdown_date` 是否为"2026 官方 schema 新增" | **无法核实**。字段存在已确认，新增时间无据（E14） |
| 7 | `winbuzzer` 引述的 Anthropic 官方句「Using OAuth tokens obtained through Claude Free, Pro, or Max accounts in any other product, tool, or service…」 | **部分无法核实**。该句出现在 winbuzzer 与 awesomeagents 两篇二手报道中并标注"via Claude Code Docs"，但**当前 `legal-and-compliance` 页面不含该句**（可能是 Consumer Terms 或已改版）。草稿未引该句（无过），但若要强化论证须先定位一手出处 |
| 8 | Anthropic 对文档变更的官方口径（"docs clean up" 还是"新增禁令"） | **存在冲突**，无法判定。同源报道自相矛盾（E8）→ 建议不据此定论 |
| 9 | CLIProxyAPI 的 WebSocket / 函数调用 / 多模态支持 | **未逐项核实**（本次只核实了定位、包装对象、round-robin、DNS-SD、OAuth、赞助商）。草稿表述大概率成立，但建议标"未逐项验证" |
| 10 | 商汤 `plan` 模式额度窗口精确语义 | **无法核实**（草稿已自标）✅ |
| 11 | 用户实际使用的订阅账号类型与厂商 | **未知，必须问用户**（草稿已列为决策点 Q1）✅ |

---

## 七、给调研员的修正优先级

1. **必改（P0）**：E1（config.yaml 7 个模型）、E2（14 个端点）、E3/E4（PRD 行号）、E5（Anthropic 2 条未取证）、E6（base.py 措辞）。
2. **必改（P1 证据纪律）**：E7（补引官方限定段，弱化 §B.2/§C.5 绝对结论）、E8（补引同源反向陈述）、E9（披露来源冲突）、E10（Trae 帖降级为二手）。
3. **必改（P1 铁律一致性）**：E22（适配器接口 vs `tech-design.md:163`，唯一的明确冲突）、E25（CLI 上游凭据 vs 铁律 1）、#8（`mgw setup` 写入边界）。
4. **建议改**：E11–E14（表述降级）、E15–E20（行号/命名微调）、E21/E23/E24/E26/E27（补漏）。

**结论**：草稿的**代码事实层**质量优秀（引用纪律可作范本），**外部证据层**基本可靠但存在选择性引用与分级失当，**合规结论层**存在实质性过度推断，**落地建议与铁律的一致性检查**有 3 处漏检。修正上述 P0/P1 后，可达到可作为 `docs/specs/` 输入依据的质量。

---

*核验结束。本报告为独立审计产出，未修改草稿与项目任何文件。*
