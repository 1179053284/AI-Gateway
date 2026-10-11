# M6-R1 独立评审报告 · 后端/公共层与产品钩子（对抗式）

> 角色：独立评审 R1（对抗式，只读主树；不改任何源码）
> 评审对象：`docs/specs/tech-design.md` §22（v2.0 增量，多产品账号接入）契约 + 下列实现：
> - 公共层 `model_gateway/accounts/{types,registry,store,device,login,net,materialize}.py`
> - 产品层 `model_gateway/upstream/<product>/{product.py,*}`（10 产品）
> - 接缝 `model_gateway/ops/runner.py`、`api/admin_accounts.py`（取用点）与 `adapters/product_out.py`
>
> 证据基准：`docs/research/20`（DSH 取证，源 `…/05-dsh插件/deepseek-harness-codearts/src/`，只读）与 §22.4 矩阵
> 快照时间：2026-09-30（工作树含未提交的 M6 增量；HEAD = 5158cbc）
> 评审方法：静态通读 + 契约逐条对表 + `pytest` 复跑（全量 1371 passed）+ /tmp 复制品**变异实验**（7 组"真能红"+1 组"红不了"）+ 跨层交叉核对 + 过期会话攻击实验
> 硬约束遵守：主树只读（唯一写入 = 本报告）；未触碰 :8300 / `model_gateway/data/**` / 真实上游；实验全部在 `/tmp/m6r1-repo` 复制品；`pytest --basetemp=/tmp/m6r1-*`

---

## 结论

**不通过（1 项严重/阻塞；命中 §22.8 硬清单第 2 条与 §22.7 错误语义表）**

- 基线：`pytest` 全量 **1371 passed**（324s）复现，测试工程量大、多数用例经得起变异（见下）；契约签名面（§22.3 十钩子、`_HOOKS`/`_ALT_HOOKS`、`pending` 非错误、`NotRefreshable`、三态额度）**逐条对表基本一致**。
- 但不能无条件通过：**alt（备选登录）通道完全绕过会话 TTL/取消**（实测：`expired=True` 的会话仍能完成登录并落盘凭据），且 `api/admin_accounts.py` 模块头声称的「会话不存在或已过期 → 404」对 alt 不成立；另有 4 项中度契约偏差与 1 项"测试红不了"的护栏虚置。

---

## 发现

### F1【严重 · 阻塞】备选登录通道（`alt`）绕过会话 TTL 与取消；「已过期 → 404」契约不成立

- 落点：`model_gateway/accounts/login.py:320-345`（`alt_call` 全程不查 `session.expired()`/`cancelled`），`model_gateway/api/admin_accounts.py:185-203`（`_session_of`/`_require_session` 只查存在性）、`:25`（模块头错误语义表："会话不存在或**已过期**（alt 必须拿到会话对象） | 404"）。
- 复现（/tmp 复制品实测，无改码）：
  ```
  构造 LoginSession(created_at=0.0, ttl_s=600) → session.expired(now) = True
  替换 raccoon._ALT_HOOKS["sms_submit"] 为返回 success 的假钩子（模拟短信第二段成功）
  await login.alt_call("raccoon", session, "sms_submit", phone=..., sms_code=...)
  → 返回 success；<root>/expired-acc/credentials.json 已落盘：{"access_token": "SMS-OK"}
  ```
- 为什么违反契约：§22.8-2「登录会话有 TTL 与取消（默认 10 分钟）」是**硬清单**；§22.7 错误语义表要求 alt 对过期会话给 404。poll/callback 走 `_advance` 有 TTL 检查（`login.py:246-252`），唯独 `alt_call` 没有 —— 过期/僵尸会话仍可完成登录并写凭据（`_commit_outcome`）。
- 修复方向（供修复轮，不代做）：`alt_call` 增加与 `_advance` 同源的 expired/cancelled 判定（返回结构化「会话已过期」或让入口层 404）；补一条"过期会话的 alt 必被拒"的回归用例。

