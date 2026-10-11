# PM 验收 · 第四轮（2026-09-27）

> 角色：产品经理（为用户会撞上的"看不懂的死路"负责）
> 依据：`docs/specs/tech-design.md` v2.0 §12–§21（尤其 §17 / §21.2 / §20 / §19 M5-x）、`docs/specs/prd.md` v1.15（Q25–Q28）
> 被审对象：`docs/changes/e2e-records/E2E-20260927-round4-fixes.md`（下称"账本"）
> 方法：**不复述账本**，本轮每一项由我本人跑命令/渲染源码函数复现用户实际看到的输出；只读，未改任何源码
> 复现沙箱：`MG_CONFIG=/tmp/pm-r4/*/config.yaml` + `MGW_ZCODE_ACCOUNTS=/tmp/pm-r4/zcode/accounts`（不触碰 `data/`、不触碰用户真实 `~/.workbuddy*`，写入类一律 `--dry-run` 或 pty 重定向到 /tmp）

---

## 1. 一句话结论

**有条件通过**：四处 §21.2 出口契约、Q28-② 的"过滤必附解释"、T9b 的"三态可分辨"经我实测**确实成立**（原谎报已根治）；但 **IX-2 的"手动解除熔断"出口是一句印给用户、实测不生效的谎**，且熔断**发生那一刻**的界面原因串不含方案要求的恢复时刻、熔断轮次会静默抹掉顶栏红点、额度/熔断到期后界面长期停在「cooldown + 剩余 —」。共 **1 严重 / 5 中 / 5 轻**，另附 8 条撤修复要求（其中 4 条我实测**当前没有任何判据会变红**）。

---

## 2. 判定表（本轮修复项 → 判定 → 证据）

