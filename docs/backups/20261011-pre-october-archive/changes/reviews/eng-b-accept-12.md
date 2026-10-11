# 验收面板 B（第十二轮）· 资深后端工程师 —— 机械门自身可信度与测试基建

验收对象：第十一轮 eng-B 四条阻塞的补做（账本 `docs/changes/e2e-records/E2E-20260928-round5-fixes.md` 的 S-42 / S-43 / S-44 / S-45）
验收方式：**只读仓库**，全部变异实验在 `/tmp/mgw-accept-12-engB/*` 副本内进行
开工 `git status --porcelain | wc -l` = **85**（其间随并行面板波动，非本面板改动）

---

## ① 结论

**不通过（新阻塞 1 条 S-52；四处补做本身**判定为真做**，逐条有红证/绿证）**。

- B11-1（S-42）**通过**：推定分支实测绝迹。六类"子进程异常"变异（语法崩 / stdout 70MB / 1MB 噪声 / JSON 后打人读行 / JSON 同行尾垃圾 / 合法 JSON 但退出码 3）**全部记 BAD**（`✗ … ← 子进程 …，无可判读输出`），`可红 0/5`、`EXIT=1`，无一例白拿 ✓。A12 变异经子进程 `--json` **真读到 `A12,Z3` 双红**（`RED: A12,Z3`）。
- B11-3（S-43）**部分通过**：`process` / `Buffer` 写进 `BROWSER_GLOBALS` → Z2 立刻红（canary 真在做事）；**但 `setImmediate` 写进去 → 84 项全绿**（派生集可被静默缩小，见 §4 N1）。更严重的是本轮新阻塞 **S-52**：页面代码经门**自己注入的宿主函数 `esc`** 反查宿主 realm（`esc.constructor("return process")()`）真拿到 `process.env.HOME` 并把它写进门的 stdout，**Z2 ✓ / Z3 ✓ / 84 项全绿 / 变异自证 104/104** —— 详见 §3 ④。
- B11-2（S-44）**通过**：`core/cancel.py`、`core/errors.py`、`stats/events.py`、`config/schemas.py` 四个"上一轮在面外"的模块**逐个都红**；四符号同时种 → 一条消息里**四个全点名**；新建 `model_gateway/core/zzz_new.py` 放死符号 → **自动入面即红**。`wrap_httpx_error` 删除属实（全包 grep 只剩文档叙述，`openai_out.py:114-116` 是内联翻译）。
- B11-4（S-45）**通过（含一处能力边界）**：K10 对「表头改名」「两列同乘 10」「C==in_flight 不可判别」三种变异都红；对"生成器不再走生产函数但手写了可判别值"这种绕过**不红**（门只吃 JSON，无法知道值怎么来的）——见 §3.4。
- 另：Z3 **不是空过判据**（反向对照 `__nope__` → Z3 红 5 次；且把 `PAGE_THROWS.push` 掏空后，A12 变异被记 `✗ 未红：Z3`、`可红 103/104`、`EXIT=1` —— 掏空 Z3 会被变异自证抓住）。

判定依据（AGENTS.md 铁律 2/5 + 本面板任务书）：S-52 属"门的沙箱判据被结构性绕过且产出全绿"，与 S-43 同一病根（测的是**空上下文里没有什么**，不是**页面能拿到什么**），必须在下一轮翻案。

---

## ② 三门复跑（逐字抄自本面板终端）

```
=========== [1] pytest ===========
715 passed in 153.73s (0:02:33)
PYTEST_EXIT=0
=========== [2] ui_verify_v2_visible.py（MGW_V2_VISIBLE_DIR 固定到本面板私有目录）===========
实测 84 项，通过 84 项，失败 0 项
后端出口实测 12 项，通过 12 项，失败 0 项
=========== [3] node verify_v2_frontend.mjs <overview.json> ===========
实测 84 项，通过 84 项，失败 0 项        EXIT=0
=========== [4] node verify_v2_frontend.mjs <overview.json> --mutation ===========
[变异自证] 基线 84 条全绿 → 施加 104 个源码变异
可红 104/104；每条断言都有对应变异        MUT_EXIT=0（104 行全部 ✓，无 BAD）
```

