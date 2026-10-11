> 版本：**v2.11（2026-10-11 · §22 新增第 11 实例 `workbuddycn`（PRD Q44，用户拍板 D1–D5））**
> ① §22.0 产品数 10 实例/9 产品 → **11 实例/10 产品**；② §22.4 矩阵新增 `workbuddycn` 行（external_link 轮询 / 无设备 / 额度 ✓ / **签到 ✓**（与国际版相反）/ remote `/v3/config` + 中国版兜底表(16，剔除服务端别名 `auto`) / openai）；③ 登录 `platform` 口径 = **`cli`**（客户端声明的 `workbuddy` 是登录页深链 `workbuddy://` 的键、本机 WorkBuddy.app 已注册该协议 ⇒ 照抄会复刻国际版 `workbuddy-ai://` 报障；同 2026-10-10 国际版修法，CN 域名 `platform=cli` 握手 2026-10-11 实测 200）；④ 共享实现唯一改动 = `buddy/protocol.py::_ATTRIBUTION_BY_PRODUCT` 补 `"workbuddycn": ("WorkBuddy","5.5.2")` 一行（缺行 = 该账号首次推理请求在 `auth_headers` 构造身份头时当场 `ValueError`，非静默降级）；⑤ `hooks.py`/`out.py`/国际版模块零改动（参数化新增的证明）。方案与实测证据：`docs/changes/plans/20261011-workbuddycn-integration-plan.md`（v2 修订稿，含 v1 方案的 6 项问题修正）。🔴 含后端改动 ⇒ 须重启 :8300；端到端登录/签到/续期待真机（方案 §7-R1/R2/R5）。
> 上一版：**v2.10（2026-10-05 · §9-Q41 草稿制：`POST /admin/api/accounts/auto-map` 从此**不是写面**）**
> ① 载荷新增可选 `models: [目录条目 id…]` = 界面当前显示为「暂不设置」的行；分析范围 =
>   `models` ∩ `_map_enabled(...) is None`（两道闸门缺一不可：前者防"同一批行每次重烧额度"，
>   后者防"覆盖用户逐行配好的"）。🔴 `models` **缺省**与**空数组**两种意思：缺省 = 旧调用方回落"全部未落位"，
>   `[]` = 本轮什么都不分析（写成 `if not asked` 回落会让空数组退化成全部重跑）。
> ② 回执改为**建议形状**：`written` 恒 `false` + `suggested:[{model,target,engine}]` + `via`/`analyzed`/
>   `matched_model`/`matched_regex`/`unmatched`/`kept`/`reason`；**不再返回**写面那套字段
>   （`added`/`already`/`moved`/`product_models`/`reload`/`accounts_mapped`/`emptied_models`）——
>   递过去就是给界面第二套真相。`_apply_mapping_items` 的生产者由**三个**减为**两个**（保存的 `mappings`
>   与逐行 `product-models/remove`），"一个写面几个生产者就几条判据"这条纪律随之改计数。
> ③ 唯一写入口 = `saveAll` 那一次提交：脏行里有目标的走一次 `mappings`（新行缺省 `enabled=true`、
>   改挂 = 条目整条搬，两条契约随 Q37 原样保留），改回「暂不设置」而盘上有位的逐行走 `remove`；
>   任一条被拒 ⇒ **不关窗** + 就地列原话 + 那些行退回盘上真值。判据 INT-111/112 改写 + 静态门 V21~V29
>   + 回执门 A/B/C/D/E（22 条变异）+ 真机门行为段。证据 `E2E-20261005-map-draft-mode.md`。）
> 上一版：**v2.9

> 版本：**v2.9（2026-10-05 · Q39 承接资格闸门与风控分类归一，新增 §5.4 机制落点表：`QuotaPool.entitled`（`available()` 与 `reserve_quota()` 两条路都读、按 rid 共享）+ `entitled_from_snapshot()`（只有 `no_plan` 否认、"没查到"一律不动位，且 `remaining is None` 的早退不再顺手跳过资格位）+ `errors.RISK_CONTROL_TYPE` 落 RETRYABLE（401/403/404/408/429 不接管、FR-3.13 一字未放宽）+ `anthropic_out._shape_error`（2xx 非消息形状 = 可重试，不再产出"空正文 + success + C 被清零"）+ 修掉 `openai_compat.py` 那条调用不存在的 `_sse()` 的零内容兜底分支。🔴 含调度/额度/出站层改动 ⇒ 须重启 :8300；补丁落在隔离工作树分支 `fix/zcode-selection-gate`（未合并）。上一版 v2.8（2026-10-05 · Q38「AI智能匹配」常驻一颗 + 只补未配置的行）：`POST /admin/api/accounts/auto-map` 语义收紧为**填充式**——
> 待分析行 = `_map_enabled(...) is None` 的目录条目（与界面那颗开关读同一个三态位，判据不另写一份）；全部已配置 ⇒ **零出站、零写盘**，
> 直接 200 回 `written:false` + `kept`（不带 `reload`：没写盘就不谈运行态换代，说 true 是假陈述）；回执新增 `kept` / `written` 两键。
> 🔴 为什么把「防覆盖」放在写面而不是把入口藏起来：Q35-③ 红线（不许用「看不见」交付），且上一轮 V27/MS8 已证明「按一次盖掉手改的行 + 再烧一次额度」真会发生。
> 判据 INT-111/112 + 静态门 V22/V23/V27。含后端改动 ⇒ 与 Q37 一并等 :8300 重启。）
> 上一版 **v2.7（2026-10-05 · Q37「模型映射」行内即落库：新增 §4 写面契约一条「改挂 = 搬条目本体」+ §22.7 三个生产者的 `enabled` 缺省口径）：① 弹窗「保存」整族删除，行内一改即落库（`POST …/mappings` 逐行、`POST …/product-models/remove` 即时解除）；② 新映射缺省 `enabled=true`（识别/选定即进池），已有位的行改挂保持当前开关态；③ 🔴 `_write_mappings_phase3` 的组合唯一预检从"第一个持有位置"升级为"全部持有位置"（`_mapping_holders`）：本行原落点 ⇒ 条目**本体**搬运（推理默认跟着走，不删了重建），别处占用或别名形状 ⇒ 仍整条拒 + 零写盘；回执新增 `moved` / `emptied_models` 两项。证据 `docs/changes/e2e-records/E2E-20261005-map-instant-commit.md`。🔴 含后端改动 ⇒ 须重启 :8300 才在线上生效。
> 上一版 **v2.6（2026-10-04 · Qoder 加密端点的本机 wasm 签名腿落地：新增 §22.4-A —— 明文仍只有一份实现（本仓 `ask.py`）、加密与 COSY 签名交给客户端自带 wasm 跑在常驻 Node 子进程里、wasm 与第三方桥**不入库不下载不改形状**、两个环境变量 `MGW_QODER_WASM_GLUE`/`MGW_QODER_NODE_BIN` 的缺省形状＝与接线前逐字节一致；状态口径写死「签名腿已实现且离线可证，服务端是否接受仍未验 ⇒ 不得宣称 Qoder 转发已交付」。上一版 v2.5（2026-10-03 债务轮两条闭口：§4 增两条契约 —— ① 每条模型带只读派生位 `spec`（「网关承诺」的界面出口 = 债务 Q33-债14 后端腿，值取 `Runtime.model_specs` 同一个对象、与 `/v1/models` 声明与出站缺省注入同源，PUT 回传被 Pydantic 忽略不落脏键）；② `configure_logging()` 让 INFO 级诊断在出货形状下真的可见（债务 Q33-债13；🔴 契约里写死**不动 `propagate`** 的理由：caplog 靠向上传播、关掉会让现有判据静默饿死而不是变红）；§22.5-9 ① 的「界面文案位」由「仍未做」改述为「已实现、与并行会话同文件 ⇒ 只在盘上未进提交」。上一版 v2.4（2026-10-03 归档 Q34：§22.7 端点表补 `POST /admin/api/accounts/auto-map`，§4 配置写面新增「映射写入只有一个出口 `_apply_mapping_items`」契约（三个生产者共用：逐行开关 / 批量保存 / 初始化）；auto-map 的两档引擎判据 = 模型分析（`_pick_analyzer` 四条闸门：chat+启用 / `cfg.mapping_enabled` 开着 / 有适配器 / 两类接入凭据位置分家；低档位优先且字典序可复现；分批 ≤40 行 ≤5 次并按所选腿自身 `max_output` 收；严格 JSON + 名单外目标就地丢弃）⇒ 任何一步失败**整表**降级 `_enum_suggest`，回执 `via`/`reason`/`matched_model`/`matched_regex` 如实回报。🔴 这条腿会真实发出站请求（消耗所选资源/账号额度）：只在用户亲手点时调用，无自动腿、无定时（铁律 1）。）**已随本轮并入**

> 🔴 **术语读法（2026-10-04 定版）**：本文规范性正文已统一到 **厂商 = 模型生产公司 / 供应商 = 接入方（「接入模型资源」每个 Key 接入 + 「接入账号资源」每个产品账号）/ 网关模型 = 把各供应商的同一厂商模型标准化成一个名字并统一规格（旧称「系统模型」作废、同义）/ 资源 = 供应商名下一条可调用模型接入**。版本史与存证类内容**保留当时措辞、不改写**（`> vN（…）`、变更表 `| v… |`、`> N. v0.x「…」→ **推翻/调整**` 原因链、`## 5.1 实施校正记录`、Q## 归档条目原文、用户原话引号内），其中指接入方的「厂商」一律按**供应商**读、「系统模型」按**网关模型**读；定义源 `prd.md` §2，执行细则 `.cursor/rules/mg-terminology.mdc`。🔴 另注：`resources[].vendor` 这个字段名承载的是**供应商名称**（历史命名，不改字段以免打断实盘配置），内置目录的 `vendor` 字段承载的才是**厂商**（生产公司）——同名字段两种语义，判身份看它在哪一层。
> 上一版 v2.3（2026-10-03 归档 Q33-⑥ 两条契约扩展：`/v1/models` 新增只读位 `specStale`（§12.2 字段表）+ 新写面 `POST /admin/api/accounts/product-models/remove`（§4 写面清单）；🔴 两条的界面文案位仍未做 = 债务 Q33-债14，本轮不反向冒充已完成；上一版 v2.2（2026-10-02 归档 Q33：多号并行 + 两级开关 + 统一规格标准）**——**① §5.3a 号间轮转落地为「活跃组 + 排空换位」**（推翻 §5.3「不轮询/顺序恒走最高优先级」，x 的"最多 x 个资源并行"保留；含切换轮不参与轮转）；**② §22.5-7 两级开关判据同源**（产品位 `product_models` = 账号侧映射唯一真相，`AppConfig.mapping_enabled()` 一处判定，进池/对外声明/可检测清单/弹窗回显/告警横幅五处共用；号开关派生 `Resource.enabled`）；**③ §22.5-8 统一规格层**（`core/model_spec.py` 数值取大 / 布尔取并 / 无来源=None 不编数 + `accounts/catalog_cache.py` 产品目录落盘缓存，TTL 一天 + `stale` 显式字段，调度与声明侧**零网络**）；**④ §22.5-9 尚未接线清单**（按实际选中资源校验承载 / 陈旧缓存的界面标注 / 产品位删除路径 / 目录按号判权益）。
> 上一版 v2.1（2026-10-02 归档：zcode 额度「联网腿 + 全站刷新额度」实施结论——**① §17 额度数据源优先级改述**（联网腿 `billing.fetch_balance` ← `product.quota` = **额度唯一实时源**；客户端日志面降为**离线聚合面**；附【探针台账】与「仅 `GET /billing/balance`」范围声明，推翻原「客户端日志优先 → 联网兜底」）；**② §17 明写 10s 节流不适用额度腿**（额度腿节奏 = ops tick，实测有效轮周期 ≈292s 而非配置 60s）；**③ §17 增补 `circuit.enter()` 的两个调用点**（领取腿 + 额度腿，并登记 `out.py` 的"唯一调用点"话术已过期）；**④ 离线面如实登记**（两 call site / 一写入函数 + 「日志一旦出现，离线腿可能用旧值覆盖网络值」的**已知限制**）；**⑤ 熔断与额度腿的错护栏改述**（熔断现在**发起前**就拦额度腿，`reason=circuit` / 0 请求）；**⑥ §22.3 只加"新增字段带默认值"注记**（`QuotaSnapshot.remaining/reason/data_at/plan_key`；三态与「未知不当零」一字未改）；**⑦ §22.7 补两个刷新额度端点 + 三段计数口径**（刷新 N · 失败 K · 未发起 J，另加「未参与」与 J 分家）并订正过时的「四值口径 / 操作 ≤3 颗 icon」；**⑧ §22.11 的 D1 仍为待实测**，只追加「billing GET 已实测可直连（2026-10-02，仅 GET）」。
> 上一版 v2.0（2026-09-26 **增量设计**：Q25/Q26/Q27 调研落地，新增 §12–§21——**① 能力位下发**（`/v1/models` 补 8 字段，实测缺 `supportsToolCall` 会被工具静默删 `tools`）/ **② 参数归一化三步探测**（S2 生效验证必需——实测非法值也返 200 被忽略）/ **③ 配置三层**（用户层不新增）/ **④ 账号存储不建统一表**（Q27-⑤ 用户决策，仅 `Resource` 加 `product` 列）/ **⑤ 设备身份 per-product 独立**（三条硬约束）/ **⑥ 运营模块与核心调度解耦**（四类结果）/ **⑦ ZCode 上游接入架构落点** / **⑧ `anthropic_out` 从空壳到实现（P0）** / **⑨ 增量实施 M3–M5** / **⑩ 不做清单 19 条**（防过度设计）/ **⑪ 用户可见出口与文案**（交互契约汇总））。
> **2026-09-29 增补（对应 PRD v1.18 / Q28-⑧）**：§17 熔断补"**读不动 = fail closed**"一档的机制口径
> （未知不给钟点、不许诺自动恢复、`_save()` 失败必须留痕、两档呈现不得聚合、判坏的类型闸），
> 见 §17 表格下方的实现期背离注记。
> **三轮独立审核已通过**（产品经理 / 研发工程师 / 交互与视觉工程师）：共发现 **48 个问题**（含 8 条严重），**全部修正**；报告见 `docs/specs/reviews/`。
> 关键修正：`mgw` CLI **此前不存在**（原稿误称"复用已有"）→ 新增 M3-0；伪代码引用不存在的符号（`entry.thinking_format`、把 `effort_levels` 当 dict 解包）→ 按真实 `EnumPool.get()` 重写；M4-2 判据「主 `~/.zcode` 不被写」**不可达**（`setting.json` 是已知例外）→ 已改写；**零映射告警写日志用户看不见**（启动脚本自动关窗）→ 改为 `/admin/api/overview` 横幅。
> v1.6 于 2026-09-05 Q22 界面参考项目规范精修同步升版，对应 PRD v1.9 §9-Q22——**① 黑主色令牌**（active 态/主按钮/开关 on 统一近黑 `#171b22`，深色主题反转为白 `#e8eaee`，配套 `--on-brand` 文本令牌；推翻 v1.5 indigo 主色）；**② 参考规范组件层**（无边框软阴影卡片 + `#eef1f3` 软边框 + 分段式 tab + 参考色板徽章；tab 纯 CSS 重塑、类名契约不变）；**③ 分组侧栏 + 两行顶栏**（侧栏四分组 + 顶栏面包屑 `Console › 分组` + 页标题由路由 `PAGE_META` 注入，7 页 page-head 去重；指标卡加 38px 图标块）；**纯前端无后端变更**，§4.11）。v1.5 于 2026-09-04 Q21 界面视觉升级同步升版（对应 PRD v1.8 §9-Q21——**① 界面参考 aionui.com 简约清爽大气**（操作后台风格现代化，组件保留小圆角）；**② 三态主题：浅色 · 深色 · 跟随系统**（令牌化双主题 CSS 变量 + `html[data-theme]` + `localStorage.mg-theme` 持久化 + `matchMedia` 系统联动；顶栏主题按钮弹出菜单；侧栏随主题切换，推翻 Q19 固定深色侧栏；**纯前端无后端变更**，§4.9））。v1.4 于 2026-09-04 Q20 资源接入管理三项修正同步升版（对应 PRD v1.7 §9-Q20——**① 厂商名称自定义**（资源表单厂商名自由输入，datalist 联想快填；`resources[].vendor` 落库，`vendor_label` 优先取 vendor 压过预设，事件 provider / by_provider 口径同步，§4.3/§4.7，INT-50）；**② 映射区去除端点/分组**（资源弹窗「就地新建系统模型」只填统一名，默认 chat + 通用；端点/分组为系统模型级属性，移入系统模型页详情可编辑，§4.9）；**③ 资源定义 = 厂商 + 账号 + Key**（账号从可空备注升级为资源身份组成、表单置 Key 前必填，§4.7））。v1.3 于 2026-09-03 Q19 两项修正同步升版（对应 PRD v1.6 §9-Q19——**① 界面视觉重设计 + 静态资源禁缓存**（暗色侧边栏/SVG 图标/组件现代化；`_StaticNoCacheMiddleware` 给全部静态资源加 `Cache-Control: no-cache`，§4.9）；**② 资源导向模型映射**（映射创建移入资源弹窗、可就地新建系统模型；`@new-*` 占位资源 id 由 `PUT /admin/api/config` 保存时解析为真实 `res-<8hex>` 并同步改写 `models[].resources[].resource` 引用，§4.7，INT-49））。v1.2 于 2026-09-03 Q18 五项修正同步升版（对应 PRD v1.5 §9-Q18——**① 管理端免鉴权**（移除 allow_admin，`/admin/api/*` 直访，§4.1）；**② 扁平资源模型**（`resources[]` 一层：厂商+Key+可选账号备注，ID 自动生成 `res-xxxxxxxx`，模型映射条目改为 `resource`+`model` 引用，§4.3/§4.7）；**③ API 接入页**（端点清单+多密钥管理，§4.9）；**④ 全局调度参数**（x/y/m/超时不再按模型覆盖，`models[]` 移除覆盖字段，§5.2/§5.5）；**⑤ 界面信息架构重整**（资源表格化/模型映射纯业务/设置页去产品管理，§4.9/§10.3））。v1.1 于 2026-09-03 五项调整同步升版（对应 PRD v1.4 §9-Q17——新增 §4.10 系统运行控制与单实例锁；`GET /admin/api/presets` 厂商预设注册表；`models[].enabled` 模型启用开关；统计派生维度扩展）。v1.0 于 2026-09-03 终审通过 · §11 八项确认点全部落定：x=并发溢出生效集（Q13）/ m/y=y 先判定（Q14）/ 管理鉴权=复用访问令牌+allow_admin【**已被 Q18-① 推翻**】/ 单次尝试超时 **60s**（原 120s，终审调小）/ 请求总预算 **300s**（原 600s，终审调小）/ 延迟提交代价接受 / failed_precondition 透传+可配覆写 / 图像 URL 有效期提示三处——对应 PRD v1.3 §9-Q16）
> 对应需求：PRD v1.14（需求真相源）
> 日期：2026-09-26（v1.6 为 2026-09-05）
> 状态：**M1 已验收**（v0.1.0：141/141 pytest + 13/13 E2E（curl 可实测项），证据 `docs/changes/e2e-records/E2E-20260903-summary.md`；商汤端点定论 = 端点 A `token.sensenova.cn/v1`（E2E-01），§10.1 十项任务全部完成）；**M2 进行中**——Q17 五项调整（PRD v1.4）已实施（181/181 pytest + E2E 证据 `docs/changes/e2e-records/E2E-20260903-M2-five-adjustments.md`）；Q18 五项修正已实施（184/184 pytest，证据 `docs/changes/e2e-records/E2E-20260903-Q18-ui-overhaul.md`）；**Q19 两项修正已实施**（视觉重设计 + 资源导向映射，185/185 pytest + 浏览器 E2E + 真实调用 200，证据 `docs/changes/e2e-records/E2E-20260903-Q19-visual-remap.md`）；**Q20 资源接入管理三项修正已实施**（供应商名称自定义 / 映射去端点分组 / 资源=供应商+账号+Key，账号必填前置；187/187 pytest（含 INT-50）+ 服务端 JS 字节核验 + 浏览器实测网关模型页，证据 `docs/changes/e2e-records/E2E-20260904-Q20-resource-mgmt.md`）；**Q21 界面视觉升级已实施**（令牌化双主题 + 三态切换，187/187 pytest 回归持平 + headless Chrome CDP 实测三态/持久化/系统联动 + 双主题截图，证据 `docs/changes/e2e-records/E2E-20260904-Q21-theme.md`）；**Q22 界面参考项目规范精修已实施**（黑主色令牌 / 参考规范组件层 / 分组侧栏 + 两行顶栏 + 指标卡图标块，纯前端；187/187 pytest 回归持平 + headless Chrome CDP 七页双主题截图 11 张，证据 `docs/changes/e2e-records/E2E-20260905-Q22-refined-ui.md`）——任何「已实现/已跑通」的宣称必须附运行证据（铁律 2）

---

## 1. 总体架构

### 1.1 架构分层

单进程异步服务，五层结构（入站 → 核心 → 出站，配置/统计/日志横切）：

```
┌────────────────────────────────────────────────────────────────┐
│        客户端工具：Trae / Claude Code / Cherry Studio / curl     │
│        （本机 127.0.0.1 或局域网 IP；Bearer <访问令牌>）          │
└───────────────────────────┬────────────────────────────────────┘
                            │ HTTP / SSE
┌───────────────────────────▼────────────────────────────────────┐
│ 入站层  model_gateway/api/                                      │
│  ├ openai_compat：GET /v1/models · POST /v1/chat/completions    │
│  │                · POST /v1/images/generations                 │
│  ├ anthropic：    POST /v1/messages（含流式）                    │
│  ├ responses：    POST /v1/responses（Responses API 兼容面，含流式）│
│  ├ admin：        /admin/api/*（管理 CRUD，免鉴权直访，Q18-①）  │
│  ├ web：          / 静态管理界面（本地内置，无构建）              │
│  └ auth：         /v1/* 访问令牌校验（admin 免鉴权，Q18-①）      │
├────────────────────────────────────────────────────────────────┤
│ 核心层  model_gateway/core/                                     │
│  ├ ir：          内部标准请求/响应/流事件模型（协议中间表示）     │
│  ├ scheduler：   调度状态机（选路/重试 m/切换续跑/兜底）         │
│  ├ resources：   资源池/生效集/冷却/连续失败计数（懒过期恢复）    │
│  ├ errors：      错误分类器（PRD FR-3.13 表 + 商汤校准）         │
│  └ cancel：      取消注册表（客户端断连 → 取消上游）             │
├────────────────────────────────────────────────────────────────┤
│ 出站层  model_gateway/adapters/                                 │
│  ├ openai_out：   OpenAI 兼容出站（商汤按量/TokenPlan 均走此）    │
│  ├ anthropic_out：P0（v2.0 提级）· gemini_out：P2                │
├────────────────────────────────────────────────────────────────┤
│ 基础设施  config / enums / stats / logging                      │
│  ├ config：YAML 加载·pydantic 校验·热重载·原子写                │
│  ├ enums：统一模型名枚举池与自动匹配（规范化/别名/置信度）       │
│  ├ stats：事件 JSONL 流水 + 日聚合快照 + 查询聚合               │
│  └ logging：key 全程脱敏                                        │
└────────────────────────────────────────────────────────────────┘
                            │ httpx（异步，流式）
                    供应商上游（商汤等）
```

### 1.2 运行形态
- 单进程（`uvicorn` 单 worker）；管理 API、网关 API、Web 界面**同端口分路径**（默认 `0.0.0.0:8300`，可配）。
- 全 asyncio：每请求一个处理 task；上游请求独立 task，与客户端响应 task 解耦——这是**取消透传**与**切换续跑**可并存的基础。
- 无数据库、无外部消息队列；全部状态在内存 + 本地明文文件。

---

## 2. 技术栈选型

| 层 | 选型 | 理由 | 备注 |
|---|---|---|---|
| 语言 | Python 3.12+ | 用户指定首选；asyncio 生态成熟 | — |
| Web 框架 | FastAPI + uvicorn | 原生 async、SSE（StreamingResponse）、中间件、自动文档 | ASGI |
| 出站 HTTP | httpx（AsyncClient） | 流式读取、精细超时、task 级取消 | 连接池复用 |
| 配置/校验 | PyYAML（MIT）+ pydantic v2（BSD-3-Clause） | 明文 YAML 读写 + 严格 schema 校验 | 均宽松开源许可 |
| Web 界面 | 原生 ES Modules + 手写 CSS（简约风），图表用 **vendored 本地 Chart.js** | 无构建工具链；**禁止 CDN**（宪法级纯本地，前端资源随源码本地内置） | Chart.js MIT，随仓库内置 |
| 测试 | pytest + pytest-asyncio + httpx MockTransport / 本地假供应商 ASGI 服务 | 假供应商后端可编程注入错误序列，确定性验证调度 | 见 test-cases.md §1 |
| 日志 | 标准库 logging | key 脱敏包装 | — |

宪法级约束落实：无遥测、无远程配置、无自动更新；前端静态资源全部本地内置；唯一出站流量是用户配置的供应商 API 调用。

---

## 3. 请求生命周期（核心数据流）

以 `POST /v1/chat/completions`（流式）为例：

1. **鉴权**：auth 中间件校验访问令牌（`Authorization: Bearer` / `x-api-key` 按协议惯例）；无效 → 401。
2. **解析**：入站协议请求体 → IR 请求（消息/工具/参数；不认识的字段原样保留于 `vendor_params` 透传）。
3. **模型解析**：`model` 名 → 网关模型定义（枚举池或自定义）；不存在 → 404（标准 error 格式）；命中 enabled=false 的禁用模型（含别名）→ 同样 404，但 `code="model_disabled"`，不进入调度（§4.7 模型启用开关）。
4. **调度选路**：Scheduler 按 §5.3 选路规则——生效集（top-x 可用资源）内取**在途请求最少**者承接（平局取优先级高；低负载即集中打最高优先级，并发时溢出），获得该请求的执行计划（§5）。
5. **出站构造**：IR → 供应商协议请求（出站适配器按资源 protocol 选择）。
6. **上游调用**：httpx 流式请求；注册到 CancelRegistry（request_id → 上游 task）。
7. **流式转发（延迟提交）**：**收到首个内容事件前不向客户端发送任何字节（含响应头）**——此窗口内失败可无感重试/切换续跑；首个内容事件到达后才提交响应头 + 开始转发（§6）。
8. **失败处理**：每次尝试失败 → ErrorClassifier 分类 → 按 §5 统一规则处理（重试/切换/透传/兜底）。
9. **取消透传**：客户端断连 → 响应 task 被 cancel → CancelRegistry 取消对应上游 task；标记 `aborted`，**不计失败、不触发切换**（§4.6）。
10. **收尾**：请求结束（成功/失败/取消）→ 统计事件一行 JSONL 追加（含逐资源尝试明细、重试/切换次数、TTFT、token、usage 来源）。

非流式与图像生成：同链路，无第 7 步的流式细节（响应整体成功或失败，天然可重放）。

---

## 4. 核心模块设计

### 4.1 入站层（api/）

| 端点 | 方法 | 说明 |
|---|---|---|
| `/v1/models` | GET | 仅返回 enabled=true 的网关模型（OpenAI 格式；禁用模型及其枚举池别名不出现——模型启用开关见 §4.7 / PRD FR-2.3） |
| `/v1/chat/completions` | POST | 非流式/SSE 流式；tool calls 透传；供应商通道扩展参数（thinking/reasoning_effort 等）原样透传 |
| `/v1/images/generations` | POST | 图像生成（OpenAI images 格式）；调度/重试/切换/取消同样适用 |
| `/v1/messages` | POST | Anthropic 原生（含流式），供 Claude Code 直连 |
| `/v1/responses` | POST | OpenAI Responses API 兼容面（含流式 SSE），供 Codex CLI 等「只认 Responses」的客户端直连。**无状态转发**：`store`/`include`/`prompt_cache_key` 等提示类字段接受并忽略；`previous_response_id`/`conversation`/`background:true` **明确 400**（语义会变又做不到，禁止静默忽略）。工具：`function` 1:1、`namespace` 摊平成 `<ns>__<child>` 并在响应侧还原、`custom`/`tool_search`/内置工具**丢弃 + 日志 + `X-GW-Dropped-Tools` 响应头**（绝不因工具形状让整轮对话失败）。`GET /v1/responses/{id}` 一律 404（无状态，见 §4.12） |
| `/admin/api/*` | - | 管理 CRUD（资源/模型映射/密钥/设置/统计查询/日志查询/健康测试）+ **`/admin/api/overview` 总览一次取齐**（运行状态/资源健康/今日聚合/最近切换，见 §4.4）+ **`/admin/api/status` 轻量状态**（version/uptime/in_flight/资源快照含 `available` 口径；顶栏 5s 轮询专用——不读事件文件，与 overview 职责区分）——**全部免鉴权直访（Q18-①）** |
| `/admin/api/system/stop` | POST | 系统运行控制：**优雅停机**（免鉴权；返回受理确认——在途请求收尾后进程退出 + 释放单实例锁，见 §4.10） |
| `/admin/api/system/restart` | POST | 系统运行控制：**自重启**（免鉴权；返回受理确认——优雅停机 + 释放锁后 `os.execv` 进程映像替换：PID 不变、同端口重绑、配置重读、锁重新登记，见 §4.10） |
| `/admin/api/presets` | GET | 供应商预设注册表清单（免鉴权；资源表单数据源，见 §4.7） |
| `/admin/api/resources/test` | POST | 单资源 + 供应商模型名连通性测试（FR-9.1 最小版，2026-09-05）：最小请求 max_tokens=1，超时 min(30s, 尝试超时)，返回 ok/latency_ms/error |
| `/` | GET | 静态管理界面 |

- 鉴权（Q18-① 修订）：**仅 `/v1/*` 三协议端点要求访问令牌**（Bearer / x-api-key）；管理界面与 `/admin/api/*` **免鉴权直访**（无令牌门、无 localStorage 令牌）。**推翻原因链**：v1.0 终审曾定「admin 额外要求 `allow_admin: true`」——自用单用户场景下徒增摩擦（每次开界面先拿令牌），用户明确「自用的系统暂时不用考虑这个」→ allow_admin 字段与管理端校验整体移除。
- 错误响应：按入站协议各自标准 error 格式（OpenAI / Anthropic / images）。

### 4.2 IR（内部标准格式，core/ir.py）

- **请求**：`messages`（role + content parts：text / image(base64|url) / tool_use / tool_result）、`tools`、采样参数、`stream`、`vendor_params`（原样透传字典）。
- **响应（非流式）**：content（text / tool_calls）、`finish_reason`（映射：stop/length/tool_calls/content_filter）、`usage`、`raw`（原始响应保留）。
- **响应（流式）**：统一事件流——`text_delta` / `reasoning_delta` / `tool_call_delta` / `usage` / `finish` / `error`。
- **设计原则：透传优先**——IR 只做协议间**必需**的语义映射；同协议进出（OpenAI→OpenAI，首发主链路）时近乎零转换，未知字段不丢弃。协议差异在**出站适配器内归一化**：
  1. 商汤 DeepSeek V4 Pro 流式 `delta.thinking_content` vs 其他 `delta.reasoning_content` → 统一为 `reasoning_delta`；
  2. **kimi-k3 图片输入仅支持 base64（PRD FR-1.8 官方口径）**：出站适配器在发送 kimi-k3（及枚举池标记 `only_base64_image: true` 的模型）前，**自动把请求中的 image_url 公网 URL 下载为 bytes → 转 base64 嵌入**；下载异常按 RETRYABLE 分类（单次下载超时/失败计入当前尝试失败，参与正常重试/切换），但不做跨资源（换资源对 URL 下载问题无帮助）。
