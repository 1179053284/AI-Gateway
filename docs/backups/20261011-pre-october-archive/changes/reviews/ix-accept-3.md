# 交互与视觉实现验收报告（第三轮）· ix-accept-3 · 2026-09-27

> 角色：**资深交互与视觉设计师（B 端工具 / 开发者工具方向）** —— 第三角色，只挑问题，不盖章。
> 基准：`docs/specs/tech-design.md` v2.0 **§21 / §17 / §16.2 / §16.5 / §12.4.1 / §20**；
> `docs/specs/prd.md` v1.15（Q28）；`docs/specs/design-spec.md` §2.1（`:192-193`）；`docs/specs/frontend-spec.md` §7.11/§7.12（`:401,403,429`）；
> 上轮报告 `docs/changes/reviews/ix-accept-2.md`；本轮被审账本 `docs/changes/e2e-records/E2E-20260927-round3-fixes.md`（T1–T11 + §二「更正」）。
> 纪律：除本报告外**零仓库文件修改**；全部临时数据在 `/tmp/ix3-*`；未碰 `~/.zcode` / `~/.workbuddy` / `~/.workbuddy-ai` / 仓库 `data/`；未向任何真实上游发请求；未重启 `:8300`（见 §8）。

---

## 1. 验收结论：**不通过**（阻断项 4 个 · S-1…S-4）

先给应得的认可：**第二轮唯一严重项 S-1（验证码文案对用户配置说谎）已真实关闭** —— 五类失败因现在各有自己的文案与各自的触发条件，逐条实跑见 §4.6；账本 §二「更正」C1–C7 主动撤回不实表述（含把「代码未接线」记成「外部依赖未实测」），这是本轮最值得肯定的一件事。

不通过的理由不是"还有优化空间"，而是**本轮自己声称已修的两项（T9 两路径同判据、T5 熔断原因可见）在真实运行态下不成立**，且新增的两列在实现上把「风控熔断」标成了「停用」——按 mg-11「无证据不得宣称完成」与第二轮同等口径，属阻断：

| # | 阻断项 | 一句话 | 复现 |
|---|---|---|---|
| **S-1** | `mgw setup` 在网关**明明在跑**时打印「网关未运行，无法感知资源失效等运行态」 | 新增的「判定依据」行对**用户当前状态陈述不实**，并静默退回纯配置判定 → T9 修复整体失效 | §4.4 实跑（401 根因 §4.4b） |
| **S-2** | 全局风控熔断在用户侧**完全不可见** | CLI 打「– 跳过 1 个（无资格 1）/ 全部正常，无需处理」exit 0；界面无任何熔断出口；重启后资源显示 `active`、`last_error=None` 而熔断文件还剩 19 分钟 | §3、§4.2 |
| **S-3** | 告警① 指路指到**没有该控件**的页（并与 §21.2 字面文案冲突） | 「到『资源池设置』页…添加资源映射」——该页只有档位/上下移/移除（`models.js:343-361`），页面自己的提示写着「新增映射：在『模型资源』页」（`models.js:297,361`） | §2 表 + §5 W-1 |
| **S-4** | 「状态」列把冷却/失效一律标成**「停用」** | 实跑渲染：同一行 状态=`停用`（title「Key 或所属产品已停用」）而 最近错误=`ZCode 风控熔断（30min，全局）`；`b-cool`/`b-err` 两分支对真实接口数据**不可达** → 新增两列的核心目的（分辨熔断/停用）被同一张表的另一列推翻 | §3.2 渲染原文 |

**其余为有条件项**（中等/轻微清单见 §6），可与下一轮一并处理；但 S-1…S-4 不关闭，「用户看得到发生了什么、知道下一步怎么办」这条项目自设底线在「配置告警」「领取失败」「熔断」三条路径上都不成立。

| 维度 | 结论 |
|---|---|
| §21 出口①（横幅）四类渲染 | ✅ 四类都真渲染（实跑 12/12 + 35/35 复现）；⚠️ 指路 1 错 1 半错、②无去处、四类同权重（L-6 残留） |
| 出口②（运营失败红点/CLI/ack） | ❌ 熔断态被吞（S-2）；toast 文案已改对但 **3s 即逝** 且与 `index.html:109` 的 title 自相矛盾 |
| 出口③（设备 ID 冲突） | ✅ 上轮已逐字符合 §15.1，本轮未回归 |
| 出口④（`mgw setup` 纪律 0） | ⚠️ 路径+来源打印仍在；新增「判定依据」行**说谎**（S-1）；跳过行处方一刀切残留（M-4 未修） |
| §17 熔断可见性（两新列） | ❌ S-2 + S-4；列本身的规范符合性大体达标（§3.3） |
| 前端规范 / 双主题 / 不新建页面 / 不新建轮询 | ✅ 合规（§3.3 实测渲染零硬编码色值；`--cool/--text-faint` 明暗双份 `base.css:19-23,55-59`） |
| 护栏可信度 | ❌ **四条断言可用变异证明「界面坏了仍绿」**（§5 变异记录，含本轮新加的 td/文案断言） |
| 账本诚实性 | ✅ C1–C7 主动更正；⚠️ 「T11② 指路改正」「T5 唯一可见出口」「node 崩溃已能非 0」三条经复核成立/半成立，逐条见 §7 |

---

## 2. 出口① 四类告警 + 熔断文案：逐条核对表

数据源 `Runtime.config_warnings()`（`main.py:231-295`）→ `/admin/api/overview.warnings[]`（`admin.py:168`）→ `configWarnings()`（`dashboard.js:65-73`，复用 `.alert alert-warn`，`base.css:874-896`）→ 启动日志同步打印（`main.py:434-435`，实跑见 §4.5）。

