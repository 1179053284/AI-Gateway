# eng-accept-5a · 第 5 轮验收 A 片：资源运行态状态机（只读审查）

审查人：senior backend engineer（slice A）｜日期：2026-09-28｜范围：`core/resources.py` 运行态三不变量
铁律 2：以下每条带 `file:line` 或实测输出；未跑的写「未验证」。仓库副本**零改动**（所有改写只发生在 `/tmp/mgw-e5a-mut/*` 的单向 `cp` 副本）。

## 门 1 · pytest（必交证据）

`cd /Users/w/Desktop/Model-Gateway && .venv/bin/python -m pytest tests/unit/test_v2_quota_reservation.py
tests/unit/test_v2_circuit.py tests/unit/test_v2_servable.py -q --basetemp=/tmp/mgw-pytest-e5a -p no:warnings`
→ **`78 passed in 0.17s`**（0.17s 说明三条用例文件都是纯内存用例，无 IO/等待）。

## 变异测试（证明守得住）

| # | 变异（去掉的不变量） | 变红的用例 + 失败行 |
|---|---|---|
| M1 | `bench()` 去掉 `if extended:` 的 max 守卫（覆盖式写法） | `test_bench_never_shortens_an_existing_cooldown` `tests/unit/test_v2_circuit.py:466: AssertionError: 短冷却覆盖了长冷却 = 提前放行 / assert 1061.0 == 2800.0`；**且生产路径用例同红** `test_v2_circuit.py:483: 额度 tick 把熔断冷却剪成 1.0 分钟，熔断仍剩 30 分钟` |
| M2 | 删 `bench()` 的终态守卫 | `test_v2_circuit.py:286: AssertionError: invalid 被冷却覆盖成 cooldown` |
| M3 | `_conn_fingerprint` 只摘要 base_url（丢掉 Key） | `test_v2_circuit.py:310: AssertionError: 改对凭据后仍判死 = 只能靠重启` |
| M4 | `snapshot_by_resource()` 里去掉 `self.reconcile_expired()` | `test_v2_servable.py:283: assert ('cooldown' == 'active')` |

结论：三条不变量都有**能真的失败**的守门用例（含 M1 的端到端穿透路径，不只是白盒单元）。

---

## 不变量 1（`bench()` 只延长 / 终态不可覆盖 / 返回所有权）：**通过**（1 中 2 轻）

证据：`resources.py:315-322` 终态守卫 + `extended` 判定；调用侧 `quota.py:499-501` 只在取得所有权时写 `last_error`（M1/M2 双红）。
全仓写状态点穷举（`grep '\.status *=\|setattr('`）：`resources.py:96/231/276/319/325/328/414`、`scheduler.py` 只用 `disable()/invalidate()`（:402/:408/:677/:683）、`quota.py` 只走 `bench`（:499）。**无旁路写者。**

- **中 1（终态的逃逸口 = 不变量 2 的误判口径）**：`resources.py:231` 的重置分支是 `invalid/disabled` 唯一逃逸口，而它的判据 `_conn_fingerprint`（:27）对 `base_url` 取**原串**，`main.py:227-230` 的适配器复用判据却是 `r.base_url.rstrip("/")`（注释自称"同一条连接"）。用户只是补/删一个结尾 `/`（或改大小写以外的等价写法）→ 指纹变 → **被 401 判死的凭据就地回到生效集并被 `servable_models` 下发、打真实上游**，同时 C/冷却历史被清零。自愈性：下一条 401 会重新 disable，但**多打一发真请求、且界面状态闪回 active**（本轮 S-2 想消灭的正是这类"显示与行为相反"）。修法：指纹口径与适配器判据对齐（`base_url.strip().rstrip("/")`），并把 `preset`/`protocol` 纳入或纳入 reset 抑制名单。
- **轻 1（latent 短冷却）**：`extended = state.status != "cooldown" or ...` —— 若某条目 `status=="active"` 却带着未来的 `cooldown_until`，短冷却仍会覆盖。按当前所有 writer（:96/:231/:276/:414）该状态**不可达**，故不判中；建议无条件 `state.cooldown_until = max(state.cooldown_until, until)` 消掉这条可达性论证。
- **轻 2（所有权契约只在 quota 侧被尊重）**：`scheduler.py:419/437/646/694/711` 五处 `bench()` 全部丢弃返回值（它们不在 bench 时写原因，暂无实害），但契约靠"约定"而非"类型"维持，与 `quota.py:489` 写的"裁决点"表述不完全一致。

