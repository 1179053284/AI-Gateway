# E2E-20260930 · M6 多产品账号接入与模型转接 · 实施台账（**已收口**）

> 依据：`docs/specs/tech-design.md` §22（架构，PRD Q29）＋ `docs/specs/prd.md` §9-Q29。
> 纪律：① 每波次由总 agent **对磁盘核证**后才放行；② 发现的问题**修复到零问题**才算交付（Q29-⑤）；③ 真实凭据类一律「未实测」（§22.11，用户驱动）。
> **回填说明**：本文件曾在 00:07 滞后（R4-C-1）→ 03:5x 首轮回填；**05:1x 终版回填**（面板/复验轮后），口径以本版为准。

## 波次总览（终态）

| 波次 | 状态 | 事实 |
|---|---|---|
| M6-0 架构总纲 | ✅ | `tech-design.md` §22（4 处裁决补入 + 3 条会话/入口约定 + 评审后注记）；PRD v1.19 + Q29 |
| M6-1 公共层 | ✅ | `accounts/{types,registry,store,device,login,net,materialize}.py` + 10 产品骨架；zcode 委托化；`ops.product_of_account` 泛化 |
| M6-2 产品批 A | ✅ | buddy/workbuddy（同族零复制）/ lobsterai / qoder+qodercn / cline |
| M6-3 产品批 B | ✅ | trae / loomy / raccoon（代理中断但产物完整，64/64 核证）/ zcode 对齐 |
| M6-4 管理端 | ✅ | 13+1 端点 API（新增 `models` 目录出口）+「账号接入」页；真机验收：M6-4b 55/55 → R3 独立 67/67 → **IX 面板 81 项 / 修复轮后 72 条断言全 PASS** |
| M6-5 模型转接 | ✅ | 物化/分派/复用判据/buddy 试点 + 9 产品 `out.py`；qoder 签名缝与 zcode 验证码缝 **fail-closed**；未注入前提资源**不进 `/v1/models`** + 横幅 |
| M6-6 审核+修复 | ✅ | 4 路对抗评审（R1/R2/R4 不通过）→ 修复轮 1（7 路，含 5 阻塞）→ 修复轮 2（面板后 2 路 + 接线补齐） |
| M6-7 交付面板 | ✅ | 轮 1：eng-b ✅0 / IX ✅0 / eng-a ✅（A-1 边界阻塞）/ **PM ❌2**；轮 2 复验：eng-a-2 ✅0 / **PM-2 ❌1（仅台账计数）** → 本文件终版回填 → PM-3 收口（进行中） |

## 测试计数沿革（均我复跑）

835 → 996 → 1221 → 1304 → 1371 → 1422 → 1443 → **1445（终态，`1422→1443→1445` 为面板两轮修复与接线补齐累计）**
- 终态命令：`.venv/bin/python -m pytest -q -p no:cacheprovider` → **1445 passed / 0 failed**；`--collect-only` = 1445；README 双语 = **1445**（逐字一致，PM-2 实测）。
- 面板复验的复制品跑动（1444 passed + 1 双树伪红）为 /tmp 环境伪影，已由两角色独立复证（主树等价 1445/0）。

## M6-6 评审 → 修复 → 红证（逐条）

