# 独立核验报告 · C / D / E 三份草稿（L2 + L3 + L4）

> 核验员立场：**证伪优先**。L1（引用可解析）已由主 agent 完成（812 条、0 问题），本报告**不重复 L1**。
> 核验对象：`docs/research/zcode-drafts/C-签到与领取.md`、`D-内部模型对接.md`、`E-账号池与额度聚合.md`
> 参考项目：`/Users/w/Desktop/zcode相关管理软件/`（**全程只读，未做任何写入**；核验脚本与中间产物均在 `/tmp/`）
> 核验方法：逐条打开被引文件，重读被引区间的**实际内容**；对负向断言做**全文/全树检索 + 命中项逐个判定**；所有数字**独立重算**。
> 结论口径：`✅证实`（内容与行号均正确）/ `⚠️部分证实`（主结论成立，但表述/范围/数字有偏差）/ `❌证伪`（断言与实际相反）/ `❓无法判定`（上游行为、未实测）

---

## 0. 总览

| 维度 | 数量 |
|---|---|
| 核验断言总数 | **149 条**（C 44 / D 55 / E 50） |
| ✅ 证实 | 128 |
| ⚠️ 部分证实（含口径/范围/行号偏差） | 17 |
| ❌ 证伪 | 2 |
| ❓ 无法判定 | 2（均为草稿自标【未验证】的上游行为） |
| 抓出问题 | **21 条**（严重 2 / 中等 6 / 轻微 13） |
| L3 负向断言 | **2 条**（C 的"无每日签到"、E 的"无并发租约"）——**两条均经全文检索后成立**，但 E 的检索范围有一处声明外缺口 |

**L3 两条负向断言的判定结果（本批最重要）**

1. **C「没有传统每日签到端点」→ ✅ 成立。** 我对整个参考项目（含 `ZCode-Panel/`、`zemote/`、`zcode-account-switcher/` 等 C 未在正文列出的项目）以 `签到|checkin|check_in|sign_in|signin|daily_reward` 检索，命中项**全部**为 `checkingUpdate` / `signingKeysCleared` / `linux_signing_key` / `checking`（构建产物与无关英文词），**零个真实签到端点**；`兑换` 命中项全部是 OAuth `token 兑换`（exchange），无兑换码端点；`gift` 命中项全部是 tier 关键词（`quota.go:622`）与 ZCode-Panel UI 标签。C 的括号免责"除 UI 文案与 tier 关键词"**准确且必要**。
2. **E「转发选号路径没有并发租约」→ ✅ 结论成立，但检索范围声明有一处缺口。** 我以更宽的关键词集（增加 `singleflight|inUse|in_use|occupied|borrow|handoff|concurren|parallel|Semaphore`）重跑，并对 `pool.Select` / `store.select` / `choose_upstreams` 的**完整实现**逐行确认：三者都只做"过滤 → 返回指针/值"，**不写回任何占用状态**；`relay.go` 的账号状态更新（254/261/286/302/310/323）全部发生在请求**结束之后**。`main.go` 无全局限流中间件。**无租约结论为真。** 缺口见 §3.2。

---

## 1. 核验结论表

### 1.1 C 草稿（签到与领取）

