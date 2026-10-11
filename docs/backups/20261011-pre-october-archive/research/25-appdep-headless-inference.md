# 25 · 无头推理级实测（第二轮：隔离临时实例 + 多账号并行派发）

- 时间窗：2026-10-02 13:51—13:59（本地）；**全部实测在 `/tmp/mgw-headless-probe` 临时实例（127.0.0.1:8452）完成，未向现网 :8300 发任何 POST、未改任何源码/项目配置、未启停任何桌面 App**
- 归因口径：**(a) 网关侧未接线/自拦** ｜ **(b) 厂商拒绝**（请求真出去并拿到 4xx）｜ **(c) 成功**
- 上游真实调用量：临时实例 `/v1/chat/completions` 共 **19 次**（其中 1 次被网关自家拦下**未出网** ⇒ 真出网 18 次）+ 6 次目录 GET = **24 次**；现网 :8300 = 0 次
- 临时实例 Bearer = 自建随机 `mg-probe-<redacted>`（33 位，与现网密钥无关）；账号凭据一律不回显

## 1 · 搭台步骤（实际命令，可复跑）

```
umask 077 && mkdir -p /tmp/mgw-headless-probe/data/upstream && chmod 700 /tmp/mgw-headless-probe
cd /Users/w/Desktop/Model-Gateway/coding
for p in buddy workbuddy lobsterai trae loomy raccoon; do cp -R data/upstream/$p /tmp/mgw-headless-probe/data/upstream/; done
# 复制前后各做一次清单（path+size+mtime），57 条中仅 runtime.json 的 mtime 变（见 §6 归因），credentials.json/meta.json 逐条一致
```

配置由 pyyaml 生成（照现网 `coding/data/config.yaml` 逐条抄字段值，`api_key: ""`）：
`gateway.host=127.0.0.1 / port=8452 / access_tokens=[{id: probe, value: <redacted>}]`、
`scheduling.max_active_per_model=2`（其余沿用现网值）、
`resources[]` = 12 条（6 产品 × 2 账号：`t-<product>-1/2`，vendor/base_url/protocol=openai/access_mode=api/account_ref 与现网同值），
`models[]` = 13 条（每产品每账号 1 条 + `probe-buddy-dual` = **t-buddy-1 与 t-buddy-2 同池**）。
模型 ID 全部取自临时实例的**实时目录**（`GET /admin/api/accounts/<p>/catalog` → `source.kind=account`：buddy 16 / workbuddy 28 / lobsterai 30 / trae 38 / loomy 8 / raccoon 6），选用：
buddy+workbuddy=`hy3`、lobsterai=`MiniMax-M3.1-Flash-Preview`、trae=`DeepSeek-V4-Flash`、loomy=`GLM-5.3-Flash`、raccoon=`sn-sensenova-6-8-flash-lite`（负对照）。

```
cd /Users/w/Desktop/Model-Gateway/coding
MG_CONFIG=/tmp/mgw-headless-probe/data/config.yaml nohup .venv/bin/python -m model_gateway.main > /tmp/mgw-headless-probe/instance.log 2>&1 &
# 端口 1s 内就绪；单实例锁与 usage 落在 /tmp/mgw-headless-probe/data/（未触碰 coding/data/）
```

⚠️ **踩到的一条实现事实**（首轮 brief 的口径需要修正）：`core/paths.py:51` 令 **数据目录 = 配置文件的父目录**，
所以 config 必须放在 `.../data/` 里、账号放 `.../data/upstream/<p>/accounts/`。
按 brief 字面把 config 放 `/tmp/mgw-headless-probe/config.yaml` 时，实例解析到
`/tmp/mgw-headless-probe/upstream/...` ⇒ `/admin/api/accounts` 报 `accounts: 0`、六个 catalog 全部
`source.kind=fallback「内置兜底目录（无可用账号或远端目录不可用）」`（0.001—0.17s）。
把 config 移到 `data/config.yaml` 后同一批请求变成 `accounts: 12 / 全部 kind=account 实时目录`。

进程前置证据（`ps -Axo pid,etime,command` 去掉本探针 shell 自身；**每次调用前后各采一次，共 26 份快照**）：

