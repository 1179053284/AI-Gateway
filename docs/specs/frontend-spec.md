# 前端开发规范（frontend-spec）

> **版本 v2.10 · 2026-09-06**（v1.0 从参考项目「模型供应商 / 技能」两页逐行提炼成文；v1.1 新增 §5.7 图标体系 Lucide 0.555.0 并全站替换落地；v1.2 指标卡数值混排等视觉——CJK 段 `.cv` .8em；v1.3 字体内置 Inter + 指标数值 19px/700/`.cv` .86em 舒适度调整；v1.4 模型资源页改版「模型供应商」模板版式；v1.5 六点修正；v1.6 厂商列表 group-card 化 + 接入配置只读常显；v1.7 禁框包框 + 连通性检测；v1.8 接入信息并入 Key 卡 + 厂商纤行 + grid 三列模型列表 + 自定义下拉；v2.0 全站规范提炼定版（§2.4 骨架选型表 / §3 双面板两变体 / §7.8–7.14 组件档）；v2.1 剩余四页系统性改造定版；**v2.2 API 接入页用户四点定版**：复制按钮一律改框内复制 icon（地址值块内嵌 / 密钥值尾随）、调用地址与端点说明改 `.split-50` 等宽并列且移至接入密钥下方、`.card-head .value` 补规则修正卡头主次层级（13px/600 muted，原无规则继承正文 14px 深色比标题还重）、使用示例（curl）移除（`.code-block` 类保留预留）；**v2.3 密钥密文化**：API 接入密钥值默认密文显示（`maskVal` 前 5 + `****` + 后 4，同资源页 Key 规格），行内「眼睛查看明文 ⇄ 收回」icon 前置于复制 icon（重渲染回到密文安全态）；**v2.4 端点两列 + 双板块等高**：端点说明改 2×2 两列网格（`.endpoint-list` grid 1fr 1fr gap 16，去行分割线——网格中 border-top 错位，参数卡教训；≤768 单列），`.split-50` 去 `align-items:start` → stretch 等高两板块；**v2.5 弹窗脚钮间距修复**（实现回归 §7.11：`modal()` 曾把 footer 整个 div 塞进 `.modal-foot`，flex gap 落在中间层上致按钮贴死；改为 footer 子节点平铺，取消↔确定恒 8px，三类弹窗一并修复）；**v2.6 导出功能全站移除**（用户指示「系统内所有导出数据功能都去掉」：数据看板 CSV 导出、系统设置配置导出（全量/脱敏）整体删除；前端本就是纯本地生成，无后端端点受影响）；**v2.7 数字输入去 spinner + 正整数过滤**（用户指示：`input[type=number]` 全局隐藏原生上下箭头（`appearance:textfield`），键入/粘贴即时滤除非数字字符（禁负号/小数点/科学计数法））；**v2.8 请求日志改竖排**（用户指示：筛选卡在上（字段 `.filter-grid` 横排一行）、日志表格卡全宽在下；废弃 3:7 分栏 + sticky-side + btn.block）；**v2.9 看板双 tab 并行一行**（用户指示：时段 tab + 维度 tab 并排同行，即模板「工具行」模式 flex-wrap gap 12）；**v2.10 成功率卡值/附属分层**（用户指示：长枚举明细拆 12px 小字 sub 行，值单行原则的定版例外）；定版三页零改动）
> （参考源码：`ConsolePage.tsx` 全 1365 行已通读，本文所有值均为源码精确提取，标注 `:行号`；网关自有组件（参考项目无对应物）以「网关实现」标注出处文件）。
> **地位**：网关管理界面（`model_gateway/web/`）唯一前端实现规范。新页面开发以本规范 + 两个模板为基准；
> 与 `design-spec.md`（视觉设计总纲）冲突时，以本文组件级精确值为准。
> **红线**：参考项目（`/Users/w/Desktop/react-v16-cursor/`）**全程只读**，禁止任何改动；只允许读取源码与访问 `http://localhost:5173` 页面。

---

## 0. 交付物索引

| 交付物 | 位置 | 说明 |
|---|---|---|
| 本规范 | `docs/specs/frontend-spec.md` | 逐像素组件规范，新页面唯一基准 |
| 模板 · 模型供应商 | `model_gateway/web/static/templates/template-providers.html` | 1:1 复刻参考页（含子侧栏/双面板/表单/列表/映射卡） |
| 模板 · 技能 | `model_gateway/web/static/templates/template-skills.html` | 1:1 复刻参考页（双分段 tab/搜索/列表卡/市场面板） |
| 样式实现 | `model_gateway/web/static/css/base.css` | 令牌 + 全部组件类（含 §9 模板组件层 + v2.0 网关组件层） |
| 七页实现 | `model_gateway/web/static/js/pages/*.js` | 已全量按本规范落地（2026-09-06 v2.0 对齐） |

访问：网关运行时 `http://127.0.0.1:8300/templates/template-*.html`（加 `?theme=dark` 预览暗色）。
**新页面开发流程**：复制更相近的模板 → 替换导航/数据/面板 → 类名与结构保持不变 → 按本规范逐项核对。

---

## 1. 设计令牌（Design Tokens）

全部组件**只允许使用令牌**（CSS 变量），禁止硬编码色值。实现：`base.css :root`（浅色）/ `[data-theme="dark"]`（深色）。

### 1.1 色彩

| 令牌 | 浅色值 | 用途（参考出处） | 深色值 |
|---|---|---|---|
| `--bg` | `#f7f8f9` | 应用底色（:428） | `#101114` |
| `--surface` | `#ffffff` | 卡片/侧栏/顶栏白底 | `#17191d` |
| `--surface-muted` | `#fafcfc` | 输入框底（:912,1360） | `#1d2025` |
| `--content` | `#fbfcfc` | 内容区底（:524）/分组卡底 | `#14161a` |
| `--border` | `#eef1f3` | 软边框/分隔线（:504,932…） | `#262a31` |
| `--border-strong` | `#e2e6ea` | 悬停描边增强 | `#363b44` |
| `--text` | `#171b22` | 主文本/主色（黑主色 :452） | `#ecedf0` |
| `--text-soft` | `#3b424a` | 次级文本（名称 :628,676） | `#c6ccd4` |
| `--text-muted` | `#59616a` | 按钮文字（:597,811） | `#9aa2ad` |
| `--text-tertiary` | `#8f98a1` | 描述/标签（:911,1244） | `#7f8792` |
| `--text-faint` | `#a3abb3` | 弱提示/图标（:806,920） | `#6c7280` |
| `--placeholder` | `#c1c7cd` | 占位符（:917,1360） | `#565d68` |
| `--brand` | `#171b22` | 黑主色（active/主按钮 :452,840） | `#e8eaee`（反转白） |
| `--brand-strong` | `#171717` | 主按钮 hover（:841） | `#ffffff` |
| `--brand-weak` | `#f3f4f6` | 中性徽章底 `b-brand`/`b-muted`（网关实现） | `rgba(232,234,238,.13)` |
| `--on-brand` | `#ffffff` | 主色上文字 | `#17191d` |
| `--card-border` | `transparent` | 卡片描边（浅色无边框软阴影，深色补边框） | `#262a31` |
| `--ok` / `--ok-bg` | `#20a877` / `#effbf6` | 成功绿徽章（:1280,1346） | `#3ddc97` / 绿 16% |
| `--err` / `--err-bg` | `#d95757` / `#fef2f2` | 危险红（:513,818） | `#f08a8a` / 红 16% |
| `--warn` / `--warn-bg` | `#c26a00` / `#fff4e7` | Hook 徽章（:1285） | `#f0a35c` / 橙 18% |
| `--cool` / `--cool-bg` | `#3285e8` / `#edf6ff` | MCP/Command 徽章（:1282） | `#6cb2f5` / 蓝 16% |
| `--g-coding`（紫） | `#7d4fc7`（底 `#f5f0ff`） | Agent/User 徽章（:1286） | `#b79af0` |
| `--seg-bg` | `#f3f4f6` | 分段 tab/灰底按钮底（:851,944,1189） | `#22252b` |
| `--switch-off` | `#d8dde2` | 开关关态（:959） | `#3a3f47` |
| `--dot-on` / `--dot-off` | `#16d76d` / `#c9ced3` | 状态圆点（:466,650） | 同 / `#4a5058` |
| `--side*` 系列 | 白底侧栏组 | 侧栏专用（见 §3.1） | `#17191d` 组 |
| `--mono` | `ui-monospace, "SF Mono", Menlo…` | Key/URL/代码（网关实现） | 同 |

