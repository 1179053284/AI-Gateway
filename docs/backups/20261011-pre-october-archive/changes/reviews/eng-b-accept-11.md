# 验收面板 B（第十一轮）· 资深后端工程师 —— 机械门自身可信度与测试基建

验收对象：`scripts/verify_v2_frontend.mjs`（门）第十轮新落的三处底层机制 + `tests/unit/test_v2_wiring_guard.py` / `tests/integration/test_int_v2_frontend_gate.py`
验收方式：**只读仓库**，全部实验在 `/tmp/mgw-accept-11-engB/*` 副本内进行
开工 `git status --porcelain | wc -l` = **82** ；收工 = **82**（其间数字随并行面板波动，非本面板改动）

---

## ① 结论

**不通过（阻塞 4 条）**。

先说清好消息，避免误读：**三处机制里有两处是的真在做事**，且第十轮那两个具体回归的修复被我独立复现打穿了——`--json` 通道不再是推定分支（锚点过期 / 子进程崩溃 / 尾部污染三种打回方式全部实测生效），变异锚点的自引用问题已消除（100 条锚点逐条验过恰好命中 1 次，`$&`/`$$`/`` $` ``/`$'` 零命中，`replace` 逐字回写无漂移）。

但本轮的四条阻塞都属于**同一类病：把"没被证明"写成"已证明"**，其中两条正是本面板被明确要求复查的两个老坑复发：

| # | 阻塞 | 一句话 | 证据 |
|---|---|---|---|
| B11-1 | `verify_v2_frontend.mjs:1230` 页面变异仍走**推定分支** | 任何让 `runChecks` 崩溃的页面变异，可以不观察就白拿"✓ 已杀死指定断言"；我造了一条**永远不可能杀死 Z2** 的变异，门报 `✓ … [抛错 SyntaxError]`「可红 101/101」 | 本文 §2.2 |
| B11-2 | 接线护栏的**模块覆盖集仍是手写清单**（`test_v2_wiring_guard.py:21` `V2_MODULES`） | 17 个真实模块在护栏之外；同一个死符号种进 `core/cancel.py` 门**全绿**，种进 `core/resources.py` 立刻红 | 本文 §3.1 |
| B11-3 | `Z2` 是**5 个名字的黑名单**，不是环境判定 | 只要漏进 `global`/`module`/`exports`/`__filename` 任一未列名，页面就能真读到 `process.env.HOME`，而 Z2 与其余 80 条**全绿** | 本文 §2.1 |
| B11-4 | 「列↔字段绑定」判据**只覆盖了过去踩过的两列**，且载荷让另两列不可判别 | 把「连续失败」与「处理中」两列的**取值对调**（表头不动、单元格数不动），81 条全绿；共享 fixture 里这两列恒为 `0/0`，本就无从判别 | 本文 §3.2 |

判定依据（AGENTS.md 铁律 5 + 本面板任务书）：B11-1 与 B11-2 不是"判据不够多"，而是**门的自证数字本身含未观察项**、**护栏的覆盖面被高估**——这正是前十轮反复出现的"新一轮判据被下一轮打破"的成因，必须先修再谈验收通过。

---

## ② 三处机制的复验

### 2.1 机制一：vm 空上下文（`browserFn`，门 89–102 行）

**做对了的（实测确认）**

```
$ node -e '... vm.createContext({}) 里 typeof ...'
sandbox sees host Buffer: undefined | setTimeout: undefined | structuredClone: undefined | URL: undefined | crypto: undefined
```

- `process/require/Buffer/setImmediate/__dirname` 在空上下文里确实取不到 → Z2 钉的是真事，不是装饰。
- **上下文不串**：`globalThis.__f` 每次 `vm.createContext({})` 都是全新 context，实测第二次调用看不到第一次写的变量：

```
call1 sees own global: number
call2 sees call1 var (must be undefined): undefined
```

