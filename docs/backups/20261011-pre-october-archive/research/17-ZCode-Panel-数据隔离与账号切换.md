# F1 · ZCode-Panel 数据隔离与账号切换机制

> 调研对象：`/Users/w/Desktop/zcode相关管理软件/ZCode-Panel/`（**全程只读**）
> 证据分级：`【一手】`直接读到的代码 / `【推断】`由代码推导未经运行证实 / `【未验证】`未证实
> 所有行号均以 Read 工具逐行核对过。

## 修订记录（据独立核验 `_verify/verify-F.md` 逐条修正）

| 原表述 | 修正后 | 类型 |
|---|---|---|
| §③「面板对主 `~/.zcode/v2/` 的**唯一写入**是 `setting.json`」 | **漏了第二处**：`tasks-index.sqlite`/`-wal` 的会话索引回写（`main.js:1212` → `session-index.js:88-95` → `:92` `copyDbFamily`，仅在上次已播种时触发）。且**与原稿 §⑥ 自述自相矛盾**（§⑥ 已承认 `syncOut` 会回写共享库） | **断言范围 > 检索范围 + 内部矛盾（严重）** |
| §①.2 / §⑨「切换**零文件复制**」 | **凭据零复制成立**；但切换链路会经 `sessionIndex.syncIn` 拷贝 `tasks-index.sqlite(+wal)`（`session-index.js:68/72`）。`main.js:1268`「一个字节的文件复制都不需要」的语境**仅指凭据** | 绝对化表述（严重） |
| §①.4「`session/` **六账号**共用」 | 引用准确（`main.js:224` 注释原文确为「六个账号共用这一份」），但「六」是**注释作者本机的账号数**；本仓库 `accounts/` 为空，**N 不可复算** → 已标注口径 | 数字不可复算 |
| §④「前端 `doSwitch` **仅 toast**」 | 实为 `setLoading` + `api.switchTo` + `toast` + `refresh()`；原稿本意（**无回滚分支**）成立，已改为准确表述 | 表述过度 |
| §⑤「jwt 写进 `options.apiKey` **与** `nodeKey`」 | 实为**仅当 `nodeKey === true`** 才写入 `nodeKey`（`import-account.js:77`） | 条件漏写 |

---

## ① 结论先行

1. 隔离的**唯一支点是环境变量 `ZCODE_DATA_BASE_DIR`**（`main.js:1204`）：把它指到 `<账号>/data`，ZCode 自己在其下建 `.zcode/v2/`，凭据/配置/日志/遥测/provider_config 全落进去。【一手】
2. 切换账号**不复制、不覆写任何凭据文件**，只做「写 `.current` + 杀掉旧进程 + 用新数据根重启」（`main.js:1276-1309`）。这是与 zcode-switch「覆写 `~/.zcode/v2/credentials.json`」路线的根本分歧。【一手】
   ⚠️ **限定**：「零复制」**只对凭据成立** —— 切换链路会经 `sessionIndex.syncIn` 搬运**会话索引** `tasks-index.sqlite(+wal)`（`main.js:1212` → `session-index.js:68/72`）。
3. 设备码是**每账号一个持久 UUID**，两处同时喂给客户端：`meta.json.device_mid` → `--device-id=<uuid>` 命令行参数 + `<账号>/data/.zcode/v2/telemetry-state.json` 的 `deviceMid`（`main.js:1125-1164, 1195-1197`）。生成一次后永不重算。【一手】
4. 隔离**不是全覆盖**：`setting.json` 仍读写主 `~/.zcode/v2/`（`main.js:66-73`）；`cli/`、`workspace/`、`plugin-workspace/`、`home/.zcode` 被**有意反向联回**主目录（`main.js:87, 128-130, 142`）；ZCode 内置浏览器的 `session/` 跨账号共用（`main.js:221-230`，作者注释记为「六个账号共用」，**该 N 值是本机账号数、本仓库 `accounts/` 为空故不可复算**）。【一手】
5. 会话索引 `tasks-index.sqlite` 因落在 `v2/` 被一并隔离，靠 `session-index.js` 在**切换边界做文件拷贝**补偿，而非符号链接（`session-index.js:5-25`）。【一手】

---

## ② 隔离机制全解

### 2.1 目录布局（`<accountsDir>/<账号名>/`）

