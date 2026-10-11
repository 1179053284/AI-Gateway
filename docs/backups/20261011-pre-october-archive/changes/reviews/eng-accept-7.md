# 第七轮 · 后端工程师攻击性验收（eng-accept-7，2026-09-28）

范围：熔断时刻读时渲染（S-21）· 运营互斥 fail closed（S-22）· 归一化单一口径（S-19e）· 接线护栏放宽（S-20）。
纪律：只验收不改生产代码；`data/` 只读未动；未碰 `~/.zcode`/`~/.workbuddy*`；未打真实上游；未重启 `:8300`；临时件全在 `/tmp/mgw-accept-7-eng/`。

---

## ① 结论

**有条件通过（1 项阻塞）。**

四处落地里：读时渲染的**核心不变量成立**（跨进程、跨午夜、同日、到期、跨年都对），fail-closed 的**开跑前探测成立**（零上游、记 failed、落盘、点亮红点、ack 正常），护栏**自证判据真能红**（4 个变异逐个打红）。但打破了三处：

| # | 破坏 | 级别 |
|---|---|---|
| **BLK-1** | 锁目录**轮中**失写 → `_release_file()` 的 `unlink` 未挡 OSError → 抛出穿出 `Scheduler._tick` 的 `finally` → **定时器任务当场死掉**；权限恢复后运营**永不重启**，且 `errors` 计数为 0、`ops-results` 一行不写、红点不亮 | 阻塞 |
| N-1 | 旧格式 `circuit.json`（写入时已烘死「，至 HH:MM」）读时**二次拼接** → `…，至 01:20，至 14:38`，且该串进「最近错误」列 | 非阻塞（升级窗口） |
| N-2 | `until_ms` 类型不符（字符串/列表）时 `_load()` 的 `float()` **不在 try 内** → `ValueError` 直穿 `get_circuit()`，`mgw zcode claim` 崩栈 | 非阻塞 |
| N-3 | 归一化**第四处**：`cli_probe.py:29` 仍自己 `base_url.rstrip("/")` 用**原始**值 → 带空格的粘贴 URL 在网关能跑、在 `mgw probe` 报 `UnsupportedProtocol` | 非阻塞 |
| N-4 | 护栏两处**假绿**盲区（局部变量同名顶替 / `cls in text` 裸子串豁免） | 非阻塞 |
| N-5 | mtime 相等即丢弃已读到的内容：粗粒度时间戳卷（exFAT/SMB/NFS）下跨进程熔断**看不见** | 非阻塞 |

机械门基线（本轮自跑）：`.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-accept-7-eng-mgw-pytest-eng -p no:warnings` → **`683 passed in 159.73s (0:02:39)`**（与第六轮账本一致，无回归）。

---

## ② 我跑了什么 → 看到什么

### 攻击 1：熔断时刻读时渲染（`quota.py:335 until_label` / `:349 _with_until` / `:459 reason`）

**1a 两个真实子进程、不同 cwd、同一份 `circuit.json`**（脚本 `/tmp/mgw-accept-7-eng/exp_a_circuit.py`；写方 cwd=`/tmp/cli-cwd`、读方 cwd=`/tmp/gw-cwd`，同一 `MGW_ZCODE_ACCOUNTS`）

```
writer: WROTE {"until_ms": 1790576820013.984, "reason": "ZCode 风控熔断（30min，全局）", "last_call_ms": 1790575020013.984}
reader: PID 87923 CWD /private/tmp/gw-cwd
ACTIVE True
REASON 'ZCode 风控熔断（30min，全局），至 14:27'
```
→ **打破失败**：文件里只有裸原因，读方按当时钟点拼，跨进程说法一致，落盘无「明日」字样。

**1b 时刻判定用显式 `now_ms` 逐个过边界**（不碰真实时钟）

```
  23:50 熔 30min            -> 'ZCode 风控熔断（30min，全局），至 明日 00:20'
  午夜后 00:05 读同一条        -> 'ZCode 风控熔断（30min，全局），至 00:20'
  跨年 23:50               -> 'ZCode 风控熔断（30min，全局），至 明日 00:20'
  同日 12:00               -> 'ZCode 风控熔断（30min，全局），至 12:30'
  now==until（刚好到期）         -> 'ZCode 风控熔断（30min，全局），至 23:59'
```
→ **打破失败**：跨日加「明日」、同日不加、跨年 `(tm_year, tm_yday)` 字典序正确。

