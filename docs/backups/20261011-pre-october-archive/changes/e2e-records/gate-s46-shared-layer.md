# S-46（面板 ix B12-1）前端验收门 · 共享行为层真跑 —— 交付记录

- 日期：2026-09-29　执行范围：**只改 `scripts/verify_v2_frontend.mjs` 一个文件**（源码/后端/测试/其它前端文件零改动）
- 批次：**只做「共享行为层」这一半**（`api.js` + `components.js`）。六个页面各自的 `renderXxx` 真跑属下一批，本轮未做。

---

## 1. 结论（数字全部复制自 runner 自己的输出）

```
[变异自证] 基线 109 条全绿 → 施加 141 个源码变异
可红 141/141；每条断言都有对应变异
```

```
实测 109 项，通过 109 项，失败 0 项
```

- 判据：**88 → 109**（新增 L0~L20 共 **21 条**）
- 变异：**112 → 141**（新增 **29 条**，全部指向 `api.js` / `components.js` / `apiaccess.js` / `resources.js` 的源码，另有一条 `self:true` 打门自己的 import 剥离）
- 既有判据/变异：**一条未删、一条未削弱**（`git diff` 只有新增行；L 段插在 K 段与 Z 段之间）

命令（payload 由 `tests/integration/test_int_v2_frontend_gate.py::_overview_payload` 真实装配产出，临时目录独立 `mktemp -d`）：

```
$ T=$(mktemp -d /tmp/mgw-s46.XXXXXX)         # 实得 /tmp/mgw-s46.eqUJ0R
$ .venv/bin/python -c "... _overview_payload(Path('$T')) ..."
$ node scripts/verify_v2_frontend.mjs /tmp/mgw-s46.eqUJ0R/overview.json            # 基线
$ node scripts/verify_v2_frontend.mjs /tmp/mgw-s46.eqUJ0R/overview.json --mutation # 变异自证
$ .venv/bin/python -m pytest tests/integration/test_int_v2_frontend_gate.py -q -p no:warnings
2 passed in 25.76s
```

`tests/integration/test_int_v2_frontend_gate.py` **无需改动**：它对数量用的是下限断言（`count >= 85`、`int(total) >= 108`），本轮 109/141 天然满足。该文件**docstring 里的 85/108 是上一轮的陈旧数字**（无机制作用，只有阅读误导），按纪律我没动它，登记在此。

---

## 2. 机制：共享层怎么"真跑"的（为什么假 DOM 必须在 realm 内）

新增三块（都在门里）：

1. `SHARED_DOM`（模块级，门内约 150 行假 DOM **源码**）：`__mk/__parse/__match/__ser` + `document/navigator/setTimeout/fetch` 桩 + `__toasts/__flush/__settle/__reset/__resp` 观察器。
2. `L_SCEN`（9 段 realm 侧驱动：`inventory / states / methods / persist / confirm / copy / modal / sw / tabs`）与 `maskScenario`。
3. `runChecks` 内的 **L 段判据**（先 await 求值、再同步判定）+ `MUTATIONS` 末尾的 29 条变异。

执行方式沿用 K 段那条路：`toModuleBody(read("api")) + toModuleBody(read("components"))` 拼进 `browserFn` 的模板里，**编进空 vm 上下文真跑**（不是复制品；门自己的 `toModuleBody` 被变异掉 import 剥离时 L0 会红，见 §4 L0 红证）。

🔴 **为什么假 DOM 写成 realm 源码、而不是像 `document`/`fetch` 那样从宿主注入形参**（本轮的设计判断，写下来免得下批复踩）：
节点是**又读又写**的可变对象 —— 页面往它上面挂 `onclick`、`modal()` 要搬 `firstChild`、还要比 `e.target === mask` 的身份。宿主节点进 realm 必过 `__guard`：① 数组属性（`children`）会被映射成 realm **副本**（`guard` 里那条"数组不能包 Proxy"的注释就是这件事），页面 push 进去就丢；② 节点身份两侧不一致，`e.target === mask` 恒假；③ 宿主对象本身带着宿主 realm 的 `constructor`（S-52 那条桥）。realm 内自建 DOM 三样都没有，而且 **L 段没有任何宿主值跨进 realm**（`INJECTED` 不增项，Z5 覆盖面不受影响）。

🔴 本轮自己撞到的两个坑（都已修并写进门内注释）：
- **detail 早于异步体求值**：`check()` 先 `ok()` 再求 `detail`，所以异步判据的 detail 写成箭头函数只会拿到空串。L 段因此一律"场景先 await、判定同步做"。
- **崩掉 ≠ 红**：`st()` 原先写 `(arr || [{}])[0]`，`arr` 是空数组时 `[0]` 为 `undefined`，而 detail 是在 `check()` 之前求值的字符串 → 子进程直接崩，变异自证报 `子进程 Error，无可判读输出`（= 盲，不是红），第一次跑就把两条既有变异（第九轮 B-5 esc）打成盲。已改成永远返回对象 + detail 一律惰性。**这条正是 Z3/第十一轮 B11-1 同一族**，说明共享层判据自己也得过"不许用崩溃冒充证据"这一关。