| 子路径 | 承载 | 由谁指定 | 行号 |
|---|---|---|---|
| `data/` | ZCode 数据根；其下 `.zcode/v2/` 存 `credentials.json` / `config.json` / `provider_config.json` / `coding-plan-cache.json` / `telemetry-state.json` / `logs/` / `certs/` | `ZCODE_DATA_BASE_DIR` | `main.js:56-63, 1204` |
| `userdata/` | Chromium userData（含跨账号不变的持久 `.updaterId`） | `ZCODE_DESKTOP_USER_DATA_DIR` | `main.js:1229, 1235` |
| `session/` | cookies / localStorage | `ZCODE_DESKTOP_SESSION_DATA_DIR` | `main.js:1230, 1236` |
| `home/` | agent 的 shell HOME；`setting.json` 落点也由它推导 | `ZCODE_DESKTOP_HOME_DIR` | `main.js:1231, 1237, 134-136` |
| `meta.json` | 注册时间 / 设备码 / 切换计数 | 面板自写 | `main.js:792, 1136` |
| `config.json` | 顶层副本，与现成账号布局兼容 | 面板自写 | `import-account.js:18, 129` |
| `plan-snapshot.json` | 套餐快照 | 面板自写 | `main.js:311, 493, 648` |
| `.rollback/` | 绑定时留的 `credentials.json` 备份（点开头，账号扫描跳过） | 面板自写 | `main.js:1748-1750, 671` |

`data/.zcode/cli|workspace|plugin-workspace` 是**目录联接（junction）**，指回 `~/.zcode/` 下同名目录（`main.js:87, 128-130`）。`home/.zcode` 同样联回 `LEGACY_ZCODE_ROOT`（`main.js:142`）。

### 2.2 启动客户端时完整设置的环境变量 / 参数（`main.js:1191-1237`）

| 名称 | 值 | 作用 | 行号 |
|---|---|---|---|
| `ZCODE_DATA_BASE_DIR` | `<账号>/data` | 核心：重定向凭据/配置/日志/遥测/provider_config | 1204 |
| `ZCODE_DESKTOP_USER_DATA_DIR` | `<账号>/userdata` | 重定向 Chromium userData | 1235 |
| `ZCODE_DESKTOP_SESSION_DATA_DIR` | `<账号>/session` | 重定向 cookies/localStorage | 1236 |
| `ZCODE_DESKTOP_HOME_DIR` | `<账号>/home` | 隔离 shell HOME；也决定 `getSettingsFile()` 位置 | 1237 |
| `--device-id=<uuid>`（CLI 参数） | 该账号 `meta.json.device_mid` | 喂 `__ZCODE_DEVICE_ID__` 通道 | 1196 |
| `--remote-debugging-port=9223`（CLI 参数） | 常量 `ZCODE_CDP_PORT` | 让面板接管客户端内置浏览器做授权 | 1191, 219 |

`env` 以 `{...process.env}` 为基（`main.js:1192`），即**在继承环境上追加**，不清空。

### 2.3 每账号 `--device-id` 的生成

- **生成**：`accountDeviceId(id)` 读 `meta.json`，`device_mid` 缺失或非字符串时 `crypto.randomUUID()` 并落盘（`main.js:1135-1145`）。另两处同口径生成：捕获账号 `main.js:812`、新建 OAuth 账号 `main.js:1693`，均写作 `(old && old.device_mid) || crypto.randomUUID()`。
- **格式**：标准 UUID（v4 形态），`import-account.js:28` 的校验正则为 `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`（大小写不敏感）。
- **存哪**：`<账号>/meta.json` 的 `device_mid`（`main.js:1136, 1141`）。
- **会不会变**：**不会**。只在字段缺失时才生成；已有值一律沿用（`main.js:1138, 812, 1693`）。代码注释明确「生成一次后永久复用」（`main.js:1131`），且强调「换了设备码等于换了台机器，服务端看就是一次异常的设备迁移」（`main.js:810-811`）。
- **喂给客户端的两条通道**（`main.js:1128-1130`）：
  - `X-Device-Mid` 请求头 ← 客户端读 `<账号>/data/.zcode/v2/telemetry-state.json` 的 `deviceMid`，由 `syncDeviceMidToZCode()` 在每次启动前对齐（`main.js:1149-1164`，值相同则跳过写入 1155）。
  - `__ZCODE_DEVICE_ID__` ← 读命令行 `--device-id=`（`main.js:1196`）。