| kind | 说了什么 | 数量 | 点名对象 | 指路的页 | **该页是否真有该控件**（代码核验） | 结论 |
|---|---|---|---|---|---|---|
| `model_without_resource` ① | 「未配置任何资源，已从 /v1/models 与 mgw setup 隐藏（调用将返回 503）」 | ✅ | ✅ 模型名（前 5 + `…`） | 「资源池设置」页「在资源池里添加资源映射」（`main.py:249`） | ❌ **该页无新增映射入口**：池行只有 effort/↑/↓/移除（`models.js:343-359`），空池提示与页内 hint 均指向「模型资源」页（`models.js:297,361`）；映射新增控件在 `resources.js:572 #rv-addmap`。§21.2 契约字面也是「模型资源」页 | **S-3 阻断** |
| `resource_without_model` ② | 「N 个资源未被任何系统模型引用」 | ✅ | ✅ 资源名 | **完全没指路**（`main.py:260-261`） | — | 🟡 只说现象不说下一步，也没定性「非故障」→ §6 M-6 |
| `model_unservable` ③ | 「资源映射全部不可用（已停用或凭据失效），已从 /v1/models 与 mgw setup 隐藏」 | ✅ | ✅ 模型名；❌ **不说是哪个资源、两种原因不区分**（registry 里其实有 `status=disabled/invalid` 可分，`resources.py:371-380`） | 「模型资源」页启用 + 「资源池设置」页更换映射（`main.py:275-278`） | ✅ 启停开关确在「模型资源」页（组级 `resources.js:233,326-329` + 逐 Key 开关 `:447`）；⚠️ 后半句「更换映射」该页只能**移除**不能新增 → 半错 | 上轮 M-3 **已修**，残留半句（§5 W-3） |
| `param_shadowed` ④ | 「参数卡推理字段不生效 … 实际生效序 = 请求级 > 资源级默认 > 参数卡（PRD FR-3.16）」 | ✅ | ✅ 模型名 + 参数卡值（`reasoning_effort=max`）+ 资源名与默认值（`资源「资源·在用」默认 low`） | 「资源池设置」页「清掉对应资源的推理默认」（`main.py:290-293`） | ✅ 该页池行有 effort 下拉且含空值项「不注入（厂商默认）」（`models.js:351-353`，写回 `:397 r.reasoning=null`） | 上轮 M-2 **已修**；措辞建议见 §5 W-4（"清掉"→控件字面） |
| 熔断出口（非 warnings） | — | — | — | — | — | **S-2/S-4**：`/admin/api/overview` 与 `/admin/api/status` **都没有熔断状态字段**（`grep circuit model_gateway/api/` → 0 命中）；`last_error` 只在**命中的那一刻**写进内存态，重启即丢（§3.1 实跑） |

补充核验（避免自创）：`param_shadowed` 对 **images 端点**是否会把用户指到一个不存在的控件（`models.js:350` 的 effort 下拉只给 chat 端点渲染）？实跑否——schema 在加载期就把 images 映射的 `reasoning` 判为无效并另发一条 `config.warnings`（`§4.7` 实跑），**该隐患不成立，撤回不报**。

---

## 3. 熔断故事端到端（用户视角）+ 新增两列实测

### 3.1 五个状态的实跑（全部隔离：`MG_CONFIG=/tmp/ix3-cfg/config.yaml`、`MGW_ZCODE_ACCOUNTS=/tmp/ix3-state/accounts`、`MGW_OPS_LOCK_DIR=/tmp/ix3-locks`，端口 14555）

| 状态 | 系统内部 | 用户实际看到 | 判定 |
|---|---|---|---|
| 命中 3012（进程内） | `enter()` 落盘 + `bench_all_zcode()` 回写（`zcode_claim.py:100-122`） | 资源行 `status=cooldown`、`cooldown_remaining_ms≈1795000`、`last_error=ZCode 风控熔断（30min，全局）`；**但「状态」列渲染成「停用」**（§3.2） | 🟡 S-4 |
| **熔断中网关重启** | `circuit.json` 剩 19 分钟仍生效；`ResourceState` **不持久化**（`main.py` 全文无 restore；`grep -n "persist\|state.json" model_gateway/main.py` → 无） | 实跑：`{'rid':'res-live','status':'active','available':True,'cooldown_remaining_ms':0,'last_error':None}` + `warnings` 无熔断项 → **界面一片正常**；且模型转发路径会重新选中被风控的账号（`get_circuit()` 在 `core/scheduler.py`、`core/resources.py` **零消费者**，实跑 grep 仅 `zcode_claim.py:133`） | 🔴 S-2（§17「否则熔断形同虚设」的原始缺陷跨重启复发） |
| **熔断到期在同一会话内** | `cooldown_until` 到时自然恢复（`resources.py:237`） | 总览只在进入页面时渲染一次（`main.js:53`），**倒计时冻在 1795s**，不刷新、不重渲染；`/admin/api/status` 其实每 5s 就带回同一份 `resources` 快照（`admin.py:118`）却只用于红点（`main.js:96-108`） | 🟡 M-5 |
| 资源卡在冷却、原因可见 | `last_error` 有值 | 无任何强制解除出口：`/admin/api/resources/test` 只回报连通性、不触碰状态（`admin.py:268-323` 全文无 `state`）；「模型资源」页的启用开关改了也不清冷却（注册表跨热重载保留）→ 用户只能干等，且「状态=停用」把他指向一个**已经开着**的开关 | 🔴 S-4 的连带后果 |
| **`claim` 全被熔断跳过** | `_circuit_gate` 已生成 `inactive` + 「剩余约 N 分钟」文案（`zcode_claim.py:125-137`） | 实跑原文：`– 跳过 1 个（无资格 1）` / `全部正常，无需处理` / `EXIT=0` —— 生成的原因串**一个字都没打印**（`cli_zcode.py:237-256` 只对 `failed` 打明细），并把熔断归到 §16.2 定义为「无资格/活动结束」的桶里 | 🔴 S-2 |

### 3.2 真实源码函数渲染（`/tmp/ix3-render.mjs`，抽取并执行 `dashboard.js:90-115`，输入 = §3.1 真实 `/admin/api/overview`）

```html
<tr>
  <td class="mono" title="资源·在用 / ix3-payload · 2 个模型映射">资源·在用</td>
  <td><span class="badge b-muted" title="Key 或所属产品已停用">停用</span></td>   ← 🔴 S-4
  <td class="num">0</td>
  <td class="num">0</td>
  <td class="num" style="color:var(--cool)">1795s</td>                             ← 🟡 M-1
  <td class="ellip" style="max-width:280px;" title="ZCode 风控熔断（30min，全局）">ZCode 风控熔断（30min，全局）</td>
</tr>
```

根因：`statusBadge` 第一分支看 `r.available === false`（`dashboard.js:111`），而 `available` 定义就是 `status == "active"`（`resources.py:385-386`，注释「可用 = 开关开启且状态正常」）→ `cooldown / invalid / disabled` **全部**落进「停用」；`:113` 的 `b-cool`（含 §2.1 要求的「悬停显示剩余时间」）与 `:114` 的 `b-err` 对真实数据不可达 = **死 UI**。只有手工 fixture（不带 `available`）才能渲染出 `cooldown`，`verify_v2_frontend.mjs:73-78` 的兜底假行恰好就是这种——所以护栏看不见这个矛盾。

