# ix 第十一轮验收 —— 攻「按属性语义解析」这套机制的边界

- 角色：资深交互设计师（只验收，不改生产代码）
- 靶子：第十轮补做的 `parseAttrs()/isInvisible()` 语义可见性模型、`Z1/Z2` 门自测、`K0~K9` 整页装配、`J2` 文案产地面、`C16` 矩阵、`--mutation` 自证
- 工作区：`/tmp/mgw-accept-11/`（仓库副本，排除 `data/`、`.git/`、`.venv/`）；**所有变异只施加在副本上**，收工时逐文件 md5 与仓库比对（见 ⑦）
- 载荷：`/tmp/mgw-accept-11-ov.json` = 由**我自己的临时实例**（`/tmp/ix11-data/config.yaml`，合成假 Key、`base_url=127.0.0.1:9`，端口 55845）现采的 `/admin/api/overview`；另备 `…-traffic.json`（今日有流量）、`…-hostile.json`（字段含 HTML）、`…-healthy.json`（正常态）
- 浏览器实测：**做了**，但不是用户那个实例 —— `:8300` 本轮开工时未在跑（`curl` 返回 000），我按硬规则另起临时实例（自己的 /tmp 目录 + 空闲端口 55845，用完已 kill），用 ego-browser 真实 Chrome 加载 `http://127.0.0.1:55845/#/dashboard|/apiaccess|/logs|/settings`，取 `getBoundingClientRect()/getComputedStyle()/innerText/elementFromPoint` 与截图（`/tmp/ix11-shots/` 18 张）。**未发起任何真实上游调用、未写真实凭据、未触碰仓库 `data/`**
- 基线（副本原样）：`实测 81 项，通过 81 项，失败 0 项`；`--mutation` → `可红 100/100；每条断言都有对应变异`
- 本轮施加 **49 个变异**：**39 个门全绿**（其中 34 个有实测到的用户可见坏结果），10 个作为对照如期变红

---

## ① 结论

**不通过（阻塞 8 条）。**

第十轮的修复方向是对的（把"隐藏写法白名单"换成"按属性语义解析"+ 门自测 Z1 + 文案产地自动发现），但**语义模型的作用域被定死了三条边界，本轮 39 条逃逸里有 36 条落在这三条边界之外，而不是边界之内**：

1. **可见性只建模「dashboard 产出的 HTML 上、元素自身的内联属性」**。样式表层叠完全在模型外：`base.css` 里加一行 `.alert-warn { display: none; }`，四条配置告警在真实 Chrome 里高度全为 0、`body.innerText` 从 856 字掉到 459 字，门 81/81 与 `可红 100/100` 同时纹丝不动。同一族还有 `body::after{position:fixed;inset:0;background:#fff;z-index:99999}`（截图 = 纯白一张，`elementFromPoint(400,300)` 返回 BODY）与 `.nav-item.hidden`（侧栏「请求日志」入口高度 0，从导航里消失）。Z1 那 18 例测的是 `isInvisible(属性串)` 这个纯函数，**它测不到"这一行 CSS 会不会让那个元素看不见"**。
2. **壳层（`index.html`）与 `main.js` 的路由/主题段完全不被执行**。E1~E4 只按字面正则看 `#ops-dot` 那一个标签。于是 `id="content"` 改名（真实 Chrome：`contentExists:false`、横幅 0、整站不启动）、`<main id="content" style="display:none">`（DOM 里 7 个子节点、4 条横幅俱在，界面纯白）、`<link href="/css/theme.css">`（`--err-bg` 取空、卡片 `box-shadow:none`、截图 = 裸样式页）、`#content inert aria-hidden="true"`（命中测试落到 `main-col`，内容区一律点不动）—— 全部 81/81 绿。**门花十轮把"总览产出的可见性"补齐，但用户真正打开的是那个壳；壳没有一条判据。**
3. **七页里只有总览被真跑；共享组件与错误管道零执行**。`api.js` 的 `if (!resp.ok)` 改成 `if (false)` 后，我在浏览器里把 `y` 填 0 点保存：后端真返 400、配置真没变（`serverFailThreshold:2`），界面却弹绿条 **「配置已保存并热重载生效」**（基线同一动作弹「保存失败：scheduling.fail_threshold: Input should be greater than or equal to 1」）。`components.js` 同理：`copyText` 去掉写入 → 剪贴板 `(untouched)` + toast「密钥已复制」；`confirmDialog` 的取消分支改成 `resolve(true)` → 点「取消」后密钥**真的被删了**（`tokensAfterCancel:[]`）。`apiaccess.js` 的 `maskVal` 改成恒等 → 密钥单元格显示 `mg-fake-0123456789abcdef`（基线 `mg-fa****cdef`）。`settings.js` 删掉解禁那一行 → 改了参数后 `#st-save.disabled` 恒为 `true`，而脏态徽章照样出现（用户看到"有未保存修改"却点不动保存）。

另外五条边界本轮同样被实测打穿：**转义只在一根管道上被证明**（K9 的哨兵只走 `warnings.message`；把 `${esc(r.name)}` 去掉后，用与门同样的 vm 手法真跑 `resourceHealthTable`，产出里活标签从 0 变 1）；**数值真值无判据**（K3 只认八张卡的**标签**，K5 的坏插值黑名单只有 `undefined`/`[object Object]`/`${`，于是"数值整族不渲染"与「成功比 NaN%」全绿）；**指路仍是语法白名单**（`【模型映射】页` 这种非「」/『』括号 + 非 cue 动词的写法 J2 全盲，而同一处文案改用「」立刻红；页名真实存在但那一页没那个控件时，前端门与 `pytest -k route_copy` 双绿）；**K4 把外链当噪声过滤**（`p !== "https"`，管理台里塞远程外链无人响）；**K8 的容器判据 fail-open**（正则不匹配时取空串默认值 → "页面上根本没有那个容器"被当成"容器可见"，趋势图整块空白而门说 `✓ K8 趋势图真画进可见容器`）。

