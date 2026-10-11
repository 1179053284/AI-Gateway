# 25 · Batch B 桌面端依赖判定（研发工程师视角）

> 视角 = 「要让调用真跑通，这台机器上必须有什么」。只读调研，未改任何既有文件、未启动任何桌面 App、未发真实上游调用。
> 路径代号（均为绝对根）：
> `DSH` = `/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts/`（权威参考实现，TS，只读）
> `OUR` = `/Users/w/Desktop/Model-Gateway/coding/model_gateway/`
> `ZP` = `/Users/w/Desktop/zcode相关管理软件/ZCode-Panel/`（真机在管 20 个 zcode 号）
> `ZPX` = `/Users/w/Desktop/zcode相关管理软件/zcode-proxy/`（Go）｜ `Z2A` = `/Users/w/Desktop/zcode相关管理软件/zcode2api/`（Python）
> `ZAG` = `/Users/w/Desktop/zcode相关管理软件/Z-Accounts-Gateway-source-20260928/`（其 `appserver.go:1-23`/`captcha.go:1-14` 经本仓 `docs/research/23` 转述并标【未验证】）
> `DATA` = `/Users/w/Desktop/Model-Gateway/coding/data/upstream/`

## 逐产品判定表

| 产品 | D 类 | App 依赖机制(一句话) | 凭据来源 | 无头刷新可否 | 调用期还须构造什么 | C 类 | 多账号并行阻碍点 | 关键证据(file:line) | 置信度 | 否证条件 |
|---|---|---|---|---|---|---|---|---|---|---|
| trae | **D1** | 一次性登录要浏览器开 trae.cn 授权页；调用期纯 HTTP，插件/网关自己在 127.0.0.1:18080 起回调服务器（不是 TRAE 起的） | 浏览器 OAuth 回跳（端口占用时回退随机端口 + 地址栏粘贴兜底）；亦可导入凭据 JSON | **可**：`ExchangeToken` 用 refreshToken 换新 token 并轮换 refreshToken，纯 HTTP | SOLO 体（`function`/`config_name` 映射 + 强制 `stream:true`）+ 三个同值 token 头 + `X-Machine-Id`/`X-Device-Id`/`X-Uid` | **C1** | 每账号必须各自持有**稳定且互异**的 `machine_id`（32hex 自生成）与 `device_id`（共用会导致同日签到互斥）；跨账号并行本身未见厂商限制 | `DSH:src/trae.ts:15,28-31,84-86,204-236,1283-1287`；`DSH:src/trae-oauth.ts:9-10,40,499-503`；`DSH:src/trae-auth.ts:10-14`；`DSH:tests/e2e/trae-reasoning-probe.e2e.spec.ts:5-6`（真发对话） | 高 | 若实测出现「同一 machine_id 多号并行被 401/风控」或发现任何一处连 TRAE 本地端口/IPC → 改 D2/C2 |
| cline | **D1** | 登录 = WorkOS **设备码轮询**（连本地监听端口都不起），浏览器可在与网关不同机器上打开授权 URL | WorkOS 设备码 → `POST /api/v1/auth/register` 换 access/refresh；导入亦可用 | **可**：WorkOS refresh（体是驼峰 `{refreshToken,grantType}`） | 标准 OpenAI 体 + **`Authorization: Bearer workos:<jwt>`（`workos:` 前缀不可剥，剥了 401 且文案误导）** + `HTTP-Referer`/`X-Title`/`X-IS-MULTIROOT`/`X-CLIENT-TYPE` | **C0** | 无设备身份字段（`DeviceSpec(fields=())`），账号间零共享状态；仅我方 `MaxRotate=3` 换号上限 | `DSH:src/cline-adapter.ts:6-9`；`DSH:src/cline-oauth.ts:11-17,21-38`；`DSH:src/cline.ts:271-281`；`OUR:upstream/cline/out.py:8-11`；`OUR:accounts/registry.py:46-47` | 高 | 若 WorkOS 侧出现「同用户并发会话数上限」类错误码 → 改 C2 |
| loomy | **D0** | 全程不需要桌面 App，也不需要本机浏览器：短信/微信两条登录都是纯 HTTP（HMAC-SHA1 签名算法已逐字节复刻成代码） | 短信两步（`sendMsgCode`→`checkCode`，声明 `expire:1209600`）或微信扫码长轮询（微信侧只需手机）；导入亦可 | **不可**：上游根本没有 refresh 端点 → 14 天到期只能**重新短信/扫码**（需一次手机侧动作） | chat 只认 `Authorization: Bearer`，业务端点只认小写 `token` → **两个都发**；账号端点另需 `account {ak}:{sig}` HMAC 签名 + `base.ua` 硬编码为四段竖线串（`Loomy`、`Desktop`、`Electron`、`macOS`） | **C0** | 无设备身份；真正阻碍是**额度语义**：积分耗尽不报错、静默改扣永久积分 → 既有「限流换号」失效，需按余额独立选号 | `DSH:src/loomy-adapter.ts:6-16`；`DSH:src/loomy.ts:213-232`；`DSH:src/loomy-auth.ts:4-15`；`DSH:src/loomy-oauth.ts:12-21,55-71`；`DSH:src/loomy-sign.ts:1-19`；`DSH:README.md:1660-1680` | 高 | 若上游新增「按设备/会话绑定」判据（如要求 `devid` 真值）→ 改 C1；若发现到期凭据仍可用 → 刷新列改「可」 |
| raccoon | **D1** | 登录要手机（微信扫码**公开网页**）或真人过一次阿里云滑块；官方桌面端那条 `office-raccoon://` 自定义协议回调链**不可复用**，已被绕开 | 客户端本地随机 `code` + 轮询 `login_with_qrcode_code`（实测任意自造 code 被接受）；短信路径手机号需 AES-128-CFB 加密 | **可**：有 `refresh_token` 轮换，纯 HTTP（滑块只在重新登录时） | 标准 OpenAI 体 + `Bearer` + `X-Org-Code`（个人号空串）+ `X-Raccoon-Language`；登录奖励/部分端点必需 `X-Client-Platform`；思考档位**只有** `extra_body.thinking.{type}` 一条有效通道 | **C0** | `device_id` 是**可选**字段（DSH 从不生成、只透传；缺失即不发该头）；本仓两号各带独立 uuid | `DSH:src/raccoon-adapter.ts:6-8`；`DSH:src/raccoon.ts:6-19,271-285`；`DSH:src/raccoon-oauth.ts:6-18,120-130,186-198`；`DSH:src/raccoon-login-page.ts:337,504-515`；`OUR:upstream/raccoon/product.py:6,27-30` | 高 | 若实测发现同账号多路并发被服务端判异常 → 改 C2；若发现 `X-Client-Device-ID` 成为 chat 硬判据 → 改 C1 |
| zcode | **D3**（登录可 D1） | **不要 ZCode 进程**（DSH 原话「纯 Node，不需要 ZCode 实例运行」），但调用期要三样**产物**：官方身份块文本（从 3.11.2 bundle 反解）+ 一次性阿里云 captcha param（需本机一台 **headful 真 Chrome**，非 ZCode 壳）+ 可选的磁盘凭据解密（secret 绑 `platform+home+username`） | ①官方 CLI **设备授权流**（`POST /oauth/cli/init` → 浏览器 → `GET /oauth/cli/poll/{flow_id}`，不经 `zcode://`）＝D1；②解密 App 数据目录 `~/.zcode/v2/credentials.json`（`enc:v1:` AES-256-GCM）＝D3 | **不可**：静态凭据，无 refresh 端点；DSH 的 `refresh()` 语义 = **重读磁盘** | 每请求现产一次一次性 captcha（缺→`400 code=3007`，复用→再 `3007`）；`system` 必须**前两块**=官方 cliPrefix(42)+stable(2856)，调用方 system 追加在**最后**；首轮 user content **数组最前面**插 `<system-reminder>` 日期块；`X-Device-Mid` 必带（缺→`400 code=3001`）；Anthropic Messages 协议 | **C0**（带实现级瓶颈） | `device_mid` **值不被绑定校验**（同一 JWT 换任意随机 UUID 都 200），只需每号稳定唯一 → 跨号并行成立；真正瓶颈是**我方**：captcha 常驻只一台浏览器 + 复用单页面 → `pageBusy` 串行化 mint；且 `3012` 有账号惩罚梯度（30min→24h→5 次停用），并行过猛会把号打进冷却 | `DSH:src/zcode.ts:2,6-27,60-87`；`DSH:src/zcode-login.ts:2-29`；`DSH:src/zcode-adapter.ts:7,15-17,30-35,494-495`；`DSH:src/zcode-identity.ts:10-27`；`DSH:src/zcode-upstream.ts:43,67-91`；`DSH:src/zcode-captcha.ts:10-23,40-48,94-108,477-497`；`DSH:src/zcode-auth.ts:320-335`；`OUR:upstream/zcode/billing.py:12-18` | 中高（推理面本机未实跑） | 见「zcode 专项」§三种解释的否证方法；若最小实测证明「合格 captcha + 完整身份块仍 405/3012」→ 改 **D2**（必须经官方宿主进程）或 **D4** |

