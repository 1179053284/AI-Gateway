# 工程视角审核报告 · tech-design §12–§20（增量设计 v2.0）

> 审核人：资深后端研发（Python / FastAPI / 异步）
> 审核日期：2026-09-26
> 审核对象：`docs/specs/tech-design.md` §12–§20（行 666–1114）
> 审核基准：**现有代码实际行为**（最重要）> 调研文档 `docs/research/08·10·14–19` > 设计文档自述
> 判据：用户要求「不要过度设计，用最简单精准高效的方式实现最好的需求」
> 只读约束：本次审核未修改任何源码/文档（本报告除外）

---

## 1. 审核结论

**有条件通过。**

§12–§20 的**方向**是对的，且有大量克制（§15.2 删抽象层、§14.2 只加一列、§12.3 砍 UI 留字段、§20 不做清单 19 条）——这些是本设计最值得肯定的部分。

但存在 **3 处"照此实施会立刻出错/无法交付"的硬问题**，以及 6 处"实施时必须补定义否则会走偏"的中等问题。硬问题的共同特征是：**设计文档引用了不存在的代码符号、不存在的 CLI 入口、以及不可达的交付判据**——产品经理审核（`PM-review.md`）无法发现这类问题，因为它们只能靠读代码验证。

**放行条件**：修完 §3 的 P0-1/P0-2/P0-3 三条（改动都很小：改 4 行伪代码 + 调 1 处阶段顺序 + 改 1 条判据措辞），即可进入 M3。

---

## 2. 与现有代码的一致性核对表

### 2.1 §12.3 代码示意引用的字段（逐字段核对 `enums/matcher.py`）

| 设计引用 | 代码实际 | 结论 |
|---|---|---|
| `entry.display` | `matcher.py:20 display: str = ""` | ✅ |
| `entry.context_window` | `matcher.py:28 context_window: int \| None = None` | ✅ |
| `entry.max_output` | `matcher.py:29 max_output: int \| None = None` | ✅ |
| `entry.image_input` | `matcher.py:30 image_input: bool = False` | ✅ |
| `entry.reasoning` | `matcher.py:33 reasoning: bool = False` | ✅ |
| `entry.vendor` | `matcher.py:27 vendor: str = ""` | ✅ |
| `entry.tool_call` | **不存在** | ⚠️ §12.3 已声明要新增 → 与设计自述一致，**不是问题** |
| `entry.effort_levels` | **存在，但类型是 `list[str]`**（`matcher.py:34`），不是 dict/map | ❌ 设计 §12.3 把它当映射用（见 P0-1） |
| `entry.thinking_format` | **不存在**；`EnumEntry` 全文无此字段（检索 `matcher.py` 关键词 `thinking_format` / `thinkingFormat`：0 命中） | ❌ 设计未声明新增，却直接引用（见 P0-1） |
| `match_enum(...)` | 无此符号；真实 API 是 `EnumPool.match(name)`（`matcher.py:173`）/ `EnumPool.get(name)`（`matcher.py:217`） | ⚠️ 属示意伪代码，不算问题，但 `get()` 对自定义模型返回 `None` → 见 P0-1 |

### 2.2 其余设计声称 vs 代码实际

