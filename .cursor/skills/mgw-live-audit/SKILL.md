---
name: mgw-live-audit
description: Model-Gateway 实盘「只读核查 / 就绪与可用性审计」的可复跑 playbook：只读基线探针 → 实盘分档复刻 → 隔离实例 + 假上游按账号身份头分派 → 事件流水对账（字段是 system_model）→ 契约 vs 现状刻画双标签 → 三态归因 → 运行时归属核查（谁在驱动这条自动腿）→ 读数纪律与未验证清单。触发语：只读核查 / 看实盘 / 可用性评估 / 就绪审计 / 为什么显示成这样 / 某号某通道能不能投用 / 这条自动更新是谁在驱动。边界：本支不用于改源码与写真实配置（全程只读，真出站需用户批准）；隔离实例配方由本支独占（mgw-delivery-round 引用本支，本支自闭环不依赖其他工程的文件）。
metadata:
  version: "1.0.1"
---

# 实盘只读核查与就绪审计（Model-Gateway）

## 0. 授权与边界（先过这一关再动手）

- **全程只读**：`GET` 探针、读 `coding/data/**`、读日志；**零写入零点击**（要证明"只读"就显式验证关窗归零/无 POST）。
- **需用户逐次批准**：真实厂商出站（烧额度）、重启/停止 `:8300`、写真实 `coding/data/config.yaml`、`git push`。
- 测试面默认**不打真实上游**：用隔离实例 + 假上游（本机已有先例，见 §3）。
- 🟡 发现差异时**禁止回避式交付**（Q35-③）：不许"跳过该成员/隐藏它/让门变绿"；正解 = 在根因处整形（出站适配层吸收）或如实报告并给方案。
- 读数与结论分栏：`已验证`（本机实测）/ `未验证`（缺什么前置、为什么代理证据不算）。**不许拿单测/假上游冒充生产实证**。

## 1. 只读基线（先摆事实，再谈判断）

命令字面在 `.cursor/memory/runbook.md`（§2/§4）；探针库存 = `bianyiandhuanjing/scripts/probe_*.py` **11 支**（含 `probe_mapping_census` / `probe_quota_sum_inline` / `probe_zcode_live_shape` / `probe_vendor_icons` 等，各有 docstring 说明用途）。

最小基线四问（每条抄输出 + 采样时刻）：
1. **后端真上线了吗**：`GET /health` + `/openapi.json` 路径计数（新端点不在册 = 没重启）。
2. **盘上配的是什么**：`coding/data/config.yaml`（读**实盘真值**，不是缺省值）+ 该文件 md5。
3. **运行态是什么**：`coding/data/upstream/<product>/accounts/*/runtime.json` 聚合（`quota.checked_at` 是 **ISO 串不是 epoch**；额度分三档：0 / `None` / `no_plan`——只看 `remaining=0` 会漏掉整档）。
4. **节奏是什么**：`coding/data/usage/ops-results-*.jsonl` 相邻 `ts` 差 = 真实刷新节奏（名义配置值 ≠ 实测行为值，两者要分开写）。

## 2. 隔离实例配方（🔴 唯一主人；跑任何"要改配置/要新端口"的验证都用这套）

1. `cp -R coding/data <仓库外路径>`（例如 `/tmp/mgw-probe/data`），只改副本端口。
2. 启动**每一条命令都带** `MG_CONFIG=<副本>/config.yaml`（**不能靠 `cd`**；数据目录 = 配置父目录）；`nohup coding/.venv/bin/python -m model_gateway.main &`。
3. 🔴 启动行必须自证**"枚举到 0 个账号"**——漏设 `MG_CONFIG` 会让账号根回落真实 `coding/data/`，把真实账号带进临时实例（已发生过一次）。
4. 杀进程按 PID：`lsof -nP -iTCP:<port> -sTCP:LISTEN`；**禁 `pkill -f`**（`env VAR=…` 前缀不在命令行，匹配不到 ⇒ 旧进程占端口、旧代码冒充新代码）。
5. 配置写入后有**热重载滞后**：隔一拍复读再判定，物化/发布类结论至少复读一次。

## 3. 假上游（按每号身份头分派行为）

