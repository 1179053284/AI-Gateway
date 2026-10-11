# 终局复核报告 · `tech-design.md` §12–§21（增量设计 v2.0）

> 复核人：独立复核员（职责 = **证伪**，非确认）
> 复核日期：2026-09-26
> 复核对象：`docs/specs/tech-design.md` §12–§21（行 681–1447，修正后版本）
> 对照清单：`reviews/PM-review.md`（17 条）/ `reviews/eng-review.md`（18 条 + O-1–O-3）/ `reviews/ix-review.md`（13 条）
> 判据：**每条结论必须能回溯到 `文件:行号`**；只读，未修改任何文件。
> 核实方式：逐条读修正后正文 + 直接读源码/脚本/模板/PRD 原文核对引用行号。

---

## 1. 总结论

**有遗漏，但无"未修"项；有 1 处"改错了"。**

- 48 条编号问题：**✅ 已修 45 条 / ⚠️ 部分 3 条 / ❌ 未修 0 条 / 🔴 改错 0 条（但 PM S1 内嵌 1 处改错）**。
- 3 条部分：**PM S1**（补了路径 A，但目录解析规则**改错**）、**PM L2**（§20 补 2/3）、**IX M-IX-1**（补了 `import` 子命令与 3 选项契约，但 §15.1↔§15.2 口径**未真正对齐**，反而引入新矛盾）。
- 修正整体质量高：三份报告的 8 条严重问题中 7 条完全修好；eng-review 的 18 条全部修好（含 3 处依赖倒置、空壳报告、`errors.py` 语义约定）。
- **新引入的问题**：4 条（1 条较重要 + 3 条轻微），详见 §3。最需处理的是 **PM S1 的修正本身违反 PRD Q25-⑨**。
- **自洽性**：§12–§21 内部 1 处硬矛盾（§15.1↔§15.2）+ 1 处口径松（§16.4↔§16.6）；与 §1–§11 基本对齐（§4.4 已同步、§7 已补）；与 PRD Q26/Q27 对齐，与 Q25 有 1 处冲突未回填（Q25-①）。

---

## 2. 逐条验证表

### 2.1 产品经理报告（PM-review.md，17 条）

