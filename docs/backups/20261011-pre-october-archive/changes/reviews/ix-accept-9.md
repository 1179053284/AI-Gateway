# 交互验收 · 第九轮（IX-9）：只攻「前端门 `scripts/verify_v2_frontend.mjs` 的逃逸面」

- 验收人：ix（资深交互设计师视角）｜日期：2026-09-28｜轮次：9
- 被测门：`scripts/verify_v2_frontend.mjs`（S-30 三层结构：A/B/C 函数级 + I 段红点行为 + K0~K6 整页装配）
- 门基线（开工首跑，仓库原状）：
  `实测 76 项，通过 76 项，失败 0 项` ／ `可红 76/76；每条断言都有对应变异`
- 变异一律在副本 `/tmp/mgw-accept-9/` 上做（12 个门依赖文件 + `logs.js`/`stats.js`/`templates.js` 副本），仓库零改动；
  驱动 `/tmp/mgw-accept-9/drive.mjs`（施加变异 → 跑实测 + 跑 `--mutation` → 还原），
  探针 `/tmp/mgw-accept-9/probe.mjs`（用与 K 段**同样**的 `new Function` 方式执行真实 `renderDashboard`，打印"用户实际看到什么"）。

---

## ① 结论：**不通过**

判据依据：本轮做出 **16 个真实坏改动**，其中 **14 个让门的两态同时全绿**（`实测 76 项…失败 0 项` **且** `可红 76/76`），
即：把它们合进生产代码后，`pytest -k frontend_gate`（`tests/integration/test_int_v2_frontend_gate.py:84/97` 两态都跑）也会全绿。
这些坏改动的用户后果都是**实打实的界面缺陷**：告警横幅整条不可见 / 熔断原因与恢复时刻从界面消失 /
24h 趋势图永久空白 / 总览页请求一个不存在的端点（生产必然报错空屏）/ 管理界面丢失 HTML 转义（存储型 XSS 面）/
把用户指到三个不存在的页面。

另有 2 个（E4b/E11）实测模式全绿、只在 `--mutation` 里被**锚点过期**顺带抓住 —— 说明"锚点过期"这道保险有效，
但也说明语义判据本身没覆盖这两类。

根因归为 **B-1~B-7 七条**（见 ③）：**门在 K 段验的是"产出 HTML 的字符串里有没有这段文本 + 结构对不对"，而不是"用户看不看得见 / 这段文本是不是后端下发的原文 / 请求的是不是那个端点"**。

---

## ② 变异清单（23 条：16 逃逸 + 7 对照）

`门输出` = 该副本上 `node scripts/verify_v2_frontend.mjs overview.json` 的最后一行 + `--mutation` 的可红行。