同页自相矛盾还有一处：上方「运行状态」指标卡按 `r.status === "cooldown"` 统计（`dashboard.js:10,16`），会显示「1 资源冷却中」，而同一张表里那一行的状态列写着「停用」——两块 UI 对同一个对象给两个结论。

### 3.3 两列对 design-spec §2.1 / frontend-spec 的符合性

| 检查项 | 结论 | 证据 |
|---|---|---|
| 列集合与顺序（资源名/状态/连续失败 C/在途/冷却剩余/最近错误） | ✅ 顺序一致；标签改「资源」「处理中」（spec 字面「资源名」「在途」）——达意，但账本 §二 C6 引 design-spec:193 时应同步改口径，否则规范与实现两个名字 | `dashboard.js:92-96` vs `design-spec.md:192` |
| 数字列对齐 | ✅ 走 `.num`（本项目 v2.12 用户指示：**列表类左对齐 + tabular-nums**），未私自右对齐 | `base.css:301-304`、渲染 HTML |
| 长错误串省略 | ✅ 机制正确：`.ellip`（`overflow/ellipsis/nowrap`）+ 场景 `max-width` 内联，与既有 `logs.js:170` 同配方；**规范值不一致**：frontend-spec:401 规定「错误摘要 260」，本列用 **280** | `base.css:311`、`frontend-spec.md:401`、`dashboard.js:104` |
| 30 字中文是否撑坏行高 | ✅ 不会（`white-space:nowrap` 强制单行，实测 td 数=18、无换行标签）；⚠️ **反向风险**在资源名列：`td.mono` 无 `ellip/nowrap`（`dashboard.js:99`），6 列后该列更窄，长厂商名会折行 → 行高不齐（本轮起的新暴露面）；**浏览器像素实测未做**（§8） | §3.2 C 组渲染原文 |
| 空态占位符 | ✅ 单格 `—`（含 `title=""` 空提示，hover 无任何反应）；❌ **整表为空时无空态**：`resourceHealthTable([])` 只渲染表头 + 空 `tbody`，违反 §8 交互范式「空结果显示空态文案而非空白」与 logs/stats 的既有做法 | `dashboard.js:106`；对照 `logs.js:121,161`、`stats.js:106`、`frontend-spec.md:429,518` |
| 双主题令牌 | ✅ 渲染产物 **0 个硬编码色值**（正则统计）；`--cool/--text-faint` 明暗双份均已定义 | §3.2 统计行；`base.css:19-23,55-59` |
| 转义安全 | ✅ 600 字符错误 + `<script>` 注入被 `esc` 吞掉，未逃逸 | §3.2 C 组 |
| 仅靠 tooltip 的信息可发现性 | ⚠️ 弱：表头含义（「移出生效集的剩余等待时间」「熔断 / 失败原因（风控熔断与普通冷却的区分）」）**只在 title 里**，无 `cursor:help`/下划线等任何可供性；后者括号半句是写给评审的设计语，不是给用户读的 | `dashboard.js:95-96` |
| 与 §17 判据的因果 | ⚠️ 两列到位但**语义被「状态」列自我推翻**（S-4），且跨重启无数据（S-2）→ §17「用户分得清风控熔断与普通失败冷却」未成立 | §3.1、§3.2 |

---

## 4. CLI / 实跑记录（原样粘贴；均在本机 `/tmp` 隔离环境）

> 4.1 零账号；4.2 熔断中；4.3 产品过滤；4.4 setup；4.5 告警双通道与二次实例；4.6 验证码五类失败文案；4.7 边界确认。

### 4.1 零账号 `claim`
```
$ MGW_ZCODE_ACCOUNTS=/tmp/ix3-state/accounts MGW_OPS_LOCK_DIR=/tmp/ix3-locks MG_CONFIG=/tmp/ix3-cfg/config.yaml \
  .venv/bin/python -m model_gateway.cli zcode claim
无账号参与 —— 尚未接入任何 ZCode 账号。
  先 `mgw zcode login` 或 `mgw zcode import <凭据.json>` 接入账号。
EXIT=2
```

### 4.2 有账号、**全局熔断生效中**（`circuit.json` 手写，`left_minutes()=19`）
```
-- 熔断文件与判定（真实 CooldownManager） --
circuit 文件 = /tmp/ix3-state/circuit.json
熔断生效中？ True 剩余分钟 = 19 原因 = ZCode 风控熔断（30min，全局）

-- 同一时刻界面数据（/admin/api/overview，网关刚重启） --
{'rid': 'res-live', 'status': 'active',  'available': True,  'cooldown_remaining_ms': 0,       'last_error': None}
{'rid': 'res-off',  'status': 'disabled','available': False, 'cooldown_remaining_ms': 0,       'last_error': None}
warnings kinds: ['model_without_resource', 'model_unservable', 'param_shadowed']

-- CLI --
$ ... zcode claim
– 跳过 1 个（无资格 1）
全部正常，无需处理
EXIT=0
```
→ S-2：已算好的「ZCode 全局风控熔断中（剩余约 19 分钟），本轮跳过」一个字没出现；「全部正常」与风控现实相反；界面对熔断零感知。

### 4.3 账号被产品能力声明过滤掉（T11⑧ 的新路径）
```
$ ... zcode claim --account someone-else          # 该名字不在 zcode 账号根里
无账号参与 —— 尚未接入任何 ZCode 账号。
  先 `mgw zcode login` 或 `mgw zcode import <凭据.json>` 接入账号。
EXIT=2

$ ... zcode claim --account ix3-payload --account someone-else
– 跳过 1 个（无资格 1）
– 跳过 1 个（并发占用 / 已停用）
全部正常，无需处理
EXIT=0
```
→ ① 账号**确实已接入**，却被告知"尚未接入"并让他去 login/import（`runner.py:368-380` 生成了准确原因 `someone-else（产品 未知 不在 zcode_claim 的支持范围 zcode 内）`，被 `cli_zcode.py:230-232` 丢弃）；② 第二行把**产品过滤**说成「并发占用 / 已停用」（`cli_zcode.py:246` 固定标签，与 `report.skipped` 真实内容无关）。

