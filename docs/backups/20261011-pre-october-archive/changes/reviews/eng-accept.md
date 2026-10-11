# 后端工程实现验收报告 · tech-design v2.0 增量（§12–§21 / M3–M5）

> 角色：资深后端研发工程师（Python / FastAPI / asyncio）—— **实现验收**（代码已写完，只挑问题）
> 验收对象：`docs/specs/tech-design.md` v2.0 §12–§21（含 §19 交付判据）· 工作树中的 M3–M5 实现与测试 · `docs/changes/e2e-records/E2E-20260926-v2-implementation.md`
> 方法：**只读**核查 + 逐符号 `grep` 找生产调用点 + 复跑测试/证据脚本
> 复现：`.venv/bin/python -m pytest -q` → **437 passed in 58.93s**（与证据文档一致）；`scripts/ui_verify_v2_visible.py` → **16/16 通过**（与证据文档一致）
> 日期：2026-09-26

---

## 1. 验收结论

**有条件通过 —— 当前状态不可交付；须修复 3 项严重问题后复验。**

- 做对的部分**确实经得起复跑**：M3-0/M3-1/M3-2/M3-3/M3-4/M3-5、M4-1、M4-2（三条硬约束）、M5-2、§21 四处出口，均有**生产调用点** + 可复现证据（见 §2 表与 §7）。
- **不能无条件通过**：有 3 项属于「**零件实现了 ≠ 系统能跑**」——
  ① 一条 §19 判据（M4-4）在证据文档里标 ✅，但**熔断回写全仓无调用点**，且该函数**签名与真实 `ResourceManager.bench` 不符，一旦接线即 `TypeError`**（§3 S1）；
  ② 空跑语义与方案**相反**，且被测试固化为「正确行为」（§3 S2）；
  ③ 报错文案把用户指向一个**不存在的配置键**，测试还把它断言为真（§3 S3）。
- 另有 **约 450 行生产死代码**（占新增 upstream+ops 约 1884 行的 ~24%），其中 `auth.py` 整层（双通道鉴权/三级降级/TLS 指纹）与 `dataroot.py` 的启动/进程控制族**零生产调用点**（§2、§6）。

---

## 2. 🔴 接线完整性核对表（新增能力 → 生产调用点）

> 方法：对每个新增公开符号 `grep -rn '<名字>' model_gateway/`；**只认 `model_gateway/` 内的调用**，`tests/`、`scripts/` 命中不算接线。