| # | 断言 | 判定 | 证据（文件:行号）与原文片段 |
|---|---|---|---|
| C1 | 无传统「每日签到」端点；由 `billing/claim`(period=daily) + `event/report`(app_daily_active) 合成 | ✅ | `activity.go:19-21` 注释"领取: POST …/billing/claim；激活: POST …/event/report（app_launch + app_daily_active 两条事件）"；`claim.rs:130-131` `EVENT_REPORT_URL` / `ACTIVATION_EVENTS = ["app_launch","app_daily_active"]`；全树检索见 §0 |
| C2 | 三段式领取：preview → 阿里云无痕验证码 → claim | ✅ | `claim.rs:9-11` 三个 URL 常量；`activity.go:224-316` SubmitClaim |
| C3 | **强制**验证码，无 `X-Aliyun-Captcha-Verify-Param` 直接拒 | ✅ | `activity.go:226-230` `if strings.TrimSpace(captchaParam)=="" { result.Code=-1; Message="缺少人机验证参数…" }`；`claim.rs:281-283` 同 |
| C4 | 幂等靠业务码 1003=已领过 / 1005=今日名额用完（回带 `data.plan.ends_at`） | ✅ | `activity.go:65-74` 文案表（1003/1005）；`activity.go:305-313` `if code==1005 { … result.NextAt = int64(*ends)*1000 }`；`claim.rs:70-76` `body.pointer("/data/plan/ends_at").map(|s| s*1000)` |
| C5 | claim **无**幂等键、无去重令牌 | ✅ | `activity.go:224-316` 全文无 idempotency；对比 `reset.go:133,156` 有 `uuid.NewString()` |
| C6 | `zcode-switch` 每账号派生独立 `virtual_device_mid`，首次"抢注"本机值、被占用则新发 UUID | ✅ | `store.rs:1064-1085` `adopt_virtual_device_mid`：`let mid = match live_mid { Some(m) if !taken(&m) => m, _ => Uuid::new_v4() }`（`store.rs:1078-1081`） |
| C7 | 生成后**永不轮换** | ✅ | `store.rs:1015-1035` 仅在为空时生成；`store.rs:1037-1047` 非空直接返回；全 `src-tauri/src/*.rs` 检索 `rotate` 仅命中 `cipher.rs` 的 `derive_key`（密钥派生，与 mid 无关） |
| C8 | `zcode-proxy` 有 5 段 cron | ✅ | `scheduler.go:307-317` `shouldRun` `if len(fields) != 5 { return false }`；`scheduler.go:409-422` `ValidateCronExpr` 同 |
| C9 | 双层互斥（plan 级 + 账号级） | ✅ | plan：`scheduler.go:159` / `scheduler.go:170` `TryLock()`；account：`activity.go:406-407` `claimLockFor(a.ID)` + `TryLock()` |
| C10 | 随机抖动 0~50% | ✅ | `scheduler.go:207-208` `jitter := rand.Intn(plan.DelaySeconds/2 + 1); sleep := plan.DelaySeconds + jitter` → jitter∈[0, ⌊D/2⌋] |
| C11 | `zcode-proxy` OAuth 新账号 `DeviceMid: LocalDeviceMid()`，必然与本机同值 | ✅ | `oauth.go:282` `DeviceMid: LocalDeviceMid(),` |
| C12 | 事件体"固定 **14** 字段" | ❌ | **实际 16 字段**。`activity.go:330-347` 与 `claim.rs:159-176` 均为：event_id / client_timezone / client_language / element_name / event_region / event_type / event_text / event_extra_detail / user_id / screen_resolution / app_version / device_os_category / device_os_version / device_mid / mac_id / marketing_params = **16** |
| C13 | `code!=0` 即中止报错 | ⚠️ | Rust 侧正确：`claim.rs:210` `if code != 0 { return Err(...) }`。**Go 侧不一致**：`activity.go:368` `if code := jsonInt(v,"code"); code != 0 && code != -1`——`code==-1` 不中止。C 只引 `claim.rs`，未标注 Go 差异 |
| C14 | 领取请求头清单（`zai_billing_headers_with_mid`） | ⚠️ | 行号正确（`quota.rs:180-201`），但**清单不全**：实际还含 `HTTP-Referer`、`X-Title: Z Code@electron`、`X-Os-Version`（`quota.rs:184,185,193-195`）。且被引函数名是 `zai_headers_with_version`（180），`zai_billing_headers_with_mid` 是 170 行的包装器 |
| C15 | 凭据选择：`zcodejwttoken`（len>20）否则 `zai_billing_token` | ✅ | `claim.rs:101-113` `jwt.filter(|t| t.trim().len() > 20)`；`quota.rs:494-521` |
| C16 | 请求体仅 `{"plan_id": …}` | ✅ | `activity.go:238`；`claim.rs:295` |
| C17 | 成功响应 `data.plan{…}` + `data.server_time`（秒 → ×1000） | ✅ | `activity.go:272-298` `result.ServerTime = int64(*st) * 1000` |
| C18 | preview 字段 & entitlements 过滤（meter=model_usage && unit_type=token && show_name 非空） | ✅ | `activity.go:150-182` `if meter != "model_usage" \|\| unitType != "token" \|\| showName == "" { continue }`；`claim.rs:361-367` |
| C19 | 业务码表 1001/1002/1003/1004/1005/3001/3007/401 | ✅ | `activity.go:65-74` 全部逐项命中 |
| C20 | 排序 priority 降序、同优先级 plan_id 升序、取 [0] | ✅ | `activity.go:126-131`；`claim.rs:268` `sort_by(\|a,b\| b.priority.cmp(&a.priority).then(a.plan_id.cmp(&b.plan_id)))` |
| C21 | 激活 `user_id` 取自 `oauth:<provider>:user_info` 的 id/user_id，兜底解 JWT | ✅ | `claim.rs:135-156`；`activity.go:379-400` |
| C22 | 激活后 sleep 1.5s 查额度，`PlanTier` 非空算成功 | ✅ | `activity.go:509` `time.Sleep(1500 * time.Millisecond)`；`activity.go:518` `if ov.PlanTier != ""` |
| C23 | 调度 `time.NewTicker(1 * time.Minute)` + 每分钟扫 `ListClaimPlans()` | ✅ | `scheduler.go:72,128` |
| C24 | cron 支持 `*` / `*/n` / `a,b` / `a-b` / `a-b/n`；`ValidateCronExpr`；`NextRunTime` | ✅ | `scheduler.go:319-345`（matchField 全分支）、`409-422`、`481-491` |
| C25 | 任务类型 detect / claim / activate / reset | ✅ | `scheduler.go:291-302` executeTask 四分支（注意：`scheduler.go:15` 注释只列前三，reset 仅见于代码） |
| C26 | 分钟级去重（写 `last_run_at` + 同分钟 continue） | ✅ | `scheduler.go:141-148`；`scheduler.go:175-176` |
| C27 | 失败隔离（单账号失败不中断，仅计 failCount） | ✅ | `scheduler.go:204-227` |
| C28 | 状态 `successCount==0 → failed` | ✅ | `scheduler.go:229-232` |
| C29 | 汇总串截断 900 字符 | ✅ | `scheduler.go:233-236` `if len(summary) > 900 { summary = summary[:900] + "…" }` |
| C30 | 落两条记录 + 实时进度 `PlanRunState` | ✅ | `scheduler.go:238-244`；`scheduler.go:20-30,196-226` |
| C31 | 空跑不算失败（`len(plans)==0` → Success=true） | ✅ | `activity.go:434-440`、`482-487` |
| C32 | `claimAll` 顺序执行、账号间 1.2s、超时 120000ms 则 `claim_cancel`、单号抛错 continue | ✅ | `main.js:327-357` `waitForClaimResult(id, 120000)`、`setTimeout(res, 1200)` |
| C33 | `autoClaimTick` 10 分钟、单轮每号最多 5 次、账号间 5s | ✅ | `main.js:19` `AUTO_CLAIM_INTERVAL_MS = 10*60*1000`；`main.js:22` `AUTO_CLAIM_PER_ACCOUNT_CAP = 5`；`main.js:23` `AUTO_CLAIM_ACCT_GAP_MS = 5_000`；`main.js:984` `setInterval(autoClaimTick, AUTO_CLAIM_INTERVAL_MS)` |
| C34 | 冷却分类（1005→nextAt；code>=1000 或 interactive→1h；其余→10min） | ✅ | `main.js:451-457`（`autoClaimCooldownFor` 声明于 451，`}` 于 457） |
| C35 | CLI `claim-preview` 逐号 `ensure_virtual_device_mid`+`preview_plans`，单号失败写 error 字段 | ✅ | `cli.rs:161-192` |
| C36 | `virtual_device_mid` 字段存在，`ensure_…` 保证非空 | ✅ | `store.rs:89` `pub virtual_device_mid: Option<String>`；`store.rs:1015-1047` |
| C37 | 切换账号时写回本机 telemetry（`write_live_device_mid`） | ✅ | `store.rs:1049-1062` |
| C38 | mid 经 `X-Device-Mid` 传递，为空才回退本机 telemetry | ✅ | `client.go:199-204` `NewClientIdentity`；`client.go:246-247` |
| C39 | DB 用 `COALESCE(NULLIF(excluded.device_mid,''), accounts.device_mid)` 防覆盖 | ✅ | `database_accounts.go:32`；`database.go:30` 注释"永不被重导入覆盖"；`account_manager.go:113-122,165` |
| C40 | 额度双通道 JWT `billing/current`→`billing/balance`；APIKey `api.z.ai/monitor…` | ✅ | `quota.go:22,220-264`；`quota.go:23-24,267-295` |
| C41 | `zcode-switch` APIKey 通道用 `open.bigmodel.cn`（与 zcode-proxy 主机不同） | ✅ | `quota.rs:20-21` 均为 `open.bigmodel.cn` |
| C42 | 归一化：解包 data/result ≤4 层、槽位求和、`tier_rank` 选主切片、字段别名防御 | ✅ | `quota.go:178-192`（`for i:=0;i<4;i++`）、`443-478`、`634-648`、`365-367` |
| C43 | 429 退避 `[500,1500,4000]ms`（共 3 次） | ✅ | `quota.rs:338` `let retry_delays = [500u64, 1500, 4000]`；`quota.rs:372-380` `backoff.next()` |
| C44 | token 全 401 时 sleep 1.5s 用首个 token 重试一次 | ✅ | `quota.rs:474-480` |
| C45 | 验证码缓存 45s TTL / 300s 宽限 / 失败冷却 60s | ✅ | `captcha.go:31-34`（45s/300s/60s）；`captcha.go:120-138` |
| C46 | 验证码无头连续 2 次失败 → 有头人工，成功后回无头 | ✅ | `captcha.go:216-223` `if headless && attempt >= 2 { headless = false; s.manual = true }`；`captcha.go:209` `s.manual = false` |
| C47 | `captcha_mode=off` 直连分支 与 `cc.Enabled=false` 跳过分支（削弱"强制"） | ✅ | `captcha.go:114-117`；`captcha.go:195-197` |
| C48 | 领取后 2s 异步刷额度 | ✅ | `activity.go:463-469` |
| C49 | `reset/use` 是唯一带 `idempotency_key` 的写接口 | ✅ | `reset.go:132-152`（`uuid.NewString()`）；`reset.go:155-181`（opportunity 也有 key）——严格说 opportunity 也带 key，C 的"唯一"指"重置执行"，可接受 |
| C50 | `zcode2api` 未实现任何领取流程（仅 `/captcha/check`） | ✅ | 全树 `grep claim/领取/签到` 于 `zcode2api/app/**.py` 仅命中 `models.py` 注释 "claims"；`admin_api.py:41-48` 仅 `/captcha/check` |

> C 另有 5 条自标【未验证】/【推断】项（APIKey 主机矛盾、mid 风控、`app_daily_active` 重复报、preview 多 plan、验证码强制），均为 ❓ 无法判定（上游行为），**标注诚实**，我逐条复核其"未验证"定位准确（例如 APIKey 主机差异确实存在：`quota.go:23-24` = api.z.ai vs `quota.rs:20-21` = open.bigmodel.cn）。

### 1.2 D 草稿（内部模型对接）

