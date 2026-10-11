# S-46（第二批）前端验收门 · 两个正式页面真跑 —— 交付记录

- 日期：2026-09-29　范围：**只改 `scripts/verify_v2_frontend.mjs` 一个文件**（另按纪律改了 `tests/integration/test_int_v2_frontend_gate.py` 的两处数量下限与 docstring 条数；`pages/*.js` / 后端 / `components.js` / `api.js` **零改动**，字节级复原见 §7）
- 对象：`model_gateway/web/static/js/pages/apiaccess.js`（M0~M9）+ `model_gateway/web/static/js/pages/settings.js`（M10~M17）
- 复用上一批共享层（`gate-s46-shared-layer.md`）：同一份 `SHARED_DOM` 假 DOM、同一套 `browserFn`/`__guard` realm 沙箱、同样的"场景先 await 跑完、判定同步做"口径；判据段用空闲的 **M 段**。
- 只跑了 `tests/integration/test_int_v2_frontend_gate.py`（主控要求，未跑全量 pytest）；**没有用浏览器/CDP**。

---

## 1. 结论（数字逐字复制自 runner 自己的输出）

```
实测 128 项，通过 128 项，失败 0 项
```

```
[变异自证] 基线 128 条全绿 → 施加 184 个源码变异
可红 184/184；每条断言都有对应变异
```

```
..                                                                       [100%]
2 passed in 45.82s
```

- 判据：**110 → 128**（新增 M0~M17 共 **18 条**）
- 变异：**145 → 184**（新增 **39 条**：38 条打两页源码 + 1 条 `self:true` 打门自己）
- 既有判据/变异：**一条未删、一条未削弱**；家族计数（由 `--json` 派生）
  `{"A":15,"B":7,"C":18,"D":3,"E":4,"F":7,"G":3,"H":2,"I":10,"J":3,"K":11,"L":22,"M":18,"Z":5}` 总数 128、errors 0、失败 0
  （既有 A~K + Z = 90 条与 L 段 22 条一字未动，M 段插在 L 与 Z 之间）
- 下限不是空过：把 `128/184` 临时改成 `999` 跑 pytest，两条都红（原样见 §9.1），随后**改回**。

命令（临时目录独立 `mktemp -d`，实得 `/tmp/mgw-s47.ULXnHi`；载荷由 `tests/integration/test_int_v2_frontend_gate.py::_overview_payload` 的真实装配产出）：

```
$ T=$(mktemp -d /tmp/mgw-s47.XXXXXX)
$ .venv/bin/python -c "… _overview_payload(Path('$T')) …"        # 真实端点产 overview.json
$ node scripts/verify_v2_frontend.mjs $T/overview.json            # 基线
$ node scripts/verify_v2_frontend.mjs $T/overview.json --notes    # 绿态读数（本批新加的旗标）
$ node scripts/verify_v2_frontend.mjs $T/overview.json --mutation # 变异自证
$ TDIR=$T node $T/red-evidence.mjs                                # 逐条红证（门的副本 + 独立 temp 树）
$ TDIR=$T node $T/red-evidence.mjs --combo 147 149 152 155 159 161     # 组合红证（API 接入 6 条）
$ TDIR=$T node $T/red-evidence.mjs --combo 166 168 171 174 175 177     # 组合红证（系统设置 6 条）
$ .venv/bin/python -m pytest tests/integration/test_int_v2_frontend_gate.py -q -p no:warnings
```

## 2. fixture：数据从**生产端点**取，不自己编字段名

fixture 由 `TestClient` 直接打生产路由取回（不启服务、不占 8300 端口）：

```python
app = create_app(config_path=…, usage_dir=…, enums_path=…)
with TestClient(app) as c:
    ov  = c.get("/admin/api/overview").json()   # → M 段的 OV.call_addresses（runner 收到的 argv 载荷里取，不写死）
    cfg = c.get("/admin/api/config").json()     # → CONFIG_FIXTURE，逐字段抄（含 resources[].api_key 的默认脱敏 "****"）
    b["gateway"]["request_total_budget_seconds"] = 1; c.put("/admin/api/config", json=b)   # → 400 原样回包
    b["gateway"]["access_tokens"].append({"id": "tok-1", …}); c.put(…)                     # → 另一条 400 原样回包
    新增密钥留空 id/value → PUT 200 → 再 GET 看服务端补齐出来的 tok-/mg- 形态
```

原样回包（逐字）：

```
PUT /admin/api/config（request_total_budget_seconds=1）→ 400
  {"status":"rejected","errors":["gateway: Value error, request_total_budget_seconds(1) 必须 >= attempt_timeout_seconds(60)（tech-design §4.7 ③）"]}
PUT /admin/api/config（两条 access_tokens 同 id）→ 400
  {"status":"rejected","errors":["Value error, gateway.access_tokens[].id 重复：'tok-1'"]}
PUT /admin/api/config（新增密钥 id/value 留空）→ 200 {"status":"ok","message":"配置已保存并生效"}
  再 GET → {"id":"tok-5ce164db","name":"Cherry Studio","value":"mg-f479eac9bfea00527e73b65696a6fe33","enabled":true,
            "quotas":{"daily_requests":0,"daily_tokens":0,"total_tokens":0}}
```

- **只有参数取值被改掉**：生产默认 x=2 与 y=2 同值、attempt_timeout=60 与 cooldown=60 同值 —— 同值时"两列绑反 / 取错字段"不可判别（M11 会空过，正是 K10 那条教训）。fixture 把 12 个参数改成互不相同：port 8300 / 并发 5 / 尝试超时 45 / 总预算 300 / 心跳 15 / 保留 7 天、x=2 y=3 m=4 退避 1.5 冷却 60 plan 18000。**键名、层级、可选字段、脱敏形态、models/resources 结构一律保持端点原样。**
- 假"服务端"（门内 `mEnv` 的 `fetch` 桩）按 **method + path** 分派，并且：
  ① GET 交**深拷贝**（页面的 `cfg` 与服务端状态从此是两个对象 → "PUT 有没有把改动带上""取消后数据没动"才真的可判）；
  ② PUT 真的落库，并按生产 `_autogen_ids`（`api/admin.py:460-479`）给空 id/value 补 `tok-`/`mg-`；
  ③ 残缺 body（没有 gateway/scheduling）按 400 拒绝而不是让假服务端自己抛（本批撞过一次，红了但归因糊在驱动器上）；
  ④ 未建模的路由一律 `404 {"errors":["无此端点：…"]}` → 端点写错会真红（同 K 段口径）。

## 3. 假 DOM 的四处增量（以及为什么不会削弱 L 段）

`SHARED_DOM` 只加不减；L 段 22 条 + 原有 145 条变异复跑全绿（§10 的 `可红 184/184` 含全部旧变异）。

| 增量 | 为什么页面真跑非有不可 | 对 L 段的影响 |
|---|---|---|
| `__match` 支持属性选择器（`[data-tk]` / `[data-sec]` / `[name=name]`，含**无引号值**） | 两页的行内绑定全靠它找控件（`apiaccess.js:98` `querySelectorAll("[data-tk]")`、`settings.js:77` `[data-sec]`、`apiaccess.js:184` `[name=name]`）；原先一律匹配不到 → "事件根本没绑上"在 realm 里被当成正常渲染 | 纯增分支，类/id/标签三分支一字未动 |
| 属性**反射**：`value` / `name` / `type` / `title` / `disabled` + `dataset` Proxy | `settings.js:88` 读 `input.name`、`apiaccess.js:116` 读 `btn.dataset.on`、`settings.js:67` 写 `#st-save.disabled`；原先只有 `__mk` 里几个写死的自有属性，解析出来的 `value="7"` / 裸 `disabled` / `data-tk="1"` 读不到。**`disabled` 恒 false 尤其致命** —— M12 的"徽章干净 ⇒ 按钮不可点"那个方向会永远失真 | `pagination` 的 `b.disabled`（L19）走同一个 setter/getter，读写一致；L 段其余场景不碰这些属性 |
| `el.prepend(...)` | `settings.js:74` 的脏态徽章正是 `pa.prepend(b)`；原先这行 TypeError → 徽章永远进不了 DOM（面板点名的那条恰好长在缺的那行上） | L 段没有 prepend 调用 |
| `__until` / `__follow` / `settle` 三个等待具 | 一次 D3 操作 = PUT + 两个 GET + 重渲染，固定 12 轮排不干。**等待口径改成"按可观察事实"**（行节点被换掉 / 徽章消失 / toast 落账）：本批第一次跑 M8 就是"请求刚发出就取样"，读到旧的两行 → 假阴性伪装成"页面坏了" | 新增，L 段未用 |

🔴 顺带把门的人读输出加了一个 `--notes` 旗标：绿态判据的 detail 默认不打印，而面板反复批评"零读数"——`--notes` 只额外打印 `id :: detail`，默认输出与 `--json`（变异自证用那条）一字未改。本批 §11 的绿态读数全部来自它。

## 4. 新增判据清单（id · 它在防什么 · 对应生产源码 `file:line`）

| id | 防的是什么事（页面级谎报形态） | 生产源码 file:line |
|---|---|---|
| M0 | API 接入页根本没跑起来 / 首屏端点写错（后端没这条路由 → 整屏空白）；7 个页内函数缺一个；**调用地址两块为空**（`esc(undefined)` 交空串，坏插值判据抓不到，见 §8-2） | `pages/apiaccess.js:24-28`、`41-53`、`77-78` |
| M1 | 密钥表**逐行取值身份**：行数与服务端不符、用途标注读到别条的名字、开关态与 `enabled` 反、停用行没置灰、缺删除/复制钮、卡头 `N/M 启用` 谎报成"全部启用" | `apiaccess.js:64-70`、`61`、`100-111`、`140-157` |
| M2 | 密钥值上屏不是密文（明文进值格 / 进序列化 HTML 的属性）。两处 `maskVal` 副本本身的口径由 L20 派生抽全部同名定义管（`apiaccess.js:19` / `resources.js:76`），M2 管的是**页面到底把什么写进了界面** | `apiaccess.js:19`、`147` |
| M3 | 眼睛按钮点开拿不到明文、图标与 `title` 不跟着换、收回后 DOM 仍留明文、点眼睛却发了请求 | `apiaccess.js:113-127` |
| M4 | 复制按钮把**密文**复制出去（粘到工具端即 401）；地址复制不是那条 URL；复制顺带发请求 | `apiaccess.js:95-96`、`128`、`149` |
| M5 | D3 启停没真落库：PUT 次数不对 / body 不是"改动后的完整配置"（只发增量、丢字段、改动没带上）/ 重渲染后界面与服务端、卡头不一致 / 后端已 200 却没有绿回执 | `apiaccess.js:31-39`、`107-111` |
| M6 | 启停遇到 400 时谎报成功（弹绿色「密钥已启用」）、红 toast 丢掉后端原因、失败后界面停在假状态 | `apiaccess.js:35-36`、`109` |
| M7 | 用途标注行内编辑不落库（PUT 发了、名字没变）/ 没有回执 / **改成同值也发全量 PUT** | `apiaccess.js:101-105` |
| M8 | 添加密钥：点「取消」也把密钥写进配置；点「生成并添加」没进 PUT；客户端自己编 id/value（抢走服务端 `_autogen_ids` 的契约）；新行没以密文出现、卡头计数没跟上 | `apiaccess.js:169-190` + 后端 `api/admin.py:460-479` |
| M9 | 删除密钥：取消 / ✕ / 遮罩任一支发出请求（点 ✕ 真的删了密钥）；**或调用方 promise 挂死**（挂死也是"零请求"，必须分开判 —— S-61 的教训）；确定分支 PUT 里没少那条 | `apiaccess.js:129-134` + `components.js:42-63` |
| M10 | 系统设置页根本没跑起来 / 首屏端点写错；三张卡少一张；「停止/重启网关」按钮丢失；已全站移除的「导出」复活 | `pages/settings.js:14-18`、`20-29`、`110-123` |
| M11 | 12 个参数输入框**绑错字段**（sec/name/value 三者对齐生产配置）、`min` 与 schema 下限不符、type 不是 number、多一个少一个框 | `settings.js:39-59`、`101-103` + 后端 `config/schemas.py:73-110` |
| M12 | 🔴 面板点名那条：**脏态徽章与保存按钮使能不同源** —— 少一行解禁 → 徽章照样显示、保存永远点不动；反向：没徽章却能点；徽章重复插两枚 / 没插在最前；三态（首屏 / 改一处 / 再改）逐一钉，并把页内 `dirty` 变量当第三条腿一起核 | `settings.js:24-25`、`65-75` |
| M13 | 正整数过滤死掉（负号/小数点/科学计数法都能键进去）；**清空被当成修改**（配置写成 null、置脏、发请求） | `settings.js:80-90` |
| M14 | 二段保存退化成一段（改一下就自动 PUT）；PUT body 不是"改动后的完整配置"；成功后没重渲染 / 没回到干净态 | `settings.js:174-181` |
| M15 | 保存失败（400 带 errors）却弹绿色「配置已保存并热重载生效」；红 toast 不带后端原因；失败后界面假装干净、把用户填的值吞掉 | `settings.js:180` + `api.js:8-14` |
| M16 | 维护区破坏性动作不需要确认就执行（取消也发 POST）；确认了却 POST 到别的端点；停止后没进「网关已停止」态；重启没进等待态 / 没绿回执 | `settings.js:126-142`、`162-172` |
| M17 | 两页**真跑产物**里有 `undefined` / `[object Object]` / 残留插值符（判产物，不判源码字面） | `apiaccess.js:61` / `settings.js:99-103` |

（M 段只钉"这一页有没有真跑起来、行为对不对"；用户可见文案的 http 黑话 / 英文枚举直出 / 指向不存在的页名仍由既有 J1/J2/J3/K4 管，**未重复**。）

## 5. 逐条红证（命令与原样输出，未做任何删减）

驱动器：`$T/red-evidence.mjs`（临时件，不入库）。**变异清单从门里 eval 出来**（`FILES` / `COMP_SRC` / `MUTATIONS` 三份都取门自己的），不另立第二份账；它把仓库入面文件复制到独立 temp 树、只施加一条变异、跑**门的副本**、打印变红行。

🔴 驱动器第一次跑踩过一个坑值得记：它只复制了具名 `FILES`，漏掉 `components.js`（那一个是 `walkFiles` 派生入面的）→ 树里没这个文件 → 门的 `FILES[COMP_SRC]` 是 undefined → `resolve` 抛 `paths[1] argument must be of type string` → L/M 整段 41 条一起"假红"。**红的是驱动器，不是门**。修法是复制面按门自己的发现口径重算一遍。

