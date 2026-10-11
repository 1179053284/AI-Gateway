# E2E-20260905 · 系统显示恢复（资源口径纠正 + 日志页残留清理）

> 日期：2026-09-05 · 触发：用户「系统现在显示内容，先把系统显示恢复好」
> 层级：API 层（admin 总览口径）+ UI 层 · 依据：用户对齐结构定论「资源 = 厂商+账号+Key」

## 问题与根因

| # | 显示问题 | 根因 |
|---|---|---|
| 1 | 总览「资源总数 7」「资源健康 健康 7 · 总数 7」，但实际只配置 **1 个资源** | `admin.py` overview `counts.resources = len(resources.registry)`——注册表 key = `(resource_id, vendor_model)` **映射条目**，1 资源 × 7 模型 = 7；资源健康表 `snapshot_resources()` 也按映射条目逐行（显示「备注/厂商模型」7 行） |
| 2 | 请求日志页右上角裸露无样式文本 `data/usage/events-*.jsonl` | `logs.js` 残留 page-head（违背 Q22-③「7 页 page-head 去重」）；文件路径说明设置页 02 区已有，此处冗余 |

## 修复

1. `core/resources.py`：`snapshot_resources()`（按映射条目）→ **`snapshot_by_resource(config)`**（按资源聚合：状态聚合 disabled > 全 invalid > 全非 active(cooldown) > active；C 取条目最大、in_flight 求和、冷却取剩余最大，附 name/vendor/account/models 映射数）。
2. `api/admin.py`：`/admin/api/overview` 与 `/admin/api/status` 换用资源口径快照；`counts.resources = len(cfg.resources)`、`counts.vendors` 按配置资源 vendor 口径（原为注册表条目口径）。
3. `dashboard.js` 资源健康表：行单元格改显示资源名（`r.name`），tooltip = 厂商 / 账号 · 映射模型数；表头 tooltip 注明聚合口径。
4. `logs.js`：删除残留 page-head 裸路径块。
5. `tests/integration/test_int_chat.py`：overview 断言同步资源聚合口径（`r["name"] == "资源A"`）。

## 实测证据

- API 实测（重启后 `GET /admin/api/overview`）：
  `counts = {"vendors": 1, "resources": 1, "models": 7}`；
  `resources = [{"name": "商汤 TokenPlan·主Key", "vendor": "商汤 TokenPlan", "account": "主账号", "status": "active", "available": true, "C": 0, "in_flight": 0, "models": 7}]`
- CDP DOM 断言：总览 8 卡 `资源健康 = 健康 1 · 总数 1`、`资源总数 = 1`、`可用模型总数 = 7`；健康表 1 行「商汤 TokenPlan·主Key」；日志页 `hasPageHead:false, hasRawPath:false`。
- 截图：`display-restore-screenshots/dashboard-restored.png`、`logs-restored.png`。
- 回归：pytest 全量 **187/187 passed**（含更新后的 INT 断言）。

## 影响面报备
- `/admin/api/status` 与 `/admin/api/overview` 的 `resources[]` 字段形态变更（resource_id→name 等全量消费者已排查：dashboard.js、test_int_chat.py，无其它消费方）；`snapshot_resources` 方法已整体替换（无残留调用，规矩 12 自查通过）。