| # | 问题摘要 | 判定 | 证据（修正后） |
|---|---|---|---|
| **S1** | 路径 A（`mgw setup` 文件下发）+ Q25-⑨ 目录解析规则整体缺失 | ⚠️ **部分（含 🔴 改错）** | 已补：`tech-design.md:788-842`（§12.4 两条路径 + §12.4.1 目录解析 + 写入纪律）；`tech-design.md:1362`（M3-5）。**但目录解析规则改错**：`tech-design.md:804` 写「`productName` **含** "workbuddy" → `~/.workbuddy/`」—— 这正是 PRD Q25-⑨ **明文禁止**的子串判断（`prd.md:592`：「不得依赖 `isWorkBuddyProduct()` 之类子串判断…必须按『产品标识 → `dataFolderName`』解析（WorkBuddy=`.workbuddy`，WorkBuddy AI=`.workbuddy-ai`）」）。`dataFolderName` 在全文**零命中**（已 grep 确认），且该规则**无法解析出 `.workbuddy-ai`**（与设计自己记录的踩坑目录 `tech-design.md:808` 相矛盾） |
| **S2** | §16.4 漏「双层互斥」 | ✅ 已修 | `tech-design.md:1124`（plan 级 `TryLock` + 账号级 `claimLockFor`，与 `prd.md:681` 对齐）；M5-1 判据补「并发触发断言只领一次」`tech-design.md:1368` |
| **S3** | 验证码求解 + 住宅代理无落点/无披露 | ✅ 已修 | `tech-design.md:1134-1160`（§16.5 全节：Playwright / 同进程 + `asyncio.Lock` / 30s 超时 / 硬依赖住宅代理 / 用户侧落点 / §20 #19 备选二选一）；M5-1 判据补降级 `tech-design.md:1368` |
| **M1** | §12 字段名与 PRD Q25-② 不一致且未标注 | ✅ 已修 | `tech-design.md:721-724`（注：以工具契约 camelCase 为准 + 声明 PRD 需回填） |
| **M2** | `thinkingLevelMap` 必须 7 键齐全、不支持写 `null` | ✅ 已修 | `tech-design.md:726-739`（§12.2a 全节）+ 代码 `tech-design.md:762-765`（7 键正向生成） |
| **M3** | §15.2 `DeviceIdentity(Protocol)` 与 §20 #14 矛盾 | ✅ 已修 | `tech-design.md:1028-1048`（删除 Protocol/`base.py`，函数直接落 `upstream/zcode/dataroot.py`）；`tech-design.md:1396`（§20 #14 保留） |
| **M4** | §14.1「新增 UI」与 §20 #12 冲突 | ✅ 已修 | `tech-design.md:960-962`（裁决「保留字段、砍掉界面」）+ `tech-design.md:1397`（§20 #15） |
| **M5** | 签到/领取落点冲突（§17 vs 19 D27） | ✅ 已修 | `tech-design.md:1162-1169`（§16.6 归属表 + 边界一句话） |
| **M6** | 排期两处依赖倒置 | ✅ 已修 | `tech-design.md:1350-1353`（说明）+ `tech-design.md:1359-1361`（M3-2 先出 7 字段 → M3-3 探测 → M3-4 补 caps）+ `tech-design.md:1365-1366`（M4-3 鉴权 → M4-4 额度）。**已复核无残留硬倒置**（见 §4） |
| **M7** | Q26-①「全新自洽画像」与 §20 #8 字面冲突 | ✅ 已修 | `tech-design.md:1390`（§20 #8 限定「ZCode 首期」+ 注明 Q26-① 适用 trae/qoder）+ `tech-design.md:1070-1072`（§15.3 措辞限定） |
| **M8** | 缺替代操作入口（能跑没法用） | ✅ 已修 | `tech-design.md:1367`（M5-0 `mgw zcode login/import/list/claim`）+ `tech-design.md:1357`（M3-0 骨架） |
| **L1** | §12.3 引用不存在的 `entry.caps` | ✅ 已修 | `tech-design.md:778-781`（边界说明：「`caps` 是本次新增的组装结果，`EnumEntry` 无 `caps` 字段（勿误引）」） |
| **L2** | Q25-⑩ 的「不做」未进 §20 | ⚠️ **部分** | 已补 3 条：`tech-design.md:1397`（#15 L-B/L-C 录入界面）/ `:1398`（#16 GUI 自动化）/ `:1399`（#17 不代用户登录）。**但 Q25-⑩ 第 1 项「不做按模型的调度参数拆分」（`prd.md:595`）仍未进 §20**（§20 全 19 行已逐条核对，无对应条目） |
| **L3** | 零映射告警（最便宜收益）排最后 | ✅ 已修 | `tech-design.md:1358`（提前为 M3-1） |
| **L4** | M4-1（P0 硬阻塞）排 M3 之后 | ✅ 已修 | `tech-design.md:1363`（M4-1 置 M4 首项，注明「ZCode 唯一硬阻塞，提到最前」）+ `tech-design.md:1351` |
| **L5** | Q26-② 代次轮换未归档 | ✅ 已修 | `tech-design.md:1400`（§20 #18） |
| **L6** | Q26-③ 重试/per-op 声明未体现 | ✅ 已修 | `tech-design.md:1126`（仅网络/5xx 重试、业务码不重试）+ `tech-design.md:1129`（per-operation 声明 `supported_products`） |

### 2.2 研发工程师报告（eng-review.md，18 条）

