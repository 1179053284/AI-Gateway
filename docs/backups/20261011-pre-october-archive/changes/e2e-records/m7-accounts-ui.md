# M7-UI 验收证据 · 账号接入页改版 + 回调接收端

> 时间：2026-09-30 15:00 → 20:30 CST｜执行：主 agent + 5 个子 agent（其中 2 个撞 150 轮上限，产物按磁盘判定）
> 设计依据：`docs/changes/design-accounts-list-v2.md`（v2.1 定稿，含 §10 逐条评审处置）
> 铁律 2：本文每个数字都是**某次实跑的尾巴输出**，标注来源；未跑的一律写「未验证」。

---

## 1. 本轮落地面（逐条 `file:line`）

| 面 | 落点 |
|---|---|
| 回跳接收端（根因修复） | 新 `model_gateway/accounts/callback_server.py`（`CallbackListener` / `CallbackCapture` / `declared_port:514`）；会话级接线 `accounts/login.py::_open_callback:396`、`_deliver`、`_close_callback:240`、`_drop:451`（出表**且**关监听，防端口泄漏） |
| 两产品接实绑端口 | `upstream/trae/product.py:167` 与 `upstream/lobsterai/product.py:204` 的 `_CALLBACK` 声明表；`upstream/lobsterai/login.py:117` 的 `gateway_port()` 降级为"仅粘贴兜底"并改正了原先「网关自己就是接收端」的错误注释 |
| 取消路由（BD2） | `api/admin_accounts.py::login_cancel`（幂等，取消不存在的会话回 200 `cancelled:false`，不 404）；测试 `tests/integration/test_admin_accounts.py::TestLoginSession::test_login_cancel_is_idempotent_and_drops_the_session` |
| BD1 停用位对定时腿生效 | `main.py:209-218` 两条腿传 `enabled_of=cron_enabled_of`；解析器 `api/admin_accounts.py:277-319` |
| BD8 无账号也起调度 | `main.py:136-228`（去掉启动期一次性"无账号即永不起"，改为**每轮**判空并直接 return，避免 0 账号写 2880 行垃圾 jsonl） |
| BD3a 资源关联 | `api/admin_accounts.py:368-397 _resource_projection`（数组；`null`=配置读不动=未知，`[]`=确实没有）+ `:499` 字段 |
| 页面重写 | `web/static/js/pages/accounts.js`（1182 行）：族层全删、10 行扁平 rail、四态点、4 列固定、额度四值、展开行、单 GET、`?p=` 深链、向导生命周期单一所有者 |
| 样式收口 | `base.css:594-603 .panel-split` + `:1102`（1280）+ `:1118-1129`（≤768 rail 横滚条带）；`frontend-spec.md` v2.16；`design-spec.md` **新增 §2.8「账号接入」**（此前全篇无此章） |
| 判据 | 新 `scripts/verify_accounts_ui.mjs`（静态门，12 判据 + 变异自证）；新 `tests/integration/test_int_v2_accounts_gate.py`（2 节点接进 pytest）；新 `scripts/verify_accounts_ui_live.py`（真机门，151 判据 + 三种撤证模式） |

---

## 2. 静态门（假 DOM，可复跑）

```
$ node scripts/verify_accounts_ui.mjs
合计：12 通过 / 0 失败
$ node scripts/verify_accounts_ui.mjs --mutation
可红 8/8；8 条判据全部可证伪
$ pytest tests/integration/test_int_v2_accounts_gate.py -v
7 passed（含 test_v2_readme_claims 全绿）
```

基线对照（改版前同一门跑老页）：`合计：2 通过 / 10 失败`。
V5 当时为绿是**事实**不是漏判——该页私有 `switchEl` 早已带 aria 三件套。
每条变异**先证可绿再证可红**（只红不绿＝死判据），锚点命中数必须恰好 1。

## 3. 真机门（独立实例 + 真 Chrome，可复跑）

```
$ .venv/bin/python scripts/verify_accounts_ui_live.py
合计：151 通过 / 0 失败
（其中浏览器段：[浏览器/full] 136 项 / 红 0）
```

