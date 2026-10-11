# 第八轮产品验收（PM · 只验收不改码）— 2026-09-28

验收人：资深产品经理（独立核验，未采信实现者自述）
被验对象：HEAD 工作区（`git log --oneline -1` = `5158cbc`，S-23~S-27 为**未提交的工作区改动**）
实验沙箱：`/tmp/mgw-pm8/`（临时 config + 注入时钟 + 独立临时实例 8399）；仓库 `data/` 只读、`~/.zcode*` 未碰、未发真实上游请求、未重启/干扰 `:8300`。

---

## ① 结论：**不通过（1 项阻塞）**

S-22 / S-24 / S-26④ 三条在用户侧**可分辨**、文档一致性基本成立、`§20` 未越界、三个机械门全部复跑通过且数字与记录一致。
但 **S-23 只修到"公式层"，没修到"时基层"**：渲染恢复时刻用的输入是 `time.monotonic()`（开机计时），而 `fmt_recovery_clock` 把它当墙钟塞进 `time.localtime()`。
我在**真实 app + 真实路由**上复现到用户实际会读到的那一串是 `…，至 10:40`，而当时墙钟 15:05、真实恢复时刻 15:35 —— 与同一行的「冷却剩余 1799796ms（≈30 分钟）」自相矛盾。
这正是第七轮我判"有条件通过"的那一条（两个出口互相矛盾）**换了一层皮仍在**：CLI ⚠ 块（墙钟）与「最近错误」列（单调钟）在真实部署里仍然各说各话。连续第八轮里第二次"修了一半自称收敛"，按铁律 3/5 不得放行。

---

## ② 逐项验收表（我跑了什么 / 读到什么 / 判定）

### 2.1 三个机械门（我亲自复跑，逐字贴输出）

| 门 | 我跑的命令 | 我看到的原文（tail） | 与记录是否一致 |
|---|---|---|---|
| pytest | `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest-pm8 -p no:warnings` | `693 passed in 125.75s (0:02:05)` | ✅ 与 `E2E-20260928-round5-fixes.md` 第七轮表下「693 passed」一致 |
| 前端门 | `node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json` | `实测 69 项，通过 69 项，失败 0 项` | ✅ 与「实测 69 项，失败 0 项」一致 |
| 前端门变异 | 同上 + `--mutation` | `可红 62/62；每条断言都有对应变异` | ✅ 与「62/62」一致 |
| 后端出口门 | `.venv/bin/python scripts/ui_verify_v2_visible.py --mutation` | `后端出口实测 12 项，通过 12 项，失败 0 项` | ✅ 与「12/12」一致 |

判定：**门本身是绿的、数字没吹**；但绿门没有覆盖本轮阻塞项（见 2.2 末"门为什么没抓到"）。

### 2.2 S-23 的产品面：两个出口在同一读取时刻是否同一句话

我造的载荷（`/tmp/mgw-pm8/check2.py`）：冻结墙钟 23:50 熔 30 分钟 → `CooldownManager(path=/tmp/mgw-pm8/circuit2.json, now=注入)` 落盘，再由**同一起点**经 `apply_to_resource()` 回写资源冷却，然后逐时刻读两个出口。原文：

```
落盘 circuit.json 原文：{"until_ms": 1790612400000.0, "reason": "ZCode 风控熔断（30min，全局）", "last_call_ms": 1790610600000.0}
（文件里只有裸原因，没有任何钟点 ✅）

  23:55 | CLI='ZCode 风控熔断（30min，全局），至 明日 00:20'
        | 列 ='ZCode 风控熔断（30min，全局），至 明日 00:20'   → 同一句话？是
  00:05 | CLI='ZCode 风控熔断（30min，全局），至 00:20'
        | 列 ='ZCode 风控熔断（30min，全局），至 00:20'        → 同一句话？是
00:21 到期 | CLI='ZCode 风控熔断（30min，全局），至 00:20'（active=False，该串不会被打出）
           | 列 ='ZCode 风控熔断（30min，全局）'                → 只留原因、不配钟点 ✅
```