| # | 问题摘要 | 判定 | 证据（修正后） |
|---|---|---|---|
| **P0-1** | §12.3 伪代码引用不存在字段 + 类型用错 + 无 None 兜底 | ✅ 已修 | `tech-design.md:754`（`EnumPool.get()`，已核 `matcher.py:217`）/ `:762-765`（`effort_levels` 是 `list[str]`，正向生成，已核 `matcher.py:34`）/ `:756-760`（`entry is None` 降级最小字段集）/ `:771-773`（`thinkingFormat` 从方言表取）。**旧符号 `match_enum` / `entry.thinking_format` / dict 解包 均已消失** |
| **P0-2** | `mgw` CLI 不存在 + M3 依赖 M5 | ✅ 已修 | `tech-design.md:840-842`（承认原稿事实错误 + 需新建入口）+ `tech-design.md:1357`（M3-0 骨架，已核 `pyproject.toml` **确无** `[project.scripts]`） |
| **P0-3** | M4-2 判据「主 `~/.zcode` 不被写」不可达 | ✅ 已修 | `tech-design.md:1364`（判据改为三件未写入 + `setting.json` 已知例外不计入 + 设备唯一性）+ `tech-design.md:1061-1063` |
| **P1-1** | §18 未定义分发点/契约/usage 映射 | ✅ 已修 | `tech-design.md:1294-1317`（① duck typing 4 方法 ② 分发点 `main.py:95-105`/`admin.py:291` ③ usage 契约）。**行号已核**：`main.py:95-105` 确为无条件构造 `OpenAIOutAdapter`；`admin.py:291` 确为 `OpenAIOutAdapter(base_url)`；`scheduler.py:274-277` 确只认 `prompt_tokens`/`completion_tokens` |
| **P1-2** | 2xx 非 JSON/SSE 语义分类器表达不了 | ✅ 已修 | `tech-design.md:1330-1340`（抛 `UpstreamError(status_code=None)` + 写明约定）。**已核** `errors.py:100-101`（`status_code is None` → `RETRYABLE`）、`errors.py:127`（`status=200` → `BAD_REQUEST`） |
| **P1-3** | 幂等码 10001 属别的产品；ZCode 是 1003/1005 | ✅ 已修 | `tech-design.md:1112-1116`（按产品分表：ZCode 1003/1005、buddy/DSH 10001）+ `tech-design.md:1195-1198`（operation 名改 `zcode_claim`） |
| **P1-4** | 方言表与热重载关系未定义 | ✅ 已修 | `tech-design.md:932-938`（加载时机表：启动一次 + `mgw probe` 后显式重载 + 不加 watcher）。**已核** `main.py:237-255` 只监听 `config_path` |
| **P1-5** | §17「复用 `pick_and_acquire`」冲突 + 熔断未接路由 | ✅ 已修 | `tech-design.md:1232`（范围限定）+ `tech-design.md:1234-1248`（熔断/额度回写 `ResourceState.status`）。**已核** `resources.py:63-64`（`available()` 只看 status/enabled）、`resources.py:151/156/49`（`bench`/`disable`/`last_error` 真实存在） |
| **P1-6** | S2 判据未限定锚点/采样次数 | ✅ 已修 | `tech-design.md:882-906`（只发 `none`/`off` 单锚点 + 说明 22–61 无重叠区间） |
| **P1-7** | 验证码求解进程模型/超时/生命周期未定义 | ✅ 已修 | `tech-design.md:1141-1146`（同进程 + `asyncio.Lock` + 30s `wait_for` + 进程级复用 + `try/except` 不 re-raise） |
| **P1-8** | `curl_cffi` async 流式 + 与 httpx 统一未闭合 | ✅ 已修 | `tech-design.md:1253-1259`（`auth.py` 统一提供并注入 + T5a/T5b + 降级链） |
| **P2-1** | §12.4 路径 A 缺原子写 | ✅ 已修 | `tech-design.md:835`（tempfile + `os.replace`，注明与 `admin.py:404-412` 同口径；**行号已核**为真实原子写） |
| **P2-2** | §12.2a 与 §13.1 对 `ultra` 未裁决 | ✅ 已修 | `tech-design.md:863-871`（§13.1 `ultra` 归属裁决表） |
| **P2-3** | §15.3 未内联 caveat + 待实测清单缺口 | ✅ 已修 | `tech-design.md:1054-1059`（两个 caveat）+ `tech-design.md:1372-1373`（补 T10） |
| **P2-4** | 无目录属性模型下发 `null` 未说明 | ✅ 已修 | `tech-design.md:780`（「目录缺某属性时输出 `null`…不臆造数值」）。**已核** `matcher.py:138-141` `claude-sonnet-4`/`claude-opus-4` 确无 `context_window`/`max_output` |
| **P2-5** | ops 与 scheduler 各写一份退避 + 需加固边界 | ✅ 已修 | `tech-design.md:1171-1177`（不 import `core/scheduler`、不 import `ErrorClassifier`、自建 6 行 + 退避序列）。**已核** `errors.py:127` 确会把 400+1003 判成 `BAD_REQUEST` |
| **P2-6** | 额度刷新触发时机未定义 | ✅ 已修 | `tech-design.md:1261-1269`（三触发点 + 不新建独立定时器） |
| **P2-7** | §7 目录结构未同步更新 | ✅ 已修 | `tech-design.md:527-541`（§7 已补 `upstream/`、`ops/`、`cli.py`；`upstream/zcode/__init__.py` 亦列）。*残留：§17 树 `tech-design.md:1206-1221` 未列 `__init__.py`（§7 已列，属冗余一致性问题，非功能缺陷）* |
| **O-1** | §18.2「强制 `stream:true` 再聚合」过度设计 | ✅ 已修 | `tech-design.md:1319-1325`（已删，改为与 `openai_out` 同形） |
| **O-2** | §13.3 S2「逐档比数值」过度设计 | ✅ 已修 | `tech-design.md:900-906`（收敛为单锚点） |
| **O-3** | `caps_overrides` 无使用者 | ✅ 已修 | 采纳「保留字段（成本≈1 行，探测失败逃生口）」`tech-design.md:958-978`；eng 原判即为「可保留」，不构成缺陷 |

