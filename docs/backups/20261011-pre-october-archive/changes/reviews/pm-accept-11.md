# PM 第十一轮验收报告（2026-09-28）

验收人：产品经理面板（第十一轮）。本轮约束：只验收、**不改任何生产代码与测试文件**；实验全部落在
`/tmp/mgw-accept-11-pm/`（含一份排除 `data/` 与 `.git/` 的仓库副本 `/tmp/mgw-accept-11-pm/repo/`）。

开工 `git status --porcelain` = **82 行**；收工 = **82 行**（同一集合，见 ⑥）。
`data/` 全程只读：`find data -newermt "2026-09-28 17:10" -type f` → **0 个文件**。
**:8300 未监听**（`lsof -nP -iTCP:8300 -sTCP:LISTEN` 空、`curl /admin/api/overview` → `http_code=000`）
→ **本轮未复跑运行态**，一切界面/端点结论来自 TestClient 真装配 + 三道门，不宣称验过活实例。

---

## ① 结论：**不通过（4 条阻塞）**

三门数字本轮全部复跑通过（pytest 705 / 前端门 81·可红 100/100 / 后端出口 12/12），
**上一轮我判"通过"的那三件事没有回退**（两列同一瞬间、四故障互不混淆、熔断手动出口真实），
**第十轮的 N-2（缺键/null 抹掉内存熔断）确实修好了**（实测 6 种坏法下常驻进程全部 `active=True/1800s`）。

但本轮打到 4 条**产品承诺面**的真缺料：

| # | 一句话 | 性质 |
|---|---|---|
| B-11-1 | 「添加/更换资源映射」被三个用户出口指到**「资源池设置」页**，而那一页根本没有添加映射的控件、且它自己写着"到「模型资源」页"——指路当场矛盾 | 当前就错，用户照做撞墙 |
| B-11-2 | PRD Q25-⑩ 与 tech-design §20-17 **明令写进文档**的「先登录工具，再配网关」在任何用户出口都不存在 | 需求字面未交付 |
| B-11-3 | 第十轮 ix 的九条"藏文案"阻塞，S-35 宣称"改成按属性语义解析"后**封住了**——实测仍有 **8 种隐藏写法让门 81/81 全绿**，其中包括本项目 `base.css:108` 自己定义的 `.hidden{display:none!important}` | 「用户可见」的担保不成立（结论可信度） |
| B-11-4 | 已发布的 README 三处失真：证据文件指向仓库里**不存在**的 `docs/…`（`docs/` 被 gitignore、`git ls-files docs` = 0）、"462/462 测试通过"（实测 705）、"当前版本 v0.2.0"（`mgw --version` = 0.1.0） | 门面自身违反铁律 2 |

S-34（坏值统一按"文件不可信"）方向对、**但落地范围比账本写的小**，且"告警"送进了本项目自己判定为
"用户看不见"的通道 → 见 ④ N-1（上一轮同条编号，仍开放）。

---

## ② 三门独立复跑输出（逐字，本面板这一跑）

### 门 1 · pytest

```
$ cd /Users/w/Desktop/Model-Gateway && .venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest -p no:warnings
........................................................................ [ 10%]
........................................................................ [ 20%]
........................................................................ [ 30%]
........................................................................ [ 40%]
........................................................................ [ 51%]
........................................................................ [ 61%]
........................................................................ [ 71%]
........................................................................ [ 81%]
........................................................................ [ 91%]
.........................................................                [100%]
705 passed in 135.67s (0:02:15)
```

**705 passed**，与账本"补做后的机械门"一节写的 705 持平。

### 门 2 · 后端用户可见出口（含变异自证）

```
$ .venv/bin/python scripts/ui_verify_v2_visible.py --mutation       # 退出码 0
[后端出口]
  ✓ overview 含四类告警  ['model_unservable', 'model_without_resource', 'param_shadowed', 'resource_without_model']
  ✓ 四类措辞互不相同  4 条
  ✓ ① 零映射告警提到 503
  ✓ ③ 不可服务告警指名模型
  ✓ ④ 覆盖告警说清生效序
  ✓ /v1/models 不含零映射模型  ['ok-model', 'shadow-model']
  ✓ /v1/models 不含不可服务模型
  ✓ /v1/models 保留可服务模型
  ✓ status 含 ops_failed_unread  = 0
  ✓ 熔断回写命中 1 条资源  benched=1
  ✓ overview 资源项带 last_error  'ZCode 风控熔断（30min，全局），至 17:44'
  ✓ overview 资源项带冷却剩余  1799999ms
...
[变异自证] 基线 81 条全绿 → 施加 100 个源码变异
可红 100/100；每条断言都有对应变异

后端出口实测 12 项，通过 12 项，失败 0 项
```

全文留存 `/tmp/mgw-accept-11-pm/gate2-backend-verbatim.txt`（135 行）。

### 门 3 · 前端门（Node）

