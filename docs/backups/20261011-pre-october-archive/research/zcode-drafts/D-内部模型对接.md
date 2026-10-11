# D · 内部模型对接（R6）

> 调研对象：`zcode2api`（Python/FastAPI）、`zcode-proxy`（Go）、`zcode-reverse-engineer/docs`
> 证据等级：【一手】= 直接读到的代码；【推断】= 未经代码证实；【未验证】= 卡住没证实
> 行号引用基准为本次只读快照。

## 修订记录（据独立核验 `verify-CDE.md` 逐条修正）

| 原表述 | 修正后 | 类型 |
|---|---|---|
| 「TLS 指纹伪装是**刚需而非可选**」 | 代码依据是"**易**被识别"（非"必被拒绝"），且**保留 `off` 模式**（`tls_fingerprint.go:31,117-124`）、DB 设置可改。改为「**强默认项（可关闭）**，实际拦截率未测」 | 过度推论（把"强建议"升格为"硬约束"） |
| 「**内部统一强制** `stream:true` 再按需聚合」 | **只对 OpenAI / Responses 生效**；Anthropic 原生路径不强制（`relay.go:232` `upstreamStream := rc.clientStream || rc.proto != protocolAnthropic`） | 表述过宽（§①#3 已限定，§⑨ 清单行未同步） |

---

## ① 结论先行

1. **ZCode 内部 AI 协议不是 OpenAI 兼容，而是 Anthropic Messages API 格式**（`ai-protocol.md:3`）。路径形如 `.../anthropic/v1/messages`，请求体用 `system` / `messages[].content[].type` / `thinking` / `max_tokens`，SSE 用 `message_start` / `content_block_delta` 事件族。
2. **两个项目对外都暴露"三协议一套内核"**：Anthropic `/v1/messages` 原生透传 + OpenAI `/v1/chat/completions` + OpenAI `/v1/responses`，另有 `/v1/models`。内核统一把请求**规范化为 Anthropic 格式**，再转发上游。
3. **OpenAI / Responses 侧一律"内部强制流式、按需聚合"**：即便客户端要非流式，也向上游发 `stream:true` 再聚合（`gateway.py:375`、`handlers_openai.go:37`、`relay.go:232`）。
   ⚠️ **限定**：**Anthropic 原生路径不强制** —— `relay.go:232` `upstreamStream := rc.clientStream || rc.proto != protocolAnthropic`，当 `proto==protocolAnthropic && clientStream==false` 时 `upstreamStream=false`；`HandleMessages`（`relay.go:94-99`）不覆写 body 的 `stream` 字段。
4. **`convert.go` 是 `gateway.py` 的 Go 移植**，两者逐函数对应（`convert.go:15-17` 自述）。
5. **TLS 指纹伪装是强默认项（非硬约束）**：`zcode.z.ai` 前置 ESA WAF，Go 默认 ClientHello **易被**判定为机器程序，故对 `zcode.z.ai` 专用 utls 指纹客户端 + 禁用 HTTP/2（`tls_fingerprint.go:14-17`、`client.go:290-291`、`client.go:324-342`）。
   ⚠️ **限定**：代码依据是"**易被识别**"而非"必被拒绝"；实现**保留 `off` 模式**（`tls_fingerprint.go:31`、`:117-124` 回退标准库），DB 默认设置 `"fingerprint": "chrome"` **可改**。**实际拦截率未测**（→ 见 §⑩ #7）。
6. **鉴权是双通道**：Plan/JWT 通道（`Authorization: Bearer <Coding Plan JWT>` → `zcode.z.ai`）与 API Key 通道（`x-api-key` → `api.z.ai` / `open.bigmodel.cn`），并有三级降级链。
7. 还有一个**独立于人机校验的隐性门槛**：免费 JWT 通道要求阿里云无痕验证参数 `X-Aliyun-Captcha-Verify-Param`，需无头浏览器实时求解（`captcha.py:197-263`、`relay.go:394-399`）。

---

## ② ZCode 内部协议（Anthropic 风格）

**端点三选一**【一手】：

