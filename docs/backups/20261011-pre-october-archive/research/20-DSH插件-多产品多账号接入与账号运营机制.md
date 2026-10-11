# 20 · DSH 插件「多产品多账号接入 + 账号运营」复核与增量调研

> **本文性质**：**复核 + 增量**，不是重写。复核基准 = `02-DSH-多产品多账号资源池机制.md` 与 `10-设备身份隔离与批量运营机制.md`（含 `drafts-v2/v2-02-…`），覆盖对象 = 2026-09-29 同步的 gitee 上游 `master f531c2984`。
> 调研对象：`/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts`（简称 DSH，**全程只读**）
> 事实基准：`src/` 源码（`lib/` 不存在于本机）。**所有行号均在本轮重新 Read 核对，未沿用旧文档行号。**
> 写作约定：**【代码】**= 直接读到的代码事实（附 `file:line`）；**【推断】**= 未经代码直接证实；**【未验证】**= 卡住没证实
> 用户点名维度：① 多产品多账号接入与管理 ② 自动化签到/领取运营 ③ 产品内部模型读出并对外输出（③ 不在本文，见 `21`）
> 网关侧对照基准：`model_gateway/config/schemas.py`、`model_gateway/core/resources.py`、`model_gateway/core/errors.py`

---

## 0. 结论先行

### 0.1 一句话总结（相对既有调研的变化幅度）

**产品数从 6 涨到 11 个实例、账号池从「无租约 + 无条件批量续期」升级为「无租约 + lead-time 定向续期 + 独立状态文档」，运营能力从「5 产品 4 项」扩到「8 产品 6 项（含一次性新手任务/登录奖励与永久积分锁定）」。**
**复核后有 3 条旧结论失效（含 1 条「建议直接抄」的操作建议）、2 条表述需更正、其余核心判定仍成立**：
- ❌ 02 §5.1「**额度不参与选号**」→ **已被推翻**（buddy/workbuddy/loomy 三家的首选选号路径就是余额分档）
- ❌ 02 §3.3 D4「refreshAll 无条件刷新」→ 已修正为 lead-time
- ❌ 02 §5.4 / 10 §1.4「TRAE 9074 设备轮换代次，直接抄」→ **机制已废弃**（改为 uid 确定性派生）
- ✅ 02 §0.3 / §4.5「**账号池无并发租约**」→ **仍成立且未被修**（新增的余额分档路径同样无占用标记）
- ✅ 10 §0.2「无设备全局唯一性校验」→ 仍成立（新增 2 个不受管设备标识，但出现了「确定性派生」这一更省事的新选项）
- ✅ 运营操作仍与「响应体业务码」判幂等、仍以「单账号失败不中断」为编排铁律（10 §2.3 成立，**但 10 表里的「间隔」不是 DSH 的现状**，见 §4.3）

### 0.2 复核总表（对 02 / 10 关键结论逐条判定）

| # | 既有结论（出处） | 本轮判定 | 当前证据 |
|---|---|---|---|
| R1 | 产品差异收敛为「平行类型而非通用类型」，CodeArts 无产品对象（02 §0.2①/§1.1） | ✅ **成立且加剧**：从 4 个平行接口 → **7 个**（新增 Cline/Loomy/Raccoon/Zcode 各自独立接口）；CodeArts 仍无产品对象 | `product.ts:74`、`qoder-product.ts:172`、`trae-product.ts:51`、`lobsterai-product.ts:136`、`cline-product.ts:62`、`loomy-product.ts:51`、`zcode-product.ts:56` |
| R2 | 账号池选号 = 三步过滤 + 取第一个，顺序即优先级（02 §0.2②） | ✅ **成立**（行号漂移 +32~92）：算法一字未改，注释依旧 | `account-pool.ts:658-718` |
| R3 | 凭据与账号索引分两处存，靠 `credentialRef` 指针关联（02 §0.2③） | ✅ **成立**，但**索引落盘位置已换后端**（settings namespace → 插件自有状态文档，双后端探测） | `jet-hub-store.ts`（新增）、`account-pool.ts:47-89` |
| R4 | 账号池**无并发租约**，并发必然重复选同一账号（02 §0.3、§4.5） | ✅ **成立，未修**：全文再 grep `lease\|reserve\|acquire\|in_flight\|mutex\|cursor\|occup` **仍零命中**；私有状态仍只有 cache/modelCache/permanentLockCache/loaded | `account-pool.ts:59-81`（复核见本文 §2.5） |
| R5 | 首次选号 `modelId` 传空串 → 不做模型级限流过滤（02 §4.2 细节 1） | ✅ **成立**：`account-pool.ts:668` 仍有 `if (modelId.length === 0) return true`；**但漂移**：`index.ts` 的 buddy/workbuddy/qoder/qodercn/trae/cline/raccoon/zcode 已改为传真实 modelId（见 §2.5） | `account-pool.ts:666-672` vs `index.ts:381,425,528,585,634,672,877,996` |
| R6 | 续期是「全局 30 分钟批量、无条件刷新所有 refreshable 账号」（02 §3.3 特征 1） | ❌ **已被修正**：`refreshAll` 现在按 **lead-time（距过期 ≤1h 才刷）** 过滤，不刷的只做本地对账 | `expiry-sync.ts:89-92`（`shouldRefreshNow`）、`:167-220`（`refreshAccountWithReconcile`） |
| R7 | 定时器「启动时无 refreshable 账号则永不创建」+「首轮要等满 30 分钟」（02 §3.3 D5） | ✅ 缺陷①**仍在**（`if (!hasRefreshable) return`，`index.ts:1158-1159`）；❌ 缺陷②**已修**（启动即跑一轮，`index.ts:1160`）；另新增 `.catch`（原为裸 `.then`，`index.ts:1179-1187`） | `index.ts:1157-1187` |
| R8 | 续期定时器判据「不看 enabled 只看 refreshable」（02 §3.3 特征 2，10 §2.2 教训 3） | ✅ **成立且已升格为注释里的契约** | `index.ts:1145-1148` |
| R9 | 运营操作抽象：四类结果分类 + 幂等看响应体 code（10 §2.3） | ✅ **成立**，并已扩展为**六类能力**（新增 `onboardingTasks` 一次性领取；`rateLimit` 支持矩阵反转为「默认开启」） | `credits-capabilities.js:62-145`、`:164-168`、`:321-323` |
| R10 | 设备指纹「持久化 + 续期不动 + 每账号互异」（10 §0.1） | ✅ **成立**：TRAE 的 `machine_id`/`device_id` 语义未变；Raccoon/Zcode/Loomy/Cline 各自新增设备标识字段（见 §2.7） | 各 `*-product.ts` + 各 `*-auth.ts` |
| R11 | 「无账号去重」缺口（02 §2.5，`trae.ts:102` 注释与代码不符） | ✅ **缺口仍在**：`addAccount` 仍是纯 append，全文未见按 uid 去重 | `account-pool.ts:407-410` |
| R12 | `sweepExpiredRateLimits` 无调用方（02 §4.2 D14 死代码） | ✅ **仍是死代码**（本轮再次 grep 无调用点） | `account-pool.ts:748-763` |
| **R13** | **02 §5.1「额度是独立查询接口，不参与选号」** | ❌ **被推翻**（3/11 provider）：首选选号路径 = 余额分档 → 池 → 单凭据 | `index.ts:370,418,782`；`*-balance-rank.ts` |
| **R14** | **02 §5.4 / 10 §1.4「TRAE 9074 设备轮换代次（只增不减、派生不改本体）」，并建议「直接抄」** | ❌ **机制已废弃**：9074 现在直接 `failed` + 冷却 300s，`onRotate` 零调用点（死参数）；改用 `uid` 确定性派生设备身份 | `trae-credits.ts:265-276,231`；`trae.ts:286` |
| **R15** | **10 §2.3 批量执行器「串行 + **间隔** + 失败隔离」** | 🔁 **部分更正**：串行与失败隔离成立；**「间隔」不存在**——`collectClaimResults` 无账号间 sleep | `jet-hub-rpc.ts:461-533` |
| **R16** | **10 §2.3 教训 3「停用账号不能参与批量操作」** | 🔁 **更正**：`collectCreditsStatus` **明确包含已停用账号**（「用户要看到的是这个账号今天领了没」）；只有**选号**才排除停用 | `jet-hub-rpc.ts:407-409` |
| **R17** | **10 §2.4「运营操作与核心调度解耦」** | 🔥 **DSH 本轮自己打破**：余额分档把运营侧数据接进了请求期选号入口。我们应保留解耦定案、用「后台任务刷新 + 选路只读」达成同等效果 | `index.ts:370,418,782`，详见 §5.4 |

### 0.3 五条「新机制」（02/10 完全没有的）

1. **`expiry-sync.ts`（新）**：把「续期」拆成 **lead-time 判据 + 池值对账** 两件事。→ 修掉了「凭据续好了、UI 却显示已过期」这类**数据源分叉**（issue !IKIRTT）。（§2.6）
2. **`permanent-lock-store.ts`（新）**：把「锁定永久积分」开关表**从 state.json 拆到独立文档**（`$DSH_HOME/jet-hub/permanent-locks.json`），原因写在文件头：state.json 是 **dsh home 级多 profile 共享**，而写入是**整体替换**语义，另一条工作区的**旧版本代码**全量重写时会静默抹掉它 → 静默解锁 → **永久积分被烧掉且不可撤回**。（§3.3）
3. **`jet-hub-store.ts` + `settings-compat.ts`（新）**：存储后端**按宿主版本能力探测**（≥0.1.7 settings 不再允许插件注册 namespace → 改用插件自有状态文档），两者都不可用时退化为内存态且**只 warn 不抛错**。（§2.2）
4. **`buddy-balance-rank.ts` / `loomy-balance-rank.ts` + 两个 selector（新）**：**余额分档选号** —— 优先消耗「快作废」的额度、永久额度排最后；这是对 02 §5.1「额度不参与调度」的直接推翻。（§2.4）
5. **永久积分锁定（`permanentLock` 运营开关，新）**：锁定时「只剩永久积分的账号等同不可用」，且**绝不落到单凭据兜底**（否则锁定形同虚设）。（§3.3）

### 0.4 最不能照抄的四点（相对 02 有增删）