## 1. trae

**证据链**
1. 推理面 = 纯 HTTP 直连：`DSH:src/trae.ts:15` 表列 `POST /api/agent/v3/llm_utils_chat @ trae-api-cn.mchost.guru`，鉴权 `Cloud-IDE-JWT <token>`；`DSH:src/trae.ts:204-236` 构造的那套 SOLO 头里没有任何「本机端口/IPC」项。
2. 全仓 grep `127.0.0.1`：trae 只出现在 `trae-oauth.ts`（登录回调服务器），**没有任何**指向 TRAE IDE 本地端口的调用；grep `spawn|execFile` 只命中 `login.ts`（打开系统浏览器）、`qoder-machine.ts`、`zcode-captcha.ts` —— **trae 不在其中**。
3. 「固定端口是谁起的服务器」答案：**插件自己起的**。`DSH:src/trae-oauth.ts:9-10` 说明 TRAE 授权页 `www.trae.cn/authorization` 强制回跳 `http://127.0.0.1:18080/authorize`（端口对齐 Go 端默认），而 `:499-503` 是本插件 `createServer().listen(port,'127.0.0.1')`；18080 被占则回退随机端口并用**实际端口**重建授权 URL。本仓同款监听在公共层（`OUR:upstream/trae/login.py:5-11`，BD4），并有「地址栏粘贴」兜底 ⇒ **即便一个本地端口都不起也能收凭据**。
4. 设备字段是**自生成**而非抄 App：`generateMachineId()` = `crypto.getRandomValues(16)` → 32hex（`DSH:src/trae.ts:1283-1287`）；`DATA/trae/accounts/*/meta.json` 两号 `machine_id`/`device_id` 互异、`via:"import"`。
5. 真实跑通有先例：`DSH:tests/e2e/trae-reasoning-probe.e2e.spec.ts:5-6` 明确「真的向 TRAE 发对话请求」，且用双环境变量闸门确认才跑。

