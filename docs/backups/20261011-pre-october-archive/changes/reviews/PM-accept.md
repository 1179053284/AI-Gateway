# PM 实现验收报告 · tech-design v2.0 增量（§12–§21 / M3–M5）

> 角色：资深产品经理（**实现验收**，非设计评审）
> 验收对象：`docs/specs/tech-design.md` v2.0 §12–§21（含 §19 交付判据）· `docs/specs/prd.md` v1.14 Q25/Q26/Q27 · 工作树中的 M3–M5 实现与测试
> 方法：只读核查；复跑 `pytest`（437 passed 复现）；逐条对照 §19 判据 / §20 不做清单 / Q25-Q27
> 日期：2026-09-26

---

## 1. 验收结论

**有条件通过（Conditional Pass）**

- **做对的部分很多且经得起复跑**：M3-0/M3-1/M3-2(能力位本体)/M3-3/M3-4/M3-5、M4-1、M4-2(三条硬约束)、M5-2、§21 四处出口，均有实现落点 + 可复现测试证据，`437 passed` 与 `16/16` 实测复现无误。
- **但不能无条件通过**：有 **3 项 §19 判据"只写了代码、未达成判据"或"完全未实现"**，且证据文档对其中两项做了**静默省略/偏高描述**（详见 §4）。这些不是"文档瑕疵"，是**交付物与判据不符**。

**放行条件（建议）**：
1. 修 S1（熔断/互斥接线）或明确降级判据并把 §19 判据改写为"手工待实测"；
2. 补/删 S2（M5-3）：要么实现，要么在 §19 与证据文档中显式标注"未做"（不能静默省略）；
3. 修 S3（`gateway.zcode.proxy` 落点）——当前文案把用户指向一个**不存在的配置键**；
4. 补 M4（PRD Q25-①/②/⑥ 回填）与 M3（方言表重载接线）后即可全通过。

---

## 2. §19 交付判据逐条核对表

