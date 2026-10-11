# A · 多账号接入 / 管理 / 切换 机制调研

> 路径基准 `/Users/w/Desktop/zcode相关管理软件/`（`文件:行号` 均相对该目录）· 只读调研，未修改任何参考项目文件。
> 证据分级：`【一手】`= 直接读到的代码；`【推断】`= 未经代码证实；`【未验证】`= 卡住未证实

## 修订记录（据独立核验 `verify-AB.md` 逐条修正）

| 原表述 | 修正后 | 类型 |
|---|---|---|
| `refresh_token`「全仓无任何 refresh 端点调用」「refresh 流程完全缺失，需自行实现」 | 本稿所查 3 个项目确实只存不用；**但同工作区 `zcode-reverse-engineer/zcode_auth.py:595-620`、`src/oauth.ts:294-303` 已实现完整 refresh，可直接移植** | 断言范围 > 检索范围（已补） |
| 锁 `modelProviderFamilyModes.zai="oauth"` → `profile.rs:895-907` | 正确为 `:884-893`（oauth 分支）；`:895-907` 是**相反语义的 `apikey` 分支**；domain 在 `:873-880` | 引用方向相反（严重） |
| 「原样拷贝 live → `store.rs:546`」 | 关键行为行是 `:548`（`credentials: live,`），区间 `:521-556` | 行号差 2 |
| `switcher.js:37`（探测）/ `:53`（关闭） | `:39` / `:55`；区间 `:37-47` / `:52-62` | 行号差 2 |
| 渐进轮询「约 4 分钟」 | delays 求和 = 325s ≈ **5.4 分钟**（源码注释也写"约 4 分钟"，与求和不符） | 数字错误 |
| 「secret 推导三份实现逐字一致」 | fallback 格式串一致，**但 `username` 取值口径三处各不相同**（`id -un` / `$USER` / `os.userInfo()`） | 表述过宽（原稿坑位节自相矛盾） |
| `web-remote-control:...pass_hash`「非 ZCode 字段」 | 改为「**用途未知**」（仅见注入/回填/排除在 hash 外，未找到消费方） | 推断写成事实 |

---

## ① 结论先行

ZCode 的登录态就是**两个纯文本 JSON 文件**：`~/.zcode/v2/credentials.json`（扁平 map，值为 `enc:v1:...` 或明文）与 `~/.zcode/v2/config.json`（provider → apiKey）。三个项目都**没有调用 ZCode 的任何"账号管理接口"**，而是**自实现 ZCode Electron 端的 `enc:v1` 加解密**（AES-256-GCM，key=SHA256(机器绑定 secret)），从而直接读写这两个文件完成"读凭据 / 存快照 / 切号"。切号本质 = **杀 ZCode 进程 → 覆写两个 JSON → 重启**；进阶做法是不杀进程只覆写 + 读回校验（zcode-switch 的 `hot_switch`），或原地 truncate 写 config 让 ZCode 的 `fs.watch` 自刷新（zcode-switcher）。账号唯一标识三套实现各不相同（凭据全文 hash / JWT `user_id` / 邮箱·手机号），但**都优先用 `config.json` 里 apiKey JWT 的 `user_id` 兜底用邮箱**。Mac 可用性差异完全取决于进程控制层：zcode-switch 用 `pgrep`/`pkill`/`open`（可用），zcode-account-switcher 硬编码 `tasklist`/`taskkill`（Mac 不可用）。

---

## ② 凭据文件结构全表

### 2.1 `~/.zcode/v2/credentials.json`（扁平 map，key 含冒号，value 均为 string）

| 键名 | 值形态 | 含义 | 证据 |
|---|---|---|---|
| `oauth:active_provider` | `enc("zai")` / `enc("bigmodel")` | 当前生效 provider id | 【一手】`zcode-switch/src-tauri/src/zcrypto.rs:136`；`zcode-account-switcher/src/oauth.js:226` |
| `oauth:<provider>:access_token` | `enc(token)` | provider 的 access token（**各项目语义不一致，见 ④.4**） | 【一手】`zcode-switch/src-tauri/src/oauth.rs:449`；`oauth.js:227` |
| `oauth:<provider>:refresh_token` | `enc(token)` | refresh token，**仅部分流程写入，且无任何项目用它刷新** | 【一手】`oauth.rs:452`；`oauth.js:228`；`zcode-switcher/src-tauri/src/oauth.rs:610` |
| `oauth:<provider>:user_info` | `enc(JSON 字符串)` | 用户档案，见 2.2 | 【一手】`oauth.rs:455`；`oauth.js:230` |
| `zcodejwttoken` | `enc(JWT)` | **调 `zcode.z.ai` 计费/权益接口的唯一正确 token** | 【一手】`oauth.rs:446`；`oauth.js:229`；`quota.js:154-156` |
| `web-remote-control:external-relay:pass_hash` | 明文 | **用途未知**（仅见"注入 / 回填 / 被排除在 hash 之外"，未找到消费方；**推断**为外部组件字段） | 【一手】`zcode-switch/src-tauri/src/store.rs:853`、`855-862`、`185-196` |

