# verify-F · F1/F2 独立核验报告（证伪视角）

> 核验员：独立第三方（未参与 F1/F2 写作）
> 核验对象：`F1-数据隔离与账号切换.md`、`F2-登录额度与套餐.md`
> 参考项目：`/Users/w/Desktop/zcode相关管理软件/ZCode-Panel/`（**全程只读，未做任何修改**）
> 核验脚本/命令：全部在 `/tmp` 或只读 grep，未写入参考项目
> 核验日期：2026-09-26
> L1（引用可解析）由主 agent 完成（3544 条引用 0 问题），本报告**不重复** L1，只做 L2/L3/L4。

---

## 0. 核验方法与检索范围声明

- **L2**：对每条决策级断言，用 Read 工具逐行读原文，核对「行号 + 内容是否被曲解」。
- **L3**：负向断言（"某能力不存在"）用**全仓检索**（`grep -rn --exclude-dir=node_modules --exclude-dir=dist --exclude-dir=build`）复核，不局限于草稿自述的文件。
- **L4**：所有数字独立重算（`wc -l` / 读代码常量 / 自数）。
- 参考项目 `accounts/` 目录**为空**（0 个账号目录），故一切"实测 N 个账号"类数字**无法从仓库复算**，只能标为「引用注释」。

---

## 1. 核验结论表

### 1.1 F1 决策级断言