| # | 新增能力（符号） | 定义处 | 生产调用点 | 结论 |
|---|---|---|---|---|
| 1 | `quota.apply_to_resource` | `upstream/zcode/quota.py:284` | **无**（仅 `tests/unit/test_v2_zcode_quota.py:245/258/267`） | ❌ 死代码（且签名错误，见 S1） |
| 2 | `quota.CooldownManager` | `quota.py:222` | **无**（仅测试） | ❌ 死代码 |
| 3 | `quota.looks_like_risk_control` | `quota.py:308` | **无**（仅测试） | ❌ 死代码 |
| 4 | `quota.parse_log_tail` / `snapshot_from_log_record` | `quota.py:108/185` | `api/admin.py:365/367`（`_zcode_quota_of`） | ✅ 已接线 |
| 5 | `quota.normalize_remote` / `aggregate` | `quota.py:156/190` | `snapshot_from_log_record:187` / `admin.py:346` | ✅ 已接线 |
| 6 | `ops.runner.run_once` | `ops/runner.py:142` | `main.py:76`（cron `_run`）、`cli_zcode.py:95` | ✅ 已接线 |
| 7 | `ops.runner.write_report` / `bump_failed_counter` | `runner.py:204/222` | `main.py:77/78` | ✅ 已接线 |
| 8 | `ops.runner.AccountLocks` | `runner.py:41` | 仅 `run_once:183` **内部新建**（两入口都不传 `locks=`） | ⚠️ 半接线：每次调用新实例 → 跨调用互斥失效（M1） |
| 9 | `ops.runner.PlanLock` | `runner.py:63` | `runner.py:243`（`Scheduler.__init__`）→ `main.py:73` 构造 | ✅ 已接线（同实例 tick 间有效） |
| 10 | `ops.runner.Scheduler` | `runner.py:235` | `main.py:73` | ✅ 已接线 |
| 11 | `ops.runner.classify_http_error` | `runner.py:83` | **无**（仅测试）；分类实由 `ops/builtin/zcode_claim.py:40 classify` 另写一份 | ❌ 死代码（重复实现） |
| 12 | `ops.runner.is_retryable` | `runner.py:105` | **无**（仅测试）；重试判定实由 `runner.py:136 _looks_retryable` 字符串前缀另写一份 | ❌ 死代码（重复实现） |
| 13 | `ops.runner.cron_matches` (+`_field_matches`) | `runner.py:275/290` | **无**（仅测试）；`Scheduler` 用固定 `interval_s=60` 轮询（`runner.py:256-259`） | ❌ 死代码（未使用的 cron 框架） |
| 14 | `ops.builtin.zcode_claim.claim` | `ops/builtin/zcode_claim.py:55` | `runner.py:181`（`run_once` 缺省注入） | ✅ 已接线 |
| 15 | `zcode.auth.degradation_chain` | `upstream/zcode/auth.py:74` | **无** | ❌ 死代码（§17 三级降级链未接入转发路径） |
| 16 | `zcode.auth.classify_status` | `auth.py:93` | **无** | ❌ 死代码 |
| 17 | `zcode.auth.build_client` / `fingerprint_available` | `auth.py:116/132` | **无**；`anthropic_out.py:450` **自建** `httpx.AsyncClient`，不经此模块 | ❌ 死代码（§17「TLS 指纹由 auth 统一注入」未落地） |
| 18 | `zcode.auth.build_headers` / `looks_like_jwt` | `auth.py:53/45` | 仅 `degradation_chain` 内部（链条本身无调用点） | ❌ 死代码 |
| 19 | `zcode.auth.Credentials` | `auth.py:36` | `oauth.py:76` | ✅ 已接线 |
| 20 | `zcode.oauth.login` | `oauth.py:79` | `cli_zcode.py:53` | ✅ 已接线（但恒 `ok=False`，见 m3） |
| 21 | `zcode.oauth.refresh` | `oauth.py:91` | **无** | ❌ 死代码（§16.3 教训 3 的「续期」无落点） |
| 22 | `zcode.oauth.read_credentials` / `build_credentials` | `oauth.py:45/64` | **无**；`ops/builtin/zcode_claim.py:21 _credentials_of` 绕过它们直读 JSON | ❌ 死代码 |
| 23 | `zcode.store.list_accounts` / `import_account` / `accounts_root` | `store.py:55/118/49` | `main.py:65`、`cli_zcode.py:40/68`、`ops/runner.py:164`、`admin.py:338/355` | ✅ 已接线 |
| 24 | `zcode.store.delete_account` | `store.py:203` | **无** | ❌ 死代码 |
| 25 | `zcode.dataroot` 设备身份族（`check_device_id_unique`/`find_account_by_device_id`/`generate_unique_device_id`/`sync_device_mid_to_telemetry`） | `dataroot.py:119/138/152/165` | `store.py:143/146/148/161/182` | ✅ 已接线 |
| 26 | `zcode.dataroot.ensure_device_id` / `build_env` / `build_args` / `launch_command` / `is_zcode_running` / `kill_zcode` | `dataroot.py:103/83/96/231/182/196` | **无**（`ensure_device_id` 仅被 `launch_command:236` 调用，而后者无调用点；`is_zcode_running` 仅被 `kill_zcode` 调用） | ❌ 死代码（整根隔离的「启动客户端」链路未提供任何 CLI 出口） |
| 27 | `zcode.claim.report_activation` / `build_activation_event` / `event_body_is_complete` | `claim.py:222/131/236` | **无**（仅测试）；`zcode_claim.claim` 只调 `preview`+`claim` | ❌ 死代码 → 签到语义不完整（M4） |
| 28 | `zcode.claim.ZCodeClaimClient` / `pick_plan` / `parse_claim` | `claim.py:154/99/116` | `ops/builtin/zcode_claim.py:67/197/218` | ✅ 已接线 |
| 29 | `core.capabilities.build_model_caps` / `build_caps_block` | `core/capabilities.py:19/52` | `api/openai_compat.py:58/59`、`cli_setup.py:32/46` | ✅ 已接线 |
| 30 | `core.dialects.DialectTable` / `build_level_map` | `core/dialects.py:101/33` | `main.py:102`、`capabilities.py:63`、`cli_probe.py:65`、`cli_setup.py:85` | ✅ 已接线 |
| 31 | `core.dialects.degrade_effort` | `dialects.py:53` | **无**（仅测试） | ❌ 死代码 → §13.2「网关层兜底（只降不升）」未落请求路径 |
| 32 | `Runtime.reload_dialects` | `main.py:165` | **无**（仅定义） | ❌ 死代码 → §13.4「探测完不生效」（M3） |
| 33 | `adapters.build_adapter` | `adapters/__init__.py:20` | `main.py:148`、`admin.py:304` | ✅ 已接线（全仓**无**直接 `OpenAIOutAdapter(` 生产构造） |
| 34 | `adapters.anthropic_out` 4 方法 | `anthropic_out.py:490/520/562/455` | `main.py:148`→`runtime.adapters`→`scheduler` duck typing | ✅ 已接线 |
| 35 | `probe.probe_model` | `probe.py:101` | `cli_probe.py:113` ← `cli.py:78` ← `[project.scripts] mgw` | ✅ CLI 可达 |
| 36 | `setup_tools.write_models_json` | `setup_tools.py:127` | `cli_setup.py:94/111` ← `cli.py:81` | ✅ CLI 可达 |
| 37 | `main._maybe_start_ops` | `main.py:58` | `main.py:315`（`_startup`） | ✅ 已接线 |
| 38 | §21 出口：`overview.warnings[]` / `status.ops_failed_unread` / 前端横幅 / 红点 | `main.py:173`、`admin.py:168/121`、`dashboard.js:71`、`main.js:94`、`index.html:109`、`base.css:1112` | 均已接线并实测（16/16） | ✅ 已接线 |

