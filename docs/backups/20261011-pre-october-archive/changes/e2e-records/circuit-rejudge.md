# 读时重判：删除 `circuit.json` 后立刻放开「熔断按住的那条冷却」

> 需求来源：用户裁决 2026-09-29（选项「读时重判」）。
> 范围：后端四文件 + 新判据文件；**未碰**前端源码、`docs/specs/`、
> `scripts/verify_v2_frontend.mjs`、`tests/integration/test_int_v2_frontend_gate.py`。
> **越界申报见 §0**。全量 pytest 尾行见 §6。

## 0. 越界申报（两处，均在动手前后写在此处）

| 文件 | 为什么必须动 | 动了几处 |
|---|---|---|
| `tests/unit/test_v2_circuit_rejudge.py` | 简报指定的新判据文件 | 新建（21 个用例 / 收集 22 条） |
| `README.md` / `README.zh-CN.md` | **既有判据 `test_v2_readme_claims.py::test_readme_test_counts_are_not_stale` 因我新增 22 条测试而红**（宣称 710、实际 748，容差 ±20）。那条判据的**本体是"文档数字必须贴近真实"**，它的注释写着"改文案的人不需要记得同步，红的是判据" —— 修法只能是同步文档数字，不能改断言、不能 skip。 | 每个文件 2 处数字（徽章 `tests-748%2F748` + 正文 `748 passed`）与日期 `2026-09-29`，零文案改动 |

其余改动全部落在简报允许的四个文件内：
`model_gateway/core/resources.py`、`model_gateway/upstream/zcode/quota.py`、
`model_gateway/api/admin.py`、`model_gateway/main.py`。

## 1. 现象与裁决

- 全局风控熔断落盘 `data/…/circuit.json`，§17 要求它回写到资源运行态。
- 官方唯一手动出口 = 用户删掉 `circuit.json`（CLI 文案明说"删除该文件可立即放开后续领取"），
  机制上 `CooldownManager.active()` 每次判定都回读磁盘，删完立刻为假。
- 缺陷：界面上那一行仍按写死的 `cooldown_until` 冻结（最长 30 分钟），且没有任何反馈。
- 裁决：改成**读时重判** —— 谁读时若熔断已不成立，就把**它当初按住的那些**放回生效集。
  不做跨进程通知、不加 watcher。

## 2. 机制定位（实测复核，含对本简报的纠正）

行号为**改动后**的行号。

