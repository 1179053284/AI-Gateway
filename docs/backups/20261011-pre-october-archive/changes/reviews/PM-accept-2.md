# PM 实现验收报告 · 第二轮（tech-design v2.0 §12–§21 / M3–M5 · R1–R7 + BUG-1/2 复核）

> 角色：资深产品经理（**实现验收**，非设计评审）
> 验收对象：`docs/specs/tech-design.md` v2.0 §19 交付判据 + §20 不做清单 + §21 用户可见出口契约；
> `docs/specs/prd.md` **v1.15**（Q25/Q26/Q27/**Q28**）；被审账本 `docs/changes/e2e-records/E2E-20260927-v2-round2-fixes.md`
> 方法：**对抗式核查**——默认证据文档为假，直到代码/实跑推翻。只读，未改动任何源码/测试/spec。
> 日期：2026-09-27
> 上游：`docs/changes/reviews/{PM,eng,ix}-accept.md`（09-26，PM 结论=有条件通过 3 项阻塞）

---

## 1. 验收结论

# **有条件通过（Conditional Pass）**

**不是我"放水"，也不是它没做**：本轮的**工程实质是真的**——537 条测试我原样复跑通过、两条反证我都用等价撤法复现出红、
`/v1/models` 过滤与跨进程锁都是真实现而非声明。R1/R2/R4/R5/R6 可判**已交付**。

但它**再次**在两个老问题上失守，且这次的形态比上轮更隐蔽：**把"机制齐了"写成"判据达成"、把"代理指标"写成"实测"**。
我判定 **6 项阻塞（均为中等，无严重级）**，全部是"判据声称达成、实际由代理支撑或出口缺失"，不是新功能缺失。

**不能无条件通过的理由（一句话版）**：§19 M4-2 的第三条判据由一条**重定向根本不生效**的用例撑着（撤掉回归它不会红）；
§17 明文要求的"3012 熔断状态落盘"对应的 `CooldownManager` **至今零生产调用点**——这正是 R7 自己宣布"已清零"的那类缺陷，
而 R7 的 AST 护栏 12 个符号里**恰好没有它**；§17 承诺的"用户从总览『最近错误』列看到熔断原因"**不成立**（该列在本项目不存在，
`last_error` 全仓只写不读）；BUG-1 的"只过滤不解释"在**最常见形态（`resources: []`）上依然成立**。

> 放行条件（6 条，逐条见 §4）：B1–B6。全部为**中等**：不阻断 OpenAI 兼容网关日常转发（M1/M2 已验收面不受影响），
> 但**必须在下一次真实 ZCode 凭据接入（T1–T10 实测）之前关闭**，否则 §17/§19 的熔断与额度管控会在真实场景里以
> "用户看不见的原因"失效——那正是 §12.1 立项目标要消灭的形态。

---

## 2. §19 逐条核对表（M3-0 … M5-3，对照当前工作树）

| 阶段 | 判据（§19 原文摘要） | 结论 | 实现落点 `file:line` | 锁定用例（精确 id） | 我对证据文档的修正 |
|---|---|---|---|---|---|
| **M3-0** | `mgw --help` 退出码 0 | ✅* | `pyproject.toml:25-26`（`mgw = "model_gateway.cli:main"`）、`model_gateway/cli.py:71` | `tests/unit/test_v2_cli.py`（CLI 分发/退出码） | 文档称"实测 `mgw --help` rc=0"，**实为 `python -m model_gateway.cli` 代理**。本机 `.venv/bin/mgw` **不存在**，`model_gateway-0.1.0.dist-info` 内**无 `entry_points.txt`**（editable 安装早于 pyproject 改动）→ 字面判据**在本环境不可执行**。`README.zh-CN.md:85` 已诚实写明两种形态，故不判 ❌，但**"须重装 `pip install -e .` 才有 `mgw`"这一事实未见于证据文档** |
| **M3-1** | 告警进 `overview.warnings[]`（非仅日志）；两类措辞不同；`custom:` 前缀可解析 | ✅ | `api/admin.py:168`、`main.py:216-279`、`main.py:403`（同时打启动日志）、`enums/matcher.py:267-274` | `tests/integration/test_int_v2_capabilities.py`（含 `custom:` 前缀）、`scripts/ui_verify_v2_visible.py` 后端 9 项（我复跑 9/9） | 达成，且实际已有**四类**告警（超出判据，属 §21 出口① 的补强，非过度设计） |
| **M3-2** | `/v1/models` 键集合含 7 字段 + PRD Q25-② 字面回填 | ✅ | `api/openai_compat.py:60-67`、`core/capabilities.py` | `tests/integration/test_int_v2_capabilities.py:51-52`（逐键断言）、`tests/unit/test_v2_capabilities.py:52-75` | 回填**已落 PRD**：`docs/specs/prd.md:571-572`（camelCase + `caps.thinkingLevelMap`，并标"与实现/契约背离"的修正说明），历史原文保留于 `prd.md:757` |
| **M3-3** | 方言表落盘可断言；S1/S2/S3 注入假序列确定性验证 | ✅ | `core/dialects.py`、`probe.py`、`cli_probe.py:129-143` | `tests/unit/test_v2_probe.py:64-130`（含 `test_probe_rejects_fake_dialect_when_not_zeroed` = S2 单锚点） | 真实探测成功率按判据本身为手工，未验 |
| **M3-4** | `thinkingLevelMap` 7 键齐全、不支持显式 `null` | ✅ | `core/capabilities.py`（`build_caps_block`） | `tests/unit/test_v2_capabilities.py:79-109`、`tests/integration/test_int_v2_capabilities.py:99-110`（`len(...) == 7`） | — |
| **M3-5** | `mgw setup` 格式/合并/原子写可断言 | ✅ | `setup_tools.py:60,144`、`cli_setup.py:95-104` | `tests/unit/test_v2_setup.py:72-151`（裸数组拒绝/合并保留/备份/无 tmp 残留） | — |
| **M4-1** | 假 Anthropic 上游 ASGI 完成一次 chat | ✅ | `adapters/anthropic_out.py`（+608 行）、`adapters/__init__.py` | `tests/integration/test_int_v2_anthropic.py`（13 条，含 `test_html_response_cools_down_and_second_resource_takes_over`） | 证据文档"§18.1 空壳→实现"成立 |
| **M4-2** | ①设备 ID 冲突拒绝而非静默重生成 ②两账号凭据/遥测互不覆盖 ③**主 `~/.zcode/v2/` credentials/config/telemetry 三件未被写入** | **⚠️（③为代理指标）** | ①`upstream/zcode/dataroot.py:119,160` + `store.py:143` ②`store.py` 导入链路 | ①②：`tests/unit/test_v2_zcode.py::test_two_accounts_do_not_overwrite_each_other` / `test_reimport_of_one_account_leaves_the_other_intact`（逐字节，真） | ③由 `test_v2_zcode.py::test_main_client_directory_three_files_never_written` 支撑，但该用例靠 `monkeypatch.setenv("MGW_ZCODE_HOME", …)` 把"主目录"指到 tmp；**`MGW_ZCODE_HOME` 只被 `oauth.py:32 zcode_home()` 消费，而 `zcode_home()` 只出现在 `oauth.py:52 read_credentials(home=None)` 的默认参数（读）**；`DEFAULT_ZCODE_HOME = Path.home()/".zcode"/"v2"`（`oauth.py:25`）**在 import 期即求值**，测试期改环境变量对它无效。→ **写路径根本不经过该变量**：若将来出现硬编码写主目录的回归，此用例**不会变红**。文档注释"任何误写都会留在这里"（`tests/unit/test_v2_zcode.py:381`）**不成立** |
| **M4-3** | 双通道鉴权 + 三级降级 + TLS 指纹 → **判据本身为手工（T5a/T5b）** | ⚠️（与上轮同，未新增可测项） | `upstream/zcode/auth.py`、`adapters/anthropic_out.py:458,479`（`build_client`/`looks_like_jwt` 已接线）、`main.py:190-197` | 无（诚实标注 T5a/T5b 未测） | 新发现：`main.py:194-197` 的"已开 `fingerprint` 但 curl_cffi 不可用 → 降级为普通 httpx"**只 `logger.warning`**。按 §21.3 原则 1（写进日志 ≠ 用户看到），这是一个**未告知用户的静默能力降级**，且它恰好会导致 T5a 的 WAF 拦截 |
| **M4-4** | 额度归一化喂 fixture 可单测；**3012 熔断 / 额度耗尽回写 `ResourceState.status`，模型转发路径自动绕开** | **⚠️** | 回写：`quota.py:348-370 apply_to_resource` → `resources.py:204-207 bench`；绕开：`resources.py:75-76 available()`；接线：`ops/builtin/zcode_claim.py:85-108` | `tests/unit/test_v2_zcode_quota.py::test_bench_account_is_the_wiring_point` / `test_apply_to_resource_passes_seconds_to_bench`；额度侧 `tests/unit/test_v2_quota_reservation.py::test_quota_exhausted_makes_resource_unavailable` | **四处与 §17 明文不符，且未列入证据文档 §5「有意偏离」**：① §17 决策表「熔断…**状态落盘**（防重启丢失）」——`quota.py:286 CooldownManager` **零生产调用点**（我全仓 AST+文本双查：仅 `quota.py:286` 定义 + `tests/unit/test_v2_zcode_quota.py:162-204` 实例化）→ 重启即丢熔断；② §17「3012 → **全局**熔断 = 对全部 ZCode 账号一并回写，`last_error` 注明『全局熔断』」——实现只 bench **触发的那一个账号**（`quota.py:398 resource_ids_of_account`），原因串为 `zcode_claim.py:100 "ZCode 风控熔断（30min）"`，**无"全局"字样**；③ §17「额度耗尽时回写 `ResourceState.status`」——实现**不回写 status**，改走 `available()` 加额度维度，而 §17 原文明确「**这样不必给 `available()` 加额度维度**」（`tech-design.md:1264`）；④ §17 收益声明「总览资源健康卡『最近错误』列直接可见原因 → 无需改前端」**为伪**（见 B3） |
| **M5-0** | 子命令 `--help` + 退出码；**`import` 冲突返回非 0 且不写盘** | ✅ | `cli_zcode.py:186-206`（冲突打印 3 选项 + `return 4`）、`cli_zcode.py:137-171`（`remove`） | `tests/unit/test_v2_cli_zcode.py::test_import_conflict_exits_4_and_writes_nothing`（断 `rc==4` + 目录未落 + 三选项文案 + `list_accounts()` 仍 1 条）、`test_import_conflict_with_regenerate_succeeds` | 判据达成。`remove` 属新增面（见 §6 判定：轻微越界、可接受、须回写 §19） |
| **M5-1** | 四类结果分类；**并发触发只领一次（双层互斥）**；无住宅代理降级 `failed` 且转发不受影响；`failed` 从 `/admin/api/status` 可读 | ✅ | `ops/runner.py:62-147 AccountLocks`（文件锁 + `_HELD_BY_US`）、`runner.py:265-271`（账号锁）、`runner.py:316-322 bump_failed_counter`、`api/admin.py:121`、`claim.py:220`（无代理文案） | 分类 `tests/unit/test_v2_ops.py::test_run_once_classifies_all_four_categories` + `:45 test_business_code_classification`；互斥 `::test_account_lock_prevents_double_claim`（**真并发**：`create_task` × 2 + `asyncio.Event` 闸门，断 `entered == 1`）+ `::test_second_process_cannot_acquire_while_held`（**真实子进程**）；隔离 `tests/integration/test_int_v2_ops_isolation.py::test_ops_failure_does_not_touch_model_forwarding`；出口 `tests/integration/test_int_v2_zcode_admin.py::test_status_exposes_ops_failed_counter` | 四条判据都有真用例。上轮"1003/1005/网络错只有假 claim"的缺口由 `tests/unit/test_v2_claim_wiring.py` 补上（走生产 `claim()`） |
| **M5-2** | `GET /admin/api/zcode/quota` 接口断言；**不做对外端点** | ✅ | `api/admin.py:325-352` | `tests/integration/test_int_v2_zcode_admin.py::test_quota_endpoint_returns_shape` / `test_quota_aggregates_across_accounts` / `test_quota_is_not_exposed_on_v1`（后者正面守 §20「不做对外端点」） | §20 边界守住 |
| **M5-3** | **并发单测断言不超发** | ✅（含 1 处已披露偏离） | `core/resources.py:162-197 pick_and_acquire`（`:193 reserve_quota` 与 `:194 in_flight += 1` 同段）、`core/scheduler.py:365,450-451,464-466`（非流式 settled）+ `:574,624-625,725-726`（流式对称）；数据源 `quota.py:206,228,240-268` → `main.py:58-70 refresh_quotas` 由 `main.py:107`（启动）+ `main.py:110`（tick 末尾）+ `api/admin.py:348`（管理端点）三处调用 | `tests/unit/test_v2_quota_reservation.py::test_concurrent_reservations_do_not_oversubscribe`（`asyncio.gather` 10 worker / 额度 3 → 恰 3 拿到，`quota_reserved`/`in_flight` 归零）；端到端 `tests/integration/test_int_v2_quota_reserve.py::test_exhausted_quota_does_not_take_more_requests`（2×200 + 3×503） | **反证我复现了**（见 §5）。但证据文档所称"**462→537 零回归**"我复跑数字**完全吻合**；所称反证"**4 failed**"我用等价撤法得到 **8 failed**（文档少报，方向保守，结论成立） |

**§19 汇总**：✅ 9 行（M3-0\*/M3-1/M3-2/M3-3/M3-4/M3-5/M4-1/M5-0/M5-1/M5-2/M5-3）· ⚠️ 3 行（**M4-2 ③、M4-3、M4-4**）· ❌ 0 行。
（M4-3 的 ⚠️ 是判据自身规定的手工项，不计缺陷；M4-2/M4-4 的 ⚠️ 计入阻塞 B1/B2/B3/B4。）