| 评审发现 | 严重度 | 修复（含红证） |
|---|---|---|
| R1-F1 `alt_call` 绕过会话 TTL/取消 | 严重·阻塞 | `_gate()` 共用；撤修复 → 过期会话仍落盘（2 failed） |
| R1-F2 `_looks_retryable` 与产品文案脱节 | 中 | `ClaimOutcome.retryable` 结构化 + 10 产品折叠点置位；红证：撤置位 → 重试计数=1 |
| R1-F3 buddy `X-Product: SaaS` + 错引行号 | 中 | 拆 `inference_headers`/`identity_headers`；红证：退回旧实现 → `'SaaS' == 'CodeBuddy'` 红 |
| R1-F4/R4-BL2 护栏 filename 豁免被虚置 | 中 | 删隐式豁免；qoder/qodercn 补 `_IMPLEMENTED`+`_REFUSED_HOOKS`；红证：植编造 success → 护栏红 |
| R1-F5 跨进程写盘无 fail-closed 互斥 | 中 | `store._AccountsWriteLock`（fail-closed，无 /tmp 退路）；红证：撤锁 → 5 failed（真两进程交错） |
| R1-F10 引擎层不校验会话↔产品配对 | 轻 | `_advance` 加配对校验；红证：删分支 → 1 failed |
| R1-F6/F11、R2-F-6 等轻项 | 轻 | F-6 删死写；F11 在 §22.2 加例外注记；F6 由额度钩子接线覆盖 |
| R2-B-1 未登记 product 打死热重载 | 阻塞 | `_apply` 全异常降级 + watcher 兜底 + `resource_adapter_unbuilt`；红证：撤兜底 → 第二次热重载不生效 |
| R2-B-2 401 判死资源不可复活 | 阻塞 | 指纹扩面 + **重登 `_nudge_reload()` 自触发**；红证：撤触发 → 重登后仍 disabled |
| R2-F-3 captcha 缝异常裸 500 | 中 | provider 异常包成 `UpstreamError`；红证：撤包装 → `500 != 500` |
| R2-F-4 zcode 3012 / D1 | 中 | 不绕过不加熔断，仅诚实标注（横幅「zcode 直连前提未验证（D1）」） |
| R2-F-5 前提未注入资源照进 `/v1/models` | 中 | `unservable_reason` 注入缝 + 告警；红证：撤谓词 → 模型回列表 |
| R3-P-4 CSRF | 中 | `admin_write_origin_guard`；红证：撤校验 → 4 例红且真实落库 |
| R3-P-1 `.ellip` 选择器失效 | 低 | 内联省略样式；CDP 实测 558=558（修前 886>558） |
| R3-P-2 断言 JSON 无「已修」标注 | 低 | 补 `status: fixed-by-Fix4` + `recheck_after_fix` |
| R4-BL-3 §22.6 operation 收敛未落地 | 阻塞 | `claim`(7)/`query_balance`(10)/`zcode_claim` 别名/跨产品枚举/额度钩子；`PRE_CHECK_PRODUCTS` 单一源 |
| R4-BL-1/BL-4 台账滞后 + 未记录改动 | 阻塞 | 本文件两轮回填；归属：README（总 agent）、`test_v2_wiring_guard.py`（Guard-fix/修复-2）、`test_v2_circuit*.py`（00:45，**归属未确认**，内容=时钟注入与 `fmt_recovery_clock` 同源） |
| R4-BL-5 卫生 | 阻塞 | ✅ `:8419` 孤儿已终止；`.pytest-tmp-m65c` 已删 + `.pytest-tmp-*` 入 `.gitignore`（PM-2 以 check-ignore 反证） |

## M6-7 面板 → 修复轮 2 → 复验（逐条）

