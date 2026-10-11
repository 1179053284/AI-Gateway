# E2E · 第五轮返工账本（2026-09-28）

> 依据：第四轮三角色验收（`docs/changes/reviews/{PM,eng,ix}-accept-4.md`，判定分别为
> **有条件通过 / 有条件通过 / 不通过**）+ 用户指令「做完一个然后自验收，有问题就改再自验收，
> 完全验收通过后进行开发下一，直至全部开发完毕」。
>
> **本轮的元规则不变**：一条断言如果撤掉修复后不会变红，它就不算证据。
> 本轮额外补了一条：**"绿"必须由能红的判据产生** —— 因此护栏、红点、前端门
> 三项都补了"能不能红"的自证（§二 末行 + §三）。
>
> 本轮结束时机械门（同一次运行实测）：
> - `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest` → **667 passed**（第四轮末 633 → +34）
> - `node scripts/verify_v2_frontend.mjs <overview>` → **实测 57 项，失败 0 项**（第四轮 46 项）
> - 同脚本 `--mutation` → **可红 45/45；每条断言都有对应变异**（第四轮 37/37）
> - `.venv/bin/python scripts/ui_verify_v2_visible.py --mutation` → 后端出口 **12/12** + 前端 57 + 变异 45/45
> - 需求真相：PRD 升 **v1.16**，新增 **Q28-⑥**（八项运行态/红点定稿）
> - 全程未写用户 `data/`（末次检查 `ls data/usage | grep -c ops` → **0**；见 §四 纪律条）

---

## 一、逐项修复与红证

### 🔴 S-1 `circuit.json` 删除后常驻进程仍熔着（CLI 承诺的出口是假的）

| 项 | 内容 |
|---|---|
| 面板实测 | PM 与 ix 各自复现：`enter()` → `unlink()` → 同进程 `active()` 仍 True / `left_minutes()` 仍 30，而**新**进程读到 `False` |
| 根因 | `quota.py:384` 把 `FileNotFoundError` 与"文件损坏"一起当 `OSError` 吞掉（"读不到就保持内存态"） |
| 修法 | 文件不存在 = 熔断**已解除**（`_cd` 归零）；损坏/半写/非对象仍保持内存态（另一条判据反向钉住）；文案改成"只放开运营闸门，已 bench 的资源按剩余冷却自行回池"（不承诺做不到的事） |
| 判据 | `tests/unit/test_v2_circuit.py::test_deleting_the_circuit_file_releases_the_running_process` / `test_cross_process_delete_is_visible_without_restart` / `test_corrupt_circuit_file_does_not_silently_clear` + `tests/unit/test_v2_cli_zcode.py::test_claim_under_global_breaker_exits_3`（新增作用域文案断言） |
| 红证 | 把 `FileNotFoundError` 分支并回 `except OSError` → **2 条变红**；改回旧文案 → CLI 判据变红 |

### 🔴 S-2 一次额度 tick 把 30 分钟熔断 bench 剪成 60 秒（提前放行）

| 项 | 内容 |
|---|---|
| eng 实测 | `熔断对齐后冷却 = 30.0 分钟 → 一次额度 tick 后 = 60 秒`，而熔断仍剩 30 分钟 |
| 根因 | `bench()` 覆盖式写 `cooldown_until`；调用方语义全都是"至少冷却这么久"，却允许后到的短值改写字先到的长值 |
| 修法 | `core/resources.py:297 bench()` 两条不变量：**冷却只延长**（`:318 extended = ...`）+ **返回是否取得所有权**；`upstream/zcode/quota.py apply_to_resource` 只在取得所有权时写 `last_error`（否则「最近错误」会被后到的短原因改写） |
| 判据 | `test_bench_never_shortens_an_existing_cooldown` / `test_quota_exhaustion_tick_does_not_shorten_the_breaker_bench` + 正向对照 `test_exhaustion_reason_still_lands_when_no_longer_cooldown_is_held`（挡住"跳过"变成吞掉一切回写的挡箭牌） |
| 红证 | 撤 `max` → 1 条红；撤所有权判断 → 另一条红（两条互相独立，单层修不住） |

### 🔴 S-3 §17 回写把 `invalid`/`disabled` 复活成可服务 + 无恢复路径

| 项 | 内容 |
|---|---|
| eng 实测 | `invalidate 后 servable=[] → 一次额度回写后 servable=['m']`（死凭据重新被声明）；ix：`invalid`/401 **永不自愈** |
| 修法① | `bench()` 拒绝覆盖终态（`core/resources.py:297`）—— 一处覆盖 scheduler 的 5 个调用点与 §17 的两个回写点 |
| 修法② | `resources.py:224` 连接身份指纹（`:21 _conn_fingerprint`，`base_url`+Key 的 sha256 前 12 位，**不存明文 Key**）：改凭据 = 新连接 → 状态/冷却/连续失败/最近错误清零；凭据未变时仍按 tech §8-4 保状态 |
| 判据 | `test_terminal_states_are_not_revived_by_a_cooldown`（invalid + disabled 两态循环）/ `test_changed_credential_clears_the_terminal_state` / `test_same_credential_reload_keeps_runtime_state`（正向对照） |
| 红证 | 撤终态守卫 → 1 条红；把指纹复位改成 `if False:` → 恢复判据红 |

### 🔴 S-4 条目级 `disabled` 被聚合成 `cooldown`；到期冷却无流量时长期谎报不可用

| 项 | 内容 |
|---|---|
| ix 实测 | 上游 401 判死 → 快照 `{'status':'cooldown','cooldown_remaining_ms':0}`，生产 `dashboard.js` 渲染出 `b-cool title="剩余 0s"`，同一屏横幅却说"凭据失效" |
| PM 实测 | 额度恢复后（无流量）`overview` 仍报 `cooldown / 0ms / "ZCode 额度耗尽"` |
| 修法 | `resources.py:129 _SEVERITY` 改为 `invalid > disabled > cooldown`（聚合与取原因同一把尺）；`:419 snapshot_by_resource` 聚合改为"任一 active 即 active，否则取最严重"；新增 `:400 reconcile_expired()`（到期即归位 + 清 `last_error`），由 `:419 snapshot_by_resource` 调用 |
| 判据 | `tests/unit/test_v2_servable.py` 新增 5 条：单条目 disabled 不得成 cooldown / invalid 压过 cooldown / 一条健康即仍下发（正向对照）/ 到期零流量也报可用 / `reconcile_expired()` 返回条数 |
| 红证 | 换回旧聚合 → 2 条红；去掉 `reconcile_expired()` 调用 → 1 条红；恢复旧 `_SEVERITY` 顺序 → 1 条红 |

### 🔴 S-5 熔断空跑轮照样清零红点；CLI 失败既点不亮红点也不落盘

| 项 | 内容 |
|---|---|
| 面板实测 | PM：CLI 只打了熔断警告，未读却从 **7 → 0**；ix：`bump_failed_counter` / `write_report` 只有 cron 腿调用，而红点与 toast 把用户指到 `ops-results-*.jsonl` |
| 修法 | 未读失败数**改为以 jsonl 为唯一事实源**：`ops/runner.py:489 unread_failures()`（按已确认水位之后的 `failed` 计数）+ `:512 ack_reports()`（写水位，**按行号不按时间戳**，避免同秒漏账）；`/admin/api/status` 与 `/admin/api/ops/ack` 改接这两个函数；删掉进程内计数器 `Runtime.ops_failed_unread` 与 `bump_failed_counter`/`clear_failed_counter`；CLI 腿 `cli_zcode.py:238 write_report(report)`；**只有打印过失败明细才 ack** |
| 附带收益 | 网关重启不再把"没人看过"的失败清零；CLI 与 cron 两条写入路径天然等价 |
| 判据 | `test_unread_count_comes_from_the_jsonl_not_memory` / `test_unread_survives_process_restart` / `test_ack_is_the_clear_exit_and_only_eats_acked_rows` / `test_ack_is_empty_dir_safe` / `test_unread_ignores_yesterdays_file` / CLI 三条（clean 轮不 ack、熔断轮不 ack、失败轮 ack 一次且落盘）/ 集成 `test_int_v2_ops_isolation`（经真 HTTP 读出 unread）+ `test_ops_ack_endpoint_clears_the_file_backed_count`（写入→3→ack→0→再写→1） |
| 红证 | 恢复"无条件 ack" → 2 条红；撤 CLI 落盘 → 1 条红 |

### 🔴 S-6 实时命中风控时「最近错误」没有"至 HH:MM"（§17 收益落在错的一半）

| 项 | 内容 |
|---|---|
| 面板实测 | PM 走**真实接线点** `_handle_risk_control` → `overview` 给出的是无时刻的旧文案，而 `circuit.reason()` 已带时刻；重启后才对 |
| 根因 | `zcode_claim.py` 回写传的是 `GLOBAL_BENCH_REASON` 常量；且 `tests/unit/test_v2_circuit.py:172` **把这条缺陷钉成了标准** |
| 修法 | `ops/builtin/zcode_claim.py:122` 改为 `reason = circuit.reason()`（cron 腿与 CLI 腿的 HTTP 出口都用它）；两条判据改为要求 `，至 HH:MM$` |
| 红证 | 换回常量 → **2 条红**（cron 腿 + CLI 腿） |

### 🔴 S-7 前端门三个逃逸变异 + "抛错算红"的推定分支

| 项 | 内容 |
|---|---|
| ix 实测 | 三个不在变异表里的破坏（表格不再调用 `statusBadge` / 红点 click 首行 `return;` / `cooldown + remaining=0` 归正为绿标）→ **46/46 仍绿**；另 `--mutation` 的 `catch` 把抛错记成已红 |
| 修法 | `scripts/verify_v2_frontend.mjs` ① `check()` 改为**逐条捕获异常**（抛错=该条红，不再靠跑崩顶替）；② 新增 `B7`（用 spy 注入证明表格**逐行调用** statusBadge）、`C8`（cooldown+0 不得归正）、**I 段 = 抽出 main.js 红点整块配假 DOM 真跑**（`I0~I8`：显隐两个方向、5s 间隔、隐藏不发请求、点击真 POST、指路文案、元素缺失静默）；③ 变异表补 11 条并去掉与新增重复的 3 条 |
| 自证 | 加严后 **45/45 变异各自打红指定判据**，且"未被任何变异覆盖的断言"为空；`tests/integration/test_int_v2_frontend_gate.py` 的门限提到 **断言 ≥50 / 变异 ≥45**，并实测"删窄即红"（删掉 I4~I8 → 两条门判据同时红） |
| 本轮自抓到的一次空过 | I 段初版把 `runDot()` 的 **Promise** 直接当布尔判 → `!!Promise` 恒真 = 我自己写出 8 条空过；改为 `async runChecks` + 统一 await 后 57 条仍全绿（这次是真绿） |

### 🟠 S-8 退出码 3 被失败吞掉 + 归因文案 + 退出码无文档

| 项 | 内容 |
|---|---|
| 修法 | `cli_zcode.py:289` `return 3 if breakered else 1`（熔断优先，注释说明"同屏失败属未发起即失败"）；`:271` 熔断轮的 inactive 标为"被熔断拦住"、非熔断轮改为如实的"无需动作"；`cli.py` 的 `claim` 子命令加 `description`+`epilog`（0/1/2/3 + `3` 跨子命令不同义），README / README.zh-CN 各补一条 |
| 判据 | `test_breaker_wins_over_a_credential_failure_in_exit_code`（含"无资格"字样不得出现）/ `test_non_breaker_round_still_labels_inactive_as_unqualified`（正向对照）/ `test_claim_help_documents_all_four_exit_codes` |
| 红证 | 撤优先级 → 1 条红；撤归因 → 同条红；撤 epilog → help 判据红 |

### 🟠 S-9 `mgw setup` 把三种成因压成一句错指路

| 项 | 内容 |
|---|---|
| 修法 | `cli_setup.py:68 _CAUSE_HINTS` + `:76 _hidden_causes()`：按"无映射 / 映射的资源均未启用 / 运行态不可用"分桶，各印一句各指对页面 |
| 判据 | `test_hidden_causes_are_split_into_three_buckets`（三桶 + 三句互不相同）+ 集成 `test_setup_reads_live_models_through_auth` 增加"必须说运行态/最近错误、不得说添加映射" |
| 红证 | 把第三句改回第一句 → **2 条红** |

### 🟠 S-10 接线护栏按裸名键控漏报 + 模块清单不全

| 项 | 内容 |
|---|---|
| eng 实测 | `AccountLocks.claim` 这类死方法因别处同名而报绿；清单漏 `main.py` / `enums/matcher.py` / `config/loader.py` / `adapters/openai_out.py` → `wrap_httpx_error`、`list_models`、`save_config` 无人报 |
| 修法 | `tests/unit/test_v2_wiring_guard.py` 符号全集改键为 **`模块#类.方法`**；同名歧义时要求引用文件**提得上类名或与定义模块有 import 关系**（`:139 _reaches_module`）—— 先试"硬要求类名"，误报 25 条后改成本方案（`runtime.resources.pick_and_acquire()` 这类实例藏在变量里的写法不能算死）；清单补齐 |
| 白名单收紧 | `_POLYMORPHIC_ALLOWLIST`（`chat_stream` / `images_generate` 等适配器接口方法）新增**可核验判据**：≥2 个类定义同名方法 + 包内确有 `.<name>(` 调用点，否则不许豁免 |
| 暴露并修掉的死/半死符号 | ① `OpenAIOutAdapter.list_models` **删除**（全包零调用）；② `config.loader.save_config` 原为"只有测试在用"，而 `api/admin.py:528` 自己手写了一份原子写 → **收敛到 `save_config`**（tempfile + fsync + `BaseException` 清临时文件，行为更严） |
| 护栏自证 | 新增 `:272 test_guard_catches_a_planted_dead_method`：临时植入 `_wiring_canary_pkg/{a,b}.py`，要求护栏抓到 ① 唯一名死方法 ② **与别处同名的死方法**（正是老版本漏报的形态），且不冤枉真有调用方的那个 |

### 🟡 S-11 熔断提示时机 + 回写作用域 + 静默空转可见

| 项 | 内容 |
|---|---|
| 修法 | ① `cli_zcode.py:247` 本轮**跑起来才**命中 3012 也打印 ⚠（原只判开局）；② `quota.py:584 resource_ids_of_account` 增加 **`product` 相符**条件（`product` 为空的旧配置保持兼容）；③ `:530 sync_circuit_to_runtime` 改返回 `(bench 数, 同名但产品不符被跳过数)`，`main.py:83` 三种情形分别留痕（生效 / 产品不符跳过 / 一个都没对上） |
| 判据 | `test_breaker_tripped_during_this_round_is_reported` + `test_product_scoping_keeps_other_products_out_of_the_bench` + `test_only_mismatching_resources_reports_skipped` + `test_sync_circuit_is_silent_noop_when_breaker_expired` |
| 红证 | 撤 product 条件 → 断言"qoder 资源被纳入"红；撤跳过计数 → `(0,0) != (0,1)` 红；撤中途提示 → CLI 判据红 |

### 🟡 S-12 轻项批（黑话 / 预留泄漏 / 枚举池空保存 / 相对路径 / 缺测状态）

| 子项 | 落点 | 红证 |
|---|---|---|
| `http-<code>` 黑话 | `core/local_admin.py:61 reason_text()`（未登记码也给人话），`cli_setup.py:144` 改用它 | 断言"未预期"/码值文案 → 撤函数即红 |
| `reserved` 泄漏 | `resources.py:369 settle_quota` / `:379 release_quota` 去掉 `remaining is None` 早退 | 恢复早退 → 复现 `reserved=1` 不归还（实测报错原文） |
| 枚举池"清空"谎报 | `api/admin.py:604` 空 entries 直接 400 并说明"会回落内置目录 = 没保存"；`:576` `source` 改按**实际生效来源**报 | 新判据 `test_enums_put_rejects_empty_list_and_reports_source_honestly` |
| `write_report` 相对路径兜底 | `ops/runner.py:460 default_usage_dir()`（经 `core/paths`，认 `MG_CONFIG`） | conftest 钉 MG_CONFIG 后若仍写相对路径，落盘判据找不到文件即红 |
| `timeout` 三态缺测 | 集成 `test_setup_when_gateway_hangs_says_timeout`（listen 不 accept 的黑洞端口） | 把 timeout 并回 not-running → 该条红 |

---

## 二、本轮新增的"测试自己也要能红"判据

| # | 自证 | 实测 |
|---|---|---|
| 1 | 接线护栏植入死方法 canary（唯一名 + 同名歧义两种） | 必须被抓到，且真有调用方的不被冤枉 → 绿 |
| 2 | 前端门"删窄即红"演练（临时删 I4~I8 判据与其变异） | `pytest tests/integration/test_int_v2_frontend_gate.py` → **2 条全红**（断言数与变异数门限各抓一次） |
| 3 | 变异模式不再接受"抛错顶替"（抛错 = 该变异无效） | 45/45 无一例走推定分支 |
| 4 | conftest 的 `_data_dir_isolated` 顺带暴露并修掉一个**生产缺陷** | `store.list_accounts()` 原把账号根下任意子目录当账号（熔断会去 bench 不存在的号）→ 加 meta.json 判据，`test_stray_directory_is_not_an_account` 钉死 |
| 5 | 我自己写出的空过被自查抓到 | I 段初版 `!!Promise` 恒真（8 条假绿）→ 改 async 后才是真绿；已写入 §一 S-7 末行 |

---

## 三、偏离方案之处（本轮新增，逐条交代）