**死代码清单（生产零调用点）：** `quota.{apply_to_resource, CooldownManager, looks_like_risk_control}`、`auth.{degradation_chain, classify_status, build_client, fingerprint_available, build_headers, looks_like_jwt}`、`runner.{classify_http_error, is_retryable, cron_matches, _field_matches}`、`dialects.degrade_effort`、`Runtime.reload_dialects`、`claim.{report_activation, build_activation_event, event_body_is_complete}`、`dataroot.{ensure_device_id, build_env, build_args, launch_command, is_zcode_running, kill_zcode, _suppress}`、`store.delete_account`、`oauth.{refresh, read_credentials, build_credentials}`。**合计约 450 行。**

---

## 3. 问题清单

### 🔴 严重

**S1 · M4-4「熔断回写 → 转发路径绕开」未达成；且 `apply_to_resource` 与真实 `bench` 签名不符，接线即崩**
- 问题：`quota.apply_to_resource`（`quota.py:284-301`）与 `CooldownManager`（`quota.py:222-281`）在 `model_gateway/` 内**零生产调用点**（仅 `tests/unit/test_v2_zcode_quota.py:245/258/267/161/173`）。→ 3012 风控/额度耗尽**永远不会回写** `ResourceState.status`，模型转发路径**仍会选中**刚被熔断的账号——§17 原文点名的"熔断形同虚设"缺陷**原样存在**。而 `E2E-20260926-v2-implementation.md:64` 把该判据标为 ✅。
- **更严重**：`quota.py:299` 调用 `mgr.bench(state)`（单参），而真实 `ResourceManager.bench` 签名是 `def bench(self, state, seconds)`（`core/resources.py:151`，第 2 个必填位置参数）→ **一旦接线立即 `TypeError: bench() missing 1 required positional argument: 'seconds'`**。该错误被单测掩盖：`test_v2_zcode_quota.py:232` 的 `_FakeResources.bench(self, state)` 只接受 1 个参数。
- 证据：`quota.py:299` vs `resources.py:151`；`_FakeResources` 定义 `test_v2_zcode_quota.py:227-234`。
- 建议：改为 `mgr.bench(state, seconds=<30min 秒数>)`（并让 `seconds` 取自 `COOLDOWN_MS`），在 3012/额度耗尽捕获点（额度查询或 `ops` tick 内）真正调用；或在 §19 把 M4-4 降级为「手工待实测」并**同步修正证据文档的 ✅**。

