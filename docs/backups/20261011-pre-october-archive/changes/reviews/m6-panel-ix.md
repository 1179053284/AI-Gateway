# M6-IX 面板评审报告 · 「账号接入」页（交互与视觉 · 独立评审）

> 角色：IX（交互与视觉）独立评审，**非实现方**；交付闸门 = 零阻塞才算通过。
> 评审对象：`model_gateway/web/static/js/pages/accounts.js` + 导航/PAGE_META（`main.js`/`index.html`）
> ＋ R3 后修复项（`accounts.js:562` 省略样式、`api/admin.py::admin_write_origin_guard`）。
> 基准：`docs/specs/frontend-spec.md`（唯一前端基准）+ `tech-design §22.7/§22.6` 行为契约。
> 纪律：**未改任何前端/后端源码**（唯一仓库写入 = 本报告 + 3 张新截图）；独立实例端口 **8396**，
> `MG_CONFIG=/tmp/m6ix-5830/config.yaml`（数据面全在 /tmp）；未碰 `:8300`、`data/**`、并行工作流文件
> （`pages/logs.js` / `pages/stats.js` / `scripts/verify_v2_frontend.mjs` 未读未改）。
> 快照：2026-09-30（工作树含未提交 M6 增量）；评审方法 = 静态通读 + 独立实例真机 CDP 重跑 + 磁盘/日志核证。

## 0. 结论摘要

**结论：通过。阻塞项：0。**

真机独立重跑 **83 条断言记录 / 81 项（去重）全部 PASS**（47 + 10 + 12 + 10 + 2 + 2；其中 S12/S15 首轮 2 条系我方断言写法错，修正版复测通过，见 §2.6 注）；
两项重点修复复验均成立：
- **P-1（qr_payload 行省略）已修实**：`.modal-body` 横向滚动消除（`scrollWidth 558 == clientWidth 558`；R3 修前 886>558），
  行内 `nowrap/hidden/ellipsis` 生效且真截断（span 1127>464）。
- **CSRF guard 未误伤自家页面**：同源 POST 全部 200（enable/disable/delete/login-start/poll/alt/callback，共 7 类），
  跨源页（:8397）no-cors POST 实测 **403** 且盘面零变化。

发现 5 条（**全部非阻塞**，均附最小复现/落点）：1 条证据标注行号漂移（低）、3 条可读性/文案（信息级）、
1 条既有登记缺口复核（信息级）。无任何「疑似」结论 —— 见 §6。

---

## 1. 评审环境与产物（可复跑）

| 项 | 事实 |
|---|---|
| 实例 | `MG_CONFIG=/tmp/m6ix-5830/config.yaml` → 数据目录 `/tmp/m6ix-5830/`；端口 **8396**；进程 `launcher.py`（uvicorn，127.0.0.1） |
| 实例形态 | `create_app` 真实代码 + 真实 HTTP 端点；**仅**把向导展示面的 10 个钩子函数替换为 canned 值（buddy/qoder/loomy/cline 的 `login_start`+`login_poll`、loomy 的 `_ALT_HOOKS` sms 两步、raccoon 的 `login_poll`；全部 `example.com`/`mock.invalid` 固定串，零真实凭据、零触网）。**raccoon `login_start` 未 patch**（本地生成 → P-1 复验走真实代码路径） |
| 种子 | 假凭据（标记串 `SECRET-IX-DO-NOT-LEAK-8899c1`）经 `store.commit_login` 落盘：buddy×3（demo1 启用 / **demo2 停用** / ix-del1 删除用）、lobsterai（uuid）、trae（machine_id+device_id）、loomy（refresh=false）、raccoon（checkin=false）、qoder（**runtime.json 故意损坏**）；cline 零账号（空态） |
| 断言脚本与结果 | `/tmp/m6ix-5830/dom_check{,2,3,4,5}.py`、`dom-results{,2,4,5,5b,6}.json`；截图 `/tmp/m6ix-5830/shots/` |
| 浏览器 | headless Chrome（CDP，独立 user-data-dir `/tmp/m6ix-5830/profile*`，端口 19225–19234） |
| 网络边界（浏览器侧） | 全量请求主机枚举 = `127.0.0.1:8396` + `loomy-qr.mock.invalid`（QR mock 图 DNS 失败，属设计内 onerror） |
| 服务端状态码全量统计 | `gateway.log`：**1782×200 / 14×404（全 favicon）/ 4×403（全部为跨源 `POST /buddy/buddy-demo1/disable` 攻击尝试）/ 0×5xx** |
| 仓库写入 | 本报告 + 截图 3 张（`m6-panel-ix-light.png` / `m6-panel-ix-dark.png` / `m6-panel-ix-qr-payload.png`，均落在 `docs/changes/e2e-records/`） |

