# 交互与视觉实现验收报告（第二轮）· v2.0 收敛后 · Q28 四处出口 + 两类新告警

> 角色：**资深交互与视觉设计师（B 端工具 / 开发者工具方向）** —— 第三角色，只挑问题，不盖章。
> 基准：`docs/specs/tech-design.md` v2.0 **§21 / §15.1 / §16.2 / §16.4 / §16.5 / §12.4.1 纪律 0 / §13.3 / §14.1**；
> `docs/specs/prd.md` v1.15 **Q28**（② 只下发可服务模型且隐藏必说明 / ③ 推理优先级定序 / ④ 跨进程出口）；
> `docs/specs/frontend-spec.md` / `design-spec.md`；上轮报告 `docs/changes/reviews/ix-accept.md`；
> 本轮被审账本 `docs/changes/e2e-records/E2E-20260927-v2-round2-fixes.md`。
> 日期：2026-09-27。纪律：除本报告外**零文件修改**；临时数据全部在 `/tmp`；未碰 `~/.zcode` / `~/.workbuddy` / `~/.workbuddy-ai`（仅 `~/.workbuddy/models.json` **只读** 用于 dry-run）；未向任何真实上游发请求。

---

## 1. 验收结论

### **有条件通过**（阻断项 1 个 · S-1）

| 维度 | 结论 | 依据 |
|---|---|---|
| §21 四处出口 + Q28 两类新告警**接线与渲染** | ✅ 全部真实落地，端到端复现 | 后端 9/9 + 前端 18/18 **独立复跑通过**（§6）；四类告警实跑渲染 4 条横幅 |
| 出口① 横幅「看得到、知道怎么办」 | ⚠️ 2 处指路失真 | M-2（④ 不点名系统模型）、M-3（③ 把「启用资源」指到没有该开关的页） |
| 出口② 运营失败（CLI 打印 / 红点 / ack） | ✅ 呈现与清零闭环 | 实跑失败行渲染符合 §16.2；`/admin/api/ops/ack` + 点击清零 + CLI 查看后自动 ack（`admin.py:379-390`、`main.js:110-116`、`cli_zcode.py:250,258-266`）——**上轮 IX-M1 已修** |
| 出口② 的「失败后唯一修复指引」 | ❌ **仍是死路（新形态）** | S-1：配好 `gateway.zcode.proxy` 照样失败，且文案**谎称「未配置住宅代理」**（实跑证明，§3.7） |
| 出口③ 设备 ID 冲突契约 | ✅ 逐字符合 §15.1 | 实跑：3 显式选项 / 默认取消 / **exit 4** / 未写盘（§3.3） |
| 出口④ `mgw setup` 纪律 0 | ✅ 主体到位，2 处残留 | 目录+来源置顶打印（劫持场景实跑显示「来源：环境变量 WORKBUDDY_CONFIG_DIR」）；`--dry-run` 不落盘；M-4/L-11 |
| 两路径（`/v1/models` vs `mgw setup`）判据一致 | ❌ **运行态维度不一致** | M-1：资源被运行态判 invalid 后，API 隐藏、setup 仍下发（**实跑复现差异集**） |
| CLI 交互质量 | ✅ 大幅改善 | 上轮 IX-M2/L1/L2 均已修并实跑确认；残留见 轻微清单 |
| 前端规范 / 无新页面 / 无新轮询 / `[hidden]` / 双主题 | ✅ 合规 | 复用 `.alert-warn`（`base.css:890`）、`.ops-dot[hidden]`（`:1125`）、`--err/--err-bg` 令牌；红点复用既有 5s 轮询 |
| 本轮账本诚实性 | ⚠️ 一处口径失实 | N4 把「求解器未接线」写成「外部依赖未实测」（S-1 证据）；§5.3「新增面 1 端点」与本轮 ack/reload 归属需澄清（非阻断，账本 §二 R 项已如实记载） |

**交付判定**：S-1 不关闭，「看到发生了什么并知道下一步」在**领取失败**这一条用户路径上不成立（指引本身还会对用户当前的配置状态说谎），按上轮同等口径属阻断。其余为有条件项，可与二期一并处理。

---

## 2. 逐出口核对表

### 出口① 配置告警横幅（本轮扩至**四类**）