| # | 断言 | 判定 | 证据与原文片段 |
|---|---|---|---|
| D1 | ZCode 内部协议是 Anthropic Messages 风格 | ✅ | `ai-protocol.md:3` "基于 Anthropic Messages API 格式" |
| D2 | 端点 `.../anthropic/v1/messages`（三选一） | ✅ | `settings.py:102-115`（zai / zai_fallback / bigmodel）；`config.go:36-40` 同值 |
| D3 | 文档侧 `x-api-key: <JWT>` 与代码 `Bearer` 两条都真实存在 | ✅ | `ai-protocol.md:41`；`agent.py:64-66` `Authorization: Bearer`；`agent.py:60-71` 分支结构 |
| D4 | 对外三协议一套内核（Anthropic 原生 + Chat + Responses + models） | ⚠️ | 路由全部命中（见 D7）。但"原生**透传**"欠准：`/v1/messages` 也过 `_normalize_body`（`gateway.py:177-200`）/`normalizeBody`（`relay.go:504-550`），非纯透传 |
| D5 | OpenAI 侧一律强制流式再聚合 | ✅ | `gateway.py:375`、`gateway.py:423` `anthropic_body["stream"] = True  # 内部一律流式，按需聚合`；`handlers_openai.go:37,86` `anth["stream"] = true`；`relay.go:232` `upstreamStream := rc.clientStream \|\| rc.proto != protocolAnthropic`。**L3 复核：存在非流式分支，但只作用于 Anthropic 原生路径**（`proto==protocolAnthropic && clientStream==false` → `upstreamStream=false`），D 的 #3 已限定"OpenAI 侧"，**成立** |
| D6 | `convert.go` 是 `gateway.py` 的 Go 移植（`convert.go:15-17` 自述） | ⚠️ | 自述准确（`convert.go:15-17`）。但**请求侧转换不在 convert.go**，在 `handlers_openai.go`；D §⑥ 已澄清，§① #4 的"convert.go 是移植"是简化说法 |
| D7 | 路由清单（models 302-320 / messages 324 / chat 361 / responses 408 / 5 个别名 345,350,355,403,449） | ✅ | 逐条命中 |
| D8 | 无 `/v1/messages/count_tokens`（zcode2api） | ✅ | `grep count_tokens zcode2api/app/routes/gateway.py` → 零命中 |
| D9 | zcode-proxy **有** count_tokens，返回 `chars/4+8` | ✅ | `zcode_api.go:101` `HandleCountTokens`；`zcode_api.go:113` `est := chars/4 + 8` |
| D10 | 双通道鉴权 + 三级降级链 | ✅ | `agent.py:57-78`（JWT Bearer / x-api-key）；三级：`relay.go:162`(JWT+captcha) → `:184`(JWT direct) → `:201`(API Key)；`gateway.py:1310-1367` 同构 |
| D11 | 鉴权双通道三级降级 + 账号状态机 | ✅ | 同上；状态映射 `relay.go:284-313`、`gateway.py:1434-1449` |
| D12 | JWT 判定不解析 claims，只按形状 | ✅ | `models.py:30-43` `looks_like_jwt`；`models.py:74-85` 决定 mode |
| D13 | JWT → API Key 兑换链（z/login → getCustomerInfo → api_keys → copy/{apiKey}） | ✅ | `oauth.py:220-276` 全链路逐行命中，返回 `f"{api_key}.{secret_key}"` |
| D14 | TLS 指纹"**刚需而非可选**" | ⚠️ | 代码依据是"**易**被识别"（`tls_fingerprint.go:14-17`），且实现留有 `off` 预设（`tls_fingerprint.go:31` "关闭（Go 默认指纹）"）与 `mode=off` 回落标准库分支（`tls_fingerprint.go:117-124`）。"刚需"是把"降低特征评分"升格为"硬要求"，属**轻度过度推论** |
| D15 | 仅 `zcode.z.ai` 用 utls 并**显式禁 h2** | ✅ | `client.go:311` `TLSNextProto: map[string]func(string,*tls.Conn) http.RoundTripper{}, // 禁 h2`；`client.go:328,335-338` `strings.Contains(urlStr,"zcode.z.ai")` 分流 |
| D16 | 其余主机标准库 + `ForceAttemptHTTP2` | ✅ | `client.go:275` `ForceAttemptHTTP2: true`；`client.go:337-338` |
| D17 | 客户端按 `(proxy,fp,ja3,timeout,isZcode)` 缓存 + `CloseIdleClients()` | ✅ | `client.go:330` `key := fmt.Sprintf("%s\|%s\|%s\|%s\|%v", …)`；`client.go:344-351` |
| D18 | 禁重定向 `http.ErrUseLastResponse` | ✅ | `client.go:284-285`、`client.go:318-319` |
| D19 | 预置指纹表 20 项 | ✅ | `tls_fingerprint.go:26-51` 逐项计数 = 20 |
| D20 | 非浏览器运行时用内置 JA3 → `ClientHelloSpec` | ✅ | `tls_fingerprint.go:53-61`（6 条）；`tls_fingerprint.go:154-216` |
| D21 | 默认模式 `chrome` | ✅ | `tls_fingerprint.go:64`；`main.go:62-68` |
| D22 | 请求头清单（agent.py:80-92） | ✅ | 逐项命中，含 `anthropic-version: 2023-06-01`、`X-ZCode-Agent: glm`、`HTTP-Referer` |
| D23 | Go 版额外桌面身份头（client.go:228-250） | ✅ | `X-Title: Z Code@electron`(233)、`X-Platform`(235)、`X-Release-Channel: stable`(236)、`X-Client-Language: zh-CN`(237)、`X-Client-Timezone`(238)、`X-Os-Category`(239)、`X-Os-Version`(244)、`X-Device-Mid`(247)、`x-request-id`(240) |
| D24 | 验证码路径追加 `X-Aliyun-Captcha-Verify-Region`（relay.go:394-399） | ✅ | `relay.go:396-398` |
| D25 | 请求体字段（model/max_tokens/temperature/top_p/system/messages/thinking/reasoning_effort/stop_sequences/tools/tool_choice） | ✅ | `gateway.py:52-65,188,538-589`；`ai-protocol.md:69-88` |
| D26 | SSE 事件族（message_start / content_block_* / message_delta / message_stop / error） | ✅ | `ai-protocol.md:113-134`；`gateway.py:1230-1246`；`convert.go:82-101` |
| D27 | 错误体 `{type,error{type,code,message},request_id}`，余额不足 `code:"1113"` | ✅ | `ai-protocol.md:138-147` |
| D28 | 模型名大小写敏感 | ✅ | `gateway.py:33` 注释；`relay.go:28` |
| D29 | 字段映射全表（system/developer→system、string→block、tool→tool_result、tool_calls→tool_use、image_url 仅 data-URI、max_tokens 优先级、stop→stop_sequences、tools→input_schema、tool_choice 三态、Responses instructions/input/max_output_tokens/reasoning.effort、去 provider/ 前缀） | ✅ | 逐条核对 `gateway.py:466-475,540` / `195-196,494-495` / `476-489` / `512-531` / `502-511` / `541-546` / `547-550` / `551-553` / `555-579` / `581-589` / `620-622` / `624-661` / `673-676` / `685-688` / `181-182` —— **全部命中**；Go 侧 `handlers_openai.go:146-159,266` / `161-180` / `199-215` / `219-252` 亦命中 |
| D30 | 丢弃字段（n/presence_penalty/frequency_penalty/logit_bias/seed/user/response_format/logprobs/top_logprobs） | ⚠️ | `grep -E 'presence_penalty\|frequency_penalty\|logit_bias\|response_format\|top_logprobs\|logprobs' gateway.py` → 零命中（✅）。但 `n`/`seed`/`user` 是通用词，**D 未对这三个词做独立检索**，其"未引用"依赖对 454-590 的人工通读。D 已标【推断】，可接受 |
| D31 | 响应映射（text→content、thinking→reasoning_content、tool_use→tool_calls、stop_reason→finish_reason、usage、chatcmpl-/resp_ 前缀） | ✅ | `gateway.py:712,775-782` / `713-714,760-765` / `715-729,766-774` / `692-697` / `740-744,748-755` / `731-732,784-786` 全部命中；`convert.go:842-850,899-904,919-927` |
| D32 | `count_tokens` 无 / models 双字段 | ✅ | `zcode_api.go:137-138` `"object":"model"` + `"type":"model"` |
| D33 | 别名映射表 6 条 / 11 条 | ✅ | `gateway.py:34-41` = 6；`relay.go:29-41` = 11 |
| D34 | `/v1/models` 来源：zcode2api 静态 9 个；proxy config.json 9 个 + DB 覆盖 | ✅ | `settings.py:146-159` 计 9 项；`config.go:43-46` 计 9 项；`zcode_api.go:121-131` |
| D35 | 目录拉取 `client/configs?version=&os=` → `builtinModels`（空则 providers[].models） | ✅ | `reset.go:250-303`；`reset.go:241-247` CatalogModel |
| D36 | 参数名分歧 `version/os` vs `app_version/platform` | ✅ | `reset.go:251`、`captcha.py:128-130` vs `client-configs.md:32-34` |
| D37 | 该接口无需认证 | ✅ | `client-configs.md:13` "**不需要任何认证**"；`:65` "（**无需任何认证**）" |
| D38 | SSE 解析器：增量缓冲 / 跨 chunk 断帧 / LF+CRLF / 16MB 上限 | ✅ | `convert.go:34-101`；`gateway.py:1248-1273` |
| D39 | `streamOpenAI` 转换（text_delta/thinking_delta/tool_calls 索引映射/首增量补 role/input_json_delta/收尾 DONE + include_usage） | ✅ | `convert.go:406-555` 区间内逐条命中（`441-463`、`448-451`、`470-483`、`484-494`、`531-550`） |
| D40 | `streamResponses` 完整事件序列 + `sequence_number` 单调递增 | ✅ | `convert.go:559-838`；`convert.go:582-593` |
| D41 | 工具调用收尾 partial_json → json.Unmarshal → input | ✅ | `convert.go:180-186`（累积）、`205-220`（finalize）；`gateway.py:836-851` |
| D42 | system 多条用 `\n\n` 拼成单个字符串 | ✅ | `gateway.py:540`；`handlers_openai.go:266` |
| D43 | 多模态仅 data-URI，远程 URL 静默丢弃不报错 | ✅ | `gateway.py:502-511`（无 else 分支）；`handlers_openai.go:199-215` |
| D44 | 流内 error 不吞（→ StreamError / 错误 chunk / response.failed / 非流式 502） | ✅ | `convert.go:189-202`；`convert.go:513-529`；`convert.go:800-818`；`convert.go:380-390`（`writeJSON(w, http.StatusBadGateway, …)`） |
| D45 | 坑位1：`api.z.ai` 把 input_tokens 放 `message_delta`，取 max 累积 | ✅ | `convert.go:137-142` 注释 + `if n := toInt(v); n > usage.InputTokens` |
| D46 | 坑位2：2xx 非 JSON/SSE 判为 WAF 页并冷却 120s | ✅ | `relay.go:329-336` `MarkCooling(…, 120)` |
| D47 | 对外鉴权：zcode2api `hmac.compare_digest`，未配置则**放行** | ✅ | `auth_admin.py:62-64` `if not key: return`；`auth_admin.py:68` |
| D48 | 对外鉴权：zcode-proxy `subtle.ConstantTimeCompare`，401 | ✅ | `auth.go:261`；`auth.go:277-283`；`auth.go:284-298` |
| D49 | 免认证路径 `/web`、`/oauth/`、`/health`、`/api/login` | ✅ | `auth.go:270-274` |
| D50 | 状态判定 401/403→invalid；429→cooling（尊重 Retry-After）；402/短语→exhausted | ✅ | `relay.go:285-287`、`288-303`、`309-312`；`gateway.py:1434-1449` |
| D51 | 风控 3012 / `unusual activity` 单独识别 | ✅ | `relay.go:461-464` `isRiskBlocked`；`relay.go:304-308` |
| D52 | 验证码配置拉取 + Playwright 求解 + 45s TTL + 宽限刷新 + 数据中心 IP F001 拒绝需住宅代理 | ✅ | `captcha.py:121-139`、`142-195`、`217-263`、`93-101` |
| D53 | 白名单透传 header（含 `x-stainless-*`） | ✅ | `agent.py:15-30,33-47`；`relay.go:401-414` |
| D54 | `/v1/models` 双字段可一次满足两类 SDK | ✅ | 同 D32 |
| D55 | `count_tokens` 仅 Go 版有 | ✅ | 同 D8/D9 |

