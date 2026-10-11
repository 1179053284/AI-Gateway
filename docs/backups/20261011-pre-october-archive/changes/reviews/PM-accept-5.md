# PM 验收 · 第五轮（slice D：账本引用审计 + 需求真相比对）

日期 2026-09-28 · 只读复核（未改任何仓库文件）· 依据 `docs/changes/e2e-records/E2E-20260928-round5-fixes.md`
+ `docs/specs/prd.md` v1.16 Q28-⑥ + `docs/specs/tech-design.md` v2.0 §19/§20/§21。

## 结论：**有条件通过**

通过条件（全部为可机械完成项，无架构返工）：
1. **E5 / G1 须用户裁决**（见下节，本轮不裁决即为「发现问题不报」）。
2. 删死常量 `model_gateway/config/loader.py:25 DEFAULT_CONFIG_PATH = Path("data")/"config.yaml"`（中-1）。
3. 补「跨午夜恢复时刻」判据（中-2，与 E5 同批）。
4. 账本 2 处历史根因引用改标注 + tech-design §21.2 路径字面同步（轻-1/轻-3）。

## Job-1 · 机械数字（本人复跑，非引用）

| 项 | 账本 claim | 实测 | 判定 |
|---|---|---|---|
| 全量 pytest | 667 passed | `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest-pm5 -p no:warnings` → **667 passed in 131.00s** | ✅ 一致 |
| 前端门 | 实测 57 项失败 0 | `node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json` → **实测 57 项，通过 57 项，失败 0 项** | ✅ 一致 |
| 变异 | 可红 45/45 且无未覆盖断言 | 同脚本 `--mutation` → **可红 45/45；每条断言都有对应变异** | ✅ 一致 |
| 门限护栏 | 断言 ≥50 / 变异 ≥45 | `tests/integration/test_int_v2_frontend_gate.py:85,96` | ✅ 存在 |
| `ui_verify_v2_visible.py --mutation` 12/12 | §四 头部 claim | **未跑**（该脚本会起实例/写目录，与只读约束冲突）| ⚠️ 未验证 |
| 「撤修复→变红」全部红证 / §二-2 删窄即红 | §一、§二 | **未复跑**（须改工作树）| ⚠️ 未验证（判据本身存在且绿） |

**污染 claim 独立复验通过**：本次全量 pytest 之后 `ls data/usage | grep -c ops` → **0**，
`data/usage` mtime 仍为运行前的 `Sep 28 02:00`（未变）。`tests/conftest.py:8-24 _data_dir_isolated`
为 autouse 且钉 `MG_CONFIG`，`:27-34` 另钉 `MGW_OPS_LOCK_DIR`，`:37-` 清进程级持锁集 → **修复是真的**。

## Job-1 · 引用逐条核对（40 处 file:line）