| # | 设计声称（行号） | 代码实际 | 结论 |
|---|---|---|---|
| 1 | §12.1「`/v1/models` 只返回 6 字段」（`tech-design.md:670`） | `openai_compat.py:39-43` 恰好 6 字段 | ✅ 准确 |
| 2 | §12.3「`/v1/models` 在现有 6 字段基础上追加，不删不改 → 向后兼容」（`:724`） | `openai_compat.py:39-44` 用 dict 字面量拼装，追加键无破坏 | ✅ |
| 3 | §14.2「`Resource` 加一列 `product: str = ""`，向后兼容」（`:874`） | `schemas.py:109-129` 为 pydantic 模型；`admin.py:367` GET 用 `model_dump()` 全量序列化、`admin.py:410` PUT 用 `model_dump(exclude={"warnings"})` 全量落盘 → 新字段自动随读写往返，旧 YAML 缺该字段走默认值 | ✅ 向后兼容成立 |
| 4 | §12.3「`SystemModel` 加 `caps_overrides`」与既有 `params` 是否重叠 | `schemas.py:166 params` 是**采样参数**，经 `ir.py:58-70 apply_model_params` 注入出站请求体；`caps_overrides` 是**能力声明**，只用于 `/v1/models` 输出 | ✅ 职责正交，**无冲突**（建议在文档一句话写明边界，防实现者混用） |
| 5 | §13.4「方言表落 `data/dialects.json`」与现有热重载的关系 | `main.py:237-255 _reload_watcher` **只监听 `runtime.config_path`**；`main.py:81 _apply` 只重建 `enum_pool`（`load_enum_pool(enums_path)`） | ❌ 未定义：方言表变更后内存快照如何刷新（见 P1-4） |
| 6 | §16.1「`ops/` 与核心调度解耦，不进 `core/scheduler.py`」 | 现有调度状态机（`scheduler.py:287-458`）承载重试/冷却/C 计数，语义是"模型转发"；ops 语义是"账号运营" | ✅ 解耦正确；但**重试退避工具函数会各写一份**（见 P2-5） |
| 7 | §17「并发租约：复用现有 `pick_and_acquire`」（`:1031`） | `resources.py:120-144 pick_and_acquire` 存在，且 `scheduler.py:324` 在模型转发路径已调用 | ⚠️ 对**模型转发**成立；但 `research/19:149` 明写 upstream/ops **不复用**其"调度/限流/租约逻辑" → 两文档表述冲突（见 P1-5） |
| 8 | §17 树：`upstream/zcode/{crypto,oauth,account,dataroot,quota,claim,auth}.py` | 全仓无 `upstream/`、`ops/` 包（`find model_gateway -name '*.py'` 确认） | ✅ 新增，符合 §7 的"一个职责一个包"风格；但 §7 目录结构（`:495-542`）**未同步更新**（见 P2-7） |
| 9 | §18.1「`anthropic_out.py` / `gemini_out.py` 仅 docstring；`base.py` 纯注释；全仓无处 import（只用了 `OpenAIOutAdapter`，`main.py:28` / `admin.py:34`）」（`:1039-1048`） | `anthropic_out.py:1` / `gemini_out.py:1` 各 1 行；`base.py:1-5` 纯 docstring；`main.py:28`、`admin.py:34` 确为仅有的两处 import | ✅ **完全准确**（这是本次审核里最诚实的一节） |
| 10 | §18「`anthropic_out` 要接现有 `adapters` 接口」 | 现有接口**不是** §4.4（`:163`）宣称的 `call(resource, ir_request)`；真实约定是 **duck typing 的 4 个方法**：`chat_nonstream(key, vendor_model, body, timeout)` / `chat_stream(...)` / `images_generate(...)`（`scheduler.py:465-468, 479-482, 554-555`）+ `aclose()`（`main.py:120`），见 `openai_out.py:100/122/164/57` | ❌ §18 未说明新适配器要实现哪些方法、在哪里被分发（见 P0-4/P1-1） |
| 11 | §18.2「2xx 但 Content-Type 非 JSON/SSE 按上游错误处理并冷却」（`:1059`） | `errors.py:98-127 classify()`：`status=200` 且无 `type` → 落到 `errors.py:127 return BAD_REQUEST` → 走"原样透传、不冷却" | ❌ 现有分类器**表达不了**该语义（见 P1-2） |
| 12 | §18.2「OpenAI 入站路径内部强制 `stream:true` 再聚合」（`:1058`） | `openai_compat.py:121 stream = bool(body.get("stream", False))` 原样透传；非流式走 `scheduler.execute_chat`（`:136`），**全仓无 chunk 聚合器** | ❌ 与既有架构不一致且非必需（见 §4 过度设计专项 O-1） |
| 13 | §19 M3-5/M3-3 用 `mgw setup` / `mgw probe`（`:1075,1077`）；§12.4.1「复用已有 CLI 形态」（`:788`）；§19 M5-0「复用已有 `mgw` CLI 形态」（`:1082`） | `pyproject.toml:1-31` **无 `[project.scripts]`**；`research/04:134` 明确「目前项目**没有任何命令入口**」；`research/04:283`、`research/05:55` 把"新增 `mgw` 命令入口"列为待办 | ❌ 「已有 CLI」不存在 + M3 依赖 M5 的 CLI（见 P0-2） |
| 14 | §19 M4-2 判据「两账号各自启动，主 `~/.zcode` 不被写」（`:1079`） | `research/17:82`：`setting.json` **固定写主 `~/.zcode/v2/setting.json`**（`zcodeSettingFile()` 硬编码）；`research/17:224` 列为"⚠️ 需实测确认"的隔离例外 | ❌ 判据客观不可达（见 P0-3） |
| 15 | §16.3 教训2「重复签到返回 HTTP 400 + code **10001**」（`:950`） | `research/10:224` 的 10001 属 **DSH/buddy 产品**；ZCode 的幂等码是 **1003**（已领过）/ **1005**（今日名额用完），见 `research/14:61-73`；`research/19:301` 亦引 1003/1005 | ❌ 码值张冠李戴（见 P1-3） |
| 16 | §16.6「首批 2 个 operation：`daily_checkin` / `query_balance`」（`:997`） | `research/14:18`：「ZCode **没有传统意义的「每日签到」端点**」；实际是 `billing/claim`（period=daily）+ `event/report`（app_daily_active）；`research/19` D27 落点为 `ops/builtin/zcode_claim.py` | ⚠️ 命名与真实机制不符，易误导实现（见 P1-3 附带） |
| 17 | §13.3 S2「发极值 vs 基线比 `reasoning_tokens`」（`:823`） | `research/08:723`：同模型同题基线波动 **22/23/38/43/61**；`research/08:721`：只有 `none`→**0** 是明确锚点 | ⚠️ 判据未限定锚点/采样次数（见 P1-6） |
| 18 | §15.3 整根隔离四件套环境变量（`:915`） | `research/17:51-56` 列出同名变量；但 `research/17:234` 明确「三个 `ZCODE_DESKTOP_*` 能否覆盖 `app.setPath` **本机未实测**」；`research/19` §八 T1–T9 **不含该待实测项** | ⚠️ 未内联 caveat、待实测清单有缺口（见 P2-3） |
| 19 | §16.5 Playwright 求解验证码（`:974`） | `research/15:241` 用 Playwright 无头 Chrome；`research/16:118` 显示参考实现用 `asyncio.Lock`（`captcha.py:116,159`）→ 异步 API | ⚠️ 进程模型/超时/浏览器生命周期未定义（见 P1-7） |
| 20 | §17 TLS 指纹 `curl_cffi`（`:1030`） | curl_cffi 官方文档确认 `AsyncSession` 存在（feature matrix `async ✅`），但 **async 流式接口无文档**（`curl-cffi.readthedocs.io/en/latest/asyncio.html` 正文仅 "TODO"），README 未出现 `stream` / `aiter_content`；`research/19:368` 已有降级备选但未进设计 | ⚠️ 未验证项 + 与 httpx 出站适配器如何统一未定义（见 P1-8） |

