# 第八轮 · 后端攻击性复验（eng-accept-8a）

复验人：资深后端工程师（第八轮）｜日期：2026-09-28 15:00–15:20
范围：第七轮修复（S-23 / S-24 / S-25 / S-26①②⑤ / S-27）的**残留逃逸**
账本依据：`docs/changes/e2e-records/E2E-20260928-round5-fixes.md`（第六轮 S-19~S-22、第七轮 S-23~S-27）

---

## ① 结论

**不通过（1 项阻塞）**。

- S-23 的**字符串一致性**确实修好了：两个出口（`circuit.reason()` / 快照 `last_error`）在四个读时刻上给出同一句话，旧格式/坏值文件不崩、不拼两个钟点，跨进程同口径 —— 全部实测通过（§二 A1/A2/A3、§四）。
- 但同一处修复**引入了一个新的、生产路径 100% 命中的错值**：`_rendered_last_error` 把跑在 `time.monotonic` 上的 `cooldown_until` 当成墙上时钟去 `time.localtime()` 格式化，界面「最近错误」列印出的是 **1970 年式的假钟点**（本机实测：真实 15:14 恢复，列里写「至 10:20」）。这正是 S-23 要消灭的那类"钟点说谎"，只是换了一种谎法，而且比修复前更糟（修复前至少是写入时算对的墙上时刻）。→ **BLK-1**。
- 另登记 3 项非阻塞（E-1 归一化口径第六处分裂 / E-2 行内两列不同瞬间 / E-3 代码卫生），以及 1 项按量化结论**判定不需要改**（S-26⑤）。
- 机械门复算：`.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest-8a -p no:warnings` → **693 passed in 124.95s**（与账本宣称一致）。**注意：BLK-1 在这个 693 全绿里完全不可见**，原因见 §三。

---

## ② 逐项：我跑了什么 → 看到什么

临时脚本全部在 `/tmp/mgw-accept-8a/`（`a1_s23.py` / `a2_xproc.py` / `a3_url.py` / `a4_perf.py` / `a5_perf2.py` / `a6_scheme.py` / `a7_http.py` / `a8_clockdomain.py`），全部设 `MG_CONFIG` 与 `MGW_ZCODE_ACCOUNTS` 指向 /tmp，零真实上游、零 `data/` 写入。

### A1 S-23 读时渲染：冻结时钟 · 四个读时刻 · 两个出口（`a1_s23.py`）

跑法：`CooldownManager(path, now=冻结)` 于 **23:50** `enter("ZCode 风控熔断（30min，全局）")`，
`zq.bench_account(rt, "acct-a", reason=cm.reason())` 回写（= CLI 走的那条路），随后在 4 个时刻各读一次。原样输出：

```
[23:50] enter → 落盘 reason = 'ZCode 风控熔断（30min，全局）'
[23:50] 落盘 until_ms = 1790612400000  (=00:20:00)
[23:50] bench_account 处理 1 条；文件里是否含「明日」= False
  23:50 熔当刻   circuit.reason() = ZCode 风控熔断（30min，全局），至 明日 00:20
                snapshot.last_error = ZCode 风控熔断（30min，全局），至 明日 00:20
                status=cooldown 冷却剩余=1800s 钟点一致=True
  23:55 读      circuit.reason() = ZCode 风控熔断（30min，全局），至 明日 00:20
                snapshot.last_error = ZCode 风控熔断（30min，全局），至 明日 00:20
                status=cooldown 冷却剩余=1500s 钟点一致=True
  00:05 读      circuit.reason() = ZCode 风控熔断（30min，全局），至 00:20
                snapshot.last_error = ZCode 风控熔断（30min，全局），至 00:20
                status=cooldown 冷却剩余=900s 钟点一致=True
  00:19 读      ... 冷却剩余=60s 钟点一致=True（同一句「至 00:20」）
  00:21 到期后   circuit.reason() = ZCode 风控熔断（30min，全局），至 00:20
                snapshot.last_error = ZCode 风控熔断（30min，全局）
                status=active 冷却剩余=0s 钟点一致=False
```

