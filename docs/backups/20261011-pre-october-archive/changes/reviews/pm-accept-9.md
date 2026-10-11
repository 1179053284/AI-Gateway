# PM 第九轮验收报告（2026-09-28）

验收人：产品经理面板（第九轮）。上一轮唯一阻塞 = S-28（恢复时刻时间基用错：生产 `ResourceManager` 默认 `time.monotonic`，界面按墙钟格式化）。本轮独立复跑、不采信实现者自述。

## ① 结论：**通过**

S-28/S-31 在**真 `create_app` + `TestClient`** 回环里逐字复核成立；S-22/S-29/S-24/S-26④ 四种故障经实测互不相同且可行动；三道门全部为**本面板自己跑的**结果；文档口径与 PRD v1.17 / Q28-⑦ 对齐。无新增阻塞项。

- 开工 `git status --porcelain`：30 M + 52 ?? = 82 行（v2.0 开发中的既有脏态）
- 收工 `git status --porcelain`：`wc -l` = **82**（同集合，md5 `6802bee5…`）；本轮我的全部实验均落在 `/tmp/mgw-accept-9-pm/`，本报告在 gitignore 的 `docs/` 下
- `find data -newermt "2026-09-28 15:30" -type f` → **空**（未污染用户数据目录；`:8300` 未启动/未触碰，`~/.zcode`/`~/.workbuddy*` 未碰，无真实上游请求——探测仅指向 `example.invalid` 且未发起调用）

## ② 逐项核验表

| 项 | 我跑了什么 | 读到什么 | 判定 |
|---|---|---|---|
| S-28 时间基 | `/tmp/mgw-accept-9-pm/check_overview.py`：真 `create_app(port 配置在 /tmp)` + `TestClient.get('/admin/api/overview')`，断 `mgr.clock.__name__ == "monotonic"` 后取列 | `[0] production manager clock = monotonic`（main.py:188 默认钟，注入点无生产调用方）；渲染见 `_rendered_last_error` resources.py:216 `wall = wall_now if … else time.time()`，钟点 = `time.time() + 剩余` 倒推 | ✅ 单调钟基底下界面仍出真墙钟 |
| S-31 两列同瞬间 | 同一资源挂两条映射：60s 短退避 + 30min 熔断，读**同一次响应**里两列 | 原文抄录：`cooldown_remaining_ms = 1799996`、`last_error = '429 短退避，至 16:28'`；独立墙钟复算 `strftime(now+1799.996s)` = **16:28**，与列同一瞬间；60s 条目自己的到期钟点（15:59±）未出现；单调钟数值格式化出的假钟点未出现 | ✅ 用户无需任何换算；两列指同一瞬间 |
| 到期不挂过去钟点 | res-b bench 0.5s 后重取 overview | `[5] expired res-b: status=active remaining=0 last_error='额度耗尽'`（无「至」）；`_with_until` 过期分支同样只回裸原因；预渲染过的旧串进 `_with_until` 被剥尾重渲染，一行仅一份钟点 | ✅ |
| 跨午夜 | `fmt_recovery_clock(23:50+1800, 23:50)`（production 走同一 epoch 入口） | `至 明日 00:20`；21:50 当日 → `至 21:50` 无「明日」 | ✅ 读时重算，两个时刻各自说得对 |
| CLI ⚠ 块 / `last_error` / 日志同口径 | 读 quota.py:365-395 `until_label`/`_with_until` → 均落到 `core/resources.fmt_recovery_clock`（唯一口径）；`enter()` quota.py:495 落盘前 `without_clock_suffix` 剥尾 | circuit `reason()` 动态渲染 `ZCode 风控熔断，至 16:28` 与列口径逐字一致；落盘只存裸原因 | ✅ 与 Q28-⑦ 定稿两条逐句对表成立 |
| 四故障可分辨 | `/tmp/mgw-accept-9-pm/check_failures.py`：真 `run_once`（chmod 500 锁目录/usage 目录制造故障、fake claim 记录发起）+ 真 `cli_zcode._claim`（仅 patch `runner.run_once` 回灌真实故障轮 report、`default_usage_dir` 指 /tmp、`_ack_failures` 防触碰 :8300） | 见下方对照表 | ✅ 四者互不相同且可行动 |
| 文档残留 | `grep 至 HH:MM|fallback_lock_dir|/tmp` × README.md/README.zh-CN.md/design-spec.md/frontend-spec.md | 四文件**零命中**旧口径；README:113-117 与 zh:110-113 退出码表 0/1/2/3 语义 + 「3 与 setup 的 3 同码不同义」与 cli.py:62-65 epilog 逐字一致；`runner_mod` 已无 `fallback_lock_dir` | ✅ |
| §20 不做清单 | 读 `usable()`(runner.py:202-218)、`.write-probe`(:209)、`SANITY_HORIZON_MS`(quota.py:318/355-361)、K 段(scripts/)、`wall_now`(:195) | 无新页面/新端点/新轮询/第二本账：usable 是既有一次性探测点，SANITY 只在既有读取处拒坏值，K 段在测试脚本、不入产品；`wall_now` 生产调用方为零 | ✅ 未越界（评述见 ④） |

### 四故障 × 四出口对照表（全部来自我这一跑的实际输出）

