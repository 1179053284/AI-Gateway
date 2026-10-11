# PM 验收 · 第七轮（2026-09-28）

## ① 结论

**有条件通过** —— 1 项阻塞（S-21 的 `last_error` 出口未随读时渲染落地，午夜后与 CLI 互相矛盾且会长期挂着错话），
S-22 / S-19 / §20 对表均通过；下列"未验证"项须在下一轮补齐。

---

## ② 逐项验收表

| 项 | 我实际跑了什么 / 读了哪里 | 观察到什么 | 判定 |
|---|---|---|---|
| **S-22 判据本身（fail closed）** | `.venv/bin/python -u /tmp/mgw-pm7/verify.py`：`MGW_OPS_LOCK_DIR=/tmp/mgw-pm7/locked/ops-locks`（父目录 `chmod 0500`），假 `claim` 注入，真调 `runner.run_once(accounts=["acct-1","acct-2"])` | `上游发起次数 = 0`；`failed 条数 = 2`（**不是 skipped**）；`skipped=[]`；原因串「运营互斥锁目录不可写：… —— 跨进程互斥建立不起来，本轮未对任何账号发起操作（宁可拒跑也不双领）。请检查数据目录权限或是否被只读挂载」 | **通过**（零发起 + 逐个记 failed，与 Q28-⑦② 一致） |
| **S-22 另一半（目录创建不出来）** | 同脚本：`MGW_OPS_LOCK_DIR=/tmp/mgw-pm7/afile/sub/ops-locks`（父路径是普通文件） | `usable() -> False`，日志 `[Errno 20] Not a directory`；`_acquire_file()` 亦只返回 False（`runner.py:193` 的 `except OSError`） | **通过** |
| **S-22 `/tmp` 退路确已取消** | `hasattr(runner,"fallback_lock_dir")` → `False`；`"mgw-ops-locks" in runner.py` 文本 → `False`；`runner.py:84` 唯一目录 = `paths.data_dir()/ops-locks` | 无退路残留 | **通过**（裁决回归钉在实现里成立） |
| **S-22 plan 锁两种成因分开呈现** | `Scheduler._tick()` 实跑两次：① `PlanLock(不可写目录)`；② `PlanLock(可写)` 且自己先 `try_acquire()` 占住 | ① `run 被调用 = 0, errors = 1` + ERROR 日志「定时器每轮都会跳过，运营已停摆；请检查数据目录权限」；② `run 被调用 = 0, errors = 0`（**静默跳过、不计错**） | **通过**（正是 Q28-⑦② 要的可分辨性） |
| **S-22 → 落盘条目可分辨**（§21 出口②） | `runner.write_report(rep, usage_dir=/tmp/mgw-pm7/usage)` 后 `cat` 该行 | `ops-results-20260928.jsonl` 里 `failed:[{account,reason:…不可写…},{…}]`，与熔断轮的 `inactive + inactive_reasons`（S-17）在结构上不同层、不同键 → **事后翻文件能判断"这一轮一个账号都没发起"** | **通过** |
| **S-22 → 红点自洽** | `runner.unread_failures(/tmp/…/usage)` → `2`；`ack_reports()` → 返回 2、随后 `unread_failures` → `0`；消费方 `api/admin.py:129-131`（`/admin/api/status` 直取 `unread_failures`，无第二本账） | 拒跑轮确实点亮顶栏红点，且"看完才清零"成立 | **通过** |
| **S-22 → CLI 文案 / 退出码** | 同一脚本内把 `run_once` 注入为拒跑结果、`write_report` 指向 tmp、`local_admin.admin_post` 打桩（**未碰 :8300**，实测 `admin_post 调用 = ['/admin/api/ops/ack']` 为桩记录），跑 `cli_zcode._claim(Namespace(account=None, manual=False))` | stdout：`✗ 失败 2 个：` + 两行 `acct-N  运营互斥锁目录不可写…` + `逐条明细已落盘：<路径>`；**退出码 = 1**（非 0/2/3）；`--help` epilog `cli.py:62-65` 载明 0/1/2/3 且警告「3 与 `mgw setup` 的 3 同码不同义」；README.md:113-117 / README.zh-CN.md:110-113 同步 | **通过**（用户看得见：文案可行动、码读得对、文件指得到） |
| **S-21 熔断文案读时渲染（circuit 侧）** | 冻结时钟实跑 `CooldownManager(circuit.json, now=…)`：23:50 `enter()` → 23:59/00:05 各读一次 `reason()` | `23:50 → …，至 明日 00:20`；`23:59 → …，至 明日 00:20`；`00:05 → …，至 00:20`；**同一份文件**两次读各说得对；`circuit.json` 原文 = `{"until_ms":1790612400000.0,"reason":"ZCode 风控熔断（30min，全局）","last_call_ms":…}` —— 不含时刻、不含「明日」 | **通过**（`quota.py:335 until_label()` / `:349 _with_until()` / `:439 enter()` 只存裸原因 / `:459 reason()` 读时拼） |
| **S-21 跨进程：CLI 写文件、网关显示 `last_error`** | `zq.apply_to_resource(rt, ["res-A"], reason=c2.reason())`（23:50 冻结）→ 把时钟推到 00:05 → 比对 `ResourceState.last_error` 与 `c2.reason()` | **23:50 写入的 last_error = `…，至 明日 00:20`；00:05 网关列仍是 `…，至 明日 00:20`；00:05 CLI 同一事实说的是 `…，至 00:20`；"两个出口是否矛盾：True"** | **不通过**（见 ③ 阻塞 B-1） |
| **S-21 背离是否在文档里交代清楚** | `grep -n "有意背离\|推翻 §17\|Q28-⑦" docs/specs/tech-design.md` → **0 命中**；`tech-design.md:1271` 仍是原字面「`last_error` 值为 **`ZCode 风控熔断（30min，至 HH:MM）`**」，上下文无 ⚠️ 注记；PRD 侧已交代（`prd.md:787` Q28-⑦① + `:796` v1.17「推翻 §17 把时刻『写入时烘死』的字面」）；代码侧已交代（`quota.py:442-447` docstring 明写"时刻**不在这里烘进字符串**"） | 技术方案**本侧一字未改**：后来人照 §17 表格施工（尤其照 `（30min，至 HH:MM）` 这个"值"字面去落盘）就会把时刻改回写入时烘死 | **有条件**：PRD 优先的口径本身站得住，但 §17 需补一行背离注记（见 ④ NB-2） |
| **S-19 徽章文案（`disabled` 两成因）** | 读 `web/static/js/pages/dashboard.js:117-139`（`statusBadge`）+ `:103`（冷却列 `fmtCooldown` 唯一口径）+ `:104`（最近错误列） | `disabled` title = 「两种成因之一：资源开关已关闭（打开即恢复），**或凭据被上游拒绝 401（需到「模型资源」页更换 Key，不会自愈）—— 见「最近错误」列**」；`invalid` title = 「上游回 404…到「资源池设置」页更换映射（不会自愈）」；未知态中性样式。**处置齐全、方向对**（401≠404 的处置差异被写明，推翻 S-19a 前的"打开开关即恢复"单因文案） | **通过（带条件）**：文案本身成立，但指路的「最近错误」列在 401 情形下**实测为空**（见下） |
| **S-19 页名与真实页面一致** | `core/resources.py:164-166`（`ROUTE_POOL_PAGE=「资源池设置」页` / `RESOURCE_PAGE=「模型资源」页` / `OVERVIEW_HEALTH_PAGE=「总览」页的资源健康表`）↔ `web/static/index.html:31/38/42` 导航 `<span>` 实文（总览 / 模型资源 / 资源池设置） | 两个页名与侧栏逐字一致；`「最近错误」` 列确在总览表（`dashboard.js:96,104`）；后端第 4 份副本已收进常量（`main.py:330` 用常量，S-19c） | **通过** |
| **S-19 实测：401 判死的资源，「最近错误」列有没有内容** | `build_runtime` + `FakeAdapter.set("sk-A", http_err(401,"invalid_api_key"))` → `rt.scheduler.execute_chat(...)` → 读 `ResourceState` 与 `rt.resources.snapshot_by_resource()` | `res-A status = disabled | last_error = None | C = 0`；下发给前端的行 = `{'rid':'res-A', 'status':'disabled', 'last_error': None}` → 页面渲染 `—` | **不通过（指路落空）**：徽章让用户"见「最近错误」列"分辨两成因，而 `scheduler.py:400-405`（AUTH）与 `:406-411`（NOT_FOUND）**只 `disable()/invalidate()`，不调 `note_failure`** → 唯一区分成因的那一列恰好没字（详见 ④ NB-3） |
| **§20 不做清单对表** | 读 `runner.py:198-214 usable()`、`:205 .write-probe`、`core/resources.py:21-53 normalize_base_url` 与其全部调用点（`main.py:47/236/241`、`openai_out.py:22/53`、`anthropic_out.py:30/452`）；`grep ops-locks`；`ls -la data/ops-locks`（只读）；对照 `tech-design.md:1403-1427`（§20）、`:1451-1463`（§21.2） | ① **零新增页面/端点/轮询**：`usable()` 只在 `run_once` 开跑前一次 + `_tick` 拿不到锁时一次，不进任何新定时器；② **无第二本账**：红点仍只认 `ops-results-*.jsonl` + 水位（`admin.py:129`），`usable()` 不记账；③ `normalize_base_url` 是**合并**而非新增副本（全包唯一定义，三处调用共用，S-19e 收敛）；④ `.write-probe.lock` 是锁目录内的临时探针，写成功即 `unlink`（`:212-213`），不产生用户可见对象 | **通过**（未引入 §20 明令不做的东西） |
| **机械门复跑** | `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest-pm -p no:warnings` | **683 passed in 156.07s**（与账本 `:227` 声明的 683 一致） | **通过** |
| **只读纪律** | 探针全程 `MG_CONFIG=/tmp/mgw-pm7/data/config.yaml`（脚本内断言 `paths.data_dir()` 含 `mgw-pm7`）；跑前/跑后 `find data -type f | sort` 两份快照 diff | `OK: data/ 文件集合未变`；`ls data/usage | grep -c ops` → **0**；未访问真实上游；`admin_post` 全程打桩（**未对 :8300 发过请求**）；未读写 `~/.zcode`/`~/.workbuddy*` | **通过** |

