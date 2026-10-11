# PM 验收面板 — 第十二轮（2026-09-28）

> 面板：资深产品经理。只验收，不改生产代码/测试/前端源码。
> 工作区基线：`git status --porcelain | wc -l` = **85**（开工时；并行会话存在，收工再测）
> HEAD = `5158cbc Remove internal spec documents from repository`

## 0. 本轮验收面（任务书四条 + 三门复跑）—— 速览
> **结论：不通过（阻塞 4 条）**，全文见 §6 / §7。
| # | 验收项 | 结论 | 证据 |
|---|---|---|---|
| A | 三门数字自己复跑 | ✅ 逐字一致：pytest 715 passed / 前端实测 84 项全绿 / `--mutation` 可红 104/104 / 后端出口 12/12 | §1.1–1.3 |
| B | S-36 指路页名分叉（→ RESOURCE_PAGE + J3 + 派生 owners） | ✅ 已收口 | §4 |
| C | S-37「先登录工具，再配网关」vs PRD Q25-⑩ + 双语对称 | ✅ 已收口（zh 107-109 / en 107-110；双语各 7 条 Notes、10 个 h2 对齐） | §5 表 |
| D | S-39 README 数字/版本/docs 链接 | △ 版本（0.2.0 三处一致）与链接（0 命中）收口；数字 710 vs 我实测 715（判据容差内） | §5 表、N-12-2 |
| E | S-40 未知按最坏是否锁死 / 删文件出口三处可达 | ❌ 不锁死（实测删文件即解、给绝对路径），但 README 零条款 + 红点零亮 + **数字串形态仍 fail-open** | §2.2 §2.3、B-12-1 B-12-4 |
| F | 拒跑口径四出口一致性 | ❌ 四套说法：日志与 CLI 第一行诚实；界面「最近错误」被追加假钟点 + 同行徽章「无需处理」；CLI 第二行「到点自动恢复」为假；红点不亮 | §3 表、B-12-2 B-12-3 |
| G | 按文案真的走一遍（自建临时实例 + HTTP 取回 resources.js） | ✅ 走通：「模型列表」板块 ×6、`#rv-addmap` ×2 真在那一屏 | §4.2 |

## 1. 三门复跑（原始输出，逐字抄本面板自己的运行）

### 1.1 pytest（已复跑）
命令：`MGW_ZCODE_ACCOUNTS=/tmp/mgw-pm12-none.json .venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest -p no:warnings`
```
715 passed in 149.96s (0:02:29)
```
→ 与账本宣称的 **715 passed** 一致（本面板独立复跑）。

### 1.2 后端出口门（本面板独立跑两轮）
```
$ MGW_V2_VISIBLE_DIR=/tmp/pm12-fixture .venv/bin/python scripts/ui_verify_v2_visible.py
  fixture=/tmp/pm12-fixture/overview.json（本轮新写，别拿旧文件当本轮结论）
实测 84 项，通过 84 项，失败 0 项
后端出口实测 12 项，通过 12 项，失败 0 项
$ .venv/bin/python scripts/ui_verify_v2_visible.py --mutation   （另跑一次）
可红 104/104；每条断言都有对应变异
后端出口实测 12 项，通过 12 项，失败 0 项
```
→ 与账本宣称「后端出口 12/12」一致。

### 1.3 前端门（用我自己 fixture /tmp/pm12-fixture/overview.json）
```
$ node scripts/verify_v2_frontend.mjs /tmp/pm12-fixture/overview.json --mutation
可红 104/104；每条断言都有对应变异      （✓ 计数 grep -c "✓" = 104）
```
→ 三门数字与本面板复跑**逐字一致**：pytest 715 / 前端实测 84 / 可红 104 / 后端 12。
→ 附加对照：把 README 承诺的复现命令 `.venv/bin/python -m pytest -q` 与我实跑的 715 条并列 →
README 写的 **710 passed**（同一天，漂移 5 条）；判据 `test_readme_test_counts_are_not_stale`
容许 ±20 且"文档 ≤ 真实"，故不判阻塞，登记 N-12-4。

