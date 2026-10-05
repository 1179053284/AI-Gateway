#!/usr/bin/env python3
"""只读盘点：全产品模型目录 × 映射状态 × 网关侧供给（:8300 或指定实例）。

用途 = 回答两件事：① 哪些模型还没有配置映射关系；② 哪些厂商/模型没配进网关。
🔴 全程只读：只发 `GET /admin/api/config`、`GET /admin/api/accounts`、
`GET /admin/api/accounts/<product>/catalog`——不写配置、不拨开关、不出站调用模型
（目录取数由网关自己的缓存/实时腿负责，本脚本不触发额度消耗类动作）。

用法：
    python3 bianyiandhuanjing/scripts/probe_mapping_census.py [base_url]
默认 base_url = http://127.0.0.1:8300
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8300').rstrip('/')
ROOT = __import__('pathlib').Path(__file__).resolve().parents[1] / 'coding'
sys.path.insert(0, str(ROOT))


def get(path: str, timeout: int = 180):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.load(r)


def main() -> int:
    from model_gateway.enums.matcher import BUILTIN_ENTRIES, normalize_name

    cfg = get('/admin/api/config')
    acc = get('/admin/api/accounts')
    res_by_id = {r['id']: r for r in cfg['resources']}
    sys_models = {m['name']: m for m in cfg['models']}
    bits = cfg.get('product_models') or []          # Q33 账号侧映射的真相层
    entry_bits = {(b['product'], b['model']) for b in bits}

    def live_rows(m) -> list:
        """这个网关模型现在到底有几条生效供给（Key 接入侧看条目位，账号侧看派生位）。"""
        out = []
        for e in (m.get('resources') or []):
            r = res_by_id.get(e['resource']) or {}
            if r.get('product'):
                if e.get('mapping_enabled'):
                    out.append(e)
            elif e.get('enabled'):
                out.append(e)
        return out

    sys_norm = {normalize_name(n) for n in sys_models}
    bkey: set[str] = set()
    for e in BUILTIN_ENTRIES:
        for k in (e.name, *(e.aliases or [])):
            bkey.add(normalize_name(str(k)))

    def resolvable(*cands: str) -> bool:
        """网关里或内置目录里有没有这个模型（斜杠前缀形态单独剥一次）。"""
        for s in cands:
            n = normalize_name(str(s))
            if n in sys_norm or n in bkey:
                return True
            if '/' in str(s):
                tail = normalize_name(str(s).split('/', 1)[1])
                if tail in sys_norm or tail in bkey:
                    return True
        return False

    print(f'=== 读数对象：{BASE}（只读）===')
    accounts_total = sum(len(p.get('accounts') or []) for p in acc['products'])
    print(f'产品 {len(acc["products"])} 个 · 账号 {accounts_total} 个 · '
          f'账号侧派生资源 {len([r for r in cfg["resources"] if r.get("product")])} 条 · '
          f'按 Key 接入的供应商资源 {len([r for r in cfg["resources"] if not r.get("product")])} 条 · '
          f'网关模型 {len(sys_models)} 个 · 产品位 {len(bits)} 条')
    print()

    hdr = ('产品', '账号', '启用', '目录', '已映射进池', '已映射已关', '未映射',
           '可直接挂', '需建模型', '无建议', '产品位')
    print('{:<18}{:>5}{:>5}{:>6}{:>10}{:>9}{:>8}{:>8}{:>8}{:>7}{:>6}'.format(*hdr))
    tot = Counter()
    detail: dict[str, dict] = {}
    for p in acc['products']:
        pid, title = p['id'], p['title']
        accounts = p.get('accounts') or []
        ms = (get(f'/admin/api/accounts/{pid}/catalog').get('models') or [])
        on = [m for m in ms if (m.get('mapped_to') or []) and m.get('map_enabled') is True]
        off = [m for m in ms if (m.get('mapped_to') or []) and m.get('map_enabled') is not True]
        unm = [m for m in ms if not (m.get('mapped_to') or [])]
        hit = [(m['id'], m['suggest']['name']) for m in unm
               if (m.get('suggest') or {}).get('name') in sys_models]
        new = [(m['id'], m['suggest']['name']) for m in unm
               if (m.get('suggest') or {}).get('name')
               and m['suggest']['name'] not in sys_models]
        nos = [m for m in unm if not (m.get('suggest') or {}).get('name')]
        rec = [(m['id'], m.get('name'), ) for m in nos if resolvable(m.get('name'), m['id'])]
        legacy = [m['id'] for m in (on + off) if (pid, m['id']) not in entry_bits]
        for k, v in (('catalog', len(ms)), ('on', len(on)), ('off', len(off)),
                     ('hit', len(hit)), ('new', len(new)), ('nos', len(nos)),
                     ('rec', len(rec))):
            tot[k] += v
        print('{:<18}{:>5}{:>5}{:>6}{:>10}{:>9}{:>8}{:>8}{:>8}{:>7}{:>6}'.format(
            title[:17], len(accounts), sum(1 for a in accounts if a.get('enabled')),
            len(ms), len(on), len(off), len(hit) + len(new) + len(nos),
            len(hit), len(new), len(nos),
            sum(1 for b in bits if b['product'] == pid)))
        detail[pid] = dict(title=title, on=[m['id'] for m in on], hit=hit, new=new,
                           nos=[m['id'] for m in nos], rec=rec, legacy=legacy)

    print()
    print(f'合计：目录 {tot["catalog"]} 条 / 已映射 {tot["on"] + tot["off"]} 条'
          f'（进池 {tot["on"]}、关着 {tot["off"]}）/ 未映射 {tot["catalog"] - tot["on"] - tot["off"]} 条')
    print(f'     未映射里：可直接挂 {tot["hit"]} 条 · 建议名要先建模型 {tot["new"]} 条 · '
          f'服务端没给建议 {tot["nos"]} 条（其中按展示名可回收 {tot["rec"]} 条）')
    print(f'     交叉核对：无建议 {tot["nos"]} − 可回收 {tot["rec"]} = {tot["nos"] - tot["rec"]} 条'
          f'（= 网关与内置目录都没有对应模型的条目数，见下表）')
    print()

    print('=== 逐产品明细（未映射三档）===')
    for pid, d in detail.items():
        print(f'---- {d["title"]} (`{pid}`)')
        if d['on']:
            print(f'   ✅ 已映射·进池 {len(d["on"])} 条: ' + ', '.join(d['on'][:12]))
            if d['legacy']:
                print(f'   ⚠️ 其中 {len(d["legacy"])} 条**没有产品位**（旧形状，靠 mapping_enabled 回落条目位）'
                      f' ⇒ 该产品新加的账号不会继承这些映射')
        if d['hit']:
            print('   🔧 可直接挂: ' + ', '.join(f'{a}→{b}' for a, b in d['hit']))
        if d['new']:
            print('   🆕 要先建网关模型: ' + ', '.join(f'{a}→{b}' for a, b in d['new']))
        if d['rec']:
            print('   👀 没建议但展示名能对上: ' + ', '.join(a for a, _ in d['rec']))
        if d['nos']:
            print(f'   ❔ 无建议需人工判断 {len(d["nos"])} 条: ' + ', '.join(d['nos'][:12])
                  + ('…' if len(d['nos']) > 12 else ''))
    print()

    rows = []
    for p in acc['products']:
        for m in (get(f"/admin/api/accounts/{p['id']}/catalog").get('models') or []):
            rows.append((p['title'], m['id'], str(m.get('name') or ''),
                         m.get('context_window'), m.get('max_output'), m.get('tool_call')))
    un = [(t, i, n) for (t, i, n, *_rest) in rows if not resolvable(i, n)]
    print('=== 网关里完全没有对应模型的条目，按名称首段机械归类（不是官方厂商归属断言）===')
    by_fam = defaultdict(lambda: {'rows': 0, 'prods': set(), 'sample': []})
    for t, i, n in un:
        s = str(i).lower().split('/', 1)[-1].strip()
        m = re.match(r'^([a-z]+)', s) or re.match(r'^([a-z]+)', n.lower())
        f = m.group(1) if m and len(m.group(1)) >= 4 else '其他/代号'
        d = by_fam[f]
        d['rows'] += 1
        d['prods'].add(t)
        if len(d['sample']) < 2:
            d['sample'].append(i)
    for f, d in sorted(by_fam.items(), key=lambda kv: -kv[1]['rows'])[:20]:
        print(f'  · {f:<12} 条目 {d["rows"]:>3}  产品 {len(d["prods"]):>2}  ' + ', '.join(d['sample']))
    print()

    print('=== 厂商维度（归属只取内置目录的 vendor 字段）===')
    by_v = defaultdict(list)
    for e in BUILTIN_ENTRIES:
        by_v[e.vendor].append(e.name)
    print('{:<18}{:>6}{:>6}{:>8}  {}'.format('厂商', '目录', '已建', '有供给', '缺的模型名'))
    for v, names in sorted(by_v.items(), key=lambda kv: -len(kv[1])):
        wired = [n for n in names if n in sys_models]
        sup = [n for n in wired if live_rows(sys_models[n])]
        miss = [n for n in names if n not in sys_models]
        print('{:<18}{:>6}{:>6}{:>8}  {}'.format(
            v[:17], len(names), len(wired), len(sup), ', '.join(miss) or '—'))
    empty = [n for n, m in sys_models.items() if not live_rows(m)]
    print('  空池（已建但一条生效供给都没有）: ' + (', '.join(empty) or '（无）'))
    print()

    print('=== 目录规格完整度（决定映射后能对外声明多少事实）===')
    for p in acc['products']:
        pid, title = p['id'], p['title']
        ms = (get(f'/admin/api/accounts/{pid}/catalog').get('models') or [])
        print(f'  {title:<18} 目录 {len(ms):>3} · 无上下文 {sum(1 for m in ms if not m.get("context_window")):>3}'
              f' · 无最大输出 {sum(1 for m in ms if not m.get("max_output")):>3}'
              f' · 工具位未知 {sum(1 for m in ms if m.get("tool_call") is None):>3}'
              f' · 有倍率 {sum(1 for m in ms if (m.get("rate") or "")):>3}')
    print('  🔴 `tool_call` 全线未知不是丢字段：这些产品的目录不声明工具能力'
          '（`upstream/zcode/product.py:81` 口径「取不到不编造」）'
          '⇒ 这一位只能由内置目录或网关模型 `caps_overrides` 提供。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