---

## 3. 问题清单

### 🔴 严重（P0：照此实施会立刻出错或无法交付）

#### P0-1 §12.3 的代码示意引用了不存在的字段 + 类型用错 → 实施即崩

**问题**
1. `tech-design.md:735` 用 `entry.thinking_format` —— `EnumEntry` **没有这个字段**（`matcher.py:17-35` 全文无 `thinking_format`/`thinkingFormat`）；§12.3 的"净新增"只声明了 `tool_call`（`:722`），`thinking_format` 无人声明。且 §14.1 把 `thinkingFormat` 归入 **L-C 方言层**（`:856`），与 §12.3 把它当 `EnumEntry` 字段自相矛盾。
2. `tech-design.md:733-734` 把 `entry.effort_levels`（实际是 `list[str]`，`matcher.py:34`）当 dict 解包：`levels = entry.effort_levels or {}` 然后 `{**{lv: None for lv in LEVELS}, **levels, ...}` —— 对 list 做 `**` 解包会抛 `TypeError`/`ValueError`。**这段伪代码按字面实现跑不起来**。
3. `tech-design.md:728` 的 `match_enum(m.name)` 在自定义系统模型（Q19-② 允许"就地新建系统模型"，不在内置目录）上会返回 `None`，随后 `entry.display`（`:740`）直接 `AttributeError`。设计未给 `entry is None` 的兜底。

**证据**：`matcher.py:17-35`（字段全集）、`matcher.py:34`（`effort_levels: list[str]`）、`matcher.py:138-141`（`claude-sonnet-4`/`claude-opus-4` 连 `context_window` 都是 `None`）、`matcher.py:173/217`（`match`/`get`，无 `match_enum`）、`tech-design.md:722,733-735,740,856`。

**建议改法（最小）**
- `effort_levels` 是"支持档位列表"，应**正向生成映射**，而非解包：
  ```python
  sup = set(entry.effort_levels or [])
  levels = {lv: (lv if lv in sup else None) for lv in LEVELS}   # 7 键齐全，不支持显式 None
  levels.update(ov.get("thinkingLevelMap") or {})
  ```
- `thinkingFormat` **从 §13 方言表取**（L-C 层），不要在 `EnumEntry` 上取；或明确在 `EnumEntry` 新增 `thinking_format: str = ""` 并在 §12.3 的"净新增"清单里列出（二选一，不能悬空）。
- 加 `entry = pool.get(m.name)`，`entry is None` 时**降级为最小字段集**（`name=m.name`、`vendor=""`、能力位不声明或全 false），不要崩。

---

#### P0-2 `mgw` CLI 不存在，且 M3 依赖 M5 才创建的 CLI（依赖倒置 + 事实错误）

**问题**
- `tech-design.md:788` 与 `:1082` 两处写「**复用已有** CLI 形态 / **已有** `mgw` CLI 形态」——**项目当前没有任何命令入口**：`pyproject.toml:1-31` 无 `[project.scripts]`，`research/04:134` 原文「`pyproject.toml` **没有 `[project.scripts]`** 段 → 目前项目**没有任何命令入口**，只能 `python -m model_gateway.main`」，`research/04:283`/`research/05:55` 均把"新增 `mgw` 入口"列为待做。
- 更严重的是**顺序**：M3-3（`mgw probe`，`:1077`）与 M3-5（`mgw setup`，`:1078`）都依赖 CLI，而创建 CLI 的 **M5-0 排在 M4 之后**（`:1082`）。这是第三处依赖倒置（PM 已修两处）。

**证据**：`pyproject.toml:1-31`、`research/04:134,283`、`research/05:55`、`research/07:81`（负向基线已确认无 `[project.scripts]`）、`tech-design.md:788,1077,1078,1082`。

**建议改法（最小）**
- 把 M5-0 拆出**最小 CLI 骨架**（`pyproject.toml` 加 `[project.scripts] mgw = "model_gateway.cli:main"` + `model_gateway/cli.py` 的子命令分发）**提升为 M3-0**，M3-3/M3-5 在其后。
- 把两处「复用已有 CLI 形态」改为「**新建** `mgw` 入口（`research/04:283`）」。

---

#### P0-3 M4-2 交付判据「主 `~/.zcode` 不被写」客观不可达

**问题**：`research/17:82` 明确 `setting.json` **由 ZCode 客户端固定写主 `~/.zcode/v2/setting.json`**（`zcodeSettingFile()` 硬编码 `LEGACY_ZCODE_V2`），且 `research/17:224` 把它列为隔离的**已知例外**。整根隔离能保证的是"凭据/配置/日志/遥测/provider_config 进账号目录"，**不能**保证"主目录零写入"。按现判据验收，M4-2 必然"不通过"，而实现其实是对的。

**证据**：`research/17:82`、`research/17:224`、`research/17:234`、`tech-design.md:1079`。

**建议改法（最小）**：判据改为可验证的**具体事实**——
> 「两账号启动后：① 各自 `data/.zcode/v2/credentials.json` 与 `telemetry-state.json` 互不覆盖；② 主 `~/.zcode/v2/` 下 **credentials/config/telemetry 三件未被写入**（`setting.json` 为已知例外，不计入）；③ 设备 ID 唯一性校验对冲突输入返回拒绝而非静默重生成。」

---

### 🟠 中等（P1：实施时必须补定义，否则会走偏）

#### P1-1 §18 未定义适配器分发点，而现有分发点硬编码了 OpenAI 适配器