| 判据 | 实现落点 `文件:行号` | 测试证据 | 结论 |
|---|---|---|---|
| **M3-0** `mgw --help` 退出码 0 | `pyproject.toml:25-26`、`model_gateway/cli.py:63` | `tests/unit/test_v2_cli.py:45`（`test_help_exits_zero`）、`test_v2_cli.py:38`（`[project.scripts]` 存在）；本地实测 4 个子命令 `--help` 退出码均 0 | ✅ |
| **M3-1** 零映射告警进 `/admin/api/overview` `warnings[]`（非仅日志） | `model_gateway/main.py:173-212`（`config_warnings`）、`api/admin.py:164-167` | `tests/integration/test_int_v2_capabilities.py:183/192/207/221` | ✅ |
| **M3-1** 两类告警措辞不同 | `main.py:184-211`（kind=`model_without_resource` / `resource_without_model`） | `test_int_v2_capabilities.py:231` | ✅ |
| **M3-1** 带 `custom:` 前缀的 model 可解析 | `enums/matcher.py:273-292`（`strip_model_prefix` 在 `resolve_request_model` 内） | `test_int_v2_capabilities.py:133/147/160` | ✅ |
| **M3-2** `/v1/models` 键集合含 7 能力位字段 | `api/openai_compat.py:37-61`、`core/capabilities.py:19-49` | `test_int_v2_capabilities.py:46`（`test_models_adds_seven_capability_fields`）、原 6 字段不动 `:34` | ✅ |
| **M3-2** PRD Q25-② 字段名回填（snake→camel、`effort_levels`→`caps.thinkingLevelMap`） | — | **无**：`docs/specs/prd.md:570` 与 `:721` 仍为 `max_input_tokens`/`supports_tool_call`/`effort_levels`；全仓 prd 无 `camelCase`/`maxInputTokens` 命中 | ❌ |
| **M3-3** 方言表落盘可断言 | `core/dialects.py:131-152`（原子写）、`cli_probe.py:127` | `tests/unit/test_v2_capabilities.py:165/196` | ✅ |
| **M3-3** 注入假序列后 S1/S2/S3 可确定性验证 | `probe.py:101-148`（`call: CallFn` 可注入） | `tests/unit/test_v2_probe.py:64/75/84/94/103/121/130` | ✅ |
| **M3-3**（§13.4）探测后**显式重载**方言表 | `main.py:165-171`（`reload_dialects` 存在） | **无调用点**（全仓仅定义）；`cli_probe.py` 只 `table.save()` | ❌ |
| **M3-4** `thinkingLevelMap` 7 键齐全、不支持为 `null` | `core/dialects.py:33-50`、`core/capabilities.py:52-68` | `test_int_v2_capabilities.py:94/106`、`test_v2_capabilities.py:81/94` | ✅ |
| **M3-5** 文件格式/合并/原子写可断言 | `setup_tools.py:74-209` | `tests/unit/test_v2_setup.py:72/82/92/102/110/118/128/144/151` | ✅ |
| **M4-1** 经 Anthropic 上游完成一次 chat | `adapters/anthropic_out.py:443-517`、`adapters/__init__.py:20-33`、`main.py:143-152` | `tests/integration/test_int_v2_anthropic.py:118`（真实假上游 ASGI）、`:136/156/172/186/208` | ✅ |
| **M4-2** 设备冲突**拒绝**而非静默重生成 | `upstream/zcode/store.py:142-158`、`dataroot.py:119-135` | `tests/unit/test_v2_zcode.py:202/216/227` | ✅ |
| **M4-2** 两账号 credentials/telemetry 互不覆盖 | 结构成立（`store._commit:184-193` 写入各自 `v2_dir_of`） | **无专门用例**（仅单账号 `test_v2_zcode.py:281`） | ⚠️ |
| **M4-2** 主 `~/.zcode/v2` 三件未被写入 | 结构成立（仅 `oauth.read_credentials:45` 读取，无写入） | **无断言** | ⚠️ |
| **M4-3** 双通道鉴权 + 三级降级 + TLS 指纹 | `upstream/zcode/auth.py:53-138`（`build_headers`/`degradation_chain`/`build_client`） | **全模块无生产调用点**（仅单测/无集成） | ⚠️（判据本身标注"手工/待实测"，但代码未接线） |
| **M4-4** 3012 熔断 / 额度耗尽**回写 `ResourceState.status`，转发路径自动绕开** | `upstream/zcode/quota.py:284-301`（`apply_to_resource`） | **无生产调用点**；仅 `tests/unit/test_v2_zcode_quota.py:245/258/267` 单测该函数本身 | ❌ |
| **M5-0** CLI 子命令 `login/import/list/claim` | `cli.py:43-58`、`cli_zcode.py:16-111` | `test_v2_cli.py:70`；`import` 冲突退出码 4（`cli_zcode.py:86`）**无 CLI 级用例** | ⚠️ |
| **M5-0** `import` 设备冲突返回非 0 且不写盘 | `cli_zcode.py:77-88`（返回 4） | "不写盘"由 `test_v2_zcode.py:213` 覆盖；**退出码 4 未测** | ⚠️ |
| **M5-1** 假上游注入 1003/1005/网络错 → 四类结果正确 | `ops/runner.py:83-102`、`ops/builtin/zcode_claim.py:40-52` | `tests/unit/test_v2_ops.py:41/51/70/89` | ✅ |
| **M5-1** 并发触发**只领一次**（双层互斥生效） | `runner.py:41-76,183` | `test_v2_ops.py:181`（**显式注入共享 `locks`**）—— 生产两入口均不传 locks | ❌（生产未生效） |
| **M5-1** 无住宅代理时降级 `failed` 且**模型转发不受影响** | `claim.py:199-205`、`ops/builtin/zcode_claim.py:78-83` | 仅 `test_v2_zcode_claim.py:123`（客户端层报错）；**"模型转发不受影响"的并发断言缺失** | ⚠️ |
| **M5-1** `failed` 可从 `/admin/api/status` 读到 | `main.py:75-78`（`bump_failed_counter`）、`api/admin.py:119-120` | `test_v2_ops.py:239`（计数器）+ `test_int_v2_zcode_admin.py:150`（端点恒 0） | ✅ |
| **M5-2** 额度聚合端点 `GET /admin/api/zcode/quota` | `api/admin.py:325-372` | `test_int_v2_zcode_admin.py:76/89/107/123` | ✅ |
| **M5-2** 不做对外端点 | `admin.py:325`（仅 admin 路由） | `test_int_v2_zcode_admin.py:138`（`/v1/*` 均 404） | ✅ |
| **M5-3** 额度预扣（事后快照→事前预留）不超发 | **无实现** | **无测试**；全仓 `预扣|reserve|超发` 零命中 | ❌ |