- 判定：**口径结构成立** —— 同一份落盘状态在午夜前后各自说得对；跨午夜加「明日」、同日不加；到期后那一列**不再配钟点**（`_rendered_last_error`：`status=="cooldown" and cooldown_until>now_s` 才配，`core/resources.py:204-212`），符合 Q28-⑦① 与 §17 注记。
- 旧格式（文件里烘死「，至 明日 00:20」）也被归一化：`00:05 读 → '…，至 00:20'`（只有一个钟点），`mark_called()` 回写后文件里 `reason` 变回裸原因 ✅；`without_clock_suffix("上游 401，至 12:30") → "上游 401"` ✅。
- CLI 把**已渲染过**的串传给 bench 端点时不会拼成两个钟点：真实 HTTP 回环里我故意 POST `reason="ZCode 风控熔断（30min，全局），至 99:99"`，列里只出现一个新钟点、没有 `99:99` ✅。

**🔴 但生产时基是错的（阻塞项 B-1，见 ③）**：把管理器换成 `main.py:188` 的**生产默认构造**（`ResourceManager()`，`clock=time.monotonic`，`core/resources.py:252`）后：

```
-- 生产默认（main.py:188 ResourceManager()）--
   列 = 'ZCode 额度耗尽，至 10:38' | 冷却剩余(ms) = 1799999
   真实墙钟口径应为 = 至 15:33        mgr.clock() 是 time.monotonic？ True
```

门为什么没抓到（我核对到具体断言）：
- `tests/integration/test_int_v2_circuit_boot.py:65` 只断**形状** `re.search(r"，至 (?:明日 )?\d{2}:\d{2}$", …last_error)` —— 一个毫无意义的钟点照样满足；它用的正是 `gw.runtime.resources`（生产默认钟），所以"跑的是真路径、验的是假口径"。
- 单元侧要么注入墙钟（`test_v2_circuit.py:617 ResourceManager(clock=lambda: t[0])`），要么显式传 `now_s=0.0`（`test_v2_servable.py:254`、`test_v2_circuit.py:244-287`）。
- 讽刺的是同文件 `test_v2_circuit.py:108 test_circuit_persists_wall_clock_not_monotonic` 早已立过"落盘必须墙钟、monotonic 跨重启无意义"的纪律 —— 本次只是把同一条纪律漏给了**渲染输入**。

### 2.3 S-22 互斥建不起来 → 整轮拒跑（用户侧可分辨性）

`/tmp/mgw-pm8/check.py` 实验（把锁目录 `chmod 0o500`，注入假 claim 记录是否发起过操作）原文：

```
usable() = False
failed 条数 = 2 | skipped = [] | success = 0
是否向任何账号发起操作（应为 0）: 0 []
failed[0] 原文: "('acc-1', '运营互斥锁目录不可写：/tmp/mgw-pm8/locks-ro —— 跨进程互斥建立不起来，本轮未对任何账号发起操作（宁可拒跑也不双领）。请检查数据目录权限或是否被只读挂载')"
run_once 里是否还有 /tmp 退路：hasattr(runner_mod,'fallback_lock_dir') = False
```

- 判据要点逐条对上 Q28-⑦②：拒跑 ✅ / 逐个记 `failed`（不是 `skipped`）✅ / 写明"未对任何账号发起 + 请检查数据目录权限"✅ / `/tmp` 退路已删净 ✅。
- 用户侧可分辨：CLI 腿 —— `report.failed` 有内容即打红字明细并 `return 1`（`cli_zcode.py:283-296`），熔断优先于失败时 `return 3`；网关 cron 腿 —— `main.py:161/166` 仍 `write_report`，`failed` 行进 `ops-results-*.jsonl` → **顶栏红点点得亮**（Q28-⑥① 的唯一事实源成立）。
- 退出码语义成文：`--help` epilog（`cli.py:62-65`，含"3 与 `mgw setup` 的 3 同码不同义"）+ `README.zh-CN.md:110-113` + `README.md:113-117` 双语均写明 0/1/2/3 ✅。
- ⚠️ 非阻塞缺口见 ④-N1（plan 锁"建不起来"只落日志，界面无出口）。

