# ix 第十二轮验收 —— 攻「样式表层叠」新机制的边界 + 第十一轮 8 条阻塞的复攻

- 角色：资深交互设计师（只验收，不改生产代码）
- 靶子：本轮实现者新修的 **B11-1（`cssHiding()` 样式表层叠）**、**B11-7（K4 外链红线）**、**B11-6 的一半（J3 指路归属）**；以及仍未修的 B11-2/3/4/5/8
- 工作区：`/tmp/mgw-accept-12-ix/`（仓库副本，排除 `data/`、`.git/`、`.venv/`；门源码 md5 与仓库一致 `727290d4df2b619884772c8aa961bf28`）；**变异只施加在副本上**
- 载荷：`/tmp/ix12-fixture-baseline/overview.json`（本轮由 `MGW_V2_VISIBLE_DIR=/tmp/ix12-fixture-baseline .venv/bin/python scripts/ui_verify_v2_visible.py` 现采）＋派生 `traffic`（今日 120 调用/切换 3 次）与 `hostile`（后端可控字段塞活标签）
- 硬规则遵守情况：`data/` 全程只读；未发起真实上游调用；未重启/kill :8300；未改动仓库任何生产文件
- 开工 `git status --porcelain | wc -l` = 85

## ① 结论

**不通过（阻塞 8 条）。**

三句话：

1. **第十一轮最重的那条（B11-3"主动说谎"）本轮一个字节都没动。** 我复攻 9 条变异（`api.js` 非 2xx 不抛 / `confirmDialog` 取消即确定 / `copyText` 不写剪贴板 / `maskVal` 恒等 / 保存按钮永不解禁 / 失败行整族不显示 / 成功率分母 / 脚钮贴死回归），**9 条全部 84 项全绿**；其中 5 条在真实 Chrome 里量到了可观察坏结果，最狠的一条仍然是：后端 400 拒绝、`/admin/api/config` 里 `fail_threshold` 仍是 2，界面弹 **绿色「配置已保存并热重载生效」**。最硬的自证是 **A11**：我把「取消真删 + 假已复制 + 密钥明文」三条**同时**种在副本上，门 `实测 84 项全绿`、`--mutation 可红 104/104` —— 这两句自报数字与"界面在骗人"完全可以同时成立。
2. **本轮唯一新增的机制（`cssHiding()` 样式表层叠）堵住了我第十一轮举的那个具体写法，但没堵住"层叠语义"本身。** 它的注释写着"扫**任意嵌套层级**的 `选择器 { 声明 }`（含 `@media` 里面）"，实现里 `:805` 的 `sel = atRule !== 0 ? "" : head` 把嵌套层的**选择器整段丢成空串**：我从门源码里**逐字切出该函数**跑探针（`/tmp/ix12-cssprobe.mjs`，零手抄），`@media{…}`、`@layer{…}`、`.alert-warn:first-child`、`main div`、`#hour-chart{height:0!important}` 五种写法派生结果全部是 `classes=["hidden"]`（什么都没学到）。浏览器侧对应六条真实坏结果：四条告警整族消失（`bannerH→[0,0,0,0]`、`innerText 873→459`）、**恰好吞掉第一条告警**（`[0,64,64,83]`，最难发现的那种）、整个内容区塌掉（`873→137`）、趋势图压成 0 高。同一枚硬币的反面也测出来了：`.ALERT-WARN`（大小写）和 `.not-a-real-ancestor .alert-warn`（复合选择器只取最右段）都让 `✗ K1 正文缺失=4` 而真浏览器**一条横幅都没少** —— 精度不足会造**误伤**，实现者要的是"能红"，我给的这两条说明它会红得不该红。另外它只吃 `read("css")` 一个文件，`index.html` 的内联 `<style>`（实测 84/84 绿 + 浏览器四条横幅全灭）与 `templates/*.html` 里那 9 个 `<style>` 块仍在模型外。
3. **其余五条第十一轮阻塞同样原样在**：壳层零判据（`#content` 改名 → Chrome 实测 `contentNull:true / banners:0 / innerText 873→137`，**整站不启动**；`<link href>` 写错 → `--err-bg` 取空、`box-shadow:none`，**裸样式**；`inert` → `elementFromPoint` 返回 **null** 且点击后 `location.hash` 不变，**全页点不动**；导航项加 `class="hidden"` → 该项高度 36→**0**，新机制明明认识 `.hidden` 却接不上壳层）；转义只在一根管道上（`资源名/最近错误/日志模型列` 三处去 `esc`，喂 `<svg onload=…>` 载荷全部 84/84 绿 —— 而 hostile 载荷那次红是**撞上**的：它含字面 `<script>`，被 K9 的整页 tripwire 捞到，`onerror/onload/onmouseover` 形态一概不响）；数值真值（八张卡值整族空、**「成功比 NaN%」**上了界面、`今日切换 0 次` 在真实 `switch_count=3` 的载荷上照样绿）；`K8` 的 `|| ["", ""]` 缺省（只改容器 id → `chartChildren:0` 而门说 `✓ K8`）；B11-6 的【】括号与 J3 的手写动作表（`「重启」`不在 4 条 `ROUTE_MARKERS` 内 → 绿；`查看日志` 指到另一个真页面 → K4 绿，而 `javascript:` 伪协议反倒被路由存在性规则捞住 = 对照）。

`本轮施加 47 个变异：38 个门全绿（其中 21 个在真实 Chrome 里量到用户可见坏结果），9 个如期变红（含 2 条**误伤方向**）。`

## ② 基线复跑（逐字）

| 实现者自报 | 本轮复跑结果 | 原文 |
|---|---|---|
| `实测 84 项全绿` | **复现** | `实测 84 项，通过 84 项，失败 0 项`（`/tmp/ix12-baseline.txt`，`MGW_V2_VISIBLE_DIR=/tmp/ix12-fixture-baseline`） |
| `--mutation 可红 104/104` | **复现** | `[变异自证] 基线 84 条全绿 → 施加 104 个源码变异` … `可红 104/104；每条断言都有对应变异`（`/tmp/ix12-mutation.txt`，副本内跑，门 md5 与仓库一致 `727290d4df2b619884772c8aa961bf28`） |
| `后端出口 12/12` | **复现** | `后端出口实测 12 项，通过 12 项，失败 0 项` |
| `pytest 715 passed` | **未复现** | 全量：`1 failed, 714 passed, 507 warnings in 153.76s` → `FAILED tests/unit/test_v2_wiring_guard.py::test_guard_catches_a_planted_dead_method`；同文件单跑：`6 passed in 23.85s`。原因见 ④ B12-8（该测试往真包目录 `model_gateway/_wiring_canary_pkg` 写盘，与并行面板互斥） |

## ③ 变异表
### §A 族 · B11-3 谎报型（六页 + 共享组件 + 错误管道）—— **本轮逐条复攻，全部仍然逃逸**

