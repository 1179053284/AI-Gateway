# Skill 组合评审 v2（2026-10-07）：75 条历史建议 → 6 支精品

> 用户口径（本次纠正后）：**近一周、本项目所有会话 ID 下的全部「建议 skill」（含已归档、含已删除会话）→ 全盘识别 → 取长补短 → 给几支精品。**
> v1 的错误：只从会话转写里搜到 6 条「拟创建」就下了结论（取样面错）。本 v2 的数据源 = 界面右侧那批建议的**真身存储**。
> 本轮仍然：**只出方案，不写任何 skill 文件、不改源码**（memory `feedback-plan-before-code`）。
> 🔴 **v2.1 勘误（2026-10-07 核实轮）**：本稿有 7 处断言的盘上事实不符（变异门终局行字面 / `python_files` 已覆写 / 符号清点器不存在 / probe 为 11 支 / README 窗口单向 / 取数不能 tail / 判据 id 现存 4 个重复），另 3 处事故描述失实 ⇒ **以 `20261007-skill-verification-round.md` 为准**；§3 各支已按勘误修订，§3.4 补六条交叉冲突的边界裁定。

---

## 0. 数据源与完整性（可复算）

| 项 | 结果 |
|---|---|
| 存储位置 | `~/Library/Application Support/com.qodercn.app.stable/main.sqlite` 表 `skill_evolution_suggestions`（含 `source_session_id / skill_name / action / summary / rationale / confidence / status`） |
| 本项目条数 | **75 条**，覆盖 **19 个会话**，时间 **09-30 05:36 → 10-07 10:37** |
| 已归档会话 | 18/27 个会话为已归档，其建议一并计入（无过滤） |
| **已删除会话** | 孤儿建议（来源会话行已不存在）= **0**；`chat_sessions.deleted_at IS NOT NULL` = **0** ⇒ 当前无已删除会话，且**会话删除不会级联删建议**（该列无外键）⇒ 这条已查证，无遗漏 |
| 状态 | `pending` 69 + `evolving` 6 ⇒ **转换率 0/75：一支都没落盘**（`evolving` 的 6 条正是 v1 在转写里找到的那 6 篇方案，全部停在「等确认」/`SKILL_CONFIRMATION_REQUIRED`） |
| 每会话条数 | 多为 5 条、最高 9 条 —— 与界面右侧「四五个」吻合 |
| 全量清单 | `docs/changes/20261007-skill-suggestions-inventory.md`（462 行：簇分布 + 75 条明细表 + 逐条摘要/理由原文） |
| 复算命令 | 先拷库再查（勿直连活库）：`cp ~/Library/Application\ Support/com.qodercn.app.stable/main.sqlite* /tmp/mgdb/ && sqlite3 /tmp/mgdb/main.sqlite "SELECT COUNT(*) FROM skill_evolution_suggestions s JOIN chat_sessions c ON c.session_id=s.source_session_id WHERE c.cwd LIKE '%Model-Gateway%';"` |

**顺带两个副产物**（回答上一轮的两个疑问）：
- 「有一样的么」：**75 个名字全部不同**，但**语义高度重复** —— 见 §1 簇分布（比如 09-30 同一会话里 4 连发「UI 改版先验证」的同义建议；全周有 16 条各自独立地描述「一轮交付环」）。⇒ 名字不重复 ≠ 内容不重复，**判重必须按簇做**。
- 「是项目维度的么」：建议**按会话生成**；落盘位置是**用户级** `~/.qoder-cn/skills/`（本机无项目级 skills 目录）。⇒ "项目维度"只能靠 description 限定工程名实现。

---

## 1. 全盘簇分布（75 条按内容归档）

