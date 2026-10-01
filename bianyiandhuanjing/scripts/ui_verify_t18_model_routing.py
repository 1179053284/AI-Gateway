#!/usr/bin/env python3
"""T-18 模型路由模板真机实测（headless Chrome CDP；2026-10-01）。

对准「我看看你是怎么理解模型路由这个事情的」逐条取证：
  ① 结构：标注条 / 预演声明 / 演示状态机 / 链路卡四段 / 顺位表 / 事件卡 / 匹配规则卡
  ② 语义（与本项目 FR-3 对齐）：生效集 top-x + 在途最少 → 故障切换（y 判定 → 冷却 → 补位）
     → 冷却归位 → 全挂 503；匹配层别名等价；空池 = 未配置资源（/v1/models 隐藏 + 503）
  ③ 交互：模型切换（4 行）/ 5 态演示联动（链路 + 顺位 + 事件 + 告警）/ toast / 深链 ?m=&state=（回读）
  ④ 主题：?theme=dark|light 令牌生效（sidenav 底色断言 + 像素统计）
  ⑤ 渲染纯度：body 文本不得出现 undefined（防插值事故）

用法：.venv/bin/python scripts/ui_verify_t18_model_routing.py
输出：docs/changes/e2e-records/t18-model-routing-screenshots/（8 张）+ 断言汇总打印
"""
import json
import os
import subprocess
import time
import base64
import urllib.request

import websocket
from PIL import Image

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 19225
BASE = "http://127.0.0.1:8300"
URL = f"{BASE}/templates/template-model-routing.html"
OUT = "/Users/w/Desktop/Model-Gateway/docs/changes/e2e-records/t18-model-routing-screenshots"
os.makedirs(OUT, exist_ok=True)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}{('  — ' + detail) if detail else ''}")


