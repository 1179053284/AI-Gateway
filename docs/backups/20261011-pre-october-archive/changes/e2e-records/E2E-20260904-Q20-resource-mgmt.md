# E2E 实测记录 · Q20 资源接入管理三项修正（2026-09-04）

> 对应：PRD v1.7 §9-Q20（① 厂商名称自定义 / ② 映射区去除端点与分组选择（归系统模型页）/ ③ 资源定义 = 厂商 + 账号 + Key，账号必填前置）
> 设计：tech-design v1.4 §4.3/§4.7/§4.9、design-spec v0.6；用例：test-cases v1.4 **INT-50** + **E2E-20 追加⑧项**
> 网关：`http://127.0.0.1:8300/`（运行进程 23:24 启动，已加载 23:23 的 schemas.py / 23:08 的 resources.py，Q20 代码在位）；浏览器：ego-browser（Chromium，DOM 快照 + `Page.printToPDF` 截图取证，同 Q19 口径）
> 执行方：AI（Trae）；执行时间：2026-09-04（本地）

---

## 0. 结论

| 项 | 结果 | 证据 |
|---|---|---|
| 全量回归 pytest | **187 passed**（39.91s，UT 29 + INT 50 + 其它，含新增 INT-50） | §1 |
| INT 管理端扩展子集（INT-46/47/49/50） | **9 passed**（3.86s） | §1 |
| 静态资源禁缓存（Q19-① 延续） | `Cache-Control: no-cache` 实测命中（/ 、resources.js、models.js） | §2.1 |
| 资源表单形态（Q20-①/②/③） | 厂商名称自由输入（datalist 联想）/ 账号必填且位于 Key 前 / 映射就地新建只填统一模型名（无端点分组） | §2.2 |
| 系统模型页端点/分组微调（Q20-②） | 详情页端点下拉（chat\|images）+ 分组输入在位 | §2.3 |
| 账号必填客户端校验 | 账号留空点创建 → toast「账号必填（资源 = 厂商 + 账号 + Key）」，不提交 | §2.4 |
| 全链路 UI 创建 + 保存（Q20-①/②/③） | 自定义厂商名 + 账号 + 就地新建系统模型一次保存：真实 `res-cfadf1e8`、vendor/account 持久化、新模型默认 chat + 通用 | §2.5 |
| 生产配置还原 | 测试对象清理后与备份逐字节一致（resources=1 / models=7 原始形态），热重载生效 | §2.6 |

---

## 1. 全量回归（UT/INT）

```
$ .venv/bin/python -m pytest -q
187 passed, 208 warnings in 39.91s

$ .venv/bin/python -m pytest tests/integration/test_int_admin_ext.py -q
9 passed, 36 warnings in 3.86s
```

- 覆盖 test-cases v1.4 全部 UT（01~29）与 INT（01~50），含 Q20 新增 **INT-50**（`tests/integration/test_int_admin_ext.py::TestVendorCustomName`）：
  - `test_int_50_vendor_custom_wins_over_preset`：自定义厂商名压过预设展示名（事件 provider / stats by_provider = 「我的厂商」）；
  - `test_int_50_vendor_roundtrip_through_config`：PUT 保存 vendor 字段 round-trip 不丢失。
- test-cases.md §6 状态矩阵已同步（UT 29/29、INT 50/50 通过）。

## 2. E2E-20 追加核验（Q20 三项，第⑧项）

### 2.1 静态资源禁缓存延续（前置）

```
$ curl -sI http://127.0.0.1:8300/
HTTP/1.1 200 OK · Cache-Control: no-cache · Content-Type: text/html; charset=utf-8

$ curl -sI http://127.0.0.1:8300/js/pages/resources.js
HTTP/1.1 200 OK · Cache-Control: no-cache

$ curl -sI http://127.0.0.1:8300/js/pages/models.js
HTTP/1.1 200 OK · Cache-Control: no-cache
```

### 2.2 资源管理页与新增资源表单（DOM 实测）

**页面描述**：`资源 = 厂商 + 账号 + Key（调度与计费最小单元）；同一厂商可挂多组「账号 + Key」组合。新增资源时一并配置模型映射（厂商模型 → 系统统一模型）…`（Q20-③）

**表格列**：备注 | 厂商 | 账号 | 模式 | Base URL | Key | 模型映射 | 启用 | 操作（Q20-③ 账号成为独立必填列）

**新增资源弹窗字段（DOM 顺序即表单顺序，Q20-①/②/③）**：

```json
labels: ["厂商名称（自定义）","备注（显示用，可空）","接入模式","账号（必填 · 厂商下区分 Key）","Base URL","Key 值（明文，仅存本地 config.yaml）"]
inputs: [
  {name:"vendor",  list:"rm-presets", placeholder:"如：商汤 / 任意厂商名"},   // Q20-① 自由输入 + datalist 联想
  {name:"name",    placeholder:"如：商汤·主Key"},
  {name:"access_mode", select api|plan},                                     // 接入模式
  {name:"account", required:true, placeholder:"如：156账号 / 主账号"},        // Q20-③ 必填 · 位于 Key 前
  {name:"base_url", placeholder:"https://…"},
  {name:"api_key", placeholder:"sk-…"},
  // 映射区（Q20-② 就地新建只填统一模型名）：
  {placeholder:"厂商侧模型名，如 sensenova-6.8-flash-lite"},
  {select value:"__new__"},   // 目标：已有系统模型 / ＋ 新建系统模型…
  {placeholder:"系统统一模型名（端点/分组在「系统模型」页调整）"}              // Q20-② 无端点/分组输入
]
datalist#rm-presets: ["商汤按量 API","商汤 TokenPlan"]
```

