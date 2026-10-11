# E2E · 第四轮返工账本（2026-09-27）

> 依据：第三轮三角色验收（`docs/changes/reviews/{PM,eng,ix}-accept-3.md`）+ 用户指令
> 「继续，做完一个然后自验收，有问题就改再自验收，完全验收通过后进行开发下一。按照此模式直至全部开发完毕。」
>
> **本轮的元规则（比修了什么更重要）**：一条断言如果撤掉修复后不会变红，它就不算证据。
> 本轮**每个**修复都做了"撤修复 → 跑 → 记条数"的红证，且新写的前端门带 `--mutation` 自证模式。
>
> 本轮结束时机械门（同一次运行，全部实测于 2026-09-27）：
> - `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest` → **633 passed**（第三轮末 603 → +30）
> - `node scripts/verify_v2_frontend.mjs <overview>` → **实测 46 项，失败 0 项**
> - 同脚本 `--mutation` → **可红 37/37；每条断言都有对应变异**
> - `.venv/bin/python scripts/ui_verify_v2_visible.py --mutation` → 后端出口 **12/12**，前端 46 项 + 37 变异全过

---

## 一、逐项修复与红证

### 🔴 1 额度模型改为「上游快照唯一权威」（我自己上一轮引入的两个更坏的洞）

| 项 | 内容 |
|---|---|
| 依据 | eng 验收严重 ①②：我上轮加的 `set_quota` 单调守卫 + `settle_quota` 累加 `used`，比原缺陷更坏 |
| 落点 | `model_gateway/core/resources.py:32`（`QuotaPool` 只剩 `remaining`/`reserved`）、`:291 set_quota`、`:303 reserve_quota`、`:318 settle_quota`、`:326 release_quota`；`model_gateway/upstream/zcode/quota.py:265 apply_snapshot_to_runtime` |
| 机制 | `remaining` = 上游快照余量（**直接覆盖，不做"只准变小"守卫**）；`reserved` = 在飞预留，只挡并发；结算**不动** `remaining`（本地不伪造消耗） |
| 红证 | 撤 `set_quota` 守卫无法复现"充值被永久拒绝"（`applied=False`、remaining 恒 0）——该行为已由 `test_snapshot_is_the_single_authority` 反向钉死；撤 `settle_quota` 的"只清预留"会复活已消耗单位（上轮实测 8→10） |
| 判据 | `tests/unit/test_v2_quota_reservation.py`（29 条，含 `test_snapshot_is_the_single_authority` / `test_successive_settles_do_not_drain_the_snapshot` / `test_inflight_reservations_gate_admission_even_with_a_stale_large_snapshot`） |

### 🔴 2 `rebuild()` 的额度接线：撤掉死行 + 补真红证（eng-④）

| 项 | 内容 |
|---|---|
| 发现 | 上轮账本写「`rebuild()` 里的 `state.quota = _pool_for(rid)` 需要一条红证」。**实测撤掉该行 → 625 条全绿** → 它是**不可达防御代码**（复用态的 `state.quota` 必然已是同一实例：池只在无任何存活状态时回收）→ **删除**，并按 §20 记为"不写不可能发生的兜底" |
| 真正的接线 | `model_gateway/core/resources.py:198`（`ResourceState(..., quota=self._pool_for(ref.resource))`）与 `:169 _pool_for` |
| 红证 | 撤 `:198` → **3 条判据同时变红**：`test_rebuild_shares_one_pool_across_mappings_of_the_same_resource` / `test_rebuild_twice_does_not_reset_the_snapshot_authority` / `test_rebuild_recycles_the_pool_when_the_resource_loses_all_references`（此前只有 1 条 query_balance 用例能捕获） |

### 🔴 3 `CaptchaUnavailable` 单一类 + 判据走**真实求解器**（不再是手搓异常）

