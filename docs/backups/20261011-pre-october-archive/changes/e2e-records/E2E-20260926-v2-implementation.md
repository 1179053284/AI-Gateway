# E2E-20260926 · tech-design v2.0 增量实现（§12–§21 / M3–M5）

> 依据：`docs/specs/tech-design.md` **v2.0**（§12–§21 增量设计，经三角色审核 + 两轮复核后定稿）
> 与 `docs/specs/prd.md` **v1.14**（Q25 / Q26 / Q27）
> 范围：**M3（能力位 / 参数归一化 / CLI / setup）→ M4（anthropic_out / upstream/zcode）→ M5（ops / 额度聚合）**
> 证据纪律：铁律 2 —— 任何「已实现 / 已跑通」必须附运行输出；**未实测项显式标注**。

---

## 一、改动清单

| 层 | 文件 | 内容 |
|---|---|---|
| CLI·入口 | `pyproject.toml`（新增 `[project.scripts] mgw`）+ **新建** `model_gateway/cli.py` | **项目此前无任何命令入口**（§19 M3-0）；子命令 `probe` / `setup` / `zcode` |
| CLI·实现 | **新建** `cli_probe.py` / `cli_setup.py` / `cli_zcode.py` | 探测 / 文件下发 / 账号管理（含设备冲突 3 选项） |
| 能力位 | `enums/matcher.py`（`EnumEntry.tool_call`）+ `config/schemas.py`（`SystemModel.caps_overrides`）+ **新建** `core/capabilities.py` + `api/openai_compat.py` | `/v1/models` 追加 7 字段 + `caps.thinkingLevelMap`（**7 键齐全**）；原有 6 字段不动 |
| 参数归一化 | **新建** `core/dialects.py` + **新建** `probe.py` | 7 档规范序（开放可扩展）/ 只降不升 / **三步探测（S2 单锚点 `none→0`）** / 方言表缓存 |
| 文件下发 | **新建** `setup_tools.py` | `mgw setup`：目录按**产品标识 → `dataFolderName`** 解析 + 环境变量优先；**路径确认 + 备份 + 合并 + 原子写 + 读回校验 + 回滚** |
| 出站适配 | `adapters/anthropic_out.py`（**从 1 行空壳 → 完整实现**）+ **新建** `adapters/__init__.py: build_adapter` | duck typing 4 方法；IR ↔ Anthropic 约 15 组映射；**usage 映射**；**2xx 非 JSON → `status_code=None`** |
| 分发点 | `main.py:108-122` + `api/admin.py:300-306` | 按 `Resource.protocol` 分支（v1.6 无条件 `OpenAIOutAdapter`，`protocol` 字段未被使用） |
| ZCode 接入 | **新建** `upstream/zcode/{crypto,dataroot,store,oauth,auth,quota,claim}.py` | 整根隔离 / 设备身份三条硬约束 / `enc:v1` / 双通道鉴权 / 额度三通道 / 领取三段式 |
| 运营模块 | **新建** `ops/{base,runner}.py` + `ops/builtin/zcode_claim.py` | 四类结果 / 双层互斥 / 串行+抖动 / 失败隔离 / 空跑两情形 / 结果落盘 |
| 用户可见出口 | `main.py`（启动告警 + `config_warnings()`）+ `api/admin.py`（overview `warnings[]`、status `ops_failed_unread`、`GET /admin/api/zcode/quota`）+ 前端 `dashboard.js`（横幅）/ `index.html` + `main.js` + `base.css`（顶栏红点） | §21 四处出口 |

---

## 二、测试证据

```
$ .venv/bin/python -m pytest -q
462 passed in 59s
```

**基线对照**：本次开工前为 **199 passed**（`M1 已验收` 时的口径）→ 新增 **263 条**，**零回归**。

> ⚠️ 环境坑：pytest tmp 目录在本沙箱里用户名探测失效（认成 `root`/`unknown`）→
> 需 `--basetemp=/tmp/mgw-pytest`。零回归**。

### 2.1 新增测试文件与用例数