判：**「明日」用对了地方**（23:50/23:55 说明日、午夜后不再说明日）、两出口在冷却中逐字相同、到期后快照只留原因（S-15 历史位）。
唯一不一致是**到期后 `reason()` 仍挂过去的钟点** —— 逐个查了 4 处生产调用点，全部被 `active()` 挡着：
`main.py:109`、`quota.py:593`、`cli_zcode.py:232/254`、`zcode_claim.py` 的 reason 紧跟 `enter()` → 列为**潜在**（§三 L-1），不计阻塞。

实机 HTTP 出口（`a7_http.py`，真 `create_app` + ASGITransport，未绑端口）：

```
[15:12:13] /admin/api/status   → cooldown 剩余=3998 最近错误='ZCode 风控熔断（30min，全局），至 10:17'
[15:12:13] /admin/api/overview → cooldown 剩余=3996 最近错误='ZCode 风控熔断（30min，全局），至 10:17'
[15:12:18] 到期后 /admin/api/status → active 剩余=0 最近错误='ZCode 风控熔断（30min，全局）'
  内存态 last_error = 'ZCode 风控熔断（30min，全局）'
```

喂进去的原因串**故意自带**「，至 09:99」→ 两出口都只有一份钟点（不拼两个 ✓），但请注意那句「至 10:17」—— 读的时刻是 15:12、冷却只剩 4 秒 → 这就是 **BLK-1**（§三）。

### A2 跨进程同口径：真起两个子进程（`a2_xproc.py`）

不同 cwd（`/tmp/mgw-accept-8a/xproc/pa`、`.../pb`）、同一 `MGW_ZCODE_ACCOUNTS`，`MG_CONFIG` 同指 /tmp：

```
### 真时钟：A enter → B 渲染
--- 子进程 pa（cwd=.../pa）rc=0 ---
PATH /tmp/mgw-accept-8a/xproc/circuit.json
FILE {"until_ms": 1790580818506.166, "reason": "ZCode 风控熔断（30min，全局）", "last_call_ms": 1790579018506.166}
REASON_AT_ENTER ZCode 风控熔断（30min，全局），至 15:33
--- 子进程 pb ---
PATH /tmp/mgw-accept-8a/xproc/circuit.json
CWD /private/tmp/mgw-accept-8a/xproc/pb
NOW 15:0x / ACTIVE True / REASON 'ZCode 风控熔断（30min，全局），至 15:33'
文件里含钟点？ False
### 冻结 23:50 熔 → 同一份文件在两个子进程里分别于 23:55 / 00:05 渲染
pa:  FILE {"until_ms": 1790612400000.0, "reason": "ZCode 风控熔断（30min，全局）", ...}
pb:  23:55  active=True  reason='ZCode 风控熔断（30min，全局），至 明日 00:20'
     00:05  active=True  reason='ZCode 风控熔断（30min，全局），至 00:20'
### 手动删除 circuit.json = 解除熔断
pb:  ACTIVE False  REASON ''
```

判：**跨进程成立** —— A 只落裸原因（文件里无钟点、无「明日」），B 读同一文件并在 23:55 说「明日 00:20」、00:05 说「00:20」；删文件即解除。（pb 那段"快照=至 00:25/00:35"是我在每个读时刻**重新回写了一次** `apply_to_resource`（冷却起点自然跟着当时的冻结钟点走）—— 属我的脚本口径，不是缺陷，故不登记。）

### A3 旧格式与手写坏值（`a1_s23.py` A2 段，11 种输入逐个判）