## 不变量 2（连接身份重置：不泄露 + 不误触/不漏触）：**不通过**（泄露面通过，判据口径不通过）

- **泄露面 = 通过（实测口径）**：`src_fp` 全仓仅 `resources.py` 内部读写（grep 命中 :86/:90/:108/:207/:216/:224/:235，无外部读者），不进 `snapshot_by_resource` 的键集（:447-462 逐键核过：rid/name/vendor/account/status/C/in_flight/cooldown_remaining_ms/last_error/models）；`ResourceState` **未定义 `__repr__`**（默认对象地址），带 repr 的只有 `QuotaPool`（:77-78，仅余量）。`/admin/api/config` 默认脱敏（`admin.py:488-490`），PUT 侧 `_unmask_resources`（:495-502）做掩码回写还原。→ 密钥与摘要都没有用户可见出口。
  - 附记（既有设计，非本轮回归）：`admin.py:484` 的 `?reveal=1` 直接回明文 Key，叠加 Q18-① 管理端免鉴权 = 任意本机进程可读全部 Key；是否可接受请产品确认，本轮不重复计缺。
- **中 2（漏触：plan/ZCode 类资源的真凭据不在指纹里）**：`api_key` 对 `product: zcode` 资源只是占位，真实凭据是账号目录里的 `credentials.json`（`quota.py:561-587` 按账号备注反查）。磁盘侧轮换/吊销 → 配置不变 → 指纹不变 → **该类资源的 `invalid/disabled` 仍没有自愈路径**（S-2 的修复只覆盖 api_key 那一条腿）。**未验证**：ZCode 资源在真实 `config.yaml` 里 `api_key` 的实际取值与出站用途（本轮未跑网关、未读 `data/`）。
- **轻 3（`protocol` 不进指纹）**：`main.py:227-230` 把 protocol 变化当作"换连接"（重建适配器），`_conn_fingerprint` 却不看它 → openai↔anthropic 切换沿用旧鉴权方案判下的死状态，两口径互相打脸。
- **正向已验证**：改名 / 改备注（`name`/`account`/`vendor`）**不会**触发重置（这些字段不在 :27 的 raw 里，只在 :219-222 就地刷新显示属性）；`test_v2_circuit.py:315-324` 的同凭据重载对照用例守住"不许误清"。
- **轻 4**：`loader.py` 无任何 env 注入/`strip()`（grep `environ|getenv|expand|strip` 全空），"Key 换成环境变量"这一题在本项目**不存在该路径**；但同样意味着 Key 尾随空格会原样出站（`scheduler.py:218` 取 `key_values` 原串），故空格编辑触发重置算真凭据变化、非误触。风险在反方向：UI 若回传一个与 `mask_key()` **非逐字节相同**的字符串（前端多 trim 一次即命中），`_unmask_resources` 不还原 → 掩码串被当新 Key 落库。未验证前端实际提交形态（属 B/C 片）。

## 不变量 3（聚合 + `reconcile_expired` 从读路径改状态）：**不通过**（线程安全通过，"不外泄旧原因"口径不通过）