### 1.4 我自己造的运行态探针（/tmp 下临时 MG_CONFIG + MGW_ZCODE_ACCOUNTS，`data/` 零写入）
探针脚本：`/tmp/pm12probe/probe.py`、`states.py`、`probe3.py`（均在 /tmp，未落仓库）。
临时实例 uvicorn 随机端口起停；`:8300` 全程未触碰（见 §7 运行态说明）。

## 2. 熔断新口径复核（三态 + fail-closed）

### 2.1 三态矩阵实测（`/tmp/pm12probe/states.py`，15 种形态逐个喂 `CooldownManager`）
```
形态           active                    untrusted                        reason()
不存在           False                       None                         ''
非 JSON          True   JSON 解析失败（半写入或被手改坏）         熔断状态文件读不动（…）→ 按熔断拒跑；确认无风控后删除 …/circuit.json 即可解除
空文件           True   JSON 解析失败（…）                    同上
数组             True   内容不是 JSON 对象（是 list）           同上
字符串           True   内容不是 JSON 对象（是 str）            同上
缺键             True   until_ms 缺少该字段（或被写成 null）    同上
null             True   until_ms 缺少该字段（…）               同上
布尔 true        True   until_ms 被写成布尔值 True，不是时间戳   同上
布尔 false       True   until_ms 被写成布尔值 False，…         同上
NaN              True   until_ms 是非有限数字（NaN/Infinity）   同上
Infinity         True   until_ms 是非有限数字（…）             同上
字符串数字       False                      None                         ''          ← 🔴 见 B-12-1
超 24h           True   until_ms 不合理（超过「现在+24h」）…     同上
合法未到期        True                      None   ZCode 风控熔断（30min，全局），至 19:20
合法已过期        False                     None   ZCode 风控熔断（30min，全局）
```
→ 三态方向（不存在=已解除 / 读不动=未知按熔断 / 可读=按文件）**14/15 与设计一致**；
→ 拒写方向实证（`/tmp/pm12-refuse`）：布尔坏值时 `mark_called()` 后盘上仍是 `{"until_ms": true}`，
  并打一条「本次**不写盘**：写下去会把跨进程的熔断凭据整盘抹掉」→ S-53 的"不销毁别的进程凭据"**成立**。

### 2.2 🔴 B-12-1（阻塞）被写成**字符串**的时间戳是漏网的 fail-open，且零日志
新口径原文承诺"坏值（缺键/null/**字符串**/布尔/NaN/超 24h/非对象/非 JSON）= 未知，一律按熔断拒跑"；
`_ms_problem()` 的 docstring 也自称判坏形态含"字符串"（`quota.py:347-348`）。实测**只对非数字字符串成立**：
`quota.py:364-365` 用 `float(raw_value)` 判数值，`float("1770000000000")` 完全合法 → 当成"已过点"放行。

本面板实测（两进程交错写盘的真实形态，A 正熔着 30 分钟）：
```
A 建立熔断，盘上 until_ms = 1790595896455.39
B 读到字符串时间戳 → active = False | untrusted = None | reason = ''
B mark_called 之后盘上 until_ms = 1770000000000.0 （A 的 1790595896455.39 是否还在）
=> 凭据是否被销毁: True
```
即：一次把 `until_ms` 写成带引号的数字（手改 / 半写入后残留 / 别的序列化器给字符串），
① 熔断在**所有进程**里当场消失（`active()=False`，模型转发立刻打回风控观察期账号）；
② `mark_called()` 不再受"拒写"保护（因为 `problem is None`），**整盘覆盖**销毁跨进程凭据；
③ 全程**零 WARNING**（连 2.1 的 `节流字段读不动` 那条都没有）。
这正是第十一轮 eng-A BLK-2/BLK-3 的同一根因（可被 coerce 成合法数的坏形态逃过判坏）——
布尔那一半修了，字符串这一半没修，且它逃过的正是本轮新口径自己承诺覆盖的形态。
判据缺口：同一判据的 `bad_forms`（`test_v2_circuit.py:1074-1079`）含 `"abc"` 与整份级
  `"just-a-string"` —— **全是非数字串**，没有"合法时间戳被写成字符串"这一形态，所以 715 条全绿也抓不到它。