| 通道 | 端点 | 认证 |
|---|---|---|
| zai（Plan/JWT，默认） | `https://zcode.z.ai/api/v1/zcode-plan/anthropic/v1/messages` | `Authorization: Bearer <JWT>` |
| zai_fallback（API Key） | `https://api.z.ai/api/anthropic/v1/messages` | `x-api-key` |
| bigmodel | `https://open.bigmodel.cn/api/anthropic/v1/messages` | `x-api-key` |

来源：`settings.py:102-115`；Go 侧同值 `config.go:36-40`。文档侧另记 `https://api.z.ai/api/anthropic/v1/messages` 走 `x-api-key: <JWT>`（`ai-protocol.md:41-43`）——与代码的"JWT 走 Bearer 到 zcode-plan"路径不同，**两条都真实存在**（代码里 JWT 优先走 zcode-plan，API Key 才回落 api.z.ai，见 `agent.py:60-71`）。

**请求头**【一手】`agent.py:80-92`：

```
content-type: application/json
accept: text/event-stream | application/json     # 跟随 stream
Authorization: Bearer <jwt>  或  x-api-key: <key>
anthropic-version: 2023-06-01
User-Agent: ZCode/3.7.7                          # settings.py:167-168
X-ZCode-App-Version: 3.7.7
X-ZCode-Agent: glm
HTTP-Referer: https://zcode.z.ai/
X-Aliyun-Captcha-Verify-Param: <verifyParam>     # 仅 JWT+验证码路径
```

Go 版额外补一批桌面端身份头：`X-Title: Z Code@electron`、`X-Platform`、`X-Release-Channel: stable`、`X-Client-Language: zh-CN`、`X-Client-Timezone`、`X-Os-Category`、`X-Os-Version`、`X-Device-Mid`、`x-request-id`（`client.go:228-250`），并在验证码路径追加 `X-Aliyun-Captcha-Verify-Region`（`relay.go:394-399`）。

**请求体字段**【一手】`ai-protocol.md:69-88` + 代码：
`model`、`max_tokens`、`temperature`、`top_p`、`stream`、`system`（字符串或 block 数组）、`messages[]`（`content` 为 typed block 数组）、`thinking:{type:"enabled",budget_tokens:N}`、`reasoning_effort`、`stop_sequences`、`tools[]`、`tool_choice`（`gateway.py:52-65,188`、`gateway.py:538-589`）。

**SSE 事件族**【一手】`ai-protocol.md:113-134`，解析实现 `gateway.py:1230-1246`、`convert.go:82-101`：

```
event: message_start            → message.usage.input_tokens
event: content_block_start      → content_block.type ∈ {text, thinking, tool_use}
event: content_block_delta      → delta.type ∈ {text_delta, thinking_delta, input_json_delta}
event: content_block_stop
event: message_delta            → delta.stop_reason + usage.output_tokens
event: message_stop
event: error                    → {type,code,message}（流内错误，不可吞）
```

**错误体**【一手】`ai-protocol.md:138-147`：`{"type":"error","error":{"type","code","message"},"request_id"}`；余额不足示例 `code:"1113"`。

**模型名大小写敏感**，必须发官方名（`gateway.py:33`、`relay.go:28`）。

---

## ③ 字段差异全表（OpenAI Chat/Responses → Anthropic）