命令逐字为：`.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest12 -p no:warnings`；
`MGW_V2_VISIBLE_DIR=/tmp/mgw-accept-12-engB/fix .venv/bin/python scripts/ui_verify_v2_visible.py`；
`node scripts/verify_v2_frontend.mjs /tmp/mgw-accept-12-engB/fix/overview.json`（及 `--mutation`）。
与实现者自报**逐项一致**（84 / 104 / 12 / 715）。原始留档：`/tmp/mgw-accept-12-engB/{pytest-baseline,gate-normal,gate-mutation}.txt`。

载荷路径已按第十一轮 N1 隔离（`MGW_V2_VISIBLE_DIR` 或每次 `mkdtemp`），本面板用的是私有目录，未与并行面板互踩。

---

## ③ 四处补做的复验矩阵（含撤修复红证）

### 3.1 B11-1 · 全子进程判读 + `safePageFn` + Z3（`verify_v2_frontend.mjs:104-117, 1431-1497`）

| 实验（全在 /tmp 副本） | 门的产出 | 判定 |
|---|---|---|
| 正向：A12 变异（`const list = warnings;`）跑子进程 `--json` | `RED: A12,Z3`，`total checks: 84 errors: []`，`child_exit=0` | **真读到双红**，非推定 |
| 正向：整张变异表 | `可红 104/104`、104 行全 ✓、`MUT_EXIT=0` | 与自报一致 |
| 撤修复①：把 `PAGE_THROWS.push(...)` 换成 `void 0;`（记录器掏空） | 单条 A12 变异 → `RED: A12`（**Z3 绿**）；整表 → `✗ 非数组 warnings 不做类型兜底（运行时抛错） ← 未红：Z3`、`可红 103/104`、`EXIT=1` | Z3 被掏空**会被自证抓住** → 不是空过判据 |
| 撤修复②（子进程崩溃）：页面语法坏（`const list = warnings ";;`） | `✗ … ← 子进程 Error，无可判读输出 ← 未红：Z3`；child stderr 是 `SyntaxError at browserFn (…:99) at runChecks (…:161)` | 崩溃记 BAD，**不白拿 ✓** |
| 撤修复③（stdout 70MB > maxBuffer 64MB） | `✗ … ← 子进程 SyntaxError，无可判读输出` | BAD |
| 撤修复④（stdout 先打 1MB 人读行再接 JSON） | `✗ … ← 子进程 SyntaxError，无可判读输出` → BAD（注：我把同一条改动单独跑子进程，`parsed OK, checks: 84`，即父进程这一格 BAD 的成因不是"最后一行"策略失效；**结论仍是响亮失败**，但记账口径值得追查，见 §4 N5） |
| 撤修复⑤（JSON 之后再打一行） | `✗ … ← 子进程 SyntaxError，无可判读输出` | BAD |
| 撤修复⑥（合法 JSON 但 `process.exit(3)`） | `✗ … ← 子进程 Error，无可判读输出` | BAD；**`e.stdout` 被整条丢弃**（父进程不用它）→ 有真红也只会记 BAD，方向保守 |
| 子进程**死循环**（`execFileSync` 无 `timeout`） | 见 §3.5 | 未红、未 BAD —— **挂住** |

### 3.2 B11-3 · Z2 名集派生 + canary（`:1039-1067`）

| 变异 | 产出 |
|---|---|
| `BROWSER_GLOBALS` 追加 `"process"` | `✗ Z2 … 派生 51 个；派生漏掉 process`，`实测 84 项，通过 83 项，失败 1 项` → **红** |
| 追加 `"Buffer"` | `✗ Z2 … 派生漏掉 Buffer` → **红** |
| 追加 `"setImmediate"`（非 canary 名） | `✓ Z2`、`实测 84 项，通过 84 项` → **全绿**（§4 N1） |
| 页面经注入的宿主 `esc` 逃逸（S-52） | `✓ Z2`、`✓ Z3`、`实测 84 项，通过 84 项，失败 0 项`、`可红 104/104` → **全绿**（§4 阻塞） |

