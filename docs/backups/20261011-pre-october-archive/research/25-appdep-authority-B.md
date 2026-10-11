# 25 · App 依赖性调研（Batch B · 外部权威证据面）— trae / cline / loomy / raccoon / zcode

> 角色：通用权威角色（本仓代码之外的独立证据：厂商官方文档 + 公开 API 说明 + 第三方开发者实证）。
> 日期：2026-10-02。本轮**零改动**（不新建/修改既有文件，除本文件）、无 git 写、不启动/退出任何 App、不发真实上游调用、未读任何凭据明文。
> 图例 D：D0 无依赖 / D1 首登录依赖 / D2 运行期依赖（需 App 进程活着）/ D3 离线产物依赖（需 App 产物但不要进程）/ D4 未知或被风控拦。
> 图例 C：C0 同账号多会话可并存且无官方限流 / C1 要求每账号设备身份唯一（或设备绑定）/ C2 互踢或服务端限流 / C3 无证据、未知。

## 逐产品判定表

| 产品 | D 类 | App 依赖机制(一句话) | 官方是否提供对外 API | token/会话官方策略 | C 类 | 多账号并行官方限制或社区实证 | 关键证据(URL 或 file:line) | 证据等级 | 否证条件 |
|---|---|---|---|---|---|---|---|---|---|
| `trae` | **D3**（倾向，D1 待实测裁决） | 推理/签到要 `Cloud-IDE-JWT` + 真实设备身份头（`X-Machine-Id`/`X-Device-Id`），凭据与设备串取自客户端本地存储；不需要客户端进程存活 | 否：内置模型无对外 API，官方「自定义模型」是 BYOK（填**你自己**的第三方 Key） | 官方未公开 JWT 生命周期；社区实测 access≈14 天、refresh≈180 天；官方社区答复「单账号同时在线设备一般 2-3 台，Pro 也不行」 | **C2**（同账号在线设备数硬上限）＋设备身份需真实 | 社区实证「多账号/混用凭据会触发风控，24h 后解锁」，无提前警告 | https://docs.trae.cn/ide/models ；https://forum.trae.cn/t/topic/6057 、/t/topic/2825 ；https://juejin.cn/post/7688669403517960202 ；`coding/model_gateway/upstream/trae/protocol.py:208,233,245-249` | 对外 API 缺失=权威文档；设备/token/风控=二手（社区+官方论坛） | 若网关**自造** machine_id/device_id 也能稳定调通推理（社区说伪造 UUID 被拒），则降 D1 |
| `cline` | **D1** | 首登录要浏览器（WorkOS 设备码）或在网页控制台建 API Key；调用期纯 HTTP，官方文档未要求任何 Cline 进程存活 | **是**：`https://api.cline.bot/api/v1` 官方 OpenAI 兼容 Chat Completions，Key 在 app.cline.bot 自助创建；另有官方 CLI 支持 headless CI | 未写过期/轮换周期，仅说「定期轮换、吊销立即失效」；无设备/会话条款 | **C3→C0（未验证）**：无任何设备绑定条款，也无并发/互踢实证 | 官方与社区均无多账号并行限制条款或实证风控报告 | https://docs.cline.bot/api/authentication 、https://docs.cline.bot/api/overview 、https://docs.cline.bot/usage/cli-overview ；https://www.xmsumi.com/detail/3898 ；`docs/research/20-…接入与账号运营机制.md:419`（`workos:` 前缀） | 权威文档（端点/鉴权/headless）；并发维度=无外部证据 | 若 `api.cline.bot` 实际校验扩展来源/客户端版本（我们用的是设备码 token 而非 Key），则升 D3 |
| `loomy` | **D3** | 出站须复刻客户端 `electron/xfyun/sign.js` 的 HMAC-SHA1 9 段签名 + `account {ak}:{sig}` 头；官方形态=桌面客户端，无网页版、无公开 API | 否：官方文档只允许 BYOK（用户自配 API Key，「密钥仅存本地不上传云端」） | 官方未披露 token 有效期/刷新/设备上限；本仓记载**不可续期** | **C3**（外部零证据） | 无官方限制条款、无社区实证风控材料 | https://loomy.xunfei.cn/docs/（BYOK 原文）；https://ai-bot.cn/sites/73695.html（「桌面级 AI 工作搭子」「每天免费5000积分」）；`upstream/loomy/sign.py:1-16`；`docs/research/20-….md:271` | 形态/BYOK/每日积分=权威＋二手；签名机制=本仓代码事实（外部无证据） | 若 AK/SK 可在网页端或开放平台自助取得且不依赖客户端产物，则降 D1 |
| `raccoon` | **D1**（倾向） | 官方明写支持「桌面端/网页端/iOS」，登录=扫码或短信（浏览器可完成），推理走 `/api/web/llm/v2` web 通道；不要求桌面进程；需 `X-Client-Platform` 头 | 否：无任何公开 API / API Key 说明 | 官方未披露；本仓记为可续期（仅 lead 窗口内账号） | **C0**（同账号多端并存是官方正面宣传：手机发指令、电脑持续执行） | 多账号并行无官方条款、无社区实证；每日 300 积分由服务端按日自动发放（本仓取证） | http://m.10jqka.com.cn/20260825/c679265019.shtml ；https://www.sensetime.com/cn/news/raccoon-work-app ；`docs/research/20-….md:330,421` | 二手（官方新闻稿 + 媒体）；无权威 API 文档 | 若 `/api/web/llm/v2` 校验桌面下发的设备指纹（本仓 `desktopDeviceIdentity`），则升 D3 |
| `zcode` | **D3 与 D4 并存**：离线产物依赖成立，405/3012 成因仍属 D4（无公开权威解释） | 内部通道每请求带阿里云无痕验证码头 + `X-Device-Mid` + 官方身份头；凭据**按设备加密**（换机不可解密）；官方客户端自带可无 Electron 运行的 CLI/app-server ⇒ 不必「桌面 GUI 进程存活」 | 分两条通道：① 开放平台 GLM Coding Plan **有**官方 API（`api.z.ai/api/coding/paas/v4`、`api.z.ai/api/anthropic`、Dashboard 建 Key）；② `zcode-plan` 内部通道**无**对外 API | 官方 FAQ：「登录凭据按设备加密，换机后无法解密，直接在新机器重新登录即可」；未披露 token 期限与并发上限 | **C1**（设备绑定）＋官方 ToS 明确禁止多账号 | ToS：「账户仅限您本人使用」「不当注册或不当使用多个账户可冻结/关闭/拒绝服务」「禁止自动化、抓取、逆向、绕开安全措施」；Coding Plan 侧违规 3 次封号（策略码 1302/1303/1113） | https://zcode.z.ai/cn/terms ；https://zcode.z.ai/cn/docs/qa ；https://zcode.z.ai/cn/docs/welcome ；https://docs.openclaw.ai/zh-CN/providers/zai ；https://github.com/zai-org/ZCode ；`/Applications/ZCode.app/Contents/Resources/app.asar`（明文串取，见 §5）；`docs/research/23-….md:22,174,184` | ToS/FAQ/开放平台端点=权威文档；asar 机制=本地取证；405/3012 直连被拒=**仅第三方自述（未验证）** | 最小实测：带 captcha+设备头的纯 HTTP 直连可通 ⇒ 判 D3；恒 405/3012 而仅官方宿主内可通 ⇒ 升 D2/D4 |

