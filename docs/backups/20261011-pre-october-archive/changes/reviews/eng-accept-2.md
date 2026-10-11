# 工程验收（第二轮）· eng-accept-2 · 2026-09-27

> 验收人：后端工程（Python / FastAPI / asyncio）· 复核对象 = `docs/changes/e2e-records/E2E-20260927-v2-round2-fixes.md`
> 依据：`docs/specs/tech-design.md` v2.0 §12–§21（§19 交付判据 / §20 不做清单）· `docs/specs/prd.md` v1.15
> 方法：接线逐符号 AST 复核（脚本在 `/tmp/engacc/`，未入库）· 测试替身签名逐个比对 · 反证亲自复跑（改-跑-还原，MD5 校验）· 并发与锁的机制级复现 · 全量复跑
> 纪律：以下每条结论附 `file:line` 或实跑输出；跑过但没结论的写「未验证」。**本轮不复用上轮口径**。

---

## 0. 验收结论：**不通过**（阻塞项 2 条）

**先说不是坏话的部分**（全部我亲自复跑并核对，零出入）：

| 文档声称 | 我的实测 | 判定 |
|---|---|---|
| `537 passed`（全量） | `537 passed, 436 warnings in 67.24s`（`--basetemp=/tmp/eng-acc-pytest`） | ✅ 真 |
| 反证 R1：删 `import json` → claim_wiring **10 failed** | `10 failed in 0.14s`（逐个 FAILED 列出，恢复后 10/10） | ✅ 真 |
| 反证 R3：`reserve_quota` 改 `if True` → **4 failed**（含端到端超发） | `4 failed, 16 passed`：`test_concurrent_reservations_do_not_oversubscribe` / `test_exhausted_resource_is_skipped_and_backup_takes_over` / `test_reserve_happens_in_the_same_sync_segment_as_in_flight` / `test_int_v2_quota_reserve.py::test_exhausted_quota_does_not_take_more_requests` | ✅ 真 |
| `ui_verify_v2_visible.py` 后端 9/9 + 前端 18/18 | `后端出口实测 9 项，通过 9 项，失败 0 项` + `实测 18 项，通过 18 项` | ✅ 真 |
| 锁状态是进程级全局 → 用例顺序会不会串 | `test_v2_ops.py` 连跑两次 **43 passed / 43 passed**；ops 族合并 **101 passed**；倒序 **80 passed**；`data/ops-locks` 未在仓库生成 | ✅ 无串扰（`tests/conftest.py:8-29` 两个 autouse fixture 有效） |
| 上轮 S1（fake 掩盖 `bench` 签名） | `_FakeResources.bench(self, state, seconds)`（`tests/unit/test_v2_zcode_quota.py:236`）↔ `ResourceManager.bench`（`core/resources.py:204`）**一致**；`lambda acc, cfg=None` ↔ `resource_ids_of_account`（`quota.py:373`）一致 | ✅ 已修 |

**不通过的两条阻塞项**（都有机械复现，不是观感判断）：

1. **S-1 · §19 M5-3「并发不超发」判据在同账号多映射的常见配置下不成立**：额度是**账号级桶**，预留却是**按 (rid, vendor_model) 状态各记一份**。一个账号 1 单位余量、映射 2 个厂商模型 → 两条状态各自 `quota_remaining=1` → **两个请求同时获批**（`/tmp/engacc/probe.py` 实跑输出：`concurrent picks on a 1-unit account: 2 -> OVER-ISSUE`）。这正是 R3 自己立的靶子（「并发请求可全部撞在同一个'剩余额度=1'的账号上」），也只是靶子的**单状态特例**被修掉了。
2. **S-2 · 「死代码 / 全接线」结论仍不实，且 12 符号 AST 护栏在设计上抓不到**：本轮自称把上轮的 3 个无调用点清零（R7 + §一「该结论不成立，已在本轮修正」）。我的逐符号 AST 扫描（`/tmp/engacc/wiring.py`，262 个公开符号）显示 **v2.0 §12–§21 范围内仍有 ≥5 个零生产调用点符号**，其中一个是 §17 点名的 **`CooldownManager`（`upstream/zcode/quota.py:286`：3012 熔断 30min 落盘 + 10s 节流）—— 全仓只有 `tests/unit/test_v2_zcode_quota.py:162/176/179/185/193/204` 引用它**，生产从不实例化。护栏抓不到的原因见 §2。

> 一句话：**绿是真的、反证是真的、9+18 是真的；但「判据本体覆盖到的那一格」不等于「交付」**。修 S-1/S-2 + 补 §6 的 4 组护栏后可复核。

---

## 1. 接线核对表（`model_gateway/` 内计数，tests/scripts 不算）

脚本：`/tmp/engacc/wiring2.py`（AST，定义行的名字本身不计引用）。

