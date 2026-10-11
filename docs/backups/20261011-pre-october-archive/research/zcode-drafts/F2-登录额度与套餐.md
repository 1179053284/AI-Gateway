# F2 · ZCode-Panel 登录驱动 / OAuth / 额度与套餐读取

> 调研对象：`/Users/w/Desktop/zcode相关管理软件/ZCode-Panel/`（**全程只读**）
> 证据分级：【一手】= 直接读到的代码；【推断】= 未经代码证实；【未验证】= 卡住未证实。
> 所有行号均以当前工作副本为准，已用 Read 逐条核对。
> **重要更正（与任务描述的框架不一致）**：`balance.js` **不是**日志通道，它走的是联网（BigModel biz 网关）；**真正读日志的是 `plan.js`**。README:222 把 `balance.js` 标为「客户端日志里的额度读取」属文档笔误，以代码为准。

## 修订记录（据独立核验 `_verify/verify-F.md` 逐条修正）

| 原表述 | 修正后 | 类型 |
|---|---|---|
| 「接码关键词**项目源码 0 命中**」 | **不成立** —— `renderer/style.css:123` 命中注释 `/* ===== 自动接码开关 ===== */`（**死代码**，`index.html` 无 `class="switch"` 元素）。**"无内置接码能力"的结论仍成立**，但"0 命中"表述错误 | 负向断言检索范围不足 |
| 「`completeOAuth` 加密写盘（main.js:1571-1584）」 | 1571-1584 位于 **`applyOAuthToken`**；`completeOAuth` 定义在 `main.js:2138`，是**调用方** | 函数名张冠李戴 |
| §①「双重闸门」只给一处引用 | 补第二道（UI）闸门 `renderer/index.html:67`（`btn--dead` + `已失效` 徽标） | 引用不全 |
| 「4MB」 | `4 * 1024 * 1024` = **4 MiB**（4,194,304 B），非 4 MB | 单位口径 |

---

## ① 结论先行

- **额度读取确实是双通道，但分工与任务描述相反**：日志通道 = `plan.js`（读 `billing/balance` 客户端日志，最准，主用）；联网通道 = `remote-plan.js` + `account-query.js`（打 `zcode.z.ai/api/v1/zcode-plan/billing/balance`，需 JWT + device_mid，用户主动触发）；另有一条**独立的余额通道** `balance.js`（BigModel `open.bigmodel.cn` biz 网关，取余额/资源包/订阅，与额度桶无关）。【一手】
- **主用日志的理由是硬的**：zcode 侧 `billing/*` 对非客户端进程返回 3012，客户端请求带 `X-Client-Sig/X-Client-Nonce/X-Client-Pow` 私钥握手 + PoW 签名，脚本无法复刻（balance.js:6-14）；联网结果还会缺 `balances`、只剩 `grant_units`，看着像满额未用（main.js:2531-2537）。【一手】
- **3012 = 服务端风控「unusual activity」**，一旦命中立即全局熔断 30 分钟，期间不发任何请求，状态落盘防重启丢失（remote-plan.js:36-48、103、163-165）。【一手】
- **OAuth 是标准 Authorization Code + `zcode://oauth/callback` 自定义协议**，凭据用 **AES-256-GCM**（`enc:v1:` 前缀），密钥由 `ZCODE_CREDENTIAL_SECRET` 或机器特征派生——**与 ZCode 客户端自己的 `enc:v1` 是同一套算法与键名**（oauth.js:243-278、main.js:1571-1584）。【一手】
- **登录驱动是「人机混合」**：手机号/验证码/人机验证全人工，驱动只自动点「登录/注册」和授权页「继续」；提交判据是「两个输入框都有有效值 + 验证码变过 + 间隔节流」，**明确不拿按钮可点当信号**（login-driver.js:262-272、353-371）。【一手】
- **Z.ai 邮箱注册通道关闭有双重闸门**：① 主进程 `startOAuthFlow` 里 `providerId==='zai'` 直接 return（`main.js:1946-1953`）；② 渲染层按钮本身标记为失效（`renderer/index.html:67`，`class="btn--dead"` + `已失效` 徽标）。`ZaiMailDriver` 代码保留待复活。【一手】

---

## ② 额度双通道（日志 vs 联网）

