# Batch B 代码取证：内部模型调用是否依赖厂商桌面端 · 多账号并行（App 依赖 · 代码专家 B）

> 角色 = 代码分析专家（只读 `coding/` 的 Python 源码 + 本地账号盘上形态取证）；纯调研，零文件修改、零真实上游调用。
> 判据口径：D0 无依赖 / D1 首登录依赖 / D2 运行期依赖（App 进程必须在跑）/ D3 离线产物依赖 / D4 未知或被风控拦。
> C0 可并行无干扰 / C1 需每账号设备身份唯一 / C2 单会话互踢 / C3 未知。
> 所有 `file:line` 为写作时实读行号；`data/upstream/...` 为盘上事实（只记字段名与时效语义，绝不回显凭据值）。

## 一、逐产品判定表

| 产品 | D 类 | App 依赖机制(一句话) | 鉴权材料形态 | 无头刷新可否 | 调用期还须构造什么 | C 类 | 多账号并行阻碍点 | 关键证据(file:line) | 置信度 | 否证条件 |
|---|---|---|---|---|---|---|---|---|---|---|
| trae | **D1** | 登录在浏览器授权页完成，凭据落 `credentials.json`；`127.0.0.1:18080` 是**网关自己**起的回跳接收端，不是 IDE 的端口 | `Authorization: Cloud-IDE-JWT <access_token>` + `X-Cloudide-Token`/`X-Ide-Token` 同值三发 | 可（`ExchangeToken` 纯 HTTP 轮换 refresh+access） | 静态 IDE 形态头（UA `Trae/0.1.52`、`X-App-Id`、`X-Ide-Version[-Code]`、`X-Device-Brand/Type/OS-Version`）+ `X-Uid`；私有 SSE 成帧（跨行 `event:`+多行 `data:` 拼接） | **C1** | 设备身份唯一性只在**登录/导入落盘时**校验，调用期无闸；两号的 `machine_id`/`device_id` 实测互异 | `upstream/trae/const.py:133-141`；`protocol.py:221-251`；`out.py:99-160`；`login.py:1-50,322-354`；`accounts/store.py:661-673` | D：高（代码面无进程依赖）／**调用是否被上游接受：未验证** | 若上游对 `X-Machine-Id`/`X-Device-Id` 做强校验（现导入号**不发**这两头，见 §2.1 缺口），或 IDE 版本准入再收紧 → 需回到 D3/D4 |
| cline | **D1** | WorkOS 设备码在浏览器点授权；之后纯 Bearer HTTP，无任何本机服务 | `Authorization: Bearer workos:<access_token>`（`workos:` 前缀不可剥） | 可（`POST {apiBase}/…/refresh`，实测在跑） | 4 个客户端标识头（`HTTP-Referer`/`X-Title`/`X-IS-MULTIROOT`/`X-CLIENT-TYPE`）+ `Accept: text/event-stream`；**非流式响应需解 `{success,data}` 信封** | **C0** | 无设备身份字段（`DeviceSpec(fields=())`）→ 唯一性闸天然不触发；当前仅 1 号 | `accounts/registry.py:166-179`；`upstream/cline/out.py:56-82`；`product.py:78-106,213-249`；`ops/builtin/auto_renew.py:46-49` | **高**（唯一有真实调用 200 + 无头续期盘上双证的产品） | 若上游按 `account_id` 限单会话并发 → 降 C2（代码面无法判定） |
| loomy | **D1** | 微信扫码 / 短信验证码在浏览器与手机端完成，凭据=登录 session | `Authorization: Bearer <session>` **且** 小写 `token: <session>` 两头并存 | **不可**（无 refresh 端点，恒 `NotRefreshable`） | 仅 `Accept: text/event-stream`；无设备字段、无签名、无 UA 伪装（讯飞 HMAC-SHA1 签名只用于**登录面** `account.xfinfr.com`） | **C0** | 无设备身份 → 本地不拦；同 session 并发语义代码面不可判 | `accounts/registry.py:184-200`；`upstream/loomy/out.py:51-69`；`login.py:79-90,448-463`；`sign.py:97-125`；`api.py:15-21` | **高**（依赖性质）／过期后果=确定事实 | 若讯飞侧对同 session 并发或 IP 绑定收紧 → C2 |
| raccoon | **D1** | 微信扫码 / 短信在浏览器与手机端完成，凭据=JWT | `Authorization: Bearer <access_token>` + `X-Org-Code`（个人号空串恒发） | 可（`POST /api/web/auth/v1/refresh` 真发 HTTP）；**但现盘上两号已 `terminal`（401/业务码 200003）→ 只能重新登录** | `X-Raccoon-Language`、`X-Client-Platform`（按本机平台映射 `desktop-macos`）；思考方言须翻译成 `extra_body.thinking.{type}` | **C1**（弱） | `device_id` 在 `DeviceSpec` 里 → 导入时要求跨号唯一（实测 2/2 互异）；**chat 头不发它**，业务头仅当值住在 `credentials.json` 才发 | `accounts/registry.py:205-223`；`upstream/raccoon/out.py:79-117`；`protocol.py:226-249`；`product.py:133-171`；`data/upstream/raccoon/accounts/*/runtime.json` | D：高；C：中（本地闸清楚，上游语义未知） | 若上游以 `device_id` 绑单会话 → C2；若 `desktop-*` 平台取值收紧 → 调用期需改常量 |
| zcode | **D4** | **代码里不存在任何"ZCode App 进程须在跑"的推理期依赖**（`kill_zcode`/`launch_command` 只被 `mgw zcode launch` CLI 调用）；直连不通的风险来自 WAF 指纹 + 验证码 + 一条**实现缺口**，不是 App | `Authorization: Bearer <zcodejwttoken>`（`enc:v1:` AES-256-GCM，**本地**口令可解）+ `X-Device-Mid` | **不可**（`refresh` 恒 `NotRefreshable`；过期只能重登/重导） | `anthropic-version: 2023-06-01`、`User-Agent: ZCode/3.11.2`、`X-Platform/X-Client-Language/X-Release-Channel`；可选 `x-aliyun-captcha-verify-*`；TLS 指纹伪装按配置 | **C1** | 推理链**当前根本打不出去**（三重：`CAPTCHA_PROVIDER=None` 使模型不进 `/v1/models`；`curl_cffi` 未装 + `fingerprint=false`；**导入号无顶层 `credentials.json` → `resolve_context()` 先抛"无凭据"**）；设备身份 16/16 互异，本地闸不是阻碍点 | `upstream/zcode/auth.py:1-21,53-71,80-104`；`out.py:70-137,28-44`；`product.py:157-191,377-389,651-663`；`dataroot.py:176-232`；`cli_zcode.py:108,120-122`；`adapters/product_out.py:91-110`；`upstream/zcode/store.py:197-236`；`main.py:239-275,412-417` | **中**（"不需要 App 进程"这条代码面可判；"需要些什么才打得通"= 未验证） | 若 D1 前提实测「直连恒被拒」→ 落 D3（需 App 的 TLS/设备产物或住宅代理）；若必须先跑一次客户端拿凭据 → 首登录仍 D1 |