| 簇 | 条数 | 代表条目（最早→最晚） | 本周对应实做 |
|---|---|---|---|
| **A 交付环（一轮改动→交付）** | 16 | `model-gateway-delivery-round`(10-01) → `mgw-change-delivery-round`(10-02) → `mgw-ui-verification-ladder`(10-03) → `mgw-frontend-delivery-chain`(10-05) | 10-01~10-06 每一轮改动都在手工重导这条链 |
| **F 实盘只读核查 / 就绪审计** | 17 | `integration-transport-existence-audit`(09-30) → `gateway-live-state-probes`(10-04) → `gateway-model-dispatch-selection-audit`(10-05) | 10-04/10-05 整段会话（调度重试核查、自动化归属、可用性评估、修复映射） |
| **B 判据 / 门卫生与归因** | 9 | `serial-mutation-falsifiability-harness`(10-02) → `ui-gate-red-triage`(10-03) → `mg-criterion-advance-with-design-loop`(10-05) | 全周 160 处「变异」、10 处「空判据」、跨轮 stale 红 |
| **E 多角色 / 多代理面板** | 8 | `multi-agent-wave-delivery`(09-30) → `multi-role-product-verdict-research`(10-02) → `multi-role-architecture-audit`(10-05) | Q33 r1~r8、10-04 三轮交叉验证、10-05 架构审计八路 |
| **G 仓库 / 记账 / 术语维护** | 8 | `repo-process-cleanup`(10-01) → `island-readme-test-count`(10-04) → `shared-tree-hunk-commit-island-verify`(10-05) | 3 个纯计数 commit、岛式提交两笔、术语统一轮 |
| **C UI 量测 / 取证** | 6 | `cdp-headless-evidence`(10-01) → `ui-defect-to-gate-pipeline`(10-03) → `ego-probe-zero-window-hygiene`(10-04) | 额度格四轮实拍、0 窗口 PDF 兜底 |
| **H 目录接入 / 额度展示 / 桥接** | 4 | `port-account-plan-quota-display`(10-01) → `model-gateway-vendor-catalog-onboarding`(10-04) → `client-wasm-signing-bridge`(10-04) → `jethub-account-handoff`(10-05) | 两轮厂商入目录、wasm 签名腿、zcode→Jet Hub |
| **D 设计先行（改版前验证）** | 3 | 09-30 同会话四连发的三支（+1 条 `design-validate-before-code`） | 09-30 那轮的真实流程（地基→对撞→原型→判据先行） |
| **I 沟通与元** | 4 | `pm-plain-answer-format`(10-04) / `oil-ui-pro`(update,10-03) / 本轮两条(10-07) | 输出格式偏好、第三方 skill 维护、元流程 |

---

## 2. 逐簇判定（三把尺：① 本周被手工重导 ≥3 次 ② 机器还没钉住 ③ 载体是「顺序+命令+词表」）