---

## 2. DOM 断言表（83 条记录 / 81 项去重，全 PASS）

### 2.1 骨架 / 顶栏 / 子侧栏（A 组）

| # | 断言 | 结果 | 关键实测值 |
|---|---|---|---|
| A1 | 导航项高亮 = accounts | PASS | `.nav-item.active` → `accounts` |
| A2 | 两行顶栏 PAGE_META 注入 | PASS | `资源配置` › `账号接入`；`document.title = 账号接入 · Model-Gateway` |
| A3 | 页内无重复页标题（`#content h1/h2` = 0） | PASS | 0 |
| A4 | 骨架 A：接管留白 `-12/-12/-48` + 高 `vh-60` + 子侧栏 248 + 右区内部滚动 + p-12 | PASS | `793/853`、`sw=248`、`ov=auto`、`pv=12px` |
| A5 | 产品族分组卡 = 8 | PASS | CodeBuddy 族/LobsterAI/Qoder 族/Trae/Cline/Loomy/Raccoon/ZCode |
| A6 | 子侧栏产品行 = 10 且顺序 = `registry.PRODUCT_IDS` | PASS | `[buddy…zcode]` 逐项一致 |
| A7 | 产品行 title = 账号数(启用数) + 登录方式 | PASS | `CodeBuddy · 3 个账号（2 启用）· 登录方式：外链授权` |
| A8 | 状态圆点：有启用则亮 / 零账号不亮 | PASS | buddy ✔ / workbuddy ✘ / cline ✘ |

### 2.2 头卡 / 表结构（B 组）

| # | 断言 | 结果 | 关键实测值 |
|---|---|---|---|
| B1 | 头卡：logo 首字母 + 副行（登录形态/协议/账号数/设备身份） | PASS | `C`；`外链授权 · OpenAI 兼容 · 3 个账号（2 启用）· 设备身份：无` |
| B2 | 卡头统计 `.value` | PASS | `3 个账号 · 2 启用` |
| B3 | 表格卡 `.card.flush` + `.card-head.inset`，添加钮在卡头 | PASS | `#ac-add` 位于 `.card-head` |
| B4 | buddy 列 = [账号,状态,最近结果,操作]（无设备/额度列） | PASS | 4 列，额度全 unknown → 整列不渲染 |
| B5 | 账号行 = demo1/demo2/ix-del1 | PASS | 顺序按目录名 |
| B6 | 停用行 `td.off` + `已停用` + 开关关态 | PASS | `off=true / sw=false` |
| B7 | 开关 a11y 三件套全量 | PASS | 3/3 `role=switch` + `aria-checked` + `aria-label=启用 / 停用账号 <name>` |
| B8 | 操作列能力驱动 = probe+refresh+claim+delete 全可用（buddy） | PASS | 4 钮 `disabled=false` |
| B9 | 行内图标钮 28×28 + aria-label 齐备 | PASS | 12/12 |
| B10 | 图标契约（fill=none / stroke=currentColor / sw=2 / 14px） | PASS | 13/13，bad=0 |
| B11 | 卡片档（radius 10 / shadow-card / p-12）+ 块间距 12px | PASS | `10px / rgba(15,23,42,.035) / 12px / gap 12` |
| B12 | D3 无「保存」/ 无导出（v2.6） | PASS | 0 / 0 |

### 2.3 能力位 / 设备列 / 空态 / 异常态（C 组）