- **请求 model 解析（所有入站端点统一）**：按「精确命中网关模型名 → 枚举池别名（含 Anthropic/Gemini/厂商原生 model id）→ 规范化匹配（忽略前缀/日期后缀/大小写）」逐级尝试；仍无 → 404。命中 **enabled=false** 的网关模型（含别名命中）→ 同样 404，但 error code 为 `model_disabled`（三端点一致，不进入选路、不触达上游，§4.7 模型启用开关）。由此 Claude Code 等直连工具填 Anthropic 原生 model id 可自动映射到统一网关模型（PRD FR-5.2 兼容）。
- **端点类型校验**：入站端点根据端点类型严格校验网关模型的 `endpoint` 字段——chat 端点（chat/completions / messages）**只接受 endpoint=chat** 的网关模型；images 端点（images/generations）**只接受 endpoint=images** 的网关模型。model 名合法但 endpoint 不匹配 → 400 标准 error（含「模型 XXX 为图像生成模型，请通过 /v1/images/generations 调用」之类明确说明），不触达上游。
- **推理参数（三级合并，PRD Q15/FR-3.16）**：IR 请求显式携带 `reasoning: {enabled: bool | None, effort: str | None}`——仅当请求方**明确指定**时非 None（**「未指定」≠「显式关闭」**，两者必须区分）。出站构造时按**当前尝试资源**合并：`请求级显式值 > 资源级 reasoning 默认 > 不注入（走该供应商通道的默认）`：
  1. 入站解析时把请求体中的 `reasoning_effort` / `thinking` 从透传字典**提升**为 IR 显式字段（防出站双重注入）；
  2. **合并发生在每次出站构造**（每次尝试/切换目标资源独立合并）——切换续跑换资源后自动按新资源默认重算，非流式/流式天然一致；
  3. 资源未配置且请求未指定 → 出站请求体不含任何推理字段（走该供应商通道的默认行为）；
  4. images 类资源不适用推理参数（配置校验警告并忽略）。

### 4.3 调度核心（core/scheduler.py + resources.py + errors.py）

**ResourceManager（全局资源注册表 + 每网关模型有序池；Q18-② 扁平模型）**
- **全局注册表**：`resources[]` 一层扁平（资源 = 供应商 + Key），每条含 `id`（系统自动生成 `res-xxxxxxxx`，全局唯一）/ `name` / `preset` / `access_mode` / `protocol` / `base_url` / `api_key` / `account`（可选账号备注）/ `enabled`。资源状态对象按**资源 ID** 索引；同一资源被多个网关模型引用时状态**全局唯一**——PRD Q11「失败判定按厂商资源维度计数」的准确落地：在模型 M1 的池中该资源连续失败达 y 冷却后，模型 M2 的池中它**同步不可用**（同一次计数、同一次冷却）。配置删除某资源的全部引用时，清理其无主状态。
- 每个网关模型仅持有**有序映射条目列表**（`{resource: <资源ID>, model: <供应商模型名>, reasoning?: {...}}`，优先级 = 列表顺序），不复制状态。
- **出站适配器按资源 ID 动态管理**：每资源一个 adapter 实例（httpx AsyncClient 池化）；`base_url` 变更（热重载/界面保存）时按 diff 重建受影响资源的 adapter，未变资源连接池保持复用。
- **供应商口径（provider label，Q18-②）**：统计与事件行的 `provider` 字段按资源解析——预设资源取预设展示名（如「商汤按量 API」）、无预设（custom）资源取资源名称备注；`account` 字段直接取资源 `account` 备注（未标注为 null）。
- 资源状态：`active`（可用）/ `cooldown`（冷却至 T）/ `disabled`（手动/401 停用）/ `invalid`（404 模型无效）。
- 每资源维护：连续失败计数 `C`（跨请求累计，含请求内重试；**成功即清零**）、冷却截止时间、状态、最近错误。
- 冷却恢复：**懒过期**——每次选路时检查 `cooldown_until < now` 则恢复 `active`（按原优先级归位），无需后台定时器。
- 状态变更（计数/冷却/停用）以 `asyncio.Lock` 串行化（单进程内足够）。

**ErrorClassifier（PRD FR-3.13 的代码化）**

| 类别 | 判定 | 处理（详见 §5 规则） |
|---|---|---|
| `RETRYABLE`（网络/超时/5xx，商汤 500 `internal_server_error`） | 连接异常、读超时、HTTP 5xx | 重试 ≤ m → 切换续跑；计入 C |
| `QUOTA`（429/配额，商汤 `quota_exceeded_error`） | HTTP 429 或错误体配额语义 | 短指数退避重试（默认 2 次）→ 移出冷却 + 切换续跑 |
| `AUTH`（401/403 凭据类） | HTTP 401；403 且错误体属凭据/权限类 | 立即停用 + 告警事件 + 切换续跑（不重试、不计 C） |
| `NOT_FOUND`（404，商汤 `not_found_error`） | HTTP 404 | 标记 invalid + 告警 + 切换续跑（不重试） |
| `BAD_REQUEST`（4xx 参数类，商汤 400 `invalid_request_error` / `failed_precondition_error`；商汤 403 `permission_denied_error` 语言类） | 其余 4xx | **原样透传调用方**（换资源同样失败，不重试不切换） |
| `RESOURCE_UNAVAILABLE`（**资源级不可承接**：上游明确否认**这条资源**对本模型有资格 —— 未订阅 / 地域封锁） | 产品层归一成的 `error_type = errors.RESOURCE_UNAVAILABLE_TYPE`（当前取证：cline 403 的 `ENTITLEMENT_ERROR` 与地域特征词） | 立即换号 + 冷却该条 `(资源, 模型)`；**不 disable 账号**（其别的模型照常可用）、**不计 C**（非健康度信号）、冷却走 `cooldown_seconds_for`（自动恢复，不用终态 `invalid`）。**取证**：`docs/changes/e2e-records/E2E-20261008-cline-403-resource-unavailable.md`（修前 cline 尝试 5/5 全失败） |
| `CANCELED`（408 / 客户端中断，商汤 `canceled_error`） | HTTP 408 或客户端断连 | aborted 语义，不计失败不切换 |

- 分类输入：HTTP 状态 + 供应商错误体（`type` 字段等）；商汤 type 已按官方文档校准入表（PRD FR-1.8）。
- 规则表**配置可扩展 + 可覆写**：`config.yaml: error_rules` 支持对特定 `(http_status, error_type)` 覆写默认分类（优先级：type 精确匹配 > HTTP 通用映射）。**典型用例**：把商汤 `failed_precondition_error`（默认 BAD_REQUEST 透传）中「引擎不可用」子类覆写为 RETRYABLE 走切换续跑（PRD FR-1.8 官方口径「默认透传，引擎不可用类可配为切换」）。M1 仅配置层支持；M2 提供界面编辑。
- `finish_reason: content_filter` 在流/响应层处理为正常结束（不算失败）。

### 4.4 出站适配层（adapters/）与 Admin 运行状态端点

- `openai_out`（首发）：chat completions + images generations；流式 SSE 解析（含商汤思考字段差异归一化、usage 读取 `stream_options.include_usage`）；多轮工具调用回传完整性由透传原则保证（IR 不删字段）。
- **推理参数出站映射（PRD Q15/FR-3.16，三级合并结果 → 供应商参数名）**：合并后的归一化值由适配器按模型映射——商汤 V4 Pro：`reasoning.enabled` → `thinking.type`（`enabled`/`disabled`，仅支持思考开关的模型）；`reasoning.effort` → `reasoning_effort` **原样透传**（opaque 字符串，取值以该供应商通道实际接受为准——商汤 V4 系 `low/high/max`，PRD FR-1.8 官方口径；网关不强校验枚举，供应商侧校验失败按 BAD_REQUEST 透传）。Anthropic / Gemini 出站适配器的推理参数映射在各自适配器阶段（P1/P2）按官方文档校准，不在本文档预先断言参数名。
- **U1 Fast / U1.5 Lite URL 有效期提示**（PRD FR-1.8 P0 要求「网关透传时在文档/界面提示该差异」；终审确认点 8：**三处齐上**）：图像生成响应中 `response_format=url` 时，① 在响应 JSON 附加扩展字段 `_gw_note.url_valid_hours`（U1.5 Lite=24，U1 Fast=1）；② **在响应头附加 `X-GW-URL-Valid-Hours: <hours>`**（curl/程序化调用方看头即知，零风险不污染响应体）；③ 枚举池条目 `response_format_url_hours` 字段按模型记录，M2 模型映射详情页展示提示说明。INT-38 验证。
- `anthropic_out`（**v2.0 提为 P0**，见 §18）/ `gemini_out`（P2）：按资源 `protocol` 字段选择。
- 适配器接口：`async def call(resource, ir_request) -> IRResponse | AsyncIterator[IREvent]`（非流式/流式两形态）+ `async def list_models(resource)`。
  > ⚠️ **口径修正（v2.0 审核发现）**：上面写的是**目标形态，未落地**。真实约定是 **duck typing 的 4 个方法**
  > （`chat_nonstream` / `chat_stream` / `images_generate` / `aclose`，见 `scheduler.py:465-468`、`openai_out.py:100/122/164/57`）。
  > 新增适配器请按真实约定实现 —— 详见 §18.2 ①。

**`GET /admin/api/overview`（总览一次取齐：运行状态 + 资源健康 + 今日聚合 + 最近切换 + 调用地址；FR-7.1 Dashboard 总览、请求日志页「切换事件」tab 与排查的数据源；M1 已实现）**：
- 返回字段：`{ version, uptime_ms, in_flight_requests, today（今日调用聚合，含 today_switch_count 今日切换次数指标）, today_by_hour（24h 分桶趋势）, resources: [{resource_id, system_models[], status, C, cooldown_remaining_ms, last_error}], recent_switch_events: [ {ts, system_model, from_resource, to_resource, reason, cls} ](内存环形缓冲容量 200，端点返回最近 20 条), call_addresses（本机/局域网调用地址） }`。
- `recent_switch_events` 由调度器在每次「bench(R) → 切下一资源」时写入内存环形缓冲；**同时写入独立事件行** `data/usage/switch-events-YYYYMMDD.jsonl`（与每请求事件行分开存放，按天分文件、7 天保留），供看板/日志页与排查直接读取。这是 PRD FR-3.14「切换与重试事件记录」的精确落地。
- **Q17-1 口径**：总览页**不常驻渲染事件明细**——今日切换以指标数字呈现（D5），明细移至请求日志页「切换事件」tab 按需查看；`recent_switch_events` 字段保留供请求日志页与排查复用（PRD FR-7.1）。

### 4.5 流式处理与「延迟提交」（§6 详述）

- 上游 httpx stream → 逐 SSE 事件解析 → IR 事件 → 入站协议再编码转发。
- **响应头延迟提交**：首个内容事件到达前不发送响应头——失败窗口内可整体重试/切换（客户端零感知）；全失败则返回标准 HTTP 错误（对工具兼容性最好）。
- **流式端点的实现纪律（避免 HTTP 语义违规）**：窗口内（首内容事件前）全部尝试+切换+退避若**耗尽失败**，路由 handler 直接 `return JSONResponse(status_code=<对应码>, body=<标准 error 格式>)`（**503 / 429 / 401 / 404 / 400**，按兜底原因取码），**不构造 StreamingResponse**。只有当首内容事件确定到达、能正向输出时，才构造 `StreamingResponse(status=200)` 并开始 yield SSE 数据。由此**绝对避免「先发 200 header 再发 error 内容」**的 HTTP 违规形态（会让工具端把错误当正常响应）。
- TTFT = 首个内容事件到达时刻 - 请求进入时刻。

### 4.6 取消管理（core/cancel.py）

- `CancelRegistry`：`request_id → 上游 task`；请求结束注销。
- 客户端断连：uvicorn cancel 响应 task → generator 内捕获 `CancelledError`/`asyncio.CancelledError` → **先取消上游 task 再退出**。
- **延迟提交窗口内的断连（首帧未发出、重试/退避/切换进行中）**：非流式 endpoint 在响应未开始时，ASGI **不会**因断连自动 cancel handler task——须在**每次尝试边界主动探测**（`await request.is_disconnected()`，Starlette 基于 receive channel 轮询，开销极小）；探测到断连 → 取消当前上游 → **中止整个尝试链**（不再重试/切换/退避）→ 标记 `aborted`（不计失败、不触发冷却）。退避 sleep 期间以 `asyncio.wait(..., timeout)` 分段，保证可被取消及时打断。
- **关键纪律**：取消路径的 `CancelledError` 必须 re-raise，严禁被通用 `except Exception` 吞掉转成「失败」（否则误计 C、误触发切换）——单测强制覆盖（test-cases UT/INT）。
- SSE 心跳：上游静默超过 `heartbeat_seconds`（默认 15s，可配）发送 `: keep-alive\n\n` 注释帧，尽早暴露死连接。
- 供应商侧返回 408 `canceled_error`（如商汤）：aborted 语义（不计失败、不触发切换），错误**透传调用方**。

### 4.7 配置中心（config/）

- 启动：读 `data/config.yaml` + `data/model-enums.yaml` → pydantic 校验 → 内存快照。
- **热重载**（双触发）：① mtime 轮询后台 task（1s）；② 管理界面保存。两者都：校验通过 → **原子替换**（tempfile + `os.replace` 同目录）→ 重建快照 → 发布 reload 事件；校验失败 → 拒绝并保留旧快照（返回明确错误）。
- **在途请求不受重载影响**：请求开始时绑定配置快照引用，完整执行后结束。
- 校验规则（嵌套层级完整；Q18-② 扁平化后口径）：① **资源引用完整性**：`models[].resources[].resource` 必须存在于 `resources[]`（按资源 ID）；资源 `preset` 若非空必须存在于预设注册表；② 资源 → vendor_model 必须存在于配置或枚举池；③ 数值边界：`x≥1、y≥1、m≥0、冷却≥0、退避≥0、超时≥1、总预算≥超时`；④ 网关模型 endpoint 字段必须为 `chat | images`；⑤ 端口范围合法；⑥ **资源级推理默认 `reasoning`（Q15）**：`enabled: bool`、`effort: 非空字符串`（均可选；effort 值不做枚举强校验，opaque 透传），配置于 endpoint=images 的资源 → **校验警告并忽略**（不阻塞加载）；⑦ **模型启用开关（Q17/D1）**：`models[].enabled` 必须为 bool（非 bool 值拒绝并指明位置；缺省视为 true，UT-25）；⑧ **Q18-④**：`models[]` **不再接受** `max_active` / `fail_threshold` / `retry_per_request` 覆盖字段（未知字段按 pydantic 默认忽略或告警，文档明确不支持）；⑨ **ID 唯一性（Q18-②）**：`resources[].id` 全局唯一（自动生成保证；手填冲突 → 校验错误指明位置）。错误信息**逐条指明位置**（如 `resources[2].api_key`、`models[0].resources[1].resource`）。
- **模型启用开关 `models[].enabled`（Q17/D1，PRD FR-2.3）**：bool，**默认 true**——现有 config.yaml 无该字段时视为启用（向后兼容）。置 false 时：① `GET /v1/models` 不返回该网关模型，其枚举池**别名同样不出现**；② 对禁用模型（含别名命中）的请求在 `/v1/chat/completions`、`/v1/images/generations`、`/v1/messages` **三端点一致拒绝**——HTTP 404 + 各协议标准 error 格式，`code="model_disabled"`，message「模型已禁用，可在管理界面开启」；**不触达上游、不计资源失败**（不参与重试/切换/冷却判定，模型解析阶段即拒绝，§4.2）；③ 管理界面保存或 config.yaml 热重载后**对新请求即时生效、在途请求不受影响**（请求绑定配置快照的既有语义）。UT-24/25、INT-39~41、E2E-16 验证。
- **资源启停开关 `resources[].enabled`（Q18-② 扁平化后口径；原 v1.1「产品接入开关 providers[].enabled」随实例层级一并移除）**：bool，默认 true。置 false 时该资源**退出调度**——`resources.py rebuild` 以 `enabled` 聚合为资源可用口径（`available()` 通道，复用 §5.3 选路过滤），模型若无其他可用资源 → 503 `NO_RESOURCE`（与模型级禁用的 404 `model_disabled` 语义区分：模型级=模型本身关闭，资源级=供给侧退出）。资源快照（`/admin/api/status`、`overview`）含 `available` 综合布尔，资源列表行内直接呈现启停开关。
- **供应商预设注册表（Q17，PRD FR-1.2）**：`model_gateway/config/presets.py` 以**模块级常量清单**内置预设数据（数据驱动，非硬编码 UI 分支），每条字段：`id` / `name`（名称）/ `mode`（接入模式 `api|plan`）/ `protocol`（协议）/ `base_url` / `billing`（计费口径）/ `notes`（说明文案）。首发内置三条：

  | id | mode | protocol | base_url | billing |
  |---|---|---|---|---|
  | `sensenova-api`（商汤按量 API） | api | openai 兼容 | `https://api.sensenova.cn/compatible-mode/v2` | 按量付费 |
  | `sensenova-tokenplan`（商汤 TokenPlan） | plan | openai 兼容 | `https://token.sensenova.cn/v1` | 积分制 |
  | `custom`（空白自定义模板） | — | — | （空） | — |

  `GET /admin/api/presets`（免鉴权，Q18-①）返回该清单，供资源表单预设下拉渲染（M2 资源管理页）。**扩展原则：新增供应商或 Plan 类型 = 仅加一条预设数据**（必要时新增协议适配器），资源表单与 UI 框架零改动；`billing` 为可扩展枚举，未知口径前端优雅降级显示「—」。UT-26、INT-46 验证。
- **配置写入的 ID 自动生成与脱敏还原（Q18-② + Q19-② 占位解析）**：`PUT /admin/api/config` 保存时——① 新增资源 `id` 为空 → 服务端生成 `res-<8hex>`；② 新增访问密钥 `id` / `value` 为空 → 服务端生成 `tok-<8hex>` / `mg-<32hex>`；③ `GET /admin/api/config` 返回的 Key 为脱敏形态（`sk-****tail`），保存回传时服务端识别脱敏形态并**还原为已存明文**（未变更不损坏；变更明文则覆盖）；④ **占位资源 id 解析（Q19-②）**：资源弹窗内即配映射时，新资源（尚未落库、无真实 id）以 `@new-*` 占位 id 被 `models[].resources[].resource` 引用 → 保存时服务端统一生成真实 `res-<8hex>` 并**同步改写全部映射条目的引用**（一次 PUT 完成资源 + 映射落库，热重载即刻生效）。INT-48/49 验证。
- **映射条目位与产品位的界面出口 = 一个只读派生位（2026-10-02 待办②闭口；✅ 2026-10-03 提交 `a83e90b` 落库，:8300 已含该位 —— 实盘 `GET /admin/api/config` 的 17 条映射条目 17/17 带 `mapping_enabled`、缺字段 0）**：`GET /admin/api/config` 在 `models[].resources[]` 每条条目上**额外带** `mapping_enabled`，值 = `AppConfig.mapping_enabled(resource, entry, system_model)`（Key 接入侧看条目位；账号侧看 `(产品, 供应商模型名)` 产品位，位缺失才回落条目位聚合）——与调度选路、`servable_models`（`/v1/models` 与 `mgw setup`）、映射弹窗的 `map_enabled`、`…/check-models` **同一条判据**，界面不再自己判「进不进池」。该键是**只读视图**：`PUT` 回传时被 Pydantic 忽略（`ModelResource` 无此字段），不落配置文件；含后端改动 ⇒ **管理端要重启才生效**。判据 = `tests/integration/test_admin_config_pool_predicate.py`（6 例，含位与条目位相反的两个形状与「位指别的网关模型」那一支）。
- 🔴 **改挂 = 搬条目本体，不是"删了重建"，也不是整条拒（2026-10-05 Q37 · v2.7）**：`POST /admin/api/accounts/mappings` 的组合唯一预检从「取第一个持有位置」（`_mapping_holder`）升级为「取**全部**持有位置」（`_mapping_holders`）后再判：
  **本行原来的落点** = 产品位 `system_model` 所指；无位（旧配置零迁移）才取那唯一一个持有该 `(资源 × 供应商模型名)` 的网关模型。命中它 ⇒ 把 `ModelResource` **本体**从旧 `SystemModel.resources[]` 摘出、挂进目标模型，`enabled` 随本次请求，**同一次 `save_config` 原子写盘**；回执新增 `moved`（搬了几条）与 `emptied_models`（旧模型被搬空 ⇒ 会掉出 `/v1/models`）。
  🔴 为什么必须搬本体而不是重建：条目级推理默认 `reasoning` 就住在这条上（第八轮 B-1' 定它 = 条目级事实），删了重建会把它静默清空 —— 那是"改个名字丢了参数"的两套真相。
  🔴 不变量没放宽：**原落点不唯一**（跨模型别名形状且无位）或**别处还挂着**（位指 A 而有条目在 B）⇒ 整条拒 + 位不写、目标模型不建、旧挂载逐字原样，`skipped` 逐条带原话。旧契约"改挂必拒"（要用户先跳过保存一次、再选新目标保存一次）随本轮作废。
  判据 = INT-108（搬本体 + `emptied_models` + 声明换向）/ INT-109（原落点不唯一仍拒 + 零写盘）/ INT-110（停用号那条一起搬、重新启用不翻倍，取代旧 INT-81 的"整条 blocked"结论）+ 四条撤证（`movable=None` / 删了重建 / 清空 `reasoning` / 退回只看第一个持有位置）。含后端改动 ⇒ **管理端要重启才生效**。
- **网关承诺的界面出口 = 每条模型带只读派生位 `spec`（2026-10-03 债务 Q33-债14 后端腿；✅ 提交 `93d970e`）**：`GET /admin/api/config` 的每条 `models[]` 上带 `{max_input, max_output, stale, sources}`，值直接取 `Runtime.model_specs` 里**同一个对象** —— 与 `/v1/models` 对外声明、出站缺省注入、承载校验读的是同一份，界面**不再自己算一遍**。为什么必须存在：「网关模型管理」页有两类数字（官网取证的模型属性 vs 合并后的网关承诺），来源不同、答案也不同；用户问"工具看到的窗口为什么是这个数"时只有后者是正确答案，而它此前**没有任何只读出口**（前端要么不显示、要么自己重算 = 第二套真相）。`stale` 就是 `specStale` 的人读形态（陈旧仍是**可用的兜底来源**，数值照旧声明，不是"不知道"）。`spec` 整体是只读视图：原样 PUT 回传被 Pydantic 忽略、不落配置文件（判据 INT-100 第三条）。
- **诊断必须能在出货形状下被看见（2026-10-03 债务 Q33-债13；✅ 提交 `94f18be`）**：`main.py::configure_logging()` 在 `create_app()` 第一句给 `model_gateway` logger 装上它自己的 handler，级别走 `MGW_LOG_LEVEL`（默认 `INFO`）。根因是链路不是级别：`uvicorn.run(log_level=...)` 的 dictConfig **只配 `uvicorn*`、不碰 root**，而 `model_gateway` 不设级别也不挂 handler ⇒ 记录上传给 `WARNING + handlers=[]` 的 root、最终落到 `lastResort`（按 WARNING 起放）⇒ **所有 `logger.info` 诊断一条都不落日志**（真机对照 `grep -c "[选路" = 0 vs 2`）。§12「消灭无报错的失败」依赖这些诊断；"切换轮里为什么避开了那个号"这类问题在旧形状下**只能靠复现**。🔴 刻意**不动 `propagate`**：caplog 的 handler 挂在 root 上、靠的就是向上传播，"关掉以免双份打印"会让现有若干条判据**静默饿死**（全绿而不是变红，比红更危险）；生产里 root 本来没有 handler ⇒ 不会双份。
- **映射写入只有一个出口（2026-10-03 Q34）**：`api/admin_accounts.py::_apply_mapping_items(request, product, meta, parsed)` —— 「先拒后动 / `(资源, 供应商模型名)` 组合全配置唯一 / 条目只落启用号 / 产品位是真相 / 回执字段集合」这五条判据**只有一份实现**，三个生产者（弹窗逐行开关 `togglePool`、批量「保存」`saveAll`、首次「初始化映射」`initMap`→`auto-map`）都从这里出去。🔴 为什么必须是抽取而不是各写一段：写路径一旦有第二份，就会出现「初始化能写进去的形状、保存写不进去」或「初始化报成功而保存报跳过」这类两套真相（= Q33-① 那一课）。判据 = pytest `A-7`（`auto-map` 回执字段集合 **⊇** `mappings` 那份，少一个字段即红）+ 回执门 **C 系列**（第三个生产者的`skipped` 两种成因 / `reload:false` / 不关窗 / 不吞原因，与 B 系列逐条对称）。
- **产品位的删除写面（2026-10-03 契约扩展第二条，债务 Q33-债8 第②条）**：`POST /admin/api/accounts/product-models/remove`，载荷 `{product, model}` ⇒ 在**同一次原子保存**里删掉 `(产品, 供应商模型名)` 那颗位 **和** 由它派生的全部账号条目（作用域 = 该产品派生资源 × 这个供应商模型名，Key 接入侧同名模型不受影响）。口径三条：① 位与条目必须一起删 —— 只删位会让条目"失去主人"后按「无位 = 回落条目位」照旧进池，只删条目则号一启用就被 `sync_product_models` 按还开着的位补回来，两种都是"删了但没删"；② **幂等 = 200**（回执 `bit_removed` / `entries_removed` 如实说本来有没有、删了几条，不许把"本来就没有"报成"已删除"）；③ 删除**不要求**该产品有启用账号（写入面要求是因为条目要有落点，删除不需要落点，否则停用态产品被锁死）。回执另带 `emptied_models`（因此一条映射都不剩、将掉出 `/v1/models` 的网关模型名）与 `reload` / `reload_errors`。判据 INT-94（6 条），撤证 MD-2/MD-3/MD-4。
- 纳入配置 schema 的运行参数（PRD §6 示意的精确化）：
  | 参数 | 默认 | 说明 |
  |---|---|---|
  | `max_concurrent_requests` | 0（不限） | FR-4.2 网关整体并发上限；超限返回 429 + Retry-After |
  | `attempt_timeout_seconds` | **60**（终审由 120 调小） | 单次上游尝试整体超时（connect + read + write），承接 PRD §6 `request_timeout_seconds` |
  | `request_total_budget_seconds` | **300**（终审由 600 调小） | 单请求全部尝试+重试+退避的总时长上限（§5.5） |
  | `heartbeat_seconds` | 15 | SSE 心跳注释帧间隔 |
  | `retry_backoff_seconds` | 0 | RETRYABLE 类同资源重试间隔（0=立即） |
  | `quota_retry` | 2 | QUOTA(429) 短指数退避重试次数（官方建议口径） |
  | `quota_backoff_base_seconds` | 1 | QUOTA 退避基数（第 n 次 = base×2^(n-1)） |
  | `cooldown_seconds` | 60 | api 模式默认冷却时长 |
  | `cooldown_seconds_plan` | 18000 | plan 模式默认冷却时长（对齐商汤滚动 5h 窗口） |
  | `retention_days` | 7 | 事件流水+切换事件+运行日志保留天数 |
  | `error_rules[]` | [] | 覆写默认分类的规则列表（§4.3） |
- **P1 字段预留（M1 允许保留、不强制校验语义）**：PRD FR-10.3 令牌配额 `access_tokens[].quotas.{daily_requests,daily_tokens,total_tokens}`、FR-8.4 导入导出字段。M1 配置 loader 读到这些字段时保留原值、不透传、不校验上限；M3 启用时补语义。
- 环境变量引用 `${VAR}`（P1）。

### 4.8 统计与日志（stats/）

- **事件流水**：每请求一行 JSONL（`data/usage/events-YYYYMMDD.jsonl`，**按天分文件**——较 PRD §6 示意的按月分文件调整：7 天保留清理 = 删除整天文件，简单且原子；PRD §6 标注「示意，最终以架构文档为准」）；**写入经单写队列串行化**（asyncio.Queue + 单写 task），防并发请求交错断行：
```json
{
  "request_id": "...", "ts": "...", "client_token_id": "tok-xxxxxxxx",
  "system_model": "deepseek-v4-flash", "endpoint": "chat", "stream": true,
  "status": "success | failed | aborted",
  "resource_attempts": [
    {"resource": "资源A/vm-A", "attempts": 2,
     "errors": ["500", "500"], "switched": true}
  ],
  "final_resource": "资源A/vm-A", "provider": "商汤按量 API", "account": "主账号",
  "retry_count": 2, "switch_count": 1,
  "duration_ms": 1234, "ttft_ms": 210,
  "input_tokens": 100, "output_tokens": 500,
  "usage_source": "vendor | estimated",
  "images_count": null, "error_summary": null
}
```
- **事件行冗余 `provider` / `account` 字段（Q17，PRD FR-6.1 派生维度；Q18-② 扁平化后口径）**：写入时由配置快照按**承接资源**（资源 ID）解析——`provider` = 预设资源取预设展示名（如「商汤按量 API」）、无预设取资源名称备注；`account` = 资源账号备注字段（未标注为 null；无承接资源或解析失败同样为 null）；**历史行无该字段时聚合按空值兼容**（归入空值组，不报错）。UT-27 验证。
- **切换事件独立流水**（PRD FR-3-14「切换与重试事件记录」精确落地）：每次「触发 bench(R) 并切到下一资源」写入一行 `data/usage/switch-events-YYYYMMDD.jsonl`（按天分文件、7 天保留、单写队列串行化）：`{"ts", "request_id", "system_model", "from_resource", "to_resource", "reason_cls", "error_summary", "was_cooldown": true/false}`。重试（同资源内 m 次）不出独立行，只在 per-request 事件的 `retry_count`/`resource_attempts[].attempts` 体现。
- **日聚合（单天单文件）**：启动时 + 每小时整点，**把当日 events 重算并覆盖写入 `daily-YYYYMMDD.json`**（每一天一个独立文件）。字段：按网关模型 / 资源 / 令牌 / **供应商（provider）/ 账号（account）**五维（`by_model` / `by_resource` / `by_token` / `by_provider` / `by_account`，后两维为 Q17 新增派生维度——由事件行冗余字段聚合而来，PRD FR-6.1）的次数、成功/失败/中断、token、重试、切换、耗时、TTFT、图像张数、费用估算；**历史天的 daily 文件一旦生成不再修改**（重算成本小：events 只保留 7 天）。对比 PRD 示意的 `daily-YYYYMM.json`（月度文件），修正为按天文件的好处：原子覆写、重启无损、7 天清理时直接删 N 天前的两个文件（events + daily）。
- 保留策略（统一）：`retention_days`（默认 7）天之前的 **events-YYYYMMDD.jsonl / switch-events-YYYYMMDD.jsonl / daily-YYYYMMDD.json** 三个文件**原子删除**（启动时 + 每日 04:00 后台 task）。日聚合快照文件**超 7 天也保留**（看板历史视图，容量可忽略）——即只删 events/switch-events，daily 快照历史全部保留。
- 看板/日志页数据源口径：请求日志页读事件 JSONL（实时）；数据看板读「历史 daily 文件 + 当日 events 实时重算」双段，避免整点前数据滞后。**admin stats 响应含可用维度键列表**（`by_model` / `by_resource` / `by_token` / `by_provider` / `by_account`），前端看板维度 tab 由维度键数据驱动生成、**不写死维度清单**（Q17，PRD FR-7.6）——后端新增维度，前端自动出现对应 tab。UT-27、INT-47 验证。
- 费用估算：纯本地查表算术（pricing 表），未配置不计费。
- 日志：`data/logs/gateway.log`（运行日志），key 脱敏（`sk-****tail`）；`RotatingFileHandler` 轮转（默认 10MB × 5 备份，可配），防长期运行无限增长。

### 4.9 Web 管理界面（web/）

- 页面对应 PRD FR-7（**Q18-③/⑤ 信息架构重整：七页**——总览 / **资源管理** / 网关模型 / **API 接入** / 数据看板 / 请求日志 / 系统设置）；design-spec v0.5（modern-minimal，含 Q18 重整 + Q19 视觉重设计与资源导向映射）已产出，M2 据此实施。
- **各页要点**：
  - **资源管理**：扁平资源**表格列表**（名称/供应商预设/账号备注/接入模式/base_url/Key 脱敏+明文切换/映射数/状态/启停/编辑/删除），新增资源表单含预设下拉（`GET /admin/api/presets` 数据驱动）；**资源 ID 不出现于表单**（服务端自动生成）；**新增/编辑资源弹窗内一并配置模型映射（Q19-②）**——「供应商模型名 → 网关模型」映射行（供应商模型名输入带枚举池 datalist 候选；目标下拉列已有网关模型 + 「＋ 新建网关模型…」就地新建：名称/端点 chat|images/分组；新资源以 `@new-*` 占位 id 引用，§4.7-④ 服务端解析）；
  - **网关模型（Q19-② 重定位：总览与微调）**：左侧分组模型列表（分组标题 + 模型名，选中态高亮）+ 右侧选中模型详情（名称/启停徽章/端点/分组说明、资源池有序管理：上移下移、资源级推理默认、移除、删除模型）；**映射的新增/调整不在本页**——引导文案指向「资源管理」页编辑对应资源；**无任何调度参数**（全局参数在系统设置，Q18-④）；
  - **API 接入（Q18-③）**：调用地址（本机/局域网）+ 端点清单（`/v1/models`、`/v1/chat/completions`、`/v1/images/generations`、`/v1/messages`）+ 鉴权方式说明 + curl 示例 + **访问密钥管理表格**（名称/值/复制/启停/删除，添加时名称可标注工具用途，支持多密钥）；
  - **系统设置**：网关参数 + 调度全局参数（x/y/m/退避/冷却）+ 数据目录 + 系统运行控制（重启/停止）；**无令牌管理（移至 API 接入页）、无「接入产品」管理（Q18-⑤）**。
