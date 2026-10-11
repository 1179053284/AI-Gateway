# M6-R3 独立评审报告 · 管理端（API + 前端）（对抗式）

> 角色：独立评审 R3（对抗式，只读主树；不改任何源码 —— 唯一写入 = 本报告）
> 评审对象：`docs/specs/tech-design.md` §22.7（API 契约 / UI 段）+ `docs/specs/frontend-spec.md`（前端唯一基准）+ 下列实现：
> - `model_gateway/api/admin_accounts.py`（13 端点）＋ `model_gateway/api/admin.py`（挂载）
> - `model_gateway/accounts/login.py`（会话引擎 / `alt_call` / `_commit`）
> - `model_gateway/web/static/js/pages/accounts.js` + `main.js` / `index.html`（导航）
> - `tests/integration/test_admin_accounts.py`
> - M6-4b 验收证据：`docs/changes/e2e-records/m6-accounts-assertions.json` + `m6-accounts-*.png`
>
> 证据基准：tech-design v2.0 §22.6/§22.7/§22.8 + frontend-spec（v2.x 定版）+ `docs/research/20`（DSH 取证）
> 快照时间：2026-09-30（工作树含未提交的 M6 增量）
> 评审方法：静态通读 + 契约逐条对表 + **独立实例真机重跑 DOM 断言（端口 8398，MG_CONFIG→/tmp）** + pytest 复跑 + 攻击面实测
> 硬约束：主树只读（唯一写入 = 本报告）；不碰 :8300 / `data/**` / 并行工作流文件（`pages/logs.js` / `pages/stats.js` / `scripts/verify_v2_frontend.mjs`）；`--basetemp=/tmp/m6r3-$$`

## 0. 结论摘要

**阻塞项：0**（无"必须停手修复"的硬缺口）；**发现 5 条**（全部附红证/最小复现，无一"疑似"）：

| # | 级别 | 一句话 | 落点 |
|---|---|---|---|
| P-1 | 低（前端缺陷，建议必修） | 向导 qr_payload 行 `.ellip` 类作用域是 `.tbl .ellip` → 模态框内失效，长内容把 `.modal-body` 撑出横向滚动条 | `accounts.js:562` × `base.css:311` |
| P-2 | 低（证据标注漂移） | 断言 JSON 的 P-B1 条目是**修复前**复现记录（`ok:true` = 复现成功），无「已修（Fix-4）」标注；今日重跑必红 | `m6-accounts-assertions.json:263` |
| P-3 | 低（读写不对称） | 视图出**原始目录名**、写路径严格白名单 → 白名单外目录名"看得见、点不动"，且与清洗名目录并存时数据错位 | `admin_accounts.py:346-347` |
| P-4 | 中（既定设计外延） | 免鉴权 + 简单 POST → **跨站 CSRF 实测可触发** enable/disable/claim/delete | `admin_accounts.py:372-665`（Q18-①） |
| P-5 | 信息级 | `delete` 重复 `confirm` 参数取末值（`confirm=0&confirm=1` 会删） | `admin_accounts.py:647` |

- **真机重验全绿**：独立实例（**8398**，`MG_CONFIG=/tmp/m6r3/config.yaml`，绝不碰 :8300 / `data/**`）自写 CDP 脚本重跑 **67 项** DOM 断言：导航高亮 / 分组卡 8 / 产品行 10 / 能力按钮（buddy 4 钮、raccoon 无签到、loomy 续期置灰）/ 设备列（uuid、machine_id+device_id）/ 空状态 / D3 启停落库（盘面核对）/ 删除确认取消 / 向导 **6 型**（device_code·qr 图·qr 内容·sms 两段·local_callback·external_link）/ 双主题 / 12px 节奏 / 390px 抽屉化 —— 全部与 M6-4b 的断言口径一致（唯一 1 项 FAIL 是我自己的期望值写错，复测已澄清，见 §2-W2b）。
- **凭据零泄露**：12 个响应体（含 404/400/409 错误体与三通道登录响应）+ 网关日志 + `ops-results-*.jsonl` 全量扫描探针串 **零命中**；视图 `display` 白名单生效。
- **护栏成立**：目录穿越（含 `--path-as-is` / 编码变体）/ 非法账号名 / 跨产品会话串用 / 会话 id 猜测 / XSS（3 向量）/ `?confirm` 缺省拒删 —— 全部按契约拦下；错误体不吞异常（真实产品代码 `NotImplementedError → 502` 可读原文；`NotRefreshable → 409`）。
- **同族缺陷（P-B1 家族）已排查干净**：`commit_login` 4 个调用方逐一核对，写回自检比较基准 = `merged`（真正落盘内容）；实测 3 轮「disable→enable」× 1.2s 间隔（共 6 次调用）全 200；反向实验证明"陈旧基准"必红（§5）。**另发现 M6-4b 证据 JSON 的 P-B1 条目是修复前复现记录且无「已修」标注（P-2）**。
- **M6-4b 截图 9 张逐张检视**：均为真实页面顺序截图（非拼贴），与断言清单互相印证；但 `m6-accounts-wizard-qr-payload.png` 里可见的横向滚动条正是 P-1 缺陷本身（清单未覆盖该视觉问题）。

