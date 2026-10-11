# 交付记录（2026-10-07）：三支 skill 落盘 + 三项结构调整

> 用户批准（原话要点）：「A+B+C 全做」「先 P2+P3+P4」「授权直接写文件」（约束：只新建 `~/.qoder-cn/skills/<新名>/`，不改 `batch-acceptance-merge` 与 `oil-ui-pro`，不碰项目源码）。
> 流程依据：`20261007-skill-portfolio-review.md`（判定）→ `20261007-skill-verification-round.md`（勘误）→ `20261007-skill-coordination-review.md`（协调性）。

## 1. 交付物

| # | 位置 | 内容 | 校验 |
|---|---|---|---|
| P2 | `~/.qoder-cn/skills/mgw-delivery-round/SKILL.md` | 一轮改动→交付 9 步（含快路径排除、岛式计数、execv 同 PID 上线判定） | 正文 77 行 / description 320 字符单行 / 无 TODO / 无多余文件 ✓ |
| P3 | `~/.qoder-cn/skills/mgw-gate-hygiene/SKILL.md` + `scripts/check_gate_js.py` + `scripts/check_esm_symbols.py` | 门卫生：三步自检 / 五分类归因 / 撤证唯一配方 / 判据随设计前进 / ESM 契约校验 | 正文 88 行 / 362 字符 / 三个文件无 README 类多余件 ✓ |
| P4 | `~/.qoder-cn/skills/mgw-live-audit/SKILL.md` | 实盘只读核查：隔离实例配方（唯一主人）/ 假上游身份头分派 / 事件行对账 / 归属核查 / 读数纪律 | 正文 71 行 / 308 字符 ✓ |

**已生效证据**：本会话的技能清单已列出三支（`mgw-delivery-round` / `mgw-gate-hygiene` / `mgw-live-audit`，各带 description）——即已被加载器识别。自动触发行为待新会话验证（不越口径）。

## 2. 附属脚本的实跑证据（skill-creator 要求「脚本必须实跑」）

| 脚本 | 正例 | 负例 |
|---|---|---|
| `check_gate_js.py`（内嵌 JS 抽取 + `node --check`） | `verify_accounts_ui_live.py:615-2831`（2216 行）+ `verify_settings_layout.py:39-418`（379 行）双绿，`合计：2 通过 / 0 失败` rc=0 | ① `/tmp` 副本注入多余的 `(` ⇒ rc=1 且点名行号；② 无 JS 块的文件 ⇒ **rc=2 点名"取不到对象即 RED"**（绝不静默通过） |
| `check_esm_symbols.py`（import/export 契约） | 现树 `16 通过 / 0 失败（扫描 16 支 .js）` rc=0 | ① 副本把 `../api.js` 改成 `../apiX.js` ⇒ rc=1 `:17 import 目标不存在`；② 副本删掉 `export const isProviderResource` ⇒ rc=1 `:17 api.js 未导出 → isProviderResource`；行号与源文件对得上 |

🔴 **如实登记的缺口**：`check_esm_symbols.py` **不提供**「未定义引用」静态腿——10-07 三版启发式实现全被正则字面量（`/["'&<>]/g` 里的引号会让朴素词法器吃代码）与模板串/Tab 键名打成大面积误报，**恒红的检查器 = 没有检查器**，故只保 import/export 契约两条确定性腿；该腿的权威做法是运行期（逐模块 `--input-type=module` import + 真浏览器逐页），已写进 SKILL.md §7。

## 3. 三项结构调整（用户批准 A/B/C）

| # | 文件 | 改动 | 复核 |
|---|---|---|---|
| A | `AGENTS.md` | 上下文装配第 4 步 = 新增 playbook 入口（三支 + 路由指针），原 4/5/6 顺延为 5/6/7 | 实测 7 步编号连续 ✓ |
| B | `.cursor/rules/mg-directory-layout.mdc` | 目录分流表补 `coding/`（源码唯一区）与 `bianyiandhuanjing/`（运行与验收环境）两行 + 真相源指针（`项目目录说明.md`）；首行包根改为 `coding/model_gateway/` | 表格 8 行、无重复行 ✓ |
| C | `.cursor/memory/runbook.md` | 12 行空占位 → 六节实命令（环境/运行/验收门链 10 步/数据位置/授权协议）；两处实测纠偏写死：**[1/2] 红即 exit**、**README 窗口是单向区间**、**收集面含 `verify_v*_repro.py` 五支**、**取终局数 grep 不 tail** | 每条命令与源码/实测对齐（`ship-gate.sh:20-22`、`test_v2_readme_claims.py:73-74`、`pyproject.toml:54`）✓ |

## 4. 未做 / 未验证（如实）

- **未创建** P5 `mgw-panel-verdict`、P6 `mgw-ui-evidence`（下一批）；P7 已按裁定折入 P2 第 7 步；`mgw-catalog-onboarding` 仍为待触发备选。
- **自动触发未验证**：需 `/skills reload` 或新会话试触发（本会话只能证明"已被列出"）。
- **未改** `batch-acceptance-merge` 的悬空引用（D3 未批）；其 description 里指的 `acceptance-verifier-false-red` 与 P3 的关系已写进 P3 description，但对方文件一字未动。
- **未提交任何 git**（规矩 13；且 `docs/` 被 gitignore，本文件与另三份评审文档永不进提交；`AGENTS.md` / 两份 rules/memory 文件属可提交面，待用户指令）。
- **判据 id 4 个重复（D6a/D6b/MS2f/MS8）**：只登记未修（属门侧改动，未获批）。
- **runbook 命令未逐条实跑**：写的是与源码/台账逐字对齐的字面（含退出码与终局行），但未整链复跑一遍（约 8~20 分钟级）；下一次真实交付轮会自然验证。
