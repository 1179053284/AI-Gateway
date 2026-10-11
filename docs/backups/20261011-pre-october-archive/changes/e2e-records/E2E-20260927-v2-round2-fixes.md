# E2E-20260927 · v2.0 第二轮收敛（上轮验收 8 条未关闭项 + 既存缺陷 BUG-1/BUG-2）

> 依据：`docs/specs/tech-design.md` v2.0 §12–§21（含 §19 交付判据）· `docs/specs/prd.md` **v1.15**（Q25/Q26/Q27 + **本轮新增 Q28**）
> 上游报告：`docs/changes/reviews/{PM,eng,ix}-accept.md`（09-26 17:1x）→ 修正记于
> `docs/changes/e2e-records/E20260926-v2-implementation.md`（09-26 19:51）
> **本文档 = 对那份"已修"账本的复核与补漏**：复核发现其中 3 项只改了表面、2 项判据仍未达、
> 1 项"全绿"结论不成立。逐条见下。
> 证据纪律（铁律 2）：每条附 `file:line` 或实跑输出；未实测项显式标注。

---

## 一、开工基线（先核实，不是转述）

| 项 | 实测 |
|---|---|
| `git log -1` | `5158cbc`（HEAD），M3–M5 全部为**未提交工作树** |
| `.venv/bin/python -m pytest -q` | **462 passed in 55.64s**（与上轮记录一致） |
| 上轮 14 条修正 | **11 条已落地**；3 条为"半落地或结论不实"（见 §二 R1/R3/R7） |
| `docs/` 目录 | 上轮修正**从未碰过 PRD**（`prd.md:567/570/571/721` 原样） |

> 🔴 **复核方法与结论的关系**：上轮账本写「死代码 0 项 —— 51 个新增公开函数全部有生产调用点」，
> 本次逐符号 AST 复核结果为 **仍有 3 个无调用点**（`auth.build_headers` / `oauth.refresh` /
> `store.delete_account`）。该结论**不成立**，已在本轮修正（R7）。

---

## 二、本轮修了什么（逐条：判据 → 落点 → 测试）

### R1 🔴 `zcode_claim` 缺 `import json` → 真实凭据下领取主流程必崩

| 项 | 内容 |
|---|---|
| 缺陷 | `ops/builtin/zcode_claim.py:41` 用 `json.loads(...)`，但该文件 imports 里**没有 `json`** |
| 为什么上轮 462 全绿照不出 | 全仓**没有任何测试调用生产 `zcode_claim.claim()`** —— `test_v2_ops.py` 一律注入假 claim（与上轮"fake 掩盖真签名"同类） |
| 修正 | `ops/builtin/zcode_claim.py:13` 加 `import json` |
| 测试 | **新建** `tests/unit/test_v2_claim_wiring.py`（10 条）：走**生产 `claim()`**，只把 HTTP 上游换成假客户端；含 `test_credentials_of_returns_jwt_mid_and_uid` |
| 🔴 反证（锁能红） | 临时删掉 `import json` → **`10 failed`**（全灭），恢复后 10/10 通过 |

### R2 🔴 熔断"只接了 cron 一条腿"

| 项 | 内容 |
|---|---|
| 缺陷 | `cli_zcode.py:184` 调 `run_once(accounts=…, manual=…)` **不传 `runtime=`** → `_maybe_bench` 首行 `if runtime is None: return` → CLI 手动领取遇 3012 风控时**熔断静默不生效** |
| 为什么不能"传个 runtime"了事 | CLI 是**独立进程**，改不到运行中网关内存里的 `ResourceState` —— 必须走跨进程出口 |
| 修正 | ① 新建 `core/local_admin.py:admin_post()`（本机 `127.0.0.1:<port>` POST，网关未运行返回 None）；② 新增端点 `POST /admin/api/zcode/bench`（`api/admin.py:403-423`）；③ `zcode_claim._maybe_bench` 两腿分流：有 runtime → 直接回写；无 runtime → `admin_post`（`ops/builtin/zcode_claim.py:84-108`）；④ `cli_zcode._ack_failures` / `cli_probe._reload_running_gateway` 收敛到同一 helper（原先各写一份 urllib） |
| 测试 | `test_risk_control_benches_in_process`（有 runtime 不走 HTTP）+ `test_risk_control_benches_from_cli_process`（`runtime=None` **必须**打到 `/admin/api/zcode/bench`）+ `test_risk_control_detected_by_message_not_only_code` |

