# 交接单 20261008-structure-other-handoffs —— 结构定版翻案：新建根 `other/handoffs/` 交接单机制

> 开单人：主会话（模型映射弹窗三轮 + 会话决策规则提炼会话）。日期：2026-10-08。
> 性质：**本单即凭据**——用户对结构定版翻案的授权记录随本单落盘存证（此前「工具应答在案」只是会话内时点引用）。
> 状态：**已执行（本单即凭据）**。

## 1. 来源会话
- 会话名称：Model-Gateway 主会话（模型映射弹窗三轮修复 + 会话决策规则提炼）
- sessionId：session-c616a2f8-b6c8-4925-a886-513c8cb01d93
- 开单时间：2026-10-08 12:5x
- 开单 AI 工具：DeepSeek Harness（modelgateway / glm-5.3-flash）

## 2. 归属话题
- 源自：① 用户 2026-10-08 指令「先整理，信息落地/该动前要经过多角色验收完全通过才可以，否则要重新核实再交叉验证直至完全通过才允许」（落地闸）+ M1 裁决「可以参考这个项目自动化验收和哪些你验收裁决不了交接真人处理的流程…/Users/w/Desktop/codex-coding」；② 规则评审 D2→D5 期间格式审查员阻塞①（交接单目录与 .gitignore:25 矛盾）与反方 N2（结构定版修案权在用户）。
- 涉及分支 / commit：main @ `4bd0a6d`（前置基线）；本落地批为文档/目录新增，不改动代码。
- 涉及文件（files-in-scope）：`other/handoffs/`（新建）、`项目目录说明.md`（登记）、`AGENTS.md`（结构定版条 + 状态链补记）、`.cursor/memory/pitfalls.md`、`.cursor/memory/decisions.md`。

## 3. 类型
☑ 方案选择（结构定版翻案 = L 级 / 评审稿五类④；已获用户当场裁决，本单转凭据存证）

## 4. TODO（要用户干什么）
- ~~要用户做的动作~~：**已完成**——2026-10-08 用户在 ask_user_question 应答中选 **A 案**。
- 备选项（当时列给用户）：
  - **A. 新建根 `other/handoffs/`（用户所选，推荐项）**：git 可见、跨机不丢、与 codex `other/people-todolist/` 同构；代价 = 翻案 2026-10-01 结构定版（「docs/ 过程真相唯一源」），同步登记项目目录说明.md 与 AGENTS 结构定版条。
  - B. 落 `docs/changes/handoffs/` 不动结构：代价 = git 不可见（gitignore:25）、跨机克隆即丢，需同步登记 AGENTS 状态链或 ACTIVE.md 防静默蒸发。
- **用户应答原文存证**：问题 = 「交接单（AI→用户待办：验收/方案取舍/裁决）的落地目录——新建顶层 other/ 是对结构定版的翻案，需你定：」；所选 = **「A：新建根 other/handoffs/（推荐）」**（ask_user_question 工具应答，2026-10-08）。
- 等确认期间的影响：无（本单开单时授权已获，落地批同轮执行）。

## 5. 证据与回滚点
| 项 | 值 |
|---|---|
| 张力本体 | `项目目录说明.md:4/:20`「docs/ 承担参考工程 other/ 的职责（过程真相唯一源）」 vs codex `other/people-todolist/`（redline 36）——本方案部分让渡 MG 的 docs/ 收编哲学，换 git 可见性 |
| 已跑的机械门与 verdict | 当场复跑读数原文 `docs/changes/e2e-records/gate-raw-20261008-4bd0a6d-recheck.log`（33/0 + 35/0 + 4 passed + 可红 59/59 + 撤证 34/1 恰红 A7） |
| 规则评审证据 | `docs/changes/reviews/session-decision-rules-d1~d5-verdicts-20261008.md` 五轮判决 + 落地批执行记录 `docs/changes/e2e-records/E2E-20261008-session-rules-landing.md` |
| 回滚点 | 删 `other/handoffs/` 两行登记即回 docs/ 承载态（交接单迁移 `docs/changes/handoffs/`，代价见 B 案）；无代码回滚面 |

## 6. 用户回复后的处置动作（AI 填，用户可核）
1. 收到 A 案（已发生）→ 建 `other/handoffs/` + `done/`；2. 项目目录说明.md 登记 other/handoffs 职责 + 与 codex 同构声明；3. AGENTS 结构定版条两行（含「已获用户点头（2026-10-08 选 A 案，凭据 = 本单）」）；4. AGENTS 状态链补记 `4bd0a6d` 两行（已实施待验收 → 验收通过（D5 终稿轮；当场复跑读数见归档 log））；5. 本单标注「已执行」，待用户抽查认可后移入 `done/`。