| 检查项 | 结论 | 证据 |
|---|---|---|
| 四类都真实渲染 | ✅ | 实跑 `ui_verify_v2_visible.py`：`banners=4 warnings=4`，kind 集合与 Q28 一致（§6 粘贴输出） |
| 措辞可被非作者理解 | ✅ 大体可 | 四条 message 实跑原文见 §6；① 带后果（503）+ 修复入口；③ 说明「隐藏」因果 |
| 指路的页名存在于侧栏 | ✅ 页名全部存在 | 「模型资源」`index.html:38`、「资源池设置」`:42`、「API 接入」`:60` |
| 指路的**动作在该页可做** | ❌ ③ 不成立 | 「到『资源池设置』页启用资源」——该页池行只有 档位/上下移/移除映射（`models.js:329-363`），资源启用开关在「模型资源」页（`resources.js:233,327-329,447-449`）→ **M-3** |
| ④ 可操作性（哪条映射赢了哪个值） | ⚠️ 不点名系统模型、不给两侧值 | 实跑原文：`1 个模型的参数卡字段会被资源级推理默认覆盖：reasoning_effort（资源D→vm-d）（生效序 请求级 > 资源级默认 > 参数卡，PRD FR-3.16）`——用户须自行反查「资源D+vm-d」属于哪个模型 → **M-2** |
| 隐藏模型告警会被误读为服务中断吗 | ✅ 不会 | ③ 主语是「资源映射全部不可用（已停用或凭据失效）」，因果指向配置而非平台；① 用将来时「调用将返回 503」 |
| 长消息溢出 | ✅ 无风险（CSS 推断） | `.alert` 为块级 + `line-height:1.6` 自动换行（`base.css:874-883`），无 max-height；**浏览器实测未做**（headless 限制，§8） |
| 4 条同时出现 | ⚠️ 可接受但权重不分 | 同标题「配置告警」+ 同橙色 `.alert-warn`（`dashboard.js:74-78`）；②冗余/④提示 与 ①③故障 同权重，与 §21.3 原则 3 相悖（上轮 IX-L4 家族，本轮扩为四类后更明显）→ 建议 ②④ 走既有 `.alert-info`（`base.css:896`）→ **轻微 L-6'**（并入 §5 轻微） |
| 双通道（启动日志） | ✅ | 实跑脚本输出前置 4 行 `[配置告警]`（§6） |

### 出口② 运营失败（CLI 打印 + 红点 + ack）

| 检查项 | 结论 | 证据 |
|---|---|---|
| `N=0` 不得报 success（§16.4 ②） | ✅ **已修**（上轮 IX-M2） | 实跑：`无账号参与 —— 尚未接入任何 ZCode 账号。` + **EXIT=2**（§3.2）；实现 `runner.py:266-270`、`cli_zcode.py:227-230` |
| 分组呈现 / 仅 ✗ 着色 / 前缀只打一次（§16.2） | ✅ 已修（上轮 IX-L1） | 实跑单行前缀 + 缩进明细（§3.6）；`cli_zcode.py:245-251` |
| 红点只增不减（上轮 IX-M1） | ✅ 已修 | ack 端点 `admin.py:379-390`；点击即确认 `main.js:110-116`；CLI 查看后自动 ack `cli_zcode.py:250,254,258-266`；网关未运行静默跳过（`local_admin.py:43-44`，实跑 §3.6） |
| 风控熔断跨进程回写（Q28-④） | ✅ 接线 | `/admin/api/zcode/bench`（`admin.py:393-412`）+ `_maybe_bench` 两腿分流（`zcode_claim.py:98-111`）；**真实凭据端到端未测**（N2，账本自述，本轮同样未测） |
| 失败行内的修复指引 | ❌ **死路（S-1）** | 见 §3.7 实跑：配了 proxy 仍报「未配置住宅代理」；生产 `captcha_solver` 恒为 `None`（`zcode_claim.py:127-129` 构造不传求解器；全仓除 docstring 外零 `playwright` 命中） |
| 「详情用 mgw zcode claim 查看」语义 | ⚠️ | 该命令是**重新执行领取**（有上游副作用），不是查看历史；历史在 `data/usage/ops-results-<date>.jsonl`（`runner.py:297-312`），文案未指路 → **M-5** |

### 出口③ 设备 ID 冲突（§15.1）

实跑全中（§3.3）：三选项逐字符合契约（含 ① 带账号名 `--reuse acct-a`）、默认取消、**exit 4**、目录内无 `acct-b`（未写盘）。`--regenerate` 分支实跑可用（§3.3）。**遗留**：上轮 IX-M5（「账号已存在（用 --reuse/--regenerate 覆盖）」语义混用 + 照抄 `--reuse` 报 argparse 错）**本轮未修亦未声称修**，实跑复现（§3.4）。

### 出口④ `mgw setup`（§12.4.1 纪律 0）