---

## ③ 阻塞项（1 条）

### B-1 · 熔断恢复时刻：`circuit.json` 改成了读时渲染，但「最近错误」里的同一句话仍是写入时烘死的

**为什么是阻塞**：PRD `prd.md:787`（Q28-⑦①）点名三个出口必须同一份口径 ——
「CLI 的 ⚠ 块、**`last_error`**、日志同用 `quota.until_label()` 一份口径」，并给出判据
「**同一条落盘状态在午夜前后必须各自说得对**」。CLI ⚠ 块与日志走 `circuit.reason()` 已成立；
`last_error` 走的是 `reason()` 的**返回值**（一句渲染完的字符串），随后长期住在 `ResourceState.last_error`，
读时不再重渲染 —— 于是"必须各自说得对"在用户最常看的那一格上不成立，且因为 S-15 定案
「到期不清 `last_error`（语义=历史）」，这句错话会**一直挂着**，不是 30 分钟后自愈。

**写入点**（三处，全是"渲染一次就存字符串"）：
- `upstream/zcode/quota.py:522`（`state.last_error = reason`，`reason` 来自 `:571 circuit.reason()`，仅 `main.py:484` 启动时 `sync_circuit` 跑一次）
- `ops/builtin/zcode_claim.py:122-124`（同进程命中 3012 时烘一次）
- `ops/builtin/zcode_claim.py:128-129` → `POST /admin/api/zcode/bench`，**payload 里就带着 CLI 进程渲染好的字符串**，跨进程传进网关内存后同样是死串