**1c 旧格式文件（升级路径）——打破成功（N-1）**

```
=== A2 旧格式文件（reason 已带「，至」）读时渲染 ===
ACTIVE True
REASON 'ZCode 风控熔断（30min，全局），至 01:20，至 14:27'
同日旧格式: ACTIVE True | REASON 'ZCode 风控熔断（30min，全局），至 23:40，至 14:27'
```
残留与不自愈证据：
```
  reason() = 'ZCode 风控熔断（30min，全局），至 01:20，至 14:38'
  mark_called 后文件 = ZCode 风控熔断（30min，全局），至 01:20
  再次读 = 'ZCode 风控熔断（30min，全局），至 01:20，至 14:38'
```
成因：`_load()` 原样收下 `reason`（`quota.py:419`），`_with_until` 无「已带时刻」判据。这条串经 `sync_circuit_to_runtime`/`bench_all_zcode` 写进 `state.last_error` → 总览「最近错误」列就是两句钟点。
未升级为阻塞的理由（附证据）：`find data -name circuit.json` → 空（用户当前不在熔窗内），影响面限于「升级时恰好熔着」的 30 分钟窗口。修法一行：`_load()` 里 `reason.split("，至 ")[0]`，或落盘时丢弃旧字段。

**1d `until_ms` 异常值（打破成功，N-2）**

```
[expired_past]   rc=0 -> ACTIVE False | REASON 'ZCode 风控熔断（30min，全局），至 13:56'
[zero]           rc=0 -> ACTIVE False | REASON 'ZCode 风控熔断（30min，全局）'
[null]           rc=0 -> ACTIVE False | REASON 'ZCode 风控熔断（30min，全局）'
[str_nonnumeric] rc=1 -> ValueError: could not convert string to float: 'abc'
[list]           rc=1 -> TypeError: float() argument must be a string or a real number, not 'list'
[far_future_days] rc=0 -> ACTIVE True | REASON '熔断，至 明日 13:57'
[neg]            rc=0 -> ACTIVE False | REASON '熔断，至 07:59'
```
真实 CLI 复现（`MGW_ZCODE_ACCOUNTS=/tmp 假根`，零账号、零上游）：
```
  File ".../upstream/zcode/quota.py", line 393, in __init__
    self._load()
  File ".../upstream/zcode/quota.py", line 418, in _load
    self._cd = Cooldown(until_ms=float(raw.get("until_ms") or 0),
ValueError: could not convert string to float: 'abc'
```
`quota.py:411-414` 的 try 只包 `json.loads`，`float()` 在外面 → 注释承诺的「半写/损坏：保持内存态」只兑现了一半。
另两点：过期时 `reason()` 仍印**已经过去**的钟点（调用方全都先判 `active()`，实测 6 处调用点 `main.py:110`/`cli_zcode.py:232,247`/`zcode_claim.py:141`/`quota.py:566` 都有前置判定 → 没打破）；`until_ms` 距离 >24h 时（时钟回拨/手改）标签谎报成「明日」，`until_label` 的「最长 30 分钟所以跨不过两天」前提没有任何约束。

**1e `active()`↔`reason()` 的 mtime 回读竞态（打破成功，N-5）**

```
=== A4 mtime 相同（模拟 exFAT/NFS 秒级时间戳）时的跨进程可见性 ===
gw sees active? False reason: '熔断，至 07:59'
cli sees active? True
```
`_load()` 已经 `read_text` + `json.loads` 拿到新内容，却在 `mtime == self._loaded_mtime` 时把结果**丢掉**（`quota.py:415`）：粗粒度时间戳卷（外接 exFAT/SMB/NFS，或 rsync `-t`/同步盘还原）上，CLI 刚建立的熔断网关看不见——而跨进程可见正是这套设计的唯一理由。改成 `(st_mtime_ns, st_size)` 或直接用已读到的 `raw` 判等价即可。

### 攻击 2：运营互斥 fail closed（`AccountLocks.usable()` / `run_once` / `Scheduler._tick`）

