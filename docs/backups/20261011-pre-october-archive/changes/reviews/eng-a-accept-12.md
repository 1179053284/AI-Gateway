# 第十二轮 · 资深后端工程师（eng-A）验收：熔断状态机 / 状态文件容错 / 运营互斥 / 时钟口径

> 被验对象：第十一轮 eng-A 自己提的三条阻塞的补做（账本 `docs/changes/e2e-records/E2E-20260928-round5-fixes.md` S-52 / S-53 / S-54）
> 落点：`model_gateway/upstream/zcode/quota.py` + `model_gateway/ops/builtin/zcode_claim.py`
> 纪律：只验收，不改生产代码/测试；实验全部在 `/tmp/mgw-accept-12-engA/`；`data/` 全程只读；不重启 :8300。

## 开工自证

```
$ git status --porcelain | wc -l
85        # 有并行面板在跑，行数会动；以下所有结论只针对我 read-only 验收的两个源文件
$ git log --oneline -1
5158cbc Remove internal spec documents from repository
```

`data/` 只读基线（25 个文件，sha256 清单）：`/tmp/mgw-accept-12-engA/data-sha-baseline.txt`
副本：`rsync -a --exclude data/ --exclude .git/ --exclude .venv/ --exclude __pycache__/` → `/tmp/mgw-accept-12-engA/repo/`

---

## ① 结论

**不通过 —— 2 项阻塞（BLK-A / BLK-B）。**

- **三条被验修复本身全部成立**，且都拿到"改坏就红"的撤修复红证（§3.4 五条变异、无一条"改坏照样全绿"）：
  BLK-1 唯一命名临时文件 = **8.8 万次真并发落盘 × 22.2 万次真并发读，0 坏 JSON / 0 残留**（第十一轮同窗口是 20.6 万次坏读）；
  BLK-2 三态读盘 + fail-closed = 20 类坏形态全部拒跑、整档 30min 挡、不给钟点、给绝对路径、删除文件 0.07 秒放开；
  BLK-3 布尔挡在判数前 = `true`/`false` 判坏且归因带 `repr`，200 次高频判定每种形态**各只 1 条日志**（不零痕迹也不刷屏）。
- **但同一个状态机上还剩两条静默 fail-open 通路，与被验修复同根因、方向相反**：
  **BLK-A** — `_ms_problem()` 的 `float(raw_value)` 类型无差别强转让**数字形态的字符串**与 **JSON 重复键**被判"可信"，
  把常驻进程正熔着的 30 分钟熔断**清零且零日志**，随后一次普通节流写把清零结果回写盘 = S-53/S-54 的原始缺陷复活；
  按项目自己的 `bad_forms` 判据实测**两条红**。
  **BLK-B** — `_save()` 的 `except OSError: pass` / `mkdir` 裸 `return` **一行日志都不留**，
  而 `enter()` 后只要盘上没这个文件，下一次 `active()` 就把"文件不存在=已解除=可信"套到自己头上：
  实测熔断当场蒸发、`_circuit_gate` 返回 None（下一轮继续打风控中的上游）、
  CLI 仍打印「已建立全局熔断：<空原因>」并承诺"后续 30 分钟所有账号停止" = 说了没做（铁律 2/5）。
- 两条都是**一行级修复**，且我已在副本验证 BLK-A 的修法零回归（副本全量 714 passed，唯一 failed 是第十一轮已记录的副本伪红）。
- 三门持平/上涨：pytest **715/715**（第十一轮 705，+10）· 前端门 **84/84**、变异 **可红 104/104**（第十一轮 100）· 后端出口 **12/12**。
- 登记非阻塞 **8 条**（§⑥），新跑坏形态 **33 类**（§⑤，S-34 六类 + S-54 布尔之外的 27 类实测分类）。

---

## ② 三门复跑（逐字）

### 门 1 · pytest（生产仓库，非副本）

```
$ .venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest-12engA -p no:warnings
........................................................................ [ 10%]
........................................................................ [ 20%]
........................................................................ [ 30%]
........................................................................ [ 40%]
........................................................................ [ 50%]
........................................................................ [ 60%]
........................................................................ [ 70%]
........................................................................ [ 80%]
........................................................................ [ 90%]
...................................................................      [100%]
715 passed in 151.12s (0:02:31)
```

**715 passed / 0 failed**（第十一轮记录 705 → +10 条，S-52/S-53/S-54 的新判据都在其中）。

### 门 2 · `scripts/ui_verify_v2_visible.py --mutation`（前端 + 变异自证）

```
$ .venv/bin/python scripts/ui_verify_v2_visible.py --mutation | tail -6
  ✓ 🔴 第十一轮 B11-9：K4 把外链当解析噪声丢掉 —— 管理台里出现远程文档链接（违反铁律 1「纯本地、无远程下发」）门却全绿
========================================================
可红 104/104；每条断言都有对应变异

============================================================
后端出口实测 12 项，通过 12 项，失败 0 项
```