| OpenAI 字段 | Anthropic 字段 | 处理 | 位置 |
|---|---|---|---|
| `messages[].role=system\|developer` | `system`（单个字符串） | 抽出，多条用 `\n\n` 拼接 | `gateway.py:466-475,540`；`handlers_openai.go:146-159,266` |
| `messages[].content: string` | `[{type:"text",text}]` | 桥接成 block 数组 | `gateway.py:195-196,494-495`；`relay.go:528-548` |
| `role:"tool"` + `tool_call_id` | `role:"user"` + `[{type:"tool_result",tool_use_id,content}]` | role 改写 | `gateway.py:476-489`；`handlers_openai.go:161-180` |
| `assistant.tool_calls[].function.{name,arguments}` | `[{type:"tool_use",id,name,input}]` | `arguments` 做 `json.loads`；解析失败塞 `{"_raw_arguments":...}` | `gateway.py:512-531`；`handlers_openai.go:219-252` |
| `image_url.url` = `data:*;base64,...` | `{type:"image",source:{type:"base64",media_type,data}}` | **仅** data-URI；远程 http(s) 图片 URL 静默丢弃 | `gateway.py:502-511`；`handlers_openai.go:199-215` |
| `max_tokens` / `max_completion_tokens` | `max_tokens` | 优先级：`max_tokens` > `max_completion_tokens` > 4096 | `gateway.py:541-546` |
| `temperature` / `top_p` | 同名直传 | — | `gateway.py:547-550` |
| `stop`（string\|array） | `stop_sequences`（数组） | 字符串包成单元素数组 | `gateway.py:551-553` |
| `tools[].function.{name,description,parameters}` | `{name,description,input_schema}` | schema 取 `parameters`\|`input_schema`\|`schema`，缺失填 `{type:object,properties:{}}` | `gateway.py:555-579` |
| `tool_choice: "auto"/"required"/{function:{name}}` | `{type:"auto"}`/`{type:"any"}`/`{type:"tool",name}` | 三态映射 | `gateway.py:581-589` |
| Responses `instructions` | `system` | 拼进 system_parts | `gateway.py:620-622` |
| Responses `input`（string\|array） | `messages[]` | `function_call`/`function_call_output` 归一成 assistant.tool_calls / role:tool | `gateway.py:624-661` |
| Responses `max_output_tokens` | `max_tokens` | 优先 `max_output_tokens` | `gateway.py:673-676` |
| Responses `reasoning.effort` | `reasoning_effort` | 直传 | `gateway.py:685-688` |
| `model` 含 `provider/` 前缀 | 去前缀 | `split("/")[1:]` 重组 | `gateway.py:181-182`；`relay.go:506-509` |
| **丢弃（无任何映射代码）** | — | `n`、`presence_penalty`、`frequency_penalty`、`logit_bias`、`seed`、`user`、`response_format`、`logprobs`、`top_logprobs` | 【推断】`gateway.py:454-590` 全文未引用这些键 |

**响应 Anthropic → OpenAI**【一手】：

| Anthropic | OpenAI Chat | OpenAI Responses | 位置 |
|---|---|---|---|
| `text` block / `text_delta` | `message.content` | `output[].content[].output_text` + `output_text` | `gateway.py:712,775-782`；`convert.go:266,919-927` |
| `thinking` block / `thinking_delta` | **`message.reasoning_content`**（DeepSeek 风格） | `output[].type="reasoning"`，`summary[].summary_text` | `gateway.py:713-714,910,760-765`；`convert.go:483,899-904` |
| `tool_use` | `message.tool_calls[].function.arguments`（JSON 字符串） | `output[].type="function_call"`（`call_id`,`name`,`arguments`） | `gateway.py:715-729,766-774` |
| `stop_reason` | `finish_reason`：`max_tokens→length`、`tool_use→tool_calls`、其他→`stop` | — | `gateway.py:692-697`；`convert.go:842-850` |
| `usage.{input,output}_tokens` | `prompt_tokens`/`completion_tokens`/`total_tokens` | `input_tokens`/`output_tokens`/`total_tokens` | `gateway.py:740-744,748-755` |
| — | `id: chatcmpl-*`、`object: chat.completion` | `id: resp_*`、`object: response` | `gateway.py:731-732,784-786` |

---

## ④ 对外暴露形态

**zcode2api（FastAPI，默认端口 3000）**【一手】`settings.py:58`：

| 方法 | 路径 | 说明 | 位置 |
|---|---|---|---|
| GET | `/v1/models` | 同时含 `object:"model"`（OpenAI）与 `type:"model"`（Anthropic） | `gateway.py:302-320` |
| POST | `/v1/messages` | Anthropic 原生 | `gateway.py:324` |
| POST | `/v1/chat/completions` | OpenAI Chat | `gateway.py:361` |
| POST | `/v1/responses` | OpenAI Responses（Codex 可直连） | `gateway.py:408` |
| — | `/v1/messages/`、`/v1/v1/messages`、`/v1/v1/chat/completions`、`/v1/v1/responses`、`/v1/v1/models` | base_url 误带 `/v1` 的兼容别名 | `gateway.py:345,350,355,403,449` |

- **无 `/v1/messages/count_tokens`**（grep 确认 gateway.py 无此路由）——Anthropic SDK 探测会 404。
- 鉴权：`Depends(verify_gateway_key)`（`auth_admin.py:57-69`）：从 `Authorization: Bearer` **或** `x-api-key` 取值，`hmac.compare_digest` 比对 `store.gateway_key()`（`store.py:156-157`）；**key 未配置则直接放行**。