命令：`TDIR=$T node $T/red-evidence.mjs`（39 条 M 段变异逐条施加；最后一步还原全部变异复跑基线）

```
### 从门里 eval 出 M 段变异 39 条（总表 184 条）

#### M0 ← M0：API 接入页把 overview 端点写错（后端没这条路由 → 整屏空白，门却看不出）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：GET("/admin/api/config"), GET("/admin/api/overview")]);   →   GET("/admin/api/config"), GET("/admin/api/panel")]);
     变红：M0,M1,M2,M3,M4,M5,M6,M7,M8,M9
       ✗ M0 API 接入页能在 realm 里真跑：首屏发出的就是两条生产端点 GET（7 个页内函数齐备）  请求=["GET /admin/api/config","GET /admin/api/panel"]；页内函数 7/7；地址字段={"local":"http://127.0.0.1:8300/v1","lan":"http://192.168.31.102:8300/v1","lan_ip":"192.168.31.102"}；端点说明 0 条；表头 []；err=Error: 无此端点：/admin/api/panel；地址块=[]
       ✗ M1 API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数  2 行 / 2 条；卡头「undefined」；停用行 0 个；第0行：第 0 行不存在（当前共 0 行） | 第1行：第 1 行不存在（当前共 0 行） | 卡头计数=undefined，应以「1/2 启用」开头
       ✗ M2 API 接入：密钥值上屏只能是密文（前5+****+后4），整页序列化 HTML 连属性里都不许出现完整明文  2 行里 0 行是密文；样例「undefined」；序列化 HTML 11 字符；第0行 值格显示「undefined」应为密文「mg-a1****8f90」 | 第1行 值格显示「undefined」应为密文「mg-0f****e1f0」
       ✗ M3 API 接入：眼睛就地⇄收回（点开见明文+图标与 title 同向变；点回见密文且 DOM 不留明文；全程零请求）  realm 抛错 Error: 无此端点：/admin/api/panel
       ✗ M4 API 接入：复制写进剪贴板的必须是**明文**（密钥=完整 value、地址=URL 原文）并给回执，且复制本身零请求  realm 抛错 Error: 无此端点：/admin/api/panel
       ✗ M5 API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执  realm 抛错 Error: 无此端点：/admin/api/panel
       ✗ M6 API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态  realm 抛错 Error: 无此端点：/admin/api/panel
       ✗ M7 API 接入（D3 用途标注）：改名发**恰好一次** PUT 且 body 带新名 + 绿回执；改成同值不得再发请求  realm 抛错 Error: 无此端点：/admin/api/panel
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现  realm 抛错 Error: 无此端点：/admin/api/panel
       ✗ M9 API 接入（删除密钥）：取消 / ✕ / 遮罩三种关闭都要**调用方已返回且零请求**；确定才发一次 PUT 且 body 少一条  realm 抛错 Error: 无此端点：/admin/api/panel
       ✗ M0 API 接入页能在 realm 里真跑：首屏发出的就是两条生产端点 GET（7 个页内函数齐备）
       ✗ M1 API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数
       ✗ M2 API 接入：密钥值上屏只能是密文（前5+****+后4），整页序列化 HTML 连属性里都不许出现完整明文
       ✗ M3 API 接入：眼睛就地⇄收回（点开见明文+图标与 title 同向变；点回见密文且 DOM 不留明文；全程零请求）
       ✗ M4 API 接入：复制写进剪贴板的必须是**明文**（密钥=完整 value、地址=URL 原文）并给回执，且复制本身零请求
       ✗ M5 API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执
       ✗ M6 API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态
       ✗ M7 API 接入（D3 用途标注）：改名发**恰好一次** PUT 且 body 带新名 + 绿回执；改成同值不得再发请求
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现
       ✗ M9 API 接入（删除密钥）：取消 / ✕ / 遮罩三种关闭都要**调用方已返回且零请求**；确定才发一次 PUT 且 body 少一条

#### M1 ← M1：密钥表只渲染第一行（多密钥场景其余密钥静默消失）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：${tokens.map((t, i) => tokenRow(t, i)).join("")}   →   ${tokens.slice(0, 1).map((t, i) => tokenRow(t, i)).join("")}
     变红：M1,M2,M5,M6,M7,M8
       ✗ M1 API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数  2 行 / 2 条；卡头「1/2 启用 · 未配置密钥时 /v1 免鉴权放行」；停用行 0 个；第1行：第 1 行不存在（当前共 1 行）
       ✗ M2 API 接入：密钥值上屏只能是密文（前5+****+后4），整页序列化 HTML 连属性里都不许出现完整明文  2 行里 1 行是密文；样例「mg-a1****8f90」；序列化 HTML 5076 字符；第1行 值格显示「undefined」应为密文「mg-0f****e1f0」
       ✗ M5 API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执  realm 抛错 TypeError: Cannot read properties of undefined (reading 'querySelector')
       ✗ M6 API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态  realm 抛错 TypeError: Cannot read properties of undefined (reading 'querySelector')
       ✗ M7 API 接入（D3 用途标注）：改名发**恰好一次** PUT 且 body 带新名 + 绿回执；改成同值不得再发请求  realm 抛错 TypeError: Cannot read properties of undefined (reading 'querySelector')
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现  取消支：PUT 0 次 / 1 行 / 弹窗 0 层；确定支：PUT 1 次，body 3 条，服务端补齐 id=tok-9001，界面 1 行、新行「undefined」、卡头「2/3 启用 · 未配置密钥时 /v1 免鉴权放行」；点「取消」后表格变成 1 行 | 重渲染后行数=1 | 新行显示「undefined」应为密文「mg-10****ef01」
       ✗ M1 API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数
       ✗ M2 API 接入：密钥值上屏只能是密文（前5+****+后4），整页序列化 HTML 连属性里都不许出现完整明文
       ✗ M5 API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执
       ✗ M6 API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态
       ✗ M7 API 接入（D3 用途标注）：改名发**恰好一次** PUT 且 body 带新名 + 绿回执；改成同值不得再发请求
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现

#### M1 ← M1：卡头把「N/M 启用」谎报成「M/M 启用」（停用密钥看起来在用）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：${tokens.filter((t) => t.enabled !== false).length}/${tokens.length} 启用   →   ${tokens.length}/${tokens.length} 启用
     变红：M1,M8
       ✗ M1 API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数  2 行 / 2 条；卡头「2/2 启用 · 未配置密钥时 /v1 免鉴权放行」；停用行 1 个；卡头计数="2/2 启用 · 未配置密钥时 /v1 免鉴权放行"，应以「1/2 启用」开头
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现  取消支：PUT 0 次 / 2 行 / 弹窗 0 层；确定支：PUT 1 次，body 3 条，服务端补齐 id=tok-9001，界面 3 行、新行「mg-10****ef01」、卡头「3/3 启用 · 未配置密钥时 /v1 免鉴权放行」；卡头="3/3 启用 · 未配置密钥时 /v1 免鉴权放行"（新增那条 enabled=true、Cursor 那条仍是停用 → 应为 2/3）
       ✗ M1 API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现

#### M1 ← M1：开关初值取反（停用密钥看起来是开着的）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：append(switchEl(t.enabled !== false, async (next) => {   →   append(switchEl(t.enabled === false, async (next) => {
     变红：M1,M5,M6
       ✗ M1 API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数  2 行 / 2 条；卡头「1/2 启用 · 未配置密钥时 /v1 免鉴权放行」；停用行 1 个；第0行 开关态=false 应为 true（Trae） | 第1行 开关态=true 应为 false（Cursor）
       ✗ M5 API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执  请求 ["GET /admin/api/config","GET /admin/api/overview","PUT /admin/api/config","GET /admin/api/config","GET /admin/api/overview"]；PUT body 的第 2 条 enabled=false、顶层键 6 个；服务端=false；界面开关=true；卡头「1/2 启用 · 未配置密钥时 /v1 免鉴权放行」；toast ["密钥已停用（该密钥的调用将 401）"]；PUT body 与「改动后的完整配置」逐字段不一致（只发增量 / 丢字段 / 改动没带上都算） | 服务端那条仍是 enabled=false | 重渲染后值格还带停用样式：mono ellip tk-val off | 重渲染卡头="1/2 启用 · 未配置密钥时 /v1 免鉴权放行" | toast=[{"text":"密钥已停用（该密钥的调用将 401）","cls":"toast ok"}]
       ✗ M6 API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态  请求 ["GET /admin/api/config","GET /admin/api/overview","PUT /admin/api/config","GET /admin/api/config","GET /admin/api/overview"]；toast=[{"text":"保存失败：Value error, gateway.access_tokens[].id 重复：'tok-1'","cls":"toast err"}]；服务端 enabled=false；界面开关=true；失败后界面开关=true（应回落成关）
       ✗ M1 API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数
       ✗ M5 API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执
       ✗ M6 API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态

#### M2/M3 ← 🔴 M2：值格直接印明文（maskVal 调用被摘掉 —— 面板 ix B12-1 ④ 的页面版）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：${esc(maskVal(t.value))}   →   ${esc(t.value)}
     变红：M2,M3,M8
       ✗ M2 API 接入：密钥值上屏只能是密文（前5+****+后4），整页序列化 HTML 连属性里都不许出现完整明文  2 行里 0 行是密文；样例「mg-a1b2c3d4e5f60718293a4b5c6d7e8f90」；序列化 HTML 6917 字符；第0行 值格显示「mg-a1b2c3d4e5f60718293a4b5c6d7e8f90」应为密文「mg-a1****8f90」 | 第0行 值格就是明文本身 | 第0行 完整明文泄漏进序列化 DOM（含属性） | 第1行 值格显示「mg-0f1e2d3c4b5a69788796a5b4c3d2e1f0」应为密文「mg-0f****e1f0」 | 第1行 值格就是明文本身 | 第1行 完整明文泄漏进序列化 DOM（含属性）
       ✗ M3 API 接入：眼睛就地⇄收回（点开见明文+图标与 title 同向变；点回见密文且 DOM 不留明文；全程零请求）  密文「mg-a1b2c3d4e5f60718293a4b5c6d7e8f90」→ 明文「mg-a1b2c3d4e5f…」→ 密文「mg-a1****8f90」；图标换了 true/true；请求 ["GET /admin/api/config","GET /admin/api/overview"]；初始值格「mg-a1b2c3d4e5f60718293a4b5c6d7e8f90」不是密文
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现  取消支：PUT 0 次 / 2 行 / 弹窗 0 层；确定支：PUT 1 次，body 3 条，服务端补齐 id=tok-9001，界面 3 行、新行「mg-10002abcdef0123456789abcdef01」、卡头「2/3 启用 · 未配置密钥时 /v1 免鉴权放行」；新行显示「mg-10002abcdef0123456789abcdef01」应为密文「mg-10****ef01」
       ✗ M2 API 接入：密钥值上屏只能是密文（前5+****+后4），整页序列化 HTML 连属性里都不许出现完整明文
       ✗ M3 API 接入：眼睛就地⇄收回（点开见明文+图标与 title 同向变；点回见密文且 DOM 不留明文；全程零请求）
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现

#### M3 ← M3：眼睛点开拿不到明文（用户看不到完整密钥，复制流程随之断裂）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：span.textContent = t.value;   →   span.textContent = maskVal(t.value);
     变红：M3
       ✗ M3 API 接入：眼睛就地⇄收回（点开见明文+图标与 title 同向变；点回见密文且 DOM 不留明文；全程零请求）  密文「mg-a1****8f90」→ 明文「mg-a1****8f90…」→ 密文「mg-a1****8f90」；图标换了 true/true；请求 ["GET /admin/api/config","GET /admin/api/overview"]；点眼睛后值格「mg-a1****8f90」没变成明文
       ✗ M3 API 接入：眼睛就地⇄收回（点开见明文+图标与 title 同向变；点回见密文且 DOM 不留明文；全程零请求）

#### M3 ← M3：眼睛收不回（data-on 不写回，明文一直挂在屏幕上）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：btn.dataset.on = "";   →   btn.dataset.on = "1";
     变红：M3
       ✗ M3 API 接入：眼睛就地⇄收回（点开见明文+图标与 title 同向变；点回见密文且 DOM 不留明文；全程零请求）  密文「mg-a1****8f90」→ 明文「mg-a1b2c3d4e5f…」→ 密文「mg-a1****8f90」；图标换了 true/true；请求 ["GET /admin/api/config","GET /admin/api/overview"]；收回后 data-on="1" 应清空
       ✗ M3 API 接入：眼睛就地⇄收回（点开见明文+图标与 title 同向变；点回见密文且 DOM 不留明文；全程零请求）

#### M4 ← 🔴 M4：复制按钮复制的是密文（粘到工具端立刻 401，用户以为密钥坏了）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：copyText(t.value, "密钥已复制")   →   copyText(maskVal(t.value), "密钥已复制")
     变红：M4
       ✗ M4 API 接入：复制写进剪贴板的必须是**明文**（密钥=完整 value、地址=URL 原文）并给回执，且复制本身零请求  剪贴板收到 ["mg-a1****8f90","http://127.0.0.1:8300/v1","http://192.168.31.102:8300/v1"]；toast ["密钥已复制","已复制","已复制"]；密钥复制写进剪贴板的是「mg-a1****8f90」不是完整明文（前5+****+后4 那种密文复制出去不可用）
       ✗ M4 API 接入：复制写进剪贴板的必须是**明文**（密钥=完整 value、地址=URL 原文）并给回执，且复制本身零请求

#### M5 ← M5：启停改了本地对象却没写回（PUT body 仍是旧 enabled —— 界面翻了、后端没变）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：      t.enabled = next;
   →   
     变红：M5
       ✗ M5 API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执  请求 ["GET /admin/api/config","GET /admin/api/overview","PUT /admin/api/config","GET /admin/api/config","GET /admin/api/overview"]；PUT body 的第 2 条 enabled=false、顶层键 6 个；服务端=false；界面开关=false；卡头「1/2 启用 · 未配置密钥时 /v1 免鉴权放行」；toast ["密钥已启用"]；PUT body 与「改动后的完整配置」逐字段不一致（只发增量 / 丢字段 / 改动没带上都算） | 服务端那条仍是 enabled=false | 重渲染后开关视觉态=false 应为 on | 重渲染后值格还带停用样式：mono ellip tk-val off | 重渲染卡头="1/2 启用 · 未配置密钥时 /v1 免鉴权放行"
       ✗ M5 API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执

#### M5/M7 ← M5：persist 不再 PUT 全量配置（只发 gateway 一节，后端按全量校验会清掉其余字段）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：await PUT("/admin/api/config", cfg);   →   await PUT("/admin/api/config", { gateway: cfg.gateway });
     变红：M5,M7,M8,M9
       ✗ M5 API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执  请求 ["GET /admin/api/config","GET /admin/api/overview","PUT /admin/api/config","GET /admin/api/config","GET /admin/api/overview"]；PUT body 的第 2 条 enabled=true、顶层键 1 个；服务端=false；界面开关=false；卡头「1/2 启用 · 未配置密钥时 /v1 免鉴权放行」；toast ["保存失败：请求体须为完整配置对象（缺 gateway / scheduling）"]；PUT body 与「改动后的完整配置」逐字段不一致（只发增量 / 丢字段 / 改动没带上都算） | 服务端那条仍是 enabled=false | 重渲染后开关视觉态=false 应为 on | 重渲染后值格还带停用样式：mono ellip tk-val off | 重渲染卡头="1/2 启用 · 未配置密钥时 /v1 免鉴权放行" | toast=[{"text":"保存失败：请求体须为完整配置对象（缺 gateway / scheduling）","cls":"toast err"}] | 成功回执不是绿色样式：{"text":"保存失败：请求体须为完整配置对象（缺 gateway / scheduling）","cls":"toast err"}
       ✗ M7 API 接入（D3 用途标注）：改名发**恰好一次** PUT 且 body 带新名 + 绿回执；改成同值不得再发请求  原名="Trae" → PUT body 名字=Trae 改过；服务端="Trae"；同值新增请求=0；toast ["保存失败：请求体须为完整配置对象（缺 gateway / scheduling）"]；PUT body 不是改名后的完整配置 | 服务端存的名字="Trae" | 重渲染后输入框值="Trae" | toast=[{"text":"保存失败：请求体须为完整配置对象（缺 gateway / scheduling）","cls":"toast err"}]
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现  取消支：PUT 0 次 / 2 行 / 弹窗 0 层；确定支：PUT 1 次，body 3 条，服务端补齐 id=undefined，界面 2 行、新行「undefined」、卡头「1/2 启用 · 未配置密钥时 /v1 免鉴权放行」；重渲染后行数=2 | 服务端没补齐 id/value：{} | 新行显示「undefined」应为密文「」 | 卡头="1/2 启用 · 未配置密钥时 /v1 免鉴权放行"（新增那条 enabled=true、Cursor 那条仍是停用 → 应为 2/3） | toast=[{"text":"保存失败：请求体须为完整配置对象（缺 gateway / scheduling）","cls":"toast err"}]
       ✗ M9 API 接入（删除密钥）：取消 / ✕ / 遮罩三种关闭都要**调用方已返回且零请求**；确定才发一次 PUT 且 body 少一条  cancel/x/mask 的 promise 态=cancel:settled,x:settled,mask:settled；各自发出的请求数=0,0,0；确定支 ["PUT /admin/api/config","GET /admin/api/config","GET /admin/api/overview"]、body 剩 ["tok-2"]；重渲染后行数=2 | toast=[{"text":"保存失败：请求体须为完整配置对象（缺 gateway / scheduling）","cls":"toast err"}]
       ✗ M5 API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执
       ✗ M7 API 接入（D3 用途标注）：改名发**恰好一次** PUT 且 body 带新名 + 绿回执；改成同值不得再发请求
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现
       ✗ M9 API 接入（删除密钥）：取消 / ✕ / 遮罩三种关闭都要**调用方已返回且零请求**；确定才发一次 PUT 且 body 少一条

#### M6 ← 🔴 M6：启停遇到 400 也弹绿色「密钥已启用」（后端拒绝了，界面说成功）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：    toast("保存失败：" + e.message, "err");   →       toast(okMsg, "ok");
     变红：M6
       ✗ M6 API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态  请求 ["GET /admin/api/config","GET /admin/api/overview","PUT /admin/api/config","GET /admin/api/config","GET /admin/api/overview"]；toast=[{"text":"密钥已启用","cls":"toast ok"}]；服务端 enabled=false；界面开关=false；400 之后还弹绿色「密钥已启用」 | 失败 toast 不是红色样式：{"text":"密钥已启用","cls":"toast ok"} | 失败 toast 开头不是「保存失败」："密钥已启用" | 失败 toast 没带后端原因："密钥已启用"
       ✗ M6 API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态

#### M6 ← M6：失败 toast 丢掉后端原因（只剩一句「保存失败」，用户不知道改哪一行）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：    toast("保存失败：" + e.message, "err");   →       toast("保存失败", "err");
     变红：M6
       ✗ M6 API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态  请求 ["GET /admin/api/config","GET /admin/api/overview","PUT /admin/api/config","GET /admin/api/config","GET /admin/api/overview"]；toast=[{"text":"保存失败","cls":"toast err"}]；服务端 enabled=false；界面开关=false；失败 toast 开头不是「保存失败」："保存失败" | 失败 toast 没带后端原因："保存失败"
       ✗ M6 API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态

#### M7 ← M7：用途标注没写进配置（PUT 发了、名字没变 —— 行内编辑静默失效）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：      t.name = v;
   →   
     变红：M7
       ✗ M7 API 接入（D3 用途标注）：改名发**恰好一次** PUT 且 body 带新名 + 绿回执；改成同值不得再发请求  原名="Trae" → PUT body 名字=Trae；服务端="Trae"；同值新增请求=0；toast ["用途标注已更新"]；PUT body 不是改名后的完整配置 | 服务端存的名字="Trae" | 重渲染后输入框值="Trae"
       ✗ M7 API 接入（D3 用途标注）：改名发**恰好一次** PUT 且 body 带新名 + 绿回执；改成同值不得再发请求

#### M7 ← M7：改成同名也发全量 PUT（每次失焦都写盘一次）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：if (v === (t.name || "")) return;   →   if (false) return;
     变红：M7
       ✗ M7 API 接入（D3 用途标注）：改名发**恰好一次** PUT 且 body 带新名 + 绿回执；改成同值不得再发请求  原名="Trae" → PUT body 名字=Trae 改过；服务端="Trae 改过"；同值新增请求=3；toast ["用途标注已更新","用途标注已更新"]；toast=[{"text":"用途标注已更新","cls":"toast ok"},{"text":"用途标注已更新","cls":"toast ok"}] | 改成同名仍发了 3 次请求
       ✗ M7 API 接入（D3 用途标注）：改名发**恰好一次** PUT 且 body 带新名 + 绿回执；改成同值不得再发请求

#### M8 ← 🔴 M8：点「取消」也把密钥写进配置（取消钮接到新增逻辑上）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：  cancelBtn.onclick = () => m.close();   →     cancelBtn.onclick = async () => {
    cfg.gateway.access_tokens.push({ id: "", name: "误加", value: "", enabled: true });
    m.close(); await persist(root, "已生成密钥并生效"); };
     变红：M8
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现  取消支：PUT 1 次 / 3 行 / 弹窗 0 层；确定支：PUT 2 次，body 3 条，服务端补齐 id=tok-9001，界面 4 行、新行「mg-10****ef01」、卡头「3/4 启用 · 未配置密钥时 /v1 免鉴权放行」；点「取消」后发出 1 次 PUT | 点「取消」后表格变成 3 行 | 点「取消」却弹了 ["已生成密钥并生效"] | 确定支 PUT 发出 2 次 | 新增那条={"id":"","name":"误加","value":"","enabled":true}（id/value 该留空交服务端生成） | 重渲染后行数=4 | 卡头="3/4 启用 · 未配置密钥时 /v1 免鉴权放行"（新增那条 enabled=true、Cursor 那条仍是停用 → 应为 2/3） | toast=[{"text":"已生成密钥并生效","cls":"toast ok"},{"text":"已生成密钥并生效","cls":"toast ok"}]
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现

#### M8 ← M8：客户端自己编 id/value（抢走服务端 _autogen_ids 的契约，列表里的 id 与密钥从此不一致）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：cfg.gateway.access_tokens.push({ id: "", name, value: "", enabled: true });   →   cfg.gateway.access_tokens.push({ id: "tok-mine", name, value: "mg-mine-mine", enabled: true });
     变红：M8
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现  取消支：PUT 0 次 / 2 行 / 弹窗 0 层；确定支：PUT 1 次，body 3 条，服务端补齐 id=tok-mine，界面 3 行、新行「mg-mi****mine」、卡头「2/3 启用 · 未配置密钥时 /v1 免鉴权放行」；新增那条={"id":"tok-mine","name":"Cherry Studio","value":"mg-mine-mine","enabled":true}（id/value 该留空交服务端生成）
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现

#### M9 ← 🔴 M9：删除不看确认结果（点「取消」也真的把密钥删了）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：      if (!await confirmDialog("删除密钥",   →         if (false && await confirmDialog("删除密钥",
     变红：M9
       ✗ M9 API 接入（删除密钥）：取消 / ✕ / 遮罩三种关闭都要**调用方已返回且零请求**；确定才发一次 PUT 且 body 少一条  cancel/x/mask 的 promise 态=cancel:undefined,x:undefined,mask:undefined；各自发出的请求数=0,0,0；确定支 []、body 剩 []；cancel：点删除后没有弹确认框 | x：点删除后没有弹确认框 | mask：表里已经没有行了（rows=0，前面某一支把密钥删光了） | 确定：表里已经没有行了（rows=0，前面某一支把密钥删光了）
       ✗ M9 API 接入（删除密钥）：取消 / ✕ / 遮罩三种关闭都要**调用方已返回且零请求**；确定才发一次 PUT 且 body 少一条

#### M9 ← M9：确认删了、PUT 里却没少那条（弹窗关了就当成功）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：      cfg.gateway.access_tokens.splice(i, 1);   →         /* 变异：忘了真的删 */
     变红：M9
       ✗ M9 API 接入（删除密钥）：取消 / ✕ / 遮罩三种关闭都要**调用方已返回且零请求**；确定才发一次 PUT 且 body 少一条  cancel/x/mask 的 promise 态=cancel:settled,x:settled,mask:settled；各自发出的请求数=0,0,0；确定支 ["PUT /admin/api/config","GET /admin/api/config","GET /admin/api/overview"]、body 剩 ["tok-1","tok-2"]；PUT body 里剩 ["tok-1","tok-2"] | 重渲染后行数=2
       ✗ M9 API 接入（删除密钥）：取消 / ✕ / 遮罩三种关闭都要**调用方已返回且零请求**；确定才发一次 PUT 且 body 少一条

#### M10 ← M10：系统设置把配置端点写错（GET 404 → 整页空白）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：cfg = await GET("/admin/api/config");   →   cfg = await GET("/admin/api/conf");
     变红：M10,M11,M12,M13,M14,M15,M16
       ✗ M10 系统设置页能在 realm 里真跑：首屏发出的就是生产端点 GET /admin/api/config（三卡 + 启停钮都在）  请求=["GET /admin/api/conf"]；卡 []；输入 0 个；保存钮 disabled=null 文案「null」；徽章=false；重启=false 停止=false；err=Error: 无此端点：/admin/api/conf
       ✗ M11 系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）  对不上的 13 处 / 共 0 个绑定；x=undefined y=undefined m=undefined 退避=undefined；页面上 0 个参数输入，期望 12 个 | 缺输入框 gateway.port | 缺输入框 gateway.max_concurrent_requests | 缺输入框 gateway.attempt_timeout_seconds | 缺输入框 gateway.request_total_budget_seconds | 缺输入框 scheduling.max_active_per_model | 缺输入框 scheduling.fail_threshold | 缺输入框 scheduling.retry_per_request | 缺输入框 scheduling.retry_backoff_seconds | 缺输入框 scheduling.cooldown_seconds | 缺输入框 scheduling.cooldown_seconds_plan | 缺输入框 gateway.retention_days | 缺输入框 gateway.heartbeat_seconds
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）  realm 抛错 Error: 无此端点：/admin/api/conf
       ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）  realm 抛错 Error: 无此端点：/admin/api/conf
       ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态  realm 抛错 Error: 无此端点：/admin/api/conf
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏  realm 抛错 Error: 无此端点：/admin/api/conf
       ✗ M16 系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）  realm 抛错 Error: 无此端点：/admin/api/conf
       ✗ M10 系统设置页能在 realm 里真跑：首屏发出的就是生产端点 GET /admin/api/config（三卡 + 启停钮都在）
       ✗ M11 系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）
       ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）
       ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏
       ✗ M16 系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）

#### M10/M16 ← M10：维护区的「停止网关」按钮没了（系统运行控制失去唯一入口）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：<button class="btn btn-sm btn-danger" id="st-stop">停止网关</button>   →   
     变红：M10,M12,M13,M14,M15,M16
       ✗ M10 系统设置页能在 realm 里真跑：首屏发出的就是生产端点 GET /admin/api/config（三卡 + 启停钮都在）  请求=["GET /admin/api/config"]；卡 ["01 · 任务执行","02 · 系统日志","维护"]；输入 12 个；保存钮 disabled=true 文案「保存配置」；徽章=false；重启=true 停止=false；err=TypeError: Cannot set properties of null (setting 'onclick')
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）  realm 抛错 TypeError: Cannot set properties of null (setting 'onclick')
       ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）  realm 抛错 TypeError: Cannot set properties of null (setting 'onclick')
       ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态  realm 抛错 TypeError: Cannot set properties of null (setting 'onclick')
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏  realm 抛错 TypeError: Cannot set properties of null (setting 'onclick')
       ✗ M16 系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）  realm 抛错 TypeError: Cannot set properties of null (setting 'onclick')
       ✗ M10 系统设置页能在 realm 里真跑：首屏发出的就是生产端点 GET /admin/api/config（三卡 + 启停钮都在）
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）
       ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）
       ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏
       ✗ M16 系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）

#### M11 ← 🔴 M11：y 与 m 两个参数框绑反（用户调的是「连续失败阈值」，写的却是重试上限）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：num("y · 连续失败阈值", "scheduling", "fail_threshold", s.fail_threshold, 1)   →   num("y · 连续失败阈值", "scheduling", "retry_per_request", s.retry_per_request, 1)
     变红：M11,M12,M13,M14
       ✗ M11 系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）  对不上的 2 处 / 共 12 个绑定；x=2 y=4 m=4 退避=1.5；缺输入框 scheduling.fail_threshold | scheduling.retry_per_request 的 min=1，schema 下限是 0
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）  realm 抛错 TypeError: Cannot set properties of null (setting 'value')
       ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）  realm 抛错 TypeError: Cannot set properties of null (setting 'value')
       ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态  realm 抛错 TypeError: Cannot set properties of null (setting 'value')
       ✗ M11 系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）
       ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）
       ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态

#### M11 ← M11：字段名对、取的却是别的值（api 冷却框里印的是 plan 冷却）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：num("api 冷却（秒）", "scheduling", "cooldown_seconds", s.cooldown_seconds, 0)   →   num("api 冷却（秒）", "scheduling", "cooldown_seconds", s.cooldown_seconds_plan, 0)
     变红：M11
       ✗ M11 系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）  对不上的 1 处 / 共 12 个绑定；x=2 y=3 m=4 退避=1.5；scheduling.cooldown_seconds 框里是「18000」，配置里是 60
       ✗ M11 系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）

#### M11 ← M11：min 与 schema 下限不符（并发上限 0 = 不限，却被 HTML 拦成 ≥1）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：num("并发上限（0 = 不限）", "gateway", "max_concurrent_requests", g.max_concurrent_requests, 0)   →   num("并发上限（0 = 不限）", "gateway", "max_concurrent_requests", g.max_concurrent_requests, 1)
     变红：M11
       ✗ M11 系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）  对不上的 1 处 / 共 12 个绑定；x=2 y=3 m=4 退避=1.5；gateway.max_concurrent_requests 的 min=1，schema 下限是 0
       ✗ M11 系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）

#### M12 ← 🔴 M12：面板点名那条 —— markDirty 忘记解禁保存按钮（徽章照样显示，保存永远点不动）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：    root.querySelector("#st-save").disabled = false;
   →   
     变红：M12,M15
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）  首屏 徽章=false/disabled=true/dirty=false；改后 徽章=1 枚「有未保存修改」/disabled=true/dirty=true；再改 徽章=1/disabled=true；页头顺序 ["有未保存修改","保存配置"]；改动后 徽章=1 枚「有未保存修改」 按钮 disabled=true dirty=true —— 两者必须同时翻（徽章在而按钮灰 = 用户点不动；按钮可点而徽章不在 = 用户不知道有未保存修改） | 第二次改动后徽章=1 按钮 disabled=true
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏  toast=[{"text":"保存失败：gateway: Value error, request_total_budget_seconds(1) 必须 >= attempt_timeout_seconds(45)（tech-design §4.7 ③）","cls":"toast err"}]；服务端预算=300；界面值=1；脏态 徽章=true/disabled=true；失败后应仍是脏态：徽章=true disabled=true dirty=true
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏

#### M12/M14 ← M12：反向 —— 干净态按钮也可点（没有未保存修改也能 PUT 一次）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：<button class="btn btn-primary" id="st-save" ${dirty ? "" : "disabled"}>保存配置</button>   →   <button class="btn btn-primary" id="st-save">保存配置</button>
     变红：M12,M13,M14
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）  首屏 徽章=false/disabled=false/dirty=false；改后 徽章=1 枚「有未保存修改」/disabled=false/dirty=true；再改 徽章=1/disabled=false；页头顺序 ["有未保存修改","保存配置"]；首屏 徽章=false 按钮 disabled=false dirty=false（应为 false/true/false）
       ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）  过滤后「1239」；清空后 徽章=false/disabled=false；cooldown_seconds=60；页内 y=8；请求 ["GET /admin/api/config"]；清空被当成修改：徽章=false disabled=false dirty=false
       ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态  点保存前 PUT 0 次；点后 1 次，body 的 y=7、顶层键 6 个；服务端 y=7；界面 y=7；徽章=false/disabled=false；保存成功后 徽章=false disabled=false dirty=false（应回到干净态）
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）
       ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）
       ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态

#### M12 ← M12：改动后不插徽章（按钮可点、用户却不知道有未保存修改 —— 同源的另一半）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：      pa.prepend(b);   →         /* 变异：徽章忘了插 */;
     变红：M12,M15
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）  首屏 徽章=false/disabled=true/dirty=false；改后 徽章=0 枚「undefined」/disabled=false/dirty=true；再改 徽章=0/disabled=false；页头顺序 ["保存配置"]；改动后 徽章=0 枚「undefined」 按钮 disabled=false dirty=true —— 两者必须同时翻（徽章在而按钮灰 = 用户点不动；按钮可点而徽章不在 = 用户不知道有未保存修改） | 改动后徽章 0 枚 | 徽章没插到页头最前面 | 徽章文案=undefined | 第二次改动后徽章=0 按钮 disabled=false
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏  toast=[{"text":"保存失败：gateway: Value error, request_total_budget_seconds(1) 必须 >= attempt_timeout_seconds(45)（tech-design §4.7 ③）","cls":"toast err"}]；服务端预算=300；界面值=1；脏态 徽章=false/disabled=false；失败后应仍是脏态：徽章=false disabled=false dirty=true
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏

#### M13 ← M13：正整数过滤死掉（负号/小数点/科学计数法都能键进去）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：const clean = input.value.replace(/[^\d]/g, "");   →   const clean = input.value;
     变红：M13
       ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）  过滤后「12a3-.x9」；清空后 徽章=false/disabled=true；cooldown_seconds=60；页内 y=8；请求 ["GET /admin/api/config"]；键入「12a3-.x9」过滤后实得「12a3-.x9」（应为 1239）
       ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）

#### M13 ← M13：清空被当成修改（配置写成 null → 后端 400 或落盘坏值）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：      if (v == null || Number.isNaN(v)) return;
   →   
     变红：M13
       ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）  过滤后「1239」；清空后 徽章=true/disabled=false；cooldown_seconds=null；页内 y=8；请求 ["GET /admin/api/config"]；清空被当成修改：徽章=true disabled=false dirty=true | 配置里 cooldown_seconds 被写成 null
       ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）

#### M14 ← M14：二段保存退化成一段（改一下就自动 PUT，用户还没点保存配置就落盘）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：      cfg[sec][input.name] = v;
      markDirty();   →         cfg[sec][input.name] = v;
      markDirty();
      save(root);
     变红：M12,M14,M15
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）  首屏 徽章=false/disabled=true/dirty=false；改后 徽章=1 枚「有未保存修改」/disabled=false/dirty=true；再改 徽章=0/disabled=true；页头顺序 ["保存配置"]；第二次改动后徽章=0 按钮 disabled=true
       ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态  点保存前 PUT 1 次；点后 2 次，body 的 y=7、顶层键 6 个；服务端 y=7；界面 y=7；徽章=false/disabled=true；还没点保存就发了 1 次 PUT | 点保存后 PUT 2 次 | 请求序列=["GET /admin/api/config","PUT /admin/api/config","PUT /admin/api/config","GET /admin/api/config","GET /admin/api/config"] | toast=[{"text":"配置已保存并热重载生效","cls":"toast ok"},{"text":"配置已保存并热重载生效","cls":"toast ok"}]
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏  toast=[{"text":"保存失败：gateway: Value error, request_total_budget_seconds(1) 必须 >= attempt_timeout_seconds(45)（tech-design §4.7 ③）","cls":"toast err"},{"text":"保存失败：gateway: Value error, request_total_budget_seconds(1) 必须 >= attempt_timeout_seconds(45)（tech-design §4.7 ③）","cls":"toast err"}]；服务端预算=300；界面值=1；脏态 徽章=true/disabled=false；PUT 2 次 | toast 2 条：["保存失败：gateway: Value error, request_total_budget_seconds(1) 必须 >= attempt_timeout_seconds(45)（tech-design §4.7 ③）","保存失败：gateway: Value error, request_total_budget_seconds(1) 必须 >= attempt_timeout_seconds(45)（tech-design §4.7 ③）"]
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）
       ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏

#### M14 ← M14：保存只 PUT 被改那一节（其余字段被后端按默认值重建）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：await PUT("/admin/api/config", cfg);
    dirty = false;   →   await PUT("/admin/api/config", { scheduling: cfg.scheduling });
    dirty = false;
     变红：M14
       ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态  点保存前 PUT 0 次；点后 1 次，body 的 y=7、顶层键 1 个；服务端 y=3；界面 y=7；徽章=true/disabled=false；PUT body 不是「改动后的完整配置」（只发增量 / 丢字段 / 改动没带上都算） | 请求序列=["GET /admin/api/config","PUT /admin/api/config"] | 服务端 fail_threshold=3 | toast=[{"text":"保存失败：请求体须为完整配置对象（缺 gateway / scheduling）","cls":"toast err"}] | 保存成功后 徽章=true disabled=false dirty=true（应回到干净态）
       ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态

#### M15 ← 🔴 M15：后端 400 也弹绿色「配置已保存并热重载生效」（设置在页版的谎报形态）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：  } catch (e) { toast("保存失败：" + e.message, "err"); }   →     } catch (e) { toast("配置已保存并热重载生效", "ok"); }
     变红：M15
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏  toast=[{"text":"配置已保存并热重载生效","cls":"toast ok"}]；服务端预算=300；界面值=1；脏态 徽章=true/disabled=false；400 之后弹了绿色「已保存」 | 失败 toast 不是红色样式：{"text":"配置已保存并热重载生效","cls":"toast ok"} | 失败 toast 开头不是「保存失败」："配置已保存并热重载生效" | 失败 toast 没带后端原因："配置已保存并热重载生效"
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏

#### M15 ← M15：保存失败什么都不说（静默吞掉，用户以为已经保存）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：  } catch (e) { toast("保存失败：" + e.message, "err"); }   →     } catch { /* 变异：静默吞掉 */ }
     变红：M15
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏  toast=[]；服务端预算=300；界面值=1；脏态 徽章=true/disabled=false；toast 0 条：[] | 失败 toast 不是红色样式：{} | 失败 toast 开头不是「保存失败」：undefined | 失败 toast 没带后端原因：undefined
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏

#### M16 ← 🔴 M16：停止网关不看确认结果（点「取消」也把网关停了）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：    if (!await confirmDialog("停止网关",   →       if (false && await confirmDialog("停止网关",
     变红：M16
       ✗ M16 系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）  停止·取消 [] / promise undefined；停止·确定 [] 停止态=undefined；重启·确定 POST=["POST /admin/api/system/restart"] 等待态 opacity=.5 待触发定时器 2 个（恢复轮询不在判据内，见证据文档负面清单）；停止·取消：点停止网关后没有弹确认框 | 停止·确定：页面上已没有「停止网关」按钮，当前页面文本："网关已停止 管理界面已无法连接后端。需要重新启动时，请双击项目根目录的 （或终端执行 ），\n        启动后刷新本"
       ✗ M16 系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）

#### M16 ← M16：重启网关不看确认结果（点「取消」也把在途请求打断）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：    if (!await confirmDialog("重启网关",   →       if (false && await confirmDialog("重启网关",
     变红：M16
       ✗ M16 系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）  停止·取消 [] / promise settled；停止·确定 ["POST /admin/api/system/stop"] 停止态=true；重启·确定 POST=[] 等待态 opacity=undefined 待触发定时器 undefined 个（恢复轮询不在判据内，见证据文档负面清单）；重启：点重启网关后没有弹确认框
       ✗ M16 系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）

#### M16 ← M16：停止端点写错（POST 到不存在的路由，界面弹「停止失败」而用户以为已停止）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：await POST("/admin/api/system/stop");   →   await POST("/admin/api/system/stops");
     变红：M16
       ✗ M16 系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）  停止·取消 [] / promise settled；停止·确定 ["POST /admin/api/system/stops"] 停止态=false；重启·确定 POST=["POST /admin/api/system/restart"] 等待态 opacity=.5 待触发定时器 2 个（恢复轮询不在判据内，见证据文档负面清单）；停止·确定：发出了 ["POST /admin/api/system/stops"] | 停止·确定：页面没有进入「网关已停止」态 | 停止·确定：停止态之外还剩 3 张卡 | 停止·确定：额外弹了 [{"text":"停止失败：无此端点：/admin/api/system/stops","cls":"toast err"}]
       ✗ M16 系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）

#### M0 ← 🔴 M0：API 接入页把地址字段名打错 —— esc(undefined) 交空串，地址栏变成**一片空白**（不是 undefined，坏插值判据抓不到，只能正面钉）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：${addrPair("本机", addr.local)}   →   ${addrPair("本机", addr.loca)}
     变红：M0
       ✗ M0 API 接入页能在 realm 里真跑：首屏发出的就是两条生产端点 GET（7 个页内函数齐备）  请求=["GET /admin/api/config","GET /admin/api/overview"]；页内函数 7/7；地址字段={"local":"http://127.0.0.1:8300/v1","lan":"http://192.168.31.102:8300/v1","lan_ip":"192.168.31.102"}；端点说明 4 条；表头 ["用途标注","密钥","状态","操作"]；err=无；地址块=["","http://192.168.31.102:8300/v1"]
       ✗ M0 API 接入页能在 realm 里真跑：首屏发出的就是两条生产端点 GET（7 个页内函数齐备）

#### M1/M17 ← M17：卡头计数写成不存在的字段名（用户读到 1/undefined 启用）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：${tokens.filter((t) => t.enabled !== false).length}/${tokens.length} 启用   →   ${tokens.filter((t) => t.enabled !== false).length}/${tokens.lenght} 启用
     变红：M1,M5,M8,M17
       ✗ M1 API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数  2 行 / 2 条；卡头「1/undefined 启用 · 未配置密钥时 /v1 免鉴权放行」；停用行 1 个；卡头计数="1/undefined 启用 · 未配置密钥时 /v1 免鉴权放行"，应以「1/2 启用」开头
       ✗ M5 API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执  请求 ["GET /admin/api/config","GET /admin/api/overview","PUT /admin/api/config","GET /admin/api/config","GET /admin/api/overview"]；PUT body 的第 2 条 enabled=true、顶层键 6 个；服务端=true；界面开关=true；卡头「2/undefined 启用 · 未配置密钥时 /v1 免鉴权放行」；toast ["密钥已启用"]；重渲染卡头="2/undefined 启用 · 未配置密钥时 /v1 免鉴权放行"
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现  取消支：PUT 0 次 / 2 行 / 弹窗 0 层；确定支：PUT 1 次，body 3 条，服务端补齐 id=tok-9001，界面 3 行、新行「mg-10****ef01」、卡头「2/undefined 启用 · 未配置密钥时 /v1 免鉴权放行」；卡头="2/undefined 启用 · 未配置密钥时 /v1 免鉴权放行"（新增那条 enabled=true、Cursor 那条仍是停用 → 应为 2/3）
       ✗ M17 两页真跑产物里没有坏插值（undefined / [object Object] / 残留插值符）——判的是产物，不是源码字面  API 接入 7372 字符；系统设置 3469 字符；API 接入：出现 undefined —— 「不同密钥，便于区分调用。 接入密钥 1/undefined / pan class="value">1/undefined」
       ✗ M1 API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数
       ✗ M5 API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现
       ✗ M17 两页真跑产物里没有坏插值（undefined / [object Object] / 残留插值符）——判的是产物，不是源码字面

#### M11/M17 ← M17：系统设置把日志字段名打错（保留天数那格显示 undefined）
     文件：model_gateway/web/static/js/pages/settings.js
     种下：value="${g.retention_days}"   →   value="${g.retention_dayz}"
     变红：M11,M17
       ✗ M11 系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）  对不上的 1 处 / 共 12 个绑定；x=2 y=3 m=4 退避=1.5；gateway.retention_days 框里是「undefined」，配置里是 7
       ✗ M17 两页真跑产物里没有坏插值（undefined / [object Object] / 残留插值符）——判的是产物，不是源码字面  API 接入 7356 字符；系统设置 3477 字符；系统设置：出现 undefined —— 「ention_days" value="undefined"></input></di」
       ✗ M11 系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）
       ✗ M17 两页真跑产物里没有坏插值（undefined / [object Object] / 残留插值符）——判的是产物，不是源码字面

#### M0/M1/M2/M3/M4/M5/M6/M7/M8/M9/M10/M11/M12/M13/M14/M15/M16/M17 ← 🔴 门自己：M 段不再把页面源码编进 realm —— 页面判据失去对象（用的是共享层复制品）
     文件：scripts/verify_v2_frontend.mjs（门自己）
     种下：          + `${toModuleBody(read(COMPONENTS_KEY))}\n${mEnv(extra)}\n`
          + `${toModuleBody(read(fileKey))}\n`;   →             + `${toModuleBody(read(COMPONENTS_KEY))}\n${mEnv(extra)}\n`;
     变红：M0,M1,M2,M3,M4,M5,M6,M7,M8,M9,M10,M11,M12,M13,M14,M15,M16,M17
       ✗ M0 API 接入页能在 realm 里真跑：首屏发出的就是两条生产端点 GET（7 个页内函数齐备）  请求=[]；页内函数 0/7（缺：renderApiAccess,persist,draw,tokenRow,endpoint,addKeyModal,maskVal）；地址字段={"local":"http://127.0.0.1:8300/v1","lan":"http://192.168.31.102:8300/v1","lan_ip":"192.168.31.102"}；端点说明 0 条；表头 []；err=ReferenceError: renderApiAccess is not defined；地址块=[]
       ✗ M1 API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数  2 行 / 2 条；卡头「undefined」；停用行 0 个；第0行：第 0 行不存在（当前共 0 行） | 第1行：第 1 行不存在（当前共 0 行） | 卡头计数=undefined，应以「1/2 启用」开头
       ✗ M2 API 接入：密钥值上屏只能是密文（前5+****+后4），整页序列化 HTML 连属性里都不许出现完整明文  2 行里 0 行是密文；样例「undefined」；序列化 HTML 11 字符；第0行 值格显示「undefined」应为密文「mg-a1****8f90」 | 第1行 值格显示「undefined」应为密文「mg-0f****e1f0」
       ✗ M3 API 接入：眼睛就地⇄收回（点开见明文+图标与 title 同向变；点回见密文且 DOM 不留明文；全程零请求）  realm 抛错 ReferenceError: renderApiAccess is not defined
       ✗ M4 API 接入：复制写进剪贴板的必须是**明文**（密钥=完整 value、地址=URL 原文）并给回执，且复制本身零请求  realm 抛错 ReferenceError: renderApiAccess is not defined
       ✗ M5 API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执  realm 抛错 ReferenceError: renderApiAccess is not defined
       ✗ M6 API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态  realm 抛错 ReferenceError: renderApiAccess is not defined
       ✗ M7 API 接入（D3 用途标注）：改名发**恰好一次** PUT 且 body 带新名 + 绿回执；改成同值不得再发请求  realm 抛错 ReferenceError: renderApiAccess is not defined
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现  realm 抛错 ReferenceError: renderApiAccess is not defined
       ✗ M9 API 接入（删除密钥）：取消 / ✕ / 遮罩三种关闭都要**调用方已返回且零请求**；确定才发一次 PUT 且 body 少一条  realm 抛错 ReferenceError: renderApiAccess is not defined
       ✗ M10 系统设置页能在 realm 里真跑：首屏发出的就是生产端点 GET /admin/api/config（三卡 + 启停钮都在）  realm 编译/执行抛错 ReferenceError: dirty is not defined
       ✗ M11 系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）  realm 抛错 ReferenceError: dirty is not defined
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）  realm 抛错 ReferenceError: renderSettings is not defined
       ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）  realm 抛错 ReferenceError: renderSettings is not defined
       ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态  realm 抛错 ReferenceError: renderSettings is not defined
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏  realm 抛错 ReferenceError: renderSettings is not defined
       ✗ M16 系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）  realm 抛错 ReferenceError: renderSettings is not defined
       ✗ M17 两页真跑产物里没有坏插值（undefined / [object Object] / 残留插值符）——判的是产物，不是源码字面  API 接入 12 字符；系统设置 1 字符；系统设置：realm 抛错 ReferenceError: dirty is not defined
       ✗ M0 API 接入页能在 realm 里真跑：首屏发出的就是两条生产端点 GET（7 个页内函数齐备）
       ✗ M1 API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数
       ✗ M2 API 接入：密钥值上屏只能是密文（前5+****+后4），整页序列化 HTML 连属性里都不许出现完整明文
       ✗ M3 API 接入：眼睛就地⇄收回（点开见明文+图标与 title 同向变；点回见密文且 DOM 不留明文；全程零请求）
       ✗ M4 API 接入：复制写进剪贴板的必须是**明文**（密钥=完整 value、地址=URL 原文）并给回执，且复制本身零请求
       ✗ M5 API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执
       ✗ M6 API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态
       ✗ M7 API 接入（D3 用途标注）：改名发**恰好一次** PUT 且 body 带新名 + 绿回执；改成同值不得再发请求
       ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现
       ✗ M9 API 接入（删除密钥）：取消 / ✕ / 遮罩三种关闭都要**调用方已返回且零请求**；确定才发一次 PUT 且 body 少一条
       ✗ M10 系统设置页能在 realm 里真跑：首屏发出的就是生产端点 GET /admin/api/config（三卡 + 启停钮都在）
       ✗ M11 系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）
       ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）
       ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）
       ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态
       ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏
       ✗ M16 系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）
       ✗ M17 两页真跑产物里没有坏插值（undefined / [object Object] / 残留插值符）——判的是产物，不是源码字面

#### 还原全部变异后的基线：实测 128 项，通过 128 项，失败 0 项
```

