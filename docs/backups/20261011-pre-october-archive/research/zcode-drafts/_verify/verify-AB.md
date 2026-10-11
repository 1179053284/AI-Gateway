# 独立核验报告 · A 稿（账号接入与切换）/ B 稿（套餐与配额）

> 核验员角色：**证伪**。L1（引用可解析）由主 agent 完成，本报告只做 **L2 正向内容断言 / L3 负向断言 / L4 统计重算**。
> 核验基准（**全程只读，未修改任何参考项目文件**）：
> - A 稿：`/Users/w/Desktop/zcode相关管理软件/{zcode-switch, zcode-account-switcher, zcode-switcher}/`
> - B 稿：`/Users/w/Desktop/zcode相关管理软件/zcode-reverse-engineer/`（下称 `RE/`）
> - 交叉核验范围：整个 `zcode相关管理软件/`（排除 `node_modules/`）
> 核验日期：2026-09-25
> 核验脚本/临时产物：无落盘（全部为只读 `sed`/检索），未在参考仓写入任何文件。

**总结论**：A 稿行号精度极高（抽查 40+ 处区间几乎全部逐字命中），主要缺陷是 **1 条被证伪的负向断言**（refresh）+ 3 处 off-by-2 引用 + 1 处引到错误分支。B 稿在**证据分级诚实度上表现好**（主动标注 `[推测]`/`[预期响应]`/文档冲突），但存在 **2 条被证伪的结论**（"不存在 claim 端点"、"21 个模型"）+ 1 条**虚构的矛盾**（Pro Max 倍数）+ 1 处**不支持结论的引用**。最严重的是 **B 的"不存在 claim 端点"与 A 的"存在 claim 端点"直接冲突，而 A 是对的**——这直接改变网关的可行性判断。

---

## 1. 核验结论表

### 1.1 A 稿 · 决策级断言