| # | 变异内容（file:line） | 实测门输出 | 变异自证 | 是否打红 | 打红了哪几条 |
|---|---|---|---|---|---|
| **E14** | `dashboard.js:6` 总览改请求 `/admin/api/panel`（生产无此路由） | `实测 76 项…失败 0 项` | 可红 76/76 | **否（逃逸）** | — |
| **E5** | `api.js:18` GET 对 overview 做"文案归一化"，四条告警正文全变「检测到配置问题，请检查设置」 | 失败 0 项 | 76/76 | **否（逃逸）** | — |
| **E1** | `dashboard.js:71` 告警正文节点加 `hidden` | 失败 0 项 | 76/76 | **否（逃逸）** | — |
| **E2** | `dashboard.js:69` 整条横幅 `style="display:none"` | 失败 0 项 | 76/76 | **否（逃逸）** | — |
| **E3** | `dashboard.js:71` 告警正文改印到 `title` 属性（可见区只剩「配置告警」） | 失败 0 项 | 76/76 | **否（逃逸）** | — |
| **E4** | `dashboard.js:104` 「最近错误」整列 `display:none`（原因+恢复时刻都看不见） | 失败 0 项 | 76/76 | **否（逃逸）** | — |
| **E4b** | `dashboard.js:102-104` 恢复时刻从「最近错误」搬到「处理中」列 | 失败 0 项 | 可红 73/76 | 半（仅锚点过期） | 无判据变红；`熔断原因从正文消失`/`少渲染一列`/`B-8` 三条变异锚点命中 0 次 |
| **E7** | `api.js:51-54` `esc()` 弱化成 `String()`（页面产出未转义 HTML） | 失败 0 项（两份载荷下均如此） | 76/76 | **否（逃逸）** | — |
| **E9** | `logs.js:121`（**不在 J2 扫描面**）「可到『运行监控』页调整维度」 | 失败 0 项 | 76/76 | **否（逃逸）** | — |
| **E9b** | `stats.js:106`（**不在扫描面**）「请到『模型映射』页补充资源」 | 失败 0 项 | 76/76 | **否（逃逸）** | — |
| **E10** | `index.html:22`（**不在扫描面**）静态副标题写「凭据失效请到『模型映射』页更换」 | 失败 0 项 | 76/76 | **否（逃逸）** | — |
| **E8** | `models.js:188` 坏页名**不带「页」字**：`toast("请到「模型映射」为该模型配置资源映射")` | 失败 0 项 | 76/76 | **否（逃逸）** | — |
| **E11** | `dashboard.js:131` `active` 分支按 `r.available` 分叉出第二套文案 | 失败 0 项 | 可红 75/76 | 半（仅锚点过期） | 无判据变红；`active 分支拼错（落兜底）` 锚点命中 0 次 |
| **E6** | `dashboard.js:42` 摘掉 `drawHourChart(data.today_by_hour)` 调用（图表卡永久空白） | 失败 0 项 | 76/76 | **否（逃逸）** | — |
| **E15** | `dashboard.js:36` 整张「资源健康」卡 `display:none` | 失败 0 项 | 76/76 | **否（逃逸）** | — |
| **E16** | `dashboard.js:37` 新增动作「审计明细」：`href="javascript:void 0"` + `onclick="location.hash='#/audit-log'"` | 失败 0 项 | 76/76 | **否（逃逸）** | — |
| T1 | `dashboard.js:37` 把唯一的 `#/logs` 链接换成 onclick 跳不存在的路由 | `失败 1 项` | 退出 2（基线有红） | 是 | **K4**（`links.length>=1` 失守） |
| T2 | `models.js:361` 模板串里以 `//` 开头的一行可见文案写坏页名（第八轮 B-4 同款） | `失败 1 项` | 退出 2 | 是 | **J2** |
| T3 | `main.js:73` 死分支 `if (false) toast("…到「运行监控」页…")` | `失败 1 项` | 退出 2 | 是 | **J2**（按源码扫，不区分可达性） |
| A1 | `dashboard.js:131` 坏页名写进 `aria-label` 属性 | `失败 1 项` | 退出 2 | 是 | **J2**（属性同样入判） |
| A2 | `dashboard.js:99` `undefined` 只出现在 `title` 属性里 | `失败 1 项` | 退出 2 | 是 | **K5**（扫整段 HTML，含属性） |
| A3 | `dashboard.js:104` 恢复时刻从整行消失 | `失败 1 项` | 退出 2 | 是 | **K6** |
| A4 | `dashboard.js:71` `configWarnings` 内部把「——」后的指路句吞掉 | `失败 1 项` | 退出 2 | 是 | **A9**（+A3/A4/A6/A7/A8 族） |

### 探针实测：这些"全绿"改动下用户实际看到什么（`probe.mjs`，与 K 段同一执行路径）

| # | 页面真实产出（剥标签后的可见文本 / 可观察调用） |
|---|---|
| E14 | `GET 请求路径 = ["/admin/api/panel"]`，**但横幅/表格内容照旧**（因为门的 `fetchStub` 不看路径、恒返回 fixture，`verify_v2_frontend.mjs:550-552`）→ 生产里 404，`main.js:53-55` 把整页换成错误空屏 |
| E5 | 横幅可见文本：`配置告警 检测到配置问题，请检查设置`（真实的 503/隐藏说明/指路句全部没到用户眼前，条数仍是 4） |
| E3 | 横幅可见文本：`配置告警`（四条横幅四个空壳，正文只在 title 里） |
| E1/E2/E4/E15 | 浏览器渲染为空/不显示，但 `innerHTML` 里文本仍在 → 剥标签后照旧命中所有判据 |
| E4b | 冷却行：`资源A 冷却中 0 0，至 16:20 1800s ZCode 风控熔断（30min，全局）`（钟点跑进「处理中」列，「最近错误」列不再给恢复时刻） |
| E6 | `#hour-chart` 的 `innerHTML` 长度 = **0**（24h 趋势卡永久空白） |
| E7 | 页面原样输出 `<img src=x onerror=alert(1)>`（A14 用的是门自带 `esc`，`verify_v2_frontend.mjs:53-54/126-128`，与页面的 `esc` 不是同一份） |
| E16 | 「审计明细」跳 `#/audit-log`：`main.js:44` `const page = PAGES[name] ? name : "dashboard"` → 静默回到总览，零提示 |

