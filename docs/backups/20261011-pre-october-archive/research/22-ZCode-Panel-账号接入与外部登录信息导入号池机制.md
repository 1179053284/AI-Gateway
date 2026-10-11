# 22 · ZCode-Panel 账号接入与「外部账号登录信息 → 本机登录」机制

> 调研对象：`/Users/w/Desktop/zcode相关管理软件/ZCode-Panel/`（**全程只读**，仅 Read/Grep/Glob；零写入，见 §⑪）
> 证据分级：【一手】直接读到的代码/注释；【推断】由代码推导未经运行证实；【未验证】未证实
> 复核基线：`17-ZCode-Panel-数据隔离与账号切换.md` / `18-ZCode-Panel-登录额度与套餐.md`（及 `zcode-drafts/F1`、`F2`），逐条按**当前工作副本**复核并标注漂移（见 §⑧）
> 本次副本状态：`git` 工作区**已有未提交改动**（`M import-account.js / main.js / package.json / renderer/app.js / renderer/index.html / settings.js / update.js`，`?? build/`）——这是被调研项目作者自己的在途修改（2026-09-26~28），**非本次调研造成**（§⑪ 附 md5 前后一致证明）。
> 最高影响结论：**17 §⑤ 的账号导入结论在本次副本中已被重写**（新增 family/credentials 双家族 + 写盘自检回滚），但 **「只校验 UUID 格式、不查跨账号唯一性」的缺口仍然存在** —— Q27-⑤ 要求的补偿项**未失效**。
> 用户点名核实：「买外部账号登录信息给本机登录使用」→ **有落点但无购买实现**：仓库内**没有任何支付/卡密/订单/商城代码**，实际落点是「面板内小店窗口 + 免费号池外链 + 剪贴板/文件导入」三段式，详见 §④。

---

## ① 结论先行

1. **外部账号信息的唯一收口是 `accounts:import` IPC + `import-account.js`**，注释自称「面板侧唯一收外部凭据的入口（YouYu Shop 那条 B 方案：小店给凭据，面板来导入）」（`main.js:2320-2322`；IPC `main.js:2323-2345`；渲染层 `preload.js:66` + `renderer/app.js:1226-1244` + 弹窗 `renderer/index.html:110-130`）。输入形态 = **JSON 对象 / JSON 文本（剪贴板） / `.json` 文件**（`import-account.js:138-145`、`renderer/app.js:1217-1224`）。【一手】
2. **当前副本已把导入从「单 jwt」升级为「双家族 + 完整凭据」**：`family: bigmodel|zai` 决定 `oauth:active_provider` 与写哪套 builtin provider；`credentials` 里取 `oauth:<family>:{access_token,refresh_token,user_info}`（`import-account.js:52-58, 79-135, 283-292`）。老格式（只有 name/jwt/device_mid）仍兼容但**不带 credentials**（`import-account.js:57-58, 286-292`）——面板注释明确「带 family + credentials 的那份才算登录完整（小店新版会给）」（`import-account.js:13-18`）。【一手】
3. **写入前有自检 + 失败整体回滚**（`verifyWritten` 读回校验 credentials 必需键 / config 的 provider.kind/apiKey/baseURL、并拒绝残留别家 provider；不通过即 `rmSync` 整个账号目录）：`import-account.js:221-253, 311-315`。【一手】由此**老格式导入（无 credentials）会通过自检**——自检只校验「已给的键」，不强制要求 access_token/user_info（`import-account.js:230-235`）→ 是否被客户端判「已登录」未实测。【推断/未验证】
4. 🔴 **跨账号设备唯一性仍未校验（复核 17 §⑤ 结论：仍成立）**：`import-account.js:165` 只做 `UUID_RE` 格式校验；全仓 `*.js` 检索 `device_mid|deviceMid|device-id|ZCODE_DEVICE`，命中的 4 个文件（main.js / import-account.js / account-query.js / remote-plan.js）**均无跨账号比较逻辑**；再检索 `重复|冲突|duplicate|conflict|唯一|uniqu`（排除 node_modules/dist）**无任何去重实现**。三条 device_mid 入口（导入 / OAuth 新建 / 捕获）全部只做「有值则沿用、无值则 `crypto.randomUUID()`」（`main.js:1746`、`main.js:812`、`main.js:1168-1178`）。【一手 + 检索说明】
5. **「买号」是外链级集成，不是购买功能**：面板内 560×780 小窗 `shop:open`（`main.js:2347-2407`，标题 `YouYu Shop`，地址 `https://shop.youyuaiwan.xyz`（`renderer/app.js:22`））+ 系统浏览器打开的 `免费号池` 外链 `https://youyuaiwan.xyz/free.html`（`renderer/app.js:16, 1188`；白名单 `main.js:2695-2699`）。**仓库内 0 处支付/卡密/订单/商城/收款/二维码代码**（负向断言检索范围见 §④.2）。买到的凭据只能**人工粘贴/选文件**进导入弹窗——因为小店窗口**没挂 preload，也没有任何 IPC 窄桥**（`main.js:2379-2381` 注释自认「暂不挂 preload，等『买完自动导入面板』那条窄桥设计定下来再挂」）。【一手】
6. **切换账号 = 改 `.current` + 杀净旧进程 + 用该账号数据根重启**，凭据零复制（`main.js:1320-1360`；数据根 `ZCODE_DATA_BASE_DIR` 注入在 `main.js:1237`）。当前副本相对 17 的**行为升级**：固定 `wait(800)` 已换成**轮询等待真退出**（`waitZCodeGone(8000)` → 失败再 `killZCode(true)` + 等 4s，`main.js:1335-1338`），且 `spawn` 后**若进程立刻退出（单实例锁冲突）会明确报错**（`main.js:1289-1304`）。【一手】
7. **解密现状 = 不解密**：导入时凭据（jwt / oauth 各键 / active_provider）一律 `oauth.encrypt` 加密后落盘（`import-account.js:286-292`），**不尝试解密输入里的 `enc:v1:` 密文**；`pickOAuth` 只把 `enc:v1:` 当作**合法字符串形态**接受（`import-account.js:42, 129-131`）。因此**跨机导入别人机器加密的密文必然不可用**（密钥派生含 `os.homedir()`/用户名，`oauth.js:248-253`）。【一手 + 推断】
8. **17 §⑤ 的其余结论逐条复核**：白名单/目录穿越双保险/默认拒绝覆盖/剔除第三方 provider 与 scrub 凭据——**全部仍成立且已加强**（新增「`<32hex>.<secret>` 请求签名密钥一律拒」，`import-account.js:43-44, 123, 193`）。【一手】

---

## ② 账号库结构与管理面

### 2.1 目录布局（`<accountsDir>/<账号名>/`，当前副本）