- **跨 realm 判定无隐患**：门内 `instanceof` 出现次数 = **0**（`grep -c "instanceof" scripts/verify_v2_frontend.mjs` → `0`）。宿主侧只做 `typeof` / `.includes()` / `.match()` / `Array.isArray`（跨 realm 均安全）。实测：

```
cross-realm Array.isArray(host view): true | arr instanceof host Array: false | constructor name: Array
```
  即"用 instanceof 判会漏、但门没用 instanceof"——此项**不构成问题**。
- **注入的是页面真 `esc` 而非门的 `esc`**（K 段）：我 gut 掉 `api.js` 的真 `esc`（只留 `&`），门立刻红：

```
--- real esc AFTER ---
export function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;");
}
=========== GATE VERDICT ===========
  ✗ K9 后端下发的原文经页面转义  err= 含转义=false
实测 81 项，通过 80 项，失败 1 项
```
  （附带事实：A 段 `check("A14")` 用的是门自己的 `esc`，对真 `esc` 弱化无感——但 K9 兜住了，不构成假绿。）
- **浏览器存在、门未注入的东西 → 失败方向是"红"不是"绿"**。我在 `renderDashboard` 里同时用了 `navigator` / `window.location` / `HTMLElement` / `document.querySelectorAll`：

```
  ✗ K0 能执行真实 renderDashboard  ReferenceError: navigator is not defined
  ✗ K7 …  ✗ K1 …  ✗ K2 …  ✗ K3 …  ✗ K8 …  ✗ K4 …  ✗ K5 …  ✗ K9 …  ✗ K6 …
实测 81 项，通过 71 项，失败 10 项
```
  10 条同时红、零条静默通过。所以这个洞是**假红（过严）**方向，不是假绿；记为非阻塞（见 §4 N2）。

**但保真度有一个能出假绿的洞 → B11-3**

Z2 的判据是**写死的 5 个名字**：

```js
  const leaked = ["process", "require", "Buffer", "setImmediate", "__dirname"]
    .filter((g) => browserFn(`return typeof ${g};`)() !== "undefined");
```

把 `global`（= 宿主 realm 的全局对象本身）漏进上下文，**这五个名字依然全是 undefined**，而页面代码能拿回真 `process`：

```
### A) leaked keys ["global","__f"] -> {"bare_process":"undefined","via_global_process":"object",...}
### B) Z2 verdict when only `global` is leaked into the sandbox
total checks: 81 | RED: NONE | Z2: {'id': 'Z2', 'ok': True}
```

完整复现（门源码除 `createContext({ global: globalThis })` 一行外未改，dashboard.js 里加两行读 Node 状态）：

```
sandbox leaks `global`; dashboard.js now reads global.process.platform/version/env.HOME
=========== gate verdict ===========
total checks: 81
RED: NONE  <-- page ran real Node process state inside the "browser" sandbox
Z2 row: [{'id': 'Z2', 'ok': True}]
```

同一条变异自证对此**无感**（`MUTATIONS` 里 `self:true` 只钉了 `process` 一个注入形状）：

```
  ✗ 🔴 第十轮 R-3：沙箱泄漏 Node 全局 …  ← 锚点命中 0 次（已过期？）
可红 99/100
```

修法是把它从"黑名单"换成"环境判定"：直接对 `Object.getOwnPropertyNames(ctx)`（或 `vm.runInContext("Object.getOwnPropertyNames(globalThis)")`）与 ES 内置 + Web 标准白名单做差集，多一个就红。

**顺带证伪成功的两项（结论是"没问题"，也登记以免下轮重复查）**
- 跨 realm 逃逸：页面代码试图用注入的宿主函数反查 Node——`esc.constructor("return process")()` 在 vm 里**拿不到宿主 realm**（返回 undefined 并抛 TypeError），且门以 10 条红的方式真报了：`RED: ['K0','K7','K1','K2','K3','K8','K4','K5','K9','K6']`。此项**推定安全**。
- 变异只改副本、绝不落回仓库：对仓库 `model_gateway` + `scripts` 全部 101 个源文件做 md5 快照 → 跑完整 `--mutation` → 再快照：

