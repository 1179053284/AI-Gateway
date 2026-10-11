# M6-R4 独立评审报告 · 横向纪律 / 护栏完整性 / 文档一致性（对抗式）

> 角色：独立评审 R4（对抗式，只读主树；不改任何源码）
> 评审对象：全部 M6 改动面 + 过程纪律 + 文档一致性
> 证据基准：`docs/specs/prd.md` Q29 / `docs/specs/tech-design.md` §22 / `docs/changes/e2e-records/E2E-20260930-M6-multi-product.md` 台账
> 快照时间：2026-09-30 02:37 CST（`git status --porcelain` 105 项 + mtime 复核）
> 评审方法：越界审计（git status + mtime（近 8h）+ 任务面比对）／护栏反例实验（/tmp 复制品）／
> 文档 ↔ 实现逐条对表／实测复跑（`--collect-only`、护栏用例）／卫生检查（进程/临时目录/data 写入）
> 硬约束：主树只读（唯一写入 = 本报告）；不碰 :8300；实验在 `/tmp` 复制品；`--basetemp=/tmp/m6r4-$$`

（本报告增量编写中，评审进行时……）

## 1. 越界审计（改动清单 + 授权面对照）

### 1.0 口径

- 快照：`git status --porcelain` = **105 项**（M 29 / ?? 76；HEAD 停在 v0.1.0 后 6 个 commit，v2 全部工作在未提交工作树上）。
- 窗口：**M6 窗 = 09-29 21:30 → 09-30 02:37**（M6-0 的前置调研稿 21:47 起；S-46 尾批在 21:28 收，不属于 M6）。
  「近 8h」= 18:37 起，另含 S-46（19:15–21:28）四项，单列在 §1.4 说明。
- 任务书不在磁盘（无 M6 brief 文件），授权面按：① 台账 `E2E-20260930-M6-multi-product.md`；② 任务列表（#6–#28）；
  ③ 各文件自述；④ 报告/记录文件四路交叉推定。**因此「是否在授权面内」的判定强度 = 推定，不是原文引用** —— 这点如实登记。

### 1.1 M6 窗内改动清单（按波次归组；mtime 为实测）

| 波次/归属 | 文件（mtime） | 授权面推定 | 报告记录 |
|---|---|---|---|
| 调研（前置） | `docs/research/20–24`（21:47–21:50） | 任务 #1–#5 | 任务系统 + 24 落盘 |
| M6-0 | `docs/specs/prd.md`（22:18）+ `tech-design.md` §22（00:07） | 台账 M6-0 行 | ✅ 台账 M6-0 行 |
| M6-1 公共层 | `accounts/{net,types,device,registry,__init__,materialize,login,store}.py`（22:31–01:39）；`ops/runner.py`（22:37）；`upstream/*/__init__.py` ×10（22:48）；`upstream/zcode/{dataroot,store,oauth,product,out}.py`（22:34–01:29，zcode 对齐+M6-5c）；`tests/accounts/{test_device,test_login_engine,test_store}.py` | 台账 M6-1 行（"zcode 委托化；`ops/runner.product_of_account` 泛化"点名） | ✅ 台账 M6-1 行 |
| M6-2 批 A | `upstream/{buddy,workbuddy,cline,lobsterai,qoder,qodercn,raccoon,loomy,trae}/**`（22:48–02:11）；`tests/accounts/test_{buddy,workbuddy,cline,lobsterai,qoder,qodercn,loomy,raccoon,trae,zcode}.py`（23:09–01:39） | 任务 #14/#15/#17/#18/#19（逐产品"产品钩子 + 测试 + registry 回填"） | 台账 M6-2/M6-3 行（未逐文件） |
| M6-3 | 同上 trae/loomy/raccoon/zcode | 任务 #17–#19 | 台账 M6-3 行（raccoon 中断一事有专记） |
| M6-4 管理端 | `api/admin_accounts.py`（新建 01:01）、`api/admin.py`（00:29）、`web/static/js/pages/accounts.js`（新建 01:14）、`main.js`+`index.html`（01:07）、`tests/integration/test_admin_accounts.py`（01:39）、`docs/changes/e2e-records/m6-accounts-*.png|json`（01:33） | 任务 #21–#23 + 台账 M6-4 行（SHELL） | 台账仍写 SHELL（**滞后**，见 §3.3）；R3 报告已引用其证据 |
| M6-5 转接 | `config/schemas.py`（00:50）、`adapters/{product_out,openai_out,__init__}.py`（00:39–00:53）、`main.py`（00:40）、`tests/{unit/test_product_out,test_schemas_product,integration/test_*_out,test_materialize}.py` | 任务 #20/#24–#28 + 台账 M6-5 行（SHELL） | 台账仍写 SHELL（**滞后**）；文件自述逐条 |
| M6-6 修复（窗内、无台账行） | `tests/unit/test_v2_circuit.py`+`test_v2_circuit_rejudge.py`（00:45，R-1 时刻注入修）；`tests/unit/test_config.py`（00:48）；`tests/unit/test_v2_wiring_guard.py`（02:17，白名单+M6 适配器条目）；`README.md`+`README.zh-CN.md`（02:37，199→1371、v0.1.0→v0.2.0、mgw 章节） | M6-6 域（RL 修复），但**四项均无报告记录** | ❌ 台账最后写入 00:07，未追加 |

### 1.2 点名文件逐项结论