**机制推断**：D1。调用期只需要 access_token（可 HTTP 续期）+ 一组自生成设备指纹头。桌面 App 与调用路径完全不相交。

**未确定**：①`machine_id` 与账号的**绑定强度**只有注释级依据（`trae.ts:134-141`「同一账号用不同 machine_id 可能触发风控或要求重新登录」），未见错误码；②`DSH_TRAE_ROTATE_MACHINE_ID` 轮换开关默认关闭，说明作者也没被证实「多号同 machine_id 会出事」；③本仓两号尚未做同产品双号并发实测。

## 2. cline

**证据链**：`DSH:src/cline-adapter.ts:6-9` 推理端点是**标准 OpenAI 兼容** `POST {apiBase}/api/v1/chat/completions`，实测标准 SSE；`DSH:src/cline-oauth.ts:11-17` 的对照表明确 Cline 走 **WorkOS 设备码轮询、不需要本地端口**（并指出官方桌面端在 prod 下走的也正是设备码分支，`48801-48811` 回调端口那条分支被刻意不实现）；三步协议在 `:21-38`。本仓取证把唯一的真实坑钉死：`workos:` 前缀不可剥（`OUR:upstream/cline/out.py:8-11`）。
**实跑先例（本仓一手）**：`:8300` 上经 cline 账号真实调用 `gpt-6-astra` 返 200，并据此抓修了非流式 `{success,data}` 信封未解包 —— 见 `docs/changes/e2e-records/E2E-20261001-anthropic-openai-catalog.md:132,138`。**这条是 Batch B 里唯一在我方网关上跑通过真实推理的账号级证据。**
**机制推断**：D1（且比 D1 更弱：授权页可以在另一台机器/手机上打开）。
**未确定**：WorkOS 侧是否有「同用户并发会话/token 复用」限流（无错误码样本）。