| 子路径 | 承载 | 由谁/何时写 | 行号 |
|---|---|---|---|
| `data/.zcode/v2/` | ZCode 数据根：`credentials.json` / `config.json` / `provider_config.json` / `telemetry-state.json` / `logs/` / `certs/` | 客户端运行时写（根由 `ZCODE_DATA_BASE_DIR` 指定）；导入/捕获/OAuth 也直接写其中三份 | `main.js:56-63, 1237` |
| `userdata/` | Chromium userData | 启动时注入 `ZCODE_DESKTOP_USER_DATA_DIR` | `main.js:1262, 1268` |
| `session/` | cookies / localStorage | 启动时注入 `ZCODE_DESKTOP_SESSION_DATA_DIR` | `main.js:1263, 1269` |
| `home/` | shell HOME | 启动时注入 `ZCODE_DESKTOP_HOME_DIR` | `main.js:1264, 1270` |
| `meta.json` | 账号元信息（见 2.3） | 面板三处写：导入 / 捕获 / OAuth 新建 | `import-account.js:299-306`；`main.js:801-814`；`main.js:1734-1747` |
| `config.json`（顶层） | 与「现成账号布局」兼容的副本 | 导入时与 `v2/config.json` 同内容写两份 | `import-account.js:295-296` |
| `plan-snapshot.json` | 套餐快照 | 日志/联网读取后落盘 | `main.js:311, 493, 648` |
| `.rollback/` | `credentials.json` / `config.json` 备份（点开头，扫描跳过） | 写登录态前备份（`applyOAuthToken` 1595-1602；`bindOAuthToCurrent` 1800-1804） | `main.js:1596, 1801` |
| `.current`（账号库根下，非账号目录） | 当前账号 id 文本 | `writeCurrentId` | `main.js:170, 183-190` |
| `.trash-YYYYMMDD/` | 删除的账号目录（移到回收站，不真删） | `deleteAccount` | `main.js:1390-1406` |
| `.session-index-seeded` | 会话索引播种标记（在账号 `v2/` 内） | `session-index.js` | `session-index.js:39, 134` |

账号扫描规则：跳过 `.` 开头目录与保留名 `last/profile/backup/tmp`（`main.js:238, 671`）。`valid` 判据 = `credentials.json` 存在 **且** `config.json` 存在（`main.js:675-676, 697`）。【一手】

### 2.2 设备码（device-id）生成规则

- **生成**：`accountDeviceId(id)` 读 `<账号>/meta.json`，`device_mid` 缺失/非字符串 → `crypto.randomUUID()` 并**立刻落盘**（`main.js:1168-1178`）。【一手】
- **格式**：标准 UUID；导入侧正则 `^[0-9a-f]{8}-…-[0-9a-f]{12}$/i`（`import-account.js:40, 165`）。【一手】
- **永不变**：有值一律沿用；注释理由「换了设备码等于换了台机器，服务端看就是一次异常的设备迁移」（`main.js:810-812`）。三处入口同口径：导入（用 payload 的 UUID，`import-account.js:304`）、捕获（`main.js:812`）、OAuth 新建（`main.js:1746`）。【一手】
- **注入两通道**：`--device-id=<uuid>` 命令行（`main.js:1229`）+ `<账号>/data/.zcode/v2/telemetry-state.json` 的 `deviceMid`（`syncDeviceMidToZCode`，`main.js:1182-1197`，值相同则跳过写 1188）。【一手】
- 🔴 **无唯一性校验**：见 §①.4 与 §⑤.6。【一手】

### 2.3 `meta.json` 字段（当前版本全集）

`registered_at` / `registered_at_source` / `registered_at_raw` / `captured_at` / `last_used_at` / `switch_count` / `switches_today` / `last_switch_date` / `via` / `phone` / `email` / `device_mid` / `note`，**外加本次新增** `family` / `family_source` / `oauth_keys` / `last_action`。【一手】

- `family`/`family_source`/`oauth_keys` 三字段由导入写入（`import-account.js:305`）；`family_source` ∈ `field|credentials|default`（`import-account.js:80-104`）。
- `via` 取值：`import`（导入，`import-account.js:303`）、`oauth`（OAuth 新建，`main.js:1743`）、`phone-manual`/`zai-mail`（OAuth 流程以 provider 判定，`main.js:2060`）。
- 切换/重启增量更新 `last_used_at`/`switch_count`/`switches_today`/`last_switch_date`/`last_action`，`switches_today` 按**本地日期**归零（`main.js:1428-1443`；注释说明不能用 `toISOString()`，1420-1421）。【一手】

### 2.4 `account-query.js` 的角色与输入输出

- **角色**：**不依赖 electron 的独立联网查询模块 + CLI**（`account-query.js:1-29`），查两件事：**有没有券** `coupon` + **日额度还剩多少** `daily`，另附 `plans` 名称列表。与面板 `remote-plan.js` 走**同一端点**：`GET https://zcode.z.ai/api/v1/zcode-plan/billing/balance?app_version=3.11.2`，鉴权 `Authorization: Bearer <zcodejwttoken>` + `X-Device-Mid`（`account-query.js:34-39, 64-84`）。【一手】
- **函数签名**：`queryAccount(jwt, deviceMid)` → `{ok, coupon{exists,count,items[]}, daily{模型:{total,used,left}}, plans[], planCount, serverTime}`（`account-query.js:58-148`）；`readLocalAccount(dir, id)` → `{id, jwt, mid}`，jwt 从 `data/.zcode/v2/config.json`（回退顶层 `config.json`）**递归扫** `eyJ` 三段串，mid 取 `meta.json.device_mid`（`account-query.js:150-167`）。【一手】
- **CLI**：`node account-query.js [--dir <账号库>] <账号名...>`（`account-query.js:172-198`）；账号库默认 `ZPANEL_ACCOUNTS_DIR` > 本项目 `accounts/` > 同级 `zcode-switch/accounts`（`account-query.js:42-49`）；**每账号间 sleep 2600ms**（`account-query.js:184, 195`）。【一手】
- **先校验后取值**（不把 400 读成「没有券」）：401→`unauthorized`、3001→`parameter`、3012→`risk`、code≠0→`business`（`account-query.js:93-99`）。券 = plans 中名字不匹配 `/ZCode Start Plan/i` 的项（`account-query.js:104-121`）；日额度 = `period` 为 `daily`（或空）的桶按 `show_name` 归并（`account-query.js:123-138`）。【一手】
- 【新增·18 未记】面板侧另有一个**导出但全仓无调用方**的签名密钥派生函数 `remote-plan.js:192-227 deriveSigningKey`（`/api/biz/customer/getCustomerInfo` → 组织/项目 → `api_keys` → `/copy/<apiKey>` 取 `secretKey`，拼成 `<apiKeyId>.<secretKey>`；注释称「与客户端本地保存的完全一致」，可选 `createIfMissing` 会**在平台侧创建 api key**，默认不创建）。检索 `deriveSigningKey|pickOrgAndProject` 仅命中 `remote-plan.js` 自身（含导出 `remote-plan.js:229-238`）——**当前是休眠能力**。见 §⑨.3。【一手】

---

## ③ 添加账号的全部通道

当前副本共有 **4 条**入口（前 3 条产出「面板内自建账号」，第 4 条收「外部凭据」）：

### 3.1 通道 A：BigModel 网页登录（面板内 OAuth 窗口）