```
legacy 旧格式(含钟点)   active=True  reason='ZCode 风控熔断（30min），至 明日 00:51'  双钟点=False
                        mark_called 后落盘 reason = 'ZCode 风控熔断（30min）'      ← 旧格式被归一化掉 ✓
until 为字符串          active=False reason='x，至 22:13'   不崩 ✓  双钟点=False
until 为 null           active=False reason='x'             不崩 ✓（坏值当 0 = 不谎报熔断）
until 负数              active=False reason='x，至 07:59'    不崩 ✓ 不谎报 ✓
until 超大数(1e18)      active=True  left=999998209389400s  reason='x，至 明日 09:46'   ← 见下"观察"
reason 为 null          active=True  reason=''              快照 last_error=None
整个文件是数组 [1,2,3]   active=False reason='' 不崩 ✓
文件是裸字符串/空串/半个JSON  active=False reason='' 不崩 ✓
mark_called 后落盘 reason = ''（坏值文件被就地洗干净）
```

判：**11 种手写输入零 traceback**（S-26① 的 `float()` 崩栈确实没了）、不拼两个钟点、坏数字不谎报熔断（一律当无熔断）。
两条观察：① `until_ms` 写成天文数字会被当真熔断读（`left=1e15s`），属"用户手写自己坑自己"，建议加个上限（如 `until_ms - now > 24h` 视为坏值）而不是照印；
② `reason` 为 null 且仍 active 时回写出的行是 `status=cooldown + 最近错误=None`，与 S-26③ 修的"徽章指到空列"同形 —— 生产中 `enter()` 恒带原因，不可达，登记为观察。

### A4 「同一资源既有 30min 熔断又有 60s 冷却」两列是否同一瞬间（`a1_s23.py` A3 段）

```
顺序=先60s后退30min熔断 → cooldown 冷却剩余=1800s 最近错误='ZCode 风控熔断（30min，全局），至 明日 00:20'
顺序=先熔断后60s       → cooldown 冷却剩余=1800s 最近错误='上游返回 502：bad gateway，至 明日 00:20'
一条熔断/一条已恢复     → status=active available=True 冷却剩余=1800s 最近错误='ZCode 风控熔断（30min，全局），至 明日 00:20'
```

判：**钟点与列在同一条目上永远同一瞬间**（都由 `e.cooldown_until` 出，`bench()` 的 max+所有权挡住了"短冷却剪长冷却"，我按两种顺序都试了，没能拆开的钟点全部相等）。
但**行内两列不同源**：「冷却剩余」是 `max(全部条目)`，「最近错误」是**单条最严重条目**（`_worst_error_entry`：严重度相同再按 C）→ 第 3 行给出 `available=True` 却带着"等到 00:20"的一句话，且 `cooldown_remaining_ms=1800000` 而前端（`dashboard.js:103` 只在 `status==="cooldown"` 时印秒数）会印 `—` → 登记 **E-2**。
第 2 行还暴露：两条目同为 cooldown 时按 **C** 决胜，于是"真正挡路 30 分钟的风控熔断"被 502 原因顶掉 —— 与 S-1「挡路原因不得是假的」同族，归 E-2 一并处理。

### A5 S-26② 归一化单一口径：调用面 + 端到端（`a3_url.py`）

全仓扫描结果（`normalize_base_url` 消费者）：`core/resources.py:43`（指纹）、`main.py:235/240`（复用判定+建适配器）、`adapters/openai_out.py:53`、`adapters/anthropic_out.py:452`、`upstream/zcode/claim.py:167`、`cli_probe.py:32` —— **六处全部走同一函数**。其余 `rstrip("/")` 只剩 `upstream/zcode/captcha.py:108 site_root`（ZCode 站点根，不是资源 base_url，非同族）。`api/admin.py:292` 只做 `.strip()`，但值直接进 `build_adapter` → 由适配器归一化，不构成第二份口径。`probe.py`/`setup_tools.py` **完全不碰 URL**（URL 只在 `cli_probe.py`）。

端到端（假厂商 HTTP 服务在 127.0.0.1 随机端口，原始 URL = `'  http://127.0.0.1:PORT/v1/  '`，看厂商**实际收到的 path**）：

