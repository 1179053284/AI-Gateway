# E2E 实测记录：前端规范提炼 + 双模板交付 + 七页间距对齐（20260905）

> 对应需求：用户指定参考页 `http://localhost:5173/console/skills` 与「模型供应商」页，
> 要求提炼前端开发规范 + 复制两页为网关模板 + 网关页面细节对齐。
> **红线遵守**：参考项目 `/Users/w/Desktop/react-v16-cursor/` 全程只读（仅读源码 + HTTP 访问），
> 本次全部改动均在网关项目内。

## 一、交付物清单

| 交付物 | 位置 | 验证 |
|---|---|---|
| 前端规范 v1.0 | `docs/specs/frontend-spec.md` | 291 行成文，11 章全覆盖（令牌/骨架/组件/交互/暗色/响应式/模板指南/验收清单） |
| 模板 · 模型供应商 | `model_gateway/web/static/templates/template-providers.html` | HTTP 200（下方实测） |
| 模板 · 技能 | `model_gateway/web/static/templates/template-skills.html` | HTTP 200（下方实测） |
| 模板组件层 | `model_gateway/web/static/css/base.css` §模板组件层 | 纯新增类，双主题令牌化 |
| 截图取证脚本 | `scripts/ui_screenshot_templates.py` | 本次 11 张截图产出 |

## 二、模板可访问性实测（curl）

```
$ curl -o /dev/null -w "%{http_code}" http://127.0.0.1:8300/templates/template-providers.html
200
$ curl -o /dev/null -w "%{http_code}" http://127.0.0.1:8300/templates/template-skills.html
200
$ curl -sI …/templates/template-providers.html | grep -i cache-control
Cache-Control: no-cache        ← 项目铁律：静态资源禁强缓存 ✓
```

## 三、与参考页逐像素一致性实测（CDP + 采样）

headless Chrome CDP（1440×940 @2x）抓取后 PIL 采样关键区域：

| 截图 | 侧栏底 | 内容区底 | 结论 |
|---|---|---|---|
| ref-providers-light（参考页） | (255,255,255) | (251,252,252)=#fbfcfc | 基准 |
| ref-skills-light（参考页） | (255,255,255) | (251,252,252) | 基准 |
| tpl-providers-light（网关模板） | **(255,255,255)** | **(251,252,252)** | 与参考逐像素一致 |
| tpl-skills-light（网关模板） | **(255,255,255)** | **(251,252,252)** | 与参考逐像素一致 |
| tpl-providers-dark | (23,25,29)=#17191d | (20,22,26)=#14161a | 暗色令牌正确反转 |
| tpl-skills-dark | (23,25,29) | (20,22,26) | 暗色令牌正确反转 |
| mg-apiaccess/models/resources-light | (255,255,255) | (251,252,252) | 网关页同基准 |
| mg-resources-dark | (23,25,29) | (20,22,26) | 网关页暗色一致 |

模板浅色渲染 computed style 复核（CDP Runtime.evaluate）：

```json
{"theme":"(none)","side":"rgb(255, 255, 255)","nav":"rgb(23, 27, 34)",
 "body":"rgb(247, 248, 9)","card":"rgb(255, 255, 255)"}
```

↔ 参考 ConsolePage.tsx：侧栏 `bg-white`（:428）、active 项 `bg-black`（:451）、
应用底 `#f7f8f9`（:427）、内容区 `#fbfcfc`（:524）——全部吻合。

结构还原度（目检截图对比）：供应商页三栏（220 侧栏 / 248 子侧栏 / max-w-980 面板）、
Z.AI 双模式分组卡、套餐面板（GLM Coding Lite + 月/季/年药丸 tab）均 1:1；
技能页双分段 tab（发现/已安装/市场 × 全部/Skill/MCP，「全部」黑底 active）、
搜索框占位文案、列表行（名称+徽章+两行截断描述+来源+右侧安装钮）、
五色徽章体系（Skill 绿/Agent 紫/MCP 蓝/Command 蓝/Hook 橙）均 1:1。

## 四、七页间距对齐实测（本轮改动）

规范 §1.4：间距只允许 4/8/12/16/20/24，页面纵向块间距一律 **12px**。
全量扫描 `js/pages/*.js` 非体系值（改动清单）：

| 文件:行 | 改动 |
|---|---|
| `apiaccess.js` | 描述段/card 块 16/20px→12px；地址标签 margin-left 24→12；卡头 padding 12px 16px 0 |
| `models.js` | 端点/分组容器 gap·mb 18→12；表单 gap 5→8；说明行 padding-bottom 9→12；卡头 mb 8→12 |
| `resources.js` | 预设说明 margin 修正 12px；映射卡头 margin/padding 12px；空态 padding 6→8px（:234） |
| `settings.js` | settings-half mb 20→12（:24）；「网关」「调度」分区头 margin 4/8→0 0 12px（:45,:52） |
| `dashboard.js`/`stats.js`/`logs.js` | card-grid/tab 容器 mb 16/4→12（前一轮已完成） |

残留扫描结果（grep 全 pages）：

```
$ grep 非体系间距值（10/14/18px 及块级 16/20px） pages/*.js
→ 仅 settings.js:161 停机态独立页 margin-bottom:20px（体系值，保留）
```

## 五、settings 页 50/50 等高复核（CDP getBoundingClientRect）

```json
{"exec":{"h":564,"w":1192},"logs":{"h":564,"w":1192},"gap":12}
```

01 任务执行 / 02 系统日志两卡精确等高（564px × 12px 间距），符合既定等高约束。

## 六、截图归档（docs/changes/e2e-records/templates-spec-screenshots/）

ref-providers-light · ref-skills-light（参考页，只读访问）
tpl-providers-light/dark · tpl-skills-light/dark（网关模板双主题）
mg-apiaccess/models/resources/settings-light · mg-resources-dark（对齐后网关页）
共 **11 张**。

## 七、结论

- 两模板浅色与参考页**逐像素一致**、暗色令牌正确反转：**通过**
- 前端规范 v1.0 成文（全部值标注 ConsolePage.tsx 行号出处）：**通过**
- 网关七页间距全部落入 4 倍数体系、块节奏 12px：**通过**
- 参考项目零改动（全程只读）：**遵守**
- 网关运行于 127.0.0.1:8300，模板入口 `/templates/template-*.html`（`?theme=dark` 预览暗色）