| # | 缺陷 | 状态 | 位置 |
|---|---|---|---|
| N1 | **无并发租约**（并发全挤 `candidates[0]`；新增的余额分档路径同样无占用标记） | 未修，与 02 §4.5 判断一致 | `account-pool.ts:658-718`；`loomy-balance-selector.ts:188-221` |
| N2 | **`getAvailableAccount` 的文档注释与实现矛盾**：注释仍写「本池默认按『重置时间最早到期』排序」，实现里那套排序早已删除（下文 674-683 行注释自己说明了为什么删） | 新增发现（注释漂移） | `account-pool.ts:650-653` vs `:674-683` |
| N3 | **永久积分锁定的隐藏成本**：三家 provider 的「什么算临时积分」判据不同，而 15 天窗口在中国版会让整池**立刻不可用**（逃生门是环境变量） | 新增发现 | `buddy-balance-rank.ts:64-99` |
| N4 | **余额分档选号把网络查询塞进每次请求的选号入口**（靠 60s TTL 掩盖）；而我们的 `pick_and_acquire` 是**同步段**，照抄会直接破坏该不变式 | 新增发现 | `index.ts:370,418,782` vs `resources.py:120-144` |

---

## 1. 多产品接入（product.ts 与各 `*-product.ts` 全表）

### 1.1 产品全表：**11 个 provider 实例 / 7 个平行类型**（相对 02 的 6/4 大幅扩张）

**以代码为准**（`index.ts` 的注册段与各 product 文件）：**【代码】**

| # | provider id | 产品类型（接口） | 类型定义 | 实例常量 | 与 02 相比 |
|---|---|---|---|---|---|
| 1 | `codearts` | **无产品类型**（常量散落） | — | — | 不变（旧结论仍成立） |
| 2 | `buddy` | `BuddyProduct` | `product.ts:74` | `CODEBUDDY` `product.ts:268` | 不变 |
| 3 | `workbuddy` | `BuddyProduct`（共用） | 同上 | `WORKBUDDY` `product.ts:381` | 不变 |
| 4 | `lobsterai` | `LobsteraiProduct` | `lobsterai-product.ts:136` | `LOBSTERAI` `lobsterai-product.ts:211` | 不变 |
| 5 | `qoder` | `QoderProduct` | `qoder-product.ts:172` | `QODER` `qoder-product.ts:439` | 不变 |
| 6 | **`qodercn`** | `QoderProduct`（共用，`id` 联合） | `qoder-product.ts:181` (`id: 'qoder'\|'qodercn'`) | `QODER_CN` `qoder-product.ts:584` | 🆕 **新增**（02 §1.1 说「加值会牵动一串调用点」，本轮证明**加值真的发生了**） |
| 7 | `trae` | `TraeProduct` | `trae-product.ts:51` | `TRAE` `trae-product.ts:263` | 不变 |
| 8 | **`cline`** | `ClineProduct` | `cline-product.ts:62` | `CLINE` `cline-product.ts:262` | 🆕 **新增** |
| 9 | **`loomy`** | `LoomyProduct` | `loomy-product.ts:51` | `LOOMY` `loomy-product.ts:118` | 🆕 **新增** |
| 10 | **`raccoon`** | `RaccoonProduct` | `raccoon-product.ts:193`（`fallbackModels` 等） | `RACCOON` `raccoon-product.ts:288` | 🆕 **新增** |
| 11 | **`zcode`** | `ZcodeProduct` | `zcode-product.ts:56` | `ZCODE` `zcode-product.ts:196` | 🆕 **新增** |

**注册点三处必须同步**（漏一处的后果见 §1.3）：`index.ts:208-212` 的 `registerProviderSettings(...)` 11 个 namespace、`index.ts:1109-1127` 的 `refreshTargets` 11 行、`plugin-src/client/jet-hub.js:189-221` 的 `PROVIDERS` 11 项（含 `label`/`icon`/`logoClass`）。
另有一处**易漏的第四点**：`jet-hub-rpc.ts` 的 `account.create` 分派必须加分支（否则 `bad-request: unknown provider`，`jet-hub-rpc.ts:1211-1212`）。

### 1.2 每产品注册字段对照组（模型来源 / 限流 / 设备标识 / 入口）

**模型来源**（远端端点 + 兜底表条目数）：**【代码】**

| provider | 远端模型来源 | 兜底表 | 条数 |
|---|---|---|---|
| `codearts` | **两个**端点合并去重：`opengw.developer.huaweicloud.com/api/v1/gateway/config` + `snap-access.cn-north-4.myhuaweicloud.com/v1/model/builtin`（`models.ts:9,17`） | 无静态表，走磁盘缓存 | — |
| `buddy` / `workbuddy` | `GET /v3/config`（`buddy.ts:39`），另有 scoped 端点优先（`buddy-oauth.ts:348-374`） | `CODEBUDDY_FALLBACK_MODELS` `product.ts:180` / `WORKBUDDY_FALLBACK_MODELS` `product.ts:295` | 16 / 23 |
| `lobsterai` | `GET /api/models/available`（`lobsterai.ts:36`） | `LOBSTERAI_FALLBACK_MODELS` `lobsterai-product.ts:183` | 19 |
| `qoder` | WASM 签名端点（`qoder-product.ts` + `qoder-wasm.ts`） | `QODER_FALLBACK_MODELS` `qoder-product.ts:362` | 17 |
| `qodercn` | 同国际版形态（`qoder-product.ts` 的 CN 常量段） | `QODER_CN_FALLBACK_MODELS` `qoder-product.ts:480` | 6 |
| `trae` | `POST/GET /api/ide/v1/get_detail_param`（`trae.ts:46`）+ batch 变体（`:53`） | `TRAE_FALLBACK_MODELS` `trae-product.ts:169` | 32 |
| `cline` | **两个**端点：`GET /api/v1/models`（全量）+ `GET /api/v1/ai/cline/recommended-models`（**免费集合唯一权威**，`cline-models.ts:8`） | `CLINE_FALLBACK_MODELS` `cline-product.ts:146` | 5 |
| `loomy` | `GET /api/v1/models`（取 `type==='chat'`，`loomy-product.ts:16,75`） | `LOOMY_FALLBACK_MODELS` `loomy-product.ts:104` | 8 |
| `raccoon` | `GET /api/web/llm/v2/model_catalog`（取 `visible:true`，`raccoon-product.ts:19,199`） | `RACCOON_FALLBACK_MODELS` `raccoon-product.ts:218` | 6 |
| `zcode` | `GET /api/v1/client/configs` 的 `offPeak.allowed_models`（`zcode-product.ts:14`） | `ZCODE_FALLBACK_MODELS` `zcode-product.ts:139` | 2（刻意只留实测可用的 GLM-5.3 / GLM-5.3-Flash） |

**限流**：**产品配置对象里仍无任何限流字段**（02 §1.4 结论不变）。限流落在两处：① 账号池 `modelRateLimits`（`account-pool.ts:670-671`）；② 各适配器的 `*_MAX_ROTATE` 常量。**但新增了一层「该 provider 是否有限流」的能力矩阵**：`RATE_LIMIT_CAPABILITIES`（`credits-capabilities.js:164-168`），目前**只有 `loomy` 登记为 `rateLimit:false`**，且该矩阵**默认开启**（与积分能力的「默认关闭」相反），理由写在 `:156-162`：限流按钮是既有 UI，默认关闭会让老用户凭空失去功能。

**设备标识字段**（用户点名维度，逐产品）：**【代码】**

| provider | 设备标识字段 | 位置 | 说明 |
|---|---|---|---|
| `trae` | `machine_id`（32hex）+ `device_id`（15 位数字派生） | `trae.ts:141,148` | 语义未变；`device_id` 有派生函数 `deriveDeviceId15(userId)`（`trae.ts:286`） |
| `qoder` / `qodercn` | `machine_id` | `qoder.ts:153` | 续期载荷必带 |
| `lobsterai` | `uuid`（+ `first_keyfrom`/`latest_keyfrom`） | `lobsterai.ts:109` | 「服务端识别同一安装的依据」 |
| **`zcode`** | `device_mid` | `zcode.ts:199` | 🆕 **由插件自己生成**（`zcode.ts:358` 读、`:297` 兼容旧格式）；**必须持久化**，随请求头 `X-Device-Mid` 下发 |
| **`raccoon`** | `device_id?`（可选） | `raccoon.ts:105` | 🆕 另有独立的桌面设备身份模块（`desktopDeviceIdentity` 语义，见 `raccoon-product.ts:110-118` 的 `clientPlatform`） |
| `codearts` / `buddy` / `workbuddy` / `cline` / `loomy` | **无** | — | 与 10 §1.2 判定一致（cline/loomy 为新增，仍无设备指纹字段） |

> **对 10 §1.4「设备注册表」设计的增量输入**：新增 2 个有设备标识的产品（zcode 的 `device_mid`、raccoon 的 `device_id`），且两者**形态不同**——zcode 的 `device_mid` 是插件**自造**（可自由分配、天然支持「每账号一套」），raccoon 的可选项更像「官方客户端已有的设备号」。
> 但 DSH **仍无设备注册表**：zcode 的 `device_mid` 存在凭据里，**没有跨账号唯一性校验**，与 10 §0.2 的判定一致（`10` 的方向未被推翻，只是又多了一个产品级实现）。

**入口**（Jet Hub 面板 `/account.create` 的登录形态）：**【代码】**

| provider | 登录形态 | 分支位置 |
|---|---|---|
| `buddy`/`workbuddy` | external-link 轮询 | `jet-hub-rpc.ts:835-877`（`productById` 分支） |
| `codearts` | 本地回调 + 两步式 | `:878-915` |
| `lobsterai` | 本地回调 + 两步式 | `:916-942` |
| `qoder`/`qodercn` | 设备码轮询 + 两步式（`isQoderFamily`） | `:943-991` |
| `trae` | 本地回调（固定端口）+ 两步式 | `:992-1021` |
| `cline` | **WorkOS 设备码轮询**（判据是响应体 `error: authorization_pending`，非 HTTP 404） | `:1022-1057` |
| `loomy` | **微信扫码**（本地弹窗页承载二维码 + 轮询 + 首次绑手机号） | `:1058-1112` |
| `raccoon` | **本地页承载 微信扫码 / 短信双路径** | `:1113-1167` |
| `zcode` | **官方 OAuth 设备授权流**（`/oauth/cli/init` → 浏览器 → `/oauth/cli/poll/{flow_id}`） | `:1168-1210` |

**九种登录形态全部收敛到同一条两步式契约**（先返回 `loginUrl`、后台 `await result`、失败删占位条目）：**02 §2.1 的「统一形状约定」在本轮被 4 个新产品**（cline/loomy/raccoon/zcode）**继续遵守**，且新增了「本地页承载」这一形态（loomy/raccoon：`loginUrl` 指向 `127.0.0.1` 的一个插件自建页面）。

### 1.3 「新增一个产品」的完整步骤（以 `docs/adding-a-new-provider.md` 为准 + 本轮增补）

文档 `docs/adding-a-new-provider.md` 给出两条路径（A 同源加点 / B 全新脉系），**本轮实测的增补点**：

