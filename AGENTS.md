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
5. 查 `.cursor/memory/`：runbook（命令链路）/ decisions（为什么这样定）/ pitfalls（坑位速查）
6. 读需求真相 `docs/specs/`：PRD 为主，tech-design / test-cases / design-spec / frontend-spec 按需；**各 spec 当前版本看下方「当前生效版本表」**，历史版本链在各 spec 头部版本史行，不要在这里展开
7. `git status && git log --oneline -5`（续接时先看 HEAD 与工作区状态，防重做）

## 目录速览
- **结构定版**：`coding/` 源码唯一区（源码/测试/配置样例/双语 README）；`bianyiandhuanjing/` 运行与验收环境（ship-gate 机械门 + verify_* 验收门）；**权威说明 = 根 `项目目录说明.md`**（结构细节与追补史不在此展开）；交接单 `docs/handoffs/`（六节必填 + 判轨理由行，完成移 `done/`）、时点备份 `docs/backups/`。
- 🔴 ~~持续待用户点头两项~~ **两项已于 2026-10-11 完成**（收口轮，用户授权「逐项解决+二次检验+落 main」）：① 推送 origin（75 笔 `5158cbc→d784749`，本地=远端）；② 重启 :8300（隔离冒烟 → config md5 跑前=跑后 → config_version=1 回执新键；复核 = 日志时间戳 / responses 端点 / 总览额度板块 / glm-5.3 实盘 200/1.7s）。**当前待点头**：workbuddycn 轮提交 `6d6feff`（1 笔未推）。
- `.cursor/rules/` — 项目规则；`.cursor/memory/` — 长期记忆（runbook / decisions / pitfalls）；`.cursor/skills/` — 场景手册（入口 INDEX，装配第 4 步）
- `docs/` — `specs/` 需求真相 / `handoffs/` 待用户表态 / `backups/` 时点备份 / `changes/` 实测台账（**开/完结分离**：进行中住 `open/`、完结自主迁 `e2e-records/`，日期+内容 grep 可查；待办 ACTIVE.md 并行协调）
- 近况（只留提炼；叙事原文一律在 `docs/changes/status-archive.md`）：
  - 2026-10-11 · **WorkBuddy（中国版）接入已实现**（第 11 产品 `workbuddycn`，同族参数化；PRD Q44 用户拍板 D1–D5；方案 v2 = `docs/changes/plans/20261011-workbuddycn-integration-plan.md`；台账 `open/E2E-20261011-workbuddycn.md`；**登录/签到/推理真机验收待用户驱动**）+ 同轮修账号静态门 V15 时间炸弹（fixtures 写死日期 10-09 起误红）+ README 双语 2396
  - 2026-10-11 · **收口+修复轮已交付**（用户授权「逐项解决+二次检验+落 main」）：4 条在飞线三批落 main（错误链 P0-1/P1-2/P1-3 + buddy 400 换号 / workbuddy 回调 / 向导确认钮；D 线补台账 `E2E-20261011-error-path-hardening.md`）+ P1-4/P2-6 根治（`a2139dd`，台账 `E2E-20261011-p14-p26-quota-floor-and-output-floor.md`）+ T13 横幅文案（`d784749`）+ `:8300` 重启复核全绿（glm-5.3 实盘 200/1.7s）+ 75 笔推 origin
  - 2026-10-11 · **知识体系重构落地**（skill 归家 `.cursor/skills/` + 入口通用化 + 门禁分级 T0/T1/T2 + 开/完结生命周期 + 知识层入 git；台账 `E2E-20261011-knowledge-refit.md`）
  - 2026-10-09 · **资源池排序改版已交付**（置顶/置底 + 整行拖拽；台账 `E2E-20261009-pool-pin-drag.md`，交接单 `docs/handoffs/20261009-pool-pin-drag.md` 待验收；未生效事项见上 🔴）
  - 2026-09-30 · **M6 多产品账号接入已交付**（全文/面板证据/仍开放决策 = qoder wasm 转发三选一；~~zcode 转发 D1~~ 已于 2026-10-07 实测关闭（3012 台账 §5），见 status-archive「2026-10-11 出栈」节）
  - **当前生效版本表**（spec 头行是本体，本表是入口速查；核对于 2026-10-11）：PRD **v1.32** · tech-design **v2.12** · test-cases **v1.26** · design-spec **v2.53** · frontend-spec **v2.57**。用法：开工前以本表定位各 spec 当前版本；版本间演进链在 spec 头部版本史行，不要在 AGENTS.md 里再堆版本引用。
  - 🔴 **归档指针（2026-10-11 定版，decisions ⑤）**：已出栈叙事与历史证据链一律走 `docs/changes/status-archive.md` → 对应台账；**早于 2026-10-01 的台账/评审/调研文本**已迁 `docs/backups/20261011-pre-october-archive/`（原图像画面证据经用户指令清理；读法声明见 pitfalls 头部与归档 README）；入口快照只保留**带未决线程**的条目，纯完结条目由交付轮自主出栈（存证不改写）。
  - 2026-09-30 · **M6 多产品账号接入与模型转接已交付**（全文叙事 + 未实测清单 + 面板证据已出栈至 `status-archive.md`「2026-10-11 出栈」节）：仍开放 = qoder wasm 转发路线三选一（zcode 模型转发 D1 已于 2026-10-07 实测关闭，`E2E-20261007-zcode-3012-defense.md` §5）。

## 验收约定（简版，细则见 mg-11）
- 完成 = 行为实测证据 + 与需求点逐条对应；`SHELL` = 可跟踪未完成项，禁止打 ✅。
- 交付回复必须带证据；无证据不得宣称完成。
- 🔴 **落地门禁（2026-10-04 用户定版；2026-10-11 增适用面分级）**：T2 白名单面（规则/门禁/术语/spec 契约/对外承诺/不可逆动作/跨面改动）的信息落地或改动生效
  （提交 main、重启 :8300、对外宣称完成），须**多角色独立验收全部 `VERDICT: 通过`（零阻塞）**；
  任一路"不通过"⇒ 逐条复研 → 修或证伪 → **同批角色重跑**，直至全通过。T0 快路径免多角色（mg-10 快档）、T1 标准轮=机械门+R3 轨道一；
  门禁细则与六路切法见 `mg-11-engineering-acceptance.mdc`「⛔ 落地门禁」（分级块在其节首）；概念归属怎么自己判见 `mg-terminology.mdc`「概念归属自动判则」。