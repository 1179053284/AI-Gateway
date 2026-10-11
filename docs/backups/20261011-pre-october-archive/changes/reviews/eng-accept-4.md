# 工程验收 · 第四轮（eng-accept-4）

验收人：后端工程角色（三角色验收组）｜日期：2026-09-27/28 跨午夜实测
被验对象：工作树 HEAD=`5158cbc` + 未提交改动（round-4 账本 `docs/changes/e2e-records/E2E-20260927-round4-fixes.md`）
方法：**全部结论来自本会话实测**（pytest / node 门 / 变异注入 / 直接跑生产函数）。未改动仓库任何源码：变异一律打在 `/tmp/mgw-mut` 的**字节级副本**上（12 个被变异文件 md5 与工作树一致，实测见下）。

---

## 1. 一句话结论

**有条件通过**：round-4 的 9 项修复本身**逐条可红可复跑**（16 个变异全部按账本宣称的条数变红，无一空转），但 IX-2 熔断这一项在"资源冷却时长 vs 熔断剩余时长"上**新引入 1 条严重缺陷**（一次额度 tick 把 30 分钟观察期改短成 60 秒），且接线护栏对**本轮自己新增符号所在的 `main.py` 完全不覆盖**。

基线（本会话实测）：
```
$ .venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest-eng -p no:warnings
633 passed in 86.14s                        ← 与账本 633 一致
$ .venv/bin/python -m pytest tests/unit/test_v2_quota_reservation.py tests/unit/test_v2_claim_wiring.py tests/unit/test_v2_circuit.py -q --basetemp=/tmp/mgw-pytest-eng -p no:warnings
60 passed in 0.09s
$ node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json            → 实测 46 项，失败 0 项
$ node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json --mutation → 可红 37/37；每条断言都有对应变异
$ .venv/bin/python -m pytest tests/integration/test_int_v2_frontend_gate.py -q    → 2 passed
```

---

## 2. 九项判定表

