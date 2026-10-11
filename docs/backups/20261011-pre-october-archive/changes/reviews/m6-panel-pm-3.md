# M6 交付面板 · PM-3（收口复验角色）· 台账 ↔ 现实 最终核验

> 角色：PM-3 收口复验（独立核验，非实现方；**唯一仓库写入 = 本文件**）
> 对象：台账 `docs/changes/e2e-records/E2E-20260930-M6-multi-product.md`（05:1x 终版回填版，mtime 05:24）
> ＋ 面板结论清单（`m6-panel-{pm,pm-2,eng-a,eng-a-2,eng-b,ix}.md`）＋ README 双语 ＋ `tech-design §22.11`
> 纪律：主树只读（写入仅本文件）；全部 pytest 在**主树只读形态**下跑（`PYTHONDONTWRITEBYTECODE=1`
> ＋ `-p no:cacheprovider` ＋ `--basetemp=/tmp/m6pm3-*`），跑前/跑后 `git status --porcelain` 均 113 行零漂移；
> 不碰 `data/`、`:8300`（61799 存活未动）、真实上游、8398（本时刻无监听）。**不跑长测**（brief 允许只跑
> `--collect-only` ＋ README 守卫 ＋ 结构核对）。
> 状态：**完成**（本报告为终稿）

## 结论

> ### **通过 · 阻塞 0**
>
> 台账 6 项可核数字**逐项与磁盘一致**（README 双语 1445 逐字、主树 `--collect-only` 1445、
> 台账 1445/0 口径、M6-7 行逐条吻合、沿革末值 1445、+23 差额来源 9+2+6+6 精确）；
> 面板全部轮次（M6-0…M6-7 ＋ 两轮修复 ＋ 复验）与 4 源结论清单（PM×2 / eng-a / eng-b / IX）
> 在台账**逐条有处置与复验状态**，无遗漏阻塞项；U1–U14 未被写成完成，skip/xfail 标记零命中。
> 附 2 条低度登记发现（L1 证据指针再漂移、L2 README 措辞承诺无清单）＋ 1 项卫生清理
> （**已当场终止 3 个遗留 M6 测试实例 8395/8396/8397**，8393-8399 现零监听）。

## 进展记录

- [x] 数字对表（§1）：6/6 一致 ＋ 结构核对 6 项
- [x] 覆盖性（§2）：全部轮次与结论清单逐条落台账
- [x] 诚实性（§3）：U1-U14 ↔ §22.11 ↔ README 尾注一致；skip/xfail 零命中
- [x] 卫生终态（§4）：规则在盘、零残渣、清理 3 个遗留实例、git status 零漂移
- [x] 结论：**通过 · 阻塞 0**

## 1. 数字对表（台账每一个可核数字逐一实测）

| # | 台账宣称 | 核验方法 | 实测结果 | 判定 |
|---|---|---|---|---|
| 1 | README 双语 = **1445**（逐字一致） | `grep -n 1445 README*.md` | `README.md:11` badge `tests-1445%2F1445`、`:178` `1445 passed`；`README.zh-CN.md:11`、`:169` 同 —— **4 处逐字 1445** | ✅ |
| 2 | `--collect-only` = 1445 | 主树 `.venv/bin/python -m pytest -q --collect-only -p no:cacheprovider --basetemp=/tmp/m6pm3-collect` | **`1445 tests collected in 0.28s`**（exit 0） | ✅ |
| 3 | 终态命令 `1445 passed / 0 failed` | **未由 PM-3 主树全量复跑**（brief 免长测）；以支撑链核验：collect=1445 ＋ README 守卫 `tests/unit/test_v2_readme_claims.py` 定向跑 **5 passed**（0.44s）＋ 复制品两轮全量（PM-2 §4 / eng-a-2 §5 = 1445 collected/1444 passed/1 双树伪红，机理双方独立复证） | 支撑充分；主树 1445/0 为总 agent 自述口径（与历史沿革同档，历史值同样无盘上产物） | ✅* |
| 4 | M6-7 行：eng-b ✅0 / IX ✅0 / eng-a ✅（A-1 边界阻塞）/ PM ❌2；eng-a-2 ✅0 / PM-2 ❌1（仅台账计数） | 逐份报告结论段比对 | `m6-panel-eng-b.md`「通过·阻塞 0」✓；`m6-panel-ix.md`「通过。阻塞项：0」✓；`m6-panel-eng-a.md`「通过（0 阻塞；A-1 交付前须收口，字面从严则升格）」→台账写「A-1 边界阻塞」属边界表述 ✓；`m6-panel-pm.md`「不通过·阻塞 2」✓；`m6-panel-eng-a-2.md`「通过·阻塞 0」✓；`m6-panel-pm-2.md`「不通过·阻塞 1（B-2a）」✓ | ✅ |
| 5 | 沿革末值 **1445**（`1422→1443→1445`）＋「1444 passed + 1 双树伪红 = /tmp 伪影」 | 台账内部一致性 ＋ PM-2 §4 机理 ＋ eng-a-2 §5 | 末值 1445 ✓；+23 来源：`test_accounts_models_api.py` 9 ＋ `test_m6_a1_wiring.py` 2 ＋ `test_m6_panel_fixes.py` 6 ＋ `test_ops_panel_fixes.py` 6 = **23**（`grep -c 'def test_'` 实测）✓；双树伪红机理与两角色结论一致 | ✅ |
| 6 | 「1445/0」 | 见 #2/#3 | collected=1445、README=1445 已真；0 failed 由复制品回跑 ＋ 伪红机理支撑 | ✅ |