`可红 100/100` 本轮再次被证明**不等于封住**：我在 `base.css` 藏着 `.alert-warn{display:none}`、在 `api.js` 藏着 `if (false)` 的**同时**跑 `--mutation`，两次都还是 `可红 100/100；每条断言都有对应变异`。

---

## ② 基线复跑（逐字）

```
$ cd /tmp/mgw-accept-11 && node scripts/verify_v2_frontend.mjs /tmp/mgw-accept-11-ov.json
[配置告警横幅] …（A1~A15）
[资源健康表] …（B1~B7）
[状态徽章四态] …（C1~C16）
…
[门自身判据自测]
  ✓ Z1 可见性判据按**属性语义**认：`class="… hidden"` 不算隐藏，真属性/裸属性/大写都算
  ✓ Z2 执行环境不含 Node 专有全局（浏览器里不存在的东西，门里也不许存在）

========================================================
实测 81 项，通过 81 项，失败 0 项
```

```
$ cd /tmp/mgw-accept-11 && node scripts/verify_v2_frontend.mjs /tmp/mgw-accept-11-ov.json --mutation
[变异自证] 基线 81 条全绿 → 施加 100 个源码变异
  ✓ …（100 行全 ✓，无「锚点命中 N 次」、无「未红」）
========================================================
可红 100/100；每条断言都有对应变异
```

（同一份门源码与仓库 `scripts/verify_v2_frontend.mjs` md5 一致：`9048425fcfce660f6c6cb85255056642`。人读输出全文见 `/tmp/mgw-accept-11-baseline.txt`、`/tmp/mgw-accept-11-mutation.txt`。）

---

## ③ 变异表

锚点简写：**D**=`model_gateway/web/static/js/pages/dashboard.js`，**IDX**=`model_gateway/web/static/index.html`，**CSS**=`model_gateway/web/static/css/base.css`，**MAIN**=`model_gateway/web/static/js/main.js`，**API**=`model_gateway/web/static/js/api.js`，**COMP**=`model_gateway/web/static/js/components.js`，**APAA**=`…/pages/apiaccess.js`，**SET**=`…/pages/settings.js`，**LOG**=`…/pages/logs.js`，**STA**=`…/pages/stats.js`，**MPY**=`model_gateway/main.py`。
「浏览器」列 = 真实 Chrome 上的可观察量（未标注者为仅静态/代码路径推断，见 ⑥ 的诚实标注）。

### A 族 · 可见性模型（样式表 / 内联写法 / 壳层）

| # | 变异 diff（原文） | 门输出 | 浏览器 | 判 |
|---|---|---|---|---|
| V1 | CSS：`.hidden { display: none !important; }` → 其后追加 `\n.alert-warn { display: none; }` | `实测 81 项，通过 81 项，失败 0 项` | 四条横幅 `getBoundingClientRect().height` = `[0,0,0,0]`；`body.innerText` 856→459；截图 `/tmp/ix11-shots/V1-css-hide-banner.png`（顶部告警区整块不见） | **绿 · 阻塞 B11-1** |
| V2 | CSS 同上锚点 → 追加 `.nav-item[data-page="logs"]{display:none}` + `.metric-card .metric-value{visibility:collapse}` + `#hour-chart{height:0!important}` | 81/81 全绿 | `hourChartH` 160→**0**；`innerTextLen` 856→**798**（八张卡数值不可见）；nav 那条因源码顺序未生效（`.nav-group .nav-item` 在后，见 ⑥ T2） | **绿 · B11-1** |
| V6 | CSS 同上锚点 → 追加 `body::after { content:""; position:fixed; inset:0; background:#fff; z-index:99999; }` | 81/81 全绿 | `elementFromPoint(400,300)` = **BODY**；`getComputedStyle(body,"::after")` = `block/99999/rgb(255,255,255)`；截图 = **纯白一张**（`V6-whiteout.png`） | **绿 · B11-1** |
| V4 | D：`      <div>${esc(w.message \|\| "")}</div>` → `      <div style="font-size:0">…</div>` | 81/81 全绿 | 消息节点 computed `font-size:0px`；横幅高度 64→44.8（只剩标题行） | **绿 · B11-1**（六类样式之外） |
| V5 | D：同上锚点 → `<div style="color:transparent">…</div>` | 81/81 全绿 | computed `color: rgba(0, 0, 0, 0)`（底为 `--warn-bg`，字完全不可读） | **绿 · B11-1** |
| V7c | IDX：`<a href="#/logs" data-page="logs" class="nav-item">` → `class="nav-item hidden"` | 81/81 全绿（J1 只读 `data-page` 字面） | 该导航项高度 **0**（`.hidden{display:none!important}` 真生效）；截图 `V7c-nav-util-class-hidden.png` | **绿 · B11-1/B11-2** |
| V3 | D：`<div class="alert alert-warn">` → `<div class="alert alert-warn hidden">` | `✗ A1`、`✗ K1 横幅节点=0 期望=4` | —— | **红**（第十轮 T1 那颗雷：红的是 A1/K1 的字面类名串，不是可见性判据） |
| V7 | IDX：`…class="nav-item" hidden>`（加 `hidden` 属性） | 81/81 全绿 | 高度仍 36 —— `.nav-group .nav-item{display:flex}`（`CSS:147`）覆盖了 UA 的 `[hidden]` | 绿但**无坏结果** → 记 ⑥ T3 |
| W1 | IDX：`if (c && !c.firstElementChild) c.innerHTML =` → `if (c) c.innerHTML =` | 81/81 全绿 | 实测**无变化**（前一行 `if (window.__MG_BOOTED) return;` 先短路） | 绿但**无坏结果** → 记 ⑥ T4 |

