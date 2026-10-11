# M6 交付面板 · eng-b 独立验证报告（转接链路 + 安全 + 运行形态）

> 角色：M6-7 面板 **eng-b**（独立评审，**非实现方**；对抗式）
> 评审对象：`docs/specs/tech-design.md` §22.3 / §22.5 / §22.7 与 M6-6 修复轮（`_nudge_reload` /
> `unservable_reason` / `admin_write_origin_guard` / `_conn_fingerprint` 扩面 / `_mint_captcha` 包装）
> 方式：`/tmp` 复制品真跑（假上游 + 真 uvicorn 子进程）+ 变异「撤修复红证」+ 静态对表
> 纪律：主树零改动（**唯一写入 = 本报告**）；`data/` 零写入；`:8300` 零触碰；真实上游零调用；
> `--basetemp=/tmp/m6eb-*` + `-p no:cacheprovider`
> 日期：2026-09-30

---

## 一、结论

> ### **通过 · 阻塞 0**
>
> 上一轮两阻塞（`m6-r2-traffic.md` B-1/B-2）与 R3-P-4（CSRF）**均已独立复现为绿**，且各自有
> 我自己的「撤修复红证」（§四）。四条端到端链路（物化→真 uvicorn→流式/非流式/错误映射；
> 跨进程重登复活；未注入前提排除；坏配置下热重载不死）全部按契约成立。
>
> **登记 5 条非阻塞**（3 中 / 2 低，全部附最小复现；F1/F2 属"BUG-1 家族未收干净"，交付话术不得
> 宣称"选了必失败的模型已全面消除"）：

| # | 级别 | 一句话 | 落点 |
|---|---|---|---|
| F1 | 中 | **出站适配器"构造失败"**的资源对应模型仍进 `/v1/models`（选了必 503）；**空 `base_url`** 的资源是**零横幅静默跳过**，调用文案还误导（"protocol 未实现"） | `main.py:341-373`（silent `continue` 在 `:345-346`）、`core/resources.py:273-316`、`core/scheduler.py:211-215` |
| F2 | 中 | `_apply` **前置步骤**失败（`load_enum_pool` 读坏 `model-enums.yaml`）→ **半应用**运行态（config/registry 已换新、adapters/key_values 仍旧）+ **零横幅**，且要用户再动一次配置才自愈 —— B-1 的护栏只覆盖了资源循环 | `main.py:312-317`、`main.py:823-853` |
| F3 | 中 | 上游错误体**回显凭据**时，明文进**事件 JSONL**（§22.2 不变式②被打破）与客户端响应体；边界缺脱敏 | `stats/events.py:28-35`（`error_summary` 取 `error_body[:160]` 原样入事件） |
| F4 | 低 | `/admin/api/accounts/import` 对非法账号名**清洗式改名**而非拒绝（`../evil` → 账号 `evil`）；与另外三条写路径（commit_login / materialize / 管理端路径参数）的"拒绝"口径不一致 | `accounts/store.py:624`、`api/admin_accounts.py:491-497` |
| F5 | 低 | 物化不写资源 `name` → 事件/统计/错误文案以 `res-xxxxxxxx` 指认资源（可读性；UI 有 vendor/account 列兜底） | `accounts/materialize.py:102-112`、`core/resources.py:420-424` |

**放行意见**：M6-7 可交付。F1/F2 建议进下一轮修复（两者的处置动作同源：把"出站前提/构造失败"
的判据并入 `servable_models`，并给"本轮重载失败"一个横幅出口）；**F3 建议在交付话术里显式声明
边界**（凭据不落盘的成立前提 = 上游错误体不回显凭据），并加一个 5 行的 `error_summary` 脱敏。

**探针总账：10 个脚本 / 134 项断言全绿**（含 4 项撤修复红证 + 4 项"观察"项；
`/tmp/m6eb/logs/probe-*.log` 全部留档，`sh /tmp/m6eb/probe/run_all.sh` 可一键复跑）。

---

## 二、评审基准与环境（可复跑）

