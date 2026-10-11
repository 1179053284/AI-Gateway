# PM 实现验收报告 · 第三轮（tech-design v2.0 §12–§21 / M3–M5 · 第二轮阻塞项 B1–B6 闭环 + 三处偏离独立裁决）

> 角色：资深产品经理（**实现验收**，非设计评审）
> 被审账本：`docs/changes/e2e-records/E2E-20260927-round3-fixes.md`（2026-09-27 15:25）
> 依据：`docs/specs/tech-design.md` v2.0 §19（判据）/ §20（不做清单）/ §21（用户可见出口契约）/ §17；
> `docs/specs/prd.md` **v1.15**（Q25–Q28）
> 方法：**对抗式核查 + 自选样本导出 + 运行时反证**。只读交付：本轮**未改动仓库任何文件**（证据见 §8）。
> 日期：2026-09-27

---

## 1. 验收结论

# **不通过（Fail）** —— 阻塞项 **7 条**（1 严重 / 6 中等）

先说公道话：**本轮的工程实质是三家里最好的一轮**。602 条我逐字复跑通过；§四的 16 行文件计数表**逐项吻合**；
`ui_verify_v2_visible.py` 12/12 + 35/35、exit=0 复现；B2（3012 落盘）/ B3（熔断原因可见）两条**真闭环**
（我用运行时撤法复现出红）；B1 的空过用例换成了**带正控制的拦截式护栏**，这是我这三轮里看到的唯一一次
"正控制真的证明拦得住"。§二 的更正（C1–C7）方向是诚实的，且**自我点名**了"清单要从方案导不能只从报告导"。

不放行的理由不是"没做"，而是**三个新形态**：

1. **一条被当成"已实测"的出口，在真实配置下必然不可达**：`mgw setup` 的"运行态优先判定"（T9 / Q28-② 路径 A）
   经 `local_admin.admin_get("/v1/models")` 发请求，而 `/v1/models` 受接入密钥保护 —— **同一个命令在没有任何密钥时
   会先退出码 2**，所以"能跑到这一步"就等于"必然 401"。我实跑取证（§5.6）。锁定它的测试把 `admin_get` **本身**
   monkeypatch 掉了 → 结构上不可能发现这件事。更糟：此时打印的判定依据是"网关未运行"，**对用户说谎**（网关在跑，只是拒了它）。
2. **本轮刚修完"静默丢字段"，同一轮又新增一个**：`EnumEntry.tool_call` 全目录常量 `True`（无一条 BUILTIN 显式取值，
   images 族也声明支持工具调用），且 §12.3 明写的"可按模型覆写"**三条路径全断**，其中
   `load_enum_pool` **静默丢弃**用户 YAML 里的 `tool_call` 键（实跑：写 `false` → 读回 `true`）。
3. **上一轮的"指错页"缺陷在改文案时反向复发**：告警①现在叫用户"到「资源池设置」页…添加资源映射"，
   而那一页自己的两处提示（`models.js:297` / `:361`）写着"新增映射：**到「模型资源」页**"，
   添加映射的控件 `#rv-addmap` 只在「模型资源」页。同一轮里 `cli_setup.py:116` 的同一句话**写对了** —— 说明改的是文案、不是判据。

另有 **2 条第二轮放行条件未闭环**（B4 §17 额度回写的未披露偏离、B5 的 pytest 锁定缺失）与 **1 条极低成本的账本一致性项**（B6）。

> **三处偏离的独立裁决见 §4**：D3 可接受；D2 **不接受当前形态**（它不是"默认值不同"，而是"该字段不再有信息量且不可覆写"）；
> D1 属**未经批准的 §17 条款裁剪**，且其理由是**被本项目自身实现反驳的假设**（我实测了成本，见 §4.1）。
>
> **对 §二 更正的总体判断**：C3/C4/C5/C6/C7 **成立且可核**（我逐项复跑/复算）；
> **C1 的"已重做为自动导出全集"言过其实** —— 新护栏只扫 30/56 个模块的**模块级函数与类**，
> **类方法与常量整体不在全集内**，而 C1 点名漏掉的正是"`AccountLocks`/`PlanLock` 的若干方法"这一类别；
> 我用自选样本测出 3 个零生产引用的公开方法仍全绿（§6.4）。

---

## 2. §19 逐条核对表（M3-0 … M5-3）