**S2 · 空跑语义与方案相反（`N=0` 未记 `inactive`），且测试把它固化为「正确」**
- 问题：§16.4 / §16.6 明确「无账号参与（`N=0`）→ 记 **`inactive`** 并输出「无账号参与」（**不得报 `success`**）」。实现 `runner.py:176-178` 对 `accounts==[]` **直接返回空 `OpReport`**（`inactive` 为空、`success` 为空）；`cli_zcode.py:109-110` 对空 report 打印 **「全部正常，无需处理」**并退出码 0 —— 正是设计点名的"0 账号被误报成成功"这一静默路径。该路径**用户可达**：无账号时执行 `mgw zcode claim` 即触发（`cli_zcode.py:95` → `runner.py:162-164`）。
- 证据：`runner.py:176-178`、`cli_zcode.py:96-110`；对照 `tech-design.md:1149`、`:1210`。
- **测试固化错误行为**：`tests/unit/test_v2_ops.py:101-108` 断言 `assert report.inactive == []`，注释写"也不是 inactive（无人参与 ≠ 无资格）"——与方案字面直接冲突。
- 建议：`N=0` 时 `report.inactive` 记入参与账号（或新增空跑标记）并在 CLI 打印「无账号参与」；同步修正该测试与代码注释（`runner.py:176` 的注释本身写的就是正确语义，代码却未实现）。

**S3 · 配置项真实性：报错文案指向**不存在**的配置键，且回退环境变量从未被读取**
- 问题：`claim.py:203-204` 提示用户「请在 config.yaml 的 `gateway.zcode.proxy` 填入住宅代理地址」。但 `config/schemas.py` 的 `GatewayConfig`（`:46-65`）**无 `zcode` 字段**，全仓无 `gateway.zcode` / `zcode.proxy` 的 schema 定义；`MGW_ZCODE_PROXY` 环境变量**全仓零命中**（§16.5 承诺的"无则回退环境变量 `MGW_ZCODE_PROXY`"未实现）。Pydantic v2 默认 `extra="ignore"`（`schemas.py` 未设 `extra="forbid"`）→ 用户照做会被**静默忽略**，问题不解决。
- 证据：`claim.py:204`；`schemas.py:46-65`（无 zcode）；`MGW_ZCODE_PROXY` 全仓仅出现在 `docs/specs/tech-design.md:1174`；测试把假键断言为真：`test_v2_zcode_claim.py:132` `assert "gateway.zcode.proxy" in msg`。
- 建议：在 `GatewayConfig` 增 `zcode: ZcodeConfig = ...`（含 `proxy: str = ""`）并真正读取（claim 路径注入 `captcha_solver`），或改文案指向**实际生效**的配置项（环境变量/参数）。参见 `docs/changes/reviews/PM-accept.md:117-120`（同一问题，尚未修复）。

### 🟡 中等

**M1 · 账号级互斥（§16.4 第二层）在生产路径失效**
- 问题：`run_once` 内 `locks = locks or AccountLocks()`（`runner.py:183`）**每次调用新建**；两个生产入口 `main.py:76`（cron）与 `cli_zcode.py:95`（手动）**都不传 `locks=`** → 同进程内两次并发 `run_once` 各持一把锁，跨调用互斥不存在。且 CLI 是**独立进程**，`threading.Lock` 本就无法跨进程 → 设计所要求的"防 **CLI**/管理端点手动与 cron 并发双领"用该机制**根本无法达成**。
- 证据：`runner.py:183`、`main.py:76`、`cli_zcode.py:95`；测试通过是因为**显式注入了共享锁** `test_v2_ops.py:183-205`（`locks=locks`），生产从不如此。
- 建议：把锁提升为进程级单例（挂 `runtime`）并在两入口注入；跨进程（CLI vs cron）改用文件锁（复用既有 `core/instance_lock.py` 范式）或明确把 §16.4 第二层的防护范围收窄为"同进程内"。

**M2 · 方言表重载缺失（`reload_dialects` 无调用点）**
- 问题：`Runtime.reload_dialects`（`main.py:165-171`）无任何调用点；`cli_probe.py:127` 只 `table.save()`。→ 探测完成后**运行中的网关仍用旧方言表**（`main.py:100-102` 启动时只加载一次），即 §13.4 原文点名的"探测完了不生效"。
- 证据：`main.py:165`（仅定义）、`cli_probe.py:127`；`/v1/models` 读的是 `runtime.dialects`（`openai_compat.py:59`）。
- 建议：probe 完成后经管理端点触发 `reload_dialects()`（或 CLI 明确要求重启并在输出里提示）。