判定"是否已登录"的判据：存在任一 `oauth:*:access_token` 键，或 `zcodejwttoken` 非空 → 【一手】`store.rs:202-211`。

### 2.2 `user_info` 内层结构（`oauth:<provider>:user_info` 解密后）

```
{ id, user_id, username, displayName, name, email, avatar, avatarUrl, rawProfile:{ email } }
```

- zcode-switch 读取字段：`username` / `displayName` / `email` / `rawProfile.email` / `id` → 【一手】`zcrypto.rs:148-157`
- zcode-switcher 读取字段：`user_id` / `email` / `phone` / `avatar` / `name` → 【一手】`zcode-switcher/src-tauri/src/crypto.rs:28-40`
- 写入侧构造：`{id, username, displayName, email, avatarUrl}` → 【一手】`oauth.rs:378-384`；`{email,name,avatar,user_id}` → 【一手】`zcode-account-switcher/src/oauth.js:260-268`
- `user_id` 缺失时回退解 `access_token` JWT 的 `user_id` / `sub` → 【一手】`zcrypto.rs:159-171`

### 2.3 `~/.zcode/v2/config.json`

```
provider: {
  "<id>": {
    name, kind: "anthropic",
    options: { apiKey, baseURL, apiKeyRequired? },
    enabled: bool,
    source: "custom",
    systemDisabledReason?: "oauth_provider_inactive"
  }
}
```

- provider id 共 6 条内置，按 family 分两组 → 【一手】`zcode-switcher/src-tauri/src/profile.rs:357-382`：
  `builtin:zai` / `builtin:zai-start-plan` / `builtin:zai-coding-plan`；`builtin:bigmodel` / `-start-plan` / `-coding-plan`
- 组装逻辑（含 baseURL 常量）→ 【一手】`zcode-switch/src-tauri/src/oauth.rs:618-675`；常量 `BIGMODEL_ANTHROPIC_BASE` / `ZAI_ANTHROPIC_BASE` / `START_PLAN_ANTHROPIC_BASE` → `oauth.rs:463-465`
- **apiKey 是明文 JWT**（不是 `enc:v1`），含 `user_id`，因此成为最稳定的账号指纹来源 → 【一手】`zcode-account-switcher/src/fingerprint.js:6-8`、`82-89`（显式跳过 `enc:` 开头与长度 <30 的值）

### 2.4 其余相关文件（同目录 `~/.zcode/v2/`）

| 文件 | 关键字段 | 用途 | 证据 |
|---|---|---|---|
| `telemetry-state.json` | `deviceMid` | 设备标识，切号时按账号切换 | 【一手】`store.rs:1049-1062` |
| `setting.json` | `providerFamilyDomain`、`providerFamilyDomainUpdatedAt`、`modelProviderFamilyModes` | 路由/域锁定，防止跨账号串路由 | 【一手】`store.rs:650-666`；`profile.rs:895-907` |
| `coding-plan-cache.json` | — | 旧账号权益缓存，**切号必须删** | 【一手】`store.rs:641-648`；`profile.rs:1129-1136` |
| `rum-electron-store/*.json` | `_arms_uid`、`_arms_session` | 另一个设备身份槽位 | 【一手】`store.rs:1196-1217`、`1219-1259` |

### 2.5 三个项目各自的快照/仓库布局

| 项目 | 目录 | 结构 | 证据 |
|---|---|---|---|
| zcode-switch | `~/.zcode-switch/accounts/<uuid>.json` | 单文件整账号：`{id,name,created_at,updated_at,hash,credentials,config,virtual_device_mid,virtual_arms_uid}` | 【一手】`store.rs:63-64`、`79-92`、`479-484` |
| zcode-account-switcher | `accounts/<shortId>.meta.json` + `.snap.json` | meta 与快照分离；snap = `{credentials:string, config:string}`（**原文串，非对象**） | 【一手】`zcode-account-switcher/src/manager.js:5-9`、`78-97` |
| zcode-switcher | `~/.zcode/v2/account-profiles/profiles.json` + `credentials.<id>.json`；备份 `~/.zcode/v2/account-backups/` | 索引 + 每账号一份 credentials 副本（**密文原样**） | 【一手】`profile.rs:6-7`、`160-169`、`1036-1039` |

---

## ③ 加密 / 解密机制

### 3.1 ZCode 自有格式 `enc:v1`（三个项目都自实现复刻）

```
格式：enc:v1:<b64url(nonce 12B)>.<b64url(authTag 16B)>.<b64url(ciphertext)>
算法：AES-256-GCM
key  = SHA256(secret)
secret = env ZCODE_CREDENTIAL_SECRET
         ?? `zcode-credential-fallback:${platform}:${homedir}:${username}`
         platform: darwin / win32 / linux
```