**复现步骤**（不碰仓库 `data/`、不碰 :8300、不打上游）：

```bash
# /tmp/mgw-pm7/verify.py 已含此段；核心 12 行：
MG_CONFIG=/tmp/mgw-pm7/data/config.yaml .venv/bin/python - <<'PY'
import datetime as dt, sys, pathlib
sys.path.insert(0, "/Users/w/Desktop/Model-Gateway")
from model_gateway.upstream.zcode import quota as zq
from tests.unit.conftest import FakeAdapter, build_runtime, chat_model, make_config
T = {"ms": dt.datetime(2026, 9, 28, 23, 50).timestamp() * 1000}
c = zq.CooldownManager(pathlib.Path("/tmp/mgw-pm7/c2.json"), now=lambda: T["ms"])
c.enter("ZCode 风控熔断（30min，全局）")
rt = build_runtime(make_config(models=[chat_model("test-model", "AB")]), FakeAdapter())
st = {s.resource_id: s for s in rt.resources.registry.values()}
zq.apply_to_resource(rt, ["res-A"], reason=c.reason())      # 23:50 烘进 last_error
T["ms"] = dt.datetime(2026, 9, 29, 0, 5).timestamp() * 1000 # 推到午夜后
print("网关列 :", st[("res-A", "vm-A")].last_error)          # …，至 明日 00:20   ← 错
print("CLI 说的是:", c.reason())                             # …，至 00:20       ← 对
PY
```