### 2.4 S-24 中途失写 → 定时器必须活着

实验原文（先持锁再 `chmod 0o500`）：

```
先拿到账号锁: True
目录改只读后 release() 未抛异常 ✓
权限恢复后 usable() = True | 同进程能否重新领 = True
plan 拿到: True
PlanLock.release() 未抛 ✓
threading 锁是否被永久卡住（能再拿到 = 没卡）: True
目录建不起来时：run 被调用 0 次（应 0），errors=1（应 >=1）
单轮抛异常后：共跑了 2 轮（应 2 = 任务没死），errors=2（应 2）
```

- 判定 ✅：账号锁释放吞 OSError 并留日志（`runner.py:217-231`）、`PlanLock.release()` 用 `try/finally` 保证进程内锁必放（`:284-293`）、`_tick()` 收尾 `except Exception` 计错误不终止调度（`:625-640`）。三条合起来 = "权限修好后运营仍能继续跑"，与用户裁决一致。

### 2.5 S-26④ 结果落不了盘 → CLI 当场改口

实验原文（`usage/` 设只读，先经 `run_once` 得到 1 条 failed）：

```
run_once failed: 1
write_report 返回: None
是否留痕: [ERROR] 运营结果落盘失败（/tmp/mgw-pm8/usage-ro：[Errno 13] Permission denied: '…/ops-results-20260928.jsonl'）→ 本轮明细未写入 /tmp/mgw-pm8/usage-ro，顶栏红点不会点亮这些失败；请检查数据目录权限
恢复可写后: /tmp/mgw-pm8/usage-ro/ops-results-20260928.jsonl | 累计日志条数: 1
```

CLI 侧代码核对：`results_path is None and report.failed` → stderr 打印「⚠ 本轮结果未能写入 …（数据目录不可写？）→ 顶栏红点不会记录这些失败，逐条原因只存在于本终端的输出与网关日志里」（`cli_zcode.py:239-247`）✅ 不谎报、不把人指到空文件。
附带核对 S-26①⑤（`_ms_or_zero`）：`_ms_or_zero("abc")=0.0 / None=0.0 / []=0.0`，坏数字文件下 `active()=False、reason()='x'`、**无 traceback** ✅。

### 2.6 文档一致性（逐条）

| 断言 | 代码/文档现状 | 判定 |
|---|---|---|
| PRD 第 3 行版本 = v1.17 | `prd.md:3` `> 版本：v1.17（Q28-⑦ 熔断时刻读时渲染 + 运营互斥 fail closed …）`；文末 `:796` 有 v1.17 变更记录 | ✅ 已到档 |
| Q28-⑥ / Q28-⑦ 两节存在且与实现相符 | `prd.md:768`（⑥八项）/`:783`（⑦两项）；⑥③④⑤⑥⑦⑧ 与 `resources.py:372-412`（终态不被覆盖 / 冷却只延长 / bench 返回所有权）、`:21 _conn_fingerprint`、`runner.py` 逐条对得上 | ✅ 相符（本轮未发现"文档有、代码无"的空头裁决） |
| Q28-⑦① 「CLI 的 ⚠ 块、`last_error`、日志同用一份口径」 | 三个出口确实各就各位：CLI `cli_zcode.py:248/257 → circuit.reason()`；列 `resources.py:556 → _rendered_last_error`；日志 `main.py:113/116/120 → circuit.reason()`。口径链：`quota.until_label()` → `resources.fmt_recovery_clock()`（`quota.py:361`，单一实现） | ✅ **实质成立**；🔴 **但在生产时基下"同一句话"不成立**（B-1）；⚠ 命名口径 PRD 写 `quota.until_label()`、tech-design 写 `fmt_recovery_clock`（`tech-design.md:1280`）——两处都对，但指的不是同一层函数，见 ④-N2 |
| tech-design §17 背离注记能否阻止后来人改回旧字面 | `:1271` 表格行就地标 ⚠️「已被 PRD v1.17 / Q28-⑦ 推翻」；`:1278-1288` 注记含：读时渲染、唯一口径点名 `fmt_recovery_clock`、"到期不配钟点（给历史行挂过去的时刻等于说谎）"、末行「**后来人请勿按上面表格的字面把时刻改回写入时拼**」 | ✅ 足以阻止"改回写入时烘死"；🔴 但注记**没写"渲染输入必须是墙钟"**，正是这条漏项放走了 B-1 |
| README / design-spec / frontend-spec 是否残留旧口径 | `grep -rn "至 HH:MM|明日|/tmp" README.md README.zh-CN.md docs/specs/design-spec.md docs/specs/frontend-spec.md` → 命中 0（仅 tech-design/prd 命中，且都是"推翻/修正"语境）；README 两处退出码段为新版语义 | ✅ 无残留旧口径 |
| 实现者自述（第七轮补做表）数字 | 与我的复跑逐字一致（693 / 69 / 62/62 / 12/12） | ✅ 未 over-claim 数字 |