**M3 · 签到语义不完整：`report_activation` 未接入**
- 问题：§16.4 明确「所谓签到 = `billing/claim`（`period=daily`）**+** `event/report` 上报 `app_daily_active` **两件事合成**」。但 `ops/builtin/zcode_claim.py:55-93` 只调 `client.preview()` 与 `client.claim(plan_id)`，**从不调用** `client.report_activation(...)`（`claim.py:222`）→ 激活事件不会上报，`report_activation`/`build_activation_event`/`event_body_is_complete` 全为死代码。
- 证据：`zcode_claim.py:70-88`；`claim.py:222-229`（无调用点）。
- 建议：在 `claim` 成功后调用 `report_activation(user_id=...)`（`user_id` 取自凭据），或明确本期不做并在 §19 标注。

**M4 · `auth.py` 整层（双通道鉴权 / 三级降级 / TLS 指纹）未接入转发路径**
- 问题：§17 要求「TLS 指纹客户端**由 `auth.py` 统一提供并注入给 `anthropic_out`**（适配器不直接持 httpx client）」。实现中 `degradation_chain`/`classify_status`/`build_client`/`fingerprint_available`/`build_headers`/`looks_like_jwt` **全部只有测试调用**；`anthropic_out.py:450` **自建** `httpx.AsyncClient`，与 `auth.build_client` 无关；转发时仅把资源的 `api_key` 作为 `x-api-key` 发出（`anthropic_out.py:459-464`），**双通道与三级降级没有任何落点**。M4-3 判据本身是「手工待实测」，但因**零接线**，即使手工也无法触发该机制。
- 证据：`auth.py:45/53/74/93/116/132`（零生产调用点）；`anthropic_out.py:446-464`。
- 建议：明确 M4-3 本期为「未接线/未实现」，把 §19 与证据文档口径改为"未做"，避免"写了代码=已交付"的误读。

**M5 · `ops_failed_unread` 只增不减，顶栏红点永不熄灭且无上限增长**
- 问题：`bump_failed_counter`（`runner.py:222-230`）**只做累加**；全仓**无任何清零点**（`grep 'ops_failed_unread\s*='` 仅 `runner.py:229`）。`main.py:105` 注释称"用户在 CLI 查看后清零"，但 `cli_zcode._claim` 并未清零。→ 一旦出现一次失败，红点**永久常亮**；且若有账号但凭据缺失，cron 每 60s 记一次 `failed`（`zcode_claim.py:64` 返回 `failed`）→ 计数**无上限累积**。
- 证据：`runner.py:229`、`admin.py:121`、`main.js:100`、`main.py:105`（注释与实现不符）。
- 建议：提供 ack 出口（如 `mgw zcode claim` 成功后清零，或管理端点 `POST /admin/api/ops/ack`），并把累加改为"最近 N 分钟内失败数"。

### 🔵 轻微

**m1 · `admin.py:_zcode_quota_of` 的 `runtime` 形参未使用**
- 证据：`admin.py:351`（定义）、`:352-371`（函数体全程未引用 `runtime`）。建议删除该参数。

**m2 · 额度三通道只实现了 1 档，"旧快照兜底"注释与实现不符**
- 问题：§17 数据源优先级为「客户端日志 → 该账号旧快照 → 联网兜底」。`_zcode_quota_of`（`admin.py:358-371`）只实现"日志"，注释写"② 旧快照兜底"但实际返回空 `QuotaSnapshot(ok=False)`（`:370`）——**无旧快照存储、无联网兜底**。
- 证据：`admin.py:369-371`。建议把注释改为"无可用数据"，或明确本期只做日志通道。

**m3 · `mgw zcode login` 恒失败（stub）**
- 问题：`oauth.login`（`oauth.py:79-88`）无论 provider 都返回 `ok=False`；`cli_zcode.py:53-56` 因此恒退出码 1。与 §20 #16「不做 GUI 自动化」一致，但 §17 的「OAuth 双流程」实际未实现（import 是唯一可用路径）。
- 证据：`oauth.py:86-88`、`cli_zcode.py:53-56`。建议在 `--help` 与输出中明示"login 暂不可用，请用 import"。

**m4 · 重试判定依赖自由文本前缀匹配，结构化 `is_retryable` 被弃用**
- 问题：`_run_one` 用 `_looks_retryable(r.detail)`（`runner.py:136-139`，字符串 `startswith("network:")` / 含 `"http 5"`）判断是否退避；而 `OpResult`（`ops/base.py:23-29`）**不携带 HTTP 状态**，`is_retryable(status, code)`（`runner.py:105`）因此无处可用。§16.4「仅网络类 / 5xx 可重试」只能靠字符串近似（`zcode_claim.py:88` 打了 `"network:"` 前缀才凑效）。
- 证据：`runner.py:129/136-139`、`ops/base.py:23-29`。建议给 `OpResult` 加 `status`/`code` 字段，用结构化判定替换字符串嗅探，并删除重复的 `classify_http_error`。