## 3. loomy

**证据链**：`DSH:src/loomy-adapter.ts:6-11` 「标准 OpenAI 兼容 + 标准 SSE，**无加密、无信封、无格式转换**」；chat 头只有两个（`DSH:src/loomy.ts:225-232`，实测缺 Bearer 前缀 → `100002 缺少 token`）。登录两条都无 App：短信两步是纯 HTTP + HMAC-SHA1 签名（`DSH:src/loomy-oauth.ts:12-21`），签名算法「逐字节复刻客户端 `electron/xfyun/sign.js`」且**全部纯函数**（`DSH:src/loomy-sign.ts:1-19`）⇒ 属于「可公开复现的算法」，不是必须从 App 里抠出来的产物；微信扫码走 `open.weixin.qq.com` 三步纯 HTTP 长轮询，`redirect_uri` 因微信域名白名单**必须**用官方地址（那个回调页实测 404，但链路完全不碰它，`DSH:src/loomy-wechat.ts:8-35`）。
**机制推断**：D0（调用期与登录期都不需要桌面端软件）。
**未确定 / 风险**：**不可续期是运营风险不是依赖风险** —— `DSH:src/loomy-auth.ts:4-15` 说清 `isLoomyRefreshable()` 恒 false、`refresh()` 只做有效性探测、失效时如实抛错。所以 14 天后必须有人拿手机重过一遍短信/扫码，**无头不可自动化**。另外 `DSH:README.md:1660-1680`：额度耗尽不报错而静默扣永久积分 ⇒ 我们的 `x 次失败换号` 对 loomy 无效，必须按余额选号。

## 4. raccoon

**证据链**：`DSH:src/raccoon-adapter.ts:6-8` 标准 OpenAI + 标准 SSE。登录侧最有价值的一条是**明确绕开桌面端**：`DSH:src/raccoon.ts:12-15` 与 `raccoon-oauth.ts:13-18` —— 官方 `desktopLogin.js` 靠 `office-raccoon://auth/callback` 自定义协议回调，且 `/code/authorize` 的回调地址写死改不成 localhost，宿主侧 Node 收不到 ⇒ 该链路只保留 `exchangeRaccoonAuthorizationCode` 备用；实改为「客户端本地随机 32hex code + 轮询」，**实测任意自造 code 都被接受**。二维码内容是**公开网页** `${apiBase}/login/mp?code=&appname=商汤小浣熊官网`，用户在**微信**里完成授权（`DSH:src/raccoon-oauth.ts:120-130`），所以「扫码」要的是手机微信，不是小浣熊桌面端。短信次路需手机号 AES-128-CFB（公开常量密钥 `raccoon.ts:36-43`）+ 阿里云滑块 `captcha_param`，滑块由用户在**插件自建的本地页**里真人完成（`raccoon-login-page.ts:337,504-515`）。
**机制推断**：D1（一次性登录要手机/浏览器，调用期纯 HTTP + refresh_token 轮换）。
**未确定**：企业号（`X-Org-Code` 非空）与个人号是否有不同并发口径；`extra_body.thinking` 之外通道（`reasoning_effort` 8 枚举）实测「被接受但无效果」，别当有效判据。