- 先例：`coding/tests/integration/test_zcode_glm_flash_failover.py:39` `class FakeZcode`——按 `X-Device-Mid` 逐号分派成功/失败/空信封/429/超时/流式中途断。
- 逐条覆盖：4xx 风控 / 200 自有信封 / 429 / 5xx + 阈值 / 超时 / 流式提交后中断 / 额度 0 / 无套餐 / 熔断 / **对外声明 vs 实际派发分叉**。
- 每条用例标 **「契约」还是「现状刻画（=缺陷证据）」**——两者混在一张表里会让"当前就是这么错的"被读成"设计如此"。
- **反证用例**（证明判据不空转）：用 `error_rules` 改判分类 ⇒ 预期换号行为变化；改不动 = 判据恒绿。

## 4. 事件流水对账（取代单发探针）

- 数据：`coding/data/usage/events-YYYYMMDD.jsonl`；🔴 模型字段是 **`system_model`**（没有 `model` 字段）；行内还有 `final_resource` / `switch_count` / `resource_attempts` / `status` / `error_summary` / `stream`。
- 按 `(网关模型, stream, 状态, 实际承接资源)` 聚合——**"池内某成员收不下某种形状"** 与 "整族拒绝" 是两回事（2026-10-04 单发采样把它读成族级约束，被事件流水推翻）。
- 探针自坑两条：`max_tokens` ≥2048（否则 token 全进 `reasoning_tokens` ⇒ 正文空但事件行 `success`）；流式**别只取首帧就断**（会被误读成"上游返回空"，实为 `aborted`）。

## 5. 运行时归属核查（"这条自动腿到底谁在驱动"）

- 三处异源证据互相印证，缺一处就会混为一谈：① 宿主定时任务表（`qoder_cron list`，注意"UI 里两行"常常是"一条任务 + 它的执行会话"）；② 网关进程内调度腿（`main.py::_maybe_start_ops` / `ops/runner.py::Scheduler` / 各 tick，用 `grep -rn "create_task\|Scheduler(\|sched.start"` **穷举**，别只认已知那几条）；③ 实盘配置真值 + 台账观察期表。
- 判"闭环"要查**写者**不只查读者：例如缓存过期后**有没有人在续**（`grep -rn ... 看写缓存的调用点是否只在管理端 HTTP 腿上`）——没人续 = 不闭环。
- 输出固定三段：**内置腿 / 外部看门狗 / 待裁定项**，并声明看门狗自身零出站/零重启/零提交。

## 6. 三态归因与"两个真相"的判别

- 每条差异强制归到三态之一：**(a) 自家门自拦 / (b) 上游拒绝 / (c) 成功**——写清是哪一态，禁止"反正不对"。
- 界面说而盘上没有 ⇒ 走"三面对账"：`GET /admin/api/config` 的 `product_models`（产品位）× `models[].resources[]`（条目）× 派生位 `mapping_enabled`，再逐产品 `GET /admin/api/accounts/{p}/catalog`（`map_enabled` **三态**：`true/false/null`，`null` = 没落库，**不许当成"开着"**）。
- 🔴 索引空间混用是静默跳过的头号成因：先取一侧 id 集合再按 id 交叉引用；症状是"一个都不命中"时先怀疑**筛错字段**，别下"数据没有"的结论。

## 7. 读数纪律（写进交付文档抬头）

- 每个被引用的源文件先 `md5 -q` + `git diff --numstat HEAD -- <file>` 登记并行会话未提交面（**引用前当轮重测**，数字会变）。
- 口径三件套写抬头：**树 md5 / 端口 / 采集时刻**；时间一律折算成本地时刻（epoch 毫秒用 python 一次算完）。
- 数字只抄运行器/接口输出行，不手推；"名义配置值"与"实测行为值"分栏。
- 未验证清单**逐条**写：缺什么前置、为什么不能做、要用户点头的是什么。

## 8. 交付形态

一句话结论（含"我知道的边界"）→ 结论表（对象 / 判定 / 证据 file:line 或读数）→ 实盘读数（逐字 + 采样时刻）→ 实盘归属表（谁在驱动）→ 契约 vs 现状刻画双标签表 → 未验证清单 → 需要用户裁决的点（每条带反转触发）。
发现自己的旧结论有错 → 开头"更正声明"逐条列。

## 9. 红线

- 不改源码、不写真实配置、不重启 `:8300`（需批准）；隔离实例全部在 `/tmp` 且跑完清理（规矩 12）。
- 不做"单发采样下结论"（至少覆盖两种承接资源再谈通道级结论）；不把 `aborted` / `reasoning` 占满的空正文读成上游故障。
- 发现真实缺陷 → 报告 + 建议，**不当场改产品代码**（那是 delivery-round 的事）。