- **视觉方案（Q19-① 重设计 + Q21 令牌化双主题）**：**令牌化双主题**——`base.css :root` 定义浅色令牌 + `[data-theme="dark"]` 覆盖深色令牌（bg/surface/border/text/brand/语义色/侧栏/阴影/滚动条/开关全量令牌化，`color-scheme` 同步），**侧栏随主题切换**（浅色白 / 深色深，推翻 Q19 固定深色侧栏）；品牌区 = 渐变 logo 标记 + 产品名；导航项 = SVG 线性图标 + 文字，激活态左侧指示条；底部运行状态点；组件（按钮/表格/表单/弹窗/徽章/开关/toast）统一现代风格（圆角、层次阴影、hover/active 交互态）。**主题三态切换（Q21-②）**：`index.html` 顶栏主题按钮 + 弹出菜单（浅色/深色/跟随系统，全 SVG 图标）；`main.js` 主题模块——`localStorage.mg-theme`（light|dark|system，默认 system）持久化，`html[data-theme]` 由 `matchMedia('(prefers-color-scheme: dark)')` 解析，系统配色变化实时联动（`change` 监听）；**纯前端，无后端接口/配置变更**。数据看板 Chart.js 网格/刻度/图例颜色取主题令牌（`--border`/`--text-faint`）随主题自适应。
- **静态资源禁缓存（Q19-① 根因修复 · 2026-09-05 加严）**：`main.py` 注册 `_StaticNoCacheMiddleware`——对静态资源请求（HTML/JS/CSS，即 StaticFiles 挂载 `/` 的响应）统一加 `Cache-Control: no-store` 响应头（原 no-cache 协商 304；本地静态资源无缓存价值，no-store 不落盘，**杜绝浏览器缓存新旧混载的 ES 模块导致 import 失败——实测症状为静态框架在、JS 渲染的内容区永久空白**），界面改版即时可见；`index.html` 另有装载兜底（3s 未见 main.js 启动标记 → 内容区显示强制刷新指引）；**界面文件更新自动刷新**（2026-09-05）：main.js 启动时快照全部界面模块文本（main/api/components/base.css/七页），每 20s 重取比对，变化 → toast 提示 + 3s 后自动 `location.reload()`——根治「旧标签页长期不刷新，跑旧脚本与新文件混搭」的排障泥潭；`/admin/api/*` 与 `/v1/*` API 响应不受影响。
- **无令牌门**：管理界面免鉴权直访（Q18-①），打开即用，无登录/令牌输入步骤。
- 技术形态：无构建静态资源（原生 ES Modules + 手写 CSS + vendored Chart.js），由 FastAPI StaticFiles 挂载 `/`。
- 全部操作走 `/admin/api/*`，最终读写两个明文 YAML（界面与文件双向一致，改文件也生效——热重载保证）。

### 4.10 系统运行控制与单实例锁（Q17/D2-D4，PRD FR-12）

#### ① main.py Server 化重构与启动序列

- M1 形态为 `uvicorn.run(app, ...)` 直启（`model_gateway/main.py`）——该形态拿不到 Server 句柄，无法从 admin 端点触发停机。v1.1 重构：`uvicorn.Config(app, host, port, ...) + uvicorn.Server(config)` 实例化后以 `server.serve()` 运行；**Server 实例挂 `app.state`**，供 system 端点设置 `should_exit`。
- **启动序列（严格顺序）**：加载配置（config.yaml + model-enums.yaml 校验通过，失败即退出）→ **获取单实例锁**（检测/清理/登记，见 ③④；获取失败按 ④ 退出，不进入服务启动）→ 绑定端口启动服务（`serve()`）；端口绑定失败按 ⑤ 兜底报错退出。

#### ② stop / restart 端点（免鉴权，Q18-①）

- `POST /admin/api/system/stop`：**优雅停机**——端点先返回受理确认（如 `{"status": "stopping"}`），随后设置 `server.should_exit = True`；uvicorn 优雅停机（**在途请求收尾后**才退出事件循环）→ 进程退出前经 atexit 释放单实例锁。
- `POST /admin/api/system/restart`：与 stop 相同的优雅停机 + 锁释放完成后，`os.execv(sys.executable, [sys.executable, "-m", "model_gateway.main", ...原 argv])` **进程映像替换**——**PID 不变、同端口重绑、配置重读、锁重新登记**（新映像重走启动序列，锁检测命中 pid==自身 → 覆盖重写，见 ④）；execv 前后环境变量 / TTY / 文件描述符天然继承（D3：无孤儿进程）。
- **设计纪律**：execv 必须在 `serve()` 返回（在途请求全部收尾）**之后**执行——顺序固定为「返回确认响应 → should_exit → serve() 返回 → 释放锁 → execv」。
- **execv 失败兜底**：捕获 `OSError` → 明确报错退出（此时锁已释放，可经 `启动网关.command` 重新拉起），不静默残留。

#### ③ gateway.lock 文件结构与获取/释放

- 路径 `data/gateway.lock`，**明文 JSON**（可查可删，D2）：`{"pid": <进程号>, "port": <监听端口>, "base_url": "http://127.0.0.1:<port>/", "started_at": "<ISO8601 启动时间>"}`。
- 获取：按 ④ 决策树判定通过后**覆盖重写**（tempfile + `os.replace` 原子写），再继续启动。
- 释放：**atexit 钩子 + SIGTERM/SIGINT 信号处理**统一收尾路径——退出前校验锁内 `pid == 自身` 才删除（幂等，防误删后续实例的锁）；stop / restart / Ctrl+C / kill 信号均走此路径。

#### ④ 启动检测决策树（含陈旧锁清理与退出码 3）

```
读 data/gateway.lock
├─ 锁不存在                         → 写锁 → 继续启动
├─ 读取/解析失败（含半行 JSON 损坏）  → 按陈旧锁处理：清理 → 写锁 → 继续启动
├─ 解析成功，按 pid 分支：
│   ├─ pid == 自身（execv 重启场景）  → 覆盖重写锁 → 继续启动
│   ├─ pid 存活（os.kill(pid, 0) 未抛 ProcessLookupError，且非自身）
│   │    → 终端打印「已有实例运行中：后台地址 http://127.0.0.1:<port>/（PID、启动时间）」
│   │    → 退出码 3 退出（不启动新实例、不换端口、不询问；交互/非交互一致，D4）
│   └─ pid 已死（os.kill 抛 ProcessLookupError → 陈旧锁，异常退出残留）
│        → 自动清理 → 写锁 → 继续启动
```

- **PID 复用误判**（陈旧 pid 被系统分配给无关进程）：按「pid 存活即拒绝启动」保守处理——宁可拒绝不猜测；锁为明文可查可删（D2），用户确认后可手动清理再启动。
- **竞态（TOCTOU）**：读 → 判 → 写在启动早期同段完成，双进程同时冷启动的窗口极小；即使漏检，⑤ 端口绑定兜底保证不出现双实例同端口服务。

#### ⑤ 端口占用兜底

锁检测遗漏（极端竞态）时，第二个实例在 uvicorn 绑定端口阶段失败（端口已被占用）→ **明确报错退出**（错误信息提示已有实例 / 端口占用），不静默换端口。

#### ⑥ 启动网关.command（macOS 双击启动脚本，FR-12.2）

项目根 `启动网关.command`（`chmod +x`），流程：

1. `cd` 到脚本自身所在目录（= 项目根）；
2. 检测 `.venv/`：缺失 → 打印环境搭建指引且**窗口不关闭**（等待按键，防闪退）；
3. 存在 → **前台**执行 `python -m model_gateway.main`——日志直接可见、Ctrl+C 可停；
4. 网关因「已有实例」以**退出码 3** 退出时：窗口显示后台地址并**保持开启**（不重复启动，用户查看地址后自行关闭）；
5. 其它异常退出：窗口同样保持开启显示错误输出，便于排查。

验证用例（test-cases v1.1）：UT-28（锁检测纯逻辑五场景）、INT-42/43（stop/restart 端点）、INT-44/45（单实例互斥/陈旧锁清理）、E2E-17/18/19（界面启停、单实例、双击脚本）。

### 4.11 界面参考项目规范精修（Q22，PRD v1.9 §9-Q22）

> **纯前端改动**（`base.css` / `index.html` / `main.js` / 7 个页面 JS），无后端接口/配置变更；三态主题机制（§4.9 Q21-②）与静态资源禁缓存（§4.9 Q19-①）原样延续。视觉基准 = 用户指定参考项目 `/Users/w/Desktop/react-v16-cursor/整体前端代码`（`ConsolePage.tsx`，主参考页 `/console/skills`，dev server `http://localhost:5173`）。

#### ① 黑主色令牌（推翻 Q21 indigo 主色）

- 参考项目 active 导航/主按钮/开关 on 统一黑主色（`bg-black`、hover `#171717`）——`base.css` 主色令牌整体换黑：浅色主题 `--brand:#171b22`（hover `--brand-strong:#0f1216`），深色主题**反转为白** `--brand:#e8eaee`（`--on-brand` 文本令牌同步反转 `#17191d`），保证按钮/激活态文字对比度。
- 生效面：主按钮（`btn-primary`）/ 激活导航项 / 开关 on / 品牌方块 / `--ring` focus 环 / 分段 tab 激活态全量走 `--brand` 令牌，双主题自动适配。

#### ② 参考规范组件层

- **卡片**：无边框 + 软阴影（`--shadow-card: 0 10px 24px rgba(15,23,42,.035)`，圆角 13px）；深色主题阴影不可见 → 补 1px 深边框（`--card-border` 令牌）。
- **软边框体系**：`#eef1f3` 用于表格行分隔/控件描边/hover 底 `#f6f7f8`；文本三级 `#171b22/#59616a/#a3abb3`；状态绿点 `#16d76d`。
- **分段式 tab**：参考项目 SegmentedTabs——灰底容器（`--seg-bg`）rounded-11 + 活动段白底浮起带小阴影；**纯 CSS 重塑**（`.tabs/.tab` 样式重写），`components.js` 类名契约不变、零改动。
- **表格/表单**：表头无底色 + 行分隔线；输入框底 `#fafcfc` + focus 边框转深；徽章 6px 圆角 + 参考色板语义色；开关 40×24 黑 on。
- **指标卡图标块**：38px 圆角块 + lucide 线性 SVG + 四色调（mi-blue/green/orange/purple 淡底彩字）+ 右侧信息列横排；总览 4 卡 / 数据看板 7 卡落地。

#### ③ 分组侧栏 + 两行顶栏

- **侧栏分组导航**：四分组（概览/资源配置/运行观测/系统设置），组标题 12px bold 灰；激活项黑底白字 + 尾部绿点 `#16d76d`；品牌区加副标题 "LLM Gateway Console"。
- **两行顶栏**：上行面包屑 `Console › 分组`（12px 灰）+ 下行页标题（15px extrabold）——页标题**由路由统一注入**：`main.js` 新增 `PAGE_META`（title/group），`route()` 写入面包屑与 `document.title`；内容区 7 页 `page-head` 移除重复标题（降为纯操作行）。
- Chart.js 网格/刻度/图例继续取主题令牌（Q21 机制），换黑主色后曲线色自动适配新令牌。

#### 验证

- test-cases v1.6 E2E-20 追加⑩项；实测证据 `docs/changes/e2e-records/E2E-20260905-Q22-refined-ui.md`（pytest 187 passed 持平 + headless Chrome CDP 七页双主题截图 11 张存档 `q22-screenshots/`）。

### 4.12 Responses API 兼容面（`/v1/responses`，PRD FR-11 P2「OpenAI Responses API 透传」）

**定位**：新一代客户端（Codex CLI、只认 Responses 的 agent）不发 `messages`/`max_tokens`，
而发 `input`/`instructions`/`max_output_tokens` 且只解析 Responses 的 SSE 事件。本端点是
**纯翻译层**：不复用第二条管线，选路/重试/故障切换/计费/取消/断连监视全部走
`scheduler.execute_chat` / `scheduler.stream_chat`（与 `/v1/chat/completions` 同一条链）。

**协议真值**：字段与事件以 OpenAI 官方 SDK 类型定义为准（`openai@6.26.0`
`resources/responses/responses.d.ts`）；真实事故口径参考同类本地网关的成熟实现
（`deepseek-harness-codearts/src/openai-gateway/responses.ts`，只读、未采用其代码）。

**三档字段处置**（改之前先读，`api/responses_compat.py` 文件头有逐条理由）：

| 档 | 字段 | 处置 |
|---|---|---|
| ① 能 1:1 表达 | `instructions` / `input` / `tools(function)` / `tool_choice` / `temperature` / `top_p` / `max_output_tokens` / `parallel_tool_calls` / `reasoning.effort` / `text.format`（→ chat `response_format`）/ `stream` | 忠实翻译 |
| ② 纯提示、遥测、缓存 | `store` / `include` / `prompt_cache_key` / `prompt_cache_retention` / `prompt_cache_options` / `service_tier` / `safety_identifier` / `metadata` / `user` / `truncation` / `max_tool_calls` / `stream_options` / `context_management` | **接受并忽略**（不改变本次内容语义；转发给异构上游只会多换一个 400） |
| ③ 🔴 语义会变又做不到 | `previous_response_id` / `conversation` / `background: true` / `input_file` / `input_image.file_id` / 未知 input item 类型 | **明确 400 + 可操作替代做法**（禁止静默忽略 —— 那是「用户以为设置生效了」） |

**无状态**：`store` 恒回 `false`，`GET /v1/responses/{id}` 一律 404（会话状态由客户端
维护）。服务端会话库在结构上可做（本地明文 JSON + 保留策略），但属**新存储层独立立项**，
不在「透传」需求内。

**工具**：`function` 1:1（兼容扁平与 chat 嵌套两种形状）；`namespace` 子工具摊平为
`<namespace>__<child>`（>64 字符截断 + 8 位哈希）并在响应侧**还原 `{name, namespace}`**；
`custom` / `tool_search` / 内置工具**丢弃 + warning 日志 + `X-GW-Dropped-Tools` 响应头**，
**绝不 400**（把「整轮对话不可用」当成本太贵）。重名先到先得，被丢弃者不得进还原表。

**流式**：延迟提交（首内容事件前零字节，窗口耗尽回非 200 JSON，§6）→ `response.created`
/ `response.in_progress` → 逐项 `output_item.added` + `content_part.added`/`reasoning_summary_part.added`
+ delta 事件 → 逐项 `*_done` + `output_item.done` → 终态 `response.completed` /
`response.incomplete`（`finish_reason=length`）/ `response.failed`。每事件带连续
`sequence_number`，**不发 `data: [DONE]`**（那是 Chat Completions 的约定）。

**usage 官方口径**：`input_tokens` 含缓存命中，命中量单列 `input_tokens_details.cached_tokens`；
`output_tokens_details.reasoning_tokens` 恒在；`total_tokens = max(上游报的, 输入+输出)`。
（少算会让客户端把缓存量当负输入夹到 0 ⇒ 自动压缩永不触发。）

**响应完整性**：`output` 按开启顺序排序、按 `output_index` 递增；空 `output[]` 补一个空
message 项；**所有可空字段都必须存在**（官方 SDK 按 schema 解析，缺键 = 客户端反序列化失败）。

**验证**：UT（`tests/unit/test_v2_responses_compat.py`，请求/响应/SSE 编码三组）+
INT-121~130（`tests/integration/test_int_v2_responses.py`，假上游端到端）；证据
`docs/changes/e2e-records/E2E-20261008-responses-endpoint.md`。

---

## 5. 调度精确语义（核心状态机）

> 本节把 PRD FR-3.4/3.5/3.7/3.8 的语义精确化为**统一判定规则**；默认 m=3、y=2（PRD Q11 定值）。

### 5.1 记号
- `m`：单请求单资源**重试**上限（默认 3）→ 同一资源上最多尝试 `m+1` 次（1 次首发 + m 次重试）。
- `y`：资源连续失败判定阈值（默认 2）。
- `C(R)`：资源 R 的连续失败计数（**跨请求累计，含请求内每次尝试失败**；成功清零）。

### 5.2 统一判定规则（每次上游尝试结束后按序执行）

```
async def execute(ir_req, system_model):
    deadline = now() + cfg.request_total_budget       # ★ 请求总预算（§5.5，默认 300s，可配）
    exhausted_reason = NONE
    tried = ∅
    while (resource = pick_for_request(pool, exclude=tried)) is not None:
        # ★ 选路规则（§5.3 并发溢出生效集，2026-09-03 定论）：
        #   生效集 = 池中 top-x 可用资源（跳过 cooldown/disabled/invalid，成员被
        #   移出时由待命资源补位）；集内取「在途请求最少」者承接本次请求，平局取
        #   优先级高者 → 低负载集中打最高优先级，并发时溢出到生效集内下一资源；
        #   故障切换的目标资源同样按此规则选取（排除本请求已尝试过的资源）
        m, y = cfg.retry_per_request, cfg.fail_threshold   # ★ 全局参数（Q18-④：不支持按模型覆盖）
        tried.add(resource)
        for attempt in 1..m+1:
            # ★ 每次尝试边界：先探测断连（§4.6 延迟提交窗口）再检查预算
            if await client_disconnected():
                cancel_upstream(); mark aborted; return   # 中止整链：不计失败不重试

            if now() > deadline:
                exhausted_reason = "BUDGET_EXHAUSTED"
                break                                     # 总预算耗尽 → 跳出走兜底
            #
            # ★ CancelledError 专用捕获（设计纪律：绝不能与上游失败混为一谈）
            #   - asyncio.CancelledError = 客户端主动取消（响应task被cancel）→ aborted
            #   - httpx.TimeoutException/ConnectError 等 = 供应商端异常 → RETRYABLE
            #   - HTTP 408 canceled_error（商汤） → classify 归 CANCELED → aborted 透传
            try:
                outcome = await call_upstream(resource, ir_req,
                                 timeout=cfg.attempt_timeout)  # 单次尝试超时（§5.5）
            except asyncio.CancelledError as ce:
                cancel_upstream()         # 保险：取消已注册的上游task
                mark aborted
                raise ce                  # ★ 关键纪律：必须 re-raise，严禁吞！
                                                 #   （调用方捕获后不进入失败分类）
            except Exception as e:
                outcome = Failure(error=e)   # httpx 异常 → 进入 classify

            if outcome.ok:
                C(R) = 0                                # 成功清零
                return outcome                          # ★ 工具端拿到结果
            cls = classify(outcome.error)

            if cls == CANCELED:                         # 供应商 408 canceled_error
                mark aborted                            # 不计失败不切换；
                return passthrough(outcome.error)       #   错误**透传调用方**（区分于客户端取消）

            if cls == BAD_REQUEST:                      # 参数类 4xx
                return passthrough_error(outcome.error)  # ★ 原样透传（换资源同样失败）

            if cls == AUTH:                             # 401/凭据 403
                disable(R); emit_switch_event(reason="AUTH"); break   # 停用+告警 → 切下一资源

            if cls == NOT_FOUND:                        # 404
                mark_invalid(R); emit_switch_event(reason="NOT_FOUND"); break  # 无效+告警 → 切下一资源

            if cls == QUOTA:                            # 429/配额
                ok = backoff_retry(R, ir_req, times=cfg.quota_retry,   # 默认 2
                                   delay=指数退避)       # 1s,2s…（可配；sleep 分段可取消）
                if ok: C(R)=0; return ok
                bench(R); emit_switch_event(reason="QUOTA"); break   # 移出+冷却 → 切下一资源

            # cls == RETRYABLE（网络/超时/5xx）
            C(R) += 1                                    # ★ 计入连续失败（跨请求）
            if C(R) >= y:
                bench(R); emit_switch_event(reason="RETRYABLE_Y")
                break                                     # ★ 命中 y：移出冷却 + 当次请求立即切下一资源
            if attempt == m+1:
                exhausted_reason = "RETRY_EXHAUSTED"
                break                                    # 重试额度耗尽（C 仍 < y，即 y > m+1 场景）
                                                          #   → 切下一资源，R 不冷却
            await sleep(cfg.retry_backoff)               # 默认 0 = 立即重试
        if exhausted_reason == "BUDGET_EXHAUSTED": break  # 预算耗尽时跳过后续资源
    return unified_no_resource_error(system_model,      # ★ 全部不可用/预算耗尽兜底
                                     reason=exhausted_reason,
                                     attempts_summary=...)   # 含「预算耗尽」标注+已尝试资源
                                                          #   （唯一向工具端报错的出口之一）
```

- `bench(R)`：移出生效集 → `cooldown_until = now + cooldown_seconds`（api 模式默认 60s；plan 模式默认 18000s 对齐滚动窗口；均可配）→ 到期懒恢复归位。
- 请求内在 R 上的失败**同时**计入 C(R)（PRD FR-3.4）；C(R) 命中 y 时**当次请求立即切换**（不再消耗 R 上剩余重试额度）——「命中条件即更换资源」（PRD Q11 用户原话口径）。
- **默认参数下的实际行为（m=3, y=2）**：资源连续失败 2 次即冷却并切换——即「失败 1 次 → 原资源重试 1 次 → 仍失败 → 切资源」。m 的余量在 y > m+1 或 QUOTA 退避等场景生效。此 m/y 生效顺序（**y 先判定**）已于 2026-09-03 经用户确认定论（PRD v1.1 §9-Q14），原待评审确认点 1 撤销。
- 429 退避重试默认 2 次、指数间隔（基值 1s，可配 `quota_backoff_base_seconds`）；plan 模式 429 冷却默认对齐滚动窗口（18000s）。
- 并发请求间通过 `asyncio.Lock` 串行化 C(R)/状态变更；同一资源可同时服务多个请求（供应商侧并发不管理，非目标）。

### 5.3 x（max_active_per_model）：并发溢出生效集（2026-09-03 重对齐定论）

> v0.2/v0.3 曾结论「x 仅展示性」——那是「顺序集中 + 补位 + 不中断」三条已确认决策联立的数学结果（路由恒等于「取最高优先级可用资源」，x 取任何值结果相同）。用户不认可该口径，于 2026-09-03 重新对齐，在四个候选（A 并发溢出 / B 生效集内轮询 / C 单请求切换深度上限 / D 维持热备窗口）中**选定 A 并发溢出**（PRD v1.1 §9-Q13）。

**选路规则（每个请求进入调度时执行，`pick_for_request`）**：
1. **生效集** = 池中 top-x **可用**资源（按优先级，跳过 cooldown/disabled/invalid；成员被移出时由池中下一待命资源**补位**，集合大小恒为 min(x, 可用数)）；
2. 生效集内取「**在途请求最少**」的资源承接本次请求；**平局取优先级高者**。

**行为效果**：
- **低负载（顺序请求）**：在途归零后，新请求总是回到最高优先级资源——与原「顺序集中调用」完全一致；
- **并发时（多工具同时调用）**：最高优先级资源在途未清零 → 溢出到生效集内下一资源——**任意时刻最多 x 个资源同时承接流量**（「最多同时生效 x 个资源」的准确落地）；
- **x=1 退化为纯顺序集中**；x 越大，并发吞吐上限越高；
- 故障切换/冷却/重试（m/y）机制不受影响：资源命中 y 被移出后由待命资源补位，生效集保持满员；**故障切换的目标资源也按同一选路规则选取**（排除本请求已尝试过的资源）。

**在途计数（in-flight，纯内存态）**：每资源维护计数器——请求开始在该资源上尝试时 +1，该次尝试结束（成功/失败/取消）时 -1；重启归零、不落盘。选路与 +1 在同一 asyncio 同步段内完成（单线程事件循环，天然无竞态）。

**与原确认决策的关系（诚实标注）**：低负载行为 = 原「顺序集中调用，不轮询」；并发行为 = 溢出分流——原表述「请求集中打到生效集中优先级最高的资源」在并发场景放宽为「集中打到生效集内在途最少的资源」。
⚠️ **本节整段是 Q13 定论的历史形态，2026-10-02 已被 §5.3a（Q33-③）部分推翻**：其中「不轮询 / 顺序请求恒走最高优先级」那半作废，「最多 x 个资源同时承接」那半保留并改由**活跃组**保证。凡引用本节选路规则，一律以 §5.3a 为准。

#### 5.3a 🔴 Q33-③ 修订（2026-10-02 用户指令，**翻案上文「不轮询」**）

用户定版：**同一产品下的同一模型资源采用「多号并行 + 轮流调用」**（例：workbuddy 接 10 个号、
产品维度开了 DeepSeek v4.1、其中 4 个号启用 ⇒ 这 4 个号**轮流**承接该模型的调用）。
上文「低负载行为 = 顺序集中调用、不轮询」（§5.3 选定 A、PRD Q13 归档 A 案）**据此翻案**。

**为什么固定前缀切片在这个形态下是错的（不是风格问题）**：生效集若取「池中前 x 条」，
10 个号 + `x=2` 时**永远只有排最前的 2 个号被用到**，其余 8 个号的额度与风控分摊价值归零 ——
而 §26 调研轮已证「多号池化的真正收益是额度/风控分摊，不是并发上限」。

**修订后的选路规则**（`core/resources.py::pick_and_acquire` / `release`）：
1. **生效集 = 活跃组**（`ResourceManager._groups`，长度恒 ≤ x）：从**轮转游标**起按池序取 x 条可用候选
   组成当前这一组，**只有组内成员可被派发**；🔴 **整组排空**（组内每条在途都归零）才把游标后移、
   下一组上位。为什么不是"某个号排空就换位"：那样仍在途的号会落到新窗口之外，而新窗口照样开满 x 条
   ⇒ 同时在途 = x + 残留，"最多 x 个资源并行"（用户指令 1 对 x 的定义）当场失效
   （评审 R2-① 探针实测 `x=1/2/3` 四号同时在途；撤证 M11 = `1 failed`，判据 UT-80）；
2. 组内取「在途最少」者承接（保留原「不堆同一个号」的性质）；**平局由游标决定**，
   于是空闲号之间按池序轮转：四个号全空闲时连续四条请求 = 1/2/3/4 各一条（判据 UT-68 / INT-75）；
3. 🔴 **轮转只作用于常态轮**（`exclude` 为空 = 本请求第一次选路）。**切换轮**（已尝试过资源）
   按池序找替补 —— 切换的语义是「刚试过 A，按用户排的优先级换 B」，
   若切换也跟着滑动，会跳到窗口尾部的 D，等于把「额度分摊」与「主备次序」两件事混成一件事；
   🔴 替补**取序 = 组内优先**（复验轮 R4-A）：组里还有可派发的成员就必须用它（即便它已在途），
   不许跳过组内去开组外新号 —— 否则"最多 x 条并行"被切换轮自己打穿（判据 UT-83，撤证 M13）；
   ⚠️ 切换轮**不参与 x 上限**：组内替补全被 `exclude` 时允许用池外备胎（宁可那一刻多一条在途，
   也不能让"明明有可用号"的请求吃 503）——这是"最多 x 条并行"这条定论的**唯一**例外，如实登记；
4. 游标与组**随池回收**（模型删/改名不留孤儿键，组内成员被移出池时同步剔除），
   **热重载不重置仍在的模型的游标**（否则一次配置保存就把刚被用过的号永久排到队尾之后）。

`x` 的口径同时明确为：**单个网关模型映射上「同时开启的并行可用资源条数」上限，统计跨两类接入**
（按量 Key 资源 + 产品账号资源，同一个 `models[].resources[]` 池）。仍是全局唯一参数（Q18-③ 不翻案）。
串行场景下这 x 条会随排空逐组换位 ⇒ "开 4 个号就 4 个号轮流"；并发场景下超出的请求复用组内最闲者。

### 5.4 切换续跑的流式边界

见 §6。非流式/图像：请求可整体重放，全规则适用（含跨多资源逐个尝试，直到成功或全部耗尽）。

### 5.5 超时与请求总预算（「不中断」与「不挂起」的边界，v0.2 新增）

PRD FR-3.5 要求「只要有可用资源不中断」，FR-3.9 要求「禁止无限挂起」——两者需要一个明确边界，否则资源池大时（如 10 资源 × 每资源多次尝试 + 退避）最坏耗时不可控：

| 参数 | 默认 | 语义 |
|---|---|---|
| `attempt_timeout_seconds`（承接 PRD §6 `request_timeout_seconds`） | **60**（终审由 120 调小；思考型模型首字节慢若被误杀，实测后调回即可） | **单次上游尝试**整体超时（connect + read + write 合并）；超时异常按 RETRYABLE 分类，正常参与同资源重试 / 切换续跑 |
| `request_total_budget_seconds` | **300**（终审由 600 调小） | **单请求总预算**：一次入站请求的全部资源尝试 + 重试 + 退避的总时长上限（**不管成功任务本身的执行时长**——流式输出开始后跑多久都行）；每次新尝试开始前检查，耗尽 → 跳出循环走「无可用资源」兜底（错误信息标注「预算耗尽」+ 已尝试资源与原因摘要） |

- 单次尝试超时 ≠ 请求失败：它只是 RETRYABLE 的一个失败样本（网络慢场景下换资源常有效）。
- 总预算同时是延迟提交窗口的等待上限（§6）：客户端在首帧前的最长无字节等待 ≤ 总预算。
- 两参数均为**全局参数**（Q18-④：不支持按模型/资源覆盖），可按需调整（调大 = 更坚持不中断；调小 = 更快兜底）；默认值已经终审确认（§11-4/6，PRD v1.3 §9-Q16）。

---

## 6. 流式边界与中途失败实现口径（PRD FR-3.6 的精确化）

**判定点 = 「首帧转发」（向客户端发出第一个内容字节）**，严于「首 token 接收」：

| 阶段 | 状态 | 失败处理 |
|---|---|---|
| 响应头未提交 + 未转发任何内容 | **可安全重放窗口** | 完整适用 §5 规则：重试 ≤ m → 切资源续跑 → …… 工具端**零感知**（只观察到正常延迟） |
| 已转发部分内容 | **不可重放**（重发导致内容重复错乱） | ① **不自动重放**；② ErrorClassifier 分类：**可重试类**（网络断/超时/5xx）→ 以标准 SSE error 帧终止流并标注 `retryable`（支持自动重试的工具端可自行重新发起整请求）；**不可重试/不确定类** → 供应商原始错误信息作为 error 帧**原封透传**（已输出内容已在客户端，不吞、不修饰），由用户判断是否重新触发；③ 两种情况均计入 C(R)（中途失败也是失败） |

- 「首帧转发」前网关仅缓冲初始事件（如 role chunk），不向客户端发送任何字节——由此「首 token 前」与「首转发前」统一，实现无歧义。
- 请求幂等性依据：POST chat/completions 无服务端副作用，重放安全。
- 延迟提交的代价：重试/切换期间客户端无字节到达（工具端自身超时需容许；**请求总预算兜底**，见 §5.5——首帧前最长等待 ≤ 总预算，不会无限挂起）。

---

## 7. 代码目录结构