**结构核对（辅助证据，非台账点名的数字）**：
- `api/admin_accounts.py` 路由 **14 条** = 台账「13+1 端点（新增 models 目录出口）」✓（`@router.` 计数，`/models` 在 `:654`）
- `model_gateway/accounts/` = 7 模块（types/registry/store/device/login/net/materialize）✓；10 产品 `build_out` 全接线（`grep -l 'def build_out' upstream/*/product.py` = 10；out.py 文件 8 个，buddy+workbuddy、qoder+qodercn 共用实现——台账 M6-5「buddy 试点 + 9 产品 out.py」按"产品"计 = 10 产品全覆盖，成立）
- `m6-accounts-assertions.json` = **72 条全 ok**（= 55 原始 + 17 `[修复轮-1]`）→ 台账 M6-4「修复轮后 72 条断言全 PASS」✓；IX 面板 81 项（去重）✓；R3 独立 67 项 ✓

## 2. 覆盖性（结论清单 → 台账逐条对表）

| 结论项（源） | 台账落点 | 复验状态在台账 | 判定 |
|---|---|---|---|
| PM B-1 `list_models` 零出口 | L53 | 「PM-2 闭环（8394 四态 + CDP 8/8 + 生产链路 file:line）」——与 PM-2 §1 逐项吻合 | ✅ |
| PM B-2a README/台账计数 | L54 | 终版回填 1445；本报告 §1 复核为真 → **真闭环** | ✅ |
| PM B-2b `.gitignore` 缺规则 | L55 | 「PM-2 闭环（check-ignore 反证）」＋本报告 §4 规则在盘/零残渣 | ✅ |
| eng-a A-1 锁等待阻塞事件循环 | L56 | 「eng-a-2 闭环：心跳 3.76ms/2490 拍；撤 5 处 await → 964ms/1 拍；恢复 1.27ms」——与 eng-a-2 §1 三态表一致 | ✅ |
| eng-a A-2 双桥接 / A-3 retryable 口径 | L57/L58 | eng-a-2 闭环（对象级同一 ＋ 5 组输入逐字段一致；zcode 改 `is_transport_failure` 同尺） | ✅ |
| eng-b F1 空 base_url / F2 `_apply` 半应用 / F3 凭据回显（红线） | L59/L60/L61 | 均「eng-a-2 闭环」＋各自撤修复红证（撤判据 → 模型回清单；撤脱敏 → 明文红） | ✅ |
| IX-1 行号漂移 / IX-2 内部编号上屏 / IX-3 短信导语 | L62 | IX-2/IX-3 有 `[修复轮-1]` 断言复验（JSON 恒 66-68 条）且磁盘复核通过（title=「该产品未提供续期通道…」无 §；`guideText` 有 `sms_code` 专属分支）；**IX-1 注记已改但指针在终态树上再度漂移 → 见 L1（非阻塞）** | ✅/△ |
| 修复轮 1（R1/R2/R3/R4 全部阻塞项） | M6-6 表 L30-47 | R1-F1/F2/F3/F4/F5/F10/F6/F11、R2-B-1/B-2/F-3/F-4/F-5、R3-P-1/P-2/P-4、R4-BL-1~5 **逐条有修复 ＋ 红证/复验**；R3 结论「无阻塞」（P-3/P-5 登记级）、eng-a-2 3 条低度登记、eng-b F4/F5 低度登记属"登记"级无需台账行 | ✅ |
| 波次全覆盖 M6-0…M6-7 ＋ 两轮修复 ＋ 复验 | L11-18 ＋ L26-62 | 无遗漏轮次；「过程记录（诚实披露）」如实登记代理越界/中断/一次真实网络调用登记 | ✅ |

