# 建议 skill 全量清单（Model-Gateway · 09-30 ~ 10-07）

> 证据源：桌面端数据库 `~/Library/Application Support/com.qodercn.app.stable/main.sqlite` 表 `skill_evolution_suggestions`（界面右侧「建议 skill」的真身）。
> 复算命令（只读，先拷库到 /tmp 再查，勿直连活库）：
> ```
> cp ~/Library/Application\ Support/com.qodercn.app.stable/main.sqlite* /tmp/mgdb/ && \
> sqlite3 /tmp/mgdb/main.sqlite "SELECT COUNT(*) FROM skill_evolution_suggestions s JOIN chat_sessions c ON c.session_id=s.source_session_id WHERE c.cwd LIKE '%Model-Gateway%';"
> ```

- 总数 **75** 条，覆盖 **19** 个会话（09-30 05:36 → 10-07 10:37）
- 状态分布：{'evolving': 6, 'pending': 69}（`pending`=从未采纳；`evolving`=发起过创建但**没有一份落盘**，转换率 0/75）
- 孤儿建议（来源会话已被删除）= **0**：会话删除不级联删建议，且当前 `chat_sessions.deleted_at` 非空行 = 0 ⇒ 「含已删除会话」这条已查证，无遗漏项
- 每个会话的条数：多为 5 条（最高 9 条）——与界面右侧「四五个」一致

## 簇分布

| 簇 | 条数 |
|---|---|
| A 交付环（一轮改动→交付） | 16 |
| B 判据/门卫生与归因 | 9 |
| C UI 量测/取证 | 6 |
| D 设计先行（改版前） | 3 |
| E 多角色/多代理面板 | 8 |
| F 实盘只读核查/就绪审计 | 17 |
| G 仓库/记账/术语维护 | 8 |
| H 目录接入/额度展示/桥接 | 4 |
| I 沟通与元 | 4 |

## 全量明细（按时间序）

| # | skill_name | 簇 | 时间 | 状态 | 置信 | 来源会话 |
|---|---|---|---|---|---|---|
| 1 | `multi-agent-wave-delivery` | A | 09-30 05:36 | evolving | 0.85 | 多账号接入与网关调研（已归档） |
| 2 | `delegated-fix-red-proof` | E | 09-30 05:36 | evolving | 0.75 | 多账号接入与网关调研（已归档） |
| 3 | `integration-transport-existence-audit` | F | 09-30 16:07 | pending | 0.88 | 多账号接入与网关调研（已归档） |
| 4 | `design-validate-before-code` | D | 09-30 20:14 | pending | 0.86 | 多账号接入与网关调研（已归档） |
| 5 | `ui-redesign-validate-first` | D | 09-30 20:29 | pending | 0.88 | 多账号接入与网关调研（已归档） |
| 6 | `ui-redesign-mutation-gate` | B | 09-30 21:53 | pending | 0.86 | 多账号接入与网关调研（已归档） |
| 7 | `ui-redesign-validate-before-code` | D | 09-30 22:07 | pending | 0.86 | 多账号接入与网关调研（已归档） |
| 8 | `mgw-console-page-delivery` | A | 10-01 06:35 | pending | 0.82 | 新增左侧模板菜单（已归档） |
| 9 | `cdp-browser-evidence` | C | 10-01 06:35 | pending | 0.7 | 新增左侧模板菜单（已归档） |
| 10 | `cdp-headless-evidence` | C | 10-01 06:53 | pending | 0.8 | 新增左侧模板菜单（已归档） |
| 11 | `model-gateway-ui-template-delivery` | A | 10-01 06:53 | pending | 0.7 | 新增左侧模板菜单（已归档） |
| 12 | `repo-process-cleanup` | G | 10-01 07:16 | pending | 0.7 | 清理项目无用文件（已归档） |
| 13 | `repo-restructure-coding-zone` | G | 10-01 07:49 | pending | 0.78 | 清理项目无用文件（已归档） |
| 14 | `mg-ui-change-verify` | A | 10-01 15:21 | pending | 0.75 | 调整模型按钮位置（已归档） |
| 15 | `model-gateway-gate-sync` | A | 10-01 15:50 | pending | 0.7 | 调整模型按钮位置（已归档） |
| 16 | `isolated-instance-e2e` | F | 10-01 16:06 | pending | 0.72 | 调整模型按钮位置（已归档） |
| 17 | `model-gateway-delivery-round` | A | 10-01 16:46 | pending | 0.85 | 调整模型按钮位置（已归档） |
| 18 | `ui-entry-discoverability` | C | 10-01 16:46 | pending | 0.7 | 调整模型按钮位置（已归档） |
| 19 | `model-gateway-live-delivery` | A | 10-01 17:04 | pending | 0.85 | 归档-网关添加主流模型（已归档） |
| 20 | `mgw-ui-gate-sync` | A | 10-01 20:12 | pending | 0.75 | 接入账号资源页面调整（已归档） |
| 21 | `unreproducible-gate-red-triage` | B | 10-01 21:05 | pending | 0.72 | 商品和我的订单 在弹窗中改成两个tab，具体参考ZCode Panel 显示的数据和形式给我做到…（已归档） |
| 22 | `mgw-admin-ui-gate-round` | A | 10-01 21:41 | pending | 0.86 | 接入账号资源页面调整（已归档） |
| 23 | `port-account-plan-quota-display` | H | 10-01 21:41 | pending | 0.7 | 接入账号资源页面调整（已归档） |
| 24 | `mgw-frontend-gate-rework` | A | 10-01 23:15 | pending | 0.82 | 接入账号资源页面调整（已归档） |
| 25 | `live-cron-scheduled-leg-verification` | F | 10-01 23:15 | pending | 0.78 | 接入账号资源页面调整（已归档） |
| 26 | `gate-embedded-js-selfcheck-and-criterion-advance` | B | 10-02 15:10 | evolving | 0.84 | 页面UI调整（已归档） |
| 27 | `multi-role-product-verdict-research` | E | 10-02 15:10 | pending | 0.88 | API调用条件核实 |
| 28 | `mgw-change-delivery-round` | A | 10-02 20:25 | evolving | 0.85 | 页面UI调整（已归档） |
| 29 | `serial-mutation-falsifiability-harness` | B | 10-02 21:46 | pending | 0.88 | API调用条件核实 |
| 30 | `serial-mutation-falsification` | B | 10-03 01:32 | pending | 0.88 | API调用条件核实 |
| 31 | `ui-gate-red-triage` | B | 10-03 10:27 | evolving | 0.85 | 页面UI调整（已归档） |
| 32 | `ui-defect-to-gate-pipeline` | C | 10-03 11:08 | evolving | 0.82 | 页面UI调整（已归档） |
| 33 | `oil-ui-pro` | I | 10-03 13:10 | pending | 0.88 | 页面UI调整（已归档） |
| 34 | `frontend-ui-change-gate-loop` | A | 10-03 17:30 | pending | 0.86 | 页面UI调整（已归档） |
| 35 | `mgw-ui-change-verify-loop` | A | 10-03 17:46 | pending | 0.88 | 页面UI调整（已归档） |
| 36 | `headless-ui-geometry-proof` | C | 10-03 17:54 | pending | 0.86 | 页面UI调整（已归档） |
| 37 | `mgw-ui-verification-ladder` | A | 10-03 20:34 | pending | 0.86 | 页面UI调整（已归档） |
| 38 | `model-gateway-vendor-catalog-onboarding` | H | 10-04 06:52 | pending | 0.9 | 归档-网关添加主流模型（已归档） |
| 39 | `official-doc-model-evidence-panel` | E | 10-04 06:52 | pending | 0.8 | 归档-网关添加主流模型（已归档） |
| 40 | `gateway-logic-audit-report` | E | 10-04 08:49 | pending | 0.85 | 网关资源调度与重试逻辑 |
| 41 | `gateway-live-state-probes` | F | 10-04 08:49 | pending | 0.8 | 网关资源调度与重试逻辑 |
| 42 | `pm-plain-answer-format` | I | 10-04 08:49 | pending | 0.7 | 网关资源调度与重试逻辑 |
| 43 | `channel-constraint-verification` | F | 10-04 09:35 | pending | 0.86 | 归档-网关添加主流模型（已归档） |
| 44 | `island-readme-test-count` | G | 10-04 09:35 | pending | 0.8 | 归档-网关添加主流模型（已归档） |
| 45 | `repo-terminology-sweep` | G | 10-04 11:12 | pending | 0.85 | API调用条件核实（分支） |
| 46 | `terminology-concept-unification` | G | 10-04 11:44 | pending | 0.86 | API调用条件核实（分支） |
| 47 | `multi-agent-concept-audit` | E | 10-04 11:44 | pending | 0.78 | API调用条件核实（分支） |
| 48 | `mg-empty-field-layer-diagnosis` | F | 10-04 11:44 | pending | 0.78 | 排查网关模型参数为空问题（已归档） |
| 49 | `mg-live-tree-provenance` | F | 10-04 11:44 | pending | 0.62 | 排查网关模型参数为空问题（已归档） |
| 50 | `multiagent-concept-audit` | E | 10-04 11:48 | pending | 0.82 | API调用条件核实（分支） |
| 51 | `terminology-bulk-rename` | G | 10-04 11:48 | pending | 0.8 | API调用条件核实（分支） |
| 52 | `client-wasm-signing-bridge` | H | 10-04 21:54 | pending | 0.86 | API调用条件核实 |
| 53 | `mgw-ui-change-gate-forward` | A | 10-04 23:19 | pending | 0.85 | 移除状态列（已归档） |
| 54 | `ego-probe-zero-window-hygiene` | C | 10-04 23:19 | pending | 0.8 | 移除状态列（已归档） |
| 55 | `mgw-spec-writeback-bookkeeping` | G | 10-04 23:19 | pending | 0.72 | 移除状态列（已归档） |
| 56 | `mgw-frontend-delivery-chain` | A | 10-05 00:51 | pending | 0.82 | 移除状态列（已归档） |
| 57 | `mgw-gate-criterion-migration` | B | 10-05 00:51 | pending | 0.78 | 移除状态列（已归档） |
| 58 | `shared-tree-hunk-commit-island-verify` | G | 10-05 07:11 | pending | 0.88 | API调用条件核实 |
| 59 | `gateway-automation-attribution` | F | 10-05 07:22 | pending | 0.72 | 自动化更新逻辑 |
| 60 | `mg-criterion-advance-with-design-loop` | B | 10-05 08:24 | pending | 0.82 | 修复模型资源与映射（已归档） |
| 61 | `mg-two-truths-live-diagnosis` | F | 10-05 08:24 | pending | 0.78 | 修复模型资源与映射（已归档） |
| 62 | `gateway-automation-loop-audit` | F | 10-05 11:08 | pending | 0.75 | 自动化更新逻辑 |
| 63 | `mgw-instance-restart-verify` | F | 10-05 11:10 | pending | 0.82 | 修复模型资源与映射（已归档） |
| 64 | `mgw-gate-terminal-evidence` | B | 10-05 11:10 | pending | 0.78 | 修复模型资源与映射（已归档） |
| 65 | `gateway-channel-failover-verification` | F | 10-05 14:05 | pending | 0.82 | 网关调用可用性评估 |
| 66 | `mg-offline-failover-matrix` | F | 10-05 14:08 | pending | 0.86 | 网关调用可用性评估 |
| 67 | `mg-live-pool-readiness-audit` | F | 10-05 14:08 | pending | 0.82 | 网关调用可用性评估 |
| 68 | `gateway-pool-selection-audit` | F | 10-05 14:37 | pending | 0.85 | 网关调用可用性评估 |
| 69 | `gateway-model-dispatch-selection-audit` | F | 10-05 16:24 | pending | 0.86 | 网关调用可用性评估 |
| 70 | `mgw-instance-liveness-proof` | F | 10-05 18:51 | pending | 0.82 | 修复模型资源与映射（已归档） |
| 71 | `multi-role-architecture-audit` | E | 10-05 18:59 | pending | 0.82 | 架构合理性分析 |
| 72 | `subagent-panel-rescue` | E | 10-05 18:59 | pending | 0.72 | 架构合理性分析 |
| 73 | `jethub-account-handoff` | H | 10-05 23:50 | pending | 0.8 | 导入ZCode账号数据 |
| 74 | `skill-suggestion-recovery` | I | 10-07 10:37 | pending | 0.8 | 推荐高价值技能 |
| 75 | `skill-portfolio-review` | I | 10-07 10:37 | pending | 0.7 | 推荐高价值技能 |


---

## 附录：逐条摘要+理由（原文）

### 1. multi-agent-wave-delivery
- 09-30 05:36 · evolving · 置信 0.85 · 「多账号接入与网关调研」
- 摘要：大规模功能落地的多代理波次流水线：① 先冻结接口与数据契约（写死签名/默认值/语义，并配签名一致性测试）→ ② 单代理打地基（公共层/骨架）→ ③ 按文件独占切分并行实现（每代理 ≤2 个模块块；共享注册表用小粒度 Edit、失败即重读重试）→ ④ 每波收尾由总 agent 亲自核证（读磁盘文件与行数、跑定向+全量测试、grep 每个新能力的生产调用点、同步 README 计数）→ ⑤ 对抗式评审波（只写报告不改码、/tmp 副本、唯一 --basetemp、报告先建后增量写防中途死亡、结论只允许 通过/不通过+阻塞数）→ ⑥ 带红证的修复轮 → ⑦ 只复验未过的角色（不必整面板重跑）→ 零阻塞才交付；代理撞轮次上限死亡时按其磁盘产物核证并重派 ≤2 块的小切片（附精确失败输出）。
- 理由：本对话全程验证：10+ 子代理多次在 150 轮上限处中断但产物完整（判据是磁盘而非报告）、每波次都靠总 agent 复跑与 grep 抓到「已造函数但无生产调用点」类假交付（list_models 零出口、*_async 未接线、quota 无通路）、面板两次抓到台账滞后与未记录改动。把这些切片尺寸/核证闸门/救援流程固化成 playbook，另一代理可逐字复用。

