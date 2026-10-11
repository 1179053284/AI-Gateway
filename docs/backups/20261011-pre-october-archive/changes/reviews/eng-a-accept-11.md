# 第十一轮验收 · 后端工程师面板 A（熔断状态机 / 状态文件容错 / 运营互斥 / 时钟口径）

> 只验收、未改任何生产代码或测试文件（收工自证见 §⑥）。
> 实验全部在 `/tmp/mgw-accept-11-engA/`（`p1b_quota.py` / `p2_cli.py` / `p2d.py` / `p3_ops.py` /
> `p4_clock.py` / `p5_direction.py` / `p6_run.py` / `p8_race.py` / `p10_cli.py` / `mutate.py` /
> 副本 `copy/`（rsync 排除 `data/` `.git/` `.venv/`））。仓库 `data/` 全程只读。
> 运行态：`:8300` 本轮**无监听**（`lsof -nP -iTCP:8300 -sTCP:LISTEN` 空）→ 用户的网关实例未被触碰；
> 界面出口用自有端口的真实装配（P6，127.0.0.1:8411）与 `TestClient` 等价路径复现。

---

## ① 结论

**不通过 —— 阻塞 3 条。**

三条都不是"第十轮修复没做到"（S-34 的行为面确实做到了，撤修复有红证），而是同一族里**仍未封死的两个方向**
加上一条**本轮新查到的坏文件生产路径**：

| # | 一句话 | 方向 | 触发要不要"人手改文件" |
|---|---|---|---|
| **BLK-1** | `_save()` 的临时文件名是**固定**的（`circuit.json.tmp`），两个进程并发落盘会互相截断 → 实测 12 秒内**读到坏 JSON 206,783 次 / 混合内容 20,351 次** | 造出坏文件本身 | **不需要**：网关 cron 与 CLI 各领不同账号、同时命中 3012/同时记账即可 |
| **BLK-2** | 文件"读不动/不可信"时：**新进程一律按"无熔断"放行**，随后 `mark_called()` **无条件整盘覆盖** → 跨进程熔断凭据被销毁，且常驻进程下一次判定也跟着清零；CLI 打「全部正常，无需处理」+ rc=0 | **fail-open** | 需要坏文件存在（BLK-1 让它自己出现） |
| **BLK-3** | `until_ms` 写成布尔 `true`/`false`：`float(True)==1.0` 是合法值 → **常驻进程内存里正熔着的熔断被清零**，零日志（S-34 六类之外的第七类） | **fail-open** | 需要（一次最常见的误改：把数字改成布尔） |

面板指令「坏数据任何 fail-open 都是阻塞级」+ 用户裁决 S-22「宁可拒跑也不冒险」→ 三条均按阻塞登记。

第十轮补做的四条**主体成立**（逐条复验矩阵见 §③，撤修复红证齐全）：

| 修复 | 结论 |
|---|---|
| `_ms_or_zero` 缺键/`null`/非数字/`NaN`/`Infinity`/>24h → `None`，`_load()` 见 `None` 保持内存态 | **行为成立**（常驻进程 13 种坏形态全部保住熔断，`active()` 无一例外为 True）；但"并 `logger.warning`"这一半**只对 3 类成立**（缺键/`null`/越界），其余 10 类零日志；且 `last_call_ms` 坏值/缺键会打出**语义错误**的"文件不可信"告警（NB-2/NB-3） |
| `last_call_ms` 坏值归 0（只影响节流） | **成立**，实测不清零熔断、不抛错 |
| 恢复时刻读时渲染 + 无可注入时钟 | **成立**：`_rendered_last_error` 形参恰为 `{entries,status,remaining_ms}`；`wall = time.time()`（resources.py:215）；两列实测说同一瞬间；把 `wall_now` 加回签名 → 形状判据红；把钟点改成单调钟/与剩余列分叉 → **三条输出判据同时红** |
| `usable()` / `PlanLock` / `LOCK_REFUSAL_PREFIX` fail closed | **成立**：开局不可写 = 整轮 0 发起 + 全部 `failed` + 落盘 + 红点 3；中途失写 = 其余账号 `failed` 而非 `skipped`；`_tick` 正忙（静默、errors 不涨）与不可用（errors+1 + 2 条日志）分得开；锁目录被文件占住也拒；不退 `/tmp` |
| CLI 分级与退出码 | **成立**：0/1/2/3 实测齐；`3` 优先于 `1`（熔着 + 拒跑同屏 → rc=3）；`refused` 抬头区分"未发起"；数据目录不可写时 ⚠「本轮结果未能写入」实测打出 |