### R3 🔴 §19 M5-3 额度预扣：**机制齐了、没人调用** ⇒ 判据形同未交付

| 项 | 内容 |
|---|---|
| 缺陷 | `reserve_quota/settle_quota/release_quota/set_quota`（`core/resources.py`）在 `model_gateway/` 内**零调用点**；`quota_remaining` 永远 `None` → `has_quota()` 恒真；上轮"并发不超发"用例是 `for _ in range(10)` **顺序循环，无一处 await** |
| 修正（接进生产路径） | ① `pick_and_acquire(system_model, exclude, amount=1)` 在**与 `in_flight += 1` 同一同步段**内预留（`core/resources.py:163-196`），预留失败则按同序换下一个候选；② `core/scheduler.py` 两条路径对称收尾 —— 非流式：成功 `settle_quota` + `settled` 标志，`finally` 未结算则 `release_quota`（`:364,451-453,466-468`）；流式：`stream_settled` 同构（`:574,617-619,724-726`）；③ 数据源接线：新增 `quota.read_account_snapshot` / `remaining_units` / `refresh_runtime_quotas`（`upstream/zcode/quota.py:206-268`），由 `main.refresh_quotas()` 在**启动 + ops tick 末尾 + 管理端点**三处调用（§17 触发时机①③）；④ `api/admin.py:351-365` 的重复实现收敛为调用 `quota.read_account_snapshot` |
| 顺带修的真实缺陷 | `resource_ids_of_account()` 原先在函数内 `load_config()` 读**默认路径** → 注入临时配置的测试/多实例场景会查错资源；改为优先用 `runtime.config`（`quota.py:309-330`），并把两个测试 fake 的签名同步为 `lambda acc, cfg=None`（**fake 必须与真实签名一致**，这是上轮 S2 的教训） |
| 测试 | 单元 `tests/unit/test_v2_quota_reservation.py`（9 → **16** 条）：`asyncio.gather` **真并发**（10 worker、额度 3 → 恰好 3 个拿到）/ 预留与 `in_flight` 同段 / 耗尽自动切备 / `refresh` 写入 `ResourceState`；端到端 **新建** `tests/integration/test_int_v2_quota_reserve.py`（4 条）：额度 2 + 上游 `delay=0.5` → **恰好 2 个 200、3 个 503**，且 `quota_reserved/in_flight` 归零无泄漏 |
| 🔴 反证（锁能红） | 把 `if self.reserve_quota(best, amount)` 换成 `if True` → **4 failed**（含端到端超发用例），恢复后全绿 |
| ⚠️ 有意偏离（须知悉） | §17 额度刷新三触发点中的 **②「模型转发成功后按 30s 节流补刷」未接**。理由：该通道是**客户端日志尾读（单次 4 MiB）**，挂在每次转发的热路径上代价过高；预留用的是**最近一次快照**，tick 级（默认 60s）新鲜度已足以拦住"余量已 0 还派活"这一类超发。未知额度**保持 `None` = 不管控**（宁可漏管也不误封资源） |

### R4 🟡 §16.4 双层互斥**跨进程**不成立