**问题**：§18 只说"要接现有 adapters 接口"，但真实接入需要改两处**当前硬编码**的位置：`main.py:95-105` 无条件构造 `OpenAIOutAdapter(...)`（`r.protocol` 字段**完全未被使用**），`admin.py:291` 健康测试也直接 `OpenAIOutAdapter(base_url)`。§18 与 §19 M4-1 都没提这两处改动，也没说 `anthropic_out` 要实现的 4 个方法签名与 usage 字段契约（`scheduler.py:274-277` 只认 `prompt_tokens`/`completion_tokens`，Anthropic 是 `input_tokens`/`output_tokens`，**必须在适配器内映射**，否则 usage 恒走本地估算）。

**证据**：`main.py:64,95-105`、`admin.py:285,291`、`scheduler.py:211-215,465-468,479-482,554-555`、`scheduler.py:274-277`、`openai_out.py:100,122,164,57`、`tech-design.md:1054-1061`。

**建议改法（最小）**：§18.2 补三行——
1. 适配器契约 = duck typing 的 `chat_nonstream` / `chat_stream` / `images_generate` / `aclose`（与 `openai_out.py` 同形），**不是** §4.4 的 `call(resource, ir_request)`（顺带修 §4.4:163 的口径，或标注 §4.4 为"目标形态，未落地"）。
2. 分发点：`main.py:103` 改为按 `r.protocol` 分支（`openai`→`OpenAIOutAdapter`，`anthropic`→`AnthropicOutAdapter`）；`admin.py:291` 同步。
3. usage 契约：适配器须输出 `usage.prompt_tokens`/`completion_tokens`。

#### P1-2 §18.2「2xx 非 JSON/SSE 按上游错误处理并冷却」现有分类器表达不了

**问题**：`errors.py:98-127` 的 `classify()` 对 `status=200`（无 `type`）会一路落到 `:127 return BAD_REQUEST` → 调度器按"参数类"**原样透传、不重试不冷却**（`scheduler.py:364-370`）。要实现"当上游错误 + 冷却"，必须让它落到 `RETRYABLE`（才能经 C≥y 触发 `bench`）。现有 `UpstreamError`（`errors.py:38-60`）只有 `status_code/error_body/error_type/no_failover` 四个字段，**没有"响应体非法"这一类**。

**证据**：`errors.py:17-23,98-127,38-60`、`scheduler.py:364-370,395-412`、`research/15:196`、`tech-design.md:1059`。

**建议改法（最小，二选一）**
- **A（推荐，零新类别）**：适配器检测到 2xx 非 JSON/SSE 时抛 `UpstreamError("upstream 2xx non-json", status_code=None)` → `classify` 在 `errors.py:100-101` 判 `status_code is None` → `RETRYABLE`，自然进入 C 计数与冷却。**需在 §18.2 显式写明这个约定**（否则实现者会填 200 或 502，语义就散了）。
- **B**：`ErrorClass` 新增 `INVALID_RESPONSE`，`classify` 加一条分支，`scheduler` 两处（`:395`、`:662`）与 `_exit_status_code`（`:234-244`）同步。改动面更大，除非将来还有别的用途，否则不必。

#### P1-3 §16.3 的幂等码 10001 属别的产品；ZCode 是 1003/1005

**问题**：§16.3 教训2 把「HTTP 400 + code **10001**（"今天已签到"）」当作运营模块的通用幂等判据，而 §16.4 又要求「业务码不重试」——**幂等码就是 already_done 判定的唯一依据**（§16.3 自己写的）。10001 出自 `research/10:224`（DSH / buddy 产品）；ZCode 的领取幂等码是 **1003**（该套餐已经领取过）/ **1005**（今日领取名额已用完，回带 `next_at`），见 `research/14:61-73`，`research/19:301` 亦引 1003/1005。照 §16.3 实现 ZCode 的 `already_done` 判定会判错。
**附带**：§16.6 的 operation 名 `daily_checkin`（`:997`）暗示存在"签到端点"，而 `research/14:18` 明确 ZCode **没有**每日签到端点（是 `claim` + `event/report` 合成），`research/19` D27 落点名为 `zcode_claim.py`。

**证据**：`research/10:224,227`、`research/14:18,20-21,61-73`、`research/19:301`、`tech-design.md:950,960,997`。

**建议改法（最小）**：§16.3 教训2 的码值标注为**按产品分表**——`ZCode: 1003 / 1005`，`buddy(DSH): 10001`；§16.6 的 operation 名 `daily_checkin` → `zcode_claim`（与 `19` D27 对齐），或加注"= claim + activate 合成，无独立签到端点"。

#### P1-4 `data/dialects.json` 与配置快照/热重载的关系未定义

**问题**：§13.4 把探测结果落 `data/dialects.json`，§12.3 的 `caps` 组装又要读它；但现有热重载只监听 `config.yaml`（`main.py:244`），`_apply` 只重建 `enum_pool`（`main.py:81`）。于是：探测完成后（同一进程内）`/v1/models` 的 `thinkingLevelMap` 会不会立刻变？改 `dialects.json` 会不会热生效？设计全篇未答。

**证据**：`main.py:81,237-255`、`tech-design.md:840,733-735`。

**建议改法（最小）**：§13.4 加一句——"方言表在**启动时加载一次**进内存快照；`mgw probe` 写完文件后**显式触发一次重载**（复用 `runtime.reload_from_file()` 或新增 `runtime.reload_dialects()`），**不新增 mtime 轮询**"。（不要为它加第二个 watcher。）

#### P1-5 §17 的"复用 `pick_and_acquire`"与 `research/19:149` 直接冲突，且熔断/额度状态未接入路由