回归持平：**705 passed**（第十轮记录 705）；前端门 **81/81**、`--mutation` **可红 100/100**；后端出口 **12/12**。

---

## ② 三门复跑输出（逐字）

```
$ .venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest -p no:warnings
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
705 passed in 135.96s (0:02:15)
```

```
$ .venv/bin/python scripts/ui_verify_v2_visible.py --mutation | tail -3
========================================================
可红 100/100；每条断言都有对应变异

============================================================
后端出口实测 12 项，通过 12 项，失败 0 项
```

```
$ .venv/bin/python scripts/ui_verify_v2_visible.py | tail -8
  ✓ Z1 可见性判据按**属性语义**认：`class="… hidden"` 不算隐藏，真属性/裸属性/大写都算
  ✓ Z2 执行环境不含 Node 专有全局（浏览器里不存在的东西，门里也不许存在）

========================================================
实测 81 项，通过 81 项，失败 0 项

============================================================
后端出口实测 12 项，通过 12 项，失败 0 项
```

```
$ node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json | tail -2
========================================================
实测 81 项，通过 81 项，失败 0 项

$ node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json --mutation | tail -2
========================================================
可红 100/100；每条断言都有对应变异
```

副本环境说明（**不是生产缺陷**，后面所有副本侧数字都要按此折算）：
`tests/unit/test_v2_servable.py::test_ops_lock_dir_ignores_cwd` 在副本里**基线即伪红**，
原因是该用例用 `sys.executable` 起子进程且只传 `PATH/HOME`（无 `PYTHONPATH`）→ 子进程按 editable 安装解析到
**仓库**、父进程按 `__file__` 解析到**副本**；同轮副本基线逐字：
`1 failed, 702 passed, 2 skipped in 126.34s (0:02:06)`。§③ 的红证条数已把这 1 条扣掉。

---

## ③ 复验矩阵（修复点 / 复现命令 / 实际输出 / 撤修复红证）

### 3.1 `quota._ms_or_zero` + `_load()`（S-34）

**复现**：`cd /tmp/mgw-accept-11-engA && /Users/w/Desktop/Model-Gateway/.venv/bin/python -u p1b_quota.py`
（22 种 `circuit.json` 形态，每例先把内存熔断复位成 `SENTINEL`，再判定一次并计日志）

常驻进程（内存正熔着 30min）实测（`active` / 左 / 日志条数 / 内存态是否保住）：

```
01 空对象 {}（缺 until_ms）      True 30 日志1 保持内存态  reason='SENTINEL-真熔断，至 18:03'
02 until_ms=null               True 30 日志1 保持内存态
03 until_ms="abc"              True 30 日志0 保持内存态        ← 静默
04 until_ms=NaN               True 30 日志0 保持内存态        ← 静默
05 until_ms=Infinity          True 30 日志0 保持内存态        ← 静默
06 until_ms=-Infinity         True 30 日志0 保持内存态        ← 静默
07 until_ms=1e400（→inf）      True 30 日志0 保持内存态        ← 静默
08 until_ms=now+25h（越界）    True 30 日志1 保持内存态  [WARNING] 时间戳不合理（… > 现在+24h）
10 JSON 截断                   True 30 日志0 保持内存态        ← 静默
11 顶层数组                    True 30 日志0 保持内存态        ← 静默
12 非 UTF-8 字节               True 30 日志0 保持内存态        ← 静默
13 顶层 null                   True 30 日志0 保持内存态        ← 静默
22 空文件（0 字节）            True 30 日志0 保持内存态        ← 静默
14 until_ms=true（布尔）       False 0  日志0 ★被文件覆盖 = 熔断清零（BLK-3）
16 until_ms=-1e15（负数）      False 0  日志0 ★被文件覆盖（可辩护为"文件说没熔"）
17 until_ms=0                 False 0  日志0 ★被文件覆盖（同上）
18 合法正熔 + 缺 last_call_ms  True 30 日志1 ★被文件覆盖（正确！）
                                 却打 [WARNING]「视为文件不可信，保持现有内存态，不清零熔断」（NB-2）
19 合法正熔 + last_call_ms="abc" True 30 日志0 ★被文件覆盖（正确，节流归 0）
```