**必须动的文件（9 处，比文档的 8 步多一处）**：

1. `src/xxx-product.ts` — 新 `XxxProduct` 接口 + 实例常量 + `ALL_XXX_PRODUCTS`（**文档建议可复用现有接口，但本轮 4 个新产品全部选择了「新建平行接口」**，理由各写在各 product 文件头：`raccoon-product.ts:1-17`、`zcode-product.ts:1-13`、`cline-product.ts` 头、`loomy-product.ts` 头）
2. `src/xxx.ts` — 协议常量 + 凭据结构 + 纯函数（**硬约束：非 codearts 的凭据必须含 `access_token`**，否则 `findAccountIdByCredential` 匹配恒失败，`account-pool.ts:510-518`）
3. `src/xxx-auth.ts` — `XxxAuth extends Service`（必须实现 `refreshAll`/`refreshAccountCredential`/`startLogin`）
4. `src/xxx-adapter.ts` — `LlmAdapter` 子类 + `registerXxxLlm()`
5. `src/xxx-oauth.ts`（或 `-login.ts` / `-wechat-login.ts` / `-qr.ts`）— 登录流程
6. `src/xxx-credits.ts`（可选）
7. `src/index.ts` — **四处**：`registerProviderSettings(...)` 加 namespace；`new XxxAuth(ctx)`；`registerXxxLlm(...)`；`refreshTargets` 加一行；另 `modelAdapters` 表（`:1209-1223`）与 `registerJetHubRpc` 签名（`:1225`）
8. `src/jet-hub-rpc.ts` — `account.create` 分支 + `account.refresh` switch + `credits.*` 各端点分支
9. `plugin-src/client/jet-hub.js` 的 `PROVIDERS` + `credits-capabilities.js` 的能力矩阵

**本轮新增的第 10 处**（文档 v1.0 未覆盖）：**`src/expiry-sync.ts` 的接入**——若该 provider 有真实过期时间，续期路径必须走 `refreshAccountWithReconcile`（否则 UI 显示「已过期」而实际能用，见 §2.6）。

**文档漂移提示（重要）**：`docs/adding-a-new-provider.md` 仍写「本插件已集成了四个 LLM Provider」，而实际是 **11 个**；其 §A1 示例里的 `ALL_PRODUCTS: readonly BuddyProduct[] = [CODEBUDDY, WORKBUDDY, BUDDY_EU]` 现为 `[CODEBUDDY, WORKBUDDY]`（`product.ts:411`）。**该文档是 v1.0 且未随产品扩张更新** —— 可作为「文档滞后于代码」的又一例证（与 02 §5.3 发现的 `credits-capabilities.js` 顶部表格漂移同类）。

---

## 2. 同产品多账号（实体 · 存储 · 生命周期 · 选号 · 续期 · 隔离 · 通道）

### 2.1 账号实体：**字段零增长**（10 个，与 02 §7.1 完全一致）

`ProviderAccountEntry` 仍是 10 个字段：`id` / `provider` / `nickname` / `enabled` / `credentialRef` / `createdAt` / `expiresAt?` / `refreshable` / `modelRateLimits?` / `traeCheckinDeviceGeneration?`（`types.ts` 的 interface，`awk` 全文读取）。
**02 §5.4 的「字段设计开始膨胀」判断在本轮得到反向验证**：新增 5 个 provider 后**一个字段都没加** —— 各 provider 的专属状态全部落在**凭据本体**（如 zcode 的 `device_mid`、raccoon 的 `device_id`）或**独立文档**里。这比「往通用 entry 上加字段」干净，可作为我们 `Account.extra` 设计的一个对照选项。

**但这也带来一处新的耦合**：README/注释要求「非 codearts 的凭据必须含 `access_token`」，因为 `findAccountIdByCredential` 对非 codearts 一律取 `access_token` 做身份比对（`account-pool.ts:510-518`）。**凭据字段名成了账号池的隐式契约**（`docs/adding-a-new-provider.md` §B2 已把它写成硬规则）。

### 2.2 存储：**从「单后端」变成「三后端按能力探测」**（02 §3.1 的存储层已过时）

```
       createJetHubStore(ctx)                       ← jet-hub-store.ts（🆕）
       ├─ settings.register 可用（DSH ≤0.1.6）→ SettingsStore  落 $DSH_HOME/settings.yaml 的 jet-hub: 段
       ├─ 否则（DSH ≥0.1.7-rc.1）        → FileStore      落 $DSH_HOME/jet-hub/state.json（原子写 tmp+rename）
       └─ 两者都不可用                    → MemoryStore    **仅内存 + 显式 warn**（不抛错）
```
**【代码】**`jet-hub-store.ts:1-34`（模块头）、`:82`（`JetHubStoreKind = 'settings'|'file'|'memory'`）、`:100-104`（老契约 schema 仍是 schemastery，02 §3.1 那条崩溃教训仍被保留）。

**为什么换后端（真实缺陷，Gitee issue IKI7WT）**：DSH 0.1.7-rc.1 起 `ctx.settings` 换成 **SettingsForms**（**没有 `register`**），命名空间只能是 profile 条目 id 且只投影 Config 里标了 `.volatile()` 的字段 → 早期写法恒走 `typeof settings.register !== 'function'` 分支 → **账号列表与模型黑名单退化为纯内存**（`jet-hub-store.ts:10-17`）。
**而 DSH 又刻意不把状态塞进插件 Config**（`:26-33`）：账号索引与限流时间戳是**运行时状态**，写 Config 会改写 `cordis.patch.yml` 并触发 Loader 协调 —— 「把易变数据混进用户手写的配置层，代价与风险都不划算」。

**三份状态文档的归属（本轮新增一张表，02/10 没有）**：

| 文档 | 内容 | 权威性 | 位置 |
|---|---|---|---|
| `settings.yaml` 的 `jet-hub:` 段 **或** `state.json` | 账号列表 + 模型黑名单 | 权威 | `jet-hub-store.ts:19-31` |
| `state.json` 的 `loomyPermanentLocked` | 锁定开关（**旧字段，降级为镜像**） | **非权威**，只写不依赖 | `jet-hub-store.ts:61-78` |
| `permanent-locks.json` | 锁定开关（表） | **权威** | `permanent-lock-store.ts:43,80` |
| `$DSH_HOME/jet-hub/`（备份另有） | 备份导出/导入 | — | `backup.ts`、`jet-hub-rpc.ts:2448-2490` |

**02 §3.1 的三条坑仍在，且行号已漂移**：
- **整体替换语义**：`store.save(...)` 必须同时携带 `accounts` 与 `disabledModels`（否则抹掉黑名单）—— `account-pool.ts:136-154` 的 `writeAccounts` 注释 + `:139-141`。✅ 结论不变。
- **进程内权威副本**：`cache` / `modelCache` / `permanentLockCache` 三个副本 + `loaded` 标志（`account-pool.ts:59-81`），理由与 02 所记一字未改（`:50-58`）。✅ 结论不变。
- **schema 必须是 schemastery**：老契约路径仍保留（`jet-hub-store.ts:99-104`），02 记的 `TypeError: registration.schema.toJSON is not a function` 崩溃未被重新触发。✅ 结论不变。

### 2.3 账号生命周期（**新增一处「昵称修复」启动钩子**）

**登录链条与 02 §2.5 一致**（行号漂移 `jet-hub-rpc.ts:824-875`）：`id = {provider}-{shortId()}`（`:827`）+ `ref = {PROVIDER}_ACCOUNT_{SHORTID}`（`:829`，**两次独立 shortId**，02 的警告仍成立）→ 先 `addAccount` 占位（`:850-858`）→ 后台 `await` → `credentials.set` + `updateAccount` 回填 → 失败 `removeAccount` 清幽灵账号（`:875`）。

**本轮增量 3 条**：

1. **昵称可区分性成为硬需求（3 次用户报障）**：服务端下发的名字常是**按 uid 自动生成的默认名**，多账号一屏认不出。各自加了专用函数并在**启动时**批量修复老账号：
   - TRAE：`traeDisplayNickname`（手机号优先）+ 启动时补 `GetUserInfo`（`trae-auth.ts:488-509` 的方法头，明确「正是用户报障 2026-09-27」）
   - Raccoon：`buildRaccoonNickname`（保留服务端正式名 + 追加手机尾号 `RaccoonAva (1100)`，`jet-hub-rpc.ts:1146-1156`）
   - Loomy：`Loomy 2222`（`jet-hub-rpc.ts:1097-1101`）；LobsterAI：手机号只露末 2 位（`index.ts:1090-1092` 的启动修复）
2. **占位条目在「起本地服务器失败」时也要清**：loomy/raccoon 的 `startXxx` 抛错路径显式 `removeAccount`（`jet-hub-rpc.ts:1084-1089`、`:1135-1140`）—— 这是 02 D13（幽灵账号）的**部分修补**，但**进程崩溃路径仍无清理**，D13 判定不变。
3. **`logout` 与 `removeAccount` 的区别不变**（02 §2.5）：`removeAccount` 先清凭据再删条目（`account-pool.ts:426-434`）。

**新增的账号运维 RPC（Jet Hub 通道）**：`account.retest` / `account.retestAll` / `account.reset` / `account.resetAll`（`jet-hub-rpc.ts:1627-1660`）、`account.reorder`（`:1230`）、`backup.export/import/status`（`:2448-2490`）。

### 2.4 选号算法：**从「三步过滤取第一个」升级为「三段式 + 余额分档」**（相对 02 §4.2 的**重大漂移**）

**旧结论仍成立的部分**：`getAvailableAccount` 本体一字未改（过滤 1/2/3 → `candidates[0]` → 逐个解析凭据，`account-pool.ts:658-718`）。
**02 §0.2② 的「手动顺序即优先级，限流豁免」仍成立**（`:674-683` 注释原文保留）。

**但选号入口已经从 1 条变成 3 条**（**这是本轮最重要的机制漂移**）：

```
resolveCredential(modelId)（index.ts，逐 provider）
 ① 余额分档选号（仅 buddy / workbuddy / loomy 三条）        ← 🆕 02 完全没有
      候选 = listAccountsByProvider(id).filter(enabled).filter(未限流)   // 与池判据手工对齐
      → rankXxxAccountsByBalance / pickBuddyAccount → 档内保持手动顺序
 ② 账号池 getAvailableAccount(id, modelId, tried)          ← 02 的既有路径（fallback）
 ③ 单凭据 ref 回退（resolve(defaultCredentialRef)）        ← 02 §7.4「同一个概念两种表示」仍在
```

