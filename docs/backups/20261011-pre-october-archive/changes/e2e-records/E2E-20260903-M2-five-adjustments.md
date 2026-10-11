# E2E 实测记录（2026-09-03，M2 五项调整 · 后端 + 前端六页 + 系统控制）

> 环境：macOS · 网关 `0.0.0.0:8300` · 管理令牌 `mg-admin-e2e-2026`（allow_admin）/ 调用令牌 `mg-trae-e2e-2026`
> 对应需求：PRD v1.4（D1–D5）/ tech-design v1.1 / design-spec v0.3 / test-cases v1.1
> 测试基线：pytest 181/181（M1 141 + 新增 UT-24~29 / INT-42~47 等 40 项）
> 界面证据：DOM 快照 `docs/changes/e2e-records/m2-ui-screenshots/dom-snapshots.txt`（六页全文）

## 总表（五项调整逐项）

| 调整项 | 结论 | 关键证据 |
|---|---|---|
| ① 日志页面化 | ✅ | 总览页无常驻事件块（DOM 快照 dashboard 节：指标卡 + 趋势 + 资源表，仅「查看日志」链接）；请求日志独立页双 tab（请求流水 103 条分页 100/页 + 切换事件 8 条），筛选（状态=failed → 22 条）、展开行（request_id/usage/错误/attempts 明细）浏览器实测通过 |
| ② 扩展性 | ✅ | `GET /admin/api/presets` 200：sensenova-api（按量付费）/ sensenova-tokenplan（积分制）/ custom（—）+ billing_display 降级；stats 五维 `dimensions=[by_model,by_resource,by_token,by_provider,by_account]` 数据驱动，前端维度 tab 不写死；CSV 导出 8 行 |
| ③ 模型开关 | ✅ | 界面圆点禁用 deepseek-v4-pro → 保存 → `/v1/models` 7→6；直名/别名（SenseNova-6.8-Flash-Lite）调用 404 `code=model_disabled`；`/v1/messages`（Anthropic 端点）同样 404；重新启用即时恢复 7 模型 |
| ④ 系统启停 + 双击脚本 | ✅ | `POST /admin/api/system/restart` → uptime 2.7s（execv 新进程）同端口恢复；`POST /admin/api/system/stop` → 确认弹窗 → 页面提示态（「网关已停止 · 需双击 启动网关.command」）→ 进程 exit 0 + 锁释放；`./启动网关.command` 启动 health ok（PID 39646） |
| ⑤ 单实例 | ✅ | 运行中二次启动 `python -m model_gateway.main` → exit 3 + 输出「已有实例运行中：后台地址 http://127.0.0.1:8300/（PID …）」；再次双击脚本同拒绝 + 窗口保持（read 等待） |

## 分项证据摘录

### ③ 模型开关（浏览器 UI → API 全链路）

```
# 界面操作（ego-browser 实测）：模型映射页点击 deepseek-v4-pro 行尾圆点
禁用后: {"off":true,"dotOn":false,"dirty":true}   # 行置灰 + dirty 标记
保存 toast: ["配置已保存并生效"]

$ curl /v1/models → ["sensenova-6.8-flash-lite","deepseek-v4-flash","glm-5.2","kimi-k3","sensenova-u1-fast","sensenova-u1.5-lite"]  # 7→6
$ POST /v1/chat/completions {"model":"deepseek-v4-pro",...}
  → 404 {"code":"model_disabled","message":"模型 'deepseek-v4-pro' 已禁用，可在管理界面开启"}
$ POST /v1/chat/completions {"model":"SenseNova-6.8-Flash-Lite",...}（别名归一后命中禁用模型）
  → 404 model_disabled
$ POST /v1/messages（Anthropic 端点）→ 404 {"type":"invalid_request_error","code":"model_disabled"}
# 重新启用（PUT config enabled=true）→ /v1/models 恢复 7 模型 ✓
```

### ④ 系统运行控制