- 常量与前缀 → 【一手】`zcode-switch/src-tauri/src/zcrypto.rs:10`；`zcode-switcher/src-tauri/src/crypto.rs:22-24`；`zcode-account-switcher/src/zcodeCrypto.js:17-20`
- secret 推导（**fallback 格式串三处逐字一致**）→ 【一手】`zcrypto.rs:42-60`；`crypto.rs:43-64`；`zcodeCrypto.js:22-27`
  - ⚠️ **但 `username` 取值口径三处各不相同**：`zcrypto.rs:34-40` 优先 `id -un` / `crypto.rs:95` 用 `$USER` / `zcodeCrypto.js:25` 用 `os.userInfo()` → 【一手】
- 解密（tag 拼接顺序：ciphertext ‖ tag）→ 【一手】`zcrypto.rs:73-93`；`crypto.rs:100-131`；`zcodeCrypto.js:45-58`
- 加密 → 【一手】`crypto.rs:134-160`；`zcodeCrypto.js:60-69`
- **是"自己实现 ZCode 的加密"，不是"调用 ZCode 的接口"** → 【一手】`zcode-account-switcher/src/zcodeCrypto.js:3-13`（注释明确写"逆向 ZCode app.asar 后确认"）；`crypto.rs:1-11`（"与 ZCode 桌面端 out/main 里的实现完全一致，已用真实凭据验证可解密"）
- **坑位**：secret 绑定 `platform + homedir + username` → 换机器/换用户名即无法解密历史凭据；`decrypt` 失败时三项目均静默降级（返回 `None`/`null`），表现为"账号显示但信息空白" → 【一手】`zcrypto.rs:97`、`zcodeCrypto.js:47`（`safeDecrypt` 的 catch 在 `quota.js:170-173`）
- **坑位**：`username` 取值口径不同 —— Rust 版优先 `id -un`（`zcrypto.rs:32-40`）而 zcode-switcher 版用 `env USER`（`crypto.rs:93-97`），account-switcher 用 `os.userInfo()`（`zcodeCrypto.js:25`）。在 `id -un` 与 `$USER` 不一致的环境（如某些 sudo/容器场景）会**互相解不开** → 【推断】基于三处实现差异，未实机验证
- 非 `enc:v1` 前缀的值一律原样返回 → 【一手】`zcrypto.rs:74`、`crypto.rs:101-103`、`zcodeCrypto.js:46`

### 3.2 导出信封（仅 zcode-switch 有，与 ZCode 无关）

```
{ format:"zsw-accounts-bundle", version:1,
  kdf:{ algo:"pbkdf2-hmac-sha256", iters:100000, salt },
  cipher:{ algo:"aes-256-gcm", nonce, tag, data } }
```

→ 【一手】`zcode-switch/src-tauri/src/cipher.rs:11-12`、`20-43`、`45-68`。**用户口令派生**，与 3.1 的机器绑定密钥是两套独立机制。

### 3.3 各项目落盘时的加密策略差异（重要）

| 项目 | 快照里的 credentials | 说明 | 证据 |
|---|---|---|---|
| zcode-switch（`capture_current`） | 原样拷贝 live 文件 → 保留 `enc:v1` | 读时用 `is_encrypted` 兼容明文 | 【一手】`store.rs:521-556`、关键行 `:548`（`credentials: live,`）；`zcrypto.rs:95-99` |
| zcode-switch（OAuth 新登录 `persist_oauth_account`） | **明文写入**（`json!(jwt)` 等，未加密） | `assemble_credentials_with_token` 不加密 | 【一手】`oauth.rs:438-458`、`lib.rs:653-659` |
| zcode-account-switcher | **全部 `encrypt()`** | 与 ZCode 客户端一致 | 【一手】`oauth.js:226-236` |
| zcode-switcher | **全部 `crypto::encrypt()`** | `import_profile_json` 时逐字段加密 | 【一手】`profile.rs:539-548`、`1253` |

> 即：zcode-switch 的 OAuth 新增账号路径会在快照里留下**明文 token**（该文件位于 `~/.zcode-switch/accounts/`），这是需要规避的差异点。

---

## ④ OAuth 登录流程

### 4.1 端点与常量汇总