### 日志通道（`plan.js`，主用）
- **读哪个文件**：`<logDir>/YYYY-MM-DD.log`，默认 `~/.zcode/v2/logs`；只扫最近 3 天（`recentLogFiles` plan.js:40-51）。新架构下每个账号有独立 `logDir`（`<账号>/data/.zcode/v2/logs`），由调用方传入（plan.js:32-35、293-294；main.js:2558）。【一手】
- **怎么解析**：只读文件尾 `TAIL_BYTES = 4 * 1024 * 1024` = **4 MiB**（plan.js:37、54-65）；定位标记 `MARKER = 'billing/balance 请求完成 '`（plan.js:36）；从标记后的 `{` 起用**括号配对**（含字符串/转义处理）抠出完整 JSON（`extractJson` plan.js:71-88），避免 payload 里带引号文案把配对判错。最多回看 80 条（plan.js:124）。【一手】
- **日志里 `billing/balance` 记录长什么样**：结构为 `{providerId, ts, payload:{code,msg,data:{plans:[...],balances:[...],server_time}}}`。`plans[]` 每项含 `plan_id/user_plan_id/name/description/status/starts_at/ends_at/entitlements[]`；`entitlements[]` 含 `entitlement_id/show_name/meter/grant_units/period/effective_at`；`balances[]` 含 `user_plan_id/entitlement_id/total_units/used_units/available_units/period/show_name`（plan.js:91-95、218-255；account-query.js:101-138 同源结构）。【一手】
- **为什么优先走日志**：(1) 日志是客户端拿到手的第一手响应，最准（plan.js:6-10）；(2) 联网那条要 `X-Device-Mid` 等一串客户端头，缺一个就 400/3001（plan.js:8-10、remote-plan.js:10-15）；(3) 联网实测会缺 `balances`，只剩 `grant_units`（main.js:2531-2537）。【一手】
- **串号防护**：日志是全局的（老架构），故支持按 `expectUserPlanId` 精确匹配；指定了却匹配不上则返回 null，让调用方退回该账号自己的旧快照，**绝不把别人的额度顶上来**（plan.js:97-107、132-141；main.js:2557-2568）。【一手】

### 联网通道（`remote-plan.js`，用户主动触发）
- **端点**：`GET https://zcode.z.ai/api/v1/zcode-plan/billing/balance?app_version=3.11.2`（remote-plan.js:24、27、142）。【一手】
- **鉴权头**：`Authorization: Bearer <zcodejwttoken>`（**必需**，错 token 401）+ `X-Device-Mid: <该账号 device_mid>`（**必需**，缺则 400 code=3001 parameter error）；另带 `X-ZCode-App-Version/X-Platform/X-Client-Language/X-Client-Timezone/X-Os-Category/User-Agent/Origin/Referer`（remote-plan.js:143-157）。【一手】
- **另有一个独立余额通道** `balance.js`：端点 `open.bigmodel.cn` 的 `/api/biz/account/query-customer-account-report`（账户余额）、`/api/biz/tokenAccounts/list/my`（资源包）、`/api/biz/subscription/list`（Coding Plan 订阅）；鉴权头 `authorization: Bearer <oauth access_token>` + `user-agent: ZCode/3.0.1` + `X-Client-Version/X-App-Id`（balance.js:118-141、156-160）。token 来源：解密 `credentials.json` 的 `oauth:<provider>:access_token`，按 `oauth:active_provider` 选 provider（balance.js:50-62）。**注意**：这是余额/资源包，不是 `billing/balance` 的额度桶，两条路数据不重叠。【一手】

### 优先级与降级关系
- **主界面额度（`plans:quota`，main.js:2527-2578）**：以日志为准 → 日志无该账号记录时，退回**该账号自己的旧快照**并标 `stale`（`snapshotToPlanData` main.js:515-585、2562-2568）→ 读到就写快照（main.js:2572-2575）。**不退回「最后一条」全局日志**（main.js:2560-2561）。【一手】
- **联网套餐是独立入口**：`fetchRemotePlanForAccount`（main.js:616-650）由用户主动触发，成功则把结果经 `normalizeRemote` 归一化后写成快照（main.js:634-648）；`normalizeRemote` 把服务端响应**包成日志记录的形状**，复用同一套 `normalize`（plan.js:309-320）。【一手】
- **`balance.js` 有 60s 内存缓存**（`CACHE_TTL_MS` balance.js:28、144-146）。【一手】

---

## ③ 节流与 3012 熔断（`remote-plan.js`）