**问题**
- 表述冲突：`tech-design.md:1031` 写"并发租约 → **复用** `pick_and_acquire`"；`research/19:149` 写"复用 `core/resources.py` 的凭据与设备绑定，但**不复用**其调度/限流/**租约**逻辑"。两者必有一处要限定范围。
- 实质缺口：`pick_and_acquire` 的可用性判据是 `resources.py:63-64 available()`，**只看 `status`/`enabled`**；而 §17 的 3012 熔断状态与额度耗尽状态都住在 `upstream/zcode/quota.py`（`:1028`）。**没有任何桥接** → 一个刚被 3012 全局熔断 30 分钟的账号，仍会被模型转发路径选中（要等它再失败一次才进 `cooldown`）。§19 M5-3 只提"额度预扣（事后快照→事前预留）"（`:1085`），**未提熔断回写**。

**证据**：`resources.py:63-64,120-144`、`scheduler.py:324`、`research/19:149,372-378`、`research/18:53-56`、`tech-design.md:1028,1031,1085`。

**建议改法（最小）**：§17 把该行改为「**模型转发路径**复用 `pick_and_acquire`；**额度查询/领取路径**不复用租约，用自建互斥（§16.4 双层互斥 + §17 节流 10s/熔断 30min）」；并在 §19 M4-4 的判据里加一条「3012 熔断/额度耗尽时，**回写该账号对应 `ResourceState.status`**（复用 `bench`/`disable`），使模型转发路径自动绕开」——这样不必给 `available()` 加额度维度，改动最小。

#### P1-6 §13.3 的 S2 判据未限定锚点与采样次数（统计上不可靠）

**问题**：§13.3 写「S2：发**极值 vs 基线**，比 `reasoning_tokens` → 真写入位」。但 `research/08:723` 实测同模型同题基线波动 **22/23/38/43/61**，并明确「生效判定**不能看绝对值**，只能看**极端开关差异**（如 `none`→0）或**多次取平均**」。§13.3 只保留了 `research/08:730-731` 的结论，**丢掉了采样纪律**：若按字面拿 `high`(23) 与基线(43) 比，n=1 会误判。

**证据**：`research/08:706-724`（原始六组数据）、`research/08:730-734`（S1/S2/S3 定义与"归零"锚点）、`tech-design.md:823,834`。

**建议改法（最小）**：§13.3 的 S2 一格改为「**只发 `none`/`off` 类关闭值**，与基线比：`reasoning_tokens` 归零 → 确认该写入位生效；非归零 → 判为假方言丢弃（**单次采样即可，因 0 与 22–61 无重叠**）。**不做逐档数值比较**」。

#### P1-7 §16.5 验证码求解：进程模型/超时/浏览器生命周期未定义

**问题**：§16.5 只写"Playwright（与 `zcode2api` 同栈）+ TTL 45s + 住宅代理 + 失败不影响模型转发"。未定义：① 同进程还是子进程；② 超时；③ 浏览器实例生命周期与清理；④ "不影响模型转发"的**具体隔离手段**。Playwright 浏览器是重资源且会挂；若不设超时，一个卡死的求解会让 ops tick 长期占用（虽 async API 不阻塞事件循环，但会悬挂任务与浏览器进程）。

**证据**：`research/15:241`（Playwright 无头 Chrome + 45s 缓存）、`research/16:118`（`captcha.py:116,159` 用 `asyncio.Lock` → 参考实现走**异步 API 同进程串行**）、`research/19:313-317`、`tech-design.md:974-977`。

**建议改法（最小）**：§16.5 补一行——「用 `playwright.async_api`（`AsyncSession`/`Browser`）**同进程**，`asyncio.Lock` 串行（照 `research/16:118`）；每次求解带 `asyncio.wait_for(..., timeout=30s)`；`ops/runner` 调用点用 `try/except (TimeoutError, PlaywrightError)` 包住 → 记 `failed`，**不 re-raise**。浏览器实例进程级复用 + 退出时 `aclose`。」

#### P1-8 §17 `curl_cffi` 的两点未闭合：async 流式能力 + 与 httpx 出站适配器如何统一

**问题**
- `curl_cffi` 官方文档确认 `AsyncSession` 存在（feature matrix `async ✅`），但 **async 流式接口无文档**（`asyncio.html` 正文只有 "TODO"），README 通篇无 `stream` / `aiter_content` / SSE 字样。而 ZCode 的**主流量是模型转发的 SSE 流式**——指纹客户端若不能流式，Plan 通道的流式转发直接不成立。
- §17 把 TLS 指纹放在 `upstream/zcode/auth.py`（`:1016`），把模型转发放在 `adapters/anthropic_out.py`（`:1007`）——**两个模块用两个 HTTP 客户端（httpx vs curl_cffi），如何统一未定义**：是 `anthropic_out` 改用 curl_cffi？还是 auth.py 提供 client 注入？设计没说。
- §19 的 T5 只测"能否通过 WAF"（`research/19:408`），**不含流式能力**；`research/19:368` 已有降级备选（httpx + 自定义 ClientHello / 只走 API Key 通道），但**未进 tech-design**。

**证据**：`curl-cffi.readthedocs.io/en/latest/`（feature matrix）、`curl-cffi.readthedocs.io/en/latest/asyncio.html`（正文 "TODO"）、`research/15:363-368`、`research/19:366-368,408`、`tech-design.md:1030,1007,1016`。

**建议改法（最小）**：§17 补一句——「TLS 指纹客户端**由 `auth.py` 统一提供**并注入给 `anthropic_out`（适配器不直接持 httpx client）」；T5 扩为「**T5a：WAF 放行 + T5b：async SSE 流式可用**」；并写明降级链：`curl_cffi 流式不可用 → 该账号只走 API Key 通道（api.z.ai 不需指纹）`。