1. **`tests/accounts/test_registry.py`（23:38）** —— 改动内容 = `_implemented_hooks` 容差 + `OPTIONAL_HOOKS`（文件自述"；M6-2/M6-3 波次引入"，见 `:48`、`:33`）。**多代理并发编辑**有台账 R-3 自述（"被多位代理编辑……需复核没有削弱护栏"）。判定：**落在 M6 波次授权面内（判据文件归公共层/各产品波次）**，但**无单一 owner、无 diff 追溯**（文件未入库、无 baseline），R-3 至今**未闭环**。护栏强度实测见 §2.1。
2. **`tests/unit/test_v2_cli_zcode.py`（22:57）** —— 改动内容 = 死符号扫描面收窄（排除 `upstream/*/product.py`）。**已授权且有记录**：台账「已裁决 #3」逐字写明（"扫描面收窄到旧 zcode 面……`def refresh(` 是 §22.3 在册钩子"）。护栏反例见 §2.2。
3. **`README.md` / `README.zh-CN.md`（02:37）** —— 内容 = 徽章 199→1371、版本 v0.1.0→v0.2.0、新增 `mgw` CLI 章节、真实凭据"not yet verified"条款。台账 W2 行声明"README 计数由总 agent 统一回填（不让代理自行改）"，且 R-2 承诺"本次在 M6-4 前回填" —— **实际 mtime 02:37 晚于 M6-4/M6-5 落盘（01:39）**，台账无对应条目。数字本身核证通过（§3.4：`--collect-only` = 1371 = 宣称值）。判定：**内容合规、口径对得上、记录缺失**（写的人未知）。
4. **`scripts/**`（M6 窗内）** —— **零 M6 写入**。窗内两项均属 S-46 工作流：`scripts/verify_v2_frontend.mjs`（20:03，S-46 两个批次各声明"只改这一个文件"）、`tests/integration/test_int_v2_frontend_gate.py`（19:59，同批声明"按纪律改数量下限+docstring"）；`scripts/ui_verify_v2_visible.py` 未动（09-28 18:42）。
5. **`core/scheduler.py`** —— **不在 M6 窗内**（mtime 09-28 14:34）。§22.5-3 的"适配器复用判据追加 product+account_ref"落在 `main.py:208/276/348-353`（复用键 = `product + account_ref + 凭据指纹`，已核）。点名文件结论：**未越界**。
6. **`api/**`** —— M6 窗内两项：`api/admin.py`（00:29）、`api/admin_accounts.py`（新建 01:01）。均属 M6-4（台账 M6-4 行明列"admin API"）。`api/openai_compat.py` 未动（09-27 07:50）。**结论：在授权面内**；台账未回填（见 §3.3）。
7. **并行工作流文件** —— `gate-s46-{shared-layer,pages-a,pages-b}.md`（18:10/20:07/21:28）、`circuit-rejudge.md`（21:07）、`E2E-20260928-round5-fixes.md`（21:14）**全部早于 21:30**，且 M6 期间**零追加**；`components.js`（19:15）的改动 = S-61 修复，已在 `E2E-20260928-round5-fixes.md`「S-61 已修」一节记录（含真 Chrome 正/反证 + cmp 复原）。**结论：无 M6 代理写入并行工作流文件**。

### 1.3 越界/未记录改动计数

- **明确越界（跨别人独占面、无任何授权依据）：0 处。**
- **"推定授权面内、但无报告记录"**：4 处 —— README×2（02:37）、`test_v2_circuit.py`+`test_v2_circuit_rejudge.py`（00:45）、`test_v2_wiring_guard.py`（02:17）；另 `test_config.py`（00:48）属 M6-5 自然面（改配置文件测试），未单列。
- **多写者风险面**：1 处 —— `tests/accounts/test_registry.py`（多代理编辑，R-3 自述）。
- **`data/` / 材料目录：0 处**（见 §5）。

### 1.4 近 8h 但先于 M6 的四项（供对照，不计 M6 越界）

`web/static/js/pages/dashboard.js`（17:02）、`pages/apiaccess.js`+`pages/resources.js`（18:30）、`components.js`（19:15）、`test_v2_adapter_drain.py`（20:15）。
前三项属 S-46/S-61 前端返工面（`components.js` 修复有记录；另两页改动未见当轮记录点名，**建议 M6-7 交付前交叉补记**）；`test_v2_adapter_drain.py`（20:15）疑为 S-46 期间的适配器排空判据，未见记录点名（**待交叉核对**）。

## 2. 护栏完整性（逐文件判定 + /tmp 反例实验）

实验环境：`/tmp/m6r4-tree`（主树子集复制品：`model_gateway/`+`tests/`+`pyproject.toml`+README）；
解释器 = 主树 `.venv/bin/python`（cwd 优先，实测 `import model_gateway` 解析到 `/private/tmp/m6r4-tree/...`）；
`--basetemp=/tmp/m6r4-$$`、`-p no:cacheprovider`、`PYTHONDONTWRITEBYTECODE=1`。主树零写入（除本报告）。

### 2.1 `tests/accounts/test_registry.py` —— 容差机制（R-3 待判项）

机制（`:47-68` `_implemented_hooks`）取**并集**：① 模块声明 `_IMPLEMENTED` → 精确放行所列钩子；
② 无声明但存在 `test_<product>.py`/`test_<product>_*.py` → **放行全部 10 钩子**（整体让位）。两者皆无 → 全约束（M6-1 原判据）。

实测（基线 `tests/accounts/test_registry.py` 38 passed；本实验只改复制品）：

