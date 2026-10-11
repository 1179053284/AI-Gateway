# 交互验收报告（第四轮）· ix-accept-4 · 2026-09-28

> 角色：资深交互设计师（B 端 / 开发者工具）· 三角色只读验收面板 · **第四轮**
> 基准：`docs/specs/tech-design.md` v2.0 **§21**（四处出口 + 三条原则）/ §17 / §16.2；`docs/specs/prd.md` v1.15 **Q28-②③⑤**；`design-spec.md:192`；`frontend-spec.md:403`
> 被审账本：`docs/changes/e2e-records/E2E-20260927-round4-fixes.md`（1–11 项 + §二红证表）
> 纪律：除本报告外**零仓库文件改动**；全部临时物在 `/tmp/mgw-ix-*`、`/tmp/ix*_probe.py`、`/tmp/render_badge.mjs`、`/tmp/mgw-fakeroot/`；未跑 `scripts/ui_verify_v2_visible.py`；未重启 `:8300`、未向其发过任何 POST（`_ack_failures` 在我所有探针里被换成记录器）；未碰 `~/.zcode` / `~/.workbuddy*` / 仓库 `data/`（仅 GET 与读文件）。
> 取证方式声明：**本轮同样拿不到像素证据**（headless Chrome 在本沙箱会挂），且 `:8300` 上跑的是用户的**老实例**（`uptime_ms=443927752` ≈ 5.1 天；`/admin/api/status` 无 `ops_failed_unread`、`/admin/api/overview` 无 `warnings`/`last_error` → 非本轮代码）。我因此把证据下沉到两层：**① 直接调用生产函数/生产代码路径**（`snapshot_by_resource` / `CooldownManager` / `cli.main(["zcode","claim"])` / `mgw setup --dry-run` 实跑）＋ **② 用生产 `dashboard.js` 源码经 Node 执行渲染函数**，两者都不是复制品。

---

## 1. 一句话结论

**不通过。** 本轮四项文案修正确实落地（我逐条实跑复现了 401 不再谎报未运行、熔断开局不再打「全部正常」且退 3、徽章四分支不再把冷却说成停用、红点 title 与副作用一致）；但**其中两项在"用户下一步怎么办"上仍然说谎或自相矛盾**，而且说谎的位置从前端搬到了后端聚合与 CLI 文案：

| 严重（S） | 中（M） | 轻（L） |
|---|---|---|
| **2** | **7** | **6** |

- **S-1**：CLI 承诺「或删除该文件以提前解除」——实测**对正在运行的网关完全不成立**，并且照做会在风控观察期内**清掉跨进程熔断记录**（副作用与文案意图相反）。
- **S-2**：`statusBadge` 四分支修好了，但后端 `snapshot_by_resource` 把「上游 401 判死的 Key」聚合成 `cooldown` → 界面渲染出 **`cooldown` + `剩余 0s`**，同页横幅同时写着「资源映射全部不可用（已停用或凭据失效）」——IX-4 同一缺陷类仍在，且这次两张嘴。
- 另有 **M-3 熔断空跑仍清零红点**、**M-4 红点指路的 jsonl 对 CLI 失败根本不存在**、**M-5 `mgw setup` 跳过原因指错页**（实测可复现）等 7 项中等问题。

---

## 2. 五项判定表（逐项附证据与逐字文案）

