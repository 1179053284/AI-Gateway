# Batch A 代码取证：五产品「桌面端依赖 / 多账号并行」判定（代码分析专家）

范围 = 只读 `/Users/w/Desktop/Model-Gateway/coding/model_gateway/`（`upstream/<product>/` + `accounts/` + `adapters/` + `core/` + `ops/`）与 `coding/data/upstream/<p>/accounts/*/*.json` 的**键名**。
方法 = 纯代码取证，不发真实上游调用、不启动任何 App。凡本仓代码推不出的一律写「未验证」。
D 类 = App 依赖性质（D0 无依赖 / D1 仅首登录 / D2 调用期需进程 / D3 需离线产物 / D4 未知或被拦）；C 类 = 多账号并行（C0 无干扰 / C1 需每账号设备身份唯一 / C2 互踢或同账号并发限 / C3 未知）。

## 一、逐产品判定表

| 产品 | D 类 | App 依赖机制(一句话) | 鉴权材料形态 | 无头刷新可否 | 调用期还须构造什么 | C 类 | 多账号并行阻碍点 | 关键证据(file:line) | 置信度 | 否证条件 |
|---|---|---|---|---|---|---|---|---|---|---|
| buddy | D1（登录在浏览器，非 App；调用期=D0） | external_link：网关取 authUrl→用户在浏览器授权→网关轮询 token；此后纯 HTTP+本地凭据 | `Authorization: Bearer <access_token>`（本地 credentials.json） | 可（`POST /v2/plugin/auth/token/refresh`，带 X-Refresh-Token） | 8 个身份/归因头 + 固定 UA；无设备字段、无签名、无时间戳 | C0 | 无（产品无设备身份 → 唯一性门形同虚设；资源/调度均无账号级锁） | `coding/model_gateway/upstream/buddy/hooks.py:75-169,174-219`；`upstream/buddy/out.py:45-63`；`accounts/registry.py:62-74` | 高 | 实测发现腾讯要求访问侧 IP/指纹或 refresh 需活 Bearer 被拒 |
| workbuddy | D1（同 buddy，共用实现） | 同上（国际版域名/平台标识不同） | 同上 | 可（同一 refresh 实现） | 同上，取值换 WorkBuddy/5.5.2 族；无设备字段 | C0 | 无 | `upstream/workbuddy/product.py:98-106,168-175`；`upstream/buddy/protocol.py:235-238,307-319`；`accounts/registry.py:77-88` | 高 | 同 buddy；另国际版促销/目录差异不影响调用面 |
| lobsterai | D1（浏览器门户登录 + 网关自起回环接收端；调用期=D0） | 登录需浏览器完成授权，回跳落**网关自己**绑的 127.0.0.1 随机端口（非厂商端口） | `Authorization: Bearer <access_token>`；refresh 只认请求体 `refreshToken`（无 Authorization） | 可（`POST /api/auth/refresh`，匿名头） | UA `LobsterAI/0.1.0` + `X-LobsterAI-Client-Capabilities` + `-Client-Version`；`stream` 恒 true；chat **不发** uuid | C1 | 网关侧 uuid 唯一性拦导入（不拦登录）；chat 面上游看不到 uuid | `upstream/lobsterai/out.py:43,47-71`；`protocol.py:224-244,280-283`；`login.py:276-316`；`product.py:204-210`；`accounts/registry.py:105-114` | 高 | 实测服务端按 uuid 关联会话/踢线，或拒绝缺 uuid 的 refresh |
| qoder | **D4（调用期实际不可发）+ D3（按取证需客户端 WASM 产物）** | 推理端点只认加密+COSY 签名请求；本仓未移植签名器 → 当场 fail-closed，模型连 `/v1/models` 都不出 | 控制面 Bearer(`security_oauth_token`→`access_token`)；**推理面无任何由本仓构造的鉴权**（url/headers/body 全由签名器产出） | 可（控制面 `POST /api/v1/deviceToken/refresh`，body=refresh_token+machine_id） | 控制面 `/sash/` 需 `Cosy-ClientType:10` + **从桌面端数据目录读的** `Cosy-MachineToken/-MachineType`（成对，缺则降级）；推理需 WASM 加密体 | C1（现状 C0，因签名未接线） | machine_id 唯一性拦导入；两站串用护栏 `family` 标记对导入凭据不生效 | `upstream/qoder/out.py:8-10,64,110-116,120-141`；`main.py:239-275,312,505-511`；`upstream/qoder/flow.py:233-297,448-483`；`accounts/registry.py:118-130` | 高（对「本仓发不出」）/ 低（对「厂商真实要求什么」） | 实测证明存在不需签名的可用推理端点，或签名器注入后仅需 Bearer |
| qodercn | 同 qoder（D4+D3），CN 域名/ clientId 全不同 | 同上；CN 公开端点实测 503（本仓只登记取证值） | 同 qoder（CN openApi 基址） | 可（同 refresh 实现挂 `openapi.qoder.com.cn`） | 同 qoder；machine_token.json 读的是 `Qoder CN` 目录 | C1（现状同上） | 同 qoder；且 `family` 缺失时护栏不拦（可能串站） | `upstream/qodercn/product.py:40,68-74,97-107`；`upstream/qoder/config.py:251-265`；`flow.py:500-511`；`accounts/registry.py:132-143` | 高/低同 qoder | 同 qoder |