**zcode-proxy（Go，默认监听 `127.0.0.1:8687`）**【一手】`config.go:66`、`main.go:109-121`：

| 路径 | 说明 |
|---|---|
| `/v1/messages`、`/v1/messages/` | Anthropic 原生 |
| `/v1/messages/count_tokens` | **有**，返回 `chars/4+8` 保守估计（`zcode_api.go:99-115`） |
| `/v1/chat/completions`、`/v1/responses`、`/v1/models` | OpenAI 三件套 |
| `/health`、`/oauth/callback`、`/web`、`/api/*` | 运维与后台 |

- 鉴权：`auth.Middleware` 包裹全局（`main.go:169`、`auth.go:265-314`）。`/v1/*` 用 **`sk-` 前缀 API Key**（`GenerateAPIKey`，`auth.go:172-178`），`x-api-key` 或 `Authorization: Bearer` 二选一，`subtle.ConstantTimeCompare` 常数时间比较（`auth.go:252-262`）。`/api/*` 用 session cookie；`/web`、`/oauth/`、`/health` 免认证（`auth.go:270-274`）。

---

## ⑤ 模型映射与目录

**别名映射表**【一手】：

- zcode2api：`MODEL_NAME_MAP`，6 条（`glm-5.3→GLM-5.3`、`glm-turbo→GLM-5-Turbo` 等），按 `model.lower()` 查（`gateway.py:34-41,185`）。
- zcode-proxy：`modelNameMap`，11 条（含 `glm-4.5v→GLM-4.5V` 等）（`relay.go:29-41`）。
- 规范化顺序（Go 版更完整）：去 `provider/` 前缀 → 查别名表 → 否则与 `cfg.GetModels()` 做 `EqualFold` 匹配并回写官方名（`relay.go:505-521`）。

**对外 `/v1/models` 清单来源**：

- zcode2api：**纯静态**，来自环境变量 `ZCODE_MODELS`（默认 9 个 GLM）（`settings.py:146-159`、`gateway.py:44`）。
- zcode-proxy：`config.json` 的 `models` 字段（默认 9 个，`config.go:43-46`），可被 DB setting `gateway_models` 逗号串覆盖（`zcode_api.go:119-131`）。

**官方模型目录拉取端点**【一手】：

```
GET https://zcode.z.ai/api/v1/client/configs?version=<appVersion>&os=<platform>
→ data.builtinModels[]  （空则回退 data.providers[].models[]）
字段：modelId / name / contextWindow / priority / vision
```

实现 `reset.go:250-303`（`CatalogModel` 结构 `reset.go:241-247`），结果去重后缓存到 DB setting `model_catalog`（`reset.go:298-300`）。该接口**无需认证**（`client-configs.md:13,65`）。

**参数名存在分歧**【未验证】：代码用 `version` + `os`（`reset.go:251`、`captcha.py:128-130`），文档用 `app_version` + `platform`（`client-configs.md:32-34`）。两者是否等价、服务端是否都接受，未实测。

**注意**：zcode2api **不拉目录**，只用静态 allowlist；只有 zcode-proxy 做了目录同步。

---

## ⑥ 请求 / 响应 / 流式转换

**`convert.go` 做了什么**【一手】：它就是 `gateway.py` 的 Go 移植，自述对应 `_openai_to_anthropic / _responses_to_anthropic / _openai_sse / _responses_sse / _collect_anthropic`（`convert.go:15-17`）。请求侧转换实际落在 `handlers_openai.go`（`openaiToAnthropic` `handlers_openai.go:129-344`；`responsesToAnthropic` `:370-472`），响应侧落在 `convert.go`。

**SSE 解析器**：增量缓冲、处理跨 chunk 断帧、同时兼容 `\n\n` 与 `\r\n\r\n`、16MB 缓冲上限防 OOM（`convert.go:34-101`；Python 版 `gateway.py:1248-1273`）。

**流式 OpenAI 转换**（`streamOpenAI` `convert.go:406-555`）：