---

## 3. 新增判据清单（id · 它在防什么 · 谁把它打红）

| id | 防的是什么事 | 打红它的变异（文件） |
|---|---|---|
| L0 | 共享层能否被编进 realm 真跑；`api/GET/PUT/POST/toast/modal/confirmDialog/tabBar/switchEl/copyText/pagination/esc` 12 个导出齐备（少导出/改名 = L 段失去对象） | `switchEl` 改名（components.js）；`toModuleBody` 不再剥 import（门自己） |
| L1 | 成功路径把后端数据丢掉（`return data` → null，界面拿到空） | `return data;` → `return null;`（api.js） |
| L2 | 后端 4 类错误形态（`errors[]` / `error.message` / `message` / `detail`）的原因必须逐条进 `Error.message`，多条要拼全 | `if(!resp.ok)→if(false)`；`data.errors ? join("；") : → "" :`（api.js） |
| L3 | **`!resp.ok` 一律 reject**（面板 ①）：4xx/5xx 绝不允许被当成成功返回数据 | `if (!resp.ok) {` → `if (false) {`；→ `if (resp.ok === false && data) {`（api.js） |
| L4 | 网络异常（fetch reject）原样抛出，不得吞成 null 让界面按"空配置"渲染 | `catch { return null; }` 包住 fetch（api.js） |
| L5 | **用户可见后果**：后端回 400 时界面只有红色「保存失败」+ 后端原因，绿色「配置已保存并热重载生效」必须消失（调用方形状照抄 `apiaccess.js:31-38 persist`） | `if(false)`；`errors` 分支置空；`toast` 丢 type（三条，api.js×2 + components.js） |
| L6 | 非 JSON 的 4xx/5xx（网关 HTML 错误页 / 502）仍 reject 并报 `HTTP <状态码>` | `if (resp.ok === false && data)`；`` \|\| \`HTTP ${resp.status}\` `` → `"请求失败"`（api.js） |
| L7 | 非 JSON 的 2xx → 返回 `null`（不得凭空造 `{}` 让调用方以为拿到了配置） | `catch { data = {}; }`（api.js） |
| L8 | GET/POST/PUT 的 HTTP 语义真的带出去（method / `JSON.stringify` / `Content-Type`） | POST 的 method 改 PATCH；PUT 不再序列化 body（api.js） |
| L9 | **点「取消」绝不执行副作用**（面板 ②）：以"DELETE 是否真被发出"判定，不看返回值字面；并且弹窗要关掉、要给出一句答复 | `cancel.onclick` 的 `resolve(false)`→`resolve(true)`；去掉 `m.close()`（components.js） |
| L10 | 点「确定」副作用**恰好一次**（确认被吞掉 = 删除/重启/停止全按不下去） | `ok.onclick` 的 `resolve(true)`→`resolve(false)`（components.js） |
| L11 | **copyText 成功**：写进剪贴板的正是那段明文（逐字节比对 `writeText` 收到的值），toast 文案与 ok 样式同源（默认文案 `已复制` 也钉） | 不写剪贴板直接 `toast(okMsg,"ok")`（components.js） |
| L12 | 剪贴板写入被拒 → toast 只能是「复制失败」+ err 样式，不得出现成功文案 | 失败分支改成成功文案；`toast` 丢 type（components.js） |
| L13 | `navigator.clipboard` 不存在时**绝不谎报已复制**（没有任何真实写入路径就不许弹成功） | 伪造一个必然成功的 clipboard（`|| { writeText: ... }`）（components.js） |
| L14 | `modal` 标题走 `esc`：title 里的 `<script>` 不得成为真元素（管理台注入面） | `${esc(title)}` → `${title}`（components.js） |
| L15 | `modal` 的 footer 子节点**平铺**进 `.modal-foot`（2026-09-06 已修过的间距回归） | `while (footer.firstChild) …` → `footEl.append(footer)`（components.js） |
| L16 | `modal` 关闭三通道：X 关 / 点遮罩关并回调 `onClose` / 点弹窗内部**不关**；返回的 `el` 就是那个遮罩 | 遮罩监听去掉 `e.target === mask` 条件；X 不绑 `close`（components.js） |
| L17 | `switchEl`：`onToggle` 返回 `true` 才翻视觉、返回 `false` 必须回滚（D3 操作即保存）；`undefined` 视为成功；关→开与开→关两个方向的入参都对 | `if (ok !== false)`→`if (true)`；删掉 toggle；`next` 恒 true（components.js） |
| L18 | `tabBar`：选中态唯一，回调收到**被点的那个** tab id | `onSwitch(t.id)`→`onSwitch(active)`；不清旧 active（components.js） |
| L19 | `pagination`：首页禁「‹」/末页禁「›」，点「›」交出下一页 offset，页码文案在 | 不再置 `disabled`（components.js） |
| L20 | `maskVal`（面板 ④）：**每处定义**都输出「前5+`****`+后4」，中段不泄漏，写进假 DOM 读回也不含完整明文，空值仍是空串；抽取数量 <2 即红（防"抽不到当没违规"） | apiaccess.js 的 maskVal 改恒等；resources.js 的 maskVal 去掉 `****`（两条各打红一次 = 证明两处都真在跑） |

---

## 4. 每条判据的红证（原样输出）

驱动器：`/tmp/mgw-s46.eqUJ0R/red-evidence.mjs`（临时件，不入库；变异清单**从门里 eval 出来**，不另立第二份账）。
命令：`TDIR=/tmp/mgw-s46.eqUJ0R node red-evidence.mjs`
（它把仓库的入面文件 rsync 到独立 temp 树 → 只施加一条变异 → 跑**门的副本** → 打印变红的判据行。）

### ① 基线还原（驱动器最后一步）
```
#### 还原全部变异后的基线：实测 109 项，通过 109 项，失败 0 项
```

### ② 面板的四条坏改动**同时**种进源码 —— `TDIR=/tmp/mgw-s46.eqUJ0R node red-evidence.mjs --combo` 全量原样输出
```
### 基线（未种任何变异）：实测 109 项，通过 109 项，失败 0 项
### 同时种进源码的坏改动 4 条（面板 ix B12-1 的实测项）：
  · 🔴 面板 ix B12-1 ①：4xx 不再抛错（后端真回 400，界面弹绿色「配置已保存并热重载生效」）
    文件 model_gateway/web/static/js/api.js
      if (!resp.ok) {
    →   if (false) {
  · 🔴 面板 ix B12-1 ②：确认弹窗的取消分支改成 resolve(true)（点「取消」真的删了密钥）
    文件 model_gateway/web/static/js/components.js
        cancel.onclick = () => { m.close(); resolve(false); };
    →     cancel.onclick = () => { m.close(); resolve(true); };
  · 🔴 面板 ix B12-1 ③：copyText 不写剪贴板直接报「已复制」
    文件 model_gateway/web/static/js/components.js
      navigator.clipboard?.writeText(text).then(
    () => toast(okMsg, "ok"), () => toast("复制失败", "err"));
    →   toast(okMsg, "ok");
  · 🔴 面板 ix B12-1 ④：maskVal 改成恒等（API 接入页密钥明文直接上屏）
    文件 model_gateway/web/static/js/pages/apiaccess.js
    const maskVal = (v) => v ? v.slice(0, 5) + "****" + v.slice(-4) : "";
    → const maskVal = (v) => v || "";
### 变红判据（共 9 条）：L2,L3,L5,L6,L9,L11,L12,L13,L20
### 其中**不属于**新增 L 段的既有判据：无（既有 88 条一条没红 = 本轮之前对此毫无感知）
### 实测汇总行：  ✗ L20 maskVal：每处定义都输出「前5+****+后4」密文，DOM 文本里不得出现完整明文
### 变红原文：
  ✗ L2 四类后端错误形态的原因都被带进 Error.message（errors[] / error.message / message / detail）  400-errors→「」缺「rid 重复：res-a」 | 400-errors→「」缺「models[3].name 必填」 | 400-errors→多条原因没拼全：「」 | 401-obj→「」缺「E 上游 401 invalid_api_key」 | 409-msg→「」缺「M 配置已被别处改动」 | 422-detail→「」缺「D 字段校验失败」
  ✗ L3 !resp.ok 一律 reject（4xx/5xx 绝不允许被当成成功返回数据）  六种失败响应：400-errors→resolve({"errors":["rid 重复：res-a","models[3].name 必填"]}) 401-obj→resolve({"error":{"message":"E 上游 401 invalid_api_key"}}) 409-msg→resolve({"message":"M 配置已被别处改动"}) 422-detail→resolve({"detail":"D 字段校验失败"}) 500-html→resolve(null) network→reject ｜静默当成功：400-errors→resolve({"errors":["rid 重复：res-a","models[3].name 必填"]}),401-obj→resolve({"error":{"message":"E 上游 401 invalid_api_key"}}),409-msg→resolve({"message":"M 配置已被别处改动"}),422-detail→resolve({"detail":"D 字段校验失败"}),500-html→resolve(null)
  ✗ L5 后端回 400 时界面只有红色「保存失败」并带后端原因，绿色「配置已保存并热重载生效」必须消失  outcome=ok toasts=[{"text":"配置已保存并热重载生效","cls":"toast ok"}]
  ✗ L6 非 JSON 的 4xx/5xx（网关 HTML 错误页）仍 reject 并给出 HTTP 状态口径  500-html → rejected=false msg=null got=null
  ✗ L9 确认弹窗点「取消」：不执行副作用（DELETE_SENT 一次都没有）+ 弹窗关掉 + 给出答复  取消分支：{"state":"settled","value":"true","calls":["DELETE_SENT"],"open":0,"labels":["","取消","确定"],"btnCount":3,"footBtnCount":2,"footBtnLabels":["取消","确定"]}
  ✗ L11 copyText 成功：写进剪贴板的正是那段明文，toast 文案与 ok 样式同源  written=[] toasts=[{"text":"密钥已复制","cls":"toast ok"}]
  ✗ L12 剪贴板写入被拒（权限/非安全上下文）：toast 只能说不一致的口径，不得报「已复制」  written=[] toasts=[{"text":"密钥已复制","cls":"toast ok"}]
  ✗ L13 navigator.clipboard 不存在时**绝不谎报已复制**（没有任何真实写入路径就不许弹成功）  toasts=[{"text":"密钥已复制","cls":"toast ok"}] written=[]
  ✗ L20 maskVal：每处定义都输出「前5+****+后4」密文，DOM 文本里不得出现完整明文  抽取 2 处：resources.js,apiaccess.js ｜ model_gateway/web/static/js/pages/apiaccess.js：恒等返回明文（输出===输入） | model_gateway/web/static/js/pages/apiaccess.js：输出里没有 **** 掩码段 | model_gateway/web/static/js/pages/apiaccess.js：密钥中段泄漏 | model_gateway/web/static/js/pages/apiaccess.js：DOM 文本里出现完整明文 | model_gateway/web/static/js/pages/apiaccess.js：口径不是「前5+****+后4」，实得 sk-a1b2c3d4e5f6g7h8j9k0lm
  ✗ L2 四类后端错误形态的原因都被带进 Error.message（errors[] / error.message / message / detail）
  ✗ L3 !resp.ok 一律 reject（4xx/5xx 绝不允许被当成成功返回数据）
  ✗ L5 后端回 400 时界面只有红色「保存失败」并带后端原因，绿色「配置已保存并热重载生效」必须消失
  ✗ L6 非 JSON 的 4xx/5xx（网关 HTML 错误页）仍 reject 并给出 HTTP 状态口径
  ✗ L9 确认弹窗点「取消」：不执行副作用（DELETE_SENT 一次都没有）+ 弹窗关掉 + 给出答复
  ✗ L11 copyText 成功：写进剪贴板的正是那段明文，toast 文案与 ok 样式同源
  ✗ L12 剪贴板写入被拒（权限/非安全上下文）：toast 只能说不一致的口径，不得报「已复制」
  ✗ L13 navigator.clipboard 不存在时**绝不谎报已复制**（没有任何真实写入路径就不许弹成功）
  ✗ L20 maskVal：每处定义都输出「前5+****+后4」密文，DOM 文本里不得出现完整明文
```

### ③ 逐条红证 —— `TDIR=/tmp/mgw-s46.eqUJ0R node red-evidence.mjs` 全量原样输出
（每条：新判据 id → 打红它的变异（文件 + 种下前后的源码）→ 该变异下变红的判据 → 门的原样红行（含 detail）。
最后一行是**还原全部变异后**的基线，证明红是变异造成的、不是判据本身在挑事。）
```

#### L0 ← 共享层少一个导出（switchEl 改名：L 段判据失去对象，必须先红给看）
     文件：model_gateway/web/static/js/components.js
     种下：export function switchEl(on, onToggle) {   →   export function switchElRenamed(on, onToggle) {
     变红：L0,L17
       ✗ L0 共享层能在 realm 里编译并真跑（12 个导出齐备；编不过/少导出 = L 段判据失去对象）  导出 12/12；不是函数：switchEl=undefined
       ✗ L0 共享层能在 realm 里编译并真跑（12 个导出齐备；编不过/少导出 = L 段判据失去对象）

#### L1 ← 成功路径把后端数据丢掉（界面拿到 null）
     文件：model_gateway/web/static/js/api.js
     种下：  return data;   →     return null;
     变红：L1,L8（另连带 K0,K7,K1,K2,K3,K8,K4,K5,K9,K6）
       ✗ L1 成功路径返回**后端那份数据**（2xx JSON 原样交出，不是 null / 不是 HTTP 串）  200-json → rejected=false got=null
       ✗ L1 成功路径返回**后端那份数据**（2xx JSON 原样交出，不是 null / 不是 HTTP 串）

#### L2 ← 🔴 面板 ix B12-1 ①：4xx 不再抛错（后端真回 400，界面弹绿色「配置已保存并热重载生效」）
     文件：model_gateway/web/static/js/api.js
     种下：  if (!resp.ok) {   →     if (false) {
     变红：L2,L3,L5,L6
       ✗ L2 四类后端错误形态的原因都被带进 Error.message（errors[] / error.message / message / detail）  400-errors→「」缺「rid 重复：res-a」 | 400-errors→「」缺「models[3].name 必填」 | 400-errors→多条原因没拼全：「」 | 401-obj→「」缺「E 上游 401 invalid_api_key」 | 409-msg→「」缺「M 配置已被别处改动」 | 422-detail→「」缺「D 字段校验失败」
       ✗ L2 四类后端错误形态的原因都被带进 Error.message（errors[] / error.message / message / detail）

#### L3 ← 🔴 同族的半吊子写法：只在「有 JSON 正文」时才判失败（HTML 错误页 502 被当成功）
     文件：model_gateway/web/static/js/api.js
     种下：  if (!resp.ok) {   →     if (resp.ok === false && data) {
     变红：L3,L6
       ✗ L3 !resp.ok 一律 reject（4xx/5xx 绝不允许被当成成功返回数据）  六种失败响应：400-errors→reject 401-obj→reject 409-msg→reject 422-detail→reject 500-html→resolve(null) network→reject ｜静默当成功：500-html→resolve(null)
       ✗ L3 !resp.ok 一律 reject（4xx/5xx 绝不允许被当成成功返回数据）

#### L4 ← 🔴 网络异常被吞成 null（断网/服务没起时界面按「空配置」渲染，不报任何错）
     文件：model_gateway/web/static/js/api.js
     种下：  const resp = await fetch(path, { ...opts, headers });   →     let resp; try { resp = await fetch(path, { ...opts, headers }); } catch { return null; }
     变红：L3,L4
       ✗ L4 网络异常（fetch reject）原样抛出，不得吞成 null/undefined 让界面以为成功  network → rejected=false msg=null got=null
       ✗ L4 网络异常（fetch reject）原样抛出，不得吞成 null/undefined 让界面以为成功

#### L5 ← 后端多条校验原因不再拼接（只剩 HTTP 状态码，用户不知道改哪一行）
     文件：model_gateway/web/static/js/api.js
     种下：data.errors ? data.errors.join("；") :   →   data.errors ? "" :
     变红：L2,L5
       ✗ L5 后端回 400 时界面只有红色「保存失败」并带后端原因，绿色「配置已保存并热重载生效」必须消失  outcome=err toasts=[{"text":"保存失败：HTTP 400","cls":"toast err"}]
       ✗ L5 后端回 400 时界面只有红色「保存失败」并带后端原因，绿色「配置已保存并热重载生效」必须消失

#### L6 ← 非 JSON 的 4xx 不再报状态码（只剩一句「请求失败」，无从判断是 401 还是 502）
     文件：model_gateway/web/static/js/api.js
     种下： || `HTTP ${resp.status}`;   →    || "请求失败";
     变红：L6
       ✗ L6 非 JSON 的 4xx/5xx（网关 HTML 错误页）仍 reject 并给出 HTTP 状态口径  500-html → rejected=true msg=请求失败 got=NO-RESULT
       ✗ L6 非 JSON 的 4xx/5xx（网关 HTML 错误页）仍 reject 并给出 HTTP 状态口径

#### L7 ← 非 JSON 的 2xx 凭空造出一个空对象（调用方以为拿到了配置）
     文件：model_gateway/web/static/js/api.js
     种下：  try { data = await resp.json(); } catch { /* 非 JSON */ }   →     try { data = await resp.json(); } catch { data = {}; }
     变红：L7
       ✗ L7 非 JSON 的 2xx → 返回 null（不得凭空造 {} 让调用方以为拿到了配置）  204-nonjson → got={} rejected=false
       ✗ L7 非 JSON 的 2xx → 返回 null（不得凭空造 {} 让调用方以为拿到了配置）

#### L8 ← POST 的 method 写错（后端路由按 method 分派，界面弹成功、数据没落库）
     文件：model_gateway/web/static/js/api.js
     种下：export const POST = (p, body) => api(p, { method: "POST", body: JSON.stringify(body) });   →   export const POST = (p, body) => api(p, { method: "PATCH", body: JSON.stringify(body) });
     变红：L8
       ✗ L8 GET/POST/PUT 的 HTTP 语义真的带出去（method + JSON 序列化 + Content-Type）  实际发出的请求：[{"p":"/admin/api/overview","m":null,"ct":"application/json","b":"<undefined>"},{"p":"/admin/api/tokens","m":"PATCH","ct":"application/json","b":"{\"name\":\"Trae\",\"enabled\":true}"},{"p":"/admin/api/config","m":"PUT","ct":"application/json","b":"{\"resources\":[1,2]}"}]
       ✗ L8 GET/POST/PUT 的 HTTP 语义真的带出去（method + JSON 序列化 + Content-Type）

#### L9 ← 🔴 面板 ix B12-1 ②：确认弹窗的取消分支改成 resolve(true)（点「取消」真的删了密钥）
     文件：model_gateway/web/static/js/components.js
     种下：    cancel.onclick = () => { m.close(); resolve(false); };   →       cancel.onclick = () => { m.close(); resolve(true); };
     变红：L9
       ✗ L9 确认弹窗点「取消」：不执行副作用（DELETE_SENT 一次都没有）+ 弹窗关掉 + 给出答复  取消分支：{"state":"settled","value":"true","calls":["DELETE_SENT"],"open":0,"labels":["","取消","确定"],"btnCount":3,"footBtnCount":2,"footBtnLabels":["取消","确定"]}
       ✗ L9 确认弹窗点「取消」：不执行副作用（DELETE_SENT 一次都没有）+ 弹窗关掉 + 给出答复

#### L10 ← 确定分支被改成 false（所有确认类操作静默失效：删除/重启/停止全按不下去）
     文件：model_gateway/web/static/js/components.js
     种下：    ok.onclick = () => { m.close(); resolve(true); };   →       ok.onclick = () => { m.close(); resolve(false); };
     变红：L10
       ✗ L10 确认弹窗点「确定」：副作用**恰好一次**（确认不得被吞掉），弹窗关掉  确定分支：{"state":"settled","value":"false","calls":[],"open":0,"labels":["","取消","确定"],"btnCount":3,"footBtnCount":2,"footBtnLabels":["取消","确定"]}
       ✗ L10 确认弹窗点「确定」：副作用**恰好一次**（确认不得被吞掉），弹窗关掉

#### L11 ← 🔴 面板 ix B12-1 ③：copyText 不写剪贴板直接报「已复制」
     文件：model_gateway/web/static/js/components.js
     种下：  navigator.clipboard?.writeText(text).then(
    () => toast(okMsg, "ok"), () => toast("复制失败", "err"));   →     toast(okMsg, "ok");
     变红：L11,L12,L13
       ✗ L11 copyText 成功：写进剪贴板的正是那段明文，toast 文案与 ok 样式同源  written=[] toasts=[{"text":"密钥已复制","cls":"toast ok"}]
       ✗ L11 copyText 成功：写进剪贴板的正是那段明文，toast 文案与 ok 样式同源

#### L12 ← 🔴 toast 的类型丢掉（失败也染成绿色 ok 样式，红绿色失去含义）
     文件：model_gateway/web/static/js/components.js
     种下：  el.className = "toast " + type;   →     el.className = "toast ok";
     变红：L5,L12
       ✗ L12 剪贴板写入被拒（权限/非安全上下文）：toast 只能说不一致的口径，不得报「已复制」  written=["sk-zzz"] toasts=[{"text":"复制失败","cls":"toast ok"}]
       ✗ L12 剪贴板写入被拒（权限/非安全上下文）：toast 只能说不一致的口径，不得报「已复制」

#### L13 ← clipboard 缺失时伪造一个必然成功的写入（非安全上下文里谎报已复制）
     文件：model_gateway/web/static/js/components.js
     种下：  navigator.clipboard?.writeText(text).then(   →     (navigator.clipboard || { writeText: () => Promise.resolve() }).writeText(text).then(
     变红：L13
       ✗ L13 navigator.clipboard 不存在时**绝不谎报已复制**（没有任何真实写入路径就不许弹成功）  toasts=[{"text":"密钥已复制","cls":"toast ok"}] written=[]
       ✗ L13 navigator.clipboard 不存在时**绝不谎报已复制**（没有任何真实写入路径就不许弹成功）

#### L14 ← modal 标题不做转义（title 里的 <script> 成为真元素 = 管理台注入面）
     文件：model_gateway/web/static/js/components.js
     种下：<h3>${esc(title)}</h3>   →   <h3>${title}</h3>
     变红：L14
       ✗ L14 modal 标题走 esc：title 里的 <script> 不得成为真元素（管理台注入面）  scripts=1 h3=alert(1)
       ✗ L14 modal 标题走 esc：title 里的 <script> 不得成为真元素（管理台注入面）

#### L15 ← 🔴 弹窗脚钮间距回归（整块 append footer，gap 落在中间层 → 取消/确定贴死，2026-09-06 已修过一次）
     文件：model_gateway/web/static/js/components.js
     种下：    while (footer.firstChild) footEl.append(footer.firstChild);   →       footEl.append(footer);
     变红：L15
       ✗ L15 modal 的 footer 子节点**平铺**进 .modal-foot（Q21 间距根修：整块 append 会让 gap 失效）  footKids=1 texts=["取消 确定"] emptied=false
       ✗ L15 modal 的 footer 子节点**平铺**进 .modal-foot（Q21 间距根修：整块 append 会让 gap 失效）

#### L16 ← 点弹窗内部也关闭（填了一半的表单被误点丢掉）
     文件：model_gateway/web/static/js/components.js
     种下：  mask.addEventListener("mousedown", (e) => { if (e.target === mask) close(); });   →     mask.addEventListener("mousedown", (e) => { close(); });
     变红：L16
       ✗ L16 modal 关闭三通道：X 按钮关、点遮罩关（并回调 onClose）、点弹窗内部**不关**  {"afterX":0,"blank":{"kids":0,"closed":1},"innerKids":0,"api":0,"el":"el-mismatch","noFooter":{"foot":false,"cls":"modal"}}
       ✗ L16 modal 关闭三通道：X 按钮关、点遮罩关（并回调 onClose）、点弹窗内部**不关**

#### L17 ← 🔴 开关不再按保存结果回滚（onToggle 返回 false 也翻成开启 = 界面与配置打架）
     文件：model_gateway/web/static/js/components.js
     种下：    if (ok !== false) el.classList.toggle("on", next);   →       if (true) el.classList.toggle("on", next);
     变红：L17
       ✗ L17 switchEl：保存成功（onToggle 返回 true）才翻视觉，返回 false 必须回滚（D3 操作即保存）  {"okTrue":{"init":false,"ret":"true","before":"switch","seen":[true],"after":true,"cls":"switch on"},"failFalse":{"init":false,"ret":"false","before":"switch","seen":[true],"after":true,"cls":"switch on"},"undef":{"init":false,"ret":"undefined","before":"switch","seen":[true],"after":true,"cls":"switch on"},"turnOff":{"init":true,"ret":"true","before":"switch on","seen":[false],"after":false,"cls":"switch"},"noToggle":{"after":true}}
       ✗ L17 switchEl：保存成功（onToggle 返回 true）才翻视觉，返回 false 必须回滚（D3 操作即保存）

#### L18 ← tab 切换回调交出的是**初始** active（第二组 tab 永远切不动）
     文件：model_gateway/web/static/js/components.js
     种下：      onSwitch(t.id);   →         onSwitch(active);
     变红：L18
       ✗ L18 tabBar：选中态唯一，且回调收到**被点的那个** tab id  {"count":2,"switched":["a"],"actives":["维度"],"cls":"tabs"}
       ✗ L18 tabBar：选中态唯一，且回调收到**被点的那个** tab id

#### L19 ← 分页按钮不再置 disabled（首页还能点「‹」、末页还能点「›」，offset 跑到负数）
     文件：model_gateway/web/static/js/components.js
     种下：    b.className = "btn btn-sm"; b.textContent = label; b.disabled = disabled;   →       b.className = "btn btn-sm"; b.textContent = label;
     变红：L19
       ✗ L19 pagination：首页禁「‹」/末页禁「›」，点「›」交出下一页 offset  first=[["‹",false],["1 / 3（共 23 条）",false],["›",false]] last=[["‹",false],["3 / 3（共 23 条）",false],["›",false]] pages=[10]
       ✗ L19 pagination：首页禁「‹」/末页禁「›」，点「›」交出下一页 offset

#### L20 ← 🔴 面板 ix B12-1 ④：maskVal 改成恒等（API 接入页密钥明文直接上屏）
     文件：model_gateway/web/static/js/pages/apiaccess.js
     种下：const maskVal = (v) => v ? v.slice(0, 5) + "****" + v.slice(-4) : "";   →   const maskVal = (v) => v || "";
     变红：L20
       ✗ L20 maskVal：每处定义都输出「前5+****+后4」密文，DOM 文本里不得出现完整明文  抽取 2 处：resources.js,apiaccess.js ｜ model_gateway/web/static/js/pages/apiaccess.js：恒等返回明文（输出===输入） | model_gateway/web/static/js/pages/apiaccess.js：输出里没有 **** 掩码段 | model_gateway/web/static/js/pages/apiaccess.js：密钥中段泄漏 | model_gateway/web/static/js/pages/apiaccess.js：DOM 文本里出现完整明文 | model_gateway/web/static/js/pages/apiaccess.js：口径不是「前5+****+后4」，实得 sk-a1b2c3d4e5f6g7h8j9k0lm
       ✗ L20 maskVal：每处定义都输出「前5+****+后4」密文，DOM 文本里不得出现完整明文

#### 还原全部变异后的基线：实测 109 项，通过 109 项，失败 0 项
```

## 5. 与简报口径不符的地方（以代码为准，逐条）

1. **`maskVal` 不在共享层。** 简报把它列进「`api.js` 与 `components.js` 里的共享行为」，实际它在两个页面文件里**逐字重复**了两份：`pages/apiaccess.js:19` 与 `pages/resources.js:76`，`components.js`/`api.js` 里根本没有。
   处理：L20 用**目录扫描派生**（不写死文件名）把所有 `maskVal` 定义抽出来逐个真跑，并要求 `抽取数 >= 2`，两处各配一条变异 —— 这样"只改一处副本"也一定红。
   建议（本轮未做，属源码改动）：把 `maskVal` 收进 `components.js` 单一出口，重复两份本身就是"改一处漏一处"的坏味道。
2. **`copyText` 没有任何降级路径。** 简报写「只有真的写进剪贴板（或真的降级成功）才 toast『已复制』」，现状是 `navigator.clipboard?.writeText(...)` 一行，`?.` 短路后**整条链静默**：既没写也没 toast。所以 L13 按现状钉的是"绝不谎报成功"；假 DOM 里也**没有**提供 `document.execCommand` 之类的降级出口 —— 如果将来加降级，必须同时给假 DOM 补那个出口，否则 L13 会红（这是设计上的 fail-closed，不是判据写错）。
   顺带一个 UX 事实（不是本轮判据）：非安全上下文里"复制"按钮现在是**点了没反应**的死按钮。
3. **`confirmDialog` 的 X / 点遮罩关闭不 resolve。** `modal()` 的 `close()` 与 `confirmDialog` 的 promise 没有任何接线（`components.js:34,50-52`），用户点 X 后 `await confirmDialog(...)` 的调用方（`apiaccess.js:130`、`resources.js:338/459`、`models.js:386/414/439`、`settings.js:127/136`）会**永久挂住**。
   我按现状钉的是"X/遮罩关闭后不得执行副作用"（L16 + L9，现状确实不执行，绿）；**没有**擅自加"X 必须 resolve(false)"的判据 —— 那会让基线直接红。这是本轮发现的真缺陷，登记给下一批：修法是 `modal({ onClose })` 里若仍未 settle 就 `resolve(false)`。
4. **`maskVal` 对短值会回显全部**：`maskVal("abcd")` → `"abcd****abcd"`（长度 ≤9 的值等于把原文打回去）。真实密钥/Key 都远长于此，所以 L20 只喂 24 位长密钥；短值口径属设计问题，未擅自写进判据。
5. **`switchEl` 的 `onToggle` 返回 `undefined` 视为成功**（`ok !== false` 的口径，`apiaccess.js:107-111` 生产调用确实 `await persist(...)` 后 `return true`）。L17 把这个"非 false 即成功"的现状钉住了（含 `noHandler` 即不传 onToggle 时默认翻转）。

---

## 5.9 最后一次三连复验（改完全站判据后原样跑，逐字复制）

```
$ node scripts/verify_v2_frontend.mjs /tmp/mgw-s46.eqUJ0R/overview.json
实测 109 项，通过 109 项，失败 0 项
$ node scripts/verify_v2_frontend.mjs /tmp/mgw-s46.eqUJ0R/overview.json --mutation
[变异自证] 基线 109 条全绿 → 施加 141 个源码变异
可红 141/141；每条断言都有对应变异
$ .venv/bin/python -m pytest tests/integration/test_int_v2_frontend_gate.py -q -p no:warnings
2 passed in 25.76s
```

判据家族计数（由 `--json` 输出派生，证明既有 88 条一条没丢）：
`{"A":15,"B":7,"C":18,"D":3,"E":4,"F":7,"I":10,"G":3,"H":2,"J":3,"K":11,"L":21,"Z":5}` 总数 109，errors 0。

## 6. 我没能覆盖什么（负面清单，下一批要接上的）

1. **六个页面的 `renderXxx` 真跑**（本轮明确不做）：简报里那条 **`settings.js` 少一行解禁 → 保存按钮永远灰、脏态徽章照样显示** 完全没被覆盖，它需要真跑 `renderSettings`；L 段只保证了"共享层被叫到时行为对"。
2. **`api.js` 的 6 个格式化/工具导出不作行为判据**：`fmtNum / fmtDur / fmtUptime / groupColor / fmtValue / debounce`。其中 `fmtNum/fmtUptime/fmtValue/esc` 只经 K 段（dashboard 真跑）间接触达页面产物，**没有取数断言**；`fmtDur/groupColor/debounce` 连触达都没有（`dashboard.js` 不 import 它们）。
3. **`components.js` 的 DOM 契约里这些没有判据**：`toast` 的自动消失计时（`__timers` 只记录不触发，`el.remove()` 那条链未跑）、`modal` 的 `wide` 之外的样式类、`pagination` 的 `pages` 计算在 `total=0` / `limit=0` 的边界、`tabBar` 空数组。
4. **响应形态没喂的**：`resp.ok=true` 但 `json()` 返回**数组**（列表端点）、`status=204` 且 `json()` 不存在（真 204 的 `resp.json` 会 reject，我用"json 抛错"等价建模）、后端返回 `{errors: []}`（空数组 → 现在落到 `HTTP <状态码>`，L2 只喂了非空数组）、`status=0`/CORS 失败（浏览器里表现为 fetch reject，与 L4 同一条路径）。
5. **realm 桥面没有新增**：L 段全部走"realm 内自建假 DOM"，`INJECTED` 不增项，所以 Z5 的覆盖集没扩大 —— 反过来说，**L 段的假 DOM 不受 Z5 保护**（它本来就不跨 realm，无需保护）；下一批若改成宿主注入 DOM，必须先解决 §2 那三个身份/副本问题，不能硬接。
6. **变异表里没有"多个坏改动同时"的组合项**（组合红证是 §4 的 `--combo` 手工跑的）。门是逐条施加变异，`kills` 只声明单条后果。
7. 未跑全量 `pytest`（主控在跑），只跑了 `tests/integration/test_int_v2_frontend_gate.py`（2 passed）；L 段判据不进浏览器，真浏览器里的 `navigator.clipboard` / `modal` 观感仍需 CDP 截图那套面（本轮未做）。