## 二、逐产品证据链与推理

### 2.1 trae（Trae，`protocol=custom`）
1. **鉴权材料从哪读**：`out.py:119` → `ProductOutAdapter.resolve_context()`（`adapters/product_out.py:91-110`）→ `accounts/store.load_credentials(product, account_ref)` = 唯一入口 `data/upstream/trae/accounts/<名>/credentials.json`（盘上键：`access_token/refresh_token/expires_at/uid/nickname/enterprise_id/phone`）。调度侧传入的 `key` 对产品资源恒为空串并被显式丢弃（`out.py:166` `del key`）。
2. **除凭据外构造什么**：`protocol.solo_headers`（`protocol.py:221-251`）——`Cloud-IDE-JWT` + 另两个同值 token 头（注释取证「缺任一都可能被上游拒绝」），`X-Uid`，其余是**仓内硬编码常量**（`const.py:70-95`：`APP_ID`/`IDE_VERSION=0.1.52`/`IDE_VERSION_CODE`/`DEVICE_BRAND`/`OS_VERSION`/`SOLO_FIXED_HEADERS`）；`Request-Traffic-Type: prod`。体 = `protocol.solo_body`，`stream` 被**强制改 true**（`out.py` 模块头表 + `const.py:66` 默认通道 `solo_work_lite`）。响应是私有成帧：`event:` 行 + 跨行拼接的 `data:`（`out.py:134-144`），0 事件按可重试错误而非空回复（`out.py:151-154`）。
3. **有没有假设 App 进程**：无。`grep` 全 `upstream/` 的 `127.0.0.1|localhost|subprocess|pgrep|/Applications` —— trae 命中项**全部是登录回跳**（`login.py:5-23`、`protocol.py:298-309,412-427`、`const.py:133-141`）。`CALLBACK_PORT=18080` 是 `accounts/callback_server.py` 的**首选端口**（占用即回退随机端口并用实际端口重建授权 URL），由网关持有，与 IDE 无关。
4. **token 生命周期**：`refresh` 真发 HTTP 到 `OAUTH_HOST + /oauth/ExchangeToken`（`product.py:99-107`、`login.py:360-399`、`const.py:48`），401/403 或 2xx 无 token → `NotRefreshable`；设备字段**一律不改写**（`login.py:376`）。盘上 `expires_at` 为毫秒，两号约 2026-10-13/14 到期。`auto_renew` 定时腿只跑 `capabilities.refresh=True` 的产品（`ops/builtin/auto_renew.py:145-150`），trae 在列。
5. **⚠️ 代码级缺口（必须报备）**：`solo_headers` 的 `X-Machine-Id`/`X-Device-Id` 只从**凭据本体**取（`protocol.py:245-250`），而 `login.py:332-344` 登录路径把设备字段**同时**写进 credentials 与 meta；公共层**导入**路径按 §22.3 把身份字段**只**落 `meta.json`（`accounts/store.py:661-673`）。盘上 2/2 号 `via='import'` → 实测构造出的 SOLO 头**不含 `X-Machine-Id`/`X-Device-Id`**（本地离线跑 `TraeOut._solo_headers()` 复现）。且 `out.py:119` 拿到 `_meta/_device` 后丢弃，无从补齐。另：盘上 `device_id` 是 32 hex 而非 `derive_device_id15` 的 15 位数字形态（`login.py:322`），两条写入路径形态不一致。
6. **判定**：D1 + C1。签到幂等只能靠 status 端点（`registry.py:49-56` `PRE_CHECK_PRODUCTS={"trae":True}`）与 App 无关。

