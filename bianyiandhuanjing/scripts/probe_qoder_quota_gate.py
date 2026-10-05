import sys, httpx, json
sys.path.insert(0, '.')
from model_gateway.accounts import store
from model_gateway.upstream.qoder import config as qcfg, flow
prod = qcfg.QODER
cred = store.load_credentials('qoder', 'qoder-eff2c221')
H = {'User-Agent': 'qoder/1.0.0', 'Content-Type': 'application/json',
     'Authorization': f'Bearer {flow.token_of(cred)}'}
url = prod.infer_base + "/model/v1/chat/completions"
names = ['qwen3.8-max', 'xyzzy-definitely-not-a-model-9', 'glm-4.7', 'asjdlk', '']
shapes = {
  'nonstream': lambda m: {"model": m, "messages": [{"role": "user", "content": "hi"}], "stream": False, "max_tokens": 1},
  'stream':    lambda m: {"model": m, "messages": [{"role": "user", "content": "hi"}], "stream": True, "max_tokens": 1},
  'nomsg':     lambda m: {"model": m, "stream": False},
  'badtok':    lambda m: {"model": m, "messages": [{"role": "user", "content": "hi"}], "stream": False, "max_tokens": 99999999},
}
for n in names:
    for tag, mk in shapes.items():
        try:
            r = httpx.post(url, headers=H, json=mk(n), timeout=25)
            print(f'{n[:26]:<28}{tag:<10}{r.status_code:>4}  {r.text[:120]}'.replace('\n', ' '))
        except Exception as e:
            print(f'{n[:26]:<28}{tag:<10}ERR {type(e).__name__} {str(e)[:70]}')
    print()