- UI：`BigModel 网页登录`（`renderer/index.html:63`）→ `renderer/app.js:533-552 doOAuth('bigmodel')` → `api.oauthStart('bigmodel','bridge',{})`（`app.js:536`）→ IPC `oauth:start`（`main.js:2641`）→ `startOAuthFlow`（`main.js:1991`）。【一手】
- 流程：清授权分区残留（`main.js:2012-2019`）→ 按域名分流代理（`main.js:2023-2028`）→ 建窗口 → 登录驱动（人工填手机号/验证码/人机验证、自动点提交与授权确认）→ 回调捕获（`main.js:2298-2312 handleOAuthCallback`）→ `completeOAuth`（`main.js:2191-2258`）→ **`importAsSnapshot` 落成新账号但不切换**（`main.js:2220-2225`；`main.js:2218-2219` 注释「只落成账号快照，绝不改动当前 ZCode 登录态」）。【一手】
- Z.ai 线：`startOAuthFlow('zai')` 直接返回 `deprecated`（`main.js:1999-2006`）。【一手】
- `importAsSnapshot`（`main.js:1708-1750`）：账号名 = `userInfo.username/displayName`，通用名（`user` 等）补 uid 尾 6 位（`main.js:1710-1715`），`slugifyAccountName` 清路径分隔/空白、最长 40 字符（`main.js:1752-1760`）；`applyOAuthToken({freshAccount:true, accountId:name})` 从**空对象**起步，不继承当前账号身份（`main.js:1719-1725`），再按 uid 复核剔除混入身份（`main.js:1727-1729`）。【一手】
- 另有 **bind 模式**（把 BigModel 附加到当前 Z.ai 身份、不新建账号）：`bindOAuthToCurrent`（`main.js:1780-1811`）**全仓无 UI 调用方**（`renderer/app.js` 检索 `bind` 仅命中 `bindEvents`，`preload.js` 无该 API；`oauthStart` 唯一调用点传 `{}`）——休眠能力。【一手】

### 3.2 通道 B：浏览器授权导入（手动链接 + 粘贴回跳）

- UI：`浏览器授权导入`（`renderer/index.html:64`）→ 弹窗（`renderer/index.html:148-172`）→ 自动生成授权链接 `api.oauthLink('bigmodel','direct')`（`renderer/app.js:558-569` → `main.js:2261-2275`）；用户在**自己已登录的浏览器**里打开并授权（`renderer/app.js:587-592` 交系统浏览器），把回跳地址/授权码贴回（`renderer/app.js:594-611` → `main.js:2278-2295 submitManualCode` → `completeOAuth` → **同样走 `importAsSnapshot` 新建账号**）。【一手】
- 校验：`parseManualInput` 先按 URL 解析（`authCode ?? code` + `state`，`oauth.js:100-114`），失败则整串当 code；`state` 不匹配即拒（`main.js:2285-2287`）。【一手】
- 定位：这是**「手上已有账号、把它的登录态导进来」**的官方指定路径（`renderer/index.html:194`；`main.js:2004`）。【一手】

### 3.3 通道 C：捕获 / 认领当前登录

- UI：`捕获当前登录`（`renderer/index.html:68`）→ `capture-modal`（`renderer/index.html:132-146`）→ `api.capture(name, replace)`（`renderer/app.js:415-423`）→ IPC `accounts:capture`（`main.js:2544-2555`）→ `captureAccount`（`main.js:748-823`）。【一手】
- 语义（当前副本）：账号目录里**已有凭据**（`credentialsOf` 存在）→ 仅刷新元信息（认领；`replace` 未勾则先拒，`main.js:758-763`）；**没有凭据但老的全局 `~/.zcode/v2/` 有** → **一次性迁移**（`copyFileSync` 凭据+配置，`main.js:759, 766-775`）；两者都没有 → 如实报错「先用这个账号启动客户端并在里面登录」（`main.js:777-782`）。【一手】
- 落地前剔除外来身份（`pruneForeignIdentity`，`main.js:721-737, 785-790`），并从平台取注册时间（`balance.fetchRegisteredAt`，`main.js:797-799`），最后 `writeCurrentId(id)` **顺手记为当前账号**（`main.js:817`）。【一手】

### 3.4 通道 D：导入账号（外部凭据 JSON）——「外部登录信息」入口

- UI：`导入账号`（`renderer/index.html:69`）→ `import-modal`（`renderer/index.html:110-130`）→ 粘贴 JSON 或选 `.json` 文件（`renderer/app.js:1217-1224`）→ `api.importAccount(text,{replace})`（`renderer/app.js:1226-1244`）→ IPC `accounts:import`（`main.js:2323-2345`）→ `accountImporter.importAccount`（`import-account.js:264-323`）。【一手】
- 主进程只负责挑一份**含 `builtin:` provider 的现成账号 config 当模板**（`main.js:2325-2332`），校验与落盘全在 `import-account.js`；取不到模板时走最小兜底 config（`main.js:2332`；`import-account.js:62-77, 199-212`）。【一手】
- 细节全部下移 §⑤ / §⑥。【一手】

### 3.5 通道对照

| 通道 | 输入 | 产出账号 | 会改当前登录态吗 | 关键失败条件 |
|---|---|---|---|---|
| A BigModel 网页登录 | 人工登录（手机号+短信+拼图） | 新账号（`importAsSnapshot`） | **不会**（注释明示 `main.js:2218-2219`） | 分区残留未清→绑错号（2012-2019）；代理未分流→白窗口；窗口关闭→取消 |
| B 浏览器授权导入 | 手动链接 + 回跳地址/码 | 新账号（同上） | 不会 | `state` 不匹配；token 交换 `code≠0`；缺 `state` 的裸码走整串兜底 |
| C 捕获当前登录 | 面板内的「当前账号名」 | 认领/迁移既有目录 | **会**（`writeCurrentId`，`main.js:817`） | 目录里无凭据且无旧全局登录态 |
| D 导入账号 | 外部凭据 JSON / 文件 | 新账号（模板 config） | 不会 | 见 §⑤.2/⑤.6 的 9+ 类拒绝分支 |

---

## ④ 「买外部账号登录信息」说法的落点核实（重点）

**结论：说法有代码落点，但落点是「外链 + 剪贴板导入」，仓库内不存在购买/支付/卡密/商城/外部服务对接功能。**不猜、不延伸。

### 4.1 有落点的部分（【一手】，全部为外链级）

| 落点 | 实现 | 行号 |
|---|---|---|
| 面板内**小店窗口**（"一元账号"按钮） | `shop:open` IPC → 新建 `BrowserWindow` 560×780，title `YouYu Shop`，`contextIsolation:true / nodeIntegration:false / sandbox:true` | `renderer/index.html:66`；`renderer/app.js:1191-1198`；`main.js:2347-2407`（窗口 2368-2382） |
| 小店地址 | `LINKS.shop = 'https://shop.youyuaiwan.xyz'` | `renderer/app.js:22` |
| **地址白名单** | https 任意；http **只放行** `127.0.0.1 / localhost / ::1 / youyuaiwan.xyz / www.youyuaiwan.xyz`（本地测试口子 + 自家域名）；`file:`/`javascript:`/陌生 http 一律拒 | `main.js:2354-2361` |
| 小店打不开的提示页 | `did-fail-load` 写说明页；回环地址时提示 `cd D:\PYxiangmu\youyu-shop` + `start.cmd`（暴露小店项目名与路径） | `main.js:2385-2401`（2395） |
| **免费号池**（"免费号池"按钮） | 系统浏览器打开 `https://youyuaiwan.xyz/free.html`；按钮 title「可以领可用的 ZCode 账号」 | `renderer/app.js:16, 1188`；`renderer/index.html:65` |
| 免费号池外链白名单 | `OPEN_URL_ALLOW` 精确到 `origin + path`；只允许 https | `main.js:2695-2699, 2701-2717` |
| 「买到的凭据」→ 导入 | 见 §③.4 通道 D（唯一收口） | `main.js:2320-2345` |

### 4.2 不存在的部分（负向断言 + 检索范围）

