# ix 验收 · 第五轮（2026-09-28 · slice C 交互设计）

判定：**有条件通过**（严重 0 / 中 8 / 轻 5；前端门另有 2 条逃逸）。
测量方式：全部为**真进程/真函数**实测（CLI 沙箱 `/tmp/mg-r5-ix`：`MG_CONFIG`/`MGW_ZCODE_ACCOUNTS`/
`MGW_OPS_LOCK_DIR` 全在 /tmp，`plan_base_url` 指向本机假上游 8399，未配代理；网关自启于 8397；
`data/usage | grep -c ops` → 0，`git status --porcelain -- data` 空）。前端门变异在 `/tmp/mg-ix-mut` 镜像上做。

## 1. CLI 熔断退出（`cli_zcode.py:217-296`）——通过（含 2 条中）
- (a) 开局熔断，逐字：
  `⚠ ZCode 风控熔断（30min，全局），至 02:49 —— 本轮未对上游发起任何领取`
  `    状态文件：/tmp/mg-r5-ix/circuit.json（到点自动恢复；删除该文件可立即放开后续领取，已冷却的资源按其剩余时间自行回池）`
  `– 跳过 1 个（被熔断拦住）` / `    本轮结果已落盘：…jsonl` / **rc=3**。
  判：文案与事实一致（假上游日志 0 请求）、未印"全部正常"、归因正确；**建议动作实测有效**
  （`rm circuit.json` 后同一沙箱下一轮不再被拦）。
- (b) 轮中建立（第三进程在假上游 preview 睡眠 6s 窗口内写熔断）：
  `⚠ 本轮命中风控，已建立全局熔断：…，至 02:50` + `✗ 失败 1 个：` → **rc=1**。
  分支走对、rc 故事自洽；但"本轮命中风控"这句**未被真实路径验证**（我的注入不来自本轮 3012）。
- (c) clean：`– 跳过 1 个（无需动作 1）` / `全部正常，无需处理` → rc=0。一致。
- (d) 失败：`✗ 失败 1 个：` + `acct-a  未配置住宅代理，验证码求解不可用 —— 请配置 gateway.zcode.proxy（或环境变量 MGW_ZCODE_PROXY）；也可加 --manual …` → rc=1。
  三条建议**全部真实存在**（`schemas.py:58/70` / `cli_zcode` `--manual`），落盘路径真实。
- **中**：(a) 与 (c) 写进 `ops-results-*.jsonl` 的行**完全同形**（实测均为
  `{"inactive":["acct-a"],"failed":[]…}`）——屏面刚把"被熔断拦住"与"无需动作"说成两件事，
  用户被指路的文件里却分不出来。
- **中**：(b) 文案承诺"停止领取**与转发选中**"，而 `sync_circuit_to_runtime` 仅 `main.py:97` 启动时调用一次；
  熔断若由非 CLI/cron 路径建立（手改文件），在跑的网关不 bench 任何资源 → 转发照旧，文案对此不打折。

## 2. 退出码文档——通过（2 条轻）
`mgw zcode claim --help` 实测打印 0/1/2/3 全文 + "3 与 `mgw setup` 的 3（写盘失败）同码不同义"；
README.md:113-117 / README.zh-CN.md:110-113 同步。警告**属实**（setup 的 3 确为写盘失败，`cli_setup.py:195`）。
轻：`import` 的 **4**（设备 ID 冲突，`cli_zcode.py:212`）在 help 与 README 退出码表里都没有；
`mgw setup --help` 实测**无退出码段**（1=取消 / 2=配置类 / 3=写盘失败只在源码里）。

## 3. `mgw setup` 成因分桶与判定依据——通过（2 条中）
四场景实测（`--dry-run`，`WORKBUDDY_CONFIG_DIR=/tmp/mg-r5-ix/wb`）判定依据行各不相同、无黑话：
`本地配置 · 原因：网关未运行（连接被拒）` / `运行中网关的 /v1/models（1 个模型可服务，含运行态）` /
`本地配置 · 原因：网关在运行但拒绝了接入密钥（401：密钥已停用或删除）` / `本地配置 · 原因：网关无响应（超时）`。
无 `http-418` 类码值泄漏。隐藏行实测：
`· 1 个未配置任何资源映射（m-nomap）—— 到「资源池设置」页为该模型添加资源映射`
`· 1 个映射的资源均未启用（m-offres）—— 到「模型资源」页打开对应资源的启用开关`
- **中**：第三桶 `runtime_dead` 的指路"到「模型资源」页看该资源的「最近错误」"**页面无此字段**
  （`grep -c 最近错误 pages/resources.js` → **0**；该列在「总览」`dashboard.js:104`）。
  用户照 CLI 指示找不到东西；且我未能让真实网关产出该桶（bench 走 `resource_ids_of_account` 后
  模型仍出现在 `/v1/models`，见未验证）。
