# M6 交付验收面板 · PM（产品 / 需求视角）· 独立评审

> 角色：PM 面板（独立评审，非实现方；**唯一写入 = 本文件**，且写在 /tmp 复制品内）
> 对象：M6 = Q29 落地（`docs/specs/prd.md` §9-Q29 v1.19 + `docs/specs/tech-design.md` §22）；台账 `docs/changes/e2e-records/E2E-20260930-M6-multi-product.md`
> 纪律执行：`cp -R` 主树 → `/tmp/mg-m6pm-main`（主树零改动，仅本报告）；`pytest --basetemp=/tmp/m6pm-$$ -p no:cacheprovider`；不碰 `data/` / `:8300` / 真实上游（全部假凭据 + 本地假上游 127.0.0.1:8393/8395）；变体实验在第二个复制品 `/tmp/m6pm-mut`
> **快照基线**：复制品建于 2026-09-30 03:57:23；对源码/README/台账逐文件 `cmp` 与主树**逐字节一致**（含 03:39–03:56 的 M6-6 收尾改动）；此后主树仅新增其他面板自己的报告产物（`m6-panel-eng-{a,b}.md`、`m6-panel-ix-*.png`），不影响本报告结论。
> 结论口径：只有「通过 / 不通过」+ 阻塞数，不写"有条件通过"

## 结论

**不通过 · 阻塞 2 条**（B-1 交付面「模型目录」零用户出口且未登记；B-2 台账两处宣称与磁盘不符）。
另记非阻塞 2 条（F-3 入口层「mgw 子命令」只覆盖 zcode；F-4 物化后 1s 窗口的配置覆盖面，代码已登记同族残留）。
测试基线（本次独立复跑，复制品）：**1422 collected / 1421 passed / 1 failed**，唯一失败 `tests/unit/test_v2_servable.py::test_ops_lock_dir_ignores_cwd` 经机理复核为**复制品双树伪红**（子进程 cwd=复制品 → 导入复制品；cwd=/tmp → 导入 venv editable 主树；实测两值 `…/mg-m6pm-main/data/ops-locks` vs `…/Model-Gateway/data/ops-locks`）→ 单树形态下即 1422/1422，与台账口径一致。
交付闸门判据：**Q29-① 范围、能力矩阵语义、14 类「未实测」诚实性、五个动作面出口**全部成立（逐条证据见下）；不通过仅因 B-1/B-2。

---

## 一、范围符合性（Q29-① 逐条）

### 1.1 在册 10 实例 / 排除项

| 项 | 要求 | 磁盘事实 | 判定 |
|---|---|---|---|
| 10 实例在册 | buddy/workbuddy/lobsterai/qoder/qodercn/trae/cline/loomy/raccoon/zcode | `model_gateway/accounts/registry.py:41-44` `PRODUCT_IDS` 10 项，逐项有 `ProductMeta`（`:58-241`） | ✅ |
| 排除 codearts | 华为云不接 | 全仓 `codearts` 只作**负例**：`tests/accounts/test_registry.py:104,119`；运行面 `registry.get()` → KeyError → 400，探针实测 `未登记的产品 'codearts'（在册：buddy/…/zcode）` | ✅ |
| 每产品薄模块 | `upstream/<product>/` | 10 目录齐；zcode 为既有实现（`registry.py:229-240` 注明"本轮接入统一管理面并补齐缺口"） | ✅ |
| 最小公共层 | `model_gateway/accounts/`（Q29-③） | `types/registry/store/device/login/net/materialize` 7 文件 | ✅ |
| 前端合规 | 逐条遵守 `frontend-spec`（Q29-④） | 新增「账号接入」页（`main.js` PAGE_META+路由、`index.html:42` 导航、`accounts.js`）；证据 = `m6-accounts-{light,dark,narrow,wizard-*}.png` + `m6-accounts-assertions.json`（55 项）；R3 独立 CDP 重跑 67 项；本次抽看浅色页与断言 JSON（A16a/b/c/e 能力钮、D3 启停、12px 节奏口径一致） | ✅ |

### 1.2 五个动作面 × 出口（逐面证据）

> 出口形态：API（`/admin/api/accounts*` 13 端点）、前端（「账号接入」页）、CLI（`mgw`）、文档（README）。**PM 探针** = 本次自建 `/tmp/m6pm-probe/probe.py`（30 项）+ `probe2.py`（6 项），真 uvicorn + 本地假上游，结果 `/tmp/m6pm-probe/probe{,2}-results.json`（全绿）。

