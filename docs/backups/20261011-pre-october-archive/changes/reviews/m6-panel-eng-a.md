# M6 交付验收面板 · eng-a（后端核心 · 独立评审）

> 角色：eng-a（后端正确性 + 反证），独立评审，**非实现方**；交付闸门：零阻塞才算通过。
> 评审对象：M6 = Q29（`docs/specs/prd.md` §9 / `docs/specs/tech-design.md` §22）。
> 台账：`docs/changes/e2e-records/E2E-20260930-M6-multi-product.md`；前序评审：`m6-r1-backend.md`、`m6-r4-discipline.md`。
> 纪律：/tmp 复制品工作（主树只读）；唯一仓库写入 = 本文件；`--basetemp=/tmp/m6ea-$$` + `-p no:cacheprovider`；
> 不碰 `data/`、`:8300`、真实上游；未验证与已验证严格分开。
> 快照：HEAD = 5158cbc（工作树含全部 M6 未提交增量）；报告已完稿（04:2x CST）。

---

## 结论

**通过（0 阻塞；附 1 条交付前须收口的文档/口径更正 A-1，不计阻塞，理由见下）**

- **抽验 4 条修复全部真实**（§1）：撤修复 → 逐条红（A/E 行为级 + 用例级），恢复 → 绿；
  其中 R1-F1 用原始攻击形态复现了"过期会话落盘 `credentials.json`"、R1-F5 用真两进程交错复现了丢更新。
- **§22.8 十条**：8 条 ✓；#1 部分（A-1）、#3 部分（A-2 口径未登记）。契约面（types/ops/store/registry）
  逐条对表一致（§3）；死代码/双账未发现"两处各写一份的核心规则"（§4）；测试质量抽读 7 例全为真断言、
  7 组变异全部按预期红/绿（§5）；全量 **1422 collected**，复制品跑出的 6 条全为"复制品不完整"伪红、
  已逐条复证 → 台账"1422 passed / 0 failed"成立（§5.3）。
- **A-1（最强项，非阻塞）**：`accounts/store.py:322,397` 的 `time.sleep` 落在异步服务路径
  （`POST /admin/api/accounts/login/{poll,callback,alt}` → `login._advance::_commit` → `store.commit_login` 等锁），
  实测可把事件循环阻塞 **1007ms**；tech-design §22.8-1 的例外登记与 R4 §3.1 的"不在异步服务路径"结论**失实**。
  不计阻塞的理由：等待**有界**（≤`_LOCK_WAIT_S` 1.0s，典型毫秒级——持锁者的写盘本身就是毫秒级；
  1s 只在持锁进程僵死一档出现）、无数据面后果、且同族的"同步写盘 + fsync"本就被既有口径接受。
  **但必须收口**（二选一，成本极低）：① 落盘下放 `asyncio.to_thread`（或等价不阻塞等待）；
  ② 更正 §22.8-1 例外登记（与 dataroot 并列，写明上界与触发条件）并更正 R4 §3.1。
  **若面板裁决按 §22.8-1 字面从严执行 → 本项升格为 1 阻塞**（本角色提供完整证据与两条收口路径，供裁决）。
- 非阻塞发现 6 条（低度）：A-2 §22.8-3 单飞口径（按会话 vs 按产品）未登记；
  A-3 `zcode_claim` 全异常 blanket `retryable=True` 与产品路径 `is_transport_failure` 两套口径；
  A-4 `all_accounts(products=None)` 缺省分支半死；A-5 两处 `ClaimOutcome→OpResult` 桥接（双账风险）；
  A-6 `_IMPLEMENTED` 是"声明即信任"（实测伪造声明护栏不红、产品单测兜住——设计如此，登记即可）；
  A-7 `write_runtime` 读-改-写不取全局锁（文档已声明的取舍：运行态权威在内存）。
- 未验证面见 §6（真实凭据/真实上游等 §22.11 全部未实测）。

### 发现清单（供修复轮直接用）