**可红 104/104**（第十一轮记录 100/100 → +4 条新变异）、**后端出口 12/12**。

### 门 3 · 正向跑 + 前端门独立逐字（fixture 落本面板独有目录，避开第十一轮记录的共享路径污染）

```
$ MGW_V2_VISIBLE_DIR=/tmp/mgw-accept-12-engA/visible .venv/bin/python scripts/ui_verify_v2_visible.py | tail -8
  ✓ Z2 执行环境不含 Node 专有全局（名集由宿主派生；派生集本身带 canary）
  ✓ Z3 页面函数对全部判据输入**未抛错**（不许用崩溃冒充证据）

========================================================
实测 84 项，通过 84 项，失败 0 项

============================================================
后端出口实测 12 项，通过 12 项，失败 0 项
```

```
$ node scripts/verify_v2_frontend.mjs /tmp/mgw-accept-12-engA/visible/overview.json | tail -3
========================================================
实测 84 项，通过 84 项，失败 0 项

$ node scripts/verify_v2_frontend.mjs /tmp/mgw-accept-12-engA/visible/overview.json --mutation | tail -3
  ✓ 🔴 第十一轮 B11-9：K4 把外链当解析噪声丢掉 —— 管理台里出现远程文档链接（违反铁律 1「纯本地、无远程下发」）门却全绿
========================================================
可红 104/104；每条断言都有对应变异
```

三门汇总：**pytest 715/715 · 前端门 84/84（变异可红 104/104）· 后端出口 12/12**。

---

## ③ 复验矩阵

### 3.1 BLK-1（S-52）`_save()` 唯一命名临时文件 —— **成立**

判据：两个 writer 子进程 + 两个 reader 子进程真并发跑 12 秒（与第十一轮面板的 12 秒窗口同口径），
reader 每轮既调 `active()` 又裸读 `circuit.json` 做 `json.loads` 并校验键集。

```
$ python run_blk1.py 2 2 12 /Users/w/Desktop/Model-Gateway          # 生产代码
REPO=/Users/w/Desktop/Model-Gateway  run_dir=/tmp/mgw-accept-12-engA/runs/r1790593771929
writers=2 readers=2 duration=12.0s
读者总读次=222121  坏JSON=0  混合内容=0  OSError=0  读者判定 untrusted 次数=0
目录残留非目标文件=[]
固定名 circuit.tmp 残留=False
   {"role": "writer", "seed": "W0", "ops": 43929, ...}
   {"role": "writer", "seed": "W1", "ops": 43947, ...}
   {"role": "reader", "seed": "R0", "reads": 111201, "bad_json": 0, ..., "active_true": 111201, ...}
   {"role": "reader", "seed": "R1", "reads": 110920, "bad_json": 0, ..., "active_true": 110892, ...}
```

**87,876 次真实落盘 × 222,121 次并发读：0 坏 JSON、0 混合内容、0 `untrusted`、目录零残留。**
第十一轮的对照数字是「12 秒读到坏 JSON 206,783 次」—— 同一并发压力下现在为 0，`os.replace` 的原子改名成立。

撤修复（副本 `/tmp/mgw-accept-12-engA/repo/` 把 `mkstemp` 改回固定名 `self.path.with_suffix(".tmp")`，`quota.py:560-570`）：

```
$ python run_blk1.py 2 2 12 /tmp/mgw-accept-12-engA/repo            # 撤修复后的副本
读者总读次=7851  坏JSON=1592  混合内容=0  OSError=0  读者判定 untrusted 次数=1595
   R0 first_bad="JSONDecodeError: Extra data: line 1 column 149 (char 148) | len=149 head='{\"until_ms\": 1790595661676.136, ...'"
```

pytest 同轮红证：

```
$ PYTHONPATH=…/repo pytest -q tests/unit/test_v2_circuit.py tests/unit/test_v2_zcode_quota.py
E  AssertionError: 读到过半写/被截断的状态：['JSONDecodeError: Expecting value: line 1 column 1 (char 0)', ...]
tests/unit/test_v2_circuit.py:1214: AssertionError
WARNING model_gateway.zcode:quota.py:547 熔断状态文件不可信（JSON 解析失败（半写入或被手改坏））且本进程无生效中的熔断 → 本次**不写盘**
1 failed, 78 passed in 1.72s
```

**1 条精确红在命名的那条判据上**（不是"改坏照样全绿"）→ 修复成立。
注：撤修复跑里 reader 读次从 111k 掉到 3.9k —— 固定名让两个 writer 互相抢同一个 tmp，吞吐也被拖垮，这是附带证据。