- 【推断】服务端按 device_mid 精确分组而非统计推断，是面板注释的判断（`main.js:1132-1133`），未经服务端侧验证。

### 2.4 `meta.json` 字段全集

`registered_at` / `registered_at_source` / `registered_at_raw` / `captured_at` / `last_used_at` / `switch_count` / `switches_today` / `last_switch_date` / `last_action` / `via` / `phone` / `email` / `device_mid` / `note`。
来源三处：导入 `import-account.js:135-141`；捕获 `main.js:801-813`；新账号 `main.js:1681-1694`。切换时由 `bumpSwitchMeta()` 增量更新 `last_used_at` / `switch_count` / `switches_today` / `last_switch_date` / `last_action`（`main.js:1377-1392`）。`switches_today` 用本地日期归零（`main.js:1371-1373, 1388`），注释说明不能用 `toISOString()`（UTC 会让日界落在早 8 点，`main.js:1369-1370`）。

---

## ③ 不受重定向的例外（隔离边界）

| 例外项 | 位置 | 代码依据 |
|---|---|---|
| **`setting.json`** | 固定写主 `~/.zcode/v2/setting.json` | `zcodeSettingFile()` 硬编码 `LEGACY_ZCODE_V2`（`main.js:73`）；`setZcodeProxy()` 写它（`main.js:975-984`）；注释给出实测：只写账号目录时日志仍 `mode=direct`，写主目录才变 `fixed_servers`（`main.js:66-73, 970-973`） |
| ZCode **内置浏览器** session | `~/Library/Application Support/ZCode/session/Partitions/zcode-embedded-browser` | `main.js:221-230`；注释「面板传的 `--user-data-dir` 对 ZCode 无效……浏览器会话与账号目录无关，六个账号共用这一份」；面板只读用于诊断、不写（`main.js:226`）。⚠️ 「六个」是**注释作者本机的账号数**，本仓库 `accounts/` 为空，**N 不可复算** |
| `cli/` `workspace/` `plugin-workspace/` | 反向联回 `~/.zcode/` | 有意共享，否则切号后项目列表空白（`main.js:76-87, 122-130`） |
| `home/.zcode` | 反向联回 `~/.zcode/` | 否则 v3.14 起 `setting.json` 落到账号私有 home，与面板写的主目录对不上（`main.js:132-142`） |
| 面板自己的 OAuth 分区 | `<APP_DIR>/Partitions/zcode-oauth-<provider>` | `main.js:234-235, 884-886`；全局共用，故每次授权前清空（`main.js:1031-1038, 1955-1966`） |

**主 `~/.zcode` 是否真的零读写？** 就代码而言：面板对主 `~/.zcode/v2/` 的写入有**两处**：

| # | 写入项 | 路径 | 触发条件 |
|---|---|---|---|
| ① | `setting.json` | `main.js:73 → 975-984` | `setZcodeProxy()` 被调用时 |
| ② | **`tasks-index.sqlite` / `-wal`**（会话索引回写） | `main.js:1212` → `session-index.js:88-95` → `:92` `copyDbFamily(dataV2, sharedV2, …)` → `:68` `copyFile` | **仅在上次已播种时**（标记文件 `.session-index-seeded` 存在）才触发 |

> ⚠️ **本条曾写错并已修正**：原稿断言「唯一写入是 setting.json」，**漏了第 ② 项**，且与原稿 §⑥ 自述（"`syncOut` 只在标记文件存在时回写"）**自相矛盾**。核验时由独立 agent 抓出。

其余对 `LEGACY_*` 的引用只有：读旧凭据做一次性迁移（`main.js:755-775`，方向是主目录 → 账号，**单向读**）、建 junction 目标（`main.js:129, 142`）、以及上表 ② 的共享库路径（`main.js:1212`）。

**防御性代码有两处**：① `launchZCode()` 在 `accountId` 为空时直接 `reject`，注释写明「不做没有账号就用默认目录兜底」（`main.js:1173-1179`）；② `curPaths()` 在无当前账号时返回 `null`，注释写明「绝不能退回全局 `~/.zcode`」（`main.js:194-200`）。

检索范围：`main.js` 全文对 `LEGACY_ZCODE_ROOT|LEGACY_ZCODE_V2` 的匹配共 8 处（26, 27, 73, 129, 142, 755, 756, 1212）；**其中 1212 是写点（经 session-index 间接写），其余为只读或建联接**。

---