| # | 级别 | 发现 | 落点 | 建议 |
|---|---|---|---|---|
| A-1 | **最强项（非阻塞；字面从严则升格阻塞）** | 等锁 `time.sleep` 阻塞事件循环 ≤1.0s（实测 1007ms；典型毫秒级）；§22.8-1 例外登记与 R4 §3.1 结论失实 | `store.py:322,397`；链路 `login.py:300-310` ← `api/admin_accounts.py:404-462` | 下放线程 / 或更正例外登记与 R4 表述（交付前必收口） |
| A-2 | 低 | §22.8-3 字面「按产品单飞」vs 实现「按会话单飞」未裁决未登记（R1-F9 未闭环） | `login.py:28,272`；spec `tech-design.md:1678` | 改 spec 字面（按会话更正确）或加裁决注记 |
| A-3 | 低 | `zcode_claim` 外层 `except Exception` 一律 `retryable=True`（非网络异常也退避重试） | `ops/builtin/zcode_claim.py:225-230` | 改用 `product_hooks.is_transport_failure(e)` |
| A-4 | 低 | `all_accounts(products=None)` 缺省分支无生产调用者 | `ops/runner.py:381-403` | 删缺省或标注仅供测试 |
| A-5 | 低 | `ClaimOutcome→OpResult` 两处桥接，归一化规则不完全一致 | `product_claim.py:130-132` vs `admin_accounts.py:566-570` | 收敛为一个 helper |
| A-6 | 登记 | `_IMPLEMENTED` 只被护栏读取、属"声明即信任"；伪造声明时护栏不红（实测），由产品单测兜住 | `tests/accounts/test_registry.py:67-77` | 维持（分层已有兜底），但别再据此推断"已接线=已验证" |
| A-7 | 登记 | `_write_quota_cache` 的读-改-写不取全局锁（并发写者可能丢 `quota` 键；文档已声明运行态权威在内存） | `query_balance.py:110-133`；`store.py:504-513` | 维持（下次 tick 重写）；如遇问题再并入锁 |


---

## 1. 修复真实性抽验（4 条）

复制品：`/tmp/m6ea-repo`（基线）＋ `/tmp/m6ea-e1..e4`（各撤修复变异）。解释器 = 主树 `.venv/bin/python`；
`--basetemp=/tmp/m6ea-*`、`-p no:cacheprovider`、`PYTHONDONTWRITEBYTECODE=1`；主树零写入。

### 1.1 R1-F1 `alt_call` 绕过会话 TTL/取消（严重·阻塞）

- 修复落点：`model_gateway/accounts/login.py:389-391`（`_gate` 共用闸门）＋ `:393-394`（成功走 `_commit_outcome`）。
- 撤修复（e1）：删 `blocked = _gate(...)` 三行 → 行为级攻击脚本（`session.created_at=0.0, ttl_s=600`，
  `expired(1e6)=True`，`loomy._ALT_HOOKS["sms_submit"]` 换假 success）；
  命令 `PYTHONPATH=/tmp/m6ea-e1 python /tmp/m6ea-e1-attack.py`（基线对照把 PYTHONPATH 指向 `/tmp/m6ea-repo`）：

  | 副本 | 观察 |
  |---|---|
  | e1（撤修复） | `outcome.state = success`；`credentials.json exists = True`，内容 `{"token": "SMS-OK"}` —— **过期会话仍完成登录并落盘**（复现 F1 原文攻击） |
  | 基线（未撤） | `outcome.state = expired`、`detail = 会话超时（600s）`；`credentials.json exists = False` |

- 用例级红证（e1）：`pytest tests/accounts/test_login_engine.py -k alt_call` → **2 failed**
  （`test_alt_call_refuses_expired_session_and_persists_nothing`、
  `test_alt_call_refuses_cancelled_session_and_persists_nothing`），与台账「撤修复 → 过期会话仍落盘（2 failed）」**逐字相符**。
- 恢复后绿：基线同文件 74 passed（含上述两条）。
- **判定：修复真实（双向可复现）**。

### 1.2 R1-F5 跨进程写盘无 fail-closed 互斥（中）

- 修复落点：`accounts/store.py:238-431`（`_AccountsWriteLock` 全局一把 `data/locks/accounts.lock`）＋
  三条写路径持锁 `:539`（`commit_login`）/`:631`（`import_account`）/`:679`（`delete_account`）。