```
mutation_exit=0
NO WRITE-BACK: repo scan surface byte-identical after mutation run
```

### 2.2 机制二：`--json` 通道

结论：**这一处修好了，且是被我三种打回方式实测确认的**，不再是推定分支。

先证明通道本身读得到红（不是靠抛错蒙的）——手工施加沙箱泄漏后跑子进程 `--json`：

```
=== child --json output with leaked sandbox ===
{"checks":[ … ,"id":"Z1","ok":true},{"id":"Z2","ok":false}]}
child_exit=0
```
单行 JSON、退出码固定 0、Z2 真实 `false`。

三种打回方式（均在副本内）：

**A. 锚点过期** → 红：
```
EXIT=1
99:  ✗ 🔴 把 `hidden` 属性判据摘掉 …  ← 锚点命中 0 次（已过期？）
104: 可红 99/100；每条断言都有对应变异
```

**B. 子进程崩溃**（把自变异 `to` 改成语法坏，副本根本跑不起来）→ 红，且**明确拒绝把抛错算红**：
```
mutation 'to' now yields a gate copy that cannot even parse
EXIT=1
117:  ✗ 🔴 第十轮 R-3：沙箱泄漏 Node 全局 …  [抛错 Error]  ← 未红：Z2
123:  ✗ … ← 纹丝不动：Z2
可红 98/100
```
这正是第十轮那条假自证的反面——第十轮这里是"抛错算绿"，现在算红。

**C. 输出被污染**
- 尾污染（JSON 之后再打一行，`indexOf("{")` 会切错、而"取最后一行"也会切错）→ **红，失败响亮**：
```
EXIT=1
104: 可红 98/100
105:  ✗ … ← 纹丝不动：Z1
106:  ✗ … ← 纹丝不动：Z2
```
- 头污染（JSON 之前打人读行，含 `${`）→ **仍然正确解析**，100/100、exit 0。
  即"最后一行 + 只输出一行"的策略确实起了作用。

**残留问题 → B11-1（推定分支只修了一半）**

`runMutations()` 的 catch 里：
```js
1229:    } catch (e) {
1230:      threw = e.name;
1230:      if (!isSelf) red = mut.kills;   // 🔴 页面变异仍按"抛错=杀死"记账
```
门自己（`self:true`）不再吃这条，但**页面变异照旧**。我据此造了一条**不可能杀死 Z2** 的变异（Z2 判的是 vm 上下文，跟 dashboard.js 语法无关）：

```js
{ why: "PANEL-EXP: page syntax break + presumptive kill on Z2", file: "dash",
  from: 'if (!list.length) return "";',
  to:   'if (!list.length) return ";;', kills: ["Z2"] },
```
跑出来的原始输出：
```
10:  ✓ PANEL-EXP: page syntax break + presumptive kill on Z2  [抛错 SyntaxError]
105: 可红 101/101；每条断言都有对应变异
```
门给了一条**凭造**的杀死并打出 101/101。再直接证明 Z2 当时根本没被求值——同一条改动跑普通模式：
```
SyntaxError: Invalid or unexpected token
    at browserFn (…/verify_v2_frontend.mjs:99:3)
    at runChecks (…/verify_v2_frontend.mjs:145:26)
EXIT=1
```
`runChecks` 在第 145 行就整体抛出，Z2（第 844 行）从未注册，"Z2 变红"无从观察。