| 阶段 | 判据要点 | 结论 | 实现落点（我核对后的真实行号） | 锁定用例（精确 id，均在 602 内） | 我的核查/修正 |
|---|---|---|---|---|---|
| **M3-0** | `mgw --help` 退出码 0 | **⚠️** | `pyproject.toml:31-32`（`mgw = "model_gateway.cli:main"`）、`model_gateway/cli.py:71` | `tests/unit/test_v2_cli.py::test_help_exits_zero` | 字面判据**本机仍不可执行**：`.venv/bin/mgw` **不存在**（实测 `ls .venv/bin \| grep mgw` 空），`dist-info` 无 `entry_points.txt`。用例走 `main(["--help"])`（进程内）+ `test_cli_entry_declared_in_pyproject`（只 grep pyproject 文本）→ **两条都是代理指标**。账本 C5 已如实更正并给等价形式，故不判 ❌；**关闭动作 = 一条 `pip install -e .` + 复跑，仍未做** |
| **M3-1** | 告警进 `overview.warnings[]`；两类措辞不同；`custom:` 前缀可解析 | ✅ | `api/admin.py:125-172`（`warnings` 字段）、`main.py:231-295`（4 类）、`main.py:431-435`（同时打启动日志）、`enums/matcher.py:266-280`（前缀剥离） | `test_int_v2_capabilities.py::test_overview_exposes_warnings_field` / `::test_warning_for_enabled_model_without_resource` / `::test_two_warning_kinds_have_distinct_wording` / `::test_request_model_prefix_is_stripped[custom:]` | 三条判据字面均达成。⚠️ 但 Q28-② 追加的"必须说明已隐藏"这句话**只锁在 602 之外**的 `scripts/verify_v2_frontend.mjs`（见 BL-5） |
| **M3-2** | `/v1/models` 键集合含 7 字段 + PRD Q25-② 字面回填 | ✅ | `api/openai_compat.py:49-70`、`core/capabilities.py:19-49`；回填 `prd.md:572-573` | `test_int_v2_capabilities.py::test_models_keeps_original_six_fields` / `::test_models_adds_seven_capability_fields`；`test_v2_capabilities.py::test_caps_fields_map_from_enum_entry` | 键集合与原 6 字段向后兼容**达成**；⚠️ 其中一个字段的**取值**不合法（`supportsToolCall`，见 BL-2，判据归属 §12.3） |
| **M3-3** | 方言表落盘可断言；假序列下 S1/S2/S3 确定性验证 | ✅ | `core/dialects.py`、`probe.py:1-170`、`cli_probe.py:129-143` | `test_v2_probe.py::test_probe_rejects_fake_dialect_when_not_zeroed`（S2 单锚点）+ `test_v2_capabilities.py::test_dialect_table_roundtrip` / `::test_dialect_table_save_is_atomic` | 真实探测成功率按判据自身为手工项，未验 |
| **M3-4** | `thinkingLevelMap` 7 键齐全、不支持显式 `null` | ✅ | `core/capabilities.py:52-68` + `core/dialects.py:build_level_map` | `test_v2_capabilities.py::test_level_map_has_all_seven_keys_with_null_for_unsupported` / `::test_level_map_keeps_unsupported_high_tiers_explicit`；`test_int_v2_capabilities.py::test_caps_level_map_has_exactly_seven_keys` | — |
| **M3-5** | `mgw setup` 格式/合并/原子写可断言 | ✅ | `setup_tools.py:60,144`、`cli_setup.py:83-147` | `test_v2_setup.py`（裸数组拒绝/合并保留/备份/无 tmp 残留）+ `test_v2_cli.py::test_setup_dry_run_writes_nothing` / `::test_setup_prints_resolved_target_and_source` / `::test_setup_non_interactive_requires_yes` | — |
| **M4-1** | 假 Anthropic 上游 ASGI 完成一次 chat | ✅ | `adapters/anthropic_out.py`（607 行）、`adapters/__init__.py:build_adapter`、`main.py:186-204`（按 `r.protocol` 分支） | `test_int_v2_anthropic.py::test_chat_nonstream_completes` / `::test_usage_mapped_so_it_is_not_estimated` / `::test_html_response_cools_down_and_second_resource_takes_over`（13 条） | §18.2 ⑤ 的 `status_code=None` 约定有落地（2xx 非 JSON → 上游错误 → 进冷却） |
| **M4-2** | ①设备 ID 冲突拒绝而非静默重生成 ②两账号互不覆盖 ③主 `~/.zcode/v2/` 三件未被写入 | **✅（③本轮换机制，成立）** | ①`upstream/zcode/dataroot.py:97,113,156` ②`store.py:190-210` ③**拦截式**：`tests/unit/test_v2_zcode.py:370-438`（拦 `Path.write_text/write_bytes` + `os.replace` + `os.open` 写标志） | ①`test_v2_zcode.py::test_constraint3_conflict_is_rejected_by_default` ②`::test_two_accounts_do_not_overwrite_each_other` / `::test_reimport_of_one_account_leaves_the_other_intact` ③`::test_main_client_directory_three_files_never_written` | **B1 闭环**：正控制先证明探针拦得住一次误写（`:424-427`，`assert touched` 再 `touched.clear()`），不是"零命中即通过"。残留见 §3 B1 行 |
| **M4-3** | 双通道鉴权 + 三级降级 + TLS 指纹（判据自身为手工 T5a/T5b） | ⚠️（判据即手工，不计缺陷） | `upstream/zcode/auth.py:104 行`、`main.py:195-211` | 无（账本未宣称已验，正确） | **上轮观察项仍在**：`main.py:206-211` "开了 `fingerprint` 但 curl_cffi 不可用 → 降级普通 httpx"**只 `logger.warning`**，按 §21.3 原则 1 属未告知用户的能力降级，且它直接决定 T5a 结果 |
| **M4-4** | ①归一化喂 fixture 可单测 ②**3012 熔断 / 额度耗尽回写 `ResourceState.status`，转发自动绕开** | **⚠️（②只做了一半）** | 3012 腿：`upstream/zcode/quota.py:326-414`（`CooldownManager` 墙上钟 + mtime 回读 + 原子写）、`ops/builtin/zcode_claim.py:100-122,125-137`、`api/admin.py:394-421`；额度腿：`core/resources.py:94-99`（`has_quota()` 进 `available()`） | `test_v2_circuit.py`（13 条，含 `::test_circuit_persists_wall_clock_not_monotonic` / `::test_risk_control_enters_circuit_and_benches_all_accounts` / `::test_snapshot_exposes_last_error_for_the_health_card`）、`test_int_v2_zcode_admin.py::test_bench_endpoint_global_scope_benches_all_zcode_resources` / `::test_overview_surfaces_circuit_reason` | **B2/B3 闭环**（撤 `_epoch_ms` → 该用例红，我复现 `1 failed`）。**B4 未闭环**：全仓**没有任何代码**在额度耗尽时写 `status`/`last_error`（`grep 额度耗尽` 只命中 docstring），而 §17 `tech-design.md:1264` 明文"**不必给 `available()` 加额度维度**" → 该偏离**没有出现在 §五 D1–D3 里** |
| **M5-0** | 子命令 `--help` + 退出码；`import` 冲突非 0 且不写盘 | ✅ | `cli_zcode.py:186-206`（3 选项 + `return 4`）、`:137-171`（`remove`） | `test_v2_cli_zcode.py::test_import_conflict_exits_4_and_writes_nothing` + `test_v2_cli.py::test_subcommand_help_exits_zero[zcode]` | `remove` 是 §19 清单外的第 5 子命令（上轮已判"轻微越界、可接受、**须回写 §19**"）→ 账本 §六仍写"新增面仅…1 个 CLI 子命令"，**§19 表格本身未回写**，下轮还会再打一遍 |
| **M5-1** | 四类结果 / 并发只领一次（双层互斥）/ 无代理降级 `failed` 且不影响转发 / `failed` 可读 | ✅ | `ops/runner.py:98-244`（`AccountLocks` 5 个静默条件）、`:247-271`（`PlanLock`）、`:332-420`（`run_once` 含产品过滤 + 空跑判定后置）、`api/admin.py:121` | `test_v2_ops.py::test_run_once_classifies_all_four_categories` / `::test_account_lock_prevents_double_claim` / `::test_plan_lock_blocks_another_process` / `::test_all_lock_dirs_unwritable_denies_instead_of_granting` / `::test_all_accounts_filtered_out_counts_as_no_participants`；`test_int_v2_ops_isolation.py::test_ops_failure_does_not_touch_model_forwarding`；`test_v2_captcha.py::test_no_proxy_raises_with_proxy_hint` | §16.4「能力声明」这一条本轮才真正成为判据（`run_once:367-379`）。IX-S-1（配好代理仍谎称未配）已修：求解器恒接（`zcode_claim.py:140-151`）+ "为什么不可用"由求解器说 |
| **M5-2** | `GET /admin/api/zcode/quota` 接口断言；不做对外端点 | ✅ | `api/admin.py:325-352` | `test_int_v2_zcode_admin.py::test_quota_endpoint_returns_shape` / `::test_quota_aggregates_across_accounts` / `::test_quota_is_not_exposed_on_v1` | §20 边界守住。**但**该端点每次请求做**两遍**全账号日志尾读且**无节流**（`:343-348` + `_zcode_quota_of`）→ 与 D1 的理由正面冲突，见 §4.1 |
| **M5-3** | 并发单测断言不超发 | ✅（附 §17 触发点② 未接） | `core/resources.py:159-165,188,197`（同 rid 共享 `QuotaPool`）、`:219-252`（预留与 `in_flight+1` 同段）、`:304-334`（reserve/settle/release 各 1 单位）、`core/scheduler.py:450,465,624,726` | `test_v2_quota_reservation.py::test_two_mappings_of_one_credential_share_a_single_quota_pool` / `::test_concurrent_two_mappings_cannot_double_spend` / `::test_reserve_settle_release_are_symmetric` / `::test_stale_snapshot_cannot_resurrect_spent_quota`；`test_int_v2_quota_reserve.py::test_exhausted_quota_does_not_take_more_requests` | **eng S-1 真闭环**：我把 `_pool_for` 退回调调即新建 → `3 failed`（含并发双花那条）。预留撤真 → `9 failed`（文档称 8，我的撤法更宽，方向一致） |