| 检查项 | 结论 | 证据 |
|---|---|---|
| 写前打印解析路径 + 来源 | ✅ 且足够醒目（前两行置顶） | 实跑：`目标目录：/tmp/ix-wb` + `（来源：环境变量 WORKBUDDY_CONFIG_DIR）`（§3.8）——正是劫持场景；无环境变量时来源显示「产品标识 → dataFolderName」 |
| 子串判断禁令（Q25-⑨） | ✅ | `workbuddy-ai → ~/.workbuddy-ai` 正确（实跑 `resolve_target_dir`，§3.8） |
| `--dry-run` 只打印 | ✅ | 全程 dry-run 验证；未触碰真实 `models.json` 写 |
| 确认 + 非交互 `--yes` | ✅ | `cli_setup.py:111-114` |
| 确认行含「合并 N 条已有条目」 | ⚠️ 仍缺 | 确认行只报模型数（`cli_setup.py:104`）；合并数只在 dry-run 结果行 / 写后结果行出现（`setup_tools.py:157-160,209`）→ **L-11**（§12.4.1 文案要素字面残留） |
| 跳过数 + 原因 | ✅ 数量有，**原因一刀切** | 实跑：`已跳过 2 个无可用资源的模型（no-res-model、disabled-res-model）—— 到「模型资源」页为它们添加映射`——对「有映射但资源被停用」的模型，「添加映射」是错的处方 → **M-4** |

### 跨进程出口（Q28-④）其余两项

方言表重载端点 `/admin/api/dialects/reload`（`admin.py:365-376`）+ probe 结束后调用（`cli_probe.py:128`）✅；运营调度**先等一个周期再 tick**（`runner.py:377-383`）✅（账本「顺带发现 1」属实）。

---

## 3. CLI 实跑记录（全部临时目录，逐条原样粘贴）

### 3.1 `zcode list`（空账号目录）
```
$ cd /Users/w/Desktop/Model-Gateway && MGW_ZCODE_ACCOUNTS=/tmp/ix-acc .venv/bin/python -m model_gateway.cli zcode list
暂无已接入的 ZCode 账号。
  接入方式：`mgw zcode login`（浏览器授权）或 `mgw zcode import <凭据.json>`
EXIT=0
```

### 3.2 `zcode claim` 零账号（上轮 IX-M2 复验）
```
$ MGW_ZCODE_ACCOUNTS=/tmp/ix-acc .venv/bin/python -m model_gateway.cli zcode claim
无账号参与 —— 尚未接入任何 ZCode 账号。
  先 `mgw zcode login` 或 `mgw zcode import <凭据.json>` 接入账号。
EXIT=2
```
✅ 不再出现「全部正常，无需处理」；非 0 退出符合 §16.4 ②。⚠️ 但 `mgw` 本机不可执行（§3.9），指路只有 mgw 形态 → M-5。

### 3.3 `zcode import` 设备 ID 冲突（同 `device_mid` 两份 payload）
```
$ … zcode import /tmp/ix-payload-a.json
✓ 已导入账号 acct-a（设备 ID MID-SAME-0001）
EXIT=0

$ … zcode import /tmp/ix-payload-b.json          # 同一 MID-SAME-0001
设备 ID 冲突：账号「acct-b」的 device_id 已被账号「acct-a」占用。
可选：
  ① --reuse acct-a    复用该设备 ID（两者共享设备，上游可能风控）
  ② --regenerate     为本账号生成新 ID（上游会视为换设备）
  ③ 取消（默认）
EXIT=4
$ ls /tmp/ix-acc/
acct-a                                            # ← 未写盘 ✅

$ … zcode import /tmp/ix-payload-b.json --regenerate
✓ 已导入账号 acct-b（设备 ID 69b5d8b0-e9ca-4e9e-8ef5-cb1088adefb3）
EXIT=0
```

### 3.4 重名导入提示（上轮 IX-M5 **残留**，实跑复现）
```
$ … zcode import /tmp/ix-payload-a.json
✗ 导入失败：账号『acct-a』已存在（用 --reuse/--regenerate 覆盖）
EXIT=1

$ … zcode import /tmp/ix-payload-a.json --reuse        # 照抄提示
mgw zcode import: error: argument --reuse: expected one argument
EXIT=2
```
`store.py:139`；设备 ID 语义参数被写成「覆盖账号」，且照抄即报错——**中等（未修未声称）**。