| # | 修复项（方案/账本口径） | 判定 | 证据（本会话实测） |
|---|---|---|---|
| §21.2① | 零映射告警进 `overview.warnings[]` + 双通道（界面横幅 + 启动日志） | **通过** | 真网关（uvicorn:18321）`GET /admin/api/overview` → `warnings` 含 `model_without_resource` + `model_unservable`；启动日志同刻打印两行 `[配置告警] …`；横幅渲染由 `node scripts/verify_v2_frontend.mjs` A1~A14 实测 14/14 绿。落点 `api/admin.py:168`、`main.py:250-316`、`dashboard.js:65` |
| §21.2② | 运营 `failed` → jsonl + CLI 打印 + **顶栏红点** | **不通过** | 红点数据源存在（`admin.py:121 ops_failed_unread`、`main.js:100`、`index.html:109 #ops-dot`），但：**CLI 进程内的失败永远点不亮红点**（`bump_failed_counter` 只在 `main.py:_run` 的 cron 腿调用），且 `cli_zcode.py:268` 无条件 `_ack_failures()` → 实测 **未读 7 → 0**（该轮 CLI 只打印了熔断警告，从未展示那 7 条）。见缺陷 M3 |
| §21.2③ | 设备 ID 冲突 → 3 个显式选项 + 默认取消 + 非 0 + **不写盘** | **通过** | 实跑 `mgw zcode import y.json`（与已导入 acct-X 同 `MID-SHARED-001`）→ 逐字打印 ①②③、`rc=4`；随后 `ls accounts` **只有 acct-X**（`store.py:167` 在 `_commit` 之前 return） |
| §21.2④ | `mgw setup` 写前打印解析路径并确认 | **通过** | pty 驱动：答 `n` → `已取消`、`rc=1`、目标目录 `[]`（空）；答 `y` → `✓ 已写入 /tmp/pm-r4/wb-dir/models.json（1 条，新增 1）`。顺序为 `cli_setup.py:84` 打印 → `:126` 计划 → `:138` 确认 → `:145` 写入 |
| Q28-② | `/v1/models` 与 `mgw setup` 只下发可服务模型 | **通过** | 真网关：`curl -H "Bearer <对>"` → `ids: ['ok-model']`；`empty-model`（无映射）与 `dead-model`（映射指向停用资源）被隐藏；`res-z` 正在风控冷却但 `ok-model` **仍在清单**（临时态不隐藏，符合 Q28-② 判据）；匿名 → `HTTP 401` |
| Q28-② 配套 | 被隐藏模型必须逐条解释，不许只过滤 | **界面通过 / CLI 不通过** | 界面：`overview.warnings` 两类分开、各自点名模型并各自指对页面（我实测的 payload 见 §3-M5）。CLI：`mgw setup` 把两类合并成一句「已跳过 2 个无可用资源的模型（empty-model、dead-model）—— 到「模型资源」页为它们添加映射」，对 `dead-model` 是错的指路。见缺陷 M5 |
| T9b | 判定依据必须说真话，三态可分辨 | **通过** | 三种真实状态各跑一次 `mgw setup --dry-run`：① 无监听 → `本地配置 · 原因：网关未运行（连接被拒）`；② 网关在跑但密钥错 → `原因：网关在运行但拒绝了接入密钥（401：密钥已停用或删除）`；③ 端口黑洞（listen 不 accept）→ `原因：网关无响应（超时）`；④ 正确密钥 → `运行中网关的 /v1/models（1 个模型可服务，含运行态）`。落点 `local_admin.py:51 REASONS` / `:61 admin_get_detail`、`cli_setup.py:98-110` |
| IX-2 界面 | 重启后（circuit.json 剩 19min）用户看得见原因 | **通过** | 真网关启动 + 真 `circuit.json`（until=+19min）→ 启动日志 `[熔断对齐] 全局风控仍在生效，已 bench 1 个资源（…至 23:47）`；`overview.resources[0] = {"status":"cooldown","cooldown_remaining_ms":1699575,"last_error":"ZCode 风控熔断（30min，全局），至 23:47"}`；总览指标卡 `dashboard.js:17` 显示「1 资源冷却中」。落点 `quota.py:511 sync_circuit_to_runtime` + `main.py:83/458` |
| IX-2 文案（恢复时刻） | §17 字面 `…（30min，至 HH:MM）` 要出现在「最近错误」 | **不通过（仅重启路径成立）** | 同一进程内走**真实接线点** `zcode_claim._handle_risk_control(runtime,…)`（cron 与 `/admin/api/zcode/bench` 调的都是它）→ `overview` 给出 `"last_error": "ZCode 风控熔断（30min，全局）"`（**无 `至 HH:MM`**），而文件里的 reason 是 `…，至 00:04`。原因：`:118/:121` 传的是 `GLOBAL_BENCH_REASON` 常量而非 `circuit.reason()`。见缺陷 M-S2 与 §4-1 |
| IX-2 CLI | 熔断中不得打印"全部正常"、退出码非 0、给状态文件路径 | **部分通过** | 有凭据账号：`⚠ …，至 00:06 —— 本轮未对上游发起任何领取` + `状态文件：/tmp/pm-r4/zcode/circuit.json（等待自动到期，或删除该文件以提前解除）`，`rc=3`，无"全部正常" ✓。但无凭据账号同屏出现 `✗ 失败 1 个：acct-pm 凭据缺失` 且 **`rc=1`**（退出码 3 被吞）；另 `– 跳过 1 个（无资格 1）` 是错的归因。见缺陷 M1/M2 |
| IX-2 手动出口 | 删除 `circuit.json` 可提前解除（账本 D3） | **不通过（严重）** | 实测：同进程 `enter()` → `active=True` → `path.unlink()` → **`active=True`、`left_minutes=30`**；新建实例（=重启）才 `False`。根因 `quota.py:377-382` `_load()` 把 `FileNotFoundError`(OSError) 吞成"保持内存态"。且 `clear()` 已删（已核实 `quota.py` 内无 `def clear`）、管理端只有加 bench 的 `admin.py:393`，界面无解除入口。见缺陷 S1 |
| IX-4 | 徽章不得把冷却/失效都渲染成「停用」 | **通过** | 用 **node 直接执行 `dashboard.js` 里的真实 `statusBadge`/`resourceHealthTable`**：active→`b-ok active`、cooldown→`b-cool title="剩余 1139s"`、invalid→`b-err invalid`、disabled→`b-muted title="资源开关已关闭" 停用`；`invalid` 态非死 UI（`scheduler.py:408,683` 调 `invalidate()`）。前端门 C1~C7 全绿；IX-4 回归变异（插回 `available===false`）实测杀掉 C2,C3,C5,C6,C7 + 连带 C4 = 6 条，与账本 §二-6 的"6 条"一致 |
| M5-3/§17 额度 | 上游报 0 → 必须看得见原因 | **通过** | 真 `apply_snapshot_to_runtime(remaining=0)` → `{"status":"cooldown","cooldown_remaining_ms":59997,"last_error":"ZCode 额度耗尽"}`，时长 = 一个刷新周期（`quota.py:290-306`） |
| 额度 | 上游恢复 → 无需人工干预自动回池 | **机制通过 / 呈现不通过** | 池确实回到 `remaining=8`、一次 `pick_and_acquire` 即选中该资源（自动回池 ✓，无第二本账）；但**同一时刻**（无流量）`overview` 仍报 `{"status":"cooldown","cooldown_remaining_ms":0,"last_error":"ZCode 额度耗尽"}` —— 冷却是懒恢复（`resources.py:246` 只在选路时翻转），`snapshot_by_resource` 不做到期判定，`note_success` 不清 `last_error`。见缺陷 M4 |
| 额度模型（无第二本账） | 撤单调守卫/结算扣减 | **通过** | `resources.py:32-56` `QuotaPool.__slots__=("remaining","reserved")`，全包无 `used` 字段；`test_snapshot_is_the_single_authority` 用 `assert mgr.set_quota(s,5) is True`（守卫会返回 False）+ `pick is not None` 双向钉死，属真机制判据 |
| 账本 §一 全部 `file:line` 引用 | 逐条复算 | **通过（19/19 未失效）** | `sed -n <L>p` 逐条打印：`resources.py:32/169/198/291/303/318/326/349`、`quota.py:265/297/335/407/511`、`captcha.py:88`、`local_admin.py:51/61`、`cli_setup.py:100/108`、`main.py:83/458`、`cli_zcode.py:231/236/269`、`dashboard.js:110`、`matcher.py:43/270`、`admin.py:606`、`runner.py:86` 全部命中账本所述内容 |
| 删除类声明 | `quota_view()` / `CooldownManager.clear()` / `local_admin.admin_get` / `tempfile` 导入 | **通过（确已删，非"改名藏起来"）** | `grep` 全包无 `quota_view`、无 `def clear`、`local_admin.py` 只剩 `admin_post`/`admin_get_detail`；`runner.py:19-31` 无 `import tempfile` |
| 机械门（本轮口径） | 633 pytest / 前端 46 项 / 变异 37/37 | **通过（我本会话重跑）** | `pytest -q --basetemp=/tmp/mgw-pytest-pm-full` → **633 passed in 86.04s**；`verify_v2_frontend.mjs` → **实测 46 项，失败 0 项**；`--mutation` → **可红 37/37；每条断言都有对应变异**；指定三文件 → **29 passed** |
| 范围纪律 | 是否自创 §20 之外的表面 | **基本通过（2 处越界需登记）** | 退出码 3 已登记 D4 ✓；`mgw zcode launch` 有 `19` §6.1「数据根 + 启动」依据；但 `mgw zcode remove` 属"为死符号补用户表面"、§19 M5-0 只列 `login/import/list/claim` → 应在偏离表登记；未发现违反 §20 不做清单的新增 |