（下接 BLK-2 / BLK-3）

### 3.2 BLK-2（S-53）三态读盘 + fail-closed —— **主体成立，但存在两处把它打回 fail-open 的洞**

新进程（空内存态）遇上读不动的文件，33 个形态里判坏的那一批全部拒跑（`fresh_active=True`）、
归因可分辨、给绝对路径、不给钟点、整档 30min 挡、拒写、无临时文件残留（逐字见 `badforms_matrix.py` 输出，下表摘录）。

| 形态（文件内容） | fresh `active()` | untrusted | remaining | 给钟点 | 给路径 | `_save()` 拒写 | 残留 tmp | `enter()` 治好 |
|---|---|---|---|---|---|---|---|---|
| `"abc"` / `NaN` / `Infinity` / 超 24h / 缺键 / `null` / `true` / `false` | True | True | 1800.0 | False | True | True | `[]` | True |
| 空文件 / `not json` / 尾巴垃圾 / 顶层 list / 顶层 null / until 是 list / 是 dict / 十六进制串 | True | True | 1800.0 | False | True | True | `[]` | True |
| UTF-16 文件 / UTF-8 BOM / 非法 UTF-8 字节 | True | True | 1800.0 | False | True | True | `[]` | True |
| 路径是**目录** | True | True | 1800.0 | False | True | True | `[]` | **False**（写不下去，见 NB-5） |

`reason()` 实测原文（形态 `{"until_ms": true}`）：

```
ZCode 风控熔断（30min，全局），至 19:45；熔断状态文件读不动（until_ms 被写成布尔值 True，
不是时间戳（盘上键：['reason', 'until_ms']））→ 按熔断拒跑；确认无风控后删除 /private/var/…/circuit.json
```

常驻进程（先 `enter()` 熔着再遇坏文件）：

```
bool_true  -> armed_active=True breaker_kept=True  log_on_change=1 disk_after_mark='覆盖为可读JSON'
empty      -> armed_active=True breaker_kept=True  log_on_change=1
over24h    -> armed_active=True breaker_kept=True  log_on_change=1
numstr_past-> armed_active=False breaker_kept=False ← 🔴 熔断被清零（见 ④ BLK-A）
dup_past   -> armed_active=False breaker_kept=False ← 🔴 同上
```

归因去重（同一坏形态高频 200 次 `active()`）：

```
形态='{"until_ms": true, ...}'  200次判定里的『读不动』条数=1  归因=until_ms 被写成布尔值 True，不是时间戳（盘上键：
形态='{"until_ms": "abc",...}'  条数=1  归因=until_ms 不是数字（str）（盘上键：['reason
形态='{"until_ms": NaN, ...}'   条数=1  归因=until_ms 是非有限数字（NaN/Infinity）
形态='{... reason dict, last_call_ms:"x"}' 条数=1  归因=…断判定不受影响（节流字段单独措辞）
形态='not json'                 条数=1  归因=JSON 解析失败（半写入或被手改坏）
形态='{}'                       条数=1  归因=until_ms 缺少该字段（或被写成 null）（盘上键：无
```

→ **六个形态各自一条、措辞逐类不同、200 次判定不刷成 200 条**（BLK-3 的两个方向都成立）；
`last_call_ms` 坏值只说节流、不把整份状态判死（反向对照 `test_breaker_fields_that_are_only_throttle_stay_benign` 绿）。

### 3.3 BLK-3（S-54）布尔挡在判数之前 —— **成立，但只堵住了七类里的"布尔"这一类**

`quota.py:362-363` 的 `isinstance(raw_value, bool)` 实测把 `true`/`false` 都判坏（上表 7/8 行）。
`repr` 归因实测带上 `True`/`False` 字面量（见上 `reason()` 原文）。
残余洞：**同一行的 `float(raw_value)`（`quota.py:365`）对"数字形态的字符串"仍然放行** → 见 ④ BLK-A。

### 3.4 撤修复实验汇总（三条修复各一次，全部"改坏就红"，无一条"改坏照样全绿"）

副本 `/tmp/mgw-accept-12-engA/repo/`，每轮只改一行，跑 `tests/unit/test_v2_circuit.py + test_v2_zcode_quota.py`（79 条）：