### 2. delegated-fix-red-proof
- 09-30 05:36 · evolving · 置信 0.75 · 「多账号接入与网关调研」
- 摘要：委托修复的「撤修复红证」协议：每个修复条目必须 ① 先复现原始失败输出 → ② 实施修复 → ③ 仅回退该修复并捕获「确实变红」的输出（保留红证文本进台账）→ ④ 恢复后跑全量确认绿；⑤ 总 agent/复验角色必须独立重做≥1 条红证、且自写探针而不是复用修复者自己的用例；⑥ 护栏类改动须先植入坏用例证明能红（空壳假实现、未接线、绕过的容差都必须被拦——变不了红的护栏不算护栏）。
- 理由：本对话的所有阻塞项（P-B1 写回自检、A-1 事件循环阻塞、B-1 热重载死亡、B-2 复活链路）都靠该协议闭环：修后 2 绿→回退 2 红→恢复绿、心跳 2ms↔1022ms 对照；且两次抓到「绿但未接线」的假闭环。红证是唯一能打穿假绿的机械判据，值得独立成 skill 供任何委托修复场景套用。

### 3. integration-transport-existence-audit
- 09-30 16:07 · pending · 置信 0.88 · 「多账号接入与网关调研」
- 摘要：审计「对接类功能」的传输通道是否真实存在的固定流程：先全包 grep 该功能必需的底层原语（监听套接字 / 自定义协议注册 / 路由），再对**正在跑的实例**把它交给浏览器或上游的那个 URL 真的请求一次（404 / connection refused 即红证），然后 grep 测试里有没有任何一条真的向该地址发过请求（还是自己手搓回调串直接喂给 handler），最后按「物理不可能 / 已降级 / 未验证」给每条流程分级。
- 理由：本轮用户推翻了我已交付的结论（「所有的账号接入和回调都有问题」），1464 条 mock 测试全绿而真机全废，根因正是测试把缺失的通道自己实现了（`tests/accounts/test_trae.py:127-140` 手搓回调 URL 直调 `login_callback`，全包零测试向该地址发过 HTTP）。我这套定位方法是可被另一个 agent 逐字复跑的（grep 原语 → 打活实例 → grep 测试到达性 → 与参考实现的三型通道对表），且完全可迁移到任何 webhook / OAuth 回跳 / 回调类功能，属于典型的「mock 全绿掩盖零实现」误判模式，值得固化成按需加载的 playbook。

### 4. design-validate-before-code
- 09-30 20:14 · pending · 置信 0.86 · 「多账号接入与网关调研」
- 摘要：改造既有 UI/交互前的固定流水线：4 路并行只读地基（规范硬约束+现实现审计+参考程序同类做法+可用组件清单）→ 3 个互相竞争的设计方向（每个 brief 内嵌已核实事实与硬约束行号）→ 独立对抗评审攻击设计书 → 用项目真样式表 + 真 API 形状 fixture 做 /tmp 可点原型 → 真浏览器量机械值（入口计数/禁用词/取值集合/折行 scrollHeight 对比/同行控件等高/侧栏宽度）→ 按评审修订后再复验 → 才动业务代码。
- 理由：本轮用户两次否掉我的产出（先否『1464 测试全绿即交付』，再否『前端明显没动脑子』），逼出这套我原先没有的流程；它含明确的失败-改道：三个子 agent 撞 150 轮上限后按磁盘判进度再切片重派、原型复验推翻我自己设计书里的三条规则。整条链可被另一个 agent 逐步复跑，且规范/门禁行号引用需定稿前逐条复验这一点也是本轮踩出来的。

### 5. ui-redesign-validate-first
- 09-30 20:29 · pending · 置信 0.88 · 「多账号接入与网关调研」
- 摘要：改造前端页面前的「先验证再动手」流水线：并行地基核查（参考程序机制 ×N + 自身实现缺陷审计）→ 多个互斥设计方案各派一个 agent + 一个组件可行性底座 agent → 对抗式设计评审（逐条 BLOCKING 处置表）→ 用项目真实 CSS + 真实 API 形状 fixture 搭 /tmp 可点原型并内置机械量测条 → 真浏览器多档宽度截图取证 → 把设计缺陷回写文档后才改产品代码。含「判据先行」：先写可变异自证的静态门（基线必须为红），再以门为验收目标实施。
- 理由：用户两次否定我的交付（『账号接入和回调都有问题』『前端明显没动脑子』『是否必须我干涉才能做好么』），并明确要求『要充分考虑和验证好方案没问题再动手改造』。本轮该流程可量化复现：地基 4 agent → 设计 3+1 agent → 评审打出 7 条 BLOCKING（其中 5 条指我的引用/门误引）→ 原型 83 断言 0 失败并暴露我自己设计书里 3 条规则漏洞（三态点同形、窄屏折叠列、drawer 死 CSS）→ 定稿 v2.1 → 静态门基线 2/10 红、实施后 12/0 绿。另一个 agent 可按此顺序逐字重跑，且现有 batch-acceptance-merge 只覆盖 commit 批量验收、不涉及设计验证阶段。

### 6. ui-redesign-mutation-gate
- 09-30 21:53 · pending · 置信 0.86 · 「多账号接入与网关调研」
- 摘要：界面改版的「先验证再动手」流水线：地基子agent扇出（规范硬约束/现状审计/参考程序做法/组件可行性）→ 三路竞争设计 + 对抗评审 → /tmp 可点原型（真 base.css + 真 API 形状 fixture + 量测条，真 Chrome 1440/1280/375 双主题）→ 设计书含逐条 BLOCKING 处置表 → 提交式静态门（断言 + 变异自证，每条先证可绿再证可红）→ 真机门 → 三条成对撤证。
- 理由：本轮完整走通且反复纠偏：v1 设计书被评审抓出 7 条 BLOCKING（含我自己写错的 J1/C16 门引用与行号），原型复验又推翻三条我自定的规则（三态点下「全停用」与 0 账号同形、窄屏折叠额度列、断言⑤误判合法圆点）。这套顺序（地基→对撞→原型量测→判据先行→撤证）不是常识，且用户明确质疑「是否必须我干涉才能做好」——把它固化成可被另一个 agent 逐字执行的 playbook，价值最高。

### 7. ui-redesign-validate-before-code
- 09-30 22:07 · pending · 置信 0.86 · 「多账号接入与网关调研」
- 摘要：UI 改版「先验证方案再动代码」流水线：并行派 4 个地基 agent（前端规范硬约束 / 现状交互负担 / 参考程序同类做法 / 可用组件底座）→ 写带 file:line 的设计书 → 独立对抗评审攻击设计 → 用**真 stylesheet + 真 API 形状的 fixture** 在 /tmp 做可点原型（自带测量条：入口计数、禁用词、取值集合、折行、控件等高、栏宽）→ 真浏览器三档宽度截图 → 按原型回写设计书 → 判据先行（门先红）→ 实施 → 变异自证 → 真机验收 + 成对撤证。
- 理由：用户两轮纠偏（『回调都有问题』『明显没动脑子…要充分考虑和验证好方案没问题再动手改造』『是否必须我干涉才能做好』）逼出这条完整流程；它在本会话里真实跑通并产出了可复跑产物（docs/changes/design-accounts-list-v2.md、/tmp/ac-proto、scripts/verify_accounts_ui.mjs 12→13/0、verify_accounts_ui_live.py 151/0）。原型阶段实测抓出设计书自身三条规则漏洞（三态点在『全停用』与 0 账号同形、窄屏折叠额度列反而不可见、断言⑤会误判 rail 合法圆点），证明『先量后改』不是形式。另一个 agent 可照此逐步复跑。

### 8. mgw-console-page-delivery
- 10-01 06:35 · pending · 置信 0.82 · 「新增左侧模板菜单」
- 摘要：Model-Gateway 控制台新增/改动页面（或导航入口）的端到端交付流水线：① 摸底（读 AGENTS.md/specs；被删功能要从 docs/changes/e2e-records 截图与 changelog 考古——git 历史是压扁的）；② 登记三件套（index.html 导航 `<a data-page>` + main.js `PAGES` + `PAGE_META`，J1 门要求侧栏标签与 PAGE_META.title 严格同源）；③ 文案红线（J2：任何扫描源内不得出现「X」页 且 X 不是真实导航项；K4：页面零外链）；④ 先跑基线门（tests/integration/test_int_v2_frontend_gate.py + accounts 门，约 60s）再动手；⑤ 手写清单类功能用 pytest 双向钉死（目录↔文件互查 + 撤证：删条目/幽灵条目两种红法，恢复后比对 SHA）；⑥ 新页面样式优先零新增 CSS（用 .panel-split 类化 gutter；分组式子侧栏在 ≤768 条带需要 `> div {flex:none;white-space:nowrap}` 补定型）；⑦ CDP 真机取证（见配套建议）；⑧ 冻结态复跑（任何测试读过的文件被改=该轮作废，先改完再杀旧跑重跑全量 ~6-7 分钟，README 计数 ±20 窗口）；⑨ 同步 frontend-spec/design-spec/brief/README 双语 + 写 docs/changes/e2e-records 证据文档（含「未实测」清单）。
- 理由：本会话用一整轮证明该流水线可执行且必要：从一句用户指令出发，经历了被删页面重建、门约束摸底、窄屏条带真缺陷修复、CDP 截图中间帧与假绿断言两次翻车、因 base.css 中途修改而杀掉并重跑全量——每步都留下了可直接复制的命令与判据。该项目 UI 迭代频率极高（changelog 数十轮，用户经常直接下 UI 指令），下一个页面改动可由任意 agent 逐字执行，避免重复踩坑与漏同步门/文档。

### 9. cdp-browser-evidence
- 10-01 06:35 · pending · 置信 0.7 · 「新增左侧模板菜单」
- 摘要：headless Chrome + CDP websocket 的本地 Web 界面取证可复用手册：ws 引导（remote-debugging-port + user-data-dir + /json/new）、cmd/js(returnByValue)/wait_for/shot 封装；🔴 截图前必须 settle ≥1s（wait_for 首次轮询在点击后即返回，会截到 .18s 主题过渡的混合帧——正确做法是捕获后按像素直方图复核明暗占比，暗色图应 ≥94% 暗像素）；🔴 颜色断言必须用精确令牌值（深色 body rgb(16,17,20) / 浅色 rgb(247,248,249)；`!= 纯白` 在浅色底恒真=假绿）；同源 iframe 用 contentDocument.title 证明「真的加载了」而非只断言 src 属性；收尾 terminate 进程。
- 理由：本会话两次栽在同一类坑并修复（混合帧截图、假绿断言），且与项目 pitfalls 里 2026-09-05 的既有条目完全同族——说明仅靠记忆条目不足以阻止复发。这些判据（settle 延时、精确色值、像素直方图、iframe title 探针）是经过试错的非显然步骤，写成可执行手册后任何 agent 可一次做对，且该手法跨项目通用（用户多个项目都用 headless Chrome 做界面证据）。

### 10. cdp-headless-evidence
- 10-01 06:53 · pending · 置信 0.8 · 「新增左侧模板菜单」
- 摘要：headless Chrome CDP 截图取证与真机断言的可复用流程：①截图前必须等待渲染稳定（≥1s；wait_for 首次轮询立即返回会截到 .18s 过渡中间帧）②颜色断言必须精确到计算令牌值（'!= 纯白' 在浅色底 #f7f8f9 下恒真 = 假绿）③截图正确性用像素亮度统计验证（缩放到 200x130 计暗/亮像素占比）④整图目检不可靠，必须裁剪关键区域放大核对 ⑤演示页面用 URL 参数（?state=&m= + replaceState）驱动确定性状态与深链回读。
- 理由：本会话两次因点击后 ~50ms 立即抓帧截到'底暗卡亮'与侧栏发灰的混合帧；'背景非白'断言在浅色主题下恒真造成假绿；大型 2880px 截图整图目检多次把暗色误读为浅色（两次），最终以像素统计+裁剪放大才裁决正确。该流程已在 ui_verify_*.py 脚本中固化为 check(name,ok,detail) 汇总模式，任何 agent 可照抄执行。

### 11. model-gateway-ui-template-delivery
- 10-01 06:53 · pending · 置信 0.7 · 「新增左侧模板菜单」
- 摘要：Model-Gateway 前端/模板改动的交付管线（可逐字执行）：①先在 docs/specs+docs/changes 里锚定既有定论与排除项（非目标/需翻案类目绝不画为功能）②实现遵循 frontend-spec 与既有模板范式（骨架选型/api.js 风格/零未定义类名）③目录或清单类改动必须配机械不变量 pytest（如模板目录↔文件双向一致）④每项断言做撤证（注入坏值证明可红）⑤跑前端门(128/128)+变异(184/184)、CDP 真机断言、冻结态全量 pytest ⑥同步证据文档 E2E-*.md + frontend-spec/brief 版本注记 + 项目记忆。
- 理由：本轮两个任务（模板页面入口、T-18 模型路由模板）及此前多轮（Q18–Q24、M6/M7）都在重复同一条管线：规格锚定→实现→目录/测试钉住→门+撤证→CDP 取证→冻结态回归→证据文档。具体坑位可复用：J1 要求侧栏标签===PAGE_META.title、J2 扫『「X」页』引用的必须是真实导航项、README 计数门 ±20、'文案改了断言要同步'（本轮已因此红过一项）。

