# M6 交付面板 · eng-a-2（复验角色 · 独立评审）

> 角色：eng-a-2（对上一轮 eng-a A-1/A-2/A-3 与 eng-b F1/F2/F3 的**复验**，独立评审，非实现方）
> 对象：M6 面板修复轮-2（含 `*_async` 接线补齐）；上一轮报告 `m6-panel-eng-a.md` / `m6-panel-eng-b.md`；
> 台账 `docs/changes/e2e-records/E2E-20260930-M6-multi-product.md`。
> 纪律：/tmp 复制品工作（主树只读）；**唯一仓库写入 = 本文件**；`--basetemp=/tmp/m6ea2-*` + `-p no:cacheprovider`；
> 不碰 `data/`、`:8300`、真实上游。**先建后增量写**。
> 状态：**已完成**（2026-09-30 05:2x CST；HEAD `5158cbc` + M6 工作树增量）

## 进展记录

- [x] 环境快照（HEAD = 5158cbc + M6 增量；复制品 8 个关键文件 sha256 与主树逐字节一致）
- [x] A-1 端到端：自写探针（并发 admin 写 + 心跳 <50ms）+ 撤 async 红证 → **真闭环**（§1）
- [x] A-2 单桥接：唯一实现（对象级同一）+ 两调用点动态穿越 + 差异场景逐字段一致（§2.1）
- [x] A-3 zcode_claim 传输 True / 非传输 False；业务码不重试；与 7 产品同一把尺（§2.2）
- [x] F1 空 base_url / 构造失败 → 不进 /v1/models + 横幅（+ 撤修复红证）（§3.1）
- [x] F2 load_enum_pool 抛错 → 不半应用 + 横幅（+ 撤修复红证）（§3.2）
- [x] F3 假上游回显 Key → 事件/日志/响应体零明文（+ 撤脱敏红证）（§4）
- [x] 全量 pytest 回归（复制品）：1445 collected / 1444 passed / 1 已自证伪红（§5）
- [x] 结论：**通过 · 阻塞 0**（§7；3 条非阻塞登记）

> **结论一句话**：eng-a A-1/A-2/A-3 与 eng-b F1/F2/F3 六条**全部真闭环**（绿→红→绿双向自证），
> 阻塞 0，非阻塞登记 3 条。

## 0. 环境与方法

| 项 | 事实 |
|---|---|
| 主树 | HEAD = `5158cbc`（工作树含全部 M6 未提交增量，与两轮面板同一树，评审开始/结束主树零写入） |
| 复制品 | `/tmp/m6ea2-repo`（`rsync -a` 自主树，排除 `data/`、`.git/`、`.venv/`、`__pycache__/`、`.pytest_cache/`）；`python -c "import model_gateway"`（cwd=复制品）= `/private/tmp/m6ea2-repo/...` |
| 关键文件 sha256 前 12 位（复制品 == 主树） | `main.py 355c548bca74` / `accounts/store.py 5521122df6d8` / `accounts/login.py e01fb1e237f0` / `api/admin_accounts.py d8a448698bfb` / `ops/bridge.py 5a964656f249` / `ops/builtin/zcode_claim.py 6e4261adf46b` / `stats/events.py 5bb59bceedab` / `core/errors.py 554915a2d6a5` |
| 解释器 | 主树 `.venv/bin/python`（复制品 cwd + `PYTHONPATH=/tmp/m6ea2-repo` 下 import 落复制品） |
| 运行数据 | 全部 `/tmp/m6ea2-rt1` / `rt2` / `rt3*`（**不是**主树 `data/`）；`:8300` 零触碰；真实上游零调用 |
| 变异纪律 | 复制品内改文件前先备份到 `/tmp/m6ea2-probe/backup_*`；恢复后与主树 sha256 逐字节比对（见 §1.3） |

## 1. A-1（锁等待不阻塞事件循环）复验 —— **真闭环**

**独立方法**（不复用修复者用例 `tests/integration/test_m6_a1_wiring.py`）：自写两个探针，
持锁者 = **真实子进程**（`/tmp/m6ea2-probe/lock_holder.py` 走生产 `_AccountsWriteLock`
真持 `<data>/locks/accounts.lock` 2.2~2.5s，pid 真活），不写"假 pid=1 锁文件"。

### 1.1 探针一：HTTP 端到端（`/tmp/m6ea2-probe/a1_http_probe.py`）

