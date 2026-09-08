#!/usr/bin/env python3
"""模板/规范交付截图取证（20260905）：
1) 参考页只读抓取（localhost:5173 providers/skills，浅色）
2) 网关模板双主题（template-providers / template-skills，?theme=dark）
3) 间距修正后网关四页（apiaccess/models/resources/settings，浅色）
用法：python3 scripts/ui_screenshot_templates.py （输出 docs/changes/e2e-records/templates-spec-screenshots/）"""
import json, subprocess, time, os, base64, urllib.request
import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 19223
OUT = "/Users/w/Desktop/Model-Gateway/docs/changes/e2e-records/templates-spec-screenshots"
os.makedirs(OUT, exist_ok=True)

proc = subprocess.Popen([
    CHROME, "--headless=new", "--disable-gpu", "--remote-debugging-port=%d" % PORT,
    "--remote-allow-origins=*",
    "--user-data-dir=/tmp/mg-tpl-profile", "--no-first-run", "--window-size=1440,940",
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

    def shot(url, name, wait_selector=None, dark=False, w=1440, h=940):
        cmd("Emulation.setDeviceMetricsOverride", **{
            "width": w, "height": h, "deviceScaleFactor": 2, "mobile": False})
        if dark:  # 同源先落 localStorage 再整页导航（hash 路由页）
            cmd("Page.navigate", url="http://127.0.0.1:8300/#/dashboard")
            time.sleep(0.8)
            cmd("Runtime.evaluate", expression="localStorage.setItem('mg-theme','dark')")
            cmd("Page.navigate", url="about:blank")
            time.sleep(0.3)
        cmd("Page.navigate", url=url)
        # 等待关键元素渲染
        sel = wait_selector or ".theme-wrap, .tb-title, #root"
        for _ in range(40):
            time.sleep(0.35)
            r = cmd("Runtime.evaluate",
                    expression=f"!!document.querySelector('{sel}')")
            if r.get("result", {}).get("value"):
                time.sleep(1.0)  # 等数据/动画稳定
                break
        cap = cmd("Page.captureScreenshot", format="png")
        data = cap["data"]
        if isinstance(data, str):
            data = base64.b64decode(data)
        path = f"{OUT}/{name}.png"
        open(path, "wb").write(data)
        print("saved", path)
        if dark:  # 还原浅色，避免影响后续
            cmd("Page.navigate", url="http://127.0.0.1:8300/#/dashboard")
            time.sleep(0.8)
            cmd("Runtime.evaluate", expression="localStorage.setItem('mg-theme','light')")

    # 1) 参考页（只读访问；Vite 首访需编译，等真实导航文本出现而非空 #root）
    def shot_ref(url, name):
        cmd("Emulation.setDeviceMetricsOverride", **{
            "width": 1440, "height": 940, "deviceScaleFactor": 2, "mobile": False})
        cmd("Page.navigate", url=url)
        # 等参考页侧栏导航真实渲染（span 文本非空）
        for _ in range(80):
            time.sleep(0.5)
            r = cmd("Runtime.evaluate",
                    expression="document.querySelector('aside button span')?.textContent?.trim() || ''")
            if r.get("result", {}).get("value"):
                time.sleep(1.5)  # 等面板数据/图标稳定
                break
        cap = cmd("Page.captureScreenshot", format="png")
        data = cap["data"]
        if isinstance(data, str):
            data = base64.b64decode(data)
        path = f"{OUT}/{name}.png"
        open(path, "wb").write(data)
        print("saved", path)

    shot_ref("http://localhost:5173/console/model-providers", "ref-providers-light")
    shot_ref("http://localhost:5173/console/skills", "ref-skills-light")
    # 2) 网关模板（双主题）
    shot("http://127.0.0.1:8300/templates/template-providers.html", "tpl-providers-light")
    shot("http://127.0.0.1:8300/templates/template-providers.html?theme=dark", "tpl-providers-dark")
    shot("http://127.0.0.1:8300/templates/template-skills.html", "tpl-skills-light")
    shot("http://127.0.0.1:8300/templates/template-skills.html?theme=dark", "tpl-skills-dark")
    # 3) 修正后网关四页（浅色）
    for p in ["apiaccess", "models", "resources", "settings"]:
        shot(f"http://127.0.0.1:8300/#/{p}", f"mg-{p}-light", wait_selector=".tb-title")
    # 附加：resources 暗色（模板组件在实页中的暗色适配）
    shot("http://127.0.0.1:8300/#/resources", "mg-resources-dark",
         wait_selector=".tb-title", dark=True)
    ws.close()
finally:
    proc.terminate()
    proc.wait()
print("DONE")