### F2【中】`_looks_retryable` 与 M6 产品失败文案不匹配 —— 产品通路上的网络类失败**不会**退避重试

- 落点：`model_gateway/ops/runner.py:314-317`（判据 = 详情以 `network:` / `timeout:` 开头或含 `http 5`）；生产方（zcode 侧）遵守该前缀（`ops/builtin/zcode_claim.py:226`），但 M6 产品钩子一律用中文文案：`upstream/buddy/hooks.py:320`「签到请求网络错误：…」、`upstream/trae/claim.py:204`「签到请求网络错误（可重试）：…」、`upstream/loomy/credits.py:233`、`upstream/raccoon/credits.py:152` 等。
- 实测（复制品内执行）：
  ```
  _looks_retryable("签到请求网络错误：ConnectError: refused") -> False
  _looks_retryable("签到请求网络错误（可重试）：ReadTimeout") -> False
  ```
- 为什么违反契约：§22.6「失败退避仅网络/5xx、业务码不重试」与 §22.8-10（429/网络退避 `[500,1500,4000]ms`）在 `POST /admin/api/accounts/{product}/{name}/claim` 通路上对 9 个新产品**整体不生效**（`_run_one` 只看详情前缀）；现有用例用的是「规范化前缀」的假失败（`tests/unit/test_v2_ops.py:61-64,178`），覆盖不到真实产品文案，属断言与生产语义脱节的盲区。

### F3【中】buddy/workbuddy 出站身份头与 DSH 取证冲突：`X-Product` 发了 DSH 明说"发错导致归因失败"的 `SaaS`；且引用行号错误、"未取证"判断不实

- 落点：`model_gateway/upstream/buddy/protocol.py:176-206`（`identity_headers`，同时供**计费/签到面**与**推理面**使用：`hooks.py:237/271/298` 与 `out.py:60`）、`model_gateway/upstream/buddy/out.py:7-17`（取证清单）。
- DSH 对照（只读复核）：`buddy-adapter.ts:1564-1580`（推理 `send()`）明确 `headers.set(HTTP_HEADER_PRODUCT, this.product.attributionName)` 并注释「**X-Product 是归属名（产品名），不是部署类型 —— 历史实现发成 `SaaS` 导致后台归因不到产品**」；`product.ts:113-118` 把该语义写进字段文档（`attributionName: 'CodeBuddy'` / `'WorkBuddy'`，`product.ts:278/401`）。计费面（`buddy-oauth.ts:361-363`、`credits.ts:236`）确实用 `BUDDY_DEPLOYMENT_TYPE='SaaS'` —— 网关把**计费面的取值套到了推理面**。
- 另两处证据问题：① `out.py:12` 引 `buddy-adapter.ts:1089-1126` 作为 `Authorization/X-Domain/X-Product*` 的出处 —— 该区间实为 `resolveCallWithInfo` 的 maxTokens/reasoning 代码（我逐行读过），头构造在 `:1564-1580`；② `out.py:15` 称 `X-IDE-Name/Type/Version`「**未取证具体取值** → 不发」——取值在源里是明确的（`X-IDE-Name/Type=attributionName`、`X-IDE-Version=clientVersion`、`X-Agent-Purpose: conversation`），"取不到"的判断不成立；DSH 注明缺这组头后台「使用端」显示 `-`。
- 影响：请求可通，但上游用量归属可能整体记不上（DSH 已把它当已修 bug 对待）；属"证据编造/留白违规"类（引用行号错 + 把可取证写成未取证），需按 §22.11 口径修正注释并决定是否补齐头。

### F4【中】骨架纪律护栏被"文件名豁免"虚置：`qodercn.login_callback` 改成**编造 success**，483 个账号用例（二轮 519 含管理端集成）全绿

