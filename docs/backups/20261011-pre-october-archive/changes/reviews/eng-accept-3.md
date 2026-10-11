# 工程验收 · 第三轮（eng-accept-3）· Python / FastAPI / asyncio 后端实现验收

> 验收日期：2026-09-27　角色：后端实现验收（第三轮）
> 基线：HEAD=`5158cbc`，全部为未提交工作树改动；本轮工作树冻结
> 依据：上轮 `docs/changes/reviews/eng-accept-2.md`（S-1 / S-2 阻塞）+ 开发方账本
> `docs/changes/e2e-records/E2E-20260927-round3-fixes.md`
> 纪律：每条结论附**当轮实跑输出**或 `file:line`；反证必须撤源码；未跑出一律写「未验证」。
> 验证脚本全部在 `/tmp/eng3/`（`quota1.py / leak.py / stream_cancel.py / stale.py / lockrace.py /
> lock2.py / lock3.py / ops.py / capclass.py / cap2.py / captcha_probe.py / visibility.py /
> guard_smuggle.py / revert.sh / revert2.sh`），仓库内**只新增本报告一个文件**。

---

## 一、验收结论：**不通过**（阻塞 8 项：🔴 严重 3 + 🟠 中等 5）

账本 §三 的 11 项返工，行为层面 **6 项我复核为真**（T2 对称性 / T4 熔断落盘 / T5 出口字段 /
T7 路径解析 / T8 锁的静默条件 / T10 护栏确实能红），数字层面**一处不差**（§九）。
但**额度这条主线（S-1 → M-3 → §19 M5-3）没有收敛**：T3 的新判据既挡不住真实流量下的滞后快照（S3-2），
又把合法余量永久拒收（S3-1）；T1 的「余量本质是一把凭据」只做到「一个 rid」（M3-1）；
T6 全新求解器**抛的异常类型和捕获的类型不是同一个类**，生产第一入口即误分类并放大上游请求（S3-3）。
另有 **2 条账本反证主张经真实撤除被推翻**（M3-5 / S3-3 的文案断言），
和 1 条**告警文案是假承诺**（M3-3「跨进程互斥仍然成立」）。

| # | 级别 | 一句话 | 对应上轮 / 账本 |
|---|---|---|---|
| S3-1 | 🔴 | 额度**永久冻结**：上游充值 / 新增额度桶 / 本地耗尽后自锁 → 资源永远不可选，只能重启进程 | 账本 T3 引入的新缺陷 |
| S3-2 | 🔴 | **M-3 未修好**：一次成功结算即污染窗口判据，同一条滞后快照把已消耗的 10 单位整份复活 | 上轮 M-3 / 账本 T3 |
| S3-3 | 🔴 | 求解器异常类 ≠ 捕获类 → 生产路径落 `network:` 误判、重试 3 次、真打 3 次 `billing/preview`；账本 T6 的文案断言实跑为假 | 账本 T6 / §16.4-§16.5 |
| M3-1 | 🟠 | 同一份凭据建成两个 rid 仍**并发超发**（池键只到 rid，没到凭据） | 上轮 S-1 残留 |
| M3-2 | 🟠 | 额度耗尽的资源在健康表仍报 `status=active / available=true`，快照里没有任何额度字段 | §17 / design-spec 资源状态表 |
| M3-3 | 🟠 | 锁退路目录随 `TMPDIR` 分叉 → 两进程同时持有同一账号锁，而告警写着「跨进程互斥仍然成立」 | 上轮 M-2/M-4 同形态 |
| M3-4 | 🟠 | 锁文件无心跳：`mtime` 只在建锁时写一次 → 合法长批次（≥22~77 账号）的 plan 锁被窃取、双批并行 | 上轮 M-2 第④条 |
| M3-5 | 🟠 | 账本 T1「撤掉即红」**不成立**：撤掉 `rebuild()` 的共享池接线 → 25 条额度用例全绿，而缺陷行为复现 | 上轮 S-2（判据形态重演） |

不阻塞但须登记：P-1/P-2/P-3（求解器自愈与收尾三条）、G-1（护栏四向走私）、N-9（跨产品误熔断）、
以及 §六 表内其余 8 项轻微。

> **实况前提**（决定下面所有「已接线」的现实意义）：本机默认账号根
> `data/upstream/zcode/accounts` **不存在**（`store.list_accounts()` → `[]`）→
> `_maybe_start_ops`（`main.py:91-94`）直接返回 `None` → **运营 tick 在本机从未起过**，
> 额度刷新 / 熔断回写 / 验证码链路只存在于测试与验收脚本里。账本 §五 列了未实测项，
> 但没点明「本机连账号都没有」，读者容易把 `602 passed` 读成「实盘可用」。

---

## 二、领域一：额度 / 预留正确性（上轮 S-1 / M-3 / M-5）

### 2.1 已核实为真（正面证据）

**同 rid 多映射共享一把桶** —— 走**真实 `rebuild()`**（不是手搭 registry）：

```
$ .venv/bin/python /tmp/eng3/quota1.py
A) 两个映射是否同一个池对象: True
A) 余量=1 两映射并发: ['z1/glm-4.6', None] reserved= 1
A) 归还后 reserved= 0
```
落点：`core/resources.py:159-165`（`_pool_for`）、`:188` 与 `:197`（rebuild 两处挂池）、
`:205-209`（资源删除时回收池，防同名复用残留）。

**预留/结算/释放对称性** —— 用**真实 `Scheduler` + 假适配器**跑 11 条出口，逐条断言
`reserved==0 && in_flight==0`：

```
$ .venv/bin/python -u /tmp/eng3/leak.py
[ok] 1 成功(非流式)  [ok] 2 上游500耗尽  [ok] 3 客户端断连探测  [ok] 4 任务取消 CancelledError
[ok] 5 预算耗尽      [ok] 6 AUTH 切备用后成功  [ok] 7 流式首帧后中途失败  [ok] 8 流式成功
[ok] 9 流式任务取消  [LEAK] 10 流式消费端提前 break(GeneratorExit): pools={'z1/glm': (1, 1)}
[ok] 11 429 QUOTA 冷却+切换        >>> 泄漏场景数 = 1 / 11
```
第 10 条**不是产品缺陷**：生产消费端不用 `break` 而是 `task.cancel()`（`api/openai_compat.py:226`），
取消在 `core/scheduler.py:634` 处穿到 `finally`（`:723-726`）。按生产形态复跑：

