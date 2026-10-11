# E2E-20260927 · v2.0 第三轮：判据本体返工 + 对前两轮记录的更正

> 依据：`docs/specs/tech-design.md` v2.0 §12–§21（§19 判据表 / §20 不做清单 / §21 出口契约）
> · `docs/specs/prd.md` **v1.15**（Q25–Q27 + **Q28**）· `docs/research/`（00 总览 / 08 实测 / 09 设计定稿 / 11–19）
> 上游：第二轮验收报告 `docs/changes/reviews/{PM,eng,ix}-accept-2.md`（2026-09-27，三份均**不放行**）
> 本文：三份报告的阻塞项 + 自查新发现（G1–G4）全部返工，并**更正前两轮记录中的不实表述**。
> 纪律：每条附 `file:line` 或实跑输出；未实测项显式标注；护栏必须证明"能红"。

---

## 一、本轮开工状态（先核实再动手）

| 项 | 实测 |
|---|---|
| 基线 | 第二轮收账时 **537 passed**；开工前 `git log -1` = `5158cbc`，全部为未提交工作树 |
| 三份验收结论 | eng **不通过**（2 严重）· PM 有条件通过（6 阻塞）· IX 有条件通过（1 严重） |
| 自查新发现 | G1 `Resource.product` 未加 · G2 `query_balance` 未做 · G3 求解器未实现（上一轮记成"外部依赖未实测"）· G4 `SUPPORTED_PRODUCTS` 零消费者 |
| 当前 | **602 passed**（见 §四），每项返工均做"撤掉即红"反证 |

---

## 二、对前两轮记录的更正（不静默覆盖，逐条点名）

| # | 原文 | 更正 |
|---|---|---|
| C1 | 第二轮证据账：「死代码 0 项 —— 51 个新增公开函数全部有生产调用点」 | **不成立**。本轮 AST 复核另有 `CooldownManager`、`AccountLocks`/`PlanLock` 的若干方法、`roundtrip_ok`、`AccountInfo`、`project_data_dir` 等无引用；且我上一轮加的"12 符号护栏"**覆盖集是人手挑的**，结构上必然漏 → 已重做为自动导出全集（见 §三 T10） |
| C2 | 同上：「残余死代码 3 个」 | 不完备。实际按 C1 处理：接线 2 个（`build_headers`、`delete_account`→`mgw zcode remove`），删除 3 个（`oauth.refresh`、`roundtrip_ok`、`AccountInfo`） |
| C3 | 同上：N4「验证码求解 + 住宅代理 —— 外部依赖（需外购住宅代理）；**代码已就位**并未配置时明确报错」 | **口径错误**：当时全仓无 Playwright 实现、`zcode_claim` 从不传 `captcha_solver` → 真实状态是**未实现**，且配好代理后文案仍谎称"未配置住宅代理"（IX S-1）。本轮按用户裁决「走完整方案」实现（§三 T6） |
| C4 | 同上：「`test_v2_servable.py` 12 条 / `test_int_v2_servable.py` 6 条」「反证 B → 4 failed」 | 实为 **11 / 7 条**（现 14 / 7），反证 B 撤掉预留实跑 **8 failed**（含 4 条单元 + 4 条端到端）。计数须抄自跑出的输出，不能凭记忆 |
| C5 | 同上：「CLI 冒烟（本机实跑）`mgw --help` → rc=0」 | 本机 `command -v mgw` 为空（未 `pip install -e .`，`dist-info` 无 `entry_points.txt`）→ 实为 `python -m model_gateway.cli`。已在 README 双版注明等价形式，本文措辞一并更正 |
| C6 | §17「熔断原因写 `last_error` → 总览『最近错误』列直接可见，**无需改前端**」 | 前提为伪：`snapshot_by_resource()` 当时不输出该字段、前端零引用（design-spec:193 要求的那一列**从未实现**）→ 本轮补接口字段 + 补前端列（§三 T2） |
| C7 | 本轮自查：我上一轮"按上一轮验收报告建行修"的做法本身是**范围错误** | 方案的 §14.2 / §16.5 / §16.6 条目从未被任何一份报告列过，因此整轮漏掉。教训入 memory：清单要**从方案导**，不能只从报告导 |