## 二、buddy（CodeBuddy，腾讯）

**证据链**
1. 鉴权材料与读处：出站基类 `adapters/product_out.py:104` `store.load_credentials(product, account_ref)` → `accounts/store.py:477-497` 读 `data/upstream/buddy/accounts/<名>/credentials.json`（明文，铁律 1）。头构造 `upstream/buddy/protocol.py:256-292`，第 281 行 `Authorization: Bearer {access_token_of(cred)}`；`access_token_of` = 读 `access_token` 键（`protocol.py:391-393`）。凭据缺失 → `out.py:58-61` 抛 `UpstreamError`（fail closed，不发空 Bearer）。
2. 除凭据外构造的东西（推理面，`protocol.py:256-292` + `out.py:62-63`）：`X-Domain`（实际请求基址主机名）、`X-Product-Code=codebuddy`、`X-Agent-Purpose=conversation`、`X-IDE-Name/X-IDE-Type/X-Product=CodeBuddy`、`X-IDE-Version=1.106.1`（`protocol.py:235-238`）、`User-Agent=CodeBuddyIDE/1.106.1`（`upstream/buddy/product.py:93`）、`Accept`/`Content-Type`。**没有**设备字段（`out.py:57` `del meta, device`；`accounts/registry.py:70` `device=_NO_DEVICE`）、没有签名/HMAC/时间戳、没有私有信封（标准 OpenAI 请求体 + `/v2/chat/completions`，`out.py:39`）。传输是普通 `httpx`（`adapters/openai_out.py:61-63`），curl_cffi/TLS 指纹只服务 zcode（`upstream/zcode/auth.py:83-101`）。
3. 有无「厂商进程存在」假设：**没有**。全仓 `127.0.0.1/localhost` 命中（`accounts/callback_server.py:64`、`upstream/trae|lobsterai|zcode` 各文件、`core/local_admin.py:41`、`api/admin.py:54`）**全部指向网关自身**（CLI 自调回环管理面 / 为登录回跳自绑的接收端），**没有一处连接厂商 App 的本地端口或 IPC**；其中回跳监听只在 `local_callback` 型或显式声明 `_CALLBACK` 表的产品上才建（`accounts/login.py:380`）。buddy 是 external_link 型，`upstream/buddy/product.py` **未声明** `_CALLBACK`，且 `hooks.py:423-431` 的 `login_callback` 直接 `NotImplementedError`（无本机回跳通道）。
4. 无头刷新：`hooks.py:174-219` 真发 `POST /v2/plugin/auth/token/refresh`，头 `protocol.py:307-319`（Bearer + `X-Refresh-Token` + `X-Auth-Refresh-Source=ide-main`）。无 `refresh_token` → `NotRefreshable`（183-186）；401/403 或文案含 expired/invalid → 终态（196-199）；网络/5xx → 普通异常可重试。定时腿 `ops/builtin/auto_renew.py:96-132`（能力位 refresh=True，`registry.py:72`），失效前 2h 自动续（`auto_renew.py:43`）。**注意风险点**：请求头同时带**可能已过期的** access_token 作 Bearer（`hooks.py:190`→`protocol.py:313-319`），服务端是否接受过期 Bearer = 未验证。
5. 专项（WASM 签名）= 不适用（本产品推理面为公开 OpenAI 兼容端点，本仓自构全部请求头）。
6. 多账号并行：N 账号 → N 条 Resource（`accounts/materialize.py:102-112`，一账号一行、幂等）；`core/resources.py:467-501` 同一 system_model 的池内按 in_flight 最少选路，生效集 = top-x（`:492`，x 默认 2，`config/schemas.py:115`），故障切换用 exclude 越出生效集；无账号级互斥/串行锁（全仓 `core/` 无 `asyncio.Lock`/`Semaphore` 用于资源）。设备唯一性门对 buddy 不成立（`accounts/device.py:123-124` 无字段即拒生成；`store.py:635-637` 无字段直接放行）。
7. 凭据字段（盘上实测键名，值全部 <redacted>）：`credentials.json` = access_token / refresh_token / expires_at / refresh_expires_at / token_type / scope / domain / user_id / nickname / enterprise_id / account_type（与 `protocol.py:510-530` 的 `build_credential` 逐键一致）；`meta.json` = created_at / updated_at / via(=import) / enabled。过期语义：`expires_at` 毫秒字符串（写入侧由 `expiresIn` 或 JWT `exp` 换算，`protocol.py:449-495`），`credexp.py:33` 认该键。