| 项 | 值 | 证据 |
|---|---|---|
| authorize | `https://chat.z.ai/api/oauth/authorize` | 【一手】`zcode-switcher/src-tauri/src/oauth.rs:21`；`oauthCli.js:29` |
| token | `https://zcode.z.ai/api/v1/oauth/token` | 【一手】`zcode-switch/src-tauri/src/oauth.rs:6`；`oauth.rs:22`；`oauthCli.js:30` |
| client_id | `client_P8X5CMWmlaRO9gyO-KSqtg` | 【一手】`zcode-switcher/.../oauth.rs:25`；`oauthCli.js:27` |
| CLI init | `https://zcode.z.ai/api/v1/oauth/cli/init` | 【一手】`zcode-switch/.../oauth.rs:7` |
| CLI poll | `{origin}/api/v1/oauth/cli/poll/{flow_id}` | 【一手】`zcode-switch/.../oauth.rs:118` |
| business login | `https://api.z.ai/api/auth/z/login` | 【一手】`zcode-switcher/.../oauth.rs:24`；`oauth.js:27` |
| userinfo (zai) | `https://chat.z.ai/api/oauth/userinfo`（`Bearer`） | 【一手】`zcode-switcher/.../oauth.rs:23`、`519-522` |
| userinfo (bigmodel) | `https://bigmodel.cn/api/biz/customer/getCustomerInfo`（**裸 token，不加 Bearer**） | 【一手】`zcode-switch/.../oauth.rs:388-397` |
| 回调 URI 变体 | `zcode://zai-auth/callback`（account-switcher）/ `zcode://oauth/callback`（switcher、switch 解析） | 【一手】`oauthCli.js:28`；`zcode-switcher/.../oauth.rs:26`；`zcode-switch/.../oauth.rs:202` |

### 4.2 流程 A —— CLI device flow（zcode-switch 主用）

1. `POST /api/v1/oauth/cli/init` body `{provider:"zai"|"bigmodel"}`，带完整 ZCode 头（含 `X-Device-Mid`）→ 返回 `data.{flow_id, authorize_url, poll_token, expires_at, poll_interval_sec}`；`state` 从 `authorize_url` 的 query 里抠出 → 【一手】`zcode-switch/.../oauth.rs:56-123`
2. 打开授权页。zcode-switch 用 **Tauri 内嵌 Webview 窗口**（非系统浏览器），靠 `on_navigation` 拦截 `zcode://` scheme 完成回调；其 `redirect_uri` 走桥接页 `https://zcode.z.ai/app/oauth/login?redirect=zcode%3A%2F%2Foauth%2Fcallback&app_version=<ver>` → 【一手】`lib.rs:450-477`；`oauth.rs:22-26`
3. 同时起 `poll` 循环：`GET .../cli/poll/{flow_id}`，`data.status ∈ {pending, ready, failed}`；`ready` 时校验 `data.token` / `data.{zai|bigmodel}.access_token` / `data.user.user_id` 三者齐备 → 【一手】`oauth.rs:131-184`；循环启动于 `lib.rs:498`、`lib.rs:730`
4. `code` 交换（deeplink 分支）：`POST /oauth/token` body `{provider, code, redirect_uri: bridge_redirect_uri(), state}` → `data.token` → 【一手】`oauth.rs:308-343`
5. zai 需二次换 business token：`POST https://api.z.ai/api/auth/z/login {token: zai_access_token}` → `data.access_token` → 【一手】`oauth.rs:594-616`、`lib.rs:636-641`
6. 组装 credentials/config 落盘 → 【一手】`lib.rs:653-660`

### 4.3 流程 B —— Authorization Code（account-switcher、zcode-switcher）

1. `buildAuthorizeUrl(state)`：`?response_type=code&client_id=<APP_ID>&redirect_uri=<CALLBACK>&state=<random>` → 【一手】`oauthCli.js:37-45`；`zcode-switcher/.../oauth.rs:168-176`
2. 系统浏览器 `shell.openExternal(authorizeUrl)`，本地随机 16B hex 作 state，10 分钟超时 → 【一手】`zcode-account-switcher/desktop/main.js:285-299`
3. 回调捕获三种通道（跨平台必须都处理）：
   - `app.setAsDefaultProtocolClient('zcode', execPath, args)` 注册系统协议 → 【一手】`main.js:435-442`
   - Windows/Linux：`second-instance` 事件从 `argv` 里捞 `zcode://` → 【一手】`main.js:389-395`
   - macOS：`app.on('open-url')`（`whenReady` 前需缓存 URL）→ 【一手】`main.js:411-417`、`444-448`
   - Electron `protocol.handle('zcode', ...)` 主通道 → 【一手】`main.js:426-434`
4. state 校验（防 CSRF / 重放 / 跨会话串扰），不匹配静默丢弃 → 【一手】`main.js:259-277`
5. `POST /oauth/token {provider:'zai', code, redirect_uri, state}` → `data.token` / `data.zai.access_token` / `data.zai.refresh_token` / `data.user` → 【一手】`oauthCli.js:59-90`
6. 写盘 + 快照；**先备份当前登录态到内存，写完快照后还原**，保证"新增账号不切当前账号" → 【一手】`oauth.js:55-66`
7. 补调 business login 初始化 billing plan，并渐进轮询 `billing/current` 的 `data.plans` 是否非空（delays `[1000,3000,6000,15000,30000,60000,90000,120000]` 求和 = **325s ≈ 5.4 分钟**；源码注释写"约 4 分钟"，与求和不符）→ 【一手】`oauth.js:129-199`、`oauth.js:181`

