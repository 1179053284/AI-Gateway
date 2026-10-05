import json, urllib.request
def g(p):
    with urllib.request.urlopen('http://127.0.0.1:8300'+p, timeout=240) as r:
        return json.load(r)
out = {'cfg': g('/admin/api/config'), 'products': []}
for p in g('/admin/api/accounts')['products']:
    cat = g(f"/admin/api/accounts/{p['id']}/catalog")
    out['products'].append({'id': p['id'], 'title': p['title'],
                            'accounts': len(p.get('accounts') or []),
                            'models': cat.get('models') or [],
                            'source': cat.get('source')})
json.dump(out, open('/tmp/vg/raw.json', 'w'), ensure_ascii=False)
print('suppliers =', len(out['products']), 'entries =', sum(len(x['models']) for x in out['products']))