- 撤修复（e2）：把模块级单例 `_WRITE_LOCK = _AccountsWriteLock()`（`:431`）替换成 no-op 上下文管理器。
- 用例级红证（e2）：`pytest tests/accounts/test_store.py` → **5 failed / 30 passed**，与台账「撤锁 → 5 failed」相符：
  ```
  FAILED ...::test_write_is_refused_while_another_process_holds_the_lock
  FAILED ...::test_lock_released_after_write_and_stale_lock_reclaimed
  FAILED ...::test_lock_dir_unusable_fails_closed_with_readable_error
  FAILED ...::test_lock_covers_the_materialization_config_save
  FAILED ...::test_interleaved_second_process_write_is_refused_and_nothing_is_lost
  ```
  其中真两进程交错用例的失败消息即"静默丢更新"的可观测化：
  `第二个进程没有被拒（跨进程互斥失效 → 丢更新）：stdout='WROTE\n'`（子进程返回码 0 = 写成功）。
- 恢复后绿：基线 `tests/accounts/test_store.py` 全绿（74 passed 批内）。
- **判定：修复真实**。注：锁为全局一把、`_LOCK_WAIT_S=1.0s` 后拒写（fail closed 语义已核，见 §3.3）。

### 1.3 R2-B-2 401 判死资源不可复活（阻塞）

- 修复落点：`accounts/materialize.py:99`（`_nudge_reload(path)`，命中既有资源时前推配置 mtime 驱动既有热重载）
  ＋ `:217-239`（前推实现）+ `main.py:312+`（既有 `_apply`/复用判据含凭据指纹）。
- 撤修复（e3）：删 `materialize.ensure_resource` 命中分支里的 `_nudge_reload(path)`。
- 用例级红证（e3）：`pytest tests/integration/test_m6_revive.py`
  → **1 failed**（`test_relogin_revives_without_extra_actions`），失败断言：
  `AssertionError: 重登后仍 disabled —— 用户按提示操作却永远 503（B-2 残差）`（`test_m6_revive.py:196`）。
  另一条（`test_ops_cron_covers_new_products_accounts`，属 Fix-η-② 面）保持绿 = 变异**精确打到本修复面**。
- 恢复后绿：基线同文件 2 passed（74 passed 批内）。
- **判定：修复真实**。

### 1.4 R4-BL-3 §22.6 operation 收敛未落地（阻塞）

- 修复落点（结构核证，基线副本程序化取值）：
  - `ops/builtin/__init__.py:21-42` 三条注册：`claim` / `zcode_claim` / `query_balance`；
  - `claim.supported_products = ('buddy','lobsterai','qoder','qodercn','trae','loomy','zcode')` = **7 产品**（== 注册表 `checkin=True` 集合，逐项相等）；
  - `query_balance.supported_products` = **10/10**；
  - **别名**：`OPERATIONS['zcode_claim'].run is OPERATIONS['claim'].run` → **True**（同一函数对象）；
    `product_claim._CLAIM_DIRECT['zcode'] is zcode_claim.claim` → True（zcode 直连分支保留 `manual`/`runtime`）；
  - **单一事实源**：`product_claim._PRECHECK is registry.PRE_CHECK_PRODUCTS` → True；
    `api/admin_accounts.py` 引用同一对象 → True（`{'trae': True}`）。
- 撤修复（e4）：把 `runner.run_once` 的枚举从 `all_accounts(operation.supported_products)` 退回旧默认
  （写死 `upstream.zcode.store.list_accounts()`）。
- 用例级红证（e4）：`pytest tests/unit/test_ops_claim_multi.py tests/unit/test_ops_balance_multi.py`
  → **1 failed**：`test_default_enumeration_is_cross_product`
  `AssertionError: 跨产品枚举没生效：[]`（buddy/trae 账号一个都没被枚举到）。
- 恢复后绿：基线两文件 + 迁移面 74 passed（含 `test_zcode_claim_alias_is_the_claim_op_narrowed_to_zcode`）。
- **判定：修复真实**（结构面 + 枚举面双向）。注：另有一条**独立**发现——`all_accounts()` 缺省分支
  （`products=None`）在生产上无调用者（`run_once` 恒传 `operation.supported_products`），属半死分支，登记于 §4.2。

### 1.5 抽验小结

| # | 抽验项 | 撤修复红证 | 恢复后 | 判定 |
|---|---|---|---|---|
| 1 | R1-F1 alt TTL | 行为级复现成功落盘 + 2 failed | 绿 | ✅ 真 |
| 2 | R1-F5 跨进程写锁 | 5 failed（含真两进程交错） | 绿 | ✅ 真 |
| 3 | R2-B-2 复活链路 | 1 failed（重登后仍 disabled） | 绿 | ✅ 真 |
| 4 | R4-BL-3 ops 收敛 | 1 failed（跨产品枚举失效） | 绿 | ✅ 真 |

