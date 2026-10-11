# ix 第十轮验收 —— 只攻「第九轮新加的门机制本身」

- 角色：资深交互设计师（验收，不改生产代码）
- 靶子：第九轮 S-32/S-33 新加的四条机制 —— ① `visibleText()` 结构化可见性清洗；② `K0~K9` 执行真实 `renderDashboard`；③ `copySources` 目录自动发现 + `PAGE_REFS` 三型认页名；④ `C16` 矩阵
- 工作区：`/tmp/mgw-accept-10/`（仓库副本，排除 `data/`、`.git/`）；**跑的是副本里的脚本**（`ROOT` 因此解析到副本）
- 基线（副本，原样）：`实测 79 项，通过 79 项，失败 0 项`；`--mutation` → `可红 87/87；每条断言都有对应变异`
- 造了 **26 个变异**（21 个施加成功，5 个锚点不存在自动跳过并换锚点重做）。结果：**9 条用户可感知的坏改动，门 79 项全绿、`--mutation` 87/87 也碰不到**；另有 8 条对照/理论限制。

## ① 结论

**第九轮的门仍然有洞，而且洞在机制的定义方式上，不在个别判据上：**

1. `visibleText()` 是一个**"隐藏写法"的白名单**（`\shidden` / `aria-hidden="true"` / `display:\s*none` / `visibility:\s*hidden`，大小写敏感、属性值形状敏感），不是可见性模型。浏览器里"看不见"的写法远多于这四种：`opacity:0`、`height:0;overflow:hidden`、`position:absolute;left:-9999px`、`visibility:collapse`、`<template>`、`<noscript>`、裸 `aria-hidden`、大写 `VISIBILITY: HIDDEN` —— **八种全部过关**。第九轮花大力气把"DOM 里有文本"升级成"可见文本"，但"可见"仍然是**字符串匹配**，所以只是把逃逸面从"三种藏法"收窄成"八种藏法"。
2. `K6`/`K8` 没有吃同一套清洗：`K6` 的**表头列名从原始 HTML 正则抓取**（不经 `visibleText`），`K8` 只看 `chartHtml.length > 100`（完全不做可见性）。于是"表头藏掉"和"图表画了但容器塌成 0 高"都绿。判据族内部**口径不一致**（K1/K2/K3 用清洗，K6/K8 用原文），这正是第八→第九轮被指出的老毛病的残留。
3. `C16` 号称"按其它字段/按量级分叉即判红"，但矩阵的**字段形态集是手工 4 组**，`last_error` 最长 40 字（`verify_v2_frontend.mjs:214-217` 的 `FULL` 恰好 40）。按 `last_error.length > 40` 分叉 → 矩阵逐字节相同、门全绿，而真实 429 文案（70 字）在生产里必然出现 —— **同一列两套措辞**，恰好是 C16 自己声明要防的。
4. `copySources` 的自动发现面写死了三种扩展名（`**/*.py`、`web/static/js/**/*.js`、`index.html`，`verify_v2_frontend.mjs:70-75`），**`css/base.css` 虽在 `FILES` 里却不在 `copySources` 里**（具名补录清单 `:541-544` 漏了 `"css"`），`web/static/templates/*.html` 整个目录不在面内 —— 而 `main.py:472` 是 `StaticFiles(directory=static_dir, html=True)` 挂在 `/`，模板页**可以 HTTP 直达**。CSS 生成的可见文案（`::after { content }`，本项目已在用：`base.css:155/404/445`）是 J2 与 K 段的双盲区。
5. `PAGE_REFS` 的三型认法里，cue 动词是**闭集**（`到|前往|请到|打开`）且括号型强制后跟"页"字 → `或去「模型映射」通过映射创建` 全绿（对照：保留"到 … 页"裸串 → J2 立刻红，说明只堵了一半）。
6. 好消息（真闭合了）：正文塞 `title=`（V10 → K1+K9 红）、钟点搬到别的列（V12 → K6 红）、未闭合隐藏标签（V24 → fail-safe 红）、tooltip 里写死页名（V25 → C3+J2 红）、新增 `pages/zzz.js` 带死页名（V19/V20 → J2 红，且变异模式在基线红时整体拒绝）—— **这三条机制的"设计意图"层面站住了**，逃逸全部来自"实现方式是字符串匹配/白名单/手工集合"。