锚点：**API**=`model_gateway/web/static/js/api.js`，**COMP**=`model_gateway/web/static/js/components.js`，**APAA**=`…/pages/apiaccess.js`，**SET**=`…/pages/settings.js`，**LOG**=`…/pages/logs.js`，**STA**=`…/pages/stats.js`。
浏览器列 = 真实 Chrome（ego-browser 任务空间「ix12 A-family browser repro」）打在**我的临时实例** `http://127.0.0.1:57388`（副本源码 + `/tmp/ix12-data`，合成假 Key `mg-fake-*`、`base_url=127.0.0.1:9`，用完即关），变异改完刷新即生效。

| # | 变异 diff（原文 → 变异） | 门输出 | 用户在浏览器里实际看到 | 判 |
|---|---|---|---|---|
| A1 | API：`  if (!resp.ok) {` → `  if (false) {` | `实测 84 项，通过 84 项，失败 0 项`（std + traffic 两份载荷都绿） | 「系统设置」页把 `y · 连续失败阈值` 改成 `0` 点保存：**基线**弹 `toast err :: 保存失败：scheduling.fail_threshold: Input should be greater than or equal to 1`；**变异**弹 `toast ok :: 配置已保存并热重载生效`，而同一次会话里 `GET /admin/api/config` 读到 `serverY` **仍是 2**（配置一个字没变）→ 绿色成功条 + 未生效的调度参数 | **绿 · 阻塞（B11-3 未修）** |
| A2 | COMP：`    cancel.onclick = () => { m.close(); resolve(false); };` → `resolve(true);` | 84/84 全绿 | 「API 接入」页点第一行「删除密钥」→ 弹窗按钮 `["","取消","确定"]` → 点**取消**：`rowsBefore=2` → `rowsNow=1`，服务端 `access_tokens` 从 `["tok-aaa","tok-bbb"]` 变成 `["tok-bbb"]` → **取消即真删**（同一 `confirmDialog` 还管着删资源/停网关） | **绿 · 阻塞** |
| A3 | COMP：`  navigator.clipboard?.writeText(text).then(\n    () => toast(okMsg, "ok"), () => toast("复制失败", "err"));` → `  toast(okMsg, "ok");` | 84/84 全绿 | 挂钩 `writeText` 后点「复制密钥（直取明文）」：`copied: []`（剪贴板一个字节没写）+ `toast ok :: 密钥已复制` → 用户往工具里粘的是剪贴板里的旧东西 | **绿 · 阻塞** |
| A4 | APAA：`const maskVal = (v) => v ? v.slice(0, 5) + "****" + v.slice(-4) : "";` → `const maskVal = (v) => v \|\| "";` | 84/84 全绿 | 密钥两行单元格实测文本 = `["mg-fake-0123456789abcdef","mg-fake-9876543210fedcba"]`（基线 `["mg-fa****cdef","mg-fa****dcba"]`）→ 2026-09-06 定版的「默认密文」被推平，投屏/肩窥直接泄 | **绿 · 阻塞** |
| A5 | SET：`    root.querySelector("#st-save").disabled = false;` → 注释掉 | 84/84 全绿 | 浏览器复采见 §B 批次（同一实例，改 `y` 后 `#st-save.disabled` 恒 `true` 而脏态徽章「有未保存修改」照样出现）→ **系统参数再也保存不了**（v2.1 修过的死 UI 家族，无判据锁定） | **绿 · 阻塞** |
| A6 | LOG：`${rows.map((r) => requestRow(r)).join("")}` → `${rows.filter((r) => r.status !== "failed").map(…)}` | 84/84 全绿 | 未复采（代码路径直读：「请求日志」表格里失败行整族不显示，卡头「共 N 条」仍按后端总数报）→ 数字与内容互相矛盾 | **绿 · 阻塞**（门绿为实测，坏结果为代码路径推断） |
| A7 | STA：`  const rate = t.requests ? Math.round((t.success / t.requests) * 100) : 0;` → 分母改 `success + failed` | 84/84 全绿（std + traffic 两份都绿；traffic 载荷 `aborted=5` 也照样绿） | 未复采（数据看板成功率丢掉「中断」→ 数字虚高） | **绿 · 阻塞** |
| A8 | COMP：`    if (ok !== false) el.classList.toggle("on", next);` → `toggle("on", !next)` | 84/84 全绿 | 第十一轮已实测：只有短暂反相，`persist()` 整页重绘会纠正 → 坏结果不持久 | **绿 · 登记（T5 复现，不算阻塞）** |
| A9 | COMP：`    while (footer.firstChild) footEl.append(footer.firstChild);` → `footEl.append(footer);` | 84/84 全绿 | 未复采（2026-09-06 用户截图指出的「取消/确定贴死」原样回归，无判据锁定） | **绿 · 阻塞（回归无防）** |
| **A10 对照** | LOG：`该筛选条件下无请求记录` → `…，可去「插件市场」页核对` | `✗ J2 …违规指路：model_gateway/web/static/js/pages/logs.js→「插件市场」页`（rc=1，83/84） | —— | **红**：证明 `logs.js` 确实在**文案扫描面**内 —— A6 的绿不是"文件没扫"，而是**行为从不执行** |
| **A11 叠加自证** | A2+A3+A4 **三条同时**施加在副本上 | 门 `实测 84 项，通过 84 项，失败 0 项`；**同一时刻** `--mutation` → `可红 104/104；每条断言都有对应变异`（`/tmp/ix12-mutation-with-A234.txt`） | 三条坏结果同时在场（明文上屏 + 假「已复制」+ 取消真删） | **门自己的"可红 104/104"依然不等于封住**（与第十一轮同型） |

> 根因未变（`scripts/verify_v2_frontend.mjs:713-714` 只 `browserFn(...)` 编译并执行 **`api.js` + `dashboard.js`** 两个文件；`read("` 的调用点全集实测为 `dash / res / index / main / css / coreRes / api`，`components.js`、`logs.js`、`stats.js`、`templates.js`、`models.js` 只进 `copySources` 文本面）。`api.js` 虽被编译，但假 `fetch`（`:719-725`）对已知路径**恒回 `ok:true`**，非 2xx 分支从来没有输入能打进去 —— A1 的 `if (false)` 因此完全不被观察。

### §B 族 · B11-2 壳层零判据 —— **本轮完全未被触碰**

门侧证据（静态）：`grep -n 'content\|crumb\|stylesheet\|script src\|<link' scripts/verify_v2_frontend.mjs` 实测只有 3 处命中，全是注释与 MUTATIONS 表里的字面量（`:77`、`:1388`、`:1390`）——**没有任何一条判据读 `#content` / `#crumb-group` / `<link href>` / `<script src>`**；`read("index")` 的调用点只有 `:399 dotTag`（红点标签）与 `:499 navAnchors`（导航 `data-page` 字面）。