---

## ③ 阻塞项（7 条，均附最小复现 + 门原始输出行）

> 复现通用前置：`cp -R` 门依赖文件到 `/tmp/mgw-accept-9/`（保持相对路径），按下述锚点做单次替换，
> `cd /tmp/mgw-accept-9 && node scripts/verify_v2_frontend.mjs overview.json [--mutation]`。

### B-1【最要害】K 段的假 `fetch` 不看请求路径 → 页面可以请求一个根本不存在的端点而"渲染成功"
- 位置：`verify_v2_frontend.mjs:550-552`（`fetchStub = async () => ({ok, status, json: () => 读 fixture})`）；`dashboard.js:6`
- 最小复现：`const data = await GET("/admin/api/overview");` → `const data = await GET("/admin/api/panel");`
- 门输出：`实测 76 项，通过 76 项，失败 0 项` + `可红 76/76；每条断言都有对应变异`
- 事实：后端只有 `/admin/api/overview`（`model_gateway/api/admin.py:136`）；生产上这改动 = 总览页整屏报错。
- 修向：F1 对 `main.js` 有 `GET("/admin/api/status")` 字面锚点，**dashboard 侧没有对端点**；补一条 `K7`：`dashSrc` 必须含 `GET("/admin/api/overview")`，且 `fetchStub` 按路径分派（未知路径返回 `{ok:false,status:404,json:()=>{throw}}`），让"请求错了端点"在 K 段真炸。

### B-2 K 段仍把「DOM 里有这段文本」当成「用户看得见」；`hiddenish` 只认 `hidden`/`aria-hidden`
- 位置：`verify_v2_frontend.mjs:566-575`（`hiddenish` 两条正则）/ `:576-585`（K2/K3 零可见性守卫）/ `:601-609`（K6 同）
- 最小复现（任选其一，全部两态全绿）：① `dashboard.js:71` `<div hidden>`（E1）；② `:69` `style="display:none"`（E2，`hiddenish` 第二条 `alert alert-warn"[^"]*display:\s*none` 因中间夹着下一个 `"` 而永不匹配）；③ `:71` 正文进 `title`（E3）；④ `:104` 整列 `display:none`（E4）；⑤ `:36` 整卡 `display:none`（E15）
- 门输出：五例均 `实测 76 项…失败 0 项` + `可红 76/76`
- 修向：K 段判据前先做一次**可见性清洗**（丢弃带 `hidden`/`aria-hidden="true"`/`style` 含 `display:none|visibility:hidden` 的节点及其子树，并把只存在于 `title=`/`aria-label=`/`data-*` 的文本从"可见文本"里剔除），判据下在清洗后的文本上；A 段同理——A2~A9 吃的是函数返回的裸 HTML，同样没有可见性口径。

### B-3 J2 的 `copySources` 缺三类**用户可见文案产地**（`logs.js` / `stats.js` / `index.html` 静态文案）
- 位置：`verify_v2_frontend.mjs:495-503`
- 最小复现：E9 / E9b / E10（各一次字符串替换，见 ② 表）
- 门输出：三例均 `失败 0 项` + `可红 76/76`
- 缺口清单（同一族，尚未入面）：`pages/logs.js`、`pages/stats.js`、`pages/templates.js`、`static/index.html` 静态文案、以及后端进界面提示的 `api/admin.py`（现只扫 `main.py`/`core/resources.py`/`cli_setup.py`；`enums/matcher.py:27` 也带页名）
- 修向：`copySources` 由目录**自动发现**（`static/js/**/*.js` + `index.html` + `model_gateway/**/*.py`），而不是手写 10 个键；新增文件即自动入面，杜绝"漏配一个产地"。