```
CodeBuddy CN.app/Contents/MacOS      0    TRAE SOLO CN.app/Contents/MacOS  0    Trae CN.app/Contents/MacOS  0
WorkBuddy AI.app/Contents/MacOS      0    WorkBuddy.app/Contents/MacOS     0    Lobster 0  Loomy 0  Raccoon 0  xiaohuanxiong 0
Cursor/VS Code/Zed .app/Contents/MacOS 0
唯一残留（非本体，全窗口同一 pid 未变）：
  84628 02-04:26:08 /Applications/WorkBuddy AI.app/Contents/Resources/app.asar.unpacked/node_modules/@tencent/tencent-docs-ai-engine/bin/darwin-arm64/editor_sdk --port 39099 ...
⇒ 26 份快照的目标 App 本体进程计数**全部为 0**（ps-pre-*/ps-post-*.txt 逐份核对）
```

## 2 · 逐产品推理级结果（`POST /v1/chat/completions`，`max_tokens:8`，prompt=“reply with the single word OK”）

| 产品 | 非流式 | 流式 | 一句话结论 |
|---|---|---|---|
| buddy | **HTTP 400 / 0.115s** 厂商体 `{"error":{"code":11101,"msg":"Non-stream chat request is currently not supported",...,"zh":"请求内容不合法，请重试"}}` = **(b)** | **HTTP 200 / 1.746s**，SSE 首帧 `delta.content="OK"`、`finish_reason=stop`、usage 21/23 = **(c)** | 无 App 推理成立；厂商**不接受非流式** |
| workbuddy | **HTTP 400 / 0.515s** 同一 `11101` = **(b)** | 第 1 次 **HTTP 400 / 0.743s** `{"code":11128,"msg":"first message is not system prompt"}` = **(b)**；第 2 次（**首条改为 system**）**HTTP 200 / 1.946s**，8 条 `data:` 帧 + `[DONE]`，usage 24/8（reasoning 8，`finish_reason=length`）= **(c)** | 无 App 推理成立；额外要求**首条必须是 system 消息**（本轮唯一一次“再看 1 次”） |
| lobsterai | **HTTP 200 / 1.152s** `message.content="OK"`、`finish_reason=stop`、usage 210/2 = **(c)** | **HTTP 200 / 0.954s**，SSE 增量（`reasoning_content`）= **(c)** | 双形态全绿（本机未装 App） |
| trae | **HTTP 200 / 1.308s** `content="OK"` + reasoning_content、usage 10/77 = **(c)** | **HTTP 200 / 1.274s**，SSE 逐字增量 = **(c)** | 双形态全绿；**且设备头实际未下发仍 200**（见 §5-G） |
| loomy | **HTTP 200 / 1.236s** `content=""`、`reasoning_content="The user has asked me to reply with"`、`finish_reason=length`、`points_consumed:1` = **(c)** | **HTTP 200 / 1.061s**，SSE 增量 = **(c)** | 双形态全绿（本机未装 App） |
| raccoon（负对照） | **HTTP 401 / 0.237s**，网关体外层 `"code":"NO_RESOURCE"`，内含厂商体 `[401] {"code":200003,"message":"authorization_verify_error","details":"authorization verify failed"}`；`已尝试：t-raccoon-1/sn-sensenova-6-8-flash-lite×1` = **(b)** | 未发（负对照只跑一次，按 brief） | **预期红 = 真红**：过期凭据无法出网推理，与首轮 probe 401 一致 |

临时实例 `GET /v1/models`（Bearer）= 13 条全部在册（`probe-{buddy,workbuddy,lobsterai,trae,loomy,raccoon}-a1/a2` + `probe-buddy-dual`），0.002s → 入口存在，非 (a)。

⇒ **推理级定论：buddy / workbuddy / lobsterai / trae / loomy 五家在其桌面端确认 0 进程时全部拿到真实推理 200（含 SSE），首轮唯一的 (a) 缺口（资源未被任何系统模型引用）纯属映射未配，配上映射即可用。**

## 3 · 多账号并行推理判定（派发层，不再只是凭据层）

同池映射 = `probe-buddy-dual` → `t-buddy-1(buddy-00fdd61f)` + `t-buddy-2(buddy-a7f1c09f)`，`x=2`；两请求**同时**发起（`stream:true`）：