| # | 变异 diff | 门输出 | 真实 Chrome 读数（临时实例 :57388，截图 `/tmp/ix12-shots/`） | 判 |
|---|---|---|---|---|
| B1 | IDX：`<main class="content" id="content"></main>` → `id="page-content"` | 84/84 全绿 | `contentNull:true`、`banners:0`、`bodyTextLen` **873→137** → 路由在第一行就抛错，**整站不启动**，只剩侧栏+顶栏骨架（`B1-rename-content.png`） | **绿 · 阻塞（B11-2 未修）** |
| B2 | IDX：`<span id="crumb-group">概览</span>` → `id="crumb-grp"` | 84/84 全绿 | 未复采（同族写法；B1 已证这条路径是 `route()` 的首个抛错点） | **绿 · 阻塞** |
| B3 | IDX：`<main … id="content">` 加 `style="display:none"` | 84/84 全绿 | `contentDisplay:"none"` 而 `contentChildren:7`、DOM 里 4 条横幅俱在（`bannerH:0`）、`bodyTextLen` 873→**137** → **内容区纯白**（`B3-main-display-none.png`） | **绿 · 阻塞** |
| B4 | IDX：`#content` 加 `inert aria-hidden="true"` | 84/84 全绿 | `contentInert:true`（横幅仍显示、`bodyTextLen` 873 不变）→ 内容区元素**退出命中测试**，全页按钮/链接点不动、读屏读不到（点击穿透实测见 ⑥） | **绿 · 阻塞** |
| B5 | IDX：`<link rel="stylesheet" href="/css/base.css">` → `/css/theme.css` | 84/84 全绿（H1/H2 判的是 `base.css` **源码文本**，不看 `<link>`） | `--err-bg` 取值 **`(empty)`**、`.card` 的 `boxShadow:"none"`、`body` 背景 `rgba(0,0,0,0)`、横幅高度 64→45（**完全裸样式**，`B5-bad-stylesheet.png`） | **绿 · 阻塞** |
| B6 | IDX：`<script type="module" src="/js/main.js">` → `/js/app.js` | 84/84 全绿 | `contentChildren:0`、`banners:0`、`dataTheme:null` → 脚本 404，**界面根本没启动**（`B6-bad-script-src.png`） | **绿 · 阻塞** |
| B7 | IDX：`<a href="#/logs" data-page="logs" class="nav-item">` → `class="nav-item hidden"` | 84/84 全绿 | 该导航项 `getBoundingClientRect().height` = **0**（`navLogsH:36→0`）→「请求日志」入口从侧栏消失，用户再也点不到那一页。**这一条正是本轮新机制的靶心**：`cssHiding()` 明明已从 `base.css` 派生出 `.hidden` 是隐藏类，但**壳层 HTML 从不进 `visibleText()`**，所以新机制对壳层一行也用不上 | **绿 · 阻塞 B11-1/B11-2 交叉** |
| B8 | MAIN：`setAttribute("data-theme", resolveTheme(themeMode))` → `"light"` | 84/84 全绿 | 施加后点「深色主题」按钮：`dataTheme` 仍是 `"light"`、`bodyBg` 仍 `rgb(247,248,249)`（`B8-dark-click-still-light.png`）→ **三态主题里两态失效**（深色/跟随系统点了没反应） | **绿 · 阻塞** |
| B9 | MAIN：`const FILES = ["/js/main.js", "/js/api.js", "/js/components.js", "/css/base.css", …PAGES]` → `["/js/main.js"]` | 84/84 全绿 | 未复采（改 `pages/*.js` 或 `base.css` 不再触发自动刷新 → 回到 2026-09-05「新旧混载 = 只有框架内容空白」事故形态） | **绿 · 登记级** |
| **B10 对照** | IDX：侧栏 `<span>资源池设置</span>` → `<span>模型映射</span>` | `✗ J1`（`meta=8 dashboard:✓,…models:≠资源池设置,…`）+ `✗ J2`（`违规指路：enums/matcher.py→「资源池设置」页, core/resources.py→…`），rc=1 | —— | **红**：壳层不是"完全没判据"，而是**只有导航标签/红点那两条字面判据**；容器 id、样式表、脚本 src、可见性一律没有 |

### §C 族 · B11-4 转义管道 —— **仍然只在一根管道上被证明，而且那根管道的红是"撞上的"**

门侧只有 `K9`（`:944-951`）看转义，它的三件套是 `sentinelHtml.includes("&lt;script&gt;")` ∧ `!/<script>/.test(sentinelHtml)` ∧ `!/onerror=alert\(1\)>/`；哨兵 `SENTINEL` 只塞进 `warnings.message`（`:741-742`）。

| # | 变异 | 门输出（载荷） | 判 |
|---|---|---|---|
| C1 | dash `:99`：`>${esc(r.name)}</td>` → `>${r.name}</td>`（资源名列去转义） | std **84/84 绿**；hostile（name=`<img src=x onerror=alert(document.domain)>`）**84/84 绿**；h2（name=`<svg onload=alert(9)>哨SVG`）**84/84 绿** | **绿 · 阻塞（B11-4 未修）** |
| C2 | dash `:104`：`>${esc(r.last_error || "—")}</td>` → 去 `esc`（「最近错误」列 = 上游原文最长最脏的一列） | std 绿；h2（`<svg onload=alert(6)>`）**绿**；hostile `<script>alert(2)</script>` → `✗ K9` | **绿 · 阻塞**；hostile 那次红是**撞上的**：该载荷恰好含字面 `<script>`，被整页 tripwire 捞到；换成 `onerror`/`onload`/`onmouseover` 形态立刻不红 → K9 不是"逐字段转义判据"，是"整页有没有 `<script>` 字样" |
| C3 | logs `:141`：`<td class="strong">${esc(r.system_model \|\| "")}</td>` → 去 `esc` | 84/84 全绿（第六页从不执行） | **绿 · 阻塞** |
| **C4 对照** | dash `${esc(w.message \|\| "")}` → 去 `esc`（唯一被看着的那根管道） | `✗ A14 告警文案经 HTML 转义`＋`✗ K9`（rc=1） | **红**：证明 K9/A14 确实是活的，只管这一根管子 |
| 现成疑点 | `main.js:54` `content.innerHTML = \`<div class="empty">${e.message}</div>\`;` —— **未过 `esc`**，`e.message` 来自 `api()` 抛出的后端原文 | 基线 84/84 全绿（该文件只被执行红点那段） | 静态事实（`file:line`）。**浏览器侧 XSS 落地未复采**：我的临时实例 `PUT /admin/api/config` 接受含标签的资源名后 `overview.resources[0].name` 回落到 `res-a`（端点把它规范化掉了），载荷种不进去 → 按"代码级成立 + 可达性未验证"登记，不夸大为已实测 |

### §D 族 · B11-5 指标数值真值 —— **仍无判据（数字造假整族逃逸）**