### 3.5 `zcode remove`（本轮新增，全路径实跑）
```
$ … zcode remove acct-b            # 非交互、无 --yes
将删除账号『acct-b』的本地数据根：
    /tmp/ix-acc/acct-b
    （含该账号的凭据与设备码；不影响网关配置里指向它的资源）
✗ 非交互环境需显式 --yes
EXIT=2                                  # 先给看要删什么、再拒绝 ✅ 未删除 ✅

$ … zcode remove nope --yes
✗ 账号『nope』不存在（见 `mgw zcode list`）
EXIT=2                                  # 指路清晰 ✅

# PTY 模拟交互、回答 n：
将删除账号『acct-b』的本地数据根：
    /tmp/ix-acc/acct-b
    （含该账号的凭据与设备码；不影响网关配置里指向它的资源）
继续？[y/N] n
已取消                                  # 取消路径干净、未删除 ✅

$ … zcode remove acct-b --yes
将删除账号『acct-b』的本地数据根：
    /tmp/ix-acc/acct-b
    （含该账号的凭据与设备码；不影响网关配置里指向它的资源）
✓ 已删除 /tmp/ix-acc/acct-b
EXIT=0
```
呈现纪律（§21.3 原则 2 / R7 声称）**成立**：绝对路径 + 内容说明 + 对网关配置的影响说明，一行不省。交互取消 return 0 与 `setup` 取消 return 1 不一致（**轻微 L-7**，`cli_zcode.py:166` vs `cli_setup.py:121`）。

### 3.6 `zcode claim` 有账号但凭据不可读（离线安全路径，验证 §16.2 呈现 + ack 静默）
```
$ cd /tmp/ix-run && MGW_ZCODE_ACCOUNTS=/tmp/ix-acc MGW_OPS_LOCK_DIR=/tmp/ix-locks \
  /Users/w/Desktop/Model-Gateway/.venv/bin/python -m model_gateway.cli zcode claim
✗ 失败 1 个：
    acct-a  凭据缺失（先 `mgw zcode login` 或 `mgw zcode import`）
EXIT=1
```
`od -c` 验证：失败行为 **硬编码 `\033[31m`**，管道/重定向下 ANSI 照样写进字节流（**L-1**，上轮 IX-L8 未修；`cli_zcode.py:247-249`）。ack 在网关不可达时静默（配置里假端口 14444，未崩溃）✅。

### 3.7 🔴 领取失败文案的「配置谎言」实跑（S-1）
```
$ .venv/bin/python - <<'EOF'
from model_gateway.upstream.zcode.claim import ZCodeClaimClient, CaptchaUnavailable
c = ZCodeClaimClient("https://example.invalid/api", "JWT", "MID", proxy="http://127.0.0.1:9")  # 住宅代理【已配置】
asyncio.run(c.solve_captcha(manual=False))
EOF
CaptchaUnavailable: 未配置住宅代理，验证码求解不可用 —— 请配置 gateway.zcode.proxy（或环境变量 MGW_ZCODE_PROXY）；也可加 --manual 由人工完成验证码
```
根因链：抛错条件是 **solver 为 None**（`claim.py:213`），与 proxy 是否配置**无关**；而生产构造客户端从不传 solver（`zcode_claim.py:127-129`），全仓无 Playwright 实现（`grep -i playwright model_gateway pyproject.toml` 仅 `claim.py:157` docstring 一处，声称「生产用 Playwright 求解」= 无依据）。后果：用户照做（配代理）→ 同一条「未配置住宅代理」**继续**出现且**否定其已做的配置**；加 `--manual` → 第二条消息承认「未接入人工验证码通道」（`claim.py:215-217`）。上轮 IX-S1 的键已真实存在并生效于 httpx（`schemas.py:49-70` + `claim.py:173-176`），**但唯一修复路径依旧无效** —— 判定维持 🔴 严重。
账本 N4（`E2E-20260927…:203`）将其写成「外部依赖（需外购住宅代理）；未配置时明确报错并降级为 failed」——**把「代码未接线」记成「依赖未实测」，口径失实**。
测试固化误导文案：`tests/unit/test_v2_zcode_claim.py:137` 仅断言 `gateway.zcode.proxy in msg`。

