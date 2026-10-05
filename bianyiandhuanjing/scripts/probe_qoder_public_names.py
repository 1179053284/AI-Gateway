"""取证：国际版公开端点到底接受哪些模型名（402/code116 = 名称被接受、卡在额度）。"""
import json, re, sys, time, httpx
sys.path.insert(0, '.')
from model_gateway.accounts import store
from model_gateway.upstream.qoder import config as qcfg
from model_gateway.upstream.qoder import flow

prod = qcfg.QODER
cred = store.load_credentials('qoder', 'qoder-eff2c221')
tok = flow.token_of(cred)
url = prod.infer_base + "/model/v1/chat/completions"
H = {'User-Agent': f'{prod.user_agent_prefix}/1.0.0', 'Content-Type': 'application/json',
     'Authorization': f'Bearer {tok}'}

cands = []
for m in prod.fallback_models:
    cands.append(m.id)                                  # 目录 key
    cands.append(m.name.lower().replace(' ', '-'))      # 展示名规范化
cands += ['qwen-plus', 'qwen-flash', 'qwen3-plus', 'qwen3.5-plus', 'qwen3-max',
          'glm-4.7', 'kimi-k2.5', 'deepseek-v3', 'minimax-m2.7']
seen, order = set(), []
for c in cands:
    if c and c not in seen:
        seen.add(c); order.append(c)

rows = []
for name in order:
    body = {"model": name, "messages": [{"role": "user", "content": "hi"}],
            "stream": False, "max_tokens": 1}
    try:
        r = httpx.post(url, headers=H, json=body, timeout=25)
        st, txt = r.status_code, r.text[:160]
    except Exception as e:
        st, txt = 0, f'{type(e).__name__}: {str(e)[:80]}'
    low = txt.lower()
    if 'unsupported' in low or 'not support' in low or 'invalid model' in low:
        verdict = 'REJECT'
    elif st == 402 or '"code":116' in txt or 'quota' in low:
        verdict = 'ACCEPT(quota-gate)'
    elif st in (401, 403):
        verdict = 'AUTH'
    elif st == 200:
        verdict = 'ACCEPT(200!)'
    else:
        verdict = f'OTHER/{st}'
    rows.append((name, st, verdict, txt.replace('\n', ' ')[:110]))
    time.sleep(0.25)

print(f'{"候选名":<26}{"HTTP":>5}  {"判定":<20} 响应')
for n, st, v, t in rows:
    print(f'{n:<26}{st:>5}  {v:<20} {t}')
acc = [n for n, _, v, _ in rows if v.startswith('ACCEPT')]
rej = [n for n, _, v, _ in rows if v == 'REJECT']
print('\n被接受（可服务，待额度）:', acc or '无')
print('被拒（名称不认）条数:', len(rej), '/', len(rows))
json.dump([{'name': n, 'http': s, 'verdict': v, 'body': t} for n, s, v, t in rows],
          open('/tmp/qoder_public_names.json', 'w'), ensure_ascii=False, indent=1)