| 簇 | 判定 | 依据 |
|---|---|---|
| **A 16 条** | ✅ **做成 P2（骨干）** | ① 最厚：16 条独立建议 + 每轮重导 + `.cursor/memory/runbook.md` 至今 **12 行空占位**（每轮用的命令链盘上无处可查，**这是承载缺口的直接证据**）；② 无任何文件/skill 承载；③ 纯工序。**合并口径**：16 条里 `mgw-change-delivery-round` 是 10-02 最后成形的一版（含撤证 + 记账 + 并行会话检查），`mgw-frontend-delivery-chain`/`mgw-ui-verification-ladder` 有最细的命令序列，`model-gateway-delivery-round` 有七步骨架。取三者并集 + 补第 10-06 才出现的两条（`ship-gate` `[1/2]` 红即 exit；后端改动未重启 `:8300` 不算交付，**pid/进程时刻不是重启判据**——`execv` 同 PID 换代） |
| **F 17 条** | ✅ **做成 P4** | ① 17 条、跨 10 个会话，10-04/10-05 的会话几乎全在此簇；② 散落的探针脚本（`probe_*.py` 12 支）没被串成一条链，字段口径（事件行是 `system_model` 不是 `model`）反复踩；③ 是取数姿势 + 判据矩阵。**合并口径**：`gateway-live-state-probes`（命令集）+ `gateway-model-dispatch-selection-audit`/`gateway-pool-selection-audit`（隔离实例复刻+假上游按身份头分派+事件对账）+ `isolated-instance-e2e`（MG_CONFIG/端口/lsof 杀进程）+ `mg-two-truths-live-diagnosis`（三面对账）+ `channel-constraint-verification`（聚合事件流水取代单发探针）+ `mgw-instance-liveness-proof`（上线判定） |
| **B 9 条** | ✅ **做成 P3** | ① 9 条；② 门自己没有「门的门」；③ 归因决策树。**合并口径**：`ui-gate-red-triage`（四分类）+ `gate-embedded-js-selfcheck`（内嵌 JS 抽取式校验 / `.mjs` 假绿）+ `serial-mutation-*` 两条（锚点唯一 / 清 `__pycache__` / 等长替换坑 / 串行独占）+ `mgw-gate-criterion-migration`+`mg-criterion-advance-with-design-loop`（**判据随设计前进：反转改写不删条目**、空判据、负向先剥注释）。**再补两类新账**：过期红（`SEC-renew` 跨 ≥2 轮只归因不修，`R5-verification.md:40,53`）与拆分/ESM 盲区（10-06 两个全站不可用 P0） |
| **E 8 条** | ✅ **做成 P5** | ① 面板在本仓复用概率极高（m6-r1..r4 / q33-r1..r9 / concept A1..A6 / 架构八路）；② 但**骨架已被钉住**（tech-design §22.9 波次表、四杆交付口径在项目 memory、接线护栏在 `test_v2_wiring_guard.py`）⇒ 只取没被钉住的三样：**brief 契约（基线度量内嵌 / ≥5 条做得好 / 判决词表 / 增量落盘 / `MG_CONFIG=` 写进第 0 条硬纪律）+ 救援决策树 + 撤改即红** |
| **C 6 条 + D 3 条** | ✅ **做成 P6** | ① 9 条；② 本地 `ui-pro` 只管设计判断，不含"改完怎么证明"；③ 量测姿势 + 成对判据。**边界写死**：ui-pro 出设计方向、本支出证据；量 Range 文本边缘而非盒子、布局判据成对（对齐+不溢出）、0 窗口取证走 `Page.printToPDF`+`qlmanage`、`Emulation.setDeviceMetricsOverride` 定视口后必须复位、入口"找得到"检查（默认态可见 + 用户词汇命名） |
| **G 8 条** | ⚠️ **做成 P7（次优先）** | 岛式计数/共享树 hunk 级提交/台账回写格式/术语批量改名，工序都对且都有 0.8+ 置信；但**频次低于 A/F/B**（记账每周 1~2 次、改名是一次性事件）。⇒ 落成一支，或作为 P2 的一节（推荐先作为 P2 的一节，等第二次真实需要时再独立） |
| **H 4 条** | ⚠️ **待触发备选** | `catalog-onboarding` 置信 0.9（全库最高）且跑过两轮、有用户明令的交叉验证前置 ⇒ 保留为备选；`client-wasm-signing-bridge`/`jethub-account-handoff` 是**一次性能力**（同族腿只有 trae/zcode 可能再来一次）⇒ 不建议现在做 |
| **I 4 条** | ❌ **不做** | `pm-plain-answer-format` 属**always-on 输出偏好** ⇒ 归 memory（已有术语四词 + 「先结论后表」惯例），做 skill 只会与 memory 双写；`oil-ui-pro` 是**第三方 skill 自身的 patch**，不属本项目；本轮两条元流程已落成文档（本文件 + inventory） |

**AI工作站（邻项目）30 条**：已顺手导出，其中 `jet-hub-gateway-client-troubleshooting`/`zcode-custom-provider-config`（会话「排查网关调用失败」）与本项目相邻，其余属 DSH 插件工程 ⇒ **不并入本项目组合**，需要时单独评。

---

## 3. 最终组合：6 支精品（3 支 P0 先落，3 支 P1）

> 统一约束：本机只加载 `~/.qoder-cn/skills` 与 `~/.agents/skills`（无项目级目录）⇒ 项目锚定靠 description 写死「Model-Gateway 工程」；正文只装**顺序 + 命令 + 词表 + 判据**，教训条文一律指针回 `.cursor/memory/pitfalls.md` / `docs/changes`，不复述（避免第二套真相）。