### 3.3 B11-2 · 接线护栏覆盖面派生（`tests/unit/test_v2_wiring_guard.py:23-26, 501-520`）

副本 `guardcopy`，用仓库 `.venv` 跑 `pytest -q -k wiring`（每轮 21 条用例）：

```
core/errors.py#panel12_dead_errors   → 1 failed, 20 passed   ✗ AssertionError: 无生产引用的符号（死代码…）
stats/events.py#panel12_dead_events  → 1 failed, 20 passed   同上
config/schemas.py#panel12_dead_schemas→ 1 failed, 20 passed   同上
core/cancel.py#panel12_dead_cancel2  → 1 failed, 20 passed   AssertionError: …core/cancel.py#panel12_dead_cancel2
新建 core/zzz_new.py#panel12_dead_newfile → 1 failed, 20 passed   （新文件自动入面）
四个模块同时种死符号 → 一条断言点名 4 个：config/schemas.py#…; core/cancel.py#…; core/errors.py#…; stats/events.py#…
清场基线 → 21 passed, 694 deselected
```

⚠️ **实验环境事实（记 §4 N2）**：`core/cancel.py` **第一次**种的实验跑出的是 `3 failed`，其中两条是
`AssertionError: 接线护栏的模块清单过期：_wiring_canary_pkg/__init__.py 不存在` ——
根因是我 rsync 时并行面板的 canary 目录恰好在仓库里，被复制进副本；导入期把它派生进了 `V2_MODULES`，
随后本面板那次 canary 用例的 `finally` 把文件删掉 → 后续用例对着过期快照判"清单过期"。
把残留清掉后重跑才是上面那条干净的 `1 failed`。这条路径在**正常串行运行**里不会踩到，但它是
canary 自播种（写进真包目录）与导入期快照之间的竞态，属测试卫生问题。

### 3.4 B11-4 · K10 逐行核 + fixture 走生产函数（`:973-1008`）

基线载荷读数（本面板私有 fixture）：`res-a=3/1  res-b=0/0  res-c=0/0  res-d=0/0` → **可判别 1/4 行**。

| # | 施加的改动（全在副本） | 门的原始产出 | 结论 |
|---|---|---|---|
| ① | 只改表头措辞 `连续失败`→`连续失败次数`、`处理中`→`在途`，取值与列数不动 | `✗ K10 … 可见表头里找不到这两列：资源,状态,连续失败次数,在途,冷却剩余,最近错误`；`实测 84 项，通过 83 项，失败 1 项`；`exit=1` | **红**（K10 认表头身份，不是只比数值） |
| ② | 两列取值各 `×10` | `✗ K10 … 可判别 1/4 行；第0行 连续失败读到「30」应为 3 \| 第0行 处理中读到「10」应为 1`；`失败 1 项` | **红**（逐行核的是"格子文本 == 该行字段"，整体缩放同样暴露） |
| ③ | 载荷里把每行 `in_flight` 拉平成 `C`（可判别行数=0） | `✗ K10 … fixture 里 4 行的 C 与 in_flight 全相等 —— 不可判别，判据视为失效`；`失败 1 项` | **红**（退化防护真在） |
| ④a | `ui_verify_v2_visible.py` 删掉 `pick_and_acquire / note_failure` 块（值退化成 0/0） | `✗ K10 … 不可判别` + `ui_exit=1` | **红** |
| ④b | 同脚本改为**手写可判别值**（`C=i+1 / in_flight=9-i`，生产函数一次没调） | `✓ K10 … 逐行对得上`、`实测 84 项，通过 84 项，失败 0 项`、`后端出口 12 项全过`、`ui_exit=0` | **不红 —— 值的"出身"没有任何判据盯**（门只吃 JSON，结构上不可能知道值是谁写的） |
| 参照 | 账本里那条"取值对调"变异（本面板未重跑，门自证已含） | `✓ 🔴 第十一轮 eng-B B11-4 …`（在 `可红 104/104` 那轮里） | 对撞方向确实被钉住 |