**根因**：`check()` 的 try/catch 只护得住传函数（`ok` 为 `()=>…`）的判据；实测 81 条里 **66 条是传值（eager）**，谓词在调用点就求值，异常**漏到 `runChecks` 之外**。例如 A12：
```js
168:  check("A12", "warnings 非数组 → 安全降级不抛", configWarnings(undefined) === "");
```
```
TypeError: Cannot read properties of undefined (reading 'length')
    at runChecks (…/verify_v2_frontend.mjs:168:41)
```
（把该行改成 `() => configWarnings(undefined) === ""` 后再跑同一条变异，A12 **确实会红**：`✗ A12 … 求值抛错 TypeError` → 说明这条变异是真判据，但门是靠"崩了算红"记账、而不是靠观察记账。）

顺带登记：这类崩溃给出的是 **exit 1**（与"有判据红"同号），不是文件头声明的 `2 = 抽取/结构级错误（脚本自身失效）`：
```
clean_exit=0
crash_exit=1
```

**我独立复算了整张变异表（剥掉推定分支）**——写了一个独立驱动 `independent_mutations.mjs`，把每条变异（含全部 100 条，不只 2 条 `self`）都施加到副本、一律以**子进程 `--json`** 观察逐条红绿：
```
baseline: 81 checks, red=[none]
============================================================
observed kills: 99/100
NOT evidenced (crash/anchor/survived): 1
  ✗ #5 非数组 warnings 不做类型兜底（运行时抛错） :: CRASHED … table claims kills=[A12] -> NOT OBSERVED
```
即：**账本数字基本诚实（99/100 可观察），但门自己的产出把 99 报成 100，且机制上允许把任意崩溃白记成杀死**。这条必须修：把 66 条 eager 判据改成惰性（或把 `red = mut.kills` 换成"崩溃 = 该条变异未获证据"），并让 `--mutation` 打印 `observed / presumed` 两栏。

### 2.3 机制三：变异锚点

自引用残留：**无**。逐条实测（把 `MUTATIONS` 从门源码里 eval 出来、重建含 68 个 `copy:` 自动发现键的 `FILES` 表，对每个 `from` 在目标文件里数命中）：
```
parsed mutations: 100
auto-discovered copy keys: 68
gate(self) mutations: 2
--- anchor problems (must be none) ---
NONE
```
两条 `gate` 自变异之所以不再撞自己写的字面量，是因为 `from` 在源码里以 `'…\\n' + '  new vm.Script('` 的**转义拼接形式**存在，与运行时真含换行的锚点串不同形，实测：
```
🔴 把 `hidden` 属性判据摘掉 … | raw from in src: false | joined from in src: true
🔴 第十轮 R-3 … | raw from in src: false | joined from in src: true
```
——即"命中 1 次"是靠**转义差异**侥幸成立的（见 §4 N4：把单行锚点写成未转义形式就会 hits=2，是下一轮的坑）。

替换语义（`$&`/`$1`/`` $` ``/`$'`/`$$`）：**零命中，且逐字回写无漂移**——
```
--- replacement-token problems ---
none
--- verbatim drift ---
none
```

只改副本、不落回仓库：见 §2.1 末尾的 101 文件 md5 前后 `diff` 为空。

---

## ③ 空过判据清单

### 3.1 接线护栏：覆盖集是**手写**的（B11-2）

`tests/unit/test_v2_wiring_guard.py` 的**符号**集确实是 AST 自动导出的（`_population()` 走 `PKG.rglob`），这点做对了；但**模块**集是手写的 38 行清单：

```python
21: V2_MODULES = [   # 注释自认：「新增模块要一并纳入本表」
```

没有任何测试把 `V2_MODULES` 与包内真实模块集比对——`test_population_covers_the_modules_named_by_the_plan:514-521` 只断言**另外 8 个手敲名字在清单里**（清单 vs 清单），不校验清单 vs 仓库。实测缺口：

```
listed modules: 38
package .py modules (excl __init__/static): 55
NOT covered by guard: 17
    adapters/gemini_out.py
    config/presets.py
    config/schemas.py
    core/cancel.py
    core/errors.py
    core/instance_lock.py
    logsetup.py
    stats/aggregate.py
    stats/events.py
    （+ 8 个 __init__.py）
```

