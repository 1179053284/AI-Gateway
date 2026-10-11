# 交互设计验收 · 第七轮（ix-accept-7 · 2026-09-28）

> 范围：只验收不改生产代码。被测 = 徽章四态文案 / `fmtCooldown` 口径 / `until_label` 跨午夜 /
> 拒跑轮文案 / `cli_setup` 指路；判据逃逸专攻 = `scripts/verify_v2_frontend.mjs`（实测 67 条 + 变异 56 条）。
> 隔离：变异实验全部在 `/tmp/mg-ix7/repo`（只含门要读的 10 个文件 + 脚本）上做，
> 实验后逐文件 `cmp -s` 与仓库比对零差异；仓库唯一写入 = 本文件。
> `:8300` 实例未重启、未发任何真实上游请求、未碰 `~/.zcode`/`~/.workbuddy*`；`data/` 只读
> （`find data -newermt '-2 hours' -type f` → 空输出）。

---

## ① 结论：**不通过**

两项**产品级阻塞**与六项**门逃逸阻塞**：

| 编号 | 一句话 | 性质 |
|---|---|---|
| **B-1** | 总览「最近错误」列里的恢复时刻**仍是写入时烘死的旧串**：23:50 熔 30 分钟，00:05 读界面仍显示「至 明日 00:20」，而那时 00:20 是 15 分钟后 —— 正是 PRD Q28-⑦ 字面禁止的形态（`prd.md:787` 明确点名 `last_error` 必须与 CLI ⚠ 块同走 `until_label()` 一份口径） | 与需求真相不符，会误导用户 |
| **B-2 ~ B-7** | 六个**改源码而门仍全绿**的变异（`实测 67 项，通过 67 项，失败 0 项`，且 `--mutation` 仍报 `可红 56/56；每条断言都有对应变异`）：口径取整方向不可判 / 负向判据被同义词绕过 / C 段 fixture 字段过少 / `J2` 覆盖面漏掉 `resources.js`+`main.js` / `J2` 只认「」括号 | 门自身可被绕过（S-19b/S-19c 的同类洞未闭合） |

基线复算（本轮亲跑，非引用账本）：
- `.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest-ix -p no:warnings` → **`683 passed in 160.44s`**（与账本一致）
- `node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json`（仓库 pristine 副本）→ **`实测 67 项，通过 67 项，失败 0 项`**

---

## ② 新文案逐条判读（原文抄录 + 判定 + 依据）

视角 = 第一次看到这个页面的用户。判据 = 这句话会不会把我支去一个**不存在/不该去**的列或按钮。

### 2.1 徽章四态 + 未知态（`model_gateway/web/static/js/pages/dashboard.js`）