- **中**：(a)(c)(d) 三种降级下按**纯配置**判定，运行态已死的模型照样写进 `models.json` 且 **rc=0**；
  只有 basis 一行小字提示"感知不到资源失效等运行态"，无 `--strict`/非 0 出口。密钥填错的用户会得到一份"成功"的文件。
- 轻：401 文案只覆盖"密钥停用/删除"，不覆盖"端口指到别的实例"（账本 G2 仍未做）。

## 4. 资源健康卡语义（`statusBadge` + 后端聚合）——不通过（4 条中）
node 真函数渲染 6 payload（实测输出）：active→`b-ok "active"`；cooldown>0→`b-cool title="剩余 1765s"`
+ 列 `1765s` + 原因在 td；cooldown=0→`b-cool title="剩余 0s"` 而「冷却剩余」列显示 `—`；
invalid→`b-err "invalid"`（无 title）；disabled→`b-muted "停用" title="资源开关已关闭"`；
未知状态→`b-err` 原样英文 `credential_changed`。
- **中**：四态里三态是**英文枚举词**直出，"invalid" 不表达"判死 / 需换 Key / 不自愈"，且无处置提示；
  停用/判死/暂时冷却只能靠颜色与英文词猜。
- **中**：cooldown=0 一行内两个口径（徽章 title "剩余 0s" vs 专用列 "—"）。
- **中**：`default` 分支把任何后端新增状态渲染成**红色 + 原样英文** → 第一眼读成"判死"。
- **中**：`last_error` 到期即清（实测 bench 2s：`t=0 cooldown … 'ZCode 额度耗尽（演示：可自愈）'` →
  `t=+4s active None`）。用户事后**无任何**"刚才为什么不可用"的痕迹；冷却期只有几十分钟，
  `ops-results-*.jsonl` 只记运营领取不含 §17 资源 bench，唯一可能去处是「请求日志」页（未验证其是否含资源级事件）。
  屏上四态对用户只剩"现在能不能用"，不含"发生过什么"。

## 5. 前端门盲区（`verify_v2_frontend.mjs`）——有逃逸
仓库文件基线实测：`实测 57 项，失败 0 项`；`--mutation` → `可红 45/45；每条断言都有对应变异`。
镜像 `/tmp/mg-ix-mut`（5 个被检文件）新做 7 条：
- **ESCAPE-1**：`dashboard.js:14` `${configWarnings(data.warnings)}` → 加
  `.filter((w) => w.kind === "uncovered")` ⇒ **57/57 仍绿**。真实页面三类告警永不显示（A 段全部直接调用函数）。
- **ESCAPE-2**：`main.js` 红点块 `const dot = …` 后插一行 `if (dot) POST("/admin/api/ops/ack");` ⇒
  **57/57 仍绿**。红点每 5s 自动确认 = 失败永久无人看见；I6 只测"点击会 POST"，不测"**只有**点击才 POST"。
- 被抓：M2 冷却列值改 `—` ⇒ B4 红；M4 互换 `dot.hidden` 两方向 ⇒ I1/I2/I6 红；
  M5 仅互换两个表头 ⇒ B2 红；M6 「最近错误」列改印 `String(r.status)` ⇒ B3/B5 红。
- 结构性：M7 想把页名改错，`dashboard.js` 里"「资源池设置」页"命中数 **0** —— 指路文案来自**后端**
  （`main.py:281/309/325`）与 `cli_setup.py:69` 两份独立副本，前端门只测原样透传 ⇒ 任一处改页名都不会红。
- 门看不见什么：整页从不装配（调用点参数/挂载与否全盲）；只判字符串存在性，不判列-头语义与数值一致
  （B6 只数单元格个数）；射程只有 5 个文件，logs/settings/api-access 三页与后端文案在外；依赖本机 node（G3）。

## 必改四项（下轮门槛）
1. `cli_setup.py:71` 第三桶指路改「总览」页（或让「模型资源」页真的带「最近错误」）。
2. `statusBadge` 四态给人话 + 处置提示（含"invalid 不会自愈，需换 Key"），`default` 不得染红。
3. 熔断轮/clean 轮在 jsonl 里可分辨；(b) 文案对"转发"承诺按 sync 时点打折。
4. 补两条门判据：banner 调用点参数被改 ⇒ 红；红点在非点击路径 POST ⇒ 红。

## 未验证
真实 3012 中途熔断（需住宅代理 + Playwright + 真站点，沙箱不可达）——故 (b) 的"本轮命中风控"归因未经真实路径实测；
Chrome/CDP 与 hover title 可见性（本沙箱 Chrome 挂起，全部结论来自 node 直调真函数，不代表浏览器布局）；
跨午夜 `至 HH:MM` 的真实显示（`quota.py:431` 只格式化 `%H:%M`，无日期；改系统时钟才可复现）；
`runtime_dead` 桶在真实网关下的产出与 `/v1/models` 对冷却资源仍下发 `m-ok` 的口径差异；
「请求日志」页能否作为 last_error 的事后替代出口。