实例：`127.0.0.1:8400`（自动挑空口，`bind` 试占 + `lsof` 双证）；临时根 `/tmp/m7-ix/`；
种子账号经生产入口 `store.commit_login` 落盘；上游全走 `httpx.MockTransport`
（A6 实证：32 条上游调用轨迹，hosts=`api.workos.com`/`loomyad.xunfei.cn`，**零真实出网**）。

关键读数（不是"通过"，是实测值）：
- 布局：`.subnav` 1440=248px / 1280=248px / **375=375px 全宽**；375 下 `.subnav` 转 `column`、
  rail 转 `row` + `overflow-x:auto`、10 行同处一条横带；主区 `main.bw=375px` 未被挤扁；
  rail 文案折行 0/10（1440 亦 0/10）；行高集合 `[38]`、`mark-sm` 高度 `[20]`。
- 令牌：浅色 `.subnav` 背景 `rgb(255,255,255)` == `--surface`；深色同一元素 `rgb(23,25,29)`；
  绿点两主题均 `rgb(22,215,109)` == `--dot-on`（`base.css:41,69` 有意同值）；
  warn 点 `#c26a00`/`#f0a35c`、灰点 `#c9ced3`/`#4a5058` 各随主题 —— 全程无硬编码 hex。
- 额度四值：有 `runtime.quota` 的行显示「有余量 查于 …」，无快照的行显示「尚未刷新」，
  `state:"unknown"` 显示「未知」并带原因 —— **BUG-1/BUG-2 的可见面**。
- `resource` 三态：`null` → 「网关资源：未知（配置读不动，不推断成 0）」；`[]` → 「无」；
  非空 → 「已物化 N 个资源 · 启用 M：ids」（经注入代理造 `null` 实测）。
- 诚实面：全页 + toast + 属性复扫禁用词命中 `[]`；`#modal-root` 收尾归零；
  删除确认如实承诺「关联资源置停用并保留 + 彻底删除去「模型资源」页」，
  N=0 变体文案不变地说明"不会停用任何资源"；缺 `?confirm=1` 的删除被 400 拒且**不动盘**。
- 目录 `state:"unknown"` → 只给原因 + **零条目**（不编造，与"未知不当零"同尺）。

截图：`docs/changes/e2e-records/m7-accounts-ui/`（14 张，19:41 那轮产出：浅/深 × 1440/1280/375、
展开行、空态、删除确认、设备码/回跳两类向导、目录未知、读失败、撤证①）。
🔴 **工具缺陷（已复现两次，非偶发）**：20:06 与 20:3x 两次复跑中 `Page.captureScreenshot`
**全部超时**（38 项 ×3 重试，`截图 0 张`），断言读数不受影响（runner 把截图失败记为错误、
未记为通过，也未让它带走整轮）。疑与本机 Chrome 实例争用或残留 profile 有关，**未查因**。
因此：① 视觉证据以 19:41 那轮 14 张为准；② 该 runner 在接入 CI 前必须先修这一步，
否则"截图齐全"会被误当成已验证。

## 4. 三条成对撤证（`--retract 1|2|3`，全部在 /tmp 复制品上）

```
撤证① 合计：6 通过 / 0 失败
  ✗[预期红] RT1 .group-card=1 railBox.class=group-card ／ RT3 容器类名不含 subnav-scroll
  ✓ R1-1 静态门同时变红 ["V1","L-A6"]
  ✓ R1-4 复制品与主树 sha256 逐字节相同 c8b7f1d7ccdb7d2a233a…
  ✓ R1-5 恢复后静态门回到全绿（红证可逆）
撤证② 合计：4 通过 / 0 失败
  断 BD8 → 额度恒「尚未刷新」且 runtime.json 从未写出（{"file": false, "quota": null}）、jsonl=[]
  恢复 BD8 → 「有余量 查于 2026-09-30 20:23」、runtime.json 出现 quota=available
  ✓ R2-3 两跑源码差异只点名 main.py（111 条原始差异行其余为 __pycache__，如实标注）
撤证③ 合计：4 通过 / 0 失败
  断 BD1 → 停用账号 ix-off 作为参与方出现在 6 个定时轮（cats=failed/success 交替）
  恢复 BD1 → ix-off 参与方命中=[]、只进 skipped（轮 0..11）
  ✓ R3-3 对照：启用账号 ix-on 恢复后仍正常进参与方（撤证没把腿撤断）
三条均含 R0：主树受监视 4 个源文件 sha256 前后一致、变动=[]
```