`last_call_ms` 半区（`test_breaker_fields_that_are_only_throttle_stay_benign` 的口径）实测：
`19/20` 熔断照旧 `active=True`、`reason` 保留、`throttle_wait_ms()` 归 0（`p1b` B 段：`throttle=0ms`）→ **成立**。

**撤修复红证**（`bash /tmp/mgw-accept-11-engA/run_mutations.sh`，逐字）：

```
M1_None归0 → quota.py        FAILED test_missing_or_null_until_ms_keeps_the_running_breaker
                             1 failed, 130 passed in 30.82s
M2_去掉NaN/Inf守卫           FAILED test_missing_or_null_until_ms_keeps_the_running_breaker
                             1 failed, 130 passed in 30.94s
M3_非数字归0                 FAILED test_malformed_circuit_numbers_do_not_crash_the_cli
                             FAILED test_missing_or_null_until_ms_keeps_the_running_breaker
                             2 failed, 129 passed in 31.59s
M4_None分支不留日志          FAILED test_missing_or_null_until_ms_keeps_the_running_breaker
                             1 failed, 130 passed in 30.78s
M5_去掉24h上限               FAILED test_absurd_until_ms_is_not_shown_as_an_eternal_breaker
                             1 failed, 130 passed in 30.58s
M6_load不再保持内存态        FAILED test_malformed_circuit_numbers_do_not_crash_the_cli
                             FAILED test_absurd_until_ms_is_not_shown_as_an_eternal_breaker
                             FAILED test_missing_or_null_until_ms_keeps_the_running_breaker
                             FAILED test_claim_under_global_breaker_exits_3
                             4 failed, 127 passed in 30.55s
```

**但"修法不可见"实验证明判据对我新报的三条毫无判断力**（`bash run_fixvis.sh`，全量 705 面）：

```
F1_布尔也判坏（isinstance(raw_value, bool) 也返回 None）
   1 failed, 702 passed, 2 skipped in 127.97s      ← 与副本基线逐字相同
F2_静默坏值也留日志（非数字分支加 logger.warning）
   1 failed, 702 passed, 2 skipped in 127.41s      ← 同上
F3_mark_called先回读（self._load() 再存）
   1 failed, 702 passed, 2 skipped in 126.31s      ← 同上
F4_mark_called只改节流键（读原 dict 只换 last_call_ms）
   1 failed, 702 passed, 2 skipped in 126.59s      ← 同上
副本基线（未变异）
   1 failed, 702 passed, 2 skipped in 126.34s
```

⇒ 这四类改动**判据完全看不见**（红/绿逐字不变）。补一条独立判据文件（不在仓库里）当场打红：

```
$ /Users/w/Desktop/Model-Gateway/.venv/bin/python -m pytest -q /tmp/mgw-accept-11-engA/counter/test_new_holes.py
FAILED test_bool_until_ms_must_not_clear_the_running_breaker
FAILED test_untrusted_shapes_must_leave_a_log_line
FAILED test_a_readable_file_must_not_be_called_untrusted
FAILED test_mark_called_must_not_erase_a_breaker_it_could_not_read
4 failed in 0.05s
```

### 3.2 恢复时刻读时渲染 / 两列同一瞬间（S-23/S-28/S-31/S-33）

**复现**：`python -u p4_clock.py`（`ResourceManager()` 生产默认钟，不注入任何时钟）

```
_rendered_last_error 形参 = ['entries', 'status', 'remaining_ms']        ← 无可注入时钟
quota.until_label 形参 = ['until_ms', 'now_ms'] / _with_until = ['reason','until_ms','now_ms']
生产 CooldownManager 的钟 = _epoch_ms（time.time()*1000）

行：status=cooldown 冷却剩余=1799999ms 最近错误='上游限流，冷却中，至 18:01'
按同一瞬间应为「至 18:01」 → 一致：True
快照耗时 0.02ms（两列取自同一次 pass）
单调钟假钟点 13:07 是否出现在界面：False
过期后：status=active 冷却剩余=0 最近错误='上游 429'（含「至」？ False）
跨午夜：23:50+1800s→明日 00:20 ｜ 23:59+120s→明日 00:01 ｜ 00:10+1800s→00:40 ｜ 12-31 23:50+1800s→明日 00:20
落盘 reason='ZCode 风控熔断（30min，全局）'（含钟点？ False）→ 读时 '…，至 18:12' → 一小时后/过点后回裸原因
```