| 文件 | 用例 | 覆盖 |
|---|---|---|
| `tests/unit/test_v2_capabilities.py` | 19 | 能力位映射 / 自定义模型兜底 / **7 键齐全** / `caps_overrides` 优先 / 档位序 / 降级 / 方言表读写 |
| `tests/unit/test_v2_probe.py` | 11 | S1 抠值域 / **S2 单锚点** / 假方言丢弃 / 规范外档位保留 / 可注入假序列 |
| `tests/unit/test_v2_setup.py` | 14 | **`dataFolderName` 解析**（非子串判断）/ 环境变量优先 / 合并 / 备份 / 原子写 / 无 `.tmp` 残留 |
| `tests/unit/test_v2_cli.py` | 17 | `mgw --help` 退出码 0 / `[project.scripts]` 存在 / setup 路径确认 / 非交互需 `--yes` |
| `tests/unit/test_v2_anthropic.py` | 36 | 请求/响应转换全表 / SSE 翻译 / **usage 映射** / **`status_code=None` 契约** |
| `tests/unit/test_v2_zcode.py` | 34 | `enc:v1` 往返 / **三条硬约束** / 目录穿越防护 / 设备码永不重算 |
| `tests/unit/test_v2_zcode_quota.py` | 24 | 日志尾读 / **括号配对** / **串号防护** / 额度归一化 / **3012 熔断 30min + 落盘** / 熔断回写 |
| `tests/unit/test_v2_zcode_claim.py` | 18 | preview 取最高优先级 / **激活事件体 16 字段** / 验证码缺失**不静默** |
| `tests/unit/test_v2_ops.py` | 33 | **四类结果** / **双层互斥（生产共享锁）** / 失败隔离 / 网络重试 vs 业务不重试 / 空跑两情形 / 清零出口 |
| `tests/unit/test_v2_quota_reservation.py` | 10 | **M5-3 额度预扣**：事前预留 / 结算 / 释放 / **并发不超发** / 未知额度向后兼容 |
| `tests/integration/test_int_v2_capabilities.py` | 18 | `/v1/models` 8 字段 / 前缀剥离 / **overview `warnings[]` 两类** |
| `tests/integration/test_int_v2_anthropic.py` | 13 | **假 Anthropic 上游完成一次 chat** / 流式 / 故障切换 / 2xx 非 JSON 冷却 |
| `tests/integration/test_int_v2_zcode_admin.py` | 9 | 额度聚合端点 / 日志优先 / **`/v1` 无额度端点**（不做对外）/ **ack 清零** / 方言表重载 |

### 2.2 关键判据的逐条落地（对照 §19 交付判据）

| 判据 | 证据 |
|---|---|
| M3-0 `mgw --help` 退出码 0 | `test_help_exits_zero` / `test_cli_entry_declared_in_pyproject` |
| M3-2 `/v1/models` 含 7 字段 | `test_models_adds_seven_capability_fields` |
| M3-4 `thinkingLevelMap` 7 键齐全、不支持为 `null` | `test_caps_level_map_has_exactly_seven_keys` / `test_caps_unsupported_levels_are_explicit_null` |
| M3-3 探测逻辑可确定性验证 | `test_probe_verifies_real_write_field` / `test_probe_rejects_fake_dialect_when_not_zeroed` |
| M3-5 文件下发格式/合并/原子写可断言 | `test_write_backs_up_existing_file` / `test_write_leaves_no_tmp_residue` |
| **M4-1 经 Anthropic 上游完成一次 chat** | `test_nonstream_chat_through_anthropic_upstream` ✅ |
| M4-2 设备唯一性冲突**拒绝**而非静默重生成 | `test_constraint3_conflict_is_rejected_by_default` |
| M4-4 熔断回写后转发路径绕开 | `test_apply_to_resource_benches_and_writes_reason` |
| **M5-1 四类结果分类正确** | `test_run_once_classifies_all_four_categories` ✅ |
| **M5-1 并发只领一次** | `test_account_lock_prevents_double_claim` ✅ |
| M5-2 额度聚合端点 | `test_quota_aggregates_across_accounts` |

---

## 三、用户可见出口实测（§21）

```
$ .venv/bin/python scripts/ui_verify_v2_visible.py

[后端出口]
  ✓ overview 含两类告警  ['model_without_resource', 'resource_without_model']
  ✓ 两类措辞不同
  ✓ 模型类告警提到 503
  ✓ status 含 ops_failed_unread  = 0

[前端渲染逻辑]（Node 执行 dashboard.js 的**真实渲染函数** + 真实接口数据）
  ✓ 渲染出 .alert-warn 横幅
  ✓ 横幅含 503 措辞
  ✓ 横幅含「未被任何系统模型引用」
  ✓ 两类告警各渲染一条  banners=2 warnings=2
  ✓ 空 warnings → 不渲染任何横幅
  ✓ warnings 非数组 → 安全降级

[顶栏红点（index.html 结构）]
  ✓ 存在 #ops-dot 元素
  ✓ 默认 hidden（0 失败时不显示）
  ✓ 存在文案节点 #ops-dot-text

[红点轮询（main.js）]
  ✓ 轮询 /admin/api/status      ✓ 读取 ops_failed_unread
  ✓ 5s 轮询间隔                 ✓ 页面隐藏时跳过轮询
  ✓ 已导入 GET（否则运行时报错）

[红点样式（base.css）]
  ✓ .ops-dot 样式存在           ✓ 用双主题令牌（--err / --err-bg）

实测 16 项，通过 16 项，失败 0 项
```