| 面板轮 1 发现 | 处置 | 复验 |
|---|---|---|
| PM B-1 `list_models` 零用户出口且未登记 | 新增 `GET /admin/api/accounts/{p}/{n}/models`（四态、零凭据）+ 前端「模型目录」入口（能力驱动）+ 9 用例 + 真机断言 | **PM-2 闭环**（8394 四态 + CDP 8/8 + 生产链路 file:line） |
| PM B-2a README 计数与台账不符 | README 逐轮同步；台账本版终填 1445 | PM-2 判「README 侧已真、台账仍 1422」→ **本版回填 1445** |
| PM B-2b `.gitignore` 缺规则 | 已加 `.pytest-tmp-*`；仓根探针目录 ignored 反证 | **PM-2 闭环** |
| eng-a A-1 锁等待阻塞事件循环（1007ms 实测） | `*_async`（`to_thread`）+ **生产接线补齐**（login/admin 4 端点；护栏白名单 3 条删除） | **eng-a-2 闭环**：自写探针心跳 3.76ms/2490 拍；撤 5 处 await → 964ms/1 拍；恢复 1.27ms |
| eng-a A-2 双桥接 | `ops/bridge.py::outcome_to_op_result` 唯一实现（`is` 同一对象；5 组输入逐字段一致） | **eng-a-2 闭环** |
| eng-a A-3 两套 retryable 口径 | `zcode_claim` 改 `product_hooks.is_transport_failure` 同尺 | **eng-a-2 闭环** |
| eng-b F1 空 base_url 资源仍可服务 | 并入 `unservable_reason` + 横幅点名；文案修正 | **eng-a-2 闭环**（撤判据 → 模型回清单） |
| eng-b F2 `_apply` 半应用 | 两阶段提交 + `hot_reload_failed` 横幅 + 自愈 | **eng-a-2 闭环** |
| eng-b F3【红线级】凭据回显进事件 JSONL/日志/响应 | `core/errors.py` 统一脱敏（`scrub_upstream_text` + Key 登记） | **eng-a-2 闭环**（三处零明文；撤脱敏 → 明文红） |
| IX-1/2/3 行号漂移 / 内部编号上屏 / 短信导语分支 | 均已修（断言 JSON 原记录保留；title 用户语言；分支修正） | IX 复验保留在修复报告；PM-2 抽查未见回归 |

## 「未实测」清单（交付话术红线：**不得写成已完成**）

- U1 真实凭据逐产品登录/领取出证（用户驱动）；U2 zcode 直连 405/3012（D1）；U3 qoder 签名端点（fail-closed 缝）；
- U4 macOS 各产品行为/上游字段漂移；U5 zcode 验证码真机；U6 T5a/T5b（curl_cffi/async SSE）；U7 T10（`ZCODE_DESKTOP_*`）；
- U8 zcode 探活直连；U9 buddy `X-IDE-*` 取值未取证（按裁决不发）与 UA 分档；U10 cline `stream:false` 与余额单位；
- U11 raccoon `device_id` 语义 / `stream:false`；U12 loomy `stream:false` / 微信图字段；U13 qoder CN `sessionType`；U14 lobsterai `prompt_cache_key`。
- 评审侧核证（R4 §4）：以上 14 类**无一处被写成"已完成"**；`grep skip/xfail` 零命中。

## 过程记录（诚实披露）

- zcode 对齐代理冒烟期一次真实网络调用（`/oauth/cli/init`，无凭据无副作用）——违规登记，后续 brief 加严。
- raccoon / M6-5a / M6-4b / M6-5b / M6-5c 代理多次撞 150 轮上限：产物经总 agent 抽验核证后按"完成"计（判据是磁盘）。
- 台账曾滞后 7 项（R4-C-1）→ 两轮回填；修复轮 2 有代理越界改 `core/scheduler.py`（文案）/`core/resources.py`（docstring）/README——已如实登记，内容经复验无风险。
- 面板期间冻结树纪律执行；复验角色均以 /tmp 复制品 + 独立探针工作。

## M6 后续补口（2026-09-30，交付后 3 项登记缺口收口）

| # | 缺口（登记来源） | 修法（含撤改红证） |
|---|---|---|
| 1 | `mgw zcode login` 仍是软占位（W3-D 遗留：设备流机器已有、CLI 未接） | `_login` 重写为真实设备流（init→打印授权地址+设备码→轮询→`commit_login`+`write_client_credentials`，与 UI 向导同路径）；退出码 0/1 口径不变；旧软占位 `oauth.login` 成为死代码按纪律删除。红证：撤回旧占位实现 → 14 failed；新用例 16/16 绿 |
| 2 | `WriteLockError` 未进 `_commit_outcome` 捕获面（eng-a-2 登记） | 纳入捕获 → 锁拒写时 `state=failed` + detail「写盘锁不可用（未落盘）」+ 凭据清空。红证：撤分支 → `state_after='success'`（谎报） |
| 3 | registry `base_url` 仅 2/10 有判据（R4 NB-2 登记） | `test_registry.py` 增全量用例：10 条非空 + 8 条与产品模块常量等式（buddy/workbuddy 无常量 → 非空+出处注释）。红证：改/清空任一值 → 红 |

