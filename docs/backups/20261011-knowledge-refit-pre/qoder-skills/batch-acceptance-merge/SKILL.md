---
name: batch-acceptance-merge
description: 把积压在任务分支上的多个 commit 批量「验收→修复→合并 main」的四阶段流水线 playbook（P0 按波次/域归组 → P1 分支 tip 一次性静态门 → P2 证据/契约/净化审计 → P3 一次构建+批量探针复采 → P4 合并 main+账本回写）。触发：用户要求「逐一验收 N 个 commit」「批量验收」「确认收敛完毕」「验收全部未完结项」「验收通过后合并 main」。仅适用于 codex-coding 工程（脚本/端口均项目锚定）。验收器/探针报红时的归因诊断不要用本 Skill，先走 acceptance-verifier-false-red。
---

# 批量验收积压 commit 并合并 main

## 适用与前置

- 适用对象：任务分支领先 main 的积压 commit（几个到上百个），或用户给出的「未完结事项」清单。
- 本 Skill 为 codex-coding 工程定制：脚本在 `bianyiandhuanjing/scripts/`，复刻端实例端口 9334/9335+，live CDP 9333（9222 被 Cursor 占用，禁用）。
- 前置动作（开工必做）：
  1. 读 `other/changes/ACTIVE.md`（活跃任务台账）。
  2. 跑 `bash bianyiandhuanjing/scripts/preflight.sh --full --symptom "<本次关键词>"`。
  3. 向用户复述验收标准口径再动手：01 包 asar verbatim 差分对齐、五维度证据（样式/交互/功能/设置/机制）**+ 端到端可用第六维（前端 + 前后端联动完整能力，红线 35）**、质量门 tsc/oxlint/vitest/build 全绿、验收执行器 fail=0；每个「通过」判定必须附可复跑证据（红线 30⑥）。**轨道一项不需请用户逐项验收，自验收全绿即自行合并**。
  4. 申报红线 20 构建计数预算（≤2 次未收敛即停手升层）。

## P0 清点归组

- `git log main..<branch> --oneline` 清点；**同时跑 `git log <branch>..main --oneline`** 探 main 侧分叉（P4 判 ff 用）。
- 按波次/改动域归组；同波次同改动的 commit 合并成一组验收，不逐个重复跑门（省 token 且防「把对的改错」）。
- 防误判：分支 log 里可能混有早已在 main 历史里的 commit——先用 merge-base/域判断剔除（实证：60 个 commit 实际只覆盖 3 个改动组）。
- 产出归组表（组 / commits / 内容）报给用户后继续。

## P1 静态门（分支 tip 一次性）

在分支 tip 上一次跑全四门：tsc → oxlint → vitest 全量 → dev 构建（一条命令即可：`bash bianyiandhuanjing/scripts/ship-gate.sh`，它串四门 + 两道外来源门，任一红 exit 1）。后台串行跑，攒批不逐 commit 跑。全绿才进 P2；红 ⇒ 先走 acceptance-verifier-false-red 归因再修复。

## P2 证据/契约审计（离线只读）

- 逐组复核验收证据存档：summary.json / acceptance-plan 契约（四列完整 + 用户确认留痕）/ 01 verbatim 抽查。
- 净化门两道全跑：`verify-no-foreign-data.sh --project` + `verify-foreign-provenance.py`，产品面必须 0 命中。
- 用各波验收复跑器离线重算（如 `run-waveAE-acceptance.sh` / `run-pet-acceptance.sh`）：**复跑 = 重算，不重采**。
- 发现 FAIL：先归因（工具坏 or 产品坏，走 acceptance-verifier-false-red）；产品坏 ⇒ 立即对齐修复再复验，不许降格放过。

## P3 运行态批量复采

- 一次构建，一个探针脚本覆盖本批全部检查点（批量验证纪律）。
- 起 worktree/分支实例必须带 `--tree <该分支源码树>` 与独立 `--port`：**不指定 tree 会永远在主线产物上跑探针**，把别的分支的修复当成没修（2026-09-24 三波并行验收实测踩坑）。
- 探针选页用 `--target-url-exact <主窗URL>`，不用 `--page-index`（主窗/宠物窗间序号会翻转）。
- 探针件信封必须含 version/appVersion，结论写版本号；含已知答案断言门的探针，断言门不过则输出一律不得采信。
- 多组并行时逐实例独立端口（9335/9336/9337…），验证锁归主控会话。

## P4 合并 main + 账本回写

1. 判 ff：`git log <branch>..main` 非空 ⇒ ff 不可行，走 merge commit。**冲突解「语义并集」**：逐处判断——main 侧的新架构/新修保留 + 分支侧的新逻辑保留，不是机械取一边（实证：appServerBridge 的 refresh 新逻辑 + main 的 loader 登记表架构两者都要）。
2. **合并授权（2026-09-24 双轨制，红线 35）**：本 Skill 处理的对象默认是**轨道一（对齐/Bug 修复）**——`ship-gate.sh` 全绿 + `verify_acceptance.py fail=0` + 端到端可用证据齐 = **自动合并 main，不再索取用户对话层确认**；merge commit message 必须写 **verdict + 证据包路径**（用户事后抽查的唯一回溯线索）。仅当该项属**轨道二（个性化：模型对接 / 登录授权 / 用户点名的定制）**时，才须先经用户人工验收（走 `other/people-todolist/` 交接单）后合并。pre-commit hook 拦截时出示机械门 verdict 留痕；禁止静默 `--no-verify`（绕过须按红线 33 当场声明）。
3. 合并后**复跑全闭环**才算完成：四门 + 探针复采 + 验收执行器，逐项核对与修复预测一致（实测一轮：tsc 0 错、vitest 1436 例全绿、探针两态数值与报告预测逐项吻合）。
4. 账本回写：ACTIVE.md 行状态、`other/specs/divergences.md`（如触发定制）、各报告 §「运行态待复验」预测逐条核对销账；跨会话项目状态变化同步更新记忆文件。
5. 向用户**通报**（不是请示）验收结果：一行「已自验收通过并合并 + 证据包路径 + 失败门为空」即可；自验收未通过的项**禁止合并**，继续修或（需用户裁决时）开交接单，绝不写「先合了再说」。

## 变体：验收「未完结事项清单」而非纯 commit

- 未开发项 ≠ 验收项：对它们「验收不通过→对齐解决」 = **先按 01 差分对齐实现，再走验收**。
- 按域互斥归组：同域事项必须并成一条线验收/实施，避免两路改同一批文件打架。
- 大块实施派子 agent 隔离 worktree 并行（worktree 内 node_modules 用指向主树的符号链接），主控持验证锁复核；**agent 自述不可信，必须实测复核**（红线 30）。
- 物理无法替用户完成的项目（如 OS 级视觉目检、需真人登录/授权的动作）→ **开 `other/people-todolist/` 交接单**列为该组唯一例外并告知用户，禁止当作"已验收"或"已合并"的依据。

## 与其它 Skill 的关系

- 验收器/探针报红、假红/假绿归因 → `acceptance-verifier-false-red`（本流水线任何一环报红都先过它，再决定修工具还是修产品）。