- 检索 `支付|卡密|订单|购买|商城|收款|付款|二维码|payment|checkout|alipay|wechatpay|stripe|下单|发货|商品`（大小写不敏感，排除 `node_modules/`、`dist/`、`build/`、`package-lock.json`）→ **0 命中**。【一手】
- 检索 `createServer|\.listen\(|http\.get|express`（全仓 `*.js`，排除 node_modules）→ **0 命中**：面板**没有任何本地 HTTP 服务**，因此「小店页面把凭据 POST 回面板」这类通道**不存在**。【一手】
- 检索 `will-download|setWindowOpenHandler`（main.js / renderer / preload）→ **0 命中**：小店窗口不会自动下载凭据文件，也无法拦截下载。【一手】
- 计费相关代码只出现在「上游 ZCode 套餐额度」语境（`plan.js` / `remote-plan.js` / `balance.js` / `account-query.js`），与「买号」无关。【一手】

### 4.3 实际链路（当前代码事实）

1. 用户点「一元账号」→ 面板内小窗打开 `https://shop.youyuaiwan.xyz`（或本地 `127.0.0.1:8790` 测试口，见 `main.js:2349-2353` 注释）。
2. 购买/领号行为**全部发生在该外部站点内**（仓库无从验证其支付与发放实现——【未验证】）。
3. 用户把小店给出的**凭据 JSON** 复制回来（或下载 `.json`）→ 在「导入账号」弹窗粘贴/选文件 → 导入成为面板账号（`import-account.js` 全流程）。
4. 为什么必须人工搬运：注释给出两条硬理由——① 小店是**部署在服务器上的网站**，写不到买家本机（`renderer/app.js:1200-1202`）；② 「买完自动导入面板」的**窄桥尚未设计定稿**，故 `shopWin` 的 `webPreferences` **刻意不挂 preload**（`main.js:2379-2381`）。【一手】

### 4.4 两处「说法 vs 代码」不一致（如实报告）

| # | 说法（出处） | 代码事实 | 性质 |
|---|---|---|---|
| ① | 按钮 title：「…买完的账号**自动进本面板的账号管理**」（`renderer/index.html:66`） | 无 preload、无 IPC 桥、无下载拦截；导入必须人工粘贴/选文件（`main.js:2379-2381`；`renderer/app.js:1226-1244`） | **UI 文案超前于实现**（会让人以为买完即入列） |
| ② | `renderer/app.js:20-21` 注释：「现在指向**本机**…部署到 youyuaiwan.xyz 之后，把这里改成 `https://youyuaiwan.xyz/shop/`」 | 第 22 行实际已是 `https://shop.youyuaiwan.xyz`（公网域名，且 `main.js:2354` http 白名单早含该域名） | **注释过期**（代码已先行部署，注释未同步） |

> 附：面板 README（Sep 25 版）**完全未提**小店/一键买号入口，只在「添加账号」写 BigModel 网页登录与「浏览器授权导入」（`README.md:26-31, 112`），并声明「面板不内置接码平台、临时邮箱或邮箱抓取接口」（`README.md:118`）——与代码一致：**手机号/验证码/邮箱全部由 `askText` 向人索要**（`login-driver.js:87-101`）。文档侧同样**零购买描述**。【一手】

---

## ⑤ 外部凭据导入：输入形态 / 解密 / 校验（当前版本）

### 5.1 支持的输入形态（`normalize`，`import-account.js:138-173`）

| 维度 | 支持 | 行号 |
|---|---|---|
| 顶层类型 | JSON **对象** 或 **JSON 文本**（剪贴板 / `.json` 文件内容），先去 BOM；空串→`empty`、解析失败→`not-json`、非对象→`not-object` | 140-145 |
| 外包一层 | `account` / `data` / `payload`（该层含 `jwt|jwtToken|device_mid|deviceMid` 任一即下钻） | 147-149 |
| 字段别名 | name = `name|id|accountName`；jwt = `jwt|jwtToken|zcodejwttoken|token|apiKey`；mid = `device_mid|deviceMid|mid|deviceId`；note = `note|desc|description` | 158-161 |
| 家族 | 显式 `family` > 从 `credentials` 键名 `oauth:<family>:...` 推断（**混两家族则报错**）> 缺省 `bigmodel` | 80-104 |
| 完整凭据 | `credentials` 对象里只取**本家族**的 `access_token` / `refresh_token` / `user_info` 三键 | 45, 113-135 |

### 5.2 白名单校验与拒绝分支（任一失败 → `{ok:false,error,msg}`）

| 分支 | 判据 | 行号 |
|---|---|---|
| `bad-name` | `^[A-Za-z0-9_-]{1,32}$` | 39, 163 |
| `bad-jwt` | `^eyJ…\.[…]\.[…]$` 三段点分 | 41, 164 |
| `bad-mid` | 必须 UUID | 40, 165 |
| `bad-family` | 非 `bigmodel|zai`；或 credentials 混家族 | 84, 95, 100 |
| `bad-cred` | 非字符串 / 空 / > `MAX_CRED_LEN=200000` / **签名密钥形态** / `user_info` 非合法 JSON 对象 / 形态不认识（非 `eyJ|sk-|enc:v1:` 开头且非 JSON） | 44, 46, 118-131 |
| `escape` | `path.dirname(dir) !== path.resolve(accountsDir)`（第二道目录穿越防护） | 271-273 |
| `exists` | 同名目录已存在且未给 `replace` | 274-276 |
| `no-dir` / `no-encrypt` / `mkdir` / `write` | 环境类失败 | 266, 269, 281, 307 |

### 5.3 签名密钥被显式拒绝（本次新增，重要）

`SIGNING_KEY_RE = /^[0-9a-f]{32}\.[A-Za-z0-9_-]{8,}$/`（`import-account.js:43-44`）——即 `<32位hex>.<secret>` 形态的**请求签名凭据**：
- 注释定性：「**按账号派生**，模板/卡片带过来的是别人的」（`import-account.js:43-44, 108-111`）。
- 双位置拦截：`pickOAuth` 逐值拒（123）；`buildConfig` 从模板递归 scrub 时**连同 `CRED_RE` 一起清空**（注释记实测：模板里的 `builtin:zai-coding-plan` 曾带着别人的 49 字符签名密钥，`import-account.js:176-180, 190-196`）。【一手】
- 参考：面板 `main.js:1552-1554 isSigningKeyShaped` 同口径，用于换号时清掉失效的旧签名 key（`main.js:1671-1678`）。【一手】

### 5.4 `family` 的作用与 config 构造（`buildConfig`，`import-account.js:182-214`）

- `PROVIDER_FAMILY`（导入与面板共用同一份，防两边写法飘移，`main.js:1541-1544`）：
  - `bigmodel` → `builtin:bigmodel` / `builtin:bigmodel-coding-plan` / `builtin:bigmodel-start-plan`（`import-account.js:53`）
  - `zai` → `builtin:zai` / `builtin:zai-coding-plan` / `builtin:zai-start-plan`（`import-account.js:54`）
- 只保留**本家族**的 provider，其余 `delete`（187-188）；`nodeKey===true` 时填入 jwt（189）；兜底 provider 强制 `kind:'anthropic'`、`enabled:true`、`options.apiKey=jwt`、`apiKeyRequired:true`、`baseURL` 必须是含 `zcode-plan` 的接口路径（199-212；兜底形状 `62-77`）。【一手】

### 5.5 凭据解密 / 加密的现状（复核 17 的疑问）