## 三、workbuddy（国际版）

与 buddy **共用同一份实现**（`upstream/workbuddy/product.py:29-30,116-131` 全部转调 `upstream/buddy/hooks.py`），差异只有 5 个参数值：platform=`workbuddy-ai`、product_code=`workbuddy`、UA=`WorkBuddy/5.5.2 WorkBuddy AI/5.5.2 CLI/5.5.2`、`append_session_params=True`（登录 URL 追加 `version`+`loginSessionId`，`protocol.py:533-550`）、兜底表 23 条（`product.py:42-91`）；基址 `https://www.workbuddy.ai`（`registry.py:83`）。归因头取值 WorkBuddy/5.5.2（`protocol.py:237`）。

逐条结论同 buddy：鉴权 `Bearer` + 本地凭据；无设备字段；无厂商进程假设；refresh=True 走同一 refresh 实现；C0（无设备身份、无账号级锁）。
差异两点：① 能力位 `checkin=False`（`registry.py:85`）→ `hooks.py:379-382` 直接返回 `inactive` 且**不发 HTTP**；② 其兜底表**来源**注明取自 IDE 本地缓存 `~/.workbuddy-ai/local_storage/*.info`（`product.py:35-41`）——这是**取证出处**，不是运行时依赖：`upstream/workbuddy/` 只有 1 个 py 文件、无任何读该目录的实现。⚠️ 但全仓**确实**有一处碰 `.workbuddy-ai`：`coding/model_gateway/setup_tools.py:37-71,127-189` 把网关系统模型写成 `~/.workbuddy-ai/models.json`（路径 A 文件下发；判据「WorkBuddy CLI 只读文件、不调 /v1/models」）——那是**下游消费方的接入面（写）**，方向相反，不构成调用上游内部模型的依赖。另注意**命名撞车**：`setup_tools.PRODUCTS` 的键 `workbuddy`/`workbuddy-ai` 指**被配置的工具**，与 `accounts/registry.py` 里作**上游厂商产品**的 `workbuddy` 不是同一物，跨角色讨论时易混。
凭据键名与 buddy 逐字相同（盘上实测，值 <redacted>）。

## 四、lobsterai（有道）