### B 族 · 壳层与入口（`index.html` / `main.js` 路由·主题·自动刷新）

| # | 变异 diff | 门输出 | 浏览器 | 判 |
|---|---|---|---|---|
| Y1 | IDX：`<main class="content" id="content"></main>` → `id="page-content"` | 81/81 全绿 | `document.getElementById("content")` = null、`banners:0`、`contentChildCount:null`；`route()` 在 `content.scrollTop` 抛错 → **整站不启动**（截图 `Y1-content-id-renamed.png`） | **绿 · 阻塞 B11-2** |
| Y2 | IDX：`<span id="crumb-group">概览</span>` → `id="crumb-grp"` | 81/81 全绿 | `contentChildCount:0`（写面包屑时抛错，连「加载中…」都没写上）→ 内容区永久空白 | **绿 · B11-2** |
| Y6 | IDX：`<main class="content" id="content"></main>` → 加 `style="display:none"` | 81/81 全绿 | computed `display:none` 而 DOM 完整（7 子节点 / 4 横幅）→ 界面只剩侧栏+顶栏，**内容区纯白** | **绿 · B11-2** |
| V8 | IDX：`#content` 加 `inert aria-hidden="true"` | 81/81 全绿 | `content.inert === true`；`elementFromPoint(400,300)` 落到 `main-col`（内容区元素退出命中测试）→ 全站点不动、读屏读不到 | **绿 · B11-2** |
| V9 | IDX：`<button class="ops-dot" id="ops-dot" hidden title=` → 中间插 `aria-hidden="true"` | 81/81 全绿（E1~E4 只看 `hidden`/`title` 字面） | 属性实测存在；「有未读失败时读屏软件收不到红点」这一路径**未实测**（本轮未造 ops_failed_unread>0 态） | **绿 · B11-2**（后果半实测） |
| X2 | IDX：`<link rel="stylesheet" href="/css/base.css">` → `href="/css/theme.css"` | 81/81 全绿（H1/H2 判的是 `base.css` 源码文本，不看 `<link>`） | `--err-bg` 取值为空、`.card` 的 `box-shadow:none`、消息 `font-size:16px`、截图 = **完全裸样式**（`X2-stylesheet-404.png`） | **绿 · B11-2** |
| X3 | IDX：`<script type="module" src="/js/main.js">` → `src="/js/app.js"` | 81/81 全绿 | `banners:0`、`contentChildCount:1`、文本「界面脚本未能加载…」→ 控制台整体不可用 | **绿 · B11-2** |
| V19 | MAIN：`document.documentElement.setAttribute("data-theme", resolveTheme(themeMode));` → `…, "light");` | 81/81 全绿 | 点「深色主题」后 `localStorage["mg-theme"]="dark"`、按钮呈 active，而 `data-theme="light"`、背景仍是浅色 → **三态主题里两态失效** | **绿 · B11-2** |
| V20 | MAIN：`const FILES = ["/js/main.js", "/js/api.js", "/js/components.js", "/css/base.css",\n    ...Object.keys(PAGES).map((n) => \`/js/pages/\${n}.js\`)];` → `const FILES = ["/js/main.js"];` | 81/81 全绿 | 未实测（推断：改 `pages/*.js`/`base.css` 不再触发自动刷新 → 回到 2026-09-05「新旧混载 = 只有框架内容空白」事故形态） | **绿 · B11-2**（登记级） |
| W10 | MAIN：`content.innerHTML = \`<div class="empty">${e.message}</div>\`;` → `…加载失败：${e.message}（网关已恢复，无需处理）…` | 81/81 全绿 | 未实测（整页失败兜底被写成「无需处理」，且 `e.message` 未转义直进 innerHTML） | **绿 · B11-3/B11-4** |

### C 族 · 六页零执行 + 共享组件 + 错误管道（谎报型）