### 2.3 「未知按最坏处理」会不会把用户锁死？——**不会锁死，但会"锁死且没人说"**
- 手动出口**真的有效**（实测）：坏值时 `mgw zcode claim` rc=**3**；`rm circuit.json` 后同一环境 rc=**1**
  （熔断解除，只剩凭据缺失失败），`active()` 由 True → False：
```
[C] 用户执行了出口（删文件）之后，同一实例再看一眼
  circuit.json exists = False
  active() = False | untrusted = None
[D] 文件缺失 = 已解除（三态①）
  active() = False | reason() = ''
```
- 措辞**可执行**：`reason()` 与 CLI 第二行都打印**绝对路径**（`/private/tmp/pm12-circ/upstream/zcode/circuit.json`），
  不是"删掉状态文件"这种空话 ✔。
- 但三处承诺只到两处半：CLI ✔（`cli_zcode.py:249-254`）、界面 ⚠（只有「最近错误」一格，见 §3）、
  **README ✘**：全文 `grep -n "circuit\|熔断\|breaker\|风控" README.md README.zh-CN.md` 只命中退出码 3 那两行，
  **没有任何一处**说明"状态文件读不动会按熔断拒跑、删掉它即可解除"（见 B-12-4）。
- 时间维度不锁死：未知档按整档 30min 挡资源（`remaining_seconds()`=1800.0 实测），到点资源回池；
  但运营闸门（claim）在文件被删之前**永久拒跑**，而界面上那条痕迹只在 30 分钟内存在 → 见 N-12-6。

## 3. 四出口口径一致性（拒跑那一档）

同一件事（"熔断状态文件读不动 → 按熔断拒跑 → 需要用户删文件"），四个出口**四套说法**：

| 出口 | 实测原文 | 判定 |
|---|---|---|
| ① 网关日志 | `熔断状态文件 …/circuit.json 读不动：until_ms 被写成布尔值 True…→ 保持现有内存态、**拒绝整盘覆盖**，并按熔断拒跑（宁可拒跑也不冒险）。确认无风控后删除该文件即可解除`（`quota.py:465-467`） | ✔ 基准口径 |
| ② `mgw` CLI 第一行 | `⚠ 熔断状态文件读不动（…）→ 按熔断拒跑；确认无风控后删除 <绝对路径> 即可解除 —— 本轮未对上游发起任何领取`（rc=**3**） | ✔ 同句同码 |
| ② `mgw` CLI 第二行 | `状态文件：<路径>（**到点自动恢复**；删除该文件可立即放开后续领取…）`（`cli_zcode.py:252-254`） | 🔴 **B-12-3 自相矛盾**：未知档没有"点"可到（`reason()` 正因如此**不给钟点**），却对用户承诺"到点自动恢复"；实际不删文件=**永不恢复** |
| ③ 总览「最近错误」列 | `熔断状态文件读不动（until_ms 被写成布尔值 True…）→ 按熔断拒跑；确认无风控后删除 <路径> 即可解除**，至 19:42**` | 🔴 **B-12-2 编造钟点**：`resources.py:214-217` 见 `status==cooldown 且 remaining>0` 就追加 `，至 HH:MM`，把"时长未知"渲染成"19:42 恢复"，与 CLI/日志"不给钟点"直接相反 |
| ③ 同行「冷却中」徽章 | `1800s 后自动回池，**无需处理**`（`dashboard.js:132-133`，实测 `status=cooldown / cooldown_ms=1800 s`） | 🔴 同屏两格互相打脸：左格说"无需处理"，右格说"确认无风控后删除该文件" —— 用户必须二选一相信 |
| ④ 顶栏红点 | `ops_failed_unread = 0`（实测，未知拒跑轮）→ **不亮** | 🔴 归入 B-12-4：`_circuit_gate` 判 `inactive`（`zcode_claim.py:145`），而红点只数 `failed`（`admin.py:122` + `runner.py:13`）；界面也**不消费** `inactive_reasons`（`grep -rn "inactive" api/admin.py web/static/js/**.js` → 零命中）。**隔离实测**：构造一条纯 `inactive`（未知拒跑文案）的运营结果落盘后 `unread_failures = 0` → 顶栏红点 0（`/tmp/pm12-redot`，见 §6 B-12-4） |