| # | 断言（A 稿原表述） | 结论 | 证据（文件:行号）与原文片段 |
|---|---|---|---|
| A1 | `credentials.json` 是**扁平 map**，值为 `enc:v1:` 或明文 | ✅证实 | `zcrypto.rs:132-136` 直接 `creds.as_object()` 后 `map.get("oauth:active_provider")`；`zcodeCrypto.js:42-51` 同样是 `rawCred['oauth:active_provider']` 平铺取键。值为 `enc:v1:` 或明文：`zcrypto.rs:137` `if is_encrypted(ap) { decrypt } else { Some(ap.to_string()) }` |
| A2 | 键名 `oauth:active_provider` | ✅证实 | `zcode-switch/src-tauri/src/zcrypto.rs:136` `map.get("oauth:active_provider")`（**行号精确**） |
| A3 | 键名 `oauth:<p>:access_token` | ✅证实 | `zcode-switch/src-tauri/src/oauth.rs:449` `m.insert(format!("oauth:{provider}:access_token"), json!(at));`（**行号精确**） |
| A4 | 键名 `oauth:<p>:refresh_token`，仅部分流程写入 | ✅证实 | `oauth.rs:452` 写入；`oauth.rs:426-436` `extract_refresh_token` 首行 `if provider != "bigmodel" { return None; }` → 仅 bigmodel 提取（**行号精确**） |
| A5 | 键名 `oauth:<p>:user_info` / `zcodejwttoken` | ✅证实 | `oauth.rs:455` / `oauth.rs:446`（**行号精确**） |
| A6 | `enc:v1` = **AES-256-GCM** | ✅证实 | `zcrypto.rs:3` `use aes_gcm::{Aes256Gcm, Nonce}`；`zcrypto.rs:86` `Aes256Gcm::new_from_slice(&key)` |
| A7 | 格式 `enc:v1:<b64url(nonce 12B)>.<b64url(authTag 16B)>.<b64url(ct)>` | ✅证实 | `zcrypto.rs:10` `PREFIX="enc:v1:"`；`zcrypto.rs:82` `nonce_b.len() != 12`；`crypto.rs:23-24` `NONCE_LEN=12 / TAG_LEN=16`；三处均 `URL_SAFE_NO_PAD` |
| A8 | **key = SHA256(secret)**，`secret = env ZCODE_CREDENTIAL_SECRET ?? \`zcode-credential-fallback:${platform}:${homedir}:${username}\`` | ✅证实（**逐字命中**） | `zcrypto.rs:42-44` `format!("zcode-credential-fallback:{}:{}:{}", platform, home, username)`；`zcrypto.rs:46-49` env 优先；`zcrypto.rs:62-67` `Sha256::digest(secret.as_bytes())`。三处实现字符串完全一致：`zcrypto.rs:43` / `crypto.rs:52-56` / `zcodeCrypto.js:26` |
| A9 | 算法顺序：**先拼 secret 再整体 SHA256**（不是先 hash 各段） | ✅证实 | `zcrypto.rs:59` `compose_fallback_secret(node_os(), &home.display().to_string(), &username)` → `zcrypto.rs:63` `Sha256::digest(secret.as_bytes())`。顺序为 `platform:home:username`（`zcrypto.rs:43` 参数序 `platform, home, username`），与 A 稿写法一致 |
| A10 | platform 取值 `darwin / win32 / linux` | ✅证实 | `zcrypto.rs:12-18` `"windows"=>"win32"`, `"macos"=>"darwin"`, `other=>other`（Linux 即 `"linux"`）；`crypto.rs:66-83` 显式三分支 |
| A11 | 解密 tag 拼接顺序 = `ciphertext ‖ tag` | ✅证实 | `zcrypto.rs:87-88` `let mut buf = ct_b.clone(); buf.extend_from_slice(&tag_b);` |
| A12 | `config.json` 有 **6 条** builtin provider，按 family 分两组 | ✅证实 | `zcode-switcher/.../profile.rs:357-376` 常量 `BUILTIN_PROVIDERS_BY_FAMILY`，注释 `/// ZCode 6 条内置 provider，按 family 分组`；独立佐证：`zcode-switch/.../oauth.rs:646-676` 恰好 `insert` 这 6 个 key |
| A13 | `apiKey` 是**明文 JWT 含 `user_id`** | ⚠️部分证实 | 成立但**非全集**。`oauth.rs:652-655`（`builtin:bigmodel-start-plan`）、`664-667`（`builtin:zai-start-plan`）的 apiKey = `jwt`（明文）；`builtin:zai` 的 apiKey = `""` 且 `enabled:false`（`oauth.rs:659-662`）。`fingerprint.js:88` 显式 `if (apiKey.startsWith('enc:') || apiKey.length < 30) continue;` → 指纹只对"有 apiKey 的 provider"成立。A 稿写成普适结论，**方向对、覆盖范围略宽** |
| A14 | 切号需**删 `coding-plan-cache.json`** | ✅证实 | `store.rs:641-648` `reset_live_plan_cache()` `fs::remove_file(&p)`；`profile.rs:1132-1136` `if mode == "oauth" { ... join("coding-plan-cache.json") ... remove_file }`（**行号精确**） |
| A15 | 切号需**锁 `setting.json`**（否则权益/路由串号） | ✅证实 | `store.rs:650-666` `align_family_domain` 写 `providerFamilyDomain` + `providerFamilyDomainUpdatedAt`（**行号精确**）；`profile.rs:1123-1127` `write_in_place(&setting_path, ...)` + 注释 `// 锁定 modelProviderFamilyModes.zai = "oauth" 与 providerFamilyDomain = "zai"`（**行号精确**） |
| A16 | `hot_switch`（不杀进程）在 **`store.rs:882-920`** | ✅证实 | `store.rs:882` `fn hot_swap_verified(...)`，`store.rs:920` 函数闭合（`grep` 显示下一个 `fn` 在 922）。**行号逐字精确** |
| A17 | hot 分支"最多 3 轮、两轮一致、250ms 递增退避" | ✅证实 | `store.rs:894` `for attempt in 0..3u32`；`store.rs:902-909` 读回→verify→sleep 150ms→再读回→verify；`store.rs:893` `250 + attempt*250`（即 250/500/750ms） |
| A18 | 原地 truncate 写在 **`profile.rs:620-636`** | ✅证实 | `profile.rs:620-627` 注释，`profile.rs:628` `fn write_in_place(...)`，`631-633` `.truncate(true)`，`636` 闭合。**行号逐字精确** |
| A19 | `fingerprint.js` 是**账号身份指纹**（非设备指纹） | ✅证实 | `fingerprint.js:5-8` 注释 `账号指纹提取`、`config.json 里「启用中的 provider」apiKey 是明文 JWT…payload 含 user_id —— 这是最稳定的账号唯一标识`；`fingerprint.js:76-116` 全流程无任何设备维度字段 |
| A20 | 设备虚拟化是 `virtual_device_mid` / `virtual_arms_uid` | ✅证实 | `store.rs:1015-1085`（device_mid，`Uuid::new_v4()`，写 `telemetry-state.json.deviceMid`）；`store.rs:1089-1098` `new_arms_uid()` 格式 `format!("uid_{suffix}")` + `take(16)`；`store.rs:1219-1259` 写 `_arms_uid` 并 `obj.remove("_arms_session")`（**行号精确**） |
| A21 | arms 目录名 `rum-electron-store/*.json`，macOS 走 `~/Library/Application Support/ZCode` | ✅证实 | `store.rs:1125` `.join("rum-electron-store")`；`store.rs:1154-1158` `HOME + "Library" + "Application Support"`（**行号精确**） |
| A22 | `X-Device-Mid` 请求头透传 | ✅证实 | `quota.rs:195-197` `if let Some(mid) = mid { h.push(("X-Device-Mid".into(), mid)); }`（**行号精确**） |
| A23 | `hot_switch` 全流程（sync_back → auto_preserve → hot_swap_verified → backfill → 删 cache → 写 mid） | ✅证实 | `store.rs:776-799`，与 A 稿列举顺序逐条对应（**行号精确**） |
| A24 | 同账号短路（hash 或 identity 匹配 → `already_active`） | ⚠️部分证实 | `store.rs:741-773` 逻辑成立（**行号精确**）。但 A 稿说"**只**回写 deviceMid/armsUid 后返回"——实际 `store.rs:752-755` 在 `hash` 不同时**还会调 `sync_live_back_to_source`**。属轻微遗漏 |
| A25 | `oauth:<p>:access_token` 语义不一致（zai OAuth token vs business token） | ✅证实 | `oauth.js:227` 存 `tokenSet.zaiAccessToken`（原始）；`zcode-switch/.../lib.rs:637-641` zai 分支调 `resolve_zai_business_token` 后存入。`quota.js:154-156` 注释 `oauth:*:access_token 是 chat.z.ai 的 OAuth token，查 zcode billing 会 401` |
| A26 | `zcodejwttoken` 是调计费接口的**唯一**正确 token | ⚠️部分证实 | `quota.js:154-156` 原文是"**才是**调 zcode.z.ai/billing 的正确 token，**必须排最前**"，且 `quota.js:157-159` 仍把 access_token 作为**后备候选**加入列表。A 稿的"唯一"是**强化**（"排最前" ≠ "唯一"）。另：该结论来源是工具作者的代码注释，非实测 |
| A27 | `zcode_cdp.rs` / `zcode_launcher.rs` **在本副本中缺失** | ✅证实（A 稿的亮点） | `zcode-switcher/src-tauri/src/lib.rs:11-12` `mod zcode_cdp;` `mod zcode_launcher;`；`ls -la` 该目录 13 个 `.rs` 文件中**确实没有这两个文件**（该 crate 当前无法编译）。A 稿主动标注【未验证】并说明 CDP 报文无法证实——**诚实且准确** |
| A28 | Mac 进程名清单含 4 个 Helper；仅 `ZCode` 作为主程序路径来源 | ✅证实 | `restart.rs:22-29` 5 个名字（`ZCode` + `ZCode Helper`/`(GPU)`/`(Plugin)`/`(Renderer)`）；`restart.rs:33-34` `MAIN_PROC_NAMES = &["ZCode"]`（**行号精确**） |
| A29 | macOS 启动用 `/usr/bin/open -n`，有参数时追加 `--args` | ✅证实 | `restart.rs:319-321` `Command::new("/usr/bin/open").arg("-n").arg(app)`；`restart.rs:352-356` `command.arg("-n").arg(app); if !tokens.is_empty() { command.arg("--args").args(&tokens); }` |
| A30 | `zcode-account-switcher` 进程控制是 Windows 硬编码 → Mac 不可用 | ✅证实 | `switcher.js:39` `execSync('tasklist /FI "IMAGENAME eq ZCode.exe" /NH /FO CSV')`；`switcher.js:55` `execSync('taskkill /F /IM ZCode.exe')`；`paths.js:29-35` 5 个候选路径**全为** `C:\`/`D:\`/`%LOCALAPPDATA%` |
| A31 | 导出信封 `zsw-accounts-bundle` / pbkdf2-hmac-sha256 / 100000 / aes-256-gcm | ✅证实 | `cipher.rs:11` `FORMAT_BUNDLE="zsw-accounts-bundle"`；`cipher.rs:12` `KDF_ITERS=100_000`；`cipher.rs:45-47` `kdf:{algo:"pbkdf2-hmac-sha256",iters,salt}` + `cipher:{algo:"aes-256-gcm",nonce,tag,data}`（**行号精确**） |
| A32 | `fingerprint.js` 的 `emailShortId = 'em-' + simpleHash(email.toLowerCase())[:10]`（djb2 变体） | ✅证实 | `fingerprint.js:101` `'em-' + simpleHash(email.toLowerCase()).slice(0, 10)`；`fingerprint.js:146-150` `let h = 5381; h = ((h*33) ^ charCodeAt) >>> 0`（djb2） |
| A33 | `accountHealth.js` 是纯本地静态检查、状态机 `errors>0→error` | ✅证实 | `accountHealth.js:5-6` 注释 `只做本地结构与字段检查，不主动访问网络`；`accountHealth.js:147-148` `const status = errors.length > 0 ? 'error' : warnings.length > 0 ? 'warning' : 'healthy'`（**行号精确**） |
| A34 | **`refresh_token` 全线只存不用 / 全仓无任何 refresh 端点调用** | ❌**证伪** | 见 §3.1。`RE/zcode_auth.py:595-620` `cmd_refresh()` 真实 `POST {provider, refresh_token, grant_type:"refresh_token"}`；`RE/src/oauth.ts:294-303` 第二份实现；`RE/docs/auth/oauth-flow.md:578` 文档化 `python zcode_auth.py refresh`。**"三项目只存不用"成立，"全仓"不成立** |
| A35 | 三份实现 secret 推导"**逐字一致**" | ⚠️部分证实 | fallback **格式串**三处一致 ✅；但 **username 取值口径不同**：`zcrypto.rs:34-40` `id -un` 优先 → `crypto.rs:95` `env USER` → `zcodeCrypto.js:25` `os.userInfo().username`。**A 稿自己在下文 ③.1 坑位里指出了这个差异，与"逐字一致"自相矛盾**（且坑位只列了 2 种，漏了 JS 的第 3 种） |
| A36 | `web-remote-control:external-relay:pass_hash` 是"**非 ZCode 字段**" | ⚠️部分证实 | `store.rs:853` 常量 + `185-196` 被排除在 hash 外 ✅。但"非 ZCode 字段"是**推断**：A 稿自己在 ⑧.6 写"未找到它被哪个外部组件消费 → 【未验证】"。表内断言与未解决项口径不一致 |

### 1.2 B 稿 · 决策级断言

| # | 断言（B 稿原表述） | 结论 | 证据（文件:行号）与原文片段 |
|---|---|---|---|
| B1 | **不存在"激活/兑换"端点**，Start Plan 由服务端自动授予 | ❌**证伪**（就工作区口径） | `RE/docs/auth/activation-protocol.md:22` 原文确为"**关键发现：不存在客户端触发"领取/claim/activate"的 API 端点。**"——B 对 RE 文档的转述**忠实**；但**同一工作区** `zcode-switch/src-tauri/src/claim.rs:10` `BILLING_CLAIM_URL = "https://zcode.z.ai/api/v1/zcode-plan/billing/claim"`，`:272` `pub fn submit_claim(...)`，`:286` `agent().post(BILLING_CLAIM_URL)`，`:289` `X-Aliyun-Captcha-Verify-Param`。**存在可用的 preview + claim（带验证码）端点**。见 §3.1 |
| B2 | 全库检索 `激活码\|兑换\|redeem\|claim\|activate` 无兑换端点或码格式 | ⚠️部分证实 | 就 `RE/` 范围：`兑换`/`redeem`/`激活码` **零命中**（仅 `node_modules` LICENSE 噪声）✅；`claim`/`activate` 仅出现在 `activation-protocol.md:22`（否定句）与脚本名 `activate_playwright.py`。**B 未声明该检索的作用域**，读者会误以为覆盖全工作区 |
| B3 | 唯一带"码"的字段是支付参数 `invitationCode`（非兑换码） | ✅证实 | `RE/docs/models/billing.md:232` `invitationCode: data.invitationCode`、`:244`、`:253`（**行号精确**，与 B 引用一致） |
| B4 | 两条互不相干的请求通道（API Key / Plan） | ✅证实 | `RE/memory-notes/zcode-plan-auth-path.md:8-11` 表格（`x-api-key: <密钥>` vs `Authorization: Bearer <zcode_jwt>`）；`RE/docs/models/free-quota.md:24-27` 同构表格。原文 `free-quota.md:22` 逐字为"ZCode 有两条互不相干的请求通道" |
| B5 | Plan 通道 base = `https://zcode.z.ai/api/v1/zcode-plan/anthropic` + `Bearer JWT` | ✅证实 | `zcode-plan-auth-path.md:11`、`:18`；`free-quota.md:27`、`:33` 逐字一致 |
| B6 | 中转站 `zcode-2api` 走 `api.z.ai/api/anthropic` + `x-api-key: JWT` **"不一定会扣免费额度"** | ✅证实（引用精确 + 诚实标注未实测） | `zcode-plan-auth-path.md:48-49` 逐字；`:53` 原文 `需要实测确认该入口对免费账号返回模型响应，并核对 billing/current 的额度扣减` → B 标 `[反编译+未实测]` ✅ |
| B7 | 免费额度 = **每日 token 配额**，GLM-5.3 **3M** + GLM-5-Turbo **2M**，`unitType:"token"`、`period:"daily"` | ✅证实（**数字逐字命中**） | `RE/docs/models/client-configs.md:73` `"grantUnits": 3000000`、`:76` `"showName": "GLM-5.3"`、`:77` `"unitType": "token"`、`:75` `"period": "daily"`、`:80` `2000000`、`:83` `"GLM-5-Turbo"`（**行号精确**） |
| B8 | **无"积分"概念** | ✅证实 | 全 `RE/**.md` 检索 `积分` **零命中**；`credit`/`point` 仅命中 `checkpoint`/`endpoint`/`pointStart` 等无关词 |
| B9 | `client/configs` **免认证**即可拉免费额度配置 | ✅证实（**三方独立佐证**） | ①`RE/docs/models/client-configs.md:13` `**不需要任何认证**，任何人都可以访问。`；`:65` `无论账号登录与否返回一致的权益`；②代码侧独立佐证：`zcode-switch/src-tauri/src/claim.rs:316` `agent().get(CLIENT_CONFIGS_URL)` 配 `quota::zai_billing_headers("")`（**空 token**）→ 确实免认证 |
| B10 | `client/configs` 客户端 1h 缓存 + 15s 超时 | ✅证实 | `client-configs.md:19` `// 请求频率: 最多每 1 小时请求一次 (o5 = 3600 * 1000)`、`:20` `// 超时: 15 秒 (Jc = 15 * 1000)`、`:42` `Date.now() + 3600000`、`:37` `timeoutMs: 15000`（**行号精确**） |
| B11 | 额度数字与模型名解耦（`showName` 可改、`grantUnits` 不变） | ✅证实 | `client-configs.md:100` 逐字 `注意：免费档 showName 官方可随时调整（2026-06 分析时为 GLM-5.2，2026-08-18 实测已为 GLM-5.3），grantUnits 数字保持不变` |
| B12 | 判定逻辑 `plans[].status==="active"` 且 plan_id/name 含 `start-plan` | ⚠️部分证实 | `activation-protocol.md:149-157` `rz()` + `:159-162` `XN()`（**行号精确**）。**漏了一个边界**：`activation-protocol.md:154` `let isStartPlan = !planId && !name ? true : XN(planId) || XN(name);` → **plan_id 与 name 同时为空时也判为 Start Plan**。B 的简化描述会漏掉这一支 |
| B13 | `fetchZaiPlanEntitlementState` 并行查两处，返回 `{authenticated,startEntitled,codingEntitled}` | ✅证实 | `activation-protocol.md:165-175` `Promise.all([KY(...), HY(...)])` + 返回三字段（**行号精确**） |
| B14 | `billing/current` 直连 401，Playwright 无头也 401 → 文档结论**不是 WAF JS Challenge 而是缺 `data.token`** | ✅证实（引用与标注均精确） | `activation-protocol.md:209` `Playwright Chromium (无头) \| ❌ 401 \| WAF 非 JS Challenge，是认证问题`；`:214` `说明 **不是 WAF 的 JS Challenge 问题**`；`:218` `**可能**认的是…另一个字段——data.token`。B 标 `[实测 401 / 根因 ⚠️推测]` ✅ **诚实度正确** |
| B15 | `oauth-flow.md:253-269` 的实测响应里**没有** `data.token` → 两文档说法不一致 | ✅证实（**高质量交叉验证**） | `oauth-flow.md:253-269` 响应体仅有 `data.zai.access_token` / `refresh_token` / `expires_in` / `user`，**确无 `data.token`**。B 的判断成立 |
| B16 | `plans[]` / `balances[]` 结构来自"**预期响应**"、数值为示例 | ✅证实（诚实标注） | `activation-protocol.md:61` `### 2.3 预期响应`；`:71-73` `total_units:3000000 / used_units:0 / available_units:70`——**内部自相矛盾**（0 已用却只剩 70），反证其为示例值。B 标 `[反编译，数值为示例]` ✅ **标注正确**（核验员补充：该示例内部不自洽，可作为"非实测"的额外证据） |
| B17 | 无额度时返回 `kind:"unavailable", reason:"coding_plan_not_entitled"` | ✅证实 | `zcode-plan-auth-path.md:44` 逐字 |
| B18 | `capabilities[]` + `entitlements[].showName` 是判断可用模型的权威字段，"都来自服务端，客户端不硬编码" | ❌**引用不支持** | B 引 `activation-protocol.md:22` + `client-configs.md:18`。**两处原文均与"可用模型权威性"无关**：`:22` 是"不存在领取端点"，`client-configs.md:18` 是 `// source: host/index.js — client configs 解析`。结论本身可讨论，但**所引证据不成立**（且客户端确实硬编码了 provider 清单：`catalog.md:62-73`） |
| B19 | 套餐优先序（Coding Plan 优先 → Start Plan → `coding_plan_not_entitled`） | ✅证实（**并主动标注了文档自身的不确定性**） | `ANALYSIS_REPORT.md:762-773`；B 标 `[反编译，文档自标 ⚠️推断]`，而 `:762` 标题确为 `### 8.5 套餐优先序 ⚠️` ✅ **标注与原文一致** |
| B20 | 免费额度由服务端在模型调用时自动授予扣减；401 通常只是 JWT 过期 | ✅证实 | `free-quota.md:65` 逐字 `billing/current 返回 401 通常是 JWT 过期，不代表免费额度不存在。免费额度在调用模型时由服务器扣减`；`client-configs.md:105` 同义 |
| B21 | 两条通道 + 四条 Bearer 查询端点（除 configs 外） | ⚠️部分证实 | `api-endpoints.md:57-64` 该表实为 **6 行**（5 个 Bearer + 1 个免认证 configs），B 漏了 `open.bigmodel.cn/api/biz/subscription/list`（`:64`）。且 B 称"全部 `Bearer <zcode_jwt>`"，但 `api-endpoints.md:59-60` 明确写的是 **`Bearer JWT (zcode.z.ai session)`**——**与"同一个 zcode_jwt"不是一回事**，这正是 B 自己在 ③ 里点出的未解疑点 |
| B22 | `PRESET_PROVIDERS` 10 条 | ✅证实 | `catalog.md:62-73`（**逐条核对 10 条**）；`ANALYSIS_REPORT.md:477-488` 同构（B 引 `474-489` ✅） |
| B23 | 模型目录 **21 个模型** | ❌**证伪** | 实际 **20 个**。`catalog.md:11-19`(GLM 9) + `:25-26`(DeepSeek 2) + `:32-33`(Kimi 2) + `:39-41`(Qwen 3) + `:47-48`(MiniMax 2) + `:54-55`(MiMo 2) = **20**；`ANALYSIS_REPORT.md:498-537` 亦为 **20**。**"21" 仅出现在 `docs/index.md:151`**（且 B 引的 `ANALYSIS_REPORT.md:45`/`491-493` 两处**都不含任何数字**）。**B 自己第 142 行的枚举也恰好是 20——B 内部自相矛盾且未察觉** |
| B24 | 格式映射（claude/glm/codex/opencode/gemini/zai/bigmodel） | ✅证实 | `catalog.md:80-86` 七行逐字对应（**行号精确**） |
| B25 | `entitlements[]` 校验函数是 **5 字段**类型检查 | ✅证实 | `client-configs.md:183-187` 恰为 5 个 `typeof` 检查：`grantUnits`/`meter`/`period`/`showName`/`unitType`（**数字精确**） |
| B26 | 错误码表（`code=2007` / 401 空 body / `code=500` / 429+`1113` / `state mismatch`） | ✅证实 | `oauth-flow.md:552-556` 5 行逐条对应；`456-466` 的 `"[1113][Insufficient balance or no resource package.]"` 亦逐字 |
| B27 | `billing.md:51-55` 与 `client-configs.md:117-121` 对 Pro Max 倍数**口径不一致**（"4 倍" vs "20x Lite"） | ❌**证伪（虚构的矛盾）** | `billing.md:54-55`：Pro = "Lite 的 **5** 倍额度"，Pro Max = "**Pro** 的 4 倍额度"；`client-configs.md:120-121`：Pro = "**5x** Lite"，Pro Max = "**20x** Lite"。**4 × 5 = 20 —— 两份文档完全等价，只是基准（Pro vs Lite）不同**。B 报了一个不存在的矛盾 |
| B28 | Coding Plan 定价（BigModel ¥49/149/469，Z.AI ¥18/72） | ✅证实 | `client-configs.md:119-121`（49/149/469）+ `:127-128`（18/72）；`billing.md:53-55` 同价 |
| B29 | `codingPlanBillingDiscount` 限时 150% 额度文案 | ✅证实 | `client-configs.md:135-143` `"150% Quota"` / `"150% 额度"`（**行号精确**） |
| B30 | `codingPlanStaticProducts` 结构含 `builtin:bigmodel-coding-plan` 键 | ⚠️部分证实 | `billing.md:66` `"builtin:bigmodel-coding-plan": [`——B 引 `billing.md:63`，**实际在 66 行，差 3** |
| B31 | 支付渠道（支付宝/微信 `/pay/create-sign`、Stripe、PayPal） | ✅证实 | `billing.md:169` `/pay/create-sign`、`:174-181` Stripe、`:183-189` PayPal（B 引 `166-192` ✅） |
| B32 | 订阅状态串 5 个 | ✅证实 | `billing.md:265-269` 5 行逐字；`ANALYSIS_REPORT.md:562-566` 同构（B 引 `559-568` ✅） |
| B33 | `quota/limit` 用文案 `不存在coding plan` 判无付费套餐（B 自评"脆"） | ✅证实 | `free-quota.md:61`；`zcode_auth.py:703` `if "不存在coding plan" in msg:`（B 引 `700-707` ✅）。B 主动加"脆，建议同时看 code"——**好的风险提示** |
| B34 | ZAPI 是内网开发地址，无实用价值 | ✅证实 | `integration-subsystems.md:29` `http://192.168.6.166:8080（开发环境）`；`:36-63` `loadZapiPresetProvider()`（**行号精确**） |
| B35 | "**可绕过登录先探权益**：`client/configs` 免认证…**这是网关最省事的一手数据源**" | ⚠️部分证实（措辞过度推论） | 接口免认证 ✅（B9）。但 `startPlanPreview` 是**与账号无关的静态套餐定义**，拿到的是"Start Plan 是什么"，**不是"这个账号有没有额度"**。B 自己在 ⑨ 写的是"拿…配置**做额度池元数据**"（正确），① 里的"探权益"会误导为"可免登录判定账号权益" |