---

## 3. R1–R7 + BUG-1/BUG-2 复核表

| 项 | 文档声称 | 我的核查 | 结论 |
|---|---|---|---|
| **R1** | `ops/builtin/zcode_claim.py:13` 补 `import json`；新建 10 条走生产 `claim()`；撤修复 → **10 failed** | 行号吻合（`zcode_claim.py:13`）。测试文件确为 10 条且**每条**都经 `accounts_root` fixture 写合法 `user_info`，必走 `_credentials_of` 的 `json.loads`（`zcode_claim.py:41`）。**反证我独立复现**：以 autouse fixture 在运行时 `del module.json`（等价撤修复、不改文件）跑该文件 → **`10 failed in 0.12s`** | ✅ **交付，反证成立** |
| **R2** | 熔断补第二条腿：`core/local_admin.py admin_post()` + `POST /admin/api/zcode/bench`（`admin.py:403-423`）+ 两腿分流 | `core/local_admin.py` 存在且只打 `http://127.0.0.1:<port>`（不外发，合铁律 1）；端点在 **`api/admin.py:393-425`（文档写 403-423，偏 10 行）**；`zcode_claim.py:100-108` 有 runtime→直改、`runtime=None`→`admin_post`；`cli_zcode.py:224` 确认 `run_once(...)` **仍不传 runtime**（这正是走第二条腿的前提）；`cli_zcode.py:258-266`、`cli_probe.py:133-140` 已收敛到同一 helper（不再各写一份 urllib）✓ | ✅ **交付**（引用行号偏差，实质无问题） |
| **R3** | 预留接进生产路径 + 三触发点 + 反证 4 failed；⚠️ 有意偏离 §17 触发点② | 见 §2 M5-3。偏离②在文档 §5.1 **已披露并给了恢复成本**，我认为**披露充分、理由成立**（4 MiB 尾读挂热路径） | ✅ 交付 / ⚠️ 但**另有 3 处未披露偏离**（§2 M4-4 ①②③）→ 计入 B2/B4 |
| **R4** | 锁落文件（pid 判活、陈旧回收）+ 进程级持有集 + 7 条跨进程用例 | `ops/runner.py:96-147`（`O_CREAT\|O_EXCL`、`_pid_alive`、`_read_pid` 容错、`_path` 正则消毒）；`_HELD_BY_US` 的引入理由（同进程第二个实例会把自家 pid 的锁当陈旧抢走）**成立且被 `runner.py:124-132 release` 的 pid 自校验兜住**；`tests/conftest.py` autouse 重定向 `MGW_OPS_LOCK_DIR` + 清空持有集 ✓；`test_account_lock_name_is_path_safe`/`test_corrupt_lock_file_is_reclaimed` 确在 | ✅ **交付**（这是本轮质量最高的一条） |
| **R5** | PRD 升 v1.15：Q25-②/① 字面回填 + §9 Q28 四项 + FR-5.1 补句 | 逐条命中：`prd.md:3`（版本行）/ `:567-568`（Q25-①「保留字段、砍界面」）/ `:571-572`（camelCase + `caps.thinkingLevelMap`，并写明是实现/契约背离的修正）/ `:205`（**确在 FR-5.1 段内**，`### FR-5` 起于 `:203`）/ `:722-749`（§9 Q28 四项）。历史原文保留 + 指向说明见 `:757` | ✅ **交付**（文档没吹，实际做了——这是我原本最怀疑的一条）。⚠️ **但同类回填漏了 Q24-⑥** → 见 §5 |
| **R6** | 判据缺测四行全部补齐 | 4 行用例名全部存在并核对：两账号互不覆盖/主目录三件（见 §2 M4-2，**③为代理**）/ `test_import_conflict_exits_4_and_writes_nothing` / `test_int_v2_ops_isolation.py`（运营失败 × 6 并发 chat 隔离） | ⚠️ **3/4 达成，1/4 是代理指标**（B1） |
| **R7** | 残余死代码"3 个"处置 + AST 护栏 12 符号 + 防长回来 | 三个符号的处置**与文档一致**：`auth.build_headers` 已接（`claim.py:81-83`，并加了 `app_version` 形参）；`oauth.refresh` + `TOKEN_URL` **已删**并在 `oauth.py:9` 记录去向；`store.delete_account` 接到 `mgw zcode remove`（`cli_zcode.py:137-171`，先打印绝对路径、非交互强制 `--yes`，我实跑 `remove nope --yes` → `✗ 账号『nope』不存在`、`rc=2`，与文档输出逐字一致）。AST 护栏确在（`tests/unit/test_v2_cli_zcode.py:132-145` 12 符号参数化） | ❌ **"残余死代码 3 个"这个完备性结论不成立**：`quota.py:286 CooldownManager`（含 `Cooldown`/`should_throttle`/`mark_called`，§17「状态落盘 + 10s 节流」的载体）**仍零生产调用点**，且**不在 12 符号护栏清单内**。这正是 R7 自己宣布清零的缺陷形态 → B2 |
| **BUG-1** | `/v1/models` 与 `mgw setup` 只下发可服务模型；单一判据源；**不允许只过滤不解释** | 判据源 ✓（`resources.py:79-106`，冷却中/额度 0 仍算可服务，与 Q28-② 一致）；路径 B ✓（`openai_compat.py:53-58`）；路径 A ✓（`cli_setup.py:92-99` + 打印"已跳过 N 个…"）；第③类告警 ✓（`main.py:246-258`）。**但**：告警③的触发条件写死为 `m.enabled and m.resources and …`（`main.py:250`），所以**"模型已启用但 `resources` 为空"这一形态只落入告警①**，而①的文案是「…调用将返回 503 —— 到『模型资源』页添加映射」，**完全不提该模型已从 `/v1/models` 隐藏**。**实跑取证**（TestClient 复现）：<br>`MODEL IDS: ['has-resource']` · `no-resource-model` 已被隐藏（Q1 True）· **横幅是否提到"隐藏"= False**（Q2）· 直调仍 503 `NO_RESOURCE`（Q3）。<br>→ 这恰是 Q25-⑧ 的**真实事故形态**（7 个系统模型 `resources: []`） | ⚠️ **机制交付、可见性不完整** → B5。另：无用例锁定"①+已隐藏"组合（`test_model_with_no_usable_resource_is_not_published` 只断 `not in ids`，不断横幅） |
| **BUG-2** | 不改优先级，按 FR-3.16 定序；出第④类告警 `param_shadowed`；定论归档 Q28-③ | 行为定序**有出站体级断言**（不是注释宣称）：`tests/integration/test_int_chat.py::test_reasoning_effort_priority_resource_default_over_params`（资源默认 `low` 赢过参数卡 `max`；请求级 `high` 又赢过资源默认）+ `test_int_chat.py:445`（无资源默认时参数卡生效）。告警④ `main.py:260-279 + _shadowed_params`（点名 模型/字段/`资源名→厂商模型` 映射，并写出生效序）。我另外验了**注入顺序不产生矛盾出站**：`scheduler.py:229 apply_model_params` 先写卡值、`:235 inject_reasoning_into_body` 后用合并值覆盖；显式 `thinking:disabled` 场景由 `ir.py:109` 的 `reasoning_effort:"none"` 配对归一化兜住 → **未发现新缺陷** | ✅ **交付**（判据链完整）。充分性问题见 §5 |