`normalize_base_url` 同源性（P4 F/G）：`None/""/"  "`→`""`；`…/v1/`、`…/v1//`、`" https://x.test/v1 "` 全部→`https://x.test/v1`；
`main.py` 内**没有**裸 `rstrip("/")`（打印 `False`），四处调用点全部 `normalize_base_url`（main.py:235/238/243）；
指纹：尾斜杠同=True、前后空白同=True、换 Key 同=False。全仓另一处 `site_root.rstrip("/")`（captcha.py:108）
作用的是**模块常量** `SITE_ROOT`（`_plan_endpoint` 返回它，不读配置）→ 不构成口径分叉。

**撤修复红证**（`bash run_res_mut.sh`，目标 `test_v2_circuit.py + test_int_v2_circuit_boot.py`）：

```
M7_把wall_now加回签名        FAILED test_recovery_clock_renderer_has_no_injectable_wall_clock
                             1 failed, 50 passed in 1.95s
M8_钟点用单调钟（wall=time.monotonic()）
   FAILED test_health_card_renders_the_clock_at_read_time
   FAILED test_recovery_clock_is_rendered_from_the_wall_clock_not_the_manager_clock
   FAILED test_the_two_columns_never_disagree_about_the_recovery_instant
   3 failed, 48 passed in 1.80s
M9_钟点与剩余列分叉（remaining_ms×2）
   同 3 条 FAILED，3 failed, 48 passed in 1.80s
```
前端门对这三型**没有判断力**（它吃 `overview.json` fixture，`last_error` 是后端渲染结果）——与第十轮结论一致；
但门自己的 `--mutation` 表里有 B-7a「恢复时刻被搬到冷却剩余列」→ 红（本轮实测 `✓ 🔴 第九轮 B-7a … 可红 100/100`）。

### 3.3 `ops/runner.py` 互斥 fail closed（S-22/S-24）

**复现**：`python -u p3_ops.py`

```
A. 开局锁目录 0500：发起过的账号 = []（应为空）
   failed=3 skipped=[]  首条='运营互斥锁目录不可写：… —— 跨进程互斥建立不起来，本轮未对任何账号发起操作（宁可拒跑也不双领）…'
   前缀匹配 LOCK_REFUSAL_PREFIX：True   日志=[ERROR 运营互斥锁目录不可写（… [Errno 13]）]
   落盘 ops-results-20260928.jsonl；unread_failures() = 3（红点会亮）
B. 跑完 acct-a 后 chmod 0500：发起=['acct-a'] success=['acct-a'] skipped=[] failed=2
   两条 failed 均以 LOCK_REFUSAL_PREFIX 开头（「在本轮中途不可写」）；run_once 没抛穿
C. 锁路径被一个文件占住：发起=[] failed=1（同样拒跑，不抛）
D. _tick：正忙 → errors 0→0、没跑、无告警；不可用 → errors 0→1、没跑、2 条告警
   （「运营互斥锁目录不可写」+「运营 plan 锁不可用 … 定时器每轮都会跳过，运营已停摆」）
E. usable() 探测文件用后即删（exists=False）；账号锁 mode=0o600
   同 API 复现（Path.write_text）新建文件 mode=0o644  当前 umask=0o22      ← NB-4（已知项补强）
G. 持有后把锁目录改 0500 再 release：没抛；同进程再 try_acquire=True（threading 锁未被 strand）
H. 「别人正持有」→ success=[a,c] skipped=[b] failed=0、无前缀命中、无告警（不误报停摆）
F. 真子进程持锁（HOLDER acquired pid=40770）→ 第二进程 try_acquire('acct-x')=False；usable() 仍 True
```

**撤修复红证**：

```
M11_中途拒跑退成skipped   FAILED test_locks_dying_mid_round_fails_the_remaining_accounts_not_skips_them
                          1 failed, 123 passed in 36.56s
M12_tick不再区分不可用    FAILED test_scheduler_tick_tells_unusable_lock_from_a_busy_one
                          E: assert broken.errors == 1  →  where 0 = Scheduler.errors
                          1 failed, 123 passed in 35.68s
M13_释放失败重新抛出      FAILED test_mid_round_write_failure_does_not_strand_the_locks
                          FAILED test_locks_dying_mid_round_fails_the_remaining_accounts_not_skips_them
                          2 failed, 122 passed in 36.68s
M10_开局不拒跑（if False） 124 passed in 35.78s → **rc=0 全绿**
```

