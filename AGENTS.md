# AGENTS — Model-Gateway 项目入口（AI 导航总文件）

> 本文件是项目唯一 AI 入口。所有新会话/工具开工前先读本文件，再按需加载规则与记忆，构建上下文。

## 项目是什么
本地运行的 LLM 网关（GitHub 开模型中转工具调研后的**独立自研**实现）：
- 聚合多家模型供应商（OpenAI 兼容体系；厂商 = 生产公司、供应商 = 接入方，见铁律 6），对外暴露**统一 OpenAI 兼容 API**，供 Trae / Cursor / Cherry Studio 等本地程序对接。
- 核心特性：**故障自动切换**——某个供应商通道上的模型调用失败 N 次（如 2 次）后自动切换到备用 Key / 同一个网关模型的其它供应商通道（fallback）。
- 全 **Python** 自研、从零构建；可借鉴开源项目（LiteLLM / One API / New API 等）的**设计思想**，不直接采用或修改第三方闭源/加密产物。

## 铁律（最高优先级，细则见 .cursor/rules/）
1. **全明文配置 · 纯本地运行 · 无远程更新**：密钥只存本地明文配置或环境变量，不入库、不硬编码进源码，禁止任何远程下发/自动更新机制。
2. **诚实必附证据**：任何「已实现 / 已跑通 / 已完成」须附运行输出 / diff / `file:line`；无证据一律写「未验证」。
3. **同问题 2 次未解决 → 停手升层书面停报**，禁止原地打补丁。
4. **无依据自创禁止**：一切以需求真相 `docs/specs/`（PRD 为主）与用户确认为唯一依据。
5. **发现问题必须报告，禁止敷衍解决**（2026-09-05 用户强调）：发现问题/偏差/坏味道必须主动报告并给出处理建议，禁止隐瞒不报、搁置不处理、随意打补丁敷衍交差；**禁止堆屎山与屎上雕花工程**（细则见 `mg-work-rules-redlines.mdc` 规矩 5/7/8）。
6. **术语唯一口径（2026-10-04 用户定版，全仓强制）**：**厂商 = 模型生产公司**（DeepSeek、月之暗面…）；**供应商 = 接入方**（「接入模型资源」里每个 Key 接入 + 「接入账号资源」里每个产品/账号）；**网关模型 = 把各供应商的同一厂商模型标准化成一个名字并统一规格**（旧称「系统模型」作废、同义）；**资源 = 供应商名下一条可调用模型接入 = 两个接入页共同维护的对象**。旧文/旧注释/旧界面文案把供应商叫「厂商」、把网关模型叫「系统模型」，一律按此纠正（定义源 `docs/specs/prd.md` §2；执行细则与替换表 `mg-terminology.mdc`）。🔴 **存证不改写**：`docs/changes/**` 台账与评审记录、各文档的版本史行（`> vN（…）`、变更表 `| v… |`、`> N. v0.x…→ **推翻**` 原因链、`## 5.1 实施校正记录` 这类校正记录）、Q## 归档条目原文、用户原话引号内 —— 一律保留当时措辞，只加读法声明；旧文里指接入方的「厂商」按**供应商**读、「系统模型」按**网关模型**读。

## 上下文装配（新会话首动作）
1. 读本文件（入口）
2. 读 `.cursor/rules/mg-00-first-principles.mdc`（入口总闸，alwaysApply）
3. 按需读其余规则：`mg-terminology.mdc`（术语唯一口径，alwaysApply）/ `mg-work-rules-redlines.mdc` / `mg-directory-layout.mdc` / `mg-10-methodology.mdc` / `mg-11-engineering-acceptance.mdc`
4. 按需调用本项目场景手册（真身唯一住址 `.cursor/skills/`，入口与触发路由 = `INDEX.md`；工具家目录一律不维护 skill，任何 AI 工具经本文件三跳内到达全部知识）：`mgw-delivery-round`（一轮改动→交付）/ `mgw-gate-hygiene`（门卫生与报红归因）/ `mgw-live-audit`（实盘只读核查）；主人契约见 INDEX，门命令字面见 runbook
5. 查 `.cursor/memory/`：runbook（命令链路）/ decisions（为什么这样定）/ pitfalls（坑位速查）/ modules（模块事实表）
6. 读需求真相 `docs/specs/`：PRD 为主，tech-design / test-cases / design-spec / frontend-spec 按需；**各 spec 当前版本看下方「当前生效版本表」**，历史版本链在各 spec 头部版本史行，不要在这里展开
7. `git status && git log --oneline -5`（续接时先看 HEAD 与工作区状态，防重做）