---

## 1. 评审环境与方法（硬约束遵守）

| 项 | 事实 |
|---|---|
| 独立实例 | `MG_CONFIG=/tmp/m6r3/config.yaml` → 数据目录 `/tmp/m6r3/`（`paths.data_dir()` = 配置父目录）；端口 **8398**；全程未读写 :8300 与项目 `data/**` |
| 实例形态 | ① 先起**原样 `python -m model_gateway.main`**（做 API/攻击面/落盘核验）；② 再起 `/tmp/m6r3/launcher.py`（**仅** 把 buddy/qoder/loomy/raccoon/cline 的 `login_start/login_poll`、buddy 的 `claim/refresh/probe`、loomy/raccoon 的 `_ALT_HOOKS` 换成 canned 返回值——真实钩子会发真实上游请求，用户裁决「真实凭据类一律未实测」；其余全部真实代码路径 + 真实 HTTP 端点）。canned 值一律 `*.example.com` / `*.mock.invalid` / 固定串，不含任何真实凭据 |
| 数据面 | 与 M6-4b 同形（buddy-demo1/2、lobster-demo1、trae-demo1、loomy-demo1、raccoon-demo1 + raccoon 坏 `runtime.json`），全部经 `store.commit_login` 落盘 |
| 浏览器断言 | 自写 CDP 脚本（`/tmp/m6r3/dom_check{,2,3,4}.py`，headless Chrome）——**未复用** `scripts/verify_v2_frontend.mjs`（并行工作流文件，未读未改） |
| pytest | `tests/integration/test_admin_accounts.py` → **23 passed**；`tests/accounts` → **483 passed**（`--basetemp=/tmp/m6r3-pytest*`） |
| 只读纪律 | 主树唯一写入 = 本报告；未改任何源码/前端/测试；`pages/logs.js`、`pages/stats.js`、`scripts/verify_v2_frontend.mjs` 未触碰 |

---

## 2. 真机重验：DOM 断言独立重跑（自写脚本，逐项与 M6-4b 口径对齐）

证据（全部在本机 /tmp，可复跑）：`/tmp/m6r3/dom-results{,2,3,4}.json` + `/tmp/m6r3/shots/*.png`。
**39/39 + 20/21 + 5/5 + 3/3**（唯一 FAIL 见 W2b，系我方期望值错误，复测澄清）。