| # | 偏离 | 依据与判断 |
|---|---|---|
| E1 | 红点未读数以 jsonl + 水位文件为准，**删除**进程内 `ops_failed_unread` 计数器 | §21.2 出口②只规定"从 `/admin/api/status` 能读到未读失败数"，没规定存哪里；进程内计数器无法跨进程（CLI）且重启即丢，属"实现选择"而非需求 |
| E2 | `bench()` 返回 bool（所有权）| 方案未规定；不给返回值就得在调用方复制时间算术，两处判据会漂移 |
| E3 | 资源运行态新增 `src_fp` 指纹字段 | 终态（invalid/disabled）此前**没有任何**恢复路径，属方案留白；按"改凭据=新连接"这一最小事实补，不新增界面/端点 |
| E4 | `mgw zcode claim` 退出码 3 **优先于** 1 | 见 PRD Q28-⑥⑧；两码并存时"本轮没真跑"是更高阶级的结论 |
| E5 | 熔断文案的恢复时刻用 `至 HH:MM`（不含日期），跨午夜会看不出是明天 | 方案 §17 字面即 `至 HH:MM`；已登记为轻项（面板 L-1），改文案需同步前端判据与 `mgw setup` 输出，留下一轮 |
| E6 | 无"一键解除熔断"界面/端点，手动出口=删除状态文件（且只放开运营闸门） | 方案未定义；§14 已确立"手改本地文件是受支持路径"。已在 Q28-⑥⑥ 记为该出口的**作用域** |

**登记未在本轮动手（相邻缺口，附可复跑判据条件）**

| # | 缺口 | 建议 |
|---|---|---|
| G1 | 锁退路的脑裂窗口：一方写主目录成功、另一方只能退 `/tmp` 时，两把锁各自成立（eng L-5） | 需要一个"主目录可达性协商"协议或让退路目录参与主目录锁的探测；改动面大于本轮边界 |
| G2 | `mgw setup` 的 401 只解释"密钥失效"，未提示"端口与配置不一致"（PM/账本 G2） | 文案补一句；需先实测两种错配的可见差异再定措辞 |
| G3 | 前端门依赖本机 `node`（无则 skip） | 进 CI 前须改为 fail 或提供 Python 侧执行器 |
| G4 | 熔断/冷却剩余时间在总览**指标区**没有聚合视图（只有资源表逐行秒数） | 与二期「账号授权」页一并考虑 |

---

## 四、纪律与操作记录

- 本轮**没有**改动用户正在使用的仓库 `data/`。中途确实发生过一次污染：新增 CLI 落盘后，测试跑进真实 `data/usage/ops-results-20260928.jsonl`（2 行，实测 `cat` 确认是本轮测试数据后删除），根因是各用例只记得设自己的临时目录。
  已按"挡在正确位置"的原则修掉：`tests/conftest.py:9 _data_dir_isolated` 逐用例钉 `MG_CONFIG` → 生产路径（`core/paths`）一律落 tmp。末次 `ls data/usage | grep -c ops` → **0**。
- 全程未访问真实上游；未读写 `~/.zcode` / `~/.workbuddy` / `~/.workbuddy-ai`；未重启 `:8300` 实例。
- 撤修复红证均在**当前工作树**上施加并即时复原（复原后同批测试复跑为绿）；发现过一次"复原未生效"由陈旧 `.pyc` 造成（mtime 秒级 + 文件大小相同），已通过清 `__pycache__` 复核 —— 后续红证须在同一轮里打印"复原后判据为绿"作为收尾。

---

## 五、下一轮（第六轮）复验要点

1. §一 每条的"撤修复 → 变红"都可按表复跑（锚点为 `file:line`，注意行号会漂移，优先按内容检索）。
2. 状态机三条不变量是否仍成立：终态不被覆盖（S-3）、冷却只延长（S-2）、改凭据即复位（S-3②）。
3. 红点：`unread_failures()` 与 `ack_reports()` 是否仍是唯一事实源（不得长出第二本账）；熔断/clean 轮是否**不** ack。
4. 前端门：`--mutation` 45/45 且"无未覆盖断言"；`test_int_v2_frontend_gate.py` 两条门限。
5. 接线护栏：canary 判据在（它一红就说明护栏瞎了）；白名单是否仍满足"多态豁免可核验"。
6. 仍开放的 G1~G4 是否需要升级为本轮范围（尤其 G1 锁脑裂）。

---

# 第五轮**复验之后**的补做（S-13 ~ S-18，2026-09-28）

> 第五轮三角色复验（`docs/changes/reviews/{eng}-accept-5a.md`、`eng-accept-5b.md`、
> `ix-accept-5.md`、`PM-accept-5.md`）判定为 **有条件通过 / 有条件通过 / 不通过（徽章与门）/ 有条件通过**。
> 它们抓到 6 项新问题（其中 2 项是我本轮修复自己引入的），已逐条修完并红证。
>
> 补做后的机械门（同一次运行）：
> - `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest` → **673 passed**（补做前 667）
> - `node scripts/verify_v2_frontend.mjs <overview>` → **实测 62 项，失败 0 项**
> - 同脚本 `--mutation` → **可红 50/50；每条断言都有对应变异**
> - `.venv/bin/python scripts/ui_verify_v2_visible.py --mutation` → 后端出口 **12/12**
> - 全程 `ls data/usage | grep -c ops` → **0**（未再污染用户目录）

| # | 问题（谁抓到） | 落点 | 判据 | 撤修复红证 |
|---|---|---|---|---|
| S-13 | `ack_reports()` 分两次读文件：`cleared` 与水位可能来自不同快照，**两次之间别的进程追加的行被水位吞掉**（eng-5b 实测） | `ops/runner.py:489 _backlog()`（单次快照），`:522 ack_reports` 用它 | `test_ack_does_not_swallow_a_row_appended_mid_ack`（在读之后真往文件追加一行） | 改回"再读一次" → 报 `并发追加的行被水位吞了`（实测 `0 == 1` 红） |
| S-14 | 连接身份指纹用**原串** base_url 且不含 protocol，而 `main.py:222` 判适配器复用时 `rstrip("/")` 视为同一条 → 用户补一个尾斜杠就把 401 判死的凭据放回生效集（eng-5a 实测） | `core/resources.py:21 _conn_fingerprint`（protocol + 归一化 base_url + key） | `test_cosmetic_url_change_does_not_revive_a_dead_credential` + 正向对照 `test_credential_change_still_revives_after_a_url_edit` | 换回原串 → 断言 `active == invalid` 红 |
| S-15a | 两条到期路径语义不同：选路归位不清原因、快照归位清 → 有流量的资源被永久钉在旧故障原因上（eng-5a） | `core/resources.py:425 _lift_if_expired()`（两条路径共用） | `test_both_expiry_paths_agree_on_the_recovered_row`（分别只走选路 / 只走快照，比对同一元组） | 让任一条路径改语义即红 |
| S-15b | `ops-results-*.jsonl` 与水位文件**无保留策略** → 用户数据目录每天涨一个文件（eng-5b） | `stats/events.py:96`（前缀取 `stem.rsplit("-",1)[0]`，纳入 `ops-results`） | `test_ops_results_are_pruned_by_the_retention_policy`（走公开入口 `EventLogger.start()`） | 恢复原前缀解析 → 报"过期 ops-results 未清理"。**这条判据同时抓出我自己写错的两处前缀/日期解析**（`switch-events` / `ops-results` 名字里带连字符） |
| S-16 | 假件契约不符（`_FakeMgr.bench` 返回 None，真实是 bool）、恒真搭车断言、`DEFAULT_CONFIG_PATH` 等 5 个**死常量**无人报（PM/eng-5a） | `config/loader.py`（删 cwd 相对死常量）、`adapters/__init__.py`+`core/ir.py`+`upstream/zcode/claim.py`（删 4 个死常量）、`tests/unit/test_v2_wiring_guard.py`（覆盖面扩到模块级 UPPER_CASE 常量 + 假件契约注释） | `test_guard_catches_a_planted_dead_method` 扩到常量（死常量必须被抓、被用的不许报） | **canary 第一次跑就抓到我的漏洞**：常量定义行自身被当成引用 → 补 `def_lines` 排除 Assign 定义行 |
| S-17 | `mgw setup` 第三桶把用户指到「模型资源」页看「最近错误」，而该列长在「总览」（ix 实测 `grep -c 最近错误 pages/resources.js` → 0）；页名在两处各写一份，改错没人红；降级写盘后最后一行只有"✓ 成功"；jsonl 里熔断轮与 clean 轮不可分辨 | `core/resources.py:155 ROUTE_POOL_PAGE / RESOURCE_PAGE / OVERVIEW_HEALTH_PAGE`（单一事实源，`main.py` 与 `cli_setup.py` 共用）、`cli_setup.py:78/:176`、`ops/base.py:45 inactive_reasons` 落盘 | `test_route_copy_names_the_page_that_actually_hosts_the_column`（文案点到的列 ↔ js 文件真有其列，双向）+ 熔断轮落盘含"熔断"断言 | 删 `"inactive_reasons"` 序列化 → 报"熔断轮没落盘原因"；把指路改回「模型资源」页 → 交叉核对判据红 |
| S-18 | 徽章四态直出英文枚举（`invalid` 不表达"判死/需换 Key/不会自愈"）、未知状态染红、`cooldown=0` 一行两口径；前端门两条逃逸（按 kind 过滤 warnings、加载即 POST ack） | `web/static/js/pages/dashboard.js:110 statusBadge`（可用/冷却中/已判死/停用 + 处置提示；未知态中性）、`scripts/verify_v2_frontend.mjs` 新增 `A15/C9/C10/C11/I9` | 50 个变异里含 ix 的三条逃逸（ESCAPE-1 filter、ESCAPE-2 加载即 ack、cooldown=0 归正） | `--mutation` 逐条要求指定断言变红，**50/50**；两条 over-claim 的 kills 列表在实测后收窄（`invalid→停用` 不该杀 C9、改 default 不该杀 C1/C5） |

## 本轮补做的自我交代

1. **我自己引入的两处缺陷**（S-15b 的前缀解析、S-16 的"常量自引用"）都是**新写的判据第一次跑就抓出来的** —— 记在这里，避免下轮把这类"修复带伤"当成既有事实。
2. **一处决策反转**：S-4 我上一轮把"到期归位清 `last_error`"定为修法，第五轮面板指出这消灭了用户唯一的事后线索，而"现在能不能用"本来就由 `status`/「冷却剩余」表达 → 改回**保留**（语义是「最近错误」= 历史），并在 `test_expired_cooldown_reads_as_available_without_traffic` 里把新语义钉死（含理由注释），不是简单删断言。
3. **两处曾只登记不修**（等用户裁决）：E5 跨午夜文案歧义、G1 锁退路脑裂 —— 第六轮已由用户分别裁决为「跨日才显示『至 明日 HH:MM』」与「fail closed：主目录不可写即拒跑本轮」，落地见上表 S-21 / S-22，PRD 归档为 **v1.17 / Q28-⑦**（两处都**推翻**了我此前的做法：S-21 推翻 §17 的「写入时烘死时刻」，S-22 推翻第四轮我自己加的 `/tmp` 退路）。

# 第六轮复验的补做（S-19 ~ ，2026-09-28）

> 第六轮面板（`docs/changes/reviews/eng-accept-6.md`、`ix-accept-6.md`）在 S-13~S-18
> 全部复算通过的前提下，另抓到 1 项**会误导用户操作**的文案缺陷（徽章把 401 判死
> 说成"打开开关即恢复"）+ 4 项门本身的逃逸/缩水。逐条修完并撤修复取红证。
>
> 补做后的机械门（同一次运行，数字全部取自runner自身输出）：
> - `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest` → **683 passed**（第六轮补做前 673：S-19 +6 / S-21 +3 / S-22 +3−2，数字一律取自 runner 自身输出）
> - `node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json` → **实测 67 项，失败 0 项**
> - 同脚本 `--mutation` → **可红 56/56；每条断言都有对应变异**
> - 全程 `ls data/` 无新增文件、`find data -newermt` 只命中 `gateway.log`（未污染用户目录）

| # | 问题（谁抓到） | 落点 | 判据 | 撤修复红证 |
|---|---|---|---|---|
| S-19a | 「停用」徽章写"资源开关已关闭 —— 打开开关即恢复"，而 **401 判死的资源也聚合成 `disabled`**（`scheduler.py:403` AUTH → `disable()`）：用户照着提示去翻一个**已经打开**的开关，问题一点没动（ix 严重项） | `web/static/js/pages/dashboard.js:136`（同时给两种成因与各自处置 + 指向「最近错误」列）、`:135`（`invalid` = 404 模型名无效 → 换**映射**去「资源池设置」页，不是换 Key） | 前端门 `C3/C4` 拆成 **可见文案与 title 分开判**（`visible()` / `titleOf()`），文案直出英文枚举不再因为 title 里有同词而蒙过 | 变异表新增 3 条：`invalid→停用`、`invalid 指错页（资源池设置→模型资源）`、`disabled 回到只说开关` → 分别打红 `C3`/`C3`/`C4`；**56/56 全红** |
| S-19b | 「冷却剩余」列与徽章 title 各算各的（列 floor / 徽章 ceil、非冷却行照印秒数、已到期印"剩余 0s"） | `dashboard.js:112 fmtCooldown()`（唯一口径，徽章与列共用）、`:103` 非 `cooldown` 一律 `—` | 前端门 `C12`（同一份 ms 两处同串）/`C13`（非冷却行不得有秒数）/`C14`（未知态 title 说明），并把**真源码**注入 harness（不许在 JS 里重写一份格式化函数） | 变异：丢单位 → 打红 `B4/C6/C12`；非冷却也印秒数 → `C13`；删未知态说明 → `C14`；"已到期"改回 `剩余 ${left}s` → `C11` |
| S-19c | 页名第 4 份副本（`main.py:339` 参数卡告警硬写「资源池设置」页）+ **门只看前端**：把 `ROUTE_POOL_PAGE` 改成一个不存在的页名，前端门 65 条判据一条都不红（ix escape） | `main.py:330` 改用常量；前端门新增 `J1`（侧栏 `<span>` ↔ `PAGE_META.title` 同源）与 `J2`（剥注释后，前端 + `core/resources.py` + `cli_setup.py` 里所有「X」页必须命中真导航项） | `J1/J2`；FILES 扩到 Python 侧文案，使**后端文案**也进变异覆盖 | 3 条新变异：侧栏改名 → `J1+J2`；只改 `PAGE_META` → `J1`；`ROUTE_POOL_PAGE` 指向不存在的页 → `J2` |
| S-19d | 降级提醒只在"某处提到过"层面被断言，漂出「将写入」那一行不会红（ix escape） | `cli_setup.py:180`（提醒仍在那一行内） | `test_setup_degrade_warning_travels_on_the_write_line`（只看 `startswith("将写入")` 那一行，且同串含"条系统模型"） | 把 `degrade_note` 挪成独立一行 → 报 `assert '⚠ 未取到运行态' in '将写入：models.json（2 条系统模型）'`，恢复后同轮转绿 |
| S-19e | 归一化口径仍有第二/第三份：`_conn_fingerprint` 用 `.strip().rstrip("/")`，`main.py` 判适配器复用只 `.rstrip("/")`，两个适配器构造函数又自己 `rstrip("/")`（S-14 修了一半） | `core/resources.py:21 normalize_base_url()`（唯一口径）→ `:33` 指纹 / `main.py:237` 复用判定 + 建适配器时先归一化 / 两个适配器 `self.base_url` | `test_url_normalization_has_exactly_one_source`（含幂等断言）+ `test_whitespace_url_edit_does_not_revive_a_dead_credential` + `test_whitespace_url_edit_reuses_the_adapter`（真 `_apply` 两轮，比对象同一性） | 撤 3 处归一化 → 两条红（复活判死凭据 / 重建客户端）；单撤 `main.py` 判定 → 复用用例红 `assert rt.adapters["res-a"] is before` |
| S-19f | **我在红证里撞出来的新缺陷**：`sync_circuit()` 不看熔断是否生效，只要配了资源就打「全局风控仍在生效」——`sync_circuit_to_runtime` 返回 `(0,0)` 同时涵盖"**根本没熔断**"，于是每次正常启动谎报一次风控状态（同一处症状是空括号 `（）`，因为未熔断时 `reason()` 为空串） | `main.py:111`（`if not circuit.active(): return`，并把 `%s` 与 f-string 混用改成纯 `%s`） | `test_startup_does_not_claim_a_breaker_that_is_not_there`（未熔断不得出现"全局风控"字样）+ 反向对照 `test_empty_account_match_while_breaker_active_still_leaves_a_trace`（熔着却没号对上**仍须**留痕且原因非空） | 撤掉 `active()` 判据 → 前者红并打印出 `（）`；只留"静音"会把后者打红，两条互为对照 |
| S-20 | 接线护栏的常量覆盖面有两个免检口：① 只看 `ast.Assign`，**带类型注解**的 `X: int = 1` 整体排除；② 额外要求名字里含 `_`，`TIMEOUT = 30` 这类单词常量不进覆盖面。同名歧义判据也只作用于类方法（`cls` 为空直接放行）→ 两家各一个同名常量会互相顶替成"已接线"。canary 快照还在 import 期一次算死，**canary 自己写进包里的文件对它不可见**（= 自证判据也是假的） | `tests/unit/test_v2_wiring_guard.py`：`_assigned_names()`（Assign/多目标/AnnAssign 同一把尺，纯声明 `X: int` 不算符号）、`_public_symbols()` 去掉 `_` 过滤、`_package_symbol_names()` 纳入模块级公开常量、`_symbol_names()` 改成按文件签名重算的缓存、`_referencing_files_named()` 的歧义豁免扩到常量并**写明仍存盲区**（"该文件与本模块有 import 关系"≠"这个访问点来自本模块"；注册表/getattr/`*` 解包看不见 → 判死前必须人工确认） | canary 补种 4 个死符号 + 4 个活对照：`DEAD_ANNOTATED_CONSTANT` / `TIMEOUT`（b.py 用自家的同名 `TIMEOUT` 也不许顶替）/ 原有两条；断言"活的不得被误报"与"死的一定要被报"成对出现 | **四个变异分别取红**（逐个施加、逐个复原）：① 去掉 AnnAssign 分支 → `DEAD_ANNOTATED_CONSTANT 未被报出`；② 加回 `"_" in name` → `TIMEOUT 未被报出`；③ 歧义判据改回只管方法 → `TIMEOUT 未被报出`（被 b.py 顶替）；④ 缓存改回 import 期快照 → 同样顶替报绿。恢复后同轮 `6 passed` |
| S-20 附带产出 | 覆盖面一放宽，护栏**立刻抓到两个真实死符号**（都不是我本轮改动的产物）：`ops/base.py NEEDS_ATTENTION: dict[str,bool]`（AnnAssign，旧判据整体看不见；全包零引用）、`main.py CONFIG_ENV = paths.CONFIG_ENV`（无下划线，纯 re-export，全包零引用；唯一"提及"是 `paths.py:23` 的一句注释） | 两处删除；`ops/base.py` 把"只有 failed 需关注"的规则留在它**生效**的地方（`runner.unread_failures` 只数 `failed`），注释指回该函数；`paths.py:23` 注释改成"全包唯一事实源" | `test_every_public_symbol_has_a_referrer` 在删之前红（`unwired = {'ops/base.py#NEEDS_ATTENTION'}` → 再报 `main.py#CONFIG_ENV`），删后转绿；`grep -rn NEEDS_ATTENTION\|CONFIG_ENV`（排除 `.venv`）确认无残留引用 |
| S-21（用户裁决） | 熔断恢复时刻跨午夜有歧义：23:50 熔 30 分钟写「至 00:20」，用户在 23:55 读到的是**已经过去**的钟点；而时刻是 `enter()` 时**烘死进字符串再落盘**的，同一条状态在午夜前后不可能都对 | `upstream/zcode/quota.py:335 until_label()`（跨日才加「明日」，不写日期）、`:352 _with_until()`、`enter()` 只存裸原因、`reason()` **读时渲染**（CLI ⚠ 块 / `last_error` / 日志同走 `circuit.reason()` 一份口径） | `test_recovery_clock_says_next_day_when_it_crosses_midnight`（冻结 23:50 → `，至 明日 00:20`）+ `..._stays_plain_clock_time_within_the_day`（12:00 → `，至 12:30` 且不得有「明日」）+ `..._is_recomputed_at_the_moment_of_reading`（同一份 `circuit.json` 在 23:55 读=「明日 00:20」、00:05 读=「00:20」，并断言文件里不含「明日」）；三条 `$` 锚定的旧正则放宽为 `，至 (?:明日 )?\d{2}:\d{2}`（否则深夜跑测试自己假红） | 变异 B（删「明日」分支）→ 跨日 + 读时两条红；变异 A（时刻烘回写入时）→ **只有**读时那条红（正是"为什么必须读时渲染"的判据）；恢复后同轮 `tests/unit/test_v2_circuit.py` 36 passed |
| S-22（用户裁决） | 运营互斥锁在主目录不可写时退 `/tmp`：互斥"看着成立"，但 `/tmp` 人人可写、重启即清，且数据目录不可写意味着同轮的熔断文件/`ops-results` 也会失败；退路再失败时 `try_acquire()` 恒 False → cron **每个 tick 静默跳过** = 运营停摆而进程正常 | `ops/runner.py`：删 `fallback_lock_dir()`；`_acquire_file()` 单目录、OSError 一律拒；新增 `AccountLocks.usable()`（把「别人正持有」与「建不起来」分开）；`run_once()` 开跑前探测 → 参与方逐个 `report.add(OpResult(a, "failed", …))` 并整轮返回；`PlanLock.usable()/lock_dir` 透传；`Scheduler._tick()` 遇「建不起来」计 `errors` + 留日志 | `test_unwritable_lock_dir_refuses_instead_of_granting`（含 `not hasattr(runner_mod, "fallback_lock_dir")` 的裁决回归钉 + 恢复可写的正向对照）、`test_lock_dir_that_cannot_be_created_denies_instead_of_granting`（`mkdir` 就失败的另一半 OSError）、`test_run_once_refuses_the_whole_round_when_locks_are_unusable`（**零次上游发起** + 记 `failed` 不是 `skipped` + 原因含「不可写」）、`test_scheduler_tick_tells_unusable_lock_from_a_busy_one`（正被持有 → `errors==0`；建不起来 → `errors==1` 且不继续跑） | 整体退回 S-22 前状态（恢复 `/tmp` 退路 + 撤 `run_once` 探测 + 撤 `_tick` 成因区分）→ **四条同时红**；复原后同轮 `67 passed`，并清掉变异期间落在 `/tmp/mgw-ops-locks-<uid>` 的 5 个残留锁文件 |