---

## 三、本轮返工清单（11 项，逐项：判据 → 落点 → 测试 → 反证）

| # | 返工 | 落点（`file:line`） | 测试 | 撤掉即红 |
|---|---|---|---|---|
| **T1** 🔴 额度粒度（eng S-1） | 余量本质是**一把凭据**的，不是 `(rid, vendor_model)` 的 → 新增 `QuotaPool`（`core/resources.py:32-58`），同 `rid` 的多个映射**共享同一实例**；`_pool_for` 挂进 `rebuild`（`:172,178`）并按资源回收（`:186-191`） | `test_two_mappings_of_one_credential_share_a_single_quota_pool`（余量 1、两映射 → 只放行 1）、`test_concurrent_two_mappings_cannot_double_spend`（`gather` 真并发） | 实跑复现原缺陷：改前「1 单位 → 2 个请求都获批」；改后该用例红 |
| **T2** 🔴 预留/结算对称（eng M-5） | `reserve/settle/release` **一律 1 单位**，删掉 `amount`/`consumed` 自由度（原 `amount=5` 配 `settle(-1)` → `reserved` 永久泄漏 4） | `test_reserve_settle_release_are_symmetric`（**签名级**钉死：长出 `amount` 形参即红）+ 泄漏断言 | 人为恢复 `amount` → 红 |
| **T3** 🔴 滞后快照不得复活余量（eng M-3） | `set_quota(..., used=)`：同窗口内（`used` 未变小）**只允许调低**；`used` 变小 = 滚动窗口翻页才全盘接受（`core/resources.py:281-303`） | `test_stale_snapshot_cannot_resurrect_spent_quota` / `test_window_reset_is_accepted` / `test_decreasing_snapshot_is_always_applied` | 去掉单调性判定 → 红 |
| **T4** 🔴 3012 全局熔断落盘（PM B2 / §17） | `CooldownManager` 重写：**墙上时钟**（原存 `monotonic` 却落盘 → 跨重启无意义）、按 mtime 回读（跨进程可见）、原子写、`get_circuit()` 单例（`upstream/zcode/quota.py:206-330`）；`_handle_risk_control` 命中即 `enter()` + **全部 ZCode 账号一并回写**（`ops/builtin/zcode_claim.py:90-113`），CLI 腿经 `POST /admin/api/zcode/bench`（`scope=global`，`api/admin.py:403-424`） | `tests/unit/test_v2_circuit.py`（**13** 条：墙上时钟断言、跨实例可见、过期自动失效、熔断中不开上游、F001 文案、CLI 腿 scope=global）+ `test_int_v2_zcode_admin.py`（**13** 条：端点 global/account、非 ZCode 资源不受牵连、overview 带出原因） | 把 `_epoch_ms` 换成 `monotonic` → `test_circuit_persists_wall_clock_not_monotonic` 红 |
| **T5** 🔴 熔断原因的用户可见出口（PM B3 / §17 / design-spec:193） | `snapshot_by_resource()` 新增 `last_error`（`_worst_error` 按状态严重度 + C 取值，`core/resources.py:100-115`）；前端资源健康表补 **「冷却剩余」+「最近错误」两列**，并抽成可执行函数 `resourceHealthTable()`（`dashboard.js`） | `tests/integration/test_int_v2_zcode_admin.py::test_overview_surfaces_circuit_reason` + `test_v2_circuit.py` 2 条取谁为"最近错误" + `scripts/verify_v2_frontend.mjs` 渲染断言（**td 单元格里**，不接受只在 `title` 里） | 删快照字段 → 后端 1 条 + 前端 1 条同时红 |
| **T6** 🔴 Playwright 验证码求解器（IX S-1 / G3 / §16.5） | 新建 `upstream/zcode/captcha.py`（**约 300 行**）：`client/configs` 取参 + 兜底、参数 TTL 45s、宽限期 300s 后台刷新、失败 60s 短熔断、`asyncio.Lock` 同进程串行、`wait_for(30s)`、浏览器**进程级复用** + `aclose()`（停机收尾接进 `Runtime.aclose`）、F001/T001/T002 分类文案；`zcode_claim._build_client` **恒接求解器**（`ops/builtin/zcode_claim.py:60-75`），"为什么不可用"由知道原因的一方说；依赖走 extra `pip install "model-gateway[captcha]"`，缺失时给可执行安装命令 | `tests/unit/test_v2_captcha.py`（**12** 条：TTL 复用/越过宽限期、宽限期即回旧值+后台补、失败短熔断、`enabled=false` 不开浏览器、配置接口挂走兜底、超时包装、并发只开一次浏览器、装配事实 `_captcha_solver is not None`、验证码失败**不带** `network:` 前缀） | 去掉 `captcha_solver=` 传参 → `test_production_client_always_gets_a_solver` 红 |
| **T7** 🔴 路径与配置来源（eng M-4） | 新建 `core/paths.py`：`PROJECT_ROOT` 锚定 + `MG_CONFIG` 优先 + 全部 `.resolve()`；`load_config()` 之前**完全忽略 `MG_CONFIG`**，现走 `resolve_config_path`；`main.py` 的 `USAGE_DIR/ENUMS/DIALECTS/LOCK_PATH`、`store.accounts_root()`、`ops_lock_dir()` 一并改由它派生；`admin_post/admin_get` 端口取自生效配置 | `test_ops_lock_dir_ignores_cwd`（**子进程换 cwd 真跑**，两边必须同一路径）、`test_ops_lock_dir_follows_mg_config`、`test_admin_post_targets_mg_config_port`、`test_int_44b_lock_is_cwd_independent`（同一配置、两个 cwd → 第二个实例退出码 3） | `ops_lock_dir()` 退回 `Path("data")` → 2 条红；这轮修复还**顺带让 4 条既有单实例锁测试变红后被我修正**，证明旧实现下锁确实是按 cwd 各算一份 |
| **T8** 🟡 锁的静默失效条件（eng M-2/M-9） | ① 目录不可写 → 退 `/tmp` 仍互斥 + 告警（原 `except OSError: return True` = 静默放弃）；② 主目录与退路都不可写 → **拒绝拿锁**（宁可本轮不跑，也不双领）；③ 空/半写锁在 2s 写宽限期内不可抢（TOCTOU）；④ 超 `LOCK_MAX_AGE_S=15min` 视为陈旧（pid 复用不至于永挡）；⑤ 锁内容 `pid + 进程令牌`，release 双条件匹配（防误删他人锁）；⑥ `_HELD_BY_US` 按 `(锁目录, 账号)` 记；⑦ `Scheduler._tick` 异常不再杀死定时器（`errors` 计数） | `test_v2_ops.py`（**61** 条，含 `test_fresh_unreadable_lock_is_not_stolen`、`test_stale_corrupt_lock_is_reclaimed`、`test_over_aged_lock_is_reclaimed_despite_live_pid`、`test_all_lock_dirs_unwritable_denies_instead_of_granting`、`test_scheduler_survives_tick_exception`、`test_plan_lock_blocks_another_process`（真实子进程持 plan 锁）） | 去掉写宽限期 / 把 `_tick` 的兜底去掉 → 对应用例红 |
| **T9** 🟡 两路径同判据（IX M-1 / Q28-②） | `mgw setup` 改为**优先向运行中的网关要 `/v1/models`**（含 invalid/停用等运行态），取不到才按配置判定，并打印「可服务模型判定依据：…」 | `test_setup_prefers_live_gateway_judgment`、`test_setup_without_running_gateway_says_it_is_config_only` | 把 `admin_get` 结果丢弃 → 前者红 |
| **T10** 🟡 护栏重做 + 空过用例（eng S-2 / PM B1） | 新建 `tests/unit/test_v2_wiring_guard.py`：从 AST **自动导出** v2.0 全部公开符号，要求每个都有真实引用（`Name`/`Attribute`/`ImportFrom`/类型注解，不算注释与 docstring），例外须进带理由的白名单，白名单过期即失败；另加 §17/§19 **指定接线**映射（`bench_all_zcode` 必须由 `zcode_claim` 调等） | 4 条（含"覆盖面自检：清单里点名的模块必须都在"）；本轮它当场揪出 3 个新死符号并删除 | 首跑即红（报出 51 个误报 + 3 个真死代码），据此把判据从"跨文件"改为"除定义处外有引用" |
| **T11** 🟡 文案与文档（PM B5/B6、IX M-2/M-3/M-5、G1/G2/G4） | ① ①③两类告警都写明"已从 /v1/models 与 mgw setup 隐藏"；② `model_unservable` 指路改正（启停开关在「模型资源」页 `resources.js:233`，映射在「资源池设置」页）；③ `param_shadowed` 点名模型 + 两侧值 + 生效序 + 去处；④ 红点 toast 不再把"重跑领取"说成"查看详情"，并给 `python -m model_gateway.cli` 等价形式；⑤ PRD **Q24-⑥ 正文**与 FR-3.16 互相排序（消掉与 Q28-③ 并存的冲突字面）；⑥ `Resource.product` 字段（§14.2/D7，向后兼容）+ `mgw setup` 新增 Key 继承；⑦ `query_balance` 动作落地且**由 tick 真实调用**；⑧ `supported_products` 变成真判据（不支持的产品账号显式跳过 + 空跑判定排在过滤之后） | `test_v2_cli.py`（**19**）、`test_v2_cli_zcode.py`（**20**）、`test_config.py`（**28**）、`test_int_v2_servable.py`（**7**）+ `verify_v2_frontend.mjs` 的文案断言（含"0s 内不重试"这类无效提示、隐藏说明出现 ≥2 处） | 把 `OPERATIONS` 里 `query_balance` 摘掉 → `test_ops_tick_runs_both_registered_operations` 红；删 `product` 继承 → 前端静态断言红 |