---

## 2. 发现的问题清单（按严重度排序）

| # | 严重度 | 原表述 | 实际是什么 | 建议修正为 |
|---|---|---|---|---|
| P1 | **高** | **B**：「不存在客户端触发领取/claim/activate 的 API 端点」「激活码/兑换码机制 ❌ 不存在，不要按此设计」 | `zcode-switch/src-tauri/src/claim.rs:9-11` 定义 `BILLING_PREVIEW_URL` / **`BILLING_CLAIM_URL = .../zcode-plan/billing/claim`** / `CLIENT_CONFIGS_URL`；`:217` `preview_plans()`；`:272` `submit_claim()` → `:286` `agent().post(BILLING_CLAIM_URL)` + `:289` 阿里云验证码头；`:187` `report_activation_events()`。**A 稿 ⑦#20 正确记录了这个端点** | 改为：「RE 文档断言不存在 claim 端点（`activation-protocol.md:22`），但**同工作区的 zcode-switch 已实现 `POST /billing/claim`（含 preview + 验证码）**，`claim.rs:9-11,217,272-313`。两者冲突需实测。**"输入激活码领权益"确实不成立（无码格式），但"客户端主动 claim 计划"是存在的**」 |
| P2 | **高** | **B**：「模型目录…**21 个模型**」 | `catalog.md` 与 `ANALYSIS_REPORT.md` 均为 **20 个**（9+2+2+3+2+2）；"21" 只在 `docs/index.md:151` 出现；B 自己的枚举也是 20 | 改为：「**20 个模型**（`catalog.md:11-55`）。注意 `docs/index.md:151` 写 21，与目录表实际 20 条**不一致**，以目录表为准」 |
| P3 | **高** | **A**：「`refresh_token`…**全仓无任何 refresh 端点调用**」「refresh 流程完全缺失…需自行实现」 | `RE/zcode_auth.py:595-620` `cmd_refresh()` 真实调用 `POST token_url {provider, refresh_token, grant_type:"refresh_token"}`；`RE/src/oauth.ts:294-303` 第二份实现；`RE/docs/auth/oauth-flow.md:578` 文档化 `python zcode_auth.py refresh` | 改为：「A 稿所查的 **3 个项目**只存不用；但**同工作区 `zcode-reverse-engineer` 已实现 refresh**（`zcode_auth.py:595-620`、`src/oauth.ts:294-303`），**可直接移植，不必自行实现**」 |
| P4 | **中** | **B**：「`billing.md:51-55` 与 `client-configs.md:117-121` 对 Pro Max 倍数口径**不一致**（"4 倍" vs "20x Lite"）」 | 4×Pro、Pro=5×Lite → 4×5 = **20×Lite**。两文档**数学等价**，只是基准不同 | 删除该"矛盾"，或改为：「两文档表述基准不同（Pro 的 4 倍 ≡ Lite 的 20 倍），**换算后一致**」 |
| P5 | **中** | **B**：`capabilities[]` + `showName` 是权威字段，**都来自服务端、客户端不硬编码** → 引 `activation-protocol.md:22`；`client-configs.md:18` | 两处原文与"模型可用性权威性"无关（`activation-protocol.md:22` 讲的是领取端点不存在；`client-configs.md:18` 是 `// source: host/index.js` 注释）。且客户端**确有硬编码** provider 清单（`catalog.md:62-73`） | 换引 `activation-protocol.md:75`（`capabilities` 实测字段）+ `client-configs.md:76,83`（`showName`）；并把"客户端不硬编码"限定为**模型权益**，说明**provider 清单是硬编码的** |
| P6 | **中** | **A**：「锁 `modelProviderFamilyModes.zai="oauth"` / `providerFamilyDomain` → `profile.rs:895-907`」 | `profile.rs:895-907` 是 **`"apikey"` 分支（主动删除该 family 项）**，语义**相反**。真正的"锁 oauth"在 `:884-893`（`modes_obj.insert(family, "oauth")`），`providerFamilyDomain` 在 `:873-880` | 改为 `profile.rs:853-910`（函数 `prepare_setting_route_update`），关键行 `:873-880`（domain）、`:884-893`（oauth） |
| P7 | **低** | **A**：「原样拷贝 live 文件 → 保留 `enc:v1` → `store.rs:546`」 | `store.rs:546` 是 `updated_at: ts,`；"原样拷贝"是 **`:548` `credentials: live,`** | 改为 `store.rs:521-556`、关键行 `:548` |
| P8 | **低** | **A**：「探测 `tasklist …`（`switcher.js:37`）；关闭 `taskkill …`（`switcher.js:53`）」 | 实际 `tasklist` 在 **`:39`**，`taskkill` 在 **`:55`**（`:37`/`:53` 分别是 `function isZCodeRunning()` 与 `if (!isZCodeRunning()) return true;`） | 改为 `switcher.js:37-47`（探测）与 `switcher.js:52-62`（关闭） |
| P9 | **低** | **B**：「仅见一处键名 `builtin:bigmodel-coding-plan` → `billing.md:63`」 | 实际在 **`:66`**（`:63` 是 `// 从 client/configs 响应中提取`） | 改为 `billing.md:66` |
| P10 | **低** | **B**：「只给了"Lite=3x Claude Pro 用量"这类相对口径 → `billing.md:68`」 | 该文案在 **`:71`**（`:68` 是 `"productId"`） | 改为 `billing.md:71` |
| P11 | **低** | **A**：「渐进轮询…（**约 4 分钟**）」 | `oauth.js:181` 完整模式 delays `[1000,3000,6000,15000,30000,60000,90000,120000]` 求和 = **325s ≈ 5.4 分钟**（源码注释自己也写"约 4 分钟"）。快速模式 `[500,2000,5000]` = 7.5s ✅ | 改为「**约 5.4 分钟**（源码注释写"约 4 分钟"，与实测求和不符）」 |
| P12 | **低** | **A**：「三份实现**逐字一致**」（secret 推导） | fallback 格式串一致，但 username 取值三处不同（`id -un` / `$USER` / `os.userInfo()`）。A 稿 ③.1 坑位与 ⑧.5 已指出该差异 → **自相矛盾**，且坑位只列 2 种 | 改为「fallback 格式串三处逐字一致；**username 取值口径三处各不相同**（`zcrypto.rs:34-40` `id -un` 优先 / `crypto.rs:95` `$USER` / `zcodeCrypto.js:25` `os.userInfo()`）」 |
| P13 | **低** | **A**：「`web-remote-control:external-relay:pass_hash`…**非 ZCode 字段**」 | 只看到被注入/回填/排除在 hash 外，**未见消费方**（A 稿 ⑧.6 自己也说【未验证】） | 改为「**用途未知**（推断为外部组件字段，未找到消费方）」 |
| P14 | **低** | **B**：①「免费额度 = 积分吗 → **不是同一个东西，是同一层语义的两种叫法**」 | 该答案单元格**自身语义矛盾**（"不是同一个东西" vs "同一层语义的两种叫法"） | 改为「同一概念的不同叫法：文档中额度实体只有 `meter:"model_usage"` 的 token 配额，**无独立积分实体**」 |
| P15 | **低** | **B**：「**可绕过登录先探权益**」 | `startPlanPreview` 是**账号无关的静态套餐定义**，不能判定某账号是否被授予额度 | 改为「可免登录拉取**套餐定义（上限口径）**作额度池元数据；**账号级 entitlement 仍需登录**」 |

