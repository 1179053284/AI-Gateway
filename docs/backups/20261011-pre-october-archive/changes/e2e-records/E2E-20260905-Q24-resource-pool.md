# E2E-20260905 · Q24 资源池设置改版（更名 / 厂商归属分组 / 模型属性 / 参数配置 / 添加模型）

> 需求：用户 2026-09-05 六点 + 追加两点（更名资源池设置；卡片按厂商归属分组（与接入商解耦）；
> 启停语义澄清；删除按钮暂时隐藏；右侧模型属性卡；底部参数配置卡对齐官方默认；
> 添加模型能力；四厂商 2026 模型一次整理）。
> 三项定论（AskUserQuestion）：①「热度」= temperature；② 官方默认直接写入 config.yaml 作初始值；
> ③ 参数按各模型官网暴露项对齐、暂不支持自定义参数、架构按可扩展设计（开放 dict + 已知键范围校验）。

## 一、改动清单

| 层 | 文件 | 内容 |
| --- | --- | --- |
| 后端·目录 | `model_gateway/enums/matcher.py` | EnumEntry 增 `vendor / context_window / max_output / image|video|audio_input / reasoning / effort_levels / params_default` 字段 + to_dict + load_enum_pool 解析；BUILTIN_ENTRIES 9 → 15 条（回填取证属性与官方默认参数） |
| 后端·配置 | `model_gateway/config/schemas.py` | SystemModel 增 `params: dict`（模块级 `PARAM_RANGES`：temperature 0~2 / top_p 0~1 / 双惩罚 ±2 / max_tokens≥1；未知键放行 = 可扩展架构） |
| 后端·注入 | `model_gateway/core/ir.py`（apply_model_params）+ `core/scheduler.py:222-229`（_out_body 字段级注入，仅 chat）+ `main.py`（Runtime.model_params） | 优先级 = 工具传参 > 网关设置 > 厂商内置：请求体该键存在且非 None 则不注入；显式 null = 不注入；重试/切换每次重算（同 INT-37 语义） |
| 后端·API | `model_gateway/api/admin.py` put_enums | 新字段全量透传（写 model-enums.yaml 持久化） |
| 数据 | `data/config.yaml` | 五个 chat 模型 params 预填官方默认；`config.example.yaml` 增 params 说明 |
| 前端 | `js/pages/models.js` 全量重写 + `index.html` + `js/main.js` | 更名「资源池设置」；按目录 vendor 归属分组；删除按钮隐藏（`SHOW_DELETE=false` 一键恢复）；模型属性卡（只读）；参数配置卡（网关值 + 官方默认列 + 填入官方默认 + 自定义添加）；「＋ 添加模型」弹窗（未接入目录模型、官方默认自动带入） |
| 测试 | `tests/unit/test_ir.py`（TestApplyModelParams 5 场景）、`tests/unit/test_config.py`（TestModelParams 4 场景）、`tests/integration/test_int_chat.py`（TestModelParamsInjection 3 场景）、`tests/unit/conftest.py`（build_runtime 补 model_params） | 语义与出站体断言 |

## 二、官网取证（铁律：仅官方域名，逐条附 URL）

### 商汤 SenseNova
- 第一方实测 `GET https://token.sensenova.cn/v1/models`（网关实际接入端点，2026-09-05）：8 模型含
  `sensenova-6.8-flash-lite`（input text+image，context 262144，max_output 65536）、
  `deepseek-v4-flash/pro`（ctx 1048576 / out 65536）、`glm-5.2`（ctx 1048576 / out 131072）、
  `kimi-k3`（ctx 1048576 / out 65536）、`u1-fast / u1.5-lite`。
- 官方 API 文档 `https://github.com/OpenSenseNova/SenseNova6.7/blob/main/API_CN.md`（OpenSenseNova 官方组织）：
  §5 推荐采样参数表——思考模式·通用任务 `temperature 1.0 / top_p 0.95 / top_k 20 / min_p 0.0 / presence_penalty 1.5 / repetition_penalty 1.0`；
  思考·精确编码 `0.6/0.95/20/0/0/1.0`；指令·通用 `0.7/0.8/20/0/1.5/1.0`；指令·推理 `1.0/1.0/40/0/2.0/1.0`。
  官方未给「缺省值」，本网关取思考模式·通用任务组合作初始值（已在下文实测全组合 200）。