| 项 | 内容 |
|---|---|
| 缺陷 | 上轮把 `AccountLocks` 改成"模块级共享锁"只解决**进程内**；cron 在网关进程、`mgw zcode claim` 在 CLI 进程 → 两个内存 `set`，同账号仍可双领 |
| 修正 | `ops/runner.py`：锁**落文件**（`data/ops-locks/<账号>.lock` 写 pid，`O_CREAT\|O_EXCL` 原子创建，pid 已死 → 陈旧回收，与 `core/instance_lock.py` 同口径）；同进程侧另加**进程级持有集** `_HELD_BY_US`（锁文件按 pid 判活，同进程第二个实例会把文件当成"自己的陈旧锁"抢走 —— 这条是新发现的次生坑）；`PlanLock` 同样接文件锁；测试隔离用 `MGW_OPS_LOCK_DIR`（`tests/conftest.py` autouse 重定向 + 清空持有集） |
| 测试 | `tests/unit/test_v2_ops.py` 新增 **7 条**：`test_second_process_cannot_acquire_while_held`（**真实子进程持锁**，父进程 `try_acquire` 必须 False）/ `..._succeeds_after_holder_exits` / `test_corrupt_lock_file_is_reclaimed` / `test_account_lock_name_is_path_safe`（`../../escape` 不得越出锁目录）/ `test_plan_lock_is_cross_process_too` / `test_run_once_skips_account_held_by_another_process` |

### R5 🟡 §19 M3-2 判据要求的 **PRD 回填**从未做

| 项 | 内容 |
|---|---|
| 缺陷 | `prd.md:570/571/721` 仍是 snake_case + 顶层 `effort_levels`；`prd.md:567` 仍是「UI 仅新增默认折叠的『高级 · 能力覆盖』」 |
| 修正 | PRD 升 **v1.15**：① Q25-② 正文改 camelCase + `caps.thinkingLevelMap`（并标注这是"实现/契约与文档背离"的修正，历史条目原文保留 + 指向说明）；② Q25-① 改为「保留 `caps_overrides` 字段、砍掉界面」；③ 新增 **§9 Q28 四项**归档（①字面回填 ②只下发可服务模型 ③推理优先级定序 ④跨进程出口与调度时机）；④ FR-5.1 补"仅返回可服务模型"的规范表述 |
| 依据 | 技术方案 §12.2（`:721-724`）、§14.1（`:989-990`）、§19 M3-2 判据（`:1383`）、final-verify-2 的 3.5d |

### R6 🟡 §19 判据缺测四行 → 全部补齐

| 判据行 | 新增用例 |
|---|---|
| M4-2 两账号 `credentials/telemetry` 互不覆盖 | `tests/unit/test_v2_zcode.py::test_two_accounts_do_not_overwrite_each_other` + `test_reimport_of_one_account_leaves_the_other_intact`（**逐字节**比对 B 的两份文件） |
| M4-2 主 `~/.zcode/v2` 三件未被写入 | `test_main_client_directory_three_files_never_written`（`credentials` / `config` / `telemetry` 三件 bytes 不变；`setting.json` 按 §15.3 **已知例外不计**） |
| M5-0 `import` 冲突退出码 4 且不写盘 | **新建** `tests/unit/test_v2_cli_zcode.py::test_import_conflict_exits_4_and_writes_nothing`（CLI 层：`rc == 4` + 目录未落 + 三个选项文案 + `list_accounts()` 仍只有 1 条）；另补 `--regenerate` / `--reuse` 两条决策分支 |
| M5-1 无住宅代理不影响模型转发（并发） | **新建** `tests/integration/test_int_v2_ops_isolation.py`：运营批量与 6 个 chat 请求**同时在飞**（`asyncio.gather` 套内层 gather）→ 运营 `failed` 且文案给出路、6 个全 200、资源**未被冷却**、红点照常累加 |

### R7 🟡 残余死代码 3 个 + 上轮"全接线"结论不实

| 符号 | 处置 | 依据 |
|---|---|---|
| `auth.build_headers` | **接线**：`claim._headers` 改为在它之上补 ZCode 专属头（消掉第三份 Bearer/UA 构造）；`build_headers` 增 `app_version` 形参 | §17「双通道鉴权归 auth」 |
| `oauth.refresh` | **删除**（含 `TOKEN_URL`），并在模块 docstring 记录去向 | §17 的 refresh 属 **M4-3**（判据本身=手工/待实测 T5a/T5b）；首期凭据一律来自 `mgw zcode import` 导入的本机已登录缓存，无落点不留死代码 |
| `store.delete_account` | **接线**：新增 `mgw zcode remove <账号>`（先打印绝对路径再确认、非交互必须 `--yes`） | 否则用户只能手删我们自己定义的目录结构；`§21.3 原则 2`（破坏性操作先看后做） |
| 防再长回来 | `test_v2_cli_zcode.py::test_symbol_has_a_production_call_site`（**AST 逐符号**，12 个参数化用例）+ `test_removed_dead_symbols_stay_removed` | 字符串 grep 会把"文档里提到"误判成"已接线"，故用 AST |