**2a 拒跑轮（打破失败）**——把 `data/ops-locks` 换成 `0o500` 目录，假 claim 计数：

```
usable()  = False
本轮发起的上游调用 = 0 []
failed 条数 = 3
skipped = []
报告 dict = {"success": [], "already_done": [], "inactive": [], "failed": [{"account": "a1", "reason": "运营互斥锁目录不可写：…本轮未对任何账号发起操作（宁可拒跑也不双领）…"}, …
落盘 = /tmp/mgw-accept-7-eng/locks/usage/ops-results-20260928.jsonl
unread_failures = 3
ack_reports = 3  ->  unread after ack = 0
```
→ 零上游发起成立；`failed`（非 `skipped`）成立；落盘、红点、ack 都不吞。

**2b 探测文件本身**（`/tmp/mgw-accept-7-eng/exp_b2.py`）

```
=== B4 残留 .write-probe.lock（崩溃遗留）===
usable() = True | 目录内容 = []
普通账号仍可拿锁: True

=== B6 六个进程并发 usable() ===
PID 89311 usable True   …（6 个全 True）…
结束后目录: []
```
→ 崩溃残留会被下一次 `usable()` 的 `write_text`+`unlink` 自清；并发互 unlink 不产生残留、不挡路。与 `stats/events.py` 的 retention 也不冲突（retention 只 `usage_dir.iterdir()`，`"ops-locks" in events.py → False`）。

**2c BLK-1：轮中失写（打破成功）**

`run_once` 侧——第一个号的锁已建立、目录随后失写：
```
run_once 抛出: PermissionError [Errno 13] Permission denied: '/tmp/mgw-accept-7-eng/locks2/mid/a1.lock'
```
调用栈：`runner.py:431 finally: locks.release(account)` → `:242 _release_file` → `:221 path.unlink(missing_ok=True)`。`missing_ok` 只吞 `FileNotFoundError`，**不吞 `PermissionError`**。整轮以异常收场 → 不返回 report → `write_report` 根本没被调 → `ops-results` 无行、红点不亮。

`Scheduler` 侧（决定性）——同一次失写之后**把权限修好**：
```
目录已恢复可写: True | 探针 usable(): True
恢复后累计跑了几轮: 1 | errors: 0 | 任务存活: False
threading.Lock 是否被永久占住: True
```
成因链：`_tick` 的 `try/except Exception` 覆盖不到**自己的 `finally`**（`runner.py:613 plan_lock.release()`）→ `PlanLock.release()` 在 `:273 self._files.release(...)` 处抛出，后面的 `:275 self._lock.release()` 永不执行 → 异常穿出 `loop()`（`:622 await self._tick(run)` 外无保护）→ 任务结束。此后 `try_acquire()` 第一步 `self._lock.acquire(blocking=False)` 永远 False，而 `usable()` 已经 True，于是**连本轮新加的那条「运营已停摆」日志都不再打**（那条在 `usable()` 分支里，进不去），`errors` 也停在 0。

为什么这次一定伤到用户：`data/` 放外接盘/SMB/NFS 的用户，一次只读重挂载或 chown 就触发；用户按提示把权限修好后，界面上「运营」一切正常、`/admin/api/status` 红点 0、`errors` 0，但领取从此不再发生，直到重启网关——这正是 S-22 立条款要消灭的「运营停摆而进程看着正常」，本轮只堵住了开跑前那一半。
最小修：`_release_file` 的 unlink 用 `contextlib.suppress(OSError)`；`PlanLock.release()` 用 `try/finally` 保证 `self._lock.release()`；`loop()` 把 `await self._tick(run)` 包进 try/except 记 `errors`。三条同时补，判据建议：`run_once` 轮中失写 → 必须返回带 `failed` 的 report 而不是抛；失写→恢复后 `fired>=2` 且 `errors==1`。

**2d 探测文件与账号锁的名字碰撞（打破成功，非阻塞）**

```
HOLDER acquired: True
PROBER usable(): True
SUITOR try_acquire(同一账号): True
```
`_path_in()` 的清洗允许 `.`/`-`，账号名恰好为 `.write-probe` 时，锁文件与探测文件是同一个路径：`usable()` 的 `write_text`+`unlink` 会**销毁别人在飞的锁**，第三个进程随即拿到同一账号 → 双领。触发面很窄（ZCode 账号名由登录侧给出，不会是这串），修法是把探测文件放到不可能被清洗结果命中的位置（如 `tempfile.mkstemp(dir=lock_dir)` 或 `ops-locks/.probe/` 子目录）。