**【代码】证据**：buddy `index.ts:370-383`、workbuddy `index.ts:418-431`、loomy `index.ts:755-817`；分档纯函数 `buddy-balance-rank.ts:107-115`（三档 `expiring:0 / permanent:1 / none:2`）、`loomy-balance-rank.ts:32-39`（`daily:0 / permanent:1 / none:2`）。

**这直接推翻 02 §5.1 的核心结论**（「额度是独立查询接口，**不参与选号**」）：

| 02 结论 | 本轮判定 | 依据 |
|---|---|---|
| 「额度信息不进入 `getAvailableAccount` 过滤条件」 | ✅ **字面仍成立**（池函数确实没碰额度） | `account-pool.ts:666-672` |
| 「额度**不参与调度**」 | ❌ **已被推翻**：buddy/workbuddy/loomy 三家的**首选路径**就是余额分档 | `index.ts:370,418,782` |
| 「`account-pool.ts` 与 6 个 `*-adapter.ts` 对积分模块的引用为零」 | 🔁 **精确复核**：`account-pool.ts` 与全部 `*-adapter.ts`（8 个）**仍零引用** ✅；但 **3 个 `*-auth.ts`**（loomy/raccoon/zcode）**新增**引用，且新增的 2 个 `*-balance-selector.ts` 引用积分模块并**反过来驱动选号** | `grep "from './…-credits"`：命中仅 `loomy-auth.ts:39`、`raccoon-auth.ts:25,39`、`zcode-auth.ts:35-36`、`buddy-balance-rank.ts:49` 及 2 个 selector |

**新增的两个「静默降级」型缺陷与对策（很值得抄，10 的「运营专题」应吸收）**：

1. **Loomy 的额度耗尽不是错误**：服务端「继续扣永久积分且照常返回」→ 既有「限流→换号」对它**完全无效**（`loomy-balance-selector.ts:8-15`）。→ 对策：把「余额」变成**选号前**的判据。
2. **查询失败必须与「真的为 0」分开**（用户报障 2026-09-29）：曾把两者混成「今日额度都已用尽」，一次网络抖动就让用户被告知「钱花完了」（实测当时 4 个号里 3 个仍有 4965/5000/5000，`index.ts:790-801`）。→ 对策：**失败结果的缓存 TTL 比成功短一个数量级**（成功 60s / 失败 5s，`loomy-balance-selector.ts:47-52`、`buddy-balance-selector.ts:66-72`）；锁定态下失败要报**可区分**的错误（`unknown` vs `exhausted`）。

3. **锁定永久积分只能是「不参与选号」，不能是「降级」**：`allowPermanent=false` 时只剩永久积分的账号直接落 `none`（**等同不可用**），而**绝不能落到单凭据兜底**——「那会绕过锁定、照样消耗永久积分，锁定形同虚设」（`loomy-balance-rank.ts:62-64`、`index.ts:786-806`）。

### 2.5 并发与队列：**仍然零租约**（02 §4.6 / D1 判定不变，已复核）

**复核方法与结果**：对 `account-pool.ts` 全文（919 行）再做大小写不敏感 grep，模式 `lease|reserve|acquire|in_flight|inFlight|inflight|busy|mutex|round.?robin|cursor|occupied|claim` —— **零命中**。
**私有状态**：仍是 `store` / `cache` / `modelCache` / `permanentLockCache` / `loaded` / `lockStore`（`account-pool.ts:47-89`），**没有任何计数或时间戳结构**。

**新增了一个「排队」模块，但它不是账号池的队列**（避免误读）：`model-queue.ts` 是 **Qoder 上游排队错误（业务码 `10605`）的共享解析**（`model-queue.ts:1-30`），与「同一账号被并发选中」毫无关系。
**并且它引入了一个新的「精确等待」策略**（对网关的退避设计有参考价值）：排队延迟优先序 `retry_after_ms` → `retryAfterMs` → `retryAfterSeconds×1000` → 兜底 `Retry-After` 响应头；**有延迟就精确等它，没有才退回指数退避**（`model-queue.ts:24-30` 的客户端权威实现取证）。

**并发后果与 02 §4.5 完全一致**（确定性推演不变）：N 个并发请求仍会拿到同一个 `candidates[0]`。
**但本轮出现了「第二条并发路径」**：余额分档选号同样**没有任何占用标记**（`loomy-balance-selector.select(candidates, ...)` 是纯函数式排序，`loomy-balance-rank.ts:127-134`），所以**buddy/loomy 的并发同样全挤在同一档的第一个账号**。**结论：既有缺口未修，且新增了两处同型缺口。**

### 2.6 续期调度（02 §3.3 的「无条件刷新」已被修正，见 §0.2 R6/R7）

**`refresh.ts` 一字未改**（三个常量与 `generation` 竞态保护仍在：`refresh.ts:2,4,6,65-67,70-77,93-96`）—— **02 §3.2 结论完全成立，且新增一行 API**：`refreshOnce()`（`refresh.ts:80-83`，「供启动时已处于到期窗口内的凭据使用」）。

**`refreshAll` 的四处演进**：

| 维度 | 02 记录 | 本轮 |
|---|---|---|
| 刷新判据 | 无条件刷新（只看 `refreshable`） | **lead-time：距过期 ≤1h 才刷**（`expiry-sync.ts:89-92`），不刷的**只做本地对账**（`:186-198`） |
| 不刷的账号 | 直接 `continue` | **必须对账**（`expiry-sync.ts:160-165`）：「存量账号的凭据早已在别处续好了，只有池里还是旧值；若跳过时对账缺失，UI 会**永远**显示『已过期』」 |
| 续期后回写 | 部分 provider 缺失（issue !IKIRTT） | **统一回写 `expiresAt`/`refreshable` 到账号池**（`expiry-sync.ts:111-156`），且「现值一致时不写盘」（`:139-144`，避免每 30 分钟全量重写 39 条记录） |
| 缺访问令牌 | 未提及 | **绝不能把 `undefined` 落盘**（会把好凭据覆盖成 `"undefined"` 字符串、账号直接报废），显式抛错（`expiry-sync.ts:201-206`） |
| 停用账号是否刷新 | 刷（只看 refreshable） | **仍刷**，且已升格为注释里的契约（`index.ts:1145-1148`） |
| 失败日志 | 6 个 provider 里只有 qoder 有 warn | **收成一张 `refreshTargets` 表，10 个空 catch 改为逐个 `logger.warn`**（`index.ts:1102-1141`） |

**`refreshTargets` 现为 11 行**（`index.ts:1109-1127`），且**新增三类「不可续期 provider 的 refreshAll 语义」**（02/10 没有）：
- `loomy`：`refreshAll` 只**探测已过期**的账号（`:1118-1119`）
- `zcode`：不可续期，但 `refreshAll` **把磁盘上最新的凭据回写到全部 zcode 账号**（用户重登官方客户端后无需重启 DSH，`:1122-1126`）
- `raccoon`：可续期，但**只续进入 lead 窗口的账号**（`:1120-1121`）

**定时器启动缺陷的现状**（对应 02 D5）：`if (!hasRefreshable) return`（`index.ts:1158-1159`）——**「启动时无 refreshable 账号 → 定时器永不创建」仍未修**；但**首轮已补**（`:1160` 先 `void refreshAllCredentials()` 再 `setInterval`），且 `.then()` 补了 `.catch()`（`:1179-1187`，注释指出原来 reject 时「定时器永远不武装且日志一个字都没有」）。

### 2.7 每账号身份 / 设备隔离（10 §1.2 的字段字典需扩充）

| provider | 设备标识 | 持久化在 | 每账号互异？ | 续期时是否改写？ |
|---|---|---|---|---|
| `trae` | `machine_id` + `device_id` | 凭据本体 | 是（随机/派生） | **不改**（`trae.ts` 语义未变） |
| `qoder`/`qodercn` | `machine_id` | 凭据本体 | 是 | 不改（续期载荷必带） |
| `lobsterai` | `uuid` | 凭据本体 | 是 | 不改 |
| **`zcode`** | `device_mid` | 凭据本体（`zcode.ts:199`） | **是，但无显式查重** | 不可续期 |
| **`raccoon`** | `device_id?` | 凭据本体（`raccoon.ts:105`） | 未验证 | 未验证 |
| 其余 5 个 | 无 | — | — | — |

**10 §0.2 的判定（「DSH 只在生成时保证互异，无全局唯一性校验与冲突处理」）在本轮仍成立且**新增 2 个未受管的设备标识**。
**10 §1.4 / §1.6 的「设备注册表」仍是缺口**——zcode 的 `device_mid` 由插件自造（`zcode.ts:358` `readDeviceMid()` + `:297` 兼容旧格式），**没有任何跨账号冲突检测**。

### 2.8 Jet Hub 与账号相关的操作通道（完整清单）

**【代码】**`jet-hub-rpc.ts:1-13` 的模块头给出端点全集 + 本轮实测的子集：

| 通道 | 作用 | 位置 |
|---|---|---|
| `account.list` | 列账号（含展示态） | `:818-822` |
| `account.create` | 9 分支（见 §1.2 入口表） | `:824-1213` |
| `account.update` / `account.delete` / `account.reorder` | 改/删/拖拽排序 | `:1216-1251` |
| `account.refresh` | **按 `entry.provider` 分派到 9 个 `refreshAccountCredential`**（含 qoder/qodercn 用 `requireQoderFamily` 防串用） | `:1254-1339` |
| `login.poll` | 前端轮询占位条目是否已拿到凭据 | `:1341-1355` |
| `login.sendSms` / `login.submitSms` | 短信登录辅助（由本端点自己收手机号） | `:1363-1436` |
| `account.retest` / `retestAll` / `reset` / `resetAll` | 探活与重置 | `:1627-1660` |
| `credits.status` / `credits.claimAll` / `credits.balances` | 积分查询与领取 | `:1672-1960` |
| `onboarding.status` / `onboarding.claim` | **一次性新手任务** | `:1437-1626` |
| `credits.permanentLock`（含历史别名 `loomy.permanentLock`） | 锁定/解锁永久积分 | `:1502-1557` |
| `model.list` / `model.setDisabled` / `model.setAllDisabled` | 模型开关 | `:2287-2447` |
| `backup.export` / `backup.import` / `backup.status` | 备份 | `:2448-2490` |

**客户端侧调用约定**（`plugin-src/management-rpc.mjs`，全文 47 行）：**薄到只剩 `connection.rpc.call('/api', 'jet-hub', {method, payload}, signal)` + `unwrapRpcResult`**——**这个「客户端零业务逻辑、只用一张方法名表」的形态可直接照搬**（我们的网关若做前端，管理 API 层可以只保留这一层胶水）。

---

## 3. 账号运营（签到 / 领取 / 锁定永久积分）