## 目录速览
- **结构定版（2026-10-01，对齐 codex-coding）**：`coding/` = 源码唯一区（model_gateway / tests / pyproject / config.example.yaml / README / LICENSE / .venv / data）；`bianyiandhuanjing/` = 运行与验收环境（`启动网关.command` + `scripts/`：ship-gate.sh 机械门 + verify_*/ui_verify_* 验收门 + fixtures）；权威说明 = 根 `项目目录说明.md`；git 仓库保持在根。**2026-10-08 追补（已获用户点头，凭据 = `other/handoffs/20261008-structure-other-handoffs.md`）**：新增根 `other/handoffs/` = AI→用户交接单唯一出口（六节必填 + 判轨理由行，完成移 `done/`），与 codex `other/people-todolist/` 同构；`docs/`/`.cursor/` 被 .gitignore:25/:17 整目录忽略，交接单不落那里
- 🔴 **状态链补记（2026-10-08 落地批，凭据 = `other/handoffs/20261008-structure-other-handoffs.md`）**：`4bd0a6d`（映射弹窗两处收口：进池开关点亮「保存」+ 弹窗辅助文案人话化 + 门锚重定，三文件原子提交）**已实施待验收 → 验收通过（D5 终稿轮：三角色五轮交叉验收全过 + 当场复跑读数原文 `docs/changes/e2e-records/gate-raw-20261008-4bd0a6d-recheck.log`）**；纯前端，刷新即生效，无重启需求
- 🔴 **待合并收口轮（2026-10-08 晚，本会话执行；用户指令「逐一核实每个待合并改动…逐一进行合并」）**：工作区 51 个未提交路径**逐一路径核实归属与在册台账**（无一「状态没更新」的假未合并——`fix/zcode-selection-gate` 分支除外：`4fb9b05` 早已是 main 祖先，分支与 `/private/tmp/mgw-zcode-fix` worktree 纯状态残留，已清）后按 R4 锚耦合闭包**分 14 批原子落账**（`2272863`…`2e781ef`，含并行会话 `8c5e906` 交插事件如实归因：其 apidocs/base.css 段与本收口轮锚耦合互补落齐）；收口轮新抓两条根因修复：① `366962c` local_admin 禁环境代理（本机 `http_proxy=127.0.0.1:7890` 把对 `127.0.0.1:<port>` 的 CLI 探活转发走代理，空端口得 502 落「timeout」而非「not-running」，三态判据失真——铁律 1 纯本地的漏网口）；② `865a963` 打桩点随 `_local_opener` 前进（门侧自纠非放宽）。终局机械门 = 全量 `2349 passed / 3 skipped` + v2 门 `145/145` + 账号门 `33/0` = **SHIP-GATE: GREEN**（原文 `docs/changes/e2e-records/gate-raw-20261008-merge-closure.log`，2026-10-08 21:5x）；README 双语同步 **2349**；工作区干净。⚠️ 如实报备三条：origin/main 仍停在 `5158cbc`（**60 个本地提交未推送**，推送需用户点头）；收口轮后台全量门期间 `coding/data/config.yaml` 有运行态写入（gitignored 运行数据，非源码面）；**:8300 未重启** ⇒ 3012 防线 / cline-403 换号 / responses 端点 / 总览额度板块等含后端改动的已落账功能**线上尚未生效**（重启须用户点头）
- `.cursor/rules/` — 项目规则（mdc，AI 工具可自动加载）
- `.cursor/memory/` — 项目长期记忆（runbook / decisions / pitfalls / modules）
- `docs/specs/` — 需求真相（PRD 与各域 spec）
- `docs/changes/` — 实测记录/运行证据（铁律 2）；**开/完结分离（2026-10-11 定版）**：进行中住 `open/`、完结自主迁 `e2e-records/`（日期+内容 grep 可查）；并行任务出现时建立 ACTIVE.md 协调
- `coding/model_gateway/` + `coding/tests/` + `coding/pyproject.toml` + `coding/config.example.yaml` — 源码唯一区 `coding/`（结构见 tech-design.md §7）。**历史交付叙事（~60 轮）已全量归档至 `docs/changes/status-archive.md`（原文不改写），入口只留近况提炼：**
  - 2026-10-09 · **资源池排序改版：↑/↓ → 置顶/置底 + 整行拖拽**（frontend-spec v2.55 §3.4；台账 `E2E-20261009-pool-pin-drag.md`；v2 门 148/0 + 变异 209/209 + 批次 pytest 78 passed + 隔离实例真机 4 连保存/拖拽落盘全对；🔴 两处真值修正：旧 `swapUnits` 的 ↑ 恒等空操作 bug、乐观锁双计次（PUT+mtime 轮询各 reload 一次 ⇒ 连续第二次保存必 409，`main.py` mtime 共享记账修复）——**含后端改动，:8300 未重启前连续保存仍会撞 409**）
  - 2026-10-08 · **待合并收口轮：51 路径逐一核实 + 14 批落账 + 代理漏网口修复**（commit `2272863`…`2e781ef`；全量 2349/3 + v2 门 145/145 + 账号门 33/0 GREEN；台账 `gate-raw-20261008-merge-closure.log`；🔴 60 提交未推送 origin、:8300 未重启线上未生效——两条都待用户点头）
  - 更早轮次（M1/M2、Q18–Q43 各轮、图标/额度/设置页/映射弹窗系列）：见归档 `docs/changes/status-archive.md` 与 `docs/changes/e2e-records/`
  - **当前生效版本表**（spec 头行是本体，本表是入口速查；核对于 2026-10-08）：PRD **v1.31** · tech-design **v2.10** · test-cases **v1.25** · design-spec **v2.53** · frontend-spec **v2.54**。用法：开工前以本表定位各 spec 当前版本；版本间演进链在 spec 头部版本史行，不要在 AGENTS.md 里再堆版本引用。
  - 🔴 **归档指针（2026-10-11 起按「开/完结分离」执行，decisions ⑤）**：查证已出栈的历史交付证据链一律走 `docs/changes/status-archive.md` → 对应台账；入口快照只保留**带未决线程**的条目（未完结面），纯完结条目由交付轮自主出栈至该归档（新条目追加在归档末尾，存证不改写）。
  - 2026-09-30 · **M6 多产品账号接入与模型转接已交付**（全文叙事 + 未实测清单 + 面板证据已出栈至 `status-archive.md`「2026-10-11 出栈」节）：仍开放 = qoder wasm 转发路线三选一、zcode 模型转发 D1。

## 验收约定（简版，细则见 mg-11）
- 完成 = 行为实测证据 + 与需求点逐条对应；`SHELL` = 可跟踪未完成项，禁止打 ✅。
- 交付回复必须带证据；无证据不得宣称完成。
- 🔴 **落地门禁（2026-10-04 用户定版；2026-10-11 增适用面分级）**：T2 白名单面（规则/门禁/术语/spec 契约/对外承诺/不可逆动作/跨面改动）的信息落地或改动生效
  （提交 main、重启 :8300、对外宣称完成），须**多角色独立验收全部 `VERDICT: 通过`（零阻塞）**；
  任一路"不通过"⇒ 逐条复研 → 修或证伪 → **同批角色重跑**，直至全通过。T0 快路径免多角色（mg-10 快档）、T1 标准轮=机械门+R3 轨道一；
  门禁细则与六路切法见 `mg-11-engineering-acceptance.mdc`「⛔ 落地门禁」（分级块在其节首）；概念归属怎么自己判见 `mg-terminology.mdc`「概念归属自动判则」。