| # | 改坏的那一行 | 结果 | 红的是哪几条 |
|---|---|---|---|
| M1 | `_save()` mkstemp → 固定名 `with_suffix(".tmp")`（`quota.py:560-570`） | **1 failed, 78 passed** | `test_concurrent_saves_never_expose_a_half_written_file`（`读到过半写/被截断的状态：['JSONDecodeError: Expecting value: line 1 column 1 (char 0)']`） |
| M2a | 去掉"未知且无内存熔断则拒写"分支（`quota.py:546-550`） | **1 failed, 78 passed** | `test_mark_called_never_destroys_a_breaker_it_cannot_read`（`tests/unit/test_v2_circuit.py:1130`，"拒写没生效：盘上被覆盖了"） |
| M2b | 去掉"盘上更长者胜"合并（`quota.py:552-555`） | **1 failed, 78 passed** | `test_save_merges_the_longer_breaker_from_disk`（`assert 0.0 == 1790596080245.116`，与账本记录同形） |
| M2c | `active()` 回到"未知=放行"（`quota.py:604`） | **6 failed, 73 passed** | `test_malformed_circuit_numbers_do_not_crash_the_cli` / `test_absurd_until_ms_is_not_shown_as_an_eternal_breaker` / `test_unreadable_breaker_file_blocks_instead_of_releasing` / `test_mark_called_never_destroys_a_breaker_it_cannot_read` / `test_untrusted_state_is_visible_on_the_ui_not_only_in_logs` / `test_cooldown_corrupt_file_blocks_instead_of_releasing` |
| M3 | 去掉布尔分支（`quota.py:362-363`） | **3 failed, 76 passed** | `test_missing_or_null_until_ms_keeps_the_running_breaker` / `test_unreadable_breaker_file_blocks_instead_of_releasing` / `test_untrusted_state_is_visible_on_the_ui_not_only_in_logs` |

M2c 的 diff 逐字（确认副本除这一行外与生产逐字节一致）：

```
$ diff /Users/w/Desktop/Model-Gateway/model_gateway/upstream/zcode/quota.py <副本>/model_gateway/upstream/zcode/quota.py
604c604
<         return self._untrusted is not None or self._cd.active(self._now())
---
>         return self._cd.active(self._now())
```

（M2c 实测 6 条红 > 账本声称的 5 条；M3 实测 3 条红 > 账本声称的 2 条 —— 差值是本轮新增的
`test_untrusted_state_is_visible_on_the_ui_not_only_in_logs` 等判据，方向与账本一致，不是账本造假。）

### 3.5 fail-closed 的反面：坏文件会不会把用户永久锁死（逐条实测）

```
=== ① 新进程（= 重启后第一次判定）===
  [fresh process, 坏文件] rc=0 {"active": true, "untrusted": true, "remaining": 1800.0,
    "reason": "熔断状态文件读不动（until_ms 被写成布尔值 True，不是时间戳（盘上键：['reason','until_ms']））
               → 按熔断拒跑；确认无风控后删除 /var/folders/…/circuit.json 即可解除"}
=== ② 重启后再重启（同一坏文件，多个进程接力）===
  [restart #2] rc=0 active=true  [restart #3] rc=0 active=true  [restart #4] rc=0 active=true
=== ③ 常驻进程最长能保持多久 ===
  常驻进程（真实墙上钟 + 前进钟）： [('+0min', True, 1800.0), ('+1min', True, 1800.0), ('+30min', True, 1800.0)]
  纯真实时间连判 500 次（同一坏文件）：active 恒 True？ True
=== ④ 删除文件 = 立刻放开（真子进程）===
  [deleted 后新进程] rc=0 {"active": false, "untrusted": false, "remaining": 0.0, "reason": ""}
  常驻进程（同一对象，删文件后）active = False reason = '' （耗时 0.07s，无任何等待）
=== ⑤ 闸门文案 + 静默档 ===
  _circuit_gate detail = ZCode 熔断状态文件读不动（…），按熔断拒跑；确认无风控后删除 /var/folders/…/circuit.json 即可解除
  含『剩余约 0 分钟』？ False      给了绝对路径？ True
  sync_circuit_to_runtime → benched=1 skipped=0
  资源状态=cooldown 冷却剩余=1800s last_error="熔断状态文件读不动（until_ms 被写成布尔值 True，…）→ 按熔断拒跑；确认无风控后删除 /var/fol"
  静默档检查：冷却剩余 > 25min → True
```

- **①③④⑤ 逐条符合口径**：未知按整档 30min 挡（不是 bench 0 秒的静默空转）、不给钟点、给绝对路径、
  删除文件 0.07 秒立刻放开、重启仍拒跑（有意的）。
- **"永久锁死"的诚实回答**：常驻进程在文件一直坏时 **没有自动上界**（`remaining_seconds()` 恒返回整档 1800s，
  500 次连判全 True）。这是 fail-closed 的定义而非缺陷，因为①它**只**挡 ZCode 运营闸门 + 启动回写
  （`sync_circuit()` 的触发点只有启动一个，`main.py:493`，故 30 分钟后被 bench 的资源自行回池、**模型转发不受影响**）；
  ②手动出口实测一次删除即放开；③`reason()`/`_circuit_gate`/CLI 三处都把"删哪个绝对路径"说全了。