| # | 账本引用 | 现场 | 判定 |
|---|---|---|---|
| 1 | `quota.py:384` 根因「把 FileNotFoundError 当 OSError 吞掉」 | 该行现为 `except FileNotFoundError:` + 385-387 注释解释旧缺陷 | ⚠️ **引用点=修复位**，行内容≠描述（轻-1） |
| 2 | `core/resources.py:297 bench()` | `def bench(self, state, seconds) -> bool` | ✅ |
| 3 | `:318 extended = ...` | `extended = state.status != "cooldown" or until > state.cooldown_until` | ✅ 逐字 |
| 4 | `upstream/zcode/quota.py apply_to_resource`（无行号） | `:478` 定义，`:487-490` docstring 声明「只在取得所有权时写原因」 | ✅ 定位到 |
| 5 | `resources.py:224` 指纹复位 | `if state.src_fp != fp:` + 复位注释 | ✅ |
| 6 | `:21 _conn_fingerprint` | 函数存在，docstring「只存摘要不存明文 Key」 | ✅（sha256 前 12 位**字面未逐字节核对**） |
| 7 | `resources.py:129 _SEVERITY` | `{"invalid":3,"disabled":2,"cooldown":1,"active":0}` | ✅ |
| 8 | `:419 snapshot_by_resource` 聚合改「任一 active 即 active」 | 定义在 `:419`，且 `:431 self.reconcile_expired()` 确由其调用 | ✅ 两条 claim 同点 |
| 9 | `:400 reconcile_expired()` | `def reconcile_expired(self) -> int` | ✅ |
| 10 | `ops/runner.py:489 unread_failures()` / `:512 ack_reports()` | 两处签名逐字命中，水位「按行号」注释在位 | ✅ |
| 11 | `ops/runner.py:460 default_usage_dir()` | `return paths.data_dir()/"usage"` | ✅ |
| 12 | `cli_zcode.py:238 write_report(report)` | 逐字命中 | ✅ |
| 13 | `cli_zcode.py:247` 中途熔断提示 | `elif circuit.active():` + `:250` ⚠ 打印 | ✅ |
| 14 | `cli_zcode.py:271` 归因分桶 | `parts.append("被熔断拦住" if breakered else f"无需动作 …")` | ✅ |
| 15 | `cli_zcode.py:289` 退出码优先级 | `return 3 if breakered else 1` | ✅ |
| 16 | `zcode_claim.py:122 reason = circuit.reason()` | 逐字命中 | ✅ |
| 17 | `test_v2_circuit.py:172` 「把缺陷钉成标准」 | 该行现为 `assert res.category == "failed"`；`：至 HH:MM$` 新断言在 **`:179`** | ⚠️ **off-by-7**，历史描述（轻-1） |
| 18 | `cli_setup.py:68 _CAUSE_HINTS` / `:76 _hidden_causes()` / `:144 reason_text` | 三处逐字命中（三桶文案存在） | ✅ |
| 19 | `test_v2_wiring_guard.py:139 _reaches_module` / `:272 canary` | 两处逐字命中；canary 确含「同名歧义」变种 `:300` | ✅ |
| 20 | 清单补齐（main/enums/config/adapters） | `V2_MODULES`（`:21`）含 `main.py`、`config/loader.py`、`enums/matcher.py`、`adapters/openai_out.py` | ✅ |
| 21 | `adapters/openai_out.list_models` 已删 | 全包 `grep list_models` 仅剩 `api/openai_compat.py:39` 路由 | ✅ |
| 22 | `api/admin.py:528` 收敛到 `save_config` | `save_config(config, runtime.config_path)`，注释「将来只改一份就是 bug」 | ✅ |
| 23 | `api/admin.py:604` 空 entries 400 / `:576` source 按实际生效 | 400 文案「等于没保存」；`from_file = path.exists() and bool(entries)` | ✅ |
| 24 | `quota.py:584 resource_ids_of_account` 加 product 条件 | def 在 **`:561`**（off-by-23），但 `:584 want = store.PRODUCT` + `:585-587` 条件即在函数体内且即该判据本体 | ✅ 可定位（非失效） |
| 25 | `:530 sync_circuit_to_runtime` 返回 `(bench, skipped)` | `def sync_circuit_to_runtime(runtime) -> tuple[int, int]` | ✅ |
| 26 | `main.py:83` 三种情形分别留痕 | def 在 `:83`，三分支日志 `:98/:101/:104`（benched / product-skipped / 零命中） | ✅（引用 def 而非打印点） |
| 27 | `core/local_admin.py:61 reason_text()` | 逐字命中 | ✅ |
| 28 | `tests/conftest.py:9 _data_dir_isolated` | autouse，钉 `MG_CONFIG` | ✅ |
| 29 | 判据名 40 余个（`test_*`） | **29/29 逐个 grep 命中定义**，仅 `test_int_v2_ops_isolation` 是**文件**（`tests/integration/test_int_v2_ops_isolation.py:85` 经真 HTTP 读 `ops_failed_unread`）非函数 | ✅ 账本按「集成」表述，成立 |
| 30 | §四 `data/usage` ops 计数 0 | 复跑后仍为 0 | ✅ |

**引用失效统计：硬失效 0；引用点内容与历史描述不符 2（#1、#17）；行号偏但可定位且仍在正确函数内 3（#24、#26、#8 双 claim 之一）。**

## Job-2 · Q28-⑥ 八项裁决 → 实现 / 测试 / 判据是否同一句话