| # | 反例（在复制品里植入） | 期望 | 实测 | 结论 |
|---|---|---|---|---|
| E2a | `qodercn.product.probe` 换成 `return ProbeResult(reachable=True, valid=True, detail='FAKE-ALWAYS-OK')` | 若护栏有效应红 | **`test_unimplemented_hooks_do_not_fake_implementations[qodercn]` GREEN**；`tests/accounts/test_qodercn.py` RED（`test_cn_hook_refuses_intl_credentials_without_upstream_call` 抓到） | 容差生效：**护栏本身放行**，是产品单测把它拦住的 |
| E2a' | `qodercn.product.build_out` 换成 `return object()` | 同上 | 护栏 **GREEN**；`test_qodercn.py` **GREEN（10/10）**；`tests/integration/test_qodercn_out.py` **RED（4 failed）** | 产品单测**并不覆盖** `build_out` —— 真正兜住的是集成测试，不是 `_implemented_hooks` docstring 宣称的"行为判据归该文件" |
| E2b | `trae.product.login_poll`（`_IMPLEMENTED` **未列**）换成 `return None` | 应红 | **RED**（`trae.login_poll 是骨架却返回了值`，`test_registry.py:189`） | 已声明产品的"未列钩子"仍被护栏守住 ✓ |

**判定**：
- **是削弱**，但削弱面**精确**：仅对 `_IMPLEMENTED` 缺失的产品（实测 = `qoder`、`qodercn`；`qoder/product.py:107` 注释明说"由 `test_qoder.py` 整体接管"）变成"整体让位"。
- R-3 的验收句式「容差只放行'已声明/已有测试'的产品；**未声明者仍红**」**与机制不符**：qoder/qodercn 未声明，但植入假实现时护栏**不红**。
- 兜底判断：E2a' 证明集成测试仍能拦住（4 failed），所以**当前树不是裸奔**；但"产品单测接管"这句 docstring 对 `build_out`（qodercn）不成立 —— 要么补 `_IMPLEMENTED`，要么修 docstring 措辞，二选一，别让下一轮再按这句话推断。
- 建议（不代改）：给 qoder/qodercn 补 `_IMPLEMENTED`（精确到钩子）即可把 E2a' 类假实现拉回护栏面；成本一行常量。

### 2.2 `tests/unit/test_v2_cli_zcode.py` —— 扫描面收窄（台账已裁决 #3）

`:190-192` 排除条件 = `not (p.name == "product.py" and p.parent.parent.name == "upstream")`。实测：

| # | 反例 | 期望 | 实测 | 结论 |
|---|---|---|---|---|
| E3a | `def oauth_refresh(cred): ...` 植进 `upstream/qodercn/product.py` | 若面未收窄应红 | **GREEN**（漏） | `upstream/*/product.py` 整体出面的真实盲区 |
| E3b | 同一符号植进 `upstream/qoder/out.py` | 应红 | **RED**（`test_removed_dead_symbols_stay_removed` 1 failed） | 旧面（非 product.py）照旧守得住 ✓ |

**判定**：收窄理由对 `def refresh(` 成立（它现在是 §22.3 冻结钩子名，会与"死代码复活"误伤），
但排除面是**整个文件**而不是**单个符号/单个文件集合**：其余 5 个死符号
（`degradation_chain`/`classify_status`/`classify_http_error`/`is_retryable`/`oauth_refresh`）若在任一 `product.py` 长回来，**这层护栏不红**（`grep "def oauth_refresh("` 全仓只会在 product.py 处静默）。
严重度：中低（产品单测/集成测试不覆盖这 5 个名字；但"死代码复活"本身不产生功能回归）。
**台账已披露（#3），不算隐瞒**；建议在 M6-6 决定是否把排除收窄到 `def refresh(` 单符号（同一补丁 1 行）。

### 2.3 `tests/unit/test_v2_wiring_guard.py` —— 白名单变更（02:17）

- 基线（复制品）：`6 passed in 123.57s`。
- 覆盖面自证：向 M6 新模块 `upstream/buddy/out.py` 植入一个无引用公开函数
  → `test_every_public_symbol_has_a_referrer` **RED**（`...buddy/out.py#dead_m6r4_public_helper` 被点名）。
  **新模块自动入面且真能红** ✓。
- 白名单新增条目（M6 适配器接口方法）逐条核真：
  - `upstream/qoder/out.py#QoderOut.chat_nonstream` → `core/scheduler.py:500` 确有 `self._adapter(r).chat_nonstream(...)`；
  - `adapters/{anthropic,openai}_out.py#*.images_generate` → `core/scheduler.py:514`；
  - `upstream/trae/out.py#TraeOut.{chat_nonstream,chat_stream}` → `:500` / `:589`。
  `test_polymorphic_allowlist_reasons_are_verifiable`（同名 ≥2 类 + 全包有 `.<name>(` 调用点）与
  `test_allowlist_entries_are_not_stale` 均随基线绿 —— 即"多态调起"理由**可核验、非借口**。
- **判定：白名单变更本身未削弱护栏**（豁免 = duck typing 接口方法，是既有机制的正确用法；粒度按全路径符号）。
  但两点登记：① 该文件在 **02:17（M6-6 审查窗）** 被改，**无报告记录**，且改动者很可能是被审一侧（M6-5c 出站接线）——
  "被审方改护栏"需在台账补记以保独立性可追溯；② 文件自述的已知盲区（同名 import 关系假绿、间接注册假红）维持原状，未见新开洞。

## 3. 文档一致性（PRD Q29 ↔ §22 ↔ 实现 ↔ 台账 ↔ README）

### 3.1 PRD Q29 / tech-design §22 → 实现（逐条核）