## 5. zcode 专项（全案最关键）

### 5.1 DSH 侧「推理路径」到底是什么（`billing/claim` 之外）
`POST https://zcode.z.ai/api/v1/zcode-plan/anthropic/v1/messages`（`DSH:src/zcode-upstream.ts:43`）——**Anthropic Messages 协议、纯 HTTPS、不经任何本机端口**。前置三件事：
1. **每请求一次性 captcha**（`zcode-adapter.ts:30-35,494-495`）：缺 `x-aliyun-captcha-verify-param` → `400 {"code":3007}`；param 一次性，复用 → 再 `3007`。
2. **body 准入块**（`zcode-identity.ts:10-20` 实测矩阵）：无 system → 3012；只有 42 字符 cliPrefix → 3012；**cliPrefix+stable(2355 字符) → 200**；完整四块(7599) → 200。首轮 user 必须在 `content` **数组最前面**插 `<system-reminder>` 日期块（拼进字符串仍判为裸请求，`zcode-identity.ts:183-197`）。
3. **`X-Device-Mid`**（缺 → `400 code=3001`，`zcode-upstream.ts:60-91`）。
关键结论原文（`DSH:src/zcode.ts:13-18`）：「上游准入**并不真的需要 Electron**：captcha 是阿里云**网页 SDK**，只需一个有 DOM 的浏览器；3012 的判据是**请求体内容**，与运行时无关 —— 上游实测 **curl 同样 200**」。且 `zcode-upstream.ts:63-65` 明确：**那些「像官方客户端」的头不是 3012 的判据**。

### 5.2 「本机 ZCode App 进程」在这条链上的真实角色 = 零
- PR#17 初版设计过「读 `<dataBase>/.zcode/v2/bridge-port.json` → 打本机桥 → 由 ZCode 实例代发」，**已被废弃**，理由是一手实测：官方闭源版 `%LOCALAPPDATA%\Programs\ZCode\ZCode.exe` **根本不写** `bridge-port.json` ⇒「装了 ZCode」≠「桥可用」，而现实用户装的正是官方版（`DSH:src/zcode.ts:6-12`）。**这条反向证明：连作者最初想要的 D2 路线在官方版上都是走不通的，所以才改成 D3/D1。**
- 本仓 `OUR:upstream/zcode/dataroot.py:176-232`（`is_zcode_running` / `kill_zcode` / `launch_command`）经 grep 全仓确认：**唯一调用点是 `OUR:cli_zcode.py:108-122`（`mgw zcode launch`）**，用途 = 「以某账号的那一份数据根启动官方客户端」（切号/登录/跑客户端产生日志的**运维路径**）。推理链（`adapters/anthropic_out` ← `upstream/zcode/out.py`）**不引用** dataroot 的任何进程函数。⇒ 判定：**导入/运维路径，不是推理路径**。（另注：本仓 `ensure_layout` 建的 `data/userdata/session/home` 四根也是给 App 启动用的，`dataroot.py:14-24` 自陈三个 `ZCODE_DESKTOP_*` 是否真覆盖 `app.setPath` 本机未实测 = §19 T10。）