### 3.1 逐产品能力清点（**11 个 provider 全部有余额查询；8 个有每日签到；3 个明确没有**）

**真相源 = `plugin-src/client/credits-capabilities.js:62-145`**（客户端门控）+ 后端各 `*-credits.ts`。**【代码】**（计数已逐行核对：`balance:true` ×11、`dailyCheckin:true` ×8、`dailyCheckin:false` ×3、`onboardingTasks:true` ×2）

| provider | balance | dailyCheckin | onboardingTasks | permanentLock | 端点与关键判据 |
|---|---|---|---|---|---|
| `codearts` | ✓ | ✓ | ✗ | ✗ | 华为 **SDK-HMAC-SHA256 签名**；三步：`GET /snap-manager/v1/statistics/plugin`（账户类型）→ `GET /v1/ops/delivery?channel=IDE` → `POST /v1/ops/claim` + `POST /v1/ops/confirm`（`codearts-credits.ts:23-26,82-88`）。**幂等是「客户端判定」**：`codearts-credits.ts:565` 明确「本协议没有幂等键，也没有服务端已领判定」 |
| `buddy` | ✓ | ✓ | ✗ | ✓ | `POST /v2/billing/meter/checkin-activity-status` + `daily-checkin`（`credits.ts:33,35`）。**幂等 = HTTP 400 + 业务码 `10001`**（`credits.ts:19,57`） |
| `workbuddy` | ✓ | **✗** | ✗ | ✓ | 国际版后端无签到接口（02 结论不变，`credits-capabilities.js:65`） |
| `lobsterai` | ✓ | ✓ | ✗ | ✗ | `client-activities` **三步**：slot → context → check_in（`lobsterai-credits.ts:214,252-266`）。**幂等 = 客户端幂等**（`claimedToday` + `actions` 含 `check_in` 双重预检）；另有客户端幂等键 `uuid`（`:266`，对齐 Go `sigin.py:63` 的 uuid4） |
| `qoder` / `qodercn` | ✓ | ✓ | ✗ | ✗ | `GET /sash/api/v1/me/campaigns` → 逐个 `POST …/{campaignId}/claim`。**幂等 = 响应体 `replayed:true`**（重复领取同样 **HTTP 200**，`qoder-credits.ts:53-54,576-578`）。⚠️ **「无可领活动」必须报 `inactive` 不能报 `already-claimed`**（`:605-610`：二者语义完全不同） |
| `trae` | ✓ | ✓ | ✗ | ✗ | `POST /trae/api/v2/ug/checkin_credits/status` → `claim`（`trae-credits.ts:19,23`）。**幂等判据只能来自 status 端点的 `checked_in`**——claim 对已签到同样回 `{code:0,"success"}`，**与真正领取无法区分**（`jet-hub-rpc.ts:1801-1806`，用户报障「显示成功但 +0 积分」）。错误分类自带冷却表（12h/60s/-1/600s/300s，`trae-credits.ts:74-99`） |
| `cline` | ✓ | **✗** | ✗ | ✗ | 只有余额（`GET /api/v1/users/{id}/balance`）；`dailyCheckin:false` 的依据是**对整个 sidecar 二进制做字符串扫描**（`credits-capabilities.js:94-99`，比「某次没看到」强，但仍非「永远不存在」） |
| `loomy` | ✓ | ✓ | **✓** | **✓** | 签到 = `POST /api/v1/points/first-login`（触发每日赠送额度，**不是 +5000**：`dailyBalance = dailyQuota - dailyConsumed`，`loomy-credits.ts:23,35`）；新手任务 = `GET/POST /api/v1/onboarding/tasks*`，8 任务共 10000 分**一次性**（`loomy-onboarding.ts:19-27`）。⚠️ **不采信服务端 `earned`，按本地 `LOOMY_TASK_POINTS` 现算**（`:27-28`，官方自己也这么做） |
| `raccoon` | ✓ | **✗** | **✓** | ✗ | 每日 300 积分**服务端按日自动发放**（账单 `biz_type: 'daily_grant'`），**没有可调用的签到端点**——把它做成按钮会让用户每次点击必然失败（`credits-capabilities.js:117-121`）。登录奖励 = `POST /api/web/desktop/v1/login/points/grant`（3000 分，**幂等一次性**，判据是响应体 `granted`，`raccoon-credits.ts:197-200`）；⚠️ **该端点必需 `X-Client-Platform` 头**（`:268`） |
| `zcode` | ✓ | ✓ | ✗ | ✗ | 签到 = 补 `event/report`（`app_launch`+`app_daily_active`）→ `billing/preview` → `billing/claim`（`zcode-auth.ts:510-520`）。⚠️ **需要阿里云 captcha，且 captcha 一次性**——每个 plan 必须重新 mint（复用会得 `3007`，`zcode-auth.ts:556-561`）。**量纲是 token 不是积分**，能力矩阵如实登记为 `balance:true` 并在 UI/RPC 层标注量纲差异（`credits-capabilities.js:138-143`） |

**三个「明确没有」被显式处理（值得抄的工程习惯）**：cline / raccoon / workbuddy 的 `credits.claimAll` 不是落到泛化的 `unsupported provider`，而是回**可读的业务性错误**（`jet-hub-rpc.ts:1857-1888`）——理由（`:1862-1864`）：「后者会让排查者以为是『provider 没注册』，而真相是『该产品无此能力』」。

### 3.2 统一抽象（本轮的「架构级提炼」）

**四类结果分类（02/10 记录）升级为「四类 + 三条正交约束」**：

```ts
// credits.ts:118-122
type ClaimOutcome =
  | { kind: 'claimed';        credit; streakDays; isStreakDay; delayedMessage? }
  | { kind: 'already-claimed'; message }              // ← 正常业务状态，不计失败
  | { kind: 'inactive';       message; actionRequired? }  // ← 正常业务状态
  | { kind: 'failed';         code; message }        // ← 唯一需要用户关注的
```
汇总用 `computeClaimSummary`（**纯函数**，`jet-hub-rpc.ts:297-329`），且带**编译期穷尽性检查**：`const exhaustive: never = outcome`（`:316-325`）——新增 kind 时**必须显式决定它计入哪一栏**，否则编译报错；运行期兜底按 `failed` 计入（「宁可多报一个失败，也不让结果凭空消失」）。**这条双重保险值得直接照搬。**

**逐账号编排：一套泛型编排 + 各协议注入下钻函数**（`jet-hub-rpc.ts:343-403` 的 `CreditsEndpointDeps`）：
- `collectCreditsStatus`（`:416`）/ `collectClaimResults`（`:461`）/ `collectCreditBalances`（`:547`）**三兄弟只写一遍**，泛型参数默认 Buddy 系，故既有调用点零改动。
- **五条不变式**（写死在注释与实现里，**逐条抄**）：
  1. **顺序执行**，不并发（理由：并发易触发风控，`:406,452,535`）
  2. **单账号失败不中断整体**（`:338-340` 的泛型化理由原文）
  3. **凭据解析必须在 `try` 之内** —— `credentialRef()` 的正则校验会抛 `TypeError`，留在 `try` 外会让**整批**以 `jet-hub/handler-failed` 失败（`:411-415`）
  4. **包含已停用账号**（签到状态查询）——「用户要看到的是『这个账号今天领了没』」（`:407-409`）
  5. **`precheckStatus` per-provider 显式声明**（`:374-385`）：CodeBuddy 系 `true`（拆成「查状态+领取」两端点，先查可省一次无效领取）；LobsterAI / Qoder / CodeArts 传 `false`（领取流程**自身多步**、内部已判幂等，再查一次纯属重复请求）。⚠️ **TRAE 必须为 `true`**，理由是一次**真实缺陷**（见 §3.1 trae 行）

**⚠️ 本轮新增的一处「编排层真实缺陷」（教训极强）**：`deps.claim ?? (claimDailyCheckin as unknown as …)` 把**三参**函数硬转成两参类型 → 调用点写 `claim(credential, product, entry)` 时 **`entry` 落进了 `fetcher` 位置** → 运行时 `TypeError: fetcher is not a function`（用户一键领取 4 个 CodeBuddy 账号全部失败，`jet-hub-rpc.ts:390-401`）。
修法是**显式包装默认实现**（而不是继续用 `as unknown as` 强转）。**教训：类型断言绕过参数位置检查 = 把编译期错误推迟到运行时。**

### 3.3 锁定永久积分（`permanentLock`）—— **本轮全新的运营维度**

**语义**：锁定后**只允许消耗会近期作废的积分**，永久积分不参与选号；只剩永久积分的账号在锁定期间**等同于不可用**（`account-pool.ts:277-283`）。

**三家支持，两套判据**（`jet-hub-rpc.ts:272-290` 的 `PERMANENT_LOCK_PROVIDERS`）：
- `loomy`：服务端直接给两个池（`dailyBalance` / `balance`）
- `buddy` / `workbuddy`：**要从资源包列表现算** —— 按 `DeductionEndTime` 距今是否满 **15 天**（`buddy-balance-rank.ts:18-31,59`）

**为什么用 `DeductionEndTime` 而不是 `CycleEndTime`（实测表格，很有价值）**：`Free Plan` 的 `CycleEndTime` 距今 2 天但 `DeductionEndTime` 距今 3008 天 —— 取 `CycleEndTime` 会把每月刷新的套餐判成「马上作废」，**锁定形同虚设**（`buddy-balance-rank.ts:20-31`）。

**逃生门（对我们是重要设计输入）**：15 天这条线在两站效果差别极大（中国版的包天然落在 17~30 天区间 → 锁定后**立刻「无可用账号」**），故提供 `DSH_BUDDY_EXPIRING_WINDOW_DAYS` 覆盖，且**默认值必须由用户显式改**（`buddy-balance-rank.ts:64-99`）。
⚠️ 解析**不能写成 `parseInt(raw) || 默认值`**：`0` 是合法值（表示「没有临时积分」→ 锁定期间整池不可用），而 `0` 是 falsy（`:86-89`，与 Qoder 排队超时同一个坑）。