---

## 3. 遗漏与矛盾检查

### 3.1 跨稿直接矛盾（最重要）

**A 稿 ⑦#20**：「领取权益端点（preview / claim / configs）→ `claim.rs:9-11` ✅ 积分/权益聚合面」
**B 稿 ①#2**：「不存在客户端触发领取/claim/activate 的 API 端点…**此路不通**」「❌ 不存在，**不要按此设计**」

**核验判定：A 对，B 错（就工作区口径）。**

```
zcode-switch/src-tauri/src/claim.rs
:9   pub const BILLING_PREVIEW_URL: &str = "https://zcode.z.ai/api/v1/zcode-plan/billing/preview";
:10  pub const BILLING_CLAIM_URL:   &str = "https://zcode.z.ai/api/v1/zcode-plan/billing/claim";
:11  pub const CLIENT_CONFIGS_URL:  &str = "https://zcode.z.ai/api/v1/client/configs";
:217 pub fn preview_plans(home, creds, config, device_mid) -> ...   // GET preview?app_version&platform
:272 pub fn submit_claim(home, creds, config, plan_id, captcha_param, captcha_region, device_mid)
:286     let mut req = agent().post(BILLING_CLAIM_URL);
:289     req = req.set("X-Aliyun-Captcha-Verify-Param", captcha_param.trim());
:292     ...send_json(json!({ "plan_id": plan_id }))
:187 pub fn report_activation_events(user_id, device_mid)   // POST /api/v1/event/report
:204     i18n::trf("err.claim.activate_req", ...)             // i18n key 里就有 "activate"
```