### 5.3 第三方材料「直连恒被拒 405/3012」的成因判定（三种可能 + 否证方法）
先给一条我认为**决定性**的旁证：`ZP:remote-plan.js:3-17` 记录 **同一个 host、同一套凭据**下 `GET /zcode-plan/billing/balance` = **200**，而 `billing/current` = **恒 405 `code=3012`**；本仓 2026-10-02 一手复测 **16/16 在册号 `GET /billing/balance` 全 200 / code=0**（`OUR:upstream/zcode/billing.py:12-18`，原始响应逐字存档 `docs/changes/e2e-records/E2E-20261002-zcode-quota-probe.md`）。
⇒ **「405 + JSON body `{"code":3012}`」是应用层拒答，不是 WAF 拦截**（WAF 只会给 HTML 挑战页/连接层重置；本仓 `docs/research/15:196` 也把「2xx 但 Content-Type 非 JSON/SSE」单列为 WAF 页判据）。所以「必须经 App / TLS 指纹」这一解读与「405 能带 JSON 业务码」自相矛盾。据此排三种可能：

| 解释 | 支持证据 | 反证 | 判定 | 否证方法（最小测法） |
|---|---|---|---|---|
| **H1 请求体准入**（缺官方身份块/首轮日期块）| `DSH:src/zcode-identity.ts:10-20` 同账号同 captcha 只换 body 的矩阵；`ZPX:relay.go:305-310,460-464` 有独立 3012 分支，而 `ZPX`/`Z2A` **两家都不注入身份块**（grep 无 `system-reminder`/`You are ZCode` 命中） | 目前无反证；本仓 `out.py:30-32` 也登记了「身份块未注入」这一缺口 | **最可能成因** | 一发请求即可判：同凭据、同 mint 环境，只切换 `system` 是否含 cliPrefix+stable 两组对比 |
| **H2 TLS/传输指纹被 ESA WAF 拦** | `docs/research/15:23-24`（Go 默认 ClientHello **易被**识别，故 `ZPX` 对 `zcode.z.ai` 用 utls + **显式禁 h2**）；`ZPX:README.md:122,247` | **限定条件是 Go**：`docs/research/15:11` 修订记录把「TLS 指纹伪装是**刚需而非可选**」降级为「**强默认项（可关闭）**，实际拦截率未测」（`15:23-24` 同口径）；`DSH`(Node undici)/`Z2A`(httpx)/curl 三家均无同类断言且自称可用 | **产品/传输栈相关，不是 App 相关**（Python 侧 `curl_cffi` 已在 `OUR:upstream/zcode/auth.py` 备好降级缝） | 同一 body 分别经 ①Go 裸 `net/http` ②Node `fetch` ③Python `httpx` ④`curl_cffi(impersonate="chrome")` 各发一次：**只有 ①挂 → H2 成立且与 App 无关**；四种都挂 → 才考虑 D4 |
| **H3 captcha param 的 mint 环境被判** | `Z2A:app/captcha.py:1-11`（Node+jsdom 方案被识破 `F001`，改 Playwright 且优先复用本机**真实 Chrome/Edge**）；`ZPX:README.md:243,245`（捆绑 Chromium 会被识别；**数据中心 IP 触发 F001**）；`DSH:src/zcode-captcha.ts:40-48,94-108`（`--headless=new` 过不了必须 headful；origin 必须真实 `https://zcode.z.ai/`，`about:blank` 第二次起 F001） | 这类失败上游给的是 **`3007`**（`zcode-adapter.ts:637-638`）与 `F001`，**不是 3012**；`ZAG` 把 mint 搬进官方渲染器（`23 §2.9`）恰好说明他撞到的是 mint 侧环境门槛，随后把整体归因写成「直连必被 405/3012」 | **可解释 ZAG 的断言来源**：很可能是 3007/F001 与 3012 混记，或 mint 合格后仍缺 H1 的 body 块 | ①去掉 captcha 头 → 必 `3007`（证明 captcha 检查在 body 检查**之前**还是之后）；②合格 shape（≥200 字符且 `securityToken≥50`，`zcode-captcha.ts:111-130`）+ 完整 body → 若 200 则 ZAG 断言被证伪 |