```
$ .venv/bin/python -u /tmp/eng3/stream_cancel.py
取消前 pools: [(1, 1)]  →  pull 出口: CancelledError  →  取消后 pools: [(0, 0)] → 归零
```
`aclose_quiet`（`core/scheduler.py:805-810`）吞 `GeneratorExit` 是有意的，上游连接由被取消的
pull 任务自己关完（`openai_compat.py:227-234` 的注释解释了为什么必须 `asyncio.wait`）。

### 2.2 🔴 S3-1 额度**永久冻结**（三条真实路径）

`core/resources.py:296-298`：

```python
window_reset = pool.used is None or used is None or used < pool.used
if not window_reset and pool.remaining is not None and remaining > pool.remaining:
    return False          # 滞后快照：不复活余量
```

`used` 单调不减 ⇒ **「used 不变而余量应变大」的快照被永久拒收**：

```
$ .venv/bin/python -u /tmp/eng3/stale.py
=== 反例②：上游充值但 used 不变 → 永久冻结 ===
耗尽后: {'remaining': 0, 'reserved': 0, 'used': 100} available() = False
充值快照（连续 5 次刷新）applied = 0 -> {'remaining': 0, 'reserved': 0, 'used': 100}
>>> available() = False：pool.used 永远停在 100 == 快照 used → 每条刷新都被判成滞后快照 → 永久拒收
```

1. **充值 / 新增额度桶**：`total` 100→200、`used` 不变 → 拒收；新桶 `used=0` 时
   `used_total`（`quota.py:278`）同样不变 → 一样拒收；
2. **本地耗尽即自锁**：`remaining=0` → `available()` False → 永不再选路 → `settle_quota` 永不执行 →
   `pool.used` 再也走不动 → 与快照 `used` 恒等 → 恒判「滞后」；
3. **日志通道断供**：`apply_snapshot_to_runtime:274-276` 见 `remaining=None` 直接 return，
   留下的是**旧的 0**，与同文件 `:246-249` 的自述「取不到快照 → 保持 None（未知 ≠ 没额度）；
   否则日志一缺失全部资源就失去服务」**正好相反**：

```
$ .venv/bin/python -c …（配额 0 之后连投 5 次 ok=False 快照）
连续 5 次"日志通道取不到"applied = 0 -> {'remaining': 0, 'reserved': 0, 'used': 100}
```

叠加 M3-2 后用户看到的现象 = **模型仍在 `/v1/models`、健康表全绿、每次调用 503 NO_RESOURCE、
只能重启进程**（`rebuild()` 跨热重载保留 `self.quotas`，改配置也救不回来）。
这正是本轮 T3 立项要消灭的「无报错的失败」，属**修复引入的回归**。

**最小修法**：①`set_quota` 一并接收 `total`，`total` 变大即整份接受；②或按快照的 `period` /
`reset_at` 判窗口翻页；③断供时按自述降级为 `remaining=None` 并告警；
④加陈旧上限（快照龄 > K 个 tick 且 `remaining==0` → 降级不管控 + 告警）。

### 2.3 🔴 S3-2 真实流量下滞后快照照样复活余量（M-3 未修好）

`settle_quota` 自己把 `used` 顶高（`core/resources.py:327` `pool.used += 1`），
而翻页判据是 `used < pool.used` —— **一次成功结算 = 一次假翻页**：

```
$ .venv/bin/python -u /tmp/eng3/stale.py
=== 反例①：结算计数污染窗口翻页判定（M-3 在真实流量下失效）===
快照后: {'remaining': 10, 'reserved': 0, 'used': 90}
10 次结算后: {'remaining': 0, 'reserved': 0, 'used': 100} available() = False
重复投递同一条滞后快照: applied = 1 -> {'remaining': 10, 'reserved': 0, 'used': 90} available() = True
```
上游剩 0、本地已消耗 10，**下一个 tick 把同一条滞后日志快照再投一次，闸门就重新打开 10 单位**；
全程只调用生产函数（`apply_snapshot_to_runtime` → `set_quota`）。
账本 T3 的用例 `tests/unit/test_v2_quota_reservation.py:244-256` 把 `settle` 只写在 `set_quota` 之前、
且只结算 1 次，恰好绕开污染路径 → 12 条用例全绿而缺陷存在。

副作用还要 ×3 倍：本地 `used` 领先上游越多，`window_reset` 越容易为真 → 守卫在活跃流量下**几乎每 tick 失效**，
每次失效都把 T1/T2 攒下的预留成果清零。这同时让账本 D1 的辩护（「预留闸门用最近快照，
tick 级新鲜度足以拦超发」）站不住 —— **tick 级刷新本身就是复活余量的那把钥匙**。

**最小修法**：`settle_quota` 不写 `pool.used`（`used` 只由快照赋值），或判据改用
`remaining + reserved` 与 `total` 对比，把「本地估算消耗」与「上游事实」拆成两个字段。

### 2.4 🟠 M3-1 同一份凭据拆两个资源 id 仍然超发（S-1 残留）

配置层没有凭据去重（`config/schemas.py:259-296` 只校验资源 id / 密钥 id / 模型名唯一），
而 `resource_ids_of_account` 明确支持一个账号 ↔ N 个 rid，`apply_snapshot_to_runtime`
把**同一个 `remaining` 分别写进每个池**：

```
$ .venv/bin/python /tmp/eng3/quota1.py
B) 该账号反查出的资源 id: ['z1', 'z2']
B) 余量=1、同凭据两资源 → 实际放行: [('z1','glm-4.6'), ('z2','glm-4.6')] 总放行数= 2
B) 两个池分别 reserved= {'z1': 1, 'z2': 1}
```
账本 T1 原话「余量本质是**一把凭据**的」，实现只做到「一个 rid」。
**最小修法**：池键改凭据指纹 `(vendor/preset, account, sha256(api_key)[:12])`；
或在 schemas 校验里禁止 `(preset, account, api_key)` 重复并报行号。二者任选其一即闭合。

### 2.5 🟠 M3-2 额度耗尽对用户不可见（与上轮 C6 同一错误形态）

