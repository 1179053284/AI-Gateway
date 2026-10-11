# M6-R2 独立评审报告 · 模型转接链路（duck typing / 物化 / 分派 / 复用退役 / 错误语义 / 并发）

> 评审人：R2 独立评审（对抗式，**不改任何源码**）
> 评审对象：`docs/specs/tech-design.md` §22.3 / §22.5 / §22.8 与 M6-5 实现
> 评审方式：只读主树 + `/tmp` 复制品真跑（假上游全链）+ 变异实验（移除证明）
> 日期：2026-09-30

---

## 一、结论

**不通过。阻塞 2 项**（另记非阻塞发现 6 项；其中 F-4 / F-5 属"隐性阻塞"——用户会以为能用，交付话术必须先处理）。

| # | 阻塞项 | 落点 |
|---|---|---|
| B-1 | 配置里出现**未登记 product** → `_apply` 抛 KeyError → 热重载 watcher **静默死亡**（后续配置改动全部不再生效）且运行态**半应用** | `main.py:291-308` / `main.py:657-676` / `adapters/product_out.py:205-214` |
| B-2 | 产品资源 401 判死（`disabled` 终态）后，**重新登录该账号 / 停用→启用往返均不能复活**（轻量逃生口只剩改 base_url/api_key；否则要删资源重物化）→ 用户按提示"重新登录"也永远是 503 | `core/resources.py:37-48` + `core/resources.py:347-363`（对照 `main.py:331-353`） |

两阻塞均已在 `/tmp` 复制品里复现到最小（红证见 4.1 / 4.2），且都是「注释承诺了保护、实现只保护了一半」的对称性缺口：B-1 是 NotImplementedError 有护栏而 KeyError 没有；B-2 是适配器复用判据加了凭据指纹而运行态身份指纹没加。

**评审基准（已冻结）**：复制品 `diff -rq` 与主树 `model_gateway/` + `tests/` 在**评审结束时仍逐字节一致**（评审期内无代码漂移；期间主树有并行会话的测试活动，见 §八）；被评审文件 sha256 前 12 位见附录 A。全部运行在 `/tmp/m6r2-work` 复制品内，`data/` 零写入、`127.0.0.1:8300` 零触碰、无真实上游。

---

## 二、复跑与实验总览（全部在复制品内）

| 项 | 命令 / 方式 | 结果 |
|---|---|---|
| 基准测试 | `pytest tests/integration/test_{buddy,trae,zcode}_out.py tests/integration/test_materialize.py tests/unit/test_{product_out,schemas_product,v2_adapter_drain}.py --basetemp=/tmp/m6r2-tmp-a` | **79 passed** |
| 其余出站测试 | `pytest tests/integration/test_{qoder,qodercn,cline,lobsterai,loomy,raccoon}_out.py` | **45 passed** |
| 独立对抗式探针（自写，76 项断言） | `/tmp/m6r2-probe/e2e_probe.py`：账号→`ensure_resource` 物化→`build_adapter`→网关真起 uvicorn + 假上游真 TCP→流式/非流式/错误映射 | **75 PASS / 1 FAIL**（FAIL = 非阻塞 F-3） |
| 变异 A（复用判据抽掉 product+account_ref+指纹） | `main.py::_adapter_reuse_key` 改返回 `(base_url, protocol)` | 2 例转红（`test_rebinding_the_account_rebuilds_the_adapter` / `test_credential_change_rebuilds_the_adapter`）→ 护栏为真 |
| 变异 B（抽掉 `_retire_adapters` 调用） | `main.py::_apply` 删延迟排空 | **6 例转红**（drain 全 5 + 改绑 1）→ 护栏为真 |
| B-1 复现 | 好配置启动 → 写入 `product: ghostproduct` → 等 mtime 轮询 | watcher `done()=True` 且异常 = KeyError；再改回好配置 2s 后配置不再重载 |
| B-2 复现 | 假上游 401 → 重新登录同账号 / 停用启用往返 / 改 api_key | disabled 保持 → 503 / 503 / **active → 200** |
| UI 添加 Key 流 | `PUT /admin/api/config` 带 `product` 无 `account_ref` 的资源（复刻 `resources.js:507-518`） | **400**：`product='trae' 时 account_ref（产品账号名）必填` |
| 全量（复制品，`-x --ignore=tests/accounts`） | `pytest -q --basetemp=/tmp/m6r2-tmp-full` | 773 passed / 1 failed —— 唯一失败 `tests/unit/test_v2_servable.py::test_ops_lock_dir_ignores_cwd` 经查为**复制品环境伪影、非产品缺陷**（该用例 spawn 子进程断言"锁目录不随 cwd 漂移"，而 venv 的 editable 安装指向主树：`cwd=tmp_path` 的子进程 import 到主树包、`cwd=复制品` 的 import 到复制品包，两者报出各自仓库路径；在单一 checkout 的真实安装形态下该断言不涉及"两棵树"）。`-x` 使其后的用例未跑 |