- 输入侧：**不做解密**。`enc:v1:` 只是被当作**合法字符串形态**放行（`import-account.js:42, 129-131`）——若卖家给的是**在卖家机器上加密**的密文，导入后客户端也解不开。【一手 + 推断】
- 输出侧：导入时统一 `oauth.encrypt` 重新加密（`zcodejwttoken` / `oauth:active_provider` / 本家族 oauth 三键，`import-account.js:286-292`），密钥派生 = `sha256(ZCODE_CREDENTIAL_SECRET ?? 'zcode-credential-fallback:<platform>:<homedir>:<username>')`（`oauth.js:243-257`）。**含 homedir/用户名** → 跨机器不可移植。【一手】
- 导入的凭据**不经任何联网校验**：不请求 `/billing/balance`、不验 JWT 是否过期、不验 uuid 是否与他人重复；**只有本地写回自检**（`verifyWritten`）。【一手】

### 5.6 跨账号 device_mid 唯一性缺口（复核 17 §⑤：**仍成立**）

- 缺失点：`import-account.js:165` 仅 `UUID_RE.test(mid)`；`importAccount` 只按**目录名**判重（`existsSync(dir)`，274-276），**不按 uid / device_mid 去重**（17 的这条结论在本次副本中逐字成立）。【一手】
- 检索范围与结果（本次已复跑，含新增代码）：
  1. `device_mid|deviceMid|device[-_]?id|ZCODE_DEVICE` → 命中 `main.js`、`import-account.js`、`account-query.js`、`remote-plan.js`（+ `account-query.js:8/56/150-167` 只读展示），逐处核对**无跨账号比较**。【一手】
  2. `重复|冲突|duplicate|conflict|唯一|uniqu`（排除 node_modules/dist）→ 仅无关注释与 `plan.js:90`（`user_plan_id` 是账号级唯一标识）【一手】。
- 后果（面板侧不拦、客户端侧未知）：同一卖家批量发的凭据若复用同一 `device_mid`，面板照单全收 → 服务端按 `X-Device-Mid` **精确分组**时可把多个账号归到同一设备（面板自己在 `main.js:1161-1166` 如此判断）。**服务端是否真按此做风控/是否拒绝，属未验证**。【推断】

### 5.7 落盘产物与写回自检（本次新增）

写盘的 5 个文件（`import-account.js:293-306`）：`v2/config.json`、顶层 `config.json`、`v2/credentials.json`、`v2/telemetry-state.json`（写 `deviceMid` + `lastDailyActiveDate`）、`meta.json`（299-306，含 `via:'import'` / `registered_at_source:'import'` / `family` / `family_source` / `oauth_keys`）。

`verifyWritten`（`import-account.js:221-253`）逐项读回：
1. `credentials.json` 必须有 `zcodejwttoken` + `oauth:active_provider` + **本次传入的每个** `oauth:<family>:<k>`（230-235）——**注意：没传就不查**，故老格式（无 credentials）能过检。【一手】
2. `config.json` 必须有兜底 provider，且 `kind==='anthropic'`、`options.apiKey === 本 jwt`、`baseURL` 含 `zcode-plan`（238-248）。
3. 不得残留非本家族 provider（249-250）。
4. 任一不过 → **删除整个账号目录并返回 `error:'verify'`**（`311-315`）；注释理由：面板的 `valid` 只看文件在不在，若不回滚会留下「永远切不过去」的账号。【一手】

---

## ⑥ 从「拿到外部登录信息」到「本机 ZCode 以该账号可用」的完整链路

### 6.1 逐步链路（通道 D = 买号/外部凭据路线）

| # | 步骤 | 实现/参数 | 行号 |
|---|---|---|---|
| 1 | 拿到凭据 JSON（卖家/小店给），含 `name` + `jwt` + `device_mid`，**新版**另有 `family` + `credentials{oauth:<f>:access_token,user_info[,refresh_token]}` | — | `import-account.js:8-18` |
| 2 | 粘贴/选文件提交，渲染层轻校验「非空」，`replace` 由勾选框决定 | `importAccount(text,{replace})` | `renderer/app.js:1226-1232` |
| 3 | 主进程挑模板（找第一个含 `builtin:` provider 的现成账号 config） | 取不到即兜底最小 config | `main.js:2325-2332` |
| 4 | `normalize` 解析 + 白名单校验（§5.1/5.2）；`resolveFamily` 定家族；`pickOAuth` 取凭据 | 拒绝即返回错误文案给 UI | `import-account.js:138-173, 267-268` |
| 5 | 同名目录已存在 → 默认拒；`replace:true` 且旧目录含 config 才 `rmSync` 覆盖 | **去重键=账号名** | `import-account.js:274-278` |
| 6 | 建 `data/.zcode/v2/`，`buildConfig(template,jwt,family)` 生成 config；凭据经 `oauth.encrypt` 写 `credentials.json`（`active_provider=family`） | — | `import-account.js:280-292` |
| 7 | 写 `telemetry-state.json`（`deviceMid = 传入的 uuid`）+ `meta.json` | — | `import-account.js:298-306` |
| 8 | `verifyWritten` 读回自检；不过则删目录回滚并报 `verify` 错误 | — | `import-account.js:311-315` |
| 9 | **切到该账号**（用户手动点列表里的「切换」）：`switchAccount(id)` → 改 `.current` + 杀进程 + `launchZCode(id)` | 见 §⑦ | `main.js:1320-1360` |
| 10 | 启动注入（关键参数）：`ZCODE_DATA_BASE_DIR=<账号>/data`、`--device-id=<meta.device_mid>`、`ZCODE_DESKTOP_{USER_DATA,SESSION_DATA,HOME}_DIR`、`--remote-debugging-port=9223` | env 以 `{...process.env}` 为基叠加 | `main.js:1224-1270` |
| 11 | 客户端以该账号自己的 `credentials.json`+`config.json` 启动 → 是否被判「已登录」由客户端读 `oauth:<family>:access_token/user_info` 决定 | 面板注释称绑好与没绑只差这两个键 | `import-account.js:13-18`（引 `main.js` bindOAuthToCurrent 实测依据） |

### 6.2 失败条件汇总（导入 → 可用）

| 类别 | 条件 | 结果 | 依据 |
|---|---|---|---|
| 输入形态 | 非 JSON / 非对象 / 空 | `not-json` / `not-object` / `empty` | `import-account.js:140-145` |
| 字段 | 名字非法 / jwt 非三段 / mid 非 UUID | `bad-name` / `bad-jwt` / `bad-mid` | 163-165 |
| 家族 | 未知家族 / credentials 混家族 | `bad-family` | 84, 95, 100 |
| 凭据 | 签名密钥形态 / `user_info` 非 JSON 对象 / 形态不认识 / 超长 | `bad-cred` | 118-131 |
| 重名 | 目录已存在且未勾覆盖 | `exists`（默认拒绝） | 274-276 |
| 落盘 | 写失败 / 自检不过 | `write` / `verify`（**已回滚目录**） | 307-315 |
| **跨设备限制** | ① 32hex.secret 签名密钥一律拒（按账号派生，别人的必然失效，`import-account.js:43-44`）② 跨机器加密的 `enc:v1:` 密文不可解（密钥含 homedir/用户名，`oauth.js:248-253`）③ **device_mid 与他人重复不拦**（缺口，§5.6）④ 卖家凭据是否已被服务端风控/是否异地登录受限 → **本仓库无从验证** | ①②③ 见左；④ 未验证 | 同左 |
| 切换 | 目录无 `credentials.json` → 拒切（提示先登录一次）；客户端找不到 → `launchZCode` reject；**进程立刻退出（单实例锁）→ 明确报错** | `switchAccount` 仍返回 `ok:true` + `launchError`（标记已改） | `main.js:1323-1328, 1216-1222, 1289-1304, 1345-1359` |
| 服务端 | 验证码 / 人机验证：**导入通道完全不需要**（不联网）；只有通道 A/B 的授权环节要人工过人机验证 | 通道 A 需人工（拼图+短信）；通道 B 借用用户浏览器的既有登录态（是否再触发验证码由上游决定，【推断】通常免） | `login-driver.js:262-272, 346`；`main.js:2298-2312` |
| 重定向例外 | 通道 B 用 `mode='direct'` 的 `zcode://oauth/callback`；面板内窗口用 https 桥接页（`mode='bridge'`）。**回调无本地 HTTP server**，靠窗口导航事件 + `zcode://` 协议在面板进程内被接住 | `oauth.js:66-76`；`main.js:2273-2288, 2297-2312` | — |