### BUG-1 🔴（既存缺陷，`.workbuddy-ai/memory` 自陈未修）`/v1/models` 下发不可服务模型

| 项 | 内容 |
|---|---|
| 缺陷 | `api/openai_compat.py` 只按 `m.enabled` 过滤 → 无可用资源的模型照样声明，工具选中即 `NO_RESOURCE`（**无报错的失败**，正是 §12.1 立项目标要消灭的形态） |
| 修正 | ① 单一判据源 `core/resources.py:servable_models(config, registry=None)`（≥1 条**已启用且未失效**的资源映射；**冷却中/额度为 0 仍算可服务** —— 临时态不该让模型在工具里凭空消失）；② 路径 B `api/openai_compat.py:53-58` 过滤；③ **路径 A 同判据**：`cli_setup.build_cli_models` 也过滤，并打印「已跳过 N 个无可用资源的模型」（只读文件的工具走的是路径 A，漏它等于没修） |
| 可见性（不允许只过滤不解释） | `Runtime.config_warnings()` 新增第 **③** 类告警 `model_unservable`（指名模型 + 指路「资源池设置/模型资源」页）→ 总览页横幅 + 启动日志双通道 |
| 测试 | `tests/unit/test_v2_servable.py`（**12** 条，含 registry 维度与"悬空引用在配置校验层就被拒"的边界）+ `tests/integration/test_int_v2_servable.py`（6 条，含 invalid 资源被隐藏且有横幅、cooldown 不隐藏） |

### BUG-2 🟡（既存"缺陷"）实为**需求内冲突**，按用户裁决处理

| 项 | 内容 |
|---|---|
| 报告口径 | `memory` 笔记记为「`inject_reasoning_into_body` 静默覆盖用户 `SystemModel.params` 的 `reasoning_effort`」 |
| 复核结论 | 代码没有写错：它实现的正是 **PRD FR-3.16（Q15，P0，已过 E2E-15 实测校准）** 的「请求级 > 资源级默认 > 厂商默认」。真正的矛盾是 **Q24-⑥ 参数卡**另写了一套「工具传参 > 网关设置 > 厂商内置」，两条 clause 未互相排序 —— `reasoning_effort` 两边都能配 |
| 用户裁决 | **「按 Q15」** → 生效序 = **请求级 > 资源级默认 > 参数卡（网关设置）> 厂商内置**，**优先级实现不动**（若反过来，`resources[].reasoning` 这一层在任何配了参数卡的模型上都失效 = 推翻一条 P0） |
| 那"静默"怎么办 | 新增第 **④** 类告警 `param_shadowed`：参数卡字段会被资源级默认覆盖时，横幅点明是哪个模型的哪条映射、并写清生效序（覆盖允许，静默不允许）；定论已归档 **PRD Q28-③** |
| 测试 | `test_int_chat.py::TestModelParamsInjection` 新增 2 条**出站体**断言（资源级赢过参数卡 / 无资源默认时参数卡生效 / 请求级永远最高）+ `test_int_v2_servable.py` 的告警可见性 2 条 |

### 顺带发现并修掉的（不在开工清单内）