---

### 🟡 轻微（P2：建议改，不改也能跑）

#### P2-1 §12.4 路径 A 写入缺原子写，与既有纪律不一致

**问题**：§12.4.1 的"写入纪律"是「备份 → 合并 → 读回校验」（`:783-786`），**没有原子写**。而项目既有纪律明确是 tempfile + `os.replace`（`admin.py:404-412`；`tech-design.md:189,552`）。且 `research/08:654`（U7）记录过 `~/.workbuddy/models.json` **被清空且改动方未定位**（CLI 侧有 `reconcileUserModelsJsonToPolicy`），说明该文件存在**外部并发写**。§12.4.1 未定义并发写与"写到一半崩"的回滚。

**证据**：`admin.py:404-412`、`tech-design.md:189,552,783-786`、`research/08:213-215,654`。

**建议改法（最小）**：写入纪律加第 4 条「同目录 tempfile + `os.replace` 原子写（与 `admin.py:404-412` 同口径）；写前备份保留为 `models.json.bak-<ts>`，写失败回滚用备份」。不改设计结构，只是补一条既有纪律。

#### P2-2 §12.2a（7 键封闭）与 §13.1（规范外档位透传）对 `ultra` 的归属未裁决

**问题**：§12.2a 要求 `thinkingLevelMap` **7 键齐全、不得省略**（`:716-718`）；§13.1 要求"规范外档位（`ultra`）**原样透传、不报错**"（`:807`）。二者**不是直接冲突**（前者管**键集合**，后者管**值域/入站值**），但设计**没说 `ultra` 在 `thinkingLevelMap` 里放哪**——工具侧 `getSupportedThinkingLevels` 只遍历那 7 个键（`research/08:341-348`），`ultra` 无处安放，于是 `deepseek-v4-pro` 的 `ultra` 能力**在声明式路径上不可达**。

**证据**：`research/08:341-348,694`、`research/08:696-698`、`tech-design.md:716-718,807`。

**建议改法（最小）**：§13.1 加一句裁决——「`thinkingLevelMap` 的**键固定为 7 个规范档**；`ultra` 等规范外档位**不新增键**，仅：① 作为 `max` 的**映射值**（若厂商 `max` 的真实值即 `ultra`）；② 在**入站透传**（非工具客户端直接发 `ultra`）时原样放行。规范外档位不进入声明式档位表。」

#### P2-3 §15.3 未内联"三件套环境变量未实测"的 caveat，且待实测清单有缺口

**问题**：§15.3 直接断言 `ZCODE_DESKTOP_{USER_DATA,SESSION_DATA,HOME}_DIR` + `--device-id` 为实现落点（`:915`），但 `research/17:234` 明确这三个变量"能否真正覆盖 `app.setPath`，仅凭面板注释判断，**本机未实测**"；`research/19` §八 T1–T9 **不含**该项。另 `research/17:83` 记录 ZCode 内置浏览器 session **跨账号共用**是"已知破绽、首期接受"——§15 未提。

**证据**：`research/17:83,224,234`、`research/19:400-412`（T1–T9 清单）、`tech-design.md:915`。

**建议改法（最小）**：§15.3 加「⚠️ 待实测：三个 `ZCODE_DESKTOP_*` 是否真的覆盖客户端 `app.setPath`（`research/17:234`）；内置浏览器 session 跨账号共用为**已知例外**」；并把该项补进 §19 的 T 清单。

#### P2-4 §12.3 对无目录属性的模型会下发 `null`

**问题**：`claude-sonnet-4` / `claude-opus-4`（`matcher.py:138-141`）**没有** `context_window` / `max_output`，按 §12.3 直映射会输出 `"maxInputTokens": null, "maxOutputTokens": null`。工具侧会退回自己的兜底值（`research/08:683`），行为可接受，但设计未说明这是有意为之。

**证据**：`matcher.py:138-141`、`research/08:683,609-617`、`tech-design.md:691-692`。

**建议改法（最小）**：§12.3 加一句「目录缺该属性时输出 `null`（工具回退自身兜底值，与现状等价），不臆造数值」。

#### P2-5 ops 与 scheduler 会各写一份退避工具

**问题**：边界总体清晰（ops **不**复用 C/冷却/选路，正确）。但"网络类/5xx 退避重试"（§16.4 `:960`）与 scheduler 的 `_sleep_interruptible`（`scheduler.py:261-270`）是同一类逻辑，会各写一份；`research/14:156` 又给了具体退避序列 `[500,1500,4000]ms`。两份退避语义容易漂移。
**另需一句话加固**：§16.6 应显式写「`ops/` **不 import** `core/scheduler` 与 `core/errors.ErrorClassifier`」——否则实现者可能顺手用 `ErrorClassifier`，而 `errors.py:127` 会把 ZCode 的 HTTP 400+1003（already_done）判成 `BAD_REQUEST`，与 §16.3 教训2 直接冲突。

**证据**：`scheduler.py:261-270`、`research/14:156`、`errors.py:127`、`tech-design.md:960,992`。

**建议改法（最小）**：把 `_sleep_interruptible` 提为 `core/` 下的公共小工具（或 ops 内自建一个 6 行函数，**不共用调度状态**）；§16.6 补一句"ops 不复用 `core/scheduler`、`core/errors`"。

#### P2-6 额度刷新的触发时机未定义（"两套定时器"风险）