---

## 2. §22.8 十条硬清单落点表（逐条 file:line + 自选反例尝试）

| # | 条目 | 落点（file:line） | 判定 |
|---|---|---|---|
| 1 | 上游调用显式超时；禁阻塞事件循环 | `accounts/net.py:18`（`DEFAULT_TIMEOUT` 四段全给）+ `:21-32`（`make_client` 唯一入口）；`time.sleep` 全 M6 面 grep = `upstream/zcode/dataroot.py:205,211`（CLI 一次性进程，**非**服务路径）+ `accounts/store.py:322,397`（**写锁等待，可达异步服务路径**） | **部分**：反例尝试命中真实偏离（A-1，非阻塞判定） |
| 2 | 会话 TTL 与取消；无孤儿任务 | `accounts/login.py:145-156`（`_gate` 三条通道共用）、`:57` TTL=600s、`:218` start 先 sweep、`:206/413` `atexit`；反例尝试见下（会话滞留，有界） | ✓（含 1 条有界反例） |
| 3 | 并发有界：登录单飞 / 运营串行+抖动 | 单飞 `login.py:271-282`（**按会话**，非 spec 字面「按产品」→ A-2）；运营串行+0~50% 抖动 `ops/runner.py:39`（1.2s）、`:520-527`；模型转发并发 = 既有 `x`（`core/scheduler.py`，非 M6） | 部分 ✓（A-2 口径未登记） |
| 4 | 写盘唯一入口 + 原子写；跨进程 fail-closed 互斥 | `accounts/store.py:173-195`（mkstemp+fsync+replace）、`:238-431`（`_AccountsWriteLock`，fail-closed 无 `/tmp` 退路）、三条写路径持锁 `:539/:631/:679`；例外登记 = `upstream/zcode/store.py` 遗留导入 + `api/admin.py` 直调（§22.2 已登记） | ✓（抽验 1.2 真红） |
| 5 | 运行态内存权威 + 落盘快照；读不动 fail closed | 读：`store.py:484-501`（`RuntimeUnreadable`）→ 视图降 unknown（`api/admin_accounts.py:329`）；写：`ops/builtin/query_balance.py:110-133`（`write_runtime`，F6 后**已有生产方**）+ `:136-167`（`set_quota`） | ✓（F6 已闭环） |
| 6 | 失败隔离（凭据解析在 try 内） | `ops/builtin/product_claim.py:113-124`、`query_balance.py:78-86`、`api/admin_accounts.py:552-570`、`runner.py:344-347`（执行器兜底） | ✓ |
| 7 | 适配器换绑延迟排空 | `main.py:457-459`（`_retire_adapters`）、`:476-483`（先摘再关）、`:447-453`（宽限 = 请求总预算 300s） | ✓ |
| 8 | 日志脱敏（凭据只短哈希） | `accounts/net.py:35-40`（`cred_fingerprint`）、`store.py:555-556`（只打指纹）、`lobsterai/login.py:238,280`、`trae/login.py:327,384`（指纹）；grep 日志行无凭据值 | ✓ |
| 9 | 内存有界（会话表/在途表清理） | `login.py:281-282`（在飞 finally 出表）、`:287-303`（终态即出表）、`:315-321`（`_sweep`）；反向尝试见下 | ✓（有界） |
| 10 | 429 退避 `[500,1500,4000]ms`；业务码不重试 | `ops/runner.py:42`、`:336-358`（`_run_one`）、`:325-333`（`_retryable_of` 结构化优先）、`ops/base.py:19-34`（`OpResult.retryable`）；7 个 checkin 产品折叠点（`upstream/{buddy/hooks,lobsterai/claim,qoder/flow,trae/claim,loomy/credits,raccoon/credits}.py` + `zcode_claim.py:225-230`） | ✓（1 条口径不一致见 A-3） |

### 2.1 自选反例尝试（要求"尝试过"；两条均实测）

**尝试 ①（打穿）事件循环阻塞 — §22.8-1**

- 脚本 `/tmp/m6ea-e1-loopblock.py`（假另一进程持锁 pid=1；协程内调 `store.commit_login`，并发 10ms 打点任务量事件循环间隔）：
  ```
  WriteLockError: 账号写互斥被占用（…accounts.lock …）
  commit_login 等待耗时 = 1005 ms
  打点次数 = 10；最大打点间隔 = 1007 ms（正常 ~10ms）
  ```