### 2.2 cline（Cline，`protocol=openai`）
1. 鉴权：`out.py:56-68` → `protocol.auth_headers`（`Bearer workos:<access_token>`，前缀幂等补齐；剥掉即 401 且报错文案误导，`product.py:19-21`）。盘上凭据键 `access_token/refresh_token/expire_time/account_id/email/nickname`，`credexp.py:14,33` 认 `expire_time` 并回退 JWT `exp`。
2. 额外构造：4 个客户端标识头 + `Accept: text/event-stream`；**推理体零私有塑形**（10 产品里唯一）。响应差异：非流式实测套 `{success,data}` 信封 → `_shape_response` 退壳（`out.py:72-82`，仅"顶层无 `choices` 且内层有"时），流式无信封。403 是地域/未开通而非凭据问题，交给既有分类器 `BAD_REQUEST`（`out.py:26-31`）。
3. App 假设：**grep 零命中**。登录 = WorkOS 设备码（`product.py:78-106`），`authorization_pending` 判据在响应体不在状态码（`product.py:15-18`）。
4. 刷新：`product.py:213-249` 真发 `POST REFRESH_PATH`。**盘上实证无头续期成功**：`data/upstream/cline/accounts/cline-8881b795/runtime.json` 的 `renew={attempted_at:"2026-10-02T13:11:19", terminal:"", last_error:""}`，且 `expire_time` 恰好 = `attempted_at + 1h`；`auto_renew.py:46-49` 记的「cline 令牌寿命 ~1h < 2h 窗口 → 加 30min 冷却」正是这台真机观察。额度 `runtime.json` `quota.state=available, source=cline-balance`。
5. 判定：D0 与 D1 的分界在「首登录需不需要人」——需要（浏览器点设备码），故 **D1**；**C0**（`DeviceSpec(fields=())`，`registry.py:175`）。唯一已进入映射并真实调用 200 的 Batch B 产品（`data/config.yaml` 中 10 条池项引用 `res-231de13a`）。

