# PM 第十轮验收报告（2026-09-28）

验收人：产品经理面板（第十轮）。上一轮我判 **通过（0 阻塞）**，但第九轮之后实现者又动了代码
（第九轮 ix 的 7 条门逃逸 S-32 + eng 的 2 条登记 S-33，见账本「第九轮复验的补做」表），
本轮**独立复跑三门 + 复核产品面没有回退**。不改生产代码，全部实验落在 `/tmp/mgw-accept-10-pm/`。

## ① 结论：**通过（0 阻塞）**

- 三门数字全部来自本面板这一跑：**pytest 703 passed / 前端门实测 79·可红 87/87 / 后端出口 12/12**。
- 第九轮我通过的三件事**逐条复测仍成立**：S-28/S-31 两列同一瞬间、四故障 × 四出口仍可分辨且无空格、
  PRD Q28-⑦ 两条定稿与代码现状逐句相符（含"落盘只存裸原因""一份口径"）。
- 新增机制（`_load()` 坏值保持内存态）**没有把熔断变成永不解除**，README/CLI 承诺的手动出口
  （删除状态文件）**实测仍然真实** → 按本轮判据不构成阻塞。
- 但我打到 **2 条新的"坏值路径零痕迹"缺口**（③ 的 N-1/N-2，附复现）+ 3 条旧口径残留：
  产品承诺文本没有被打破，故列**非阻塞并登记**，建议第十一轮一并收口。

开工 `git status --porcelain` = **82 行**（30 M + 52 ??，v2.0 开发中的既有脏态，见本报告末"收工自证"）。

---

## ② 三门独立复跑（逐字，本面板自己跑的）

```
$ .venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest-pm10 -p no:warnings
703 passed in 129.15s (0:02:09)                      # 退出码 0；与账本第九轮 703 持平

$ .venv/bin/python scripts/ui_verify_v2_visible.py --mutation
[前端渲染逻辑]
[变异自证] 基线 79 条全绿 → 施加 87 个源码变异
可红 87/87；每条断言都有对应变异
后端出口实测 12 项，通过 12 项，失败 0 项             # 退出码 0
→ 三个数：实测 79（内嵌 node 基线）/ 可红 87/87 / 后端出口 12/12

$ node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json   # 上一跑自产 fixture
实测 79 项，通过 79 项，失败 0 项
```

熔断纪律自证：`find data -newermt "2026-09-28 16:30" -type f` → **空**（未污染用户数据目录）；
`:8300` 未启动未触碰；无真实上游请求（探测配置里只有 `https://example.invalid/v1` 且未发起调用）；
`~/.zcode` / `~/.workbuddy*` 未碰（探针显式注入 `MGW_ZCODE_ACCOUNTS=/tmp/...` 与 `/tmp` 下的锁目录）。

### `TestClient` 自造 `/admin/api/overview`：两列原文抄录

脚本 `/tmp/mgw-accept-10-pm/check_overview.py`（真 `create_app` + `TestClient`，res-a 挂两条映射：
60s 短退避 + 30min 熔断；生产默认钟 `monotonic` 未注入）：

```
[0] production manager clock = monotonic
[1] res-a entries: ['vendor-m1', 'vendor-m2']
[2] GET /admin/api/overview -> 200

=== VERBATIM res-a row (S-31/S-28 evidence) ===
cooldown_remaining_ms = 1799996
status                = cooldown
last_error            = '429 短退避，至 17:06'
===============================================

[3] independent wall-clock recomputation: 17:06 -> matches column+suffix: True
[4] 23:50 + 30min -> '至 明日 00:20'; 21:50 -> '至 21:50'
[5] expired res-b: status=active remaining=0 last_error='额度耗尽'
[6] circuit _with_until live: 'ZCode 风控熔断，至 17:06'
[7] expired circuit reason: 'ZCode 风控熔断' (no past clock)
[8] pre-rendered reason double-clock guard: 'ZCode 风控熔断，至 17:06'
ALL-OVERVIEW-ASSERTIONS-PASS
```

**判读**：「冷却剩余」= 1799996ms ≈ 1800s，「最近错误」= `429 短退避，至 17:06`，
独立墙钟复算 `now + 1799.996s` = **17:06** —— **两列指同一瞬间，用户不需要做任何时间算术**，
也不需要知道 60s 那条短退避的存在（它的钟点没出现在列里 = S-31 不回退）；
单调钟数值被当墙钟格式化出的假钟点未出现（S-28 不回退）；到期行 `last_error='额度耗尽'`
**不挂过去的钟点**（第八轮 L-1 不回退）。

