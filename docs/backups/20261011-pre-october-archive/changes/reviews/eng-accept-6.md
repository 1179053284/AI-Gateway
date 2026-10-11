# 工程验收 第六轮 · S-13~S-17 补做差量复核（senior backend, 2026-09-28）

方式：只读复核 + `/tmp/mgw-e6` 副本上**逐条撤修复**（每条都跑"复原后为绿"收尾）。
基线（真仓，一次运行）：`tests/unit/test_v2_ops.py test_v2_circuit.py test_v2_servable.py
test_v2_cli.py test_v2_wiring_guard.py` → **144 passed**（`--basetemp=/tmp/mgw-pytest-e6`）。
副本 `.venv` 为符号链接，测试环境一致。

| # | 结论 | 撤修复变异（/tmp/mgw-e6） | 输出 |
|---|---|---|---|
| S-13 | **通过** | `ack_reports()` 在 `_backlog()` 之后再 `_report_rows()` 读一次（复原"两次读"） | `test_ack_does_not_swallow_a_row_appended_mid_ack` → `E assert 2 == 1` 红；复原后同批 1 passed |
| S-14 | **通过（口径仍有 1 处不严格，见 N-2）** | `_conn_fingerprint` 换回 `f"{r.base_url}\n{r.api_key}"`（原串、无 protocol） | `test_cosmetic_url_change_does_not_revive_a_dead_credential` → `E assert 'active' == 'invalid'` 红；正向对照 `test_credential_change_still_revives_after_a_url_edit` 变异下仍绿（符合"对照"定位：它防的是过度修复，不是红证） |
| S-15a | **通过** | 共用动作 `_lift_if_expired` 里加 `state.last_error = None` | 两条判据**都**红：`test_both_expiry_paths_agree_on_the_recovered_row` → `E assert ('active', None) == ('active', '上游 429 限流')`；`test_expired_cooldown_reads_as_available_without_traffic` → `E assert None == 'ZCode 额度耗尽'`。该判据同时钉"两路一致"**与**"保留历史值"，比我预期的强 |
| S-15b | **通过（真实目录实测）** | 前缀解析换回 `split("-")[0]` + 日期 `split("-",1)[1]` | `test_ops_results_are_pruned_by_the_retention_policy` → `E assert not True` 红。**真实目录形态实测**（daily/events/switch-events/ops-results/ack 各造 30 天前 + 新鲜件，走 `EventLogger.start()`）：删除 `events-20260829` / `switch-events-20260829` / `ops-results-20260829` / `ops-results-ack.json`；保留 `daily-*.json` 与未过期件 → 前缀解析对全部现存文件种类正确。真实 `data/usage` 现存仅 `daily-*.json` / `events-*.jsonl` / `switch-events-*.jsonl`，无未覆盖种类 |
| S-16 | **部分通过（护栏有 3 类逃逸，见 N-1）** | 在 `core/scheduler.py` 追加死符号后跑 `test_v2_wiring_guard.py` | ①`DEAD_E6_BENCHMARK_LIMIT = 42` → **被抓**（`core/scheduler.py#DEAD_E6_BENCHMARK_LIMIT`）②`DEAD_E6_ANNOTATED: dict[str,int] = {}` → **6 passed，逃逸** ③`DEADE6CONSTANT = 7`（无下划线）→ **逃逸** ④`class E6Decoy: def aclose(self)` → 只报 `#E6Decoy`，**同名死方法 `aclose` 未被报**（逃逸）。复原后基线 6 passed |
| S-17 | **部分通过（页名未真正单一源，见 N-3/N-4）** | (a) dashboard.js 列名 最近错误→最近失败：交叉判据红 `「最近错误」列的归属变了：[]`；(b) `runtime_dead` 指路改回 `{RESOURCE_PAGE}`：红；(c) `OVERVIEW_HEALTH_PAGE` 改成不存在的「仪表盘」页 → **`test_v2_cli.py` 21/21 全绿**（未红） |

## 新缺陷（本轮）

- **N-1（中）接线护栏仍可种死代码**：`_public_symbols` 只处理 `ast.Assign` 且要求
  `id.isupper() and "_" in id`（`tests/unit/test_v2_wiring_guard.py:82-87`）→
  带注解的常量（`X: Final[...] = `、`X: dict = {}`）与无下划线全大写常量结构性逃逸；
  同名歧义路径（`:170` 起 `_reaches_module` 只要"该文件 import 过本模块"即算引用）
  使 `aclose`/`claim` 这类名字的死方法成盲区。建议：`AnnAssign` 并入、放宽 isupper 判定、
  歧义名要求"同文件内确有的类名/变量标注出现"。
- **N-2（轻）S-14 口径仍非"完全一致"**：`resources.py:29` 用 `.strip().rstrip("/")`，
  而 `main.py:226` 复用判定只用 `r.base_url.rstrip("/")`（无 strip，比较对象是适配器存的原文）。
  后果：URL 首尾空白/制表符的编辑 → 指纹不变（凭据不复活）但适配器重建 → 两处口径反向。
  修一处 `strip()` 对齐即可。
- **N-3（轻·硬编码泄漏）**：`main.py:330` 的 `param_shadowed` 告警把页名写成字面量
  `「资源池设置」页`，**未走** `ROUTE_POOL_PAGE` —— 即"第四处"仍在硬编码；改常量它不红。
  （其余 `main.py:111/286/313/314` 与 `cli_setup.py:74-78` 确实已同源。）
- **N-4（轻·交叉判据盲区）**：交叉核对只把「最近错误」这一**列**绑到 `dashboard.js`，
  不绑**页名↔导航标签**（`js/main.js:22 title:"总览"`）→ 变异 (c) 证明改成不存在的页名全绿。
  另：JS 侧页名天然硬编码且无守卫（`models.js:157/188/248/297/361`、`dashboard.js:124`
  均写「模型资源」页），与 Python 侧 `no_mapping` 指到「资源池设置」页对同一动作给出不同入口，
  属文案一致性债（两页都能配映射，非事实错误），需用户裁决口径。

## 语义反转（S-15a）消费者复核 → 无漂移

全包 `last_error` 读取点穷举：`resources.py:146-149 _worst_error`（按 status 严重度择优，
归位条目降为 active 后仍作为"历史条"参与，符合新语义）、`web/static/js/pages/dashboard.js:104`
（仅在为空时置灰，无逻辑判定）。`servable_models`（`resources.py:170-186`）只看
`status in ("disabled","invalid")`；switch 事件/请求日志不读该字段。→ **未发现仍假设"归位即清"的消费方**。

## 其它

- `ACCOUNT_PRODUCTS` 删除后 `ops/builtin/__init__.py` 完整：docstring 未留孤儿、
  三个 import（`AccountOperation` / `query_balance` / `zcode_claim`）全部被 `OPERATIONS` 使用；
  `tests/unit/test_v2_ops.py:674` 已改为本用例内自建集合，全包 `grep ACCOUNT_PRODUCTS` 仅剩测试与历史评审文档。
- **未验证**：① 全量 `pytest 673 passed` 与前端门（`verify_v2_frontend.mjs --mutation 50/50`、
  `ui_verify_v2_visible.py --mutation 12/12`）本轮未跑（按指示不做全量），S-18 整条属前端门范围 → **未验证**；
  ② 未重启 :8300 实例、未打真实上游；③ N-1 的逃逸形态未在真实提交历史里回归验证（仅本轮种植样本）。
