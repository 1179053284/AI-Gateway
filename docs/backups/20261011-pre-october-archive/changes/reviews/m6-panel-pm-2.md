# M6 交付面板 · PM-2（复验角色）· 独立复核（B-1 / B-2a / B-2b 闭环核证）

> 角色：PM-2 复验（独立评审，非实现方；**唯一仓库写入 = 本文件**）
> 对象：上一轮 PM 判定「不通过 · 阻塞 2」（`docs/changes/reviews/m6-panel-pm.md`：B-1 `list_models` 零用户出口；B-2a README 计数与台账不符；B-2b `.gitignore` 缺 `.pytest-tmp-*`）；修复轮已处置，本报告核证三条是否真实闭环 + 修复未引入新问题。
> 纪律执行：主树只读（唯一例外 = B-2b 反证目录，造后即删；见 §3）；全部实验在 /tmp 复制品 / 变体；`--basetemp=/tmp/m6pm2-pytest-*` + `-p no:cacheprovider`；不碰 `data/`、`:8300`、真实上游（假凭据 + 零真实调用）。
> 状态：**完成**（本报告为终稿；主树写入唯一 = 本文件 + §3 披露的两个探针目录）

## 结论

**不通过 · 阻塞 1 条**（B-2a 未闭环：README 侧已真，但台账未回填 → 「README 计数与台账不符」仍成立）。
B-1 **闭环**（四态 live + 真机 UI 8/8 + 反向 3/3 + 生产链路 grep + 回归绿）；B-2b **闭环**（规则在盘 + 反证 + 敏感性对照）。
全量回归（复制品，唯一一次）：**1445 collected / 1444 passed / 1 failed** —— 唯一失败为已知**复制品双树伪红**（本轮两点实验直接复核机理，单树形态即 1445/1445）；修复轮 23 条新测试定向复跑 **23 passed**；未发现修复引入其他新问题。

## 零、环境快照（核证基线）

| 项 | 值 |
|---|---|
| 主树 HEAD | `5158cbc`（`5158cbc6d052cfc47c938082ab8d612883f482a9`） |
| 复制品 | `/tmp/m6pm2-copy`（`rsync` 主树，排除 `.venv`/`data`/缓存）；`diff -rq` 与主树**逐字节一致**（含 `.git`，除排除项零差异） |
| 修复轮关键产物 mtime | `admin_accounts.py` 04:52:43 · `accounts.js` 04:32:01 · `.gitignore` 04:12:18 · `README{,.zh-CN}.md` 05:03:52 · 台账 **03:56:58**（早于修复轮全部改动） |
| 关键文件 sha256 | `admin_accounts.py` `d8a44869…` · `accounts.js` `10bdfe6d…` · `.gitignore` `87b1000a…` · `README.md` `3c35af6b…` · `README.zh-CN.md` `c6abb330…` · 台账 `556dc8f3…`（`shasum -a 256`） |
| 独立实例 A（未变异） | `127.0.0.1:8394`，`MG_CONFIG=/tmp/m6pm2-run/data/config.yaml`，cwd `/tmp/m6pm2-copy`（导入解析实测 = 复制品，非 editable 主树） |
| 变体实例 B（源码变异） | `127.0.0.1:8398`，`MG_CONFIG=/tmp/m6pm2-mut/data/config.yaml`，cwd `/tmp/m6pm2-mut`（仅 /tmp，主树零改动） |
| 假凭据 | 统一探针值 `SECRET-PM2-DO-NOT-LEAK-c4f1zz`（写入账号 `credentials.json`，扫描全部响应是否回传） |

## 一、B-1（`list_models` 零用户出口）· 复跑核证 → **闭环**

### 1.1 生产路径调用链（不再零出口；file:line 逐环）

| 环 | 位置 | 证据 |
|---|---|---|
| 路由挂载 | `model_gateway/api/admin.py:36`（`from …admin_accounts import router as accounts_router`）+ `:137`（挂载注释）→ `main.py:874-876` `include_router(admin_router)` | grep + 存活实例实测可达（非只读代码） |
| 端点 | `model_gateway/api/admin_accounts.py:654-690` `GET /admin/api/accounts/{product}/{name}/models`；配置表取用点 `:674` `hook = _hook(product, "list_models")` | 实测四态见 1.2 |
| 前端入口 | `accounts.js:316-318`（`p.models_wired` 才渲染 `[data-op="models"]` 钮）→ `:368`（`openModels` 分派）→ `:448-465`（GET 同端点）→ `:468-488`（`ok` 才出列表，`unknown` 只出原因） | CDP 真机 8/8（见 1.3）；服务端旗标同源 `admin_accounts.py:193-205`（与端点取用**同一张 `_HOOKS` 表**） |

