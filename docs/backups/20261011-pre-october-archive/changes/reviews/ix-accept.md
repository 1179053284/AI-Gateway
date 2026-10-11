# 交互与视觉实现验收报告 · tech-design v2.0 增量（§12–§21 / M3–M5）

> 角色：**资深交互与视觉设计师（B 端工具 / 开发者工具方向）** —— 第三角色，只挑问题，不盖章。
> 基准：`docs/specs/tech-design.md` **v2.0 §12–§21**（重点 §21 四处出口契约、§13.3 probe 交互契约、§16.2 四类结果呈现、§16.4 空跑语义、§15.1 硬约束 3、§12.4.1 写入纪律 0）
> 项目定位：**单用户 / 自用 / 开发者工具** —— 不按 SaaS 标准要求（不要求新手引导、多语言、移动端）。
> 纪律：只读，未修改任何项目文件。所有结论均附 `文件:行号`；可运行项均已实跑。

---

## 1. 验收结论

### **有条件通过**

**判据拆开看**：

| 维度 | 结论 | 依据 |
|---|---|---|
| §21 四处出口**接线** | ✅ 全部真实落地 | 独立复现 16/16（§2），四处出口在生产路径均有调用点，非死代码 |
| §21 四处出口**"用户看到后知道怎么办"** | ⚠️ 2 处不成立 | 出口② toast 指向的命令当前不可执行（`mgw` 未安装，IX-M3）；出口② 的红点信号**永久为真**（IX-M1）；claim 失败的**唯一**修复指引指向不存在的配置键（IX-S1） |
| CLI 交互质量 | ⚠️ 基本可用，6 处文案/呈现缺陷 | §3 |
| 既有前端规范一致性 | ✅ 遵守 | 复用 `.alert-warn`、双主题令牌齐全、`[hidden]` 陷阱已规避（§7） |
| 过度设计 | ✅ 未发现越界 | §6 |

**若按用户口径「完全通过才可以交付」判定 → 当前不满足**，需先满足 3 条硬条件（全部为**已由 PM/eng 提出、至今未修复**项，本报告在交互视角补充了"为什么它阻断交付"）：

| # | 硬条件 | 为什么它阻断"交互交付" |
|---|---|---|
| 1 | `claim.py:204` 的 `gateway.zcode.proxy` 改为**真实生效**的配置/参数入口（或实现该键） | 这是领取失败时**唯一**给用户的修复指引。指引无效 = 用户无路可走，出口③在"知道怎么办"这一维直接归零 |
| 2 | 红点计数提供 ack/清零出口（`mgw zcode claim` 成功后清零，或 `POST /admin/api/ops/ack`） | 一次失败后红点**永久常亮**，信号从此不可信 —— 违反 §21.3 原则 3「需要关注"与"正常状态"必须分开」的立意 |
| 3 | 无账号时 `mgw zcode claim` 不得输出「全部正常，无需处理」 | 新用户**第一次**执行该命令就会看到这句，而实际什么都没发生（§16.4 明确禁止） |

---

## 2. §21 四处出口逐条核对表

> 方法：读源码定位生产调用点 + 独立复现渲染（Node 执行 `dashboard.js` 的**真实源码**函数）+ 实跑 CLI。