| # | 项 | 判定 | 关键证据（`file:line` / 命令 + 实测输出） |
|---|---|---|---|
| **1** | **IX-4 状态徽章四分支** | **不通过**（前端分支本身：通过；作为"用户看到的最终输出"：不通过） | 分支代码 `dashboard.js:110-123` ✅ 四态互不相同 + 兜底不归正；**但真实载荷** `resources.py:360-371` 把条目级 `disabled`（401/AUTH，`scheduler.py:403`）并入 `cooldown` → 实测 `/tmp/ix4_probe.py`：`A 上游 401 判死 → {'status':'cooldown','cooldown_remaining_ms':0,'last_error':'上游返回 401：invalid_api_key'}`；渲染 `/tmp/render_badge.mjs`：`→ <span class="badge b-cool" title="剩余 0s">cooldown</span>` + 同行「冷却剩余」= `—` |
| **2** | **IX-2 熔断可见性 + CLI 诚实性** | **有条件通过**（开局态：通过；**新置态/解除出口/退出码文档：不通过**） | 界面侧：`tests/integration/test_int_v2_circuit_boot.py`（真启动 + 真 HTTP GET overview）48 条测试全绿（`pytest … -q --basetemp=/tmp/mgw-pytest-ix` → `48 passed`），断言 `available is False` 且 `"风控熔断" in last_error` ✅ 重启后看得见。CLI 侧逐字实测（`/tmp/ix_redpoint_probe.py`，`admin_post` 换记录器）：<br>`⚠ ZCode 风控熔断（30min，全局），至 00:50 —— 本轮未对上游发起任何领取`<br>`    状态文件：…/circuit.json（等待自动到期，或删除该文件以提前解除）`<br>`– 跳过 2 个（无资格 2）` / `退出码 = 3`；**同一脚本另外记到 `POST /admin/api/ops/ack`** → 空跑清零（M-3）。<br>「删除即解除」反证（`/tmp/ix2_probe.py`）：删文件后常驻进程 `active = True / left_minutes = 30`，**新进程** `active = False` → 文案不成立且削弱保护（S-1）。<br>跨午夜：23:50 进入 → 文案 `至 00:20`（无日期，L-1）。<br>退出码文档：`mgw zcode claim --help`（`cli.py:59-62`）与 `README*.md` **均无 0/1/2/3 说明**，只有 `cli_zcode.py:220-222` 注释；且 `3` 在 `cli_setup.py:152`=写盘失败、网关进程=「已有实例」（§4.10）三处同码不同义（M-7） |
| **3** | **T9b `mgw setup` 判定依据三态** | **通过（文案本身）/ 有条件（下一步指路）** | 真跑 `python -m model_gateway.cli setup workbuddy --dry-run`（`WORKBUDDY_CONFIG_DIR=/tmp/mgw-ix-home`，未写任何工具目录）：<br>① 正常：`可服务模型判定依据：运行中网关的 /v1/models（7 个模型可服务，含运行态）`<br>② 密钥错：`可服务模型判定依据：本地配置 · 原因：网关在运行但拒绝了接入密钥（401：密钥已停用或删除） —— 感知不到资源失效等运行态`（**不再谎报未运行** ✅，`local_admin.py:51-58` + `cli_setup.py:108`）<br>③ 未运行：`… 原因：网关未运行（连接被拒） …`；④ 超时（黑洞端口 8411，生产 `admin_get_detail`）：`why='timeout' → … 原因：网关无响应（超时） …`<br>缺项：跳过行的动作指路对 2/3 成因是错的（M-5），401 只列一因（L-6，账本 G2 已自登记） |
| **4** | **顶栏红点文案 = 副作用** | **不通过**（措辞一致 ✅；副作用边界与指路真实性 ❌） | 一致性：`index.html:109` `title="运营任务有失败 · 点击确认（逐条原因见 data/usage/ops-results-*.jsonl）"`；`main.js:119-120` toast `已确认运营失败。逐条原因见 data/usage/ops-results-*.jsonl；重跑用 mgw zcode claim（未安装则 python -m model_gateway.cli zcode claim）`；全仓 `grep 查看详情` 在**出厂 UI 里已无残留**（只剩 `docs/specs/ui-template-design-brief.md` 模板示意）✅；`python -m model_gateway.cli --version` → `mgw 0.1.0` ✅ 兜底命令是真的。<br>不一致处：熔断空跑照样 ack（M-3，实测 POST 记录）；`ops-results-*.jsonl` **只有网关调度器写**（`main.py:134,140`；`write_report` 全仓无第三个调用点，CLI 路径不调）→ CLI 看到的失败永远不在被指路的文件里，且当前 `find data -name "ops-results*"` = 空（M-4） |
| **5** | **前端判据门 `verify_v2_frontend.mjs`** | **通过（作为"红证自证"）/ 不通过（作为"UI 能用"的证据）** | `node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json` → **`实测 46 项，通过 46 项，失败 0 项`**；`--mutation` → **`可红 37/37；每条断言都有对应变异`**；`pytest tests/integration/test_int_v2_frontend_gate.py`（含在生产 48 条里）2 条绿。<br>但我用三个**不在变异表里**的源码破坏做"逃逸实验"（副本 `/tmp/mgw-fakeroot/`，源码零改动），门**全部保持 46/46 绿**：见 §4 空过清单 E-1/E-2/E-3。门能证明的是"这些字符串还在这些文件里 + 这些断言不是恒真"，**不能**证明界面能用 |