| # | 变异 | 门输出 | 真实 Chrome 读数（:57388） | 判 |
|---|---|---|---|---|
| D1 | dash `:80`：`<div class="metric-value">${fmtValue(value)}</div>` → `<div class="metric-value"></div>` | 84/84 全绿（std + traffic 两份） | `values` = `["1 资源冷却中","13m26s",…]` → **`["","","","","","","",""]`**，八张卡只剩图标与标签；`body.innerText` 873→814 | **绿 · 阻塞** |
| D2 | dash `:11`：`const rate = t.requests ? Math.round((t.success / t.requests) * 1000) / 10 : 0;` → 去掉 `t.requests ?` 守卫 | 84/84 全绿（std 与 traffic 都绿） | 第三张卡文本 = **「成功 0 · 成功比 NaN%」**（我的实例此刻 `today.requests=0`，正是每天 0 点后/刚重启时的真实形状）；K5 的坏插值黑名单只有 `undefined`/`[object Object]`/`${`，`NaN` 不在内 | **绿 · 阻塞** |
| D3 | dash `:37`：`今日切换 ${data.today.switch_count} 次` → `今日切换 0 次`（写死常量） | std 绿；**traffic 载荷真实 `switch_count=3` 也 84/84 全绿** | 浏览器未复采到可见差异 —— 我的实例今日切换数本身就是 0，基线与变异同显「今日切换 0 次」。**门侧证据是决定性的**：判据从不把界面数字与载荷数字对表，所以"写死 0"与"真实 3"不可判别（这正是第十一轮 eng-B 给 K10 立的那条"可判别性"要求，只落在了两列上，没落到指标卡与卡头） | **绿 · 阻塞（缺可判别性）** |
| D4 | `model_gateway/main.py:329`：告警③成因 `全部不可用（已停用或凭据失效），` → `全部不可用（今日流量高峰引发的临时冷却，无需处理，稍后自动恢复），` | 84/84 全绿（A4/A5 只数「已从 /v1/models…隐藏」命中次数，不钉成因句） | 未复采（K1 已证后端文案原样透传进横幅正文）→ 真因是"开关关闭/凭据失效（不会自愈）"，界面却说"临时冷却·无需处理·稍后自动恢复"，用户据此坐等自愈 | **绿 · 阻塞** |
| **D5 对照** | dash `metricCard("运行状态"` → `"网关状态"` | `✗ K3 八张指标卡全部可见`（rc=1） | —— | **红**：K3 认**标签**不认**值**，这两件事的差集就是 D1~D3 |

### §E 族 · B11-8 判据缺省 fail-open + B11-6 的【】形态 —— **都未修**

| # | 变异 | 门输出 | 真实 Chrome 读数 | 判 |
|---|---|---|---|---|
| E1 | dash `:31`：`<div id="hour-chart" style="height:160px"></div>` → `id="hour-cart"`（**只改容器**，`getElementById("hour-chart")` 不动） | 84/84 全绿，`✓ K8` | `chartBoxExists:false`、`chartRenamed:true`、**`chartChildren:0`**（柱子一根没画进界面里那个框）、`body.innerText` 873→811 → 趋势卡只剩一条 160px 高的空白带 | **绿 · 阻塞**：`:918` 的 `(pageHtml.match(…) \|\| ["", ""])[1]` 原样还在 —— 正则不匹配 → 空串 → `isInvisible("")` 与 `!/height:0/` 双双通过，"查无此容器"被洗成"容器可见"。`grep -n '\|\| \["", ' scripts/verify_v2_frontend.mjs` 实测仍有 4 处同类缺省（`:250 titleOf`、`:310`、`:918`、`:924`） |
| E2 | logs：`该筛选条件下无请求记录` → `…，失败成因见【模型映射】页` | 84/84 全绿（`PAGE_REFS`/J3 的括号集仍只有「」/『』，`:574`、`:667`） | 未复采，但该串会原样进界面文本（第十一轮实测 `inBody:true`）→ 把用户指到 Q24 已改名的死页 | **绿 · 阻塞（B11-6 另一半）** |
| **E3 对照** | 同一锚点、同一死页名，只改用「」：`…，失败成因见「模型映射」页` | `✗ J2 …违规指路：…logs.js→「模型映射」页` | —— | **红**：坐实 E2 的因是**括号白名单**，不是"没扫到 logs.js" |

### §F 族 · **本轮新机制 `cssHiding()` 的边界**（B11-1 只修了一半）

新机制本体：`scripts/verify_v2_frontend.mjs:778-832`（`HIDE_DECL` / `hidesIn` / `cssHiding` → `{classes, ids, tags}` 三集），接入点 `:833 isInvisible()`（class/id）与 `:873 visibleText()`（裸标签）。它确实堵住了第十一轮 B11-1 的主案发现场（顶层 `.alert-warn{display:none}`），但**"扫任意嵌套层级"这句注释（`:783-784`）与实现不符**，其余 6 条边界各带一条用户可见坏结果。

**(F-0) 代码级探针**（不靠门色，直接跑门里切出来的原函数；`/tmp/ix12-cssprobe.mjs` 逐字切 `:778-831`，零手抄）：

| 输入（都追加在 `.hidden{display:none!important}` 之后） | 派生出的 `classes` | 真浏览器会不会藏 | 判 |
|---|---|---|---|
| `.alert-warn{display:none}`（顶层） | `["hidden","alert-warn"]` | 会 | 机制有效 |
| `@media (min-width: 1px) { .alert-warn { display: none; } }` | **`["hidden"]`** | **会** | **漏** |
| `@layer hide { .alert-warn { display: none; } }` | **`["hidden"]`** | **会** | **漏** |
| `.alert-warn:first-child { display: none; }` | **`["hidden"]`** | **会**（第一条横幅） | **漏** |
| `main div { display: none; }` | **`["hidden"]`** | **会**（整块内容塌） | **漏** |
| `#hour-chart { height: 0 !important; }` | `["hidden"]`、`ids=[]` | **会**（图表压成 0 高） | **漏** |
| `.ALERT-WARN { display: none; }` | `["hidden","alert-warn"]` | **不会**（类名大小写敏感） | **误伤方向** |
| `.not-a-real-ancestor .alert-warn { display: none; }` | `["hidden","alert-warn"]` | **不会**（祖先不存在） | **误伤方向** |
| `.hidden { display: block !important; }` | `["hidden"]`（仍算隐藏） | **不会**（后面的 `!important` 顶掉前面的） | **模型只有"藏"没有"露"** |
| 仓库 `base.css` 原样 | `["hidden","nav-toggle","drawer-mask","ops-dot"]`、`ids=[]`、`tags=[]` | —— | 现量只有 4 个类 |

> 根因（逐行）：`:802-807` 里 `@media/@supports` 分支把 `atRule` 置 1，随后 `sel = atRule !== 0 ? "" : head`（`:805`）——**嵌套层的 `.selector` 被直接丢成空串**，到 `}` 时又走 `if (atRule !== 0) { atDepth -= 1; … }`（`:812-814`）这条不填集合的分支。所以注释说的"`@media` 里面的（规则）仍然要算"在实现里等于没算；`@layer` 同理。`ids` 集在真实 `base.css` 上派生结果为**空**，K8 那条容器判据（`:918-921`）只看**内联** `attrs`，因此 CSS 侧对图表容器一条也接不上。

**(F-1) 门色 + 浏览器复采**（载荷 std；浏览器 = 我的临时实例 :57388，截图 `/tmp/ix12-shots/`）