### 2.3 loomy（Loomy/讯飞，`protocol=openai`，不可续期）
1. 鉴权：`out.py:51-69` **两个头并存**（`Bearer` 供 `/chat/completions`，小写 `token` 供 `/models`、`/points/*`、`/onboarding/*`；实测带错 → `200 + code 100002 缺少 token`，`out.py:9`）。凭据键 `access_token/userid/phone/nickname/expires_at`。
2. 额外构造：**没有**。无设备字段、无签名、无 UA 伪装。`sign.py` 的讯飞 HMAC-SHA1（`account {ak}:{sig}`）只用于**账号宿主** `ACCOUNT_BASE`（`constants.py:13`），唯一调用点 `login.py:342` → 属登录面，不在推理面。
3. App 假设：grep 零命中；`login.py` 走微信扫码（`wechat.py` 取微信那张 JPEG 由网关自己带 UA/Referer 回捞，`product.py:23-29`）与短信两段（`_ALT_HOOKS`，`product.py:93-100`）。
4. 过期后果（确定事实）：`login.py:79-90` 恒 `NotRefreshable`（"refreshAll 只探测已过期账号"）；`expires_at` 是**本地按 14 天推算**的毫秒串（`login.py:448-463`，服务端只接受 `expire` 参数、不回到期时间）→ 真过期只能重扫码/重发短信。运行期表现为 401 → `ErrorClass.AUTH` → `resources.disable()`（`core/scheduler.py:408-411,683-686`）→ 该资源进 `disabled`，`servable_models` 据此不再对外声明（`core/resources.py:312-315`）；`auto_renew` 因能力位 `refresh=False` 直接跳过（`auto_renew.py:149`）。
5. 判定：**D1 + C0**。

### 2.4 raccoon（Raccoon 小浣熊，`protocol=openai`）
1. 鉴权：`out.py:79-98` = `Bearer <access_token>` + `X-Org-Code`（个人号恒发空串）+ `X-Raccoon-Language: zh` + `X-Client-Platform` + `Accept`。凭据键 `access_token/refresh_token/expires_at/user_id/nickname/phone`；`expires_at` 由 JWT `exp` 推算落盘（`credexp.py:13`）。
2. 额外构造：`X-Client-Platform` 按**本机平台**如实映射 `desktop-macos`（`const.client_platform()`，`out.py:46-49`）——注意这是"伪装成桌面端形态"的**字符串常量**，不是 App 进程；**chat 头集刻意不套业务端点形状**（`out.py:40-44`，DSH chat 硬编码四头），`X-Client-Device-ID` 因此不在推理面出现。体差异：把 IR 注入的顶层 `thinking`/`reasoning_effort` 翻译成唯一有效通道 `extra_body.thinking.{type}` 并**删掉原字段**（`out.py:100-117`，实测表 `out.py:17-23`：`reasoning_effort` 被接受但无效果、顶层 `thinking` 被忽略）。
3. App 假设：grep 零命中。登录 = 微信扫码页（`const.py:67-69`）/ 短信；每日 300 分服务端自动发放 → 能力位 `checkin=False`（`registry.py:203-204,220`）。
4. 刷新：`product.py:133-171` 真发 `POST /api/web/auth/v1/refresh`；401 或业务码 `200003` → `NotRefreshable`。**盘上现状 = 终态**：两号 `runtime.json` `renew.terminal="Raccoon 登录态已过期（refresh_token 失效，HTTP 401／业务码 200003），请重新登录"`（attempted 2026-10-01T23:01:18），而 `quota.state=unknown, source=raccoon-points`。→ 结论：**续期能力存在且无头，但 refresh_token 本身会死**；死因（轮换被别处消费 / TTL / 单会话）代码面不可判。
5. 判定：**D1 + C1**（`DeviceSpec(fields=("device_id",))`，`registry.py:219`；盘上 2/2 互异，实测构造的 chat 头不带它 → 该唯一性只是**本地导入闸**）。

