# 25 · 无 App 依赖与多账号并行：真实运行取证（实证探针）

- 时间：2026-10-02 13:35—13:45（本地）；网关 = 127.0.0.1:8300（pid 38665，Thu Oct 1 07:42:26 起，未重启 · 未改任何文件 · 未启停任何 App）
- 任务：证明/否定「不打开厂商桌面 App，网关也能用本地账号凭据调用其内部模型」+「同产品多账号能否并行」
- 上游调用总量 ≈ **23 次**（1 次 cline 首发厂商 500 被网关重试 ×2；catalog 7 次含 1 次 401；probe 14 次；资源连通测试 3 次全部在网关侧 400 拒发 = 0 上游）
- 归因口径：**(a) 网关自拦**（fail-closed 门 / 未映射，请求没出去）｜**(b) 厂商拒绝**（请求真出去并拿到 4xx/5xx）｜**(c) 成功**
- 如实记录：`data/config.yaml` 在本轮窗口内被**并行会话**于 13:45 重写（本探针全程只读，未写任何项目文件）；
  交付前复核终态仍为 `models 19 / resources 36 / /v1/models 17 条`、横幅仍是
  `model_without_resource` + `resource_without_model` 两条 ⇒ 本报告结论不受影响。

## 1 · 实测判定表