### 2.7 §20 对表（本轮新增物是否越界）

| 新增物 | 落点 | 是否违反"不做清单" |
|---|---|---|
| `AccountLocks.usable()` / `PlanLock.usable()` | `runner.py:200-215`（`.write-probe` 试写后即删，纯探测） | ✅ 不新增页面/端点/轮询/第二本账；它只是把同一个 `try_acquire()==False` 的**成因**分开，正是 Q28-⑦② 要求 |
| `.write-probe` 落盘文件 | 锁目录内的瞬态探针（`probe.unlink(missing_ok=True)`，suppress） | ✅ 不是第二本账（不记状态、不参与判据）；🔴 命名与自述不完全一致：自述/表格写作 `.write-probe.lock`，代码实际是 `.write-probe`（`runner.py:205`）→ 见 ④-N3；unlink 失败时会留一个孤儿文件（`LOCK_MAX_AGE_S` 之外无人回收）→ 归入 ④-N4 |
| `_ms_or_zero()` | `quota.py:337-348` | ✅ 容错读取，无新增机制/记账 |
| 页名常量 `ROUTE_POOL_PAGE` / `RESOURCE_PAGE` / `OVERVIEW_HEALTH_PAGE` | `resources.py:214-216`，`main.py`/`cli_setup.py` 共用 | ✅ 单一事实源，不新增页面；且被后端门 `J1/J2` 双向钉住（我在前端门 `--mutation` 里看到对应变异条目取红） |
| `_rendered_last_error` / `without_clock_suffix` / `fmt_recovery_clock` | `resources.py:154-212` | ✅ 读时渲染，未加轮询、未加字段、未加端点（仍走既有 `snapshot_by_resource`） |
| 「到期保留历史原因」 | `_lift_if_expired`（`:499-514` 明确**不**清 `last_error`） | ✅ 与 Q28-⑥④/S-15 定稿一致，未开新账 |

**未发现**新页面 / 新端点 / 新轮询 / 第二本账 / 产品化包装（无通知中心、无告警框架，§21.3 三条原则未被稀释）。

---

## ③ 阻塞项（1 项，含复现）

### B-1「最近错误」列的恢复时刻在**生产时基**下是假钟点，与 CLI 出口仍然矛盾（S-23 修了一半）

- 现象（真实 app + 真实路由，端口 8399 临时实例、临时 config、空账号根 = 零上游请求）：

