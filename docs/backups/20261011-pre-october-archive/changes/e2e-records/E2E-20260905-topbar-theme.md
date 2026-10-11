# E2E 实测记录：顶栏精简 + 三图标主题组 + 总览页头移除（20260905）

> 对应需求（用户三条指令）：
> 1. 去掉总览页面右上方 v0.1.0、16h29m、在途 0
> 2. 主题切换改三图标（太阳=浅色 / 月亮=深色 / 自动=跟随系统），大小按设计规范
> 3. 内容板块去掉页头栏与网址信息（`/html/body/div[1]/div/main/div[1]`）

## 一、改动清单

| # | 文件:位置 | 改动 |
|---|---|---|
| 1 | `index.html:88-105` | 顶栏右移除 `tb-version`/`tb-uptime`/`tb-inflight` 三 span 及 `·` 分隔符 |
| 1 | `main.js:53-61` | `refreshTopbar()` 删除三项文本写入（保留侧栏底部状态点轮询）；移除失用的 `fmtUptime` import |
| 2 | `index.html:90-103` | 主题切换 = `.theme-group` 三 `icon-btn` 直切（sun/moon/monitor，Lucide sw2） |
| 2 | `main.js:87-102` | 下拉弹出逻辑（theme-btn/theme-menu/外点关闭）全部移除 → 三按钮 `onclick` 直切；active 态 `.on` 同步 |
| 2 | `base.css:156-161` | 新 `.theme-group`（gap 4px）+ `.icon-btn.on` = `--brand` 黑底 `--on-brand` 反白；删旧 `.theme-wrap/.theme-btn/.theme-menu` |
| 3 | `dashboard.js:5-10` | 删除 `.page-head`（页级地址栏，即 `main > div[1]`），内容首块直出指标卡网格 |
| 附 | `base.css:535-536` | 补回 `.dropdown` 依赖的 `menu-in` keyframes + 新增 `.pos-wrap` 定位锚（模板顶栏下拉用，替代已删 `.theme-wrap` 的定位作用） |
| 附 | 两模板 `:79-80` | `theme-wrap` → `pos-wrap`（类名语义化，模板功能不变） |

**规范尺寸依据**（frontend-spec §5 组件层）：`icon-btn` 32×32 · rounded-10 · 图标 14px sw2 ——
与参考项目按钮内动作图标（:600,:924 14px/sw2）同体系；active 黑底反白同 tab active 语义（Q22 黑主色令牌）。

## 二、CDP 实测（headless Chrome 1440×940 @2x）

**1) 顶栏精简**：

```json
{"version":false,"uptime":false,"inflight":false,"rightText":"重载配置"}
```

**2) 三图标主题组**（尺寸 + active + 切换行为）：

```json
[{"mode":"light","iconPx":"14px","btnPx":"32px x 32px"},
 {"mode":"dark","iconPx":"14px","btnPx":"32px x 32px"},
 {"mode":"system","active":true,"iconPx":"14px","btnPx":"32px x 32px"}]

点击月亮 → {"theme":"dark","stored":"dark"}        ← data-theme + localStorage 双生效
点击太阳 → "light"
点击显示器 → {"theme":"light","activeMode":"system"} ← 跟随系统正确解析（无系统暗色偏好→浅色）

active 计算样式：{bg:"rgb(23, 27, 34)"＝#171b22, color:"rgb(255, 255, 255)"}  ← 黑底白图
.tb-right 子元素 = [tb-addr(空), theme-group, 重载配置] · 图标总数 = 3（无多余元素）
```

**3) 总览内容首块**：

```json
{"firstChild":"card-grid","hasPageHead":false}
```

**4) 模板回归**：`template-{skills,providers}.html` HTTP 200，profile 下拉脚本
（`profile-btn`/`profile-menu`）与 `?theme=dark` 预览不受影响。

## 三、过程问题（诚实记录）

首轮验证发现 dashboard 渲染报错 `esc is not defined`——因移除 `call_addresses` 时误删了
仍被 :34,:59-61,:69 使用的 `esc` import，随即补回（`dashboard.js:3`）并复测通过。
期间 visual 分析两度误报（"顶栏多两个图标"/"无 active 态"），以 CDP 硬数据定论推翻：
tb-right 实际仅 3 图标；active 按钮 computed `#171b22` 黑底白字渲染正确。

## 四、截图（topbar-theme-screenshots/ · 2 张）

- `mg-topbar-light.png`：浅色 · 显示器 active 黑底 · 顶栏仅主题组 + 重载配置 · 首块四指标卡
- `mg-topbar-dark.png`：点击月亮后的深色主题全页

## 五、文档同步

- `design-spec.md` 升版 **v0.9**：§1.2 布局图 / §1.2 顶栏两行结构 / 主题切换条目改为三图标直切；版本头记录三项修正与原因链
- `frontend-spec.md` §5.7 图标选型表不变（sun/moon/monitor sw2 仍准确）

## 六、结论

- 顶栏三项轮询文本移除：**通过**（元素不存在 + 右侧文本仅「重载配置」）
- 三图标主题直切（尺寸合规范 / active 黑底白图 / 三模式切换 + 持久化 + 系统联动）：**通过**
- 总览页头（总栏 + 网址）移除：**通过**（`main > div[1]` = card-grid，无 page-head）
- 模板与既有页面回归无损：**通过**（模板 200 + 下拉/暗色预览正常；JS 语法校验通过）