真 uvicorn（复制品代码，随机端口）+ 真子进程持锁；写请求 = `POST /admin/api/accounts/buddy/a1-acc/disable`
（`_set_enabled` → `commit_login_async`），心跳 = `GET /health` 背靠背连打。

| 副本状态 | 写请求 | 心跳（持锁窗口内） | 裁决 |
|---|---|---|---|
| **绿（接线版）** | 500 `WriteLockError … 已等待 1s`，**1016ms**（确实打满锁预算 = 真走到等锁路径） | **max 3.76ms** / 2490 拍（基线 ~0.5ms） | 事件循环未被停摆 ✓ |
| **红（撤接线：`await store.commit_login_async(` → `store.commit_login(`，2 处）** | 500，1023ms | **max 964.28ms** / **仅 1 拍**（整段窗口被冻住） | 复现 eng-a 的 ~1s 阻塞 ✓ |
| **恢复绿** | 500，1024ms | **max 1.27ms** / 2528 拍 | 恢复后回到毫秒级 ✓ |

旁证：持锁期间被拒写的账号 `enabled` 仍为 `true`（拒写 = 零落字节）；持锁释放后同端点
`disable` 200/6.2ms、`enable` 200/4.4ms（脚本收尾真跑）。

### 1.2 探针二：`login.py` 通道（`/tmp/m6ea2-probe/a1_login_probe.py`）

协程里 `await login._commit_outcome(session, outcome)`（poll/callback/alt 三通道**共用实现**），
同时 10ms 打点任务量事件循环间隔；另一进程真持锁。

| 副本状态 | 等锁总耗时 | 事件循环最大间隔 | 裁决 |
|---|---|---|---|
| **绿（接线版）** | 1012.6ms（WriteLockError 拒写，未落盘） | **12.2ms**（89 拍） | 等锁在工作线程 ✓ |
| **红（撤接线 1 处）** | 1021.9ms | **1032.4ms**（**仅 1 拍**） | 停摆 ~1s 红证成立 ✓ |
| **恢复绿** | 1009.3ms | **12.1ms** | ✓ |

### 1.3 红线与恢复核证

- 两文件撤接线共 5 处（admin_accounts 4 + login 1，与 `test_m6_a1_wiring.py` 的 AST 判据
  期望数一致）；撤后 `grep "await store.*_async"` 两文件零残留。
- 恢复：`cp` 回备份 → sha256 前 12 位 `d8a448698bfb` / `e01fb1e237f0`，与主树**逐字节一致**。

### 1.4 裁决

**A-1 真闭环**（绿 <50ms → 撤接线红 ~1s → 恢复绿，三态双向可复现；HTTP 与 login 两条生产
异步路径分别独立复现）。eng-a 的"字面从严则升格阻塞"条件不再存在。

⚠️ 低度观察（非阻塞，附证据）：`_commit_outcome` 的 `except (CommitError, ValueError, OSError)`
**不含 `WriteLockError`**（后者继承 `Exception`，`store.py:82`）→ 拒写时异常原样上抛（HTTP 层
500 可读文案；探针实测 `outcome.state` 停在 `"success"`）。对用户"不是谎报"（请求明确失败），
但"落盘失败 → 状态翻 failed"这句只在自检失败一档成立。登记备查，不构成阻塞。

### 1.5 接线完整性（除两处撤线点外的旁证）

全包 grep `commit_login|import_account|delete_account` 调用点（去注释/定义）：
异步服务面只有 `accounts/login.py:344`（async）与 `api/admin_accounts.py:289/519/631/743`（async）；
`cli_zcode.py:168,194` 是 CLI 同步面（独立进程，正确用同步版）；
`upstream/zcode/store.py:217` 的 `delete_account` 委托仅被 CLI 调用；`api/admin.py:442` 的 zstore
用法是 `list_accounts`/读快照（只读）。**无第三个异步残留点**。

## 2. A-2（单桥接）/ A-3（retryable 口径）复验 —— **真闭环**

### 2.1 A-2 单一桥接

**静态（全仓 grep，`model_gateway/`）**：`outcome.category` / `outcome.retryable` 只出现在
`ops/bridge.py:42-44`（唯一实现）；桥接引用只有两处调用点 ——
`ops/builtin/product_claim.py:135`（`bridge.outcome_to_op_result`）与
`api/admin_accounts.py:89 import + :595 调用`。**无第二份归一化规则**。

**动态（自写 `a2_a3_probe.py`；in-process 双路径 + ASGI 端点半开通）**：