---

## 4. 新发现缺陷（本轮新出，附严重度与是否阻断）

> 严重度定义：**严重**=已验收行为被破坏或交付物不可用；**中等**=判据声称达成而实际由代理/缺出口支撑，须关闭后才可放行；**轻微**=准确性、可维护性、账本完整性。
> 对照 §20 不做清单逐条自查：以下 6 项**均不落在 §20 的任何"不做"条目内**，不是我拿设计稿要价。

| # | 严重度 | 阻断? | 缺陷 | `file:line` 证据 | 为什么阻断/不阻断 |
|---|---|---|---|---|---|
| **B1** | 中等 | **阻断 M4-2 判据** | §19 M4-2 第三条判据由**重定向无效**的用例支撑：`MGW_ZCODE_HOME` 只作用于 `oauth.zcode_home()`，而该函数只在 `read_credentials(home=None)` 的**读默认值**里被消费；`DEFAULT_ZCODE_HOME` 在 import 期已求值。写路径不经过它 → 真正的"误写主目录"回归**测不出来**（用例恒绿） | `oauth.py:25`、`oauth.py:32-35`、`oauth.py:52`；`tests/unit/test_v2_zcode.py:381`（注释"任何误写都会留在这里"为伪） | 判据本身（"三件未被写入"）我判断**行为大概率是对的**（全仓无任何写主目录的代码），但**判据被一条不能红的用例声明为已验证**——这是账本可信度问题，必须改写判据表述或换成 `monkeypatch` 拦 `Path.home()` 的真锁 |
| **B2** | 中等 | **阻断 M4-4** | §17「3012 熔断…**状态落盘**（防重启丢失）」**未落地**：`CooldownManager` 零生产调用点（10s 节流 `should_throttle`/`mark_called` 同样未接）。网关一重启，30 分钟熔断即丢，被风控账号立刻重新进入选路 | 定义 `quota.py:286-345`；引用面：全仓仅 `tests/unit/test_v2_zcode_quota.py:162,176,179,185,193,204`。§17 要求见 `tech-design.md:1249`（决策表「熔断」行）与 `:1266` | 与 R7 的完备性结论直接冲突（R7 称残余死代码 3 个并已清零 + 建了 12 符号 AST 护栏，护栏清单 `test_v2_cli_zcode.py:132-145` 独缺此类）。不阻断日常转发，阻断 ZCode 真实接入 |
| **B3** | 中等 | **阻断 §17/§21 出口** | 熔断**原因对用户不可见**：`state.last_error` 全仓**只写不读**——`snapshot_by_resource()` 输出字段（`rid/name/vendor/account/status/available/C/in_flight/cooldown_remaining_ms/models`）**不含 `last_error`**，总览资源健康表只有 4 列（资源/状态/连续失败/处理中），全站 JS 无 `last_error`/「最近错误」引用。§17 承诺「总览资源健康卡『最近错误』列直接可见原因 → **无需改前端**」**前提为伪**；`design-spec.md:193` 要求的「最近错误」列**不存在** | 写：`quota.py:367`、`resources.py:217`；读：**无**（`resources.py:269-304` 无该字段；`web/static/js/pages/dashboard.js` 表头 4 列）。方案依据 `tech-design.md:1271-1276`；设计稿 `docs/specs/design-spec.md:193` | 用户看到的是资源变 `cooldown` 而**不知道为什么**、要等多久（`cooldown_remaining_ms` 只在徽章 `title` 里）。这正是 §21.3 原则 1/3 的反例，也是 §12.1「消灭静默」的复发 |
| **B4** | 中等 | **阻断 §17 一致性** | 额度耗尽这条腿**没按 §17 写字面**：实现选择给 `available()` 加额度维度（`resources.py:69-76`）而**不回写 `status`**，而 §17 原文明确「**这样不必给 `available()` 加额度维度**」。后果：余量为 0 的资源在界面上**仍显示 `active`**，且 §21 四类告警里**没有"额度耗尽"这一类**——`/admin/api/zcode/quota` 的界面消费者按 §20 #12 属二期，所以首期**额度状态对用户完全不可见** | `resources.py:69-76,221-251`；`tech-design.md:1264`（"不必加维度"）；告警清单 `main.py:216-279`（仅 4 类，无额度类）；§20 #12 见 `tech-design.md:1423` | 功能上"不派活"是对的（保守闸门，方向正确），但**这是第三条未披露偏离**（文档 §5 只披露了触发点②一条）。验收须把它补进"有意偏离"并决定是否为额度耗尽出第 ⑤ 类告警 |
| **B5** | 中等 | **阻断 Q28-② 契约** | BUG-1 的"不允许只过滤不解释"对 `resources: []` 形态未满足（见 §3 BUG-1 实测取证）。同一份代码里，"有映射但全失效"走了③（含"已从 /v1/models 隐藏"字样），"根本没映射"走①（不含）→ **同一件事两种说法，且更常见的那种没说** | `main.py:234-244`（①文案）vs `main.py:246-258`（③文案，`:250` 条件排除空映射）；用例缺口 `tests/integration/test_int_v2_servable.py:35-45`（只断 `not in ids`） | Q28-② 原文（`prd.md:736`）「被隐藏模型必须出现在总览横幅…**不允许只过滤不解释**」是用户批准的硬约束；修一行文案 + 一条断言即可关闭 |
| **B6** | 中等 | **不阻断放行，阻断需求账本一致** | **需求回填只做了一半**：R5 以"字面与实现/契约背离"为由回填了 Q25-①/②，却**没有回填 Q24-⑥**——`prd.md:550` 与变更日志 `prd.md:758` 仍原文写「优先级 = **工具调用传参 > 网关设置 > 模型厂商官方内置**」，与 `prd.md:741` Q28-③ 的「请求级 > **资源级默认** > 参数卡」**并存且互斥**。源码文档串同病：`schemas.py:184`、`core/ir.py:58-60`（`apply_model_params` docstring 仍是 Q24 三级序） | 见左列行号 | 我**认可本轮的裁决本身**（理由见 §5），但既然本轮已确立"字面背离即修正"的标准，同一标准必须贯穿。**当前 PRD 有两处互相矛盾的优先级正文，下一轮任何人按 `prd.md:550` 实现都会做出相反的排序** |