| # | 事实 | 位置 | 与简报的出入 |
|---|---|---|---|
| F1 | `ResourceState` 用 `__slots__`，新字段必须同时进 `__slots__` 与 `__init__` | `core/resources.py:101-106` / `:129-135` | 一致 |
| F2 | `_lift_if_expired` 归位动作 + `reconcile_expired`（读时调） | `core/resources.py:596-614` / `:548-570` | 一致 |
| F3 | `snapshot_by_resource` 内部已调 `reconcile_expired()` → 释放点挂这里 | `core/resources.py:640-652` | 一致 |
| F4 | `bench()` 返回"是否取得冷却所有权"、冷却只延长不缩短 | `core/resources.py:426-459` | 一致 |
| F5 | `CooldownManager`（`circuit.json` 读写 + `active()` 每次回读盘）家在 **upstream/zcode/quota.py**；简报里"给 `CooldownManager` 加归位动作"指的是 `core/resources.py` 的 **`ResourceManager`**（`_lift_if_expired` 的家） | `upstream/zcode/quota.py:435-564` | **纠正 1（命名）**：本实现按 `ResourceManager` 落刀 |
| F6 | 熔断回写链路：`bench_all_zcode` / `sync_circuit_to_runtime` → `bench_account` → `apply_to_resource` → `mgr.bench()` | `upstream/zcode/quota.py:816-833` / `:837-866` / `:926-939` / `:773-813` | 一致（简报的 `:796`/`:822` 是改动前行号，函数不变） |
| F7 | 额度耗尽共用同一条链：`apply_snapshot_to_runtime` → `apply_to_resource(QUOTA_EXHAUSTED_REASON)` | `upstream/zcode/quota.py:297-300` | 一致（第 1 号坑成立） |
| F8 | 429/连续失败退避走 `core/scheduler.py` 的 `runtime.resources.bench(state, seconds)`（**不经 quota**） | `core/scheduler.py:419`/`437`/`646`/`694`/`711` | **纠正 2**：成因必须落在 `bench()` 这一层才覆盖得到它；只在 quota.py 埋标记会漏掉整类退避 |
| F9 | 可服务判据 `servable_models` 只把 `disabled`/`invalid` 判为不可服务，**`cooldown` 一直是可服务** | `core/resources.py:227-262`，消费方 `api/openai_compat.py:53`、`main.py:374` | **纠正 3（重要）**：简报说"模型被 `/v1/models` 隐藏"—— 实测**不是**。熔断回写落 `cooldown`，`/v1/models` 从不因此隐藏（BUG-1 定稿口径）。真实效果是**被挡出生效集**（`available()` 要 `status=="active"`）+ 总览那一行冻结。所以"下发可服务模型"这条读路径接重判是**空操作**，本实现不接（钉在 J19），真正接的是**出快照**与**选路**两处 |
| F10 | 运行态**不落盘**：`cooldown_until` 只在内存，`rebuild()` 按 `(rid, vendor_model)` 保留条目、连接身份指纹变了才清零 | `core/resources.py:340-365`（全仓 `cooldown_until` 无第二处写入） | 一致（新字段无序列化兼容问题） |
| F11 | `untrusted`（文件读不动）→ `active()` 返回 **True**（未知按最坏处理） | `upstream/zcode/quota.py:651-657` | 一致，"untrusted 不释放"不需要第二处特判 |
| F12 | 既有测试契约的两条硬约束：`test_v2_claim_wiring.py:99` 以 `fake(runtime, account, *, reason, seconds=None)` 替换 `bench_account`；`test_v2_zcode_quota.py:267`、`test_v2_circuit.py:81` 的假 `mgr.bench(state, seconds)` | 见文件 | **纠正 4**：简报建议"把成因作为参数从调用方带进 `bench_account`/`bench`"。加任何一个关键字参数都会让这些**既有假件 `TypeError`**（既有判据红），而规矩是"不得为了让全绿改既有断言"。成因改为在 `ResourceManager` 一层用**显式作用域**声明（`circuit_hold()`），`bench()`/`bench_account` 签名逐字符不变 |
| F13 | 熔断未成立时的回写**不是**"熔断按住"（`sync_circuit_to_runtime` 里 `active()` 为假就直接返回；CLI 腿经端点回写时文件可能已被删/没落盘成功） | `upstream/zcode/quota.py:837-841`、既有判据 `test_int_v2_zcode_admin.py::test_overview_surfaces_circuit_reason` | **追加结论（简报未提）**：登记只在 `get_circuit().active()` 此刻为真时发生。若一律登记，那条既有 §17 接口判据立刻红（回写完下一次读就被"重判"放开 = 熔断的唯一可见出口重新空转）。R15 是这件事的红证 |
| F14 | 基线 pytest 尾行（改动前，全量）：`726 passed in 169.56s` | — | **纠正 5**：简报说基线 719 passed，本机实测 726 |

## 3. 实现（每处 file:line）