| # | 发现 | 处置 |
|---|---|---|
| 1 | 🔴 **运营调度器在启动瞬间就跑第一轮**（`Scheduler.start` 先 tick 后 sleep）→ 每次重启网关都立即发起一次真实领取，重启风暴会对着上游连打 | 改为**先等一个周期**再 tick；`tests/unit/test_v2_ops.py::test_scheduler_waits_one_period_before_first_tick` |
| 2 | 🔴 `ops/runner.Scheduler`（cron 触发 / plan 跳过）**此前零测试** | 补 3 条（等一个周期 / plan 锁被占则跳过且不排队 / cron 模式按分钟粒度不被 `interval_s` 变密） |
| 3 | 🟡 `core/resources.py:212` `def note_success(...) -> None:        state.C = 0`（函数体挤在签名同一行） | 拆回两行（可读性，行为不变） |
| 4 | ⚪ `api/admin.py:403` 段落注释被重复拼接（`# ---------- 配置读写 ----------# ---------- 配置读写 ----------`） | 修正，并在其后插入新端点 |
| 5 | 🟡 `README.zh-CN.md` **完全没有 CLI 章节**（上轮记录称"两个版本都补了"） | 补 `## 命令行（mgw）` 全量子命令 + 破坏性操作说明；EN 版补 `import` / `remove` 与"只下发可服务模型"两条 |

---

## 三、测试与实跑证据

```
$ .venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest
537 passed, 436 warnings in 67.93s
```

**基线对照**：开工前 **462** → 现 **537**（**+75 条**），**零回归**。
（⚠️ 环境坑复记：本沙箱须 `--basetemp=/tmp/mgw-pytest`，否则 pytest tmp 用户名探测失效。）

新增/改写测试文件（8 个新建 + 5 个增补）：

| 文件 | 用例 | 覆盖 |
|---|---|---|
| `tests/unit/test_v2_claim_wiring.py` | **新建 10** | 生产 `claim()` 全路径（R1/R2），反证已做 |
| `tests/unit/test_v2_quota_reservation.py` | 9 → **16** | 真并发不超发 / 预留与在途同段 / 刷新写入 `ResourceState` |
| `tests/integration/test_int_v2_quota_reserve.py` | **新建 4** | 端到端超发（2 成 3 败）/ 未知额度不受控 / 失败释放预留 |
| `tests/unit/test_v2_ops.py` | 33 → **43** | 跨进程互斥（子进程）7 条 + 调度器触发时机 3 条 |
| `tests/unit/test_v2_cli_zcode.py` | **新建 20** | 冲突退出码 4 / `remove` 确认流 / **AST 死代码护栏 12 条** |
| `tests/unit/test_v2_servable.py` | **新建 12** | `servable_models` 判据本体 + 路径 A 同判据 |
| `tests/integration/test_int_v2_servable.py` | **新建 6** | 清单过滤 + 两类新告警 |
| `tests/integration/test_int_v2_ops_isolation.py` | **新建 1** | 运营失败 × 并发转发隔离 |
| `tests/unit/test_v2_zcode.py` | 33 → **37** | M4-2 两账号互不覆盖 / 主目录三件未写 |
| `tests/integration/test_int_chat.py` | +2 | 推理三级优先级（出站体断言） |
| `tests/conftest.py` | +2 fixture | 锁目录重定向 + 进程级持有集复位 |

### §21 用户可见出口实测（含本轮新增的③④两类）

```
$ .venv/bin/python scripts/ui_verify_v2_visible.py

[后端出口]
  ✓ overview 含四类告警  ['model_unservable', 'model_without_resource',
                          'param_shadowed', 'resource_without_model']
  ✓ 四类措辞互不相同  4 条
  ✓ ① 零映射告警提到 503            ✓ ③ 不可服务告警指名模型
  ✓ ④ 覆盖告警说清生效序
  ✓ /v1/models 不含零映射模型  ['ok-model', 'shadow-model']
  ✓ /v1/models 不含不可服务模型      ✓ /v1/models 保留可服务模型
  ✓ status 含 ops_failed_unread  = 0
后端出口实测 9 项，通过 9 项，失败 0 项

[前端渲染（Node 执行 dashboard.js 的真实渲染函数 + 真实接口数据）]
实测 18 项，通过 18 项，失败 0 项
  （新增断言：横幅含「已从 /v1/models 隐藏」、横幅说清推理优先级）
```

### CLI 冒烟（本机实跑）

```
$ .venv/bin/python -m model_gateway.cli --help            → rc=0
$ .venv/bin/python -m model_gateway.cli zcode --help      → 列出 list/login/launch/import/claim/remove
$ .venv/bin/python -m model_gateway.cli zcode remove nope --yes
✗ 账号『nope』不存在（见 `mgw zcode list`）                → rc=2
```

