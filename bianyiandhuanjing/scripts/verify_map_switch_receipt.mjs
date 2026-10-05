#!/usr/bin/env node
/**
 * 「模型映射」弹窗的**回执与写入口**契约门（债务 Q33-债8 的界面那一半 / 台账 §16 起）。
 *
 * 钉的是这个弹窗对 `POST /admin/api/accounts/mappings` 那份回执的读法。后端那份 `skipped`
 * 有**两种成因**（`admin_accounts.py::_write_mappings_phase3` 逐字写了两种措辞，判据
 * INT-85 / INT-86 已在 pytest 侧钉死）：
 *   ① 组合冲突 ⇒ **整条拒**：产品位与任何条目都没动 ⇒ `product_models` 里没有这一条；
 *   ② 按号权益闸门 ⇒ **位已写、其余号已挂**，只是这个号自己的目录说没有 ⇒ `product_models`
 *      里有这一条，`skipped` 里只有那个号。
 * 前端一旦把两者混为一谈，就会出现「盘上已写而界面回滚」或反之 —— 两套真相，Q33 要消灭的形状。
 *
 * 🔴 2026-10-05 第四次裁定（草稿制）之后本门的形状：
 *   写面从**四条**（整表保存 / 逐行开关 / 逐行选目标 / 初始化落库）收成**一条** = `saveAll`；
 *   `runAiMatch` 从此**不是写面**（只出建议、零写盘）⇒ 本门反过来钉它「体内一次写请求都不许有」；
 *   `stage` / `mountSwitch` 是草稿腿 ⇒ 判据 = 体内零 POST + 开关位置由草稿画；
 *   新增 E 组：取消必须真能取消（三条关闭通道同走 `tryClose`，有脏态先警告再关）。
 *   旧判据一条没删，逐条换了主人（变更理由写在每条 desc 或本注释里）。
 *
 * 🔴 本门是**源码契约级**（不是 DOM 行为级）：它证明「读的是权威字段、回滚只在整条拒那一支、
 * 部分跳过不回滚」。DOM 行为级由 `verify_accounts_ui.mjs`（假 DOM）与
 * `verify_accounts_ui_live.py`（真 Chrome）承接。
 *
 * 用法：
 *   node bianyiandhuanjing/scripts/verify_map_switch_receipt.mjs
 *   node bianyiandhuanjing/scripts/verify_map_switch_receipt.mjs --file /tmp/mutated.js
 *   node bianyiandhuanjing/scripts/verify_map_switch_receipt.mjs --mutate 1..18   # 成对撤证
 *   （1~5 钉草稿腿 `mountSwitch` / `stage`，6~10 钉 AI 腿 `runAiMatch`，
 *    11~15 钉唯一写入口 `saveAll`，16~18 钉取消腿 `tryClose` 与三条关闭通道）
 */
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const PAGE = join(ROOT, "coding/model_gateway/web/static/js/pages/accounts.js");

/** 从 `const xxx = (…) => {` 起按**花括号配平**切出整个函数体。
 *  🔴 不用「到下一个 `};` 为止」那种写法 —— 函数体内有模板串与嵌套对象，早停在半句上
 *     会让所有判据对着一份残缺切片通过（复验教训：切片抓错 = 全绿假门）。 */
function sliceFn(src, marker) {
  const start = src.indexOf(marker);
  if (start < 0) return null;
  let depth = 0, i = src.indexOf("{", start), seen = 0, inStr = null;
  for (; i < src.length; i++) {
    const ch = src[i], prev = src[i - 1];
    if (inStr) {                              // 跳过字符串/模板串内的花括号
      if (ch === inStr && prev !== "\\") inStr = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") { inStr = ch; continue; }
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return src.slice(start, i + 2);   // 含结尾 `};`
    }
    seen++;
    if (seen > 200000) break;                 // 病态输入兜底，不让门挂死
  }
  return null;
}
const sliceSwitch = (src) => sliceFn(src, "const mountSwitch = (i) => {");
const sliceStage = (src) => sliceFn(src, "const stage = (i, patch) => {");
const sliceAi = (src) => sliceFn(src, "const runAiMatch = async () => {");
const sliceSave = (src) => sliceFn(src, "const saveAll = async () => {");
const sliceClose = (src) => sliceFn(src, "const tryClose = () => {");