## 第六轮补做期间新登记、**尚未修**的相邻缺陷（不是被跳过，是等着定夺）

| # | 缺陷 | 证据 | 为什么不随手修 |
|---|---|---|---|
| N-1 | 热重载换下的出站适配器**从不 `aclose()`**：`Runtime._apply()` 直接 `self.adapters = new_adapters`，只有 `Runtime.aclose()`（进程关停）才关。每改一次 `base_url`/`protocol` 就留下一个 httpx 客户端（开 TLS 指纹时是 curl_cffi 客户端，更重） | `main.py:249`（赋值点）↔ `main.py:368-376`（仅关停路径关）；S-19e 的红证跑动时该行为被我撞出 | `_apply()` 是**同步**路径而在途请求可能正持有旧适配器：立即 close 会打断正在流式响应的调用（比泄漏更糟）。正确解法要选一种"延迟/引用计数关闭"策略（`aclose` 投递到事件循环 + 等在途计数归零，或让适配器引用计数）—— 属设计决策，请用户定夺后单独立项 |

# 第七轮复验的补做（S-23 ~ S-27，2026-09-28）

> 第七轮面板：`pm-accept-7.md` **有条件通过（1 阻塞）**、`eng-accept-7.md` **有条件通过（1 阻塞）**、
> `ix-accept-7.md` **不通过（1 项产品阻塞 + 6 条门的语义逃逸）**。
> PM 与 ix **各自独立**打到同一个缺陷（S-23：只把 CLI 那侧改成读时渲染，界面那一列还烘死着）——
> 这说明 S-21 上一轮**只修了一半**就自称收敛，是本轮最该记的教训。
>
> 补做后的机械门（数字一律取自 runner 自身输出）：
> - `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest` → **693 passed**（第七轮前 683）
> - `node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json` → **实测 69 项，失败 0 项**
> - 同脚本 `--mutation` → **可红 62/62；每条断言都有对应变异**
> - `.venv/bin/python scripts/ui_verify_v2_visible.py --mutation` → 后端出口 **12/12**
> - `find data -newermt "2026-09-28 13:50" -type f` → **空**（未污染用户数据目录）

| # | 问题（谁抓到） | 落点 | 判据 | 撤修复红证 |
|---|---|---|---|---|
| S-23 | 「最近错误」列的恢复时刻仍是**写入时烘死**：23:50 熔 30 分钟，`circuit.reason()` 到 00:05 会说「至 00:20」，而那一列还挂着「至 **明日** 00:20」——**两个出口互相矛盾**，且因 S-15"到期不清原因"会长期挂着（PM B-1 与 ix B-1 独立命中） | `core/resources.py`：`without_clock_suffix()`（剥掉写入侧带来的旧尾巴）+ `fmt_recovery_clock()`（唯一口径，跨日才加"明日"）+ `_worst_error_entry()`/`_rendered_last_error()`（**冷却中才配钟点，到期只留原因**）；`quota.py`：`enter()` 与 `apply_to_resource()` 都只存裸原因、`_load()` 归一化旧格式 | `test_health_card_renders_the_clock_at_read_time`（同一冷却对象在 23:55 / 00:05 / 到期后三种读时刻各说对各的话，并与 `fmt_recovery_clock` 交叉核对）；`test_legacy_circuit_file_does_not_double_the_clock`（旧文件只有一份钟点，且 `mark_called()` 回写时把旧格式**归一化**掉）；boot 用例改判"内存里裸、HTTP 响应里带钟点" | 三次独立变异分别取红：只撤快照渲染 → 5 条红；只撤 `apply_to_resource` 的剥尾 → 3 条红；只撤 `_load` 的剥尾 → 旧格式那条红（复现点正是"下一次写盘把旧格式又存回去"）。全部复原后同轮 `43 passed` |
| S-24 | `path.unlink(missing_ok=True)` **只吞 FileNotFoundError**：跑完第一个号后锁目录变只读 → `PermissionError` 顶穿 `run_once`、穿出 `Scheduler._tick` 的 `finally` 与 `loop()` → **定时器任务当场死亡**；且 `PlanLock.release()` 里文件释放先抛 → `threading.Lock` **永不放开**。权限修好后 `usable()` 已 True，运营却再也不跑（eng 唯一阻塞 BLK-1） | `ops/runner.py`：`_release_file()` 吞 OSError 并留日志（锁文件由 `LOCK_MAX_AGE_S` 超龄回收兜底）；`PlanLock.release()` 用 `try/finally` 保证进程内锁必放；`_tick()` 的收尾 `except Exception` → 计 `errors` + 留日志，不终止调度 | `test_mid_round_write_failure_does_not_strand_the_locks`（持有后 chmod 只读 → 释放不抛 + 同进程能重新领 + threading 锁可再获取）、`test_scheduler_task_survives_a_failing_lock_release`（走真 `Scheduler.start`，第二轮仍跑 + `errors>=1` + 任务存活） | 整体退回三处修复前状态 → 两条同时红（第二条打印 `一次释放失败就杀死了定时器：[1]`）；复原后同轮 `69 passed` |
| S-25 | 前端门**对字面串硬、对语义等价改写没有抵抗力**（ix 交出 5 类"改了源码门仍全绿"）：① `fmtCooldown` ceil→floor（C12 只比对一致性 + fixture 全整秒）；② invalid 补一句「也可先换 Key 重试」（C3 只禁字面「更换 Key」）；③ `disabled` 文案按 `r.account`/`r.C` 分叉（C 段 fixture 没有这些字段）；④ `resources.js`/`main.js` 根本不在 J2 扫描清单里；⑤ 页名改用『』括号即漏检 | `scripts/verify_v2_frontend.mjs`：C 段 fixture 换成**生产行形状**（rid/name/vendor/account/C/in_flight/models/last_error 齐全）；新增 `C15`（**向上取整**钉死：1799999→1800s、1→1s）与 `C16`（徽章是 status+冷却时长的**纯函数**，其余字段不得改变输出）；C3 的禁令改成 `!/换\s*Key/`；`J2` 的 copySources 补 `resources.js`+`main.js`，括号正则同时认 `「」`与`『』`，并把"抽取总数 ≥8"作防空过条件 | 6 个新变异（每条对应 ix 的一种逃逸）：floor 版取整、invalid 加换 Key、disabled 按 `r.C` 分叉、resources.js 指不存在的页、main.js 指不存在的页、cli_setup 用『』写页名 | `--mutation` **62/62 全红**（撤修复前是 56/56 且 C15/C16 无变异 → 现补全）；`实测 69 项` 全绿；pytest 侧把下限抬到 68 条断言 / 60 个变异 |
| S-26①⑤ | `circuit.json` 里 `until_ms` 是字符串时 `float()` **崩栈**（`mgw zcode claim` 整条 traceback）；`_load()` 用 `mtime == 上次` 去重读盘 → 时间戳只到秒的卷上，别的进程**同一秒内**写的新熔断看不见 | `quota.py`：`_ms_or_zero()` 容错读取（坏值=无熔断，不崩）；`_load()` **每次真读文件**（删掉 `_loaded_mtime` 整套缓存，含 `_save` 里的回写） | `test_malformed_circuit_numbers_do_not_crash_the_cli`、`test_breaker_written_within_the_same_second_is_still_seen`（`os.utime` 把 mtime 钉死成同一个值，第二次改写仍要被看到）；`test_cooldown_enters_and_expires` / `test_throttle_blocks_rapid_calls` 改成走**注入时钟**而不是手改 `_cd`（旧写法在"必回读"下会被覆盖，那正是我们要的行为） | 退回 pre-S-26⑤ 的整个 `_load` → 只有 `same_second` 那条红（另外 3 条在两种实现下都绿，说明它们是**精确判别**而非泛泛变红）；坏值用例撤 `_ms_or_zero` 后报 `ValueError` |
| S-26② | base_url 归一化的**第四、第五处**：`cli_probe.py` 与 `upstream/zcode/claim.py` 各自 `rstrip("/")` → 粘贴带空格的 URL 时"网关能跑、probe 报 UnsupportedProtocol" | 两处改用 `core.resources.normalize_base_url` | `test_base_url_normalization_has_no_second_implementation`：**全包扫描**"不许出现第二份 `base_url...rstrip("/")` 写法"（形态级判据，新增即红），外加 `ZCodeClaimClient` 的行为断言 | 把 `cli_probe.py` 改回 `rstrip("/")` → 判据直接报 `出现了第二份 base_url 归一化实现：['cli_probe.py:33']` |
| S-26③ | 401→`disable()` / 404→`invalidate()` **只改状态不记原因** → 徽章写着"见「最近错误」列"，用户去看那一列是空的 `—`，提示把人支到不存在的地方（ix/PM 双向命中，S-19a 的另一半） | `core/resources.py`：`disable(state, reason="")` / `invalidate(state, reason="")` 写 `last_error`；`core/scheduler.py` 四个判死出口把 `summary` 传下去 | `test_killed_resources_carry_the_reason_the_badge_points_at`（401/404 各跑真实 `execute_chat`，断言**快照里**该列非空且含上游错误码字样） | 把两处 `if reason:` 改成 `_ = reason` → 报 `401 判死但「最近错误」为空：{... 'last_error': None ...}`；复原后 `22 passed` |
| S-26④ | `write_report()` `except OSError: return None` **静默**：顶栏红点以该文件为唯一事实源（S-5 裁决），写不进去=这一轮失败对用户彻底不存在；CLI 还继续把用户指到那个没有内容的文件 | `ops/runner.py`：失败记 `logger.error` 并写明"红点不会点亮"；`cli_zcode.py`：`results_path is None and report.failed` 时向 stderr 打印「未能写入 …（数据目录不可写？）→ 顶栏红点不会记录这些失败」 | `test_write_report_failure_is_logged_not_swallowed`（含"恢复可写就不再报错"的正向对照）、`test_claim_says_out_loud_when_the_round_was_not_persisted` | 撤掉 logger.error 与 CLI 那段 → 两条同时红；复原同轮 `31 passed` |
| S-26⑥ | 接线护栏两处假绿：① 模块级常量在"全包唯一名"时**任何同名局部变量**都算引用；② 类方法歧义判定用 `cls in text` **子串**匹配，别人 docstring 提一句类名就把死方法洗白 | `tests/unit/test_v2_wiring_guard.py`：`_home_import_forms()`（跨文件引用常量必须有 `from home import name` 或 `import home`+`别名.name` 两种真实形态之一）、`_mentions_identifier()`（类名要作为 AST 标识符出现才算写过）、`_tree()` 按 (大小,mtime) 缓存解析结果 | canary 再补两种逃逸种子：`LOCAL_MASK`（c.py 里同名局部变量顶替）、b.py 的 docstring 里写 `CanaryA`；两条新断言与"活的不得被误报"成对出现 | 单独撤 ① → `TIMEOUT/LOCAL_MASK 未被报出`（被顶替）；单独撤 ② → `A.claim 未被报出`；两条同时撤 → 同上。**顺带抓到 3 个真实死常量**：`main.py` / `cli_setup.py` / `cli_probe.py` 各有一份从不被引用的 `DEFAULT_CONFIG = paths.default_config_path()`，已删 |
| S-27 | `tech-design.md:1271` 仍写死"值为 `ZCode 风控熔断（30min，至 HH:MM）`"（写入时烘死的字面），全文零处 Q28-⑦ 注记 → 后来人照字面实现会把 S-21/S-23 一起回退（PM） | `docs/specs/tech-design.md` §17 该表格行就地标 ⚠️ + 表下补"实现期背离"注记（读时渲染 / 唯一口径 / 到期不配钟点 / 请勿改回），格式与 Q28-⑤ 对 §12.3 的处理一致 | 人工核对：`grep -n "Q28-⑦" docs/specs/tech-design.md` 命中 2 处（表格行 + 注记首行） | 文档改动，无红证；风险由注记本身承担 |
1. **S-21 被我"修了一半"就当收敛**（第七轮 PM/ix 各打到同一处）：只改了 `circuit.reason()`，界面出口 `last_error` 完全没动 → 同一屏两个说法。教训写进判据：`test_health_card_renders_the_clock_at_read_time` 里把两个出口**逐字比对**，不再靠人记"哪些出口要同步"。
2. **两条既有测试改成走注入时钟**（`test_cooldown_enters_and_expires` / `test_throttle_blocks_rapid_calls`）：它们手改 `cm._cd`，在"每次判定必回读文件"的新实现下会被覆盖——被覆盖**正是**要的行为，所以这是改判据而不是让步；语义（到期自动失效 / 过 10s 放行）保持。

# 第八轮复验的补做（S-28 ~ S-31，2026-09-28）

> 第八轮面板（4 个子 agent 分片）：`eng-accept-8a.md` **不通过（1 阻塞）**、`eng-accept-8b.md`
> **有条件通过（1 阻塞）**、`ix-accept-8.md` **不通过（13 条门逃逸）**、`pm-accept-8.md` **不通过（1 阻塞）**。
> PM 与 eng-8a **再次各自独立**打到同一处 —— S-23 修对了**公式**、用错了**时基**。
>
> 补做后的机械门（数字全部取自 runner 自身输出）：
> - `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest` → **701 passed**（第八轮前 695）
> - `node scripts/verify_v2_frontend.mjs <overview>` → **实测 76 项，失败 0 项**
> - 同脚本 `--mutation` → **可红 76/76；每条断言都有对应变异**
> - `.venv/bin/python scripts/ui_verify_v2_visible.py --mutation` → 后端出口 **12/12**
> - `find data -newermt "2026-09-28 15:00" -type f` → **空**（未污染用户数据目录）

