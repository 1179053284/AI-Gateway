# E2E · 2026-09-06 · frontend-spec v2.0/v2.1 提炼 + 剩余四页系统性改造

> 任务：根据已定版的「总览 / 模型资源 / 资源池设置」三页与两个模板页，提炼完善前端 UI 规范（frontend-spec v2.0 → v2.1），并把剩余四页（数据看板 / 请求日志 / API 接入 / 系统设置）的**结构、布局、功能细节**系统性改造到位。**定版三页零改动**（用户明确要求）。

## 1. 改动清单（证据：file:line + DOM 断言 + 截图）

### 1.1 规范文档
| 文档 | 版本 | 内容 |
|---|---|---|
| `docs/specs/frontend-spec.md` | v2.0 | 全站提炼定版：§2.4 四骨架选型表；§3 重写「子侧栏双面板页」+ 两网关实现变体（v1.4–v1.8 版本注内容正式落档正文）；§5 数据观测页 / §6 工具页骨架；§7.8–7.14 组件档（指标卡 / 表格 / 图表令牌化 / 弹窗 / 分页空态 / 区头页头 / 输入展示块）；§8 交互范式补 D3 / 草稿槽位唯一 / 脱敏 / 检测反馈；变更记录补齐 v1.1–v2.1 |
| `docs/specs/frontend-spec.md` | v2.1 | 剩余四页系统性改造定档：API 接入改 D3、系统设置纵向三卡堆叠 + 唯一脏态保存页、请求日志右卡 card-head 化、数据看板卡级操作归属；§3 加注定版页为内联等价实现（新页面用 .sec-head 类，不回改定版页） |
| `docs/specs/design-spec.md` | v2.9 | §2.4 API 接入口径同步（D3：启停/增删即落库）；§2.7 系统设置布局改纵向三卡自然高度堆叠（废弃 50/50 等高） |

### 1.2 样式（`model_gateway/web/static/css/base.css`）
- 新增 v2.0 组件类：`.sec-head(.sub/.t/.d)`、`.card.flush` + `.card-head.inset`、`.pager`、`.tbl th.sortable`、`.tbl td.strong`、`.tbl .ellip`、`.tbl td.exp`、`.req-detail(.errline/.sep)`、`.sticky-side`、`.btn.block`、`.center-card`、`.addr-group`（`.addr-row` gap 8→16px）、`.maint-grid/.maint-title(.danger)/.maint-ops`、`.off/.locked`
- **根修**：`.icon-btn` `display:grid` → `inline-grid`（base.css:474 附近）——grid 块级在 td 内独占一行，曾致 API 接入密钥行「复制 + 删除」换行错位（getBoundingClientRect 实测 y 差 30px → 修复后 sameRow=True）；对既有 flex 容器内用法零影响
- 图表令牌化（stats.js `drawChart`）：系列色硬编码 `#16a34a/#dc2626/#d97706` → 运行时读 `--ok/--err/--warn` 令牌（`tok()` + `alpha()` 透明填充），暗色自动反转（截图 stats-dark 三系列为亮色变体证实）