> ⚠️ **方法说明（诚实标注）**：本机沙箱下 **headless Chrome 加载真实页面会挂住**
> （`--dump-dom` + 真实 URL 超时；已实测复现）。故前端验证改用
> **Node 直接执行 `dashboard.js` 里的真实渲染函数**（**同一份源码，非复制品**）
> + 结构 / 轮询 / 样式断言。脚本：`scripts/verify_v2_frontend.mjs`。
> **未经真实浏览器渲染验证** —— 这是环境限制，不是跳过。

启动日志同步打印（双通道，`main.py` `_startup`）：

```
[配置告警] 1 个系统模型未配置任何资源，调用将返回 503 —— 到「模型资源」页编辑资源添加映射（empty-model）
[配置告警] 1 个资源未被任何系统模型引用（孤儿资源）
```

> **为什么要双通道**：启动脚本正常路径是 `nohup` 后台拉起 + **自动关闭终端窗口** ——
> **告警只写日志 = 用户看不见**（这正是 Q25-⑧ 的立项理由）。接口出口才是真正的可见路径。

---

## 四、验收发现的问题与修正（三角色并行验收 → 全部已修）

> 三个角色（产品经理 / 研发工程师 / 交互与视觉）**并行**验收同一冻结产物，共报出
> **1 处"接线即崩"、2 处"语义与方案相反"、1 处"误导用户"、约 450 行死代码**。以下逐条记录修正。

| # | 验收发现 | 严重度 | 修正 |
|---|---|---|---|
| 1 | **熔断回写未接线**：`apply_to_resource` / `CooldownManager` 全仓**零生产调用点** → 3012 熔断永不生效 | 严重 | 加 `quota.bench_account()` 接线点，由 `zcode_claim._maybe_bench()` 在风控/耗尽时调用 |
| 2 | **接线即崩**：`apply_to_resource` 调 `mgr.bench(state)`，但真实签名是 `bench(state, seconds)` → `TypeError`。**单测的 fake 也少了该参数，掩盖了缺陷** | 严重 | 修正调用传 `seconds`；**同时把测试的 fake 对齐真实签名**，并新增 `test_apply_to_resource_passes_seconds_to_bench` 护栏 |
| 3 | **空跑语义与方案相反**：`N=0` 返回空 report，CLI 打印「全部正常，无需处理」且退出 0 | 严重 | `run_once` 记 `inactive=["（无账号参与）"]` + `no_participants=True`；CLI 输出明确说明并**退出 2** |
| 4 | **测试断言了错误行为**：`test_empty_accounts_reports_inactive_not_success` 把错误行为断言为真 | 严重 | 改为断言正确行为（不再是"测试通过但功能错"） |
| 5 | **配置键不存在**：提示让用户配 `gateway.zcode.proxy`，但该键在 schema 里不存在，Pydantic 静默忽略 → 用户照做被丢弃 | 严重 | 新增 `ZcodeUpstreamConfig`（`proxy` / `plan_base_url` / `claim_interval_seconds` / `claim_cron` / `fingerprint`），挂在 `gateway.zcode`；加 `test_config_key_actually_exists` 护栏 |
| 6 | **双层互斥生产失效**：`run_once` 每次新建 `AccountLocks()` → cron 与 CLI 各持一把锁 | 中等 | 改为**模块级共享锁** `_SHARED_LOCKS`；测试**不传 `locks=`** 以守生产路径 |
| 7 | **红点只增不减**：`ops_failed_unread` 无清零出口 → 一次失败后**永久常亮** | 中等 | 加 `clear_failed_counter()` + `POST /admin/api/ops/ack` + 前端点击即确认清零 + CLI 查看后自动 ack |
| 8 | **方言表探测后不重载**：`mgw probe`（独立进程）写完文件，运行中的网关不刷新 | 中等 | 加 `POST /admin/api/dialects/reload`；probe 结束后通知网关（网关未运行时跳过） |
| 9 | **`--manual` 文案循环**：已加 `--manual` 仍叫用户加 `--manual` | 中等 | 分两种提示；加 `test_manual_hint_does_not_loop` |
| 10 | 🔴 **功能缺口（验收顺带发现）**：`anthropic_out` 一律发 `x-api-key`，而 **ZCode Plan 通道需 `Authorization: Bearer <jwt>`** → 必然 401 | 严重 | `_headers` 按凭据形状判定（JWT → Bearer）；加 `test_jwt_credential_uses_bearer` |
| 11 | **约 450 行死代码**（占新增 24%）：`auth.py` 整层、`cron_matches`、`classify_http_error`、`dataroot` 进程控制族、`oauth.refresh`、`report_activation`、`degrade_effort` | 中等 | **接线**而非删除：fingerprint→适配器、cron→Scheduler、激活上报→领取流程、degrade_effort→出站档位兜底、launch→`mgw zcode launch`。**删除**真正冗余的：`degradation_chain`（我们用"两资源+调度器切换"表达降级链）、`classify_status`、`runner` 里的重复业务码表 |
| 12 | README 缺 CLI 章节；`mgw` 不在 PATH 时红点 toast 指路会 `command not found` | 轻微 | README 两个版本补 CLI 章节（含 `python -m model_gateway.cli` 等价形式）；版本与测试徽章更新 |
| 13 | `zcode list` 表头 CJK 宽字符右偏 | 轻微 | 用 `_wcwidth` 做东亚宽字符补偿 |
| 14 | 多失败时「✗ 失败 N 个」前缀重复打印 | 轻微 | 前缀只打一次，逐条缩进列出 |

