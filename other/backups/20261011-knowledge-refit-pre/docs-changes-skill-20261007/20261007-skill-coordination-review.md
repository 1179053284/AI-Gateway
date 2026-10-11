# 协调性评审（2026-10-07）：六支 skill × 现有规则/规范体系

> 用户问题：「这六个 skill 和现在的项目规则规范协调配合是否最恰当理想的？」
> 方法：读全 `.cursor/rules/`（6 份 267 行）、`.cursor/memory/`（runbook / pitfalls / decisions / modules）、`AGENTS.md` 入口结构、`docs/specs/**` 的分工声明，逐支做协调矩阵，找"同工序多主人 / 与规则打架 / 该由指针承担却被重写"三类问题。

---

## 1. 现有体系的分层与单一主人（先把尺子摆出来）

| 层 | 位置 | 单一主人（谁说了算） | 现状 |
|---|---|---|---|
| 纪律与红线 | `.cursor/rules/*.mdc` | 铁律 1/4/5/6、规矩 12/13/14/16、术语四词、目录边界 | 完备，alwaysApply 三份 + 按需三份 |
| 事实与教训 | `.cursor/memory/pitfalls.md`（50KB） | 现象/根因/修复方向/日期 + 磁盘锚 | 完备（119 行口径） |
| 命令字面 | `.cursor/memory/runbook.md` | 「固定命令，直接复制用」 | 🔴 **12 行空占位**（原文：项目尚未初始化…无命令可复制前禁止凭印象写） |
| 为什么这样定 | `.cursor/memory/decisions.md` | 只追加不改写、同主题取最新 | 完备（含术语统一轮的"改文不改字段"裁定） |
| 需求/设计真相 | `docs/specs/**` | PRD / tech-design / test-cases / design-spec / frontend-spec | 完备 |
| 运行时证据 | `docs/changes/**` | 台账 / 评审（**docs/ 被 gitignore，永不进提交**） | 完备 |
| 入口装配 | `AGENTS.md` | 1 读入口 → 2 读总闸 → 3 按需读规则 → 4 查 memory → 5 读 specs → 6 git status | 🔴 **6 步里没有 skills 入口**；全仓 rules 目录 **0 次**提到 skill（AGENTS 里 "skill" 的唯一出现是模板文件名 `template-{providers,skills}.html`） |

**结论先行**：六支与现有体系**互补性成立**（rules 管纪律、memory 管事实、specs 管需求、skills 管"按需执行协议"），**但要做到"最恰当"还需 3 处结构调整 + 1 处规则打架的处置**（§3），否则会出现"skill 成为命令/教训的第二真相源"。

---

## 2. 逐支协调矩阵（只列有交集的格子）

| 支 | 与 rules | 与 memory | 与 specs / 既有 skill | 判定 |
|---|---|---|---|---|
| **P2 交付环** | 🔴 **与 mg-10「两档流程」打架**（见 §3.1） | runbook 空 ⇒ 命令链无家可归；pitfalls 是教训主人 | AGENTS「验收约定」是完成/SHELL 口径的主人 | ⚠️ **必须先加"快路径排除" + 命令字面落 runbook** |
| **P3 门卫生** | 规矩 12 零垃圾（/tmp 必须清）、mg-11「脚本须元数据头、禁复制变体」 | pitfalls `:25/:54/:58/:69/:71/:73-74` 已是教训主人 ⇒ **指针化**；撤证配方单一主人 = P3（§3.4-C1） | 无既有 skill 覆盖 ⇒ 净增量 | ✅ 协调，需按红线加两条纪律 |
| **P4 实盘审计** | 红线 4（无远程依赖）、mg-11「外部 API 取值格式」、真出站须用户授权（Q32 U-8 口径） | pitfalls `:104`（MG_CONFIG）等 ⇒ 配方归 P4、教训指针化 | 既有 `probe_*.py` 11 支是工具、非协议 ⇒ 不冲突 | ✅ |
| **P5 派杆** | 规矩 5/8（升层/停手）、mg-11 取证分级 | 骨架已在 tech-design §22.9 + 项目 memory ⇒ 只取三样；救援树教训在 pitfalls/memory ⇒ 指针 | `batch-acceptance-merge` 是"合并"主人，P5 是"评审"⇒ 分界写在 description | ✅ |
| **P6 UI 取证** | 规矩 16 单层弹窗（设计阶段就查）、规矩 12 零垃圾 | pitfalls `:15/:52/:64-67` 是教训主人 ⇒ 指针化 | **本地 `ui-pro` 是设计方向主人**（其 12 步循环），P6 ⑧ 已降为指针；frontend/design-spec 是组件真相 ⇒ 不重述 | ✅ |
| **P7 记账** | 规矩 13/14、mg-terminology 的批量替换工序 | pitfall `:95/:99` 是计数口径主人、`decisions.md` 是"为什么"主人 | — | ⚠️ 重写风险最高 ⇒ **折进 P2 第 7 步**（已改） |