- 落点：`tests/accounts/test_registry.py:47-68,155-211`（`_implemented_hooks`：产品只要存在 `test_<product>.py` 就"整体让位"，护栏不再断言任何钩子）。
- 变异实验（/tmp 复制品，两次独立复现）：把 `qodercn/product.py::login_callback` 的返回值改成 `LoginOutcome(state="success", credentials={"access_token": "FAKE", ...})`（= 断言文档里最典型的"写一半的假实现"）→
  - 第一次：`pytest tests/accounts/` **483 passed**（零红）；
  - 第二次（干净复制品）：`pytest tests/accounts tests/integration/test_admin_accounts.py tests/integration/test_qodercn_out.py tests/integration/test_qoder_out.py` **519 passed**（零红）。
  `qoder`/`qodercn` 恰好未声明 `_IMPLEMENTED`，完全走文件名豁免；`grep -rn "login_callback" tests/integration/*.py` 无任何命中（非 local_callback 产品的回跳拒绝在两套测试里都没有判据）。
- 为什么是问题：该用例的 docstring 承诺「未接线的钩子必须显式 NotImplementedError，**不得**返回编造值」（题面），但豁免机制让"已接线"的判定与**行为判据归该文件**的承诺脱钩（断言目标与题面无关的形态）。对"假实现"的拦阻在 9 个产品上实际失效。

### F5【中】§22.8-4 的「跨进程 fail-closed 互斥」未落到账号/配置写盘面

- 落点：`model_gateway/accounts/materialize.py:23-25`（自认："跨进程（CLI 导入 + 服务端登录同时发生）仍可能丢更新 … 登记为残留契约项"）；`accounts/store.py:259-294`（`commit_login` 只在**进程内**无锁；tmp+rename 保证单文件原子，但不防跨进程丢更新）；只有 `ops/runner.py` 的 `AccountLocks` 是 fail-closed 落盘锁（S-22 口径）。
- 为什么违反契约：§22.8-4 是硬清单条目（"写盘唯一入口 + 原子写；跨进程（CLI / cron / 服务）用既有 fail-closed 互斥"），当前在"登录物化资源"与"账号目录写入"两条新写路径上**没有**任何跨进程互斥（CLI `mgw zcode import`/未来账号 CLI 与服务端登录并发 → 后者覆盖前者，静默丢资源/丢元信息）。代码注释承认了，但没有降级判据、也没有修复波次。

### F6【轻】账号级 `runtime.json` 无生产写入方；产品 `quota` 钩子在 9 个新产品上无生产调用点

- 事实：`write_runtime` 全仓无生产调用（仅 `accounts/store.py` 定义 + `__init__` 导出 + 测试）；`read_runtime` 只在 `api/admin_accounts.py:317` 被读。§22.2 布局里 `runtime.json`（冷却/最近错误/水印）与 §22.8-5「运行态内存权威 + 落盘快照」因此处于"只读结构"状态。
- 关联：`ops/builtin/query_balance.py:23` 的 `SUPPORTED_PRODUCTS=("zcode",)`（`zcode_claim` 同）→ §22.5-6「余额快照由 ops tick 后台刷新后 `set_quota`」只覆盖 zcode；10 个产品的 `quota` 钩子（M6-2/M6-3 已实现+单测）没有任何入口调用（无 API、无 ops 操作），账号页"额度"列对新产品恒 `unknown`（fail-closed、不谎报，但契约的刷新链路是断的）。
- 另：前端已自登记 `claim_onboarding` 无端点（`web/static/js/pages/accounts.js:776-781`）——与上同族：产品层已实现、入口层未接。

### F7【轻】`claim_onboarding` 注册面两家分裂（loomy 进 `_HOOKS`，raccoon 放 `_OPTIONAL_HOOKS`），且无消费方