| # | 项 | 判定 | 我实际跑了什么 / 看到什么 |
|---|---|---|---|
| 1 | 额度模型 = 上游快照唯一权威（`resources.py:32/291/303/318/326`） | **通过** | 读码：`QuotaPool.__slots__ = ("remaining","reserved")`（:54），`set_quota` 无大小比较（:297-301），`settle_quota` 只 `reserved-1`（:324）→ 全包无第三个"本地消耗"维度。**反证变异**：M15 把第三轮的"只准变小"守卫插回 `set_quota` → 3 红（`test_snapshot_is_the_single_authority`/`test_window_reset_is_accepted`/`test_exhaustion_bench_lasts_one_refresh_cycle_and_self_heals`）；M16 把"结算侧自扣 remaining"插回 → 4 红（含集成 `test_exhausted_quota_does_not_take_more_requests`）→ 两个反模式**一旦复活必红**。1:1 对称另有签名级护栏 `test_reserve_settle_release_are_symmetric:220-235`（实测零泄漏）。残留见 轻 L-2 |
| 2 | `rebuild()` 接线（`resources.py:198`） | **通过** | M1（副本上删 `quota=self._pool_for(ref.resource)`）→ **6 条红**，含账本点名的 3 条 rebuild 判据，断言行分别是 `test_v2_quota_reservation.py:393`（`assert a.quota is b.quota`）、`:412`（`(st.quota.remaining, st.quota.reserved) == (3, 0)` 得 `(None,0)`）、`:430`（`KeyError: 'res-z'`）。另 3 条附带红：`:472/:485/:512`。→ 账本"只此一行承重 + 3 条真红证"成立（实测比宣称更多）。复用分支删除是否"不可达"无法历史复跑，但当前不变量由上述 3 条钉住 |
| 3 | 单一 `CaptchaUnavailable` + 4 条走真求解器（`captcha.py:88`） | **通过** | 全包 `class CaptchaUnavailable` 仅 `claim.py:68` 一处（grep 实测）。M6（`captcha.py` 恢复同名类）→ **3 红**（比宣称的 2 多 1）；M7（`_build_client` 不注入 `captcha_solver`）→ **2 红**，与账本一致。假上游与被换者**同形**：生产 `ZCodeClaimClient._http(self, timeout)`（`claim.py:172`）↔ 桩 `_http(self, timeout)` 返回带 `get/post` 的异步上下文管理器，`_Resp` 提供 `json()/status_code`（生产 `claim.py:187-190` 正好只用这两个）→ 无签名漂移。4 条新用例均**不手搓异常**：文案来自 `CaptchaSolver.__call__` 的真 raise（`captcha.py:156`），且 `test_batch_executor_does_not_retry_a_captcha_failure:335-337` 用 `previews==1 / slept==[]` 做数量判别（M6 下实测变 3 次，即原缺陷） |
| 4 | T9b（`local_admin.py:51/61`、`cli_setup.py:98-108`） | **通过（有保留）** | M11（撤 Bearer 头）→ 1 红；M12（HTTPError 吞成 not-running）→ 2 红；M14（把 `/v1/models` 加进鉴权豁免，拆前提）→ 2 红 —— 账本三条红证全部复跑成立。**直接探因**（自建 4 个假 HTTP 端点）：401→`unauthorized`、非 JSON→`bad-json`、无监听→`not-running` 均正确；但仍有 3 处未堵（见 轻 L-1：`http-<code>` 打印裸码、合法 JSON 数组给出 `reason=ok`+`data=None` 使 CLI 打印自相矛盾句、服务端半路断连归入"未运行"）。PRD Q28-⑤ 要求的**超时**态零测试覆盖 |
| 5 | IX-2 熔断（`quota.py:335/407/511`、`main.py:83/458`、`cli_zcode.py:231/236/269`） | **不通过** | 红证全部复跑：M8（去"至 HH:MM"）→ 4 红；M9（startup 不调 `sync_circuit`）→ 1 红；M10（熔断开「全部正常」/退出码 0）→ 1 红；M13（对齐时长写死 1800s）→ 1 红。**但攻击面失守 3 处**：① 严重 **S-1**（额度 tick 把 30min 冷却改短成 60s，实测 E1）；② 中 **M-2**（删除 `circuit.json` 对运行中进程无效，而 CLI 正把这条路指给用户，实测 E2）；③ 中 **M-3**（运行期 `ResourceState.last_error` **不带**恢复时刻，且 `mgw zcode claim` 汇总行仍谎报「无资格」，实测 E4/E5）；④ `sync_circuit` 会错 bench 非 ZCode 资源（实测 E6，账号备注同名即触发） |
| 6 | P3-2 `tool_call`（`matcher.py:43/270`、`admin.py:606`） | **通过** | M2（加载器不读）→ 2 红；M3（PUT 不读回）→ 1 红。**单向字段全量体检**：`EnumEntry.to_dict` 导出 17 键 = `load_enum_pool` 读的 17 键 = `put_enums` 读的 17 键（逐行比对 `matcher.py:51-64` / `:251-271` / `admin.py:591-607`），并用 ASGI 真端点做了 **17 键全量往返**：`PUT 一条自定义条目（含 tool_call:false / params_default / effort_levels / hours …）→ GET 回来逐字节相等`（实测输出 `17 键全量往返一致？ True`）。不变量 `__post_init__:48-49` 对两条入口同受约束（`test_v2_capabilities` 的 images 族用例 + 归一用例在 M2/M3 之外独立成立）。残留：空 `entries` 的 `source` 谎报（轻 L-3） |
| 7 | eng-⑤ 退路锁目录（`ops/runner.py:86-98`） | **通过** | M4（改回 `tempfile.gettempdir()`）→ 恰 1 红（`test_fallback_lock_dir_is_independent_of_tmpdir`）。该判据**不空**：断言了两个 `TMPDIR` 同目录 + **字面** `/tmp/mgw-ops-locks-<uid>` + 目录实际可写（`tests/unit/test_v2_ops.py` 实测读原文）。协议其余静默路径复查：① 两目录都不可写 → `return False` 不放行（`_acquire_file:213-215`，另有 `test_v2_ops.py:907` 覆盖）；② TOCTOU 宽限期 2s；③ `(锁目录, 账号)` 键（:128-129）；④ pid 复用 → 令牌双条件 + 15min 超龄（:225、:57）；⑤ 同进程多实例 → 模块级 `_HELD_BY_US` 先登记后落盘。未发现新的可达双领路径。两点登记为轻（L-4 相对路径陷阱 / L-5 单侧退路时的脑裂窗口，均需异构前提，本地单用户不成立） |
| 8 | §17 另一半：额度耗尽必 bench + 原因串（`quota.py:290-292`） | **通过（其自身判据）** | M5（撤那次 `apply_to_resource`）→ 2 红，与账本一致；正向对照两条（有余量不 bench / 快照未知不 bench）在 M5 下**保持绿**，说明它们是能区分的判据而非陪跑。时长确实 = 一个刷新周期（`_quota_refresh_seconds:300-306`，实测 `left <= 60+1`）。反复 tick 不会把资源永久锁死（充值后下一 tick 不再 bench，冷却自然到期）。**但这段新代码是 S-1 与 M-1 的直接引信**（见下）：它与熔断共用 `bench()` 这个"覆盖式"写入口 |
| 9 | 接线护栏覆盖类方法（`test_v2_wiring_guard.py::_public_symbols:55`） | **不通过** | 已核实删除：`local_admin.admin_get` / `ResourceManager.quota_view` / `CooldownManager.clear` 在包内 **0 引用点**（grep 仅剩文档叙述）。护栏**灵敏度是真的**：副本上给 `ops/runner.py` 加一个无人调用的公开函数 → 立刻红。**但两处结构性盲区实测复现**：① `_population()` 以**裸名字**为键（`setdefault`，:145）→ 我给 `AccountLocks` 注入一个死方法 `claim`（与 `zcode_claim.claim` 同名）→ 护栏 **4 passed**（死而未报）；实测同名碰撞 7 组：`Scheduler / aclose / active / claim / left_ms / release / try_acquire`，其中 `Scheduler` 首个定义者是 `core/scheduler.py` → **`ops/runner.py::Scheduler` 从未被检查过**。② `V2_MODULES` 不含 **`main.py`**（本轮 `sync_circuit` 就住在这）、`enums/matcher.py`（P3-2 落点）、`api/auth.py`、`config/*`、`core/errors.py`、`adapters/openai_out.py`、`stats/*` 等 **26 个模块** → 我给 `main.py` 加死函数 → 护栏 **4 passed**。③ 护栏因此漏报的真实死符号（本会话 grep 实证）：`core/errors.wrap_httpx_error`（全包 0 引用）、`adapters/openai_out.list_models`（0 引用）、`config/loader.save_config`（**只被 tests 引用**）。→ "扩展后只剩 1 个新死符号"这句话**不成立** |