- `message.reasoning` 字段 = 思考过程；`max_tokens` 含 reasoning；图片 URL/Base64 双通道（§7）。
- 上下文窗口：sensecore 帮助中心为 JS 渲染无法抓取 → 采用 `/v1/models` 第一方数值（262144）。

### DeepSeek
- `https://api-docs.deepseek.com/quick_start/pricing`：模型 = deepseek-v4-flash（V4-Flash-0731）/ deepseek-v4-pro（V4-Pro-0813）/ deepseek-v4-flash-vision-exp（实验、图片输入）；CONTEXT LENGTH 1M；MAX OUTPUT 上限 384K（经商汤接入实为 65536，按第一方为准）。
- `https://api-docs.deepseek.com/guides/thinking_mode`：思考默认开启、默认 effort **high**；effort 枚举 low/medium/high/xhigh/max（medium/xhigh→high）；**思考模式不支持 temperature/top_p/presence_penalty/frequency_penalty（不报错但不生效）**。
- `https://api-docs.deepseek.com/api/create-chat-completion`：`temperature` 默认 **1**、`top_p` 默认 **1**、thinking 默认 enabled。
- `https://api-docs.deepseek.com/news/news260424`：V4 Preview——Flash 284B/A13B；1M 上下文全服务默认；双模式。
- 结论：params_default = `{temperature: 1.0, top_p: 1.0}`（官方缺省；思考模式下不生效，与厂商内置一致，注入无害）。

### 智谱 GLM（docs.z.ai 官方文档站）
- `https://docs.z.ai/guides/llm/glm-5.2.md`：Flagship；输入输出纯文本；Context 1M / Max Output 128K；thinking 默认 enabled（GLM-5.2 自动判断是否思考）。
- `https://docs.z.ai/guides/llm/glm-5.3.md`：纯文本；1M/128K；**强制思考**（disabled 不再支持）；effort low/high/max 默认 max。
- `https://docs.z.ai/guides/vlm/glm-5.3-flash.md`：输入 Video/Image/Text/File；1M/128K；320B/A18B；推荐设置 `temperature 1 / top_p 0.95 / effort max`。
- `https://docs.z.ai/guides/overview/concept-param.md`：temperature/top_p 默认「模型相关」未给缺省值（→ 不注入 temperature）；max_tokens 默认表：glm-5.2/5.3/5.3-flash 默认 **65536**（上限 131072）；reasoning_effort 允许 max/high/low（GLM-5.2 另接受 xhigh/medium/minimal/none 映射）。
- 结论：glm-5.2/5.3 params_default = `{max_tokens: 65536}`；glm-5.3-flash = `{temperature: 1.0, top_p: 0.95, max_tokens: 65536}`。

### Moonshot Kimi（platform.moonshot.cn 官方文档站）
- `https://platform.moonshot.cn/docs/models`：2026 在售 = `kimi-k3`（2.8T 参数、原生视觉、1M 上下文）/ `kimi-k2.7-code`（256K）/ `kimi-k2.7-code-highspeed` / `kimi-k2.6`（256K，视觉+文本、思考/非思考）；k2.5、k2 系列、moonshot-v1、kimi-latest 已下线。
- `https://platform.moonshot.cn/docs/api/models-overview`（参数参考）：k3 / k2.7-code `temperature` **固定 1.0**、`top_p` **固定 0.95**、双惩罚固定 0（传入其他值报错，官方建议勿显式传入）；k2.6 思考 1.0 / 非思考 0.6；k3 `reasoning_effort` low/high/max 默认 **max**、始终推理；k2.7-code thinking 恒 enabled+keep all。
- `https://platform.moonshot.cn/docs/api/chat`：K3 `max_completion_tokens` 默认 131072、最大 1048576（经商汤接入上限 65536，按第一方为准）。
- 结论：k3/k2.7 系/k2.6 params_default = `{temperature: 1.0, top_p: 0.95}`（官方固定值；注入值与固定值一致不报错）。