---

## 3. 新发现缺陷（按 严重 / 中 / 轻）

### 🔴 严重

**S1 · 熔断的"手动解除"出口是印给用户的谎：删除 `circuit.json` 在运行中的网关里根本不生效**

- 用户在哪一步看到什么：用户在 23:18 命中 3012，跑 `mgw zcode claim`，屏幕告诉他
  `状态文件：…/circuit.json（等待自动到期，或**删除该文件以提前解除**）`。他删了。文件确实没了。
  然后再跑 → **仍然** `⚠ … 本轮未对上游发起任何领取`，再等 28 分钟也没动静；他没有任何线索知道"要重启才生效"。
- 根因：`quota.py:377-382` `_load()` 在 `self.path.stat()` 抛 `FileNotFoundError`（`OSError` 子类）时 `return`，**保留内存 `_cd`**；只有全新进程才会得到"没熔断"的默认态。
- 实测（本会话）：
  ```
  circuit_path = /tmp/pm-r4/zcode/circuit.json
  enter 后 active = True  reason = ZCode 风控熔断（30min，全局），至 00:15
  → 用户按 CLI 提示删掉状态文件之后
     active = True （同一进程 = 运行中的网关）   left_minutes = 30
     新进程读到吗？ active = False
  ```
- 为什么不可接受：这是账本 **D3 删除 `CooldownManager.clear()` 之后留下的唯一手动出口**，而 D3 的正当性依据（§14「手改本地文件是受支持路径」）成立的前提是**那条路径真能被感知**——配置文件的先例靠 `mtime 热重载`，熔断文件恰好**没有**"消失也算变更"的读取逻辑。同时 `admin.py:393` 只有"加 bench"、没有解除端点、界面无入口（`grep 解除|冷却 js/pages/resources.js` 无命中）。
- 处理建议（三选一，**须由用户裁决**，属产品口径不是实现细节）：
  ①  `_load()` 见文件不存在即归零内存态（最小改动、与文案一致）；
  ② 恢复显式出口：`POST /admin/api/zcode/circuit/clear` + `mgw zcode claim --clear-circuit`（§21.2 的"CLI 打印 + 端点"范式已有先例：`/ops/ack`、`/dialects/reload`）；
  ③  只改文案为「删除该文件**并重启网关**」——但这是把 30 分钟的风控观察期问题转嫁成重启成本，我不推荐默认走这条。

