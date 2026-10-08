#!/usr/bin/env node
/**
 * 「网关模型管理」参数配置卡的契约门（2026-10-04 参数卡排查轮 / 方案
 * `docs/changes/plans/20261004-model-param-card-empty-diagnosis.md`）。
 *
 * 钉的是排查抓到的三条真缺陷不许回退：
 *  R1 行集合必须来自官方**参数档案**（`param_fields`），不是只来自「有缺省值的 dict」——
 *     否则「官方有这个参数、只是没公布缺省」的模型整张卡又变空（实盘 36 条里 22 条就是这个形状）；
 *  R2 空态与行内提示**不得谎称网关没设参数**：`apply_spec_defaults` 那条腿照样注入 `max_tokens`
 *     （实盘 hy3 / hy4-preview / gemini-3.8-flash 当下就在注入），所以卡片必须有只读段，
 *     且「清空 max_tokens」的后果必须写成「改由统一规格注入 N」而不是「走供应商通道默认」；
 *  R3 依据必须**常驻可见**（本项目红线：信息不许只住 tooltip）；四档语义（可设 / 已废弃 /
 *     设了被忽略 / 传非默认报错）不许折叠；没取证的不许假装知道。
 *
 * 级别：🔴 **源码契约级**（与 `verify_map_switch_receipt.mjs` 同一性质）——它证明「界面读的是档案、
 * 四档都在、只读段在渲染、方向说对了」，不证明「浏览器里真画出来长什么样」；后者由
 * `probe_model_param_card.py`（真机 DOM 读数）承接。
 *
 * 用法：
 *   node bianyiandhuanjing/scripts/verify_model_param_card.mjs
 *   node bianyiandhuanjing/scripts/verify_model_param_card.mjs --mutate 1..12
 */
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const FILES = {
  models: "coding/model_gateway/web/static/js/pages/models.js",
  matcher: "coding/model_gateway/enums/matcher.py",
  admin: "coding/model_gateway/api/admin.py",
  main: "coding/model_gateway/main.py",
};
const OUT_NAME = { models: "models.js", matcher: "matcher.py", admin: "admin.py", main: "main.py" };

/** 按花括号配平切函数体（同 `verify_map_switch_receipt.mjs` 那一课：
 *  「找到下一个 }; 为止」会早停在模板串上，让所有判据对着残缺切片通过 = 全绿假门）。 */
function sliceFn(src, marker) {
  const start = src.indexOf(marker);
  if (start < 0) return null;
  let depth = 0, i = src.indexOf("{", start), seen = 0, inStr = null;
  for (; i < src.length; i++) {
    const ch = src[i], prev = src[i - 1];
    if (inStr) {
      if (ch === inStr && prev !== "\\") inStr = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") { inStr = ch; continue; }
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return src.slice(start, i + 1);
    }
    seen++;
    if (seen > 200000) break;
  }
  return null;
}

const M = {
  paramRow: "function paramRow(m, e, key) {",
  basis: "function paramBasisText(field, e, key) {",
  control: "function paramControl(field, key, cur) {",
  coerce: "function coerceParamFor(raw, field) {",
  injected: "function injectedElsewhereHTML(m) {",
  detail: "function drawDetail(root) {",
};

const MUTATIONS = {
  1: { file: "models", desc: "空态退回那句谎话（也未设置网关参数）",
       from: "你也还没设过任何参数 ⇒ 这些参数一律不注入",
       to: "也未设置网关参数，可在下方手动添加" },
  2: { file: "models", desc: "行集合退回只看 params_default（档案里没缺省值的键又不出行）",
       from: "    ...Object.keys(e?.param_fields || {}),\n", to: "" },
  3: { file: "models", desc: "依据列搬进 tooltip（信息只住悬停那条红线）",
       from: "overflow-wrap:anywhere\">${esc(paramBasisText(field, e, key))}</div>",
       to: "overflow-wrap:anywhere\" title=\"${esc(paramBasisText(field, e, key))}\"></div>" },
  4: { file: "models", desc: "摘掉「设了被忽略」这一档（四档塌成三档）",
       from: "  if (field.availability === \"ignored\") bits.push(\"⚠ 厂商明确忽略该参数，设了不生效\");\n",
       to: "" },
  5: { file: "models", desc: "max_tokens 清空后果又写成走供应商通道默认（方向说反的那条）",
       from: "? `清空后这一项改由统一规格注入 ${m.spec.max_output}（见下方「网关自动代发的 2 个参数」）`",
       to: "? \"清空网关值（不再注入，走供应商通道默认）\"" },
  6: { file: "models", desc: "丢掉 string_list 的逗号解析（官方形状是数组却存成字符串）",
       from: "    const arr = s.split(\",\").map((x) => x.trim()).filter(Boolean);",
       to: "    const arr = [s];" },
  7: { file: "admin", desc: "PUT 枚举池不再读回 param_fields（编辑一次就把档案抹平）",
       from: "            param_fields={str(k): dict(v) for k, v in (i.get(\"param_fields\") or {}).items()},",
       to: "" },
  8: { file: "main", desc: "把偏差提示从唯一横幅通道摘掉（用户再看不见官方那句依据）",
       from: "                \"kind\": \"param_vs_catalog\",",
       to: "                \"kind\": \"param_vs_catalog_disabled\"," },
  9: { file: "models", desc: "缺省值四态折成两态（「已知但网关不注入」那一档消失）",
       from: '        + (willInject ? " · 网关按它注入" : " · 网关不注入这一项（走供应商通道默认）")',
       to: '        + " · 网关按它注入"' },
  12: { file: "models", desc: "不看 availability 就说「按它注入」（本轮真机抓到的自写假陈述）",
        from: '  const willInject = known && field.availability === "supported" && field.inject !== false;',
        to: '  const willInject = known;' },
  11: { file: "models", desc: "把「官方推荐值」说成「官方缺省」（证据说重一档）",
        from: '  const dLabel = field.default_source === "recommended" ? "厂商推荐值" : "厂商官方缺省";',
        to: '  const dLabel = "厂商官方缺省";' },
  10: { file: "admin", desc: "同一件事再开第二条出口（写面回执一份 warnings）",
        from: "    return {\"status\": \"ok\", \"message\": \"配置已保存并生效\"}",
        to: "    return {\"status\": \"ok\", \"message\": \"配置已保存并生效\", \"warnings\": advice}" },
};