### 12. repo-process-cleanup
- 10-01 07:16 · pending · 置信 0.7 · 「清理项目无用文件」
- 摘要：仓库过程垃圾清理 playbook：先盘点（git status 未跟踪 + git ls-files 对照）、grep 逐一验证引用再分类（一次性诊断脚本/探针输出=删，运行时目录=补 .gitignore，现役验收门与测试=保留）、对模糊类目（证据台账）先用 AskUserQuestion 征询，删除用 git rm 留痕，收尾跑金丝雀测试 + pytest --collect-only 验证清理未破坏测试收集。
- 理由：会话中出现可复用的多步流程与一次工具失败换道：git rm 遭遇 .git/index.lock 失败，通过 ps 查无 git 进程 + 锁文件时间戳（9 天前、0 字节）判定为陈旧锁后安全移除再重试——本项目存在多会话共用工作树的情形，陈旧锁会复发，该「先查活性与时间戳、不盲删」的判定步骤值得固化；此外「tests/ 全绿≠无垃圾、scripts/fixtures 被 verify 门引用不可删」等引用核验结论也是可复制的执行顺序。未命中任何现有 skill（无架构可视化/站点类技能适用）。

### 13. repo-restructure-coding-zone
- 10-01 07:49 · pending · 置信 0.78 · 「清理项目无用文件」
- 摘要：把既有仓库对齐 codex-coding 式「coding/ 源码唯一区 + bianyiandhuanjing/ 运行与验收环境」结构并保持机械门全绿的迁移 playbook
- 理由：本次会话从研读参考工程到落地迁移形成了一条可复现的多步流水线：核对运行中服务与路径锚点（PROJECT_ROOT=包父级、editable venv、data/ 随包）→ git mv 跟踪文件 + mv 未跟踪 → 就地重建 venv（system python3 是 3.9 的坑，须用 ~/.local/bin/python3.12）→ 批量修正门脚本 ROOT 语义（parents[1]→parents[2] + coding/ 前缀 + copy: 键同步）→ ship-gate 全量回归直到 GREEN。其中有三处真实试错：python3.9 建出的 venv 不可用需重建；editable venv 指向旧路径必须删除重建；门脚本内硬编码的 copy:model_gateway 键漏改前缀导致变异自证在 join(work, rel) 处以 ERR_INVALID_ARG_TYPE 崩溃——这类错误形态（基线全绿但变异循环 undefined 崩溃 = 某硬编码键未同步）是再次做同类迁移时必然复现的坑。此外 ship-gate.sh 机械门本身是一个可逐字复用的验收产物。