### 4.4 坑位：`oauth:<provider>:access_token` 语义不一致

- zcode-account-switcher 存 **zai OAuth 原始 access_token**（`oauth.js:223`、`227`）；zcode-switcher 与 zcode-switch 的 zai 分支存 **business access token**（`api.z.ai/api/auth/z/login` 返回值，`zcode-switcher/.../oauth.rs:606-609`、`lib.rs:637-641`）→ 【一手】
- 后果：`quota.js:154-159` 明确要求 **`zcodejwttoken` 排最前**，因为 `oauth:*:access_token` 查 billing 会 401 → 【一手】`quota.js:154-156`

### 4.5 refresh

**A 稿所查的 3 个项目都只存不用**：`refresh_token` 被写入 credentials，但在这 3 个仓库内无任何 refresh 端点调用 → 【一手】`oauth.rs:426-436`（仅 bigmodel 提取）、`zcode-switcher/.../oauth.rs:610-614`、`oauth.js:228`。

> ✅ **修正（核验发现）**：**同工作区的 `zcode-reverse-engineer` 已实现 refresh**，可直接移植，不必自行实现：
> - `zcode-reverse-engineer/zcode_auth.py:595-620` `cmd_refresh()` → `POST token_url {provider, refresh_token, grant_type:"refresh_token"}`
> - `zcode-reverse-engineer/src/oauth.ts:294-303`（第二份实现）
> - 文档化入口 `docs/auth/oauth-flow.md:578`（`python zcode_auth.py refresh`）→ 【一手】

---

## ⑤ 账号快照 / 切换闭环

### 5.1 zcode-switch（Mac 可用，功能最全）

`switch_to(paths, id, force, restart, hot)` → 【一手】`store.rs:735-851`

1. **同账号短路**：`hash` 相同，或双方 identity 有信号且 `identity_matches` → 只回写 `deviceMid` / `armsUid` 后返回 `already_active` → 【一手】`store.rs:741-773`
2. **hot 分支**（`hot_switch=true` 且 ZCode 在跑）：不杀进程。`sync_live_back_to_source` → `auto_preserve` 旧账号 → `hot_swap_verified` → `backfill_relay_pass_hash` → 删 plan cache → 写 deviceMid/armsUid → 【一手】`store.rs:776-799`
   - `hot_swap_verified`：最多 3 轮「写 credentials+config → 读回 → identity 校验」，两轮一致才成功；失败按 250ms 递增退避 → 【一手】`store.rs:882-920`
3. **cold 分支**：`kill_zcode()` → `sync_live_back_to_source` → `auto_preserve`（把当前登录态另存为 `Auto MM-DD HHMM`）→ `write_live`（注入 relay pass）→ `write_live_config` → 删 `coding-plan-cache.json` → `align_family_domain` → `rematerialize_wiped_builtins` → 写 deviceMid/armsUid → 可选 `launch_zcode` → 【一手】`store.rs:801-850`
4. **原子写**：`tmp-<uuid>` + rename → 【一手】`store.rs:213-221`

**Mac 进程控制（关键可复用点）**
- 探测：`pgrep -x zcode` / `pgrep -x ZCode` → 【一手】`store.rs:275-287`
- 关闭：`pkill -x` → 等 4s → 仍在则 `pkill -9 -x` → 再等 4s → 【一手】`store.rs:310-341`
- 启动：`Command::new(path).process_group(0)` + stdio 全 null（detached）→ 【一手】`store.rs:33-40`、`343-355`
- 客户端路径候选（macOS）：`/Applications/ZCode.app/Contents/MacOS/ZCode`、`$HOME/Applications/...`、`/usr/local/bin/zcode` → 【一手】`store.rs:402-422`
- 打开 URL：macOS 用 `open <url>`，仅允许 `https://` → 【一手】`store.rs:357-384`
- **沙箱逃生口**：环境变量 `ZCODE_SWITCH_HOME` 存在时，`zcode_running()` 直接返回 false、kill/launch 变 no-op（便于测试）→ 【一手】`store.rs:255-257`、`277-279`、`311-314`、`344-346`

### 5.2 zcode-switcher（Rust + Tauri，Mac 有完整分支）

`switch_to(id)` → 【一手】`profile.rs:1063-1147`
1. 取凭据副本 → 计算 config/setting 需要写的内容 → 备份 credentials（+config、setting）→ 【一手】`profile.rs:1071-1107`
2. `atomic_write(credentials.json)` → 【一手】`profile.rs:1109-1111`
3. config 用 **`write_in_place`（truncate + write，不换 inode）**，目的让 ZCode 的 `fs.watch` 识别为"同文件 modify"从而自重建 session → 【一手】`profile.rs:1112-1122`、`620-636`
4. `write_in_place(setting.json)` 锁 `modelProviderFamilyModes.zai="oauth"` / `providerFamilyDomain` → 调用点 `profile.rs:1122-1127`；实现 `profile.rs:853-910`（函数 `prepare_setting_route_update`），关键行 `:873-880`（写 domain）、`:884-893`（`modes_obj.insert(family, "oauth")`）；⚠️ 同函数 `:895-907` 是**相反语义的 `"apikey"` 分支**（主动删除该 family 项），勿误引
5. oauth 模式删 `coding-plan-cache.json` → 【一手】`profile.rs:1132-1136`
6. 触发 CDP 无感刷新 → 【一手】`profile.rs:1138-1142`

