# 第十轮 eng 复验（S-32/S-33 修复无新洞 + 「跨进程/时钟」族再压一遍）

> 角色：资深后端工程师。只验收、未改任何生产代码。
> 实验全部在 `/tmp/mgw-accept-10-eng/`（含仓库副本 `copy/`，`ROOT` 由 `import.meta.url` 推导 → 副本脚本指副本目录）。
> 被验对象：第九轮补做（`docs/changes/e2e-records/E2E-20260928-round5-fixes.md` 文末「第九轮复验的补做」表）的 N-1 / N-2 / cli_probe 判空三处修复。

---

## ① 结论

**有条件通过：0 阻塞。** 第九轮的三处修复本身都成立，没有把 S-28/S-22 打回来：

| 修复 | 复验结论 |
|---|---|
| N-1（`_rendered_last_error` 删 `wall_now`） | **成立且是双层防护**。把 `wall_now` 加回并让生产调用点误传 manager 钟（monotonic），副本实测 `3 failed, 42 passed`：形状判据红 + **两条输出判据也红**。前端门不参与（它吃 JSON fixture，不吃后端渲染）。 |
| N-2（坏值 → 保持内存态 + 告警） | **方向正确，但"坏值"的四种写法仍得到相反结果**：`"abc"`/截断/数组/超 24h 保持内存态（对），`null`/缺 `until_ms` 键/`NaN` **仍把正熔着的熔断静默清零 = fail-open**（C2 实测）。不是本轮引入，但 `_load()` 的注释与第九轮记录的"坏值 = 读不动这份文件：不清零熔断"因此**说过头了**（铁律 2）。→ 非阻塞 R-1，须"补码或改记录"二选一。 |
| N-2 的失效面（会不会永不解除） | **不会**。常驻进程 + 永久坏文件：内存 `until_ms` 是绝对墙钟，过期即 `left_ms=0` → `active()=False`（连续 5 次判定复确认）。最坏保持时长**有界 = 24h**（需文件先给过一个 ≤24h 的合法远值再转坏）。手动出口**有效**：真子进程删文件后立刻 `active=False / reason=''`。 |
| `cli_probe.py` 判空改 `normalize_base_url` | 未回归（本轮未复跑该条，第九轮已撤修复取红证；本次改动面只碰 quota/resources/门，与 probe 无交叉）。**未验证 = 表述为"本轮未复验"，不宣称。** |
| 门的 `new Function` 执行 `api.js`+`dashboard.js` 全文 | **主问 = 红了，可接受**（`window.location`、裸 `location`、`require`、被真使用的 import 绑定 → 全部 K0 红，抛错没被吞）。附带发现三类静默变绿（宿主全局 `process`/`navigator`、注入假件的属性、渲染期不可达函数），属"执行全文"新引入的保真缺口 → 非阻塞 R-2。 |

回归持平：**703 passed**；node 门实测 **79/0**；`--mutation` 可红 **87/87**；后端出口 **12/12**。`find data -newermt "2026-09-28 16:00"` **空**。仓库除本报告零改动。

---

## ② 逐项取证

原始脚本：`/tmp/mgw-accept-10-eng/probe_n2.py`、`probe_f.py`、`gate_probe.py` + 二次全局泄漏批次、`lock_a.py/lock_b.py`。日志里 `熔断状态里的时间戳不合理（… > 现在+24h）→ 视为文件不可信，保持现有内存态，不清零熔断` = `_ms_or_zero` 的 WARNING（quota.py:362）。

### 1. N-2 的新风险面

**1a 常驻网关 + 永久损坏文件 → 熔断永不解除？（判定链走通）**