### B-4 `PAGE_REFS` 两个正则都强制以「页」结尾 → 改版后的旧页名只要不写「页」就全绿
- 位置：`verify_v2_frontend.mjs:487-494`
- 最小复现：E8 `toast("请到「模型资源」页…")` → `toast("请到「模型映射」为…")`（去掉「页」字，`模型映射` 是 Q24 已被「资源池设置」取代的死名）
- 门输出：`失败 0 项` + `可红 76/76`
- 修向：除 `「X」页` 外，再扫 `「X」`/`『X』` 全量括号为**候选页名**，与 `navLabels` ∪ 历史页名黑名单（`模型映射`/`系统模型`/`账号授权`…）比对；命中"曾经是页名"即判红。

### B-5 页面产出的转义无人验：A14 测的是门自己注入的 `esc`，K 段不测转义
- 位置：`verify_v2_frontend.mjs:53-54`（门自带 `esc`）/ `:126-128`（A14）/ `:548-549`（K 段用 `api.js` 里的 `esc`）
- 最小复现：E7 —— `api.js:51` 的 `esc` 改成 `return String(s ?? "");`（原实现挪到未使用的 `escUnused`）
- 门输出：两份载荷下均 `实测 76 项…失败 0 项` + `可红 76/76`；探针在含 HTML 的告警载荷下打出 `页面原样输出 <img src=x onerror=alert(1)>`
- 影响：管理端免鉴权（Q18-①）+ 上游错误原文进 `last_error` → 未转义即存储型 XSS 面；全站所有页面共用这一个 `esc`
- 修向：K 段加一条 `pageHtml` 层面判据（载荷里放一条含 `<script>` 的哨兵 message，要求页面产出里出现 `&lt;script&gt;`），A14 改用 `api.js` 的真实 `esc` 而不是门自带副本。

### B-6 K 段只覆盖 `renderDashboard` 的少数出口：图表/其它调用点零判据；`K4` 只认 `href="#/…"`
- 位置：`verify_v2_frontend.mjs:583-585`（K3 八张卡）/ `:586-590`（K4）；`dashboard.js:42`、`dashboard.js:37`
- 最小复现：E6（删 `drawHourChart(...)` 调用 → `#hour-chart` innerHTML 长度 0）；E16（新增 `onclick="location.hash='#/audit-log'"` 的动作）
- 门输出：两例均 `失败 0 项` + `可红 76/76`
- 修向：K 段的假 DOM 已接住 `getElementById`，直接补 `K7 图表卡非空`（`nodes["hour-chart"].innerHTML.length > 200`）；`K4` 的链接抽取扩到 `(href|location\.hash\s*=|location\.href\s*=)\s*=?\s*["']#?/?([\w-]+)` 并统一与 `navLabels` 比对（`main.js:44` 的静默回落正是这类动作的真实后果）。

### B-7 `C16` 矩阵把 `available` 与 `status` 绑死、`K6` 对"列位"零要求
- 位置：`verify_v2_frontend.mjs:276-293`（`available: st === "active"`）/ `:601-609`（整行级判定）
- 最小复现：E11（`active` 分支按 `r.available` 分叉文案）；E4b（恢复时刻搬到「处理中」列）
- 门输出：两例**实测模式全绿**（`实测 76 项…失败 0 项`），仅 `--mutation` 以 `可红 75/76`、`可红 73/76` 被**锚点过期**顺带抓住（`✗ active 分支拼错（落兜底） ← 锚点命中 0 次`、`✗ 熔断原因从正文消失 ← 锚点命中 0 次`）
- 诚实注记：E11 的 `active + available:false` 组合在生产聚合里是否可达未取证（`core/resources.py` 聚合口径我未逐行确认），但它违反 `C16` 名字自己承诺的"只由 status + 冷却时长决定"；E4b 则是 §17 恢复时刻的**列位**回归，而 `K6` 只看整行。
- 修向：`C16` 的 `available` 与 `models/C/in_flight` 一样做正交（`available` 取 `true/false` 两轮）；`K6` 按 `<td>` 拆列，断言钟点落在「最近错误」列（用 `B1/B2` 已有的表头→列序映射）。