| 项 | 事实 |
|---|---|
| 复制品 | `/tmp/m6eb/work`（`rsync -a` 自主树，排除 `data/`、`.git/`、`.venv/`、`__pycache__/`、`.pytest_cache/`） |
| 网关（真 uvicorn 子进程） | `python -m model_gateway.main`，端口 **8390 / 8391 / 8392 / 8393 / 8395**（每次 `MG_CONFIG=/tmp/m6eb/rt*/config.yaml`） |
| 假上游 | `/tmp/m6eb/probe/fake_upstream.py`（uvicorn，:8394；可切 200/401/500、SSE 中途断、回显 Authorization） |
| 探针 | `/tmp/m6eb/probe/run{1..9}*.py`（脚本 + 输出留档 `/tmp/m6eb/logs/probe-*.log`；一键复跑 `sh /tmp/m6eb/probe/run_all.sh`） |
| pytest | `cd /tmp/m6eb/work && .venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=/tmp/m6eb-pytest-eb* [路径]` |
| 冻结核证 | 7 个被审文件 sha256 前 12 位**评审开始 = 评审结束**（附录 A）；`diff -rq`（copy vs 主树）`model_gateway/`+`tests/` **逐字节一致**（运行期出现的 `_wiring_canary_pkg_<pid>` 是 pytest 用例自己的自播种夹具，随进程退出清理；我另以"变异后逐文件还原 + sha256 比对"保证复制品干净）→ 本报告 `file:line` 有效 |
| 主树写入 | 仅本文件。`:8300`、`data/**`、真实上游：零触碰（全部 `MG_CONFIG` 指向 `/tmp/m6eb/rt*`，日志核对无真实域名调用） |

**pytest 独立复跑（复制品）**：

- 非 accounts：**924 passed / 1 failed**（341s）——唯一失败
  `tests/unit/test_v2_servable.py::test_ops_lock_dir_ignores_cwd`，**是复制品环境伪影、非产品缺陷**：
  断言输出逐字给出两棵仓库路径
  ```
  AssertionError: 锁目录随 cwd 漂移：/private/tmp/m6eb/work/data/ops-locks
                      != /Users/w/Desktop/Model-Gateway/data/ops-locks
  ```
  该用例以 `env={"PATH","HOME"}` 起子进程（无 `PYTHONPATH`/`MG_CONFIG`）→ 走 venv 的 editable
  `.pth`（内容 = 主树绝对路径）；`cwd=复制品` 时 `-c` 的 `sys.path[0]` 指向复制品 → 两棵树各自
  报出自己的仓库根。单 checkout 安装形态下两个 cwd 解析同一棵树，不过该断言无涉"两棵树"。
- `tests/accounts`：**497 passed**（1.1s）。
- 合计 **1422 收集 / 1421 passed**，与台账终态"1422"一致（README 写 1421 ≤ 实际，在护栏容差内）。

---

## 三、端到端四跑（命令 + 观察）

### ① 全链：账号 → `ensure_resource` 物化 → 出站分派 → **真 uvicorn** → 流式/非流式/错误映射

`/Users/w/Desktop/Model-Gateway/.venv/bin/python /tmp/m6eb/probe/run1_e2e.py` → **33/33 PASS**（`/tmp/m6eb/logs/probe-run1_e2e.log`）
（下表中「上游 500」「流中途失败」两行出自 `run8_errors.py` → **9/9**，`/tmp/m6eb/logs/probe-run8_errors.log`）