| # | 变异 diff | 门输出 | 浏览器 | 判 |
|---|---|---|---|---|
| W2 | API：`  if (!resp.ok) {` → `  if (false) {` | 81/81 全绿；**同时 `--mutation` 仍 `可红 100/100`** | 基线同一动作 toast=「保存失败：scheduling.fail_threshold: Input should be greater than or equal to 1」；变异后 toast=**「配置已保存并热重载生效」**，而 `GET /admin/api/config` 里 `fail_threshold` 仍是 **2**（界面重绘后输入框也回到 2） | **绿 · 阻塞 B11-3（本轮最严重）** |
| W3 | COMP：`navigator.clipboard?.writeText(text).then(() => toast(okMsg, "ok"), () => toast("复制失败", "err"));` → `toast(okMsg, "ok");` | 81/81 全绿 | 挂钩 `writeText` 后点「复制密钥」：`copied:"(untouched)"` + toast「密钥已复制」（基线 `copied:"mg-fake-0123456789abcdef"`）→ 用户往工具里粘的是剪贴板里的旧东西 | **绿 · B11-3** |
| W5 | COMP：`cancel.onclick = () => { m.close(); resolve(false); };` → `resolve(true);` | 81/81 全绿 | 「删除密钥」弹窗点**取消**后：`tokensAfterCancel:[]`、页面行数 0 → 确认框的取消等于确定（同族还管着删资源/停网关） | **绿 · B11-3** |
| V14 | APAA：`const maskVal = (v) => v ? v.slice(0, 5) + "****" + v.slice(-4) : "";` → `const maskVal = (v) => v \|\| "";` | 81/81 全绿 | 密钥单元格 = `mg-fake-0123456789abcdef`（基线 `mg-fa****cdef`）；截图 `V14-mask-plaintext.png` → 2026-09-06 定版的「默认密文」被推平，投屏/肩窥直接泄 | **绿 · B11-3** |
| V15 | SET：`    root.querySelector("#st-save").disabled = false;` → 注释掉 | 81/81 全绿 | 改 `y` 之后：`#st-save.disabled` 恒 `true`，而脏态徽章「有未保存修改」照样出现 → **系统参数再也保存不了**（v2.1 修过的死 UI 家族，无一条判据锁定） | **绿 · B11-3** |
| V17 | LOG：`</tr></thead><tbody>${rows.map((r) => requestRow(r)).join("")}` → `${rows.filter((r) => r.status !== "failed").map(…)}` | 81/81 全绿 | 未实测（请求流水整族不显示失败行，卡头「共 N 条」仍按后端总数报） | **绿 · B11-3** |
| V18 | STA：`const rate = t.requests ? Math.round((t.success / t.requests) * 100) : 0;` → `(t.success + t.failed) ? Math.round((t.success / (t.success + t.failed)) * 100) : 0` | 81/81 全绿（std 与 traffic 两份载荷都绿） | 未实测（数据看板成功率分母丢掉 `aborted` → 中断不计，成功率虚高） | **绿 · B11-3/B11-5** |
| W4 | COMP：`if (ok !== false) el.classList.toggle("on", next);` → `toggle("on", !next)` | 81/81 全绿 | 实测：点击瞬间显示与服务端相反，但 `persist()` 整页重绘把最终态纠正回来 → 只有短暂反相 | 绿、**坏结果不持久** → 记 ⑥ T5 |
| W6 | COMP：`while (footer.firstChild) footEl.append(footer.firstChild);` → `footEl.append(footer);` | 81/81 全绿 | 未实测（2026-09-06 用户截图指出的「取消/确定贴死」原样回归，无任何判据锁定） | **绿 · B11-3**（回归无防） |
| X1 | D：`<a href="#/logs" …>查看日志</a>` → `<a href="#/resources" …>查看日志</a>` | 81/81 全绿（K4 只验路由存在性） | 未实测（点「查看日志」跳到「模型资源」页） | **绿 · B11-6** |
| V13 | D：`查看日志</a>` → `查看日志</a> · <a href="https://docs.model-gateway.example.com/troubleshoot">官方排障指南</a>` | 81/81 全绿（K4 把 `https` 当噪声 `p !== "https"` 过滤） | 未实测（本地优先的管理台里出现远程外链，且门看不见） | **绿 · B11-7** |

### D 族 · 文案真值 / 指路语法 / 转义管道

| # | 变异 diff | 门输出 | 浏览器 | 判 |
|---|---|---|---|---|
| V16 | LOG：`该筛选条件下无请求记录` → `…，失败成因见【模型映射】页` | 81/81 全绿（J2 的括号集只有「」/『』，cue 动词表不含「见」） | 实测界面文本 = 「该筛选条件下无请求记录，失败成因见【模型映射】页」（`inBody:true`）→ 把用户指到 Q24 已改名的死页 | **绿 · 阻塞 B11-6** |
| W11 | 同一锚点、同一死页名，只是改用「」：`…，失败成因见「模型映射」页` | `✗ J2 …违规指路：…logs.js→「模型映射」页` | —— | **红（对照：证明 V16 的因是括号/动词白名单，不是"没扫到 logs.js"）** |
| X5 | LOG：空态文案 → `…；若为失败调用，请到「API 接入」页更换 Key` | 81/81 全绿；**`pytest -k route_copy` 2 passed** | 未实测（页名真实存在，换 Key 的控件在「模型资源」页；`logs.js` 根本不在 pytest 那条判据的 `copy_files` 里） | **绿 · B11-6** |
| X6 | SET：`<span class="card-title">维护</span>` → 追加 `<span class="value">端口改动请到「模型资源」页重启网关</span>` | 81/81 全绿；**`pytest -k route_copy` 2 passed**（`owners` 动作表里没有「重启」这一项） | 未实测（重启按钮就长在本页，却把人支到另一页） | **绿 · B11-6** |
| W7 | MPY：`"message": (f"{len(hidden)} 个已启用模型的资源映射全部不可用（已停用或凭据失效），"` → `…（今日流量高峰引发的临时冷却，无需处理，稍后自动恢复），"` | 81/81 全绿（A4/A5 只数「已从 /v1/models…隐藏」两次命中，不钉成因句） | 未截图（K1 已证后端文案原样透传到横幅）→ 真因是开关关闭/凭据失效，用户据此坐等自愈 | **绿 · 阻塞 B11-5** |
| W8 | MPY：②类告警尾部 `…）"` → `…）—— 属正常状态，无需处理，可忽略本条")` | 81/81 全绿 | 同上（把"配置冗余提示"升级成"可忽略"） | **绿 · B11-5** |
| V12 | D：`${esc(r.name)}</td>` → `${r.name}</td>` | 81/81 全绿（std + hostile 两份载荷都绿） | **vm 真跑 `resourceHealthTable`**：基线产出活标签 0 个，变异后 1 个（`<img src=x onerror=alert(document.domain)>`） | **绿 · 阻塞 B11-4** |
| W9 | LOG：`<td class="strong">${esc(r.system_model \|\| "")}</td>` → 去掉 `esc` | 81/81 全绿（两份载荷都绿） | vm 真跑 `requestRow`：活标签 0 → **1** | **绿 · B11-4** |

### E 族 · 指标真值 / 坏插值白名单