### 14. mg-ui-change-verify
- 10-01 15:21 · pending · 置信 0.75 · 「调整模型按钮位置」
- 摘要：Model-Gateway 前端微调（按钮/导航/文案）闭环：先 grep 门禁与测试是否钉住待改字符串（bianyiandhuanjing/scripts/*.mjs + tests）→ 改 web/static（index.html 导航、js/main.js PAGE_META、pages/*.js）→ 静态资源 no-store 免重启 :8300 → 用 ego-browser 打开 #/ 页面以 page.evaluate + getBoundingClientRect DOM 几何断言取证（CDP 截图超时不要反复重试，DOM 读数本身就是证据）→ 回报格式 = 文件:行 + 断言读数表 + 明确「未验证」项。附 ego-browser 会话陷阱：需先 listTaskSpaces 取数字 id 再 taskSpace(id)，已 finish 的空间不可恢复需新开；选择器多匹配会报歧义，用更具体选择器或 evaluate 内点击。
- 理由：本会话连续 3 轮微调（添加模型按钮移位、两次导航改名）走的是同一条可复现流程，且出现真实试错：Page.captureScreenshot 多次超时后改用 DOM 几何断言作为证据并成立；改名轮先做了「门禁是否钉住字符串」的 grep 才动手。这些步骤 ego-browser SKILL.md 未覆盖（它只讲截图路径，未给超时降级链），值得沉淀为项目锚定的验证技能。

### 15. model-gateway-gate-sync
- 10-01 15:50 · pending · 置信 0.7 · 「调整模型按钮位置」
- 摘要：Model-Gateway 门禁同步流水线（文案/页名/计数改动后逐字可复跑）：① 跑 `cd coding && .venv/bin/python ../bianyiandhuanjing/scripts/ui_verify_v2_visible.py [--mutation]`——它自起实例并写按次唯一的新鲜 fixture，严禁拿 /tmp 旧 fixture 直接喂 verify_v2_frontend.mjs（否则 K10 假红）；② 按 J2 违规清单清全站旧页名（前端文案 + .py 页名常量/注释 + templates），再同步 verify_v2_frontend.mjs 的断言串与变异 from 锚点，循环 --mutation 直到「可红 N/N + 基线 128/128 全绿」（输出会精确报 '锚点命中 0 次' 的过期条目）；③ 账号页另跑 verify_accounts_ui.mjs（含 --mutation）；④ README 测试数 = 实测 collected，同步 badge tests-N%2FN 与双语正文（合法窗口 [collected-20, collected]）；⑤ 隔离实例 = 复制 coding/data → 改 gateway.port → MG_CONFIG=... .venv/bin/python -m model_gateway.main。
- 理由：本会话在多轮改动中反复执行此流水线并付了学费：先用陈旧 fixture 跑门得到 K10 假红、页名改版后 13 个变异锚点与多处断言串过期、README 计数被判据钉住报红、隔离实例的起法需端口改写+MG_CONFIG。步骤固定且全部有精确命令与判读方法，另一代理可逐字复跑；项目已有同类工程锚定 skill（batch-acceptance-merge）先例。

### 16. isolated-instance-e2e
- 10-01 16:06 · pending · 置信 0.72 · 「调整模型按钮位置」
- 摘要：本地服务隔离实例端到端验证 playbook：复制线上数据目录到 /tmp 并只改副本端口→env（如 MG_CONFIG=…）指向副本启动→重启时按端口取 PID 杀进程（lsof -nP -iTCP:<port> -sTCP:LISTEN），禁用 pkill -f（经 env VAR=… 传的配置不在命令行，匹配不到→旧进程占端口、旧代码静默冒充新代码）→配置写入后存在热重载滞后，隔一拍重读再判定，勿把时差当失败（物化/发布类结论至少复读一次）。
- 理由：本会话 pkill -f 未匹配 env 前缀进程导致旧实例冒充新代码、白跑一轮并误导出『物化未生效』的假结论；随后又两次把热重载时差误判为资源/模型未发布——工具链经验完整且可逐步复跑。

### 17. model-gateway-delivery-round
- 10-01 16:46 · pending · 置信 0.85 · 「调整模型按钮位置」
- 摘要：Model-Gateway 项目一轮交付的可复跑流水线：① 侦察（AGENTS.md/.cursor/memory/docs/specs + git status）；② 冻结 API 契约、向用户复述理解（'我已准确理解'）后再动码；③ 并行子代理 = 文件不重叠 + 各自'禁改清单' + 证据要求（pytest 输出行/file:line），前端与后端按冻结契约同轮并行；④ 集成验收：node scripts/verify_accounts_ui.mjs [--mutation]、ui_verify_v2_visible.py（现场生成鲜 fixture 再跑 verify_v2_frontend.mjs，--mutation 需 184/184）——文案改名会使变异 from 锚点批量过期，按报错清单批量改锚点后迭代至全绿；⑤ 隔离实例真机 E2E：cp coding/data → 改端口 → MG_CONFIG 启动（杀进程用 lsof 取 PID 再 kill，'env VAR=…' 不在命令行，pkill -f 匹配不到）；⑥ 收尾：README 双语计数同步（badge+正文，钉数判据 ±20 容差）、docs/changes/e2e-records 证据文档、AGENTS.md 条目、记忆更新、git 提交；⑦ 硬约束：动真实凭据/真实付款/重启 :8300 前先征得用户同意，未实测项如实登记。
- 理由：本会话 40+ 轮实际执行并多次踩坑纠错：pkill 因 env 变量不在命令行而失败只能按 PID 杀、静态门变异锚点随页名/文案改名 13 处批量过期需迭代修复、README 计数钉数随并行会话漂移、镜像验证实例的 MG_CONFIG 隔离配方。这些是可复跑的工具链级操作序列，记忆（简规则）装不下细节，适合按需加载的 skill。

### 18. ui-entry-discoverability
- 10-01 16:46 · pending · 置信 0.7 · 「调整模型按钮位置」
- 摘要：UI 功能交付前必做'找得到'验证：① 入口命名改用用户自己的词汇（用户口头说'购买账号'，界面就别只挂内部叫法'一元账号'）；② 从页面默认落点走完整点击路径——产品级/条件级入口在默认状态下可能完全不显示（本案例：入口只在左栏选中 ZCode 产品后才出现在卡头），交付回复必须写出'页面→左栏选什么→卡头哪个按钮'的完整导航；③ 验证要在真实运行实例上按用户路径实走（DOM 断言），不要只在实现视角截图。
- 理由：最后一轮用户直接问'购买账号和导入账号的功能入口在哪儿呀？你到底完没完成'——功能已上线且验证通过，但①按钮文案是内部叫法（一元账号）②入口只在选中 zcode 产品后可见，默认落点看不到，导致用户找不到并质疑完成度。命名词汇不匹配 + 默认态不可见是 UI 交付的两个可复用检查项，值得沉淀为独立 skill。

### 19. model-gateway-live-delivery
- 10-01 17:04 · pending · 置信 0.85 · 「归档-网关添加主流模型」
- 摘要：把 Model-Gateway 改动真正落地到运行中的 :8300 并附实证的固定链路：①代码/目录改动=重启生效（POST /admin/api/system/restart，execv，先征得用户同意；仅配置改动走 PUT /admin/api/config 热生效）；②配置写路径=GET（脱敏）→改→PUT 全量（服务端自动还原密钥，写后用 ?reveal=1 只验形态不回显）；③接入模型=PUT config 增系统模型；批量映射=POST /admin/api/accounts/mappings {product, items:[{model,target}]}（target 须为现有系统模型或枚举池条目名；落点=该产品全部启用账号的物化资源）；④验证链=/admin/api/enums → 页面 DOM（同一 URL 导航不会重载 SPA，必须 location.reload()；厂商卡在左侧栏末尾需滚动）→ /v1/models（Bearer 取 reveal=1 的 access_token，不出屏）→ 真实小调用（小 max_tokens）为最强证据；⑤提交=只提交自己改的文件，先 git log <base>..HEAD + git show <新提交> --name-only 核对并行会话是否触碰同文件，推送命令交用户执行。
- 理由：用户两次纠正交付标准：『看不到数据』（目录条目≠已接入可见）与『需要重启你就重启，不要反复聊』；最终收敛出一套已实测走通的免试错命令链路（重启端点、脱敏回写、映射端点、DOM 重载陷阱、/v1/models 验证、文件粒度提交与冲突检查），正是典型的 2+ 步可复跑流程。

### 20. mgw-ui-gate-sync
- 10-01 20:12 · pending · 置信 0.75 · 「接入账号资源页面调整」
- 摘要：Model-Gateway 前端页面改版的三件套同步门改法：改页面 JS 时必须同轮改静态门（verify_*.mjs 判据+变异锚点）、真机门（verify_*_live.py 的 SEED/READ/ck 断言）与 README 测试计数，并按既定顺序收敛红项
- 理由：本轮产生可复现的多步流程：①改 coding/model_gateway/web/static/js/pages/*.js 后，静态门会因 DOM 契约钉死而红（如 .exp 列、四值额度词表、navTitle、卡头按钮数），须逐条重写判据并重定锚变异（锚点过期=假通过，脚本报「锚点命中 0 次」即信号）；②fixture（bianyiandhuanjing/scripts/fixtures/*.json）需补新字段才能让新判据有对象（如 runtime.quota.plan/items）；③真机门按 SEED→READ 收集 JS→ck 断言三处同步改，RED 项按「先判据后变异」收敛；④pytest 全量后把计数同步进 coding/README.md 与 README.zh-CN.md（守卫允许 ±20 漂移、不许虚报）。过程中踩到三个可泛化坑：modal() 是追加不是替换导致弹窗套弹窗（用户红线：.modal-mask ∈ {0,1}）、ego-browser 驱动级抖动（page.$ is not a function / page label not found / CD

### 21. unreproducible-gate-red-triage
- 10-01 21:05 · pending · 置信 0.72 · 「商品和我的订单 在弹窗中改成两个tab，具体参考ZCode Panel 显示的数据和形式给我做到…」
- 摘要：静态扫描门报红但手工复现不出时的归因流程：① 先怀疑详情串是格式化产物（如 `${name}→「${page}」页`），命中的可能不是字面那条正则，去读判据函数里**全部**分支（本例第三条 cue 动词+「X」不要求“页”字才是真凶）；② 用花括号计数从门源码里原样抽出它的 helper（stripComments）在 Node 里 eval 复现，而不是自己重写一份近似实现；③ 共享/被并行会话改写的树先把仓库冻结到临时目录再跑门——副本必须放在与门脚本相同的相对位置（<tmp>/bianyiandhuanjing/scripts/），因为 ROOT 由脚本自身路径推导；④ 需要命中上下文时在同目录做门的一份带调试输出的临时副本（打印 m[0]+idx+上下文），用完即删；⑤ 用 git show HEAD:<file> 跑同一套抽取判断是既有缺陷还是本轮引入，据此决定只规避文案、不动门判据面。
- 理由：本会话在这一步上真实消耗了六轮试错：先误判为并行会话中间态、再冻结树证明红仍在、最后才定位到门的第三条正则 + stripComments 失步（HEAD 既有）。全程包含方法切换（改正则口径→抽函数复现→冻结树→打补丁副本），且结论可复用为通用排障程序；现有 batch-acceptance-merge 明确把「报红归因」推给另一条 Skill，本仓库这条静态文案扫描门的归因细节不在其中。

### 22. mgw-admin-ui-gate-round
- 10-01 21:41 · pending · 置信 0.86 · 「接入账号资源页面调整」
- 摘要：Model-Gateway 管理端页面改版一轮的完整交付流水线（含两道验收门的契约同步）：① 开工前 git status/diff 查并行会话未提交改动 → ② 并行派 Explore 子代理取证（前端现状 / 后端语义 / 参考实现）→ ③ 实施（源码在 coding/，冻结类型加字段一律带默认值放末尾）→ ④ 同步门契约：静态 vm 门 bianyiandhuanjing/scripts/verify_accounts_ui.mjs（改 DOM 结构必须重锚 MUTATIONS 的 from: 源码行，否则 applyEdit 抛「锚点命中 0 次」；新行为必须补判据 + 一条可红变异，禁止留 true 占位死判据）与真机门 verify_accounts_ui_live.py（自带独立实例 :8400-8499 + 假上游，绝不碰 :8300；行 td 列索引/SEED/READ 三处要一起改）→ ⑤ 判据「累计测量」陷阱：计数型判据（请求日志、一次性 DOM 探针）必须在新段落动作前重新取基线/重新打标，否则把前段合法流量算成本段假红 → ⑥ 复跑顺序：pytest -q（coding/）→ 静态门 → 静态门 --mutation → 真机门 → ⑦ README 双语计数同步（badge + 正文 + alt 文本三处，守卫只许 ≤ 真实且 ±20）→ ⑧ :8300 活实例只读 DOM 复验（前端刷新即生效；后端改动须先获用户批准才重启）→ ⑨ 写 docs/changes/e2e-records/ 台账，数字一律抄自命令输出行。
- 理由：本轮出现多次方向反转与踩坑纠偏：modal() 是追加不是替换导致二级弹窗叠层（后被用户红线废除）、续期归属层级被用户翻案（弹窗→行内）、真机门 B12/B12b 因累计测量被自己新增段落打假红、credexp 漏认 qoder/cline 的 expire_time 键（靠真实盘上文件核验才发现）。整条链路含固定脚本路径、端口区间、判据锚点与 README 计数纪律，是另一个 agent 可逐字复跑的多步流水线，且当前无任何 Skill 覆盖（batch-acceptance-merge 仅适用 codex-coding 工程）。

### 23. port-account-plan-quota-display
- 10-01 21:41 · pending · 置信 0.7 · 「接入账号资源页面调整」
- 摘要：从参考工具（DSH 插件 / zcode-switch / ZCode-Panel）忠实移植「账号 → 套餐识别 + 套餐余粮」查询与展示的 playbook：① 先读参考侧字段路径再动手（buddy data.Response.Data.Accounts[] 双层嵌套、CycleCapacityRemain 周期口径 ≠ CapacityRemain 终身口径、DeductionEndTime 毫秒才是作废判据；trae expire_time 秒级须×1000；qoder userQuota+addOnQuota+dedicatedResourcePackages 三层；lobsterai 用 profile-summary 而非 /api/user/quota；raccoon 四积分池；loomy 永久+每日两池；zcode unit_type=token 走离线日志通道）；② 归一化成 plan + items[{name,unit,remaining,total,used,active,expires_at}]，取不到的键写 None/空串不编造；③ 展示公式：套餐徽章 → 粗体总额 + 量纲（token 用 K/M 两位小数）→ 分桶附属行三选一（长期/每日、长期/临时按到期窗口 15 天、N 个资源包有效）→「另有 N 已失效」→ 查于时间 → 逐包明细进 tooltip；④ 铁律：查不到与余额 0 严格分型、失效包不计入总额、负值 clamp 0、多包相加两位小数、时间单位各产品不同必须归一化；⑤ 交付前用真实盘上凭据/快照文件跑一遍解析器做覆盖率核验（只输出解析结果，绝不回显令牌）。
- 理由：用户明确痛斥此前多次调研仍把余量列做成粗摘要，并给出「好好调研参考实现怎么查询和显示」的方法要求；本轮沉淀出的字段路径表 + 归一化契约 + 展示公式 + 覆盖率核验步骤是可被另一个 agent 在同类产品接入任务中逐条复用的多步流程，且踩坑点（周期 vs 终身口径、秒/毫秒、未知当 0）均为真实纠偏所得。

### 24. mgw-frontend-gate-rework
- 10-01 23:15 · pending · 置信 0.82 · 「接入账号资源页面调整」
- 摘要：Model-Gateway 前端改版时同步重写两道验收门的流水线：静态门 verify_accounts_ui.mjs（判据 + 变异自证：每条 V 判据必须配一条可红变异、过期锚点要重定锚不许删条目）+ 真机门 verify_accounts_ui_live.py（改 READ 采集器列索引/新增观测量 → 改种子 SEED → 改 ck 断言），并把「累计型测量」（请求日志、一次性 DOM 探针）改为动作前一刻取基线，避免前段合法流量造成假红；改完先 node --check 内嵌 JS 再跑门。
- 理由：本轮多次踩到同一套机制：变异锚点因改版命中 0 次报 BAD、新增判据没配变异被门自己判失败、B12/B12b 因累计请求日志与 rail 探针被前段（映射弹窗/批量续期）合法重取冲掉而假红，都是靠固定步骤定位并修复的；这套步骤含具体文件、命令与判据口径，另一个 agent 可照跑，属可复放流水线而非一次性经验。

### 25. live-cron-scheduled-leg-verification
- 10-01 23:15 · pending · 置信 0.78 · 「接入账号资源页面调整」
- 摘要：在真实实例上验证「定时腿/凭据轮换」类功能的观测法：重启后先取基线（相关文件的 mtime + 台账 JSON 键），等 ≥2 个 cron 周期再复查——文件 mtime 每轮都变=空转（典型根因：续期窗口大于令牌寿命），终态错误每轮重试=缺终止标记；配合界面 DOM 读数核对文案是否如实（已过期不得写“将自动续期”）。含抓出的两类缺陷判据与护栏写法（冷却常量 + runtime 台账键、读-改-写只动一个键）。
- 理由：假上游门全绿的情况下，只有真凭据 + 真 cron 才暴露出 cline 逐轮空转轮换与 raccoon 终态无限重试两个缺陷；定位手段是纯观测式（mtime 基线→跨轮复查→DOM 文案核对），且中途因误判“余额腿挂了”走过弯路（实为报告节奏与腿耗时），这套纠偏后的流程可被其他 agent 逐步复放。

### 26. gate-embedded-js-selfcheck-and-criterion-advance
- 10-02 15:10 · evolving · 置信 0.84 · 「页面UI调整」
- 摘要：改验收门（Python 内嵌 JS / vm 静态门）后的三步自检与判据推进流程：① 按花括号配平从 .py 里切出每段 `await section(...)` 与 `const READ` 内嵌 JS，逐段 `node --check`（本轮两次抓到我自己的字符串 bug：相邻字面量漏 `+`、字符串里嵌套双引号）；② 设计变更后必须推进钉旧设计的判据并把理由写进判据（V10/B14/D4b/V13 四次同形操作），同时补一条能打死新判据的变异；③ 加代码前先 grep 变异锚点表，避免新写的行让既有锚点命中 2 次（本轮真实踩到 V4 锚点失效）。
- 理由：同一套动作在本会话出现四次且每次都有失败-纠正循环（门语法崩、锚点过期、判据空过），是另一个 agent 可逐字复跑的多步流程；现有 memory 只有零散一句话，没有可执行的提取脚本与推进判据的操作顺序。

### 27. multi-role-product-verdict-research
- 10-02 15:10 · pending · 置信 0.88 · 「API调用条件核实」
- 摘要：多角色交叉验证调研流水线：预定义判定口径（如 D0-D4 运行期依赖 / C0-C3 多账号并行）→ 按批次为每个对象派「代码分析专家 / 研发工程师 / 通用权威」三个独立角色 + 一路真机实测，统一输出契约（同一张逐对象判定表 + file:line 证据 + 否证条件 + 置信度）→ 主 agent 逐格比对、分歧亲自复研、一致才交付。含关键手法：利用 `ps` 天然实验（目标桌面端未运行即为对照）、强制 (a)自家门自拦/(b)上游拒绝/(c)成功 三态归因、遇「测不了」改建隔离临时实例（如 MG_CONFIG=/tmp/... 端口 8452 + 凭据副本）而非写未验证、必做撤证（能红）与负对照、只读型 Explore agent 无法落盘时由主 agent 代为写证据文件。
- 理由：用户明确规定了验收方式（每产品三角色 + 交叉验证不等于叠加 + 分歧由主 agent 复研 + 一致才交付），本轮完整跑通且踩中多个非显然环节：Explore 只读不能写报告、第一轮 9 格因自家映射缺口而「不可测」被误判、须靠 ps 天然实验与临时实例才拿到推理级证据。这是另一个 agent 可逐字复跑的多步流水线，且用户随后把同一标准扩展到「开发和改动」，属长期复用规程。

### 28. mgw-change-delivery-round
- 10-02 20:25 · evolving · 置信 0.85 · 「页面UI调整」
- 摘要：Model-Gateway 单轮「改动→判据→撤证→真机证据→归案」交付环的可复跑 playbook：① 认领改动面并检查并行会话（ps/mtime/md5，禁用 cp 整文件恢复，只按行 inverse edit）；② 实现时守硬约束（共享判据单一事实源、明细不新增 <tr>、颜色走令牌、单层弹窗）；③ 判据三层（静态 vm 门 verify_accounts_ui.mjs / 真机门 verify_accounts_ui_live.py / pytest），改旧设计时判据「随设计推进」并在判据文案里写明理由，新增变异前先 grep 变异锚点表防唯一锚被撞；④ 每改一处必须做双向撤证（退回改动→判据必红；再原语复原）；⑤ 真机证据用 CDP 只读探针 + 截图 + 几何/像素读数，临时实例用 MG_CONFIG 指向 /tmp（数据根随配置文件父目录，仓库 data/ 零写入），跑门前把浏览器窗口归 normal、并用 md5 括住被测源码；⑥ 记账：台账 + spec 归案（frontend-spec/design-spec 升版）+ AGENTS 状态链 + memory，且所有数字必须抄自运行器原始输出；⑦ 结尾显式列「未验证」清单。
- 理由：本会话连续十余轮都在同一套交付要求下被反复矫正（用户多次要求「充分检查核验」「动点脑子」、指出我把两类资源混在一页、把标题删成贴线、把旧判据留成假绿），而每次真正收敛靠的都是同一串动作：静态门+真机门+撤证+活实例读数+规范归案+台账。期间还踩出多条可复用纪律：门内嵌 JS 必须先逐段 node --check（我两次写出 Python 式相邻字符串拼接/嵌套双引号，靠此机械抓回）、长时门跑必须用 md5 括住源码否则读数不可归因、禁止用 cp 快照恢复共享树文件（我覆盖了并行会话的新版）。这些是可被下一个 agent 逐字执行的流水线，写成 skill 比散在 memory 里更可执行。

### 29. serial-mutation-falsifiability-harness
- 10-02 21:46 · pending · 置信 0.88 · 「API调用条件核实」
- 摘要：沉淀「串行变异自证（撤证）流水线」技能：/tmp 单文件脚本模板（锚点必须全仓唯一 → 施加变异 → 清 __pycache__ → 定向 pytest 串行 → md5 校验复原 → 全部撤销后复绿自检），并把本轮反复踩到的三条硬纪律写成可执行步骤：绝不与全量 pytest/门禁并发跑、等长替换必须靠清字节码或改长度来避免假红/假绿、台账里的撤证行必须如实写明每次实跑的文件集范围（禁止把「2 文件红」写成「七文件」）。
- 理由：本轮为 M7~M14 八条判据逐一做「改坏必红」证明，过程中踩了三个只有实操才知道的坑：① 变异脚本与全量 pytest 并发跑导致 3 条与代码无关的红；② `max(`→`min(` 等长替换 + 秒级复原使 .pyc 的 (mtime,size) 校验位仍成立，出现「复原了还红」；③ 复绿自检表达式自身写错（`t.split` 用在 list 上）导致两轮虚报范围。脚本骨架、锚点唯一性、md5 复原断言、串行独占、以及「撤证范围必须与实跑文件集一致」的记账纪律，是另一个 agent 可以逐字复跑的多步流水线；目前只有 .cursor/memory/pitfalls 的散文条目，没有可执行 playbook，也没有覆盖「判据红证打不响时随设计推进而不是放宽阈值」（本轮 A-1 撤接线腿实测 6ms<500ms 的处置）。

### 30. serial-mutation-falsification
- 10-03 01:32 · pending · 置信 0.88 · 「API调用条件核实」
- 摘要：串行变异自证流水线：锚点唯一性断言 → 一行"掏空修复"变异 → 清 __pycache__ → 只跑定向测试并抄它自己的输出行 → md5 校验复原 → 复绿自检；并规定"撤掉修复仍全绿 = 判据缺陷"必须当场改写判据后复跑（本轮 M21 假绿就是这么抓到并修好的）。
- 理由：本会话反复执行且踩过三类坑：等长替换撞上 .pyc 的 (mtime,size) 双条件、变异与全量 pytest 并发制造幽灵红、以及新写的心跳判据第一版假绿（计时起点写在任务体内 / gather 之后取值）。这是 2 步以上、可被其他 agent 逐字复跑的固定流程，还包含一次真实的方向纠正。

### 31. ui-gate-red-triage
- 10-03 10:27 · evolving · 置信 0.85 · 「页面UI调整」
- 摘要：UI 改版后把门判据跑红时的四分类归因与修复流水线：逐条读门自己那行实测值，把每条红归为「实现缺陷 / 判据读点搬家 / 判据空转（fixture 到不了那个分支）/ 判据假红（扫描面没跟上自己的改动）」，再按对应处方修；含具体命令：`node verify_accounts_ui.mjs [--mutation]`（变异锚必须逐字唯一命中，锚文本少一颗反引号就命中 0 次报 BAD）、`nohup python -u verify_accounts_ui_live.py --skip-legs > /tmp/q-liveN.log` 后用 `sed 's/\x1b\[[0-9;]*m//g' | grep -aE "合计：|^  ✗"` 取终局行、改门内嵌 JS 后先跑抽取式 `node --check`、浏览器段整片 FATAL（`page label not found: pN`）时先用最小探针（newPage+goto+evaluate(title)）确认浏览器可用再重跑，且不得中途 kill 在跑的门（尸体会毒化下一轮标签页）。
- 理由：本轮出现三次以上同类返工与自我纠偏（D4b 长期空转、V15 把正则打在拼接串上结构性不可能绿、V17 因把 title 搬到格根而假红、三条 D4/V13/V14 因读点搬家恒空），每次都靠同一套「读实测值→四分类→修→重定锚→复跑取门自己那行」的流程收敛；含固定命令与输出格式，另一个 agent 可照做，且这些坑在本项目会反复出现。

### 32. ui-defect-to-gate-pipeline
- 10-03 11:08 · evolving · 置信 0.82 · 「页面UI调整」
- 摘要：把用户实拍的前端呈现缺陷变成「量出来的判据」的固定流程：先用 ego-browser DOM 探针量画出来的几何与计算样式（getBoundingClientRect().left、scrollWidth-clientWidth、computed fontWeight/backgroundColor、以及属性类判据的 title/aria 本身），改结构后把同一把尺搬进静态门 verify_accounts_ui.mjs 与真机门 verify_accounts_ui_live.py，并给判据补一个真能触发它的 fixture 行，最后成对撤证（临时改回坏形态复测非零 → 恢复并 md5 逐字节校验）。
- 理由：本轮用户在同一处界面连三次实拍打回（额度格信息选择 → 进度条错落/灰轨道 → 字重参差），每一次我的第一版修法都不完整：定宽三列钉住了条却把数字挤到裁字（只验对齐没验溢出）、证据条挂内部 span 让三条悬停判据空转、qwarnw 整格加粗造成字重混乱。这些教训的共同解法是一条可复跑的工具链（探针 → 判据入门 → 补对象 → 成对撤证），涉及具体命令与读点，属于按需加载的 playbook；现有 memory 只留了结论性规则，没有这条链。

### 33. oil-ui-pro
- 10-03 13:10 · pending · 置信 0.88 · 「页面UI调整」
- 摘要：补一节「先分清是哪一个 ui-pro」：用户说「用这个 skill」并指向 ~/Desktop/ui-pro（或说本地/离线）时，直接读该目录的 SKILL.md 走纯离线流程，不进本 shell 的付费远端编译链；并记录两处实测替代——build_explorer.py 需 python3.12（本机 python3 是 3.9.6 会直接报「需要 Python 3.10 或更新版本」），附件 upload 返回 403「暂无权限访问」重试一次仍失败时，按契约停止并把订单/失败原样报给用户，不得改读文件内容冒充上传。
- 理由：本轮出现明确的技能错配：用户要的是他本机的离线 ui-pro（/Users/w/Desktop/ui-pro，name: ui-pro，零网络），而被名字诱导加载的是本付费远端 shell，一路走到 ¥19.90 支付待确认才被用户纠正「不是那个付费skill啊，是我纯本地的这个skill」——技能名与描述相对用户的实际用法过宽/易混。同时随包生成器与上传通道各失败一次并需要替代命令，这些都不是 SKILL.md 现有内容覆盖的。

### 34. frontend-ui-change-gate-loop
- 10-03 17:30 · pending · 置信 0.86 · 「页面UI调整」
- 摘要：Model-Gateway（codex-coding）前端改版验收闭环的可照抄命令序列：改完 JS/CSS → 按模块做语法检查（`cp x.js /tmp/x.mjs && node --check /tmp/x.mjs`，因为 `node --check x.js` 对 ES 模块假绿）→ 生成载荷 `coding/.venv/bin/python bianyiandhuanjing/scripts/make_overview_payload.py /tmp` → `node bianyiandhuanjing/scripts/verify_v2_frontend.mjs "$OV"` → `node bianyiandhuanjing/scripts/verify_accounts_ui.mjs` → 页面真机 runner（如 `verify_settings_layout.py`）；每一步都用 md5 跑前=跑后自证树未被并行会话改动（TREE_QUIET），新判据必须插坏例子撤证到「恰红该条」再按 md5 复原；无 OS 窗口时画面证据走 `Page.printToPDF` + `qlmanage -t -s 1500` 转 PNG，`PageBudgetError (8/8)` 用同 space 的 `task.page('pN').close()` 清标签页；最后归案四件套 frontend-spec / design-spec / AGENTS.md 链条 / 设计说明台账 + pitfalls。
- 理由：本会话把这条链路完整跑了三遍（说明集中卡尾→分组、板块头收成单行），过程中出现多处需要试错才找到的替代命令：`verify_v2_frontend.mjs` 裸调会打印用法并 exit 2（必须吃 overview-json）、系统 python3 无 ssl 且缺 pytest（必须用 `coding/.venv/bin/python`）、`node --check` 假绿掩盖了整页崩溃、浏览器标签页配额耗尽导致「浏览器没交回读数」被误判成页面缺陷。这些都是一套固定的工具链与输出格式，另一个 agent 可照抄执行，且明显超出任何现有 skill 的范围。

### 35. mgw-ui-change-verify-loop
- 10-03 17:46 · pending · 置信 0.88 · 「页面UI调整」
- 摘要：沉淀本轮反复使用的「改前先量、改后要证」UI 改动验证流水线：① 开工先取 base.css/页面 JS 的 md5 并隔 20s 复测，确认共享树是否被并行会话在改；② 改完必须按 ES 模块做语法检查（cp x.js /tmp/x.mjs && node --check /tmp/x.mjs），因为 node --check 对 .js 按 CommonJS 解析会假绿；③ 门调用口径：coding/.venv/bin/python bianyiandhuanjing/scripts/make_overview_payload.py /tmp 生成载荷 → node verify_v2_frontend.mjs <json> → verify_accounts_ui.mjs（含 --mutation 自证）→ 真机 runner 带 md5 前后守卫；④ 新增几何判据必须成对（对齐 + 不溢出）且用 document.createRange 量**文本**边缘而非盒子；⑤ 每条新判据配一次撤证（插入坏形状→恰该条红→复原→md5 与基线逐字节一致）；⑥ 画面证据走 Page.printToPDF(1440×900)+qlmanage -t 转 PNG（本机 Ego Lite 无 OS 窗口，captureScreenshot 必超时），报 PageBudgetError(8/8) 时先用同 space 的 task.page('pN').close() 清残留标签页。
- 理由：本轮出现多次工具失败与替代：node --check 假绿导致整页「界面脚本未能加载」、PageBudgetError 使 runner 无读数、captureScreenshot 超时改走 printToPDF；且这套 6 步流程在五次连续改动中被逐字重复执行，含具体命令与文件路径，另一个 agent 可原样复跑。现有 oil-ui-pro 只讲设计判断，不覆盖本仓验证脚手架。

### 36. headless-ui-geometry-proof
- 10-03 17:54 · pending · 置信 0.86 · 「页面UI调整」
- 摘要：本机 0 宽浏览器下的 UI 改版取证与判据闭环 playbook：用 `Emulation.setDeviceMetricsOverride` 造真视口量几何 → `Page.printToPDF` + `qlmanage -t` 转 PNG 再读图（绕开 `Page.captureScreenshot` 必超时）→ 布局判据三条腿成对（对齐 / 不溢出 / 配对距离，且必须量 Range 文本边缘而非盒子）→ 每条新判据配一次撤证（插坏例子看它红、逐条 md5 复原）→ 门跑前后 md5 守卫（跨编辑即作废）→ 浏览器配额被上一轮泄漏占满时用同 space 的 `task.page('pN').close()` 清理 → ES 模块改完必须 `cp x.js /tmp/x.mjs && node --check`（`node --check x.js` 按 CommonJS 解析会假绿）。
- 理由：本轮多次因工具/环境失败而换路（截图超时→PDF、`node --check` 假绿、PageBudgetError 8/8、BSD grep 的 `\|` 静默零命中、量盒子量出 `间隙0`），每一次都是先做错再纠正才收敛；这些步骤有确定命令与确定顺序，另一个 agent 可照着复跑，而现有 ego-browser 技能只讲开浏览器与操作页面，不含这套几何量测 + 判据可证伪 + 树冻结纪律。

### 37. mgw-ui-verification-ladder
- 10-03 20:34 · pending · 置信 0.86 · 「页面UI调整」
- 摘要：Model-Gateway 管理端一轮 UI 改动的完整验收阶梯：改前 md5 快照 → ES 模块 `cp x.js /tmp/x.mjs && node --check` → 从 Python 门文件里抽出内嵌 JS（`JS = r'''` 到下一个 `'''`）再 `node --check` → 静态门 + `--mutation`（锚点须恰命中 1 次、必须落在门真正复制的那个文件、红消息要能按文字归因、负向判据先剥注释）→ 只读几何探针（`Emulation.setDeviceMetricsOverride` 定视口，画面走 `Page.printToPDF` + `qlmanage -t`）→ `ship-gate.sh --gates` 终局数并按来源归因 README 漂数。
- 理由：本轮这套流程被逐字执行了四遍（额度格、脚钮两态、结果浮层各一遍），且每次都是靠其中某一步抓出我自己的缺陷：内嵌 JS 抽出检查抓到被我吞掉的注释开行与丢掉的右括号；变异自证抓到锚点指错文件的 BAD；md5 前后对照抓到我在门下改文件又当场回滚。用户还两次实拍纠正方向（先做完再带实测数问口径）。这是另一个 agent 可以原样复跑的多步管线，散落在多条 memory 里但没有一份可执行的 playbook。

### 38. model-gateway-vendor-catalog-onboarding
- 10-04 06:52 · pending · 置信 0.9 · 「归档-网关添加主流模型」
- 摘要：Model-Gateway 新增厂商/模型入内置目录的完整交付流水线：官方取证 → 多子 agent 逐格交叉验证 → 写 BUILTIN_ENTRIES + 来源注释 + 测试钉点 → 厂商图标双向在册（VENDOR_ICON + 官方 128px 资产，缺则判红/退回首字母）→ 定向测试与 ship-gate/静态门 → :8300 重启 + PUT 系统模型 + 按产品目录建映射 + /v1/models + 真实调用矩阵（流式、首条 system、max_tokens≥2048）→ 岛式快照 README 计数 → 按文件粒度提交。
- 理由：同一流程在本会话内跑了两轮（Anthropic/OpenAI，再混元/MiniMax/Gemini），第二轮用户明令「写入前必须多子 agent 交叉验证」；过程含多次纠偏与踩坑（图标腿未提交会拆半套、max_tokens 过小导致假阴性、并行会话 README 计数漂移归因、共享树提交切法）。步骤多、含具体工具链与判据，另一 agent 可照单执行，属典型按需 playbook，而非一句内存规则能承载。

### 39. official-doc-model-evidence-panel
- 10-04 06:52 · pending · 置信 0.8 · 「归档-网关添加主流模型」
- 摘要：为『按官方文档取模型规格』派多角色的取证面板：r1 每厂商一名研究员（只用官方域、逐格附 URL、未核实显式标注、禁第三方数字）→ r2 两名验证员逐格独立复核（不得以 r1 为据，只当 URL 索引）→ r3 终审对『拟写入精确表』再判一次，输出 确认/不成立/无法核实 三态与可写入裁定；含平台取证技巧（Mintlify 站 URL 加 .md、腾讯大页 curl --compressed 防 WebFetch 截断误报、Google 域走 127.0.0.1:7890 代理、共享浏览器被占用时禁用 browser-use 改 curl）与报告先写骨架再逐段落盘的防中断纪律。
- 理由：本会话该协议被完整执行且两次失败重派（两名 agent 因抢共享浏览器中断，重派时显式禁用 browser-use 才跑通），并抓出官方文档自相矛盾（MiniMax thinking 缺省三页互斥、Gemini『含思考』只见于计费口径）——这些是纯方法论/工具链知识，可复用于任何『按官方文档写数据』的任务，且用户明确要求把它作为写入前置门。

### 40. gateway-logic-audit-report
- 10-04 08:49 · pending · 置信 0.85 · 「网关资源调度与重试逻辑」
- 摘要：Model-Gateway「只读核实 + 多 agent 交叉验证 + 台账报告」流水线：先按 docs/specs/prd.md §2 钉术语与 HEAD，再按固定判据档（成立/部分成立/不成立/无法验证）派 3 路独立角色（选路 / 失败切换 / 状态新鲜度），主 agent 亲自复验每一条承重数字并区分「名义配置值 vs 实测行为值」，最后按固定骨架交付 docs/changes/e2e-records 台账：更正声明 → 结论表 → 实盘读数（逐字+采样时刻）→ 真实流水诚实项 → 问题分级（A 待拍板 / B 缺陷 / C 易误判）→ 交叉验证裁决表 → 文档 vs 代码偏差 → 未验证清单。
- 理由：本轮出现完整可复跑的 2+ 步流程，且靠它当场纠错三处：①子 agent 过头结论「9 家额度闸门整个不成立」被我读 _apply_quota_to_pools 三态口径推翻；②我自己照抄 claim_interval_seconds=60 当实测节奏，被 ops-results JSONL 逐行算出的 290–298 秒推翻；③「配进 error_rules 即可不必改代码」被规则键是 (http,type)、不读 code 推翻。用户明确要求「派多 agent 交叉验证」「重新核实」「输出详细报告」，该流程另一个 agent 可逐字重跑；现有 batch-acceptance-merge 只覆盖验收合并，不覆盖只读核实与裁决口径。

### 41. gateway-live-state-probes
- 10-04 08:49 · pending · 置信 0.8 · 「网关资源调度与重试逻辑」
- 摘要：Model-Gateway 只读实盘探针命令集（全部须逐字抄输出并注明采样时刻）：GET /health 与 /openapi.json 路径计数判断后端是否真上线；coding/data/usage/ops-results-*.jsonl 按 ts 求相邻差得真实刷新节奏；upstream/*/accounts/*/runtime.json 聚合 quota.state 与 checked_at（ISO 字符串，非 epoch）分布；coding/data/config.yaml 数零映射条目资源、产品位开关；find data/upstream/zcode/accounts -name '*.log' 证离线面恒失败；circuit.json 的 until_ms 判熔断。含两个踩过的坑：系统 python3 无 pyyaml 必须用 coding/.venv/bin/python；zsh 下 `--include=*.py` 会 glob 失败，须改用 Grep 工具。
- 理由：本轮多次因工具形态失败并替换（python3→venv python、grep --include→Grep 工具），且所有结论可信度都压在这些具体读数上；checked_at 第一次按 epoch 解析得 0 条、改 ISO 才有读数，属典型 trial-and-error。这套探针是可被逐字复跑的固定管线，比 always-in-context 的简短记忆更适合承载命令细节。

### 42. pm-plain-answer-format
- 10-04 08:49 · pending · 置信 0.7 · 「网关资源调度与重试逻辑」
- 摘要：面向该用户（有研发基础的 PM）的回答/报告写法：先一句话结论再给表；四道门、三情形、更新机制一律表格化；代码位置与 file:line 收进附录不打断正文；禁用研发黑话（号/按号、bench、pool、in-flight），对象名严格用 PRD §2 四词（厂商=造模型的 / 供应商=接入渠道 / 资源=模型资源 / 网关模型=统一名）；自己写错的须在开头立「更正声明」逐条列原说法与更正依据；事实与「未验证」严格分栏，不许把单测/假上游冒充生产实证。
- 理由：用户在两轮内连续纠正同一件事：第一轮「厂商和供应商你别给我搞混了，感觉你输出的厂商都不对」、第二轮「我不是研发，套专业的数据看不到…需要通俗易懂准确清晰」，随后又第三次指出「术语还是有问题」。这是输出规格上的 2+ 轮精修并已稳定成形；AGENTS.md 铁律 6 只给术语定义，不含这套表达结构与黑话清单，适合独立按需调用。

### 43. channel-constraint-verification
- 10-04 09:35 · pending · 置信 0.86 · 「归档-网关添加主流模型」
- 摘要：核实「某厂商/通道拒绝某请求形态」这类结论的固定流程：不靠单发探针，改为聚合网关自己的事件流水（coding/data/usage/events-YYYYMMDD.jsonl，按 网关模型 × stream × 状态 × 实际承接资源 × error_summary 分组），逐条指认是哪个池成员产出的结果；再按「确定性通道差异 ⇒ 出站适配层补齐（流式聚合 / 首条 system 整形）」「内容相关差异 ⇒ 同样在根因处整形」定层，并显式禁止「跳过/隐藏该成员」这类回避式修法；同时钉住两个探针自坑：预算 ≥2048（否则 token 全进 reasoning_tokens ⇒ 正文空但事件行 success）与流式只取首帧即止会被误读成上游空返回（实为 aborted）。
- 理由：用户两次纠正我的方法与结论：「你再充分核实下你的问题是否真的存在…而不是单方面只看问题而偏离整体项目定位和目标」暴露我把池内成员差异读成「上游抖动/族级约束」；随后「再有类似问题绝对不允许…这是回避问题，严重违规，属于堆屎山」= going-forward 级禁令。整套判据取法、分层决策与探针预算规则是 2 步以上、可被另一个 agent 逐字复跑的管线，且当天三次踩坑（空返回、aborted、误报族级约束）。

### 44. island-readme-test-count
- 10-04 09:35 · pending · 置信 0.8 · 「归档-网关添加主流模型」
- 摘要：本仓 README 测试计数的提交快照（岛式）口径操作：先只提交自己改动的面（git diff --numstat 逐文件核对、不夹带并行会话），再 git archive HEAD | tar -x -C /tmp/island-N && cd /tmp/island-N/coding && 主仓 .venv/bin/python -m pytest -q；README 双语取「岛收集数 − 1 条 skip」，已知岛拷贝伪红 test_ops_lock_dir_ignores_cwd 单列归因；随后本机 test_readme_test_counts_are_not_stale 必红（宣称岛值 / 工作树实收），按已归档裁定保留并在账里写明漂数来源（并行会话未入库测试条数），禁止改数字蒙绿。
- 理由：本会话把这条管线完整跑了两轮（README 1962 → 1967，两次岛式 494~495s 全量），且与「计数必须抄自 runner 自己输出」「台账不得留待回填」等既有规则绑定；它是可逐字复跑的多步流程，另有并行会话共享树这个前提条件必须写清，否则下轮很容易把工作树值误写进 README。

### 45. repo-terminology-sweep
- 10-04 11:12 · pending · 置信 0.85 · 「API调用条件核实（分支）」
- 摘要：全仓术语/概念改名的可复跑工序：先快照 + 保护锁（保留项与存证行）→ 按「先全扫、最后统一还原归档行、还原过的文件不再回扫」的顺序批量替换 → 双语 README/配置注释/代码注释/界面文案分档处理 → 快照 diff 还原存证行 → 门内字面同批推进 → 多 agent 交叉验证后才宣称「已统一」。
- 理由：本轮踩了三次同类坑并都做了方向纠正：①第一版把保留项「厂商 API 文档」误伤、并改了版本史行，只能从快照整体回滚重做；②还原步骤夹在多轮扫描之间，后一轮把已还原的 models.js:1 与 PRD 归档行再次改坏，才定出「替换→最后还原→再跑门」的工序铁律；③我在每份文档顶部宣称「规范性正文已统一」而实际还剩 ~37 处 = over-claim。更典型的是缺省档改名：先按「厂商内置默认」定名扫完 13 个文件，随后发现 PRD FR-3.16 规范句写的是「该供应商通道默认」，只能整体反向重扫。这套顺序、豁免范围（docs/changes 与 docs/research 属存证、docs/ 还被 gitignore 永不进提交）、字段名/类名不许动等判据，另一个 agent 无法从代码里推出来，只能照抄工序。

### 46. terminology-concept-unification
- 10-04 11:44 · pending · 置信 0.86 · 「API调用条件核实（分支）」
- 摘要：全仓术语/概念统一的完整工序：定义源先行 → 保留词锁 + 存证豁免 → 批量替换（扫描全做完再还原归档行）→ 界面文案与门内字面同批推进并重新打红 → 多 agent 交叉验证 → 去重缺陷表与落库切分。
- 理由：本会话是一条真实可复跑的流水线，且多次试错才收敛：第一版批量替换误伤「厂商 API 文档」并改到版本史行→从快照回滚重建；还原顺序错位导致已还原行被二次污染→定下「替换→最后还原→再跑门」；文档顶部声明写成超出实测的「正文已统一」→被自己复核判为过度声明。这些教训目前只散落在 .cursor/rules 与 pitfalls 的短规则里，没有一份能照着执行的 playbook（含扫描脚本骨架、保留词表、`docs/` 被 gitignore 时不能用 `git diff -- docs/changes/` 自证的替代取证法）。另一个 agent 照它可逐步执行，属 2 步以上可复现流程。

### 47. multi-agent-concept-audit
- 10-04 11:44 · pending · 置信 0.78 · 「API调用条件核实（分支）」
- 摘要：按面切路的只读多 agent 审计面板：固定六路分工（配置数据流/调度规格/协议归属/界面统计/规范文档/测试与门）+ 统一输出契约（报告分段增量写、末行 VERDICT、P0/P1/P2、每条附 file:line 与逐字命令输出、并行会话文件单独归属），主 agent 逐条复研去重（两路同报只算一条）。
- 理由：用户明确要求「所有改动都需要经过多 agent 交叉验证验收通过才能交付」，且反复强调交叉验证不是叠加、分歧由主 agent 亲自复研。本轮实际产出即依赖这套输出契约与去重规则；会话里还出现子 agent 越界改文件、行号报错、把注释当可见文案扫出假结果等情况，说明契约需要写死。这是可被其他 agent 逐字执行的多步流程，且现有 batch-acceptance-merge/acceptance-verifier-false-red 只覆盖验收合并与假红归因，未覆盖概念审计与去重定案。

### 48. mg-empty-field-layer-diagnosis
- 10-04 11:44 · pending · 置信 0.78 · 「排查网关模型参数为空问题」
- 摘要：Model-Gateway「界面某字段为空/没有配置项」四层定位 playbook：渲染集合来源(models.js pkeys 之类) → 目录/数据层(EnumEntry.params_default) → 消费与注入层(ir.apply_model_params + apply_spec_defaults / scheduler._out_body) → 实盘只读读数(curl :8300/admin/api/config + data/config.yaml 交叉比对)，并按固定分类判定三类缺陷：①按设计留空(有据) ②对自身行为的假陈述(文案说不注入但别的层在注入) ③多源对同一字段各说各话(参数卡 max_tokens vs 网关承诺 max_output)，最后再查该卡在前端门里有没有判据(verify_v2_frontend.mjs 的 models.js 引用点)。交付格式固定：docs/changes/plans/YYYYMMDD-*.md + P0/P1/P2 分期 + 决策点表(每条带反转触发) + 未验清单，诊断阶段零源码改动。
- 理由：本轮是一条可被其他 agent 逐字复跑的多步管线，且含两处非显然的转向：初始假设「创建路径没带默认值」被实盘只读读数证伪(10 条 params 与官方默认逐键差异为零)，以及 images 是否被注入需读 scheduler 的 endpoint==chat 门才敢下结论——正是本项目「假说先被证据打掉再写诊断」的做法；再加上「空 ≠ 缺陷」的三分法与「参数卡今天零判据」这类必须专门去查的覆盖面步骤，都属于按需 playbook 而非始终在上下文里的简短规则。

### 49. mg-live-tree-provenance
- 10-04 11:44 · pending · 置信 0.62 · 「排查网关模型参数为空问题」
- 摘要：共享工作树 + 实盘实例上的取证读数纪律：报告任何数字前先 md5 -q 五个被引用源文件 + git diff --numstat HEAD 登记并行会话未提交改动，实盘一律走只读 GET /admin/api/config(管理端免鉴权)、零写入零点击，读数脚本用 .venv/bin/python 从 data/config.yaml 与 BUILTIN_ENTRIES 交叉计算而非手抄，并把测量口径(工作树 md5 / 实盘端口 / 采集时刻)写进交付文档抬头。
- 理由：本轮把这些当成硬性步骤执行并在文档里留下了「引用前须重测 md5」的自警，是项目特有、可复跑的取证格式；但它与上一条 playbook 部分重叠，且更像记忆级规则，故置信度较低。

### 50. multiagent-concept-audit
- 10-04 11:48 · pending · 置信 0.82 · 「API调用条件核实（分支）」
- 摘要：分层只读多 agent 审计的固定工序：按「配置与数据流 / 调度与规格 / 入站出站协议 / 界面文案与统计维度 / 规范文档一致性 / 测试与验收门」六路并行派只读 agent，每路必须交 file:line + 逐字 runner 输出 + P0(行为错)/P1(误导下次改动)/P2(措辞) 分级并增量写报告；主 agent 逐条亲自复研（两路同报只算一条、只有一路报且能证伪才算）、去重合并成一张缺陷表（含「看着可疑但归属正确」清单与未验证项）。
- 理由：本轮用户两次纠正口径并明令「所有改动都要多 agent 交叉验证」；实际执行形成了可被另一个 agent 逐字复跑的六路分工 + 判决格式 + 去重合并规则，且过程中出现真实分歧（A2/A3 同报档位归属、A6 报的死锚点被我复现、A5 的行号漂移），这些判定纪律不在任何现有技能里。

### 51. terminology-bulk-rename
- 10-04 11:48 · pending · 置信 0.8 · 「API调用条件核实（分支）」
- 摘要：术语/概念批量改名的安全工序：先锁保留搭配（厂商官方文档、厂商内置目录、厂商归属…）→ 跳过叙述行与引号内用户原话 → 全部扫描完成后**最后**统一还原存证行且还原过的文件不再回扫 → 界面文案改动必须同批推进门内字面并复跑 --mutation 证明仍可红 → 双替换伪影自检（网关网关模型）→ 声明只在残留实测清零后才写「已统一」；注意 docs/ 被 gitignore，「存证未改写」不能用 git diff 证明，要用基线快照对拍。
- 理由：这条工序是被三次真实事故换来的：第一版误伤保留项并改了版本史、还原顺序错了被后一轮再改坏、以及「规范性正文已统一」的过度声明被复验抓为撒谎；还包含一次方向反转（缺省档先改成厂商内置、复核 PRD 后反转为供应商通道默认）。步骤具体、可逐字执行，现有技能完全未覆盖。

### 52. client-wasm-signing-bridge
- 10-04 21:54 · pending · 置信 0.86 · 「API调用条件核实」
- 摘要：把「客户端自带 wasm/签名」的能力桥接进 Python 服务的完整流程：动手前六步离线可行性探针（自包含 ESM 判定→generateRuntimeAuthFields→create+签名→getOwnPropertyNames 决定 payload 模式还是 ask 模式→host 带不带 scheme→凭据键名清点）；桥本体写我方 .mjs（NDJSON 按 id 配对、console.log 改道、缺件点名、形状不符拒绝服务且不许退回让上游拼明文、一账号一上下文且键含令牌短指纹）；Python 侧 fail-closed 三件套（create_subprocess_exec 必须显式 limit=4MB，否则 asyncio 默认 64KiB 被整份密文撑爆→读任务静默死亡→等待者拿到错原因且每次请求泄漏一个子进程；_pump 全循环兜底+kill+清 _loop；单号残缺允许换号、基础设施级才 no_failover；stderr 尾巴出口按值脱敏；环境变量注入且未配置=与接线前逐字节一致）。
- 理由：本轮完全靠试错与纠偏长出来：三次探针定接口、实测复现 ValueError: Separator is not found、评审抓出 accountKey 不含令牌会导致续期后永久旧身份签名。项目还有 trae/zcode 等同族签名/验证码注入缝，另一个 agent 可按此 playbook 逐字复用；且涉及用户明确红线（不许把能力需求简化或回避），值得固化为按需加载的操作手册而非仅口头规则。

### 53. mgw-ui-change-gate-forward
- 10-04 23:19 · pending · 置信 0.85 · 「移除状态列」
- 摘要：Model-Gateway 界面改动交付流水线：删/改一个控件或列 → 判据「随设计前进」（重定锚不删条目）→ 按序跑四道门（静态门 verify_accounts_ui.mjs + --mutation、回执门 verify_map_switch_receipt.mjs --mutate 1..N、v2 门需 make_overview_payload.py 载荷、真机门 verify_accounts_ui_live.py --skip-legs 约 20 分钟）→ :8300 只读探针 → 规范回写（frontend-spec/design-spec/AGENTS.md）+ 台账 + 项目 memory。含本仓硬纪律：变异锚必须恰一命中、每条变异只打红它声明的那条判据、判据对象缺失必须如实红而不用空判据蒙过、并行会话在飞面只报备不代改。
- 理由：本轮出现完整可复跑的多步管线，且三处靠试错才收敛：V25 被自己注释里的「104px」打红（判据扫含注释切片）、回执门 D1 锚因缩进变化命中 0 次需重定锚、MS8 首跑因门实例 `models: []` 没有对象 ⇒ 改成判据自造对象再净零。这些步骤和坑位都不在任何现有技能里（batch-acceptance-merge 只管多 commit 批量验收合并），另一个 agent 照此可逐字复跑。

### 54. ego-probe-zero-window-hygiene
- 10-04 23:19 · pending · 置信 0.8 · 「移除状态列」
- 摘要：在本机 Ego Lite「0 个 OS 窗口」环境下写/跑浏览器探针与真机判据的操作卫生：① 必须先 `Emulation.setDeviceMetricsOverride` 设视口（1440×900）、跑完 `clearDeviceMetricsOverride` 复位，否则 getBoundingClientRect 全 0、几何判据量到的是环境产物；② 不要用 `page.waitForSelector`（该环境下弹窗在 DOM 里、evaluate 读得到全文却恒超时），改页内轮询 `evaluate(() => !!document.querySelector(...))`；③ 单击用页内 `el.click()`（驱动层 page.click 实测派发 2 次）；④ 声明只读就必须零写入零点击并显式验证关窗归零；⑤ 内嵌 JS 抽出后 `node --check`，Python 侧 `ast.parse`，且字符串内禁嵌套 ASCII 双引号（本轮三次踩）；⑥ 系统 python3=3.9.6，含 walrus/f-string 的脚本须 python3.12。
- 理由：本轮为「探针跑不通」做了三轮归因式改法（waitForSelector 瞎 → 页内轮询；名列宽 0px → 没设视口；SyntaxError 三连 → 嵌套双引号与 3.9 语法），是典型的可复用工具链与输出格式规范，且现有 ego-browser 技能只讲开站/操作/截图，不覆盖这个 0 窗口环境的量测陷阱。

### 55. mgw-spec-writeback-bookkeeping
- 10-04 23:19 · pending · 置信 0.72 · 「移除状态列」
- 摘要：改完界面/契约后的规范回写固定动作与账本格式：① frontend-spec / design-spec 版本号取**下一个空位**（落笔前 grep 现值，被并行会话占用就顺位，并在正文写版本号说明）；② 三处都要动：顶部「版本」行（并把旧行降为「上一版」）、规范正文小节（§7.11 等）、文末版本表逐行；③ AGENTS.md 巨型条目的插入点 = 尾部「运行时数据 coding/data/」那句之前；④ 台账命名 `docs/changes/e2e-records/E2E-YYYYMMDD-<主题>.md`，门号必须逐字抄运行器自己的输出并附原文路径；⑤  存证不改写：旧台账/版本史行/用户原话引号内保留当时措辞；⑥ 项目 memory 写 project 作用域并在同作用域 MEMORY.md 加一行指针（勿误写进 user 索引）。
- 理由：本轮实际踩到并纠正了三处账本缺陷：并行会话把 frontend-spec 顶部版本行留在 v2.43 而 v2.44 挂在下面、版本表缺 v2.44 行、我自己把新轮次的索引指针先写进了 user 作用域 MEMORY.md 再迁回 project；以及一次 Edit 因 `old_string` 命中第一处 `try {` 而改坏文件。这些是格式固定、可逐字执行的回写程序，另一 agent 照做即可避免同类假账。

### 56. mgw-frontend-delivery-chain
- 10-05 00:51 · pending · 置信 0.82 · 「移除状态列」
- 摘要：Model-Gateway 前端改动（accounts.js 等）的完整验收链与命令序列：改码 → `cp x.js /tmp/x.mjs && node --check` → 账号静态门 `verify_accounts_ui.mjs`（+ `--mutation`）→ 回执门 `verify_map_switch_receipt.mjs`（`--mutate 1..11` 逐条 rc=1 恰一红）→ v2 门（先 `make_overview_payload.py` 生成 overview JSON 再喂 `verify_v2_frontend.mjs`）→ 真机门 `verify_accounts_ui_live.py --skip-legs`（后台跑 ~20 分钟、端口 8400-8499 隔离实例 + 假上游、绝不 kill）→ :8300 只读探针 → 定向 pytest → 规范回写（frontend-spec / design-spec / AGENTS.md）+ 台账 + 记忆。含本机环境固定坑：Ego Lite 0 个 OS 窗口 ⇒ `Page.captureScreenshot` 必超时、几何判据必须 `setViewport(1440,900)` 后跑并 `clearViewport` 复位、`waitForSelector` 对弹窗恒超时须改页内轮询；README 漂数那条红按已归档裁定保留不蒙绿；docs/ 被 gitignore ⇒ 文档改动永不进提交。
- 理由：本轮跑通了一条 8+ 步、命令与端口全部固定的可复现流水线，中途因环境（0 窗口、视口、浏览器分段超时）多次纠偏并靠后台重跑收敛；现有技能里 `batch-acceptance-merge` 明写仅适用 codex-coding 工程，`ego-browser` 只讲浏览器操作，都没覆盖这条链。另一个 agent 按此可逐字重跑，属典型 on-demand playbook 而非一句话记忆规则。

### 57. mgw-gate-criterion-migration
- 10-05 00:51 · pending · 置信 0.78 · 「移除状态列」
- 摘要：在本仓「设计变了但判据不许删」的判据前进法：① 静态门每条腿必须配一条能红、且只改被测语法不改结构的变异（变异里引用未定义变量会让假 DOM 崩掉 ⇒ 红来自整页没渲染 = 无效撤证）；② 判据扫的是含注释的源码切片 ⇒ 自己在注释里写的字面（如旧列宽数值）会把自己打红；③ 换载体时重定锚而不是删条目（本轮把回执门 D1~D5 从「删除钮五条」改写成「解除这条腿五条」、B 系列与变异 5/6/10/11 全部重锚，条数不减）；④ 真机判据要钉「这次改动改变了什么」而不是「我以为会发哪几个请求」（本轮 MS8 断言『不发 mappings』被同表其它带自动建议的行合法提交打穿，改成『remove 恰 1 条 + 该行末位=null』）；⑤ 没有对象的判据是空判据 ⇒ 让判据自己造对象再归零（净零生命周期），别改别段依赖的 fixture 前提；⑥ 样本缺失必须如实红，不许空过；⑦ 每次改完内嵌 JS 的门都要抽出 JS 段 `node --check`。
- 理由：本会话出现多次真实纠偏：V25 被自己注释打红、MS8 两次红（一次 fixture 前提、一次判据对象选错）、变异锚点过期报 BAD、无效撤证风险。这些是同一套可复用的判据写作/迁移纪律，散落在多条 always-in-context 记忆里但没有一份可按步骤执行的 playbook。

### 58. shared-tree-hunk-commit-island-verify
- 10-05 07:11 · pending · 置信 0.88 · 「API调用条件核实」
- 摘要：在并行会话同处一树的共享工作区里，只提交自己那一刀的完整流程：按关键字把 `git diff HEAD` 的 hunk 分类成「我的 / 别人的 / 混合」→ 纯我的文件整份 add、可分离的用 `git apply --cached --recount`、混合文件走 `git show HEAD:<f>` + 定点替换 + `git hash-object -w --stdin` + `git update-index --cacheinfo 100644,<sha>,<path>` → 核对暂存 diff 零污染 → `git archive` 解出提交树快照（软链 .venv）跑全量自证 → README 取岛式「收集减 skip」值 → 撤证复原一律用 /tmp 备份并前后 md5 比对（禁 `git checkout --`）。
- 理由：本轮该流程被完整走通两次（`c473d4d` 签名腿 19 文件、`914f97b` 启动器），且踩出三处只有做过才知道的坑：MIX hunk 无法用 apply 拆分必须改走 hash-object+update-index；`--cacheinfo` 要求 sha 而 `git hash-object -` 需 `--stdin`（我因此报错一次）；工作树含并行会话未跟踪测试导致 README 漂数红是预期而须报备。现有记忆只有「隔离后合并、ff-only、跑前 md5」这类原则句，没有任何一份可逐字复跑的命令链，属于 2+ 步可复用管线。

### 59. gateway-automation-attribution
- 10-05 07:22 · pending · 置信 0.72 · 「自动化更新逻辑」
- 摘要：核查「某个自动更新到底谁在驱动」的证据链 playbook（Model-Gateway）：① mcp__builtin__qoder_cron action=list 取任务全集，并识别「UI 里第二行是执行会话不是第二个任务」（outputMode=merged 时按 lastRunAt/名字前缀对号）；② 把 createdAt/lastRunAt/nextRunAt/expiresAt 的 epoch 毫秒用 python3 一次性换算成本地时刻，判断观察窗是否到期；③ grep 网关进程内调度腿（main.py::_maybe_start_ops、ops/runner.py::Scheduler、config/schemas.py 的 claim_interval_seconds/claim_cron/quota_net、query_balance.py 的 via!="user" 豁免）确认「发 HTTP 的那一条在网关里，不在 Qoder」；④ 读实盘 coding/data/config.yaml 取当前真值而不是缺省值；⑤ 读台账观察期表（docs/changes/e2e-records/E2E-20261002-zcode-quota-refresh.md §8）取轮次/N_i/Δ 实测数；⑥ 交付口径固定为「内置腿 vs 外部只读看门狗 vs 待裁定项」三段，并声明看门狗自身零出站/零重启/零提交。含一条环境坑：zsh 下 grep 的 --include=*.py 必须加引号，否则整条命令报 no matches found 而前半段已执行。
- 理由：本轮出现了一条可被另一个 agent 逐字复跑的多步判定链，且结论依赖三处异源证据（cron 任务字段 / 网关源码 / 实盘配置 / 台账表）互相印证——缺任一处就会把「Qoder 定时任务」和「网关内置调度腿」混为一谈，这正是用户提问的陷阱所在。项目里同类腿很多（2h 自动续期、5h 批量续期、额度 cron 腿、观察期采样、ship-gate），「是不是通过 X 定时驱动的」这类归因问题会反复出现；本仓库既有 skills 全是设计/验收/合并流水线，没有覆盖这种运行时归属核查。同时本轮真踩到 zsh 未加引号的 --include glob 让一条组合命令半失败，属于会重复发生的操作坑，值得随 playbook 固化。

### 60. mg-criterion-advance-with-design-loop
- 10-05 08:24 · pending · 置信 0.82 · 「修复模型资源与映射」
- 摘要：「判据随设计前进」的固定收口流程：旧判据**反转改写而不是删条目**，逐门复跑 + 变异重定锚 + 内嵌 JS `node --check` + 真机门 md5 前后自证，一次跑完不许开第 N 轮角色。含本轮踩到的四类坑位与修法：① 负向判据必须 `stripComments`（我自己写的注释/可见文案把禁词扫成红）；② 变异锚点命中 0 次报 BAD ⇒ 重定锚后再看命中数，不能只看「没报错」；③ 判据里 `some()` 的布尔参与加法 ⇒ 方向反了的空判据（画出来就红、一颗不画反而绿）；④ python heredoc 里嵌 JS 字符串带内层双引号 ⇒ SyntaxError（本轮两次），改用「」或先写临时文件。命令序列：`node bianyiandhuanjing/scripts/verify_accounts_ui.mjs` → `--mutation` → `node .../verify_map_switch_receipt.mjs` → `--mutate 1..N`（要求逐条恰一红）→ `pytest -q tests/integration/test_accounts_catalog_mapping_api.py ...` → 真机门 `verify_accounts_ui_live.py --skip-legs --port 84xx --basetemp ...`（跑前后 md5 必须一致，漂移则如实声明该轮非独占终局）。
- 理由：本轮把 V22/V25/V26/V27 四条钉住旧契约的判据反转改写并新增 V28，配套 12 条变异逐条恰一红、可红 48/48；过程中真实发生了三次门侧自伤（BAD 命中 0、空判据方向反、禁词写进可见文案）和两次 heredoc 语法崩溃，都是靠反复试错才收敛的可复用步骤，另一个 agent 照单执行即可避免重犯。

### 61. mg-two-truths-live-diagnosis
- 10-05 08:24 · pending · 置信 0.78 · 「修复模型资源与映射」
- 摘要：定位「界面说而盘上没有」类缺陷的实盘三面对账管线：只读 `GET :8300/admin/api/config`（`product_models` 产品位 × `models[].resources[]` 条目 × 派生位 `mapping_enabled`）+ 逐产品 `GET /admin/api/accounts/{p}/catalog`（`map_enabled` 三态位 / `mapped_to` / `suggest.confidence` / `map_landing`），按四类形状分档统计——「位开而零进池条目」「位关且零条目」「建议占了下拉当前值（map_enabled=null 但界面有目标）」「位指别处」；再用代码定位写面生产者（行开关 / 行下拉 / auto-map）比对各自的 `enabled` 缺省值。先区分是不是假关联，再决定改写面还是改显示。
- 理由：用户两条投诉（资源池不显示 + 多一步保存）被这一套读数一次锁定为同一根因（14 条位关零条目 + 26 行建议占位），且明确证否了「显示层 bug」的初判；该管线含固定端点、固定字段与分档判定表，可被逐字复跑，也纠正了我一开始只想在文案上打补丁的倾向。

### 62. gateway-automation-loop-audit
- 10-05 11:08 · pending · 置信 0.75 · 「自动化更新逻辑」
- 摘要：核查「某个自动更新到底谁在驱动 / 是否内部闭环」的固定取证链路（Model-Gateway）：① `mcp__builtin__qoder_cron {action:list}` 取任务表，并用 python 把 createdAt/lastRunAt/nextRunAt/expiresAt 折成本地时刻（截图里「两行」常常是一条任务 + 它的 merged 执行会话，`list` 只有一条即为一条）；② 与网关进程内的腿严格分开：`main.py::_maybe_start_ops` + `ops/runner.py::Scheduler`（间隔取 `gateway.zcode.claim_interval_seconds`，实测一轮 ≈292s）、tick 三条腿（签到 / `query_balance` 额度快照 / `auto_renew.refresh_due`）、启动即刷 `refresh_quotas`（本地日志尾读、零网络）、`_hourly_aggregation`，用 `grep -rn "create_task\|Scheduler(\|sched.start"` 穷举全部周期循环，别只认已知那几条；③ 判「闭环」必须查**写者**而不只看读者：`grep -rn catalog_cache` 看 `write_cache` 的调用点是否只在管理端 HTTP 腿上（实盘只有 `api/admin_accounts.py:1218/:1371`），配合 `DEFAULT_TTL_SECONDS=86400` 与「调度/`/v1/models` 零网络只读缓存」⇒ 缓存过期无人续 = 不闭环；④ 覆盖面按能力位收窄（`capabilities.balance` / `checkin` 推导 `SUPPORTED_PRODUCTS`）+ 闸门（`quota_net` 缺省 false，改它要写 `coding/data/config.yaml` 并重启 :8300）+ 仓内静态数据（`BUILTIN_ENTRIES` 扩充 = 改源码）三类一并列为不闭环；⑤ 观察期进度读台账表格行数与最后一行（`E2E-20261002-zcode-quota-refresh.md` §8 观察期表，本轮 29/Δ=0）而不是凭记忆；⑥ 输出形态 = 「内部闭环的 / 不闭环的分块 / 一句话口径（刷新时效 vs 取得新数据）」，含后端改动的建议一律标注「要重启 :8300、先不动等你定」。附一条 shell 坑：zsh 下 `grep --include=*.py` 会被 glob 吞成 `no matches found`，须引号包住或直接改用 Grep 工具。
- 理由：用户按「追问同一结论的更严口径」方式连问两轮（是不是 Qoder 定时驱动 → 那是不是完全闭环），第二轮实质否掉了第一轮回答的完整性，逼出「写者 vs 读者 / 能力位覆盖面 / 静态目录 / 外部闸门」这套分类判据；过程含一次工具失败替换（zsh glob）与一次时间范围换算（expiresAt 折本地时刻得出窗口今日 16:00 到期）。这是另一 agent 可逐字复跑的多步取证管线，且该项目反复出现同类提问（用户以完备性考察为导向），比 always-in-context 的精简记忆条目更适合按需加载成 playbook。

### 63. mgw-instance-restart-verify
- 10-05 11:10 · pending · 置信 0.82 · 「修复模型资源与映射」
- 摘要：Model-Gateway 重启 :8300 并证明「哪一条语义真的上线」的完整流程：跑前 md5/备份快照 → POST /admin/api/system/restart → 轮询回 200 → 用**幂等零写盘的形状探针**（回执是否带新键 + config md5 跑前=跑后）判定新码已加载 → 只读复验 /v1/models、位不变量、供出静态资源 md5=磁盘 md5、调度基线 → 明确列出哪些实盘判据必须用户点头（会烧真实额度/写真实配置）才能跑。
- 理由：本轮出现两处只有踩过才知道的坑：① 网关走 execv 同 PID 换代，pid 与 ps lstart 都不变 ⇒ 「进程时刻」是假判据，我当场差点据此认为没重启；② 替代判据是设计出来的（幂等请求 + 响应新键 + 配置文件逐字节不变 + 零出站），另一个 agent 无法凭直觉复现。还包含一条边界判断：实盘 10 个产品没有一个 pending=0，故 written:false 早退只能在临时实例钉、不许替用户烧额度——这类「哪些验证不能做」的决策流程正是 playbook 该固化而 memory 装不下的部分。

### 64. mgw-gate-terminal-evidence
- 10-05 11:10 · pending · 置信 0.78 · 「修复模型资源与映射」
- 摘要：门终局数的取证与漂移归因：ship-gate.sh 在 [1/2] pytest 非 0 时直接 exit ⇒ [2/2] 静态门必须按门内同一套命令手工复跑（cd coding、用 .venv/bin/python 跑 make_overview_payload.py <tmpdir> 取 tail -1 的 json 路径再喂 node 门，裸调会 exit 2）；README 计数红用 git archive HEAD 快照 --collect-only 得提交树数、逐支统计未跟踪 test_*.py 贡献、算出净增；并含两条实盘事实：tests/verify_v*_repro.py 不在收集范围（python_files 未覆写）、索引可以比磁盘新（README 工作树副本比 HEAD 旧 ⇒ 提交会静默回退数字）。
- 理由：本轮我三次走错才收敛：先按 node 直接调门（打印用法 exit 2）、再用系统 python3.12（ModuleNotFoundError: pytest）、最后读 ship-gate.sh 才拿到正确调用；期间又用 e.get("product") 筛条目得出「47 条全零」的假结论（同一坑第二次踩，AGENTS.md 早记过）。这些都是带固定路径与固定命令的可复跑步骤，且直接决定「能不能宣称某个门数属于当前这棵树」，符合『引用工具调用/固定格式的 durable 流程』信号。

### 65. gateway-channel-failover-verification
- 10-05 14:05 · pending · 置信 0.82 · 「网关调用可用性评估」
- 摘要：为「某通道/某产品账号池能否投用」交付一套可复跑判据矩阵的 playbook：用既有集成测试基建（fake vendor + make_gateway/client fixture，数据根经 conftest 的 MG_CONFIG 自动隔离）搭本地假上游，按每号身份头（如 X-Device-Mid）逐号分派行为，覆盖轮转/并发上限/4xx 风控/200 自有信封/429/5xx+阈值/超时/流式提交后中断/额度 0 排除/熔断/对外声明与派发分叉；每条用例必须标明「契约」还是「现状刻画=缺陷证据」，并用既有配置覆写面（error_rules 改判分类）做反证以证明判据不空转，禁止在共享工作树上改源码做撤证。
- 理由：本轮从零长出这条 2+ 步流水线并跑通 22 条用例；期间 4 处需要替换做法（系统 python3 无 yaml 改用 coding/.venv、attempt_timeout 传浮点被 schema 拒须传 int、grep --include 在 zsh 下失配、空流断言被自己打回后补 Z20 对照）；用户还明确纠正了范围（不打真实上游）并要求「再进一步核实」，正是可被其他 agent 逐字复用的方法与产出格式（含 契约/现状刻画 双标签 + 台账里的自纠清单）。现有 skills 与 .cursor/rules 都没有这条链。

### 66. mg-offline-failover-matrix
- 10-05 14:08 · pending · 置信 0.86 · 「网关调用可用性评估」
- 摘要：Model-Gateway 渠道/号池故障切换的离线判据矩阵 playbook：用「按账号身份头（如 X-Device-Mid）分派行为」的可编程假上游 + 既有 integration fixtures 跑全栈真实 HTTP，逐条覆盖 4xx/405/200信封/429/5xx/超时/流式中途断/额度0/熔断/声明vs派发；用例必须区分「契约」与「现状刻画=缺陷证据」，并用 error_rules 改分类做反证证明判据不空转。
- 理由：本轮从零长出一套可复跑流程（22 passed），期间我自己判据写错 6 次、用户两次纠正方法与范围；这些步骤（身份头分派假上游、契约/现状分类、反证 Z22、撤证不空转）另一个 agent 可逐字执行，且现有技能（batch-acceptance-merge 等）完全不覆盖这种渠道故障矩阵测试。

### 67. mg-live-pool-readiness-audit
- 10-05 14:08 · pending · 置信 0.82 · 「网关调用可用性评估」
- 摘要：只读审计「实盘到底哪些资源会被派发」的固定链路：用 AppConfig.mapping_enabled 逐条算进池（含无产品位回落条目位）、从 data/upstream/<product>/accounts/*/runtime.json 灌额度并区分 0 / None / no_plan 三档、对照 /admin/api/overview 的视图位 available=status=='active'（不含额度）与派发位 available()、再用进程内 pick_and_acquire 模拟 N 次派发做归因；附踩过的坑：事件字段是 system_model 不是 model、config 里模型只有 name 没有 id、x 可能被并行会话改动作废引用前必须重测。
- 理由：用户最后一问（「没额度的号为什么在池里」）暴露出只看 remaining=0 会漏掉 no_plan 整档，而这套「配置+运行态+只读模拟」的交叉核法是可复用的多步管线；我自己在此处翻过两次车（读错 key、筛错字段导致假 0 行），值得固化成按需 playbook 而不是只留在记忆里。