| 观察 | 实测值 |
|---|---|
| 物化（生产写路径 `commit_login` → `_materialize_best_effort`） | `{"id":"res-64b0ca5a","vendor":"CodeBuddy","protocol":"openai","base_url":"https://copilot.tencent.com","api_key":"","account":"acc-1","product":"buddy","account_ref":"acc-1","enabled":true}`——base_url = 注册表取证值、Key 为空（凭据不进配置） |
| `ensure_resource` 幂等 | 二次调用内容**零变更**（仅前推 mtime） |
| 非流式 | 200，内容/统一模型名正确；假上游收到路径 `/v2/chat/completions`（取证值）、`Authorization: Bearer TOKEN-ACCOUNT-A-9f3c7b21`（账号目录令牌）、配置里的哨兵 Key **未外发**、`model=hy3`（映射厂商名）、`X-Product: CodeBuddy`（F3 修正值） |
| 流式 SSE 帧序 | `['role','content','content','finish','usage']` + `data: [DONE]` 收尾；usage 帧透传 `prompt=7/completion=3`；模型名统一为 `cb-model` |
| 事件落盘 | `status=success / usage_source=vendor / input=7 output=3`，`final_resource=res-…/hy3` |
| 401 判死 | 响应 401 如实透传（AUTH 不重试）；运行态 `disabled` + `last_error=[401] …`；模型从 `/v1/models` 消失；再调 503 `NO_RESOURCE`（可读） |
| 上游 500（单资源） | 非 200 可读；**y=2 后资源进 `cooldown`**（`cooldown_remaining_ms≈59988`，上游恰 2 次调用）；重启后运行态复位 `active` |
| 流中途失败（首帧后） | HTTP 已提交 200 → `{"error":{"message":"mid-stream break","retryable":true}}` 帧 + `[DONE]`；**上游恰 1 次调用（不重放）**；事件 `status=failed`；C=1 < y=2 → 无粘滞冷却，恢复后 200 |
| 上游不可达 | 503 + `[network] ConnectError …` 可读（不裸 500） |

### ② 重登复活链（B-2 残差，**跨进程**形态）

同一实例内：401 判死（`disabled` 终态）→ 另一个进程（`commit_login` = 登录引擎的落盘入口）写入新
令牌并触发 `_nudge_reload`（只前推 mtime）→ 既有 1s 热重载重算运行态：

```
7.2  {"status":"disabled", "last_error":"[401] …"}          ← 判死
8.1  跨进程 commit_login 退出码 0
8.2  重登后模型回到 /v1/models：['cb-model']                 ← 无任何额外操作
8.3  {"status":"active","C":0,"last_error":null}             ← 终态清零
8.4  复活后 200 且出站头 = Bearer TOKEN-ACCOUNT-B-51d0e8aa   ← 新令牌生效
```

补充：手动**停用**的资源（`enabled=false`）在重登后**保持停用**（幂等命中不改内容）——"用户的
决定不被拨回"这条纪律成立（`materialize.py:118-142` 实测）。

### ③ 未注入前提排除（F-5 / F-4）

`run2_premise.py` → **11/11 PASS**（`/tmp/m6eb/logs/probe-run2_premise.log`）
（qoder 签名器 `None`、zcode 验证码 `CAPTCHA_PROVIDER=None`，均走生产默认）

- `/v1/models` = `['bb-model']` —— `qd-model` / `zc-model` **不下发**；
- 横幅（`/admin/api/overview.warnings`）：
  `2 个模型因出站前提未注入不可服务（qoder 签名未注入（WASM/COSY）、zcode 验证码未注入），已从 /v1/models 与 mgw setup 隐藏 —— 选到它们必然失败（503）；请在「模型资源」页暂时停用对应资源，或等待出站通道接线（qd-model、zc-model）；注意：zcode 直连前提未验证（D1），当前不代表 zcode 转发可用`
  —— 点名、成因、去向、D1 诚实标注四要素齐全；与「③ 资源不可用」**分开计数**（无 `model_unservable`）；
- 旁证：zcode 资源本身 `enabled=true / 运行态 active`（只是不被声明）→ 排除是**判据驱动**而非拉黑；
- 现场证据：`qd-model` 直调 503，文案含 `WASM` / `SIGNER_FACTORY`（可读、不伪装成上游错误）。

### ④ 热重载健壮性（B-1 不回潮）+ 两个同族探针

`run3_reload.py` → **10/10**（`/tmp/m6eb/logs/probe-run3_reload.log`）

- 人为写入未登记 `product: ghostproduct` 的资源 → 该资源**按资源降级**（无适配器），横幅
  `resource_adapter_unbuilt` 点名（`KeyError: "未登记的产品 'ghostproduct'（在册：…）"`）；