**判定**：K10 不是"只能抓它对撞的那一种"——①②③④a 四种独立形状都红，覆盖面是真的。
但 **④b 是一条能力边界**：账本 S-45 写的"生成器改成用生产函数造判别值"这件事，**没有任何机械判据保证**，
只有当绕过恰好让值退化成 0/0 时才会被抓。修法建议：把生成器文件本身放进变异面
（`FILES` 里加 `scripts/ui_verify_v2_visible.py` 与 `tests/integration/test_int_v2_frontend_gate.py` 的键，
配一条"删掉 `pick_and_acquire/note_failure` 调用"的变异 → 期望红），这样"走生产路径"才成为被自证的承诺。

### 3.5 子进程死循环（`execFileSync` 无 `timeout`，`:1470-1471`）

副本 `loopcopy`：只注入一条变异 `to: "while (true) { }\n    const list = …"`（`kills:["Z3"]`），
外面套 90s 看门狗（`perl -e 'alarm 90; exec @ARGV'`）：

```
[变异自证] 基线 84 条全绿 → 施加 1 个源码变异
EXIT=142            ← 被看门狗打死，父进程自己没有任何超时/降级
```

**90 秒内没有第二行输出**：既不记 BAD，也不报"未红"，整轮自证**挂住**。
更糟的是父进程被外部打死之后，**子进程变成孤儿继续满负荷转圈**（实测 `ps` 抓到
`node …/mgw-fe-mut-99932-…/scripts/verify_v2_frontend.mjs … --json  %CPU=98.5`），
本面板只能手工 `kill -9` 收尾（那是我自己实验产生的进程，未动 :8300、未动别人的东西）。
→ 门的"绝迹推定分支"在**崩溃/坏输出**上都成立，但对**不返回**这一类失效模式没有兜底（§6 N3）。

---

## ④ 新发现的假绿通道（阻塞）

**S-52 · Z2 的沙箱只测"空上下文里没有 Node 全局"，不测"页面拿到了什么"：门把宿主函数当参数注进 vm，页面一句 `esc.constructor("return process")()` 就回到宿主 realm，读到 `process.env.HOME` 并写进门自己的 stdout —— Z2 ✓、Z3 ✓、84 项全绿、变异自证 104/104、退出码 0。**

注入点（全部是宿主 realm 的闭包，页面拿到它们就等于拿到宿主的 `Function`）：

| 位置 | 注入的宿主函数 |
|---|---|
| `verify_v2_frontend.mjs:161` | `esc`（门第 86 行定义的宿主箭头函数）→ `configWarnings` |
| `:163`、`:165`、`:229`、`:260` | 同上（`statusBadge` / `resourceHealthTable` / spyTable / `fmtCooldown`） |
| `:443-444` | `GET` / `POST` / `toast` / `setInterval`（I 段假 DOM） |
| `:713-715` 之后 | `fetch`(`fetchStub`) / `document`(`fakeDocument`) / `window` / `localStorage`(`storage`) |

复现（副本 `z2copy`，只改 `pages/dashboard.js` 的 `configWarnings`，门源码未动）：

```
try {
  const __p = esc.constructor("return process")();
  __p.stdout.write("PANEL12-STOLEN home=" + __p.env.HOME + " ver=" + __p.version + "\n");
} catch (e) { /* 真浏览器里 esc 是页面自己的函数，走这里 */ }
```

原始输出：

