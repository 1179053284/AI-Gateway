/** 模型映射弹窗 + 批量签到/领取子模块（D-1/D-4 拆分第二步，2026-10-06）——从 accounts.js 物理移出。
 * 共享状态经 accounts/state.js（live binding 读 + setXxx 写）。 */
import { GET, POST, esc } from "../api.js";
import { modal, confirmDialog, toast, toastCard, copyText, initSplitResize } from "../components.js";
import { view, selected, panelEl, setSelected, setPanelEl } from "./state.js";

/* ---------- 模型映射（产品内部模型 → 网关模型）与批量签到 / 领取 ----------
 * 契约（后端随本轮落地，前端按冻结 payload 实现，不预判字段）：
 *   GET  /admin/api/accounts/{product}/catalog → {product,title,checkin,source,models[],accounts[]}
 *        （ModelInfo 全字段随 asdict 带出——映射行的目录辅助信息即来源于此，**无需第二个弹窗**；
 *         单账号 `/{product}/{name}/models` 是 B-1 生产出口，仅后端/测试消费，界面不再调用）
 *   POST /admin/api/accounts/mappings          {product, items:[{model,target}]}   🔴 **唯一**写入口 =「保存」那一次提交
 *   POST /admin/api/accounts/auto-map          {product, models:[空行 id…]}   常驻「AI智能匹配」：**只出建议、零写盘**
 *        （服务端选一条当前可用的 chat 腿（优先 flash/lite 档）逐条判定；没有可用腿或
 *         回答不可解析 ⇒ **整表**降级正则；回执 `via` 说清用了哪档引擎、`reason` 说清为什么）
 *   POST /admin/api/accounts/claim-all         {product} 或 {product:null}（null = 全部支持签到的产品）
 * 两处共用纪律：动作期间触发钮进「执行中…」禁用态（顺序执行可达数十秒，**不加人为超时**）；
 * 结果一律从响应 payload 出（失败只报原文，不编造成功）；写完重取服务端视图自同步（D3）。
 */

/** 模型映射弹窗（root = 页面 root，保存成功后按 models.js `persist(root)` 同款口径重绘本页）。
 *  🔴 **宽版 + 单层弹窗**（2026-10-01 用户定版：弹窗里绝不许再叠弹窗——需要更多信息就
 *  加宽弹窗、把信息融合进列表或就地展开）。目录字段（上下文/输出/推理…）直接画进映射行。
 *
 * 🔴 2026-10-05 第四次裁定 = **草稿制**（「调用AI分析结果直接回填到弹窗内，但不提交保存，
 * 仅在前端进行展示。右侧显示黑色 保存按钮，所有修改、设置 点击保存提交数据后才能入库存储」）：
 *   · 弹窗里**没有任何一条腿会自己写盘** —— 选目标、拨进池开关、改回「暂不设置」、采纳建议、
 *     AI 回填，全部只改内存里那份 `draft`；
 *   · 唯一的写入口 = 脚部那颗黑色「保存」（`mappings` 一条 + 逐行 `product-models/remove`），
 *     没有改动时它是禁用的；
 *   · 「取消 / ×」在有未保存改动时必须**真能取消**（就地两步确认后才放弃，不弹二级窗）。
 *   这条裁定作废上一轮的「行内一改即落库」；它同时也把 10-04 那两条常驻说明
 *   （「未落库 · …才写入」「保存后解除关联」）**请了回来** —— 上一轮删它们不是因为话错，
 *   而是因为那一步不存在了；现在这一步重新存在，话就重新是真话。 */