### 1.2 圆角 / 阴影 / 字体

| 令牌 | 值 | 用途 |
|---|---|---|
| `--radius` 10px | 按钮/图标块/导航项（rounded-10） | |
| `--radius-card` 13px | 卡片/弹窗/列表卡（rounded-13 :801,857,1163） | |
| `--radius-full` 999px | 开关/药丸 tab/圆点 | |
| `--shadow-card` | `0 10px 24px rgba(15,23,42,.035)` | 卡片软阴影（:801 等） |
| `--shadow` | `0 5px 14px rgba(15,23,42,.06)` | 分段 tab active 段（:1195）/药丸 active |
| `--shadow-pop` | `0 18px 42px rgba(15,23,42,.14)` | 下拉/弹窗（:504） |
| `--shadow-brand` | `0 8px 16px rgba(0,0,0,.10)` | 主按钮/active 导航（:452,840） |
| `--ring` | `0 0 0 3px rgba(23,27,34,.07)` | focus 外圈 |
| 字体栈 | **`"Inter", -apple-system, "SF Pro Text", "PingFang SC", …`**（v1.3：Inter OFL 本地内置 `web/static/fonts/` 五字重 400-800 + `@font-face`，数字/西文用 Inter；CJK 依序回落 PingFang SC/雅黑。参考项目实际为纯系统栈，Inter 为 2026-09-05 用户「换舒服字体」要求） | |
| 等宽 `--mono` | `ui-monospace, "SF Mono", Menlo…` | Key/URL/代码 |

**禁止**：引入令牌之外的新圆角/阴影/色值；`border-radius` 只能取 6/8/9/10/11/12/13/full。
**唯一例外**：`.code-block`（curl 示例）为代码展示惯例**恒深底** `#161a26`（双主题不变，网关实现 apiaccess 页）。

### 1.3 字号字重体系（全量穷举，无其他值）

| 规格 | 值 | 用途（出处） |
|---|---|---|
| 特大 | 19px/700 `-.01em` | 指标卡数值（网关自有；v1.3 由 22px/800 调小调柔——用户反馈数字过大）；**混排等视觉：值内 CJK 段经 `fmtValue()`（api.js）包 `<span class="cv">` 缩至 .86em（16.34px）** 与数字视觉等高 |
| 大 | 18px/800 | 套餐价格（:864） |
| 标题 | 16px/800 | 套餐名（:860） |
| 页标题 | 15px/800 `-.01em` | 顶栏标题/可编辑供应商名（:484,769） |
| 正文强调 | 14px/800 | 市场名（:1312） |
| **基准** | **13px** 600/700/800 | 名称/按钮/输入/列表（全文） |
| 辅助 | 12px 500/600/700 | 面包屑/描述/徽章/tab（:443,956,852） |
| 微 | 11px 500/700 | 品牌副标/徽章字/Owner（:436,1288） |
| 标志 | 10px/900 | 20×20 mark 字母（:676） |

### 1.4 间距体系（只允许 4 的倍数，核心节奏 **12px**）

`4 · 8 · 12 · 16 · 20 · 24` —— 参考 `space-y-3 / mb-3 / mt-3 / p-3 / gap-3` 全部 = **12px**；
组间 `mb-5`=20px；微间距 `gap-1`/`mt-1`=4px、`gap-2`/`mt-2`=8px。**页面纵向块间距一律 12px**（mt-3 + space-y-3 叠加节奏，:848,906,973）。禁止 10/14/18px 等非体系值（三列属性网格列距 14px 为已定版例外，models 页 `attrRows`）。

---

## 2. 应用骨架（App Shell）

```
.app（grid 220px+1fr，h-100vh，bg --bg）
├─ .sidenav 220px 白底 border-r --side-border（:429）
└─ .main-col（grid 60px+1fr）
   ├─ .topbar 60px 白底 border-b（:477）
   └─ 内容区 bg --content
```

### 2.1 侧栏 `.sidenav`（:429-474）

| 元素 | 规格 |
|---|---|
| 品牌区 | 高 60px，px-3（12px），logo **35×35 rounded-10 黑底白字** `--brand`，投影 `0 8px 18px rgba(0,0,0,.12)`；名 14px/800 `-.01em`；副标 11px/500 |
| 滚动区 | px-3 py-4（12/16px） |
| 分组 | `mb-5`（20px）；组标题 `mb-2`（8px）px-2 12px/700 `--text-faint` |
| 导航项 `.nav-item` | **h-9（36px）** rounded-10 **px-2.5（10px）gap-2.5** 13px/600，图标 16px `stroke-width 2.1` |
| active 态 | bg `--brand` 字 `--on-brand` + `--shadow-brand`；**尾部 6×6 圆点 `--dot-on`**（:452,466） |
| hover 态 | bg `--side-hover` 字 `--side-strong` |
| 底区 | border-t + p-3；状态点 8×8 + 文字 12px |

### 2.2 顶栏 `.topbar`（:477-522）

- 高 **60px**，px-3，白底，border-b `--side-border`；两行结构：
  - 面包屑 `.crumb`：12px/600 `--text-faint`，`mb-1`（4px），`Console › 分组名`（chevron 14px）；
  - 页标题 `.tb-title`：15px/800 `-.01em`，截断省略；由 `main.js PAGE_META` 路由统一注入（页内**不再重复页标题**）。
- 右侧（网关实现 index.html）：调用地址 `.tb-addr`（mono 12px `--text-muted`，≤768 隐藏）+ **主题三图标直切组** `.theme-group`（sun/moon/monitor，icon-btn 32×32，图标 14px sw2，active 黑主色底反白，v0.9 定版；原 Q21 下拉弹出式废弃）。
- 下拉 `.dropdown`（:504-519）：`top 44px` w-180 rounded-13 border p-1（4px）`--shadow-pop`；项 h-9 rounded-10 px-3 12px/600；danger 项红字红底悬停。

### 2.3 内容区

- 底色 `--content`（#fbfcfc），滚动区 **p-3（12px）**（padding-bottom 48px），4px 细滚动条（thumb #d1d5db）。
- **页面限宽规则**：表单型多栏页用 `max-width 980px; margin 0 auto`（供应商模板 :537）；列表型/数据型页面全宽。
- **双面板页接管留白（网关实现 resources/models）**：页面根 `margin:-12px -12px -48px; height:calc(100vh - 60px)` 抵消内容区留白并接管滚动——左子侧栏固定、右侧主区 `overflow-y:auto; padding:12px` 内部滚动（根除长配置页底部空白；断点：≤1280 底部 -40px，≤768 `margin:-12px -10px -36px`）。

### 2.4 四类页面骨架选型表（v2.0 提炼定版）

| 骨架 | 结构 | 网关页面 | 模板基准 |
|---|---|---|---|
| **A · 子侧栏双面板页**（§3） | 左 subnav 248px 列表 + 右撑满配置区（内部滚动） | 模型资源 / 资源池设置 | template-providers |
| **B · tab+列表页**（§4） | 工具行（分段 tab）+ 搜索 + list-card 全宽 | ——（预留：技能类扩展页） | template-skills |
| **C · 数据观测页**（§5） | card-grid 指标行 + 全宽图表卡 + 全宽表格卡（可选 page-head 操作行 + 双 tab） | 总览 / 数据看板 | ——（网关自有） |
| **D · 工具页**（§6） | 卡片堆叠 + split-37（API 接入为操作即保存 D3；系统设置为脏态二段保存 + page-head 操作行） | API 接入 / 系统设置 | ——（网关自有） |

---

## 3. 页面骨架 A：子侧栏双面板页（模板 + 两个网关实现变体）

```
内容区（flex；双面板页接管留白见 §2.3）

> 注：两个定版页（模型资源 / 资源池设置）为内联样式等价实现——本节记录的结构与数值即其现状；
> §7.13 的 `.sec-head` 等类为同规格类化形态，供新页面直接使用，不要求回改定版页。
├─ .subnav 248px（列表 :590-605）
│   ├─ .subnav-scroll（px-3 12px）
│   └─ .subnav-foot（border-t p-3，「添加」入口）
└─ 主区 flex:1 滚动 p-3
   ├─ 头卡（logo-block.dark 40 + 名称 + 副行 + 右操作）
   └─ mt-3 + space-y-3（12px 叠加节奏 :906）各配置卡
```

