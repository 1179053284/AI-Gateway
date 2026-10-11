# E2E 实测记录 · Q19 视觉重设计 + 资源导向映射（2026-09-03）

> 对应：PRD v1.6 §9-Q19（① 界面视觉重设计 + 静态资源禁缓存 / ② 资源导向模型映射）
> 设计：tech-design v1.3 §4.7-④/§4.9、design-spec v0.5；用例：test-cases v1.3 **INT-49** + **E2E-20 追加⑥⑦项**
> 网关：`http://127.0.0.1:8300/`（重启加载 Q19 新代码）；浏览器：ego-browser（Chromium，DOM 快照 + `Page.printToPDF` 截图取证，同 M2/Q18 口径）
> 执行方：AI（Trae）；执行时间：2026-09-03 16:30–16:50（本地）

---

## 0. 结论

| 项 | 结果 | 证据 |
|---|---|---|
| 全量回归 pytest | **185 passed**（38.89s，UT 29 + INT 49 + 其它，含新增 INT-49） | §1 |
| E2E-20 Q19 追加两项核验（⑥⑦） | **2/2 通过** | §2 |
| 「界面没变化」根因修复 | 静态资源 `Cache-Control: no-cache` 实测生效（HTML/JS/CSS） | §2.1 |
| 占位 id 全链路（UI 真实操作） | `@new-*` → `res-fc834f39` + 映射引用同步改写 | §2.2 |
| 业务链路（真实商汤） | chat 200（22 tokens）；测试对象已清理、配置与备份逐字节一致 | §3 |

---

## 1. 全量回归（UT/INT）

```
$ .venv/bin/python -m pytest -q
185 passed, 200 warnings in 38.89s
```

- 覆盖 test-cases v1.3 全部 UT（01~29）与 INT（01~49），含 Q19 新增 **INT-49**（占位资源 id `@new-1` → 生成真实 `res-xxxxxxxx` 并改写 `models[].resources[].resource` 引用 + 新模型即刻可调用，`tests/integration/test_int_admin_ext.py::test_int_49_placeholder_resource_ref`）。
- test-cases.md §6 状态矩阵已同步（UT 29/29、INT 49/49 通过）。

## 2. E2E-20 追加核验（Q19 两项）

### ⑥ 视觉重设计 + 静态资源禁缓存（Q19-①）

**根因定位**：用户报告「UI 效果还是没改」——静态资源（HTML/JS/CSS）响应无缓存控制头，浏览器强缓存命中旧 JS，界面改版不可见。修复 = `model_gateway/main.py` 新增 `_StaticNoCacheMiddleware`，静态资源统一 `Cache-Control: no-cache`。

**响应头实测（curl -I）**：

```
$ curl -sI http://127.0.0.1:8300/
Cache-Control: no-cache
Content-Type: text/html; charset=utf-8

$ curl -sI http://127.0.0.1:8300/js/pages/resources.js
HTTP/1.1 200 OK
Cache-Control: no-cache

$ curl -sI http://127.0.0.1:8300/css/base.css
Cache-Control: no-cache
```

**新 UI 骨架实测（浏览器 DOM + 计算样式）**：

- 暗色侧边栏：`.sidenav` computed `background-color: rgb(20, 24, 48)`（= #141830，design-spec §1.2 规格）。
- 品牌区：`.brand-name` = "Model-Gateway"（渐变 logo 标记 + 产品名）。
- 导航 7 项均含 `svg.nav-ico`（SVG 线性图标），标签：总览 / 资源管理 / **系统模型** / API 接入 / 数据看板 / 请求日志 / 系统设置（「模型映射」已更名「系统模型」，Q19-②）。
- 侧栏底部运行状态点（`.side-foot` + `#tb-status`）。
- 整页截图（printToPDF，423KB）存档 `/tmp/mg-ui-dashboard.pdf`（视觉证据，含暗色侧边栏布局）。

### ⑦ 资源导向模型映射（Q19-②）

**资源弹窗映射区（DOM 实测）**：

- 编辑既有资源弹窗：含「模型映射 · 厂商模型 → 系统统一模型（可就地新建）」区块；目标下拉列出全部已有系统模型（sensenova-6.8-flash-lite（已有）/ deepseek-v4-flash（已有）/ …）+「＋ 新建系统模型…」选项。
- 新增资源弹窗：厂商模型名输入（datalist `rm-vm-cands` 枚举池候选）+ 目标下拉（默认 `__new__` 就地新建）+ 新建子表单（系统统一模型名 / 端点 chat|images / 分组）。
- 资源表格「模型映射」列：既有资源显示「7 映射」。