### 4.4 `setup workbuddy --dry-run`（T9 的「两路径同判据」）
```
A) 网关确实在跑（14555 实例 /health 正常，配置里 access_tokens 有一条 enabled）
$ ... setup workbuddy --config /tmp/ix3-cfg/config.yaml --dry-run
目标目录：/tmp/ix3-wb
    （来源：环境变量 WORKBUDDY_CONFIG_DIR）
可服务模型判定依据：本地配置（网关未运行，无法感知资源失效等运行态）      ← 🔴 说谎（S-1）
已跳过 2 个无可用资源的模型（disabled-res-model、no-res-model）—— 到「模型资源」页为它们添加映射
将写入：models.json（2 条系统模型）
  [dry-run] 将写入 3 条（新增 2）
EXIT=0

B) 把网关停掉后（同样输出，一字不差 —— 两种状态无法区分）
可服务模型判定依据：本地配置（网关未运行，无法感知资源失效等运行态）
```
```
4.4b 根因（同端口、同进程组内实测）
$ curl -s -w "HTTP=%{http_code}\n" http://127.0.0.1:14555/v1/models
HTTP=401
{"error": {"message": "缺少接入密钥（Authorization: Bearer 或 x-api-key）", "type": "authentication_error", "code": 401}}
$ curl -s -H "Authorization: Bearer mg-ix3ix3ix3" http://127.0.0.1:14555/v1/models | head -c 60
{"object":"list","data":[{"id":"healthy-model","object":"model",...
```
`cli_setup.py:97` 用 `local_admin.admin_get("/v1/models", port=…)`，而 `admin_get` 不带任何鉴权头（`local_admin.py:57-61`），`/v1/*` 在配了密钥时必须 Bearer（`api/auth.py:14,46-56`）→ `HTTPError` 落入 `except OSError` → `None` → 走「网关未运行」分支。`config.example.yaml:17-21` 默认就带 enabled 密钥，因此**这条新文案对绝大多数真实部署都是假话**，且 T9 的运行态对齐从未生效。讽刺处：正确的那个密钥值就在同一个函数上面两行已被取出（`cli_setup.py:92 api_key = tokens[0].value`）。
另一处残留（M-4，本轮未声称修）：`disabled-res-model` 是「有映射但资源停用」，处方「为它们添加映射」仍然错。

### 4.5 出口① 双通道 + 二次实例（`core/paths.py` 改动的 UX 面）
```
$ .venv/bin/python -m model_gateway.main          # cwd=/，MG_CONFIG=/tmp/ix3-cfg/config.yaml
已有实例运行中：后台地址 http://127.0.0.1:14555/（PID 48041、启动时间 2026-09-27T15:36:54+08:00）
EXIT=3
```
✅ **跨目录检测成立**（从 `/` 启动仍能识别在 `/tmp/ix3-cfg` 里的锁 —— 这正是 eng M-4 的 UX 半边）；地址/端口取自锁文件内的真实值（`instance_lock.py:52-59`），不会指向错端口。
⚠️ 可执行性缺最后一句：没有告诉用户「因此无需重复启动，直接打开上述地址；要重启请到『系统设置 → 系统运行控制』」。裸 ISO 串 `2026-09-27T15:36:54+08:00` 也不如「今天 15:36 启动（已运行 2h）」可读。建议见 §5 W-8。
⚠️ `启动网关.command:100-105`：命中「已有实例运行中」时**打印并打开脚本自己算出的 `$ADMIN_URL`**（来自当前配置），而不是日志里那行的真实地址——若用户改了端口尚未重启，会被领到一个打不开的地址，而真实地址明明就在同一行日志里（本轮只读码，未双击实测：脚本会调 AppleScript 关终端标签，不在沙箱里跑）。

```
$ .venv/bin/python scripts/ui_verify_v2_visible.py; echo exit=$?
[配置告警] 1 个系统模型未配置任何资源，已从 /v1/models 与 mgw setup 隐藏（调用将返回 503） —— 到「资源池设置」页选中该模型、在资源池里添加资源映射（empty-model）
[配置告警] 1 个资源未被任何系统模型引用（孤儿资源）
[配置告警] 1 个已启用模型的资源映射全部不可用（已停用或凭据失效），已从 /v1/models 与 mgw setup 隐藏 —— 到「模型资源」页启用对应资源，或到「资源池设置」页更换映射（zombie-model）
[配置告警] 1 个模型的参数卡推理字段不生效：「shadow-model」参数卡 reasoning_effort=max 被资源级默认（资源「资源D」默认 low）覆盖。实际生效序 = 请求级 > 资源级默认 > 参数卡（PRD FR-3.16） —— 要让参数卡生效，请到「资源池设置」页清掉对应资源的推理默认
后端出口实测 12 项，通过 12 项，失败 0 项
实测 35 项，通过 35 项，失败 0 项
exit=0
```
✅ 账本 §四的 **12/12 + 35/35 + exit 0 复现无出入**；四条告警的启动日志双通道真实存在。

### 4.6 验证码五类失败文案（`/tmp/ix3-captcha-probe.py`，真实 `captcha.py` 代码路径，零网络：`fetch_config` 走缓存短路 + 浏览器为注入式假对象）
```
1) 未配置住宅代理（manual=False）
CaptchaUnavailable: 未配置住宅代理，验证码求解不可用 —— 请配置 gateway.zcode.proxy（或环境变量 MGW_ZCODE_PROXY）；也可加 --manual 由人工完成验证码
2) 未配置住宅代理且 --manual（manual=True）
CaptchaUnavailable: 已指定 --manual：请在已登录的 ZCode 客户端里手动完成一次领取后重试；若要自动求解请配置住宅代理 gateway.zcode.proxy
3) 代理已配置，但 Playwright 未安装
CaptchaUnavailable: 验证码求解需要 Playwright 与浏览器内核：`pip install "model-gateway[captcha]" && python -m playwright install chromium`；也可加 --manual 由人工完成验证码
4) 求解超时（30s 上限，SDK 无任何回调）
异常类型 = CaptchaUnavailable
str(e) 长度 = 0  内容 = ''
4b) 超时后第二次调用
CaptchaUnavailable: 验证码求解失败（60s 内不重试）：            ← 冒号后什么都没有
5) 风控拒绝 F001
CaptchaUnavailable: 风控拒绝(F001): 出口 IP / 运行环境被风控识别（云服务器与数据中心 IP 几乎必现）→ 换住宅代理后重试。原始信息: {...}
6) T001 拒绝（文案称「网关会自动刷新重试」）
第 1 次：风控拒绝(T001): 验证参数已过期 → 网关会自动刷新重试。原始信息: {...}
第 2 次：验证码求解失败（60s 内不重试）：风控拒绝(T001): ...      ← 同一函数亲手把"自动重试"挡在 60s 熔断外
7) 装配错误（客户端未接求解器）
CaptchaUnavailable: 验证码求解器未接入（装配错误）—— 请检查网关版本与 `gateway.zcode` 配置；也可加 --manual 由人工完成验证码
8) 生产装配事实：_build_client 恒接求解器 → solver = <CaptchaSolver ...> proxy='' manual=False
```
→ **归因诚实性达标**（第二轮 S-1 的根因）：每条文案的触发条件与它说的话一致（`captcha.py:155-156` ↔ `NO_PROXY_HINT`；`:248-251` ↔ `PLAYWRIGHT_HINT`）。
→ 两例外：**超时没有文案**（`captcha.py:186 raise CaptchaUnavailable(str(e))`，而 `asyncio.wait_for` 抛的 `TimeoutError` 的 `str()` 为空）→ 运营明细、CLI 失败行、JSONL 三处同时变空白（M-1）；**T001/T002 承诺的"自动刷新重试"被同函数的 60s 失败熔断否定**（M-2）。
→ 另一处语义漂移：`--manual` 的 `help` 写「未配置住宅代理时，手动完成验证码」（`cli.py:61-62`），实际它只是**换一条提示**，全程不接受任何人工输入、也不等待（`captcha.py:156`），且该次领取仍以 `failed` 收尾（`zcode_claim.py:191-192`）。