- 好资源不受牵连（`m-good` 仍 200）；
- **第二次配置改动仍生效**（`m-good2` 出现并可调用，用的是新账号令牌）→ watcher 未死；
- 同族探针（见 F1）：`m-ghost` / `m-nourl`（空 `base_url`）**都进了 `/v1/models`**，调用 503
  `资源 '…' 无可用出站适配器（protocol 未实现）`；空 `base_url` 那条**连横幅都没有**。

---

## 四、撤修复红证（我对修复轮的独立变异实验，全部在复制品内，事后逐字节还原）

`run9_mutations.py`（A/B/D + 还原）与 `run9c_watcher.py`（B-1 两层护栏分层）：
A/B/D **4/4 红证成立**，C 分层 **5/5**（`/tmp/m6eb/logs/probe-run9*.log`）。

| # | 变异 | 预期红态 | 实测 |
|---|---|---|---|
| A | `materialize._nudge_reload(path)` → `pass` | 重登不复活 | **红**：`dead(disabled)`（模型不回清单） |
| B | `Runtime._resource_credential_fp` 恒返回 `""` | 有 nudge 也不复活（指纹不刷新） | **红**：`dead(disabled)` |
| D | `admin_write_origin_guard` 顶部 `return` | 跨源写请求被执行 | **红**：`rc=200, enabled=False`（账号真被停用） |
| C1 | 只撤 `_reload_watcher` 兜底 `except` | —— | **不红**：内层按资源降级接住（`m-2nd=yes`）→ 内层是主护栏 |
| C2 | 只撤 `_apply` 内层降级 | —— | 外层兜底接住：watcher 活着、改动仍生效；但**只有日志、零横幅**（C2b） |
| C3 | 两层都撤（复刻 B-1 原缺陷） | watcher 死亡、第二次改动不生效 | **红**：`m-2nd=NO`（`m-ghost` 仍被声明 = 半应用同族症状） |
| E | 还原核证 | —— | 三文件 sha256 与备份一致（`e3d10e7dd9e1` / `e7080f99bd65` / `5c2e8d18eb63`） |

结论：`_nudge_reload`、运行态指纹的凭据分量、来源校验三处修复**都是承重的**；B-1 由**内层降级
（主）+ watcher 兜底（副）**两层共同成立。

---

## 五、安全面

`run4_security.py` → **31/31 PASS**（`/tmp/m6eb/logs/probe-run4_security.log`；实例 :8395 + rt4）

### 5.1 CSRF 来源校验（`admin_write_origin_guard`，`api/admin.py:99-134`）

| 请求形态 | 端点 | 实测 |
|---|---|---|
| **无 Origin**（curl / CLI / 本机脚本） | `POST …/disable`、`…/enable` | **200 放行**（A1/A2） |
| **同源** `Origin: http://127.0.0.1:8395` | `POST …/disable` | 200（A3） |
| **同族回环** `Origin: http://localhost:8395` | `POST …/enable` | 200（A4） |
| **跨源** `Origin: http://evil.example:8395` | `POST …/disable` | **403** + 可读文案（`Origin '…' 与 Host '…' 不同源`）（A5） |
| **异端口同主机** `Origin: http://127.0.0.1:8396` | `POST …/disable` | **403**（A6） |
| `Sec-Fetch-Site: cross-site`（无 Origin） | `POST …/disable` | **403**（A7） |
| 跨源 | `POST …/delete?confirm=1` | 403 + 账号目录仍在（A9/A10） |
| 跨源 | `PUT /admin/api/config` | 403 + 配置文件**逐字节不变**（A11/A12） |
| 跨源 | `GET /admin/api/overview` | 200（只覆盖写方法，读不受影响）（A13） |
| 三次 403 之后 | 账号 `enabled` 仍 `true` | 零副作用（A8） |

范围核证：`system/stop|restart` 与 `config`、`accounts*` 同一 `APIRouter(dependencies=[…guard])`
（`api/admin.py:134,139,762,778`）→ 同一护栏覆盖全部管理端写方法。

### 5.2 凭据不回传 / 不落盘（13 个响应体 + 日志 + 结果文件）

扫描客体 = 账号令牌 `SECRET-SEC-EB-4c19d7a0`（真在链路里：对照 C.4 出站头 = `Bearer <它>`）。