三协议全链正向结论（探针明细）：buddy 路径 `/v2/chat/completions`、`Bearer` 账号令牌、配置 Key 不外发、SSE 帧序（role 首帧 → 内容 → `finish_reason` → **usage 帧** → `data: [DONE]` 收尾）、事件 `usage_source=vendor`；trae 路径 `/api/agent/v3/llm_utils_chat`、三重 token 头、强制 `stream:true` + `config_name`、SOLO 事件聚合、`token_usage`→usage 帧；zcode `/api/v1/zcode-plan/anthropic/v1/messages`、`Bearer JWT` + `anthropic-version` + 无 `x-api-key`、thinking/文本双通道、usage 映射 11/5。错误映射：401→`disabled`（三产品一致，AUTH 即断不重试）；trae 流内 1005→429、**首帧后失败不重放**（error 帧 + `[DONE]`，上游恰 1 次新请求）；zcode WAF 200+HTML→RETRYABLE→503；captcha 缝每请求现产（p-1/p-2 不复用）。

---

## 三、发现（阻塞 2）

### B-1【阻塞】未登记 `product` 打不死 `_apply`、却能打死热重载任务 —— 配置从此静默冻结

- **现象**：`config.yaml` 里任何一条资源写了一个未登记的产品名（如 `product: codercn` 打错字、老配置里写着已改名的产品）→ 热重载轮询任务抛 `KeyError` 死亡；此后**所有**配置改动不再生效，界面/日志都没有提示，`/health` 照常 200。
- **落点**：
  - `main.py:291-308`：`_apply` 只捕 `except NotImplementedError`（为"未接线 build_out"设的护栏），`build_product_adapter` 的未登记产品 `KeyError`（`account_ref` 为空的 `ValueError` 被 schema 校验器挡在前面，构不成同级风险）直接冒穿；
  - `adapters/product_out.py:205-214`：`registry_get(prod)` 显式"未登记当场 KeyError（不静默降级）"；
  - `main.py:393-401`：`reload_from_file` 只捕 `ConfigError`；`main.py:657-676`：`_reload_watcher` 循环内**无任何 try/except** → 异常直接终结该后台任务。
  - 讽刺对照：`main.py:301-305` 注释自己写着"不能让它冒出去：`_apply` 跑在 mtime 轮询任务里……配置从此不再生效，比"缺一个适配器"严重得多" —— 该论证对 KeyError 同样成立，护栏没覆盖到。
- **红证**（复制品实测）：
  ```
  改文件 2.5s 后 watcher.done() = True | cancelled = False
     watcher 退出异常: KeyError "未登记的产品 'ghostproduct'（在册：…）"
     runtime.config.resources = 1 | adapters = {}
  改回好配置 2s 后 runtime.config.resources = 1 （热重载已死）
  ```
  另测：启动期同配置直接 `KeyError` 冒穿 `create_app`（不是文档口径的"校验失败→退出码 2"的友好输出）。