### 3.1 子侧栏 `.subnav`（ProviderList :590-671）

- 宽 **248px** 白底 border-r `--side-border`；滚动区 px-3 py-4；底区 border-t p-3。
- 分组标题：12px/700 `--text-faint` `mb-2`（无左右 padding；双面板网关变体中 `padding:0` 覆写）。
- **分组卡片 `.group-card`**（:625-652）：rounded-12 bg `--content` **p-2（8px）** + `inset 0 0 0 1px --border`；头部行 h-28 px-4 `mb-1.5`（6px）= `.mark-sm` 20×20 + 名称 13px/800；行按钮 `.mode-btn`：
  - `.mode-btn`：**h-8（32px）rounded-9 px-2.5 13px/700**，flex 布局 `label flex-1 截断 + .dot 8×8 尾部（margin-left:auto）`；
  - active：**白底 + `inset 0 0 0 1px --text`**；hover 白底（:631-635）。
- **纤行 `.anchor-item`**（:656-659）：**h-38 rounded-10 px-2.5** 13px/700，`display:flex; align-items:center`（**必须显式居中**——参考提炼遗漏致点/文字错位的教训，见 pitfalls）+ mark + 名称截断 + `.dot`；active `bg --content + inset 1px --border`；hover `--side-hover`；行距 4px。
- `.mark-sm` 图标块（:673-695）：**20×20 rounded-6**，字母 10px/900 或 14-16px 线性 SVG；默认灰字，`.dark` 变体 = 黑底白字。
- 底部 `.side-add`：h-9 rounded-10 px-2.5 13px/700 ghost + plus 图标 16px。

### 3.2 模板基准组件（template-providers 复刻页专用）

- **头卡**（ApiProviderHeader :801-827）：`flex justify-between` 卡片；左：`.logo-block` **40×40 rounded-10**（`.dark` = 品牌黑底白字 20px/900，投影 `0 10px 22px rgba(0,0,0,.12)`；默认灰底 `--surface-muted` 图标 20px）+ 名称行（可编辑名 `.edit-name` **15px/800 `-.02em` hover 纯黑** + 铅笔 `.icon-btn.sm`）+ 副行 12px/600 `--text-faint`；右：`.btn`（禁用/启用）+ 删除 `.icon-btn.lg.danger`（**仅自定义项显示** :816）。
- **表单卡与字段**（SettingsCard / Field :907-928, 1353-1363）：卡 = `.card`（rounded-13 **p-3** `--shadow-card`，无边框）；Field 规格 = **label 13px/700 `--text-tertiary` `mb-2`（8px）**；输入 **h-11（44px）rounded-11 border `--border` bg `--surface-muted` px-3.5（14px）** 13px/600 `--text-soft`；**focus：边框转 `--text`（#20242a 黑）+ 底转白**；字段间距 `mb-3`（12px）。类实现 = `.form-row`（flex column gap 8）+ `.form-grid2`（两列 gap 0 12）。
- **带尾钮输入组 `.input-group`**（API Key :912-926）：同 Field 外框，内嵌透明 input + 图标 14px `--text-faint`；`focus-within` 边框转黑底转白。
- **列表卡与行**（:932-949, 1000-1036）：容器 `.list-card`：rounded-12~13 白底 border `--card-border` **overflow-hidden**；行 `.list-row`：**h-46px px-4（16px）gap-3**，行间 border-b `--border`（`.list-row + .list-row`，末行无）；编辑态行 bg `--content`（`.editing`）；追加按钮 `.btn-soft`：`mt-2`（8px），**h-9 rounded-10 bg `--seg-bg` 无描边** px-3.5 13px/700。
- **开关控制卡**（Claude 映射 :953-995）：头行 `mb-3`：标题 13px/800 + 描述 12px + `.switch`（右置）；展开区 `space-y-3`。
- **套餐面板**（PackageConnectionPanel :829-876）：头卡 + **药丸 tab `.pill-tabs/.pill-tab`**（:851-854：容器 rounded-full bg `--seg-bg` p-1 gap-1；段 px-3 py-1 高约 26px 12px/700；active 白底 + `--shadow`）+ 套餐卡（名 16px/800、描述 `mt-2` 13px/500 行高 20px `--text-tertiary` max-w-560、价格 `mt-3` 18px/800、订阅黑按钮）。

### 3.3 网关变体 ①：模型资源页（`pages/resources.js`，v1.4–v1.8 定版落档）

- **子侧栏 = 资源供应商纤行**：`.anchor-item`（mark-sm 内 16px server SVG + 名称截断 + `.dot` 任一 Key 启用 = 亮），无分组标题；`subnav-foot` 放 `.side-add`「添加模型资源」；**未保存草稿不出现在子侧栏**（v2.0 修正②）。
- **头卡（厂商基本信息 + 接入形式 + Base URL 合并一卡，v1.9 定论）**：`.logo-block.dark` 首字 + `.edit-name`（15px/800）+ 铅笔 20×20 `.icon-btn.sm` + 副行「Key 及关联账号 · N 组 Key · M 个模型映射」12px/600 faint；右 `.btn`（禁用/启用）+ `.icon-btn.lg.danger`（删除）。第二行：已设置 → 无标签 `addr-value` 值块（接入形式 + Base URL + 复制 icon 20×20，**界面不可改**）；未设置 → `.in` 下拉（接入形式）+ `.in.mono` 输入（Base URL），保存后即隐藏。
- **「Key 及关联账号」独立卡**：区头 `.sec-head`；行 = `.list-row`（padding 12px 0，行间 border-top）内 grid `1.2fr 1fr`：Key 值（`.in.mono` font-weight **400**，右侧绝对定位复制 + 眼睛 28×28）+ 所属账号（`.in` 选填）+ `.switch` + 删除 `.icon-btn.sm.danger`；Key 脱敏显示，眼睛 → `GET config?reveal=1` 明文/收回；**新 Key 草稿行槽位唯一**（已有空行只聚焦不新增），填写失焦即落库（`@new-*` 占位 → 服务端生成真实 id）。
- **「模型列表」卡**：区头 `.sec-head`；**grid 三列 `340px max-content 1fr`**（v1.8；⚠ 表头三格必须是 grid 直接子元素，包 div 会整体占首列挤错位）；列 1 = `.in.mono` 无边框透明输入（padding-right 30px 容复制 icon）+ 复制按钮；列 2 = **自定义下拉**（`.in` 按钮 + `.dropdown` 菜单，箭头恒距文字 10px，根治原生 select 箭头钉框右缘）；列 3 = 操作右对齐（检测 `.icon-btn.sm` + 删除 `.icon-btn.sm.danger`）；行高 46px，行间 border-top。
- **连通性检测三态**（v1.7，FR-9.1）：行内 CPU 图标按钮 → `POST /admin/api/resources/test` 逐启用 Key 检测 → 全过 `var(--ok)` / 部分过 `var(--warn)` / 全挂 `var(--err)`，title 记 `n/total · 最快 Xms`，状态保持至下次检测；草稿态凭 `base_url+api_key` 直连检测。
- **操作即保存（D3）**：变更确认后直接 PUT，失败提示并**以服务端最新配置重渲染**（`persist()` 自同步）；删除类走确认弹窗（级联影响列明）。

### 3.4 网关变体 ②：资源池设置页（`pages/models.js`，Q24 定版落档）