### 2.5 zcode（ZCode/z.ai，`protocol=anthropic`，D1 前提未定论）
**（a）推理链路是什么**：`registry.py:229-240` 出站基址 = Plan/JWT 通道的 anthropic 基址 `https://zcode.z.ai/api/v1/zcode-plan/anthropic`；实际 URL 由 `AnthropicOutAdapter._url()` 拼 `{base}/v1/messages`（`adapters/anthropic_out.py:496-504`）。鉴权头**统一**走 `auth.build_headers("jwt", …)`（`out.py:127`）→ `Authorization: Bearer <zcodejwttoken>` + `X-Device-Mid`（缺 mid → 额度/权益类端点 `400/3001`，`auth.py:68-69`）+ `X-Platform/X-Client-Language/X-Release-Channel` + `User-Agent: ZCode/<app_version>`；本层再补 `anthropic-version: 2023-06-01`（`out.py:129-132`）。**API Key 通道（`x-api-key` + `api.z.ai/api/anthropic`）在 `auth.py` 有构造器但未接进出站**（`auth.py:5-8`；`ZcodeOut._headers` 恒 `"jwt"`），故 `auth.py:74-77` 宣称的"两个资源表达降级链"目前只有 Plan/JWT 一条腿（盘上 16 条资源 `protocol` 全 `anthropic`、基址同一个）。

**（b）`dataroot.py` 的 App 操作属于哪条路径（本案最易混点）**：`is_zcode_running/kill_zcode/launch_command/build_env/build_args`（`dataroot.py:88-103,176-232`）的**唯一调用方是 `cli_zcode.py:108,120-122`**（`mgw zcode launch`），`api/admin_zcode.py` 零引用、推理链（`out.py`/`anthropic_out`）零引用。`dataroot.py:1-30` 的整根隔离（四个 `ZCODE_DESKTOP_*` 环境变量 + `--device-id=`）服务的是"**启动官方客户端做账号切换/倒库**"，与"网关转发一次 chat"是两条路。⇒ **不得**把 `kill_zcode` 读成"推理前要先杀/先起 App"。同理 `telemetry-state.json` 的 `deviceMid` 同步（`dataroot.py:159-171`，调用点 `product.py:317`、`store.py:217`、`cli_zcode.py:302`）是**落盘面**。

**（c）凭据读取（含"离线产物"性质判定）**：`product.py:157-191` `_resolved_credentials`/`outbound_credentials` 双处落盘合并 —— ① 顶层 `credentials.json` ② 账号私有客户端数据根 `<账号>/data/.zcode/v2/credentials.json`，后者值多为 `enc:v1:`（`crypto.py:1-19,95-120`：AES-256-GCM，`key=SHA256(secret)`，secret = `ZCODE_CREDENTIAL_SECRET` 或 `zcode-credential-fallback:{platform}:{home}:{username}`）。**解密不可以需要 App 进程**：纯本地口令派生。盘上实测 15/16 号为 `enc:v1:`、16/16 可解出三段点分 JWT（`oauth.py:71-89` 读取时解密）。⇒ 对**导入路径**这才是 D3（要拿到 App 数据目录里的密文产物）；对**推理路径**只是本地文件解密。

