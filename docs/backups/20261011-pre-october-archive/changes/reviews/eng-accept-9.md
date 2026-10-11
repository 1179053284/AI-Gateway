# eng-accept-9 — 第九轮后端工程复验（第八轮四项修复的成立性 + 晚到修改自引入的问题）

复验人：后端工程视角子 agent · 日期：2026-09-28 · 基线：工作树 HEAD `5158cbc`（复验前后 `git diff --stat` 一致，仓库内除本文件零改动）
依据：`docs/changes/e2e-records/E2E-20260928-round5-fixes.md` 文末「第八轮复验的补做（S-28 ~ S-31）」表 + 「第八轮的自我交代」两节。

---

## ① 结论

**有条件通过：第八轮的四项修复（S-28 时基 / S-31 两列同源 / S-29 中途失写 / S-26 追加 E-4+L-1）与 E-1、E-3 全部在本轮独立复现下成立；阻塞项 0。**

- 机械门复跑一致：`.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest-9 -p no:warnings` → **`701 passed in 126.30s`**（与账本宣称的 701 持平，无新增红）。
- 我以**生产默认钟**（不注入）跑真 `create_app` → `bench()` → `snapshot_by_resource()`，钟点与 `time.time()+剩余` 逐字相等，且"单调钟数值格式化出的假钟点"未出现。
- S-29 在**真实子进程**里对三种破坏（chmod 500 / 目录整个删掉 / 换成指向只读目录的软链）逐一实测：前两种与第三种按预期 `failed`+`skipped=[]`+抬头分级+`rc=1`；**"目录整个删掉"这一种是自愈放行**（见 N-3）。
- 新登记 6 条非阻塞（N-1…N-6），其中 **N-1（`wall_now` 测试专用参数无护栏）与 N-2（合理性上限的失效方向是 fail-open）** 建议下一轮处理：前者是 S-28 复发的唯一通路，后者与本仓库自己的 S-22 裁决（"宁可拒跑也不双领"）取向相反。

纪律：仓库 `data/` 全程只读（`find data -newermt "2026-09-28 15:30" -type f` → **空**）；未访问真实上游（全部端点为 `127.0.0.1:9` 死端口或空格串）；未读写 `~/.zcode`/`~/.workbuddy`/`~/.workbuddy-ai`（`mgw setup` 只跑 `--dry-run`，且在"未配置接入密钥"处即 rc=2 退出）；`:8300` 未启动/未重启（`lsof -nP -iTCP:8300 -sTCP:LISTEN` 无输出，全程用 `TestClient` 进程内回环，配置端口 8931 仅作占位、从未 bind）。所有脚本与副本在 `/tmp/mgw-accept-9-eng/`。

---

## ② 逐项取证

### 1. S-28 时基（`core/resources.py:_rendered_last_error`）

我跑了什么：`/tmp/mgw-accept-9-eng/a_s28_s31.py` —— 真 `create_app`（配置落 `/tmp/mgw-accept-9-eng/conf-a/config.yaml`），**不注入任何时钟**，取 `app.state.runtime.resources` 直接 `bench()` 后 `snapshot_by_resource()`，再打 `/admin/api/overview`。

```
A1 clock.__name__ = monotonic | monotonic = 702197.8
A1 row: cooldown 1799999 'ZCode 风控熔断（30min，全局），至 16:27'
A1 期望钟点(墙钟倒推) = 16:27 | PASS
A1 反向断言：单调钟格式化出的假钟点 11:33 不得出现 → PASS
A2 A2-同日   注入墙钟=23:30 剩余=1799999 → 'ZCode 风控熔断（30min，全局），至 23:59' | PASS
A2 A2-跨午夜 注入墙钟=23:50 剩余=1799999 → 'ZCode 风控熔断（30min，全局），至 明日 00:19' | PASS
A2 复原 time.time: True
A7 overview status: 200
A7 resources[].last_error: res-a active 1799989 '上游返回 401：凭据已失效'
```