- `text_delta → {"content": text}`；`thinking_delta → {"reasoning_content": thinking}`（`convert.go:470-483`）
- `content_block_start(tool_use) → tool_calls[index]`，用 `toolIndices[srcIdx]→toolIdx` 做源块索引到工具序号的映射（`convert.go:441-463`）
- 首个增量前补发 `{"role":"assistant","content":""}`（`convert.go:448-451,471-474`）
- `input_json_delta → tool_calls[index].function.arguments` 增量（`convert.go:484-494`）
- 收尾发 `finish_reason` chunk + `data: [DONE]`；`stream_options.include_usage=true` 时追加 `choices:[]` + usage chunk（`convert.go:531-550`）

**流式 Responses 转换**（`streamResponses` `convert.go:559-838`）：完整事件序列 `response.created` → `output_item.added` → `content_part.added` → `output_text.delta` → `output_text.done` → `content_part.done` → `output_item.done` → `response.completed`，工具走 `function_call_arguments.delta/done`，`sequence_number` 全局单调递增（`convert.go:582-593`）。

**工具调用收尾**：`partial_json` 累加后 `content_block_stop` 时 `json.Unmarshal` 成 `input`（`convert.go:180-186,205-220,658-685`；Python `gateway.py:836-851`）。

**system prompt**：多条 system/developer 用 `"\n\n"` 拼成**单个** `system` 字符串（`gateway.py:540`、`handlers_openai.go:266`）。

**多模态**：只识别 `data:<mime>;base64,<payload>` 并转 Anthropic base64 image source；非 data-URI（远程 URL）**静默丢弃**，不报错（`gateway.py:502-511`、`handlers_openai.go:199-215`）。

**流内错误处理**：上游 `event: error`（overloaded_error / 风控中途拦截）不吞——记入 `usage.StreamError`（`convert.go:189-202`）；OpenAI 侧改发错误 chunk（`convert.go:513-529`），Responses 侧发 `response.failed`（`convert.go:800-818`）；非流式聚合时返回 502 而非伪装成功空响应（`convert.go:380-390`）。

**两个实测坑位**【一手】：
1. `api.z.ai` 通道把最终 `input_tokens` 放在 `message_delta`（`message_start` 为 0），故取 max 累积（`convert.go:137-142`）。
2. 2xx 但 `Content-Type` 非 JSON/SSE（WAF 挑战页/登录页 HTML）按上游错误处理，并冷却账号（`relay.go:329-336`）。

---

## ⑦ TLS 指纹（`tls_fingerprint.go`）

**为什么**：ZCode 桌面端是 Electron（Chromium），Go 默认 `crypto/tls` 的 ClientHello 指纹与浏览器差异明显，**易被上游 ESA WAF 识别为机器程序**（`tls_fingerprint.go:14-17`）。因此用 `github.com/refraction-networking/utls` 模拟浏览器指纹。

**怎么实现**【一手】：

- 默认模式 `chrome`（`tls_fingerprint.go:64`、`main.go:62-68`），预置模式表 20 项（`chrome/firefox/safari/edge/qq/360/ios/android/randomized/golang/...`，`tls_fingerprint.go:26-51`）。
- 预置模式映射到 utls 的 `ClientHelloID`（`presetHelloID`，`tls_fingerprint.go:82-112`）。
- 非浏览器运行时（bun/node/deno/curl/python/okhttp）没有官方 utls 预设，改用**内置 JA3 字符串**，自行解析成 `ClientHelloSpec`（`builtinJA3` `tls_fingerprint.go:53-61`；`ja3ToClientHelloSpec` `tls_fingerprint.go:154-216`）。
- 握手：对已建连的原始连接（直连 TCP，或经 SOCKS5 / HTTP CONNECT 隧道）执行 `utlsHandshake`；`mode=off` 时退回标准库（`tls_fingerprint.go:116-150`）。

**只对 `zcode.z.ai` 启用**【一手】：

- `ClientForURL` 按主机分流：URL 含 `zcode.z.ai` → utls 指纹客户端（**HTTP/1.1，显式禁 h2**，因为 ESA WAF 不支持 h2 ALPN）；其余（`api.z.ai`、`open.bigmodel.cn`）→ 标准库客户端 + `ForceAttemptHTTP2`（`client.go:324-342`、`client.go:270-292`、`client.go:308-313`）。
- 客户端按 `(proxy, fingerprintMode, ja3, timeout, isZcode)` 做键缓存复用连接池，设置变更时 `CloseIdleClients()` 失效（`client.go:326-351`）。
- 禁用重定向跟随（`http.ErrUseLastResponse`），把 WAF 挑战/登录页 302 交回 relay 显式分类（`client.go:283-286`、`relay.go:258-263`）。