**Mac 重启** → 【一手】`restart.rs`
- 进程名清单（macOS）：`ZCode`、`ZCode Helper`、`ZCode Helper (GPU)`、`ZCode Helper (Plugin)`、`ZCode Helper (Renderer)`；仅 `ZCode` 作为主程序路径来源 → 【一手】`restart.rs:20-36`
- 杀：`sysinfo` 枚举 + `kill_with(Signal::Term)`，不支持则 `kill()` → 【一手】`restart.rs:235-240`、`292-311`
- 启：`/usr/bin/open -n <AppBundle>`，有参数时追加 `--args`；`macos_app_bundle()` 从可执行路径向上找 `.app` → 【一手】`restart.rs:314-341`、`345-377`、`379-385`
- 记录已见 exe 路径到 `zcode-switcher-settings.json`，供下次启动用 → 【一手】`restart.rs:149-189`
- CDP 热切换依赖 `--remote-debugging-port=9229`，由快捷方式参数注入 → 【一手】`restart.rs:83-85`、`343-344`；`lib.rs:11-12`、`46-63`（`zcode_launcher` 模块）。⚠ `zcode_cdp.rs` / `zcode_launcher.rs` **在本副本中缺失**（`lib.rs:11-12` 有 `mod` 声明但文件不存在）→ 【未验证】CDP 具体报文无法证实

### 5.3 zcode-account-switcher（Mac 闭环不可用）

`switchTo(target, opts)` → 【一手】`switcher.js:108-153`：`isZCodeRunning()` → `killZCode()` → 备份到 `.last/` → 原子替换两个文件 → `launchZCode()`

- **根因**：进程控制是 Windows 硬编码 —— 探测 `tasklist /FI "IMAGENAME eq ZCode.exe"`（`switcher.js:37-47`，实际命令在 `:39`）、关闭 `taskkill /F /IM ZCode.exe`（`switcher.js:52-62`，实际命令在 `:55`）；`paths.js:29-35` 的 exe 候选全是 `C:\...` → Mac 上 `findZCodeExe()` 必返 null，`launchZCode()` 直接抛错 → 【一手】
- 可复用的是**回滚设计**（`.last/` 备份 + `rollback()` + 写失败自动 `restoreLast()`）与**原子写**（`.zcas.tmp` + rename）→ 【一手】`switcher.js:126-142`、`156-179`、`94-99`
- 可复用的是**安全前置条件**：运行中改 credentials 不可靠（客户端会回写），必须 `force` kill → 【一手】`switcher.js:5-9`、`111-124`

### 5.4 快照捕获与去重

| 项目 | 捕获 | 去重键 | 证据 |
|---|---|---|---|
| zcode-switch | `capture_current`：读 live → 算 hash → 查重 → 取名（默认取 identity label）→ 附带 deviceMid/armsUid | `canonical_hash`（credentials 全文 SHA256，剔除 `web-remote-control:*`）+ identity 兜底 | 【一手】`store.rs:521-554`、`185-200`、`556-567` |
| zcode-account-switcher | `capture`：`extractFingerprint()` → id = `emailShortId \|\| shortId` | 邮箱 hash 优先，回退 user_id 前 8 位 | 【一手】`manager.js:61-100`、`69`、`fingerprint.js:98-101` |
| zcode-switcher | `capture_current`：email/phone 为唯一 key，无则报错 | `identity_key` = `email:<归一化>` 或 `phone:<纯数字>`；内部 id = `sha256(key)[..12]` | 【一手】`profile.rs:984-1059`、`583-593`、`1035` |

---

## ⑥ 指纹与健康检查

### 6.1 `fingerprint.js` 是**账号身份指纹**，不是设备指纹

→ 【一手】`zcode-account-switcher/src/fingerprint.js`
- 输入：`config.json` 里启用 provider 的 `options.apiKey`（明文 JWT）+ `credentials.json` 解密出的 user_info / access_token
- 提取：`userId` = JWT `user_id || sub`；`shortId` = 前 8 字符；`emailShortId` = `'em-' + simpleHash(email.toLowerCase())[:10]`（djb2 变体，`fingerprint.js:146-150`）；另带 `customerId` / `userKey`（来自 access_token JWT 的 `customer_id` / `user_key`）
- **与防风控无关**（无设备维度）；防风控相关的是设备身份虚拟化，见 6.2