### 3.8 `mgw setup` 三情形 dry-run + 劫持来源
```
$ .venv/bin/python -m model_gateway.cli setup workbuddy --config /tmp/ix-cfg/config.yaml --dry-run
目标目录：/Users/w/.workbuddy
    （来源：产品标识 workbuddy → dataFolderName .workbuddy）
已跳过 2 个无可用资源的模型（no-res-model、disabled-res-model）—— 到「模型资源」页为它们添加映射
将写入：models.json（1 条系统模型）
  [dry-run] 将写入 2 条（新增 1）
EXIT=0

$ WORKBUDDY_CONFIG_DIR=/tmp/ix-wb … setup workbuddy … --dry-run
目标目录：/tmp/ix-wb
    （来源：环境变量 WORKBUDDY_CONFIG_DIR）      ← 劫持场景显式点名，前两行置顶，可作 hijack guard ✅
…
$ resolve_target_dir('workbuddy-ai') → (/Users/w/.workbuddy-ai, '产品标识 workbuddy-ai → dataFolderName .workbuddy-ai') ✅
$ resolve_target_dir('workbuddy', env={'CODEBUDDY_CONFIG_DIR':…}) → 环境变量来源 ✅
```
（注：dry-run 读了真实 `~/.workbuddy/models.json` 的既有 1 条以计算「新增 1」，**只读未写**。）

### 3.9 `mgw` 安装态 + 兜底
```
$ command -v mgw → （空，exit 1）；ls .venv/bin/mgw → 不存在
$ pyproject.toml:25-26 已声明 [project.scripts] mgw = "model_gateway.cli:main"（venv 未重装）
```
README 双版本已补 CLI 章节**且给了兜底形态**：`README.md:85` / `README.zh-CN.md:85`「若 `mgw` 不在 PATH，可用等价形式 `python -m model_gateway.cli …`」→ 上轮 IX-M3 的文档半边**已修**；但**产品内文案**（红点 title/toast、空态指引、告警指路）仍只有 mgw 形态 → 归入 M-5。

### 3.10 用法错误退出码（上轮 IX-L3 **残留**）
```
$ .venv/bin/python -m model_gateway.cli zcode      → 用法行 + EXIT=0
$ .venv/bin/python -m model_gateway.cli            → 帮助 + EXIT=0
```
且用法行已过时：`mgw zcode {list|login|import|claim}`（`cli_zcode.py:19`）缺 launch/remove；`cli.py:44` zcode 摘要同样过时 → **L-3**。

---

## 4. 文案问题清单（含建议措辞）

| # | 位置 | 现文案（实跑原文） | 问题 | 建议措辞 |
|---|---|---|---|---|
| W-1 | `claim.py:219-221` | 「未配置住宅代理，验证码求解不可用 —— 请配置 gateway.zcode.proxy…也可加 --manual 由人工完成验证码」 | ① 对已配置代理的用户**陈述不实**（触发条件是 solver 缺失）；② 指了两个都不存在的出路 | 未配代理：`验证码求解未启用：本期未接入 Playwright 求解器，且未配置住宅代理。领取仅两条路——在客户端手动完成一次领取，或等 M5-1 求解器接线（gateway.zcode.proxy 为前置条件而非充分条件）`；已配代理：去掉「未配置住宅代理」前缀，直说`求解器未接线（配置已读到），领取暂不可自动完成` |
| W-2 | `main.py:265-269`（④） | 「1 个模型的参数卡字段会被资源级推理默认覆盖：reasoning_effort（资源D→vm-d）（生效序 …）」 | **不点名是哪个系统模型**；不给两侧的值；无去处 | `系统模型「shadow-model」参数卡的 reasoning_effort=max 会被映射「资源D→vm-d」的资源级默认 low 覆盖（生效序 请求级 > 资源级默认 > 参数卡，PRD FR-3.16）—— 如需参数卡生效，到「资源池设置」页把该映射的推理默认改为「不注入」` |
| W-3 | `main.py:255-258`（③） | 「…到『资源池设置』页启用资源或到『模型资源』页更换资源」 | 两页动作说反：启用资源开关在「模型资源」页，映射增删在「资源池设置」页 | `…已从 /v1/models 隐藏 —— 到「模型资源」页启用对应资源，或到「资源池设置」页为该模型更换/添加可用映射` |
| W-4 | `cli_setup.py:98-99` | 「已跳过 2 个无可用资源的模型（…）—— 到『模型资源』页为它们添加映射」 | 对「有映射但资源停用」处方错误；未说明这些模型同时会在总览横幅出现；未提示修复后需重跑本命令；未区分两类原因 | `已跳过 2 个模型：no-res-model（未配置映射）→ 到「模型资源」页添加映射；disabled-res-model（映射的资源均已停用）→ 启用资源或更换映射。两者已在网关总览页横幅说明；修复后重跑 mgw setup` |
| W-5 | `index.html:109` / `main.js:116` | 「用 mgw zcode claim 查看详情」 | ① 该命令**重新执行领取**（副作用），不是查看；② mgw 未安装时无兜底形态 | `详情见 data/usage/ops-results-<日期>.jsonl（或重跑 python -m model_gateway.cli zcode claim 重新领取并打印）` |
| W-6 | `cli_zcode.py:57,229` / `claim` 失败行 `:249` | 「先 `mgw zcode login`…」 | login 为恒失败占位（`oauth.py:81-90`，诚实报错并转指 import），但引导语把死路排在第一顺位 | 引导语首句改 `用 mgw zcode import <凭据.json> 接入账号`（login 注明「本期占位，浏览器授权后 import」） |
| W-7 | `store.py:139` | 「账号『X』已存在（用 --reuse/--regenerate 覆盖）」 | 设备 ID 语义参数当「覆盖」用；照抄 `--reuse` 即报错（§3.4） | 「账号『X』已存在：确认覆盖请用 `--regenerate` 或 `--reuse <账号名>`（二者同时决定设备 ID 处置，见 mgw zcode import --help）」——更优：拆 `--overwrite` |