## 6. 组合红证（同一页多条坏改动**同时**种下去）

### 6.1 API 接入页 6 条同时种：`TDIR=$T node $T/red-evidence.mjs --combo 147 149 152 155 159 161`

```
### 基线（未种任何变异）：实测 128 项，通过 128 项，失败 0 项
### 同时种进源码的坏改动 6 条：
  · 🔴 M1：卡头把「N/M 启用」谎报成「M/M 启用」（停用密钥看起来在用）
    文件 model_gateway/web/static/js/pages/apiaccess.js
    种下：${tokens.filter((t) => t.enabled !== false).length}/${tokens.length} 启用
    →  ${tokens.length}/${tokens.length} 启用
  · 🔴 🔴 M2：值格直接印明文（maskVal 调用被摘掉 —— 面板 ix B12-1 ④ 的页面版）
    文件 model_gateway/web/static/js/pages/apiaccess.js
    种下：${esc(maskVal(t.value))}
    →  ${esc(t.value)}
  · 🔴 🔴 M4：复制按钮复制的是密文（粘到工具端立刻 401，用户以为密钥坏了）
    文件 model_gateway/web/static/js/pages/apiaccess.js
    种下：copyText(t.value, "密钥已复制")
    →  copyText(maskVal(t.value), "密钥已复制")
  · 🔴 🔴 M6：启停遇到 400 也弹绿色「密钥已启用」（后端拒绝了，界面说成功）
    文件 model_gateway/web/static/js/pages/apiaccess.js
    种下：    toast("保存失败：" + e.message, "err");
    →      toast(okMsg, "ok");
  · 🔴 🔴 M8：点「取消」也把密钥写进配置（取消钮接到新增逻辑上）
    文件 model_gateway/web/static/js/pages/apiaccess.js
    种下：  cancelBtn.onclick = () => m.close();
    →    cancelBtn.onclick = async () => {
    cfg.gateway.access_tokens.push({ id: "", name: "误加", value: "", enabled: true });
    m.close(); await persist(root, "已生成密钥并生效"); };
  · 🔴 🔴 M9：删除不看确认结果（点「取消」也真的把密钥删了）
    文件 model_gateway/web/static/js/pages/apiaccess.js
    种下：      if (!await confirmDialog("删除密钥",
    →        if (false && await confirmDialog("删除密钥",
### 变红判据（共 7 条）：M1,M2,M3,M4,M6,M8,M9
### 其中新增 M 段：M1,M2,M3,M4,M6,M8,M9
### 其中**不属于**新增 M 段的既有判据：无（既有 110 条一条没红）
### 实测汇总行：实测 128 项，通过 121 项，失败 7 项
### 变红原文：
  ✗ M1 API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数  2 行 / 2 条；卡头「2/2 启用 · 未配置密钥时 /v1 免鉴权放行」；停用行 1 个；卡头计数="2/2 启用 · 未配置密钥时 /v1 免鉴权放行"，应以「1/2 启用」开头
  ✗ M2 API 接入：密钥值上屏只能是密文（前5+****+后4），整页序列化 HTML 连属性里都不许出现完整明文  2 行里 0 行是密文；样例「mg-a1b2c3d4e5f60718293a4b5c6d7e8f90」；序列化 HTML 6917 字符；第0行 值格显示「mg-a1b2c3d4e5f60718293a4b5c6d7e8f90」应为密文「mg-a1****8f90」 | 第0行 值格就是明文本身 | 第0行 完整明文泄漏进序列化 DOM（含属性） | 第1行 值格显示「mg-0f1e2d3c4b5a69788796a5b4c3d2e1f0」应为密文「mg-0f****e1f0」 | 第1行 值格就是明文本身 | 第1行 完整明文泄漏进序列化 DOM（含属性）
  ✗ M3 API 接入：眼睛就地⇄收回（点开见明文+图标与 title 同向变；点回见密文且 DOM 不留明文；全程零请求）  密文「mg-a1b2c3d4e5f60718293a4b5c6d7e8f90」→ 明文「mg-a1b2c3d4e5f…」→ 密文「mg-a1****8f90」；图标换了 true/true；请求 ["GET /admin/api/config","GET /admin/api/overview"]；初始值格「mg-a1b2c3d4e5f60718293a4b5c6d7e8f90」不是密文
  ✗ M4 API 接入：复制写进剪贴板的必须是**明文**（密钥=完整 value、地址=URL 原文）并给回执，且复制本身零请求  剪贴板收到 ["mg-a1****8f90","http://127.0.0.1:8300/v1","http://192.168.31.102:8300/v1"]；toast ["密钥已复制","已复制","已复制"]；密钥复制写进剪贴板的是「mg-a1****8f90」不是完整明文（前5+****+后4 那种密文复制出去不可用）
  ✗ M6 API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态  请求 ["GET /admin/api/config","GET /admin/api/overview","PUT /admin/api/config","GET /admin/api/config","GET /admin/api/overview"]；toast=[{"text":"密钥已启用","cls":"toast ok"}]；服务端 enabled=false；界面开关=false；400 之后还弹绿色「密钥已启用」 | 失败 toast 不是红色样式：{"text":"密钥已启用","cls":"toast ok"} | 失败 toast 开头不是「保存失败」："密钥已启用" | 失败 toast 没带后端原因："密钥已启用"
  ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现  取消支：PUT 1 次 / 3 行 / 弹窗 0 层；确定支：PUT 2 次，body 3 条，服务端补齐 id=tok-9001，界面 4 行、新行「mg-10002abcdef0123456789abcdef01」、卡头「4/4 启用 · 未配置密钥时 /v1 免鉴权放行」；点「取消」后发出 1 次 PUT | 点「取消」后表格变成 3 行 | 点「取消」却弹了 ["已生成密钥并生效"] | 确定支 PUT 发出 2 次 | 新增那条={"id":"","name":"误加","value":"","enabled":true}（id/value 该留空交服务端生成） | 重渲染后行数=4 | 新行显示「mg-10002abcdef0123456789abcdef01」应为密文「mg-10****ef01」 | 卡头="4/4 启用 · 未配置密钥时 /v1 免鉴权放行"（新增那条 enabled=true、Cursor 那条仍是停用 → 应为 2/3） | toast=[{"text":"已生成密钥并生效","cls":"toast ok"},{"text":"已生成密钥并生效","cls":"toast ok"}]
  ✗ M9 API 接入（删除密钥）：取消 / ✕ / 遮罩三种关闭都要**调用方已返回且零请求**；确定才发一次 PUT 且 body 少一条  cancel/x/mask 的 promise 态=cancel:undefined,x:undefined,mask:undefined；各自发出的请求数=0,0,0；确定支 []、body 剩 []；cancel：点删除后没有弹确认框 | x：点删除后没有弹确认框 | mask：表里已经没有行了（rows=0，前面某一支把密钥删光了） | 确定：表里已经没有行了（rows=0，前面某一支把密钥删光了）
  ✗ M1 API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数
  ✗ M2 API 接入：密钥值上屏只能是密文（前5+****+后4），整页序列化 HTML 连属性里都不许出现完整明文
  ✗ M3 API 接入：眼睛就地⇄收回（点开见明文+图标与 title 同向变；点回见密文且 DOM 不留明文；全程零请求）
  ✗ M4 API 接入：复制写进剪贴板的必须是**明文**（密钥=完整 value、地址=URL 原文）并给回执，且复制本身零请求
  ✗ M6 API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态
  ✗ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现
  ✗ M9 API 接入（删除密钥）：取消 / ✕ / 遮罩三种关闭都要**调用方已返回且零请求**；确定才发一次 PUT 且 body 少一条
```