- **附加事实（半应用）**：`_apply` 先写 `self.config` / `resources.rebuild` / `key_values` 等，再在资源循环里炸 → 运行态停在"配置已换、适配器还是旧的"的中间态（上例 `adapters={}` 而 `config.resources` 已含新资源）。
- **建议**：`_apply` 的资源循环把 `(KeyError, ValueError)` 与 `NotImplementedError` 并轨为"按资源降级 + warning"；`_reload_watcher`/`reload_from_file` 至少兜底记日志并保持任务存活（配置坏了一次不该赔上整个热重载）。修复后须补两条红证测试（幽灵产品 + watcher 存活）。

### B-2【阻塞】401 判死的产品资源无法通过"重新登录 / 重挂账号"复活 —— 终态与凭据身份脱钩

- **现象**：产品资源（凭据在账号目录）被上游 401 → 运行态 `disabled`（终态）。用户按错误提示"重新登录该账号"后：**适配器会重建**（凭据指纹进了 `_adapter_reuse_key`），但**运行态不清零**（`src_fp` 只含 protocol+base_url+api_key），资源永远不再进生效集 → 每个请求 503 NO_RESOURCE；「停用→启用」开关往返也不清终态；页面 Key 字段对产品资源无意义。轻量逃生口只剩手改 base_url 或（没人会想到的）api_key 来触发 `src_fp` 变化；否则要删掉资源、重新登录让物化生成新 id。
- **落点**：
  - `core/resources.py:37-48`（`_conn_fingerprint` = protocol + base_url + api_key）与 `core/resources.py:347-363`（只有 `src_fp` 变化才清零 `invalid/disabled/cooldown`）；  - 对照 `main.py:331-353`（`_adapter_reuse_key` **已**含 `product + account_ref + 凭据指纹`）——同一"连接身份"概念在两处判定分叉，正是 S-14 家族缺陷当年的形态；
  - 规格口径：§22.5-3 只点名"改绑账号必须重建适配器"（实现做到了），但"改绑/重登 = 新连接身份 → 运行态清零"（Q28-⑥③、S-2 修复的立意）在产品场景没有落地——产品资源的"Key"就是账号凭据，而它不在 `src_fp` 里。
- **红证**（复制品实测）：
  ```
  ① 401: HTTP 401, status=disabled
  ② 重新登录后: reload=True, adapter新建=True, status=disabled, HTTP 503
  ③ 停用/启用往返后: status=disabled, HTTP 503
  ④ 改 api_key 后: status=active, HTTP 200        ← 唯一逃生口是个不该有意义的字段
  ```
  另有"改绑到另一有效账号"版本：适配器 `account_ref=acc-B`，状态仍 `disabled`，调用 503，B 账号从未被打（上游请求数停在 1）。
- **影响**：正好命中"终端用户按提示操作却永远失败且无解释"这一类；也说明 M6-7 交付前"账号失效→改 Key/重登→恢复"的故事在产品资源上是断的。
- **建议**：`_conn_fingerprint` 对 `product` 非空资源追加 `account_ref + 凭据短哈希`（与 `_adapter_reuse_key` 同源），或在资源页给产品资源提供"重置运行态"入口；并补"401→重登→复活"的红证用例。

---

## 四、发现（非阻塞 6）