`grep -rn "list_models" model_gateway/api/admin_accounts.py model_gateway/web/static/js/pages/accounts.js` 命中：端点取用（`:674`）、旗标判据（`:205`）、UI 按钮/请求（`accounts.js:316-318,443,458`）——**不再是零消费者**。10/10 产品 `_HOOKS` 皆有 `list_models`（实例 A 视图 `models_wired` 全 True，实测）。

### 1.2 四态 live 复跑（独立实例，假凭据；不 import 被测应用）

| # | 态 | 请求 | 实测结果 | 判定 |
|---|---|---|---|---|
| 1 | 成功 | `GET 8394 /admin/api/accounts/qoder/pm2-qd/models` | **200**，`state=ok`，`source=static`，**17 条**（`auto/ultimate/performance/…`）；响应键恰 `{product,account,source,state,models}` | ✅ 可读 |
| 2 | 未接线 | `GET 8398 /admin/api/accounts/buddy/pm2-bd/models`（变体：摘 `_HOOKS["list_models"]`） | **400** `buddy 未提供钩子 'list_models'（契约表 \`_HOOKS\` 缺项）`；同实例视图 `models_wired: buddy=False`、qoder/其余=True（只影响被摘产品） | ✅ §22.6「未登记=不支持」 |
| 3 | 未知产品 | `GET 8394 /admin/api/accounts/codearts/x/models` | **400** `未登记的产品 'codearts'（在册：buddy/…/zcode）` | ✅ 先在册校验、零调用 |
| 4 | 钩子抛错 | `GET 8398 /admin/api/accounts/qoder/pm2-qd/models`（变体：qoder 钩子改抛错） | **200** `state=unknown` + `models=[]` + `reason="RuntimeError: PM-2 变异复现：目录钩子抛错（仅 /tmp 变体）"`（「读不到」≠「真的为空」） | ✅ 不编造 |
| 附 | 账号不存在 / 非法名 | `8394 /qoder/ghost/models` → 404 `账号不存在：qoder/ghost`；`/qoder/%2E%2E/` → 400 `账号名必须匹配…` | ✅ 拒绝面齐 |

**无凭据明文**：统一探针值在**全部 8 个响应体**中零出现（`live-states.json` 5 例：成功 / 未知产品 / 未知账号 / 非法名 / 视图；`mut-states.json` 3 例：未接线 / 抛错 / 视图；全部 `secret_leaked=false`）；四态响应均不含 `hook_meta` / 账号目录路径字段。
（变体说明：态 2/4 需「产品未接线 / 钩子抛错」构造，10/10 产品现均已接线 → 在 `/tmp/m6pm2-mut` 复制品做源码变异复现，主树零改动；变异仅动两处锚点。）

### 1.3 UI 出口真机断言（CDP headless Chrome → 8394）

`#/accounts` → 子侧栏切 qoder → 行内「模型目录」钮 → 弹窗，**8/8 PASS**（证据 `evidence/ui-check.json` + 截图 `evidence/pm2-models-modal.png`，1440×940）：
U1 子侧栏产品行=10 · U2 默认组账号表=1 行 · U3 切 qoder 出现 `pm2-qd` 行 · U4 头卡提示含「模型目录来源：本地静态表（static）（账号行「模型目录」可查看）」· U5 `[data-op=models]` 钮存在（title + SVG）· U6 弹窗标题=`模型目录 · Qoder / pm2-qd` · U7 **17 条 `[data-mdl]` 含 `auto` + 来源「本地静态表」** · U8 脚=1 颗「关闭」钮。截图可见真实渲染的 17 行模型（id + 12px 事实行）。

### 1.4 死代码抽查（一层链路）