| 符号 | 定义 | 生产调用点 | 判定 |
|---|---|---|---|
| `admin_post` | `core/local_admin.py:19` | `cli_probe.py:140`、`cli_zcode.py:266`、`ops/builtin/zcode_claim.py:110` | 已接 |
| `servable_models` | `core/resources.py:79` | `api/openai_compat.py:53`、`cli_setup.py:33/96`、`main.py:252` | 已接（路径 A/B + 告警三处同源）✅ BUG-1 名副其实 |
| `refresh_runtime_quotas` | `upstream/zcode/quota.py:240` | `api/admin.py:348`、`main.py:70`（← `main.py:102/107/110`） | 已接，但见 M-10（「启动」触发点是条件化的） |
| `read_account_snapshot` / `remaining_units` | `quota.py:206 / 228` | `api/admin.py:361`、`quota.py:260` | 已接 |
| `set_quota` | `core/resources.py:221` | `quota.py:265` | 已接 |
| `reserve_quota` | `core/resources.py:228` | `core/resources.py:193`（`pick_and_acquire` 同段） | 已接 |
| `settle_quota` / `release_quota` | `resources.py:240 / 247` | `scheduler.py:450 + 624` / `scheduler.py:465 + 726` | 已接；**流式那一半零测试**（M-1） |
| `bench_account` | `quota.py:392` | `api/admin.py:410`、`zcode_claim.py:106` | 已接（两条腿都在） |
| `apply_to_resource` | `quota.py:348` | `quota.py:401` | 已接（上轮 S1 的接线缺陷不复存在） |
| `resource_ids_of_account` | `quota.py:373` | `quota.py:257/398`（两处都传 `runtime.config`） | 已接 |
| `build_headers` | `upstream/zcode/auth.py:53` | `upstream/zcode/claim.py:83` | 已接，且 `_headers` 有真实断言（`test_v2_zcode_claim.py:188/196`） |
| `delete_account` | `upstream/zcode/store.py:203` | `cli_zcode.py:168` | 已接 |
| `degrade_effort` | `core/dialects.py:53` | `core/scheduler.py:251` | 已接 |
| `run_once` / `write_report` / `bump_failed_counter` / `clear_failed_counter` | `ops/runner.py:229/297/315/326` | `cli_zcode.py:224`+`main.py:102` / `main.py:103` / `main.py:104` / `api/admin.py:389` | 已接 |
| `AccountLocks` / `PlanLock` / `ops_lock_dir` | `ops/runner.py:62/155/56` | `runner.py:187/164/235`、`runner.py:351/354`、`runner.py:82` | 已接，但见 M-2 / M-9 |
| `build_client` / `looks_like_jwt` / `fingerprint_available` | `auth.py:80/45/98` | `adapters/anthropic_out.py:458/479`、`main.py:193` | 已接（上轮 M4 大体收敛；残留偏离见 m-5） |
| **`CooldownManager`** | `quota.py:286` | **0** | 🔴 **未接**（§17「熔断状态落盘防重启丢失 + 节流 10s」在生产中不存在） |
| **`Cooldown`** | `quota.py:273` | 2（`quota.py:291/300`，**全在被弃用的 CooldownManager 内部**） | 🔴 死链 —— 护栏把它判成「已接」，见 §2 |
| **`AccountInfo`** | `dataroot.py:48` | **0** | 🔴 未接（v2.0 新增 dataclass） |
| **`Bucket.reset_note`** | `quota.py:54` | **0** | 未接（v2.0 新增 property） |
| **`OpReport.all_normal`** | `ops/base.py:61` | **0**（仅 `test_v2_ops.py:88/98/114`） | 未接 |
| **`crypto.roundtrip_ok`** | `crypto.py:139` | **0**（仅 `test_v2_zcode.py:71`） | 未接 |
| `save_config` | `config/loader.py:57` | **0** —— `api/admin.py:507-515` **另写了一份原子写**（且少 `os.fsync`） | 上轮遗留：死代码 + 与 §4.7 中心化的原子写重复 |
| `adapters/openai_out.list_models` | `openai_out.py:183` | **0**（`/v1/models` 不走上游） | 上轮遗留 |
| `errors.wrap_httpx_error` / `retryable_hint` | `core/errors.py:130 / 63` | **0** —— 两个适配器各自 `except httpx.TimeoutException/HTTPError` 内联 5 处（`openai_out.py:110/158/175`、`anthropic_out.py:527/584`） | 上轮遗留：与 R7「消掉第三份 Bearer/UA 构造」同类的重复，未清 |

**对照文档口径**：§一 写「仍有 3 个无调用点（`auth.build_headers` / `oauth.refresh` / `store.delete_account`）」——这 3 个本轮确实处理了（前两个接线、`oauth.refresh` 连同 `TOKEN_URL` 删除，`test_removed_dead_symbols_stay_removed` 守住）。但**「残余死代码」远不止那 3 个**：v2.0 范围内还剩下表中标 🔴 的 5 项（`CooldownManager`/`Cooldown`/`AccountInfo`/`reset_note`/`all_normal`/`roundtrip_ok`），另有 4 项上轮遗留。**R7 的账只结了一半，却按「全接线」的口径交付。**

---

## 2. 对 12 符号 AST 护栏的攻击（`tests/unit/test_v2_cli_zcode.py:132-188`）

护栏是真的（12 个参数化用例，我核对过数量），也确实比 grep 强（docstring/注释不计）。但它**不能完成它被赋予的职责**，三个独立缺口：

| # | 缺口 | 证据 | 后果 |
|---|---|---|---|
| G-1 | **清单自选（cherry-picked）**：`_WIRED_SYMBOLS`（`:135-148`）只列已知的 12 个。新增一个没人调的公开函数，护栏永远不会知道 | 我的全量 AST 扫描得到 262 个公开符号、32 个零引用（含 FastAPI 装饰器注册的路由，排除后仍有 §1 表中的 🔴 项）；`CooldownManager` 不在清单里 | 「防再长回来」只防住 12 根已知的草，**新长的不防**。上轮 51 函数、本轮 12 符号，两轮都是「数自己列的表」 |
| G-2 | **只数「名字出现过」，不看引用者自己是否活着**：`ast.walk` 在整个包里找 `Name/Attribute`，**死代码内部的引用照样算数** | `Cooldown` 的 2 个「引用」（`quota.py:291/300`）全部位于从未被实例化的 `CooldownManager` 体内。把 `Cooldown` 加进清单 → **测试直接通过**，而它是死的 | 一条死链上的符号可以无限互相「作证」 |
| G-3 | **期望文件映射是装饰**：`_WIRED_SYMBOLS` 的 value 只出现在断言失败的消息里（`:178-179`），**从未被断言** | 例如 `settle_quota: "core/scheduler.py"` —— 只要全仓任何地方出现这个名，用例即绿；接错到别的（甚至同为死代码的）文件不会红 | 「按判据接线」这一层没有约束，护栏实际只回答「这名字还有人提吗」 |
| G-4 | （附带）`test_removed_dead_symbols_stay_removed`（`:182-188`）用**整包字符串拼接**找 `"def refresh("` 等，注释/docstring 里提一句就会假红；且 `def refresh(` 无差别禁止今后任何同名函数 | `:184-188` | 能防复活，但会误伤；建议同样换成 AST |

**建议改法（成本低、能守住）**：把护栏从「名字被提过」升级为 **「自 `main.py`/`cli.py`/`api/*` 可达」**——从生产入口做 AST 调用图 BFS，列出所有不可达的公开定义即为红；清单不再需要人工维护（G-1/G-2 同时解决），期望落点用「可达路径必须经过 X 文件」来表达（解决 G-3）。

---

## 3. 测试替身签名核对表（ops → claim → quota → resources 链）

真实可调用 ↔ 注入的替身，逐个比对（`inspect` 级别，不是读注释）：