## 1. trae

**外部证据摘录**
- 官方《内置模型 & 自定义模型》：「除内置模型外，TraeCode 还支持接入自定义模型」，自定义须「填写调用该模型所需的 API 密钥」并由系统「调用服务商的接口来检测 API 密钥是否有效」——即 **BYOK 是用户自带第三方 Key，与账号订阅内置模型不是同一条通道**；全文无任何面向外部程序的调用规范，模型选择入口只在 IDE 输入框（https://docs.trae.cn/ide/models）。
- 官方中文社区（Bug 反馈区）：「目前 Trae 对单个账号的同时在线设备数量有限制，一般是 2-3 台同时在线，主要是为了防止账号共享滥用」「我这边可以帮你反馈给开发团队…手动帮你处理设备下线」（https://forum.trae.cn/t/topic/6057）；另一帖：「一个号最多登两个设备哈」「pro 用户也不行呀」「多个账号会导致会触发风控，24h 后会解锁」（https://forum.trae.cn/t/topic/2825）。
- 第三方开发者实证（Trae CN 自动签到 Serverless 复盘，2026-09-24）：主机 `https://api.trae.cn`，端点 `/trae/api/v2/ug/checkin_credits/{status,claim}`、`/api/v2/pay/ide_user_ent_usage`；鉴权 `Authorization: Cloud-IDE-JWT <token>`；「x-device-id —— claim 必需、status 不需要；不带 claim 必回 9004」；凭据「harvested from the local Electron client's storage directories」，且「fabricated UUIDs or telemetry hashes are rejected」；「JWT expires approximately every 14 days, refresh token ~180 days」；「限流码藏在 HTTP 200 的 body 里」，`9074` 常在设备标识无效时出现（消息却谎报网络拥塞）；「Default Python user-agents may also trigger WAF rejections that resemble authentication errors」（https://juejin.cn/post/7688669403517960202）。
- 另一社区代理（2026-09-22）：「Trae 桌面端的登录态是加密存在本地 storage.json 里…硬编码盐 + AES-128-CBC + SHA-512 KDF」；「设备指纹头（machineId / deviceId / appVersion 等）、Cloud-IDE-JWT 鉴权」；「代理是独立 Node 进程…不要求图形界面在推理时活跃」；「token 刷新只在进程内存里做」（https://zishu.me/blog/trae-openai-proxy.html）。
- 本地取证（只读）：`/Applications/TRAE SOLO CN.app/Contents/Resources/app/product.json` → `dataFolderName: .trae-cn`、`package.json` version `1.107.1`；`out/main.js` 与 workbench 包内均含 `machineId`(39/43 处) 与 `Cloud-IDE-JWT`(9 处)；`Contents/Resources/app/bin/trae-solo-cn` 只是 VS Code 式 CLI 包装（`ELECTRON_RUN_AS_NODE=1 … out/cli.js`，第 32-38 行）——**Trae 的「CLI」是编辑器命令行，不是无头推理入口**。本仓 `upstream/trae/const.py:86,104` 的 UA 刻意写成 `VSCode 1.107.1 (TRAE SOLO CN)`，与安装包版本一致，说明服务侧存在 App 版本耦合。