**我的结论**：ZAG 的 `appserver.go:1-23`「唯一被风控接受的形态 = 官方宿主进程自己发请求」是**作者自述、我方未复验**（`docs/research/23:22,184` 已如实标【未验证】），且与 DSH 的一手矩阵、ZCode-Panel 的 200 复测、本仓 16/16 的 200 三者相冲突。按「**推理面 = D3**（要产物不要进程）」判；若最小实测证明「合格 captcha + 完整身份块仍 405/3012」，则按证据改判 **D2**（须 spawn 官方宿主 `zcode.cjs app-server --stdio`，注意这**不是** GUI App 而是它的 Node bundle，属 D2/D3 边界，`23:186` 的 `exec.Command(node, zcode.cjs, "app-server", "--stdio")`）或 **D4**。

### 5.4 zcode 多账号并行
`device_mid` **不绑定校验**：同一 JWT 换任意随机 UUID，`billing/balance` 都回 200，缺它才 400/3001（`DSH:src/zcode-auth.ts:320-335`）⇒ 自生成即可，本仓 16 号各带**互不相同**的 `device_mid`（uuid 形态，`DATA/zcode/accounts/*/meta.json`）。`event/report` 幂等按 `device_mid+日期` 去重（`zcode-upstream.ts:277`）。⇒ **C0**。
但两条**真实**阻碍要写清：①`DSH` 的 captcha 是「常驻一台浏览器 + 复用单页面 + `pageBusy` 串行」（`zcode-captcha.ts:484-497`、`README:1914`）——**这是我方吞吐上限，不是厂商限制**，多号并行 mint 会排队；②`3012` 有**账号惩罚梯度**（30min / 24h 内第 3 次起 24h / 5 次停用，`zcode-identity.ts:22-27`）且被分类为 `PERMISSION` **不可重试**（`zcode-adapter.ts:660-670`）⇒ 并行必须配 per-account 熔断，否则会自己把号打死（本仓 F-4 已登记转发路径遇 3012 **无护栏**，`out.py:35-40`）。另 `23 B5`（`liveaccount.go`）把「官方客户端正在用的号」从池里排除，反证「同号被 App 与网关同时使用」是作者认定的风控形态 —— 我们的整根隔离只解了**数据**冲突，没解**同号并发**。

## 最可能与其他角色分歧的地方
1. **zcode 判 D3 而非常被预期的 D2/D4**。分歧点在于「ZAG 作者断言」的可信度：我认为它与三条一手 200 复测（DSH 矩阵 / ZCode-Panel 同 host 双端点对照 / 本仓 16/16）不可并存，倾向判 ZAG 归因错误（H1 或 H3 混记成 405/3012）。若评审角色以「材料说了」为通过依据，会得出 D2 并要求引入官方宿主桥 —— 那会把一条不存在的 App 依赖变成架构债。
2. **「headful 真 Chrome」算不算 App 依赖**。我判**不算**（阿里云网页 SDK，任何有 DOM+canvas 浏览器皆可；obscura/Lightpanda 实测不行是引擎缺口，不是 ZCode 壳），但它确实是**调用期的一个本地进程需求**，运维视角会把它当依赖报出来。这是措辞级分歧，需要在 PRD 里统一。
3. **loomy 判 D0 而它「14 天后必须人拿手机重登」**。若「无头刷新可否」被列为硬性验收项，loomy 会从 D0 掉到「不可自动化」——我已在表内如实分列，别把两件事混成一个 D 级。
4. **trae 判 C1（设备身份必须每号唯一）vs 判 C0**。依据只是注释级（`trae.ts:134-141` 风控 + `:84-86` 签到互斥），没有错误码样本；保守起见我给 C1，激进角色可能给 C0。
5. **本仓 trae `device_id` 形态存疑**：`DATA/trae/accounts/*/meta.json` 里是 **32hex**，而 `DSH:src/trae.ts:84-86,143-148` 说签到用的 `device_id` 应是 **15/16 位数字**（本仓也实现了 `derive_device_id15(uid)`，`OUR:upstream/trae/protocol.py:122-125,212`）。SOLO 头的 `X-Device-Id` 走 hex32、签到头走 15 位数字（`protocol.py:226-250` 的 `read_str(cred,"login_device_id") or read_str(cred,"device_id")`）——**两条通道两种值**。这属于**导入侧字段口径风险**，与 App 依赖无关，但必须报告（铁律 5），建议后续角色核对 DSH `generateDeviceId` 注释里「早期实现错误地生成了 16 位纯数字」那条改判。