| # | 变异（`to` 追加在锚点行后） | 门输出 | 真实 Chrome 读数 | 判 |
|---|---|---|---|---|
| **F1** | `@media (min-width: 1px) { .alert-warn { display: none; } }` | `实测 84 项，通过 84 项，失败 0 项` | `bannerH [64,64,64,83] → [0,0,0,0]`、`bodyTextLen 873 → **459**`（四条配置告警整族从屏幕上消失，`F1-@media.png`） | **绿 · 阻塞** |
| **F3** | `.alert-warn:first-child { display: none; }` | 84/84 全绿 | `bannerH [64,64,64,83] → [**0**,64,64,83]`、`bodyTextLen 873→760` → **恰好吞掉第一条告警**（最隐蔽的形态：界面看起来"还有三条"，用户不会发现少了一条） | **绿 · 阻塞** |
| **F5** | `@layer hide { .alert-warn { display: none; } }` | 84/84 全绿 | `bannerH → [0,0,0,0]`、`bodyTextLen 873→459` | **绿 · 阻塞** |
| **F7** | **`index.html`** 里 `<link>` 之后插 `<style>.alert-warn { display: none; }</style>` | 84/84 全绿（`cssHiding` 只吃 `read("css")` = `base.css`） | `bannerH → [0,0,0,0]`、`bodyTextLen 873→459` → **样式来源不止 `base.css`**：壳层内联 `<style>`、`templates/*.html` 里那 9 个 `<style>` 块（实测 `grep -c "<style"`）全在模型外 | **绿 · 阻塞** |
| **F8** | `main div { display: none; }` | 84/84 全绿（规则③"后代裸标签"被整条排除） | `bodyTextLen 873 → **137**`、`bannerH [0,0,0,0]`、`chartH 160→0` → 内容区里**每一个 div 都不显示**，整个工作台只剩壳（`F8-main-div.png`）。排除它的理由是"防误伤 `.nav-item span`"，但代价是这条最狠的写法完全不被观察 | **绿 · 阻塞** |
| **F9b** | `#hour-chart { height: 0 !important; }` | 84/84 全绿（`hidesIn` 要求 `height:0` 与 `overflow:hidden` **同块**；K8 又只看内联 attrs） | `chartH 160 → **0**`、`chartVisibleBars 1`（柱还在 DOM 里）→ 趋势卡塌成一条 0 高空白带（`F9b.png`） | **绿 · 阻塞** |
| F9a | `#hour-chart { height: 0; }`（不带 `!important`） | 84/84 全绿 | `chartH` 仍 **160** —— 容器自带内联 `style="height:160px"` 压过外部规则 | 绿但**无坏结果** → 记 ⑥ |
| **F2** | `.hidden { display: block !important; }`（把该藏的**露**出来） | 84/84 全绿 | 门侧仍把 `class="hidden"` 判成隐藏（探针第 ⑨ 行）；仓库里真在用这条工具类的是 `logs.js:151` 的折叠明细行 `<tr class="hidden">`。**坏结果未复采**：我的临时实例没有任何请求流水（`hiddenRows:0`，基线与变异两次实测相同）→ 按登记处理 | **绿 · 理论限制（模型无"反向"语义，缺可判别的行）** |
| **F6** | `.ALERT-WARN { display: none; }`（大小写） | `✗ K1 正文缺失=4`、`✗ K9`（rc=1，82/84） | 浏览器 `bannerH [64,64,64,83]` **完全正常**（HTML 类名大小写敏感）→ 门**误伤**：真实 CSS 里出现大写变体或命名习惯不同时，判据会红而用户什么都没丢 | **红 · 误伤方向** |
| **F12** | `.not-a-real-ancestor .alert-warn { display: none; }` | `✗ K1 正文缺失=4`、`✗ K9`（rc=1） | 未复采（该祖先在页面里根本不存在，按 CSS 语义不可能命中；F6 已实测同型"浏览器不受影响"）→ **只取最右段**使复合选择器把"在某个容器里才藏"放大成"全局藏" → 误伤 | **红 · 误伤方向** |
| **F11** | `p { display: none; }`（裸标签全局） | 84/84 全绿 | 未复采（总览产出的关键正文不在 `<p>` 里，门未误伤） | 绿 · 无坏结果 → 记 ⑥ |
| **F1b 对照** | 顶层 `.alert-warn { display: none; }`（实现者变异表那颗） | `✗ K1`＋`✗ K9`，rc=1 | —— | **红**：证明 F1/F3/F5/F7/F8 的绿不是"样式表面板根本没接上"，而是**恰好漏在嵌套层/伪类/选择器精度/其它样式来源这四把尺子之外** |

> **与第十一轮的对照**：第十一轮同样的 `.alert-warn{display:none}` 逃逸（V1）本轮确实被堵（F1b 红）；但把同一条规则挪进 `@media`（F1）、挪进 `@layer`（F5）、加个 `:first-child`（F3）、换到 `index.html` 的 `<style>`（F7）、写成 `main div`（F8）或 `#hour-chart{height:0!important}`（F9b）——**六种写法全部重新回到"门 84 项全绿 + 屏幕上少东西"**。也就是说这一轮补的是"一条具体写法"，不是"层叠语义"；同一族里少一根尺子就少一类堵不住。

### §G 族 · 本轮新修的 J3 / K4 各自的口子

| # | 变异 | 门输出 | 判 |
|---|---|---|---|
| G1 | SET：`<div class="card-head"><span class="card-title">维护</span></div>` → 追加 `<span class="value">端口改动请到「模型资源」页重启网关</span>` | 84/84 全绿 | **绿 · 阻塞（B11-6 剩余）**：J3 的 `ROUTE_MARKERS`（`:632-636`）本轮虽改成"由源码控件标记派生"，但**动作正则仍只有 4 条手写项**（映射/换 Key/开关/档位），`重启` 不在表内 → 页名真存在（J2 绿）、归属无从判定；而"重启网关"按钮 `#st-restart` **就长在本页**（`settings.js` maintSection）→ 把人就近在眼前的动作支到另一页 |
| G2 | dash：`查看日志</a>` → `查看日志</a> · <a href="#/resources">查看资源</a>`（文案与目标页不符） | 84/84 全绿 | **绿 · 阻塞**：K4 只验"路由存在"，不验"文案承诺的动作在那一页"；同一族第十一轮 X1（`查看日志` 跳 `#/resources`）至今无判据 |
| **G3 对照** | dash：同上锚点 → `<a href="javascript:alert(1)">点我</a>` | `✗ K4 …内部 2 条；外链 0 条`（rc=1） | **红**：K4 的外链红线（B11-7）在 `http(s)://`、`//host` 之外**顺带**接住了 `javascript:` 伪协议（被"不是导航项"这条抓住）→ 本轮未找到 B11-7 的逃逸，登记为已修 |

## ④ 阻塞项