**（d）405/3012 与 fail-closed 在代码里怎么落**：
- `out.py:35-44`（F-4）明确登记：转发路径遇 3012 **无护栏**——全仓 `circuit.enter()` 唯一调用点在领取路径；分类按 HTTP 状态走，4xx 落 `BAD_REQUEST` 原样透传、不计 C 不冷却。DSH 侧记有账号惩罚梯度（3 次/24h→24h、5 次停用）。
- 装配侧把"前提未注入"变成**不对外声明**：`main.py:239-275` `_outbound_premise_gap()` 判 `zcode_out.CAPTCHA_PROVIDER is None → "zcode 验证码未注入"`，经 `Runtime._unservable_reason`（`main.py:501-511`）注入 `ResourceManager.unservable_reason`（`core/resources.py:252-271,344-353`），`servable_models` 据此把映射剔出 `/v1/models` 与 `mgw setup`（`core/resources.py:291-318`）。分层纪律：`core/` 不 import `upstream/`，判据本体住在装配侧（`main.py:242-247`）。
- 验证码是**注入缝**而非硬接：`out.py:70-83` `CAPTCHA_PROVIDER`（`ContextVar` 每请求一次，避免一次性 param 复用 → 3007）；`out.py:14-27` 说明为什么不接 `captcha.py`（45s 缓存 + 宽限期刷新的 solver 会把转发路径变成 DSH 记录过的 3007 缺陷形态）。生产默认 `None` = §17 降级链第二步"JWT 直连"。`out.py:139-167` 的 F-3 契约：provider 任何异常必须包成 `UpstreamError`，否则冒穿成 500。
- 探活/额度通道共用熔断与 10s 节流（`product.py:411-440`）：`circuit.active()` → **未发起**；`quota.py:279-291` 记「联网腿 `billing/balance` 实测 16/16 号 200/code=0」，并**证伪**了旧注释"PoW 私钥握手脚本无法复刻"。
- 环境事实（本机实查）：`data/config.yaml` `gateway.zcode.fingerprint = false`；`.venv` **未安装 `curl_cffi`**（`auth.py:80-104` 会静默降级 httpx，`main.py:412-417` 只在开了开关时告警）。`auth.py:14-16`：`zcode.z.ai` 前置 ESA WAF，普通 ClientHello 易被判机器程序。

**（e）🔴 代码级阻断（本轮新发现，与 App 无关但决定 D 判定的可用性）**：`ZcodeOut._headers`（`out.py:121`）**先**调 `resolve_context()`，而 `product_out.py:104-108` 在顶层 `credentials.json` 缺失/空时直接抛 `UpstreamError("…无凭据（未登录或凭据文件缺失）…资源已物化、凭据未落盘")`；盘上 **16/16 号 `via='import'` 且 0/16 有顶层 `credentials.json`**（私有导入 `upstream/zcode/store.py:197-236` 只写 `meta.json` + `data/.zcode/v2/*`，不写公共层凭据），离线实跑 `build_out(...)._headers("")` 已复现该抛错。→ 设计用来兜底的 `outbound_credentials` **永远轮不到执行**。测试盲区：`tests/integration/test_zcode_out.py` 用 tmp 目录造顶层凭据，故全绿。当前用户不可见，只因 (d) 的 `CAPTCHA_PROVIDER` 闸先把模型藏了——**解除 D1 前提后这条会立刻变成 100% 503**。

**（f）判定**：推理链的 App 依赖 = **代码面判为 D1（首登录浏览器设备流，`oauth.py:107-117` + `registry.py:225-228`）+ 无运行期进程依赖**；但"能不能真打通"= **D4**（405/3012 未裁决 + 指纹关闭/依赖缺失 + 验证码未注入 + (e) 的阻断）。C 类 = **C1**（`X-Device-Mid` 必带；`device.py:63-92` 导入要求跨号唯一，盘上 16/16 互异 → 本地闸不阻碍并行）。

## 三、公共层与调度层：多账号并行到底靠什么保证