**§19 汇总**：✅ **9** 行（M3-1 / M3-2 / M3-3 / M3-4 / M3-5 / M4-1 / M4-2 / M5-0 / M5-1 / M5-2 / M5-3 —— 11 行了，M3-0 与 M4-3、M4-4 另计）· **⚠️ 3** 行（**M3-0** 字面判据本机不可执行 / **M4-3** 判据自身手工 + 降级未告知 / **M4-4** 额度腿无实现且未列偏离）· ❌ 0 行。
账本 §六 那句"M3-0…M5-3 **全部有实现 + 有可复跑测试**"在 M4-4 的"额度耗尽"子句上**不成立**。

---

## 3. 第二轮阻塞项闭环表（我上一轮的 B1–B6）

| # | 上轮要求（§7 放行条件最小动作） | 本轮状态 | 证据 |
|---|---|---|---|
| **B1** | M4-2③ 不能由"重定向不生效"的代理用例声明：改拦 `Path.home()` 或降级为手工 | **✅ RESOLVED** | `tests/unit/test_v2_zcode.py:370-438`：monkeypatch `Path.write_text/write_bytes` + `os.replace` + `os.open`（写标志），命中即 `AssertionError`；**正控制** `:424-427` 先写一次主目录证明探针有效（`assert touched` 后 `touched.clear()`），再跑真实导入链路并断 `touched == []` + 三件字节未变。**"能红的护栏"这一条成立**（我这三轮第一次见到）。残留（不阻断）：①正控制只验了 4 个被拦通道里的 1 个（`write_text`）；②**内置 `open()` 与 `shutil.*` 写入未纳管**——当前 zcode 包内实写只用 `Path.write_text`（`dataroot.py:57`、`store.py:202,204`）与 `os.replace`（`quota.py:371`），故今日无漏；③`:381-386` 造的 `setting.json` 只作对照未断言（与 §15.3 已知例外一致） |
| **B2** | §17「3012 熔断状态落盘」接进生产，或删掉并记偏离 | **✅ RESOLVED** | `quota.py:326-414` 墙上钟（`_epoch_ms:296-303` 专门解释为何不能用 monotonic）+ `_load()` mtime 回读（跨进程）+ `get_circuit()` 单例；`zcode_claim.py:115 enter()` / `:125-137 _circuit_gate` / `:172-176 节流`；CLI 腿经 `admin.py:394-421 scope=global`。**反证我复现**：`_epoch_ms` 换回 monotonic → `test_circuit_persists_wall_clock_not_monotonic` **1 failed** |
| **B3** | 熔断原因可见：`snapshot_by_resource()` 带出 `last_error` + 总览补列 | **✅ RESOLVED（附字面差）** | `core/resources.py:102-116 _worst_error` + `:391-392` 字段；前端 `web/static/js/pages/dashboard.js resourceHealthTable()`（可执行函数，被 `verify_v2_frontend.mjs` 抽取真渲染）；用例 `test_v2_circuit.py::test_snapshot_exposes_last_error_for_the_health_card`、`test_int_v2_zcode_admin.py::test_overview_surfaces_circuit_reason`，前端断言明确要求**出现在 `<td>` 里**（不接受只在 `title`）。字面差：§17 `tech-design.md:1271` 要求串内含「至 HH:MM」，实现用「（30min，全局）」+ 独立「冷却剩余」列（信息等价且更实时，可接受，但应记为字面偏离） |
| **B4** | §5 补齐未披露偏离（`available()` 加维度 / 非全局 / 额度不回写 status）+ 决定额度可见出口 | **⚠️ PARTIAL → 计入 BL-4** | 已修：全局熔断（`bench_all_zcode`）、`last_error` 可见。未修：①§五 **只披露 D1–D3，`available()` 加额度维度这条仍在**（`tech-design.md:1264` 明文禁止）；②**额度耗尽从不回写 `status`、从不写 `last_error`**（全仓 `额度耗尽` 仅命中 docstring `quota.py:17,437,507`）→ 余量为 0 的资源在总览健康表**仍显示 `active`**（`resources.py:369-378` 聚合只看 `status`），用户看不到"为什么这条不派活"；③`query_balance` 接了 tick（`main.py:117-122`），但其结论只进 `ops-results-*.jsonl`，界面零消费者（§20 #12 允许二期，故只算偏离未披露，不算越界）；④`quota_view()`（`resources.py:336-339`）生产零调用 |
| **B5** | ①类文案加"已隐藏" + `test_int_v2_servable.py` 加一条断言锁定 | **⚠️ PARTIAL → 计入 BL-5** | 文案已加（`main.py:247-251`，实跑横幅可见）。**锁定未做**：`test_int_v2_capabilities.py:192-204` 与 `:228-241` 只断 `"503" in msg`，**没有任何 pytest 断言"已隐藏"字样**。我实跑反证：运行时把①文案里的"已从 /v1/models 与 mgw setup 隐藏（调用将返回 503）"替换掉 → `tests/integration/test_int_v2_capabilities.py + test_int_v2_servable.py + test_v2_servable.py` **39 passed 全绿**。唯一锁在 602 之外的 `verify_v2_frontend.mjs`。**且新文案指错页**（BL-3） |
| **B6** | `prd.md:550`（及日志）加指向 Q28-③ 的修正句；`schemas.py`/`ir.py` 文档串同步四级序 | **⚠️ PARTIAL → 计入 BL-6** | 已做：FR-3.16 正文新增排序条 `prd.md:193`；变更日志 `prd.md:759` 已标"原文写…⚠️ 已被 v1.15/Q28-③ 回填为…"。**未做**：Q24-⑥ 条款正文 `docs/specs/prd.md:551` **逐字未改**，仍写「**优先级 = 工具调用传参 > 网关设置 > 模型厂商官方内置**」；`config/schemas.py:190` 与 `core/ir.py:59` 的 docstring 仍是旧三级序。账本 T11⑤ 声称"Q24-⑥ **正文**与 FR-3.16 互相排序（消掉冲突字面）" —— **正文没有消掉**，下一轮任何人按 `prd.md:551` 实现会做出相反排序 |

**闭环率**：B1/B2/B3 = 3 条真闭环（均附我复现的红）；B4/B5/B6 = 3 条 PARTIAL，全部转入本轮阻塞项。

---

## 4. 三处偏离的独立判断（§五 D1–D3）

### 4.1 D1「§17 额度刷新触发点② 未接」——**判定：未获批准的范围裁剪；理由是假设，且被本项目自身实现反驳**