### 🟠 中

**M1 · 熔断中 `mgw zcode claim` 照跑整轮批量：同屏既说"未对上游发起任何领取"又报 `✗ 失败`、退出码退回 1**

- 用户看到：
  ```
  ⚠ ZCode 风控熔断（30min，全局），至 00:06 —— 本轮未对上游发起任何领取
      状态文件：/tmp/pm-r4/zcode/circuit.json（…）
  ✗ 失败 1 个：
      acct-pm  凭据缺失（先 `mgw zcode login` 或 `mgw zcode import`）
  EXIT=1
  ```
  实测命令：`MG_CONFIG=/tmp/pm-r4/claim/config.yaml MGW_ZCODE_ACCOUNTS=… python -m model_gateway.cli zcode claim`
- 机制：`cli_zcode.py:231` 只是**读**了 `circuit.active()` 用于打印，`:232` 仍无条件 `await run_once(...)`；上游挡板在 `zcode_claim.claim()` 里且位于凭据检查**之后**（`:96-100` 先 `凭据缺失` → 才 `:102 _circuit_gate`），于是"没打上游"为真、却产出了 failed；`cli_zcode.py:258-264` 的 `return 1` 抢在 `:269 return 3` 之前。
- 坏结果：账本 D4 新增退出码 3 的全部意义是"脚本能区分'本轮一次都没打'与'打了但有失败'"，这条区分在**凭据不齐**（用户接入初期最常见）的状态下失效；用户也无法从输出判断这轮到底跑没跑。

**M2 · 熔断中的账号在 CLI 上被归因为「无资格」，真实原因（剩余 N 分钟）只活在从未打印的 `detail` 里**

- 用户看到（账号凭据齐全时）：
  ```
  ⚠ ZCode 风控熔断（30min，全局），至 23:47 —— 本轮未对上游发起任何领取
      状态文件：/tmp/pm-r4/zcode/circuit.json（…）
  – 跳过 1 个（无资格 1）
  ```