| # | 状态 | 可见文案 | title 原文（抄录） | 判定 | 依据 / 交叉核对 |
|---|---|---|---|---|---|
| W-1 | `active` | 可用 | `可承接请求` | **通过**：不承诺"健康/无故障"，只说能不能承接；C 段有值时仍可显示"可用"，与 `resources.py:472`（任一 active 即资源可用）一致 | `dashboard.js:131`；`core/resources.py:472` |
| W-2 | `cooldown` | 冷却中 | `${left}s 后自动回池，无需处理` / `已到期，下次选路即回池` | **通过（一句需算术的风险已消除）**：秒数与「冷却剩余」列同源（都走 `fmtCooldown`，`dashboard.js:103`+`:133`），用户不需要换算；`已到期` 分支不再印 `剩余 0s`。**非阻塞建议 R-4**：`无需处理` 与 CLI 的"删除状态文件可立即放开"（`cli_zcode.py:243-246`）在"用户有没有得做"这一层不一致 —— 界面没给任何手动出口 | `dashboard.js:112-115`/`:103`/`:129-134`；`ops/zcode/quota.py` 无对应 UI 端点（`admin.py` 只有 `/admin/api/zcode/bench`，无 un-bench） |
| W-3 | `invalid` | 模型名无效 | `上游回 404：该模型名无效 —— 到「资源池设置」页更换映射（不会自愈）` | **通过**：① 说清是上游 404 而不是我们的错；② 指路目标真实存在 —— `「资源池设置」页` = 侧栏标签（`index.html` 导航）且页内**确实**能改映射（`models.js:290` 资源池有序映射 / `:294` 优先级说明）；③ 不说"换 Key"，不会把用户支去 `模型资源` 页空跑。**遗留（→ B-3）**：判据只防字面串"更换 Key"，写"换 Key/更换密钥"即可加进错误处置而门不红 | `dashboard.js:135`；`js/pages/models.js:290,294` |
| W-4 | `disabled` | 已停用 | `两种成因之一：资源开关已关闭（打开即恢复），或凭据被上游拒绝 401（需到「模型资源」页更换 Key，不会自愈）—— 见「最近错误」列` | **通过（S-19a 已闭合）**：两条成因 + 各自处置都给了；三个指路点全部真实存在 —— 「模型资源」页的开关按钮 `id="rv-toggle"`（`resources.js:233`，标签"禁用/启用"）、该页可编辑 Key（`resources.js:229` "Key 及关联账号 · N 组 Key"、`:370-372` keycopy/eye）、「最近错误」列在 `dashboard.js:96`(表头)/`:104`(单元格)；**且换 Key 真的能恢复**：连接指纹变化 → `state.status="active"` + 清 `last_error`（`resources.py:246-256`），文案不含谎。**建议 R-1**：`打开即恢复` 的主语是"资源开关"，而页面上那颗按钮写着"启用/禁用"（按分组=一组 Key 一条资源），第一次读要绕一下 | `dashboard.js:136`；`core/resources.py:246-256`；`js/pages/resources.js:229,233,370` |
| W-5 | 未知态 | 原样显示 `r.status` | `网关未识别的状态值（可能是新版本引入的态）` | **通过**：中性样式不冒充判死（`b-muted` 非 `b-err`），且明说"可能是新版本引入的态"，用户不会去翻配置 | `dashboard.js:137` |

补充核对（判据 1 要求的 grep 交叉验证）：`grep -c 最近错误 web/static/js/pages/resources.js` → **0**，与 W-4 的处置指向（在总览页而不在资源页）自洽；`cli_setup.py:73-79` 的三条成因指路同样用常量拼页名，且 `runtime_dead` 明确指到 `{OVERVIEW_HEALTH_PAGE}` = `「总览」页的资源健康表`（`core/resources.py:166`），与徽章的指向一致 —— **文案层没有第二套口径**。

### 2.2 跨午夜「至 明日 HH:MM」——冻结时钟读时渲染实测

构造：`CooldownManager(path=/tmp/mg-ix7/circuit.json, now=lambda: 冻结 ms)`，`enter("ZCode 风控熔断（30min，全局）)` 在 23:50 / 12:00；落盘在 /tmp，不碰用户目录。渲染结果**原样抄录**：

| 场景 / 读取时刻 | `circuit.reason()`（读时渲染 = CLI ⚠ 块 / 启动日志的口径） | 写入时烘死的那串（= 总览「最近错误」列的取值） | 判定 |
|---|---|---|---|
| A 23:50 熔，**@23:50** 刚熔 | `ZCode 风控熔断（30min，全局），至 明日 00:20` | 同串 | 唯一可读 ✓（left_ms=1800000，与「冷却剩余 1800s」相互印证，无需算术） |
| A **@23:55** 同夜读 | `…，至 明日 00:20` | 同串 | 唯一可读 ✓ |
| A **@00:05** 跨午夜读 | `…，至 00:20`（**无**「明日」） | `…，至 明日 00:20` | 读时口径 ✓ / **烘死口径 ✗ = B-1**：此刻"明日 00:20"读起来是**还要等一天**，而真实是 15 分钟 |
| A **@00:25** 已恢复 | `…，至 00:20`（left_ms=0，历史位） | `…，至 明日 00:20` | 同上，且恢复后列里留着的仍是"明日"字样 → 用户会把已发生的事读成将来 |
| B 12:00 熔 **@12:00 / @12:20** | `…，至 12:30`（无「明日」） | 同串 | ✓ 与 `test_recovery_clock_..._stays_plain_clock_time_within_the_day` 一致 |
| C 23:50 熔、进程不重启、**@00:05** 才读 | `…，至 00:20` | `…，至 明日 00:20` | **B-1 的最短复现路径**（正是 00:00–00:20 这个窗口内界面上必然出现一次） |