| # | 变异 diff | 门输出 | 浏览器 | 判 |
|---|---|---|---|---|
| V10 | D：`      <div class="metric-value">${fmtValue(value)}</div>` → `      <div class="metric-value"></div>` | 81/81 全绿（K3 只认八张卡的**标签**） | 实测 `metricValues` = `["","","","","","","",""]`；截图 = 八张卡只有图标与标签（`V10-metric-values-dropped.png`） | **绿 · 阻塞 B11-5** |
| V11 | D：`const rate = t.requests ? Math.round((t.success / t.requests) * 1000) / 10 : 0;` → `const rate = Math.round((t.success / t.requests) * 1000) / 10;` | 81/81 全绿（std 与 traffic 都绿） | 实测第三张卡 = **「成功 0 · 成功比 NaN%」**（本轮现采载荷 `today.requests=0`，正是每天 0 点后与刚重启时的真实形状） | **绿 · B11-5** |
| X4 | D：`今日切换 ${data.today.switch_count} 次` → `今日切换 0 次` | 81/81 全绿（traffic 载荷里真实 `switch_count=3` 也照样绿） | 未截图（卡头写死 0 → 用户以为全天零切换/零故障转移） | **绿 · B11-5** |

---

### F 族 · 假 DOM 与真浏览器的差异（K8 容器判据的缺省值）

| # | 变异 diff | 门输出 | 浏览器 | 判 |
|---|---|---|---|---|
| Z1 | D：`const box = document.getElementById("hour-chart");` → `document.getElementById("hour-cart")` | `✗ K8 … 容器属性= style="height:160px" 元素数=0` | —— | **红**（`chartHtml` 取 `nodes["hour-chart"]`，取不到就红） |
| Z3 | D：容器与取节点**两边同时**改名（`hour-chart` → `trend-box`） | `✗ K8 … 容器属性=无 元素数=0` | —— | **红**（`bars` 维把这对钉住了） |
| Z2 | D：只把**容器**改名 —— `<div id="hour-chart" style="height:160px"></div>` → `<div id="hour-cart" style="height:160px"></div>`（`getElementById("hour-chart")` 不动） | `实测 81 项，通过 81 项，失败 0 项`（`✓ K8`） | `oldId:false / newId:true / boxChildren:0 / boxHeight:160`、`barsAnywhere:0` → 「今日调用趋势（24h）」卡里只剩一条 **160px 高的空白带**，柱子一根没有；截图 `Z2-chart-never-drawn.png` | **绿 · 阻塞 B11-8** |

> 根因（`verify_v2_frontend.mjs:770`）：`const attrs = (pageHtml.match(/<div\s+id="hour-chart"([^>]*)>/) || ["", ""])[1];` —— 正则不匹配时缺省成**空串**，`isInvisible("")` 与 `!/height:0/.test("")` 双双通过，于是"容器不存在"= "容器可见"。detail 里那行 `|| ["", "无"]` 甚至已经把 `容器属性=无` 打出来了（Z3 那次），但**判据不看它**。这是第十轮"按语义解析"改造留下的典型 fail-open：语义模型对"有属性串但没有元素"这一形态没有第三态。

---

## ④ 阻塞项（8 条，逐条可复现）