| # | 发现 | 落点 / 证据 | 建议 |
|---|---|---|---|
| F-3 | **captcha 缝的异常契约缺失**：`CAPTCHA_PROVIDER` 抛任何非 `UpstreamError` 异常（Playwright 超时是最可能的形态）→ 调度器捕获面只有 `UpstreamError/CancelledError` → 裸 **500 Internal Server Error**：无分类、无事件行、无冷却、无提示（实测 `status=500 body='Internal Server Error'`，零上游请求）。缝本身未接线（生产 `None`），属**潜伏缺口**，但接线波次一接就踩 | `upstream/zcode/out.py:120-129,133-142`；`core/scheduler.py:383/636` 的捕获面 | 约定"provider 异常 → `UpstreamError` 包装（可读文案 + 可重试语义）"，或让 `_mint_captcha` 兜底转换；补假 provider 抛错的红证用例 |
| F-4 | **zcode 流量路径的 3012 无护栏（D1 未裁决）**：`circuit.enter()` 全仓唯一调用点在 claim 路径（`ops/builtin/zcode_claim.py:121`）；转发路径遇 3012 只按 HTTP 状态分类，4xx（非 401/404/429/408）落 `BAD_REQUEST` → `scheduler.py:393-399/669-674` **原样透传、不计 C、不冷却**。而 DSH 实测该风控有账号惩罚梯度（30 分钟 / 24h 内 3 次→24h / **5 次停用**，`zcode-identity.ts:29-31`），且 `docs/research/24 §2-D1` 明确"直连是否成立"仍是最高待裁决点。用户重复重试可能烧号，且界面上 `/v1/models` 照常下发（`servable_models` 只看 enabled+运行态） | `docs/research/24-…md:89-97`；DSH `zcode-identity.ts:21-31`；`core/errors.py:117-127` | 交付话术不得写"zcode 模型转发可用"；接线/放行前先走 D1 最小实测；至少给 zcode 资源的 `/v1/models` 能力位或告警加"通道前提未验证"标注 |
| F-5 | **未接线的 qoder/qodercn 资源照常出现在 `/v1/models`**：签名缝 fail-closed（503 + 可读文案，已验证），但资源 `enabled+active` → `servable_models` 判定可服务 → 工具选到必然 503 的模型，正是 BUG-1 要消灭的"选了必失败"形态（当时的口径是"隐藏 + 横幅说明"）。**红证**：`GET /v1/models → ['qd-model']`，随后 `POST /v1/chat/completions` 恒 503（`"qoder 出站需要 WASM 加密与 COSY 签名…本资源当前不可用"`） | `qoder/out.py:66-70,110-116`；`core/resources.py:237-269`；`main.py:411-482`（config_warnings 无此类） | 给"已物化但出站未接线/前提未成立"的产品资源进 config_warnings 或在资源列表打标 |
| F-6 | `main.py:309 adapter.protocol = r.protocol` 是**死写 + 语义污染**：全仓无任何读者（grep 仅此一处写）；且把产品适配器自报的 `custom`/`anthropic` 覆写成 schema 字面量——trae 资源实测 `adapter.protocol == 'openai'`（探针记录）。注释"供复用判据/诊断"与实现不符（复用判据读的是 `r.protocol`） | `main.py:309,331-353`；`adapters/product_out.py:86-87` | 删掉该行或让它不覆写产品分支；注释同步 |
| F-7 | **资源页对产品资源仍渲染 Key 编辑/「添加 Key」**，而 `promoteKeyDraft` 不带 `account_ref` → 保存被 400 拒（实测 PUT 400）；同页「所属账号」输入写的是 `account`（展示字段）而非出站身份 `account_ref` → 界面显示的账号与实际用凭据的账号可分裂（唯一可用路径=手改 config） | `resources.js:263, 507-518, 431-433`；`api/admin.py` PUT 校验；`adapters/product_out.py:104` | 产品组隐藏 Key 编辑/添加；「所属账号」对产品资源应绑定 `account_ref`（或明确只读展示） |
| F-8 | `gateway.zcode.fingerprint=true` 而 curl_cffi 缺失时**只在日志告警**，未进 `config_warnings()`（总览横幅）——违背本仓自己的论据"告警写进日志=用户看不见"（`main.py:415-416`）。本机实测 curl_cffi **未安装** → 当前开启即静默降级为普通 httpx | `main.py:324-329` vs `main.py:411-482`；本机 `import curl_cffi` 失败 | 该告警进 warnings[] 横幅 |