**无遗漏阻塞项**：对照 6 份面板报告结论段，阻塞项全集 = {PM-1: B-1/B-2a/B-2b} ∪ {eng-a: A-1（边界）} ∪ {eng-b: F1/F2/F3} ∪ {IX: 0} ∪ {eng-a-2: 0} ∪ {PM-2: B-2a 残项} —— 台账全部行有处置，且除 IX-1 指针（L1）外全部为真闭环。

## 3. 诚实性（未实测清单 ↔ README 尾注 ↔ §22.11）

- 台账 U1–U14 与 `tech-design.md:1706-1708`（§22.11）五类（真实凭据 / zcode 405-3012 / qoder 签名 / macOS / 字段漂移）**方向一致且更细**；与 README 双语尾注（「需要真实凭据的 ZCode / Anthropic 路径项未验证」）一致。
- **未发现任何 U 项被写成"已完成"**（R4 §4 全表核证 ＋ 本报告抽核源码注释：`zcode/captcha.py:17-18`、`buddy/out.py:15-16`、`cline/out.py:33-34` 等均写「未实测/未取证」）。
- skip/xfail：`pytest.mark.skip` = 0、`pytest.mark.xfail` = 0、`skipif`/`xfail` 全文零命中；唯一 `pytest.skip(` 在 `tests/integration/test_int_v2_frontend_gate.py:86`，为「本机无 node」条件跳过 —— 本机 `node v24.18.0` 在位（`/usr/local/bin/node`），**不触发、不构成"伪装通过"**。
- **L2（低度，非阻塞）**：README 尾注称未验证项"已显式列出"，但 README 内并无该清单（R4 §3.4 已指出「仓库内没有那份清单，建议改措辞或内嵌最小清单」，终版 README 未处置）。台账 L70「评审侧核证」未记该措辞注记。

## 4. 卫生终态

- `.gitignore:32-33` 规则在盘（注释 ＋ `.pytest-tmp-*`）；全仓（排除 .git/.venv）`find . -name '.pytest-tmp-*'` **零残渣**。
- 主树两次 pytest（collect-only ＋ README 守卫）前后 `git status --porcelain` 均 **113 行**（34 M ＋ 79 untracked），与 PM-2 基线**零漂移**；无新增异物（`.workbuddy-ai/` 属既有基线项）。
- **遗留端口清理（本次执行）**：发现 3 个 M6 面板轮的孤儿测试实例仍监听（PPID=1）——
  `41441`（`:8396` `/tmp/m6ix-5830/launcher.py`，IX 面板实例）、`43361`（`:8397` `http.server`，IX CSRF PoC 页）、
  `47098`（`:8395` `/tmp/m6pf1-inst/launcher.py`，修复轮真机实例）。已 `SIGTERM` 三进程并复核：
  **8393-8399 现零监听**；`:8300`（PID 61799，用户实例）**未触碰且存活**；8398 本时刻无监听（若有勿动约束未触及）。
- `/tmp` 下遗留实验目录（m6ix-5830、m6pf1-inst、m6pm2-*、m6ea2-* 等）为面板证据与复跑材料，**保留不删**（非仓内残渣）。

## 5. 低度登记发现（非阻塞；供交接）