async function openModelMap(root, p) {
  if (!p) return;
  const body = document.createElement("div");
  body.innerHTML = `<div class="loading">正在读取模型目录…</div>`;
  /* 🔴 三颗钮、三种语义，**没有一颗有两态**（2026-10-05 第三次指示那颗钮常驻 = 保留；
     第四次指示补回「保存」= 它只有一态：有没有未保存的改动，读的是 `draft` 不是文案）：
       · 「取消」= 放弃草稿（有改动时两步确认）；
       · 「AI智能匹配」= 常驻，打 `auto-map`：**只出建议、只回填下拉、一个字都不写**，
         分析范围 = 屏幕上仍显示「暂不设置」的那些行（前端带 `models`，后端再与"配置里从没落过位"取交集）；
         网关内没有可用模型时后端整表降级正则。
       · 「保存」= 唯一的写入口（黑色主钮，脏态数决定使能与文案）。
     两态史（写在这里免得下轮又猜）：Q34「初始化映射 ⇄ 保存」→ 上一轮「落库后收起」→
     本轮「AI智能匹配」常驻 + 「保存」回归，但**两颗是不同的钮、不同的语义**，不再是一钮两态。 */
  const draft = new Map();            // i → { target?, enabled? }（键缺失 = 这一项没动过）
  let catalog = null;
  const foot = document.createElement("div");
  foot.innerHTML = `<button class="btn" data-map="cancel">取消</button>
    <button class="btn" data-map="ai" disabled>AI智能匹配</button>
    <button class="btn btn-primary" data-map="save" disabled>保存</button>`;
  /* 必须在 modal() **之前**取引用（components.js 会把 footer 子节点平铺走，§7.11） */
  const [cancelBtn, aiBtn, saveBtn] = [...foot.querySelectorAll("button")];
  const dlg = modal({ title: `模型映射 · ${p.title}`, body, footer: foot, wide: true, cls: "map-modal" });
  /* AI 钮的使能只由**一件事**决定：有没有落点（账号 + 目录非空）。请求在飞时由 `runAiMatch`
     自己临时改文案并禁用、结束（成功或失败）都调 `setMode()` 回到真实态。 */
  const setMode = () => {
    aiBtn.textContent = "AI智能匹配";
    aiBtn.disabled = !(catalog && (catalog.accounts || []).length)
      || !(catalog && (catalog.models || []).length);
  };
  try {
    const [cat, cfg, enums] = await Promise.all([
      GET(`/admin/api/accounts/${p.id}/catalog`),
      GET("/admin/api/config"),
      GET("/admin/api/enums"),
    ]);
    catalog = cat || {};
    const options = targetOptions((cfg && cfg.models) || [], (enums && enums.entries) || []);
    /* 「首次」的判据 = 后端那个**三态位**：所有行的 `map_enabled` 都是 `null`（既无产品位、
       也无条目）才算没初始化过。不看 `mapped_to`（那只是条目扇出的结果，号全停时会是空表
       而位还在），也不看前端缓存。 */
    body.innerHTML = mapBodyHTML(catalog, options, p);
    /* 没账号 = 没有资源可挂：目录照常可看，匹配钮禁用（写了也挂不上，只会在配置里留空映射）。 */
    setMode();
    /* 行开关（🔴 2026-10-02 用户「让增加的开关哪里去了呢，需求丢了么」）：需求原文是
     * **每个产品内的模型**都要有开关 ⇒ 判据 = 这一行**当前有没有目标**
     * （下拉已选 / 联想命中 / 已有映射），不是"历史上有没有映射"。旧实现只在已映射行画开关，
     * :8300 实盘 10 个产品里 9 个整列只有 `—`（zcode 2 行 / buddy 17 行 = 0 颗开关），
     * 等于需求没做。没目标的行照旧画开关，但置灰 + 悬停说清为什么按不动（不隐藏、不假装有状态）。 */
    /* 🔴 2026-10-03 用户实拍「资源池里已经关联并开启进池的怎么没显示？」追出来的**读取面假态**：
       后端对「既无产品位、也无条目」的行返回 `map_enabled = null`（= 未映射；
       `admin_accounts.py::_map_enabled` 末行 `return False if seen else None`），
       而旧写法 `!== false` 把 `null` 当成"开着" ⇒ 弹窗里同一行同时出现三个互相矛盾的信号：
       开关是绿的 + 下拉里有**自动建议预选**的模型名（`pickTarget()`，不是已落库的 `mapped_to`）
       + 状态徽章写「未映射」。用户据此以为"已关联并开启进池"，而盘上 `product_models: []`，
       资源池自然一行都不显示（资源池读的是 `models[].resources[]` 里的真绑定）。
       定版 = **开关只认后端那个位：`null` ⇒ 关**（没落库就是没进池），拨一下才写。 */
    let saving = false;                  // 保存在飞：三颗钮全禁用，别让人在半程里改
    let aiBusy = false;                  // AI 在飞：`syncFoot` 期间不许把文案/使能抢回真实态
    let armed = false;                   // 「再点一次就放弃」已经提示过

    /* 🔴 草稿制的三份状态，各自只有一个主人（上一轮那两份 `mapOn` / `mapKnown` 是"落库后的真实态"
       在前端的副本 —— 行内即落库时它们还有意义，草稿制下会变成第四套真相，一起删）：
         · 盘上真相 = `m.mapped_to` + 后端那个三态位 `m.map_enabled`（`null` = 从没落过位）；
         · 草稿     = 外层那张 `draft`（键缺失 = 这一项没动过）；
         · 画出来的 = `curTarget(i)` / `curEnabled(i)`（草稿优先，回落盘上真值）。
       🔴 2026-10-03 那条读取面假态的教训原样保留：三态位只认 `=== true`，`null` 不是"开着"。 */
    const modelOf = (i) => (catalog.models || [])[i] || {};
    const selOf = (i) => body.querySelector(`select[data-idx="${i}"]`);
    const rowOf = (i) => body.querySelector(`[data-mapsw="${i}"]`)?.closest(".list-row");
    const persistedTarget = (i) => pickTarget(modelOf(i), options);
    const persistedEnabled = (i) => {
      const m = modelOf(i);
      return mapHasBit(m) ? m.map_enabled === true : null;   // null = 盘上没这条 ⇒ 保存时按缺省进池
    };
    const staged = (i, key) => {
      const d = draft.get(i);
      return d && d[key] !== undefined ? d[key] : undefined;
    };
    const curTarget = (i) => {
      const t = staged(i, "target");
      return t === undefined ? persistedTarget(i) : t;
    };
    const curEnabled = (i) => {
      const e = staged(i, "enabled");
      if (e !== undefined) return e;
      const p = persistedEnabled(i);
      return p === null ? true : p;      // 新映射缺省进池（Q37 ② 保留，只是主人换成「保存」那一次）
    };
    const isDirty = (i) => {
      const t = staged(i, "target");
      if (t !== undefined && t !== persistedTarget(i)) return true;
      const e = staged(i, "enabled");
      if (e === undefined) return false;
      const p = persistedEnabled(i);
      if (p === null) return !!curTarget(i) && e !== true;   // 没落库 + 缺省本就是 true ⇒ 不算改过
      return e !== p;
    };
    const dirtyRows = () => (catalog.models || []).map((_m, i) => i).filter(isDirty);
    /* 脚部那颗「保存」= 脏态数的唯一出口。文案里带数（0 处禁用）：
       "点了什么都没改"与"改了 20 行还没存"在界面上绝不能长得一样。 */
    const syncFoot = () => {
      const n = dirtyRows().length;
      saveBtn.disabled = n === 0 || saving;
      saveBtn.textContent = n ? `保存（${n} 处未保存）` : "保存";
      saveBtn.title = n ? "一次提交这一屏的改动：写入配置、成功才关窗" : "没有需要保存的改动";
      if (saving || aiBusy) { aiBtn.disabled = true; } else { setMode(); }   // AI 钮的判据只有一份 = setMode
    };
    /* 只换自己那一行（旧"整格 innerHTML= 覆盖"会把同格的下拉一起吃掉 = 10-04 抓到的那条病，纪律保留）。 */
    const repaintState = (i) => {
      const row = rowOf(i);
      if (!row) return;
      const slot = row.querySelector(`[data-mapfoot="${i}"]`);
      if (slot) slot.innerHTML = mapFootHTML(modelOf(i), i, {
        target: curTarget(i),
        dirty: isDirty(i),
        hadBit: mapHasBit(modelOf(i)),
        options,
      });
      row.style.opacity = curTarget(i) && curEnabled(i) ? "" : "0.6";
    };
    /* 开关画的是**草稿位**（不是"请求成功后的回执"）：草稿制下没有请求，所以这里只读 `curEnabled`。
       🔴 没有目标的行照旧画开关但禁用 + 悬停给原因（2026-10-02 定版：绝不消失）。 */
    const mountSwitch = (i) => {
      const holder = body.querySelector(`[data-mapsw="${i}"]`);
      if (!holder) return null;
      const m = modelOf(i);
      const target = curTarget(i);
      /* 🔴 没有目标 ⇒ 牌必须画成"关"。缺省进池（`curEnabled` 对新行返回 true）说的是
         **保存之后**会是什么，不是这一格现在的状态；拿它去画牌，禁用的开关照样是绿的，
         等于替一个还不存在的映射宣称"已进池" —— 2026-10-03 那条「读取面不许撒谎」的病
         换了个位置复活，被真机门 MS2f 当场抓回（:8497 临时实例 8 行无位行全绿）。 */
      const on = target ? curEnabled(i) : false;
      holder.replaceChildren();
      const el = switchEl(on, () => {
        if (!target) { toast("该行还没有映射目标：先在「网关模型映射」里选一个", "warn"); return false; }
        stage(i, { enabled: !on });
        return false;      // 🔴 不许 switchEl 自己翻牌：位置由 `stage` 重画出来的那一个说
      });
      if (!target) {
        el.disabled = true;
        el.title = "该行还没有映射目标：先在「网关模型映射」里选一个，选完这颗开关立刻可用（保存后才入库）";
      } else if (!mapHasBit(m)) {
        el.title = `这一行还没落库（挂着「${target}」）：保存后按${on ? "进池" : "不进池"}写入配置`;
      } else {
        el.title = on ? `开启：该映射（→ ${target}）进资源池、可对外调用；改完要点「保存」才写入`
          : `关闭：该映射（→ ${target}）不进资源池、不出现在 /v1/models（映射关系保留）；改完要点「保存」才写入`;
      }
      if (saving) el.disabled = true;                     // 保存在飞：禁二次点击
      holder.append(el);
      return el;
    };
    /* 唯一的改草稿入口：改内存 + 重画那一行 + 刷新脚部。**一个 POST 都没有**。 */
    const stage = (i, patch) => {
      draft.set(i, { ...(draft.get(i) || {}), ...patch });
      armed = false;                       // 用户还在编辑 ⇒ 那句"再点一次就放弃"作废
      const warn = body.querySelector("[data-discard]");
      if (warn) warn.remove();
      const sel = selOf(i);
      if (sel && patch.target !== undefined) sel.value = patch.target;
      repaintState(i);
      mountSwitch(i);
      syncFoot();
    };
    /* 「取消 / × / 点遮罩」三条通道都走这里（modal() 的 ✕ 与遮罩 mousedown 是两条不经过按钮的
       关闭路径 —— 同一形状在 components.js 的 confirmDialog 注释里记过一次，这里照同一口径堵）。 */
    const tryClose = () => {
      const n = dirtyRows().length;
      if (!n || armed) { detachGuard(); dlg.close(); return; }
      armed = true;
      const slot = body.querySelector("#ac-map-err");
      if (slot) slot.innerHTML = `
        <div class="alert alert-warn" data-discard style="margin-bottom:12px">
          <div class="alert-title">${n} 处改动还没有保存</div>
          <div>再点一次「取消」（或右上角 ×）就全部放弃 —— 配置里一点没动；
            要继续编辑就点「保存」，或改任意一行让这句提示消失。</div></div>`;
      syncFoot();
    };
    cancelBtn.onclick = tryClose;
    dlg.el.querySelector(".modal-close").onclick = tryClose;
    const guardBackdrop = (e) => {
      if (e.target !== dlg.el || !dirtyRows().length || armed) return;
      // 捕获阶段 + stopPropagation：modal() 自己在遮罩上注册了一条 close，我这条在它之后，
      // 同一元素上注册顺序决定先后 ⇒ 只能从祖先节点的捕获阶段抢下来。
      e.stopPropagation();
      e.preventDefault();
      tryClose();
    };
    const detachGuard = () => document.removeEventListener("mousedown", guardBackdrop, true);
    document.addEventListener("mousedown", guardBackdrop, true);
    /* 下拉一改 / 采纳一颗建议 = 只改草稿（🔴 这个接线块里一次 POST 都不许有 —— 静态门 V29 钉这条）。 */
    body.querySelectorAll("select[data-idx]").forEach((sel) => {
      const i = Number(sel.dataset.idx);
      sel.onchange = () => stage(i, { target: String(sel.value || "") });
    });
    body.querySelectorAll("[data-adopt]").forEach((btn) => {
      btn.onclick = () => {
        const i = Number(btn.dataset.for);
        stage(i, { target: btn.dataset.adopt });
      };
    });
    body.querySelectorAll("[data-mapsw]").forEach((holder) => {
      mountSwitch(Number(holder.dataset.mapsw));
    });
    syncFoot();

    /* ---------- 唯一的出站腿：「AI智能匹配」= 只回填、不写盘 ---------- */
    const runAiMatch = async () => {
      // 🔴 分析范围 = **屏幕上仍显示「暂不设置」的行**（2026-10-05 第四次指示第③条）。
      //    草稿制下这个清单只能由界面给：AI 的答案不落库，所以"配置里没落位"这件事
      //    在第二次点击时依然成立 —— 只按后端那道闸门判，就会把同一批行再烧一次额度。
      const empty = (catalog.models || [])
        .map((m, i) => ({ m, i }))
        .filter(({ i }) => !curTarget(i))
        .map(({ m }) => String(m.id));
      aiBusy = true;
      aiBtn.disabled = true;
      aiBtn.textContent = "AI 匹配中…";
      const slot = () => body.querySelector("#ac-map-err");
      if (slot()) slot().innerHTML = "";
      if (!empty.length) {
        setMode();
        syncFoot();
        toast(`没有待匹配的行：${(catalog.models || []).length} 行要么已配置过、要么这一屏已经填着目标`
              + "（要重挑哪一行，先把那一行改回「暂不设置」）", "ok");
        return;
      }
      try {
        const r = await POST("/admin/api/accounts/auto-map", { product: p.id, models: empty });
        const sug = r.suggested || [];
        /* 🔴 只回填、不写盘：`written` 必须恒 false（后端这条腿从此没有写面字段），
           界面把"还没入库"这件事说在明面上 —— 否则用户带着"AI 已经帮我配好了"离开，
           而盘上一条都没写，正是这一整轮要消灭的那个形状。 */
        let filled = 0;
        sug.forEach((s) => {
          const i = (catalog.models || []).findIndex((m) => String(m.id) === String(s.model));
          if (i < 0) return;
          const sel = selOf(i);
          if (!sel || !options.some((o) => o.value === s.target)) return;   // 名单外的名字不填（后端已丢，双保险）
          stage(i, { target: s.target, enabled: persistedEnabled(i) === null ? true : curEnabled(i) });
          filled += 1;
        });
        const engine = r.via === "model"
          ? `由模型分析（${r.analyzed_by}）判定 ${r.matched_model ?? 0} 条`
          : `由正则匹配判定 ${r.matched_regex ?? 0} 条`;
        toast(`AI 匹配完成：${engine}`
              + (r.via === "model" && r.matched_regex ? `、正则补齐 ${r.matched_regex} 条` : "")
              + `；已回填 ${filled} 行到下拉里 —— 🔴 还没入库，点「保存」才写入配置`
              + (r.kept ? `；${r.kept} 行（已配置或已填值）本轮没送去分析` : ""), "ok");
        if (r.reason) toast(r.reason, "warn");
        if (r.unmatched) toast(`${r.unmatched} 行模型与正则都没给出可信目标 ⇒ 这些行保持「暂不设置」`, "warn");
        if (r.written !== false) {
          // 后端要是哪天偷偷开始写盘，这里当场说一句 —— 草稿制的契约由界面这一眼也盯一遍
          toast(`⚠️ 后端回执写着 written=${JSON.stringify(r.written)}，与"AI 只出建议"的契约不符`, "err");
        }
      } catch (e) {
        const el = body.querySelector("#ac-map-err");
        if (el) el.innerHTML = `
          <div class="alert alert-err" style="margin-bottom:12px"><div class="alert-title">AI 匹配失败</div>
            <div>${esc(e.message)}（下拉里的内容一个字没动）</div></div>`;
      }
      aiBusy = false;
      setMode();                        // 回真实态：不留「AI 匹配中…」的假忙碌
      syncFoot();
    };
    aiBtn.onclick = () => runAiMatch();

    /* ---------- 唯一的写入口：「保存」 ----------
     * 两条腿一次点完：① 有目标且改过的行 → 一次 `mappings`（新行缺省进池、改挂 = 条目整条搬）；
     * ② 改回「暂不设置」而盘上有位的行 → 逐行 `product-models/remove`。
     * 🔴 成功才关窗：任何一条被拒 / 任何一行解除失败 ⇒ 不关窗、就地列原话、草稿保留（用户改的
     *    东西绝不能因为一次失败的提交而丢）。回显按后端权威字段 `product_models`，不自己算。 */
    const saveAll = async () => {
      const rows = dirtyRows();
      if (!rows.length) { dlg.close(); return; }
      saving = true;
      syncFoot();
      const items = [];
      const unbinds = [];
      rows.forEach((i) => {
        const m = modelOf(i);
        const t = curTarget(i);
        if (t) items.push({ model: String(m.id), target: t, enabled: curEnabled(i) });
        else if (mapHasBit(m)) unbinds.push(i);
      });
      const slot = () => body.querySelector("#ac-map-err");
      if (slot()) slot().innerHTML = "";
      const lines = [];
      try {
        if (items.length) {
          const r = await POST("/admin/api/accounts/mappings", { product: p.id, items });
          const bits = new Map((r.product_models || []).map((b) => [b && b.model, b]));
          const rejected = (r.skipped || []).filter((x) => !bits.has(x.model));
          (r.product_models || []).forEach((b) => {
            const i = (catalog.models || []).findIndex((m) => String(m.id) === String(b.model));
            if (i < 0) return;
            const m = modelOf(i);
            m.mapped_to = [b.target];
            // D-3（2026-10-06 判定书裁定「仍该改」）：三态位只认 `=== true`——
            // 后端 `product_models[].enabled` 是 strict bool，但沿用 `!== false`
            // 的两态读法会把 null/undefined 折成「开着」，与同文件 :1300 建立的律
            // （null 不是开着）自相矛盾，是下一轮的误读源。
            m.map_enabled = b.enabled === true;
            draft.delete(i);                       // 盘上现在就是这一格画的样子 ⇒ 草稿交还给真相
            repaintState(i);
            mountSwitch(i);
          });
          rejected.forEach((x) => {
            const i = (catalog.models || []).findIndex((m) => String(m.id) === String(x.model));
            if (i >= 0) {                          // 被拒的那行**退回盘上的真值**（不留"看着已改"的假态）
              draft.delete(i);
              const sel = selOf(i);
              if (sel) sel.value = persistedTarget(i);
              repaintState(i);
              mountSwitch(i);
            }
          });
          if (rejected.length) {
            lines.push(...rejected.map((x) => `「${x.model}」这条未生效：${x.reason || "后端没有说明原因"}`));
          }
          const partial = (r.skipped || []).filter((x) => bits.has(x.model));
          if (partial.length) {
            lines.push(`另有 ${partial.length} 个号本轮没挂上：`
                       + String(partial[0].reason || "").split("——")[0]);
          }
          if ((r.emptied_models || []).length) {
            lines.push(`系统模型 ${r.emptied_models.join("、")} 已无任何映射，将从 /v1/models 隐藏`);
          }
          if (r.reload === false) {
            lines.push(`配置已写入，但运行态未换代：${(r.reload_errors || []).join("；")}`);
          }
          if (!rejected.length) {
            toast(`已保存：${(r.product_models || []).length} 条映射入库`
                  + `（新增 ${r.added ?? 0} · 改挂 ${r.moved ?? 0} · 已存在 ${r.already ?? 0}`
                  + ` · 进池 ${r.turned_on ?? 0} · 出池 ${r.turned_off ?? 0}）`, "ok");
          }
        }
        for (const i of unbinds) {
          const m = modelOf(i);
          try {
            const r = await POST("/admin/api/accounts/product-models/remove",
                                 { product: p.id, model: String(m.id) });
            m.map_enabled = null; m.mapped_to = [];
            draft.delete(i);
            const sel = selOf(i);
            if (sel) sel.value = "";
            repaintState(i);
            mountSwitch(i);
            if ((r.emptied_models || []).length) {
              lines.push(`系统模型 ${r.emptied_models.join("、")} 已无任何映射，将从 /v1/models 隐藏`);
            }
            if (r.reload === false) {
              lines.push(`解除已写入，但运行态未换代：${(r.reload_errors || []).join("；")}`);
            }
          } catch (e) {
            // 解除失败：这一行退回盘上的真值（位还在），并把原话留在错误槽里
            draft.delete(i);
            const sel = selOf(i);
            if (sel) sel.value = persistedTarget(i);
            repaintState(i);
            mountSwitch(i);
            lines.push(`「${m.name || m.id}」解除失败：${e.message}（这一行仍是原来的关联）`);
          }
        }
        await repaintPanel(root);
        if (lines.length) {
          const el = slot();
          if (el) el.innerHTML = `
            <div class="alert alert-warn" style="margin-bottom:12px">
              <div class="alert-title">没有全部生效（弹窗不关，改完再保存一次）</div>
              ${lines.map((x) => `<div>· ${esc(String(x))}</div>`).join("")}</div>`;
          toast("部分改动未生效，详见弹窗上方的说明", "warn");
        } else {
          detachGuard();
          dlg.close();
        }
      } finally {
        saving = false;
        armed = false;
        syncFoot();
        body.querySelectorAll("[data-mapsw]").forEach((h) => mountSwitch(Number(h.dataset.mapsw)));
      }
    };
    saveBtn.onclick = () => saveAll();
  } catch (e) {
    body.innerHTML = `
      <div class="alert alert-err"><div class="alert-title">模型目录读取失败</div>
        <div>${esc(e.message)}</div></div>`;
    return;
  }
}