- 机制：`zcode_claim.py:130-137 _circuit_gate` 把熔断分类为 `inactive` 并把"剩余约 N 分钟"写进 `detail`，其 docstring 自己写明「**必须在 detail 里给出剩余时间，否则用户只看到"跳过"却不知道被什么挡住**」；而 `cli_zcode.py:247-254` 对 `inactive` **只打印计数**、从不打印 detail（只有 `failed` 才逐条打原因）。
- 坏结果：§16.2 的 `inactive` = "账号无资格（业务态）"，用户据此去查账号资格/活动是否结束，而真凶是网关自己的风控；这正是 §21.3 原则 3 要消灭的"把两种状态混成一条"。

**M3 · 一次什么都没做（或只跑了本地判定）的 CLI 轮次，会把用户从未看过的历史失败红点清零**

- 实测：网关侧预置 `ops_failed_unread = 7`（模拟 cron 留下的 7 条未读失败）→ 在熔断中跑 `mgw zcode claim` → 打印 `CLI 后：未读失败 = 0`。CLI 屏幕上**从未出现那 7 条**。
- 机制：`cli_zcode.py:268` 无条件调用 `_ack_failures()` → `POST /admin/api/ops/ack`；而 §21.2② 要求的另一腿"**CLI 失败点亮顶栏红点**"结构性缺失 —— `bump_failed_counter` 只在 `main.py:_run`（cron 腿，`runtime` 非空）被调，`run_once(runtime=None)` 的 CLI 进程无处可加。
- 坏结果：红点是用户**无人值守时唯一的失败信号**（cron 在后台跑）；用户在终端敲一次 claim（哪怕本轮被熔断短路）就把它抹掉，且再也找不回那批失败的时间点（只能去翻 `data/usage/ops-results-*.jsonl`，而那正是红点 toast 才告诉他的路径）。

**M4 · 熔断/额度到期后，资源早已回池，界面却长期显示「cooldown + 冷却剩余 — + 最近错误 依旧写着旧原因」**

- 实测（额度场景，`claim_interval_seconds=1` → bench 时长 5s）：
  ```
  T0  上游=0        → {"status":"cooldown","cooldown_remaining_ms":4997,"last_error":"ZCode 额度耗尽"}
  T+6s 上游已恢复=8 → {"status":"cooldown","cooldown_remaining_ms":   0,"last_error":"ZCode 额度耗尽"}  池= QuotaPool(remaining=8)
        一次真实选路 → ZCode资源（= 其实早就可用）
        选路后界面   → {"status":"active", … , "last_error":"ZCode 额度耗尽"}
  ```
- 机制：冷却到期是**懒恢复**，全项目唯一翻转点在 `resources.py:246`（`pick_and_acquire` 内），`snapshot_by_resource`（`:349`）不做到期判定；`note_success`（`:331`）只清 `C`、不清 `last_error`。
- 坏结果：用户看到的是一行自相矛盾的状态（"冷却中"却"剩余 —"，且原因还是早已过去的 额度耗尽/风控熔断）。低频模型可以在这行挂几小时几天。这直接侵蚀本轮 IX-2/IX-4 想建立的"界面状态可信"，用户会去手动关开资源开关或删熔断文件（进而撞上 S1）。3012 到期同样受影响（`sync_circuit` 只在启动跑一次）。

**M5 · `mgw setup` 对"被隐藏的模型"给了一句合并的、且指错页的解释**

- 实测输出：
  ```
  已跳过 2 个无可用资源的模型（empty-model、dead-model）—— 到「模型资源」页为它们添加映射
  ```
  而 `dead-model` 的映射**本来就存在**（指向被停用的 `res-d`），真动作是"启用该资源"；`empty-model` 才是"添加映射"，且总览横幅已经正确地把添加映射指到「资源池设置」页。
