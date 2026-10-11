# ix 验收 · 第六轮（2026-09-28 · S-17/S-18 差分复验）

判定：**不通过**（严重 1 / 中 3 / 轻 3；门另有 3 条双绿逃逸）。
测量：全部真进程/真函数。沙箱 `/tmp/mg-ix6`（`MG_CONFIG`/`WORKBUDDY_CONFIG_DIR`/`MGW_OPS_LOCK_DIR`/账号根全在 /tmp，
网关自启于 8397，真实写入 wb/wb2/wb3）；仓库 `git status --porcelain -- data` 空、`ls data/usage|grep -c ops` → **0**。
镜像 `/tmp/mg-ix6/mut` 上做变异，**未改仓库任何文件**。
（干扰项排除：仓库根 `.workbuddy-ai/memory/`（09-22~26）只有 memory 无 models.json，非本仓 CLI 产物。）

## 1. S-18 徽章四态 —— **不通过（1 严重）**
node 直调真函数 8 payload 逐字：
- active → `<span class="badge b-ok" title="可承接请求">可用</span>`
- cooldown>0 → `<span class="badge b-cool" title="1766s 后自动回池，无需处理">冷却中</span>`
- cooldown=0 → `title="已到期，下次选路即回池"`；同列「冷却剩余」印 `—` → **ix §4 中-2 两口径已消**
- invalid → `<span class="badge b-err" title="上游已拒绝（Key 或模型名失效）—— 需在「模型资源」页更换，不会自愈">已判死</span>`
- disabled → `<span class="badge b-muted" title="资源开关已关闭 —— 打开开关即恢复">停用</span>`
- 未知 `quota_window_flipped` → `b-muted` 原样英文（**不染红，符合主张**）
- 缺 status → 徽章文字为 **`undefined`**（JS 词漏到界面，轻）
- **严重**：真实 401 走的是 `disable()` 不是 `invalidate()`（`core/scheduler.py:400-405` AUTH→disable；
  `:406-411` NOT_FOUND→invalidate）。聚合层 `resources.py:134` 注释自证「`disabled`（401 判死 / 手动停用）」，
  而徽章说「资源开关已关闭 —— **打开开关即恢复**」。
  用户会以为：这列自己被我关了，拨回来就好。真相：Key 被上游拒绝，开关本就是开的，拨开关只会再 401 一次。
  **最高频病根被指派了一个必然无效的动作**，而"换 Key"这句唯一正确的处置挂在只有"模型名失效"才走到的 `invalid` 上。
- **中（过度承诺）**：cooldown 分支不看成因即承诺「无需处理」——RETRYABLE/网络类/配置类失败同样进 cooldown
  （`resources.py:331`），"自动回池" ≠ "回池后能用"。
- **中（同屏两口径）**：一资源两条目（A=invalid、B=cooldown）时聚合 `status=invalid`（severity，`:465`）
  而 `cooldown_remaining_ms=max(条目)`（`:479`）→ 一行同印「已判死·不会自愈」+「1766s」倒计时（node 实测可渲染）。
  结论：**只凭「状态」+「冷却剩余」两列不足以决定下一步**，仍必须读第三列「最近错误」（AUTH 是否写 last_error 未验证）。

## 2. S-17 CLI 文案 —— 通过（含 2 中）
页名交叉核对（读到的列真在该页）：`RESOURCE_PAGE`=「模型资源」页 → `pages/resources.js:255-263` 确有「Key 及关联账号」✓；
`OVERVIEW_HEALTH_PAGE`=「总览」页资源健康表 → `dashboard.js` 确有「最近错误」列 ✓。
四场景逐字（`mgw setup workbuddy --yes`，真写盘）：
- (a) 无监听：`可服务模型判定依据：本地配置 · 原因：网关未运行（连接被拒） —— 感知不到资源失效等运行态`
  `将写入：models.json（7 条系统模型；⚠ 未取到运行态，清单可能含已不可服务的模型（原因见上方判定依据行））`
  **终行** `✓ 已写入 /tmp/mg-ix6/wb/models.json（7 条，新增 7）`，**rc=0**