| 替身 | 定义 | 顶替的真实可调用 | 签名 | 风险 |
|---|---|---|---|---|
| `_FakeClient` | `test_v2_claim_wiring.py:68`（`preview`/`claim(plan_id,*,manual)`/`report_activation(*,user_id="")`/`aclose`） | `upstream/zcode/claim.py:205/224/239/255` `ZCodeClaimClient` | ✅ 四个方法逐一对齐（`report_activation` 多给了默认值，无害） | ⚠️ **顶替的是整个客户端类**：真实 `_get`/`_post`/`claim`/`report_activation` 的 HTTP 腿（`claim.py:179-253`）与 `zcode_claim.claim` 的 `client_factory is None` 构造分支（`zcode_claim.py:126-129`）**均无任何测试执行**。见 M-7 |
| `_Recorder.fake(runtime, account, *, reason, seconds=None)` | `test_v2_claim_wiring.py:100` | `quota.py:392 bench_account` | ✅ 一致 | 但它顶替的正是「回写实现」本身 → 与下一行叠加后，**claim→bench_account→apply_to_resource→ResourceManager.bench 整链在单个测试里没有真跑过** |
| `record_admin_post.fake(path, **kw)` | `test_v2_claim_wiring.py:113` | `core/local_admin.py:19 admin_post(path, *, port, timeout, payload, config_path)` | ❌ **`**kw` 宽松吸收任意关键字** | 🔴 **正是上轮 S2 的形态**：R2 修的跨进程出口，其客户端被一个什么都收的假函数顶替 → `admin_post` 内部（端口解析 `:27-32`、payload 键名、失败返 None）**测试结构上不可能发现**。我在 M-4 发现的「端口读默认配置 → 静默 None」恰好藏在这层假下面 |
| `_NoProxyClient(*a, **kw)` | `test_int_v2_ops_isolation.py:29` | `ZCodeClaimClient(base, jwt, mid, proxy=)` | ❌ 构造器宽松；且**缺 `report_activation`**（该用例走 failed 分支未触发） | 构造参数漂移不可见（同 M-7） |
| `run_once` 的假 claim | `test_v2_ops.py:74/93/119/…`（`async def claim(account, *, manual=False, runtime=None)`） | `zcode_claim.claim(account,*,manual,client_factory,runtime)` | ✅ 兼容（少 `client_factory`，`run_once` 从不传） | 一处例外：`test_v2_ops.py:345` 用 `lambda a, **k` → 宽松 |
| `_FakeResources.bench(self, state, seconds)` | `test_v2_zcode_quota.py:236` | `resources.py:204` | ✅ 一致（上轮 S1 修的那条，本轮守住） | — |
| `lambda acc, cfg=None` | `test_v2_zcode_quota.py:299/312` | `quota.py:373 resource_ids_of_account(account, config=None)` | ✅ 一致（R3 明确同步过） | — |
| `lambda root, name, **kw` | `test_v2_quota_reservation.py:241/265` | `quota.py:206 read_account_snapshot(root, account, *, log_dirs_tail=3)` | ✅ 兼容（`**kw` 吃掉 `log_dirs_tail`，宽松但不致错） | — |
| `_FakeRuntime.config.resources[].id` | `test_v2_zcode_quota.py:247` | 真实 `quota.py:389` 读 `r.account` | ❌ 假配置没有 `account` 属性 | 仅在 `resource_ids_of_account` 被顶替时才不炸；若哪天解除顶替，这里会 AttributeError（提醒，不算缺陷） |
| **`POST /admin/api/zcode/bench`（R2 新增服务端）** | `api/admin.py:394-423` | — | — | 🔴 **仓库内没有任何测试 POST 过它**（`tests/` 全文只在 `test_v2_claim_wiring.py:152` 断言"客户端会打到这个 path 字符串"）。端到端我替它补了：见 §4-E |

**判定**：链上「上轮被打过脸的那两处」（`bench` / `resource_ids_of_account`）签名已严格对齐，是真进步。但**新引入的两处出口（`admin_post` 客户端、`/zcode/bench` 服务端）用了一个宽松假 + 零服务端测试**，等于把 R2 的修复放在了没有护栏的地面上。

---

## 4. 并发与锁的正确性分析

### A. 预留是否在所有出口释放？——**是的**（读码 + 实跑，逐出口）

`pick_and_acquire` 在同一同步段做「预留 + `in_flight += 1`」（`resources.py:191-197`，段内无 await，事件循环单线程 → 真原子）。收尾：

| 出口 | 位置 | 结果 |
|---|---|---|
| 非流式成功 | `scheduler.py:448-451` → `settle_quota` + `settled=True` | ✅ 预留转消耗 |
| 非流式其余全部（BAD_REQUEST/CANCELED 抛错、AUTH/NOT_FOUND/QUOTA break、m 耗尽、预算耗尽、`finally`） | `scheduler.py:462-465`（`finally: release; if not settled: release_quota`） | ✅ 释放 |
| 流式成功（流自然结束） | `scheduler.py:623-625` | ✅（但见 M-1：无测试） |
| **流式首帧后中途失败**（committed → yield error 帧 → `return`） | `scheduler.py:636-659`，`return` 穿过内层 `finally: aclose_quiet`（`:721-722`）再穿外层 `finally`（`:723-726`），`stream_settled` 仍为 False → 释放预留 | ✅ **实跑验证**：`remaining=2 reserved=0 in_flight=0 status=active C=1`（`/tmp/engacc/probe2.py` P7-b） |
| 流式首帧前失败 → 切换/503 | 同上外层 `finally` | ✅ 实跑：`rc 503 · remaining 2 reserved 0 in_flight 0`（P7-c） |
| 客户端断连 / `CancelledError` | 两个 `finally` 均在异常链路上 | ✅（`in_flight` 归零另有 `diag_*` 脚本族佐证） |
| 预算耗尽 | `scheduler.py:372-375 / 581-584` → break → `finally` | ✅ |

**唯一的理论泄漏窗口**：`pick_and_acquire` 返回（`scheduler.py:352`）到 `try:`（`:367`）之间若 `_emit_switch` 抛异常，预留与在途都不释放。核查 `stats/events.py:65-66` 只做 `queue.put_nowait`（无界队列不抛）、`switch_ring` 是 `deque(maxlen=200)` → **实际不可达**，列为已核查非缺陷（m-8）。流式同段（`:561-576`）同理。

### B. `quota_reserved` 会不会跨请求上漏？——**当前不会，但埋了两颗雷**

- 雷 1（**M-5**）：`reserve_quota(state, amount)` 按 `amount` 加，`settle_quota`/`release_quota` 却**硬编码减 1**（`resources.py:237/244/251`）。生产目前没有 `amount≠1` 的调用点（两处 `pick_and_acquire` 都用默认值），所以不发作；但 `pick_and_acquire(..., amount=…)` 是公开参数，单测 `test_v2_quota_reservation.py:210` 还专门测了 `amount=5`，**没有任何测试测它的结算对称性**。实跑：`pick(amount=3)` → `reserved=3`；`settle_quota()` → `reserved=2`（应为 0）→ 预留永久残留。
- 雷 2（**M-1**）：流式结算分支无护栏（下面 C 项）。

### C. 「反证 4 failed」证明的是非流式，**流式那一半是裸的**

我做了两次额外反证（都改完即还原，MD5 校验一致）：