> **§19 统计**：✅ 14 项 · ⚠️ 7 项 · ❌ 5 项（M3-2 回填、M3-3 重载、M4-4 接线、M5-1 互斥接线、M5-3）。

---

## 3. PRD Q25 / Q26 / Q27 覆盖核对表

### Q25（配置三层 / 能力位 / 探测 / setup）

| 条目 | 实现落点 | 结论 |
|---|---|---|
| Q25-① 配置三层，`SystemModel.caps_overrides` | `config/schemas.py:168-170`、`core/capabilities.py:61-67` | ✅（字段已加，YAML 可改、无界面，符合 §14.1 裁决）；⚠️ PRD `prd.md:567` 仍写"UI 仅新增高级·能力覆盖"，未回填 |
| Q25-② `/v1/models` 补能力位 | `api/openai_compat.py:37-61` | ✅（以 **camelCase** 实现，含 `caps.thinkingLevelMap`；这是对 PRD 字面的**有意修正**，正确）；❌ PRD 未回填 |
| Q25-③ 7 档开放序 + 规范外透传 | `core/dialects.py:22`、`probe.py:166-170` | ✅（`ultra` 等原样保留；`test_v2_capabilities.py:132`、`test_v2_probe.py:111/121`） |
| Q25-④ 两层降级（工具 clamp / 网关只降不升，不叠加） | `core/dialects.py:53-80` | ⚠️ **仅函数存在，未接入任何请求路径**；且实现含"向上取最近"（`:76-79`）与"只降不升"字面矛盾；docstring 提到的 `already_clamped` 参数不存在 |
| Q25-⑤ 探测优先 + **必须含 S2** | `probe.py:101-148`、`cli_probe.py:54-133` | ✅（S2 单锚点 `none→0`，假方言丢弃）；❌ 探测结果**不重载**（§13.4） |
| Q25-⑥ 账号存储四表（products/accounts/credentials/runtime_state） | **未做** | ❌ 字面未做，但**这是 Q27-⑤ 用户决策明确推翻**（tech-design §14.2）→ 以最新决策为准**实现正确**；❌ 但 PRD `prd.md:582` 仍写四表、未回填 |
| Q25-⑦ 入站剥离 `custom:`/`custom-local:` | `enums/matcher.py:266-292` | ✅ |
| Q25-⑧ 零映射启动告警（两类） | `main.py:173-212` + `admin.py:164-167` + `dashboard.js:11,70-81` | ✅ |
| Q25-⑨ `mgw setup` 按 `dataFolderName` 解析 + 处理 env | `setup_tools.py:49-71` | ✅（无 `productName` 子串判断；`test_v2_setup.py:25/33/47/56`） |
| Q25-⑩ 不做清单（不拆调度 / 不做 L-B·L-C 界面 / 不做 GUI 自动化 / 不代登录） | 见 §5.2 | ✅ |

### Q26（设备身份 / 批量运营）