**与「必须打开 App 才能调用」假设的关系**：外部证据不支持 D2（社区代理明确「不需要 GUI 活跃」），但支持 **D3**：登录态与设备身份串属客户端离线产物，且服务侧校验真实性（伪造被拒）。本仓走的是自造 `machine_id`/`device_id` + 自办 OAuth 回调（`protocol.py:160-174`、`docs/research/20-….md:130`），与社区「必须真实串」的实证存在张力。

**未确定项**：① 自造设备串对**推理**通道是否被拒（社区结论只覆盖签到 claim）；② 官方从未公开 token 期限，14d/180d 是二手；③ 2-3 台上限是否按 `device_id` 计数（若是，多账号并行=每台号各占一号设备位，会撞上限）。

## 2. cline

**外部证据摘录**
- 官方 API 文档《Authentication》：「Every request to the Cline API requires authentication via a Bearer token in the Authorization header」；Base URL `https://api.cline.bot/api/v1`，端点含 `/api/v1/chat/completions`；Key 在 app.cline.bot「Settings → API Keys → Create a new key. Copy it immediately…」；吊销「stop working immediately」；建议「Rotate keys periodically」——**未提及任何过期时间表、设备绑定、或必须有扩展/进程在跑**（https://docs.cline.bot/api/authentication）。
- 官方《API Overview》：「The Cline API is an OpenAI-compatible Chat Completions endpoint」，并有企业管理端点（users/organizations/billing/API keys）（https://docs.cline.bot/api/overview）。
- 官方《CLI Overview》：「Run Cline in your terminal with interactive chat or fully headless automation for CI/CD and scripting」——Cline 官方支持无 GUI 形态（https://docs.cline.bot/usage/cli-overview）。
- 官方《Cline (usage-billing)》：「sign in once with Google, GitHub, or email」，定位为托管计费 provider（https://docs.cline.bot/getting-started/cline-provider）。
- 二手中文实证（2026-07-30）：控制台确有 API Keys 页，「接口格式兼容 OpenAI」，并列出免费模型 `minimax-m3` / `mimo-v2.5` / `deepseek-v4-flash`（https://www.xmsumi.com/detail/3898）。

**与假设的关系**：**否证「必须开 App」**。`api.cline.bot` 是厂商自己对外营业的 HTTP API（Key 即凭证），与「IDE 扩展宿主」解耦 ⇒ D1（首登录要浏览器）而非 D2/D3。