- 判定：**成立**。生产默认钟是 `time.monotonic`（本机量级 70.2 万秒），钟点仍由 `time.time()+剩余` 倒推；`11:33`（把 `cooldown_until` 直接交给 `time.localtime` 的旧错法产物）未出现。跨午夜走的是**生产分支**（`wall_now=None` → `time.time()`），「至 明日 00:19」正确。
- **我在脚本里改了什么（交代）**：为造跨午夜，仅在进程内 `time.time = lambda: <2026-09-28 23:50 的 epoch>`，取完快照立刻复原（脚本自带复原断言 `A2 复原 time.time: True`）；`cooldown_remaining_ms` 仍由真实单调钟计算，未被伪造。仓库文件零改动。
- 秒级进位（A7 段，同一脚本）：`剩余 1799999 → 至 16:27`、`剩余 1829998 → 至 16:28`，无 off-by-one。

🔴 **攻击 `wall_now`**：

```
A6 签名: (entries: list['ResourceState'], status: str, remaining_ms: int,
          wall_now: float | None = None) -> str | None
A6 全仓命中（生产代码树）:
    model_gateway/core/resources.py:193 def _rendered_last_error(...)
    model_gateway/core/resources.py:195 wall_now: float | None = None) -> str | None
    model_gateway/core/resources.py:216 wall = wall_now if wall_now is not None else time.time()
    model_gateway/core/resources.py:564 "last_error": _rendered_last_error(entries, status, remaining_ms)
F3 wall_now 测试侧调用点（tests/）：
    test_v2_circuit.py:248 _rendered_last_error(entries, "cooldown", 60_000, wall_now=0.0)
    test_v2_circuit.py:282 _rendered_last_error([entry], "cooldown", 1500_000, wall_now=t2350 + 300)
    test_v2_circuit.py:284 _rendered_last_error([entry], "cooldown", 900_000, wall_now=t2350 + 900)
    （其余 5 处均不传 wall_now）
A6 生产调用（不传 wall_now）: ZCode 风控熔断（30min，全局），至 16:27
A6 若调用方传 manager 钟（单调）: ZCode 风控熔断（30min，全局），至 11:33   ← S-28 原样复活
A6 若传 0（测试用例现写法）:     ZCode 风控熔断（30min，全局），至 08:30
```

结论：**没有第二个生产调用点**，现存调用点不传该参数 → 修复当前成立。但"只有测试在用"这件事本身就是风险：参数存在、无类型/量级护栏、无任何断言禁止传入 `manager.clock()`，而它一旦被误用，产出正是一个"看着像恢复时刻的 1970 年/开机秒假钟点"，且 701 条判据里没有任何一条会因此变红（S-28 上一轮的假绿机制就是"每条都注入了 epoch 钟"）。→ **N-1**。

### 2. S-31 两列同源

我跑了什么：同一资源两条映射、剩余时长不同（60s / 1800s）、`C` 不同（9 / 1），再看三种混合形态；并核对前端三个出口。

```
A3 row: cooldown 1799999 C= 9 '上游限流，冷却中，至 16:27'
A3 同源 PASS | 未用 60s 钟点 PASS | 原因取自最严重(C=9)条目: True
A4 row: active   剩余= 1799999 'ZCode 风控熔断（30min，全局）'          | 钟点有无 = False
A5 row: disabled 剩余= 1799999 '上游返回 401：凭据已失效'                | 钟点有无 = False
```