---

## 5. 四个必答问题的直接回答

### Q2 R1–R7 + BUG-1/2 是否真交付？
见 §3 表。**结论**：R1/R2/R4/R5/R7（处置本体）/BUG-2 = **真交付**；R3 = 交付但有 3 条未披露偏离；R6 = 3/4；R7 = **完备性结论不实**（B2）；BUG-1 = **机制真、解释不完整**（B5）。
特别核的两点：① `/v1/models` 确实**排除了**不可服务模型（实跑 `MODEL IDS: ['has-resource']`，且 `test_int_v2_servable.py::test_invalid_credential_model_is_hidden_but_explained` + `cooldown 不隐藏` 双向都锁）——**排除动作不是静默的，但对"空映射"这一形态解释缺失**；② **PRD 回填（R5）逐行核到**，不是空承诺。

### Q3 §21 四处出口 + 两类新告警，真实用户能否看到、能否知道怎么办？

| 出口 | 我能验证的 | 判定 |
|---|---|---|
| ① 配置告警（现 4 类） | `/admin/api/overview.warnings[]`（`admin.py:168`）+ 总览页 `.alert-warn` 每条一横幅（`dashboard.js:71-80`，我复跑 `ui_verify_v2_visible.py` 前端 **18/18**）+ **同时**打启动日志（`main.py:403`，我的实跑输出里可见 `[配置告警] …`） | ✅ 用户看得到；②③④类文案含"到 XX 页"指路；①类文案缺"已隐藏"（B5） |
| ② 运营 `failed` | 落 `ops-results-<date>.jsonl`（`runner.py:296-312`）+ `mgw zcode claim` 分组打印 + 顶栏红点（`main.js:100`，5s 轮询复用既有 `/admin/api/status`）+ **点击即 ack 清零并 toast 告知去哪里看**（`main.js:111-116` → `admin.py:379-390`）+ CLI 侧 ack（`cli_zcode.py:250,254` → `admin_post`） | ✅ **本轮最完整的一条**：知道有失败、知道去哪看、知道怎么消 |
| ③ 设备 ID 冲突 | CLI 3 个显式选项 + 默认取消 + `rc=4`（`cli_zcode.py:193-206`），用例断到文案与"不写盘" | ✅ |
| ④ `mgw setup` | 写前打印目标目录+来源+确认、非交互须 `--yes`、`--dry-run`、备份/原子写/读回校验（`cli_setup.py:95-104` + `test_v2_setup.py:110-151`） | ✅ |
| 新增 ③`model_unservable` / ④`param_shadowed` | 都走出口①（横幅 + 启动日志双通道），文案各不相混（脚本断言 4 类措辞互异 ✓）。④说清生效序，但**串里引的是"PRD FR-3.16"**，而真正给出四级序的是 Q28-③（FR-3.16 正文根本没有参数卡这一层）——引用不精确，轻微 | ✅ 机制达成；不足：**只在总览呈现**，用户正在编辑参数卡的「资源池设置」页内**无任何就地提示**（§21 只要求横幅，故不判违约）；且 `last_error` 那条本该并入出口①的"为什么"仍缺失（B3） |