**非阻塞（同族小项，记账）**
1. `K1` 的 `want` 只取 `warnings.length`（`:568`），计数一致即绿 —— 载荷正文与页面正文**从不做等值比对**（B-1/B-2 都源于此）；建议 `K1` 直接要求"每条 message 都作为某条横幅的可见文本出现一次"。
2. `stripComments` 的"代码态 `//`"仍会把**含 `//` 的正则字面量之后同行内容**当注释（如 `/^\/\//`），本轮未能构造出有真实文案的可用坏改动，仅登记为口径模糊点（方向 4：字符串/模板/块注释三类我都试过，见 ④）。
3. `main.py:320-321`、`enums/matcher.py:27` 这类**注释里的合法页名**目前被 `#` 行保留规则放行（`verify_v2_frontend.mjs:483`），但注释里写"旧页名 + 页"会造成假红（T3 也证明 J2 不区分可达性）；口径应在 spec 里写明"注释不得出现「X」页字样"。
4. `FILES`/`copySources`/`MUTATIONS` 三处手写清单互相独立，建议由同一份自动发现结果派生，避免"新增了页面却忘了进门"。

---

## ④ 我试过但**打破不了**的（门在这些点是硬的）

| 尝试 | 结果 | 说明 |
|---|---|---|
| T1 用 `onclick` 完全替换掉页面上唯一的合法链接 | **红：K4** | `links.length>=1` 兜住了"链接全被换成不可静态识别的跳转" |
| T2 把坏页名放进模板字符串里以 `//` 开头的一行（第八轮 B-4 原逃逸） | **红：J2** | 按字符扫描的剥注释器确实堵住了"模板串里的 `//` 被当注释" |
| T3 坏页名写进永不相等的死分支 `if (false) toast(…)` | **红：J2** | J2 扫源码不吃运行时可达性 → 这类"文案在文件里就算数"是**故意的严** |
| A1 坏页名藏进 `aria-label` 属性 | **红：J2** | 属性文本同样入判（任务方向 7 的这条假设不成立） |
| A2 `undefined` 只出现在 `title=` 属性里 | **红：K5** | K5 扫整段 HTML（含属性），不是只扫剥标签后的文本 |
| A3 恢复时刻从冷却行整体消失 | **红：K6** | 钟点存在性在行级是硬的（缺的只是列位，见 B-7） |
| A4 `configWarnings` 内部吞掉「——」之后的指路句 | **红：A9**（连带 A3/A4/A6/A7/A8） | A 段直接吃函数输出，渲染器丢文案立刻响 |
| 把 `configWarnings(...)` 调用包进 HTML 注释 / 按 kind 过滤 / 加 `aria-hidden` | **红：K1 / A15 / K1** | 第八轮 B-1/B-11 与 S-18 ESCAPE-1 的补法本轮复验有效 |
| 把 `data.warnings` 换成 `data.res`、指标卡 `String(undefined)`、删表体 | **红：K2 / K5 / K3** | 结构级缺件仍能抓住（只有"文本在但看不见"这一族漏） |
| 让 `renderDashboard` 中途抛错（`data.nope`） | **红：K0~K6** | 抛错=判据失去对象，被 K0 显式钉住 |
| `esc` 弱化后想让 A 段也背锅 | **A14 仍绿、无判据可红** | 反向确认 B-5 的根因：A14 用门自带 `esc`，与页面那份不是同一实现 |
| 正则字面量/嵌套模板/注释套注释打穿 `stripComments` | **未能造出可用逃逸** | 方向 4 的三类构造实测后要么"保留文本"（只会更严），要么只影响同行；登记为口径模糊点而非漏洞 |

---

## ⑤ 工作树基线（`git status --porcelain | shasum`，82 行 porcelain）

- 开工：`994985f23949da1cf082a7d610761e4446c3aab5  -`
- 收工：`994985f23949da1cf082a7d610761e4446c3aab5  -`（**与开工一致**，连算两次同值）
- 收工自检三件：
  1. `diff -q` 逐个比对沙箱 15 个副本与仓库原文 → 零 DIFF（变异全部还原）
  2. 仓库原状重跑门：`实测 76 项，通过 76 项，失败 0 项`
  3. CI 级复验：`.venv/bin/python -m pytest tests/integration/test_int_v2_frontend_gate.py -q` → **2 passed**
- 诚实注记：写报告后的一次 `shasum` 读出过 `bbef1a75…`，随后三次重读均回到基线值（本目录 `docs/` 由 `.gitignore:17` 忽略，报告文件本身不入 porcelain）；
  疑为 git 未跟踪文件枚举的瞬时抖动，**未留下任何仓库改动**，故仍按基线一致记账。

补充（铁律 2）：本轮**未改任何生产代码**；未启动 `:8300`；未发真实上游请求；`data/` 只读未写。