| 条目 | 实现落点 | 结论 |
|---|---|---|
| Q26-① 每账号虚拟设备、全局互异、导入复用、冲突拒绝 | `upstream/zcode/dataroot.py`、`store.py:118-162` | ✅（三条硬约束全测）；⚠️ `ensure_device_id`（`dataroot.py:103`）本身不查重，"生成→查唯一性"落在另一个函数 `generate_unique_device_id:152`（UUID4 下实际风险极低） |
| Q26-② 指纹持久化 + 轮换代次 | `dataroot.py:103-116`（永不重算） | ✅ 持久化；❌ 轮换代次（D12）未做 —— 与 §20 #18 / Q26-⑤ 一致（延后） |
| Q26-③ 批量/单账号操作 + 四类结果 + 幂等按 code | `ops/runner.py:83-102`、`ops/base.py:23-69` | ✅ 四类结果、业务码优先；⚠️ `AccountOperation`（name/supported_products/execute）未形式化，仅函数+模块常量；⚠️ **空跑 N=0→inactive 未实现** |
| Q26-④ 与核心调度解耦（独立 `ops/`，不进 scheduler/Resource） | `ops/runner.py:15-16`（不 import scheduler/errors，已核） | ✅ |
| Q26-⑤ 排期（D9–D11 做 / D12–D15 延后） | — | ⚠️ D14/D15（批量执行器/首批 operation）已做 —— 由 Q27-④ 要求，与 §20 #18 字面冲突（**设计自相矛盾，需裁决**） |

### Q27（ZCode 接入决策）

| 条目 | 实现落点 | 结论 |
|---|---|---|
| Q27-① 合规四项（私有端点/指纹/验证码/设备虚拟化） | `auth.py:116-129`、`claim.py`、`dataroot.py` | ⚠️ 结构就位但**未接线**：`build_client` 无调用点；验证码求解器未实现（仅可注入钩子） |
| Q27-② 免费额度双通道 + 三级降级链 | `auth.py:53-90` | ⚠️ 已写但**无生产调用点**；免费额度双通道读取未接线 |
| Q27-③ 方案先行、实测随实施（9 项待实测） | 证据文档 §四列 11 项 | ✅ 诚实标注 |
| Q27-④ 三段式 + 16 字段事件 + 幂等码 + 批量执行器（cron+双层互斥+抖动+隔离+四类结果） | `claim.py:131-238`、`ops/runner.py` | ✅ 三段式/16 字段（`test_v2_zcode_claim.py`）/幂等码/抖动/隔离；❌ **双层互斥未接线**；⚠️ cron 用固定 60s tick（`cron_matches` 无调用点） |
| Q27-⑤ 设备身份初期独立 + **补跨账号唯一性校验** | `dataroot.py:119-162` | ✅（不建统一表 + `check_device_id_unique`） |
| Q27-⑥ 整根隔离（`ZCODE_DATA_BASE_DIR` + 三件套 + `--device-id`） | `dataroot.py:37-98,231-238` | ✅ |
| Q27-⑦ `anthropic_out` 空壳补齐（P0） | `adapters/anthropic_out.py`（579 行） | ✅ |
| Q27-⑧ 不做免重启切换 | 未做 | ✅ |
| Q27-⑨ 不做清单 | 见 §5.2 | ✅ |

---

## 4. 问题清单

### 🔴 严重

**S1 · M4-4 判据"熔断回写 → 转发路径绕开"未真正达成（只写了代码）**
- 问题：`apply_to_resource`（`model_gateway/upstream/zcode/quota.py:284`）与 `CooldownManager`（`quota.py:222`）**全仓无任何生产调用点**，只在 `tests/unit/test_v2_zcode_quota.py:245/258/267` 被单测。即 3012 熔断状态**永远不会进入运行系统**，`ResourceState.status` 也**永远不会被回写** → §17 所述"熔断形同虚设"的原始缺陷**原样存在**。
- 证据：`grep apply_to_resource|CooldownManager` 在 `model_gateway/` 内零命中（仅 quota.py 定义处）。
- 建议：在额度/领取路径捕获 3012 → 调用 `apply_to_resource(runtime, [...])`；或若本期不接线，把 §19 M4-4 判据改写为"手工待实测"并在证据文档标注。