### 未核实项（诚实标注）
- sensenova-6.8-flash-lite 深度推理「档位」：官方只有思考模式开关、无 effort 档位文档 → `effort_levels=[]`，界面显示「支持（档位未核实）」。
- kimi-k3 的 `only_base64_image=True`（既有 E2E 实测结论）与上游 `/v1/models` input_modalities=[text] 存在出入：保留实测结论（上游元数据可能未反映图片通道），已在界面以独立字段呈现。
- claude-sonnet-4 / claude-opus-4（Anthropic 预置路由别名）：属性未取证，仅保留 vendor 归属。
- DeepSeek/智谱/Kimi 直连官方端点的原厂属性（如 K3 输出上限 131072）与经商汤接入的第一方数值（65536）取后者：目录属性 = 网关实际可达口径；原厂口径记录于本文件备查。

## 三、实测证据

### 1) 单测 / 集成测试
```
.venv/bin/python -m pytest -q
→ 199 passed（原 187 + 新增 12：UT 注入 5 / UT params 校验 4（含温度 99 拒绝、max_tokens 0 拒绝、未知键 top_k 放行）/ INT 注入 3）
```
关键断言：
- 注入 + 请求覆盖：params `{temperature:0.3,max_tokens:99}` + 请求 temperature=0.7 → 出站 `temperature=0.7, max_tokens=99`（字段级优先级）
- 无 params → 出站体与请求一致（透传）
- images 端点 → 不注入

### 2) 真实调用（网关 8300 → 商汤上游）
| 用例 | 结果 |
| --- | --- |
| kimi-k3 不带采样参数（注入 1.0/0.95） | 200，finish=stop（首轮遇上游 RPM 限流，直连同参同错，非注入问题；稍后重试通过） |
| sensenova-6.8-flash-lite 请求显式 temperature=0.7（请求 > 网关 1.0） | 200，finish=length |
| deepseek-v4-flash 不带采样参数（注入 1.0/1.0） | 200 |
| images u1-fast（2048x2048，不注入） | 200，返回 url |
| 商汤官方推荐参数全组合直连实测 | 200（top_k/min_p/presence_penalty/repetition_penalty 均被接受） |

### 3) 界面实测（IAB 浏览器，1440×900）
- 导航与页标题 = 「资源池设置」；面包屑 `Console › 资源配置 › 资源池设置`。
- 左卡按厂商归属：商汤 SenseNova（3/3）、DeepSeek（2/3）、智谱 GLM（1/3）、Moonshot Kimi（1/4）、Anthropic（0/2 未接入）+ 自定义卡（无自定义模型时不显示）；deepseek-v4-* 经商汤接入仍归 DeepSeek 卡（解耦验证 ✓）；行 = 模型 ID + 启用状态点；每卡底部「＋ 添加模型」。
- 删除按钮：头卡仅「禁用」按钮，无删除（SHOW_DELETE=false）。
- 模型属性卡（只读）：sensenova-6.8-flash-lite = 256K/64K/图片✓/深度推理 支持（档位未核实）；deepseek-v4-flash = 1M/64K/档位 low/high/max。
- 参数配置卡：六参数行（网关值 + 官方默认列 + 填入官方默认）+ 添加参数；优先级提示「工具调用传参 > 此处网关设置 > 模型厂商官方内置」。
- 添加模型回环：智谱卡 → 弹窗列出 glm-5.3 / glm-5.3-flash（含属性摘要）→ 选 glm-5.3 → 创建成功且参数卡 max_tokens=65536 官方默认自动带入 → 测试后从配置移除（避免留下无资源映射的不可调用模型），目录仍保留供后续接入。
- **「基本属性」板块移除（Q24-⑨，同日用户追加定版）**：初版含端点/分组编辑卡，用户看板后要求去掉——已移除该卡与对应保存事件（`#md-endpoint`/`#md-group` DOM 断言不存在），页面结构定版 = 头卡 + 模型属性 + 资源池 + 参数配置；端点/分组数据字段保留（创建时由「添加模型」按目录带入，调整走配置文件）。移除后截图 `q24-shots/dark-no-basic-attr.png`。
- 截图（双主题）：`docs/changes/e2e-records/q24-shots/`（light-top / light-params / dark-top / dark-deepseek / dark-no-basic-attr.png）。