- 判定：**成立**。`remaining_ms` 与钟点同源（`snapshot_by_resource` 先算 `cooldown_remaining_ms=max(...)`，两处共用，`resources.py:550` 与 `:564`）。原因取自 `_SEVERITY`+`C` 最重条目、钟点取整资源最大剩余——资源级语义自洽（"本资源最早可承接"= 最后一条冷却到期），不是 ix-8 那版的"各说一套"。
- 混合形态：**最严重条目已过期并恢复**（A4）→ `reconcile_expired()` 先跑，聚合变 `active`，文案只留历史线索、**不配过去的钟点**；**判死条目 + 另一条仍在冷却**（A5）→ 聚合 `disabled`，原因取判死条目、同样不配钟点。两处都不自相矛盾（不给"判死"编一个恢复时刻），符合账本 S-31「非 cooldown 状态一律不配钟点」。
- 前端出口核对（`model_gateway/web/static/js/pages/dashboard.js`）：

```
:103 ${r.status === "cooldown" ? fmtCooldown(r.cooldown_remaining_ms) : "—"}
:129 const left = Math.ceil((r.cooldown_remaining_ms || 0) / 1000);
:133 left > 0 ? `${fmtCooldown(r.cooldown_remaining_ms)} 后自动回池，无需处理`
:104 <td class="ellip" ... title="${esc(r.last_error || "")}">${esc(r.last_error || "—")}</td>
```

  「冷却剩余」列、徽章 title 的「Xs 后自动回池」、「最近错误」列**三处都用同一个 `cooldown_remaining_ms`、都以 `status==="cooldown"` 门控**，且 `last_error` 经 `esc()` 原样透传（前端不做任何钟点运算）→ A7/F 载荷的 `…，至 16:38` 到界面是一字不差的。node 门的 **K6「冷却中的资源在页面上肉眼印出恢复时刻」为绿**（用真端点载荷）。
- 唯一残形：A4/A5 里 payload 的 `cooldown_remaining_ms` 仍是非零最大值而 `status` 非 cooldown。UI 因门控而不打架，但**直接读 `/admin/api/overview` 的第三方**会看到 `status=disabled` + `cooldown_remaining_ms=1799999` 的组合 → 登记 **N-6**（判可接受：语义是"该资源某条映射仍在冷却"，非谎报）。

### 3. S-29 中途失写（`ops/runner.py` + `cli_zcode._claim`）

我跑了什么：`/tmp/mgw-accept-9-eng/b_proc.py` 由 `c_run.sh` **起真实子进程**（每场景独立 `MG_CONFIG`/`MGW_OPS_LOCK_DIR`/`MGW_ZCODE_ACCOUNTS` 全在 /tmp），三场景 × 三阶段：① 真 `run_once`；② 真 `cli_zcode._claim`（抬头+退出码+落盘）；③ 真 `Scheduler.start(interval_s=1)` 跑多个 tick 并在中途破坏、随后恢复权限。

**chmod 0o500**（第一个账号跑完后）：

```
[child] 已施加 chmod：lock_dir=/tmp/mgw-accept-9-eng/s-chmod/locks exists=True usable=False
[child] run_once calls = ['acct-1']
[child] report = {"success": ["acct-1"], "failed": [
   {"account": "acct-2", "reason": "运营互斥锁目录在本轮中途不可写：… 本账号及其后共 2 个账号均未发起操作（宁可拒跑也不双领）…"},
   {"account": "acct-3", "reason": "…同上…"}], "skipped": [], "no_participants": false}
[child] skipped = []
运营锁释放失败（/…/s-chmod/locks/acct-1.lock：[Errno 13] Permission denied）→ 交给超龄回收，不向上抛
✓ 已领取 1 个
✗ 失败 2 个（其中 2 个**未发起**：互斥锁不可用，本轮拒跑 → 查数据目录权限）：
    acct-2  运营互斥锁目录在本轮中途不可写：…
    acct-3  运营互斥锁目录在本轮中途不可写：…
    逐条明细已落盘：/private/tmp/mgw-accept-9-eng/s-chmod/conf/usage/ops-results-20260928.jsonl
[child] CLI 退出码 = 1
```