- 机制：`store.py:292-298`（等锁循环）+ `:316-322`/`:385-397` 的 `time.sleep(_LOCK_POLL_S)`；生产链 =
  `POST /admin/api/accounts/login/{poll,callback,alt}`（`api/admin_accounts.py:404-462`）→ `login._advance::_commit`
  （`login.py:300-310`）→ `store.commit_login` → 等锁。**1.0s 内整个网关事件循环停摆**（所有并发请求被拖住）。
- 对照：R4 评审 §3.1 的结论「time.sleep 仅存在于 dataroot，不在异步服务路径」**不成立**（漏了 store.py 这两处）。
- 处置建议（不代改）：① 把落盘经 `asyncio.to_thread` 下放，或 ② 把该等待登记进 §22.8-1 的**例外表**（与 dataroot 并列）并说明上界 1.0s。

**尝试 ②（未打穿，有界）会话表滞留 — §22.8-9**

- 脚本 `/tmp/m6ea-e2-sweep.py`（ttl=0.01、无后续流量）：
  ```
  TTL 已过、零流量：_sessions = 2 （会话均已过期）
  再 start 一次后：_sessions = 1
  ```
- 结论：清理由流量驱动（`start` 先 sweep，`poll/callback` 终态出表），"无人轮询的过期会话"会滞留到
  下一次 `start`。上界 = TTL 窗口内新建的登录数（每条登录都要走 `start` → 顺带 sweep）→ **内存有界成立**，
  与 R1「未验证」条目一致，本次实测**未打穿**。

---

## 3. 契约面核证

### 3.1 `accounts/types.py` ↔ §22.3 冻结面（含 4 处裁决补入）

| §22.3 条目 | 实现（file:line） | 判定 |
|---|---|---|
| `LoginKind` 五字面量 | `types.py:18`（device_code/external_link/local_callback/qr/sms_code 逐字一致） | ✓ |
| `Capabilities` 五位默认 False | `types.py:27-47`（balance/checkin/onboarding/permanent_lock/refresh） | ✓ |
| `DeviceSpec`（fields/derive） | `types.py:50-63` | ✓ |
| `ProductMeta`（id,title,login,protocol,base_url,device,capabilities,models_source） | `types.py:66-84`；`login_alt` 带默认值放字段末尾 | ✓ |
| 裁决①`protocol` 补 `custom` | `types.py:75` + 注册表 qoder/qodercn/trae=`custom`（`registry.py:121,135,151`） | ✓ |
| 裁决②`ClaimOutcome` + `NotRefreshable` | `types.py:177-196`（`category: Category` **直接 import** `ops.base.Category`，`types.py:15`，无第二份四类字面量）+ `:198-203` | ✓ |
| 裁决③`meta` 通道（`account`/`dir` 必含） | `store.hook_meta`（`store.py:446-466`，锚字段最后写、白名单化），消费点 `product_claim.py:120`、`query_balance.py:81`、`admin_accounts.py:559,615`、`adapters/product_out.py:109` | ✓ |
| 裁决④`start(kind=)` + `_ALT_HOOKS`/`alt_call` | `login.py:124-142`（非法值当场 ValueError）、`:210-227`；`_alt_hook` `:171-186`（表外 KeyError）；`alt_call` `:361-395` | ✓ |
| 钩子签名面（10+1） | `tests/accounts/test_registry.py:24-40`（FROZEN_HOOKS 含 `claim_onboarding` 可选表 `:43-45`） | ✓（护栏逐产品断言） |
| `ClaimOutcome.retryable` 默认 False（加字段纪律） | `types.py:186-195` | ✓ |

### 3.2 `ops` 四类结果 / `retryable` 结构化语义

- 四类**唯一字面量**：`ops/base.py:12`；"只有 failed 需关注"的规则住在消费点（`base.py:13-16` 注释，原先的第二张表已删）。
- `OpResult.retryable: bool | None = None`（`base.py:26-34`）→ 判据 `runner._retryable_of`（`runner.py:325-333`）：
  **结构化声明优先、`None` 才回退前缀**（`_looks_retryable` `:314-322`）。