| # | 改动 | 位置 |
|---|---|---|
| I1 | 运行态标记 `circuit_held`（进 `__slots__` + 默认假） | `core/resources.py:106` / `:129-135` |
| I2 | 读时重判的两个注入点：判据槽 `circuit_active` + 成因作用位 `_bench_held_by_circuit` | `core/resources.py:282-287` |
| I3 | `circuit_hold()`：显式声明"这一段之内 `bench()` 取得的冷却 = 熔断按住"（作用域内不得 await） | `core/resources.py:289-306` |
| I4 | `bench()` 不变量三：**成因标记随所有权一起换**（取得所有权时写入，未取得不动） | `core/resources.py:444-459` |
| I5 | `reconcile_expired()` 加第二个释放条件（不另起一处） | `core/resources.py:548-570` |
| I6 | `_circuit_cleared()`：判据缺失 / 熔断仍在 / 判据抛错 → 一律不释放（fail-closed） | `core/resources.py:572-588` |
| I7 | `_lift_for_read()`：两条读取路径共用的归位动作（到期 + 熔断重判） | `core/resources.py:590-594` |
| I8 | `_lift_if_expired()` 归位时清标记 | `core/resources.py:596-614` |
| I9 | `_lift_if_circuit_cleared()`：只放 `circuit_held` 且 `status=="cooldown"`；置 `cooldown_until=0`、清标记；**不动 `last_error`** | `core/resources.py:616-638` |
| I10 | 选路读取点接线（`pick_and_acquire` 改用 `_lift_for_read`） | `core/resources.py:398-405` |
| I11 | 凭据变更清零路径清标记（PRD Q28-⑥⑤） | `core/resources.py:354-363` |
| I12 | `circuit_hold_scope(runtime, *, held=True)`：熔断回写的成因声明，且**只在 `get_circuit().active()` 为真时登记** | `upstream/zcode/quota.py:745-771` |
| I13 | `bench_all_zcode(..., circuit=True)` 包进作用域（cron 同进程腿 + 管理端点 global 腿；签名新增关键字参数带默认值，既有调用点与既有假件不受影响） | `upstream/zcode/quota.py:816-833` |
| I14 | `sync_circuit_to_runtime` 启动对齐包进作用域 | `upstream/zcode/quota.py:858-866` |
| I15 | `apply_to_resource` **不**加成因参数（所有权与成因各一处口径，写进 docstring） | `upstream/zcode/quota.py:785-791` |
| I16 | `/admin/api/zcode/bench`：成因由调用方**显式**带（载荷 `circuit` 字段，缺省=熔断；`false/0/no`=非熔断），响应回 `circuit_held` = 声明 ∩ 熔断真的成立 | `api/admin.py:404-447` |
| I17 | 装配侧注入判据：`Runtime._wire_circuit_rejudge()`（core 不 import upstream；取调用时的单例，不绑死实例） | `main.py:196-201` / `:225-245` |
| I18 | `sync_circuit()` 注释补上"建立只在启动 / 解除每次读重判"的方向不对称 | `main.py:92-100` |

## 4. 判据清单（`tests/unit/test_v2_circuit_rejudge.py`：21 个用例，收集 **22 条**
（J8 按 `invalid`/`disabled` 参数化）；时间一律注入 `manager.clock` 的假钟，**零真 sleep**）

| # | 判据 | 钉住的方向 |
|---|---|---|
| J1 | `test_deleting_the_breaker_file_releases_the_row_on_the_next_snapshot` | 裁决本体：删文件 → 下一次出快照立刻 `active` +「冷却剩余」归零 + `last_error` 留着但**不带钟点** |
| J2 | `test_snapshot_keeps_the_row_cooled_while_the_breaker_still_holds` | 🔴 反向：熔断仍在生效时读快照必须**还是** `cooldown` |
| J3 | `test_unwired_manager_never_rejudges` | 分层：判据未注入（CLI 独立进程 / 未装配单测）→ 行为与改动前逐字节一致 |
| J4 | `test_quota_exhaustion_cooldown_survives_the_breaker_delete` | 🔴 第 1 号坑：额度耗尽的 cooldown 不受删熔断文件影响 |
| J5 | `test_backoff_cooldown_survives_the_breaker_delete` | 🔴 第 1 号坑：429/连续失败退避同理 |
| J6 | `test_a_longer_backoff_after_the_breaker_is_not_released` | 所有权换手：熔断后被更长退避接管 → 不再被熔断的解除放开 |
| J7 | `test_shorter_backoff_does_not_take_the_breaker_ownership` | J6 的正向对照（短退避没取得所有权 → 仍归熔断 → 照样放开） |
| J8 | `test_terminal_states_are_never_reopened_by_the_rejudge[invalid / disabled]` | 🔴 终态：反复读 + 选路都不得回 `active` |
| J9 | `test_terminal_state_reached_while_the_breaker_holds_is_still_terminal` | 组合：判死在先、熔断回写在后 → `bench()` 拒绝覆盖终态 |
| J10 | `test_untrusted_breaker_file_is_never_released` | 🔴 fail-closed：文件读不动（未知档）不释放；删掉坏文件才算解除 |
| J11 | `test_a_predicate_that_raises_fails_closed` | 判据抛错 → 不释放 |
| J12 | `test_selection_releases_the_breaker_held_resource_only_when_the_breaker_is_gone` | 第二处读路径（选路）：两处独立接线各自可被撤回抓红 |
| J13 | `test_other_process_deleting_the_file_is_visible_without_restart` | 🔴 跨进程：另一个进程删文件 → 本进程下一次读就重判（**不测成必须重启**） |
| J14 | `test_a_new_breaker_written_by_another_process_blocks_the_rejudge` | 反向同族：放开后另一个进程重新熔上 → 下一次读继续挡 |
| J15 | `test_a_bench_written_while_the_breaker_is_absent_is_never_registered` | 登记只在熔断真的成立时发生（守住 §17 那个"唯一可见出口"不空转） |
| J16 | `test_startup_alignment_registers_the_persisted_breaker` | 启动对齐（`sync_circuit_to_runtime`）这条写点也登记成因 |
| J17 | `test_no_reset_path_leaves_the_marker_behind` | 交付 3：解除 / 到期归位 / 凭据变更清零三条路径之后标记不得残留 |
| J18 | `test_released_cooling_can_be_held_by_the_breaker_again` | 可逆性：解除不是一次性状态（新一轮风控重新按住） |
| J19 | `test_breaker_cooldown_never_hid_the_model_from_the_listing` | 机制事实（纠正 3）：`servable_models` 不因 `cooldown` 隐藏模型 |
| J20 | `test_running_gateway_rejudges_after_the_user_deletes_the_file` | 端到端：真 `create_app` + `/admin/api/zcode/bench` + `/admin/api/status`（钉 main.py 的接线） |
| J21 | `test_endpoint_can_declare_a_non_breaker_cause` | 端点成因由调用方**显式**声明（`"circuit": false`），不靠 reason 文案猜 |

