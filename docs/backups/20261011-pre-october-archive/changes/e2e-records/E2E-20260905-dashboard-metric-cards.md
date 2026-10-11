# E2E-20260905 · 总览指标卡信息密度与混排字号修正（用户实测反馈两问题）

> 日期：2026-09-05 · 层级：UI 层（纯前端，无后端变更） · 触发：用户截图反馈问题 1/问题 2

## 问题与修复

| # | 用户反馈 | 根因 | 修复 |
|---|---|---|---|
| 1 | 「今日调用」「今日 token」卡的重点信息显示不对，应与「资源健康」卡类似 | `dashboard.js` 把「成功比 0%」「输出 0」作为 `sub` 传入 `metricCard`，渲染成第二行 12px 灰色 `metric-label`，与 22px 主数值层级错乱 | 改为单行大字并列：`成功 0 · 成功比 0%`、`输入 0 · 输出 0`（与「健康 7 · 总数 7」同构）；`metricCard` 移除 sub 参数（8 处调用点同步） |
| 2 | 卡片重要信息里中文与数字视觉字号不一致 | `.metric-value` 22px/800 下 CJK 字面占满 em 高（≈22px），数字 cap 高约 0.7em（≈15px），混排显中文偏大 | `api.js` 新增 `fmtValue()`：值内 CJK 段（`[\u4e00-\u9fff]+`）包 `<span class="cv">`，CSS `.metric-value .cv { font-size: .8em }`（22px→17.6px），视觉等高；先 `esc()` 后包裹，无注入面 |

## 改动文件
- `model_gateway/web/static/js/api.js`（+`fmtValue`）
- `model_gateway/web/static/js/pages/dashboard.js`（两卡单行化；`metricCard` 签名去 sub；数值经 `fmtValue`）
- `model_gateway/web/static/css/base.css`（+`.metric-value .cv`）
- 文档同步：design-spec v1.0（指标卡/字号行 + 版本头）、frontend-spec v1.2（特大字号行）

## 实测证据（headless Chrome CDP，1440×940 @2x）

DOM 检查（`#/dashboard`）——8 张指标卡逐卡断言：

```
[{"label":"运行状态","valueText":"运行中","cvPx":"17.6px","subLabelCount":0},
 {"label":"运行时长","valueText":"0m28s","cvPx":null,"subLabelCount":0},        ← 纯西文不受影响
 {"label":"今日调用（次）","valueText":"成功 0 · 成功比 0%","cvPx":"17.6px","subLabelCount":0},
 {"label":"今日 token","valueText":"输入 0 · 输出 0","cvPx":"17.6px","subLabelCount":0},
 {"label":"资源健康","valueText":"健康 7 · 总数 7","cvPx":"17.6px","subLabelCount":0},
 {"label":"厂商数量","valueText":"1","cvPx":null},
 {"label":"资源总数","valueText":"7","cvPx":null},
 {"label":"可用模型总数","valueText":"7","cvPx":null}]
```

- `#/stats` 回归：7 张指标卡数值均无 CJK（`hasCv:false`），渲染不受影响（该页数值本无中文，样式零变化）。
- 截图：`dashboard-metric-screenshots/dashboard-light.png`（浅色全页 + 指标卡区放大核对）、`dashboard-dark.png`（深色）、`stats-light.png`（看板页）。
- 深浅双主题排版一致（`.cv` 仅字号，无色彩依赖）。

## 回归
- pytest 全量 **187/187 passed**（与 Q22 基线持平，2026-09-05）。

## 影响面报备
- `.metric-value .cv` 仅在 `fmtValue()` 产生的 span 上生效；当前仅总览 `metricCard` 使用。数据看板页 `metric()`（stats.js）未接入 `fmtValue`（其数值无 CJK，接入了也无视觉差异），保持不动。