```
### 1) /v1/chat/completions         → 网关 HTTP 200 · 厂商收到的 path = ['/v1/chat/completions']
### 2) /admin/api/resources/test 草稿直连
  protocol=openai    → 200 {'ok': True, 'latency_ms': 1} 厂商侧 path=['/v1/chat/completions']
  protocol=anthropic → 200 {'ok': True, 'latency_ms': 1} 厂商侧 path=['/v1/messages']
  protocol=gemini    → 200 {'ok': True, 'latency_ms': 1} 厂商侧 path=['/v1/chat/completions']
### 3) 健康测试（已存资源）→ {'ok': True} 厂商侧 path=['/v1/chat/completions']
### 4) 适配器 base_url 归一化后 = 'http://127.0.0.1:63495/v1'（配置原值带空格+尾斜杠）
### 5) `mgw probe` 的 _make_call_fn（同一个带空格 URL）→ status=200 厂商侧 path=['/v1/chat/completions']
```

判：**没有出现"网关能跑、工具报错"**：转发 / 三类协议健康测试 / 已存资源健康测试 / probe 的 `_make_call_fn` 五个出口，厂商侧看到的 path 全无 `//`、无空格残留。S-26② 通过。
（同一轮里我另外打出一个**相邻的新洞**，登记 E-1。）

### A6 S-26⑤「每判定一次读一次盘」的实测开销（`a4_perf.py` + `a5_perf2.py`）

文件 52 字节；`_load` 逐个包计时器；批量走**真实 ops 函数** `zcode_claim.claim()`（50 个临时账号 + 假客户端，闸门挡下所有上游）：

```
裸 read_text：中位 10.00µs  p95 14.25µs  max 55.67µs
read+json.loads：中位 10.40µs  p95 12.00µs
50 账号 × (active+left_ms+throttle_wait_ms) → _load 调用 150 次，合计 1762µs，整段 1.81ms
  平均每次 _load = 11.74µs
熔断中 50 账号 × (active+left_minutes+reason+throttle) → _load 200 次 3085µs，整段 3.22ms
裸 _save（tmp 写 + os.replace）：中位 94.4µs p95 136.3µs

[全局熔断中] 3 批 × 50 账号 = 150 次领取 → _load 301 次（每账号 2.01 次）· 读盘合计 3.68ms ·
  整轮 10.8ms → 读盘占 34.1% · 单次 _load 中位 11.6µs p99 17.5µs
```

调用面统计（grep `get_circuit()` 全部命中）：`main.py:108`（仅启动一次）、`quota.py:592`（`sync_circuit_to_runtime`，启动/接线时）、`cli_zcode.py:230/254`（CLI 一次）、`zcode_claim.py:120/140/179`（每账号 2~4 次）。**转发路径（`scheduler` / `api`）一次都不碰熔断文件** —— 每请求 0 次读盘。

判：**"每判定一次读一次盘"不构成问题，按量化结论不建议再加缓存**。50 账号批量领取一轮 = 301 次读盘 ≈ **3.7ms**；而同一轮的 10s 节流（`THROTTLE_MS`）意味着账号之间本来就要 `await` 10 秒（我实测未熔断批量时 150 次领取要跑到几百秒，正是节流而非读盘），读盘占节流的比例 ≈ **0.1‰**。真正会放大的只有 `_save`（中位 94µs/次），量级同样无害。⚠️ 但要留一句事实给 PM：**S-26⑤ 的代价不在耗时，而在"读盘次数随并发放大"** —— 目前是每判定 1 次同步 `read_text`，跑在事件循环线程上；若将来把运营改成并发批次（当前是串行 for），11.7µs×N 的同步读会开始咬事件循环，届时应换成 `to_thread` 或 mtime+size 双判据，而不是回退成 S-26⑤ 之前的纯 mtime 缓存。

### A7 机械门与纪律复算

```
.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest-8a -p no:warnings
  → 693 passed in 124.95s (0:02:04)
find data -newermt "2026-09-28 14:30" -type f  → 空（本轮未碰用户数据）
git status --porcelain 与开工前一致（我只写了本文件；docs/ 被 gitignore）
curl -s http://127.0.0.1:8300/admin/api/status → exit 7 连接被拒
```