### Q4 Q15-vs-Q24 冲突的裁决是否站得住？`param_shadowed` 够不够？

**裁决本身我认可，但依据不是"两条款都不冲突"，而是"必须选一边"**：
- 对 **FR-3.16**：一致。FR-3.16 原文（`prd.md:43`、`:485`）只写「请求级 > 资源级 > 厂商默认」，**从未提模型参数卡**；把参数卡插在"资源级"与"厂商默认"之间，保留了 FR-3.16 的两端关系，属**补空**而非**翻案**。
- 对 **Q24-⑥**：**按字面不一致**。`prd.md:550` 写的是「工具调用传参 > **网关设置** > 模型厂商官方内置」三层，资源级默认根本不在其序列里；新序把"资源级默认"置于"网关设置(参数卡)"之上，**Q24-⑥ 的字面没有为这一点授权**。所以本轮做的是**填补两条 clause 的空隙，而不是"实现本来就对"**——证据文档 BUG-2 写"代码没有写错：它实现的正是 FR-3.16"这半句准确，但它据此**回避了 Q24-⑥ 字面被改这件事**，只靠 Q28-③ 归档兜底，而**没有把 Q28-③ 的结论回写进 Q24-⑥ 正文**（B6）。我依赖的具体行：**`docs/specs/prd.md:550`**（与 `:758` 变更日志同源表述）。
- **`param_shadowed` 够不够**：**机制够、位置不够**。够的一面：覆盖允许、静默不允许，点名到「模型 + `reasoning_effort`/`thinking` + `资源名→厂商模型`」（`main.py:260-279`），并写出生效序；范围也准（资源级默认只有推理维度能盖参数卡，其余键不可能被盖，所以不存在漏报）。不够的一面：① 用户**在改这个值的那一页看不见**（只进总览横幅）；② 告警只在 `config_warnings()` 被调用时（总览刷新/启动）算，**保存配置那一刻不反馈**；③ 引用串把定论来源写成 FR-3.16（见上）。三者都不构成违约（§21 只承诺横幅），但 Q24-⑥ 的字面必须先回填，否则这条告警的文案与 PRD 正文会互相指认对方错。