| # | 契约（§21.2） | 实现落点 | 渲染/文案是否到位 | 用户知道怎么办吗 | 结论 |
|---|---|---|---|---|---|
| **1** | 零映射告警 → `overview.warnings[]` + 总览页 `.alert-warn` 横幅，**两类措辞不同** | `main.py:173-204`（`config_warnings`，两类 kind/message）<br>`api/admin.py:168`（`"warnings": runtime.config_warnings()`）<br>`dashboard.js:14`（渲染入口）+ `:71-79`（`configWarnings`）<br>`.alert-warn` 样式 `base.css:890`；启动日志双通道 `main.py:312-313` | ✅ 实跑渲染出 **2 条**横幅（`banners=2 warnings=2`）；两类 message 实测：<br>①`1 个系统模型未配置任何资源，调用将返回 503 —— 到「模型资源」页编辑资源添加映射（empty-model）`<br>②`1 个资源未被任何系统模型引用（孤儿资源）` | ✅ ① 含**修复入口**，且页名「模型资源」与侧栏 `index.html:38` 完全一致 | ✅ |
| **2** | 运营 `failed` → JSONL + `mgw zcode claim` 打印 + **顶栏红点** | JSONL：`ops/runner.py:204-219`，生产调用 `main.py:77`<br>CLI 打印：`cli_zcode.py:96-111`<br>红点：`admin.py:119-121`（`ops_failed_unread`）→ `main.js:94-115`（5s 轮询）→ `index.html:109-112`（`#ops-dot` + `#ops-dot-text`）→ `base.css:1112-1132` | ✅ 红点**有文案**：`运营失败 ${n}`（`main.js:102`）+ `title` 提示（`index.html:109`）+ **点击 toast 指路**（`main.js:110-112`）。方案未要求点击反馈，属**加分而非过度设计** | ⚠️ toast 文案「用 `mgw zcode claim` 查看详情」—— 但 `mgw` 当前**不在 PATH**（见 IX-M3）；且红点永不熄灭（IX-M1） | ⚠️ |
| **3** | 设备 ID 冲突 → CLI 打印 **3 个显式选项**，默认取消、退出码非 0 | `cli_zcode.py:77-86`（3 选项 + `return 4`）<br>`store.py:155-158`（默认拒绝、`conflict=True`）<br>`dataroot.py:119-135`（共用唯一性校验） | ✅ **实跑复现**（`MGW_ZCODE_ACCOUNTS=/tmp/...`）：<br>`设备 ID 冲突：账号「acct-b」的 device_id 已被账号「acct-a」占用。` + `① --reuse acct-a …` + `② --regenerate …` + `③ 取消（默认）`<br>**退出码 = 4**（非 0 ✅）；**未写盘**（目录内仍只有 `acct-a`，无 `acct-b` ✅） | ⚠️ 措辞本身可判断（① 与 ② 各带风险提示、③ 为默认）；但**未提示"重新执行本命令并加该参数"**，且不打印冲突的 device_id 值 | ⚠️ |
| **4** | `mgw setup` → **写前打印解析路径并确认** + `--dry-run` | `cli_setup.py:70-72`（打印目录+来源）<br>`:92`（打印将写入条数）<br>`:99-109`（确认 / 非交互需 `--yes`）<br>`:111-118`（写后打印 + 备份名 + 失败回滚提示）<br>`setup_tools.py:49-71`（解析规则）/`:127-209`（备份+合并+原子写+读回+回滚） | ✅ **实跑**：`目标目录：/Users/w/.workbuddy-ai` + `（来源：环境变量 WORKBUDDY_CONFIG_DIR）` + `将写入：models.json（7 条系统模型）`；`--dry-run` 只打印不落盘 | ⚠️ 路径**可判断**（打印了推导来源，正是方案点名的劫持场景）；但**未给出"合并 N 条已有条目"**（§12.4.1 文案要素，见 IX-L6） | ⚠️ |

**出口①②的独立复现记录（只读，未改任何文件）**：

```
$ .venv/bin/python -c "…调用 Runtime.config_warnings()…"   # 造两类告警的配置
[{kind: model_without_resource, message: "1 个系统模型未配置任何资源，调用将返回 503 —— 到「模型资源」页编辑资源添加映射（empty-model）"},
 {kind: resource_without_model,  message: "1 个资源未被任何系统模型引用（孤儿资源）"}]

$ node scripts/verify_v2_frontend.mjs /tmp/mg-ix-overview.json
  ✓ 渲染出 .alert-warn 横幅        ✓ 横幅含 503 措辞
  ✓ 横幅含「未被任何系统模型引用」  ✓ 两类告警各渲染一条  banners=2 warnings=2
  ✓ 空 warnings → 不渲染任何横幅   ✓ warnings 非数组 → 安全降级
  ✓ 存在 #ops-dot 元素            ✓ 默认 hidden（0 失败时不显示）
  ✓ 存在文案节点 #ops-dot-text     ✓ 轮询 /admin/api/status
  ✓ 读取 ops_failed_unread        ✓ 5s 轮询间隔   ✓ 页面隐藏时跳过轮询
  ✓ .ops-dot 样式存在             ✓ 用双主题令牌（--err / --err-bg）
实测 16 项，通过 16 项，失败 0 项
```