| 产品 | App 此刻是否运行（证据） | /v1/models 含该产品服务模型 | 单次调用结果（状态码+耗时+一句话） | 失败归因 | 多账号并行（2 并发） | 凭据形态与时效（只字段名） | 无头可调用? |
|---|---|---|---|---|---|---|---|
| buddy | **未运行**（`CodeBuddy CN.app/Contents/MacOS` 匹配 0，前/后各采一次） | 否（资源 res-eee3b1e1 未被任何系统模型引用） | catalog `GET` 200 / 0.152s，16 条实时目录；probe 200 / 0.313s `valid:true` | 推理=**(a)** 未映射；凭据/目录=**(c)** | **2/2 成功** 0.297s + 0.317s（两账号各一） | access_token / refresh_token / expires_at=1793440168000(2026-10-31 17:49) / refresh_expires_at=1796032167000(11-30) / token_type / domain / user_id；via=import | **凭据级：是**；推理级：未验证（(a)） |
| workbuddy | **主进程未运行**（`WorkBuddy AI.app/Contents/MacOS`=0，仅侧车 pid 84628 `tencent-docs-ai-engine` 起 2d04h；`WorkBuddy.app`=0） | 否 | catalog 200 / 1.142s，28 条；probe 200 / 0.649s `valid:true` | 同上 **(a)** | 未测（可补） | access_token / refresh_token / expires_at=1821589901000(**2027-09-22**) / refresh_expires_at 同值 / scope；via=import | **凭据级：是**；推理级：未验证（(a)） |
| lobsterai | **无 App**（/Applications 内无该产品桌面端；`Lobster` 匹配 0） | 否 | catalog 200 / 0.190s，30 条；probe 200 / 0.145s `valid:true` | **(a)** | 未测 | access_token / refresh_token / expires_at=1793274736000(10-29) / uid / first_keyfrom / latest_keyfrom；meta.json 带 `uuid`；via=import | **凭据级：是**；推理级：未验证（(a)） |
| qoder | **Qoder CN 运行中**（pid 6552，2d16h）；国际版 `api2.qoder.sh` 无对应 App（未装） | 否 | probe 200 / 0.832s `valid:true`（userinfo 200，**无需签名**）；catalog 0.0016s = 本地静态表 17 条（无网络） | 推理=**(a) 双门**：`SIGNER_FACTORY=None`（`upstream/qoder/out.py:64`，判据 `main.py:239`）+ 未映射 | 不适用（仅 1 账号） | security_oauth_token / access_token / refresh_token / expire_time=1793283810000(10-29) / refresh_token_expire_time=1821795810000(2027-09-21)；meta `machine_id`；via=import；quota=**exhausted** | **凭据级：是（仅 userinfo 面）**；推理级：否（(a) 签名未接线） |
| qodercn | **Qoder CN 运行中**（同上） | 否 | probe 200 / 0.117s valid；catalog 0.0017s 静态 14 条 | 推理=**(a)** 同 qoder（签名缝 + 未映射） | **2/2 成功** 0.109s + 0.147s（qodercn-78eb0339 / -83e4692c） | 同 qoder（expire_time=1793283701000，10-29）；meta `machine_id`；5 账号全 enabled、quota available | **凭据级：是**；推理级：否（(a)） |
| trae | **未运行**（`TRAE SOLO CN.app`=0、`Trae CN.app`=0） | 否 | catalog 200 / 0.674s，38 条实时；probe 200 / 0.163s valid（回 uid） | **(a)** 未映射 | 未测 | access_token / refresh_token / expires_at=1791892336347(10-13) / uid / enterprise_id；meta `machine_id`+`device_id`（registry `derive:true`）；via=import | **凭据级：是**；推理级：未验证（(a)） |
| cline | **未运行**（`Cursor.app`/`Visual Studio Code.app`/`Zed.app` 的 Contents/MacOS 均为 0） | **是**：10 条（claude-* / gpt-6-* / gpt-5.6-sol，走 res-231de13a） | `POST /v1/chat/completions` model=`claude-haiku-4-5` → **HTTP 200 / 1.399s**，content=`"OK"`，usage 13+4=17 tokens，provider=Anthropic，cost 3.3e-05 | **= (c) 成功**（真推理，无 App） ；另 `gpt-6-astra` → 503 包装厂商 500（Vercel `400 Invalid '…'）= **(b)** | 不适用（1 账号；且并发会撞同一 res） | access_token / refresh_token / expire_time=1790921479000(**2026-10-02 14:11**，实测时约剩 30min) / account_id / email；runtime.renew.attempted_at=13:11:19（已刷过一轮）；via=import | **是（推理级实测通过）** |
| loomy | **无 App**（`Loomy`=0，未装） | 否 | catalog 200 / 0.137s，8 条；probe 200 / 1.031s valid | **(a)** 未映射 | 未测 | access_token(32B) / userid / phone / nickname / expires_at=1791901963488(10-13)；**无 refresh_token**（registry `refresh:false`）；via=import | **凭据级：是**；推理级：未验证（(a)） |
| raccoon | **无 App**（`Raccoon`/`xiaohuanxiong`=0，未装） | 否 | probe → `valid:false`，detail「凭据已失效（**HTTP 401**），请重新登录」/ 0.114s；catalog 200 但 6 条 = **兜底表**（日志 `[raccoon] 模型目录 HTTP 401（回退兜底表）`） | **(b) 厂商拒绝 401**（非网关自拦；资源仍 enabled/active） | 未测（两账号同凭据态） | access_token / refresh_token / expires_at=1790846997000(**2026-10-01 17:29 已过期**) / user_id / phone；meta `device_id`；runtime.renew.terminal=「refresh_token 失效，HTTP 401／业务码 200003」；via=import | **否**（凭据已过期，厂商 401） |
| zcode | **运行中**：ZCode.app v3.14.4（主 pid 10909，Helper 11007/11009/11010/11019）+ zcode-switch(79680) + ZCode Panel(42194) | 否 | catalog 0.0022s 静态 2 条（GLM-5.3 / GLM-5.3-Flash，无网络）；并行 probe 两账号 `billing/balance` **200**（1.098s / 1.112s） | 推理=**(a) 双门**：`CAPTCHA_PROVIDER=None`（`upstream/zcode/out.py:78`）+ 未映射；D1（JWT 直连是否成立）**仍未裁决** | **2/2 成功** 1.098s + 1.112s（1179053284qqcom / 2632，无 429） | 密文态：`data/.zcode/v2/credentials.json` 键 `oauth:zai:access_token`、`zcodejwttoken`、`account-provider:…:api-key`、`web-remote-control:external-relay:pass_hash`（`enc:v1:` 前缀 = Electron safeStorage 密文，网关已能解出并用于 billing 调用）；meta.json `family/display_name/device_mid/via=import/imported_at`，**无过期字段** | **凭据级：是（billing 面 200）**；推理级：未验证（(a)，且 App 在跑 → 不构成无 App 对照） |

## 2 · 前置/后置状态（采集命令与关键原始输出）

```
# 进程（前 13:36 / 后 13:44 各一次；两次结论一致）
ps -Axo pid,etime,command | grep -vF "/bin/zsh -c" > snap
grep -cF 匹配数（0 = 未运行）：
  CodeBuddy CN.app/Contents/MacOS        0     WorkBuddy AI.app/Contents/MacOS  0   WorkBuddy.app/…  0
  TRAE SOLO CN.app/Contents/MacOS        0     Trae CN.app/Contents/MacOS       0
  Cursor.app/Contents/MacOS              0     Visual Studio Code.app/…         0   Zed.app/…  0
  Qoder CN.app/Contents/MacOS            4     ZCode（pid 10909，command 名 "ZCode"）在跑
  zcode-switch.app/Contents/MacOS        1     ZCode Panel.app/Contents/MacOS   1
  Lobster / Loomy / Raccoon / xiaohuanxiong / xunfei / copilot.tencent   全部 0（且 /Applications 内无对应 App）