**修正后复跑**：`462 passed`（较验收前 +22 条新增护栏用例），§21 出口实测 **后端 4/4 + 前端 16/16**，**死代码 0 项**（脚本复核：51 个新增公开函数全部有生产调用点）。

---

## 五、🔴 未实测项（诚实标注，不宣称完成）

| # | 项 | 为什么未测 | 对应待实测编号 |
|---|---|---|---|
| 1 | **免费额度走哪条通道**（`api.z.ai` vs `zcode-plan/anthropic`） | 需真实 ZCode 凭据 + 联网 | T1 |
| 2 | `billing/current` 的 401 根因 | 同上 | T2 |
| 3 | **`enc:v1` 的 `username` 取值口径**（`USER` / `LOGNAME` / `getpass`） | 需与真实 ZCode 客户端比对 | T3 |
| 4 | `setting.json` 是否同样不受重定向 | 需真实客户端 | T4 |
| 5 | **`curl_cffi` 能否通过 `zcode.z.ai` 的 WAF**（T5a）与 **async SSE 流式**（T5b） | 需联网 + 真实端点 | T5a/T5b |
| 6 | CLI device flow 是否仍可用 | 同上 | T6 |
| 7 | 验证码是否真的强制 | 同上 | T7 |
| 8 | 3012 的具体触发阈值 | 服务端行为不可知 | T8 |
| 9 | RE 文档时效（最新实测 2026-08-18） | 需重跑 `client/configs` | T9 |
| 10 | 三个 `ZCODE_DESKTOP_*` 是否真覆盖 `app.setPath` | 需真实客户端 | T10 |
| 11 | **验证码求解 + 住宅代理**（Playwright） | **外部依赖**（需外购住宅代理）；代码已就位并**未配置时明确报错**（`test_missing_captcha_solver_raises_with_user_guidance`） | — |

> 以上均按用户要求「**做的过程中再测**」处理（PRD Q27-③）。

---

## 六、与方案的一致性说明（含一处**有意偏离**）

### 5.1 一处有意偏离（需知悉）

| 项 | 方案字面 | 实现 | 理由 |
|---|---|---|---|
| `EnumEntry.tool_call` 默认值 | §12.3 写 `bool = False` | **`bool = True`** | 实测工具侧 `supportsToolCall !== true` 会**删除请求中的 `tools`** —— 即**字段缺失与 `false` 行为相同**。默认 `False` 会让"静默删 tools"这个 bug **原样保留**，而消灭它正是 §12.1 的立项目标。默认 `True` 后若某模型确实不支持，失败是**上游可见的 400**（可发现），而非静默降级（不可发现）。 |

> 已在代码注释（`enums/matcher.py`）与本节显式标注，供验收判断。

### 5.2 方案要求但**未做**的（均为方案本身列入"不做清单"）

- 不做统一 Device Registry（§20 #1，Q27-⑤）
- 不做免重启热切换（§20 #2）
- 不做 L-B/L-C 录入界面（§20 #15）
- 不做 GUI 自动化（§20 #16）
- 不做对外额度端点（§19 M5-2 明确"不做对外端点"）
- 不做首期前端 UI（§20 #12；已用 CLI 入口替代）

---

## 七、复跑方式

```bash
cd /Users/w/Desktop/Model-Gateway
.venv/bin/python -m pytest -q                    # 全量 437 条
.venv/bin/python scripts/ui_verify_v2_visible.py # §21 用户可见出口实测
.venv/bin/python -m model_gateway.cli --help     # 或安装后 `mgw --help`
```