```
$ .venv/bin/python -u /tmp/eng3/visibility.py
条目状态: active | available()（选路用）= False | has_quota()= False
健康表行: {'rid':'z1','name':'Z账号',…,'status':'active','available':True,…,'last_error':None,'models':1}
>>> 用户看到 status/available = active True，而调度器已拒绝该资源；行内没有任何额度字段
>>> 该模型仍在 /v1/models（servable_models 不看额度）: {'sys'}
```
`snapshot_by_resource`（`core/resources.py:358-395`）的状态聚合只看 `e.status`，**不看 `e.available()`**，
也不带额度；`quota_view()`（`:336-339`）**生产零调用**（全包只有 `test_v2_quota_reservation.py:332`）。
T5 把「最近错误」补进快照是对的，但**额度耗尽这一类同样静默的拒绝没有补**，
而它是 §19 M5-3 闸门唯一对用户可见的后果。

**最小修法**：健康表行内加 `quota`（复用 `quota_view`），聚合状态补 `quota_exhausted`，
`dashboard.js:90-106` 的 `resourceHealthTable()` 加一列（该函数已是可执行导出，加列即可）。

### 2.6 🟡 其余（详见 §六表）

`set_quota(rid, None)` 之后 `settle/release` 双双早退 → `reserved` 永久泄漏
（`:292-295` + `:319-334`，实跑 `结算后 reserved = 1` → 重新管控后 `has_room()=False`）。
**当前无生产调用方传 None**（生产唯一写入点 `quota.py:281` 恒带 `used`；
我为此专门复核过 `api/admin.py`：全包 `set_quota` 命中仅 `quota.py:281` + 测试，
先前的相反印象已作废）→ 定级轻微，但**一旦接上「额度可编辑」的管理端点即升中等**。

`pick_and_acquire` 与 `try` 之间的 `_emit_switch`（`core/scheduler.py:352` → `:353-357` → `try` 在 `:367`）
抛出时预留 + 在途双泄漏（注入 `RuntimeError('disk gone')` 实跑 `pools={'z2/glm': (1, 1)}`）。

`set_quota` 不带 `used` 时走 `window_reset=True` 全盘接受（`:296`）—— 目前生产不会走到，属公共 API 陷阱。

---

## 三、领域二：跨进程锁 + 路径解析（上轮 M-2 / M-4 / M-9）

### 3.1 已核实为真

```
$ .venv/bin/python -u /tmp/eng3/lockrace.py
=== 5 个进程 / 5 个不同 cwd 同时抢同一账号 ===
cwd=/ → acquire=False   cwd=/private/tmp → acquire=True（唯一赢家）
cwd=/Users/w/Desktop/Model-Gateway → False   cwd=/Users/w → False   cwd=/private/etc → False
>>> 赢家数 = 1（期望 1）   锁目录 = /private/tmp/eng3/lockcfg/ops-locks（由 MG_CONFIG 派生，与 cwd 无关）
```
- `O_CREAT|O_EXCL` → `write` 的空窗：他人见 `pid=None` 且 `age<2s` → **拒抢**（`ops/runner.py:169-172`）；
- **创建者写完 pid 之前就死**：宽限期内 `acquire=False`，3 秒后回收并 `acquire=True`（**无 livelock**）；
- 主目录与退路**都不可写** → **拒绝拿锁**（不放行）：`acquire = False` +
  `本轮跳过该账号，不冒险双领：acct-deny`（`:210-212`，实测 `lock3.py` ②）；
- `_release_file` 双条件匹配（pid + 本进程令牌），且**建立与删除位置一致**（主目录不可写时实测）：
  `持锁期间 退路: ['acct-loc.lock']`（内容 `55147 <token>`，mode 0600）→ `release 后 退路: []`；
- `_HELD_BY_US` 键 = `(锁目录, 账号)`（`:67`、`:125-131`），实测同进程两处 `run_once` 互相顶掉（§四 ⑤）；
- `Scheduler._tick` 异常不再杀定时器（`:492-506`：warning + `errors += 1` + `finally` 释放 plan 锁）；
- 路径改造面：`main.py:53-60` 的 `DEFAULT_CONFIG/ENUMS/USAGE_DIR/DIALECTS/LOCK_PATH` 全经
  `core/paths.py`（`PROJECT_ROOT` 锚定 + `MG_CONFIG` 优先 + `.resolve()`）；
  从 `/tmp` 跑 `python -m model_gateway.main` → **与仓库实例相撞并 exit=3**
  （`已有实例运行中：后台地址 http://127.0.0.1:8300/（PID 19819…）`），且**不再生成 `/tmp/data`**；
  `instance_lock` 语义未变（M1/M2 的 `tests/integration/test_int_system_proc.py` 全绿）。
- 残余 `Path("data")` 只有两处，都不在生产热路径：`ops/runner.py:425`（`write_report` 缺省分支，
  生产两个调用点 `main.py:115/121` 都显式传 `runtime.usage_dir`）、`config/loader.py:25`
  （兼容常量，全包零引用，实际解析走 `resolve_config_path`）。

### 3.2 🟠 M3-3 退路目录随 `TMPDIR` → 互斥**恰好在其存在的场景里失效**

`fallback_lock_dir()`（`ops/runner.py:87-95`）走 `tempfile.gettempdir()`，
其第一优先来源是**进程环境变量 `TMPDIR`**：GUI/Terminal 起的网关是 `/var/folders/…/T`，
cron / ssh 起的 CLI 通常没有 `TMPDIR` → `/tmp`。主目录不可写时两个进程**各退各的目录**，
双双拿到同一把账号锁，而告警写着「跨进程互斥仍然成立」：

```
$ .venv/bin/python -u /tmp/eng3/lock3.py
A: acquire=True 退路=[…已退回 /tmp/eng3/tmpA/mgw-ops-locks-501，跨进程互斥仍然成立…]
B: acquire=True 退路=[…已退回 /tmp/eng3/tmpB/mgw-ops-locks-501，跨进程互斥仍然成立…]
>>> 同一账号同时持有者 = 2（互斥成立应为 1）
```
多用户机器（账本自己列的 N5）另外一面：本机 `gettempdir()=/var/folders/…/T`（父目录 0700，私有）安全；
`TMPDIR` 未设时落 `/tmp`（world-writable + sticky）、目录名可预测 →
别的 uid 抢先把 `mgw-ops-locks-<uid>` 建成自己的目录，我们两侧都写不了 →
**运营永久空跑**（fail-closed 不双领，但只有 `logger.error`，界面零出口）。