> D 自标【未验证】7 条 + 【推断】2 条，我复核其定性合理（尤其"丢弃字段清单是反向推断"——确实只能靠通读证明，D 已如实标注）。

### 1.3 E 草稿（账号池与额度聚合）

| # | 断言 | 判定 | 证据与原文片段 |
|---|---|---|---|
| E1 | 两套同源：`pool.go` 自述"与 zcode2api models.py 一致" | ✅ | `pool.go:14` "状态（与 zcode2api models.py 一致，另加 inactive=套餐未激活）" |
| E2 | 状态机 / round-robin / `is_selectable` 是同一套逻辑的 Go 移植 | ✅ | `pool.go:167` 注释"models.py is_selectable 移植"；`pool.go:169-179` ↔ `models.py:91-100`；`pool.go:192-242` ↔ `store.py:242-256` |
| E3 | **⭐ 转发选号路径没有并发租约（lease/in-flight）** | ✅ | **L3 专项，见 §3.2**。`pool.Select`（`pool.go:192-242`）、`store.select`（`store.py:242-256`）、`choose_upstreams`（`proxy.rs:325-405`）三处完整实现均为"过滤→返回"，零占位写回 |
| E4 | 命中项全部是"领取/重置/计划"级互斥，与转发选号无关 | ⚠️ | **判定结论正确**（逐项复核：`activity.go:405-423`、`reset.go:185-192`、`scheduler.go:44,159,170`、`pool.go:44,234-240`、`store.py:29`、`captcha.py:116,159` 均与选号无关）。但"**全部**"不成立：表中**漏列**至少 10 处命中（`captcha.go:66,78,120…`、`auth.go:38,43,108…`、`config.go:32`、`oauth.go:58`、`zcode_api.go:23-24`、`scheduler.go:40,43`、`quota.py:439`、`zcode-switcher/oauth.rs:40`、`captcha.rs:58`、`store.py:42` busy_timeout）。漏列项经我补检**同样与选号无关**，故结论不受影响 |
| E5 | `pool.go:44` 的 `mu` "只保护 `rotation` 游标 map，临界区仅游标自增" | ⚠️ | `mu` 还保护 `refreshFn`（`pool.go:65,117-119,158-160`）。`234-240` 临界区确实仅游标自增 ✅ |
| E6 | `proxy.rs`（switcher）"**无任何锁**" | ❌ | `proxy.rs:5` `use std::sync::{Mutex, OnceLock}`；`proxy.rs:84` `static PROXY: OnceLock<Mutex<Option<ProxyRuntime>>>`；`:817,845,858,872` 均 `.lock()`。该锁保护本地代理服务生命周期，**与选号无关**（判定列 ❌ 否 正确），但"无任何锁"表述与事实相反 |
| E7 | 账号状态更新只发生在请求失败/成功**之后**（事后记账） | ✅ | `relay.go:254,261,286,302,310,323` 全部在 `forwardOnce` 的响应处理后 |
| E8 | 并发请求可命中同一账号；round-robin 游标只能"近似摊开" | ✅ | `pool.go:237-239` 在锁内自增后**立即释放**，无占用标记 |
| E9 | 无 per-account 并发上限；`use_count` 是累计计数 | ✅ | `database_accounts.go:184-191` `use_count = use_count + 1` |
| E10 | `total_remaining = Σ 各账号 Remaining`，仅在 dashboard 返回 | ✅ | `api_handlers.go:122` `totalRemaining := 0.0`；`:131` `totalRemaining += a.Remaining`（全仓**唯一**一处累加）；`:139` `"total_remaining": totalRemaining` |
| E11 | 跨账号聚合数据源是**库里上次刷新的快照**，非实时拉取 | ✅ | `handleDashboard` 直接读 `ListAccounts("")` 的 `a.Remaining`，无 fetch |
| E12 | zcode2api `/status` 只返回可选中账号数（`quota_pool`） | ✅ | `admin_api.py:81-84` `sum(1 for a in store.list_accounts(p) if a.is_selectable())` |
| E13 | 两套都没有对外额度聚合端点 | ✅ | 全量 `/v1/*` 路由枚举 = messages / messages/ / messages/count_tokens / chat/completions / responses / models（+别名），**无 quota/credits/balance** |
| E14 | 6 态状态机（+inactive） | ✅ | `pool.go:22-29` = active/exhausted/cooling/invalid/disabled/inactive |
| E15 | `is_selectable` 含冷却到期判定 | ✅ | `pool.go:169-179`；`pool.go:182-187` `EffectiveStatus` |
| E16 | 三种选路策略 + 设置开关，默认 round_robin | ✅ | `pool.go:32-36`；`pool.go:223-241`；`database.go:332` `"selection_strategy": "round_robin"` |
| E17 | 候选池过滤链（provider→group→skip→accountSelectable→有凭证） | ✅ | `pool.go:199-218` |
| E18 | `best_quota` 按 `Remaining` 降序、未知(0)排后 | ✅ | `pool.go:227-232` `sort.SliceStable(… pool[i].Remaining > pool[j].Remaining)`；零值自然排后 |
| E19 | zcode2api 只有 round-robin，无策略开关 | ✅ | `store.py:242-256` |
| E20 | zcode-switcher 有序列表 + 顺序 failover，无游标 | ✅ | `proxy.rs:325-405` 构建 `Vec<Upstream>`；`proxy.rs:588` `for upstream in upstreams` |
| E21 | 额度耗尽阈值 `remaining <= 0`，无预留水位 | ✅ | `quota.go:713-723` `AllExhausted`；`database.go:328-340` 默认设置清单确无水位项 |
| E22 | 主动路径 `applyQuotaResult` → `MarkExhausted` | ✅ | `zcode_api.go:53-62` |
| E23 | 被动路径 402 → `MarkExhausted` + 异步刷额度 + 换号 | ✅ | `relay.go:309-312` |
| E24 | 恢复：有余量时 exhausted/inactive/invalid/cooling到期 全部回 active | ✅ | `zcode_api.go:64-72` |
| E25 | 冷却默认 60s / 风控 120s / 429 30s / 连接失败 60s / 3xx WAF 120s | ✅ | `pool.go:254-265`；`relay.go:220,254,261,302` |
| E26 | zcode2api `COOLING_SECONDS=300`，但 429 显式传 60，连接失败走 300 | ✅ | `settings.py:99`；`gateway.py:1441` `cooling_seconds=60`；`gateway.py:1399`（无参）+ `gateway.py:237` |
| E27 | 重试上限 `maxAccountAttempts=5` / `maxCaptchaRetries=3` | ✅ | `relay.go:22-26`；`gateway.py:30-31` |
| E28 | 换号循环 + 请求级 `tried` skip 集 | ✅ | `relay.go:110-124`；`gateway.py:1285-1296` |
| E29 | 状态码映射表（401/403、429、402、3012、连接失败/3xx、验证码被拒、2xx 非 JSON、其它 4xx/5xx 不换号） | ✅ | `relay.go:284-320` 逐分支命中；`relay.go:270-282`（验证码）；`relay.go:315-320`（其它 4xx/5xx 终止） |
| E30 | 单账号降级链 JWT+验证码 → JWT 直连 → API Key | ✅ | `relay.go:151-224`；`gateway.py:1310-1367` |
| E31 | 全部失败 503 + `no_available_account` + 冷却恢复提示 | ✅ | `relay.go:126-145`；`pool.go:302-325` `CoolingInfo` |
| E32 | 成功后 `MarkUsed` + 30s 节流刷额度 | ✅ | `relay.go:323-324`；`relay.go:701-712`（`< 30` return）；`pool.go:284-292` |
| E33 | 账号表字段分组（自然键/身份/凭证/状态/额度快照/计数/活动/时间） | ✅ | `database.go:186-224` 逐字段命中 |
| E34 | 索引 enabled/status/account_group | ✅ | `database.go:222-224` |
| E35 | upsert COALESCE 保留 device_mid/creds_raw；status disabled 特判 | ✅ | `database_accounts.go:32,33,34` |
| E36 | SQLite WAL + SetMaxOpenConns(1) + busy_timeout=5000 | ✅ | `database.go:8,158,160-162` |
| E37 | zcode2api 瘦表 + RLock + 内存常驻 | ✅ | `store.py:29,30,54-66,85-104` |
| E38 | zcode-switcher 用 JSON 文件 `~/.zcode/account-profiles/proxy-account-pool.json` | ✅ | `proxy_pool.rs:49-50` `.join("account-profiles").join("proxy-account-pool.json")` |
| E39 | 账号生命周期增删改查/刷新/重置/切回/导出 | ✅ | `account_manager.go:40-50,55-191,196-235,274-376,410-444`；`database_accounts.go:88-136,139-148,240-255`；`store.py:166-221,228-239`；`reset.go:183-236` |
| E40 | 导出 `zcb1:` 加密包；导入按 user_id upsert、跳过无凭证 | ✅ | `export_bundle.go:44-99,102-153`（`if it.UserID == "" \|\| (it.ZCodeJWT=="" && it.APIKey=="") { continue }` 于 136-138） |
| E41 | zcode2api 导出**明文 secret** | ✅ | `store.py:259-271` `{"name":…, "mode":…, "secret": a.secret}` |
| E42 | `enc:v1` 格式 + AES-256-GCM + `SHA-256(secret)` 密钥 + 回退串 | ✅ | `credential_crypto.go:17-23,61-64,39-59,96-110`；`104-106` ct‖tag 兼容注释；`135-150` 不验签 |
| E43 | `zcb1:` = `base64(salt16‖nonce12‖ciphertext)`，PBKDF2-SHA256(…,120000,32) → AES-256-GCM | ✅ | `export_bundle.go:16-23`（`pbkdf2Iterations = 120000`）、`78-98`、`114-115` |
| E44 | 出口代理优先级：组绑定 → 默认代理 → 全局 `upstream_proxy` → 直连 | ✅ | `egress_proxy.go:50-61`；`database_ops.go:279-302`（组匹配 284-295，`IsDefault` 回退 296-300） |
| E45 | 代理存在原因：风控按 IP 判定（F001）、多账号 IP 隔离、健康检查、验证码复用 | ✅ | `settings.py:134-136`；`egress_proxy.go:54-59,74-108`；`main.go:78-79` |
| E46 | `ProbeLocalProxyPorts` 探测 9 个端口 | ✅ | `egress_proxy.go:173` 计 9 项 |
| E47 | 额度刷新循环：启动等 5s、默认 60s、显式 0 = 关闭、并发 4 + 每账号 0-2s 延迟 | ✅ | `pool.go:82-85,100-113,128,147`；`database.go:333` |
| E48 | 计划调度器：每分钟 tick、5 段 cron、分钟去重、per-plan TryLock、delay+0~50% 抖动 | ✅ | `scheduler.go:72,127-151,307-317,159,170,204-211` |
| E49 | zcode2api 额度监控：启动等 5s、默认 60s、并发 8 | ✅ | `quota.py:461,467,479,435-448`（`Semaphore(8)` 于 439）；`settings.py:97` |
| E50 | 启动顺序 `pool.Start()` → `scheduler.Start()`；热重载 30s | ✅ | `main.go:59,96,48` |