---

## 3. 新缺陷分级（用户在哪一步 · 看到什么 · 以为什么 · 真相）

### 🔴 严重

**S-1 · CLI 的"手动解除熔断"出口是假的，且照做会拆掉保护**（`model_gateway/cli_zcode.py:237`）
- **哪一步**：领取被风控挡住，用户想"我不想等 30 分钟"。
- **看到（逐字）**：`    状态文件：/Users/…/data/upstream/zcode/circuit.json（等待自动到期，或删除该文件以提前解除）`
- **以为**：删了这个文件，熔断就解除了，可以立刻重领。
- **真相（实测 `/tmp/ix2_probe.py`）**：`文件已删除 exists = False` → `G（常驻进程）删除后 active = True left_minutes = 30`。**运行中的网关读的是内存态**（`quota.py:380-391 _load()` 遇 `OSError` 直接 `return`，不清 `_cd`），删除**不能提前解除**；而 `新进程 active = False` 说明删除**抹掉了跨进程唯一凭据** —— 下一次重启的网关在风控观察期内既不 bench 也不拦领取（`sync_circuit_to_runtime` 直接 `return 0`），正是 §17 立项要防的那件事。文案意图与副作用**方向相反**。
- 关联：账本 D3 把「手改本地文件」当作唯一手动出口（引 §14），所以这条不是边角措辞，是**该修复的唯一出口本身**。

**S-2 · 「上游 401 判死」在界面上被说成"冷却中，剩余 0s"，并与同页横幅打架**（`core/resources.py:360-371` + `dashboard.js:118`）
- **哪一步**：Key 被上游拒了（改了 Key / Key 过期），用户开总览想知道怎么办。
- **看到（逐字，渲染自生产 `dashboard.js`）**：状态列 `<span class="badge b-cool" title="剩余 0s">cooldown</span>`；「冷却剩余」列 `—`；「最近错误」列 `上游返回 401：invalid_api_key`；顶部横幅 `1 个已启用模型的服务映射全部不可用（已停用或凭据失效）…`（`model_unservable`）。
- **以为**：只是暂时冷却，等一下自动恢复 —— 于是**不去换 Key**；而且同一屏一个地方说"等会儿"、一个地方说"要动手"，用户不知道信哪个。
- **真相（实测 `/tmp/ix4_probe.py` 三行）**：`A 上游 401 判死 → status='cooldown' / cooldown_remaining_ms=0`、`B 冷却已到期未归位 → status='cooldown' / cooldown_remaining_ms=0`、`F 整资源 AUTH → status='cooldown' / remaining=0`。聚合式 `elif entries and all(e.status != "active"): status = "cooldown"` 把**条目级 `disabled`（AUTH，`scheduler.py:403`）与"到期未懒恢复"**一律折成 `cooldown`；`ResourceState.available` 对 `disabled` 永不自愈（懒恢复只覆盖 `cooldown`，`resources.py:246-248`）。前端 IV 分支忠实地渲染了一个已经丢信息的字段 —— **IX-4 的缺陷类没消失，只是从前端下移到了聚合层**。

### 🟠 中

**M-3 · 一次上游都没打的熔断轮，照样清零用户的未读失败**（`cli_zcode.py:268`）
用户看到 `⚠ … 本轮未对上游发起任何领取` + `– 跳过 2 个（无资格 2）`，以为"这轮什么都没发生"；真相（实测同一脚本 `POST 记录 → POST /admin/api/ops/ack`）：顶栏红点**被清空**，而清空是**全局**的（`admin.py:379-388` → `clear_failed_counter` 归 0），把网关 `query_balance` 那类他从没在 CLI 里看到过的失败一起抹掉（`main.py:140` 共用同一计数）。CLI 侧没有任何一句说明"已确认/已清零"。