**未确定项**：① 本仓用的是 WorkOS 设备码 token（带 `workos:` 前缀，`docs/research/20-….md:419`），与 dashboard 签发的 API Key 是否同一权益集合（尤其**免费模型集合**是否只对 `recommended-models` 的 token 开放）；② 官方对并发/多机同 Key 无任何条款 ⇒ C 类只能是「未验证」；③ 非流式 `{success,data}` 信封（本仓已实网抓修）在官方文档中**无记载**，属未文档化行为。

## 3. loomy

**外部证据摘录**
- 官方帮助中心（loomy.xunfei.cn/docs）栏目=开始使用/用户指南/技能广场/安全须知/常见问题；自定义模型答复「可以。…你可以在 Loomy 中自行配置 API Key 进行使用」，并强调「文件操作默认在本地完成」——**只有 BYOK，没有内置模型的对外 API**（https://loomy.xunfei.cn/docs/）。
- 第三方收录（2026-08-20）：「Loomy 是科大讯飞推出的桌面级 AI 工作搭子」「下载 Windows 或 macOS 客户端并完成安装」「每天免费5000积分！」——**无网页版、无 API 接口说明**（https://ai-bot.cn/sites/73695.html）。每日 5000 与本仓观测到的 `dailyQuota=5000` 相互印证（`docs/research/20-….md:240`）。
- 本仓代码事实（外部无对应文档）：`upstream/loomy/sign.py:1-16` 逐字节复刻客户端 `electron/xfyun/sign.js` 的 9 段 HMAC-SHA1 签名，认证头前缀为 `account {ak}:{sig}` 而非 Bearer，且 body 只能序列化一次。
- 讯飞开放平台（xfyun.cn）公开 API 采用签名鉴权体系，但那是**另一套产品**（语音/星火开放 API），与 `loomyad.xunfei.cn` 的 Loomy 内部通道无文档关联 ⇒ 不可当作同一条通道的证据。

**与假设的关系**：支持 **D3**（要客户端产物：签名算法 + CAccount 凭证），不支持 D2（无任何材料说调用时客户端必须活着）。账号宿主 `account.xfrfr.com`/`xfinfr.com` 与 `loomyad.xunfei.cn` 在公开材料中**完全无记载**。

**未确定项**：① AK/SK 能否在非桌面途径取得；② 官方未披露 token 生命周期，本仓判「不可续期」——若为真，凭证寿命是唯一硬约束，必须靠实测确认；③ 并发/多设备：外部零证据。

## 4. raccoon

**外部证据摘录**
- 2026-08-25 商汤产品稿：小浣熊「支持『桌面端』、『网页端』、『iOS 手机端』」，另有行业版与「企业私有化部署／软硬件一体机」（http://m.10jqka.com.cn/20260825/c679265019.shtml）。
- 官方新闻稿《商汤小浣熊移动端正式上线》：「跨屏协同，指令不间断」「手机发指令，电脑持续执行。离开工位，工作不中断」——同一账号跨端并存是**官方正面卖点**（https://www.sensetime.com/cn/news/raccoon-work-app）。
- 使用指南类二手（2026-09-12）：「产品支持桌面、网页、移动端及私有化部署」，且「个人使用免费，注册 code.sense time.com 账号即可」，未见任何开放接口或 API Key 说明（https://blog.csdn.net/PHTR1/article/details/165124483）。注意：该文混写了旧「代码小浣熊」IDE 插件与新 RaccoonWork，**不可**把插件形态当作内部模型通道证据。
- 本仓取证：端点前缀 `/api/web/llm/v2`、`/api/web/points/v1`、`/api/web/desktop/v1`；登录奖励端点必需 `X-Client-Platform`（`docs/research/20-….md:330`）；每日 300 积分「服务端按日自动发放」，无签到端点（`:330`）；另有独立的桌面设备身份模块（`raccoon-product.ts:110-118` 语义，`docs/research/20-….md:117`）。

**与假设的关系**：`/api/web/*` 前缀 + 官方「网页端」支持 ⇒ 通道属 **web 会话**，浏览器即可完成登录，不需桌面进程 ⇒ **D1**；但「桌面端设备身份」字段若被推理通道校验，则应升 D3。

**未确定项**：① 网页端是否有登录/风控差异（扫码 vs 短信）；② 多账号并行既无官方条款也无社区实证 ⇒ C3（另一维度 C0）；③ 官方从未披露 token/refresh 策略，本仓「可续期（lead 窗口）」属代码事实。