| 动作面 | API（实测） | 前端 | CLI | 文档 | 判定 |
|---|---|---|---|---|---|
| **接入** | `login/start|poll|callback|alt`、`import`（`admin_accounts.py:384-536`）；探针 import buddy/loomy → 200 且凭据落 `data/upstream/<p>/accounts/<n>/` | 向导弹窗**六型**（R3 §2：device_code/external_link/local_callback/qr 图/qr 内容/sms 两段；W4b 证 local_callback 不轮询） | 仅 `mgw zcode login|import` | README 仅 zcode 段 | ✅（API/前端够用） |
| **管理** | 列表 + `{claim|refresh|probe|enable|disable|delete}`；探针 disable→`meta.json enabled=false`→视图 false→enable 复原 | 行内开关（D3 即落库）+ 能力驱动 4 钮 + 删除二次确认 | `mgw zcode list|remove` | README 未写该页 | ✅ |
| **切换** | 复用既有调度（账号→资源→同模型多资源优先序，§22.5-6） | 资源池设置（既有页） | — | README「切换续跑」段（通用） | ✅ **探针 2**：两 buddy 账号 → 同一系统模型，上游对 A 恒 500 → 命中序 `[FAKE-A, FAKE-A, FAKE-B]`，响应 `FROM-ACCOUNT-B` |
| **签到领取** | `POST …/claim`（四类出口）；探针 loomy → `success`，**真 HTTP** 到假上游 `/points/first-login`；停用后 → `inactive` 且**零上游请求** | 能力驱动按钮（`accounts.js:302-315`） | `mgw zcode claim`（`zcode_claim` 真别名，退出码契约不动） | README 退出码段 | ✅ |
| **模型转发** | `/v1/chat/completions`；探针 buddy 非流式+流式均 200；上游收到 `Bearer <账号目录凭据>`（配置 Key 不外发）、路径 `/v2/chat/completions`、`X-Product: CodeBuddy`（F3 修正后） | 资源弹窗映射（既有页） | — | README 统一入站段（通用） | ✅ |

**范围结论**：Q29-① 与五个动作面**逐条成立**；唯一缺口在 §22.0 交付面里的「模型目录」（见 B-1）。

---

## 二、能力矩阵抽查（3 产品 × 语义一致性）

| 产品 | `research/20 §3.1`（真源 = DSH `credits-capabilities.js:62-145`） | `registry.py` | `GET /admin/api/accounts/capabilities`（探针实测） | 前端行为（`accounts.js`） |
|---|---|---|---|---|
| **raccoon** | dailyCheckin **✗**（每日 300 分服务端按日自动发放，无可调端点）/ onboarding ✓ | `checkin=False`（`:205-223`） | `{'balance': True, 'checkin': False, 'onboarding': True, 'permanent_lock': False, 'refresh': True}` | `if (c.checkin)` 才渲染 claim（`:312-315`）→ **无签到钮** ✅（断言 JSON A16c：`['probe','refresh','delete']`） |
| **loomy** | dailyCheckin ✓ / onboarding **✓** / permanentLock **✓**；§2.6 `refreshTargets`：不可续期（只探测已过期） | `refresh=False, permanent_lock=True`（`:184-200`） | `{…, 'refresh': False}` | `else` 分支 → `off + disabled` + title「该产品不可续期：续期通道未登记」（`:302-311`）✅（A16b） |
| **buddy** | dailyCheckin ✓（幂等 = HTTP 400 + 业务码 10001）/ permanentLock **✓** | `checkin=True, permanent_lock=True`（`:62-74`） | `{'checkin': True, 'permanent_lock': True, 'refresh': True}` | 4 钮全可用 ✅（A16a） |

**「未登记 = 不渲染 / 不参与」**：
- 渲染：产品与行来自 `GET /admin/api/accounts`（服务端只枚举 `PRODUCT_IDS`）→ 未登记产品**无处出现**；按钮由 `Capabilities` 驱动（`:298-319`）。
- 参与：ops 参与方**从能力位推导**（`ops/builtin/product_claim.py:47-54` 按 `checkin`、`query_balance.py:42-44` 按 `balance`）；探针实测 `claim` 参与方恰 7 个（workbuddy/cline/raccoon 天然不在内）、`query_balance` 10 个；未登记产品请求 → 400。
- 边界诚实：`onboarding` 能力位为 ✓（loomy/raccoon）但**入口未接**，前端以 `ONBOARDING_ENDPOINT_READY=false` 不渲染（`accounts.js:84,316`）并自登记 —— 属"能力位已登记、端点未就绪"，未谎报 ✅