补充：删文件后，运行中的实例那一行**仍继续显示**"…请删除 <路径> 即可解除，至 19:42"（实测 `[C] status=cooldown cooldown_ms=1800`），
即指令文案被当成历史记录冻结 30 分钟，用户照做之后界面不会给他任何"已生效"的反馈 —— 同属 B-12-2。

## 4. 指路文案走查（S-36：真的按文案走一遍）

跑法：本面板自己起的临时实例（`MG_CONFIG=/tmp/pm12-circ/config.yaml`，uvicorn 随机端口），
既取 `/admin/api/overview`，也**从 HTTP 取回线上那份 `resources.js`**（不是读本地磁盘副本）。

1. 文案本体（`/tmp/pm12-visible.out` 的 `[配置告警]` 两行，与 overview.warnings[] 同源）：
```
① 1 个系统模型未配置任何资源…—— 到「模型资源」页选中要承接的资源，在「模型列表」里添加映射指向该系统模型（empty-model）
③ 1 个已启用模型的资源映射全部不可用…—— 到「模型资源」页启用对应资源，或在同一页的「模型列表」里给该模型更换映射（zombie-model）
```
   → 页名 = `RESOURCE_PAGE`（`resources.py:225` = 「模型资源」页），导航里真存在该项
   （`index.html` `data-page="resources"`、`main.js:23` `resources: { title: "模型资源", group: "资源配置" }`）✔
2. 那一屏真有那个控件（HTTP 实取的 `/js/pages/resources.js`）：
```
板块标题出现次数 模型列表 = 6 | #rv-addmap = 2
addmap 按钮标签: ['<button class="btn btn-soft" id="rv-addmap" style="margin-top:12px">${PLUS}添加模型</button>']
```
   路径可走通：左子侧栏点某供应商 → `drawDetail()`（`resources.js:203-275`）渲染「模型列表」板块 →
   板块内 `#rv-addmap` 就是添加映射行的入口（`resources.js:572` 绑定 push 一条 `{vm,sys}` 草稿）。✔
   交叉印证：`models.js:361` 的提示也写「到「模型资源」页编辑资源添加映射」——**两侧文案同页**，S-36 的改向成立。
3. ⚠ 残留（登记 N-12-1）：文案说"添加**映射**"，按钮字面是「添加模型」；而「资源池设置」页
   （`models.js:84`）另有一个「＋ 添加模型」= 从厂商目录新建系统模型，**同一字面两种动作**，
   用户刚被从那一页指过来。J3 只按控件标记判归属（`test_v2_cli.py:347-354` 的 `rv-addmap`），
   不看按钮可见文字，所以这层错位门抓不到（与第十一轮登记项 S-51 余下半同源）。

## 5. README 承诺抽查（逐条自己核，不替实现者圆场）