```
A0 刚 enter:            active=True  left_min=30  reason='ZCode 风控熔断（30min，全局），至 17:05'
A1 文件永久坏（非数字）: active=True  left_min=30          ← 保持内存态（正确，不清零）
A2 内存钟推到 t0+31min: active=False left_min=0  reason='…（30min，全局）'（裸原因，无假钟点）
A3 再推 29 分钟，连续 5 次判定: active=False ×5
```
判定链：`active()` → `_load()`（`_ms_or_zero` 回 `None` → **提前 return，保持内存态**）→ `_cd.active(now)` → `left_ms = max(0, until_ms − now)` → 内存 `until_ms` 是**绝对墙钟**，过期即 0 → False。
**结论：不会永不解除。** 坏文件只让"解除时刻"退化成"内存态自己的时刻"，而那个时刻必然到达。

**1b 用户唯一手动出口 = 删文件（PRD Q28-⑥）→ 真起子进程验**

```
== F. 真子进程常驻（pid=8229）==
CHILD  enter 后: active=True left_min=30 reason='ZCode 风控熔断（30min，全局），至 17:07'
PARENT 文件存在=True 内容={"until_ms": 1790586430271.257, "reason": "...", "last_call_ms": ...}
PARENT 已删除 circuit.json（exists=False）→ 通知子进程重新判定
CHILD  删文件后第1次判定: active=False left_min=0 reason=''
CHILD  删文件后第2次判定: active=False
CHILD  再判定 reason(): ''
CHILD  sync_circuit_to_runtime 出口: circuit.active()=False
```
**结论：出口完好**（`FileNotFoundError` 分支未被 N-2 影响；常驻进程的内存熔断被立刻放开，重启对齐 `sync_circuit_to_runtime` 也跟着静默）。

**1c 时钟回拨 / 前拨跨 24h 边界 + 合法/坏值边界**

| 场景 | 实测 |
|---|---|
| 回拨 2h（内存正熔 30min） | `active=True left_min=150` → **熔断被拉长**（fail-**closed**，有界），钟恢复后回 `left_min=30` |
| 现在比 `until_ms` 早 25h（即前拨 25h 视角） | WARNING + 保持内存态 → `active=True`，`left_min=1530`（复打数字，报告初稿写 ≈1500） |
| 读方进程钟比写方快 25h | `until_ms` 落在"过去"→ 合法 → `active=False left_min=0` = 提前放行（墙钟语义固有，回拨族不可免，有界 ≤30min+钟差） |
| `until_ms` = now+**23h59m** | `_ms_or_zero` 回数值 → `active=True left_min=1439`，界面 `r，至 明日 16:34`（合法） |
| now+**恰好 24h** | `active=True left_min=1440`（比较是严格 `>`，边界按合法收） |
| now+**24h01m** | `None` → 坏值 → 保持内存态 |
| `-1e15`（负数） | **合法**（无下限校验），`active=False` → 无害，但界面 `reason()` 回裸原因 `'r'` |

**1d `mark_called()` 在坏文件下写回什么（归一化 vs 污染）**

```
E1 内存正熔 + 文件坏（"until_ms":"abc"）→ mark_called 落盘:
   {"until_ms": 1790586334505.961, "reason": "ZCode 风控熔断（30min，全局）", "last_call_ms": 1790584534505.961}
```
**归一化**（不是污染）：坏字符串被内存态的合法 float 替换，`reason` 仍是裸原因，无「，至」尾巴。测试 `test_v2_circuit.py:578-580` 钉的就是这条。

**1e 新发现的同族两处（第九轮未覆盖，非本轮引入）**