### 4.7 `zcode remove`（破坏性操作，重跑复核呈现纪律）
```
$ ... zcode remove ix3-payload                     # 非交互（管道）且无 --yes
将删除账号『ix3-payload』的本地数据根：
    /tmp/ix3-state/accounts/ix3-payload
    （含该账号的凭据与设备码；不影响网关配置里指向它的资源）
✗ 非交互环境需显式 --yes
EXIT=2                                              # ✅ 先给用户看要删什么，再拒绝；未删除
```
✅ 绝对路径 + 内容说明 + 对网关配置的影响，三要素齐（§21.3 原则 2 成立）。⚠️ 交互回答 `n` 时 `return 0`（`cli_zcode.py:164-166`），而 `setup` 取消 `return 1`（`cli_setup.py:136-138`）——同为"用户主动放弃"两种退出码（上轮 L-5 残留）。
⚠️ 残留（未声称修）：`store.py:144` 仍是「账号『X』已存在（用 --reuse/--regenerate 覆盖）」，照抄 `--reuse` 会 argparse 报错（上轮 §3.4 实跑）；`zcode_claim.py:164` 的「凭据缺失」引导仍把恒失败的 `mgw zcode login`（`oauth.py:81-90`）排在第一顺位，且**产品内 CLI 指引一律 `mgw …` 形态**，本机 `command -v mgw` 为空（`pyproject.toml:31-32` 已声明入口，venv 未重装；README:85 双版给了兜底形式、未被应用内文案引用）。

---

## 5. 文案问题清单（现文 → 建议措辞，逐字可用）

| # | 位置 | 现文案 | 问题 | 建议措辞 |
|---|---|---|---|---|
| **W-1** | `main.py:247-251` ① | `… —— 到「资源池设置」页选中该模型、在资源池里添加资源映射（empty-model）` | 该页**没有**新增映射控件（`models.js:297,361` 反向指路）；§21.2 字面也是「模型资源」页 | `1 个系统模型未配置任何资源：已从 /v1/models 与 mgw setup 隐藏（调用会返回 503）—— 到「模型资源」页选一个已接入的资源，在其「模型映射」区点「添加模型」，把供应商模型映射到该系统模型（empty-model）；保存后本横幅自动消失` |
| **W-2** | `main.py:260-261` ② | `1 个资源未被任何系统模型引用（孤儿资源）` | 没说性质、没说下一步 | `1 个已启用资源未被任何系统模型引用，不会承接任何请求（配置冗余，不是故障）—— 要用它就到「模型资源」页为它添加映射，不用就到该页删除` |
| **W-3** | `main.py:275-278` ③ | `…（已停用或凭据失效）… 到「模型资源」页启用对应资源，或到「资源池设置」页更换映射` | 两因合一让用户自己猜；后半页只能移除不能新增 | 按 registry 状态分叉：`disabled-res-model —— 其映射「资源·停用」已被停用 → 到「模型资源」页打开该资源的启用开关`；`… —— 其映射「资源X」凭据失效（连续鉴权失败）→ 到「模型资源」页更新 Key 并点「检测连通性」`；末句改 `（如需断开失效映射，可在「资源池设置」页点 🗑 移除）` |
| **W-4** | `main.py:290-293` ④ | `… 要让参数卡生效，请到「资源池设置」页清掉对应资源的推理默认` | 「清掉」不是控件上的字 | `… 要让参数卡生效：到「资源池设置」页把该映射行内的推理档位选为「不注入（厂商默认）」；或把参数卡改成与资源级默认同值以免误判` |
| **W-5** | `cli_zcode.py:231-232` | `无账号参与 —— 尚未接入任何 ZCode 账号。先 \`mgw zcode login\` 或 \`mgw zcode import\` …` | 账号存在但被产品/停用过滤时**说谎** | 分流：`if report.skipped_with_reason:` → `无账号参与本轮：` + 逐条 `  – someone-else（产品 未知，不在 zcode_claim 支持范围 zcode 内）`；仅当账号列表本身为空才用现文案 |
| **W-6** | `cli_zcode.py:243-244,246` | `– 跳过 N 个（无资格 N）` / `– 跳过 N 个（并发占用 / 已停用）` | 固定标签与真实原因脱节；熔断被说成"无资格" | 单行合并并按原因分桶：`– 跳过 2 个（风控熔断 1，约剩 19 分钟 / 产品不匹配 1 / 并发占用 0）`；明细行照常缩进打印（数据都已在 `report` 里） |
| **W-7** | `cli_zcode.py:256` | `全部正常，无需处理` | 熔断中打这行是**反向结论** | `本轮未发起领取：ZCode 全局风控熔断中（3012，剩余约 19 分钟），到点自动恢复，无需处理。`（保持非失败语义、exit 0） |
| **W-8** | `main.py:518-520` | `已有实例运行中：后台地址 http://127.0.0.1:8300/（PID 19819、启动时间 2026-09-27T15:36:54+08:00）` | 缺"因此你该做什么"；裸 ISO | `网关已在运行：直接打开 http://127.0.0.1:8300/ 即可（本次启动已取消，未占用端口）。要重启/停止：管理页「系统设置 → 系统运行控制」。（该实例 PID 19819，今天 15:36 启动，已运行 4h32m）` |
| **W-9** | `index.html:109` | `title="运营任务有失败，用 mgw zcode claim 查看详情"` | ① 与本轮刚改的 toast 自相矛盾（重跑 ≠ 查看）；② 只有 `mgw` 形态；③ 它是红点唯一**可停留**的说明，而 toast 只活 3s（`components.js:12`） | `title="运营任务有 N 条失败。逐条原因：data/usage/ops-results-<日期>.jsonl。点此标记已读；重新领取：python -m model_gateway.cli zcode claim"`，并把 toast 缩成 `已确认 N 条运营失败（原因见 ops-results）` 或按 `err` 走 6s |
| **W-10** | `dashboard.js:103,113` | `1795s` | 30 分钟熔断以"一千八百秒"呈现，人要心算；项目已有 `fmtDur`（`api.js:32`）却未 import | 用 `fmtDur(r.cooldown_remaining_ms)` → `29m55s`；徽章 title 同串 |
| **W-11** | `dashboard.js:111` | 状态徽章 `停用`（凡 `available===false`） | 把「冷却中」「凭据失效」「我主动停用」三者压成一个词，且与同行「最近错误」互相打脸 | 按 `r.status` 分支：`cooldown`→`<b-cool>冷却 29m55s`；`invalid`→`<b-err>凭据失效`（title「连续鉴权失败——到『模型资源』页更新 Key」）；`disabled`→`<b-muted>已停用`（title「你在『模型资源』页关掉的开关」） |
| **W-12** | `captcha.py:207-209,186` | 超时 → `str(TimeoutError)==''` → 空白 | 最可能真实发生的一类失败**没有任何说明** | `except asyncio.TimeoutError: raise CaptchaUnavailable(f"验证码求解超时（>{int(self.timeout_s)}s 未完成）：多为出口代理不可达或浏览器内核缺失——请确认 gateway.zcode.proxy 可连通，或执行 python -m playwright install chromium；也可加 --manual 人工完成一次领取") from e` |
| **W-13** | `captcha.py:297-298` | `T001/T002：… → 网关会自动刷新重试` | 本次领取即告失败，且 60s 内被自家熔断挡住（§4.6 (6b) 实跑） | `验证参数已过期 → 本次领取未成功；网关约 1 分钟后才会重新求解（60s 失败熔断），无需手工处理` |
| **W-14** | `cli.py:61-62` | `--manual  help：未配置住宅代理时，手动完成验证码` | 实际不接受任何输入、不等待，只换一句提示 | `--manual  本次不自动求解：改为提示你在已登录的 ZCode 客户端里手动完成一次领取（本次领取会以失败记录）` |