### 2.3 交互与视觉报告（ix-review.md，13 条）

| # | 问题摘要 | 判定 | 证据（修正后） |
|---|---|---|---|
| **S-IX-1** | 零映射告警写日志 = 用户看不见 | ✅ 已修 | `tech-design.md:1405-1447`（新增 §21 全节）+ `tech-design.md:1430`（告警进 `/admin/api/overview` 的 `warnings[]` + 两类文案）+ `tech-design.md:1358`（M3-1 判据改为断言 `warnings[]`）。**启动脚本行为已核**：`启动网关.command:6-7,21,71-88`（nohup/自动关窗/日志路径均属实）。⚠️ 见 §3 新问题 #3 |
| **S-IX-2** | 运营 `failed` 无用户可见出口 | ✅ 已修 | `tech-design.md:1179-1188`（§16.6 结果出口表：JSONL 落盘 + `mgw zcode claim` 打印 + 顶栏红点）+ `tech-design.md:1431`（§21.2 #2）。**已核** `/admin/api/status` 真实存在且为顶栏 5s 轮询（`admin.py:110-112`、`design-spec.md:181`） |
| **M-IX-1** | 设备冲突未定义 + `import` 子命令缺失 | ⚠️ **部分（引入新矛盾）** | 已补：`tech-design.md:1010-1022`（3 选项交互契约 + 默认取消 + 退出码非 0）+ `tech-design.md:1367`（M5-0 加 `import`）。**但未真正对齐**：§15.1 约束 1 写「冲突则**重新生成**（有上限）」`tech-design.md:1006`，§15.2 `check_device_id_unique` docstring 写「冲突时由调用方**拒绝并交用户决策**」`tech-design.md:1045` —— 同一「硬约束 1」给出相反口径；且 §15.1 的对齐说明 `tech-design.md:1024-1026` 引用的「§15.2 写的『冲突则调用方重新生成』」**已不存在于 §15.2** |
| **M-IX-2** | `mgw setup` 破坏性写盘缺路径确认 | ✅ 已修 | `tech-design.md:821-831`（写入纪律 0：写前打印解析路径+来源、`--yes`、`--dry-run`、成功/失败/回滚三句文案） |
| **M-IX-3** | 额度聚合端点消费者/用词冲突 | ✅ 已修 | `tech-design.md:1369`（M5-2 改为 `GET /admin/api/zcode/quota` + 响应形状 + 消费者=二期「用量」面板 + 明确「不做对外端点」） |
| **M-IX-4** | 熔断回写后用户无法分辨原因 | ✅ 已修 | `tech-design.md:1242-1248`（统一 `bench` + 写 `last_error` 文案 + 全局熔断范围口径）。**已核** `design-spec.md:192-193` 资源健康卡确有「最近错误」列 |
| **M-IX-5** | 验证码/住宅代理无配置入口/无提示 | ✅ 已修 | `tech-design.md:1148-1154`（配置项 `gateway.zcode.proxy` + 环境变量回退 + 未配置显式提示 + `--manual`） |
| **M-IX-6** | `mgw probe` 无确认/进度/结果输出 | ✅ 已修 | `tech-design.md:908-922`（CLI 交互契约：确认提示 + 逐模型即时打印 + 结束计数） |
| **M-IX-7** | 二期 UI 落点未记录 | ✅ 已修 | `tech-design.md:1394`（§20 #12 补二期落点：骨架 A + 复用 `template-vendor-accounts.html`（T-17·2119 行·5 页签））。**已核**：模板真实存在、2119 行、标题「T-17 · 多端账号授权」、5 页签（账号/授权/模型/体检/用量）、`frontend-spec.md:149` 确为「A · 子侧栏双面板页」 |
| **L-IX-1** | §16.4 引用「UI 手动」与首期不做 UI 冲突 | ✅ 已修 | `tech-design.md:1124`（改为「防 **CLI / 管理端点手动**与 cron 并发双领」） |
| **L-IX-2** | `caps_overrides` 缺 YAML 形状 | ✅ 已修 | `tech-design.md:964-978`（YAML 片段 + 注明 mtime 热重载生效；**已核** `design-spec.md:104` 确为「界面与文件双向一致 + 1s mtime 热重载」） |
| **L-IX-3** | 四类结果 CLI 呈现未定义 | ✅ 已修 | `tech-design.md:1095-1107`（按类分组 + 仅 `✗` 着色 + 无失败末行） |
| **L-IX-4** | §12.4.1 失败只写「回滚」 | ✅ 已修 | `tech-design.md:829-831`（成功/回滚/路径三句文案，并入写入纪律 0） |