- 落点：`upstream/loomy/product.py:180-193`（11 项 `_HOOKS`）vs `upstream/raccoon/product.py:324-340`（10 项 `_HOOKS` + `_OPTIONAL_HOOKS`）。§22.3 只说"可选"，没规定注册面；`_OPTIONAL_HOOKS` 全仓无消费者（仅测试断言），raccoon 注释称"入口层按 `Capabilities.onboarding` 发现它（模块级同名函数）"——这与本项目"不给字符串 `getattr` 后门"的纪律（`login.py:99-109`、`admin_accounts.py:157-170`）自相矛盾：现有入口层要么按表取（raccoon 的表没人读），要么 `getattr`（被禁）。
- 影响面小（M6-4 未接 UI 端点），但"唯一发现点"的承诺不成立，后续接线必须先收敛注册面。

### F8【轻】§22.6 的 operation 命名收敛（`claim`/`query_balance`，`zcode_claim` 保留为别名）未实施

- 事实：`ops/builtin/__init__.py:10-23` 的键仍是 `zcode_claim`/`query_balance`（`zcode_claim.py:26` `OPERATION_ID="zcode_claim"`），无 `claim` 操作；调用方（`main.py:159`、`cli_zcode.py:230`）按 `zcode_claim` 取。规格文字（§22.6 末条）未落地，也无别名映射。

### F9【轻】单飞粒度：规格写「按产品单飞」，实现是「按会话单飞」

- 落点：`accounts/login.py:233-244`（`_inflight` 键 = `session_id`）。同一产品的两个会话并发轮询会各打一次上游。按会话单飞在语义上更正确（两个会话是两次登录），但**与 §22.8-3 的字面表述不一致**，且无测试/注释说明该裁决——评审按条文对表时属"契约与实现不一致"。

### F10【轻】引擎层不校验「会话 ↔ 产品」配对（防串线只在入口层与 `alt_call`）

- 落点：`accounts/login.py:191-199`（`poll`/`callback` 直接 `_advance(product=入参, session_id)`，`_advance` 用入参产品取钩子、用 `session.product` 落盘）。当前唯一生产调用方 `admin_accounts.py:398-424` 有 400 校验，因此**不可达**；但 `LoginEngine` 是公共层公开类型（`accounts/__init__.py` 导出），约束靠调用方自觉，属纵深防御缺口（`alt_call` 自己做了这层校验，poll/callback 没做，家族内不一致）。

### F11【轻】zcode 导入路径仍是"非原子 + 非唯一入口"写盘（§22.1 零重写的遗留，但 §22.2 不变式①②⑤ 未标注例外）

- 落点：`upstream/zcode/store.py:183-207`（`_commit` → `dataroot._write_json` 用 `Path.write_text`，凭据用 `dest.write_text` 直写 v2 目录），`upstream/zcode/dataroot.py:66-68`。§22.1 说 zcode 零重写，§22.2 又写"全明文 + 原子写（tmp+rename）""落盘只经 `accounts/store.py` 唯一入口"，两处口径没有互相背书/豁免标注——现状按"既有实现豁免"理解可通，但条文层面留白（建议在 §22.2 显式登记例外或统一委托）。

---

## 反例清单（≥5 条；F1-F5 有红证，"风险在这"类已标注）