→ 四项判据全中：后续账号 `failed` ✓、`skipped == []` ✓、抬头分级「其中 2 个**未发起**」✓、退出码 1 ✓；第一个账号的真实成功未被抹掉 ✓；`release()` 的 `PermissionError` 被吞成 warning 未上抛（S-24 边界未被 S-29 改动破坏）✓。

**Scheduler 段（同场景）**：

```
[child] tick0 failed=2 skipped=[] success=1
[child] tick1 failed=0 skipped=[] success=3
[child] tick2 failed=0 skipped=[] success=3
[child] tick3 failed=0 skipped=[] success=3
[child] scheduler task 存活 = None errors = 1 ticks = 4 恢复后立即再拿 plan 锁 = True
运营 plan 锁不可用（/…/s-chmod/locks）→ 定时器每轮都会跳过，运营已停摆；请检查数据目录权限
```

（`task 存活 = None` 是我的探针在 `stop()` 之后读 `self._task` 的写法问题，`stop()` 会置 None；`ticks=4` 与各 tick 结果才是证据。）**恢复可写后不需要重启即回到 `success=3`**，孤儿 `__plan__.lock` 被自己回收（`runner.py:173` 有 `if pid == os.getpid(): unlink; continue` 分支）→ 我原本怀疑"15 分钟超龄期内运营被自己的陈旧锁永久挡住"，**打破失败**（见⑤）。

**软链变体**（锁目录换成指向 `chmod 500` 目录的软链）：

```
[child] 已施加 symlink：lock_dir=…/s-symlink/locks exists=True is_symlink=True usable=False
[child] run_once calls = ['acct-1'] … "skipped": []（acct-2/acct-3 failed，"中途不可写"）
✗ 失败 2 个（其中 2 个**未发起**…）    [child] CLI 退出码 = 1
[child] tick0 failed=1 skipped=[] success=2 / tick1 success=3 / tick2 success=3
```

→ 只读软链同样落进 fail-closed 分支 ✓（打印的路径是解析后的 `ro-target`：生产实例走 `ops_lock_dir()`（resolve），我显式传入时保留软链形态——两者只是显示口径，行为一致）。

**目录整个删掉（rmdir）变体 —— 新发现（N-3）**：

```
[child] 已施加 rmdir：lock_dir=/tmp/mgw-accept-9-eng/s-rmdir/locks exists=False usable=True
[child] run_once calls = ['acct-1', 'acct-2', 'acct-3']
[child] report = {"success": ["acct-1","acct-2","acct-3"], "failed": [], "skipped": []}
✓ 已领取 3 个
全部正常，无需处理
[child] CLI 退出码 = 0
[child] scheduler … errors = 0 ticks = 5（每个 tick 都 success=3）
```

根因：`_acquire_file()` / `usable()` 都以 `target.parent.mkdir(parents=True, exist_ok=True)` 起手，目录被删后**当场重建**，于是 `usable() is True`，S-29 的中途探测不会触发。后果是：别的进程（并发 CLI / cron 腿）持有的锁文件随目录一起消失，本轮继续发起 → **跨进程互斥被摧毁，存在双领窗口**，而用户看到的是"全部正常"。与 S-22/S-29 的边界（"不可写"）不冲突，属同族缺口（账本 G1 的邻居）。产品内没有删除者（见下面回归面的 F1 实测），故登记为**非阻塞**。

**我在子进程里替换了什么（交代）**：① `R.product_of_account` 打桩为恒返回 `"zcode"`（避免在真实账号根建假账号，`has_account` 走的是 `~/.zcode` 口径）；② `B.OPERATIONS[zcode_claim.OPERATION_ID] = dataclasses.replace(op, run=fake_claim)` —— 第一版我直接 `op.run = fake_claim`，被 frozen dataclass 挡下：`dataclasses.FrozenInstanceError: cannot assign to field 'run'`（原始报错已留存于本轮首次运行输出），`_claim` 每次从 `OPERATIONS` 取对象，替换字典项即可，**未改仓库源码、未发真实上游**（`fake_claim` 只 append 账号名并按场景破坏目录）。