| 撤掉的修复 | 结果 | 结论 |
|---|---|---|
| 流式成功路径不置位 `stream_settled`（`scheduler.py:625` 改 `pass`） | `537 passed`（全绿） | 弱反证：`release_quota` 的 `max(0,…)` 掩盖了双减 → 行为无变化，**不能据此说有覆盖** |
| **删掉流式成功路径的 `settle_quota`（`scheduler.py:624`）** —— 等价于「每次成功流式响应永久泄漏 1 个预留」 | **`537 passed`（全绿）** | 🔴 **M-1：流式额度结算/泄漏在生产测试里照不出来**。R3 声称「两条路径对称收尾」，其中一条从未被测。文档的 4-failed 反证全部来自非流式 + 记账单测 |

### D. 「并发不超发」用例是真的并发吗？——**是**

- 单元（`test_v2_quota_reservation.py:119-155`）：`asyncio.gather` 起 10 个 worker，每个拿到资源后 `await hold.wait()` 真实重叠，额度 3 → 恰好 3 个 `ok`、`reserved/in_flight` 归零。顺序 for 循环不可能产生这个结果，且 MUT-B 会让它红 → **有效**。
- 端到端（`test_int_v2_quota_reserve.py:25-44`）：真实 uvicorn + 真实调度器 + 真实适配器，上游 `delay=0.5` 把 5 个请求叠在飞行中 → 2 成 3 败（503）→ **有效**。
- 但两者都是**单状态**。跨状态就破了 → **S-1**。

### E. 我替 `POST /admin/api/zcode/bench` 补的实测（`/tmp/engacc/probe2.py`，ASGITransport，真实 ResourceManager）

```
before: active None
   POST rc: 200 {'ok': True, 'account': 'acct-a', 'benched': 1}
   after : cooldown 'ZCode 风控熔断（30min）' cooldown_ms= 1799999
   missing account -> rc 400 {'error': 'account 必填'}
   unknown account -> rc 200 {'ok': True, 'account': 'ghost', 'benched': 0}
   garbage body   -> EXC JSONDecodeError（→ 500，非 400）
```
结论：**端点本身是好的**（`bench_account → resource_ids_of_account(runtime.config) → apply_to_resource → ResourceManager.bench(state, 1800)` 全链正确，30min 时长与 `last_error` 文案都对）。缺陷是①仓库无护栏（M-8），②非 JSON 请求体走 500。

### F. 跨进程锁（`ops/runner.py`）——**R4 只做到了「机制存在」，四个条件下它静默失效**

| # | 问题 | 证据（实跑/`file:line`） |
|---|---|---|
| ① | **锁目录随 cwd 变化**：`ops_lock_dir()` 返回相对路径 `data/ops-locks`（`runner.py:56-59`），网关 cwd=仓库（`启动网关.command:19 cd "$(dirname "$0")"`），`mgw` 是装的 console script（`pyproject.toml [project.scripts]`）可在任意目录跑 | `cwd=/tmp -> data/ops-locks => resolved: /private/tmp/data/ops-locks` / `cwd=repo => ...: /Users/w/Desktop/Model-Gateway/data/ops-locks` / `HOME cwd -> /Users/w/data/ops-locks`。**两份锁文件，跨进程互斥不存在**。（可达性说明：cwd 变了 `store.accounts_root()` 也变（`store.py:27/49-52`，同样相对），CLI 会因"无账号"而 rc=2 拦在路上；但 README:109 明确教的 `MGW_ZCODE_ACCOUNTS` 绝对路径覆盖 + 没设 `MGW_OPS_LOCK_DIR` 时，**账号看得见、锁不在同一处 → 双领成立**） |
| ② | **锁目录不可写 → 直接当作「已拿到锁」**：`runner.py:103-106` `except OSError: return True`，无任何日志/告警 | `MGW_OPS_LOCK_DIR` 指向不可写父目录：`a.try_acquire('x')=True`、锁文件 `[]` 一个都没写出来 → 跨进程层静默蒸发（同进程还有 `_HELD_BY_US` 挡着，跨进程彻底裸奔）。与 §12.1「消灭静默降级」直接冲突 |
| ③ | **create 与 write pid 非原子 → 0 字节锁被当成陈旧锁回收**：`runner.py:109-118` `O_CREAT\|O_EXCL` 拿到 fd 后才 `f.write(pid)`；竞争方此时 `_read_pid` 读空 → `int("")` ValueError → `None` → `runner.py:112` 判定非存活持有者 → `unlink` 重建 | `_read_pid(empty) = None` / `try_acquire('acct') on a 0-byte lock of a LIVE process -> True`。窗口只有微秒级，但 `test_corrupt_lock_file_is_reclaimed`（`test_v2_ops.py:419`）恰恰把「内容读不出 pid 就抢」固化成了期望行为 —— 空文件与损坏文件在代码里不可区分 |
| ④ | **`_HELD_BY_US` 只按账号名、不按锁文件路径**（`runner.py:52/134-152`），任何一个实例的 `release(name)` 都会摘掉别的实例的在册持有；而 `_acquire_file` 见 `pid == os.getpid()` 就认定「自己重启留下的陈旧锁」并 unlink 重建 | A(d1) 持 'x' → B(d2) `try_acquire('x')=False`（**不同目录也被挡**，方向相反的另一类串扰）→ B `release('x')` → C(d1) `try_acquire('x')=True` **抢走了 A 仍在持有的锁**，A 毫无察觉。生产里 `_SHARED_LOCKS` 与每个 `PlanLock._files` 就是两个实例（`runner.py:187/164`）；目前靠「账号名 ≠ `__plan__`」侥幸不撞 —— 而 `_sanitize`（`store.py:91-95`）允许账号叫 `__plan__` |
| ⑤ | **PID 复用只判活、不看年龄**：`_pid_alive`（`runner.py:89-97`）对存活的 pid 一律认账，没有 TTL/最大持有时长；网关崩溃后若 pid 被系统回收给长命进程 → 该账号/`__plan__` 锁**永远拿不到**，`Scheduler._tick`（`runner.py:366-367`）**静默 return**，`skipped_ticks` 也不计数（只有 cron 未命中才 +1，`:385`）→ 运营从此不再跑，界面/日志无任何痕迹 | 读码 + `runner.py:364-371`；`test_second_process_succeeds_after_holder_exits` 只测了 pid 已死的乐观分支（`test_v2_ops.py:408-416` 手工写 999999） |
| ⑥ | **`run_once` 的 release 配对**：✅ 正确（`runner.py:278-286`，`try/finally` 包住 `_run_one`，异常/取消都释放；释放顺序是先 `_HELD_BY_US.discard` 再删文件） | — |
| ⑦ | **`_tick` 里 `plan_lock.try_acquire()` 抛出即杀死调度任务**：`_acquire_file` 只兜了 `mkdir` 的 OSError，`os.open` 的其他 OSError（EACCES/ENOSPC/ELOOP）会从 `runner.py:169` 冒到 `Scheduler._tick:366`，此时 `threading.Lock` 已被 acquire 且不会释放（`:166-171` 的顺序），异常继续冒到 `loop()`（`:377-386`）→ **asyncio 任务静默终止**（无人 await，只在 GC 时留一条 "Task exception was never retrieved"），此后运营永久停摆 | 读码；`PlanLock.release`（`:174-179`）只在 `try/finally` 内被调用，而抛出发生在进入 `try` 之前 |