顺带：`_release_file` 抛错时留下的孤儿锁（`残留锁文件: ['bob.lock']`）没有任何保留期清理，账号改名/删除后 `ops-locks/*.lock` 只增不减（S-15b 同族的小缺口）。

### 攻击 3：归一化单一口径（`core/resources.py:21`）

审计全包 `base_url` 站点（`Grep base_url`）+ 功能验证：

```
cli_probe 源码里的拼接: ['url = base_url.rstrip("/") + "/chat/completions"']
probe 拼出的 URL = ' https://api.example.com/v1 /chat/completions'
同一配置在网关侧: 'https://api.example.com/v1'
normalize 幂等: True
probe 同款 URL 真实请求反应: UnsupportedProtocol Request URL is missing an 'http://' or 'https://' protocol.
```
→ **第四处确认**：`model_gateway/cli_probe.py:29`（入参来自 `:114 _make_call_fn(res.base_url, …)`，原始值）。用户粘贴带空格的端点时，网关转发正常而 `mgw probe` 判该资源失败——探测结论与实际行为相反，用户会去"修"一个本来好的配置。`_conn_fingerprint` 与 `main.py:236/241` 与两个适配器构造都同源，没能打破。

排除项（都不是第四处）：`api/admin.py:292` 只 `.strip()`，但值交给 `build_adapter` → `openai_out.py:53`/`anthropic_out.py:452` 内部再 `normalize_base_url`，口径最终一致（实测草稿路径归一化后与运行态同串）；`upstream/zcode/claim.py:164`、`captcha.py:108` 属厂商侧 `plan_base_url`/`site_root`，与资源 `base_url` 不同域。

新发现的小口径缝（非阻塞）：
```
全空格 base_url: '' | `if not r.base_url` 视其为存在: True
```
`main.py:233` 用未归一化的真值判断，`" "` 被当成"有端点"→ 建出 `base_url=""` 的适配器（`normalize_base_url(" ")` = `""`），该资源在界面显示可用、每次请求都失败。判据应写成 `if not normalize_base_url(r.base_url)`。

### 攻击 4：接线护栏（`tests/unit/test_v2_wiring_guard.py`）

先把包与测试整份复制到 `/tmp/mgw-accept-7-eng/wire/`（**不改仓库**），基线 `6 passed in 47.11s`。

**假绿（打破成功，N-4）**——在复制包里种 `_fake/a.py`（真死符号）+ `_fake/c.py`（无 import 关系的同名局部变量 / import 过 a 但调的是 b 的方法）：
```
被抓为死的符号: ['_fake/a.py#DEAD_ONLY_HERE', '_fake/b.py#B', '_fake/b.py#handler', '_fake/c.py#claim_user', '_fake/c.py#local_shadow_user', '_fake/reg.py#dispatch']
_fake/a.py#dead_but_shadowed: 判定=绿  引用文件=['_fake/c.py']
_fake/a.py#A.claim: 判定=绿  引用文件=['_fake/c.py', 'ops/builtin/__init__.py', 'ops/builtin/zcode_claim.py']
```
两个洞：① `_referencing_files_named` 只对**歧义名**要求 import 关系（`:233`），全包唯一名的符号把别处的**局部变量赋值**当引用（`c.py` 里 `dead_but_shadowed = 1`）；② 歧义豁免里 `cls in text` 是**裸子串**（`:234`），单字母类名 `A` 在任何文件文本里都命中 → 连 `ops/builtin/*.py` 这种与 `_fake.a` 毫无关系的文件都来"顶替"。第 ② 条在真包里同样成立：任何短/通用类名（`A`/`Op`/`Row`/`Config`…）都会让它名下所有同名方法自动免检。
`_reaches_module` 的"有 import 关系就算引用"盲区按预期复现（`A.claim` 报绿）。
反向也确认护栏仍有牙：`DEAD_ONLY_HERE`（死常量）、`dispatch`（只被 `importlib`+`getattr` 注册表调起 = 已知假红）都被如实报死。

