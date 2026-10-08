/** 对接说明：面向工具端与脚本的完整调用文档（骨架 D · frontend-spec §6）。
 *
 * 🔴 全页只讲**网关视角**（2026-10-07 用户指示）：模型一律用网关模型 ID 调用；不写任何
 *    厂商相关描述（对接方/对接 AI 照本页写请求即可，不引入外部命名与外部参数形态）。
 *
 * 结构：快速开始 → 获取模型列表（字段逐条）→ 当前可服务模型（实读 · 每模型参数与对接信息）→
 * 指定推理强度 → 上下文与输出上限 → 其它参数 → 常见错误。
 *
 * 数据来源三条，全部本地同源：
 *   /admin/api/overview  调用地址（本机 / 局域网）
 *   /admin/api/config    接入密钥（**仅内存**：取第一条启用密钥调 /v1/models；
 *                        值为空则不带头。密钥值永不进 DOM —— 与「API 接入」页同一条纪律）
 *   /v1/models           实读模型清单（与工具端所见逐字段一致）
 */

import { GET, esc } from "../api.js";
import { copyText } from "../components.js";

const COPY = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`;

/* token 数按千分位精确显示（对接文档以准确为先：1,048,576 比 "1M" 少一次换算歧义） */
const tokCell = (n) => n == null
  ? `<span style="color:var(--text-faint)">未知</span>`
  : `<span class="mono">${Number(n).toLocaleString("en-US")}</span>`;

/* 规范档位（升序）——与网关侧 core/dialects.py 的 7 档同一顺序 */
const LEVEL_ROWS = [
  ["off", "关闭推理"],
  ["minimal", "最低"],
  ["low", "低"],
  ["medium", "中"],
  ["high", "高"],
  ["xhigh", "很高"],
  ["max", "最高"],
];

/* /v1/models 响应字段逐条解释（与后端 openai_compat.py::list_models 同源） */
const FIELD_ROWS = [
  ["id", "网关模型名 —— 请求里 model 字段填它（别名与大小写/日期后缀差异网关会自动归一）"],
  ["name", "展示名（给人看）"],
  ["vendor", "来源标签（只读展示字段，对接调用用不到它）"],
  ["endpoint", "chat / images —— 决定走哪个端点调用"],
  ["group", "控制台里的分组标签"],
  ["maxInputTokens", "输入窗口（这条模型最多能收多少 token）；未知时为 null"],
  ["maxOutputTokens", "输出上限（本次最多生成多少 token；思考过程的 token 是否计入以该模型为准）"],
  ["context_length", "与 maxInputTokens 同值 —— 兼容只认这个键的客户端（模型发现）"],
  ["supportsToolCall", "是否支持工具调用：true / false / null（null = 没有证据，不等于不支持）"],
  ["supportsImages", "是否支持图片输入：true / false / null"],
  ["supportsReasoning", "是否支持深度推理：true / false / null"],
  ["specStale", "true = 上面的数值里至少一个来自过期的目录缓存（昨日数据），仅供参考"],
  ["caps.thinkingLevelMap", "规范档位 → 支持情况：非 null = 支持，null = 不支持；7 个键固定齐全"],
  ["caps.thinkingFormat", "通道方言提示（由探测得出，可能为空字符串）"],
];

/* 常见错误（状态码口径 = core/scheduler.py::_exit_status_code + 入站校验） */
const ERR_ROWS = [
  ["401", "authentication_error", "缺少密钥，或密钥无效 / 已停用", "在「API 接入」页核对；停用的密钥调用会立即 401"],
  ["404", "model_not_found", "模型名不存在（未定义的网关模型名，且枚举池无匹配）", "用 GET /v1/models 返回的 id 原样填"],
  ["404", "model_disabled", "模型已停用（不会进入调用流程）", "在「网关模型管理」页开启该模型"],
  ["400", "endpoint_mismatch", "端点用错：对话模型打到了图像端点（或反之）", "chat 走 /v1/chat/completions，图像走 /v1/images/generations"],
  ["400", "—", "请求参数未被接受（错误原文原样透传）", "按错误提示调整参数；可用参数见上文能力位与该模型档位"],
  ["429", "—", "全部可用账号额度耗尽 / 被限流", "看错误信息里的「已尝试」；额度恢复后自动可用"],
  ["503", "ALL_OVER_CAPACITY", "本次输出上限超过全部可用账号的能力", "调小 max_tokens 后重试"],
  ["503", "NO_RESOURCE 等", "没有可用资源 / 重试预算耗尽（终态）", "看错误信息里的「原因」与「已尝试」；确认相关资源已启用"],
  ["503", "EMPTY_UPSTREAM_CONTENT", "流式输出零内容（重试与切换后仍无）", "重试；连续出现时检查对应账号状态"],
];

let docsData = null;

export async function renderApiDocs(root) {
  const [ov, cfg] = await Promise.all([GET("/admin/api/overview"), GET("/admin/api/config")]);
  const models = await readServingModels(cfg);
  docsData = { ov, models };
  draw(root);
}

/** 实读 /v1/models：等同工具端所见（密钥仅在内存中用于本请求，不渲染、不落 DOM）。 */
async function readServingModels(cfg) {
  const token = (cfg.gateway?.access_tokens || []).find((t) => t.enabled !== false && t.value);
  const headers = token ? { Authorization: "Bearer " + token.value } : {};
  try {
    const r = await fetch("/v1/models", { headers });
    if (!r.ok) return { err: `HTTP ${r.status}` };
    const d = await r.json();
    return { data: Array.isArray(d.data) ? d.data : [] };
  } catch (e) {
    return { err: String((e && e.message) || e) };
  }
}

/* ---------- 渲染 ---------- */

function draw(root) {
  const { ov, models } = docsData;
  const base = ov.call_addresses?.local || location.origin + "/v1";
  const lan = ov.call_addresses?.lan || "";
  root.innerHTML = `
    <p class="page-desc">工具端（Trae / Cursor / Cherry Studio 等）与脚本调用本网关的完整说明：
      怎么拿模型清单、怎么指定推理强度与输出上限、参数从哪里来。调用地址与密钥在
      <a href="#/apiaccess" style="color:var(--cool);font-weight:600;text-decoration:none">API 接入</a> 页维护。</p>

    ${cardStart("快速开始", "OpenAI 兼容 · 四个端点同一套密钥")}
      ${addrBlock(base, lan)}
      <p class="form-hint" style="margin-bottom:12px">鉴权：请求头 <code class="mono">Authorization: Bearer &lt;密钥&gt;</code>；
        Anthropic 协议端点还可用 <code class="mono">x-api-key: &lt;密钥&gt;</code>。未配置任何密钥时 /v1 免鉴权放行。</p>
      <div class="endpoint-list" style="margin-bottom:12px">
        ${endpoint("/v1/chat/completions", "对话（OpenAI 兼容）", "流式（SSE）与非流式都支持")}
        ${endpoint("/v1/messages", "对话（Anthropic 协议兼容）", "供使用该协议的客户端直连")}
        ${endpoint("/v1/models", "模型清单", "「获取模型列表」调它")}
        ${endpoint("/v1/images/generations", "图像生成", "返回 URL 或 base64（按模型能力）")}
      </div>
      ${codeTabs("quick")}
      <div class="code-shell" data-codeset="quick">
        ${codeCopy("quick", "复制当前示例")}
        ${codePre("curl", SAMPLE.quick.curl(base))}
        ${codePre("python", SAMPLE.quick.python(base), true)}
        ${codePre("node", SAMPLE.quick.node(base), true)}
      </div>
      <p class="form-hint" style="margin-top:12px">把 <b>&lt;接入密钥&gt;</b> 换成「API 接入」页生成的密钥、<b>&lt;模型 ID&gt;</b> 换成
        下方清单里的 id 即可直接运行（本网关对外只提供清单里的那些模型 ID，调用时 <code class="mono">model</code> 一律填它们）。
        用 Anthropic 协议的客户端走 /v1/messages：<code class="mono">max_tokens</code> 必填，
        <code class="mono">thinking.type</code> 支持开关，思考内容以 thinking 块返回。</p>
    ${cardEnd()}

    ${cardFlushStart("获取模型列表", "GET /v1/models · 响应字段逐条解释")}
      <div style="padding:0 16px 12px">
        <div class="code-shell">
          ${codeCopy("list", "复制命令")}
          <pre class="code-block" data-copyset="list">curl ${esc(base)}/models \\
  -H "Authorization: Bearer &lt;接入密钥&gt;"</pre>
        </div>
        <p class="form-hint" style="margin-top:8px">返回 <code class="mono">data[]</code>，每个元素是一个可对外服务的网关模型
          （只含已启用、且挂有可用资源的模型）。字段如下：</p>
      </div>
      <div class="table-wrap"><table class="tbl"><thead><tr>
        <th style="width:210px">字段</th><th>含义</th>
      </tr></thead><tbody>
        ${FIELD_ROWS.map(([k, v]) => `<tr><td class="mono strong">${esc(k)}</td><td style="color:var(--text-muted)">${esc(v)}</td></tr>`).join("")}
      </tbody></table></div>
    ${cardEnd()}

    ${cardFlushStart("当前可服务模型", `实读 GET /v1/models · ${modelCountText(models)}`)}
      <div class="table-wrap"><table class="tbl"><thead><tr>
        <th>模型 ID</th><th>端点</th><th class="num">上下文</th><th class="num">最大输出</th>
        <th>推理与档位</th><th>工具调用</th><th>图片输入</th>
      </tr></thead><tbody>
        ${modelRows(models)}
      </tbody></table></div>
      <div style="padding:12px 16px"><p class="form-hint">${modelsNote(models)}</p></div>
    ${cardEnd()}

    ${cardStart("指定推理强度", "两种写法 · 请求级覆盖资源级默认")}
      <div class="table-wrap" style="margin-bottom:12px"><table class="tbl"><thead><tr>
        <th style="width:230px">请求参数</th><th>作用</th>
      </tr></thead><tbody>
        <tr><td class="mono strong">reasoning_effort: "&lt;档位&gt;"</td>
          <td style="color:var(--text-muted)">指定思考强度；关闭用 <code class="mono">"off"</code>（<code class="mono">none</code> / <code class="mono">disabled</code> 等价）</td></tr>
        <tr><td class="mono strong">thinking: {"type": "enabled" | "disabled"}</td>
          <td style="color:var(--text-muted)">只开关、不指定强度（与 reasoning_effort 二选一即可）</td></tr>
      </tbody></table></div>
      <p class="form-hint" style="margin-bottom:12px">先看该模型 <code class="mono">supportsReasoning</code> 与
        <code class="mono">caps.thinkingLevelMap</code>：非 null 的键才是它支持的档位。支持档位：</p>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px">
        ${LEVEL_ROWS.map(([k, v]) => `<span class="badge b-muted" title="${esc(v)}"><span class="mono">${esc(k)}</span> · ${esc(v)}</span>`).join("")}
      </div>
      <div class="card-body" style="gap:8px;margin-bottom:12px">
        <p class="form-hint" style="margin:0"><b>发到不支持的档位不会报错</b>：网关按该模型档案就近换算到支持的档位（关闭类档位不参与换算）；七档之外的自定义档位名原样透传。</p>
        <p class="form-hint" style="margin:0"><b>谁优先</b>：请求里带了就用请求的；没带则用「网关模型管理」页资源池每行右侧的推理档位默认；都没设就不注入任何思考参数。</p>
        <p class="form-hint" style="margin:0"><b>思考内容在哪</b>：响应里单独放在 <code class="mono">reasoning_content</code>（非流式在 message、流式在 delta；各通道原有的思考字段名会保留一份，网关另补一份统一的 <code class="mono">reasoning_content</code>）。</p>
      </div>
      ${codeTabs("reason")}
      <div class="code-shell" data-codeset="reason">
        ${codeCopy("reason", "复制当前示例")}
        ${codePre("curl", SAMPLE.reason.curl(base))}
        ${codePre("python", SAMPLE.reason.python(base), true)}
        ${codePre("node", SAMPLE.reason.node(base), true)}
      </div>
    ${cardEnd()}

    ${cardStart("上下文与输出上限", "窗口只能读取 · 输出上限随请求指定")}
      <div class="card-body" style="gap:8px;margin-bottom:12px">
        <p class="form-hint" style="margin:0"><b>上下文窗口（输入）</b>不可通过请求设定（窗口是模型的固有属性）：
          从 GET /v1/models 的 <code class="mono">maxInputTokens</code> / <code class="mono">context_length</code> 读取；网关不改写也不截断输入，
          超过窗口的输入会被拒绝（错误原文原样透传）。留足输出预算的有效输入上限 ≈ 窗口 − 本次输出上限。</p>
        <p class="form-hint" style="margin:0"><b>输出上限可以指定</b>：请求里写 <code class="mono">max_tokens</code>（或用较新的
          <code class="mono">max_completion_tokens</code>），本次生成就封顶在这个值。没写时网关按本次实际承接账号的规格带一个缺省值，
          防止超限被拒；某账号装不下会自动换下一个账号，全部装不下返回 503（错误码 ALL_OVER_CAPACITY，调小重试即可）。</p>
        <p class="form-hint" style="margin:0"><b>优先级</b>：请求传参 &gt; 「网关模型管理」页参数配置卡里填的值 &gt; 网关按规格自动代发 &gt; 该模型自身默认。</p>
      </div>
      <div class="code-shell">
        ${codeCopy("maxtok", "复制示例")}
        <pre class="code-block" data-copyset="maxtok">curl ${esc(base)}/chat/completions \\
  -H "Authorization: Bearer &lt;接入密钥&gt;" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "&lt;模型 ID&gt;",
    "messages": [{"role": "user", "content": "写一个二分查找"}],
    "max_tokens": 8192
  }'</pre>
      </div>
    ${cardEnd()}

    ${cardStart("其它参数（温度、核采样等）", "透传为主 · 各模型参数档案在参数配置卡")}
      <p class="form-hint" style="margin:0 0 8px">
        temperature / top_p / stop / seed 等采样参数直接透传，网关只在请求没带时按「参数配置」卡补齐（仅对话端点；
        图像生成不注入任何参数）。每个模型支持哪些参数、默认值多少、哪些项已失效 —— 在
        <a href="#/models" style="color:var(--cool);font-weight:600;text-decoration:none">网关模型管理</a> 页的「参数配置」卡逐项可查，
        完整参数档案见 <a href="/help/params.html" target="_blank" rel="noopener" style="color:var(--cool);font-weight:600;text-decoration:none">参数配置详细说明</a>。</p>
    ${cardEnd()}

    ${cardFlushStart("常见错误", "状态码 · 错误码 · 怎么办")}
      <div class="table-wrap"><table class="tbl"><thead><tr>
        <th style="width:64px">状态码</th><th style="width:210px">错误码</th><th>什么意思</th><th>怎么办</th>
      </tr></thead><tbody>
        ${ERR_ROWS.map(([s, c, m, f]) => `<tr><td class="mono strong">${esc(s)}</td><td class="mono">${esc(c)}</td>` +
          `<td style="color:var(--text-muted)">${esc(m)}</td><td style="color:var(--text-muted)">${esc(f)}</td></tr>`).join("")}
      </tbody></table></div>
      <div style="padding:12px 16px"><p class="form-hint">每次请求的去向、重试与切换过程都落「请求日志」页；
        错误原文一律原样透传（网关不修饰）。</p></div>
    ${cardEnd()}
  `;
  wire(root);
}

/* ---------- 片段 ---------- */

const cardStart = (title, value) => `
  <div class="card" style="margin-bottom:12px">
    <div class="card-head"><span class="card-title">${esc(title)}</span>
      <span class="value">${esc(value)}</span></div>`;

const cardFlushStart = (title, value) => `
  <div class="card flush" style="margin-bottom:12px">
    <div class="card-head inset"><span class="card-title">${esc(title)}</span>
      <span class="value">${esc(value)}</span></div>`;

const cardEnd = () => `</div>`;

function addrBlock(base, lan) {
  const pair = (label, url) => `
    <span class="addr-group">
      <span class="addr-label">${esc(label)}</span>
      <span class="addr-value" style="display:inline-flex;align-items:center;gap:8px">
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(url)}</span>
        <button class="icon-btn sm" data-dcopy="${esc(url)}" title="复制${esc(label)}地址"
          style="width:20px;height:20px">${COPY}</button>
      </span>
    </span>`;
  return `<div class="addr-row">${pair("本机", base)}${lan ? pair("局域网", lan) : ""}</div>`;
}

const endpoint = (path, name, note) => `<div class="endpoint-item">
    <span class="mono" style="font-weight:600">${esc(path)}</span>
    <span style="color:var(--text-muted)">${esc(name)}</span>
    <span class="form-hint">${esc(note)}</span>
  </div>`;

/* 模型 ID + 行尾复制钮：配对语法与本页地址那两颗钮一致（值在左、20×20 icon 贴右、gap 8px），
   不另立第二种「值旁边有个钮」的形状。 */
const idCell = (id) => `<span style="display:inline-flex;align-items:center;gap:8px">${esc(id)}`
  + `<button class="icon-btn sm" data-idcopy="${esc(id)}" title="复制模型 ID"`
  + ` style="width:20px;height:20px">${COPY}</button></span>`;

const codeTabs = (key) => `
  <div class="code-tabs" data-codetabs="${key}">
    <button class="code-tab active" data-codelang="curl">curl</button>
    <button class="code-tab" data-codelang="python">Python</button>
    <button class="code-tab" data-codelang="node">Node.js</button>
  </div>`;

/* 复制钮住在代码块内右上角（CSS .code-shell / .code-copy）：一块一个主人，
   钮与它复制的那段代码同框，不再隔着 8px 悬在块外。 */
const codeCopy = (key, label) =>
  `<button class="btn btn-sm code-copy" data-copygroup="${key}">${esc(label)}</button>`;

const codePre = (lang, text, hidden) =>
  `<pre class="code-block${hidden ? " hidden" : ""}" data-lang="${lang}">${esc(text)}</pre>`;

function modelCountText(models) {
  if (models.err) return "实读失败";
  return `${(models.data || []).length} 个`;
}

/* 三态小徽章（✓ 支持 / ✗ 明确不支持 / ? 未知）；语义与字段表同源，提示挂在控件上 */
function capMark(v, label) {
  const txt = v === true ? "✓" : v === false ? "✗" : "?";
  const cls = v === true ? "b-ok" : "b-muted";
  const tip = v === true ? `${label}：支持`
    : v === false ? `${label}：明确不支持` : `${label}：未知（模型档案没有这项证据）`;
  return `<span class="badge ${cls}" title="${esc(tip)}">${txt}</span>`;
}

/* 「推理与档位」格：有档位列档位；支持但未列档位写明；明确不支持 / 未知各自成态 */
function reasonCell(m) {
  const lv = Object.entries(m.caps?.thinkingLevelMap || {})
    .filter(([, v]) => v).map(([k]) => k);
  if (lv.length) return `<span class="mono" style="color:var(--text-muted)">${esc(lv.join(" · "))}</span>`;
  if (m.supportsReasoning === true) return `<span class="badge b-ok">支持 · 档位未列</span>`;
  if (m.supportsReasoning === false) return `<span class="badge b-muted">不支持</span>`;
  return `<span class="badge b-muted">未知</span>`;
}

function modelRows(models) {
  if (models.err) {
    return `<tr><td colspan="7" style="color:var(--text-faint)">实读失败（${esc(models.err)}）——
      可能当前没有启用中的接入密钥可代取清单；上方字段说明不受影响，实际以工具端请求 /v1/models 为准。</td></tr>`;
  }
  const list = models.data || [];
  if (!list.length) {
    return `<tr><td colspan="7" style="color:var(--text-faint)">当前没有可对外服务的模型（模型需启用、且挂有可用资源）。</td></tr>`;
  }
  return list.map((m) => `<tr>
      <td class="mono strong">${idCell(m.id)}</td>
      <td class="mono" style="color:var(--text-muted)">${esc(m.endpoint || "chat")}</td>
      <td class="num">${tokCell(m.maxInputTokens)}</td>
      <td class="num">${tokCell(m.maxOutputTokens)}</td>
      <td>${reasonCell(m)}</td>
      <td>${capMark(m.supportsToolCall, "工具调用")}</td>
      <td>${capMark(m.supportsImages, "图片输入")}</td>
    </tr>`).join("");
}

function modelsNote(models) {
  if (models.err) return "清单实读失败不影响本页其它内容。";
  const list = models.data || [];
  const stale = list.filter((m) => m.specStale).length;
  return `调用时 <code class="mono">model</code> 字段一律填这里的网关模型 ID；`
    + `共 ${list.length} 个可服务模型（只含已启用且挂有可用资源的）。`
    + `工具/图片列：✓ 支持 · ✗ 明确不支持 · ? 未知（档案没有这项证据）。`
    + (stale ? `其中 ${stale} 条的窗口/上限取自昨日目录缓存（specStale），仅供参考。` : "");
}

/* ---------- 示例代码 ---------- */

/* 🔴 示例里的 &lt;接入密钥&gt; / &lt;模型 ID&gt; 是占位符：渲染前整体 esc()，
   textContent 复制回来仍是原文。 */
const SAMPLE = {
  quick: {
    curl: (b) => `curl ${b}/chat/completions \\
  -H "Authorization: Bearer <接入密钥>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "<模型 ID>",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": false
  }'`,
    python: (b) => `from openai import OpenAI

client = OpenAI(base_url="${b}", api_key="<接入密钥>")

resp = client.chat.completions.create(
    model="<模型 ID>",
    messages=[{"role": "user", "content": "你好"}],
)
print(resp.choices[0].message.content)`,
    node: (b) => `const BASE = "${b}";
const KEY = "<接入密钥>";

const res = await fetch(BASE + "/chat/completions", {
  method: "POST",
  headers: { Authorization: "Bearer " + KEY, "Content-Type": "application/json" },
  body: JSON.stringify({
    model: "<模型 ID>",
    messages: [{ role: "user", content: "你好" }],
    stream: false,
  }),
});
console.log(await res.json());`,
  },
  reason: {
    curl: (b) => `curl ${b}/chat/completions \\
  -H "Authorization: Bearer <接入密钥>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "<模型 ID>",
    "messages": [{"role": "user", "content": "这道题分几步解？"}],
    "reasoning_effort": "high"
  }'`,
    python: (b) => `resp = client.chat.completions.create(
    model="<模型 ID>",
    messages=[{"role": "user", "content": "这道题分几步解？"}],
    # 非标准字段走 extra_body；关闭推理换成 "off"，或 {"thinking": {"type": "disabled"}}
    extra_body={"reasoning_effort": "high"},
)
print(resp.choices[0].message.reasoning_content)
print(resp.choices[0].message.content)`,
    node: (b) => `const res = await fetch("${b}/chat/completions", {
  method: "POST",
  headers: { Authorization: "Bearer KEY", "Content-Type": "application/json" },
  body: JSON.stringify({
    model: "<模型 ID>",
    messages: [{ role: "user", content: "这道题分几步解？" }],
    reasoning_effort: "high",
  }),
});
const data = await res.json();
console.log(data.choices[0].message.reasoning_content);`,
  },
};