**统计：✅ 45 / ⚠️ 3 / ❌ 0 / 🔴 0（PM S1 内嵌 1 处改错）。**

---

## 3. 新引入的问题

### 3.1 🔴 较重要：PM S1 的修正**违反它自己引用的 PRD Q25-⑨**

- **位置**：`tech-design.md:801-806`（§12.4.1 目标目录解析），关键行 `tech-design.md:804`：「`productName` **含** "workbuddy" → `~/.workbuddy/`」
- **PRD 原文**：`prd.md:592` ——「目标目录**必须按『产品标识 → `dataFolderName`』解析**（WorkBuddy = `.workbuddy`，WorkBuddy AI = `.workbuddy-ai`）；**不得依赖 `isWorkBuddyProduct()` 之类子串判断**（实测其实现为 `includes("workbuddy")`，对两产品均返回 true）」
- **问题**：`tech-design.md:804` 用的正是被禁的子串判断；`dataFolderName` 在全文**零命中**；该规则**永远推不出 `.workbuddy-ai`** —— 而设计自己在 `tech-design.md:808-810` 记录「本机被劫持到 `/Users/w/.workbuddy-ai`」。即：踩坑记录说要看 `.workbuddy-ai`，解析规则却只会给出 `.workbuddy`。
- **结论**：PM S1 的交付**不满足** Q25-⑨（「必须按 dataFolderName 解析」未做）。建议 §12.4.1 改为「按产品标识 → `dataFolderName` 解析」，删除子串判断。