**S2 · §19 M5-3「额度预扣」完全未实现，且证据文档静默省略**
- 问题：`tech-design.md:1394` 把 M5-3 列为交付项（判据"并发单测断言不超发"），但代码中**无任何预扣/预留实现**，**无任何测试**；`E2E-20260926-v2-implementation.md` 的 §2.2 判据表（`:55-67`）**未列 M5-3 行**。
- 证据：全仓 `预扣|预留|reserve|超发|quota_hold` 在 `model_gateway/` 与 `tests/` 零命中。
- 建议：要么实现，要么在 §19 判据表与证据文档**显式写"未做/延后"**——不能静默跳过。

**S3 · §16.5 用户侧落点缺失，报错文案把用户指向不存在的配置键**
- 问题：`claim.py:203-204` 的提示让用户"在 config.yaml 的 `gateway.zcode.proxy` 填入住宅代理地址"，但该键在 `config/schemas.py`（`GatewayConfig` `:46-66` 无 `zcode`）与 `config.example.yaml` 中**均不存在**，`MGW_ZCODE_PROXY` 环境变量全仓零命中。Pydantic 默认 `extra="ignore"` → 用户照做会被**静默忽略**，问题不解决。
- 证据：`grep zcode|proxy model_gateway/config/schemas.py` → 无；`grep MGW_ZCODE_PROXY model_gateway/` → 无。
- 建议：补 `gateway.zcode.proxy` schema 字段并真正读取，或改文案指向实际生效的配置项。

### 🟡 中等

**M1 · M5-1「双层互斥·防 CLI/管理端点与 cron 并发双领」在生产未生效**
- 问题：`runner.py:183` `locks = locks or AccountLocks()` —— 每次调用**新建**锁集合；生产两个入口（`main.py:76` 的 cron `_run`、`cli_zcode.py:95` 的 `_claim`）**都不传 `locks`** → CLI 与 cron 各持一把锁，**跨入口双领无防护**。测试 `test_v2_ops.py:181` 通过是因为它**显式注入了共享 `locks`**（`:194`），生产从不这么做。同理 `Scheduler` 的 `PlanLock`（`runner.py:63-76`）只约束同一实例的 tick，CLI 完全绕过。
- 证据：`main.py:76`、`cli_zcode.py:95`（无 locks 参数）；`test_v2_ops.py:183-205`。
- 建议：把 `AccountLocks`/`PlanLock` 提升为进程级单例（如挂在 `runtime` 上）并在两入口注入。

**M2 · §16.4/§16.6「N=0 → `inactive` + 输出『无账号参与』」未实现，且被测试固化**
- 问题：`runner.py:176-178` 对 `accounts==[]` **直接返回空 report**（`inactive` 为空）；`cli_zcode.py:109-110` 对空 report 打印"**全部正常，无需处理**"——正是设计点名的"0 账号被误报成成功"这一静默路径。`test_v2_ops.py:101-108` 甚至把偏离写成了断言（`assert report.inactive == []`，注释"也不是 inactive"）。
- 证据：`runner.py:176-178`、`cli_zcode.py:96-110`、`test_v2_ops.py:101-108`；对照 `tech-design.md:1149`、`:1210`。
- 建议：N=0 时记 `inactive` 并输出"无账号参与"，同步修正该测试。

**M3 · §13.4「`mgw probe` 写完文件后显式触发一次重载」未落地**
- 问题：`Runtime.reload_dialects`（`main.py:165`）**无任何调用点**；`cli_probe.py:127` 只 `table.save()`。→ 探测完成后，**运行中的网关仍用旧方言表**（设计原文点名的"探测完了不生效"）。
- 证据：`grep reload_dialects` → 仅 `main.py:165/171` 定义处。
- 建议：probe 完成后经管理端点触发 `reload_dialects()`（或明确要求重启）。