function runChecks(S) {
  const checks = [];
  const add = (id, desc, ok, detail) => checks.push({ id, desc, ok, detail: detail ?? "" });
  const row = sliceFn(S.models, M.paramRow);
  const basis = sliceFn(S.models, M.basis);
  const control = sliceFn(S.models, M.control);
  const coerce = sliceFn(S.models, M.coerce);
  const inj = sliceFn(S.models, M.injected);
  const detail = sliceFn(S.models, M.detail);

  add("P0", "六个切片全部切到（切片失败 = 后面全是假绿）",
      ![row, basis, control, coerce, inj, detail].some((x) => x === null),
      [row, basis, control, coerce, inj, detail].map((x, i) => (x === null ? "✗" : "✓") + i).join(""));

  /* ---- R1 行集合来自官方档案 ---- */
  add("P1", "空态把话指向只读段（「网关自动代发」不是黑箱；2026-10-06 人话版锚点）",
      detail !== null && /网关自动代发的 2 个参数/.test(S.models));
  /* 🔴 负向判据：那句谎话必须**全文件再也不出现**。只有正向判据的门，
     把谎话改回来照样全绿（本次 --mutate 1 第一版就是这么空转的）。 */
  add("P1b", "全文件不得出现「也未设置网关参数」（统一规格那条腿照样在注入）",
      !S.models.includes("也未设置网关参数"),
      `命中 ${(S.models.match(/也未设置网关参数/g) || []).length} 处`);
  add("P2", "pkeys 并集含 param_fields（档案里的键一律出行）",
      detail !== null && detail.includes("Object.keys(e?.param_fields || {})"));
  add("P2b", "行集合仍含用户已设的自定义键（档案外键不许消失）",
      detail !== null && detail.includes("Object.keys(m.params || {})"));

  /* ---- R3 依据常驻可见 + 四档不折叠 ---- */
  add("P3", "每行渲染 .pbasis 文本位（内容来自 paramBasisText，不是只挂 title）",
      row !== null && row.includes("class=\"pbasis\"")
      && />\$\{esc\(paramBasisText\(field, e, key\)\)\}<\/div>/.test(row));
  add("P4", "四档语义齐备：未公布缺省 / 已废弃 / 设了被忽略 / 传非默认报错",
      basis !== null && ["厂商未公布缺省值", "已标注废弃", "厂商明确忽略该参数", "对非默认值直接返回报错"]
        .every((t) => basis.includes(t)));
  add("P4b", "缺省值四态齐备：官方缺省 / 官方推荐值 / 已知但网关不注入 / 未公布",
      basis !== null && basis.includes("网关按它注入")
      && basis.includes("厂商推荐值")
      && basis.includes("网关不注入这一项（走供应商通道默认）"));
  add("P4c", "🔴「按它注入」只在 supported 档说（rejected/ignored 即便有缺省也不参与派生）",
      basis !== null && basis.includes('known && field.availability === "supported"')
      && basis.includes("field.inject !== false"));
  add("P5", "官方范围与官方枚举跟着档案进依据列（不在前端写死）",
      basis !== null && basis.includes("官方范围") && basis.includes("官方枚举"));
  add("P6", "没档案的键写「未取证」，不假装知道形状",
      basis !== null && basis.includes("未取证：该键不在这个模型的官方参数档案里"));

  /* ---- R2 只读段 + max_tokens 方向 ---- */
  add("P7", "只读段渲染进参数卡（md-injected + injectedElsewhereHTML(m)）",
      detail !== null && detail.includes("md-injected") && detail.includes("injectedElsewhereHTML(m)"));
  add("P8", "只读段两条腿齐：max_tokens 走统一规格、推理档走资源池（2026-10-06 人话版锚点）",
      inj !== null && inj.includes("max_tokens") && inj.includes("reasoning_effort")
      && inj.includes("上限代发") && inj.includes("资源池"));
  add("P9", "行内 × 的提示按合并规格的实际值说（改由统一规格注入）",
      row !== null && row.includes("改由统一规格注入"));
  add("P10", "同一条方向在两处回执口径一致（× 与清空都写，命中 ≥2）",
      (S.models.match(/改由统一规格注入/g) || []).length >= 2,
      `命中 ${(S.models.match(/改由统一规格注入/g) || []).length} 处`);

  /* ---- 控件形状跟着档案走 ---- */
  add("P11", "布尔与枚举给下拉（不让人手打 true/false 或猜档位）",
      control !== null && (control.match(/<select/g) || []).length >= 2);
  add("P12", "string_list 按逗号解析成数组（官方形状是数组的键不许存成字符串）",
      coerce !== null && coerce.includes("string_list") && coerce.includes("split(\",\")"));
  add("P13", "无档案键回落老规矩猜类型（自定义键既不报错也不假装）",
      coerce !== null && coerce.includes("return coerceParam(s)"));
  add("P14", "参数名候选用 datalist 且标注在册/未取证两种身份",
      /md-pkey-list/.test(S.models) && S.models.includes("该模型官方在册")
      && S.models.includes("通用参数名，未取证"));

  /* ---- 后端：一套真相 + 只标不拦 ---- */
  add("P15", "matcher：params_default 由档案派生，与手填冲突即拒（不并存两套）",
      S.matcher.includes("PARAM_INJECTABLE") && S.matcher.includes("与由")
      && /不一致/.test(S.matcher));
  add("P16", "matcher：只有 supported 档参与注入（ignored/rejected/deprecated 不进 params_default）",
      /PARAM_INJECTABLE: frozenset\[str\] = frozenset\(\{"supported"\}\)/.test(S.matcher));
  add("P17", "matcher：档案形状写错在加载期就报（kind/availability/values/类型四类都查）",
      ["不在册", "须为 dict", "没有 values", "不匹配"].every((t) => S.matcher.includes(t)));
  add("P18", "admin：GET 导出的 param_fields 在 PUT 里读回来（不吞档案）",
      /param_fields=\{str\(k\): dict\(v\) for k, v in \(i\.get\("param_fields"\) or \{\}\)\.items\(\)\}/
        .test(S.admin));
  add("P19", "admin：坏档案是 400 不是 500",
      S.admin.includes("枚举池条目不合法"));
  add("P20", "main：偏差提示走唯一横幅通道（config_warnings 里 kind=param_vs_catalog）",
      S.main.includes("def _params_vs_catalog") && S.main.includes('"kind": "param_vs_catalog"'));
  add("P20b", "🔴 负向：admin 写面不得再回执第二份（同一件事两个出口 = 将来只改一个）",
      !S.admin.includes('"warnings": advice'),
      `命中 ${(S.admin.match(/"warnings": advice/g) || []).length} 处`);
  add("P21", "main：判据只认目录规范名（不拿别名/模糊命中去评别人的参数）",
      S.main.includes("param_advice(m.name, m.params)") && !S.main.includes("param_advice(pool.match"));

  return checks;
}