- **节流**：全局 `MIN_GAP_MS = 10000`（10s），`throttle()` 保证两次调用间隔不小于 10s（remote-plan.js:33、88-92）；请求超时 `REQUEST_TIMEOUT_MS = 12000`（remote-plan.js:34、97）。【一手】
- **3012 是什么**：服务端判定「异常活动 / unusual activity」的业务 code。`call()` 里 `body.code === 3012` 即触发 `enterCooldown`（remote-plan.js:103）；`fetchPlanByJwt` 再兜一层返回 `reason:'rate-limited'`（remote-plan.js:163-165）。account-query.js:98 同样把 3012 单列。注释另记 `billing/current` 已被风控，**无论怎么请求都 405 code=3012**，已弃用（remote-plan.js:14-15）。【一手】
- **熔断阈值 / 恢复时间**：`COOLDOWN_MS = 30 * 60 * 1000`（30 分钟）；`enterCooldown` 写 `cooldownUntil = now + 30min`；`fetchPlanByJwt` 入口先查 `cooldownLeftMs()`，>0 直接返回 `reason:'cooldown'` 不发请求（remote-plan.js:38、79-81、126-133）。成功一次即 `clearCooldown()`（remote-plan.js:169）。【一手】
- **状态落盘**：`STATE_FILE = .remote-plan-state.json`，**必须写可写位置**——打包后 `__dirname` 在只读的 `app.asar` 里会导致熔断状态永远存不下来、重启即丢（remote-plan.js:40-48、63-71）。读时去 BOM（remote-plan.js:56）。【一手】

---

## ④ 套餐解析（`plan.js`）

- **归一化输出字段**（`normalize` plan.js:207-284）：计划级 `planId / userPlanId / name / description / status / startsAt / endsAt / entitlements[] / buckets[] / pending / expired`；权益级 `entitlementId / showName / meter / grantUnits / period / effectiveAt / pending`；桶级 `showName / period / totalUnits / usedUnits / availableUnits`（plan.js:218-255、186-198）。【一手】
- **`tier`（Max/Pro/Lite/Start）判定：代码里没有 `tier` 字段，也没有 Max/Pro/Lite 的分级逻辑**。检索了 `plan.js`、`balance.js`、`remote-plan.js`、`account-query.js`、`main.js` 全文关键词 `tier`（0 命中）、`Max|Pro|Lite`（0 命中）。套餐只按服务端返回的 `name`（如 `ZCode Start Plan`、`ZCode Global Build`）区分；`account-query.js:107` 用 `/ZCode Start Plan/i` 正则把基础套餐从「券」里剔除。所谓档位完全由服务端 `name` 字符串承载，面板不做映射。【一手 + 检索说明】
- **额度换算**：无单位换算（不做 token↔金额）。只有一处兜底算术：`availableUnits` 缺省时退回 `max(0, total - used)`，**绝不拿总量当可用**（plan.js:186-197；account-query.js:131-133 同）。【一手】
- **时间处理**：接口给秒，`toIso` 转本地 ISO 字符串，**不能透传**否则渲染层当毫秒显示成 1970（plan.js:173-180、237-240）。平台时间按 UTC+8 解析（balance.js:73-88）。【一手】
- **pending / expired**：`pending` = entitlement `effective_at` 在未来（活动券提前发放但未生效，plan.js:200-205、228）；`expired` 按读取时刻重算（plan.js:263-264）。计划级 `pending` = 所有权益都待生效（plan.js:262）。展示排序：常规套餐在前、`one_time` 赠送在后（plan.js:267-269）。【一手】

---

## ⑤ OAuth 与凭据加解密（`oauth.js`）

- **两条 provider**（PROVIDERS oauth.js:40-62）：
  - `bigmodel`：authorizeUrl `https://bigmodel.cn/login`，appId `zcode`，paramStyle `redirect-appId`（参数 `redirect`+`appId`+`state`）。
  - `zai`：authorizeUrl `https://chat.z.ai/api/oauth/authorize`，client_id `client_P8X5CMWmlaRO9gyO-KSqtg`，paramStyle `oauth2`（`redirect_uri`+`response_type=code`+`client_id`+`state`）。
  - 两者 tokenUrl 同为 `https://zcode.z.ai/api/v1/oauth/token`，redirectUri 同为 `zcode://oauth/callback`（DESKTOP_REDIRECT oauth.js:38）。【一手】
