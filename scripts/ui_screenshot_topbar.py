#!/usr/bin/env python3
"""顶栏精简 + 三图标主题组 + 总览页头移除 —— 实测取证：
1) 顶栏无 v版本/uptime/在途 文本
2) 三主题图标存在且 active 正确；点击切换 data-theme 生效
3) 总览内容首块 = card-grid（无 page-head 地址栏）
用法：python3 scripts/ui_screenshot_topbar.py"""
import json, subprocess, time, os, base64, urllib.request
import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 19232
OUT = "/Users/w/Desktop/Model-Gateway/docs/changes/e2e-records/topbar-theme-screenshots"
os.makedirs(OUT, exist_ok=True)

proc = subprocess.Popen([
    CHROME, "--headless=new", "--disable-gpu", "--remote-debugging-port=%d" % PORT,
    "--remote-allow-origins=*",
    "--user-data-dir=/tmp/mg-topbar-profile", "--no-first-run", "--window-size=1440,940",
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

    def ev(expr):
        return cmd("Runtime.evaluate", expression=expr).get("result", {}).get("value")

    def shot(name):
        cap = cmd("Page.captureScreenshot", format="png")
        data = cap["data"]
        if isinstance(data, str):
            data = base64.b64decode(data)
        open(f"{OUT}/{name}.png", "wb").write(data)
        print("saved", name)

    cmd("Emulation.setDeviceMetricsOverride", **{
        "width": 1440, "height": 940, "deviceScaleFactor": 2, "mobile": False})
    cmd("Page.navigate", url="http://127.0.0.1:8300/#/dashboard")
    time.sleep(3)

    # 1) 顶栏文本检查
    r = ev("""JSON.stringify({
      version: !!document.getElementById('tb-version'),
      uptime: !!document.getElementById('tb-uptime'),
      inflight: !!document.getElementById('tb-inflight'),
      rightText: document.querySelector('.tb-right').innerText.trim()})""")
    print("topbar:", r)

    # 2) 三主题图标 + active 态
    r = ev("""JSON.stringify([...document.querySelectorAll('#theme-group .icon-btn')].map(b => ({
      mode: b.dataset.themeMode,
      active: b.classList.contains('on'),
      iconPx: getComputedStyle(b.querySelector('svg')).width,
      btnPx: getComputedStyle(b).width + 'x' + getComputedStyle(b).height})))""")
    print("theme-group:", r)

    # 3) 总览内容首块
    r = ev("""JSON.stringify({
      firstChild: document.getElementById('content').firstElementChild.className,
      hasPageHead: !!document.querySelector('#content .page-head')})""")
    print("dashboard content:", r)

    shot("mg-topbar-light")

    # 4) 点击月亮 → 深色生效
    ev("document.querySelector('[data-theme-mode=dark]').click()")
    time.sleep(0.5)
    print("after dark click:", ev("JSON.stringify({theme: document.documentElement.dataset.theme, stored: localStorage.getItem('mg-theme')})"))
    shot("mg-topbar-dark")

    # 5) 点击太阳 → 浅色恢复；点击自动 → active 跟随
    ev("document.querySelector('[data-theme-mode=light]').click()")
    time.sleep(0.3)
    print("after light click:", ev("document.documentElement.dataset.theme"))
    ev("document.querySelector('[data-theme-mode=system]').click()")
    time.sleep(0.3)
    print("after system click:", ev("JSON.stringify({theme: document.documentElement.dataset.theme, activeMode: document.querySelector('#theme-group .on')?.dataset.themeMode})"))
    ws.close()
finally:
    proc.terminate()
    proc.wait()
print("DONE")