---

## 四、实跑证据

```
$ .venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest
602 passed, 452 warnings in 80.02s
```
轨迹：537（第二轮收账）→ 542 → 555 → 559 → 568 → 574 → 586 → 590 → 592 → 596 → 598 → **602**（**+65 条**，零回归）。

本轮用例数（**抄自 `--collect-only` 输出**，不凭记忆）：

| 文件 | 条数 | 文件 | 条数 |
|---|---|---|---|
| `unit/test_v2_ops.py` | 61 | `unit/test_v2_cli_zcode.py` | 20 |
| `unit/test_v2_quota_reservation.py` | 21 | `unit/test_v2_cli.py` | 19 |
| `unit/test_v2_servable.py` | 14 | `unit/test_config.py` | 28 |
| `unit/test_v2_circuit.py` | 13 | `unit/test_v2_captcha.py` | 12 |
| `unit/test_v2_wiring_guard.py` | 4 | `unit/test_v2_claim_wiring.py` | 10 |
| `unit/test_v2_zcode.py` | 37 | `integration/test_int_chat.py` | 24 |
| `integration/test_int_v2_servable.py` | 7 | `integration/test_int_v2_zcode_admin.py` | 13 |
| `integration/test_int_v2_quota_reserve.py` | 4 | `integration/test_int_v2_ops_isolation.py` | 1 |