---

## 3. 发现的 4 处不协调 + 3 条硬约束（要做"理想"就得先处置）

### 3.1 🔴 P2 与 `mg-10` 快路径打架（唯一真正的规则冲突）
`mg-10-methodology.mdc` 快路径明文：「**不加 todolist、不拆多条、不逐条等人工验收**」+ 单点验证 + pitfalls 补一行即交付。
而 P2 原稿是无条件 9 步（全门 + 岛式计数 + 台账 + 归案 + 上线判定）。
**处置**（写进 P2 description 与第一步）：P2 只对**有交付语义**的改动生效（交付/合并 main/多文件或跨层改动/用户点名验收）；**单点小修走 mg-10 快路径**（取证三选一 → 只改目标文件 → 单点验证 → pitfalls 补一行），P2 负责在末尾提醒"若属快路径请回 mg-10"。不这样做，skill 的自动触发会把每次小修拖成全流程。

### 3.2 🔴 `runbook.md` 空占位 ⇒ 命令字面必须"回家"
从 09-30 到 10-07 的 75 条建议里「命令链」是最高频内容，但盘上唯一为命令准备的容器是空的（12 行占位，且原文禁止凭印象写）。
**处置**：P2/P3/P4 落盘时**同轮把命令字面写进 `.cursor/memory/runbook.md`**（按「环境准备 / 运行 / 验收 / 数据位置」四节），skill 正文只写**顺序与判读**并指 runbook。这样：人复制走 runbook、AI 执行走 skill，命令只有一份。

### 3.3 🔴 入口缺 skills 装配 ⇒ 新会话发现不了这六支
`AGENTS.md` 上下文装配 6 步里没有 skills；`.cursor/rules/` 0 处提及。装到用户级目录后**唯一的发现途径是 description 自动触发**（不可验证、不可靠）。
**处置**（需你点头，改的是入口文件）：在第 3 步后加一行——「3.5 按需调用本项目 playbook（用户级 skill）：交付环 `mgw-delivery-round` / 门卫生 `mgw-gate-hygiene` / 实盘审计 `mgw-live-audit` / 派杆 `mgw-panel-verdict` / UI 取证 `mgw-ui-evidence`；触发路由见各 description」。

### 3.4 🟡 `mg-directory-layout.mdc` 的目录分流表已过期（规则自身腐烂）
表里只有 `model_gateway/`、`docs/`、`tests/`、`scripts/`、`.cursor/`；**没有 2026-10-01 定版的 `coding/`（源码唯一区）与 `bianyiandhuanjing/`（启动器+验收门）**，而六支 skill 的每条命令都落在后两个目录上 ⇒ 读规则的人会以为这些路径"不在规范内"。
**处置**（需你点头）：分流表补两行（`coding/` = 源码/测试/配置样例/venv；`bianyiandhuanjing/` = 启动器 + 机械门 + fixtures），或改为"目录分流以 AGENTS.md「结构定版」为真相源"。