- 机制：`cli_setup.py:116-121` 只算了一个 `hidden` 集合、套一句文案；界面侧 `main.py:264-300` 已经按 `model_without_resource` / `model_unservable` 分开说明并各指对页。
- 坏结果：CLI 是"文件下发"这一路径的唯一说明出口。用户到「模型资源」页找不到"为系统模型添加映射"的动作（那页是 Key/映射管理，添加映射在「资源池设置」的资源池区，`models.js:290`），或去"添加"一个已存在的映射；这正是 Q28-②「不允许只过滤不解释」想要避免的第二轮误导。

### 🟡 轻

**L1 · 状态徽章同一列中英文混排**：`active`/`cooldown`/`invalid` 直接吐后端枚举字面，唯独 `disabled` 显示「停用」（`dashboard.js:110-122`，实测渲染见 §2 表）。"多久恢复"只在 hover `title` 里；「冷却剩余」列单位是**秒**（19 分钟显示 `1139s`）。整站其余为中文，且 `cooldown_remaining_ms` 需 hover 才知语义 —— 与 `frontend-spec.md:403` 并不冲突，但对中文用户是新坏味道。

**L2 · 退出码语义没有任何用户可见文档**：`cli_zcode.py:220-222` 的 0/1/2/3 只在源码注释里；`README*.md:94-101`、`mgw zcode claim --help` 均未提"D4 新增的 3 = 熔断中未执行"。账本 D4 的正当性（脚本可区分）在文档缺失下打折。

**L3 · 变异自证在"渲染抛错"时是推定而非实测**：`verify_v2_frontend.mjs` `runMutations` 的 `catch` 分支把 `red = mut.kills` 直接当作"已变红"（本轮命中 1 条：`非数组 warnings 不做类型兜底 [抛错 TypeError]`）。整体仍是加严，但这类"能红"没有逐条证据。

**L4 · 界面文案与 §21.2 字面漂移且未登记**：方案 §21.2 出口①第②类字面写「到「**模型资源**」页编辑资源添加映射」，实装为「到「**资源池设置**」页…添加资源映射」（`main.py:269-272`）。实装指路**更准**（映射在 models 页资源池区添加），但属于对方案字面的背离，账本 §三 偏离表（D1–D5）没有登记它 —— 铁律 4 要求逐条交代。

**L5 · `mgw setup` 连续两行给出不同数字**：`将写入：models.json（1 条系统模型）` 紧跟 `[dry-run] 将写入 2 条（新增 1）`（`cli_setup.py:126` vs `setup_tools.py:160` 的合并语义）。两者都对（后者含既有条目），但没解释差异，用户会怀疑写漏或写重。

**L6 · 三态可分辨里只有两态被测试钉住**：`timeout` 分支（`local_admin.py:85`）**没有任何判据**触达（`test_int_v2_setup_live.py` 覆盖 not-running 与 401；`test_reasons_table_covers_every_documented_reason` 只查 `REASONS` 字典键）。删掉该分支后 `TimeoutError` 会被 `:87 except OSError` 吞成 `not-running` —— 也就是把 T9b 的原谎换一种触发条件复活，而 29 条测试全绿。（我本会话用黑洞监听实测到了正确文案，属**人工**证据，非门。）

---

## 4. 要求主 agent 执行的「撤修复红证清单」

> 规则：逐条施加、跑指定判据、把结果贴回第五轮账本。**凡"撤掉后 0 条变红"的，即本轮红证不成立**，必须补判据；我已标 ✔=我已确认能红 / ✘=我预判不会红（须补测）。