| # | 反例（一句话） | 红证/依据 | 类型 |
|---|---|---|---|
| R1 | 过期/未取消的登录会话仍可经 `alt` 完成登录并落盘凭据（TTL 被绕过） | 实测：`expired=True` 的会话 `alt_call` 返回 success 且写出 `credentials.json` | 已证实（F1） |
| R2 | 产品 claim 的网络类失败**不触发**退避重试（详情文案与 `_looks_retryable` 约定脱节） | 实测：真实产品文案 → `_looks_retryable=False` | 已证实（F2） |
| R3 | 推理面 `X-Product: SaaS`（DSH 明示这是"归因不到"的历史 bug 值）；引用行号错、"未取证"判断不实 | DSH 源 `buddy-adapter.ts:1564-1580` / `product.ts:113-118` 对照 | 已证实（F3） |
| R4 | "写一半的假实现"可零红通过：`qodercn.login_callback` 编造 success，483/519 用例全绿 | 变异实验（两次独立复制品） | 已证实（F4） |
| R5 | 并发写盘（CLI 导入 × 服务端登录）无跨进程互斥 → 静默丢资源/丢元信息 | 代码自认（`materialize.py:23-25`）+ 无文件锁实现 | 已证实（F5） |
| R6 | 产品 `quota` 钩子/账号 `runtime.json` 无生产通路 → 账号页额度列对新品恒 unknown（若上游凭据有效但额度已耗尽，用户看不到"耗尽"信号） | grep 零调用点 | 风险（F6） |
| R7 | 若 meta.json 损坏，设备查重把它当"不占用" → 同一设备 ID 可能被第二个账号复用（§15.1 硬约束 1 的 fail-open 边界） | `device.py:35-47`（读不动返回 `{}`）+ `find_account_by_values` 口径；**未构造红证**（需策略裁决：fail-closed 会阻断导入） | 风险（未证伪） |
| R8 | `onboarding` 能力位 true 但功能不可达（无端点）+ 两家注册面分裂 | `accounts.js:776-781` 自登记 + `_OPTIONAL_HOOKS` 无消费者 | 风险（F7） |
| R9 | `poll/callback` 在引擎层不校验会话产品配对（当前入口层有校验，属纵深防御缺口） | `login.py:191-199` 读码 | 风险（F10） |

---

## 变异实验记录（"真能红"清单，全部在 /tmp 复制品执行）

| # | 变异 | 目标用例 | 结果 |
|---|---|---|---|
| 1 | `device.generate_unique` 删除"多字段显式报错"守卫 | `test_device.py::test_generate_unique_refuses_multi_field_spec` | **红**（1 failed / 25 passed） |
| 2 | `store.commit_login` 删除失败回滚（`_rollback` 调用） | `test_store.py` 三条回滚/自检用例 | **红**（3 failed） |
| 3 | `login._single_flight` 去掉在飞复用 | `test_login_engine.py::test_concurrent_poll_is_single_flight` | **红** |
| 4 | `materialize.ensure_resource` 去掉幂等命中 | `test_materialize.py` 两条 | **红** |
| 5 | `trae/claim.py` claim 后状态复核改为恒真 | `test_trae.py::test_claim_code_zero_*` 两条 | **红** |
| 6 | `ops/runner._run_one` 对所有失败都重试 | `test_v2_ops.py` 两条 | **红** |
| 7 | `buddy/hooks.py` quota 的 unknown 分支改 exhausted | `test_buddy.py::test_quota_unknown_never_zero[route2/4]` | **红** |
| 8 | `qodercn.product.login_callback` 改成编造 success | 全部 `tests/accounts/`（483） | **全绿 → 见 F4（护栏盲区）** |

抽查结论：8 组里 7 组目标用例真能红（断言与题面相关、非循环自证）；第 8 组精确定位了豁免机制的盲区（详见 F4）。逐条读过断言的用例还包括：`test_login_engine.py::test_pending_is_not_an_error_and_session_survives`（状态机语义真断言）、`test_trae.py::test_derive_device_id15_*`（**独立重写**参考算法做对照，非实现自证）、`test_qodercn.py::test_cn_hook_refuses_intl_credentials_without_upstream_call`（断言"零上游"而非只断言异常）、`test_admin_accounts.py::test_no_credential_in_any_response`（扫全部响应文本）——均未发现"永真断言 / 循环自证 / 断言目标与题面无关"（唯一形态问题是 F4 的豁免机制）。

## DSH 取证抽查（file:line 复核，只读）