- 对象级同一：`admin_accounts.outcome_to_op_result is bridge.outcome_to_op_result` → **True**
  （`__module__ = model_gateway.ops.bridge`），即两处消费点执行的是**同一个函数对象**；
- 穿越证明：把两处入口都换成 recorder（真正执行原函数）后，路径 A（`product_claim.claim`）
  与路径 B（`POST /admin/api/accounts/buddy/acc-a2/claim` → `_claim_once`）**每次都命中**
  （`hook_saw_outcome=True`）；
- 差异场景（eng-a A-5 点名的"两路输入"）逐字段比对：

  | 输入（同一 `ClaimOutcome`） | 路径 A（ops） | 路径 B（admin 端点） | 一致 |
  |---|---|---|---|
  | `failed + retryable=True` | `(failed, True, "network: ConnectError")` | `(failed, True, 同)` | ✓ |
  | **`already_done + retryable=True`（历史分叉点）** | `(already_done, None, …)` | `(already_done, None, …)` | ✓（旧实现此处一 None 一 True） |
  | `success + retryable=True` | `(success, None, …)` | `(success, None, …)` | ✓ |
  | `failed + retryable=False` | `(failed, False, …)` | `(failed, False, …)` | ✓ |
  | 非 `ClaimOutcome`（垃圾对象） | `(failed, None, "…类型异常…")` | `(failed, None, "…类型异常…")` | ✓ |

  → **两处输出逐字段一致**（含 detail）；A-5 双账风险消解。

### 2.2 A-3 retryable 口径（zcode vs 7 产品）

**代码落点**：`ops/builtin/zcode_claim.py:233`（`retryable = product_hooks.is_transport_failure(e)`）；
判据本体 `ops/builtin/product_hooks.py:33-36`（`httpx.HTTPError` + `OSError`，含 `__cause__` 链）；
7 产品同类折叠点见 `product_claim.py:125`、`query_balance.py:86` 与 6 个 upstream 折叠点
（`upstream/buddy/hooks.py:308,323`、`lobsterai/claim.py:95,123,206`、`qoder/flow.py:648,681`
（qodercn 同族 `flow.py` 承用）、`trae/claim.py:205`、`loomy/credits.py:234,314,343`、
`raccoon/credits.py:154`）。

**动态实测（`zcode_claim.claim` 假客户端注入，凭据走 stub）**：

| 输入 | zcode 输出 | 7 产品（同异常类走 `product_claim`） | 一致 |
|---|---|---|---|
| 业务码失败（未知码 9999 / 1002） | `failed` / `inactive`，**不重试** | 业务折叠 `retryable=False`，不重试 | ✓（生效判据见下） |
| `httpx.ConnectError` | `failed, retryable=True` | `failed, retryable=True` | ✓ |
| `httpx.ReadTimeout` / `TimeoutError(OSError)` | `True` | 同类判据 | ✓ |
| `ValueError`（非传输） | **`False`**（修复前为 blanket `True`） | `False` | ✓ |
| `RuntimeError(__cause__=ConnectError)` | `True` | 同类判据 | ✓ |

**生效判据**（行为层面的"不重试"）：`runner._retryable_of` 实测 —
zcode 业务码（`None`→前缀回退）→ `False`；7 产品业务折叠（结构化 `False`）→ `False`；
两条传输路径 → `True`。**同一把尺成立**。

**撤修复红证**：把 `zcode_claim.py:233-236` 换回旧 blanket 形态（`retryable=True` + `network:` 前缀）→
重跑探针：`ValueError` 变为 `retryable=True`、`detail="network: ValueError: 解析失败"`（**复现 A-3 原文**）；
恢复后 `ValueError → False`（sha256 `6e4261adf46b` == 主树）。

⚠️ 低度观察（非阻塞）：zcode **业务码**失败走 `classify()` 出口（`OpResult(..., retryable=None)`）
而非结构化 `False`（7 产品是 `False`）—— 生效判据相同（None→前缀回退→不重试），但字段语义
"未声明"与"明确不重试"仍有区别；若业务失败文案以 `network:` 开头会被误判重试（探索未发现
现有生产路径会产出这种文案）。登记备查。

## 3. eng-b F1 / F2 复验 —— **真闭环**

探针：`/tmp/m6ea2-probe/f1_f2_probe.py`（in-process `create_app` + `httpx.ASGITransport`，
无端口；与 eng-b 的"真 uvicorn 子进程"方法独立）。

### 3.1 F1（适配器缺口 → 不进 `/v1/models` + 横幅）