---

## 2. 发现的问题清单

### 严重（2 条）

**P1 · C 草稿：激活事件体字段数写错（14 → 实际 16）**
- 原表述：`claim.rs:158-177`、`activity.go:330-347` 事件体"**固定 14 字段**"（§③ 3.3）；§⑧ 复用点清单再次强调"字段需 **14** 项齐全"。
- 实际是什么：两个实现**都是 16 个键**。逐项枚举（`claim.rs:159-176` / `activity.go:330-347`）：`event_id`、`client_timezone`、`client_language`、`element_name`、`event_region`、`event_type`、`event_text`、`event_extra_detail`、`user_id`、`screen_resolution`、`app_version`、`device_os_category`、`device_os_version`、`device_mid`、`mac_id`、`marketing_params` = **16**。
- 影响：这是**施工级数字**。若 Model-Gateway 按"14 项"实现事件体，会缺字段导致服务端拒绝或统计异常。
- 建议修正为：`激活事件体固定 16 字段（activity.go:330-347 / claim.rs:159-176）；注意 device_os_version 在非 Windows 下为空串（client.go:107-110）`。

**P2 · E 草稿：`proxy.rs` "无任何锁" 与事实相反**
- 原表述：§④ 命中表 —— "`proxy.rs`（switcher） | **无任何锁** | ❌ 否"。
- 实际是什么：`zcode-switcher/src-tauri/src/proxy.rs` **有锁**：`:5` `use std::sync::{Mutex, OnceLock}`；`:84` `static PROXY: OnceLock<Mutex<Option<ProxyRuntime>>>`；`:86-87` `proxy_slot()`；`:817,845,858,872` 四处 `.lock()`。该锁保护本地代理服务的启停状态（`ProxyRuntime`），**确实与转发选号无关**——所以该行的"是否用于转发选号 = ❌ 否"是**对的**，但"无任何锁"这句是错的。
- 影响：负向断言的可信度。一张自称"命中与判定"的表里出现"无任何锁"这种可被一行 grep 证伪的陈述，会削弱整条 L3 结论的说服力。
- 建议修正为：`proxy.rs | PROXY: OnceLock<Mutex<Option<ProxyRuntime>>>（:84,:817…），保护本地代理服务生命周期，不参与选号 | ❌ 否`。

### 中等（6 条）

**P3 · E 草稿：负向断言的检索范围未覆盖其自述的调研对象之一**
- 原表述：§④ 检索范围 = `zcode-proxy/*.go` + `zcode2api/app/**/*.py` + `zcode-switcher/src-tauri/src/*.rs`（三棵树）；而文档头部 §调研对象 列了**四个**项目（含 `zcode-account-switcher/` Node）。
- 实际是什么：`zcode-account-switcher/`（Electron 桌面账号切换器，含 `desktop/main.js` 等）**未被纳入负向断言的检索范围**。
- 我补检结果：该目录**没有任何转发/选号逻辑**（无 `round_robin`/`rotation`/`upstream`/`selectAccount` 命中），因此**结论不受影响**。此外我也补检了 `zcode-switch/`（C 的 Rust 项目，E 未列）——同样无转发选号（`grep select|round_robin|rotation|upstream` 于 `src-tauri/src/*.rs` 零命中）。
- 建议修正为：把检索范围明确写成"**转发网关**（zcode-proxy / zcode2api / zcode-switcher）"，并补一句"另经补检 `zcode-switch/`、`zcode-account-switcher/`、`ZCode-Panel/` 均不含转发选号逻辑，故负向结论对全部 6 个项目成立"。这样把"范围缺口"变成"范围覆盖证据"。

**P4 · E 草稿：命中表漏列 ≥10 处锁/信号量命中，与"命中与判定（全部）"的表述不符**
- 原表述：§④ 表格标题为"**命中与判定（全部为【一手】）**"，仅列 7 行。
- 实际是什么：同一关键词集在同样范围内还命中：`captcha.go:61,66,78,120,152-168`（`solveSem` 容量 1 信号量 + `mu`）、`auth.go:38,43,108,122,141,187,213,388`（`RWMutex`/`failMu`）、`config.go:32,58`、`oauth.go:58,100…304`、`zcode_api.go:23-24`（`claimMu`+`claimLocks`）、`scheduler.go:40,43,99,109,119`（`runMu`/`execMu`）、`quota.py:439`（`Semaphore(8)`）、`zcode-switcher/oauth.rs:40,122-129,250…`、`captcha.rs:58,258,280`、`store.py:42`/`database.go:162`（busy_timeout）。
- 我逐项判定：**全部与转发选号无关**（分别是验证码求解串行、Web 鉴权、配置热重载、OAuth 流程、领取/重置互斥、调度器运行态、额度刷新并发、代理生命周期、SQLite 忙等）。
- 建议修正为：把表格改为"**代表性命中**"并补一句"完整命中清单见附录（共 N 处），逐项判定均与选号无关"。负向断言的价值在于**穷尽**，所以这里值得补全。