> **未验项（诚实标注）**：真实浏览器渲染未验 —— 沙箱内 headless Chrome 加载真实页面会挂住（E2E 已声明同一限制）；上表用 Node 执行 `dashboard.js` 的**同一份源码**函数替代。ZCode 真实凭据/上游不可达，`claim` 四类结果为**注入式复现**，非真实领取。

---

## 3. CLI 交互质量逐命令核对表

> 实跑入口：`.venv/bin/python -m model_gateway.cli`（`mgw` 当前不可用，见 IX-M3）。

| 命令 | 帮助信息 | 确认/进度/结果 | 空态 | 退出码 | 结论 |
|---|---|---|---|---|---|
| `mgw --help` | ✅ 三子命令各有中文一句话（`cli.py:29/37/44`） | — | ✅ 无子命令打印帮助 | ✅ 0（`cli.py:73-75`） | ✅ |
| `mgw probe --help` | ✅ 4 个参数均有说明（实测输出） | ✅ 执行前确认含**模型数 + 预计请求数 + 频控风险**（`cli_probe.py:89-90`）；✅ 逐模型即时打印（`:117/122`）；✅ 结束打印成功/失败计数 + 落盘路径（`:128`） | ✅「没有需要探测的模型（…用 --all 强制重探）」（`:85`） | ✅ 0/1（失败或取消）/2（配置或用法错） | ⚠️ 确认后到首个结果之间**无进度输出**（IX-L10） |
| `mgw setup <tool>` | ✅ 目标工具取值与可选值一致（实测 `workbuddy / workbuddy-ai`） | ✅ 破坏性操作**先打印后确认**（`cli_setup.py:70-72,99-109`）；✅ 写后打印绝对路径 + 备份名（`:113-115`）；✅ 回滚提示（`setup_tools.py:203-205`） | ✅ 未知产品列出可选值（实测 `✗ 未知产品 'trae'（可选：workbuddy, workbuddy-ai)`，退出 2） | ✅ 0 / 1（取消）/ 2（用法）/ 3（写失败） | ⚠️ 确认行缺"合并 N 条已有条目"（IX-L6） |
| `mgw zcode claim` | ✅ `--account` / `--manual` 有说明 | ✅ **分组呈现符合 §16.2**：`✓ 已领取 N 个` / `– 跳过 N 个（已领过 a / 无资格 b）` / `✗ 失败 …`；✅ 无失败时输出「全部正常，无需处理」（`cli_zcode.py:109-110`）；✅ 仅 `✗` 行着色（`:108`） | ❌ **无账号时输出「全部正常，无需处理」**（实测，IX-M2） | ✅ 0/1 | ❌ |
| `mgw zcode list` | ✅ | — | ✅「暂无已接入的 ZCode 账号（用 `mgw zcode login` 或 `mgw zcode import`）」（`:42`） | ✅ 0 | ⚠️ 表头 CJK 宽度未补偿 → 错位（IX-L2） |
| `mgw zcode import` | ✅ 三选项措辞与 `--reuse/--regenerate` help 一致（`cli.py:51-54`） | ✅ 冲突 3 选项 + 未写盘（实测） | ✅ 凭据不可用给出原因（`store.py:131`） | ✅ 0 / 1 / **4** | ⚠️ "账号已存在"提示把 `--reuse` 当"覆盖"用（IX-M5） |
| `mgw zcode login` | ✅ | ✅ 明说"浏览器将打开授权页"（`cli_zcode.py:52`） | — | ✅ 1（恒失败，stub，见 eng m3） | ⚠️ help 未标注"暂不可用"，用户会以为是环境问题（建议同 eng m3） |
| `mgw zcode`（无子命令） | ✅ 打印用法（`cli_zcode.py:19`） | — | — | ❌ **返回 0**（用法错误应为非 0，IX-L3） | ⚠️ |

---

## 4. 问题清单

### 🔴 严重