⚠️ **`:8300` 上用户的网关实例当前并未在跑**（连接被拒），因此"实机界面那一列"我无法直接取证；改用真 `create_app` + ASGITransport（未绑端口、未起 uvicorn、未重启/杀任何进程）复现，输出的正是 `admin.py:118/167` 那两个真实出口。

---

## ③ 阻塞项与登记项

### BLK-1（阻塞）：读时渲染跨了时钟域 —— 「最近错误」列的钟点是 1970 年式的假时刻

最小复现（`a8_clockdomain.py`，零内部字段篡改，只用公开 `bench()` 与真 `create_app`）：

```
本机 time.monotonic() = 699511.2  · time.time() = 1790579587.5  · 开机以来 ≈ 194.31 小时
现在的真实钟点 = 15:13:07
fmt_recovery_clock(monotonic+30min, monotonic) = '10:48'   ← 正确答案应为 '15:43'

—— 生产默认时钟（main.py:188 `ResourceManager()` 用的就是 time.monotonic）——
  ResourceManager.clock 函数 = time.monotonic
  冷却中的行 → status=cooldown 冷却剩余=1800s
  「最近错误」列 = 'ZCode 风控熔断（30min，全局），至 10:48'
  ↑ 30 分钟后 = 15:43，而列里印的是上面那个串

—— 真·转发路径（资源指向 127.0.0.1:9 拒连，连打 4 次，无任何注入）——
[15:13:43] /admin/api/status 的总览行：
  {'status': 'cooldown', 'cooldown_remaining_ms': 59997,
   'last_error': '[network] network: ConnectError: All connection attempts failed，至 10:20'}
  条目 cooldown_until = 699608（单调钟）· 按 epoch 格式化 = 10:20 · 真实到期 = 15:14
```

根因链（`file:line`）：
1. `core/resources.py:252 def __init__(self, clock=time.monotonic)`，`main.py:188 self.resources = ResourceManager()` → **生产 `cooldown_until` 活在单调钟域**；
2. `core/resources.py:211` `f"{e.last_error}，至 {fmt_recovery_clock(e.cooldown_until, now_s)}"`，而 `fmt_recovery_clock`（`:167-174`）用 `time.localtime(...)`；
3. `quota.py:332 _epoch_ms()` 刻意用墙上时钟（注释写明"不能用 monotonic"），S-21 的读时渲染因此成立 —— 但 S-23 把同一把尺借给**单调钟域的条目字段**时没做换算。

后果：**任何一条进入冷却且带原因的资源**（`note_failure` 每次失败都写 `last_error`，`resources.py:416-419`）在总览那一列印出与"多久之后能用"无关的假时刻（`up=86300` 的注入版实测印「至 08:28」，而真实钟点是 15:13）。此外 `fmt_recovery_clock` 的「明日」判据比的是**两个单调钟读数各自的 `tm_yday`**（等价于"开机秒数是否跨过本地午夜线"），与真实日期无关 —— 该分支**能**假翻，但我这一轮没能让它真的翻出「明日」（东八区偏移下 86300/88100 落在同一"日"），故此项标 **未验证**，不作为独立缺陷登记。同一行的「冷却剩余」是对的（`cooldown_remaining_ms` 用同域相减）→ 同行两列自相矛盾，用户照「至 10:20」判断何时重试必然判错 —— 与 S-23/PRD Q28-⑦ 的裁决正面冲突。

为什么 693 条判据抓不到（务必一并补判据，否则下轮还会漏）：
- 单元/集成用例几乎都 `ResourceManager(clock=lambda: t[0])` 注入 **epoch 值**（`tests/unit/test_v2_circuit.py:617`、`test_v2_servable.py:275` 等），于是 `fmt_recovery_clock` 收到的是合理时刻；
- 唯一用生产默认钟的 `test_snapshot_exposes_last_error_for_the_health_card`（`test_v2_circuit.py:291-307`，内部 `_RealMgrRuntime.resources = ResourceManager()` 见 `:510`）只断 `re.search(r"，至 (?:明日 )?\d{2}:\d{2}$")` —— 假时刻照样命中正则，**判据形态而非语义**。