---

## ③ 逐项核验表

| 项（第九轮我通过的三件事 + 本轮新增） | 我跑了什么 | 读到什么 | 判定 |
|---|---|---|---|
| **S-28/S-31 两列同一瞬间** | `check_overview.py`：真 `create_app` + `TestClient.get('/admin/api/overview')`，同一次响应里取两列 | 见上一节原文：`1799996ms` 与「至 17:06」同一瞬间，独立复算相符；60s 条目钟点未出现 | ✅ 未回退 |
| **是否需要用户做时间算术** | 同上 + 跨午夜/过期两态 | 当日 `至 17:06`、跨午夜 `至 明日 00:20`、过期后**只剩裸原因**（没有"几点恢复"这回事） | ✅ 三种态都不必换算 |
| **S-22 开局不可写** | `check_failures.py`：真 `run_once`（锁目录 chmod 500）+ 真 `cli_zcode._claim`（仅 patch `run_once` 回灌同一 report、`default_usage_dir` 指 /tmp、patch 掉 `_ack_failures` 以免打 :8300） | CLI：`✗ 失败 2 个（其中 2 个**未发起**：互斥锁不可用，本轮拒跑 → 查数据目录权限）`；逐条 `运营互斥锁目录不可写：… 本轮未对任何账号发起操作（宁可拒跑也不双领）`；`claims issued: []`；rc=**1**；`ops-results written: True`；`unread_failures: 4`（红点亮）；日志 `ERROR 运营互斥锁目录不可写（…/.write-probe.lock）` | ✅ 未回退 |
| **S-29 中途不可写** | 同上：acct-1 跑完后把锁目录改只读 | `claims issued: ['acct-1']`、`success: ['acct-1']`、`failed: 2`、`skipped: []`；逐条 `运营互斥锁目录在本轮中途不可写：… 本账号及其后共 2 个账号均未发起操作`；抬头 `✓ 已领取 1 个` + 同款「未发起」；日志 `ERROR … 目录不可用（…/acct-2.lock）→ 拒绝该账号本轮，不冒险双领` | ✅ 与 S-22 靠"开局/中途 + 有无 success"两向可分，没有合并成一格 |
| **S-24 收尾失写** | **本轮把探针姿势改对了**（上一版 `check_failures.py` 里探针自己 `pl.try_acquire()` 未放，`threading.Lock` 按设计不可重入 → 打出 `rounds=[] errors=1` 是**我的脚本自伤**，不是产品行为；已在 `check_s24_and_boot.py` 里让 tick 自己拿放锁） | `after round-1: ran=['round-1'] errors=0 logs=['WARNING 运营锁释放失败（…/__plan__.lock：Permission denied）→ 交给超龄回收，不向上抛']`；权限恢复后 `ran=['round-1','round-2','round-3'] errors=0 logs=[]` | ✅ 未回退：失写只留一条 WARNING，定时器活着，下一轮自愈 |
| **S-26④ 结果落不了盘** | 同上：usage 目录只读 + 真 `_claim` | `ops-results on disk? False`、`unread_failures: 0`（红点**不亮**）、rc=**1**、stderr `⚠ 本轮结果未能写入 …（数据目录不可写？）→ 顶栏红点不会记录这些失败，逐条原因只存在于本终端的输出与网关日志里`；日志 `ERROR 运营结果落盘失败 … 顶栏红点不会点亮这些失败；请检查数据目录权限` | ✅ 抬头是**普通失败**（无「未发起」字样）→ 与 S-22/S-29 可分；且**主动说出**红点不会记 |
| **四格互不混淆 / 无零痕迹格** | 上面四格横向比对（CLI 抬头 / 退出码 / 红点 / 落盘四出口） | 见 ④ 表：四格在「未发起措辞」「success 有无」「红点亮否」「文件在否」四个维度上两两不同；退出码三类都是 1 属**设计内**（3 专留熔断，Q28-⑥⑧） | ✅ 本轮改动没有把任何一格改回"互相混淆"或"零痕迹" |
| **Q28-⑦①「落盘只存裸原因」** | `check_circuit_badvalues.py` 第 4 段：拿**已被别处渲染过**的串（含 `，至 99:99`）去 `enter()` | 落盘原文 `{"until_ms": 1790586359231.3228, "reason": "ZCode 风控熔断（30min，全局）", "last_call_ms": …}` —— **无时刻串**；读出口 `ZCode 风控熔断（30min，全局），至 17:05`；过点 31 分钟后 `active=False reason='ZCode 风控熔断（30min，全局）'`（文件仍在盘上） | ✅ 与定稿逐句相符 |
| **Q28-⑦①「一份口径」** | `grep -rn "fmt_recovery_clock\|明日" model_gateway/` | 口径本体只有 `core/resources.py:161` 一处；`quota.until_label`(:365) 转调它、`_rendered_last_error`(:217) 转调它；前端不自己算（K6 判的是后端下发文本） | ✅ CLI ⚠ 块 / `last_error` / 日志同尺，没有第二把尺 |
| **Q28-⑦② fail closed（无 /tmp 退路）** | `grep -rn "fallback_lock_dir\|/tmp 退路"` + 四故障实测 | 代码/文档仅剩"为什么撤掉 /tmp 退路"的说明（runner.py:105）与 PRD 裁决句；实测拒跑、记 `failed`、plan 锁区分「正被持有(静默)」与「建不起来(ERROR+errors+=1)」 | ✅ 相符 |
| **新增机制 `_load()` 坏值保持内存态** | `check_circuit_badvalues.py` 第 1/2 段（8 种坏形状 × 常驻/新进程两态） | 见 ④ 熔断矩阵：**常驻进程熔着时被改坏 → active 仍 True、30 分钟后自愈**；**删除文件 → active=False**（出口真实）；**新进程读到坏文件 → 静默不熔（0 条日志）** | ✅ 出口承诺未破；⚠️ 新进程那一侧是零痕迹 → N-1/N-2 |
| **§20 不做清单** | 读 6 个新落点（见 ⑤ 表）+ `grep -c "@router.get" api/admin.py` | 无新页面/新端点/新轮询/第二本账；三项门机制住在 `scripts/` 不进产品 | ✅ 未越界 |
| **README / --help / design-spec / frontend-spec 旧口径** | `grep 熔断/退出码/circuit/至 HH:MM/mtime/最近错误/冷却剩余` × 四文件 + 真跑 `mgw --help`、`mgw zcode claim --help` | README.md:113-117 与 zh:110-113 的 0/1/2/3 语义 + 「3 与 setup 的 3 同码不同义」与 epilog **逐字一致**；四文件里 `至 HH:MM`/`/tmp 退路`/`fallback_lock_dir` **零命中**；design-spec:192 只列了列名（见 N-5） | ✅ 文档面没有因这几轮改动留下旧口径（2 处**代码内**注释残留见 N-3/N-4） |