| 承诺 | 本面板核法 | 结论 |
|---|---|---|
| 版本 v0.2.0 | `mgw --version` → `mgw 0.2.0`；`pyproject.toml:3` `version = "0.2.0"`；`__init__.py:6` 同 | ✔ 三处一致（S-39 已交付） |
| 测试 710/710、"710 passed as of 2026-09-28" | 我实跑 `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest -p no:warnings` → **715 passed** | ⚠ N-12-2：同一天宣称 710、实为 715（徽章 `tests-710%2F710` 同漂）；在判据容差（≤真实、±20）内，但 README 的话术是"数字会由 `test_v2_readme_claims.py` 钉住不漂"，同日即漂 5 条 = 这句承诺的口径其实容许 20 条漂移 |
| 不引用 gitignore 的 `docs/`、`.cursor/` | `grep -c "docs/\|\.cursor/" README.md README.zh-CN.md` → **0 / 0** | ✔ S-39 已交付 |
| 端点清单（`/v1/chat/completions`、`/v1/images/generations`、`/v1/messages`、`/v1/models`） | `grep @router` → `openai_compat.py:38/125/262`、`anthropic.py:316`；双语端点串集合完全相同 | ✔ |
| 调度 x=2 / y=2 / m=3、单次尝试 60s、总预算 300s、SSE 心跳 15s、api 冷却 60s / plan 对齐 5h | `schemas.py:103/104/105`、`:78`、`:79`、`:79 heartbeat`、`:109`、`:110 (18000)` | ✔ 逐条对上 |
| `mgw zcode claim` 退出码 0/1/2/3 + "3 在 `mgw setup` 下另有含义（写盘失败）" | 实测坏熔断文件 → `RC=3`；删文件 → `RC=1`；`cli_setup.py:206` 写盘失败 `return 3` | ✔ 真实 |
| 「先登录工具，再配网关」（PRD Q25-⑩） | PRD `docs/specs/prd.md:599` 原文 = "不做工具的登录态管理——`mgw setup` 只能写配置，不能替用户登录；文档须写明「先登录工具，再配网关」"；zh `README.zh-CN.md:107-109`、en `README.md:107-110` | ✔ 语义对齐；双语**对称**（各自 7 条 Notes、10 个 h2 小节、同一句"不代登录/只写配置/先登录再跑 setup"三要素都在） |
| "被隐藏的模型会在总览以横幅说明数量与原因，不会静默消失" | 我的实例实测 warnings ①③ + 后端门 `✓ /v1/models 不含零映射模型 / 不含不可服务模型 / 保留可服务模型` | ✔ |
| "Web console：Overview, resources, system models, dashboard, request logs, API access and settings"（七页） | `PAGE_META` 8 项 = 七页 + `templates: 模板预览`；`index.html:66-86` 侧栏实含「模板预览」分组 1 项 + 「需求预演」分组 3 项（演示数据） | ⚠ N-12-4：对外 README 只承诺七页，实际交付的控制台多两组开发/预演导航；唯一解释住在 `docs/specs/frontend-spec.md` v2.11/v2.12，而 `docs/` 已被 gitignore → clone 用户看不到任何说明 |
| 熔断状态文件读不动 → 按熔断拒跑 + 删文件解除（本轮新口径） | `grep "circuit\|熔断\|breaker\|风控"` 双语 README → 只命中退出码 3 两行 | 🔴 零条款（并入 B-12-4） |
| 流式取消透传 / failover-continue 行为 | 本轮未做真实上游调用（纪律禁止） | 未验证（本轮）；README 自己在 171 行也标了 ZCode/Anthropic 需真实凭据项为"未验证"，口径诚实 ✔ |

## 6. 阻塞 / 登记清单

### 阻塞（4 条，全部落在本轮"新口径"这一件事上）
| # | 一句话 | 落点 | 复现/证据 |
|---|---|---|---|
| **B-12-1** | `until_ms` 被写成**数字字符串**时 `float()` 吞成合法时间戳 → 未知档当场变"已过期"放行，且 `mark_called()` 不再受拒写保护、**整盘覆盖销毁跨进程熔断凭据**，全程零日志；与本面板承诺的"字符串=坏值=一律拒跑"直接相反 | `quota.py:364-365`（`_ms_problem` 数值分支）＋ docstring `:347-348` 自称覆盖"字符串" | §2.2 输出：`B active=False / untrusted=None / reason=''`、盘上 `1790595896455.39 → 1770000000000.0`、`凭据是否被销毁: True`。判据缺口：`test_v2_circuit.py:1074-1079` 的 `bad_forms` 只有非数字串
  （`{"until_ms": "abc"}`）与整份级 `"just-a-string"`，**不含"合法时间戳被写成字符串"**这一形态，故 715 条全绿抓不到 |