| 裁决 | 实现 | 测试（已复跑绿） | 判据与措辞一致？ |
|---|---|---|---|
| ① jsonl 为唯一事实源 + 两条腿落盘 + 确认=写水位 | `runner.py:489/512`、`cli_zcode.py:238`、`admin.py:129/390-400`；进程内计数器已删（`Runtime` 无 `ops_failed_unread`，仅存 API 响应键） | `test_unread_count_comes_from_the_jsonl_not_memory`/`test_unread_survives_process_restart`/`test_failure_round_acks_once_and_lands_in_the_pointer_file`/`test_ops_ack_endpoint_clears_the_file_backed_count` | ✅「按行号不按时间戳」=「水位（行数）」 |
| ② 只在打印过失败明细后 ack；熔断空跑轮不清零 | `cli_zcode.py:291-292` | `test_clean_round_does_not_ack:270`/`test_breaker_round_does_not_ack:294` | ✅ |
| ③ `invalid`/`disabled` 终态不被临时冷却覆盖 | `resources.py:297-316` 单一咽喉（覆盖 scheduler 5 点 + §17 2 回写点） | `test_terminal_states_are_not_revived_by_a_cooldown:268`（两态循环） | ✅ |
| ④ 冷却只延长 + 返回值裁决所有权 | `:318 extended`；`quota.py:478-490` 只在取得所有权时写 `last_error` | 3 条：不缩短 / tick 不剪熔断 / 正向对照仍落原因 | ✅「写 last_error 的一方必须问它」被正向对照钉住 |
| ⑤ 改凭据=新连接身份 → 运行态清零；未变按 §8-4 保状态 | `:21` 指纹 + `:224` 复位 | `test_changed_credential_clears_the_terminal_state`/`test_same_credential_reload_keeps_runtime_state`（对照） | ✅ |
| ⑥ 删状态文件=已解除（跨进程一致）+ 文案只放开运营闸门 | `quota.py:384-387`；文案 `cli_zcode.py:245-246` | `test_deleting_the_circuit_file…:405`/`test_cross_process_delete…:427`/`test_corrupt_circuit_file_does_not_silently_clear:438`（反向钉「损坏仍保持内存态」） | ✅ |
| ⑦ 回写作用域受 `product` 约束 + 不匹配必留痕 | `quota.py:561/584-587`、`:530` 返回二元组、`main.py:98-108` | `test_product_scoping…:523`/`test_only_mismatching…:542`/`test_sync_circuit_is_silent_noop…:564` | ✅ |
| ⑧ 退出码 3 优先于 1 + 0/1/2/3 进 `--help`/README | `cli_zcode.py:289`、`cli.py` epilog、`README.md:113-117`、`README.zh-CN.md:110-113` | `test_breaker_wins_over_a_credential_failure_in_exit_code:345`/`test_non_breaker_round…:373`/`test_claim_help_documents_all_four_exit_codes:397` | ✅ |

**§20 / Q25-⑩ / Q27-⑤ 不做边界**：逐项比对未见越界 —— 未按模型拆调度参数（#20，调度仍全局）、
未新增 ZCode 账号管理页（#12，前端只改文案/红点）、无 GUI 自动化与代登录（#16/#17）、
未建统一 Device Registry / 四表存储（#1，`src_fp` 只在内存 `ResourceState`，未进 `schemas.py`、未进端点、未进界面）。

### 偏离 E1–E6 逐条判定

| # | 判定 | 依据 |
|---|---|---|
| E1 jsonl 为事实源、删进程内计数器 | **可接受**（已被 PRD Q28-⑥① 逐字追认；§21.2 出口②只规定"能从 `/admin/api/status` 读到"，账本对 §21.2 的读法成立） | 需求真相已回填 |
| E2 `bench()` 返回 bool | **可接受**（④「由返回值裁决谁 owns」即为其追认） | 同上 |
| E3 `src_fp` 字段 | **可接受**（⑤ 为其需求化；未新增界面/端点，纯内存） | 同上 |
| E4 退出码 3 优先 | **可接受**（⑧ 明文） | 同上 |
| E5 `至 HH:MM` 无日期 | **不可就这么算了 → 升级用户裁决**（见下）；且**PRD Q28-⑥ 未登记此项**，属需求真相留白 | 八项表内无对应条 |
| E6 手动出口=删文件（仅放开运营闸门） | **可接受**，但**可发现性为零**：界面上没有任何地方告诉用户这个出口存在，只有 CLI 文案 `:245` 提到 → 建议与 G4 并二期补一处「配置告警」横幅（§21.2 已有横幅体系） | ⑥ 已记作用域 |

### E5 / G1 决策选项

**E5（熔断文案跨午夜看不出哪天恢复）**
- **A**：仅当恢复时刻落在次日及以后时输出 `至 明日 HH:MM`（同日仍 `至 HH:MM`）。改动面：`quota.py:431` 一处 + 现有正则断言 `，至 \d{2}:\d{2}$`（`test_v2_circuit.py:179` 及 CLI 同族）同步放宽 + `cli_zcode.py:245` 文案。前端不需改（徽章文本来自后端串）。
- **B**：全站改绝对时刻 `至 MM-DD HH:MM`。语义最干净，但资源表列宽/「剩余 Xs」副标要复测，且变异表 I7「指路文案」类判据需重排。
- **推荐 A**（只在真会歧义时变长，符合 §21.3 原则 3「最小可见差异」；B 的额外收益对单用户本地部署近乎零）。
- **什么都不坏的地方恰恰是问题**：现有判据只要求 `，至 \d{2}:\d{2}$`，**冻结时钟下没有任何一条测试能因"跨午夜歧义"而变红** —— 也就是说 A 之外还须新增一条「23:40 起 30 分钟」的判据，否则本轮自立的元规则（"撤掉修复不会变红的断言不算证据"）在这项上失效。不改的后果：用户在 23:40 命中风控 → 看到「至 00:10」，可能等到第二天凌晨以为已恢复、或第二天白天完全不知道该不该再等，且这是**唯一**的恢复时刻出口（§17 回写的可见性收益）。