### P2 · `mgw-delivery-round`（← 簇 A 16 条合并）
- **description**：Model-Gateway 一轮改动（前端/后端/配置）从认领到交付的可复跑环：并行会话检查 → 硬约束 → 阶梯验收（语法→静态门+变异→真机门→全量）→ 双向撤证 → 计数与台账收敛 → 归案 → 上线/重启判定 → 未验证清单。触发：改完复验 / 验收 / 自验收 / 合并 main。不适用：纯调研方案轮、批量验收积压 commit（走 `batch-acceptance-merge`）。
- **主干 9 步**（每步给逐字命令 + 终局口径行）：
  1. 开工：`git status` + 并行会话探测（mtime / `git diff --numstat HEAD -- <file>`，**引用前当轮重测**）+ 被监视文件 md5 基线；
  2. 阶梯语法：`cp x.js /tmp/x.mjs && node --check /tmp/x.mjs`（**`node --check x.js` 对 ES 模块假绿**，pitfalls 两处实证）+ 门内嵌 JS 抽取校验（见 P3）；
  3. 静态门：`node bianyiandhuanjing/scripts/verify_accounts_ui.mjs`（+ `--mutation`）；v2 门须先 `make_overview_payload.py <tmp>` 取载荷（裸调恒 exit 2）；
  4. 全量：`bash bianyiandhuanjing/scripts/ship-gate.sh --gates`；🔴 **[1/2] 非 0 直接 exit ⇒ [2/2] 根本没跑**，红时必须同树手工复跑 `[2/2]` 才能报其余门号；`--skip-legs` 是调试开关不得作交付口径；
  5. 真机门：`verify_accounts_ui_live.py --port 84xx`（隔离实例 + 假上游）；跑前=跑后 md5 一致才算该轮读数有效；
  6. 撤证：每条改动「退回必红且红在该红那条 → 复原必绿 → md5 逐字节」；
  7. **计数与台账一次收敛**：`git archive HEAD` 岛式快照 `--collect-only` 取提交树值（🔴 收集面**含** `tests/verify_v*_repro.py` 五支，`coding/pyproject.toml:54` 已覆写 `python_files`）→ 双语 README 同时改 → 守卫窗口是**单向区间 `[collected−20, collected]`**（`test_v2_readme_claims.py:73-74`，不许虚报）→ 本机守卫必红要**报备 + 写明红因 + 登记债务**（禁改数字蒙绿）；台账模板 §0 用户原话 → §改动面/根因 → §判据 → §撤证 → §门行 → §未做未验 → §归案；🔴 **所有终局数一律 grep 关键词取（合计：/可红），不许 tail**（失败清单打在合计行之后）；
  8. 归案：spec 版本号取下一个空位（被并行会话占了就顺位 + 写明改号原因）+ AGENTS 状态链 + memory；
  9. **上线判定**：纯前端 `no-store` 刷新即生效；**含后端改动 ⇒ 未重启 `:8300` 不算交付**，且 `execv` 同 PID 换代 ⇒ **pid/进程时刻不是判据**，用「幂等零写盘请求的回执新键 + 配置 md5 跑前=跑后」判新码已加载；无法只读证明时判「未上线」并报备分裂状态（新前端+旧后端）。