**持久化的三重坑（用户点名，全在 `permanent-lock-store.ts`）**：
1. **为什么不能与账号池放同一份文档（真实风险，用户 2026-09-29 定案）**：`state.json` 是 **dsh home 级、多 profile 共享**；写入是**整体替换**语义；另一条工作区里的**旧版本代码**不认这个字段 → 全量重写时**静默抹掉** → CodeBuddy/WorkBuddy **静默解锁** → 「解锁后选号继续消耗永久积分，而积分烧掉**不可撤回**」（`permanent-lock-store.ts:4-25`）。
2. **单向迁移，判据只认「文件不存在」**：新文档不存在时才读老字段；一旦存在即为**唯一权威，不再回看老字段**——否则用户在 desktop 里解锁后会被老字段里陈旧的 `true` 重新拉回锁定态（`:27-32`、`account-pool.ts:105-128`）。
3. **写顺序：权威先落、镜像后落且失败只 warn**（`account-pool.ts:317-345`）：理由原文「独立文档才是本 profile 选号的依据；镜像写失败只让另一条工作区的面板显示旧值，**不会让我们误烧用户的永久积分**」。
   另有**第四坑**：损坏时按「文档存在但空表」处理，**不**回落到老 state.json 字段——「那条路径会把用户已解除的锁定重新打开，**保守方向在这里是反的**」（`permanent-lock-store.ts:94-99`）。

### 3.4 运营操作的入口与批量入口（Jet Hub 侧）

| 入口 | 方法 | 批量策略 |
|---|---|---|
| 一键签到 | `credits.claimAll` + `provider` | 逐账号**顺序**；每账号内部自带幂等；结果按 §3.2 四类汇总 |
| 查签到状态 | `credits.status` | 逐账号顺序；**6 个 provider 如实返回 `status: null`**（不臆造状态对象），只对 CodeBuddy 系走真实端点（`jet-hub-rpc.ts:1672-1747`） |
| 查余额 | `credits.balances` | 逐账号顺序；**CodeArts 用「带原因」的钩子**区分「Token 计费账户」与「余额查询失败」（`:1958-1980`） |
| 新手任务 | `onboarding.status` / `onboarding.claim` | **独立端点**，与每日签到语义分离（「每号只能领一次」vs「每天有收益」，`:1555-1562`） |
| 客户端门控 | `checkinProviders()`（`credits-capabilities.js:321-323`） | **从能力表推导**，页头「一键签到」遍历它 —— 注释明确禁止硬编码渠道字面量（否则「新渠道永远不被签到」或「对已下线渠道发必然失败的请求」） |
| 锁定 | `credits.permanentLock`（含历史别名 `loomy.permanentLock`，`:1502-1557`） | 写入后 `ctx.emit('llm/adapters-updated')` 广播（因为**开关会改变选号结果**）；广播失败不反噬已落盘的开关 |

**⚠️ 一处「双真相源」风险（本轮新增发现）**：能力矩阵现在**有两份用途相反的默认值约定**——积分能力「**默认关闭**」（未登记=不支持，避免必然失败的请求），限流能力「**默认开启**」（未登记=有限流，避免老用户凭空失去按钮）。两者都写在同一文件且都有充分理由（`credits-capabilities.js:156-162`），但**新增产品时必须同时想清楚两个方向**，容易搞反。

### 3.5 ⚠️ 规则漂移：TRAE `9074` 设备轮换**已被废弃**（推翻 02 §5.4 与 10 §1.4 的操作性建议）

**02 §5.4 / 10 §1.4 曾把「只存整数代次、派生不改本体、只增不减」列为「非常聪明，直接抄」的机制。本轮实测：该机制在 DSH 里已成为死代码。**

| 事实 | 证据 |
|---|---|
| `9074` 现在**不再触发换设备号**，直接返回 `failed` + 冷却 300s | `trae-credits.ts:265-276`（注释原文「**9074：设备轮换已废弃，不再重试**」「基于 user_id 确定性派生设备身份，不同账号天然不同设备」） |
| `onRotate` 回调参数**仍在签名里但零调用点** | `trae-credits.ts:231`（声明）；全仓 grep `onRotate` 仅此一处 |
| 代次回写链路仍在，但**永远不会被触发** | `jet-hub-rpc.ts:1815` 传入 `(next) => pool.updateTraeCheckinDeviceGeneration(...)`；`account-pool.ts:774-790` 实现仍在；但调用方 `onRotate` 从不被调用 |
| 派生函数本身仍保留 | `trae.ts:1334-1337`（`deriveCheckinDeviceId`）、`:1361-1364`（`deriveRotatingMachineId`）；`trae.ts:260` 仍在用 generation 派生头 |

**为什么废弃（新机制）**：TRAE 签到身份改为 **基于 `credential.uid` 确定性派生**（`trae.ts:286` 的 `deriveDeviceId15(userId)`；`trae-credits.ts:219` 原文「设备身份：基于 `credential.uid` 确定性派生，**每个账号独立稳定**」）。
→ **对 10 的「设备注册表」设计的直接影响**：DSH 的经验说明**「确定性派生」比「随机生成 + 冲突检测」更省事**——`device_id = f(uid)` 天然满足「每账号互异」「跨进程稳定」「无需持久化」三条，且**不需要注册表**。
→ **但仍不满足 10 §1.4 的「导入已有缓存时复用原设备 ID」**：确定性派生只覆盖「本插件自己算出来的」场景。**建议：我们的设备层把「确定性派生」作为默认策略，把「导入复用 + 冲突拒绝」保留为显式路径**（两者不冲突：派生函数是纯函数，导入时若缓存里已有设备标识则优先复用缓存值）。

**冷却表仍在用（可抄）**：`classifyTraeCheckinError`（`trae-credits.ts:74-99`）：`1005`→12h / `429`→60s / `401`→**-1（永久）** / `404`→60s / `5xx`→600s / `4xx`→600s / 业务码非 0→300s。

---

## 4. 增量与漂移清单（相对 02 / 10 / v2-02）

### 4.1 新增产品（5 个，`src/` 与 `package.json` 一致）

| provider | 一句话定位 | 登录 | 特有难点（代码注释里的实证） |
|---|---|---|---|
| `qodercn` | Qoder 中国版（**不是新协议，是同产品第二区域**） | 设备码轮询 | ⚠️ **国际/中国两站 token 不通用**，`account.refresh` 必须用 `requireQoderFamily` 分派（`jet-hub-rpc.ts:1287-1295`：注释明确「不要图省事写 `qoder.refreshAccountCredential(...)`」） |
| `cline` | Cline（WorkOS 设备码） | WorkOS 设备码轮询 | ⚠️ **`Authorization` 必须保留 `workos:` 前缀**（剥掉前缀回 401，实测，`cline-product.ts:96-115`）；免费模型集合**只由 `recommended-models` 的 `free` 数组下发**（`cline-models.ts:8-13`） |
| `loomy` | 讯飞 Loomy | **微信扫码**（本地弹窗页） | ⚠️ 早期「先要手机号、但表单等 `loginMode:'sms'`」造成**顺序死锁**（用户报障，`jet-hub-rpc.ts:1063-1067`） |
| `raccoon` | 商汤小浣熊 | 本地页承载 微信扫码 / 短信 | ⚠️ **思考档位只有开/关**（`reasoning_effort` 8 个枚举全被接受但**实测无效果**，只有 `extra_body.thinking.type` 生效；8 轮配对实验，`raccoon-product.ts:24-70`）；⚠️ 图片约束是**请求体字节**（`HTTP_413: request body exceeds 10MB`）不是 token（`raccoon-product.ts:91-118`） |
| `zcode` | 智谱 z.ai | 官方 OAuth 设备流（`/oauth/cli/init` → 浏览器 → `/oauth/cli/poll/{flow_id}`） | ⚠️ **必须每请求产一个阿里云 captcha**（约 1.2 秒，需常驻 chromium）；⚠️ 协议是 **Anthropic Messages**（不是 OpenAI 兼容）；⚠️ 请求体必须带官方身份块与首轮日期块，否则回 `3012`（`index.ts:940-961`） |

### 4.2 新增机制（**02/10 完全没有的 6 项**）

| # | 机制 | 位置 | 解决了什么 | 对我们的价值 |
|---|---|---|---|---|
| M1 | **`expiry-sync`（lead-time + 池值对账）** | `expiry-sync.ts`（221 行） | 「凭据续好了但 UI 显示已过期」的数据源分叉（issue !IKIRTT） | ⭐ **直接照搬**：我们的 `ResourceState.expires_at` 会有同一个坑（§5.1） |
| M2 | **独立状态文档 + 镜像字段** | `permanent-lock-store.ts` | 多 profile 共享文档被旧代码整体重写抹掉 | ⭐⭐ **必须抄**：我们若有多进程/多版本共存场景同理 |
| M3 | **存储后端按能力探测（settings/file/memory 三态）** | `jet-hub-store.ts`、`settings-compat.ts` | 宿主 API 破坏性升级导致账号列表**退化为纯内存**（真实缺陷 IKI7WT） | ⭐ 我们有 loader 原子写，但「探测 + 显式降级 + warn」的分层值得抄 |
| M4 | **余额分档选号** | `buddy-balance-rank.ts`、`loomy-balance-rank.ts`、两个 selector | 「额度耗尽不是错误」型静默降级（Loomy）与「积分何时作废」的负载均衡 | ⭐⭐ 与 02 §8.5「额度参与调度」的建议**方向一致，本轮已落地实现**，可直接抄判据 |
| M5 | **锁定永久积分（运营开关）** | `permanentLock` RPC + 两个 rank 模块的 `options` | 用户要「保住不过期的积分」 | ⭐ 需求轮可评估（我们若做 OAuth 号池，这是高价值特性） |
| M6 | **上游排队错误的精确等待** | `model-queue.ts` | 排队业务码 `10605` 在 **HTTP 200 + 流内帧**与 **403 + JSON** 两条通道出现 | ⭐ **通道二义的教训**：同一业务错误可能出现在「流内帧」与「HTTP 错误体」两处 |

**另有 4 项与「运营/账号」弱相关但值得记录的新增**：`image-budget.ts`（图片像素/字节预算，直击「一张截图值 ≈2781 token」的上下文爆炸）、`backup.ts` + `backup.export/import`（备份导出含**脱敏**选项）、`plugin-src/client/account-order.js` / `account-model-link.js` / `model-bulk.js`（客户端侧排序与模型联动）、`plugin-src/client/credit-expiry.js`（积分到期展示）。

### 4.3 旧结论修正表（**逐条判定**）