| # | 断言（原表述） | 结论 | 证据（文件:行号 + 原文片段） |
|---|---|---|---|
| F1-1 | 隔离支点 `ZCODE_DATA_BASE_DIR=<账号>/data`（`main.js:1204`） | ✅证实 | `main.js:1204 env.ZCODE_DATA_BASE_DIR = root;`，`root = dataRootOf(accountId)`（1202），`dataRootOf = accountsDir/id/data`（56-57） |
| F1-2 | ZCode 在其下自建 `.zcode/v2/` | ✅证实 | `main.js:58 zcodeV2Of = path.join(dataRootOf(id), '.zcode', 'v2')`；注释 53-55「它会在 `<X>\.zcode\v2\` 下建出 config.json / logs / certs / telemetry-state.json」 |
| F1-3 | 三个 desktop 环境变量在 `main.js:1229-1237` | ✅证实 | 1229-1231 拼 `userdata`/`session`/`home`；1235-1237 `env.ZCODE_DESKTOP_USER_DATA_DIR / _SESSION_DATA_DIR / _HOME_DIR` |
| F1-4 | `accountDeviceId()` 读 `meta.json.device_mid`，缺失才 `crypto.randomUUID()`（`main.js:1135-1145`） | ✅证实 | 1136 `path.join(accountsDir(), id, 'meta.json')`；1138 `if (typeof meta.device_mid !== 'string' \|\| !meta.device_mid.trim())`；1139 `meta.device_mid = crypto.randomUUID()` |
| F1-5 | 生成一次**永不重算** | ✅证实 | 1138 仅在缺失/非法时生成；1131 注释「生成一次后永久复用」 |
| F1-6 | 捕获/新建都写 `old.device_mid \|\| randomUUID()`（`:812`、`:1693`） | ✅证实 | `812 device_mid: (old && old.device_mid) \|\| crypto.randomUUID(),`；`1693 device_mid: old.device_mid \|\| crypto.randomUUID(),` |
| F1-7 | 同时喂两条通道：`--device-id=<uuid>`（`:1196`）与 `telemetry-state.json` 的 `deviceMid`（`:1149-1164`） | ✅证实 | 1196 `args.push('--device-id=' + mid)`；1197 `syncDeviceMidToZCode(mid, accountId)`；1149-1159 写 `cur.deviceMid`，1155 值相同则跳过 |
| F1-8 | `setting.json` 仍读写主 `~/.zcode/v2/`（`main.js:66-73`） | ✅证实 | 73 `zcodeSettingFile = () => path.join(LEGACY_ZCODE_V2, 'setting.json')`；读 `getZcodeProxy` 956-960，写 `setZcodeProxy` 975-984 |
| F1-9 | `cli/workspace/plugin-workspace/home/.zcode` 有意联回主目录（`:87`、`:142`） | ✅证实 | 87 `SHARED_ZCODE_DIRS = ['cli','workspace','plugin-workspace']`；128-130 `linkDir(...LEGACY_ZCODE_ROOT, name)`；142 `linkDir(accountId/home/.zcode, LEGACY_ZCODE_ROOT)` |
| F1-10 | ZCode 内置浏览器 session **六账号共用**（`:221-230`） | ⚠️部分证实 | 代码注释 224 原文确为「**六个账号共用**这一份」；但"六"是**作者本机状态的注释**，仓库 `accounts/` 为空（0 目录），**无法复算**。见 §4 |
| F1-11 | 切换**零文件复制** | ❌证伪（绝对化表述） | `switchAccount`（1276-1309）本身确无 copy；但它调 `launchZCode`→`sessionIndex.syncIn`（1212），`session-index.js:68/72` 会 `copyFile` `tasks-index.sqlite` 及 `-wal`。代码注释 1268「一个字节的文件复制都不需要」仅指**凭据** |
| F1-12 | 切换**不覆写凭据** | ✅证实 | `switchAccount` 无任何写 `credentials.json` 的调用；全仓 `copyFileSync` 命中 769/770（捕获迁移）、1546/1547/1750（OAuth 备份），均非 switch |
| F1-13 | 切换**无自动回滚** | ✅证实 | `switchAccount` 1294-1308 无回滚分支，`prevId` 仅回传；`rollback()`（1448-1478）已改为"按当前账号重启"，且只由 IPC `accounts:rollback`（2509）手动触发 |
| F1-14 | 导入只校验 UUID 格式，不查跨账号唯一性 | ✅证实 | `import-account.js:60 if (!UUID_RE.test(mid))`，全文无跨账号比较；检索 `device_mid\|deviceMid\|device[-_]?id\|ZCODE_DEVICE` 仅命中 import-account.js / main.js / account-query.js / remote-plan.js，逐一核对无唯一性检查 |
| F1-15 | 隔离唯一支点、ZCode 自建 v2、凭据/配置/日志/遥测全落进去 | ✅证实 | 见 F1-1/F1-2；`credentialsOf/configOf/planCacheOf/telemetryOf/logsOf` 均基于 `zcodeV2Of`（59-63） |
| F1-16 | 面板对 `LEGACY_ZCODE_V2` 的**唯一写入是 setting.json**；8 处匹配逐一核对**无其它写点** | ❌证伪 | 8 处匹配（26/27/73/129/142/755/756/1212）本身准确；但 `main.js:1212` 的 `syncIn(..., LEGACY_ZCODE_V2, ...)` 内部 `syncOut` 会把 `tasks-index.sqlite(+wal)` **回写进 `~/.zcode/v2/`**（`session-index.js:88-95, 92`）。故主目录**至少还有一处写点**。且与 F1 §⑥ 自述「syncOut 回写共享库」**自相矛盾** |
| F1-17 | `session-index` 在切换边界做文件拷贝补偿，而非符号链接（`session-index.js:5-25`） | ✅证实 | 23-25「正确做法：在切换边界做文件拷贝…只拷 main + wal，不拷 shm」；18-21 解释不用符号链接的原因 |
| F1-18 | `SYNC_FILES = ['tasks-index.sqlite','tasks-index.sqlite-wal']`（38）；不拷 shm（25,133） | ✅证实 | 38 定义；25 注释；133 `fs.rmSync(...'-shm', { force: true })` |
| F1-19 | `syncIn` 步骤 1-5（回写上一次、清符号链接、安全阀、copyDbFamily、删 shm+写标记） | ✅证实 | 107-109 / 113-116 / 124-128 / 129 / 133-134 逐条对应 |
| F1-20 | 陈旧 WAL 陷阱（54-57, 61-81） | ✅证实 | 54-57 注释；70-79 源无 wal 时删目标 `-wal`/`-shm` |
| F1-21 | `syncOut` 只在标记文件存在时回写，回写后删标记（88-95, 93） | ✅证实 | 90 `if (!fs.existsSync(markPath(dataV2))) return 'not-seeded'`；93 `fs.rmSync(markPath(dataV2), { force: true })` |
| F1-22 | 无退出钩子；`main.js` 仅有 `app.on('second-instance')`（2836）与 `window-all-closed`（2850）；`app:quit` 只调 `killZCode()`（2824-2827） | ✅证实 | 全仓检索 `before-quit\|will-quit\|'quit'\|app.on(`：仅 2836、2850（2378 是注释）；2824-2827 `app:quit` 仅 `await killZCode()` |
| F1-23 | `syncOut` 唯一调用方是下一次 `syncIn`（`session-index.js:107-108`） | ✅证实 | 全仓 `syncOut` 仅 88（定义）、108（调用）、140（导出） |
| F1-24 | `copyDbFamily` 失败只记字符串不抛（68-69, 73）；`syncIn` 不校验结果，调用方仅 `console.log`（`main.js:1213`） | ✅证实 | 68-69/72-73 catch 里只 `notes.push(...)`；1213 `console.log('[session-index] 播种 ' + ...)` |
| F1-25 | 客户端探测顺序 `currentExe`（95-105）：设置 > `ZCODE_EXE` > `lastDetect` > `commonPaths` > 占位猜测 | ✅证实 | 97/98/99/100-103/104 逐条对应 |
| F1-26 | `detect()` 六源顺序（337-390） | ✅证实 | 352 env；356-357/361-362 注册表协议；236/372 LaunchServices；358/363-368/303-331 卸载项；210-228/369/373 进程；244-261/376 常见路径；264-294/377 子目录扫描 |
| F1-27 | 同路径**合并而非去重丢弃**，`sources` 累加（339-349）；命中取第一个 `ok`（379） | ✅证实 | 343-347 `if (hit) { if (!hit.sources.includes(source)) hit.sources.push(source); continue; }`；379 `tried.find((t) => t.ok)` |
| F1-28 | `describeExe()` 校验规则（140-171） | ✅证实 | 144-147 存在且是文件；148-152 Win `.exe`/mac `.app/Contents/MacOS/`；153-155 basename 含 zcode；160-161 app.asar→good；163-164 Resources→warn；166-170 都没有→warn |
| F1-29 | `normalizeClientPath` 补 `Contents/MacOS/ZCode`（133-138）；`existsRaw` 临时 `noAsar`（116-126） | ✅证实 | 136 `if (/\.app$/i.test(t)) return path.join(t,'Contents','MacOS','ZCode')`；119 `process.noAsar = true` |
| F1-30 | 账号库优先级（409-414）：设置 > `ZPANEL_ACCOUNTS_DIR`（399）> 打包态 `APP_DIR/accounts`（404）> 源码态 `__dirname/accounts`（405） | ✅证实 | 逐条对应 |
| F1-31 | 授权代理绕过名单（1872）与 `applyOAuthProxyPolicy`（1884-1904）五步 | ✅证实 | 1872 常量；1887 resolveProxy；1889-1891 untouched；1893-1897 setProxy；1899 closeAllConnections |
| F1-32 | 授权分区全局共用 → 每次授权前 `clearPanelOAuthSession()`（1959-1966 → 1043-1086） | ✅证实 | 1959-1966 调用；1043-1086 实现 |
| F1-33 | `ZCODE_HTTP_PROXY` 环境变量完全不被读取（965） | ✅证实 | 965 注释原文 |
| F1-34 | 前端 `doSwitch` **仅 toast**（`renderer/app.js:429-440`） | ⚠️部分证实 | 429-440 除 `toast` 外还有 `setLoading`/`api.switchTo`/`refresh`（436-439）。核心意思（前端无回滚逻辑）成立，但"仅 toast"不准确 |
| F1-35 | 导入白名单：名字 `^[A-Za-z0-9_-]{1,32}$`（27,58）、jwt `^eyJ…`三段（29,59）、device_mid UUID（28,60） | ✅证实 | 27/29/28 定义，58/59/60 校验；28 含 `/i` 大小写不敏感 ✓ |
| F1-36 | 去重键=账号名；`existsSync(dir)` 默认拒绝，`replace:true` 才覆盖（113-119）；目录穿越双保险（115） | ✅证实 | 113/116/118/119/115 逐条对应 |
| F1-37 | `buildConfig` 只留 `builtin:`、删第三方、jwt 写 `options.apiKey` 与 `nodeKey`、`CRED_RE` scrub（79-85）、兜底 `builtin:bigmodel-start-plan`（88-93） | ⚠️部分证实 | 75 删除非 builtin；76 `options.apiKey = jwt`；**77 `if (v && v.nodeKey === true) v.nodeKey = jwt;` —— 仅当 nodeKey 恒等 true 才写**，非无条件；79-85 scrub；88-93 兜底。表述"写进 …与 nodeKey"漏了 `=== true` 条件 |

### 1.2 F2 决策级断言

| # | 断言（原表述） | 结论 | 证据（文件:行号 + 原文片段） |
|---|---|---|---|
| F2-1 | 额度读取实为「一日志 + 联网」两通道 + 独立余额通道 | ✅证实 | 日志=`plan.js`（35-37）；联网=`remote-plan.js`（27,125）+ `account-query.js`（35,58）；余额=`balance.js`（25-26, 156-160）。三路数据不重叠（draft §② 判断正确） |
| F2-2 | 读日志的是 `plan.js`（**不是** `balance.js`） | ✅证实 | `plan.js:6` 注释「数据源：客户端自己的日志 ~/.zcode/v2/logs/…」；`balance.js:10-14` 走 `open.bigmodel.cn` biz 网关。**子 agent 对主 agent 错误假设的纠正本身正确** |
| F2-3 | `balance.js` 走 BigModel biz 网关查余额/资源包/订阅 | ✅证实 | 157 `/api/biz/account/query-customer-account-report`；158 `/api/biz/tokenAccounts/list/my`；159 `/api/biz/subscription/list` |
| F2-4 | README:222 把 `balance.js` 标为「客户端日志里的额度读取」属笔误 | ✅证实 | `README.md:222` 原文「balance.js        客户端日志里的额度读取」；223 才是「plan.js  套餐额度解析（读该账号自己的日志）」 |
| F2-5 | 日志通道读 `~/.zcode/v2/logs/YYYY-MM-DD.log`，默认该目录，只扫最近 3 天（40-51） | ✅证实 | 35 `LEGACY_LOG_DIR = ~/.zcode/v2/logs`；44 `for (let i = 0; i < 3; i++)` |
| F2-6 | 标记 `billing/balance 请求完成 ` + 括号配对抠 JSON + 取尾 4MB | ✅证实 | 36 `MARKER = 'billing/balance 请求完成 '`；37 `TAIL_BYTES = 4 * 1024 * 1024`；54-65 readTail；71-88 extractJson（含字符串/转义处理） |
| F2-7 | 最多回看 80 条（124） | ✅证实 | 124 `while (at >= 0 && guard < 80)` |
| F2-8 | 联网通道打 `zcode.z.ai/api/v1/zcode-plan/billing/balance`，需 `Bearer <jwt>` + `X-Device-Mid` | ✅证实 | 24 `ZCODE_ORIGIN`；27 `BILLING_PATH`；142 url；146-147 两个必需头 |
| F2-9 | 缺 `X-Device-Mid` → 400 code=3001（remote-plan.js:11-12,138-140） | ✅证实 | 11-12 注释；138-140 早退 |
| F2-10 | **3012 = 服务端风控 unusual activity，命中即熔断 30 分钟** | ✅证实 | 14-15 注释「billing/current 已被服务端风控…405 code=3012 blocked due to unusual activity」；103 `if (body && body.code === 3012) enterCooldown(body.msg)`；38 `COOLDOWN_MS = 30 * 60 * 1000` |
| F2-11 | 熔断期间不发请求（入口查 `cooldownLeftMs`） | ✅证实 | 126-133 `const left = cooldownLeftMs(); if (left > 0) return {reason:'cooldown'}` |
| F2-12 | 成功一次即 `clearCooldown()`（169） | ✅证实 | 169 `clearCooldown();` |
| F2-13 | 节流 10s（33, 88-92） | ✅证实 | 33 `MIN_GAP_MS = 10000`；88-92 throttle |
| F2-14 | 请求超时 12s（34, 97） | ✅证实 | 34 `REQUEST_TIMEOUT_MS = 12000`；97 setTimeout abort |
| F2-15 | 状态落盘 `STATE_FILE = .remote-plan-state.json`，必须写可写位置（40-48, 63-71）；读时去 BOM（56） | ✅证实 | 45-48 路径选择；63-71 writeState；56 `.replace(/^\uFEFF/, '')` |
| F2-16 | OAuth = Authorization Code + `zcode://oauth/callback`，靠 Electron 导航事件拦截（**无本地 server**） | ✅证实 | 38 `DESKTOP_REDIRECT = 'zcode://oauth/callback'`；2027-2048 四个导航事件调 `tryCapture`；全仓检索 `createServer\|.listen(\|http.Server\|express` **0 命中**（仅 `protocol.handle('zcode')` 2845） |
| F2-17 | 凭据 **AES-256-GCM `enc:v1`**，密钥来自 `ZCODE_CREDENTIAL_SECRET` 或机器特征 | ✅证实 | 243 `PREFIX='enc:v1:'`；244 `ALGO='aes-256-gcm'`；246 `CREDENTIAL_SECRET_ENV='ZCODE_CREDENTIAL_SECRET'`；248-253 fallback `zcode-credential-fallback:<platform>:<homedir>:<username>`；255-257 `sha256(secret)`；273-277 encrypt（nonce 12B，base64url） |
| F2-18 | 登录驱动提交判据 = 输入框有效值 + 验证码变过 + 4.5s 节流，**明确不用"按钮可点"当信号** | ✅证实 | 356 `s.hasForm && s.phoneOk && s.codeOk`（315-316 手机≥11、验证码≥4）；360 `changed = s.code !== this.lastCode`；361 `s.btnOk && changed && Date.now() - this.lastClickAt > this.clickGapMs`；274 `clickGapMs = 4500`；268-271 注释「不能拿按钮可点当信号」 |
| F2-19 | Z.ai 通道关闭有 `startOAuthFlow` 硬闸门（1946-1953） | ✅证实 | 1946 `if (providerId === 'zai') { return { ok:false, deprecated:true, ... } }`，不建窗口 |
| F2-20 | 代码中**无 `tier` 字段** | ✅证实 | 全仓（排除 node_modules）`\btier\b` 大小写不敏感 **0 命中** |
| F2-21 | 无 Max/Pro/Lite 分级 | ✅证实 | 全仓 `\b(Max\|Pro\|Lite)\b` **0 命中**（"Start" 仅出现在套餐名字符串 `ZCode Start Plan`，非档位字段） |
| F2-22 | **无内置接码平台 / 临时邮箱 / 邮箱抓取** | ⚠️部分证实 | 实质成立（无任何接码/收信逻辑，手机号/验证码/邮箱均由 `askText` 向人索要 87-101/346/609）。但草稿称"项目源码 **0 命中**"**不准确**：`renderer/style.css:123` 有 `/* ===== 自动接码开关 ===== */`（**死 CSS 注释**，`index.html` 无任何 `class="switch"` 元素，退出码 1），README:118 明确否认 |
| F2-23 | 日志结构 `{providerId, ts, payload:{code,msg,data:{plans,balances,server_time}}}`；字段名清单 | ✅证实 | plan.js:92-94 `obj.payload.data`；213 `rec.obj.providerId`；276 `d.server_time`；222-228/232-240 entitlement/plan 字段；186-197 bucket 字段 |
| F2-24 | 为什么优先日志：3012 签名不可复刻（balance.js:6-14）；缺头 400/3001（plan.js:8-10, remote-plan.js:10-15）；联网缺 balances（main.js:2531-2537） | ✅证实 | 三处原文均在 |
| F2-25 | 串号防护 `expectUserPlanId`（plan.js:97-107,132-141；main.js:2557-2568） | ✅证实 | 132-141 匹配逻辑；2557 `userPlanIdOfAccount`；2562-2568 退旧快照 |
| F2-26 | 主界面额度 `plans:quota`（2527-2578）；**不退回"最后一条"全局日志**（2560-2561） | ✅证实 | 2549-2555 无账号直接返回；2558 `plan.fetchPlans(..., logsOf(accId))`；2560-2561 注释 |
| F2-27 | `normalize` 输出字段（207-284）；桶级兜底 `max(0,total-used)`，绝不拿总量当可用（186-197） | ✅证实 | 190-196 `hasAvail ? Number(b.available_units) : Math.max(0, total - used)`；account-query.js:131-133 同 |
| F2-28 | `toIso` 秒→本地 ISO，不能透传（173-180, 237-240） | ✅证实 | 174-180；237-238 注释「直接透传…会当毫秒，1970 年附近」 |
| F2-29 | pending = `effective_at` 在未来（200-205, 228）；expired 按读取时刻重算（263-264）；计划级 pending（262）；排序（267-269） | ✅证实 | 逐条对应 |
| F2-30 | 平台时间按 UTC+8 解析（balance.js:73-88） | ✅证实 | 81-84 注释+`+08:00` 拼接 |
| F2-31 | OAuth 两条 provider 参数（PROVIDERS oauth.js:40-62）：bigmodel `bigmodel.cn/login`/appId `zcode`/`redirect-appId`；zai `chat.z.ai/api/oauth/authorize`/`client_P8X5CMWmlaRO9gyO-KSqtg`/`oauth2` | ✅证实 | 44/45/49；54/55/60 逐条对应 |
| F2-32 | 两者 tokenUrl 同为 `zcode.z.ai/api/v1/oauth/token`，redirectUri 同为 `zcode://oauth/callback`（38） | ✅证实 | 47/57；38/46/56 |
| F2-33 | 桥接页 `zcode.z.ai/app/oauth/login?redirect=…&app_version=…`（64-95）；`mode='direct'` 直接用 `zcode://`（74） | ✅证实 | 66-71 desktopRedirectUri；74 `if (mode === 'direct') return DESKTOP_REDIRECT` |
| F2-34 | `parseCallbackUrl` 取 `authCode ?? code` + `state`（99-114） | ✅证实 | 110 `url.searchParams.get('authCode') \|\| url.searchParams.get('code')` |
| F2-35 | token 交换 POST，body `{provider, code, redirect_uri, state}`，多级回退取 access_token（148-186） | ✅证实 | 155-160 body；132-140 resolveAccessToken（`bag.access_token`→`bag.accessToken`→`data.access_token`→`data.accessToken`） |
| F2-36 | `completeOAuth` 用 `oauth.encrypt` 加密各字段写 `credentials.json`（**main.js:1571-1584**） | ⚠️部分证实 | 加密写盘属实（1571-1584），但该段落在 **`applyOAuthToken`**（1530 定义）内，**`completeOAuth` 在 main.js:2138**。函数名张冠李戴（completeOAuth 只是调用方） |
| F2-37 | `zcodejwttoken` 只在有新值时覆盖（1583-1584） | ✅证实 | 1583 注释；1584 `if (tokenSet.zcodeJwt) cred.zcodejwttoken = oauth.encrypt(...)` |
| F2-38 | Z.ai 额外用 access_token 换业务 token `POST api.z.ai/api/auth/z/login`（oauth.js:222-239） | ✅证实 | 59 businessLoginUrl；223-231 |
| F2-39 | `enc:v1` 与客户端是否同一套：算法/前缀/键名同，但密钥派生是面板回退式，注释"与官方一致"属逆向结论（oauth.js:28-31） | ✅证实 | 28-31 注释「凭据落盘键名（与官方一致）」；密钥派生 248-257 确为回退式，草稿已诚实标注【一手+半推断】 |
| F2-40 | `account-query.js` 只查券+日额度+plans 名（2-24,140-147）；先校验后取值（10-14,93-99） | ✅证实 | 97-99 先判 3001/3012/非0；104-121 券；123-138 日额度 |
| F2-41 | 券判定 = 名字不匹配 `/ZCode Start Plan/i`（107） | ✅证实 | 107 `if (/ZCode Start Plan/i.test(p.name \|\| '')) continue;` |
| F2-42 | 日额度 = `period` 为 `daily` 或空，按 `show_name` 归并（123-138） | ✅证实 | 126-127 `if (period && period !== 'daily') continue;`；134-137 累加 |
| F2-43 | `readLocalAccount` 从 config 递归找 JWT + meta 取 device_mid（151-167） | ✅证实 | 154-164 递归；165 meta |
| F2-44 | CLI 每次请求后 sleep 2600ms（184,195） | ✅证实 | 184/195 `setTimeout(x, 2600)` |
| F2-45 | 登录驱动"人机混合"分工（262-272,346）；自动点登录/注册（284-286,364-367）；`confirmAuthorize`（181-212） | ✅证实 | 逐条对应 |
| F2-46 | `PAGE_FILL` 原生 setter + input/change/blur（218-242）；协议真实 click（154-170,288-297） | ✅证实 | 233-240；161 `target.click()`；294 `cb.click()` |
| F2-47 | Z.ai `formSettleMs = 12000` 宽限期 + `nextAttemptAt` +12s 退避（398-402,618-619,636,644-656） | ✅证实 | 398 默认 12000；644 `settleAt = Date.now() + this.formSettleMs`；636/653 `+ 12000` |
| F2-48 | `probeChallenge` 纯观察不点击（475-521） | ✅证实 | 484-491 仅 `querySelector` 识别，无 click |
| F2-49 | 激活链接人工粘贴（671-680）；必须 `win.loadURL` 原窗口（19-21,134-144,693-695） | ✅证实 | 674-679 askText；138 `loadURL`；693 `this.navigate(this.verifyLink)` |
| F2-50 | `readShownEmails`（561-567,744-768） | ✅证实 | 561-567 定义；746/756 调用 |
| F2-51 | `balance.js` 60s 内存缓存（28,144-146） | ✅证实 | 28 `CACHE_TTL_MS = 60 * 1000`；144-146 |
| F2-52 | `balance.js` token 来源：解密 `oauth:<provider>:access_token`，按 `oauth:active_provider` 选（50-62） | ✅证实 | 54-60 逐条对应 |
| F2-53 | 代理分流常量与实现（main.js:1872, 1874-1904）；实测注释 1861-1870 | ✅证实 | 1872；1884-1904；1861-1868 注释（F1 写 1861-1868，F2 写 1861-1870，同一段注释边界口径不一，均覆盖） |
| F2-54 | `did-fail-load` 不静默，写说明页 + manual 提示（2050-2063, 1909-1925） | ✅证实 | 2052-2063；1910-1925 showLoadErrorPage |
| F2-55 | 「双重闸门」关闭 Z.ai | ⚠️部分证实 | 代码闸门 1946-1953 ✅；第二道"UI 按钮标注已失效"确存在（`renderer/index.html:67` `btn--dead` + `<span class="btn__badge">已失效</span>`），但草稿未给该处行号，只给了代码闸门一处 |

---

## 2. 发现的问题清单（原表述 → 实际 → 建议修正）

### P1 ❌【严重·断言范围 > 检索范围 + 内部矛盾】F1 §③「主 `~/.zcode` 唯一写入是 setting.json」
- **原表述**：F1 §③「就代码而言：面板对 `LEGACY_ZCODE_V2` 的**唯一写入**是 `setting.json`（`main.js:73 → 975-984`）……检索范围：`main.js` 全文对 `LEGACY_ZCODE_ROOT|LEGACY_ZCODE_V2` 的匹配共 8 处（26, 27, 73, 129, 142, 755, 756, 1212），**逐一核对无其它写点**。」
- **实际是什么**：`main.js:1212` 把 `LEGACY_ZCODE_V2` 作为 **sharedV2** 传给 `sessionIndex.syncIn`。`syncIn` 第①步（`session-index.js:107-109`）会调 `syncOut`，`syncOut`（88-95）→ `copyDbFamily(dataV2, sharedV2, ...)`（92）→ `copyFile(s, d)`（68），把**上一个账号的 `tasks-index.sqlite`（及 `-wal`）写进 `~/.zcode/v2/`**。故主 `~/.zcode/v2/` 的写点**至少有两个**：`setting.json` 与 `tasks-index.sqlite`。
- **自相矛盾证据**：F1 §⑥ 自己写了「`syncOut`（88-95）：只在标记文件存在时回写……避免把空库推回共享」，即已承认写共享库；但 §③ 又说唯一写入是 setting.json。
- **建议修正为**：「面板对主 `~/.zcode/v2/` 的写入有两处：① `setting.json`（73→975-984）；② `tasks-index.sqlite`/`-wal` 的会话索引回写（1212 → `session-index.js:88-95`，仅在上次已播种时触发）。其余对 `LEGACY_*` 的引用为只读（755-756 迁移读取）或建联接（129、142）。」

### P2 ⚠️【严重·绝对化】F1「切换零文件复制」
- **原表述**：§①.2「切换账号**不复制**、不覆写任何凭据文件」；§⑨「切换 = 改标记 + 杀进程 + 换数据根重启，**零文件复制**」。
- **实际是什么**：凭据确实零复制；但切换路径 `switchAccount → launchZCode → sessionIndex.syncIn` 会 `copyFileSync` `tasks-index.sqlite` 与 `-wal`（`session-index.js:68/72`）。代码注释 `main.js:1268`「一个字节的文件复制都不需要」语境仅指凭据（1267-1272 通篇讲凭据）。
- **建议修正为**：「切换**不复制/不覆写任何凭据**；但会通过 `session-index.syncIn` 搬运会话索引 `tasks-index.sqlite(+wal)`（`main.js:1212`）。」

### P3 ⚠️【中·负向断言检索范围不足】F2 §⑥「项目源码 0 命中」接码关键词
- **原表述**：「检索 `login-driver.js / oauth.js / main.js / import-account.js / settings.js` 全文关键词……**项目源码 0 命中**（仅 `node_modules/` 里……无关命中）」。
- **实际是什么**：结论实质正确，但"0 命中"不成立——全仓（排除 node_modules）在 **`renderer/style.css:123`** 命中 `/* ===== 自动接码开关 ===== */`。这是一段**死 CSS 注释**（`renderer/index.html` 无任何 `class="switch"` 元素，grep 退出码 1），不构成"内置接码能力"，但确实是被漏掉的一处命中。
- **建议修正为**：「全仓源码除 `renderer/style.css:123` 一句遗留注释『自动接码开关』（对应元素已不存在，属死代码）外，无任何接码/收信实现；`README.md:118` 亦明确否认。手机号/验证码/邮箱均由 `askText` 向使用者索要。」

### P4 ⚠️【中·数字不可复算】F1「六账号共用 session」
- **原表述**：§①.4「ZCode 内置浏览器的 `session/` **六账号共用**（`main.js:221-230`）【一手】」。
- **实际是什么**：`main.js:224` 注释原文确为「六个账号共用这一份」——**引用准确**。但"六"是该注释**作者本机的账号数**；参考项目 `accounts/` 目录**为空（0 个账号）**，仓库内无法复算该数字。
- **建议修正为**：保留引用但标注口径，如「session 跨账号共用（`main.js:224` 作者注释记为『六个账号共用』；本仓库 `accounts/` 为空，N 值不可复算）」。

### P5 ⚠️【中·函数名张冠李戴】F2 §⑤ / §① 「`completeOAuth` 加密写盘（main.js:1571-1584）」
- **原表述**：「`completeOAuth` 用 `oauth.encrypt` 加密各字段写 `credentials.json`（`main.js:1571-1584`）」。
- **实际是什么**：1571-1584 位于 **`applyOAuthToken`**（定义于 `main.js:1530`）；`completeOAuth` 定义在 `main.js:2138`，是调用方。
- **建议修正为**：「`applyOAuthToken`（`main.js:1571-1584`，由 `completeOAuth` 2138 调用）加密各字段写 `credentials.json`。」

### P6 ⚠️【轻·表述过度】F1 §④「前端 `doSwitch` 仅 toast」
- **实际是什么**：`renderer/app.js:429-440` 还有 `setLoading`、`api.switchTo`、`await refresh()`。草稿本意（前端无回滚处理）成立。
- **建议修正为**：「`doSwitch` 只做 `switchTo` + toast + 刷新，**无任何回滚分支**。」

### P7 ⚠️【轻·条件漏写】F1 §⑤「把 jwt 写进 `options.apiKey` 与 `nodeKey`」
- **实际是什么**：`import-account.js:77` `if (v && v.nodeKey === true) v.nodeKey = jwt;` —— **仅当 `nodeKey` 恒为布尔 `true`** 才写入。
- **建议修正为**：「jwt 写入 `options.apiKey`；若 `nodeKey === true` 则同时写入 `nodeKey`。」

### P8 ⚠️【轻·引用不全】F2 §①「双重闸门」只给一处引用
- **实际是什么**：第二道（UI）闸门在 `renderer/index.html:67`（`btn--dead` + `已失效` 徽标），草稿未给行号。
- **建议修正为**：补 `renderer/index.html:67`。

### P9 ⚠️【轻·单位口径】"4MB"
- **实际是什么**：`plan.js:37` `4 * 1024 * 1024` = 4 **MiB**（4,194,304 B），非 4 MB。
- **建议修正为**：「4 MiB」。

### P10 ⚠️【轻·口径不一】同一段实测注释行范围
- F1 §⑧ 写 `main.js:1861-1868`，F2 §⑧ 写 `main.js:1861-1870`。同一段注释（1858-1871），建议统一为 `1858-1871`。

---

## 3. 遗漏与矛盾检查

### 3.1 内部矛盾（同一份草稿内）
| 矛盾 | 位置 | 说明 |
|---|---|---|
| **主目录写点** | F1 §③ vs F1 §⑥ | §③ 称唯一写入是 setting.json；§⑥ 称 `syncOut` 会回写共享库（=主 `~/.zcode/v2`）。**同一份草稿前后冲突**（见 P1） |
| **切换是否复制文件** | F1 §①.2/§⑨ vs F1 §④/§⑥ | §①.2/§⑨ 称"零文件复制"；§④ 步骤 7 又列出 `syncIn`（会复制）。口径未打通（见 P2） |
| **实测注释行号** | F1 §⑧ vs F2 §⑧ | 1861-1868 vs 1861-1870（见 P10） |

### 3.2 遗漏（草稿未覆盖但属决策相关的点）
1. **`fsp.cp` 在 `deleteAccount` 跨卷回退**（`main.js:1359`）：删除账号时若跨卷 `renameSync` 失败，会整目录复制。草稿 §⑨ 未提；不影响 F1 主线，但属"文件复制"清单的缺口。
2. **`applyOAuthToken`/`bindOAuthToCurrent` 会写 `.rollback` 备份**（1546-1547、1750）：F1 §②.1 表格提到 `.rollback/`（1748-1750、671），但**未提 `applyOAuthToken` 那条 1546-1547 也写同一目录**——即 `.rollback` 有两个写点，非只有绑定路径。
3. **`account-query.js` 的 `period` 取自 balance 桶**（126），而 `plan.js` 的 `period` 取自 entitlement（193）——两文件对同一字段的口径不同，草稿 §② 未点出。
4. **`recentLogFiles` 只读"第一个含 MARKER 的文件"**（`plan.js:110-117`），非"最近 3 天全部扫描"；草稿表述"只扫最近 3 天"易被读成"3 天都解析"。
5. **`plan.fetchPlans` 的 `providerMismatch`**（`plan.js:216`）是另一道串号防线，草稿 §② 只讲了 `expectUserPlanId`。

### 3.3 子 agent prompt 错误假设的核验结论
- 主 agent 派 F2 时假设「读日志的是 `balance.js`」。**F2 子 agent 的纠正（读日志的是 `plan.js`）经独立核验，本身完全正确**：
  - `plan.js:6` 明写数据源为客户端日志；`plan.js:35` 默认 `~/.zcode/v2/logs`；`plan.js:36` MARKER；`plan.js:293-294` 读 `logDir`。
  - `balance.js:6-14` 明写走 `open.bigmodel.cn` biz 网关，且**主动声明不把 zcode billing 当数据源**（因 3012/签名）。
  - `README.md:222` 把 `balance.js` 标为"客户端日志里的额度读取"确系文档笔误（223 行才是 plan.js）。
- 结论：**纠正成立，且草稿对 README 笔误的指认也成立**。

---

## 4. 统计数字重算表

| 数字 | 草稿期望值 | 我重算值 | 口径 / 命令 | 结论 |
|---|---|---|---|---|
| `main.js` 行数 | 2853 | **2853** | `wc -l main.js` | ✅ |
| `session-index.js` 行数 | （未直接给，F1 引用到 140） | **140** | `wc -l` | ✅ |
| `import-account.js` 行数 | （引用到 148） | **148** | `wc -l` | ✅ |
| `settings.js` 行数 | （引用到 432） | **432** | `wc -l` | ✅ |
| `login-driver.js` 行数 | （引用到 786/789） | **789** | `wc -l` | ✅ |
| `oauth.js` 行数 | （引用到 278） | **296** | `wc -l` | ✅ |
| `balance.js` 行数 | （引用到 160） | **210** | `wc -l` | ✅ |
| `plan.js` 行数 | （引用到 320） | **322** | `wc -l` | ✅ |
| `remote-plan.js` 行数 | （引用到 171） | **238** | `wc -l` | ✅ |
| `account-query.js` 行数 | （引用到 195） | **198** | `wc -l` | ✅ |
| 「六账号共用 session」的 6 | 6 | **不可复算** | `ls accounts/` → 空目录（0 项）；6 来自 `main.js:224` 注释 | ⚠️ 引用注释 |
| 熔断时长 | 30 分钟 | **30 分钟** | `remote-plan.js:38 COOLDOWN_MS = 30 * 60 * 1000` | ✅ |
| 联网节流 | 10s | **10s** | `remote-plan.js:33 MIN_GAP_MS = 10000` | ✅ |
| 登录点击节流 | 4.5s | **4500ms** | `login-driver.js:274 clickGapMs = 4500` | ✅ |
| 日志尾读取 | 4MB | **4 MiB = 4,194,304 B** | `plan.js:37 TAIL_BYTES = 4*1024*1024` | ⚠️ 单位应为 MiB |
| 请求超时 | 12s | **12000ms** | `remote-plan.js:34` | ✅ |
| 日志回看条数 | 80 | **80** | `plan.js:124 guard < 80` | ✅ |
| 日志扫描天数 | 最近 3 天 | **3** | `plan.js:44 i < 3` | ✅ |
| `balance.js` 缓存 | 60s | **60000ms** | `balance.js:28` | ✅ |
| CLI 请求间隔 | 2600ms | **2600ms** | `account-query.js:184,195` | ✅ |
| Z.ai 宽限期 | 12000ms | **12000ms** | `login-driver.js:398` | ✅ |
| CDP 端口 | 9223 | **9223** | `main.js:219` | ✅ |
| 登录页等待 | 45s | **45000ms** | `login-driver.js:341` | ✅ |
| `main.js` 中 `LEGACY_ZCODE_*` 匹配数 | 8 处（26,27,73,129,142,755,756,1212） | **8 处，行号完全一致** | `grep -n` | ✅（但"无其它写点"结论错，见 P1） |
| 全仓 `LEGACY_ZCODE_*` 匹配数 | （未给） | **9 处**（多 `session-index.js:30` 注释） | `grep -rn` | 补充 |
| 共享库/账号库会话条数 | 22 vs 3 | **不可复算** | `session-index.js:12-13` 注释，本仓库无 sqlite | ⚠️ 引用注释 |
| 代理实测 328ms | 328ms | **不可复算** | `main.js:1862` 注释 | ⚠️ 引用注释 |
| `tier` 全仓命中 | 0 | **0** | `grep -i \btier\b`（排除 node_modules） | ✅ |
| `Max\|Pro\|Lite` 全仓命中 | 0 | **0** | `grep`（排除 node_modules） | ✅ |
| 接码关键词全仓命中 | 0（草稿称） | **1**（`renderer/style.css:123` 注释）+ README:118 | `grep -i sms\|接码\|…` | ❌ 草稿的 0 不成立（见 P3） |

---

## 5. 诚实声明（无法核验项及原因）

1. **服务端行为类断言无法核验**：3012 的具体风控阈值、`billing/current` 恒返 405/3012、联网返回缺 `balances` 的触发条件、`chat.z.ai`/`bigmodel.cn` 代理可达性（200/328ms/ERR_CONNECTION_CLOSED）——均为参考项目注释中的**实测记录**，本次仅做**只读**核验、未发起任何真实网络请求，故只能确认"代码/注释如此写"，无法证实服务端侧事实。草稿亦多处自标【未验证】，态度正确。
2. **`enc:v1` 与官方客户端逐字节一致**：需反编译 ZCode `app.asar` 比对派生函数，本次未做（受只读与范围约束）。草稿已自标【一手+半推断】，核验一致。
3. **"六账号""22 条 vs 3 条""328ms""9 个账号混写"等经验数字**：参考项目 `accounts/` 为空、无运行期 sqlite/日志样本，**仓库内不可复算**，只能确认"注释原文如此"。
4. **`ZCODE_DESKTOP_*` 三变量能否真正覆盖 ZCode 的 `app.setPath`**：依赖 ZCode 客户端二进制行为，本次未实测，草稿已自标【推断】。
5. **L3 检索的边界**：我排除了 `node_modules/`、`dist/`、`build/`；`dist/` 内含打包后的同一份源码副本，未纳入（若纳入会重复计数）。`dist/mac-arm64/.../*.plist` 等命中均为打包产物，与源码结论无关。
6. **未修改参考项目**：全程只读；核验用命令均为 `grep`/`wc`/`ls`/`sed -n`（只读），未在参考项目内写任何文件。核验产物仅写入本报告路径。

---

## 6. 汇总

- **核验断言条数**：**92 条**（F1 37 条 + F2 55 条，含决策级与次级）。
- **结论分布**：✅证实 **86** 条（F1 34 + F2 52）；⚠️部分证实 **6** 条（F1-10、F1-34、F1-37、F2-22、F2-36、F2-55）；❌证伪 **2** 条（F1-11「零文件复制」绝对化、F1-16「主目录唯一写入 setting.json」）；❓无法判定 **0** 条（另有若干经验数字标为"引用注释、不可复算"）。
- **最严重 3 条**：
  1. **P1（❌）** F1 §③「主 `~/.zcode` 唯一写入是 setting.json / 无其它写点」——漏掉 `session-index.syncOut` 对 `~/.zcode/v2/tasks-index.sqlite` 的回写，且与 §⑥ 自相矛盾。属"断言范围 > 检索范围"。
  2. **P2（❌/⚠️）** F1「切换零文件复制」——切换链路实际会复制 `tasks-index.sqlite(+wal)`；"零复制"仅对凭据成立。
  3. **P3（⚠️）** F2「接码关键词项目源码 0 命中」——`renderer/style.css:123` 实际命中「自动接码开关」（死代码），结论实质成立但"0 命中"不成立。
- **L2 重点结论**：F1/F2 的**所有决策级机制判断方向正确**（隔离支点、设备码双通道与永不复算、setting.json 例外、会话索引拷贝补偿、plan.js 才是日志通道、3012/熔断/节流、OAuth 无本地 server、AES-256-GCM、提交判据、无 tier/无接码平台）；**未发现"行号对但内容被根本曲解"的严重情形**，问题集中在**绝对化表述、检索范围不足、函数名张冠李戴、数字不可复算**四类。
- **子 agent 纠正核验**：F2 对主 agent「balance.js 读日志」假设的纠正**本身正确**（见 §3.3）。