`可红 87/87` 的自证只证明"表里那 87 个变异各自能红"，不证明门封住：**本轮 9 条阻塞没有一条在表里**。

## ② 变异表

锚点文件：D = `model_gateway/web/static/js/pages/dashboard.js`，M = `.../pages/models.js`，CSS = `.../static/css/base.css`，TPL = `.../static/templates/template-providers.html`，R = `.../pages/resources.js`。
门输出原文 = 副本里 `node scripts/verify_v2_frontend.mjs /tmp/ov10.json`（fixture 为 S-32 记录里那份现采 overview）。

| # | 变异（施加处） | 门输出原文 | 用户看到什么变了 | 打红？ |
|---|---|---|---|---|
| V1 | D：`class="alert alert-warn"` → `…alert-warn hidden"`（`.hidden{display:none!important}` 真实存在于 `base.css:108`） | `✗ A1 渲染出 .alert-warn 横幅` / `✗ K1 … 横幅节点=0 期望=4 正文缺失=0` | 告警横幅整块不见 | **红（但是假因）**：红的是字面 class 串匹配，不是可见性判据（见 ④ T1） |
| V2 | D：横幅加 `style="opacity:0"` | `实测 79 项，通过 79 项，失败 0 项`（`✓ K1`） | 总览页顶部**一片空白**：启动脚本 nohup 关窗后，配置告警的唯一界面出口消失 | **否 · 阻塞 B10-1** |
| V3 | D：横幅加 `style="height:0;overflow:hidden"` | 同上，79/79 全绿 | 横幅占位塌成 0，四句告警全看不见 | **否 · B10-1** |
| V4 | D：横幅加 `style="VISIBILITY: HIDDEN"`（CSS 属性名大小写不敏感） | 79/79 全绿 | 同 V2；第九轮明确把 `visibility:hidden` 列为要堵的藏法，只因为**大写**就绕开 | **否 · B10-1** |
| V23 | D：横幅加 `STYLE="DISPLAY: NONE"`（属性名+值全大写） | 79/79 全绿 | 同 V2 | **否 · B10-1** |
| V26 | D：横幅加 `style="visibility:collapse"` | 79/79 全绿（`✓ K1 每条告警都作为可见文本出现`） | 同 V2；正则只认 `visibility:\s*hidden` | **否 · B10-1** |
| V5 | D：横幅加 `style="position:absolute;left:-9999px"` | 79/79 全绿 | 横幅被搬到屏幕外，页面上没有告警 | **否 · B10-1** |
| V6 | D：正文 `<div>${esc(message)}</div>` → `<template>…</template>` | 79/79 全绿 | 横幅只剩「配置告警」标题，正文一行空白（`<template>` 内容浏览器不渲染） | **否 · B10-2** |
| V7 | D：正文包进 `<noscript>…</noscript>` | 79/79 全绿 | 开着 JS 的正常用户永远读不到告警正文 | **否 · B10-2** |
| V8 | D：正文加**裸** `aria-hidden`（无 `="true"`） | 79/79 全绿 | 屏幕阅读器用户完全读不到告警正文（视觉正常） | **否 · B10-3** |
| V9 | D：正文加 `ARIA-HIDDEN="TRUE"` | 79/79 全绿 | 同 V8；门自证表把小写 `aria-hidden="true"` 判为 🔴 B-11 坏改动，大写即逃逸 | **否 · B10-3** |
| V10 | D：正文搬进 `title="${esc(message)}"`，正文改「详见本页」 | `✗ K1 … 横幅节点=4 期望=4 正文缺失=4`、`✗ K9` | —— | 红（第九轮声称项成立） |
| V11 | D：`<th title="…">最近错误</th>` → 加 ` hidden`（**表头单元格隐藏**） | 79/79 全绿 | 资源健康表**「最近错误」列标题消失**：那一列里的"，至 17:04"还在，但用户不知道这列是什么、分不清"风控熔断等 30 分钟"和"该查 Key"（K6 的表头是从**原始 HTML** `<th[^>]*>([^<]*)</th>` 抽的，不经 `visibleText`） | **否 · B10-4** |
| V12 | D：在「冷却剩余」前插一列把 `last_error` 也印出来 | `✗ B6`、`✗ K6 … 表头=资源,状态,连续失败,处理中,冷却剩余,最近错误 最近错误列=1800s 冷却剩余列=ZCode 风控熔断（30min，全局），至 17:04 串列=2` | —— | 红（列位契约成立） |
| V13 | D：`drawHourChart` 里 `box.innerHTML=` 前插一行 `box.style.cssText="height:0;overflow:hidden"` | 79/79 全绿（`✓ K8 今日趋势图真的画进容器`） | 「今日趋势」卡片**图形区一片空白**（柱子在 DOM 里、塌成 0 高），门却说"真的画进容器"（K8 只判 `chartHtml.length>100`，不套 `visibleText`） | **否 · B10-5** |
| V14 | D：`case "active"` 徽章按 `String(r.last_error).length > 40` 分叉成长版「可用（近期错误较多，见「最近错误」列）」 | 79/79 全绿（`✓ C16 徽章只由 status + 冷却时长决定`）；把 fixture 一行 `last_error` 换成真实形状 70 字 `上游 429：rate limit reached for model glm-4.6，请 30s 后重试（Key sk-****1234）` 后**仍 79/79 全绿** | 「状态」列同一列出现**两种说法**（短错误的行说「可用」、长错误的行说「可用（近期错误较多…）」），用户会以为多了一个告警态；C16 矩阵里最长形态恰好 40 字，`>40` 的分叉看不见 | **否 · B10-6** |
| V15 | CSS：`.hidden{…}` 后追加 `.alert-warn::after { content: "请前往「模型映射」页处理"; }` | 79/79 全绿（`✓ J2 …`） | **每条配置告警横幅底下都多出一行可见指路**，把用户指向 Q24 已改名的死页「模型映射」；CSS 生成的文本既不在 J2 的产地面（`css` 键不在 `copySources`），也不在 K 段（不产出 HTML） | **否 · B10-7** |
| V16 | TPL：已上架服务的模板页 `<body>` 后注入 `<div class="alert">请到「模型映射」页配置资源。</div>` | 79/79 全绿 | `main.py:472` 用 `StaticFiles(html=True)` 挂在 `/` → 该文件可 `/templates/template-providers.html` **HTTP 直达并渲染**，用户读到死页名；模板又是新页复制底稿，死名会被抄进真页。自动发现面只收 `index.html`，整个 `templates/` 在面外 | **否 · B10-8** |
| V17/V18 | R：死页名改写 | `!! 锚点命中 0 次，未施加`（resources.js 里没有「资源池设置」字样，该页指路在 models.js/dashboard.js） | —— | 未施加（改用 M 重做，见 V21/V22） |
| V21 | M：`或到「模型资源」页通过映射创建` → `或去「模型映射」通过映射创建` | 79/79 全绿（`✓ J2`） | 空态提示把用户支到不存在的页「模型映射」；cue 动词表是闭集（`到\|前往\|请到\|打开`），"去"不在里面，且括号后没跟"页"字 → 三型认法全不命中 | **否 · B10-9** |
| V22 | M：对照 —— `或到 模型映射 页通过映射创建`（裸串保留"页"） | `✗ J2 … 违规指路：…models.js→「模型映射」页` | —— | 红（第九轮"裸 到 X 页"项成立） |
| V19 | 新增孤儿文件 `web/static/js/pages/zzz.js`：`export const X = "请到「模型映射」页新建资源";` | `✗ J2 … 违规指路：…zzz.js→「模型映射」页` | —— | **红**（自动发现确实把新文件拉进面；`--mutation` 侧基线红会整体拒绝，`:1031-1036`） |
| V20 | 新增 `zzz.js`，死页名写在 HTML 注释里 | `✗ J2`（同上） | —— | 红（方向是保守假红，非漏洞） |
| V24 | D：正文用**未闭合**的 `<span aria-hidden="true">` 包住 | `✗ K1 … 正文缺失=4`、`✗ K9` | —— | 红（fail-safe：清洗宁可判"看不见"） |
| V25 | D：`invalid` 徽章 `title` 里的「资源池设置」页改成「模型映射」页（**纯属性文本**） | `✗ C3`、`✗ J2 … dashboard.js→「模型映射」页` | —— | 红（J2 扫源码全文，属性里的页名照样抓） |