| 面 | 结果 |
|---|---|
| 13 个响应体（health / models / overview / accounts / capabilities / presets / config-脱敏 / stats / logs / switches + 3 个错误体 404/400×2） | **零命中**（C.1；配置哨兵 Key 同样零命中 C.2） |
| accounts 视图键集合 | 无 `access_token` / `credentials` / `zcodejwttoken`（C.3） |
| 常规 401 后的**新增**事件行 / 网关日志 / `ops-results-*.jsonl` | **零命中**（D.2 / D.6） |
| 对抗式：假上游把 `Authorization` 回显进错误体 | 响应体 **有**（in_response=True）/ 事件 JSONL **有**（in_events=True）/ 日志 **无**（in_log=False）/ ops-results 无 → **F3** |

### 5.3 账号名穿越（6 形态 + import）

`..%2F..%2Fetc`→405、`%2E%2E`→400、`..`→405、`a b`→400、`中文`→400、33 字符→400；
`import` 未登记产品→400（先拒后写）；`import` 载荷名 `../evil` → 200 且落库为 `evil`（**F4**，
无越界目录，响应明示落库名）。

---

## 六、schema / 配置兼容

`run5_schema.py` → **11/11 PASS**（`/tmp/m6eb/logs/probe-run5_schema.log`）

| 契约 | 实测 |
|---|---|
| `product==""` 且 `api_key` 空 → 拒 | 文案 `api_key 不能为空（product 为空 = 按量 API 资源，必须配 Key；…§22.5-2）` |
| `product==""` + `api_key` 非空 → 收 | 旧配置零改动（S2） |
| `product` 非空 + `account_ref` 空 → 拒 | `product='buddy' 时 account_ref（产品账号名）必填…`（S3；`build_adapter` 层同样的可读 `ValueError` S11） |
| `product` 非空 + 空 Key → 收 | 凭据在账号目录（S4） |
| 旧配置整体加载 | 手工 v1 配置 + 随仓 `config.example.yaml` 均可加载（S5/S6） |
| `custom → Resource.protocol` 落值 | 端到端物化实测 = `"openai"`（run2 3.3），注册表自定义协议族不落配置字面量 |
| **分派以 `product` 优先** | `protocol="anthropic"` + `product="qoder"` → `QoderOut`（自报 `protocol="custom"`）；`protocol="openai"` + `product="zcode"` → `ZcodeOut`（自报 `"anthropic"`）；无 `product` 才走 protocol 分支（S7/S8/S9，F-6 不回潮） |
| 未登记 product | 可读 `KeyError`（在册清单齐全）（S10） |

---

## 七、CLI 契约（`mgw zcode claim`，Q28-⑥⑧）

`run6_cli.py` → **12/12 PASS**（`/tmp/m6eb/logs/probe-run6_cli.log`）

| # | 项 | 实测 |
|---|---|---|
| CLI.1 | `claim --help` epilog | `0 = 全部正常；1 = 有失败（需关注）；2 = 无账号参与；3 = **全局风控熔断中，本轮未对上游发起领取**…⚠️ 3 与 `mgw setup` 的 3（写盘失败）同码不同义` |
| CLI.2/3 | `zcode --help` / `--version` | 子命令清单完整；`mgw 0.2.0` |
| CLI.4 | 无账号 | **退出码 2** + `无账号参与 —— 尚未接入任何 ZCode 账号`（不报 success） |
| CLI.6 | 有账号但凭据缺失（零网络） | **退出码 1** + `✗ 失败 1 个` + `凭据缺失（先 mgw zcode login…）` |
| CLI.8 | 开局熔断（真 `circuit.json`，走生产 `CooldownManager.enter`） | **退出码 3**（**优先于 1**：同屏仍列 `凭据缺失` 失败）+ `本轮未对上游发起任何领取` + 状态文件绝对路径 + 手动出口说明 |
| CLI.9 | in-process 假执行体 | 全成功 → **0**；业务失败 → **1** |
| CLI.10 | 熔断 + 执行体全成功 | **3**（空跑不得报 0） |
| CLI.11 | README 双语 | claim 退出码 0/1/2/3 与"按子命令读"提醒均在（`README.md:117-121` / `README.zh-CN.md:113-116`） |