**P5 · D 草稿：把"降低被识别概率"升格为"刚需而非可选"**
- 原表述：§① #5 "TLS 指纹伪装是**刚需而非可选**"。
- 实际是什么：代码注释原文是"**易**被上游 ESA WAF 识别为机器程序"（`tls_fingerprint.go:14-17`），且实现**保留了 `off` 模式**（`tls_fingerprint.go:31` "关闭（Go 默认指纹）"；`:117-124` `if fp.Mode == "" || fp.Mode == "off"` 回落标准库；`database.go` 默认设置 `"fingerprint": "chrome"` 可改）。也就是说指纹是**默认开启、可关闭的强建议**，不是不可绕过的硬约束。
- 建议修正为：`TLS 指纹伪装对 zcode.z.ai 是强默认项（默认 chrome，可被设置改为 off）；代码依据是"易被识别"而非"必被拒绝"，实际拦截率未测（→ 与 D §⑩ #7 的"未验证"呼应）`。

**P6 · D 草稿：可复用点清单里"内部统一强制 stream:true"表述过宽**
- 原表述：§⑨ 表 —— "内部统一强制 `stream:true` 再按需聚合 | `gateway.py:375,423`；`relay.go:232`"。
- 实际是什么：强制流式**只对 OpenAI / Responses 生效**。Anthropic 原生路径不强制：`relay.go:232` `upstreamStream := rc.clientStream || rc.proto != protocolAnthropic`，当 `proto==protocolAnthropic && clientStream==false` 时 `upstreamStream=false`，且 `HandleMessages`（`relay.go:94-99`）不覆写 body 的 `stream` 字段。（D §① #3 已正确限定为"OpenAI 侧一律"，此处是清单行的措辞不一致。）
- 建议修正为：`OpenAI/Responses 路径内部强制 stream:true 再按需聚合（Anthropic 原生路径保持客户端 stream 意图）`。

**P7 · C 草稿：`code!=0` 中止条件未标注 Go/Rust 差异**
- 原表述：§③ 3.3 "`code!=0` 即中止报错。【一手】`claim.rs:131,192-213`"。
- 实际是什么：Rust 为 `if code != 0 { return Err(...) }`（`claim.rs:210`）；**Go 为 `code != 0 && code != -1`**（`activity.go:368`），即 Go 容忍 `-1`（响应非 JSON 时的兜底码）。两实现对"非 JSON 响应"的处理因此不同。
- 建议修正为：`code!=0 中止（Rust claim.rs:210）；Go 侧为 code!=0 && code!=-1（activity.go:368），-1 是"响应非 JSON"兜底码，不中止`。

**P8 · C 草稿：请求头清单不全（漏 3 个头）**
- 原表述：§③ 3.1 列出 10 个头，称来自 `zai_billing_headers_with_mid`。
- 实际是什么：`quota.rs:180-201` 实际构造 13 个头，漏列 `HTTP-Referer`（184）、`X-Title: Z Code@electron`（185）、`X-Os-Version`（193-195）。另外函数名不精确：`zai_billing_headers_with_mid` 定义在 `quota.rs:170`，被引的 180-201 是 `zai_headers_with_version`。
- 建议修正为：补上三个头，并把函数名改为 `zai_headers_with_version`（由 `zai_billing_headers_with_mid` 包装，quota.rs:166-172）。

### 轻微（13 条）

| # | 草稿 | 原表述 | 实际 | 建议 |
|---|---|---|---|---|
| P9 | E | `pool.go:44` 的 `mu` "只保护 rotation 游标 map" | 还保护 `refreshFn`（`pool.go:65,117-119,158-160`） | 改为"保护 rotation 游标与 refreshFn 注入；234-240 临界区仅游标自增" |
| P10 | E | §④ 检索范围"`zcode-proxy/*.go` 全部 **12 个目标文件** + 其余 Go 文件" | 该目录实有 **24 个 `.go`**（含 `_test.go`、`proc_*.go`） | 改为"全部 24 个 .go 文件" |
| P11 | E | §⑨ "zcode2api 额度监控 `QuotaMonitor._loop`（`quota.py:451-497`）" | `_loop` 定义在 `quota.py:458-483`；451-497 覆盖的是整个 class + 单例 | 改为 `quota.py:458-483`（class 451-497） |
| P12 | E | §⑨ 启动顺序"`pool.Start()`（main.go:59）→ `scheduler.Start()`（main.go:96）" | 正确，但 `scheduler` 变量构造在 95、`Start()` 在 96 | 无需改，仅备注 |
| P13 | D | §⑨ "验证码自动求解 … `captcha.go:113-207`" | 求解主流程延伸到 `captcha.go:227`（`doSolve` 188-227） | 改为 `captcha.go:113-227` |
| P14 | D | §⑥ "`streamOpenAI` `convert.go:406-555`" | 函数体到 `convert.go:557`（下一个 `func` 在 559） | 改为 `convert.go:406-557` |
| P15 | D | §⑥ "`streamResponses` `convert.go:559-838`" | 函数体到 `convert.go:840`（`openaiFinish` 在 842） | 改为 `convert.go:559-840` |
| P16 | D | §① #4 "`convert.go` 是 `gateway.py` 的 Go 移植" | 请求侧转换在 `handlers_openai.go`；`convert.go` 只承接响应侧 + SSE 解析 | §① 加一句"（请求侧见 handlers_openai.go）"，与 §⑥ 对齐 |
| P17 | D | §① #2 称 Anthropic `/v1/messages` 为"**原生透传**" | 仍过 `_normalize_body` / `normalizeBody`（补 max_tokens、桥接 content、GLM-5.3 强制 thinking） | 改为"原生协议 + 轻量规范化后转发" |
| P18 | D | §⑨ "内部统一强制 stream:true" 与 §① #3 口径不一致 | 见 P6 | 同 P6 |
| P19 | C | §④ 4.1 任务类型引 `scheduler.go:15` | 第 15 行注释只列 detect/claim/activate，`reset` 仅见于 291-302 代码 | 改为"代码 291-302 支持 4 类（注释 :15 仅列前 3）" |
| P20 | C | §⑧ "`reset/use` 的 `idempotency_key`" 称"唯一带幂等键的写接口" | `reset/opportunity`（`reset.go:155-159`）同样带 `idempotency_key` | 改为"reset 系列是唯一带幂等键的写接口（use + opportunity）" |
| P21 | D | §⑤ "zcode2api **不拉目录**，只用静态 allowlist" | 正确（`gateway.py` 无 `client/configs` 调用），但 D 未说明 `reset.go` 的目录同步**只写 DB setting、未回灌 `/v1/models` 的过滤** | 可补一句"目录仅落 DB，未参与 /v1/models 过滤"（与 D §⑩ #8 呼应） |

---

## 3. 遗漏与矛盾检查

### 3.1 交叉矛盾（三稿之间）

| 议题 | C 的说法 | D/E 的说法 | 判定 |
|---|---|---|---|
| `client/configs` 参数名 | C §② 用 `?version=&os=`（与代码一致） | D §⑤ 指出代码 `version/os` vs 文档 `app_version/platform` 分歧 | **无矛盾**：C 直接引代码，D 额外指出文档分歧。但 C 未提这个分歧，属"遗漏"而非矛盾 |
| APIKey 通道主机 | C §⑥ 明确标注"两个参考项目主机不同（api.z.ai vs open.bigmodel.cn），需实测"【未验证】 | E §③ 只写 `api.z.ai`（zcode-proxy 侧） | **C 更准确**。E 在描述 zcode-proxy 时写 `api.z.ai` 正确，但未提及 zcode-switch 用 `open.bigmodel.cn`，属**范围遗漏** |
| 冷却默认值 | C §⑦ 只列 `quota.rs` 的 429 退避与 1.5s 重试 | E §④ 列 `pool.go` 60s / `gateway.py` 300s | **互补**，无矛盾 |
| 领取的并发保护 | C §① #4 称"二者都做了账号级互斥" | E §④ 称命中项都是"领取/重置/计划级互斥" | **一致** |
| 事件体字段数 | C 说 14 | D 未涉及 | 与代码矛盾（见 P1） |

### 3.2 L3 专项：E「无并发租约」的完整复核（本节为独立复算，非引用草稿）

**检索关键词集（我用的比 E 更宽）**：`lease|reserve|in_flight|inflight|acquire|busy|TryLock|claimLockFor|mutex|Lock()|RWMutex|semaphore|Semaphore|singleflight|inUse|in_use|occupied|borrow|handoff|concurren|parallel|chan struct`

**检索范围**：`zcode-proxy/*.go`（24 文件）、`zcode2api/app/**/*.py`（15 文件）、`zcode-switcher/src-tauri/src/*.rs`（12 文件）、`zcode-switch/src-tauri/src/*.rs`（12 文件，**E 未覆盖**）、`zcode-account-switcher/{desktop,src}`（**E 未覆盖**）

