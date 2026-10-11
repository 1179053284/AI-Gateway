# eng-accept-8b · 第八轮后端攻击性复验（运营互斥 + 落盘链路）

复验对象：`model_gateway/ops/runner.py`（`_release_file` / `PlanLock.release` / `Scheduler._tick` /
`run_once` 的 `usable()` 探测 / `AccountLocks.usable`）、`model_gateway/cli_zcode.py`（CLI 腿）、
`model_gateway/stats/events.py`（保留清理）。账本：`docs/changes/e2e-records/E2E-20260928-round5-fixes.md`
（第六轮 S-22 / 第七轮 S-24、S-26④）。

## ① 结论

**有条件通过（1 阻塞）。**

1. **第七轮 BLK-1（S-24）确认已修，且强度是真的**：不是"不抛异常"级别的修法。我用**真实
   asyncio 定时器任务 + 真实子进程**复现了"跑完第一个账号后 `chmod 0o500`"的场景，实测
   **任务存活、`errors` 计数、恢复权限后运营继续真实发起账号操作（恢复后又跑了 15 次 claim）**；
   另外三种收尾故障（锁文件被第三方删除、锁目录换成指向只读处的符号链接、真 ENOSPC 满盘卷）
   逐条判过：**都不会停摆**，`_tick` 与 `run_once` 的 `finally` 都吞掉了 OSError 并留痕，
   腾出空间/换回可写目录后当轮即恢复。`data/` 只读、`:8300` 未重启、未发任何真实上游请求
   （CLI 腿全程挂了 `_build_client` 安全网，构造真实客户端会当场炸成本地失败）。
2. **S-22 的 fail closed 全链路端到端成立**：整轮拒跑记 `failed` → 文案、退出码
   （A=1 / 熔断时 3 **优先于** 1 / N=0 = 2）、`ops-results-*.jsonl` 落盘、
   `unread_failures()` 红点从 1 → `ack_reports()` 清 1 → 0，逐环节实测通过；
   **既没被 ack 吞掉，也不存在"永远点不亮"**（点不亮只发生在 `write_report` 本身失败的分支，
   而那正是 S-26④ 覆盖的分支）。
3. **S-26④ 成立**：两种真实不可写形态（当日文件不存在 + 目录只读 / 文件存在但 0444）
   都同时打出 `logger.error`（写明"顶栏红点不会点亮这些失败"）与 CLI 的
   `⚠ 本轮结果未能写入 …` 改口，且**不改变退出码语义**（有失败仍 1）。
4. 🔴 **新阻塞 BLK-1**：`run_once` 只在**开跑前**探测一次 `usable()`；**跑到一半锁目录失写**
   （本轮 S-24 的原始场景！）时，余下账号在 `_acquire_file` 里被 OSError 打成 `False`，
   `run_once` 把它们记进 **`skipped`** —— 于是 `failed=[]` → `ops-results` 里 failed 0 行 →
   红点 0 → **真实 CLI 打印"全部正常，无需处理"并 exit 0**（见 LEG F 实测）。
   这违反 S-22 自己定下的裁决口径（runner.py:422-432 注释："`skipped` 是'正常没动作'，会被读成没事"），
   而 CLI 那句 `– 跳过 N 个（并发占用 / 已停用）`（cli_zcode.py:281）在成因是 EACCES/ENOSPC 时
   是**错误的归因**。第七轮修的是"停摆"，本条是同一个场景的"谎报没事"，另半边没收住。
5. 非阻塞观察 4 条（`.write-probe.lock` 无自愈 / 探测文件 0644 泄露 token /
   `data/ops-locks` 不在保留策略内 / 第三方删锁 = 互斥静默失效 + 同名目录占位时**完全无日志**），
   见 ③ 之后。

机械门（我自己跑的，非采信自述）：

```
.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest-8b -p no:warnings
693 passed in 125.23s (0:02:05)
```

---

## ② 跑了什么 → 看到什么