| 条款 | 实现落点（实测） | 判定 |
|---|---|---|
| Q29-① 10 实例（除 CodeArts） | `accounts/registry.PRODUCT_IDS` 10 项；`test_registry.py::test_registry_has_the_ten_products_and_no_codearts` | ✅ |
| Q29-③ 最小公共层 | `model_gateway/accounts/{types,registry,store,device,login,net,materialize}.py` + 10 个 `upstream/<p>/` 薄模块 | ✅（结构层面） |
| §22.3 类型面 | `types.py:18` LoginKind / `:72,84` ProductMeta(+`login_alt` 默认) / `:178-191` ClaimOutcome(category 复用 `ops.base.Category`，`types.py:15` import) + NotRefreshable / `:126` ProbeResult | ✅ |
| §22.3 补入①`protocol="custom"` | `registry.py` qoder/qodercn/trae=custom；`test_registry.py::test_matrix_protocol` 钉住 | ✅ |
| §22.3 补入②ClaimOutcome/NotRefreshable | 同上 | ✅ |
| §22.3 补入③`meta` 通道 | `store.py:192 hook_meta()`（`account`/`dir` 锚字段最后写、防 meta.json 覆盖、白名单化名字） | ✅ |
| §22.3 会话约定 `start(kind=)` | `login.py:172`（缺省=主推形态、非法值当场 `ValueError`）+ `:304` 门面 | ✅ |
| §22.3 `_ALT_HOOKS`/`alt_call` | `login.py:320` `alt_call(product, session, name, **kw)`，未知名字 KeyError；loomy/raccoon 导出 `_ALT_HOOKS`；`test_registry.py` 校验可选钩子签名 | ✅ |
| §22.4 矩阵：登录/设备/模型来源/协议 | `test_registry.py` 四条矩阵用例（38 passed）逐产品断言 | ✅（**base_url 列不存在于矩阵**——见下） |
| §22.4 base_url | `registry.py:24` 注释自认"§22.4 没有 base_url 列"，逐产品注明出处；10 条中只有 zcode 被用例钉（`test_registry.py:250`）→ **其余 9 条仅文档可溯、无判据** | ⚠️ 覆盖缺口（登记，非违规） |
| §22.5-1 物化 | `accounts/materialize.py`（00:38）+ `test_materialize.py` | ✅（R1/R2 深查） |
| §22.5-2 schema（`account_ref`；api_key 可空但 product 空时必填） | `config/schemas.py:149-191`（validator 双向约束）+ `test_schemas_product.py` | ✅ |
| §22.5-3 分派 product 优先 + 复用判据 | `adapters/__init__.py::build_adapter` 首行判 product；`main.py:208/276/348-353` 复用键含 `product+account_ref+凭据指纹` | ✅ |
| §22.6 operation 收敛（claim/query_balance、`zcode_claim` 兼容别名） | **机制在、收敛未做**：`ops/runner.py:365-411` 已支持 `operation=` 并按其 `supported_products` 过滤参与方（§22.6 的匹配机制）；但 `ops/builtin/__init__.py` **仍只注册 2 条**：`zcode_claim`（`zcode_claim.py:23` `SUPPORTED_PRODUCTS=("zcode",)`）+ `query_balance`（zcode only）；全仓无 `"claim"` operation id、无别名条目、无多产品 claim op → cron/批量路径对 9 个新产品**未接线** | ⚠️ **部分落地**（台账无此状态条目） |
| §22.7 API 13 端点 | `api/admin_accounts.py:337-647` 逐条齐（accounts / capabilities / login{start,poll,callback,alt} / import / {product}/{name}/{claim,refresh,probe,enable,disable,delete}） | ✅ 端点面齐（响应体凭据面归 R3） |
| §22.7 UI「账号接入」页 | `main.js:8/19/27`（PAGE_META+路由）、`index.html:42` 导航、`accounts.js`；证据 `m6-accounts-{light,dark,narrow,wizard-*}.png`+`m6-accounts-assertions.json` | ✅（合规深度归 R3） |
| §22.8-1 无阻塞事件循环 | 全 M6 面 grep 无 `requests`；`time.sleep` 仅 `upstream/zcode/dataroot.py:205,211` 的 `kill_zcode()`（**CLI 一次性进程管理**，`cli_zcode.py:104` 调用，不在异步服务路径） | ⚠️ 字面外，实质可接受（登记） |
| §22.8-4/5 写盘唯一入口、未知 fail closed | `accounts/store.py` 唯一入口 + 原子写；zcode 状态文件沿 Q28-⑧ | ✅（R1 深查） |
| §22.11 待实测 | 见 §4（未见任何一处被写成"已完成"） | ✅ |

### 3.2 §22.4 矩阵列的专项说明

任务书要求核对"§22.4 矩阵的 base_url/device/protocol 列"——**实测矩阵本体只有 产品/登录/设备/额度/签到/模型来源/上游协议/照抄落点 八列，没有 base_url 列**（`tech-design.md:1618-1629`）；`registry.py:24` 的注释也这么说。
- `device` / `protocol` 两列：被 `test_registry.py::test_matrix_device_fields` / `test_matrix_protocol` 逐产品钉住，38 passed ✅。
- `base_url`：9/10 无判据，仅 `registry.py` 内逐条注明来源（如 lobsterai→`lobsterai-product.ts:63`、cline/loomy 含 `/api/v1` 的拼接理由）。**建议**在 M6-7 补一条矩阵用例或把出处写进 §22.4 附注，别让"注册表值"成为无人能核的自由量。

### 3.3 台账（E2E-20260930-M6-multi-product.md）与事实对照