| # | 改哪一行 → 改成什么 | 期望变红的判据 | 我的预判 |
|---|---|---|---|
| 1 | `ops/builtin/zcode_claim.py:118` `zq.bench_all_zcode(runtime, reason=GLOBAL_BENCH_REASON)` → `reason=zq.get_circuit().reason()`；同步 `:121-122` admin_post 的 `"reason"` | **当前无任何判据变红**；同时 `tests/unit/test_v2_circuit.py:172 assert benched == [zcode_claim.GLOBAL_BENCH_REASON]` **会红** —— 该断言现在钉的是缺陷 | ✘ 必须先改判据为「回写原因含 `至 HH:MM` 且与 `circuit.reason()` 同源」，并新增 `apply_to_resource → snapshot_by_resource()[0]["last_error"]` 含「至 」的判据 |
| 2 | `core/local_admin.py:85-86` 删除 `except TimeoutError: return None, "timeout"` 整支 | 预判 `tests/integration/test_int_v2_setup_live.py` 5 条 + `tests/unit/test_v2_cli.py` **全绿** | ✘ 需新增：黑洞监听（`bind+listen` 不 accept）→ `mgw setup` 输出含「超时」且不含「未运行」 |
| 3 | `core/resources.py:246` 删掉懒恢复两行（`if r.status=="cooldown" and now>=r.cooldown_until: r.status="active"`） | 应红：`tests/unit/test_v2_quota_reservation.py::test_exhaustion_bench_lasts_one_refresh_cycle_and_self_heals` **不会红**（它只断言"不续期"） | ✘ 需新增：bench 到期后（无流量）`snapshot_by_resource` 必须报 `status != "cooldown"` 或 `cooldown_remaining_ms>0` 二者取一为真，禁止「cooldown + 0ms」共存（我的 M4 复现脚本可直接改造成判据） |
| 4 | `upstream/zcode/quota.py:381` `except (OSError, ValueError): return` → 文件不存在时 `self._cd = Cooldown(); self._loaded_mtime=None; return`（**反向**：先补判据，再要求现行为变红） | 现判据无一覆盖"运行中删除文件" | ✘ 需新增：`cm.enter(); path.unlink(); assert cm.active() is False`（或改文案 + 判据断言文案含「重启」）—— 否则 S1 永久复发 |
| 5 | `cli_zcode.py:232` `report = await run_once(...)` → `if breakered: report = OpReport(); report.no_participants=False` 之类的短路 | `test_claim_under_global_breaker_exits_3` 仍绿（它用的是**有凭据**账号） | ✘ 需新增：「无凭据账号 + 熔断中 → `rc==3` 且 stdout 不含 `✗ 失败`」判据（对应 M1） |
| 6 | `cli_zcode.py:268` 删 `_ack_failures()` | 无任何判据断言"熔断轮次不得清零历史未读失败" | ✘ 需新增集成判据：预置 `runtime.ops_failed_unread=7` → CLI 熔断轮 → `GET /admin/api/status` 仍为 7；同时明确 CLI 侧失败如何点亮红点（M3） |
| 7 | `zcode_claim.py:135` 把 `inactive` 分类改为 `skipped`（或把 `detail` 打进 CLI） | `test_claim_skipped_while_circuit_active`（`test_v2_circuit.py:137-146`）会红 ✔ —— 它断言 `res.category=="inactive"` 且 detail 含"熔断/分钟" | ✔ 机制判据存在；但**呈现层**无判据：需加一条 `capsys` 断言 stdout 含「熔断」而非「无资格」（M2） |
| 8 | `cli_setup.py:119-121` 合并文案 → 按 `kind` 分两句（无映射 / 映射全不可用，分别指「资源池设置」/「模型资源」） | 现有 `test_setup_without_running_gateway_says_it_is_config_only` 只断言 `"已跳过" not in out`，对混合场景**无判据** | ✘ 需新增：`empty-model` 行含「资源池设置」、`dead-model` 行含「启用」/「模型资源」，且不得对已存在映射说"添加映射"（M5） |
| 9 | `dashboard.js:113` `case "cooldown"` 的 `title="剩余 …s"` 删掉 | 前端门 C6 红 ✔ | ✔ 已确认（`--mutation` 表内「cooldown 不再给剩余秒数」） |
| 10 | `quota.py:415` 去掉 `，至 {_hhmm(…)}` | 账本称 4 条红（unit `test_enter_reason_carries_the_recovery_clock` / CLI / boot 集成 / …）—— 我核对了 `test_v2_circuit.py:266-278`、`test_v2_cli_zcode.py:222` 附近、`test_int_v2_circuit_boot.py:52` 三处**确实**依赖该串 | ✔ 成立，**但**注意第 1 条：这条红证不能覆盖 `_handle_risk_control`，两者互不替代（我在 §2/M-S2 已实测出差异） |

