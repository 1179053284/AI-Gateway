import json, sys
from collections import defaultdict
sys.path.insert(0, 'coding')
from model_gateway.enums.matcher import BUILTIN_ENTRIES, normalize_name
rows = json.load(open('/tmp/vg/rows2.json'))
raw = json.load(open('/tmp/vg/raw.json'))
cfg = raw['cfg']
sys_norm = {normalize_name(m['name']) for m in cfg['models']}
cat_names = {normalize_name(e.name) for e in BUILTIN_ENTRIES}
CANON = {'z-ai': '智谱 GLM', 'moonshotai': 'Moonshot Kimi', 'deepseek': 'DeepSeek', 'openai': 'OpenAI',
         'anthropic': 'Anthropic', 'google': 'Google', 'x-ai': 'xAI', 'spacexai': 'xAI',
         'sensenova': '商汤 SenseNova', 'tencent': '腾讯混元', 'bytedance-seed': '字节 Seed/Doubao',
         'bytedance': '字节', 'xiaomi': '小米 MiMo', 'minimax': 'MiniMax', 'stepfun': '阶跃星辰',
         'qwen': 'Qwen（阿里，命名空间原文）', 'mistralai': 'Mistral AI', 'nvidia': 'NVIDIA',
         'meta': 'Meta', 'meta-llama': 'Meta（Llama）', 'cohere': 'Cohere', 'amazon': 'Amazon',
         'perplexity': 'Perplexity', 'moonshot': 'Moonshot Kimi'}
cat_vendor = {}
for e in BUILTIN_ENTRIES:
    cat_vendor[normalize_name(e.name)] = e.vendor
    for a in (e.aliases or []):
        cat_vendor.setdefault(normalize_name(str(a)), e.vendor)
def vl(r):
    v = str(r['vendor'])
    if v.startswith('（'):
        return v
    base = v.lstrip('~')
    if base in CANON:
        return CANON[base]
    return cat_vendor.get(r['canon']) or base
def st(c):
    if c in sys_norm: return '已有'
    if c in cat_names: return '在册未建'
    return '没有'
L = ['', '## 附录 A：逐供应方的未关联清单（按厂商分组）', '',
     '每行 = `供应商目录名` → 规范化模型名 → 厂商（证据等级）→ 该供应商目录给的规格 → 网关现状。', '']
for sp in raw['products']:
    u = [r for r in rows if r['sup'] == sp['id'] and not r['mapped']]
    if not u:
        continue
    L.append(f'### {sp["title"]} (`{sp["id"]}`) — 未关联 {len(u)} / {len(sp["models"])} 条')
    L.append('')
    g = defaultdict(list)
    for r in u:
        g[vl(r)].append(r)
    for v, rs in sorted(g.items(), key=lambda kv: -len(kv[1])):
        L.append(f'- **{v}**（{len(rs)} 条）')
        for r in sorted(rs, key=lambda x: x['canon']):
            spec = f"ctx={r['ctx'] or '—'} out={r['out'] or '—'}"
            extra = []
            if r.get('reasoning') is not None:
                extra.append('推理' + ('✓' if r['reasoning'] else '✗'))
            if r.get('image') is not None:
                extra.append('图' + ('✓' if r['image'] else '✗'))
            if r.get('mode'):
                extra.append('模式:' + r['mode'])
            L.append(f"  - `{r['mid']}` → `{r['canon']}` [{r['ev']}] · {spec}"
                     + (' · ' + ' '.join(extra) if extra else '') + f" · 网关：{st(r['canon'])}")
    L.append('')
open('docs/changes/20261003-vendor-model-gap.md', 'a').write('\n'.join(L) + '\n')
print('appendix lines', len(L), 'rows', sum(1 for r in rows if not r['mapped']))