## 5. zcode（含 405/3012 专题）

**外部权威证据**
- 官方《ZCode 用户协议》：「您的ZCode账户仅限您本人使用。未经ZCode同意，您直接或间接授权第三方使用您ZCode账户…的行为无效」「如有证据证明或ZCode根据相关规则判断您存在**不当注册或不当使用多个ZCode账户**的情形，ZCode可采取冻结或关闭账户、拒绝提供服务等措施」「通过深度链接、页面抓取、社交机器人、蜘蛛或其他**自动化的方式**使用本服务…对ZCode的任何算法、源代码、机制等进行**反向工程**…不得以任何方式绕开或规避…的安全措施」「您注册/登录并使用ZCode即视为您明确授权ZCode访问并操作您的本地设备环境」（https://zcode.z.ai/cn/terms）。
- 官方 FAQ：「登录凭据按设备加密，换机后无法解密，直接在新机器重新登录即可」；「已购 GLM Coding Plan，用 API Key 接入 Coding 场景」与「开放平台模型资源包 / 充值余额，走 OpenAI 兼容协议」被列为**两条独立计费通道**，「无法正常消耗编程套餐额度」（https://zcode.z.ai/cn/docs/qa）。
- 官方文档首页：「绑定 BigModel 或 Z.ai 账号，使用 GLM-5.3、GLM-5.3-Flash 等内置模型」；闲时任务「全程不消耗套餐额度」（与 `docs/research/20-….md:104` 的 `offPeak.allowed_models` 同向）（https://zcode.z.ai/cn/docs/welcome）。
- 开放平台侧：官方 Coding Plan 提供 Anthropic 兼容 Base URL `https://api.z.ai/api/anthropic` 与 `…/api/coding/paas/v4`，凭 Key 来自 Z.AI 控制台；限流表现为 HTTP 429 / 错误码 1302、1305（https://docs.openclaw.ai/zh-CN/providers/zai）；违规判罚见「The GLM Coding Plan is designed specifically for Coding Scenarios」「Violating the Usage Rules three or more times will result in an account ban」，策略码 1302/1303/1113（https://awesomeagents.ai/news/zai-coding-plan-bans-non-coding-use/）。
- 智谱已于 2026-09 开源 ZCode（`https://github.com/zai-org/ZCode`，Monorepo：Electron 桌面 + 浏览器前端+本地服务 + 独立终端 TUI/Agent CLI；「两种模式都在本机运行，无需 Electron」；本地服务用 `ZCODE_SERVER_AUTH_TOKEN`）——**官方自己承认终端形态可脱离桌面 GUI 运行**（https://news.qiniu.com/archives/1789970579947、README）。

**本地取证（只读，2026-10-02，`rg -a` 串取 `/Applications/ZCode.app/Contents/Resources/app.asar`）**
- 通道构造：`buildZCodeEndpointUrls` → `zcodePlanOpenAiBaseUrl: ${o}/api/v1/zcode-plan`、`zcodePlanAnthropicBaseUrl: ${o}/api/v1/zcode-plan/anthropic`、`…/billing/current`、`…/billing/balance`（与 AGENTS/本仓记载一致）。
- 验证码是**请求级**注入：`runtimeProviderHeaders` 逐条落到 `X-Aliyun-Captcha-Verify-Param` / `X-Aliyun-Captcha-Verify-Region`；另有 `aliyun_captcha_verification`、结果判据 `traceless_passed`（无痕验证）。
- `POST /api/v1/zcode-plan/billing/claim` 需 `Authorization: Bearer <n>` + 两个 captcha 头 + `X-ZCode-App-Version` + `X-Platform`。
- 客户端预置里同时存在 `/coding/paas/v4`（openai-compatible）与 `/api/anthropic` 两条**开放平台**通道路由 ⇒ 官方自己就把「Plan 内部通道」和「开放平台 API」分开处理。
- 字符串计数：`zcode-plan` 23 / `app-server` 7 / `X-Device-Mid` 7 / `Aliyun-Captcha` 6 / `ZCODE_BUILTIN_PROVIDER_CONFIG_FILE` 2。

