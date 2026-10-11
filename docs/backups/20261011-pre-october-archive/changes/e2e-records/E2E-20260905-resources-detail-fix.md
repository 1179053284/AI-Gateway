# E2E-20260905 · 模型资源页细节修正 + 连通性检测上线

> 日期：2026-09-05 · 层级：UI 层 + API 层（新增测试端点）
> 反馈：① 讨厌板块内框包框；② 模型列表对齐/箭头/hover 细节；③ 加模板同款连通性检测

## 落地对照

| # | 反馈 | 落地 |
|---|---|---|
| 1 | 去掉板块内框包框（外层实线框 + 内部边距） | Key 组行去边框与 padding，改 1px 分隔线行（字段自带标签+输入框，无嵌套框） |
| 2a | 供应商模型左对齐 | 输入框 padding 归零，文字与表头「供应商模型ID」同 x 起点（实测两者均距卡左 13px，对齐） |
| 2b | 去掉 hover 弹层与下拉箭头、缩小列宽 | 移除 datalist（`list` 属性）——Chrome 的联想箭头与悬浮预览一并消失；列宽 340px 固定 |
| 2c | 系统映射模型ID 左对齐、展开箭头别太靠右 | 下拉 260px 固定 + `padding-left:0`（文字左对齐、箭头贴近文字）；表头同列对齐 |
| 2d | 操作列图标位置 | 操作列 76px 居中：检测 + 删除两枚 icon-btn |
| 3 | 加模板同款连通性检测 | 每行「检测连通性」按钮（cpu 图标）→ `POST /admin/api/resources/test`：走该资源配置的适配器/Key 发最小请求（`max_tokens:1`，超时 min(30s, 尝试超时)）；前端对该厂商**全部启用 Key** 逐个检测，toast 汇总「连通正常 · N/N · 最快延迟」或失败明细；FR-9.1 单资源测试最小版提前落地 |

## 实测证据
- 后端直测：`POST /admin/api/resources/test {"resource":"res-sensenova-main","model":"sensenova-6.8-flash-lite"}` → **`{"ok":true,"latency_ms":521}`**（真实调用商汤）。
- 界面链路：点行内检测按钮 → toast **「连通正常 · 1/1 · 370ms」**、按钮状态恢复（rv4-test-toast.png）。
- 对齐断言：vm 文字与表头同 x（均 13px）；`hasDatalistArrow:false`；`sysW:260`；`testBtns:7`；`keyRowBoxed:false`（rv4-final.png）。
- 回归：pytest 全量 **187/187 passed**。

## 说明
- 连通性检测会对厂商发真实最小请求（约 1 token 消耗）——连通性验证的固有成本。
- 枚举池联想（datalist）随箭头一并移除；录入联想后续随模型目录重构（T1）统一回归。