**§17 自己的措辞**（`tech-design.md:1285-1293`）：

| 触发点 | 说明 |
|---|---|
| ① `ops/runner` 每个 tick 末尾 | 顺带刷新一次（串行 + 10s 节流 + 3012 熔断） |
| ② **模型转发成功后** | **按 30s 节流补刷**（对齐 `16` §⑨） |
| ③ 管理端点 | 支持手动触发 |

1. **"每次转发都读 4 MiB"不成立**：②的字面自带 30 s 节流，即 **≤2 次/分钟**，不是"挂在热路径上每次调"。账本与 `main.py:71-73` docstring 的表述把方案条款改写成了一条更贵的假条款。
2. **成本我实测了**（合成 4.05 MiB / 6261 条 `billing/balance` 日志，`MAX_LOG_SCAN=80` 会提前退出）：
   `quota.parse_log_tail()` 单次 **13.5 ms / 14.3 ms**；`read_account_snapshot` 命中最新一份即返回 → 约 14 ms/账号。
   即"太贵"的量级是 **十毫秒级、且已被节流**。
3. **更关键**：同一个"贵"读法他们**在自己的管理端点上做了两遍且没有节流** —— `api/admin.py:343-348`：
   先对每个账号 `_zcode_quota_of()`（尾读），再 `refresh_runtime_quotas()`（再尾读一遍）。
   一次管理端请求的开销 **> 60 s 内 ②被节流后允许的全部开销**。所以"代价过高"不是关于本代码库的事实，是**未被检验的口径**。
4. **他们对①的实现也未按字面做**：`query_balance`（tick 末尾那条腿）**不查熔断、不共享 10 s 节流**
   （闸门只在 `zcode_claim.claim()` 里，`zcode_claim.py:168-176`）。因为该通道只读本地日志、不碰上游 → **实质无害，但字面不符**，同样应记在偏离表里。

**结论**：不撤销判据、不要求立刻接；但必须**二选一**：(a) 按 §17 接上（他们自估"低成本：成功分支加一次节流调用"）；
或 (b) 把 §17 该行改为"仅 tick + 管理端点"并**请用户在 PRD/技术方案上确认**，同时修正 `main.py:71-73` 与本账本 D1 的成本陈述。
**并顺手修掉管理端点的双读 + 无节流**（那才是本文件里真正贵的那次读）。

### 4.2 D2「`EnumEntry.tool_call` 默认 `True`（§12.3 字面 `False`）」——**判定：不接受当前形态（→ BL-2）**

§12.3 的完整句子是：「`EnumEntry` 加 `tool_call: bool = False`（唯一净新增的**目录字段**）—— **按模型族给默认值，可按模型覆写**」。
"默认值取 True 还是 False"只是这条的**第一个词**；本轮的落地把后面两个约束整段丢掉了：

| 方案要求 | 现状（实测） |
|---|---|
| 按模型族给默认值 | `matcher.py:41 tool_call: bool = True`，**全 `BUILTIN_ENTRIES` 零条显式取值**（`grep -c "tool_call=" matcher.py = 0`）→ 该字段是**常量**，不含任何族信息；`endpoint="images"` 的模型也对外声明 `supportsToolCall: true`（TestClient 实跑：`{'id':'sensenova-u1-fast','endpoint':'images','supportsToolCall':True}`） |
| 可按模型覆写 | 三条路径全断：①`caps_overrides` 只处理 `thinkingLevelMap`/`thinkingFormat`（`capabilities.py:61-68`）；②目录里没有逐条取值；③**`load_enum_pool` 静默丢弃 YAML 的 `tool_call` 键**（`matcher.py:243-260` 逐字段构造，唯独没读 `item.get("tool_call")`）——实跑：YAML 写 `tool_call: False` → 加载回 `True`，同批 `context_window/reasoning/effort_levels/params_default` 全部正常 |

所以**这不是"选了一个不同的默认值"，而是"该能力位对全部模型都是同一条未经取证的声明，且用户无法纠正"**。
他们自己的论证（"False 会保留静默删 tools 的 bug"）我认可方向，但它只支持"目录里应显式取证并尽量给 True"，
不支持"常量 True + 无覆写口"。而"用户改了配置被静默丢弃"正是本轮 T11⑥ 为 `product` 专门修掉的那类缺陷
（`verify_v2_frontend.mjs:99` 原话："漏传会被后端默认成空 = 静默丢字段"）。
**关闭动作**：`load_enum_pool` 补 `tool_call=bool(item.get("tool_call", True))` + 一条断言（含"写 False 生效"）；
非 chat 族显式 `False`；并在 §12.3 或 §五 记明"默认 True 需配套覆写口"。

### 4.3 D3「Playwright 走 optional extra」——**判定：接受**

`pyproject.toml:23-27`（`captcha = ["playwright>=1.44"]` + 注释说明为何不进主依赖）；
缺失时 `captcha.py:246-251` 惰性导入失败 → `CaptchaUnavailable(PLAYWRIGHT_HINT)`，文案含**可执行安装命令**
+ `--manual` 出路（`test_v2_captcha.py::test_playwright_missing_hint_is_actionable`）。
不静默降级、不假装能跑、与 §20 #19（用户裁决走完整方案）和 §16.5 的硬依赖披露一致。**唯一附带要求**：见 §6.3 的 `aclose()` 收尾未做完整（属实现缺陷，不属偏离本身）。

---

## 5. 用户可见出口核对表（§21 四处出口 + 两类新告警）

| 出口 | 契约（§21.2） | 真实用户看得到？ | 看得到后能行动？ | 判定 |
|---|---|---|---|---|
| **①** 配置告警（现 4 类） | `overview.warnings[]` + 总览 `.alert-warn` 横幅 + 启动日志 | ✅ 实跑复现 4 条横幅（`ui_verify` 12/12）；每条各一横幅、空数组不渲染、非数组安全降级 | **⚠️ 一类指错页**：见 §5.1 | **⚠️（BL-3 / BL-5）** |
| **②** 运营 `failed` | JSONL + `mgw zcode claim` 打印 + 顶栏红点 | ✅ `admin.py:121 ops_failed_unread` + `main.js:94-124`（5 s 轮询、页面隐藏跳过、点击即 ack） | ✅ toast 文案与副作用一致（"重跑用 `mgw zcode claim`（未安装则 `python -m model_gateway.cli …`）"）并指到 `data/usage/ops-results-*.jsonl`；CLI 侧亦有 ack | ✅（**轻微字面差**：§16.6/§21 写 `data/ops-results-<date>.jsonl`，实现落 `data/usage/`；文案与现实自洽） |
| **③** 设备 ID 冲突 | CLI 3 显式选项 + 默认取消 + 退出码非 0 | ✅ `cli_zcode.py:203-208` | ✅ 三选项含各自后果说明；`rc=4` 且不写盘 | ✅ |
| **④** `mgw setup` | 写前打印解析路径并确认；`--dry-run` | ✅ `cli_setup.py:83-138`（目标目录 + 来源 + 判定依据 + 条数 + 确认/`--yes`/`--dry-run`） | **❌ 判定依据那一行会说谎**：见 §5.2 | **❌（BL-1）** |
| 新告警 `model_unservable` | 隐藏必须解释（Q28-②） | ✅ `main.py:263-279` | ✅ "到「模型资源」页启用对应资源（→ `resources.js:233` 组级 + `:447` 单 Key 开关，控件**确在该页**），或到「资源池设置」页更换映射（→ `models.js:351-358` 行内档位/移除，控件**确在该页**）"；点名模型（用例 `::test_invalid_credential_model_is_hidden_but_explained`） | ✅ |
| 新告警 `param_shadowed` | 不留静默（Q28-③） | ✅ `main.py:280-294` | ✅ 点名模型 + 两侧值（`参数卡 reasoning_effort=max 被资源级默认（资源「资源D」默认 low）覆盖`）+ 完整生效序 + "到「资源池设置」页清掉对应资源的推理默认"（**该页确实有该控件** `models.js:351`，选项含"不注入（厂商默认）"） | ✅（引用串写"PRD FR-3.16"，但四级序实为 Q28-③ 所加，FR-3.16 正文只有三级 → 轻微；另：「资源池设置」页参数卡头部 `models.js:306` 仍印"工具调用传参 > 此处网关设置 > 厂商内置"，与本页 `:319`"推理…在资源池行内按资源配置"自相矛盾 → 与 BL-6 同源） |