## ④ 切换账号完整流程（`switchAccount`, `main.js:1276-1309`）

1. 校验账号目录存在，否则 `{ok:false}`（1277-1278）。
2. 校验 `credentialsOf(id)` 存在，否则拒绝并提示「先切到它登录一次」（1279-1284）。
3. `prevId = readCurrentId()`（1286，读 `accounts/.current`，`main.js:170-181`）。
4. `await killZCode()`（1288）→ `await wait(800)`（1289）。杀进程口径：Win `taskkill /IM ZCode.exe /F`（1106-1112）；mac `pkill -x ZCode`，注释强调必须 `-x` 精确匹配，否则会连带杀掉 `ZCode Helper` / `ZCode Panel`（1114-1122）。
5. `writeCurrentId(id)`（1291）——**先改标记再启动**。
6. `bumpSwitchMeta(dir, 'switch')`（1292 → 1377-1392）。
7. `launchZCode(id)`（1298），内部按顺序追加额外动作：
   - 取/生成 device_mid → `args.push(--device-id)` + 写 `telemetry-state.json`（1195-1197）；
   - `sessionIndex.syncIn(<账号>/data/.zcode/v2, LEGACY_ZCODE_V2, accountId)`（1211-1216）；
   - `linkSharedZcodeDirs(accountId)`（1220）；
   - `mkdir` 三个目录并注入三个 `ZCODE_DESKTOP_*`（1229-1237）；
   - `spawn(exe, args, {detached:true, stdio:'ignore', env})`，`unref()`，500ms 无 `error` 即视为成功（1244-1260）。
8. 返回 `{ok:true, prevId, noRollbackTarget: !prevId, launchError}`（1302-1308）。

**失败与回滚**：启动失败**不把整次切换判为失败**（1294-1301）——标记已改、凭据各在各家，只回传 `launchError`。`switchAccount` 内**没有任何回滚 prevId 的分支**；`prevId` 仅回传给前端。
代码注释给出理由（`main.js:1264-1275`）：「一个字节的文件复制都不需要……老架构要『把快照复制成全局 live』，既多了一层覆盖写，也是账号库一分家就互相认不出的根源。这里把它彻底去掉了。」
旁证：`writeLiveBackToSnapshot()` 已退化为空实现，返回 `{ok:true, changed:false, skipped:'datadir-architecture'}`（`main.js:1317-1319`）；`rollback()` 语义被改成「按当前账号重启客户端」（`main.js:1438-1478`），旧 `.rollback` 快照只提示已不适用（1449-1457）；前端 `doSwitch` 只做 `setLoading` + `api.switchTo` + `toast` + `refresh()`，**无任何回滚分支**（`renderer/app.js:429-440`）。

---

## ⑤ 账号导入（`import-account.js`）

- **入口**：IPC `accounts:import`（`main.js:2270-2292`）。主进程只负责从现成账号里挑一份含 `builtin:` provider 的 config 当模板（`main.js:2273-2278`）。
- **输入来源**：对象或 JSON 文本（剪贴板 / `.json` 文件，`import-account.js:35-39`）；允许外包一层 `account` / `data` / `payload`（42-44）；字段别名：name|id|accountName、jwt|jwtToken|zcodejwttoken|token|apiKey、device_mid|deviceMid|mid|deviceId、note|desc|description（53-56）。
- **校验（白名单，逐字段严格）**：账号名 `^[A-Za-z0-9_-]{1,32}$`（27, 58）；jwt `^eyJ…三段点分`（29, 59）；device_mid 必须 UUID（28, 60）。任一不合法即返回 `{ok:false, error}`。
- **去重键 = 账号名（目录名）**：`dir = accountsDir/<name>`，`fs.existsSync(dir)` 即判「已存在」，默认拒绝，仅 `replace:true` 才覆盖（113-119）。**没有按 `uid` / `device_mid` 的去重**。
- **目录穿越双保险**：名字白名单已限死，另加 `path.dirname(dir) !== path.resolve(accountsDir)` 拦截（115）。
- **覆盖行为**：只有目录里已存在 `data/.zcode/v2/config.json` 或顶层 `config.json` 时才 `rmSync(dir, {recursive:true})`（117-119）。
- **落盘产物**（122-141）：`v2/config.json`、顶层 `config.json`（兼容）、`v2/credentials.json`（`zcodejwttoken` + `oauth:active_provider` 均经 `oauth.encrypt`）、`v2/telemetry-state.json`（写入传入的 `deviceMid`）、`meta.json`（`via:'import'`，`registered_at_source:'import'`，`device_mid` 来自 payload）。
- **config 构造**（`buildConfig`, 70-95）：只保留 `builtin:` 开头的 provider，第三方 provider 直接 `delete`；把 jwt 写进 `options.apiKey`，**若 `nodeKey === true` 则同时写入 `nodeKey`**（`import-account.js:76-77`）；再用 `CRED_RE` 递归 scrub 其它凭据形态（79-85）；一个 builtin 都没有时兜底造 `builtin:bigmodel-start-plan`（88-93）。
- ⚠ **device_mid 唯一性缺口**：导入只校验 UUID **格式**，不比对其它账号的 `meta.json.device_mid`。
  检索范围：`*.js` 全文匹配 `device_mid|deviceMid|device[-_]?id|ZCODE_DEVICE`，命中 `import-account.js`、`main.js`、`account-query.js`、`remote-plan.js`；逐一核对，**无任何跨账号比较逻辑**。若上游凭据复用了同一 mid，面板不会拦截。