| 任务要求项 | 我的断言（结果） | 关键实测值 |
|---|---|---|
| 导航高亮 | A2 PASS | `.nav-item.active` = `accounts`；`PAGE_META` 注入 `Console › 资源配置` + `账号接入` |
| 分组卡数 | A6/A7 PASS | group-card = **8**（CodeBuddy 族/LobsterAI/Qoder 族/Trae/Cline/Loomy/Raccoon/ZCode）；产品行 = **10**（`registry.PRODUCT_IDS` 全量、顺序一致） |
| 能力按钮 | A16a/b/c/e PASS | buddy 行 = `probe+refresh+claim+delete` 4 钮全可用；loomy `refresh` 钮 `disabled+off` 且 title 给出「不可续期：续期通道未登记」；raccoon 无 `claim` 钮；loomy/raccoon 均无 `onboarding` 钮（端点未就绪） |
| 设备列 | A12b/c/d PASS | lobsterai 列含 `设备`，单元格 `uuid = 1111…5555`；trae 双行 `machine_id = …` + `device_id = …`；buddy 无设备列 |
| 空状态 | A17 PASS | cline（0 账号）：`暂无账号——点击「接入账号」用设备码授权完成第一个账号接入`，且无表格 |
| D3 启停落库 | D1/D1b/D1c PASS | UI 点开关 → 视图重取（`aria-checked` 同步）→ 盘面 `meta.json enabled=true`；再点回 = `false`（审计 `updated_at` 同步刷新、`via` 不篡改） |
| 删除确认取消 | D2a/D2b PASS | `confirmDialog` 标题「删除账号」、正文列明级联影响、脚钮 2 颗（取消/确定）；取消后账号目录仍在（零字节落盘） |
| 向导 ≥3 型 | W1–W6 PASS（**6 型**） | device_code（qoder：设备码+复制+授权地址+打开+自动轮询 1 次）；external_link（buddy：地址+打开+轮询「等待中」）；local_callback（trae：textarea+提交，**2.6s 零 poll 请求**且状态保持「等待用户操作」）；qr=图片（loomy：`img[data-wz=qr-img]` src=官方图片地址、200×200 属性、无 payload 文本分支）；qr=内容（raccoon：原文展示+复制+打开链接、**不伪造图片**）；sms_code（loomy 两段：手机号→校验 toast→下发(pending.detail 原样)→验证码→成功→弹窗关+账号落盘） |
| 双主题 | A22a/A22b PASS | 浅色 `data-theme=light`（顶栏 light 钮 active，`--bg #f7f8f9`）；深色 `data-theme=dark`（`--bg #101114` / `--surface #17191d`，令牌反转正确） |
| 补充抽查 | A0/A3/A4/A5/A8/A9/A10/A10b/A13/A14/A15/A18/A19/A20/A21/A23/A24/A25/A26/A27/A28/A23b PASS | 骨架接管留白 `-12/-12/-48` + 高 `calc(100vh-60px)` + 子侧栏 248 + 右区内部滚动；卡头统计 `2 个账号 · 1 启用`；停用行 `td.off`；开关 a11y 三件套与 `aria-checked` 同步；额度全 unknown → 整列不渲染；图标契约（fill=none/currentColor/sw2/14px）与 icon-btn 28×28；卡片 10px 圆角 + 12px 节奏；390px 应用侧栏抽屉化（`translateX(-100%)`）|

**W2b 澄清记录（防误读）**：首轮我把 `<img width="200">` 的**渲染宽**当断言值，broken-image 情形下 border+padding 使含内容盒缩到 182px → 我方 FAIL；复测（`/tmp/m6r3/shots/r3-wizard-qr-img-recheck.png`）确认 `width/height` 属性 = 200/200、src = 挑战返回的图片地址、`naturalWidth=0`（mock 域不可达 → 触发设计内的 onerror toast「二维码图片加载失败」）。**实现无误，是我方断言写法问题。**

**A24 网络边界（浏览器侧）**：整段会话的 `Network.requestWillBeSent` 全量枚举 = 仅 `127.0.0.1:8398` 静态/管理端点 + `loomy-qr.mock.invalid`（二维码 mock 图，`ERR_CONNECTION_CLOSED`）+ 字体/favicon —— **零真实上游主机触达**。

---

## 3. 凭据不泄露核验（API + 日志 + 结果文件）

探针串 `SECRET-R3-DO-NOT-LEAK-77c1`（写入 buddy/lobsterai/trae/loomy/raccoon 的凭据与 refresh_token）：

