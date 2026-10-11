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
4. 按需调用本项目 playbook（用户级 skill，装在 `~/.qoder-cn/skills/`）：`mgw-delivery-round`（一轮改动→交付）/ `mgw-gate-hygiene`（门卫生与报红归因）/ `mgw-live-audit`（实盘只读核查）；触发路由与边界见各 description，门命令字面见 runbook
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
- `docs/changes/` — 实测记录/运行证据（铁律 2；如 `M1-task1-scaffold.md`）；并行任务出现时建立 ACTIVE.md 协调
- `coding/model_gateway/` + `coding/tests/` + `coding/pyproject.toml` + `coding/config.example.yaml` — 源码唯一区 `coding/`（结构见 tech-design.md §7）。**历史交付叙事（~60 轮）已全量归档至 `docs/changes/status-archive.md`（原文不改写），入口只留近况提炼：**
  - 2026-10-09 · **资源池排序改版：↑/↓ → 置顶/置底 + 整行拖拽**（frontend-spec v2.55 §3.4；台账 `E2E-20261009-pool-pin-drag.md`；v2 门 148/0 + 变异 209/209 + 批次 pytest 78 passed + 隔离实例真机 4 连保存/拖拽落盘全对；🔴 两处真值修正：旧 `swapUnits` 的 ↑ 恒等空操作 bug、乐观锁双计次（PUT+mtime 轮询各 reload 一次 ⇒ 连续第二次保存必 409，`main.py` mtime 共享记账修复）——**含后端改动，:8300 未重启前连续保存仍会撞 409**）
  - 2026-10-08 · **待合并收口轮：51 路径逐一核实 + 14 批落账 + 代理漏网口修复**（commit `2272863`…`2e781ef`；全量 2349/3 + v2 门 145/145 + 账号门 33/0 GREEN；台账 `gate-raw-20261008-merge-closure.log`；🔴 60 提交未推送 origin、:8300 未重启线上未生效——两条都待用户点头）
  - 2026-10-08 · **对接说明清单表每行模型 ID 后配复制钮**（design-spec v2.53 / frontend-spec v2.54 §6 末条；台账 `E2E-20261008-apidocs-modelid-copy.md`；🔴 该页此前整页未跟踪 ⇒ 提交单元含整页 + 侧栏接线 + 该页 CSS 三段 + `help/`）
  - 2026-10-08 · **对接说明页四颗复制钮搬进代码框内右上角**（design-spec v2.52 / frontend-spec v2.53；台账 `E2E-20261008-apidocs-codecopy.md`）
  - 2026-10-08 · **`/v1/responses` 兼容端点透传**（test-cases v1.25；台账 `E2E-20261008-responses-endpoint.md`，含撞车专节 §5——并行会话同树同功能，停手判据已归案）
  - 2026-10-08 · **趋势图柱体 0px 事故与假 DOM 门补强**（新探针 `probe_trend_charts_geometry.py`；台账 `E2E-20261008-trend-bars-zero-height.md`）
  - 2026-10-08 · **cline-403 resource-unavailable 换号链路**（台账 `E2E-20261008-cline-403-resource-unavailable.md`）
  - 2026-10-08 · **R3 落账/验收双轨制 + 交接单结构落地**（decisions.md 2026-10-08；凭据 `other/handoffs/20261008-structure-other-handoffs.md`）
  - 2026-10-08 · **映射弹窗两处收口**（commit `4bd0a6d`，D5 终稿轮五轮交叉验收通过；台账 `E2E-20261006-map-switch-save-btn.md`）
  - 2026-10-07 · **总览「账号资源额度」板块**（PRD Q43，frontend-spec v2.52 §7.20；台账 `E2E-20261007-overview-account-quota.md`）
  - 2026-10-07 · **accounts.js 拆分收口 + 配置代次乐观锁**（commit `172e17b`；详细叙事在归档）
  - 2026-10-06 · **P0/P1/P2 修复批**：拆分遗留全局不可用（`6df2ca5`）→ fmtTok/switchEl 未定义（`f6ea951`）→ 映射弹窗收口（`4bd0a6d`）；单账号并发上限 `concurrency_cap`（`0992863`）
  - 2026-10-05 · **草稿制落账**：auto-map 不再是写面（tech-design v2.10 §9-Q41；台账 `E2E-20261005-map-draft-mode.md`）
  - 更早轮次（M1/M2、Q18–Q43 各轮、图标/额度/设置页/映射弹窗系列）：见归档 `docs/changes/status-archive.md` 与 `docs/changes/e2e-records/`
  - **当前生效版本表**（spec 头行是本体，本表是入口速查；核对于 2026-10-08）：PRD **v1.31** · tech-design **v2.10** · test-cases **v1.25** · design-spec **v2.53** · frontend-spec **v2.54**。用法：开工前以本表定位各 spec 当前版本；版本间演进链在 spec 头部版本史行，不要在 AGENTS.md 里再堆版本引用。
  - 🔴 **归档指针**：查证 2026-10-08 之前的历史交付证据链一律走 `docs/changes/status-archive.md` → 对应台账；新状态链条目追加在该归档末尾（仍遵守「存证不改写」），入口快照只维护最近两周。