### 6.2 系统设置页 6 条同时种：`TDIR=$T node $T/red-evidence.mjs --combo 166 168 171 174 175 177`

```
### 基线（未种任何变异）：实测 128 项，通过 128 项，失败 0 项
### 同时种进源码的坏改动 6 条：
  · 🔴 M11：字段名对、取的却是别的值（api 冷却框里印的是 plan 冷却）
    文件 model_gateway/web/static/js/pages/settings.js
    种下：num("api 冷却（秒）", "scheduling", "cooldown_seconds", s.cooldown_seconds, 0)
    →  num("api 冷却（秒）", "scheduling", "cooldown_seconds", s.cooldown_seconds_plan, 0)
  · 🔴 🔴 M12：面板点名那条 —— markDirty 忘记解禁保存按钮（徽章照样显示，保存永远点不动）
    文件 model_gateway/web/static/js/pages/settings.js
    种下：    root.querySelector("#st-save").disabled = false;

    →  
  · 🔴 M13：正整数过滤死掉（负号/小数点/科学计数法都能键进去）
    文件 model_gateway/web/static/js/pages/settings.js
    种下：const clean = input.value.replace(/[^\d]/g, "");
    →  const clean = input.value;
  · 🔴 M14：保存只 PUT 被改那一节（其余字段被后端按默认值重建）
    文件 model_gateway/web/static/js/pages/settings.js
    种下：await PUT("/admin/api/config", cfg);
    dirty = false;
    →  await PUT("/admin/api/config", { scheduling: cfg.scheduling });
    dirty = false;
  · 🔴 🔴 M15：后端 400 也弹绿色「配置已保存并热重载生效」（设置在页版的谎报形态）
    文件 model_gateway/web/static/js/pages/settings.js
    种下：  } catch (e) { toast("保存失败：" + e.message, "err"); }
    →    } catch (e) { toast("配置已保存并热重载生效", "ok"); }
  · 🔴 🔴 M16：停止网关不看确认结果（点「取消」也把网关停了）
    文件 model_gateway/web/static/js/pages/settings.js
    种下：    if (!await confirmDialog("停止网关",
    →      if (false && await confirmDialog("停止网关",
### 变红判据（共 6 条）：M11,M12,M13,M14,M15,M16
### 其中新增 M 段：M11,M12,M13,M14,M15,M16
### 其中**不属于**新增 M 段的既有判据：无（既有 110 条一条没红）
### 实测汇总行：实测 128 项，通过 122 项，失败 6 项
### 变红原文：
  ✗ M11 系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）  对不上的 1 处 / 共 12 个绑定；x=2 y=3 m=4 退避=1.5；scheduling.cooldown_seconds 框里是「18000」，配置里是 60
  ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）  首屏 徽章=false/disabled=true/dirty=false；改后 徽章=1 枚「有未保存修改」/disabled=true/dirty=true；再改 徽章=1/disabled=true；页头顺序 ["有未保存修改","保存配置"]；改动后 徽章=1 枚「有未保存修改」 按钮 disabled=true dirty=true —— 两者必须同时翻（徽章在而按钮灰 = 用户点不动；按钮可点而徽章不在 = 用户不知道有未保存修改） | 第二次改动后徽章=1 按钮 disabled=true
  ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）  过滤后「12a3-.x9」；清空后 徽章=false/disabled=true；cooldown_seconds=60；页内 y=8；请求 ["GET /admin/api/config"]；键入「12a3-.x9」过滤后实得「12a3-.x9」（应为 1239）
  ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态  点保存前 PUT 0 次；点后 1 次，body 的 y=7、顶层键 1 个；服务端 y=3；界面 y=7；徽章=true/disabled=true；PUT body 不是「改动后的完整配置」（只发增量 / 丢字段 / 改动没带上都算） | 请求序列=["GET /admin/api/config","PUT /admin/api/config"] | 服务端 fail_threshold=3 | 保存成功后 徽章=true disabled=true dirty=true（应回到干净态）
  ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏  toast=[{"text":"配置已保存并热重载生效","cls":"toast ok"}]；服务端预算=300；界面值=1；脏态 徽章=true/disabled=true；400 之后弹了绿色「已保存」 | 失败 toast 不是红色样式：{"text":"配置已保存并热重载生效","cls":"toast ok"} | 失败 toast 开头不是「保存失败」："配置已保存并热重载生效" | 失败 toast 没带后端原因："配置已保存并热重载生效" | 失败后应仍是脏态：徽章=true disabled=true dirty=true
  ✗ M16 系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）  停止·取消 [] / promise undefined；停止·确定 [] 停止态=undefined；重启·确定 POST=["POST /admin/api/system/restart"] 等待态 opacity=.5 待触发定时器 2 个（恢复轮询不在判据内，见证据文档负面清单）；停止·取消：点停止网关后没有弹确认框 | 停止·确定：页面上已没有「停止网关」按钮，当前页面文本："网关已停止 管理界面已无法连接后端。需要重新启动时，请双击项目根目录的 （或终端执行 ），\n        启动后刷新本"
  ✗ M11 系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）
  ✗ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）
  ✗ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）
  ✗ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态
  ✗ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏
  ✗ M16 系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）
```