落盘文件原文：`{'until_ms': 1790612400000.0, 'reason': 'ZCode 风控熔断（30min，全局）', 'last_call_ms': 1790610600000.0}` → **文件不含「明日」✓**（S-21 的"只存裸原因"成立）。

**三处（+1 处）口径对表：**

| 出口 | 取值方式 | 是否同一份口径 |
|---|---|---|
| CLI ⚠ 块 | `cli_zcode.py:241` `⚠ {circuit.reason()} —— 本轮未对上游发起任何领取`、`:251` `⚠ 本轮命中风控，已建立全局熔断：{circuit.reason()}` | ✓ 读时渲染 |
| 启动/重载日志 | `main.py:114/117/121` 全部 `% circuit.reason()`（且 `:111` 先 `active()` 判据） | ✓ 读时渲染 |
| **总览「最近错误」列** | `zcode_claim.py:121-124` `enter()` → `reason = circuit.reason()` **取一次** → `bench_all_zcode(reason=…)` → `quota.py:522 state.last_error = reason` → `resources.py:158`/`:491` 快照**原样吐存储串**；`admin.py` 概览端点无重算（`grep circuit model_gateway/api/admin.py` 只有 `/zcode/bench` 与 ack） | ✗ **写入时烘死 → B-1** |
| 顶栏红点 title | `index.html:109` 静态"运营任务有失败 · 点击确认（逐条原因见 data/usage/ops-results-*.jsonl）" | 不适用（不含恢复时刻，见 R-5） |

现有测试为什么没抓到：`tests/unit/test_v2_circuit.py:379-397` 只断言 `CooldownManager.reason()` 与落盘文件，**没有任何一条把 `state.last_error` 拉到午夜后再读一次**。

### 2.3 拒跑轮（S-22）文案可见性

原文（`model_gateway/ops/runner.py:413-418`）：
`运营互斥锁目录不可写：{lock_dir} —— 跨进程互斥建立不起来，本轮未对任何账号发起操作（宁可拒跑也不双领）。请检查数据目录权限或是否被只读挂载`

| 出口 | 呈现 | 能否分辨"我没干活"vs"我干活了但有账号失败" |
|---|---|---|
| `data/usage/ops-results-*.jsonl` | 一轮**一行**（`runner.py:455-461`），`failed` 数组里逐账号带整句原因（`ops/base.py:36` `(账号, 原因)`） | **能**：句子直接说"本轮未对任何账号发起操作"；但**没有机器可读的相位字段**（`category` 仍是 `failed`），要靠中文子串区分 → R-2 |
| CLI stdout | `cli_zcode.py:277-280` 先打 `✗ 失败 N 个：` 再逐行 `账号  {原因}` | **勉强能**：抬头"失败 N 个"里的 N 是**账号数**（5 个号 = 5 行同一句），第一眼会读成"5 个号各自失败了"，往下读原因才纠正 → R-2 建议给这种轮单独一行抬头（如"本轮拒跑：…"）再列账号 |
| 顶栏红点 | 计数 `sum(len(r["failed"]))`（`runner.py:535`）+ 静态 title 指路 jsonl | **不能**：界面上只有"运营失败 5"，成因只在文件里；界面没有运营结果列表页（`grep -rn ops web/static/js/pages/*.js` 只命中 `settings.js:116` 的 CSS 类名 `.maint-ops`）→ R-5 |

`Scheduler._tick()` 侧（`runner.py:595-598`）把"建不起来"与"正被持有"分开计 `errors` + `logger.error`，与用户裁决一致 ✓。