- **真 CLI 实测**（全量重定向到 /tmp，未碰 `data/`、未打真实上游、未连 :8300）：

```
$ MG_CONFIG=/tmp/mgw-accept-12-engA/cli/config.yaml python -m model_gateway.cli zcode claim
⚠ 熔断状态文件读不动（until_ms 被写成布尔值 True，不是时间戳（盘上键：['reason', 'until_ms']））
  → 按熔断拒跑；确认无风控后删除 /private/tmp/mgw-accept-12-engA/cli/upstream/zcode/circuit.json 即可解除
  —— 本轮未对上游发起任何领取
    状态文件：/private/tmp/…/circuit.json（到点自动恢复；删除该文件可立即放开后续领取，已冷却的资源按其剩余时间自行回池）
rc(坏文件)=3
$ rm -f cli/upstream/zcode/circuit.json && 同命令重跑
rc(删除后)=1
```

  → **④ CLI 明确说删哪个路径 = 成立**；同一条命令只把文件删掉，退出码 3 → 1 = **放开即时**；
  坏文件同屏带"凭据缺失"失败时仍是 3 → **3 优先于 1 无回退**。

| 修复点 | 判据 | 实测命令 | 输出 | 撤修复实验 | 判定 |
|---|---|---|---|---|---|
| BLK-1 `mkstemp` 唯一名 + `fsync` + `os.replace` | 真并发读永不见半写 | `run_blk1.py 2 2 12 <生产>` | 222,121 读 / 87,876 写：**0 坏 JSON、0 混合、0 残留** | M1 改回固定名 → `1 failed, 78 passed`；同 harness 复现 **1592 坏读 / 1595 次 untrusted** | **成立** |
| BLK-2 三态读盘 + `active()` fail-closed + 拒写 + 只延长 | 未知按熔断拒跑、给手动出口 | `badforms_matrix.py` / `phase2.py` / `bypass_probe.py` / 真 CLI | 20 类形态拒跑、整档 1800s、无钟点、给绝对路径、删文件 0.07s 放开、`rc 3→1` | M2a 去拒写 → 1 红；M2b 去合并 → 1 红（`assert 0.0 == 1790596080245.116`）；M2c 未知=放行 → **6 红** | **主体成立，两处洞 → BLK-A / BLK-B** |
| BLK-3 布尔挡在判数前 + 归因逐类不同 + 变化才记一条 | `true/false` 判坏；不零痕迹也不刷屏 | `badforms_matrix.py` / `phase2.py` ② | 6 形态各 1 条日志/200 次判定，归因措辞逐类不同；`last_call_ms` 坏只说节流 | M3 去布尔分支 → `3 failed` | **成立，但类型纪律只做了一半 → BLK-A** |

（下面逐条展开）

### 3.6 「未知则拒写」能否被绕过 + 合并规则能否造成「该解除的解除不了」（`bypass_probe.py`）

```
=== A. 拒写分支的四条绕过路径 ===
  A1 mark_called 拒写： True | 拒写日志条数= 1
  A2 enter() 后盘上内容：until_ms 超前分钟= 30.0 | 熔断还在？ True | 文件恢复可信？ True
  A3 过期内存态 + 未知盘 → 拒写： True
  A4 _save 现读盘（不吃陈旧 _untrusted）→ 写入且保住盘上 5 倍长： 5.0 档
  A5 除 quota.py 之外直接写熔断文件的地方： （无 —— 只有 _save()）

=== B. 合并规则会不会造成『该解除的解除不了』 ===
  B1 过期长熔断残留：active= False  remaining= 0.0  reason= '盘上旧熔断'
  B2 23h 残留 + 新 30min enter → 合并结果超前分钟= 1380.0
     手动出口：删除文件后 active = False
  B3 落盘 until_ms 与 time.time()*1000 同尺度： True | 与 monotonic 无关（monotonic*1000 = 714545171）
```

- **绕过结论**：`enter()` 之后 untrusted 态确实被内存态"掩盖"（A2 允许写盘），
  但写下去的是**一条熔断**而不是"没有熔断"，且读侧立刻恢复可信 → **不构成绕过**；
  A3 证明"内存里熔断已过期"仍走拒写分支；A4 证明 `_save()` 是**现读盘**（`quota.py:544`）而不是吃
  陈旧的 `self._untrusted`，所以另一个进程刚写的 5 倍长熔断被保住；A5 证明没有第二条写盘路径（管理端点/CLI 都不直接改这个文件）。
  **唯一真实的绕过是 BLK-B（写失败静默）与 BLK-A（假可信），不在这四条里。**
- **合并规则不会锁死**：盘上过期长值 → `active()=False` 直接解除（B1）；
  盘上未过期长值（23h，可信窗口内）→ 合并取长 = 1380 分钟，但**上限被 `SANITY_HORIZON_MS` 钉在"现在+24h"**，
  且删除文件当场放开（B2）→ 无"解除不了"状态。