| 02/10 旧结论 | 判定 | 说明 |
|---|---|---|
| 02 §0.2① 产品差异 = 4 个平行接口 | 🔁 **漂移**：**7 个** | 新增 cline/loomy/raccoon/zcode 各建新接口；qodercn 让 `QoderProduct.id` 变成联合类型（证明 02 引用的「加值会牵动一串调用点」是真的，但**并未阻止加值**） |
| 02 §0.2② 选号三步过滤取第一个 | ✅ 成立（`account-pool.ts:658-718`），**但入口已变为三段式** | 余额分档 → 池 → 单凭据 |
| 02 §0.2③ 凭据/账号索引分离 | ✅ 成立 | 落盘后端换了（settings → file），`credentialRef` 指针语义不变 |
| 02 §0.3 / §4.5 **无并发租约** | ✅ **仍成立**（本轮再复核零命中） | 且新增的余额分档路径**同样无占用标记** |
| 02 §1.4 「产品配置里没有任何限流字段」 | ✅ 成立 | 但新增了「该 provider 是否有限流」的**能力矩阵**（`RATE_LIMIT_CAPABILITIES`） |
| 02 §1.5 目录门控「凭据可解析」而非「有条目」 | ✅ 成立，行号漂移 | `providerCatalogVisible` 现在 `account-pool.ts:892-906`；`DSH_HIDE_MODELS_WITHOUT_ACCOUNT` 默认开启（`:910-919`） |
| 02 §2.5「没有同一用户重复登录的去重」 | ✅ **仍成立** | `addAccount` 仍是纯 append（`account-pool.ts:407-410`） |
| 02 §3.3「refreshAll 无条件刷新，不看过期」 | ❌ **已被修正** | lead-time（≤1h）过滤 + 不刷的也对账（§2.6） |
| 02 §3.3「定时器启动缺陷（无 refreshable 则永不创建）」 | ⚠️ **仍在**（`index.ts:1158-1159`） | 但「首轮等满 30 分钟」已修 |
| 02 §3.3 D4「每 30 分钟一次 TRAE token 轮换」 | ❌ **已缓解** | TRAE 续期现走 lead-time（`trae-auth.ts:440-472`），轮换频率降到「距过期 1h 内」 |
| 02 §4.2 细节 1「首次选号 modelId 传空串」 | 🔁 **部分修正** | 11 个 provider 里 8 个首选路径已传真实 modelId（`index.ts:381,425,528,585,634,672,877,996`）；3 个（codearts/lobsterai/loomy）仍传 `''`（`:245,482,824`） |
| 02 §4.3「写标记的并发正确性（落盘顺序无保证）」 | ⚠️ **仍无法验证** | `settings.replace` 的串行化问题换成 `store.save`，`FileLockStore` 用 tmp+rename（原子），但**并发写仍是 read-modify-write 整体替换**，无 CAS/队列（`account-pool.ts:142-154`） |
| 02 §4.4 探活 vs 重置语义 | ✅ 成立，行号漂移 | 探活 `account-probe.ts:283/331`、重置 `:351/357`；⚠️ **分派表现在有 4 条分支**（buddy / lobsterai / trae / codearts-else），注释自承**两次因漏加 provider 而出缺陷**（`:186-197`） |
| 02 §5.1「额度不参与选号」 | ❌ **已被推翻**（3/11 provider） | 见 §2.4 |
| 02 §5.2 额度口径（周期 vs 终身、精确值优先、失效三重判定） | ✅ 未复核（本轮未读 `credits.ts` 的对应行） | 标注为**未复核**而非「成立」 |
| 02 §5.3 能力矩阵「默认关闭」 | ✅ 成立并扩展 | 新增 `onboardingTasks`、`RATE_LIMIT_CAPABILITIES`（**方向相反**）、`PERMANENT_LOCK_EXPIRING_WINDOW_DAYS`、`supportsCreditPackageList`（`credits-capabilities.js:224-227`） |
| 02 §5.4 / 10 §1.4 TRAE 9074 设备轮换代次「非常聪明，直接抄」 | ❌ **操作建议已废弃** | DSH 改用 uid 确定性派生，9074 不再换设备号（§3.5） |
| 02 §6.x 错误分类三套并存 | ✅ 成立 | 新增 `model-queue.ts` 的排队/额度码分类（第 4 套），但它是共享模块（比 02 的「不统一」有改善） |
| 10 §0.1 设备指纹必须持久化/续期不动/每账号互异 | ✅ 成立 | 新增 zcode `device_mid` / raccoon `device_id` |
| 10 §0.2「DSH 只在生成时保证互异，无全局唯一性校验」 | ✅ **仍成立**（新设备标识同样无查重） | 但出现**新选项**：uid 确定性派生（§3.5） |
| 10 §2.2 三条血泪教训（权威状态源 / 幂等看响应体 code / 停用账号不参与批量） | 🔁 **部分修正** | ①「权威状态源」仍成立且**新增反例**：TRAE 的 claim 响应**无法区分**已领与真领，只能靠 status 端点（`jet-hub-rpc.ts:1801-1806`）；②「幂等看响应体 code」**升级为「业务码 + 客户端判定 + 服务端回放标记」三型**（见 §3.1）；③「停用账号不参与批量」**不成立**——`collectCreditsStatus` 明确**包含已停用账号**（`:407-409`），只有**选号**才排除停用 |
| 10 §2.3 批量执行器（串行 + 间隔 + 失败隔离） | ✅ 成立 | **但「间隔」未实现**：`collectClaimResults` 只有串行，**没有账号间 sleep**（`jet-hub-rpc.ts:461-533`）。10 §2.3 表里那条「串行 + 间隔」的「间隔」是**我们自己的建议**，不是 DSH 的现状 —— **此处需要更正 10 的表述** |
| 10 §2.4「运营与核心调度解耦」 | 🔥 **被 DSH 自己打破** | 余额分档选号**把运营侧的余额查询直接接进了核心选号链路**（`index.ts:370,418,782`）——DSH 的取舍是「宁可耦合也要解决静默降级」，与 10 的定案**相反**。**这是我们需求轮必须重新权衡的一处冲突**（见 §5.4） |

### 4.4 行号漂移速查（旧 → 新，供后续复用）

| 结论 | 02/10 旧行号 | 本轮新行号 |
|---|---|---|
| 账号池 schema / 私有状态 | `account-pool.ts:126,136,141,143` | `account-pool.ts:49,59,64,77,79,81`（新增 `permanentLockCache`/`lockStore`） |
| `getAvailableAccount` | `:565-625` | `:658-718`（+93） |
| 手动顺序即优先级 | `:581-590` | `:674-683` |
| `modelId` 空串短路 | `:575` | `:668` |
| `excludeAccountIds` 必要性 | `:553-564` | `:646-656` |
| `sweepExpiredRateLimits` 无调用方 | `:655-670` | `:748-763`（仍是死代码） |
| 探活/重置语义 | `account-probe.ts:1-30` | `:20-36`；入口 `:283/331/351/357` |
| 探测不传 accountPool | `:115-117` | `:173-175` |
| 全量重测串行 | `:230-233` | `:325-345`（`:328-329`） |
| 探测超时 120s | `:61` | `:112` |
| 续期三常量 | `refresh.ts:2,4,6` | 不变（文件未改） |
| `generation` 竞态保护 | `refresh.ts:46-47,93-96` | `refresh.ts:49-50,65-67,70-77,96-99` |
| 全局 30 分钟批量 | `index.ts:357-401` | `index.ts:1100-1187` |
| 定时器启动缺陷 | `index.ts:386-401` | `index.ts:1157-1187` |
| `settings.replace` 整体替换 | `account-pool.ts:187-189,250-251` | `account-pool.ts:136-154,244-266`（概念不变，改为 `store.save`） |
| 目录门控 | `account-pool.ts:744-759,767-771` | `:892-919` |
| `currentAccountId` 靠 token 反查 | `account-pool.ts:417-429` | `:510-524`（`findAccountIdByCredential`） |
| 能力矩阵 | `credits-capabilities.js:60-73,81-92` | `:62-145`（表）+ `:294-305`（门控函数）+ `:321-346`（列表推导） |

---

## 5. 网关侧借鉴点

> 网关侧现状基线（本轮实测）：`Resource`（`schemas.py:138-164`）**已有 `product: str` 字段**（v2.0 §14.2 阶段一 / 调研 09 D7，注释写明「Q27-⑤ 已否决统一四表，本列是账号存储落地的**唯一**保留项」）；`api_key` 仍 `min_length=1`（`:156`），`account` 仍是自由文本（`:157`）。

### 5.1 ⭐⭐ 直接照搬（无需改设计）

| # | 借鉴点 | DSH 证据 | 落到我们哪里 |
|---|---|---|---|
| B1 | **续期与「池值对账」必须分开**：lead-time 判据用**凭据**的过期时间（不是账号池/资源状态里那份可能陈旧的值）；不刷的也要回写一次 | `expiry-sync.ts:76-92,160-165` | `ResourceState.expires_at` 与凭据里的 `exp`. 建议新增 `should_refresh_now(credential_exp)` + `reconcile_expiry(state, credential)` 两个函数，**在 `ResourceManager` 之外**（它是纯状态管理，不该发网络） |
| B2 | **续期响应缺 token 时绝不能把 `undefined` 落盘**（会把好凭据覆盖成 `"undefined"` 字符串、账号直接报废） | `expiry-sync.ts:201-206` | 凭据写入路径加显式校验；我们已有 pydantic，可再加一道 `model_validator` 拒绝空 `api_key` |
| B3 | **「查询失败」与「真的为 0」必须分开，且失败缓存 TTL 比成功短一个数量级** | 成功 60s / 失败 5s：`loomy-balance-selector.ts:44-52`、`buddy-balance-selector.ts:66-72` | 我们的 `bench`/余额查询若要做缓存，用同款「失败短 TTL」；也适用于厂商模型目录缓存 |
| B4 | **`computeClaimSummary` 的双重保险**（编译期穷尽性检查 + 运行期未知 kind 计 failed） | `jet-hub-rpc.ts:297-329` | `model_gateway/ops/` 的结果汇总：Python 用 `match` + `assert_never` 等价实现 |
| B5 | **凭据解析必须在 `try` 之内**（否则单个账号的异常会让**整批**失败） | `jet-hub-rpc.ts:411-415` | 批量运营执行器逐账号 try 的边界必须**包含**凭据解析/解析校验 |
| B6 | **`precheckStatus` 必须 per-provider 显式声明**，不能全局一刀切 | `jet-hub-rpc.ts:374-385`（+ TRAE 的真实缺陷 `:1801-1806`） | 我们的 `AccountOperation` 接口（10 §2.3）应加 `needs_precheck: bool` 字段 |
| B7 | **能力矩阵「默认关闭」+ 从表推导渠道列表（禁止硬编码字面量）** | `credits-capabilities.js:294-323` | 我 `capabilities` 字段（v2-02 §8.2 已建议）直接采纳；再加一条「列表必须从表推导」的约定 |
| B8 | **「不支持」要回可读的业务性错误，不能回泛化的 `unsupported provider`** | `jet-hub-rpc.ts:1857-1888` | 我的 ops 若收到不支持的 provider，错误文案要能区分「未注册」与「该产品无此能力」 |
| B9 | **原子写 + 探测式降级 + 显式 warn**（三态存储后端） | `jet-hub-store.ts:82`、`settings-compat.ts:1-20` | 我们的 `loader.py` 已有原子写；建议补「无法持久化时显式告警而不是静默内存态」 |