---

## ③ 阻塞项（全部含可复现 diff + 门输出行）

复现方式（统一）：

```bash
W=/tmp/mg-ix7/repo          # 只放门要读的 10 个文件 + 脚本（仓库零改动）
cd /Users/w/Desktop/Model-Gateway
mkdir -p $W/scripts && cp scripts/verify_v2_frontend.mjs $W/scripts/
# …（FILES 里 10 个路径逐个 cp 到同名相对路径，见 mutate.py 的构造）…
cp /tmp/mg-v2-visible/overview.json /tmp/mg-ix7/overview.json
# 施加下面某一条变异后：
node $W/scripts/verify_v2_frontend.mjs /tmp/mg-ix7/overview.json
node $W/scripts/verify_v2_frontend.mjs /tmp/mg-ix7/overview.json --mutation
```

### B-1｜「最近错误」列的恢复时刻是写入时烘死的（跨午夜后必然说谎）

- 缺陷链：`ops/builtin/zcode_claim.py:121-124` → `upstream/zcode/quota.py:522` → `core/resources.py:158,491`；读取侧无重算。
- 复现（已实测，输出抄自 2.2 表格）：23:50 `enter()`，00:05 时 `circuit.reason()` = `…，至 00:20` 而同一时刻列里那条 = `…，至 明日 00:20`。
- 与需求冲突：`docs/specs/prd.md:787`（Q28-⑦①）"**CLI 的 ⚠ 块、`last_error`、日志同用 `quota.until_label()` 一份口径**"，且理由栏点名的正是这个形态。
- 修法建议（择一，别再打补丁）：① `last_error` 存**裸原因 + until_ms**，快照出口按当时的钟点渲染；② 或把 `until_ms` 作为独立字段随冷却 bench 落进 `ResourceState`，`snapshot_by_resource` 里调 `quota._with_until()`（保持唯一口径）。补一条把 `state.last_error` 拉到午夜后复读的判据（现在 `test_v2_circuit.py:379` 只测 `reason()`）。

### B-2｜`fmtCooldown` 的取整方向不可判（ceil→floor 全绿）

```diff
- const n = Math.ceil((ms || 0) / 1000);
+ const n = Math.floor((ms || 0) / 1000);
```
门输出：`实测 67 项，通过 67 项，失败 0 项` ／ `--mutation` → `可红 56/56；每条断言都有对应变异`
根因：S-19b 把徽章与列**收敛成同一个函数**（正确），于是"两处同串"判据（`C12`，脚本 `:219-226`）对任何单函数内部改动恒绿；而所有 fixture 毫秒值都是 1000 的整数倍（脚本 `:128` `1799000`、`:181` `61000`、`:229` `1766000`；`/tmp/mg-v2-visible/overview.json` 的 res-a 是 `1799998`，但 `C6/C11` 用的是脚本内写死值）→ floor 与 ceil 无差。真实 payload 一定是非整秒（1799998 就是证据），所以"少报 1 秒/向下取整"这类**让用户提前预期回池**的改动门看不见。
修法：`C12` 之外加一条"同一 ms 的串必须等于 `Math.ceil(ms/1000)`"的口径钉，并把 fixture 改成非整秒（如 `1799998`）+ 至少一条断言直取 `fmtCooldown(1500)` = `2s`。

### B-3｜`invalid` 的负向判据只认字面串"更换 Key"（同义词可塞进错误处置）

```diff
- 到「资源池设置」页更换映射（不会自愈）
+ 到「资源池设置」页更换映射；也可先换 Key 重试（不会自愈）
```
门输出：`实测 67 项，通过 67 项，失败 0 项`
根因：`C3`（脚本 `:190-194`）用 `!titleOf(b.invalid).includes("更换 Key")`。S-19a 的实质是"别把 404 说成换 Key 能好"，但字面串判据挡不住"换 Key / 更换密钥 / 试试别的 Key"。用户照做 → 换了一把好 Key 仍然 404，白折腾。
修法：负向判据改语义集（`/换\s*Key|更换密钥|换\s*凭据/i` 全禁），或正向钉死"处置短语必须逐字等于 `更换映射`"（`= titleOf(...).match(/更换\S+/)` 唯一）。

