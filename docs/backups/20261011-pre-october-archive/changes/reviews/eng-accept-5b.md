# eng-accept-5b — Round-5 后端验收（B 片）：红点未读数的文件事实源 / 并发 / 跨日 / CLI

审查人：senior backend engineer（只读）。运行门：
`pytest tests/unit/test_v2_ops.py tests/integration/test_int_v2_ops_isolation.py tests/integration/test_int_v2_zcode_admin.py -q` → **78 passed**（HEAD）。
复现脚本 `/tmp/mgw_repro.py`；真 CLI 沙箱 `/tmp/mgw-cli`（`MG_CONFIG`/`MGW_ZCODE_ACCOUNTS`/`MGW_OPS_LOCK_DIR`，repo `data/` 未被写）。

结论一句话：**文件是唯一事实源成立**（进程内计数器 `ops_failed_unread` 已从全仓清除，仅剩测试 fixture 的字段名）；跨日/坏输入不撒谎；但**保留策略漏了 ops-results**，且 **ack 返回值 `cleared` 会在 ack 自身双读的窗口里多报**，两处 TOCTOU 组合**无判据**。

## 逐点判定

### 1. Ack 水位 vs 交错 —— 判定：基本 PASS，附 轻 缺陷 + 无判据
`ack_reports`(runner.py:512) 先 `_report_rows` 计数 → `len(rows)` 写水位；`unread_failures`(runner.py:489) 用 `rows[acked:]`。
- **复现（P1）**：在 ack 首读与写水位之间追加一条失败行 → `watermark_rows=1`（用的是**追加前**的计数），`unread_after=1`。**被追加的行没有被吞**（红点仍亮）——方向正确，单源成立。
- **轻缺陷**：同轮 `cleared=3` 而实际只清 2 —— `ack_reports` 内 `cleared = unread_failures(base)`(:522) 做**第二次独立读**，会把窗口内新行计入返回值，但水位没吃它。`/admin/api/ops/ack` 响应 `{cleared}`(admin.py:400) 与日志因此**报多**。用户无感（点仍亮是对的），仅数字撒谎。
- **中（固有，建议记录不判红）**：若失败行在 ack **首读之前**落地、用户从未见过 → 被水位一并确认。ack 语义=清"当下全部"，无行级 ID 无法避免；cron 与 ack 同刻的概率极低。
- **无判据**：`test_ack_is_the_clear_exit_and_only_eats_acked_rows`(test_v2_ops.py:326) 只测"ack 完成后**再**追加"(:337-338)；**ack 调用内部**的追加窗口无任何断言。

### 2. 跨日翻转 —— 判定：PASS，组合无判据
水位带 `{date,rows}`；`unread_failures` 仅当 `ack["date"]==today` 才用 `rows`，否则 `acked=0`(:500-505)；读的是 `_results_path(base,today)`——**按日分文件**。
- **复现（P2）**：昨日水位 `{date:yesterday,rows:99}` + 今日 1 条失败 → `unread=1`（既不 0 也不复现昨日）。
- 判据：`test_unread_ignores_yesterdays_file`(:347-358) 证明"昨日文件不被读"；`test_ack_is_the_clear_exit...`(:338) 证明水位后新失败重新计入。
- **无判据**：「ack 文件 dated 昨日 + 今日有行」这一**具体交错**无断言（靠代码 + 我的复现覆盖，非测试）。

### 3. 保留策略 —— 判定：中 缺陷
`retention_days`(schemas.py:81) 的清扫在 `stats/events.py:82-96`，`:89` **只匹配 `events`/`switch` 前缀**。
- `ops-results-*.jsonl` 与 `ops-results-ack.json` **无任何地方清理** → **无限增长**（每个 cron tick + 每次 CLI 各追加一行，7×24 网关日积数千行）。
- **不产生谎报**：`unread` 只读当日文件，陈旧文件永不被读；纯磁盘膨胀。
- **无判据**：无测试覆盖 ops-results 的清理/陈旧日期不被读（`test_unread_ignores_yesterdays_file` 只证"不读"，未证"被删"）。

### 4. 坏输入 —— 判定：PASS，无判据
`_report_rows`(:470) 逐行 try/except ValueError 跳过 + `isinstance(row,dict)` 过滤；`unread_failures` 对 ack 读 `(OSError,ValueError,TypeError)` 兜底；`r.get("failed") or []` 容忍缺键。admin `ops_runner_unread`(:126) 再套 `except Exception: return 0`，**5s 轮询 `/admin/api/status` 不可能 500**。
- **复现（P4）**：半行(无换行)+非 dict `[1,2,3]`+缺 `failed` 的 dict+字符串行+**损坏 ack 文件**混布 → `unread=2`（只数两条合法失败），不抛；`ack_reports=2` 不抛。
- **无判据**：全仓无一条测试写入畸形行/损坏 ack——仅代码审查 + 我的复现。

### 5. CLI ack 纪律 —— 判定：PASS
真 CLI 无账号轮（离线，不碰上游）：打印「无账号参与」、退出码 2、**未 POST ack**，且 `write_report`(cli_zcode.py:238) 已在 `return 2` **之前**落盘 → `/tmp/mgw-cli/usage/ops-results-20260928.jsonl`（正是 `default_usage_dir`→`unread` 读的那个目录），repo `data/` 未污染。
- 判据：`test_clean_round_does_not_ack`(:270-291) `acks==[]`；熔断轮(:307) `acks==[]`；失败轮 `test_failure_round_acks_once_and_lands_in_the_pointer_file`(:311-341) `acks==["/admin/api/ops/ack"]` **恰好一次** + 打印路径文件含失败原因。ack 仅在打印失败明细之后调用（cli_zcode.py `_ack_failures` 于 for-print 之后 ~289）。

## Vacuous-assertion 嫌疑
- `test_ops_ack_is_idempotent`(:208-212) 只断言空目录两次 `cleared==0`——正向清零由 :196 覆盖，本用例本身偏弱（非假阳性，但零信息）。
- `test_ack_is_empty_dir_safe`(:341-344) 只走 empty 路径，不碰交错。

## 撤修复红证清单（请主 agent 逐条跑）
1. `ack_reports` 水位改为写时**重读** `len(_report_rows())`（模拟晚计数）→ 期望 `test_v2_ops.py:338` 变红（证明吞行防线）。
2. 去掉 `unread_failures` 的 `ack.get("date")==day` 判定(:501) → 昨日 dated 水位会吞今日 → 期望 P2 复现转红（当前**无测试**，红会暴露判据缺口）。
3. `_report_rows` 去掉 `except ValueError`（坏行不再跳过）→ 期望 `/admin/api/status` 复现 500（当前**无测试**）。
4. `stats/events.py:89` 前缀加 `ops`（误纳 ops-results）→ 与 P2 陈旧日期读取对撞，确认保留改动的影响面。
5. `cli_zcode.py` 把 `_ack_failures()` 移到 `if report.failed` **之外**（无条件清零）→ 期望 `test_v2_cli_zcode.py:291` 与 `:307` 变红。

## 未验证
- 失败轮真 CLI 端到端 POST `/admin/api/ops/ack`（禁打上游，需活的网关 + 凭据 fixture）未实跑；"恰好一次 POST"依赖单测 monkeypatch 版 `admin_post`。
- 真多进程 `O_APPEND` 下"一条超长行被两个写者交错劈成两条畸形行"→ 该失败被 `_report_rows` 静默丢弃——**仅在逻辑层模拟，未在真实并发下复现**。