### P3 · `mgw-gate-hygiene`（← 簇 B 9 条合并 + 10-06 新账）
- **主干**：① 三门逐字跑法与终局行格式（🔴 字面以门源码为准：变异门为 `可红 X/Y；N 项 BAD` 或 `可红 X/Y；X 条判据全部可证伪（expectGreen 型…）`，`verify_accounts_ui.mjs:2545-2547`）；② 改门后三步自检（内嵌 JS 按 runner 同姿势抽出 → `.mjs` → `node --check`；`py_compile`；id 唯一性）；③ 新增判据前预检：`ck()` id 全局唯一（`grep -o 'ck("[A-Za-z0-9]*"' bianyiandhuanjing/scripts/verify_accounts_ui_live.py | sort | uniq -d`；🔴 实跑现存 4 个重复 `D6a/D6b/MS2f/MS8` = 已登记缺陷，lint 对它报红并注明即可，不代改门）+ 变异锚点命中恰 1 次；④ **报红四分类归因表**（实现缺陷 / 判据读点搬家 / 判据空转＝没有对象 / 判据假红或结构性不可能绿），每格给症状-确认-处方-本仓实证；⑤ 归因工具链：`stripComments` 失步、冻结树到临时目录（副本须在与门脚本相同相对位置）、`git show HEAD:<file>` 判既有还是本轮引入；⑥ **判据随设计前进**：反转改写不删条目、理由写进判据、重定锚后复跑看命中数；⑦ 新增第五类 **过期红**（>1 轮只归因不修的合法红必须改写或删判据对象）；⑧ 拆分/重构类改动的验收必须含逐模块 `node --input-type=module` `import()` + **符号清点（自带配方**：去注释/去字符串后比对「段内引用 ∩ 全部导出 − 段内定义 − 已 import」，含**子模块互相引用**层）+ 真浏览器逐页 —— 🔴 该清点器**盘上尚不存在**（10-06 仅以台账脚本形态存档，`E2E-20261006-arch-audit-s1-s5.md:362-365`），落盘时须自带或先写脚本并实跑。
- **边界**：只改门/加判据/门报红时用；界面呈现缺陷的量测走 P6；验收器（门自己）坏 vs 产品坏的归因诊断是本支的唯一出口 —— **顺带收口 `batch-acceptance-merge` 里指向不存在的 `acceptance-verifier-false-red` 的悬空引用**（见 §6-D3）。

### P4 · `mgw-live-audit`（← 簇 F 17 条合并）
- **主干**：① 只读基线（`GET /health`、`/openapi.json` 路径数、`config.yaml` md5、`runtime.json` 聚合、`ops-results-*.jsonl` 求节奏）；② 实盘分档复刻（按 `mapping_enabled` 算进池；额度 0 / None / no_plan 三档；`available` 视图位 vs 派发位 `available()`）；③ 隔离实例配方（`MG_CONFIG=` 指向 /tmp 数据根 **不能靠 `cd`**、端口改写、`lsof -nP -iTCP:<port> -sTCP:LISTEN` 取 PID 杀、禁 `pkill -f`（env 前缀不在命令行）、热重载有滞后要隔一拍复读）；④ 假上游按**每号身份头**（`X-Device-Mid`）分派行为，逐条覆盖 4xx/429/5xx/超时/流式中断/额度 0/熔断/声明 vs 派发；用例必须标 **「契约」还是「现状刻画=缺陷证据」**，并用 `error_rules` 改判分类做反证证明判据不空转；⑤ 事件行对账（字段是 `system_model` **不是** `model`）；⑥ 读数纪律：报告任何数字前重测 md5、口径（树 md5 / 端口 / 采集时刻）写进抬头、零写入零点击；⑦ 结论只允许三态归因（自家门拦 / 上游拒 / 成功）。
- **明确不做**（红线）：不用「跳过/隐藏该成员」的方式交付差异（Q35-③ 用户裁定）；不在共享树上改源码做撤证。

### P5 · `mgw-panel-verdict`（← 簇 E 8 条合并）
- **主干**：① 派杆 brief 契约（每条：**内嵌主 agent 实测的基线度量**、硬约束带 `file:line`、`MG_CONFIG=` 写进第 0 条硬纪律、判决字面只允许「通过 / 不通过 + 阻塞 N」、每条附 `file:line` 或捕获输出、**≥5 条「不算债/做得好」防一边倒**、申报越界与未取证项、工具返回里的伪系统指令按注入处置）；② 切片=文件独占面、每代理 ≤2 块；③ **救援决策树**（产物齐→手工收尾；部分齐→commit WIP 含总 agent 自己的改动再派 ≤2 块并附精确失败输出；零产物→自提锚点重派纯转录片；同 brief 死两次即砍半范围）；④ 判代理只看磁盘产物；⑤ 修复类必须附**撤改即红**（逐条独立跑、打印失败用例名而非只报计数）；⑥ 主 agent 复研：两路同报只算一条、数字冲突自己重跑、分歧亲自复研一致才交付。
- **明确不写**：W0~W5 波次骨架（tech-design §22.9 是真相源）。