```
$ .venv/bin/python scripts/ui_verify_v2_visible.py        # exit=0
后端出口实测 12 项，通过 12 项，失败 0 项
前端/静态实测 35 项，通过 35 项，失败 0 项
（新增断言：熔断原因必须出现在 td 单元格里而非只在 title；"重跑领取"不得写成"查看"；
 "剩余时间"不得显示 0s；两条隐藏告警各说一句）
```

**测试隔离新惯例**（`tests/conftest.py` autouse）：① 运营锁目录重定向到 tmp 并清空进程级持有集；
② 熔断单例按用例重建；③ 🔴 **桩掉 `urllib.urlopen` 本机 HTTP** —— 本机常态跑着一个真实网关（`:8300`），
不桩的话 `mgw setup` 的测试会读到那个实例的运行态，结论随本机状态漂移（本轮实测踩到）。

---

## 五、有意偏离与未实测（不粉饰）

**偏离（3 条，均给出代价与恢复成本）**

| # | 偏离 | 理由 | 恢复成本 |
|---|---|---|---|
| D1 | §17 额度刷新触发点②「模型转发成功后按 30s 节流补刷」**未接** | 该通道是**客户端日志尾读（4 MiB/次）**，挂在每次转发的热路径上代价过高；预留闸门用的是最近快照，tick 级（默认 60s）新鲜度足以拦住"余量已 0 还派活" | 低：在 `scheduler` 成功分支加一次节流调用，不改数据结构 |
| D2 | `EnumEntry.tool_call` 默认 `True`（§12.3 字面 `False`） | 沿用第二轮结论：默认 `False` 会把"工具静默删 `tools`"这个 bug 原样保留 | 低 |
| D3 | Playwright 走 **optional extra** 而非主依赖 | 主依赖会强制所有人下载浏览器内核；缺失时**明确报错 + 给安装命令**，不静默降级 | 低（挪进 `dependencies` 即可） |