- **子侧栏 = 厂商归属分组卡**（内置目录 `GET /admin/api/enums` 的 vendor 字段，与接入商解耦）：`.group-card` 头行（`.mark-sm` 首字，全启用时 `.dark` + 厂商名 13px/800 `--text-soft`）+ 行 `.mode-btn`（系统模型 ID 截断 + `.dot` 纯状态指示，禁用行文字半透明）；卡底 `.btn.btn-sm` 全宽「＋ 添加模型」；无目录条目归「自定义」卡。
- **头卡**：`.logo-block.dark` 首字 + 名称 15px/800 `-.02em`（禁用半透明）+ 端点/启停徽章行 + 副行 12px/600 faint「端点文案 · 分组 · N 个资源（顺序 = 优先级）」；右 `.btn`（启停）+ 删除（`SHOW_DELETE=false` 暂隐藏）。
- **模型属性卡**（目录只读）：`.sec-head`（右描述「来源：内置模型目录（官网取证）· 只读」）+ **三列网格 `repeat(3,1fr)` gap 14px 12px**（`.form-row` 无底 margin：label 13/700 tertiary + 值/`.mono`/`yn()` ✓—徽章）。
- **资源池卡**：`.sec-head`（右描述「顺序 = 优先级：生效集 top-x 承接、失败切换按序补位」）+ `.list-row` 行（h-46 序号 20px 右对齐 faint + 资源名 mono/700 + 厂商徽章 `b-brand` + `/厂商模型` mono/700 + effort 下拉 `.in.mono` 150px（仅 chat）+ ↑↓ `.btn.btn-sm` + 移除 `.icon-btn.sm.danger`）。
- **参数配置卡**（三级优先级：工具传参 > 网关设置 > 厂商内置；仅 chat 注入）：`.sec-head`（右侧 = 优先级文案 + `.btn.btn-sm`「恢复官方配置」）+ **两列网格 `repeat(2,minmax(0,1fr))` gap 12px 28px**（⚠ 单元格须覆写 `#id .list-row + .list-row { border-top:0 }` 防网格错位继承分割线，行距对齐 12px 节奏——design-spec v2.8）；单元格行 = 参数名 170px 13/600 soft 截断 + `.in.mono` 弹性输入（空 = 不注入走厂商内置）+ `icon-btn.sm` ×（官方参数 = 清空网关值行保留 / 自定义 = 删行）；底部添加参数行（新键空值不落配置，填值 change 后保存）。
- **操作即保存（D3）**：同变体 ①。

---

## 4. 页面骨架 B：技能页（tab + 搜索 + 列表卡）

```
.content p-3 全宽（:1123-1176）
├─ 工具行 mb-3 flex-wrap gap-3：分段 tab×2（市场阶段隐藏第二组 :1135）
├─ 搜索行 flex gap-2：.input-group（搜索图标 14px）+ 可选黑主按钮 h-11
└─ mt-3 .list-card（行列表 / 空态）
```

### 4.1 分段 tab `.tabs/.tab`（SegmentedTabs :1189-1203）

容器：**inline-flex gap-1（4px）rounded-11 bg `--seg-bg` p-1（4px）**；段：**h-8（32px）rounded-9 px-3 12px/700**；active：**白底 + `--shadow` + 字 `--text`**；非 active 字 `--text-tertiary` hover `--text-muted`。多组 tab 并排 gap-3；条件性显示/隐藏整组。

### 4.2 列表行 `.list-row`（SkillListItem :1235-1273）

- 行 `flex items-center gap-3 p-3`，行间分隔线；左侧 `flex-1 min-w-0`：
  - 名称行 `flex-wrap gap-2`：名 **13px/800 `-.01em`** 截断 + 版本 12px/700 `--text-faint` + 徽章组；
  - 描述 `mt-1` 13px/500 行高 20px `--text-tertiary` **两行截断**（`.clamp-2`）；
  - 来源 `mt-1` 12px/600 `--text-faint`「来自 xxx」。
- 右侧操作（`shrink-0 gap-2`）：已安装 → `.switch` + `.icon-btn.danger`（32×32）；发现 → `.btn`「安装」（带 14px download 图标）。
- 空态 `.list-empty`：p-3 13px/600 `--text-tertiary`（:1165）。

### 4.3 徽章色板 `.badge`（SkillBadge :1276-1289，语义全表见 §7.10）

**rounded-md（6px）px-2 py-0.5（8/2px）11px/700 淡底彩字**；圆药丸变体 `.b-pill`（h-6 rounded-full px-2.5）。

### 4.4 市场面板（MarketPanel :1291-1332）

搜索 + `.btn-primary.btn-lg`「添加市场」；提示行 `mt-2` 12px/600 `--text-faint`；列表卡 `mt-3`：名 14px/800 → 来源 `mt-1` 12px/600 → 描述两行截断 → 元徽章组 `mt-2 gap-2`（`b-gray`）+ 删除 `.icon-btn.danger`。

---

## 5. 页面骨架 C：数据观测页（总览 / 数据看板，网关自有）

```
.content p-3 全宽
├─（可选）.page-head：右置次要操作（如「导出当前表格 CSV」）
├─（可选）工具行：双 .tabs 并排一行（时段 tab + 维度 tab，flex-wrap gap 12；v2.9 与模板「技能页」工具行同款）
├─ .card-grid（minmax(300px,1fr) auto-fill gap-12px）指标卡行（margin-bottom 12px）
├─ .card-grid > .card[grid-column:1/-1] 全宽图表卡（margin-bottom 12px）
└─ .card-grid > .card[grid-column:1/-1] 全宽表格卡
```

- **总览（dashboard.js）**：8 张指标卡（运行状态/运行时长/今日调用/今日 token/资源健康/厂商/资源/模型）→ 24h 纯 CSS 柱状趋势卡（高 160px，成功/失败/中断三色堆叠 `--ok/--err/--warn`，零依赖降级形态即正式形态）→ 资源健康表格卡（.tbl + 状态徽章列）。无 page-head、无事件常驻块。
- **数据看板（stats.js）**：**工具行 = 时段 tab（今日/近7天/近30天）+ 维度 tab（后端维度键数据驱动，前端不写死）并行一行（v2.9）** → 指标卡行 → Chart.js 日趋势卡（高 220px，成功/失败/中断三折线）→ 维度明细表格卡（列头可排序）。**导出功能已按 2026-09-06 用户指示全站移除（v2.6）**。
- 指标卡 / 表格 / 图表组件规格见 §7.8–§7.10。

---

## 6. 页面骨架 D：工具页（API 接入 / 系统设置，网关自有）

```
.content p-3 全宽
├─（可选）.page-head 操作行（仅系统设置：脏态 badge + 保存钮）+（可选）.page-desc 页导语
└─ 卡片堆叠（间距 12px，自然高度）：
   ├─ 常规 .card（配置表单 01·02；卡内二级分组头 .sec-head.sub）
   ├─ .card.flush 表格卡（.card-head.inset + .tbl 直贴）——密钥清单（卡头右侧挂卡级操作）
   └─ .split-50（1fr/1fr gap-12）等宽双板块（API 接入：调用地址 | 端点说明，v2.2 定版
        置于密钥卡下方）/.split-37（3fr/7fr）：请求日志 = 筛选卡 : 日志表格卡
```

- **API 接入 = 操作即保存（D3，v2.1 对齐资源页）**：无「保存配置」二段提交——添加密钥（弹窗确认即 PUT，服务端生成 `tok-` id 与 `mg-` 密钥值）、删除（确认弹窗列明 401 影响）、启停（行内 `.switch` 即时落库）、用途标注（行内无边框输入失焦即存）；全部变更后以服务端最新配置重渲染（`persist()` 自同步）。**页面结构（v2.2 用户定版）**：page-desc → 接入密钥 `.card.flush` 表格卡（`.card-head.inset`：标题 + `N/M 启用` 统计 + 右侧「＋ 添加密钥」`.btn.btn-sm`；行 = 用途标注行内编辑 ｜ 密钥值**默认密文**（`maskVal` 前 5 + `****` + 后 4）+ **眼睛查看明文**（v2.3：`.icon-btn.sm` 眼睛 ⇄ eye-off 就地切换，前置于复制 icon）+ 值尾复制 icon ｜ 状态开关 ｜ 操作列删除 `.icon-btn.sm.danger`）→ `.split-50` 两板块并列 = 调用地址（`.addr-group` 成组，地址 `addr-value` 框内 URL 后内嵌 20×20 复制 icon，对齐资源页 Base URL 模式）| 端点说明。**复制交互一律 icon 化**（无「复制」文字按钮）。停用行整行弱化 `.off`。
- **系统设置 = 全站唯一脏态二段保存页**（参数批量编辑：12 个数字输入逐项 change 攒脏，`badge b-warn`「有未保存修改」+ 主保存钮 disabled 联动；保存 `PUT config` → 校验失败 400 错误列表 toast、成功热重载生效）。布局 = 纵向三卡自然高度堆叠（01 任务执行全宽 / 02 系统日志全宽 / 维护全宽；v2.1 起**废弃 50/50 等高**——01 卡内容多被迫内部滚动、02 卡大量空白）。
- **维护区**（settings）：`.card-head`「维护」+ `.maint-grid`（flex wrap gap 24）分组块 = `.maint-title`（13px/600 muted mb-8；`.danger` 红 700）+ `.maint-ops`（flex gap 8 wrap：按钮组 + 尾随 `.form-hint` 说明）。危险操作（重启/停止）`.btn.btn-sm.btn-danger` + 确认弹窗；停止成功 → `.center-card` 停止提示态。
- **请求日志页**（logs.js，骨架 D 混合；**v2.8 竖排定版**）：双 tab 行 → 筛选卡在上（`.filter-grid` 筛选字段横排一行：字段 `flex:1 1 200px` 均分 + 重置按钮右端，窄屏自动换行；切换事件 tab 仅日期 + 提示文案）→ 日志表格卡全宽在下（**card-head = 动态标题「请求流水/切换事件」+ 右置 `.value`「共 N 条」**）+ `.tbl` 可排序 + 展开行（`.exp` chevron + `.req-detail`）+ `.pager` 分页。（v2.1 的 3:7 左右分栏 + `.sticky-side` 粘滞 + `.btn.block` 全宽钮随本版废弃，类已删）
- **数据页卡级操作原则（v2.1 提炼）**：操作按钮归属其作用对象所在卡（如 CSV 导出在维度明细卡头、添加密钥在密钥卡头），不设游离于内容外的页级操作行。