**最小修法**：退路路径写成**常量绝对路径**（不经 `gettempdir()`），建目录 `0700` + 校验属主；
告警必须打印实际退路目录，并把「本周期走过退路 / 两侧都不可写」上报 `/admin/api/overview`
（日志在 nohup 拉起 + 自动关窗的正常路径下等于没人看）。

### 3.3 🟠 M3-4 无心跳 → 15 分钟陈旧窃取把合法批次打掉（实跑双跑）

锁文件 `mtime` 只在建锁时写一次（`_try_create:183-185`），批次期间**没有任何 touch**，
`age` 表示「距上次写入多久」而不是「是否还在干活」。把在飞锁的 mtime 拨到 16 分钟前（等价于
「A 合法持有已超 15 分钟」）：

```
A: acquire=True pid=48571 → LOST-LOCK mid-hold: file now '48594 859e4ecbb07858b5' → HELD-for=12.0s stolen=True
B: acquire=True pid=48594
>>> A 在干活期间锁被 B 抢走（双跑）: True
```
用源码常量把界算出来（`runner.py:39/42/45`、`quota.py:290`、`captcha.py:37`、`claim.py` 各 httpx `timeout=20`）：

| 对象 | 上界算法 | 结果 | 15min 够不够 |
|---|---|---|---|
| **账号锁**（单账号一次 `_run_one`） | 3×（节流 10s + 求解 30s + preview 20 + claim 20 + report 2×20）+ 退避 2s | **≤ ~400s** | ✅ 够（这一半安全） |
| **plan 锁**（整批，`_tick` → `main.py:111-122` = claim 批 + balance 批） | 每账号下界 10s 节流 + 1.2~1.8s 串行间隔 ≈ 11.2~11.8s；带求解（TTL 45s → 约每隔一账号重解 30s）≈ 41.5s | **≥ 77 账号（纯 happy path）／≥ 22 账号（带求解）即超 15 分钟** | ❌ **不安全** |

后果：第二进程起**整批并行**运营，§16.4「串行 + 间隔 + 抖动防风控」的不变量消失
（同账号的**同时**双领仍被账号锁挡住，但「一次只跑一批」已经破了）；
系统时钟向前跳（NTP 校时）也会一次性把所有在飞锁判成陈旧，同样触发双跑。

**最小修法**（任选）：①`run_once` 每账号循环里 `os.utime(lock_path)` 续期（一行心跳）；
②锁内容加 `deadline`，只在超过 deadline 时回收；③`LOCK_MAX_AGE_S = max(15min, 账号数×60s)`。

### 3.4 🟡 半写 pid 绕过写宽限期

宽限期只保护 `pid=None`（`:167-172`）。模拟撕裂写（文件里只有半截数字 `485`，年龄 0.4s）→
`acquire=True`：**宽限期内即被抢**。真实概率低（一次小 `write()` 在 APFS 上近似原子），
但判据应当按**年龄**而不是按**能否解析**：`age < LOCK_WRITE_GRACE_S` 时一律不抢（无论内容）。

---

## 四、领域三：运营注册表 / 新动作（上轮 G2 / G4）

| 动作 | 生产调用点 | 核实 |
|---|---|---|
| `zcode_claim` | `main.py:114`（cron tick）· `cli_zcode.py:226`（CLI） | 注册 + 双入口都真调 |
| `query_balance` | `main.py:120`（**同一 tick 的第二条腿**）→ `query_balance.py:44` → `zq.apply_snapshot_to_runtime` | G2 闭合：不是「只注册」，且额度真的写回运行时池 |
| 额度刷新触发点 | `main.py:125`（启动）· `api/admin.py:348`（管理端点直调 `refresh_runtime_quotas`）· `main.py:120`（tick 经 `query_balance`） | §17 三通道齐；D1 明示只欠「转发成功后 30s 节流补刷」 |
| 3012 熔断两腿 | `zcode_claim.py:117`（进程内 `bench_all_zcode`）· `:121-122` → 管理端点（CLI 腿 `scope=global`） | 「半生效」补上第二条腿 |

参与方过滤与空跑语义（`/tmp/eng3/ops.py`，**cwd=/private/tmp**、`MG_CONFIG` 指 /tmp、
`MGW_ZCODE_ACCOUNTS` 指 /tmp）：

```
product_of_account('acct-real') = 'zcode'      product_of_account('ghost') = ''
① 全部不在产品目录: skipped=[…产品 未知 不在 zcode_claim 的支持范围 zcode 内…] no_participants=true 真实调用次数 = 0
② 声明 other、账号是 zcode: skipped=[…产品 zcode 不在 x_other 的支持范围 other 内] no_participants=true 调用次数 = 0
③ 正常: success=['acct-real']       ④ accounts=None（自动列账号）: success=['acct-real']
⑤ 账号已被本进程持有: skipped=['acct-real']（未再次领取）
```
→ 「全部被过滤掉」确实报 `no_participants` 而不是 success（两个方向都测了）；
`product_of_account` 经 `store.has_account` → `accounts_root()`（缺省值 `store.py:27` 由
`paths.data_dir()` 派生，绝对）→ **换 cwd 仍能查到账号**（④ 实证）。

🟠 N-9（跨产品误熔断，见 §六）：产品判定完全不看本轮新增的 `Resource.product`
（`config/schemas.py:163`，**生产零消费者**），反查走
`resource_ids_of_account` 的 `r.account == 账号名` 字符串相等（`quota.py:500`）→

```
product_of_account('acct-real') = 'zcode'
resource_ids_of_account -> 被运营/熔断扫到的资源: ['res-plain']    ← 一个 product="" 的 OpenAI 按量资源
apply_to_resource(...) → 返回 1，条目状态: ['cooldown']            ← 被 ZCode 全局熔断 bench 30 分钟
```