1. 鉴权材料：chat 面 `upstream/lobsterai/out.py:47-62` → `protocol.client_headers`（`protocol.py:235-244`）= `Bearer <access_token>`（`protocol.py:230`，读 credentials.json 的 `access_token`）+ Accept/Content-Type/UA。控制面 exchange/refresh 走 `anonymous_headers`（`protocol.py:218-221`，**无 Authorization**），续期凭据在请求体 `refreshToken`（`protocol.py:280-283`）。
2. 除凭据外的构造物：`User-Agent: LobsterAI/0.1.0`（`const.py:37`，刻意不跟真版本走）、`X-LobsterAI-Client-Capabilities: kimi-k3-agentic-v1,thinking-level-control-v1`（`const.py:42`；不带会少一个模型、`reasoning_effort:off` 会 500）、`X-LobsterAI-Client-Version`（同步钩子只能取进程内缓存或兜底 `2026.9.4`，`login.py:107-120`）。`prepare_body` 强制 `stream:true`（`out.py:64-71`，非流式走 SSE 聚合 `out.py:75-92`）。**推理面不带 uuid/keyfrom**（`out.py:51` `del meta, device`）。设备身份 uuid 与 keyfrom 时间戳只出现在控制面：exchange 请求体（`login.py:245-251`）、refresh 请求体与模型目录 query（`protocol.py:249-277` + `models.py:194-196`）。签到面还伪装客户端形态 `platform=win32`（`const.py:69-73`）。无签名/HMAC/TLS 指纹。
3. 厂商进程假设：**没有**。`redirect_uri = http://127.0.0.1:{随机端口}/auth/callback` 是**网关自己**的回跳接收端（`product.py:204-210` `_CALLBACK`，`callback_server.py:64,205` 只绑回环），门户只校验 URL **形状**、端口可随机（`login.py:151-178`）。注意 `login.py:125-148` 明确纠正过「网关 8300 端口不是接收端」的旧口径。
4. 无头刷新：`login.py:276-316` 真发 `POST /api/auth/refresh`；无 refresh_token / 401·403 / 命中会话终止标记（`const.py:85`：40100/40101/token rejected）→ `NotRefreshable`；成功后把 `expires_at` 回写 meta.json（315 行 + `protocol.py:501-524`）。依赖 `version`（`client_version()`，取不到用兜底常量，`login.py:86-104`）→ **不需 App、不需人工**。
5. 专项（WASM 签名）= 不适用（推理走 `API_BASE/api/proxy/v1/chat/completions` 公开路径，本仓自构全部头/体）。
6. 多账号：C1。身份字段 = `uuid`（`registry.py:110`）。**登录路径不拦第二个账号**（`login.py:181-197` `device.generate_unique` 每次生成新唯一值）；**导入路径会拦**（`store.py:696-699` → `plan_import_device` → `device.py:63-92` 任一身份字段相同即冲突并拒绝）。调度层无账号级并发上限（`resources.py:467-501`）。chat 面不发 uuid → 上游无法在推理时把两账号判为同一安装（此推论依赖「服务端不因其它信号关联」，**未验证**）。
⚠️ 附加发现（不占题号）：**本轮抓到的缺口，须报告，非猜测**：盘上 2 个 lobsterai 账号均 `via=import`，其 `credentials.json` **没有 `uuid`**（uuid 被 `store.py:709-711` 按 DeviceSpec 剥进 `meta.json`）；而 `protocol.keyfrom_body` 只从**凭据**读 uuid（`protocol.py:261-263`）。后果：导入号的 refresh 请求体与模型目录 query **不含 uuid**，与 `registry.py:96-104` 记载的「每次续期原样回传 uuid（服务端识别同一安装）」不符。登录路径造的号两处都有（`protocol.py:405` 写凭据 + `credential_meta` 写 meta），故该缺口只在导入号上成立。上游是否因此拒绝/降权 = 未验证，需实测角色覆盖。
7. 凭据字段（键名，值 <redacted>）：access_token / refresh_token / expires_at / uid / user_id / nickname / first_keyfrom / latest_keyfrom（+ 登录号才有的 uuid）。`meta.json`：created_at / updated_at / via / uuid。过期语义：`expires_at` = 毫秒字符串（`expiresIn` 相对当前时刻换算，缺则 JWT `exp`，`protocol.py:384-408`）；`credexp.py:33` 认 `expires_at`。access token 实测为 HS512 JWT、约 30 天（`protocol.py:363-381` 引 `main.go:317`，本仓不验签）。