## 5. 撤修复红证（逐条：撤哪一行 → 红几条，原样输出）

实验方式：脚本对生产文件做**单点字符串替换**（跑完立刻还原；`ls **/*.bak` 为空、
关键字命中数复原已核对），每次跑判据子集
`test_v2_circuit_rejudge.py + test_v2_circuit.py + test_v2_zcode_quota.py +
test_v2_claim_wiring.py + test_v2_servable.py + test_scheduler.py +
test_int_v2_zcode_admin.py`（当前该子集 **173 passed**）。

> 全部 18 处单点撤回**都至少抓红一条**，没有"撤了没人管"的空档。
> 实验脚本是临时的（`scripts/tmp_circuit_rejudge_reverts.py`），跑完已删除；
> 生产文件与 `.bak` 均已核对还原（`grep -c` 关键锚点命中数一致、`find -name "*.bak"` 为空）。

### R1 `bench()` 不登记成因（`core/resources.py:458` 删那一行）→ 红 16
```
FAILED test_v2_circuit_rejudge.py::test_deleting_the_breaker_file_releases_the_row_on_the_next_snapshot
FAILED test_v2_circuit_rejudge.py::test_unwired_manager_never_rejudges
FAILED test_v2_circuit_rejudge.py::test_a_longer_backoff_after_the_breaker_is_not_released
FAILED test_v2_circuit_rejudge.py::test_shorter_backoff_does_not_take_the_breaker_ownership
FAILED test_v2_circuit_rejudge.py::test_terminal_states_are_never_reopened_by_the_rejudge[invalid]
FAILED test_v2_circuit_rejudge.py::test_terminal_states_are_never_reopened_by_the_rejudge[disabled]
FAILED test_v2_circuit_rejudge.py::test_untrusted_breaker_file_is_never_released
FAILED test_v2_circuit_rejudge.py::test_a_predicate_that_raises_fails_closed
FAILED test_v2_circuit_rejudge.py::test_selection_releases_the_breaker_held_resource_only_when_the_breaker_is_gone
FAILED test_v2_circuit_rejudge.py::test_other_process_deleting_the_file_is_visible_without_restart
FAILED test_v2_circuit_rejudge.py::test_a_new_breaker_written_by_another_process_blocks_the_rejudge
FAILED test_v2_circuit_rejudge.py::test_startup_alignment_registers_the_persisted_breaker
FAILED test_v2_circuit_rejudge.py::test_no_reset_path_leaves_the_marker_behind
FAILED test_v2_circuit_rejudge.py::test_released_cooling_can_be_held_by_the_breaker_again
FAILED test_v2_circuit_rejudge.py::test_breaker_cooldown_never_hid_the_model_from_the_listing
FAILED test_v2_circuit_rejudge.py::test_running_gateway_rejudges_after_the_user_deletes_the_file
16 failed, 157 passed in 3.42s
```