### 5.1 出口①的页面归属核查（BL-3）

告警① `main.py:247-251`：「…到**「资源池设置」页**选中该模型、在资源池里**添加资源映射**」。实测：

- 「资源池设置」= `pages/models.js`（`main.js:24` 的 `PAGE_META.models.title`）。该页资源池卡**只有**行内 effort / 上移 / 下移 / 移除映射（`models.js:343-358`），**没有"添加映射"控件**；
- 该页**自己两处**写着相反的话：`models.js:297`「新增 / 调整映射：**在「模型资源」页**编辑对应资源」、`models.js:361`「无资源…——到「模型资源」页编辑资源添加映射」；
- 添加映射的按钮在「模型资源」页：`resources.js:274 / :816 #rv-addmap「添加模型」`；
- 同一轮里 `cli_setup.py:116` 的同一建议**写的是正确的**「到「模型资源」页为它们添加映射」；
- 为什么护栏没发现：`verify_v2_frontend.mjs:47` 的断言是 `html.includes("「资源池设置」页")` —— **只验字符串存在，不验那一页有没有那个控件**（这正是"代理指标"的教科书形态）。
- 对比：第二轮我记录的①原文是「到「模型资源」页编辑资源添加映射」（**当时是对的**）。本轮为补"已隐藏"字样顺手把页面改错了 → **改文案时引入的回归**。

### 5.2 出口④（`mgw setup`）的运行态判定不可达（BL-1，本轮最严重）

因果链（每步都实测）：

1. `cli_setup.py:88-91`：无任何**启用**接入密钥 → 直接 `return 2`（"未配置任何启用的接入密钥"）。→ **setup 能继续的前提是"存在密钥"**；
2. `api/auth.py:42-59`：`/v1/*` 非豁免路径，`access_tokens` 非空时**必须**带 `Authorization/x-api-key`，否则 **401**；
3. `core/local_admin.py:49-62 admin_get()`：只发 `method="GET"`，**全仓该文件无 `Authorization` 字样**；
4. 实跑（TestClient，同进程 ASGI，零外网、零端口占用）：
   `GET /v1/models` 无头 → **`401 authentication_error`**；带 `Bearer mg-secret` → `200 ['m1']`；
5. → `cli_setup.py:97-105` 的 `live` **恒为 None** → `servable=None` → 退回纯配置判定，并打印
   「可服务模型判定依据：**本地配置（网关未运行，无法感知资源失效等运行态）**」——而网关**正在运行**；
6. 锁不锁得住？`test_v2_cli.py:195-213` 用 `monkeypatch.setattr(la,"admin_get", lambda *a,**k: {...})` **替换了失败的那一调用本身**，
   因此它验的是"如果 admin_get 成功，行为对不对"，**永远不可能发现 admin_get 在真实配置下必然失败**。
   另一条 `::test_setup_without_running_gateway_says_it_is_config_only` 断的是 `rc=0` + "网关未运行" —— 在"网关其实活着但拒了我们"时同样绿。
   → 结论：**T9 声称"两路径同判据"在真实用户配置下不成立**，且第 21 号契约（"输出不得对用户说谎"）被违反。

---

## 6. 新风险区探测结果（本轮指派 6 项）

### 6.1 `Resource.product` 有消费者吗？——**无行为消费者；其 docstring 描述的机制住在别处**

- 定义 `config/schemas.py:160-165`；派生判据 `runner.py:321-329 product_of_account()` 走的是
  `zstore.has_account(account)`（看账号目录里有没有 `meta.json`）+ `zstore.PRODUCT` 常量，**不读 `Resource.product`**；
  熔断→资源的反查走 `quota.py:484-500 resource_ids_of_account()`，按 `r.account == 账号名` 字符串匹配，**也不读它**。
- 全包 grep：`product` 的真实读者只有 `resources.js:513`（同组新增 Key 时把它抄过去）+ `config.example.yaml` + 测试。
  → 用户把 `product` 填/不填，**系统行为逐字节相同**（我据代码路径核对，未实跑双份配置）。
- **但它是 §14.2 `tech-design.md:1002` 明文要求的"阶段一保留列"**（Q27-⑤ 只做这一列），所以**判为"按方案交付"而非越界自创**。
  问题在**文档串**：`schemas.py:160-164` 声称"非空时…运营类动作按 `supported_products` 匹配参与方"，
  而真实匹配根本不看这一列 → **下一轮任何人按 docstring 实现都会以为改 `product` 就能开关运营**。
  同类：`Resource` 全部字段（我导出的 11 个：id/name/vendor/preset/access_mode/protocol/base_url/api_key/account/product/enabled）
  中，只有 `product` 无行为读者。**关闭动作**：docstring 改成"阶段一预留列，当前无判据消费者"，或把 `product_of_account` 改为优先读 `Resource.product`（二者择一，别继续互相指认）。

### 6.2 `query_balance` 是否只注册不使用？——**已被真实入口调用（G2 成立），但输出无用户面**

- 注册 `ops/builtin/__init__.py:21-26`；真实调用点 `main.py:109,117-122`（每个 ops tick 跑一遍，
  `run_once(operation=op_balance)` → `query_balance()` → `apply_snapshot_to_runtime()` → 写**共享池**）。
- 反证方向成立：`test_v2_ops.py::test_ops_tick_runs_both_registered_operations` 存在；账本称"摘掉 `query_balance` 即红"，我未复跑该反证（**未验证**）。
- 缺口：只有 cron 一条入口 —— `mgw zcode claim` 只跑 claim 动作（`cli_zcode.py:225`），管理端点无"只刷额度"触发；
  结果 detail（"已用 x/y 余 z"）只进 JSONL；界面零消费者（§20 #12 允许）。→ 记入 BL-4 的"B4 未闭环"，不单列。