M10 全绿我单独追了成因（`bash run_m10.sh`，同一探针分别跑未变异/已变异副本）：

```
=== 基线（未变异）=== 开局检查还在吗：True  发起过的账号：[]  failed=[('acct-a','运营互斥锁目录不可写：…'),('acct-b',…)]  skipped：[]
=== 施 M10 后 ===     开局检查还在吗：False 发起过的账号：[]  failed=[('acct-a','运营互斥锁目录在本轮中途不可写：…'),…]  skipped：[]
```
⇒ 行为**仍然 fail-closed**（第二道防线 `_acquire_file` + 循环内 `usable()` 兜住，零发起），
所以这不是"改坏了照样全绿"的缺陷，而是**判据只认 `"不可写"` 子串**（test_v2_ops.py:1011 区域 / 1190），
分不清"开局就没得写"与"中途失写"两种文案；删掉开局那段不会红（NB-1）。

### 3.4 CLI 出口（`cli_zcode.py`）

**复现**：`python -u p10_cli.py`（自有端口 8412、`admin_post` 打桩，ack 不外发）与 `python -u p2d.py`

```
[正常-熔着]  rc=3  ⚠ ZCode 风控熔断（30min，全局），至 18:28 —— 本轮未对上游发起任何领取 / – 跳过 2 个（被熔断拦住）
[坏-null]    rc=0  – 跳过 2 个（无需动作 2）/ 全部正常，无需处理      ← BLK-2；跑完后 circuit.json = {"until_ms": 0.0, "reason": "", …}
[坏-abc]     rc=0  全部正常，无需处理                                  ← BLK-2，且全程 0 条 WARNING
[坏-NaN]     rc=0  全部正常，无需处理                                  ← 同上
[坏-true]    rc=0  全部正常，无需处理                                  ← BLK-3；文件回写 until_ms=1.0 但 reason 仍是"熔断"
[坏-截断]    rc=0  全部正常，无需处理                                  ← BLK-2
[B 本轮中途命中 3012] rc=1  ⚠ 本轮命中风控，已建立全局熔断：…，至 18:29 / ✗ 失败 1 个 / 含「全部正常」？ False
[C 再跑一轮]         rc=3（第二轮开局即熔）
[D1 数据目录不可写 + 拒跑轮] rc=1 + stderr「⚠ 本轮结果未能写入 …（数据目录不可写？）→ 顶栏红点不会记录这些失败…」
[D3 熔着 + 数据目录不可写]  rc=3（3 优先于 1）且两条提示都在
[C3 熔着 + 无账号]          rc=2（无账号参与优先于 3；⚠ 熔断行仍先打出来）

真子进程（`python -m model_gateway.cli zcode claim`）：合法熔着 rc=3；null rc=0；截断 rc=0
`… claim --help` epilog：「0 = 全部正常；1 = 有失败；2 = 无账号参与；3 = 全局风控熔断中…⚠️ 3 与 mgw setup 的 3 同码不同义」
```

**撤修复红证**：

```
M14_熔断不再优先于失败（return 3 if breakered else 1 → return 1）
   FAILED test_breaker_wins_over_a_credential_failure_in_exit_code    1 failed, 101 passed
M15_不再说结果未落盘（if False and results_path is None …）
   FAILED test_claim_says_out_loud_when_the_round_was_not_persisted   1 failed, 101 passed
M16_不再区分未发起与发起后失败（refused = 0）
   FAILED test_claim_head_separates_refused_from_attempted_failures   1 failed, 101 passed
M17_本轮中途建熔不再提示（elif circuit.active() → elif False）
   FAILED test_breaker_tripped_during_this_round_is_reported          1 failed, 101 passed
```

---

## ④ 阻塞项（3）

### BLK-1 熔断落盘的临时文件名固定 → 并发写自己制造坏 `circuit.json`