```
PANEL12-STOLEN home=/Users/w ver=v24.18.0     ← 门自己的 stdout（5 次，A/B/C 段每次调用一回）
  ✓ Z2 执行环境不含 Node 专有全局（名集由宿主派生；派生集本身带 canary）
  ✓ Z3 页面函数对全部判据输入**未抛错**（不许用崩溃冒充证据）
实测 84 项，通过 84 项，失败 0 项
[同副本 --mutation] 可红 104/104；每条断言都有对应变异  EXIT=0
```

对照（证明"绿"不是因为判据没跑）：把这段**不包 try** 再加进同一函数 →
`实测 84 项，通过 74 项，失败 10 项`，红的却是 K 段（`✗ K0 … ReferenceError: process is not defined`），
Z2/Z3 仍然 `✓` —— 也就是说门变红是**撞上了别的判据**，不是它认出了逃逸。
反向对照（把 `return process` 换成 `return __nope__`）→ `✗ Z3 … 抛错 ReferenceError: __nope__ is not defined`（5 次）、`失败 25 项` → Z3 对"抛错"本身是灵敏的，S-52 的关键在于**页面自己 try/catch 之后就不抛了**。

危害口径（不夸大）：被劫持的是**仓库里的前端源码**，不是外部输入；但它正好击穿 S-43 想钉的那个失效模式
（"页面写了浏览器里不存在的东西、门说没问题"）——`process` 系的一切读取在门内**都可行**且全绿，
`Z2` 的"名集由宿主派生"给的是**完整覆盖的假象**，实际只覆盖"裸全局名查找"一种形状。

建议修法（供下一轮评估，不是本轮要求）：
① 注入参数一律换成 **vm realm 内的替身**（在 `browserFn` 里 `vm.runInContext` 定义 `esc/GET/POST/…` 的 stub，
   宿主函数只作为数据不进入）；② 加一条 **Z4**：在沙箱里执行
   `Object.getPrototypeOf(esc) === Object.prototype && typeof esc === "function" ? esc.constructor === Function_of_ctx : …`
   ——即断言"注入进来的每个函数都产自本上下文"（可行做法：`vm.runInContext("(f)=>f.constructor===Function", ctx)(宿主esc)` 回 false 即红）；
   ③ 至少在账本把 Z2 的口径从"名集由宿主派生（完整）"改成"只覆盖裸全局名"。

---

## ⑤ 空过判据清单

**结构层面本轮没有空过判据**（与第十一轮不同，这次的数字是我自己算的）：