| 台账条目 | 事实（mtime/实测） | 判定 |
|---|---|---|
| M6-3「收尾中……缺公共层 `hook_meta`＋会话 kind/`_ALT_HOOKS`（收尾代理进行中）」 | `hook_meta`（`store.py:192`，文件 01:39）、`start(kind=)`（`login.py:172`，01:01）、`alt_call`（`:320`）均已落地；trae/loomy/raccoon 全部文件+测试在 01:29 前完成 | **滞后**（00:07 后未回填） |
| M6-4「SHELL」 | `api/admin_accounts.py`（01:01）、`admin.py`（00:29）、`accounts.js`（01:14）、`main.js/index.html`（01:07）、`test_admin_accounts.py`（01:39）、截图/断言（01:33-34）已全部落盘并自测 | **滞后**（波次事实上已实施） |
| M6-5「SHELL」 | `materialize.py`（00:38）、`product_out.py`（00:53）、`schemas.py`（00:50）、`main.py`（00:40）、10 个产品 `out.py` + `test_*_out.py` 全落盘 | **滞后** |
| R-1（`test_v2_circuit` 跨午夜假红）「待修」 | 00:45 已注入时钟（`test_v2_circuit.py:249/280-292` `_frozen_wallclock`/`_frozen_ms`，与 `fmt_recovery_clock` 同源）；台账未标已修 | **滞后** |
| R-2（README 计数漂移）「本次在 M6-4 前回填」 | 回填 **实际 mtime 02:37**（晚于 M6-4 落盘 01:39）；数字核证通过（§3.4） | **滞后 + 口径不符** |
| R-3（`test_registry.py` 容差需复核） | 仍未闭环（本报告 §2.1 给出判定与反例） | **开** |
| R-4（hook_meta/zcode/loomy 短信缺口）「收尾代理进行中」 | 已落地（`hook_meta` + `_ALT_HOOKS`）；台账未更新 | **滞后** |
| R-5/R-6（trae 不轮询 / loomy pending.detail+qr 渲染） | 未见核对记录；`accounts.js` 是否按 R-5/R-6 实现属 R3 面 | **待 R3 结论** |
| R-7（ModelInfo 字段缺口登记：buddy `defaultReasoningEffort`、`creditsRate`） | `types.py:156-174` ModelInfo **未扩字段**（`creditsRate`/`defaultReasoningEffort` 零命中）→ 与"未扩字段，不编造"一致 ✅ | ✅ |
| 「全部产出仅新增/修改 M6 授权面；`data/` 零写入；材料目录全程只读」 | §1/§5 核证：授权面基本成立；`data/` 无 M6 进程写入；材料 git 干净 | ✅（表述成立） |

> 结论：台账**处于"进行中"状态且明显滞后于磁盘**（最后写入 00:07 vs 最新产物 02:37，七个条目未回填）。
> 按台账自己的纪律（文件头"每波次收尾即追加该波事实"）与 Q29-⑤（对磁盘核证后放行），**M6-7 交付前必须整体回填**，
> 否则"计数与待修清单状态"这两项在验收时呈现的是假历史。

### 3.4 README 双语计数与 `--collect-only`

- 实测（复制品，`pytest -q --collect-only --basetemp=/tmp/m6r4-collect-*`）：**1371 tests collected**。
- README.md 徽章 `tests-1371%2F1371`、正文"**1371 passed** as of 2026-09-29"；README.zh-CN.md 同。
- 与 `test_v2_readme_claims.py::test_readme_test_counts_are_not_stale` 的两个方向（`n<=collected`、`collected-n<=20`）一致 ✅；版本三向（README / `mgw --version` / `pyproject`）= **0.2.0** 一致 ✅（`mgw --version` 实测输出 `mgw 0.2.0`）。
- **口径提示**：判据钉的是 **collected**，README 写的是 **passed**。若套件存在失败，README 的"1371 passed"仍可过判据。本评审复跑（复制品全量）见 §3.5 —— 这正是"数字对得上 ≠ 全绿"的既有已知弱点，登记不改（判据设计属 M6-6 决策）。
- 另：README 说需要真实凭据的 ZCode/Anthropic 项"已显式列为 not yet verified"，但**仓库内没有那份清单**（`docs/` 已被移出版本库，README 自身也不允许引用它）——用户侧只能看到这一句承诺。建议改为在 README 内嵌最小清单（或改写措辞），避免"承诺了一个看不到的清单"。

### 3.5 复制品全量复跑（README "1371 passed" 的独立核证）