- B3 复核第十轮的时钟口径：落盘是墙钟 `time.time()*1000`，非单调钟（重启不丢）→ 未回退。

### 3.7 第十 / 十一轮已成立项的回退抽查（生产仓库，未改一字节）

```
$ .venv/bin/python -m pytest -q -p no:warnings -k "two_columns or never_shortens or does_not_shorten or wall_clock or read_time or midnight or recomputed or legacy_circuit_file or mid_round_write_failure or scheduler_task_survives or locks_dying_mid_round or refuses or refusal or exit_code or breaker" tests/unit/test_v2_circuit.py tests/unit/test_v2_ops.py tests/unit/test_v2_cli_zcode.py tests/unit/test_v2_zcode_quota.py
................................                                         [100%]
32 passed, 149 deselected in 4.44s
```

覆盖：两列同一瞬间（`test_the_two_columns_never_disagree_about_the_recovery_instant`）、
恢复时刻读时渲染 / 跨午夜 / 不用管理进程钟、`bench()` 只延长不缩短
（`test_bench_never_shortens_an_existing_cooldown` + 额度 tick 不剪熔断）、
锁中途失写不 stranded + 调度任务存活 + `LOCK_REFUSAL_PREFIX` 归因、CLI 退出码与熔断优先。
外加 §3.5 的真 CLI 实测 `rc(坏文件)=3 → 删文件后 rc=1`（3 优先于 1 无回退）。全绿。

---

## ④ 阻塞项（2 条，都是**静默 fail-open**，与被验修复同根因）

### BLK-A（新第八类坏形态）数字形态的字符串 / JSON 重复键 = 可信时间戳 → 把常驻进程正熔着的熔断**清零并回写盘**

**机制**：`_ms_problem()` 用 `float(raw_value)` 做**类型无差别**强转（`quota.py:365`）。
`_save()` 只会写 JSON **数字**，所以 `"1790000000000"`（字符串）与 `{"until_ms": <熔着>, "until_ms": 0}`（重复键，
`json.loads` 后值覆盖前值）都不是"本工具写出来的形态"，但现在都被判**可信**；
`_load()` 见到可信就无条件 `self._cd = disk`（`quota.py:524-525`）→ 常驻进程内存里的 30 分钟被覆盖。

**实测（`phase2.py` ①，常驻进程先 `enter()` 熔着再把文件换成这两种形态）**：

```
numstr_past -> {'armed_active': False, 'breaker_kept': False, 'reason': '覆盖',
                'disk_after_mark': '覆盖为可读JSON', 'until_kept': '{"until_ms": 1790000000000.0, "reason"'}
dup_past    -> {'armed_active': False, 'breaker_kept': False, 'reason': '覆盖',
                'disk_after_mark': '覆盖为可读JSON', 'until_kept': '{"until_ms": 0.0, "reason": "\\u8986\\u76d'}
```

- `armed_active=False` = 闸门开（`_circuit_gate` 走 `return None`）→ 继续打正在风控的上游；
- **熔断被清零这件事零日志**（上面那 1 条 `log_on_change` 是节流字段 `last_call_ms 缺少该字段` 的告警，不是熔断）；
- 随后一次普通 `mark_called()` 把清零结果**写回盘** → 跨进程凭据一并销毁 = S-53 正要堵的方向借两条新通路复活。

**按项目自己的口径判红**（把这两种形态加进 `test_v2_circuit.py:1074` 的 `bad_forms`，生产代码零改动，副本跑）：

```
E  AssertionError: 坏文件把熔断抹掉了：{"until_ms": "1790000000000", "reason": "覆盖"}
E  assert False is True
E  AssertionError: 坏文件把熔断抹掉了：{"until_ms": 1790999999999.0, "until_ms": 0, "reason": "覆盖"}
1 failed
```

**与账本自述的矛盾**：`quota.py:348` 的 docstring 写明判坏形态含「**字符串**」，实测只含「非数字字符串」；
本轮 33 形态矩阵里 `"abc"`/`"0x…"` 判坏、`"1790000000000"`/`"  179059…  "` 却直接可信。

**修复可行性已验证（副本，零回归）**：`_ms_problem` 加 `if not isinstance(raw_value, (int, float))` 类型闸 +
`json.loads(..., object_pairs_hook=_reject_dup_keys)` 拒重复键 →
新加的两条形态**绿**、`test_v2_circuit.py + test_v2_zcode_quota.py` **79 passed**、
副本全量 **714 passed, 1 failed**（唯一 failed 是第十一轮已记录的副本环境伪红 `test_ops_lock_dir_ignores_cwd`）。