> 另：账本 §二-6 声称 IX-4 兜底插回使「前端门 6 条红（C2~C7）」—— 我用 `--mutation` 实跑复核为 **C2,C3,C5,C6,C7 指定 + C4 连带 = 6 条**，条数与口径一致，**不属虚报**。

---

## 5. 未验证清单（我未能自证的部分，一律不写成"已实现"）

| # | 项 | 状态 |
|---|---|---|
| U1 | 总览横幅 / 顶栏红点在**真实浏览器**里的渲染与显隐 | **未验证**。`verify_v2_frontend.mjs` 的 A/B/C/D 是"node 执行真实渲染函数拿 HTML"（可信），E/F/G/H 是**源码文本契约**（`includes`），红点从未被驱动过；本轮我未跑 `ui_verify_v2_visible.py`（按指示避免共享 /tmp 竞争）。账本 §一-10 已自我声明"前端半按源码契约断言"，我不把它当行为证据 |
| U2 | 真实 3012 风控命中（真上游 + 住宅代理） | **未验证**。本轮所有熔断均经 `enter()`/`circuit.json` 注入，路径与文案等价，但"上游真的回 3012"依赖 `docs/research/19` 的 T5a/T5b |
| U3 | WorkBuddy 真读 `models.json` 后选中模型 | **未验证**（§19 M3-5 本就标手工，且受工具登录态阻塞，Q25-⑩ 不代登录） |
| U4 | 验证码求解器（Playwright + 代理）真实过关 | **未验证**。我只复核 `captcha.py:88` 单一异常类、`_build_client` 注入求解器的**装配**判据存在（`test_client_is_always_assembled_with_a_solver`，断言真 solver 类型） |
| U5 | `启动网关.command` 正常路径（nohup + 自动关窗）下用户确实看到横幅 | **部分验证**：我验证了 `overview.warnings` 与启动日志双通道都产出；**未验证**真实双击 `.command` 后的窗口/浏览器时序 |
| U6 | 撤修复红证的完整复跑 | **未验证**：我不能改源码，账本 §二 的 16 行撤修复只复核了前端 6 条（实测）与 #1/#2/#3/#5/#7/#9/#10 的**判据体**；其余撤修复（额度守卫、`_pool_for`、`matcher tool_call`、`admin.py:606`、`fallback_lock_dir`、`apply_to_resource`）我只做了"测试体是否真依赖该机制"的静态判定，未实跑 |
| U7 | 熔断对齐在**无 ZCode 账号但 circuit.json 存在**时的表现 | **未验证**（`bench_all_zcode` 走 `zcode_account_names()`，无账号即 0 条 bench；此时 `sync_circuit` 返回 0、启动日志不打 `[熔断对齐]`——是否算"资源仍在打上游"要看 `resource_ids_of_account` 能否命中备注，我没构造这组数据） |

---

### 附：本会话实测用到的命令（可复跑；全部只读源码、写入仅在 /tmp）

```
node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json            # 46/46 绿
node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json --mutation  # 37/37 可红
.venv/bin/python -m pytest tests/integration/test_int_v2_circuit_boot.py \
    tests/integration/test_int_v2_setup_live.py tests/unit/test_v2_cli_zcode.py \
    -q --basetemp=/tmp/mgw-pytest-pm -p no:warnings                              # 29 passed
.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest-pm-full -p no:warnings  # 633 passed in 86.04s
MG_CONFIG=/tmp/pm-r4/{off,bad,hang,gw}/config.yaml … cli setup workbuddy --dry-run  # 三态判定依据
MG_CONFIG=… MGW_ZCODE_ACCOUNTS=… cli zcode claim                                  # rc=3 / rc=1 两情形
MGW_ZCODE_ACCOUNTS=/tmp/pm-r4/imp/accounts cli zcode import {x,y}.json            # 冲突：rc=4 + 不写盘
```