- **回调方式**：桌面端生产环境用 https 桥接页 `https://zcode.z.ai/app/oauth/login?redirect=zcode://oauth/callback&app_version=<ver>`，授权完成后桥接页转交 `zcode://` 自定义协议；`mode='direct'` 则直接用 `zcode://`（oauth.js:64-95；BRIDGE_PREFIX main.js:1856）。【一手】
- **回调捕获**：**无本地 HTTP server**，靠 Electron 窗口导航事件拦截 —— `will-redirect / will-navigate / did-navigate / did-redirect-navigation` 四个事件都调 `tryCapture`；命中 `BRIDGE_PREFIX` 或 `zcode://` 且 `state` 匹配才接住（main.js:2027-2048、1927-1933）。`parseCallbackUrl` 取 `authCode ?? code` + `state`（oauth.js:99-114）。【一手】
- **token 交换**：POST tokenUrl，body `{provider, code, redirect_uri, state}`，从 `data.<provider>.access_token`（及 `accessToken`、顶层同名）多级回退取值（oauth.js:148-186）。【一手】
- **凭据加解密**：算法 **AES-256-GCM**，前缀 `enc:v1:`，格式 `enc:v1:<nonce>.<tag>.<cipher>`（base64url，nonce 12B），authTag 校验（oauth.js:243-278）。密钥：`deriveKey = sha256(secret)`，secret 取环境变量 `ZCODE_CREDENTIAL_SECRET`，否则回退 `zcode-credential-fallback:<platform>:<homedir>:<username>`（oauth.js:246-257）。【一手】
- **与客户端 `enc:v1` 是否同一套**：**是同一套**——前缀、算法、键名（`oauth:active_provider / oauth:<p>:access_token / refresh_token / user_info / zcodejwttoken`）都与官方一致（oauth.js:28-31 注释、main.js:1571-1584 写入）。但**密钥派生是面板自己实现的回退式**，注释称「与官方一致」为逆向结论；未在客户端二进制中比对同一派生函数。【一手 + 半推断】
- **落盘**：`applyOAuthToken` 用 `oauth.encrypt` 加密各字段写 `credentials.json`（`main.js:1571-1584`，**由 `completeOAuth`（`main.js:2138`）调用**）；`zcodejwttoken` 只在有新值时覆盖，避免写空（`main.js:1583-1584`）。Z.ai 额外用 access_token 换业务 token `POST api.z.ai/api/auth/z/login`（`triggerBusinessLogin` oauth.js:222-239）。【一手】

---

## ⑥ 登录驱动（`login-driver.js`）

### BigModel 手机号（`LoginDriver.run` login-driver.js:334-391）
完整步骤：等登录页出现手机号输入框（45s）→ 提示人工操作 → 轮询 `probeForm` → 满足判据后自动点「登录 / 注册」→ 等落到授权页 → `confirmAuthorize`（勾协议 + 点「继续」）。【一手】
- **哪些自动、哪些留人**（类注释 login-driver.js:262-272 + `manual()` 提示 346）：**人工** = 填手机号、点「获取验证码」、过腾讯拼图、填短信验证码；**自动** = 点「登录/注册」（login-driver.js:284-286、364-367）、授权页勾协议 + 点「继续」（`confirmAuthorize` 181-212）。【一手】
- **提交判据（关键）**：`s.hasForm && s.phoneOk && s.codeOk`（手机号 ≥11 位、验证码 ≥4 位）**且** `s.code !== this.lastCode`（验证码变过）**且** `Date.now() - lastClickAt > clickGapMs`（默认 4500ms）**且** `s.btnOk` 才点（login-driver.js:300-322、356-368）。注释明说：**登录页一加载完按钮 `disabled` 就是 false，不能拿按钮可点当信号**，否则会空提交（login-driver.js:268-271）。【一手】
- **被拒退避**：BigModel 线是「验证码没变不重提」，注释理由是「填错时反复原样提交最容易招风控」；`clickGapMs` 作为最小点击间隔（login-driver.js:274-277、359-361）。【一手】
- **表单填充**：Vue/React 受控输入必须走**原生 setter + input/change/blur 事件**（`PAGE_FILL` login-driver.js:218-242）。协议勾选走**真实 click()**，被拦才兜底置位补发事件（`ensureAgreementChecked` login-driver.js:154-170；`checkAgreement` 288-297）。【一手】