**M-4 · 红点文案指路的明细文件不含 CLI 的失败**（`index.html:109` / `main.js:119` / `ops/runner.py:426-441`）
用户点红点 → 看到 `逐条原因见 data/usage/ops-results-*.jsonl` → 去翻文件；真相：`write_report` 只在网关调度器里被调（`main.py:134,140`），`mgw zcode claim` 的失败**只打印、不落盘**（全仓第三个调用点不存在），照做的人会得出"界面在骗我"或"我的失败是假的"。另：`runner.py:13` 文档字符串与 §21.2 表都写 `data/ops-results-<date>.jsonl`（少一层 `usage/`），文案对了、规范落后（见 L-4）。

**M-5 · `mgw setup` 的跳过解释把"开关没开/Key 失效"说成"没映射"**（`cli_setup.py:120-121`）
逐字：`已跳过 1 个无可用资源的模型（m-mapped-but-off）—— 到「模型资源」页为它们添加映射`。真相（实测：模型**有**映射、资源 `enabled:false`）：映射早已存在，该做的是打开资源开关或换 Key（横幅 `model_unservable` 给的正是这两条）。用户跑到「模型资源」页找不到"添加映射"的对象 → 判定界面在说谎。Q28-②「不许只过滤不解释」在**数量**上达标、在**动作**上不达标。

**M-6 · 熔断的"唯一可见出口"依赖账号名备注字符串相等，不匹配时静默空转**（`quota.py:536-545 resource_ids_of_account` + `main.py:93 if n:`）
用户在 CLI 看到熔断进行中，去总览找"哪个资源被熔了"；真相：`resource_ids_of_account` 要求 `资源.account.strip() == ZCode 账号名`（Q20-③ 的备注约定），不相等 → `bench_all_zcode` 返回 0 → `sync_circuit` 的 `if n:` 连一条日志都不发（实测：账号名与资源备注不挂钩时资源仍是 `active`、`last_error=None`）—— 正是第三轮 S-2 的症状，只是触发条件从"代码没接"变成"备注没起中文名对齐"。

**M-2 · 「– 跳过 N 个（无资格 N）」把三种不同因由压成一个标签**（`cli_zcode.py:247-254` + `zcode_claim.py:125-137`）
逐字：`– 跳过 2 个（无资格 2）`。真相：`_circuit_gate` 与「今日名额已用完」「活动结束」「（无账号参与）」**共用 `inactive` 桶**，而呈现层只印桶计数、**从不打印每条的 detail**（那里带着「剩余约 X 分钟」）。§21.3 原则 3（正常业务态与需关注分开）与 §16.2 的类别定义在此互相打脸。

**M-1 · 熔断"被建立"的那一轮完全没有熔断提示**（`cli_zcode.py:231` 只判开局）
逐字实测（`/tmp/ix_redpoint_probe.py` 第二轮，FakeClient 返 3012）：
```
– 跳过 1 个（无资格 1）
✗ 失败 1 个：
    acct-a  unusual activity detected, please try later
退出码 = 1 | 结束后 active() = True | 熔断文件已落盘 = True
```
用户以为"就一次网络/业务失败，重试就好"→ 很可能马上再 `claim`；真相：这一次**建立了 30 分钟全局熔断**（`active() True`），第二个账号已被熔断挡下，而界面上没有任何一句「已触发全局熔断，至 HH:MM，状态文件 …」。修好的"开局可见"没覆盖"发生瞬间可见"。

**M-7 · 退出码语义不可见且跨子命令不一致**（`cli_zcode.py:220-222` vs `cli.py:59-62`、`cli_setup.py:152`、§4.10）
`0/1/2/3` 只写在源码 docstring；`--help`、README、`docs/specs/§16.4` 都没同步（账本 D4 自认"§16.4 只定了 0/1/2"）。脚本化用户读到 `3` 无法分辨是"熔断未执行"（claim）、"写盘失败"（setup）还是"已有实例在跑"（网关进程）。

### 🟡 轻