```
A: HTTP=200 time=0.789s   B: HTTP=200 time=1.747s
GET /admin/api/logs/requests →
  13:57:01.001 req_ae196cfdb52b probe-buddy-dual success final=t-buddy-2/hy3  acct=buddy-a7f1c09f dur=788  ttft=667
  13:57:01.959 req_074c42d2db5a probe-buddy-dual success final=t-buddy-1/hy3  acct=buddy-00fdd61f dur=1745 ttft=1643
```

**判定：网关派发层并行成立** —— 两条并发在途请求被分到**不同资源 / 不同账号**，双双 200，无 429、无切换（`switch_count=0`）。

同账号 2 并发（`probe-buddy-a1`，池内仅 `t-buddy-1`，并发期间每 0.1s 采 `/admin/api/overview`）：

```
sameA HTTP=200 1.818s ／ sameB HTTP=200 1.793s        （两条同时返回）
13:57:32.132 req_7f80fe5dc0d6 final=t-buddy-1/hy3 acct=buddy-00fdd61f dur=1791
13:57:32.158 req_2a6d260182a7 final=t-buddy-1/hy3 acct=buddy-00fdd61f dur=1816
ov-8/10/12/14（均在途期间）: in_flight_requests=2 | t-buddy-1 {available:true, status:active, in_flight=2} | t-buddy-2 in_flight=0
ov-16（返回后）: in_flight_requests=0
```

**判定：同账号 2 并发不互斥、不 429、凭据/会话未失效**（`in_flight=2` 实测压在同一个资源上且双双 200）。
⇒ 单账号也能并发；多账号并行的收益是**额度/风控分摊**，不是“并发能力上限”。

## 4 · 撤证（三条，全红）

1. **RED-1（开关真生效）**：临时 config 里 `t-lobsterai-1.enabled: false` → 重启实例（pid 14330→17451）后
   `GET /v1/models` 从 13 → **11 条**且 `probe-lobsterai-a1` **消失**；overview 横幅
   `model_unservable「2 个已启用模型的资源映射全部不可用…（probe-buddy-a2、probe-lobsterai-a1）」`；
   调用变红且**未出网**：`HTTP=503 time=0.006332s`
   体＝`{"error":{"message":"无可用资源；原因：无可用资源","type":"gateway_error","code":"NO_RESOURCE","system_model":"probe-lobsterai-a1"}}`
   ⇒ §2 的绿不是缓存/假象，判据可红。
2. **RED-2（并行归因可红）**：再把 `t-buddy-2.enabled: false`，同池只剩 t-buddy-1，重发同一对并发
   `A: HTTP=200 1.617s / B: HTTP=200 2.019s` → 日志两条 `final=t-buddy-1/hy3 acct=buddy-00fdd61f`（**同账号**）
   ⇒ §3 的“两个不同账号”确实由选路产生（不是两条并发天然就分开的假象），去掉一条资源后立刻塌成同账号。
3. **RED-3（负对照天然红）**：raccoon 过期号 → `HTTP 401 / 0.237s` 厂商 `authorization_verify_error`（§2 表末行）。

## 5 · 顺带发现（主动报告，本轮**一律未修改任何代码**）