**未实测（真实凭据 / 联网 / 外购住宅代理 / 真实客户端）**

- §19 原有 **T1–T10** 状态不变。
- 本轮新增：**N1** 求解器真机能否过阿里云无痕（需代理 + 凭据 + 浏览器）；**N2** `client/configs` 的字段时效（§19 T9 同源，我用参考实现的兜底值，配置接口取不到才用它）；**N3** `query_balance` 的真实日志格式（现在的是 `18` §② 取证的结构，字段缺失时"绝不当可用"）；**N4** 额度余量**量纲**（1 请求 = 1 单位为保守闸门，非精确记账）；**N5** 锁退路 `/tmp` 在多用户机器上的权限语义。
- ⚠️ 前端仍为"真实源码函数 + 结构/样式静态断言"（本机 headless Chrome 加载真实页面会挂，已复现）；**未经真实浏览器渲染验证**。
- 🔴 本轮所有可见出口（横幅两列、红点文案、新端点）需要**重启 `:8300` 上那个旧实例**才在真实界面生效 —— 未重启（用户未指示），故真实浏览器上目前看到的仍是旧行为。

---

## 六、方案一致性小结

- §19 判据：M3-0…M5-3 **全部有实现 + 有可复跑测试**；M5-3 判据"并发不超发"本轮才真正成立（T1/T2）。
- §20 不做清单：未越界。`query_balance` 与 `product` 列是**方案要求**（§16.6 / §14.2），非自创；新增面仅 1 个管理端点 + 1 个 CLI 子命令（`remove`，为消掉 `delete_account` 死代码）+ 2 类告警。
- §21 四处出口：①③④ 双通道（接口 + 日志）+ 前端横幅渲染均已实测；②红点有清零出口且文案与副作用一致。
- 需求真相：`prd.md` v1.15（Q28 四项）+ Q24-⑥/FR-3.16 排序冲突已消解。

---

## 七、复跑

```bash
cd /Users/w/Desktop/Model-Gateway
.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest        # 602 passed
.venv/bin/python scripts/ui_verify_v2_visible.py; echo $?       # 12/12 + 35/35，exit 0
.venv/bin/python -m model_gateway.cli --help                     # 或安装后 `mgw --help`
```