`quota.py:486-495`：`tmp = self.path.with_suffix(".tmp")` + `write_text` + `os.replace`。
两个进程同时 `_save()` 时，它们**共用同一个 tmp inode**（各自 `O_CREAT|O_TRUNC` + 独立写偏移），
`os.replace` 发布的可能是"甲的 JSON 头 + 乙的尾随字节"。项目里另外四处原子写都用唯一名
（`config/loader.py:65`、`setup_tools.py:182`、`instance_lock.py:61`、`api/admin.py:558` 全走 `tempfile.mkstemp`），
**只有 `quota._save()`（以及 `runner.py:588` 的 ack 水位、`main.py:554` 的 daily 快照、`core/dialects.py:150`）用固定名。**

实测（`p8_race.py`：两个 writer 进程 reason 长度差 80 倍 + 一个 reader 校验，12 秒）：

```
writer A 共写 184717 次 / writer B 共写 180951 次
reader: 坏 JSON 206783 次 / 混合内容 20351 次
  样本： JSONDecodeError: '{"until_ms": 1790000000002.0, "reason": "reason-Axxxxx", "last_call_ms": 1790000000000.0}xxxxxxxxxxxxxxxxx…'
```

可达性（按代码事实校正过）：`enter()`（3012 接线点 `ops/builtin/zcode_claim.py:121`）与 `mark_called()`（同文件 :183）
都在**账号锁之内**执行，但账号锁是 per-account 的、且 CLI 腿不取 plan 锁（`cli_zcode.py:235` 直接 `run_once`）→
**网关 cron 与 `mgw zcode claim` 各领不同账号**时两者并发，同一秒内对同一个 `circuit.json` 各 `_save()` 一次即撞上。
而 `_load()` 每次判定真读文件（S-26⑤）→ 判定方在窗口里看到的就是上面那种垃圾。

最小修法：`quota._save()` 改 `tempfile.mkstemp(dir=self.path.parent, prefix=".circuit.", suffix=".tmp")`
+ `os.fdopen` 写 + `os.replace`（与 `instance_lock.py:53-64` 同尺，5 行内）；
顺带把 `runner.py:588` / `main.py:554` / `dialects.py:150` 一并统一。
判据：新增一条"两个进程并发 `_save()` 后文件必须仍可 `json.loads` 且等于其中一方"的用例（现有 705 条对此**零判断力**）。

### BLK-2 「读不动」= 新进程按无熔断放行 + `mark_called()` 整盘覆盖 = 熔断被静默销毁（fail-open）

`_load()` 的 `if until_ms is None: return`（quota.py:477）只保护**有内存态**的进程；
新进程内存本来就是 `Cooldown()` → 读不动等价于"没熔断"。而 `mark_called()`（quota.py:538-540）
**不 `_load()`**，直接拿内存态整份 `_save()`。两者串起来是一条自我完成的路径：

`python -u p5_direction.py`（C 段=常驻最坏时长；D 段=覆盖销毁）：

```
=== D. 读不动 → 放行 → mark_called 覆盖销毁（跨进程凭据丢失） ===
null   放行(active=False) 改前={"until_ms": null, "reason": "别进程的真熔断"…} 改后=until_ms=0.0 reason='' 日志=3
缺键   放行(active=False) ……同……                                              改后=until_ms=0.0 reason='' 日志=3
"abc"  放行(active=False) 改前={"until_ms": "abc", "reason": "别进程的真熔断"…} 改后=until_ms=0.0 reason='' 日志=0
NaN    放行(active=False) ……同……                                              改后=until_ms=0.0 reason='' 日志=0
截断   放行(active=False) 改前={"until_ms": 179                                改后=until_ms=0.0 reason='' 日志=0
数组   放行(active=False) 改前=[1,2]                                          改后=until_ms=0.0 reason='' 日志=0
非UTF8 放行(active=False) 改前=\xff\xfe\x00bad                                改后=until_ms=0.0 reason='' 日志=0
越界25h放行(active=False) 改前={"until_ms": now+25h, …}                        改后=until_ms=0.0 reason='' 日志=3
```

端到端一次事故（`p9` 内联链，用的是 **BLK-1 实测到的那份竞态垃圾**）：

```
1) A 进程熔着： True  ZCode 风控熔断（30min，全局），至 18:18
2) 文件被并发写打成垃圾后，A 进程： True | 日志 0 条
3) 新进程 B 读到： False  (空)
4) B 走完领取路径（throttle_wait_ms + mark_called）后文件 =
   {"until_ms": 0.0, "reason": "", "last_call_ms": …} → A 的熔断凭据是否还在： False
5) A 进程之后： False （下一次判定连自己内存里的熔断也没了）
   全程 WARNING 条数： 0
```

