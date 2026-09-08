#!/usr/bin/env python3
"""Q22 截图取证：headless Chrome CDP 抓取网关七页 · 浅色/深色双主题。
用法：python3 scripts/ui_screenshot.py  （输出 /tmp/mg-q22/*.png）"""
import json, subprocess, time, os
import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 19222
OUT = "/tmp/mg-q22"
os.makedirs(OUT, exist_ok=True)

PAGES = ["dashboard", "resources", "models", "stats", "logs", "apiaccess", "settings"]

proc = subprocess.Popen([
    CHROME, "--headless=new", "--disable-gpu", "--remote-debugging-port=%d" % PORT,
    "--remote-allow-origins=*",
    "--user-data-dir=/tmp/mg-q22-profile", "--no-first-run", "--window-size=1440,940",
    "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.5)

try:
    import urllib.request
    req = urllib.request.Request(
        "http://127.0.0.1:%d/json/new?about:blank" % PORT, method="PUT")
    info = json.load(urllib.request.urlopen(req))
    ws = websocket.create_connection(info["webSocketDebuggerUrl"], timeout=30)
    mid = [0]

    def cmd(method, **params):
        mid[0] += 1
        ws.send(json.dumps({"id": mid[0], "method": method, "params": params}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid[0]:
                return msg.get("result", {})

    def shot(page, theme, wide=True):
        size = {"width": 1440, "height": 940} if wide else {"width": 900, "height": 940}
        cmd("Emulation.setDeviceMetricsOverride", **{
            "width": size["width"], "height": size["height"],
            "deviceScaleFactor": 2, "mobile": False})
        # 同源页设 localStorage 主题 → about:blank 中转 → 目标路由强制整页重载读取主题
        cmd("Page.navigate", url="http://127.0.0.1:8300/#/dashboard")
        time.sleep(0.8)
        cmd("Runtime.evaluate", expression=f"localStorage.setItem('mg-theme','{theme}')")
        cmd("Page.navigate", url="about:blank")
        time.sleep(0.3)
        cmd("Page.navigate", url=f"http://127.0.0.1:8300/#/{page}")
        # 等路由渲染（顶栏标题出现）+ 数据请求
        for _ in range(40):
            time.sleep(0.35)
            r = cmd("Runtime.evaluate", expression="document.querySelector('.tb-title')?.textContent || ''")
            title = r.get("result", {}).get("value", "")
            if title:
                time.sleep(0.7)
                break
        cap = cmd("Page.captureScreenshot", format="png")
        data = cap["data"]
        if isinstance(data, str):
            import base64
            data = base64.b64decode(data)
        path = f"{OUT}/mg-q22-{page}-{theme}{'-wide' if wide else ''}.png"
        open(path, "wb").write(data)
        print("saved", path)

    for p in PAGES:
        shot(p, "light")
    for p in PAGES:
        shot(p, "dark")
    shot("dashboard", "light", wide=False)
    ws.close()
finally:
    proc.terminate()
    proc.wait()
print("DONE")