| 故障 | CLI 抬头 | 退出码 | 顶栏红点 | ops-results-*.jsonl |
|---|---|---|---|---|
| S-22 开局不可写 | `✗ 失败 2 个（其中 2 个**未发起**：互斥锁不可用，本轮拒跑 → 查数据目录权限）`，逐条含「不可写：…本轮未对任何账号发起操作」 | **1**（熔断外） | **亮**（unread=2，本轮实测） | **落盘**（failed×2） |
| S-29 中途不可写 | `✓ 已领取 1 个` + 同款「未发起」抬头，逐条为「**在本轮中途**不可写…本账号及其后共 2 个账号均未发起」；skipped=[] | **1** | **亮** | **落盘**（1 success + 2 failed） |
| S-24 收尾失写 | 不经 CLI（cron 腿）；日志「运营锁释放失败…→ 交给超龄回收，不向上抛」 | n/a | 仅真实账号失败才亮 | 正常行不丢 |
| S-26④ 落盘失败 | 抬头为**普通失败**（无「未发起」字样）+ stderr `⚠ 本轮结果未能写入 …（数据目录不可写？）→ 顶栏红点不会记录这些失败` | **1** | **不亮**（unread=0，且已明说） | **无文件**（实测 glob=[]） |

补充：S-22/S-29 共用前缀 `LOCK_REFUSAL_PREFIX`（判别锚）但「开局/中途」措辞与 success 有无互斥可分；S-24 正确姿势复测（round 中 chmod）→ `rounds=['round-1','round-2'] errors=0 threading锁已放` = 失写自愈、调度存活。退出码不区分三类（皆 1）是**设计内**（3 专留熔断，Q28-⑥⑧），区分由「未发起」抬头 + 文件/红点在否完成，均可行动（各条点名目录与处置动作）。

### 三门独立复跑（逐字，本面板自己跑的）

```
$ .venv/bin/python -m pytest -q --basetemp=/tmp/mgw-pytest-pm9 -p no:warnings
701 passed in 126.15s (0:02:06)

$ node scripts/verify_v2_frontend.mjs /tmp/mgw-accept-9-pm/overview.json        # 我自己造的（无告警）payload
✗ 基线本身就有 11 条红（A1,A2,A3,A4,A5,A6,A7,A8,A9,B3,K1）…                     # 空告警 payload 下拒绝空过，非假绿

$ node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json          # 本面板 16:01 运行 ui 门时自产 fixture（mtime 实证）
实测 76 项，通过 76 项，失败 0 项

$ node scripts/verify_v2_frontend.mjs /tmp/mg-v2-visible/overview.json --mutation
可红 76/76；每条断言都有对应变异

$ .venv/bin/python scripts/ui_verify_v2_visible.py --mutation
后端出口实测 12 项，通过 12 项，失败 0 项（并内嵌 node 变异 76/76）
```

## ③ 阻塞项

**0**。

## ④ 非阻塞建议

1. **`wall_now=None` 这个"只为测试存在"的参数可接受，但要设防**：单一注入点、生产默认 `None`、且 S-28 回归用例特意**不注入**（我本轮实测亦走默认路径 + monotonic 基底下真墙钟）——比"整模块塞时钟"更省。建议保持现状 + 在 docstring 的「注入仅为跨午夜可测」旁补一句"生产调用方禁止传入"（现仅靠约定）。
2. 前端门 usage 注释未写明 fixture 必须含 `warnings[]`/熔断行：我给健康 payload 时 11 条红（保守拒过，是好事），但新读者会误以为产品坏了——建议 header 用法行补一句输入契约。
3. 代码内两处旧口径注释（不影响行为）：`quota.py:486` 首句「文案必须带恢复时刻（§17 字面…）」与 `zcode_claim.py:114`「`enter()` 会把它规范成 …，至 HH:MM」——现实现是 enter **剥尾存裸原因**、读时才拼；下一轮顺手把措辞改齐。
4. S-24（cron 腿收尾失写）用户可见面只有网关日志（无红点、无 CLI）：语义上"自愈无需动作"成立，但权限长期坏时与 S-22 的日志会重复刷；可考虑连续 N 轮释放失败并入一次告警文案（不建议为此加端点）。
5. 既有登记未修项 N-1（热重载换下的适配器不 `aclose`）仍开放，维持"待用户定夺"，不构成本轮阻塞。

## ⑤ 未验证清单（如实）

- **:8300 真实实例的顶栏红点浏览器级呈现**：约束禁碰 8300；红点语义经 `unread_failures` 对 /tmp usage 目录直读实测（亮/不亮两态均验），toast/徽章 DOM 层依赖三道门输出，未亲见真实浏览器。
- **`_ack_failures` 对运行中网关的 admin POST 副作用**：为不污染真实用户红点，我 patch 掉了 CLI 的 ack 调用；水位读写语义以 701 条 pytest + `unread_failures` 直读为旁证，非 live 端到端。
- **CLI→网关 `/admin/api/zcode/bench` 内存回写的真机跨进程往返**（两进程场景）：同进程 TestClient 已验渲染，跨进程仅由集成测试覆盖。
- **真实午夜时刻的生产路径**：以冻结 23:50/00:05 的 epoch 入口数学验证 + 读时重算代码路径核实，未在自然午夜挂机。
- **T5a/T5b（WAF、curl_cffi 流式）与真实领取端到端**：§19 手工项，本轮不验。
