import json, re, sys
from collections import Counter, defaultdict
sys.path.insert(0, 'coding')
from model_gateway.enums.matcher import BUILTIN_ENTRIES, normalize_name

rows = json.load(open('/tmp/vg/rows2.json'))
raw = json.load(open('/tmp/vg/raw.json'))
cfg = raw['cfg']
sys_norm = {normalize_name(m['name']): m['name'] for m in cfg['models']}
res_by_id = {r['id']: r for r in cfg['resources']}
cat_vendor = {}
for e in BUILTIN_ENTRIES:
    cat_vendor[normalize_name(e.name)] = e.vendor
    for a in (e.aliases or []):
        cat_vendor.setdefault(normalize_name(str(a)), e.vendor)
cat_names = {normalize_name(e.name) for e in BUILTIN_ENTRIES}
supplied_by = {normalize_name(m['name']): 0 for m in cfg['models']}
for m in cfg['models']:
    n = 0
    for e in (m.get('resources') or []):
        r = res_by_id.get(e['resource']) or {}
        if r.get('product'):
            n += 1 if e.get('mapping_enabled') else 0
        elif e.get('enabled'):
            n += 1
    supplied_by[normalize_name(m['name'])] = n

# 厂商标签归一：内置目录 vendor 字段优先（官网取证的正式厂商名），否则用供应商命名空间原文
CANON_VENDOR = {'z-ai': '智谱 GLM', 'moonshotai': 'Moonshot Kimi', 'moonshot': 'Moonshot Kimi',
                'deepseek': 'DeepSeek', 'openai': 'OpenAI', 'anthropic': 'Anthropic', 'google': 'Google',
                'x-ai': 'xAI', 'spacexai': 'xAI', 'sensenova': '商汤 SenseNova',
                'tencent': '腾讯（混元 Hy 系列）', 'bytedance-seed': '字节 Seed/Doubao',
                'bytedance': '字节（另一命名空间）', 'xiaomi': '小米（MiMo）', 'minimax': 'MiniMax',
                'stepfun': '阶跃星辰（Step）', 'qwen': 'Qwen 系列（命名空间原文 qwen）',
                'mistralai': 'Mistral AI', 'nvidia': 'NVIDIA', 'meta': 'Meta',
                'meta-llama': 'Meta（Llama 系列）', 'cohere': 'Cohere', 'amazon': 'Amazon',
                'perplexity': 'Perplexity', 'stealth': '（路由聚合别名，背后厂商不定）',
                'openrouter': '（路由聚合别名，背后厂商不定）', 'inclusionai': 'InclusionAI（Ling）',
                'aion-labs': 'Aion Labs', 'upstage': 'Upstage（Solar）', 'sakana': 'Sakana AI',
                'nousresearch': 'Nous Research', 'rekaai': 'Reka AI', 'microsoft': 'Microsoft',
                'ibm-granite': 'IBM Granite', 'thinkingmachines': 'Thinking Machines',
                'poolside': 'Poolside', 'meituan': '美团（LongCat）', 'baidu': '百度（文心）',
                'kwaipilot': '快手（Kat Coder）', 'arcee-ai': 'Arcee AI', 'writer': 'Writer',
                'fireworks': 'Fireworks', 'liquid': 'Liquid AI', 'inception': 'Inception',
                'prism-ml': 'PrismML', 'dots-studio': 'dots.mm', 'sao10k': 'Sao10K（社区微调）',
                'thedrummer': 'TheDrummer（社区微调）', 'undi95': 'undi95（社区微调）',
                'gryphe': 'Gryphe（社区微调）', 'cognitivecomputations': 'Cognitive Computations',
                'apodex': 'Apodex', 'mancer': 'Mancer（社区托管）', 'relace': 'Relace',
                'morph': 'Morph', 'typesafe': 'Typesafe', 'perceptron': 'Perceptron',
                'unbiased': 'Unbiased（Pareto）', 'inference-net': 'Inference.net',
                'anthracite-org': 'Anthracite（社区微调）', 'nex-agi': 'Nex AGI'}