## ③ 阻塞项（9 条：均有用户可见后果且门全绿；`--mutation` 87/87 无一触及）

| ID | 洞 | 依据（变异） | 建议修法（不动生产代码，只给口径） |
|---|---|---|---|
| **S-34 B10-1** | `visibleText` 的隐藏判据是**字符串白名单**：`opacity:0`、`height:0;overflow:hidden`、`visibility:collapse`、`position:absolute;left:-9999px`、大写 `VISIBILITY/DISPLAY` 全过关 | V2/V3/V4/V5/V23/V26 → 79/79 绿 | ① 全部正则加 `i` 标志；② 把"看不见"的判定改成**黑名单扩展集**：`opacity:\s*0`、`visibility:\s*collapse`、`height:\s*0`、`left:\s*-\d{4,}`、`overflow:\s*hidden` 与 `display:\s*none` 并列；③ 项目自身工具类要**按类名解析**（读 `base.css` 里 `display:none` 的类名，命中 class 属性即判隐） |
| **S-34 B10-2** | `<template>` / `<noscript>` 内的文本被当可见 | V6/V7 → 绿 | 把 `template`/`noscript`/`option`/`datalist` 与 `script`/`style` 同列"正文丢弃"标签（浏览器不渲染它们的子树） |
| **S-34 B10-3** | `aria-hidden` 只认 `="true"` 且大小写敏感 | V8（裸 `aria-hidden`）/V9（`ARIA-HIDDEN="TRUE"`）→ 绿 | 正则 `aria-hidden(\s|$|=|>|="true")` + `i` 标志；`isInvisible` 整体大小写不敏感（HTML 属性名与值 `true` 本就大小写不敏感） |
| **S-34 B10-4** | `K6` 的**表头列名不经 `visibleText`**，`<th hidden>` 让列名消失仍绿 | V11 → 绿；后果＝「最近错误」列失去标题 | `heads` 抽取改成对每个 `<th>` 片段跑 `visibleText`，隐藏/不可见的表头不计入列序（并同时要求列名数 == 该行 `<td>` 数） |
| **S-34 B10-5** | `K8` 只判 `chartHtml.length > 100`，与 K1/K2/K3 不同口径 | V13 → 绿；后果＝趋势图区空白但门说"画进容器" | `K8` 改判 `visibleText(chartHtml).length > 100` 并要求小时刻度（`0..23`）在清洗后仍在；再加一条"容器不得带塌陷样式"（`height:0`/`display:none`/`opacity:0`） |
| **S-34 B10-6** | `C16` 矩阵的字段形态集是手工 4 组、`last_error` 最长恰好 40 字，**按长度/按未列举字段分叉看不见** | V14（含 70 字真实 429 载荷）→ 79/79 绿 | ① 给每个状态追加一对"**同一行仅 last_error 长度不同**"的形态（40 字与 70 字），要求输出逐字节相同；② 再加"随机打乱无关字段值"的形态生成器（rid/name/vendor/account/C/in_flight/models/last_error 各取 3 值笛卡尔积抽 20 组），把"矩阵"从手写 4 组变成**由生产行形状派生**；③ 判据补一句：徽章可见文本必须 ∈ 四态白名单（`可用/冷却中/模型名无效/已停用`），任何带后缀的分叉直接红 |
| **S-34 B10-7** | 产地面漏 **CSS**：`css/base.css` 在 `FILES` 里却没进 `copySources`（`verify_v2_frontend.mjs:541-544` 具名补录清单缺 `"css"`，自动发现只收 `.py`/`.js`/`index.html`）；CSS `content` 是浏览器真实生成的可见文本，且本项目已在用 `::after{content}` | V15 → 绿 | ① `copySources` 补 `css` 键；② 对 CSS 源额外抽 `content:\s*"…"` 里的串进 J2 候选集；③ `walkFiles` 的 keep 加 `.html`（整个 `web/static`）与 `.css` |
| **S-34 B10-8** | 产地面漏 **`web/static/templates/*.html`**（11 个文件，`StaticFiles(html=True)` 挂 `/` → 可 HTTP 直达，见 `main.py:472`） | V16 → 绿 | 自动发现的 `.html` 白名单从"只有 `index.html`"改成 `web/static/**/*.html`；若要显式排除模板，就在 J2 里断言"模板目录不进面"并在页面路由上确认这些 URL 不被导航可达（当前做不到 —— 它们确实返回 200） |
| **S-34 B10-9** | `PAGE_REFS` cue 动词闭集 + 括号型强制后跟"页"字 | V21（`或去「模型映射」通过映射创建`）→ 绿；V22（保留"到 … 页"）→ 红，证明只堵一半 | cue 动词集补 `去|进|去…|在|到…查看`（或反向：把**所有** `「X」` 括号串中"看起来像页名"的都拉进候选，再用 `navLabels` 与"含『页/卡片/按钮』的白名单"二次判定）；同时把"已知被改名的旧页名"（模型映射/系统模型/接入管理）列成**死名黑名单**常量，全文命中即红 —— 这条最省事且不依赖语法猜测 |