实测输出：`两个出口是否矛盾：True`。

**用户读到什么**：00:05 打开总览，「最近错误」写「…至 **明日** 00:20」→ 以为还要等约 24 小时；
而同一时刻 `mgw zcode claim` 说「至 00:20」（15 分钟后）。两处必有一处在骗人，而骗人的是那处不用敲命令就能看到的地方。

**建议修法（择一，勿两处各写一份）**：
① `last_error` 只存**裸原因**（与 `circuit.json` 同纪律），由 `snapshot_by_resource()`（`core/resources.py:491`）
在**读时**用 `until_label(entry.cooldown_until)` 拼 —— 与 S-19b 给「冷却剩余」列定的"同一份 ms 走同一个函数"是同一条纪律；
② 或前端按已有的 `cooldown_remaining_ms` 自行渲染时刻。
无论哪种，判据都要加一条**跨午夜读总览**的断言（现有三条 S-21 判据只覆盖了 `circuit.reason()`，
`tests/unit/test_v2_circuit.py` 里没有 `last_error` 的午夜后复算 —— 这也是它这次没被门抓住的原因）。

---

## ④ 非阻塞建议

| # | 建议 | 证据 / 落点 |
|---|---|---|
| NB-1 | **整轮拒跑时，落盘失败要说话**。S-22 的触发前提就是"数据目录写不进去"，而 `write_report()` 在 `OSError` 时 `return None`（`runner.py:462-463`），CLI 只在 `results_path is not None` 时打印落盘行（`cli_zcode.py:284-285/294-295`）→ 真实场景（整个 `data/` 只读）下红点不会亮、`ops-results` 里也不会有这一轮，用户只剩 CLI 那一屏。`run_once:409-412` 注释里"只有 failed 才会落盘、点亮红点、让退出码非 0"三件里有两件在此场景失灵。建议补一行「⚠ 本轮结果未能落盘（<path> 不可写）—— 顶栏红点不会提示」。（我实测的是"`data/usage` 可写、仅 `ops-locks` 不可写"这一半，功能正常；全只读这一半是代码推断，**未实测**） |
| NB-2 | **§17 补一行背离注记**。`tech-design.md:1271` 至今是被推翻的旧字面，且 §17 全段无 Q28-⑦/读时渲染字样（grep 0 命中）。项目先例是可接受的：`main.py:111`、`quota.py:442-447` 都写明了推翻理由；但技术方案作为施工文件应当同处标注（§12.3 的 Q28-⑤ 背离也是靠 PRD 侧标注才没被改回去）。另：§17 字面把时刻放在括号内 `（30min，至 HH:MM）`，实现是括号外 `（30min，全局），至 明日 00:20` —— 建议一并写清取哪个串，避免下轮"照字面对齐"。 |
| NB-3 | **401/404 判死时补写 `last_error`**（`scheduler.py:400-411` 未走 `note_failure`），否则 S-19 徽章"见「最近错误」列"的指路落空、两成因在界面上仍不可分辨（实测 `last_error=None`）。这不是 S-19 文案写错，是文案依赖的后端事实没长出来。修法同 S-19 精神：`error_summary(e)` 现成，只差 AUTH/NOT_FOUND 分支各写一次；并补一条判据"被 401 停用 ⇒ 快照行 `last_error` 含 401 关键字"。 |
| NB-4 | **`data/ops-locks/` 无保留策略**。S-15b 只把 `ops-results` 纳入清理（`stats/events.py:96`）；`.write-probe.lock` 正常路径即时 `unlink`（`runner.py:212-213`），但进程被 kill 时会在用户数据目录留下死文件，账号 `*.lock` 陈旧件也只在同名再抢时才回收。当前用户机器 `data/ops-locks` 尚不存在（`ls` → No such file，运营 cron 未起），无实际堆积；建议与二期一并考虑。 |
| NB-5 | **账本 N-1（换下的出站适配器不 `aclose`）继续挂着**：本轮未验证其影响面（需长跑 + 观察 fd），维持"等用户定夺"的登记状态，不建议顺手打补丁。 |