| # | 级别 | 发现 | 证据 | 建议 |
|---|---|---|---|---|
| L1 | 低 | `m6-accounts-assertions.json` 的 P-B1 `note` 写「修复轮-1 于 2026-09-30 核准更正：调用点 store.py:551、实现 store.py:726-752、注记 store.py:734-737」，但**终态树上三处均不符**：调用点 = `store.py:567`、`_verify_written` 定义 = `store.py:786`、P-B1 注记 = `store.py:794`（`store.py` mtime 04:18、sha256 前 16 = `5521122df6d8c487`，与 eng-a-2 冻结值一致 ⇒ 非评审后再变，是更正时即已滞后 14 分钟——异步接线使实现后移 ~60 行）。即 IX-1「行号更正」在终态未真正闭环（同类第 3 次漂移）；Ledger L62「IX-1 均已修」在该点上与磁盘不符。语义/修复本体/回归用例（`test_admin_accounts.py::test_enable_after_stale_meta_still_works`）均真实有效，属**证据指针级**低度（同 IX-1/R3-P-2 既定级别） | `grep -n _verify_written store.py` → `567/786`；`grep -n 'P-B1\\|比较基准' store.py` → `794`；JSON note 原文 | 一行再校正（或改符号引用不写行号），可与后续任何一次改动一并做 |
| L2 | 低 | README 尾注「explicitly listed as not yet verified」承诺的清单不在 README 内（R4 §3.4 已指出，未处置） | `README.md:178`、`README.zh-CN.md:169`；全文无该清单 | 改措辞（指向 docs 交付文档口径）或内嵌最小清单 |

> 两条均**不构成阻塞**：不改变任何交付面行为/数字，且各有既定同族先例（IX-1、R3-P-2、R4 §3.4）判低。
> 若收口方按 PM-1/PM-2 的「台账宣称必须与磁盘相符」最严口径复核：L1 涉及台账 L62 对 IX-1 的闭环宣称 → 可升格 1 阻塞（判据与处置均在本报告，一行可修）。

## 6. 方法与限制（诚实披露）

- 未跑主树全量（brief 明确免长测）：#3 的 passed 口径为"支撑链核验"，非 PM-3 亲跑；`1445 passed/0 failed` 在上游两角色复制品回跑（1444+1 伪红、机理复证）下成立。
- 未重验 15 张面板截图逐像素（属 IX/eng 面板既有范围）；未触碰 `data/`、`:8300`、真实上游；未跑任何真实凭据路径（与 U1 一致）。
- 历史沿革 835/996/…/1422（除末值外）无盘上产物，仍属自述（同 PM-2 §5 口径）；本次只核末值与 +23 可核差额。
- 主树写入披露：唯一写入 = 本文件；另含 3 个遗留测试进程的终止操作（§4，已记录 pid/端口/路径）。

## 附：关键核验命令与原始输出

```bash
# 1) README 逐字
grep -n "1445" README.md README.zh-CN.md
#   README.md:11 badge 1445/1445 · :178 "1445 passed" ; zh:11 / :169 同

# 2) 主树 collect-only
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q --collect-only -p no:cacheprovider \
  --basetemp=/tmp/m6pm3-collect          # → 1445 tests collected in 0.28s

# 3) README 守卫
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/unit/test_v2_readme_claims.py -q \
  -p no:cacheprovider --basetemp=/tmp/m6pm3-guard     # → 5 passed in 0.44s

# 4) 结构
grep -c '@router\.' model_gateway/api/admin_accounts.py              # → 14
grep -l 'def build_out' model_gateway/upstream/*/product.py | wc -l  # → 10
python3 -c "import json;d=json.load(open('docs/changes/e2e-records/m6-accounts-assertions.json'));print(len(d))"  # → 72

# 5) 卫生
find . -name '.pytest-tmp-*' -not -path './.git/*' -not -path './.venv/*'   # → 空
git status --porcelain | wc -l                                        # → 113（前后一致）
lsof -nP -iTCP:8393 -iTCP:8394 -iTCP:8395 -iTCP:8396 -iTCP:8397 -iTCP:8398 -iTCP:8399 -sTCP:LISTEN
#   清理前：8395/8396/8397 三个 M6 遗留实例；kill -TERM 41441 43361 47098 后 → 零监听
```

（终稿 · PM-3 · 2026-09-30；HEAD `5158cbc` ＋ 113 行 M6 工作树增量，与面板各轮同树）