- **R-1 坏值判定的四种写法不一致（fail-open 残留）**
  ```
  == C2. 常驻进程内存正熔着，文件被改成不同坏值 ==
    非数字      → 改前 True 改后 True   保持（正确）
    null        → 改前 True 改后 False  被清零 = FAIL OPEN
    缺 until_ms 键 → 改前 True 改后 False 被清零 = FAIL OPEN
    until_ms=0  → 改前 True 改后 False  （语义上=文件说没熔断，可接受）
    顶层数组     → 保持（正确） / JSON 截断 → 保持（正确）
    NaN         → 改前 True 改后 False  被清零 = FAIL OPEN
    超 24h      → 保持（正确）
  ```
  根因两行：`_ms_or_zero` 的 `float(raw_value or 0)` 把 **None/缺键归 0**（其 docstring 自己还写着"None … 当 0"，quota.py:344-349 未随 N-2 更新）；`NaN > horizon` 恒 False 且 NaN 为真值 → 绕过**唯一**的上限比较。
  可达性：全仓库 `_save()` 是唯一写者且原子写，`null`/缺键/`NaN` 只能来自**人用手改文件**或外来工具；而 CLI 明确把该文件路径印给用户作手动出口（`cli_zcode.py:252/260`），"改数字而不是删文件"是同一动机的邻动作。
  最小修法（≤3 行，不回退既有红证）：`if raw_value is None: return None`；`import math` 后 `if not math.isfinite(v) or v > horizon: return None`；顺手把 docstring 的"None 当 0"改掉。
- **R-2 读侧拒绝 + 写侧无条件覆盖 = 抹掉别的进程的熔断**
  ```
  E2 前置：别进程写 until_ms=now+25h（被判坏值），本网关 active=False
  E2 mark_called 落盘 → {'until_ms': 0.0, 'reason': '', 'last_call_ms': ...}
        他进程熔断还在吗：没了（被抹掉）
  ```
  `mark_called()`（quota.py:527-529）**不 `_load()`**，直接拿内存态整份 `_save()`；它在领取主路径上（`ops/builtin/zcode_claim.py:183`，紧接 `throttle_wait_ms()`）。于是 N-2 在读侧"保持内存态、不清零"的收益，被写侧的整盘覆盖抵消：文件里真实存在但他进程钟差导致越界的熔断会被 0 抹掉，跨进程凭据消失。
  最小修法：`mark_called()` 先 `_load()`；若仍读不动则**只更新 `last_call_ms`**（读原文件 dict 改写该键后原子替换），或至少 `logger.warning("将覆盖一份读不动的熔断状态")` 让它可见。

### 2. S-33 形状判据的有效性（除了签名判据还有没有第二道防线）

**有，而且已经实测到了。** 在副本 `copy/model_gateway/core/resources.py` 施加三处变异：签名回加 `wall_now: float | None = None`、渲染改 `wall = (time.time() if wall_now is None else wall_now)`、生产调用点传 `self.clock() * 1000`（monotonic）。

```
变异已施加：签名回加 wall_now + 生产调用点传 manager 钟
（import 自检：/private/tmp/mgw-accept-10-eng/copy/model_gateway/core/resources.py）
3 failed, 42 passed in 0.11s
  FAILED test_recovery_clock_is_rendered_from_the_wall_clock_not_the_manager_clock
  FAILED test_the_two_columns_never_disagree_about_the_recovery_instant
  FAILED test_recovery_clock_renderer_has_no_injectable_wall_clock
```
第二道防线的**机制**（为什么输出判据也抓得到）：这两条**故意不注入时钟**，用 `ResourceManager()` 生产默认钟（并断 `mgr.clock.__name__ == "monotonic"`，:503），期望值取 `time.strftime("%H:%M", time.localtime(time.time() + rem_s))`，外加反向断言 `not row["last_error"].endswith(strftime(localtime(st.cooldown_until)))` —— 假钟点必然落在这两条的射程内（tests/unit/test_v2_circuit.py:484-516、:519-545）。
另外形状判据的 `set(params) == {"entries","status","remaining_ms"}` 把"换个名字再加回来"也一起钉死了。
前端门（K6/C16）对此**无判断力**：它吃 `overview.json` fixture，`last_error` 是后端渲染结果 → 结论：防线是"形状 + 两条输出"，不是门。

### 3. 门改动（`new Function` 执行 `api.js`+`dashboard.js` 全文）的降级方式

副本基线：`实测 79 项，通过 79 项，失败 0 项`（rc=0）。十个变异：