配置：`res-good`（正常）/ `res-empty`（`base_url=""`）/ `res-ghost`（`product=ghostproduct` 未登记）；
三条启用映射 `m-good` / `m-empty` / `m-ghost`。

| 观察 | 实测 |
|---|---|
| `GET /v1/models` | **`["m-good"]`** —— `m-empty`/`m-ghost` 不再对外声明（eng-b 红证里两条都在清单里） |
| `runtime.config_warnings()` | `resource_adapter_unbuilt` 一条，点名两资源与成因：`空地址资源（base_url 未配置（出站地址为空））`、`幽灵资源（出站适配器构造失败（KeyError: "未登记的产品 'ghostproduct'（在册：…）"））`，并写明 `其映射的 2 个系统模型已从 /v1/models 与 mgw setup 隐藏（m-empty、m-ghost）` |
| `GET /admin/api/overview` | `warnings` 同一条（UI 横幅出口 ✓） |
| 直调被隐藏模型 | 503 + **成因如实**：`资源 '空地址资源' 无可用出站适配器（base_url 未配置或出站装配失败）—— 见总览页配置告警横幅`（原"protocol 未实现"错归因已消失） |

**撤修复红证**（复制品内把 `Runtime._unservable_reason` 撤成"只返回前提缺口"= 退回 F1 前的判据面）：
`/v1/models` 回到 **`["m-empty","m-ghost","m-good"]`**（eng-b 红态逐条复现）；横幅仍在，但**丢失**
"其映射的 2 个系统模型已从 /v1/models … 隐藏（m-empty、m-ghost）"一段（`assembly_hidden` 变空）
—— 证明"隐藏"与"点名去向"两半同由该判据驱动。恢复后 sha256 `355c548bca74` == 主树，绿态复跑一致。

### 3.2 F2（`_apply` 前置步骤失败 → 不半应用 + 横幅）

探针注入 `model_gateway.main.load_enum_pool` 抛 `RuntimeError`（等价 eng-b 的 ParserError），
随后写新配置（+`m-new`）并 `await runtime.reload_from_file()`：

| 观察 | 实测 |
|---|---|
| 返回值 | `(False, ["RuntimeError: 模拟 model-enums.yaml 损坏：ParserError（探针注入）"])` |
| 运行态代次 | `config 同代=True`、`adapters 同代=True`、`key_values 同代=True`、**`half_applied=False`**（eng-b 半应用症状消失） |
| `/v1/models` | 仍 `["m-good"]`（坏配置下不虚报新模型） |
| 横幅 | `hot_reload_failed`：`最近一次配置热重载失败：RuntimeError: … —— 运行态仍是上一代（已生效的模型/资源未变）；修正该文件后再次保存配置即可重试` |
| 自愈 | 解除注入后再存一次 → `(True, [])`，`m-new` 生效（`/v1/models = ["m-good","m-new"]`），横幅消失 |

**撤修复红证**（复刻旧序）：复制品里 `_apply` 把 `self.config = config` 挪到 `load_enum_pool` 之前
+ `reload_from_file` 不再写 `_apply_error` → 重跑探针：**`half_applied=True`**（config 有 `m-new`、
adapters 仍是旧代）、`/v1/models` 出现 `m-new`、警告里**没有** `hot_reload_failed`
（= eng-b F2"半应用 + 零横幅"逐条复现）。恢复后 sha256 `355c548bca74` == 主树，绿态复跑一致。

## 4. eng-b F3 复验（凭据回显脱敏） —— **真闭环**

探针：`/tmp/m6ea2-probe/f3_probe.py`。假上游（本进程线程）把收到的 `Authorization` 原样回显进
401 错误体（`Bearer <key>` 与裸 Key 两种形态都写）；网关资源 Key 特意用**无 `sk-` 前缀**的
`F3P-a1b2c3d4e5f60718293a4b5c`（≥8 位 → 只可能命中 Bearer 形态规则 + 装配侧字面值登记表）。

| 面 | 绿（接线版） | 撤脱敏红证（`scrub_upstream_text` 头部 `return text`） |
|---|---|---|
| 响应体（401 透传） | **零明文**；掩码形态 `F3P****4b5c` 在（`plain=False, auth=False, masked=True`） | `plain_key=True, auth_value=True`（逐字回显） |
| 事件 JSONL（`usage/events-*.jsonl`） | **零明文**；`error_summary` 与 `resource_attempts[].errors[]` 均为 `Bearer F3P****4b5c; raw key F3P****4b5c` | `plain_key=True, auth_value=True` |
| 切换事件 JSONL | 掩码命中、零明文 | （同上族） |
| 网关日志 | 零明文（该 401 日志行不含错误体） | 零明文（日志本就不带 body） |
| 全 RT 目录扫描 | 除 `config.yaml` 本身（明文配置 = 铁律 1 的设计）外**零命中** | —— |