| 项 | 内容 |
|---|---|
| 落点 | `model_gateway/upstream/zcode/captcha.py:88`（`from …claim import CaptchaUnavailable`，异常类全包只有一份） |
| 判据 | `tests/unit/test_v2_claim_wiring.py`（14 条）：新增 4 条**不注入假 claim、不自造异常**——只把 HTTP 边界换成假上游，装配（`ops/builtin/zcode_claim.py:140 _build_client`）与求解器（`captcha.get_solver`）走真的 |
| 红证 A | 让 `captcha.py` 重新定义同名类 → **2 条变红**，且实测 `previews == 3`（正是原缺陷：一次配置问题被退避重试三轮、三次真打 preview） |
| 红证 B | 撤 `_build_client` 的 `captcha_solver=` 注入 → **2 条变红**（文案变成"求解器未接入（装配错误）"） |
| 红证 C | `test_batch_executor_does_not_retry_a_captcha_failure` 断言 `_run_one` 后 `previews == 1` 且 `slept == []`（一次都没睡） |

### 🔴 4 T9b：`mgw setup` 的运行态取数被 401 挡住且谎报"网关未运行"

| 项 | 内容 |
|---|---|
| 根因 | `/v1/*` 在 `AuthMiddleware` 之后（豁免只有 `/health`、`/admin/`），CLI 发的是匿名请求 → 401 → `admin_get` 只返回 `None` → 打印"网关未运行" |
| 落点 | `model_gateway/core/local_admin.py:61 admin_get_detail`（返回 `(数据, 原因)`，原因 ∈ `:51 REASONS`：`ok`/`not-running`/`timeout`/`unauthorized`/`forbidden`/`bad-json`/`http-<code>`）；`model_gateway/cli_setup.py:100`（带 `Authorization: Bearer <接入密钥>`）、`:108`（降级时把**真实原因**写进判定依据行） |
| 判据 | 新建 `tests/integration/test_int_v2_setup_live.py`（5 条，**不桩 `admin_get`**：真 uvicorn + 真鉴权中间件 + 真 urllib） |
| 红证 | ① 撤 Bearer 头 → `test_setup_reads_live_models_through_auth` 红（实测打印"本地配置 · 原因：网关在运行但拒绝了接入密钥（401…）"）；② 把 `HTTPError` 吞成 `not-running` → 2 条红；③ **正向对照**：把 `/v1/models` 加进豁免前缀 → 2 条红（防其余用例因前提消失而集体空过） |
| 顺带 | 旧单测里 `monkeypatch.setattr(la, "admin_get", …)` 的**自证式桩**被删除，改为 `test_cli_models_hide_what_the_gateway_cannot_serve`（纯机制判据 + "给不给 servable 结论必须不同"的判别式） |

### 🔴 5 IX-2：全局熔断的可见性与 CLI 诚实性（§17 的出口真正生效）

| 项 | 内容 |
|---|---|
| 5a 文案 | `quota.py:335 _hhmm` + `CooldownManager.enter`（`:407`）→ 原因串按 §17 字面带恢复时刻：`ZCode 风控熔断（30min，全局），至 23:18` |
| 5b 重启对齐 | 新增 `quota.py:511 sync_circuit_to_runtime`（熔断剩余时长 = 资源冷却时长）+ `main.py:83 sync_circuit` 包装，`:458` 在 startup 事件里调用（**独立于运营调度是否启动**） |
| 5c CLI | `cli_zcode.py:231 breakered = circuit.active()` → `:236` 打印"本轮未对上游发起任何领取"+状态文件路径；`:269` 熔断时**不打印**"全部正常"且**退出码 3**（新增语义：0 正常 / 1 有失败 / 2 无账号参与 / 3 熔断中未执行） |
| 5d 删除 | `CooldownManager.clear()` **删除**（无生产调用点；方案未定义"手动解除"出口，加一个等于自创 §21 之外的表面）→ 手动出口 = CLI 打印的状态文件路径（`circuit.json`），方案 §14 已确立"手改本地文件是受支持路径" |
| 红证 | 撤 5a → 4 条红（unit + CLI + 启动集成）；撤 5b 的 startup 调用 → `tests/integration/test_int_v2_circuit_boot.py::test_startup_rebenches_resources_while_breaker_is_active` 红（该文件另有**正向对照**：无落盘熔断时启动不得凭空 bench）；撤 5c 防护 → `test_claim_under_global_breaker_exits_3` 红；把对齐时长写死 30min → `test_sync_circuit_cooldown_matches_remaining_time` 红 |