---

## ⑧ 鉴权链

**对外（网关自己的 key）**：

| 项目 | 取值来源 | 比较方式 | 未配置行为 |
|---|---|---|---|
| zcode2api | `Authorization: Bearer` 或 `x-api-key`（`auth_admin.py:57-69`） | `hmac.compare_digest`（`auth_admin.py:68`） | **放行**（`auth_admin.py:62-64`） |
| zcode-proxy | `x-api-key` 或 `Authorization: Bearer`（`auth.go:277-283`） | `subtle.ConstantTimeCompare`（`auth.go:261`） | 401（`auth.go:284-298`） |

**对内（上游凭证）双通道**【一手】`agent.py:57-78`：

| 通道 | 凭证 | 目标端点 |
|---|---|---|
| Plan/JWT | `Authorization: Bearer <Coding Plan JWT>` | `zcode.z.ai/.../zcode-plan/anthropic/v1/messages` |
| API Key | `x-api-key: <api_key>` | `api.z.ai/api/anthropic/v1/messages` |
| BigModel | `x-api-key: <api_key>` | `open.bigmodel.cn/api/anthropic/v1/messages` |

- **JWT 判定不解析 claims**，只按"三段点分 + base64url 字符集"识别形状（`models.py:30-43`），据形状决定 `mode="jwt"|"apiKey"`（`models.py:74-85`）。
- **JWT 可换取 API Key**：`OAuth access_token → api.z.ai/api/auth/z/login 得 biz_token → getCustomerInfo 取 organizations/projects → GET/POST .../api_keys → GET .../api_keys/copy/{apiKey} 取 secretKey`，最终拼成 `"{apiKey}.{secretKey}"`（`oauth.py:220-276`）。OAuth 授权/兑换端点与公开 client_id 见 `oauth.py:31-35`。
- **三级降级链**：JWT+验证码 → JWT 不带验证参数直连 → API Key 回退端点（`gateway.py:1310-1367`；Go 版 `relay.go:151-224`，Go 额外把风控拦截 3012 作为一条独立分支，不立即冷却账号）。
- **状态判定**：401/403 → `invalid`；429 → `cooling`（Go 版还尊重 `Retry-After` 退避一次，`relay.go:288-303`）；402 或余额不足短语 → `exhausted`（`gateway.py:1434-1449`、`relay.go:444-458`）。
- **风控单独识别**：`code 3012` / `unusual activity` → 不当作普通错误（`relay.go:461-464`）。
- **人机校验**：验证码配置从 `GET zcode.z.ai/api/v1/client/configs` 拉 `data.configs.captcha{enabled,prefix,region,sceneId}`（`captcha.py:121-139`），用 Playwright 无头 Chrome 跑阿里云无痕 SDK 求解，缓存 TTL 45s、宽限期后台刷新（`captcha.py:142-195,217-263`）。数据中心 IP 会被风控 `F001` 拒绝，需住宅代理（`captcha.py:93-101`）。

---

## ⑨ 可复用点清单