| 面 | 方法 | 结果 |
|---|---|---|
| 全部响应体 | `GET accounts` / `GET capabilities` / `claim` / `refresh` / `probe` / `disable` / `enable` / `import`（含回显型）/ `login/start` / `login/poll` / `login/alt` + 错误体（404 账号不存在、400 非法名/未登记产品、409 设备冲突、409 不可续期） | **零命中**（12/12） |
| 视图投影 | `display` 键集合实测 ⊆ `{via, created_at, updated_at, expires_at, plan, nickname, phone, email}`（白名单 `_META_DISPLAY_KEYS`，admin_accounts.py:78）——凭据键与私有 meta 键不出现在任何层级 | 通过 |
| 网关日志 | `/tmp/m6r3/gateway{1..4}.log` grep 探针串 + 令牌值 | **零命中**；落盘路径的"指纹"行为 INFO 级未输出，无明文（`store.py:291` 只打指纹） |
| 运营结果 | `usage/ops-results-20260930.jsonl` grep 探针串 | 零命中（`failed.reason` 只含产品层文案） |
| 注册表/能力 | capabilities 响应逐产品 `dataclasses.asdict(ProductMeta)`（无凭据字段） | 通过 |

---

## 4. 攻击面实测（逐条红证）

1. **账号名白名单 / 目录穿越**（`admin_accounts.py:173-182` `_require_account` 与 `store.sanitize_name` 同尺）：
   - `%2E%2E`、`...`、`.hidden`、`中文`、`a b`、33 字符、`a%00b` → 全 **400**「账号名必须匹配 [A-Za-z0-9_-]{1,32}」；`-` → 404（合法名但账号不存在）；
   - `curl --path-as-is .../buddy/../claim` → **400**（`..` 到达端点被白名单拦下）；`..%2F..%2Fetc` / `a%2Fb`（编码斜杠）→ **405**（路由不匹配，压根到不了 handler）；
   - 写路径一致：白名单外目录名的账号（手工落盘）任何动作（claim/enable/…）→ 400（§7-P-3 记录读侧不对称）。
2. **`?confirm=1` 语义**（`admin_accounts.py:645-659`）：缺省 → 400 且**零字节落盘**（账号目录原样）；`confirm=0`/`confirm=2` → 400；`confirm=true` → 422（int 解析）；`confirm=1` → 200 删除 + 关联资源置停用并保留（yaml 实测）。**重复参数取末值**：`confirm=1&confirm=0` → 400，`confirm=0&confirm=1` → 删除（P-5，信息级）。
3. **会话 id 猜测 / 跨产品串用**：id = `secrets.token_hex(8)`（16 hex）；随机 id → `200 {"state":"expired"}`（无差异面、无枚举泄露）；`poll` 拿 A 产品会话按 B 产品 → **400**「会话与产品不匹配」；`alt` 同理（buddy 因 `_ALT_HOOKS` 表缺项先 400，loomy/raccoon 走 `_require_session` → 404/400）；**引擎自身防串线**（`login.alt_call`，login.py:338-341）进程内实测：`alt_call("buddy", <loomy 会话>, "sms_send")` → `ValueError：会话与产品不匹配：会话属于 'loomy'，却按 'buddy' 调用 'sms_send'`；`_session_of` 已收敛到公开 `login.get_session`（login.py:353，`None`→404 实测），且 `poll_login/callback_login/alt_call` 的**全部**消费方只有 `api/admin_accounts.py` 一处（无第二个入口会漏掉产品校验）。
4. **错误体不吞异常**（映射表逐条实测）：真实产品代码 `loomy.login_callback`（`NotImplementedError`，RuntimeError 子类）→ **502**「产品层执行失败：loomy.login_callback：本产品非 local_callback 型…」；`loomy.refresh` 真实实现 → **409**「不可续期」+ `refreshable:false`；未登记产品 400 / 账号不存在 404 / `CommitError → 500`（用例 `test_refresh_success_not_refreshable_and_rollback` 钉死）/ 兜底 500 带 `logger.exception`（§22.8-5 不伪装业务失败）。
5. **XSS（页面把外部文本插入 DOM 的路径）**——三个向量全部实测零执行：
   - ① `import` 载荷 `meta.plan/nickname = <img onerror=…>/<svg onload=…>`（走真实落盘与视图投影）→ 行内以**文本**呈现（`planText=true` 指认原文在 textContent 中）、`#ac-table img` = 0、`window.__XSS_PLAN/NICK` = undefined；
   - ② **白名单外目录名**（`x<img src=x onerror=…>` 手工目录）→ 行 `data-acc`/单元格均为文本，零执行；写路径 400 拒绝；
   - ③ `claim` 钩子返回的 **detail 带 HTML**（模拟上游错误文本）→ 徽章 `title` 属性与 toast 均为转义后的纯文本（`badge b-err` / toast 原文），`window.__XSS_CLAIM` = undefined、表格内零注入元素。
   - 机理：`esc()`（api.js:51 覆盖 `&<>"'`）贯穿 `accounts.js` 各处插值；toast 走 `textContent`；`modal()/confirmDialog()` 对 title/text 亦 esc。**未发现可利用注入点**。