| # | 问题（谁抓到） | 落点 | 判据 | 撤修复红证 |
|---|---|---|---|---|
| S-28 | 「最近错误」列的钟点把 `cooldown_until` 当**墙钟**格式化，而生产 `ResourceManager()` 默认钟是 `time.monotonic`（开机以来秒数，本机约 70 万）→ 真 `create_app` 回环里 15:18 显示「至 10:20」（真实恢复 15:48），「明日」分支在生产几乎永不触发；**693 条判据全绿是因为每条都注入了 epoch 钟**（PM 与 eng-8a 各自独立命中） | `core/resources.py`：`_rendered_last_error(entries, status, remaining_ms, wall_now=None)` —— 钟点由 `time.time() + 剩余` 倒推，**与 manager 的时间基无关**；`wall_now` 仅为跨午夜可测而注入 | `test_recovery_clock_is_rendered_from_the_wall_clock_not_the_manager_clock`：**故意不注入时钟**，断 `mgr.clock.__name__ == "monotonic"` 后比对 `strftime(time.time()+剩余)`，并反向断"单调钟数值格式化出来的那个假钟点不得出现" | 把渲染改回 `fmt_recovery_clock(e.cooldown_until)` → 新用例红（外加原有 2 条同时红）；复原同轮 `43 passed` |
| S-31 | 同一行两列打架：「冷却剩余」取**所有条目的最大值**，而恢复钟点取"最严重条目"自己的到期时间 → 出现「1800s 后自动回池」配「至 23:51」（ix-8 用真快照打出来的） | `snapshot_by_resource` 先把 `remaining_ms` 算出来，**两处共用同一个数**；非 `cooldown` 状态一律不配钟点（判死/已恢复都没有"几点恢复"这回事） | `test_the_two_columns_never_disagree_about_the_recovery_instant`（同资源两条映射：60s 退避 + 30min 熔断，断钟点必须等于列上那个剩余量、且不得出现 60s 的钟点） | 撤聚合改回条目级 → 该用例红 |
| S-29 | `run_once` 只在**开跑前**探一次 `usable()`；本轮中途锁目录失去可写性时 `try_acquire()` 的 False 与"别人正持有"共用一条 `skipped` 分支 → 真实 CLI 打印「全部正常，无需处理」、退出码 0、红点 0，而后面几个账号**一个都没发起**（eng-8b 唯一阻塞，与用户 S-22 裁决相反） | `ops/runner.py`：获取失败时**再探一次** `usable()`，不可写则把本账号及其后所有账号记 `failed` 并结束本轮；`LOCK_REFUSAL_PREFIX` 常量供文案判别 | `test_locks_dying_mid_round_fails_the_remaining_accounts_not_skips_them`（第一个号跑完 chmod 只读 → 后续 `failed` 含"中途不可写"、`skipped==[]`、零次发起、第一个号的成功记录不被抹掉）；CLI 侧 `test_claim_head_separates_refused_from_attempted_failures`（抬头分级：「其中 N 个**未发起**」） | 删掉中途探测 → 用例报 `failed 为空、acct-2/acct-3 进了 skipped`；复原同轮 `69 passed` |
| S-30 | ix-8 造 18 个变异、**13 个门仍全绿**（8 个连 `--mutation` 也全绿）。要害五类：① 告警调用被包进 `<!-- -->` → 横幅整块消失而 A 段 15 条全绿；② 页名指向**真实存在但没有该控件**的页面；③ 告警装配地 `main.py` 不在扫描面；④ `stripComments` 按行首字符判注释 → 模板串里的可见文案被当注释删；⑤ `C16` 只是两点纯度测试（按值维/按 ms 量级分叉都看不见）；另有同义词「更换密钥」、去括号页名、`aria-hidden`、`document.title` 许诺界面上没有的动作、指标卡零覆盖 | `scripts/verify_v2_frontend.mjs` 结构性补三层：**⑴ K0~K6 执行真实 `renderDashboard`**（假 DOM 接 innerHTML，载荷由**真实端点** `TestClient` 现取）→ 判据下在**产出 HTML 的可见文本**上：横幅条数/`aria-hidden`/`display:none`/指标卡八张/健康表挂得上/每个 `#/路由` 都是真导航项/冷却行**肉眼**可见恢复时刻；**⑵** 注释剥离改成按字符扫描（模板串与字符串内部的 `#`/`//` 是正文），页名正则同时认 `「」`/`『』`**与不带括号**的「到 X 页」，copySources 补 `resources.js`/`main.js`/`main.py`/`api.js`；**⑶** `C16` 改成 **4 状态 × 4 组字段形态 × 5 个冷却量级**的矩阵，`C3` 的禁令扩到 `换\s*(Key|key|密钥|api key)`；控件级指路由 pytest 侧 `test_route_copy_points_at_a_page_that_actually_hosts_the_control` 承担（动作→文件对照表 + 实现标记必须还在） | 13 条新变异逐条要求指定断言变红（注释包横幅、`aria-hidden`、少一张指标卡、链接指不存在路由、main.py 坏页名、模板串内被当注释的可见文案、无括号页名、按账号值分叉、按量级 floor、同义词、渲染整体抛错、健康表不再挂上、错误列改印状态码）→ **可红 76/76**，`实测 76 项` 全绿 | 变异表本身即红证（每条锚点命中数≠1 也判红）；另外把 pytest 侧下限抬到 **75 条断言 / 74 个变异**，门被删窄会红。`test_route_copy…` 的红证：把徽章的「模型资源」页改成「资源池设置」页（页名真实存在）→ 报 `说「更换 Key」却指「资源池设置」页`；复原转绿 |
| S-26 追加（8a E-4 / L-1） | ① `until_ms` 为天文数字时照单全收 → 界面显示「剩余几千万年」；② 已过期的熔断 `reason()` 仍挂一个**过去**的钟点，而快照侧同语义已剥掉 → "文件还在、已过点"窗口里两出口又打架 | `quota.py`：`_ms_or_zero(value, now_ms)` 加 `SANITY_HORIZON_MS = 24h`（超界当坏值归 0 + `logger.warning`）；`_with_until()` 在 `until_ms <= now` 时只回裸原因（不再靠调用方先问 `active()`） | `test_absurd_until_ms_is_treated_as_bad_data_not_an_eternal_breaker`（30 天后的时间戳 → `active() is False` + 日志含"不合理"）、`test_expired_breaker_reason_carries_no_past_clock`（过点前带钟点、过点后必须没有） | 两条同时撤（`if False` + 删过期分支）→ 两条同时红；复原同轮 `44 passed` |
| 8a E-1 | `main.py` 判"有没有端点"用原串 `if not r.base_url` → 只填空格的资源被建出一个指向空串的适配器，请求照发、错误直出 httpx 黑话（用户不会想到去补那一栏） | `main.py:232` 改用 `normalize_base_url(r.base_url)` 判空；缺适配器时调度器给的是中文「无可用出站适配器」 | `test_whitespace_only_base_url_gets_no_adapter`（真 `create_app`：空格端点 → **不在 adapters 里**、资源仍在快照上不静默消失） | 判空改回 `if not r.base_url` → 报 `空端点仍建出了适配器：['res-a']`；复原 `15 passed` |
| 8a E-3 | 我 S-23 的插入把 `_SEVERITY` 写了**两遍**（后一份遮蔽前一份）——同一张表两处定义正是"改一处漏一处"的前夕 | `core/resources.py` 删重复定义，只留一处 | 接线护栏 + `grep -c "^_SEVERITY = "` 现为一处；`test_invalid_outranks_cooldown_in_the_aggregate` 继续钉语义 | — |

## 第八轮的自我交代

1. **同一个坑摔了两次**：S-21/S-23 都是"改了文案的算法、没管它的时间基 / 没管第二个出口"。两次都是面板独立打到，说明我的自审缺一条固定动作——**每改一处用户可见文案，先把"这句话还会从哪个出口出现"列全再动手**。本轮起把"两出口逐字比对"写成判据（不靠自觉）。
2. **前端门的假绿根因是判据层级**：A/B/C 段全在"直接调用函数"这一层，所以"函数对、调用点坏"永远红不了。本轮补的 K 段把判据下移到**执行页面装配后的产出 HTML**，并把判据对象从"整行字符串"收紧到"剥掉标签后的可见文本"（我自己第一版又把钟点判在了 `title` 属性上，被自己的变异打红后才收紧）。

# 第九轮复验的补做（S-32 / S-33，2026-09-28）

> 第九轮：`pm-accept-9.md` **通过（0 阻塞）**、`eng-accept-9.md` **有条件通过（0 阻塞，6 条登记）**、
> `ix-accept-9.md` **不通过（7 条阻塞：23 个变异里 16 个逃逸，14 个连"实测+变异"两态都全绿）**。
>
> 补做后的机械门（数字取自 runner 自身输出）：
> - `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest` → **703 passed**
> - `node scripts/verify_v2_frontend.mjs <overview>` → **实测 79 项，失败 0 项**
> - 同脚本 `--mutation` → **可红 87/87；每条断言都有对应变异**
> - `.venv/bin/python scripts/ui_verify_v2_visible.py` → 后端出口 **12/12**
> - `find data -newermt "2026-09-28 15:30" -type f` → **空**

| # | 问题（谁抓到） | 落点 | 判据 | 撤修复红证 |
|---|---|---|---|---|
| S-32 B-1 | K 段假 `fetch` **不看请求路径** → 把页面改成 `GET("/admin/api/panel")`（后端无此路由，生产整屏空白）仍两态全绿 | `fetchStub` 按路径分派（未知路径回 404 → `api.js` 抛错 → 渲染失败）；新增 `K7` 钉端点字面量 | `K7`；`--mutation` 的 B-1 变异 | 变异"改端点" → K7 红（且渲染抛错被 K0 抓到） |
| S-32 B-2 | 「DOM 里有这段文本」被当成「用户看得见」：`<div hidden>`、内层 `display:none`、正文只进 `title=` 三种藏法全绿；原先 `hiddenish` 第二条正则因属性里夹引号**永不匹配** | 新增**结构化可见性清洗** `visibleText()`：按标签栈丢隐藏元素**及子树**、丢注释/`<script>`/`<style>` 正文、**属性文本不计入**；`K1/K2/K3/K6` 改判清洗后的可见文本 | `K1`（横幅节点数 + **每条 message 必须作为可见文本出现一次**）、`K2`（`冷却中` 要可见）、`K3`（八张卡可见） | 三条变异（`hidden` / 内层 `display:none` / 正文进 title）分别打红 K1；第一版 `isInvisible` 漏了"attrs 结尾的 hidden"，被自家变异当场打回后修正 |
| S-32 B-3 | `copySources` 手写清单漏产地：`logs.js`、`stats.js`、`index.html` 静态文案、`api/admin.py` 全在面外 | 改成**目录自动发现**（`model_gateway/**/*.py` + `web/static/js/**/*.js` + `index.html`，跳过 `__pycache__`/`vendor`），变异模式一并复制这些文件 | `J2`（当前 67 个文件入面、17 处页名引用）；Python 三引号 docstring 与整行 `#` 结构性剥除 | 变异"在 `logs.js` 里指去「运行监控」页" → J2 红 |
| S-32 B-4 | 两条页名正则都强制以「页」结尾 → 把"页"字去掉（`请到「模型映射」为…`，Q24 的死页名）就漏检 | `PAGE_REFS` 增加第三型：**cue 动词（到/前往/请到/打开）后紧跟的括号串**即候选页名（要求串内只有文字/数字/空格，排除「＋ 添加模型资源」这类按钮文案） | 变异"去掉页字并改死页名" → J2 红 | 同左 |
| S-32 B-5 | **页面产出的转义无人验**：A14 吃的是门自己注入的 `esc` 副本，把 `api.js` 的 `esc` 改弱后页面原样输出 `<img src=x onerror=…>` 仍全绿（管理端免鉴权 + 上游错误原文 = 存储型 XSS 面） | 渲染**两次**：真载荷 + 掺入含 `<script>`/引号哨兵的载荷；新增 `K9` 要求页面产出里只剩 `&lt;script&gt;` 且哨兵文案仍可见 | `K9` | 变异"弱化 `api.js` 的 esc" → K9 红 |
| S-32 B-6 | K 段只覆盖少数出口：删掉 `drawHourChart(...)` 调用（图表容器空）无人管；`K4` 只认 `href="#/…"`，`onclick="location.hash='#/audit-log'"` 这种指向不存在路由的动作漏过 | 假 DOM 已接住 `getElementById` → 新增 `K8`（趋势容器 innerHTML > 100）；`K4` 的抽取扩到 `location.hash=` / `location.href=` | `K8`、`K4` | 两条变异分别打红 |
| S-32 B-7 | `C16` 把 `available` 与 `status` 绑死（按 `available` 分叉看不见）；`K6` 只看整行不看**列位**（把恢复时刻搬到别的列仍绿） | `C16` 的矩阵加一维 `available ∈ {true,false}`；`K6` 按表头算出「最近错误」列序，要求钟点**只**在该列可见、且「冷却剩余」列是秒数 | `C16`、`K6`（第一版按 `<x>${cell}` 包裹把属性当正文，被自家 B-8 变异打回后改成重开 `<td`） | 两条变异（搬钟点 / active 分叉）分别打红 |
| S-33 N-1 | `_rendered_last_error(..., wall_now)` 是**只为测试存在的时钟参数**且无护栏：误传 manager 钟（monotonic）就是 S-28 原地复活，而判据仍全绿 | 删参数（生产调用面不存在误用入口），测试侧改 `_frozen_wallclock()` patch `time.time` | `test_recovery_clock_renderer_has_no_injectable_wall_clock`（签名参数集必须恰为 `{entries,status,remaining_ms}`）+ 冻钟版跨午夜用例 | 把参数加回来 → 形状判据红；把渲染改回条目钟点 → S-28 那三条红（上一轮已取） |
| S-33 N-2 | `SANITY_HORIZON_MS` 的失效方向是 **fail-open**：时钟回拨 >24h 或非 epoch 钟注入时，真在熔的 `until_ms` 被判坏值归 0 = 熔断被静默清零，与 S-22 裁决相反 | `quota.py`：`_ms_or_zero` 坏值/超上限返回 `None`；`_load()` 见 `None` **保持内存态并告警**（与"文件读不动"同一类），只有本来无内存态的新进程才按"无熔断"起 | `test_malformed_circuit_numbers_do_not_crash_the_cli`（含"已在熔的进程遇到坏文件必须仍 active"）、`test_absurd_until_ms_is_not_shown_as_an_eternal_breaker` | 把坏值改回归 0 → 两条同时红（实测打印出"文件坏了就把熔断清了 = fail open"）；复原同轮 45 passed |
| S-33 追加 | `cli_probe.py:51` 选链路时用原串判空（E-1 同族）：只填空格的端点被当"有端点"，探测报 httpx 黑话 | 改用 `normalize_base_url(r.base_url)` 判空 | `test_probe_skips_a_resource_whose_endpoint_is_only_whitespace` | 撤判空 → 报"空格端点被当成可用链路" |

## 第九轮的自我交代

1. **门自身也被自己的判据骗了两次**：`isInvisible` 漏"属性串结尾的 hidden"、按 `<x>` 包裹单元格把**属性当正文** —— 两处都是**新加的变异当场打回**的，不是靠读代码发现。记在这里：写"可见性判据"时，属性/文本的边界必须逐字符核，不能靠正则直觉。
2. ix 连续三轮都在打破前端门，说明"门"的强度是**对抗出来的**而不是设计出来的。本轮起把"每条新判据必须同时提交一个能打红的变异"当成硬约束（87/87 就是这个约束的产物），而不是等下一轮再被指出。

# 第十轮复验的补做（S-34 / S-35 + eng R-3，2026-09-28）

> 第十轮面板：`pm-accept-10.md` **通过（0 阻塞，另登记 2 条"坏值路径零痕迹"+ 3 条旧口径残留）**、
> `eng-accept-10.md` **有条件通过（0 阻塞，R-1 坏值方向、R-2 执行全文的保真缺口、R-3 Node 全局泄漏）**、
> `ix-accept-10.md` **不通过（9 条阻塞：造 26 个变异、21 个施加成功，其中 9 条用户可感知的坏改动
> 让门 79 项全绿，且 `--mutation 可红 87/87` 一条都碰不到）**。
>
> 补做后的机械门（数字逐字取自本轮 runner 自身输出）：
> - `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest -p no:warnings` → **705 passed in 135.12s**（第九轮后 703）
> - `node scripts/verify_v2_frontend.mjs <overview>` → **实测 81 项，通过 81 项，失败 0 项**
> - 同脚本 `--mutation` → **可红 100/100；每条断言都有对应变异**
> - `.venv/bin/python scripts/ui_verify_v2_visible.py --mutation` → **后端出口实测 12 项，通过 12 项，失败 0 项**
> - `find data -newermt '-70 minutes' -type f` → **空**（`data/` 全程只读）