端点 ↔ UI **双向**均活：UI 点击触发真实 `GET` 并渲染 17 行（反向证：变体实例 B 中 `models_wired=False` 时按 `accounts.js:316` 不渲染该钮——旗标与端点同源同表）；端点无 UI 时也可通过 cURL 独立到达（正向证）。**非死代码**。

**变体实例 B 的 UI 反向核证（CDP，3/3 PASS，`evidence/ui-check-mut.json` + `pm2-mut-unknown-modal.png`）**：
V1 未接线（buddy 行）→ **无**「模型目录」钮（≠ 误渲染「点了必然失败」的钮）；V2 钩子抛错的 qoder → 钮仍在（抛错 ≠ 未接线，语义分离正确）；V3 点击后弹窗 = `alert-warn` 原文出原因（含 `RuntimeError: PM-2 变异复现…`）+ `[data-mdl]` **n=0**（零编造条目）。

## 二、B-2a（README 计数与台账不符）· 复跑核证 → **未闭环**

### 2.1 README 侧（已真）

`--collect-only`（复制品，`--basetemp=/tmp/m6pm2-collect -p no:cacheprovider`）实测 **1445 tests collected**；README 双语宣称 **1445**：`README.md:11`（badge `tests-1445%2F1445`）、`:178`（`1445 passed`）；`README.zh-CN.md:11`（`测试：1445/1445`）、`:169`（`1445 passed`）——**逐字一致**（无容差依赖）。README 计数判据（`test_v2_readme_claims.py:61-74`）在其 ±20 容差内绿。

**+23 差额来源可核**（1422→1445，修复轮新增测试）：`tests/integration/test_accounts_models_api.py` 9 + `test_m6_a1_wiring.py` 2 + `test_m6_panel_fixes.py` 6 + `tests/unit/test_ops_panel_fixes.py` 6 = **23**（`grep -c "def test_"`）。即 README 新数字不是笔误，是修复轮真加了 23 条。

### 2.2 台账侧（未回填 → 判定阻塞的依据）

台账 `docs/changes/e2e-records/E2E-20260930-M6-multi-product.md`（mtime **03:56:58**，早于修复轮 04:12–05:03 全部改动）仍写：

- `:5` 「…一次性回填至全量 **1422 passed / 0 failed**」
- `:17` 「M6-6 审核+修复 …全量 **1422 passed / 0 failed**」
- `:29` 「M6-6 修复轮后（**终态**）| **1422 passed / 0 failed**，**README 同步 1422**」 ← 终态宣称
- `:59` 「R-2 README 计数漂移 | ✅ …终态 1422」

而磁盘 README = **1445**、实测 = **1445** → 「台账宣称与磁盘不符」（B-2a 的原始缺陷表述）**仍成立**，只是方向反转：README 侧改真了，**台账侧的「README 同步 1422 / 终态 1422」成了新的不实宣称**。修复轮改了 README（且因 `test_v2_readme_claims.py` ±20 窗在上限，不改即红），但**未同步回填台账**（台账 mtime 03:56:58 < 修复轮 04:12+，`grep 1445` 在 docs/ 台账内零命中）。
- 判据：上一轮 PM 的口径 = 「台账说同步就必须真同步」（本报告 §2.1 已逐字核过 README 侧）；台账「同步 1422」的说法与磁盘不符 → 该条不闭环。同族前例（R4-BL-1/BL-4 台账滞后、PM-1 B-2）均按**阻塞**处置，标准一致。
- 最小处置：台账计数沿革 `:5/:17/:29/:59` 回填为 1445（或改口径），与 README 双侧对齐。

## 三、B-2b（`.gitignore` 缺 `.pytest-tmp-*`）· 复跑核证 → **闭环**

- 规则在盘：`.gitignore:32-33`（注释「测试临时目录（--basetemp 唯一纪律…）」+ `.pytest-tmp-*`）。
- **反证（仓根造目录）**：`mkdir .pytest-tmp-probe && echo probe > .pytest-tmp-probe/probe.file` → `git status --porcelain` 对其**零可见**（grep 退出码 1）；`git check-ignore -v` = `.gitignore:33:.pytest-tmp-*	.pytest-tmp-probe/probe.file`；`git status --porcelain --ignored` 显示 `!! .pytest-tmp-probe/` → 目录已造、被忽略、随即 `rm -rf` 删除（事后 `git status` 零命中）。
- **敏感性对照（防假绿）**：同法造 `.pytest-tmpX-probe/`（不匹配 `-` 后缀）→ `?? .pytest-tmpX-probe/` **可见** → 规则真生效、非「空目录天然不可见」的假通过。已删。
- 主树写入披露：本次核证含**唯一一次主树写操作**（上述两个探针目录，造后即删，均为 ignored/即刻清理状态）；除此之外主树零改动。