**性质判定（避免反向过度推论）**：
- 存在的是 **`claim`（领取计划）+ `preview`（预览计划）**，且**强制阿里云验证码**。
- **仍然不存在**"输入激活码/兑换码"这种机制——`claim` 的入参是 `plan_id` + 验证码，不是"码"。所以 B 的"无兑换码格式"部分成立，**"不存在 claim/activate 端点"部分不成立**。
- B 的错误根源是**作用域**：B 只调研 `RE/`（其头部已声明），但把 `RE/` 内的文档结论**升格为对 ZCode 的整体判断**，且未与同工作区代码交叉验证。B 明明引用了同工作区的 A 稿作为二手（B:170,172），却漏掉了 A 稿 ⑦#20 这条相反证据。

### 3.2 其他矛盾

| 类型 | 内容 |
|---|---|
| **B 内部自相矛盾** | 第 141 行说"21 个模型"，第 142 行枚举恰好 20 个（9+2+2+3+2+2）；同一稿内未察觉 |
| **A 内部矛盾** | ②.1/③.1 说"三份实现**逐字一致**"，③.1 坑位/⑧.5 又说"**username 口径不一致**" |
| **A 内部口径不一** | ②.5 说 zcode-switcher 快照"**密文原样**"（`profile.rs:1039-1041` 确写原始 `cred_bytes`）；③.3 说 zcode-switcher"**全部 `crypto::encrypt()`**"（那是 `import` 路径，`profile.rs:539-551`）。两条**描述不同代码路径**却共用"落盘加密策略"这一栏，易误读 |
| **B 内部口径不一** | ③ 说 401 根因"缺 `data.token`"；⑤.2 说"401 **通常只是 JWT 过期**"。两种解释共存但未并列对账（B ⑩.1 承认未闭合，但 ⑤.2 的措辞偏断言） |
| **源文档本身冲突（B 已标注 ✅）** | `client-configs.md:99`（每日重置）vs `ANALYSIS_REPORT.md:714-723`（5h/周/月四维度）——B 正确标注并择一，处理得当 |
| **源文档本身冲突（B 已标注 ✅）** | `activation-protocol.md:236`（缺 `data.token`）vs `oauth-flow.md:253-269`（响应无该字段）——B 正确标注为 ❓需实测 |