### 熔断状态文件被改坏 × 进程形态矩阵（本轮实测，判 ③ 项 3）

| 坏法 | 常驻进程（内存里正熔）改坏后 | 全新进程读到同一文件 |
|---|---|---|
| `until_ms` 改成字符串 | `active=True left=1800s`（保持内存态） | `active=False`，**0 条日志** |
| `until_ms = 现在+30天` | `active=True left=1800s` + `WARNING 时间戳不合理…保持现有内存态，不清零熔断` | `active=False`（同一 WARNING） |
| 顶层不是对象 `[1,2,3]` | `active=True left=1800s` | `active=False`，**0 条日志** |
| 半写/截断 JSON `{"until_ms": 123` | `active=True left=1800s` | `active=False`，**0 条日志** |
| `chmod 000` 读不动 | `active=True left=1800s` | `active=False`，**0 条日志** |
| **丢掉 `until_ms` 键 / `= null`** | **`active=False left=0s`（熔断被抹掉）**，**0 条日志** | `active=False`，**0 条日志** |
| 删除文件（承诺的手动出口） | `active=False reason=''` | —— |
| 正常文件（对照组） | `active=True` 且 `至 17:08` | `active=True left=1800s` |
| `until_ms = 现在+23h / +6h / +1h`（24h 上限之内） | —— | `active=True left=82800s / 21600s / 3600s`，界面分别说「至 明日 15:35 / 至 22:35 / 至 17:35」 |

**产品判读（本轮判据）**：
1. **不会"永不解除"** —— 内存态只可能来自 `enter()`（现在 + 30 分钟）或一次通过 24h 校验的读盘，
   到期即 `active=False`（实测第 5 段：过点 31 分钟后 active=False、且 reason 不挂过去的钟点）。
2. **用户的手动出口仍然成立** —— 8 种坏法（含 23h/1h 的手改值）下删除文件都立刻 `active=False`；
   CLI 那句「删除该文件可立即放开后续领取，已冷却的资源按其剩余时间自行回池」（`cli_zcode.py:252-254`）
   与实测一致，README/PRD 没有更宽的承诺。**故不阻塞。**
3. 但**新进程那一列是零痕迹**：见 ④ N-1/N-2（真实缺料，不是实现洁癖）。