---

## 5. 新发现缺陷分级（file:line）

### 🔴 严重（1）

**S-1 · 领取失败唯一修复指引仍是死路，且对用户配置状态陈述不实**——详见 §3.7。`claim.py:213-221`（抛错条件与 proxy 无关）、`zcode_claim.py:127-129`（solver 恒缺）、全仓零 Playwright 实现、`claim.py:157` docstring 失实、账本 `E2E-20260927…:203`（N4）口径失实。上轮 IX-S1 的「键不存在」已修，「路径无效」未修——同一判据（失败后用户无路可走）不降级。

### 🟡 中等（6）

| # | 缺陷 | 证据 | 建议 |
|---|---|---|---|
| M-1 | **两路径可服务判据不一致（运行态维度）**：`/v1/models` 用 registry（invalid 资源→隐藏），`mgw setup` 纯配置（照样下发）——Q28-②「与 mgw setup 只下发可服务模型」在凭据运行态失效场景失守，文件路径重新引入「无报错的失败」 | 实跑差异集：`API 可服务 [] / setup ['healthy-model'] / 差异 ['healthy-model']`（invalidate 后）；`cli_setup.py:33`（`servable_models(config)`）vs `openai_compat.py:53`（带 registry）；`core/resources.py:79-104`、`scheduler.py:408,683`（invalid 来源） | setup 时若网关在跑，拉 `/admin/api/status` 或 `/v1/models` 合并运行态 invalid 集；拿不到时打印一行「网关未运行——仅按配置判定，运行态失效（凭据类）未纳入」 |
| M-2 | ④ 告警不点名系统模型、不给两侧值、无去处 | `main.py:265-295`；实跑原文 §6 | 按 W-2 改 |
| M-3 | ③ 告警「启用资源」指到无该开关的页 | `main.py:257` vs `models.js:329-363`、`resources.js:233,327-329,447-449` | 按 W-3 改 |
| M-4 | setup 跳过行处方一刀切、无横幅联动提示 | `cli_setup.py:98-99`；实跑 §3.8 | 按 W-4 改 |
| M-5 | 产品内指路只有 `mgw` 形态且「查看详情」语义错位（重跑副作用≠查看） | `index.html:109`、`main.js:116`、`cli_zcode.py:57,229`；`command -v mgw` 空（§3.9）；兜底仅在 README:85 | 按 W-5/W-6 改；或让 `pip install -e .` 写进安装后必做并同步 toast |
| M-6 | （残留、未声称）重名导入提示语义混用 + 照抄报错 | `store.py:139`；实跑 §3.4 | 按 W-7 改 |

### 🔵 轻微（11）