---

## ⑥ 会话索引同步（`session-index.js`）

- **为什么需要**：`tasks-index.sqlite`（主键 `(workspace_key, task_id)`）正好在 `v2/` 里，数据根隔离把它也隔开了 → 切号后历史会话「不见了」（`session-index.js:5-13`，实测共享库 22 条 vs 账号库 3 条）。
- **为什么不整共享 `v2`**：`v2` 里还有 per-account 的 credentials / provider_config / telemetry / logs（`session-index.js:15-16`）。
- **为什么不用符号链接**：SQLite 打开 WAL 库时按「打开者的路径」拼 `<db>-wal` / `<db>-shm`，关闭/checkpoint 时删掉重建，链接会被换成真文件 → 主库共享但各账号 WAL 里未 checkpoint 的事务互相看不见（`session-index.js:18-21`）。
- **搬运实现**：`SYNC_FILES = ['tasks-index.sqlite', 'tasks-index.sqlite-wal']`（38）；只拷 main + wal，**不拷 shm**（25, 133）。
- **`syncIn(账号v2, 共享v2, accountId)`**（103-138）：
  1. 先对**上一次播种过的账号**做回写 `syncOut`（107-109）——所以调用点只需一处；
  2. 清早期版本留下的符号链接（113-116）；
  3. 安全阀：账号侧存在**未播种过的真库**时先改名留档 `*.pre-seed-<ISO时间>` 再覆盖（124-128）；
  4. `copyDbFamily(共享 → 账号)`（129）；
  5. 删陈旧 shm，写播种标记 `.session-index-seeded`（133-134）。
- **`copyDbFamily` 的陈旧 WAL 陷阱**（54-57, 61-81）：源端无 `-wal`（事务已 checkpoint）时，必须把目标端 `-wal` / `-shm` 一并删掉，否则 SQLite 会把陈旧 wal 重放上去、把刚拷过去的主库盖回去。
- **`syncOut`**（88-95）：只在标记文件存在时回写，回写后删标记（93）——避免把空库推回共享。
- **调用点唯一**：`main.js:1211-1216`，在 `spawn` 之前（此时旧客户端已退出）。

**边界（重要）**
- 全仓检索 `before-quit|will-quit|syncOut|app.on`：`main.js` 仅有 `app.on('second-instance')`（2836）与 `app.on('window-all-closed')`（2850），**无退出钩子**；`app:quit` handler 只调 `killZCode()`（`main.js:2824-2827`）。`syncOut` 的唯一调用方是下一次 `syncIn`（`session-index.js:107-108`）。
- 【推断】由此推得：若面板在账号 A 活跃时退出且未再切换，A 本轮新建的会话不会回写共享库；下次再 `syncIn(A)` 时标记仍在 → 走 `copyDbFamily(共享→账号)` 直接覆盖 A 的库，**本轮新会话可能丢失**。需实测确认。
- 【一手】`copyDbFamily` 失败只往 `notes` 里记字符串、不抛异常（68-69, 73），`syncIn` 也不校验结果，调用方仅 `console.log`（`main.js:1213`）。

---

## ⑦ 客户端自动探测（`settings.js`）

**最终生效顺序**（`currentExe`, 95-105）：设置页指定 > `ZCODE_EXE` 环境变量 > 上次探测结果 `lastDetect` > `commonPaths()` 中第一个通过校验的 > 占位猜测（调用方必须再用 `describeExe()` 判可用性）。