---

## ⑦ 切换账号使登录生效的链路 + 对 `~/.zcode` 的写入面

### 7.1 `switchAccount(id)`（`main.js:1320-1360`，当前副本口径）

1. 账号目录不存在 → `{ok:false}`（1321-1322）。
2. `credentialsOf(id)` 不存在 → 拒绝并提示「先切到它、在弹出的客户端里登录一次」（1323-1328）。
3. `prevId = readCurrentId()`（1330；读 `accounts/.current`，`main.js:172-181`）。
4. `killZCode()`（1332）→ **`waitZCodeGone(8000)` 轮询**；超时则 `killZCode(true)`（`pkill -9 -x`）+ 再等 4s（1335-1338）。杀进程口径：Win `taskkill /IM ZCode.exe /F`；mac `pkill -x ZCode`（必须 `-x`，否则连带 `ZCode Helper`/`ZCode Panel`，`main.js:1105-1123`）。
5. `writeCurrentId(id)`（1340，**先改标记**）→ `bumpSwitchMeta(dir,'switch')`（1341 → 1428-1443）。
6. `launchZCode(id)`（1347）：见 7.2。启动失败**不把整次切换判失败**，只回传 `launchError`（1343-1350）；**无回滚 prevId 分支**（返回 1351-1359）。
7. 前端 `doSwitch` = `setLoading` + `switchTo` + `toast` + `refresh()`，无回滚分支；不足 1 天的账号先 `confirm`（`renderer/app.js:429-440`）。【一手】

### 7.2 `launchZCode(accountId)` 的注入顺序（`main.js:1206-1306`）

`accountId` 为空 → 直接 reject（**不做无账号兜底**，注释「否则会直接改动你本机的 `~/.zcode`」，1207-1209）→ 账号目录不存在 → reject（1210-1212）→ **先校验客户端可执行文件**（1216-1222）→ 组参数/env（1224-1225）：
1. `accountDeviceId` → `args.push('--device-id=<mid>')` + `syncDeviceMidToZCode`（1228-1230）；
2. `env.ZCODE_DATA_BASE_DIR = <账号>/data`（1235-1237）；
3. `sessionIndex.syncIn(<账号>/data/.zcode/v2, ~/.zcode/v2, id)`（1244-1249）——**在 spawn 之前**（此时旧客户端已退出）；
4. `linkSharedZcodeDirs(id)`（1253 → 123-155）：把 `cli/`、`workspace/`、`plugin-workspace/` 软链回 `~/.zcode/`（`SHARED_ZCODE_DIRS`，87；`linkDir` 只占空目录、有内容绝不动，103-120；mac 同时处理 `home/.zcode` 回链，见 132-142 注释）；
5. `mkdir` 三个目录 + 注入 `ZCODE_DESKTOP_{USER_DATA,SESSION_DATA,HOME}_DIR`（1262-1270）；
6. `spawn(exe, args, {detached:true, stdio:'ignore', env})` + `unref()`；**进程若立刻退出 → reject（单实例锁冲突）；1500ms 后仍存活才算成功**（1273-1305）。
7. 另有 `invalidateProviderConfig(id)`：删 `<账号>/v2/provider_config.json`，逼客户端从 config.json 重新导入（`main.js:156-165`，被 `applyOAuthToken` 调用 1690）。【一手】

### 7.3 面板对主 `~/.zcode` 的写入面（**当前副本=三处**，17 记两处）

| # | 写入项 | 触发 | 行号 |
|---|---|---|---|
| ① | `~/.zcode/v2/setting.json`（`httpProxy`） | 仅在用户点「用系统代理 / 清除」时；实测 `ZCODE_DATA_BASE_DIR` **不管** setting.json，且环境变量 `ZCODE_HTTP_PROXY` 客户端完全不读 | `main.js:73, 975-984, 956-960` |
| ② | `~/.zcode/v2/tasks-index.sqlite(-wal)` | `sessionIndex` 回写：`syncIn` 内对上次播种账号 `syncOut`（有标记文件才回写，回写后删标记）；`copyDbFamily` 只拷 main+wal、**不拷 shm**，源端无 wal 时清目标陈旧 wal/shm | `main.js:1244-1249`；`session-index.js:38-39, 61-81, 88-95, 103-138` |
| ③ | **`~/.zcode/{cli,workspace,plugin-workspace}/`（建目录联接）+ `~/.zcode/` 下 `home/.zcode` 回链** | 每次 `launchZCode` 调 `linkSharedZcodeDirs`；`linkDir` 在目标不存在时 `mkdirSync(target)` | `main.js:87, 103-120, 123-155`（114） |
| 读（非写） | 旧凭据一次性迁移（`~/.zcode/v2/credentials.json`+`config.json` → 账号目录） | 仅 `captureAccount` 且账号侧无凭据时 | `main.js:755-775` |

其余 `LEGACY_*` 引用均为只读或建联接路径（`main.js:26-27, 73, 129, 142, 755-756, 1245`）。防御性闸门两处仍在：无账号拒启动（1207-1209）、`curPaths()` 无当前账号返回 `null` 且注释「绝不能退回全局 `~/.zcode`」（`main.js:192-206`）。【一手】
会话索引的边界（17 §⑥ 推断）**未变**：全仓仍**无退出钩子**（`main.js` 仅 `app.on('second-instance')` 2892 与 `app.on('window-all-closed')` 2906），`syncOut` 唯一调用方仍是下一次 `syncIn`（`session-index.js:107-108`）。【一手】

---

## ⑧ 相对 17/18 的版本增量与结论漂移

### 8.1 版本判定方法（先定基线钉在哪一版）

- 工作区**已有未提交改动**（`import-account.js` / `main.js` / `settings.js` / `update.js` / `package.json` / `renderer/app.js` / `renderer/index.html`，另有 `build/`）——即 17/18 写作（2026-09-26 08:09）之后，作者又继续改到 2026-09-28 07:02。【一手】
- 判定：17 §⑤ 引用的 `import-account.js:27/28/29/58/59/60/148` 与 **git HEAD 版逐行吻合**（`git show HEAD:import-account.js` 同名行号），而当前工作副本该文件已重写（`NAME_RE` 39 / `UUID_RE` 40 / `JWT_RE` 41 / 校验 163-165 / `module.exports` 325-328）→ **17 §⑤ 是对旧版（HEAD 版）的结论**。
- 17 §①/§④ 引用的 `main.js` 行号（`switchAccount` 1276、`ZCODE_DATA_BASE_DIR` 1204、`accounts:import` 2270）**既不等于 HEAD（1194 / 1124 / 2188）也不等于当前（1320 / 1237 / 2323）** → 17 写于 09-26 07:02 的中间态，其后 main.js 又改动过（当前较 17 整体后移约 +33~+50 行）。
- `settings.js`（17 §⑦）引用与当前一致（`mdfind` 236 / `detect` 337 / `describeExe` 140 / `normalizeClientPath` 133）→ **该节无需漂移修正**。
- `session-index.js` / `account-query.js` / `oauth.js` / `plan.js` / `login-driver.js` / `balance.js` 未改动（`git status` 未列出）→ 17 §⑥、18 全文的行号结论**基本保持**（本次抽验：`session-index.js` 38/61/88/103/124-128/133-134 全中；`plan.js` 36/37/40/71/207 全中；`login-driver.js` 334/569/475/181 全中）。【一手】