```
Model-Gateway/
├── AGENTS.md
├── pyproject.toml              # 包元数据 + 依赖 + pytest 配置
├── 启动网关.command             # macOS 双击启动脚本（§4.10-⑥）
├── .cursor/                    # rules / memory（已有）
├── docs/specs/                 # prd.md · tech-design.md · test-cases.md（真相源）
├── model_gateway/
│   ├── __init__.py
│   ├── main.py                 # 入口：装配 + uvicorn Server 启动（单实例锁/优雅停机/自重启，§4.10）
│   ├── api/                    # 入站层
│   │   ├── auth.py             # /v1/* 访问令牌中间件（admin 免鉴权，Q18-①）
│   │   ├── openai_compat.py    # /v1/models · /v1/chat/completions · /v1/images/generations
│   │   ├── anthropic.py        # /v1/messages
│   │   ├── responses_compat.py # /v1/responses（Responses API 兼容面，§4.12）
│   │   └── admin.py            # 管理 API（CRUD + 统计/日志查询 + 健康测试；ID 自动生成与脱敏还原）
│   ├── core/
│   │   ├── ir.py               # 内部标准格式（pydantic）
│   │   ├── scheduler.py        # §5 调度状态机
│   │   ├── resources.py        # 资源池/生效集/冷却/计数（懒恢复）
│   │   ├── errors.py           # 错误分类器（FR-3.13 代码化）
│   │   └── cancel.py            # 取消注册表与透传
│   ├── adapters/
│   │   ├── base.py             # 适配器接口
│   │   ├── openai_out.py       # OpenAI 兼容出站（商汤首发）
│   │   ├── anthropic_out.py    # Anthropic 原生出站（P1 → **v2.0 提为 P0**，§18）
│   │   └── gemini_out.py       # P2
│   ├── upstream/               # 🆕 上游产品接入层（v2.0，与核心调度解耦，§17）
│   │   └── zcode/              #   首期只有 ZCode 一个产品（**不做 base.py 抽象**，§15.2）
│   │       ├── __init__.py
│   │       ├── crypto.py       #   enc:v1 加解密
│   │       ├── oauth.py        #   OAuth 双流程 + refresh
│   │       ├── account.py      #   账号模型 + 列表管理
│   │       ├── dataroot.py     #   整根隔离 + 设备 ID（§15.2/15.3）
│   │       ├── quota.py        #   额度三通道 + 3012 熔断
│   │       ├── claim.py        #   签到/领取（HTTP 交互，§16.6）
│   │       └── auth.py         #   双通道鉴权 + TLS 指纹
│   ├── ops/                    # 🆕 运营调度（v2.0，薄适配器，§16.6）
│   │   ├── __init__.py
│   │   ├── runner.py           #   批量执行器：cron + 双层互斥 + 抖动 + 隔离 + 四类结果
│   │   └── builtin/            #   首批 operation：zcode_claim / query_balance
│   ├── cli.py                  # 🆕 mgw 命令入口（v2.0 M3-0，此前无任何入口）
│   ├── config/
│   │   ├── loader.py           # 加载/校验/热重载/原子写
│   │   ├── schemas.py          # pydantic 配置模型（PRD §6 schema 落地）
│   │   └── presets.py          # 供应商预设注册表（内置常量清单，§4.7）
│   ├── enums/
│   │   └── matcher.py          # 统一名自动匹配（精确→别名→规范化，置信度）
│   ├── stats/
│   │   ├── events.py           # JSONL 流水
│   │   └── aggregate.py        # 日聚合 + 看板查询
│   ├── web/
│   │   └── static/             # 管理界面（无构建；vendored chart.js/）
│   │       ├── index.html      # 七页单页骨架（hash 路由）
│   │       └── js/pages/       # dashboard / resources / models / apiaccess / stats / logs / settings
│   └── logsetup.py             # 脱敏日志
├── tests/
│   ├── unit/                   # 调度/分类/匹配/校验纯逻辑
│   ├── integration/            # 假供应商后端（可编程错误序列）
│   └── conftest.py
├── scripts/
│   └── sensenova_probe.py      # M1 商汤双端点实测脚本（§10.2）
└── data/                       # 运行时数据（.gitignore；config.yaml 由用户创建/界面生成）
```

---

## 8. 关键技术决策与风险

| # | 决策/风险 | 处置 |
|---|---|---|
| 1 | **asyncio 取消语义陷阱**：客户端断连的 `CancelledError` 若被通用 `except Exception` 捕获，会误判为上游失败（误计 C、误切换） | 取消路径专用处理 + 必须 re-raise；单测/集测强制覆盖（INT-09）；评审时重点检查每个 `except` 块 |
| 2 | **超时与取消混淆**：httpx 超时异常 ≠ 取消 | 分类器区分 `httpx.TimeoutException`（RETRYABLE）与 `CancelledError`（CANCELED） |
| 3 | **配置文件崩溃损坏** | 全部写入走 tempfile + `os.replace` 原子替换（同目录，保证同文件系统） |
| 4 | **热重载与在途请求竞态** | 请求绑定配置快照；资源状态（C/冷却）独立于配置快照，按资源 ID 关联 |
| 5 | **流式重放边界实现歧义** | 「首帧转发」严格定义（§6）；初始事件缓冲后才提交 |
| 6 | **m/y 生效顺序** | 统一规则见 §5.2；**y 先判定**（2026-09-03 用户确认，原 §11-1 落定） |
| 7 | **商汤 Key 体系未知** | 不猜测：M1 首项双端点实测定论（§10.2）；两种预设内置，切换零成本 |
| 8 | **纯本地前端资源** | 禁 CDN；Chart.js vendored 进仓库（MIT） |
| 9 | **单 worker 并发能力** | asyncio IO 密集场景足够；网关自身并发上限可配（保护本机，FR-4.2）；不做多进程 |
| 10 | **供应商流式思考字段差异**（商汤 DeepSeek V4 Pro `thinking_content`） | 出站适配器归一化为 `reasoning_delta`；透传原则保证多轮回传完整 |
| 11 | **延迟提交窗口断连检测**（v0.2）：响应未开始时 ASGI 不主动推送断连事件，普通 endpoint 的 handler task 不会被自动 cancel | 每次尝试边界 `request.is_disconnected()` 主动探测（§4.6/§5.2 伪代码已含）；INT-24 实测验证 |
| 12 | **事件 JSONL 并发写交错断行**（v0.2） | 单写队列串行化（§4.8）；INT-20 断言行完整性验证 |
| 13 | **CancelledError 与失败混淆**（v0.3 新增）：通用 `except Exception` 捕获 CancelledError 会误判为上游失败（误计 C、误切换） | §5.2 伪代码专用 try/except + CancelledError re-raise；分类器明确区分 httpx 异常 vs CancelledError |
| 14 | **流式端点 HTTP 语义违规**（v0.3 新增）：先发 200 StreamingResponse header 再写 error body 会让工具端混淆 | §4.5 规定窗口耗尽直接 return JSONResponse（非 200），首内容确定到达时才构造 StreamingResponse(200) |
| 15 | **kimi-k3 图片 URL 不支持**（v0.3 新增，PRD FR-1.8 官方口径） | 出站适配器 URL→base64 自动下载转换（§4.2）；下载失败 RETRYABLE 处理 |
| 16 | **切换事件记录形态**（v0.3 新增，PRD FR-3-14 / FR-7-1）：Dashboard 「最近切换事件」需要独立可读数据源 | 独立 switch-events-YYYYMMDD.jsonl + /admin/api/overview 内存环形缓冲（§4.4/§4.8） |
| 17 | **日聚合文件模糊命名**（v0.3 新增）：`daily-YYYYMM.json` 月度文件 + 当日重写会导致重启/竞态 | 修正为按天单文件 `daily-YYYYMMDD.json`（§4.8），原子覆写当天文件，历史文件只读 |
| 18 | **并发溢出选路的在途竞态**（v0.4）：两请求同时选路可能都取同一资源而未溢出 | 选路与在途 +1 在同一 asyncio 同步段完成（单线程事件循环天然原子）；UT-22/INT-22 验证 |
| 19 | **推理参数合并歧义**（v0.5，Q15）：「未指定」与「显式关闭」混淆会把资源默认强加给显式关闭的请求；入站透传字段与出站注入字段重复注入 | IR 用 `None` 区分未指定/显式值；入站把 `reasoning_effort`/`thinking` 从透传字典提升为显式字段（防双重注入）；UT-23/INT-36/37 验证 |
| 20 | **execv 重启边界**（v1.1 新增，Q17）：映像替换时机不当会切断在途请求；环境变量/TTY 继承不确定；execv 失败进程死亡无提示 | execv 严格排在 `serve()` 返回（在途请求收尾）+ 释放锁之后（§4.10-② 设计纪律）；execv 前后环境/argv 原样传递（PID/TTY 天然保持，D3）；捕获 `OSError` 明确报错退出（锁已释放，可脚本重新拉起）；INT-43/E2E-17 实测 |
| 21 | **锁文件竞态与陈旧判定**（v1.1 新增）：TOCTOU（双进程同时判定无锁）、PID 复用误判（陈旧 pid 被新进程占用）、锁文件损坏（半行 JSON） | 读→判→写同段完成压缩竞态窗口；pid 存活即拒绝启动（保守，宁可误拒——锁明文可查可删，D2）；损坏 JSON 按陈旧锁清理重写；端口绑定失败兜底（§4.10-⑤）；UT-28 五场景 + INT-44/45 |
| 22 | **信号处理与 atexit 锁释放时序**（v1.1 新增）：SIGTERM/SIGINT、uvicorn 优雅停机与 atexit 锁释放顺序不当 → 锁残留（下次启动误拒）或误删后续实例的锁 | 统一收尾路径：信号 handler 只触发 `should_exit`（在途收尾），进程退出时 atexit 释放锁；释放前校验锁内 pid==自身（幂等）；INT-42/44 覆盖 |
| 23 | **三层配置结构迁移风险**（v1.2 新增，Q18-②）：providers→accounts→keys 扁平化为 resources[] 时，存量 data/config.yaml 不兼容（启动校验失败）+ 事件/统计的资源标识口径变化 | 提供**迁移脚本/逻辑**：启动或迁移时把三层结构压平为资源条目（供应商+Key+账号备注，ID 自动生成），模型映射三元组改为 resource 引用；资源标识统一为「资源名/供应商模型名」展示口径；INT-48 + 浏览器 E2E 验证迁移后可用 |
| 24 | **管理端免鉴权暴露面**（v1.2 新增，Q18-①）：移除管理鉴权后，同网段任意进程可读写配置/停止网关 | 接受（用户定论：自用系统暂不考虑）——监听仅服务用户自己设备（宪法级），风险由局域网边界承担；文档诚实标注此取舍 |

---

## 9. 性能与稳定性基线（验收口径，实施阶段实测）

- 多工具并发混合场景（20 并发：流式+非流式+中途取消，持续 ≥ 60s）：无请求堆积、内存 RSS 稳定（增长 < 10%）。
- 取消透传延迟：客户端断连 → 上游取消发起 ≤ 1s（心跳周期内更早）。
- 调度开销：选路 + 分类纯内存操作，单请求网关自身开销目标 < 5ms（不含上游）。
- 数值验收标准以实测证据为准（PRD FR-4.3），不在文档预写结论。

---

## 10. 实施计划

### 10.1 M1 任务拆解（核心网关）

| # | 任务 | 依赖 |
|---|---|---|
| 1 | 脚手架：pyproject + 包结构 + 配置 schema（PRD §6 落地）+ 样例 config | - |
| 2 | **商汤双端点实测**（scripts/sensenova_probe.py，§10.2）→ 回填 PRD/预设 | 1 |
| 3 | 最小链路：openai_compat 入站（非流式）→ 调度（单资源直通）→ openai_out 出站 → 事件落盘 | 1 |
| 4 | 调度完整化：错误分类器 + 重试 m + 切换续跑 + 冷却恢复 + y 计数 | 3 |
| 5 | 流式：SSE 透传 + 延迟提交 + 首帧边界 + 心跳 + 中途失败两分支 | 4 |
| 6 | 取消透传：CancelRegistry + 断连检测 + aborted 语义 | 5 |
| 7 | Anthropic /v1/messages 入站（IR 双向转换） | 4 |
| 8 | images 端点（调度/重试/切换/取消同样适用） | 4 |
| 9 | 访问令牌 + admin 骨架 + 热重载 | 1 |
| 10 | pytest 全量 + curl/工具实测（含 test-cases.md E2E 清单） | 全部 |

> **M1 状态（2026-09-03）**：上表任务 1-10 全部完成并**验收通过**——v0.1.0：141/141 pytest + 13/13 E2E（curl 可实测项；E2E-07 Trae 实配移交用户验收、E2E-14 按用例约定以 INT-04 兜底），证据 `docs/changes/e2e-records/E2E-20260903-summary.md`；商汤端点定论 = 端点 A `token.sensenova.cn/v1`（E2E-01）。

M2（管理界面）**进行中**（Q17 五项调整已实施并留证；**Q18 五项修正已实施**：184/184 pytest，浏览器 E2E 与验收待完成）/ M3（统计看板）/ M4（增强）按 PRD §8 里程碑执行。

> **模型自动发现（PRD FR-1.4 P0）的形态分阶段说明**：M1 形态 = 任务 2 的 `/models` 拉取（脚本输出清单）+ 手动填 config.yaml + 枚举池自动匹配（matcher）；产品级「拉取 → 自动匹配推荐 → 确认入库」向导随 **M2 资源管理界面**交付。P0 功能不悬空，形态分两步落地。

### 10.2 商汤双端点实测方案（M1 首项，Q12 定论路径）

`scripts/sensenova_probe.py`（Key 从环境变量 `SENSENOVA_API_KEY` 读取，不落盘、不入日志）：

1. 端点 A：`https://token.sensenova.cn/v1`（用户答复倾向的体系，**优先**）；
2. 端点 B：`https://api.sensenova.cn/compatible-mode/v2`；
3. 对每个端点执行：
   - `GET /models`（Bearer Key）→ 记录 HTTP 状态 + 模型清单（存 `docs/changes/sensenova-models-A|B.json`）；
   - 最小 `POST /chat/completions`（model 优先取清单中的 `deepseek-v4-flash`，否则清单首个；清单获取失败时回退官方文档已知模型名）→ 记录状态 + 响应摘要；
4. 输出判定表：**以最小 chat 调用为主判据**（HTTP 200 + 合法响应 = 端点可用）；`GET /models` 为模型清单辅助判据（若 /models 异常而 chat 成功：端点可用、清单另案处理，不据此判死端点）。401/403 = Key 不属于该体系。
5. 结论回填：PRD FR-1.8、config 预设默认值、decisions.md；模型清单差异同步枚举池预置条目。

> **实测定论（2026-09-03，E2E-01/02 已执行）**：端点 A `https://token.sensenova.cn/v1` **可用**（`GET /models` 200 返回 8 模型 + 最小 chat 200），定论为商汤首发接入端点；端点 B 结果存档 `docs/changes/sensenova-models-B.json`。证据：`docs/changes/e2e-records/E2E-20260903-summary.md`。

### 10.3 M2 任务拆解（管理界面 · 含五项调整 Q17 + 五项修正 Q18 + 两项修正 Q19）

> 对应 PRD v1.4 §9-Q17（D1-D5）/ v1.5 §9-Q18 / v1.6 §9-Q19、design-spec v0.3/v0.4/v0.5、test-cases v1.1/v1.2/v1.3 新增用例（UT-24~28 / INT-39~49 / E2E-16~20）。