### 6.3 `upstream/zcode/captcha.py`（342 行）——**账本对"未真机执行"是显式的；测试证明的是纪律与 harness，不是上游行为**

- **披露核查（通过）**：模块 docstring `:17-18`「⚠️ 未实测口径：真机能否过无痕、`client/configs` 字段时效…本机无法验证」；
  账本 §五 N1/N2 独立登记；C3 明确把上一轮"代码已就位"更正为"当时是**未实现**"。这三处**没有粉饰**。
- **测试证的是什么**：`FakePage/FakeBrowser` + 注入 `now/sleep` → 真跑了 `_run_browser` 的控制流（先 `goto(ORIGIN_URL)` 落同源、`set_content` 的 HTML 里必须含兜底 `sceneId`、事件解析、超时包装、TTL/宽限期/失败短熔断/串行锁）。
  这些都是**我们能控的部分**，判定有效。阿里云 SDK 是否真产出可用 param —— **不在测试射程内，且账本没声称**。
- **我新发现的两个真缺陷（账本未提）**：
  1. **Playwright driver 从不 `stop()`**：`captcha.py:254 pw = await async_playwright().start()` 的 `pw` 是 `launch()` 内局部变量，
     只把 browser 返回；`aclose()`（`:272-279`）只 `browser.close()` → 驱动进程（node）无人回收；
  2. **`CaptchaSolver.aclose()` 无任何测试**（`tests/` 里 `aclose` 只出现在 `_NoopClient`），而 §16.5 明写"退出时 `aclose()`"，
     且 `get_solver()`（`:330-336`）在 proxy/manual 变化时**直接重建单例、不关旧的**（旧浏览器对象失去唯一引用）；
     `main.py:324-328` 也只关当前 `_SOLVER`。→ 真机上大概率残留 chromium/node 进程（**未实测，标 未验证**）。
  3. 内部口径自相矛盾：`:14` 说"求解结果是**一次性**的短时效凭证"，而实现按 §16.5 要求缓存 45 s 并在多账号间复用 →
     若"一次性"为真，第二个账号必吃 `T002`；文案把它归为"网关会自动刷新重试"。属 N1 未实测项，但应写进风险表而不是留在注释里。

### 6.4 接线护栏重做（T10）——**方向正确、检测器真能红，但"全集"言过其实**

- 我独立复核检测器：`_referencing_files("bench_all_zcode") → [admin.py, zcode_claim.py]`（能找到），
  `→ []`（`quota_view`/`all_normal`/`clear`，确实判空）→ **不是空转护栏**；`_population()` 实测 **132 个符号 / 30 个模块**。
- **我自选样本导出的漏网（全部零生产引用，护栏看不见）**：
  | 类别 | 符号 | 说明 |
  |---|---|---|
  | 类方法（`_public_symbols` 只走 `tree.body`，方法整体不在射程） | `ResourceManager.quota_view`（`resources.py:336`） | 自称"资源健康卡/诊断用"，健康卡实际不调它 |
  | | `OpReport.all_normal`（`ops/base.py`） | 无调用者（CLI 自己判 `report.failed`） |
  | | `CooldownManager.clear`（`quota.py:387`） | **无手工解除熔断的出口**：误判 3012 只能等 30 min 或手删 `circuit.json`（§21 原则 3 的"知道怎么办"没填） |
  | 模块级常量（`ast.Assign` 不纳入） | `ACCOUNT_PRODUCTS`（`ops/builtin/__init__.py:30`） | 唯一引用在 `test_v2_ops.py:638` —— **只被测试用的"生产常量"** |
  | 未纳入清单的模块（**`main.py` 不在 `V2_MODULES`**，包内 56 模块只覆盖 30） | `config/loader.py::save_config`、`core/errors.py::wrap_httpx_error` | 全包零引用（M1/M2 存量，不属 v2.0 范围，仅登记） |
- 另：上一版"手挑 12 符号"护栏**并未删除**，仍与新护栏并存（`test_v2_cli_zcode.py:132-160`），两份手挑映射表会各自漂移。
- **判定**：C1 的更正**方向诚实**（确实从手挑改成了 AST 自动导出，并加了逐调用方钉死 + 白名单过期），
  但"**自动导出全集**"这一表述**超出证据**：它导出的是"30 个模块的模块级函数与类"，而它点名承认漏掉的正是**类方法**这一类。

### 6.5 `core/paths.py` 对已验收 M1/M2 行为的影响——**大方向是修 bug，两处需登记**

- ✅ **变好的**：`MG_CONFIG` 现在被 `load_config()` 尊重（`config/loader.py:38` 走 `resolve_config_path`）；
  单实例锁 / 运营锁 / 枚举 / 方言 / usage 全部绝对化（`main.py:49-60`）。
  锁的 cwd 无关性有**真子进程**用例：`test_int_system_proc.py::test_int_44b_lock_is_cwd_independent`（两个 cwd、同 `MG_CONFIG` → 第二个 `rc=3` + "已有实例运行中"）。
- ⚠️ **行为变更 1（窄场景）**：锁的位置从"固定 `data/`"变成"**生效配置的父目录**"（`paths.data_dir()`）。
  两份不同 `MG_CONFIG`（不同目录）+ **同一端口**时，两把锁互不相干 → 第二个实例不再收到"已有实例运行中 / rc=3"，
  而是走到 uvicorn 绑定失败。旧实现（`git show HEAD:main.py:49`）是 `Path("data")/gateway.lock`，同 cwd 下两份配置**共用一把锁**。
  建议：锁 payload 里**已经存了 port**（`instance_lock.py:57`）→ 加一次端口维度的复核即可。
- ⚠️ **行为变更 2**：设 `MG_CONFIG=/elsewhere/c.yaml` 后，`usage/`、`dialects.json`、`ops-results-*.jsonl`、`gateway.lock`
  全部迁到 `/elsewhere/`（AGENTS/PRD 均写"运行时数据 `data/`"）。界面读的是 `runtime.usage_dir`，自洽；
  但**历史数据会在新位置"凭空不见"**。`paths.py:45-51` 说明了规则，**账本与 README 未提示这条迁移后果**（未验证用户侧观感）。
- ⚠️ **残留**：`ops/runner.py:425` 的兜底 `Path("data") / "usage"` 与 `config/loader.py:25 DEFAULT_CONFIG_PATH` 仍是 cwd 相对
  （生产路径都显式传参/走 `resolve_config_path`，故当前不触发；但 T7 的"全部数据路径经 paths 解析"这句话字面未做完）。
- ⚠️ `store.DEFAULT_ACCOUNTS_ROOT`、`main.{USAGE_DIR,ENUMS_PATH,DIALECTS_PATH,LOCK_PATH}` 均为 **import 期求值**，
  与 `ops_lock_dir()` 刻意"调用期解析"不一致（同进程改环境变量不生效）。CLI 每次新进程 → 无实际影响。

### 6.6 其他（顺手登记，不阻断）