```
$ node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json            # 退出码 0
实测 81 项，通过 81 项，失败 0 项

$ node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json --mutation  # 退出码 0
[变异自证] 基线 81 条全绿 → 施加 100 个源码变异
可红 100/100；每条断言都有对应变异
```

第十轮我读到的是"实测 79 / 可红 87/87"，本轮是 **81 / 100** —— 判据与变异都真的长了一批，
`Z1`（可见性语义自测）与 `Z2`（沙箱不含 Node 全局）两条新判据本轮实跑为 ✓。

> ⚠️ **本轮踩到一次"假红"，根因是门自己的输出路径是全局固定的**：
> `scripts/ui_verify_v2_visible.py:28` 写死 `OUT = Path("/tmp/mg-v2-visible")`。
> 我在 17:14 用它生成 fixture，17:30 该文件被**同机并发会话**重写（`ls -la` mtime=17:30），
> 内容里 `调用将返回 503` 变成 `调用将返回 5xx`，于是 `node … overview.json` 当场
> `✗ A2 文案透传：含 503 / 实测 81 项，通过 80 项，失败 1 项`。
> 全仓（含所有 /tmp 副本）grep 不到 `调用将返回 5xx` 的源码 —— 即那是**某次变异中间态被留在了共享盘上**。
> 我用副本重跑门 2 重新生成干净 fixture 后 81/81 复原（`/tmp/mgw-accept-11-pm/gate2-copy.txt`）。
> 这不是产品缺陷，但它说明：**两道门的输入/输出跨进程共享且无版本隔离**，任何并行验收都会互相污染。

---

## ③ 阻塞项

### B-11-1 · 指路页名分叉：「资源池设置」页并不能添加/更换映射（三个用户出口同时说错话）

**现象**
总览横幅、`mgw setup` 输出、总览状态徽章 title 三处，把"为模型添加/更换资源映射"指到
**「资源池设置」页**；该页**没有**添加映射的控件，它自己的页面文案写着到「模型资源」页。

**复现一（CLI 真实输出，/tmp 配置，零真实上游调用）**

```
$ MG_CONFIG=/tmp/mgw-accept-11-pm/data/config.yaml \
  python -m model_gateway.cli setup workbuddy-ai --dry-run
目标目录：/Users/w/.workbuddy-ai
    （来源：产品标识 workbuddy-ai → dataFolderName .workbuddy-ai）
可服务模型判定依据：本地配置 · 原因：网关未运行（连接被拒） —— 感知不到资源失效等运行态
已跳过 2 个不可服务的系统模型：
    · 1 个未配置任何资源映射（model-empty-pool）—— 到「资源池设置」页为该模型添加资源映射
    · 1 个映射的资源均未启用（model-all-disabled）—— 到「模型资源」页打开对应资源的启用开关
```

**复现二（同一份配置，真 `create_app` + TestClient 的横幅原文）**

```
$ /Users/w/Desktop/Model-Gateway/.venv/bin/python /tmp/mgw-accept-11-pm/check_cross_exit2.py
=== 出口 A：总览横幅（warnings 原文） ===
  [model_without_resource] 1 个系统模型未配置任何资源，已从 /v1/models 与 mgw setup 隐藏（调用将返回 503） —— 到「资源池设置」页选中该模型、在资源池里添加资源映射（model-empty-pool）
  [model_unservable] 1 个已启用模型的资源映射全部不可用（已停用或凭据失效），… 或到「资源池设置」页更换映射（model-all-disabled）
```

**复现三（目标页的真实控件 —— 该页做不到它被指路做的事）**

`model_gateway/web/static/js/pages/models.js` 里与映射相关的控件只有三个：
```
351:  <select class="in mono" data-effort="${i}" …>     # 资源级推理默认
356:  <button class="btn btn-sm" data-up="${i}" …>↑</button>   # 优先级
358:  <button class="icon-btn sm danger" data-rmres="${i}" title="移除该映射">
```
全文件 `grep -n "添加资源\|新增资源\|添加映射"` → **只命中一行，且它是把用户往外推的提示**：
```
361:  }).join("") || `<p class="form-hint" …>无资源（调用将无可用资源 503）——到「模型资源」页编辑资源添加映射</p>`;
297:  <p class="form-hint" …>新增 / 调整映射：在「模型资源」页编辑对应资源…</p>
```
真正能添加映射的控件在**另一页**：`web/static/js/pages/resources.js:274` `id="rv-addmap"`（＋ 添加模型）。

**与需求真相的冲突**
- `docs/specs/design-spec.md:405`（§19-19 资源导向映射 Q19-②）：「**系统模型页无「新建系统模型 / 添加资源」入口（映射创建仅在资源侧）**」
- `docs/specs/design-spec.md:251`：「无资源模型：资源池空态提示「无资源（调用将无可用资源 503）——到『**模型资源**』页编辑资源添加映射」」
- 代码里自己的判据也承认指路要对页：`model_gateway/main.py:319-321`「🔴 指路必须指对页面（验收 IX-M-3）」
- 受影响的用户可见出口（四处）：`main.py:296`、`main.py:324`、`cli_setup.py` `_CAUSE_HINTS["no_mapping"]`、`dashboard.js:135`
  ；错误前提写在 `core/resources.py:224`（`ROUTE_POOL_PAGE = "「资源池设置」页"  # 模型 ↔ 资源的映射、档位、优先级`）