### 4. S-26 追加（E-4 合理性上限 / L-1 过期分支）

我跑了什么：`/tmp/mgw-accept-9-eng/d_quota.py`（`logging=WARNING` 直连 stdout，能看到归 0 时的日志）。

```
D0 SANITY_HORIZON_MS = 86400000 = 24h? True
D1 'now+23h59m'   → _ms_or_zero = 1790086340000.0        ← 保留
D1 'now+24h 整'   → _ms_or_zero = 1790086400000.0        ← 保留（判据是 `v > horizon`）
LOG WARNING 熔断状态里的时间戳不合理（1790086400001.0 > 现在+24h）→ 按坏值处理（视为无熔断）
D1 'now+24h+1ms' → _ms_or_zero = 0.0                     ← 归 0 并留日志
D1 'now+25h'     → 0.0（同上 WARNING）    D1 '天文数字(1e18)' → 0.0（WARNING）
D1 '负数 -1e15'  → -1000000000000000.0（原样）  D1 '0' → 0.0  D1 '字符串 "123"' → 123.0  D1 'None' → 0.0
D2 已过期: active = False | reason = 'ZCode 风控熔断（30min，全局）' | left_ms = 0.0
D2 负 until: active = False | reason = '负数到期' | left_ms = 0.0
D4 enter 后立刻 reason: '上游返回 3012：命中风控，至 22:43' | active = True
D4 过点后 reason: '上游返回 3012：命中风控' | active = False
D4 恰好到期瞬间 reason: '上游返回 3012：命中风控' （应无钟点）
D4 双钟点检查: 1 0
D4 传入 now=None 的未过期裸调用 = 'X，至 16:04'   D4 传入 now=None 的已过期裸调用 = 'X'
D4 空原因 = '' 'X'
```

- 判定：**成立**。边界无 off-by-one（23h59m 保留、恰 24h 保留、+1ms 才归 0，与注释「超过现在+24h」字面一致）；负数/0/字符串/None 全部不崩、不谎报（`active() False`、裸原因、`left_ms 0`）；L-1 的过期分支与 `enter()` 立刻 `reason()` 的组合仍给钟点，过点/恰过点给裸串，**没有双钟点**（`，至` 计数 1 / 0）。
- 🔴 **反噬方向（新发现 N-2）**：`_load()` 把 `self._now()` 当合理性基准，钟一偏小就把**真熔断**判成坏值：

```
D3 [真实 epoch 钟] active = True | reason = '真实刚写入的 30min 熔断，至 16:33'
D3 [now=0（无钟）] active = False | reason = '真实刚写入的 30min 熔断'
D3 [单调钟当 epoch（time.monotonic()*1000）] active = False | reason = '真实刚写入的 30min 熔断'
LOG WARNING 熔断状态里的时间戳不合理（1790584384087.687 > 现在+24h）→ 按坏值处理（视为无熔断）
```

  生产默认 `self._now = now or _epoch_ms`，且全仓**没有**生产调用点注入 `now=`（grep 仅测试命中），所以当下不致命；可达路径是**系统时钟回拨 >24h**（NTP 纠正/用户改日期）——此时 30 分钟熔断被静默清零、领取照打上游。失效方向是 **fail-open**，与本项目 S-22「宁可拒跑也不双领」的 fail-closed 裁决相反。→ N-2。

### 5. E-1（`main.py` 判空）/ E-3（`_SEVERITY` 单份）+ 全仓判空审计

```
main.py:235            if not normalize_base_url(r.base_url):
main.py:238            if (old is not None and old.base_url == normalize_base_url(r.base_url)
main.py:243                    r.protocol, normalize_base_url(r.base_url),
$ grep -rn "^_SEVERITY" model_gateway tests scripts
   model_gateway/core/resources.py:178:_SEVERITY = {"invalid": 3, "disabled": 2, "cooldown": 1, "active": 0}
```