### 6.2 设备身份虚拟化（zcode-switch，真正的"指纹"层）

- `virtual_device_mid`：每账号一个 UUID，写入 `telemetry-state.json.deviceMid`；捕获时优先"收养"当前 live 的 mid（若未被其他账号占用），否则新建 → 【一手】`store.rs:1015-1035`、`1049-1062`、`1064-1085`
- `virtual_arms_uid`：格式 `uid_<36 进制 16 字符>`，写入 `rum-electron-store/*.json` 的 `_arms_uid`，并**删除 `_arms_session`**；跨平台目录探测（macOS 走 `~/Library/Application Support/ZCode`）→ 【一手】`store.rs:1089-1098`、`1147-1172`、`1196-1217`、`1219-1259`
- 请求头透传：`X-Device-Mid` → 【一手】`zcode-switch/src-tauri/src/quota.rs:195-197`
- 遥测事件体也带 `device_mid` + `user_id` + `mac_id`（空串）→ 【一手】`claim.rs:158-177`

### 6.3 `accountHealth.js`：纯本地静态检查，不联网

→ 【一手】`zcode-account-switcher/src/accountHealth.js:12-156`

| 判据 | 结果 |
|---|---|
| `credentials` / `config` 非空字符串；且均为合法 JSON | 否 → `error` |
| 能取到任一候选 token（`quota.readCandidateTokensFromSnapshot`） | 无 → `error`（`'未找到可用于登录/查询的 token'`） |
| 能取到 enabled provider 的 apiKey；能解析出稳定 `user_id` | 否 → `warning` |
| `user_info` 能在本机解密且为合法 JSON | 否 → `warning`（`'user_info 无法在当前机器环境解密'`） |

状态机：`errors>0 → error`；`warnings>0 → warning`；否则 `healthy` → 【一手】`accountHealth.js:147-156`

---

## ⑦ 可复用点清单

| # | 机制 | 文件:行号 | 我们能不能用 |
|---|---|---|---|
| 1 | `enc:v1` 解密（AES-256-GCM + SHA256(机器 secret)） | `zcode-switch/src-tauri/src/zcrypto.rs:73-93`；`zcode-switcher/src-tauri/src/crypto.rs:100-131` | ✅ 直接移植（Python 用 `cryptography` 即可，逻辑仅 20 行） |
| 2 | secret 推导（含 env 覆盖） | `zcrypto.rs:42-60`；`zcodeCrypto.js:22-27` | ✅ 必须先做，否则读不到任何账号信息；注意 `id -un` vs `$USER` 口径 |
| 3 | `enc:v1` 加密（写回） | `zcode-switcher/.../crypto.rs:134-160`；`zcode-account-switcher/src/zcodeCrypto.js:60-69` | ✅ 需要"新增账号写盘"时用 |
| 4 | credentials 字段清单 | `zcode-switch/.../oauth.rs:438-458`；`oauth.js:206-236` | ✅ 直接照抄键名 |
| 5 | config.json 6 条 provider + baseURL 常量 | `zcode-switch/.../oauth.rs:618-675`、`463-465` | ✅ 上游路由映射表 |
| 6 | 账号身份提取（JWT `user_id` / user_info 解密） | `zcrypto.rs:130-173`；`fingerprint.js:76-144` | ✅ 聚合账号列表的主键来源 |
| 7 | 凭据全文 hash 去重 + 剔除易变键 | `store.rs:185-200`、`556-567` | ✅ 建议照用（比 user_id 更稳，能识别"同账号换 token"） |
| 8 | identity 模糊匹配（user_id > email > provider+username） | `store.rs:922-946` | ✅ 处理"token 变了但人是同一个" |
| 9 | 原子写（tmp + rename） | `store.rs:213-221`；`switcher.js:94-99`；`profile.rs:607-618` | ✅ 通用 |
| 10 | 原地 truncate 写（骗过 `fs.watch`） | `zcode-switcher/.../profile.rs:620-636` | ✅ 免重启热生效的关键技巧 |
| 11 | 热切换 + 写后读回校验 + 退避重试 | `store.rs:882-920` | ✅ 不杀进程切号，最省事 |
| 12 | 切前 kill、切后 launch（macOS `pgrep`/`pkill -9`/`open`）+ macOS 多进程名清单（含 4 个 Helper） | `store.rs:275-341`、`343-355`；`restart.rs:314-341`、`20-36` | ✅ Mac 唯一可行路径；漏杀 Helper 会导致登录态被回写覆盖 |
| 13 | 备份 + 一键回滚（`.last` / `account-backups`） | `switcher.js:126-179`；`profile.rs:709-735` | ✅ 强建议 |
| 14 | 切号后一致性三件套：删 `coding-plan-cache.json`、锁 `setting.json` 的 `providerFamilyDomain`/`modelProviderFamilyModes`、重物化被清空的 builtin apiKey | `store.rs:641-648`、`650-666`、`668-733`；`profile.rs:1129-1136`、`895-907` | ✅ 不做会权益/路由串号、provider 被 `oauth_provider_inactive` 禁用 |
| 15 | 设备身份虚拟化（`deviceMid` / `_arms_uid`） | `store.rs:1015-1085`、`1147-1259` | ⚠️ 视合规策略决定；机制本身可移植 |
| 16 | OAuth 授权码流程 + 回调三通道（协议注册 / `second-instance` / macOS `open-url`） | `oauthCli.js:27-90`；`zcode-switcher/.../oauth.rs:21-26`、`437-476`；`desktop/main.js:389-448` | ✅ 聚合账号入口；Mac 走 `open-url` |
| 17 | CLI device flow（init + poll） | `zcode-switch/.../oauth.rs:56-184` | ⚠️ account-switcher 注释称该端点 2026-06 起 404（`oauthCli.js:5-7`），需实测 |
| 18 | business login 初始化 billing plan + 渐进轮询 | `oauth.js:129-199` | ✅ 新账号"没有 plan"的根因修复 |
| 19 | 额度/权益查询端点、token 优先级、权益等级判定 | `quota.js:11-18`、`146-168`、`190-210`；`quota.rs:20-23` | ✅ `zcodejwttoken` 排最前；plans → Max/Pro/Lite/Start |
| 20 | 领取权益端点（preview / claim / configs） | `zcode-switch/.../claim.rs:9-11` | ✅ 积分/权益聚合面 |
| 21 | ZCode 请求头全套 + 账号健康检查（静态、离线） | `zcode-switch/.../quota.rs:180-201`；`accountHealth.js:12-156` | ✅ 上游调用必需；健康检查作聚合前准入校验 |
| 22 | 导出/导入 bundle 格式 + 沙箱开关（`ZCODE_SWITCH_HOME` / `ZCAS_DATA_DIR` / `ZCODE_CREDENTIAL_SECRET`） | `store.rs:1284-1296`、`255-257`；`cipher.rs:20-68`；`profile.rs:222-244`；`paths.js:42-57`；`zcrypto.rs:47` | ✅ 账号搬运 + 测试隔离 |
| 23 | 并发保护（`store_guard` 互斥） | `store.rs:1045-1046`、`lib.rs` 多处 | ✅ 网关多线程下必须补 |