**「`mgw zcode claim` 与网关 cron 是否真的互相竞争？」**：默认安装（cwd 一致 + 锁目录可写 + 不设 `MGW_ZCODE_ACCOUNTS`）→ **成立**，`test_run_once_skips_account_held_by_another_process`（`test_v2_ops.py:448`）用真实子进程证明了机制可用。**双领仍然可构造**：走上面 ①（绝对 `MGW_ZCODE_ACCOUNTS` + 不同 cwd）、②（锁目录不可写）、③（create/write 竞争窗口）任一条。

### G. 并发正确性小结

非流式路径的预留/结算/释放是**干净的**；锁的**机制**（O_EXCL 原子创建、pid 判活、陈旧回收、TryLock 不排队、串行+抖动、逐账号隔离）也都**写对了**。问题集中在：跨状态记账口径（S-1）、刷新与本地记账互相抵消（M-3）、以及 6 个「静默失效」条件（M-2）。

---

## 5. 复跑结果（精确数字）

```
$ .venv/bin/python -m pytest -q --basetemp=/tmp/eng-acc-pytest
537 passed, 436 warnings in 67.24s (0:01:07)          ← 与文档一致

$ .venv/bin/python scripts/ui_verify_v2_visible.py
后端出口实测 9 项，通过 9 项，失败 0 项
实测 18 项，通过 18 项，失败 0 项                      ← 与文档一致（该脚本自起临时配置+随机端口，未触碰运行中的网关与 ~/.zcode）

顺序无关性（锁状态是进程级全局，故专测）
  tests/unit/test_v2_ops.py                              43 passed  in 5.13s
  tests/unit/test_v2_ops.py（第二次独立进程）             43 passed  in 5.17s
  ops+claim_wiring+cli_zcode+zcode_quota+ops_isolation   101 passed in 6.12s
  倒序（zcode_quota→claim_wiring→ops）                    80 passed  in 5.21s
  仓库 data/ 未生成 ops-locks（conftest 隔离有效）

逐文件用例数 vs 文档表（`--collect-only -q`）
  test_v2_claim_wiring 10 ✅ | test_v2_quota_reservation 16 ✅ | test_int_v2_quota_reserve 4 ✅
  test_v2_ops 43 ✅ | test_v2_cli_zcode 20 ✅ | test_int_v2_ops_isolation 1 ✅ | test_v2_zcode 37 ✅
  test_v2_servable   声明 12 → 实测 11 ❌（m-1）
  test_int_v2_servable 声明 6 → 实测 7 ❌（m-1）
  AST 护栏参数化用例 12 ✅（与 §三「12 个参数化用例」一致）

反证复跑（改 → 跑 → 还原 → MD5 比对）
  (a) 删 zcode_claim.py `import json`              → 10 failed ✅ 声称成立
  (b) pick_and_acquire `if self.reserve_quota(...)` → `if True` → 4 failed ✅ 声称成立
  (c) 流式 settle_quota 删除（新增）                → 537 passed ❌ M-1
  基线 MD5：zcode_claim fee56b0e… / resources a85338bd… / scheduler ddac5c59…
  还原后 MD5：三者与基线逐字节一致 ✅

开工前 462 的基线数：**未验证**（工作树无该快照，无法回溯）
```

---

## 6. 新发现缺陷清单（严重 / 中等 / 轻微）

### 🔴 严重（2）

**S-1 · 额度按「资源条目」而非「账号桶」预留：同账号多映射时并发超发，M5-3 判据本体不成立**
- 位置：`upstream/zcode/quota.py:263-266`（`for state in mgr.registry.values(): if state.resource_id[0] in rids: mgr.set_quota(state, remaining)`）+ `core/resources.py:69-76/228-238`
- 机理：`remaining_units` 是**账号级**余量，被原样写给该账号的**每一个** `(rid, vendor_model)` 状态；`reserve_quota` 只在单个状态内做 `remaining - reserved` 闸门 → N 个状态各拿一份完整额度。
- 最小复现（`/tmp/engacc/probe.py`，走生产 `refresh_runtime_quotas` + 生产 `pick_and_acquire`）：
  ```
  资源 res-z(account=acct-a) 映射 vm-1 / vm-2，日志快照 available=1
  refresh updated: 2 states
  state ('res-z','vm-1'): remaining=1 reserved=0
  state ('res-z','vm-2'): remaining=1 reserved=0
  concurrent picks on a 1-unit account: 2 -> OVER-ISSUE
  ```
  一个资源服务多个厂商模型是 Q18/Q24 之后的**常态**（同一 Key 下 glm-4.5 + glm-4.5-air），所以这不是边角。
- 建议修法（任择一，都很小）：① 把预留粒度提到账号桶：`ResourceState` 持 `bucket: AccountBucket`（含 `remaining/reserved` 各状态共享），`has_quota/reserve/settle/release` 全部走桶；② 或 `refresh_runtime_quotas` 写 `set_quota(state, remaining // len(states_in_account))`（保守切分）并加注释说明是近似。③ 补一条端到端用例：同账号 2 映射 + 额度 1 + `asyncio.gather` → 断言恰好 1 个 200。

**S-2 · 「全接线/死代码清零」结论不实；12 符号 AST 护栏在设计上抓不到（G-1/G-2/G-3）**
- 位置：`upstream/zcode/quota.py:286 CooldownManager`（+ `:273 Cooldown`、`:317 enter`、`:324 clear`、`:338 should_throttle`、`:343 mark_called`）/ `dataroot.py:48 AccountInfo` / `quota.py:54 reset_note` / `ops/base.py:61 all_normal` / `crypto.py:139 roundtrip_ok`
- 证据：`/tmp/engacc/wiring.py` 输出 + `grep` 全包命中只在 `tests/`：见 §1 表。
- 影响分层说清楚：**§19 M4-4 的判据（熔断回写 `ResourceState.status`、转发自动绕开）是达到的**（`bench_account → apply_to_resource → bench`，我在 §4-E 端到端实测通过）。**不达的是 §17 的两条附加口径**：「3012 熔断**状态落盘**（防重启丢失）」与「**节流 10s**」—— 实现体在 `CooldownManager` 里，生产从不实例化 → 网关重启即忘记熔断、且领取/额度通道没有任何 10s 节流。同时 `test_v2_zcode_quota.py:295` 的注释自己写着「`apply_to_resource` / `CooldownManager` 此前零生产调用点」——只修了前者。
- 建议修法：要么接线（把 `CooldownManager` 挂到 `runtime`，`_maybe_bench` 与 `refresh_runtime_quotas` 读它的 `active()/should_throttle()`，重启时 `_load()`），要么**按 §19 的口径把它降级为「本期未做」并从 §17 决策表旁边标注**，同时把护栏改成 §2 末的可达性版本（否则下轮还会以同样的形式失真）。