恢复后 sha256 `554915a2d6a5` == 主树；绿态复跑一致。

⚠️ 低度观察（非阻塞，F1 边界）：横幅文案"已从 /v1/models 与 mgw setup 隐藏"在**网关运行时**
成立（`mgw setup` 优先读运行中 `/v1/models`，`cli_setup.py:143-148`）；**网关不可达**时 CLI 降级到
`servable_models(config)`（**无 registry 注入**，`cli_setup.py:43`）→ 实测该降级档会把
`m-empty`/`m-ghost` 一并写进 models.json（本角色 in-process 复现：`['m-good','m-new','m-empty','m-ghost']`）。
与 F-5（前提缺口）**同一性质**（判据都在运行态注入），且 CLI 在降级时会打印明示
"⚠ 未取到运行态，清单可能含已不可服务的模型"（`cli_setup.py:182-184`）—— 不构成阻塞，登记备查。

## 5. 全量 pytest 回归（复制品）

命令：`cd /tmp/m6ea2-repo && .venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=/tmp/m6ea2-bt`
（`PYTHONDONTWRITEBYTECODE=1`；主树零写入）。`--collect-only` = **1445 collected**（与 README/README.zh-CN
的双语徽章 + 正文 "1445/1445" 同数）。

**结果：`1 failed, 1444 passed, 345.32s`**（跑批 05:14–05:20）。

唯一失败 `tests/unit/test_v2_servable.py::test_ops_lock_dir_ignores_cwd` —— **独立复证为
"复制品两棵树"环境伪影，非产品缺陷**（不复用前两位评审的结论，自证如下）：

1. 机制（我自己跑出的证据，只读、非 pytest）：venv 的 editable `.pth` 内容 = 主树绝对路径
   （`/Users/w/Desktop/Model-Gateway`）。用例以 `env={"PATH","HOME"}` 起子进程（无 `PYTHONPATH`/
   `MG_CONFIG`）、`cwd` 两处（复制品根 / tmp）：
   ```
   cwd=replica -> /private/tmp/m6ea2-repo/data/ops-locks
   cwd=/tmp     -> /Users/w/Desktop/Model-Gateway/data/ops-locks
   ```
   前者经 `sys.path[0]=cwd` 导入复制品、后者经 `.pth` 导入主树 → 两棵树各报自己的 repo 根。
2. **前提在主树成立**（同命令、只读）：`cwd=主树` 与 `cwd=/tmp` **均输出**
   `/Users/w/Desktop/Model-Gateway/data/ops-locks`（单 checkout 下 a == b，断言不红）。
3. 该用例主题（`ops_lock_dir()` 与 cwd 无关，`runner.py:80-88`）与本轮修复面无关；
   其余 1444 条（含新增 `tests/integration/test_m6_a1_wiring.py`、
   `tests/unit/test_ops_panel_fixes.py`、`test_m6_servable_*` 等修复轮-2 用例）全绿。

→ 净结果：**0 真红**；台账/README 的 "1445" 口径与磁盘一致。

## 6. 探针/证据清单（全部可复跑）

| 文件 | 用途 |
|---|---|
| `/tmp/m6ea2-probe/lock_holder.py` | 真实子进程持账号写锁 N 秒 |
| `/tmp/m6ea2-probe/a1_http_probe.py` | A-1 HTTP：并发 admin 写 + 心跳延迟（绿/红/恢复三态） |
| `/tmp/m6ea2-probe/a1_login_probe.py` | A-1 login 通道：`_commit_outcome` 打点间隔 |
| `/tmp/m6ea2-probe/a2_a3_probe.py` | A-2 双路径逐字段一致 + A-3 retryable 口径 |
| `/tmp/m6ea2-probe/f1_f2_probe.py` | F1 可服务集/横幅 + F2 半应用/横幅/自愈 |
| `/tmp/m6ea2-probe/f3_probe.py` | F3 三面明文扫描 |
| `/tmp/m6ea2-probe/*_{green,green2,red}*.json`、`pytest-full.log` | 三态原始输出与全量跑批日志 |
| `/tmp/m6ea2-probe/gw_*.log`、`/tmp/m6ea2-rt{1..5}/` | 网关日志与运行数据（全在 /tmp） |
| 复制品 | `/tmp/m6ea2-repo`（与主树 `diff -rq model_gateway tests` **零差异**） |

