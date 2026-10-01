#!/usr/bin/env python3
"""模板页面真机实测（headless Chrome CDP；2026-10-01 用户指示恢复侧栏「模板页面」入口）。

对准用户诉求逐条取证（「左侧菜单增加一个菜单入口 / 所有模板在这个入口内显示」）：
  ① 侧栏「模板」分组 ·「模板页面」入口存在，**点击**可进入（crumb / 页标题 / active 同步）
  ② 子侧栏 = 总览 + 12 个模板行；总览卡片网格 = 12 张（「所有模板」的机械计数）
  ③ 卡片点击 → iframe **真的加载**（contentDocument.title 出自模板文件）+ 深链同步
  ④ 宽度切换 1440→1280→适应（iframe style.width 实测）；刷新 / 新标签打开按钮在位
  ⑤ 主题跟随：顶栏切深色 → iframe src 带 `?theme=dark` 重载且**帧内** dataset.theme=dark
  ⑥ 深链 #/templates?t=tpl-vendor-accounts 直达预览（需求预演提示条 `.alert-warn` 在位）

用法：.venv/bin/python scripts/ui_verify_templates_page.py
输出：docs/changes/e2e-records/templates-page-screenshots-20261001/（截图）+ 断言汇总打印
"""
import json
import os
import subprocess
import time
import base64
import urllib.request

import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 19224
BASE = "http://127.0.0.1:8300"
OUT = "/Users/w/Desktop/Model-Gateway/docs/changes/e2e-records/templates-page-screenshots-20261001"
os.makedirs(OUT, exist_ok=True)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}{('  — ' + detail) if detail else ''}")