### BLK-B `_save()` 失败**零日志** + 空读把刚建立的熔断抹掉 = 熔断当场蒸发

**机制**：`_save()` 的 `except OSError: pass`（`quota.py:573-574`）与 `mkdir` 失败的裸 `return`（`557-559`）
都不留一行日志；而 `enter()` 之后只要盘上文件**不存在**（写失败、或目录不可写），
下一次 `active()` 的 `_load()` 就把「文件不存在 = 已解除 = 可信」（`524-525`）套到自己头上。

**实测（`phase2.py` ④，熔断文件所在目录中途 chmod 0555，S-24 同族故障）**：

```
  A 进程 enter() 后 active = False （内存态）
  A 进程日志： 【零日志】
  circuit.json 是否真的存在： False
  B 进程（同目录另一进程）active = False ← False = 跨进程 fail-open
  B 进程 reason = （空串）
  CLI 会打印的文案： ⚠  / 状态文件：/private/var/…/upstream/zcode/circuit.json
```

闸门单独验证（`bypass_probe` 同族，`zcode_claim._circuit_gate`）：

```
enter() 是否抛错：否（被 except OSError: pass 吞）
盘上文件真的存在吗： False
本进程 active() = False   reason() = ''
日志（本次建立熔断的过程）： 【零日志】
下一轮 _circuit_gate 返回： None（闸门开了 → 会继续打上游）
```

**后果**：`cli_zcode.py:255` 这条路径会打印「⚠ 本轮命中风控，已建立全局熔断：**<空串>**」
并断言「后续 30 分钟内所有 ZCode 账号都会停止领取与转发选中」—— 说了没做（铁律 2/5）；
下一轮运营照打上游，正是 §17 熔断要防的"继续打只会延长风控"。
**同一项目对次要得多的运营报告已有裁决**：写不进去必须打「⚠ 本轮结果未能写入」（S-26④，`cli_zcode.py:241`）；
熔断文件比报告更重要却零措辞，口径不一致。
**修复方向**：`_save()` 失败记 WARNING（带 errno + 绝对路径），CLI 在未落盘时把文案改成"仅本进程生效"。

---

## ⑤ 新发现的坏形态清单（第八类起，33 形态矩阵逐条跑完）

完整原始输出见本轮 `/tmp/mgw-accept-12-engA/`（脚本 `badforms_matrix.py` / `phase2.py` / `bypass_probe.py` / `run_blk1.py`）。按结局分五档：

| 档 | 形态 | 结局 |
|---|---|---|
| ✅ 判坏 → fail-closed（拒跑 / 整档 1800s / 不给钟点 / 给绝对路径 / 拒写 / 零残留 / `enter()` 治好） | `"abc"`、`NaN`、`Infinity`、超 24h、缺键、`null`、`true`、`false`、**空文件**、`not json`、有效 JSON + 尾巴垃圾、顶层 `[1,2,3]`、顶层 `null`、`until_ms` 是 list、`until_ms` 是 dict、`"0x…"` 十六进制串、**UTF-16 文件**、**UTF-8 BOM**、**非法 UTF-8 字节**、**路径是目录**（读侧 `IsADirectoryError`） —— 共 20 类 | 与账本一致 |
| ⚪ 按文件语义接受（值本身是合法 JSON 数字，不构成 fail-open） | `"1790594721139"`（字符串未来值 → 当 10 分钟真熔断挡）、`1.7906e+12` 科学计数、重复键但后值是未来值、`reason` 是 dict/list（`str()` 兜住不崩）、`last_call_ms` 单独坏（只说节流、不判死整份） | 可接受，但类型无纪律 → 见 NB-1 |
| 🔴 **静默 fail-open（BLK-A）** | `"1790000000000"`（数字串指过去）、`{"until_ms": <熔着>, "until_ms": 0}`（重复键后值=过去）、`-1.0`（负数=已过期） | 熔断清零、零日志、并回写盘 |
| 🔴 **写侧静默（BLK-B）** | 目录 `0555`（写不进去 → 零日志 + 内存态被空读抹掉）、路径是**目录**时 `enter()` 静默失败（`enter_heals=False`） | 跨进程 fail-open |
| ⚠ 特殊 | **悬空符号链接** → `FileNotFoundError` 被当成「已解除且可信」：`fresh_active=False`、零日志，且 `enter()` 会**把符号链接本身替换成普通文件**（悄悄改掉用户的目录布局）；`0444` 只读文件 + 可写目录 → 读写都正常（`os.replace` 只看目录权限，POSIX 语义正确，实测 `until_on_disk=30.0`、零残留）；父目录缺失 → `_save()` 的 `mkdir(parents=True)` 自愈 | NB-2 |