---

## ⑧ 未解决项

1. **`zcode_cdp.rs` / `zcode_launcher.rs` 缺失** —— `zcode-switcher/src-tauri/src/lib.rs:11-12` 有 `mod` 声明，但对应文件在副本中不存在，CDP 无感切号的具体报文（目标端口、`Runtime.evaluate` 内容、刷新触发点）**无法证实** → 【未验证】
2. **CLI device flow 是否仍可用** —— `zcode-switch` 主用 `/oauth/cli/init` + `/oauth/cli/poll`，但 `zcode-account-switcher/src/oauthCli.js:5-7` 明确写"2026-06 起端点返回 404，官方已改用 Authorization Code"。两者矛盾，未实测 → 【未验证】
3. **`oauth:<provider>:access_token` 到底该存哪个 token** —— 三个项目给出两种答案（zai OAuth token vs business token），未验证哪种能被 ZCode 客户端正常识别 → 【未验证】
4. **refresh 在 A 稿的 3 个项目里缺失，但同工作区已有实现** —— 3 个项目只落盘 `refresh_token`，无刷新调用（`quota.js:78` 的提示印证）。✅ **但 `zcode-reverse-engineer/zcode_auth.py:595-620` 与 `src/oauth.ts:294-303` 已实现完整 refresh 调用，可直接移植** → 【一手】
5. **username 口径不一致** —— `zcrypto.rs:32-40` 用 `id -un`，`crypto.rs:86-97` 用 `$USER`，二者不同时解密失败；另 zcode-switch OAuth 新增账号路径落盘**明文**（`oauth.rs:438-458` 不加密），是否被后续流程补加密未逐行追完 → 【推断】
6. **`web-remote-control:external-relay:pass_hash` 的真实用途** —— 只看到"注入 / 回填 / 从 hash 中剔除"，未找到它被哪个外部组件消费 → 【未验证】
7. **`X-Device-Mid` 的服务端校验强度** —— 仅见客户端透传，未见服务端是否强校验（决定"多账号共用一个 deviceMid"是否可行）；`setting.json` 完整字段集也未清点，只确认 `providerFamilyDomain` / `providerFamilyDomainUpdatedAt` / `modelProviderFamilyModes` 三个被读写 → 【未验证】
8. **`CLIENT_APP_VERSION` 不一致** —— `zcode-switch/.../quota.rs:23` 为 `3.11.2`，`zcode-account-switcher/src/quota.js:17` 为 `4.1.10`；服务端是否按版本路由不同响应未验证 → 【推断】