6. **跨站 CSRF（P-4，见 §7）**：从另一 origin（`http://127.0.0.1:8397` 页面）`fetch(POST, no-cors)` → 服务端**真实执行**（buddy-demo2 `enabled` False→True，盘面核对）——简单请求无预检，`?confirm=1` 也照删。

---

## 5. 同族缺陷搜索（P-B1「写回自检比较基准」家族）

**结论：家族已清理干净，未发现第二个同族点。**

1. **比较基准现状**（store.py:259-473）：`commit_login` 用 `merged`（= 旧 meta 合并入参 + `created_at/updated_at/via` 刷新后的**落盘期望内容**）作为 `_verify_written` 的元信息基准；凭据侧只逐键校验"本次传入的键"。**陈旧基准必红的反向实验**（不改源码，直接以旧 meta 调私有校验口）：
   - `① stale baseline（updated_at 用上一秒）→ CommitError: 写回自检：元信息键 'updated_at' 读回不一致`（与 P-B1 原始复现文案逐字一致）；
   - `② merged baseline → PASS`。→ 修复点真实有效、回归用例真能红。
2. **全部调用方（4 处）逐一核对**：`_set_enabled`（admin_accounts.py:237-255，P-B1 原发点，实测 3 轮「disable→enable」× 1.2s 间隔共 **6 次调用全 200**，盘面 `updated_at` 刷新、`via` 保留）；`account_refresh`（:590，meta 传 `{}` → 不引入陈旧键）；`import_account`（store.py:383，载荷 meta 里即便含 `updated_at` 也会被覆写后按 merged 比对）；`login._commit_outcome`（login.py:287-301，钩子 meta 同理）。
3. **store 管理键清点**：仅 `created_at`（setdefault）/`updated_at`（恒刷新）/`via`（仅在缺失时写）三个（store.py:280-284）；`enabled` 归 admin 层、设备字段归 import/session 层——无第四个"调用方会带着过期值回传"的键。
4. **其余"读回自检"实现无同族**：`setup_tools.write_models_json` 的读回只验**形状**（`models` 是否 list），不与入参逐值比对；zcode 旧 `_commit`（upstream/zcode/store.py:183）**没有**读回自检（只有原子写+telemetry 同步）→ 无陈旧基准面。
5. **文档漂移**：`m6-accounts-assertions.json` 的 P-B1 条目是**修复前**的复现记录（见 §7-P-2）。

---

## 6. M6-4b 证据核验（截图与断言一致性 + 清单抽查）

**截图（9 张逐张检视，非拼贴判定）**：
- 尺寸/模式：8 张 `1440×853 RGB` + 1 张 `780×1688`（窄屏，= 390 CSS @dsf2，与"≤768 抽屉化"的断点口径自洽）。
- 与断言一致：light/dark 的导航高亮、buddy 双行（1 启用/1 停用）、`A16a` 的 4 钮、头卡副行、`接入账号` 钮在卡头 —— 与我复跑画面逐项一致；wizard 5 张的弹窗结构（设备码行/二维码区/短信两段/回贴 textarea/qr_payload 文本行）与 `W1–W6` 断言逐项对应。
- **真实顺序截图痕迹**（反拼贴证据）：external / callback / qr-payload 三张顶部都残留同一个 6 秒生命期的 err toast「二维码图片加载失败（官方图片地址不可达）」（前一步 loomy qr 的 `img.onerror`）——跨步骤状态延续，拼贴难以伪造；同时 `m6-accounts-wizard-qr-payload.png` 里可见的**横向滚动条**正是 P-1 缺陷本体（清单未覆盖该视觉问题；裁切佐证 `/tmp/m6r3/shots/m6-4b-qr-payload-bottom-crop.png`）。
- 一处口径说明：其 wizard mock 使用了**含真实厂域名的 URL**（`copilot.tencent.com/login/demo`、`trae.example.com/…`）——截图中仅为展示文本、未见请求痕迹（其 A24 亦称未触达真实上游）；**我方复跑改用 `*.example.com / *.mock.invalid` 并逐请求枚举核实 0 触达**（§2-A24），口径更硬。