- `ops/runner.py:_HELD_BY_US` 键含锁目录 ✓；`LOCK_WRITE_GRACE_S`/`LOCK_MAX_AGE_S`/令牌双条件 release 均有对应用例。
- `cli_setup.py:100` 用 `str(id).split(":")[-1]` 反剥前缀：若系统模型名本身含 `:` 会截错（当前命名规则下不发生）。
- 熔断文件 `store.accounts_root().parent/circuit.json` 与 docstring `quota.py:333` 写的 `data/upstream/zcode/circuit.json`
  在默认根下一致 ✓（未实跑跨进程双 CLI 竞争，标 未验证）。

---

## 7. 复跑数字对照（命令逐字照抄，差异逐项列出）

| 项 | 账本声称 | 我实测 | 结论 |
|---|---|---|---|
| 全量回归 | `602 passed, 452 warnings in 80.02s` | `602 passed, 452 warnings in 80.27s (0:01:20)`（`--basetemp=/tmp/pm3-pytest`） | **逐字吻合** |
| `unit/test_v2_ops.py` | 61 | **61** | ✓ |
| `unit/test_v2_quota_reservation.py` | 21 | **21** | ✓ |
| `unit/test_v2_captcha.py` | 12 | **12** | ✓ |
| `unit/test_v2_circuit.py` | 13 | **13** | ✓ |
| `unit/test_v2_wiring_guard.py` | 4 | **4** | ✓ |
| `unit/test_v2_servable.py` | 14 | **14** | ✓ |
| `unit/test_v2_cli.py` | 19 | **19** | ✓ |
| （附带自加）`test_v2_cli_zcode.py` / `test_config.py` / `test_v2_claim_wiring.py` / `test_v2_zcode.py` | 20 / 28 / 10 / 37 | **20 / 28 / 10 / 37** | ✓ |
| （附带自加）`test_int_chat.py` / `int_v2_servable` / `int_v2_zcode_admin` / `int_v2_quota_reserve` / `int_v2_ops_isolation` | 24 / 7 / 13 / 4 / 1 | **24 / 7 / 13 / 4 / 1** | ✓ |
| `scripts/ui_verify_v2_visible.py` | 后端 12/12 + 前端 35/35，exit=0 | **12/12 + 35/35，`exit=0`**（横幅/资源表/字段继承/红点四组全绿） | ✓ |
| §四 括注的 4 条"新增断言" | td 单元格 / "重跑领取"非"查看" / **"剩余时间"不得显示 0s** / 两条隐藏告警 | 前两条与第四条存在；**"不得显示 0s" 这一条在 `verify_v2_frontend.mjs` 与 `ui_verify_v2_visible.py` 中 grep `0s`、`剩余时间` 均零命中** | **✗ 一项无对应断言**（他们自己在 C4 立的规矩"计数须抄自跑出的输出"，这条没抄） |
| 轨迹基线 | 537（第二轮收账）→ 602（+65，零回归） | 第二轮我本人复跑 = **537 passed** ✓；本轮 602 ✓；**"零回归"我只能证成"602 全绿"**，无法证成"没有用例被删/改弱"（`docs/` 与 `.gitignore` 之外无提交基线，工作树全部未提交） | 部分可核 |
| T4 反证 | 换 monotonic → 红 | `test_v2_circuit.py::test_circuit_persists_wall_clock_not_monotonic` **1 failed** | ✓ |
| T1/T2 反证 | 撤预留 → 8 failed | 我的撤法（`reserve_quota` 恒真）→ **9 failed**（含端到端 `test_exhausted_quota_does_not_take_more_requests`）；`_pool_for` 退回调即新建 → **3 failed** | 方向 ✓，数字随撤法而变（已写明撤法） |
| `file:line` 抽查（10 处） | — | 准：`resources.py:32`（QuotaPool）、`resources.py:282-302`（set_quota）、`resources.py:106`（_worst_error）、`resources.js:233`（rv-toggle）、`admin.py:394-421`（差 9 行）。**偏**：T4 写 `quota.py:206-330` → 实 `326-414`（**差约 120 行**）；T6 写 `zcode_claim.py:60-75` → 实 `140-151`（**差 80 行**）；T1 写 `:172,178 / :186-191` → 实 `188,197 / 205-209`；T4 写 `zcode_claim.py:90-113` → 实 `100-122` | **✗ 4/10  materially 偏**（不是造假，代码都在，但铁律 2 要求可指认的行号；疑为文件增长后未回抄） |

---

## 8. 阻塞项清单与放行条件（全部关闭即可转"通过"）

| # | 严重度 | 阻塞项 | 最小关闭动作 | 成本 |
|---|---|---|---|---|
| **BL-1** | 🔴 严重 | `mgw setup` 的"运行态优先"（T9 / Q28-② 路径 A / §21 出口④）**在 setup 能执行的任何配置下都不可达**（`/v1/models` 需密钥，`admin_get` 不带），且失败时打印"网关未运行"**对用户陈述不实**；锁定用例把 `admin_get` 本身打桩 | `admin_get` 支持并传 `Authorization: Bearer <tokens[0].value>`；把"未运行"与"被拒/401"两种原因分开打印；**一条不桩 `admin_get`、走真实鉴权中间件的用例**（TestClient 即可，零外网） | 低 |
| **BL-2** | 中等 | `supportsToolCall` 无按族取值 + 无覆写口 + **`load_enum_pool` 静默丢弃 YAML 的 `tool_call`**（实跑 False→True）；images 族也声明支持工具调用 | `matcher.py:243-260` 补读 `tool_call`（默认 True）+ 断言"写 False 生效"；非 chat 族显式 `False` 或在 §12.3 记"全族为真"的依据 | 低 |
| **BL-3** | 中等 | 告警①指路指到**没有该控件的页面**（「资源池设置」无"添加映射"；该页自述"到「模型资源」页"）；护栏只验字符串存在 | `main.py:250` 改回「模型资源」页（与 `cli_setup.py:116` 同口径）；把 mjs 断言升级为"页面↔控件归属"表（每类告警的去处页必须能指到真实 id/按钮） | 极低 |
| **BL-4** | 中等 | 第二轮 B4 未闭环：额度耗尽**从不回写 `status`/`last_error`**，余量为 0 的资源在总览仍显示 `active` 且无原因；该 §17 偏离（`available()` 加维度）**未写进 §五** | 在 `set_quota(remaining=0)` 或 tick 结算处出一次 `bench + last_error="ZCode 额度耗尽"`（§17 字面），**或**在 §五 D 表补第 4 条偏离并请用户确认；二者都要给"额度已 0"一个用户可见出口（第⑤类告警 或 健康表一列） | 中 |
| **BL-5** | 中等 | Q28-②"已隐藏"这句话**没有任何 pytest 锁**：运行时删掉该字样 → 相关 **39 passed** 全绿，锁在未纳入 602 的 `.mjs` | 在 `test_int_v2_capabilities.py::test_warning_for_enabled_model_without_resource` 补 `assert "隐藏" in msg`（一行） | 极低 |
| **BL-6** | 中等 | 第二轮 B6 未闭环：`prd.md:551`（Q24-⑥ 条款正文）与 `schemas.py:190`、`ir.py:59` 仍是旧三级序；账本 T11⑤ 声称"正文已消掉冲突字面" | `prd.md:551` 加一句指向 Q28-③；两处 docstring 改四级序；`models.js:306` 参数卡头部的旧序一并改 | 极低 |
| **BL-7** | 中等 | D1 是**未经批准的 §17 条款裁剪**，且理由（"每次转发 4 MiB 太贵"）经实测不成立（**14 ms/次、条款自带 30 s 节流**），反被自家 `GET /admin/api/zcode/quota` 的"每请求两遍无节流尾读"反驳（`admin.py:343-348`） | 接上②（自估低成本）**或**按 §17 修订流程取得用户确认并改正 `main.py:71-73` 与本账本的成本陈述；同时给管理端点加节流/复用快照 | 低-中 |