| # | 断言 | 结果 | 关键实测值 |
|---|---|---|---|
| C1 | lobsterai 设备列 `uuid = …` + 头卡「设备身份：uuid」 | PASS | 列 = [账号,状态,设备,最近结果,操作] |
| C2 | trae 设备列双行 + 头卡「本机回跳 · 产品专属出站塑形」 | PASS | `machine_id = …` + `device_id = …` |
| C3 | loomy 续期置灰 + 原因 + claim 保留 | PASS | `disabled+off`；title=「该产品不可续期：续期通道未登记（tech-design §22.6）」 |
| C4 | raccoon 无签到钮（checkin=false）；onboarding 未登记不渲染 | PASS | ops = [probe, refresh, delete] |
| C5 | qoder 运行态损坏 → fail closed | PASS | `状态未知` + warn 色 `rgb(194,106,0)` + dot 灭 + title 给原文原因 |
| C6 | cline 空态文案（含登录形态指路）+ 无表格 | PASS | `暂无账号——点击「接入账号」用设备码授权完成第一个账号接入` |

### 2.4 登录向导（W 组，**6 型**全跑）

| # | 断言 | 结果 | 关键实测值 |
|---|---|---|---|
| W1a–c | **device_code**（qoder）：参数段 / 进行段 / 轮询 | PASS | 设备码+复制+授权地址+打开；2.4s 后转「等待中」 |
| W2a–b | **local_callback**（trae）：粘贴段 + **零轮询** | PASS | 2.7s 内 `/login/poll` 计数 1→1（零新增），状态保持「等待用户操作」 |
| W3a–c | **external_link**（buddy）：地址 + 打开 + 轮询 + 重名提示 | PASS | 重名提示=`同名账号已存在：登录成功会覆盖其凭据目录` |
| W4a–b | **qr=图片**（loomy）：双形态 tab + `<img>` 渲染 | PASS | `src=…mock.invalid…`、`width=200`；无 payload 文本分支 |
| W5a–c | **qr=内容**（raccoon）：如实展示 + 不伪造图 + **P-1 复验** | PASS | 见 §3.1 |
| W6a–b | **sms_code**（loomy 两段）：手机号→发送→验证码段 | PASS | 手机号锁定 + `待继续` + detail 原文（pending 不作错误，`alert-info`） |
| W7 | 账号名重名即时提示（同一断言在参数段复测） | PASS | 覆盖语义文案 |
| W8/W8b | 输入 focus 态 + 弹窗规格 | PASS | 边框 `rgb(23,27,34)` + 底白；h-44/radius 8；弹窗 560px/radius 10/脚钮 1 |
| F9/F9b | **失败出口**（非法回跳）→「登录失败」+「重新发起登录」→ 恢复 | PASS | 文案=`回跳校验未通过：回跳路径不是 /authorize（实际 /not-a-callback）` |

### 2.5 D3 交互 / CSRF / 主题 / 运行期（E/T/R 组）

| # | 断言 | 结果 | 关键实测值 |
|---|---|---|---|
| E1/E1b/E1c | 启停点击 → 重取视图；响应 200；Origin 同源 | PASS | `Origin: http://127.0.0.1:8396` + `Sec-Fetch-Site: same-origin`；节点换代（防陈旧竞态） |
| E2 | 启停往返（再点回停用）+ 盘面 | PASS | 200；盘面 `enabled=true→false`，`updated_at` 刷新、`via='import'` 保留 |
| E3/E4 | 删除二次确认弹窗 + 取消不落库 | PASS | 标题/级联文案/脚钮 2 颗/**gap=8px**/`btn-danger`；取消后 `/delete` 请求数 0 |
| E5/E5b | 确认删除 → 视图消失 + 200（`?confirm=1`）+ 盘面目录移除 | PASS | 行数 3→2；`upstream/buddy/accounts/ix-del1` 不存在 |
| E6 | **跨源 no-cors POST → 403**（guard 真生效） | PASS | `Origin: http://127.0.0.1:8397` → `403`；buddy-demo1 盘面 `enabled=true` 未变 |
| T1/T2 | 双主题（浅 `#f7f8f9` / 深 `#101114`，顶栏 on 态） | PASS | 卡片深色底 `rgb(23,25,29)` 反转正确 |
| R1/R2 | 零 JS 异常 / 零 console.error；请求仅本机+mock 图域 | PASS | exceptions 0 / console_err 0；hosts=[127.0.0.1:8396, loomy-qr.mock.invalid] |

### 2.6 frontend-spec 组件级条款实测（S 组）