| 机制 | 文件:行号 | 我们能不能用 |
|---|---|---|
| Anthropic 原生透传 + OpenAI/Responses 双向适配层 | `gateway.py:454-590,692-793`；`handlers_openai.go:129-472` | **能**。整套映射表可直接移植，是"上游是 Anthropic 风格"的通用解法 |
| OpenAI/Responses 路径内部强制 `stream:true` 再按需聚合（**Anthropic 原生路径保持客户端 stream 意图**） | `gateway.py:375,423`；`relay.go:232` | **能**。简化上游分支，非流式只需聚合器 |
| 增量 SSE 解析器（跨 chunk 断帧 + CRLF + 16MB 上限） | `convert.go:34-101`；`gateway.py:1248-1273` | **能**，直接抄 |
| `thinking_delta → reasoning_content` / Responses `reasoning` 项 | `gateway.py:713-714,760-765`；`convert.go:483` | **能**，对齐 DeepSeek 风格客户端 |
| 工具调用 `partial_json` 累积 → `input` 还原 | `convert.go:180-186,658-685` | **能** |
| 流内 `error` 事件不吞（→ 502 / `response.failed`） | `convert.go:189-202,513-529,800-818` | **能**，避免"假装成功" |
| 2xx 非 JSON/SSE 判为 WAF 页并冷却账号 | `relay.go:329-336` | **能** |
| `message_delta` 携带 input_tokens 的兼容取值 | `convert.go:137-142` | **能**，上游差异兜底 |
| utls TLS 指纹 + 按主机分流（指纹站禁 h2） | `tls_fingerprint.go:116-150`；`client.go:324-342` | **能**（Go）。Python 侧需 `curl_cffi`/`httpx` 替代方案【推断】 |
| 客户端连接池按 `(proxy,fp,ja3,timeout,host)` 缓存 | `client.go:326-351` | **能** |
| JWT 形状识别（不解析 claims） | `models.py:30-43` | **能** |
| JWT → API Key 兑换链 | `oauth.py:220-276` | **能**，但依赖 api.z.ai 私有接口稳定性 |
| 三级降级链 + 账号状态机（active/exhausted/cooling/invalid） | `gateway.py:1310-1367`；`pool.go:169-242` | **能** |
| 验证码自动求解（Playwright + 阿里云无痕） | `captcha.py:197-263`；`captcha.go:113-207` | **能用但重**：依赖真实 Chrome、需住宅代理、45s 缓存；纯 API Key 通道可绕过 |
| 模型目录同步 `client/configs` → `builtinModels` | `reset.go:250-303` | **能**，但需先解决 `version/os` vs `app_version/platform` 参数分歧 |
| `/v1/models` 同时输出 `object` + `type` 双字段 | `gateway.py:306-320`；`zcode_api.go:133-145` | **能**，一次满足两类 SDK 校验 |
| `count_tokens` 保守估计端点 | `zcode_api.go:99-115` | **能**，防 Anthropic SDK 报 405 |
| 白名单透传客户端 header（含 `x-stainless-*`） | `agent.py:15-47`；`relay.go:401-414` | **能**，安全且保留 SDK 元数据 |
| 无痕验证 `X-Aliyun-Captcha-Verify-Region` 头 | `relay.go:396-398` | **能**（Python 版缺这个头，是差异点） |

---

## ⑩ 未解决项

1. **`client/configs` 参数名分歧**：代码 `version`+`os`（`reset.go:251`、`captcha.py:128-130`）vs 文档 `app_version`+`platform`（`client-configs.md:32-34`）。未实测哪个必需、是否都接受。【未验证】
2. **JWT 通道的确切认证头**：文档称 `x-api-key: <JWT>`（`ai-protocol.md:41`），代码在 JWT 模式下发 `Authorization: Bearer`（`agent.py:64-66`）。是否为服务端同时接受两种、还是文档过时，未验证。【未验证】
3. **丢弃字段清单是反向推断**：`n/presence_penalty/frequency_penalty/logit_bias/seed/user/response_format/logprobs` 在 `gateway.py:454-590` 中无任何引用，但上游是否接受这些字段、是否有默认行为，未验证。【推断】
4. **远程图片 URL 的支持边界**：两项目都只处理 `data:` base64，远程 URL 静默丢弃。上游是否原生支持 `{type:"image",source:{type:"url"}}`，未验证。【未验证】
5. **`count_tokens` 的 token 估算法**（`chars/4+8`）与真实 tokenizer 的偏差量级未测，且仅 Go 版有。【未验证】
6. **风控 3012 的触发条件**（IP 段 / 频次 / 设备指纹）未定位；只知道 `unusual activity` 文案与 `"code":3012` 两个信号（`relay.go:461-464`）。【未验证】
7. **utls 指纹是否仍有效**：默认 `chrome` 预设会随 utls 版本老化，`main.go:70-74` 有"旧值回落 chrome"的迁移逻辑，说明指纹有效性需要长期维护；当前实际拦截率未知。【未验证】
8. **`/v1/models` 与上游实际可用模型的偏差**：两项目都用静态/半静态清单，未做"清单 ∩ 账号实际权益"的过滤，可能出现"列了但用不了"。【推断】