| # | 问题（谁抓到） | 落点 | 判据 | 撤修复红证 |
|---|---|---|---|---|
| S-34（eng R-1） | 第九轮记录说过头：`_ms_or_zero` 只对 `"abc"`/截断/数组/超 24h 保持内存态，而 **`null` / 缺 `until_ms` 键 / `NaN`** 三种写法仍把正熔着的熔断静默清零 = fail-open（与 S-22「宁可拒跑也不冒险」相反） | `quota.py::_ms_or_zero`：缺键/`null`/非数字/非有限（`NaN`/`Infinity`）四类**统一返回 `None`**并 `logger.warning`；`_load()` 见 `None` 保持内存态（新进程无内存态才按"无熔断"起）；`last_call_ms` 坏值仍归 0（它只是节流，不清零熔断 = 良性） | `test_missing_or_null_until_ms_keeps_the_running_breaker`、`test_breaker_fields_that_are_only_throttle_stay_benign`（两半都要：坏熔断字段不许清、坏节流字段不许崩） | 把 `raw_value is None` 分支改回 `return 0.0` → `test_missing_or_null_until_ms_keeps_the_running_breaker` 红：`AssertionError: 坏文件把熔断抹掉了：{}`（本轮实测 `1 failed, 4 passed`）；复原同四条 `5 passed` |
| S-35 B10-1a/1b/1c/2/3 | ix：`visibleText()` 是**"隐藏写法"的白名单**（4 条正则、大小写与属性值形状敏感），`opacity:0`、`height:0;overflow:hidden`、`left:-9999px`、`visibility:collapse`、`<template>`、`<noscript>`、裸 `aria-hidden`、大写 `STYLE="DISPLAY: NONE"` 八种全部过关 —— "可见"仍然靠字符串匹配 | 改成**按属性语义判定**：`parseAttrs()` 名/值成对结构解析 → `isInvisible()`（`hidden` 出现即真、`aria-hidden` 非 `false` 即真、`style` 内六类规则，全部小写化 + 空白归一）；`<script>/<style>/<template>/<noscript>` 内容整体不计入可见文本；`class="… hidden"` 不再误判 | `Z1`（**门自己的** 18 例语义自测表，含大写/裸属性/反例）、`K1`/`K2`/`K3`/`K6`/`K8` 全部吃清洗后的可见文本 | 五型变异各打红 K1（`opacity:0` / 大写 / `height:0;overflow:hidden` / `<template>` / 裸 `aria-hidden`）；把 `hidden` 判据摘掉的**门自身变异**经子进程读回 Z1 真变红 |
| S-35 B10-4/5 | K 族内部**口径不一致**：`K6` 的表头列名从原始 HTML 正则抓（不经可见性清洗），`K8` 只看 `chartHtml.length > 100`（完全不做可见性）→ 藏掉「最近错误」表头、图表画了但容器塌成 0 高，都绿 | `K6` 的表头集合改由**可见 `<th>`** 算出（`hidden` 表头 = 该列不存在，列位契约随之判红）；`K8` 要求容器本身可见 + 柱数与数据行数匹配 | `K6`、`K8` | 两条变异：`<th hidden>最近错误</th>` → K6 红；`#hour-chart` 的 `height:160px`→`0px` → K8 红 |
| S-35 B10-6 | `C16` 自称"按其它字段分叉即红"，但矩阵里 `last_error` 最长恰好 40 字 → 徽章按 `length > 40` 分叉两套措辞时矩阵逐字节相同，而真实 429 原文 70~200 字在生产必然出现 | `FULL.last_error` 换成 70+ 字的上游 429 原文；矩阵补**长度维**（4 状态 × 4 字段形态 × 5 量级 × `available ∈ {true,false}`） | `C16` | 变异"40 字以上走另一套说法" → C16 红 |
| S-35 B10-7/8 | 文案产地自动发现只写死 `**/*.py` + `js/**/*.js` + `index.html`：**`base.css` 在 `FILES` 里却不在 `copySources` 里**，`web/static/templates/*.html` 整目录在面外 —— 而 `main.py` 是 `StaticFiles(directory=static_dir, html=True)`，模板页可 HTTP 直达；`::after { content: "…" }` 用户看得见 | 发现面加 `css/*.css` 与 `templates/*.html`；`css` 键补进具名清单（原去重逻辑把已在 `FILES` 里的 rel 跳过，导致 CSS 双重漏检） | `J2`（入面文件数在明细里打印，缩水可见） | 两条变异：CSS `content` 写死「模型映射」页 → J2 红；`template-skills.html` 加坏页名 → J2 红 |
| S-35 B10-9 | `PAGE_REFS` 的 cue 动词是闭集（`到|前往|请到|打开`）且括号型强制后跟"页"字 → `或去「模型映射」核对` 全绿（对照：保留"到 … 页"裸串立刻红，说明只堵了一半） | cue 集扩为 `到/前往/请到/请打开/打开/去/进入/跳到/切换至/导航至`（**故意不含 见/参照**：`见「最近错误」列` 是列名不是页名，误伤会把判据变成噪音）；串内字符集限定为文字/数字/空格 | `J2` | 变异"apiaccess 里写 `或去「模型映射」核对`" → J2 红 |
| R-3（eng） | 门用 `new Function` 执行前端源码 = 代码住在**本进程全局作用域**：Node 独有的 `process`/`require`/`Buffer`/`setImmediate` 取得到，浏览器取不到 → 页面写 `process.platform` 时门全绿、用户拿到崩页 | 新增 `browserFn()`：前端源码一律编译进**空 vm 上下文**（只有 ECMAScript 内置对象，浏览器侧依赖仍由形参注入）；5 处执行点（`configWarnings`/`statusBadge`/`renderTable`/红点块/`renderDashboard`）全部改走该通道 | `Z2`（执行环境自测：五个 Node 全局名 `typeof` 必须全为 `undefined`） | 「沙箱泄漏 Node 全局」变异（往上下文塞 `process`）→ Z2 红 |

## 第十轮的自我交代

1. **ix 的九条阻塞没有一条在变异表里**。`可红 87/87` 只证明"表里那 87 个变异各自能红"，不证明门封住——
   本轮把这条写进门的设计：新增判据必须同时新增"坏改动的自然写法"型变异（现在是 100/100），
   且白名单式判据（列举坏写法）一律升级为语义模型（属性解析 / 结构规则），否则每轮都会重演。
2. **门自己的自证是假的，被自家红证当场揭穿**（S-7 同族，第二次）：`--json` 模式里人读行照打，
   父进程用 `indexOf("{")` 定位 JSON，撞上 K5 判据名里的 `${` → `JSON.parse` 抛 `SyntaxError` →
   走"抛错算红"的推定分支，`Z1` 那条"把 hidden 判据摘掉"从未真读到红。现已改为 `--json` 只输出 JSON、
   父进程取**最后一行**解析、且**门自身变异不再接受抛错当红**（页面源码变异保留该口径：
   渲染抛错就是用户看到的崩页）。教训：推定分支不能充当证据。
3. 沙箱化当场把 `I1` 打红，查明是假红：跨 realm `await` 比同 realm 多几个微任务 tick，
   原先 `await Promise.resolve()` 单次让帧在半完成状态下判定 → 改成等**宏任务边界**（`setTimeout 0`）。
   另外两处由红证暴露的实现错：变异锚点用**单行**文本时会命中 `MUTATIONS` 表自身的字面量（要求恰好 1 次，
   改为两行锚点）；`isInvisible` 第一版按"属性串里出现过 hidden"判（字面巧合，ix 指出的正是这条）。
4. PM 的两条"坏值路径零痕迹"已随 S-34 落地为 `logger.warning`（缺键/null 与超上限各一条），
   坏值不再静默改变熔断语义；PM 的 3 条旧口径残留与 eng 的其余非阻塞项（探针写失败无自愈、
   `.write-probe.lock` 0644 泄漏 pid+token、`data/ops-locks` 不在保留期、第三方锁删除零日志）
   **登记未修**，等第十一轮面板复验后再定取舍（铁律 5：不搁置不隐瞒）。

# 第十一轮复验的补做（S-36 ~ S-54，2026-09-28）

> 第十一轮四个面板（`pm-accept-11.md` / `eng-a-accept-11.md` / `eng-b-accept-11.md` / `ix-accept-11.md`）
> 全部判 **不通过**，合计 **19 条阻塞**：PM 4、eng-A 3（熔断状态文件方向性）、eng-B 4（门自身可信度）、
> ix 8（可见性模型 / 壳层 / 六页零执行 / 转义 / 真值 / 指路 / 外链 / 缺省 fail-open）。
> 另：eng-A 面板在写完报告后撞到子 agent 轮次上限死亡（`status=failed`），报告 31,607 字节已在盘上，
> 我按文件内容而非它的收尾消息采信（它的收工自证里还主动交代了自己一次误发到并行会话端口的 POST）。
>
> 补做后的机械门（数字逐字取自本轮 runner 自身输出）：
> - `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest -p no:warnings` → **715 passed in 149.78s**（第十轮后 705）
> - `node scripts/verify_v2_frontend.mjs <overview>` → **实测 84 项，通过 84 项，失败 0 项**
> - 同脚本 `--mutation` → **可红 104/104；每条断言都有对应变异**
> - `.venv/bin/python scripts/ui_verify_v2_visible.py --mutation` → **后端出口实测 12 项，通过 12 项，失败 0 项**
> - `find data -newermt '-240 minutes' -type f` → **空**（`data/` 全程只读）

| # | 问题（谁抓到） | 落点 | 判据 | 撤修复红证 |
|---|---|---|---|---|
| S-36 | 指路页名分叉：`ROUTE_POOL_PAGE` 被用来说"添加/更换资源映射"，而该控件 `#rv-addmap` 长在「模型资源」页（`resources.js:274`），「资源池设置」页只有档位/优先级/移除（`models.js`），且那一页自己写着去「模型资源」页（PM B-11-1） | `main.py` ①③两条告警、`cli_setup.py::no_mapping`、`dashboard.js` invalid 徽章 → 全部改指 `RESOURCE_PAGE`；`cli_setup` 里已无引用的 `ROUTE_POOL_PAGE` import 删掉 | 门侧新增 **J3**（指路动作↔控件归属，**由源码里的控件标记派生**，含 @media 与常量还原）；pytest 侧 `test_route_copy_points_at_a_page_that_actually_hosts_the_control` 的 `owners` 由手写改成派生（原来写 `"映射": {resources.js, models.js}` = 漏洞本体） | 把 ① 改回「资源池设置」页 → pytest 红：`该动作的控件只在 resources.js`；把徽章改回旧页名 → 门红 C3+J3（变异表里各有一条）；复原后 `2 passed` |
| S-37 | PRD Q25-⑩ / tech-design §20-17 明令的「先登录工具，再配网关」**零交付**：双语 README、CLI、界面全部无命中（PM B-11-2） | `README.md` / `README.zh-CN.md` 各加一条（英文 "Log in to the tool first, then point it at the gateway"），并写明 `mgw setup` 只写配置、不代登录 | `test_v2_readme_claims.py::test_login_first_disclaimer_ships_in_both_languages` | 把中文那句换成"先配置再使用" → 该判据红（实测），复原绿 |
| S-38 | **可见性模型不含样式表层叠**：`isInvisible()` 只看元素内联 `style`，`base.css` 一条 `.alert-warn{display:none}` 就让四条告警在真 Chrome 里高度全 0（PM 实测 11 种藏法 8 种全绿；ix 实测 `body.innerText` 856→459 且 `--mutation` 仍 100/100）。**更根本**：本项目 `base.css:108` 自己定义 `.hidden{display:none!important}` 且 `logs.js:151` 在用 → 第十轮"类名里带 hidden 不算隐藏"这条判据对本项目是错的 | 新增 `cssHiding()`：扫 `base.css` 任意嵌套层级的 `选择器{声明}`（含 `@media`），产出"隐藏类名/id/裸标签"三集；`isInvisible = 内联属性 ⊕ 样式表命中`；`visibleText` 另判标签级隐藏。三条误伤排除也写进代码注释：`@keyframes` 的 `from{opacity:0}`、伪元素 `.x::after{display:none}`、后代裸标签 `.nav-item span{display:none}` | `Z1`（25 例，含 `class="alert hidden"`→**算隐藏**、未定义类名→不算）+ 内联样式集补 `font-size:0`/`color:transparent`/`max-height:0`/`clip-path:inset()`/`zoom:0`/`translate(-NNNpx)` | 两条新变异：CSS 里加 `.alert-warn{display:none}` → K1 红；**删掉** `.hidden` 那条规则 → Z1 红（证明判据真在读样式表，不是背清单）。面板报的 `opacity:0`/大写/`<template>` 等仍在原变异表里逐条红 |
| S-39 | README 失真三处：`462/462`（实测 705）、`v0.2.0` 而 `mgw --version`=0.1.0、证据链接指向被 .gitignore 的 `docs/`（PM B-11-4） | `pyproject.toml` + `model_gateway/__init__.py` 版本对齐到 **0.2.0**（design-spec §2.1 线框就是 v0.2.0）；双语 README 数字改为"710（截至 2026-09-28，附复现命令）"；删掉 docs/ 链接 | `test_v2_readme_claims.py` 四条：版本 == `__version__` == pyproject 且无残留旧版本、`mgw --version` 与之一致、宣称条数 ≤ 真实条数且漂移 ≤20、README 不引用 `docs/`/`.cursor/` | 三条各验一条：版本改回 0.1.0 → 版本判据红；数字改回 462 → 漂移判据红；docs 链接复原 → 路径判据红 |
| S-40 | 坏值告警只覆盖 3/13 类且措辞错位：字符串/NaN/非对象/截断/chmod 000 全部零日志；而 `last_call_ms`（只是节流）坏掉却报"熔断状态不可信"（PM N-1 半收口 + eng-A NB-2/NB-3） | `_ms_problem()` 逐形态给**不同**归因串；`_set_untrusted()` 只在信任态**变化时**记一条（不刷屏也不零痕迹）；节流字段单独措辞；`reason()` 里给出可执行手动出口（删除该文件） | `test_missing_or_null_until_ms_keeps_the_running_breaker`（坏形态扩到 10 种：布尔 true/false、`[]`、`"just-a-string"`、非 JSON）+ `test_untrusted_state_is_visible_on_the_ui_not_only_in_logs`（界面出口：§17 回写必须 bench 上「最近错误」且时长按整档挡） | 把 `remaining_seconds()` 的未知档从 30min 改成 0 → 界面判据红（`assert … > 25*60`）；布尔分支删掉 → 两条红；复原 52 passed |
| S-41 | 门的 fixture 是**全局共享可变路径** `/tmp/mg-v2-visible/overview.json`：并行面板互相覆写，PM 与 eng-B 各被污染出一条假红 | `scripts/ui_verify_v2_visible.py` 改 `MGW_V2_VISIBLE_DIR` 或 `mkdtemp` 独有目录，并把 `fixture=<路径>` 打进输出 | 输出行本身（"本轮新写，别拿旧文件当本轮结论"） | 未做红证（属工具行为，非产品判据）；已实测并行两跑互不覆盖 |
| S-42 | **变异自证仍吃推定分支**：81 条判据里 66 条 eager 传值，页面函数一抛错整个子进程崩掉，`catch` 里 `red = mut.kills` 白拿 ✓；面板独立驱动实测 99/100 而门报 100/100（eng-B B11-1） | `runMutations` 里**所有**变异统一走子进程 `--json`（跑门的副本，ROOT 指向 work 目录）；`--json` 模式把 `errors` 一并回传、退出码恒 0；父进程只认 `ok:false`，崩溃/无输出记 BAD；页面函数包一层 `safePageFn`（抛错记一笔 + 返回哨兵串，正/反判据都因此变红） | 新增 **Z3**「页面函数对全部判据输入未抛错」 | 面板那条"不可能杀死 Z2 的语法变异"路径消失；`A12` 变异现在要求 `["A12","Z3"]` 双红，实测 `可红 104/104`（无一例靠抛错） |
| S-43 | Z2 是**手写 5 个名字**的黑名单：只漏 `global` 就能让页面真读 `process.env.HOME` 而 Z2 ok:true（eng-B B11-3） | 被测名集改由**宿主派生**：`Object.getOwnPropertyNames(globalThis)` 减去空 vm 上下文的 ECMAScript 内置、再减去"浏览器确实存在、允许注入"的 Web 全局表 → 52 个 Node 专有名逐个 `typeof` 必须 `undefined`；派生集本身带 canary（`process`/`Buffer`/`global` 必须在集内，防派生塌成空集） | `Z2`（改名即说明口径） | "沙箱泄漏 `process`"变异 → Z2 红（实测）；把 canary 名字从派生里剔掉 → Z2 红 |
| S-44 | 接线护栏覆盖面手写：`V2_MODULES` 38 条 vs 磁盘 56 个模块，**18 个在面外**（含 `core/cancel.py`/`core/errors.py`/`config/schemas.py`/`stats/events.py`）；死符号种进面外模块 `6 passed` 一声不响（eng-B B11-2） | `V2_MODULES = sorted(PKG.rglob("*.py"))` 派生；`test_population_covers_…` 改成双向钉（清单里不许有不存在的路径 / 磁盘上不许有未入面模块） | 派生即覆盖面；另加 8 个点名模块（含原先漏掉的 4 个）作为二次锚 | 派生后**立刻抓到真死符号** `core/errors.py#wrap_httpx_error`（与 `openai_out.py:114-116` 的内联翻译重复且措辞更弱）→ 删除该符号；面板原复现（种进 `core/cancel.py`）现在同一判据路径下会红 |
| S-45 | 「连续失败」与「处理中」两列**取值对调**门全绿：B6 只数列数、K6 只看「最近错误」列位；且 fixture 里这两列恒为 0/0，天然不可判别（eng-B B11-4） | 两份 fixture 生成器（`ui_verify_v2_visible.py` 与 `test_int_v2_frontend_gate.py::_overview_payload`）走**生产函数**造判别值：`pick_and_acquire` 记在途、`note_failure×3` 记连失 | 新增 **K10**「逐行核：连续失败=该行 C、处理中=该行 in_flight」，并把"可判别行数 = 0"本身判红（防 fixture 退化） | 变异：交换 `${r.C}`/`${r.in_flight}` 两个 `<td>` → K10 红（实测计入 104/104）；复原 84 项全绿 |
| S-51（半） | ix B11-6/B11-7：指路是语法白名单、页名归属表手写、`K4` 把外链当解析噪声过滤 | J3 + pytest 派生（见 S-36）；`K4` 拆成"内部链接必须是真导航项" + "出现 `http(s)://`/`//host` 直接红"（铁律 1 的界面侧表达） | `K4`（detail 打"内部 N 条；外链 M 条"） | 变异：往告警横幅里塞 `https://docs.model-gateway.example.com/faq` → K4 红（实测） |
| S-52 | 熔断落盘的临时文件名**固定**（`circuit.json` → `circuit.tmp`），cron 与 CLI 并发落盘互相截断：面板 12 秒实测读到坏 JSON **206,783 次**、混合内容 20,351 次 —— 坏文件是它自己造的，不需要人手改（eng-A BLK-1） | `_save()` 改 `tempfile.mkstemp`（`O_EXCL` 唯一名）+ `flush`/`fsync` + `os.replace` 原子改名，失败路径在 `finally` 里扫残留 | `test_concurrent_saves_never_expose_a_half_written_file`（6 线程读写 1.5 秒，任何一次读到非完整 JSON 即红 + 不许留临时文件） | 改回固定名 `circuit.tmp` → 该判据红（实测 `1 failed, 77 passed`）；复原绿 |
| S-53 | 「读不动」= 新进程按**无熔断放行** + `mark_called()` 无条件整盘覆盖 → 跨进程熔断凭据被销毁，连常驻进程下一次判定也跟着清零；CLI 打「全部正常，无需处理」+ rc=0（eng-A BLK-2，方向与用户裁决 S-22 相反） | `_read_disk()` 给三态（不存在=已解除可信 / 读不动=未知 / 可读=按文件）；`active()` 对未知**返回 True**；`_save()` 在"未知且自己没有熔断"时拒写、在"盘上更长"时按**只延长不缩短**合并；`reason()` 对未知不给钟点、给手动出口；`_circuit_gate` 归因文案分叉（不再"剩余约 0 分钟"）；`remaining_seconds()` 未知按整档 30min 挡 | `test_unreadable_breaker_file_blocks_instead_of_releasing`、`test_mark_called_never_destroys_a_breaker_it_cannot_read`、`test_save_merges_the_longer_breaker_from_disk`、`test_cooldown_corrupt_file_blocks_instead_of_releasing`（原 `…_degrades_safely` 断言的正是被推翻的方向） | 三处各验：拒写去掉 → mark_called 判据红；合并去掉 → `assert 0.0 == 1790592674429.368` 红；`active()` 回到"未知=放行" → **5 条同时红**；复原 51 passed |
| S-54 | 布尔形态逃过判坏：`float(True)==1.0` 是合法数值 → 最常见的"把数字改成 true"会把正熔着的熔断清零，零日志（S-34 六类之外的第七类，eng-A BLK-3） | `_ms_problem()` 把 `isinstance(raw_value, bool)` 挡在判数值**之前**，归因串带上 `repr` 值（不同写法不并成一条日志） | `test_missing_or_null_until_ms_keeps_the_running_breaker` 的形态集含 `true`/`false` | 删掉布尔分支 → 2 条红（实测），复原绿 |