### 8.2 行号漂移速查（17/18 → 当前）

| 引用点 | 17/18 记 | 当前 | 漂移 |
|---|---|---|---|
| `env.ZCODE_DATA_BASE_DIR`（隔离支点） | main.js:1204 | **1237** | +33 |
| `switchAccount` | main.js:1276-1309 | **1320-1360** | +44 且逻辑改写 |
| `launchZCode` | main.js:1191-1237 | **1206-1306** | 逻辑改写 |
| `accountDeviceId` | main.js:1135-1145 | **1168-1178** | +33 |
| `syncDeviceMidToZCode` | main.js:1149-1164 | **1182-1197** | +33 |
| `accounts:import` IPC | main.js:2270-2292 | **2323-2345** | +53 |
| `writeLiveBackToSnapshot` | main.js:1317-1319 | **1368-1370** | +51 |
| `rollback` | main.js:1438-1478 | **1499-1532** | +61 |
| 单实例锁 | main.js:2829-2833 | **2889-2892** | +60 |
| `sessionIndex.syncIn` 调用点 | main.js:1212 | **1245** | +33 |
| `import-account.js` 全部引用 | 18、27-30、58-60、113-119、122-141 | **39-46、163-165、274-278、283-306、317-328** | **整文件重写** |
| `zcodeSettingFile`（setting.json 例外） | main.js:66-73 | **65-73** | 0（§③ 结论不变） |
| `app.js doSwitch` | app.js:429-440 | **429-440** | 0（结论不变） |

### 8.3 结论漂移（只列会改变判断的）

| # | 17/18 原结论 | 当前事实 | 定性 |
|---|---|---|---|
| 1 |（17 §④）「切换 = killZCode + `wait(800)` 固定睡眠」 | 改为 `waitZCodeGone(8000)` 轮询 + 超时 `kill -9` + 再等 4s（`main.js:1335-1338`） | **行为升级**（修「切了号但登录态没变」的一条独立成因，注释 1140-1146） |
| 2 |（17 §④）「spawn 后 500ms 无 error 即视为成功」 | 改为 **1500ms + 检测 `exitCode/killed`**，起来就退（单实例锁冲突）**明确 reject**（`main.js:1289-1304`） | **行为升级** |
| 3 |（17 §④）「launch 不校验 exe 存在」 | 新增 **spawn 前 `describeExe` 预检**（`main.js:1216-1222`） | **新增**（防无人接的异步 error） |
| 4 |（17 §⑤）「jwt 写进 `options.apiKey`，仅 `nodeKey===true` 时同写 `nodeKey`」 | 仍成立（`import-account.js:189`），另新增 `apiKeyRequired:true` 与 baseURL 强制含 `zcode-plan`（207-211） | 复核一致 + 加强 |
| 5 |（17 §⑤）「导入只校验 UUID 格式、不查跨账号唯一性」 | **仍成立**（§5.6） | **复核一致（缺口未修复）** |
| 6 |（17 §⑤）「config 剔除第三方 provider、scrub 凭据」 | 仍成立，且 scrub 加入签名密钥形态（`import-account.js:190-196`） | 复核一致 + 加强 |
| 7 |（17 §⑤）「按目录名判重、`replace` 才覆盖、只有含 config 才 `rmSync`」 | **完全一致**（`import-account.js:274-278`） | 复核一致 |
| 8 |（17 §⑤）「无 family 概念、无 verify 自检」 | 新增 `family` 双家族（52-104）、`verifyWritten` 回滚（221-253, 311-315）、`pickOAuth`（113-135） | **新增** |
| 9 |（17 §①.4）「隔离例外：setting.json / 内置浏览器 session / 三个共享目录 / home/.zcode」 | 例外全部成立；但**内置浏览器 session 的注释已改写**：现为「面板只用于诊断展示、**不写**这些目录」+ mac 实测（3.14.3）与 Windows 同构（`main.js:225-230`），17 引用的「六个账号共用这一份」原句在本次副本中已不存在 | 复核一致（表述有漂移） |
| 10 |（17 §⑨）「补一条 device_mid 跨账号唯一性检查」的建议 | 面板作者**仍未补**；Q27-⑤ 要求我们自建 → **该建议对我们仍是有效补偿项** | 复核一致 |
| 11 |（18 §②）`balance.js` 端点 / `plan.js` 日志主用 / 3012 熔断 | 未改动文件，抽验行号全中（`plan.js:36-37`、`remote-plan.js:33/38`） | 复核一致 |
| 12 |（18 §⑦）`account-query.js` 的角色（联网查券+日额度，CLI sleep 2600ms） | 一致（`account-query.js:58-148, 184, 195`）；另注：其默认账号库**三级回退**含同级 `zcode-switch/accounts`（42-49） | 复核一致 + 补充 |
| 13 |（18 §⑤/§⑩）未提 `deriveSigningKey` | **新增发现**：`remote-plan.js:192-227` 导出但全仓无调用（含可选 `createIfMissing` 会在平台侧建 api key） | **18 的漏项**（详见 §⑨.3） |

### 8.4 本次相对 17/18 的**新增**事实（不属于漂移，是新增覆盖）

- 「买号」外链三段式（§④）与**无支付功能**的负向结论（4.2）。
- 通道 B「浏览器授权导入」的完整机制（`oauth.js:78-95, 116-123`；`main.js:2261-2295`）——18 只提到 OAuth 主流程，未覆盖此通道。
- `bind` 模式（附加 BigModel 到当前身份）与「全仓无 UI 调用方」的休眠状态（§3.1）。
- 导入自检 `verifyWritten` 与回滚（§5.7）。
- 签名密钥形态的拒绝与派生函数（§5.3、§⑨.3）。

---

## ⑨ 网关侧借鉴点（映射 Q27-⑤/⑥ 已有定论）

> 前提：Q27-⑤/⑥ 已定「ZCode 设备身份独立实现（`ZCODE_DATA_BASE_DIR` 整根隔离 + 每账号 `--device-id`）+ 必须补跨账号唯一性；隔离路线采整根隔离」。**不重复已定部分**，只列增量与风险。