### 1.3 四页系统性改造（定版三页 + dashboard.js 零改动）
| 页面 | 改造点 |
|---|---|
| `pages/stats.js` 数据看板 | ① 指标卡对齐总览定版：`metric()` 四参 sub 行废弃 → `metricCard()` 三参**值单行**（`·` 并列）+ `fmtValue()` CJK 混排等高；② 孤立页级操作行（page-head「导出当前表格 CSV」）移入「维度明细」卡头（download 14px 图标 + `.btn.btn-sm`）；③ 明细表排序状态提升为模块级 `sortState`，**CSV 导出行序 = 表格当前排序**（原固定按 requests）；④ 表头排序键 `.sortable` 类化；⑤ 名称列 `.strong` 类化 |
| `pages/logs.js` 请求日志 | ① 右日志表格卡 card-head 化：动态标题（请求流水/切换事件）+ 右置 `.value`「共 N 条」（原计数挤在左筛选卡底部）；② 筛选卡 `.sticky-side` 类化、重置钮 `.btn.block`；③ 展开指示 `▸/▾` 字符 → Lucide `chevron-right/chevron-down` 14px（`.exp` 格）；④ 展开详情 `.req-detail/.errline/.sep` 类化；⑤ 表格 `.sortable/.strong/.ellip` 类化 |
| `pages/apiaccess.js` API 接入 | **交互模式改操作即保存（D3，对齐资源页 persist 自同步）**：① 废弃「保存配置」二段提交与 dirty 脏态；② 密钥启停改行内 `.switch` 即时落库（原「停用」文字钮）；③ 用途标注改行内无边框输入失焦即存；④ 添加密钥弹窗确认即 PUT（服务端生成 tok-/mg-，toast「已生成密钥并生效」）；⑤ 删除确认即落库；⑥ 「＋ 添加密钥」移入密钥卡头（`.card-head.inset` 右侧）；⑦ 密钥清单卡 `.card.flush` + `.card-head.inset` 类化；⑧ 调用地址 `.addr-group` 成组（本机/局域网各一组，组间 16px）；⑨ page-head 操作行移除（保留 page-desc 导语） |
| `pages/settings.js` 系统设置 | ① 布局：50/50 等高（`.settings-half`，01 卡被迫内滚、02 卡大量空白）→ **纵向三卡自然高度堆叠**（01 任务执行 / 02 系统日志 / 维护，12px 节奏）；② **脏态徽章死 UI 修复**：`bindExec` change 只解禁保存钮、徽章只在重渲染时出现（实际永不显示）→ `markDirty()` 就地补插 `badge b-warn`；③ 小节头 `.sec-head.sub`、维护区 `.maint-*`、停止提示 `.center-card` 类化；④ 移除空函数 `bindLogs` |
| 公共 | `components.js` `pagination()` 内联样式 → `.pager` 类；`index.html` 装载兜底卡 → `.center-card` 类 |

### 1.4 定版三页零改动验证
- `dashboard.js` / `resources.js` / `models.js` 与用户验收版本一致（中途曾做等价类迁移，按用户「三页不要改」要求**已全部回滚**，grep `sec-head|class="off"|locked` = 0 残留）
- DOM 不变性抽查：总览 8 指标卡 ✓ / 模型资源子侧栏纤行 + 头卡编辑 + 无 sec-head 类 ✓ / 资源池设置厂商卡 + 三区头 section ✓

## 2. 验证证据