| # | 条款 | 结果 | 实测 |
|---|---|---|---|
| S1/S2 | §7.9 表头 12px/700/faint/.02em/padding 10×16 / 单元格 padding 12×16 | PASS | 逐值一致 |
| S3 | §7.2 开关 40×24、knob 20×20、radius-full | PASS | 一致 |
| S4 | §7.1 `.btn-sm` h-30 / radius 8（卡头添加钮） | PASS | 30px / 8px / 12.5px |
| S5 | §7.13 `.card-head .value` 13px/600 muted | PASS | `rgb(89,97,106)` |
| S6 | §7.4 toast（fixed 顶部居中 / 16px / radius 10 / 卡片式） | PASS | mid=720 = vw/2 |
| S7 | §7.12 空态 `.empty` 13px/600 tertiary 居中 | PASS | 卡内覆写 `border/radius=0`（依 v1.7 禁框包框，与 resources/apiaccess 同款先例） |
| S8/S8b | §7.16 输入 label 关联（账号名 / 回跳 textarea） | PASS | `label[for]` 逐项 |
| S9/S10/S11 | §10 断点：≤1280 底 -40px；≤768 `-12/-10/-36` + 应用侧栏抽屉化 | PASS | `matrix(1,0,0,1,-220,0)` + fixed |
| S12b–S21 | §3.1 子侧栏细节：248/白底/`--side-border(#f6f7f8)`；group-card p-8/inset/radius10；mode-btn h-32/radius6/13-700/active 白底+inset `--text`；mark-sm 20×20/radius6；组标题 12-700-faint/pad 0；`.dot` 8×8 `#16d76d`；导航 active 尾点 6×6；`.nav-ico` 16px；`th.num` 左对齐（v2.13）；icon-btn.sm radius 8 + 图标 14；`.off` opacity .5 | PASS | 逐值一致 |
| 图标几何 | §7.7 **逐 path 与 Lucide 0.555.0 官方源码对表** | PASS | 页内 10 图标（plus/trash-2/copy/heart-pulse/refresh-cw/calendar-check/award/external-link/qr-code/smartphone）+ 导航 `user-round`（sw 2.1）**geometry 全等**（对参考项目 `node_modules/lucide-react@0.555.0` 只读比对） |

> 说明（我方初版期望值写错、复测澄清的 2 处，防误读）：S12 首轮把 `--side-border` 期望写成 `--border(#eef1f3)` → 复测 `#f6f7f8` 正确；
> S15 首轮选择器写错致表达式异常 → 改 `nth-child` 后复测全绿。**实现无过，属评审侧断言写法问题。**

---

## 3. 重点修复项复验（R3 后修复轮）

### 3.1 P-1：向导 qr_payload 行省略样式（`accounts.js:562`）

R3 修前实测：`.modal-body` `scrollWidth 886 > clientWidth 558`（横向滚动条）+ 内容折两行。
本轮独立复验（raccoon 真实 `login_start`，非 canned）：

| 观测点 | 修前（R3 记录） | 本轮实测 | 判定 |
|---|---|---|---|
| `.modal-body` scrollWidth / clientWidth | 886 / 558（溢出 328） | **558 / 558** | 修复成立 |
| payload `<span>` computed | `normal / visible / clip` | **nowrap / hidden / ellipsis** | 修复成立 |
| 真截断（span scrollWidth > clientWidth） | — | **1127 > 464**（title 携全值 144 字符） | 修复成立 |
| 视觉 | 折两行 + 横向滚动条 | 单行省略号 + 无滚动条（截图 `m6-panel-ix-qr-payload.png`） | 修复成立 |

### 3.2 CSRF guard（`api/admin.py::admin_write_origin_guard`）与页内 POST 的相互影响

| 场景 | 请求头 | 结果 | 判定 |
|---|---|---|---|
| 页面启停（enable/disable） | `Origin: http://127.0.0.1:8396` + `Sec-Fetch-Site: same-origin` | **200**（响应体正常，视图重取） | 未误伤 |
| 页面删除（`?confirm=1`） | 同上 | **200** + 盘面目录移除 | 未误伤 |
| 向导四端点 start/poll/alt/callback | 同上 | **200 × 4** | 未误伤 |
| 异源页（:8397）no-cors POST disable | `Origin: http://127.0.0.1:8397`（`Sec-Fetch-Site: same-site`） | **403** + 盘面零变化 | 拦下成立 |
| 服务端日志全量 | — | 403 共 4 条（全部跨源尝试）；同源 POST 0 个 4xx | 无假阳性 |

---

## 4. frontend-spec 逐条对照（账号页相关条款）