**清单抽查（≥5 条，逐条落到代码/实测）**：

| 清单项 | 代码定位 | 我的实测 |
|---|---|---|
| A13 额度列全 unknown 不渲染 | `accounts.js:223`（`quotaCol = some(state !== "unknown")`）+ `quotaCell` 的 unknown 分支 | PASS（buddy 全 unknown → 无「额度」列） |
| A16b loomy 续期置灰+原因 | `accounts.js:302-311`（`c.refresh` else 分支：`off + disabled + title`） | PASS（title 原文核对） |
| A16c raccoon 无签到 | `accounts.js:312-315`（`if (c.checkin)`） | PASS（raccoon ops 无 claim） |
| A16e onboarding 按钮不渲染 | `accounts.js:84`（`ONBOARDING_ENDPOINT_READY=false`）+ `:316` | PASS（loomy/raccoon 均无 onboarding 钮） |
| W4b local_callback 不轮询 | `accounts.js:54`（`POLLABLE` 集合不含 local_callback）+ `:500` 判据 | PASS（2.6s 内 0 个 `/login/poll` 请求） |
| D1b 启停即落库（无「保存」） | `accounts.js:330-339`（POST → `reload`）→ `admin_accounts.py:237` → `store.commit_login` | PASS（盘面 `enabled` 核对 + 全页无「保存」字样） |
| D2 删除二次确认 + `?confirm=1` | `accounts.js:411-422` + `admin_accounts.py:645-659` | PASS（取消零落盘；API 侧缺省 400） |
| A24 全量请求无真实上游 | `accounts.js` 仅本机相对路径；无外链 `<script>` | PASS（请求全量枚举） |

**漂移 1 处**：P-B1 条目（§7-P-2）；其余抽查项与实现一致，未发现清单-实现漂移。

---

## 7. 发现清单（含最小复现与处理建议）

### P-1（低 · 前端缺陷，建议修）向导 qr_payload 行 `.ellip` 失效 → 弹窗横向滚动条
- **位置**：`model_gateway/web/static/js/pages/accounts.js:562`（`<span class="mono ellip" …>`）——`.ellip` 在 `base.css:311` 是**表格作用域** `.tbl .ellip`，模态框内不生效（实测 computed：`white-space: normal / overflow: visible / text-overflow: clip`；对照表内为 `nowrap/hidden/ellipsis`）。
- **最小复现**：账号接入 → 左栏选 **Raccoon** → 「＋接入账号」→「开始登录」→ `.modal-body` 出现横向滚动条（实测 `scrollWidth 886 > clientWidth 558`），二维码内容行折成两行且右侧被裁切（与 M6-4b 截图 `m6-accounts-wizard-qr-payload.png` 所见一致）。
- **建议**：该行改用与 `linkHTML` 相同的内联 `overflow:hidden;text-overflow:ellipsis;white-space:nowrap`（accounts.js:548），或把 `.ellip` 提升为全局类（注意 `td` 内语义不变）。**证据**：`/tmp/m6r3/shots/r3-raccoon-overflow.png` + 上述实测值。

### P-2（低 · 证据标注漂移）断言 JSON 的 P-B1 条目是"修复前复现记录"，无「已修」标注
- **位置**：`docs/changes/e2e-records/m6-accounts-assertions.json:263-266`（`ok:true` 的含义是"缺陷复现成功（500）"）；修复落在 `model_gateway/accounts/store.py:447-473`（比较基准改 `merged`），回归见 `tests/integration/test_admin_accounts.py:614` 与 `tests/accounts/test_store.py:434`。M6 台账（`E2E-20260930-M6-multi-product.md`）待修清单 R-1..R-7 **未登记 P-B1 已修**。
- **后果**：任何人拿该 JSON 重跑会对 P-B1 得红（我方实测：现在**不会**再 500 —— 3 轮「disable→enable」×1.2s 间隔共 6 次调用全 200），可能被误判为回归。
- **建议**：给该条加 `"note": "复现记录（Fix-4 前）；修复后应断言 200（见 store.py::_verify_written）"`，或在台账里补一行"P-B1 已修（Fix-4）"。