`.tmp` 残留同名冲突：`mkstemp` 是 `O_EXCL` + 随机名，33 个形态 × 两趟（fresh/armed）跑完 **`tmp_leftovers` 全部为 `[]`**；
BLK-1 的 12 秒真并发（8.8 万次落盘）也是 `[]`。

---

## ⑥ 非阻塞登记（8 条）

| # | 条目 | 证据 / 落点 |
|---|---|---|
| NB-1 | docstring 与实现分叉：`_ms_problem` 自称判坏「字符串」，实只判「非数字字符串」 | `quota.py:348` vs `quota.py:365`；矩阵 9/10/26 行 |
| NB-2 | 悬空符号链接 = `FileNotFoundError` 被归入「已解除且可信」，与"用户手动删除"不可分辨；且写盘会把链接换成普通文件 | 矩阵 33 行 `fresh_active=False`；可一行修（`os.path.islink(self.path)` 时按未知） |
| NB-3 | `reason` 无长度上限：2 MB 字符串照单全收并写进 `last_error`/日志；`_read_disk` 也无体积上限（每次判定读全文） | 矩阵 23 行 `fresh_remaining=599.9`、`reason` 原样回显 |
| NB-4 | 路径是目录时 `enter()` 静默不生效（`enter_heals=False`），用户按 CLI 提示"删掉这个路径"反而删不掉熔断 | 矩阵 32 行 |
| NB-5 | `left_ms()/left_minutes()` 在 untrusted 态返回 **0**，而 `remaining_seconds()` 返回 **1800** —— 同一"未知"两个尺。今天唯一消费者 `zcode_claim.py:149` 被 `if circuit.untrusted` 提前挡住（实测文案无"剩余约 0 分钟"），但这是给未来调用者留的陷阱 | `quota.py:626-644` vs `630-641`；`phase2` ⑤ `left_minutes=0` 而 `remaining=1800.0` |
| NB-6 | 归因措辞：非法 UTF-8 / BOM / UTF-16 一律归为「JSON 解析失败（半写入或被手改坏）」，把**编码问题**说成**半写入**，会把用户往"并发写坏了"的方向查 | 矩阵 29/30/31 行 reason 原文 |
| NB-7 | 副本环境伪红 `test_ops_lock_dir_ignores_cwd`（editable 安装把子进程解析到仓库、父进程解析到副本）——第十一轮已记录，本轮逐字复现，**非生产缺陷** | 副本全量 `1 failed, 714 passed` |
| NB-8 | 熔断轮里"凭据缺失"的账号在 `_credentials_of` 阶段就返回 `failed`（`zcode_claim.py:175-177`），不走 `_circuit_gate` → CLI 打印成「✗ 失败 1 个」而**不是**「被熔断拦住 1 个」（`cli_zcode.py:280` 的措辞意图），红点也按失败计 | 真 CLI 实测原文见 §3.5 末 |

---

## ⑦ 收工自证

```
$ git status --porcelain | wc -l
      85          # 与开工同一个数；并行面板在跑（任务列表里「完成第七轮修复（S-35~S-54）」仍未完结）

$ find data -type f -exec shasum -a 256 {} \; | sort > data-sha-final.txt
$ diff /tmp/mgw-accept-12-engA/data-sha-baseline.txt /tmp/mgw-accept-12-engA/data-sha-final.txt
  data/ 逐字节未变（25 个文件）           # 全程只读：所有实验写 /tmp，CLI 腿用 MG_CONFIG 重定向到 /tmp/…/cli/

$ shasum -a 256 model_gateway/upstream/zcode/quota.py model_gateway/ops/builtin/zcode_claim.py
1b5298341bc597bba7f584e790834559977cba10c6f154f40881956e5fdbb9fd  model_gateway/upstream/zcode/quota.py
454e48be514712aa87a4cb85e39ea061d10c19d84d67d3c9e0d7c90cbd7bb6b7  model_gateway/ops/builtin/zcode_claim.py
  两文件本轮未被改动（与开工基线一致）→ 我验的就是这份，撤修复实验没有污染生产树

$ git status --porcelain | grep -E "quota.py|zcode_claim.py"
  （无输出 = 这两个文件我一个字节没改）
```

- 我改过的生产树文件：**只有本报告** `docs/changes/reviews/eng-a-accept-12.md`（新建）。
- `git status` 里 `tests/` 的 ` M`/`??` 条目**不是我改的**：开工时就是 85 行、我全程只动 `/tmp/mgw-accept-12-engA/repo/` 副本，
  是并行编码面板 S-35~S-54 的在途改动（本轮所有红证都用 `PYTHONPATH=<副本>` 跑副本，未读写仓库 `tests/`）。
- 未发起任何真实上游调用；未重启/kill :8300；副本实验物保留在 `/tmp/mgw-accept-12-engA/`（`runs/` 有 BLK-1 两轮原始目录）。
