import json, re, sys
from collections import Counter, defaultdict
sys.path.insert(0, 'coding')
from model_gateway.enums.matcher import BUILTIN_ENTRIES, normalize_name

raw = json.load(open('/tmp/vg/raw.json'))
cfg = raw['cfg']
sys_norm = {normalize_name(m['name']): m['name'] for m in cfg['models']}
res_by_id = {r['id']: r for r in cfg['resources']}
bits = cfg.get('product_models') or []
def live_by_norm(n):
    name = sys_norm.get(n)
    if not name: return 0
    m = cfg['models'][[i for i, x in enumerate(cfg['models']) if x['name'] == name][0]]
    c = 0
    for e in (m.get('resources') or []):
        r = res_by_id.get(e['resource']) or {}
        if r.get('product'): c += 1 if e.get('mapping_enabled') else 0
        elif e.get('enabled'): c += 1
    return c

PLAN_PREFIX = {'cline-free', 'cline-pass'}   # 只有这两个是供应方自己的套餐位；其余 `x/y` 前缀按厂商命名空间处理
cat_vendor, cat_alias = {}, {}
for e in BUILTIN_ENTRIES:
    cat_vendor[normalize_name(e.name)] = e.vendor
    for a in (e.aliases or []):
        cat_alias[normalize_name(str(a))] = e.vendor

def tokens(s):
    s = normalize_name(s)
    return [t for t in re.split(r'[^a-z]+', s) if len(t) >= 3]

# 先扫一遍：命名空间证据（供应商目录里的 `厂商/模型` 形态）
ns_by_tok = defaultdict(Counter)
ns_by_full = defaultdict(Counter)
rows = []
for sp in raw['products']:
    for m in sp['models']:
        mid = str(m['id'])
        ns, tail = '', mid
        if '/' in mid:
            h, t = mid.split('/', 1)
            if h.lower() not in PLAN_PREFIX:
                ns, tail = h, t
            else:
                tail = t
        mode = ''
        mm = re.search(r':(free|batch|short)$', tail)
        if mm:
            mode = mm.group(1); tail = tail[:mm.start()]
        disp = str(m.get('name') or '')
        # 人读名：展示名与 id 不同且含数字或已知系列词 ⇒ 用展示名（供应商代号 id 的情形）
        human = tail
        # 展示名优先：带版本号，或首词是已知系列词（`DeepSeek-Flash` 这类无版本号也要走展示名）
        if disp and normalize_name(disp) != normalize_name(mid):
            dt = tokens(disp)
            known_head = bool(dt) and (dt[0] in {k.split('-')[0] for k in list(cat_vendor) + list(ns_by_tok)}
                                       or any(dt[0] in k for k in cat_vendor))
            if re.search(r'\d', disp) or known_head:
                human = disp
        canon = re.split(r'[·|]', str(human))[0]
        canon = re.sub(r'\s*[:\-]?\s*(免费|限时免费)\s*$', '', canon)
        canon = normalize_name(canon)
        if ns:
            ts2 = [t for t in tokens(tail) if t not in ('flash', 'lite', 'pro', 'max', 'mini',
                                                        'plus', 'turbo', 'preview', 'free', 'batch',
                                                        'short', 'latest', 'prime', 'thinking',
                                                        'reasoning', 'highspeed', 'ultraspeed',
                                                        'code', 'vision', 'omni', 'instruct')]
            for t in ts2:
                ns_by_tok[t][ns] += 1
            if len(ts2) >= 2:
                ns_by_tok['-'.join(ts2[:2])][ns] += 1
            ns_by_full[canon][ns] += 1
        rows.append(dict(sup=sp['id'], sup_title=sp['title'], mid=m['id'], ns=ns, mode=mode,
                         disp=disp, tail=tail, canon=canon, human_from_disp=(human is disp),
                         ctx=m.get('context_window'), out=m.get('max_output'),
                         reasoning=m.get('reasoning'), image=m.get('image_input'),
                         effort=m.get('effort_levels'), free=m.get('free'), rate=m.get('rate'),
                         mapped=[t for t in (m.get('mapped_to') or []) if t],
                         map_state=('开' if m.get('map_enabled') is True
                                    else '关' if m.get('map_enabled') is False else '未映射'),
                         sug=(m.get('suggest') or {}).get('name')))

TIER = {'auto', 'fast', 'balanced', 'primary', 'deep', 'ultimate', 'performance', 'efficient',
        'default', 'premium', 'router', 'fusion', 'multimodal', 'code', 'free', 'bodybuilder',
        'pro', 'max', 'lite', 'mini'}
def vendor_of(r):
    c = r['canon']
    if str(r['ns']).lower() == 'openrouter':
        return '（路由聚合别名，背后厂商不定）', 'T'
    if c in cat_vendor: return cat_vendor[c], 'E1'
    if c in cat_alias: return cat_alias[c], 'E1'
    if r['ns']: return r['ns'], 'E2'
    if ns_by_full.get(c): return ns_by_full[c].most_common(1)[0][0], 'E3a'
    GEN = {'flash', 'lite', 'pro', 'max', 'mini', 'plus', 'turbo', 'preview', 'code', 'vision',
           'omni', 'fast', 'small', 'thinking', 'reasoning', 'highspeed', 'ultraspeed', 'latest',
           'instruct', 'chat', 'base', 'exp', 'v2', 'v3', 'v4', 'r1', 's', 'x'}
    ts = [t for t in tokens(c) if t not in GEN]
    for cand in ('-'.join(ts[:2]), ts[0] if ts else ''):
        if cand and ns_by_tok.get(cand):
            return ns_by_tok[cand].most_common(1)[0][0], 'E3b'
    # 首词属于内置目录某供应商的模型名前缀族（sensenova* / glm* / kimi*…）
    if ts:
        for e in BUILTIN_ENTRIES:
            if normalize_name(e.name).startswith(ts[0]):
                return e.vendor, 'E1b'
    toks = tokens(c)
    if not toks or not re.search(r'\d', c) and not toks:
        return '（供应商自定义档位）', 'T'
    if not re.search(r'\d', c) and (set(toks) & TIER or len(toks) == 1 and toks[0] in TIER):
        return '（供应商自定义档位）', 'T'
    return '（未确认）', 'E4'

for r in rows:
    r['vendor'], r['ev'] = vendor_of(r)
    r['tier'] = (r['ev'] == 'T')

un = [r for r in rows if not r['mapped']]
print('条目', len(rows), '| 已关联网关模型', len(rows) - len(un), '| 未关联', len(un))
print('未关联里：供应商自定义档位', sum(1 for r in un if r['tier']),
      '| 未确认厂商', sum(1 for r in un if r['ev'] == 'E4'))
print('证据分布（未关联）:', dict(Counter(r['ev'] for r in un)))
vc = Counter(r['vendor'] for r in un if not r['tier'])
print('未关联的厂商 top：', dict(vc.most_common(25)))
print()
print('=== 未确认厂商（E4）的条目，逐条看是否能人工指认 ===')
for r in [x for x in un if x['ev'] == 'E4'][:40]:
    print(f"  {r['sup']:<10} id={r['mid']:<34} 展示名={r['disp'][:26]:<26} canon={r['canon'][:26]}")
print('E4 合计', sum(1 for r in un if r['ev'] == 'E4'))
print()
print('=== 自定义档位（T）===')
for r in [x for x in un if x['tier']][:30]:
    print(f"  {r['sup']:<10} id={r['mid']:<28} 展示名={r['disp'][:30]}")
json.dump(rows, open('/tmp/vg/rows2.json', 'w'), ensure_ascii=False)