```
POST /admin/api/zcode/bench → {'ok': True, 'scope': 'account', 'account': 'acct-e2e', 'benched': 2}
墙钟真实墙钟 now+30min = 15:35 | 现在 = 15:05
用户实际读到的「最近错误」列 = 'ZCode 风控熔断（30min，全局），至 10:40'
同行 status/cooldown_remaining_ms = cooldown 1799796
→ 该钟点是否等于真实恢复时刻？ 否（渲染的不是墙钟）
```

  同一行里「冷却剩余 ≈ 30 分钟」和「至 10:40」互相打脸；用户照这一列判断"什么时候可以重试"必然判错（本轮 15:35 恢复，界面说 10:40 已过）。
- 根因（`file:line`）：`core/resources.py:252` `def __init__(self, clock=time.monotonic)` → `main.py:188 self.resources = ResourceManager()`（`grep -n clock model_gateway/main.py` = **0 命中**，无任何地方把时钟换成墙钟）→ `bench()` 把 `cooldown_until` 记成单调秒（`:392`）→ `snapshot_by_resource` 把它连同 `self.clock()` 一起交给 `fmt_recovery_clock`（`:556` → `:211` → `:167-178`），而后者用 `time.localtime()` 当墙钟解析。
- 连带后果：`fmt_recovery_clock` 的「明日」分支比较的是 `(tm_year, tm_yday)` —— 单调钟下两者都是"1970 年 + 开机天数"，**跨真实午夜时 99% 情况下不会说「明日」**，而偶尔开机时长刚好跨过单调日的午夜时会**无缘无故地说「明日」**。Q28-⑦① 花大篇幅裁决的"跨日才加明日"在生产里不成立。
- 为什么两个出口仍互相矛盾：CLI/circuit 一侧是 `_epoch_ms`（墙钟，`test_v2_circuit.py:108` 专门钉过），界面一侧是单调钟 —— 同一条 30 分钟熔断，终端说「至 15:35」、界面说「至 10:40」，正是第七轮 PM/ix 独立命中的那一类"两个出口给两种说法"。
- 复现（不依赖我的机器状态）：
  1. `python -c "from model_gateway.core.resources import ResourceManager; import time; m=ResourceManager(); print(m.clock is time.monotonic, m.clock(), time.time())"` → `True` 且两数差 ~17.9 亿；
  2. 或跑 `/tmp/mgw-pm8/e2e2.py`（临时实例 8399）；
  3. 或直接看 `tests/integration/test_int_v2_circuit_boot.py:65`：把断言从"形状正则"改成"钟点等于 `time.localtime(time.time()+剩余)`"，该用例立刻红（我未改仓库任何测试，仅据此判定门为假绿）。
- 修复方向（供实现者定夺，均属既有口径内）：① 生产把 `ResourceManager(clock=time.time)`（`main.py:188`，同时确认 `cooldown_remaining_ms`/`reconcile_expired` 仍只看差值）；② 或在渲染处按"剩余秒数 + 墙钟"换算；③ 无论哪种，**必须补一条用生产默认构造（不注入时钟）的判据**，并允许把 boot 用例的形状正则升级为数值相等 —— 否则同一层假绿会再来一次。

---

## ④ 非阻塞建议