| # | 问题 | 证据 |
|---|---|---|
| L-1 | ANSI 着色无 isatty 门控（重定向即污染文件）——上轮 IX-L8 原样残留 | `cli_zcode.py:247-249`；`od -c` §3.6 |
| L-2 | `.ops-dot` 点击=清账（信号销毁动作）却仍 `cursor: default`、无 hover——上轮 IX-L7 残留且语义变重 | `base.css:1123` vs `main.js:110-116` |
| L-3 | 用法行/摘要过时：`zcode {list|login|import|claim}` 缺 launch/remove | `cli_zcode.py:19`、`cli.py:44` |
| L-4 | `mgw` / `mgw zcode` 无子命令 exit 0——上轮 IX-L3 残留（测试亦固化 `test_v2_cli.py:59,71`） | §3.10 |
| L-5 | 取消退出码不一致：setup 取消=1，remove 取消=0 | `cli_setup.py:121` vs `cli_zcode.py:166` |
| L-6 | 四类告警同标题同权重（②冗余/④提示 与 ①③故障 全橙全「配置告警」）；既有 `.alert-info` 未用 | `dashboard.js:74-78`、`base.css:890,896`；§21.3 原则 3 |
| L-7 | 注释/文案「两类」残留：`main.py:216-217`、`admin.py:164`（实为四类）；`ui_verify_v2_visible.py:2` 自称「headless Chrome CDP」实为 Node（`:123-134` 自述挂住） | grep 输出 §6 附录 |
| L-8 | 指标卡「可用模型总数」= enabled 计数，含被横幅宣告「不可服务」的模型，与出口①语义打架 | `admin.py:143`、`dashboard.js:26` |
| L-9 | `mgw zcode claim` 无 `--config`；代理/端口全依 **CWD 相对** `data/config.yaml`——异目录静默失去住宅代理与 ack 目标（IX-L5 家族） | `loader.py:22`、`zcode_claim.py:63`、`local_admin.py:29-30` |
| L-10 | probe 确认到首结果间无「正在探测 X」（IX-L10 残留）；setup 交互确认行仍无「合并 N 条已有条目」（IX-L6 半修：dry-run/写后已有） | `cli_probe.py:105-125`、`cli_setup.py:104` vs `setup_tools.py:157-160` |
| L-11 | 空跑伪账号 `inactive=["（无账号参与）"]` 混入四类容器（JSONL 形态污染；CLI 呈现幸而先短路） | `runner.py:268` |

---

## 6. 账本证据复现（原样粘贴）

`scripts/ui_verify_v2_visible.py`（§三声称「后端 9/9 + 前端 18/18」）——**复现一致，无虚**：

```
[后端出口]
  ✓ overview 含四类告警  ['model_unservable', 'model_without_resource', 'param_shadowed', 'resource_without_model']
  ✓ 四类措辞互不相同  4 条
  ✓ ① 零映射告警提到 503            ✓ ③ 不可服务告警指名模型
  ✓ ④ 覆盖告警说清生效序
  ✓ /v1/models 不含零映射模型  ['ok-model', 'shadow-model']
  ✓ /v1/models 不含不可服务模型      ✓ /v1/models 保留可服务模型
  ✓ status 含 ops_failed_unread  = 0
后端出口实测 9 项，通过 9 项，失败 0 项
```

`node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json`：**18/18**（横幅 8 + 红点 DOM 3 + 轮询 5 + 样式 2），含新断言「已从 /v1/models 隐藏」「请求级」各 1、`banners=4 warnings=4`。

复跑核对：断言名与实现一致——后端已改「四类」（无「两类说四」断言）；「overview 含四类告警」用**集合相等**（非子集），不恒真；「每条告警各渲染一条横幅」计数比对，不恒真。**弱点**：「用双主题令牌」仅正则验证 `.ops-dot` 后 300 字符内出现 `var(--err`，**不验证暗/亮两份主题均有定义**——存在但偏弱，不算恒真（若硬编码色值仍会红）。

`pytest`：**537 passed, 436 warnings in 67.46s**（`--basetemp=/tmp/mgw-pytest`）——账本 §三「537 passed」**复现**，零回归。

`CLI 冒烟`三条（账本 §三）：`zcode --help` 确列出 `list/login/launch/import/claim/remove`（实跑 §3.10 前置输出）✅；`zcode remove nope --yes` 文案与 rc=2 逐字一致 ✅。

---

## 7. 前端规范符合性 / 回归

| 检查 | 结论 | 证据 |
|---|---|---|
| 组件复用（`.alert`/`.alert-warn`/`.alert-title`） | ✅ 无自造横幅样式 | `dashboard.js:74-78`、`base.css:874-896`、`frontend-spec.md:473` |
| `[hidden]` 陷阱 | ✅ `.ops-dot[hidden]{display:none}` 在位 | `base.css:1125` |
| 双主题令牌 | ✅ `--err-bg/--err/--border/--text` | `base.css:1112-1131`；token 双色板前期已复核 |
| 不新建页面 / 不新建轮询 | ✅ 横幅入总览、红点复用 5s status 轮询 | `dashboard.js:14`、`main.js:89-119`；`§21.2/§5.3` 一致 |
| 转义 / 安全降级 | ✅ `esc(w.message)`；空/非数组→不渲染 | `dashboard.js:72-77`；实跑断言 2 项 |
| 「UI 声称但无实现」 | ⚠️ 两处：toast 指 `mgw`（未安装，M-5）；`claim.py:157` docstring「生产用 Playwright」无实现（S-1） | — |
| 本轮新增 CLI/端点是否带来越界 UI | ✅ 无（ack/bench/reload 均无界面件；账号管理页仍按 §20 #12 不做） | `admin.py:365-412` |

---