**证伪实验**：种一个"全包除定义处再无引用"的公开函数，分别落在清单外与清单内。

- 落 `core/cancel.py`（清单外，resources.py 的同种已移除，只剩这一处）：
```
planted_dead  counts → resources.py:0  cancel.py:1
=========== RUN GUARD ===========
......                                                                   [100%]
6 passed in 21.70s
```
**门全绿。**
- 同样的种法落 `core/resources.py`（清单内，对照组）：
```
=========== RUN GUARD (control: listed module) ===========
E  AssertionError: 无生产引用的符号（死代码，§20 反过度设计）：core/resources.py#planted_dead_symbol_listed_module
FAILED tests/unit/test_v2_wiring_guard.py::test_every_public_symbol_has_a_referrer
1 failed, 5 passed in 21.63s
```

结论与项目历史一致：**手写的覆盖集不算护栏**。修法很轻——把 `V2_MODULES` 换成"`PKG.rglob('*.py')` 减去显式排除集"，排除项同样要求附理由并有过期检查（和现有 `ALLOWED_NO_REFERRER` 同构）。`_wiring_canary_pkg` 自播种本身有效（对照组红即证），它的问题是播种在**已被覆盖**的模块里，因而测不到"清单漏一整个模块"这个真实失效模式。

### 3.2 空过 / 失效判据（实测，逐条）

| 判据 | 失效方式（我施加的改动） | 门是否响 |
|---|---|---|
| **B11-4：列↔字段绑定缺失** | `dashboard.js` 里把「连续失败」与「处理中」两列的 `<td>` 取值**整体对调**（表头不动、`<td>` 数不动） | **不响**：`实测 81 项，通过 81 项，失败 0 项` |
| 同上，用可判别载荷 | 自建 fixture 令 `C/in_flight = 3/7, 1/9, 5/2, 8/4`，跑同一份对调副本 | **仍不响**：`实测 81 项，通过 81 项，失败 0 项` |
| （对照，证明方法有效） | 把「冷却剩余」与「最近错误」两列取值对调 | **响 4 条**：`✗ B4 ✗ C12 ✗ C13 ✗ K6 … 串列=1 / 实测 81 项，通过 77 项，失败 4 项` |
| **Z2**（§2.1） | 漏 `global` 进 vm 上下文 + 页面读 `global.process.env.HOME` | **不响**（81 全绿） |
| **A12 记账方式**（§2.2） | `const list = warnings;` | 响（真红），但门是**凭崩溃推定**，不是观察 |

另外：共享载荷 `/tmp/mg-v2-visible/overview.json` 里四条资源 `C` 与 `in_flight` **恒为 0/0**（本次实跑读数），所以这两列在任何现存判据下天然不可判别——这是 B11-4 的成因之一。

### 3.3 `ui_verify_v2_visible.py` 的 12 条后端出口判据**无自证**

```
### any mutation harness for ui_verify's own 12 backend checks? ###
grep -cE "MUTATION|kills|变异" → 1        # 唯一那处是文件头注释「--mutation 交给 verify_v2_frontend.mjs」
```
即 `--mutation` 把 100 条前端变异跑完后，**12 条后端出口判据没有任何变异盯守**（"后端出口实测 12 项" 独立于变异面）。抽测其反应性尚可：
```
### probe: is backend check ④ vacuous? change the wording it asserts ###
  ✗ ④ 覆盖告警说清生效序
  ✗ A6 含推理优先级说明「请求级」（Q28-③）
后端出口实测 12 项，通过 11 项，失败 1 项
```
→ 不是空过判据，但属"未被自证覆盖"，记 §4 N3。

---

## ④ 三门基线复跑（逐字抄自本面板终端）