🟡 附带：`runner.py:394` 把「（无账号参与）」塞进 `OpReport.inactive`（该字段语义是**账号名列表**）
→ `report.total` 把「无人参与」数成 1 条，CLI 的「无资格 1」随之一并虚高（`cli_zcode.py:237-244`）。

---

## 五、领域四：验证码求解器（全新 ~300 行，真机从未跑过）

**未验证面先说清**：本机 `playwright installed: False`（`importlib.util.find_spec` 实测）→
`_default_launcher` / `_run_browser` 的真实浏览器行为（代理参数、`expose_function`、SDK 加载、
F001/T001/T002 真值、真实取消语义）**全部未验证**。以下只判「代码写下来能不能跑」。

### 5.1 🔴 S3-3 异常类型错位：生产路径整体走偏

`upstream/zcode/captcha.py:84` 与 `upstream/zcode/claim.py:66` **各有一个** `CaptchaUnavailable`
（互不为子类），而 `ops/builtin/zcode_claim.py:191` 捕的是 claim 那个。用真实装配（无住宅代理 =
真实用户最常见状态）跑通生产链路：

```
$ .venv/bin/python -u /tmp/eng3/capclass.py
两个 CaptchaUnavailable 是否同一个类: False      互相 issubclass: False
run_once 结果: failed=[{'account':'acct-x','reason':'network: CaptchaUnavailable: 未配置住宅代理，验证码求解不可用 …'}]
claim() 实际被调用次数 = 3（MAX_ATTEMPTS_PER_ACCOUNT） 退避 sleep = [0.5, 1.5, 4.0]  preview 打上游次数 = 3
>>> 被判成网络类（_looks_retryable）= True
```
后果链：
1. `:191-192` 分支在生产里**永不命中**（`_build_client` 恒传求解器；`solve_captcha` 自己那个异常
   只在 `solver is None` 时抛，也不会发生）→ 死分支；
2. 异常落到 `:209-210` 外层 `except Exception` → 前缀 **`network:`** → `_looks_retryable` True →
   **一个确定性本地失败被当网络抖动重试 3 次，每次真打一次 `billing/preview`**
   （§16.4/§17 全部立意在减少风控敏感流量，这里 ×3）；
3. 账本 T6 主张「验证码失败**不带** `network:` 前缀」——**实跑为假**。
   `tests/unit/test_v2_captcha.py` 全篇捕的是 `cap.CaptchaUnavailable`（`:98`、`:132`、`:183`、`:225`），
   从未穿过 `zcode_claim.claim` 的真实类型边界，所以 12 条全绿而缺陷存在（与 M3-5 同形态：反证没走生产入口）。

**最小修法**：只留一个异常类（`claim.py:66` re-export captcha 的，或 `zcode_claim.py:191` 改捕
`captcha.CaptchaUnavailable`），并在外层 `except Exception` 里显式排除它；
补一条**走 `_build_client` + 真 solver** 的断言用例（当前两条「生产接线」用例都 monkeypatch 掉了 `get_solver`）。

### 5.2 干净的部分（值得记一笔）

`asyncio.wait_for(self._run_browser(…))`（`captcha.py:208-209`）**确实能打断** `while True` 轮询
—— 循环体 `await self._sleep(0.2)` 是可取消挂点；`finally: await page.close()`（`:239-244`）
在取消期间仍执行。假件实跑：超时后「1 个页面、`closed=True`、浏览器留待复用」，
**没有页面泄漏**（真实 Playwright 下的取消语义仍属未验证）。
`Runtime.aclose`（`main.py:323-331`）与进程级复用形成对称收尾，方向正确 —— 但见 5.3 第 2 条把这条腿打穿。

### 5.3 🟠 P-1 / P-2 复用浏览器的三条自愈与收尾漏洞

```
$ .venv/bin/python -u /tmp/eng3/cap2.py
① `_browser` 的全部赋值点：__init__ / _ensure_browser / aclose；__call__ 异常分支里复位？ False
   第 1 次: browser crashed → _browser 复位了吗: False
   第 2 次（熔断窗口后）: browser crashed → 再次开的浏览器数 = 1（=1 → 永远用那个已崩的浏览器）
③ 后台刷新跑完后: 启动次数 = 2 | _browser 又非 None 了 = True
$ .venv/bin/python -u /tmp/eng3/captcha_probe.py   （②段）
单例是否换人: True | 旧浏览器 closed 状态 = False | 现场存活浏览器数 = 2
```
1. **崩一次即永久不可用**（P-1）：`__call__` 的 `except`（`:183-186`）只记失败时间、
   不把 `self._browser` 置 None → 之后每 60s 拿同一个死浏览器再试，永不重启（直到进程退出）。
   导航 OOM / Chrome 崩 / 代理断都走这条路。
2. **停机收尾之后重开浏览器**（P-2）：宽限期后台刷新（`:165 asyncio.create_task(…)`，
   **不持引用、不取消、不 await**）在 `Runtime.aclose()` 置 `_browser=None` 之后进 `_ensure_browser`
   → **重新 launch 一个 Chromium**（实跑启动次数 1→2）→ 事件循环随即退出 → 孤儿无头浏览器进程；
   `main.py:447-450` 对 ops task 的 cancel **不会**传播进这个独立任务；
   `create_task` 不保存引用还意味着它可能在飞行中被 GC（asyncio 只持弱引用）。
3. **换参即泄漏旧浏览器**（P-2）：`get_solver()`（`:330-336`）在 `proxy`/`manual` 变化时**同步**换新实例，
   旧实例的浏览器无人 `await aclose()`（实跑：旧浏览器 `closed=False`、现场存活 2 个）。
   一次 cron（`manual=False`）+ 一次 `mgw zcode claim --manual`（`cli_zcode.py:226` 透传 `args.manual`）
   必走这条路。附带：`self._lock` 是**实例级** → 换参瞬间「同进程串行、同时只开一个浏览器」的承诺失效
   （§16.5 进程模型）。

### 5.4 🟠 P-3 失败短熔断：全站封 60s，且与自家文案矛盾