### 🟡 中等（10）

**M-1 · 流式额度结算/释放零测试覆盖**（证据：§4-C 反证 (c) `537 passed`）。R3「两条路径对称收尾」的一条无护栏。建议：把 `test_int_v2_quota_reserve.py` 的两个用例各加一个 `stream=True` 版本（`StreamOk(chunks=…)` 成功 → 断言 `remaining-1/reserved=0`；`abort_after=1` → 断言 `remaining` 不变 / `reserved=0`），后者我已手工跑通可直接转成用例。

**M-2 · 跨进程锁 6 个静默失效条件**（详见 §4-F ①②③④⑤⑦）。最小修法打包：① 锁目录改为绝对锚定（`runtime.config_path.parent / "ops-locks"`，CLI 侧从 `MGW_DATA_DIR`/`--data-dir` 解析，与 `accounts_root()` 同源）；② `mkdir` 失败时**降级要出声**（返回一个 `degraded` 标记，`run_once` 落 `report.note` + 日志 warning）；③ 锁文件创建用 `os.write(fd, pid)` 后立即 `fsync`，并把「读不出 pid」判为**持有**而非陈旧（除非 mtime 超阈值）；④ `_HELD_BY_US` 键改成 `(str(lock_dir.resolve()), account)`；⑤ `__plan__` 与账号名空间隔离（plan 键加 `\x00` 前缀或放 `__plan__/` 子目录）；⑦ `PlanLock.try_acquire` 内部先 `try/except` 释放 threading lock 再上抛，`Scheduler.loop` 外面包一层 `except Exception` 记日志继续。

**M-3 · tick 刷新把本地已消耗的额度「复活」**：`quota.py:265` 是无条件 `set_quota(remaining)`，而 `settle_quota`（`resources.py:245`）在两次刷新之间本地递减。客户端日志**只在 ZCode 客户端自己调 billing/balance 时才更新**（§17 明说日志通道是主用），所以日志一停更，每个 tick 都把余量写回旧值 → 闸门实际变成「每 60s 放行 N 个」而不是「总共 N 个」。与 S-1 叠加后超发放大。建议：`state.quota_remaining = min(快照值, 上次快照 - 已结算消耗)`，或按桶记 `consumed_since_snapshot` 并在刷新时扣减。文档 N1 只承认了「量纲未实测」，未承认这条。

**M-4 · 跨进程出口的端口/配置解析读默认路径，`MG_CONFIG` 被完全忽略**：`local_admin.py:27-32`（`load_config(None)` → `config/loader.py:22-35` 的 `data/config.yaml`，cwd 相对）与 `ops/builtin/zcode_claim.py:62-65 _plan_endpoint()` 同样问题。而 `MG_CONFIG` 只在 `main.py:48/302-306` 被认（`启动网关.command:20` 明确支持它），`load_config` 本身不读该环境变量。**后果**：用 MG_CONFIG 或非 8300 端口的用户，CLI 领取遇 3012 → `admin_post` POST 到 8300 → 连不上 → **返回 None 静默跳过**（`local_admin.py:43-44`），R2 声称修掉的「熔断静默不生效」以另一种形式回来；`_plan_endpoint` 也会读到错误文件的 proxy/plan_base。`cli_probe.py:140` 是传了 `port=` 的（正确写法），`zcode claim` 这条没传，且 `mgw zcode claim` 根本没有 `--config` 选项（`cli.py:63-66`）。建议：`load_config` 认 `MG_CONFIG`，或 `admin_post`/`_plan_endpoint` 接受 `--config` 并默认解析同一环境变量；`admin_post` 返回 None 时 CLI 至少打印一行「网关未运行/端口不符 → 熔断未回写」。

**M-5 · `reserve_quota(amount)` 与 `settle_quota/release_quota`（硬编码 1）不对称 → amount>1 永久泄漏**：`resources.py:237` vs `:244/:251`。实跑：`amount=3` 结算后 `reserved=2`。生产暂无 amount≠1 调用点（潜伏）。建议：`settle_quota(state, consumed=1)` 同步减 `consumed` 个预留（或让 `pick_and_acquire` 记下 `amount` 到状态里，收尾按记录值释放），并在 `test_v2_quota_reservation.py:210` 补断言对称性。

**M-6 · §17「3012 → 全局熔断」口径未落实，且未进偏离清单**：§17 决策表写「对**全部 ZCode 账号**一并回写，`last_error` 注明『全局熔断』」；实现 `quota.py:392-401 bench_account` 只解析**触发风控的那一个账号**的资源，reason 串是「ZCode 风控熔断（30min）」（`zcode_claim.py:104`），无「全局」。文档 §5.1/5.2 的偏离清单里没有这一条（只披露了 §17 触发点② 与 `tool_call` 默认值）。要么补齐（`for acc in store.list_accounts(): bench_account(...)` + 文案加「全局」），要么把 §17 口径改成「单账号熔断」并请用户确认。

**M-7 · 生产 `claim()` 的真实客户端构造分支零测试**：`zcode_claim.py:126-129`（`client_factory is None` 时才构造 `ZCodeClaimClient` + `_plan_endpoint()`）——所有测试都注入假客户端，真实构造参数、`proxy` 生效路径、三段式 HTTP 腿（`claim.py:179-253`）均无覆盖。这属于 R1 同一类「只有真实路径才会暴露」的缺陷面。我手工代跑了一次（`/tmp/engacc/probe.py` P4）：`args=('https://zcode.z.ai/api/v1/zcode-plan','jwt-p4','mid-p4') kwargs={'proxy':''}` → **构造正确、无 TypeError**，结论是「未覆盖」而非「有 bug」。建议加一条不联网用例：把 `ZCodeClaimClient` 换成记录型 stub，断言构造参数与 `_plan_endpoint` 的读取来源。