## 5. 回归计数

| 跑法 | 结果 |
|---|---|
| `tests/accounts tests/integration/test_admin_accounts.py tests/unit/test_v2_ops.py tests/unit/test_v2_wiring_guard.py` | **639 passed / 1 skipped**（156s） |
| 回调专项 `test_callback_server.py + test_m7_callback_capture.py` | **40 passed / 1 skipped** |
| 全量 `pytest tests/ -q` | **1520 passed / 1 skipped**（唯一失败是 README 计数门，随后已回填 1520 转绿） |
| README / `mgw --version` / `pyproject.toml` | 三向一致 **0.2.0** |

## 6. 本轮自查出的问题（不藏）

1. **死判据**：真机门 `H2b`（375px 十行同横带）此前读 `x.by`，而 rail 探针根本没采这个字段
   → `new Set([undefined×10]).size===1` **空过**（打印就是 `y 值=[null]`）。
   已修：探针补 `by`（`:566`），判据加"10 个值必须都是有限数"。
   **修后复跑实证**：`✓ H2b …｜实测 y 值=[72]（10 行）`，全套仍 `合计：151 通过 / 0 失败`。
   这条是我自己读输出时发现的，对抗评审与静态门都没覆盖到 —— 记下来是因为它的形态：
   **仪器读不到数却报绿**，比报红危险得多。
2. **引用漂移**：设计书与门注释里 5 处 `frontend-spec.md:519` 已过期（圆点/开关规则现在在 `:524`），
   全部更正并复跑门 12/0。
3. **我自己的两个错判**：① 上一轮断言 `NotImplementedError` 弹 500，实为 `RuntimeError` 子类走 502；
   ② 给门补 `/login/cancel` 桩时把反引号写进模板字符串，直接把门改崩 `SyntaxError`，改回后复跑 12/0。
4. **判据缺桩不该由被审方绕**：页面实现者发现门没给 `login/cancel` 造桩时，选择**如实上报**而非删功能，
   代价是当时把破坏性钮排到最后。桩已由我补上；按钮序问题消解，
   但「重新发起登录不作废旧会话」（旧会话靠服务端 TTL 出表）仍登记在页面尾部缺口 ⑤。
5. **现状缺陷 D-1**（真机门 G5a 主动登记，非误报）：行操作后的视图重取若失败，
   页面**不给** alert/「数据可能已过期」注记，旧数据静默继续显示（面板级读失败路径 G5 是有的，
   行级 patch 路径没有）。修法与 G5 同源，待下一批。

## 7. 仍开放（不得写成已完成）

- **真实凭据实测**：10 个产品的登录/领取仍全部未做（用户驱动）。本轮只证明接口与界面纪律，不证明上游可用。
- **M7-B** 登录两步契约：占位行生命周期（start 即建、失败/超时/取消删行）、`login.poll` 改凭据存在性探针、
  上游节奏（cline `slow_down` 累加、qoder 404=pending、zcode `poll_interval_sec`）下沉服务端。
- **M7-C** 扫码/短信型：QR 真渲染（现 `qr_payload` 仍是可复制文字串）、微信长轮询搬到服务端、
  阿里云滑块 param 经本机页回投（不引入 playwright）。
- **M7-D** zcode：`authorize_url` 的 `redirect` 改写为桥接页 + `state` 取服务端源 + 轮询/回调双通道赛跑
  （`oauth.rs:129-131` 注明不改写到不了回调）。
- **BD3b** `unservable_reason`、**BD5** 每账号持久化 `last_op`（含 ops 报告行补 `product`）未落地 →
  「转发未接线」横幅与「最近运营」列整块不显示（不硬编码、不假装有）。
- `resources.js` / `models.js` 仍自带内联 gutter，因此 ≤768 的 rail 修复**只到 accounts 页**；
  两页各自一行改动即可继承（已登记 M7-U4）。
- 真机门复跑截图超时（§3 末）未查因。