界面侧（`p6_run.py`，8 次真装配重启，自有端口 8411）：

```
形态 正常-熔着30min：row_status=cooldown available=False 冷却剩余=1799763
   last_error='ZCode 风控熔断（30min，全局），至 18:11'
   日志 [WARNING] [熔断对齐] 全局风控仍在生效，已 bench 1 个资源
形态 坏-null   ：row_status=active available=True 冷却剩余=0 last_error=None  日志 3 条（文案说"不可信"）
形态 坏-非数字 ：row_status=active available=True 冷却剩余=0 last_error=None  日志 []      ← 界面无痕 + 日志无痕
形态 坏-NaN    ：同上，日志 []
形态 坏-截断JSON：同上，日志 []
形态 坏-顶层数组：同上，日志 []
形态 坏-布尔true：同上，日志 []
CLI 侧同 6 种形态：rc=0 + 「全部正常，无需处理」（§3.4）
```

对照 §17 的立身之本（`main.py:88-92` 注释原文：「重启后必须重新看见它，否则模型转发照旧打向仍在风控观察期里的账号」）——
现在这句话只在"文件恰好是人写的合法 JSON"时成立。**闸门层实测**（`p2_cli.py` A 段，假 `_build_client` 计数，零真实请求）：

```
正常：熔着（now+30min）  结果=inactive 客户端被建=0 上游调用=0 详情='ZCode 全局风控熔断中（剩余约 30 分钟），本轮跳过'
坏：null/缺键/"abc"/NaN/Infinity/true/截断/数组/顶层null/越界25h
                        结果=inactive 客户端被建=1 上游调用=1 详情='当前无可领取活动'   ← 10/10 全部放行
```

最小修法（两处，都不回退既有红证）：
① `mark_called()` 改为"读原文件 dict、只换 `last_call_ms`，读不动才退回内存态整存"（F4 已实测该改法全套 705 不受影响）；
② `_load()` 见 `until_ms is None` **且内存无态**时，不再按"无熔断"起，而是按 `文件 mtime + COOLDOWN_MS`
   设一个**有界**的保守熔断并打一条 WARNING（mtime 是绝对墙钟 → 到点自己解除，不会永挡；
   手动出口"删文件"语义不变，P5 B3 实测 `unlink → active=False reason=''`）。

**最坏保持时长（回答"会不会永不解除"）**：坏文件 + 常驻进程 = 有界，实测等于内存自己的到期点：

```
C0 起点：active=True left_min=30 → C1 +29min：True 1 → C2 +31min：False reason='SENTINEL-真熔断'（裸原因）
C3 之后连续 5 次判定恒 False
```
唯一能把保持时长推过 24h 的是**墙钟回拨**（回拨量 + 原剩余），实测 30 天回拨 → `left_min=44639 ≈31.0 天`
（方向是 fail-**closed**，有界且手动删文件立即解除）；第十轮记的"最坏 24h 有界"要补这个前提。

### BLK-3 `until_ms` 布尔形态未被判坏 → 常驻进程的正熔熔断被清零（第七类坏值）

`float(True)==1.0` / `float(False)==0.0` 是合法数值、`1.0 < horizon` 也不是布尔 → 走"合法已过期"分支，
`_load()` 用它覆盖内存（实测 `p1b` 用例 14、`p5` A 段、`p10` `[坏-true] rc=0`）。
S-34 的六类（缺键/`null`/非数字/非有限/越界 + `last_call` 归 0）**不含 JSON 布尔**；
`test_missing_or_null_until_ms_keeps_the_running_breaker` 的五个 payload 也不含布尔（F1 施加布尔判坏后全量逐字不变 = 零判据）。
最小修法 1 行：`if isinstance(raw_value, bool) or raw_value is None:`（F1 实测不动任何判据）。

---

## ⑤ 非阻塞登记（6）