**M4 · M3-2 第二判据「PRD Q25-② 字段名回填」未做；§14.1 要求的 Q25-① 回填也未做**
- 问题：`prd.md:570`、`:721` 仍为 `max_input_tokens`/`supports_tool_call`/`effort_levels`；`prd.md:567` 仍写"UI 仅新增…高级·能力覆盖"（§14.1 裁决为"保留字段、砍掉界面"）。
- 证据：`grep maxInputTokens|supportsToolCall|camelCase docs/specs/prd.md` → 零命中。
- 建议：回填 PRD 三处（Q25-①②⑥ 的字段名与 UI 口径）。

**M5 · 过度设计 / 死代码（约 400 行无生产调用点）** —— 详见 §5.1。

**M6 · 证据文档描述与工作树不符（范围混入）**
- 问题：`E2E-20260926-v2-implementation.md:23` 称 `base.css` 改动 = "顶栏红点"，但 `git diff` 实测 `base.css` **555 行插入**，主体是 **v2.12 视觉重构**（圆角体系、列表左对齐、tab 换行）+ ops-dot（`:1112-1126`）；`index.html`/`main.js` 另含"模板预览/需求预演"导航与 `templates.js`（**文件 mtime 09-23，早于本次 M3–M5 的 09-5x**）。
- 证据：`git diff --stat`（base.css 555/`29` 个 hunk）；`stat` 时间戳；`templates.js` 为 09-23 既有文件。
- 建议：若属并行任务，请隔离工作树；若属本次，证据文档需如实登记。**此条不影响 M3–M5 代码本身**。

### ⚪ 轻微

- **L1** 证据文档 `:44` 记 `test_v2_anthropic.py` 36 例，实测 **34**（其余文件计数与总数 238/437 准确）。
- **L2** M5-0 判据"`import` 冲突返回非 0 退出码"**无 CLI 级用例**（`cli_zcode.py:86` 的 `return 4` 未被覆盖；store 层覆盖了"不写盘"）。
- **L3** M4-2 两条判据（"两账号各自 credentials/telemetry 互不覆盖"、"主 `~/.zcode/v2` 三件未被写入"）**无断言**（结构成立）。
- **L4** §16.6/§17 声明首批 **2** 个 operation（`zcode_claim` / `query_balance`），仅实现 **1** 个（`ops/builtin/zcode_claim.py`）；`query_balance` 以 M5-2 管理端点形式存在，未作为 ops operation。
- **L5** Q26-③ 的 `AccountOperation` 未形式化（仅函数 + 模块常量 `SUPPORTED_PRODUCTS`）—— 与 §20 #7/#14 一致，但与 Q26-③ 字面有差。
- **L6** 证据文档 §四 #11 称验证码求解"**代码已就位**"，实际仅 `captcha_solver` 可注入钩子（`claim.py:157-168,199-205`），**无 Playwright 求解实现**；措辞偏高。
- **L7** `degrade_effort`（`dialects.py:53`）无调用点 + 与 §13.2"只降不升"矛盾（`:76-79` 向上取）+ docstring 引用不存在的 `already_clamped` 参数；`test_v2_capabilities.py:148` 固化了向上行为。
- **L8** `ensure_device_id`（`dataroot.py:103`）不做唯一性校验（§15.1 硬约束 1 的查重落在 `generate_unique_device_id:152`）。
- **L9** `build_env` docstring 称"在继承环境上追加，不清空"（`dataroot.py:85`），实际返回全新 dict（不含 `os.environ`）。
- **L10** `resolve_target_dir` 的 `customUserDataDir` 分支不可达（`setup_tools.py:68-69`），因两产品的 `custom_user_data_dir` 均为空（`:37-46`）。

---

## 5. 过度设计专项 + §20 不做清单

### 5.1 过度设计审查

**结论：整体克制尚可，但存在约 400 行"无生产调用点、仅为单测存在"的脚手架。**