- **计数**：1445 → **1464 passed / 0 failed**（我复跑；README 双语同步 1464）；`:8300` 已再次优雅重启至最新代码。
- 过程登记：代理越界文件 1 处（`model_gateway/cli.py` 子解析器注册 `--name`/help，2 处，已如实上报）；真实上游设备流/凭据仍未验证（§22.11，用户驱动）。
- **仍开放（需用户决策，非本轮回合）**：① qoder/qodercn 模型转发（签名通道含 292KB WASM，需决策"引入 wasm 运行时采用参考产物 / 逆向重写 / 维持 fail-closed"）；② zcode 模型转发（D1：直连 405/3012 待真实凭据最小实测——接线前资源保持不进 `/v1/models`）；③ 真实凭据全链路验证（U1–U14）。

## M7-UI（2026-09-30）·「账号接入」页 v2 改版 + 回跳接收端 + 三项后端硬前置

> 依据 = `docs/changes/design-accounts-list-v2.md` v2.1（对抗评审 7 BLOCKING + 4 MAJOR 的逐条处置见该文 §10）；
> 触发 = 用户 2026-09-30 反馈「账号接入-产品列表现在太复杂了，不用按系列分组……明显没动脑子」。
> 本轮**不新增产品、不动转接层**：只做这一页 + 它硬依赖的三处后端 + 判据门 + 规范回写。

### 落地（逐项 `file:line`）