## 必须实测才能定论的地方
1. **zcode 推理面单变量矩阵（首要，D1 裁决）**：取 1 个在册号，绕开 `/v1/models` 直接从 `upstream/zcode/out.py` 发 `POST /zcode-plan/anthropic/v1/messages`，四组：
 - A 无 captcha 头 + 无身份块 → 预期 `400 {"code":3007}`（说明 captcha 检查先于 body 检查）；若得 **3012** 说明 body 检查在前，则 ZAG 的「带合法 captcha 仍 3012」就自洽；
 - B 有身份块+日期块、无 captcha → 预期 `3007`；
 - C 完整身份块 + 合格 captcha（长度≥200、`securityToken`≥50）→ **200 = 直连成立（D3 定案）**；`405+code=3012` = 转 H2/H4 测；
 - D C 组但**去掉** stable 块只留 cliPrefix → 预期 3012（复现 DSH 矩阵，证明判据真的是 body）。
 ⚠ 纪律：C/D 之间不要连续重试，每组间隔并先落 3012 计数（`zcode-identity.ts:22-27` 的 5 次停用梯度是真实风险）。
2. **zcode 传输栈对照（H2）**：同 C 组 body，分别用 `httpx` / `curl_cffi(impersonate="chrome")` / Go 裸 `net/http` 各发一次。预期：若只有 Go 得 **405/3xx/HTML** → 判定「TLS 指纹是传输栈问题」，本仓继续走 `curl_cffi`；若三者一致 → H2 排除。
3. **zcode captcha mint 无头可行性（macOS 本机）**：`DSH` 的 headful 硬约束是 **Windows 实测**（`zcode-captcha.ts:40-48` + README 表格），本仓 `upstream/zcode/captcha.py:20` 自己标了「未实测口径」，且 `OUR:main.py:254-272` 因 `CAPTCHA_PROVIDER=None` 把 zcode 模型**排除出 `/v1/models`**。测法：本机 Playwright 起真实 Chrome（非捆绑 Chromium）、导航 `https://zcode.z.ai/`、`startTracelessVerification`，分别试 headless/headful，判据 = param 是否 ≥200 字符且能换 200。预期：headless 得 `F001`/短 param → 必须 headful（并把结论回写 §16.5 与 `23:332` 的「住宅代理」前提是否成立）。
4. **同产品双号并发**：trae 两号（各自 machine_id/device_id）、zcode 两号（各自 device_mid）各并发 1 条最小请求（`max_tokens` 压到个位）。预期 200/200；若出现 `401`、`9004`、`code=3012` 或「该设备已签到」类互斥 → 把对应 C 类从 C0/C1 升级到 C2 并给出错误码。
5. **trae `machine_id` 绑定强度**：同账号故意换一个 machine_id 发一次（预期 `401`/要求重登 vs 200），用来把 `trae.ts:134-141` 的注释级依据升为错误码级事实。⚠ 有触发风控风险，需用户批准且只做一次。
6. **loomy/raccoon 无头刷新边界**：raccoon 走 refresh 端点单测化即可（预期 200 + 新 token）；loomy 无端点可测，只能确认「不假装续期」这条纪律在失效时给出**明确错误**而非静默成功。
7. **未实测项（本轮同样不做，登记不代改）**：真实扫码支付闭环、`ZCODE_DESKTOP_*` 三变量能否覆盖 `app.setPath`（§19 T10）、老格式（仅 jwt+device_mid）导入是否被官方客户端判未登录（`22 U1`）。