**canary 自证（打破失败）**——逐个撤掉 S-20 的修复面，跑 `-k planted`：
```
M1 撤 AnnAssign 分支: rc=1 -> 1 failed, 5 deselected in 26.05s
M2 加回 '_'.in name 过滤: rc=1 -> 1 failed, 5 deselected in 28.07s
M3 同名歧义只管方法: rc=1 -> 1 failed, 5 deselected in 28.32s
M4 快照退回 import 期: rc=1 -> 1 failed, 23.35s
M5 去掉定义行排除: rc=1 -> 1 failed
复原后: 6 passed in 48.02s
```
→ 4 颗种子（`DEAD_ANNOTATED_CONSTANT` / `TIMEOUT` 顶替 / import 期快照 / AnnAssign）分别把自证判据打红，复原后同轮转绿；S-20 记录的"变异逐个红"复算成立。

---

## ③ 阻塞项（1 条）

**BLK-1 运营互斥的释放路径没挡 OSError：一次瞬时失写 = 运营永久停摆且零痕迹**

- 位置：`model_gateway/ops/runner.py:221`（`path.unlink(missing_ok=True)` 不吞 `PermissionError`）→ `:242`（`_release_file`）→ `:273`（`PlanLock.release` 里 `_files.release` 先抛，`:275 self._lock.release()` 永不执行）→ `:431`（`run_once` 的 `finally`）→ `:613` + `:622`（`_tick` 的 `finally` 抛出，穿出 `loop()` 的 `await`，任务死亡）。
- 复现：`/tmp/mgw-accept-7-eng/exp_b4.py`（输出见 §2c）——`run()` 里把锁目录 `chmod 0o500`，睡 0.3s 后 `chmod 0o700` 复原，再睡 0.8s：`目录已恢复可写: True | 探针 usable(): True`，但 `任务存活: False`、`跑了几轮: 1`、`errors: 0`、`threading.Lock 永久 locked`。
- 为什么伤用户：`data/` 在外接/网络卷上的用户，一次只读重挂载、磁盘满后的 EROFS、或一次 `chown -R` 就够；他照日志修好权限后，红点、`errors`、界面全都显示正常，领取却从此不再发生，直到重启网关。本轮 S-22 的裁决目的（"绝不静默停摆"）在"开跑后才失写"这一半没有兑现，而 `AccountLocks.usable()` 与 `_tick` 的成因区分恰恰以为它兑现了。
- 建议最小修：`_release_file` 用 `contextlib.suppress(OSError)` + `logger.error`；`PlanLock.release()` 保证 `_lock.release()` 在 `finally`；`loop()` 给 `_tick` 包一层 `except Exception` 并计 `errors`。补两条判据：①轮中失写 → `run_once` 返回含 `failed` 的 report（不抛）；②失写→恢复 → 后续 tick 重新开跑且 `errors>=1`。

---

## ④ 非阻塞（按优先级）