命令（`/tmp/m6r4-tree`，主树零写入）：
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/ -q -p no:cacheprovider --basetemp=/tmp/m6r4-full-$$`

```
3 failed, 1368 passed in 271.87s (0:04:31)
FAILED tests/integration/test_int_v2_frontend_gate.py::test_frontend_assertions_all_pass
FAILED tests/integration/test_int_v2_frontend_gate.py::test_frontend_assertions_can_actually_go_red
FAILED tests/unit/test_v2_servable.py::test_ops_lock_dir_ignores_cwd
```

**3 条全部判定为复制品环境伪红（逐条复证）**：

1. 前两条：复制品当时缺 `scripts/`（本次排除清单）→ 门脚本找不到。补 `scripts/` 后单独复跑：
   `tests/integration/test_int_v2_frontend_gate.py` → **2 passed in 52.14s** ✓。
2. 第三条：该用例在子进程里换 cwd 比对 `ops_lock_dir()`，子进程 env 被写死为 `{"PATH","HOME"}`
   → 复制品 cwd 下导入的是复制品、`/tmp` cwd 下导入的是 venv 的 **editable 主树**，两边本就该不同。
   独立复证（只读，不起 pytest）：主树 cwd 与 `/tmp` cwd 各跑一次
   `from model_gateway.ops.runner import ops_lock_dir` → 均为 `/Users/w/Desktop/Model-Gateway/data/ops-locks`（一致）✓。

**净结果：复制品 1368 passed + 3 条环境伪红 = 主树预期的 1371/1371**（未在主树内跑全量 —— 只读约束）。
README 的 "1371 passed" 与 `--collect-only` = 1371 交叉成立；台账 W3 行的 "~1206–1210 passed / 1–3 failed"
是修复前历史值，与当前不矛盾（R-1/R-2 已修）。

## 4. 「未实测」清单完整性（全部声称未实测项；确认无一被当成已完成）

收集面：`tech-design.md` §22.11 / §19 / §22 + `prd.md` Q29 + E2E 台账 + README 双语 + `accounts/`、`upstream/**` 源码注释。
以下**每一项**在磁盘上都写作"未实测/未取证/待实测/not yet verified"，**未发现任何一处被写成"已完成/已验证"**：

| # | 项 | 登记处 |
|---|---|---|
| U1 | 真实凭据逐产品登录/领取出证（用户驱动） | `tech-design.md:1698-1700`；台账头 §③；README 尾注 |
| U2 | zcode 直连 405/3012（D1 待实测） | `prd.md:813`；`upstream/zcode/product.py:334`；台账 M6-0 行 |
| U3 | qoder 模型转发的签名端点（若需要） | `tech-design.md:1700`；`qoder/out.py` SIGNER_FACTORY 注入缝（未注入 = fail closed） |
| U4 | macOS 下各产品行为 / 上游字段漂移（`20 U1–U13`/`21 U1–U8`/`22 U1–U7`/`23 U1–U10` 按需复核） | `tech-design.md:1700` |
| U5 | zcode 验证码"真机能否过无痕" + `client/configs` 字段时效 | `upstream/zcode/captcha.py:17-18`（"本机无法验证……只保证接口纪律与降级可见"） |
| U6 | T5a/T5b：`curl_cffi` 过 WAF + async SSE 流式 | `tech-design.md:1258,1311`；`upstream/zcode/auth.py:17,86` |
| U7 | T10：三个 `ZCODE_DESKTOP_*` 是否真覆盖 `app.setPath` | `tech-design.md:1083,1426`；`upstream/zcode/dataroot.py:24` |
| U8 | zcode 探活/直连真实可用性（不打验证码的端点） | `upstream/zcode/product.py:333-334` |
| U9 | buddy `X-IDE-Name/Type/Version` 取值未取证 → **不发**；UA 按模型族分档取值未取证 | `upstream/buddy/out.py:15-16`；`buddy/protocol.py:185` |
| U10 | cline `stream:false` 上游是否接受未取证；余额单位未取证（不换算） | `upstream/cline/out.py:33-34`；`cline/constants.py:80-85` |
| U11 | raccoon `device_id` 字段语义/是否每账号互异未验证；`stream:false` 未取证 | `upstream/raccoon/product.py:31`；`raccoon/out.py:52-53` |
| U12 | loomy `stream:false` 未取证；微信图内容字段"不编造" | `upstream/loomy/out.py:29-30`；`loomy/wechat.py:32`、`loomy/product.py:24` |
| U13 | qoder/qodercn CN 是否需要 `sessionType` 非缺省值 | `upstream/qoder/ask.py:41` |
| U14 | lobsterai `prompt_cache_key` 未实测支持（不注入） | `upstream/lobsterai/out.py:13` |

配套核证（防"把未实测当已完成"）：
- 无 skipped/xfailed 伪装：`grep -rn "pytest.mark.skip|skipif|xfail" tests/accounts tests/integration/test_*_out.py tests/unit/test_product_out.py` → **零命中**。
- M6-4b "独立实例真机实测"用的是**假凭据**：实例配置 `/tmp/mg-m64b/config.yaml` 全部 `api_key: ''`（产品账号资源），
  其账号目录凭据为占位符（实测样例：`{"token": "SECRET-TOKEN-DO-NOT-LEAK-9f3a"}` / `T1` / `T2`）——
  即该"真机"是 **UI/接口层的真机**，不是真实上游凭据实测；与 §22.11 不冲突，也未被吹成真实凭据验证。
- README 尾注"ZCode / Anthropic-path items ... **not yet verified**"与上表一致；但见 §3.4 的措辞问题（清单本体不在用户可见面）。

## 5. 卫生（进程 / 临时目录 / data / 材料目录）

### 5.1 端口与进程（实测 `lsof`/`ps`，快照 02:40–03:0x）

| 端口/PID | 状态 | 判定 |
|---|---|---|
| `:8300` PID 61799（`.venv/bin/python -m model_gateway.main`，启动 09-29 01:14，ppid 1） | 主网关，监听 `*:8300` | 预期内（不碰） |
| `:8398` PID 30292（`/tmp/m6r3/launcher.py`，启动 **02:40:27**） | **R3 评审的活实例**（健康检查回 `config:/private/tmp/m6r3/config.yaml`） | 非孤儿；并行工作流，勿动 |
| `:8399` | **无监听** | ✓ 任务书点名的"遗留 8399"不存在 |
| `:8419` PID 20058（`model_gateway.main`，启动 **01:09:33**，ppid 1，config `/tmp/mg-m64b/config.yaml`） | **M6-4b 遗留孤儿实例**（已存活 ~1.5h，10 资源/0 系统模型/0 token） | ⚠️ 孤儿，建议清理 |
| PID 48105/48106（09-27 的 pty 遗留 `mgw zcode remove acct-b`） | 旧波次残渣（先于 M6） | 登记（非 M6） |

### 5.2 泄漏的临时目录/夹具

- **`.pytest-tmp-m65c/`（仓库根，未入库、未 gitignore）**：8 个测试目录 + 8 个 `*current` 符号链接，
  创建于 01:11–01:12（M6-5b/c 回归批次：`test_qoder_*` / `test_qodercn_*`）。
  内含 `upstream/*/accounts/*/credentials.json` 夹具（占位符，非真凭据）。
  `.gitignore` 只忽略 `data/`、`.pytest_cache/`，**不覆盖 `.pytest-tmp-*`** —— 一次 `git add .` 就会入库。
  违反 §22.9 判据行"`--basetemp` 唯一"的纪律本意（唯一更要落在 `/tmp`，不能落在仓内）。
- `.pytest_cache/` 在 M6 窗内被写（快照日 lastfailed 等）→ 说明有 M6 进程在**主树内**直接跑 pytest 未关 cacheprovider（无害但违反"冻结树"精神）。
- `/tmp`：`/tmp/m6-*`（10+）、`/tmp/m6w1-*`（6）、`/tmp/m6r1-*`、`/tmp/m6r2-work`、`/tmp/m6r3`、`/tmp/mg-m64b`（含 Chrome profile ×2）——评审/波次残渣，量大但位置正确；建议 M6-7 一并清理。

### 5.3 `data/` 是否被写（git status + mtime 双证）

- M6 窗内 `data/` 命中仅两条：`data/usage/daily-20260929.json`（**23:00:00**）、`daily-20260930.json`（**02:00:00**）——
  均为整点边界写（长期运行的 `:8300` 实例 PID 61799 的日切/定时行为），**无 events/ops-results 新增**，
  `data/gateway.lock` mtime 停在 09-29 01:14（未被任何 M6 进程动）。
- **台账"`data/` 零写入"成立**（指 M6 产出未写用户 data/；日切属于常驻网关自身行为）。

### 5.4 材料目录（DSH）零改动抽查

- `/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts`：`git status --porcelain` **空**（工作树干净）；
  最新 snapshot commit 日期 2026-09-29（**先于 M6 开始**）；抽查 `package.json` mtime = **09-29 20:09**（= 快照入库时间，非 M6 期间）。
- 仓库内 `.zcode/`（09-05）/`.trae/`（09-03）未动；`.workbuddy-ai/`（未入库异物，memory 内容为 09-22–09-26，目录 mtime 19:53）为 M6 前遗留，登记不追责。

## 6. 过程反例（≥5；均附证据）

| # | 反例 | 证据 | 严重度 |
|---|---|---|---|
| C-1 | **台账 vs 磁盘口径分叉（滞后 7 项）**：M6-3 写"收尾中/缺 hook_meta"，M6-4/5 写 SHELL，R-1/R-2/R-4 写"待修/在改"——而实现、修复、证据已在 00:29–02:37 全部落盘；台账最后写入 **00:07**。违反其自定纪律"每波次收尾即追加该波事实"（`E2E-20260930-…md:3`）与 Q29-⑤"对磁盘核证后放行"。 | 台账 mtime 00:07；`store.py`(01:39)、`admin_accounts.py`(01:01)、`accounts.js`(01:14)、`test_v2_circuit.py`(00:45, 注入时钟)、README(02:37) | **高** |
| C-2 | **R-2 承诺与事实时间不符**：台账 R-2 写"本次在 M6-4 前回填"，实际 README 回填 mtime **02:37**（晚于 M6-4/5 落盘 01:39）；且回填人不可考（"总 agent 统一回填"是 W2 的约定，M6-6 未记）。数字本身对（1371=collect）。 | 台账 R-2 行；`stat README.md` = 02:37 | 中 |
| C-3 | **护栏被"被审一方"在审查窗内修改且无记录**：`tests/unit/test_v2_wiring_guard.py`（02:17）新增 M6 适配器白名单条目；条目经我逐条核真（scheduler.py:500/514/589 调用点存在），但"改动者 = M6-5c 出站接线一方"的可能性高，无台账条目 → 独立性不可追溯。反例同族：`tests/accounts/test_registry.py` 被**多位代理并发编辑**（台账 R-3 自认），至今未闭环。 | 文件 mtime；R-3 行 | 中 |
| C-4 | **护栏容差的实际语义与文件自述不符**（详情 §2.1）：docstring 写"行为判据归该产品的单测文件"，实测 `qodercn` 植入假 `build_out` → 产品单测 **10/10 全绿**、真正拦住的是集成测试（4 failed）。若无集成测试，假实现会一路绿到交付。 | E2a' 实验输出 | 中 |
| C-5 | **卫生：泄漏 basetemp + 孤儿实例 + 任务口径分叉**：`.pytest-tmp-m65c/`（含凭据夹具）落进仓库根且不在 .gitignore；M6-4b 实例（:8419，PID 20058）跑完不关，存活 1.5h+；任务列表写"独立实例实测（端口 8399）"而仓内证据/存活实例是 **8419**（8399 从未监听）——同一事实两套端口号。 | §5.1/§5.2 | 中 |
| C-6 | **时刻相关假红（潜伏型测试缺陷）**：`test_v2_circuit.py` ×2 条按当日拼串断言"至 HH:MM"，23:39/23:55 运行时跨午夜必红、白天全绿；两个代理各自复现后才定位。修法（注入时钟）到 M6-6 窗口 00:45 才落地。测试写死墙钟 = 可复现性缺陷，非环境问题。 | 台账 R-1 行；`test_v2_circuit.py:249,280-292` | 中 |
| C-7 | **代理死亡后产物被依赖**（已自报）：raccoon 代理 150 轮中断，产物由总 agent 抽验后按"完成"计。台账措辞（"判据是磁盘"）方向正确且后续 64/64 绿复核过；但该代理**自己的报告缺失**，其声明的取证（`X-Client-Platform` 等）当时未经第二人核，属"未核证即被依赖"。 | 台账"过程记录"第 2 条 | 低-中 |
| C-8 | **zcode 对齐代理冒烟期真实网络调用**（已自报，正面案例）：`/oauth/cli/init` 无凭据 GET；违反 brief"无网络"约束，已登记并在后续 brief 加严。**报告得实**，作为诚实披露的正面样本记录。 | 台账"过程记录"第 1 条 | 低（已处置） |

## 7. 结论

### 7.1 总结论

- **越界**：明确越界写入 **0 处**；"推定授权面内但**无报告记录**" **4 处**（README 02:37、`test_v2_circuit*.py` 00:45、`test_v2_wiring_guard.py` 02:17）；多写者风险 **1 处**（`test_registry.py`）。点名怀疑的 `core/scheduler.py`（09-28）、`scripts/**`（S-46 面）、并行工作流文件（全部 ≤21:28）**均无 M6 写入**。
- **护栏**：① `test_registry.py` 容差**确有削弱**且只对 `qoder/qodercn` 生效（整体让位；假 `build_out` 三层实测：护栏绿/单测绿/集成红）——R-3 需以"补 `_IMPLEMENTED` 或改措辞"收口；② `test_v2_cli_zcode.py` 收窄有**面级盲区**（`upstream/*/product.py` 内任何死符号复活不红），已披露、可 1 行收窄；③ `test_v2_wiring_guard.py` 白名单变更**未削弱**（新模块可红、条目可核验），但改在审查窗内且无记录。
- **文档**：Q29/§22 的实现核证基本通过（§3.1 表），**两处缺口**：§22.6 operation 收敛**未落地**；§22.4 无 base_url 列、9/10 条 base_url 无判据。台账滞后 7 项（C-1）。README 计数（1371=collect 实测）与版本（0.2.0 三向一致）**核证通过**；复制品全量 1368 passed+3 环境伪红 → 等价主树 1371/1371。
- **未实测**：14 类逐项在册、无一处被写成已完成；M6-4b"真机实测"实为假凭据的 UI 层实测（与 §22.11 不冲突）。
- **卫生**：`.pytest-tmp-m65c`（含凭据夹具、未 gitignore）、`:8419` 孤儿实例、`.pytest_cache` 主树写入 三项需清理；`data/` 零 M6 写入、材料目录零改动成立。

### 7.2 阻塞清单（M6-7 交付前须收口；本评审不改任何东西）

| # | 阻塞项 | 建议（不代改） |
|---|---|---|
| BL-1 | 台账整体回填（C-1/C-2：M6-3/4/5 状态 + R-1/R-2/R-4 实际已完成；R-5/R-6 待 R3；计数表补 1371） | M6-6 收尾时一次性回填并注明回填时刻 |
| BL-2 | R-3 闭环：`qoder/qodercn` 容差语义（补 `_IMPLEMENTED` 或改正 docstring"行为判据归该文件"） | 二选一并记入台账 R-3 行 |
| BL-3 | §22.6 operation 收敛（`claim`/`query_balance` 多产品化 + `zcode_claim` 兼容别名）**部分落地**且无状态条目：匹配机制已在 `ops/runner.py`，注册表与别名未做 → cron/批量路径对 9 个新产品未接线 | 实现，或正式登记为"未交付/延期"（Q29-⑤ 不许静默） |
| BL-4 | 未记录改动 4 处归属/回填（README、`test_v2_circuit*.py`、`test_v2_wiring_guard.py`） | 在台账补记改动人与时点（护栏文件改动尤其要留痕） |
| BL-5 | 卫生清理：删 `.pytest-tmp-m65c/`（并入 `.gitignore` 加 `.pytest-tmp-*`）、终止 PID 20058、清理 `/tmp/mg-m64b` 等 M6 残渣 | 机械操作，注意 :8398 属 R3 活动实例勿动 |

### 7.3 非阻塞登记（建议 M6-7 一并处置）

1. `test_v2_cli_zcode.py` 排除面收窄到 `def refresh(` 单符号（1 行）；
2. `§22.4` 附注补 base_url 出处或补矩阵用例；
3. README "explicitly listed as not yet verified" 措辞（用户可见面无该清单）；
4. `§22.8-1` 的 `time.sleep` 事实（CLI 进程管理，非事件循环）与 `cline` 余额单位口径写进交付说明；
5. `.pytest_cache/` 主树写入与 `.workbuddy-ai/` 异物登记（M6 前遗留，不追责）。

### 7.4 本报告的边界

- 任务书不在磁盘 → "授权面"为四路推定，**不是原文引用**（§1.0 已声明）；
- 未做：主树内跑全量（只读约束，用复制品等价核证）、:8300 任何交互、任何源码/测试/配置修改；
- 唯一写入 = 本文件。评审过程中所有反例实验均落在 `/tmp/m6r4-tree`（已逐文件 diff/cmp 复原并清洁），
  主树 `git status` 除本文件外零增量。