| 项 | 落点 | 复跑证据 |
|---|---|---|
| **BD4 回跳接收端** | 新 `model_gateway/accounts/callback_server.py`（`CallbackListener` `:109`；**只绑 127.0.0.1**，首选端口被占回退系统分配端口）；引擎侧 `accounts/login.py:396 _open_callback` / `:418` 随会话创建、随会话销毁 | `tests/integration/test_m7_callback_capture.py` 16 例（真回跳落库 / 双写 userinfo / latin1 昵称 / 伪造 trace 拒绝 / 噪声请求不扰会话 / 端口回退 / 兜底粘贴仍可用 / 无泄漏） |
| **trae 接线** | `upstream/trae/product.py:167 _CALLBACK` 声明表 + `upstream/trae/login.py:158`：授权 URL 用**实际绑定端口**（`callback_server.declared_port`，取不到才回退常量 18080） | 同上（`test_trae_real_arrival_commits_credentials` / `test_preferred_port_taken_falls_back_and_authorize_url_follows`） |
| **lobsterai 接线** | `upstream/lobsterai/product.py:204 _CALLBACK` + `upstream/lobsterai/login.py:177` 同口径 | 同上（`test_lobsterai_real_arrival_exchanges_inside_the_request`） |
| **BD2 `login/cancel` 路由** | `api/admin_accounts.py:596-616`：幂等 `{cancelled: bool}`、**永不 404**（用户点取消与上游回跳本是竞态），出表同时关掉该会话的接收端 | `test_cancel_closes_the_listener` / `test_ttl_expiry_settles_listener_and_drops_session` / `test_paste_back_still_works_when_the_listener_never_gets_a_hit`；`accounts.js` 关窗路径统一请求作废 |
| **BD1 cron 两条腿 `enabled_of`** | `api/admin_accounts.py:278 cron_enabled_of`（内部即手动腿的 `_enabled_of`）→ `main.py:212`（claim 腿）与 `:218`（余额腿）**两条都传** | `test_m7_backend_preconditions.py:104`（停用被跳过）+ `:150` **成对撤证**（不传 `enabled_of` → 停用账号仍被领取）+ `:174`（开关与 cron 读同一位） |
| **BD8 调度器在新装不起** | `main.py:135 _maybe_start_ops`：**撤"启动时 0 账号就永不起定时器"的一次性判定**，门改到每一轮（`main.py:209` 空轮直接返回、不空写 JSONL），`:224 sched.start(_run)` | 同上 `:194`（0 账号也起）/ `:222`（空轮不落盘，首个账号落盘后拿到快照）/ `:256`（不重启网关即出额度） |
| **BD3a `resource` join** | `api/admin_accounts.py:499`（`_resource_projection`：`None` = 配置读不动 = **未知**，`[]` = 确实没有）→ 前端 `accounts.js:483-490` 三态分开呈现 | 同上 `:304` / `:346` |
| **页面 v2 重写** | `web/static/js/pages/accounts.js`（1182 行全量重写）：族层删除 → 10 行扁平 `.anchor-item` **选择器**（非容器）+ 4 列固定列集（`.exp`/账号/状态〔开关+文字合一〕/额度〔四值〕/操作 ≤3 icon）+ 实现词汇全降进展开行 `.req-detail` + 唯一入口 `.subnav-foot .side-add`（`:188-189`）+ `?p=` 深链（`:161-166`，未在册回落首项并在 `.value` 注明）；gutter 收进 `base.css:601 .panel-split`（含 ≤768 横滚条带 `:1123-1129`） | 真机断言轮由并行验收代理负责（`docs/changes/e2e-records/m7-accounts-ui*`，本行不代其宣称） |
| **判据门接电** | 新 `tests/integration/test_int_v2_accounts_gate.py` 把 `scripts/verify_accounts_ui.mjs` 纳入 pytest：正常跑要求 `0 失败` + 判据数 ≥12（门被删窄即红），`--mutation` 要求字面 `可红 8/8` + 无 BAD | `pytest tests/integration/test_int_v2_accounts_gate.py -v` → **2 passed**（12 通过 / 0 失败；可红 8/8） |
| **规范回写** | `tech-design.md` §22.7：本页组成按定版改写并**记明推翻**（原「左子侧栏产品 group-card」= 臆造族轴），API 块补 `login/cancel` 一行；`design-spec.md` **v2.19 补 §2.8「账号接入」章**（此前全篇无章 —— 正是本页能连续两轮交付坏而无人可判的制度原因，设计书 §8-5 点名要补） | 两份文件在盘（本文写毕核对 diff） |

### 本轮实测抓出的三个真 bug（均已修，每条在判据门里有对应变异）

| # | bug（设计书 §0-4） | 根因 → 修法 | 门/证 |
|---|---|---|---|
| BUG-1 | 额度列对真数据源**失明**：`quotaCell()` 只读 `a.quota`（网关池内存摘要），从不读 `a.runtime.quota`（落盘余额快照，唯一写者 `ops/builtin/query_balance.py:110-133`） | 取数改「优先 `runtime.quota` → 退 `a.quota`（只进展开行，量纲不同不得混列）→ 无快照写『尚未刷新』」（`accounts.js:431-437`） | V4 + 变异「quotaCell 改回只读 `a.quota`」 |
| BUG-2 | **全新安装后调度器永不启动**：`_maybe_start_ops` 只在 startup 钩子调一次（`main.py:957`），且"无账号即 `return None`"排在 `refresh_quotas()` 之前 → 接入第一个账号后额度恒「未知」，直到用户重启网关 | 一次性判定撤掉，门改每轮（BD8，见上表）；界面第四态「尚未刷新」把"网关还没查过"**如实暴露**，不折进「未知」 | V7 + 变异「第四态折进『未知』」；`test_gateway_process_writes_quota_snapshot_without_restart` |
| BUG-3 | **开关对定时腿撒谎**：行内 switch 的 `title` 写「账号停用：运营执行跳过」，但只有手动腿传 `enabled_of`，cron 两条腿都不传（`ops/runner.py:462-470` 明确"给了才跳过"）→ 谎只对一半入口成立 | 两条腿都传 `cron_enabled_of`（BD1），`title` 现写「手动与定时两条腿同判据」（`accounts.js:421`） | `:150` 成对撤证（不传 → 停用账号仍被领取） |