| # | 项 | 落点 | 建议 |
|---|---|---|---|
| N-1 | 旧格式 `circuit.json` 二次拼接「…，至 01:20，至 14:38」并进「最近错误」列 | `quota.py:419` 收下带时刻的 reason + `:349 _with_until` 无判据 | `_load()` 里 `reason.split("，至 ")[0]`（或写盘时清洗一次）；补一条"旧格式文件读一次即规范"的判据 |
| N-2 | `until_ms` 类型不符 → `ValueError/TypeError` 直穿 `get_circuit()`，`mgw zcode claim` 崩栈 | `quota.py:418`（在 try 之外） | `float()` 一并进 try 或加 `_as_float()` 兜底为 0；与 `:414` 注释的承诺一致 |
| N-3 | 归一化第四处：CLI 探测用原始 `base_url` 自己 `rstrip("/")` | `cli_probe.py:29` ← `:114` | 改 `normalize_base_url(base_url)`；顺手把 `main.py:233` 的 `if not r.base_url` 改成 `if not normalize_base_url(r.base_url)`（全空格端点目前会建出空 base 适配器） |
| N-5 | mtime 相等即丢弃已读到的新内容（粗粒度时间戳卷上跨进程熔断看不见） | `quota.py:415` | 比较 `(st_mtime_ns, st_size)`，或既然已经读出 `raw` 就直接按内容等价判 |
| N-6 | 护栏假绿两处：唯一名的局部变量顶替 / `cls in text` 裸子串 | `test_v2_wiring_guard.py:233-234` | 唯一名也要求"该文件 import 过 home 或写出过 home 模块名"；`cls in text` 改成 AST 级 `Name` 类名比对或要求 `cls` 长度/边界匹配。护栏定位是"把人叫过来"，盲区已写在 `:220-224` docstring 里，故不阻塞 |
| N-7 | `.write-probe.lock` 与账号锁同名空间碰撞（可销毁别人在飞的锁） | `runner.py:205` vs `:122-124` | 探测改用 `tempfile.mkstemp(dir=lock_dir)`，或放独立子目录 |
| N-8 | `ops-locks/*.lock` 无保留期清理（release 抛错/账号删除后成孤儿） | `runner.py:216-221` | 与 `stats/events.py:96` 的 retention 同族，按 `LOCK_MAX_AGE_S` 起一轮清扫即可（注意别扫到活的） |
| N-9 | `until_ms` 距 now >24h 时标签仍写「明日」（时钟回拨/手改会踩） | `quota.py:345` | 要么按前提钳制 `until_ms <= now + COOLDOWN_MS`，要么 >24h 时直出日期；同时「过期 reason 仍印过去钟点」可考虑 `_with_until` 里判 `until_ms <= now` 就不拼时刻 |
| N-10 | 既存 N-1（热重载换下的适配器从不 `aclose()`）仍未修 | `main.py:249` vs `:368-376` | 维持第六轮的"等用户定夺"，本轮复核仍在 |

---

## ⑤ 试过但**没能打破**的攻击面

1. **跨进程读时渲染一致性**：两个真实子进程（`/tmp/cli-cwd` 写、`/tmp/gw-cwd` 读）同一份文件 → 同一串「，至 14:27」；文件里不含「明日」。
2. **时刻边界**：23:50/00:05/跨年/同日/`now==until` 五种组合全对，「明日」只在真跨日出现。
3. **过期/0/null/缺字段时 `reason()`**：都退回裸原因或过去钟点，且**全部 6 处生产调用点都先判 `active()`**（`main.py:110`、`cli_zcode.py:232/247`、`zcode_claim.py:141`、`quota.py:566`）→ 没有"未熔断却宣称恢复时刻"的出口。
4. **拒跑轮零上游发起**：假 claim 计数 0，`failed`=参与方数（不是 `skipped`），报告落盘、`unread_failures=3`、`ack_reports` 清 3 且不误吞。
5. **`.write-probe.lock` 残留**：进程崩溃留下的残留文件被下一次 `usable()` 自动清掉，不永久挡任何账号。
6. **并发 `usable()`**：6 个真实进程同时探测 → 全 True、目录清空、无互踩后果。
7. **retention 与探测文件冲突**：retention 只扫 `usage_dir`，`ops-locks` 不在其视野，互不影响。
8. **归一化前三处**：`_conn_fingerprint`、`main.py:236/241`、两个适配器构造同源且幂等；`admin.py` 健康测试把未归一化值交给 `build_adapter` 后仍归一，口径不分叉。
9. **护栏自证**：M1~M5 五个变异逐个把 canary 打红，复原同轮 6 passed；`ALLOWED_NO_REFERRER` 过期检查、多态豁免两条可核验判据都有效。
10. **全量回归**：`683 passed`（与第六轮账本同数）。

---

### 附：本轮纪律自证

```
$ git status --short | grep -E "_fake|_wiring_canary|accept-7"   → （空）
$ find data -newermt "2026-09-28 02:30"                          → （空，data/ 未被写）
$ ls /tmp/mgw-accept-7-eng/                                      → exp_a_circuit.py exp_bc.py exp_b2.py exp_b3.py exp_b4.py d_driver.py d_mutate.py e_misc.py wire/ acc*/ locks*/ config.yaml
```
仓库工作树与本轮开工时首条 `git status` 一致（实测 `29` 个 ` M` + `52` 个既有 `??`，`grep -E "_fake|_wiring_canary|accept-7|/tmp"` → **0 行**），未新增/删除任何文件；`:8300` 实例未动。