**为什么是阻塞而不是洁癖**：这是用户**看得见的两句话互相打脸**——横幅说"去 A 页加映射"，
用户到了 A 页，A 页原地写着"去 B 页加映射"。属于本任务判据里"同一件事在不同出口必须同一句话"的正面违反，
且第一跳是错的（浪费一次跳转 + 让用户怀疑告警不可信）。PRD Q28-②「不允许只过滤不解释」只满足了一半：
解释了，但把用户支去了一个做不了这件事的页面。

**门为什么没抓到**：`scripts/verify_v2_frontend.mjs` 的 J 族（:474 起）只核对「文案里出现的页名在侧栏存在」，
从不核对"那一页有没有这个控件"；更糟的是 `:909` 有一条变异**把错误措辞锁成契约**
（`from: "到「资源池设置」页更换映射", to: "到「模型资源」页更换 Key"`）——将来按本报告改正指路时，
这条变异会因锚点找不到而施加失败，需要连变异一起改。

**修法建议**
1. 改四处文案：`添加/更换映射` → 指「模型资源」页（该页 `#rv-addmap` 才是入口）；
   并修正 `core/resources.py:224` 的注释前提。
2. 判据升级（防再犯）：给 J 族加一条"页名 ↔ 该页控件锚点"交叉核对——指路句里的动词
   （添加映射 / 更换 Key / 启用开关 / 清推理默认）必须在被指页面的源码里存在对应控件锚点 id 或 `data-*`，
   否则判红；同时替换 `:909` 那条锁死错误页名的变异。

---

### B-11-2 · PRD Q25-⑩ 明令的「先登录工具，再配网关」在任何用户出口都不存在

**需求原文**
- `docs/specs/prd.md:599`（Q25-⑩）：「不做工具的登录态管理——`mgw setup` 只能写配置，**不能替用户登录**；
   **文档须写明「先登录工具，再配网关」**」，依据是实测 `08` §5 O1（工具无登录态时**完全不发模型请求**、进程空转）。
- `docs/specs/tech-design.md:1435`（§20 不做清单第 17 条）：「**不代用户登录工具**（PRD Q25-⑩）；
   文档须写"**先登录工具，再配网关**"」。

**实测（交付面零命中）**

```
$ grep -rln "先登录" --exclude-dir=.git --exclude-dir=__pycache__ --exclude-dir=.venv .
./docs/research/09-设计定稿-我定的方案.md
./docs/research/08-WorkBuddy首次接入实测与工具侧契约.md
./docs/specs/prd.md
./docs/specs/tech-design.md
./docs/specs/reviews/PM-review.md

$ grep -n "登录" README.zh-CN.md
99:mgw zcode import <凭据.json>   # 导入本机已登录账号（设备 ID 冲突则拒绝并给选项）
155:- **单用户。** 无注册无登录，管理界面…免鉴权——请只在自己的设备上运行…
$ grep -n -i "log in|login|signed in|session" README.md   → 只有 "…kills the whole session"（讲故障切换，与此无关）
$ grep -n "登录" model_gateway/cli_setup.py model_gateway/setup_tools.py → 0 命中
```

即：**这条承诺只写在需求与技术方案里，一处都没交付到用户会读的地方**（README 双语、`mgw setup` 输出、
`mgw setup --help`、界面 API 接入页全都没有）。用户按 README 跑完 `mgw setup workbuddy` 后，
若工具没登录，得到的是"进程空转、一个请求都不发"，而他读过的每一页都没告诉他先登录 ——
这正是 Q25-⑩ 立这条的目的（实测踩过的坑，见 `08` §5 O1）。

**为什么阻塞**：这是 PRD 用"须写明"字面下达的**交付项**，不是风格问题；而且它守护的是一个
"看起来一切正常、实际零调用"的静默失败，属 §12.1 要消灭的那类无报错失败。

**修法建议**（成本极低）：`README.md` / `README.zh-CN.md` 的 CLI 段各加一行；
`mgw setup` 在打印目标目录后追加一句
「⚠ 本命令只写配置、不代你登录工具：**先登录工具，再配网关**（工具无登录态时不会发起任何模型请求）」。
建议同时进 `mgw setup --help` 的 epilog（`claim` 已有 epilog 先例，`setup`/`probe` 现在完全没有 epilog）。

---

### B-11-3 · 门对「用户可见」的担保不成立：8 种隐藏写法下 81/81 全绿

**账本的说法（第十轮补做）**：`E2E-20260928-round5-fixes.md:355` 称 S-35 把 `visibleText()`
「**改成按属性语义判定**」，并列举已被识别的 `opacity:0` / `height:0;overflow:hidden` /
`left:-9999px` / `visibility:collapse` / `<template>` / `<noscript>` / 裸 `aria-hidden` / 大写 `STYLE="DISPLAY: NONE"`。