---

## 6. 新发现缺陷分级（`file:line`）

### 🔴 严重（4 · 全部阻断）

**S-1 · `mgw setup` 的「判定依据」行对网关在跑与否陈述不实，T9 修复实际未生效** —— 实跑 §4.4/4.4b。根因 `cli_setup.py:97` + `local_admin.py:57-61`（无鉴权头）+ `api/auth.py:46-56`；`config.example.yaml:17-21` 默认配密钥 ⇒ 默认部署全中。修法：`admin_get("/v1/models", headers={"Authorization": f"Bearer {api_key}"})`（`api_key` 在 `cli_setup.py:92` 已备好），或改用免鉴权的 `/admin/api/*` 暴露同判据；两种都不能证明在跑时才打「网关未运行」，且建议附端口号（`…（未运行，或端口与此配置不一致）`）。

**S-2 · 全局风控熔断在用户侧整体不可见** —— 实跑 §3.1 / §4.2。三处断点：① `overview/status` 无熔断字段；② 资源态不落盘 → 重启即"看起来正常"，而 §17 回写只在命中那一刻有效（`zcode_claim.py:100-117`；`grep get_circuit model_gateway/core/*` → 0）；③ CLI 已生成的剩余分钟文案被摘要层丢弃并归入「无资格」（`cli_zcode.py:237-256`）。最低成本闭合：`status` 里加 `circuit_active/circuit_left_ms/circuit_reason`（`get_circuit()` 现成），总览复用既有 `.alert-warn` 出一条横幅（不新建页面、不新建轮询，符合 §21.2），CLI 按 W-6/W-7 改摘要。

**S-3 · 出口① 告警① 把用户指到没有该控件的页，并与 §21.2 字面文案冲突** —— `main.py:249` vs `models.js:297,361`、`resources.js:572`、`tech-design.md:1455`。本轮 T11② 声称"指路改正"，改正只落到③；②（无去处）同批未处理。

**S-4 · 「状态」列把冷却/失效标成「停用」，新增两列的目的被同一行推翻** —— 实跑渲染 §3.2；根因 `dashboard.js:111` 以 `available` 为判据 + `resources.py:385-386`（`available = status=="active"`）；`b-cool/b-err` 分支对真实数据不可达 = 死 UI，且违反 `frontend-spec.md:403`（b-muted 语义=停用）与 `design-spec.md:193`（三态徽章 + 悬停剩余时间）。后果：用户被引去翻一个本来就开着的启用开关，而真正该说的是"等 29 分钟 / 换 Key"。

### 🟡 中等（7）

| # | 缺陷 | 证据 | 建议 |
|---|---|---|---|
| M-1 | 验证码**超时**这一类失败文案为空串，三处呈现（CLI 失败行 / JSONL / 红点指引）同时失去信息 | §4.6 (4)/(4b)；`captcha.py:186,207-209`；`test_v2_captcha.py:223-227` 只断言异常类型不测文案 | W-12；测试补 `assert str(excinfo.value).strip() != ""` |
| M-2 | T001/T002 承诺「网关会自动刷新重试」与自家 60s 失败熔断矛盾 | §4.6 (6b)；`captcha.py:167-177,296-299` | W-13 |
| M-3 | 护栏可被证明假绿（4 条变异全部无感），本轮新增的 td/文案断言同样在内 | §7 变异表 | 断言改「按 kind 定位到该条 message」，且 fixture 不得自带兜底 |
| M-4 | `--manual` 的 help 与实际能力不符（无输入、无等待，仅换提示） | `cli.py:61-62`、`captcha.py:156`；§4.6 (2) | W-14 |
| M-5 | 冷却倒计时/熔断恢复在会话内**永不刷新**：总览只渲染一次，`/admin/api/status` 每 5s 已带回同一份快照却只喂红点 | `dashboard.js:5-43`、`main.js:96-124`、`admin.py:118` | 红点轮询回调里顺带重写 `#rv-health` 单元格（零新端点、零新轮询） |
| M-6 | 四类告警同标题同权重（②冗余 / ④提示 与 ①③故障全橙同「配置告警」），既有 `.alert-info` 未用于降级；②亦无去处 | `dashboard.js:68-72`、`base.css:896`；§21.3 原则 3 | ②④走 `.alert-info` + 标题「配置提示」；①③保持「配置告警」 |
| M-7 | 产品内 CLI 指引一律 `mgw …`（红点 title、`claim` 失败行、空态引导），本机 `mgw` 不可执行；README 的兜底形式未被应用引用 | `index.html:109`、`zcode_claim.py:164`、`cli_zcode.py:57,232`；`command -v mgw` 空（§4.7） | 统一 `python -m model_gateway.cli …`（或两者并列）；W-9 |