`FAIL_CACHE_MS=60_000`（`:32`）按实例共享 → 一个账号失败后**整批所有账号** 60s 内直接拿
`CaptchaUnavailable`（`:167-170`）；而 `_format_reject` 对 T001/T002 写的是
「验证参数已过期 → **网关会自动刷新重试**」（`:296-298`），实现却对**所有**异常一律熔断（`:184`），
且 tick 缺省 60s（`config/schemas.py:60`）→ 用户看到的正是文案承诺「会自动重试」的那类可恢复错误，
被静默顺延一整轮；批次汇总里也没有「本批 X 个账号因验证码熔断未尝试」的出口（只有红点 + JSONL）。
**最小修法**：参数类（T001/T002）不写 `_failed_at`、清 `_param` 后立刻重解一次；
仅 F001 / 依赖缺失类才熔断；被熔断跳过的账号写进 `report.skipped` 并说明原因。

---

## 六、新发现缺陷汇总（含轻微，每条给最小复现）

| # | 级别 | 缺陷 | 最小复现 / 证据 | 建议修法 |
|---|---|---|---|---|
| S3-1 | 🔴 | 额度永久冻结（充值/新桶、耗尽自锁、断供保旧 0） | `/tmp/eng3/stale.py` 反例②；`quota.py:246-249` vs `:274-276` | `set_quota` 带 `total` 判窗口；断供降级 `None`+告警 |
| S3-2 | 🔴 | 真实流量下滞后快照复活余量（M-3 未修好） | `/tmp/eng3/stale.py` 反例①（`resources.py:327` 污染 `used`） | `settle` 不写 `pool.used`；守卫比对 `remaining+reserved` vs `total` |
| S3-3 | 🔴 | 求解器异常类 ≠ 捕获类 → `network:` 误判 + 3× preview；账本 T6 文案断言为假 | `/tmp/eng3/capclass.py` | 统一异常类 + 走生产入口的用例 |
| M3-1 | 🟠 | 同凭据两 rid 仍并发超发 | `/tmp/eng3/quota1.py` B 段（放行 2） | 池键=凭据指纹，或禁止重复 `(preset,account,api_key)` |
| M3-2 | 🟠 | 额度耗尽仍报 available、快照无额度字段（`quota_view` 生产零调用） | `/tmp/eng3/visibility.py` | `snapshot_by_resource` 带 `quota_view` + 前端一列 |
| M3-3 | 🟠 | 退路锁随 `TMPDIR` 分叉，互斥失效且告警谎称成立 | `/tmp/eng3/lock3.py` ④ | 固定绝对退路 + 打印实际目录 + 上报 overview |
| M3-4 | 🟠 | 锁无心跳 → 合法长批次被窃取（≥22~77 账号） | `/tmp/eng3/lockrace.py` 第二段 `LOST-LOCK mid-hold` | 账号循环 `os.utime` 续期 / 锁内写 deadline |
| M3-5 | 🟠 | 账本 T1「撤掉即红」不成立：`rebuild()` 接线零测试覆盖 | `/tmp/eng3/revert2.sh` R1'：`25 passed` 而缺陷复现 | 补一条走 `rebuild()`（配置→池→选路）的用例 |
| P-1 | 🟠 | 浏览器崩一次后永不重启（`_browser` 不复位） | `/tmp/eng3/cap2.py` ① | `except` 里 `await self.aclose()` |
| P-2 | 🟠 | 停机后重开浏览器（孤儿进程）+ 换参泄漏旧浏览器 + 串行锁随换参失效 | `/tmp/eng3/cap2.py` ③、`captcha_probe.py` ② | 持任务引用 + `_closed` 标志；换参回收旧实例 |
| P-3 | 🟠 | 60s 全站熔断与「会自动刷新重试」文案矛盾，批次内无出口 | `captcha.py:32/184` vs `:296-298`；`schemas.py:60` | 参数类不熔断；跳过账号入 `report.skipped` |
| N-9 | 🟠 | `Resource.product`（本轮新增）零消费者；运营反查按账号名串相等 → **普通按量资源被 ZCode 全局熔断 bench 30min** | §四 末实跑：`resource_ids_of_account → ['res-plain']`、`apply_to_resource → ['cooldown']` | `resource_ids_of_account` 增加 `r.product == PRODUCT`（或 preset 白名单）过滤 |
| G-1 | 🟠 | 接线护栏四向走私全绿 | `/tmp/eng3/guard_smuggle.py` 四段全 `4 passed` | 覆盖面自动导（`git diff --name-only HEAD`），含类方法、模块级常量、pydantic 字段 |
| N-1 | 🟡 | `set_quota(rid, None)` 后 `settle/release` 早退 → `reserved` 永久泄漏（生产暂无调用方） | `leak.py` 12：`结算后 reserved = 1` | `settle/release` 无条件减 `reserved`，`None` 只影响扣减 |
| N-2 | 🟡 | `pick_and_acquire` 与 `try` 之间 `_emit_switch` 抛出 → 预留+在途双泄漏 | 注入 `RuntimeError` → `pools={'z2/glm': (1, 1)}` | acquire 移进 `try`，或 emit 包 `except: 归还` |
| N-3 | 🟡 | 半写 pid 绕过 2s 写宽限期（宽限期只保护 pid=None） | `lock2.py` ①：0.4s 龄即 `acquire=True` | 一律按年龄判，不看内容 |
| N-4 | 🟡 | `set_quota` 不带 `used` 即全盘接受 raise（公共 API 陷阱） | `resources.py:296` | 缺 `used` 视为同窗口，只允许调低 |
| N-5 | 🟡 | `store.accounts_root()` 不 `.resolve()`，相对 `MGW_ZCODE_ACCOUNTS` 让账号根与 `circuit.json` 随 cwd 分裂 | 实跑：相对 env 下 `circuit_path()= circuit.json`（相对） | 返回前 `.resolve()`（对齐 `core/paths.py:15`） |
| N-6 | 🟡 | `OpReport.inactive` 混入「（无账号参与）」→ `total`/CLI 计数虚高 1 | `ops.py` ① 输出 | 由 `no_participants` 单独承载 |
| N-7 | 🟡 | `write_report` 缺省仍 `Path("data")/"usage"`；CLI 腿根本不调 `write_report` → 「结果落 JSONL」只覆盖 cron 腿 | `grep write_report` → 仅 `main.py:115/121` + 测试 | 缺省改 `paths.data_dir()`；CLI 也落盘或文案说明只打印 |
| N-8 | 🟡 | 口径与实现相反三处：`remaining_units`「1 请求预留 1 单位」（`quota.py:232`，实际由 `set_quota` 整份替换）；`refresh_runtime_quotas` 文档「取不到 → 保持 None」（`:246-249`，实际保持旧值）；同函数文档仍引用已不存在的 `ResourceState.quota_remaining`（`:242`） | `visibility.py` / §2.2 / §2.3 | 文档随实现改写；`settle` 的 ±1 标明是本地估算而非上游量纲 |