**全链路实测（真实 UI 操作，非 API 直调）**：

1. 「+ 新增资源」弹窗填写：备注 `E2E-测试资源` / 账号 `e2e-账号` / base_url `http://127.0.0.1:19999/v1` / Key `sk-e2e-test-key`；映射行：厂商模型 `e2e-vendor-model` → 就地新建系统模型 `e2e-sys-model`（端点 chat / 分组 E2E测试）→ 点「创建」→ 页面「保存配置」提交。
2. **保存后 config 实测**（`GET /admin/api/config`）：
   - 新资源 id = `res-fc834f39`（占位 `@new-*` 已解析为真实 id，无 `@` 残留）；
   - 新模型 `e2e-sys-model`（分组 E2E测试 / chat）的 `resources[0].resource` = `res-fc834f39`（**引用同步改写成功**）、`model` = `e2e-vendor-model`。
3. 系统模型页实测：左侧分组列表出现「E2E测试」组含 `e2e-sys-model`；点选后右侧详情正确（分组：E2E测试 · 端点：chat；资源池 1. E2E-测试资源 [sensenova-api 徽章] / e2e-vendor-model；↑↓移除/删除模型控件在位）。
4. 资源页实测：表格新行「E2E-测试资源 | 商汤按量 API | e2e-账号 | API · 按量 | … | 1 映射」。
5. **清理还原**：系统模型页「删除模型」+ 保存配置 → 资源页「删除」+ 保存配置；`GET /admin/api/config` 与操作前备份**逐字节一致**（`配置一致: True`）——生产配置零污染。

## 3. 业务链路冒烟（真实商汤 TokenPlan）

```
$ curl -s -X POST http://127.0.0.1:8300/v1/chat/completions \
    -H "Authorization: Bearer <接入密钥>" -H "Content-Type: application/json" \
    -d '{"model":"sensenova-6.8-flash-lite","messages":[{"role":"user","content":"回复ok"}],"max_tokens":10}'
→ HTTP 200：choices[0].message（reasoning_content 前置，finish_reason=length，
  usage {prompt_tokens:12, completion_tokens:10, total_tokens:22}）
```

- Q19 改动（admin.py 占位解析 / 前端三文件重写 / no-cache 中间件）对业务链路零影响：真实调用 200、usage 统计正常。

## 4. 变更清单（Q19）

| 文件 | 变更 |
|---|---|
| `model_gateway/main.py` | 新增 `_StaticNoCacheMiddleware`（静态资源 `Cache-Control: no-cache`） |
| `model_gateway/api/admin.py` | `_autogen_ids` 扩展：`@new-*` 占位资源 id 解析 + `models[].resources[].resource` 引用同步改写 |
| `model_gateway/web/static/index.html` | 布局重写：暗色侧边栏 + 品牌区 + SVG 图标导航 + 底部状态点；「模型映射」→「系统模型」 |
| `model_gateway/web/static/css/base.css` | 视觉规范重写：暗色侧边栏色板 / 按钮卡片表格表单弹窗徽章 toast 现代化 / 响应式 |
| `model_gateway/web/static/js/pages/resources.js` | 弹窗下半部新增模型映射区（映射行 / 就地新建子表单 / `@new-*` 占位 id） |
| `model_gateway/web/static/js/pages/models.js` | 重定位为总览 + 微调（去新建/添加入口；启停/排序/effort/移除/删除保留） |
| `model_gateway/web/static/js/main.js` | 导航项名称同步（系统模型） |
| `tests/integration/test_int_admin_ext.py` | 新增 INT-49（占位 id 解析 + 引用改写 + 即刻可调用） |

## 5. 遗留与说明

- headless 环境 `captureScreenshot` 超时（同 Q18 轮），视觉证据以 `Page.printToPDF`（423KB 整页 PDF）+ DOM 计算样式替代；PDF 已存档 `/tmp/mg-ui-dashboard.pdf`。
- 视觉效果最终以用户浏览器实测为准（no-cache 已保证改版即时可见，需强制刷新一次旧缓存或正常刷新即可）。
- E2E-07（Trae 实配）仍为 SHELL 待用户验收；E2E-16~19 未执行（状态见 test-cases §6）。