### 68. gateway-pool-selection-audit
- 10-05 14:37 · pending · 置信 0.85 · 「网关调用可用性评估」
- 摘要：审计网关「某个网关模型到底选了哪些号」的可复跑流水线：从实盘 config + 各账号 runtime.json 读出额度/资格分档 → 在隔离实例（显式 MG_CONFIG + 假上游，按每号身份头 X-Device-Mid 分派行为）一比一复刻该分布 → 依次跑「全正常串行 / 并发 / 持续 5xx / 持续 4xx 风控 / 200 自有信封 / 额度 0 / 无套餐」多轮 → 读事件 JSONL（字段是 system_model，不是 model）按规则逐轮判红绿 → 给改前/改后对照表。含三条必踩坑：x 限的是「同时承接的资源数」而非请求数；零读数必须先证明不是选择器失明；空正文被记 success 属「无报错的失败」，反证用例（只改分类即换号）用来钉判据不空转。
- 理由：用户两轮收窄指令（先「严格测试能否投用」→ 再「就是正常调网关看内部取的资源对不对」）才把范围定准；过程中我因把 x 当请求并发上限、按 model 字段筛事件、手工拼 ResourceState 造出假阳性而多次返工；最终流程（实盘分档复刻 → 隔离实例 → 故障注入 → 事件行对账 → 前后对照）是另一个 agent 可逐字复跑的管线，且本项目反复出现同类需求（Q33 号级承载、可用性核实轮都用过同形探针）。