---

## 三、诚实性核证

| 面 | 要求 | 磁盘/实测事实 | 判定 |
|---|---|---|---|
| 14 类「未实测」未被吹成已完成 | §22.11 + 台账 | 逐项在注释/文档写作「未实测/未取证/待 D1」：U2 `main.py:212-215`、U3 `qoder/out.py:10-20`、U5 `zcode/captcha.py:17-18`、U9 `buddy/out.py:15-16`、U10 `cline/out.py:33-34`、U11 `raccoon/product.py:31`、U12 `loomy/out.py:29-30`、U13 `qoder/ask.py:41`、U14 `lobsterai/out.py:13`；`grep mark.skip/skipif/xfail tests/` **零命中** | ✅ |
| **D1 用户可见面标注** | 横幅/注释/文档 | **横幅实测**：`GET /admin/api/overview → warnings[kind=model_unservable_premise]` 文案含「**注意：zcode 直连前提未验证（D1），当前不代表 zcode 转发可用**」（`main.py:589-601` 同源；总览页 `dashboard.js:14,65` 渲染）；同时 zcode 模型被**排除出 `/v1/models`**（探针：`pm-zc-model` 不在 ids） | ✅ |
| **qoder 签名缝 fail-closed** | 不伪造签名/不静默降级 | `upstream/qoder/out.py:64` `SIGNER_FACTORY=None` → 当场可读错误；探针直调 `pm-qd-model` → **503**（非 200、非空回复），横幅点名「qoder 签名未注入（WASM/COSY）」 | ✅ |
| 台账/README 计数与事实 | 数字对得上 | ⚠️ README 双语 = **1421**（`README.md:11,178`、`README.zh-CN.md:11,169`，日期 2026-09-29），台账计数沿革写「终态 1422 …**README 同步 1422**」→ 与磁盘不符（复制品实测 collected=1422；1421 passed 的差额 = 双树伪红 1 项，**未在主树内跑全量**，按机理推定单树为 1422）；判据 `test_v2_readme_claims.py` 有 ≤20 容差 → 判据绿但"已同步"的话不实 | ⚠️ **B-2** |

---

## 四、交付纪律（Q29-⑤）可追溯性

| 项 | 台账声明 | 独立核证 | 判定 |
|---|---|---|---|
| 计数沿革 | 835→996→1221→1304→1371→**1422** | 终值：复制品 `--collect-only` = **1422**，实跑 1421 passed + 1 复制品伪红（机理已复核）→ 按机理推定单树 = 1422/1422，与声明一致（**未在主树内跑全量**）；历史值无盘上产物，属自述 | ✅（终值） |
| 每条修复带红证 | M6-6 表 12 行，行行「撤修复 → N failed」 | **抽样独立复现 2 条**（第二个复制品 `/tmp/m6pm-mut`，改前/改后均复跑）：① R1-F1 撤 `alt_call` 的 `_gate` → `test_alt_call_refuses_expired_session_and_persists_nothing` **RED**（复原 GREEN）；② R3-P-4 撤 CSRF 依赖（`admin.py` router 两处）→ **4 failed**（含 nothing-persisted / admin-router-also-guarded），复原 6 passed | ✅（抽样） |
| R-1…R-7 终态 | 各行 ✅ | 逐条落盘：R-1 时钟注入（`test_v2_circuit.py:249,423`）；R-3 `_IMPLEMENTED`+`_REFUSED_HOOKS`（`qoder/product.py:117,124`、`qodercn/product.py:116,123`）；R-5 `POLLABLE` 不含 local_callback（`accounts.js:54`）；R-6 `pending+detail` 原文展示 + qr 两分支（`:703-704,559-571`）；R-7 `ModelInfo` 未扩字段（仅注释登记缺口） | ✅ |
| §22.6 operation 收敛（R4-BL-3） | 已落地 | `ops/builtin/__init__.py`：`claim`（7 产品，能力位推导）/ `query_balance`（10）/ `zcode_claim`（`run` 与 claim **同一函数对象** = 真别名）；`PRE_CHECK_PRODUCTS` 单一事实源 `registry.py:56` | ✅ |
| R4「台账滞后 7 项」收口 | 已一次性回填 | 台账头注明回填时刻 + M6-3/4/5 已改 ✅ + R-1/R-2/R-4 标收口 | ✅（但引入 2 处新偏差 → B-2） |
| 卫生（R4-BL-5） | 「`.pytest-tmp-m65c` 已删并**纳入 `.gitignore`**；`:8419` 孤儿已终止」 | `.pytest-tmp-m65c/` 确已删；`:8419` 确无监听（本次 `lsof` 实测只剩 8300/8396/8397）；**但 `.gitignore` 无任何 `.pytest-tmp*` 规则** | ⚠️ **B-2** |