### Q5 范围纪律：过度设计 / 悄悄丢行为？

- **新增两面新"面"的定性**：
  - `POST /admin/api/zcode/bench`（`admin.py:393`）——**正当**。PRD **`prd.md:745-749` Q28-④** 点名授权：「凡是"要改运行中网关内存态"的动作都必须有管理端点出口——…**风控熔断回写（`POST /admin/api/zcode/bench`）**」。不是 §20 任何"不做"条目；且只监听 `127.0.0.1`（`local_admin.py`）。
  - `mgw zcode remove`（`cli_zcode.py:137`）——**轻微越界、可接受**。§19 M5-0 判据只列 `login/import/list/claim` 四个子命令，`remove` 是第 5 个；§20 唯一相关的 #12 禁的是"首期**前端 UI**（ZCode 账号管理页）"，CLI 不在其列。**替代方案本来是删掉 `store.delete_account`**（R7 自己列的两选项之一），选它的理由是"否则用户只能手删我们自己定义的目录结构"，我认为站得住。**必须回写 §19 M5-0 判据清单**，否则下轮验收会把它当"实现超出方案"再打一遍。
  - 证据文档 §5.3「本轮新增面仅为 1 个管理端点 + 1 个 CLI 子命令 + 2 类告警」——**核对为真**（不多不少），这条自陈守得住。