两轮的结论行都是：**红的只有新增 M 段那几条，既有 110 条一条没红**。

🔴 组合选法上本批自己修正过一次：第一轮把变异 #165（y/m 两框绑反）放进了 settings 组合，结果 M12/M13/M14 的红是 `TypeError: Cannot set properties of null (setting 'value')` —— 因为 #165 把 `[name=fail_threshold]` 这个输入框整个换掉了，场景找不到它。**红是红了，但归因糊在"另一条变异顺手撞坏了现场"上**。换成 #166（字段名对、取错值）后六条各自红各自的，见 §6.2。

## 7. 复原证据（字节级 + 残渣）

红证与组合红证全程只在 `$T/tree/` 里改文件，**仓库源码一个字节没动**（门文件除外，那是本批的交付物）。

```
$ TDIR=$T node $T/red-evidence.mjs --combo            # 不种变异：把仓库入面文件重新同步进树
### 基线（未种任何变异）：实测 128 项，通过 128 项，失败 0 项
--- cmp：仓库 vs 重新同步的树（字节级复原确认） ---
OK 字节一致  model_gateway/web/static/js/pages/apiaccess.js
OK 字节一致  model_gateway/web/static/js/pages/settings.js
OK 字节一致  model_gateway/web/static/js/api.js
OK 字节一致  model_gateway/web/static/js/components.js
OK 字节一致  model_gateway/web/static/js/pages/resources.js
OK 字节一致  model_gateway/web/static/js/pages/models.js
OK 字节一致  model_gateway/web/static/js/pages/dashboard.js
OK 字节一致  model_gateway/web/static/js/main.js
OK 字节一致  model_gateway/api/admin.py
```