---

## 3. 新缺陷分级清单（含复现命令与实测输出）

### 🔴 严重

**S-1｜一次额度 tick 把 30 分钟熔断冷却改短成一个刷新周期（60s）→ §17 观察期被穿透；且"重启即穿透"是默认路径**

`bench()` 是**覆盖式**写入（`resources.py:268-271` `cooldown_until = now + seconds`），而 round-4 新增的两条回写共用它：熔断走 `bench_all_zcode(seconds=left_ms/1000)`（30min），额度耗尽走 `apply_to_resource(seconds=_quota_refresh_seconds(runtime))`（60s，`quota.py:290-292`）。只要熔断期间发生一次 `remaining==0` 的额度回写，资源自己的冷却就被改短；下一个 tick 若快照回到 `>0`（充值/窗口翻页）就**不再续 bench** → 资源在熔断还剩约 29 分钟时回到生效集，模型转发重新打向仍在风控观察期的账号——正是 §19 M4-4 要消灭的那件事。

更糟的是**启动顺序**把触发成本降到零：`main.py:458 sync_circuit(runtime)`（bench 30min）→ `main.py:460 _maybe_start_ops()` → `main.py:144 refresh_quotas(runtime)`（同一次 startup 内即可把它改短成 60s）。且 `CooldownManager` 的类文档明写着熔断期间"**停止领取与额度回写**"（`quota.py:359`），但 `refresh_runtime_quotas`（:241-262）与 `query_balance`（`ops/builtin/query_balance.py:45`）**都没有熔断闸门** —— 文档承诺与实现不一致。

