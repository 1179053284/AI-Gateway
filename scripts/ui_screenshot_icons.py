#!/usr/bin/env python3
"""图标体系对齐（Lucide 0.555.0）截图取证：
网关导航七页新图标 + 模板图标 + 参考页导航对比。
用法：python3 scripts/ui_screenshot_icons.py（输出 docs/changes/e2e-records/icons-lucide-screenshots/）"""
import json, subprocess, time, os, base64, urllib.request
import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 19228
OUT = "/Users/w/Desktop/Model-Gateway/docs/changes/e2e-records/icons-lucide-screenshots"
os.makedirs(OUT, exist_ok=True)

proc = subprocess.Popen([
    CHROME, "--headless=new", "--disable-gpu", "--remote-debugging-port=%d" % PORT,
    "--remote-allow-origins=*",
    "--user-data-dir=/tmp/mg-icons-profile", "--no-first-run", "--window-size=1440,940",
    "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.5)

try:
    req = urllib.request.Request(
        "http://127.0.0.1:%d/json/new?about:blank" % PORT, method="PUT")
    info = json.load(urllib.request.urlopen(req))
    ws = websocket.create_connection(info["webSocketDebuggerUrl"], timeout=40)
    mid = [0]

    def cmd(method, **params):
        mid[0] += 1
        ws.send(json.dumps({"id": mid[0], "method": method, "params": params}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid[0]:
                return msg.get("result", {})

    def wait(sel, tries=30):
        for _ in range(tries):
            time.sleep(0.35)
            r = cmd("Runtime.evaluate", expression=f"!!document.querySelector('{sel}')")
            if r.get("result", {}).get("value"):
                time.sleep(0.9)
                return True
        return False

    def shot(url, name, sel):
        cmd("Emulation.setDeviceMetricsOverride", **{
            "width": 1440, "height": 940, "deviceScaleFactor": 2, "mobile": False})
        cmd("Page.navigate", url=url)
        wait(sel)
        cap = cmd("Page.captureScreenshot", format="png")
        data = cap["data"]
        if isinstance(data, str):
            data = base64.b64decode(data)
        open(f"{OUT}/{name}.png", "wb").write(data)
        print("saved", name)

    # 网关页（新 Lucide 导航图标 + 指标卡图标）
    shot("http://127.0.0.1:8300/#/dashboard", "mg-dashboard-nav", ".metric-card")
    shot("http://127.0.0.1:8300/#/stats", "mg-stats-nav", ".metric-card")
    # 模板（内容图标密集：server/cpu/trash/eye/log-in/check/download/search）
    shot("http://127.0.0.1:8300/templates/template-providers.html",
         "tpl-providers-icons", ".subnav")
    shot("http://127.0.0.1:8300/templates/template-skills.html",
         "tpl-skills-icons", ".list-row")
    # 参考页导航（对比基准，只读）
    cmd("Page.navigate", url="http://localhost:5173/console/model-providers")
    for _ in range(60):
        time.sleep(0.5)
        r = cmd("Runtime.evaluate",
                expression="document.querySelector('aside button span')?.textContent?.trim() || ''")
        if r.get("result", {}).get("value"):
            time.sleep(1.2)
            break
    cap = cmd("Page.captureScreenshot", format="png")
    data = cap["data"]
    if isinstance(data, str):
        data = base64.b64decode(data)
    open(f"{OUT}/ref-providers-nav.png", "wb").write(data)
    print("saved ref-providers-nav")

    # CDP 实测：网关导航图标描边 = 2.1（参考 :464 同值）
    cmd("Page.navigate", url="http://127.0.0.1:8300/#/dashboard")
    wait(".nav-ico")
    r = cmd("Runtime.evaluate", expression="""JSON.stringify(
      [...document.querySelectorAll('.nav-ico svg')].map(s => ({
        sw: s.getAttribute('stroke-width'),
        paths: s.querySelectorAll('path,rect,circle,line,ellipse').length })))""")
    print("nav-ico attrs:", r.get("result", {}).get("value"))
    ws.close()
finally:
    proc.terminate()
    proc.wait()
print("DONE")