---

## 4. 配置项真实性核对

| 配置项 / 环境变量 | 设计要求 | 实现真相 | 结论 |
|---|---|---|---|
| `gateway.zcode.proxy` | §16.5：`config.yaml` 住宅代理地址 | `schemas.py:46-65` 的 `GatewayConfig` **无 `zcode`**；全仓无该键 schema | ❌ **不存在**（S3） |
| `MGW_ZCODE_PROXY` | §16.5：无配置时回退该环境变量 | 全仓**零命中**（仅出现在设计文档 `tech-design.md:1174`） | ❌ **从未被读取** |
| Pydantic 对未知键的行为 | — | `schemas.py` 未设 `extra="forbid"`，Pydantic v2 默认 `extra="ignore"` → 用户填 `gateway.zcode.proxy` 被**静默丢弃** | ⚠️ 静默忽略（不报错，问题不解决） |
| `MGW_ZCODE_ACCOUNTS` | §20 账号根目录覆盖 | `store.py:51` `os.environ.get("MGW_ZCODE_ACCOUNTS")` | ✅ 真实读取（集成测试 `test_int_v2_zcode_admin.py:61` 用它隔离） |
| `MGW_ZCODE_HOME` | 客户端数据目录覆盖 | `oauth.py:34` `os.environ.get("MGW_ZCODE_HOME")` | ✅ 真实读取 |
| `ZCODE_CREDENTIAL_SECRET` | `enc:v1` 密钥 | `crypto.py:89` `os.environ.get("ZCODE_CREDENTIAL_SECRET")` | ✅ 真实读取 |
| `ZCODE_DATA_BASE_DIR` / `ZCODE_DESKTOP_{USER_DATA,SESSION_DATA,HOME}_DIR` | §15.3 整根隔离 | `dataroot.py:38-41` 定义常量，`build_env:87-92` 组装 | ⚠️ 常量与组装存在，但 `build_env` **无生产调用点**（m/死代码） |
| `caps_overrides` | §14.1 唯一净新增配置字段 | `schemas.py:172` `Field(default_factory=dict)`；`capabilities.py:61` 读取且优先级最高 | ✅ 真实存在且生效（`test_int_v2_capabilities.py:118`） |
| `WORKBUDDY_CONFIG_DIR` / `CODEBUDDY_CONFIG_DIR` | §12.4.1 目录解析最高优先 | `setup_tools.py:40/44` 声明，`resolve_target_dir:63-66` 读取 | ✅ 真实读取 |

---

## 5. 测试真实性核对

**总览**：`437 passed` 可复现（我实测 437 passed in 58.93s）；v2 新增用例 `pytest --collect-only` = **238 条**，与证据文档"新增 238 条"一致；`scripts/ui_verify_v2_visible.py` **16/16** 可复现。**数字无造假。**

**逐项核对（真实行为 vs 绕过生产路径）：**