| 网关断言 | DSH 源实况 | 结论 |
|---|---|---|
| buddy 基址 `product.ts:271` | `endpoint: 'https://copilot.tencent.com'`（`product.ts:271`） | ✓ |
| workbuddy 基址 `product.ts:384` | `endpoint: 'https://www.workbuddy.ai'`（`:383-384`） | ✓ |
| trae Agent 基址 `trae-product.ts:155` | `TRAE_AGENT_HOST='https://trae-api-cn.mchost.guru'`（`:155`） | ✓ |
| qoder 加密基址 `qoder-product.ts:445`；CN `:604` | `encryptedInferBase:'https://api2.qoder.sh'`（`:445`）；CN 同字段 `:604` | ✓ |
| lobsterai 基址 `lobsterai-product.ts:63` | `LOBSTERAI_API_BASE='https://lobsterai-server.youdao.com'`（`:63`）；门户 `:77` 同值口径 | ✓ |
| buddy 推理身份头出处 `buddy-adapter.ts:1089-1126` | 该区间是 `resolveCallWithInfo()`（maxTokens/reasoning），头在 `:1564-1580` | ✗（见 F3） |
| `X-Product` 语义 = 部署类型（两产品共用） | 计费面 `buddy-oauth.ts:361-363` ✓；**推理面** `buddy-adapter.ts:1575-1577` 用 `attributionName`，并注明 `SaaS` 是历史 bug | ✗（见 F3） |
| 「X-IDE-Name/Type/Version 值未取证」 | `buddy-adapter.ts:1573-1576` + `product.ts:113-118` 给出取值来源 | ✗（见 F3） |
| trae `deriveDeviceId15` 移植（`trae.ts:324-381`） | 逐字节对照 `seededStream/seededDigits`：SHA256(utf8("salt:seed")++counterBE32)、byte%10 → 与 `upstream/trae/protocol.py:106-131` 等价 | ✓（且测试用独立重写对照） |
| qoder 幂等 = `replayed:true`、claim 空体 | `qoder-credits.ts:53-57,541-577`；`body:''`（`:559`）→ 网关 `content=b""` | ✓ |

## §22.8 十条硬清单逐条落点（本轮评审口径）

| # | 条目 | 落点/结论 |
|---|---|---|
| 1 | 上游调用显式超时、不阻塞事件循环 | ✓ `accounts/net.py:18-32` + 各产品 `make_client`；grep 无 `requests/time.sleep`（`subprocess`/`time.sleep` 仅存在于 zcode `dataroot.py` 的 CLI 启动路径，不在事件循环） |
| 2 | 会话 TTL 与取消、无孤儿任务 | **✗ 部分**：poll/callback ✓（`login.py:246-252`）、atexit ✓；**alt 通道无 TTL/取消检查**（F1） |
| 3 | 登录单飞/运营串行+抖动 | 部分 ✓：运营串行+抖动 ✓（`runner.py:472-478`）；单飞=按会话（见 F9，与条文表述不符） |
| 4 | 写盘唯一入口+原子写；跨进程 fail-closed 互斥 | 部分 ✓：原子写 ✓（`store.atomic_write_json`）；跨进程互斥 ✗（F5；zcode 导入遗留见 F11） |
| 5 | 运行态内存权威+落盘快照；读不动 fail closed | 读侧 ✓（`read_runtime` 抛 `RuntimeUnreadable`，视图降 unknown）；**写侧无生产方**（F6） |
| 6 | 失败隔离（凭据解析在 try 内） | ✓ `admin_accounts.py:542-557`、`runner.py:328-341` |
| 7 | 适配器换绑延迟排空 | ✓ `main.py:312-320,365-369`（`_retire_adapters` + 宽限=总预算）；复用判据含 `product+account_ref+凭据指纹`（`main.py:331-353`） |
| 8 | 日志脱敏（凭据只短哈希） | ✓（`net.cred_fingerprint`+`store.commit_login` 日志；grep 无凭据入日志） |
| 9 | 内存有界（会话表/在途表清理） | ✓（终态出表 + `start` 扫过期 + `_inflight` finally 清理；`_sweep` 仅在 `start`——见「未验证」注） |
| 10 | 429 退避 `[500,1500,4000]ms`；业务码不重试 | 部分 ✗：序列 ✓；但 M6 产品通路的网络类失败因 F2 **不触发**退避重试 |