- **过度设计扫描（对照 §20 全部 20 条）**：未见违反。正面证据：`test_quota_is_not_exposed_on_v1` 主动守"不做对外端点"（§20 #12/M5-2）；未建统一 Device Registry、未加热切换 watcher（`main.py:244` 仍只监听 config.yaml）、未做 L-B/L-C 录入界面（`caps_overrides` 只进 YAML）、未做 GUI 自动化、调度参数仍全局一套（`schemas.py:182`）。
- **须记在案的一处"方案树未落地"**：§17 代码树把 `ops/builtin/` 首批 operation 写作「`zcode_claim` / **`query_balance`**」（`tech-design.md:1238`），实现目录只有 `zcode_claim.py`。§19 判据未要求它，故**不判违约**，但它是"额度耗尽/余量对用户不可见"（B4）的一个现成落点。
- **是否悄悄丢掉已验收行为**：**未发现**。`/v1/models` 原 6 字段逐字保留（diff 里是替换 list-comprehension，不是删字段）；行为变更只有"隐藏不可服务模型"一项，且**由用户批准**（`prd.md:732-736` Q28-②）。基线 462→537 无删除用例。`matcher.py`/`schemas.py` 的删除行只有 docstring。**账本外的存量改动**（不属本轮）：`models.js`/`apiaccess.js`（modal footer 空引用崩溃修复，mtime 09-24）、`index.html`/`base.css`（09-26）、`web/static/templates/*` 9 个模板 + `pages/templates.js`（09-22~24，**规范依据在 `frontend-spec.md:19 / :580` v2.11，是既有已定版资产，不是本轮私加**）——这三批都在 M3-M5 未提交工作树里，两份 e2e 账本都未逐文件登记，属**过程可追溯性问题**，不计本轮缺陷。

---

## 6. 诚实声明：我实跑了什么 / 只读了什么

**实跑（命令 + 输出，全部本机 `.venv`，无外网、无真实凭据）**