### B-4｜C 段 fixture 字段过少，"只影响真实载荷"的分支不可见

```diff
- ">已停用</span>`;
+ ">${r.account ? "已停用（账号未启用）" : "已停用"}</span>`;
```
门输出：`实测 67 项，通过 67 项，失败 0 项`
根因：脚本 `:179-184` 的四个 fixture 只给 `status/available/cooldown_remaining_ms`，**不带 `account`/`C`/`in_flight`/`models`**；而生产快照里这些字段恒在（`resources.py:491` 附近的快照字典），并且 ZCode 熔断的匹配要求**资源 `account` 备注恰好等于 ZCode 账号名**（`quota.py:605-607`；该字段界面必填，`config/schemas.py:144` Q20-③），真实资源通常带非空 `account` 与非零 `C`/`in_flight`（本轮实测的 `overview.json` 里 res-a 就是 `account:""`/`C:0`/`models:1` 的构造数据，不代表生产）。于是任何按这些字段分叉的文案/分支（含把"已停用"改成"账号未启用"这种**归因错误**）都进不了判据。
修法：C 段至少一份 fixture 用**真实快照**（`/tmp/mg-v2-visible/overview.json` 里 res-a 已有 `account/C/in_flight/models`，可直接把 `statusBadge(benchRow)` 也纳入 C1~C5 的输入集，而不是另造精简对象）。

### B-5 / B-6｜`J2` 的覆盖面漏了 `resources.js` 与 `main.js`（页名指路可随便指去不存在的页）

```diff
# resources.js:235（模型资源页，用户 hover 可见）
- title="删除该供应商及其全部 Key 与模型映射"
+ title="删除该供应商及其全部 Key 与模型映射（换 Key 请到「模型映射」页）"
```
```diff
# main.js:119（红点 toast，用户必然看到）
- 逐条原因见 data/usage/ops-results-*.jsonl
+ 逐条原因见「运营日志」页 data/usage/ops-results-*.jsonl
```
两条门输出均为：`实测 67 项，通过 67 项，失败 0 项`
根因：脚本 `:382-386` 的 `copySources` 只列 `dashboard.js / models.js / apiaccess.js / settings.js / core/resources.py / cli_setup.py` —— **不读 `resources.js`（`FILES.res` 已读却只喂 D1~D3）也不读 `main.js`**（`mainSrc` 只喂 F/G/J1）。S-19c 的账本把结论写成"前端 + Python 里所有「X」页必须命中真导航项"，覆盖面其实差两个用户文案最密的前端文件；`main.py` 更是连 `FILES` 都不在（`:121/294/321/338` 四处指路全靠常量才没漂）。
修法：`copySources` 直接由 `FILES` 里所有前端 + Python 文案文件生成（少手工点名），并把 `main.py` 加进 `FILES`。

### B-7｜`J2` 只认「」括号，换一种书名号/引号即完全隐身

```diff
# cli_setup.py:75（J2 **确实**读这个文件，但这条不会被抽出）
- "resource_disabled": f"到{RESOURCE_PAGE}打开对应资源的启用开关",
+ "resource_disabled": f"到『模型映射』页打开对应资源的启用开关",
```
门输出：`实测 67 项，通过 67 项，失败 0 项` ／ `--mutation` → `可红 56/56；每条断言都有对应变异`
根因：脚本 `:391` 的正则 `/「([^「」]{2,12})」页/g` 只匹配直角引号。`mgw setup` 把用户指去一个不存在的「模型映射」页（Q24 已更名）而门全绿 —— 与 S-17/S-19c 修的是同一类缺陷，只是括号不同。
修法：判据扩为 `(「[^「」]{2,12}」|『[^『』]{2,12}』|"…")\s*页`，并反向钉"文案里凡是 `X页` 形式的目标必须来自常量"。

> 备注（账本 over-claim，铁律 2）：S-19b 行写"**并把真源码注入 harness（不许在 JS 里重写一份格式化函数）**"，但脚本 `:157-160` 的 B7 间谍注入的是**手写复制品** `(ms) => Math.ceil(...)`；`fmtCooldown` 的任何改动对 B7 都不敏感。这条与 B-2 同根。

---

## ④ 非阻塞建议

- **R-1** `disabled` 的 title 里"资源开关"建议改成页面实际字样（那颗按钮写"启用/禁用"），少一次心智翻译。
- **R-2** 拒跑轮：`OpResult` 加一个相位字段（如 `stage: "lock_unusable"`），CLI 抬头对这种轮打"本轮拒跑（未发起任何操作）"，红点文案对这种轮可显示"运营停摆"而非"运营失败 N"。
- **R-3** 四态处置全在 hover title 里；触屏/窄屏无 hover 时用户只剩"已停用"三个字。建议把成因指向浓缩一句进「最近错误」列（该列已在同一行右侧，成本为零）。
- **R-4** `cooldown` 说"无需处理"，但 CLI 明说删除 `circuit.json` 可立即放开领取（`cli_zcode.py:243-246`）：界面侧要么给同样的出口，要么把"无需处理"限定为"网关会自动恢复"。
- **R-5** 运营失败**界面没有明细页**，唯一出口是文件（`grep -rn ops web/static/js/pages/*.js` → 只有 `settings.js:116` 的 `.maint-ops`）。红点 title 是指路文案却是静态串，无法带出"这一轮的成因"。属设计缺口，建议按 Q28 另立需求项。
- **R-6** `docs/specs/design-spec.md` / `frontend-spec.md` 里检索不到徽章四态的字面文案（`冷却中/已停用/模型名无效` 零命中，仅 `design-spec.md:219` 的"（已停用）"是另一处），意味着四态文案的真相只活在 `dashboard.js` + 门里；建议把五态文案回写进 design-spec §2.1，否则第八轮还会重新审一遍。

---

## ⑤ 我设计过但**没能打破**门的变异（门在以下几点是硬的）

| 变异（施加于 /tmp 副本） | 门的反应（实测行原样） |
|---|---|
| 徽章与列各算一套：`left > 0 ? \`${left - 1}s 后自动回池\`` | `实测 67 项，通过 65 项，失败 2 项` → **`✗ C6`** `✗ C12`（S-19b 的原缺陷形态确实回潮即红） |
| 「冷却剩余」列不再报秒数（改成恒 `—`） | `通过 64 项，失败 3 项` → **`✗ B4` `✗ C12` `✗ C13`** |
| `disabled` 的处置从 title 挪空（`title=""`） | `失败 1 项` → **`✗ C4`**（`visible()`/`titleOf()` 分开判确实咬住了"只有属性里有话说"这种假通过） |
| 覆盖面内文件用规范括号指去不存在的页（`dashboard.js`：「模型资源」→「模型映射」） | `失败 1 项` → **`✗ J2` 违规指路：dashboard.js→「模型映射」页**（报错把违规文件+页名一起打出来，可直接定位） |

另外三条不必自己施加变异也能确认判据是真的：`A15`（调用点筛类别）/`I9`（加载即 POST）/`C8`（`cooldown + remaining=0` 归正）在门自带 `MUTATIONS` 里有对应变异（脚本 `:497-500`、`:554-557`、`:508-512`），本轮两次 `--mutation` 运行（B-2/B-7 变异态下）都打印 `可红 56/56；每条断言都有对应变异`，即施加各自变异时它们确实变红。

**门仍属"文本判据 + fixture 判据"的性质**：它对**字面串与调用形状**很硬（B-1 之外的文案改写基本一改就红），但对**语义等价改写**（同义词、书名号、取整方向、真实载荷才有的字段）没有抵抗力 —— B-2~B-7 全部落在后半类。