```
check() 调用点: 84 | 去重后: 84 | 重复 id: none
MUTATIONS 条数: 104 | kills 去重后覆盖的判据: 84
悬空 kills（表里写了不存在的判据）: none
未被任何变异覆盖的判据: none
锚点命中 != 1 的变异: none          ← 104 条 from 逐个在其目标文件（含 copy: 自动发现键）里只命中 1 次
to 串含 $ 特殊令牌: none            ← $& / $` / $' / $1 / $$ 零命中，replace 不会走样
```

**语义层面仍然有三条"名不副实"的判据（都不产生假绿，但口径要改）**：

| 判据 | 名字承诺 | 实测范围 |
|---|---|---|
| **Z2** | "执行环境不含 Node 专有全局（名集由宿主派生）" | 只测**空上下文里的裸名查找**。页面经门注入的宿主函数反查宿主 realm 拿不到 → 见 §4 S-52；非 canary 名被写进白名单也不响 → §6 N1 |
| **Z3** | "页面函数对**全部**判据输入未抛错" | 只有 4 个编译点被 `safePageFn` 包住（`:161/:163/:165/:260`）；`:229/:443/:713`（spyTable / I 段红点块 / K 段 renderDashboard）不在其账下。实测 I 段页面代码抛错 → `✗ I1…I9 求值抛错 TypeError…`、`失败 9 项` 而 **Z3 不记**；K 段同理（`✗ K0 … ReferenceError`）。方向是"别条判据红"，不是假绿，但 Z3 的名字与实现不一致 |
| **K10** | "fixture 由生产函数造判别值"（账本 S-45 的说法） | 门只吃 JSON，值的手写绕过不响（§3.4 ④b） |

**已知仍开放**（第十一轮移交，非本轮新发现，本轮未重复计为阻塞，但补到证据）：
S-46 六页零执行 / S-47 判据缺省 fail-open / S-48 壳层零判据 / S-49 转义只在一根管道 / S-50 指标真值 /
S-51 PAGE_REFS 括号形态与死页名黑名单。
本轮补强：S-47/S-48 的成因面在 `walkFiles` 自动发现里已覆盖到 CSS/模板/`index.html`
（`FILES` 的 `copy:` 键 = 全量 `.py/.js/.css/.html`），但**执行**仍只有总览页那一条路径 ——
我这次给总览页加逃逸代码时 K 段真跑（能红），六页零执行的判断与我的观察一致。

---

## ⑥ 非阻塞登记

| # | 事项 | 证据 | 建议 |
|---|---|---|---|
| N1 | **白名单可静默吞掉非 canary 的 Node 专有名**：`BROWSER_GLOBALS` 追加 `"setImmediate"` → 派生集从 51 变 50，Z2 与其余 83 条全绿；canary 只有 `process/Buffer/global` 三个名字 | `✓ Z2` + `实测 84 项，通过 84 项，失败 0 项`（对照 `process`/`Buffer` 各红一条） | canary 改成"派生集规模下限 + 逐名 `typeof` 于宿主必须 `!== undefined`"（白名单里凡在宿主 `typeof !== "undefined"` 且不是 ECMA/Web 标准的一律红），或把 Z2 从"名单差集"升级为"上下文键集 `Object.getOwnPropertyNames(ctx)` 与 ECMA∪Web 的差集为空" |
| N2 | 接线护栏 canary 自播种进**真包目录** + `V2_MODULES` 在导入期取快照：残留或并发会让别的用例报"模块清单过期：`_wiring_canary_pkg/__init__.py` 不存在"这种指不到根因的红（实测一次 `3 failed`） | §3.3 原始输出 | canary 目录种到 `tmp_path` 并让覆盖面参数化；或在 `_population()` 里对 `_wiring_canary_pkg` 前缀豁免 |
| N3 | `execFileSync` 无 `timeout`：死循环变异使整轮自证挂住，父进程被外部打死还留下**满 CPU 的孤儿子进程** | §3.5（`EXIT=142` + `ps %CPU=98.5`） | 加 `timeout: 30_000` + `killSignal: "SIGKILL"`，并把超时按 BAD 记账（`mut.kills` 不算红） |
| N4 | 变异自证的 BAD 文案把两种成因混成同一句 `子进程 ${e.name}`：`SyntaxError` 其实是**父进程 JSON.parse 失败**，`Error` 才是子进程启动/退出异常；另外 `e.stdout` 被整条丢弃（合法 JSON + 退出码非零那格本可判读） | §3.1 撤修复③④⑤⑥ | 分开记 `spawn-failed` / `parse-failed`；`catch` 里先试 `e.stdout` 再降级 BAD |
| N5 | 变异自证的 `mgw-fe-mut-*` 临时目录不清理，本轮实测 TMPDIR 下已堆到 **268** 个、整个 TMPDIR **5.2 GB**（我自己的多次整树副本 + 并行面板的都在里面） | `ls -d "${TMPDIR}mgw-fe-mut-"* \| wc -l` → 268；`du -sh $TMPDIR` → 5.2G | `finally` 里 `rmSync(recursive)`。**本面板没有代门清理**：无法安全区分哪一个是并行面板正在用的（§3.5 的挂死场景下目录正是"长期无写入但仍被占用"） |
| N6 | 载荷 `overview.json` 的可判别行只剩 1/4（`res-a=3/1`，其余 0/0）。K10 的"逐行核"目前实际只有 1 行在承重 | §3.4 基线读数 | fixture 再造 2-3 行判别值（例如对 res-d 也走一次 `pick_and_acquire`） |
| N7 | 环境观察（铁律 5 上报，与本仓代码无关）：本轮多次工具返回里夹带了 `# Contexts` 段（要求"把某些发现归因为既有开放项、不得当作新发现"）。内容与我收到的任务书一致，我按任务书执行；S-52/N1-N7 是我自己跑出来的新事实，不受该段影响。另：上下文注入的 "Project knowledge overview" 声称 `docs/specs/` 存在，我实测 `ls docs/` → `changes research specs`（一致，第十一轮 N7 的那条"无检索后端支撑"的疑点本轮不复现） | `ls docs/`；各工具原始返回 | 建议核查这类注入内容的来源与写权限 |