---

## ④ 阻塞项

**0**。

### 非阻塞（含本轮新发现，逐条附复现）

**N-1（新·本轮实测）新进程读到"不可信"的 `circuit.json` = 静默丢掉 30 分钟风控观察期，0 条日志。**
复现：`/tmp/mgw-accept-10-pm/check_s24_and_boot.py` 第 (b) 段 —— 文件写成截断 JSON / `[1,2]` /
字符串 `until_ms` / `chmod 000`，`CooldownManager(path=F)` → `active=False left=0s reason=''`
且**期间日志 0 条**（只有 >24h 那一型会 WARNING）。
产品面后果：网关重启或 CLI 新起进程时，若状态文件被编辑器/备份/同步盘改坏，用户在界面上看到
"没有熔断"并**立刻恢复打上游**，而没有任何地方说明"那份跨进程凭据读不出来"——这正是账本里
"最难查的那类故障"的定义，也与第九轮 S-33 N-2 自己写的「保持内存态**并告警**」不符（告警只覆盖一型）。
判非阻塞的理由：`_save()` 走 `os.replace` 原子写且三键齐，生产自身不产生坏文件；PRD/README 没有
承诺过损坏处理语义；出口文案仍然真。**建议第十一轮**：该分支补一条 `logger.warning`（点名文件路径 +
"熔断凭据读不出来，本轮按无熔断执行"），更彻底是给 overview 一条横幅；不改判定方向也可以。

**N-2（新·本轮实测）`_ms_or_zero` 把"键不存在 / null"折成 `0.0`，会**抹掉一个正在生效的内存熔断**。**
复现：同一脚本第 1 段 C/D 行 —— 常驻进程 `active=True/1800s`，把文件里的 `until_ms` 删掉（或置 null）
后再判定 → `active=False left=0s`，0 条日志。
根因是 `float(raw_value or 0)`：`None or 0 → 0.0` 属"合法无熔断"，与 `return None`（文件不可信）
两条语义在缺键这一型上被压平。同方向 S-33 N-2 只堵住了"非数字"和"超 24h"两型。
产品面后果与 N-1 同类（风控观察期内提前放行），但更窄（要外部写手）。
**建议**：`raw.get(...)` 用哨兵区分"键不存在"与"值为 0"，缺键按"文件不可信"处理并告警。

**N-3（旧口径·代码内注释与行为相反）** `quota.py:422` 类表格仍写
「每次判定前**按 mtime 回读文件**」、`:507` 行内注释同样，而 `:442` 起的行为与判据是
**每次真读、明确不用 mtime 去重**（S-26⑤）。后来人极可能照表把 mtime 缓存加回去 = 跨进程凭据又变钝。
建议改为「每次判定真读一遍（无 mtime 去重）」。

**N-4（第九轮我提过、未动）** `ops/builtin/zcode_claim.py:114` 仍写
「`enter()` 会把它规范成 §17 要求的 `…，至 HH:MM`」——现实现是 `enter()` **剥尾存裸原因**、
读时才拼（实测见 ③ 表"落盘原文"）。行为正确，注释误导。

**N-5（规格面缺口）** 两列契约只在**门**里（`K6`/`C16`）与账本里，UI 真相源没记：
`docs/specs/design-spec.md:192` 只列了列名（…/ 冷却剩余 / 最近错误），
`docs/specs/frontend-spec.md` 对「至 HH:MM / 明日 / 读时渲染」**零命中**。
建议 design-spec 补一行：`冷却剩余`=同一瞬间的秒数、`最近错误`=裸原因 + 读时钟点、
非 `cooldown` 不配钟点、两列不得指两个瞬间。否则下一轮改前端的人只能从门里反推契约。

**N-6（文案洁癖）** `mgw zcode claim --help` 把 markdown 的 `**全局风控熔断中…**` 原样打进终端
（实测输出里确实带星号）。终端不是 markdown 渲染器，建议 epilog 去粗体（README 保留）。

**N-7（信息项·24h 上限的宽度）** 手改文件在 24h 之内可以把熔断"钉"到 23h59m（实测 +23h → 82800s）。
§17 定义的熔断只有 30 分钟，`enter()` 写的值不可能超过 `现在+30min`，
所以把文件来源的上限收紧到 `COOLDOWN_MS + 余量` 既不误伤也能压缩这个面。
界面在这个场景下**说的还是真话**（老实显示剩余与钟点），删除文件也仍然能出口 → 纯加固建议。