**M-8 · `POST /admin/api/zcode/bench` 服务端零测试**（`api/admin.py:394-423`）：仓库里没有任何请求打过它；客户端侧还被 `**kw` 宽松假遮蔽（§3 表）。行为我已实测正确（§4-E），但两处该修：① 补一条 ASGI 用例（真实 `ResourceManager` 下断言 `status=cooldown` / `last_error` / `benched` 数）；② 非 JSON 请求体现在会 500 抛栈（`await request.json()` 未兜），改成 400。

**M-9 · `PlanLock` 在生产里等于空转，却被 R4 当作修正项交付**：唯一持有者是 `Scheduler`（`main.py:98` 只建一个），`loop()` 串行 `await self._tick(run)`（`runner.py:377-383`）→ 同进程永不重叠；CLI `mgw zcode claim`（`cli_zcode.py:224`）与管理端点**都不取 plan 锁**。于是「跨进程 plan 互斥」没有第二个竞争者，`test_plan_lock_is_cross_process_too`（`test_v2_ops.py:436`）测的是**机制**而不是接线。要么给管理端加「立即执行一轮」并走 `_tick`（让锁有竞争者），要么在文档里把这一层写清为「当前只防同进程重入，实际屏障是账号级锁」。

**M-10 · R3 声称的三触发点之①「启动刷新」是条件化的**：`main.py:109-110` 的 `refresh_quotas(runtime)` 位于 `_maybe_start_ops` 内、在两个早退之后（`:84-85` 无账号 / `:93-94` `interval<=0 且无 cron`）。因此**关掉运营调度或没账号时启动刷新不执行**，额度全为 `None`（= 不管控），只剩管理端点那一次。与 §17「不新建独立定时器」不矛盾，但 R3 的表述（「启动 + tick 末尾 + 管理端点」）比实际强。建议把 `refresh_quotas(runtime)` 提到 `Runtime.__init__`/startup 钩子里无条件跑一次（一次 4 MiB 尾读，代价可接受），或在文档写清条件。

### 🔵 轻微（8）

- **m-1 文档用例数与实际不符**：`test_v2_servable.py` 声明 12 实为 **11**；`test_int_v2_servable.py` 声明 6 实为 **7**（`--collect-only` 逐条列名核对）。总数抵消，但一张逐行对账的表里错两个数，会连带削弱其余 8 行的可信度。
- **m-2 `pick_and_acquire` 的「预留失败换下一个候选」分支在 amount=1 时不可达**：`available()` 已含 `has_quota()`（`resources.py:76`），同一同步段内 `reserve_quota(amount=1)` 的判据与之严格互补 → `resources.py:196` 注释「选中即耗尽（同一 tick 内已被并发占满）」描述的是不可能事件（只有 amount>1 才可能）。代码留着无害（面向 amount），但注释按"防住的场景"写会误导下一轮验收。
- **m-3 上轮 m1/m2 未修且本轮只字未提**：`api/admin.py:353 _zcode_quota_of(runtime, ...)` 的 `runtime` 形参仍未使用（函数体 `:361` 只用了 `zq/zstore`）；`api/admin.py:330` 的端点 docstring 仍宣称「客户端日志 → **该账号旧快照 → 联网兜底**」，两级都不存在（`quota.py:225` 直接 `ok=False`）。铁律 5 要求未处理项显式挂账，不能只列本轮清单。
- **m-4 `ops_failed_unread` 仍无上限**：`bump_failed_counter`（`runner.py:315-323`）每 tick 累加，清零出口只有 CLI `_ack_failures`（`cli_zcode.py:266`）和顶栏红点点击（`main.js:108-116`）。无人开界面、不跑 CLI 时，凭据缺失的账号会让计数每 60s +1（上轮 M5 建议的「最近 N 分钟失败数」未采纳，也未挂账）。
- **m-5 §17「适配器不直接持 httpx client」仍有偏离**：`adapters/anthropic_out.py:461` 在 `fingerprint=False` 时自建 `httpx.AsyncClient`，与 `auth.build_client`（`auth.py:80`）并行存在两份。未列入 §5.2 偏离清单。
- **m-6 上轮遗留死代码/重复**（详见 §1 表）：`save_config`（`config/loader.py:57`）零调用而 `api/admin.py:507-515` 复制了一份原子写（少 `os.fsync`、临时文件命名口径不同）；`wrap_httpx_error`/`retryable_hint`（`core/errors.py:130/63`）零调用而两个适配器内联同一转换 5 处；另有 `openai_out.list_models`、`Bucket.reset_note`、`dataroot.AccountInfo`、`crypto.roundtrip_ok`、`OpReport.all_normal`。这些与 R7 消掉「第三份 Bearer/UA 构造」用的是同一条理由。
- **m-7 `/v1/models` 语义变了但周边口径没跟上**：`web/static/js/pages/apiaccess.js:89` 的端点说明仍写「仅返回**已启用**的系统模型」；`api/admin.py:143` 概览的模型计数按 `enabled` 统计（与 `servable_models` 不同源）→ 界面两处数字与 `/v1/models` 实际长度可不一致。有 ③ 类横幅解释隐藏（`main.py:250-262`），**不是静默**，所以只算文案/口径欠账。
- **m-8 已核查非缺陷**：`pick_and_acquire` 与 `try` 之间的理论泄漏窗口不可达（`stats/events.py:65-66` 是 `put_nowait`，`switch_ring` 是 maxlen=200 的 deque）；`tests/integration/*` 的并发用例经 MUT-B 证明有效；`Cooldown` 的 `left_ms/active` 用 `time.monotonic()*1000` 与 `until_ms` 同源自洽（不受系统时钟调整影响）。

---

## 7. 行为变更的影响面（blast radius）

| 变更 | 依赖旧语义的地方 | 判定 |
|---|---|---|
| **`/v1/models` 只下发可服务模型**（`openai_compat.py:53-58`，BUG-1/Q28-②） | ① `api/admin.py:143` 概览模型计数仍是 `enabled` 口径 → 与下发数不一致（m-7）；② `apiaccess.js:89` 文案未更新（m-7）；③ 集成侧 `test_int_model_switch.py:43-72`（INT-39 轮询 /v1/models 断言启用/禁用可见性）配的都是**有映射**的模型，故未受影响——全量 537 绿佐证；④ `anthropic.py` 无 /v1/models 路由 → 该面无需同步；⑤ **路径 A 同步做了**（`cli_setup.py:33/96`）并打印跳过数，这是本轮做对的地方（漏它等于没修） | 无回归；文案/计数两处欠账 |
| **运营调度不再 t=0 触发**（`runner.py:377-383`，顺带修 #1） | 额度「启动刷新」被这条变更间接影响：`refresh_quotas` 只在 `_maybe_start_ops` 里被调，早退时不执行（M-10）；`test_scheduler_waits_one_period_before_first_tick` 守住新行为；`_hourly_aggregation`/`_reload_watcher` 与之无关 | 变更方向正确（避免重启风暴打上游），但把「启动刷额度」绑上了 ops 开关 |
| **`resource_ids_of_account()` 优先 `runtime.config`**（`quota.py:373-389`，R3 顺带修） | 两处生产调用点（`:257/:398`）都显式传 `runtime.config`；`config=None` 的文件回退分支**在生产已无人使用**（只剩注释里那句"仅在无 config 时才回退"）；测试 fake 签名已同步（`lambda acc, cfg=None`）；`_FakeRuntime` 的假 resources 没有 `account` 属性，靠顶替该函数才不炸（§3 表） | 无回归；回退分支近乎死码（可保留为防御） |
| 附：**冷却中/额度 0 的模型不隐藏**（`resources.py:88-105`）与 §5.3「不做清单」一致，没有把临时态做成界面消失 | ✅ 有对应用例（`test_v2_servable.py::test_cooldown_does_not_hide_model`、`test_int_v2_servable.py::test_cooldown_model_stays_published`） | 判定正确 |