```
=========== [1] pytest ===========
705 passed in 134.82s (0:02:14)
=========== [2] ui_verify --mutation ===========
[变异自证] 基线 81 条全绿 → 施加 100 个源码变异
可红 100/100；每条断言都有对应变异
后端出口实测 12 项，通过 12 项，失败 0 项
=========== [3] node gate normal ===========
========================================================
实测 81 项，通过 81 项，失败 0 项
=========== [4] node gate --mutation ===========
[变异自证] 基线 81 条全绿 → 施加 100 个源码变异
可红 100/100；每条断言都有对应变异
=========== git status end ===========
      82
```

命令逐字为：`.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest -p no:warnings`；`.venv/bin/python scripts/ui_verify_v2_visible.py --mutation`；`node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json`（及 `--mutation`）。与账本（81 条断言 / 100 个变异 / 后端 12 项 / pytest 705）**逐项一致**。

补充两条与基线相关的实测：
- **判据 id ↔ 变异 kills 双向对齐**（无孤儿、无重复、无悬空）：
```
check() call sites: 81 | unique ids: 81
duplicate check ids: none
checks NOT in any kills: []
kills NOT matching any check id: []
```
- **确定性**：同一载荷连跑 15 次
```
distinct verdict sets across 15 runs: 1
  red= NONE count= 15
```

⚠️ **基线曾被我这边读到"红"，根因值得记一笔**：17:30 我读到的 `overview.json`（md5 `5941c67d…`）里四类告警**不含「503」**，于是门稳定报
```
实测 81 项，通过 80 项，失败 1 项
  ✗ A2 文案透传：含 503
```
而同期 `pytest` 是 705 全绿（集成测试用 `_overview_payload(tmp_path)` 自造载荷，不读这个文件）。当前仓库 `main.py:295` 确实写着「调用将返回 503」——即 `/tmp/mg-v2-visible/overview.json` 是**全局唯一、被并行面板与多份 /tmp 副本反复覆写**的共享可变路径，别的副本改了文案就会把主仓的门带红。我随后自跑 `ui_verify_v2_visible.py` 重新生成（md5 → `61e3cc2c…`，`has 503: True`）后基线恢复。见 §4 N1。

---

## ⑤ 非阻塞登记

| # | 事项 | 证据 / 位置 | 建议 |
|---|---|---|---|
| N1 | 门的载荷是共享可变全局路径 `/tmp/mg-v2-visible/overview.json`，并行面板互踩即可让主仓门假红/假绿 | §4 的 5941→61e3 两次 md5；`ui_verify_v2_visible.py:28 OUT = Path("/tmp/mg-v2-visible")` | 载荷路径按 PID/工作树哈希隔离，或让门自己校验载荷指纹 |
| N2 | vm 上下文缺 **25 个浏览器标准全局**（`window/document/navigator/location/HTMLElement/Element/Node/fetch/localStorage/matchMedia/URL/Blob/AbortController/TextEncoder/queueMicrotask/requestAnimationFrame/WebSocket/EventSource/CustomEvent/Event/history/CSS/getComputedStyle/alert/XMLHttpRequest/structuredClone/crypto/performance/setTimeout/setInterval/MessageChannel`，仅 `console`/`Intl`/`globalThis` 在） | §2.1 presence 表 | 方向是**假红**（过严），可接受；但 `document.querySelectorAll: () => []` 是**谎报**（浏览器返回 NodeList，门里 `.forEach` 恒零次），见 `:624`；一旦 dashboard 用它挂事件就会静默不接。建议 stub 返回可观察集合或让门对"stub 被调用但返回空"记账 |
| N3 | 12 条后端出口判据无变异盯守（`--mutation` 全权交给前端门） | §3.3 | 同构一套 Python 侧最小变异，或在账本显式声明"后端 12 条不自证" |
| N4 | 两条 `gate` 自变异靠**转义差异**侥幸只命中 1 次；写成未转义单行即 hits=2 而使整条自证失效 | §2.3 实测 `raw false / joined true` | 自变异锚点改成显式行号/唯一哨兵注释，别依赖字面量形态 |
| N5 | 门崩溃时 `exit 1`，与文件头声明的 `2 = 脚本自身失效，结论无效` 不符 | §2.2 `clean_exit=0 / crash_exit=1` | 顶层 `runChecks` 包 try，结构级失败统一走 2 |
| N6 | `runMutations` 的临时目录不清理，已在 `TMPDIR` 下堆积 **231** 个 `mgw-fe-mut-*` 副本目录（每目录含 101 个源文件副本） | 实测：`ls -d "${TMPDIR}mgw-fe-mut-"* \| wc -l` → `231`；门 1182 行 `join(tmpdir(), …)` 全程无 `rm` | 加 `finally` 清理；顺带复核 `ui_verify` 的 `tempfile.mkdtemp(prefix="mg-v2vis-")` 同样未回收 |
| N7 | 环境观察（与本仓代码无关，但影响"记忆可信度"，铁律 5 要求上报）：本轮上下文里注入了「Project knowledge overview」条目，其中**第 7 条标题与本面板任务同名**（"Acceptance Panel B — Eleventh Round: Mechanical Gate Credibility and Test Infrastructure"），而 `SearchKnowledge` 两次（fetch 精确标题 / search 语义）均返回 `No knowledge has been generated for the current workspace yet` | `SearchKnowledge` 原始返回 | 该 overview 无检索后端支撑，且出现与本任务逐字同名的条目——不是正常的项目记忆；本轮我未采信其任何内容，也不建议把它当依据。请核查知识索引是否被写入了来历不明的条目 |