1. **N 账号 = N 资源**：`config/resources` 实测 trae 2、cline 1、loomy 2、raccoon 2、zcode 16，`account_ref` 去重数与号数相等，`api_key` 全为空串（凭据不进 config，铁律 1 / `product_out.py:11-14`）。物化由 `accounts/materialize.py::ensure_resource` 负责，zcode 私有导入路径也补了 `_materialize_best_effort`（`upstream/zcode/store.py:229-247`）。
2. **同一系统模型可挂同产品多条资源**：池键 = `(resource_id, vendor_model)`（`core/resources.py:113-134,417-427`），同产品多号在同一个 `models[].resources[]` 里就是并列条目；`pick_and_acquire` 在**同一同步段**做在途 +1 与额度预留（`:467-499`，`in_flight` 最少者承接，平局按优先序），生效集 = 可用候选的 top-`x`（`x=max_active_per_model`，当前实跑 `x=2`）。`max_concurrent_requests=0` = 不限总并发。
3. **调用期没有任何"每账号/每产品串行"锁**：全仓 `Lock/Semaphore` 命中只有 ①账号盘写锁 `accounts/store.py:230,439,555,692,740`（`_WRITE_LOCK` 只护落盘；`write_runtime` 显式不取锁 `:524-529`）②`materialize` 顺序锁 ③热重载锁 ④`zcode/captcha.py:115` 求解串行（**不在推理路径**）。适配器 `chat_*` 全程零锁 ⇒ 同产品多号并行无代码级互斥。
4. **设备唯一性只拦"第二个账号的落盘"，不拦"第二个账号的调用"**：`accounts/device.py:63-92`（任一身份字段相同即冲突）被 `store.import_account`（`:661-673`，查重与落盘同临界区）与 zcode 登录/导入（`product.py:335-350`、`upstream/zcode/store.py:164-188`）调用；生成新号冲突→重生成（有上限），导入冲突→拒绝交用户决策（`reuse`/`regenerate`）。实测 Batch B 全部身份字段跨号互异（trae 2/2、raccoon 2/2、zcode 16/16）→ **不会拦下并行**。
5. **故障切换不会把多号当一号**：401/403 → `disable`、404 → `invalidate`、429/5xx → `cooldown`（`core/scheduler.py:408-416,683-691`），状态住在 per-`(rid, model)` 的 `ResourceState`；`access_mode=plan` 用更长冷却（`resources.py:619`，配置 `cooldown_seconds_plan=18000`）。适配器复用判据含 `product+account_ref+凭据短哈希`（`main.py:513-519`）→ 换号/重登必重建，不串凭据。
6. **zcode 的全局熔断是唯一"跨号"闸门**：`quota.py:745+` `Circuit.enter()`（30min）+ `resources.py:330-334,480-487` 的**读时重判**（`circuit_active` 由装配侧注入，`main.py:341-359`）——命中 3012 后 Batch B 里只有 zcode 会**整产品同时按住**，这是 zcode 特有的"并行被连坐"点，不是设备唯一性。

## 四、凭据落盘字段与时效语义（问题 7，只记字段名）

| 产品 | `credentials.json` 键 | 时效键与语义 | 私有文件 |
|---|---|---|---|
| trae | `access_token` `refresh_token` `uid` `nickname` `phone` `enterprise_id` `expires_at` | `expires_at`=**毫秒**（盘上 2026-10-13/14）；`credexp.py:9` 认此键 | 无；`meta.json` 载 `machine_id`/`device_id` |
| cline | `access_token`(带 `workos:` 前缀) `refresh_token` `account_id` `email` `nickname` `expire_time` | `expire_time`=毫秒，**实测寿命 ~1h**（`auto_renew.py:46-49` + 盘上 `attempted_at`+1h） | 无 |
| loomy | `access_token`(讯飞 32-hex session) `userid` `phone` `nickname` `expires_at` | `expires_at`=**本地按 `SESSION_TTL_S`=1209600 推算的毫秒串**，服务端不回到期值（`login.py:448-463`） | 无 |
| raccoon | `access_token` `refresh_token` `user_id` `nickname` `phone` `expires_at` | `expires_at` 由 JWT `exp` 推算落盘（`credexp.py:13`）；盘上已过期 + `renew.terminal` | 无；`meta.json` 载 `device_id`（业务头只在凭据里有值才发） |
| zcode | **0/16 有顶层 `credentials.json`**（导入路径不写） | 无 → `credexp` 解析不到 ⇒ 界面倒计时"未知"，`auto_renew` 记 `skipped:"no-expiry"` | `data/.zcode/v2/{credentials,config,telemetry-state}.json`：`zcodejwttoken`（`enc:v1:` AES-256-GCM，15/16 密文）、`oauth:active_provider`、`oauth:<p>:access_token`、`account-provider:coding-plan:…:api-key`（多条）、`web-remote-control:external-relay:pass_hash` |