> 残留但**本轮未声称修**（复跑仍在，不重复计数）：`store.py:144` 覆盖措辞 + 照抄报错（上轮 M-6）；ANSI 无 isatty 门控（`cli_zcode.py:250-252`）；用法行 `mgw zcode {list|login|import|claim}` 过时（`cli_zcode.py:19`、`cli.py:44`）；`counts.models`「可用模型总数」含被横幅宣告不可服务的模型（`admin.py:143`，与出口① 打架）；取消退出码 0/1 不一致；`main.py:232`、`admin.py:164` 注释仍写「**两类**」（实为四类）；`ui_verify_v2_visible.py:2` 自称「headless Chrome CDP」而 `:140-141` 自述 Chrome 挂。

---

## 7. 「能骗过检查」的断言清单（全部以 `/tmp/ix3-mirror` 仓库副本做变异复现，未改仓库任何文件）

变异方法：整仓 `model_gateway/` + `scripts/` 拷到 `/tmp/ix3-mirror`，只改副本，跑**同一份** `verify_v2_frontend.mjs`。

| # | 断言 | 变异 | 结果 | 结论 |
|---|---|---|---|---|
| 1 | `覆盖告警指到可操作的页面`（`mjs:55`：`html.includes("「资源池设置」页")`） | 把 ④ 的「去处」整句删掉（①③ 不动） | **✓ 仍绿**（`mjs` 输出见下） | 🔴 断言对象是**拼接后的全横幅 HTML**，不是那条告警；④ 完全没去处也绿 |
| 2 | `两类隐藏告警都各说一句`（`mjs:48-50`：`match(/已从 \/v1\/models[^。]{0,40}?隐藏/g).length >= 2`） | ③ 去掉「已隐藏」说明，① 把该短语重复第二遍 | **✓ 仍绿，且打印「命中 2 处」** | 🔴 计数型而非按 kind → Q28-② 回归无感 |
| 3 | `熔断原因出现在 td 单元格里（非仅 title 属性）`（`mjs:82-83` + 兜底 `:73-75`） | 从真实 `overview.json` 删掉带熔断原因的那一**整行资源** | **✓ 仍绿，detail 显示的正是脚本自己伪造的行** | 🔴 fixture 兜底 = 自证；后端漏字段/改 `rid` 键名都测不出 |
| 4 | `不再把重跑领取说成查看详情` / `指到 ops-results` / `给出等价命令`（`mjs:127-129`） | 把 `main.js:119-120` 的 `toast(...)` 整段替换成 `toast("已确认")`（注释保留） | **三条全部 ✓ 仍绿** | 🔴 两个 `includes` 命中 `main.js:117-118` 的**注释**；负向正则靠"删掉"即可满足；`index.html:109` 那条仍然写错的 title 根本没进检查 |
| 5 | `四类措辞互不相同`（`py:108`） | —— | 恒真（四条不同模板串必然互不相同） | 🟡 零信息断言 |
| 6 | `pytest test_solve_timeout_is_wrapped_not_raised_raw`（`test_v2_captcha.py:223-227`） | 生产路径超时 | 只 `pytest.raises(类型)`；实测 `str(e)==''` 仍绿 | 🟡 「包装」为真、"用户看得懂"为假 → M-1 |
| 7 | `用双主题令牌（--err / --err-bg）`（`mjs:136-137`，`.ops-dot` 后 300 字符窗口） | —— | 上轮已提，未改：只验"附近出现过 var(--err"，不验明暗两份定义 | 🟡 弱 |
| 8 | `每行 6 个单元格`（`mjs:87-89`） | 把「最近错误」单元格内容替换成空串 | ✓（另有占位符断言兜着 null 情形，但**非 null 的空渲染**无感） | 🟡 计数型断言通病 |
| 9 | 「前端/静态实测 35 项」这一数字 | 删掉一半 `check` | 仍 exit 0 | 🟡 项数无门禁，账本里的 35 不构成护栏 |
| — | **诚实的几条**（值得保留并表扬） | —— | `overview 含四类告警`（集合**相等**）、`每条告警各渲染一条横幅`（banners==warnings 联动变化，实测 M2 后自动变 3/3）、`空 warnings → 不渲染`、`warnings 非数组 → 降级`、`.ellip/td` 结构断言 | ✅ |
| — | **node 子进程崩溃时总脚本是否非 0**（本轮要求确认项） | 把副本 `verify_v2_frontend.mjs` 换成未捕获异常 | `PYTHON_EXIT=1`（同时打印 stderr 前 400 字符） | ✅ **已修复**（`ui_verify_v2_visible.py:162` 的 `r.returncode == 0` 生效）；建议再补「子进程输出里必须出现『实测 N 项，失败 0 项』」的字符串门，防止"提前退出=全绿" |

---

## 8. 环境与时点注记（诚实前置）