### 🔴 6 IX-4：`statusBadge` 用 `available===false` 兜底，把冷却/失效说成「停用」

| 项 | 内容 |
|---|---|
| 根因 | 后端 `available = status == "active"` → 任何非 active 都落进第一行，返回「停用 + Key 或所属产品已停用」；判据只能是 `status`（后端已聚合成 disabled/invalid/cooldown/active 四态，`core/resources.py:349 snapshot_by_resource`） |
| 落点 | `model_gateway/web/static/js/pages/dashboard.js:110 statusBadge` 改为按 `r.status` 四分支 + 兜底原样显示 |
| 判据 | `verify_v2_frontend.mjs` 新增 C1~C7（四态**类名与文案都互不相同**、cooldown 带剩余秒数、disabled 提示必须是"资源开关"、未知状态不静默归正） |
| 红证 | 变异模式：把旧的那行兜底插回去 → C2/C3/C4/C5/C6/C7 **全部变红**；且该回归被 `tests/integration/test_int_v2_frontend_gate.py` 捕获（实测 46 项中 6 项红） |

### 🟠 7 P3-2：`tool_call` 的覆写通道断在加载器里

| 项 | 内容 |
|---|---|
| 落点 | `enums/matcher.py:270`（`load_enum_pool` 读 `tool_call`）、`matcher.py:43 __post_init__`（非 `chat` 端点恒 `false` 的不变量，内置目录与用户 YAML 同受约束）、`api/admin.py:606`（`PUT /admin/api/enums` 读回该键） |
| 判据 | `tests/unit/test_v2_capabilities.py`（22 条）+ `tests/integration/test_int_v2_capabilities.py`（19 条）新增 YAML 覆写、images 族不声称支持、`images + tool_call: true` 被归一、**枚举池 GET→改→PUT→再 GET 与 `/v1/models` 三处同结论** |
| 红证 | 撤 `matcher.py:270` → 2 条红（含集成往返）；撤 `__post_init__` → 2 条红；撤 `admin.py:606` → 1 条红 |
| 需求侧 | 对 §12.3「默认 `False`」的**有意背离**已写入 PRD **Q28-⑤**（含实测理由与两条约束） |

### 🟠 8 eng-⑤：退路锁目录随 `TMPDIR` 漂移

| 项 | 内容 |
|---|---|
| 根因 | `fallback_lock_dir()` 用 `tempfile.gettempdir()` → 读 `TMPDIR`；macOS 下 GUI 会话与 shell 的 `TMPDIR` 常不同 → 网关进程与 CLI 进程**各退到不同目录各自加锁**，互斥恰好在最需要它的退路分支失效 |
| 落点 | `model_gateway/ops/runner.py:86 fallback_lock_dir()` 改为固定 `/tmp/mgw-ops-locks-<uid>`（并删掉不再使用的 `tempfile` 导入） |
| 判据 | `tests/unit/test_v2_ops.py::test_fallback_lock_dir_is_independent_of_tmpdir`（两个 `TMPDIR` 取值必须同目录 + 目录确实可写） |
| 红证 | 改回 `gettempdir()` → 该条红 |

### 🟠 9 §17 的另一半：额度耗尽必须同时写 `status` / `last_error`

| 项 | 内容 |
|---|---|
| 落点 | `quota.py:265 apply_snapshot_to_runtime`：`remaining == 0` 时对这批 rid `apply_to_resource(..., reason=QUOTA_EXHAUSTED_REASON, seconds=_quota_refresh_seconds(runtime))`（`:297`，时长 = 一个额度刷新周期，充值后下一次 tick 自动回池） |
| 判据 | `tests/unit/test_v2_quota_reservation.py` 新增 4 条：耗尽必 bench 且原因串 = §17 字面 `ZCode 额度耗尽`；有余量**不得** bench（正向对照）；快照未知**不得** bench；冷却时长 ≤ 一个刷新周期 |
| 红证 | 撤那次 `apply_to_resource` → 2 条红 |

### 🟠 10 IX-5：前端断言**全部**经变异证明能红