## M6 多产品账号接入与模型转接（2026-09-30 **已交付**）
- 指令 = PRD v1.19 §9-Q29：DSH 插件全部产品（**除华为云 CodeArts**）的「账号接入/管理/切换/签到领取」+ **模型转发**整合进网关；架构 `tech-design.md` §22（10 实例 registry、`accounts/` 最小公共层 + `upstream/<product>/` 薄模块 + 转接层复用既有调度）。
- **证据（可复跑）**：台账 `docs/changes/e2e-records/E2E-20260930-M6-multi-product.md`（评审→修复→**撤修复红证**全表）；对抗评审 `docs/changes/reviews/m6-r{1,2,3,4}-*.md`；交付面板 `m6-panel-{pm,pm-2,pm-3,eng-a,eng-a-2,eng-b,ix}.md` —— **四角色全部「通过 · 0 阻塞」**；前端真机断言 81 项 + 截图（`m6-accounts-*` / `m6-panel-ix-*`）。
- 计数：`pytest -q` → **1560 passed / 0 failed**（README 双语同值；数字取自 2026-09-30 全量跑的输出行 `1 failed, 1560 passed, 1 skipped in 369.16s`——那 1 红项正是钉这个数字的 `test_readme_test_counts_are_not_stale` 本身，同步到 1560 后即绿）。M7 一轮另加：回调接收端 + 页面改版 + zcode/扫码登录，判据 `node scripts/verify_accounts_ui.mjs` = 13 通过 / 0 失败、真机门 151 通过 / 0 失败。
- **未实测（用户驱动，不得写成已完成）**：真实凭据逐产品登录/领取；zcode 直连 405/3012（D1）；qoder 签名缝与 zcode 验证码缝（均 **fail-closed**，未注入时资源不进 `/v1/models` 且有横幅）；T5a/T5b、T10；各产品 `stream:false` 等现场项（清单见 §22.11 与台账）。
- 新增：管理端「账号接入」页（`#/accounts`，遵守 frontend-spec）+ `/admin/api/accounts*`（含 `models` 目录出口）；**`mgw zcode login` 已接真实设备流**（2026-09-30 补口；退出码 0/1/2/3 契约不变）；跨进程写盘互斥 `data/locks/accounts.lock`（fail-closed）。
- **仍开放（需用户决策）**：qoder/qodercn 模型转发（签名含 292KB WASM：引入 wasm 运行时 / 逆向重写 / 维持 fail-closed）；zcode 模型转发（D1 最小实测后接线）。

## 验收约定（简版，细则见 mg-11）
- 完成 = 行为实测证据 + 与需求点逐条对应；`SHELL` = 可跟踪未完成项，禁止打 ✅。
- 交付回复必须带证据；无证据不得宣称完成。
- 🔴 **落地门禁（2026-10-04 用户定版）**：任何信息落地（写进 `docs/specs/`、台账、记忆、README）或改动生效
  （提交 main、重启 :8300、对外宣称完成），须**多角色独立验收全部 `VERDICT: 通过`（零阻塞）**；
  任一路"不通过"⇒ 逐条复研 → 修或证伪 → **同批角色重跑**，直至全通过。门禁细则与六路切法见
  `mg-11-engineering-acceptance.mdc`「⛔ 落地门禁」；概念归属怎么自己判见 `mg-terminology.mdc`「概念归属自动判则」。