### 3.3 该覆盖却漏掉

| # | 归属 | 遗漏内容 | 为什么重要 |
|---|---|---|---|
| M1 | **B** | **`data.token` 的存在性其实可从同工作区代码直接确认** | `zcode-switch/src-tauri/src/lib.rs:630` `.pointer("/data/token")`（缺则报 `err.oauth.no_token`）；`zcode-account-switcher/src/oauthCli.js:79` `if (!d.token \|\| !(d.zai && d.zai.access_token)) throw`。**两份独立实现都在读 `data.token`** → B 标为"❓必须先实测"的关键未知数，**在工作区内已有强旁证**。B 的 ⑩.1【关键阻塞点】本可降级 |
| M2 | **B** | **claim/preview 端点**（同 §3.1） | 直接决定"能否主动领取权益"这一产品决策 |
| M3 | **A** | **`zcode-switch` 存在第二套导出格式**：`store.rs:1284-1296` `export_bundle_value()` 产出 `{"format":"zcode-accounts-bundle","version":**2**, accounts:[{name,createdAt,credentials,config}]}`——**明文导出**（credentials/config 原样）。A ③.2 只描述了 `cipher.rs` 的 `zsw-accounts-bundle` v1（口令加密） | 两个 bundle 格式混在 ⑦#22 一行里；明文导出（v2）在账号搬运时是**安全敏感点**，A 未提示 |
| M4 | **A** | `oauth.js:15` 注释「**bigmodel 入口已移除（新流程仅 zai）**」；`oauth.js:31-34` `PROVIDER.providerIds = ['builtin:zai-start-plan','builtin:zai-coding-plan','builtin:zai']` | A ②.3 把 6 条 builtin 当对称两组讲，但 account-switcher 已**只支持 zai**，bigmodel 侧事实性缺失。影响"两 family 对称"这一隐含假设 |
| M5 | **A** | `store.rs:668-733` `rematerialize_wiped_builtins` 里 `in_sandbox()` 时**故意把 access_token 置空**（`:707-711`） | A ⑦#14 提到"重物化被清空的 builtin apiKey"，但未说明沙箱下行为不同（测试与生产不一致） |
| M6 | **B** | `RE/docs/models/billing.md` 的 `codingPlanStaticProducts` **只有 BigModel 侧**（`billing.md:66` 单键），而 `client-configs.md:123-128` 有 Z.AI 定价 | B ② 表格同时给了两套渠道价，但未指出"产品 ID 结构只在 BigModel 侧有样本" |