**代码实际（`scripts/verify_v2_frontend.mjs:686-702`）**：`isInvisible()` 只读
`hidden` / `aria-hidden` / **元素自己内联 `style` 里的 6 条正则**
（`display:none`、`visibility:hidden|collapse`、`opacity:0`（仅字面 0）、`height:0(+overflow:hidden)`、
`left:-NNNpx`、`transform:scale(0)`）。**它不解析样式表、不解析 class、不看 `@media`。**

**实测（对 /tmp 副本施加，仓库零改动；`/tmp/mgw-accept-11-pm/escape_probe.py`）**

```
=== 基线（未改动）===            门 exit=0 实测 81 项，通过 81 项，失败 0 项
  🔴 逃逸成功（门全绿）：E1  CSS 类把整条横幅藏掉 .alert-warn{display:none}
  🔴 逃逸成功（门全绿）：E2  正文 font-size:0（内联）
  🔴 逃逸成功（门全绿）：E3  正文 COLOR:TRANSPARENT（大写属性名+大写值）
  🔴 逃逸成功（门全绿）：E4  正文 max-height:0;overflow:hidden（ix 测的是 height:0）
  ✅ 判红：E5  正文 visibility:hidden          → ✗ K1 / ✗ K9
  ✅ 判红：E6  正文搬进 <noscript>              → ✗ K1 / ✗ K9
  🔴 逃逸成功（门全绿）：E7  横幅包进 class="hidden"（本项目 base.css:108 定义了 .hidden{display:none!important}）
  🔴 逃逸成功（门全绿）：E8  用 CSS 只藏「最近错误」那一列（.tbl td.ellip:last-of-type{visibility:hidden}）
  🔴 逃逸成功（门全绿）：E9  @media 里把横幅藏掉（响应式写法）
  🔴 逃逸成功（门全绿）：E10 clip-path:inset(50%)（DOM 在、屏幕上一个像素都没有）
  🔴 逃逸成功（门全绿）：E11 正文前插零宽字符 —— ⚠️ 这条**不算逃逸**：文本仍然可见，门绿是对的，列在此处只为完整
=== 复原确认 ===                  门 exit=0 实测 81 项，通过 81 项，失败 0 项
```

**有效逃逸 8 条**（E1/E2/E3/E4/E7/E8/E9/E10）。其中 **E7 最重**：
`model_gateway/web/static/css/base.css:108` 就是 `.hidden { display: none !important; }` ——
"用 class 隐藏"不是刁钻写法，而是**本项目自带的、最地道的隐藏方式**；
而 S-35 为了防止 `class="… hidden"` 误判，专门把这一型**放成了不算隐藏**
（账本 `:355` 原话「`class="… hidden"` 不再误判」）。方向反了：对本项目而言它是真阳性。
E8 说明同一族问题的另一半：「最近错误」列是 §17 熔断的**唯一**用户可见出口
（`dashboard.js:86-88` 自己写的），一条样式表规则就能把它抹掉而门毫无反应。

**为什么 PM 面板判它阻塞**：本轮验收结论里有大量"已实测用户可见"的表述
（横幅/徽章/列/红点"可见"）。若"可见"的担保可以被子类名或一行 CSS 绕过，
`81 项全绿 + 可红 100/100` 就**不能**支撑那句"用户看得见"。这与第十轮 ix 抓到 B10 时的性质相同，
而账本对本轮的表述是"根修（白名单 → 语义模型）"——**实测说明它仍然是白名单，只是更长**。

**主责面板是 ix**，但结论归属三门共用，故 PM 侧一并登记为阻塞。

**修法建议**
1. 承认"内联 style + 两个布尔属性"不等于可见性：把**样式表里与页面 DOM 里真实存在的
   display:none / visibility:hidden / font-size:0 / color:transparent / clip-path 规则**纳入判定
   ——最小实现：扫 `css/*.css` 里的 `.X{…display:none…}` 类名集合，命中元素 `class` 即判隐藏；
   `class="hidden"` 特例按本项目 CSS 判真（并删掉"不再误判"那条反向白名单）。
2. 补 E1–E10 这批"坏改动的自然写法"型变异进门（照第十轮自己的设计原则：新增判据必须同时新增变异）。
3. 门自身的输出路径 `/tmp/mg-v2-visible` 改为按仓库根哈希/进程唯一目录，避免并发验收互相污染（见 ② 末尾）。

---

### B-11-4 · 已发布 README 的三处事实失真（门面违反铁律 2）