## 五、qoder / 六、qodercn（两站同实现，差异全在 `upstream/qoder/config.py`）

1. 鉴权材料形态——**两面分说**：
   - 控制面（登录轮询 / 续期 / userinfo / 用量 / 活动）：`Bearer <token>`，取用顺序 `security_oauth_token` → `access_token`（`flow.py:221-228`，双写见 `flow.py:190-202`），来源同样是本地 credentials.json（`store.py:477-497`）。
   - **推理面**：本仓**从未**为它构造过鉴权。`upstream/qoder/out.py:120-141` 把「明文 ask → `{url, headers, body}`」整体交给外部签名器（契约见 `out.py:22-27`），`url`/`headers`/`body` 三项全由签名器给。所以「qoder 推理用 Bearer 还是信封字段」在本仓**不可判定**。
2. 控制面除凭据外的构造物（`flow.py:277-297` sash_headers）：`Cosy-ClientType: 10`（桌面 app 身份，`config.py:229-230`）、`User-Agent: Qoder`，以及成对的 `Cosy-MachineToken` / `Cosy-MachineType`——**这两个值由 `flow.py:256-274` 从厂商桌面端数据目录的 `machine_token.json` 读**（候选路径 `flow.py:233-253`：`~/Library/Application Support/Qoder{, CN}/SharedClientCache/cache/machine_token.json` 等，可用 env `QODER_MACHINE_TOKEN_PATH` 覆盖）。缺任一头 → 只带 ClientType（`flow.py:260-262,272-273`：两个值必须成对，缺一视为拿不到），消融取证表明不带这组头时 `/sash/…/campaigns` 恒回空（`flow.py:281-284`）。续期面另带 `User-Agent: qoder/1.0.0` + body `{refresh_token, machine_id}`（`flow.py:463-468`）。推理明文体的固定字段（`ask.py:194-240`）：`business={"type":"agent"}` **必填**（缺会被路由到故障节点，`ask.py:36-38,17-19`）、`chat_context.extra.modelConfig.key` = 目录 key（`ask.py:19-21`）、顶层 `tools` 恒在（`ask.py:22`）。无 HMAC/时间戳签名自实现，无 TLS 指纹。
3. 有无「App 进程在跑」的假设：**没有一处要求进程**。全仓唯一的「读厂商 App 产物」= 上面第 2 条的 `machine_token.json`（**D3 形态：只要文件不要进程**），且只服务 `/sash/` 额度与签到面，读不到时保守降级 + 提示（`flow.py:82` `_MACHINE_HEADER_NOTE`），不影响 chat 路径。DSH 的主路径是 spawn 桌面端 `runtime-info` 二进制，本仓**明确未实现**（`flow.py:236-239` TODO）→ 未验证。
4. 无头刷新：**可以**。`flow.py:448-483` 真发 `POST {open_api_base}/api/v1/deviceToken/refresh`，终态 401/403 或缺 token → `NotRefreshable`（471-473、481-482），网络/5xx → 可重试；`machine_id` 从 meta.json 或凭据任一处取（`flow.py:486-497`）——盘上 6 个 qoder/qodercn 导入号的 `machine_id` 都在 meta.json，取得到。`refresh` 前还有区域串用护栏（`flow.py:456`，`_guard_family` `flow.py:500-511`）。定时腿同 buddy（`auto_renew.py:96-132`）。
5. **Q5 专项：api2.qoder.sh 这条链路到底要不要签名？** 证据链逐跳：
   - 目录端点要签名：`accounts/registry.py:117` 注「远端目录端点需 WASM 签名，明确不实现」；`flow.py:824-861` 的 `list_models` **恒零网络**，只把静态表映射成 ModelInfo（`config.QODER_MODELS` 17 条 / `QODER_CN_MODELS` 14 条）；`flow.py:840-841` 明写「DSH 的 listModels 恒用静态表（远端目录需签名）」。
   - 推理端点**也**要签名（不只目录）：`out.py:8-10` 状态表把「请求加密与 COSY 签名」标 🔴 未移植，前两行（响应解包 / 明文构造）已实现；`envelope.py:10` 明确「内层 body **并未加密** —— 只有**请求**体需要 WASM 加密」；签名器要产出的是 `{url, headers, body}`（`out.py:52-58` SignedRequest；`out.py:14-16`：DSH 是调用客户端自带 WASM 的导出函数，非密码学破解）。
   - 端点不可替换：`config.py:223-226` 与 `registry.py:122-125`——公开端点 `api2-v2.qoder.sh` 只认通用名、发目录 key 回 `Unsupported model`；CN 公开端点实测 503（`config.py:259`、`registry.py:136-137`）。而本仓的模型 id 就是目录 key（`config.py:98-101`）。
   - 因此**本仓现在发不出有效的推理请求**：`out.py:64` 生产默认 `SIGNER_FACTORY = None`（全仓 grep 只有测试用 `monkeypatch` 注入：`tests/integration/test_qoder_out.py:131`、`test_qodercn_out.py:108`）→ `out.py:110-116` `_require_signer` 抛 `UpstreamError(NOT_WIRED_HINT, no_failover=True)`，`out.py:120-141` 在 `signer(...)` 之前，**一次上游请求都不发**。
   - 对外也不声明：装配侧 `main.py:264-267` 对 product∈{qoder,qodercn} 且 `SIGNER_FACTORY is None` 返回「qoder 签名未注入（WASM/COSY）」，经 `main.py:312,505-511` 注入 `ResourceManager.unservable_reason`，`core/resources.py:291-297` 的 `servable_models` 据此把这些模型从 `/v1/models` 与 `mgw setup` 隐藏（`config_warnings` ⑤ 给横幅，`main.py:727-737`）。
   - 判据钉在测试里：`tests/integration/test_qoder_out.py:320-328`（未注入签名器 → 503 + 文案含 WASM/SIGNER_FACTORY + `qoder_upstream.requests == []`）与 `tests/integration/test_m6_traffic_guards.py:323`。
   - **结论**：「签名只用于目录端点、推理不需要」这一乐观读法**在本仓代码里不成立**；但「厂商真实推理端点是否必须签名」只能由实测角色在注入签名器/抓包后定论 → 该格写 **D4（现状被拦，无法定论）**，D3 是按 DSH 取证的**最可能**性质（离线产物：WASM 导出函数）。