**405/3012 的公开成因**：**无权威文档**。全网检索（中英、含 `"zcode-plan/anthropic"` 精确匹配）只找到本仓 `docs/research/23-….md:22,174,184` 转述的第三方项目作者自述（「直连即使带合法验证码参数也被 405/3012 拦，verified 2026-09-26」），以及 `docs/research/24-….md:89-97` 登记的未裁决 D1。可信的机制旁证有三条：① 官方 ToS 明禁自动化/绕安全措施（策略性动因）；② 请求级阿里云无痕验证码 + 官方身份头（说明通道被设计为「只有能跑 captcha SDK 的 webview/宿主才可用」）；③ Coding Plan 侧存在 1302/1303/1113 的策略拦截体系（同厂商风控风格）。**TLS/UA 指纹假说没有任何公开证据**——Trae 侧倒有一条相反旁证（默认 Python UA 会被 WAF 拒，说明这类厂商确实用 UA/WAF 层，但对 zcode 无实证）。

**与假设的关系**：官方开源 CLI「无需 Electron」+ asar 里可独立 `app-server` 的事实，**削弱 D2**（不必桌面 GUI 进程）；每请求 captcha 产物 + 设备绑定凭据 + 版本头**支持 D3**；「直连是否恒被拦」缺权威证据 ⇒ 该子问题维持 **D4**。

## 6. 仅凭外部权威无法定论、只能靠代码/实测的格子

1. **trae**：自造 `machine_id`/`device_id`（本仓路径）能否过**推理**通道校验（社区只证签到 claim 拒伪造串）；2-3 台上限是否按 device 头计数；官方无 token 寿命文档。
2. **cline**：设备码 token 与 dashboard API Key 的**权益集合是否同一**（尤其免费模型）；并发/多机同 Key 行为；非流式 `{success,data}` 信封未文档化。
3. **loomy**：签名所需 AK/SK 的取得途径是否只能来自客户端；「不可续期」是否属实（官方对凭据生命周期零披露）。
4. **raccoon**：`/api/web/llm/v2` 是否校验桌面下发的设备身份（决定 D1 vs D3）；同账号多端并存是否对**并发请求**有限流；每日积分自动发放的权威说明缺失。
5. **zcode**：**405/3012 的真实成因**（TLS/UA 指纹 vs captcha 场景绑定 vs 要求 Plan 订阅态）只能靠带/不带 captcha 的最小实测裁决；官方 Start/ZCode Plan 与 Coding Plan 的额度边界；同账号多会话并存行为（FAQ 只讲凭据设备加密，不讲并发）。

## 7. 我预测会与代码角色分歧的格子及原因

1. **trae（D 类）**：我判 D3，代码角色大概率报 D1/D0——因为本仓自己做 OAuth、自己 `new_machine_id()` 造 32hex、并用 `derive_device_id15(uid)` 派生签到身份（`protocol.py:122,160-174,202`）。分歧根因：**「插件跑通了签到」≠「推理通道接受合成设备串」**；若代码侧只有签到/额度实测而无推理实测，D3 应保留为保守判定。
2. **zcode（D 类）**：我拆成「机制 D3 + 405/3012 属 D4」，而代码角色可能直接报 D2（因 `docs/research/23` 的第三方桥方案要 spawn 官方宿主）或报 D0（因本仓 `captcha.py` 已能用 Playwright 自 mint）。分歧根因：第三方「必须官方宿主」的结论**未经我们复验**，而我方 Playwright 路线**尚未真实发过上游请求**；两边都在猜，必须靠 M4-3 最小实测裁决（`docs/research/24-….md:89-97` 选项 A）。
3. **raccoon（D 类）**：我按官方「网页端」+`/api/web/` 前缀判 D1，代码角色若盯着 `desktopDeviceIdentity` 可能报 D3。分歧根因：本仓未证明该桌面身份参与**推理**请求（仅证明 `X-Client-Platform` 参与登录奖励端点）。
4. **cline（Q2 的「官方通道」认定）**：我会把「`api.cline.bot` 是厂商对外营业 API」当作否证「必须开 App」的决定性证据；代码角色若只用设备码 token，可能坚持「这就是扩展私有通道」而报 D2/D3。分歧根因：**同一 host 上的两类凭证（Key vs token）能力面不同**，需要各自实测一次才算定论。
5. **loomy（C 类）**：外部完全无证据（C3），代码角色可能把「余额分档选号成功 / 无 429」误读为 C0 并存无限制。分歧根因：DSH 侧的多账号轮转成功只证明**没被拦**，不证明厂商**允许**；官方条款空缺处一律记 C3。