| 项 | 内容 |
|---|---|
| 落点 | `scripts/verify_v2_frontend.mjs` 重写为「`runChecks()` + `MUTATIONS` + `--mutation`」；`scripts/ui_verify_v2_visible.py` 加 `--mutation` 透传，并**改掉了它自我吹嘘的覆盖范围**（原文声称在浏览器里验证红点显隐，实际从未驱动浏览器 → 现写明"前端半按源码契约断言"并删掉无用的 `CHROME` 常量） |
| 结构 | 46 条断言 / 37 个源码变异；变异施加在**临时副本**上（不碰工作树）；锚点命中数 ≠ 1 直接判红（防"锚点过期 = 假通过"）；**基线不干净就不许跑变异**（否则"变红"无法归因）；未被任何变异覆盖的断言 → 判失败 |
| 本轮抓出的 4 类假绿 | ① 负向断言只扫 `main.js`，`index.html` 红点 `title="…查看详情"` 在判据外（已改文案 + 新增 E4）；② `python -m model_gateway.cli` 之类"指路"断言用 `includes` 扫全文，注释里提一句也算绿（现锚到具体句子）；③ 熔断行判据与 `last_error` 渲染分处两文件、改一边不影响另一边；④ 列数判据把 `<thead>` 算成一列（`<th` 前缀）→ 恒多算一列，`每行 6 单元格` 这种写死数字一旦加列就永远对不上（改为 `<th[ >]` 且与 `<td>` 数动态比较） |
| 门的位置 | 新增 `tests/integration/test_int_v2_frontend_gate.py`（2 条）：用**生产装配**造 overview 后跑 `node …`，实测模式与变异模式各一条，并断言"断言总数 ≥ 40 / 变异总数 ≥ 30"（防门被悄悄删窄）；无 `node` 时 skip 并说明 |

### 🟡 11 接线护栏扩展到**类方法**

| 项 | 内容 |
|---|---|
| 落点 | `tests/unit/test_v2_wiring_guard.py::_public_symbols` 现在同时导出模块级符号与类的公开方法（跳过 `_`、property/staticmethod/classmethod、框架隐式钩子） |
| 结果 | 全集从 ~60 涨到含方法后**只报出 1 个**新死符号：`ResourceManager.quota_view()`（我为"诊断"自创、无人调用）→ **删除**，4 处测试改为直接读 `state.quota.remaining/reserved` |
| 顺带 | 同轮 `local_admin.admin_get` 因改判据而失去引用 → 护栏**当场报错**（`无生产引用的符号：admin_get`），我据此删除而非加白名单 —— 这是该护栏第一次替我挡住"兼容壳" |

---

## 二、撤修复红证总表（本轮全部实测）

| # | 撤掉的修复 | 变红的判据 | 条数 |
|---|---|---|---|
| 3A | `CaptchaUnavailable` 恢复成两个类 | `test_solver_reason_reaches_the_user_verbatim`、`test_batch_executor_does_not_retry_a_captcha_failure`（且实测 `previews=3`） | 2 |
| 3B | `_build_client` 不注入求解器 | `test_client_is_always_assembled_with_a_solver`、`test_solver_reason_reaches_the_user_verbatim` | 2 |
| 4-① | `mgw setup` 不发 Bearer | `test_setup_reads_live_models_through_auth` | 1 |
| 4-② | 401 被吞成"未运行" | `test_models_endpoint_rejects_anonymous`、`test_setup_on_wrong_token_says_401_not_not_running` | 2 |
| 4-③ | `/v1/models` 进鉴权豁免（前提被拆） | 同上 2 条 | 2 |
| 5a | 文案去掉"至 HH:MM" | unit×2 + CLI×1 + 启动集成×1 | 4 |
| 5b | startup 不调 `sync_circuit` | `test_startup_rebenches_resources_while_breaker_is_active` | 1 |
| 5c | 熔断时仍打印"全部正常"/退出码 0 | `test_claim_under_global_breaker_exits_3` | 1 |
| 5d | 对齐时长写死 30min | `test_sync_circuit_cooldown_matches_remaining_time` | 1 |
| 2 | 撤 `rebuild()` 的 `quota=_pool_for` | 3 条 rebuild 级判据 | 3 |
| 7-① | 加载器不读 `tool_call` | YAML 覆写 + 枚举池往返 | 2 |
| 7-② | 去掉非 chat 不变量 | images 族不声称 + 强制归一 | 2 |
| 7-③ | `PUT /admin/api/enums` 不读回 | 枚举池往返 | 1 |
| 8 | 退路目录改回 `gettempdir()` | TMPDIR 独立性 | 1 |
| 9 | 额度耗尽不写状态 | 2 条 | 2 |
| 6 | 插回 `available===false` 兜底 | 前端门 6 条红（C2~C7）→ pytest 集成门失败 | 6 |
| 10 | （由 `--mutation` 逐条施加） | 37/37 变异各自打红指定断言 | — |