### Z.ai 邮箱注册（`ZaiMailDriver.run` login-driver.js:569-786，已失效，留档）
- **提交退避（比 BigModel 完整）**：`formSettleMs = 12000` 宽限期（表单首次填满后等 12s 再点，让用户先过验证）；`nextAttemptAt` 被拒后 +12s 重试窗口（login-driver.js:398-402、618-619、636、644-656）。**不去猜人机验证过没过**——注释实测阿里云验证组件 DOM 会整体消失又重建，t+12s 元素归零但验证并未通过（login-driver.js:646-649）。【一手】
- **人机验证探测**：`probeChallenge` 纯观察（不点击），识别 Cloudflare Turnstile / Google reCAPTCHA / hCaptcha / 极验 Geetest / canvas / 自定义「点击开始验证」按钮，并读 token 长度（login-driver.js:475-521）。【一手】
- **激活链接**：只能人工从外部邮箱复制粘贴（`askText` login-driver.js:671-680），且**必须 `win.loadURL` 在原窗口打开**——交系统浏览器会丢该 partition 会话（login-driver.js:19-21、134-144、693-695）。回到授权页后核对邮箱是否本次注册账号（`readShownEmails` 561-567、744-768）。【一手】

### Z.ai 通道关闭的代码依据
`startOAuthFlow('zai')` 闸门：main.js:1946-1953，`if (providerId === 'zai')` 直接返回 `{ok:false, deprecated:true, msg:'Z.ai 邮箱注册通道已被官方关闭…'}`，**不建窗口**。注释说明 `ZaiMailDriver` 原样保留，删掉这段判断即可复活（main.js:1945）。【一手】

### 有没有内置接码平台 / 临时邮箱
**没有**。检索 `login-driver.js / oauth.js / main.js / import-account.js / settings.js` 全文关键词：`接码`、`sms`、`sms-activate`、`5sim`、`smspool`、`temp mail`、`临时邮箱`、`mail.tm`、`guerrilla`（大小写不敏感）——**业务代码 0 命中**（仅 `node_modules/` 里 app-builder-lib 的 `sms_FI` 语言表、ajv 的 `keywords` 等无关命中）。代码层面所有手机号/验证码/邮箱均由 `askText` 向使用者索要（login-driver.js:87-101、346、609）。与 README:118 一致。

> ⚠️ **修正（核验发现）**：原稿写「项目源码 **0 命中**」**不成立** —— 全仓（排除 `node_modules/`）在 **`renderer/style.css:123`** 命中一句注释 `/* ===== 自动接码开关 ===== */`。这是一段**死代码**：`renderer/index.html` 中**没有任何 `class="switch"` 元素**（grep 退出码 1），即该样式规则无对应元素。
> **裁决**：**"无内置接码能力"的结论仍成立**，但"0 命中"的表述错误 → 已改为「业务代码 0 命中，另有一句无对应元素的遗留 CSS 注释」。

---

## ⑦ 账号查询（`account-query.js`）

- **查什么**：只两样——**有没有券**（`coupon`）+ **日额度还剩多少**（`daily`），外加 `plans` 名称列表便于人眼扫（account-query.js:2-24、140-147）。【一手】
- **走哪条通道**：**联网**，端点与 `remote-plan.js` 相同（`zcode.z.ai/api/v1/zcode-plan/billing/balance`），鉴权同为 `Authorization: Bearer <jwt>` + `X-Device-Mid`（account-query.js:34-39、64-84）。【一手】
- **先校验后取值**：明确先判 status/code（401/3001/3012/非 0），**绝不把 400 读成「没有券」**（account-query.js:10-14、93-99）。【一手】
- **券判定**：`plans` 中名字不匹配 `/ZCode Start Plan/i` 的即为券（活动券/礼包，通常 `one_time`），取首个 entitlement 的 `grant_units`（account-query.js:104-121）。**日额度**：`balances` 中 `period` 为 `daily`（或空）的桶，按 `show_name` 归并求和 `total/used/left`（account-query.js:123-138）。【一手】
- **凭据来源**：`readLocalAccount` 从账号目录 `data/.zcode/v2/config.json` 递归找形如 JWT（`eyJ` 开头、三段）的字符串作 jwt；从 `meta.json` 取 `device_mid`（account-query.js:151-167）。CLI 每次请求后 sleep 2600ms（account-query.js:184、195）。【一手】

---

## ⑧ 代理分流（`main.js`）