- **L-1 · 恢复时刻无日期**：`至 00:20` 对 23:50 建立的熔断是"次日 00:20"，但界面/CLI 无"次日"字样（实测 `23:50 进入熔断 → … ，至 00:20`）。建议 `至 明天 00:20` 或 `至 09-28 00:20`。
- **L-2 · 状态列中英混排 + `invalid` 零提示**：`active` / `cooldown` / `invalid` 为英文、`停用` 为中文；`invalid` 分支**连 title 都没有**（`dashboard.js:119`），用户不知道它=凭据/模型名永久失效。另 §17 字面是 `ZCode 风控熔断（30min，至 HH:MM）`，实现为 `…（30min，全局），至 HH:MM`（括号内外错位，账本称"按 §17 字面"，属轻微 overstated）。
- **L-3 · 熔断资源与普通冷却资源同形**：状态列两种情况都是 `b-cool cooldown`，区分只剩「最近错误」单元格 —— 它是 `.ellip max-width:280px` 的截断文本，全文只在 hover title（触屏/键盘不可达）；剩余时长以秒显示 `1800s`（G1 已登记）。
- **L-4 · 规范/注释路径落后于实现**：`runner.py:13` 与 `tech-design.md:1456` 写 `data/ops-results-<date>.jsonl`，实现（`runner.py:428`）写 `data/usage/ops-results-<date>.jsonl`；界面文案与实现一致 → 以规范为准会错。
- **L-5 · 失败行顺序错乱（管道下）**：实测 `mgw setup` 全无可下发模型时，stderr 的 `✗ 没有可下发的系统模型…` 出现在 `目标目录 / 判定依据` **之前**（stdout 块缓冲），读日志的人误以为"没到判据就失败了"。
- **L-6 · 401 提示只列一因**（`local_admin.py:55`）：`（401：密钥已停用或删除）`；端口/`--config` 指向另一份配置同样 401。账本 G2 已登记未做 —— 保持登记状态即可，但别宣称"三态可分辨"已完备。

---

## 4. 前端判据的空过清单（具体到 check id）

**实测三个"逃逸实验"（在 `/tmp/mgw-fakeroot/` 副本上施加，源码零改动；三个都不在 37 条变异表里）**

| 编号 | 施加的源码破坏 | 门的结果 | 该红而未红的判据 |
|---|---|---|---|
| **E-1** | `dashboard.js` 资源健康表不再调用徽章函数：`<td>${statusBadge(r)}</td>` → `<td><span class="badge b-ok">active</span></td>`（整表恒绿标 active） | **46/46 绿** | `C1–C7`（它们只单测 `statusBadge`，**没有一条判"表格真的调用了它"**）+ `B1–B6` 全不响 |
| **E-2** | `main.js` 红点点击处理器首行插 `return;`（点击什么都不做，`POST("/admin/api/ops/ack")` 文本仍在文件里） | **46/46 绿** | **`F7`「点击红点真的 POST 确认（不是只弹提示）」** —— 名字承诺行为，判据只做 `includes` |
| **E-3** | `statusBadge` 前插 `if (r.status === "cooldown" && !(r.cooldown_remaining_ms > 0)) return b-ok active`（把 S-2 的真实载荷渲染成绿标正常） | **46/46 绿** | `C2/C5/C6` —— fixture 与 `MUTATIONS` 里的 cooldown 载荷 `cooldown_remaining_ms` 恒 >0，**生产可达的 `remaining=0` 形态没有载荷** |

**判据锚定层级错位（结构性、非单条 bug）**

| 组 | 具体判据 | 锚定实为 | 因此看不见 |
|---|---|---|---|
| `F1 F2 F3 F4 F5 F6`、`G1 G2 G3`、`E1 E2 E3 E4`、`H1 H2` | `mainSrc.includes(...)` / 正则扫 `main.js` / `index.html` / `base.css` **源码文本** | 源码字符串在场，**从不执行 main.js** | 轮询是否真跑、`dotText.textContent` 的值（`运营失败 N`）、ack 后是否真回隐、toast 是否真渲染、5s 与 20s 两个 `setInterval` 的相互影响、处理器绑定顺序 |
| `E4` | `dotTag` 正则只取 `<button …>` **开标签** | 单标签属性串 | 红点子节点 `<span class="ops-dot-mark">` 里若再长出误导文案，完全在判据外 |
| `A2–A9` | 判 **fixture 自带字符串**的回声 | 手工模式下 `/tmp/mg-v2-visible/overview.json` 是手维护文件 | 生产告警文案改了字面 → 手工模式仍绿（只有 `test_int_v2_frontend_gate.py` 用生产装配重造才闭合）；A6/A7/A8 三条尤其 |
| `--mutation` 自身 | `catch (e) { threw = e.name; red = mut.kills; }`（脚本第 317-319 行） | **抛错即视作"指定断言已红"** | 本轮实测 **1 例走此分支**：`✓ 非数组 warnings 不做类型兜底（运行时抛错） [抛错 TypeError]` → `A12` 的"可红"是**推定**的，未被观察。37/37 的分子里含 1 个自证豁免 |
| 门的自锁 | 只钉数量（断言 ≥40 / 变异 ≥30） | 数量 | 把 `C1–C7` 换成 7 条无关断言，门照绿 |