| 变异 | 门结果 | 判定 |
|---|---|---|
| M3 `api()` 内 `window.location.href`（渲染期必经） | rc=1，红 10 条（K0/K7/K1/K2/K3/K8/K4/K5/K6…） | **红 = 可接受** |
| M6 import 的绑定在渲染期真被用 | rc=1，`✗ K0 … ReferenceError: esc is not defined` | 红 |
| M7 顶层裸 `location.href`（Node/浏览器都没有） | rc=1，`✗ K0 … ReferenceError: location is not defined` | 红 |
| M9 顶层 `require('fs')` | rc=1，`ReferenceError: require is not defined` | 红 |
| **M2 顶层 `navigator.userAgent`** | rc=0，79/79 **全绿** | ★ 静默变绿 |
| **M8 顶层 `process.pid`（Node 独有，浏览器必炸）** | rc=0，79/79 **全绿** | ★ 静默变绿 |
| **M10 顶层 `document.cookie`（注入假件无此属性 → undefined 不抛）** | rc=0，79/79 **全绿** | ★ 静默变绿 |
| M1/M5 **未被使用**的单行/多行 `import` | rc=0 全绿（`toModuleBody` 把 import 剥掉） | 静默但生产无害 |
| M4 只加一个渲染期不被调用的函数（内部用未注入全局） | rc=0 全绿 | K 段固有覆盖范围（S-30 只补 `renderDashboard` 可达面） |

**结论**：任务问的那一档（新增 import / `window.location` 这类未注入全局）**是红的** —— 抛错没被吞：`renderPage` 的 `catch` 把 `name/message` 记进 `renderErr`，K0/K7 的 detail 直接把它当判据打印。
但"执行全文"确实**新增**了一个静默面：**宿主全局泄漏**（Node 的 `process`/`navigator`/`structuredClone`/`setTimeout` 等对模块体可见）与**假件属性缺失只回 `undefined`**。生产里 api.js 若依赖 `navigator.clipboard` 之类的浏览器 API，门既不会红也测不到可用性。→ 非阻塞 **R-3**，最小修法：把 K 段的 `new Function` 换成 `node:vm.runInContext(src, ctx)`，`ctx` 只放 `fetch/document/window/localStorage` 四个注入项（或给全局读加 Proxy，`has` 未知标识符 → 抛）。改动局限在 `renderPage()` 内 ~10 行，不动任何判据字面量。

### 4. 回归

```
.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest-10 -p no:warnings
  → 703 passed in 128.47s            （第九轮 703 → 持平，S-32/S-33 没吃掉任何判据）
node <副本>/scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json
  → 实测 79 项，通过 79 项，失败 0 项
.venv/bin/python scripts/ui_verify_v2_visible.py --mutation
  → 可红 87/87；每条断言都有对应变异
  → 后端出口实测 12 项，通过 12 项，失败 0 项
find data -newermt "2026-09-28 16:00" -type f
  → （空）＝ 未污染用户数据目录；data/ops-locks 在本机不存在（只读 ls，未创建）
```

### 5. 第九轮 eng 留下的另外 4 条非阻塞（逐条：在不在 / 要不要升级 / 最小修法）