### 5.2 ⭐ 需要改造后照搬（我们的架构与 DSH 不同）

| # | 借鉴点 | DSH 做法 | 我们的改造 |
|---|---|---|---|
| B10 | **余额参与调度** | 在 `resolveCredential` 入口插一段「余额分档 → 排序 → 取第一个」（`index.ts:370,418,782`） | ⛔ **不能照抄这个插法**（它把网络查询塞进了每次请求的选号路径，靠 60s 缓存掩盖）。我们应做成 **`pick_and_acquire` 的次级排序键**（同 `in_flight` 时优先「快到期额度多」的），并**由独立的余额刷新任务**维护 `credit_balance`/`credit_expiring`，**选路本身零网络调用**（v2-02 §8.5 已给出同方向建议） |
| B11 | **锁定永久积分** | 开关进独立文档；锁定时「只剩永久积分的账号等同不可用」，但**绝不落到单凭据兜底** | 若我们做：`Account.exclude_permanent_only: bool` + 选路过滤。**关键**：锁定态下「查不到余额」要**报可区分错误**（`unknown` vs `exhausted`，`index.ts:790-805`），否则一次网络抖动会告诉用户「钱花完了」 |
| B12 | **确定性派生设备身份**（取代随机 + 注册表的一部分） | `device_id = f(uid)`（`trae.ts:286`、`trae-credits.ts:219`） | 10 §1.4 的设备注册表**可简化**：优先用 `f(account_uid)` 派生（纯函数、跨进程稳定、天然互异），**把注册表收窄为「导入已有缓存时的复用 + 冲突拒绝」**（10 §1.4 的 D11 保留，D9/D12 可大幅缩水） |
| B13 | **多 profile / 多进程共存时的「独立文档 + 镜像」** | `permanent-lock-store.ts:4-25` + `account-pool.ts:317-345` | 我们的铁律 1 是纯本地明文；但**若同一份 `data/` 会被两条工作区/两个版本的网关进程读写**（用户已在 DSH 侧刻意如此），则这条**必须**有。需要用户确认是否存在该场景（列入未验证） |
| B14 | **`allowPermanent` 型「降级为不可用」而非「降档」的语义** | `loomy-balance-rank.ts:55-64` | 我 `Resource.status` 加一个「不参与本维度」的表达；建议用 `disabled_by_policy` 而非新增 status 值 |

### 5.3 ⛔ 明确**不抄**（照抄会让我们退步）

| # | DSH 的做法 | 为什么不能抄 |
|---|---|---|
| C1 | **账号池无并发租约** | 与 DSH 一致会破坏我们已有的 `in_flight` 聚合（02 §8.5 D1 结论不变） |
| C2 | **余额分档选号在每次请求的选号入口做网络查询** | 我们的 `pick_and_acquire` 是同步段（`resources.py:120-144` 注释「选路与在途 +1 在同一同步段，无 await」）。把网络查询塞进去会直接破坏该不变式 |
| C3 | **9 个 `*Auth` 各写一遍 `refreshAll`/`status`/`logout`**（02 D9） | 我们的规模不允许：应抽基类 + `Product.auth` 数据驱动（v2-02 §8.5 已建议） |
| C4 | **运营操作与核心调度耦合**（余额分档是运营侧数据反过来驱动核心选号） | 10 §2.4 的定案（可插拔模块 + 解耦）**我们应保留**；DSH 的耦合是被「静默降级」逼出来的，我们可以用「运营侧维护、调度侧只读缓存」达成同样效果而**不引入请求期网络调用** |
| C5 | **`onRotate` 这种「保留参数但不再调用」的死代码** | 我们实现设备轮换时要么做要么删（DSH 的 `trae-credits.ts:231` + `account-pool.ts:774` 是典型的「注释说废弃、代码留着」） |

### 5.4 ⚠️ 必须向需求轮提交的一处**冲突**（不是 bug，是取舍）

**10 §2.4 定案「运营操作与核心调度解耦」，而 DSH 本轮的选择恰好相反。**
- DSH 的理由：Loomy 的额度耗尽**不报错**，「限流 → 换号」的反馈环完全无效，只能在选号前读余额。
- 我们的机会：我们的 `ResourceState` 已有 `status` / `cooldown_until` / `C`（连续失败计数）与**可注入时钟**（`resources.py:68`），且**选路一开始就知道 system_model**（02 §0.3 的对照结论）。因此可以走「**运营侧后台任务刷新余额 → 写进 `ResourceState` → 选路只读**」这条路，**两头的好处都拿到**。
- **需要用户/需求轮确认的点**：余额刷新任务的频率、失败退避、以及「余额为 0 但未过期」是否要直接判 `Resource` 不可用（DSH 是判的，代价是「查不到就被视为不可用」的风险——它已用「失败短 TTL + 可区分错误」缓解）。

---

## 6. 未验证清单

| # | 事项 | 卡点 | 影响 |
|---|---|---|---|
| U1 | **02 §5.2 的额度口径结论未复核**（周期 vs 终身、精确值优先、失效三重判定、`roundCredits`） | 本轮按任务优先级只核了「额度是否参与选号」（已推翻）与运营端点，未重读 `credits.ts` 的对应行段 | 中：若网关要做积分展示，这些口径仍需以当前代码重新核对（**不要沿用 02 的行号**） |
| U2 | `ctx.credentials` 的存储位置/加密方式/`env`\|`file` 两种 source 优先级（02 U1） | `@deepseek-ai/dsh-credentials` 仍**不在本机 `node_modules`**（无 `node_modules` 目录），无法读实现 | 低（本轮新增证据：`docs/adding-a-new-provider.md:81` 注释称凭据为「加密存储」，但**无代码可验**） |
| U3 | `credentialRef()` 的名称正则约束具体是什么（02 U2） | 同上；仅见 `jet-hub-rpc.ts:411-413` 与 `docs/adding-a-new-provider.md:528` 提到「会对名称做正则校验」且「非法名称抛 TypeError」 | 低（我们可自定义命名规则，只需满足自己的 pydantic 约束） |
| U4 | `JetHubStore.save` / `FileLockStore.save` 的**并发写是否串行化** | 两个实现都是「同步读 → 改 → 异步原子写」，**无 CAS / 无写队列**；但无法确认宿主是否对同一文件的写入做串行化 | 中：决定「限流标记并发丢失」是真实缺陷还是理论风险（与 02 U3 同源，换了后端但问题形态不变） |
| U5 | `zodercn`（Qoder 中国版）是否真有每日领取活动 | 代码只是**与要素同形**且注释明确要求「若将来确认 CN 无签到，改这里时必须换成强证据」（`credits-capabilities.js:72-85`）；未做真实调用 | 低（与本轮网关目标无关） |
| U6 | raccoon `credential.device_id` 的语义与是否每账号互异 | 未读 `raccoon-auth.ts` 全文，只确认字段存在（`raccoon.ts:105`） | 中：影响 10 §1.2 设备字段字典的完整性 |
| U7 | 各 provider 的**请求期轮换**是否覆盖全部 11 个 | 已确认 raccoon/loomy/zcode 的 adapter **不调用 `getAvailableAccount`**（grep 零命中），但未逐条读它们的 `resolveCredential` 失败重试逻辑 | 中：影响「哪些 provider 真能换号」的结论强度 |
| U8 | 客户端 UI 层（`plugin-src/client/jet-hub.js`，3000+ 行）的**一键签到页头、锁定按钮、新手任务按钮**渲染是否与后端能力矩阵一致 | 只读了 `PROVIDERS` 与 `credits-capabilities.js`，未读渲染逻辑 | 低（能力矩阵已声明「不一致会导致按钮出现但点了报错」的判据） |
| U9 | `README.md`（116KB）与 `AGENTS.md`（336KB）中的**用户报障原文与定案** | 按任务要求用 Grep 定位、未整读；本轮所有引用均来自 `src/` 与 `docs/` 的代码注释 | 低（注释里已含 issue 编号与用户原话，证据等级足够） |
| U10 | `lib/` 编译产物与 `src/` 的语义差异（02 U9） | 本机不存在 `lib/` | 低 |
| U11 | 是否存在「同一份 `data/` 被两条工作区/两个版本网关进程同时读写」的场景 | DSH 侧用户**刻意**把 desktop 与 web 分成两个互不影响的工作区（`permanent-lock-store.ts:20-22`），我们的实际情况未确认 | **高**：决定 B13（独立文档 + 镜像）是否必须做 |
| U12 | 「余额刷新」若改为后台任务，其频率/退避是否有上游限流风险 | DSH 用 60s TTL + 每轮 `Promise.all` 并发查；我们若 N 个账号 × M 个资源，规模可能大得多 | 中 |
| U13 | `qoder-machine.ts`（20KB）、`qoder-envelope.ts`、`zcode-captcha.ts` 等新模块的细节 | 本轮未读（属「模型输出面」与「客户端伪装」范畴，非账号管理核心） | 低（21 号文档覆盖） |

---

## 7. 零改动证明

**调研对象全程只读**：本轮对所有材料文件仅使用 Read / Grep / Glob / `awk` / `sed -n`（只读文本查看），**未写入、未运行其代码/测试、未发起任何网络请求**。

```
$ git -C "/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts" status --porcelain
（输出为空）

$ git -C "/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts" log --oneline -1
a3fe5f2 snapshot: 上游 gitee master f531c2984（2026-09-29，经 API 重建，逐文件 blob sha 校验一致）
```

**空输出 = 无任何文件被修改/新增/删除**（含未跟踪文件）。
`HEAD` 仍为 `a3fe5f2`（即本轮调研的基准快照），未做任何 checkout / reset / commit。

**本轮涉及的只读统计**：`src/` 共 90 个 `.ts` 文件、50193 行；本轮实际读取/检索的文件约 45 个（含 8 个 `*-product.ts`、`index.ts` 关键段、`account-pool.ts` 全文关键段、`expiry-sync.ts` / `permanent-lock-store.ts` / `jet-hub-store.ts` 全文、`credits-capabilities.js` 全文、`jet-hub-rpc.ts` 的 8 个关键段、7 个 `*-auth.ts`/`*-credits.ts` 的关键段、2 个 `*-balance-rank.ts`）。

**网关侧**：仅读取 `model_gateway/config/schemas.py`（`Resource` 定义段），**未改任何源码/测试/data，未触碰 127.0.0.1:8300**。

---

*文档结束。第 ③ 项用户点名用途（产品内部模型读出并对外输出）不在本文范围，见 `21-DSH插件-内部模型读取与输出面机制.md`。*