反证（证明"差在树里、不在仓库里"）：#165/#149/#152/#155/#159/#161 那批改动落在树上时，`diff $T/tree/…/apiaccess.js model_gateway/…/apiaccess.js` 的**左侧（树）**是坏改动、**右侧（仓库）**是正确代码，逐条对应：

```
36c36
<     toast(okMsg, "ok");
>     toast("保存失败：" + e.message, "err");
61c61
<         <span class="value">${tokens.length}/${tokens.length} 启用 · 未配置密钥时 /v1 免鉴权放行</span>
>         <span class="value">${tokens.filter((t) => t.enabled !== false).length}/${tokens.length} 启用 · 未配置密钥时 /v1 免鉴权放行</span>
128c128
<     row.querySelector("[data-cpykey]").onclick = () => copyText(maskVal(t.value), "密钥已复制");
>     row.querySelector("[data-cpykey]").onclick = () => copyText(t.value, "密钥已复制");
130c130
<       if (false && await confirmDialog("删除密钥",
>       if (!await confirmDialog("删除密钥",
147c147
<         <span class="mono ellip tk-val ${off ? "off" : ""}" data-tkval …>${esc(t.value)}</span>
>         <span class="mono ellip tk-val ${off ? "off" : ""}" data-tkval …>${esc(maskVal(t.value))}</span>
182,184c182
<   cancelBtn.onclick = async () => {
<     cfg.gateway.access_tokens.push({ id: "", name: "误加", value: "", enabled: true });
<     m.close(); await persist(root, "已生成密钥并生效"); };
>   cancelBtn.onclick = () => m.close();
```

残渣 grep（期望 0 命中）：

```
$ grep -rnE "if \(false\)|if \(false &&|tok-mine|addr\.loca[\"' ]|tokens\.lenght|retention_dayz|system/stops|admin/panel|admin/conf|误加|switchElRenamed|/\* 变异" \
      model_gateway/ --include="*.js" --include="*.py" | wc -l
0
```

（第一次跑这个 grep 出过 1 命中，是我的模式 `addr\.loca` 把正确代码里的 `addr.local` 当前缀吃进来了 —— 收紧成 `addr\.loca["' ]` 后为 0。记下来是因为这类"正则吃掉合法代码"正是本门反复批评的字面巧合。）

## 8. 与简报口径不符之处 / 发现的真缺陷（登记，未顺手改源码）

1. **`M` 段编号不连续的历史遗留**：简报说"M 段空闲，用 M0…Mn"。实际门里 L 段本批已被上一批的交付补了一条 **L21**（S-61），L 段共 22 条；M 段按简报从 M0 连续编到 M17，无冲突。
2. 🔴 **`esc(undefined)` 交出的是空串，不是字面 "undefined"**（`api.js:51-54` 的 `String(s ?? "")`）。后果：把 `${addrPair("本机", addr.local)}` 写成 `addr.loca` 时，调用地址那块**一片空白**，M17 那种"坏插值"判据**抓不到**。简报把"产物无坏插值"当成能覆盖这类错的手段，实测不成立。
   处理：把这个方向改由 **M0 正面钉**（两块 `data-copy` 必须非空且逐条等于后端 `call_addresses.local/.lan`），并配了一条专门打它的变异（#180，红行原样见 §5）。**顺带一个 UX 事实（非本批判据）**：字段名打错/后端少给字段时，用户看到的是"地址框空白"，没有任何提示 —— 建议下一批在源码侧对 `call_addresses` 缺失做显式降级文案。
3. **`maskVal` 仍是两份逐字重复的页内定义**（`apiaccess.js:19` / `resources.js:76`，不是共享导出）—— 与上一批 §5.1 同一事实，本批未动。M2 用"页面写进 DOM 的东西"这条正面判据补上了 `apiaccess` 那一侧的行为面；两份定义本身的口径仍由 L20 的目录派生抽全量把守（抽到 <2 处即红）。建议仍是什么：收进 `components.js` 单一出口。
4. 🔴 **`settings.js` 的 `bindMaint` / `draw` 没有 null 兜底**：变异把「停止网关」按钮那行删掉后，`root.querySelector("#st-restart").onclick` 之前的一行先抛 `TypeError: Cannot set properties of null (setting 'onclick')`，**整张设置页崩掉**（不是只有那个按钮没了）。这是"一个控件缺失 → 全页白屏"的耦合，属真实现状，不是判据写错。红行见 §5 的 M10/M16 那两条。**未改源码**，登记给下一批：要么在 `draw` 里对维护区控件做存在性判断，要么让这类缺失显式报错到界面上。
5. **`confirmDialog` 的 ✕/遮罩已会 settle(false)**（账本 S-61 一节所述，`components.js:48-61` 现状）—— 简报这条说法与代码一致 ✓。M9 因此能同时钉"三种关闭都零请求 **且调用方 promise 已返回**"；上一批只能钉到"✕ 不执行副作用"为止。
6. **`waitForRecovery` 的 30s 轮询在假定时器下不会推进**：`SHARED_DOM` 的 `setTimeout` 只登记不触发（`__timers` 计数可见）。M16 因此把重启判到"POST 恰好一次 + 绿回执 + 任务卡压暗 opacity=.5 + 定时器已排队"为止，**没有**判"恢复后自动重渲染"。简报未提这条约束，属实现现场的限制，写进负面清单 §9。

## 9. 我没能覆盖什么（负面清单）

1. **apiaccess.js**：`endpoint()` 只数了条数与文本（4 条端点说明），没判每条的三段结构（路径/名称/备注）绑得对不对；`tokenRow()` 里 `off` 样式在 `<td class>` 与 `<span class>` 两处只核了 td 那一处；`addKeyModal` 的表单提示文案没判；`.split-50` / `.addr-row` 的布局层结构没判（属 CSS/视觉面，归 CDP 那条面）。
2. **settings.js**：`logsSection` 的两句文件路径提示（`data/usage/events-*.jsonl` 等）只随产物干净度扫过，没逐条核；`execSection` 末尾那句校验提示文案没判；`stoppedState` 的恢复指引文案（「启动网关.command」）只核了"网关已停止"这个串；**`waitForRecovery` 的恢复成功支（GET /admin/api/status 通过后 toast「网关已重启恢复」+ 重渲染）完全没跑**（假定时器限制，见 §8-6）；重启失败支（POST 被拒 → 红 toast「重启失败：…」）也没喂过。
3. **数据形态没喂的**：`access_tokens` 为空数组（"暂无接入密钥"那个 empty 分支只断言了首屏有密钥时它**不在**）；单条密钥；`enabled` 字段缺失（undefined 视为启用）的密钥；`overview.call_addresses` 缺 `lan` 或整个缺失的降级；config 里 `gateway`/`scheduling` 缺节（本批只让假服务端拒绝，没让页面真跑）；`retry_backoff_seconds` 为 0.0（生产默认）时 `value="0"` 与"清空=未修改"的边界；后端 5xx（HTML 错误页）在这两页 persist/save 上的表现（共享层由 L3/L6 管，页面上只走了一次 400 JSON）。
4. **只钉了字面、没钉结构的**：M10 的三张卡标题（「01 · 任务执行」「02 · 系统日志」「维护」）是字符串比对；M17 的"坏插值"只看三种标记串（`undefined` / `[object Object]` / `${`），不判"该有值的地方是否为空"—— 后者只在调用地址那一处由 M0 补了（§8-2）。
5. **DOM 层面没判的**：`hidden`/`display:none` 之类"渲染了但看不见"在这一段不参与判定（可见性清洗只挂在 K 段的 HTML 路上，M 段判的是假 DOM 树里的 textContent/属性；样式表命中那条对本段未接）；事件委托（真实浏览器里 `onchange` 冒泡语义）在假 DOM 里是直接调用，不验证冒泡顺序。
6. 变异表里**没有"组合"条目**：组合红证是 §6 手工跑的，`kills` 仍只声明单条后果。
7. 未跑全量 pytest（主控在跑），只跑了 `tests/integration/test_int_v2_frontend_gate.py`；M 段不进浏览器，真 Chrome 里的剪贴板权限、弹窗观感、切换动效仍需 CDP 那条面交叉核对（本批按纪律没碰浏览器）。