/* ---------- 变异表：每条只改语法、不改结构；锚点歧义时用 slice 限定到某个函数体内 ----------
 * 🔴 前导空格不是区分手段（`if (r.reload === false) {` 这类同形句曾让 `--mutate` 命中 3 次，
 *    2026-10-04 概念审计 A6-B-1 实跑抓到）⇒ 一律靠 `slice` 把锚点关进函数体。 */
const MUTATIONS = {
  1: { desc: "开关点击改成**当场写盘**（草稿制的形状就是「改一格不动盘」，这一改整套作废）",
       slice: "mountSwitch",
       from: "        stage(i, { enabled: !on });",
       to: "        stage(i, { enabled: !on });\n        POST(\"/admin/api/accounts/mappings\", { product: p.id, items: [] });" },
  2: { desc: "拨完让 switchEl 自己翻牌（位置从此有两个主人：它翻的那一个 与 草稿那一个）",
       slice: "mountSwitch",
       from: "        return false;      // 🔴 不许 switchEl 自己翻牌：位置由 `stage` 重画出来的那一个说",
       to: "        return true;      // 撤证：让 switchEl 自己翻" },
  3: { desc: "保存在飞不禁二次点击（半程里改的东西会被提交回来的回执盖掉）",
       slice: "mountSwitch",
       from: "      if (saving) el.disabled = true;                     // 保存在飞：禁二次点击",
       to: "      // 撤证：不禁二次点击" },
  4: { desc: "stage 里长出 POST（「唯一的改草稿入口」不再唯一，写入口回到两处）",
       slice: "stage",
       from: "      draft.set(i, { ...(draft.get(i) || {}), ...patch });",
       to: "      draft.set(i, { ...(draft.get(i) || {}), ...patch });\n      POST(\"/admin/api/accounts/mappings\", { product: p.id, items: [] });" },
  5: { desc: "用户接着编辑而那句「再点一次就放弃」不撤（恐吓常驻 = 用户以为改不动了）",
       slice: "stage",
       from: "      if (warn) warn.remove();",
       to: "      if (false) warn.remove();" },
  6: { desc: "AI 回填完顺手写盘（正是第四次裁定要杀的那件事：机器给的结果不经人确认就进配置）",
       slice: "runAiMatch",
       from: "        const sug = r.suggested || [];",
       to: "        const sug = r.suggested || [];\n        await POST(\"/admin/api/accounts/mappings\", { product: p.id, items: sug });" },
  7: { desc: "吞掉降级原因（用户分不清这次是模型判的还是正则猜的）",
       slice: "runAiMatch",
       from: "      if (r.reason) toast(r.reason, \"warn\");",
       to: "      if (false) toast(r.reason, \"warn\");" },
  8: { desc: "匹配结束不收回真实态（`aiBusy` 不复位 ⇒ 那颗钮永远写着「AI 匹配中…」= 假忙碌）",
       slice: "runAiMatch",
       from: "      aiBusy = false;",
       to: "      // 撤证：不复位" },
  9: { desc: "名单外的目标也往下拉里填（原生 select 塞不进清单外的 value ⇒ 显示成空白，看着像已选）",
       slice: "runAiMatch",
       from: "          if (!sel || !options.some((o) => o.value === s.target)) return;",
       to: "          if (!sel) return;" },
  10: { desc: "屏幕都填满了还发请求（白烧一次出站 = 上一轮 V27/MS8 那条病的又一形状）",
        slice: "runAiMatch",
        from: "      if (!empty.length) {",
        to: "      if (false) {" },
  11: { desc: "保存提交**整表**而不是脏行（没改过的行被按当前界面值重写一遍，含缺省位）",
        slice: "saveAll",
        from: "      const rows = dirtyRows();",
        to: "      const rows = (catalog.models || []).map((_m, i) => i);" },
  12: { desc: "不读后端权威字段（`rejected` 恒空 ⇒ 整条被拒也 toast 成功 + 关窗）",
        slice: "saveAll",
        from: "          const rejected = (r.skipped || []).filter((x) => !bits.has(x.model));",
        to: "          const rejected = [];" },
  13: { desc: "items 为空也发 `mappings`（后端对「全部 target 为空」回 400 ⇒ 一次纯解除的保存必红）",
        slice: "saveAll",
        from: "        if (items.length) {",
        to: "        if (true) {" },
  14: { desc: "有失败也关窗（用户带着「保存过了」离开，而盘上那几条根本没动 = 复验 R10 抓过的同一形状）",
        slice: "saveAll",
        from: "        if (lines.length) {",
        to: "        if (false && lines.length) {" },
  15: { desc: "解除判据丢掉后端那个位（无位的行也发 remove ⇒ 从没配置过的行吃一次写请求）",
        slice: "saveAll",
        from: "        else if (mapHasBit(m)) unbinds.push(i);",
        to: "        else unbinds.push(i);" },
  16: { desc: "有脏态也一步关窗（用户一次误点就丢掉一屏编辑）",
        slice: "tryClose",
        from: "      if (!n || armed) { detachGuard(); dlg.close(); return; }",
        to: "      detachGuard(); dlg.close(); return;" },
  17: { desc: "关窗时不摘 document 上的捕获监听（每次开弹窗漏一条，越积越多且会打到下一个弹窗上）",
        from: "    const detachGuard = () => document.removeEventListener(\"mousedown\", guardBackdrop, true);",
        to: "    const detachGuard = () => {};" },
  18: { desc: "「取消」绕过 tryClose 直接关（三条关闭通道只堵一条 = 静默丢弃）",
        from: "    cancelBtn.onclick = tryClose;",
        to: "    cancelBtn.onclick = () => { detachGuard(); dlg.close(); };" },
  /* 19~22 钉本轮**新写**的四条腿（新判据没有反例 = 等于没有断言；19 就是真机门 MS2f
     在 :8497 当场抓回的那条缺陷本身，修完之后它必须还能红）。 */
  19: { desc: "无目标的行也按缺省位画牌（绿色开关替一个不存在的映射宣称「已进池」= MS2f 抓的那条）",
        slice: "mountSwitch",
        from: "      const on = target ? curEnabled(i) : false;",
        to: "      const on = curEnabled(i);" },
  20: { desc: "AI 腿又去读写面那份 `product_models`（草稿制下后端不再返回它 ⇒ 一行也填不出来，"
             + "而界面照样 toast「匹配完成」）",
        slice: "runAiMatch",
        from: "        const sug = r.suggested || [];",
        to: "        const sug = r.product_models || [];" },
  21: { desc: "草稿整键覆盖（只改 target 就把已改的 enabled 抹回缺省 = 用户拨过的开关被吃掉）",
        slice: "stage",
        from: "      draft.set(i, { ...(draft.get(i) || {}), ...patch });",
        to: "      draft.set(i, patch);" },
  22: { desc: "被拒的那行不回退（盘上没写而下拉留着新目标 = 「看着已改」的假态）",
        slice: "saveAll",
        from: "              draft.delete(i);\n              const sel = selOf(i);",
        to: "              const sel = selOf(i);" },
};