### 3.4 "把推断写成事实"专项（B 对象是逆向文档，此项尤其关键）

| 位置 | 文档说的是什么 | 稿件是否越界 |
|---|---|---|
| `activation-protocol.md:22` | 文档自标"关键发现"，来源是**逆向 JS Bundle**（文档 `:4` 声明），**未实测**（该文档 `:6` 自述"Start Plan **未激活**"） | B 标 `[反编译]` ✅ **未越界**。但 B 由此推出的**行动结论**（"此路不通/不要按此设计"）**越界**了（见 P1） |
| `activation-protocol.md:63-85` | 文档明确写 `### 2.3 预期响应` | B 标 `[反编译，数值为示例]` ✅ **未越界**（且核验员确认该示例 `total_units:3000000 / used_units:0 / available_units:70` 内部不自洽，可作非实测的旁证） |
| `ANALYSIS_REPORT.md:762-773` | 文档标题自带 `⚠️`，内容是 `javascript` 伪代码 | B 标 `[反编译，文档自标 ⚠️推断]` ✅ **未越界** |
| `zcode-plan-auth-path.md:44` | 文档写 `kind:"unavailable", reason:"coding_plan_not_entitled"`，来源标"ASAR 源码确认" | B 标 `[反编译]` ✅ **未越界** |
| `client-configs.md:99,107` | 文档写"实时验证（2026-08-18）"、`[实测]` | B 标 `[实测]` ✅ **未越界** |
| `client-configs.md:111-128`（定价） | 文档**未标注**该表来自实测还是反编译 | B 标 `[反编译]` ⚠️ **B 的自行判断**（偏保守，可接受，但未说明依据） |
| **A 稿** `profile.rs:620-627` | 代码注释写"让 ZCode 的 fs.watch（chokidar 类）识别成'同一个文件 modify'…部分 watcher 实现会因此漏掉变化"——这是**工具作者对 ZCode 客户端行为的假设**，未见验证 | A ⑦#10 写"**骗过 `fs.watch`**"（肯定语气）⚠️ **轻微越界**：应注明"依据源码注释的假设，未验证 ZCode 实际 watcher 行为" |
| **A 稿** `quota.js:154-156` | 代码注释（工具作者）称 `zcodejwttoken` 才是 billing 正确 token、access_token 会 401 | A 写成【一手】并强化为"**唯一**正确 token" ⚠️ **轻微越界**：这是工具作者的经验注释，非实测；且 `quota.js:157-159` 仍保留 access_token 作后备 |

---

## 4. 统计数字重算表

| # | 归属 | 断言 | 期望值 | **我重算值** | 口径 / 算式 | 判定 |
|---|---|---|---|---|---|---|
| S1 | A | `config.json` builtin provider 条数 | 6 | **6** | `oauth.rs:646-676` 6 个 `insert`；`profile.rs:359-376` 常量 2×3 | ✅ |
| S2 | A | macOS 进程名条数 | 5 | **5** | `restart.rs:23-29`：ZCode + 4 Helper | ✅ |
| S3 | A | `hot_swap_verified` 重试轮数 | 3 | **3** | `store.rs:894` `for attempt in 0..3u32` | ✅ |
| S4 | A | 退避步长 | 250ms 递增 | **250/500/750ms** | `store.rs:893` `250 + attempt*250` | ✅ |
| S5 | A | kill 等待时长 | 4s + 4s | **4s + 4s** | `store.rs:321` 软 4s；`:333` 硬 4s | ✅ |
| S6 | A | billing 轮询总时长 | "约 4 分钟" | **325s ≈ 5.4 分钟** | `oauth.js:181` `1000+3000+6000+15000+30000+60000+90000+120000` | ❌ 见 P11 |
| S7 | A | 快速检查模式时长 | （未提） | **7.5s** | `oauth.js:180` `500+2000+5000`；源码注释 `~7.5s` ✅ | — |
| S8 | A | PBKDF2 迭代次数 | 100000 | **100000** | `cipher.rs:12` `KDF_ITERS = 100_000` | ✅ |
| S9 | A | `enc:v1` nonce / tag 长度 | 12B / 16B | **12 / 16** | `zcrypto.rs:82`；`crypto.rs:23-24` | ✅ |
| S10 | A | arms uid 随机字符数 | 16 | **16** | `store.rs:1092` `.take(16)` | ✅ |
| S11 | A | `enc:v1` 三段 base64 段数 | 3 | **3** | `zcrypto.rs:75-78` `parts.len() != 3` | ✅ |
| S12 | A | hot 分支写入后读回次数 | 2 | **2** | `store.rs:903-909` `read_live` → verify → `read_live` → verify | ✅ |
| S13 | B | GLM-5.3 每日额度 | 3,000,000 | **3,000,000** | `client-configs.md:73` | ✅ |
| S14 | B | GLM-5-Turbo 每日额度 | 2,000,000 | **2,000,000** | `client-configs.md:80` | ✅ |
| S15 | B | 模型目录条数 | 21 | **20** | `catalog.md` 9+2+2+3+2+2；`ANALYSIS_REPORT.md:498-537` 同为 20 | ❌ 见 P2 |
| S16 | B | `PRESET_PROVIDERS` 条数 | 10 | **10** | `catalog.md:63-72` | ✅ |
| S17 | B | 套餐/计费端点条数 | "四条(Bearer) + configs" | **5 Bearer + 1 免认证** | `api-endpoints.md:59-64`（多出 `open.bigmodel.cn/api/biz/subscription/list`） | ⚠️ 见 P/B21 |
| S18 | B | `client/configs` 缓存 / 超时 | 1h / 15s | **3,600,000ms / 15,000ms** | `client-configs.md:19-20,42` | ✅ |
| S19 | B | `entitlements` 校验字段数 | 5 | **5** | `client-configs.md:183-187` | ✅ |
| S20 | B | 错误码条数 | 5 | **5** | `oauth-flow.md:552-556` | ✅ |
| S21 | B | 冲突文档的配额维度数 | 4 | **4** | `ANALYSIS_REPORT.md:720-723` | ✅ |
| S22 | B | Coding Plan 定价条数 | 3(BigModel)+2(Z.AI) | **3 + 2** | `client-configs.md:119-121` / `:127-128` | ✅ |
| S23 | B | `builtin:bigmodel-coding-plan` 出现位置 | `billing.md:63` | **`:66`** | 见 P9 | ❌ off-by-3 |
| S24 | B | "Lite=3x Claude Pro" 位置 | `billing.md:68` | **`:71`** | 见 P10 | ❌ off-by-3 |
| S25 | A | 2.5 表 zcode-switch 快照字段数 | 8 | **8** | `store.rs:542-552`：id/name/created_at/updated_at/hash/credentials/config/virtual_device_mid/virtual_arms_uid = **9** | ⚠️ A 写 8（漏了 `hash` 或把两 virtual 合并）——轻微 |