### 2.1 S-24：真实定时器任务 + 真实子进程（`/tmp/mgw-accept-8b/attack_s24.py`）

每轮 = 真 `run_once`（3 个账号、假 claim、`delay_s=0`）包在真 `Scheduler.start()` 的
`_tick` → `PlanLock` → `AccountLocks` 链路里，故障由外部时钟点注入（`chmod` / `rmdir` + `symlink` / 删锁文件）。

| 场景（跑了什么） | 看到什么 |
|---|---|
| ① 跑完第一个账号后 `chmod 0500`（BLK-1 原形态），0.12s 后恢复权限 | `"errors": 2, "task_alive_at_stop": true, "claims_total": 16, "claims_after_restore": 15`；恢复后轮次 `"success": ["a1","a2","a3"]` |
| ② 第三方把所有 `*.lock` 删掉（两次） | `"errors": 0, "rounds_ran": 10, "claims_total": 30, "task_alive_at_stop": true`（`_release_file` 的 `_read_lock` 读不到 → 不再 unlink → 无异常） |
| ③ 锁目录本体换成符号链接 → 指向 `0500` 目录，再换成指向 `0700` 目录 | `"errors": 3`（3 个 tick 被拒并记数），`"task_alive_at_stop": true`，`"claims_after_mark_back": 15` → 换回可写后立刻续跑 |
| ④ 锁目录换成**悬空**符号链接（挂载丢失），再撤软链 | `"errors": 3, "task_alive_at_stop": true`；日志给出真实成因：`[Errno 17] File exists: '…/locks'`（`Path.mkdir(exist_ok=True)` 对悬空软链 `is_dir()` 为假 → 重新抛出 → 被 `except OSError` 吞住）；撤掉软链后 `mkdir` 自愈，续跑 15 次 claim |
| ⑤ 全程 `0500`（永不恢复） | `"errors": 9, "rounds_ran": 0, "claims_total": 0, "task_alive_at_stop": true` → 每轮**响亮拒跑**（不是静默停摆），任务不死 |

场景①关键 stderr（证明"顶穿"已堵住、且降级为可回收）：

```
[log WARNING] 运营锁释放失败（…/locks/a1.lock：[Errno 13] Permission denied: …）→ 交给超龄回收，不向上抛
[log ERROR] 运营互斥锁目录不可用（…/locks：[Errno 13] Permission denied: '…/locks/a2.lock'）→ 拒绝该账号本轮，不冒险双领
[log ERROR] 运营互斥锁目录不可写（…/locks：[Errno 13] Permission denied: '…/locks/.write-probe.lock'）
[log ERROR] 运营 plan 锁不可用（…/locks）→ 定时器每轮都会跳过，运营已停摆；请检查数据目录权限
[log WARNING] 运营锁释放失败（…/locks/__plan__.lock：[Errno 13] Permission denied: …）→ 交给超龄回收，不向上抛
```

`PlanLock.release()` 的进程内 `threading.Lock` 也确实放开：场景①恢复权限后同一 `PlanLock` 连续
拿到锁并跑完 5 轮（若 `_lock` 卡死，后续每轮都会走 `try_acquire()==False` 分支、claims 恒 0）。

### 2.2 ENOSPC：真实满盘卷（`hdiutil create -size 4m -fs HFS+` + `dd`/4KB pad 压满）

```
[填满] 第 63 个 4KB 失败：errno=28 No space left on device
[填满] df: 4056 3908 148 97%
[log ERROR] 运营互斥锁目录不可写（…/mnt/locks3：[Errno 28] No space left on device: '…/.write-probe.lock'）
[满盘] usable() -> False
[满盘] claims_initiated: [] | failed 行: 3 | 原因头: 运营互斥锁目录不可写：…/locks3 —— 跨进…
[满盘] write_report -> /tmp/mgw-accept-8b/mnt/usage3/ops-results-20260928.jsonl
[满盘] usage 目录: ['ops-results-20260928.jsonl'] | unread_failures(红点) -> 3
```