### R2 出快照不重判（`reconcile_expired` 退回只调 `_lift_if_expired`）→ 红 10
```
FAILED test_v2_circuit_rejudge.py::test_deleting_the_breaker_file_releases_the_row_on_the_next_snapshot
FAILED test_v2_circuit_rejudge.py::test_shorter_backoff_does_not_take_the_breaker_ownership
FAILED test_v2_circuit_rejudge.py::test_untrusted_breaker_file_is_never_released
FAILED test_v2_circuit_rejudge.py::test_other_process_deleting_the_file_is_visible_without_restart
FAILED test_v2_circuit_rejudge.py::test_a_new_breaker_written_by_another_process_blocks_the_rejudge
FAILED test_v2_circuit_rejudge.py::test_startup_alignment_registers_the_persisted_breaker
FAILED test_v2_circuit_rejudge.py::test_no_reset_path_leaves_the_marker_behind
FAILED test_v2_circuit_rejudge.py::test_released_cooling_can_be_held_by_the_breaker_again
FAILED test_v2_circuit_rejudge.py::test_breaker_cooldown_never_hid_the_model_from_the_listing
FAILED test_v2_circuit_rejudge.py::test_running_gateway_rejudges_after_the_user_deletes_the_file
10 failed, 163 passed in 3.39s
```

### R3 选路不重判（`pick_and_acquire` 退回只调 `_lift_if_expired`）→ 红 1
```
FAILED test_v2_circuit_rejudge.py::test_selection_releases_the_breaker_held_resource_only_when_the_breaker_is_gone
1 failed, 172 passed in 3.37s
```
（R2 不抓这条、R3 只抓这条 → 两处读取点各自独立被钉住，不是同一处生效两次。）

### R4 释放不看「熔断是否仍成立」（无条件抬）→ 红 12（含既有判据 1 条）
```
FAILED test_v2_circuit_rejudge.py::test_deleting_the_breaker_file_releases_the_row_on_the_next_snapshot
FAILED test_v2_circuit_rejudge.py::test_snapshot_keeps_the_row_cooled_while_the_breaker_still_holds
FAILED test_v2_circuit_rejudge.py::test_unwired_manager_never_rejudges
FAILED test_v2_circuit_rejudge.py::test_untrusted_breaker_file_is_never_released
FAILED test_v2_circuit_rejudge.py::test_a_predicate_that_raises_fails_closed
FAILED test_v2_circuit_rejudge.py::test_selection_releases_the_breaker_held_resource_only_when_the_breaker_is_gone
FAILED test_v2_circuit_rejudge.py::test_other_process_deleting_the_file_is_visible_without_restart
FAILED test_v2_circuit_rejudge.py::test_a_new_breaker_written_by_another_process_blocks_the_rejudge
FAILED test_v2_circuit_rejudge.py::test_startup_alignment_registers_the_persisted_breaker
FAILED test_v2_circuit_rejudge.py::test_released_cooling_can_be_held_by_the_breaker_again
FAILED test_v2_circuit_rejudge.py::test_running_gateway_rejudges_after_the_user_deletes_the_file
FAILED tests/unit/test_v2_circuit.py::test_sync_circuit_benches_resources_after_restart
12 failed, 161 passed in 3.39s
```
（既有判据 `test_v2_circuit.py::test_sync_circuit_benches_resources_after_restart`
也在守"观察期内不得放出"，未被修改。）

### R5 释放不看成因（任何 cooldown 都抬 = 第 1 号坑）→ 红 6（含既有判据 1 条）
```
FAILED test_v2_circuit_rejudge.py::test_quota_exhaustion_cooldown_survives_the_breaker_delete
FAILED test_v2_circuit_rejudge.py::test_backoff_cooldown_survives_the_breaker_delete
FAILED test_v2_circuit_rejudge.py::test_a_longer_backoff_after_the_breaker_is_not_released
FAILED test_v2_circuit_rejudge.py::test_a_bench_written_while_the_breaker_is_absent_is_never_registered
FAILED test_v2_circuit_rejudge.py::test_endpoint_can_declare_a_non_breaker_cause
FAILED tests/integration/test_int_v2_zcode_admin.py::test_overview_surfaces_circuit_reason
6 failed, 167 passed in 3.39s
```

### R6 释放不看终态（`invalid`/`disabled` 也抬）→ 红 2
```
FAILED test_v2_circuit_rejudge.py::test_terminal_states_are_never_reopened_by_the_rejudge[invalid]
FAILED test_v2_circuit_rejudge.py::test_terminal_states_are_never_reopened_by_the_rejudge[disabled]
2 failed, 171 passed in 3.37s
```

### R7 判据抛错当成「已解除」（fail open）→ 红 1
```
FAILED test_v2_circuit_rejudge.py::test_a_predicate_that_raises_fails_closed
1 failed, 172 passed in 3.35s
```