| # | 任务 | 内容 | 依赖 | 对应用例 |
|---|---|---|---|---|
| 1 | **模型启用开关** | `models[].enabled` 配置/校验/解析拒绝（三端点 404 `model_disabled`）+ `/v1/models` 过滤 + 热重载即时生效 + 模型映射页开关 UI（§4.7） | M1 | UT-24/25、INT-39~41、E2E-16 |
| 2 | **供应商预设注册表** | `config/presets.py` 内置三条预设 + `GET /admin/api/presets` + 资源表单预设下拉数据驱动渲染（§4.7） | M1 | UT-26、INT-46 |
| 3 | **统计维度扩展** | 事件行冗余 provider/account + `by_provider`/`by_account` 聚合 + stats 可用维度键返回（§4.8） | M1 | UT-27、INT-47 |
| 4 | **系统运行控制端点** | main.py Server 化重构（§4.10-①）+ `POST /admin/api/system/stop` / `restart`（§4.10-②） | M1 | INT-42/43、E2E-17 |
| 5 | **单实例锁** | `data/gateway.lock` 检测/登记/释放 + 启动序列集成 + 端口占用兜底（§4.10-③④⑤） | 4 | UT-28、INT-44/45、E2E-18 |
| 6 | **双击启动脚本** | 项目根 `启动网关.command`（§4.10-⑥） | 5 | E2E-19 |
| 7 | **前端六页 + Q18 重整** | 数据看板（维度 tab 数据驱动）/ 请求日志（独立页双 tab 按需加载）/ 系统设置（含系统运行控制与全局调度参数）；Q18 重整：接入管理 → **资源管理表格页**（扁平资源 + ID 自动生成 + 账号备注）、模型映射**去调度参数**、新增 **API 接入页**（端点清单 + 多密钥管理）、设置页**去令牌管理与产品管理**、前端**去令牌门** | 1/2/3/4 | E2E-16/17 |
| 8 | **Q18 后端配套** | schemas.py 扁平资源模型 + admin.py 配置读写（ID 自动生成/脱敏还原，INT-48）+ auth.py 收窄至 /v1/* + 存量 config.yaml 迁移 | M1 | INT-48 |
| 9 | **Q19 视觉重设计 + 禁缓存** | 暗色侧边栏 + SVG 图标 + 组件现代化（§4.9 视觉方案）+ `_StaticNoCacheMiddleware` 静态资源 `Cache-Control: no-cache`（§4.9） | 7 | E2E-20 |
| 10 | **Q19 资源导向映射** | 资源弹窗内配「供应商模型名 → 网关模型」映射（可就地新建网关模型，`@new-*` 占位 id，§4.9/§4.7-④）+ 网关模型页重定位为总览微调 + admin.py 占位 id 解析与引用改写 | 8 | INT-49、E2E-20 |
| 11 | **M2 回归** | 全量 pytest + 界面/脚本 E2E（E2E-16~20） | 全部 | — |

---

## 11. 确认点记录（全部已落定 · 2026-09-03 终审）

> 2026-09-03：确认点 1/2（m/y 顺序、x 语义）与推理参数需求（PRD Q15）先行落定；**同日终审确认点 3-8 全部落定（PRD v1.3 §9-Q16），本文档升级 v1.0，M1 启动**。

1. **m/y 生效顺序** → **已落定（2026-09-03）：y 先判定**——资源连续失败达 y 即冷却 + 当次请求立即切换（每资源每请求实际尝试 y=2 次）；m 为同资源重试上限（重试耗尽同样切换）。写入 §5.2，PRD §9-Q14。
2. **x 的定位** → **已落定（2026-09-03）：并发溢出生效集**——x = 同时承接流量的资源数上限；生效集内取在途最少者（平局优先级高），低负载顺序集中、并发溢出。写入 §5.3，PRD §9-Q13。
3. **管理 API 鉴权** → **已落定（终审）：复用访问令牌 + `allow_admin` 标志**（方案 A）——管理界面登录输入持有该标志的令牌（§4.1）；不设独立管理密码。【**已被 Q18-① 推翻（2026-09-03）**：管理端整体免鉴权，allow_admin 移除——自用系统不考虑管理鉴权，PRD v1.5 §9-Q18】
4. **默认参数** → **已落定（终审）**：端口 8300、SSE 心跳 15s、事件流水保留 7 天、429 退避 2 次（1s/2s 起）、**单次尝试超时 60s（原方案 120s，终审调小；思考型模型首字节慢若被误杀，实测后调回即可）**、**请求总预算 300s（原方案 600s，终审调小）**、网关并发上限默认不限、冷却 api 60s / plan 18000s、重试间隔 0。全部可配。【「多数可按模型覆盖」**已被 Q18-④ 取消**：调度参数全局唯一一套，PRD v1.5 §9-Q18】
5. **响应头延迟提交** → **已落定（终审）：接受**——重试/切换期间客户端零字节到达（开头多等几秒），换首帧前无感续跑（§4.5/§6）。
6. **请求总预算语义** → **已落定（终审）：认可语义，默认值调小为 300s**——预算只管「失败重试切换」总时长，**不管成功任务本身的执行时长**（流式输出开始后跑多久都行）；耗尽即返回统一错误（防挂起，FR-3.9）（§5.5）。
7. **failed_precondition_error 默认策略** → **已落定（终审）：默认透传 + 配置可覆写**（M1 配置层、M2 界面）——错误体无法区分「引擎不可用/安全检查/编码失败」，默认 BAD_REQUEST 透传；M1 双端点实测后观察真实错误分布，一行配置即可切换为 RETRYABLE（§4.3）。
8. **图像 URL 有效期提示** → **已落定（终审）：三处齐上**——响应体 `_gw_note.url_valid_hours` + **响应头 `X-GW-URL-Valid-Hours`** + M2 界面模型详情页（§4.4）。

> **评审通过（2026-09-03 终审）：八项全部落定，本文档升级 v1.0，M1 实施（任务 1 脚手架 + 任务 2 商汤双端点实测）启动**；实施证据按 test-cases.md §6 口径留存。

---

# 增量设计（v2.0 · 2026-09-26）

> **本节范围**：`docs/research/` 调研完成后（Q25 调研实测 / Q26 设备身份与批量运营 / Q27 ZCode 接入决策）**新增的需求落地设计**。
> **设计纪律**：§1–§11 的既有架构**不动**（M1/M2 已验收）；本节只做**增量**。每条设计都附「**为什么不做更多**」，防过度设计。
> **依据**：`docs/research/11`（总纲）/ `12`–`18`（机制详解）/ `19`（实现方案）；PRD v1.14 §9-Q25/Q26/Q27。

## 12. 能力位下发与工具侧契约（PRD Q25-②）

### 12.1 现状缺口（实测，非推断）

`/v1/models` 当前**只返回 6 个字段**（`api/openai_compat.py:39-42`）：

```json
{"id": "...", "object": "model", "created": 0, "owned_by": "model-gateway",
 "endpoint": "chat", "group": "编程"}
```

**零能力位**。工具侧实测（`08` §6.4）需要 **8 个字段**，缺了会**静默改变行为**：

| 缺失字段 | 工具的静默行为（实测） |
|---|---|
| `supportsToolCall !== true` | 工具**删除请求中的 `tools`** → 工具调用能力被剥离 |
| 无 `thinkingLevelMap` | 推理档位**变哑**（工具不再下发推理参数） |
| 无 `maxInputTokens` / `maxOutputTokens` | 工具用自己的兜底值 → 可能超上下文 |

> **这是"网关没做错什么、但工具行为被改变"的典型** —— 没有报错，只有能力静默降级。

### 12.2 字段映射（数据源**已在**，只差暴露）

| 工具要的字段 | 网关已有 | 来源 | 映射 |
|---|---|---|---|
| `maxInputTokens` | `context_window` | `enums/matcher.py` `EnumEntry` | 直映射 |
| `maxOutputTokens` | `max_output` | 同上 | 直映射 |
| `supportsImages` | `image_input` | 同上 | 直映射 |
| `supportsReasoning` | `reasoning` | 同上 | 直映射 |
| `name` | `display` | 同上 | 直映射 |
| `vendor` | `vendor` | 同上 | 直映射 |
| `caps.thinkingLevelMap` | `effort_levels` + 方言表（§13） | 目录 + 探测 | 组装（**见下 12.2a**） |
| `supportsToolCall` | 🔴 **无此字段** | — | **需新增**（见 12.3） |
| `specStale` | `ModelSpec.from_stale_cache` | `core/model_spec.py`（合并腿）→ `core/capabilities.py::build_model_caps` | ✅ **Q33 契约扩展**（2026-10-03，债务 Q33-债8 第①条）：只读位，`true` = 这条声明里**至少有一个数取自超 TTL 的目录缓存**；无合并规格参与声明 ⇒ `false`（**字段不得缺失**，缺字段时界面只能显示"不知道"）。立意：从前这个事实算得出来却没有用户可见出口，"昨天的数"与"实时的数"在界面上长得一样。判据 UT-95 + INT-93，撤证 MD-1 |

> **⚠️ 字段名以工具契约为准（camelCase），此处**修正** PRD Q25-② 的字面**：
> 实测工具契约（`08` §4.4 / §6.4）用的是 **camelCase**（`maxInputTokens` / `supportsToolCall` …），
> 且要的是 **`caps.thinkingLevelMap`** 而非顶层 `effort_levels`。
> **PRD Q25-② 的 snake_case 写法与"顶层 effort_levels"需回填修正**（已记入 §19 **M3-2** 判据）。

### 12.2a `thinkingLevelMap` 必须是 **7 键齐全**的映射（不支持显式写 `null`）

**🔴 键缺失（`undefined`）≠ `null`** —— 工具判定逻辑（`08` §4.4）：

```js
// 工具侧：v !== null && ((lv !== "xhigh" && lv !== "max") || v !== undefined)
```

对 `minimal` / `medium` 这类**非高阶档**，**键缺失会被判为"支持"** → 工具把该档发出去 → **上游静默忽略** → **正是 §12 要消灭的"静默降级"**。

**因此输出要求**：
1. **规范序 7 键必须全部出现**（`off` / `minimal` / `low` / `medium` / `high` / `xhigh` / `max`）
2. **不支持的档显式写 `null`**，**不得省略键**
3. `xhigh` / `max` 即使不支持也**必须显式出现**（`08` §4.4 明确要求）

### 12.3 实现（最小改动）

1. **`EnumEntry` 加 `tool_call: bool = False`**（唯一净新增的**目录字段**）—— 按模型族给默认值，可按模型覆写。
2. **`SystemModel` 加 `caps_overrides: dict[str, Any] = {}`** —— **默认空**，仅在"目录不准 / 探测失败"时使用（**YAML 可改，首期不做界面**，见 §14.1）。
3. **`/v1/models` 增加 8 字段输出**（在现有 6 字段基础上追加，**不删不改原有字段** → 向后兼容）。

```python
# api/openai_compat.py 增量（示意）
LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"]   # 规范序 7 档

for m in runtime.config.models:
    if not m.enabled:
        continue
    entry = runtime.enum_pool.get(m.name)          # ✅ 真实 API：EnumPool.get() → EnumEntry | None
    ov = m.caps_overrides or {}
    if entry is None:
        # ✅ 兜底：自定义网关模型（Q19-② 允许就地新建，不在内置目录）→ 最小字段集，不崩
        # 🔴 2026-10-03 Q33 债务轮改判：三个能力位在"没条目 = 不知道"时输出 **None**，不是 False。
        #    `False` 是对工具的 affirmative 承诺"这个模型干不了这件事"，而我们并没有这个证据；
        #    工具侧 `!== true` 对 null/false 处理相同 ⇒ 零回归，差别在我们不说谎。
        #    唯一仍可为 False 的是非 chat 端点的 `supportsToolCall`（图像端点没有 tools 参数，
        #    与 `EnumEntry.__post_init__` 同一条不变量）。判据 UT-86，实现 `core/capabilities.py:_flag`。
        extra = {"name": m.name, "vendor": "", "maxInputTokens": None, "maxOutputTokens": None,
                 "supportsToolCall": None, "supportsImages": None, "supportsReasoning": None,
                 "caps": {"thinkingLevelMap": {lv: None for lv in LEVELS}}}
    else:
        # ✅ effort_levels 是 list[str]（matcher.py:34）→ 正向生成映射，**不做 dict 解包**
        sup = set(entry.effort_levels or [])
        levels = {lv: (lv if lv in sup else None) for lv in LEVELS}   # 7 键齐全，不支持显式 None
        levels.update(ov.get("thinkingLevelMap") or {})
        extra = {
            "name": entry.display, "vendor": entry.vendor,
            "maxInputTokens": entry.context_window, "maxOutputTokens": entry.max_output,
            "supportsToolCall": entry.tool_call, "supportsImages": entry.image_input,
            "supportsReasoning": entry.reasoning,
            # ✅ thinkingFormat 属 L-C 方言层（§14.1），**从方言表取，不在 EnumEntry 上取**
            "caps": {"thinkingLevelMap": levels,
                     "thinkingFormat": (runtime.dialects.get(m.name) or {}).get("thinkingFormat", "")},
        }
    data.append({**base6, **extra})                # base6 = 原 6 字段，不动
```

**边界说明**：
- `caps` 是**本次新增的「组装结果」**，`EnumEntry` **无** `caps` 字段（勿误引）
- **目录缺某属性时输出 `null`**（如 `claude-sonnet-4` 无 `context_window`）→ 工具回退自身兜底值，**与现状等价，不臆造数值**
- **`caps_overrides` 与既有 `params` 职责正交**：`params` 是**采样参数**（经 `ir.apply_model_params` 注入出站请求体）；`caps_overrides` 是**能力声明**（只影响 `/v1/models` 输出）—— 勿混用

> **为什么不做更多**：
> - ❌ **不做**"每个模型手填能力位" —— 数据已在内置目录（`enums/matcher.py:67-140`），手填是重复劳动且必然漂移
> - ❌ **不做**"能力位查询接口" —— 工具读 `/v1/models` 就够了
> - ❌ **不做**"能力位版本协商" —— 无需求，且会引入协议复杂度

### 12.4 🔴 两条下发路径**都要做**（PRD Q25-⑨，此前设计遗漏）

> **⚠️ 本节是审核补入的** —— 原 §12 只做了**路径 B（API）**，但**实测 WorkBuddy CLI 只读文件、不调 `/v1/models`**（`08` §6.5）→ **按原方案实施，首期对 WorkBuddy 无效**。

| 路径 | 机制 | 适用工具 | 实测状态 |
|---|---|---|---|
| **A · 文件下发** | `mgw setup` 生成 `models.json`，写入工具的数据目录 | **WorkBuddy CLI**（只读文件） | ✅ **已验证**（`08` §6.5） |
| **B · API 下发** | `/v1/models` 返回能力位（§12.2/12.3） | 读 API 的工具 | ⏳ 待验证 |

#### 12.4.1 路径 A：`mgw setup` 的目录解析规则（PRD Q25-⑨）

**目标目录解析**（按优先级）：

```
1. 环境变量 WORKBUDDY_CONFIG_DIR / CODEBUDDY_CONFIG_DIR        ← 🔴 最高优先级
2. product.config.customUserDataDir
3. 🔴 按「产品标识 → dataFolderName」解析：
      workbuddy      → .workbuddy        （WorkBuddy）
      workbuddy-ai   → .workbuddy-ai     （WorkBuddy AI）
   → 即 ~/.<dataFolderName>/
```

> 🔴 **不得使用 `productName` 的子串判断**（如 `"workbuddy" in productName`）——
> **实测其实现为 `includes("workbuddy")`，对 WorkBuddy 与 WorkBuddy AI 两个产品均返回 true**，
> **永远推不出 `.workbuddy-ai`**。PRD Q25-⑨（`prd.md:592`）**明文禁止**此写法。
>
> ⚠️ **这条修正本身曾出错**（第三轮复核发现）：原稿写的就是被禁的子串判断，
> 且 `dataFolderName` 在全文零命中 —— 与本设计自己记录的踩坑目录（`/Users/w/.workbuddy-ai`）**自相矛盾**。

> 🔴 **踩坑记录**（`08` §5 O2）：本机 `WORKBUDDY_CONFIG_DIR=/Users/w/.workbuddy-ai` 由**另一个产品注入**，
> 导致从 `/Applications/WorkBuddy.app` 取的 CLI **跑到了 WorkBuddy AI 的目录**。
> **判别方法：不要只看日志里的 `productName`，要看 `userConfigPath` 的实际路径。**

**文件格式**（两种并存，**不可混用**）：

| 消费者 | 格式 | 裸数组 |
|---|---|---|
| GUI | `[...]` 裸数组 | ✅ |
| **CLI** | `{"models": [...], "availableModels": [...]}` | ❌ **解析器直接丢弃裸数组** |

**写入纪律（必守）**：

**0. 🔴 写前打印解析结果并等待确认**（审核补入 —— 设计自己记录了该路径**曾被环境变量劫持**）：

```
目标目录：/Users/w/.workbuddy-ai    （来源：环境变量 WORKBUDDY_CONFIG_DIR）
将写入：models.json（合并 3 条已有条目）
继续？[y/N]
```

- 交互式需回车确认；**非交互需 `--yes`**；**`--dry-run` 只打印不写**
- 写完打印：`已写入 <绝对路径>；原文件备份为 models.json.bak-<ts>`
- 失败打印：`写入失败，已从备份回滚：<原因>`

**1.** **写入前先备份**已有文件为 `models.json.bak-<ts>`（实测发生过原文件被清空的事故，`08` §5 O2；该文件存在**外部并发写**）
**2.** **合并而非覆盖**（保留用户已有条目）
**3.** **原子写**：同目录 tempfile + `os.replace`（与 `admin.py:404-412` 既有纪律同口径）
**4.** 写入后**读回校验**；失败用备份回滚

**实现**：`mgw setup <tool>`。

> 🔴 **审核修正**：原稿写「复用**已有** CLI 形态」—— **事实错误**。项目当前**没有任何命令入口**：
> `pyproject.toml` **无 `[project.scripts]`**，只能 `python -m model_gateway.main`（`research/04:134` 原文确认）。
> **因此需先新建 `mgw` 入口**（见 §19 **M3-0**），本节的 `mgw setup` 依赖它。

#### 12.4.2 路径 B：API 下发

即 §12.2 / §12.3（`/v1/models` 补 8 字段）。

> **为什么不做更多**：❌ **不做**"自动探测工具安装位置并静默改写其配置" —— 写别人的数据目录是**破坏性操作**，
> 必须**显式命令 + 备份 + 读回校验**。

---

## 13. 参数归一化与方言表（PRD Q25-③④⑤）

### 13.1 规范档位序（7 档，**开放可扩展**）

```
off < minimal < low < medium < high < xhigh < max
```

**🔴 规范外档位原样透传、不报错** —— 实测 `deepseek-v4-pro` 返回的合法值含 **`ultra`**（超出 7 档序）。网关**不得**因档位不在规范序内而拒绝。

**`ultra` 的归属裁决**（审核补入，防与 §12.2a 的 7 键封闭冲突）：

| 路径 | `ultra` 如何处理 |
|---|---|
| **声明式路径**（`/v1/models` 的 `thinkingLevelMap`） | **不新增键** —— 键**固定为 7 个规范档**。若该供应商通道的 `max` 真实值就是 `ultra`，则写成 `{"max": "ultra"}`（**作为 `max` 的映射值**） |
| **入站透传路径**（客户端直接发 `ultra`） | **原样放行**，不报错 |

> **理由**：工具侧的档位枚举只遍历那 7 个键（`08` §4.4）→ 新增第 8 个键**工具看不到**，是无效声明。
> **规范外档位不进入声明式档位表。**

### 13.2 降级分两层（**不得叠加**）

| 层 | 职责 | 规则 |
|---|---|---|
| **工具层** | 工具自己 clamp | 就近取值，**优先向上** |
| **网关层** | 兜底 | **只降不升**；**工具已 clamp 时网关不得二次 clamp** |

> **为什么不做更多**：❌ **不做**"网关内建完整档位映射引擎" —— 工具已有 clamp 引擎（`08` 实测），网关只需**兜底 + 透传**。

### 13.3 `mgw probe` 三步探测（**S2 只验单一锚点**）

| 步 | 动作 | 产出 |
|---|---|---|
| **S1** | 发非法值触发 400，从**错误文案**抠出值域 | 候选值域 |
| **S2** | **只发 `none`/`off` 类关闭值**，与基线比 `reasoning_tokens`：**归零 → 确认该写入位生效**；非归零 → 判为假方言丢弃 | **真写入位** |
| **S3** | 定档：值域 ∩ 规范序（规范外保留） | 方言表 |

**🔴 为什么 S2 不能省**（实测，`08` §九）：

```
reasoning.effort = "bogus"（非法值） → HTTP 200，且 reasoning_tokens 与基线无异
thinking.type = "enabled"            → HTTP 200，同样与基线无异
```

**即：非法值也返回 200 —— 上游"忽略"了它，而非"接受"了它。**
只做「200/400 二分」会把**被忽略的字段误判成支持的写法**。

**🔴 为什么 S2 只验 `none` 单锚点，不逐档比数值**（审核修正）：

实测**同模型同题**的 `reasoning_tokens` 波动为 **22 / 23 / 38 / 43 / 61**（`08` §九）——
**逐档比数值在 n=1 时必然误判**（如拿 `high`=23 与基线=43 比会得出"未生效"的错误结论）。
而 `none` → **0** 与 22–61 **无重叠区间**，是唯一可靠的锚点，**单次采样即可**。

> **因此不做**「多次采样 + 阈值调参」—— 那正是过度设计。

**🔴 CLI 交互契约（审核补入 —— 长耗时且会触发频控，不能没有反馈）**：

```
$ mgw probe [--model <name> | --all]
将探测 N 个模型，预计 M 次请求（可能触发上游频控），继续？[y/N]

✓ glm-5.2        → 写入位 reasoning_effort（档位 none/minimal/…/max）
✗ kimi-k3        → 探测失败，保留硬编码 fallback

完成：成功 N 个，失败 M 个（方言表已写入 data/dialects.json）
```

- **默认探测范围**：当前**启用且尚无方言记录**的模型（避免重复探测）
- 逐个模型**即时打印**结果（长任务不能等结束才输出）
- 结束打印成功/失败计数 + 落盘路径

> **这是本次调研推翻自己原设计的唯一一处** —— 原设计"二分探测"有缺陷，已改为三步 + 单锚点。

### 13.4 方言表缓存与探测纪律

- 结果落 `data/dialects.json`（**探测结果优先，硬编码作 fallback**）
- **必须串行 + 间隔 + 退避**：实测探测中约 **1/3 请求触发 429**
- 探测失败 → 才允许手填（L-C 层，见 §14）

**🔴 加载时机（审核补入，否则"探测完了不生效"）**：

| 时机 | 行为 |
|---|---|
| 进程启动 | **加载一次**进内存快照（`runtime.dialects`） |
| `mgw probe` 写完文件后 | **显式触发一次重载**（复用现有 `runtime.reload_from_file()` 或新增 `reload_dialects()`） |
| 其他 | **不新增 mtime 轮询** —— 现有热重载只监听 `config.yaml`（`main.py:244`），**不为方言表加第二个 watcher** |

> **为什么不做更多**：❌ **不做**"启动时全量探测所有模型" —— 慢且触发频控；探测**按需触发 + 缓存**。
> ❌ **不做**方言表的独立文件监听 —— 一个显式重载调用即可，加 watcher 是过度设计。

**探测的可测试性**：探测函数签名接受可注入的 `call_fn`（默认走真实 adapter），
单测注入"按请求体返回 400 / 200 + 指定 `reasoning_tokens`"的假序列 → **S1/S2/S3 可确定性验证**（这是 M3-3 能进 CI 的前提）。

---

## 14. 配置三层与账号存储（PRD Q25-⑥ / Q27-⑤）

### 14.1 配置三层（**用户层不新增设置项**）

| 层 | 内容 | 谁填 | 现状 |
|---|---|---|---|
| **L-A 用户层** | `enabled` / `endpoint` / `group` / `resources[]` / `params{}` | **用户** | 已有（**不新增**） |
| **L-B 目录层** | `context_window` / `max_output` / `image_input` / `reasoning` / `effort_levels` / `display` / `vendor` / `tool_call` | **内置目录自动带入** | 数据已在，只差暴露 |
| **L-C 方言层** | `thinkingLevelMap` / `thinkingFormat` / `maxTokensField` | **探测自动得出**（§13.3），失败才手填 | 新增 |

**唯一净新增 = `SystemModel.caps_overrides` 配置字段**（**YAML 可改**，供目录/探测不准时覆盖）。

> **⚠️ 审核修正**：原稿写「UI 唯一净新增 = 默认折叠的『高级 · 能力覆盖』」，与 §20 #12「首期不做 UI」**直接冲突**，
> 且撞 PRD Q25-⑩「**不做** L-B/L-C 的用户录入界面」。
> **裁决：保留字段、砍掉界面** —— 首期通过 YAML 手改 `caps_overrides`；界面随二期前端补。

**`caps_overrides` 的 YAML 形状（审核补入 —— 它是首个"没有界面表面"的 `SystemModel` 字段）**：

```yaml
models:
  - name: glm-5.2
    resources: [...]
    caps_overrides:                    # 默认空；仅在目录不准 / 探测失败时填
      thinkingLevelMap:
        max: ultra                     # 把该供应商通道的 max 映射到 ultra（§13.1）
        minimal: null                  # 显式声明"不支持"（不得省略键，§12.2a）
      thinkingFormat: openai           # 覆盖探测得出的方言族
```

> 改后由**既有 mtime 热重载**生效（`design-spec.md:104`：界面与文件双向一致 + 文件外部修改经 1s 轮询热重载）——
> **本项目既有范式，手改文件是受支持路径**，不违背交互约定。

> ⚠️ **PRD 需回填（第三轮复核发现）**：PRD Q25-①（`prd.md:567`）仍写「**UI 仅新增默认折叠的「高级 · 能力覆盖」**」，
> 与本设计的「**保留字段、砍掉界面**」裁决不一致 → **PRD Q25-① 的 UI 部分需回填修正**（与 Q25-② 的字段名回填同类）。

### 14.2 账号存储：**不建统一表**（Q27-⑤ 用户决策）

用户明确答复：

> **「建议初期先独立开。后面接入多个产品运行有必要合并的话再合并」**

**因此本设计**：

| 做 | 不做 |
|---|---|
| ✅ `Resource` **加一列** `product: str = ""`（默认空 = 旧行为，**向后兼容**） | ❌ **不做** `products` / `accounts` / `credentials` / `runtime_state` 四表 |
| ✅ 各产品的账号与凭据**各自独立实现** | ❌ **不做**跨产品统一账号抽象 |
| ✅ 接口层预留"可提升为公共层"的可能 | ❌ **不实现**该提升 |

> **为什么不做更多（这是本设计最重要的一条克制）**：
> 当前**只有 ZCode 一个产品**需要 OAuth 账号管理。为 **1 个产品**建 4 张通用表 + 迁移脚本 + 双读期
> —— 这是**教科书级的过度设计**。等真的有第 2、3 个产品且形态一致时再抽象，成本更低（那时才知道共性在哪）。

---

## 15. 设备身份（per-product 独立，PRD Q26-① / Q27-⑤）

### 15.1 三条硬约束（用户需求 ①，**不可妥协**）

| # | 约束 | 机制 |
|---|---|---|
| **1** | **不允许两个账号绑定到同一设备 ID** | **生成新账号时**：生成 → 查唯一性 → 冲突则重新生成（有上限，**不静默降级**）；<br>**导入已有账号时**：查唯一性 → 冲突则**拒绝 + 交用户决策**（见下） |
| **2** | **导入已有账号缓存 → 复用原设备 ID** | 缓存内已有设备标识 → **原样复用，绝不重新生成** |
| **3** | **冲突 → 拒绝 + 报由用户决策** | **不自动替换** —— 自动换 = 让已登录账号在上游眼里"换设备" → **反而触发风控** |

> **🔴 两条路径的差别（第三轮复核发现口径未对齐，此处显式裁决）**：
> **「重新生成」只适用于生成新账号**（此时新设备 ID 无上游历史，重生成无副作用）；
> **导入路径一律「拒绝 + 交用户决策」** —— 因为缓存里的设备 ID **已有上游登录历史**，自动替换等于替用户做危险决定。
> §15.2 的 `check_device_id_unique` 是**共用**的唯一性校验函数，**生成/导入两条路径的后续处置不同**。

**🔴 硬约束 3 的交互契约（审核补入 —— 原稿只说"报由用户决策"，未定义报什么/怎么决策）**：

冲突时**不写盘**，打印并给三个显式选项：

```
设备 ID 冲突：账号「X」的 device_id 已被账号「Y」占用。
可选：
  ① --reuse Y        复用 Y 的设备 ID（两者共享设备，上游可能风控）
  ② --regenerate     为 X 生成新 ID（上游会视为换设备）
  ③ 取消（默认）
```

**默认行为 = 取消，退出码非 0** —— 不替用户做危险决定。

> ⚠️ **与 §15.2 的口径统一（第三轮复核后修正）**：
> §15.2 的 `ensure_device_id` **仅用于「生成新账号」路径**；`check_device_id_unique` 是**共用**校验函数。
> **导入路径**明确为「**拒绝 + 交用户决策**」，不自动生成。两条路径的差别见 §15.1 上表下的裁决说明。

### 15.2 实现落点（**不做抽象层** —— 审核修正）

> **⚠️ 审核修正**：原稿定义了 `class DeviceIdentity(Protocol)` 与 `upstream/base.py 产品适配器接口`，
> 但当前**只有 ZCode 一个实现** → 为 1 个实现建抽象层，**正是用户点名要避免的"为 1 个场景建通用框架"**，
> 且与 §20 #14「不预先抽象成公共层」**自相矛盾**。
>
> **裁决：删掉这两个抽象**，函数**直接落 `upstream/zcode/dataroot.py`**：

```python
# upstream/zcode/dataroot.py（普通函数，不做 Protocol）
def ensure_device_id(account_dir: Path) -> str:
    """取该账号的设备 ID；不存在则生成。**生成一次后永不重算。**

    注：仅用于「生成新账号」路径 —— 导入路径见 §15.1 硬约束 3（拒绝 + 交用户决策，不自动生成）。
    """

def check_device_id_unique(accounts_root: Path, device_id: str) -> bool:
    """跨账号唯一性校验（硬约束 1）。

    本函数**只做校验、不做处置** —— 两条调用路径的处置不同（§15.1）：
      · 生成新账号：冲突 → 重新生成（有上限）
      · 导入已有账号：冲突 → **拒绝 + 交用户决策**（不自动重生成）
    """
```

等真有第 2 个产品（trae/qoder 类）时**再**抽象（那时才知道共性在哪）。

### 15.3 ZCode 实现：**整根隔离**（详见 `19` §6.1）

`ZCODE_DATA_BASE_DIR`（数据根）+ `ZCODE_DESKTOP_{USER_DATA,SESSION_DATA,HOME}_DIR`（三件套）+ `--device-id` + `telemetry-state.json`（双通道）。

**⚠️ 两个必须内联的 caveat（审核补入）**：

| # | caveat | 依据 |
|---|---|---|
| 1 | **三个 `ZCODE_DESKTOP_*` 是否真的覆盖客户端 `app.setPath` —— 本机未实测** | `17` §⑩ #5（仅凭面板注释判断）→ 已补进 §19 待实测清单 |
| 2 | **ZCode 内置浏览器 session 跨账号共用** —— 客户端用 `app.setPath` 覆盖，命令行 `--user-data-dir` 无效 → **已知例外，首期接受** | `17` §③ |

> **因此**：整根隔离能保证的是「**凭据 / 配置 / 日志 / 遥测 / provider_config 进账号目录**」，
> **不能**保证「主目录零写入」—— `setting.json` 是**已知例外**（客户端固定写主 `~/.zcode/v2/`）。
> 判据已按此改写（见 §19 M4-2）。

> **为什么不做更多**：
> - ❌ **不做**统一 Device Registry（Q27-⑤ + 只有 1 个产品需要）
> - ❌ **不做**"**ZCode 的**设备画像随机化（品牌/系统版本）" —— ZCode 的设备身份**只有 `--device-id` + 数据根，无 persona 字段**；参考项目也都没随机化
> - ✅ **只做**参考项目缺的那一条：**跨账号唯一性校验**（`ZCode-Panel` 只校验 UUID 格式、不查重）
>
> **⚠️ 措辞限定（审核修正）**：PRD Q26-① 要求新账号「生成**一整套全新自洽画像**」（含品牌/系统版本）——
> 该要求适用于 **trae / qoder / lobsterai 类有 persona 字段的产品**（`10` D10 per-product 字段字典保留），
> **ZCode 不涉及**。原稿 §20 #8 的"不做画像随机化"是**全局措辞**，会与 Q26-① 冲突 → 已限定为"ZCode 首期"。

---

## 16. 运营操作模块（PRD Q26-② / Q27-④）

### 16.1 定位：与核心调度**解耦**

运营接口（签到/领礼包）是**产品专属业务接口**，**不是 OpenAI 兼容 API 的组成部分**。

**因此**：独立 `model_gateway/ops/` 模块，**不进 `core/scheduler.py`**、**不进 `Resource` 主流程**。

> ⚠️ 它**不违反铁律 1**（本地主动发起的出站请求，与调模型接口性质相同），但**扩大网关职责边界**（从"模型转发"到"账号运营"）→ 已在 PRD v1.14 Q27-④ 显式归档。

### 16.2 四类结果（**只有 `failed` 需用户关注**）

| 类别 | 含义 | 需关注 |
|---|---|---|
| `success` | 本次真的成功 | 否 |
| `already_done` | 幂等命中（已签到/已领取） | 否 —— **是正常业务状态** |
| `inactive` | 无资格 / 活动结束 | 否 —— 正常业务状态 |
| `failed` | 真的出错 | ✅ **是** |

**🔴 CLI 呈现约定（审核补入 —— 四类混排会稀释注意力）**：

```
$ mgw zcode claim
✓ 已领取 3 个
– 跳过 2 个（已领过 1 / 无资格 1）
✗ 失败 1 个：acct-b  验证码求解超时

全部正常，无需处理          ← 无失败时输出这一行
```

- **只有 `✗` 行着色**（`--err`）
- `already_done` / `inactive` 归入"跳过"一行，**不与失败混排**

### 16.3 三条硬教训（必须继承，每条都对应参考项目踩过的真实缺陷）

1. **状态接口用错会得到"看似合理的假数据"** —— 必须确认哪个是权威状态源
2. **幂等看响应体 `code`，不看 HTTP 状态** —— ⚠️ **幂等码必须按产品分表**（审核修正）：
   - **ZCode**：`1003`（该套餐已领取过）/ `1005`（今日名额已用完，回带 `next_at`）→ `already_done` / `inactive`
   - **buddy / DSH**：`10001`（"今天已签到"）
   > 原稿把 **buddy 的 `10001`** 当作通用判据，照此实现 ZCode 的 `already_done` **会判错**。
   > **判错的后果**：把"已领过"当成失败 → 重试 → **触发频控**（正是教训 2 要防的）
3. **停用账号不参与运营，但续期不看 `enabled`** —— 这两个是**独立开关**。合并会导致停用账号的 `refresh_token` 过期后**无法自动恢复**

### 16.4 执行策略

| 策略 | 内容 |
|---|---|
| **并发** | **串行 + 间隔 + 随机抖动** |
| **🔴 双层互斥**（PRD Q27-④ 明确要求） | **plan 级 `TryLock`**（拿不到直接跳过本 tick，不排队）+ **账号级 `claimLockFor`**（防 **CLI / 管理端点手动**与 cron 并发双领） |
| **失败隔离** | **逐账号失败隔离**，单账号失败不中断其余 |
| **重试** | **仅网络类 / 5xx 退避重试**；**业务码不重试**（幂等语义下重试业务错误无意义） |
| **空跑语义** | 分两种情形（**勿混**）：① **有账号参与但全部无需动作** → 记 `success`（避免 N/N 误报 failed）；② **无账号参与（`N=0`）** → 记 **`inactive`** 并输出「无账号参与」（**不得报 `success`**） |
| **参与范围** | 运营类**跳过 `enabled=false` 账号**；续期类**不看 `enabled`**（两个独立开关，§16.3 教训 3） |
| **能力声明** | **per-operation 声明 `supported_products`**（不同产品支持的动作不同，不按产品整体开关） |

> **⚠️ 审核补入**：原稿漏了「**双层互斥**」，而 PRD Q27-④ 明确要求（`prd.md:681`）。
> **缺互斥的后果**：cron 分钟 tick 与手动触发重叠会**重复 `claim`** → 正是 §16.3 教训 2 警告的"触发频控"同一类风险。

### 16.5 验证码求解（PRD Q27-① 已接受；**审核补入**）

签到/领取的**第 2 步强制阿里云无痕验证码**（`14` §③）。用户已明确接受（Q27-① 第 3 项）。

| 项 | 方案 | 依据 |
|---|---|---|
| 实现 | **Playwright `async_api`**（与 `zcode2api` 同栈，可复用其求解逻辑） | `19` §6.5 |
| **进程模型** | **同进程** + `asyncio.Lock` **串行**（照参考实现 `captcha.py:116,159`） | 审核补入 |
| **超时** | 每次求解 `asyncio.wait_for(..., timeout=30s)` | 审核补入 |
| **浏览器生命周期** | **进程级复用**，退出时 `aclose()` | 审核补入 |
| 缓存 | TTL 45s + 宽限期后台刷新 | `14` §⑦ |
| 🔴 **硬依赖** | **住宅代理**（数据中心 IP 会被风控 `F001` 拒绝） | `19` §6.5 / `11` R8 |
| **隔离手段** | `ops/runner` 调用点用 `try/except (TimeoutError, PlaywrightError)` 包住 → 记 `failed`，**不 re-raise** | 审核补入 |

**🔴 用户侧落点（审核补入 —— 原稿只在文档内披露依赖，用户侧零落点）**：

| 项 | 落点 |
|---|---|
| 配置项 | `config.yaml` 的 `gateway.zcode.proxy`（无则回退环境变量 `MGW_ZCODE_PROXY`） |
| **未配置时** | **不静默失败** —— 直接提示：<br>`未配置住宅代理，验证码求解不可用。`<br>`请在「系统设置」或 config.yaml 的 gateway.zcode.proxy 填入住宅代理地址；也可 --manual 手动完成。` |
| 手动兜底 | `--manual` 由用户手动过验证码 |

> 🔴 **外部依赖必须显式披露（审核要求）**：**住宅代理需外购/额外部署**，是**成本与部署门槛**，
> 不是纯代码工作。§19 M5-1 的交付判据已据此改写（含"无住宅代理时的降级行为"）。
>
> **备选**（若不愿引入住宅代理）：§20 已列一条"首期不做验证码求解，领取降级为手动" ——
> **二者必居其一，不能悬空**。默认走"引入住宅代理"，因为 Q27-④ 明确"要签到和领取能力"。

### 16.6 模块归属（**审核澄清**，消除 §17 与 `19` D27 的落点冲突）

| 职责 | 落点 | 说明 |
|---|---|---|
| **HTTP 交互**（preview / claim / 事件上报 / 验证码求解） | `upstream/zcode/claim.py` | 产品专属接口，与 `upstream/zcode/` 其余模块同层 |
| **调度与结果分类**（cron / 互斥 / 抖动 / 隔离 / 四类结果） | `ops/runner.py` | **薄适配器**：调用 upstream 的 HTTP 交互，不自己发请求 |

> **边界一句话**：**`upstream/` 负责"怎么调上游"，`ops/` 负责"什么时候调、怎么批量、结果怎么归类"。**

**🔴 硬边界（审核补入，否则实现者会顺手用错）**：

| 约束 | 原因 |
|---|---|
| `ops/` **不 import** `core/scheduler` | 避免复用其重试/冷却/C 计数语义（那是"模型转发"的） |
| `ops/` **不 import** `core/errors.ErrorClassifier` | ⚠️ **`errors.py` 会把 ZCode 的 `HTTP 400 + code 1003` 判成 `BAD_REQUEST`** → 与 §16.3 教训 2 直接冲突 |
| 退避逻辑 | 自建 6 行小函数（**不共用**调度状态）；退避序列 `[500, 1500, 4000]ms`（`14` §⑦） |

**🔴 结果出口（审核补入 —— 原稿四类结果**没有任何用户可见出口**，cron 后台失败会静默）**：

| 出口 | 内容 |
|---|---|
| **落盘** | 每 tick 写 `data/ops-results-<date>.jsonl`（与既有 `data/usage/events-*.jsonl` 同形态） |
| **`mgw zcode claim`** | 直接打印（呈现见 §16.2） |
| **后台 tick 的 `failed`** | 累计进 `/admin/api/status`（**顶栏 5s 轮询已在跑**）→ 有未读失败时**顶栏状态区显示红点** |

> **不新建页面、不新建轮询** —— 复用既有顶栏轮询与 JSONL 形态。
> **⚠️ 「空跑」的两情形（措辞统一）**：`len(accounts)==0` 时**不得报 `success`** —— 应记为 `inactive` 并输出「无账号参与」（否则 0 账号会被误报成成功，是新的静默路径）。与 §16.4 的空跑语义一致。

> **为什么不做更多**：
> - ❌ **不做**并发执行 —— 实测批量操作更敏感（探测阶段已有 1/3 触发 429）
> - ❌ **不做**通用"运营 DSL" —— 每个产品的接口形态不同，硬编码适配器更简单可靠
> - ✅ **只做**首批 2 个 operation：`zcode_claim` / `query_balance`
>
> **⚠️ operation 命名（审核修正）**：原稿写 `daily_checkin`，**暗示存在"签到端点"** —— 但实测
> **ZCode 没有传统意义的"每日签到"端点**（`14` §①）：所谓签到 = `billing/claim`（`period=daily`）
> **+** `event/report` 上报 `app_daily_active` **两件事合成**。
> → operation 名改为 **`zcode_claim`**（与 `19` D27 的落点 `zcode_claim.py` 对齐）。

---

## 17. ZCode 上游接入（PRD Q27）

**完整方案见 `docs/research/19-ZCode接入实现方案.md`**，此处只固化**架构落点**：

```
model_gateway/
├── adapters/anthropic_out.py    ← §18（P0，从空壳到实现）
├── upstream/                    🆕 上游产品接入层（与核心调度解耦）
│   └── zcode/                   ZCode 产品实现（**首期只有这一个产品 → 不做 base.py 抽象**，§15.2）
│       ├── __init__.py
│       ├── crypto.py            enc:v1 加解密
│       ├── oauth.py             OAuth 双流程 + refresh（移植 RE 实现）
│       ├── account.py           账号模型 + 列表管理
│       ├── dataroot.py          整根隔离：数据根 + 启动 + 设备 ID（§15.2/15.3）
│       ├── quota.py             额度三通道 + 3012 熔断
│       ├── claim.py             签到/领取（HTTP 交互，§16.6）
│       └── auth.py              双通道鉴权 + TLS 指纹
└── ops/                         🆕 运营调度（薄适配器，§16.6）
    ├── __init__.py
    ├── runner.py                批量执行器：cron + 双层互斥 + 抖动 + 隔离 + 四类结果
    └── builtin/                 首批 operation：zcode_claim / query_balance
```

**关键决策**（依据 `19` §六）：

| 项 | 决策 | 依据 |
|---|---|---|
| 免费额度通道 | **双通道都实现**（API Key + Plan） | Q27-② 用户"都需要" |
| 额度数据源优先级（🔴 **2026-10-02 v2.1 改述，推翻本行原「客户端日志优先（绕开签名风控）→ 联网兜底」**） | **联网腿 = 额度唯一实时源**（`upstream/zcode/billing.py::fetch_balance` ← `upstream/zcode/product.py::quota`）；**客户端日志面降为「离线聚合面」**（`quota.py::read_account_snapshot`，只服务 `/admin/api/zcode/quota` 的聚合与管理端点的启动种，**不再是额度的真相来源**） | 【探针台账】§2/§3/§5（16/16 号 `GET /billing/balance` 全 200/code=0）+ 代码 `product.py:520-609`、`billing.py:163-181`、`quota.py:284-291`；详见下方「额度数据源的定版改述」 |
| 熔断 | 3012 风控 → **全局熔断 30 分钟**，状态落盘；🔴 **10s 节流只作用于领取腿与探活腿，不作用于额度腿**（2026-10-02 明写，见下方「额度腿的节奏」） | `18` §③ + 【探针台账】§7.3 |
| 鉴权 | 双通道 + **三级降级链**（JWT+验证码 → JWT 直连 → API Key） | `15` §⑧ |
| TLS 指纹 | `curl_cffi`（Python 侧） | `15` §⑦，**待实测 T5a/T5b** |
| **并发租约（范围限定，审核修正）** | **模型转发路径**复用现有 `pick_and_acquire`；**额度查询 / 领取路径**复用**自建互斥**（§16.4 双层互斥 + 30min 熔断；**额度腿不吃 10s 节流**，其节奏归 ops tick / `run_once` 的 1.2s 逐号间隔） | `16` §④ + `19` §六 + `ops/runner.py:39,415-416` |

**🔴 额度数据源的定版改述（2026-10-02 v2.1 · 方案 `20261002-zcode-quota-and-refresh.md` §9-2 第 1/4 条）**

> 上面表格原行「**客户端日志优先**（绕开签名风控）→ 联网兜底」**已被实测推翻并就地改述**：
> 网关对 zcode 额度"一直没有数据"的**真因不是联网被风控挡住，而是根本没有联网腿**。

- **联网腿 = 额度的唯一实时源**：`upstream/zcode/billing.py::fetch_balance`（`billing.py:163-181`，
  本模块唯一 HTTP 落点是 `_http_get_balance`，`billing.py:87-100`）← `upstream/zcode/product.py::quota`
  （`product.py:520-611`，`billing.fetch_balance` 全仓**唯一调用方**在 `product.py:568`）。
  实测 = 16/16 在册账号 `GET /billing/balance` 全部 **HTTP 200 / code=0 / 单请求 ≈0.1s**，其中 **6 号当场给出真实 token 数值**
  （含 1 号 `available_units=0` 的自然耗尽），10 号是 `code=0` 的空数组 —— 【探针台账】
  `docs/changes/e2e-records/E2E-20261002-zcode-quota-probe.md` §2 / §3 / §6.1–§6.3。
  ⚠️ 同一路径还有**第二个调用点 = 探活腿**（`product.py:437-442` + `PROBE_PATH = "/billing/balance"`，
  `product.py:66`），它只回答"凭据有效吗"、**不产出额度数值** ⇒ 额度的实时源仍只有上面那一条。
- **客户端日志面降为「离线聚合面」**：`quota.py::read_account_snapshot`（`quota.py:279-315`，
  函数 docstring 里的"离线面"定位改述已在码内，`quota.py:284-291`），服务两件事 ——
  管理端点 `GET /admin/api/zcode/quota` 的聚合（`api/admin.py:456-466`）与**启动种**
  （`main.py:230` → `main.py:70-85 refresh_quotas`）。它**不是**额度的真相来源。
- **形状事实（两条通道形状不同，别按实现倒推）**：网络响应体顶层就是
  `{code, msg, data:{server_time, plans, balances}, logid}`、**无 `payload` 包** ⇒
  `normalize_remote` 读 `body["data"]` 对本通道本来就对（`quota.py:220-227`，**不改**）；
  少解一层 `payload` 这个 bug **只存在于日志通道**，剥层器 `_unwrap_log_record`（`quota.py:129-148`）
  只加在日志侧的两个应用点（过滤腿 `quota.py:185`、取快照腿 `quota.py:260`）。
  台账原据 = 【探针台账】§4 表首行 + §6.4（📌 该文件 §6.4 与码内注释指向的「§7.1」在 r5 修订「删重复 §7」后
  **已不存在** = 悬空引用，登记在文末偏差清单）。
- 🔴 **范围声明（这条结论只覆盖到哪儿，禁止越界引用）**：证伪的**只是**旧注释里
  「`GET /billing/balance` 需要 `X-Client-Sig/Nonce/Pow` 私钥握手 + PoW、**脚本无法复刻**」这一句，
  且**仅测了这条只读 GET**（【探针台账】§5 明写未证明：`/v1/chat/completions` 一类的**推理面**是否需要
  签名/captcha、是否回 405/3012 —— **未测**；Monitor 通道已被裁决④ 从设计里删除，本轮 4 号 ×3 路径全 404）。
  ⇒ 本节任何措辞都**不得**被读成"zcode 直连已打通 / D1 已解决"；D1 的其余子问题在 §22.11 仍是**待实测**。
- ⚠️ **凭据只能经公共层 `store.hook_meta("zcode", name)` 组装**（【探针台账】§5.1：16/16 号顶层
  **没有 `credentials.json`**、`meta.json` 无 `dir`/`account` ⇒ 自己拼目录 = 16/16 空 jwt）。
  任何"第四份自己拼路径"的写法在这里都会静默变成"额度永远未知"（`product.py:520-547` 的 `_identity_of`）。

**离线面的如实登记（同一批改述的第 4 条：两 call site / 一写入函数 / 一条已知限制）**

| 项 | 事实（以代码为准） |
|---|---|
| 离线面 call site | **两个**：`api/admin.py:462`（`zq.refresh_runtime_quotas`，管理端点顺带回写）· `main.py:230`（启动腿 `refresh_quotas`）—— 两者都经 `quota.py:338-359 refresh_runtime_quotas` |
| 写入函数 | **一个**：`quota.py:362-401 apply_remaining_to_runtime` —— 离线腿（`apply_snapshot_to_runtime`，`quota.py:404-410`）与**联网腿**（`ops/builtin/query_balance.py:115`，经 `_POOL_APPLYERS = {"zcode": _apply_zcode_quota}`，`query_balance.py:121`）都收敛到它，**不留第二份"写池 + 余量 0 则 bench"** |
| 今天为什么不冲突 | 本机实况 = 网关账号根内**没有任何 `.log`**（`find coding/data/upstream/zcode/accounts -name '*.log'` → **0**，在册 16 号）⇒ `read_account_snapshot` 对 16 号**恒 `ok=False`**（`quota.py:302-315`，与"剥层修没修"无关）⇒ 离线腿今天**一次都不写** |
| 🔴 **已知限制（主动登记，本轮不修）** | **一旦日志出现**，离线腿会把日志算出的余量**无条件覆盖**联网腿刚写的值：`apply_remaining_to_runtime` 只判 `remaining is None`（`quota.py:386-397`，即"**有没有数**"），**既不比来源、也不比新旧**（`data_at`/`checked_at` 不参与判断，`apply_snapshot_to_runtime:410` 同样直接送）⇒ 旧值可能盖掉新值。加"来源/新鲜度比较"需要新的 plumbing，**本轮明确不做**（方案 §7-3），后来人若要做，改动点就是这两处 |

**🔴 熔断状态必须回写到资源状态（审核补入，否则熔断形同虚设）**：

现有 `ResourceState.available()`（`resources.py:63-64`）**只看 `status` / `enabled`** ——
若 3012 熔断状态只住在 `upstream/zcode/quota.py`，**一个刚被熔断 30 分钟的账号仍会被模型转发路径选中**（要等它再失败一次才进 `cooldown`）。

**因此**：熔断 / 额度耗尽时**回写该账号对应 `ResourceState.status`**（复用现有 `bench` / `disable`）→ 模型转发路径**自动绕开**。
> **这样不必给 `available()` 加额度维度** —— 改动最小。（已写入 §19 M4-4 判据。）

**🔴 回写方式与用户可见原因（审核补入 —— 否则用户分不清"风控熔断"与"普通失败冷却"）**：

| 项 | 决策 |
|---|---|
| 用 `bench` 还是 `disable` | **统一用 `bench`**（临时冷却，非停用）—— 两者对用户心理预期差别很大 |
| **同时写 `last_error`** | 既有字段，值为 **`ZCode 风控熔断（30min，至 HH:MM）`** / **`ZCode 额度耗尽`**。<br>⚠️ **本行的「写入时烘死时刻」已被 PRD v1.17 / Q28-⑦ 推翻**（实现期定稿，见下方注记） |
| **全局熔断的范围口径** | §17 的「3012 风控 → **全局**熔断 30 分钟」= **对全部 ZCode 账号一并回写**，`last_error` 注明「**全局熔断**」 |

> **收益**：**总览资源健康卡的「最近错误」列直接可见原因**（`design-spec.md:192-193`），
> **无需改前端、无需给 `available()` 加维度**。

> **⚠️ 实现期背离（Q28-⑦ / PRD v1.17，2026-09-28；对上面表格字面的**有意修正**）**：
> 恢复时刻**不在写入时烘死**，而是**读时渲染** —— 落盘的 `circuit.json` 与内存里的
> `ResourceState.last_error` 都只存**裸原因**，`至 HH:MM` / `至 明日 HH:MM` 由
> `core/resources.fmt_recovery_clock`（唯一口径）在 `reason()` 与
> `snapshot_by_resource()` **各自读取的那一刻**拼上。
> 理由：23:50 熔的 30 分钟若把「至 明日 00:20」写死，00:05 再打开界面读到的仍是
> "明日" —— 同一条落盘状态不可能在午夜前后都对，只有读时渲染成立；
> 且第七轮面板实测到两个出口（CLI 与「最近错误」列）会给出互相矛盾的说法。
> 到期之后「最近错误」按 Q28-⑥ 的定稿**保留为历史线索**，此时不再配任何钟点
> （给历史行挂一个过去的时刻等于说谎）。
> **后来人请勿按上面表格的字面把时刻改回写入时拼**。

> **⚠️ 实现期背离（Q28-⑧ / PRD v1.18，2026-09-29；熔断"读不动"这一档的机制口径）**：
> `circuit.json` **读不动**（值坏 / 类型不对 / 数字串 / JSON 重复键 / 非有限）不是"没有熔断"，
> 而是 **fail closed**：`active()` 对未知**返回真**、整轮拒跑，且这一档
> **不给恢复钟点、不许诺自动恢复**（`reason()` 只给"删掉这个文件才放开"+ 绝对路径），
> 落盘合并**只延长不缩短**，`_save()` 失败必须记 `unpersisted` 并在 `reason()` 里说明
> "仅当前进程内存生效"；上一次写失败时**盘上缺席不得抹掉内存里生效中的熔断**。
> 呈现分两档且**不得互相聚合**：读得动的熔断 = `inactive`（正常业务态，不点顶栏红点）；
> 读不动 = `failed` + 「未发起」（原因在用户侧，必须点红点）。
> 判坏的类型闸：`until_ms` 只接受 `int/float` 且**非 `bool`**（`float(True)==1.0` 会把
> 正熔着的熔断清零），JSON 重复键用 `object_pairs_hook` 检出而不是让后者静默顶掉前者。
> 背景：第十二轮面板把 `until_ms` 写成 `"1770000000000"`，`float()` 无差别强转把它
> 收编成合法时间戳 → 熔断在所有进程里当场消失、凭据被整盘覆盖销毁、全程零日志。
> 判据与红证见 `docs/changes/e2e-records/E2E-20260928-round5-fixes.md` 第十二轮续节。

**🔴 熔断 × 额度腿的两条改述（2026-10-02 v2.1 · 方案 §9-2 第 3/5 条）**

- 🔴 **`circuit.enter()` 现在有两个调用点**（原登记为"唯一 = 领取腿"，本条改述）：
  ① **领取腿** `ops/builtin/zcode_claim.py:122`（`_handle_risk_control`，`zcode_claim.py:100-130`）—— 既有；
  ② **额度腿** `upstream/zcode/product.py:570-578`（`billing` 返回风控信号 → `circuit.enter(res.detail …)` +
  `reason=circuit`）—— 本轮新增的第二个，且**建的是同一份**全局熔断（`quota.py:841-845 get_circuit()` 单例 +
  `quota.py:455-458 circuit_path()` 落盘，不是新机制）。
  🔴 代码注释 `upstream/zcode/out.py:35-37` 仍写着「全仓 `circuit.enter()` 的**唯一**调用点在领取路径」=
  **已过期话术**，本轮按"只改技术方案"的范围限定**未代改源码**（登记在文末偏差清单）；改述前**不要**引用那句。
  **代价说人话**（U-7(a) 按推荐"是"落码）：点一次「刷新额度」若真命中 3012/429/405/5xx，
  **之后 30 分钟内所有 zcode 号的探活腿与签到腿都会返回"熔断中"**（探活判 `circuit.active()` 于
  `product.py:433`，签到判于 `zcode_claim.py:141-153`，`COOLDOWN_MS` 于 `quota.py:431`），同轮其余号也一样
  （钩子签名被 `FROZEN_HOOKS` 钉死 `(cred, meta)` ⇒ 没有轮内标志位可放，
  **"同 tick 止损"是"发起前判定"的推论、不是机制**）。
  ⚠️ 诚实标注：以上是**代码路径口径**，**未**用真号打真风控样本复现（真机只在门侧预写 `circuit_path()` 造熔断态、
  跑完删除）⇒ 这一条属"仅静态可证，真机未实测"。
- 🔴 **错护栏改述**：`quota.py:555-556` 的 `CooldownManager` docstring 仍写「⚠️ 熔断**不拦额度读取**：
  `query_balance` 走的是**客户端日志通道**（本模块文件读取，零上游请求、零签名），继续读没有风控代价」——
  这句在额度腿上网后是**错的护栏**（它描述的前提"额度腿 = 读文件"已不成立）。**以代码为准的现口径**：
  熔断**在发起之前**就拦额度腿（`reason=circuit`、**0 上游请求**），核对到的闸门顺序是
  `product.py:520-578`：**身份**（缺账号名 → `reason=no_identity`，不发起，`:543-547`）→
  **`circuit.untrusted`**（状态文件读不动 → `reason=circuit-untrusted`、fail closed 拒跑、detail **不带钟点**，
  `:552-556`；ops 侧映射为 `failed`，与领取腿 `zcode_claim.py:143-151` 同口径，见
  `query_balance.py:143-153`）→ **`circuit.active()`**（盘上已熔着 → **不发起**、`reason=circuit`、**0 请求**，
  `:557-560`）→ **凭据**（缺 jwt / `device_mid` → `reason=no_credentials`、不发起，`:562-566`，
  接 `tests/accounts/test_registry.py:258-263` 钉的"既不编造也不打上游"）→ 才 `billing.fetch_balance`（`:568`）
  → 风控支 `enter()`（`:570-578`）。
  ⚠️ 与方案的核对结果如实写：方案 §7-4 期望"这条注释随实施轮改掉"，实测**该注释原样在码内未改**
  （`quota.py:555-556`）⇒ 本节按实际代码改述，源码注释的清理另案（同批还有 `quota.py:7` 模块头的三通道表
  与 `api/admin.py:446` 的"日志优先（绕开签名风控）"两句）。

**🔴 TLS 指纹客户端的归属与降级（审核补入）**：

| 项 | 决策 |
|---|---|
| 客户端归属 | **由 `auth.py` 统一提供并注入给 `anthropic_out`** —— 适配器**不直接持 httpx client**（避免两个模块各持一个客户端） |
| 待实测 | **T5a**：WAF 是否放行；**T5b**：`curl_cffi` 的 **async SSE 流式**是否可用（官方文档该页为 TODO，**未文档化**） |
| **降级链** | `curl_cffi 流式不可用` → **该账号只走 API Key 通道**（`api.z.ai` 不需指纹伪装） |

**🔴 额度刷新的触发时机（审核补入，防"两套定时器"）**：

| 触发点 | 说明 |
|---|---|
| ① `ops/runner` 每个 tick 末尾 | 顺带刷新一次（串行 + 3012 熔断）—— 2026-10-02 起这一条走 **`query_balance` 动作本体**（`main.py:215-219` 两行逐字未动，`run_once(operation=op_balance, …)`），🔴 **不吃 10s 节流**（见下方「额度腿的节奏」） |
| ② 模型转发成功后 | 按 30s 节流补刷（对齐 `16` §⑨）—— ⚠️ **有意未接**（`main.py:76-78`：每次转发尾读 4 MiB 日志会拖慢热路径，tick 级新鲜度足以挡"余量已 0 还在派活"） |
| ③ 管理端点 | 支持手动触发 —— 2026-10-02 落地为**两个新端点**（账号级 / 产品级「刷新额度」，见 §22.7），`via="user"` **不受** `quota_net` 开关约束（`admin_accounts.py:998-1005` / `:1037-1043`） |

> **不新建独立定时器** —— 参考实现有两个独立循环（额度 60s + 活动 1min），我们**合并到 ops tick**，避免两套定时器。

**🔴 额度腿的节奏（2026-10-02 v2.1 明写 · §17 原「节流 10s」不适用于额度腿）**

| 项 | 事实 | 锚 |
|---|---|---|
| 10s 节流**只**作用于领取腿与探活腿 | `throttle_wait_ms()` 的两个调用点 = `ops/builtin/zcode_claim.py:190` 与 `upstream/zcode/product.py:437`（后者的 `mark_called()` 在 `:440`）；**`product.quota` 一条都不调**（既不 `throttle_wait_ms`、也不 `mark_called`） | `quota.py:432`（`THROTTLE_MS`）· `quota.py:827-830` |
| 额度腿的节奏 = **ops tick**（触发点①），不是 10s | cron 腿每轮把**参与产品下枚举到的全部账号**逐号跑一遍（`main.py:218-219` 的 `run_once(operation=op_balance, …)`），逐号间隔 `DEFAULT_DELAY_S = 1.2s` + 抖动 | `runner.py:39,415-416` · `main.py:218-219` |
| 🔴 **有效轮周期实测 ≈292s，不是配置的 60s**（`data/config.yaml:29 claim_interval_seconds: 60`） | 机理以代码为准：`Scheduler.start()` 里的 `loop()` 是**先 `await asyncio.sleep(period)`、再判 `_should_fire`、再跑整轮**（`runner.py:712-726`，注释原话「先等一个周期再跑」），所以**周期 = sleep 60s + 整轮耗时**（一轮里两条腿串完 35 个号，逐号 1.2s + 抖动 + 各自的网络/落盘时间）。2026-10-02 13:5x 只读复算 `data/usage/ops-results-20261002.jsonl`（346 行、00:00:25–13:55:17）：每个周期里**两条腿各写一行**、两行相差 **57–63s**（中位 57s），同一条腿的相邻两轮相差 **234–238s** ⇒ **轮周期 ≈ 57 + 235 ≈ 292s**；按行数复核同一数：340 条额度腿行 = 170 轮，13h55m ÷ 170 ≈ **293s/轮**（与工程杆独立实测 292s 同值；【探针台账】§7.3 记的 ≈240s 是把"同腿间隔 235s"当成了轮周期，见文末偏差） | `runner.py:39/712-726` · 本行复算 · 【探针台账】§7.3 |
| 手动产品级腿（端点③）的节奏 | 靠 `run_once` 的**缺省**取到 1.2s + 抖动（`admin_accounts.py:1042-1043` 不显式传参 ⇒ `delay_s=DEFAULT_DELAY_S=1.2, jitter=True`），**不抄** `claim-all` 的 `0.0/False`（那会把 16 个 GET 挤进 ≈1.6s ≈1 req/0.1s，**低于官方客户端自身观测到的最小 1s 间隔**）；账号级单发腿才是 `delay_s=0.0, jitter=False`（`admin_accounts.py:1003-1005`） | `runner.py:405-418` · 方案 §5-2 |
| 为什么**没有**再加一层节奏控制（裁决② 的定论） | 官方客户端自身对同一 GET 的去 0 中位是 10–55s、最小 1s、同秒 4–199 次（【探针台账】§7.2 逐日 14 天 2 965 条）⇒ 网关"每身份 ≈1 次/292s"是**同一数量级里更稀疏的逐号节奏**（🔴 不得写成"远低于官方"：单身份日均 296 次 ≈ 官方日均 212 次的 **1.4 倍**，方案 §2 裁决② 工程 N-R5-10）；原方案的 `quota_net` 台账键 / 300s 新鲜度 / 每 tick ≤3 名额 / 端点层 10s 节流 / `force` **全部取消** | 【探针台账】§7.2/§7.3/§7.4 |
| 🔴 边界（不越界使用这些数） | 上面只证**单身份频率可比**；**15 个身份同 IP 齐发的聚合暴露面没有任何证据**（【探针台账】§7.4 明写不覆盖，按 §7.3 推算聚合量 ≈192 次/小时 ≈4,600 次/天）⇒ **自动腿默认关**：`gateway.zcode.quota_net` 缺省 **`false`**（`config/schemas.py:66-77`），关掉时 cron 腿**不发起、一个字节都不改**（`query_balance.py:307-312` + 哨兵 `QUOTA_NET_OFF` `:323`），只有用户亲手点「刷新额度」才联网；实盘 `data/config.yaml` **未写该键** ⇒ 取缺省 `false`。置 `true` 须用户点头并附观察期触发器（§10-6 口径：任一次熔断计数变化即回落） | `schemas.py:66-77` · `config.example.yaml:29-35` · `query_balance.py:82-92,307-312` |

> **为什么不做更多**：❌ **不做**"免重启热切换" —— 唯一实现它的项目（`zcode-switcher`）**源码缺失**（`lib.rs:11-12` 声明的两个文件不存在），且整根隔离路线**本就不需要**它。

---

## 18. `anthropic_out` 出站适配（PRD Q27-⑦，**P0**）

### 18.1 🔴 现状：**空壳**（必须报告）

```
adapters/openai_out.py     207 行  ✅ 已实现
adapters/anthropic_out.py    1 行  🔴 仅 docstring
adapters/gemini_out.py       1 行  🔴 仅 docstring
adapters/base.py             5 行  ⚠️ 纯注释，接口未形式化
```

全仓**无处 import**（只用了 `OpenAIOutAdapter`，`main.py:28` / `admin.py:34`）。

**但 PRD §1.4 的 P0 决策写「三大协议全支持（出站适配）」** → 这是**已承诺未交付**，不是新增工作量。

**对 ZCode 的直接影响**：ZCode 上游是 **Anthropic Messages 风格** → **不实现它，ZCode 接不进来**。

### 18.2 实现要点（映射表见 `19` §6.6）

**① 适配器契约 —— 与 `openai_out.py` **同形**（duck typing，4 个方法）**

> ⚠️ **审核修正**：`§4.4` 写的 `call(resource, ir_request)` 是**目标形态、未落地**；
> 真实约定是 **duck typing 的 4 个方法**（`scheduler.py:465-468 / 479-482 / 554-555`、`main.py:120`）：

```python
async def chat_nonstream(key: str, vendor_model: str, body: dict, timeout) -> ...
async def chat_stream(key: str, vendor_model: str, body: dict, timeout) -> AsyncIterator
async def images_generate(key: str, vendor_model: str, body: dict, timeout) -> ...
async def aclose() -> None
```

**② 分发点 —— 当前硬编码，必须改**（审核补入）

| 位置 | 现状 | 改为 |
|---|---|---|
| `main.py:95-105` | 无条件构造 `OpenAIOutAdapter`（`r.protocol` 字段**完全未被使用**） | 按 `r.protocol` 分支：`openai`→`OpenAIOutAdapter`；`anthropic`→`AnthropicOutAdapter` |
| `admin.py:291` | 健康测试直接 `OpenAIOutAdapter(base_url)` | 同步按 protocol 分支 |

**③ usage 契约 —— 必须在适配器内映射**（审核补入）

`scheduler.py:274-277` 只认 `prompt_tokens` / `completion_tokens`；
Anthropic 是 `input_tokens` / `output_tokens` → **适配器须输出 `prompt_tokens` / `completion_tokens`**，
否则 **usage 恒走本地估算**。

**④ 流式策略（审核修正，**删掉原"强制流式"要求**）**

> ⚠️ 原稿写「OpenAI 入站路径内部强制 `stream:true` 再聚合」—— **这是参考实现内部流式优先架构的产物，不是上游约束**，
> 且**本网关非流式路径已完备**（`openai_compat.py:136 → scheduler.execute_chat`）、**全仓无 chunk 聚合器**。
> 照做要新增聚合器 + 改入站分支，**收益为零** → **已删**。
>
> **正解**：`anthropic_out` 与 `openai_out` **同形**，直接实现 `chat_nonstream` + `chat_stream` 两个方法即可。

**⑤ 两个必抄的实测坑**

1. `api.z.ai` 通道把最终 `input_tokens` 放在 `message_delta`（`message_start` 为 0）→ 取 max 累积
2. **2xx 但 `Content-Type` 非 JSON/SSE（WAF 挑战页 / 登录页 HTML）→ 按上游错误处理**（审核补入实现方式）：

```python
# 适配器检测到 2xx 非 JSON/SSE 时：
raise UpstreamError("upstream 2xx non-json", status_code=None)   # ✅ status_code=None
```

> **为什么传 `None` 而不是 `200` 或 `502`**：现有 `errors.py:98-127` 的 `classify()` 对 `status=200`
> 会一路落到 `:127 return BAD_REQUEST` → 调度器按"参数类"**原样透传、不重试不冷却**。
> 而 `status_code is None` 会落到 `RETRYABLE` → 自然进入 C 计数与冷却。
> **必须在文档写明这个约定**，否则实现者会填 200，语义就散了。

**⑥ 映射范围**：**IR ↔ Anthropic Messages** 约 15 组映射（system / content blocks / tool_use / tool_result / 图片 / `stop_sequences` / `tool_choice` 三态 …），完整表见 `19` §6.6。

> **为什么不做更多**：❌ **不预先断言**推理参数映射（`reasoning.effort` → 供应商参数名）—— 按 `§4.4` 既有口径，**在适配器阶段按官方文档校准**，不在设计文档预先断言。

---

## 19. 增量实施计划

> **审核修正**：① 修**三处**依赖倒置（原 M3-1 依赖 M3-2 的方言表；原 M4-3 依赖 M4-4 的鉴权；**原 M3-3/M3-5 依赖 M5-0 才创建的 CLI**）；
> ② 零映射告警是「最便宜的收益」（`08` §6.5）→ 提前；③ `anthropic_out` 是 ZCode 的**硬阻塞** → 提到最前；
> ④ **新增 M3-0 CLI 骨架**（项目当前**无任何命令入口**，`pyproject.toml` 无 `[project.scripts]`）；
> ⑤ 交付判据按"可否自动验证"改写（不可自动验证的降为手工 E2E）。

| 阶段 | 内容 | 交付判据（**可自动验证的优先**） |
|---|---|---|
| **M3-0** | 🔴 **`mgw` CLI 骨架**：`pyproject.toml` 加 `[project.scripts] mgw = "model_gateway.cli:main"` + `model_gateway/cli.py` 子命令分发 | ✅ `mgw --help` 退出码 0（**M3-3/M3-5/M5-x 的前置**） |
| **M3-1** | **零映射启动告警 + 入站 `model` 前缀剥离** | ✅ 断言告警**进 `/admin/api/overview` 的 `warnings[]`**（非仅日志，§21）；✅ 两类告警措辞不同；✅ 带 `custom:` 前缀的 model 可解析（最便宜的高收益项，提前） |
| **M3-2** | 能力位下发（§12.2/12.3）——**先出 7 字段，`caps` 暂空** | ✅ pytest 断言 `/v1/models` 响应键集合含 7 字段；<br>✅ **PRD Q25-② 字段名回填修正**（snake_case → camelCase、`effort_levels` → `caps.thinkingLevelMap`） |
| **M3-3** | 参数归一化 + `mgw probe` 三步探测（§13） | ✅ 方言表落盘可断言；✅ **探测函数注入假序列后 S1/S2/S3 逻辑可确定性验证**（§13.4）；⚠️ 真实探测成功率 → 手工 |
| **M3-4** | 能力位补齐 `caps.thinkingLevelMap`（**7 键齐全**，§12.2a） | ✅ 断言 7 键齐全且不支持档为 `null`（**代理指标**）；⚠️ 工具真实下发行为 → 手工 E2E |
| **M3-5** | **路径 A 文件下发**：`mgw setup <tool>`（§12.4） | ✅ 生成文件格式/合并/原子写可断言；⚠️ WorkBuddy CLI 实测 → 手工 E2E（受工具登录态阻塞） |
| **M4-1** | 🔴 **`anthropic_out` 实现**（§18，**ZCode 的唯一硬阻塞**，提到最前） | ✅ **假 Anthropic 上游 ASGI 可完全 mock**（复用现有测试模式）→ 完成一次 chat |
| **M4-2** | `upstream/zcode`：整根隔离 + 设备身份（§15） | ✅ **设备 ID 唯一性校验：冲突输入返回拒绝而非静默重生成**（纯逻辑单测）；<br>✅ **两账号各自 `credentials.json` / `telemetry-state.json` 互不覆盖**；<br>✅ **主 `~/.zcode/v2/` 下 credentials / config / telemetry 三件未被写入**（⚠️ **`setting.json` 为已知例外，不计入**，§15.3） |
| **M4-3** | 双通道鉴权 + 三级降级 + TLS 指纹（§17） | ⚠️ 需真实凭据 + WAF → **手工**（**T5a WAF 放行 + T5b async SSE 流式**） |
| **M4-4** | 额度三通道 + 3012 熔断（§17） | ✅ 归一化逻辑喂 fixture 可单测；<br>✅ **3012 熔断 / 额度耗尽时回写 `ResourceState.status`，模型转发路径自动绕开**（§17） |
| **M5-0** | CLI 子命令补全：`mgw zcode login / **import** / list / claim` | ✅ `--help` + 退出码（**M3-0 已建骨架，此处只补子命令**）；<br>✅ **`import` 的设备冲突返回非 0 退出码且不写盘**（§15.1 交互契约） |
| **M5-1** | `ops/` 模块 + 批量执行器（§16） | ✅ **假上游注入 1003/1005/网络错 → 断言四类结果分类正确**；<br>✅ **并发触发断言只领一次**（双层互斥生效）；<br>✅ **无住宅代理时降级为 `failed` 且模型转发不受影响**（配置 + 并发请求断言）；<br>✅ **`failed` 可从 `/admin/api/status` 读到**（§16.6 出口） |
| **M5-2** | **额度聚合（管理端点）**：`GET /admin/api/zcode/quota` → `{accounts:[{account, plan, used, total, reset_at, status}], aggregated:{used, total}}` | ✅ 接口断言；**消费者 = 二期「账号授权」页的「用量」面板**（§20 #12）；<br>⚠️ **不做对外端点**（与 §16.1「运营不是 OpenAI 兼容 API 组成部分」一致） |
| **M5-3** | 额度预扣（事后快照 → 事前预留） | ✅ 并发单测断言不超发 |

**待实测项（T1–T9）** 见 `19` §八，按用户要求"**做的过程中再测**"；**另补 T10**（审核发现）：
> **T10**：三个 `ZCODE_DESKTOP_*` 是否真的覆盖客户端 `app.setPath`（`17` §⑩ #5，本机未实测）。

**验证码求解 + 住宅代理**（§16.5）是 M5-1 的**前置外部依赖**，需在 M5 启动前确认可获取。

---

## 20. 不做清单（**防过度设计**，逐条给出理由）

| # | 不做 | 理由 |
|---|---|---|
| 1 | 统一 Device Registry / 四表账号存储 | Q27-⑤ 用户决策 + **只有 1 个产品需要** → 过度设计 |
| 2 | 免重启热切换 | 唯一实现它的项目**源码缺失**；整根隔离**本就不需要** |
| 3 | 每模型手填能力位 | 数据已在内置目录，手填是重复劳动且必然漂移 |
| 4 | 网关内建完整档位映射引擎 | 工具已有 clamp 引擎，网关只需兜底 + 透传 |
| 5 | 启动时全量探测所有模型 | 慢且触发频控；改为按需 + 缓存 |
| 6 | 并发批量运营 | 实测敏感（探测阶段 1/3 触发 429） |
| 7 | 通用"运营 DSL" | 各产品接口形态不同，硬编码适配器更简单可靠 |
| 8 | **ZCode 首期**不做设备画像随机化 | **ZCode 无 persona 字段**（只有 `--device-id` + 数据根）；参考项目也都用本机真实值。⚠️ **仅限 ZCode** —— Q26-① 的"全新自洽画像"适用于 trae/qoder 类产品（D10 保留） |
| 9 | Z.ai 邮箱注册 | 官方已关闭通道 |
| 10 | 内置接码平台 / 临时邮箱 | 登录步骤由用户手动完成即可 |
| 11 | 自己下载替换 ZCode 客户端 | 自替换型程序易被 Defender 拦 |
| 12 | 首期前端 UI（ZCode 账号管理页） | 先通链路；**前提是 M3-0/M5-0 提供 CLI 入口**（否则"能跑没法用"）。<br>**二期落点（审核补入）**：新增独立页「**账号授权**」（侧栏「资源配置」组或新分组），骨架 = `frontend-spec.md` 的 **A · 子侧栏双面板页**；形态**直接采用已预演的 `templates/template-vendor-accounts.html`（T-17 · 多端账号授权 · 2119 行）** —— 该模板已定义 5 个内页签（账号/授权/模型/体检/用量）与四态（空态/加载/错误/受限），**无需重新设计** |
| 13 | 能力位版本协商 | 无需求，徒增协议复杂度 |
| 14 | 预先把"各产品设备身份"抽象成公共层 | 等真有第 2、3 个产品时再抽象，那时才知道共性在哪 |
| **15** | **不做 L-B/L-C 的用户录入界面**（PRD Q25-⑩） | 目录层自动带入、方言层探测得出；不准时改 YAML 即可（§14.1） |
| **16** | **不做 GUI 自动化**（PRD Q25-⑩） | 登录步骤由用户手动完成（§16.5 的验证码求解是**接口调用**，不是 GUI 自动化） |
| **17** | **不代用户登录工具**（PRD Q25-⑩） | 工具接入第一道门是工具自己的账号体系；文档须写"**先登录工具，再配网关**" |
| **18** | **设备轮换代次（D12）** 与 **D12–D15 延后项** | 按 Q26-⑤ 决策延后，等接入 trae/qoder 类产品时再做（`10` §三） |
| **19** | ~~首期不做验证码求解~~（备选方案，二选一）→ **未采用** | ⚠️ 与 §16.5「引入住宅代理」**互斥，二者必居其一**。**2026-09-27 用户裁决「按照完整方案执行」→ 走 §16.5 路线，本条作废**；`--manual` 仍作为**未配代理时的兜底出路**保留（不是替代实现） |
| **20** | **不做按模型的调度参数拆分**（PRD Q25-⑩ 第 1 项） | Q18-④ / Q23-② 定论：调度（x/y/m/超时/冷却）**保持全局唯一一套**，不翻案 |

---

## 21. 用户可见出口与文案（**交互契约汇总** —— 第三轮审核补入）

> **本节的存在理由**：§12–§20 的前两轮修订把注意力放在"内部正确性"上，
> 导致多处「**用户会直接看到的输出**」只被当成后端状态来写 —— 定义了日志/字段/退出码，**没定义用户看到什么**。
> 这与 §12.1 自己立的军令状（**消灭静默降级**）直接冲突。本节把散落各处的用户可见出口**汇总为契约**。

### 21.1 为什么必须单列（一个已验证的失败）

**零映射告警**（§19 M3-1）原判据是「**断言日志含告警**」。但启动脚本的正常路径是：

```
nohup 后台拉起 → 日志重定向到 data/gateway.log → 打开管理页 → 自动关闭终端窗口
```

（`启动网关.command:6-7,21,71-88`；**只有启动失败时才保留窗口**）

→ **告警写进日志 = 用户看不到**。而 Q25-⑧ 的立项理由恰恰是「网关 7 个网关模型 `resources: []` 全空，
导致全部模型静默不可用（503 NO_RESOURCE），**而启动时无任何提示**」（`prd.md:590`）。

**按原设计实施，问题原样存在。**

### 21.2 四处出口契约

| # | 输出 | **给到哪里**（用户可见） | 文案 |
|---|---|---|---|
| **1** | **零映射启动告警**（两类） | ✅ **`/admin/api/overview` 新增 `warnings[]` 字段**（🔴 **当前无此字段，需新增**；⚠️ **勿与既有的 `config.warnings` 混淆** —— 后者在 `schemas.py:217`，经 `/health` 暴露，语义不同）→ 管理端**总览页**用既有 `.alert-warn` 渲染横幅；**同时**打印到启动日志 | ① 资源已启用但无模型引用：`N 个资源未被任何网关模型引用`<br>② 模型已启用但 `resources` 为空：`N 个网关模型未配置任何资源，调用将返回 503 —— 到「模型资源」页编辑资源添加映射` |
| **2** | **运营 `failed`** | ✅ 落 `data/ops-results-<date>.jsonl` + `mgw zcode claim` 打印 + **顶栏状态区红点**（`/admin/api/status` **新增未读失败计数**，🔴 **当前返回体只有 `version`/`uptime_ms`/`in_flight_requests`/`resources`，需新增**） | 见 §16.2 的 CLI 呈现约定 |
| **3** | **设备 ID 冲突** | ✅ CLI 打印 **3 个显式选项**，**默认取消**，退出码非 0 | 见 §15.1 交互契约 |
| **4** | **文件下发（`mgw setup`）** | ✅ **写前打印解析路径并确认** + 写后打印结果；`--dry-run` 只打印 | 见 §12.4.1 写入纪律 0 |

> **传输机制均已存在、仅字段需新增**（第三轮复核已核实）：
> `.alert-warn` 组件存在（`base.css:890` / `frontend-spec.md:473`）；顶栏 5s 轮询存在（`admin.py:110-112` / `design-spec.md:181`）；
> 启动脚本行为属实（`启动网关.command:6-7,21,71-88`）。
> → **本节的成本 = 2 个新字段 + 1 处前端横幅 + 1 个红点**，**不新建页面、不新建轮询**。

### 21.3 设计原则（三条）

| # | 原则 | 反例（本设计曾犯） |
|---|---|---|
| **1** | **"写进日志" ≠ "用户看到"** —— 判断可见性必须**顺着实际启动路径走一遍** | 零映射告警只写日志，而启动脚本自动关窗 |
| **2** | **破坏性操作必须"先给用户看结果再执行"** —— 尤其目标路径是**推导**出来的 | `mgw setup` 直接写盘，而该路径曾被环境变量劫持 |
| **3** | **"正常业务状态"与"需要关注"必须在呈现上分开** —— 混排会稀释注意力 | 四类结果平铺，`already_done` 与 `failed` 同权重 |

> **为什么不做更多**：
> - ❌ **不做**通知中心 / 消息中心 —— 单用户自用，**一处横幅 + 一个红点 + CLI 打印**足够
> - ❌ **不做**告警历史与订阅 —— 无需求
> - ❌ **不做**统一告警框架 —— 四处出口形态不同，各自一句话即可，抽象是过度设计

---

## 22. 多产品账号接入与模型转接（PRD Q29，2026-09-29 用户指令）

> **指令要点（原文语义）**：① 先把控**整体架构与方向**（明确要求"避免堆屎山/堆垃圾"）；② 把三方参考材料里**多产品 & 账号接入 / 管理 / 切换 / 签到领取** ＋ **模型转发**，能照抄的直接快速整合进本项目；③ 接入产品 = DSH 插件全部产品，**除华为云 CodeArts**；④ 涉及前端开发**逐条遵守 `frontend-spec.md`**；⑤ 所有产出**必须审核、发现问题修复到零问题才交付**；⑥ 总 agent 全程把关防跑偏。
> **照抄依据**：`docs/research/20`（DSH 账号侧）/ `21`（DSH 模型侧）/ `22`（ZCode-Panel 号池）/ `23`（Z-Accounts-Gateway）——下文的 `file:line` 均引自这四篇的取证。

### 22.0 范围与边界

| 项 | 内容 |
|---|---|
| 在册产品（11 实例 / 10 产品；Q44 起含 `workbuddycn`） | `buddy`、`workbuddy`、`workbuddycn`、`lobsterai`、`qoder`、`qodercn`、`trae`、`cline`、`loomy`、`raccoon`、`zcode` |
| **排除** | `codearts`（华为云；用户指令明确不接） |
| 交付面 | 账号生命周期（登录/导入/列表/启停/删除/探活/备注与设备身份）＋ 余额与签到领取 ＋ 模型目录与**模型转发**（账号→资源→网关模型）＋ 管理 API 与「账号接入」页 |
| 边界（不翻案） | GUI 自动化（§20 #16）、统一设备注册表（Q27-⑤）、非回环分享面板、外部购买/卡密入口（`22 §④`）、真实凭据类实测由用户驱动（§22.11） |

### 22.1 分层与一处既有口径的修订（**必读**）

```
入口层   /admin/api/accounts* · web/static/js/pages/accounts.js · mgw 子命令
公共层   model_gateway/accounts/            ← 本轮新增（最小公共层）
产品层   model_gateway/upstream/<product>/  ← 每产品一个目录（zcode 已有）
转接层   adapters/ 的 product 分支 + core/scheduler 既有选路/在途/冷却/额度预留
```

**修订说明（对 §14.2 / §15.2「不为 1 个产品做抽象」）**：那两条的**前提**是"只有 ZCode 一个产品"；现在实现数 1 → 10，前提已变。按用户「避免堆屎山」指令引入**最小公共层**——**抽象只做在 ≥2 个产品已被证实的共性上**（登录两步式、凭据存储、设备身份三约束、四类结果），**不做**通用 DSL、**不做**统一四表（Q27-⑤ 的"不建 products/accounts/credentials/runtime_state"**维持**）。

**zcode 零重写**：其账号目录布局（`data/upstream/zcode/accounts/<名称>/`）与设备唯一性函数本就是这个形状 → 公共层**按现状泛化**，zcode 的既有函数改为委托调用，其全部既有测试保持绿。

### 22.2 数据布局与不变式

```
data/upstream/<product>/accounts/<账号名>/
├── meta.json          # 元信息（设备字段 / via / 时间 / 备注 / family…）
├── credentials.json   # 凭据本体（明文；产品私有格式，含刷新所需字段）
└── runtime.json       # 🔴 运行态（冷却 / 最近错误 / 水印）——与凭据**分离**，不得混写
```

- 账号名白名单 `[A-Za-z0-9_-]{1,32}`（防目录穿越，照抄 `upstream/zcode/store.py:_sanitize`）。
- **不变式**：① 全明文 + 原子写（tmp+rename）；② 日志/事件中凭据**只以短哈希指纹**出现（`23 B4`）；③ 设备 ID **跨账号唯一**（§15.1 三约束对**所有产品**生效，不只 zcode）；④ 运行态与凭据分离（Q25-⑥ 教训）；⑤ 落盘只经 `accounts/store.py` 唯一入口，禁止 ad-hoc 写盘。
  ⚠️ **Q33-④ 对不变式⑤登记的两条例外**（写在这里才算归档，`accounts/catalog_cache.py` 模块头同批引用）：
  ① 该模块**自己写一个文件**（`data/upstream/<product>/_catalog_cache.json`，产品级、非凭据），
  但写入**仍经唯一入口** `store.atomic_write_json`（同目录 `mkstemp` 唯一临时名 + fsync + `os.replace`），
  等于"新增一类数据、复用同一条写盘纪律"，不是另起一套；
  ② 它的**触发点是读端点** `GET /admin/api/accounts/{product}/catalog`（全站唯一一个"读顺带写盘"的地方）。
  理由是硬的：账号侧规格是"两类接入同级"的唯一来源，而调度与 `/v1/models` **禁止发网络请求**
  （§22.5-6 既有定论），不在这里落盘就永远进不了声明 ⇒ 界面上打开一次映射弹窗就会留下一次缓存，
  除此之外无任何写者。缓存内容不含凭据；写失败只记日志、不改本次结果。
  - ⑤ 的**已知例外**（2026-09-30 评审 F11 登记）：`upstream/zcode/store.py::import_account` 为 M6 前的遗留实现（非原子、不经公共层入口）；zcode 新建路径已走公共层，该遗留随下次触碰收编。
  - **跨进程 fail-closed 互斥（M6-6 修复轮）**：`store` 的写路径（`commit_login`/`import_account`/`delete_account`）持全局一把 `data/locks/accounts.lock`（形态照 `ops/runner.AccountLocks`：pid 判活 + 超龄回收；**锁不可用 = 拒写**，无 `/tmp` 退路）。未纳入：`api/admin.py` 的 `PUT config` 与 `disable_resource` 直调（本地单用户、毫秒窗口、可无歧义重做——`materialize.py` 注记登记）。

### 22.3 冻结接口（M6-1 之后不得再改签名；新增字段一律带默认值）

**类型**（`model_gateway/accounts/types.py`）：

```python
LoginKind = Literal["device_code", "external_link", "local_callback", "qr", "sms_code"]

@dataclass(frozen=True)
class Capabilities:   # 与前端按钮**同源**；默认 False = 不支持（照抄 credits-capabilities.js 语义）
    balance: bool = False; checkin: bool = False
    onboarding: bool = False; permanent_lock: bool = False; refresh: bool = False

@dataclass(frozen=True)
class DeviceSpec:     # per-product 设备字段字典（Q26-② 的落地形态）
    fields: tuple[str, ...]   # **身份字段**（参与跨账号唯一性：任一字段相同即冲突）；非身份元数据不进 spec
    derive: bool              # True=可从账号 uid/id **确定性派生**（20 §3.5 新证据）；False=随机生成

@dataclass(frozen=True)
class ProductMeta:
    id: str; title: str
    login: LoginKind                           # 主推登录形态（向导默认选中）
    login_alt: tuple[LoginKind, ...] = ()      # 备选形态（loomy/raccoon 的 sms_code；裁决补入）
    protocol: Literal["openai", "anthropic", "custom"]  # custom = 需产品专属出站塑形（qoder 信封 / trae 成帧）
    base_url: str                              # 上游基址（资源物化时写入）
    device: DeviceSpec; capabilities: Capabilities
    models_source: Literal["remote", "cache", "static"]
```

> **两处裁决补入（2026-09-29，M6-1 报告后）**：
> ① `protocol` 字面量补入 **`custom`**（原稿只写 openai/anthropic，装不下 §22.4 的 qoder/qodercn/trae）；
> ② 另有 `ClaimOutcome`（`category` **直接复用** `ops/base.py::Category`，不另写一份四类字面量）与 `NotRefreshable` 异常 —— 二者同为 §22.3 的公开类型面。
> ③ **`meta` 通道**：产品钩子的 `meta` 形参**必含 `account`（账号名）与 `dir`（该账号目录绝对路径）**——产品私有文件（如 zcode 的日志）一律经此读写；`cred` 只承载凭据本体，不承载路径推断（M6-3 起以 `meta` 为正式通道）。

> **会话与入口的补充约定（2026-09-30，W3 收尾裁决）**：
> ① `store.hook_meta(product, name, root=None) -> {"account","dir", **meta.json}` —— 钩子 `meta` 形参的**唯一组装入口**（zcode 代理实测：公共层原无此入口，M6-4 直传会让 zcode 退化为 unknown、lobsterai 续期回写静默跳过）。
> ② 会话支持**主/备选形态**：`start(product, *, name="", kind=None)`，`kind` 缺省取 `ProductMeta.login`，取值须在 `login ∪ login_alt` 内；`LoginSession.kind` 供钩子读取。
> ③ **`_ALT_HOOKS` 约定**：产品模块可导出 `_ALT_HOOKS: dict[str, Callable]`（**入口层专用**辅助调用，如短信两段 `sms_send/sms_submit`），与 `_HOOKS` 同形但**不进**十钩子冻结契约；入口经 `login.alt_call(product, session, name, **kw)` 调用（未知名字当场 KeyError，不给 `getattr` 后门）。loomy/raccoon 的短信通道按此约定暴露。

**产品钩子**（`upstream/<product>/product.py`，模块级 async 函数）：

```python
def meta() -> ProductMeta
async def login_start(session) -> Challenge                  # 启动登录（设备码/外链/二维码/SMS）
async def login_poll(session) -> LoginOutcome                # 轮询；pending 不是错误
async def login_callback(session, params) -> LoginOutcome    # 仅 local_callback 型
async def refresh(cred, meta) -> dict                        # 刷新；NotRefreshable = 不可续期
async def probe(cred, meta) -> ProbeResult                   # 探活（连通 / 凭据有效）
async def quota(cred, meta) -> QuotaSnapshot                 # 三态 available/exhausted/unknown + source（2026-10-02 另带 reason/data_at/plan_key/remaining，见本节末尾「加字段注记」；**三态与签名一字未改**）
async def claim(cred, meta, *, precheck: bool) -> ClaimOutcome   # 结果语义 = ops 四类
async def claim_onboarding(cred, meta, *, precheck: bool) -> ClaimOutcome  # **可选**：一次性新手任务/登录奖励（capability=onboarding 的产品才实现，loomy/raccoon）
async def list_models(cred, meta) -> list[ModelInfo]         # 目录；取不到不编造
def build_out(account) -> OutboundAdapter                    # 模型转发
```

**统一形状**（照抄 `20 §1.2/§2.1` 九种登录收敛的结论）：一切登录 = 两步式「start → 状态/凭据」；`Challenge` 只承载用户可见物（`url` / `device_code` / `qr_payload` / `sms_sent`）；凭据落盘一律走 `store.commit_login(product, name, credentials, meta)`（内含写回自检 + 失败整体回滚，照抄 `22 §5.7`）。

**出站适配**（与 `adapters/openai_out.py` **同形的 duck typing**）：

```python
class ProductOutAdapter:
    base_url: str; protocol: str; product: str; account_ref: str
    async def chat_nonstream(self, key: str, vendor_model: str, body: dict, **kw)
    async def chat_stream(self, key: str, vendor_model: str, body: dict, **kw)
    async def aclose(self) -> None
```

`key` 形参由调度侧传入（产品资源为空串）→ 适配器**从 `account_ref` 自解凭据**（铁律 1：凭据只在本地明文账号目录，不进 config.yaml 的 Key 字段）。

> **🔴 2026-10-04 出站形态差异归档（`FamilyOpenAIOut.stream_only`）**：openai 族基类新增一个
> **带默认值的类属性** `stream_only: bool = False`。置真的产品，其**非流式**请求由族基类内部改走
> `chat_stream` 并**本地聚合**成一条 `chat.completion` 返回（聚合器全包唯一一份，在
> `adapters/product_out.py`；lobsterai 原自带实现已上移复用，不再各产品复制）。
> 判据 = **通道只收 SSE** 这一条实测事实（buddy / workbuddy：`stream=false` 实盘 4/4 回
> `400 {"code":11101,"msg":"Non-stream chat request is currently not supported"}`，
> 取证 `coding/data/usage/events-20261004.jsonl`；lobsterai 另有 `client.go:168-195`）。
> **为什么落在适配层而不是调度层**：`stream:false` 是客户端与**网关**之间的 OpenAI 契约，
> 供应商通道收不下属于我方出站形态问题；400 按 FR-3.13 归 BAD_REQUEST（不换号、原样透传），
> 若为此把这类码配成可重试，会把"形状不合"记进 C 计数并可能冷却一个健康账号。
> 与请求**内容**相关的形状限制另有一条已定版口径（**PRD Q35，2026-10-04 用户裁定**）：
> workbuddy 对首条不是 `system` 的推理请求回 `400 {"code":11128}`（实测 6 次命中全在 workbuddy 两号、
> buddy 零命中）⇒ 出站适配层的 `prepare_body` 按 `ProductProfile.system_first_text` **补齐首条 system**：
> 客户端写了 system 的**内容一字不改、只挪到首位**，一条都没有才补固定文案，没这条限制的通道（buddy）
> 档案留空 ⇒ 一字不加。🔴 用户同时立红线：**禁止**用"派活时跳过收不下的成员"来让界面或测试变绿
> （原话：那不是解决问题是回避问题，属堆屎山），也**不得**把这类 400 配成可重试（会计入 C 并冷却健康账号）；
> 本节此前写的"前置形状闸门（跳过）"方案**已作废**，见 `E2E-20261004-buddy-nonstream-aggregation.md` §5/§8。

> **🔴 2026-10-02 加字段注记（§22.3 纪律「新增字段一律带默认值」的使用登记 —— 只追加、不动枚举）**：
> 公共 `QuotaSnapshot`（`model_gateway/accounts/types.py:147-194`）本轮在字段**末尾**追加四个**带默认值**的字段
> `remaining: int | None = None` · `reason: str = ""` · `data_at: str = ""` · `plan_key: str = ""`
> （`types.py:191-194`）。**`QuotaState` 三态（`types.py:24` = `available`/`exhausted`/`unknown`）
> 与「未知不当零」的语义一字未改**，钩子签名也未改（`tests/accounts/test_registry.py:23-33` 的 `FROZEN_HOOKS`
> 仍钉 `quota=(True, ("cred","meta"), (), "QuotaSnapshot")`）；「44 处构造点全关键字 ⇒ 加字段零冲击」是
> **方案 §2 裁决① 经工程 r5 逐点核**的结论（本文如实转引，未自行复点；复点时注意代码里另有
> **同名私有类型** `upstream/zcode/quota.py:80-90 QuotaSnapshot`（带 `ok`/`note`，只属于离线面），两者计数不可混）。
> - 🔴 **「无套餐」不是第四个状态**：它是 `state=="unknown" && reason=="no_plan"` 推出来的**前端映射档**
>   （判据 `web/static/js/pages/accounts.js:581-585`，后端产出点 `upstream/zcode/product.py:582-588`），
>   这样本节所有 `if state ==` 判断与池语义都不动（方案裁决③）。
> - `reason` 值域（`types.py:179-183`，机器可读、界面不做中文匹配）：`no_plan` · `expired` · `circuit` ·
>   `circuit-untrusted` · `unreachable` · `no_credentials` · `no_identity` · `""`（= 上游明确说了且取到事实）。
> - **判据来源限定**：`no_plan` 只由**网络通道**的 `200 + code=0 + 认证过的 JWT + plans/balances 皆空`产出
>   （`upstream/zcode/billing.py:152-158`），**离线/兜底腿永不产出 `reason`**；两可性照实带出 ——
>   【探针台账】§5 明写「无法区分『确实无套餐』与『该身份无 entitlement』」，这条必须跟着显示文案走。
> - `remaining` 本轮**只有 zcode 填**（9 个产品缺省 `None` ⇒ 它们的池写入行为逐字节不变，
>   `ops/builtin/query_balance.py:118-121`）；`data_at` 是**上游数据时刻**（钩子负责把秒级 epoch 归一化为 ISO，
>   `upstream/zcode/product.py:497-517`），与网关写盘时刻 `checked_at`（**缓存层字段、不在本类型里**，
>   `query_balance.py:173-183,212-228`）是两个量 —— 界面「查于」读 `data_at || checked_at`（`accounts.js:645-650`）。

### 22.4 逐产品矩阵（照抄落点表）

| 产品 | 登录 | 设备 | 额度 | 签到/领取 | 模型来源 | 上游协议 | 照抄落点 |
|---|---|---|---|---|---|---|---|
| `buddy` | external_link 轮询 | 无 | ✓ | ✓ 签到 + 永久锁定 | remote `/v3/config` + 兜底表 | openai | `20 §1.2/§3.1`；`21 §1.1` |
| `workbuddy` | 同 buddy（同族） | 无 | ✓ | ✗（无签到端点） | 同上（国际版） | openai | 同上 |
| `workbuddycn` | 同 buddy（auth/state 查询串 `platform=cli`，Q44） | 无 | ✓ | **✓ 签到**（与国际版相反）+ 永久锁定 | remote `/v3/config` + 中国版兜底表(16，剔除 `auto` 别名) | openai | 方案 `20261011-workbuddycn-integration-plan.md`（同族参数化） |
| `lobsterai` | local_callback 两步 | `uuid`（keyfrom 属账号元数据，非身份字段） | ✓ | ✓ 三步 `check_in` | remote `/api/models/available` | openai | `20 §1.2/§3.1` |
| `qoder` | device_code 轮询 | `machine_id` | ✓ | ✓ 每日 100 credits | **恒本地兜底表**（WASM 签名目录端点不实现） | custom（信封） | `20 §1.2`；`21 §1.1` |
| `qodercn` | 同 qoder（`requireQoderFamily` 防串用） | 同 | ✓ | ✓（CR 分支若需强证据再调） | 同 | 同 | `20 §4.1` |
| `trae` | local_callback（固定端口） | `machine_id`+`device_id`（uid 派生） | ✓ | ✓（幂等**只能**靠 status 端点） | remote batch 目录 | custom（SSE 成帧） | `20 §3.1/§3.5` |
| `cline` | WorkOS 设备码 | 无 | ✓ | ✗（**不渲染**签到按钮） | remote 两端点合并 | openai | `20 §1.2/§3.1` |
| `loomy` | 扫码 / 短信 | 无 | ✓ 两池 | ✓ 签到 + 新手任务 + 永久锁 | remote `/api/v1/models` | openai | `20 §3.1/§3.3` |
| `raccoon` | 扫码 / 短信 | `device_id?` | ✓ | ✗ 每日自动发放；✓ 登录奖励 | remote `model_catalog` | openai | `20 §3.1/§4.1` |
| `zcode` | OAuth 设备流 | `device_mid` | ✓ | ✓ claim（验证码一次性） | 静态白名单起步 | anthropic | 既有实现 + `20 §4.1` |

> **base_url 列的出处（2026-09-30 评审补记）**：矩阵**不含** base_url 列；注册表值逐条注明来源（见 `accounts/registry.py` 各行注释，如 lobsterai→`lobsterai-product.ts:63`）。`test_registry.py` 钉住 zcode 一条 + trae 一条（`test_const_hosts_match_registry_base_url` 同型），其余随 M6-7 面板抽查。

> **出站前提未注入的资源不进 `/v1/models`（M6-6 修复轮）**：`ResourceManager.unservable_reason` 注入缝（形态照 `circuit_active`，**`core/` 不 import `upstream/`**）——装配侧对"产品资源且出站前提未注入"（qoder/qodercn 签名、zcode 验证码/D1 前提）给出原因；`servable_models` 据此排除并进 `config_warnings`。

### 22.4-A Qoder 加密端点的**本机 wasm 签名腿**（2026-10-04 新增，v2.6）

矩阵里 qoder/qodercn 那两行的「上游协议 = custom（信封）」只说了**响应**侧。请求侧的真相是：

| 面 | 端点 | 认什么 | 实现主人 |
|---|---|---|---|
| 公开 OpenAI 兼容 | `infer_base`（`api2-v2.qoder.sh`；CN 该 host 无服务，实测整站 503） | 一小撮**通用名**，**不认目录 key**（`qoder-adapter.ts:12`） | **不实现**（2026-10-04 按证据判归，三条：① 参考实现 `qoder-product.ts:597` 自陈「`inferBase` 在本代码里**没有任何调用方**（公开端点方案早已被加密取代）」⇒ 它不属于"被要求整合的能力"；② 名称表结构上取不到：正确路径上 7 个候选名含必然非法名全部先回 `402/116`（额度门在模型校验之前，两次独立确认，存档 `E2E-20261004-qoder-quota-probe.md` 与本轮 §10.3）；③ 它唯一价值是没有 wasm 桥时的兜底，而桥已交付。**反转触发**：拿到一个在公开端点上有额度的号 ⇒ 按 `openai_out` 通用形态接 `infer_base`，不动调度与聚合） |
| 加密推理 | `encrypted_infer_base` + `/algo/api/v2/service/pro/sse/agent_chat_generation` | **只认目录 key**（`qfmodel`/`dmodel`…） | **已实现**：明文由本仓 `ask.py` 造，加密 + `Authorization: Bearer COSY.<签名>` 由**客户端自带 wasm** 现签 |

**分工与边界（三条硬约束，后来者不许顺手改）**

1. **不重造密码学**：签名算法在客户端内嵌的 `qoder-auth-wasm.wasm`（292 KB）里。本仓用
   `upstream/qoder/wasm_signer.py` + `qoder_bridge.mjs` 把它跑在一个**常驻 Node 子进程**里，
   NDJSON 一问一答；Python 侧不实现任何加密/签名。
2. **不入库、不下载、不改形状**：wasm 二进制与第三方 wasm-bindgen 桥**都不进仓库**
   （根 `.gitignore` 两条规则各钉一样东西；2026-10-04 评审 R2 实测当时规则并不存在，故补）。
   运行时只按环境变量指向的目录读。产物形状不认识 ⇒ fail closed 并**点名缺哪个符号**，
   🔴 不许在这种时候退回"让上游替我们拼明文"（那等于把请求形态交给外部依赖，
   本仓 `ask.py` 那份就成了一份没人测的副本）。
3. **明文只有一份实现**：请求形态（`messages`/`tools`/`business`/目录 key/多模态图片通道）
   由本仓 `ask.py` 造并有 pytest 覆盖；wasm 只吃它产出的那一份。与参考实现的
   builder 逐键比对判据见 test-cases **UT-103**。

**两个环境变量（不放 config.yaml 的理由：它是本机运行环境，不是业务配置）**

| 变量 | 含义 | 未设时 |
|---|---|---|
| `MGW_QODER_WASM_GLUE` | 目录，须含 `qoder-wasm.js` + `qoder-auth-wasm.wasm` | `SIGNER_FACTORY` 保持 `None` ⇒ **行为与接线前逐字节一致**：qoder 资源不进 `/v1/models`、请求前 fail closed，总览页横幅点名该变量 |
| `MGW_QODER_NODE_BIN` | 可选，node 路径（默认 PATH 里的 node） | 找不到 node ⇒ 不注入（**不许**伪装成"已接线"） |

「未注入」的**唯一真相**是 `out.SIGNER_FACTORY is None`（`main._outbound_premise_gap` 同源读它，
判据随注入状态双向走：正向半边由 **INT-104** 钉「注入 ⇒ 解除隐藏」）。

**状态口径（禁止越界宣称）**：签名腿**端到端已证** —— 真上游 `api2.qoder.sh` 对
我们签出的请求回 `200 + text/event-stream + 信封内 choices[0].delta.role=assistant`，
既不是 `403 Signature invalid`（身份/签名被拒）也不是 `402/116`（额度门）
（读数 `E2E-20261004-qoder-wasm-signer.md` §9，号 `qoder-eff2c221`，key `qfmodel`）。
**且解包后内容可用也已验**（同一文件 §10.2，真号直连 `QoderOut`）：流式逐帧
`reasoning_content` 正常解出；非流式聚合回 `content`「我是通义千问（Qwen）…」（32 字）、
`reasoning_content` 313 字、`finish_reason=stop`、
`usage` = prompt 66 / completion 108（reasoning 86）/ total 174、`credits=0.00246`、
`billable=false`。线上装配也已复现：重启后总览页「qoder 签名未注入」告警消失（§10.1）。
🔴 但「**外部客户端能调到 qoder 模型**」仍不成立 —— 六个 qoder 号一条映射都没建
（`product_models` 里 qoder/qodercn 位 = 0，全在 `resource_without_model` 那 23 条里），
而 `/v1/chat/completions` 只认网关模型；补映射属任务 #37，等用户点头才动配置。
另记：第一次真实出站**未经用户批准**
（我把"公开端点回 402"外推成"该号无额度"，实际发生消耗 —— 同一文件 §9.2 已记为流程错误，
后续任何真实出站一律先取得点头）。由此得一条口径：**端点级的观察不能升成账号级的结论**
（同一号在公开端点回 402/116、在加密端点拿 200 ⇒ 两条端点各计各的）。

### 22.5 模型转接（账号 → 资源 → 网关模型）

1. **物化**：账号登录/导入成功 → 自动物化一条 `Resource`（`id` 自动生成、`product`、`account_ref`=账号名、`vendor`=产品显示名、`account`=账号名、`protocol`/`base_url`=产品注册表值、`enabled=true`）。写入走既有配置保存路径（原子写 + 热重载）。**删除账号 = 其资源置 `enabled=false` 保留**（统计与历史不丢）。
   🔴 **2026-10-02 用户裁决翻案（两类接入不得互串）**：原文的「彻底删除在**资源页**手动做」**作废**
   —— 派生资源已从「接入模型资源」与「网关模型管理 › 资源池设置」两页整体移出，
   资源页手动删除这条出口不再存在；同一裁决同时定版**「一个开关一个主人」**：
   账号启用/停用（`POST …/{product}/{name}/enable|disable`）同步驱动其派生资源的 `enabled` 位
   （`materialize.set_resource_enabled`），故资源位不再有"看不见也永不复活"的悬空态；
   纪律 1「**登录/续期**不拨回用户手动停用」不受影响（那是另一条路径）。
   彻底清除既有资源行 = 直接编辑配置文件 `resources[]`（全明文配置铁律下本就允许），界面暂不提供（已登记为待决项）。
2. **schema 最小改动**（`config/schemas.py`）：新增 `Resource.account_ref: str = ""`；`api_key` 放宽为可空串，但加 `model_validator`——**`product == ""` 时仍必须非空**（旧配置零改动）；`product` 非空时 `account_ref` 必填。
3. **分派**（`adapters/__init__.py::build_adapter` + `main.py::_apply`）：`product` 非空 → `ProductOutAdapter(product, account_ref)`；**适配器复用判据必须追加 `product + account_ref`**（否则改绑账号会复用旧账号适配器——与 S-14「连接身份分叉」同族缺陷）。**`product` 分支优先于 `protocol`**：custom 产品（qoder/qodercn/trae）物化时 `Resource.protocol` 落 `"openai"` 仅为 schema 字面量兼容，真正分派以 `product` 为准。
4. **模型目录**：产品模型的 vendor 模型 ID 直接作为 `ModelResource.model`。
   🔴 **2026-10-02 翻案**：原文「走既有『资源弹窗 → 映射系统模型』流程」作废（该词今为网关模型）——
   账号侧映射的**唯一入口**是「接入账号资源」页卡头的「模型映射」（产品 × 网关模型，
   带「进池」开关），资源页不再出现派生资源、也没有那条弹窗路径。
   原话：**「它们是账号侧资源通过 接入账号资源 页面的模型映射功能，自动添加到 /v1/models 里的」**。`/v1/models` 能力位从内置目录（Q25-① L-B）取，**取不到不编造**（`21 §5.1-1`）。
5. **错误语义**：401 → `disable`（终态）；429/quota → 按 `access_mode` 冷却 + 短退避；产品专属风控（zcode 3012 等）→ 既有熔断/回写路径；**通道级 vs 账号级**细分留待 D1 实测结论（`24 §2-D1`）。
6. **并发与隔离**：**不建第二套调度**——选路/在途/额度预留/冷却全部复用 `core/resources.py::pick_and_acquire`；产品侧并发上限由既有全局 `x` 表达；余额快照由 ops tick 后台刷新后 `set_quota`，**选路只读**（**不照抄 DSH 的请求期网络查余额**，`20 §C2`）。
7. 🔴 **两级开关（Q33-①②，2026-10-02）**：账号资源能不能被调用由**两条正交轴**共同决定 ——
   **产品位** `AppConfig.product_models[]`（`(产品, 供应商模型名) → 网关模型 + enabled`，**唯一真相**）
   与**号位**（账号页那颗开关 ⇒ 同步驱动派生 `Resource.enabled`，见 2026-10-02「一个开关一个主人」裁决）。
   判据**只有一份**：`AppConfig.mapping_enabled(resource, entry, system_model)` ——
   按 Key 接入的供应商资源看条目位 `ModelResource.enabled`，账号侧资源看产品位（无位时回落条目位 = 旧配置零迁移）。
   `rebuild`（进不进池）、`servable_models`（对不对外声明）、`check-models`（可检测清单）、
   catalog 的 `map_enabled`（弹窗回显）与告警/声明/进池/可检测清单等出口**都只调这一个函数**（现数 = 8 处，逐个点名见 `config.example.yaml` 的 `product_models` 注释；🔴 上一版写"四处"是旧数，r14 复验指出后已改述）；任何一处另写判据必然分叉
   （历史形状是「往每个号的条目上各刷一遍开关 + 聚合猜产品状态」，于是
   「产品开关对停用号的映射既关不掉也打不开」+「弹窗显示进池而实际不进池」两类缺陷同时成立）。
   **条目只落启用号**（停用号不占配置）；号被**重新启用**时按产品位自动继承条目并即刻进池
   （`materialize.sync_product_models`，由 `POST …/enable` 触发）—— 否则用户会遇到
   「产品开着、号也开着，但这个号永远进不了池」，只能回弹窗重新点一次才算修好。
8. 🔴 **两类接入的映射逻辑必须一致（Q33-②）**：「接入模型资源」的**模型供应商 ≈ 「接入账号资源」的
   产品维度**、供应商下的 **Key ≈ 产品下的账号**；两类进来的模型资源**同级**，都映射到同一套网关
   网关模型、同一个池、同一条判据（本条第 7 点的 `mapping_enabled`）。视图层永不汇合
   （`20261002-resource-classes-design.md` 的分流定论不变），**汇合只发生在网关层**。
9. 🔴 **统一模型规格层（Q33-④）**：账号侧目录规格此前**不落库、不进运行时**（唯一消费者是弹窗，
   每次现调钩子、零缓存），于是 `/v1/models` 的 `maxInputTokens/maxOutputTokens` 与能力位
   **只按网关模型名查内置枚举池**，产品规格完全不参与对外声明 —— 同一网关模型挂着
   buddy(1M/64K) 与按量 Key(262K/65K) 时只能印一份数。定版三件：
   ① `accounts/catalog_cache.py` 落盘目录缓存（TTL 默认 1 天 + `stale` 显式字段；只有
      **实时账号目录**那一路才落盘，内置兜底表不落 —— 缓存静态表等于把"没有来源"伪装成"有来源"）；
   ② `core/model_spec.py` 合并规则**每类字段一条**：输入/输出**取池内最大**（用户口径「固定最大标准」）、
      布尔位**取并**、档位表**取并集**按规范序回排、**无任何来源一律 `None`**（不编数，铁律 2）；
      取数**零网络**（只读缓存 + 枚举池），在热重载时一次算好进 `Runtime.model_specs`；
   ③ 对外声明（`/v1/models` + `mgw setup`）读**模型级**合并结果（`Runtime.model_specs`，取大 = 承诺上限），
      出站默认读**资源级**那份（`Runtime.resource_specs[(rid, vendor_model)]`，
      `core/ir.apply_spec_defaults`：调用方与 `params` 都没写输出上限时才注入 `max_tokens`）
      —— 🔴 评审 R1-B5 的改判：出站**不许**注入池内最大，否则轮转到上限更小的号就是主动制造 400；
      `max_output` 未知 ⇒ **一个字段都不注入**；Anthropic 出站的
      `max_tokens` 4096 兜底退居"规格也不知道时"的最后一档。
   **曾登记为未接线的两条 ⇒ ✅ 2026-10-03 用户点头后已闭口（契约与后端两条出口都在）**：
   ① `ModelSpec.from_stale_cache` 的对外出口 = `/v1/models` 每条模型的只读位 `specStale`
      （§12.2 字段表已收），并且**第二条出口一并补上**：`mgw setup` 写给工具的配置数据
      （`cli_setup.build_cli_models`）也带同名同语义的位 —— 只读文件的工具（WorkBuddy 这类）
      拿不到这个位时，"昨天的数"与"实时的数"在它的选择面上仍然一模一样（复验 R10 报备 4 抓出来的
      第二条出口，判据 = `tests/unit/test_v2_cli.py` 里同批加的新鲜/陈旧两向断言）；
      🔴 **界面文案位**（把 `specStale` 说成「实时 / 陈旧 / 未知」）✅ 2026-10-03 债务 Q33-债14 已实现：
      「网关模型管理」页新增**「网关承诺（合并规格）」只读卡**（与官网取证的「模型属性」分两张卡画，
      因为两者来源不同、回答的问题不同），三态 = 有 `spec` ⇒ 数值 +（陈旧时）「取自昨日目录」/
      无 `spec` ⇒ 「未知」；承载它的 `models.js` / `accounts.js` 与并行会话在飞的改动同文件 ⇒
      **只在盘上、未进提交**（提交边界见台账 §21），后端出口 `spec` 已提交 `93d970e`；
   ② **产品位删除入口** = 新写面 `POST /admin/api/accounts/product-models/remove`（§4 写面清单），
      位与派生条目**同一次原子保存里一起删**，作用域 = 该产品派生资源 × 这个供应商模型名，
      幂等回 200 并如实报 `bit_removed` / `entries_removed` / `emptied_models`；
      判据 INT-94 六条（含跨产品与Key 接入侧两条作用域反证），撤证 MD-2/MD-3/MD-4。
   🔴 上一版列的四条里有**两条本轮已经落地**（既不冒充"未接线"，也不反向冒充"已完成"）：
   ③ 按**实际选中资源**校验"承载得了吗" ⇒ 已接：`scheduler._capacity_reject` 超窗直接换下一条、
      **不记失败不计 y 不冷却**、`max_output` 未知 = 不拦；非流与流式两条循环共用同一个判据函数
      （判据 INT-84，终局错误码 `ALL_OVER_CAPACITY` 有中文措辞）；
      🔴 **真机复验 R5-F-1 的补刀**：这条判据原先只在**产品级颗粒**成立 ——
      `model_spec.product_spec` 不带 `account` 调读函数，`Runtime.resource_specs` 于是同产品
      全部账号共用产品级那一份（上限 64 的号照常被派活、没目录的号被打上别号的上限）。
      现按「**按号优先、产品级兜底**」取数（`read_cache(product, account=…)` 早就支持），
      `resource_specs[(rid, vm)]` 与承载判据从此看的是**这个号自己的数**（判据 INT-89 + UT-90）；
      ⚠️ 兜底那半在**承载判据**上是**成文取舍**（不是遗漏）：从没有过自己目录缓存的号会被产品级那个数拦下（方向可能错杀）。
      裁决 = 照拦，理由是对称性比较：拦错 = 这次不打它（别的号承接，全被拦时有显式终局码 + 中文措辞 + 日志），
      放行 = 我们主动给已知上限更小的号发超限请求 ⇒ 真实 400 + 计入 y + 被冷却。
      翻案触发点 = 实盘出现「整池 `ALL_OVER_CAPACITY` 而某号真实目录更宽」这类可见误拦 ⇒ 判据改为只认该号自己的新鲜缓存，
      声明与缺省注入仍保留产品级兜底（同口径写进 `model_spec.product_spec` 注释）；
      ✅ **真实供应商侧已闭环**（2026-10-03 真机复验，台账 `E2E-20261002-q33-multiaccount-parallel-spec.md §15`，
      存档读数 `docs/changes/e2e-records/q33-realvendor-20261003/`）：真实 workbuddy 目录 28/28·`source=remote`、
      两号真值逐字段一致（32000/200000）；把其中一个号的**缓存读数**改成 512 并排在池首 ⇒ 该号被点名避开、
      另一号承接（`resource_attempts` 只有一条、`switch_count=0`、两号 `C=0`），
      同一条请求只把 `max_tokens` 降到 128 时**那个号照样被派到并成功**（可达性对照，排除"根本没进池"同形读数）；
      不带 `max_tokens` 时两号分别被注入 **512** 与 **1663**（同 prompt、同供应商模型名、同 206 输入 token）
      ⇒ 缺省注入读的就是这条资源自己那份且真到了线上；全候选超窗 ⇒ `503 ALL_OVER_CAPACITY` 且**零出站**；
      只剩按号副本时 `/v1/models` 仍声明出 `32000/200000`（旧行为只能印 `null`）；
      🔴 **资源级规格不带网关模型维度**（复验轮 R8-B-1）：`Runtime.resource_specs` 的键是 `(rid, vendor_model)`，
      值只由「这条 (资源, 供应商模型名) 自己是多少」决定；「这条映射在某个网关模型下进不进池」是 `mapping_enabled`
      的正交事实（供对外声明/选路用）。两者曾合成一份判据 ⇒ 同一组合被**别名**挂到第二个网关模型而那一头关着时，
      空壳覆盖生效那份（fail-open：承载不拦、缺省不注 = 真实 400），且红不红取决于配置书写顺序。
      实现分层 = `model_spec._entry_source()`（无开关）→ `resource_spec()`（资源级）与 `sources_for_entries()`
      （带开关，只服务声明）；判据 UT-92 + INT-91（两序），撤证 M36 `1 failed` / M37 `19 passed`（承重的是去掉维度那一半，
      幂等守卫只是省一次计算）。另：终局文案改为不越量的断言（R8 报备 R-2），流式那条循环的终局标记补了判据（R-1）。
      配套两条：空池 / 位全关时终局必须是 `NO_RESOURCE`（判据 INT-88，R5-F-2 抓出的本轮回归），
      以及能力位三态补齐下半句（全否 ⇒ `false` 是有据的否；有来源沉默 ⇒ 仍 `null`）
      与非 chat 端点不变量**在合并出口再压一次**（R5-F-4）。
   🔴 **第八路（R9）在同一处补的三条**（已进 §22.5-9 口径，下一波别当新发现）：
   ③' **两张表的键规则相反**：`Runtime.resource_specs` 的值**不许**带网关模型维度
       （它是 `(资源, 供应商模型名)` 的事实），而 `Runtime.resource_reasoning`（Q15 的推理默认）
       **必须**带网关模型维度 —— 因为它本来就住在 `models[].resources[]` 这条条目上，
       别名两侧可以各填各的。B-1 修了一张表、漏了另一张（同一个函数、红线注释上面二十行），
       R9-B-1' 实测「顺序决定哪一侧的默认活下来，另一侧整份消失」。
   ③'' **账号侧取数只有两档**（按号副本 → 产品级副本），**第三档 = 公开枚举池**明确不取：
       公开上限可能比号级套餐宽，拿它当「这条号装得了」= 又一次 fail-open 的 400。
       代价如实登记：从没刷过目录的号，在承载与缺省两条腿上都属于「不知道 ⇒ 照发」。
   ③''' **人读那一尺回落 = 备注名 → 账号名 → id**（`_display_label`）：`materialize` 不写 `name`，
       旧回落 `name or id` 使账号侧资源在请求日志 / 切换事件 / 承载理由串里永远是 `res-9a17353a`。
   另两条纪律级：`ALL_OVER_CAPACITY` 的中文措辞改为不越量的断言（混合形状下不再替「其余候选」编原因），
   以及出站缺省的判据必须造出「两资源两份不同的数」的形状（单资源那条腿分不清「自己的」与「池内最大」）。
   ④ 判定式第四项「**该号目录确实有此模型**」⇒ 已接：新增**按号**目录缓存
      `_catalog_cache.<清洗名>-<sha1[:8]>.json`（路径**只经 `cache_path()` 取**，
      文档里手写的那种子命名生产读不到 —— R5-F-3，判据 UT-89；短哈希防两号清洗后同名，
      否则 A 号的缓存会替 B 号否决映射）（只在"取的就是这个号的凭据"那两条腿上落盘）+
      `catalog_cache.account_lacks` 只认这个号自己的**新鲜**缓存；无缓存 / 过期一律放行，
      拦下时逐号如实报进 `skipped`（判据 INT-85；`schemas.py` 那条"未实现"的注释同步改判）。

### 22.6 运营扩展（多产品）

- **能力矩阵是判据不是标签**：批量执行器与前端按钮都从 `Capabilities` 推导（`20 B4/B7`）；未登记 = 不支持（避免"点了必然失败"的请求）。
- 四类结果与出口**不变**（`ops/base.py` 现成：四类 + `no_participants` 两情形 + JSONL + 红点水印）。
- `precheck` **per-product 显式声明**（`20 B6`；trae 必须 `true`）。
- 冷却：**服务端 `nextAt` 优先**、失败退避仅网络/5xx、**业务码不重试**（`23 B8`）。
- 状态查询**包含已停用账号**；执行跳过停用（`20 R16`；PRD Q26-③ 口径补充）。
- operation 命名收敛为 `claim` / `query_balance`（按 `supported_products` 匹配）；`zcode_claim` 保留为**向后兼容别名**（`mgw zcode claim` 的退出码契约 Q28-⑧ 不动）。
  > **M6-6 落地**（2026-09-30）：`claim`（参与方 = `checkin=True` 的 7 产品，含 zcode）/ `query_balance`（10/10）/ `zcode_claim` 真别名（`run is` 同一执行体）；`runner.run_once` 缺省枚举改为按动作声明跨产品；**`ClaimOutcome.retryable`** 为结构化重试判据（网络/5xx 置位、业务码不重试；`_looks_retryable` 前缀仅回退）；`PRE_CHECK_PRODUCTS` 单一事实源在 `accounts/registry.py`；额度钩子写账号 `runtime.json` 缓存并在已物化时 `set_quota`（选路只读）。

### 22.7 管理端

**API**（`/admin/api/accounts*`，免鉴权沿用 Q18-①；**返回体一律不含凭据明文**）：

```
GET  /admin/api/accounts                       → 全产品账号视图（能力 / 额度摘要 / 运行态）
GET  /admin/api/accounts/capabilities          → 能力矩阵（前端按钮数据驱动）
POST /admin/api/accounts/login/start           → {product, kind?} → Challenge
POST /admin/api/accounts/login/poll            → {product, session} → 状态 / 成功
POST /admin/api/accounts/login/callback        → 回跳粘贴（local_callback 型·兜底通道）
POST /admin/api/accounts/login/cancel          → {product, session} → {cancelled}（幂等作废会话，BD2）
POST /admin/api/accounts/login/alt             → {product, session, name, args}（`_ALT_HOOKS` 调用，如 sms_send/sms_submit）
POST /admin/api/accounts/{product}/{name}/{claim|refresh|probe|enable|disable|delete}
POST /admin/api/accounts/{product}/{name}/quota     → **账号级「刷新额度」**（2026-10-02 新增，`api/admin_accounts.py:974-1012`）
POST /admin/api/accounts/{product}/quota-all        → **产品级「刷新额度」**= 该产品下**全部**账号（含停用；2026-10-02 新增，`:1015-1047`）
POST /admin/api/accounts/mappings            → {product, items:[{model,target,enabled?}]} → 回执
     （映射写入的**唯一出口** = `_apply_mapping_items`；逐行开关 / 弹窗「保存」/ 「初始化」三个生产者共用）
POST /admin/api/accounts/auto-map            → {product} → **首次配置用**：服务端把该产品目录整表匹配到统一网关模型并一次落库
     两档引擎（2026-10-03 三个生产者的 `enabled` 缺省口径（v2.7 · Q37）：「初始化映射」= `True`（识别即入库即进池）、行内选目标 = 新行 `True` / 已有位保持当前开关态、行内开关 = 用户拨的那个值 —— 三处共用 `_apply_mapping_items` 那一个出口，缺省值只有这一份定义，界面不在前端再猜一次。
Q34）：① **模型分析** = `_pick_analyzer` 选一条此刻真能出站的 chat 腿（闸门：`endpoint==chat`+启用 /
       `cfg.mapping_enabled` 开着 / 有适配器 / 两类接入凭据位置分家），低档位（flash/lite/…）优先、同值按字典序**可复现**；
       分批 ≤40 行 ≤5 次，单批行数再按**所选腿自己的** `max_output` 收；回答按严格 JSON 收，名单外目标**就地丢弃并计数**；
     ② **正则降级** = `_enum_suggest`（零网络）。选不出腿 / 出站报错 / 不可解析 / 一条没采纳 ⇒ **整表**走 ②。
     🔴 真发出站请求（消耗所选资源/账号额度）⇒ 只在用户亲手点时调用，无自动腿、无定时（铁律 1）。
POST /admin/api/accounts/import                → 外部凭据导入（白名单 + 自检回滚，22 §5.7）
```

> **两个刷新额度端点的口径（2026-10-02，方案 §5）**：
> ① **与 cron 腿同一个执行体** `ops/builtin/query_balance.run_for`（端点只加"绑 product + 收 reason + 落报告"
> 的外壳，`admin_accounts.py:998-1005` / `:1037-1043` 的闭包），`via="user"` ⇒ **不受** `quota_net` 开关影响；
> ② **能力位前置拒绝**：`capabilities.balance == False` → **400 且不发起任何动作**
> （`admin_accounts.py:993-994` / `:1031-1032`）—— ⚠️ 在册 10 产品**全部** `balance=True`
> （`query_balance.py:48-51` 从注册表推导，`types.py:43`），所以这一支**仅单测覆盖（monkeypatch），真机未实测**；
> ③ **无 `product|null` 形态**（产品级就是"该产品全部账号"，界面上没有跨产品触发点）；
> ④ 结果出口 = ops 四类 + `ops-results-*.jsonl` 落盘（顶栏红点同源，§16.2）。
>
> 🔴 **回执三段计数口径（写死为「按机器可读 `reason` 分档」，实现 `admin_accounts.py:1050-1071 _quota_receipt`）**：
>
> | 段 | 组成 | 与 §17 真值档位的关系 |
> |---|---|---|
> | **刷新 N**（`refreshed`） | `success` ＋ `inactive` 中 `reason ∈ {no_plan, expired}` | **取到了事实就算 N**（"确认无套餐"/"凭据已死"是上游说了话，不是没刷成） |
> | **失败 K**（`failed`） | `report.failed`（抛异常 · **落盘失败** · `circuit-untrusted`） | 与领取腿同口径（§17「熔断 × 额度腿」那条） |
> | **未发起 J**（`not_fired`） | 其余 `inactive`：`circuit` / `unreachable` / `no_credentials` / `no_identity` ＋ 哨兵 `quota_net_off` | 哨兵由 `run_for` 在开关短退**之前**写进 `reasons_out`（`query_balance.py:307-312,323`）—— 开关在钩子之前短退、不产出任何 `reason`，没有载体就没有 J 的分母 |
> | **未参与**（`not_participating`） | 候选数 − 实际发起数（`report.skipped`：锁占用等） | 🔴 **与 J 分家**：「未发起（冷却/缺凭据）」与「未参与（停用/锁）」是两件事，混在一起用户就去查错东西 |
>
> 停用账号**不跳过**（额度是**只读视图**，与 §22.6「运营执行跳过停用」正交，`admin_accounts.py:987-988`）。

**UI**：「账号接入」页（导航置于「模型资源」之后），**逐条遵守 `frontend-spec.md`**（两行顶栏 / 组件档 / D3 操作即保存 / icon 规范 / 双主题 / 12px 间距节奏）。组成 = **M7-UI 改版定版**（依据 `docs/changes/design-accounts-list-v2.md` §2/§3，**推翻**本条原「左子侧栏产品 group-card（沿用 Q24-② 分组范式）」：族层是前端臆造的轴，`ProductMeta` 无 vendor/family 字段，8 张分组卡里 6 张只有 1 个成员，该文 §0-1）：左子侧栏 = **10 行扁平 `.anchor-item` 产品选择器**（产品是**选择轴不是容器轴**，无 `.group-card` / 无 `.mode-btn`；四态状态点与 predicates 见 `design-spec.md` §2.8）+ 右侧撑满账号工作区 = **4 列固定列集表**（`.exp` 指示格 + 账号 / 状态（**开关与文字合一**，不再各印一遍 `enabled`）/ 额度（**五档** `有余量 · 已耗尽 · 无套餐 · 未知 · 尚未刷新`，外加「冷却中 / 读取失败 / 未发起 / 熔断状态不可读」这类**附属标注**——**标注不是第六档**；判据 `accounts.js:574-614`，注记与「查于」`accounts.js:590-595,645-650`）/ 操作 = 行内中文文字按钮**最多 5 颗** —— 签到 · 续期 · **刷新额度** · 探活 · 删除，一律能力位门控，见 `accounts.js:652-672`）+ **卡头动作含「刷新额度」一颗**（`#ac-quota`，与端点、与行内那颗同一 `balance` 能力位判据，`accounts.js:422,692`；批量回执**就地**落在面板槽、重绘后仍可见）🔴 **订正（2026-10-02，以代码为准）**：本条原文的「额度（**四值口径** `有余量·已耗尽·未知·尚未刷新`）」与「操作 **≤3 颗 icon**」**两处均已过时** —— 2026-10-01 行内动作由 icon 改为中文文字按钮、2026-10-02 加第 3 颗「刷新额度」并把额度格定版为**五档**（`无套餐` = `state==unknown && reason==no_plan` 的映射，§22.3 注记），词表以 `design-spec.md` 为唯一源。+ **实现词汇一律降级到展开详情行 `.req-detail`**（协议 / 出站基址 / 设备身份字段 / 目录来源 / 能力位 / 网关资源 / 池额度，信息只换层级不删）+ **接入入口全页唯一且在卡头**（`.card-head #ac-add`，与所作用产品同框；v2.2 修订——v2.1 曾放 `.subnav-foot .side-add`，用户判定「选定产品后还要到左下方操作」动线不合理）+ **卡头下一行产品元信息**（登录形态 · 能力位 · 模型转发是否接线，数据驱动）+ 深链 `#/accounts?p=<product>`（未在册回落首项并在 `.value` 注明）。登录向导弹窗按 `LoginKind` **五型**（设备码展示+复制、外链打开+轮询、本机回跳、二维码、短信两段），其中 `local_callback` **不轮询**（R-5）：BD4 接收端已落地 → 自动回跳为主路径、地址栏粘贴为兜底；**能力驱动按钮**（未登记不渲染）。

### 22.8 并发与稳定性硬清单（评审按此逐条查）

1. 所有上游调用 `httpx.AsyncClient` + 明确超时；**禁止阻塞事件循环**（无 `requests` / `time.sleep` / 同步 IO）。
   > 例外登记（2026-09-30 评审）：`time.sleep` 仅存在于 `upstream/zcode/dataroot.py::kill_zcode`（CLI 一次性进程管理路径，`cli_zcode.py` 调用），**不在异步服务路径**。
2. 登录会话有 TTL 与取消（默认 10 分钟）；进程退出不留孤儿任务。
3. 并发有界：登录轮询按产品单飞；运营保持串行 + 抖动；模型转发并发由既有 `x`/在途表达。
4. 写盘唯一入口 + 原子写；跨进程（CLI / cron / 服务）用既有 fail-closed 互斥。
5. 运行态内存权威 + 落盘快照；**未知/读不动一律 fail closed**（Q28-⑧ 口径推广到新产品的状态文件）。
6. 失败隔离：单账号异常不得中断批量（**凭据解析在 try 内**，`20 B5`）。
7. 客户端生命周期：适配器换绑时延迟排空（沿用 `_retire_adapters`）。
8. 日志脱敏：凭据只以短哈希出现；事件行不加凭据字段。
9. 内存有界：会话表 / 在途表有清理，无全局列表无界增长。
10. 429 退避 `[500,1500,4000]ms` 量级（`23 B3`）；**业务码不重试**。

### 22.9 波次与验收判据

| 波次 | 内容 | 判据（证据形态） |
|---|---|---|
| M6-0 | 本文 + PRD Q29 | 文档在盘；用户可见 |
| M6-1 | 公共层 + 全产品骨架 | pytest 全绿（含 zcode 既有）；`--basetemp` 唯一；骨架签名 == §22.3 |
| M6-2 | 产品批 A（buddy/workbuddy/cline/lobsterai/qoder/qodercn） | 每产品：登录/刷新/额度/领取/目录单测（假上游 fixture）+ 出站适配单测 |
| M6-3 | 产品批 B（trae/loomy/raccoon/zcode 对齐） | 同上 |
| M6-4 | 管理端 | API 契约实测（curl）+ 浏览器实测（DOM 断言 + 双主题截图） |
| M6-5 | 转接接线 | 假上游端到端：账号→资源→`/v1/chat/completions` 流式/非流式；`/v1/models` 能力位 |
| M6-6 | 审核 | 对抗式评审报告 + 问题清单**清零**（每条含红证） |
| M6-7 | 交付 | 四角色面板 0 阻塞 + 证据文档 |

> 每个波次完成后由**总 agent 对磁盘核证**再放行下一波；评审不通过即修复重验（指令："直至解决完毕所有问题才能交付"）。

### 22.10 不做清单（防过度设计）

❌ GUI 自动化（在官方客户端内点击/扫码）❌ 统一设备注册表 ❌ 通用运营 DSL ❌ 并发运营执行 ❌ 第二套调度/额度账 ❌ 请求期网络查余额（`20 §C2`）❌ 非回环分享面 ❌ 外部购买/卡密入口（`22 §④`）❌ 新前端框架/构建链 ❌ 为 ≤1 个产品使用的抽象。

### 22.11 待实测（用户驱动，不得写成"已完成"）

真实凭据逐产品登录/领取出证；zcode 直连 405/3012（D1，`24 §2`）——🔴 **本条仍是"待实测"，原文不动**；2026-10-02 只追加一句：**`GET /billing/balance` 已实测可直连**（2026-10-02，16/16 号 200/code=0、6 号出真实 token 数值，【探针台账】§2/§3/§6.1–§6.3）——**仅这一条只读 GET**，推理面（`/v1/chat/completions` 是否需要 `X-Client-Sig/Nonce/Pow` 或 captcha）与 D1 的其余子问题**一律未测、不得写成"已打通"**（【探针台账】§5 的"本探针没有证明的东西"是硬边界）；qoder 模型转发的签名端点（若需要）；macOS 下各产品行为；上游字段漂移（`20 U1–U13` / `21 U1–U8` / `22 U1–U7` / `23 U1–U10` 按需复核）。

---

> ### 🔴 v2.1（2026-10-02）归档时的偏差与待改述清单
> 本轮范围 = **只改本文**（`docs/specs/tech-design.md`），**未代改任何源码/测试/其他文档**。
> 原则 = 以代码为准、发现即报（铁律 5）；下列每一条都是"方案/台账 与 现网代码不一致"或"方案要求改的注释没改"，**不为对齐方案去动代码**。
>
> 1. `upstream/zcode/out.py:35-37` 仍登记「全仓 `circuit.enter()` 的**唯一**调用点在**领取**路径」—— 实际已是**两处**
>    （领取腿 `ops/builtin/zcode_claim.py:122` ＋ 额度腿 `upstream/zcode/product.py:570-578`）。
>    方案 §9-2 第 3 条要求的"`out.py` 登记同批改述"**未随实施轮落地** ⇒ 源码注释待改，本文 §17 已按两调用点改述并明写"改述前不要引用那句"。
> 2. **三处旧口径仍在码内**：① `upstream/zcode/quota.py:555-556`（`CooldownManager` docstring「⚠️ 熔断**不拦额度读取**：
>    `query_balance` 走的是客户端日志通道…零上游请求、零签名」= 额度腿上网后**错的护栏**）；
>    ② `quota.py:7`（模块头"三通道"表仍以「客户端日志 ⭐ 主用 …（联网请求需 `X-Client-Sig/Nonce/Pow`…脚本无法复刻）」为第一优先）；
>    ③ `api/admin.py:446`（`GET /admin/api/zcode/quota` docstring「数据源优先级（§17）：**客户端日志**（绕开签名风控）→ 该账号旧快照 → 联网兜底」）。
>    **只有** `read_account_snapshot` 的函数 docstring 已改述（`quota.py:284-295`）。⇒ 本文按代码事实写"哪条腿是什么身份"，源码注释清理另案。
> 3. **机理措辞与代码不符**：【探针台账】§7.3 与方案 §0.1 都写「`Scheduler.loop()` 是"**跑完再等**"」，
>    实际 `ops/runner.py:712-726` 是**先 `await asyncio.sleep(period)`、再判 `_should_fire`、再跑整轮**
>    （码内注释原话「先等一个周期再跑」）。两种说法的周期都 = `sleep` ＋ 一轮耗时，结论不变，但本文以代码措辞为准。
> 4. **有效 tick 数值取哪个**：台账 §7.3 记 ≈240s、工程杆独立实测 292s。本轮从同一份
>    `data/usage/ops-results-20261002.jsonl`（340 行）复核 = 一轮内两腿写入差中位 **57s** ＋ 同腿间隔中位 **235s**
>    ⇒ **轮周期 ≈292s**（240s 那一档是把"同腿间隔"误当轮周期）。本文取 ≈292s 并附了可复跑的折法。
> 5. **`BillingResult.kind` 值域**：代码含 **`risk_control`** 档（`upstream/zcode/billing.py:60`，判定
>    `billing.py:117-123`），方案 §3-1 原文写「`kind ∈ {ok, no_plan, expired, unreachable}`（**无 `circuit`**）」⇒
>    语义一致（**熔断仍只由调用方 `product.py:570-578` 建立**，`billing` 不 `enter()`），字面不同，以代码为准。
> 6. **手动产品级腿的 1.2s/抖动是靠缺省拿到的**：`api/admin_accounts.py:1042-1043` **不显式**传
>    `delay_s/jitter`，取 `ops/runner.py:415-416` 的缺省（`DEFAULT_DELAY_S=1.2`、`jitter=True`）——
>    与方案 §5-2 字面"端点写 `delay_s=1.2, jitter=True`"效果同值，本文按代码写（单账号腿才是显式 `0.0/False`，`:1003-1005`）。
> 7. **悬空引用**：【探针台账】§6.4 两处（`:141`/`:145`）、以及码内注释 `upstream/zcode/quota.py:137` 与
>    测试注释 `coding/tests/accounts/test_zcode.py:433` 引用的「【探针台账】§7.1」
>    在 r5 修订"删重复 §7"后**该节已不存在**（台账现在只有 §7 / §7.2 / §7.3 / §7.4）⇒
>    「2961/2961 条日志记录带 `payload`、0 条带顶层 `data`」的原据实际落在台账 **§4 表首行**与 **§6.4**，本文引用改指这两处；台账侧待补一行。
> 8. **归档链未完成（不属本文范围，但如实登记）**：PRD 现为 **v1.19**、全文 `Q32` **0 命中**
>    （方案 §9-1 要求的 PRD 归档未落地）；交付台账 `docs/changes/e2e-records/E2E-20261002-zcode-quota-refresh.md` **不在盘**。
>    ⇒ 本轮写入本文的一切"已落码"结论，其证据**只有代码 `file:line` ＋ 探针台账**；
>    **全量 pytest / 静态门 / 真机门 / :8300 活实例终验在本轮未复跑** = **未验证**，
>    任何小节都不得被读成"已验收"。（另注：`docs/` 在本仓 `.gitignore:21` 内 ⇒ 本文改动无 git diff 可附，证据 = `file:line` 与 grep 输出。）

## §5.4 承接资格闸门与风控分类归一（2026-10-05 · PRD Q39）

> 只登记本轮改动的**机制落点**；判据与实盘/隔离读数在
> `docs/changes/e2e-records/E2E-20261005-zcode-glm-flash-failover-test.md` §6/§7。

| 落点 | 改了什么 | 为什么在这里 |
| --- | --- | --- |
| `core/resources.py::QuotaPool.entitled` | 额度池加**第三个位**（缺省 `True`），`available()` 与 `reserve_quota()` **两条路**都读它；写入按 **rid 共享池**粒度（`set_entitled`） | 资格是**账号级**事实，与 `remaining` 同粒度；只挡选路侧不挡预留侧 = 有路径绕过时照样发。缺省必须宽松，否则新接入即被误封 |
| `upstream/zcode/quota.py::entitled_from_snapshot` + `apply_remaining_to_runtime(..., entitled=)` | 只有 `reason == "no_plan"` 返回 `False`；`state ∈ {available, exhausted}` 且 `reason` 空 ⇒ `True`（恢复）；其余（`unreachable/circuit/expired/no_credentials/no_identity`）⇒ **`None` = 不动**。关键结构修正：`remaining is None` 的早退**不能再顺手跳过资格位**（`no_plan` 的 `remaining` 恰是 None，旧早退就是那条漏网） | 额度回写的**唯一实现**（离线面与联网腿共用），在这里分叉就会造出"两条路径算了两种额度"的老问题 |
| `ops/builtin/query_balance.py::_apply_zcode_quota` | 联网腿把 `entitled_from_snapshot(snap)` 一并传入 | 资格位的**唯一生产者**就是这条联网腿；不接上 = 判据永远是死代码 |
| `core/errors.py::RISK_CONTROL_TYPE` + `classify()` 第 3b 步 | 归一化 type ⇒ `RETRYABLE`；排在 `error_rules` 与厂商 type 表**之后**、HTTP 通用映射**之前** | 某产品要改判据走配置覆写即可，不必动代码（§4.3 既有优先级不变）；FR-3.13 的 400 语义**一字未放宽** |
| `upstream/zcode/out.py::_as_risk_control` | 信封 `code ∈ {3012, 3007}` / `looks_like_risk_control(msg)` / HTTP 405 ⇒ 打上归一化 type；`status_code ∈ {401,403,404,408,429}` **不接管** | 抢 401 会把"401→停用"的终态判定改成可重试（既有单测钉着）；这是**分类正确**，不是新增跳过分支 |
| `adapters/anthropic_out.py::_shape_error` + `_looks_like_message` | 2xx 但 JSON 不是一条消息 ⇒ `UpstreamError(status_code=None)`；流式请求被回非 SSE 的 JSON ⇒ 同一判据 | 与既有 `_non_json_error`（2xx 非 JSON/SSE）同一条立意：200 ≠ 取到了。旧形状产出的是"空正文 + `success` + C 被清零" |
| `api/openai_compat.py` 零内容兜底分支 | `_sse(_finish_only())` → `_finish_only()`（**模块里从来没有 `_sse()`** ⇒ `NameError` 冒穿成未分类 500，而事件行已记 `success`） | 这条兜底自写下就零覆盖（既有"空流"用例只钉出站体带没带 `stream:true`）；本轮由 zcode 的 200 信封形状实测打穿 |

🔴 **两条没动、也不该顺手动的**：① `unservable_reason`（前提缺口判据）**仍只管对外声明**，
没有接进 `rebuild()`/派发 —— 把它接进去就是 Q35-③ 禁止的"隐藏它"；② 冷却时长
（`cooldown_seconds_plan=18000`）未调 —— 现在坏号会被冷却了，一个持续风控的号会锁 5 小时，
这属于产品口径，等用户裁定（台账 §7 待裁定 R-5）。

### §5.4b 量纲阈值（PRD Q39-④，2026-10-05 同日补充）

新模块 **`core/quota_policy.py`** 是「承接资格」判据的**唯一实现点**（含阈值表），两条腿都调它：

| 量纲 | 识别串（`strip().lower()`） | 阈值 | 触底方向 |
| --- | --- | --- | --- |
| token | `token` / `tokens` | **10000** | 余量 `< 10000` ⇒ 剔出；`>= 10000` ⇒ 留 |
| 积分 | `credit` / `credits` / `积分` / `点` | **50** | 同上；实盘数值**常为小数**，比较不按整数写 |
| 认不出 | `""` / `times` / 其他 | **无** | **不设阈值**（宁可宽松，不编数量纲） |

判定顺序：`no_plan` 否认 → `below_floor()`（逐包，`active=False` 与 `remaining=None` 都不参与）→
正向三态 → `None`（没查到 ⇒ 一位都不动）。放 `core/` 的理由：阈值按**量纲**走而量纲是跨产品的
（zcode=token，buddy/lobsterai/loomy/trae/workbuddy/qoder=积分），长在 `upstream/<product>/`
里必然长成"两条路径判两种资格"；`core/` 不 import `upstream/`、`accounts/`，只吃快照的鸭子形状
（账号层 `items` 与 zcode 层 `buckets` 两种证据归一成同一张逐包清单）。

🔴 这一格把通用体也接上了闸门：`_apply_quota_to_pools` 的通用体此前**只写三态、从不写资格位**，
所以"积分制 <50"这类规则若不接这里，非 zcode 产品永远不会被阈值挡住。
边界与代价：资格位的**生产者只有额度刷新腿**（zcode 联网腿 / 通用三态体，含 `ops/builtin/query_balance.py`
与启动那次对齐），重启后到第一轮 tick（≤60s）之前仍是"未知 ⇒ 放行"（既有设计，登记为 R-6）；
总览「可用」视图位不含资格（债 **Q39-债1**，与 D-7 同族，属独立一刀，本轮不动界面）。