def vlabel(r):
    v = str(r['vendor'])
    if v.startswith('（'):
        return v
    alias = v.startswith('~')            # `~厂商/*-latest` = 取最新的路由别名
    base = v.lstrip('~')
    if base in CANON_VENDOR:
        return CANON_VENDOR[base]
    hit = cat_vendor.get(r['canon'])
    if hit:
        return hit
    return ('~' + base) if alias else base
for r in rows:
    r['vlabel'] = vlabel(r)

un = [r for r in rows if not r['mapped']]
sug_n = sum(1 for r in un if r['sug'] and normalize_name(r['sug']) in sys_norm)
by_vendor = defaultdict(list)
for r in un:
    by_vendor[r['vlabel']].append(r)

def status(canon):
    if canon in sys_norm:
        return '已建·有供给' if supplied_by[canon] else '已建·空池'
    if canon in cat_names:
        return '内置目录在册（未建网关模型）'
    return '网关完全没有'

L = []
A = L.append
A('# 供应商 × 供应商模型名 关联缺口盘点（2026-10-03，:8300 实读 · 只读）')
A('')
A('**口径（按用户 2026-10-03 的纠正定版）**：')
A('- **厂商** = 模型的生产公司（DeepSeek、智谱、月之暗面…）；同一个模型不管几家转售，厂商只有一个；')
A('- **供应商** = 本网关的接入产品/账号（CodeBuddy、WorkBuddy、LobsterAI、Qoder、QoderCN、Trae、Cline、Loomy、Raccoon、ZCode）；')
A('- **网关模型** = 把各供应商的同一个供应商模型名统一成一个名字并标准化参数（`models[]` + 内置目录规格取证）。')
A('')
A('所以本文回答的是：**各供应商目录里的模型，有多少还没关联到网关模型；这些模型分别属于哪个厂商**，')
A('供你决定要把哪些供应商模型名接入网关配置。')
A('')
A('**厂商归属的证据等级**（每行都带标记，绝不口头归属）：')
A('- `E1` = 内置目录（官网取证那一份）里该模型名已有 `vendor` 字段；')
A('- `E2` = 供应商目录的 id 自带厂商命名空间（如 `moonshotai/kimi-k3`、`z-ai/glm-5.3-flashx`）；')
A('- `E3` = 同一模型名/同一名词在别处带命名空间 ⇒ 继承（如 Raccoon 的 `GLM-5.3` 从 `z-ai/glm-5.3` 继承）；')
A('- `T`  = 供应商自定义档位/路由（`Auto`/`Ultimate`/`openrouter/fusion`…），**背后不是固定供应商模型名**；')
A('- `E4` = 无内部证据，需你或官网取证确认。')
A('')
ev = Counter(r['ev'] for r in un)
A(f'未关联条目 **{len(un)} / {len(rows)}**；证据分布：E1 {ev["E1"]} · E2 {ev["E2"]} · E3a {ev["E3a"]} · E3b {ev["E3b"]} · '
  f'档位 T {ev["T"]} · 未确认 E4 {ev["E4"]}')
A('')
A('## 1. 厂商汇总（未关联的模型按厂商归并）')
A('')
A('| 厂商 | 未关联模型数 | 涉及供应商 | 供应商列表 | 网关现状（按模型计） |')
A('|---|---|---|---|---|')
rows_sum = []
for v, rs in by_vendor.items():
    canons = {r['canon'] for r in rs}
    sups = sorted({r['sup_title'] for r in rs})
    st = Counter(status(c) for c in canons)
    st_s = '、'.join(f'{k} {n}' for k, n in sorted(st.items(), key=lambda kv: -kv[1]))
    rows_sum.append((v, len(canons), len(sups), sups, st_s))
for v, n, s, sups, st_s in sorted(rows_sum, key=lambda x: (-x[1], x[0])):
    A(f'| {v} | {n} | {s} | {", ".join(sups)} | {st_s} |')
A('')
A('## 2. 分层：按"接入一个网关模型能解开几个供应商"排序')
A('')
A('### 2a 网关已有该供应商模型名、只是没挂映射 ⇒ 立刻可挂（不需要新配置）')
tier = defaultdict(list)
for r in un:
    tier[status(r['canon'])].append(r)