```
$ .venv/bin/python - <<'PY'      # （完整脚本见正文证据 E1）
  bench_all_zcode = 1
  熔断后资源冷却 = 30.0 分钟（熔断剩余 30 分钟）
  一次额度 tick 后资源冷却 = 60 秒（熔断仍剩 30 分钟）
```
建议修法（择一，都要带判据）：① `bench()` 改为 `cooldown_until = max(现有, now+seconds)`；② 或额度耗尽回写时取 `max(_quota_refresh_seconds, 熔断剩余)`；③ 并在 `refresh_runtime_quotas`/`query_balance` 加 `_circuit_gate` 同判据的短路（与文档一致）。

### 🟠 中

**M-1｜§17 回写覆盖 `invalid`/`disabled` 状态 → 失效凭据被说成"暂时冷却"，并让模型重新被声明为可服务（违 PRD Q28-②）**
`apply_to_resource`（`quota.py:477-483`）对匹配 rid 的**全部** state 无条件 `bench()`；`servable_models` 只把 `disabled/invalid` 判为不可服务（`resources.py:152`），`cooldown` 算可服务 → 回写后该模型重新出现在 `/v1/models` 与 `mgw setup` 的清单里；冷却到期后 `pick_and_acquire` 又把它放回生效集。
```
E3 实测：
  disable 后 servable = []
  §17 回写后 status = cooldown servable = ['m']  快照列 status/available = ('cooldown', False)
  冷却到期后 pick_and_acquire = R/vm status = active
```
既有缺陷（`apply_to_resource` 早于本轮），但本轮新增的两条调用点（启动 sync + 每 tick 额度耗尽）让它第一次**无上游参与也会发生**。修法：`apply_to_resource` 跳过 `status in ("invalid","disabled")`，或按 S-1 的 max 语义并保留状态严重度。

**M-2｜删除 `circuit.json` 不影响运行中进程，而 CLI 正把这条路指成唯一手动出口**
`CooldownManager._load()` 在 `stat()` 抛 `OSError` 时**直接 return**（`quota.py:377-388`），内存里的 `_cd` 原样保留 → 网关进程的 `_circuit_gate` 继续拒绝领取。round-4 按 D3 删了 `clear()`，把"手改本地文件"确立为唯一手动出口（`cli_zcode.py:237` 原文：「或删除该文件以提前解除」）。
```
E2 实测：
  enter 后 active = True
  删除文件后（exists=False）active 仍为 = True  reason = ZCode 风控熔断（30min，全局），至 00:36
```
修法：`_load()` 里 `FileNotFoundError` 应把状态清为 `Cooldown()`（并把 `_loaded_mtime=None`）。否则要么恢复一个受支持的解除出口，要么把 CLI 那句话改准。