---

## 7. 通用组件规范（全站共用）

### 7.1 按钮（全量变体）

| 类 | 规格（精确值） | 出处 |
|---|---|---|
| `.btn`（次级） | **h-9（36px）rounded-10 px-4（16px）** 13px/700，border `--border` 白底，字 `--text-muted`；hover bg `--side-hover` 字 `--text` | :811,1266 |
| `.btn-primary`（主） | 同尺寸**黑底白字** + `--shadow-brand`，hover `--brand-strong` | :840,867,1156 |
| `.btn-soft`（添加） | h-9 rounded-10 **bg `--seg-bg` 无描边** px-3.5，hover 加深 | :944 |
| `.btn-lg`（大主钮） | **h-11（44px）**，其余同 primary | :1156,1299 |
| `.btn-sm`（小钮，网关实现） | **h-30px rounded-8 px-10px 12.5px/700**（资源池行内 ↑↓/卡底添加/密钥操作） | resources/models |

| `.btn-danger`（危险） | border `--err-bg` 字 `--err` 白底；hover bg `--err-bg` border `--err` | :818 系 |
| `.btn-ghost` | 无边框灰字，hover 灰底黑字 | — |
| disabled | `opacity .45` + not-allowed + 无阴影位移 | — |
| 按钮内图标 | **SVG 14×14 sw2**（`.btn svg` 统一），与文字 gap 6px | :600,947,1269 |

图标按钮 `.icon-btn`：**32×32 rounded-10**（sm 28×28 rounded-8 行内，lg 36×36 卡片头）；图标 14px（lg 16px）`--text-faint`；hover 灰底；**danger hover `--err-bg`/`--err`**（:818,1028）。20×20 微缩变体用于名称旁铅笔（resources 头卡）。

### 7.2 开关 `.switch`（:958-968, 1250-1254）

**40×24 圆角 full**；knob **20×20 白圆** `top 2px`，投影 `0 3px 8px rgba(15,23,42,.18)`；on `--brand`（位移 16px）/ off `--switch-off`；过渡 .18s。行内与表头右置两用。

### 7.3 状态圆点 `.dot`

**8×8**；on `--dot-on`（#16d76d）/ off `--dot-off`；用于列表行尾、模式按钮尾、子侧栏纤行尾（数据态指示——**圆点只读，操作用开关/按钮**，交互范式⑥）。

### 7.4 toast（sonner 顶部居中，网关实现 `#toast-wrap`）

`position fixed top 16px` 水平居中；卡片式：白底 border rounded-12 `--shadow-pop` px-16 py-11 13px/600；**宽度 max-content**（max `min(560px, 100vw-32px)`）；前缀色点（ok 绿/err 红/中性灰）；2.4s 自动消失（err 6s）；入场上移 8px 渐显。

### 7.5 滚动条

`width 4px`，thumb `#d1d5db` rounded-2，hover `#b8bec6`；track 透明；深色 thumb `#343943`。

### 7.6 可编辑名称（行内编辑范式）

静态：extrabold 文本按钮 hover 纯黑（供应商 15px / 模型 13px 两档）；点击 → 原位替换 input（供应商：h-8 rounded-10 **border `--text`** px-2.5 15px/800 白底；模型：h-8 透明底 13px/700）；Enter/失焦保存、Escape 还原；所在行 bg `--content`。

### 7.7 图标体系（Lucide）