**IX-S1 · 领取失败时给用户的**唯一**修复指引指向一个不存在的配置键（交互死路）**
- 问题：`mgw zcode claim` 在无验证码求解器时抛出的文案是「未配置住宅代理，验证码求解不可用 —— 请在 config.yaml 的 `gateway.zcode.proxy` 填入住宅代理地址；也可 --manual 手动完成」（`upstream/zcode/claim.py:203-204`）。但 `GatewayConfig`（`config/schemas.py:46-55`）只有 `host/port/max_concurrent_requests/attempt_timeout_seconds/request_total_budget_seconds/heartbeat_seconds/retention_days/access_tokens`，**无 `zcode`、无 `proxy`**；全文件 `zcode|proxy` 零命中。且 `schemas.py` 未设 `extra="forbid"`（Pydantic v2 默认 `ignore`）→ 用户照做会被**静默丢弃**，问题不解决、也无任何报错。
- 证据：`claim.py:203-204`；`schemas.py:46-55`（无该键）；`schemas.py:1-24`（无 `model_config`）；测试把假键固化为正确：`tests/unit/test_v2_zcode_claim.py:132`（`assert "gateway.zcode.proxy" in msg`）。
- **交互视角补充（本报告与 eng-S3 / PM:117-120 的差异）**：这不是纯后端缺键 —— 它是用户失败后**唯一**被给出的修复路径。指引无效 ⇒ 出口③「用户知道怎么办吗」= **否**，且用户会反复照做、反复失败，属于 §21.1 所批判的"定义了状态、没定义用户看到什么"的同类错误。
- 建议：二选一 —— ① 在 `GatewayConfig` 增 `zcode: ZcodeConfig(proxy: str = "")` 并真正注入 `captcha_solver`；② 若本期不做求解器，文案改为指向**真实生效**的路径（如「本期未实现自动求解；请用 `--manual`（需先完成 §16.5 外部依赖）」），并**同步改测试断言**。

### 🟡 中等

**IX-M1 · 顶栏红点只增不减 → 一次失败后永久常亮（信号自我失效）**
- 问题：`bump_failed_counter`（`ops/runner.py:222-230`）只做累加，全仓**无清零/ack 出口**（`main.py:106` 初值 0 之外，仅 `runner.py:229` 一处赋值）；`main.py:105` 注释称"用户在 CLI 查看后清零"，但 `cli_zcode._claim`（`cli_zcode.py:91-111`）并未清零。
- 证据：`runner.py:222-230`、`admin.py:121`、`main.js:100-106`、`main.py:105`（注释与实现不符）。
- **交互视角补充**：§21.3 原则 3 要求"需要关注"必须与"正常状态"分开呈现，其**前提**是这个信号可信。永久常亮后用户会在 1–2 天内学会忽略顶栏红点 —— 出口②的呈现投入（文案/tooltip/点击反馈）全部作废。
- 建议：提供 ack 出口（`mgw zcode claim` 成功后清零 + `POST /admin/api/ops/ack`），并把累加语义改为"最近 N 分钟失败数"或"未确认失败数"。

**IX-M2 · 无账号时 `mgw zcode claim` 输出「全部正常，无需处理」且退出 0**
- 问题：`run_once` 对 `accounts == []` 直接 `return report`（`ops/runner.py:176-178`，空报告）；`cli_zcode.py:109-110` 对空报告打印「全部正常，无需处理」并 `return 0`。与 §16.4 情形②「`N=0` → 记 `inactive` 并输出「无账号参与」（**不得报 `success`**）」（`tech-design.md:1149`）直接冲突。
- 证据（实跑）：
  ```
  $ .venv/bin/python -m model_gateway.cli zcode claim      # 无任何账号
  全部正常，无需处理
  EXIT=0
  ```
- 根因：`OpReport.all_normal`（`ops/base.py:58-60`）定义为 `not self.failed` → **空报告也是"全部正常"**；CLI 以 `if not report.failed` 直接判定（`cli_zcode.py:109`）。
- **交互视角补充**：这是**新用户第一次**执行该命令就会看到的输出 —— "什么都没做"却被告知"全部正常"，直接误导（用户会以为领取成功）。§16.4 明文禁止此路径。另外 `report.skipped`（未参与，`ops/base.py:41-42`）在 CLI **完全没有呈现出口**。
- 建议：`N=0` 时输出「无账号参与（先 `mgw zcode import`）」并返回非 0（或至少不要报"全部正常"）；同步修正 `tests/unit/test_v2_ops.py:101-108`（`assert report.inactive == []` + `assert report.all_normal is True`，与其自身 docstring「`N=0` → `inactive`」矛盾）把错误行为固化的断言。