建议修法（择一，我未改生产代码）：
- (a) 快照侧不碰域：`_rendered_last_error` 改用"当下墙上钟 + 剩余秒"渲染，即 `fmt_recovery_clock(time.time() + max(0, e.cooldown_until - now_s))`（`cooldown_remaining_ms` 已经是同域相减，天然安全），并给 `fmt_recovery_clock` 的 docstring 钉死"入参必须是 epoch 秒"；
- (b) 把 `ResourceState.cooldown_until` 整体迁到墙上钟（`_epoch_ms/1000`）—— 改动面大（S-1/S-2 的 max、懒恢复、`bench` 全部要复核跨域回归），且失去单调钟对系统时间跳变的免疫；
- 无论哪种，判据必须补一条**用生产默认钟**的语义断言：`mgr = ResourceManager()`（不注入）→ bench 后 `row["last_error"]` 里的 `HH:MM` 必须等于 `time.strftime("%H:%M", time.localtime(time.time() + cooldown_remaining_ms/1000))`。这一条在今天的代码上必红。

### 非阻塞登记

| # | 问题 | 证据 | 建议 |
|---|---|---|---|
| L-1 | `circuit.reason()` 在**到期后**仍挂过去的钟点（快照侧已按 S-23 剥掉）→ 两出口在"文件还在、已过期"窗口互相矛盾；目前 4 处生产调用全被 `active()` 挡着（`main.py:109`、`quota.py:593`、`cli_zcode.py:232/254`），属潜在 | A1 输出 `00:21 到期后 … 钟点一致=False` | `_with_until()` 加 `until_ms <= now → 只回裸原因`（与快照同语义），别再靠调用方守门 |
| E-1 | **归一化口径的"第六处"**：`main.py:232 if not r.base_url` 用**原串**判空，其余全用归一化值 → `base_url: "   "`（只填空格，粘贴场景常见）归一化成 `""` 仍被建适配器，模型照常 `/v1/models` 下发、`servable_models` 判可服务，每次请求 503 且直出 httpx 黑话 | `a6_scheme.py`：`adapters keys = ['res-noscheme','res-space','res-ok']` · `servable_models = ['s-bad','s-ok']` · `/v1/chat/completions[s-bad] → 503 "[network] network: UnsupportedProtocol: Request URL is missing an 'http://' or 'https://' protocol."` | ① `main.py:232` 改判 `normalize_base_url(r.base_url)`；② 加载期给"非空但归一化后为空 / 缺 scheme"的 base_url 出一条 config 警告并**把该资源挡出 `servable_models`**（§12.1 消灭无报错失败）；③ `[network] network:` 这段前缀重复 + `UnsupportedProtocol` 属 S-12 同类黑话，一并洗 |
| E-2 | 行内两列不同源：「冷却剩余」`max(条目)` vs「最近错误」单条最严重（严重度同则比 C）→ ① `available=True` 的行可带"至 00:20"且 JSON 里 `cooldown_remaining_ms=1800000`，前端却印 `—`；② 30min 风控原因会被同资源另一条 502（C 更大）顶掉，挡路原因失真 | A4 三行输出 | 快照先按"**真正决定这一行能不能用的那条条目**"取（剩余时间最大的条目优先，其次严重度），并把 `cooldown_remaining_ms>0` 与 `available` 的互斥关系写进判据 |
| E-3 | 代码卫生：`_SEVERITY` 在 `core/resources.py:146` 与 `:184` **同定义写了两遍**（连注释三份），S-16/S-20 那套死符号护栏抓不到（两处都"被引用"） | grep：`resources.py:146` / `resources.py:184` | 删一份；判据可加"同一模块内同名 AST 赋值不得重复" |
| E-4 | `until_ms` 为天文数字时照单全收（`left=999998209389400s` → 界面显示"剩余几千万年"）；手写文件才会命中 | A3 输出 | `_ms_or_zero` 之外加合理性上限（如超过 now+24h 视为坏值并留日志） |