**问题**：§17 说额度"客户端日志优先 → 联网兜底"（`:1027`），§19 M5-2 交付"管理端可见聚合数字"（`:1084`），但**全篇未定义额度刷新的触发频率/位置**。参考实现有**两个**独立循环（额度刷新 `pool.refreshLoop` 默认 60s + 活动 cron 1min，`research/16:236-237`），§16 又给 `ops/runner` 一个 cron → 存在"两套定时器"的风险，而设计没裁决是共用 ticker 还是各跑各的。

**证据**：`research/16:236-243`、`research/18:33-37`（日志通道）、`tech-design.md:1027,1084`。

**建议改法（最小）**：§17 加一句——「额度刷新**不新建独立定时器**：① 每个 `ops/runner` tick 末尾顺带刷新一次（**串行 + 10s 节流 + 3012 熔断**）；② 每次模型转发成功后按 30s 节流补刷（对齐 `research/16:243`）；③ 管理端点支持手动触发。」

#### P2-7 §7 目录结构未同步更新

**问题**：§7（`tech-design.md:495-542`）是"代码目录结构"的**唯一真相源**，但 §17 新增的 `upstream/`、`ops/` 两个顶层包未回写 §7；§17 的树（`:1006-1020`）又漏了 `upstream/__init__.py`（`research/19:129` 有）。

**证据**：`tech-design.md:495-542,1006-1020`、`research/19:129-144`。

**建议改法（最小）**：§7 补 `upstream/`、`ops/` 两行；§17 树补 `__init__.py`。

---

## 4. 过度设计专项

### 4.1 建议砍掉 / 简化

| # | 位置 | 为什么是过度设计 | 最小改法 |
|---|---|---|---|
| **O-1** | §18.2「OpenAI 入站路径内部强制 `stream:true` 再聚合」（`:1058`） | 这是参考实现（`zcode-proxy`/`zcode2api`，`research/15:20-21`）**内部流式优先架构的产物**，不是上游约束。Anthropic Messages 原生支持 `stream:false`（`research/15:21` 亦确认 Anthropic 路径不强制）。而**本网关**非流式路径已完备（`openai_compat.py:136 → scheduler.execute_chat`），全仓**无 chunk 聚合器** → 照做要新增一个聚合器 + 改入站分支，**收益为零** | 删掉该条。`anthropic_out` 与 `openai_out` 同形，直接实现 `chat_nonstream` + `chat_stream` 两个方法即可（`openai_out.py:100,122`） |
| **O-2** | §13.3 S2「发**极值 vs 基线**比 `reasoning_tokens`」（`:823`） | "逐档比数值"在 22–61 的噪声下统计不可靠（`research/08:723`），会引入**多次采样 + 阈值调参**的复杂度 | 收敛为**单一锚点**：只验 `none`/`off` → 归零（单次采样）。见 P1-6 |
| **O-3** | §12.3 `SystemModel.caps_overrides`（`:723`） | 字段本身极便宜（1 行），但 M3 阶段**无任何使用者**（§12.3 的 caps 全部来自目录 + 方言表；§14.1 明确它"仅在目录不准/探测失败时使用"） | **可保留**（成本≈1 行，且是探测失败的逃生口）；若严格 YAGNI，可延到 M3-4 实测出现"目录不准"时再加。**不建议为它加 UI/校验**（§14.1 已砍 UI，正确） |

### 4.2 克制得当、明确不该再砍的（记录以免后续被"优化"掉）

- §14.2 只加 `Resource.product` 一列、不建四表（`:874`）——`research/08:806-813` 的两阶段评估支持这个判断，✅。
- §15.2 删掉 `DeviceIdentity(Protocol)` 与 `upstream/base.py` 抽象（`:896-909`）——只有 1 个实现，✅ 完全正确。
- §16.6 只做 2 个 operation、不做"通用运营 DSL"（`:996-997`）——✅。
- §20 全表 19 条不做清单——✅ 这是本文档最有价值的一节。
- §17「不做免重启热切换」（`:1033`）——依据（源码缺失 `lib.rs:11-12`）已在 `research/19:69-82` 闭合，✅。

---

## 5. 明确无问题的部分

以下经核对**确实没有问题**，不再重复列出：

1. **§12.1 现状描述**：`/v1/models` 6 字段、零能力位的判断与 `openai_compat.py:39-43` 完全一致。
2. **§12.2 字段映射**：`maxInputTokens↔context_window`、`maxOutputTokens↔max_output`、`supportsImages↔image_input`、`supportsReasoning↔reasoning`、`name↔display`、`vendor↔vendor` 六条直映射与 `matcher.py:20,27-33` 逐条对得上；唯一真缺的就是 `supportsToolCall`（`matcher.py` 无 `tool_call`）——设计也承认了。
3. **§12.3 向后兼容**：追加字段不删不改（`openai_compat.py:39-44`），`Resource.product` 经 `model_dump` 全量往返（`admin.py:367,410`），**旧配置零改动**。
4. **§12.3 `caps_overrides` 与 `params` 不冲突**：职责正交（`schemas.py:166` + `ir.py:58-70` vs 能力声明）。
5. **§12.4 两条下发路径的判断**：路径 A 对 WorkBuddy CLI 必需（只读文件）、路径 B 对其他工具——`research/08:621-627` 支持；"不做自动探测并静默改写他人配置"的克制正确。
6. **§14.1 配置三层**：L-A 不新增、L-C 探测得出、唯一净新增 `caps_overrides`——与 `schemas.py` 现有分层不冲突。
7. **§15.1 三条硬约束**：与 `research/17:137-138`（参考项目只校验 UUID 格式、不查重）形成明确互补，我们的"跨账号唯一性校验"是**真缺口补齐**，不是重复造轮子。
8. **§15.3 措辞限定**：把"不做画像随机化"限定为"ZCode 首期"（`:922-924`），消除了与 PRD Q26-① 的全局冲突——这是很干净的一处修正。
9. **§16.2 四类结果**：`success`/`already_done`/`inactive`/`failed` 与 `research/14:104`（空跑算成功）、`research/10:246` 一致。
10. **§16.4 双层互斥**：`plan 级 TryLock + 账号级 claimLockFor` 与 `research/14:95`（`scheduler.go:168-173`、`activity.go:405-423`）逐字对应，补入正确。
11. **§17 额度读取优先级（日志优先）**：与 `research/18:21-22,36`（日志是客户端第一手响应、联网缺 `balances`）一致，理由充分。
12. **§17 3012 熔断 30min / 节流 10s / 状态落盘**：与 `research/18:53-56` 逐项一致（含"状态必须写可写位置"的坑）。
13. **§18.1 空壳现状**：`anthropic_out.py:1`、`gemini_out.py:1`、`base.py:1-5`、`main.py:28`/`admin.py:34` 全部核实无误——**这是本次设计里最扎实的一节**。
14. **§19 已修的两处依赖倒置**：M3-3→M3-4（方言表→caps）顺序正确；M4-3→M4-4（鉴权→额度联网）顺序正确。
15. **§20 不做清单**：19 条中 14 条与 `research/19` §2.2、`research/16:257`（参考项目无租约）、`research/18:153`（无 tier 概念）等证据对应，无凭空条目。