---

## 五、用户故事走查（3 条）

**① 添加 buddy 账号 → 出现在模型列表（假凭据）→ 能用。**
`POST /admin/api/accounts/import` → **自动物化**配置资源（`res-6bbe337a`：`vendor=CodeBuddy`、`base_url=https://copilot.tencent.com`、`account_ref=pm-buddy`、`enabled=true`）→ 热重载 **1.08s** 进内存快照 → 资源页保存映射（基址改本地假上游 + 系统模型 `pm-buddy-model`）→ `GET /v1/models` **含** `pm-buddy-model` → 非流式/流式调用均 200。
⚠️ 前提：**厂商模型 ID 要用户自己填**（§22.5-4 的既有手工映射流程）；产品的 `list_models` 钩子无出口（B-1）。

**② 对 loomy 账号点签到（假上游）→ 能用。**
`import loomy` → `POST …/loomy/pm-loomy/claim` → `category=success`、`detail=已触发每日赠送额度（消耗后不回补）…`；假上游**真收到** `POST /points/first-login` 且 `token` 头 = 账号凭据；停用后 claim → `inactive`（「账号已停用…运营执行跳过停用账号」）且**零上游请求**。

**③ 在「账号接入」页启停一个账号 → 能用。**
API 面：disable → `meta.json enabled=false` → 视图 false → enable → 恢复；前端面：R3 独立 CDP 重跑 D1/D1b/D1c（开关 → 视图重取 → 盘面核对；删除取消零落盘）+ 本次抽看截图与断言 JSON 一致。

---

## 六、发现

### B-1（阻塞）§22.0 交付面「模型目录」零用户出口，且未登记
- 事实：10 产品的 `list_models` 钩子**全部实现**（`upstream/*/product.py` 的 `_HOOKS["list_models"]`，逐个 `async def list_models` 有真实实现 + 单测，如 `tests/accounts/test_trae.py:597-675`）；但**生产消费者为零**：`grep -rn "list_models" model_gateway/ scripts/` 在 `upstream/` 外只命中 `api/openai_compat.py:39` 的**同名不同物**端点函数；CLI 无账号子命令、UI 无目录选择（`resources.js` 的「厂商模型 ID」是**纯手工输入**，无 datalist）。
- 反差佐证：账号页**自己就把这一层画成了标签**——`accounts.js:198` 渲染「模型目录来源：remote/static」，但页面/接口都没有任何地方能列出该目录的模型；系统模型页的目录选型（`models.js:16,135`）只连**内置四厂商目录**（`/admin/api/enums`，Q24），与产品账号目录无关。
- 违反：`tech-design.md:1520` 交付面明文列「**模型目录**与模型转发（账号→资源→系统模型）」；Q29-② 要求"能照抄的直接整合"。
- 同族前例与不对称：R1-F6 曾对同类条件（`quota` 钩子无通路）出具发现，修复轮**为 quota 补了 `query_balance` 出口**；`list_models` 未被同一标准处置，且 §22.11/台账 14 类「未实测」**未登记**此事。
- 最小处置（二选一）：① 接线（如账号视图/资源弹窗按账号列出可用厂商模型）；② 在 §22.11 + 台账正式登记为「未交付/未接线」并把 §22.0 的「模型目录」字样改准。