**IX-M3 · 出口② toast 指向的命令当前不可执行，且 README 无 CLI 章节**
- 问题：`main.js:111` 的 toast 文案为「运营任务有失败，用 `mgw zcode claim` 查看详情」，`cli.py:9/29/37/44` 的帮助也一律写 `mgw`；但本机 `command -v mgw` → **NOT FOUND**，`.venv/bin/mgw` **不存在**（`pyproject.toml:25-26` 已声明 `[project.scripts]`，只是 venv 未重装）。同时 `README.md` 中 `mgw`/CLI/命令行/probe/setup **零命中**（仅 `:60` 有 `pip install -e .`）。
- 证据：`command -v mgw` = NOT FOUND；`ls .venv/bin/mgw` 不存在；`pyproject.toml:25-26`；`README.md`（141 行）无 CLI 内容；`main.js:111`。
- **交互视角补充**：出口②的完整链路是"红点 → 点击 → 告诉你去哪看"。最后一步落地为 `zsh: command not found: mgw`。这正是 §21.3 原则 1「'写进日志' ≠ '用户看到'」的同类问题：**"文案说了去哪" ≠ "用户真能到"**。
- 建议：README 增一节 CLI（`mgw probe` / `mgw setup` / `mgw zcode`）+ 明示需 `pip install -e .` 才会注册 `mgw`；或 toast 文案改为当前必然可用的形态（如 `python -m model_gateway.cli zcode claim`）。E2E `:171` 已承认"或安装后"，但**用户可见文案没有这层兜底**。

**IX-M4 · `--manual` 是误导性开关：help 承诺"手动完成验证码"，实现无任何手动环节**
- 问题：`cli.py:57-58` 的 help 写「未配置住宅代理时，手动完成验证码」；但实现路径 `ops/builtin/zcode_claim.py:80-83` 在 `manual=True` 时仅把错误包装成 `OpResult(failed, "需手动完成验证码：{e}")`，**没有任何让用户输入验证码参数的交互**。更矛盾的是：用户**已经加了 `--manual`**，得到的文案里仍写着「也可 --manual 手动完成」（`claim.py:203-204`）。
- 证据：`cli.py:57-58`；`zcode_claim.py:80-83`；`claim.py:200-205`；`ops/runner.py:190`（`manual` 仅透传）。
- 建议：二选一 —— ① help 改为「无住宅代理时的降级：仅给出明确失败原因（不实现手动过码）」；② 真正实现手动环节（打印需用户完成的步骤/接受用户粘贴的 `verify-param`）。并去掉失败文案里"也可 --manual"这句自指。

**IX-M5 · "账号已存在"提示把设备 ID 语义的参数当"覆盖"用，且照抄提示会报错**
- 问题：`store.py:138-139` 在目标账号已存在且未传 `reuse/regenerate` 时返回 `message="账号『X』已存在（用 --reuse/--regenerate 覆盖）"`，CLI 原样打印（`cli_zcode.py:87`）。但这两个参数在 `cli.py:51-54` 与 `§15.1` 中的语义是**设备 ID 冲突处置**（复用设备 / 重生成设备），不是"覆盖账号"。且 `--reuse` **必须带 ACCOUNT 参数** —— 用户照抄提示会得到 argparse 报错。
- 证据（实跑两段）：
  ```
  $ … zcode import dup-name.json
  ✗ 导入失败：账号『acct-a』已存在（用 --reuse/--regenerate 覆盖）
  EXIT=1

  $ … zcode import dup-name.json --reuse
  mgw zcode import: error: argument --reuse: expected one argument
  ```
  源码：`store.py:138-139`、`cli_zcode.py:87`、`cli.py:51-54`。