未实测项：**真实网络下的 `0`（全成功）** —— 按 §22.11 需真实凭据/住宅代理，本报告用 in-process
假执行体验证"退出码映射"这一段，**不宣称真机领取通过**。

---

## 八、反例 / 风险（含"我没能证伪但风险在这"）

### F1【中】"选了必失败"家族未收干净：适配器构造失败**仍进 `/v1/models`**；空 `base_url` 是**零横幅静默跳过**

- **红证 A（未登记 product）**：`ids=['m-good','m-ghost']`（`m-ghost` 被声明）；调用 →
  `503 {"message":"资源 '幽灵资源' 无可用出站适配器（protocol 未实现）"}`；横幅只有
  `resource_adapter_unbuilt`（点名幽灵资源）。
- **红证 B（空 base_url）**：`res-nourl.base_url=""` + 模型 `m-nourl` → **`m-nourl` 也在
  `/v1/models`**，`warnings` 里**没有**任何新条目（`['resource_adapter_unbuilt']` 是幽灵那条），
  调用 503 且文案是 `无可用出站适配器（protocol 未实现）`——**原因说错了**（protocol 已实现，
  是地址为空被 `main.py:345-346` 静默 `continue`）。
- **为什么算问题**：Q28-② / BUG-1 / F-5 的立意是"**选了必然失败的模型不得对外声明**"。修复轮把这条
  判据接到了"资源停用/失效"（③）与"出站前提未注入"（⑤），**没有接到"适配器根本没建出来"**；
  `servable_models` 只看 `enabled + 运行态 + premise`，看不到 `runtime.adapters` 缺项。
- **建议**：把 `_adapter_errors`（构造失败）与"空 `base_url` 跳过"并入 `unservable_reason` 的
  同一谓词（或让 `ResourceManager` 暴露 `adapter_missing` 判据由装配侧注入），隐藏+横幅；
  空 `base_url` 那条至少要有横幅，且错误文案要与真实成因一致。

### F2【中】`_apply` 前置步骤失败 → 半应用运行态 + 零横幅（B-1 护栏只覆盖资源循环）

- **触发**：`data/model-enums.yaml`（**用户可扩展文件**，UI 也直写它）被手改坏（YAML ParserError）。
- **红证（live，rt5）**：坏 enums → 物化第二个账号（其热重载必失败）→ 加模型映射 →
  `/v1/models = ['m-good','m-new']`（config/registry 已换新）→ `m-new` 调用
  `503 … 无可用出站适配器（protocol 未实现）`（adapters/key_values 还是旧的）→
  `warnings=[]`（**零横幅**）→ 修好 enums 再动一次配置才自愈（200）。
- **红证（in-process 精确到字段）**：`reload_from_file()` 抛 `ParserError` 后
  `rt.config.models=['m-good','m-new']`、`rt.resources.pools` 含 `m-new`，而
  `rt.adapters=['res-A']`、`rt.key_values=['res-A']`（`HALF-APPLIED=True`）。
- **为什么算问题**：这是 B-1 的**同一个"半应用 + 只在日志里"**形态，只是触发点从"资源循环"挪到
  "循环之前"（`main.py:314-317`：`self.config`/`resources.rebuild` 先落地，`load_enum_pool` 再抛）。
  watcher 不死（本轮不是那次阻塞级），但用户看到的是"模型在清单里、调用永远 503、界面无任何提示"。
- **建议**：`_apply` 做成"先在局部构造全部派生件、最后一次原子换"（或把 `load_enum_pool` 包成
  "失败回落内置 + 记一条 warning"）；并给"本轮热重载失败"加一个横幅出口（当前只有 stdout/日志）。

### F3【中】凭据经上游错误体回显 → 明文进事件 JSONL（§22.2 不变式②）与客户端响应体