- `ClaimOutcome.retryable: bool = False`（`types.py:195`）→ 桥接两处：`product_claim.py:130-132`（非 failed 归 `None`）、
  `api/admin_accounts.py:566-570`（原样透传，Fix-ζ 补的 `retryable`）。**两处桥接 = 双账风险（A-5，低）**。
- 实测语义：`test_ops_claim_multi.py:139-177`（网络类重试 / 业务码不重试，**且用例自钉前提** `_looks_retryable(NETWORK_TEXT) is False`）；
  `test_v2_ops.py` 既有 zcode 前缀回退未破坏。

### 3.3 `store` 写回自检 + 锁 + 回滚

- 自检 `store.py:726-752`：凭据**逐键**读回 + `merged`（含 store 管理键）**逐键**读回；基准 = `merged` 而非调用方原值（P-B1 已修，`:734-737`）。
- 回滚 `:755-771`：新建 → 整目录删；既有 → 逐文件写回旧字节；回滚自身不再抛（原始异常优先）。
- 锁 `:238-431`：进程内 `_PROCESS_LOCK` + 线程局部深度（可重入）+ 跨进程 `O_EXCL` 锁文件；**fail-closed 双层**
  （锁目录不可用 → `WriteLockError` 拒写；被占用 → 等 1.0s 后拒写；无 `/tmp` 退路）；陈旧回收 = pid 判活 + 15min 超龄 + 2s 写入宽限 + 双条件（pid+token）释放。
- 临界区覆盖：`commit_login` `:539-557`（含末尾物化）、`import_account` `:631-652`（查重与落盘同临界区）、`delete_account` `:679-684`（rmtree + 停用资源同临界区）。
- **抽验 1.2 已实测**：删锁 → 5 failed（含真两进程交错：子进程 `WROTE` 返回码 0 = 丢更新可观测化）。

### 3.4 `registry` 单一事实源

- `PRE_CHECK_PRODUCTS`（`registry.py:56`）**对象级单一**：`product_claim._PRECHECK is registry.PRE_CHECK_PRODUCTS → True`；
  `admin_accounts._PRECHECK is registry.PRE_CHECK_PRODUCTS → True`（实测）。
- `_IMPLEMENTED` / `_REFUSED_HOOKS`：**每产品一份、无第二副本**（10 个 `upstream/*/product.py`），唯一消费者 = 护栏
  `tests/accounts/test_registry.py:52-101`；`_TESTS_TAKEOVER` 逃生门**全仓零使用**（仅机制在）。
- 能力位/设备规格：只住 `registry.PRODUCTS`（无第二张表；`test_matrix_capabilities_from_research_3_1` 钉住）。
  前端按钮数据驱动（`accounts.js:312-319` 读 `/capabilities` 响应，不硬编码产品名）。

### 3.5 附：§22.5-3 分派与复用判据（契约面抽查）

- `build_adapter` 首行判 `product`（`adapters/__init__.py:17-19`）；复用键 `_adapter_reuse_key`
  `main.py:400-415` = `(归一 base_url, protocol, product, account_ref, 凭据短哈希)` —— 与 §22.5-3
  「复用判据必须追加 `product + account_ref`」一致，且追加了凭据指纹（重登即重建）。
- 构造失败全异常降级：`main.py:362-372`（B-1 修复；未登记 product 的 `KeyError` 不再打死热重载）。

---

## 4. 死代码 / 双账检查

### 4.1 独立符号抽查（自实现 AST 扫描：`/tmp/m6ea-deadscan.py`，565 个 public 顶层符号）

自实现扫描给出的"无外部引用"名单经甄别后**绝大多数为同文件内使用 / 测试隔离缝 / 鸭子类型接口**（误报），
逐个人工抽查 ≥3 个 M6 新符号，**均有生产引用**：

| 符号 | 生产引用（file:line） |
|---|---|
| `accounts.store.hook_meta` | `ops/builtin/product_claim.py:120`、`query_balance.py:81`、`api/admin_accounts.py:559,615`、`adapters/product_out.py:109` |
| `ops.builtin.product_hooks.is_transport_failure` | `product_claim.py:124`、`query_balance.py:86` |
| `core.resources.ResourceManager.unservable_reason` | 装配侧写 `main.py:257`；读 `main.py:625`、`resources.py:295,347` |
| `accounts.types.ClaimOutcome.retryable` | 消费 `runner.py:331`；置位 7 产品折叠点（见 §2 #10） |
| `adapters.product_out.build_product_adapter` | `adapters/__init__.py:17` import、`main.py:354` 经 `build_adapter` 分派 |