### 3.2 ⚠️ §15.1 与 §15.2 对「硬约束 1」口径相反，且对齐说明引用已失效原文

- `tech-design.md:1006`（约束 1 机制）：「分配时生成 → 查唯一性 → **冲突则重新生成**（有上限，不静默降级）」
- `tech-design.md:1045`（`check_device_id_unique` docstring，标注「硬约束 1」）：「**冲突时由调用方拒绝并交用户决策**（不静默重生成）」
- `tech-design.md:1024-1026`（对齐说明）声称「§15.2 写的『冲突则调用方重新生成』仅适用于『生成新账号』路径…两处已对齐」—— 但 §15.2 **已不再写这句话**，说明与正文脱节。
- **结论**：M-IX-1 的修正方向对（补 3 选项、补 `import`），但**没有真正消除矛盾**，只是把矛盾从「§15.1#3 vs §15.2」搬到了「§15.1#1 vs §15.2」。

### 3.3 ⚠️ §21.2 / §16.6 引用的响应字段**当前不存在**（传输机制真实，字段需新增且未标注）

- `/admin/api/overview` 的 **`warnings[]`**：**不存在**。`admin.py:122-161` 的 overview 返回体无 `warnings` 键；`tech-design.md:172`（§4.4 的 overview 契约）也未列。`tech-design.md:1430` 与 `:1358` 以「✅ `/admin/api/overview` 的 `warnings[]`」表述，**未注明这是需新增的字段**。且项目已存在一个**同名不同义**的 `config.warnings`（`schemas.py:217`，暴露在 `/health`，`main.py:193`）→ 有混淆风险。
- `/admin/api/status` 的**失败计数/红点**：**不存在**。`admin.py:114-119` 的返回体只有 `version`/`uptime_ms`/`in_flight_requests`/`resources`；`tech-design.md:1185`、`:1431` 要求「`failed` 累计进 `/admin/api/status` → 顶栏红点」，需新增字段 + 前端红点，设计未标注。
- **对照**：§21 引用的**传输机制均真实** —— `.alert-warn` 存在（`web/static/css/base.css:890`、`frontend-spec.md:473`）；顶栏 5s 轮询存在（`admin.py:110-112`、`design-spec.md:181`）；启动脚本行为属实（`启动网关.command:6-7,21,71-88`）。
- **建议**：§21.2 明确标注「overview 新增 `warnings[]`（当前无此字段；勿与 `config.warnings` 混淆）」「status 新增未读失败计数」。

### 3.4 ⚠️ §12.2 的跨章引用**指向错误的 M 编号**

- `tech-design.md:724`：「PRD Q25-② 的 snake_case 写法与"顶层 effort_levels"需回填修正（**已记入 §19 M3-1 判据**）」
- 实际：M3-1 = 零映射告警 + 前缀剥离（`tech-design.md:1358`），与能力位无关；能力位字段下发是 **M3-2**（`tech-design.md:1359`），其判据也未提「PRD 回填」。→ 该跨章引用因排期重排而失效（应指向 M3-2）。

### 3.5 低严重度（列而不铺陈，均已核实）

| # | 位置 | 问题 | 证据 |
|---|---|---|---|
| a | `tech-design.md:5` | changelog 写「伪代码引用不存在的 `EnumField`」——**实际不存在的符号是 `entry.thinking_format`**（eng P0-1）；`EnumField` 全仓**零出现** | `grep EnumField` 仅命中该行；eng-review.md:38,75 |
| b | `tech-design.md:165`（§4.4） | 仍标「`anthropic_out`（P1）」，与 §7 `:525`（「P1 → **v2.0 提为 P0**」）及 §18（P0）不一致 | 三处对照 |
| c | `tech-design.md:1206-1221`（§17 树） | 未列 `upstream/zcode/__init__.py`（§7 `:529` 已列） | 两处对照 |
| d | `tech-design.md:950-962`（§14.1） | 裁决「砍界面」符合 Q25-⑩，但**未像 §12.2 那样标注「PRD Q25-① 字面需回填修正」**——`prd.md:567` 仍写「UI 仅新增默认折叠的『高级·能力覆盖』」 | `prd.md:567` vs `tech-design.md:962` |