**门结构上不可能覆盖（本轮面板的共同盲区，不许用"46/46 绿"代替"UI 能用"）**

1. **不建 DOM、不解析 HTML**：属性引号截断、`.ellip` 280px 溢出后的可读性、列宽/对齐、`<thead>` 与 `<tbody>` 的实际栅格、卡片等高/12px 节奏（frontend-spec 的量化条款）—— 一条都测不到。`A14` 只测告警文案转义，资源名 / `last_error` 进 `title="…"` 的转义无判据。
2. **不测量布局**：无一处 `getBoundingClientRect`；`B6` 只数标签个数，不测视觉列对应关系（第三轮的"窄屏换行/等宽并列"类缺陷全在盲区）。
3. **不做双主题并排**：`H1/H2` 只看 `.ops-dot` 一个类的令牌化。我自己用源码 grep 补验了本轮相关类：`base.css:23`（浅）与 `:59`（深）都定义了 `--cool/--cool-bg`，`.b-cool`（`:331`）双色可用 —— **但这是人肉补测，不是门的结论**。
4. **零可达性判据**：无键盘 Tab 序、无 focus 环、无 `aria-*`、无 role、无对比度计算；`E1` 只验 id 存在。红点是一个 `<button hidden>`，其全部信息（`title` + `dotText`）对屏幕阅读器是否朗读、hover-only 的 4 处 title（徽章剩余秒 / 三个表头解释 / 最近错误全文 / 红点说明）在触屏与键盘下**不可达**，无一测到。
5. **页面覆盖窄**：只有 `dashboard.js` 三函数 + `resources.js` 的 `promoteKeyDraft`（D1–D3）+ 红点三文件。`models.js` / `apiaccess.js` / `stats.js` / `logs.js` / `settings.js` / `templates.js` **六页零判据**（含 Q28-③ 参数卡、密钥密文、脏态徽章、D3 操作即保存这些本轮之前就定版的表面）。
6. **不跑真接口**：`/admin/api/overview` 的真实载荷形态（尤其 S-2 的 `cooldown + remaining=0 + AUTH last_error`）从未进入门；`snapshot_by_resource` 与 `statusBadge` 之间没有一条契约测试。

---

## 5. 要求主 agent 执行的撤修复红证清单（交互面 · 按优先级）

> 本轮我**没有权限改源码**，以下是我判"该红没红 / 无判据"的点，请逐条做「撤修复 → 跑 → 记条数」。前三条我已用逃逸实验证明**当前门抓不到**，属必做。