- **E-3 成立**：`_SEVERITY` 全仓仅一处定义（第八轮曾两份互相遮蔽）。**E-1 成立**：判空与复用比较都用归一化尺；空格端点不建适配器（账本判据）+ 我本轮 A 段用空格串配置复跑过 `F2` 路径（见下）。
- 判空/比较仍用原串的残余点（逐个查过）：

| 位置 | 形态 | 实测 |
|---|---|---|
| `api/admin.py:292` | `(body.get("base_url") or "").strip()` → `:298 if not (base_url and api_key)` | 空格草稿已被 `strip()` 挡住，**不是**同类缺口 |
| `setup_tools.py` | 无 `base_url` 字段使用 | 不适用 |
| `upstream/zcode/claim.py:167` | `self.base_url = normalize_base_url(base_url)` | 已同源 |
| `adapters/{openai_out,anthropic_out}.py:53/452` | 入站即归一化 | 已同源 |
| `core/resources.py:43`（指纹） | `normalize_base_url(getattr(r,"base_url",""))` | 已同源 |
| 🔴 `cli_probe.py:51` | `enabled = {r.id: r for r in config.resources if r.enabled and r.base_url}` | **仍用原串判空**；`_make_call_fn` 内部倒是归一化（`:32`）。实测见下 |

```
F2 $ mgw probe --yes --model m2 → rc=1        （m2 的资源端点是 "   " 三个空格）
      ✗ m2                           → 探测失败，保留硬编码 fallback
      完成：成功 0 个，失败 1 个（方言表已写入 /private/tmp/mgw-accept-9-eng/conf-e/dialects.json）
      （网关未运行，跳过重载通知；下次启动会自动加载）
F2 $ mgw probe --yes --model m1 → rc=1        （m1 端点 127.0.0.1:9 死端口）
      ✗ m1                           → 探测失败，保留硬编码 fallback
```

→ 后果限定在 CLI probe 腿：空格端点被当成"有端点"参与探测，最终以「探测失败，保留硬编码 fallback」收场（不是 traceback、不发真实上游），但用户不会被告知"这一栏还没填"。属 E-1 同族的**文案/一致性**缺口 → **N-4**。

### 6. 回归面

**(a) `/admin/api/overview` 的 `resources[].last_error` 消费者**：见 §2 的 dashboard.js 摘录（`esc()` 原样、三处同源同门控）+ `A7 overview status: 200`。node 门用我 dump 的真实载荷复跑：

```
dump row: res-a cooldown 1799994 'ZCode 风控熔断（30min，全局），至 16:38'
######## NODE 实测 ########  实测 76 项，通过 65 项，失败 11 项
  ✗ A1…A9（告警横幅/503/「未被任何系统模型引用」/推理优先级「请求级」/覆盖告警三态…）
  ✗ K1 告警横幅真的出现在页面产出里   ✗ K2 资源健康表真的挂进页面
######## NODE 变异 ########  ✗ 基线本身就有 11 条红（A1…A9,K1,K2）——先修实测再谈变异
```

判定：这 11 条红的成因是**我的载荷只有一条资源、`warnings` 只含"未配置接入密钥"**，不含 A 段/K1 所需的告警样本；与冷却/钟点相关的 **K6「冷却中的资源在页面上肉眼印出恢复时刻」为绿**（对 `…，至 16:38` 的可见文本判据成立）。第八轮宣称的「实测 76 项失败 0 项 / 可红 76/76」需要它自己的告警载荷，**本轮未复现 → 该数字标 未验证**（不是红证，也不是绿证）。

**(b) `stats/events.py` 保留清理会不会删 `.write-probe.lock`/锁文件目录**：

```
F1 usage 真清理后: ['daily-20260101.json', 'locks-nested']
F1 外层锁文件仍在: ['.write-probe.lock', 'acct-x.lock']
F1 嵌套 locks-nested 仍在: True
```

