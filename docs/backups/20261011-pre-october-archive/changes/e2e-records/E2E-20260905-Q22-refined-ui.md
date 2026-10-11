# E2E 实测记录 · Q22 界面精修：参考项目规范落地（2026-09-05）

> 背景：用户指定参考项目 `/Users/w/Desktop/react-v16-cursor/整体前端代码`（dev server 5173，主参考页 `/console/skills` 即 `ConsolePage.tsx`），要求按其风格与设计规范处理网关页面细节。
> 对应：PRD v1.9 §9-Q22、tech-design v1.6 §4.11、design-spec v0.8、test-cases v1.6（E2E-20 追加⑩项）
> 网关：`http://127.0.0.1:8300/`（运行中）；浏览器：headless Chrome（CDP，`scripts/ui_screenshot.py`，1440×940 @2x）
> 执行方：AI（Trae）；执行时间：2026-09-05（本地）

---

## 0. 结论

| 项 | 结果 | 证据 |
|---|---|---|
| 参考规范提取 | ConsolePage.tsx 五项规范：黑主色 / 无边框软阴影卡片 / 分组侧栏 / 两行顶栏 / 分段式 tab | §1 |
| base.css 重写 | 黑主色令牌（`--brand:#171b22`）+ 参考色板（`#eef1f3`/`#171b22`/`#16d76d`）+ 组件层全套替换；类名契约全保留 | §2.1 |
| JS 语法检查 | main.js + 7 页 + components/api 全部 `node --check` 通过 | §2.2 |
| 线上资源更新 | `/`、`/css/base.css` 含新标记（nav-group-title / crumb-group / metric-ico）；`Cache-Control: no-cache` 延续 | §2.3 |
| 全量回归 pytest | **187 passed**（与 Q21 基线一致；Q22 纯前端改动） | §2.4 |
| 双主题截图 | 11 张 PNG（7 页浅色 + 3 页深色 + 1 张窄屏 900px）存档 `q22-screenshots/` | §3 |

---

## 1. 参考项目规范提取（ConsolePage.tsx / index.css）

从参考项目源码提取并映射到网关令牌体系：

| 参考规范（ConsolePage.tsx） | 网关落地（base.css vQ22） |
|---|---|
| 主色黑：active 导航 `bg-black text-white`、主按钮 `bg-black` hover `#171717`、开关 on `#171b22` | `--brand:#171b22`（深色主题反转为白 `#e8eaee` + `--on-brand` 文本令牌） |
| 卡片无边框软阴影：`rounded-[13px] bg-white shadow-[0_10px_24px_rgba(15,23,42,0.035)]` | `.card` 无边框（`--card-border:transparent`）+ `--shadow-card` 同式阴影；深色主题补边框 |
| 软边框色板：`#eef1f3`（分隔）/ `#f6f7f8`（hover 底） | `--border:#eef1f3`、`--side-hover:#f6f7f8` |
| 文本层级：`#171b22` / `#59616a` / `#8f98a1` / `#a3abb3` | `--text` / `--text-muted` / `--text-faint` 四级对齐 |
| 分组侧栏：组标题 12px bold 灰 + 项 h-36 rounded-10 + active 绿点 `#16d76d` | `.nav-group-title` + `.nav-item.active::after`（绿点） |
| 两行顶栏：面包屑 12px（Console › 分组）+ 页标题 15px extrabold | `.crumb` + `.tb-title`（60px 顶栏，路由注入） |
| 分段式 tab：容器 `bg-#f3f4f6` rounded-11 + 活动段白底浮起 | `.tabs`/`.tab` 重塑为 SegmentedTabs 形态（纯 CSS，组件零改动） |
| 输入框：`bg-#fafcfc` + focus 边框转 `#20242a` | 表单底 `--surface-muted:#fafcfc`、focus `border-color:var(--text)` |
| 徽章色板：绿 `#effbf6/#20a877`、蓝 `#edf6ff/#3285e8`、橙 `#fff4e7/#c26a00` | b-ok/b-cool/b-warn 同款；红用 `#fef2f2/#d95757` |

## 2. 实施与验证

### 2.1 改动清单（5 个文件 + 新脚本）