**M-3｜熔断"可见性"只做了一半：运行期界面那一列没有恢复时刻，CLI 汇总行仍谎报「无资格」**
① `zcode_claim._handle_risk_control:117` 用**未加工**的 `GLOBAL_BENCH_REASON` 去 bench，`_hhmm` 只进 `enter()` 里的 `circuit.reason()` → 只有**重启后** `sync_circuit` 才把「至 HH:MM」写进 `last_error`。实测（E4）：
```
  熔断 reason（落盘/CLI 打印用）: ZCode 风控熔断（30min，全局），至 00:27
  ResourceState.last_error（总览「最近错误」列）: ZCode 风控熔断（30min，全局）
  → 界面那一列带恢复时刻吗？ False
```
§17 的字面要求恰好针对 `last_error` 这一列（"总览资源健康卡「最近错误」列直接可见原因"）→ 5a 的收益在**不重启时拿不到**。② 熔断中的 `mgw zcode claim` 输出（E5 实测）：
```
⚠ ZCode 风控熔断（30min，全局），至 00:33 —— 本轮未对上游发起任何领取
    状态文件：…/circuit.json（等待自动到期，或删除该文件以提前解除）
– 跳过 2 个（无资格 2）
----- 退出码 = 3 -----
```
`cli_zcode.py:252` 把熔断跳过说成「无资格」——而 `test_v2_cli_zcode.py:206` 的 docstring 恰恰把"上一版打印 `– 跳过 2 个（无资格 2）`"列为原缺陷。修法：`bench_all_zcode(reason=get_circuit().reason())`（一行）+ 给熔断跳过单独一类计数。

**M-4｜`sync_circuit` 会错 bench 非 ZCode 资源（账号备注同名即触发）**
`resource_ids_of_account`（`quota.py:526-542`）只按 `r.account == 账号名` 匹配，不看厂商/产品；而 Q20-③ 把「账号」定为**必填自由备注** → 同一个人邮箱同时给 ZCode 和别家配资源是常态。实测（E6）：
```
  ('res-z', 'vm-res-z')      status=cooldown last_error='ZCode 风控熔断（30min，全局），至 00:22'
  ('res-openai', 'vm-res-openai') status=cooldown last_error='ZCode 风控熔断（30min，全局），至 00:22'
  sync_circuit 处理了 2 个资源
```
现有 `test_bench_endpoint_leaves_non_zcode_resources_alone`（`tests/integration/test_int_v2_zcode_admin.py:271-282`）只验了"备注不同/为空"的情形，**同名情形零覆盖**（名字与意图相符、机制不符）。修法：`resource_ids_of_account` 增加产品/厂商判据（`Resource.product`/`preset`），并把上面这条用例改成同名资源。

### 🟡 轻

**L-1｜`admin_get_detail` 仍有 3 处折叠/说谎**（实测 E7）：① `http-<code>` 不在 `REASONS` → `cli_setup.py:108` 原样打印 `http-404` 这种黑话；② 合法 JSON 但非对象 → `(None, "ok")` → CLI 打印「本地配置 · 原因：**运行中网关的真实状态**」自相矛盾；③ 服务端 accept 后断连（进程活着但响应坏了）→ 归 `not-running`。另 `admin_get_detail` 在配置读不出时也返回 `not-running`（`local_admin.py:77`）。
**L-2｜`reserved` 潜在泄漏（API 陷阱，生产暂不可达）**：预留后 `set_quota(rid, None)` 再结算 → 预留不归还（`settle_quota:321` 早退）。实测 E8：`settle 后 reserved=1 → 余量回到 1 时 has_room=False → 该资源永不放行`。当前生产唯一写点 `quota.py:288` 不传 None 故不可达；但 `test_set_quota_none_clears_management`（:64）正在教用户走这条路。建议：结算/释放无条件 `reserved = max(0, reserved-1)`。
**L-3｜枚举池"清空"是静默无效 + `source` 谎报**：`PUT {"entries": []}` 返回 `已保存并生效`，文件写成 `entries: []`，而 `load_enum_pool`（`matcher.py:272-274`）见空即回落内置目录 → `GET` 同时报 `source=file` 和 15 条内置条目（实测 E9）。建议 `PUT` 拒绝空清单，或 `source` 按实际生效池给。
**L-4｜`write_report` 的 `usage_dir=None` 兜底是相对路径** `Path("data")/"usage"`（`ops/runner.py:428`），与 `paths.py` 立的"必须与 cwd 无关"纪律冲突（本轮 eng-⑤ 同族）。当前两个生产调用点都显式传参 → 属陷阱而非故障。
**L-5｜单侧退路的锁脑裂窗口**：若两个进程一方能写主目录、另一方只能退 `/tmp`，两者各得一把锁 → 互斥失效（`_acquire_file:198-212` 只在**自己**失败时退）。需要异构前提，本地单用户不成立；如要堵死可"退路锁与主锁同时取"。另 `/tmp/mgw-ops-locks-<uid>` 目录名可预测、`mkdir` 未限定 0700（`runner.py:202`），他用户可抢先建目录 → 建议 `mkdir(mode=0o700)` + 属主校验。
**L-6｜文案与 §17 字面有出入**：实现为 `ZCode 风控熔断（30min，全局），至 HH:MM`（`zcode_claim.py:65` + `quota.py:415`），§17 字面是 `ZCode 风控熔断（30min，至 HH:MM）`；两行要求（含"全局"、含恢复时刻）都满足了，但既算"有意背离"就该像 D1 那样在 PRD 记一句。另 `至 HH:MM` 不带日期，23:50 熔断显示"至 00:20"（实测 00:32 / 00:36 两次都落在跨午夜分支）。