---

## 未能证伪的尝试（试过但没打穿）

1. **`_ALT_HOOKS` 后门**：尝试用字符串名让 `login.alt_call` 走到 `getattr` 路径 → 表外名字当场 `KeyError`（`login.py:133-148`），未导出表 → 可读 `RuntimeError`；未打穿。
2. **`hook_meta` 锚字段被 meta.json 污染**：构造 `{"account": "evil", "dir": "/tmp/evil"}` 的 meta.json → 锚字段写在最后、以文件为准的合并方向正确，钩子拿到的仍是白名单后的本账号目录；未打穿（`store.py:207-212`）。
3. **多字段设备身份旧缺陷复现**（"单值候选比完整元组 → 查重恒过"）：现实现对多字段显式报错 + 逐字段比对，变异实验 1 证明守卫是可红的；未打穿。
4. **三态额度被压成两态**：把 buddy quota 的 unknown 分支改成 exhausted → 用例红（变异 7）；`raccoon/loomy/trae/qoder` 的 unknown 分支抽查亦为显式 `unknown`；未打穿。
5. **`pending` 被当错误**：`_advance` 对 `pending` 保留会话、API 原样透传、前端只显示"等待中"；尝试在 hook 返回非 pending/success 的未知 state（如 "expired"）→ 引擎按终态出表（合理）；未打穿。
6. **写回自检的"过期元信息"再次触发 500**（P-B1 同族）：`_verify_written` 以 `merged` 为基准（`store.py:447-474`），用 P-B1 用例复跑 + 我构造带旧 `updated_at` 的二次提交均通过；未打穿。
7. **凭据从 API 泄漏**：视图走 `_META_DISPLAY_KEYS` 白名单 + 专门用例扫全部响应；未打穿。
8. **`NotRefreshable` 被吞成 500**：`_endpoint` 的 except 顺序（`NotRefreshable` 在 `RuntimeError` 之前）正确；loomy/zcode 抛 `NotRefreshable`，trae/buddy 终态映射亦为 `NotRefreshable`；未打穿。
9. **模型转发的适配器复用分叉（S-14 同族）**：改绑 `account_ref`/重登（凭据指纹变）→ 复用判据含 `product+account_ref+指纹`，会重建；未打穿。
10. **导入改写源文件**：`import_account` 只读源（`_load_payload`），用例含逐字节不变断言；未打穿。

## 未验证（本轮未能覆盖/需后续）

- **§22.8-9 的极端面**：`LoginEngine._sweep()` 只在 `start()` 被调用；若上游长期只 poll/alt 不 start，过期会话靠 poll 触发出表——"无人轮询的过期会话"会滞留在 `_sessions` 直到下一次 `start`（内存仍被 TTL 限制在有限数量级，但"有清理"依赖调用模式）。未构造长跑实验证伪/证实。
- **`account_claim` 的 `runtime` 透传**：`_claim_once` 显式 `del manual, runtime`，产品 claim 拿不到风控熔断 runtime（zcode 由 `zcode_claim` 内部自带）。M6 产品是否需要熔断接线未见规格条目，未判违规。
- **真实上游行为**（各产品 `base_url`、`X-Product` 归因、短信通道、验证码）：按 §22.11 属用户驱动实测，本轮全部用假上游/只读源论证。
- **§22.4 中未逐条复证的产品**：lobsterai 三步 `check_in`、loomy 两池额度、raccoon `granted` 语义只做了源码与用例级核对（用例质量抽查在变异集内），未逐条回 DSH 源复核每个 `file:line`。
- 主树工作区含大量未提交改动（M6-4/M6-5 进行中），本报告基于该快照；修复轮合入后需复核 F1-F11 的落点行号漂移。