- **无端点（chat/images）下拉、无分组（是否通用）输入**——已从资源弹窗映射区去除（Q20-②），仅剩统一模型名。
- 整页 PDF 存档 `docs/changes/e2e-records/q20-screenshots/resource-form-q20.pdf`（视觉证据）。

### 2.3 系统模型页端点/分组微调（DOM 实测，Q20-②）

选中模型详情首行：

```
端点 [chat 对话（流式 + 非流式）▼]   分组 [通用  ]   ← 可编辑控件
hint: 端点 / 分组是系统模型级属性，在此调整（映射新增在「资源管理」编辑资源）。
```

- 端点下拉选项 `chat 对话（流式 + 非流式）` / `images 图像生成`；分组为自由输入。
- 左侧分组列表（通用/编程/图像生成）与右详情 3:7 布局正常。

### 2.4 账号必填客户端校验（Q20-③）

- 表单填自定义厂商 `测试厂商` + Base URL + Key，**账号留空** → 点「创建」：
- toast = `账号必填（资源 = 厂商 + 账号 + Key）`；弹窗未关闭（不提交）；`GET /admin/api/config` 无变化（未污染配置）。

### 2.5 全链路创建 + 保存（Q20-①/②/③，真实 UI 操作）

1. 新增资源填写：厂商名称 `测试厂商`（自定义）/ 接入模式 `plan` / 账号 `156账号` / Base URL `https://example.com/v1` / Key `sk-test-key`；
2. 映射行：厂商模型 `vendor-model-x` → 就地新建系统模型 `test-uni-model`（无端点/分组输入，Q20-②）→ 点「创建」（toast「已新建系统模型『test-uni-model』（未保存）」）→ 页内「保存配置」（toast「配置已保存并生效」）。
3. **保存后 config 实测**（`GET /admin/api/config`）：

```json
resources: [
  {"id":"res-sensenova-main","vendor":"","preset":"sensenova-tokenplan","access_mode":"plan","account":"主账号", ...},
  {"id":"res-cfadf1e8","vendor":"测试厂商","preset":"","access_mode":"plan","account":"156账号",
   "base_url":"https://example.com/v1","enabled":true}          // 占位 @new-1 → 真实 id；vendor/account 持久化
]
models.test-uni-model: {"name":"test-uni-model","group":"通用","endpoint":"chat","enabled":true,
  "resources":[{"resource":"res-cfadf1e8","model":"vendor-model-x","reasoning":null}]}   // 默认 chat + 通用（Q20-②）
```

- 占位 `@new-1` → 真实 `res-cfadf1e8`（INT-49 链路复验）；新模型默认端点 chat / 分组 通用。

### 2.6 清理还原（生产配置零污染）

- 恢复备份 `data/config.yaml` → `POST /admin/api/config/reload` → `{"status":"ok","message":"配置已重载"}`；
- 复验：`resources: 1`、`models: [sensenova-6.8-flash-lite, deepseek-v4-flash, deepseek-v4-pro, glm-5.2, kimi-k3, sensenova-u1-fast, sensenova-u1.5-lite]`（原始 7 模型），与备份一致。

## 3. 变更清单（Q20）

| 文件 | 变更 |
|---|---|
| `model_gateway/config/schemas.py` | Resource 类注释更新（资源 = 厂商 + 账号 + Key，Q20-③；vendor 自定义 Q20-①）；`account`/`vendor` 字段语义落档 |
| `model_gateway/core/resources.py` | `vendor_label` 优先取自定义 `resources[].vendor`（压过预设展示名），事件 provider / stats by_provider 口径（Q20-①） |
| `model_gateway/web/static/js/pages/resources.js` | 厂商名称自由输入 + datalist 联想；账号必填且置 Key 前；映射区去端点/分组（就地新建只填统一模型名）；页描述/表格列更新；账号缺失校验 toast |
| `model_gateway/web/static/js/pages/models.js` | 详情页新增端点（chat\|images）与分组可编辑控件（Q20-② 系统模型级属性） |
| `tests/integration/test_int_admin_ext.py` | 新增 TestVendorCustomName（INT-50 两项：vendor 压过预设 + round-trip 持久化） |
| `docs/specs/prd.md` | v1.6 → **v1.7**（§9-Q20 三项修正归档） |
| `docs/specs/tech-design.md` | v1.3 → **v1.4**（Q20 同步：vendor 口径 / 端点分组归系统模型页 / 账号必填） |
| `docs/specs/test-cases.md` | v1.3 → **v1.4**（新增 INT-50、E2E-20⑧、覆盖矩阵与状态矩阵同步） |
| `docs/specs/design-spec.md` | v0.5 → **v0.6**（资源表单/表格列/系统模型页端点分组微调 + 推翻原因链） |

## 4. 遗留与说明

- headless 环境 `captureScreenshot` 超时（同 Q18/Q19 轮），视觉证据以 `Page.printToPDF` + DOM 快照替代；PDF 已存档 `docs/changes/e2e-records/q20-screenshots/resource-form-q20.pdf`。
- 视觉效果最终以用户浏览器实测为准（no-cache 已保证改版即时可见，需强制刷新一次旧缓存或正常刷新即可）。
- 账号必填目前为**前端表单校验 + 配置 round-trip 持久化**；服务端 schema 层 `account` 仍允许空串（向后兼容旧配置），界面层按 Q20-③ 强制。