### P-3（低 · 读写白名单不对称）读侧出原始目录名、写侧严格白名单 → 展示与可操作不一致
- **位置**：`model_gateway/api/admin_accounts.py:346-347`（`store.list_accounts()` 原始目录名直接进视图）vs `store.sanitize_name`（store.py:109）与 `_require_account`（admin_accounts.py:173-182）。手工/外部工具落下的白名单外目录名（带 `<`/空格/引号）会作为"账号"展示，但任何动作 400；且 `load_meta` 走 sanitize 后的名字 → 与同名清洗目录并存时**显示数据会指向另一目录**。
- **实测**：目录 `x<img src=x onerror=…>`（带合法 `meta.json`）→ 视图出现该行（展示为文本，零 XSS）；`enable` → 400。写侧护栏本身**成立**（这正是我们想要的），问题只在读侧口径。
- **建议**：视图层对非法名做过滤/标记（如 `invalid_name: true` 或直接不列出），避免"看得见、点不动、数据还可能错位"。

### P-4（中 · 安全暴露面，M6 外延）免鉴权 + 简单请求 → 跨站 CSRF 可触发破坏性端点
- **位置**：全部 13 个账号端点（`admin_accounts.py:372-665`）均为 **POST + 无鉴权**（§22.7 / Q18-① 免鉴权）；`?confirm=1` 只防误触、不防跨站。
- **实测（真 PoC）**：从**另一 origin**（`http://127.0.0.1:8397` 页面）`fetch("http://127.0.0.1:8398/admin/api/accounts/buddy/buddy-demo2/enable", {method:"POST", mode:"no-cors"})` → 浏览器**未预检直接发出**，服务端执行，盘面 `enabled` False→True。同理可打 `disable`、`claim`、`delete?confirm=1`（删除不需要请求体）。
- **定性**：属 Q18-① 既定"本地自用、免鉴权"设计的外延风险（`config.example.yaml:10` 还示范了 `host: 0.0.0.0`，局域网可达），**非 M6 引入**，但 M6 新增端点（尤其 `delete`/`import`）显著扩大了可被第三方网页触发的破坏面。
- **建议（交总 agent/用户裁决，本评审不改）**：破坏性端点要求自定义头或 `Content-Type: application/json`（跨站必预检）/ 校验 `Origin`；或在文档与 UI 明示"仅本机回环使用"并保持 `host: 127.0.0.1`。

### P-5（信息级）`delete` 重复 `confirm` 参数取末值
- **位置**：`admin_accounts.py:647`（`confirm: int = Query(default=0)`）。实测：`?confirm=1&confirm=0` → 400；`?confirm=0&confirm=1` → **200 删除**（FastAPI 取最后一个）。
- **定性**：标准框架行为，无安全增益问题（攻击者本可只带一个 `confirm=1`），但与"显式确认"语义有歧义。
- **建议**：可选加固——拒绝重复 `confirm` 参数或改 `Literal[1]`；不改亦可接受（登记即可）。

---

## 8. 放行意见

- **管理端 API（13 端点）与「账号接入」页实现与 `tech-design §22.7` / `frontend-spec`（两行顶栏 / 骨架 A / D3 / 图标契约 / 双主题 / 12px 节奏 / a11y 三件套）逐条相符**；凭据不泄露、白名单护栏、错误语义、会话防串线、P-B1 家族清理 —— 均已有独立真机红证。
- **无阻塞项**。按"零问题交付"纪律，建议 M6-6 收口时处理：**P-1（前端，含 `.ellip` 作用域）必修**；P-2（证据标注）随手补；P-3/P-4/P-5 由总 agent 决策（P-4 建议至少形成文字结论，避免"局域网 + 免鉴权 + 可 CSRF"三叠加被无意识继承）。
- 本报告全部结论可复跑：实例数据 `/tmp/m6r3/`、断言脚本与截图 `/tmp/m6r3/dom_check*.py`、`/tmp/m6r3/shots/`、结果 JSON `/tmp/m6r3/dom-results*.json`、pytest `--basetemp=/tmp/m6r3-pytest*`。