t = tier['已建·有供给'] + tier['已建·空池']
g1 = defaultdict(list)
for r in t:
    g1[(r['vlabel'], r['canon'])].append(r)
A(f'共 **{len(g1)} 个供应商模型名**、{len(t)} 条目录条目（含 2 个空池模型 `glm-5.3` / `glm-5.3-flash`）：')
A('')
A('| 厂商 | 网关模型 | 供应商（原始名） | 供应商给的规格 | 网关现状 |')
A('|---|---|---|---|---|')
for (v, c), rs in sorted(g1.items(), key=lambda kv: (kv[0][0], kv[0][1])):
    who = '；'.join(f'{x["sup_title"]}:{x["mid"]}' for x in rs[:4]) + ('…' if len(rs) > 4 else '')
    spec = '；'.join(sorted({(f'ctx={x["ctx"]}' if x.get('ctx') else 'ctx=—') + '/' +
                            (f'out={x["out"]}' if x.get('out') else 'out=—') for x in rs})[:4])
    A(f'| {v} | `{c}` | {who} | {spec} | {status(c)} |')
A('')
A(f'对账：网关自己的建议腿（`_enum_suggest`，只看 id）能挂 {sug_n} 条 / 11 个模型名；'
  f'本盘点按**展示名 + id 双路**归一得到 {len(t)} 条 / {len(g1)} 个模型名 ⇒ '
  f'**多出的 {len(t) - sug_n} 条就是缺口 B 的实测规模**（Qoder/QoderCN 的代号 id、Loomy/Raccoon 的倍率后缀名）。')
A('')
A('### 2a′ 被最多供应商同时提供、但网关还没有的模型（接入优先级排序用）')
g3b = defaultdict(list)
for r in tier['网关完全没有']:
    g3b[r['canon']].append(r)
A('| 网关模型候选名 | 厂商 | 供应商数 | 供应商 | 供应商目录给的规格 |')
A('|---|---|---|---|---|')
cands = [(c, rs) for c, rs in g3b.items()
         if not rs[0]['vlabel'].startswith('（') and not any(x['ev'] == 'T' for x in rs)]
for c, rs in sorted(cands, key=lambda kv: (-len({x['sup'] for x in kv[1]}), -len(kv[1]), kv[0]))[:30]:
    sups = sorted({x['sup_title'] for x in rs})
    if len(sups) < 2:
        break
    spec = '；'.join(sorted({f"{x['sup']} ctx={x['ctx'] or '—'} out={x['out'] or '—'}"
                             for x in rs})[:4])
    A(f'| `{c}` | {rs[0]["vlabel"]} | {len(sups)} | {", ".join(sups)} | {spec} |')
A('')
A('### 2b 内置目录（官网取证）已有、但还没建成网关模型 ⇒ 建一个解开一批')
g2 = defaultdict(list)
for r in tier['内置目录在册（未建网关模型）']:
    g2[(r['vlabel'], r['canon'])].append(r)
A(f'共 **{len(g2)} 个**：')
A('')
A('| 厂商 | 模型 | 想用它（已被建议挂到这个名）的供应商条目 | 内置目录规格 |')
A('|---|---|---|---|')
bent = {normalize_name(e.name): e for e in BUILTIN_ENTRIES}
for (v, c), rs in sorted(g2.items(), key=lambda kv: (-len(kv[1]), kv[0][0])):
    e = bent.get(c)
    spec = f'ctx={getattr(e, "context_window", None)} / out={getattr(e, "max_output", None)} / ' \
           f'tool={getattr(e, "tool_call", None)} / img={getattr(e, "image_input", None)}' if e else '—'
    A(f'| {v} | `{c}` | {len(rs)} 条：' + '；'.join(f'{x["sup_title"]}:{x["mid"]}' for x in rs[:3]) +
      ('…' if len(rs) > 3 else '') + f' | {spec} |')
A('')
A('### 2c 网关与内置目录都完全没有 ⇒ 要接入就得先做官网取证 + 新建供应商模型名')
g3 = defaultdict(list)
for r in tier['网关完全没有']:
    g3[r['vlabel']].append(r)