---

## 6. 可测试性专项（§19 交付判据逐条核）

| 判据 | 可否自动验证 | 说明 |
|---|---|---|
| M3-1「零映射启动有明确告警」 | ✅ | 断言 stderr/日志即可 |
| M3-2「`/v1/models` 返回 7 字段」 | ✅ | pytest 断言响应键集合 |
| M3-2「工具不再删 `tools`」 | ❌ | 需真实 WorkBuddy CLI（且受 `research/08:538` O1「工具自身登录态」阻塞）→ 应降为手工 E2E |
| M3-3「方言表落盘」 | ✅ | 断言文件内容 |
| M3-3「探测成功率与 429 退避**实测记录**」 | ❌ | "记录"不是判据 → 改为「探测结果可复现 + 429 触发时退避次数可断言」 |
| M3-4「工具按能力位正确下发推理档位」 | ❌ | 需真实工具 → 手工 E2E；可自动化的**代理指标**是「`thinkingLevelMap` 7 键齐全且不支持档为 `null`」 |
| M3-5「CLI 经 `mgw setup` 后工具调用不被剥离」 | ❌ | 需真实 CLI + 登录；且 `research/08:654` 记录该文件可能被外部改写 → 手工 E2E + 内容断言 |
| M4-1「经 Anthropic 协议上游完成一次 chat」 | ✅ | 现有测试已有"可编程假厂商 ASGI"模式（`tech-design.md:68`）→ 假 Anthropic 上游可完全 mock |
| M4-2「设备 ID 唯一性校验生效」 | ✅ | 纯逻辑单测 |
| M4-2「主 `~/.zcode` 不被写」 | ❌ | 见 P0-3，判据本身不可达 |
| M4-3「JWT / API Key 都能打通（T5 实测）」 | ❌ | 需真实凭据 + WAF → 手工 |
| M4-4「多账号额度可查可聚合」 | ⚠️ | 归一化逻辑可单测（喂 fixture）；真实额度需联网 |
| M5-0「CLI 入口可用」 | ✅ | `--help` + 退出码 |
| M5-1「四类结果分类正确 + 双层互斥生效」 | ✅ | 假上游注入 1003/1005/网络错 → 断言分类；并发触发断言只领一次 |
| M5-1「无住宅代理时降级为 `failed` 且不影响模型转发」 | ✅ | 配置 + 并发模型请求断言 |
| M5-2「管理端可见聚合数字」 | ✅ | 接口断言 |
| M5-3「并发下不超发」 | ✅ | 并发单测 |

**§13.3 探测如何 mock**：现有 `§2` 已声明测试用 `httpx.MockTransport` / 假厂商 ASGI（`tech-design.md:68`），但 §13.3 **未说明探测的上游调用是否可注入**。建议：`mgw probe` 的探测函数签名接受 `call_fn: Callable`（默认走真实 adapter），单测注入"按请求体返回 400/200 + 指定 `reasoning_tokens`"的假序列 → 可确定性验证 S1/S2/S3 三步逻辑。**这是 M3-3 能进 CI 的前提**，建议写进判据。

---

## 7. 附：本次审核的检索范围（供复核）

- **代码**：`model_gateway/` 全量 `*.py`（重点 `enums/matcher.py`、`config/schemas.py`、`core/{ir,resources,scheduler,errors}.py`、`adapters/{base,openai_out,anthropic_out,gemini_out}.py`、`api/{openai_compat,admin}.py`、`main.py`）、`pyproject.toml`。
- **关键词**：`caps_overrides`、`tool_call`、`thinking_format`、`thinkingLevelMap`、`dialects`、`product`、`match_enum`、`call(`、`protocol`、`adapters[`、`mgw`、`[project.scripts]`、`argparse`、`click`、`console_scripts`、`os.replace`、`tempfile`、`model_dump`。
- **文档**：`docs/specs/tech-design.md`（§1–§20 全读）、`docs/research/{04,05,07,08,10,14,15,16,17,18,19}`、`docs/specs/prd.md:633`。
- **外部**：`curl-cffi.readthedocs.io`（feature matrix / asyncio 页）。
- **未做**：未运行测试、未启动服务、未调用任何上游。