| 测试 | 断言是否验证行为 | 是否绕过生产路径 | 备注 |
|---|---|---|---|
| `test_v2_ops.py:70 test_run_once_classifies_all_four_categories` | ✅ 真验证四类归位 | 否（走 `run_once`） | 注入假 `claim` 属正常单测手法 |
| `test_v2_ops.py:181 test_account_lock_prevents_double_claim` | ✅ 真验证互斥 | ⚠️ **是**：显式传 `locks=locks`（`:194`），而生产两入口**都不传** → 测试覆盖的路径生产不存在（M1） | 判据"并发只领一次"在**生产**未达成 |
| `test_v2_ops.py:101 test_empty_accounts_reports_inactive_not_success` | ❌ **断言错误行为**：`assert report.inactive == []`（`:107`） | 否 | 与 §16.4/§16.6 相反（S2） |
| `test_v2_zcode_quota.py:245/258/267 test_apply_to_resource_*` | ✅ 验证函数逻辑 | ⚠️ **是**：用 `_FakeRuntime`/`_FakeResources`（`:218-242`），其 `bench(self, state)` 只有 1 参 → **掩盖了与真实 `bench(state, seconds)` 的签名不符** | 判据 M4-4 在**集成系统**未达成（S1） |
| `test_v2_zcode_claim.py:123 test_missing_captcha_solver_raises_with_user_guidance` | ⚠️ 只验证报错**字符串** | 否 | 把**不存在的配置键**断言为真（`:132`，S3） |
| `test_v2_zcode_claim.py:70/82 test_activation_event_*` | ✅ 真验证 16 字段 | ⚠️ **是**：`build_activation_event` 无生产调用点 → 测的是死代码 | 签到事件不会上报（M3） |
| `test_v2_capabilities.py:134-155 degrade_effort` | ✅ 真验证降级语义 | ⚠️ **是**：`degrade_effort` 无生产调用点 → 测的是死代码 | §13.2 网关层兜底未接线 |
| `test_v2_zcode_quota.py:161-213 CooldownManager / looks_like_risk_control` | ✅ 真验证逻辑 | ⚠️ **是**：均无生产调用点 → 测的是死代码 | 熔断状态永不进入运行系统 |
| `test_int_v2_capabilities.py:46/94/106/118` | ✅ 真验证 `/v1/models` 8 字段 / 7 键 / `caps_overrides` | 否（真 HTTP 打 `/v1/models`） | 生产路径真实 |
| `test_int_v2_anthropic.py`（13 条，假 Anthropic ASGI） | ✅ 真走 `runtime.adapters` + scheduler | 否 | M4-1 判据成立 |
| `test_int_v2_zcode_admin.py:76/89/107/123/138/150` | ✅ 真 HTTP 打管理端点 | 否 | M5-2 判据成立 |
| `test_v2_cli.py`（17 条） | ✅ 验证 `--help`/`[project.scripts]`/确认交互 | 否 | — |

**结论**：无"测试通过但功能完全没接线"的**假绿**（关键判据 M3-2/M4-1/M5-2 走真实 HTTP）；但存在 **6 处"单测直接调函数、绕过生产路径"**，其中 `apply_to_resource`（S1）与 `AccountLocks`（M1）两处**恰好掩盖了生产缺陷**——这正是"零件实现了不等于系统能跑"的典型。

---

## 6. 过度设计专项

新增约 1884 行（upstream 1391 + ops 493），其中**约 450 行（~24%）为生产死代码**：

1. **为 1 个场景建通用框架**（用户点名要避免的）：
   - `runner.py:275-318 cron_matches` + `_field_matches`（44 行）：自研 5 段 cron 解析器，但 `Scheduler` 用固定 `interval_s=60` 轮询（`runner.py:256-259`）→ **整套 cron 框架零使用**。
   - `auth.py:74-138`（约 84 行）：为**尚不存在**的"双通道+三级降级+TLS 指纹"建了完整机制，但转发路径零接线（M4）。
2. **同一语义两份实现**：`runner.classify_http_error`（`runner.py:83-102`）与 `ops/builtin/zcode_claim.classify`（`zcode_claim.py:40-52`）重复；`runner.is_retryable`（`runner.py:105-109`）与 `runner._looks_retryable`（`runner.py:136-139`）重复 → 前者均死代码。
3. **`dataroot.py` 启动/进程控制族**（`launch_command`/`kill_zcode`/`is_zcode_running`/`build_env`/`build_args`/`ensure_device_id`/`_suppress`，约 79 行）：无任何 CLI 命令使用（`cli_zcode.py` 只有 list/login/import/claim）→ 死代码。
4. **`oauth.py`**：`refresh`（`oauth.py:91-111`）、`read_credentials`（`:45-61`）、`build_credentials`（`:64-76`）均无调用点；实际凭据读取由 `zcode_claim._credentials_of` 另行直读 JSON（`zcode_claim.py:21-33`）→ 重复且死。
5. 未使用形参：`capabilities.build_model_caps(..., dialects)`（`capabilities.py:19`，函数体未用）、`admin._zcode_quota_of(runtime, ...)`（`admin.py:351`）。

**反例（克制到位，值得肯定）**：§14.2「不建统一账号表」、§15.2「不做 `DeviceIdentity` Protocol / 不做 `upstream/base.py` 抽象」、§20「不做运营 DSL」——这些**确实没做**（`upstream/` 下只有 `zcode/` 一个产品目录，无 `base.py`；`ops/builtin/` 只有 `zcode_claim.py`）。

---

## 7. 明确无问题的部分（做对了）