残留侧车（如实记录，不构成本体运行）：
  84628 02-04:11:45 /Applications/WorkBuddy AI.app/Contents/Resources/app.asar.unpacked/node_modules/@tencent/tencent-docs-ai-engine/bin/darwin…
```

网关侧：

```
GET /v1/models（Bearer 接入密钥）→ count 17
  7× 商汤直连 + 10× cline（claude-fable-5-1…gpt-5.6-sol）  ← 其余 9 个产品 0 条
GET /admin/api/overview → warnings:
  {"kind":"model_without_resource","message":"2 个系统模型未配置任何资源…（glm-5.3、glm-5.3-flash）"}
  {"kind":"resource_without_model","message":"33 个资源未被任何系统模型引用（res-97a9c5d9、res-8b0c8a19、res-eee3b1e1、res-febed676、res-d426adca…）"}
  resources 运行态：36 条中 35 active / 1 disabled（res-1723268e = zcode-ef91d043）
GET /admin/api/accounts → counts {products:10, accounts:35, enabled:35, disabled:0}；10 产品 models_wired 均为 true
  ⚠️ `models_wired` 的真实含义 = 该产品 `_HOOKS` 是否提供可调用的 `list_models`
     （api/admin_accounts.py:218），**不是**「已接入服务集」——勿据此判定可服务。
data/config.yaml（api_key 一律不回显）：resources 36 条 = 1 直连（商汤）+ 35 产品资源
  产品资源 `api_key` 长度 0、`product`/`account_ref` 成对、`enabled:true`（仅 res-1723268e false）
  models 19 条，其中只有 cline 的 res-231de13a 与商汤 res-sensenova-main 被引用
```

网关自拦判据（源码，只读）：

```
core/resources.py:274  servable_models(config, registry)  —— /v1/models 唯一判据源
core/resources.py:271/348  ResourceRegistry.unservable_reason / ResourceManager.unservable_reason（注入缝）
main.py:239 _outbound_premise_gap：prod in (qoder,qodercn) 且 SIGNER_FACTORY is None → "qoder 签名未注入（WASM/COSY）"
                                  prod == zcode 且 CAPTCHA_PROVIDER is None → "zcode 验证码未注入"
upstream/qoder/out.py:64   SIGNER_FACTORY: … | None = None      ← 全仓无任何生产赋值点（grep 仅命中文档/判据）
upstream/zcode/out.py:78   CAPTCHA_PROVIDER: … | None = None    ← 同上
grep coding/data/gateway.log（本轮窗口 4MB 尾部）「兜底|回退|目录取不动|HTTP 4xx/5xx」→ 仅 1 条：
  [raccoon] 模型目录 HTTP 401（回退兜底表）
  ⇒ buddy/workbuddy/lobsterai/trae/loomy 五家同窗口无任何回退告警，其目录确为厂商实时返回