定时器版（先满盘后 `rm filler`）：满盘期 `{"errors": 0, "rounds_entered": 4, "claims": 3, "alive": true}`
—— 满盘期拒绝发生在 `run_once` 的账号级探测（plan 锁文件 `O_CREAT` 只建 0 字节文件、不占块 → 成功），
所以 `Scheduler.errors` 不涨而**失败进了 report**（`failed` 3 行 → 红点亮），分类正确；
腾出空间后 `{"rounds_entered": 10, "claims": 21, "alive": true}` → 续跑。

判定：**ENOSPC 不停摆**（`usable` / `_acquire_file` / `write_report` / `ack_reports` 四条路径都是
`except OSError`，errno 28 属 OSError 家族，逐条实测有日志与 `failed` 行为证）。

### 2.3 `.write-probe.lock` 探测文件（`/tmp/mgw-accept-8b/attack2.py`）

```json
"1-residue-default-mode":        {"usable": true,  "probe_after": false}
"2-probe-residue-readonly":      {"usable_1": false, "usable_2": false,
                                  "residue_still_there": true,
                                  "usable_after_manual_removal": true}
"3-multi-process-usable": {"per_proc":[{"usable_true":4080,"usable_false":0},
                                       {"usable_true":4108,"usable_false":0},
                                       {"usable_true":4125,"usable_false":0}],
                           "any_false": false, "leftovers": []}
"4-cross-process-account-lock": {"grants_per_proc":[55,47,56],
                                 "overlap_max_depth": 1, "leftover_locks": []}
```

- **崩溃残留会不会永久挡住 `usable()`**：默认残留（本进程 uid 可覆盖，0644）**不会**——
  `write_text` 覆盖式写 + 随后 `unlink` 成功，目录干净。
  但**本进程写不动的残留**（0444；同码等价于"曾经 `sudo mgw` 跑过一次、探测文件属 root"）
  → `usable()` **恒 False**，且 `usable()` 在写失败分支 `return False` **走不到 unlink**（runner.py:208-213）
  → **无自愈**，只有人工删文件才恢复（实测 `usable_after_manual_removal: true`）。
  后果是"每轮响亮拒跑"（所有账号 `failed` + 红点 + CLI exit 1），不是静默停摆 → 记 OB-1。
- **多进程互相 unlink 造成误判**：3 进程 × 约 0.5s 共 12,313 次 `usable()`，
  **0 次误判 False、0 残留**（`write_text` 幂等覆盖，unlink 谁抢到都无害）。打破不了。
- **保留清理**：`stats/events.py:_cleanup_old_files` 只走 `usage_dir`，**不含 `data/ops-locks/`**。
  probe 名字固定 → 最多 1 个文件、不积累；账号锁文件在进程被 kill/账号改名后**永久残留**
  （只在同名再竞争时按 `LOCK_MAX_AGE_S` 回收）。仓库当前**没有** `data/ops-locks/` 目录
  （`ls: … No such file or directory`），说明尚无历史残留，但清理策略确实缺一块 → 记 OB-3。
- **跨进程互斥是真的**：3 进程抢同一账号，交错日志的 `IN/OUT` 最大并发深度 = 1，
  158 次授权无一重叠，收工无残留锁。

### 2.4 S-22 fail closed 端到端（CLI 腿，`/tmp/mgw-accept-8b/cli_e2e.sh`）

临时 `MG_CONFIG=/tmp/mgw-accept-8b/cli/data/config.yaml`（port **8399**，且实测无人监听 →
CLI 内部的 `admin_post("/admin/api/ops/ack")` 必然 no-op，**绝不碰 :8300 真实实例**），
`MGW_ZCODE_ACCOUNTS` / `MGW_OPS_LOCK_DIR` 全部指到临时目录；假账号 `eng8b`（只有 `meta.json`、
无凭据 → `claim()` 在 `_build_client` 之前就本地返回"凭据缺失"，加上安全网，全程零真实上游请求）。

**LEG A（锁目录 0500，usage 可写）→ `EXIT=1`**