/** 弹窗体：来源行（服务端口径原样给出，含 fallback 的如实声明）+ 账号操作区 + 表头 + 逐模型一行。
 *  🔴 2026-10-01 用户定版：**目录字段直接画进行内**（上下文/输出/推理/图片/工具——取不到不展示），
 *  原「模型目录」二级弹窗废除（弹窗套弹窗 = 用户明令禁止的交互，frontend-spec §7.11 红线）。
 *  🔴 2026-10-04 用户定版：**「状态」列删除**（「有关联映射配置不就是映射了吗，没关联就是没映射啊」）。
 *     这一列本来同时承载三件事，删列不等于丢信息，而是把它们交还给各自真正的对象：
 *       · 映射了什么 = 「网关模型映射」下拉的**当前值**（`pickTarget` 已改为先读已落库的 `mapped_to`）；
 *       · 进不进池   = 那颗开关本身的位置；
 *       · 没落库而正则有一条够格的建议 = 下拉下面那一行的「建议挂到 X · 采纳」（`mapFootHTML`）。 */
function mapBodyHTML(cat, options, p) {
  const models = cat.models || [];
  const src = cat.source || {};
  /* 列宽一次定死（红线：同一列表行几何必须统一）。2026-10-04 去掉状态列那一档宽度 ⇒ 省下的
     全给模型名（它本就最长）。进池列 44px = 开关 40px + 4 的余量，不用更宽把开关推到列右缘。
     配合 `.modal.wide.map-modal{width:880px}`。 */
  const grid = "display:grid;grid-template-columns:minmax(0,1fr) 56px 208px 44px;gap:12px;align-items:center";
  const th = (t) => `<span style="font-size:12px;font-weight:700;color:var(--text-faint)">${t}</span>`;
  /* 🔴 消耗声明必须在**按下之前**看得见（与「模型检测」同一纪律，2026-10-02 定版）：
     初始化 = 真发一次出站请求。放在弹窗顶部而不是脚注，因为脚注在 483 行的表里根本滚不到。 */
  /* 🔴 这颗钮常驻 ⇒ 消耗声明也**常驻**（每次点都可能真发一次出站），不再随"是否首次"隐去。
     草稿制（2026-10-05 第四次裁定）改的是后半句：答案**只回填下拉、不写配置**，
     而"还要不要再问模型"这件事由屏幕上还空着几行决定 —— 这两点都必须写在按下之前看得见的位置。 */
  const initNote = `
    <div class="alert alert-warn" style="margin-bottom:12px">
      <div class="alert-title">「AI智能匹配」= 让网关替你把这些模型挂到网关模型上</div>
      <div>将请网关内一条<b>当前可用</b>的模型（优先 flash / lite 档）逐条判断这份目录里
        <b>当前显示为「暂不设置」的</b>模型该挂到哪个网关模型；答案<b>只回填进下面的下拉，
        不写入配置</b> —— 填完要点右下角<b>「保存」</b>才入库。
        <b>真实出站一次，会消耗那条资源/账号的额度</b>；网关内没有可用模型时自动降级为正则匹配
        （不联网、零消耗）。🔴 <b>已配置过的行、以及这一屏已经填着目标的行都不再送去分析</b>
        （要重挑哪一行，先把那一行改回「暂不设置」）；一屏都填满了这颗钮一次请求都不发。</div>
    </div>`;
  const head = `
    <p class="form-hint" style="margin:0 0 12px">${esc(src.detail || "目录来源未说明")}</p>
    ${(cat.accounts || []).length ? "" : `
    <div class="alert alert-warn" style="margin-bottom:12px">
      该产品还没有账号：目录可查看，但映射要等「接入账号」后才有资源可挂。</div>`}
    ${initNote}<div id="ac-map-err"></div>`;
  if (!models.length) {
    return `${head}<p class="form-hint" style="margin:0">目录为空：未读到该产品的模型条目。</p>`;
  }
  const rows = models.map((m, i) => {
    const cur = pickTarget(m, options);          // 下拉当前显示的那个目标（已落库优先）
    const sw = `<span data-mapsw="${i}"></span>`;
    return `
      <div class="list-row" style="${grid}">
        <span style="min-width:0">
          <b>${esc(m.name || m.id)}</b>
          <span style="display:block;font-size:12px;color:var(--text-faint);margin-top:4px">
            <span class="mono">${esc(m.id)}</span>${modelFactsHTML(m)}</span>
        </span>
        <span>${ruleHTML(m)}</span>
        <span style="min-width:0">
          <select class="in" data-idx="${i}" style="width:100%" aria-label="网关模型映射 ${esc(m.name || m.id)}"
            >${optionHTML(options, cur)}</select>
          <span data-mapfoot="${i}" style="display:block;margin-top:6px">${mapFootHTML(m, i,
            { target: cur, dirty: false, hadBit: mapHasBit(m), options })}</span>
        </span>
        <span class="map-sw">${sw}</span>
      </div>`;
  }).join("");
  return `${head}
    <div class="list-card">
      <div class="list-row" style="${grid}">${th("模型")}${th("规则")}${th("网关模型映射")}${th("进池")}</div>
      ${rows}
    </div>
    <p class="form-hint" style="margin-top:12px">行内辅助信息 = 目录字段（上下文 / 输出 / 推理 / 图片 / 工具——
      取不到的不展示，不编造）；目录来源见顶部。🔴 <b>这一屏的改动要点「保存」才写入配置</b>：
      <b>网关模型映射</b> = 这一行要挂的网关模型（选一个 = 填进草稿；改另一个名字 = 改挂，
      保存时条目整条跟着搬过去（旧落点不留残条目）；改回「暂不设置」= 保存时解除，
      产品位与该产品全部账号的对应条目一起撤，映射行本身不删）。
      <b>进池开关</b>：每个模型一行、行行都有；一颗开关管该产品<b>全部账号</b>的同名映射
      （落点是配置里的产品位，不是逐号各刷一遍）。开 = 参与资源池、可被对外调用；
      关 = 不进资源池、不出现在 /v1/models（映射关系与账号凭据都保留，随时可拨回）。
      新挂上的目标<b>缺省就是进池</b>；还没有目标的行开关是灰的，选好目标后立刻可用。
      「取消」或右上角 × 会放弃所有未保存的改动（先问一次，盘上一点不会动）。</p>`;
}