### B-2（阻塞）台账两处宣称与磁盘不符（R-2 同族复发）
1. 台账计数沿革行写「README **同步 1422**」；磁盘 `README.md:11,178` / `README.zh-CN.md:11,169` = **1421 passed**（截至 2026-09-29）。
2. 台账 R4-BL-5 行写「`.pytest-tmp-m65c` 已删并**纳入 `.gitignore`**」；磁盘 `.gitignore`（38 行全文）**无** `.pytest-tmp*` 规则（目录本身确已删除 → 残留风险仅"复发"）。
- 判据：`test_v2_readme_claims.py:61-74` 对计数有 `≤20` 容差 → 1421 与 1422 之差使**判据绿**，故这是"台账话术"而非"判据"抓出的偏差；但 M6 的交付纪律正是"对磁盘核证后放行"，R4 曾以同族问题判**阻塞**（BL-1/BL-4），标准应一致。
- 最小处置：README 改 1422（或台账改口径）＋ `.gitignore` 补一行或用词改准。

### F-3（非阻塞）入口层三出口中「mgw 子命令」只覆盖 zcode
`tech-design.md:1526` 入口层图列「`/admin/api/accounts*` · `accounts.js` · **mgw 子命令**」；实际 `cli.py:29-77` 仅 `probe/setup/zcode`。API+UI 已覆盖五个动作面 → 不阻塞；但规格图与实现不符，未登记。

### F-4（非阻塞）物化后 1s 窗口内整份保存可能覆盖刚物化的资源
机理：物化写盘 → 内存快照待热重载（实测 1.08s）→ 期间 `PUT /admin/api/config`（整份保存）把旧快照写回盘 → 新资源行丢失（账号与凭据仍在）。可达性：需人类在 1s 窗口内"导入→开资源页→保存"，实际不可达；`materialize.py` 模块头已把「`api/admin.py` PUT 直调未纳入跨进程锁」登记为残留，本条是同一处的**时序面**，建议合并登记。

---

## 七、未能证伪的尝试

1. 让未登记产品在任意出口露头（API 400 / ops 参与方不含 / 前端列表不含）—— 未打穿。
2. 让 zcode/qoder 在前提未就位时"装作可用"（`/v1/models` 隐藏 + 横幅点名 D1 + 直调 503）—— 未打穿。
3. 让停用账号仍被运营领取（`inactive` + 上游零请求）—— 未打穿。
4. 验证"切换"只对 zcode 生效（两 buddy 账号跨账号切换实测成功）—— 未打穿。
5. 推翻两条最严重修复的红证（F1 alt TTL / R3-P4 CSRF）—— 撤修复各自复现红、复原绿，未打穿。
6. 在 README/台账里找"把未实测写成已完成"的句子 —— 只找到 B-2 类计数/卫生话术不实（**不是** §22.11 性质的谎报）—— 该红线未被打穿。

---

## 八、未验证

- 真实凭据逐产品登录/领取（§22.11 U1）：本轮全部假凭据 + 假上游。
- D1 zcode 直连 405/3012 真实行为（U2）：只验证了"前提未就位 → 如实标注 + 不进模型列表"。
- qoder/qodercn 真实签名通道（U3）、真机验证码（U5）、上游字段漂移（U4）：无真实凭据不可判。
- 前端 55 项 DOM 断言与 9 张截图**未逐项重跑**（依赖 R3 独立重跑 67 项 + 本次抽看截图/JSON）；窄屏与深色仅看图。
- 台账历史计数 835/996/1221/1304/1371 无盘上产物可核（仅终值 1422 本次独立复跑）。
- 台账 R4-BL-1/BL-4 中「`test_v2_circuit*.py` 归属未确认」：归属无法从盘上判定，按自述接受。

---

## 附：本次独立证据清单（实验产物全部在 /tmp；主树唯一写入 = 本报告）

| 证据 | 路径 |
|---|---|
| PM 探针 1（故事①②③ + ⑤ 转发 + 矩阵 + D1/签名诚实性，30/30 PASS） | `/tmp/m6pm-probe/probe.py`、`/tmp/m6pm-probe/probe-results.json`、实例配置 `/tmp/m6pm-probe/data/config.yaml`、假上游 127.0.0.1:8393 |
| PM 探针 2（切换/续跑，6/6 PASS） | `/tmp/m6pm-probe/probe2.py`、`/tmp/m6pm-probe2/probe2-results.json`、假上游 127.0.0.1:8395 |
| 变体红证（F1 / CSRF） | `/tmp/m6pm-mut`（改前改后复跑输出见上文）、备份 `/tmp/m6pm-login.bak`、`/tmp/m6pm-admin.bak` |
| 全量 pytest（复制品） | 1422 collected / 1421 passed / 1 failed（伪红，机理复核见结论）；`--basetemp=/tmp/m6pm-40733`、`-p no:cacheprovider` |