### M7 仍开放（登记，不得写成已完成）

| # | 开放项 | 现状事实 |
|---|---|---|
| M7-U1 | **真实凭据逐产品登录/领取** | 仍未实测（承 §22.11 U1）：本轮回跳接收端、向导、行内操作全部是**假上游 / fixture** 证据，没有一条真凭据出证 |
| M7-U2 | **二维码 / 短信的本机侧未完工（机制 B）** | `qr_payload` 型（raccoon）只在界面原样展示 + 复制/打开，**本机不生成二维码图片**（`accounts.js:935-947`，不伪造图片）；短信通道若要求图形验证码/滑块，向导未内置该环节（`:984` 明写"请改用主形态登录"）——要走完这两型需引入本地 QR 编码器与图形验证码流程，未做 |
| M7-U3 | **BD3b `unservable_reason` 按产品/账号出口未落地** | 面板上方「转发未接线」`.alert.alert-info` 因此**不显示**（判据只在装配侧 `main.py:493`，无账号级出口，前端不硬编码产品 id —— `accounts.js:1171`） |
| M7-U4 | **BD5 每账号 `last_op` 未落地** | 「最近运营」列**整列不出现**；运营报告行仍只写账号名、不带 `product`（`ops/runner.py:394-401`，跨产品同名会认错）—— 补它牵动 `ops/runner.py` 与落盘形态，不在本轮范围（`accounts.js:1173`） |
| M7-U5 | **窄屏 rail 缺陷只修了本页** | `base.css:1123-1129` 的 ≤768 条带**作用域限 `.panel-split`**，而只有 `accounts.js:182` 用它；`resources.js:164-181` / `models.js:102-123` 仍自带内联 gutter 副本 → 那两页在窄屏**保持 248px 固定栏的老缺陷**（设计书 §4-3 的"三处收口"只收了一处） |
| M7-U6 | **zcode 桥接 URL 重写 / 状态取值来源（D 系列）未动** | 承 M6：`zcode` 直连 405/3012（§22.11 D1/U2）与 `ZCODE_DESKTOP_*`（T10）原样未碰，本轮零改动 |

### M7 计数与复跑口径

- **计数**：1464 → 1520 → **1560 passed / 0 failed**（README 双语同值 1560，`AGENTS.md` M6 段同值）。
  - 数字**取自本轮全量跑自己的输出行**，非估算：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/ -q -p no:cacheprovider --basetemp=/tmp/…` →
    `1 failed, 1560 passed, 1 skipped, 911 warnings in 369.16s (0:06:09)`；那 1 红项正是钉这个数字的 `tests/unit/test_v2_readme_claims.py::test_readme_test_counts_are_not_stale` 本身（它拿 `--collect-only` 的实收数对比 README 旧值），同步到 1560 后复跑该文件转绿（含版本三元组 README / `mgw --version` / `pyproject.toml` = 0.2.0 一致的判据）。
  - 1520 → 1560 的 +40 来自 M7-C/M7-D 两波：`tests/accounts/test_qr_image.py`（服务端出图 + 213 字节上限）、`test_zcode.py` 44→46（桥接页改写、state 取源、回跳副通道、串线拒收，含我补的两条正向判据）、`test_raccoon.py` / `test_loomy.py` 换码与长轮询判据。未逐项拆到个位，不充数。
- **门本身**：`node scripts/verify_accounts_ui.mjs` → `合计：13 通过 / 0 失败`（exit 0；第 13 条 = 扫码型必须渲染恰一个 `<img src="data:image…">`）；`--mutation` → `可红 8/8；8 条判据全部可证伪`（exit 0）。两条都已在 pytest 里复跑。