- **交互视角补充**：同一 flag 承担"设备冲突处置"与"覆盖已存在账号"两种语义，且**覆盖场景下会静默改写已有账号目录**（`store.py:138` 守卫被 `reuse` 绕过 → `_commit` 覆盖 `meta.json`）。这是"提示让用户困惑 + 危险语义被同一开关承载"的双重问题。
- 建议：把"覆盖已存在账号"拆为独立参数（如 `--overwrite`）并在提示中写全（`--reuse <账号名>`）；"账号已存在"的提示改为「用 `--overwrite` 覆盖，或改名后重试」。

### 🔵 轻微

| # | 问题 | 证据 | 建议 |
|---|---|---|---|
| IX-L1 | `claim` 多失败时「✗ 失败 N 个：」前缀**逐行重复**（3 个失败 → 3 行各写"失败 3 个"），与 §16.2 的单行汇总示例不符 | `cli_zcode.py:106-108`（`print` 在 `for` 内）；实跑：`✗ 失败 3 个：acct-b …` / `✗ 失败 3 个：acct-c …` / `✗ 失败 3 个：acct-d …` | 汇总行只打一次，明细行改为 `  ✗ acct-b  验证码求解超时` |
| IX-L2 | `zcode list` 表头 CJK 宽度未补偿 → 表头每列比数据行宽 2 显示列，逐列右偏 | `cli_zcode.py:44-46`；实测表头列宽 22/40/16 vs 数据列宽 20/38/14 | 用 `wcwidth` 或手工补偿（表头改 ASCII 亦可） |
| IX-L3 | 用法错误返回 0：`mgw`（无子命令）、`mgw zcode`（无子命令）均 `return 0` | `cli.py:73-75`、`cli_zcode.py:18-20`；测试亦固化 `test_v2_cli.py:59/71` | 用法错误返回 2（与其他子命令口径一致） |
| IX-L4 | 两类告警同为 `.alert-warn`（橙）+ 同标题「配置告警」→ 与 §21.3 原则 3「正常业务状态与需要关注分开」不符：②"资源未被引用"是**配置冗余非故障**，却与 ①"调用将返回 503"同权重 | `main.py:187-203`（两类 kind）、`dashboard.js:75-76`（固定 `.alert-warn` + 固定标题）、`base.css:890/896`、`tech-design.md:1471` | ② 改用既有 `.alert-info`（`base.css:896`）或标题区分（「配置告警」/「配置提示」） |
| IX-L5 | `--config` 只作用于 `config.yaml`：方言表/枚举池仍固定读 `data/`（CWD 相对）→ 传 `--config` 时"读 A 写 B" | `cli_probe.py:56/65/127`、`cli_setup.py:55/84-85`（`from model_gateway.main import DIALECTS_PATH, ENUMS_PATH`） | 由 config 路径推导同级 `data/`，或 help 注明"仅 config.yaml 生效" |
| IX-L6 | `mgw setup` 确认行未给「合并 N 条已有条目」（§12.4.1 的确认文案要素）；该数在**确认之后**才算出 | `cli_setup.py:92`（只打模型条数）vs `tech-design.md:834`；`merge_models` 仅在 `write_models_json` 内调用（`setup_tools.py:154`） | 确认前先读一次目标文件，打印「将写入 models.json（新增 N / 保留 M）」 |
| IX-L7 | `.ops-dot` 设 `cursor: default`，但元素**可点击**（有 toast 反馈）→ 可点性无可视提示 | `base.css:1123`（`cursor: default`）、`main.js:110-112`（click → toast） | 改 `cursor: pointer`（或加 `:hover` 底色反馈） |
| IX-L8 | `✗` 行着色硬编码 `\033[31m`，无 TTY 检测 → 重定向/管道时把 ANSI 码写进文件 | `cli_zcode.py:108` | 用 `sys.stdout.isatty()` 门控；并改用设计令牌对应的色值而非裸码 |
| IX-L9 | 方案 §21.2 称"顶栏 5s 轮询**存在**（`不新建轮询`）"—— 实测前端此前**无**该轮询，本次新增 `setInterval`（端点确实复用，功能无问题，属**方案成本口径**偏差） | `git diff HEAD -- model_gateway/web/static/js/main.js`（`:89-116` 整块为 `+`）；`main.js:113-114`；`design-spec.md:181` 是设计文档而非实现 | 无需改代码；更新 §21.2 的成本描述，避免"代价评估已核实"误导后续审核 |
| IX-L10 | `mgw probe` 确认后到首个结果之间**无任何进度输出**（单模型最长 6 次请求 + 1.5s 间隔）→ 用户可能误以为卡住 | `cli_probe.py:105-125`、`probe.py:110-139` | 每个模型开探前打一行 `… 正在探测 <model>` |