1. 全量回归（文档主数字，**逐字吻合**）：
```
$ cd /Users/w/Desktop/Model-Gateway && .venv/bin/python -m pytest -q --basetemp=/tmp/pm-acc-pytest
537 passed, 436 warnings in 67.58s (0:01:07)
```
2. 用例计数（文档表格逐项比对）：claim_wiring **10** ✓ / quota_reservation **16** ✓ / int_quota_reserve **4** ✓ / ops **43** ✓ / cli_zcode **20** ✓ / **servable(unit) 11，文档称 12** ✗ / **int_servable 7，文档称 6** ✗ / ops_isolation **1** ✓ / v2_zcode **37** ✓（合计 149，两行各错一个、总数互相掩盖）。
3. **反证 A（文档称撤 `import json` → 10 failed）**——我以 autouse fixture 运行时 `del zcode_claim.json`（**未改文件**）等价撤修复：
```
10 failed in 0.12s
```
→ **成立**。
4. **反证 B（文档称 `pick_and_acquire` 不预留 → 4 failed 含端到端超发）**——我 patch `reserve_quota` 恒真（等价 `if True`）：
```
8 failed, 12 passed   （含 tests/integration/test_int_v2_quota_reserve.py::test_exhausted_quota_does_not_take_more_requests）
```
→ **方向成立**（护栏确实能红），**数字不符**（我复现得 8，文档称 4；我的撤法更宽，会连带上直接测 `reserve_quota` 的单测）。列为准确性瑕疵，非造假。
5. §21 可见性脚本：**`后端 9/9 + 前端 18/18` 完全复现**。
6. CLI 冒烟：`python -m model_gateway.cli --help` → `rc=0`；`zcode --help` 列出 `list/login/launch/import/claim/remove`；`zcode remove nope --yes` → `✗ 账号『nope』不存在（见 \`mgw zcode list\`）`、`rc=2`——**与文档逐字一致**。
7. **BUG-1 可见性实测取证**（TestClient，见 §3 BUG-1 与 B5）：
```
MODEL IDS: ['has-resource']
  kind = model_without_resource | msg = 1 个系统模型未配置任何资源，调用将返回 503 —— 到「模型资源」页编辑资源添加映射（no-resource-model）
Q1 该模型已从 /v1/models 隐藏? True
Q2 任一横幅提到"已隐藏"?      False
Q3 直调被隐藏的模型 -> 503 {"error": {... "code": "NO_RESOURCE" ...}}
```
8. **死代码独立复扫**（AST，只读）：确认 `quota.py:286 CooldownManager` 在全仓**无任何非自身文件引用**（B2）。同批扫出 37 个可疑符号，其中绝大多数是我的静态扫描误报（经同文件内/属性调用消费），已逐个手工回验，**不扩大指控**。

**只读、未实跑（一律标 未验证，不作为放行依据）**

- 开工基线「上轮 `462 passed`」与「上轮 14 条修正 / 11 条已落地」：**未验证**（上轮工作树已被覆盖，无 commit 可比）。
- `docs/` 全目录（含 `prd.md`/`tech-design.md`/`design-spec.md`/两份 e2e 账本/三份 accept 报告）被 `.gitignore:17` 排除，**HEAD 无版本控制基线** → R5 的 PRD 回填**无法用 diff 审计**，我只能逐行读文件（已做）。
- §19 判据中的手工项 **T1–T10** 与本轮新增加固项 **N1–N4**：**未验证**，文档也**没有**宣称它们已验证（此处给诚实加分）。真实凭据、联网、住宅代理、Playwright 全部未触。
- `mgw` 命令名**未验证**（本机不可执行，见 §2 M3-0）。
- 浏览器内**真实渲染截图**本轮未采（前端 18 项是 Node 侧跑真实渲染函数 + DOM 结构断言，不等于 Chrome 实测）；上轮的 CDP 截图不覆盖 ③④ 两类新告警。

---

## 7. 放行条件（对应 §4，全部关闭即可转"通过"）

| # | 条件 | 最小关闭动作 | 预估成本 |
|---|---|---|---|
| B1 | M4-2 ③ 判据不能由代理用例声明 | 改为 `monkeypatch` 拦 `Path.home()`/断 `zcode_home()` 不被写路径调用；**或**把 §19 该行显式降级为"手工" | 低 |
| B2 | §17 熔断状态落盘 | `CooldownManager` 接进 `_maybe_bench`（进入时 `enter()`、启动时读回并补 bench）或**删除并在 §17 记偏离**；同时把它加入 `test_v2_cli_zcode.py` 的 AST 护栏清单 | 中 |
| B3 | 熔断原因可见 | `snapshot_by_resource()` 带出 `last_error`(+`cooldown_remaining_ms`)，总览资源表补列；§17 的"至 HH:MM"文案落地 | 低-中 |
| B4 | 额度耗尽的呈现 + 未披露偏离 | §5「有意偏离」补 3 条（`available()` 加维度 / 非全局熔断 / 额度不回写 status）；决定是否为额度耗尽加第⑤类告警或接 `query_balance` | 低（记账）+ 中（告警） |
| B5 | Q28-②「不允许只过滤不解释」补全 | ①类文案加"已从 /v1/models 隐藏"，`test_int_v2_servable.py` 加一条断言锁定 | **极低** |
| B6 | PRD Q24-⑥ 字面回填 | `prd.md:550`（及 `:758` 日志）加指向 Q28-③ 的修正句；`schemas.py:184`/`ir.py:58-60` 文档串同步四级序 | **极低** |

> 另附 3 条**不阻断**的观察（建议进 pitfalls/runbook，不要留成下次争议）：
> ① `settle_quota`/`release_quota` 把归还量硬编码为 `-1`（`resources.py:244,251`），而 `reserve_quota`/`pick_and_acquire` 支持 `amount`（`:193,228-238`）——今天所有调用点 `amount=1` 所以不暴露，`test_amount_greater_than_one_reserves_multiple_units` 只测预留不测结算/释放，属**潜伏不对称**，一旦有人传 `amount=2` 就漏预留。
> ② `runner.py:107-114` 锁目录不可写时 `return True`（静默退回进程内互斥）——与 §21.3 原则 1 相冲，建议至少出一次告警。
> ③ `gateway.host` 默认 `0.0.0.0`（`schemas.py:74`）+ 管理端免鉴权（Q18-① 用户定论）= 新增的 `POST /admin/api/zcode/bench` 这类**改状态端点**在局域网可被任意本机进程调用。不是本轮引入的暴露类，本轮只是多一个成员，仅提示记录。

**结论重申：有条件通过；阻塞项 6 个（B1–B6），全部为中等，无严重级。**