| spec 条款 | 判定 | 依据 |
|---|---|---|
| §1.1 色彩只用令牌 | 符合 | `accounts.js` 零硬编码色值（静态扫描 0 命中）；实测色值 = 令牌值 |
| §1.2 圆角（4/6/8/10/full，禁裸写 px/50%） | 符合 | 仅 `var(--radius-*)`；唯一字面量 `border-radius:0`（卡内空态归零覆写，与 `resources.js:542/559/907`、`apiaccess.js:143` 同款先例） |
| §1.3 字号体系（15/13/12/11） | 符合 | 内联尺寸仅 15/13/12px 三档 |
| §1.4 间距 4 的倍数、页内块距 12px | 符合 | 卡片 gap 实测 12px ×N |
| §2.1 侧栏导航项（h-36 / radius 8 / 13-600 / 图标 16 sw2.1 / active 尾点 6×6） | 符合 | 导航新增项沿用既有类，实测 16px/sw2.1/6×6 尾点 |
| §2.2 两行顶栏 PAGE_META | 符合 | A2 |
| §2.3 双面板接管留白（含 ≤1280/≤768 断点） | 符合 | A4 + S9/S10 |
| §2.4 骨架选型 = **A（子侧栏双面板页）** | 符合 | subnav 248 + 右区内部滚动；与 models/resources 同构 |
| §3.1 `.subnav`/`.group-card`/`.mode-btn`/`.mark-sm`/`.dot` | 符合 | S12b–S16 逐值 |
| §7.1 按钮与 icon-btn | 符合 | S4/S20（btn-sm h-30；icon-btn.sm 28×28 + 14px 图标） |
| §7.2 开关 | 符合 | S3 |
| §7.3 圆点（只读数据态） | 符合 | 圆点无 click 处理（源码 + 实测只读），可操作态由 `.switch` 承担（范式⑥） |
| §7.4 toast | 符合 | S6 + 各操作均有 toast（E 组/向导各步） |
| §7.7 图标体系（Lucide 0.555.0 / 属性契约 / 尺寸描边） | 符合 | B10 + 官方源码逐 path 对表 11/11 全等 |
| §7.9 表格（th/td/`.num`/`.strong`/`.off`/`.mono`） | 符合 | S1/S2/S19/S21；`td.ops` nowrap 局部补丁 |
| §7.11 弹窗（560/86vh/radius 10/脚钮平铺 gap 8） | 符合 | W8b + E3（gap 实测 8px，v2.5 契约） |
| §7.12 空态/加载态 | 符合（有意的卡内变体） | S7；`.empty` 卡内覆写与既有页一致 |
| §7.13 `.card-head`/`.card-head .value` | 符合 | S5 |
| §7.14 `.form-row`/`.in`/`.addr-value`/focus 态 | 符合 | W8 + 各按钮/输入实测 |
| §7.16 可访问性基线 | 符合 | 开关三件套（B7）、图标钮 aria-label（B9/S8）、输入 label（S8/S8b）、弹窗关闭 `aria-label=关闭`（W1a） |
| §7.17 脚本健壮性（禁空引用/一个失败不拖垮初始化） | 符合 | 全交互路径 `Runtime.exceptionThrown = 0`（R1）；`#ac-add` 直引用由同函数先渲染保证 |
| §8 交互范式①toast ②开关即时+删除确认③行内编辑(不适用)④分段 tab⑤搜索(不适用)⑥状态双呈现⑦**D3**⑧草稿槽位(不适用)⑨敏感值脱敏(不适用: 页面不展示密钥)⑩异步反馈(按钮防连点+轮询)⑪卡级操作归属 | 符合 | E1–E5、W1–W8、B3（添加钮在卡头）；⑨/⑧ 本页无对应面 |
| §9 暗色主题（令牌反转、组件零改动） | 符合 | T2 + 双主题截图（`m6-panel-ix-{light,dark}.png`） |
| §10 响应式（1280/768 断点 + 表格横向滚动 + 抽屉化） | 符合 | S9–S11 + `m6-accounts-narrow.png` 交叉印证 |
| §12 新页面 PR 自检清单（令牌/间距/卡片/尺寸/focus/暗色/空态/删除确认） | 符合 | 上表逐项 |
| 行为契约（tech-design §22.3/§22.6/§22.7 前端面） | 符合 | local_callback 零轮询（W2b）、pending 原文呈现不成错误（W6b）、NotRefreshable 置灰给原因（C3）、删除 `?confirm=1`（E5）、claim 入口能力驱动（C4）、未登记能力不渲染（C4/onboarding） |
| 已登记缺口（`accounts.js` 文件尾 ①–⑤） | 复核：与实现一致 | ①onboarding 无端点→隐藏 ②无取消会话端点（关闭后留 TTL）③sms start 仍走主形态 ④「最近结果」仅本会话 ⑤import UI 未做。均**不构成本面板阻塞**，属已登记的诚实取舍 |