- **N1（产品缺口，需用户裁决）**：`Scheduler._tick()` 遇 plan 锁"建不起来"只做 `logger.error + errors+=1`（`runner.py:614-620`），而 `Scheduler.errors` 未被任何管理端点/界面读取（`grep -rn errors model_gateway/api/admin.py` 只命中 422 校验串）→ 该情形在用户侧只剩日志，**红点不亮**（因为根本没进 `run_once`、没有 report 可落盘）。这与 §21.3 原则 1「写进日志 ≠ 用户看到」相冲，也正是 Q28-⑦② 立项要消灭的"运营停摆而进程看着正常"。实现与 PRD 字面相符（PRD 只要求"计错误 + 留日志"），故**不阻塞**，但建议下轮把它升为一个可见出口（复用既有横幅/红点，不新建页面）。
- **N2（文档）**：PRD `:787` 指 `quota.until_label()`、tech-design `:1280` 指 `core/resources.fmt_recovery_clock`。两处都对，但"唯一口径"的名字只有一个才拦得住第三人。建议 PRD 那句补成「口径本体 = `resources.fmt_recovery_clock`，`quota.until_label()` 是它的 ms 适配」。
- **N3（记录与代码不一致）**：第七轮补做表/自述写的是 `.write-probe.lock`，代码实际探针文件名是 `.write-probe`（`runner.py:205`）。属证据文档笔误，按铁律 2 建议就地更正该行。
- **N4（卫生）**：探针 `unlink` 被 `contextlib.suppress(OSError)` 吞掉 → 权限抖动后锁目录可能长期残留 `.write-probe`（无人回收、无超龄逻辑）。建议下一轮 tick 顺带清或写进注释。
- **N5（注释误导）**：`reconcile_expired` 文档串写"（并清掉已失效的原因串）"（`resources.py:487`），而下级 `_lift_if_expired` 明确「**不**清 `last_error`」（`:504-508`，S-15 定稿）。前者是旧语义残留，建议改字，否则后来人会以为到期抹原因。
- **N6（到期时的 CLI 串）**：`circuit.reason()` 在 `active()==False` 时仍返回「…，至 00:20」（我实测 00:21 读到）。目前所有调用点都以 `active()` 为闸门（`cli_zcode.py:246/256`、`main.py:109`），故不外泄；但它是"给历史行挂过去时刻"的同族风险，建议 `reason()` 自身到期即只回裸原因，与列的口径对齐。

---

## ⑤ 明确未验证（不用"看起来没问题"代替证据）

1. **用户当前运行的 `:8300` 实例**：`curl http://127.0.0.1:8300/admin/api/overview` → `HTTP 000`（8 秒超时内无响应，端口未监听）。按要求未重启该实例，故 B-1 的**现场实拍**未取得；我的复现走的是同一段代码（`create_app` → `/admin/api/zcode/bench` → `/admin/api/overview`）+ 生产默认 `ResourceManager()`。真实部署里若已有冷却行，预期同样表现为假钟点 —— **未在用户进程上验证**。
2. **日志这一第三个出口**：只做了代码级核对（`main.py:113/116/120` 调 `circuit.reason()`），未从真实 `data/gateway.log` 抓取整行原文。
3. **真实 3012 风控 / 真实上游领取**：未发起（约束），因此熔断的**产生**路径靠注入，**呈现**路径靠 bench 端点。
4. **S-22 在 cron 腿的红点点亮端到端**：判定依据是 `main.py:161/166` 调 `write_report` + `runner.unread_failures` 只数 `failed` 的既有实现（我未起网关 UI、未用浏览器复现红点数字变化）。
5. **前端 DOM 层的「最近错误」渲染**：只验到后端 `last_error` 字符串与既有门（69/69、62/62）；未在浏览器里截图核对这一列的实际显示。
6. **`Manager.bench` 与 429 退避在真实负载下的钟点**：未压测（B-1 的时基结论与之同构，但真实 429 场景的现场值未采）。

---

### 自证：工作区与用户数据未被我改动

实测原文（2026-09-28 15:08 后跑）：

```
$ find data -newermt "2026-09-28 14:30" -type f
（空输出 —— 本轮实验期间仓库 data/ 零文件被新建或改写；:8300 实例本就未监听，故连 gateway.log 都没动）
$ git status --short | wc -l
      82          # 与开工时逐字相同（29 个 M + 53 个 ??，全部是实现者的既有改动）
$ lsof -nP -iTCP:8399 -sTCP:LISTEN
（空 —— 我的临时实例随脚本结束已退出）
```

我的实验全程 `MG_CONFIG=/tmp/mgw-pm8/data/config.yaml`、`MGW_ZCODE_ACCOUNTS=/tmp/mgw-pm8/data/no-accounts`（空账号根，零上游请求）；
被跟踪文件零改动，仅新增本报告 `docs/changes/reviews/pm-accept-8.md`（`docs/` 已 gitignore）。