1. **`build_adapter` 分发点完整**：生产仅 `main.py:148` 与 `admin.py:304` 两处构造适配器，**全仓无**直接 `OpenAIOutAdapter(` 生产调用；`main.py:144-146` 的复用判定（`base_url` + `protocol`）正确，两个适配器均 `base_url.rstrip("/")`（`openai_out.py:49`、`anthropic_out.py:449`）。
2. **`anthropic_out._url()` 对 `/v1` 的处理正确**：`endswith("/v1")` → `{base}/messages`，否则 `{base}/v1/messages`（`anthropic_out.py:466-474`），两种 base_url 形态都覆盖（`test_v2_anthropic.py:45/51`）。
3. **`images_generate` 的 `no_failover` 契约成立**：`UpstreamError` 支持 `no_failover`（`errors.py:54/60`），调度器识别（`scheduler.py:399/664`），与既有 `openai_out.py:87` 同口径。
4. **`_maybe_start_ops` 返回 `sched._task` 可靠**：`Scheduler.start` 内 `create_task` 同步赋值 `self._task`（`runner.py:261`），`getattr(sched,"_task",None)`（`main.py:83`）必得该 task；shutdown 的 `cancel()` + `suppress` 兜底（`main.py:325-328`）不会因取消抛异常。
5. **`cli_zcode._claim` 打印与 `runner` 返回一致**：直接使用 `run_once` 返回值（`cli_zcode.py:95-111`），`report.failed` 为 `(name, reason)` 元组（`ops/base.py:40`）与解包一致（`cli_zcode.py:107`）。
6. **`/v1/models` 确实读到方言表**：`openai_compat.py:59` → `capabilities.build_caps_block:66-67` → `runtime.dialects.thinking_format_of`（`main.py:102`）。
7. **能力位本体正确**：7 键齐全且不支持显式 `null`（`dialects.py:47`）、`caps_overrides` 优先级最高（`capabilities.py:61-63`）、`tool_call` 默认 `True` 的**有意偏离**已在代码注释（`matcher.py:36-41`）与证据文档 `:150` 双处显式标注 —— 属**披露充分的合理偏离**，不算问题。
8. **设备 ID 三硬约束落地正确**：导入路径冲突**默认拒绝**并给 3 选项 + 退出码 4（`cli_zcode.py:77-86`），`import_account` 冲突时不写盘（`store.py:155-158`）、`ensure_device_id` 生成一次不重算（`dataroot.py:111-116`）。
9. **`ops/` 硬边界遵守**：`ops/` 与 `ops/builtin/` **未** import `core.scheduler` / `core.errors`（仅 import `ops.base` 与 `upstream.zcode.*`），符合 §16.6。
10. **§21 四处用户可见出口真实接线**：`admin.py:168`（overview `warnings[]`）、`admin.py:121`（status `ops_failed_unread`）、`dashboard.js:71-75`（`.alert-warn` 横幅）、`index.html:109-111` + `main.js:94-100` + `base.css:1112`（红点），16/16 实测通过。
11. **`probe` / `setup` 经 CLI 真实可达**：`pyproject.toml:25-26` → `cli.py:78/81` → `cli_probe.run_probe` / `cli_setup.run_setup` → `probe.probe_model`（`cli_probe.py:113`）/ `setup_tools.write_models_json`（`cli_setup.py:111`）。
12. **证据文档数字可信**：`437 passed`、`16/16`、`238 条新增用例` 均可复现；未实测项（T1–T10、验证码/住宅代理）**诚实标注**（`E2E-20260926-v2-implementation.md:124-140`），未虚报。

---

## 8. 放行条件（建议）

1. **S1**：修 `quota.py:299` 的 `mgr.bench(state)` → `mgr.bench(state, seconds=COOLDOWN_MS/1000)`，并在 3012/额度耗尽捕获点真正调用 `apply_to_resource`；或把 §19 M4-4 与证据文档的 ✅ 改为「未接线 / 手工待实测」。
2. **S2**：`N=0` 记 `inactive` 并在 CLI 输出「无账号参与」；修正 `test_v2_ops.py:101-108`。
3. **S3**：补 `GatewayConfig.zcode.proxy` schema 并真正读取（或改文案指向生效配置），修正 `test_v2_zcode_claim.py:132`。
4. **M1–M5**：至少明确"本期未做"并在 §19 / 证据文档同步口径，避免"写了代码 = 已交付"。
5. **§6**：删除或接线约 450 行死代码（优先删 `cron_matches` 族与 `classify_http_error`/`is_retryable` 重复实现）。