/** 「这一行的映射在盘上有位」= 曾关联过（2026-10-04 起这也是"改回「暂不设置」要不要发解除"的判据）。
 *  读的是后端那个**三态位**（`_map_enabled`：`null` = 从没写入配置），与开关、进池、规格同源。 */
const mapHasBit = (m) => m.map_enabled !== null && m.map_enabled !== undefined;

/** 下拉下面那一行 = 这一行「这一格现在说的是草稿还是配置」的**唯一**常驻出口。
 *  🔴 草稿制（2026-10-05 第四次裁定）下这三条都是真话，而上一轮它们被删过一次 ——
 *    删它们不是因为话说错，是因为那一步（「保存」）不存在了：当时一改即落库，
 *    再写「未落库 · 点保存才写入」就是假陈述。现在「保存」回来了、且是**唯一**写入口，
 *    于是"改了还没入库"这件事重新需要一个常驻的地方说清（否则用户带着"AI 已经配好了"离开）。
 *   · 有草稿改动且改回「暂不设置」而盘上有位 ⇒ 「保存后解除关联」；
 *   · 有草稿改动（挂了/改了目标或拨了开关）⇒ 「已改动 · 点「保存」才入库」；
 *   · 没改动、盘上没位、正则有一条够格的建议 ⇒ 「建议挂到 X · 采纳」（点了才进草稿，
 *     不点不写、点了也还没写 —— 一句话里两个不许混）；
 *   · 其余 ⇒ 空着。下拉的值 + 开关的位置已经把"挂到哪、进不进池"说完了，
 *     「进不进池」绝不在这里再说一遍（说两遍就会有两套真相）。 */