### 69. gateway-model-dispatch-selection-audit
- 10-05 16:24 · pending · 置信 0.86 · 「网关调用可用性评估」
- 摘要：严格测试「某个网关模型实际被派到哪些资源」的固定流水线：只读取实盘 config + 各账号 runtime.json 复刻资源分档 → 起隔离实例 + 本地假上游（按身份头逐号分派失败形状）→ 逐条规则（额度0/停用/无承接资格/反复失败/量纲阈值）出对账表 → 改前改后同表复跑。
- 理由：用户三次收窄口径（不要打真上游→就是要正常调网关看内部选得对不对→再补量纲阈值），最终稳定成一套可复跑的证据格式；过程里踩了多个非显然坑：真实字段名是 system_model 不是 model（零读数先是选择器失明）、models[] 用 name 不是 id、x 限的是承接资源数而非请求数、资格位必须经真实生产者函数灌入。这些步骤另一个 agent 无法凭直觉复现，且明确可 verbatim 重跑（pytest 矩阵 + probe_zcode_live_shape.py 双产物）。

### 70. mgw-instance-liveness-proof
- 10-05 18:51 · pending · 置信 0.82 · 「修复模型资源与映射」
- 摘要：证明「代码改动是否真在 :8300 运行实例上生效」的可复跑流程：execv 同 PID 换代使 ps/pid 失效 ⇒ 用「磁盘 md5 ⇄ 供出字节 md5 + cache-control」验前端，用「幂等零写盘请求的回执新键」验后端；无法只读证明（如 openapi requestBody 为空、唯一能证的 POST 会真写盘）时一律判「未上线」并显式报备「新前端 + 旧后端」这种分裂状态与它的具体风险。