### R8 判据缺失当成「已解除」（core 自己判熔断）→ 红 2
```
FAILED test_v2_circuit_rejudge.py::test_unwired_manager_never_rejudges
FAILED tests/unit/test_v2_circuit.py::test_sync_circuit_benches_resources_after_restart
2 failed, 171 passed in 3.37s
```

### R9 解除后不清标记 → 红 2
```
FAILED test_v2_circuit_rejudge.py::test_selection_releases_the_breaker_held_resource_only_when_the_breaker_is_gone
FAILED test_v2_circuit_rejudge.py::test_no_reset_path_leaves_the_marker_behind
2 failed, 171 passed in 3.37s
```

### R10 到期归位不清标记 → 红 1
```
FAILED test_v2_circuit_rejudge.py::test_no_reset_path_leaves_the_marker_behind
1 failed, 172 passed in 3.37s
```

### R11 凭据变更清零不清标记 → 红 1
```
FAILED test_v2_circuit_rejudge.py::test_no_reset_path_leaves_the_marker_behind
1 failed, 172 passed in 3.37s
```

### R12 解除后仍留着熔断那份旧钟点（`cooldown_until` 不作废）→ 红 1
```
FAILED test_v2_circuit_rejudge.py::test_no_reset_path_leaves_the_marker_behind
1 failed, 172 passed in 3.36s
```
⚠️ 诚实批注：这一处**只被字段级断言抓到** —— 「冷却剩余」列的推导先看 `status`
（`cooldown_remaining_ms()` 在非 cooldown 时直接返 0），所以 J1 的
`cooldown_remaining_ms == 0` 抓不到"留着未来钟点"这件事。见负面清单 N-4。

### R13 全局回写不声明成因（`bench_all_zcode` 摘掉作用域）→ 红 13
```
FAILED test_v2_circuit_rejudge.py::test_deleting_the_breaker_file_releases_the_row_on_the_next_snapshot
FAILED test_v2_circuit_rejudge.py::test_a_longer_backoff_after_the_breaker_is_not_released
FAILED test_v2_circuit_rejudge.py::test_shorter_backoff_does_not_take_the_breaker_ownership
FAILED test_v2_circuit_rejudge.py::test_terminal_states_are_never_reopened_by_the_rejudge[invalid]
FAILED test_v2_circuit_rejudge.py::test_terminal_states_are_never_reopened_by_the_rejudge[disabled]
FAILED test_v2_circuit_rejudge.py::test_untrusted_breaker_file_is_never_released
FAILED test_v2_circuit_rejudge.py::test_selection_releases_the_breaker_held_resource_only_when_the_breaker_is_gone
FAILED test_v2_circuit_rejudge.py::test_other_process_deleting_the_file_is_visible_without_restart
FAILED test_v2_circuit_rejudge.py::test_a_new_breaker_written_by_another_process_blocks_the_rejudge
FAILED test_v2_circuit_rejudge.py::test_no_reset_path_leaves_the_marker_behind
FAILED test_v2_circuit_rejudge.py::test_released_cooling_can_be_held_by_the_breaker_again
FAILED test_v2_circuit_rejudge.py::test_breaker_cooldown_never_hid_the_model_from_the_listing
FAILED test_v2_circuit_rejudge.py::test_running_gateway_rejudges_after_the_user_deletes_the_file
13 failed, 160 passed in 3.42s
```

### R14 启动对齐不声明成因（`sync_circuit_to_runtime` 摘掉作用域）→ 红 1
```
FAILED test_v2_circuit_rejudge.py::test_startup_alignment_registers_the_persisted_breaker
1 failed, 172 passed in 3.38s
```

### R15 登记不看「熔断此刻真的成立」（摘掉 `active()` 那道闸）→ 红 2（含既有判据 1 条）
```
FAILED test_v2_circuit_rejudge.py::test_a_bench_written_while_the_breaker_is_absent_is_never_registered
FAILED tests/integration/test_int_v2_zcode_admin.py::test_overview_surfaces_circuit_reason
2 failed, 171 passed in 3.38s
```
🔴 这条是**设计裁决的证据**：正因为"没有熔断凭据的回写不登记成因"，
那条既有 §17 接口判据才继续成立（按简报字面"凡熔断回写一律标记"会把它打红）。

### R16 端点忽略调用方声明的成因（一律按熔断）→ 红 1
```
FAILED test_v2_circuit_rejudge.py::test_endpoint_can_declare_a_non_breaker_cause
1 failed, 172 passed in 3.39s
```