- (b) 活网关+对密钥：`…（7 个模型可服务，含运行态）` / `将写入：models.json（7 条系统模型）`（**无 ⚠，正确**）/ `✓ 已写入 …（新增 0）`+备份行
- (c) 活网关+**错密钥**：`原因：网关在运行但拒绝了接入密钥（401：密钥已停用或删除） —— 感知不到资源失效等运行态`，⚠ 在，终行仍 `✓ 已写入（7 条，新增 7）` rc=0
- (d) 挂起监听：`原因：网关无响应（超时） —— …`，⚠ 在，终行 `✓ 已写入`
判：caveat 逐字存在、措辞不自证清白，五屏内可读到 → 主张成立。但 (i) **它不是最后一行**，屏面终行永远是
「✓ 已写入 …（N 条，新增 N）」+ rc=0；只看结尾的用户读成"全成功、文件可信"。(ii) (c) **归因错指**：
真相是"我配置的密钥/端口和这个实例不一致"，文案断言"网关侧密钥已停用或删除"（G2 仍未做）→ 用户会去
「API 接入」页重建密钥，而不是核对配置。(iii) 三处降级都**没给下一步动作**（"原因见上方判定依据行"只回指原因）。
- 轻：CLI「凭据失效需换 Key」与徽章「凭据失效=停用·打开开关即恢复」就同一现象给两套口径（互相拆台）。

## 3. S-17 jsonl 可分辨性 —— **通过**
沙箱真 CLI 熔断轮（rc=3，屏面 `⚠ ZCode 风控熔断（30min，全局），至 03:47 —— 本轮未对上游发起任何领取`），
文件单看（`/tmp/mg-ix6/usage/ops-results-20260928.jsonl`）：
`"inactive": ["acct-a","acct-b"], "failed": [], "inactive_reasons": {"acct-a": "ZCode 全局风控熔断中（剩余约 30 分钟），本轮跳过", …}`
→ 无滚屏也能判定"这一轮被全局风控拦住、没发起领取"。轻：文件说「本轮跳过」，弱于屏面「未对上游发起任何领取」。

## 4. 门（基线 62/62 ✓；--mutation 50/50 ✓）与 8 条新逃逸
被抓：E1 冷却列印徽章文字→B4 红；E2 `default:` 返空串→C7 红；E5 仅第二次点击才 POST ack→I6 红；
E8 把 disabled 标签写成「已判死」→ 门红 + `test_v2_servable` 红。
**逃逸成功（node 门仍 62/62 绿）**：
- **ESCAPE-A（E4）** 把降级 caveat 从「将写入」行挪到其**前一行**独立打印 → node 绿 **且 `test_v2_setup.py` 14 passed**
  ⇒ S-17"末行追加 caveat"这条主张**实际无判据钉住位置**。
- **ESCAPE-B（E7）** 徽章用 `Math.floor`、列用 `Math.ceil` → 同一行两个剩余时间（差 1s），node 绿 ⇒ 门不核对数值口径。
- **ESCAPE-C（E6）** 徽章 title 页名改「计费」页（不存在的页）→ node 绿 **且 `test_v2_cli.py::test_route_copy_names_the_page_that_actually_hosts_the_column` + test_v2_setup 35 passed**
  ⇒ 页名"单一事实源"只覆盖后端两份，`dashboard.js` 里那一份是**第四副本**，双向核对判据不认它。
- E3 熔断块删状态文件路径 → node 绿（`test_claim_under_global_breaker_exits_3` 红）：后端有护栏，属前端门射程外，**不计缺陷**。
计数：8 尝试 / 4 条令 node 门保持绿 / 其中 **3 条同时骗过 pytest**（A、B、C）。

## 必改四项（下轮门槛）
1. `statusBadge`：401 路径（现落 `disabled`）不得说「打开开关即恢复」；按来源区分「手动停用」与「上游拒绝凭据·需换 Key」。
2. 页名交叉核对判据扩到**前端文案**（dashboard.js/resources.js 里点到的页名+列名，双向），消掉第四副本。
3. 降级提醒钉在**终行**（`✓ 已写入` 之后另起 ⚠ 一行，含"下一步：核对 --config 的 token/端口是否与在跑的实例一致"），
   并考虑非 0 出口或 `--strict`；401 归因改写为"配置与实例不一致"（G2 收口）。
4. 门补 3 条：caveat 位置断言（须在"✓ 已写入"之后）；同行徽章/冷却列数值口径一致；invalid 行不得带倒计时（或后端聚合把 `cooldown_remaining_ms` 在非 cooldown 时置 0）。

## 未验证
真实浏览器/CDP（本机 Chrome 挂起，结论全部来自 node 直调真函数，不代表布局与 hover 可见性）；
AUTH→`disable()` 是否同时写 `state.last_error`（决定「最近错误」能否补救「停用」）；
degraded 写入条数 > 运行态可服务条数的**真实分歧样本**（沙箱 7 模型运行态全可服务，⚠ 只是"可能"）；
clean 轮 jsonl 对照行（由 `ops/base.py:59` 写入条件推断，未实跑）；`scripts/ui_verify_v2_visible.py --mutation` 12/12 未复跑；
E5/E7 类逃逸在 `--mutation` 50 条之外的实际覆盖率（只看"这条改动能不能让门变红"）。