## 第十一轮登记、**尚未修**（本轮预算内没做完，不是被跳过）

| # | 问题（谁抓到） | 为什么还开着 |
|---|---|---|
| S-46 | ix B11-3（**最严重，主动说谎**）：七页里只有总览被真执行，`api.js`/`components.js` 共享行为零执行 —— `api.js:8` 的 `if (!resp.ok)` 改成 `if (false)` 后，后端真返 400、配置一个字没改，界面弹绿色「配置已保存并热重载生效」；`confirmDialog` 取消分支改 `resolve(true)` → 点「取消」真的删了密钥；`copyText` 不写剪贴板却 toast「已复制」；`maskVal` 改恒等 → 密钥明文上屏；`settings.js` 少一行解禁 → 保存按钮永远灰而脏态徽章照样在 | 需要给六个页面各配假 DOM 真跑 `renderXxx` + `api()` 四态响应 + `confirmDialog/copyText/switchEl/modal` 行为判据，每条还要配能打红的变异。本轮先做完了"门自己不再靠崩溃冒充证据"（S-42）这一 prerequisite —— 没有它，这批新判据的抛错又会被推定成红。**列为第十二轮第一优先** |
| S-47 | ix B11-8（元问题）：判据缺省 fail-open，`pageHtml.match(...) || ["", ""]` 让"页面上根本没有那个容器"被判成"容器可见"（实测趋势卡是 160px 空白带、柱数 0，门说 `✓ K8`）；同族缺省还有 `titleOf`/`heads`/`dotTag`/`metaBlock` | 全站缺省要逐个改成"取不到即红"，并与 S-46 的新判据一起验（改了缺省会让一些原本靠空串蒙过的判据立刻红，需要同时补 fixture）。第十二轮做 |
| S-48 | ix B11-2：壳层零判据 —— `index.html` 只被字面正则扫过，`main.js` 的 `route()`/主题/自动刷新三段完全不跑。实测 `#content` 改名（整站不启动）、`<main style="display:none">`（界面纯白）、`<link href>` 写错（裸样式页）、`inert`（内容区点不动）全部 81/81 绿 | 需要壳层可见性判据 + id 交叉核对（派生自 JS 里的 `getElementById` 全集）+ `<link>/<script src>` 存在性 + `route()`/`applyTheme()` 真跑。第十二轮做 |
| S-49 | ix B11-4：转义只在 `warnings.message` 一根管道上被证明；去掉 `${esc(r.name)}` 门全绿（面板用同样的 vm 手法真跑，活标签 0→1） | 哨兵要**逐字段**塞（资源名/厂商/账号/last_error/request_id/error_summary）并对六页各跑一次；另需一条"后端可控字段未过 esc 即红"的静态判据。第十二轮做 |
| S-50 | ix B11-5：数值真值无判据 —— 八张指标卡整族不渲染、`成功比 NaN%`、今日切换写死 0、告警成因被改成"临时冷却·无需处理"全部 81 绿 | K5 坏插值集要补 `NaN/null/Infinity/-0/0÷0`，并加"载荷里放哨兵值 → 界面同一数字"的一致性判据。第十二轮做 |
| S-51（余下半） | ix B11-6：`PAGE_REFS` 仍是"括号 + cue 动词"的语法白名单，`【模型映射】页` 这类写法界面可见而门全绿（同锚点改「」立刻红 = 只堵了一半）；死页名黑名单未建 | 归属判据（J3）已经把"页名真实存在但控件不在那一页"这一半堵住了；剩下的"括号形态"要改成**反向派生**（源码里所有括号串 ⊕ 引号内近似导航标签）+ 死页名黑名单。第十二轮做 |
| 旧账 #48 | 热重载换下的适配器未 `aclose`（`main.py` 建 adapter vs 换 adapter 的路径） | 需要定"延迟关闭 / 引用计数"的口径，属产品决策不是判据缺口；仍登记等裁决 |
| 另登记 | 探针写失败分支无自愈（0444 或 root 属主文件 = 永久拒跑）、`.write-probe.lock` 0644 泄漏 pid+token、`data/ops-locks` 不在保留期清理内、第三方锁被删 = 互斥静默失效零日志、argparse 把 claim epilog 折成一段、`--config` 帮助文案与 `paths.py` 口径不符、design-spec §2.1 线框有「● 运行中 v0.2.0」而 `dashboard.js:16` 只渲染「运行中」（不擅自加控件） | 均为面板非阻塞项，逐条留给第十二轮复验时定取舍（铁律 5） |

## 第十一轮的自我交代

1. **"改成语义模型"这句话我说过头了**（第十轮记录原文：可见性判据从白名单升级成语义模型）。第十一轮 PM 与 ix 各自证明：它仍然只是一份**更长的白名单**，作用域被定死在"元素自身的内联属性"，样式表层叠完全在外。铁律 2 的同一形态第三次犯（第九轮"坏值 = 文件读不动"、第十轮"`--json` 自证"、本轮"语义模型"）：**宣布机制升级之前，必须先写出这个模型的作用域边界**（管到哪一层、不管哪一层），否则"升级"这个词就是给用户发的免检券。
2. **手写覆盖集不是护栏** —— 本轮两条（Z2 的 5 个名字、`V2_MODULES` 的 38 条路径）都是同一课的第 N 次重演，且派生之后**立刻**抓到真死符号 `wrap_httpx_error`。已把"覆盖集必须由文件系统/宿主自动派生 + 派生本身带 canary"当成硬约束；以后凡是"清单"形态的判据，先看它能不能派生。
3. **我自己写的第一版合并判据是空过的**：`test_save_merges_the_longer_breaker_from_disk` 最初用"同一进程内推进时钟 + 直改内存"造场景，撤掉修复后**照样全绿**（内存里那份本来就是长的那份，对调不出来）。是照例做"撤修复必须红"时当场发现的，重写成两个 `CooldownManager` 交错写盘的真实形态才有效。规则重申：新判据在写进账本之前，必须先有一次"改坏了它红"的运行输出；没有这条，账本里的"已修"只是我的自我声明。
4. eng-A 面板撞轮次上限死亡但报告完整落盘 → 我按磁盘文件采信、并按其 3 条阻塞登记（第十二轮复验时它的复现命令可直接复用）。另把面板共同抱怨的"共享 fixture 污染"（S-41）修成 per-run 目录 —— 这是**验收环境自己的缺陷**，不修就会持续制造假红/假绿。

# 第十二轮复验的补做（S-55 ~ S-60，进行中，2026-09-28）

> 第十二轮四个面板仍全部判 **不通过**，合计 **15 条阻塞**（PM 4 / eng-A 2 / eng-B 1 / ix 8；
> "数字串时间戳"是 PM B-12-1 与 eng-A BLK-A 同源，合成 S-55 处理）。
> 报告：`pm-accept-12.md` / `eng-a-accept-12.md` / `eng-b-accept-12.md` / `ix-accept-12.md`。
> eng-A 再次撞轮次上限，但因简报里写了"边做边写"，452 行报告完整落盘、可直接采信。
>
> 本节先记**已收口**的部分（S-55 / S-56 / S-57 的 CLI 那一半），数字取自本轮 runner 自身输出：
> - `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest -p no:warnings` → **719 passed in 151.18s**
> - `node scripts/verify_v2_frontend.mjs <overview>` → **实测 84 项，失败 0 项**；`--mutation` → **可红 104/104；每条断言都有对应变异**
> - `.venv/bin/python scripts/ui_verify_v2_visible.py --mutation` → **后端出口实测 12 项，通过 12 项，失败 0 项**
> - `find data -newermt '-420 minutes' -type f` → **空**（`data/` 全程只读）

| # | 问题（谁抓到） | 落点 | 判据 | 撤修复红证 |
|---|---|---|---|---|
| S-55 | `float()` 无差别强转：**数字串** `"1770000000000"` 被当合法时间戳 → 熔断在所有进程里当场消失、`mark_called()` 不再受"未知拒写"保护 → 整盘覆盖销毁跨进程凭据、全程零日志；**JSON 重复键**被 `json.loads` 静默"后者顶掉前者"（PM B-12-1 + eng-A BLK-A） | `quota._ms_problem` 只接受 `int/float` 且非 `bool`，字符串判坏并在归因里带截断原值（防不同形态被去重并成一条）；`_read_disk` 用 `object_pairs_hook` 检出重复键 | `test_numeric_string_timestamp_cannot_shorten_or_wipe_the_breaker`、`test_duplicate_keys_are_not_silently_the_last_value`、`test_missing_or_null…` 形态集扩到 12 种、`test_claim_with_unreadable_state_file_promises_no_auto_recovery`（CLI 端到端 rc=3） | 去类型闸 → 3 条红（含 CLI）；去重复键检测 → 2 条红；复原 5 passed |
| S-56 | 落盘失败**完全静默**：目录 0555 时 `enter()` 无异常、零日志、文件不存在，下一次判定把"文件不存在"读成"已解除" → 抹掉本进程刚建立的熔断 → 闸门开、下一轮继续打风控账号，而 CLI 还打印「已建立全局熔断：」+ 空原因（eng-A BLK-B 两半） | `_save() -> bool` + 唯一失败出口 `_save_failed()`（记 `_save_error` + WARNING 带绝对路径）；`_load()` 的 `keeping_memory`：**上次写盘失败时，盘上缺席不得抹掉内存里生效中的熔断**；`reason()` 追加「未能写入状态文件…仅当前进程内存生效，请检查 <路径> 可写性」；新增 `unpersisted` | `test_save_failure_is_never_claimed_as_persisted`（0555 目录：`_save()` 返回假、`unpersisted` 有值、`reason()` 含三要素、日志有"落盘失败"） | 失败分支改回静默成功 → 红；`keeping_memory` 置 False → 同一条红；复原 5 passed |
| S-57（半） | CLI 第二行对未知档许诺「到点自动恢复」，与上一行"读不动 → 按熔断拒跑"自相矛盾（PM B-12-3） | `cli_zcode.py` 按 `circuit.untrusted` 分叉：未知档说「**读不动 → 不会自动恢复**；只有删除该文件才会放开后续领取」，可信档保持原文（S1 的作用域限定不动） | 同上一条 CLI 判据（含"不会自动恢复"、**不含**"到点自动恢复"、含绝对路径、不含"全部正常"） | 去掉分叉（两条都走"到点自动恢复"）→ CLI 判据红 |

## 第十二轮登记、**尚未修**（按序处理，不隐藏）

| # | 问题（谁抓到） | 状态 |
|---|---|---|
| S-46 | ix B12-1：六页与共享行为**一个字节都没执行** —— `api.js:8` 的 `if (!resp.ok)` 改 `if (false)` 后，Chrome 里后端 400、`fail_threshold` 未变，界面弹绿色「配置已保存并热重载生效」；`confirmDialog` 取消→真删密钥；`copyText` 不写剪贴板仍报"已复制"；`maskVal` 恒等→明文上屏；**三条同时种上门仍 84/84 绿、`可红 104/104`** | 未修（第一优先；S-42 已把"崩溃算红"清掉，现在能安全地给六页配真跑判据） |
| S-47 | ix B12-6：`:918` 的 `\|\| ["", ""]` 缺省 fail-open 原样在，只改容器 id → 门 `✓ K8` 而 Chrome `chartChildren:0` | 未修 |
| S-48 | ix B12-2：壳层零判据（`#content` 改名=整站不启动、`<main style=display:none>`=纯白、`<link>` 写错=裸样式、`inert`=点不动、深色点了没反应） | 未修 |
| S-49 | ix B12-4：K9 只是整页 `<script>` tripwire，不是逐字段转义 —— 资源名/最近错误/日志列去 `esc` 在 `<svg onload>`、`<img onerror=alert(document.domain)>` 上全绿（撞字面 `<script>` 才红，属侥幸） | 未修 |
| S-50 | ix B12-5：指标真值无判据 —— 八张卡整族空、界面出现「成功比 NaN%」、`switch_count=3` 的载荷上写死 0 仍绿 | 未修 |
| S-51（余） | ix B12-7：`【模型映射】页` 仍盲（同锚点改 `「」` 立刻红）；J3 动作表只有 4 条手写项；K4 只验路由存在（`javascript:` 反而红，说明还是字面判据） | 未修 |
| S-57（余） | PM B-12-2 / B-12-4：未知档在界面被拼上「，至 19:42」的钟点而同行徽章写「无需处理」（同屏打脸）；用户删文件后那一行仍冻结 30 分钟无反馈；未知拒跑轮 `ops_failed_unread=0` → 顶栏红点不亮；README 双语零条款、PRD/tech-design 未归档该方向 | 未修（下一步） |
| S-58 | eng-B S-52：vm 只挡全局名，**没挡 realm 桥接** —— 页面里 `esc.constructor("return process")()` 拿到宿主 Function 读 `HOME` 并写进 stdout，Z2✓Z3✓、84 全绿、104/104；另 `execFileSync` 无 timeout（死循环变异挂死整轮、留 98% CPU 孤儿） | 未修（门可信度根基，下一步） |
| S-59 | ix B12-3：本轮新写的 `cssHiding()` **注释与实现不符** —— 面板把该函数从门源码里逐字切出来跑探针，五种写法派生只剩 `classes=["hidden"]`（`@media` 内规则、`@layer`、伪类复合、壳层 `<style>`、`!important` 竞争都没进），Chrome 实害 `bannerH=[0,0,0,0]`、`innerText 873→137`、`chartH 160→0`；反面 F6/F12 还造成误伤红 | 未修（与 S-38 同一族："自称扫了 @media 其实没扫"，按"机制作用域必须先写清并重做"处理） |
| S-60 | ix B12-8：接线护栏 canary 往**真包目录** `model_gateway/_wiring_canary_pkg/` 写盘，四面板并发跑 pytest 互相踩 → 面板全量实跑 `1 failed, 714 passed`（单跑 6 绿）。含义要写清：我报的 715/719 都是各自那次运行的真实输出，但该测试**不具备并发安全性** | 未修（改 tmp_path + 护栏可吃任意 root） |
| 旧账 #48 | 热重载换下的适配器未 `aclose` | 仍等口径裁决 |

## 第十二轮的自我交代

1. **我这一轮修的东西被面板逐条打穿**：S-38 的 `cssHiding()`（注释说"任意嵌套含 @media"，实测派生只剩一个类名）、S-53 的 fail-closed（未知档在界面编钟点、徽章还说"无需处理"、红点还不亮）。同一形态第四次出现 —— 简报里那句"机制升级"没有配作用域证明。下一步凡新增机制，必须同时提交"该机制**测不到**什么"的负面清单与探针脚本（ix 这次就是用 `/tmp/ix12-cssprobe.mjs` 把函数单独切出来跑，才让注释与实现的落差无法抵赖）。
2. **交付口径要附运行时刻与并发性**：`715/719 passed` 都是真跑，但 canary 写进真包目录使这个数字**在并发下不可复现**（面板实测 `1 failed, 714 passed`）。已登记 S-60，修完之前，任何全量绿都应注明"单次运行"。
3. 门的可信度还剩两条根子上的洞（S-58 realm 桥接、S-46 六页零执行）。在这两条修完之前，`可红 104/104` 与 `84 项全绿` 都**不足以支撑"前端已验收"**的说法 —— 本轮 ix 同时种三个坏改动仍拿满分，就是证据。

# 第十二轮复验的补做（续，2026-09-29：S-57 余 / S-58 / S-59 / S-60 + 三条新洞）

> 本节数字全部取自本轮 runner 自身输出（不是上一节的数）：
> - `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest -p no:warnings` → **719 passed in 150.36s**
>   （**单次运行**：S-60 修完之前这句必须带，理由见上一节自我交代 2）
> - `node scripts/verify_v2_frontend.mjs <overview>` → **基线 88 条全绿**
> - `node scripts/verify_v2_frontend.mjs <overview> --mutation` → **可红 112/112；每条断言都有对应变异**
> - `.venv/bin/python scripts/ui_verify_v2_visible.py --mutation` → **后端出口实测 12 项，通过 12 项，失败 0 项**
> - `stat -f %Sm data/usage/daily-20260929.json` → **17:00:00**（常驻 :8300 的整点聚合，
>   本轮第一次跑测试是 17:11 之后）→ `data/` 本轮仍只读