## 五、最可能与其他角色分歧的地方
1. **zcode 的 D 类归属**：本角色判「代码面无 App 进程依赖，D4 来自风控/接线而非 D2/D3」。材料侧若把 `dataroot.py` 的 `kill_zcode`/整根隔离当成推理期依赖，会判成 D2/D3 —— 请对方指具体调用点（本角色查得调用面只有 `cli_zcode.py`，见 §2.5(b)）。
2. **zcode 的真实阻断点是"实现缺口"而不是"直连被拒"**：§2.5(e) 的 `resolve_context()` 先抛无凭据，是**代码可判定**的既成事实；若其他角色把 zcode 不可用全归因 D1 前提，会漏掉这条。修法方向（供裁决，本轮不实施）：`ZcodeOut._headers` 改为不依赖顶层凭据、或导入路径补写公共层 `credentials.json`。
3. **trae 是否"已可用"**：本角色只证明"无 App 依赖 + 头/体能构造出来"，**未**证明上游接受；且 §2.1(5) 的设备头缺失（导入号）很可能被上游风控判异常。材料侧若据 DSH 参考实现宣称 trae 转发可用，需先看这条读侧不对称。
4. **loomy 的 `sign.py` 会不会被算成 D3（需要客户端签名产物）**：本角色判不会——签名用于**账号宿主登录面**（`login.py:342` 唯一调用点），`ak/sk` 是仓内常量（`constants.py`），推理面 `out.py` 一个签名都不算。
5. **raccoon 的 `X-Client-Platform: desktop-macos`**：会被读成"依赖桌面端"。它是按本机 OS 生成的**字面量伪装**（`out.py:46-49`），与 App 进程无关；但它是**准入条件**性质的常量，取值错了会被 `login/points/grant` 拒。
6. **C1 与 C0 的边界（raccoon）**：`DeviceSpec` 声明了 `device_id` 却被 chat 头忽略 → 本角色判 C1(弱)。若以"上游看不到该字段"为准，raccoon 更近 C0。

## 六、本角色无法定论、必须实测的地方
1. **zcode 推理链 D1 前提（最高优先）**：`POST {plan}/v1/messages` 用 `Bearer zcodejwttoken + X-Device-Mid + anthropic-version`（无验证码头）是否被 WAF/风控接受（200 / 405 / 3012 / 3007）；以及 `curl_cffi`（**当前未安装**）+ `fingerprint=true` + 住宅代理 + 每请求新鲜 captcha 四件齐备后才成立的假设。须先修 §2.5(e) 才能测到真链路。
2. **zcode API Key 备选通道**：`x-api-key` + `api.z.ai/api/anthropic` 是否可用、是否真能绕开 3012 —— 代码里**未接线**（`auth.py:5-8` 只有构造器），完全待实测。
3. **各产品同账号并发语义（C0 vs C2）**：loomy 单 session 并发、cline 单 `account_id` 并发、raccoon JWT 会话是否互踢 —— 代码里既无锁也无上游证据。特别地 **raccoon `refresh_token` 为何死**（401/200003：被别处轮换消费？TTL？单会话顶号？）必须实测，它直接决定 raccoon 是 D1 还是 D2。
4. **trae 上游对 SOLO 头的最低要求**：缺 `X-Machine-Id`/`X-Device-Id` 是否仍 200；`IDE_VERSION=0.1.52` 准入是否已被抬（`4001`）。
5. **trae `device_id` 形态**：15 位数字派生（`login.py:322`）vs 盘上 32 hex，上游签到/风控接受哪一种，需真实号实测。
6. **loomy/zcode 过期后果的界面可见性**：`credential_expiry_ms` 对 zcode 取不到值（无顶层凭据）→ 是否会在过期前给出预警，属实测项。
7. **`stream:false` 面**：loomy 与 raccoon 上游是否接受非流式**未取证**（两文件模块头各记一条 M6-5b 待实测项），trae 侧只能本地聚合。