---

## 七、反证核查表（账本 §三「撤掉即红」逐条复跑）

变异前 `cp` 备份到 `/tmp/eng3/bak/`，跑完还原。
md5（前=后，逐字节）：`resources.py 057ea11f…` / `runner.py 3ecb03de…` / `zcode_claim.py 1fb951b3…` /
`quota.py f29e475d…` / `loader.py 969120f5…` / `paths.py b92ba674…` / `main.py ae83880a…`。

| 账本主张 | 我撤掉的东西 | 实跑结果 | 判定 |
|---|---|---|---|
| T1「改后该用例红」 | `rebuild()` 的共享池接线（`:188`、`:197` 两处，diff 已打印证明生效） | **`25 passed`**（`test_v2_quota_reservation.py` + `test_int_v2_quota_reserve.py`），而同一次变异让真实行为退回「余量 1 放行 2」 | ❌ **不成立**（M3-5） |
| T2 对称性（签名级钉死） | 给 `reserve_quota` 加回 `amount` | `1 failed test_reserve_settle_release_are_symmetric` | ✅ |
| T3 滞后快照 | 删掉单调性判定 | `1 failed test_stale_snapshot_cannot_resurrect_spent_quota` | ✅（守卫存在，但守卫本身有 S3-1/S3-2） |
| T4 墙上时钟落盘 | `_epoch_ms` 换回 `monotonic` | `1 failed test_circuit_persists_wall_clock_not_monotonic` | ✅ |
| T5 熔断原因出口 | 快照去掉 `last_error` | `2 failed`（后端 `test_overview_surfaces_circuit_reason` + 单测）；`ui_verify_v2_visible.py` → `后端 12 项 / 通过 11 / 失败 1：✗ overview 资源项带 last_error` | ✅ |
| T6 恒接求解器 | `_build_client` 摘掉 `captcha_solver=` | `1 failed test_production_client_always_gets_a_solver` | ✅ 装配层；同项「不带 network: 前缀」被 S3-3 推翻 ❌ |
| T7 路径来源 | `ops_lock_dir()` 退回 `Path("data")` | **2 failed**：`test_v2_servable.py::test_ops_lock_dir_ignores_cwd` / `::test_ops_lock_dir_follows_mg_config` | ✅ 与账本「2 条红」逐条一致 |
| T8③ 写宽限期 | 去掉 `age < LOCK_WRITE_GRACE_S` 分支 | `1 failed test_fresh_unreadable_lock_is_not_stolen` | ✅ |
| T10 护栏能红 | ——（改用走私测试代替撤除） | 四种死代码形态全部 `4 passed`（§八） | ❌ 覆盖不足（G-1） |

> **自记一次假阴性**：我第一次跑 T7 变异时在 `test_v2_ops.py` 里找用例（那两条实际在
> `test_v2_servable.py`），得到「62 passed」的错误结论；随后定位到正确文件并用 `revert2.sh` 重做。
> 现结论以重做为准。

> **M3-5 的成因**（决定这类反证的可信度）：`tests/unit/test_v2_quota_reservation.py` 全部用
> `_state(..., quota=shared)` + `_mgr_with(...)` **手工拼装** registry/pools/quotas
> （`:126-172`；整个文件里 `rebuild` 只出现在注释中），4 条端到端
> （`tests/integration/test_int_v2_quota_reserve.py:33/61/75`）传的是 `set_quota(state对象, n)`
> → 两条路都**不经过** `rebuild()` 里真正决定「谁和谁共用一把桶」的那两行。
> 撤掉接线后缺陷回来了、测试照样全绿。判据：**反证必须变异生产装配点**，不能只变异数据结构。

---

## 八、接线护栏走私测试（`tests/unit/test_v2_wiring_guard.py`）

基线 `_population()` = **133** 个符号。四种形态，**每一种护栏都全绿**：

| 走私形态 | 做法 | 护栏结果 |
|---|---|---|
| ① 未纳入 `V2_MODULES` 的改动文件 | `config/loader.py` 加两个互相引用的死公开函数（该文件本轮被改，却不在清单里） | `4 passed` |
| ② 类方法 | `ResourceManager` 加 `completely_dead_method`（`_public_symbols` 只看模块级 def/class） | `4 passed` |
| ③ 「公开符号只被私有死函数引用」 | `core/paths.py`（清单内）加 `dead_but_privately_referenced` + `_nobody_calls_this` | `4 passed`；`_referencing_files` 返回 `['model_gateway/core/paths.py']`（同模块自引用即算已接线） |
| ④ 主入口 / 其余改动文件 | `main.py` 加 `totally_unwired_main_symbol`。本轮被改动却不在清单里的共 **4 个**：`config/loader.py`、`config/schemas.py`、`enums/matcher.py`、`main.py` | `4 passed` |

结论：护栏能挡「全包零引用的**模块级公开函数**」，挡不住本轮 S-2 的原形态 ——
「接了，但接在没人走的地方 / 接在死码里」。另外两类结构性盲区：**模块级常量不在导出集**
（`ACCOUNT_PRODUCTS` 生产零引用、仅 `test_v2_ops.py:638` 用；`Resource.product` 新字段零消费者）、
**pydantic 字段也不在导出集**（`_public_symbols` 只采 `FunctionDef/AsyncFunctionDef/ClassDef`）。
清单本身仍是**手挑 30 个文件** —— 与账本 C1 对上一版的批评（「覆盖集是人手挑的，结构上必然漏」）
**同一形态**；账本只承认了一半（重做为「自动导出」，但导出范围依旧是人工枚举的模块表）。

---

## 九、复跑数字对照（逐条，抄自运行器输出）