| **B-12-2** | 未知档在**界面出口被编造成"有钟点、无需处理"**：「最近错误」尾随 `，至 19:42`，同行徽章写 `1800s 后自动回池，无需处理`，与 CLI/日志"不给钟点 + 请删文件"相反；用户删掉文件后该行仍原样挂着 30 分钟（指令已执行完仍在喊话） | `resources.py:214-217`（cooldown 一律追加钟点）＋ `dashboard.js:132-133`（无需处理）＋ `quota.py:621-623`（原因串被当历史记录冻结） | §3 表③行与"补充"段（`/tmp/pm12probe/probe3.py` 的 `[B]`/`[C]` 原文） |
| **B-12-3** | CLI 第二行对用户承诺「**到点自动恢复**」，而未知档按定义没有恢复时刻、不删文件就永不自动恢复 —— 同一屏两行自相矛盾，用户会等一个不会来的自动恢复 | `cli_zcode.py:252-254`（该行未随 S-53 分叉未知档） | 本面板 CLI 实跑输出第 3 行（`/tmp/pm12-claim.out`）：第一行"…不给钟点拒跑"、第二行"（到点自动恢复；…）" |
| **B-12-4** | "未知=需人工干预的永久拒跑"这个**产品承诺变更**在三个应说话的地方都没说：README 零条款；顶栏红点不亮（该轮记 `inactive`，界面又不消费 `inactive_reasons`）；PRD/tech-design 只归档了"删文件=解除"（v1.16-⑥ / Q28-⑦），**没有**"读不动=按熔断拒跑"这条方向裁决（铁律 4） | README 双语；`zcode_claim.py:135,145` + `admin.py:122`；`docs/specs/prd.md:779` / `docs/specs/tech-design.md:294`（同仓另一处"状态文件读不动"的方向写的是"按陈旧锁处理：清理 → 写锁 → 继续启动"——那是**实例锁**的既有裁决、与熔断不同子系统，不算冲突，但没有任何文档说明熔断侧现在走的是**相反方向**） | §2.3 的 grep 结果、§3 表④行实测 `ops_failed_unread = 0` |

### 登记（非阻塞，本轮不判死，但必须继续挂着）
| # | 内容 |
|---|---|
| N-12-1 | 指路文案说"添加映射"、按钮字面「添加模型」，且与「资源池设置」页的「＋ 添加模型」（另一种动作）同字面；J3/pytest 只看控件标记不看按钮文字（§4.3） |
| N-12-2 | README 与徽章同日数字 710 vs 实测 715（§5；判据容差 ±20 使"钉住不漂"这句话名实不符，建议改为"≥ 当前且每次升版同步"或收紧容差） |
| N-12-3 | README 把用户指向 `mgw zcode claim --help`，而该 epilog 仍被 argparse 折成一段且 markdown `**…**` 字面漏进终端（第十一轮"另登记"未修，实测输出见 §5 复跑；不影响正确性，影响"看完能照做"） |
| N-12-4 | 控制台侧栏实际 11 项导航（七页 + 模板预览 1 + 需求预演 3），对外 README 只承诺七页，解释文档在 gitignore 的 `docs/` 里，clone 用户无从得知 |
| N-12-5 | `mgw setup` 的 `3`（写盘失败）与 `claim` 的 `3`（熔断拒跑）同码异义，README 已注明"按子命令读退出码"✔ 但脚本使用者仍易混；建议后续把 setup 写盘失败改独立码 |
| N-12-6 | 运行中**新出现**的坏文件（并发半写、外部手改）只在网关日志留痕：熔断对齐只在启动时跑一次（`main.py:493`），运营轮里的未知拒跑既不 bench、不进 warnings、也不进红点 → 界面对该状态的可发现性只有"重启一次"这条路（B-12-2/B-12-4 的时间维补充，修复时一并解决即可，不单列阻塞） |
| N-12-7 | 第十一轮登记的 S-46 ~ S-51、旧账 #48（热重载未 `aclose`）本轮**未见实现者声称已做**，本面板未重复验收（账本 `E2E-20260928-round5-fixes.md:413-424` 仍列为"尚未修"，诚实 ✔）；其中 S-46（六页共享行为零执行、面板可把 `confirmDialog` 取消改成删除）仍是全站最大敞口 |