### R17 装配侧不注入判据（`main.py:200` 那行撤掉）→ 红 1
```
FAILED test_v2_circuit_rejudge.py::test_running_gateway_rejudges_after_the_user_deletes_the_file
1 failed, 172 passed in 3.38s
```

### R18 `bench()` 丢掉终态闸门（删 `core/resources.py` 的 `if state.status in ("invalid","disabled"): return False`）→ 红 2
```
FAILED tests/unit/test_v2_circuit_rejudge.py::test_terminal_state_reached_while_the_breaker_holds_is_still_terminal
FAILED tests/unit/test_v2_circuit.py::test_terminal_states_are_not_revived_by_a_cooldown
2 failed, 171 passed in 3.33s
```
（J9 抓的是"新机制与既有终态闸门的交界处"，与既有判据同向、互为备份。）

### 判据 ↔ 撤回映射（每条判据都至少被一次撤回抓红，无空过；逐条对照上面的原样输出）

| 判据 | 抓红它的撤回 | 判据 | 抓红它的撤回 |
|---|---|---|---|
| J1 | R1 R2 R4 R13 | J12 | R1 R3 R4 R9 R13 |
| J2 | R4 | J13 | R1 R2 R4 R13 |
| J3 | R1 R4 R8 | J14 | R1 R2 R4 R13 |
| J4 | R5 | J15 | R5 R15 |
| J5 | R5 | J16 | R1 R2 R14 |
| J6 | R1 R5 R13 | J17 | R1 R2 R9 R10 R11 R12 R13 |
| J7 | R1 R2 R13 | J18 | R1 R2 R4 R13 |
| J8 | R1 R6 R13 | J19 | R1 R2 R13 |
| J9 | R18 | J20 | R1 R2 R4 R13 R17 |
| J10 | R1 R4 R13 | J21 | R5 R16 |
| J11 | R1 R4 R7 | | |


## 6. 全量回归（原样尾行）

判据文件单独跑：
```
$ .venv/bin/python -m pytest tests/unit/test_v2_circuit_rejudge.py -q --basetemp=$(mktemp -d) -p no:warnings
......................                                                   [100%]
22 passed in 0.14s
```

全量（收尾必跑）：
```
$ .venv/bin/python -m pytest -q --basetemp=$(mktemp -d) -p no:warnings
748 passed in 178.61s (0:02:58)
```
基线（改动前同命令）：`726 passed in 169.56s` → 726 + 22 = **748**。
零既有判据被修改、零 skip/xfail：`git status --short tests/` 只有
`?? tests/unit/test_v2_circuit_rejudge.py` 一项（新文件），既有测试文件一个字节都没动。

读路径覆盖面（grep 实测，用来支撑"接了几处就几处"这句话）：
`ResourceState.status` 的消费方在包内只有两处 ——
`available()`（被 `pick_and_acquire` 用）与 `servable_models`（只判 `disabled`/`invalid`）；
`cooldown_remaining_ms` / `_rendered_last_error` 只在 `snapshot_by_resource` 里被读
（`grep -rn "\.status ==\|status in (" model_gateway` 无第三处运行态读者）。
所以"出快照 + 选路"两处接完即为全覆盖，`/v1/models` 那条接了是空操作（F9 + J19）。

## 7. 负面清单

1. **没接的读路径**：`servable_models`（`/v1/models`、`mgw setup`、`config_warnings`）
   —— 机制上接了也是空操作（F9），已用 J19 钉住"熔断 cooldown 不隐藏模型"这个事实；
   若哪天有人把熔断回写改成 `disable`，J19 会红，逼作者重新对齐口径。
2. **没测的组合**：
   - 熔断 + **同 rid 多厂商模型映射**（一个资源两条映射，只有一条被熔断按住）的聚合形态
     未单测（`snapshot_by_resource` 的聚合逻辑由既有判据守着，本文件只测单映射条目）；
   - `circuit.json` **落盘失败**（`unpersisted` 档，熔断只在内存里）时"删文件"这个动作
     本身无从执行 —— 该档的释放依赖内存态到期，本改动不覆盖、也没测；
   - 运营 `query_balance` tick（额度刷新）与用户删文件的**先后交错**没有专门判据；
   - 多进程**并发**写/删状态文件（§17 的 mkstemp 原子性那一族）由既有判据覆盖，未新增；
   - 真实 `mgw zcode claim` CLI 进程 → HTTP → 网关的端到端一条没跑（J20 用 ASGI 端点代替）；
     `scripts/ui_verify_v2_visible.py` 也没重跑（它经 `apply_to_resource` 直接回写，
     不在熔断作用域内 → 标记为假 → 行为应当不变，但这是**推断不是实测**）。