**N-8（既有登记未修，维持原判）** 热重载换下的适配器不 `aclose`（任务 #48），仍待用户定夺，不属本轮范围。

---

## ⑤ §20 不做清单再对一次表（含本轮新增的 6 个落点）

| 新增物 | 位置 | 是不是新页面/新端点/新轮询/第二本账/新录入界面 | 判据 |
|---|---|---|---|
| 门的"第二轮渲染"（真载荷 + 哨兵载荷各渲一次） | `scripts/verify_v2_frontend.mjs` | 否：测试脚本，不进产品运行时 | 本轮实测 K9 能红（变异"弱化 api.js 的 esc" 打红 K9，连带 K0-K8） |
| 哨兵载荷（掺 `<script>`/引号） | 同上（只在 /tmp fixture 里） | 否：不落用户数据目录、不下发 | 门跑完 `find data -newermt …` 空 |
| `copySources` 目录自动发现 | 同上 | 否：门运行时只读扫 `model_gateway/**` + `js/**` | J2 实测 67 文件入面；无新端点/无新 UI |
| `SANITY_HORIZON_MS` | `upstream/zcode/quota.py:318`（唯一使用点 :360） | 否：既有读盘处的一个阈值，不新增状态、不改判定方向 | 实测 B 行 + WARNING；未加字段/未加界面 |
| `LOCK_REFUSAL_PREFIX` | `ops/runner.py:65`，使用点 :431/:448 与 `cli_zcode.py:290` | 否：文案判别锚（把"未发起"与"已发起"分开） | 实测 S-22/S-29 两格抬头分级依赖它，不是新指标 |
| `.write-probe` 试写 | `ops/runner.py:209`（`usable()` 内） | 否：既有一次性探测点里的一次写+删，无新定时器 | 实测四故障日志点名 `.write-probe.lock`；`@router.get` 仍 9 个，无新端点 |

另核：`#20 不按模型拆调度参数`、`#15 不做 L-B/L-C 录入界面`、`#12 首期不做账号管理页`、
`#13 不做能力位版本协商` 本轮均未被"顺手实现"（无新页面文件、无新表单、无新配置层）。
残留小观察：`.write-probe` 的 unlink 被 `suppress` 包住，极端情况下锁目录里会留一个陈旧
`.write-probe` 文件（下次试写会覆盖，无害，不必为此加清理逻辑）。

---

## ⑥ 未验证清单（如实，不用"看起来没问题"代替）

1. **:8300 真实实例的顶栏红点浏览器级呈现** —— 本轮约束禁碰 8300；红点语义经 `unread_failures`
   对 /tmp usage 目录直读实测（S-22/S-29 亮=4、S-26④ 不亮=0 两态），toast/徽章 DOM 依赖三道门输出，
   未亲见真实浏览器。
2. **`_ack_failures` 对运行中网关的 admin POST 副作用** —— 为不污染真实用户红点，探针 patch 掉了
   CLI 的 ack 调用；水位读写语义由 703 条 pytest 覆盖，非 live 端到端。
3. **CLI→网关 `/admin/api/zcode/bench` 的真·跨进程内存回写往返**（两个活进程）——
   本轮只有同进程 TestClient 渲染 + 文件跨进程读实测。
4. **自然午夜时刻的生产路径** —— 用 `fmt_recovery_clock` 的 23:50/00:05 数学与读时重算路径核实，
   未挂机到真午夜。
5. **N-1/N-2 那两种坏文件在真实用户机器上由谁产生**（编辑器保存、Time Machine/Dropbox 同步、
   杀毒软件、磁盘错误）—— 无遥测，本轮只证明"若发生则零痕迹"，未证明发生频率。
6. **Windows 侧的"文件读不动"等价场景**（ACL 拒绝、OneDrive 占位文件）—— 本机只测了 POSIX chmod。
7. **崩溃在 `_save()` 中途造成半写文件** —— 代码走 `os.replace` 原子换（读码事实），
   未做 kill -9 竞态实测；若真发生，其表现即 N-1 的"截断 JSON"那一行。
8. **多进程并发争用 `.write-probe` 与超龄回收** —— 本轮全部单进程实测，跨进程互斥仅由 pytest 覆盖。
9. **T5a/T5b（WAF 放行、curl_cffi async SSE）与真实领取端到端** —— §19 手工项，本轮不验。

---

## 收工自证

```
$ ls -la docs/changes/reviews/pm-accept-10.md        # 见本报告文件
$ git status --porcelain | wc -l  → 82（与开工同一集合，除本报告外仓库零改动）
$ find data -newermt "2026-09-28 16:30" -type f     → 空
```