### 🔴 反证复跑（本轮新增护栏"能红"的证据）

| 撤掉的修复 | 结果 |
|---|---|
| `zcode_claim.py` 删 `import json` | `test_v2_claim_wiring.py` → **10 failed** |
| `pick_and_acquire` 不预留（`if True`） | 额度用例 → **4 failed**（含端到端超发） |

---

## 四、未实测项（诚实标注，不宣称完成）

§19 的 T1–T10 **状态不变**（均需真实 ZCode 凭据 / 联网 / 真实客户端），本轮**未新增**可测项：
T1 免费额度通道 / T2 `billing/current` 401 / T3 `enc:v1` 的 `username` 口径 / T4 `setting.json` 重定向 /
T5a `curl_cffi` 过 WAF + T5b async SSE / T6 CLI device flow / T7 验证码强制性 / T8 3012 阈值 /
T9 RE 文档时效 / T10 `ZCODE_DESKTOP_*` 覆盖 `app.setPath`。

本轮**新增加固**的未实测口径：

| # | 项 | 为什么未测 |
|---|---|---|
| N1 | 额度余量的**真实量纲**（1 请求 = 1 单位是否为上游口径） | 需真实账号 + 联网读 `billing/balance`；当前判据只保证"余量为 0 不再派活"这一保守方向 |
| N2 | `POST /admin/api/zcode/bench` 在**网关真运行 + CLI 真领取**下的端到端一次 | 需真实凭据；本轮以"CLI 进程必然打到该端点"的路由级断言覆盖（`test_risk_control_benches_from_cli_process`）+ 端点本身的集成断言 |
| N3 | 跨进程互斥在**真实 cron + 真实 CLI** 双进程下的表现 | 锁文件机制已用真实子进程验证（`test_second_process_cannot_acquire_while_held`）；未测的是"真实领取"这一层（受 N2 同源阻塞） |
| N4 | 验证码求解 + 住宅代理（Playwright） | 外部依赖（需外购住宅代理）；未配置时明确报错并降级为 `failed` |

> 均按 PRD Q27-③「做的过程中再测」处理。

---

## 五、与方案的一致性

### 5.1 一处**有意偏离**（§17 触发点②）

已在 R3 表末给出理由与代价分析：不接「模型转发成功后 30s 节流补刷」，保留「启动 + tick 末尾 + 管理端点」三处中的两处定时点 + 一处手动。
若验收判为不可接受，恢复成本 = 在 `scheduler` 成功分支加一次节流调用（不改数据结构）。

### 5.2 上轮记录的**偏离仍然存续**（未翻案）

`EnumEntry.tool_call` 默认 `True`（方案 §12.3 字面为 `False`）—— 理由见上轮 §5.1，本轮复核**同意维持**：默认 `False` 会把"工具静默删 `tools`"这个 bug 原样保留。

### 5.3 方案"不做清单"仍然守住

未建统一 Device Registry、未做免重启热切换、未做 L-B/L-C 录入界面、未做 GUI 自动化、未做对外额度端点、未做首期账号管理前端 UI；本轮新增面仅为 **1 个管理端点 + 1 个 CLI 子命令 + 2 类告警**，均有明确落点理由（跨进程 / 路径 A 同源判据 / 不允许静默）。

### 5.4 `.workbuddy-ai/memory/MEMORY.md` 的"已知缺陷"账

BUG-1 已修（本轮）；BUG-2 经复核为**需求内冲突**、按 Q28-③ 定论后**优先级不变 + 出告警**。该文件由另一工具维护，本轮未代改（避免误伤他方记录），此处留痕。

---

## 六、复跑方式

```bash
cd /Users/w/Desktop/Model-Gateway
.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest     # 537 passed
.venv/bin/python scripts/ui_verify_v2_visible.py             # 后端 9/9 + 前端 18/18
.venv/bin/python -m model_gateway.cli --help                 # 或安装后 `mgw --help`
```