| ID | 洞（机制级） | 复现（变异 → 门 → 用户实际看到） | 建议修法（只给口径，本轮不动生产代码） |
|---|---|---|---|
| **S-42 B12-1**（=B11-3 未修，**最严重**） | **七页里只有总览被真跑；`api.js`/`components.js` 的行为零执行**。`browserFn` 只编译 `api + dash`（`:713-714`），而假 `fetch`（`:719-725`）对已知路径**恒回 `ok:true`** → 非 2xx 分支没有任何输入能打进去；`settings/apiaccess/logs/stats/models/templates/components` 只进 `copySources` 文本面 | A1（400 → 绿色「配置已保存并热重载生效」+ 服务端 `fail_threshold` 仍 2，**Chrome 实测**）、A2（点「取消」→ `tokensInConfig` 少一条，**实测**）、A3（`copied:[]` + toast「密钥已复制」，**实测**）、A4（密钥单元格 `mg-fake-0123456789abcdef`，**实测**）、A5（`#st-save.disabled` 恒 true 而徽章「有未保存修改」在场，**实测**）、A6/A7/A9；**A11：三条同时种上，门 84 项全绿 + `可红 104/104`** | ① 每页一套假 DOM 真跑 `renderXxx(root)`，断言"该页承诺的控件在产出里且可见"（`#st-save`、`[data-tkey]`、`[data-delkey]`、`[data-tkval]`、`#log-table`…）；② `api()` 用假 `fetch` 跑**四种响应**（200 / 400+errors / 401+detail / 非 JSON），断言非 2xx **必抛**且抛出文案含后端原因 —— 关键是让 `fetchStub` 能按用例返回 `ok:false`，否则这条分支永远不会被观察；③ `confirmDialog/copyText/switchEl/modal` 各跑一次真行为断言（取消→`resolve(false)`、`clipboard.writeText` 被调用、失败分支不得报"已复制"、footer 子节点平铺）；④ `maskVal` 之类的脱敏函数导出并单测（前 5+`****`+后 4，且明文不得出现在产出 HTML 里） |
| **S-42 B12-2**（=B11-2 未修） | **壳层零判据**：门里 `grep 'content\|crumb\|stylesheet\|<link'` 只命中注释与变异表字面量；`read("index")` 仅 `:399 dotTag` + `:499 navAnchors` 两处；`main.js` 只有红点那块被执行，`route()`/`applyTheme()`/自动刷新三段不跑 | B1（`contentNull:true / banners:0 / innerText 873→137` **整站不启动**）、B3（`contentDisplay:"none"` 而 DOM 7 子节点，**内容区纯白**）、B4（`contentInert:true`、`elementFromPoint` 返回 **null**、点击后 `location.hash` 不变，**全页点不动**）、B5（`--err-bg` 空、`boxShadow:"none"`、`bodyBg` 透明，**裸样式**）、B6（`contentChildren:0 / dataTheme:null`）、B7（导航项高度 36→**0**，「请求日志」入口消失）、B8（点深色后 `data-theme` 仍 `"light"`） | ① 把 `visibleText()`/`isInvisible()` **同样跑在 `index.html` 壳层**上（七个导航项 + `#content` + `#crumb-group` + `#tb-title` + `#ops-dot` + `#toast-wrap` + `#modal-root` 都要"存在且可见"）；② **id 交叉核对**：各页 `getElementById("X")`/`querySelector("#X")` 的 id 集 ⊆ 壳层真实出现的 id（B1/B2 正是缺这条）；③ `<link href>`/`<script src>` 指向的文件必须真在 `static/` 下；④ `route()` 用假 `location.hash` + 假 PAGES 真跑一遍，断言面包屑/标题/内容容器三步都落；⑤ 主题：三态各跑一次 `applyTheme()`，断言 `data-theme` 与 `resolveTheme(mode)` 一致 |
| **S-42 B12-3**（本轮新，**样式表层叠只学了一层**） | `cssHiding()` 的"任意嵌套层级"名不副实：`@media/@supports/@layer` 内的**选择器被丢成空串**（`:805`），最右段含 `:` 直接 `continue`（`:819`），后代+裸标签整条排除（`:825` `pieces.length === 0`），`height:0` 要与 `overflow:hidden` **同块**才算（`:780-781`），且**只吃 `base.css` 一个样式来源**；模型只有"藏"没有"露"（反向 `!important` / 后写规则不被观察）；类名/id 一律 `toLowerCase()` | 门侧六条逃逸（F1/F3/F5/F7/F8/F9b 全 84/84 绿）+ 探针原文（五种写法都只派生出 `classes=["hidden"]`）+ Chrome：F1 `bannerH[0,0,0,0]`、F3 `bannerH[**0**,64,64,83]`、F5 同 F1、F7 同 F1（样式在壳层 `<style>`）、F8 `innerText 873→**137**`、F9b `chartH 160→0`；误伤两条（F6 浏览器 `[64,64,64,83]` 正常而门 `✗ K1 正文缺失=4`；F12 同型） | ① 递归解析：`@media/@layer` 内层**保留选择器**（把 `sel` 赋成 `head` 而不是空串），媒体条件至少按"桌面视口恒成立"处理；② 最右段允许伪**类**选择元素本体（`:first-child/:nth-child/:not(...)` 等结构伪类要算，只有 `::` 伪元素与 `:hover/:focus` 这类交互态才排除）；③ 复合选择器保留"祖先必须出现"这条约束（现在只取最右段 → 大小写/不存在祖先两个方向都会误伤），并去掉类名/id 的 `toLowerCase()` 折叠；④ `height:0` 单独算"塌陷"（配 `overflow` 只是加分项），`!important` 与源码顺序按真层叠算出**最终值**，而不是"命中过任一隐藏声明"；⑤ 样式来源集合化：`base.css` + `index.html`/`templates/*.html` 里所有 `<style>` 一起进 `cssHiding`；⑥ Z1 的 25 例扩到"写法维度"（@media/@layer/伪类/复合/大小写/`!important` 反向/第二样式文件各至少一例） |
| **S-42 B12-4**（=B11-4 未修） | **K9 是"整页 `<script>` tripwire"，不是逐字段转义判据**：哨兵只进 `warnings.message`（`:741-742`），其余字段全靠"输出里有没有字面 `<script>`/`onerror=alert(1)>`" | C1（资源名列去 `esc`：std **绿**、hostile `<img onerror=alert(document.domain)>` **绿**、h2 `<svg onload=…>` **绿**）、C2（「最近错误」列去 `esc`：std/h2 **绿**，hostile 只因含字面 `<script>` 偶然 `✗ K9`）、C3（日志模型列去 `esc` **绿**）；现成未转义管道 `main.js:54` `${e.message}` | ① 哨兵**逐字段**塞（`resources[].name/vendor/account/last_error`、`today_by_hour[].hour`、`logs.rows[].system_model/error_summary`），每字段一份载荷，断言产出里活标签数为 0；② 把"整页 tripwire"换成**结构判据**：`${…}` 插值若引用后端可控字段而未过 `esc()` 即红（静态可判，`main.js:54` 会立刻被抓）；③ 载荷里同时放 `<script>` / `<img onerror=…>` / `<svg onload=…>` 三种形态，缺一条红 |
| **S-42 B12-5**（=B11-5 未修） | **数值真值无判据**：K3 只认标签、K5 坏插值黑名单缺 `NaN/null/Infinity`、卡头数字不与载荷对表、A 段不钉成因句 | D1（八张卡 `values=["",…,""]`，**实测**）、D2（界面出现**「成功比 NaN%」**，**实测**）、D3（`switch_count=3` 的 traffic 载荷上写死 0 仍 84/84 绿 = 判据不具可判别性）、D4（告警③成因改成"临时冷却·无需处理·稍后自动恢复"仍绿） | ① K5 坏插值集补 `NaN/Infinity/-0/null/0%/undefined%`，并断言每张指标卡 `visibleText(metricValue).length>0`；② **哨兵数字对表**：把 `switch_count/success/failed/requests/tokens` 换成互不相同的可辨识值，断言界面文本出现同一数字（写死常量立刻红）—— 这条 K10 已经给"连续失败/处理中"两列立过，请推广到指标卡与卡头；③ 四类告警各钉一条成因子句白名单（③类必含「已停用或凭据失效」且含处置动作；②类不得出现「无需处理/可忽略/自动恢复」） |
| **S-42 B12-6**（=B11-8 未修） | **判据缺省 fail-open 原样在**：`:918 (… || ["", ""])[1]` 把"容器不存在"洗成"容器可见"；同类缺省实测还剩 `:250 titleOf`、`:310`、`:924` | E1（只改容器 id → 门 `✓ K8`，Chrome `chartChildren:0`、`chartBoxExists:false`、`innerText 873→811` = 160px 空白带） | ① 关键容器正则**取不到即红**（缺省 `null` + `if (!m) return false`），全门同类缺省过一遍；② K8 加结构断言：`bars` 必须是**那个容器**的子节点（现在 `bars` 来自假 DOM 的 `nodes` 表、容器来自 HTML 串，两边可以各说各话）；③ Z1 类自测补"缺省形态"用例（空串/null/匹配失败） |
| **S-42 B12-7**（=B11-6 剩余） | **指路仍靠语法白名单 + 手写动作表**：括号集只有「」/『』（`:574`、`:667`），`ROUTE_MARKERS` 只有 4 条动作（`:632-636`），K4 只验路由存在 | E2（`见【模型映射】页` 84/84 绿；对照 E3 同串改「」立刻 `✗ J2`）、G1（`请到「模型资源」页重启网关` 绿，按钮就在本页）、G2（`查看资源` 指到另一个真页面 绿；对照 G3 `javascript:` 反而红） | ① 候选集反向取：抽出源里**所有**括号形态（`「」『』【】“” '' ()`）再对 `navLabels ∪ 死页名黑名单`；② 建**死页名黑名单**常量（模型映射/系统模型/接入管理/运行监控…），全文命中即红，不靠语法猜；③ 动作↔页归属表由"页面实现文件里真实存在的控件标记"**全量派生**（现在只派生了 4 个动作，其余仍靠人加正则）；④ K4 拆出"文案动作与目标页一致"这条（`查看日志` 的 `href` 必须落在日志页） |
| **S-42 B12-8**（本轮新） | **`pytest 715 passed` 不可逐字复现**：全量 `1 failed, 714 passed`，失败项 `tests/unit/test_v2_wiring_guard.py::test_guard_catches_a_planted_dead_method`；单跑同文件 `6 passed` | 根因（代码级）：该测试 `tests/unit/test_v2_wiring_guard.py:433-436` 往**真包目录** `model_gateway/_wiring_canary_pkg/` 写 `__init__.py`/`a.py`/`b.py`，再让护栏扫整个 `model_gateway` 包 —— 与并行面板（或同一工作树上的第二次跑）竞态：另一个进程在 `finally` 里删掉该目录时，本进程的覆盖面少一块。仓库 `data/` 与生产源码未受影响（本轮实测该目录已清理、`git status --porcelain` 开工/收工同为 85） | ① canary 写 `tmp_path` 并用 `sys.path` 注入，不要往真包落盘；② 若必须写工作树，加**进程级文件锁**并在 AGENTS/runbook 注明"全量 pytest 不可并行"；③ 交付口径请写实测原话（`1 failed, 714 passed`）而不是四舍五入成 `715 passed` |

