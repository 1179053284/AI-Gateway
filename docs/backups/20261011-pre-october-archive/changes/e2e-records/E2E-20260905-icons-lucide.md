# E2E 实测记录：图标体系统一 Lucide 0.555.0（20260905）

> 对应需求：网关图标与参考前端同体系。排查结论：参考全站使用 **lucide-react 0.555.0**
> （`package.json:51`），网关原为旧版 Feather 手抄 path（Lucide 是 Feather 分支，0.5xx 已大量改版）。
> **红线遵守**：参考项目全程只读（仅读源码 + node_modules path 数据 + HTTP 访问）。

## 一、参考图标体系（ConsolePage.tsx + node_modules 只读提取）

| 规则 | 值 | 出处 |
|---|---|---|
| 图标库 | Lucide `0.555.0`（ISC 开源） | package.json:51 |
| SVG 契约 | viewBox 24×24 · fill none · stroke currentColor · 圆角端点 | lucide 官方 |
| 导航图标 | 16px · 描边 **2.1** | ConsolePage :463-464 |
| 动作图标 | 14px · 描边 2（默认） | :481,:600,:924,:1216… |
| logo 块 | 20px | :709,:716 |
| 药丸 check | 12px · `#16d76d` | :1347 |

## 二、网关替换实施（scripts/icons_lucide_align.py + 手工 6 处）

脚本指纹替换 **72 处**（旧 Feather path → Lucide 0.555 官方 path，attr 顺序照官方）：

```
替换统计: trash-2×11 server×10 cpu×9 download×5 user×4 shield×4
chevron-right×3 search×3 sun×2 refresh-cw×2 file-text×2 wrench×2 settings×2
plus×2 check×1 layout-grid×1 database×1 layers×1 chart-column×1 list×1
key×1 sliders-vertical×1 menu×1 moon×1 monitor×1 eye×1
```

手工补充（`svg()` 帮助函数分离结构 + 文本符号）：
- `dashboard.js:53-54`：activity / arrow-left-right 换官方 path（coins/shield-check 原本已符合）
- `stats.js:76,82`：chart-column / image（rect 补 ry）
- `resources.js:228`：✕ 字符 → Lucide `x`
- `components.js:23`：弹窗关闭 ✕ 字符 → Lucide `x`
- `settings.js:159`：停止态 ⏹ emoji → Lucide `power`（40px · `--err`）
- `template-providers.html:207`：log-in 旧 polyline 格式 → 官方 3 path

导航图标选型（网关七页语义映射）：总览 `layout-grid` / 资源管理 `database` /
系统模型 `layers` / 数据看板 `chart-column` / 请求日志 `list` / API 接入 `key` /
系统设置 `sliders-vertical`；主题三态 `sun`/`moon`/`monitor`。

描边规范化：nav-ico 全部 2.1（原 1.9），主题/面包屑/动作图标全部 2（原 1.7/2.2/2.5）；
品牌 M 字 logo 保留（品牌标识，同参考品牌字母 C 性质）。

## 三、实测证据

**1) 残留清零（源码级 grep）**：

```
$ grep -rln 'polyline|rx="1.5"|M21 2l-2 2m|l1.4-1.4|M21 12.8A9|16.65|M3.51 9a9|
  M19.4 15a|3.77-3.77|M14 2H6|M1 12s4|M17 3a2.85|✕|⏹|points="3 6 5 6|…' index.html js/ templates/
grep-exit=1   ← 全站无旧 Feather path / 文本符号残留
```

**2) 描边分布**：`2.1`×21（导航 index 7 + 模板 14）· `2`×57 · `2.4`×1（品牌 logo）——无其他值。

**3) CDP 对比（网关 vs 参考，同屏同参）**：

```
gateway nav:   7×{sw:"2.1", size:"16px"}    ← 与参考逐项一致
reference nav: 7×{sw:"2.1", size:"16px"}

gateway search icon:  {fill:"none", stroke:"rgb(163,171,179)"＝#a3abb3, sw:"2px",
                       d:"m21 21-4.34-4.34"}   ← Lucide 官方 path
reference（:1216）:   SearchIcon h-3.5 w-3.5 text-[#a3abb3]（默认 sw 2）→ 逐属性一致
```

**4) 模板交互态**：CDP 点击 API Key 模式 → `panel-api` 可见，Lucide 精确 path 命中
`trash-2`×8、`plus`×2；`eye` path `M2.062 12.348…` 源码级确认（grep 计数 1）。

**5) JS 语法**：`node --check` dashboard/stats/settings/resources/components 全部 OK。

**6) 截图（icons-lucide-screenshots/ · 7 张）**：
ref-providers-nav（参考基准）· mg-dashboard-nav（导航 7 图标 + 指标卡
activity/arrow-left-right/coins/shield-check）· mg-stats-nav ·
tpl-providers-icons · tpl-providers-api-icons（eye/trash/plus 交互态）·
tpl-skills-icons · tpl-skills-installed-check（开关 + trash 交互态）。
目检结论：全部图标线性描边风格渲染正常，无破图。

## 四、规范同步

`docs/specs/frontend-spec.md` 升版 **v1.1**：新增 §5.7 图标体系（Lucide）——
SVG 属性契约 / 尺寸描边用法对照表（含参考行号）/ 网关图标选型表 / 权威取图来源
（参考项目 node_modules `__iconNode`，只读）。

## 五、结论

- 图标库统一 Lucide 0.555.0（与参考同库同版本同 path）：**通过**（72+6 处替换，残留清零）
- 导航描边/尺寸与参考逐项一致（2.1/16px，CDP 实测）：**通过**
- 搜索图标与参考逐属性一致（fill/stroke/sw/path）：**通过**
- 文本符号（✕ ⏹）全部图标化：**通过**
- 参考项目零改动（全程只读）：**遵守**