（清理挂在 `EventLogger.start()`，构造本身不触发——我第一次只 new 不 start，误得"什么都没删"，加上 `start()` 后为上面这份。）过期 `events-/switch-events-/ops-results-*.jsonl` 与过期 ack 水位被删，`daily-*.json` 保留，**锁文件与嵌在 usage 里的锁目录都不受触碰** ✓。

**(c) `mgw setup` / `mgw probe` 退出码**：`probe`（探测全失败）= **1**、`probe --help` = 0、`probe` 缺 `--yes` = **2**、`setup` 缺 tool 参数 = **2**（argparse）、`setup workbuddy --dry-run`（无接入密钥）= **2**、`zcode claim` 中途拒跑 = **1**（§3）。

```
E2 $ mgw setup → rc=2   usage: mgw setup [-h] [--yes] [--dry-run] [--config CONFIG] tool
E2 $ mgw probe → rc=2   ✗ 非交互环境需显式 --yes
```

与 `cli.py:62` epilog 文档一致（0/1/2/3 四档，S-8 交付的口径未被本轮改动破坏）。

---

## ③ 阻塞项

**0。** 本轮没有发现"用户会拿到错误事实"或"功能停摆而界面说没事"级别的新缺陷：S-28/S-31/S-29/S-26追加/E-1/E-3 六项在独立复现下均成立，701 条判据无新增红。

---

## ④ 非阻塞登记

| # | 现象（证据） | 影响面 | 我的处置建议与理由 |
|---|---|---|---|
| N-1 | `wall_now` 是**只有测试在用**的生产函数参数：`resources.py:195`；调用点 `:564` 不传，测试传 `0.0`/伪 epoch（F3 清单）；一旦有人传 manager 钟 → `A6 …至 11:33`（S-28 原样复活）且 701 条判据全绿 | 复发风险，非当下缺陷 | **建议下轮删掉该参数**，跨午夜判据改 `monkeypatch.setattr(time, "time", …)`（我本轮就是这么测的，可行且测的是生产分支）。留着它等于把上一轮假绿的机制留在原地。本轮不动生产代码（验收角色） |
| N-2 | `_ms_or_zero` 的合理性上限失效方向是 **fail-open**：`D3 now=0/单调钟 → active=False`，真实 30min 熔断被"视为无熔断"并只在日志留 WARNING；可达路径 = 时钟回拨 >24h | 罕见但方向错：熔断存在的全部意义是"别再打上游" | 建议改**fail-closed**：超界时不归 0，而是 `until_ms = now + COOLDOWN_MS`（保守续期）或拒载并让 `active()` 回 True；至少把 WARNING 升成界面可见。本轮仅登记——需产品口径裁决（与 S-22 同一条取向） |
| N-3 | 锁目录**中途被整个删掉** → `mkdir(parents=True)` 当场重建、`usable() True`，本轮 3 个账号照跑、CLI `rc=0`「全部正常」（rmdir 场景原始输出）。别的进程的锁文件随目录消失 → 双领窗口 | 需要外部删除者；产品内无删除者（F1 实测清理不碰锁目录） | 与账本 G1（锁退路脑裂）同族，改动面 > 本轮边界。建议：`run_once` 开局记下 `lock_dir` 的 `st_ino/st_dev`，中途变化即视为互斥被摧毁 → 走已建立的"未发起"分级文案。登记不催 |
| N-4 | `cli_probe.py:51` 判"有没有端点"仍用**原串** `r.base_url`；空格端点参与探测，最终以「探测失败，保留硬编码 fallback」rc=1 收场（F2） | 纯 CLI 腿的归因文案，不发真实上游、不崩栈 | 一行改成 `if r.enabled and normalize_base_url(r.base_url)` 并给"未配置端点"专属文案（与 `main.py:235` 同一把尺）。属 S-26「第四处归一化」清单的漏项，非本轮修复自引入（是相邻未改点） |
| N-5 | `usable()` 每次探测都写/删 `lock_dir/.write-probe.lock`；拒跑轮里每个失败账号都会触发一次。进程被 kill 在两步之间 → 陈旧 `.write-probe.lock` 永不清理 | 单文件、覆盖写、无 glob 消费者（F1 证明保留清理不碰它） | 可接受。若要洁癖：给 `.write-probe` 加 `finally` 之外的超龄回收。不建议本轮动 |
| N-6 | A4/A5：`status=active/disabled` 的行 payload 仍带 `cooldown_remaining_ms=1799994`，而 `last_error` 不配钟点。UI 三出口因 `status` 门控而一致（dashboard.js:103/129/133），但 API 直读方会看到"判死 + 还有 30min 冷却" | 仅第三方消费者观感 | 判**可接受**：字段语义是"该资源某条映射的剩余冷却"，非"本资源恢复时刻"。若要更清楚，可在 overview 增加 `cooldown_scope` 说明字段——超出本轮范围，登记 |