### 4) 参数对照二次核实（Q24-⑩，2026-09-05 用户看板反馈后逐家复查）
| 厂商 | 复查结论（官方域证据） | params_default 终版 |
| --- | --- | --- |
| DeepSeek | `api-docs.deepseek.com/api/create-chat-completion`：**`frequency_penalty` / `presence_penalty` 标记 deprecated（"no longer supported, will not take effect"）**；`stop`（≤16 序列）与 `max_tokens` 无固定默认（"refer to the documentation"）；带默认值仅 temperature 1 / top_p 1（thinking 默认 enabled、effort 默认 high 归推理体系；response_format 默认 text 不注入防与 json_mode 冲突） | `temperature 1.0, top_p 1.0`（维持 2 项，**不虚构**） |
| 智谱 GLM | `docs.z.ai/api-reference/llm/chat-completion`：**分系列默认——GLM-5.3/5.2 系列 `temperature` 默认 1.0（范围 0~1）、`top_p` 默认 0.95（范围 0.01~1）、`do_sample` 默认 true**（此前仅按 concept-param「模型相关」处理，属漏列，已修正）；max_tokens 默认 65536（concept-param 默认表） | `temperature 1.0, top_p 0.95, do_sample true, max_tokens 65536`（+3） |
| Moonshot Kimi | `platform.moonshot.cn/docs/api/models-overview`：k3 / k2.7-code / k2.6 三列均列 **`presence_penalty` 固定 0、`frequency_penalty` 固定 0**（与 temperature/top_p 同为「固定」口径） | `temperature 1.0, top_p 0.95, presence_penalty 0, frequency_penalty 0`（+2；k2.6 温度按思考模式取 1.0，非思考 0.6 已记录） |
| 商汤 | 复查无变化：官方文档仅给推荐采样参数组合（6 项已全取），`/v1/models` supported_sampling_parameters=[temperature, stop] 无更多默认 | 6 项推荐组合（不变） |

注入与回写：GLM/Kimi 新增键已同步写入 `data/config.yaml`（用户定论② 官方默认作初始值）；网关重启后实测——glm-5.2 注入 4 参数真实调用 200（finish=stop）、kimi-k3 注入 4 参数真实调用 200（首轮遇上游 TPM 额度耗尽 `ModelAccountTpmRateLimitExceeded`，窗口后重试通过）；pytest 199/199 持平。
界面（Q24-⑩）：模型属性卡去「归属厂商」行、改三列栅格；头卡副标题去厂商前缀；截图 `q24-shots/dark-kimi-3col-params.png`（kimi-k3 三列属性 + 4 参数行）。

### 5) 参数行「× 移除」按钮（同日用户反馈补全）
- 用户反馈「添加的自定义参数没法清除」：原实现清空自定义参数值 + 失焦才会删行（不可发现），未保存的空行则完全无法移除。
- 修复：每条参数行尾增 × 按钮——官方参数 = 清空网关值（行保留显示官方默认参考，配置删除该键）；自定义参数 = 删除该行并从配置移除该键；未保存本地行 = 仅移除 DOM。底部提示文案同步。
- 实测：deepseek-v4-flash 添加自定义 `top_k=40` → 点 × → 行消失 + toast「已删除参数 top_k」+ 配置恢复 `{temperature, top_p}`；点官方 `temperature` × → toast「已清空（不再注入，走厂商内置）」+ 行保留值空 + 配置移除该键；点「填入官方默认」恢复。pytest 199/199 持平。