---

## 5. 四态走查（空 / 无能力 / 不可用 / 异常）

| 态 | 触发 | 呈现（实测） | 出口 |
|---|---|---|---|
| **空**（零账号） | cline | `暂无账号——点击「接入账号」用设备码授权完成第一个账号接入`（文案随产品登录形态动态）；无表格 | 卡头「＋ 接入账号」→ 向导（W1 通道） |
| **无能力** | raccoon（checkin=false）/ loomy·raccoon（onboarding 端点未登记） | 相应按钮**不渲染**（未登记=不渲染，不做「点了必然失败」的钮）；其余动作照常 | probe/refresh/delete 仍可用；无死胡同 |
| **不可用** | loomy 续期（能力 refresh=false）；停用账号（buddy-demo2） | 续期钮 `disabled+off` + title 给原因；停用行 `td.off`（opacity .5）+ 状态「已停用」+ 开关关态 + title 说明「运营执行跳过（续期不受影响）」 | 开关即时切回启用（E1/E2 往返实测）；续期不因停用被锁（正交） |
| **异常** | qoder `runtime.json` 损坏（fail closed）；登录流程失败（非法回跳） | `状态未知`（warn 色、dot 灭、title 携可读原因含文件路径与解析错误）；`登录失败` alert-err + 原因原文 | 「重新发起登录」回到「等待用户操作」（F9b 实测）；轮询连续失败上限后「轮询已停止」+ 原因（源码 `accounts.js:761-769`） |
| 附：**pending 正常态** | sms 下发（loomy canned） | `待继续` + detail 原文（灰蓝 info，不着红色） | 提交验证码 / 重新发送 |

**可读性结论**：四种态的文案均「说人话」且都可行动；pending 与失败在视觉上严格分色（只有失败着色）。

---

## 6. 发现清单（0 阻塞；含最小复现/落点）

1. **F-ix-1（低 · 证据标注行号漂移）**：`m6-accounts-assertions.json` 的 P-B1 `note` 与 R3 报告 §7-P-2 均引
   `store.py:447-473`，实际落点为：调用点 `store.py:551`、实现 `store.py:726-756`、P-B1 注记 `store.py:733-737`
   （447-473 现为 `hook_meta`/`load_credentials`）。语义正确（比较基准=merged 已实机复验：enable/disable 均 200、
   `updated_at` 刷新、`via` 保留），仅**指针不实**。建议：改 note 行号（一行编辑）。
   **最小复现**：`grep -n "_verify_written" model_gateway/accounts/store.py`。
2. **F-ix-2（信息级 · 可读性）**：loomy 续期钮 title 引用内部文档编号「（tech-design §22.6）」——
   对最终用户是噪音。建议改纯用户语言（如「该产品未提供续期通道」）。落点：`accounts.js:309-310`（实测 title 原文见 C3）。
3. **F-ix-3（信息级 · 可读性）**：短信形态的导语落在 `guideText` 默认分支「请按上方指引完成登录。」
   （device_code/qr/local_callback/external_link 均有专属导语）。建议补 `sms_code` 分支（如「先点『发送验证码』，收到后填入完成登录」）。
   落点：`accounts.js:624-639`；复现：loomy 向导 → 短信 tab → 开始登录。
4. **F-ix-4（信息级 · 既有登记复核）**：向导关闭后服务端会话保留至 TTL（无「取消会话」端点）。
   已在 `accounts.js` 文件尾缺口②登记；本面板复核确认**文案无欺骗**（关闭即关窗、无「已取消会话」的假承诺）。
5. **F-ix-5（信息级 · 设计取舍）**：运行态损坏的 title 直接给绝对路径 + JSON 解析错误原文（如
   `/private/tmp/…/runtime.json（Expecting property name…）`）。本机自用场景下对诊断有价值，**不建议改**，仅登记。