3. **界面仍可能陈旧的形态**：
   - 释放只发生在**有人读**的时候。总览的 `/admin/api/status` 是 5s 轮询
     （`api/admin.py:110-123`），所以界面开着时**最长约 5 秒**那一行仍是旧 `cooldown`；
     界面没开且没有流量 → 一直陈旧到下一次读（这是"读时重判"的定义性代价，
     裁决明确"不做跨进程通知、不加 watcher"）。
   - `untrusted`（文件在而读不动）→ 一律不释放：用户若删错了文件或只剩坏文件，
     那一行不动 —— 方向与 Q28-⑧① 一致，但界面上没有"为什么没反应"的第二出口
     （`circuit.reason()` 里那句"删除该文件即可解除"只在 CLI 侧可见）。
   - 判据本身抛错（ZCode 子模块不可用 / 目录权限）→ fail-closed 不放开，
     那一行最长冻满 30 分钟。
   - 前端 `dashboard.js:129-138` 的徽章文案仍写"…后自动回池，无需处理"，
     它按 `cooldown_remaining_ms` 说话；本次纯后端，前端未改（纪律），
     所以"刚删完文件的那 5 秒"里徽章还是旧措辞。
4. **`cooldown_until` 作废只发生在重判释放那一支**（R12 的红证只有一条字段级判据）；
   到期归位那一支本来就 `now >= cooldown_until`，无需作废。
5. **成因作用域是进程内一个布尔**（`ResourceManager._bench_held_by_circuit`）：
   靠"三条熔断回写路径全程同步、段内不 await"成立（已写进 `circuit_hold()` 的约束注释）。
   将来若有人把回写改成跨 await 的批量任务，误标风险会回来 —— 目前**没有判据**能抓到那种
   重构（写不出"await 了就红"的自动判据），属于口径靠注释守的地方。
6. **CLI 侧文案未更新**（`cli_zcode.py:249-273` 只说"删除该文件可立即放开后续领取"）：
   现在删完对**界面**也立刻生效，这句仍然正确、只是说少了；该文件不在本次范围，未动。
7. **热路径多了一次磁盘回读**：`pick_and_acquire` 每次选路调一次 `_circuit_cleared()`
   → `CooldownManager.active()` → `_load()`（**每次真读盘**，这是 S-26⑤ 的既有口径，
   不用 mtime 去重）。一次约 100 字节的本地读，相对一次上游 HTTP 可忽略，
   且领取路径本来就是这个尺（每账号一次）。**没有**加 TTL 缓存：加了就会重新造出
   "秒级时间戳卷上看不见另一个进程刚写的熔断"那个坑（quota.py `_load()` 的注释写得很清楚）。
   未实测单次转发的延迟差值（无基准测试判据），只做了读路径计数的静态核对。

## 8. 过程中发现的其它问题（按规矩报告，未擅自扩大改动）

1. `tests/unit/test_v2_circuit.py:640-654` 有一坨**游离在模块级的 `def __init__(self, resources…)`**
   （`_RealMgrRuntime` 的一份重复粘贴：缩进 8 空格、没有宿主类，真实定义在 `:389`）。
   它是死代码，不参与收集也不影响任何判据，但下一次有人照着它改就会改到错的那一份。
   建议该文件的主人清理（不在本次范围，我没碰）。
2. README 的数字与真实条数**长期贴边**：基线 726 对宣称 710 已经吃掉 ±20 容差里的 16，
   任何一批新增测试都会把它顶红（本次实测就是这样红的，见 §0）。
   建议把 `test_v2_readme_claims.py::test_readme_test_counts_are_not_stale` 的容差收到 0
   （徽章数字 == 实测 collected），否则每个并行批次都要抢着改同一行 README。
   —— 这是**判据本体**，我没有权限改，只在此报告。
3. 熔断的**解除出口**目前只有"删文件 / 等 30 分钟"两条，`mgw zcode` 没有"解除熔断"的
   一等命令（`cli_zcode.py:249-273` 只打印文件路径与提示）。读时重判让"删文件"立刻对
   界面生效，但**命令化**仍是缺口 —— 属需求侧决定，未自创。