### 3.5 三条已固化的硬约束（写进每支 description，不重述正文）
1. **零垃圾（规矩 12）**：P3 的冻结树副本、P4 的隔离实例数据根、P6 的探针脚本一律 `/tmp`，跑完清理；要入库只能进 `bianyiandhuanjing/scripts/` 且带元数据头（mg-11）。
2. **红线指针**：真出站/烧额度/重启 `:8300` 一律"先获批"（Q32 U-8 口径 + 规矩 13/14）；`push` 无明确指令禁止；README 计数**禁蒙绿**（pitfalls `:99`）。
3. **术语**：正文只用现行四词 + 供应商模型名（`mg-terminology`），不出现"系统模型"；台账类文档在 `docs/`（gitignore，不进提交——skill 要写明，否则会被误读为"没提交=失败"）。

---

## 4. 协调后的理想形态（落盘清单与分工契约）

**落盘清单从 6 支收敛为 5 支 + 1 折入 + 1 备选**：

| 支 | 状态 | 与体系的关系（契约） |
|---|---|---|
| P2 `mgw-delivery-round` | 落盘（骨干） | 纪律引用 rules（规矩 12/13/14/16、红线 4）｜命令落 runbook｜教训指 pitfalls｜完成口径指 AGENTS 验收约定；**含快路径排除** |
| P3 `mgw-gate-hygiene` | 落盘 | 撤证配方**唯一主人**（P2/P5 引用）｜教训指 pitfalls｜门命令字面落 runbook |
| P4 `mgw-live-audit` | 落盘 | 隔离实例配方**唯一主人**｜读数分级指 mg-11 取证分级｜真出站指针红线 |
| P5 `mgw-panel-verdict` | 落盘 | 只装 brief 契约/救援树/撤改即红；骨架指 tech-design §22.9｜与 `batch-acceptance-merge` 分界写进 description |
| P6 `mgw-ui-evidence` | 落盘 | 设计方向指本地 `ui-pro`｜组件规范指 frontend-spec/design-spec｜教训指 pitfalls｜规矩 16 在方案阶段即查 |
| P7 `mgw-repo-bookkeeping` | **折入 P2 第 7 步** | 术语工序指 `mg-terminology`；第二次真实需要再独立 |
| `mgw-catalog-onboarding` | 备选待触发 | 暂无冲突；下次加模型时评 |

**一句话形态**：`.cursor/` = 纪律（为什么+必须）｜`docs/specs` = 需求（做什么）｜`runbook` = 命令（敲什么）｜`pitfalls` = 教训（别再踩）｜**skills = 顺序与停手点（什么时候做、做到哪停、红了怎么办）**。五者各一份，互不复制，全部靠指针连接。

---

## 5. 需要你点头的三项（都属"改项目文件"，故单独列出）

| # | 动作 | 文件 | 代价 |
|---|---|---|---|
| A | 加 skills 入口行（§3.3） | `AGENTS.md` 上下文装配第 3 步后 1 行 | 极小；不动既有内容 |
| B | 目录分流表补 `coding/` 与 `bianyiandhuanjing/`（§3.4） | `.cursor/rules/mg-directory-layout.mdc` | 小；属规则文件（唯一真相源），故必须你点头 |
| C | 命令字面写进 runbook（§3.2） | `.cursor/memory/runbook.md` | 中（三门 + 变异的逐字命令）；这是 P2/P3/P4 落盘的**前置**，否则命令会有两份 |

> 以上三项都不做也能落盘 5 支，但代价是：命令字面留在 skill 里（与 runbook 的定位重复）、新会话靠自动触发发现 skill（不可验证）。**推荐 A+B+C 一起做**。

---

## 6. 未验证 / 未做（如实）

- 本轮**零写入**：未改 AGENTS/规则/runbook、未创建 skill；只新增本文档（`docs/` gitignore）。
- 「skill 自动触发是否可靠」**无法在本会话验证**（须 `/skills reload` + 新会话）；§3.3 加的入口行是**对冲手段**，不是验证结论。
- `mg-directory-layout` 过期一事只核了两处（表内无 `coding/`、无 `bianyiandhuanjing/`），**未逐条核该文件其它小节是否也过期**（如需，我另开一轮全量核）。
- P2 的"快路径排除"是设计裁定，**未实跑对比**（跑一轮小修看是否真的更轻）——落盘后可用一次真实小修验证。