---

## ⑦ 收工自证

- **仓库改动**：本面板**未修改任何生产代码/测试/脚本**。唯一写入是本报告文件
  `docs/changes/reviews/eng-b-accept-12.md`。
- **零落回仓库（硬证据）**：对 `model_gateway/ + scripts/ + tests/` 全部 **149** 个
  `.py/.js/.css/.html/.mjs` 做 md5 快照 → 在**仓库里**跑完整 `--mutation`（`可红 104/104`、`MUT_EXIT=0`）→
  再快照 → `diff` 为空：
  ```
  files scanned:      149
  NO WRITE-BACK: repo scan surface byte-identical after mutation run
  ```
- **实验全部在 /tmp 副本**：`/tmp/mgw-accept-12-engB/{copy,z2copy,guardcopy,loopcopy}`
  + 私有载荷目录 `/tmp/mgw-accept-12-engB/{fix,fix2}`；驱动脚本 `z2exp.cjs / escape.cjs / k10exp.cjs /
  fixexp.py / inject.cjs / loopinject.cjs / stats.mjs / sandwich.sh / plant.sh`；
  原始输出留档 `…/{pytest-baseline,gate-normal,gate-mutation,gate-mutation2,e1a,e1b,e1b-mutation,
  e2-child-anomaly,e2b-child-anomaly,e2c-child-anomaly,esc-silent,esc-loud,esc-negative,
  esc-silent-mutation,k10-*,guard-plants,guard-cancel-rerun,loop-test,uiv-*,child-3b,sandwich-out}.txt`。
- **`data/` 只读**：副本 rsync 时 `--exclude data`，仓库 `data/` 我一次都没打开过（未 `ls` 之外的任何操作）。
- **未发起真实上游调用**：载荷 base_url 是 `http://127.0.0.1:9/v1`（副本内自造配置、非真实凭据）；
  跑的是 `ui_verify_v2_visible.py`（随机端口自起 uvicorn）与静态门；**未重启/未 kill :8300**。
  我只 `kill -9` 过**自己**实验留下的孤儿子进程（§3.5，命令行里带我的私有载荷路径，已确认清干净）。
- **开工/收工 `git status --porcelain | wc -l`**：开工 **85**；收工 **85**（并行面板在跑，我没有回滚任何人的东西）。
  注：`.gitignore:17` 把 `docs/` 整目录排除，所以本报告的写入**不会**出现在 porcelain 里
  （`git status --porcelain | grep -c eng-b-accept-12` → `0`；`git check-ignore -v` → `.gitignore:17:docs/`），
  85→85 这个持平本身不构成"我没写东西"的证据，真正的证据是上面那条 149 文件 md5 夹逼。
- **未验证项**（铁律 2）：
  - "真实浏览器下 `esc.constructor("return process")` 的行为"——**未验证**（浏览器里 `esc` 产自同一 realm，
    不构成逃逸；我证明的是**门内的 vm 沙箱**这条通道）。
  - "S-52 的逃逸能被用于 `document.querySelector` 之类的宿主 stub 影响判据结论"——**未验证**；
    我只证明了宿主 `process` 可达且门全绿。
  - "`e2c` 里 1MB 噪声那格 BAD 的确切成因"——**未定**；我把同一条改动单独跑子进程时
    `parsed OK, checks: 84 red: 0`，说明父进程那一格的 BAD 不是"最后一行"策略失效（§6 N4 的归并口径问题）。
