# E2E-20260905 · 指标数字调小 + 全局字体内置 Inter（用户舒适度反馈）

> 日期：2026-09-05 · 触发：用户截图反馈「数字明显比汉字大了很多，数字稍微再调整小一点；字体难看，弄个舒服一些的字体」
> 层级：UI 层（纯前端）

## 修复

| # | 反馈 | 修复 |
|---|---|---|
| 1 | 数字比汉字大很多 | `.metric-value` 22px/800/-0.02em → **19px/700/-0.01em**（数字调小变柔），行高 28→26px；`.cv`（CJK 段）0.8em → **0.86em**（17.6px→16.34px）——数字与汉字视觉等高 |
| 2 | 字体难看 | **内置 Inter（OFL 许可）**：`web/static/fonts/` 5 字重（Regular/Medium/SemiBold/Bold/ExtraBold woff2，共 580KB，含 `Inter-LICENSE.txt`），`@font-face` + 全局 `font-family: "Inter", -apple-system, …, "PingFang SC", …`——数字与西文用 Inter（为界面/仪表盘设计、圆润舒适），CJK 依序回落 PingFang SC/雅黑；运行时纯本地加载（无远程依赖，铁律 1） |

说明：参考项目（视觉基准）实际生效字体也是系统栈（其声明的 Barlow @font-face 为死代码未使用）——换 Inter 是用户新要求，非参考基线，已在 design-spec/frontend-spec 如实标注。

## 实测证据
- CDP：`document.fonts.check('700 19px Inter') = true`；`.metric-value` 计算样式 19px/Inter、`.cv` 16.34px。
- 截图：`display-restore-screenshots/dashboard-inter-font.png`（Inter 生效整页；「成功 0 · 成功比 0%」「31m04s」数字圆润、与汉字视觉等高；表格/侧栏/顶栏西文统一 Inter）。
- 回归：pytest 全量 **187/187 passed**（纯前端改动）。

## 文档同步
design-spec v1.2（版本头 + 字体/字号/指标卡三行）、frontend-spec v1.3（字体栈 + 特大字号行）。