**`detect()` 多源探测**（337-390）：
| 顺序 | 来源 | 行号 |
|---|---|---|
| 1 | `ZCODE_EXE` 环境变量 | 352 |
| 2 | Win：注册表 `zcode://` 协议注册（HKCU + HKLM） | 356-357, 361-362 |
| 2' | mac：LaunchServices `mdfind kMDItemCFBundleIdentifier == "dev.zcode.app"` | 236, 372 |
| 3 | Win：注册表卸载项 `DisplayIcon` / `UninstallString` 反推目录 | 358, 363-368, 303-331 |
| 4 | 正在运行的进程：Win `Get-Process ZCode` 的 Path；mac 从 `ZCode Helper` 的 comm 反推宿主 `.app` | 210-228, 369, 373 |
| 5 | 常见安装路径（Win `%LOCALAPPDATA%\Programs\ZCode` 等；mac `/Applications/ZCode.app` 等） | 244-261, 376 |
| 6 | 安装目录扫一层子目录（应对改名/自定义位置），用存在性过滤掉 `zcode-switch.app` 之类邻居 | 264-294, 377 |

同一条路径被多个来源指向时**合并而非去重丢弃**，`sources` 累加作为更强证据（339-349）；命中取第一个 `ok`（379）。
**`describeExe()` 校验**（140-171）：存在且是文件；Win 必须 `.exe`，mac 必须在 `.app/Contents/MacOS/` 内；basename 含 `zcode`；同包有 `app.asar` → `good`，有 `Resources` → `warn`，都没有 → `warn`。
辅助：`normalizeClientPath()` 在 mac 上把 `ZCode.app` 自动补成 `.../Contents/MacOS/ZCode`（133-138）；`existsRaw()` 临时置 `process.noAsar=true` 绕开 Electron 的 asar 路径补丁（116-126）。

**设置落盘**：`<appDataDir('zcode-panel')>/settings.json`（48-49）。**账号库优先级**（409-414）：设置页指定 > `ZPANEL_ACCOUNTS_DIR`（399）> 打包态 `APP_DIR/accounts`（404）> 源码态 `__dirname/accounts`（405）；打包态必须换到可写位置，因为 `app.asar` 是只读虚拟归档（400-403）。

---

## ⑧ 授权窗口代理分流（`main.js:1858-1904`）

- **绕过名单**：`PROXY_BYPASS_RULES = 'bigmodel.cn;*.bigmodel.cn;*.zhipuai.cn;<local>'`（1872）。
- **分流实现**（`applyOAuthProxyPolicy`, 1884-1904）：
  1. `ses.resolveProxy('https://chat.z.ai/')` 现读系统代理（1887）；
  2. `toProxyRules()` 把 `"PROXY 127.0.0.1:7897"` / `"SOCKS5 ..."` / `"DIRECT"` 归一成 Chromium `proxyRules`（1875-1882）；
  3. 解析不出（系统没配代理）→ 返回 `mode:'untouched'`，不动 Electron 默认行为（1889-1891）；
  4. 否则 `ses.setProxy({mode:'fixed_servers', proxyRules, proxyBypassRules})`（1893-1897）；
  5. `ses.closeAllConnections()` 断开挂在旧策略上的连接（1899）。
- **为什么 `bigmodel.cn` 必须直连**（实测注释 1861-1868）：`bigmodel.cn` 全走代理 → `ERR_CONNECTION_CLOSED`；绕过直连 → HTTP 200（328ms）。`chat.z.ai` 相反，走代理 200、直连不通。ZCode 客户端自己给主会话下发 `mode=direct`，所以它从未暴露此问题；只有**跟随系统代理的面板授权窗口**会中招，表现为「窗口开了但一片空白」。
- **时序要求**：必须在建窗口 / `loadURL` **之前**设好（1968-1970）。
- **窗口分区**：`persist:zcode-oauth-<provider>`（2023），全局共用 → 每次授权前 `clearPanelOAuthSession()`（1959-1966 → 1043-1086），否则 B 账号会绑到 A 的 BigModel 上（1031-1038）。
- **面板自身改 ZCode 代理**走 `setting.json`（975-984）；注释指出环境变量 `ZCODE_HTTP_PROXY` **完全不被读取**（965）。

---

## ⑨ 可复用点清单