---

## 4. 自洽性抽查结果

### 4.1 §12–§21 内部

| 检查项 | 结果 | 证据 |
|---|---|---|
| 7 档规范序三处一致 | ✅ | `tech-design.md:737` / `:749` / `:858`（off/minimal/low/medium/high/xhigh/max）与 `prd.md:573` 一致 |
| `mgw` 子命令集合前后一致 | ✅ | 使用处：`setup`（`:838,:1362`）、`probe`（`:911,:1360`）、`zcode claim`（`:1098,:1184,:1431`）、`zcode login/import/list/claim`（`:1367`）、`--reuse/--regenerate`（`:1017-1018`）、`--manual`（`:1154`）、`--yes/--dry-run`（`:829`）——**全部有定义处，无未定义子命令** |
| §15.1 ↔ §15.2 设备冲突口径 | ❌ **不一致** | 见 §3.2 |
| §16.4 ↔ §16.6「空跑」口径 | ⚠️ 措辞松（可解释，非硬冲突） | `:1127`「空跑算成功（避免 0/N 误报 failed）」vs `:1188`「`len(accounts)==0` 不得报 `success`，应记 `inactive`」。二者可读作「N>0 无失败」与「N=0」两场景，但同一术语「空跑」在相邻两节含义不同，建议统一措辞 |
| 模块落点 upstream vs ops | ✅ | `:1166-1169`、`:1216`、`:1220` 三处一致（HTTP 交互在 `upstream/zcode/claim.py`，调度在 `ops/runner.py`） |
| §19 依赖顺序（重点复核） | ✅ **无硬倒置** | M3-0→M3-1→M3-2→M3-3→M3-4→M3-5；M4-1→M4-2→M4-3→M4-4；M5-0→M5-1→M5-2→M5-3。三处原倒置均已修（`:1350` 自述；已逐条核）。*唯一软疑虑（低置信，附反方）：M4-3 为手工 E2E、需真实凭据，而账号登录命令 `mgw zcode login` 在 M5-0（M4 之后）；但登录能力本体属 M4-2 的 `upstream/zcode/oauth.py`，可用脚本直调，故**不构成硬阻塞**，仅提请注意* |

### 4.2 §12–§21 与 §1–§11 既有架构

| 检查项 | 结果 | 证据 |
|---|---|---|
| 适配器接口口径 | ✅ 已同步修正 | `tech-design.md:166-169`（§4.4 加「口径修正（v2.0 审核发现）」）——eng P1-1 的附带项已做 |
| §4.4 overview 契约 vs §21 `warnings[]` | ❌ 不同步 | `:172` 无 `warnings`；见 §3.3 |
| §7 目录结构 | ✅ 已同步 | `:527-541` 补 `upstream/`、`ops/`、`cli.py`、`__init__.py` |
| `anthropic_out` P0/P1 标注 | ⚠️ 不一致 | §4.4 `:165`（P1）vs §7 `:525` / §18（P0）；见 §3.5b |
| 熔断回写复用既有 `bench`/`disable`/`last_error` | ✅ | `resources.py:151/156/49` 真实存在；`:1239` 引用正确 |
| `/v1/models` 追加不破坏既有 6 字段 | ✅ | `openai_compat.py:39-44` 为 dict 字面量，追加键安全（与 `:745` 自述一致） |

### 4.3 §12–§21 与 PRD Q25/Q26/Q27