| # | 问题（谁抓到） | 落点 | 判据 | 撤修复红证 |
|---|---|---|---|---|
| S-57（余下：红点那一半） | PM B-12-4：未知档整轮拒跑却记 `inactive`，而红点只数 `failed` = "拒跑了但没有任何人知道" | `zcode_claim._circuit_gate` 按 `circuit.untrusted` 分档：**读不动 → `failed` + 「未发起：…读不动…删除 <path> 即可解除」**；读得动的熔断维持 `inactive`（正常业务态，不该点红点）。两条界都要钉住 | `test_claim_with_unreadable_state_file_promises_no_auto_recovery`（未知档：`failed==["acct-a"]`、reason 含「未发起」「读不动」、`inactive==[]`）+ `test_claim_under_global_breaker_exits_3`（可信档：`inactive==["acct-a","acct-b"]` 且 **`failed==[]`**） | 两处**各改各的**：未知档改回 `inactive` → 前者红（`1 failed, 1 passed`）；可信档改成 `failed` → 只有后者红（`1 failed, 1 passed`）；复原 `33 passed` |
| ↑ 我写坏过一次 | 第一版判据是 `"failed" in body` —— 子串判 JSON 结构 | `failed` 是**恒存在的键**（空数组也在串里），把未知档改回 `inactive` 后 `"failed"` 和「未发起」字样**都还在**，实测**对着被改坏的源码一路绿灯**（`1 passed`） | 加 `_last_ops_record()`：按 `json.loads` 取结构，断言的是 `failed` **数组里的账号** | 就是上面那行"撤修复红证"——它是靠**先跑了一次撤修复**才发现原判据是假的，不是写完就当它有效 |
| S-58 | eng-B S-52：门的 vm 只挡**全局名**，没挡 **realm 桥** —— `esc.constructor("return process")()` 拿到宿主 `Function`，页面能读 `HOME`、能往 stdout 写字，Z2✓Z3✓、84 全绿；另 `execFileSync` 无 timeout（死循环变异挂死整轮 + 98% CPU 孤儿） | ① `browserFn` 里加 realm 内编译的 `__guard`：入口实参、**宿主调用的返回值**、对象属性、原型链全部包装；`constructor/__proto__/prototype` 三个桥属性摘掉；`getPrototypeOf` 伪装成 realm 的 `Object.prototype`；数组映射成 realm 真数组、thenable 换成 realm Promise（否则宿主原生方法在 Proxy receiver 上抛 incompatible receiver）；② 变异子进程 `timeout: 30_000, killSignal: "SIGKILL"` | **Z5**：拿 `INJECTED` 注册表（browserFn 自己登记的**全部**跨 realm 实参，非手写名单）在 realm 内 BFS，对每个可达函数问"你的 `constructor` 是不是本 realm 的 `Function`"；canary = `INJECTED.length >= 8` 且用一个**只为探测造的**宿主假件走返回值那条路 | 三条自门变异逐条红（都计入 112/112）：摘入口 guard → Z5 红；入口包但**返回值不包** → Z5 红；不伪造原型链 → Z5 红。`execFileSync` 那条无需红证（超时后 `blind` 记 BAD，不白拿"已杀死"） |
| ↑ 我又写坏过一次 | 第一版 Z5 为了拿结果**真去调用**被注入的假件（`f("return typeof process")()`） | 于是 `GET` 被当成"用户请求了一次"记进 `calls` → I5/I8/I9 三条"**不该发请求**"的判据被自己的探针污染成红（实测 `基线本身就有 3 条红（I5,I8,I9）`） | 改成纯结构判定（看 `constructor` 归属），**不调用任何注入值**；探测需要的返回值改用一个只为探测造的 `controlHost()` | 复原后 `基线 88 条全绿`。规则重申：**判据不得改动被测现场** |
| S-59 | ix B12-3：`cssHiding()` 注释说"含 @media"，实现把 at-rule **整块跳过**（`sel = atRule !== 0 ? "" : head`），派生只剩 `classes=["hidden"]` | 改成**栈**分两类：`@media/@supports/@layer` 透明（里面的规则照常参与），只有 `@keyframes/@font-face/@property` 整块跳过；来源不止 `base.css`，壳层 `index.html` 的 `<style>` 一起进；三条误伤排除（伪类最右段 / 后代裸标签 / at-rule 头部）保留 | **Z4**（合成样式表正反两问：`plain/media/supports/layer` 进集合，`fade`/`span`/`card` 不进，本项目 `.hidden` 必须在）+ 变异"把 at-rule 一律当整块跳过" → Z4 红 | 复采样两路都过：① `/tmp/mgw-cssprobe-r12.mjs` 把 `cssHiding` 从**门源码现切**出来跑 13 项（含 `@media`/`@layer`/`@supports`/嵌套 at-rule/id 进 @media/大写选择器 五个正向，`@keyframes`/伪类/后代裸标签/`!important` 反向 四个不误伤）→ **13/13 PASS**，仓库真实派生 `classes=["hidden","nav-toggle","drawer-mask","brand-text","nav-group-title","tb-addr","ops-dot"]`；② 真 Chrome 交叉核对（下表单列） |
| S-60 | ix B12-8：接线护栏的 canary 往**真包目录**写固定名 → 并发 pytest 互相踩（面板全量 `1 failed, 714 passed`） | canary 目录名带 pid（`_wiring_canary_pkg_<pid>`），派生覆盖面用 `_is_canary()` 把这类自播种目录排除 | `test_v2_wiring_guard.py` 的派生双向钉 + canary 用例 | 面板那条复现（两个进程同时跑）现在互不撞名；本轮全量为**单次运行**口径，并发安全性待第十二轮面板复跑确认 |
| 新发现 ①（本轮变异自证当场抓到） | `可红 108/109`：变异"冷却已到期那一支改成「稍后自动回池」"**纹丝不动 C6,C12** —— 两条判据都只走 `remaining>0` 分支，**到期分支的文案无人管**（用户会读成"还得再等"） | `dashboard.js` 的 `"已到期，下次选路即回池"` 一支补判据 | **C18**：`remaining=0` 的徽章 title 必须含「已到期」与「下次选路即回池」，且不得残留 `\d+s 后` / 「稍后/需等待/再等」 | 该变异现在杀 C18（计入 112/112）；`kills` 从写错的 `["C6","C12"]` 改成 `["C18"]` —— 原写法是**把判据名当账目抄**，不是从分支推出来的 |
| 新发现 ②（真 Chrome 交叉核对，S-59 的作用域证明） | 上一轮的教训是"注释说扫了 @media 其实没扫"，所以这次必须**拿浏览器实测**而不是只信派生集 | 隔离实例（静态目录复制到 `/tmp/mgw-chrome`，仓库文件零改动，`grep -c` 复核 = 0）+ CDP `Emulation.setDeviceMetricsOverride` 1440×900 | `.alert-warn` 的 `offsetHeight[]` 与 `body.innerText` 长度 | 基线 `[64,64] / 498`；`@media(min-width:1px){.alert-warn{display:none}}` → `[0,0] / 355`；`@layer comps{…}` → `[0,0] / 355`；顶层直接藏 → `[0,0] / 355`；`@keyframes fade{from{opacity:0}}` 干扰项 → **`[64,64] / 498`（没被误判成隐藏）**。四次的 Chrome 结论与门的派生**逐条一致** |
| ↑ 复采过程本身踩到的坑 | 第一次跑出来的 AFTER 与 BEFORE **一模一样**（`[141,83]` 不变），一度以为改动没生效 | `curl` 证明服务端已经吐出那条规则（`served has rule: true`）→ 问题在浏览器侧：`window.innerWidth === 0`，**`@media (min-width: 1px)` 在 0 宽视口下永不命中**（截图也报 `Cannot take screenshot with 0 width`） | 任何"响应式把东西藏起来"的实测都必须**先钉住视口尺寸**再看结论 | 加 `setDeviceMetricsOverride` 后同一批用例立刻出正确结论（上一行）；不加就会**假绿**（藏了也量得出高度） |

## S-46 第一批（共享行为层）交付 + 带出的两条新账（同日续，2026-09-29）

> 数字取自各自 runner 原样输出（主控**独立复跑**过，不是转述子 agent 的话）：
> - `node scripts/verify_v2_frontend.mjs <overview>` → **实测 109 项，通过 109 项，失败 0 项**
> - `--mutation` → 交付时 **可红 141/141；每条断言都有对应变异**（主控随后又加了一条
>   "未处理拒绝"变异 → 现 **可红 142/142**，见本节末"新 ①"）
> - `.venv/bin/python -m pytest tests/integration/test_int_v2_frontend_gate.py` → **2 passed in 25.75s**
> - `.venv/bin/python scripts/ui_verify_v2_visible.py --mutation` → **后端出口实测 12 项，通过 12 项，失败 0 项**
> - 只改了 `scripts/verify_v2_frontend.mjs` 与 `tests/integration/test_int_v2_frontend_gate.py`（前端/后端源码零改动，`git status` 复核）；报告 `docs/changes/e2e-records/gate-s46-shared-layer.md`（334 行，含 L0~L20 逐条红证）
> - **组合红证（主控亲手复现，不是转述）**：把面板点名的四条坏改动**同时**种进源码
>   （`api.js` 的 `if (!resp.ok)` → `if (false)`、`confirmDialog` 取消 → `resolve(true)`、
>   `copyText` 不接拒绝却报"已复制"、`maskVal` 改恒等 × **两份副本**）→
>   `实测 109 项，通过 100 项，失败 9 项`，红的正是 **L2, L3, L5, L6, L9, L12, L13, L20 + Z3**；
>   **既有 88 条（A/B/C/D/E/F/G/H/I/J/K/Z1/Z2/Z4/Z5）一条没红** —— 说明新判据不是把旧判据
>   换个名字再红一遍。四份文件事后 `cmp` **字节级复原**，`grep -c "if (false)"` = 0。
>   （`Z3` 也在其列，是这条组合里 `copyText` 留下的 unhandled rejection —— 见下面"新 ①"）

| # | 事项 | 落点 | 判据 | 红证 |
|---|---|---|---|---|
| S-46（第一批） | `api.js` / `components.js` 的共享行为**从未被执行**：`if (!resp.ok)` 改 `if (false)` 后后端真返 400、界面弹绿色「配置已保存并热重载生效」 | 门里新增 **L0~L20 共 21 条**，在 realm 内真跑共享函数，响应四态齐喂（成功 / 4xx 带后端原因 / fetch reject / 非 JSON）：错误路径必须 reject 且带出原因、只有成功才返回数据、`confirmDialog` 取消不得执行副作用、`copyText` 没真写成功就不许说"已复制"、`maskVal` 默认密文且 DOM 里不许出现完整明文 | 21 条各配源码变异（共 29 条：`api.js`/`components.js` 两处 + `maskVal` **两份副本各一条** + 一条门自身 import 剥离） | 141/141 全杀；报告里逐条附"种坏改动 → 该条红"的原样输出 |
| ↑ 简报被推翻的一处 | 我派单时把 `maskVal` 当成 `components.js` 的共享导出 | **实际不是**：它在 `apiaccess.js:19` 与 `resources.js:76` **逐字重复两份**，`components.js` 里没有（主控 `grep` 复核成立） | L20 改成**由目录派生抽出全部同名定义真跑**，并要求"抽取数 ≥ 2"本身为真 —— 否则副本被删掉一条、判据还在绿 | 两份副本各配一条变异，删任一条 L20 红 |
| ↑ 简报被推翻的第二处 | 我说 `copyText` 有"降级路径" | 代码里**没有任何降级**：`clipboard` 缺失时整条链静默（既不写也不 toast） | L13 按"**绝不谎报成功**"钉现状（不是钉降级），假 DOM 未提供 `execCommand` 出口 | 报告负面清单里写明"降级形态未覆盖" |
| **S-61（新发现，未修）** | `components.js:42` 的 `confirmDialog` **只在「取消」「确定」两个按钮上 resolve**，而 `modal()`（`components.js:16-38`）自带 **✕ 按钮**（`.modal-close`）与**遮罩 mousedown** 两条关闭路径，`confirmDialog` 又**没传 `onClose`** → 用户点 ✕ 或点遮罩时 promise **永不 settle**，`await confirmDialog(...)` 的调用方**永久挂住**（弹窗关了、后面的代码再也不执行、界面无任何异常） | 待修：三条关闭路径都要 settle（✕/遮罩 = 视为取消 `resolve(false)`） | 必须**新增**一条"dismiss 后 promise 必须 settle"的判据 —— 现有 L 段只钉"取消不得执行副作用"，**挂死本身不红**（这条判据缺失是本轮自查出来的，不是面板给的） | 未修，登记为 #87；修的时候要连"只钉按钮也算过"这个假绿一起堵掉 |
| 门自身的一条缺省修正 | `test_int_v2_frontend_gate.py` 的数量下限停在 **85 / 108**（现实中已是 109 / 141）—— 留着旧下限等于**允许门悄悄缩水 24 条而一声不响**；另外 `split("实测 ")` 取的是**第一段**，任何判据名里出现"实测"就会抢走解析（取数错方向 = S-47 同族） | 下限钉到当前真实条数 **109 / 141**，解析改用 `rsplit`（取最后一次出现），docstring 同步 | 撤修复红证：把两个下限临时改成 999 → 两条各红，`AssertionError: 断言总数只剩 109 条` / `变异表缩水到 141 条`（原样输出）；复原 `2 passed` |

### 主控独立复采时**自己撞出来的两个门缺陷**（同日续）

我按面板口径做"四条坏改动同时种"的组合红证时，门**整轮崩了**（`RC=1`、stdout 全空），
连"哪条红"都读不出来。顺着这条崩溃查下去是两个真缺陷，都不是面板报的：

| # | 问题 | 落点 | 判据 | 红证（A/B 直接对照） |
|---|---|---|---|---|
| 新 ① | 页代码在 realm 里留下 **unhandled rejection** 时，Node 默认**杀掉整轮**：`copyText` 的 rejection 分支被删掉（写入照发、无人接拒绝）→ 变异自证里这类"崩溃"不是证据，只是让整轮没有输出。第十一轮 B11-1 清掉的是**同步**抛错这条路，异步那条一直没管 | `process.on("unhandledRejection")` 兜网记进同一份 `PAGE_THROWS`；`safePageFn` 另接一层：页函数返回 thenable 时把 reject 换成哨兵串 | **Z3** 的口径从"未抛错"扩成"**未抛错、未留下未处理的拒绝**" + 变异表新增一条（正是我种的那个形状）→ `kills: ["L13","Z3"]` | **有兜网**：`可红 142/142`、该变异 `L13,Z3` 双红；**摘掉兜网**（只删那一行监听）：同一条变异变 `子进程 Error，无可判读输出`、`可红 141/142`。起作用的是**这一行监听**，不是我先前误记的 `__guard` thenable 包装 —— 复测分清后已把这句写进代码注释 |
| 新 ② | **Z3 排在了异步判据之前**：兜网是在宏任务边界之后才记账的，Z3 eager 求值时记录还没落进来 → 实测 `未红：Z3`（一条本该红两条的变异只红了一条） | Z3 移到 `await Promise.all(pending)` **之后**，并先排空两次宏任务；顺带让 `detail` 在结算完成后才取 | 同上那条变异 | 移动前 `未红：Z3`；移动后 `可红 142/142` |
| 顺带 | 变异自证的推定分支又长回来了：一条"会崩"的变异被记成 `← 子进程 Error，无可判读输出`（BAD），而 **BAD 不是红**、不白拿 ✓ —— 这条本来就对，值得记的是它**替我发现了**上面的洞：门自己崩了却只打一行"无法判读"，很容易被当成环境问题放过去 | —（无需改） | — | 复现命令：`cp` 备份四份前端源码 → 四改同种 → `node scripts/verify_v2_frontend.mjs <overview>` → `RC=1` 空输出 → 逐文件 `cmp` 确认**字节级复原**（`grep -c "if (false)"` = 0） |

> 数量随之变动：基线 **109** 条（未变），变异 **141 → 142**；`test_int_v2_frontend_gate.py` 的下限同步钉到 **109 / 141**（见上一节"门自身的一条缺省修正"，下限 141 对 142 仍成立，属"只准涨不准跌"的口径）。


## S-61 已修：确认弹窗的 ✕ / 遮罩通道不给答复（同日续，2026-09-29 晚）

> 这一条是 S-46 第一批的子 agent **自查出来主动申报**的（它按简报"只改门、不许越界改源码"
> 把它登记成待修而不是顺手改掉，方向正确）。我复核源码成立后本轮修掉。

| 项 | 内容 |
|---|---|
| 缺陷 | `components.js` 的 `modal()` 有**三条**关闭通道：`.modal-close`（✕）、遮罩 `mousedown`、以及调用方自己的按钮；而 `confirmDialog` 只在「取消」「确定」两个按钮上 `resolve`，**没给 `modal()` 传 `onClose`**。生产调用形状是 `if (!await confirmDialog(...)) return;`（`apiaccess.js:130-134`）→ 用户点 ✕ 或点空白处时 **promise 永不 settle**：弹窗消失了、删除既不执行也不报错，调用方永久挂住，界面看不出任何异常 |
| 为什么旧判据抓不到 | L9 钉的是"点取消**不执行副作用**"。挂住的 promise 连副作用都没有 —— 那种写法**照样绿**。所以必须把 **settle 本身**做成判据，而不是把旧判据改严 |
| 落点 | `confirmDialog` 加一次性答复闸门 `settle()`；`modal({ onClose: () => settle(false) })`（✕/遮罩 = 用户没做选择 = **取消**，绝不能当成「确定」去触发破坏性动作）；两个按钮改成**先给答复再关**（`m.close()` 会**同步**回调 `onClose`，顺序颠倒则「确定」被 `false` 抢先定掉） |
| 判据 | 门的 `L_SCEN.confirm` 场景扩出 `x` / `mask` 两条通道 + 新增 **L21**「经 ✕ / 遮罩关闭也必须 settle 并答复『取消』（副作用零次、弹窗关掉）」；另加 **3 条变异**：① 摘掉 `onClose`（= 原缺陷复发）→ L21 红；② `onClose` 改成 `settle(true)`（没做选择被当成确定）→ L21 红；③ 按钮分支顺序写反 → **L10 红**（这条就是"顺序"那句注释的红证）。既有 L9/L10 三条变异的锚点同步改到新源码形状 |
| 门的数字 | 基线 **实测 110 项，通过 110 项，失败 0 项**；变异自证 **可红 145/145；每条断言都有对应变异**；`pytest tests/integration/test_int_v2_frontend_gate.py` → **2 passed in 25.42s**（数量下限同步钉到 **110 / 145**，模块 docstring 里残留的 85/108 一起改掉） |
| **真 Chrome 正证** | 隔离实例 :57390（仓库当前代码，未动 :8300）+ `Emulation.setDeviceMetricsOverride 1440×900`（先量到 `window.innerWidth === 1440` 才开始判读）→ 页内 `import("/js/components.js")` 真调 `confirmDialog`，四条通道逐一驱动并用 `Promise.race(400ms)` 判 settle：`x → settled:false` / `mask → settled:false` / `cancel → settled:false` / `ok → settled:true`，四次 `maskStillOpen` 全 0 |
| **真 Chrome 反证** | 临时把 `confirmDialog` 改回修复前的形状（去掉 `onClose`、按钮改回 `m.close(); resolve(...)`）再跑**同一支探针**：`x → STILL-PENDING(400ms)` / `mask → STILL-PENDING(400ms)`，而 `cancel/ok` 照常 settle，且四种情况弹窗**都关了**（`maskStillOpen: 0`）—— 与缺陷描述完全一致：看起来一切正常，调用方再也不回来。随后 `cp` 复原并 `cmp` 确认**字节级一致** |
| 顺带审计 | 另两处 `modal()` 调用（`apiaccess.js:181`「添加接入密钥」、`models.js:171`「添加模型」）**不包 promise**（拿到的是 `{close, el}` 句柄），没有同类挂死风险；它们靠 ✕/遮罩关闭 = 不保存，正是预期行为。故本条只改 `confirmDialog`，不给 `modal()` 加新表面 |