- **红证**：假上游在 401 错误体里回显 `Authorization`（令牌 `SECRET-SEC-EB-2nd-9a11`）：
  - 客户端响应体：`in_response=True`；
  - **事件 JSONL**：`in_events=True`，字段与原文逐字（`/tmp/m6eb/rt4/usage/events-20260930.jsonl`）：
    ```
    resource_attempts[].errors[] = [401] {"error":{"message":"token rejected; got Authorization: Bearer SECRET-SEC-EB-2nd-9a11","type":"auth_error"}}   （行 status=failed）
    ```
    成因：`stats/events.py:28-35 error_summary` 取 `err.error_body[:160]` 原样入事件；
  - 网关日志：`in_log=False`；`ops-results-*.jsonl`：无。
- **注**：常规 401（不回显）时，上述四个面**全零命中**（D.2/D.6；扫描令牌 `SECRET-SEC-EB-4c19d7a0`，
  且对照 C.4 证明该令牌真的在出站头上——扫描客体存在）。
- **性质**：`error_summary` 是既有实现（非 M6 新写），但 M6 让"账号令牌"成为产品资源的常态凭据，
  面被放大；且 §22.2 不变式②写的是**绝对口径**（"日志/事件中凭据只以短哈希出现"）。
- **触发条件**：需要上游把凭据回显进错误体（WAF/代理错误页、调试型网关都可能）。
- **建议**：`error_summary` 加一层边界脱敏（`Bearer \S+` / `sk-[A-Za-z0-9_-]{8,}` / 本账号令牌
  前缀匹配替换为 `…<hash8>`），或至少在交付话术里显式声明该边界（"凭据不落盘"的前提是上游不回显）。

### F4【低】import 路径清洗式改名 vs 其余写路径"拒绝"——口径不一致

- `POST /admin/api/accounts/import {"payload":{"name":"../evil"}}` → 200 且落库 `evil`
  （`store.py:624 sanitize_name`）；非越界（`accounts/evil`）、响应明示落库名。
- 对照：`commit_login`（`_require_name` 严格校验）、`materialize._require_name`、管理端
  `_require_account` 全部**拒绝**改名。
- 影响：同一清洗值（如 `evil` / `../evil` / `e vil`）会落到同一账号，导入到已存在账号时按
  "已存在"拒绝（不静默覆盖）→ 风险有限；但"看得见的行为差异"会让用户以为改名成功了别的名字。
- **建议**：与其余路径对齐（非法名 400 + 可执行文案），或在响应里明确"名已清洗为 X"。

### F5【低】物化资源 `name` 为空 → `res-xxxxxxxx` 进入事件/统计/错误文案

- `state.label = r.name or r.id`（`resources.py:420-424`）→ 事件 `resource_attempts[].resource =
  "res-64b0ca5a/hy3"`（留档 run1 事件行）、错误文案 `资源 'res-4665fbdc' …`（run7 半应用红证）、
  看板"按资源"维度同。
- UI 有 vendor/account 列兜底，故列低；但排障文案里的 `res-xxxxxxxx` 对用户没有信息量。
- **建议**：物化时 `name = f"{vendor}/{account}"`（或留空但文案回退到 vendor+account）。

### 风险（我没能证伪，但风险在这）

1. **F3 的镜像面**：客户端响应体原样透传"厂商原始错误"是 §6 的**有意契约**（不修饰）；一旦上游
   回显凭据，调用方（工具）也能看到本网关的内部账号令牌。修 error_summary 只能保住落盘面，
   响应面要不要脱敏是**产品口径**（本报告不替用户决定）。
2. **zcode D1 前提**：本报告只验证了"前提未注入 → 不下发 + 横幅"，**没有**验证"注入验证码后
   zcode 转发真的可用"（需 D1 实测）；注入后 `unservable_reason` 会自动放行，此时它是否真的
   可服务**无证据**（交付话术红线不变）。
3. **真实上游凭据行为**：`product` 资源的凭据在账号目录逐请求重读（不缓存）——我验证了"重登即换
   令牌生效"，但"上游对同一账号换令牌是否接受/是否触发风控"无真实凭据不可判（§22.11）。

---

## 九、未验证（无证据即不下结论）