| 死代码 | 位置 | 行数 | 说明 |
|---|---|---|---|
| `auth.py` 全模块 | `upstream/zcode/auth.py:53-138` | ~85 | `build_headers`/`degradation_chain`/`classify_status`/`build_client`/`fingerprint_available` **无生产调用点** |
| `apply_to_resource` + `CooldownManager` | `upstream/zcode/quota.py:222-301` | ~80 | M4-4 判据要求接线，实际未接（见 S1） |
| `launch_command`/`kill_zcode`/`is_zcode_running`/`build_env`/`build_args` | `upstream/zcode/dataroot.py:83-238` | ~90 | 无 `mgw zcode start` 入口消费 |
| `cron_matches` + `_field_matches` | `ops/runner.py:275-318` | ~45 | 自研 5 段 cron 解析器，生产用固定 60s tick |
| `degrade_effort` | `core/dialects.py:53-80` | ~28 | 无调用点（见 L7） |
| `is_retryable` | `ops/runner.py:105-109` | ~5 | 生产用字符串式 `_looks_retryable` |

- **与"解决问题是否匹配"**：新增 ~1884 行（upstream 1391 + ops 493）中，**约 1/5 未被生产路径引用**。其中 `auth.py`、`cron_matches` 属"为将来场景预先造轮子"，正是用户点名要避免的形态；`apply_to_resource`/`CooldownManager` 则是"写了但没接线"，属**判据未达成**（已在 S1 记）。
- **应当肯定**：`ops/` 未 import `core/scheduler`/`errors`（`runner.py:15-16`）、不做统一 Device Registry、`caps_overrides` 只走 YAML 不建界面、setup 不做"静默改写工具配置"——这些**主动克制**与 §20 一致。
- **建议**：删掉无调用点的 `cron_matches`/`degrade_effort`/`is_retryable`，或补上调用点；`auth.py`/`dataroot` 启动相关函数若本期不接线，移出交付面并在证据文档标注"为 T5a/T5b 预留"。

### 5.2 §20 不做清单（20 条）遵守情况

| # | 不做项 | 代码核查 | 遵守 |
|---|---|---|---|
| 1 | 统一 Device Registry / 四表账号存储 | `store.py` 为 per-account 目录，无统一表 | ✅ |
| 2 | 免重启热切换 | 无实现 | ✅ |
| 3 | 每模型手填能力位 | 能力位来自内置目录（`capabilities.py:41-49`） | ✅ |
| 4 | 网关内建完整档位映射引擎 | 仅 `degrade_effort` 小函数（且未接线） | ✅ |
| 5 | 启动时全量探测 | `cli_probe.py:67-76` 仅探"无记录"模型，按需 | ✅ |
| 6 | 并发批量运营 | `runner.py:184-200` 串行 + 抖动 | ✅ |
| 7 | 通用"运营 DSL" | 硬编码 `zcode_claim` | ✅ |
| 8 | ZCode 首期不做设备画像随机化 | 无 persona 随机化 | ✅ |
| 9 | Z.ai 邮箱注册 | `oauth.login:79-88` 直接返回"需浏览器完成" | ✅ |
| 10 | 内置接码平台/临时邮箱 | 无 | ✅ |
| 11 | 自己下载替换 ZCode 客户端 | 无 | ✅ |
| 12 | 首期前端 UI（ZCode 账号管理页） | 无账号管理页（模板预览为 09-23 既有，非本次） | ✅ |
| 13 | 能力位版本协商 | 无 | ✅ |
| 14 | 预先抽象公共层 | 无 `upstream/base.py`/Protocol | ✅ |
| 15 | L-B/L-C 用户录入界面 | `caps_overrides` 仅 YAML | ✅ |
| 16 | GUI 自动化 | `oauth.py:3-4,79-88` 明确不做 | ✅ |
| 17 | 不代用户登录工具 | 同上 | ✅ |
| 18 | 设备轮换代次（D12）与 D12–D15 延后项 | 未做 D12；**做了 D14/D15（批量执行器/首批 operation）** | ⚠️ 见下 |
| 19 | 首期不做验证码求解（备选，二选一） | 未实现求解器（选了 §16.5 路线但只留钩子） | ✅ |
| 20 | 不做按模型的调度参数拆分 | 未动全局调度参数 | ✅ |