- **不在 `oauth.js`/`login-driver.js` 里，在 `main.js`**。规则常量 `PROXY_BYPASS_RULES = 'bigmodel.cn;*.bigmodel.cn;*.zhipuai.cn;<local>'`（main.js:1872）。【一手】
- **实现**：`applyOAuthProxyPolicy(providerId)` 用 `session.fromPartition('persist:zcode-oauth-'+providerId).resolveProxy('https://chat.z.ai/')` 现读系统代理，`toProxyRules` 解析成 Chromium proxyRules，再 `setProxy({mode:'fixed_servers', proxyRules, proxyBypassRules: PROXY_BYPASS_RULES})`，随后 `closeAllConnections()` 断开旧策略连接（main.js:1874-1904）。**代理地址不写死，从系统代理现读**。【一手】
- **为何分流（实测注释 main.js:1861-1870）**：`bigmodel.cn` 全走代理 → `ERR_CONNECTION_CLOSED`，绕过直连 → 200；`chat.z.ai` 走代理 → 200，绕过 → 不通；`zcode.z.ai` 走代理 → 200。结论：国内域名直连，其余跟随系统代理。**必须在建窗口/loadURL 之前设好**（main.js:1968-1970）。【一手】
- **失败处理**：`did-fail-load` 不静默，写说明页并推 manual 提示（main.js:2050-2063、1909-1925）。【一手】

---

## ⑨ 可复用点清单

| 机制 | 文件:行号 | 我们能不能用 |
| --- | --- | --- |
| 从客户端日志尾读 `billing/balance`（4 MiB tail + 括号配对） | plan.js:36-88 | ✅ 直接用；绕开签名风控，拿真实 balances |
| 多账号串号防护：`user_plan_id` 精确匹配 + 退旧快照 | plan.js:97-149；main.js:2557-2568 | ✅ 账号池聚合必备 |
| 联网额度端点 + 必需头（Bearer + X-Device-Mid） | remote-plan.js:142-157；account-query.js:64-84 | ✅ 补日志缺失场景；须带 device_mid |
| 全局节流 10s + 3012 熔断 30min + 状态落盘 | remote-plan.js:33-48、88-110 | ✅ 多账号批量查询的限速骨架 |
| BigModel biz 余额/资源包/订阅接口 | balance.js:156-160、118-141 | ✅ 额度之外的余额维度 |
| OAuth Authorization Code + 桥接页/自定义协议回调捕获 | oauth.js:64-114；main.js:1927-2048 | ✅ 无本地 server，用窗口导航事件拦截 |
| 凭据 AES-256-GCM `enc:v1` 加解密 | oauth.js:243-278 | ✅ 与客户端同格式，可读写其凭据 |
| 受控输入原生 setter + 事件；协议真实 click | login-driver.js:154-170、218-242 | ✅ 任何 Vue/React 登录页自动化通用 |
| 「输入框有效值 + 内容变过 + 节流」提交判据 | login-driver.js:300-322、356-368 | ✅ 避免空提交招风控 |
| 按域名代理分流（国内直连、境外走系统代理） | main.js:1872-1904 | ✅ 网关若做浏览器登录同样需要 |
| 人机验证纯观察探测（不点击） | login-driver.js:475-521 | ⚠️ 只识别类型；过关仍需人工 |
| 联网结果包成日志形状复用同一 normalize | plan.js:309-320 | ✅ 统一数据模型 |

---

## ⑩ 未解决项

1. **`enc:v1` 密钥派生是否与官方客户端逐字节一致**：【未验证】。注释（oauth.js:28-31）称与官方一致，但未在 ZCode 客户端二进制/app.asar 中比对同一派生函数；若官方用 OS 密钥链（Keychain/DPAPI）而非机器特征，回退式 secret 会解不开。
2. **3012 的具体风控阈值**：【未验证】。代码只知「命中即熔断 30min」，无法得知服务端按频率/设备/IP 的判定门槛。
3. **联网返回缺 `balances` 的触发条件**：【未验证】。仅注释记录实测会缺（main.js:2533-2537），未找到稳定复现规律。
4. **`tier`（Max/Pro/Lite/Start）分级**：代码中不存在该概念，档位只由服务端 `name` 字符串承载；若需结构化档位，须自行对 `name` 建映射表。【一手：不存在】
5. **`billing/current` 端点**：注释称已被风控恒返 405/3012（remote-plan.js:14-15），未在本次调研中实请求验证。