| ID | 洞（机制级） | 复现（变异 → 门 → 浏览器） | 建议修法（只给口径，本轮不动生产代码） |
|---|---|---|---|
| **S-35 B11-1** | **可见性模型不含样式表层叠**：`isInvisible()` 只解析元素自身的内联 `style`（`verify_v2_frontend.mjs:686-702`），`base.css` 的规则只作为**文本**进 J2 的文案产地面（`:78`），没有任何判据把"某条 CSS 规则会命中这个元素"接上 | V1 / V2 / V6 / V4 / V5 / V7c → 81/81 全绿；V1 下横幅高度 `[0,0,0,0]`、V6 下整页纯白；**V1 与 W2 施加期间 `--mutation` 仍 100/100** | ① 从 `base.css` 解析出 `选择器 → {display,visibility,opacity,height,overflow,position,z-index}` 表，`visibleText()` 增加"类名命中隐藏规则即判隐"（含 `!important` 与源码顺序）；② 把 `font-size:0`、`color:transparent`、`clip-path:inset(50%)`、`zoom:0`、`transform:translate(-9999px…)` 并入 `isInvisible` 的样式集，并同步进 Z1 的 18 例；③ 增一条**层叠层**判据：对页面产出的关键元素（横幅/指标卡/图表容器/健康表）跑一次真浏览器或 CSSOM 计算，断言 `offsetHeight>0` 且 `getComputedStyle().display!=="none"`（本机已有 `scripts/ui_screenshot*.py` 的 CDP 路子可复用） |
| **S-35 B11-2** | **壳层零判据**：`index.html` 只被 E1~E4（`#ops-dot` 字面）与 J1（`data-page`/`<span>` 字面）扫过；`main.js` 只有红点那一块被执行（I 段），`route()`/主题/自动刷新三段完全不跑 | Y1（`#content` 改名 → 整站不启动）、Y2（面包屑 id → 内容区永久空白）、Y6（`#content style="display:none"` → 纯白）、V8（`inert` → 点不动）、V9（红点 `aria-hidden`）、X2（`<link>` 写错 → 裸样式）、X3（`<script src>` 写错 → 不启动）、V19（主题恒浅色）、V20（自动刷新清单塌半）→ 全部 81/81 绿 | ① 把 `visibleText()` 也跑在 **`index.html` 的壳层 HTML** 上（同一套 `isInvisible`），断言七个导航项 + `#content` + `#crumb-group` + `#tb-title` + `#ops-dot` + `#toast-wrap` + `#modal-root` 都可见且存在；② 加一条 **id 交叉核对**：`main.js`/各页 `getElementById("X")` 与 `querySelector("#X")` 的 id 集合 ⊆ `index.html` 里真实出现的 id（本轮 Y1/Y2 正是这条缺失）；③ 加 `<link href>` / `<script src>` 的存在性判据（文件必须真在 `static/` 下）；④ 把 `main.js` 的 `route()` 也用假 DOM 真跑一遍（假 `location.hash` + 假 PAGES），断言写面包屑/标题/内容容器的三步都落到位；⑤ 主题：断言 `applyTheme()` 后 `data-theme ∈ {light,dark}` 且与 `resolveTheme(mode)` 一致（三态各一次） |
| **S-35 B11-3** | **七页里只有总览被真跑；`components.js`/`api.js` 的共享行为零执行**（`FILES` 里 `settings/models/apiaccess/logs/stats/templates/components` 只进文案产地面，`runChecks` 里没有任何 `read("settings")` 之类） | W2（保存 400 被谎报成「配置已保存并热重载生效」，服务端值未变）、W3（剪贴板未写却报「已复制」）、W5（点「取消」真的删了密钥）、V14（密钥明文）、V15（保存按钮永远灰）、V17（失败行整族不显示）、W6（脚钮贴死回归）、W10、V18 → 全部 81/81 绿 | ① 用与 I 段同样的手法给**每页**配假 DOM 真跑 `renderXxx(content)`：断言"该页承诺的控件确实在产出里且可见"（`#st-save`、`[data-tksw]`、`[data-tkey]`、`[data-delkey]`、`.filter-grid` 字段、`#log-table`）；② `api.js` 的 `api()` 用假 `fetch` 真跑四种响应（200 / 400+errors / 401+detail / 非 JSON），断言**非 2xx 必抛**且抛出文案含后端原因；③ `components.js` 真跑 `confirmDialog`（断言取消→`resolve(false)`）、`copyText`（断言 `clipboard.writeText` 被调用、失败分支不报"已复制"）、`switchEl`（断言 class 与 `onToggle` 收到的 `next` 同向）、`modal`（断言 footer 子节点平铺、`gap` 生效）；④ `maskVal` 一类的脱敏函数抽成可执行导出并直接单测（前 5 + `****` + 后 4，且明文不得出现在产出 HTML 里） |
| **S-35 B11-4** | **转义只在一根管道上被证明**：K9 的哨兵只塞进 `warnings.message`（`verify_v2_frontend.mjs:655-658`），其余后端可控字段（资源名/厂商/账号/模型名/错误摘要/request_id）与其余六页全在模型外 | V12、W9 → 81/81 绿；vm 真跑产出里活标签 0 → 1 | ① 把哨兵**逐字段**塞：`resources[].name/vendor/account/last_error`、`counts`、`today_by_hour[].hour`、以及（若扩到六页）`logs.rows[].system_model/error_summary`，对每个字段各跑一次渲染并断言产出里 `<img`/`<script`/`onerror=` 作为活标签数为 0；② 加一条静态判据：页面文件里 `${…}` 插值若含 `name\|vendor\|account\|error\|message\|model\|request_id` 字段而未过 `esc(`/`fmtValue(` 即红（现在 `main.js:54` 的 `${e.message}` 就是现成的漏点） |
| **S-35 B11-5** | **真值无判据**：K3 只认标签、K5 的坏插值只有 `undefined`/`[object Object]`/`${` 三件套、A 段只钉少数锚点串（成因句/严重度句都不钉） | V10（八张卡数值全空）、V11（「成功比 NaN%」）、X4（今日切换写死 0）、W7/W8（告警成因被改成"临时冷却·无需处理"/"可忽略"）→ 81/81 绿 | ① K5 的坏插值集补 `NaN`、`null`、`Infinity`、`-0`、`undefined%`、`0/0`、`[object`，并断言**每张指标卡的值非空**（`visibleText(metricValue).length>0`）；② 值一致性：把载荷里的 `switch_count/success/failed/requests/tokens` 换成可辨识的哨兵值，断言界面文本出现同一数字（写死常量立刻红）；③ 告警文案：给四类各钉一条"成因子句白名单"（③类必须含「已停用或凭据失效」并含处置动作，②类不得出现「无需处理/可忽略」），并把"同一故障不得出现两种严重度口径"写成断言 |
| **S-35 B11-6** | **指路仍是语法白名单 + 动作↔页归属表是手写的**：`PAGE_REFS` 只认「」/『』括号与 10 个 cue 动词（`:553-568`）；pytest 侧 `owners`/`page_to_file` 只覆盖 3 个页名 6 个动作、`copy_files` 不含 `logs.js`/`stats.js`/`components.js`/`main.js` | V16（`【模型映射】页` 界面可见、门全绿；同锚点改「」立刻红 = W11）、X5/X6（页名真实存在但控件不在那一页，前端门 + `pytest -k route_copy` 双绿）、X1（`查看日志` 指向别的真页面） | ① 候选集反过来取：抽出源里**所有**括号串（`「」『』【】"" '' ()`）与"引号内出现的、等于或近似导航标签的串"，再用 `navLabels ∪ 死名黑名单` 判定；② 建**死页名黑名单**常量（模型映射 / 系统模型 / 接入管理 / 运行监控 / 运维面板 / 插件市场 …），全文命中即红，不依赖语法猜测；③ 动作↔页归属表由"页面实现文件里真实存在的控件标记"派生（现在是人写的），并把 `copy_files` 扩到 `web/static/js/**` 全量 |
| **S-35 B11-7** | **K4 把外链当噪声过滤**：`p !== "http" && p !== "https"`（`:781`） | V13 → 81/81 绿（管理台里出现 `https://docs.model-gateway.example.com/...` 远程外链，与"纯本地运行、无远程下发"的铁律承诺冲突） | K4 拆两条：① 页面产出里的每个 `href` 必须落在 `#/<页>` 或相对路径白名单内；② 出现 `http(s):` / `//host` 直接红（要外链就必须在 PRD 里登记为"外部链接清单"并逐条放行） |
| **S-35 B11-8** | **判据缺省 fail-open**：K8 的容器属性正则不匹配时缺省成空串（`:770` `… || ["", ""][1]`），"元素不存在"被判成"元素可见"；同一写法在 detail 里已经打出 `容器属性=无` 却不参与判定 | Z2（只改容器 id）→ 81/81 全绿 + 浏览器实测趋势卡里 160px 空白带、柱数 0；对照 Z1/Z3（改取节点 / 两边同改）都 `✗ K8` | ① 关键容器/节点的正则**取不到即判红**（缺省值改成 `null` 并 `if (!m) return false`），全站同类缺省（`titleOf`、`heads`、`dotTag`、`metaBlock`）一并过一遍；② K8 增加"容器必须存在且 `bars` 是它的**子节点**"这条结构断言（现在 `bars` 来自 `nodes` 表、容器来自 HTML 串，两者可以各说各话）；③ Z1 那类门自测表补"缺省形态"用例（空串 / null / 匹配失败） |