GET /admin/api/logs/requests?limit=400 → {"date":"20261002","total":0}（本轮之前今日无推理流量）
```

## 3 · 无头调用实测（原始输出摘录）

```
## 推理（唯一已映射的产品通路）##
POST /v1/chat/completions {"model":"gpt-6-astra","max_tokens":8,"stream":false,…}
  HTTP=503 time=3.247554s
  {"error":{"message":"[500] {\"error\":\"inference request failed: failed to invoke model
   'openai/gpt-6-astra' from Vercel: request failed with status 400: {\\\"error\\\":{\\\"message\\\":
   \\\"Invalid '；原因：无可用资源；已尝试：res-231de13a/openai/gpt-6-astra×2 …",
   "code":"NO_RESOURCE","system_model":"gpt-6-astra"}}      → 归因 (b) 厂商拒绝（鉴权已过，模型路由 400）
POST /v1/chat/completions {"model":"claude-haiku-4-5",…}
  HTTP=200 time=1.399390s
  {"choices":[{"finish_reason":"stop","message":{"content":"OK"}…}],
   "model":"claude-haiku-4-5","provider":"Anthropic",
   "usage":{"prompt_tokens":13,"completion_tokens":4,"total_tokens":17,
            "cost_details":{"upstream_inference_cost":3.3e-05}}}   → 归因 (c) 成功，且 Cursor/VS Code/Zed 均未运行

## 资源连通测试（期望走产品出站适配器）—— 三条全部未发出请求 ##
POST /admin/api/resources/test {"resource":"res-eee3b1e1","model":"deepseek-v4-flash"}
  HTTP=400 {"error":{"message":"该资源无可用出站适配器或 Key"}}    （workbuddy/lobsterai 同）
  根因（只读取证）：api/admin.py:411-415 要求 `key_values.get(rid)` 非空，
  而 main.py:396 `self.key_values = {r.id: r.api_key for r in config.resources}`，
  产品资源 api_key 恒为 ""（凭据住在 data/upstream/<p>/accounts/）⇒ **该产品资源在此端点上是死路径**

## 凭据/目录（真实厂商调用）##
GET  /admin/api/accounts/buddy/catalog      HTTP=200 0.152480s  source={'kind':'account','account':'buddy-00fdd61f'} 16 条
GET  /admin/api/accounts/workbuddy/catalog  HTTP=200 1.141830s  kind=account 28 条
GET  /admin/api/accounts/lobsterai/catalog  HTTP=200 0.189838s  kind=account 30 条
GET  /admin/api/accounts/trae/catalog       HTTP=200 0.674045s  kind=account 38 条
GET  /admin/api/accounts/loomy/catalog      HTTP=200 0.137257s  kind=account 8 条
GET  /admin/api/accounts/raccoon/catalog    HTTP=200 0.126546s  kind=account 6 条  ← 实为兜底（日志 401 回退）
POST /admin/api/accounts/buddy/buddy-00fdd61f/probe        200 0.312869s {"reachable":true,"valid":true,"ok":true,"detail":"凭据有效"}
POST /admin/api/accounts/workbuddy/workbuddy-0f003108/probe 200 0.649121s valid:true
POST /admin/api/accounts/lobsterai/lobsterai-4e51cb1a/probe 200 0.144892s "profile-summary 正常"
POST /admin/api/accounts/trae/trae-1274402e/probe           200 0.163430s "凭据有效（uid …）"
POST /admin/api/accounts/loomy/loomy-a06ba956/probe         200 1.030720s valid:true
POST /admin/api/accounts/raccoon/raccoon-7aeade53/probe     200 0.113663s {"valid":false,"detail":"凭据已失效（HTTP 401），请重新登录"}  ← (b)
POST /admin/api/accounts/qoder/qoder-eff2c221/probe         200 0.832464s "userinfo 返回 200"（无需签名）
POST /admin/api/accounts/qodercn/qodercn-78eb0339/probe     200 0.117318s "userinfo 返回 200"

## 多账号并行（同产品 2 并发，分别绑不同 account_ref 资源）##
buddy   ：res-eee3b1e1(buddy-00fdd61f) 200 0.297007s valid  ＋  res-febed676(buddy-a7f1c09f) 200 0.317336s valid
qodercn ：qodercn-78eb0339 200 0.109489s  ＋  qodercn-83e4692c 200 0.146747s
zcode   ：1179053284qqcom 200 1.097613s "billing/balance 200"  ＋  2632 200 1.111772s
（三组皆同时发起、双双返回，无 429 / 无风控码 / 无会话失效）
```

## 4 · 结论（逐条对应问题）

1. **无 App 依赖 = 成立（凭据面全线成立，推理面仅 cline 实测）**
   5 个产品（buddy / workbuddy / lobsterai / trae / loomy）在其桌面端**确认未运行/未安装**时，
   用本地明文凭据真实拿到厂商目录与探活 200；cline 更进一步——Cursor/VS Code/Zed 全未运行时
   **推理 HTTP 200 且内容正常**。⇒ 调用期不依赖 App 进程，厂商只认凭据 + 设备身份字段。
2. **qoder / qodercn / zcode 的推理不可用是网关自己拦的（(a)），不是厂商拒绝（(b)）**
   `SIGNER_FACTORY`/`CAPTCHA_PROVIDER` 全仓无生产赋值点（`upstream/qoder/out.py:64`、`upstream/zcode/out.py:78`），
   判据 `main.py:239` 把其映射排除出 `/v1/models`；同时这三家 probe/userinfo/billing 均 200，
   说明**厂商侧接受凭据**，缺的是网关侧签名/验证码通道。zcode 的 D1（JWT 直连是否成立）仍未裁决。
   ⚠️ 另注意 zcode 与 qodercn 本轮 **App 正在运行**，其 200 不构成"无 App"对照证据（对照证据来自 buddy/workbuddy/lobsterai/trae/loomy/cline）。
3. **除 cline 外没有任何产品的资源被系统模型引用**：33 条资源 `resource_without_model`（overview 横幅）
   ⇒ 9 个产品的「推理」通路在网关侧尚未接线，属 (a)。推理级无头实测目前只有 cline 一格是绿的。
4. **多账号并行 = 厂商侧成立（3 产品 × 2 并发全绿）**；但**网关派发层并行尚未验证**：
   没有任何系统模型池里存在 ≥2 条资源（`max_active_per_model = 2`、`pick_and_acquire` 取 top-x 可用集，
   `core/resources.py:467-505`，设计与凭据并行能力匹配），要实测须先给某产品建映射（= 写 config，本轮禁止）。

## 5 · 发现的缺陷（主动报告，未擅自修改）

- **F-A 产品资源在 `/admin/api/resources/test` 上恒 400**（`api/admin.py:411-415` + `main.py:396`）：
  判据把「有 api_key」当成有适配器的前置，产品资源凭据不在 `api_key` 里 ⇒ 34 条产品资源无法用连通性测试验证。
  建议：`rid` 分支改为「product 资源不要求 key，只要求适配器存在」。**处理建议：改动很小但属行为变更，需用户裁决后再动。**
- **F-B catalog `source.kind='account'` 会在厂商 401 回退兜底表时谎报"来自账号 X 的实时目录"**
  （raccoon 实测：日志 `[raccoon] 模型目录 HTTP 401（回退兜底表）`，响应仍为 kind=account + 6 条兜底）。
  建议：`_catalog_models`（`api/admin_accounts.py:1247`）区分 `remote_ok` / `fallback`，否则界面把兜底表冒充实时目录。
- **F-C cline `gpt-6-astra` 的厂商 400 被压成 `NO_RESOURCE`/503 且错误串在 `Invalid '` 处截断**，
  重试 ×2 打同一 res-231de13a。归因不诚实（实际是厂商模型路由 400，不是"无可用资源"）。
  建议：非凭据类 5xx 包 4xx 保留原始上游状态码语义，并放宽错误摘要长度。

## 6 · 未验证项与原因 / 还缺什么实验

| 未验证 | 原因 | 定论所需实验 |
|---|---|---|
| buddy/workbuddy/lobsterai/trae/loomy/qoder/qodercn/raccoon/zcode 的**推理级**无头调用 | 这些产品资源未被任何系统模型引用（(a) 未接线），`/v1/chat/completions` 无入口；`resources/test` 又因 F-A 恒 400 | 二选一：①用户批准在界面为某产品建映射（写 config.yaml）后打 `/v1/chat/completions`；②修 F-A 后用 `resources/test` 打真实推理（各 1 次，约 5 次上游调用） |
| 网关**派发层**多账号并行（同一系统模型 top-x 两资源同时在途） | 无产品有 ≥2 条映射入池 | 建一条映射含两资源（如 buddy 两账号）→ 并发 2 请求 → 读 `/admin/api/overview` 的 `in_flight`/`C` |
| zcode 直连推理（D1） | `CAPTCHA_PROVIDER=None`，且 ZCode.app 正在运行，不构成无 App 对照 | 用户裁决 D1 + 批准临时退出 ZCode.app/ZCode Panel/zcode-switch 三进程后做对照实验（**本轮一律未执行，需明确批准**） |
| qoder/qodercn 签名通道可行性 | `SIGNER_FACTORY=None`（WASM/COSY 未移植，PRD 记为开放项） | 需先做签名移植或注入测试 signer；本轮只证明 userinfo 面无需签名 |
| raccoon 恢复后是否可无头调用 | 凭据已过期（expires_at 2026-10-01 17:29）且 refresh 已终态失效，需用户重新登录 | 重新登录 → 重复第 3 节 catalog/probe 两步 |
| 「App 曾运行过所以凭据已被保活」这一混淆因素 | 无法回溯历史进程状态 | 对照实验：完全退出某 App 并等待 N 小时后再打一次（需用户批准退出 App） |

需要用户批准的动作（均未执行）：①为某产品/某系统模型建立映射（写 `data/config.yaml`）；②临时退出 ZCode.app + ZCode Panel + zcode-switch 做无 App 对照；③修 F-A/F-B/F-C 三条缺陷。