| # | 事实与实测 | 建议 |
|---|---|---|
| NB-1 | 开局拒跑与中途拒跑共用 `"不可写"` 子串判据 → 删掉开局那段**全绿**（M10，124 passed），但文案会从"本轮未对任何账号发起操作"变成"在本轮中途不可写"（对开局就不可写的目录是**说谎**） | `test_run_once_refuses_the_whole_round_when_locks_are_unusable` 补一条 `assert "中途" not in r`；或把两种成因的前缀分成两个常量 |
| NB-2 | `last_call_ms` 缺键/`null` 也走 `_ms_or_zero` 的同一条 WARNING → 对**完全读得懂**的文件打「视为文件不可信，保持现有内存态，不清零熔断」，实测 `p1b` 用例 18/20 与 `counter` 第三条：文件里的熔断**被采用**了，日志却说不可信；每次判定一条（5 次判定 5 条） | 把告警按字段拆开：只有 `until_ms` 判坏时才说"不可信"；`last_call_ms` 缺失说"节流信息缺失，按无最近调用处理"（DEBUG 级） |
| NB-3 | 静默坏值族（`"abc"`/`NaN`/`±Infinity`/截断/数组/非 UTF-8/顶层 `null`/空文件）保持内存态但**0 条日志**（`p1b` 用例 03–07/10–13/22 日志=0）；第十轮补做表写的"四类统一返回 None 并 `logger.warning`"只对 3 类成立（铁律 2） | 按 F2 补三行日志（实测不影响判据），并把补做表口径改成"缺键/`null`/越界三类留痕，其余四类当前静默" |
| NB-4 | 已知项补强：`usable()` 探测文件用后即删（`exists=False`），但同一 API（`Path.write_text`）在该目录新建文件实测 `mode=0o644 umask=0o22`，账号锁走 `os.open(...,0o600)` 实测 `mode=0o600` → 600/644 不对称仍在（`runner.py:209-212`） | 探测文件改 `os.open(..., 0o600)`，与 `_try_create` 同尺 |
| NB-5 | 一行状态文件字段缺失以外的"内容脏"会被 `str()` 直上界面：`reason` 写成 dict → 界面/CLI 出现 `"{'a': 1}，至 17:51"`（`p1b` 用例 21） | `_load()` 里 `reason` 只接受 `str`，其它类型当坏值（并入 NB-3 的告警） |
| NB-6 | 资源级聚合行：一条映射 cooldown + 一条 active → `status=active` 却 `cooldown_remaining_ms=1799999`（`p4` C 段）。界面用 `status==="cooldown"` 兜住（dashboard.js:103 显示 `—`），所以**用户侧不矛盾**，但 `/admin/api/overview` 的 JSON 里两列语义打架，任何别的消费者都会读成"在冷却" | 要么在 `status!="cooldown"` 时把聚合剩余也归 0，要么在快照里加 `cooldown_entries` 计数说明它来自哪条映射 |

已知开放项本轮未升级（热重载适配器未 `aclose`、探针写失败无自愈、`.write-probe.lock` 0644、
`data/ops-locks` 不入保留清理、第三方删锁静默失效）——除 NB-4 外本轮未重复取证。

---

## ⑥ 收工自证

```
开工：$ git status --porcelain | wc -l        → 82
收工：$ git status --porcelain | wc -l        → 82      （净增 0）

四个被测文件 仓库 vs 副本（变异复原后）md5 逐对相同：
2aa0581234ba14f81a23b2008a53fca0  model_gateway/upstream/zcode/quota.py
1d65619111e00e5cdb5f8a6611e8748e  model_gateway/core/resources.py
3cf367018d5cffb15ffac0ccd4462a50  model_gateway/ops/runner.py
57d0f95a25e7d9b2fc1c4d151f2f6991  model_gateway/cli_zcode.py

$ find data -newermt "-180 minutes" -type f   → （空）＝ 用户数据目录全程只读、零污染
$ lsof -nP -iTCP:8300 -sTCP:LISTEN            → （空）＝ 用户网关实例本就没跑，未被重启/kill
```

**本轮自我交代（须报的自身偏差）**：P2 的 CLI 腿在失败轮里调用了生产函数 `_ack_failures()`
→ `admin_post("/admin/api/ops/ack")`，当时沙箱配置里写的 8399 恰被并行面板的 `fake401.py`（pid 33683）占用，
故有 2–3 次 ack POST 打到了**别人的进程**（对方非网关，返回非 JSON → `admin_post` 静默返回 None，
未写任何数据目录）。P10/P2-D 起已把端口改到无监听的 8412 并把 `admin_post` 打桩，`:8300` 与仓库 `data/` 全程未触碰。