```
✗ 失败 1 个：
    eng8b  运营互斥锁目录不可写：/private/tmp/…/data/ops-locks —— 跨进程互斥建立不起来，本轮未对任何账号发起操作（宁可拒跑也不双领）。请检查数据目录权限或是否被只读挂载
    逐条明细已落盘：/private/tmp/…/data/usage/ops-results-20260928.jsonl
（stderr）运营互斥锁目录不可写（…：[Errno 13] Permission denied: '…/.write-probe.lock'）
jsonl: {"ts": "2026-09-28T15:07:17", …, "failed": [{"account": "eng8b", "reason": "运营互斥锁目录不可写…"}], "skipped": [], "no_participants": false}
unread_failures(顶栏红点) = 1
ack_reports 本次清掉      = 1
unread_after_ack          = 0
ack 水位文件              = {"date": "20260928", "rows": 1}
```

→ **拒跑轮的失败数没被 ack 吞掉**：CLI 自己那一次 `_ack_failures()`（网关不在跑）是无操作，
未读保持 1；只有用户点红点（main.js:109-113，`dot.addEventListener("click")` → POST ack）
或显式调 `ack_reports()` 才清零，清零数与水位一致（`rows: 1` → 未读 0）。界面侧不会
"加载即 ack"（poll 只读 `/admin/api/status`）。

**LEG C（熔断生效 + 锁目录 0500）→ `EXIT=3`**：

```
⚠ 面板第八轮复验：3012 风控，至 15:37 —— 本轮未对上游发起任何领取
    状态文件：/tmp/…/data/zcode/circuit.json（到点自动恢复；删除该文件可立即放开后续领取…）
✗ 失败 1 个：
    eng8b  运营互斥锁目录不可写：…
[main-return=3]
```

→ **熔断 3 优先于 1** 与 `--help` epilog（cli.py:62-65）/README 一致。

**LEG D（ghost 账号，N=0）→ `EXIT=2`**："无账号参与 —— 尚未接入任何 ZCode 账号。"
（注：`no_participants` 的早退发生在 `usable()` 探测**之前**，所以"无账号 + 锁目录不可写"时
用户只看到 rc 2、看不到锁问题——量级很小，记为观察不列为缺陷。）

**LEG E（恢复 `chmod 0700`）→ `EXIT=3`，但 stdout 出现 `凭据缺失`**：
说明这一轮**真的越过了 `usable()` 探测、进到逐账号 claim** → CLI 腿的"恢复后续跑"也成立。
（此处 rc=3 是我脚本的 `rm` 删错了 circuit 路径、熔断仍生效所致 —— 我的复现瑕疵，非被测代码问题。）

### 2.5 S-26④ 落盘失败改口（两种真实形态）

**B2：usage 目录 0500 且当日文件不存在 → `EXIT=1`**

```
（stdout）✗ 失败 1 个：
    eng8b  凭据缺失（先 `mgw zcode login` 或 `mgw zcode import`）
（stderr）运营结果落盘失败（…/data/usage：[Errno 13] Permission denied: '…/ops-results-20260928.jsonl'）→ 本轮明细未写入 …/data/usage，顶栏红点不会点亮这些失败；请检查数据目录权限
（stderr）⚠ 本轮结果未能写入 /private/tmp/…/data/usage（数据目录不可写？）→ 顶栏红点不会记录这些失败，逐条原因只存在于本终端的输出与网关日志里
（usage 目录）total 0        ← 确实一行都没写进去
```

**B3：当日文件已存在但 `chmod 0444` → `EXIT=1`**：同上两句文案都出现，且
`unread=1`（只数得到我预先植入的旧行）→ 本轮失败**确实点不亮红点**，而文案把这件事说明白了。