> 复核提示：以上每条的"红/绿"都是在**副本**里对 `scripts/verify_v2_frontend.mjs`（与仓库 `16:24` 版本逐字节相同）跑出来的；施加完已把副本文件还原（脚本内 `dashboard.js 已还原：True`）。

## ④ 理论限制（不计阻塞：绕过得了，但拿不出用户可见坏改动）

- **T1 「class=hidden 被堵住」是巧合，不是判据**（V1 红的是 A1/K1 的字面 `class="alert alert-warn"` 串匹配）。→ 现在无害，但一旦有人把 A1 改成"包含式"匹配（`class~="alert-warn"`），V1 立刻转绿。建议随 B10-1 一起把类名解析做掉，别留这颗雷。
- **T2 `.md` 与 gitignore 的 `data/` 不在面内**：J2 的红利只到"文档写错页名"，文档不是产品 UI 出口 → 无用户可见后果。（注：`docs/` 里若写死旧页名属 PM 文档一致性问题，交 PM 侧记账，不在本门范围。）
- **T3 `esc()` 改写造成的 K1 绕过：没有空间**。K1 两侧都 `decode`（`&lt; &gt; &quot; &#39; &amp;`）后再做 `includes`，把 `（` 换成 `(`、加空格、换全半角都会让 message **不等值 → 红**（V25 同族）。残余风险只有"十进制/十六进制实体"（`&#x27;`）这类**门自己会假红**的方向，不是假绿。
- **T4 未闭合/大写标签名**：`tagRe` 对标签名做了 `toLowerCase()`，`<SPAN HIDDEN>` 认得出；未闭合隐藏元素会把后续文本一律判隐（V24 → 红）→ 方向是假红（宁可错杀），不构成逃逸。
- **T5 属性里含 `>`**（`title="a>b"`）：`tagRe` 的属性分组允许引号内的 `>`，解析不错位；未见可利用后果。
- **T6 `C16` 的 ms 量级集**缺 `≥86400000`（一天以上）这一格：网关最长冷却是全局熔断 30min（1800000ms），生产拿不到那个量级 → 理论分叉。
- **T7 「FILES 之外的新文件在变异模式下不被复制」不成立**：V19/V20 证明 `copy:` 自动发现把 `pages/zzz.js` 同时带进**实测**与 `runMutations` 的复制表（`:1021-1025` 遍历整个 `FILES`），且基线红时 `runMutations` 直接 `return 2` 拒绝出结论（`:1031-1036`）。这条面是本轮唯一"攻击失败但机制确实封死"的项。
- **T8 `K9` 的第二轮渲染（掺 `<script>` 哨兵）与 `fetchStub` 按路径分派**：V2/V6/V8 一类改动都不影响 K9 绿，但也**造不出**新的转义逃逸 —— 哨兵走的是同一条 `esc()` 路径，属性型（`title=`）已被 V10/V25 两面包住。