| 检查项 | 结果 | 证据 |
|---|---|---|
| Q25-①（UI 仅新增「高级·能力覆盖」） | ⚠️ 设计已裁决砍界面，但 **PRD 未回填** | `prd.md:567` vs `tech-design.md:960-962`；见 §3.5d |
| Q25-②（8 字段） | ✅ 已标注 PRD 需回填 | `tech-design.md:721-724`（但 M 编号引用错，见 §3.4） |
| Q25-③④⑤ | ✅ | `:855-871` / `:873-880` / `:882-944` 与 `prd.md:573/576/579` 一致 |
| Q25-⑥ | ✅ | `:980-996`（只加 `product` 列，本次只做阶段一，与 `prd.md:584` 一致） |
| Q25-⑦⑧ | ✅ | `:1358`（M3-1 前缀剥离 + 零映射告警） |
| Q25-⑨ | ❌ **违反** | `tech-design.md:804` 子串判断 vs `prd.md:592` 明禁；见 §3.1 |
| Q25-⑩ | ⚠️ 第 1 项未归档 | 见 PM L2 |
| Q26-①（画像） | ✅ 已限定范围 | `:1070-1072`、`:1390` |
| Q26-③（幂等码/重试/per-op） | ✅ | `:1112-1116`、`:1126`、`:1129`（与 `prd.md:633-636` 一致，且修正了 10001 张冠李戴） |
| Q26-⑤（D12–D15 延后） | ✅ | `:1400`（§20 #18） |
| Q27-①（验证码） | ✅ | `:1134-1160` |
| Q27-④（双层互斥） | ✅ | `:1124`（与 `prd.md:681` 逐字对齐） |
| Q27-⑦（`anthropic_out` P0） | ✅ | `:1277-1290`（空壳描述与实测吻合：`anthropic_out.py`=1 行、`gemini_out.py`=1 行、`base.py`=5 行、`openai_out.py`=207 行、`main.py:28`/`admin.py:34` 为仅有两处 import） |

---

## 5. 诚实声明（无法核实项及原因）

1. **research 文档的具体行号未逐条打开**：`docs/research/08·10·14–19` 不在必读清单内，其行号（如 `08 §5 O2`、`research/04:134`、`research/17:234`）**未逐条核对**。但其中可独立验证的关键结论已用源码/配置直接证实（如「无 `[project.scripts]`」已由 `pyproject.toml` 直接确认；「`errors.py` 会把 400+1003 判成 `BAD_REQUEST`」已由 `errors.py:127` 直接确认）。
2. **外部网络未访问**：`curl_cffi` 官方文档（async 流式是否可用）、阿里云无痕验证码行为、ZCode 上游契约 —— 均无法核实，只能确认「设计已把其列为待实测（T5a/T5b/T10）」。
3. **尚不存在的设计物只能验证「当前不存在」，不能验证「设计正确」**：`data/dialects.json`、`data/ops-results-*.jsonl`、`model_gateway/upstream/`、`model_gateway/ops/`、`model_gateway/cli.py`、`overview.warnings[]`、`/admin/api/zcode/quota` —— 均已确认当前不存在（符合"增量设计"定位），但其设计正确性无法用静态核对判定。
4. **T-17 模板仅抽查**：核对了标题、总行数（2119）、5 个页签、`.alert-warn` 出现处；`ix-review` 引用的 `:280`（额度呈现）、`:1035`（轮询反馈）、`:1775-1894`（四态）**未逐行打开**。
5. **未运行测试、未启动服务、未调用任何上游**：所有结论均为静态核对（读文件 + 读源码）。
6. **判定口径说明**：`⚠️ 部分` 指「主要诉求已满足但存在明确缺口/口径未统一」；`🔴 改错` 仅用于「修正本身与明确依据（PRD/代码）直接冲突」。本次唯一达到 `🔴` 强度的是 **§3.1（§12.4.1 目录解析违反 PRD Q25-⑨）**，其余归入 `⚠️`。