> 另确认「R3-P2 已闭环」：断言 JSON 的 P-B1 条目已带 `status: fixed-by-Fix4` + `recheck_after_fix`（复现记录保留不删），
> 与「历史记录 vs 通过断言」的语义已分离，不再有误读面。

---

## 7. 证据真实性核对（防「证据漂移」）

| 面 | 核对方法 | 结论 |
|---|---|---|
| 9 张既有截图 | **逐张打开检视（9/9 全量）**：light、dark、narrow、wizard-device、wizard-callback、wizard-sms、wizard-qr-payload、wizard-external、wizard-qr-img | **与当前代码一致**（布局/文案/开关态/列集合逐项可对上）；`wizard-qr-payload` 里可见的横向滚动条 = P-1 修前缺陷本体（修复已由 §3.1 复验闭环）；`qr-img` 为 mock 域不可达的 broken-image 设计内形态；`wizard-external` 的 mock URL 展示文本含真实厂域（`copilot.tencent.com/login/demo`，仅文本、无请求痕迹——与本轮 R2 断言「未触达真实上游」一致，同 R3 §6 口径） |
| 真实顺序截图痕迹 | 跨步骤 err toast（loomy 图 onerror）在 device→sms→callback→qr-payload 多张顶部同串延续 | 判为真实顺序截屏（非拼贴），与 R3 结论一致 |
| 断言清单 vs 实现 | 抽样 ≥8 条落代码 + 全部等价重跑（见我 §2 的 81 项） | A13→`accounts.js:223`；A16b→`:305-311`；A16c→`:312`；A16e→`:84`+`:316`；W4b→`:54`+`:500`；D1b→`:330-339`→`admin_accounts._set_enabled`；D2→`:411-422`；P-1→`:562`。**逐条一致，无漂移** |
| P-B1 修复标注 | `store.py:551`（merged 基准）+ 实机 enable/disable 往返 200 + 盘面 `updated_at/via` | 修复真实有效；仅行号指针漂移（F-ix-1） |
| 凭据不泄露（辅助抽查） | 我种子标记串 `SECRET-IX-…` 在页面文本/响应体/日志扫描 | 零命中（与本面板主职无关，附带确认） |

---

## 8. 未验证 / 明确不做

- **真实凭据逐产品登录/领取出证**：按用户裁决不做（canned 仅替换向导展示面 6 个上游调用；claim/probe/refresh 的真实钩子**未点击**——页面按钮存在性/置灰判据已断言，**点击后的真实上游结果未实测**）。
- 未跑 pytest（本面板职责为真机交互与视觉；计数与用例门由其他面板负责）——**本报告不转述任何 pytest 计数**。
- 未覆盖：zcode/qodercn/workbuddy/lobsterai 的向导实跑（能力位/设备列/空态/按钮判据已按注册表断言；其 canned 未备）；「会话已过期」「轮询已停止」两态的**真机触发**（源码路径已核，未构造过期会话做 UI 实测）。
- 窄屏 390px 的**交互**（抽屉开合）未重跑，只核了断点与抽屉化 CSS/矩阵（R3 已实测过抽屉化）。

---

## 9. 复跑指引

```bash
# 实例（保持运行中；如需重启）
MG_CONFIG=/tmp/m6ix-5830/config.yaml /Users/w/Desktop/Model-Gateway/.venv/bin/python /tmp/m6ix-5830/launcher.py
# 断言（4 段，全 PASS 时输出 TOTAL n FAIL 0）
.venv/bin/python /tmp/m6ix-5830/dom_check.py    # 47 条：骨架/能力/设备/向导6型/主题/异常
.venv/bin/python /tmp/m6ix-5830/dom_check2.py   # 10 条：D3 启停/删除/CSRF（需先重置 buddy-demo2=停用 + 重建 ix-del1）
.venv/bin/python /tmp/m6ix-5830/dom_check4.py   # 12 条：组件级条款
.venv/bin/python /tmp/m6ix-5830/dom_check5.py   # 10 条：子侧栏细节（S12/S15 以 dom-results5b.json 的修正版为准）
# 跨源 PoC 页面：python -m http.server 8397 --bind 127.0.0.1（cwd=/tmp/m6ix-5830/csrf）
```