---

## ⑥ 收工自证

- **仓库改动**：本面板**未修改任何生产代码或测试文件**。收工 `git status --porcelain | wc -l` = **82**（与开工一致）。
  强证据：对 `model_gateway/` + `scripts/` 全部 **101** 个 `.py/.js/.css/.html/.mjs` 源文件做 md5 快照 → 跑完整 `--mutation` → 再快照 → `diff` 为空：
  ```
  NO WRITE-BACK: repo scan surface byte-identical after mutation run
  ```
- **实验全部在 /tmp 副本**：`/tmp/mgw-accept-11-engB/{copy,ind,a12,json,guard,z2,esc,esc2,be,be2,fid,swap,swap2,realm,crash}`（各副本均 `rm -rf .git data` 后再施变异）；独立驱动 `/tmp/mgw-accept-11-engB/independent_mutations.mjs`，原始输出留档 `/tmp/mgw-accept-11-engB/{mut-baseline,expA,expA2,expB,expC1,expC2,determinism,leak,escape}.txt/json`。
- **`data/` 只读**：全程只 `ls -la data/`，未写、未删、未改权限（收工列表与开工一致：`config.yaml` `-rw-------` Sep 24 22:48、`gateway.lock` Sep 22 20:53、`usage/` Sep 28 02:00；我未触碰）。
- **未发起真实上游调用**：所有实验只跑静态门与 `TestClient`/临时目录路径；载荷里的 `base_url` 为 `http://127.0.0.1:9/v1`（副本内自造配置，非真实凭据）；**未重启/未 kill :8300 实例**。
- **并行波动说明**：期间 `git status` 行数与文件 mtime 会因其他面板变动；`/tmp/mg-v2-visible/overview.json` 在 17:30 被并行覆写过一次（§4 末），那不是我的改动，我也未回滚任何人的东西。
- **未验证项**（铁律 2）：
  - 「门在真实浏览器下与 vm 判定一致」——**未验证**（本机 headless Chrome 加载真实页面挂住，见门头注释；本面板仅在 vm 空上下文内复现，未与真实浏览器做交叉对照）。
  - 「17 个清单外模块里存在真死符号」——**未验证**；我只证明了"种进去不会被发现"这一覆盖能力问题。