| # | 现在还在不在（实测） | 要不要升级为阻塞 | 最小修法 |
|---|---|---|---|
| **probe 写失败分支无自愈** | **语义需修正**：`usable()` 无状态、每轮重探（runner.py:430 开局 + :448 每次 `try_acquire()` 回 False 后再探）→ 可写性恢复即自动恢复，**没有"不自愈"**。真正残留的是陈旧 `.write-probe.lock`：实测正常路径写后 unlink 成功、`exists=False`；只有进程被 kill 在两步之间才留文件，且下次 `write_text` 覆盖写，永不错挡 | **不升** | 什么都不做（或洁癖：`_try_create` 的超龄回收顺带带上 `.write-probe.lock`） |
| `.write-probe.lock` 权限 0644 泄露 pid+token | **还在**。实测同一调用（`Path.write_text`）：`mode=644`、内容 `9999 deadbeefdeadbeef` 全局可读；对照账号锁 `os.open(...,0o600)` → `acct-a.lock mode=600`。泄的是 pid + 本进程 `_LOCK_TOKEN`（`secrets.token_hex(8)`，runner.py:75），该 token 参与 `_release_file` 的双条件授权 | **不升**（同机可读该目录的攻击者本来就有写权限；token 是进程随机数，跨轮无效） | `usable()` 换成 `os.open(probe, O_CREAT\|O_TRUNC\|O_WRONLY, 0o600)` + `os.fdopen`，与 `_try_create` 同尺（1 行口径统一，去掉 600/644 不对称） |
| `data/ops-locks` 不入保留清理 | **还在**。`_cleanup_old_files` 覆盖面是 `m in ("events","switch-events","ops-results")` 且 `suffix==".jsonl"`（stats/events.py:82-112），整目录压根不看锁目录；`LOCK_MAX_AGE_S=15min` 的超龄回收只在**下一次同账号抢锁**时触发，删掉的账号/从未再跑的账号留下的 `.lock` 永不清理 | **不升**（数量被账号数上界约束，无增长面） | 保留清理里加一条"锁目录下 mtime > N 天**且 pid 不存活**（复用 `_pid_alive`）的 `*.lock` 才删"。⚠️ 必须先判存活：无脑删就是把下面那条变成产品内自伤 |
| 第三方删锁 = 互斥静默失效且零日志 | **还在，真双进程实测**：A（pid 13125）持有 `acct-c` → 第三方 `unlink` → B 新进程 `try_acquire("acct-c") = True`（**双领窗口成立**），B 侧日志 **0 条**，A 全程不知情。单进程复现会被 `_HELD_BY_US`（runner.py:71）挡住，故本轮改真子进程 | **不升**（需外部删除者；产品内无删除者 —— 第九轮 F1 + 本轮 events.py 覆盖面复核一致） | 比 N-3 的 inode 方案轻两处：① 领取结束在 `finally` 里校验 `_path(account)` 仍在且 token 匹配，不匹配 → `logger.warning("运营锁被外部删除")` + 该账号标 `failed`（复用 S-29 已建立的"未发起"分级文案与红点/退出码）；② 或开局记 `lock_dir` 的 `st_ino/st_dev`，中途变化即整轮按互斥被摧毁处理 |

---

## ③ 阻塞项

**0。**

（列两条我判定为"必须处理但不阻塞"的，附最小复现，交由下一轮或用户裁决方向；二者都**不是**第九轮修复引入的回归，而是同族里未覆盖的写法。）

- **R-1（fail-open 残留 + 记录说过头）**
  最小复现：`python` 里 `cm = CooldownManager(path); cm.enter("r")`（active=True），把同一 path 写成 `{"until_ms": null}` 或 `{"last_call_ms": 1}`（缺 `until_ms`）或 `{"until_ms": NaN}`，再 `cm.active()` → **False**。对照写成 `{"until_ms": "abc"}` → **True**。
  为什么不算阻塞：全仓库唯一写者 `_save()` 原子写且从不产出这三种形态；触发前提是人改文件；且 `null`/缺键可辩护为"文件明说没熔断"。**但** `_load()` 的注释与第九轮记录把它说成"坏值一律保持内存态"，与代码不符 → 要么补 `math.isfinite` + `None → return None`，要么把注释/记录改成"仅非数字与越界判坏"。
- **R-2（`mark_called` 覆盖越界熔断）**
  最小复现：文件写 `{"until_ms": <now+25h>, "reason": "别进程"}`，`CooldownManager(path)`（内存空）→ `active()=False` → `mark_called()` → 文件变 `{"until_ms": 0.0, "reason": ""}`（实测 E2）。
  为什么不算阻塞：前提是别的进程写出 >24h 的值，即需要 >23.5h 的钟差；`enter()` 自己只写 now+30min。修法 1 行（`mark_called` 先 `_load()`）。