## 7. 结论

> ### **通过 · 阻塞 0**
>
> 六条待复验项（eng-a A-1/A-2/A-3 + eng-b F1/F2/F3）**全部真闭环**，且每条都有我自己的
> 「绿 →（撤修复）红 → 恢复绿」双向证据（A-2 为结构 + 两路径逐字段一致性，
> 以"对象级同一 + 历史分叉场景"替代撤修复概念）。复制品与主树 `diff -rq` 零差异；
> 全量 pytest 1445 collected / 1444 passed + 1 条已自证伪红（两棵树伪影）。

| # | 复验项 | 我的复跑（自写探针） | 裁决 |
|---|---|---|---|
| A-1 | 锁等待不阻塞事件循环 | `a1_http_probe.py`（真 uvicorn + 真子进程持锁）：心跳 max **3.76ms/2490 拍**（写请求真等满 1016ms）；撤 5 处 `await *_async` → **964.28ms/仅 1 拍**；恢复 → **1.27ms**。`a1_login_probe.py`（`_commit_outcome`）：**12.2ms → 1032.4ms/1 拍 → 12.1ms** | ✅ 真闭环 |
| A-2 | `ClaimOutcome→OpResult` 单桥接 | 全仓 grep：归一化规则只在 `ops/bridge.py:42-44`；`admin_accounts.outcome_to_op_result is bridge.outcome_to_op_result` = **True**；两路径 5 组输入（含历史分叉 `already_done+retryable=True`）**逐字段一致** | ✅ 真闭环 |
| A-3 | zcode retryable 与 7 产品同一把尺 | 传输类（ConnectError/ReadTimeout/TimeoutError/`__cause__` 包装）→ **True**；`ValueError` → **False**；业务码 → 不重试（`_retryable_of` 实测 False，7 产品同）；撤回 blanket → `ValueError=True` 红证 | ✅ 真闭环（1 条低度字段语义观察） |
| F1 | 空 base_url / 构造失败不进 `/v1/models` + 横幅 | `/v1/models` 只剩 `m-good`；`resource_adapter_unbuilt` 横幅点名两资源与成因、点名被隐藏模型；overview 同源；直调 503 成因如实；撤 F1 判据 → 两模型回清单 + 横幅丢失"已隐藏"段红证 | ✅ 真闭环 |
| F2 | 前置步骤失败不半应用 + 横幅 | 注入 `load_enum_pool` 抛错 → `(False, …)`、config/adapters/key_values **同代**、`half_applied=False`、`hot_reload_failed` 横幅；修复后自愈；撤回旧序 → `half_applied=True` + 零横幅红证 | ✅ 真闭环 |
| F3 | 凭据回显三处零明文 | 假上游回显（Bearer + 裸 Key）：响应体 / 事件 JSONL / 日志**零明文**、掩码 `F3P****4b5c` 在；撤 `scrub_upstream_text` → 响应体与事件明文红证；全 RT 扫描除 config 本体零命中 | ✅ 真闭环 |

**非阻塞登记（3 条，均附证据；不改变"通过"）**：
1. `_commit_outcome` 的 except 不含 `WriteLockError`（拒写时 `outcome.state` 停在 `success`，
   异常上抛为 HTTP 500）—— 对用户不谎报（请求明确失败），但 docstring 的"落盘失败 → failed"
   只覆盖自检失败一档（§1.4）。
2. zcode 业务码失败 `retryable=None`（未声明）vs 7 产品结构化 `False` —— 生效判据一致
   （前缀回退 → 不重试），字段语义有差（§2.2）。
3. 横幅"已从 mgw setup 隐藏"在**网关不可达**的降级档不成立（`servable_models(config)` 无
   registry 注入）—— CLI 自带明示提醒，且与 F-5 同性质（§4 尾部）。

## 8. 未验证（本轮边界）

1. 真实凭据 / 真实上游（§22.11 全档）：本轮一律假 uvicorn / 假上游 / 假客户端，未触网。
2. 前端面（账号接入页 DOM / 双主题）不在本角色职责内。
3. `mgw setup` 真机写盘路径未跑（避免触碰真实工具目录）；只做了 in-process
   `build_cli_models` 判据面（§4 尾部的降级档观察来自它）。
4. 长跑类（锁等待分布、会话滞留上界）未做压测——A-1 只复现了"持锁者僵死一档 ≤1.0s"的边界。