/* ---------- 交互 ---------- */

function wire(root) {
  root.querySelectorAll("[data-dcopy]").forEach((b) =>
    b.onclick = () => copyText(b.dataset.dcopy));
  root.querySelectorAll("[data-idcopy]").forEach((b) =>
    b.onclick = () => copyText(b.dataset.idcopy, "模型 ID 已复制"));
  for (const grp of root.querySelectorAll("[data-codeset]")) {
    const key = grp.dataset.codeset;
    const tabs = root.querySelectorAll(`[data-codetabs="${key}"] [data-codelang]`);
    tabs.forEach((b) => {
      b.onclick = () => {
        tabs.forEach((x) => x.classList.toggle("active", x === b));
        grp.querySelectorAll("pre[data-lang]").forEach((p) =>
          p.classList.toggle("hidden", p.dataset.lang !== b.dataset.codelang));
      };
    });
    const copyBtn = root.querySelector(`[data-copygroup="${key}"]`);
    if (copyBtn) copyBtn.onclick = () => {
      const vis = [...grp.querySelectorAll("pre[data-lang]")]
        .find((p) => !p.classList.contains("hidden"));
      if (vis) copyText(vis.textContent, "示例已复制");
    };
  }
  root.querySelectorAll("pre[data-copyset]").forEach((pre) => {
    const key = pre.dataset.copyset;
    const btn = root.querySelector(`[data-copygroup="${key}"]`);
    if (btn) btn.onclick = () => copyText(pre.textContent, "示例已复制");
  });
}