function mapFootHTML(m, i, st) {
  const note = (t) => `<span style="font-size:12px;color:var(--text-muted)">${t}</span>`;
  const s = (st && st.target) || "";
  if (st && st.dirty) {
    if (!s && st.hadBit) return note("保存后解除关联（现在还没写入配置）");
    return note(s ? "已改动 · 点「保存」才入库" : "已清空 · 点「保存」才入库");
  }
  if (mapHasBit(m)) return "";
  const sug = suggestionOf(m, (st && st.options) || []);
  if (!sug) return "";
  return note(`建议挂到 <b class="mono">${esc(sug)}</b>（正则匹配）`
    + ` <button class="btn btn-sm" data-adopt="${esc(sug)}" data-for="${i}">采纳</button>`
    + "（只填进下拉，还要点「保存」）");
}

/** 目录字段辅助段（拼在模型 ID 后；只列上游明确给出的事实，None/缺省一律不展示）。 */
function modelFactsHTML(m) {
  const facts = [
    m.context_window != null ? `上下文 ${fmtTok(m.context_window)}` : "",
    m.max_output != null ? `输出 ${fmtTok(m.max_output)}` : "",
    m.reasoning === true
      ? `深度推理${(m.effort_levels || []).length ? `（${m.effort_levels.join("/")}）` : ""}` : "",
    m.image_input === true ? "图片输入" : "",
    m.tool_call === true ? "工具调用" : "",
  ].filter(Boolean);
  return facts.length ? ` · ${esc(facts.join(" · "))}` : "";
}