- **G-a｜buddy/workbuddy 系厂商拒非流式**：`code 11101 "Non-stream chat request is currently not supported"`；workbuddy 还要 `11128 first message is not system prompt`。网关是**原样透传** `stream:false`（厂商自有错误体即证据）。影响：CLI/工具端用 `stream:false` 打这两家必 400。建议（需用户裁决，未动）：在 buddy 族 `prepare_body` 或 IR 层对 `stream=false` 做「强制流式 + 聚合」/首条补 system 的塑形（属行为变更，不在探针权限内）。
- **G-b｜401 被包成 `NO_RESOURCE`**：raccoon 的厂商 401 在网关侧变成 `"code":"NO_RESOURCE"`＋「原因：无可用资源」，与首轮 F-C 同一坏味道（真因是凭据失效，不是没资源）。归因不诚实，建议保留上游语义。
- **G-c｜`in_flight_requests` 与 `resources[].in_flight` 都在 overview 里可用**（本轮据此取证，无缺陷）；但 `/admin/api/logs/requests` 的 `rows`（不是 `items`）与 `account` 字段命名需按此读取，首轮 brief 里 `in_flight` 的猜测键名不成立。
- **G-d｜trae 设备头缺口不影响推理**（首轮 brief 列的已知缺口①被实测证伪其影响）：`upstream/trae/protocol.py:245-250` 只从**凭据本体**取 `machine_id/login_device_id/device_id`，而导入号的这两个字段只落在 `meta.json`（实测 `credentials.json` 键集 = `access_token/enterprise_id/expires_at/nickname/phone/refresh_token/uid`，无设备字段）⇒ `X-Machine-Id`/`X-Device-Id` 确实没下发，**但非流式与流式都 200**。结论：Trae 推理面当前不要求设备头（至少这批账号/此刻）；是否长期如此未验证。

## 6 · 现网未被改动的核对

- `coding/data/config.yaml`：mtime **13:45:30 2026 / 14487 B**，与开工前逐字相同（本轮全程只读，未做任何写操作）。
- `coding/data/upstream/*/credentials.json`、`meta.json`：清单（path+size+mtime）**逐条一致**，未被重写。
- ⚠️ 如实记录：`coding/data/upstream/*/runtime.json` 的 **mtime** 在本轮窗口内被刷了两批（13:54:33—13:54:52、13:59:11—13:59:25，覆盖 cline/qoder/qodercn 等我**从未调用过**的产品）。字段级比对：项目文件与我在 13:51 的临时副本**只差 `quota.checked_at` 时间戳**（项目 = 13:59:11，副本 = 13:59:37 被我的实例同样地刷新过）⇒ 写入者是**现网 :8300（pid 38665）自身的周期性额度刷新**，与本探针无关；我的实例只写 `/tmp/mgw-headless-probe/data/`。size 全部未变。
- 现网 :8300 未收到我的任何请求（本轮 0 次 GET/POST）；`ps` 显示 Qoder CN / ZCode / zcode-switch / ZCode Panel 全程未被我触碰。

## 7 · 未验证项

| 未验证 | 原因 | 定论所需实验 |
|---|---|---|
| qoder / qodercn / zcode 的推理级 | `SIGNER_FACTORY=None`、`CAPTCHA_PROVIDER=None`（`main.py:239` 判据），配了映射也进不去；且这三家 App 正在运行，不构成无 App 对照 | 首轮已定性的两项前置（签名移植 / D1 裁决）＋用户批准临时退出相关 App |
| cline 之外产品的**非流式**通路 | 厂商直接拒（11101） | 见 G-a 的塑形决策（用户裁决后实现 + 复跑本表） |
| workbuddy / 其余产品在**长 prompt / 大 max_tokens** 下的表现 | 本轮 `max_tokens=8`，两条绿请求被 reasoning 吃掉（`finish_reason=length`、content 为空） | 需真实任务级采样，属另一轮 |
| 多账号池 >2（x>2）与失败切换（y） | 临时实例只造了 2 条同池 | 需要时把 `max_active_per_model` 调到 3 并配 3 账号 |
| raccoon 恢复后可用性 | 凭据终态过期 | 用户重新登录后复跑 §2 |
| 并行分派的**稳定性**（是否总按 in_flight 均分） | 本轮 n=2；RED-2 只证明“资源少时会塌”。未测 3+ 并发下是否出现倾斜 | 3—5 并发采 10 组以上再定分布结论 |

## 8 · 收尾

- 临时实例 pid 17451 已 `kill`（`lsof -nP -iTCP:8452` 空），`/tmp/mgw-headless-probe`（含账号副本、日志、响应体、token）已 `rm -rf`；
- 源码/配置零改动：本轮只读取源码（`core/paths.py`、`config/schemas.py`、`adapters/product_out.py`、`upstream/{buddy,trae}/protocol.py`、`api/admin_accounts.py`）；
  期间树上有**并行会话在飞**（收尾时 `git status --porcelain` 计数 M=39 / ??=6；`main.py` md5 开工采样 `1afafd0f…`），我未代改。