> 严重度排序（我的判断）：**B12-1 > B12-3 > B12-2 > B12-5 > B12-4 > B12-6 > B12-7 > B12-8**。
> B12-1 仍排第一，因为它是**主动说谎**：用户带着根本没生效的 `y/m/超时/冷却` 去跑生产，界面上还留着一条绿色成功条作为"已经生效"的伪证。
> B12-3 排第二，因为它本轮是"半成品被当成成品"：注释声称覆盖了 `@media`，探针证明一条也没覆盖；同一条规则换个写法（挪进媒体查询、加个 `:first-child`、换到壳层 `<style>`）就整族重新逃逸，而六条里有三条（F3/F8/F9b）是"页面看起来还好，只是少了一块"这种用户最难自己发现的形态。

## ⑤ 对照实验（证明判据不是空过）

**9 条如期变红**（同一批驱动器、同一份 std 载荷，与 38 条绿互为对照）：

| # | 变异 | 变红的判据 |
|---|---|---|
| A10 | `logs.js` 空态文案加 `可去「插件市场」页核对` | `✗ J2 违规指路：…logs.js→「插件市场」页`（⇒ A6 的绿不是"文件不入面"） |
| B10 | 壳层侧栏 `<span>资源池设置</span>` → `<span>模型映射</span>` | `✗ J1`（`models:≠资源池设置`）＋ `✗ J2`（⇒ 壳层有判据，但只有标签/红点这一条线） |
| **F1b** | 顶层 `.alert-warn { display: none; }`（实现者本轮自己加的那颗） | `✗ K1 横幅节点=4 期望=4 正文缺失=4`＋`✗ K9`（⇒ 新机制在它选中的写法上真的有效；F1/F3/F5/F7/F8 的绿是**边界**问题不是"没接上"） |
| F6 | `.ALERT-WARN { display: none; }`（大小写） | `✗ K1`＋`✗ K9`，而浏览器横幅高度不变 ⇒ **误伤方向**也证明门是活的 |
| F12 | `.not-a-real-ancestor .alert-warn { display: none; }` | `✗ K1`＋`✗ K9`（只取最右段 → 误伤） |
| C4 | `${esc(w.message \|\| "")}` 去 `esc` | `✗ A14 告警文案经 HTML 转义`＋`✗ K9` |
| D5 | `metricCard("运行状态"` → `"网关状态"` | `✗ K3 八张指标卡全部可见`（⇒ K3 认标签不认值） |
| E3 | 同一死页名改用「」括号 | `✗ J2 …logs.js→「模型映射」页`（⇒ E2 的绿是括号白名单） |
| G3 | `<a href="javascript:alert(1)">` | `✗ K4 …内部 2 条；外链 0 条`（⇒ K4 的路由存在性 + 外链红线是活的） |

另两组反向自证：