| # | 施加（撤/改） | 期望 | 我现在的证据 |
|---|---|---|---|
| **R1** | `dashboard.js` 表格里 `<td>${statusBadge(r)}</td>` → 硬编码 `b-ok active` 徽章 | `verify_v2_frontend.mjs` 必须红；**当前实测 46/46 绿** | E-1 |
| **R2** | `main.js` 红点 click 处理器首行插 `return;` | `F7` 必须红；**当前实测 46/46 绿** | E-2 |
| **R3** | fixture/生产装配补一条 `status:"cooldown", cooldown_remaining_ms:0` 的资源行，并加变异「cooldown 且剩余 0 → 归正为 active」 | 新增判据必须红；`C6` 的"剩余秒数"要有 0 值对照 | E-3 + `/tmp/ix4_probe.py` A/B/F |
| **R4** | 把 `verify_v2_frontend.mjs:317-319` 的 `red = mut.kills`（抛错即算红）改为"抛错即判该变异无效"，并让 `A12` 以不抛错的方式证红 | 37/37 仍成立且**无一例走推定分支** | 实测 `[抛错 TypeError]` 1 例 |
| **R5** | 撤 `snapshot_by_resource` 的条目级 `disabled` 归并（把 `all(e.status != "active") → cooldown` 改成把 `disabled` 单列/优先） | S-2 关闭后必须**只有**新用例红；请新增一条「AUTH → `disable()` → 快照不得为 `cooldown`、`remaining` 不得为 0」的判据（当前 pytest 全集里**没有**这条，`test_v2_circuit.py:241-262` 只手工把 `status` 设成 `"cooldown"` 再断 `remaining >= 0`，是**恒真式**） | §2 表 1 + R5 说明 |
| **R6** | 撤 `cli_zcode.py:268` 熔断分支的 `_ack_failures()`（或改为仅在打印过失败明细后 ack） | 当前**零判据**（我实测到 `POST /admin/api/ops/ack` 在熔断空跑轮发生）→ 请先补判据再撤 | M-3 |
| **R7** | 撤 `main.py:134/140` 的 `write_report`，或给 CLI 路径补落盘 | M-4：需要一条「CLI 一轮失败 → `ops-results-*.jsonl` 至少 1 行」或把红点文案改成"仅网关调度轮次落盘"的判据；当前两者皆无 | M-4 + `find data -name "ops-results*"` 为空 |
| **R8** | 撤 `cli_setup.py:120-121` 的指路子句（`到「模型资源」页为它们添加映射`） | 当前只有"条数"判据、无文案分因判据 → 按 M-5 分「无映射 / 开关关闭 / 凭据失效」三因后各钉一句 | 实测 `m-mapped-but-off` |
| **R9** | 撤 `sync_circuit` 的 `if n:`（改为 0 也必须留痕）+ 账号名不匹配场景 | 需新增「资源备注 ≠ 账号名 → 启动必须有可见信号（日志或横幅）」的判据 | M-6 |
| **R10** | 撤 `quota.py:407` 的 `enter()` 文案 `，至 HH:MM` / 撤 `circuit_path()` 打印 | 账本 §二 5a 记 4 条红 —— **请复跑并附 `pytest -k "recovery_clock or breaker" -q` 输出**，我未逐条复跑 | 账本自述，未复现 |

---

## 6. 未验证清单（本轮面板说出口的盲区）

1. **真实浏览器渲染与像素**：Chrome 在本沙箱会挂（未尝试截图）→ 双主题并排观感、`剩余 0s` title 是否真能 hover 出来、`.ellip` 截断后 `last_error` 可读性、红点在 5 个顶栏元素里的挤占，全部**未验证**。
2. **`:8300` 上的真界面**：该实例是用户 5.1 天前起的**旧构建**（`/admin/api/status` 无 `ops_failed_unread`、`/admin/api/overview` 无 `warnings`/`last_error`）；按安全约束我未重启、未 POST → **本轮改动没有一次经真实浏览器与真实服务同框验证**。
3. **`mgw zcode claim` 未对真实上游/真实账号根跑过**：全部 CLI 证据来自 `model_gateway.cli.main([...])` 在 `/tmp` 隔离账号根 + `MGW_ZCODE_ACCOUNTS` + 熔断文件重定向下的执行，且 `_ack_failures` 走的 `admin_post` 被我换成记录器（避免清用户红点）。真实账号下的 detail 文本（例如 `剩余约 X 分钟`）未观测。
4. **cron → 红点亮 → 点击清零的端到端**：未跑（需向 8300 POST）。红点的**跨进程一致性**（CLI ack 后界面 5s 内是否必回隐）未观测。
5. **`ops-results-*.jsonl` 的真实存在性**：当前仓库 `data/usage/` 下**没有**该文件（`find` 空）→ M-4 的"CLI 不落盘"结论有代码级证据（唯一两个调用点在 `main.py`），但"网关调度轮次确实会落盘"未在真实运行里观测。
6. **账本 §二 其余红证行**（额度模型、`rebuild()` 接线、`CaptchaUnavailable`、`TMPDIR` 锁目录、`tool_call` 覆写）：属 PM/eng 覆盖面，我只跑了交互相关的 5 个测试文件（48 passed）与前端门两模式，**未逐条复跑**。
7. **无 `node` 环境下的门行为**（账本 G3）：本机 `node v24.18.0` 可用，skip 分支未验证；`mgw` console script 是否真的装到用户 PATH 未验证（我全程用 `python -m model_gateway.cli`，这恰是红点文案给的兜底，已实测可用）。
8. **`--manual` 与熔断交叉**、**设备 ID 冲突退出码 4**（§15.1）：`--manual` 在熔断轮的行为由代码推断（`breakered` 与 `manual` 无交互），未实测。