另记一条**观察**（非缺陷）：软链场景里显式传入的 `AccountLocks(LOCK)` 打印软链路径、`ops_lock_dir()` 默认实例打印解析后的真实路径（`/private/tmp/…/ro-target`）。生产统一走默认实例，口径一致。

---

## ⑤ 试过但打破不了的清单

1. **把 S-28 打回来**：不改源码、只用生产默认单调钟跑真 `create_app` → 钟点恒等于 `time.time()+剩余`；反向假钟点（`11:33`）从未出现。
2. **让两列打架**：两条映射 60s/1800s + 反转 `C`（最严重条目给短冷却）→ 钟点仍跟 `remaining_ms`，60s 的钟点从未出现在文案里。
3. **跨午夜/进位 off-by-one**：`23:30+30min → 至 23:59`、`23:50+30min → 至 明日 00:19`；`1799999ms → 16:27`、`1829998ms → 16:28`。均无 off-by-one。
4. **S-29 逃逸**：chmod 与只读软链两形态都稳定落 `failed`（不发起、`skipped=[]`、抬头分级、`rc=1`）；`release()` 的 `PermissionError` 不上抛、定时器多 tick 存活。
5. **恢复后仍需重启**（我预期的 15 分钟孤儿锁停摆）：**打破失败**——`_try_create` 有 `pid == os.getpid()` 自回收分支，恢复可写后下一个 tick 就 `success=3`，`plan_lock.try_acquire() = True`。
6. **合理性上限 off-by-one / 坏值崩栈**：`now+23h59m`/`now+24h` 保留、`+1ms` 归 0 并 WARNING；负数、`0`、`None`、字符串、`1e18` 全部不抛异常、`left_ms` 不为负、`reason()` 不挂过去钟点。
7. **双钟点**（L-1 × `enter()` 立刻 `reason()`）：`，至` 计数恒为 1（活跃）/0（过点、恰过点、空原因、`until_ms=0`）。
8. **判空用原串的 admin 侧**：`admin.py:292` 已 `strip()`，空格草稿被 `:298` 挡住，构造不出"空格端点建适配器"。
9. **保留清理误删锁文件**：过期 3 类 jsonl 被删的同时 `.write-probe.lock`/`acct-x.lock`/嵌在 usage 里的 `locks-nested/` 全部存活。
10. **`mgw setup` 越权写用户目录**：只跑 `--dry-run`；输出显示在落盘前即因「✗ 未配置任何启用的接入密钥」以 rc=2 退出。目标目录本身**未验证**（遵守 `~/.workbuddy*` 不碰约束），故本条只到"未观察到写入"，不宣称"确认没写"。
11. **机械门回归**：`701 passed`，与第八轮宣称数持平，无我本轮触碰导致的红。