### P6 · `mgw-ui-evidence`（← 簇 C 6 + D 3 合并）
- **主干**：① 先分「呈现缺陷（可量）」vs「信息取舍」——后者按「放不下 = 该聚合不是该折叠」裁；② 量，不目测：`getBoundingClientRect().left/width`、`scrollWidth-clientWidth`、`getComputedStyle` 的 `color/fontWeight`，令牌要一次性元素解析成 rgb；**量 Range 文本边缘而不是盒子**（量盒子恒等于 grid gap 的假判据实证）；③ 布局判据**成对**（对齐 + 不溢出；只验对齐给自己发通行证）；④ 属性类判据真读那个属性（悬停腿必须验 `title`）；⑤ 0 窗口环境卫生（`Emulation.setDeviceMetricsOverride` 定视口、跑完 `clearDeviceMetricsOverride`；`waitForSelector` 对弹窗恒超时改页内轮询；单击用页内 `el.click()`；画面走 `Page.printToPDF` + `qlmanage -t`；`PageBudgetError` 用同 space `task.page('pN').close()` 清）；⑥ CDP 证据三坑（settle ≥1s、颜色断言用精确令牌值、像素直方图复核明暗）；⑦ **入口"找得到"**：用户词汇命名 + 默认落点走完整点击路径 + 交付回复写明导航路径；⑧ 改版前的设计先行**不在此支重写** ⇒ 指针：本地 `ui-pro`（其 `SKILL.md:56` 十二步工作循环已含小样/对比页/独立评审），本支只负责"改完怎么证明"。
- **边界**：设计方向探索走本地 `ui-pro`（合规模式）；浏览器驱动细节走 `ego-browser`。

### P7 · 备选/次优先
- `mgw-repo-bookkeeping`（簇 G 8 条）：岛式计数、hunk 级提交（`git apply --cached --recount` / `hash-object`+`update-index --cacheinfo`）、台账/规范回写格式、术语批量改名工序（**还原存证行必须最后做、且还原过的文件不再回扫**）。**建议先作为 P2 的第 7 步展开，第二次真实需要时再独立成支**。
- `mgw-catalog-onboarding`（簇 H，置信 0.9）：官方取证 → 多子 agent 逐格复核 → 写 `BUILTIN_ENTRIES` + 图标双向在册 → 定向测试 → 重启 + 映射 + `/v1/models` + 真实调用矩阵（流式/首条 system/`max_tokens≥2048`）→ 岛式计数 → 文件粒度提交。**待触发**（下次加模型时启用）。

### 3.4 六条边界裁定（核实轮发现 6 处同工序多主人，落盘时按此写进各支 description）

1. **撤证**（改坏→必红→复原）→ 单一主人 **P3**（配方含 `__pycache__`/等长替换/串行独占）；P2 只写"自己这一刀按 P3 配方"、P5 只写"委托修复按 P3 配方"。
2. **门调用** → P2 = **跑**（不改门）；P3 = **改/加判据/门报红归因**；命令字面只存 P3。
3. **`MG_CONFIG` 隔离实例配方** → 单一主人 **P4**（含 lsof/端口/热重载滞后）；P2/P5 引用。
4. **岛式计数** → 先折进 **P2 第 7 步**，P7 独立时再抽。
5. **`--skip-legs`** → 默认跑全腿；仅当"额度联网腿会真实出站且未获批准"时可跳过，且该轮**不得宣称已交付**并登记未跑腿。
6. **触发路由**：有未提交改动=P2｜只读状态疑问=P4｜渲染几何/样式=P6｜门报红或改门=P3｜多角色评审=P5｜提交/账本/改名=P7｜积压 commit 批量验收=`batch-acceptance-merge`；各支 description 写明"若另一支更贴合则转交"。
   另：所有 skill 的"归案/写回"步骤只能写 `.cursor/` 与 `docs/`（`.cursor/rules/mg-directory-layout.mdc:13`：**其它 `.xxx` 工具目录不维护、不写入**）。

---

## 4. 明确不做（含理由）