---

## 三、偏离方案之处（逐条交代，不含"顺手优化"）

| # | 偏离 | 依据与判断 |
|---|---|---|
| D1 | `EnumEntry.tool_call` 默认 `True`（§12.3 字面是 `False`） | 实测：字段缺失与 `false` 对工具同效 → 默认 `False` 会让 §12.1 立项要消灭的"静默删 tools"原样保留。已写入 **PRD Q28-⑤**，并补两条约束（非 chat 恒 `false`、覆写走枚举 YAML 且读写双向透传） |
| D2 | 删除 `rebuild()` 复用分支的 `state.quota = _pool_for(rid)` | 实测撤掉后 625 条全绿 → 不可达防御代码。改由 `:198` 一处保证不变量，并补 3 条走 `rebuild()` 的红证 |
| D3 | 删除 `CooldownManager.clear()` | 无生产调用点；方案未定义"手动解除熔断"表面。手动出口 = CLI 打印 `circuit.json` 路径（§14 已确立"手改本地文件是受支持路径"） |
| D4 | 熔断中 `mgw zcode claim` 新增**退出码 3** | §16.4 只定了 0/1/2；"本轮一次上游都没打"与"全部正常"必须是两个退出码，否则脚本化调用无法分辨。属§21.3 原则 3 的补齐，非新增功能 |
| D5 | `mgw setup` 判定依据文案改为「本地配置 · 原因：<三态之一>」 | 原文案只有"网关未运行"一种，会把 401 说成进程问题（T9b） |

**登记而未在本轮动手的相邻缺口**（按"发现即报告、不在本轮范围内偷改"处理）：

| # | 缺口 | 建议 |
|---|---|---|
| G1 | 熔断/冷却**剩余分钟**在界面上只有资源健康卡的「冷却剩余」列（单位秒，且需展开到资源粒度）；总览指标区没有聚合"还有多久恢复" | 二期与「账号授权」页一并考虑 |
| G2 | `mgw setup` 的 401 提示只解释"密钥失效"，未提示"网关端口与配置不一致"这一常见成因 | 文案可加一句；需先实测两种错配的可见差异 |
| G3 | 前端门依赖本机 `node`（无则 skip）；纯 Python 环境下这道门会静默不跑 | 若要进 CI，需把渲染函数改用 Python 侧 JS 引擎或在 pytest 里断言"node 缺失即 fail" |

---

## 四、下一轮（第五轮）复验要点（写给验收 agent）

1. **本轮每个修复的红证是否可复跑**：按 §二 的"撤掉→判据"表逐条重做（工作树即现网代码，锚点见 §一 的 `file:line`）。
2. **额度账模型**：确认没有第二本账（不得存在 `used` 启发式、结算侧扣减、单调守卫），并验证"快照充值后必须重新放行"。
3. **可见性三态**：`mgw setup` 在 401 / 未运行 / 超时 三种情形下打印的依据是否与真因一致；`mgw zcode claim` 在熔断中是否退出码 3 且无"全部正常"。
4. **前端门**：`node scripts/verify_v2_frontend.mjs <overview> --mutation` 必须 37/37；`pytest tests/integration/test_int_v2_frontend_gate.py` 必须 2 条绿。
5. **护栏强度**：`_public_symbols` 现覆盖类方法 —— 新增任何无人调用的公开方法/函数都会被拦，白名单只允许"由包外机制调起"且附理由。