- **线程/事件循环安全 = 通过**：`reconcile_expired`（:410-417）纯同步无 `await`；两个调用点 `admin.py:118`（status，5s 轮询）与 `:167`（overview）都在事件循环协程内；热重载 `main.py:245-252 _apply/rebuild` 由协程 `_reload_watcher`（:475/:493-508）`await`，同线程。全仓 grep `to_thread|run_in_executor|threading.` 仅命中 `ops/runner.py:67,257`（cron 计划锁）、`main.py:193`、`captcha.py:115`（asyncio.Lock），**无工作线程碰 registry**。CLI/cron 是独立进程、各持自己的 registry，资源回写经 HTTP `/admin/api/zcode/bench`（`test_v2_circuit.py:192` 钉住）。
- **与 `pick_and_acquire` 懒过期的分歧 = 真缺陷（中 3）**：两条 cooldown→active 路径**对 `last_error` 的处理不一致** —— `:275-276`（有流量时）只翻状态**不清原因**，`:413-415` 清。流量先于轮询到达时，条目离开 `cooldown` 后 `reconcile_expired` 永不回头，**旧冷却原因被永久钉在一台已可用的资源上**，并经 `_worst_error`（:139-142，只看"有没有 last_error"，不看状态）显示到 `dashboard.js:104` 的「最近错误」列。这正是 `test_v2_servable.py:283` 判为"谎报当前故障"的同一现象，只是当前用例只测了**零流量**那一半。叠加 `note_success`（:384-385）只清 `C` 不清 `last_error`，成功恢复的资源同样带幽灵原因。修法：把"到期即清 last_error"抽成一个函数，两个过期点共用（或在 `note_success` 清）。
- **关于"清了会不会丢唯一记录" = 不会丢**：每请求 `meta.error_summary` 随事件落盘（`scheduler.py:187-197` 的 event 载荷含 `error_summary`，`_log`→`events.log_request` :310-311），请求日志页仍可追溯；熔断原因另有 `circuit.json`（`quota.py:319-325` 墙钟 + `至 HH:MM` 文案，`test_v2_circuit.py:353-361` 守住）。**未验证**：本轮未实跑落盘文件核对键名。
- **中 4（§17 唯一可见出口的静默空转，仍有一条）**：`sync_circuit_to_runtime`（`quota.py:549-558`）在"该账号的资源全是 `invalid/disabled`"时，`bench_account` 经 `bench()` 终态守卫返回 0、`account_bound_resources` 的 `mismatched` 也为空 → 返回 `(0, 0)`，与"熔断没生效"完全同形。而 :539-542 自己写着"这条回写是熔断的**唯一**可见出口 …两种都必须说出来"。恰好最该被说出来的（判死号 + 还在熔断）没说。
- **轻 5 聚合其余核过**：`_SEVERITY`（:129）invalid>disabled>cooldown>active 与 `test_v2_servable.py:241-252` 一致；`cooldown_remaining_ms`（:393-397）对非 cooldown 返 0，不会出现"剩余 0s 的冷却"徽章。**但** `_worst_error` 用 `max(key=(severity, C))`，同严重度同 C 时取**注册表插入序第一条**，标着「最近错误」却可能展示更早那条，且 rebuild 后顺序可漂（建议加时间戳键）。
- **轻 6**：`snapshot_by_resource:446` 对"没有任何映射条目"的资源给 `status=active / available=true` —— 一台从不承接请求的资源显示为健康。
- **轻 7**：`reconcile_expired()` 的返回值（:417）两个端点都没消费，docstring 的"便于日志留痕"未接线（`grep reconcile_expired` 仅 :431 一处调用）。

## 假断言 / 弱断言嫌疑（点名）

1. `tests/unit/test_v2_circuit.py:467` `assert (st.cooldown_until - t[0]) > 1700` —— 与 :466 断同一量的等价重述，零额外覆盖。
2. `tests/unit/test_v2_circuit.py:76-80` `_FakeMgr.bench()` 返回 `None`：与真实 `bench()->bool` 契约相反，任何走 `_FakeRuntime` 的断言在 `apply_to_resource` 里都会因 `if not None` 恒真而**全部跳过写入**（正是 `test_v2_zcode_quota.py:224` 记过的"假对象掩盖接线崩"同类）。当前用例恰好不依赖它，属潜伏误导，建议 fake 返回 `True`。
3. `tests/unit/test_v2_circuit.py:287` `assert st.last_error is None` 只在守卫生效路径上有意义（M2 下 :286 先红，够不到这行），单独看接近搭车断言。

## 处置建议（按性价比）

1. 中 1 + 轻 3：统一"连接身份"判据（与 `main.py:227` 对齐 + 纳入 protocol）——一处改动同时补住不变量 1 的逃逸口。
2. 中 3：过期清理抽函数、`note_success` 清 `last_error`，并在 `pick_and_acquire` 翻转路径补一条用例（当前测试矩阵只有零流量半区）。
3. 中 2：plan 类资源另设身份来源（账号目录 mtime/jwt 摘要）或显式声明"该模式无自愈路径"并给出手动归位入口。
4. 中 4：`sync_circuit_to_runtime` 的返回加第三类计数"因终态被挡"。
5. 另立一项（本片外）：凭据更换时应一并回收该 rid 的 `QuotaPool`（`resources.py:215` 复用同池、:224-235 重置分支不碰 `remaining/reserved`）—— 换新 Key 后仍可能挂着旧账号的"额度耗尽"闸门，需下一轮额度 tick 才解（**未验证**是否有秒级 tick 兜底覆盖全部资源）。

## 未验证清单

未启动网关进程、未跑 integration/E2E、未读 `data/` 运行时产物、未核 ZCode 资源的 `api_key` 实际取值、未核前端 PUT 回传的 Key 形态、未跑全量 pytest（按要求只跑指定三文件）。