## 8. 环境与时点注记（诚实前置）

- **运行中网关是旧代码**：`127.0.0.1:8300` uptime≈4.5 天（≈09-22/23 启动），`/admin/api/overview` **无 `warnings` 字段**、`POST /admin/api/ops/ack` → **405**（实跑）。→ 本轮所有可见出口在用户**重启网关前不生效**；「真实站点生效」未验证（不重启用户进程属既定保守）。
- **浏览器渲染未做**：沙箱 headless Chrome 挂住（上两轮 + 脚本 `:123-134` 同口径），以 Node 执行**同一份源码**函数替代——沿用项目已接受的替代法，非浏览器证据。
- 真实凭据路径（领取成功/already_done/inactive 四类真值、bench 端到端、probe 真探测、`pip install -e .` 装出 `mgw`）：均未验证；probe 契约符合性为**代码阅读 + 上轮实跑**结论。
- `.workbuddy-ai/`（仓库根 untracked，mtime 09-22/26）非本轮产物、未 gitignore——顺带报给 eng（不属交互维度，不计级）。

---

## 9. 上轮遗留账（本轮是否兑现）

| 上轮编号 | 本轮声称 | 实跑核验 |
|---|---|---|
| IX-M1 红点只增不减 | 已修 | ✅ ack 三出口实跑/读码齐（§2 出口②） |
| IX-M2 无账号假成功 | 已修 | ✅ §3.2 |
| IX-M3 mgw 不可执行 / README | 部分（顺带 5） | ✅ README 双版含兜底；⚠️ 产品内文案未兜底（M-5） |
| IX-S1 代理键死指引 | （R 项外，键已存在） | ❌ **换了形态仍是死路 + 新增说谎成分 → S-1** |
| IX-L1 前缀重复 / IX-L2 表头错位 | 已修 | ✅ §3.6 单前缀；§3.1 表头对齐（`_wcwidth`） |
| IX-L3/L5/L6/L7/L8/L10 | 未声称修 | ❌ 全部仍在（L-1/L-2/L-4/L-9/L-10/L-5'） |
| IX-M4 --manual 误导 | 键与双分支文案已动 | ⚠️ 循环半消：`--manual` 分支改口（`claim.py:215-217`），但主分支仍推荐一个无实现的开关（W-1） |
| IX-M5 import 提示 | 未声称 | ❌ 原样（§3.4，M-6） |
| 范围外发现 enabled_of 未接线 | 未声称 | ❌ 原样（`main.py:89`、`cli_zcode.py:224` 均不传）；因当前无任何入口能把账号置 disabled，用户暂不可见——维持移交 eng 注记 |

---

## 10. 复跑方式（只读）

```bash
cd /Users/w/Desktop/Model-Gateway
MGW_ZCODE_ACCOUNTS=/tmp/ix-acc .venv/bin/python -m model_gateway.cli zcode list|claim   # §3.1/3.2
MGW_ZCODE_ACCOUNTS=/tmp/ix-acc … zcode import /tmp/ix-payload-{a,b}.json                # §3.3/3.4（a 先 b 后）
MGW_ZCODE_ACCOUNTS=/tmp/ix-acc … zcode remove acct-b [--yes]                            # §3.5
.venv/bin/python -m model_gateway.cli setup workbuddy --config /tmp/ix-cfg/config.yaml --dry-run  # §3.8
.venv/bin/python scripts/ui_verify_v2_visible.py                                        # §6（9/9+18/18，自带临时网关）
node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json                    # §6（18/18）
.venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest                                # 537 passed
```

## 11. 判定汇总

**有条件通过**。硬条件 3 条：
1. **S-1**：`solve_captcha` 文案按状态分叉（未配代理 / 已配代理但求解器未接线），并撤掉 `claim.py:157` 与账本 N4 的失实表述（或本期接线 solver）。
2. **M-1**：`mgw setup` 与 `/v1/models` 的运行态判据对齐（或显式打印「仅按配置判定」的告警行）——Q28-② 的字面要求。
3. **M-2/M-3**：④ 告警点名系统模型 + 两侧值 + 去处；③ 告警把「启用资源」指回「模型资源」页（按 W-2/W-3 逐字）。

> 诚实声明：本报告全部 CLI 结论为实跑粘贴原文；未跑项（真实凭据领取、probe 真网络、浏览器视觉、`mgw` 安装态、旧版运行网关的重启后表现）均已逐条标注「未验证/未测」。临时数据仅在 `/tmp/ix-*`；未向真实上游发请求；未写用户真实数据目录（`~/.workbuddy/models.json` 仅 dry-run 只读）。