> **不阻断但必须登记**（建议直接进 pitfalls）：护栏"全集"实为 30/56 模块的模块级定义（方法/常量不在内，
> 3 个零引用公开方法为实证）；`pw.stop()` 缺失 + `aclose()` 无测试；熔断无手工解除出口；4/10 抽查 `file:line` 漂移；
> §四"0s 断言"不存在；`runner.py:425` 的 cwd 相对兜底；锁位置随配置目录迁移导致"两份配置同端口"时单实例话术退化、
> 历史数据在新目录"看不见"；`ops-results` 落 `data/usage/` 与 §21 字面差；`param_shadowed` 串引 FR-3.16（实为 Q28-③）；
> M4-3 的 curl_cffi 降级仍只进日志；`mgw zcode remove` 仍未回写 §19 M5-0；真实浏览器渲染**未做**（本机 headless Chrome 加载真页会挂，账本 §五 已如实标注）；
> `:8300` 上旧实例未重启 → 本轮全部界面改动在真实浏览器上**尚未生效**（账本 §五 已声明，且"是否重启"须由用户指示）。

---

## 9. 诚实声明：我实跑了什么 / 只读了什么 / 我改了什么

**我改动了什么**：**仓库零改动**。全部反证用 `PYTHONPATH` 注入 `/tmp/pm3plug/*.py` 插件在**运行时**替换实现，
测试结束即消失；未新增/修改/删除任何 `model_gateway/`、`tests/`、`scripts/`、`docs/specs/`、账本文件。
证据（写本报告之后采集）：

```
$ git diff --stat | tail -3
 tests/integration/test_int_system_proc.py          |  35 +-
 tests/unit/test_config.py                          |  38 ++
 26 files changed, 2241 insertions(+), 101 deletions(-)   ← 全部为开发者的既有工作树改动，本轮未增加一项
$ ls -la docs/changes/reviews/ | grep PM-accept-3
-rw-r--r--@ 1 w staff 48752 Sep 27 15:49 PM-accept-3.md   ← 本文件（344 行；采集于最后一次编辑前，自引用会略变）
                                                          该目录唯一新增项，其余 6 份 mtime 未变
$ shasum -a 256 data/config.yaml data/gateway.lock
0613f42874ea60261337573a3cf33fcc92e10b5df2011042b91df302fe914c4e  data/config.yaml   （mtime Sep 24 22:48，只读未写）
857977d1c251710d0359ef69da94a19bbfb7590c3c98f49e34570c66e4bbb605  data/gateway.lock  （mtime Sep 22 20:53，只读未写）
```
未触 `~/.zcode`、`~/.workbuddy`、`~/.workbuddy-ai`；未发任何真实外网请求；未重启 `:8300` 实例。
（`data/gateway.log` 持续增大是**那个旧实例自己在写**，与本会话无关。）

**实跑（命令 + 输出）**

1. `cd /Users/w/Desktop/Model-Gateway && .venv/bin/python -m pytest -q --basetemp=/tmp/pm3-pytest` → **`602 passed, 452 warnings in 80.27s`**。
2. 16 个文件的 `--collect-only | grep -c '::'` 全表（§7），逐项与账本 §四 吻合。
3. `.venv/bin/python scripts/ui_verify_v2_visible.py; echo exit=$?` → **12/12 + 35/35，`exit=0`**（全文输出已抄录进本报告 §5/§7）。
4. 反证 4 组（全部运行时注入，见 §3/§4/§5/§7）：quota 共享池 `3 failed` / 预留闸门 `9 failed` / 熔断墙上钟 `1 failed` / **①文案删字 → `39 passed`（无红）**。
5. 鉴权实测（TestClient，同进程 ASGI）：`GET /v1/models` 无头 → `401`；带 key → `200 ['m1']`；`grep Authorization model_gateway/core/local_admin.py` → **零命中**。
6. 能力位实测：`endpoint=images` 的 `sensenova-u1-fast` → `supportsToolCall: True`。
7. YAML 覆写实测：`model-enums.yaml` 写 `tool_call: False` → `load_enum_pool(...).tool_call == True`（同批 `context_window/reasoning/effort_levels/params_default` 正常）。
8. 成本实测：合成 4.05 MiB / 6261 条日志 → `parse_log_tail` **13.5 ms / 14.3 ms** 两次。
9. 护栏自窥：`_population()` = **132 符号 / 30 模块**；`main.py` 不在清单；`quota_view`/`all_normal`/`clear`/`save_config` **零引用可测出**。
10. `file:line` 抽查 10 处（§7 末行），4 处 materially 偏。

**只读、未实跑（一律 未验证，不作为放行依据）**

- 第二轮基线"537 → 602 零回归"中的"**零回归**"：工作树全部未提交、`docs/` 被 `.gitignore` 排除 → 无 diff 基线可比，我只能证"602 全绿"。
- §19 手工项 **T1–T10** 与本轮新增 **N1–N5**：真实凭据 / 联网 / 住宅代理 / Playwright 真机 / WorkBuddy CLI 实测 —— **全部未触**（账本也未宣称）。
- `mgw` 命令名字面判据（本机未 `pip install -e .`）。
- 真实浏览器（Chrome）内的渲染与样式（前端 35 项 = Node 侧抽取真实源码函数 + DOM 结构断言，**不等于浏览器实测**）。
- Playwright driver/浏览器进程残留、`aclose()` 行为、验证码"一次性 vs 45 s 复用"的实际后果 —— 推断自代码，**未验证**。
- `circuit.json` 的**跨进程双 CLI 竞争**（只核到"按 mtime 回读"的代码与单实例跨重启用例）。
- 账本对另两份报告（eng / IX）结论的转述：我核对过 —— **eng 不通过（2 严重）· IX 有条件通过（1 严重）· PM 有条件（6 阻塞）**，三份原文与之一致，**未失实**。

**结论重申：不通过；阻塞项 7 个（BL-1 严重，BL-2…BL-7 中等）。**
B1/B2/B3 真闭环（均附我复现的红），这一点请记账；本轮新增的 7 条里有 5 条是"机制在、锁不在 / 文案在、归属不在 / 偏离在、账上不在"，
与第二轮同一形态，因此按同一口径不降级。