### 4.2 双账 / 重复规则清点

| # | 项 | 判定 |
|---|---|---|
| A-5 | `ClaimOutcome → OpResult` **两处桥接**：`product_claim.py:130-132`（非 failed 归 `None`）vs `admin_accounts.py:566-570`（原样透传）。行为上无差（`retryable` 只在 failed 时被读），但"非 failed 归零"这条归一化规则只在一处 | **低·双账风险（建议收敛成一个 helper）** |
| A-3 | 重试性判定**两套口径**：7 产品走 `is_transport_failure(e)` 精确判定；`zcode_claim.py:225-230` 外层 `except Exception` **一律** `retryable=True`（连非网络异常也退避重试，与 §22.6「仅网络/5xx」不一致；M6-6 前该路径靠 `network:` 前缀，行为等价，属**遗留口径**而非新回归） | **低·口径不一致** |
| A-4 | `runner.all_accounts(products=None)`（`runner.py:381-403`）的**缺省分支**无生产调用者（`run_once` 恒传 `operation.supported_products`，`runner.py:435-440`）；仅测试在用 | **低·半死分支** |
| — | 四类字面量 / 能力位表 / precheck 表 / 业务码表（`zcode_claim.classify` 唯一）/ capabilities 表：**均只一份**（§3.4 实测） | ✓ |
| — | F7「onboarding 注册面分裂」现状：loomy 进 `_HOOKS`、raccoon 进 `_OPTIONAL_HOOKS`，但 `product_hooks.hook_of`（`product_hooks.py:23-30`）是**联合唯一取用点** → "无发现点"的原始问题已消解；`claim_onboarding` 仍**无入口端点**（前端 `accounts.js:84` `ONBOARDING_ENDPOINT_READY=false` + `:775-778` 自登记） | 已登记（非静默） |
| — | 前端 `FAMILIES`（`accounts.js:57-68`）是**展示分组**、非规则副本：带"未出现在本表的在册产品自动落单卡"的兜底 + 依据注释；`POLLABLE`（`:53`）是 `LoginKind` 的 UI 侧派生（R-5 修复点）。规则本体仍在 registry | ✓（可接受） |

---

## 5. 测试质量（≥5 例判定 + 变异）

### 5.1 抽读判定（真断言 vs 循环自证）

| # | 用例 | 判定 |
|---|---|---|
| 1 | `test_login_engine.py::test_alt_call_refuses_expired_session…` | **真断言**：零钩子调用（`calls == ["1"]`）+ 零落盘（文件不存在）+ 正向对照（TTL 内照常成功） |
| 2 | `test_store.py::test_interleaved_second_process_write_is_refused…` | **真断言**：真起第二进程（`subprocess.run`），判据 = 退出码非 0 + 可读原因；无锁时"子进程 WROTE"可观测 |
| 3 | `test_m6_revive.py::test_relogin_revives_without_extra_actions` | **真断言（端到端）**：真 uvicorn + 假上游；断言 `st.status` 回 active、`C==0`、模型回 `/v1/models`、新凭据真被使用、配置 Key 不外发 |
| 4 | `test_ops_claim_multi.py::test_default_enumeration_is_cross_product` | **真断言**：seed 三产品账号、断言实际调用账号集合；`workbuddy` 不入枚举（无签到能力） |
| 5 | `test_ops_balance_multi.py::test_quota_hook_result_lands_in_runtime_cache_and_pools` | **真断言**：三态逐档；断言的是**另一路径读回**（`read_runtime`）与共享池对象（`pool.remaining`），非函数自返回值 |
| 6 | `test_qoder_out.py::test_qoder_nonstream_end_to_end` | **真断言**：假上游侧比对路径/query/头/信封 key/`session_type`/事件 JSONL；`CONFIG_KEY not in headers` 反向断言 |
| 7 | `test_cline.py::test_hooks_still_unimplemented_are_declared_and_raise` | **真断言**（见变异 6：伪造实现即红） |

未发现"永真断言 / 断言目标与题面无关"；各用例断言对象落在**外部可观测状态**（文件、池、进程退出码、上游收到的请求）。