**唯一图标库：[Lucide](https://lucide.dev) `0.555.0`**（ISC 开源，与参考项目 `package.json` 一致；
参考全站 `lucide-react`，网关 vanilla 项目直接内联其官方 path）。**禁止**再手绘/复制旧
Feather path（Lucide 是 Feather 的分支，0.5xx 已大量改版：eye/moon/key/settings/wrench/
cpu/database/layers 均已换 path）。

**SVG 属性契约（所有图标统一）：**

```html
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
     stroke-width="2" stroke-linecap="round" stroke-linejoin="round">…</svg>
```

- 尺寸：`width="14" height="14"` 动作图标（按钮内/搜索/面包屑 chevron/密钥眼睛）· 16 导航
  （`.nav-ico` 由 CSS 定尺寸）与子侧栏 mark 内 · 20 logo 块（`.logo-block`）· 12 药丸 check。
- 描边：导航 **2.1**（参考 :463-464），其余一律 **2**（Lucide 默认）；无其他值。
- 颜色：只吃 `currentColor`，由父级文字色控制（如 check 药丸 `stroke="#16d76d"` 参考 :1347）。

**尺寸/描边用法对照（参考出处）：**

| 场景 | 图标 | 尺寸 | 描边 | 参考 |
|---|---|---|---|---|
| 侧栏导航 | server / cpu / wrench / user / shield / settings / file-text / refresh-cw | 16 | 2.1 | :463-464 |
| 面包屑 | chevron-right | 14 | 2 | :481 |
| logo 块 | server / cpu | 20 | 2 | :709,716 |
| 按钮内动作 | plus / eye / download / log-in / pencil | 14 | 2 | :600,924,947,1269 |
| 搜索框 | search | 14 | 2 | :1216 |
| 药丸徽章 | check | 12 | 2 | :1347 |

**网关页面图标选型（Lucide 官方名，v2.0 按七页实际用图全量核对）：**

| 页面/场景 | 图标（Lucide 名） |
|---|---|
| 导航 · 总览 | `layout-grid` |
| 导航 · 模型资源 | `database` |
| 导航 · 资源池设置 | `layers` |
| 导航 · 数据看板 | `chart-column` |
| 导航 · 请求日志 | `list` |
| 导航 · API 接入 | `key-round` |
| 导航 · 系统设置 | `sliders-vertical` |
| 主题切换 | `sun` / `moon` / `monitor`（sw 2） |
| 菜单/折叠 | `menu`；弹窗关闭/移除行/清空参数 `x`；停止态 `power` |
| 指标卡 | `activity` / `arrow-left-right` / `coins` / `shield-check` / `chart-column` / `circle-check` / `refresh-cw` / `timer` / `gauge` / `image` |
| 行内动作 | `eye` / `eye-off`（Key 明文）· `trash-2`（删除）· `pencil`（改名）· `copy`（复制）· `cpu`（连通检测）· `plus`（添加）· `server`（资源供应商 mark）· `chevron-down`（下拉/展开）· `chevron-up/down`（排序 ↑↓ 用文本字符，日志展开用 `chevron-right`/`chevron-down` 14px） |

**权威来源**：参考项目 `node_modules/lucide-react@0.555.0/dist/esm/icons/<name>.js`
（只读；`__iconNode` 即官方 path）。取新图标时按官方 attr 顺序（如
`<rect width="20" height="8" x="2" y="2" rx="2" ry="2"/>`）逐属性复制，不改动几何。

### 7.8 指标卡 `.metric-card`（v2.0 定档，参考规范组件层 + 网关实现）

结构：`.card.metric-card` = flex `align-items:center` gap 12px：

- 左：`.metric-ico` **38×38 rounded-10** 图标块，内嵌 Lucide SVG **19×19** sw2；四色调 `--*-bg` 底 + `--*` 字：`mi-blue`（cool）/ `mi-green`（ok）/ `mi-orange`（warn）/ `mi-purple`（g-coding，深色底 14% 半透明）。
- 右：`.metric-main`（min-width:0）：
  - `.metric-label` **12px/600 `--text-tertiary`**；
  - `.metric-value` **19px/700 line-height 26px `-.01em`** `font-variant-numeric: tabular-nums`；
  - **值单行原则**：多项重点信息用 `·` 并列一行（如 `成功 0 · 成功比 0%`、`输入 0 · 输出 0`），**不拆 12px 灰色 sub 行**（design-spec v1.0 定版）；**例外（v2.10 用户定版）**：长枚举附属信息（如看板成功率卡「成功 N · 失败 N · 中断 N」）拆为值下方 12px/600 `--text-tertiary` 小字行（复用 `.metric-label`，`fmtValue` 处理 CJK），仅此一卡适用；
  - **CJK 混排**：值内 CJK 段经 `fmtValue()`（api.js）包 `<span class="cv">`（`.86em`）与数字视觉等高；纯数字/西文不受影响。
- 网格容器：`.card-grid` = `repeat(auto-fill, minmax(300px,1fr))` gap 12px，横向响应式（随宽度 1–3 张/行）。

### 7.9 表格 `.tbl`（清单类信息首选，v2.0 定档；网关实现 base.css）

容器 `.table-wrap { overflow-x:auto }`（窄屏横向滚动）；`table.tbl`：`width:100%; border-collapse:collapse; font-size:13px`。

| 元素 | 规格 |
|---|---|
| 表头 `th` | **12px/700 `--text-faint`** `letter-spacing .02em` 无底色，padding **10px 16px**，border-b `--border`，nowrap |
| 单元格 `td` | padding **12px 16px**，border-b `--border`，vertical-align middle；末行无线 |
| 行 hover | `--surface-muted`（transition .12s） |
| 数字列 `.num` | `text-align:right` + `font-variant-numeric: tabular-nums`（th 同） |
| 等宽 `.mono` | `--mono` 12.5px |
| 可排序表头 `.sortable`（v2.0） | `cursor:pointer`；hover 字提亮 `--text-muted`；当前排序列尾随 `↑/↓` 字符 |
| 强调单元格 `.strong`（v2.0） | `font-weight:600`（主名称列） |
| 长值截断 `.ellip`（v2.0） | `overflow:hidden; text-overflow:ellipsis; white-space:nowrap` + 场景 `max-width` 内联（密钥值 340 / 错误摘要 260），配合 `title` 悬停全值 |
| 停用弱化 `.off`（v2.0） | `opacity:.5`（全站统一值；整行锁定另加 `pointer-events:none`） |
| 状态列 | 三态徽章 `b-ok`（成功）/`b-err`（失败）/`b-warn`（中断）/`b-muted`（停用），悬停 title 补充语义（如 cooldown 剩余秒数） |
| 展开行（请求流水） | 主行尾 `.exp` 指示格（36px 居中 `--text-faint`，`chevron-right` ↔ `chevron-down` 14px）；详情行 `.hidden` 切换 + `.req-detail`（12px `--text-muted`，flex column gap 4；错误行 `.errline` 红色；attempts 区 `.sep` 虚线上分隔） |

### 7.10 图表（Chart.js v4 vendored 本地，v2.0 令牌化定档）

- 容器：图表卡 `.card` 内 `.card-head`（`.card-title` 13px/800 soft + 右 `.value` 13px/600 `--text-muted` 说明）+ 固定高 div（总览 160px / 看板 220px）；**Chart.js 只接受 `<canvas>` 元素**（v4 传容器 div 静默不渲染，实施校正记录）。
- **颜色一律运行时读令牌**（`getComputedStyle(document.documentElement)`）：网格 `--border`、刻度/图例 `--text-faint`、**系列色 成功 `--ok` / 失败 `--err` / 中断 `--warn`**（禁止硬编码 `#16a34a` 等）；填充透明度用令牌色 + alpha（≤.08）。`responsive:true; maintainAspectRatio:false; interaction mode index`；图例 12px boxWidth 12。
- 纯 CSS 降级柱状（Chart.js 缺失时）：`--ok/--err/--warn` 堆叠 + 10px `--text-faint` 日期标签——即总览 24h 趋势的正式形态。

### 7.11 弹窗 `.modal`（v2.0 定档；网关实现 components.js）

- 遮罩 `.modal-mask`：`fixed inset 0 rgba(15,18,25,.45)` + `blur(3px)` z-50，flex 居中 padding 24。
- 卡 `.modal`：**宽 560px**（`.wide` 800px）max-height 86vh rounded-13 border `--border` `--shadow-pop`，入场上移 10px 缩放 .18s。
- 头 `.modal-head`：padding 14px 18px border-b；标题 h3 **15px/800**；关闭 `.modal-close` 28×28（x 16px）。
- 体 `.modal-body`：padding 16px 18px 滚动；脚 `.modal-foot`：padding 12px 18px border-t，右对齐 `取消 .btn` + `确定 .btn-primary`（危险 `.btn-danger`）；**实现注记（v2.5）**：`modal()` 须将 footer 子节点平铺进 `.modal-foot`（flex gap 8px 直接分隔按钮）——禁止把包装 div 整体 append（会让 gap 落在中间层、按钮贴死）。
- 表单弹窗字段 = `.form-row`（label 上置）；确认弹窗 `confirmDialog(title, text, danger)` 默认危险红确定。
- 遮罩点击关闭；Escape 由各弹窗自行处理（网关现状：遮罩/按钮关闭）。

### 7.12 分页 / 空态 / 加载 / 居中提示卡（v2.0 定档）

- 分页 `.pager`（components.js `pagination()`）：flex 右对齐 gap 8px `margin-top:12px` 13px/600 `--text-muted`；`‹ ›` 为 `.btn.btn-sm` disabled 联动；页码文案 `cur / pages（共 total 条）`；每页默认 100 条（仅 total > 100 渲染）。
- 空态 `.empty`：白卡 rounded-13 软阴影，p 28px 24px，13px/600 `--text-tertiary` 居中（列表卡内空态用 `.list-empty` p-3）。
- 加载 `.loading`：p-24 居中 13px `--text-faint`。
- 居中提示卡 `.center-card`（v2.0）：`max-width:560px; margin:80px auto; text-align:center; padding:40px`（网关停止提示态 / index.html 装载兜底；卡内标题 18px/800 + 正文 13px `--text-muted` 行高 1.8）。

### 7.13 区头与页头（v2.0 定档，网关实现）

| 类 | 规格 | 用途 |
|---|---|---|
| `.card-head` / `.card-title` | flex gap 8 mb-12；标题 **13px/800 `--text-soft` `-.005em`** | 卡片标题行（右侧可挂 `.value` 或操作） |
| `.card-head .value`（v2.2 补规则） | **13px/600 `--text-muted`** `tabular-nums`——卡头辅助说明的固定层级（弱于标题；此前无规则继承正文 14px 深色致主次颠倒） | 卡头统计/说明（密钥卡「N/M 启用」、看板卡说明、日志「共 N 条」） |
| `.sec-head`（v2.0） | flex `align-items:center` `justify-content:space-between` gap 12 **mb-12**；左 `.t` = 13px/800 `--text-soft`；右 `.d` = 12px/500 `--text-faint` 右对齐 | 卡内一级区头（Key 卡/模型列表卡/属性卡/资源池/参数卡） |
| `.filter-grid`（v2.8） | `flex wrap gap 12 align-items:flex-end`；字段 `.form-row` `flex:1 1 200px` 无底 margin、按钮 `flex:none` | 筛选字段横排（请求日志筛选卡） |
| `.sec-head.sub`（v2.0） | 仅左标题 **13px/700 `--text-muted`** | 卡内二级分组头（系统设置「网关」「调度」） |
| `.page-head` | flex gap 8 **min-height 36px mb-12**（页标题已上移顶栏，纯操作行） | 数据/工具页顶部 |
| `.page-actions` | `margin-left:auto` flex gap 8 | 操作右置 |
| `.page-desc` | 12px/500 `--text-faint` mb-12 行高 1.6 | 页导语（API 接入） |
| `.form-hint` | 12px/500 `--text-faint` 行高 1.6 | 卡内/表单尾提示 |

### 7.14 输入与展示块（v2.0 汇总定档）

| 类 | 规格 | 出处 |
|---|---|---|
| `.form-row` | flex column gap 8 mb-12；label 13px/700 tertiary；input/select/textarea **h-44 rounded-11 border `--border` bg `--surface-muted` px-14** 13px/600 soft；**focus 边框 `--text` + 底白 + `--ring`**；`.invalid` 红 | Field :912-928 |
| 数字输入（v2.7） | `input[type=number]` **隐藏原生 spinner**（全局 `appearance:textfield` + `::-webkit-*-spin-button` none）；**正整数过滤**：input 事件 `replace(/[^\d]/g,"")` 即时滤除负号/小数点/科学计数法（键入与粘贴均覆盖）；min 下限与业务校验走 change + 后端 400 | 系统设置参数表 |
| `.form-grid2` | 两列 grid gap `0 12px`（窄屏单列） | — |
| `.in`（行内输入） | **h-36 rounded-10 border bg `--surface-muted` px-12** 13px/600 soft；focus 同上；`.mono` 12.5px | 弹窗/映射行/参数行 |
| `.addr-label` / `.addr-value` | label 13px/600 muted；value = `--surface-muted` 底 rounded-11 border px 5px 14px mono 13px/600 soft | API 接入 |
| `.addr-group`（v2.0） | inline-flex gap 8；`.addr-row` 容器 gap **16px** flex-wrap | 地址成组（本机/局域网） |
| `.endpoint-list` / `.endpoint-item`（v2.4 两列） | list = `grid 1fr 1fr gap 16`（2×2，无行分割线；≤768 单列）；item = flex column gap 2：路径 mono/600 + 名称 muted + 说明 form-hint | 端点清单 |
| `.split-50`（v2.2，v2.4 等高） | `grid 1fr 1fr gap 12`（默认 stretch **两卡等高**；≤768 单列） | 等宽等高双板块并列（调用地址 | 端点说明） |
| `.code-block` | **恒深底 `#161a26` 字 `#c9d1e8`** border `#232a40` rounded-10 p 13px 16px mono 12px 行高 1.75（主题例外，§1.2）；**预留类**——curl 使用示例已按 2026-09-06 用户指示移除，暂无消费页面 | 预留 |
| `.input-group` | h-44 rounded-11 bg muted px-14，内嵌透明 input + 前置图标 14px faint；`focus-within` 边框黑底白 | 搜索/Key 行 |

---

## 8. 交互范式

1. **一切动作 toast 反馈**（成功/失败/稍后接入），文案「已 + 动词」或「xx 稍后接入」。
2. **开关即时生效**（无确认弹窗）；删除类走确认弹窗（`confirmDialog`，级联影响在正文列明）。
3. **行内编辑就地替换**，不改页面布局；Escape 可撤销。
4. **分段 tab 切换面板显隐**（`hidden` 类），支持条件联动（市场隐藏分类 tab）。
5. 搜索/过滤即时生效（input 事件），空结果显示空态文案而非空白。
6. **状态双呈现**：列表行尾圆点（数据态）+ 开关（可操作态）——圆点永远不承担点击启停。
7. **操作即保存（D3，网关定版）**：配置型页面变更确认后直接 `PUT /admin/api/config` + toast，失败提示后**无论成败以服务端最新配置重渲染**（`persist()` 自同步，杜绝界面与服务端漂移）——模型资源 / 资源池设置 / **API 接入（v2.1 起：启停 switch、用途标注行内编辑、添加删除即落库）** 均为此模式；仅「系统设置」因参数批量编辑保留**脏态二段保存**（§6）。
8. **草稿槽位唯一**：添加 Key / 映射行时已有空草稿行只聚焦不新增，杜绝空行堆积。
9. **敏感值脱敏**：Key 与接入密钥一律密文显示（`maskVal` 前 5 + `****` + 后 4），眼睛 icon 切换查看明文（资源页 Key 走 `GET config?reveal=1` 拉取；API 接入密钥接口本就返回值，纯前端切换），收回/重渲染回到密文安全态；复制直取明文，不依赖显示态；修改时值不变 = 不修改。
10. **检测/异步操作反馈**：连通检测按钮三态着色（§3.3）+ toast 汇总；重启等长操作进入等待态（半透明锁定 + 恢复探测）。
11. **卡级操作归属（v2.1）**：操作按钮放其作用对象的卡头/卡底（添加密钥在密钥卡头、恢复官方配置在参数卡头），不设游离页级操作行；表格行内启停用 `.switch`（可操作态），状态纯指示用圆点/徽章（数据态）。

## 9. 暗色主题规则

- 实现：`[data-theme="dark"]` 令牌整体反转（`base.css`），组件**零改动**自动适配；三态（浅/深/跟随系统）由 `main.js` 写 `data-theme`（`localStorage.mg-theme` 持久化 + `matchMedia` 系统联动）。
- 反转要点：**黑主色 → 白主色**（`--brand` #e8eaee / `--on-brand` 深字）；白底 → `#17191d` 系；软边框 → `#262a31`；阴影加深（.35/.55）；淡彩底改半透明（16-18%）；`color-scheme: dark`；开关 knob / 选中滚动条反向。
- **图表与降级组件必须走令牌**（§7.10）；禁止写死浅色值（如 `#fff` 底、`rgba(15,23,42,…)` 阴影须走令牌或 `[data-theme="dark"]` 覆盖）。唯一例外 `.code-block` 恒深底。
- 新组件验收必须双主题截图通过。

## 10. 响应式

参考页为桌面优先；网关补充：≤1280px 侧栏收窄 62px（仅图标）、`.content` 底部 -40px；≤768px 侧栏抽屉化（汉堡 `.nav-toggle`）、`.split-37/.form-grid2/.settings-half` 单列、`.tb-addr` 隐藏、`.page-actions` 换行；双面板页接管留白带对应断点（§2.3）；表格窄屏横向滚动（`.table-wrap`）；参数配置两列网格 ≤1080px 回退单列（models 页）。模板页保持桌面形态即可，新页面必须补上述断点。

## 11. 模板使用指南（`static/templates/`）

1. **选型**：带子列表 + 详情面板 → 复制 `template-providers.html`；tab 过滤 + 列表 → 复制 `template-skills.html`；指标/表格型数据页与工具页无模板 → 按 §5/§6 骨架 + §7 组件从零组装。
2. **改造步骤**：改侧栏分组/项与 active → 改面包屑分组名与页标题（顶栏）→ 替换面板数据 → 演示 JS 换成真实 API 绑定（网关 `api.js` GET/PUT + `components.js` toast/modal）。
3. **保持不动**：类名、DOM 结构层级、内联尺寸值；需要新组件时先查本规范，规范没有 → 提规范变更（记录值与出处）再实现。
4. 模板即**活规范**：修改组件样式必须同步改 `base.css` + 本文档，禁止在模板内私加 `<style>`。

## 12. 验收清单（新页面 PR 自检）

- [ ] 仅使用 §1 令牌与既有组件类；无新色值/圆角/阴影/字号（`.code-block` 恒深底除外）
- [ ] 间距全部落在 4/8/12/16/20/24；页面块间距 = 12px
- [ ] 卡片 = rounded-13 p-3 `--shadow-card`；表格卡 = `.card.flush` + `.card-head.inset`
- [ ] 按钮/输入/tab/开关/图标尺寸逐项对表（h-9 / h-11 / h-8 / 40×24 / 38 图标块 / 14 图标）
- [ ] 指标卡值单行 + `fmtValue` CJK 处理；表格数字列 `.num` 右对齐
- [ ] focus 态：输入边框转黑 + 底转白；tab 无 outline
- [ ] 图表色全部运行时取令牌（禁止硬编码系列色）
- [ ] 暗色主题截图通过；toast 反馈齐备；空态文案就位；删除类有确认弹窗
- [ ] 与模板/定版页并排对照无可见偏差（间距/对齐/字重）

## 13. 变更记录

| 版本 | 日期 | 内容 |
|---|---|---|
| v1.0 | 2026-09-05 | 从参考项目两页（ConsolePage.tsx :429-1363）逐行提炼成文；同步交付两模板 + base.css 模板组件层 |
| v1.1 | 2026-09-05 | §5.7 图标体系：Lucide 0.555.0 唯一图标库 + SVG 属性契约 + 选型表；全站 Feathers 旧 path 替换 |
| v1.2 | 2026-09-05 | 指标卡数值混排等视觉：CJK 段 `fmtValue()` 包 `.cv` .8em |
| v1.3 | 2026-09-05 | 字体内置 Inter（OFL 本地五字重）+ 指标数值 22px/800 → 19px/700、`.cv` .8em → .86em |
| v1.4 | 2026-09-05 | 模型资源页改版「模型供应商」模板版式（版本注；正文并入 v2.0 §3.3） |
| v1.5 | 2026-09-05 | 模型资源页六点修正：右区撑满接管留白 / 接入信息未设置时可编辑 / Key 标签式字段 + 单 Key 开关（版本注；并入 v2.0 §3.3） |
| v1.6 | 2026-09-05 | 厂商列表 group-card 化 + 接入配置只读常显（实验版，后被 v1.8 纤行取代） |
| v1.7 | 2026-09-05 | 禁「板块内框包框」+ 连通性检测上线（三态着色，版本注；并入 v2.0 §3.3） |
| v1.8 | 2026-09-05 | 接入信息并入 Key 卡（v1.9 纠错为并入头卡）+ 厂商纤行 + grid 三列模型列表 + 自定义下拉（版本注；并入 v2.0 §3.3） |
| **v2.0** | **2026-09-06** | **全站规范提炼定版**（以已定版的总览/模型资源/资源池设置三页与两模板为基准）：① §3 重写为「子侧栏双面板页」并落档两个网关实现变体（模型资源 / 资源池设置，含 v1.4–v1.8 全部定版结论）；② 新增 §2.4 四骨架选型表 + §5 数据观测页 + §6 工具页骨架（含脏态保存 / split-37 / settings-half / 表格卡 flush 变体）；③ 通用组件规范移至 §7 并扩充 §7.8–7.14：指标卡 / 表格 / 图表令牌化 / 弹窗 / 分页空态 / 区头页头 / 输入展示块；④ §8 交互范式补 D3 操作即保存 / 草稿槽位唯一 / 脱敏 / 检测反馈（原第 1–6 条语义不变）；⑤ 统一停用弱化 `opacity .5`（原 .45/.5/.55 收敛）、展开指示改 Lucide chevron、新增 `.sec-head/.card.flush/.pager/.sortable/.ellip/.off/.sticky-side/.btn.block/.center-card/.addr-group/.maint-*/.req-detail` 组件类；⑥ 剩余四页（数据看板/请求日志/API 接入/系统设置）按本版对齐落地。**章节重排**：原 §5 通用组件 → §7（图标体系 §5.7 → §7.7）、原 §6 交互范式 → §8（条目⑥「状态双呈现」不变）；历史文档中的旧节号引用按此对照 |
| **v2.1** | **2026-09-06** | **剩余四页系统性改造**（结构/布局/交互对齐定版页模式；定版三页零改动）：① 数据看板——CSV 导出按钮由孤立页级操作行迁入「维度明细」卡头，导出行序与表格共用 `sortState` 排序状态；② 请求日志——右表格卡 card-head 化（动态标题「请求流水/切换事件」+「共 N 条」计数由左筛选卡迁出右置）；③ API 接入——**改操作即保存（D3）**：废弃「保存配置」二段提交，启停改行内 switch 即时落库、用途标注改行内编辑失焦即存、添加/删除确认即 PUT 自同步重渲染，「＋ 添加密钥」移入密钥卡头；④ 系统设置——50/50 等高（settings-half）废弃，改纵向三卡自然高度堆叠，成为全站唯一脏态二段保存页；⑤ §5/§6/§8 同步定档「卡级操作归属」原则与 D3 适用范围 |
| **v2.10** | **2026-09-06** | **看板成功率卡值/附属分层**（用户截图指示「· 成功 79 · 失败 26 · 中断 10 改成小字附属信息」）：`metricCard()` 增可选 sub 参数（值下方 12px/600 tertiary 行，复用 `.metric-label` + `fmtValue`），成功率卡值行只留 `69%` 大字、枚举明细入 sub 行；其余卡不传不受影响（断言：值行无枚举/sub 行 12px/全页仅此一卡有 sub）；「值单行原则」记录此定版例外 |
| **v2.9** | **2026-09-06** | **数据看板双 tab 并行一行**（用户截图指出两组 tab 上下两行占空间）：时段 tab 与维度 tab 由两行改一个工具行容器并行（`flex wrap gap 12 align-items:center`——与模板「技能页」工具行同款模式，§4.1 多组 tab 并排 gap-3 的落地）；断言：两组 tab 同行（y 差 <2px、间距 12px）、3+5 段完整、≤768 换行不溢出 |
| **v2.8** | **2026-09-06** | **请求日志页改竖向排列**（用户指示「筛选和数据竖向排列，筛选项在上面」）：废弃 `.split-37` 3:7 左右分栏——筛选卡全宽置上（新增 `.filter-grid`：筛选字段 flex 均分横排一行 + 重置按钮右端，≤768 自动换行），日志表格卡全宽置下；`.sticky-side`（粘滞窄列）与 `.btn.block`（全宽钮）随分栏废弃并删类；DOM 断言 7/7（竖排相邻/字段同行/两卡等宽/无残留/窄屏换行） |
| **v2.7** | **2026-09-06** | **数字输入去 spinner + 正整数过滤**（用户截图指出输入框上下小箭头）：① base.css 全局 `input[type=number]` 隐藏原生 spinner（appearance textfield + webkit 伪元素 none——全站 number 输入仅系统设置 12 个，对未来输入统一生效）；② settings.js 输入框 input 事件正整数过滤（`replace(/[^\d]/g,"")`，键入/粘贴即时滤除 `-`/`.`/`e`，浏览器层本就拒绝字母串）；min 下限约束保留既有 change 校验 + 后端 400。断言：appearance 全 textfield、`-12.3e4/-5/1.5/1e2` 分别滤为 `1234/5/15/12`、脏态保存链路正常 |
| **v2.6** | **2026-09-06** | **导出功能全站移除**（用户指示「把系统内所有导出数据功能都去掉，不需要导出功能」）：① 数据看板——维度明细卡头「导出 CSV」按钮 + `exportCsv()/csvCell()` 整体删除（明细排序 `sortState` 保留供表格使用，toast import 同步清理）；② 系统设置——维护区「配置导出」块（导出全量配置含明文 Key / 导出脱敏配置）+ `exportConfig()` 删除，维护区仅剩系统启停。均为纯前端本地生成实现，无后端端点受影响；DOM 断言 9/9（两页无「导出」字样、排序/图表/启停/保存功能保持） |
| **v2.5** | **2026-09-06** | **弹窗脚钮间距修复**（用户截图指出「取消/生成并添加链接到一起」）：实现偏离 §7.11——`components.js modal()` 把调用方 footer 整个 div append 进 `.modal-foot`，`gap:8px` 作用于中间 div（唯一子元素）而非按钮间，实测按钮间距 0px；根修 = footer 子节点平铺进 `.modal-foot`，确认弹窗（confirmDialog）/ 添加接入密钥 / 添加模型三类弹窗一并恢复 8px（实测各 8px，取消路径不落库验证通过） |
| **v2.4** | **2026-09-06** | **API 接入页两点精修**（用户指示）：① 端点说明改两列式——`.endpoint-list` 由单列纵排改 2×2 网格（gap 16px、去 border-top 行分割线防网格错位，≤768 回退单列）；② 调用地址与端点说明两板块**等高**——`.split-50` 去 `align-items:start` 改 grid 默认 stretch，两卡底边对齐（实测 207px/207px） |
| **v2.3** | **2026-09-06** | **密钥密文化**（用户指示「系统密钥都要密文显示，点击查看才显示明文；复制按钮前加查看 icon」）：API 接入密钥值由明文直显改默认密文（`maskVal` 前 5 + `****` + 后 4，同资源页 Key 规格），行内 icon 顺序 = **眼睛（查看/收回明文）→ 复制**；眼睛就地切换不重渲染、重渲染后回到密文安全态；DOM 未泄露明文（断言：默认密文一致 / 页面文本不含明文 / 切换往返 / icon 顺序） |
| **v2.2** | **2026-09-06** | **API 接入页用户四点定版**：① 复制交互 icon 化——调用地址与密钥值不再用「复制」文字按钮，地址 `addr-value` 框内 URL 后内嵌 20×20 复制 icon（对齐资源页 Base URL 模式）、密钥值尾随复制 icon（`flex:0 1 auto` 紧贴值尾，长值截断）；② 调用地址与端点说明改 `.split-50` 等宽双板块并列（新增类），位置移至接入密钥卡下方；③ `.card-head .value` 补规范规则（13px/600 `--text-muted`）修正卡头主次层级（原无规则继承正文 14px 深色，比标题还重）；④ 使用示例（curl 卡）移除，`.code-block` 类保留预留 |