**登记待办（实现方已知、非本轮判定）**：`accounts/materialize.py:20-25` 自认"跨进程（CLI 导入 + 服务端登录同时）可能丢更新，与管理端 PUT 同口径"。与 §22.8-4 的"跨进程 fail-closed 互斥"存在字面差（进程内锁），建议 M6-6 台账保留。

---

## 五、DSH 取证抽查（5 处，只读复核，基准 = `/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts` HEAD `a3fe5f2` = 上游 `f531c2984`）

| # | 被审代码的引用 | 实际文件:行（逐字） | 判定 |
|---|---|---|---|
| 1 | `qoder/out.py:10` "`qoder-wasm.ts:599-706` 的 `QoderEncryptedInfer`" / `:22-26` "WASM 导出函数" | `qoder-wasm.ts:599` = `export class QoderEncryptedInfer {`；`:23-26` = "WASM 同时导出了成对的编解码函数…我们直接调用它" | ✅ 真 |
| 2 | `trae/out.py:7,22` "`trae.ts:1534-1538`（stream:true）" 与 `trae.ts:44` | `trae.ts:44` = `export const TRAE_CHAT_PATH = '/api/agent/v3/llm_utils_chat'`；`trae.ts:1533-1538` = `transformToSOLOBody` 内 `stream: true` | ✅ 真（两处精确） |
| 3 | `trae/out.py:116` "`data:` 跨行拼接（`:1520`）" 与 `:16` "`channelFor`（`:656-661`）" | `trae-adapter.ts:1520` = `currentData += trimmed.slice(5) // SOLO data 可能会跨行拼接`；`trae-adapter.ts:658` = `private channelFor(model: string)` | ✅ 真（1520 精确；channelFor 在 658，窗口含声明） |
| 4 | `zcode/out.py:51` "验证码头（`zcode-upstream.ts:87-88`）"；测试引 `zcode-adapter.ts:494-495 / :563` | `zcode-upstream.ts:87-88` = 两个头名逐字；`zcode-adapter.ts:494-495` = "2. 产出一个新鲜 captcha（一次性！）/ `const captchaParam = await this.mintCaptcha()`"；`:563` = `region: this.options.captchaRegion ?? 'cn'` | ✅ 真（三处精确） |
| 5 | `buddy/out.py:11` "`buddy-adapter.ts:1583`（`/v2/chat/completions`）"；`registry.py:114-116` "`qoder-product.ts:445` `encryptedInferBase`"；`credits.ts:222-228` X-Domain 与 baseURL 一致 | `buddy-adapter.ts:1583` = `fetchImpl(`…`${this.product.endpoint}/v2/chat/completions``；`qoder-product.ts:445` = `encryptedInferBase: 'https://api2.qoder.sh',`；`credits.ts:226-228` = "X-Domain 必须与之一致" | ✅ 真 |

未发现"编造的 file:line"。（同批顺手复核：`zcode-identity.ts:1-30` 的 3012 准入矩阵与"5 次停用"惩罚警告为真，已用于 F-4。）

---

## 六、未能证伪（我试过但未能打破的）

1. **三协议流式字节契约**：SSE 帧序（role → 内容 → finish → usage → `[DONE]`）、中途失败 error 帧 + `[DONE]` 收尾、`model` 统一名替换、usage 帧透传/映射——76 项探针中除 F-3 外全绿。
2. **fail-closed 无静默降级**：buddy/trae/zcode 缺凭据 → 503 + 零上游请求；qoder 未注入签名器 → 503 可读文案 + 零上游请求（45 passed 含此例）；trae 空流 → 可重试失败不谎报空回复；zcode WAF HTML 200 → 不当作成功。
3. **复用/退役判据**：`product+account_ref+凭据指纹` 三个分量每抽掉一个都有测试转红（变异 A）；延迟排空（`_pending_close` → 宽限期后 `client.is_closed=True`）与 in-flight 不截断有 6 例红证（变异 B）；探针另证：换 base_url（真换端口）/重登/改绑 → 适配器均重建且旧 client 真被关闭。
4. **schema 契约**：`product==""` 且 `api_key` 空 → 拒；`product` 非空 `account_ref` 空 → 拒；产品资源空 Key 可载；手改保留残留 Key 不拒但不外发；`custom` 物化落 `openai` 字面量；`product` 分支优先于 `protocol`（trae 落 `TraeOut` 而非 OpenAI 适配器）；无 `product` 字段的老配置零改动加载（含仓库自带 `config.example.yaml`）。
5. **物化纪律**：幂等（二次调用零写盘）、registry `base_url` 落盘、账号删除=置 `enabled=false` 保留、坏配置拒写不覆盖。

## 七、未验证（无证据即不下结论）

1. 真实上游/真实凭据（buddy/trae/zcode 真机登录与转发）——§22.11 用户驱动；zcode 直连 405/3012 的 D1 前提未裁决（F-4 的"3012 落地为哪个 HTTP 状态"直接决定分类走向，我无法在无真实凭据下判定）。
2. qoder 真实签名器（WASM/COSY）：注入缝契约只被假签名器验证；生产 `SIGNER_FACTORY=None` 的 fail-closed 行为已验证。
3. TLS 指纹（curl_cffi）在真 WAF 下的效果：本机未安装 curl_cffi，只验证了"缺失→告警文案"路径（且该告警不进横幅，见 F-8）。
4. zcode system 身份块缺失的真实后果（3012 账号惩罚梯度）——只有 DSH 的实测矩阵转述，未在我方复现。
5. 前端「账号接入」页与 M6-4 管理端（本轮评审边界外；F-7 只覆盖「模型资源」页对产品资源的 Key 编辑行为）。
6. 运营侧 claim/quota 与本次转接链路的交叉（未在 R2 范围）。

## 八、评审纪律自我交代

- 主树零写入：唯一新增文件 = 本报告；`data/**` 未触碰（全部实验 `MG_CONFIG` 指向 `/tmp/m6r2-*`）；`127.0.0.1:8300` 未触碰；无真实上游调用。
- 全部真跑在 `/tmp/m6r2-work` 复制品（`rsync` 排除 `data/`/`.git`/`.venv`，事后 `diff -rq` 与主树逐字节一致）；变异实验改的是复制品，事后已还原并 `diff -q` 验证。
- 探针与复现脚本：`/tmp/m6r2-probe/e2e_probe.py`（76 项断言，含本节全部红证）；`--basetemp` 全部使用 `/tmp/m6r2-tmp-*` 独立目录。
- 已知边界（诚实披露）：主树存在**并行会话**的活动痕迹（部分源文件 mtime 02:11–02:37、主树 `.pytest_cache` 02:44 被更新，均非本次评审所写——本次全部 pytest 的 cache/basetemp 都在 `/tmp/m6r2-*`）。但这些改动**早于/不晚于我的复制时点**：评审结束时 `diff -rq /tmp/m6r2-work/{model_gateway,tests}` 与主树**仍逐字节一致**（无代码漂移），本报告 file:line 有效。若 M6-6 修复改动上述落点，须按附录 A 哈希重新定位。

## 附录 A · 被评审文件哈希（sha256 前 12 位，评审时点）

```
3eb69bf48747  model_gateway/main.py
72e147c3f3ed  model_gateway/adapters/product_out.py
8e438f202fb2  model_gateway/adapters/__init__.py
c3b7804a1661  model_gateway/adapters/openai_out.py
f91575833c10  model_gateway/adapters/anthropic_out.py
33116ea60029  model_gateway/accounts/materialize.py
70ffdff25f56  model_gateway/config/schemas.py
7f566bf6ef77  model_gateway/core/resources.py
9307e54decac  model_gateway/upstream/qoder/out.py
e0fa38742f24  model_gateway/upstream/trae/out.py
3a1e7697d9e2  model_gateway/upstream/zcode/out.py
```