> **范围外发现（非 IX 维度，供 eng 复核，仅记一行）**：`run_once(..., enabled_of=…)`（`ops/runner.py:167-174`，§16.4「运营类跳过 `enabled=false` 账号」的唯一落点）在**两个生产入口都未传入** —— cron `main.py:76` 与 CLI `cli_zcode.py:95` 均只传 `accounts`/`manual`；`_maybe_start_ops`（`main.py:63-68`）也只看"有无账号"、不看 `enabled`。→ 停用账号仍会被自动领取，且 `enabled_of` 实际为死参数。

---

## 5. 用户可见信息一致性专项

| 检查项 | 结论 | 证据 |
|---|---|---|
| 页名一致性（告警文案 → 导航） | ✅ 「模型资源」与侧栏 `data-page="resources"` 文案完全一致 | `main.py:190` vs `index.html:38` |
| 术语统一（资源 / 模型 / 账号） | ✅ 未发现混用：告警用"系统模型""资源"；红点用"运营失败"；CLI 用"账号" | `main.py:189/201`、`main.js:102`、`cli_zcode.py:44-46` |
| 红点文案 ↔ CLI 文案 | ⚠️ 一致（都指 `mgw zcode claim`），但该命令当前不可执行 | `main.js:111`、`index.html:109` |
| 错误提示是否告诉用户"怎么办" | ⚠️ 多数有（`setup` 未知产品列可选值、`list` 空态给下一步、`probe` 空态给 `--all`）；**关键失败路径失效**（IX-S1 指向不存在的键；IX-M4 自指 `--manual`；IX-M5 照抄会报错） | 见对应条目 |
| 退出码语义 | ⚠️ 成功 0 / 失败非 0 基本成立（probe 0/1/2、setup 0/1/2/3、import 0/1/**4**）；例外：无子命令返回 0（IX-L3） | `cli.py:73-75`、`cli_zcode.py:18-20`、`:86`、`cli_setup.py:118` |
| `gateway.zcode.proxy` 键真实性（用户点名核查） | ❌ **不存在**（`schemas.py` 全文 `zcode`/`proxy` 零命中）；`MGW_ZCODE_PROXY` 亦零命中 | `schemas.py:46-55`；`claim.py:204`；`tests/unit/test_v2_zcode_claim.py:132` |

---

## 6. 过度设计专项

| 检查 | 结论 | 证据 |
|---|---|---|
| "做了 UI 但没人用" | ✅ 未发现。红点有真实数据源（`admin.py:121` ← `runner.py:229` ← `main.py:78`），横幅有真实数据源（`admin.py:168` ← `main.py:173`） | — |
| 是否新建页面/端点/轮询 | ✅ 未新建页面；✅ 未新建端点（复用 `/admin/api/status`）；⚠️ 前端**新建了一个 5s 轮询**（方案声称复用，见 IX-L9） | `main.js:94-115` |
| 红点是否超出方案（点 + 文案 + tooltip + 点击反馈） | ✅ 属**合理增强**：方案只要求"红点"，实现给了文案与出口指引；4 处代码、零新组件 | `index.html:109-112`、`main.js:102/110-112` |
| 是否自造样式 | ✅ 未自造：横幅复用既有 `.alert`/`.alert-warn`/`.alert-title`（另一处既有用法 `templates.js:171-172`）；红点仅 1 个小类（21 行） | `dashboard.js:75-76`、`base.css:1112-1132` |
| 单用户定位是否被按 SaaS 标准要求 | ✅ 未越界（无引导、无多语言、无移动端适配；红点仅 1 处、无通知中心） | `main.js:89-115` |
| `--manual` 开关 | ❌ 属**反向过度设计**：加了参数与 help 文案，却没有对应的交互实现（IX-M4） | `cli.py:57-58`、`zcode_claim.py:80-83` |
| 该给的反馈是否给了 | ⚠️ 3 处缺失：`probe` 单模型无"进行中"（IX-L10）、`setup` 确认前无合并影响（IX-L6）、`claim` 无账号时给假成功（IX-M2） | 见对应条目 |

> **范围说明（避免误判）**：`templates.js` 与 9 个 `templates/*.html`、侧栏「模板预览 / 需求预演」分组虽在工作区未提交，但文件 mtime 为 **09-23 / 09-24**，早于本次 M3–M5（09-26），**不属本次交付**，故不计入过度设计（与 `PM-accept.md:147-148,200` 一致）。

---

## 7. 明确无问题的部分（做对了）

1. **出口① 的"用户看到"链路真的打通**：接口出口（`admin.py:168`）→ 渲染（`dashboard.js:14`）→ 组件（`base.css:890`）三处均有生产调用点，实跑渲染 2 条横幅；启动日志双通道（`main.py:312-313`）与方案一致。
2. **告警文案含修复入口且页名与导航一致**（`main.py:190` ↔ `index.html:38`）—— 这是"用户知道怎么办"的正面案例。
3. **两类告警措辞确实不同**（实跑两条 message 语义清晰：故障型带 503 后果 + 修复入口；冗余型只陈述事实，不误报为故障）。
4. **红点默认隐藏且正确规避 `[hidden]` 陷阱**：`.ops-dot{display:inline-flex}` 与 `[hidden]` 的冲突被显式处理（`base.css:1125` `.ops-dot[hidden]{display:none}`）—— 这是常见且易漏的坑，实现方处理正确。
5. **红点用双主题令牌**：`--err-bg` / `--err` / `--border` / `--text` 在浅色（`base.css:22-23`）与深色（`:58-59`）均有定义，无硬编码色值。
6. **红点只在页面可见时轮询**（`main.js:97`），隐藏标签页不打扰。
7. **出口③ 的硬约束 3 完整落地**：实跑验证 —— 打印 3 个显式选项、**默认取消**、**退出码 4**、**未写盘**（目录内无 `acct-b`）。这是四处出口中"契约与实现最贴合"的一处。
8. **出口④ 的写入纪律 0 落地**：写前打印目标目录**及其推导来源**（实测在环境变量劫持场景下正确显示 `/Users/w/.workbuddy-ai` + `来源：环境变量 WORKBUDDY_CONFIG_DIR`）；`--dry-run` 不落盘；非交互强制 `--yes`；写后打印备份名；失败回滚有明确文案。
9. **`claim` 四类结果的分组呈现符合 §16.2**（✓ / – / ✗ 三段，`already_done` 与 `inactive` 合并为"跳过"一行，仅 `✗` 着色，无失败时输出「全部正常，无需处理」）—— 仅多失败时的计数前缀重复（IX-L1）。
10. **`esc()` 转义到位**（`dashboard.js:77`），空数组/非数组输入安全降级（`:72-73`，Node 校验通过）。
11. **空态均给可执行下一步**：`zcode list`（`cli_zcode.py:42`）、`probe`（`cli_probe.py:85`）、`setup` 未知产品（`cli_setup.py:59`）。
12. **与既有前端规范一致**：复用 `.alert` 组件族（`frontend-spec.md:473` 同口径，非自造样式）；`.ops-dot` 未违反 `frontend-spec.md:480` 的"顶栏右恰好 1 个动作按钮（C16）"—— 该条约束的对象是**模板页页头**，控制台顶栏不在其约束范围内。

---

## 8. 复跑方式（只读）

```bash
cd /Users/w/Desktop/Model-Gateway
.venv/bin/python -m model_gateway.cli --help                 # CLI 入口
.venv/bin/python -m model_gateway.cli zcode claim             # IX-M2（无账号时的假成功）
.venv/bin/python -m model_gateway.cli zcode list              # IX-L2（表头错位）
node scripts/verify_v2_frontend.mjs <overview.json>           # 出口①② 渲染校验（16/16）
# 出口③：MGW_ZCODE_ACCOUNTS=<临时目录> … zcode import <冲突凭据>  → 退出码 4、未写盘
```