```
README.md:167 / README.zh-CN.md:161：
  "Current version: **v0.2.0** (tech-design v2.0) — 462/462 tests passing; …
   … explicitly listed as **not yet verified** (see `docs/changes/e2e-records/E2E-20260926-v2-implementation.md`)."

实测：
  $ grep -n "__version__" model_gateway/__init__.py      → __version__ = "0.1.0"
  $ grep -n "^version" pyproject.toml                     → version = "0.1.0"
  $ python -m model_gateway.cli --version                 → mgw 0.1.0
  $ .venv/bin/python -m pytest -q …                       → 705 passed        （README 说 462/462）
  $ git ls-files docs | wc -l                             → 0                  （docs 全目录未入库）
  $ grep -n "docs/" .gitignore                            → 17:docs/
  $ git log --oneline -1 之前的提交                        → "Remove internal spec documents from repository"
```

1. **版本号分叉**：README 说 v0.2.0，包与 `mgw --version` 都是 0.1.0（HEAD 提交也叫 "Initial release … v0.1.0"）。
   用户在 README 看到的版本与自己敲出来的命令回显不一致。
2. **测试数陈旧**：462/462 已被实测 705 取代（第十/十一轮各 +6/+2）。这不是"虚报通过"（数字只会偏小），
   但它是 README 里**唯一的量化证据**，且已经不对。
3. **证据指针悬空**：README 让读者"见 `docs/changes/e2e-records/…`"，而 `docs/` 被 gitignore、
   仓库里 0 个文件 —— 克隆下来的人打不开这个路径。README.md:161 与 README.zh-CN.md:161 都引用它
   （zh 版那句还漏了一个右括号：「…未验证**（见 …md。」）。

**为什么阻塞**：README 是这个开源门面对外**唯一**的证据入口；"无证据不得宣称完成"是本项目铁律 2，
而现在的证据链接不可达、量化数字与版本各自为真。**修法**（一次性）：删掉或改写为"随仓库附带"的真实链接
（例如指向 `tests/` + 一条 `pytest` 命令），版本与测试数改成与 `__version__`/本轮输出一致，
并在 zh 版补回括号。若刻意不想公开账本，就应把那句改成不含路径的说法，而不是留一个 404 指路。

---

## ④ 非阻塞登记

**N-1（上一轮同编号，本轮**半收口**，仍开放）"文件不可信则保持内存态**并告警**"：告警只覆盖 2/7 种坏法，且送进用户看不见的通道。**

实测（`/tmp/mgw-accept-11-pm/check_s34_badvalues.py`，同进程常驻 + 新进程两态，逐型抓日志）：

| 坏法 | 常驻（内存正熔） | 全新进程 | 新进程日志 |
|---|---|---|---|
| `until_ms` = 字符串 `"abc"` | `active=True left=1800s` ✓ | `active=False left=0s` | **0 条（零痕迹）** |
| `until_ms = null` | `active=True left=1800s` ✓ | `active=False` | 2 条 WARNING ✓ |
| 丢掉 `until_ms` 键 | `active=True left=1800s` ✓ | `active=False` | 2 条 WARNING ✓ |
| `until_ms = NaN` | `active=True left=1800s` ✓ | `active=False` | **0 条（零痕迹）** |
| `until_ms = 现在+30天` | `active=True left=1800s` ✓ | `active=False` | 2 条 WARNING ✓ |
| 顶层不是对象 `[1,2,3]` | `active=True left=1800s` ✓ | `active=False` | **0 条（零痕迹）** |
| 截断 JSON `{"until_ms": 123` | —— | `active=False` | **0 条（零痕迹）** |
| `chmod 000` 读不动 | —— | `active=False` | **0 条（零痕迹）** |

代码根因：`quota.py:356-359` 的 `logger.warning` 只挂在"缺键/null"分支，`:369-371` 只挂在">24h"分支；
`:362-363`（非数字）与 `:364-365`（NaN/Inf）**直接 `return None` 不告警**；
`_load()` 的 `:464-466`（OSError/坏 JSON）与 `:467-468`（顶层非 dict）也不告警。
账本 `E2E-20260928-round5-fixes.md:354` 写的是「缺键/`null`/非数字/非有限四类**统一返回 `None`** 并 `logger.warning`」
——**四类里只有两类真告警**，这是第十轮 eng R-1 刚批评过的"说过头"在同一处的重现（铁律 2）。

**用户侧到底看到什么**（这条比日志条数更要紧）：
- 界面**没有任何出口**：实测重启（`check_cross_exit2.py` (e) 段）
  「熔断文件 until_ms=字符串 → 新进程启动日志 0 条熔断相关 WARNING；
  overview 的 last_error 列 = []；横幅 kinds = ['model_without_resource','model_unservable','param_shadowed']，
  没有任何一条说明"状态文件读不出来"」。
- 而本项目**自己三处**写明"只写日志 = 用户看不见"：
  `main.py:478-481`「配置告警**双通道**……**单写日志是不够的**：启动脚本正常路径是 nohup 后台拉起 + 自动关窗，用户看不到日志」、
  `dashboard.js:61-63`「🔴 为什么走接口而非只写日志：启动脚本正常路径是 nohup 后台 + **自动关窗**，告警写进日志 = 用户看不见」、
  `启动网关.command:71-79` 实装的正是 `nohup … >> data/gateway.log` 且自动关窗。