### 本面板对上一轮四条 PM 阻塞的复验结论
- **S-36 指路页名**：已收口（§4 实测走通，双文案同页 + J3/派生 owners 到位）✔
- **S-37 先登录工具**：已收口（双语各一条、语义与 PRD Q25-⑩ 对齐、判据 4 条在 `test_v2_readme_claims.py:77-86`）✔
- **S-39 README 失真**：版本/链接两项收口 ✔，数字一项形式合规但同日漂 5 条（N-12-2）△
- **S-40 坏值告警与界面出口**：日志归因分叉与节流字段单独措辞**实测到位**
  （`节流字段读不动（last_call_ms 缺少该字段…）→ 按『没有最近一次调用』处理，熔断判定不受影响`，§2.1 复跑），
  但"界面出口"这一半只做到"有一格文字"，没做到"说对话"（B-12-2）；且新引入的未知档自身还有一个未覆盖的坏形态（B-12-1）→ **未收口** ✘

## 7. 结论与运行态说明

**结论：不通过（阻塞 4 条）。**
4 条全部集中在本轮唯一的产品承诺变更（熔断未知态 fail-closed）上：方向本身我判**成立**
（未知按最坏处理不会把用户锁死 —— 删文件出口实测有效、给的是绝对路径、CLI 与日志同句、rc=3 诚实），
但"未知"这件事目前**只在日志与 CLI 里诚实**，一进界面与第二行 CLI 就被翻译成"有个钟点、无需处理、到点自动恢复"，
等于把新口径最贵的那一条承诺（宁可拒跑也不冒险）在最常被读的出口上撤销掉了；
外加一个仍可复现的 fail-open 漏网形态（B-12-1）。这四处修完后我可以判通过或有条件通过。

- 三门复跑：pytest **715 passed** / 前端实测 **84 项全绿** / `--mutation` **可红 104/104** / 后端出口 **12/12** ——
  与实现者自跑数字**逐字一致**，本面板独立复现，无假绿证据（数字层面本轮可信）。
- 纪律自证：`data/` 全程只读 —— `find data -newermt '-40 minutes' -type f` 输出为空；
  实验全在 `/tmp/pm12-circ`、`/tmp/pm12-states`、`/tmp/pm12-refuse`、`/tmp/pm12-fixture`；
  未发起任何真实上游调用（所有 claim 轮都在熔断闸门处返回，凭据为假串 `sk-fake-not-real`）；
  **`:8300` 本轮未在监听**（`lsof -nP -iTCP:8300 -sTCP:LISTEN` 空）→ 本轮未复跑用户运行态实例，
  运行态结论一律来自本面板自起的随机端口临时实例。
- 未改动任何生产代码/测试/前端源码：仅新增本报告文件 `docs/changes/reviews/pm-accept-12.md`（`docs/` 已 gitignore）。
  收工 `git status --porcelain | wc -l` 见下方补记，与开工 85 的差异只应为并行会话所致，本面板不产生源码 diff。

### 7.1 收工自证（本轮最后一条命令输出）
```
$ git status --porcelain | wc -l
      85          ← 开工 85 / 收工 85（本面板零源码 diff）
$ find data -newermt '-45 minutes' -type f
(空 = data/ 全程未被写入)
$ ls -la docs/changes/reviews/pm-accept-12.md
-rw-r--r--@ 1 w  staff  23650 Sep 28 19:17 docs/changes/reviews/pm-accept-12.md
```
`docs/` 在 .gitignore 内（所以 `git status` 计数不变），报告确实落盘如上。