> **关于 #18**：`§20 #18` 字面把 D12–D15 列为延后项，但 **§19 M5-1 / §16 / Q27-④ 明确要求本期做"批量执行器 + 首批 operation"**。实现按 M5-1 做了（`ops/runner.py`、`ops/builtin/zcode_claim.py`）。**这是设计内部自相矛盾，不是代码违规**——按时间更晚、更具体的 Q27-④ 判断，实现方向正确。**建议**把 §20 #18 收窄为"仅 D12/D13（轮换代次/操作抽象）延后"，消除歧义。
>
> **§20 总结：未发现"做了说不做的事"的真实违反。**

---

## 6. 明确无问题的部分（做对了）

1. **M3-0 CLI 骨架**：`pyproject.toml:25-26` 新增 `[project.scripts]`，`mgw --help`/`probe|setup|zcode --help` 退出码均 0（本地实测）。
2. **M3-2 能力位本体**：`/v1/models` 原 6 字段不动 + 追加 8 字段；字段名 **camelCase 正确**（对 PRD snake_case 的有意修正，方向正确）；自定义模型不崩、目录缺属性输出 `null` 不臆造（`capabilities.py:30-49`）。
3. **M3-4**：`thinkingLevelMap` **7 键齐全、不支持显式 `null`**；`caps_overrides` 优先级最高；`thinkingFormat` 取自方言表而非 `EnumEntry`（`capabilities.py:60-68`）。
4. **M3-5 setup**：`dataFolderName` 解析（**未用被禁的 `productName` 子串判断**）、env 优先、合并/备份/原子写/读回/回滚/dry-run/路径确认，测试覆盖完整（`test_v2_setup.py` 14 例）。
5. **M3-3 探测**：三步 S1/S2/S3，**S2 单锚点 `none→0`**，假方言丢弃，规范外档位保留，`call_fn` 可注入 → 满足"可确定性验证"（`test_v2_probe.py` 11 例）。
6. **M3-1**：零映射告警**双通道**（`overview.warnings[]` + 启动日志），两类措辞不同；入站前缀剥离生效。
7. **M4-1 anthropic_out**：与 `openai_out` 同形 4 方法；**usage 在适配器内映射**；**2xx 非 JSON/SSE → `status_code=None`**（与 `errors.classify` 的 `RETRYABLE` 约定一致，`errors.py:100-101`）；流式事件翻译；真实假上游完成 chat/流式/故障切换（集成 13 例）。
8. **M4-2 设备身份三条硬约束**：复用 / 拒绝 / `--regenerate` / `--reuse` 全测；账号名白名单防目录穿越。
9. **M5-2**：额度聚合端点 + **不做对外端点**（`/v1/*` 404）。
10. **§21 四处出口**：总览横幅、顶栏红点、CLI 三选项、setup 写前确认 —— `scripts/ui_verify_v2_visible.py` **16/16 实测复现通过**。
11. **测试基线**：`pytest -q` 复跑 **437 passed**（与证据一致），新增 **238** 条，零回归。

---

## 7. 复跑记录（只读）

```
$ .venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pm-verify
437 passed, 368 warnings in 58.23s

$ .venv/bin/python scripts/ui_verify_v2_visible.py
实测 16 项，通过 16 项，失败 0 项

$ .venv/bin/python -m model_gateway.cli --help            # exit=0
$ .venv/bin/python -m model_gateway.cli zcode --help      # exit=0
$ .venv/bin/python -m model_gateway.cli setup --help      # exit=0
$ .venv/bin/python -m model_gateway.cli probe --help      # exit=0

# 新增 v2 用例数（collect-only）：238（unit 201 + integration 37）
```