**判据缺口（不另计等级）**：PRD Q28-⑤ 明写"未运行 / **超时** / 401 三态可分辨"——`timeout` 分支（`local_admin.py:85-86`）**零测试**（`REASONS` 表测只查名字在不在）。§19 M4-4 的"模型转发路径自动绕开"在熔断语境下只有 overview `available=False` 的断言（`test_int_v2_circuit_boot.py:58`），没有"熔断中真发一次 `/v1/chat/completions` 不打向该资源"的端到端请求级判据（额度侧有 `test_int_v2_quota_reserve.py`，熔断侧无）。

---

## 4. 空过 / 弱断言清单（点名到行）

| # | 位置 | 问题 | 判定 |
|---|---|---|---|
| 1 | `tests/unit/test_v2_circuit.py:174` `assert "30" in zq.get_circuit().reason()` | `"30"` 来自**测试自己**传给 `enter()` 的串（:140/:172 的 `…（30min，全局）`）；`enter()` 只要不吞输入就恒真 | **空过**：M8 撤 5a 后该用例仍靠同函数其它断言变红，但这一条本身不可能红 |
| 2 | `tests/unit/test_v2_circuit.py:172` `assert benched == [zcode_claim.GLOBAL_BENCH_REASON]` | 把"回写原因**不带**恢复时刻"钉成标准（见 M-3） | **反向判据**：M-3 修好后必红，须一并改 |
| 3 | `tests/unit/test_v2_claim_wiring.py:134-136`（`_Recorder` 桩 + `"风控熔断" in reason`） | 桩返回 1 并记录入参，不证明资源真被 bench；资源级落点另有 `_RealMgrRuntime` 用例覆盖 | **弱**（可作接线判据保留，但 M-3 的文案改进会让它变红，需同步） |
| 4 | `tests/unit/test_v2_quota_reservation.py:342-346` `test_view_exposes_quota_for_diagnostics` | 写入 `set_quota(s,7)` 后读回同两个字段，无任何生产路径参与；用例名里的 `quota_view` 本轮已删 | **空过 + 残留命名**，建议删除 |
| 5 | `tests/integration/test_int_v2_setup_live.py:141-143` `test_reasons_table_covers_every_documented_reason` | docstring 称"REASONS 与 `admin_get_detail` 的返回值同源"，实际只比一张手挑字面集合；漏 `forbidden`，且结构上不可能覆盖 `http-<code>`；新增返回码不会让它红 | **弱**：应改为从函数枚举可能返回值（或 AST/正则提取 `return None, "xxx"`）再比对 |
| 6 | `scripts/verify_v2_frontend.mjs:313-319` 抛错自证分支 `red = mut.kills` | 变异导致 `runChecks` 抛错时，直接把"应红的断言"当作已红 | **1/37 命中**（实测 `[抛错 TypeError]` 只出现在"非数组 warnings 不做类型兜底"一条），其余 36 条为真证据 |
| 7 | `tests/unit/test_v2_wiring_guard.py:156` `assert len(pop) >= 60` | 下限宽松（实测 182），且 `:174-180` 的覆盖面自检只点名 8 个模块 | 方向对但**挡不住扫描器自身漏文件**（见判定 9 的 ①②） |
| 8 | `tests/unit/test_v2_ops.py::test_fallback_lock_dir_is_independent_of_tmpdir` | — | **非空过**（字面路径 + 可写探针），作为本轮判据质量的正例 |
| 9 | `tests/integration/test_int_v2_setup_live.py:84`（鉴权前置对照）、`test_int_v2_circuit_boot.py:64`（无落盘熔断不得凭空 bench）、`test_v2_quota_reservation.py:476`（有余量不 bench） | — | **正向对照真实有效**：M14/M5 分别证明它们能区分前提消失与修复缺失 |