function main() {
  const argv = process.argv.slice(2);
  const mutIdx = argv.indexOf("--mutate");
  const override = {};
  if (mutIdx >= 0) {
    const key = argv[mutIdx + 1];
    const spec = MUTATIONS[key];
    if (!spec) {
      console.log(`变异编号须为 1~${Object.keys(MUTATIONS).length}`);
      process.exit(2);
    }
    const src = readFileSync(join(ROOT, FILES[spec.file]), "utf8");
    const hits = src.split(spec.from).length - 1;
    if (hits !== 1) {   // 变异没落地 = 假撤证：先怀疑变异，别判「门太松」
      console.log(`✗ 变异 #${key} 锚点在 ${FILES[spec.file]} 命中 ${hits} 次（要求恰 1 次）⇒ 本次撤证作废`);
      process.exit(3);
    }
    const dir = mkdtempSync(join(tmpdir(), "paramcard-mut-"));
    const out = join(dir, OUT_NAME[spec.file]);
    writeFileSync(out, src.replace(spec.from, () => spec.to), "utf8");
    override[spec.file] = out;
    console.log(`变异 #${key}：${spec.desc}（写入 ${out}）`);
  }
  const S = {};
  for (const [k, rel] of Object.entries(FILES)) {
    S[k] = readFileSync(override[k] || join(ROOT, rel), "utf8");
  }
  const checks = runChecks(S);
  const failed = checks.filter((c) => !c.ok);
  console.log(`\n文件：${Object.values(FILES).join(" · ")}`);
  for (const c of checks) {
    console.log(`  ${c.ok ? "✓" : "✗"} ${c.id} ${c.desc}${c.detail ? "  ｜ " + c.detail : ""}`);
  }
  console.log("\n" + "=".repeat(56));
  console.log(`合计：${checks.length - failed.length} 通过 / ${failed.length} 失败`);
  failed.forEach((c) => console.log(`  ✗ ${c.id} ${c.desc}｜${c.detail}`));
  process.exit(failed.length ? 1 : 0);
}

main();