/** 消耗规则：显式 `free:true` → 免费徽章；否则非空 `rate` 文本；都没有 = `—`（**不冒充免费**）。 */
function ruleHTML(m) {
  if (m.free === true) return `<span class="badge b-brand">免费</span>`;
  if (m.rate) return `<span class="mono">${esc(m.rate)}</span>`;
  return `<span style="color:var(--text-faint)">—</span>`;
}

/** 目标下拉选项 = **一张平铺的网关模型清单**（2026-10-03 用户实拍「网关模型不用区分新建的还是之前的，
 *  输出的数据都是网关模型」⇒ 旧版给「内置目录里尚未接入」的名字加 `新建：` 前缀、并按"现有 / 新建"分两段，作废）。
 *  排序（同条指示「按照模型名称排序。按照能力等级降序排列」）：
 *    ① **名称族**自然序 —— 族 = 名单里真实存在的前缀关系（`glm-5.3-flash` 以 `glm-5.3-` 开头 ⇒ 归进 `glm-5.3`；
 *       不引入任何"档位词表"，谁是谁的前缀由数据自己说）；
 *    ② 同族内按**能力等级降序** —— 分数只取内置目录已有字段，逐级比较：
 *       上下文 → 最大输出 → 推理档位数 → 深度推理 → 图片/视频/音频输入 → 工具调用；
 *    ③ 目录里没有这个模型 = **无据可判** ⇒ 排同族最后（不编一个分数出来）；分数相同再按名称自然序。
 *  同名按 value 去重（现有模型优先，同一目标不会出现两个选项）。
 *  🔴 真机门按 `value` 比对选中项（`verify_accounts_ui_live.py:2019` 就是被 label 前缀坑过一次才改成按 value），
 *     所以去掉前缀不影响判据；但**别再把语义写进 label**。 */