## 9.1 下限不是空过（临时把 128/184 改成 999 的原样输出，随后已改回）

```
$ .venv/bin/python -m pytest tests/integration/test_int_v2_frontend_gate.py -q -p no:warnings
>       assert count >= 999, f"断言总数只剩 {count} 条（门被删窄也要能红）"
E       AssertionError: 断言总数只剩 128 条（门被删窄也要能红）
>       assert int(total) >= 999, f"变异表缩水到 {total} 条（每条判据都得配一个能打红的变异）"
E       AssertionError: 变异表缩水到 184 条（每条判据都得配一个能打红的变异）
2 failed in 39.96s
```

改回后的两处（本批对测试文件的**全部**改动 = 这两行数字 + docstring 里的条数）：

```
assert count >= 128, f"断言总数只剩 {count} 条（门被删窄也要能红）"
assert int(total) >= 184, f"变异表缩水到 {total} 条（每条判据都得配一个能打红的变异）"
```

## 10. 最后一次三连复验（全部改完后原样跑，逐字复制）

```
$ node scripts/verify_v2_frontend.mjs /tmp/mgw-s47.ULXnHi/overview.json
实测 128 项，通过 128 项，失败 0 项
$ node scripts/verify_v2_frontend.mjs /tmp/mgw-s47.ULXnHi/overview.json --mutation
[变异自证] 基线 128 条全绿 → 施加 184 个源码变异
可红 184/184；每条断言都有对应变异
$ .venv/bin/python -m pytest tests/integration/test_int_v2_frontend_gate.py -q -p no:warnings
2 passed in 45.82s
```

## 11. 绿态读数（`--notes` 原样输出，证明每条判据都有真数字）