---

## 5. 要求主 agent 执行的"撤修复红证"清单（第五轮复跑用；含我对副本的实测条数）

在**工作树**上逐条施加（或按本报告方式在 `/tmp` 副本上施加），判据 = "括号内用例必红，且红因是指定断言行"。我已在字节级副本上跑过，实测条数写在最右列。

| 撤掉的修复 | 锚点（file:line） | 应变红的判据 | 实测 |
|---|---|---|---|
| `rebuild()` 的额度接线 | `core/resources.py:198` | `test_v2_quota_reservation.py:393 / :412 / :430`（+472/485/512 附带） | **6 红**（账本称 3，实测更多） |
| `set_quota` 复活"只准变小"守卫 | `core/resources.py:297-301` | `:267` `test_snapshot_is_the_single_authority`、`test_window_reset_is_accepted:277` | **3 红** |
| `settle_quota` 复活本地消耗账 | `core/resources.py:318-324` | `:187`、`:263`、`test_settle_consumes_reserved_quota:101`、集成 `test_exhausted_quota_does_not_take_more_requests` | **4 红** |
| `captcha.py` 再定义同名异常类 | `upstream/zcode/captcha.py:88` | `test_v2_claim_wiring.py:296 / :310 / :320`（且 `previews` 变 3） | **3 红**（账本称 2） |
| `_build_client` 不注入求解器 | `ops/builtin/zcode_claim.py:150` | `test_client_is_always_assembled_with_a_solver:292`、`test_solver_reason_reaches_the_user_verbatim` | **2 红** |
| 加载器不读 `tool_call` | `enums/matcher.py:270` | `test_yaml_can_turn_tool_call_off_per_model`、`test_enums_round_trip_preserves_tool_call` | **2 红** |
| `PUT /admin/api/enums` 不读回 | `api/admin.py:606` | `test_enums_round_trip_preserves_tool_call` | **1 红** |
| 退路目录改回 `gettempdir()` | `ops/runner.py:98` | `test_fallback_lock_dir_is_independent_of_tmpdir` | **1 红** |
| 额度耗尽不写状态 | `upstream/zcode/quota.py:290-292` | `test_exhausted_snapshot_benches_with_the_documented_reason`、`test_exhaustion_bench_lasts_one_refresh_cycle_and_self_heals`（正向对照 :476/:488 必须保持绿） | **2 红** |
| 熔断文案去"至 HH:MM" | `upstream/zcode/quota.py:415` | unit×2 + CLI×1 + 启动集成×1 | **4 红** |
| startup 不调 `sync_circuit` | `main.py:458` | `test_startup_rebenches_resources_while_breaker_is_active` | **1 红** |
| 对齐时长写死 30min | `upstream/zcode/quota.py:522-523` | `test_sync_circuit_cooldown_matches_remaining_time` | **1 红** |
| 熔断中打印"全部正常"/退出码 0 | `cli_zcode.py:266-269` | `test_claim_under_global_breaker_exits_3` | **1 红** |
| `mgw setup` 不发 Bearer | `cli_setup.py:100` | `test_setup_reads_live_models_through_auth` | **1 红** |
| HTTPError 吞成 not-running | `core/local_admin.py:82-84` | `test_models_endpoint_rejects_anonymous`、`test_setup_on_wrong_token_says_401_not_not_running` | **2 红** |
| `/v1/models` 进鉴权豁免（拆前提） | `api/auth.py:15` | 同上 2 条 | **2 红** |
| 前端徽章插回 `available===false` | `web/static/js/pages/dashboard.js:110` | `pytest tests/integration/test_int_v2_frontend_gate.py` → C2~C7 红 | 门侧 46/37 全绿（我复跑），源码回归由门捕获 |