6. 多账号并行：C1（网关侧）。`machine_id` = 身份字段（`registry.py:126,139`）；登录生成走 `flow.py:427-438` `generate_unique`（uuid4 + 跨账号查重，不静默降级，`device.py:109-140`）→ 同产品 N 账号可各得唯一 machine_id、**不被拦下第二个**；导入路径带相同 machine_id 会被拒（`store.py:696-699`，须 `--reuse/--regenerate`）。调度面同 buddy（无账号级锁，只受 top-x=2 默认与额度预留 `resources.py:584-597` 影响）。次生风险两点：① `family` 标记只由本仓登录写入（`config.py:270-273`），盘上 6 个导入号**都没有该键** → `_guard_family`（`flow.py:500-511`「无标记不拦」）对导入号不生效，qoder/qodercn 凭据可互相接错资源而不报（实测面：`out.py:96-108` 也走同一判据）；② 上游侧「同一 uid 多设备/并发」行为本仓无任何取证 → 未验证。
7. 凭据字段（键名，值 <redacted>）：`credentials.json` = security_oauth_token / access_token / refresh_token / expire_time / refresh_token_expire_time / uid / nickname（+ 本仓登录号才有的 machine_id / family）。`meta.json` = created_at / updated_at / via(=import) / machine_id。时效语义要点：**qoder 系的过期键叫 `expire_time`**（毫秒，写入侧归一化，`flow.py:164-170`），`credexp.py:30-33` 专门为此把 `expire_time` 列进候选键，只认 `expires_at` 会让倒计时恒「未知」。另有 `refresh_token_expire_time`（刷新令牌自身寿命）。盘上导入号无 `machine_id`/`family` 于凭据本体的事实已在第 6 条使用。

## 七、我认为最可能与其他角色分歧的地方