function targetOptions(cfgModels, enumEntries) {
  const names = [];
  const seen = new Set();
  const add = (n) => { if (n && !seen.has(n)) { seen.add(n); names.push(n); } };
  for (const m of cfgModels) add(m && m.name);
  const spec = new Map();
  for (const e of enumEntries) {
    const n = e && e.name;
    if (!n) continue;
    add(n);
    spec.set(n, [Number(e.context_window) || 0, Number(e.max_output) || 0,
      (e.effort_levels || []).length, e.reasoning ? 1 : 0, e.image_input ? 1 : 0,
      e.video_input ? 1 : 0, e.audio_input ? 1 : 0, e.tool_call ? 1 : 0]);
  }
  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
  const nat = (a, b) => collator.compare(a, b);
  const familyOf = (n) => {
    let root = n;
    for (const c of names) {
      if (c !== n && c.length < root.length && n.startsWith(c + "-")) root = c;
    }
    return root;
  };
  const capDesc = (a, b) => {
    const x = spec.get(a), y = spec.get(b);
    if (!x && !y) return 0;
    if (!x) return 1;                       // 无据可判的排最后
    if (!y) return -1;
    for (let i = 0; i < x.length; i += 1) { if (x[i] !== y[i]) return y[i] - x[i]; }
    return 0;
  };
  const fam = new Map(names.map((n) => [n, familyOf(n)]));
  const sorted = names.slice().sort((a, b) => nat(fam.get(a), fam.get(b)) || capDesc(a, b) || nat(a, b));
  return [{ value: "", label: "暂不设置" },
    ...sorted.map((n) => ({ value: n, label: n }))];
}

/** 下拉**初始**显示哪一个目标 = **配置里的事实，一个字的建议都不掺**。
 *  草稿制（2026-10-05 第四次裁定）之后"这一格现在显示什么"分两层：初始值由本函数给（盘上挂着谁），
 *  之后由 `draft` 覆盖（用户/AI 改了什么）—— 两者都不是"我建议挂哪"，建议永远只住行内那一行小字。
 *  ① `mapped_to` = 配置里真实挂上的网关模型名（后端 `_mapped_to`：条目优先，条目为空而产品位还在时
 *     回落到位上那个 `system_model`），且它必须真在下拉清单里 —— 原生 select 塞不进清单外的 value
 *     （会显示成空白，看着像已选、提交时什么也没选）；
 *  ② 没落库 = 「暂不设置」（空）。
 *  🔴 旧写法只读建议、从不读 `mapped_to` ⇒ 一条**已挂 hy3** 的行只要建议低于阈值（或建议指向别的名字），
 *     下拉就显示「暂不设置」，把"有映射"读成"没映射"（2026-10-04 那一刀修的是这半边）。
 *  🔴 而 2026-10-04 补上的那半腿（没落库就回落成正则建议）是**反向的同一个假态**：:8300 实盘
 *     workbuddy 9 / trae 8 / raccoon 4 / loomy 3 / zcode 2 = 26 行下拉里挂着一个从没写进配置的网关模型名，
 *     配一句小字「未落库」，用户据此以为"已关联并进池"，而资源池当然一行都不显示。
 *     建议不再进下拉，改由行内**一键采纳**给（`mapFootHTML`）—— 打开弹窗不写任何东西，点一下才算。 */
function pickTarget(m, options) {
  const inList = (n) => !!n && options.some((o) => o.value === n);
  return (m.mapped_to || []).find(inList) || "";
}

/** 正则建议（`_enum_suggest` 的三级匹配，置信 ≥0.7 才敢拿出来），且只服务"一键采纳"这一件事。 */
function suggestionOf(m, options) {
  const s = (m && m.suggest) || null;
  const name = s && typeof s.confidence === "number" && s.confidence >= 0.7
    ? String(s.name || "") : "";
  return name && options.some((o) => o.value === name) ? name : "";
}

const optionHTML = (options, cur) => options.map((o) =>
  `<option value="${esc(o.value)}"${o.value === cur ? " selected" : ""}>${esc(o.label)}</option>`).join("");