| # | 借鉴点 | 证据 | 映射/增量 | 风险 |
|---|---|---|---|---|
| 1 | **外部凭据导入 = 单收口 + 白名单 + 默认拒绝覆盖 + 写回自检回滚** | `import-account.js:264-323`（自检 221-253、回滚 311-315） | Q27-⑥ 采整根隔离后，我们的「导入外部凭据」入口应同构：**导入后读回校验**（缺 provider / kind / apiKey / baseURL 任一即删目录），否则会留下「网关认为有效、ZCode 客户端判未登录」的账号（面板注释原话 217-219） | 自检**只校验已给字段**（无 access_token/user_info 也过检，230-235）→ 我们应把「必需键全集」写死，而非按 input 动态取 |
| 2 | **凭据解密必须本地重加密，且不可跨机移植** | `oauth.js:243-257`；`import-account.js:286-292`；**导入侧不解密输入密文** | 我们的号池若从别处收凭据：`enc:v1:` 密文（派生含 homedir/username）**跨机必解不开**，只有明文 jwt/access_token 可迁移；导入时应**一律重新加密**，并**拒绝把出售方的 `<32hex>.<secret>` 签名密钥当凭据收下**（`import-account.js:43-44, 123`），改为本地派生 | 若接受密文并原样落盘，表现为「账号能导入、切过去登不上」，属最难查的一类故障 |
| 3 | **签名凭据可由 access_token 本地派生**（`deriveSigningKey`：`getCustomerInfo` → 组织/项目 → `api_keys` 列表 → `/copy/<apiKey>` 取 `secretKey`，拼 `<apiKeyId>.<secretKey>`） | `remote-plan.js:175-227`；`KEY_NAME='zcode-api-key'`（25）；**导出但无调用方**（229-238） | 直接服务 Q27-④ 的签名需求：拿到 access_token 即可**按账号派生**签名 key，无需卖家提供；配合「导入时拒收他人的签名 key」形成闭环 | ⚠️ `options.createIfMissing=true` 时**会在平台侧创建 api key**（212-219）——**写操作**；我们应只读复用（`createIfMissing` 缺省 false），不得默认创建。另：注释「与客户端本地保存的完全一致」为面板自述，**未验证** |
| 4 | **导入的老格式（仅 jwt+device_mid）不足以判定「登录完整」** | `import-account.js:13-18, 286-292, 230-235` | 我们的导入契约应要求 `${family, access_token, user_info}` 齐全并为**硬校验**；只给 jwt 的「半份凭据」应显式降级为「仅可查额度、不可启动客户端」而不是照收 | 面板现状=照收 + 自检放行 → 用户体验上是「导入成功但用不了」 |
| 5 | 🔴 **跨账号 device_mid 唯一性校验（用户点名项）在参考项目仍缺，我们必须自建** | `import-account.js:165`（仅格式）；全域检索无比较逻辑（§5.6 的检索范围） | Q27-⑤ 已定「分配前查注册表，冲突则重新生成」→ 本次复核确认**该补偿项未因参考项目更新而失效**；另建议把校验前移到**导入入口**（而不是只在启动分配时），否则冲突会在导入后才暴露 | 冲突来源真实存在：同一卖家批量发货、或「同一份备份被导入两次换名」→ 服务端按 `X-Device-Mid` 精确分组（面板自述 `main.js:1161-1166`），多个账号同设备可能触发上游风控 |
| 6 | **切换成功的判据要绑「新进程没自杀」而非 spawn 返回** | `main.js:1289-1304`（起来就退 = 单实例锁冲突），配 `waitZCodeGone` 轮询（1149-1156） | 我们若同样「换数据根重启」客户端：必须 ① 等旧进程真退出（轮询 + 超时强杀）② 检测新进程是否立即退出，否则会出现「网关说已切换、实际还是旧登录态」 | 固定 sleep 在客户端退出慢时（flush `tasks-index.sqlite` 实测单账号 3MB）必然偶发失败 |
| 7 | **`provider_config.json` 一次性 legacy 导入的坑** | `main.js:156-165`（删掉该文件逼客户端重读 config.json）；调用点 1690 | 我们直接改 `config.json` 注入 provider 时，**必须同时作废 `provider_config.json`**，否则客户端继续用旧 provider 表 | 静默失效（改了对不上），排查成本高 |
| 8 | **导出但未挂 UI 的休眠能力**（`bind` 模式 / `deriveSigningKey`） | `main.js:1780-1811`；`remote-plan.js:192-227` | 说明参考项目在「把 BigModel 附加到既有 Z.ai 身份」「派生签名 key」两条线上已有实现，可作我们设计输入 | 休眠代码未经端到端验证，直接照搬需自测 |
| 9 | **`account-query.js` 的 CLI 形态**（先校验后取值 / 不把 400 读成「没有券」/ 每账号 sleep 2600ms / 账号库三级回退） | `account-query.js:58-148, 42-49, 184-195` | 与 Q27-④「批量执行器 + 逐账号失败隔离」同构：我们的 `mgw` 巡检子命令可直接复用这套「先判 status/code 再取字段」的写法与 2600ms 节流口径 | 3012 阈值未知（18 §⑩.2 未变），需按 2600ms + 熔断兜底 |

**明确不借鉴**（与 Q27-⑨ 边界一致）：小店内窗/免费号池这类**外部商业入口**（§④）——个人自用网关不需要，且引入外部站点依赖与合规不确定性。

---

## ⑩ 未验证清单

1. 【未验证】「只给 jwt+device_mid 的老格式导入」在客户端侧是否被判「未登录」（面板注释称「带 family + credentials 的那份才算登录完整」，但自检不强制）。需实机导入一次并启动客户端观察。
2. 【未验证】同一个 `device_mid` 被两个账号复用（跨账号重复）时，**服务端**是否拒绝/风控；面板只在注释层面判断「服务端按 device_mid 精确分组」（`main.js:1161-1166`），本仓库无从证实服务端策略。
3. 【未验证】`deriveSigningKey`（`remote-plan.js:192-227`）派生结果与客户端本地保存的签名密钥是否真「完全一致」——注释自述，未在客户端侧比对；其 `createIfMissing` 分支的真实副作用（是否创建 api key / 是否影响既有 key）未实测。
4. 【未验证】`shop.youyuaiwan.xyz` 与 `youyuaiwan.xyz/free.html` 的**实际内容**（是否有付费购买、发的是何种凭据、是否绑定机器）——调研全程只读本地仓库，**未访问任何网络**。
5. 【未验证】小店「买完自动导入」窄桥的**未来设计**（`main.js:2379-2381` 只是承诺挂 preload 前必须校验来源 origin + 字段格式）；当前实现为零。
6. 【未验证】mac 侧三个 `ZCODE_DESKTOP_*` 环境变量是否真能覆盖客户端 `app.setPath`（沿用 17 §⑩.5 的未验证项，本次未新增证据）。
7. 【未验证】`import-account.js` 的 `PROVIDER_FAMILY` 是硬编码白名单（仅 `bigmodel`/`zai`），第三家族会直接被拒；未验证客户端未来是否引入第三家族。

---

## ⑪ 零改动证明

**材料目录零改动**——全程仅用 Read/Grep/Glob，未写入、未运行其代码/安装依赖/联网。

1. 开工前已记录源文件 md5（工具输出另存 `/tmp/zcode-panel-hashes-before.txt`），收工时重跑同一命令比对，**全部一致**（含 `main.js` / `import-account.js` / `renderer/app.js` / `renderer/index.html` / `settings.js` 等 17 个文件）。
2. `git -C "/Users/w/Desktop/zcode相关管理软件/ZCode-Panel" status --porcelain` 收工输出（**非空，但为调研前既有状态，非本次造成**）：

```
 M import-account.js
 M main.js
 M package.json
 M renderer/app.js
 M renderer/index.html
 M settings.js
 M update.js
?? build/
```

> 说明：任务下发时的预期是「输出应为空」，实际**不为空**——这是被调研项目作者自己的在途修改（文件 mtime 2026-09-26 ~ 09-28，早于本次调研），也正是本报告 §⑧ 要复核的那批增量。本次调研未对其做任何改动（md5 前后一致为证）。
3. 本报告只写了本文件（`docs/research/22-…md`），未触碰 Model-Gateway 的源码 / 测试 / `data/`，未访问 `127.0.0.1:8300`。