> 严重度排序（我的判断）：**B11-3 > B11-2 > B11-1 > B11-5 > B11-4 > B11-6 > B11-8 > B11-7**。B11-3 最严重是因为它**主动说谎**：后端明确 400 拒绝、配置一个字没改，界面弹的是绿色「配置已保存并热重载生效」；用户带着没生效的 `y/m/超时/冷却` 去跑生产，且界面上再也查不到痕迹。B11-8 单看后果只是"一张空白图表卡"，但它是**判据自身的 fail-open 形态**（缺省值把"查无此物"洗成"通过"），同一写法在门里还有多处，属于会持续制造新逃逸的元问题。

---

## ⑤ 对照实验（证明判据不是空过）

这 10 个变异**如期变红**，说明第十轮的机制在它覆盖到的范围内确实有效，也说明我上面那 39 条绿不是"门根本没跑"：

| # | 变异 | 变红的判据 |
|---|---|---|
| V3 | D：横幅 `class="alert alert-warn hidden"` | `✗ A1`、`✗ K1 横幅节点=0 期望=4` |
| W11 | LOG：空态文案写 `见「模型映射」页`（**带「」括号**的死页名） | `✗ J2 …违规指路：…logs.js→「模型映射」页` |
| W12 | D：横幅 `style="opacity:0"`（内联，六类样式之内） | `✗ K1 正文缺失=4`、`✗ K9` |
| X7 | D：`metricCard("运行状态"…)` → `"网关状态"` | `✗ K3 八张指标卡全部可见` |
| X8 | D：`<a href="#/operations">查看日志</a>`（路由不存在） | `✗ K4 …href="#/operations"` |
| Y3 | IDX：侧栏 `<span>资源池设置</span>` → `<span>模型映射</span>` | `✗ J1`、`✗ J2` |
| Y4 | IDX：删掉日志导航项的 `data-page`（**不在变异表里**的对照） | `✗ J1`、`✗ J2`、`✗ K4` |
| Y5 | IDX：红点 `title` 的「点击确认」→「查看详情」（**不在变异表里**的对照） | `✗ E4` |
| Z1 | D：`getElementById("hour-chart")` → `("hour-cart")` | `✗ K8 … 元素数=0` |
| Z3 | D：容器与取节点**两边同时**改名 | `✗ K8 … 容器属性=无 元素数=0` |

另外两组反向自证：

- **门的基线耦合**：把载荷换成"正常态"（`warnings: []`、四资源全 `active`、`last_error: null`）后跑门 → `实测 81 项，通过 67 项，失败 14 项`（A7/A8/A9/B3/B4/K1/K2/K6 等红）。**这条不是逃逸**，但它说明：机械门的"绿"只对应一份**合成故障载荷**，永远无法在用户实况数据上跑绿 → 交付回复里"门 81/81 绿"不能被读成"用户当前界面没问题"。（登记为 ⑥ T1。）
- **`--mutation` 与这些洞不相交**：在 `base.css` 藏着 `.alert-warn{display:none}`、以及 `api.js` 藏着 `if (false)` 的两种情况下分别跑 `--mutation`，两次都输出 `可红 100/100；每条断言都有对应变异`。

---

## ⑥ 理论限制 / 登记项（拿不出用户可见坏结果，或已实测无坏结果）