/** 批量签到 / 领取（卡头「一键领取」与子侧栏「一键签到」共用）：
 *  `payload.product = null` = 全部支持签到的产品（谁参与由后端按能力位判，前端不筛）。 */
async function batchClaim(btn, payload) {
  if (!btn || btn.disabled) return;
  const label = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "执行中…";
  let r = null;
  try {
    r = await POST("/admin/api/accounts/claim-all", payload);
  } catch (e) {
    toast("批量执行失败：" + e.message, "err");
  }
  btn.innerHTML = label;                   // 钮可能已被重绘替换：改的是旧节点也不影响页面
  btn.disabled = false;
  await refreshAfter(selected, null);      // 🔴 先重绘（运营会改额度快照，且整块 innerHTML 重建）
  if (r) showClaimAllResult(r);            // 再落回执：反序则回执刚写进槽就被自己的重绘吃掉
}

/** 批量续期（2026-10-01 用户裁决：产品维度批量续期，窗口 = 5h 内失效）：
 *  `POST /admin/api/accounts/{product}/refresh-due`（缺省窗口由后端 `BATCH_RENEW_WITHIN_S` 定）。
 *  回执只说"动了谁"：续期 / 失败 / 失效时间未知（不猜、不续）三类分开列。 */
async function batchRenew(btn, p) {
  if (!btn || btn.disabled || !p) return;
  const label = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "执行中…";
  let r = null;
  try {
    r = await POST(`/admin/api/accounts/${p.id}/refresh-due`, {});
  } catch (e) {
    toast("批量续期失败：" + e.message, "err");
  }
  btn.innerHTML = label;                   // 钮可能已被重绘替换：改旧节点不影响页面
  btn.disabled = false;
  await refreshAfter(p.id, null);          // 🔴 先重绘（整块 innerHTML 重建）
  if (r) showRenewResult(r);               // 再落回执 —— 顺序反了回执就被自己抹掉（PM r5 B-R4-5）
}

function showRenewResult(r) {
  const SKIP_TEXT = { "no-expiry": "未续（失效时间未知）", cooldown: "冷却中（30 分钟内已续过）",
    terminal: "需重新登录（上游判不可续期）" };
  const rows = (r.results || []).map((x) => receiptRow(
    x.account,
    x.skipped ? (SKIP_TEXT[x.skipped] || "未续") : x.ok ? "已续期" : "失败",
    x.skipped ? "is-warn" : x.ok ? "is-ok" : "is-err",
    x.detail || "")).join("");
  const sk = r.skipped || {};
  const bits = [`续期 ${r.renewed} 个`, `失败 ${r.failed} 个`];
  if (sk["no-expiry"]) bits.push(`失效时间未知 ${sk["no-expiry"]} 个`);
  if (sk.cooldown) bits.push(`冷却中 ${sk.cooldown} 个`);
  if (sk.terminal) bits.push(`需重新登录 ${sk.terminal} 个`);
  const p = productOf(r.product);
  showBulkReceipt(`批量续期 · ${p ? p.title : r.product}`, {
    sum: `窗口 ${esc(String(r.within_hours))} 小时内到期的账号：${esc(bits.join(" · "))}。`,
    note: "「冷却中」= 30 分钟内已续过（不重复打上游）；「失效时间未知」= 上游没给到期时刻，无法判断要不要续；"
      + "「需重新登录」= 上游判不可续期。三者都**不是**失败。",
    rows, empty: "该窗口内没有到期的账号（未发起任何续期）。",
    tone: (r.failed ?? 0) > 0 ? "err" : "ok",
  });
  // 🔴 出口只有 `showBulkReceipt` 这一条（它走结果浮层，不是 modal）⇒ 批量腿"迟到回执叠第二层
  //    遮罩"那条红线由构造消失，不再需要判遮罩分支。
}

/** 批量结果：摘要行 + 每参与账号一行（分类 + 明细）；**只有失败着红**（行级 claim 同口径）。 */
function showClaimAllResult(r) {
  const p = r.product ? productOf(r.product) : null;
  const rep = r.report || {};
  // 🔴 `no_participants` 是后端给的**权威标记**（N=0 不得报成功，`test_v2_ops.py` 钉）：
  //    它成立时即使 `participants` 非空也说"没有可参与的账号"，不自己数中文串。
  const none = rep.no_participants || !(r.participants || []).length;
  showBulkReceipt(`批量签到 · ${p ? p.title : "全部支持签到的产品"}`, {
    sum: none ? "" : claimReportSum(r),
    note: "「已领」= 上游说这个号今天已经领过；「未参与」= 停用或本轮没被执行到，**不是**失败。",
    rows: none ? "" : claimReportRows(r),
    empty: "没有可参与的账号（全部停用/无账号）。",
    tone: ((rep.failed || []).length) > 0 ? "err" : "ok",
  });
}

function claimReportSum(r) {
  const rep = r.report || {};
  return `成功 ${(rep.success || []).length} · 已领 ${(rep.already_done || []).length}`
    + ` · 未参与 ${(rep.inactive || []).length} · 失败 ${(rep.failed || []).length}`;
}

function claimReportRows(r) {
  const details = r.details || {};
  return (r.participants || []).map((name) => {
    const d = details[name] || {};
    const cat = String(d.category || "");
    return receiptRow(name, CLAIM_LABEL[cat] || cat || "—",
      cat === "failed" ? "is-err" : cat === "success" ? "is-ok" : "",
      d.detail || "");
  }).join("");
}

/** 批量动作后的重绘（服务端为准）：重取视图 → rail + 面板。
 *  `root` 用于壳被重建过时重新锚定面板（正常路径与 drawShell 捕获的是同一节点）。 */
async function repaintPanel(root) {
  await fetchView();
  const panel = root && root.querySelector ? root.querySelector("#ac-panel") : null;
  if (panel) setPanelEl(panel);
  paintRail();
  paintPanel();
}