**G1（锁退路脑裂：一方写主目录、另一方只能写 `/tmp`）**
- **A**：让退路参与主目录命名空间 —— 落 `/tmp` 前必须先探测主目录锁集，主目录有同名锁则视为**已被持有**（`/tmp` 只作镜像，不作第二把锁）。正确但需要"主目录可达性协商"，改动面 = `ops/runner.py:86-220` 锁获取全路径 + 新增超时/异常分支，且**跨挂载点无法原子**。
- **B**：**fail closed** —— 主数据目录不可写即拒绝本轮批量（保留告警 + 配置告警横幅），`/tmp` 退路只保留给"主目录完全不可用且显式配了 `MGW_OPS_LOCK_DIR`"的场景。
- **推荐 B**。理由：`/tmp` 退路的立项理由（`runner.py:90`「不能悄悄把跨进程互斥关掉」）在混合格局下**恰好自己就变成了它要防的那件事** —— 互斥被悄悄关掉且无人知道；而本项目最坏失败态是对风控敏感的上游**重复领取**（3012 → 全局熔断 30 分钟）。不做的后果：网关 cron 腿与在只读仓库目录里跑的 `mgw zcode claim` 可**同时**领取同一账号，两边日志都说"只有我在跑"，§16.3「只领一次」不变量被静默破坏。可用性损失仅存在于"数据目录半可写"这一本地产部署几乎不出现的格局，而该格局本身已经可见。→ **须用户裁决**（B 改变了"绝不拦用户"的既有行为）。

## 缺陷分级

| 级 | # | 内容 | 证据 |
|---|---|---|---|
| 严重 | — | 本轮**未发现**新「严重」缺陷（八项裁决均实现 + 有能红的判据 + 全绿） | 667 passed |
| 中 | 中-1 | `config/loader.py:25` 仍保留 cwd 相对的 `DEFAULT_CONFIG_PATH`（全包零引用，纯"兼容旧引用"占位）。这正是本轮 `core/paths.py:3-15` 立项要消灭的形态；且接线护栏按 `模块#类.方法` 键控，**模块级常量不在其覆盖内**，将来谁 import 回去都不会被报 | `grep DEFAULT_CONFIG_PATH` 仅命中定义行；`main.py:53` 用 `paths.default_config_path()` |
| 中 | 中-2 | E5 相关：判据体系对「跨午夜恢复时刻」**零覆盖**（现有正则只允许 `至 HH:MM`），改文案必红、不改则永远无人发现 | `test_v2_circuit.py:179`、`quota.py:431` |
| 轻 | 轻-1 | 账本 2 处「历史根因」引用点已是修复后代码（`quota.py:384`、`test_v2_circuit.py:172`），第六轮按行复跑会误判为不符 | 见 Job-1 #1/#17 |
| 轻 | 轻-2 | `tests/unit/test_v2_ops.py:838` 桩件仍写 `ops_failed_unread = 0`（该属性已从生产 `Runtime` 删除），误导后续维护者以为第二本账还在 | grep |
| 轻 | 轻-3 | `tech-design.md` §21.2 出口②仍写 `data/ops-results-<date>.jsonl`，实现与 PRD v1.16 为 `data/usage/ops-results-<date>.jsonl`；技术方案版本头仍停 v2.0（2026-09-26），未记 Q28-⑥（PRD 已记） | `tech-design.md:1456` vs `prd.md:774` |
| 轻 | 轻-4 | G3 自认：前端门依赖本机 `node`，缺则 skip → CI 上可能整段静默通过（账本已登记，需进 CI 前处理） | `test_int_v2_frontend_gate.py` |

## 未验证（诚实清单）

1. 全部「撤修复 → 变红」红证（§一各行）与 §二-2「删窄即红」演练：只读约束下未施加改动，**未复跑**。
2. `scripts/ui_verify_v2_visible.py --mutation` 的后端出口 12/12：**未跑**（会起实例/写目录）。
3. `_conn_fingerprint` 是否恰为「sha256 前 12 位」：函数与「不存明文 Key」注释已核，**长度字面未逐字节核对**。
4. 真实上游行为（3012/401 实弹）、`:8300` 在跑实例是否已加载本轮代码：**未测**（账本亦声明未访问真实上游、未重启实例）。
5. `list_accounts()` 的 meta.json 判据只在 `test_stray_directory_is_not_an_account` 绿这一层采信，未独立复现生产缺陷原形态。