---

## 8. 与 §19 / §20 的对照（只列本轮复核触及的）

| 判据行 | 文档口径 | 我的判定 |
|---|---|---|
| M5-3 并发不超发 | 已交付 + 反证 | **部分达成**：单状态达成（真实并发用例 + MUT-B 可红）；同账号多状态超发（S-1）；流式一条无护栏（M-1） |
| M4-4 熔断回写 → 转发绕开 | 已交付（R1/R2） | **达成**（我端到端实测 §4-E）；但 §17 的「状态落盘 + 10s 节流」在生产不存在（S-2）、「全局」口径未落实（M-6） |
| M5-1 双层互斥 / 只领一次 | 已交付（R4） | **机制达成、默认部署下条件成立**；6 个静默失效条件（M-2）；plan 层实为空转（M-9） |
| M5-1 无住宅代理不影响转发 | 已交付（R6d） | **达成**，`test_int_v2_ops_isolation.py` 的 gather 套 gather 是真并发，且用生产 `zcode_claim.claim`（只顶替 HTTP 边界）——这是本轮质量最好的一个用例 |
| M5-0 import 冲突退出码 4 且不写盘 | 已交付（R6b） | **达成**（CLI 层，含三个选项文案 + 目录未落 + `list_accounts()` 断言） |
| M4-2 两账号互不覆盖 / 主目录三件未写 | 已交付（R6a） | **达成**；且 `MGW_ZCODE_HOME` 重定向到 tmp（`test_v2_zcode.py:365-390`），**我复核过：不碰真实 `~/.zcode`** |
| M3-2 PRD 回填 | 已交付（R5） | 达成（PRD v1.15 已含 Q28 四项与 camelCase 回填；本轮之前从未动 PRD 的指控属实） |
| M5-2 额度聚合、不做对外端点 | 达成 | ✅ `test_quota_is_not_exposed_on_v1` 守住 404 |
| §20 不做清单 | 守住 | ✅ 复核未见违例（无 Device Registry / 无热切换 / 无 L-B·L-C 界面 / 无 GUI 自动化 / 无对外额度端点 / 无按模型拆调度参数） |

---

## 9. 诚实声明（本报告自身的证据边界）

1. **以下结论有实跑证据**：537 / 9+9 / 18+18；test_v2_ops 双跑与合并/倒序；三组反证（(a) 10 failed、(b) 4 failed、(c) 537 passed 即流式无护栏）；`/tmp/engacc/probe.py` 的 4 组复现（0 字节锁被抢、同进程跨实例抢锁、同账号双状态超发、amount 泄漏）与 `probe2.py` 的 bench 端点 + 流式三条（成功 / 中途断 / 首帧前错）；锁目录随 cwd 解析差异；`client_factory=None` 构造参数实录。脚本全在 `/tmp/engacc/`，未入库。
2. **未验证 / 无法验证**：① 开工基线「462 passed」——工作树无该快照，无法回溯；② §19 的 T1–T10 与文档 §四 N1–N4（真实凭据 / 联网 / 真实客户端 / 住宅代理），本轮同样**没有**任何真实上游调用（本机 `data/upstream/zcode/accounts` 不存在，未接入任何 ZCode 账号，运营链路实际处于休眠）；③ 「零回归」我只能证明**当前 537 全绿**，不能证明相对 462 无回归（测试集合变了，回归判据本身不可自动验证）；④ 3012 真实触发、`enc:v1` username 口径、`curl_cffi` 过 WAF 与 async SSE、`setting.json` 重定向、额度真实量纲 —— 全部未验证；⑤ 我没有跑过真实双进程「同时领取」的完整场景（受 ② 阻塞），M-2/S-1 的结论来自同机制的进程内/子进程级复现，**属机制级证据，不属生产现场证据**。
3. **未做的事**：没有修改仓库任何源码（三处临时反证均已按 MD5 还原）；唯一新增文件是本报告；没有动 `~/.zcode`、`~/.workbuddy*`；`ui_verify_v2_visible.py` 自带临时配置与随机端口，未连接运行中的 8300 网关。
4. **对文档的措辞纪律**：本轮 R1–R7/BUG-1/BUG-2 的**大部分内容是真的**，且可复现；我给的「不通过」针对的是 S-1（判据本体在常见配置下不成立）与 S-2（结论口径超出证据）两条，以及 §2 指出的「护栏抓不到它被指望抓的东西」——不是「造假」。铁律 2 的口径是「无证据即写未验证」，本报告对 §19 各行凡未实测的一律照抄文档的「未验证」标记，未替它们补绿。

---

## 10. 放行条件（建议清单，按成本排序）

1. S-1 额度按账号桶（或保守切分）+ 一条「同账号 2 映射 · 额度 1 · 并发」端到端用例。
2. S-2 二选一：接 `CooldownManager`（落盘 + 节流）或按 §19 口径降级为「本期未做」并同步 §17 与本证据文档；同时把 AST 护栏升级为可达性版本（§2 末）。
3. M-1 流式结算两条用例（成功 / 中途断），可直接从本报告 §4-E 的实跑输出转写。
4. M-4 配置解析统一（`load_config` 认 `MG_CONFIG` 或 `admin_post`/`_plan_endpoint` 显式取 `--config`），`admin_post` 返回 None 时在 CLI 出声。
5. M-2 锁目录绝对化 + 不可写降级出声 + 0 字节锁判为持有 + `_HELD_BY_US` 键加目录（④⑤⑦ 三条一并）。
6. M-6 / M-9 / M-10 三项口径与文档对账（要么补实现，要么进 §5 偏离清单并请用户确认）。
7. m-1~m-7 归入下轮一并清账；上轮 m1/m2/m4 未处理项在文档里显式挂账（铁律 5）。