- **本沙箱 headless Chrome 会挂**：因此本轮与项目既有口径一致，采用「**真实源码函数 + Node 执行 + 结构/样式静态断言**」，并用真实接口数据（我自己起的隔离实例 `/admin/api/overview`）喂进去渲染。**明确声明：所有本轮结论均未在真实浏览器里验证**——横幅换行、`.ellip` 在 `table-layout:auto` 下是否真按 280px 截断（不截则退化为 `.table-wrap` 横向滚动，`base.css:291`）、长资源名折行造成的行高不齐（§3.3）、toast 3s 可读性、红点 hover title 出现时机，均属**未验证**。
- **`:8300` 上那个实例仍是改动前的代码**（未重启，等用户指示）：PID 19819、已运行 4天18时50分；实跑证明——`/admin/api/overview` **无 `warnings` 键**、资源行 **无 `last_error`**、`POST /admin/api/ops/ack` → **HTTP 405**。也就是说本轮所有可见出口（两新列、四类横幅、新端点、红点文案）在用户真实界面上**一个都还没生效**；本轮所有"用户会看到 X"的结论都是按新代码渲染得出的。
- 真实凭据路径（领取成功/already_done、bench 真上游、probe 真探测、`pip install -e .` 装出 `mgw`、真机过阿里云无痕、住宅代理）：均未验证（与账本 §五 N1–N5 同口径）。
- 写操作边界：仅写 `/tmp/ix3-*`（配置、账号根、锁目录、circuit.json、dry-run 目标 `WORKBUDDY_CONFIG_DIR=/tmp/ix3-wb`）。**例外披露**：为复现默认场景，有一次 `setup … --dry-run` 未设该环境变量，按 §4.4 B 之后的一次运行打印了真实目标目录 `/Users/w/.workbuddy` 并**只读**其 `models.json` 以计算"新增 2"；`--dry-run` 全程不落盘（`cli_setup.py:122-125`）。仓库 `data/` 未被本轮任何进程写入（`ls -la data` 时间戳为 :8300 实例自身日志）。临时网关进程已 kill。
- 仓库改动：**仅本报告一个文件**（`docs/` 在 `.gitignore` 内，`git status` 不列出，故附 `ls -la` 为证）。

---

## 9. 对账本轮账本（T5/T9/T11 与「更正」的兑现情况）

| 账本声称 | 实跑核验 | 判定 |
|---|---|---|
| T11④「红点 toast 不再把重跑说成查看详情，并给 `python -m model_gateway.cli` 等价形式」 | toast 确实改对（`main.js:119-120`）；但同一元素的 `title`（`index.html:109`）仍是旧措辞，且它是唯一可停留的说明 | ⚠️ 半兑现（W-9） |
| T11②「`model_unservable` 指路改正（启停开关在 resources.js:233）」 | ③ 改正无误（页名/控件双向核对通过）；但同类缺陷在 ① 原样存在、在 ③ 后半句残留、② 干脆没去处 | ⚠️ 同类未清零（S-3） |
| T5「`last_error` + 两列 = 熔断原因的用户可见出口」 | 字段与列都在（真实 payload 已渲染）；但状态列标成「停用」（S-4）、重启后无数据（S-2）、倒计时不刷新（M-5） | ❌ 出口不成立 |
| T9「setup 优先向运行中的网关要 /v1/models，并打印判定依据」 | 该请求 100% 拿不到（401），打印的那行反而是假「网关未运行」 | ❌ 未生效（S-1） |
| T6「求解器恒接、各失败原因各有文案、缺失给可执行安装命令」 | 恒接已证（§4.6 (8)）；五类文案四条准确、**超时为空**（M-1）、T001 承诺不实（M-2） | ✅ 大体兑现，两处需补 |
| §四「12/12 + 35/35 + exit 0」「602 passed」 | 前两项逐字复现；`602 passed` 本轮**未复跑**（未验证，不质疑） | ✅ / 未验证 |
| §二 C6 自纠「§17 曾写『无需改前端』是伪前提」 | 更正属实，且本轮确实补了列 | ✅ 诚实加分 |

---

## 10. 复跑方式（只读，零仓库改动）

```bash
cd /Users/w/Desktop/Model-Gateway
export MG_CONFIG=/tmp/ix3-cfg/config.yaml MGW_ZCODE_ACCOUNTS=/tmp/ix3-state/accounts MGW_OPS_LOCK_DIR=/tmp/ix3-locks
nohup .venv/bin/python -m model_gateway.main > /tmp/ix3-gw.log 2>&1 &      # 14555，数据全在 /tmp/ix3-cfg
.venv/bin/python -m model_gateway.cli zcode claim                          # S-2 / W-6 / W-7
.venv/bin/python -m model_gateway.cli zcode claim --account someone-else   # 4.3
.venv/bin/python -m model_gateway.cli setup workbuddy --dry-run            # S-1（配好密钥即在跑也说未运行）
.venv/bin/python /tmp/ix3-captcha-probe.py                                 # 五类失败文案实跑（零网络）
node /tmp/ix3-render.mjs                                                   # 真实 resourceHealthTable + 真实 payload
.venv/bin/python scripts/ui_verify_v2_visible.py; echo exit=$?             # 12/12 + 35/35，exit 0
# 变异复现：cp -R model_gateway scripts /tmp/ix3-mirror/ 后只改副本，再跑 /tmp/ix3-mirror/scripts/verify_v2_frontend.mjs
```

## 11. 判定汇总

**不通过**（阻断 4 条）。放行条件（按最小成本排序，均可在同一条码路内完成）：

1. **S-1**：`admin_get` 带鉴权头（或换免鉴权出口）+ 拿不到运行态时文案不得断言"未运行"（须含"或未响应/端口不符"）。
2. **S-2 + S-4**：`status` 暴露熔断三字段并在总览出一条横幅；`statusBadge` 改按 `status` 分支（同时复活 `b-cool/b-err`）；`claim` 摘要按 W-6/W-7 分桶并打印已生成的剩余分钟明细。
3. **S-3**：告警①②（及③后半句）按 W-1/W-2/W-3 改正指路与去处，与 `models.js:297,361` 的页内说法、§21.2 字面三者一致。
4. **M-3**：`verify_v2_frontend.mjs` 的横幅类断言一律改为「先按 `kind` 取出该条 message，再在其上测」；删除 `benchRow` 的硬编码兜底；`main.js` 的文案断言改为对**渲染产物/字符串常量**取词，不得被注释满足。
5. 中等项 M-1/M-2/M-5/M-6/M-7/M-4 可合并到下一轮，但 M-1（超时空白）建议随 S-1 一并，因它与本轮严重项同属"文案与原因不符"。

> 诚实声明：本报告全部 CLI/接口结论为**实跑原文粘贴**（隔离环境，端口 14555，数据全在 `/tmp/ix3-*`）；变异实验只在 `/tmp/ix3-mirror` 副本上进行，仓库源码零修改（`git status` 与开工前一致）；未在真实浏览器中验证任何视觉结论；`:8300` 用户实例未重启、未写入、未打扰；未向真实上游发任何请求；真实凭据相关路径全部标注未验证。