---

## ⑤ 未验证（铁律 2，不以"看起来没问题"代替证据）

1. **网关 cron 腿的端到端**：我只直调 `run_once` → `write_report` → `unread_failures`（即该腿实际使用的同一组函数），**没有**在真实网关进程里等一个 tick 触发拒跑；`main.py:159` 之后的 `_maybe_start_ops` 包装未实跑（用户实例在 :8300，按约束不得重启）。
2. **前端门未复跑**：`node scripts/verify_v2_frontend.mjs --mutation`（账本称 56/56、67 项实测 0 失败）**本轮我没有重新执行**；S-19 徽章/C12-C14 的判定来自我直接读 `dashboard.js:103-139` 源码 + 后端快照实跑数据，不等于门本身为绿。
3. **浏览器里徽章的实际呈现**：`disabled` 的处置说明只存在于 `title`（hover 才可见），未做真人 hover 可发现性验证；「已停用」大字对不悬停的用户仍不区分两成因 —— 该项以"文案存在"为通过依据，交互层面**未验证**。
4. **`mgw zcode claim` 的真实进程退出码**：`_claim()` 函数返回 1 已实测（注入假件 + 打桩 `admin_post`）；**未**用真 CLI 进程跑（其默认账号集会读 `~/.zcode`，属禁区）。`--help` epilog 文案为源码核对，未跑 `--help` 子进程。
5. **`/admin/api/zcode/bench` 端点侧的字符串落地**：只由代码路径推断（payload 带 CLI 渲染好的串），未起临时实例复采。
6. `data/` 内容我只做了**文件集合**前后 diff 与 `data/usage` 计数核对，未逐字节比对用户配置（写操作为零，`find -newermt` 未复跑）。

---

### 附：本轮复跑可复现物
- 探针脚本 `/tmp/mgw-pm7/verify.py`、完整输出 `/tmp/mgw-pm7/out.txt`（含 `data-before/after.txt` 两份快照）
- 门命令：`.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest-pm -p no:warnings` → 683 passed
- 只读核对：`find data -type f | sort` 前后一致；`ls data/usage | grep -c ops` → 0