---

## ④ 非阻塞处置建议（按性价比排序）

1. **R-1**：`_ms_or_zero` 加 `raw_value is None → None` + `math.isfinite(v)`，并同步 docstring/第九轮记录的口径（0.5 人时，能顺带补两条变异红证）。
2. **R-2**：`mark_called()` 先 `_load()`（或改为"读原文件只换 `last_call_ms` 键"），让"保持内存态"在读侧的收益不被写侧抵消。
3. **R-3（门的宿主全局泄漏）**：K 段 `new Function` → `node:vm` + 白名单沙箱（`process`/`navigator` 之类从此为红）。
4. `usable()` 的探测文件与账号锁同尺（0600），去掉 600/644 不对称。
5. 锁的"外部删除"检测：`finally` 里校验 token 匹配 → WARNING + `failed`（复用 S-29 分级文案）。
6. 保留清理扩到 `ops-locks`，但**必须以 pid 存活为前置**。
7. 记录修正：第九轮「坏值 = 读不动这份文件」应限定为「非数字/越界」；`until_ms` 无下限校验（负数被当合法，当前无害）也值得一句注记，免得下轮当成新洞。

---

## ⑤ 打破不了的清单（本轮试过且没打穿的）

1. **常驻 + 永久坏文件把熔断锁死**：打不出来。内存 `until_ms` 是绝对墙钟，过期必放开（A2/A3 连续 5 次 `active=False`）；最坏保持 24h 有界（B3/B4）。
2. **删文件解除不了**：打不出来。真子进程 pid 8229 实测立刻 `active=False / reason='' / left_min=0`，`FileNotFoundError` 分支未被 N-2 触碰。
3. **只靠形状判据护 `wall_now`**：打不出来。删掉形状判据也不会放过误传 monotonic —— 两条输出判据（生产默认钟 + 反向断言）同样红（实测 3 failed）。
4. **让门对"未注入全局"静默放行**：主路径打不出来（`window.location`/裸 `location`/`require`/被使用的 import 绑定 → 全 K0 红，抛错进 `renderErr` 并被打印）。只在 Node 独有全局与假件属性缺失两处变绿（→ R-3，属沙箱保真度而非本轮判据设计）。
5. **`mark_called` 把坏值写回盘（污染）**：打不出来。落盘始终是归一化 float + 裸原因（E1）。
6. **S-22 的 fail-closed 取向被本轮改动翻案**：没有。坏文件下界内行为一律朝"保持熔着"偏（回拨 → 熔断拉长；越界 → 保持内存态），未观察到"锁永挡"或"整站不可用"。
7. **回归缩水**：703/703、87/87、79/0、12/12 与第九轮记录逐项一致，无一项缩水。

---

## ⑥ 证据时效与并发说明（本轮自查）

- 本会话期间仓库有**并行面板在写**：`docs/changes/reviews/pm-accept-10.md`、`ix-accept-10.md` 于 16:2x 后出现，`scripts/verify_v2_frontend.mjs`（16:24:18）与 `tests/integration/test_int_v2_frontend_gate.py`（16:24:48）也被他人改过。
- 我的全部证据都取在**这些改动之后**：副本 rsync 于 16:33，门基线/变异、pytest、ui_verify 均在其后跑。终局 `diff` 复核：仓库 vs 副本的 `verify_v2_frontend.mjs`、`quota.py`、`core/resources.py`、`api.js` **逐字节无差异**（副本里的 wall_now / api.js 变异均已回滚，仓库对应文件从未被写入）。
- 我净写入仓库的文件只有本报告。`git status --porcelain` 条数开局/收尾同为 **82**；`find data -newermt "2026-09-28 16:00" -type f` **空**；除报告外仅 `.pytest_cache/`、`__pycache__/*.pyc`（gitignore 内，非源码改动）。
- 待下一轮注意：若并行面板在本报告之后又动了门脚本，本文的门侧数字（79/87/12）需以新 tip 重跑为准。