- `grep -rn "gateway.log" model_gateway/ scripts/` → **零命中**：没有任何界面/端点读它。
  所以 S-34 的"告警"落到的通道，恰好是本项目判定为不可见的那一个。

判非阻塞的理由与上一轮相同（`_save()` 走 `os.replace` 原子写、生产自身不产坏文件、
PRD 没有承诺损坏处理语义、手动出口仍真），**但必须登记**：风险面是"重启即在风控观察期内提前放行且无人知道"。
建议：`_load()` 顶部统一一条 WARNING（点名 `self.path` + "熔断凭据读不出来，本轮按无熔断执行"），
并把 `quota.py:430` 类表格的错误口径一起改（见 N-3）；要做透就给 overview 加一条既有 kind 的告警复用横幅（不新增页面/端点）。

**N-2（新）`mgw zcode claim --help` 的 epilog 被 argparse 折成一段，且 markdown 星号原样打进终端。**
实测输出：
```
退出码：0 = 全部正常；1 = 有失败（需关注）；2 = 无账号参与； 3 = **全局风控熔断中，本轮未对上游发起领取**（可能同屏列出
未发起即失败的账号，结论仍以 3 为准：本轮没真正跑过） ⚠️ 3 与 `mgw setup` 的 3（写盘失败）同码不同义 —— 按子命令读退出码。
```
`cli.py:62-65` 里的 `\n` 与缩进被 argparse 默认 formatter 折叠（未用 `RawDescriptionHelpFormatter`），
"3 与 setup 同码不同义"这条本该独立醒目的一句被并进退出码列表同一行。语义齐全（0/1/2/3 + 同码不同义都在，
Q28-⑥⑧ 因此判"已交付"），但排版意图丢了。上一轮 N-6（星号）也仍未改。**修法**：`zc_claim` 用
`formatter_class=argparse.RawDescriptionHelpFormatter`，并把 `**…**` 去掉。
（附带：`mgw setup --help` / `mgw probe --help` **完全没有 epilog** —— setup 的 `3 = 写盘失败`
只在别处文案里出现，自己的 --help 不说；属同一族，建议一起补。）

**N-3（旧口径·仍开放，本轮定位更准）** 与上一轮同条，但**现在是两处**：
`upstream/zcode/quota.py:430` 类能力表仍写「每次判定前**按 mtime 回读文件**」、
`:518` 行内注释 `# 跨进程可见：按 mtime 回读`；而 `:450` 的实现与判据是
「每次判定**真读一遍文件**，**不用 mtime 去重**」（S-26⑤）。`grep -n mtime` 全仓仅这几处 + `runner.py:149` 的合法用法。
后来人照表施工把 mtime 缓存加回去 = 跨进程凭据再次变钝。**本轮未修。**

**N-4（旧口径·仍开放）** `ops/builtin/zcode_claim.py:114` 仍写「`enter()` 会把它规范成 §17 要求的 `…，至 HH:MM`」，
而实现是 `enter()` **剥尾存裸原因**（`quota.py:513` + `:506-509` 的注释、`apply_to_resource` `:587`）。
行为对、注释误导。**本轮未修。**

**N-5（规格面缺口·仍开放）** 两列契约仍只活在门与账本里：
`docs/specs/design-spec.md:192` 只列了列名（…/ 冷却剩余 / 最近错误），
`grep -c "读时\|至 HH:MM\|明日" design-spec.md` → **0**；
`grep -c "冷却剩余\|最近错误\|读时\|明日" frontend-spec.md` → **0**。
**本轮未修**。（本轮新增实测支撑：两列同一句话这件事确实成立，见 ⑤，所以缺的是"把它写成规格"，不是"修行为"。）

**N-6（新·小）`--config` 的 --help 文案与实际解析不一致。**
`cli.py:34/41` 写「配置文件路径（缺省 data/config.yaml）」，而 `core/paths.py` 的口径是
`MG_CONFIG` 环境变量优先、否则**项目根**的 `data/config.yaml`（与 cwd 无关）。
实测：cwd 在 `/tmp/mgw-accept-11-pm`、不设 `MG_CONFIG` 时，`setup --dry-run` 仍读到了仓库根的
`data/config.yaml`（cwd 无关性正确），但帮助文本读起来像"当前目录下的 data/"。
`paths.py` 顶部注释正是为了消灭这个误读而写的。建议改为「缺省：`MG_CONFIG` 或 `<项目根>/data/config.yaml`」。

**N-7（新·小）红点指路是相对路径，CLI 同类指路是绝对路径。**
`web/static/index.html:109` title 与 `main.js:120` toast 都写 `data/usage/ops-results-*.jsonl`（相对字面量），
而 `cli_zcode.py:244` 打的是 `default_usage_dir()` 的绝对路径（本轮实测
`/private/tmp/mgw-accept-11-pm/data/usage/ops-results-20260928.jsonl`）。
默认安装时两者重合；用户把配置放别处（`MG_CONFIG`）时界面那句会指偏。非阻塞，建议界面下发绝对路径或说"数据目录/usage/"。