- **载荷维度**：把我派生的 `traffic` 载荷（`today.requests=120 / switch_count=3 / aborted=5`）喂给基线门 → 84/84 绿；喂给 D3（切换数写死 0）与 A7（成功率分母丢 `aborted`）→ 仍 84/84 绿 ⇒ **"绿"不代表界面数字与后端一致**（B12-5 的"可判别性"缺口）。
- **`--mutation` 与这些洞不相交**：A2+A3+A4 三条同时在场时跑 `--mutation` → `可红 104/104；每条断言都有对应变异`（`/tmp/ix12-mutation-with-A234.txt`）。

## ⑥ 理论限制 / 登记项（拿不出用户可见坏结果，或实测无坏结果）

- **T1 样式来源不止一处，但只有 `base.css` 被证明有害**：`templates/*.html` 里 9 个 `<style>` 块（实测 `grep -c "<style"`）与 F7 同型；本轮只用 F7（壳层 `<style>`）拿到"四条横幅全灭"的实测，模板预览页那份未单独复采（可达但不在七页主流程）。
- **T2 `height:0` 不带 `!important` 打不过内联**（F9a：`chartH` 仍 160）→ 无坏结果，不计阻塞；但它同时说明"内联压外部"这层优先级门也没建模（若哪天删掉 K8 依赖的内联 `height:160px`，外部规则就会赢，门对此无感）。
- **T3 裸标签全局隐藏（F11 `p{display:none}`）**：门 84/84 绿 —— 总览关键正文不在 `<p>` 里，本轮拿不出坏结果 → 登记。但 `settings.js` 的 `.form-hint` 是 `<p>`，说明误伤面还在。
- **T4 `.hidden` 反向（F2）**：门侧仍把 `class="hidden"` 判成隐藏（探针 ⑨），但**坏结果未复采** —— 我的临时实例没有请求流水，`logs.js:151` 折叠明细行 `hiddenRows` 在基线与变异两次实测都是 0（不可判别）。这与 D3 是同一件事：判据要能红，喂给它的数据必须先可判别。
- **T5 `switchEl` 显示反转（A8）**：与第十一轮 T5 同型（短暂反相、整页重绘纠正），不计阻塞；但两处调用点都靠"保存后重绘"掩盖，这层依赖仍无判据。
- **T6 `main.js:54` 的 `${e.message}`**：静态未转义管道是事实，**浏览器侧 XSS 落地未复采**（见 §C 行末）→ 不升格为独立阻塞，并入 B12-4 修法②。
- **T7 门与载荷耦合（第十一轮 T1 仍在）**：判据把"四类告警 + 一条熔断资源 + `C=3/in_flight=1`"当载荷前提；本轮用 std/traffic/hostile/hostile2 四份载荷验证的是"逃逸与载荷无关"，不是"门能在用户实况上跑绿"。交付里"84 项全绿"不能被读成"用户当前界面没问题"。
- **T8 截图通道不稳**：`Page.captureScreenshot` 两次 CDP 超时（D1 之后中止过一次批跑），`/tmp/ix12-shots/` 只留下 §A/§B/§F 那几张；其余一律以 `getBoundingClientRect/getComputedStyle/innerText/elementFromPoint/剪贴板挂钩` 的**数值读数**为证。
- **T9 假 DOM 仍会自动建节点**（`:708 getElementById: (id) => (nodes[id] ||= {...})`）：这是 B12-6/E1 能长期存在的机制性原因。
- **T10 本轮未做（诚实登记，不为了收尾而略过证据）**：A6/A7/A9/B2/B9/D4/E2 的浏览器形态未复采（门绿均为实测）；`--mutation` 变异表自身锚点漂移（第十一轮 T8"门自身规则可被静默删除"）本轮未重复验证；J3 在 Python 侧常量展开（`expandPageConsts`）上的漏检面未攻。

## ⑦ 收工自证

```
$ md5 -q scripts/verify_v2_frontend.mjs
727290d4df2b619884772c8aa961bf28        # 与开工快照一致（门源码未被我为通过而改）

$ # 副本 vs 仓库 逐文件 md5（15 个靶文件）→ 15/15 same，0 个 DIFF
same  js/pages/dashboard.js   same  index.html   same  css/base.css
same  js/api.js               same  js/components.js   same  js/main.js
same  js/pages/apiaccess.js   same  js/pages/logs.js   same  js/pages/models.js
same  js/pages/resources.js   same  js/pages/settings.js  same  js/pages/stats.js
same  js/pages/templates.js   same  model_gateway/main.py  same  scripts/verify_v2_frontend.mjs
另：diff -rq 副本/js 仓库/js  →  COPY-CLEAN-ALL-JS

$ git status --porcelain | wc -l
开工：85
收工：85      # 本轮我未改动仓库任何文件（docs/ 被 .gitignore 忽略，本报告不入数）

$ curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:57388/    # pkill -f ix12-serve.py 之后
000                  # 临时实例已下线；:8300 全程未触碰（开工时用户实例未在跑）
```

- 变异只施加在 `/tmp/mgw-accept-12-ix/`（`rsync -a` 排除 `data/`、`.git/`、`.venv/`、`__pycache__/`）；驱动器每条跑完即还原并断言 `read()==原内容`；浏览器批次里我用 `node:fs` 直改副本，全部在 `finally` 还原并二次复核（`restored-check {"inert":false,"contentId":true}`、`restored-file {"noesc":false}`、`COPY-CLEAN-ALL-JS`）。
- 临时实例 `/tmp/ix12-serve.py`：端口 **57388**（避开 :8300 与并行面板占用的 8399），数据目录 `/tmp/ix12-data`，合成假 Key `mg-fake-*` / `sk-fake-*`，`base_url=http://127.0.0.1:9`（discard 端口）→ **未发起任何真实上游调用、未写真实凭据**；期间对它的 `PUT /admin/api/config`（改 `fail_threshold`/`retry_per_request`、试种植活标签资源名、删过一条假密钥）全部落在 `/tmp/ix12-data/config.yaml`；**仓库 `data/` 全程只读，未写一个字节**。
- 浏览器证据：ego-browser 任务空间 5 个（A-family / B-family shell / F-family css cascade / D-E-A5 / C-family xss），截图 12 张在 `/tmp/ix12-shots/`，其余为内联数值读数。
- 可复跑：

```
MGW_V2_VISIBLE_DIR=/tmp/ix12-fixture-baseline .venv/bin/python scripts/ui_verify_v2_visible.py
node /tmp/mgw-accept-12-ix/scripts/verify_v2_frontend.mjs /tmp/ix12-fixture-baseline/overview.json [--mutation]
python3 /tmp/ix12-drive.py /tmp/ix12-a.json      # 另：-b / -f / -f2 / -cde / -h2 / -g
node /tmp/ix12-cssprobe.mjs                       # cssHiding 探针（从门源码逐字切出，零手抄）
IX12_PORT=57388 .venv/bin/python /tmp/ix12-serve.py
```

原始输出：`/tmp/ix12-baseline.txt`、`/tmp/ix12-mutation.txt`、`/tmp/ix12-mutation-with-A234.txt`、`/tmp/ix12-pytest.txt`、`/tmp/ix12-*.result.json`（每条含锚点命中数、门汇总行与红项原文）。