1. **qoder 的 D 类**。我从代码得出「推理需要签名（不止目录）」，但**不等于**厂商要求「App 进程在跑」。若实测角色用抓包/注入签名器证明只需 Bearer + 明文即可打通推理，我这格（D4+D3）就应改成 D1/D0。反之若他们仅凭 `registry.py` 的注释判「目录才需要签名」，那与本仓 `out.py:8-10` 的表**直接冲突**——冲突点请以此二处 file:line 为准裁。
2. **buddy 的归因头是否必需**。`upstream/buddy/out.py:13-15` 记录「缺 `X-IDE-*` 族后台归因显示 `-`」是**归因**问题、不是**能否 200** 的问题；若实测发现腾讯按这组头做准入校验（缺即拒），D 类不变但「调用期还须构造什么」要升级为硬前提。
3. **lobsterai 的 uuid 缺口归因**。我判为「导入路径剥键」造成（`store.py:709-711` + `protocol.py:261-263`），属本仓缺陷；若另一角色在 :8300 实测到 refresh 带 uuid 成功，请核对该号是 `via=login` 还是 `via=import`（盘上现存两个号都是 import）。
4. **「无 App 假设」的口径**。我的判据是「全仓除网关自身回环监听外无任何本地端口/IPC 连接」（`callback_server.py:64` 只绑回环、`login.py:380` 才建监听），与「厂商服务端是否偷偷检查 App 在线」是两件事——后者本角色无法定论，不应被写成已排除。
5. **C 类的「C0 vs C1」**。设备唯一性是**网关自己**的写盘约束（`device.py:63-92`），不是上游观察到的事实。若实测角色主张「上游会按 uuid/machine_id 关联并互踢」，那是新的 C2 证据，我这格给不出。
6. **`setup_tools.py` 的 `workbuddy` ≠ `registry.py` 的 `workbuddy`**（命名撞车，见第三节 ②）。另一角色若把「往 `~/.workbuddy-ai/models.json` 写模型」读成「依赖 WorkBuddy App」，会把 D1 误判成 D3/D2；该写入是**网关→下游工具**的接入面，方向与上游调用相反。
7. **「有没有账号级串行」的口径**。我按「请求路径无任何锁」判 C0/C1：`core/` 与 `adapters/` 里 `Lock`/`Semaphore` 零命中（唯一两把在写侧：`materialize.py:64` `_ORDER_LOCK` 串行化「读配置→改→写」、`store.py::_AccountsWriteLock` 跨进程落盘锁），登录/续期写凭据不会阻塞在途 chat。若另一角色把「续期时 `commit_login` 持锁」当作运行期串行证据，结论会比我保守。

## 八、本角色无法定论、需要实测才能定论的地方

1. qoder/qodercn：推理端点对 COSY 签名的**真实**要求（是否含时间窗/一次性 nonce）；`api2-v2.qoder.sh` 用通用名是否真的可用；`machine_token.json` 陈旧值能否被 `/sash/` 接受（`flow.py:260-262` 说「可能陈旧但仍比不带强」，出处是 DSH 注释、非本仓实测）；CN 的 `session_type` 是否需 `qoder_work`（`ask.py:39-42` 明记「待实测」）。
2. buddy/workbuddy：access_token 过期后 refresh 是否仍被接受（第 2 节第 4 条的 Bearer 风险）；`X-Enterprise-Id`/`X-Tenant-Id` 对纯个人号的影响（`protocol.py:222-226` 有才发）。
3. lobsterai：不含 uuid 的 refresh / 模型目录请求的实际后果；`X-LobsterAI-Client-Version` 用兜底 `2026.9.4` 会不会被拒（`login.py:107-120` 的论据是「Go 侧长期发假值未被拒」，属转述）；`stream` 恒 true 的强制改写对非流式客户端的端到端正确性。
4. 多账号真并发：同一产品 N 账号在**真实上游**下同时打满是否有互踢/降速（本仓只有 in_flight 计数与冷却，`resources.py:467-501`）；以及默认 x=2（`config/schemas.py:115`）是否需要为多账号上调——这是**调度配置**问题，不是 App 依赖问题，但用户很可能把它误读成后者，需实测给出观感。
5. 全部五产品的凭据真实时效数值与续期窗口（本角色只看到字段名与语义，未见任何值，也未验证服务端 `refresh_token` 寿命）。