function runChecks(src, sw, st, ai, save, close) {
  const checks = [];
  const add = (id, desc, ok, detail) => checks.push({ id, desc, ok, detail });
  const postCount = (s) => (s ? (s.match(/POST\(/g) || []).length : -1);

  /* ---------- A · 进池开关 = 只改草稿（旧 A 组钉的是 `togglePool` 当场写盘，随草稿转换主人） ---------- */
  add("A0", "切到 `mountSwitch`（开关这条腿的落点；切片失败 = 后面全是假绿）",
      sw !== null, sw ? `长度 ${sw.length}` : "未找到 `const mountSwitch = (i) => {`");
  if (sw === null) return checks;
  add("A1", "点击只调 `stage`，函数体内**零 POST**（草稿制的形状：改一格不动盘）",
      /stage\(i, \{ enabled: !on \}\);/.test(sw) && postCount(sw) === 0,
      `stage 调用=${/stage\(i, \{ enabled: !on \}\);/.test(sw)}｜POST 数=${postCount(sw)}`);
  add("A2", "没有目标的行：toast 说清 + `return false`（不静默，也不许留下翻牌后的假位置）",
      /if \(!target\) \{ toast\(/.test(sw) && /return false;/.test(sw),
      (sw.match(/if \(!target\)[^\n]*/)?.[0] ?? "(没找到无目标支)").slice(0, 90));
  add("A3", "拨完仍 `return false` —— 位置由 `stage` 重画的那一个说，不许 switchEl 自己翻牌",
      /return false;[^\n]*不许 switchEl 自己翻牌/.test(sw),
      `return false 共 ${(sw.match(/return false;/g) || []).length} 处`);
  add("A4", "画出来的位置读草稿（`curEnabled(i)`），不读盘上那个位、也不读前端的第二份状态；"
     + "🔴 且**没有目标的行牌位必须画成关**——缺省进池说的是「保存之后」，拿它画当前状态"
     + "就是替一个还不存在的映射宣称「已进池」（真机门 MS2f 在 :8497 抓回的那条）",
      /const on = target \? curEnabled\(i\) : false;/.test(sw) && !/mapOn/.test(sw),
      (sw.match(/const on = [^\n]*/)?.[0] ?? "(没读 curEnabled)").slice(0, 60));
  add("A5", "保存在飞禁二次点击（半程里改的东西会被提交回来的回执盖掉）",
      /if \(saving\) el\.disabled = true;/.test(sw),
      (sw.match(/if \(saving\)[^\n]*/)?.[0] ?? "(没禁二次点击)").slice(0, 60));
  add("A6", "悬停文案把「点保存才写入」说在位（三态各一条）且零「即落库」这种上一轮的旧口径",
      (sw.match(/保存/g) || []).length >= 3 && !/拨一下即落库|点一下即落库/.test(sw),
      `「保存」出现 ${(sw.match(/保存/g) || []).length} 处｜旧口径回潮=${/拨一下即落库|点一下即落库/.test(sw)}`);

  /* ---------- B · stage = 唯一的改草稿入口 ---------- */
  add("B0", "切到 `stage`（草稿的唯一改入口）", st !== null,
      st ? `长度 ${st.length}` : "未找到 `const stage = (i, patch) => {`");
  if (st !== null) {
    add("B1", "stage 体内**零 POST**（写入口一旦多一处，「保存 = 唯一写入口」就是空话）",
        postCount(st) === 0, `POST 数=${postCount(st)}`);
    add("B2", "改完重画那一行 + 摘掉「再点一次就放弃」那句过期恐吓 + 刷新脚部那颗钮",
        /warn\) warn\.remove\(\);/.test(st) && /repaintState\(i\);/.test(st)
        && /mountSwitch\(i\);/.test(st) && /syncFoot\(\);/.test(st),
        `撤警告=${/warn\.remove\(\)/.test(st)}｜重绘=${/repaintState\(i\);/.test(st)}｜刷脚部=${/syncFoot\(\);/.test(st)}`);
    add("B3", "草稿是**合并写**（`{ ...旧, ...新 }`）：只改 target 不许把已改的 enabled 抹掉",
        /draft\.set\(i, \{ \.\.\.\(draft\.get\(i\) \|\| \{\}\), \.\.\.patch \}\);/.test(st),
        (st.match(/draft\.set[^\n]*/)?.[0] ?? "(整键覆盖)").slice(0, 90));
    add("B4", "缺省位不在这里第二次算（stage 体内不许出现「? true :」这类二次判定）",
        !/\? true :/.test(st), `出现二次判定=${/\? true :/.test(st)}`);
  }

  /* ---------- C · AI 这条腿 = 只出建议、零写盘（旧 C 组钉的是 `initMap` 当场落库，随本轮反转） ---------- */
  add("C0", "切到 `runAiMatch`（第三个生产者从此不写盘，本门反过来钉它）", ai !== null,
      ai ? `长度 ${ai.length}` : "未找到 `const runAiMatch = async () => {`");
  if (ai !== null) {
    add("C1", "读的是建议字段 `suggested`，不再读写面那份 `product_models`",
        /const sug = r\.suggested \|\| \[\];/.test(ai) && ai.indexOf("r.product_models") < 0,
        `suggested=${/r\.suggested/.test(ai)}｜残留 product_models 读取=${ai.indexOf("r.product_models") >= 0}`);
    add("C2", "名单外的目标不填（后端已丢一次，界面再挡一次 = 双保险）",
        /if \(!sel \|\| !options\.some\(\(o\) => o\.value === s\.target\)\) return;/.test(ai),
        (ai.match(/if \(!sel[^\n]*/)?.[0] ?? "(没挡)").slice(0, 90));
    add("C3", "AI 不关窗（用户要看回填了什么；关窗 = 把结果藏起来）",
        ai.indexOf("dlg.close()") === -1,
        `dlg.close() 命中 ${(ai.match(/dlg\.close\(\)/g) || []).length} 处（必须 0）`);
    add("C4", "降级原因与「没给出可信目标的那几行」都不许吞（一次部分成功不能被报成全成功）",
        /if \(r\.reason\) toast\(r\.reason, "warn"\);/.test(ai) && /if \(r\.unmatched\) toast\(/.test(ai),
        `reason=${/if \(r\.reason\)/.test(ai)}｜unmatched=${/if \(r\.unmatched\) toast\(/.test(ai)}`);
    add("C5", "各条出口都把那颗钮收回真实态（`aiBusy` 复位 + ≥2 次 `setMode()`），不留「AI 匹配中…」的假忙碌",
        /aiBusy = false;/.test(ai) && (ai.match(/setMode\(\);/g) || []).length >= 2,
        `setMode() 数=${(ai.match(/setMode\(\);/g) || []).length}｜aiBusy 复位=${/aiBusy = false;/.test(ai)}`);
    add("C6", "🔴 这条腿体内**一次写请求都不许有**（`mappings` / `product-models/remove` 各 0 处）",
        ai.indexOf("accounts/mappings") < 0 && ai.indexOf("product-models/remove") < 0,
        `mappings=${(ai.match(/accounts\/mappings/g) || []).length}｜remove=${(ai.match(/product-models\/remove/g) || []).length}`);
    add("C7", "屏幕没有空行 ⇒ 早退，且早退在**发请求之前**（白烧一次额度 = 上一轮 V27/MS8 那条病）",
        ai.indexOf("if (!empty.length) {") >= 0
        && ai.indexOf("if (!empty.length) {") < ai.indexOf("POST(\"/admin/api/accounts/auto-map\""),
        `早退@${ai.indexOf("if (!empty.length) {")}｜auto-map POST@${ai.indexOf("POST(\"/admin/api/accounts/auto-map\"")}`);
    add("C8", "后端要是恢复写盘，界面当场指出（`written !== false` 这条自查在册）",
        /if \(r\.written !== false\) \{/.test(ai),
        (ai.match(/if \(r\.written[^\n]*/)?.[0] ?? "(没自查)").slice(0, 60));
  }

  /* ---------- D · 保存 = 唯一写入口（旧 B 组「行内即时落库」的判据整体搬到这里，一条不松） ---------- */
  add("D0", "切到 `saveAll`（唯一写入口）", save !== null,
      save ? `长度 ${save.length}` : "未找到 `const saveAll = async () => {`");
  if (save !== null) {
    add("D1", "只提交**脏行**（`dirtyRows()`）：没改过的行不许被按当前界面值重写一遍",
        /const rows = dirtyRows\(\);/.test(save),
        (save.match(/const rows = [^\n]*/)?.[0] ?? "(整表提交)").slice(0, 60));
    add("D2", "按后端**权威字段** `product_models` 分两种成因（整条拒 vs 位已写个别号没挂），不解析文案",
        /const bits = new Map\(\(r\.product_models \|\| \[\]\)\.map\(/.test(save)
        && /const rejected = \(r\.skipped \|\| \[\]\)\.filter\(\(x\) => !bits\.has\(x\.model\)\);/.test(save)
        && /const partial = \(r\.skipped \|\| \[\]\)\.filter\(\(x\) => bits\.has\(x\.model\)\);/.test(save),
        (save.match(/const rejected[^\n]*/)?.[0] ?? "(没分因)").slice(0, 90));
    add("D3", "两条腿各自早退：`items` 为空不发 `mappings`；下拉空而盘上**没位**的行不发 `remove`",
        /if \(items\.length\) \{/.test(save) && /else if \(mapHasBit\(m\)\) unbinds\.push\(i\);/.test(save),
        `空 items 不发=${/if \(items\.length\)/.test(save)}｜没位不发解除=${/else if \(mapHasBit\(m\)\) unbinds\.push/.test(save)}`);
    add("D4", "有失败**不关窗**（`dlg.close()` 只许待在无失败那一支）且原话就地列出",
        /if \(lines\.length\) \{/.test(save)
        && /else \{[\s\S]{0,80}detachGuard\(\);[\s\S]{0,80}dlg\.close\(\);/.test(save)
        && /没有全部生效（弹窗不关/.test(save),
        `close 总数=${(save.match(/dlg\.close\(\)/g) || []).length}｜不关窗文案=${/没有全部生效（弹窗不关/.test(save)}`);
    add("D5", "被拒 / 解除失败的那些行**退回盘上的真值**（`draft.delete(i)` + 下拉回写），"
       + "不许留下「下拉已改而盘上没写」的假态",
        (save.match(/draft\.delete\(i\);/g) || []).length >= 4
        && /sel\.value = persistedTarget\(i\);/.test(save),
        `draft.delete 共 ${(save.match(/draft\.delete\(i\);/g) || []).length} 处｜回写下拉=${/sel\.value = persistedTarget\(i\);/.test(save)}`);
    add("D6", "「写入 ≠ 生效」两条腿都读（`reload === false` 各一次）+ 掉出声明的模型如实说",
        (save.match(/if \(r\.reload === false\) \{/g) || []).length === 2
        && /r\.emptied_models/.test(save),
        `reload 支=${(save.match(/if \(r\.reload === false\) \{/g) || []).length} 处（需 2）`);
    add("D7", "本地态只在后端确认写入之后才改，且按回执逐行回显（`m.mapped_to = [b.target]`）",
        /m\.mapped_to = \[b\.target\];/.test(save) && /m\.map_enabled = b\.enabled !== false;/.test(save),
        (save.match(/m\.mapped_to = \[b\.target\];[^\n]*/)?.[0] ?? "(没按回执回显)").slice(0, 60));
    add("D8", "保存成功后重绘本页（`repaintPanel`）—— 弹窗外那一屏不许还挂着旧态",
        /await repaintPanel\(root\);/.test(save),
        (save.match(/repaintPanel[^\n]*/)?.[0] ?? "(没重绘)").slice(0, 60));
  }

  /* ---------- E · 取消必须真能取消（10-04 那条律随草稿制复活） ---------- */
  add("E0", "切到 `tryClose`（三条关闭通道的共同落点）", close !== null,
      close ? `长度 ${close.length}` : "未找到 `const tryClose = () => {`");
  if (close !== null) {
    add("E1", "有脏态时第一次只**警告**（两步确认，不静默丢弃用户的工作）",
        /if \(!n \|\| armed\) \{ detachGuard\(\); dlg\.close\(\); return; \}/.test(close)
        && /data-discard/.test(close),
        (close.match(/if \(!n \|\| armed\)[^\n]*/)?.[0] ?? "(一步就关)").slice(0, 90));
    // 🔴 判"摘监听"不许只看**调用点还在**（`() => {}` 那种空壳照样过）—— 必须钉住定义里真的
    //    removeEventListener 了同一把 handler。变异 #17 就是把定义换成空壳，第一次跑当场逃掉。
    add("E2", "真关之前摘掉 document 上的捕获监听（定义里真 removeEventListener，不是空壳），"
       + "且函数体内 `dlg.close()` 恰一处（没有第二条关窗路径）",
        /detachGuard\(\);/.test(close) && (close.match(/dlg\.close\(\);/g) || []).length === 1
        && /const detachGuard = \(\) => document\.removeEventListener\("mousedown", guardBackdrop, true\);/.test(src),
        `dlg.close 次数=${(close.match(/dlg\.close\(\);/g) || []).length}｜摘监听=调用 ${/detachGuard\(\);/.test(close)}`
        + `／定义 ${/const detachGuard = \(\) => document\.removeEventListener/.test(src)}`);
    add("E3", "三条通道（取消钮 / 右上角 × / 点遮罩空白）都指向 `tryClose`"
       + "（modal() 自带两条不经过按钮的关闭路径 = components.js 的 confirmDialog 注释里记过的同一形状）",
        /cancelBtn\.onclick = tryClose;/.test(src)
        && /\.modal-close"\)\.onclick = tryClose;/.test(src)
        && /document\.addEventListener\("mousedown", guardBackdrop, true\);/.test(src),
        `取消=${/cancelBtn\.onclick = tryClose;/.test(src)}｜×=${/\.modal-close"\)\.onclick = tryClose;/.test(src)}`
        + `｜遮罩=${/guardBackdrop, true\);/.test(src)}`);
  }
  return checks;
}

function main() {
  const argv = process.argv.slice(2);
  const fileArg = argv.indexOf("--file");
  let target = fileArg >= 0 ? argv[fileArg + 1] : PAGE;
  const mutIdx = argv.indexOf("--mutate");
  if (mutIdx >= 0) {
    const key = argv[mutIdx + 1];
    const spec = MUTATIONS[key];
    if (!spec) {
      console.log("变异编号须为 1~22（1~5 草稿腿 / 6~10 AI 腿 / 11~15 保存腿 / 16~18 取消腿 / 19~22 本轮新判据的反例）");
      process.exit(2);
    }
    const src = readFileSync(PAGE, "utf8");
    // 可选 `slice`：把锚点的命中计数与替换**限定在某个函数体内**（同形回执分支的唯一可靠区分手段）
    const SLICE_MARKERS = {
      mountSwitch: "const mountSwitch = (i) => {",
      stage: "const stage = (i, patch) => {",
      runAiMatch: "const runAiMatch = async () => {",
      saveAll: "const saveAll = async () => {",
      tryClose: "const tryClose = () => {",
    };
    let base = src, scope = "整份文件";
    if (spec.slice) {
      const marker = SLICE_MARKERS[spec.slice];
      if (!marker) { console.log(`✗ 变异 #${key} 的 slice 名不在册：${spec.slice}`); process.exit(2); }
      const body = sliceFn(src, marker);
      if (body === null) {
        console.log(`✗ 变异 #${key} 切片失败：找不到 ${marker} ⇒ 撤证作废`);
        process.exit(3);
      }
      base = body; scope = `${spec.slice} 函数体（${body.length} 字符）`;
    }
    const hits = base.split(spec.from).length - 1;
    if (hits !== 1) {   // 🔴 变异没落地 = 假撤证：先怀疑变异，别判「门太松」
      console.log(`✗ 变异 #${key} 锚点在${scope}命中 ${hits} 次（要求恰 1 次）⇒ 变异未落地，本次撤证作废`);
      process.exit(3);
    }
    const dir = mkdtempSync(join(tmpdir(), "mapdraft-mut-"));
    const mutated = join(dir, "accounts.js");
    const newBase = base.replace(spec.from, () => spec.to);   // 函数替换：避免 `$&` 之类被展开
    const outText = spec.slice ? src.replace(base, () => newBase) : newBase;
    if (spec.slice && outText === src) {
      console.log(`✗ 变异 #${key} 切片未能回写（函数体在整份文件里不唯一）⇒ 撤证作废`);
      process.exit(3);
    }
    writeFileSync(mutated, outText, "utf8");
    target = mutated;
    console.log(`变异 #${key}：${spec.desc}（范围=${scope}，写入 ${mutated}）`);
  }
  const src = readFileSync(target, "utf8");
  const checks = runChecks(src, sliceSwitch(src), sliceStage(src), sliceAi(src),
                 sliceSave(src), sliceClose(src));
  const failed = checks.filter((c) => !c.ok);
  console.log(`\n文件：${target.replace(ROOT + "/", "")}`);
  for (const c of checks) {
    console.log(`  ${c.ok ? "✓" : "✗"} ${c.id} ${c.desc}${c.detail ? "  ｜ " + String(c.detail).slice(0, 200) : ""}`);
  }
  console.log("\n" + "=".repeat(56));
  console.log(`合计：${checks.length - failed.length} 通过 / ${failed.length} 失败`);
  failed.forEach((c) => console.log(`  ✗ ${c.id} ${c.desc}｜${String(c.detail).slice(0, 200)}`));
  process.exit(failed.length ? 1 : 0);
}

main();