**N-8（上一轮 N-7 维持）** 24h 上限之内的手改值仍能把熔断"钉"住（实测 `+23h → left=82800s`、
界面老实显示「至 明日 16:17」），删除文件仍能出口 → 纯加固建议（把文件来源上限收到 `COOLDOWN_MS + 余量`）。

**N-9（上一轮 N-8 维持）** 热重载换下的适配器不 `aclose`：待用户定夺，不属本轮范围。

**N-10（新·工程环境）** 门的共享输出 `/tmp/mg-v2-visible`（`ui_verify_v2_visible.py:28`）被同机并发会话
在 17:30 覆盖为变异中间态，直接制造了一次假红（见 ② 末）。修法见 B-11-3 建议 3。

**§20 不做清单本轮再对表**：S-34/S-35/R-3 的新增物全部落在 `quota.py`（读盘分支）、
`scripts/verify_v2_frontend.mjs`（门自身）与 `scripts/`；无新页面、无新端点（`@router.get` 仍 9 个）、
无新轮询、无第二本账、无新录入界面。未越界。

---

## ⑤ 上一轮遗留项复核（逐条：收口 / 仍开放 + 本轮证据）

| 上一轮（第十轮）我登记的 | 本轮判定 | 证据 |
|---|---|---|
| **N-1** 新进程读不可信文件 = 零痕迹 | **半收口·仍开放**（8 型里 3 型有 WARNING；且界面零出口） | ④ N-1 的实测矩阵 + `check_cross_exit2.py` (e) 段 |
| **N-2** 缺键/null 抹掉内存熔断（fail-open） | **已收口** ✓ | 常驻进程在 6 种坏法下全部 `active=True left=1800s`（上一轮 B/C 两型是 `active=False`） |
| **N-3** `mtime 回读` 注释与行为相反 | **仍开放**（且是两处：`:430` 与 `:518`） | ④ N-3 |
| **N-4** `enter()` 规范成 `…至 HH:MM` 的误导注释 | **仍开放** | ④ N-4 |
| **N-5** 两列契约未进 design-spec / frontend-spec | **仍开放**（两文件对关键词零命中） | ④ N-5 |
| **N-6** `--help` 里 markdown 星号 | **仍开放**（并新增：epilog 被折叠） | ④ N-2 |
| **N-7** 24h 上限宽度 | **维持原判**（非阻塞加固） | ④ N-8 |
| **N-8** 适配器 `aclose` | **维持原判**（待用户定夺） | ④ N-9 |
| 第九/十轮的**行为结论**：两列同一瞬间 / 一份口径 | **未回退** ✓ | `check_cross_exit2.py` (c) 段：CLI ⚠ 与界面「最近错误」列**同一行同一句话** `'ZCode 风控熔断（30min，全局），至 17:55'` |
| Q28-⑥④ 冷却只延长不缩短 | **未回退** ✓ | 同一行 before=1799995ms → after=1799994ms（1ms 自然流逝），`last_error` 未被"429 短退避"改写 |
| Q28-⑥⑥ 熔断手动出口（删文件） | **未回退** ✓ | 7 种坏法 + 正常文件下删除后一律 `active=False reason=''` |
| Q28-⑥⑦ 回写一个都没匹配上须留痕 | **交付** ✓ | `sync_circuit()` 实测一条：`WARNING [熔断对齐] 全局风控仍在生效（…，至 17:55），但没有资源的账号备注对上任何 ZCode 账号 —— 界面上看不到熔断痕迹，请到「模型资源」页把对应资源的账号备注填成该 ZCode 账号名`（指路页名这次是对的：账号备注确实在资源页编辑）；注意其界面侧出口按 `main.py:96` 明示"二期补" |
| Q28-⑥⑧ 退出码 3 优先于 1 + 进 --help/README | **交付** ✓ | 实测 `mgw zcode claim` 在熔断中同屏有 2 条失败仍 `EXIT=3`，并打印状态文件绝对路径；`--help` epilog 与 `README.zh-CN.md:110-113` 三处口径一致 |
| Q28-② `/v1/models` 与 setup 只下发可服务模型 + 不允许只过滤不解释 | **交付**（但指路见 B-11-1） | `GET /v1/models → 200 ids=['model-ok']`（配置里三个启用模型只放出可服务的那个）；横幅逐条给数量/名字/成因 |
| Q25-⑨ `mgw setup` 目标目录按 dataFolderName 解析 | **交付** ✓ | 实跑打印「目标目录：/Users/w/.workbuddy-ai（来源：产品标识 workbuddy-ai → dataFolderName .workbuddy-ai）」，**只用 --dry-run，未写用户工具目录** |
| Q28-⑤ `mgw setup` 三态可分辨 | **两态实测 + 一态读码** | 未运行＝「网关未运行（连接被拒）」；401＝我在 8399 起假服务实测「网关在运行但拒绝了接入密钥（401：密钥已停用或删除）」；超时＝`local_admin.py:54` 已登记「网关无响应（超时）」（未实测，见 ⑥ 未验证） |
| ix 第十轮 9 条阻塞（B10-1a…B10-9） | **在门内** ✓（100/100 可红清单里逐条点名），但**担保强度见 B-11-3** | 门 2/门 3 的变异清单原文可见 B10-1a/1b/1c/2/3/4/5/6/7/8/9 与 R-3 |
| eng 第十轮 R-3（Node 全局泄漏） | **交付** ✓ | `Z2 执行环境不含 Node 专有全局` 实跑为 ✓；另有对应变异「沙箱泄漏 Node 全局」可红 |
| eng 第十轮其余非阻塞（探针写失败无自愈 / `.write-probe.lock` 0644 / `data/ops-locks` 保留期 / 第三方锁删除零日志） | **本轮未复核**（账本 `:378-379` 记为"登记未修，等第十一轮定取舍"） | 见 ⑥ 第 7 条 —— 这几条我本轮没有独立实测，不能判收口 |