proc = subprocess.Popen([
    CHROME, "--headless=new", "--disable-gpu", "--remote-debugging-port=%d" % PORT,
    "--remote-allow-origins=*",
    "--user-data-dir=/tmp/mg-tplpage-profile", "--no-first-run", "--window-size=1440,940",
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
        # 🔴 截图前必须等渲染稳定：主题切换有 .18s 过渡 + 合成器同步延迟，
        #    点击后立即抓帧会拿到"部分区域换色"的中间帧（实测 02 首版出现"底暗卡亮"混合帧）。
        time.sleep(1.1)
        cap = cmd("Page.captureScreenshot", format="png")
        data = cap["data"]
        if isinstance(data, str):
            data = base64.b64decode(data)
        path = f"{OUT}/{name}.png"
        open(path, "wb").write(data)
        print("  saved", path)

    # ---------- ① 侧栏入口存在 + 真实点击进入 ----------
    ok = nav(f"{BASE}/#/dashboard", "document.querySelector('.tb-title')?.textContent==='总览'",
             "dashboard 加载")
    check("前置：总览页可加载", bool(ok))
    check("① 侧栏有「模板」分组 +「模板页面」入口（data-page=templates）",
          bool(js("""(() => {
            const a = document.querySelector('.nav-item[data-page="templates"]');
            const g = [...document.querySelectorAll('.nav-group-title')].find(x => x.textContent === '模板');
            return !!a && a.textContent.includes('模板页面') && !!g;
          })()""")))
    js("document.querySelector('.nav-item[data-page=\"templates\"]').click()")
    ok = wait_for("document.querySelector('.tb-title')?.textContent === '模板页面' "
                  "&& document.querySelector('#crumb-group')?.textContent === '模板' "
                  "&& !!document.querySelector('.panel-split')", "点击进入模板页面")
    check("① 点击入口进入（crumb=模板 / 标题=模板页面 / 双面板骨架在位）", bool(ok))
    check("① 侧栏该项为 active（当前路由高亮）",
          bool(js("document.querySelector('.nav-item[data-page=\"templates\"]').classList.contains('active')")))

    # ---------- ② 所有模板：子侧栏 12 行 + 总览 12 卡片 ----------
    ok = wait_for("document.querySelectorAll('[data-open]').length === 12", "总览卡片渲染")
    check("② 总览卡片网格 = 12 张（data-open 计数）", bool(ok),
          f"count={js('document.querySelectorAll(\"[data-open]\").length')}")
    check("② 子侧栏 = 总览项 + 12 个模板行",
          bool(js("!!document.querySelector('#tpl-ov') && "
                  "document.querySelectorAll('[data-tpl-id]').length === 12")),
          f"rows={js('document.querySelectorAll(\"[data-tpl-id]\").length')}")
    check("② 三个分组标题在位（基准模板 · 对照 / P0 · 本期新增 / 需求预演）",
          bool(js("""(() => {
            const t = [...document.querySelectorAll('.subnav-scroll div')].map(x => x.textContent);
            return t.some(x => x === '基准模板 · 对照') && t.some(x => x === 'P0 · 本期新增')
                && t.some(x => x === '需求预演');
          })()""")))
    check("② 卡片元数据完整（示例 T-05 卡含骨架徽章 + 文件名）",
          bool(js("""(() => {
            const c = document.querySelector('[data-open="tpl-stepper-wizard"]');
            return !!c && c.textContent.includes('多步向导') && c.textContent.includes('D · 工具页')
                && c.textContent.includes('template-stepper-wizard.html');
          })()""")))
    shot("01-overview-light")

    # 暗色总览（主题跟随的文档级取证）
    js("document.querySelector('#theme-group [data-theme-mode=\"dark\"]').click()")
    ok = wait_for("document.documentElement.dataset.theme === 'dark'", "切深色")
    time.sleep(0.6)  # 过渡完成后取值（立即取值拿到的是过渡中间色，断言会失真）
    ok = ok and js("getComputedStyle(document.body).backgroundColor") == "rgb(16, 17, 20)"
    check("② 总览页暗色生效（body 背景 = 深色令牌 rgb(16,17,20)）", bool(ok),
          str(js("getComputedStyle(document.body).backgroundColor")))
    shot("02-overview-dark")
    js("document.querySelector('#theme-group [data-theme-mode=\"light\"]').click()")
    wait_for("document.documentElement.dataset.theme === 'light'", "切回浅色")

    # ---------- ③ 卡片点击 → iframe 真加载 ----------
    js("document.querySelector('[data-open=\"tpl-tabs-view\"]').click()")
    ok = wait_for("!!document.querySelector('#tpl-frame')", "进入预览")
    check("③ 卡片点击进入预览（#tpl-frame 在位）", bool(ok))
    check("③ iframe src = /templates/template-tabs-view.html?theme=light",
          js("document.getElementById('tpl-frame').getAttribute('src')")
          == "/templates/template-tabs-view.html?theme=light",
          str(js("document.getElementById('tpl-frame').getAttribute('src')")))
    check("③ 深链同步 #/templates?t=tpl-tabs-view",
          js("location.hash") == "#/templates?t=tpl-tabs-view", str(js("location.hash")))
    check("③ 子侧栏该行 active（选中态）",
          bool(js("document.querySelector('[data-tpl-id=\"tpl-tabs-view\"]').classList.contains('active')")))
    ok = wait_for("(document.getElementById('tpl-frame').contentDocument?.title || '').includes('T-02')",
                  "iframe 内容真实加载（帧内 title 含 T-02）")
    check("③ iframe 内文档真实加载（contentDocument.title 含 T-02）", bool(ok),
          str(js("document.getElementById('tpl-frame').contentDocument?.title || ''"))[:60])
    check("③ 预览头三按钮在位（刷新 / 复制路径 / 新标签打开）",
          bool(js("!!document.querySelector('#tpl-refresh') && !!document.querySelector('#tpl-copy') "
                  "&& !!document.querySelector('#tpl-open')")))
    shot("03-preview-tabsview-light")

    # ---------- ④ 宽度切换 ----------
    js("[...document.querySelectorAll('#tpl-widths .tab')].find(b => b.textContent === '1280').click()")
    check("④ 宽度 1280：iframe style.width=1280px",
          bool(js("document.getElementById('tpl-frame').style.width === '1280px'")),
          str(js("document.getElementById('tpl-frame').style.width")))
    js("[...document.querySelectorAll('#tpl-widths .tab')].find(b => b.textContent === '适应').click()")
    check("④ 宽度 适应：iframe style.width=100%",
          bool(js("document.getElementById('tpl-frame').style.width === '100%'")),
          str(js("document.getElementById('tpl-frame').style.width")))
    js("[...document.querySelectorAll('#tpl-widths .tab')].find(b => b.textContent === '1024').click()")
    check("④ 宽度 1024 可切回", bool(js("document.getElementById('tpl-frame').style.width === '1024px'")))
    shot("04-preview-width1024-light")
    js("[...document.querySelectorAll('#tpl-widths .tab')].find(b => b.textContent === '1440').click()")

    # 刷新按钮：src 保持不变（重载由浏览器执行；此处钉"不炸"）
    js("document.querySelector('#tpl-refresh').click()")
    time.sleep(0.5)
    check("④ 刷新按钮后 iframe 仍在且 src 不变",
          js("document.getElementById('tpl-frame')?.getAttribute('src')")
          == "/templates/template-tabs-view.html?theme=light")

    # ---------- ⑤ 主题跟随（控制台 → iframe 重载） ----------
    js("document.querySelector('#theme-group [data-theme-mode=\"dark\"]').click()")
    ok = wait_for("document.getElementById('tpl-frame').getAttribute('src')"
                  ".includes('theme=dark')", "iframe 随主题重载")
    ok2 = wait_for("(document.getElementById('tpl-frame').contentDocument?.documentElement.dataset.theme || '')"
                   " === 'dark'", "帧内主题=dark")
    check("⑤ 顶栏切深色 → iframe src 带 ?theme=dark 且帧内 dataset.theme=dark", bool(ok and ok2),
          str(js("document.getElementById('tpl-frame').getAttribute('src')")))
    shot("05-preview-tabsview-dark")
    js("document.querySelector('#theme-group [data-theme-mode=\"light\"]').click()")
    ok = wait_for("document.getElementById('tpl-frame').getAttribute('src')"
                  ".includes('theme=light')", "切回浅色重载")
    check("⑤ 切回浅色 → iframe 同步 ?theme=light", bool(ok))
    ok2 = wait_for("(document.getElementById('tpl-frame').contentDocument?.documentElement.dataset.theme || '')"
                   " === 'light'", "帧内主题=light")
    check("⑤ 帧内 dataset.theme=light（往返闭合）", bool(ok2))

    # ---------- ⑥ 深链直达（需求预演 + 提示条） ----------
    cmd("Page.navigate", url=f"{BASE}/#/templates?t=tpl-vendor-accounts")
    ok = wait_for("!!document.querySelector('#tpl-frame') && "
                  "document.getElementById('tpl-frame').getAttribute('src')"
                  ".includes('template-vendor-accounts.html')", "深链直达 T-17")
    check("⑥ 深链 #/templates?t=tpl-vendor-accounts 直达预览", bool(ok),
          str(js("document.getElementById('tpl-frame')?.getAttribute('src')")))
    check("⑥ 需求预演提示条在位（.alert-warn 非线上功能）",
          bool(js("""(() => {
            const a = document.querySelector('main .alert.alert-warn');
            return !!a && a.textContent.includes('非线上功能');
          })()""")))
    check("⑥ 子侧栏 T-17 行 active",
          bool(js("document.querySelector('[data-tpl-id=\"tpl-vendor-accounts\"]').classList.contains('active')")))
    ok = wait_for("(document.getElementById('tpl-frame').contentDocument?.title || '').includes('T-17')",
                  "T-17 帧内加载")
    check("⑥ iframe 内文档真实加载（title 含 T-17）", bool(ok),
          str(js("document.getElementById('tpl-frame').contentDocument?.title || ''"))[:60])
    shot("06-deeplink-t17-light")

    # 回到总览（总览项点击路径）
    js("document.querySelector('#tpl-ov').click()")
    ok = wait_for("document.querySelectorAll('[data-open]').length === 12 && !document.querySelector('#tpl-frame')",
                  "回总览")
    check("⑥ 子侧栏「模板总览」点击回网格（深链参数清除）",
          bool(ok) and js("location.hash") == "#/templates", str(js("location.hash")))

    # ---------- ⑦ 窄屏（≤768：.panel-split 子侧栏转全宽横条带，§2.3 v2.16 规则命中本页） ----------
    cmd("Emulation.setDeviceMetricsOverride", **{
        "width": 768, "height": 900, "deviceScaleFactor": 2, "mobile": False})
    time.sleep(0.8)
    ok = js("(() => { const s = document.querySelector('.panel-split > .subnav'); "
            "return !!s && Math.round(s.getBoundingClientRect().width) === 768; })()")
    check("⑦ ≤768 子侧栏转全宽（.panel-split 断点规则命中）", bool(ok),
          str(js("Math.round(document.querySelector('.panel-split > .subnav')?.getBoundingClientRect().width)")))
    check("⑦ ≤768 横条带可横滚（scrollWidth > clientWidth）",
          bool(js("(() => { const sc = document.querySelector('.subnav-scroll'); "
                  "return sc.scrollWidth > sc.clientWidth; })()")),
          str(js("(() => { const sc = document.querySelector('.subnav-scroll'); "
                 "return `${sc.scrollWidth}/${sc.clientWidth}`; })()")))
    shot("07-overview-narrow768")
    cmd("Emulation.setDeviceMetricsOverride", **{
        "width": 1440, "height": 940, "deviceScaleFactor": 2, "mobile": False})

    ws.close()
finally:
    proc.terminate()
    proc.wait()

fails = [n for n, ok, _ in results if not ok]
print(f"\nTEMPLATES PAGE VERIFY: 实测 {len(results)} 项 · 失败 {len(fails)} 项")
if fails:
    print("失败项：" + "；".join(fails))
    raise SystemExit(1)
print("DONE")