---

## 5. 诚实声明：我无法核验的部分

1. **所有"服务端真实行为"** —— 我没有执行任何真实 API 调用（无有效 ZCode 账号 / 不做外部请求）。因此以下只能"核对文档自述"而**不能证实事实本身**：
   - B 的 `[实测]` 项（`client/configs` 返回 3M+2M、`subscription/list` 返回 `{"code":200,"data":[]}`、`quota/limit` 返回 `code:500`、JWT payload 的 `user_id:8009570`）——**我只验证了"文档确实这么写了"**，无法验证这些数字/响应在 2026-09 仍成立。B 自己在 ⑩.9 已提示"接入前必须重跑一次"，**该提示必须保留**。
   - `billing/current` 401 的根因（`data.token` vs JWT 过期 vs WAF）——**无法判定**。我只能指出：`zcode-switch/src-tauri/src/lib.rs:630` 与 `zcode-account-switcher/src/oauthCli.js:79` **都要求响应里有 `data.token`**，这是"客户端期望存在"的强旁证，但**不能证明服务端确实返回**（也可能是文档作者把 `data.token` 与 `data.zai.access_token` 记混）。
   - `POST /billing/claim` 是否真的可用、`plan_id` 取值、验证码是否必填生效——**未实测**。我只证实"代码里存在并会被调用"，**不证实服务端接受**。
2. **`/billing/claim` 的业务语义** —— 我无法判定它是"免费 Start Plan 的领取"还是"付费 Coding Plan 的下单/激活"。`claim.rs` 有 `parse_plan`（`entitlements`/`grants`/`priority`）与验证码，更像**付费产品下单**；但 `BILLING_PREVIEW_URL` 与 `claim` 同域，**也可能是 Start Plan 领取**。**这决定了 P1 的最终修正措辞，需实测确认**。
3. **`zcode-switcher` 的 CDP 无感切号** —— `zcode_cdp.rs` / `zcode_launcher.rs` 在副本中**确实缺失**（A ⑧.1 成立），因此 `schedule_post_switch_refresh()` 的具体报文、`--remote-debugging-port=9229` 的注入细节**无法核验**。
4. **Mac 实机可用性** —— A 声称"zcode-switch 的 `pgrep`/`pkill`/`open` 在 Mac 可用"，我只验证了**代码分支存在且语法合理**，**未在 macOS 上实际运行**。同理"漏杀 Helper 会导致登录态被回写覆盖"是 A 的推断，我未实测。
5. **`CLI device flow` 是否已废弃** —— `oauthCli.js:5-7` 说 2026-06 起 404，但 `zcode-switch` 仍以它为主流程且**未见任何更新注释**。两方矛盾，**我无法判定哪个是当前现实**（A ⑧.2 已正确标为【未验证】）。
6. **`username` 口径差异的实际影响** —— A 说"`id -un` 与 `$USER` 不一致的环境（sudo/容器）会互相解不开"。逻辑成立，但我**未构造该环境实测**（A 已标【推断】，恰当）。
7. **`web-remote-control:external-relay:pass_hash` 的消费方** —— 全工作区未找到，**无法判定**其用途。
8. **`CLIENT_APP_VERSION` 不一致的服务端影响** —— `quota.rs:23 = "3.11.2"` vs `quota.js:17 = "4.1.10"` 我**已核实两处数值属实**，但"服务端是否按版本路由不同响应"**无法判定**。
9. **未逐条核验的低优先级引用**（时间预算内抽查通过，未做 100% 穷举）：A 稿 ⑦ 表的 #1-#23 中的 `zcrypto.rs:73-93`、`crypto.rs:100-160`、`zcodeCrypto.js:45-69`、`cipher.rs:20-68`、`store.rs:1045-1046`、`profile.rs:222-244`、`manager.js:5-9` 等我已抽验命中；B 稿的 `oauth-flow.md` 全区间、`catalog.md`、`api-endpoints.md`、`integration-subsystems.md`、`zcode_auth.py` 关键区间已逐条读原文核对。**A 稿 ⑦#19/#21/#22 与 B 稿 ⑨ 的少数行号我按抽样判定为可接受，未逐字核对**。

---

## 6. 给主 agent 的修订优先级建议

1. **必须先解决 P1**（B 的"不存在 claim 端点"）—— 它同时是 A/B 冲突点与网关可行性关键。建议主 agent 实测 `POST /api/v1/zcode-plan/billing/claim` 与 `GET .../billing/preview`。
2. **P2/P3 是数字与负向断言的硬伤**，直接改。
3. **P4/P5 是"报了不存在的矛盾"与"引了不支持结论的证据"**，属于逆向调研里最伤可信度的两类错误，建议在合并稿里统一复查所有"⚠️不一致"类断言。
4. **P6-P15 为引用精度问题**，A 稿行号总体极准（抽查命中率 >90%），建议按表逐条微调即可。
5. 建议在最终稿中**显式声明每份草稿的作用域**（A=3 个 switcher 项目；B=RE 逆向文档），并**把所有"不存在/全仓无"类结论统一降级为"在我调研的范围内未找到"**——本次两条最严重错误（P1、P3）都是**作用域泄漏**造成的。