> 自我交代：**第一轮 LEG B 没能打破落盘**——目录 0500 但当日文件已存在时，`open(path,"a")`
> 只需要**文件**的写权限（POSIX 语义：目录写权限只管创建/删除条目），所以那次照样追加成功、
> 没有 ⚠ 文案（`stdout` 甚至打出"逐条明细已落盘"）。这是 POSIX 事实、不是缺陷；
> 真正的落盘失败分支由 B2/B3 两种形态覆盖。顺带一个值得记的边角：
> 若数据目录整体只读但**当日文件恰好早先建好且仍可写**，运营仍能正常落盘与点红点。

### 2.6 仓库清洁（铁律：`data/` 只读、不碰 `~/.zcode`）

```
$ find /Users/w/Desktop/Model-Gateway/data -mmin -5 -type f      → （空）
$ git status --porcelain | wc -l                                  → 82（与开工前同一份工作区）
$ find /tmp/mgw-accept-8b -name "*.log"                           → 空（CLI 腿未写日志文件）
```

---

## ③ 阻塞项（1 项）

### BLK-1 · mid-round 失写 → 余下账号记 `skipped`，真实 CLI 打印"全部正常，无需处理" + `exit 0`

**位置**：`model_gateway/ops/runner.py:426`（`usable()` 只探一次）+ `:434-437`（账号循环里
`if not locks.try_acquire(account): report.skipped.append(account)`）。
`_acquire_file` 把 EACCES/ENOSPC/EISDIR 一律收成 `return False`（:193-196），而 `run_once`
把 `False` 一律当"别人正持有"→ 记 `skipped`。`_tick` 已经会分诊成因（:614），账号循环不会。

**后果链**（全部实测）：`failed=[]` → `ops-results` 该行 `"failed": [], "skipped": ["m2","m3"]`
→ `unread_failures() = 0` → 顶栏红点不亮 → CLI `if report.failed:` 不成立 →
`– 跳过 2 个（并发占用 / 已停用）`（错误归因）+ `全部正常，无需处理` + **返回 0**。
即：这些账号本轮**一次上游都没发起**，而四个出口（stdout/退出码/jsonl/红点）全说"没事"。
这正是 S-22 注释里点名的"会被读成没事"，只是发生在"跑到一半才失写"的分支。

**最小复现 A（成因真实：`chmod 0500` mid-round，见 `attack2.py` ⑤）**

```python
LOCKS.mkdir(); locks = AccountLocks(LOCKS); claims = []
async def claim(a, *, manual=False, runtime=None):
    claims.append(a)
    if a == "m1": os.chmod(str(LOCKS), 0o500)      # 跑完第一个号后目录失写
    return OpResult(a, "success", "ok")
rep = asyncio.run(run_once(accounts=["m1","m2","m3"], claim=claim,
                           locks=locks, delay_s=0.0, jitter=False))
```

实测：

```json
{"claims_actually_initiated": ["m1"],
 "report_success": ["m1"], "report_skipped": ["m2","m3"], "report_failed": [],
 "jsonl_failed_count": 0, "jsonl_skipped": ["m2","m3"],
 "unread_failures_red_dot": 0, "ack_cleared": 0}
```

**最小复现 B（同一分类路径，走真实 CLI）**：让 `usable()` 通过但账号锁建不起来
（把 `ops-locks/eng8b.lock` 占成一个**目录**；`os.open` 走 EEXIST/宽限期分支 → `try_acquire()` False），
然后跑真实 `mgw zcode claim`：

```
EXIT=0
--- stdout ---
– 跳过 1 个（并发占用 / 已停用）
全部正常，无需处理
    本轮结果已落盘：/private/tmp/…/ops-results-20260928.jsonl
--- stderr ---                        ← 空：这条路径连一行日志都没有
jsonl: {"failed": [], "skipped": ["eng8b"], "no_participants": false}
顶栏红点 unread_failures = 0
```

**建议修法（3 处，不扩范围）**：账号循环里 `try_acquire()` 返回 False 时补一次
`locks.usable()` 分诊（与 `_tick` 同一把尺）：探测不过 → 把该账号**及本轮余下账号**记 `failed`
并写清"锁目录中途失写"；探测得过 → 才记 `skipped`。同时把 cli_zcode.py:281 的
"并发占用 / 已停用"改成按实际成因给措辞。