### 仍开着（S-46 的余下半）
六个页面各自的 `renderXxx` 仍**零执行**（`resources/models/stats/logs/apiaccess/settings`），
含面板点名的 `settings.js` 那条"少一行解禁 → 保存按钮永远灰、脏态徽章照样在"；
`api.js` 还有 6 个导出（`fmtNum`/`fmtDur`/`groupColor`/`debounce` 等）、`toast` 自动消失计时、
数组型/空 `errors` 响应形态未覆盖。第二批做。

## 本轮仍未收口（不隐藏）



| # | 状态 |
|---|---|
| S-46（余下半） | **第一批已交付**：`api.js`/`components.js` 共享行为层 L0~L20 真跑 + 29 条变异（见上一节）。仍开着的是**六个页面各自的 `renderXxx`**（`resources/models/stats/logs/apiaccess/settings`，含 `settings.js` 保存按钮灰/脏态徽章那条），以及 `api.js` 的 6 个工具导出、`toast` 自动消失计时、数组型/空 `errors` 响应形态 |
| **S-61（新账，未修）** | `confirmDialog` 点 ✕ / 遮罩关闭时 promise **永不 settle** → `await` 它的调用方永久挂住（见上一节末尾的机制定位）。要连"**只钉两个按钮也算过**"这个假绿一起堵：新增"dismiss 必须 settle"判据 + 变异 |
| S-48 / S-49 / S-50 / S-51（余） | 壳层 `index.html`+`main.js` 路由/主题零判据；转义只在 `warnings.message` 一根管道上被证明；指标数值真值无判据；`PAGE_REFS` 括号形态仍是语法白名单 |
| S-57（余下：只剩一条等裁决） | README 双语条款、PRD **v1.18 / Q28-⑧** 七项、tech-design §17 背离注记**均已归档**（本轮做）。未决的只有 Q28-⑧ 第⑦条：用户删掉 `circuit.json` 后界面那一行仍冻结至多 30 分钟 —— "**读时重判**"还是"**进程间通知**"属产品口径，**等用户裁决，不自创** |
| 旧账 #48 | 热重载换下的适配器未 `aclose` —— **本轮已实测取证**（见下一节），仍等口径裁决 |

## 本轮的自我交代

1. **两条"我自己写坏的判据"都是靠撤修复当场暴露的**（子串判 JSON、探针调用被测假件）。这不是运气：规矩是"新判据写进账本之前必须先有一次改坏了它红的运行输出"，本轮两次都执行到了，所以两次都没漏过去。
2. **"实测"二字的作用域**：`可红 112/112` 说的是"每条断言配一个能打红的源码变异"，**不等于**"六页都真跑过"（S-46 还开着），也**不等于**浏览器里量过（S-59 这轮才第一次量到）。写账本时把这两层分开陈述，别让一个总数替另一层背书。
3. 浏览器自动化的视口是**测量条件**的一部分：0 宽视口会让所有 `min-width` 断言静默失效，方向和"门假绿"完全一致。以后凡涉及响应式的实测，简报里要先钉死 `setDeviceMetricsOverride`，并把 `window.innerWidth` 和结论一起打印。


# 旧账 #48 取证：热重载换下的适配器确实不关（2026-09-29，只读探针，脚本跑完即删、源码零改动）

> 前面自我交代里那句 `可红 112/112` 是当时的真实数字；S-46 第一批 + S-61 之后现在是
> **实测 110 项全绿 / 可红 145/145**。账本不回改历史数字，只在此声明当前值。

这一条从第十二轮起一直挂着"等口径裁决"，但**我从来没有实测过它是不是真的漏**。本轮补上：

| 测法 | 结果（原样输出） |
|---|---|
| 构造 `Runtime(cfg_a, …)`，记录 `rt.adapters["res-a"]`，再 `rt._apply(cfg_b)` 把同一资源的 `base_url` 换掉 | `res-a adapter replaced: True` / `换端点后 —— 旧适配器 client 是否已关闭: False` |
| 再把资源列表清空（删资源）后 `_apply` | `删资源后 adapters 里还有 res-a 吗: False` / `被丢掉的 client 是否已关闭: False` |
| 看退出时会不会兜住 | `Runtime.aclose()`（`main.py:377-385`）只遍历**当前** `self.adapters` → 换下/删掉的那些**整个进程周期都不关** |

**机制定位**：`main.py:209` 的 `_apply` 是**同步**方法（所以它压根没法 `await old.aclose()`），
`main.py:237-251` 复用判据只防住"凭据类改动多造一个 client"，被换掉的那些直接掉出字典。

**顺带抓到一处"注释说的比实现做的多"**（本项目反复出现的同一族）：`main.py:227` 写的是
「按资源 id 索引；base_url **或 protocol** 变更才重建，**防在途连接泄漏**」——
读起来像"泄漏已经被这条规则解决了"，实测恰恰是**被重建的那些才没人关**。

**等用户裁决的口径**（不自创）：
- (a) **延迟排空**：reload 时挂一个 asyncio 任务，宽限期取 ≥ 请求总预算（Q16 定过 300s）之后再 `aclose()`。
  优点：不会截断任何合法在途请求；判据能用**假时钟**写，不必真睡 300 秒。
- (b) **引用计数**：在途归零才关。精确，但给运行态加了共享可变状态，异常路径上容易反而漏掉。
- (c) **维持现状但写清**：把注释与行为对齐，接受"配置每改一次留一个 client 到进程退出"。

主控建议 (a)。影响面如实说：本地单用户、改配置不频繁时泄漏很小；但 `PUT /admin/api/config`
每次保存都会走 `_apply`，反复调参 50 次就是 50 个带 keep-alive 的 client 挂到退出。

# S-46 第二批（API 接入页 + 系统设置页真跑）交付，含主控独立复核（2026-09-29 晚）

> 子 agent `gate-s46-pages-a` 在 150 轮上限处**中断**（最后一句是"Now the M-section checks"），
> 但按老规矩**以磁盘为准**判生死：主控亲自复跑后确认**交付是完整的**，不是半成品 ——
> 死在写报告尾巴的阶段，判据与变异已经落盘。
> 数字全部由主控自己重跑取得（不转述 agent 的话）：
> - `node scripts/verify_v2_frontend.mjs <overview>` → **实测 128 项，通过 128 项，失败 0 项**
> - `--mutation` → **可红 184/184；每条断言都有对应变异**
> - `node --check scripts/verify_v2_frontend.mjs` → 语法干净（它没把门改崩）
> - `grep -c 'check("M'` → **18 条**（M0~M17 连续），既有 A/B/C/D/E/F/G/H/I/J/K/L/Z 段**一条没被削弱**
> - `tests/integration/test_int_v2_frontend_gate.py` 两处下限已由它同步钉到 **128 / 184**，
>   并附了"临时改成 999 立刻红"的原样输出（`断言总数只剩 128 条` / `变异表缩水到 184 条`）——
>   下限不是空过这件事它自己验了，我复核了那两行数字确实等于 runner 读数
> - **仓库前端源码零改动**：它的红证与组合红证全程在 `$T/tree/` 副本里种变异（比我上一轮
>   手工"改完再 cmp 复原"的做法更安全，这个纪律值得沿用）

| 项 | 内容 |
|---|---|
| 交付 | 18 条**页面级真跑**判据：API 接入页 M0~M9（密钥表逐行对服务端 / 上屏只能密文 / 眼睛⇄收回且 DOM 不留明文 / 复制写进剪贴板的是明文 / D3 启停成功支与**失败支不得弹绿** / 用途改名恰好一次 PUT 且同值不发请求 / 添加密钥取消零 PUT / 删除的**取消·✕·遮罩**三支都零请求且调用方已返回）；系统设置页 M10~M17（首屏端点 / **12 个输入框逐个绑到生产配置字段且 min 与 schema 下限一致** / 脏态徽章与保存钮**使能同源双向** / 正整数过滤与"清空=未修改" / 二段保存闭环 / 保存失败只有红 toast 带后端原因且**页面仍脏** / 维护区两个破坏性动作都要确认才落地 / 两页产物无坏插值） |
| 组合红证（它的，命令与读数在报告 §6） | API 接入页 **6 条坏改动同时种** → `实测 128 项，通过 121 项，失败 7 项`，红的是 M1,M2,M3,M4,M6,M8,M9，**既有 110 条一条没红**；系统设置页 6 条同时种 → `通过 122 项，失败 6 项`，红 M11~M16，同样不动既有判据 |
| 它推翻/修正我的简报口径 3 处 | ① 简报说"M 段空闲、L 段到 L20"—— 实际本批开始前 L 段已因 S-61 多出 **L21**（它核过不冲突，M0~M17 连续编号没问题）；② 简报把"产物无坏插值"当成能覆盖**字段名打错**的手段 —— **不成立**，因为 `esc(undefined)` 交出的是空串而不是 `"undefined"`（见新账 S-63）；③ 简报没提假定时器不推进，因此 `waitForRecovery` 的**恢复成功支跑不了**，它把它写进负面清单而不是假装判过 |
| 新登记的两条真实现状缺陷 | **S-62**（#88）：`settings.js` 维护区控件没有存在性判断，缺一个按钮会把**整页**崩成 `TypeError`（不是少一个按钮，是白屏）；**S-63**（#89）：`esc()` 的 `String(s ?? "")` 让"后端少给字段"在界面上表现成**一片空白且零提示**，M17 结构上抓不到，需源码侧显式降级文案 |
| 报告 | `docs/changes/e2e-records/gate-s46-pages-a.md`（132KB，11 节：结论 / fixture 取自生产端点 / 假 DOM 四处增量 / 判据清单 / 逐条红证 / 组合红证 / 复原证据 / 与简报不符与登记缺陷 / 负面清单 / 下限非空过 / 最后三连复验） |

# 旧账 #48 已修：热重载换下/删掉的适配器走「延迟排空」（2026-09-29，用户裁决）

> 数字取自 runner 原样输出：`tests/unit/test_v2_adapter_drain.py` → **7 passed in 0.57s**。

| 项 | 内容 |
|---|---|
| 口径 | 用户裁决 = **(a) 延迟排空**（另两案：引用计数 / 维持现状改注释）。宽限期取 `gateway.request_total_budget_seconds`（Q16/§5.5 定 300s）—— **派生自请求总预算而不是拍常数**：在途请求最久不超过总预算，所以"宽限期 ≥ 总预算"既不可能截断任何合法请求，又给出泄漏上界；配置坏值退回 300，退回方向是**等得更久**（保守侧），不是更快关 |
| 落点 | `main.py:194-198` 新增 `Runtime._pending_close` / `_drain_tasks`；`main.py:251-260` `_apply` 末尾按**对象身份**（`id()` 集合）算出"没被复用的那些"交给 `_retire_adapters`；`_drain_grace_seconds()` / `_schedule_drain()` / `_drain_pending()`；`reload_from_file` 有事件循环 → 挂任务，**没有循环时原样留给停机 `aclose()` 兜底**（`_schedule_drain` 捕获 `RuntimeError` 不丢件）；`aclose()` 取消未到期任务并补关待清单项 |
| 顺手改掉的一条谎 | `main.py:227` 原注释写「base_url 或 protocol 变更才重建，**防在途连接泄漏**」—— 实测被换下的 client 整个进程周期都没人关。这就是我自己上一节列的"注释说的比实现做的多"同一族的**第四、五次**实例，现已改成事实并指名 `#48`。**教训固化**：以后凡我在注释里写"防住/避免/不会"这类结果性承诺，同一次提交里必须有一条判据在它不成立时会红 |
| 判据 | 7 条，方向成对：**要关**（换端点进清单 / 过宽限期真关 / 删资源同样排空 / 停机兜底 / 无事件循环留给停机）+ **不能在宽限期内关**（在途请求绑旧快照）+ **口径不得硬编码**（改预算数 → 宽限期跟着变） |
| 撤修复红证 | M1 去掉 `_retire_adapters(...)` 那一行 → **`5 failed, 2 passed`**；M2 去掉 `aclose()` 里的补关循环 → **`2 failed, 5 passed`**；M3 把 `await asyncio.sleep(self._drain_grace_seconds())` 改成 `sleep(0)`（=立刻关）→ **`1 failed, 6 passed`**，红的正是"宽限期内不得关"那条。三次 `cp` 复原后 `cmp` **字节级一致** + `7 passed` |
| 为什么 M3 这条判据必须存在 | 只测"要关"会鼓励出"reload 时马上 aclose"那种**更坏**的修法 —— 它会静默截断正在流式返回的响应。把"不许提前关"也做成判据，才是把这个功能从"看起来对"变成"做对了"的那一步 |

# Q28-⑧⑦ 已实现：删掉 circuit.json 之后「读时重判」（2026-09-29，用户裁决，子 agent 交付 + 主控独立复核）

> 用户裁决 = **读时重判**（否掉"进程间通知/watcher"与"维持现状+文案说明"两案）。
> 交付 by `breaker-rejudge`；**下面每个数字都是主控自己重跑的输出**，不是转述。
> - 全量：`.venv/bin/python -m pytest -q --basetemp=$(mktemp -d) -p no:warnings` → **748 passed in 175.95s**（748 collected 已核）
> - 新判据文件：`tests/unit/test_v2_circuit_rejudge.py` → **22 passed in 0.16s**
> - 定向三文件：`46 passed in 1.86s`

| 项 | 内容 |
|---|---|
| 机制 | `ResourceManager` 新增运行态标记 `ResourceState.circuit_held`（随 `__slots__`/`__init__` 一起加）；成因由写入侧**显式声明**：`circuit_hold()` 作用域 + `quota.circuit_hold_scope(runtime, held=…)` 包住三条熔断路径（`quota.py:831` 全局回写、`:860` 启动对齐、`admin.py:445` 管理端点）；读侧 `reconcile_expired()` 变成**两条释放条件**（到期 ⊕ 熔断已不成立），动作收在 `_lift_for_read` → 出快照与选路**共用同一组动作**（S-15 口径的延伸）；判据注入在 `main.py:200/225/245`（`circuit_active = lambda: zq.get_circuit().active()`，每次回读盘） |
| 分层 | `core/` **不 import** `upstream/zcode/`：走"装配侧注入一个谓词"这条路，而不是让 core 去认识熔断对象 |
| fail-closed 三点 | ① 谓词没接（独立进程跑的 CLI / 未装配的单测）→ **不重判**，行为与改动前一致；② 谓词**抛错** → 不放开；③ `circuit.untrusted`（文件读不动）→ `active()` 本来就返回真，**不特判第二遍**，与 Q28-⑧① 同向 |
| 终态与标记清理 | 只动 `status == "cooldown"`；`invalid`/`disabled` 无路径被改回（Q28-⑥③）；解除后清 `circuit_held`，且**自然到期那条路也要清**（否则下一条别的原因的短冷却会被当成"熔断按住的"提前放开） |
| **主控独立撤修复红证**（逐条单撤，原样尾行） | R1 摘掉释放条件二（`_circuit_cleared` 恒假）→ **`11 failed, 35 passed`**；R2 不看熔断是否成立就登记成因（`circuit_hold_scope` 恒真）→ **`1 failed, 45 passed`**，红的是 `test_a_bench_written_while_the_breaker_is_absent_is_never_registered`；R3 释放时不看成因（=我简报里的"第 1 号坑"）→ **`5 failed, 41 passed`**，红的正是 `test_quota_exhaustion_cooldown_survives_the_breaker_delete` / `test_backoff_cooldown_survives_the_breaker_delete` / `test_a_longer_backoff_after_the_breaker_is_not_released` 等。三次 `cp` 复原均 `cmp` **字节级一致**，复原后 `46 passed` |
| 端到端一条 | `test_running_gateway_rejudges_after_the_user_deletes_the_file` 走**真 `create_app`**：CLI 腿经 `/admin/api/zcode/bench` 回写 → 删文件 → 下一次读就回 `active`。这一条同时兜住"机制存在但没接线"那类事故（谓词在 `__init__` 里没挂上时它会红） |
| 它推翻我的四处简报口径（**都是我写错，不是它抗命**） | ① 归位动作的家是 `ResourceManager`，我写的 `CooldownManager` 是错的；② **成因不能做成参数** —— 既有假件 `bench`/`bench_account` 的签名会被新关键字参数打 `TypeError`，改成显式作用域后标记随 `bench()` 所有权一起换；③ **登记必须只在熔断此刻真成立时**，否则既有 §17 判据 `test_overview_surfaces_circuit_reason` 会被打红（我简报里没预见到这条耦合）；④ 我说要接 `/v1/models` —— **不成立**：`servable_models`（`core/resources.py:237-252`）里 `cooldown` **一直算可服务**（隐藏会让模型从工具里凭空消失），所以重判真正影响的是出快照与选路两处，接到这里只是多一次磁盘回读、行为零差异。它按实测**没接**并写下理由 |
| 顺带被它改到的越界一处 | README 双语的测试数字 710→**748**（`test_v2_readme_claims.py` 的漂移判据被新增 22 条顶红，不更新就全量红）。属"数字必须跟着真实条数走"的既有规矩，已申报 |
| 报告 | `docs/changes/e2e-records/circuit-rejudge.md`（30KB：机制定位 / 每处 `file:line` / 判据↔撤回映射表 / 18 处单点撤回红证原样尾行 / 全量尾行 / 负面清单） |