| 机制 | 文件:行号 | 我们能不能用 |
|---|---|---|
| 用 `ZCODE_DATA_BASE_DIR` 做账号级数据根 | `main.js:1204` | ✅ 直接照搬，是本方案地基 |
| 三件套 `ZCODE_DESKTOP_{USER_DATA,SESSION_DATA,HOME}_DIR` 隔离 Chromium 侧 | `main.js:1229-1237` | ✅ 照搬；注意客户端用 `app.setPath` 覆盖，命令行 `--user-data-dir` 无效（`main.js:1227-1228`） |
| 每账号持久 UUID 设备码，双通道注入（CLI + telemetry） | `main.js:1135-1164, 1195-1197` | ✅ 直接满足「一账号一设备」硬需求 |
| 已有设备码永不重算 | `main.js:1138, 812, 1693` | ✅ 照搬；注释给出「换码=异常设备迁移」的理由 |
| 切换 = 改标记 + 杀进程 + 换数据根重启，**凭据零文件复制** | `main.js:1276-1309` | ✅ 照搬；比覆写凭据路线少一整类故障。⚠️ 会话索引仍会拷贝（`main.js:1212`） |
| 无账号时拒绝启动（防退回主目录） | `main.js:1173-1179, 194-200` | ✅ 强烈建议照搬，是隔离的兜底闸门 |
| `pkill -x` 精确匹配杀进程 | `main.js:1114-1122` | ✅ 照搬（宽匹配会连自己一起杀） |
| 导入白名单校验 + 默认拒绝覆盖 + 目录穿越双保险 | `import-account.js:27-30, 58-60, 113-119` | ✅ 照搬；建议**补一条 device_mid 跨账号唯一性检查** |
| 导入 config 时剔除第三方 provider、scrub 其它凭据 | `import-account.js:70-95` | ✅ 照搬，防串号 |
| 单实例锁（两实例会互抢 `.current` 与切换） | `main.js:2829-2833` | ✅ 照搬 |
| 会话索引在切换边界拷贝 main+wal、删陈旧 wal/shm | `session-index.js:61-81, 103-138` | ⚠️ 场景相同才用；我们若不共享 workspace 可省 |
| 未播种真库先改名留档再覆盖 | `session-index.js:124-128` | ✅ 通用安全阀，值得移植 |
| 多源自动探测 + 合并证据 + 可用性分级 | `settings.js:337-390, 140-171` | ✅ 照搬（跨机器部署必备） |
| mac 传 `.app` 自动补 `Contents/MacOS/<bin>` | `settings.js:133-138` | ✅ 照搬 |
| 授权窗口按域名分流代理 + 现读系统代理不写死 | `main.js:1872, 1884-1904` | ✅ 照搬（若我们的上游含国内域名） |
| 授权分区全局共用 → 每次授权前清空 | `main.js:1031-1038, 1955-1966` | ✅ 照搬，防绑错账号 |
| `setting.json` 例外：写主目录、跨账号共用 | `main.js:66-73, 975-984` | ⚠️ 需按我们的客户端实测确认是否同样不受重定向 |

---

## ⑩ 未解决项

1. 【未验证】ZCode 除 `telemetry-state.json.deviceMid` 与 `--device-id=` 外是否还有第三处持久化设备码。面板注释（`main.js:1128-1130`）是二手描述，本次未反编译 ZCode 的 `app.asar` 求证。
2. 【推断】面板退出且未切号时 `session-index` 不回写，可能丢本轮新会话（依据：无退出钩子，`syncOut` 仅由下次 `syncIn` 触发）。需实跑验证。
3. 【未验证】`import-account.js` 不校验 `device_mid` 跨账号唯一性（已说明检索范围）。若上游凭据复用同一 mid，面板不会拦——对我们的硬需求是个缺口。
4. 【未验证】mac 探测依赖 bundle id `dev.zcode.app`（`settings.js:236`），不同客户端版本是否一致未证实。
5. 【推断】`ZCODE_DESKTOP_USER_DATA_DIR` 等三个变量能否真正覆盖 ZCode 的 `app.setPath('userData'|'sessionData')`，仅凭面板注释（`main.js:1227-1228`）判断，本机未实测。
6. 【未验证】`setting.json` 不受 `ZCODE_DATA_BASE_DIR` 影响是 ZCode v3.14.x 的实测结论（`main.js:68-70`），换版本可能变化。