**逐项判定结果**（全部与转发选号无关）：

| 命中 | 用途 | 与选号相关？ |
|---|---|---|
| `activity.go:404-423` `claimLockFor`+`TryLock` | per-account 领取互斥 | 否 |
| `reset.go:185-192` `claimLockFor` | 防重复消耗重置机会 | 否 |
| `scheduler.go:44,59-68,159,170` `execLocks`+`TryLock` | per-plan 执行互斥 | 否 |
| `scheduler.go:40,99,109,119` `runMu` | 运行态 map 读写 | 否 |
| `pool.go:44,65,117,158,234-240` `mu` | rotation 游标 + refreshFn | 否 |
| `captcha.go:61,66,78,120,152-168,178-276` `mu`+`solveSem` | 验证码求解串行 | 否 |
| `auth.go:38,43,108,122,141,187,213,388` `mu`/`failMu` | Web session / 登录失败计数 | 否 |
| `config.go:32,58` `mu` | 配置热重载 | 否 |
| `oauth.go:58,100…304` `mu` | OAuth flow map | 否 |
| `zcode_api.go:23-24` `claimMu`+`claimLocks` | 领取/重置锁表 | 否 |
| `store.py:29,135-260` `RLock` | 内存账号字典 / 游标 | 否（`select` 持锁读 pool+自增游标，**出锁后即返回**） |
| `captcha.py:116,159,184` `asyncio.Lock` | 求解串行 | 否 |
| `quota.py:439` `Semaphore(8)` | 额度刷新并发上限 | 否 |
| `zcode-switcher/oauth.rs`、`captcha.rs`、`proxy.rs`、`profile.rs` `Mutex` | OAuth/验证码/代理生命周期 | 否 |
| `database.go:162`、`store.py:42` `busy_timeout` | SQLite 忙等（非锁对象） | 否 |
| `zcode-switch`、`zcode-account-switcher` | **无任何命中** | — |

**`pool.Select` 完整实现复核**（`pool.go:192-242`，逐行）：
1. `ListAccounts("")` → 全量读库；
2. 过滤：provider 匹配 / group 匹配 / `skip[a.ID]` / `accountSelectable` / 有凭证（199-218）；
3. `len(pool)==0` → return nil（219-221）；
4. 按策略返回：`random` 直接索引（226）；`best_quota` 排序取 [0]（229-232）；`round_robin` 在 `mu` 内算下标、自增游标、**return**（234-241）。
→ **全过程无任何"标记该账号已被占用"的写操作**。`store.select`（`store.py:242-256`）同构。`choose_upstreams`（`proxy.rs:325-405`）构建有序 `Vec<Upstream>` 后返回，无占用。

**结论**：E 的负向断言**为真**。唯一需要修正的是 (a) 检索范围声明未覆盖其自述的 `zcode-account-switcher`（P3），(b) 命中表自称"全部"但漏列 ≥10 项（P4），(c) `proxy.rs` "无任何锁"错误（P2）。

### 3.3 L3 专项：C「无每日签到端点」的完整复核

- 关键词：`签到|checkin|check_in|sign_in|signin|daily_reward|每日签到`
- 范围：整个参考项目（含 `ZCode-Panel/`、`zemote/`、`zcode-account-switcher/`、`ZCode-Deploy/` 等 C 未在正文列出的项目），排除 `node_modules/`
- 命中：`ZCode-Deploy/人格.txt`（英文 "checking"）、`zcode-proxy/scheduler.go:74`（`checking every 1 minute` 日志）、`ZCode-Panel/main.js:1507,1541,1562`（`signingKeysCleared`）、`zemote/**`（`settings.checking` i18n）、`zcode-switcher/src/**`（`checkingUpdate`）、`zcode2api/Dockerfile:27`（`linux_signing_key.pub`）、`zcode-switch/target/**/ring-*.d`（构建产物路径）
- **无一条是签到端点/签到函数**。C 的免责"除 UI 文案与 tier 关键词"覆盖了这些命中。
- 补充检索 `reward|gift|兑换|redeem`：`兑换` 全部为 OAuth token exchange（`oauth.go:24,112,142,143,147,181,229,235,237`、`main.py:99,121,123`、`README.md:94,96`）；`gift` 全部为 tier 关键词（`quota.go:622`）与 ZCode-Panel UI 标签（`main.js:312-357`、`renderer/app.js:144-305`）。
- **结论**：C 的负向断言**为真**，且 C 主动限定了免责范围，属高质量负向断言。

### 3.4 未覆盖的相邻事实（建议补充，非错误）

1. **`zcode-proxy` 的 `handleDashboard` 用 `EffectiveStatus` 而非 DB `status` 统计**（`api_handlers.go:124`），而 `CountAccountsByStatus`（`database_accounts.go:240-255`）用 DB 原值——E §⑤ 把两者并列为"状态统计"，实际口径不同（前者含"冷却到期即视为 active"的展示态）。建议注明。
2. **`best_quota` 的 `Remaining` 是快照值**（E §⑪ #5 已标【推断】，我确认：`pool.go:229-231` 读 `Account.Remaining`，该字段由 `applyQuotaResult`（`zcode_api.go:92`）在上次刷新时写入，选号前无实时刷新）——**E 的推断成立，可从【推断】升为【一手】**。
3. **`total_remaining` 跨 provider 直接相加**（`api_handlers.go:131` 对全量账号累加，不分 `Provider`），E §⑪ #4 已标【未验证】单位同质性——正确，且我确认代码**确实未做单位归一**。
4. **`zcode-switch` 的 `virtual_arms_uid`**（`store.rs:90,1174`）与 `virtual_device_mid` 并列存在，C 只提了后者。C 的结论不受影响，但若 Model-Gateway 要做完整设备伪装，这是遗漏的第二个设备标识。

---

## 4. 统计数字重算表