---

## ④ 非阻塞观察（建议一并处理）

| # | 观察 | 证据 | 建议 |
|---|---|---|---|
| OB-1 | `.write-probe.lock` 的写失败分支 `return False` **走不到 unlink**（runner.py:206-214）→ 本进程写不动的残留（0444 / 曾 root 跑过）**永久拒跑**、无自愈 | `attack2.py` ②：`usable_1=false, usable_2=false, residue_still_there=true`，手工删除后才 `true` | 写失败时 `unlink(missing_ok=True)` 后重试一次再判 False（红点仍亮，属"响亮的永久拒跑"，故不阻塞） |
| OB-2 | probe 用 `write_text` → **0644**（真锁是 `os.open(...,0o600)`），内容含 `pid + _LOCK_TOKEN`；共享机器上任何本地用户可读 | 实测残留文件权限位；`runner.py:208` vs `:159` | 与真锁同权限（`os.open(..., 0o600)`） |
| OB-3 | `data/ops-locks/` 不在保留清理内（`stats/events.py` 只遍历 `usage_dir`）：probe 固定名不积累，但崩溃/改名遗留的 `*.lock` 永久留存 | `grep -rn "ops-locks" model_gateway/` 仅 `runner.py:84` + `paths.py` 文档；仓库当前无该目录 | 纳入 `_cleanup_old_files`（或 `run_once` 开头顺手扫超龄锁） |
| OB-4 | 第三方删掉**在飞**的锁文件 → 互斥静默失效、可在同一账号上双领（文件锁固有），且 `_acquire_file` 对"锁路径被占成目录"这类 OSError 走 `pid is None + 宽限期`分支时**完全无日志**（LEG F stderr 为空） | `attack_s24.py` ②（不停摆）；LEG F stderr 空 | 至少在 `try_acquire` 因 OSError 失败时把成因带上账号名进日志；宽限期分支可加一条 debug 级说明 |

---

## ⑤ 试过但**没能打破**的攻击面（如实记录）

1. **`_release_file` 顶穿调度**：三种破坏形态（只读目录 / 第三方删文件 / 悬空软链）× 真
   `Scheduler.start`，任务全部存活、恢复后全部续跑 —— S-24 的修法成立。
2. **`threading.Lock` 卡死**：恢复权限后同一 `PlanLock` 连续拿锁跑完 5 轮（`try/finally` +
   `contextlib.suppress(RuntimeError)` 都到位）。
3. **多进程 `usable()` 互相 unlink**：12,313 次并发探测零误判零残留。
4. **跨进程账号互斥**：3 进程真抢，最大重叠深度 1，无一漏网（`O_CREAT|O_EXCL` + 令牌双条件成立）。
5. **pid 复用 / 空文件 TOCTOU**：`LOCK_WRITE_GRACE_S` 与 `_LOCK_TOKEN` 双条件未被打穿
   （用第三方进程写入伪造 `pid token` 时，回收仍要过"pid 存活 + 超龄"两道）。
6. **ENOSPC**：errno 28 走 OSError 家族、四路径均有 `except`，实测既不崩也不停摆。
7. **ack 语义**：拒跑轮的失败既没被吞（网关离线时 CLI 的 ack 是 no-op，未读保持 1），
   也没"永远点不亮"（唯一不亮的分支 = `write_report` 失败，已由 S-26④ 的两句文案交代）。
8. **红点加载即清**：`main.js` 只在 `dot` 的 click 里 POST ack，poll 只读 status。

## ⑥ 复现物料

`/tmp/mgw-accept-8b/`：`attack_s24.py`（定时器 + 目录故障）、`attack2.py`（probe/多进程/mid-round 分类）、
`attack_enospc.py` 与内联 4KB-pad 脚本（真满盘卷）、`cli_run.py` + `cli_e2e.sh`（CLI 五腿 + B2/B3）、
`pytest.out`（693 passed）。仓库内除本文件外零改动。