1. 真实上游 / 真实凭据（buddy/trae/zcode/qoder… 真机登录与转发）——§22.11 用户驱动。
2. qoder 真实签名器（WASM/COSY）与 zcode 真实验证码求解器：仅验证了缝的 fail-closed 与
   provider 异常 → 503 可读（`_mint_captcha` 包装）。
3. `mgw zcode claim` **真实网络的退出码 0**（全成功）：需真凭据/住宅代理；本报告只验证映射逻辑。
4. 前端「账号接入」页与 M6-4 管理端 UI（本角色边界外；IX/PM 覆盖）。
5. `trae`/`loomy`/`raccoon`/`cline`/`lobsterai` 的逐产品全链真跑：本次端到端只跑了 buddy 全链
   （qoder/zcode 只到"前提排除"面）；其余产品的出站链路由 R2 探针与集成测试覆盖，我未逐个复跑。
6. TLS 指纹（curl_cffi）在真 WAF 下的效果（本机未安装 curl_cffi）。

---

## 附录 A · 被审文件哈希（sha256 前 12 位；评审开始 = 评审结束，零漂移）

```
e7080f99bd65  model_gateway/main.py
8de76e546857  model_gateway/core/resources.py
72e147c3f3ed  model_gateway/adapters/product_out.py
5c2e8d18eb63  model_gateway/api/admin.py
e3d10e7dd9e1  model_gateway/accounts/materialize.py
7239bf27c7d3  model_gateway/cli_zcode.py
70ffdff25f56  model_gateway/config/schemas.py
```

`diff -rq /tmp/m6eb/work/{model_gateway,tests} <主树>/…` → **完全一致**（评审结束时零差异；
运行期出现的 `_wiring_canary_pkg_<pid>` 是 pytest 用例的自播种夹具、随进程退出清理）。
变异实验后三文件已还原并与备份逐字节一致。

## 附录 B · 复跑命令与证据清单

```sh
# 一键复跑全部探针（约 8 分钟；输出留档 /tmp/m6eb/logs/probe-*.log）
sh /tmp/m6eb/probe/run_all.sh

# 单跑
/Users/w/Desktop/Model-Gateway/.venv/bin/python /tmp/m6eb/probe/run1_e2e.py       # ① 全链+流式+错误映射
/Users/w/Desktop/Model-Gateway/.venv/bin/python /tmp/m6eb/probe/run2_premise.py   # ③ 前提排除
/Users/w/Desktop/Model-Gateway/.venv/bin/python /tmp/m6eb/probe/run3_reload.py    # ④ 热重载健壮 + F1 观察
/Users/w/Desktop/Model-Gateway/.venv/bin/python /tmp/m6eb/probe/run4_security.py  # ⑤ 安全面
/Users/w/Desktop/Model-Gateway/.venv/bin/python /tmp/m6eb/probe/run5_schema.py    # ⑥ schema/兼容
/Users/w/Desktop/Model-Gateway/.venv/bin/python /tmp/m6eb/probe/run6_cli.py       # ⑦ CLI 契约
/Users/w/Desktop/Model-Gateway/.venv/bin/python /tmp/m6eb/probe/run7_halfapply.py # F2 半应用红证
/Users/w/Desktop/Model-Gateway/.venv/bin/python /tmp/m6eb/probe/run8_errors.py    # 错误映射（500/中途失败）
/Users/w/Desktop/Model-Gateway/.venv/bin/python /tmp/m6eb/probe/run9_mutations.py # A/B/D 撤修复红证
/Users/w/Desktop/Model-Gateway/.venv/bin/python /tmp/m6eb/probe/run9c_watcher.py  # C 分层撤修复红证
```

- 运行数据：`/tmp/m6eb/rt1..rt8`、`rt-cli`、`rtA..rtD`、`rtC1..rtC3`（配置/账号/事件/日志全在盘）
- 网关日志：`/tmp/m6eb/logs/gw{1..6}.log`、`mut-*.log`；探针输出：`/tmp/m6eb/logs/probe-*.log`
- pytest：`/tmp/m6eb/logs/pytest-full-nonaccounts.log`（924 passed / 1 artifact failed）、
  `pytest-accounts.log`（497 passed）