| 条目 | 理由 |
|---|---|
| 品牌 tile / 图标审计类 | 已被 `test_v2_product_icons.py`(22 例) + `test_v2_vendor_icons.py`(15 例) 钉死 ⇒ 再写文档 = 第二套真相（尺子②） |
| `pm-plain-answer-format` | always-on 输出偏好 ⇒ 归 memory/rules（术语四词已在册），skill 化只会双写 |
| `oil-ui-pro`(update) | 第三方 skill 自身维护，不属本项目 |
| 09-30 的同义四连发（UI 改版先验证 ×3 + design-validate ×1） | 合并进 P6 的第 ⑧ 条，不各立一支 |
| `multi-agent-wave-delivery` 原样 | W0~W5 已被 tech-design §22.9 + 项目 memory 钉住，原样做会与 `batch-acceptance-merge` 抢触发 ⇒ 只取 P5 的模板层 |

---

## 5. 落盘顺序与机制约束

1. 建议批次：**P2 → P3 → P4**（每轮都付的钱）→ 再 **P6 → P5** → P7 按需。
2. 🔴 同一会话内第二次 `skill_manage create` 会 `SKILL_TARGET_MISMATCH`（memory 在册）⇒ 6 支 = 6 个会话轮次；`skill_manage` 只能写 `SKILL.md` ⇒ 带 `scripts/`（P6 探针）或 `references/`（P3 成因索引、P5 brief 模板）的形态需要**你授权直接写文件**。
3. 🔴 10-03 那次 `skill_manage(action=create)` 连续 3 次返回 `SKILL_CONFIRMATION_REQUIRED`（`pendingInteractionCount=0` 也照拦）⇒ 需要你给一句**成文授权**，别逐支问。
4. 每支落盘后当场按 `skill-creator` 清单自检（单行 description ≤1024、目录名=name、无 `TODO:`、正文 <500 行、无多余文件），并在**新会话**试触发一次（本会话无法验证自动触发，不越口径）。

---

## 6. 待你裁决

| # | 问题 | 选项 | 推荐 |
|---|---|---|---|
| D1 | 批次 | ① 先 P2+P3+P4 ② 6 支一次 ③ 只做 P2 | **①**（本轮都在付的三笔钱先收） |
| D2 | 写入通道 | ① 只用 `skill_manage`（6 轮、单文件）② 授权 `Write` 直落 `~/.qoder-cn/skills/<新名>/`（可带 scripts/references，只新建不改已有两支） | **②**（P3/P5/P6 的形态依赖它） |
| D3 | 是否顺手收口 `batch-acceptance-merge` 的悬空引用（改它的 description/正文指向 P3） | ① 收口 ② 只声明不动别人 | **①**，但该文件属 codex-coding 工程，需你单独点头 |
| D4 | `.cursor/memory/runbook.md` 空占位 | ① 补指针 + 三门逐字命令 ② 继续空着 | **①**（skill 给 AI、runbook 给人复制） |
| D5 | P7 两支（记账/目录接入） | ① 现在做 ② 备选待触发 | **②** |

---

## 7. 未验证 / 未做（如实）

- **本轮零 skill 写入、零源码改动**；只落两份文档（`docs/` 被 gitignore，不进提交）。
- 10-06 那天的**会话内容**不在本 CLI 存储（该日 0 段），判定改用 git log + 台账；但**建议表里有 10-05 与 10-07 的条目、无 10-06 条目** ⇒ 10-06 若有建议，本库未记录（系统未生成）。
- 已删除会话：`chat_sessions` 中 `deleted_at` 非空 = 0、孤儿建议 = 0 ⇒ 「含已删除会话」已覆盖；**若曾有过被硬删除的会话，其建议是否曾被级联清除无法追溯**（当前表内无 FK，但更早版本可能有）——如需彻底排除，只能靠 10-05 之前的备份比对，本轮没做。
- 簇归并是**语义人工判定**（`20261007-skill-suggestions-inventory.md` 的簇分布由脚本关键词映射生成，个别条目归簇可争论；判定表里每条都给了代表条目供你复核）。
- P2~P6 的正文均**未实跑**（本轮只设计形态）；落盘时按 `skill-creator` 要求逐支实跑自检。