- **T1 门与载荷耦合**：见上。判据把"四类告警 + 一条熔断资源"当成载荷前提，正常运行的网关实况会让门红 14 条。修法方向：K/A/B 段的判据改为"按传入载荷的形态**条件断言**"（有告警才比横幅数，有冷却才比钟点），另设一份"健康态载荷"跑零横幅/零冷却的正交断言。
- **T2 CSS 源码顺序**：V2 里 `.nav-item[data-page="logs"]{display:none}` 未生效（与 `base.css:147` 的 `.nav-group .nav-item{display:flex}` 同特异度、且我的插入点在文件前部），实测导航项仍高 36。同类隐藏要写成 `!important` 或追加到文件末尾 —— 我用 V7c（工具类 `.hidden{display:none!important}`）达成了同样的用户可见后果并实测到 `height:0`。**这条也是给修法的提醒：判据若按类名解析 CSS，必须连层叠顺序与 `!important` 一起算。**
- **T3 `hidden` 属性在部分元素上无效**：IDX 导航项加 `hidden` 后浏览器仍显示（`display:flex` 覆盖 UA 规则）→ 该变异无坏结果，不计阻塞；但同一写法在 `.ops-dot` 上项目是**专门补了** `.ops-dot[hidden]{display:none}`（`CSS:1125`）才生效的，说明这层依赖是逐个组件手工打的补丁。
- **T4 装载兜底判据的短路顺序**：W1（去掉 `!c.firstElementChild`）实测无变化，因为前一行 `if (window.__MG_BOOTED) return;` 先短路。坏结果不成立 → 不计阻塞。
- **T5 `switchEl` 显示反转（W4）**：门全绿，浏览器实测只有**短暂**反相，`persist()` 的整页重绘会纠正 → 记为登记项而非阻塞；但两处调用点（`apiaccess.js:107`、`resources.js:447`）都依赖"保存后整页重绘"来掩盖显示错，这层依赖本身没有判据。
- **T6 假 DOM 与真浏览器的差异（本轮攻到了，成果转成 B11-8）**：`renderPage` 的 `getElementById` 会**自动建节点**（`:623`），所以"代码写进一个界面上不存在的 id"这件事门永远看不到报错。三条实测把边界划清：改取节点（Z1）红、两边同改（Z3）红、**只改容器 id（Z2）绿** —— 因为 K8 的 `bars` 维来自 `nodes` 表、容器维来自 HTML 串且缺省 fail-open。残余风险：任何"新增第二个写点"（例如把指标值也搬到 `getElementById("x").innerHTML=`）都会同样只在 HTML 串之外留下内容，门看不见。
- **T7 `matchMedia` 恒 `matches:false`**：主题段本轮根本不被执行（B11-2 已计），所以这条差异本轮不是独立逃逸；等 ④ B11-2-④ 落地后需要真值表（light/dark/system × matches true/false）。
- **T8 门自身的规则可以被静默删掉（实测）**：把 `visibleText()` 的丢弃标签名单从 `["script","style","template","noscript"]` 改成去掉 `"noscript"` → `实测 81 项，通过 81 项，失败 0 项` **且 `--mutation` 仍 `可红 100/100`**（表里没有依赖 `<noscript>` 的变异，Z1 又只测 `isInvisible`）；作为对照，去掉 `"template"` → `可红 99/100 … ✗ 🔴 第十轮 B10-2：正文包进 <template> ← 未红：K1`（rc=1，被抓到）。**结论：门自身语义模型的可删除性取决于"变异表里恰好有没有依赖这条规则的变异"，而不是取决于门自测。** 建议：Z1 从"测 `isInvisible` 纯函数"扩到"测 `visibleText` 的整棵结构"（`<noscript>`/`<template>`/`<style>`/嵌套隐藏祖先/未闭合隐藏标签各一例），并把 `self:true` 的变异从 2 条扩到"每条被删规则一条"（`--mutation` 里已有子进程跑副本的机制，成本只是表变长）。因缺"用户可见坏结果"，本条按登记处理，不占阻塞名额。
- **T9 未实测的坏结果（诚实标注）**：V13（外链）、V17（失败行过滤）、V18（成功率分母）、V20（自动刷新清单）、W6（脚钮贴死）、W7/W8（告警成因文案）、W10（兜底文案）、X1（跳错真页）、X4（今日切换写死）、X5/X6（指路页名）—— 这些**门全绿是实测的**，坏结果目前是代码路径/文案直达层面的推断（其中 W7/W8/X4 有 K1/A 段的"后端文案原样透传"作为间接证据）。下一轮若补浏览器复采，优先补 V17/V18/X4 三条（数字造假类）。
- **T10 `data/` 与文档不在面内**：J2 面覆盖 `model_gateway/**` 的 `.py/.js/.css/templates/*.html/index.html`（本轮实测 `入面文件=80`），`.md` 与 `scripts/` 不在内；文档写错页名属 PM 侧一致性问题，不在本门范围。

---

## ⑦ 收工自证

```
$ cd /Users/w/Desktop/Model-Gateway && git status --porcelain | wc -l
开工：82
收工：82          # 本轮我未改动仓库任何文件（docs/ 被 .gitignore 忽略，本报告不入数）
```

- 变异只施加在 `/tmp/mgw-accept-11/` 副本；收工逐文件与仓库 md5 比对，**17/17 全部 same、0 个 DIFF**（`dashboard.js` `index.html` `base.css` `api.js` `components.js` `main.js` `apiaccess.js` `logs.js` `models.js` `resources.js` `settings.js` `stats.js` `templates.js` `main.py` `core/resources.py` `cli_setup.py` `verify_v2_frontend.mjs`），驱动器每条变异跑完即还原并断言 `read()==原内容`
- 仓库侧 `md5 scripts/verify_v2_frontend.mjs = 9048425fcfce660f6c6cb85255056642`（与开工快照一致，门源码未被我为通过而改；T8 那两次"删规则"实验写在副本里、跑完即还原，已复核 `gate restored: True`）
- 临时实例：`/tmp/ix11-serve.py`（端口 55845，数据目录 `/tmp/ix11-data`，合成假 Key `sk-fake-*`、`base_url=127.0.0.1:9`）→ 已 `pkill -f ix11-serve.py`，复跑 `curl http://127.0.0.1:55845/` = `000`（确认已下线）；**未重启/未触碰 :8300**（开工时 `curl http://127.0.0.1:8300/` 返回 000，即用户实例未在跑；期间发现 8399 被并行面板占用，已改随机端口避让）
- 期间对临时实例配置做过 `PUT /admin/api/config`（加/删一个假接入密钥、试写 `fail_threshold=0`），全部落在 `/tmp/ix11-data/config.yaml`；仓库 `data/` 全程只读（未写一个字节）
- 浏览器证据：`/tmp/ix11-shots/` 18 张截图 + 上表内联的 `getBoundingClientRect/getComputedStyle/innerText/elementFromPoint` 读数；ego-browser 任务空间均已 `finish()`
- 本报告存在性（逐字）：

```
$ ls -la docs/changes/reviews/ix-accept-11.md
-rw-r--r--@ 1 w  staff  39929 Sep 28 17:49 docs/changes/reviews/ix-accept-11.md
```

---

### 附：本轮变异清单（49 条，全绿 39 / 变红 10）

`ix11-specs-batch{1,2,3,4,5}.json` + `*.result.json`（每条含锚点命中数、跑完的门汇总行与红项原文）留在 `/tmp/`，可原样复跑：

```
python3 /tmp/ix11-drive2.py /tmp/ix11-specs-batch1.json
node /tmp/ix11-xss.mjs                       # 转义族（V12/W9）的活标签计数
python3 /tmp/ix11-serve.py                   # 浏览器复采用的临时实例（IX11_PORT 环境变量指定端口）
```