### 6) 三处澄清（同日用户三问）
- images 模型详情移除「images 端点不注入网关参数」提示段（参数配置卡不渲染时提示无依附）。
- 属性卡「端点类型」更名「网关端点」：chat/images = 网关统一对外 API 的两类端点统一枚举（PRD FR-1/FR-4），非厂商概念、非自造业务词（对应 `/v1/chat/completions` 与 `/v1/images/generations`）。
- 资源池行内 effort 自由文本改下拉枚举：目录 `effort_levels`（DeepSeek low/high/max、GLM max/high/low、K3 low/high/max）优先，无档位文档的模型（商汤 6.8、K2.x、自定义）以通用三档 low/high/max 兜底 + 悬停说明「官方未公布档位」；后端 `ReasoningDefault.effort` 为不透明透传（`schemas.py:106` min_length=1 无枚举校验），取值约束由 UI 承担；遗留自由值兼容保留为额外选项。实测：选 high 落盘 `{enabled:true, effort:"high"}` → 恢复「不注入」→ reasoning 回 None；pytest 199/199。截图 `q24-shots/dark-effort-select.png`。

### 7) 参数配置卡版式精简（同日用户定版）
- 去每行「填入官方默认」按钮与「官方默认：X」显示列（初始化的值就是默认值），行 = 参数名 + 网关值输入 + ×。
- 卡头优先级文案右侧增「恢复官方配置」按钮：确认弹窗 → `m.params = {...目录 params_default}` 全量重置（覆盖当前值与自定义参数）；无官方默认的模型按钮禁用。
- 实测：temperature 改 0.7 → 恢复官方配置 → 确认 → toast「已恢复官方默认参数」+ 值回 1 + 配置回 `{temperature:1, top_p:1}`；DOM 断言 data-fill=0、「官方默认：」文字 0 处。（本条截图因内置浏览器捕获通道瞬时故障未存档，行为以 DOM 断言与配置回验为准。）

### 8) 参数配置卡两列栅格（同日用户定版）
- `#md-params` 改 `repeat(2,minmax(0,1fr))` 两列栅格（单元格 = 参数名 170px + 弹性输入框 + 行尾 ×，去中部大空白），≤1080px 窄屏回退单列。
- 实测：DOM 断言 grid 2 列 × 6 单元格；截图 `q24-shots/dark-params-2col.png`（sensenova-6.8-flash-lite 六参数两列）。

### 9) 分割线与间距修正（2026-09-06 用户反馈）
- 根因：全局 `.list-row + .list-row { border-top }` 兄弟分割线在两列栅格里错位生效（每格上缘都有线且左右不对齐），叠加 6px 行距显得过挤。
- 修正：网格内单元格屏蔽继承分割线（`#md-params .list-row + .list-row { border-top:0 }`），行距对齐项目 12px 节奏（`gap:12px 28px`）。DOM 断言：6 单元格 border-top 全 0、rowGap 12px；截图 `q24-shots/dark-params-2col-gap12.png`。

### 10) 「深度推理（档位未核实）」文案澄清（2026-09-06 用户问询）
- 复核结论（证据）：商汤官方 API 文档（OpenSenseNova API_CN.md 全文）**无任何 effort/档位字样**——推理仅有「思考模式 / 指令模式」开关；第一方 `token.sensenova.cn/v1/models` 元数据中 sensenova-6.8-flash-lite 仅 `supported_features=[tools, json_mode, reasoning]`、`supported_sampling_parameters=[temperature, stop]`，**无 effort 字段**。即「档位未核实」的实质 = **官方未公布**，按信息核实纪律不得虚构 low/high/max。
- 措辞修正：模型属性卡显示「支持（官方未公布档位）」+ 悬停说明（官方仅思考模式开关；资源池 effort 提供通用 low/high/max 供选用）；与 DeepSeek/GLM/K3 的「档位 low/high/max」（官方公布）形成对照。DOM 断言旧文案 0 处、新文案 1 处。

### 11) 已知边界
- 运行中的旧网关进程不识别 params 字段，需重启进程（本次验证已重启）；配置文件热重载只针对配置内容。
- 添加参数的空值行不落配置（填值后才保存），避免空串进入请求体。
- Anthropic 卡仅作路由别名归属展示，无属性/参数（未取证不虚构）。