**并且**：修 S-1 / M-1 / M-2 / M-3 / M-4 时必须**各带一条能红的判据**，建议直接写成
- S-1：`熔断生效期间一次 `apply_snapshot_to_runtime(remaining=0)` 后，断言 `st.cooldown_until - now > 熔断剩余 - 1s``（今天这条必红 → 正是 S-1）；
- M-1：`先 invalidate/disable，再 §17 回写，断言 status 仍为 invalid/disabled 且 servable_models 为空`；
- M-2：`CooldownManager.enter → 删除文件 → 同实例 active() 必须转 False`；
- M-3：`真跑 3012 腿后断言 ResourceState.last_error 含"至 HH:MM"`（今天必红）；`mgw zcode claim` 在熔断中**不得**出现"无资格"字样（今天必红）；
- M-4：`非 ZCode preset + 同 account 备注` 的资源在 `sync_circuit` 后仍 `active`（今天必红）。

---

## 6. 未验证清单

1. **一切真实上游交互**：ZCode 3012 实际风控、客户端日志 payload 的真实形状、Playwright 验证码求解（§16.5）、`curl_cffi` 的 T5a/T5b（WAF 放行、async SSE 流式）—— 按 §19 标为手工，本会话未联网、未读 `~/.zcode`。
2. **WorkBuddy / WorkBuddy AI 工具端真读 `models.json`**（§19 M3-5 手工项，受登录态阻塞）。
3. **真·双进程双领**：跨进程互斥我只复跑了测试（`test_v2_ops.py` / `test_int_v2_ops_isolation.py`），未亲自起两个进程对打。
4. **`rebuild()` 复用分支被删代码的"不可达"历史论证**：只能确认当前不变量由 :198 + 3 条判据成立，无法复跑"撤掉后 625 全绿"这一步（那行已不在树上）。
5. **界面渲染事实**（`statusBadge` 四态、熔断行在界面上的呈现）：属 IX 角色域；我只验到 `/admin/api/overview` 的 `last_error`/`available` 字段级事实。
6. `scripts/ui_verify_v2_visible.py`：按指示**未运行**（会写共享 `/tmp` 路径）。
7. **护栏"新增公开符号必被拦"的前向承诺**（账本 §四 第 5 条）：本会话实测**不成立**（判定 9 的 ①②：同名方法与未列入模块的死符号都不报），故第 5 节要求以"必红判据"而非护栏作为兜底。

---

### 附：本会话证据的复现方式（只读，不改仓库）
```
# 副本（与工作树 md5 逐文件一致）+ 变异驱动器
tar --exclude=.venv --exclude=.git --exclude=data --exclude=__pycache__ --exclude=.workbuddy-ai -C /Users/w/Desktop/Model-Gateway -cf - . | (mkdir -p /tmp/mgw-mut && tar -C /tmp/mgw-mut -xf -)
# E1 S-1 / E2 M-2 / E3 M-1：见 §3 代码块；E4-E9（3012 真路径 last_error、CLI 输出、
#   admin_get_detail 四态探因、reserved 泄漏、枚举池空 PUT 与 17 键往返）为同批 heredoc 实测，输出已抄录在正文。
```