```

[配置告警横幅]
  ✓ A1 渲染出 .alert-warn 横幅
  ✓ A2 文案透传：含 503
  ✓ A3 文案透传：含「未被任何系统模型引用」
  ✓ A4 含「已从 /v1/models …隐藏」（Q28-②）
  ✓ A5 两类隐藏说明各一句（零映射 + 不可服务）
  ✓ A6 含推理优先级说明「请求级」（Q28-③）
  ✓ A7 覆盖告警点名系统模型
  ✓ A8 覆盖告警给出两侧具体值
  ✓ A9 覆盖告警指到可操作页面
  ✓ A10 每条告警各渲染一条横幅
  ✓ A11 空 warnings → 不渲染任何横幅
  ✓ A12 warnings 非数组 → 安全降级不抛
  ✓ A13 四类 kind 各渲染一条（无被吞类别）
  ✓ A14 告警文案经 HTML 转义

[资源健康表]
  ✓ B1 表头有「最近错误」列（design-spec §2.1）
  ✓ B2 表头有「冷却剩余」列
  ✓ B3 熔断原因在 td 正文里（不能只在 title 属性）
  ✓ B4 冷却剩余带单位秒
  ✓ B5 无错误资源显示占位符而非空白

[配置告警横幅]
  ✓ A15 总览把**整份** warnings 交给渲染器（调用点不筛类别）

[资源健康表]
  ✓ B7 资源健康表逐行调用 statusBadge（不是硬编码徽章）
  ✓ B6 每行单元格数 = 表头列数（防空列错位）

[状态徽章四态]
  ✓ C1 active → 绿标 + 人话「可用」
  ✓ C2 cooldown → 冷却标 b-cool + 人话「冷却中」，**不得**说成「停用」
  ✓ C3 invalid（404 模型名无效）→ 红标 + 文案直说模型名无效 + 指对页面 + **不提换 Key**
  ✓ C17 未知档冷却徽章说「需人工确认」并指向「最近错误」列；普通冷却仍说「无需处理」
  ✓ C4 disabled → 文案「已停用」并在 title **同时给出两种成因与各自处置**（S-19 严重项）
  ✓ C9 四态文案无英文枚举残留（active/cooldown/invalid 不得直出）
  ✓ C5 四态的**样式类与文案**都互不相同（兜底分支不得吃掉冷却/失效）
  ✓ C6 cooldown 徽章带剩余秒数与恢复口径（多久回池、要不要动手）
  ✓ C7 未知状态原样显示（不静默归为正常）
  ✓ C10 未知状态用中性样式（不冒充判死）
  ✓ C11 冷却已到期（remaining=0）不说「剩余 0s」
  ✓ C18 冷却已到期（remaining=0）要说清「已到期 + 下次选路即回池」，不得残留倒计时或「还要等」口径
  ✓ C12 徽章 title 与「冷却剩余」列用同一个格式化口径
  ✓ C13 非 cooldown 的行「冷却剩余」列一律显示 —（不与徽章打架）
  ✓ C14 未知状态文案里保留原值且用中性样式（已含在 C7/C10，此处钉 title 说明）
  ✓ C15 冷却剩余一律**向上取整**（不得把未满一秒报成 0s，也不得截短）
  ✓ C16 徽章只由 status + 冷却时长决定（按其它字段/按量级分叉即判红）
  ✓ C8 cooldown 且剩余 0ms 时不得归正为绿标

[资源编辑器字段继承]
  ✓ D1 promoteKeyDraft 存在
  ✓ D2 新增 Key 继承 product（漏传会被后端默认成空 = 静默丢字段）
  ✓ D3 同组字段一并继承（vendor/preset/access_mode/protocol）

[顶栏红点 DOM 契约]
  ✓ E1 存在 #ops-dot 元素
  ✓ E2 默认 hidden（0 失败时不显示）
  ✓ E3 存在文案节点 #ops-dot-text
  ✓ E4 红点 title 与副作用一致（说「确认」不说「查看」）

[红点轮询与副作用]
  ✓ F1 轮询 /admin/api/status
  ✓ F2 读取 ops_failed_unread
  ✓ F3 5s 轮询间隔
  ✓ F4 页面隐藏时跳过轮询
  ✓ F5 已导入 GET（否则运行时报错）
  ✓ F6 红点按计数显隐（两个方向都写）
  ✓ F7 点击红点真的 POST 确认（不是只弹提示）

[红点行为（执行真代码）]
  ✓ I0 能抽取红点逻辑整块（抽不到=结构被改，本节后继判据失去意义）
  ✓ I1 有未读失败 → 红点去 hidden 并写明条数
  ✓ I2 无未读 → 红点保持 hidden
  ✓ I3 轮询打的是 /admin/api/status 且读 ops_failed_unread
  ✓ I4 轮询间隔 5000ms
  ✓ I5 页面隐藏时不发请求
  ✓ I6 点击 = 确认（POST ack）且立即隐藏红点
  ✓ I7 点击后给出去看明细与重跑的真实指路
  ✓ I8 红点元素不存在时静默跳过（首屏未就绪不得抛错）
  ✓ I9 未经点击绝不 POST 确认（否则每 5s 自动吞掉用户的失败）

[红点文案与指路]
  ✓ G1 toast 把副作用说成「重跑」而不是「查看详情」
  ✓ G2 指到已落盘的逐条原因（ops-results jsonl）
  ✓ G3 给出未装 mgw 时的等价命令

[红点样式]
  ✓ H1 .ops-dot 样式存在
  ✓ H2 用双主题令牌（--err-bg），不写死颜色

[页名与导航同源]
  ✓ J1 侧栏标签与路由注入的页标题同源（PAGE_META.title === 侧栏 <span>）
  ✓ J2 可见文案里出现的「X」页都是真实导航项（页名改版不留旧指路）
  ✓ J3 「到 X 页做 Y」的指路：Y 的控件必须真的长在 X 页的实现文件里（归属派生）

[整页装配可达性]
  ✓ K0 能执行真实 renderDashboard（执行不了=本段判据失去对象）
  ✓ K7 页面请求的就是后端真实存在的 `/admin/api/overview`（第九轮 B-1）
  ✓ K1 每条告警都作为**可见文本**出现在横幅里（注释掉/藏起来/塞进 title 都要红）
  ✓ K2 资源健康表真的挂进页面且**可见**（表头 + 数据行）
  ✓ K3 八张指标卡全部**可见**（此前指标卡零覆盖，display:none 也算藏）
  ✓ K8 趋势图真画进**可见**容器（删调用/把容器压成 height:0 都要红，第九轮 B-6 + 第十轮 B10-5）
  ✓ K4 页面产出的每个链接都指向真实导航项，且**没有任何外部链接**
  ✓ K5 页面**产出了内容**且没有坏插值（undefined / [object Object] / 残留 ${）
  ✓ K9 后端下发的原文经页面转义（`<script>` 不得原样出现在产出里，第九轮 B-5）
  ✓ K6 恢复时刻落在**「最近错误」那一列**且肉眼可见（第九轮 B-7：不许搬到别的列）
  ✓ K10 逐行核：「连续失败」= 该行 C、「处理中」= 该行 in_flight（对调即红）

[共享行为层真跑（api.js + components.js · S-46）]
  ✓ L0 共享层能在 realm 里编译并真跑（12 个导出齐备；编不过/少导出 = L 段判据失去对象）
  ✓ L1 成功路径返回**后端那份数据**（2xx JSON 原样交出，不是 null / 不是 HTTP 串）
  ✓ L2 四类后端错误形态的原因都被带进 Error.message（errors[] / error.message / message / detail）
  ✓ L3 !resp.ok 一律 reject（4xx/5xx 绝不允许被当成成功返回数据）
  ✓ L4 网络异常（fetch reject）原样抛出，不得吞成 null/undefined 让界面以为成功
  ✓ L5 后端回 400 时界面只有红色「保存失败」并带后端原因，绿色「配置已保存并热重载生效」必须消失
  ✓ L6 非 JSON 的 4xx/5xx（网关 HTML 错误页）仍 reject 并给出 HTTP 状态口径
  ✓ L7 非 JSON 的 2xx → 返回 null（不得凭空造 {} 让调用方以为拿到了配置）
  ✓ L8 GET/POST/PUT 的 HTTP 语义真的带出去（method + JSON 序列化 + Content-Type）
  ✓ L9 确认弹窗点「取消」：不执行副作用（DELETE_SENT 一次都没有）+ 弹窗关掉 + 给出答复
  ✓ L10 确认弹窗点「确定」：副作用**恰好一次**（确认不得被吞掉），弹窗关掉
  ✓ L21 确认弹窗经 ✕ / 遮罩关闭也必须 settle 并答复「取消」（副作用零次、弹窗关掉）
  ✓ L11 copyText 成功：写进剪贴板的正是那段明文，toast 文案与 ok 样式同源
  ✓ L12 剪贴板写入被拒（权限/非安全上下文）：toast 只能说不一致的口径，不得报「已复制」
  ✓ L13 navigator.clipboard 不存在时**绝不谎报已复制**（没有任何真实写入路径就不许弹成功）
  ✓ L14 modal 标题走 esc：title 里的 <script> 不得成为真元素（管理台注入面）
  ✓ L15 modal 的 footer 子节点**平铺**进 .modal-foot（Q21 间距根修：整块 append 会让 gap 失效）
  ✓ L16 modal 关闭三通道：X 按钮关、点遮罩关（并回调 onClose）、点弹窗内部**不关**
  ✓ L17 switchEl：保存成功（onToggle 返回 true）才翻视觉，返回 false 必须回滚（D3 操作即保存）
  ✓ L18 tabBar：选中态唯一，且回调收到**被点的那个** tab id
  ✓ L19 pagination：首页禁「‹」/末页禁「›」，点「›」交出下一页 offset
  ✓ L20 maskVal：每处定义都输出「前5+****+后4」密文，DOM 文本里不得出现完整明文

[两个正式页面真跑（apiaccess.js + settings.js · S-46 第二批）]
  ✓ M0 API 接入页能在 realm 里真跑：首屏发出的就是两条生产端点 GET（7 个页内函数齐备）
  ✓ M1 API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数
  ✓ M2 API 接入：密钥值上屏只能是密文（前5+****+后4），整页序列化 HTML 连属性里都不许出现完整明文
  ✓ M3 API 接入：眼睛就地⇄收回（点开见明文+图标与 title 同向变；点回见密文且 DOM 不留明文；全程零请求）
  ✓ M4 API 接入：复制写进剪贴板的必须是**明文**（密钥=完整 value、地址=URL 原文）并给回执，且复制本身零请求
  ✓ M5 API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执
  ✓ M6 API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态
  ✓ M7 API 接入（D3 用途标注）：改名发**恰好一次** PUT 且 body 带新名 + 绿回执；改成同值不得再发请求
  ✓ M8 API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现
  ✓ M9 API 接入（删除密钥）：取消 / ✕ / 遮罩三种关闭都要**调用方已返回且零请求**；确定才发一次 PUT 且 body 少一条
  ✓ M10 系统设置页能在 realm 里真跑：首屏发出的就是生产端点 GET /admin/api/config（三卡 + 启停钮都在）
  ✓ M11 系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）
  ✓ M12 系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）
  ✓ M13 系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）
  ✓ M14 系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态
  ✓ M15 系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏
  ✓ M16 系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）
  ✓ M17 两页真跑产物里没有坏插值（undefined / [object Object] / 残留插值符）——判的是产物，不是源码字面

[门自身判据自测]
  ✓ Z1 可见性判据 = **内联属性 ⊕ 样式表命中**（`.hidden` 这类工具类按 base.css 算隐藏）
  ✓ Z2 执行环境不含 Node 专有全局（名集由宿主派生；派生集本身带 canary）
  ✓ Z5 跨 realm 桥封死：注入面与返回值上的可达函数都不带宿主 realm（覆盖集由 INJECTED 派生）
  ✓ Z4 样式表派生自测：@media/@supports/@layer 的隐藏要进集合；@keyframes/伪元素/后代裸标签不能进
  ✓ Z3 页面函数对全部判据输入**未抛错、未留下未处理的拒绝**（不许用崩溃冒充证据）

========================================================
实测 128 项，通过 128 项，失败 0 项

[读数明细 --notes]
  ✓ A1 :: (空)
  ✓ A2 :: (空)
  ✓ A3 :: (空)
  ✓ A4 :: (空)
  ✓ A5 :: 命中 2
  ✓ A6 :: (空)
  ✓ A7 :: (空)
  ✓ A8 :: (空)
  ✓ A9 :: (空)
  ✓ A10 :: banners=4 warnings=4
  ✓ A11 :: (空)
  ✓ A12 :: (空)
  ✓ A13 :: banners=4/4
  ✓ A14 :: (空)
  ✓ B1 :: (空)
  ✓ B2 :: (空)
  ✓ B3 :: ZCode 风控熔断（30min，全局），至 19:54
  ✓ B4 :: (空)
  ✓ B5 :: (空)
  ✓ A15 :: (空)
  ✓ B7 :: (空)
  ✓ B6 :: 行=2 列=6 每行单元格=6,6
  ✓ C1 :: <span class="badge b-ok" title="可承接请求">可用</span>
  ✓ C2 :: <span class="badge b-cool" title="61s 后自动回池，无需处理">冷却中</span>
  ✓ C3 :: <span class="badge b-err" title="上游回 404：该模型名无效 —— 到「模型资源」页更换映射（不会自愈）">模型名无效</span>
  ✓ C17 :: 未知档=120s 后暂时回池；熔断状态文件读不动，需人工确认 —— 见「最近错误」列；普通档=61s 后自动回池，无需处理
  ✓ C4 :: <span class="badge b-muted" title="两种成因之一：资源开关已关闭（打开即恢复），或凭据被上游拒绝 401（需到「模型资源」页更换 Key，不会自愈）—— 见「最近错误」列">已停用</span>
  ✓ C9 :: {"active":"<span class=\"badge b-ok\" title=\"可承接请求\">可用</span>","cooldown":"<span class=\"badge b-cool\" title=\"61s 后自动回池，无需处理\">冷却中</span>","invalid":"<span class=\"badge b-err\" title=\"上游回 404：该模型名无效 —— 到「模型资源」页更换映射（不会自愈）\">模型名无效</span>","disabled":"<span class=\"badge b-muted\" title=\"两种成因之一：资源开关已关闭（打开即恢复），或凭据被上游拒绝 401（需到「模型资源」页更换 Key，不会自愈）—— 见「最近错误」列\">已停用</span>"}
  ✓ C5 :: {"active":"<span class=\"badge b-ok\" title=\"可承接请求\">可用</span>","cooldown":"<span class=\"badge b-cool\" title=\"61s 后自动回池，无需处理\">冷却中</span>","invalid":"<span class=\"badge b-err\" title=\"上游回 404：该模型名无效 —— 到「模型资源」页更换映射（不会自愈）\">模型名无效</span>","disabled":"<span class=\"badge b-muted\" title=\"两种成因之一：资源开关已关闭（打开即恢复），或凭据被上游拒绝 401（需到「模型资源」页更换 Key，不会自愈）—— 见「最近错误」列\">已停用</span>"}
  ✓ C6 :: <span class="badge b-cool" title="61s 后自动回池，无需处理">冷却中</span>
  ✓ C7 :: (空)
  ✓ C10 :: (空)
  ✓ C11 :: (空)
  ✓ C18 :: 已到期，下次选路即回池
  ✓ C12 :: (空)
  ✓ C13 :: (空)
  ✓ C14 :: (空)
  ✓ C15 :: 1799999→1800s 61001→62s 1→1s 0→—
  ✓ C16 :: {"active":"<span class=\"badge b-ok\" title=\"可承接请求\">可用</span>","cooldown":"<span class=\"badge b-cool\" title=\"61s 后自动回池，无需处理\">冷却中</span>","invalid":"<span class=\"badge b-err\" title=\"上游回 404：该模型名无效 —— 到「模型资源」页更换映射（不会自愈）\">模型名无效</span>","disabled":"<span class=\"badge b-muted\" title=\"两种成因之一：资源开关已关闭（打开即恢复），或凭据被上游拒绝 401（需到「模型资源」页更换 Key，不会自愈）—— 见「最近错误」列\">已停用</span>"}
  ✓ C8 :: (空)
  ✓ D1 :: (空)
  ✓ D2 :: (空)
  ✓ D3 :: (空)
  ✓ E1 :: (空)
  ✓ E2 :: (空)
  ✓ E3 :: (空)
  ✓ E4 :: <button class="ops-dot" id="ops-dot" hidden title="运营任务有失败 · 点击确认（逐条原因见 data/usage/ops-results-*.jsonl）">
  ✓ F1 :: (空)
  ✓ F2 :: (空)
  ✓ F3 :: (空)
  ✓ F4 :: (空)
  ✓ F5 :: (空)
  ✓ F6 :: (空)
  ✓ F7 :: (空)
  ✓ I0 :: (空)
  ✓ I1 :: (空)
  ✓ I2 :: (空)
  ✓ I3 :: (空)
  ✓ I4 :: (空)
  ✓ I5 :: (空)
  ✓ I6 :: (空)
  ✓ I7 :: (空)
  ✓ I8 :: (空)
  ✓ I9 :: (空)
  ✓ G1 :: (空)
  ✓ G2 :: (空)
  ✓ G3 :: (空)
  ✓ H1 :: (空)
  ✓ H2 :: (空)
  ✓ J1 :: nav=7 meta=7 dashboard:✓,resources:✓,models:✓,stats:✓,logs:✓,apiaccess:✓,settings:✓
  ✓ J2 :: 违规指路：无 指路总数：model_gateway/enums/matcher.py:1,model_gateway/web/static/js/pages/dashboard.js:1,model_gateway/web/static/js/pages/models.js:1,model_gateway/web/static/js/pages/settings.js:1,model_gateway/core/resources.py:3,model_gateway/cli_setup.py:1 ｜入面文件=79
  ✓ J3 :: 派生命中 6 条指路；归属全部对得上
  ✓ K0 :: (空)
  ✓ K7 :: 源码含端点=true err=
  ✓ K1 :: 横幅节点=4 期望=4 正文缺失=0
  ✓ K2 :: rows=5 冷却中=true
  ✓ K3 :: (空)
  ✓ K8 :: 容器属性= style="height:160px" 元素数=73
  ✓ K4 :: 内部 1 条；外链 0 条
  ✓ K5 :: (空)
  ✓ K9 :: err= 含转义=true
  ✓ K6 :: 表头=资源,状态,连续失败,处理中,冷却剩余,最近错误 最近错误列=ZCode 风控熔断（30min，全局），至 19:54  冷却剩余列=1800s  串列=0
  ✓ K10 :: 可判别 1/4 行；逐行对得上
  ✓ L0 :: 导出 12/12；全部为函数
  ✓ L1 :: 200-json → rejected=false got={"hello":"world","n":7}
  ✓ L2 :: 四类形态逐条对上
  ✓ L3 :: 六种失败响应：400-errors→reject 401-obj→reject 409-msg→reject 422-detail→reject 500-html→reject network→reject
  ✓ L4 :: network → rejected=true msg=Failed to fetch got=NO-RESULT
  ✓ L5 :: outcome=err toasts=[{"text":"保存失败：rid 重复：res-a","cls":"toast err"}]
  ✓ L6 :: 500-html → rejected=true msg=HTTP 500 got=NO-RESULT
  ✓ L7 :: 204-nonjson → got=null rejected=false
  ✓ L8 :: 实际发出的请求：[{"p":"/admin/api/overview","m":null,"ct":"application/json","b":"<undefined>"},{"p":"/admin/api/tokens","m":"POST","ct":"application/json","b":"{\"name\":\"Trae\",\"enabled\":true}"},{"p":"/admin/api/config","m":"PUT","ct":"application/json","b":"{\"resources\":[1,2]}"}]
  ✓ L9 :: 取消分支：{"state":"settled","value":"false","calls":[],"open":0,"labels":["","取消","确定"],"btnCount":3,"footBtnCount":2,"footBtnLabels":["取消","确定"]}
  ✓ L10 :: 确定分支：{"state":"settled","value":"true","calls":["DELETE_SENT"],"open":0,"labels":["","取消","确定"],"btnCount":3,"footBtnCount":2,"footBtnLabels":["取消","确定"]}
  ✓ L21 :: 两条通道都 settle 且答复=false
  ✓ L11 :: written=["sk-a1b2c3d4e5f6g7h8"] toasts=[{"text":"密钥已复制","cls":"toast ok"}]
  ✓ L12 :: written=["sk-zzz"] toasts=[{"text":"复制失败","cls":"toast err"}]
  ✓ L13 :: toasts=[] written=[]
  ✓ L14 :: scripts=0 h3=&lt;script&gt;alert(1)&lt;/script&gt;
  ✓ L15 :: footKids=2 texts=["取消","确定"] emptied=true
  ✓ L16 :: {"afterX":0,"blank":{"kids":0,"closed":1},"innerKids":1,"api":1,"el":"el-ok","noFooter":{"foot":false,"cls":"modal"}}
  ✓ L17 :: {"okTrue":{"init":false,"ret":"true","before":"switch","seen":[true],"after":true,"cls":"switch on"},"failFalse":{"init":false,"ret":"false","before":"switch","seen":[true],"after":false,"cls":"switch"},"undef":{"init":false,"ret":"undefined","before":"switch","seen":[true],"after":true,"cls":"switch on"},"turnOff":{"init":true,"ret":"true","before":"switch on","seen":[false],"after":false,"cls":"switch"},"noToggle":{"after":true}}
  ✓ L18 :: {"count":2,"switched":["b"],"actives":["维度"],"cls":"tabs"}
  ✓ L19 :: first=[["‹",true],["1 / 3（共 23 条）",false],["›",false]] last=[["‹",false],["3 / 3（共 23 条）",false],["›",true]] pages=[10]
  ✓ L20 :: 抽取 2 处：resources.js,apiaccess.js ｜ 2 处定义逐条对上（样例 sk-a1****k0lm）
  ✓ M0 :: 请求=["GET /admin/api/config","GET /admin/api/overview"]；页内函数 7/7；地址字段={"local":"http://127.0.0.1:8300/v1","lan":"http://192.168.31.102:8300/v1","lan_ip":"192.168.31.102"}；端点说明 4 条；表头 ["用途标注","密钥","状态","操作"]；err=无；地址块=["http://127.0.0.1:8300/v1","http://192.168.31.102:8300/v1"]
  ✓ M1 :: 2 行 / 2 条；卡头「1/2 启用 · 未配置密钥时 /v1 免鉴权放行」；停用行 1 个；逐行对得上
  ✓ M2 :: 2 行里 2 行是密文；样例「mg-a1****8f90」；序列化 HTML 6873 字符；无明文
  ✓ M3 :: 密文「mg-a1****8f90」→ 明文「mg-a1b2c3d4e5f…」→ 密文「mg-a1****8f90」；图标换了 true/true；请求 ["GET /admin/api/config","GET /admin/api/overview"]；三态都对
  ✓ M4 :: 剪贴板收到 ["mg-a1b2c3d4e5f60718293a4b5c6d7e8f90","http://127.0.0.1:8300/v1","http://192.168.31.102:8300/v1"]；toast ["密钥已复制","已复制","已复制"]；全部对上
  ✓ M5 :: 请求 ["GET /admin/api/config","GET /admin/api/overview","PUT /admin/api/config","GET /admin/api/config","GET /admin/api/overview"]；PUT body 的第 2 条 enabled=true、顶层键 6 个；服务端=true；界面开关=true；卡头「2/2 启用 · 未配置密钥时 /v1 免鉴权放行」；toast ["密钥已启用"]；启停闭环对得上
  ✓ M6 :: 请求 ["GET /admin/api/config","GET /admin/api/overview","PUT /admin/api/config","GET /admin/api/config","GET /admin/api/overview"]；toast=[{"text":"保存失败：Value error, gateway.access_tokens[].id 重复：'tok-1'","cls":"toast err"}]；服务端 enabled=false；界面开关=false；失败支口径正确
  ✓ M7 :: 原名="Trae" → PUT body 名字=Trae 改过；服务端="Trae 改过"；同值新增请求=0；toast ["用途标注已更新"]；编辑闭环对得上
  ✓ M8 :: 取消支：PUT 0 次 / 2 行 / 弹窗 0 层；确定支：PUT 1 次，body 3 条，服务端补齐 id=tok-9001，界面 3 行、新行「mg-10****ef01」、卡头「2/3 启用 · 未配置密钥时 /v1 免鉴权放行」；两条支路都对
  ✓ M9 :: cancel/x/mask 的 promise 态=cancel:settled,x:settled,mask:settled；各自发出的请求数=0,0,0；确定支 ["PUT /admin/api/config","GET /admin/api/config","GET /admin/api/overview"]、body 剩 ["tok-2"]；四支全对
  ✓ M10 :: 请求=["GET /admin/api/config"]；卡 ["01 · 任务执行","02 · 系统日志","维护"]；输入 12 个；保存钮 disabled=true 文案「保存配置」；徽章=false；重启=true 停止=true；err=无
  ✓ M11 :: 对不上的 0 处 / 共 12 个绑定；x=2 y=3 m=4 退避=1.5；逐字段对上
  ✓ M12 :: 首屏 徽章=false/disabled=true/dirty=false；改后 徽章=1 枚「有未保存修改」/disabled=false/dirty=true；再改 徽章=1/disabled=false；页头顺序 ["有未保存修改","保存配置"]；两向同源
  ✓ M13 :: 过滤后「1239」；清空后 徽章=false/disabled=true；cooldown_seconds=60；页内 y=8；请求 ["GET /admin/api/config"]；过滤与未修改语义都在
  ✓ M14 :: 点保存前 PUT 0 次；点后 1 次，body 的 y=7、顶层键 6 个；服务端 y=7；界面 y=7；徽章=false/disabled=true；二段保存闭环对得上
  ✓ M15 :: toast=[{"text":"保存失败：gateway: Value error, request_total_budget_seconds(1) 必须 >= attempt_timeout_seconds(45)（tech-design §4.7 ③）","cls":"toast err"}]；服务端预算=300；界面值=1；脏态 徽章=true/disabled=false；失败支口径正确
  ✓ M16 :: 停止·取消 [] / promise settled；停止·确定 ["POST /admin/api/system/stop"] 停止态=true；重启·确定 POST=["POST /admin/api/system/restart"] 等待态 opacity=.5 待触发定时器 2 个（恢复轮询不在判据内，见证据文档负面清单）；两条破坏性动作都要确认才落地
  ✓ M17 :: API 接入 7356 字符；系统设置 3469 字符；两页产物干净
  ✓ Z1 :: (空)
  ✓ Z2 :: 派生 52 个；全部取不到
  ✓ Z5 :: 登记注入值 61 个；全部走不出去
  ✓ Z4 :: 派生=plain-hide,media-hide,supports-hide,layered-hide；本项目样式表派生出 7 类/0 id/0 标签
  ✓ Z3 :: (空)
```