### 2.1 静态检查与回归
- JS 语法：`node --check` 全部 pages/*.js + js/*.js 通过
- pytest：**199 passed**（41.05s，与改造前持平，无回归）

### 2.2 DOM 断言（CDP，headless Chrome，23/23 PASS）
- stats：无孤立 page-head / 导出在明细卡头（`.card-head #s-export` + svg）/ 指标卡 ≥6 值单行 / sortable ≥8
- logs：右卡头动态标题「请求流水」/ 计数在 `.value` / 筛选卡无计数残留 / `.exp` 带 svg
- apiaccess：无 `#a-save` / 无 page-actions / 添加密钥在 `.card-head.inset` / switch / 行内输入 / icon-btn danger 删除
- settings：无 `.settings-half` / 三卡堆叠 / `.sec-head.sub` ×2 / `.maint-grid` / 保存钮禁用
- 定版三页不变性（见 1.4）

### 2.3 交互抽查（CDP 模拟点击，11/11 PASS）
1. logs 展开行：点击 → `.req-detail` 显示 + chevron-down 切换 → 再点收回 ✓
2. stats：列头点击排序箭头出现 ✓；导出按钮位于明细卡头 ✓
3. **apiaccess D3 启停往返**：switch 点击 → 翻转 + PUT 后自同步重渲染保持 → 再点击往返 → **配置恢复原状（无残留变更）** ✓
4. apiaccess 添加密钥弹窗：打开 → 取消 → 密钥数不变（不落库）✓
5. settings 脏态：改值 → `badge b-warn` 出现（死 UI 修复生效）+ 保存钮解禁 → 整页重载 → 徽章消失 + 输入还原（不保存即还原）✓

### 2.4 双主题截图（15 张，`frontend-spec-v2-screenshots/`）
七页 × 浅色/深色 wide（14 张）+ 总览窄屏 1 张；关键确认：
- stats 浅/深：指标值单行、「4 张」CJK 混排等高、**图表三系列色随主题令牌反转**（浅 `#20a877/#d95757/#c26a00` ↔ 深 `#3ddc97/#f08a8a/#f0a35c`）
- apiaccess：D3 版式（无保存钮 / switch / 卡头添加钮 / 操作列同行）
- logs：右卡头「请求流水 · 共 N 条」；settings：纵向三卡 + 维护区
- dashboard/resources/models：与验收版一致（未动）

## 3. 遗留与说明
- apiaccess D3 化将 design-spec §2.4「保存统一走页内保存配置」旧口径升级为 D3（design-spec v2.9 已同步）——启停/删除/添加均有即时落库与确认弹窗，语义风险（401 立即生效）在确认文案中列明
- `.settings-half` CSS 类保留未删（无页面引用；后续可清理）
- 期间检测到外部并行修改（models.js attrRows 档位文案、frontend-spec 节号等），已基于最新内容重放改造并逐项核对，无冲突残留

## 4. 追加 · API 接入页用户四点定版（同日第二轮，frontend-spec v2.2 / design-spec v2.10）

用户四点指示与落实：

| # | 指示 | 落实 | 证据 |
|---|---|---|---|
| 1 | 调用地址、Key 不用复制按钮，改复制 icon，icon 放框内链接后 | 地址 `addr-value` 值块内 URL 后内嵌 20×20 复制 icon（对齐资源页 Base URL 模式）；密钥值尾随复制 icon（`flex:0 1 auto` 紧贴值尾 8px，长值 ellip 截断 + title 全值）；全页无「复制」文字按钮 | DOM 断言：地址 icon 在框内且 data-copy 含 URL ✓ / 密钥 `.ellip + button.icon-btn svg` ✓ / 地址列无 `.btn` ✓ / 操作列仅剩删除 icon ✓ |
| 2 | 调用地址、端点说明横排并列 2 板块，放接入密钥下面 | 新增 `.split-50`（grid 1fr 1fr gap 12，≤768 单列）；页面顺序 = page-desc → 接入密钥 flush 卡 → split-50（调用地址 ｜ 端点说明） | DOM 断言：结构顺序（flush 紧邻 split-50）✓ / 两卡标题「调用地址|端点说明」✓ / 两卡等宽（差 <2px 且 >400px）✓ |
| 3 | 接入密钥标题与提示字号不对，主次逻辑乱 | 根因：`.card-head .value` 无 CSS 规则，统计提示继承正文 14px 深色比 13px 标题还重；base.css 补 `.card-head .value { 13px/600 --text-muted }` 全站规则（logs「共 N 条」/ stats 卡说明 / settings 卡说明一并归位） | DOM 断言：computed fontSize=13px 且 fontWeight=600 ✓ |
| 4 | 去掉使用示例 | curl 示例卡整卡移除（`#a-example` 渲染段一并删除）；`.code-block` 类保留预留 | DOM 断言：无 `#a-example` 且无「使用示例」卡头 ✓ |

- 回归：pytest **199 passed**；API 接入页专项 DOM 断言 10/10 PASS；全站断言 22/23 PASS（唯一 FAIL 为测试时点跨 UTC 日——09-06 当日无日志致空表无展开行，切 09-05 后 22 行 + 展开功能完好、空态文案正常，非代码回归）
- 截图：`frontend-spec-v2-screenshots/mg-q22-apiaccess-{light,dark}-wide.png` 已更新（双主题）
- 文档：frontend-spec v2.2（§6 结构 / §7.13 `.card-head .value` / §7.14 `.split-50` + `.code-block` 预留 / 变更记录）、design-spec v2.10（§2.4 ASCII 与条目重绘）、AGENTS.md 状态链

## 5. 追加 · 接入密钥密文化（同日第三轮，frontend-spec v2.3 / design-spec v2.11）

用户指示：「系统密钥都要密文显示，点击查看才可以显示明文。密钥类信息复制按钮前面要有一个显示和加密的查看 icon。」

落实（对齐资源页 Key 成熟模式）：
- **默认密文**：接入密钥值由明文直显改为 `maskVal` 脱敏（前 5 位 + `****` + 后 4 位，与资源页 Key 同规格）——如 `mg-trae-e2e-2026` → `mg-tr****2026`；悬停 title 不再含明文（原实现 title 泄露全值，一并修复）
- **眼睛查看**：行内 icon 顺序 = **眼睛（查看明文 ⇄ 收回，Lucide `eye`/`eye-off`）→ 复制**；就地切换不触发重渲染，重渲染（启停/增删后）自动回到密文安全态
- **复制不变**：复制 icon 直取明文（不依赖显示态）
- 资源页（模型资源）Key 本就是此模式，本轮不改动

验证（CDP DOM 断言 8/8 PASS）：
1. 默认密文与 `config` API 明文按 maskVal 规格一致 ✓
2. DOM 页面文本不含明文（无泄露）✓
3. icon 顺序 = 眼睛在前、复制在后 ✓
4. 点眼睛 → 明文显示 + eye-off 图标 ✓；再点 → 收回密文 ✓
5. 两行密钥均默认密文 ✓

回归：pytest 199 passed 持平；截图 `frontend-spec-v2-screenshots/mg-q22-apiaccess-{light,dark}-wide.png` 已更新。

## 6. 追加 · 端点两列 + 双板块等高（同日第四轮，frontend-spec v2.4 / design-spec v2.12）

用户指示：「端点说明改为两列式结构，把调用地址和端点说明调整为等高的两个板块。」

落实（纯 CSS，JS 零改动）：
- **端点说明两列式**：`.endpoint-list` 由单列纵排改 `grid 1fr 1fr gap 16px`（4 个端点排 2×2）；**去掉 endpoint-item 行间 border-top 分割线**——网格中行分割线会错位（资源池参数卡同款教训，design-spec v2.8）；≤768 回退单列
- **两板块等高**：`.split-50` 去掉 `align-items:start` → grid 默认 stretch，「调用地址」与「端点说明」两卡拉伸至等高、底边对齐

验证（CDP DOM 断言 6/6 PASS）：
1. `.endpoint-list` computed 两列 ✓；4 个端点前两个同行、后两个换行（2×2）✓；分割线残留 0 ✓
2. 两板块高度 207px / 207px（差 <2px）✓
3. ≤768：端点回退单列 ✓、双板块回退单列 ✓

截图：`frontend-spec-v2-screenshots/mg-q22-apiaccess-{light,dark}-wide.png` 已更新。

## 7. 追加 · 弹窗脚钮间距修复（同日第五轮，frontend-spec v2.5 / design-spec v2.13）

用户截图指出：「弹窗下面的操作按钮都链接到一起了，不符合规范」（添加接入密钥弹窗「取消」与「生成并添加」贴死）。

**根因（实现偏离规范，规范 §7.11 本就规定脚钮 flex gap 8px）**：`components.js modal()` 把调用方传入的 footer **整个包装 div** append 进 `.modal-foot`——DOM 变成 `.modal-foot > div > button×2`，`gap:8px` 作用于中间 div（唯一子元素）而非按钮之间，按钮在 div 内以默认 inline 排列紧贴。实测修复前按钮视觉间距 **0px**。

**根修**：`modal()` 改为将 footer 子节点**平铺**进 `.modal-foot`（`while (footer.firstChild) footEl.append(footer.firstChild)`），flex gap 直接分隔按钮；`.modal-foot > div` 中间层消失。三类弹窗一并受益：
1. 确认弹窗 `confirmDialog`（取消/确定）
2. 添加接入密钥（apiaccess `addKeyModal`）
3. 添加模型（models `addModelModal`）

验证（CDP DOM 断言 5/5 PASS）：
1. 添加接入密钥弹窗：取消↔生成并添加间距 = **8px**（实测 8px）；`.modal-foot` 首子元素为 BUTTON（无中间 DIV）✓
2. 添加模型弹窗：取消↔添加间距 = 8px ✓
3. 确认弹窗（资源删除供应商）：取消↔确定间距 = 8px ✓；**取消路径不落库**——供应商数前后一致 ✓

截图：`frontend-spec-v2-screenshots/mg-modal-foot-gap.png`（弹窗打开态，间距正常）。

## 8. 追加 · 导出功能全站移除（同日第六轮，frontend-spec v2.6 / design-spec v2.14）

用户指示：「把系统内所有导出数据功能都去掉，不需要导出功能。」

全站盘点（grep「导出/export」）共两处，均删除：

| 位置 | 删除内容 | 保留 |
|---|---|---|
| 数据看板 `stats.js` | 维度明细卡头「导出 CSV」按钮（含 download 图标）、`exportCsv()`、`csvCell()`、`#s-export` 绑定、`toast` import | 明细排序 `sortState`（表格排序仍用）、指标卡/图表/双 tab 全部功能 |
| 系统设置 `settings.js` | 维护区「配置导出」块（导出全量配置含明文 Key / 导出脱敏配置两按钮）、`exportConfig()` 及绑定 | 维护区「系统启停」（重启/停止 + 确认弹窗）、脏态保存 |

说明：两处导出均为**纯前端本地生成**（CSV Blob / config GET 下载），后端无导出端点，`?reveal=1` 明文接口保留（资源页眼睛在用）——删前端即彻底移除，无后端受影响。

验证（CDP DOM 断言 9/9 PASS）：
- stats：无 `#s-export`、全页无「导出」字样；明细排序表头 ≥8、指标卡 ≥6、图表 canvas 在（功能保持）
- settings：无 `#st-export`/`#st-export-masked`、全页无「导出」字样；维护区危险标题仅「系统启停」×1、重启/停止按钮在、保存钮禁用态正常

回归：pytest **199 passed**；截图 `frontend-spec-v2-screenshots/` 15 张已更新。

## 9. 追加 · 数字输入去 spinner + 正整数过滤（同日第七轮，frontend-spec v2.7 / design-spec v2.15）

用户截图指出：系统设置参数输入框右侧有浏览器原生的上下小箭头，要求去掉并限制正整数格式输入。

落实：
- **隐藏 spinner（base.css 全局）**：`input[type=number] { appearance: textfield }` + `::-webkit-outer/inner-spin-button { -webkit-appearance: none }`——全站 number 输入仅系统设置 12 个（网关 4 + 调度 6 + 系统日志 2），规则全局生效对未来输入统一
- **正整数过滤（settings.js）**：每个 `[data-sec]` 输入框加 input 事件监听，`value.replace(/[^\d]/g, "")` 即时滤除非数字字符（键入与粘贴均覆盖）——禁负号、小数点、科学计数法 `e`；含字母的串由 `type=number` 浏览器层拒绝（value 置空），双层兜底
- **校验链路不变**：min 下限（端口≥1、x/y≥1、m/冷却≥0 等）由既有 change 分支 Number() 转换 + 后端 400 校验兜底，空值 = 不修改语义保留

验证（CDP DOM 断言 9/9 PASS）：
1. 全部 number 输入 computed `appearance: textfield`（spinner 不渲染）✓
2. 非法格式即时滤除：`-12.3e4`→`1234`、`-5`→`5`、`1.5`→`15`、`1e2`→`12`、`-9.9`→`99` ✓
3. 合法值仍正常触发脏态徽章 + 保存解禁（链路无回归）✓

回归：pytest **199 passed**；截图 `frontend-spec-v2-screenshots/` 15 张已更新。

## 10. 追加 · 请求日志页竖向排列（同日第八轮，frontend-spec v2.8 / design-spec v2.16）

用户指示：「把筛选和日志数据改为竖向排列结构，筛选项在上面。数据信息在下面。」

落实：
- **废弃 `.split-37` 3:7 左右分栏**：筛选卡全宽置上（卡间距 12px）、日志表格卡全宽置下
- **新增 `.filter-grid`（base.css）**：筛选字段横排一行——`flex wrap gap 12 align-items:flex-end`，字段 `flex:1 1 200px` 均分、重置按钮 `flex:none` 右端；窄屏自动换行；切换事件 tab 时仅日期字段 + 提示文案 + 重置
- **随分栏废弃删除类**：`.sticky-side`（粘滞窄列）、`.btn.block`（重置钮恢复常规宽度）——grep 全站无引用残留
- 日志表格卡（动态标题 + 共 N 条 + 可排序表格 + 展开行 + 分页）结构不变

验证（CDP DOM 断言 7/7 PASS）：
1. 竖排相邻：筛选卡与日志表格卡为兄弟节点且紧邻（筛选在前）✓
2. 筛选字段横排：日期/模型/状态/密钥 4 字段同一行（y 相同）✓；重置按钮与字段同行右端 ✓
3. 两卡等宽（均全宽）✓；`.sticky-side` 零残留 ✓
4. 计数/表格/分页功能保持 ✓
5. ≤768：字段自动换行（多行）✓

回归：pytest **199 passed**；截图 `frontend-spec-v2-screenshots/` 15 张已更新（logs 竖排版式）。

## 11. 追加 · 数据看板双 tab 并行一行（同日第九轮，frontend-spec v2.9 / design-spec v2.17）

用户截图指出：数据看板的时段 tab（今日/近7天/近30天）与维度 tab（按模型/按资源/按密钥/按厂商/按账号）上下两行占空间，要求并行放到一行。

落实：两组 tab 收进一个工具行容器（`display:flex; flex-wrap:wrap; align-items:center; gap:12px`）——与模板「技能页」工具行（frontend-spec §4 工具行模式：多组分段 tab 并排 gap 12）同款；窄屏自动换行不溢出。

验证（CDP DOM 断言 4/4 PASS）：
1. 两组 tab 同一行（y 差 <2px，组间距 12px）✓
2. 时段 3 段 + 维度 5 段完整，tab 切换/指标卡/图表功能保持 ✓
3. ≤768：维度 tab 换行至时段 tab 下方、不溢出内容区 ✓

回归：pytest **199 passed**；截图 `frontend-spec-v2-screenshots/` 15 张已更新（stats 工具行版式）。

## 12. 追加 · 看板成功率卡值/附属分层（同日第十轮，frontend-spec v2.10 / design-spec v2.18）

用户截图指示：成功率卡「把 `· 成功 79 · 失败 26 · 中断 10` 改成小字附属信息显示」。

落实：`stats.js metricCard()` 增可选 `sub` 参数——值行下方追加 12px/600 `--text-tertiary` 小字行（复用 `.metric-label` 类 + `fmtValue` CJK 处理）；成功率卡值行只留 `69%` 大字，「成功 N · 失败 N · 中断 N」枚举移入 sub 行；其余指标卡不传 sub、保持值单行不受影响。总览页 metricCard 为独立实现，零改动。

> 规范注记：此项为指标卡「值单行原则」（design-spec v1.0 定版）的**用户定版例外**——长枚举附属信息拆小字行，已记入 frontend-spec §7.8 与 design-spec §1.3。

验证（CDP DOM 断言 4/4 PASS）：
1. 成功率卡三行结构：label「成功率」12px → value「69%」**19px 且不含枚举** → sub「成功 79 · 失败 26 · 中断 10」**12px** ✓
2. 全页仅成功率卡一处 value+sub 组合（其余卡无 sub 行）✓
3. 指标卡总数保持（≥6）✓

回归：pytest **199 passed**；截图 `frontend-spec-v2-screenshots/` 15 张已更新。