```
$ curl -X POST -H "Authorization: Bearer mg-admin-e2e-2026" .../admin/api/system/restart
  → {"status":"restarting","message":"网关重启已受理：优雅停机后同端口自动重启"}
$ sleep 3 && curl .../admin/api/status
  → {"version":"0.1.0","uptime_ms":2697,...}   # uptime 重置 = execv 映像替换新进程 ✓

# 浏览器实测停止：设置页「停止网关」→ 确认弹窗（取消/确定）→ 确定
停止后页面: {"stoppedPage":true,"hasCommand":true}   # 提示态 + 启动网关.command 指引 ✓
后台进程退出码 0（优雅停机）✓；data/gateway.lock 已删除（锁释放）✓

$ ./启动网关.command（等价双击）
  → health: ok；锁重新登记 {"pid":39646,"port":8300,...}
```

### ⑤ 单实例锁

```
$ .venv/bin/python -m model_gateway.main（已有实例运行时）
  已有实例运行中：后台地址 http://127.0.0.1:8300/（PID 39000、启动时间 2026-09-03T12:30:45+08:00）
  exit_code=3
$ ./启动网关.command（二次双击）
  已有实例运行中：后台地址 http://127.0.0.1:8300/（PID 39646、…）
  已有实例运行中，后台地址见上方输出。窗口保持开启，查看后可自行关闭。
```

### ① 请求日志页（浏览器实测）

```
请求流水 tab: {"tabs":["请求流水","切换事件"],"active":"请求流水","count":"共 103 条","rowCount":100}
筛选 status=failed: {"count":"共 22 条"}
展开行: request_id：req_a3058abb32ac · chat · usage：estimated · 错误：[network] timeout: …（含 attempts 明细）
切换事件 tab: {"active":"切换事件","count":"共 8 条","rows":8}
```

### ② 数据看板（浏览器实测）

```
{"periodTabs":["今日","近 7 天","近 30 天"],
 "dimTabs":["按模型","按资源","按令牌","按厂商","按账号"],   # 由 /admin/api/stats dimensions 键生成
 "activeDim":"按模型","tableRows":7}
切「按资源」→ 首行 (none)/31/0/22/9/0%（历史行空值归组兼容）✓
CSV 导出 toast: ["已导出 8 行"]；Chart.js canvas 渲染 516×258 ✓（修复点：v4 仅接受 canvas 元素）
```

### 产品接入开关（providers[].enabled，design-spec §2.6 新增字段）

```
# 界面禁用商汤 TokenPlan → 保存
禁用产品后: {"badge":["已停用"],"configDimmed":"0.5","dirty":true}   # 专属配置区收起置灰 ✓
$ POST /v1/chat/completions {"model":"glm-5.2",...}
  → 503 {"code":"NO_RESOURCE","message":"无可用资源"}   # 调度侧资源全部退出 ✓
# 展示口径（修复点）：/admin/api/status 资源含 "available":false
禁用展示: 资源健康 0/7 存在不可用资源（停用/冷却）· 徽章「停用」×7
恢复后: 7/7 可用 ✓
```

## 本轮修复的问题（附定位）

1. **models.js 语法错误**（`flatMap` 链多余右括号，`node --check` 定位 223 行）——此前 3/6 页状态下浏览器整页加载失败，已修复并通过全部页面模块 import 检查。
2. **`/admin/api/status` 端点缺失**——main.js 令牌门/顶栏轮询指向该端点但后端无实现（404 → 令牌永远无法通过）。已补轻量 status 端点（不复用 overview：后者读全日事件文件，不适合 5s 轮询）。
3. **Chart.js v4 不接受容器 div**——传 div 时 canvas 不创建。已改为显式 `<canvas>` 元素。
4. **资源快照不反映 key/provider 禁用**——`snapshot_resources()` 新增 `available` 综合口径（status + 开关），总览「资源健康」与状态徽章优先显示停用态。

## 测试基线

```
$ .venv/bin/python -m pytest tests/ -q
  181 passed, 184 warnings in 37.39s   # M1 141 + M2 新增 40（UT-24~29 / INT-42~47 等）
```

## SHELL（待用户验收项）

- E2E-07 Trae 实配（M1 移交项不变）
- macOS 双击 `启动网关.command` 的 Finder 双击路径（本记录以 `./启动网关.command` 终端等价执行；Finder 双击行为依赖系统「打开方式」设置，需用户侧确认）