## ⑤ 两个 shasum（`git status --porcelain | shasum`，仓库工作树）

- 开工（16:24 前后）：`994985f23949da1cf082a7d610761e4446c3aab5`
- 收工（报告写入后、含全部实验还原完毕）：`994985f23949da1cf082a7d610761e4446c3aab5`
- **两值相同 ✓**（原因有据：`git check-ignore -v` → `.gitignore:17: docs/` 命中本报告路径，故 `docs/` 整体不进 `git status --porcelain`；报告写入后哈希与开工值一致，已实测）。

**过程异常必须报（铁律 2/5，含未闭合项）**：会话中途（第一批变异跑完、`--mutation` 之后）我取到过第三个值 `bbef1a75976ccbf6018ef52cd79eed30058d87fd`，与开工值不同，收工又回到开工值。
逐项核查结果：① 报告所在的 `docs/` 被 `.gitignore:17` 整目录忽略 → 本轮交付文件不可能影响 porcelain；② `find -newermt "2026-09-28 16:20"` 显示窗口内被写的 6 处里，`.pytest_cache/`（ignore:31）与 `tests/integration/__pycache__/*.pyc`（ignore:23）**同样被忽略**，也不可能是元凶；③ 剩下 `E2E-20260928-round5-fixes.md`(16:30)、`pm-accept-10.md` 在 ignore 内，`test_int_v2_frontend_gate.py`/`verify_v2_frontend.mjs` 是已跟踪且早已是 ` M` 状态（内容改写不改变 porcelain 文本）。
→ **中途那个第三值我至今无法逐项归因**（当时只存了哈希、没存列表快照，事后无法 diff），只能说：它由并行会话（任务板 #8 三角色并行验收进行中）在同工作树**瞬时创建又删除的未跟踪、未忽略路径**造成最合理。**这不是本角色所为**：本角色全程只写 `/tmp/mgw-accept-10` 与 `/tmp/ix10`，对仓库零写入，且收工值与开工值相同。
教训回写：以后中途复取值须连同 `git status --porcelain` 全文一起留档，否则无法归因（建议编排方对同工作树写入串行化）。
本角色零改动自证：`scripts/verify_v2_frontend.mjs`（mtime 仍为 16:24，与副本 md5 相同）、`diff -rq model_gateway/web /tmp/mgw-accept-10/model_gateway/web` → 除 `.DS_Store` 外零差异、`model_gateway/core/resources.py` same；副本内施加过的变异全部还原（脚本内 `dashboard.js 已还原：True`），副本 `pages/` 无残留 `zzz.js`。