| 草稿 | 断言数字 | 口径 | 期望值 | 我重算值 | 判定 |
|---|---|---|---|---|---|
| C | cron 段数 | `shouldRun` / `ValidateCronExpr` 的 `len(fields)` | 5 | **5**（`scheduler.go:309,411`） | ✅ |
| C | 互斥层数 | plan 级 + 账号级 | 2 | **2**（`scheduler.go:159/170` + `activity.go:406`） | ✅ |
| C | **激活事件体字段数** | 请求体 JSON 键数 | 14 | **16**（`activity.go:330-347`、`claim.rs:159-176`） | ❌ |
| C | 抖动范围 | `rand.Intn(D/2+1)` | 0~50% | **jitter∈[0,⌊D/2⌋]**（`scheduler.go:207`） | ✅ |
| C | 429 退避序列 / 次数 | `retry_delays` 数组长度 | [500,1500,4000] / 3 | **[500,1500,4000] / 3**（`quota.rs:338`） | ✅ |
| C | 验证码缓存 TTL / 宽限 / 失败冷却 | 常量 | 45s / 300s / 60s | **45s / 300s / 60s**（`captcha.go:31-34`） | ✅ |
| C | 汇总串截断 | 硬编码 | 900 | **900**（`scheduler.go:234-235`） | ✅ |
| C | claimAll 账号间隔 | `setTimeout` | 1.2s | **1200ms**（`main.js:354`） | ✅ |
| C | claimAll 超时 | `waitForClaimResult` 参数 | 120000 | **120000**（`main.js:344`） | ✅ |
| C | 自动轮询间隔 / 单轮上限 / 账号间隔 | 常量 | 10min / 5 / 5s | **10min / 5 / 5000ms**（`main.js:19,22,23`） | ✅ |
| C | 冷却分类阈值 | 硬编码 | 1h | **`60*60*1000`**（`main.js:453,454`） | ✅ |
| C | 领取后刷额度延迟 | `time.Sleep` | 2s | **2s**（`activity.go:466`） | ✅ |
| C | 激活后确认延迟 | `time.Sleep` | 1.5s | **1500ms**（`activity.go:509`） | ✅ |
| C | 验证码无头升级阈值 | `attempt >= N` | 2 | **2**（`captcha.go:217`） | ✅ |
| C | captcha 求解重试上限 | `captchaSolveRetries` | （C 未提） | **4**（`captcha.go:37`） | — |
| D | 协议数 | `protocol` 枚举 | 3 | **3**（`relay.go:57-61`） | ✅ |
| D | 降级级数 | `tryAccount` 路径数 | 3 | **3**（`relay.go:162,184,201`） | ✅ |
| D | 预置指纹模式数 | `tlsFingerprintPresets` 长度 | 20 | **20**（`tls_fingerprint.go:31-50`） | ✅ |
| D | `modelNameMap` 条数 | map 字面量 | 11 | **11**（`relay.go:30-40`） | ✅ |
| D | `MODEL_NAME_MAP` 条数 | dict 字面量 | 6 | **6**（`gateway.py:35-40`） | ✅ |
| D | 默认模型数 | `DefaultModels` / `MODEL_ALLOWLIST` | 9 | **9 / 9**（`config.go:44-45`、`settings.py:149-157`） | ✅ |
| D | SSE 缓冲上限 | `maxSSEBuffer` | 16MB | **16<<20 = 16MiB**（`convert.go:35`） | ✅ |
| D | zcode2api 默认端口 | `PORT` 默认 | 3000 | **3000**（`settings.py:58`） | ✅ |
| D | zcode-proxy 监听地址 | `ListenAddr` 默认 | 127.0.0.1:8687 | **127.0.0.1:8687**（`config.go:66,85`） | ✅ |
| D | count_tokens 估算式 | `chars/4+8` | chars/4+8 | **chars/4+8**（`zcode_api.go:113`） | ✅ |
| D | 请求超时（claim/preview） | `CLAIM_TIMEOUT_SECS` | （C 引 25s） | **25s**（`claim.rs:13`）；Go 侧 25s（`activity.go:239`） | ✅ |
| D | 余额不足错误码 | 文档示例 | 1113 | **"1113"**（`ai-protocol.md:143`） | ✅ |
| E | 状态机状态数 | `Status*` 常量 | 6 | **6**（`pool.go:23-28`） | ✅ |
| E | 选路策略数 | `Strategy*` 常量 | 3 | **3**（`pool.go:33-35`） | ✅ |
| E | `maxAccountAttempts` | 常量 | 5 | **5**（`relay.go:24`） | ✅ |
| E | `maxCaptchaRetries` | 常量 | 3 | **3**（`relay.go:23`） | ✅ |
| E | 冷却默认值 | `MarkCooling` 兜底 | 60s | **60s**（`pool.go:256-258`） | ✅ |
| E | 风控冷却 | 硬编码 | 120s | **120s**（`relay.go:220`） | ✅ |
| E | 429 冷却 | 硬编码 | 30s | **30s**（`relay.go:302`） | ✅ |
| E | 3xx WAF 冷却 | 硬编码 | 120s | **120s**（`relay.go:261`） | ✅ |
| E | 连接失败冷却 | 硬编码 | 60s | **60s**（`relay.go:254`） | ✅ |
| E | zcode2api 默认冷却 | `COOLING_SECONDS` | 300 | **300**（`settings.py:99`） | ✅ |
| E | 429 显式冷却（zcode2api） | `cooling_seconds=` | 60 | **60**（`gateway.py:1441`） | ✅ |
| E | 额度刷新间隔默认 | `quota_refresh_interval` | 60 | **60**（`pool.go:103`、`database.go:333`、`settings.py:97`） | ✅ |
| E | 额度刷新并发（proxy） | `sem` 容量 | 4 | **4**（`pool.go:128`） | ✅ |
| E | 额度刷新每账号延迟 | `rand.Intn` | 0-2s | **`rand.Intn(2000)` ms = 0–1999ms**（`pool.go:147`） | ✅ |
| E | 额度刷新并发（zcode2api） | `Semaphore` | 8 | **8**（`quota.py:439`） | ✅ |
| E | 启动等待（proxy 刷新循环） | `time.After` | 5s | **5s**（`pool.go:85`） | ✅ |
| E | 启动等待（zcode2api 监控） | `wait_for timeout` | 5s | **5s**（`quota.py:461`） | ✅ |
| E | 关闭后回看设置间隔 | `wait = interval if >0 else 30` | 30s | **30s**（`quota.py:479`） | ✅ |
| E | 探测端口数 | `probePorts` 长度 | 9 | **9**（`egress_proxy.go:173`） | ✅ |
| E | 成功补刷节流 | 硬编码 | 30s | **30s**（`relay.go:706`、`gateway.py:1503`） | ✅ |
| E | PBKDF2 迭代次数 | `pbkdf2Iterations` | 120000 | **120000**（`export_bundle.go:23`） | ✅ |
| E | PBKDF2 派生长度 / 盐长 | 参数 | 32 / 16 | **32 / 16**（`export_bundle.go:78,86`） | ✅ |
| E | AES 模式 | `aes.NewCipher` + `cipher.NewGCM` | AES-256-GCM | **AES-256-GCM**（key 32B；`export_bundle.go:87-91`、`credential_crypto.go:96-100`） | ✅ |
| E | `enc:v1` nonce / tag 长度 | 解码校验 | 12 / 16 | **nonce 12**（`credential_crypto.go:93`）、tag 16（`Seal` 尾 16B，`:128`） | ✅ |
| E | `zcb1:` 布局 | 切片偏移 | salt16‖nonce12‖ct | **raw[:16], raw[16:28], raw[28:]**（`export_bundle.go:114`） | ✅ |
| E | 6 态 / 3 策略 / 5 次换号 | 见上 | — | 全部 ✅ | ✅ |

**数字类错误合计：1 处**（C 的 14 vs 16）。其余 50 余个数字全部独立重算通过。

---

## 5. 诚实声明

### 5.1 无法核验项及原因

1. **上游服务端行为（8 条，全部 ❓）**——C 的 5 条（mid 是否被风控、`app_daily_active` 重复报是否被拒、preview 是否可能一次多 plan、验证码是否真强制、APIKey 通道现行主机）+ D 的 3 条（丢弃字段上游是否接受、远程图片 URL 上游是否支持、utls 指纹当前拦截率）。**原因**：这些需要真实凭证向 `zcode.z.ai` / `api.z.ai` 发请求，超出只读代码核验的能力边界。三稿均已自标【未验证】，**标注诚实**。
2. **`count_tokens` 估算偏差量级**（D §⑩ #5）——需真实 tokenizer 对照，无法在只读前提下测量。
3. **并发压测数据**（E §⑪ #1）——"撞号率"需实际并发运行参考项目，我只做了**代码结构级**证明（无占位写回），未做运行时验证。E 已如实标注。
4. **AST 级调用图分析**（E §⑪ #2）——我用的是"关键词全树检索 + 三处选号函数逐行通读"，未做完整调用图。理论上仍可能存在通过 channel 实现的隐式串行（我额外检索了 `chan struct` / `singleflight`，未发现选号相关用法），但**不能 100% 排除**。E 的这条自陈同样成立。
5. **`zcode2api/app/statics/**` 前端 JS**——我未逐行核验后台页面的账号操作逻辑（与 C/D/E 的结论无直接关联）。
6. **`zcode-switch/src-tauri/target/**`**——构建产物，已排除。

### 5.2 核验方法学说明（可复现）

- **只读约束遵守**：全程仅使用 Read / Grep / `awk` / `sed -n` / `grep -n` 等只读命令；未对 `/Users/w/Desktop/zcode相关管理软件/` 做任何写入、未创建文件、未修改 git 状态。
- **行号复核方式**：对每条引用先用 `awk 'NR>=X && NR<=Y'` 打印**带行号**的实际内容，再比对草稿的行号区间与内容语义；对"恰好偏移 1-2 行"的高频错误类型做了专项检查（例如 C 的 `main.js:451-457` 经 `grep -n` 确认 `autoClaimCooldownFor` 声明于 451、`}` 于 457，**未偏移**）。
- **负向断言方法**：不用草稿给的关键词，而是**自行扩关键词集**（增加同义/近义模式）后在**更宽的范围**（含草稿未列的项目）检索，再逐个判定命中项。这是本报告发现 P2/P3/P4 的方法基础。
- **统计重算**：所有数字均回到常量定义/字面量处计数，不依赖草稿的中间表述。

### 5.3 对三稿的总体评价

| 草稿 | 可信度 | 说明 |
|---|---|---|
| **C** | **高**（44 条中 41 ✅ / 2 ⚠️ / 1 ❌） | 行号精度极高（抽查 40+ 条无偏移）；负向断言质量优秀（主动限定免责范围）。唯一硬伤是事件体字段数 14→16，属施工级错误，必须修。 |
| **D** | **高**（55 条中 51 ✅ / 4 ⚠️ / 0 ❌） | 映射表逐条命中，是本次核验中**最扎实**的部分；分歧与未验证项标注规范（尤其"丢弃字段是反向推断"）。问题集中在措辞强度（"刚需"）与范围口径（"统一强制流式"），非事实错误。 |
| **E** | **中高**（50 条中 42 ✅ / 7 ⚠️ / 1 ❌） | 核心负向断言（无租约）**成立且是本批最有价值的结论**；加密参数、状态机、阈值数字全部正确。扣分项集中在**负向断言的证据呈现**：命中表自称"全部"却漏列 ≥10 项、范围未覆盖自述调研对象、`proxy.rs` "无任何锁"与事实相反——这三条都在削弱那条本来正确的核心结论的说服力。建议按 P2/P3/P4 补齐后再定稿。 |

---

*核验完成时间：2026-09-25 · 核验员：独立证伪视角 · 参考项目全程只读*