---

## ④ 我试过但**没能打破**的攻击面

1. **两出口逐字一致性**（S-23 核心命题）：23:50 / 23:55 / 00:05 / 00:19 四个读时刻，`circuit.reason()` 与 `snapshot_by_resource()["last_error"]` **完全同一句话**，「明日」只在真正跨午夜时出现、午夜后自动消失；落盘的 `circuit.json` 里**不含**任何钟点（`文件里含钟点？ False`）。打不破。
2. **旧格式/坏值 11 种**：字符串/null/负数/超大数 `until_ms`、`reason` 为 null、整体是数组、裸字符串、空串、半个 JSON、reason 只有钟点 —— **零 traceback**、零"两个钟点"、坏值一律不谎报熔断；且 `mark_called()` 回写时把旧格式**就地归一化**（`'ZCode 风控熔断（30min）'`）。打不破（除 E-4 的"照单全收"）。
3. **跨进程**：两个真子进程（不同 cwd）共用同一 `circuit.json`，B 完整复现 A 的熔断并在同刻给出同一句原因；删文件 = 新进程 `active()=False`（CLI 承诺的手动出口成立）。打不破。
4. **冷却所有权 vs 钟点**：我先 60s 后 30min、先 30min 后 60s 两种顺序都试（含 `note_failure` 写原因 + `bench` 返回 False 的组合），**没有任何一次**让"最近错误"的钟点跑在「冷却剩余」前面 —— `bench()` 的 `max` + 返回值裁决确实拦住了 S-1/S-2 那一族。没打破（只在**跨条目聚合**上打破，见 E-2）。
5. **URL 归一化五个出口**：真转发 / `resources/test`（openai·anthropic·gemini 草稿直连）/ 已存资源健康测试 / `probe._make_call_fn`，喂同一个 `'  http://host:port/v1/  '`，厂商侧 path 全部规范；`normalize_base_url` 幂等；全仓再无第二份 `base_url...rstrip("/")`（只剩 `captcha.py` 的站点根，不同族）。没打破（相邻洞另登记 E-1）。
6. **`_load` 去掉 mtime 缓存**：用 `os.utime` 把 mtime 钉成同一秒（他们的判据 `test_breaker_written_within_the_same_second_is_still_seen` 的形态）我复跑在 693 里；另外我按"每判定一次读一次盘"实测了 301 次/150 账号轮 = 3.7ms，找不到能量化的退化。没打破。
7. **实机界面出口**：`:8300` 未运行（curl exit 7），我改在真 `create_app` + `/admin/api/status`、`/admin/api/overview` 两个真实 HTTP 出口上取证 —— 到期前后那句话的变化与注入版一致（除 BLK-1 的钟点数值本身）。

---

## ⑤ 交付自证

```
$ ls -la docs/changes/reviews/eng-accept-8a.md
-rw-r--r--@ 1 w  staff  23459 Sep 28 15:15 docs/changes/reviews/eng-accept-8a.md   （243 行）
$ git check-ignore -v docs/changes/reviews/eng-accept-8a.md
.gitignore:17:docs/        docs/changes/reviews/eng-accept-8a.md      ← 报告按项目约定不进版本库
$ git status --porcelain | grep -v '^ M \|^?? ' | wc -l
       0                                                            ← 本轮零新增改动（工作树与开工前一致）
$ find data -newermt "2026-09-28 14:30" -type f | wc -l
       0                                                            ← 用户数据目录未被触碰
```
本轮**未修改任何生产代码/测试**；未读写 `data/`、`~/.zcode`、`~/.workbuddy`、`~/.workbuddy-ai`；未发起真实上游请求（全部指向 127.0.0.1 上的假厂商 / 端口 9 拒连）；未重启或杀 `:8300`（它本来就没在跑）。