## 四、全量回归（唯一一次，复制品）

- 命令：`cd /tmp/m6pm2-copy && <主树 venv>/python -m pytest -q --basetemp=/tmp/m6pm2-pytest-51286 -p no:cacheprovider`（复制品内跑；主树只读）
- 结果：**1445 collected / 1444 passed / 1 failed**，用时 343.81s（输出 `/tmp/m6pm2-run/pytest-full.log`；`pytest exit=1`）
- 唯一失败 = `tests/unit/test_v2_servable.py::test_ops_lock_dir_ignores_cwd`（`:161`），断言原文：`assert a == b, f"锁目录随 cwd 漂移：{a} != {b}"` → `…/m6pm2-copy/data/ops-locks != …/Model-Gateway/data/ops-locks`
- **机理复核（两点直接实验，不采信报告）**：同一探针（打印 `ops_lock_dir()`）以 `env -i PATH/HOME + PYTHONDONTWRITEBYTECODE=1` 四面跑：
  A `cwd=复制品` → `/private/tmp/m6pm2-copy/data/ops-locks`；B `cwd=/tmp` → 主树路径（editable `.pth` 兜底）；
  C `cwd=主树` → 主树；D `cwd=/tmp` → 主树 → **单树形态两侧同值 ⇒ 该条即绿**。
  ⇒ 失败 = 复制品双树伪红（父进程解析复制品、子进程经主树 `.pth` 解析主树），与 PM-1 判定同源同机理、本轮**直接复现**。按机理单树 = **1445/1445**（未在主树跑全量，纪律）。
- 修复轮 23 条新测试**定向复跑**：`tests/integration/test_accounts_models_api.py`（9）+ `test_m6_a1_wiring.py`（2）+ `test_m6_panel_fixes.py`（6）+ `tests/unit/test_ops_panel_fixes.py`（6）→ **23 passed**（10.49s，`--basetemp=/tmp/m6pm2-fixfiles`）。README 计数判据（±20 窗）在 1445==1445 下绿。

## 五、未验证 / 说明

- 台账历史计数 835/996/1221/1304/1371 无盘上产物，仍属自述；本轮只核终值。
- 复制品形态的 `test_ops_lock_dir_ignores_cwd`：**本轮已直接复现并复核**（A/B 异值、C/D 同值，见 §4）→ 判为环境伪红，不计入真红。
- 台账侧遗留（§2.2）：至本报告落盘，台账 mtime 仍 = 03:56:58（`stat` 复核），未被修复轮或本轮回填 → B-2a 阻塞依据。
- 主树写入披露：除本报告外，仅 §3 的两个探针目录（造后即删）；复核期 `git status --porcelain` 与基线**逐行一致**（113 行，零漂移），HEAD 仍 `5158cbc`。
- 真实凭据登录/领取仍「未实测」（U1 同 §22.11），本轮全假凭据零触网。
- README 计数判据自身保留 ±20 容差（既存设计，PM-1 已记）；本报告的核证不依赖该容差（逐字比对）。

## 附：本次独立证据清单（主树外）

| 证据 | 路径 |
|---|---|
| 实例 A 四态 + 拒绝面 + 视图（原始响应） | `/tmp/m6pm2-run/evidence/live-states.json` |
| 变体 B 未接线 / 抛错 / 旗标 | `/tmp/m6pm2-run/evidence/mut-states.json` |
| CDP 真机断言（8/8）+ 弹窗截图 | `/tmp/m6pm2-run/evidence/ui-check.json`、`pm2-models-modal.png` |
| 探针源码（独立编写） | `/tmp/m6pm2-run/probe_models.py`、`probe_mut.py`、`ui_check.py` |
| 复制品 / 变体 | `/tmp/m6pm2-copy`、`/tmp/m6pm2-mut`（实例日志 `server.log`） |
| 全量 pytest 输出 | `/tmp/m6pm2-run/pytest-full.log` |