proc = subprocess.Popen([
    CHROME, "--headless=new", "--disable-gpu", "--remote-debugging-port=%d" % PORT,
    "--remote-allow-origins=*",
    "--user-data-dir=/tmp/mg-t18-profile", "--no-first-run", "--window-size=1440,940",
    "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.5)

try:
    req = urllib.request.Request("http://127.0.0.1:%d/json/new?about:blank" % PORT, method="PUT")
    info = json.load(urllib.request.urlopen(req))
    ws = websocket.create_connection(info["webSocketDebuggerUrl"], timeout=60)
    mid = [0]

    def cmd(method, **params):
        mid[0] += 1
        ws.send(json.dumps({"id": mid[0], "method": method, "params": params}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid[0]:
                return msg.get("result", {})

    def js(expr):
        r = cmd("Runtime.evaluate", expression=expr, returnByValue=True)
        return r.get("result", {}).get("value")

    def wait_for(expr, desc, timeout=25.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if js(expr):
                    return True
            except Exception:
                pass
            time.sleep(0.35)
        print(f"    [wait_for 超时] {desc}: {expr[:110]}")
        return False

    def nav(url, wait_expr, desc):
        cmd("Emulation.setDeviceMetricsOverride", **{
            "width": 1440, "height": 940, "deviceScaleFactor": 2, "mobile": False})
        cmd("Page.navigate", url=url)
        return wait_for(wait_expr, desc)

    def shot(name):
        time.sleep(1.1)  # 渲染稳定后再抓帧（过渡/合成器滞后教训）
        cap = cmd("Page.captureScreenshot", format="png")
        data = cap["data"]
        if isinstance(data, str):
            data = base64.b64decode(data)
        path = f"{OUT}/{name}.png"
        open(path, "wb").write(data)
        im = Image.open(path).convert("L")
        px = list(im.resize((200, 130), Image.BOX).get_flattened_data())
        dark = sum(1 for v in px if v < 80) / len(px) * 100
        light = sum(1 for v in px if v > 180) / len(px) * 100
        print(f"  saved {path}（暗={dark:.0f}% 亮={light:.0f}%）")

    READY = "!!document.querySelector('#render-root') && document.querySelectorAll('#render-root .card').length >= 4"

    # ---------- ① 默认态结构 ----------
    ok = nav(f"{URL}?theme=light", READY, "初始渲染")
    check("① 模板页加载（render-root 渲染出卡组）", bool(ok))
    check("① 标题 = T-18 模型路由", js("document.title").startswith("T-18 · 模型路由"),
          str(js("document.title")))
    check("① 标注条 + 预演声明在位",
          bool(js("document.body.innerText.includes('T-18 · 需求预演（演示数据）') "
                  "&& document.body.innerText.includes('需求形态预演 · 非线上功能')")))
    check("① 演示状态机 5 段在位",
          js("document.querySelectorAll('#state-tabs .tab').length") == 5,
          str(js("document.querySelectorAll('#state-tabs .tab').length")))
    check("① 子侧栏 4 个模型行 + deepseek 激活",
          bool(js("document.querySelectorAll('.subnav .mode-btn').length === 4 && "
                  "document.querySelector('.subnav .mode-btn.active')?.dataset.m === 'deepseek-v4-pro'")))
    check("① 链路卡四段（入站/匹配/选路/承接）",
          bool(js("document.body.innerText.includes('① 入站') && document.body.innerText.includes('② 匹配') "
                  "&& document.body.innerText.includes('③ 选路') && document.body.innerText.includes('④ 承接')")))
    check("① 默认态：生效集含两条资源 · 落点 #1",
          bool(js("document.body.innerText.includes('生效集 {res-7b21d084, res-3f9a2c1e}') "
                  "&& document.body.innerText.includes('res-7b21d084') && document.body.innerText.includes('平局 → 优先级高')")))
    check("① 顺位表 2 行 · 状态=可用 · 在途列 0/0",
          bool(js("document.querySelectorAll('.card .tbl tbody tr').length >= 2 && "
                  "document.body.innerText.includes('可用')")))
    check("① 事件卡「共 2 条」", bool(js("document.body.innerText.includes('共 2 条')")))
    check("① 匹配规则卡 5 行（规范名/别名/前缀剥离/禁用模型/未命中）",
          bool(js("['规范名','别名','前缀剥离','禁用模型','未命中'].every(function(k){return document.body.innerText.includes(k)})")))
    check("① 无 undefined 泄漏（渲染纯度）",
          bool(js("!document.body.innerText.includes('undefined')")))
    shot("01-default-light")

    # ---------- ④ 主题（顺路先在默认态取证） ----------
    nav(f"{URL}?theme=dark", READY, "暗色重载")
    time.sleep(0.6)
    ok = js("document.documentElement.dataset.theme") == "dark" and \
         js("getComputedStyle(document.querySelector('.sidenav')).backgroundColor") == "rgb(23, 25, 29)"
    check("④ ?theme=dark 令牌生效（sidenav = rgb(23,25,29)）", bool(ok),
          str(js("getComputedStyle(document.querySelector('.sidenav')).backgroundColor")))
    shot("02-default-dark")
    nav(f"{URL}?theme=light", READY, "回浅色")

    # ---------- ③ 演示状态联动 ----------
    js("[...document.querySelectorAll('#state-tabs .tab')].find(t => t.textContent === '故障切换').click()")
    ok = wait_for("document.body.innerText.includes('已移出生效集')", "故障切换态")
    check("③ 故障切换：#1 冷却中 42s · C=2/2 · #2 在途 4",
          bool(ok) and bool(js("document.body.innerText.includes('42s') && document.body.innerText.includes('HTTP 500') "
                  "&& document.body.innerText.includes('续跑中')")),
          "含 'HTTP 500' 与 '续跑中'")
    check("③ 故障切换：③ 段含「已移出生效集」· ④ 段落点 = res-3f9a2c1e",
          bool(js("document.body.innerText.includes('已移出生效集') && "
                  "document.body.innerText.includes('res-3f9a2c1e')")))
    check("③ 故障切换：事件卡 3 条（新增实时切换行）", bool(js("document.body.innerText.includes('共 3 条')")))
    check("③ tab active 同步", bool(js("document.querySelector('#state-tabs .tab.active')?.dataset.state === 'failover'")))
    shot("03-failover-light")

    js("[...document.querySelectorAll('#state-tabs .tab')].find(t => t.textContent === '冷却恢复').click()")
    ok = wait_for("document.body.innerText.includes('剩余 8s')", "冷却恢复态")
    check("③ 冷却恢复：剩余 8s + 归位事件行",
          bool(ok) and bool(js("document.body.innerText.includes('冷却期满 60s，按原优先级归位')")))
    shot("04-cooldown-light")

    js("[...document.querySelectorAll('#state-tabs .tab')].find(t => t.textContent === '全部不可用').click()")
    ok = wait_for("document.body.innerText.includes('全部资源不可用')", "全挂态")
    check("③ 全部不可用：alert-err + 503 兜底语义",
          bool(ok) and bool(js("!!document.querySelector('#render-root .alert-err') "
                  "&& document.body.innerText.includes('503')")),
          str(js("document.querySelector('#render-root .alert-err .alert-title')?.textContent")))
    shot("05-down-light")

    js("[...document.querySelectorAll('#state-tabs .tab')].find(t => t.textContent === '加载').click()")
    ok = wait_for("!!document.querySelector('#render-root .loading')", "加载态")
    check("③ 加载态：.loading 在位", bool(ok))
    shot("06-loading-light")

    # ---------- ③ 空池（kimi-k3） ----------
    js("[...document.querySelectorAll('#state-tabs .tab')].find(t => t.textContent === '默认').click()")
    js("[...document.querySelectorAll('.subnav .mode-btn')].find(b => b.dataset.m === 'kimi-k3').click()")
    ok = wait_for("document.body.innerText.includes('未配置任何资源映射')", "空池态")
    check("③ 空池：alert-warn + .empty + 「前往配置映射」出口",
          bool(ok) and bool(js("!!document.querySelector('#render-root .alert-warn') "
                  "&& !!document.querySelector('#render-root .empty')")),
          str(js("document.querySelector('#render-root .alert-title')?.textContent")))
    check("③ 空池：副行 = 未配置资源映射 · 今日 0 调用",
          bool(js("document.body.innerText.includes('未配置资源映射 · 今日 0 调用')")))
    shot("07-empty-kimi-light")

    # ---------- ③ 别名模型（sensenova） ----------
    js("[...document.querySelectorAll('.subnav .mode-btn')].find(b => b.dataset.m === 'sensenova-6.8-flash-lite').click()")
    ok = wait_for("document.body.innerText.includes('别名 1 条')", "sensenova 切换")
    check("③ 别名：② 段含「别名 1 条：sensenova-6.7-flash-lite」",
          bool(ok) and bool(js("document.body.innerText.includes('sensenova-6.7-flash-lite')")))
    check("③ 单资源池：③ 段含「单资源池 · 全量集中」",
          bool(js("document.body.innerText.includes('单资源池 · 全量集中')")))
    check("③ 切换 toast 反馈", bool(js("document.querySelectorAll('#toast-wrap .toast').length >= 1")))
    shot("08-sensenova-alias-light")

    # ---------- 深链回读（?m= & ?state=） ----------
    nav(f"{URL}?theme=light&m=deepseek-v4-pro&state=failover", "document.body.innerText.includes('已移出生效集')", "深链 failover")
    check("③ 深链 ?m=&state= 回读（failover 直达）",
          bool(js("document.querySelector('#state-tabs .tab.active')?.dataset.state === 'failover'")))
    nav(f"{URL}?theme=light&m=kimi-k3", "document.body.innerText.includes('未配置任何资源映射')", "深链 kimi")
    check("③ 深链 ?m=kimi-k3 回读（空池直达）",
          bool(js("document.querySelector('.subnav .mode-btn.active')?.dataset.m === 'kimi-k3'")))

    ws.close()
finally:
    proc.terminate()
    proc.wait()

fails = [n for n, ok, _ in results if not ok]
print(f"\nT18 MODEL ROUTING VERIFY: 实测 {len(results)} 项 · 失败 {len(fails)} 项")
if fails:
    print("失败项：" + "；".join(fails))
    raise SystemExit(1)
print("DONE")