| 文件 | 改动 |
|---|---|
| `model_gateway/web/static/css/base.css` | 整体重写：黑主色令牌（浅黑/深白反转 + `--on-brand`）、无边框软阴影卡片、分组导航、两行顶栏、分段 tab、参考色板徽章/表单/开关/表格；**pages/*.js 引用的类名全部保留** |
| `model_gateway/web/static/index.html` | 侧栏四分组（概览/资源配置/运行观测/系统设置）；顶栏左面包屑 `#crumb-group` + `#tb-title`；品牌区加副标题 LLM Gateway Console |
| `model_gateway/web/static/js/main.js` | 新增 `PAGE_META`（7 页 title/group）；`route()` 注入面包屑分组 + 顶栏页标题 + `document.title` |
| `pages/dashboard.js` / `pages/stats.js` | page-head 去重标题（移入顶栏）；`metricCard/metric` 加图标块（`metric-ico` 38px 圆角块 + 4 色调 mi-blue/green/orange/purple，lucide 线性 SVG 内联） |
| `pages/resources/models/apiaccess/settings/logs.js` | page-head 去重标题，操作行保留 |
| `scripts/ui_screenshot.py`（新增） | headless Chrome CDP 截图工具：localStorage 注入主题 → about:blank 中转强制重载 → 七页双主题截图 |

### 2.2 JS 语法检查

```
$ cd model_gateway/web/static/js && for f in main.js pages/*.js components.js api.js; do node --check "$f"; done
（全部无输出 = 通过）
```

### 2.3 线上资源核验（网关运行中，静态禁缓存延续）

```
$ curl -s http://127.0.0.1:8300/ | grep -o 'nav-group-title\|crumb-group\|tb-title\|brand-sub' | sort -u
brand-sub / crumb-group / nav-group-title / tb-title

$ curl -s http://127.0.0.1:8300/css/base.css | grep -o 'shadow-card\|--brand: #171b22\|nav-group-title\|metric-ico' | sort -u
--brand: #171b22 / metric-ico / nav-group-title / shadow-card

$ curl -sI http://127.0.0.1:8300/css/base.css | grep -i cache
Cache-Control: no-cache
```

### 2.4 全量回归

```
$ .venv/bin/python -m pytest -q
187 passed, 208 warnings in 39.83s
```

与 Q21 基线持平（Q22 纯前端改动，无后端接口/配置变更）。

## 3. 截图取证（`docs/changes/e2e-records/q22-screenshots/`，1440×940 @2x）

| 文件 | 核验点 |
|---|---|
| mg-q22-dashboard-light-wide.png | 分组侧栏 + 黑色 active 项带绿点；两行顶栏（Console › 概览 / 总览）；4 指标卡图标块（绿/蓝/橙/紫）；无边框软阴影卡片 |
| mg-q22-resources-light-wide.png | 面包屑 Console › 资源配置；表格 + 黑色开关 on + 黑主按钮「+ 新增资源」 |
| mg-q22-models-light-wide.png | 系统模型页 3:7 分栏 + 锚点列表 |
| mg-q22-stats-light-wide.png | 分段式 tab（今日/近7天/近30天 + 维度 tab）；7 指标卡图标；Chart.js 曲线色自动适配新令牌 |
| mg-q22-logs-light-wide.png | 请求/切换双 tab + 3:7 筛选表格 |
| mg-q22-apiaccess-light-wide.png | 地址行 + 端点列表 + code-block |
| mg-q22-settings-light-wide.png | 上下等高 02/03 区 + 重启/停止按钮 |
| mg-q22-dashboard-dark-wide.png | 深色主题：黑主色反转白（active 导航白底黑字 + 绿点；主按钮白底黑字） |
| mg-q22-resources-dark-wide.png | 深色表格 + 徽章半透明底 |
| mg-q22-stats-dark-wide.png | 深色分段 tab + 图表 CSS 变量适配 |
| mg-q22-dashboard-light.png | 900px 窄屏：内容区响应式压缩 |

截图执行输出：

```
$ python3 scripts/ui_screenshot.py
saved /tmp/mg-q22/mg-q22-dashboard-light-wide.png
…（共 11 张）
DONE
```

## 4. 遗留

- 无 SHELL 项；三态主题（Q21）与静态禁缓存（Q19）机制原样延续，未回归。