| 项 | 账本 | 本轮复跑 | 判定 |
|---|---|---|---|
| 全量 | `602 passed, 452 warnings in 80.02s` | `602 passed, 452 warnings in 81.21s`（`--basetemp=/tmp/eng3-pytest`）；收工后再跑 `602 passed … in 79.69s` | ✅ |
| `unit/test_v2_ops.py` | 61 | 61 | ✅ |
| `unit/test_v2_quota_reservation.py` | 21 | 21 | ✅ |
| `unit/test_v2_servable.py` | 14 | 14 | ✅ |
| `unit/test_v2_circuit.py` | 13 | 13 | ✅ |
| `unit/test_v2_wiring_guard.py` | 4 | 4 | ✅ |
| `unit/test_v2_zcode.py` | 37 | 37 | ✅ |
| `unit/test_v2_captcha.py` | 12 | 12 | ✅ |
| `unit/test_v2_claim_wiring.py` | 10 | 10 | ✅ |
| `unit/test_v2_cli_zcode.py` | 20 | 20 | ✅ |
| `unit/test_v2_cli.py` | 19 | 19 | ✅ |
| `unit/test_config.py` | 28 | 28 | ✅ |
| `integration/test_int_chat.py` | 24 | 24 | ✅ |
| `integration/test_int_v2_servable.py` | 7 | 7 | ✅ |
| `integration/test_int_v2_zcode_admin.py` | 13 | 13 | ✅ |
| `integration/test_int_v2_quota_reserve.py` | 4 | 4 | ✅ |
| `integration/test_int_v2_ops_isolation.py` | 1 | 1 | ✅ |
| `scripts/ui_verify_v2_visible.py` | 12/12 + 35/35，exit 0 | `后端出口实测 12 项，通过 12 项，失败 0 项` / `实测 35 项，通过 35 项，失败 0 项`，`exit=0` | ✅ |
| 顺序无关（进程级单例 `_HELD_BY_US` / `_CIRCUIT` / `_SOLVER`） | 未主张 | `ops + circuit + captcha` 正序 `86 passed`、倒序 `86 passed` | ✅ |
| 账本点名的 9 条用例是否存在 | T7/T8/T4 等 | 逐条 `grep -rl "def <name>" tests` 命中（61 条 ops、13 条 circuit 等全在） | ✅ |

**数字层面无一处不符 —— 本轮所有问题都在行为与判据层，不在计数层。**
账本 §一/§四 的历史轨迹（537→602）与 C4/C5 的既往数字属历史事实，无法复跑：未验证。

---

## 十、未验证清单（显式）

- **Playwright 真实行为全部未验证**（本机未装 `playwright`）：`chromium.launch(proxy=…)`、
  `page.goto`/`set_content`/`expose_function`、阿里云 SDK 与 F001/T001/T002 真值、
  真实取消期间 `page.close()` 能否走完。`httpx.AsyncClient(proxy=…)` 在实装 0.28.1 下参数合法（核过签名），
  真实代理行为未验证。
- 真实浏览器渲染：沿用账本自述（headless Chrome 加载真实页面会挂）。两列只由
  `scripts/verify_v2_frontend.mjs:67-84` 以「真实函数 + 结构断言」验证，**我没在真实浏览器里看到过它们**；
  `web/static/js/pages/resources.js`（模型资源页）没有 `last_error` 列，只有总览页有 —— 口径归 PM/IX 定。
- 跨 uid 抢占退路目录：只证了「同 uid + `TMPDIR` 分叉」，未实跑第二 uid（无第二账户）。
- ZCode 真实凭据 / 额度量纲 / `client/configs` 字段时效 / 真机能否过无痕：未验证（账本 N1–N4 同向）。
- 本轮我**未审计**的范围（不代表通过）：T9（`mgw setup` 优先取运行中网关）只核对了用例存在与通过；
  T11 ①–④ 纯文案项、`enums/matcher.py` 与 `stats/*` 的 v2.0 改动、前端呈现细节 —— 均属未验证。

---

## 十一、诚实声明

1. 每条「成立 / 不成立」都附当轮实跑输出或 `file:line`；跑不出来的一律写「未验证」；
   不替开发方圆场，也不给自己圆场。
2. **我自己的两次错误，点名记录**：
   ① §七 末：T7 变异第一次在错误的测试文件里找用例，得到「62 passed」的假阴性，已定位到
   `test_v2_servable.py` 重做，现结论以重做为准；
   ② §2.6：我一度根据被截断的检索输出误认为 `api/admin.py` 存在 `set_quota` 调用点，
   落笔前用 `Grep` 复核 —— 全包命中仅 `upstream/zcode/quota.py:281` + 测试，故 N-1 定级「轻微（当前不可达）」；
   若日后接上额度可编辑的管理端点，N-1 **立即升中等**。
3. 全部验证代码在 `/tmp/eng3/`，**仓库内只新增本报告一个文件**；为反证（8 项变异）与护栏走私
   （4 项变异）改过的 7 个源文件已逐一还原，md5 与变异前备份逐字节相同（§七 列出全值）。
   未修改任何测试、规范、配置。
4. 未重启 `:8300` 的旧实例（pid 19819 仍在跑本轮之前的代码，与账本 §五 ⚠️ 自述一致）、未绑定端口；
   为验证单实例锁的 cwd 语义，从 `/tmp` 触发过一次 `python -m model_gateway.main`，
   它在锁判定处即 `exit=3` 退出（未写锁、未建 Runtime、未写 `data/`，`ls /tmp/data` 为空）；
   仓库 `data/` 的 mtime 变化全部来自那个一直在跑的实例自身；
   未触碰 `~/.zcode`、`~/.workbuddy`、`~/.workbuddy-ai`；全程零外网
   （假适配器 + `httpx.MockTransport`，唯一真实连接尝试是对 `127.0.0.1` / 不存在端口的失败连接）。
5. 我没有「顺手修」任何缺陷：§六 每条只给最小修法建议，取舍由开发方与需求真相（`docs/specs/`）定。
6. **收工自检（同轮实跑）**：`git diff --stat` = `26 files changed, 2241 insertions(+), 101 deletions(-)`，
   与开工基线一致；`ls -la docs/changes/reviews/eng-accept-3.md` 存在（见 §〇 附）；
   反证与走私全部做完之后再跑一次全量 → `602 passed, 452 warnings in 79.69s`，
   即验收动作没有把工作树留在任何变异状态。