A(f'按厂商计 **{len(g3)} 个厂商、{sum(len(v) for v in g3.values())} 条模型**：')
A('')
A('| 厂商 | 未关联模型数 | 涉及供应商 | 例子（供应商目录原名） |')
A('|---|---|---|---|')
for v, rs in sorted(g3.items(), key=lambda kv: (-len({x["canon"] for x in kv[1]}), kv[0])):
    canons = sorted({x['canon'] for x in rs})
    sups = sorted({x['sup_title'] for x in rs})
    A(f'| {v} | {len(canons)} | {", ".join(sups)} | ' + ', '.join(f'`{c}`' for c in canons[:6]) +
      ('…' if len(canons) > 6 else '') + ' |')
A('')
A('### 2d 不是供应商模型名：供应商自定义档位 / 路由（要挂必须先问供应商这个档位实际打到哪个模型）')
for r in [x for x in un if x['ev'] == 'T']:
    A(f'- {r["sup_title"]}：`{r["mid"]}`（展示名 {r["disp"]}）')
A('')
A('### 2e 厂商未确认（E4，全部 6 条）')
for r in [x for x in un if x['ev'] == 'E4']:
    A(f'- {r["sup_title"]}：`{r["mid"]}`（展示名 {r["disp"]}）')
A('')
A('## 3. 逐供应商：未关联条度数 × 厂商分布')
A('')
A('| 供应商 | 目录 | 已关联 | 未关联 | 未关联里的厂商分布（前 8） |')
A('|---|---|---|---|---|')
for sp in raw['products']:
    rs = [r for r in rows if r['sup'] == sp['id']]
    u = [r for r in rs if not r['mapped']]
    c = Counter(r['vlabel'] for r in u)
    A(f'| {sp["title"]} | {len(rs)} | {len(rs) - len(u)} | {len(u)} | ' +
      ', '.join(f'{k} {v}' for k, v in c.most_common(8)) + ('…' if len(c) > 8 else '') + ' |')
A('')
A('## 4. 判读注意（不掩盖的部分）')
A('')
A('1. **Cline 是聚合转售方**：它一家 485 条、目录里带 **64 个厂商命名空间**（含大量长尾：`sao10k`、`thedrummer`、`inception`、`rekaai`…）。')
A('   这不代表网关要接 64 家厂商 —— 2c 表里 Cline 独有的长尾我建议按"是否真有供应商账号能给量"筛，'
  '不要按目录里有没有名字筛。')
alias_n = sum(1 for x in un if str(x['mid']).startswith('~'))
A('2. **`~openai/gpt-astra-latest` 这类 `~厂商/*-latest`（本表共 ' + str(alias_n) + ' 条）'
  '是"永远取最新"的别名**，规格随时间漂移 ⇒ 不适合直接做成网关模型'
  '（网关模型要的是标准参数，别名会把漂移引进来）。')
A('3. **同一供应商模型名的多个变体**（`:batch` / `:free` / `-preview` / `-0731` 日期 / `Prime` / `FlashX` / `Highspeed`）'
  '在网关里是**独立模型还是别名**，是要你定的口径：我按字面分开计数，没有替你把 `deepseek-v4-pro-0813` 折进 `deepseek-v4-pro`。')
A('4. **规格数值不可当官网取证用**：2a/2b 表里的 `ctx/out` 是**供应商目录给的数**，用于对照；'
  '新建内置目录条目仍须按项目规矩逐条官网取证（`docs/specs/` 里那条约束）。')
A('5. `tool_call` 全表 645 条都是 `null`（这些产品的目录不声明工具能力，`upstream/zcode/product.py:81` 口径），'
  '所以供应商模型名的工具位只能来自内置目录或 `caps_overrides`。')
open('docs/changes/20261003-vendor-model-gap.md', 'w').write('\n'.join(L) + '\n')
print('lines =', len(L))
print('未关联', len(un), '| 厂商数', len(by_vendor), '| 2a', len(g1), '| 2b', len(g2), '| 2c 厂商', len(g3), '模型', sum(len({x['canon'] for x in v}) for v in g3.values()))