---

## ⑥ 未验证清单（如实）

1. **运行态**：`:8300` 未监听（开工即如此），按约束**未重启、未新起、未 kill** → 本轮**未复跑运行态**；
   红点/徽章/横幅的真实浏览器呈现全部只到"TestClient + 门"这一层。
2. **真实上游调用**：一次都没发（配置里只有 `https://example.invalid/v1`；熔断中的 claim 实测因"凭据缺失"
   在发起前就被拒 → 零网络）。`mgw probe` 因此**未执行**。
3. **`mgw setup` 的写盘路径与退出码 3（写盘失败）**：未实测 —— 真写会改用户 `~/.workbuddy-ai`，越界；只跑了 `--dry-run`。
4. **超时态**（Q28-⑤ 三态之一）：只读码确认 `local_admin.py:54` 有登记，未起假慢服务实测。
5. **B-11-3 的 CSS 逃逸**只验到"门判不判红"这一层，未驱动真实浏览器渲染截图证明像素不可见
   （判据依据是 `base.css:108` 的 `display:none !important` 与 CSS 级联常识）。
6. **N-1 的坏文件在真实用户机上由谁产生**：无遥测，仍只证明"若发生则界面零痕迹"。
7. **eng 第十轮其余非阻塞项**、**多进程并发争用**、**自然午夜生产路径**、**Windows 侧文件读不动**：
   本轮未做，维持上一轮"未验证"。
8. **并行会话干扰**：验收期间同机另有会话在动本项目（`/private/tmp/mgw-accept-11/`、`/tmp/mgw-accept-11-*` 等
   多份副本，以及 17:30 对共享 fixture 的覆盖；我还观察到主仓 `dashboard.js` 一度带着一段
   `.alert-warn{display:none}` 与 `class="hidden"` 包装、随后自行复原）。**这些改动不是我做的**：
   我对仓库本体只有读操作，写操作只发生在 `/tmp/mgw-accept-11-pm/`；`git status --porcelain` 行数
   开工/收工同为 82，`find data -newermt "2026-09-28 17:10" -type f` → 0。

---

## 收工自证

```
$ git status --porcelain | wc -l        → 82（与开工同一数字）
$ find data -newermt "2026-09-28 17:10" -type f | wc -l  → 0（用户数据目录只读）
$ ls -la docs/changes/reviews/pm-accept-11.md   → 本报告（新建）
```

本面板创建/改动的文件（**仓库内只有这一份报告，其余全在 /tmp**）：

- 新建 `/Users/w/Desktop/Model-Gateway/docs/changes/reviews/pm-accept-11.md`（本报告；`docs/` 已被 `.gitignore` 忽略）
- `/tmp/mgw-accept-11-pm/check_s34_badvalues.py` —— 坏值 × 常驻/新进程 × 日志矩阵 + 永不解除 + 手动出口
- `/tmp/mgw-accept-11-pm/check_cross_exit.py`、`check_cross_exit2.py`（+ `cross2.txt`）—— 跨出口一致性实测
- `/tmp/mgw-accept-11-pm/escape_probe.py`、`escape_probe.sh` —— 对副本的独立逃逸探测
- `/tmp/mgw-accept-11-pm/repo/` —— 仓库副本（rsync 排除 `data/`、`.git/`、`.venv/`、`__pycache__`），
  所有变异施加后均已复原，收尾复跑 81/81
- `/tmp/mgw-accept-11-pm/{gate2-backend-verbatim.txt,gate2-copy.txt,gate3-node-plain.txt,gate3-node-mutation.txt}` —— 三门逐字输出
- `/tmp/mgw-accept-11-pm/data/{config.yaml,usage/…}`、`accounts/`、`circuit.json`、`fake401.py` —— 临时配置与假状态

**生产代码与测试文件：零改动。**