### 5.2 变异实验（复制品内，共 7 组；4 组为任务指定抽验，3 组自选）

| # | 变异（撤/伪造） | 目标 | 结果 |
|---|---|---|---|
| 1 | 撤 `alt_call` 的 `_gate`（`login.py:389-391`） | `test_login_engine.py -k alt_call` | **2 failed**（+ 行为级攻击：过期会话落盘 `{"token":"SMS-OK"}`） |
| 2 | 锁单例换 no-op（`store.py:431`） | `tests/accounts/test_store.py` | **5 failed**（含真两进程交错） |
| 3 | 撤 `_nudge_reload`（`materialize.py:99`） | `tests/integration/test_m6_revive.py` | **1 failed**（重登后仍 disabled） |
| 4 | `run_once` 枚举退回 zcode-only（`runner.py:435-440`） | `test_ops_claim_multi.py` | **1 failed**（跨产品枚举没生效：`[]`） |
| 5 | 摘掉额度池写入（`query_balance.py:147-149` 后短路） | `test_ops_balance_multi.py` | **2 failed**（`assert 5 == 0`） |
| 6 | `qodercn.login_callback` 编造 success（R1-F4 原攻击） | `tests/accounts/test_registry.py` | **1 failed**（"登记为显式拒绝，却返回 state='success'"）——F4 盲区**确已关闭** |
| 7 | cline：伪造 `_IMPLEMENTED` 声明 + `login_callback` 编造 success | `tests/accounts`+`test_admin_accounts.py` | 护栏**绿**、产品单测 **1 failed**（`test_cline.py::test_hooks_still_unimplemented_are_declared_and_raise`）→ `_IMPLEMENTED` 是"声明即信任"，由产品单测兜底（A-6，设计如此，登记） |

### 5.3 全量复跑（独立核证台账"1422/0"）

- 命令：`cd /tmp/m6ea-repo && python -m pytest -q -p no:cacheprovider --basetemp=/tmp/m6ea-full-bt`（主树零写入）
- **`1422 tests collected`**（`--collect-only`，与台账/README 口径一致）。
- 首轮复制品全量：`2 failed, 1416 passed, 4 errors in 339.49s` —— **6 条全部定位为"复制品不完整"的伪红**，逐条复证：
  1. `test_config.py::TestLoadExample::test_example_config_loads`（1 failed）+ `test_v2_readme_claims.py` 四例（4 errors）：
     我的复制品起初未含 `config.example.yaml` / `README*.md`（评审面只需源码与测试）→ 补齐后**同一批重跑 52 passed**（`test_config` + `test_v2_readme_claims` + `test_v2_servable`，仅剩下条）。
  2. `test_v2_servable.py::test_ops_lock_dir_ignores_cwd`（1 failed）：复制品固有伪红（`cwd=复制品` 导入复制品、`cwd=/tmp` 导入可编辑安装的主树 → 两个不同路径）。
     独立复证（只读、非 pytest）：主树 cwd 与 `/tmp` cwd 各跑 `from model_gateway.ops.runner import ops_lock_dir` →
     **均输出 `/Users/w/Desktop/Model-Gateway/data/ops-locks`**（一致）→ 该用例的前提在主树成立，复制品才不成立。
- **净结果**：1422 条全部有交代，未发现真红 → 台账"1422 passed / 0 failed"**成立**（与 R4 §3.5 的同类伪红判法一致）。

---

## 6. 未验证（本轮未覆盖）

1. 真实凭据 / 真实上游行为（§22.11 的 U1–U14 全部）——本轮一律假上游/假凭据，未触网。
2. 前端面（accounts.js DOM/双主题/交互）不在本角色职责内（eng-b / M6-IX 面）。
3. `import_account` 遇 `OSError`（磁盘满等）时向 CLI 冒栈的兜底行为未构造（仅读码：`store.py:655` 只捕 `WriteLockError`）。
4. §22.8-2 的"极端面"（长期只 alt 不 start 的会话滞留）只做了短程实测，未做长跑；§22.8-9 同理。
5. 会话 ↔ 产品配对（F10）在 `poll/callback` 的引擎层校验已加（`login.py:292-293`），本轮未再变异（R1 已变异）。
6. A-1 的"典型毫秒级"是按持锁者写盘耗时推断（写路径为同步 fsync，实测本机单文件写入为毫秒级），未做**并发压测**量化典型等待分布。

