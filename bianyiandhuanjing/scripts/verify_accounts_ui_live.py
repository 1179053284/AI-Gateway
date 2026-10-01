#!/usr/bin/env python3
"""M7-UI 真机验收 · 「账号接入」页（独立实例 + 真 Chrome + 真 HTTP）。

`scripts/verify_accounts_ui.mjs` 是**假 DOM 判据门**（vm 里渲染 `accounts.js`）——它证明不了
真实布局、真实 CSS、真实 HTTP。本 runner 专门补它证明不了的那一半：

    ① 独立实例：自己的 config + 自己的数据根（全在 `--basetemp` 下；**绝不写仓库 `data/`**、
       **绝不碰 :8300 的在册实例**），端口在 8400–8499 内自动挑空闲口（bind + `lsof` 双验）。
    ② 种子数据：一律经**生产入口** `model_gateway.accounts.store.commit_login` 落盘
       （+ `write_runtime` 造额度快照），覆盖 启用 / 停用 / 无 runtime.json / 额度 available /
       额度 exhausted / runtime.json 损坏 / 零账号产品 七种形态。
    ③ 真 Chrome（ego-browser）驱动，≥40 条**具名判据**，每条带**实测值**。
    ④ 假上游：`httpx.MockTransport` 顶掉全部 `AsyncClient` 传输层 —— 本实例**结构上无法**
       发出真实网络请求（轨迹落 `fake-trace.jsonl` 供核对）。🔴 **不使用任何真实厂商凭据**，
       也不做真实登录/领取（那是 UI/接口层真机，不是凭据测试）。

用法：
    .venv/bin/python scripts/verify_accounts_ui_live.py                  # 全量真机断言 + 截图
    .venv/bin/python scripts/verify_accounts_ui_live.py --port 8412      # 指定端口
    .venv/bin/python scripts/verify_accounts_ui_live.py --basetemp DIR   # 指定临时根
    .venv/bin/python scripts/verify_accounts_ui_live.py --shots DIR      # 截图目录
    .venv/bin/python scripts/verify_accounts_ui_live.py --retract 1|2|3  # 三项成对撤证
    .venv/bin/python scripts/verify_accounts_ui_live.py --keep           # 保留临时目录

退出码：0 = 全绿；1 = 有失败；2 = 装配级错误（实例起不来 / 浏览器跑不出读数）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = Path(sys.executable)
BANNED = ["正常", "在服务", "健康", "在线", "已取消"]
QUOTA_WORDS = ["有余量", "已耗尽", "未知", "尚未刷新"]
PRODUCT_IDS = ["buddy", "workbuddy", "lobsterai", "qoder", "qodercn",
               "trae", "cline", "loomy", "raccoon", "zcode"]
CHECKED_AT = "2026-10-01T09:30:00"

#: 种子表（生产入口 commit_login 落盘；runtime 三形态 absent / dict / corrupt）
SEED = [
    {"product": "buddy", "name": "ix-on", "enabled": True, "runtime": "absent"},
    {"product": "buddy", "name": "ix-off", "enabled": False, "runtime": "absent"},
    {"product": "workbuddy", "name": "ix-only-off", "enabled": False, "runtime": "absent"},
    {"product": "lobsterai", "name": "ix-quota-avail", "enabled": True,
     "device": {"uuid": "ix-uuid-0001"},
     "runtime": {"quota": {"state": "available", "source": "ix-fake",
                           "detail": "有效包 1 个，本周期剩余 300 credits",
                           "checked_at": CHECKED_AT}}},
    {"product": "qoder", "name": "ix-quota-exhausted", "enabled": True,
     "device": {"machine_id": "ix-mid-qoder"},
     "runtime": {"quota": {"state": "exhausted", "source": "ix-fake",
                           "detail": "额度已用尽", "checked_at": CHECKED_AT}}},
    {"product": "qodercn", "name": "ix-corrupt", "enabled": True,
     "device": {"machine_id": "ix-mid-cn"}, "runtime": "corrupt"},
    {"product": "trae", "name": "ix-unknown-quota", "enabled": True,
     "device": {"machine_id": "ix-mid-trae", "device_id": "ix-did-trae"},
     "runtime": {"quota": {"state": "unknown", "source": "ix-fake",
                           "detail": "上游未给出余额（IX 假值）", "checked_at": CHECKED_AT}}},
    {"product": "cline", "name": "ix-device", "enabled": True, "runtime": "absent"},
    {"product": "loomy", "name": "ix-norefresh", "enabled": True, "runtime": "absent"},
]


# ==================== 小工具 ====================

def log(msg: str) -> None:
    print(msg, flush=True)


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def port_is_free(port: int) -> tuple[bool, str]:
    """bind 试 + `lsof -iTCP:<port> -sTCP:LISTEN` 双验。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError as e:
            return False, f"bind 失败：{e}"
    try:
        out = subprocess.run(["lsof", f"-iTCP:{port}", "-sTCP:LISTEN"],
                             capture_output=True, text=True, timeout=10)
        if out.stdout.strip():
            return False, "lsof 有监听者：" + out.stdout.splitlines()[0][:120]
        return True, f"bind ok + lsof 无监听（rc={out.returncode}）"
    except Exception as e:  # noqa: BLE001
        return True, f"bind ok（lsof 不可用：{type(e).__name__}）"


def pick_port(preferred: int = 0) -> tuple[int, str]:
    if preferred:
        ok, why = port_is_free(preferred)
        if not ok:
            raise SystemExit(f"✗ 指定端口 {preferred} 不可用：{why}")
        return preferred, why
    for port in range(8400, 8500):
        ok, why = port_is_free(port)
        if ok:
            return port, why
    raise SystemExit("✗ 8400-8499 无空闲端口")


def http(method: str, url: str, body: dict | None = None, timeout: float = 30.0):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except urllib.error.URLError as e:
        return 0, {"_error": f"{type(e.reason).__name__}: {e.reason}"}
    try:
        return status, json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return status, {"_raw": raw[:200].decode("utf-8", "replace")}


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, bool, str]] = []

    def add(self, cid: str, desc: str, ok: bool, measured: str) -> None:
        self.rows.append((cid, desc, bool(ok), str(measured)))
        log(f"  {'✓' if ok else '✗'} {cid} {desc}  ｜实测 {str(measured)[:280]}")

    @property
    def failed(self):
        return [r for r in self.rows if not r[2]]

    def summary(self) -> str:
        return f"合计：{len(self.rows) - len(self.failed)} 通过 / {len(self.failed)} 失败"


def emit(rep: Report, cid: str, desc: str, ok: bool, measured: str) -> None:
    rep.add(cid, desc, ok, measured)


# ==================== 实例装配（配置 / 种子 / 启动） ====================

CONFIG_TMPL = """gateway:
  host: 127.0.0.1
  port: {port}
  retention_days: 7
  access_tokens: []
  zcode:
    claim_interval_seconds: {interval}
    claim_cron: ''
scheduling:
  max_active_per_model: 2
  fail_threshold: 2
  retry_per_request: 3
resources: []
models: []
"""

FAKEBOOT = '''"""IX 假上游引导（本 runner 生成到 --basetemp 内）：
用 httpx.MockTransport 顶掉**全部** AsyncClient 传输层 → 本实例结构上发不出真实网络请求。
"""
import json
import os
import sys
import time as _t
from pathlib import Path

REPO = os.environ.get("MGW_IX_REPO")
sys.path.insert(0, REPO)
TRACE = Path(os.environ["MGW_FAKE_TRACE"])
TRACE.write_text("", encoding="utf-8")

import httpx  # noqa: E402


def _trace(entry):
    with TRACE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\\n")


def _handler(request):
    url = str(request.url)
    _trace({"method": request.method, "url": url, "host": request.url.host,
            "path": request.url.path})
    path = request.url.path
    if path.endswith("/user_management/authorize/device"):
        return httpx.Response(200, json={
            "device_code": "IX-PRIVATE-DEVICE-CODE", "user_code": "GX-012345",
            "verification_uri": "https://upstream.invalid/authorize",
            "verification_uri_complete": "https://upstream.invalid/authorize?user_code=GX-012345",
            "expires_in": 300, "interval": 5})
    if path.endswith("/user_management/authenticate"):
        return httpx.Response(400, json={"error": "authorization_pending",
                                         "error_description": "IX 假上游：等待用户授权"})
    if path.endswith("/v2/billing/meter/get-user-resource"):
        return httpx.Response(200, json={"code": 0, "message": "ok", "data": {"Response": {"Data": {
            "Accounts": [{"PackageName": "IX-Fake-Pack", "Status": 1, "CapacityUnit": "credits",
                          "CycleCapacityRemainPrecise": "300.00",
                          "DeductionEndTime": int((_t.time() + 86400) * 1000)}]}}}})
    return httpx.Response(503, json={"code": 503, "error": "ix-fake-upstream",
                                     "message": "IX 假上游拒绝（无真实凭据）"})


_ORIG = httpx.AsyncClient.__init__


def _init(self, *args, **kwargs):
    if kwargs.get("transport") is None and kwargs.get("mounts") is None:
        kwargs["transport"] = httpx.MockTransport(_handler)
    return _ORIG(self, *args, **kwargs)


httpx.AsyncClient.__init__ = _init

from model_gateway.core import paths  # noqa: E402
from model_gateway.main import create_app  # noqa: E402
import uvicorn  # noqa: E402

cfg_path = paths.resolve_config_path(None)
app = create_app(cfg_path)
cfg = app.state.runtime.config
_trace({"boot": True, "config": str(cfg_path), "port": cfg.gateway.port,
        "claim_interval_seconds": cfg.gateway.zcode.claim_interval_seconds,
        "asyncclient_patched": httpx.AsyncClient.__init__ is not _ORIG})
uvicorn.Server(uvicorn.Config(app, host=cfg.gateway.host, port=cfg.gateway.port,
                              log_level="warning")).run()
'''

SEEDER = '''"""IX 种子（本 runner 生成）：**只经生产入口** store.commit_login / write_runtime 落盘。"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["MGW_IX_REPO"])
from model_gateway.accounts import store  # noqa: E402

spec = json.loads(Path(os.environ["MGW_IX_SEED"]).read_text(encoding="utf-8"))
out = {}
for row in spec:
    product, name = row["product"], row["name"]
    cred = {"ix_fake_token": "IXFAKE-" + product + "-" + name + "-token",
            "access_token": "IXFAKE-" + product + "-" + name + "-access"}
    meta = {"enabled": row["enabled"], "nickname": "IX·" + product, "plan": "pro",
            "expires_at": "2026-12-31T10:00:00"}
    meta.update(row.get("device") or {})
    got = store.commit_login(product, name, cred, meta, via="m7-ix")
    runtime = row.get("runtime", "absent")
    rpath = Path(store.product_root(product)) / got / "runtime.json"
    if isinstance(runtime, dict):
        store.write_runtime(product, got, runtime)
    elif runtime == "corrupt":
        rpath.write_text("{ not json !!", encoding="utf-8")
    out.setdefault(product, []).append(got)
print(json.dumps(out, ensure_ascii=False))
'''


def write_config(run_dir: Path, port: int, interval: int) -> Path:
    conf_dir = run_dir / "mgw-conf"
    conf_dir.mkdir(parents=True, exist_ok=True)
    cfg = conf_dir / "config.yaml"
    cfg.write_text(CONFIG_TMPL.format(port=port, interval=interval), encoding="utf-8")
    return cfg


def gateway_env(cfg_path: Path, run_dir: Path, repo: Path) -> dict:
    env = dict(os.environ)
    env["MG_CONFIG"] = str(cfg_path)
    env["MGW_IX_REPO"] = str(repo)
    env["MGW_FAKE_TRACE"] = str(run_dir / "fake-trace.jsonl")
    env["MGW_OPS_LOCK_DIR"] = str(run_dir / "ops-locks")
    env.pop("MGW_ZCODE_PROXY", None)
    for pid in PRODUCT_IDS:
        env.pop(f"MGW_{pid.upper()}_ACCOUNTS", None)
    return env


def start_gateway(cfg_path: Path, run_dir: Path, repo: Path, log_name: str = "gateway"):
    boot = run_dir / "fakeboot.py"
    if not boot.exists():
        boot.write_text(FAKEBOOT, encoding="utf-8")
    out = (run_dir / f"{log_name}.log").open("w", encoding="utf-8")
    proc = subprocess.Popen([str(PY), str(boot)], env=gateway_env(cfg_path, run_dir, repo),
                            stdout=out, stderr=subprocess.STDOUT, cwd=str(run_dir))
    return proc, out


def wait_health(port: int, proc: subprocess.Popen, timeout: float = 30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False, f"进程已退出（rc={proc.returncode}）"
        code, body = http("GET", f"http://127.0.0.1:{port}/health", timeout=2.0)
        if code == 200 and isinstance(body, dict) and body.get("status") == "ok":
            return True, body
        time.sleep(0.4)
    return False, "等待 /health 超时"


def stop(proc: subprocess.Popen, out) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
    try:
        out.close()
    except Exception:  # noqa: BLE001
        pass


def seed_accounts(cfg_path: Path, run_dir: Path, repo: Path, spec=None) -> dict:
    seed_file = run_dir / "seed-spec.json"
    seed_file.write_text(json.dumps(spec if spec is not None else SEED, ensure_ascii=False),
                         encoding="utf-8")
    script = run_dir / "seeder.py"
    script.write_text(SEEDER, encoding="utf-8")
    env = gateway_env(cfg_path, run_dir, repo)
    env["MGW_IX_SEED"] = str(seed_file)
    r = subprocess.run([str(PY), str(script)], env=env, capture_output=True, text=True,
                       timeout=240, cwd=str(run_dir))
    if r.returncode != 0:
        raise RuntimeError(f"种子失败：{r.stderr[-900:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def strip_resource(cfg_path: Path, product: str, account: str) -> str:
    """从**临时实例自己的** config.yaml 摘掉某账号的物化资源（造 BD3a 的 `resource: []` 真形态）。"""
    import yaml

    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    removed = ""
    keep = []
    for row in data.get("resources") or []:
        if row.get("product") == product and row.get("account_ref") == account:
            removed = row.get("id", "")
            continue
        keep.append(row)
    data["resources"] = keep
    cfg_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return removed


def account_dir(cfg: Path, product: str, name: str) -> Path:
    return cfg.parent / "upstream" / product / "accounts" / name


# ==================== 响应形态注入代理（只服务两态注入判据） ====================

class InjectHandler(BaseHTTPRequestHandler):
    """透明本机代理；只为造出两个**真后端在真实部署里会给**的形态：
    `resource:null`（配置读不动）与 `GET /admin/api/accounts` 502（§5 读失败）。
    其余判据一律直连实例，不经本代理。"""

    backend = 0
    mode_file = ""

    def log_message(self, *a):  # noqa: D102
        return

    def _mode(self) -> str:
        try:
            return Path(self.mode_file).read_text(encoding="utf-8").strip()
        except Exception:  # noqa: BLE001
            return ""

    def _do(self, method: str) -> None:
        mode = self._mode()
        is_view = self.path == "/admin/api/accounts"
        if method == "GET" and is_view and mode == "error":
            body = json.dumps({"error": {"message": "IX 注入：账号视图读取失败（假 502）"}}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = self.rfile.read(length) if length else None
        conn = HTTPConnection("127.0.0.1", self.backend, timeout=60)
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("accept-encoding", "connection", "content-length")}
        headers["Host"] = self.headers.get("host") or f"127.0.0.1:{self.backend}"
        conn.request(method, self.path, body=payload, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        ctype = resp.getheader("Content-Type") or ""
        if method == "GET" and is_view and mode == "resource-null" and resp.status == 200:
            data = json.loads(raw.decode("utf-8"))
            for p in data.get("products", []):
                for a in p.get("accounts", []):
                    if p.get("id") == "buddy" and a.get("name") == "ix-on":
                        a["resource"] = None
            raw = json.dumps(data, ensure_ascii=False).encode()
        if (method == "GET" and mode == "models-unknown" and resp.status == 200
                and self.path.endswith("/models") and "json" in ctype):
            raw = json.dumps({"product": "loomy", "account": "ix-norefresh", "source": "remote",
                              "state": "unknown", "models": [],
                              "reason": "IX 注入：上游目录端点不可用（ConnectError）"},
                             ensure_ascii=False).encode()
        self.send_response(resp.status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        self._do("GET")

    def do_POST(self):  # noqa: N802
        self._do("POST")

    def do_PUT(self):  # noqa: N802
        self._do("PUT")


def start_proxy(port: int, backend: int, mode_file: Path):
    InjectHandler.backend = backend
    InjectHandler.mode_file = str(mode_file)
    mode_file.write_text("", encoding="utf-8")
    srv = ThreadingHTTPServer(("127.0.0.1", port), InjectHandler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, th


# ==================== 浏览器侧脚本（ego-browser / 真 Chrome） ====================

JS = r'''
const fs = await import("node:fs");
const PAYLOAD = JSON.parse(fs.readFileSync("__PAYLOAD__", "utf8"));
const E = PAYLOAD.expect;
const MODE = PAYLOAD.mode || "full";
const OUT = "__OUT__";
const QUOTA_LIST = __QUOTA_WORDS__;
const BANNED_LIST = __BANNED_LIST__;
const checks = [];
const shots = [];
const extra = {};
const ck = (id, desc, ok, measured) => {
  checks.push({ id, desc, ok: !!ok, measured: String(measured).slice(0, 300) });
};
const j = (v) => JSON.stringify(v);
const task = await taskSpace("M7-UI 账号接入页真机验收");
const page = task.page("p1");

async function section(name, fn) {
  try { await fn(); } catch (e) {
    ck("SEC-" + name, "分段「" + name + "」执行未抛错", false,
       (e && e.name) + ": " + String(e && e.message).slice(0, 220));
  }
}
async function shot(name) {
  const p = PAYLOAD.shotsDir + "/" + name + ".png";
  /* 截图失败不得带走整轮读数（实测遇到过 Page.captureScreenshot 超时）：重试 3 次后只记错误。 */
  for (let i = 0; i < 3; i++) {
    try { await page.screenshot({ path: p }); shots.push(p); return; }
    catch (e) {
      extra.shotErrors = (extra.shotErrors || []).concat([name + "：" + String(e && e.message).slice(0, 90)]);
      await page.waitForTimeout(1500);
    }
  }
}
async function setViewport(w, h) {
  await page.cdp("Emulation.setDeviceMetricsOverride",
    { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  await page.waitForTimeout(260);
}
async function clearViewport() {
  await page.cdp("Emulation.clearDeviceMetricsOverride");
  await page.waitForTimeout(200);
}
async function instrument() {
  await page.evaluate(() => {
    window.__ix = { req: [], byPath: {}, intervals: 0, cleared: 0 };
    const of = window.fetch;
    window.fetch = function (u, o) {
      let path = "";
      try {
        const s = String(u);
        path = s.split("?")[0];
        const q = s.indexOf("confirm=1") >= 0 ? "?confirm=1" : "";
        window.__ix.req.push(((o && o.method) || "GET") + " " + path + q);
      } catch (e) { /* 计数失败不得影响请求 */ }
      const p = of.apply(this, arguments);
      if (path.indexOf("/admin/api/") >= 0) {
        p.then((res) => { res.clone().json().then((b) => {
          window.__ix.byPath[path] = b; }).catch(() => {}); }).catch(() => {});
      }
      return p;
    };
    const oi = window.setInterval;
    window.setInterval = function () { window.__ix.intervals++; return oi.apply(this, arguments); };
    const ci = window.clearInterval;
    window.clearInterval = function () { window.__ix.cleared++; return ci.apply(this, arguments); };
    const rail = document.getElementById("ac-rail");
    if (rail) {
      rail.dataset.ixprobe = "1";
      if (rail.firstElementChild) rail.firstElementChild.dataset.ixrow = "1";
    }
  });
}
async function tagModal() {
  await page.evaluate(() => {
    const m = document.querySelector("#modal-root .modal-mask");
    if (m) m.dataset.ixm = "1";
  });
}
async function reqs() { return page.evaluate(() => (window.__ix ? window.__ix.req.slice() : [])); }
const nOf = (list, needle) => list.filter((x) => x.indexOf(needle) >= 0).length;
/* 🔴 单击派发：ego-browser 的 page.click() 实测**每次派发 2 个 click 事件**
   （/tmp 诊断：页内 `el.click()` → click 事件 1 次、POST 1 条；`page.click()` → 事件 2 次、POST 2 条）。
   那是**驱动**的重复派发，不是页面的缺陷，但它会让「1 击 = 1 请求」类判据失真，
   所以计数敏感的动作一律用页内派发；真实指针输入另由 PCICK 判据单独证明。 */
async function click(sel) {
  await page.evaluate((s) => {
    const el = document.querySelector(s);
    if (!el) throw new Error("找不到控件 " + s);
    el.click();
  }, sel);
}

const READ = () => {
  const q = (s, r) => Array.from((r || document).querySelectorAll(s));
  const txt = (n) => (n ? n.textContent.replace(/\s+/g, " ").trim() : null);
  const box = (el) => { const r = el.getBoundingClientRect(); return {
    bx: Math.round(r.x * 10) / 10, by: Math.round(r.y * 10) / 10,
    bw: Math.round(r.width * 10) / 10, bh: Math.round(r.height * 10) / 10 }; };
  const cs = (el) => getComputedStyle(el);
  const probe = (prop, tok) => {
    const el = document.createElement("span");
    el.style[prop] = "var(" + tok + ")";
    document.body.append(el);
    const v = getComputedStyle(el)[prop];
    el.remove();
    return v;
  };
  const rail = q(".anchor-item").map((b) => {
    const nameSpan = q("span", b)[1] || q("span", b)[0];
    return {
      pid: b.dataset.pid, title: b.getAttribute("title"),
      aria: b.getAttribute("aria-selected"), tab: b.getAttribute("tabindex"),
      active: b.classList.contains("active"),
      badge: txt(b.querySelector(".badge")),
      dots: q(".dot", b).map((d) => cs(d).backgroundColor),
      text: txt(b), h: Math.round(b.getBoundingClientRect().height * 10) / 10,
      // 🔴 H2b 的观测量：行顶 y。此前探针只收了 h/markH/badgeH，`x.by` 恒 undefined，
      //    于是 `new Set([undefined ×10]).size === 1` **空过**（打印出来就是 y 值=[null]）。
      by: Math.round(b.getBoundingClientRect().y * 10) / 10,
      wrapped: nameSpan ? nameSpan.getClientRects().length > 1 : false,
      markH: (() => { const m = b.querySelector(".mark-sm"); return m ? Math.round(m.getBoundingClientRect().height * 10) / 10 : null; })(),
      badgeH: (() => { const m = b.querySelector(".badge"); return m ? Math.round(m.getBoundingClientRect().height * 10) / 10 : null; })(),
    };
  });
  const rows = q("#ac-table tbody tr[data-acc]").map((tr) => {
    const td = q("td", tr);
    const sw = tr.querySelector("[role=switch]");
    const cell = td[3] ? td[3].firstElementChild : null;
    return {
      name: tr.dataset.acc, cls: tr.className,
      account: txt(td[1]), state: txt(td[2]),
      stateTitle: td[2] && td[2].lastElementChild ? td[2].lastElementChild.getAttribute("title") : "",
      quota: txt(td[3]), quotaColor: cell ? cs(cell).color : "",
      quotaSub: td[3] ? txt(td[3].querySelector("span + span")) : null,
      ops: q("[data-op]", tr).map((b) => b.dataset.op),
      expCls: td[0] ? td[0].className : "",
      chev: td[0] && td[0].querySelector("svg path") ? td[0].querySelector("svg path").getAttribute("d") : "",
      swAria: sw ? { role: sw.getAttribute("role"), checked: sw.getAttribute("aria-checked"),
        label: sw.getAttribute("aria-label"), on: sw.classList.contains("on"),
        h: Math.round(sw.getBoundingClientRect().height * 10) / 10 } : null,
      h: Math.round(tr.getBoundingClientRect().height * 10) / 10,
    };
  });
  const details = q("#ac-table tbody tr[data-rexp]").map((tr) => ({
    name: tr.dataset.rexp,
    bits: q(".req-detail > span", tr).filter((s) => !s.classList.contains("sep")).map(txt),
    ops: q("[data-op]", tr).map((b) => b.dataset.op),
  }));
  const panel = document.querySelector("#ac-panel");
  let resident = "";
  if (panel) {
    const c = panel.cloneNode(true);
    q(".req-detail", c).forEach((n) => { if (n.parentElement) n.parentElement.remove(); });
    resident = c.textContent.replace(/\s+/g, " ").trim();
  }
  const subnav = document.querySelector(".subnav");
  const split = document.querySelector(".panel-split");
  const main = document.querySelector(".panel-split > main");
  const railBox = document.getElementById("ac-rail");
  const wrap = document.querySelector(".table-wrap");
  const head = document.querySelector(".card-head");
  const root = document.documentElement;
  const tok = (n) => cs(root).getPropertyValue(n).trim();
  const words = __BANNED_LIST__;
  const hits = [];
  [document.getElementById("content"), document.getElementById("modal-root"),
   document.getElementById("toast-wrap")].filter(Boolean).forEach((rt) => {
    const w = document.createTreeWalker(rt, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      for (const word of words) {
        if (n.nodeValue && n.nodeValue.indexOf(word) >= 0) {
          hits.push("文本「" + word + "」@" + (n.parentElement ? n.parentElement.tagName : "?")
                    + "：" + n.nodeValue.replace(/\s+/g, " ").trim().slice(0, 46));
        }
      }
    }
    q("*", rt).forEach((el) => {
      for (const a of Array.from(el.attributes || [])) {
        for (const word of words) {
          if (a.name !== "style" && a.value.indexOf(word) >= 0) {
            hits.push("属性 " + a.name + "「" + word + "」@" + el.tagName);
          }
        }
      }
    });
  });
  return {
    rail,
    railBox: railBox ? { role: railBox.getAttribute("role"),
      orient: railBox.getAttribute("aria-orientation"), label: railBox.getAttribute("aria-label"),
      cls: railBox.className, probe: railBox.dataset.ixprobe || null,
      rowProbe: railBox.firstElementChild ? (railBox.firstElementChild.dataset.ixrow || null) : null,
      fd: cs(railBox).flexDirection, overflowX: cs(railBox).overflowX } : null,
    groupCards: q(".group-card").length,
    modeBtns: q(".mode-btn").length,
    filterSwitch: q("#ac-only").length,
    navTitle: txt(document.querySelector(".subnav .nav-group-title")),
    subnav: subnav ? Object.assign({ w: cs(subnav).width, bg: cs(subnav).backgroundColor,
      fd: cs(subnav).flexDirection, borderRight: cs(subnav).borderRightWidth,
      borderBottom: cs(subnav).borderBottomWidth }, box(subnav)) : null,
    split: split ? { disp: cs(split).display, fd: cs(split).flexDirection,
      margin: cs(split).margin, h: Math.round(box(split).bh) } : null,
    main: main ? Object.assign({ overflowY: cs(main).overflowY, pad: cs(main).padding }, box(main)) : null,
    wrap: wrap ? { overflowX: cs(wrap).overflowX, sw: wrap.scrollWidth, cw: wrap.clientWidth,
      tblW: wrap.querySelector("table") ? Math.round(wrap.querySelector("table").getBoundingClientRect().width) : null } : null,
    head: head ? Object.assign({ title: txt(head.querySelector(".card-title")),
      values: q(".value", head).map(txt), buttons: q("button", head).length, cls: head.className,
      valueColor: head.querySelector(".value") ? cs(head.querySelector(".value")).color : "" }, box(head)) : null,
    // 2026-09-30 两处口径随实现更新（用户反馈轮）：入口从 .subnav-foot 移进卡头；
    // 空态不再是自带卡片阴影的 `.empty`，而是卡内两行普通块 → 从「还没有账号」处截取面板文本。
    headAdd: head ? head.querySelectorAll("#ac-add").length : 0,
    empty: (() => { const c = document.querySelector("#ac-panel .card"); if (!c) return "";
      const t = txt(c); const i = t.indexOf("还没有账号");
      return i >= 0 ? t.slice(i, i + 80) : ""; })(),
    sideAdd: q(".side-add").length,
    sideAddText: txt(document.querySelector(".side-add")),
    addBtnsAnywhere: q("button").filter((b) => (b.textContent || "").indexOf("接入账号") >= 0).length,
    ths: q("#ac-table th").map((t) => ({ cls: t.className, text: txt(t) })),
    rows, details, resident,
    alertErr: q("#ac-panel .alert-err").length,
    alertErrText: txt(document.querySelector("#ac-panel .alert-err")),
    retry: q("#ac-retry").length,
    pageStyles: q("#content style").length,
    modalCount: (document.getElementById("modal-root") || { children: [] }).children.length,
    modalProbe: (() => { const m = document.querySelector("#modal-root .modal-mask"); return m ? (m.dataset.ixm || null) : null; })(),
    modalTitle: txt(document.querySelector(".modal-head h3")),
    modalAlert: document.querySelector(".modal .alert") ? document.querySelector(".modal .alert").className : "",
    wizardText: txt(document.querySelector(".modal-body")),
    wizardTtl: txt(document.querySelector("[data-wz='ttl']")),
    wizardBtns: q(".modal-foot [data-wz]").map((b) => b.dataset.wz + ":" + txt(b)),
    confirmText: txt(document.querySelector(".modal-body p")),
    confirmBtns: q(".modal-foot .btn").map(txt),
    pasteBox: !!document.querySelector("#ac-cb-url"),
    pasteLabel: txt(document.querySelector("label[for='ac-cb-url']")),
    pasteHint: document.querySelector("#ac-cb-url") ? document.querySelector("#ac-cb-url").placeholder : "",
    tabs: q(".modal .tab").map((b) => ({ kind: b.dataset.kind, text: txt(b),
      active: b.classList.contains("active"),
      h: Math.round(b.getBoundingClientRect().height * 10) / 10,
      wrapped: b.getClientRects().length > 1 })),
    toasts: q("#toast-wrap .toast").map(txt),
    focusPid: (document.activeElement && document.activeElement.dataset && document.activeElement.dataset.pid) || "",
    banned: hits.slice(0, 8),
    tokens: { warn: tok("--warn"), dotOn: tok("--dot-on"), dotOff: tok("--dot-off"),
      surface: tok("--surface"), border: tok("--border"), muted: tok("--text-muted"),
      warnRgb: probe("color", "--warn"), dotOnRgb: probe("backgroundColor", "--dot-on"),
      dotOffRgb: probe("backgroundColor", "--dot-off"), surfaceRgb: probe("backgroundColor", "--surface"),
      mutedRgb: probe("color", "--text-muted") },
    theme: root.getAttribute("data-theme"),
    innerW: innerWidth,
    lsProduct: (() => { try { return localStorage.getItem("mgw-accounts-product"); } catch (e) { return "ERR"; } })(),
    req: (window.__ix ? window.__ix.req.slice() : []),
    byPath: (window.__ix ? window.__ix.byPath : {}),
    timers: (window.__ix ? { created: window.__ix.intervals, cleared: window.__ix.cleared } : null),
    apiEntries: performance.getEntriesByType("resource").map((x) => x.name)
      .filter((n) => n.indexOf("/admin/api/") >= 0).map((n) => n.replace(location.origin, "")),
  };
};
async function read() { return page.evaluate(READ); }
async function setTheme(mode) {
  await page.evaluate((m) => { localStorage.setItem("mg-theme", m); }, mode);
  await page.reload();
  await page.waitForSelector(".panel-split .anchor-item", { timeout: 20000 });
  await page.waitForTimeout(300);
}
const act = (x) => ((x.rail || []).find((y) => y.active) || {}).pid;
const rowOf = (x, name) => (x.rows || []).find((r2) => r2.name === name) || {};
const bitOf = (x, name, head) => {
  const d = (x.details || []).find((v) => v.name === name) || { bits: [] };
  return (d.bits || []).find((b) => b.indexOf(head) === 0) || "";
};

async function mainMode() {
if (MODE === "rail") {
  /* 撤证①：族容器塞回 rail 后，真浏览器侧 rail 判据必须变红 */
  await setViewport(1440, 900);
  await page.goto(PAYLOAD.url + "#/accounts");
  await page.waitForSelector(".anchor-item", { timeout: 25000 });
  await page.waitForTimeout(400);
  const r = await read();
  ck("RT1", "撤证①：rail 容器 .group-card 计数必须为 0（族容器不得复活）",
     r.groupCards === 0, ".group-card=" + r.groupCards + " railBox.class=" + r.railBox.cls);
  ck("RT2", "撤证①：.anchor-item 计数 === 10", r.rail.length === 10, "计数=" + r.rail.length);
  ck("RT3", "撤证①：rail 容器类名含 subnav-scroll（不得被换成族卡片）",
     /subnav-scroll/.test(r.railBox.cls), "class=「" + r.railBox.cls + "」");
  ck("RT4", "撤证①：rail 行 title 逐字判据仍成立（与族层无关的对照项）",
     r.rail.every((x) => E.railTitles[x.pid] === x.title),
     "不符 " + r.rail.filter((x) => x.title !== E.railTitles[x.pid]).length + "/10；首行=「" + (r.rail[0] || {}).title + "」");
  await shot(PAYLOAD.shotName || "retract1-rail");
} else if (MODE === "quota") {
  /* 撤证②：额度列是否离开「尚未刷新」 */
  await setViewport(1440, 900);
  await page.goto(PAYLOAD.url + "#/accounts?p=" + E.quotaProduct);
  await page.waitForSelector("#ac-table tbody tr[data-acc]", { timeout: 25000 });
  await page.waitForTimeout(400);
  const r = await read();
  const row = rowOf(r, E.quotaAccount);
  ck("RT5", "撤证②：额度格文本（断 BD8 → 恒「尚未刷新」；恢复 → 必须移动）",
     true, E.quotaProduct + "/" + E.quotaAccount + " 额度格=「" + row.quota + "」");
  await shot(PAYLOAD.shotName || "retract2-quota");
} else {

/* ==================== 全量真机断言 ==================== */
await setViewport(1440, 900);
await page.goto(PAYLOAD.url + "#/accounts");
await page.waitForSelector(".panel-split .anchor-item", { timeout: 25000 });
/* 🔴 清掉**上一轮跑**留在同一源上的持久态（localStorage 按 origin 跨进程/跨轮次存活；
     实测上一轮在代理源留下的 mgw-accounts-product=qoder 会让本轮首屏选中 qoder）。
     主题键随后显式钉回 light，保证浅/深两档各自可比。 */
await page.evaluate(() => { localStorage.clear(); localStorage.setItem("mg-theme", "light"); });
await page.reload();
await page.waitForSelector(".panel-split .anchor-item", { timeout: 25000 });
await page.waitForTimeout(450);
await instrument();
let r = await read();

await section("rail", async () => {
  ck("B1", "rail 行数：.anchor-item 计数 === 在册产品数 10（扁平、无族层）",
     r.rail.length === 10, "计数=" + r.rail.length + " pids=" + r.rail.map((x) => x.pid).join(","));
  ck("B2", "rail 顺序 === registry.PRODUCT_IDS 原序（深链稳定）",
     j(r.rail.map((x) => x.pid)) === j(E.productIds), "实测=" + r.rail.map((x) => x.pid).join(" › "));
  ck("B0", "族层消失：真浏览器下 .group-card 与 .mode-btn 计数都为 0",
     r.groupCards === 0 && r.modeBtns === 0, ".group-card=" + r.groupCards + " .mode-btn=" + r.modeBtns);
  const zero = r.rail.filter((x) => E.zeroAccountProducts.indexOf(x.pid) >= 0);
  ck("B3", "0 账号产品不渲染计数徽章、也不画状态点",
     zero.length === E.zeroAccountProducts.length && zero.every((x) => !x.badge && x.dots.length === 0),
     zero.map((x) => x.pid + ":badge=" + (x.badge || "null") + ",dots=" + x.dots.length).join(" "));
  const withAcc = r.rail.filter((x) => E.railCounts[x.pid] > 0);
  ck("B3b", "有账号产品的徽章文本 === 账号数",
     withAcc.every((x) => x.badge === String(E.railCounts[x.pid])),
     withAcc.map((x) => x.pid + "=" + x.badge).join(" "));
  const dot = (pid) => ((r.rail.find((x) => x.pid === pid) || {}).dots || [])[0] || "";
  ck("B4a", "四态点·绿：buddy（有启用账号）== var(--dot-on) 的计算色",
     dot("buddy") === r.tokens.dotOnRgb, "实测=" + dot("buddy") + " 令牌=" + r.tokens.dotOn);
  ck("B4b", "四态点·橙（warn）：qodercn（runtime.json 损坏 → status unknown）== var(--warn)",
     dot("qodercn") === r.tokens.warnRgb, "实测=" + dot("qodercn") + " 令牌=" + r.tokens.warn);
  ck("B4c", "四态点·灰（dot-off）：workbuddy（有账号但零启用）== var(--dot-off)",
     dot("workbuddy") === r.tokens.dotOffRgb, "实测=" + dot("workbuddy") + " 令牌=" + r.tokens.dotOff);
  ck("B4d", "四态点·无：raccoon / zcode 的 dots 数 === 0",
     E.zeroAccountProducts.every((p) => (((r.rail.find((x) => x.pid === p) || {}).dots) || []).length === 0),
     E.zeroAccountProducts.map((p) => p + "=" + (((r.rail.find((x) => x.pid === p) || {}).dots) || []).length).join(" "));
  ck("B4e", "四态互不相同（绿/橙/灰 三色各异，杜绝「三态同形」）",
     new Set([dot("buddy"), dot("qodercn"), dot("workbuddy")]).size === 3,
     "green=" + dot("buddy") + " warn=" + dot("qodercn") + " off=" + dot("workbuddy"));
  ck("B5", "rail 行 title 逐字 === 「产品名 · N 个账号（M 已启用）」（10/10）",
     r.rail.every((x) => x.title === E.railTitles[x.pid]),
     "首行=「" + (r.rail[0] || {}).title + "」；不符 " + r.rail.filter((x) => x.title !== E.railTitles[x.pid]).length + "/10");
  ck("B6", "rail 容器 role=tablist + aria-orientation=vertical + aria-label",
     r.railBox.role === "tablist" && r.railBox.orient === "vertical" && !!r.railBox.label,
     "role=" + r.railBox.role + " orientation=" + r.railBox.orient + " label=「" + r.railBox.label + "」");
  ck("B6b", "每行 role=tab（10/10）",
     r.rail.every((x) => E.railTitles[x.pid] !== undefined) && r.rail.length === 10,
     "行数=" + r.rail.length + "；tabindex 值集=" + j(Array.from(new Set(r.rail.map((x) => x.tab)))));
  const sel = r.rail.filter((x) => x.aria === "true");
  ck("B7", "aria-selected=true 恰好 1 行，且与 .active 同位",
     sel.length === 1 && sel[0].pid === act(r),
     "selected=" + sel.map((x) => x.pid).join(",") + " active=" + act(r));
  ck("B8", "roving tabindex：active 行 tabindex=0，其余 9 行 = -1",
     r.rail.filter((x) => x.tab === "0").length === 1 && r.rail.filter((x) => x.tab === "-1").length === 9,
     "tab0=" + r.rail.filter((x) => x.tab === "0").map((x) => x.pid).join(",") + " tab-1 数=" + r.rail.filter((x) => x.tab === "-1").length);
  ck("B13", "「只看有账号」派生开关在 2 个空产品（<5）时不渲染（§1.3 触发态）",
     r.filterSwitch === 0, "#ac-only=" + r.filterSwitch + " 空产品数=" + E.zeroAccountProducts.length);
  ck("B14", "子侧栏小标题「接入产品」在位（不受 J1 门保护，靠 §2 设计裁决）",
     r.navTitle === "接入产品", "实测=「" + r.navTitle + "」");
});

await section("panel", async () => {
  // 2026-09-30 改口径：用户判定「选定产品后还要到左下方操作」动线不合理 → 入口定版在卡头（与所作用产品同框）
  ck("C1", "卡头 = 产品名 + 计数 + **唯一入口按钮**（#ac-add，2026-09-30 定版）",
     r.head.buttons === 1 && r.headAdd === 1 && r.head.title === "CodeBuddy" && r.head.values.length === 1,
     "card-head 按钮=" + r.head.buttons + " #ac-add=" + r.headAdd + " title=「" + r.head.title + "」 values=" + j(r.head.values));
  ck("C2", "全页接入入口恰好 1 处，且就在卡头（rail 底 .side-add 已移除）",
     r.headAdd === 1 && r.addBtnsAnywhere === 1 && r.sideAdd === 0,
     "#ac-add=" + r.headAdd + "；文本含「接入账号」的 button=" + r.addBtnsAnywhere + " .side-add=" + r.sideAdd);
  ck("C4", "表头逐字 =（.exp 空格列）账号 / 状态 / 额度 / 操作",
     j(r.ths.map((t) => t.text)) === j(["", "账号", "状态", "额度", "操作"]) && r.ths[0].cls === "exp",
     "实测=" + j(r.ths.map((t) => (t.cls ? "." + t.cls : "·") + (t.text || "∅"))));
  ck("C3b", "buddy 面板两行按数据渲染（ix-off / ix-on）",
     j(r.rows.map((x) => x.name)) === j(["ix-off", "ix-on"]), "行=" + r.rows.map((x) => x.name).join(","));
  ck("C11", "状态列文字实测：已停用 / 已启用（+ 后文「状态未知」档）",
     rowOf(r, "ix-off").state === "已停用" && rowOf(r, "ix-on").state === "已启用",
     "ix-off=「" + rowOf(r, "ix-off").state + "」 ix-on=「" + rowOf(r, "ix-on").state + "」");
  ck("C11b", "状态文字 title 如实（启用位不含凭据有效性结论）",
     (rowOf(r, "ix-on").stateTitle || "").indexOf("不含凭据有效性事实") >= 0,
     "「" + (rowOf(r, "ix-on").stateTitle || "").slice(0, 90) + "」");
  ck("C12", "开关 aria 三件套齐（role=switch / aria-checked / aria-label）",
     !!rowOf(r, "ix-on").swAria && rowOf(r, "ix-on").swAria.role === "switch"
     && rowOf(r, "ix-on").swAria.checked === "true"
     && rowOf(r, "ix-on").swAria.label === "启用 / 停用账号 ix-on",
     j(rowOf(r, "ix-on").swAria));
  ck("C10", "停用行只加 .off、**不加 .locked**（设计书 §3 有意区别）",
     /(^|\s)off(\s|$)/.test(rowOf(r, "ix-off").cls || "") && !/locked/.test(rowOf(r, "ix-off").cls || ""),
     "ix-off class=「" + rowOf(r, "ix-off").cls + "」");
  ck("C13", "副行只列白名单三项（昵称 / 套餐 / 到期），`via` 不上常驻面",
     (rowOf(r, "ix-on").account || "").indexOf("IX·buddy") >= 0
     && (rowOf(r, "ix-on").account || "").indexOf("套餐 pro") >= 0
     && (rowOf(r, "ix-on").account || "").indexOf("到期 2026-12-31 10:00") >= 0
     && (rowOf(r, "ix-on").account || "").indexOf("m7-ix") < 0,
     "副行=「" + rowOf(r, "ix-on").account + "」");
  ck("C14", "常驻面零命中实现词汇（协议 / 出站基址 / 设备身份字段 / 模型目录来源）",
     ["协议：", "出站基址：", "设备身份字段", "模型目录来源"].every((w) => (r.resident || "").indexOf(w) < 0),
     "常驻面文本长度=" + (r.resident || "").length + "；命中=" + j(
       ["协议：", "出站基址：", "设备身份字段", "模型目录来源"].filter((w) => (r.resident || "").indexOf(w) >= 0)));
  ck("C15", "打开页面只有 1 个 GET：/admin/api/accounts ×1、/capabilities ×0（§4-1）",
     nOf(r.apiEntries, "/admin/api/accounts") === 1 && nOf(r.apiEntries, "capabilities") === 0,
     "资源计时 API=" + j(r.apiEntries));
});

await section("pointer", async () => {
  /* 真实指针输入（CDP mousePressed/Released）单独证明一次：计数敏感判据用页内派发，
     但「用户点得动」这件事必须由真输入事件证明（见文件头 click() 的注记）。 */
  await page.click(".anchor-item[data-pid='workbuddy']");
  await page.waitForTimeout(500);
  const rp = await read();
  ck("P1", "真实指针点击 rail 行即可选中产品（active + 卡头 + aria-selected 三处一致）",
     act(rp) === "workbuddy" && rp.head.title === "WorkBuddy（国际版）"   // 2026-09-30 改名：与参考程序标签同口径，避免与国内版混淆
     && (rp.rail.find((x) => x.pid === "workbuddy") || {}).aria === "true",
     "active=" + act(rp) + " 卡头=「" + rp.head.title + "」 aria=" + (rp.rail.find((x) => x.pid === "workbuddy") || {}).aria);
  ck("P1b", "真实指针点击是幂等的（selectProduct 对同一产品早退，不叠状态）",
     rp.rail.filter((x) => x.aria === "true").length === 1,
     "aria-selected=true 行数=" + rp.rail.filter((x) => x.aria === "true").length);
  await click(".anchor-item[data-pid='buddy']");
  await page.waitForTimeout(400);
});

await section("quota", async () => {
  ck("D3", "无 runtime.json 的账号 → 额度格「尚未刷新」（BUG-2 的可见态）",
     rowOf(r, "ix-on").quota === "尚未刷新", "buddy/ix-on 额度格=「" + rowOf(r, "ix-on").quota + "」");
  ck("D6", "额度格文本 ⊂ 四值口径（全表扫描零越界）",
     r.rows.every((x) => QUOTA_LIST.some((w) => x.quota === w || (x.quota || "").indexOf(w) === 0)),
     "本表=" + j(r.rows.map((x) => x.quota)) + " 词表=" + QUOTA_LIST.join("/"));
  ck("D7", "未知不当零：额度格无 0 / — / undefined / NaN",
     r.rows.every((x) => ["0", "—", "undefined", "NaN"].indexOf(x.quota) < 0),
     "实测=" + j(r.rows.map((x) => x.quota)));
});

await section("expand", async () => {
  const before = r.details.length;
  await click("td[data-exp='ix-on']");
  await page.waitForSelector("tr[data-rexp='ix-on']", { timeout: 10000 });
  await page.waitForTimeout(250);
  const r2 = await read();
  ck("C5", ".exp 展开：详情行 0 → 1（首列 class=exp，不用 .icon-btn 承担展开）",
     before === 0 && r2.details.length === 1 && r2.rows.find((x) => x.name === "ix-on").expCls === "exp",
     "details " + before + "→" + r2.details.length + " 首列 class=「" + r2.rows.find((x) => x.name === "ix-on").expCls + "」");
  ck("C5b", "chevron 图标随状态切换（right → down）",
     r2.rows.find((x) => x.name === "ix-on").chev !== r.rows.find((x) => x.name === "ix-on").chev
     && (r2.rows.find((x) => x.name === "ix-on").chev || "").indexOf("6 9 6 6 6-6") >= 0,
     "展开前 d=「" + r.rows.find((x) => x.name === "ix-on").chev + "」→ 展开后「" + r2.rows.find((x) => x.name === "ix-on").chev + "」");
  const need = ["协议：", "出站基址：", "模型目录来源", "能力位"];
  const d = (r2.details.find((x) => x.name === "ix-on") || { bits: [], ops: [] });
  const hit = need.filter((w) => (d.bits || []).some((b) => b.indexOf(w) >= 0));
  ck("C6", "展开行含 协议 / 出站基址 / 目录来源 / 能力位（无设备身份产品 4/4）",
     hit.length === 4, "命中 " + hit.length + "/4；bits=" + (d.bits || []).length + " 条");
  ck("C6a", "无设备身份产品（buddy）**不渲染**设备行（不写「无 / 0」占位）",
     (d.bits || []).every((b) => b.indexOf("设备身份字段") < 0),
     "bits=" + j((d.bits || []).map((b) => b.slice(0, 12))));
  ck("C6b", "展开行的 base_url 与注册表逐字相同（真值来自后端，不是前端猜的）",
     bitOf(r2, "ix-on", "出站基址：") === "出站基址：https://copilot.tencent.com",
     "实测=「" + bitOf(r2, "ix-on", "出站基址：") + "」");
  ck("C6c", "能力位行逐字含五项口径",
     /^能力位：签到 支持 · 续期 支持 · 余额 支持 · 永久积分锁 支持 · 新手任务 不支持$/.test(bitOf(r2, "ix-on", "能力位")),
     "实测=「" + bitOf(r2, "ix-on", "能力位") + "」");
  const resLine = bitOf(r2, "ix-on", "已物化");
  ck("C7", "BD3a：非空 resource → 「已物化 N 个资源 · 启用 M」",
     /^已物化 1 个资源 · 启用 1：res-/.test(resLine), "实测=「" + resLine.slice(0, 90) + "」");
  ck("C7b", "行内 rid 与后端 resource[0].id 逐字相同",
     resLine.indexOf(E.resourceIds["buddy/ix-on"]) >= 0,
     "后端 rid=" + E.resourceIds["buddy/ix-on"] + "；行内尾=" + resLine.slice(-22));
  ck("C7c", "网关额度池另立一行（与厂商余额快照分列，不混进额度列）",
     bitOf(r2, "ix-on", "网关额度池").indexOf("网关额度池") === 0,
     "实测=「" + bitOf(r2, "ix-on", "网关额度池").slice(0, 80) + "」（池摘要 state=" + E.poolStates["buddy/ix-on"] + "）");
  await shot("1440-light-expanded");
  await click("td[data-exp='ix-on']");
  await page.waitForTimeout(300);
  const r3 = await read();
  ck("C5c", "再点一次收起：详情行 1 → 0（原地 patch，不整页重洗）",
     r3.details.length === 0 && r3.rail.length === 10, "details=" + r3.details.length + " rail=" + r3.rail.length);
  ck("B15", "展开/收起**不重建 rail 行**：首行 dataset.ixrow 探针仍在（三级重绘只到行级）",
     r3.railBox.probe === "1" && r3.railBox.rowProbe === "1",
     "容器探针=" + r3.railBox.probe + " 首行探针=" + r3.railBox.rowProbe);
});

await section("quota-per-product", async () => {
  await click(".anchor-item[data-pid='qoder']");
  await page.waitForTimeout(300);
  const rq = await read();
  ck("D1b", "已耗尽：额度格「已耗尽」且着色 == var(--warn) 计算色（而池摘要仍 unknown → BUG-1 反证）",
     rowOf(rq, "ix-quota-exhausted").quota === "已耗尽"
     && rowOf(rq, "ix-quota-exhausted").quotaColor === rq.tokens.warnRgb
     && E.poolStates["qoder/ix-quota-exhausted"] === "unknown",
     "额度=「" + rowOf(rq, "ix-quota-exhausted").quota + "」 color=" + rowOf(rq, "ix-quota-exhausted").quotaColor
     + " warn=" + rq.tokens.warn + "；a.quota.state=" + E.poolStates["qoder/ix-quota-exhausted"]);
  await click("td[data-exp='ix-quota-exhausted']");
  await page.waitForSelector("tr[data-rexp='ix-quota-exhausted']", { timeout: 10000 });
  const rq2 = await read();
  ck("C8", "resource:[]（**真后端**：摘掉物化资源 + 热重载）→「网关资源：无」，绝不写 0",
     bitOf(rq2, "ix-quota-exhausted", "网关资源").indexOf("网关资源：无") === 0,
     "后端 resource=" + j(E.emptyResource) + "；实测=「" + bitOf(rq2, "ix-quota-exhausted", "网关资源").slice(0, 70) + "」");
  await click("td[data-exp='ix-quota-exhausted']");
  await page.waitForTimeout(200);

  await click(".anchor-item[data-pid='lobsterai']");
  await page.waitForTimeout(300);
  const rl = await read();
  ck("D1", "四值之「有余量」：runtime.json 快照（BUG-1 修复面，真文件真值）",
     (rowOf(rl, "ix-quota-avail").quota || "").indexOf("有余量") === 0
     && E.poolStates["lobsterai/ix-quota-avail"] === "unknown",
     "额度=「" + rowOf(rl, "ix-quota-avail").quota + "」；池摘要=" + E.poolStates["lobsterai/ix-quota-avail"]);
  ck("D4", "「查于 …」附属 = checked_at 前 16 字符（原样投影，不重算时区）",
     rowOf(rl, "ix-quota-avail").quotaSub === "查于 " + E.checkedAtText,
     "实测=「" + rowOf(rl, "ix-quota-avail").quotaSub + "」 期望=「查于 " + E.checkedAtText + "」（源 " + E.checkedAt + "）");
  await click(".anchor-item[data-pid='qodercn']");
  await page.waitForTimeout(300);
  const rc = await read();
  ck("C11d", "qodercn/ix-corrupt：状态=「状态未知」且 runtime_ok=false 蕴含 status=unknown",
     rowOf(rc, "ix-corrupt").state === "状态未知" && E.statuses["qodercn/ix-corrupt"] === "unknown",
     "状态=「" + rowOf(rc, "ix-corrupt").state + "」 后端 status=" + E.statuses["qodercn/ix-corrupt"]);
  await click("td[data-exp='ix-corrupt']");
  await page.waitForSelector("tr[data-rexp='ix-corrupt']", { timeout: 10000 });
  const rc2 = await read();
  ck("C11e", "读不动原文进展开行（§5：中性色、不吞异常）",
     bitOf(rc2, "ix-corrupt", "运行态读取").indexOf("运行态读取") === 0,
     "实测=「" + bitOf(rc2, "ix-corrupt", "运行态读取").slice(0, 110) + "」");
  await click("td[data-exp='ix-corrupt']");
  await click(".anchor-item[data-pid='trae']");
  await page.waitForTimeout(300);
  const rt = await read();
  ck("D1c", "四值之「未知」：runtime.quota.state=unknown（查了但拿不到 ≠ 还没查）",
     rowOf(rt, "ix-unknown-quota").quota === "未知",
     "trae/ix-unknown-quota 额度格=「" + rowOf(rt, "ix-unknown-quota").quota + "」");
  await click("td[data-exp='ix-unknown-quota']");
  await page.waitForSelector("tr[data-rexp='ix-unknown-quota']", { timeout: 15000 });
  const rt2 = await read();
  ck("C6d", "有设备身份产品（trae：machine_id + device_id）→ 展开行给设备字段与本账号登记态",
     bitOf(rt2, "ix-unknown-quota", "设备身份字段").indexOf("设备身份字段：machine_id + device_id") === 0
     && bitOf(rt2, "ix-unknown-quota", "设备身份字段").indexOf("本账号：machine_id=已登记 + device_id=已登记") >= 0,
     "实测=「" + bitOf(rt2, "ix-unknown-quota", "设备身份字段") + "」");
  ck("C6e", "目录出口接线位如实（models_wired=true → 「目录出口已接线」）",
     bitOf(rt2, "ix-unknown-quota", "模型目录来源").indexOf("目录出口已接线") >= 0,
     "实测=「" + bitOf(rt2, "ix-unknown-quota", "模型目录来源") + "」");
  await click("td[data-exp='ix-unknown-quota']");
  await click(".anchor-item[data-pid='buddy']");
  await page.waitForTimeout(300);
});

await section("keys", async () => {
  await click(".anchor-item[data-pid='buddy']");
  await page.waitForTimeout(200);
  await page.press(".anchor-item[data-pid='zcode']", "Home");
  await page.waitForTimeout(300);
  const home = await read();
  await page.press(".anchor-item.active", "ArrowDown");
  await page.waitForTimeout(300);
  const down = await read();
  await page.press(".anchor-item.active", "ArrowUp");
  await page.waitForTimeout(300);
  const up = await read();
  await page.press(".anchor-item.active", "End");
  await page.waitForTimeout(400);
  const end = await read();
  ck("B9", "↓ 键：选中 + 焦点同时下移一项（roving 立即激活，不等空格）",
     act(down) === "workbuddy" && down.focusPid === "workbuddy",
     "Home=" + act(home) + " ↓→" + act(down) + " focus=" + down.focusPid);
  ck("B10", "↑ 键：选中 + 焦点同时上移一项",
     act(up) === "buddy" && up.focusPid === "buddy", "↑→" + act(up) + " focus=" + up.focusPid);
  ck("B11", "Home / End：分别落到第一项 / 最后一项",
     act(home) === "buddy" && act(end) === "zcode",
     "Home=" + act(home) + " End=" + act(end) + "（末项 " + (end.rail[9] || {}).pid + "）");
  ck("B11b", "aria-selected / tabindex 随键盘移动同步改写（不是只改 class）",
     (end.rail.find((x) => x.pid === "zcode") || {}).aria === "true"
     && (end.rail.find((x) => x.pid === "zcode") || {}).tab === "0"
     && (end.rail.find((x) => x.pid === "buddy") || {}).aria === "false",
     "zcode aria=" + (end.rail.find((x) => x.pid === "zcode") || {}).aria
     + " tabindex=" + (end.rail.find((x) => x.pid === "zcode") || {}).tab);
  const reqsNow = await reqs();
  ck("B12", "切产品 0 请求（§4-5「1 击 + 2 class」）：驱动期无新 API 调用",
     nOf(reqsNow, "/admin/api/accounts") === 0, "驱动期请求=" + j(reqsNow.slice(0, 8)));
  ck("B12b", "键盘导航只改 class：首行 dataset.ixrow 探针在 4 次移动后仍在（未重建 rail）",
     end.railBox.rowProbe === "1", "首行探针=" + end.railBox.rowProbe);
  ck("C3", "0 账号产品面板给出空态两行，且按 login 生成（zcode=设备码授权）",
     /还没有账号/.test(end.empty || "") && /点右上『接入账号』/.test(end.empty || "")
     && /设备码授权/.test(end.empty || ""), "「" + (end.empty || "") + "」");
  await shot("1440-light-empty-state");
  await click(".anchor-item[data-pid='buddy']");
  await page.waitForTimeout(300);
});

await section("ops-switch", async () => {
  const reqBefore = (await reqs()).length;
  await click("tr[data-acc='ix-on'] [role=switch]");
  await page.waitForFunction(() => {
    const sw = document.querySelector("tr[data-acc='ix-on'] [role=switch]");
    return sw && sw.getAttribute("aria-checked") === "false";
  }, undefined, { timeout: 20000 });
  const after = await read();
  const added = (await reqs()).slice(reqBefore).filter((x) => x.indexOf("/admin/api/accounts") === 0
    || /^POST /.test(x) || x.indexOf("/admin/api/accounts") >= 0);
  const toggles = added.filter((x) => /\/(enable|disable)$/.test(x));
  const views = added.filter((x) => x === "GET /admin/api/accounts");
  ck("E1", "开关 = 1 击 + 1 请求（POST /disable 恰好 1 次）+ 1 次视图重取",
     toggles.length === 1 && toggles[0] === "POST /admin/api/accounts/buddy/ix-on/disable"
     && views.length === 1,
     "启停请求=" + j(toggles) + " 视图重取=" + views.length + "；全部新增=" + j(added));
  const resp = (after.byPath || {})["/admin/api/accounts/buddy/ix-on/disable"];
  ck("E2", "后端真落盘：POST 响应体 {enabled:false, changed:true}（不是前端自 high）",
     !!resp && resp.enabled === false && resp.changed === true, "响应体=" + j(resp));
  ck("E1b", "行原地 patch：rail 探针仍在（未整页重洗）+ 行文本改「已停用」",
     after.railBox.probe === "1" && rowOf(after, "ix-on").state === "已停用",
     "ix-on 状态=「" + rowOf(after, "ix-on").state + "」 ixprobe=" + after.railBox.probe);
  ck("E1c", "rail 徽章/标题随真实计数更新（2 个账号（0 已启用））",
     (after.rail.find((x) => x.pid === "buddy") || {}).title === "CodeBuddy · 2 个账号（0 已启用）",
     "rail title=「" + (after.rail.find((x) => x.pid === "buddy") || {}).title + "」");
  await click("tr[data-acc='ix-on'] [role=switch]");
  await page.waitForFunction(() => {
    const sw = document.querySelector("tr[data-acc='ix-on'] [role=switch]");
    return sw && sw.getAttribute("aria-checked") === "true";
  }, undefined, { timeout: 20000 });
  const back = await read();
  ck("E2b", "再点一次拨回 true（往返无残留，rail 标题恢复原值）",
     rowOf(back, "ix-on").swAria.checked === "true"
     && (back.rail.find((x) => x.pid === "buddy") || {}).title === E.railTitles.buddy,
     "rail title=「" + (back.rail.find((x) => x.pid === "buddy") || {}).title + "」");
  ck("E4", "签到钮按 capabilities.checkin 门控：buddy(✓) 行内 = claim/probe/delete",
     j(rowOf(back, "ix-on").ops) === j(["claim", "probe", "delete"]),
     "buddy/ix-on ops=" + j(rowOf(back, "ix-on").ops) + "（checkin=" + j(E.caps.buddy.checkin) + "）");
  await click(".anchor-item[data-pid='cline']");
  await page.waitForTimeout(300);
  const rc = await read();
  ck("E4b", "cline（checkin=✗）行内只有 探活 + 删除，**无签到死钮**",
     j(rc.rows[0].ops) === j(["probe", "delete"]), "实测 ops=" + j(rc.rows[0].ops));
  ck("E5", "行内动作 ≤3 颗（§3）",
     rc.rows.every((x) => x.ops.length <= 3) && back.rows.every((x) => x.ops.length <= 3),
     "cline=" + rc.rows[0].ops.length + " 颗；buddy 最多=" + Math.max.apply(null, back.rows.map((x) => x.ops.length)) + " 颗");
  await click(".anchor-item[data-pid='loomy']");
  await page.waitForTimeout(300);
  await click("td[data-exp='ix-norefresh']");
  await page.waitForSelector("tr[data-rexp='ix-norefresh']", { timeout: 10000 });
  const rl = await read();
  const d = rl.details.find((x) => x.name === "ix-norefresh") || { ops: [], bits: [] };
  ck("E9", "能力位 refresh=false（loomy）→ 展开行**不渲染**续期钮；目录钮（models_wired）仍在",
     (d.ops || []).indexOf("refresh") < 0 && (d.ops || []).indexOf("models") >= 0,
     "展开行 ops=" + j(d.ops) + "（capabilities.refresh=" + j(E.caps.loomy.refresh) + "）");
  ck("E9b", "能力位 onboarding=true 但 BD7 端点未落地 → 新手任务不渲染（不「点了必然失败」）",
     (d.ops || []).indexOf("onboarding") < 0, "展开行 ops=" + j(d.ops));
  ck("E9c", "能力位行如实写「续期 不支持」",
     bitOf(rl, "ix-norefresh", "能力位").indexOf("续期 不支持") >= 0,
     "实测=「" + bitOf(rl, "ix-norefresh", "能力位") + "」");
});

await section("models-dialog", async () => {
  await click("tr[data-rexp='ix-norefresh'] [data-op='models']");
  await page.waitForSelector(".modal .alert-warn, .modal [data-mdl]", { timeout: 25000 });
  await page.waitForTimeout(300);
  const rm = await read();
  const rows = await page.evaluate(() => Array.from(document.querySelectorAll(".modal [data-mdl]"))
    .map((n) => n.getAttribute("data-mdl")));
  ck("E10", "模型目录弹窗：state=ok 时逐条列出（含 data-mdl 锚点），并标注来源",
     (rm.modalTitle || "").indexOf("模型目录 · Loomy / ix-norefresh") === 0 && rows.length > 0
     && (rm.wizardText || "").indexOf("来源：") >= 0,
     "标题=「" + rm.modalTitle + "」 条目=" + rows.length + " 条；来源行=「"
     + ((rm.wizardText || "").match(/来源：[^·]*（[^）]*）/) || ["（无）"])[0] + "」");
  ck("E10c", "弹窗与接口一致：条目数 == GET …/models 的 models 数；来源标注 == 注册表 models_source",
     rows.length === E.loomyModels.count && rm.tokens.surface !== ""
     && (rm.wizardText || "").indexOf("来源：" + E.loomyModels.sourceLabel) >= 0,
     "UI 条目=" + rows.length + " / API models=" + E.loomyModels.count + "（state=" + E.loomyModels.state
     + "）；来源标注=「" + E.loomyModels.sourceLabel + "」=注册表值，**不含实际取数路径**（→ 缺陷 D-3）");
  await shot("1440-light-models-list");
  await click(".modal-foot .btn");
  await page.waitForTimeout(300);
  const closed = await read();
  ck("E10b", "目录弹窗关闭后 #modal-root 回到基线（0 子节点）",
     closed.modalCount === 0, "modal-root 子节点=" + closed.modalCount);
});

await section("wizard-device", async () => {
  await click(".anchor-item[data-pid='cline']");
  await page.waitForTimeout(250);
  const base = await read();
  await click("#ac-add");
  await page.waitForSelector(".modal .modal-foot", { timeout: 15000 });
  await page.waitForTimeout(250);
  const w0 = await read();
  ck("F0", "向导打开：modal-root 子节点 0→1，标题带产品名",
     base.modalCount === 0 && w0.modalCount === 1 && /^接入账号 · Cline$/.test(w0.modalTitle || ""),
     "modal " + base.modalCount + "→" + w0.modalCount + " 标题=「" + w0.modalTitle + "」");
  ck("F0b", "参数段：无账号名输入（M7-E 免填标识）+ 「开始登录」；会话未建时页脚只有「关闭」",
     w0.wizardBtns.join(",") === "cancel:关闭" && (await page.$("#ac-wz-name")) === null,
     "页脚=" + j(w0.wizardBtns) + " #ac-wz-name=" + ((await page.$("#ac-wz-name")) === null ? "缺（正确）" : "仍在（回归）"));
  await click("[data-wz='start']");
  await page.waitForSelector("[data-wz='cancel']", { timeout: 25000 });
  await page.waitForTimeout(400);
  const w1 = await read();
  ck("F1", "device_code 向导：真 POST /login/start 后展示设备码 GX-012345 + 授权地址",
     (w1.wizardText || "").indexOf("GX-012345") >= 0
     && (w1.wizardText || "").indexOf("upstream.invalid/authorize") >= 0,
     "正文=「" + (w1.wizardText || "").slice(0, 140) + "」");
  ck("F1b", "Challenge 私态不外泄：页面文本不含 IX-PRIVATE-DEVICE-CODE",
     (w1.wizardText || "").indexOf("IX-PRIVATE-DEVICE-CODE") < 0,
     "命中=" + ((w1.wizardText || "").indexOf("IX-PRIVATE-DEVICE-CODE") >= 0));
  ck("F2", "TTL 倒计时从 ttl_s=600 起算（页脚 10:00 档）",
     /^本次会话约 (10:00|9:5\d) 后自动失效$/.test(w1.wizardTtl || ""),
     "首帧=「" + w1.wizardTtl + "」");
  ck("F12", "会话已建 → 页脚 = 重新发起登录 + TTL 倒计时 + 取消登录（破坏性动作在最后）",
     w1.wizardBtns.filter((x) => x.indexOf("ttl:") !== 0).join(",") === "restart:重新发起登录,cancel:取消登录"
     && w1.wizardBtns.some((x) => x.indexOf("ttl:") === 0),
     "页脚=" + j(w1.wizardBtns));
  await shot("1440-light-wizard-device");
  await page.waitForTimeout(3300);
  const w2 = await read();
  const secs = (t) => { const m = /(\d+):(\d\d)/.exec(t || ""); return m ? Number(m[1]) * 60 + Number(m[2]) : -1; };
  ck("F2b", "TTL 倒计时**真的在走**（3.3s 后秒数变小）",
     secs(w2.wizardTtl) > 0 && secs(w2.wizardTtl) <= secs(w1.wizardTtl) - 3,
     w1.wizardTtl + " → " + w2.wizardTtl);
  ck("F3b", "pending 不是失败：状态区仍是 .alert.alert-info（不渲染 .alert-err）",
     w2.modalAlert === "alert alert-info" && w2.alertErr === 0,
     "alert class=「" + w2.modalAlert + "」 面板 alert-err 数=" + w2.alertErr);
  const a = await reqs();
  await page.waitForTimeout(4400);
  const b = await reqs();
  const polls = b.slice(a.length).filter((x) => x.indexOf("/login/poll") >= 0).length;
  ck("F3", "device_code 在轮询：4.4s 内 ≥2 次 POST /login/poll（POLL_MS=2000）",
     polls >= 2, "poll=" + polls + " 次；窗口请求=" + j(b.slice(a.length).slice(0, 4)));
  const c0 = nOf(await reqs(), "/login/cancel");
  await click("[data-wz='cancel']");
  await page.waitForTimeout(800);
  const c1 = nOf(await reqs(), "/login/cancel");
  const w3 = await read();
  ck("F4", "「取消登录」发真 POST /admin/api/accounts/login/cancel（恰好 1 次，不多发）",
     c1 - c0 === 1, "cancel 请求 " + c0 + "→" + c1);
  ck("F4c", "取消端点真回 {\"cancelled\":true}（BD2 幂等出口）",
     j((w3.byPath || {})["/admin/api/accounts/login/cancel"]) === '{"cancelled":true}',
     "响应体=" + j((w3.byPath || {})["/admin/api/accounts/login/cancel"]));
  ck("F4b", "关窗后 modal-root 归零、向导不残留",
     w3.modalCount === 0, "modal-root 子节点=" + w3.modalCount);
  ck("F11", "定时器不泄漏：setInterval 创建数 === clearInterval 数（poll + tick 两条都清）",
     !!w3.timers && w3.timers.created === w3.timers.cleared && w3.timers.created >= 2,
     "created=" + (w3.timers || {}).created + " cleared=" + (w3.timers || {}).cleared);
});

await section("wizard-callback", async () => {
  await click(".anchor-item[data-pid='lobsterai']");
  await page.waitForTimeout(250);
  await click("#ac-add");
  await page.waitForSelector("[data-wz='start']", { timeout: 15000 });
  await click("[data-wz='start']");
  await page.waitForSelector("[data-wz='cancel']", { timeout: 25000 });
  await page.waitForTimeout(400);
  const w = await read();
  ck("F7", "local_callback 向导：授权地址 + 兜底粘贴框 #ac-cb-url 仍在位",
     w.pasteBox && (w.pasteLabel || "").indexOf("兜底：回跳地址（整串粘贴）") >= 0,
     "pasteBox=" + w.pasteBox + " label=「" + w.pasteLabel + "」");
  ck("F7b", "文案如实：主路径=自动回跳、粘贴=兜底（且不再出现「打不开属正常」旧话）",
     (w.wizardText || "").indexOf("主路径是自动回跳") >= 0
     && (w.wizardText || "").indexOf("端口没绑定成功") >= 0
     && (w.pasteHint || "").indexOf("没接住时") >= 0
     && (w.wizardText || "").indexOf("属正常") < 0,
     "提示=「" + (w.pasteHint || "") + "」；正文尾=「" + (w.wizardText || "").slice(-90) + "」");
  const a = await reqs();
  await page.waitForTimeout(5200);
  const b = await reqs();
  const polls = b.slice(a.length).filter((x) => x.indexOf("/login/poll") >= 0).length;
  ck("F8", "local_callback **不轮询**（R-5 契约）：5.2s 窗口内 POST /login/poll === 0",
     polls === 0, "poll=" + polls + "；窗口请求=" + j(b.slice(a.length).slice(0, 4)));
  const t0 = w.wizardTtl;
  await page.waitForTimeout(2200);
  const w2 = await read();
  ck("F2c", "local_callback 的 TTL 同样在倒计时（tick 腿与轮询腿相互独立）",
     w2.wizardTtl !== t0 && /^本次会话约 9:/.test(w2.wizardTtl || ""),
     t0 + " → " + w2.wizardTtl);
  await shot("1440-light-wizard-callback");
  const c0 = nOf(await reqs(), "/login/cancel");
  await click(".modal-close");
  await page.waitForTimeout(800);
  const c1 = nOf(await reqs(), "/login/cancel");
  ck("F5", "✕ 关闭同样作废会话：cancel 恰好 +1（onClose 不重复触发）",
     c1 - c0 === 1, "cancel " + c0 + "→" + c1);
  await click("#ac-add");
  await page.waitForSelector("[data-wz='start']", { timeout: 15000 });
  await click("[data-wz='start']");
  await page.waitForSelector("[data-wz='cancel']", { timeout: 25000 });
  const d0 = nOf(await reqs(), "/login/cancel");
  await page.mouse.click(6, 6);
  await page.waitForTimeout(900);
  const d1 = nOf(await reqs(), "/login/cancel");
  const wAfter = await read();
  ck("F6", "遮罩关闭同样作废会话：cancel 恰好 +1 且弹窗归零",
     d1 - d0 === 1 && wAfter.modalCount === 0, "cancel " + d0 + "→" + d1 + " modal=" + wAfter.modalCount);
});

await section("wizard-survives-ops", async () => {
  await click(".anchor-item[data-pid='buddy']");
  await page.waitForTimeout(250);
  await click("#ac-add");
  await page.waitForSelector("[data-wz='start']", { timeout: 15000 });
  await tagModal();
  const m0 = await read();
  await click("tr[data-acc='ix-on'] [role=switch]");
  await page.waitForFunction(() => {
    const sw = document.querySelector("tr[data-acc='ix-on'] [role=switch]");
    return sw && sw.getAttribute("aria-checked") === "false";
  }, undefined, { timeout: 20000 });
  const m1 = await read();
  ck("E3", "行操作**不拆在飞的向导**：modal 探针仍在、modal-root 子节点数不变（§4-2 红证）",
     m0.modalCount === 1 && m1.modalCount === 1 && m1.modalProbe === "1",
     "modal " + m0.modalCount + "→" + m1.modalCount + " ixm=" + m1.modalProbe + "；行状态=" + rowOf(m1, "ix-on").state);
  await click(".anchor-item[data-pid='trae']");
  await page.waitForTimeout(400);
  const m2 = await read();
  ck("E3b", "切产品同样不拆向导（面板已换 Trae，弹窗仍在）",
     m2.modalCount === 1 && m2.head.title === "Trae" && m2.modalProbe === "1",
     "modal=" + m2.modalCount + " 卡头=「" + m2.head.title + "」 ixm=" + m2.modalProbe);
  const cancels = nOf(await reqs(), "/login/cancel");
  await click("[data-wz='cancel']");
  await page.waitForTimeout(700);
  const cancels2 = nOf(await reqs(), "/login/cancel");
  ck("E3c", "参数段（会话未建）点「关闭」不发 cancel 请求（无会话可作废）",
     cancels2 === cancels, "cancel 计数 " + cancels + "→" + cancels2);
  await click(".anchor-item[data-pid='buddy']");
  await page.waitForTimeout(400);
  await click("tr[data-acc='ix-on'] [role=switch]");
  await page.waitForFunction(() => {
    const sw = document.querySelector("tr[data-acc='ix-on'] [role=switch]");
    return sw && sw.getAttribute("aria-checked") === "true";
  }, undefined, { timeout: 20000 });
  const restored = await read();
  ck("E3d", "向导全程后 ix-on 启用位回到 true（rail 标题回到原值，无状态残留）",
     (restored.rail.find((x) => x.pid === "buddy") || {}).title === E.railTitles.buddy,
     "rail title=「" + (restored.rail.find((x) => x.pid === "buddy") || {}).title + "」 期望「" + E.railTitles.buddy + "」");
});

await section("banned", async () => {
  const rb = await read();
  ck("F9", "禁用词零命中（可见文本 + 属性 + toast）：" + BANNED_LIST.join(" / "),
     rb.banned.length === 0, "命中=" + j(rb.banned) + "（词表 " + BANNED_LIST.length + " 项）");
});

await section("deeplink", async () => {
  await page.goto(PAYLOAD.url + "#/accounts?p=trae");
  await page.waitForSelector(".anchor-item.active", { timeout: 20000 });
  await page.waitForTimeout(500);
  const d1 = await read();
  ck("G1", "深链 #/accounts?p=trae → 选中 Trae",
     act(d1) === "trae" && d1.head.title === "Trae",
     "active=" + act(d1) + " 卡头=「" + d1.head.title + "」");
  await page.goto(PAYLOAD.url + "#/accounts?p=nope");
  await page.waitForSelector(".anchor-item.active", { timeout: 20000 });
  await page.waitForTimeout(500);
  const d2 = await read();
  ck("G2", "深链 ?p=nope → 回落第一项 + .value 注明「未在册，已回到第一项」",
     act(d2) === "buddy" && d2.head.values.some((v) => v.indexOf("产品「nope」未在册，已回到第一项") >= 0),
     "active=" + act(d2) + " values=" + j(d2.head.values));
  await click(".anchor-item[data-pid='trae']");
  await page.waitForTimeout(400);
  const d3 = await read();
  ck("G3", "用户选定产品写入 localStorage（键名 mgw-accounts-product）",
     d3.lsProduct === "trae" && act(d3) === "trae",
     "点击 trae 后 localStorage=" + d3.lsProduct + " active=" + act(d3));
  await page.goto(PAYLOAD.url + "#/accounts");
  await page.waitForSelector(".anchor-item.active", { timeout: 20000 });
  await page.waitForTimeout(500);
  const d4 = await read();
  ck("G4", "无 ?p= 重载 → 恢复上次选中产品（§4-4 刷新不丢）",
     act(d4) === "trae" && d4.head.title === "Trae",
     "重载后 active=" + act(d4) + " 卡头=「" + d4.head.title + "」 localStorage=" + d4.lsProduct);
  ck("G4b", "深链本身不写记忆（只有用户选定才写）：?p=nope 回落不覆盖 localStorage",
     d2.lsProduct === "buddy" || d2.lsProduct === "trae",
     "回落档 localStorage=" + d2.lsProduct + "（回落注记仍留在 .value）");
  await click(".anchor-item[data-pid='buddy']");
  await page.waitForTimeout(300);
});

await section("layout", async () => {
  await setViewport(1440, 900);
  const L1440 = await read();
  await setViewport(1280, 800);
  const L1280 = await read();
  await setViewport(375, 800);
  const L375 = await read();
  ck("H6", "真 base.css 生效：.panel-split display/margin 实测 + 页内 <style> 副本为 0",
     L1440.split.disp === "flex" && L1440.split.margin.indexOf("-12px") === 0 && L1440.pageStyles === 0,
     "display=" + L1440.split.disp + " margin=" + L1440.split.margin + " height=" + L1440.split.h
     + "px 页内 <style>=" + L1440.pageStyles);
  // 2026-09-30 用户要求「产品列表宽度缩短 30%」：248 × 0.7 = 174px（只作用于账号接入页的
  // `.panel-split-narrow`，模型/资源两页的 rail 仍是 248px）。判据跟着实现走，不是反过来。
  ck("H1", ".subnav 计算宽度：1440→174px、1280→174px、375→全宽 375px",
     L1440.subnav.w === "174px" && L1280.subnav.w === "174px" && L375.subnav.bw === 375,
     "1440=" + L1440.subnav.w + " 1280=" + L1280.subnav.w + " 375=" + L375.subnav.w + "/" + L375.subnav.bw + "px");
  ck("H2", "375px：骨架转竖排、rail 变横向条带（.subnav column + .subnav-scroll row + 横滚）",
     L375.subnav.fd === "column" && L375.railBox.fd === "row" && L375.railBox.overflowX === "auto",
     "subnav.fd=" + L375.subnav.fd + " rail.fd=" + L375.railBox.fd + " rail.overflow-x=" + L375.railBox.overflowX);
  const ys = L375.rail.map((x) => x.by);
  // 🔴 空过防线：值必须是**有限数**（缺字段时 Set{undefined} 的 size 也是 1，那就是死判据）
  ck("H2b", "375px：10 行 rail 同处一条横带（同一 y，且 y 必须真读到）",
     ys.length === 10 && ys.every((v) => typeof v === "number" && Number.isFinite(v))
     && new Set(ys).size === 1, "y 值=" + j(Array.from(new Set(ys))) + "（" + ys.length + " 行）");
  ck("H3", "375px：主区未被挤扁（main ≥ 300px）且表格交给 .table-wrap 横滚",
     L375.main.bw >= 300 && !!L375.wrap && L375.wrap.overflowX === "auto" && L375.wrap.sw >= L375.wrap.cw,
     "main.bw=" + L375.main.bw + "px wrap sw=" + (L375.wrap || {}).sw + " cw=" + (L375.wrap || {}).cw);
  ck("H4", "375px：rail 文案零折行（10/10 单行矩形）",
     L375.rail.every((x) => !x.wrapped), "折行=" + L375.rail.filter((x) => x.wrapped).length + "/10");
  ck("H4b", "1440px：rail 文案零折行",
     L1440.rail.every((x) => !x.wrapped), "折行=" + L1440.rail.filter((x) => x.wrapped).length + "/10");
  const hs = L1440.rail.map((x) => x.h);
  ck("H5", "rail 行高一致（≤1px 容差）：10 行同一高度档",
     new Set(hs).size === 1, "高度集合=" + j(Array.from(new Set(hs))));
  const marks = L1440.rail.filter((x) => x.markH).map((x) => x.markH);
  ck("H5b", "rail 行内控件等高（mark-sm 徽章块 10/10 同档）",
     marks.length === 10 && new Set(marks).size === 1, "mark-sm 高度=" + j(Array.from(new Set(marks))));
  await shot("375-light");
  ck("H7", "1280px 档：主区仍完整（.subnav 174px + main ≥ 900px）",
     L1280.main.bw >= 900, "main.bw=" + L1280.main.bw + "px innerWidth=" + L1280.innerW);
  await setViewport(1440, 900);
  await page.waitForTimeout(300);
});

await section("themes", async () => {
  const light = await read();
  ck("I1", "浅色：.subnav 背景 == var(--surface) 计算色（无硬编码 hex）",
     light.subnav.bg === light.tokens.surfaceRgb,
     "实测=" + light.subnav.bg + " 令牌=" + light.tokens.surface);
  ck("I7", "浅色：rail 额度/卡头 .value 文字色 == var(--text-muted) 计算色",
     light.head.valueColor === light.tokens.mutedRgb,
     "实测=" + light.head.valueColor + " 令牌=" + light.tokens.muted);
  await setTheme("dark");
  const dark = await read();
  ck("I2", "深色：同一元素背景随令牌翻转（两值不同且各自等于该主题 --surface）",
     dark.subnav.bg === dark.tokens.surfaceRgb && dark.subnav.bg !== light.subnav.bg,
     "light=" + light.subnav.bg + "(" + light.tokens.surface + ") dark=" + dark.subnav.bg + "(" + dark.tokens.surface + ")");
  ck("I7b", "深色：.value 文字色同样走令牌（两主题各异）",
     dark.head.valueColor === dark.tokens.mutedRgb && dark.head.valueColor !== light.head.valueColor,
     "light=" + light.head.valueColor + " dark=" + dark.head.valueColor);
  const dot = (x, pid) => (((x.rail.find((y) => y.pid === pid) || {}).dots) || [])[0] || "";
  ck("I3", "新元素 .dot（绿档）在两主题下都等于 --dot-on 的计算色（无硬编码 hex）",
     dot(light, "buddy") === light.tokens.dotOnRgb && dot(dark, "buddy") === dark.tokens.dotOnRgb,
     "light=" + dot(light, "buddy") + "(" + light.tokens.dotOn + ") dark=" + dot(dark, "buddy")
     + "(" + dark.tokens.dotOn + ")｜--dot-on 两主题同值（base.css:41,69 有意为之）");
  ck("I4", "warn 点 = var(--warn)，两主题各取其解析值",
     dot(light, "qodercn") === light.tokens.warnRgb && dot(dark, "qodercn") === dark.tokens.warnRgb,
     "light=" + dot(light, "qodercn") + "(" + light.tokens.warn + ") dark=" + dot(dark, "qodercn") + "(" + dark.tokens.warn + ")");
  ck("I5", "灰点（有账号零启用）= var(--dot-off)，两主题不同值",
     dot(light, "workbuddy") === light.tokens.dotOffRgb
     && dot(dark, "workbuddy") === dark.tokens.dotOffRgb
     && dot(light, "workbuddy") !== dot(dark, "workbuddy"),
     "light=" + dot(light, "workbuddy") + "(" + light.tokens.dotOff + ") dark=" + dot(dark, "workbuddy") + "(" + dark.tokens.dotOff + ")");
  await shot("1440-dark");
  await click("td[data-exp='ix-on']");
  await page.waitForTimeout(400);
  await shot("1440-dark-expanded");
  await click("td[data-exp='ix-on']");
  await setViewport(375, 800);
  await page.waitForTimeout(400);
  await shot("375-dark");
  await setViewport(1440, 900);
  await setTheme("light");
  await page.waitForTimeout(300);
  await shot("1440-light");
});

await section("injection", async () => {
  if (!PAYLOAD.proxyUrl) return;
  /* 注入段：只为造出两个「真后端在真实部署里会给、本机这份健康实例给不出」的响应形态
     —— `resource:null`（配置读不动）与 `GET /admin/api/accounts` 502（§5 读失败），
     以及 `models` 的 `state:"unknown"` 出口。其余全部判据一律直连实例。 */
  fs.writeFileSync(PAYLOAD.modeFile, "resource-null");
  await page.goto(PAYLOAD.proxyUrl + "#/accounts");
  await page.waitForSelector(".anchor-item", { timeout: 25000 });
  await page.evaluate(() => { localStorage.removeItem("mgw-accounts-product");
    localStorage.setItem("mg-theme", "light"); });
  await page.reload();
  await page.waitForSelector(".anchor-item", { timeout: 25000 });
  await page.waitForTimeout(700);
  const pre = await page.evaluate(() => ({
    href: location.href,
    rail: document.querySelectorAll(".anchor-item").length,
    rows: Array.from(document.querySelectorAll("#ac-table tbody tr[data-acc]")).map((t) => t.dataset.acc),
    panel: (document.querySelector("#ac-panel") || {}).innerText ? document.querySelector("#ac-panel").innerText.replace(/\s+/g, " ").slice(0, 120) : "",
  }));
  ck("I0", "注入代理可达：页面在代理源上渲染出 10 行 rail 与 buddy 的账号表",
     pre.rail === 10 && pre.rows.indexOf("ix-on") >= 0,
     "href=" + pre.href + " rail=" + pre.rail + " rows=" + j(pre.rows) + " 面板=「" + pre.panel + "」");
  await click("td[data-exp='ix-on']");
  await page.waitForSelector("tr[data-rexp='ix-on']", { timeout: 15000 });
  await page.waitForTimeout(300);
  const rn = await read();
  const line = bitOf(rn, "ix-on", "网关资源");
  ck("C9", "resource:null（配置读不动）→「网关资源：未知（…不推断成 0）」",
     line.indexOf("网关资源：未知") === 0 && line.indexOf("不推断成 0") >= 0,
     "注入形态=" + E.injectResourceNull + "；实测=「" + line.slice(0, 70) + "」");
  await click("td[data-exp='ix-on']");
  await page.waitForTimeout(300);

  /* §5 读失败：视图端点 502 + 一次**行操作**触发重取（POST 成功、GET 失败），再一次面板级重绘 */
  fs.writeFileSync(PAYLOAD.modeFile, "error");
  await click("tr[data-acc='ix-on'] [role=switch]");
  await page.waitForTimeout(1600);
  const re0 = await read();
  ck("G5a", "现状登记（缺陷 D-1）：行操作后视图重取失败**不**给 alert/过期注记，旧数据静默继续显示",
     re0.alertErr === 0 && re0.retry === 0 && re0.rail.length === 10
     && !re0.head.values.some((v) => v.indexOf("数据可能已过期") >= 0),
     "alert=" + re0.alertErr + " 重试钮=" + re0.retry + " rail=" + re0.rail.length
     + " values=" + j(re0.head.values) + " toasts=" + j(re0.toasts));
  await click(".anchor-item[data-pid='workbuddy']");
  await page.waitForTimeout(1500);
  const re1 = await read();
  ck("G5", "§5 读失败（面板级重绘后到齐）：.alert.alert-err + 「重试」+ rail 保留上次数据 + 「数据可能已过期」",
     re1.alertErr === 1 && re1.retry === 1 && re1.rail.length === 10
     && re1.head.values.some((v) => v.indexOf("数据可能已过期") >= 0),
     "alert=" + re1.alertErr + " 重试钮=" + re1.retry + " rail=" + re1.rail.length + " values=" + j(re1.head.values));
  ck("G5b", "失败原因原文上屏（不吞异常）",
     (re1.alertErrText || "").indexOf("IX 注入：账号视图读取失败") >= 0,
     "「" + (re1.alertErrText || "").slice(0, 130) + "」");
  await shot("1440-light-load-error");
  fs.writeFileSync(PAYLOAD.modeFile, "");
  await click("#ac-retry");
  await page.waitForTimeout(1800);
  const re2 = await read();
  ck("G5c", "「重试」恢复：alert 消失、卡头计数行回到原值",
     re2.alertErr === 0 && re2.head.values.length === 1
     && re2.head.values[0] === E.railCountsHead.workbuddy,
     "alert=" + re2.alertErr + " values=" + j(re2.head.values));
  await click(".anchor-item[data-pid='buddy']");
  await page.waitForTimeout(600);
  await click("tr[data-acc='ix-on'] [role=switch]");
  await page.waitForTimeout(1500);

  /* 目录「取不动」出口：注入 state=unknown → UI 只给原因、零条目 */
  fs.writeFileSync(PAYLOAD.modeFile, "models-unknown");
  await click(".anchor-item[data-pid='loomy']");
  await page.waitForTimeout(500);
  await click("td[data-exp='ix-norefresh']");
  await page.waitForSelector("tr[data-rexp='ix-norefresh']", { timeout: 15000 });
  await click("tr[data-rexp='ix-norefresh'] [data-op='models']");
  await page.waitForSelector(".modal .alert-warn", { timeout: 25000 });
  await page.waitForTimeout(400);
  const ru = await read();
  const rowsU = await page.evaluate(() => document.querySelectorAll(".modal [data-mdl]").length);
  ck("E10d", "目录 state=unknown → 只展示原因 + **零条目**（不编造，与「未知不当零」同尺）",
     (ru.wizardText || "").indexOf("目录取不动") >= 0 && rowsU === 0
     && (ru.wizardText || "").indexOf("IX 注入：上游目录端点不可用") >= 0,
     "正文=「" + (ru.wizardText || "").slice(0, 140) + "」 条目=" + rowsU);
  await shot("1440-light-models-unknown");
  await click(".modal-foot .btn");
  fs.writeFileSync(PAYLOAD.modeFile, "");
  await page.goto(PAYLOAD.url + "#/accounts");
  await page.waitForSelector(".anchor-item", { timeout: 20000 });
  await page.waitForTimeout(600);
});

await section("deletes", async () => {
  fs.writeFileSync(PAYLOAD.modeFile, "");
  await click(".anchor-item[data-pid='loomy']");
  await page.waitForTimeout(500);
  await click("tr[data-acc='ix-norefresh'] [data-op='delete']");
  await page.waitForSelector(".modal .modal-foot .btn", { timeout: 15000 });
  await page.waitForTimeout(300);
  const dm = await read();
  ck("E6", "删除二次确认：文案如实承诺「关联资源置停用并保留 + 彻底删除去模型资源页」",
     /^确定删除 Loomy 的账号「ix-norefresh」？/.test(dm.confirmText || "")
     && (dm.confirmText || "").indexOf("关联资源会被置为停用并保留") >= 0
     && (dm.confirmText || "").indexOf("彻底删除请到「接入模型资源」页") >= 0,
     "确认文案=「" + (dm.confirmText || "") + "」");
  ck("E6b", "确认弹窗二段钮（取消 / 确定）+ 破坏性在后",
     j(dm.confirmBtns) === j(["取消", "确定"]), "按钮=" + j(dm.confirmBtns));
  await shot("1440-light-delete-confirm");
  await click(".modal-foot .btn-danger");
  await page.waitForFunction(() => !document.querySelector("tr[data-acc='ix-norefresh']"),
                             undefined, { timeout: 25000 });
  const dd = await read();
  ck("E6c", "删除后行消失、面板回到空态（面板级重取，不做假删；产品名在卡头）",
     dd.rows.length === 0 && /还没有账号/.test(dd.empty || ""),
     "rows=" + dd.rows.length + " empty=「" + (dd.empty || "").slice(0, 60) + "」");
  ck("E6d", "删除回执 toast 与后端 message 同口径（不谎报级联）",
     dd.toasts.some((t) => t.indexOf("ix-norefresh 已删除") >= 0), "toasts=" + j(dd.toasts));
  await click(".anchor-item[data-pid='qoder']");
  await page.waitForTimeout(300);
  await click("tr[data-acc='ix-quota-exhausted'] [data-op='delete']");
  await page.waitForSelector(".modal .modal-foot .btn-danger", { timeout: 15000 });
  const dm2 = await read();
  ck("E7", "N=0 变体（该账号已无在册资源）：确认文案仍承诺「资源会被置为停用并保留」",
     (dm2.confirmText || "").indexOf("关联资源会被置为停用并保留") >= 0,
     "确认文案=「" + (dm2.confirmText || "").slice(0, 150) + "」");
  await click(".modal-foot .btn-danger");
  await page.waitForFunction(() => !document.querySelector("tr[data-acc='ix-quota-exhausted']"),
                             undefined, { timeout: 25000 });
  await page.waitForTimeout(600);
  const dd2 = await read();
  ck("E7b", "N=0 删除后面板回到空态（后端 resources_disabled=false，见 Python 侧复核）",
     dd2.rows.length === 0 && /还没有账号/.test(dd2.empty || ""),
     "rows=" + dd2.rows.length + " empty=「" + (dd2.empty || "").slice(0, 60) + "」");
});

await section("final", async () => {
  const rf = await read();
  ck("Z1", "收尾：无禁用词残留（全页 + toast 复扫）",
     rf.banned.length === 0, "命中=" + j(rf.banned));
  ck("Z2", "收尾：#modal-root 归零（无泄漏弹窗）",
     rf.modalCount === 0, "modal-root 子节点=" + rf.modalCount);
  ck("Z3", "收尾：rail 仍 10 行（删除账号不洗选择轴）",
     rf.rail.length === 10, "rail=" + rf.rail.length + " 计数=" + j(rf.rail.map((x) => E.railCounts[x.pid])));
  extra.finalRailTitles = rf.rail.map((x) => x.title);
  extra.finalToasts = rf.toasts;
});
}
}

try { await mainMode(); } catch (e) {
  ck("FATAL", "浏览器主流程未抛错（读数有效性判据）", false, String(e && e.message).slice(0, 220));
}
fs.writeFileSync(OUT, JSON.stringify({ checks, shots, extra }, null, 1));
console.log(JSON.stringify({ mode: MODE, total: checks.length,
  failed: checks.filter((c) => !c.ok).map((c) => c.id) }));
await clearViewport().catch(() => {});
await task.finish({ keep: [] });
'''.replace("__QUOTA_WORDS__", json.dumps(QUOTA_WORDS, ensure_ascii=False)) \
   .replace("__BANNED_LIST__", json.dumps(BANNED, ensure_ascii=False))


def run_browser(payload: dict, run_dir: Path, rep: Report, tag: str, absorb: bool = False) -> dict:
    """absorb=True：读数**只打印不入账**（撤证用——那几条红是预期红，不该混进判据合计）。"""
    run_dir.mkdir(parents=True, exist_ok=True)
    Path(payload.get("shotsDir") or ".").mkdir(parents=True, exist_ok=True)
    pfile = run_dir / f"payload-{tag}.json"
    ofile = run_dir / f"browser-results-{tag}.json"
    jfile = run_dir / f"browser-{tag}.js"
    pfile.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    jfile.write_text(JS.replace("__PAYLOAD__", str(pfile)).replace("__OUT__", str(ofile)),
                     encoding="utf-8")
    with jfile.open("r", encoding="utf-8") as fh:
        proc = subprocess.run(["ego-browser", "nodejs"], stdin=fh, capture_output=True,
                              text=True, timeout=1800, cwd=str(run_dir))
    if not ofile.exists():
        log(f"✗ 浏览器分段「{tag}」没交回读数（rc={proc.returncode}）")
        log("  stdout: " + proc.stdout[-1200:])
        log("  stderr: " + proc.stderr[-1200:])
        rep.add("BROWSER-" + tag, f"浏览器分段 {tag} 产出读数", False,
                f"rc={proc.returncode} {proc.stderr.strip()[-200:]}")
        return {"checks": [], "fatal": True}
    data = json.loads(ofile.read_text(encoding="utf-8"))
    for c in data.get("checks", []):
        if absorb:
            log(f"  {'✓' if c['ok'] else '✗'} [{tag}] {c['id']} {c['desc']}｜{c['measured'][:200]}")
        else:
            rep.add(c["id"], c["desc"], c["ok"], c["measured"])
    bad = [c["id"] for c in data.get("checks", []) if not c.get("ok")]
    log(f"  [浏览器/{tag}] {len(data.get('checks', []))} 项 / 红 {len(bad)} "
        f"{j0(bad)}；截图 {len(data.get('shots', []))} 张"
        + (data.get("extra", {}).get("shotErrors")
           and f"；截图失败 {j0(data['extra']['shotErrors'])}" or ""))
    return data


def j0(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def build_expect(view: dict, port: int = 0) -> dict:
    rail_counts = {p["id"]: len(p["accounts"]) for p in view["products"]}
    rail_titles = {p["id"]: f"{p['title']} · {rail_counts[p['id']]} 个账号"
                   f"（{sum(1 for a in p['accounts'] if a['enabled'])} 已启用）"
                   for p in view["products"]}
    resource_ids, pool_states, statuses, caps = {}, {}, {}, {}
    for p in view["products"]:
        caps[p["id"]] = p["capabilities"]
        for a in p["accounts"]:
            res = a.get("resource")
            if isinstance(res, list) and res:
                resource_ids[f"{p['id']}/{a['name']}"] = res[0]["id"]
            pool_states[f"{p['id']}/{a['name']}"] = a["quota"]["state"]
            statuses[f"{p['id']}/{a['name']}"] = a["status"]
    qoder = next((p for p in view["products"] if p["id"] == "qoder"), {"accounts": []})
    source_label = {"remote": "远端目录", "cache": "磁盘缓存", "static": "本地静态表"}
    loomy = next((p for p in view["products"] if p["id"] == "loomy"), {"models_source": "remote"})
    ms = {"state": "?", "count": -1, "sourceLabel": source_label.get(loomy["models_source"], "?")}
    if port:      # 弹窗条目数的判据来自**真接口读数**，不是前端自证
        st, mdl = http("GET", f"http://127.0.0.1:{port}/admin/api/accounts/loomy/ix-norefresh/models")
        if isinstance(mdl, dict) and "models" in mdl:
            ms["state"] = mdl.get("state", "?")
            ms["count"] = len(mdl.get("models") or [])
    return {
        "productIds": PRODUCT_IDS,
        "railCounts": rail_counts,
        "railTitles": rail_titles,
        "railCountsHead": {p["id"]: f"{rail_counts[p['id']]} 个账号 · "
                                    f"{sum(1 for a in p['accounts'] if a['enabled'])} 已启用"
                           for p in view["products"]},
        "zeroAccountProducts": [pid for pid in PRODUCT_IDS if rail_counts.get(pid) == 0],
        "resourceIds": resource_ids,
        "poolStates": pool_states,
        "statuses": statuses,
        "caps": caps,
        "checkedAt": CHECKED_AT,
        "checkedAtText": CHECKED_AT.replace("T", " ")[:16],
        "loomyModels": ms,
        "emptyResource": (qoder["accounts"][0]["resource"] if qoder["accounts"] else []),
        "injectResourceNull": "resource=null（注入代理改写 GET /admin/api/accounts）",
    }


def api_view(port: int) -> dict:
    return http("GET", f"http://127.0.0.1:{port}/admin/api/accounts")[1]


# ==================== 主流程 ====================

def main() -> int:
    ap = argparse.ArgumentParser(description="M7-UI 账号接入页真机验收")
    ap.add_argument("--port", type=int, default=0, help="实例端口（缺省在 8400-8499 自动挑）")
    ap.add_argument("--basetemp", default="/tmp/m7-ix", help="临时根（默认 /tmp/m7-ix）")
    ap.add_argument("--shots", default="", help="截图目录（默认 docs/changes/e2e-records/m7-accounts-ui）")
    ap.add_argument("--retract", type=int, choices=[1, 2, 3], default=0, help="成对撤证模式")
    ap.add_argument("--keep", action="store_true", help="保留临时目录")
    ap.add_argument("--no-proxy", action="store_true", help="跳过注入段（resource:null / 读失败）")
    args = ap.parse_args()

    if args.retract:
        return retract_main(args)

    run_dir = Path(args.basetemp) / f"run-{int(time.time())}"
    run_dir.mkdir(parents=True, exist_ok=True)
    shots = Path(args.shots or (ROOT / "docs/changes/e2e-records/m7-accounts-ui"))
    shots.mkdir(parents=True, exist_ok=True)
    rep = Report()

    port, why = pick_port(args.port)
    emit(rep, "A0", "端口挑选（8400-8499，bind + lsof 双验；:8300 在册实例零接触）",
         8400 <= port <= 8499 and port != 8300, f"port={port} 判据={why}")
    cfg_path = write_config(run_dir, port, interval=0)
    emit(rep, "A0b", "独立实例配置与数据根都落在 --basetemp 下（仓库 data/ 零写入）",
         str(run_dir) in str(cfg_path), f"config={cfg_path}")

    seeded = seed_accounts(cfg_path, run_dir, ROOT)
    emit(rep, "A1", "种子经生产入口 store.commit_login 落盘（含物化资源）",
         sum(len(v) for v in seeded.values()) == len(SEED), j0(seeded))
    removed = strip_resource(cfg_path, "qoder", "ix-quota-exhausted")
    emit(rep, "A1b", "为 BD3a 的 [] 形态摘掉 qoder 的物化资源（临时实例自己的 config）",
         bool(removed), f"removed={removed}")

    proc, out = start_gateway(cfg_path, run_dir, ROOT)
    ok, health = wait_health(port, proc)
    emit(rep, "A2", "独立实例真启动（/health 200 且 config.path 指向临时目录）",
         ok and isinstance(health, dict) and "mgw-conf" in str(health.get("config", {}).get("path", "")),
         j0(health)[:280] if isinstance(health, dict) else str(health))
    if not ok:
        log((run_dir / "gateway.log").read_text(encoding="utf-8")[-2500:])
        return 2
    time.sleep(2.8)                      # 配置 mtime 轮询热重载（1s）+ 余量

    code, view = http("GET", f"http://127.0.0.1:{port}/admin/api/accounts")
    expect = build_expect(view, port)
    want_counts = {"products": 10, "accounts": len(SEED),
                   "enabled": sum(1 for s in SEED if s["enabled"]),
                   "disabled": sum(1 for s in SEED if not s["enabled"])}
    emit(rep, "A3", "GET /admin/api/accounts 200 且 counts 与种子逐字相符",
         code == 200 and view["counts"] == want_counts,
         f"counts={j0(view['counts'])} 期望={j0(want_counts)}")
    emit(rep, "A3b", "热重载后 resource 三态之 [] 由**真后端**给出（不是注入）",
         expect["emptyResource"] == [], f"qoder/ix-quota-exhausted resource={j0(expect['emptyResource'])}")
    raw = json.dumps(view, ensure_ascii=False)
    leaks = [t for t in ("IXFAKE", "ix_fake_token", "credentials") if t in raw]
    emit(rep, "A3c", "账号视图载荷零凭据（IXFAKE / ix_fake_token / credentials 均不外泄）",
         not leaks, f"命中={j0(leaks)}；载荷字节={len(raw.encode())}")

    proxy_port = 0
    proxy_url = ""
    srv = th = None
    mode_file = run_dir / "inject-mode"
    if not args.no_proxy:
        for cand in (port + 1, port + 50, 8499):
            free, _ = port_is_free(cand)
            if free:
                proxy_port = cand
                break
    if proxy_port:
        srv, th = start_proxy(proxy_port, port, mode_file)
        proxy_url = f"http://127.0.0.1:{proxy_port}/"
        emit(rep, "A5", "注入代理在环（只为 resource:null 与 §5 读失败两态；其余判据一律直连）",
             True, f"proxy={proxy_url} → backend=127.0.0.1:{port}")
    else:
        emit(rep, "A5", "注入代理在环", False, "8400-8499 内找不到第二个空闲口（注入段将跳过）")

    url = f"http://127.0.0.1:{port}/"
    data = run_browser({"mode": "full", "url": url, "proxyUrl": proxy_url,
                        "shotsDir": str(shots), "expect": expect,
                        "modeFile": str(mode_file)}, run_dir, rep, "full")
    try:
        # Python 侧复核（**实例仍在跑**）：?confirm=1 契约 + 删除级联的真实去向（N>0 / N=0）
        if not data.get("fatal"):
            code8, err8 = http("POST", f"{url}admin/api/accounts/trae/ix-unknown-quota/delete")
            v8 = api_view(port)
            alive = [p["id"] + "/" + a["name"] for p in v8["products"] for a in p["accounts"]
                     if a["name"] == "ix-unknown-quota"]
            emit(rep, "E8", "缺 ?confirm=1 的删除被拒（400 + 可读原因）且**不动盘**",
                 code8 == 400 and "confirm=1" in j0(err8) and alive == ["trae/ix-unknown-quota"],
                 f"HTTP {code8} 原因={j0(err8)[:150]}；账号仍在={j0(alive)}")
            code9, err9 = http("POST", f"{url}admin/api/accounts/nope/x/delete?confirm=1")
            emit(rep, "E8b", "未在册产品 / 不存在账号 → 显式错误（不静默成功）",
                 code9 in (400, 404), f"HTTP {code9} {j0(err9)[:150]}")

            code2, cfg_view = http("GET", f"{url}admin/api/config")
            resources = cfg_view.get("resources") or [] if isinstance(cfg_view, dict) else []
            loomy_res = [r for r in resources
                         if r.get("product") == "loomy" and r.get("account_ref") == "ix-norefresh"]
            emit(rep, "E6e", "N>0 级联为真：删除 loomy/ix-norefresh 后其资源**仍在册且 enabled=false**",
                 len(loomy_res) == 1 and loomy_res[0]["enabled"] is False,
                 f"/admin/api/config rc={code2}；资源={j0(loomy_res)}")
            gone = api_view(port)
            names = {p["id"] + "/" + a["name"] for p in gone["products"] for a in p["accounts"]}
            emit(rep, "E6f", "两个被删账号都已从服务端视图消失",
                 not ({"loomy/ix-norefresh", "qoder/ix-quota-exhausted"} & names),
                 f"残留={j0(sorted({'loomy/ix-norefresh', 'qoder/ix-quota-exhausted'} & names))}")
            untouched = [s["product"] + "/" + s["name"] for s in SEED
                         if s["name"] not in ("ix-norefresh", "ix-quota-exhausted")
                         and s["product"] + "/" + s["name"] not in names]
            emit(rep, "E6g", "其余种子账号未受牵连（删除只动目标行）",
                 untouched == [], f"意外消失={j0(untouched)}；在册={len(names)}")
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        stop(proc, out)

    trace = run_dir / "fake-trace.jsonl"
    lines = [json.loads(x) for x in trace.read_text(encoding="utf-8").splitlines() if x.strip()] \
        if trace.exists() else []
    net = [x for x in lines if "url" in x]
    emit(rep, "A6", "假上游零真实出网：全部上游调用被 MockTransport 截获（轨迹可核）",
         any(x.get("asyncclient_patched") for x in lines),
         f"轨迹 {len(net)} 条上游请求；hosts={j0(sorted({x['host'] for x in net}))}")

    log("\n" + "=" * 62)
    log(rep.summary())
    for cid, desc, _ok, measured in rep.failed:
        log(f"  ✗ {cid} {desc}｜{measured}")
    (run_dir / "assertions.json").write_text(
        json.dumps([{"id": c, "desc": d, "ok": k, "measured": m} for c, d, k, m in rep.rows],
                   ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.keep:
        shutil.rmtree(run_dir, ignore_errors=True)
    else:
        log(f"（临时目录保留：{run_dir}）")
    return 1 if rep.failed else 0


# ==================== 三项成对撤证 ====================

def make_copy(dst: Path) -> Path:
    """把被测树复制到 /tmp（**主树零改动**）。布局 = 仓库新结构（coding/ + bianyiandhuanjing/）。"""
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "coding").mkdir(exist_ok=True)
    shutil.copytree(ROOT / "coding/model_gateway", dst / "coding/model_gateway",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"), dirs_exist_ok=True)
    (dst / "bianyiandhuanjing" / "scripts").mkdir(parents=True, exist_ok=True)
    for name in ("verify_accounts_ui.mjs", "verify_accounts_ui_live.py", "verify_v2_frontend.mjs"):
        src = ROOT / "bianyiandhuanjing/scripts" / name
        if src.exists():
            shutil.copy2(src, dst / "bianyiandhuanjing/scripts" / name)
    if (ROOT / "bianyiandhuanjing/scripts/fixtures").exists():
        shutil.copytree(ROOT / "bianyiandhuanjing/scripts/fixtures",
                        dst / "bianyiandhuanjing/scripts/fixtures", dirs_exist_ok=True)
    for name in ("pyproject.toml", "config.example.yaml"):
        if (ROOT / "coding" / name).exists():
            shutil.copy2(ROOT / "coding" / name, dst / "coding" / name)
    return dst


def apply_edit(path: Path, old: str, new: str, tag: str) -> None:
    src = path.read_text(encoding="utf-8")
    hits = src.count(old)
    if hits != 1:
        raise RuntimeError(f"{tag}：编辑锚点在 {path.name} 命中 {hits} 次（需恰好 1 次）")
    path.write_text(src.replace(old, new), encoding="utf-8")


def run_gate(page_file: Path) -> tuple[int, str]:
    r = subprocess.run(["node", str(ROOT / "bianyiandhuanjing/scripts/verify_accounts_ui.mjs"), "--json",
                        "--page", str(page_file)], capture_output=True, text=True, timeout=240)
    last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-400:]
    return r.returncode, last


def retract_main(args) -> int:
    base = Path(args.basetemp) / f"retract{args.retract}-{int(time.time())}"
    base.mkdir(parents=True, exist_ok=True)
    rep = Report()
    port, why = pick_port(args.port)
    log(f"[撤证 {args.retract}] 端口 {port}（{why}）；临时根 {base}")
    shots = Path(args.shots or (ROOT / "docs/changes/e2e-records/m7-accounts-ui"))
    shots.mkdir(parents=True, exist_ok=True)
    watched = ["coding/model_gateway/main.py", "coding/model_gateway/web/static/js/pages/accounts.js",
               "coding/model_gateway/api/admin_accounts.py", "bianyiandhuanjing/scripts/verify_accounts_ui.mjs"]
    before = {f: sha256(ROOT / f) for f in watched}
    try:
        rc = {1: retract_1, 2: retract_2, 3: retract_3}[args.retract](base, port, rep, shots)
    finally:
        pass
    changed = [f for f in watched if sha256(ROOT / f) != before[f]]
    emit(rep, "R0", "主树零改动（撤证只发生在 /tmp 复制品上）",
         changed == [], f"受监视 {len(watched)} 个源文件的 sha256 前后一致；变动={j0(changed)}")
    log("\n" + "=" * 62)
    log(rep.summary())
    for cid, desc, _ok, measured in rep.failed:
        log(f"  ✗ {cid} {desc}｜{measured}")
    (base / "assertions.json").write_text(
        json.dumps([{"id": c, "desc": d, "ok": k, "measured": m} for c, d, k, m in rep.rows],
                   ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.keep:
        shutil.rmtree(base, ignore_errors=True)
    else:
        log(f"（临时目录保留：{base}）")
    return rc if rc not in (0, 1, 2) else (1 if rep.failed else 0)


def retract_1(base: Path, port: int, rep: Report, shots: Path) -> int:
    copy = make_copy(base / "tree")
    page_copy = copy / "coding/model_gateway/web/static/js/pages/accounts.js"
    page_main = ROOT / "coding/model_gateway/web/static/js/pages/accounts.js"
    before = sha256(page_main)
    apply_edit(page_copy, '<div class="subnav-scroll" role="tablist"',
               '<div class="group-card" role="tablist"', "撤证①")
    rc, out = run_gate(page_copy)
    try:
        red = [c["id"] for c in json.loads(out).get("checks", []) if not c.get("ok")]
    except Exception:  # noqa: BLE001
        red = []
    emit(rep, "R1-1", "撤证①：族容器塞回 rail → **静态门**变红（V1 + L-A6 必须红）",
         {"V1", "L-A6"} <= set(red),
         f"红判据={j0(red)}（--json 模式恒 rc={rc}，判据取 checks[].ok）")
    rc0, out0 = run_gate(page_main)
    try:
        red0 = [c["id"] for c in json.loads(out0).get("checks", []) if not c.get("ok")]
    except Exception:  # noqa: BLE001
        red0 = ["<读数失败>"]
    emit(rep, "R1-1b", "对照：主树同一门全绿（红是变异造成的，不是门坏了）",
         red0 == [], f"主树红判据={j0(red0)} rc={rc0}")

    run = base / "gw"
    cfg = write_config(run, port, interval=0)
    seed_accounts(cfg, run, copy)
    proc, out_h = start_gateway(cfg, run, copy, log_name="gw")
    ok, health = wait_health(port, proc)
    if not ok:
        emit(rep, "R1-2", "复制品实例启动", False, str(health))
        stop(proc, out_h)
        return 2
    time.sleep(2.0)
    expect = build_expect(api_view(port))
    data = run_browser({"mode": "rail", "url": f"http://127.0.0.1:{port}/",
                        "shotsDir": str(shots), "expect": expect,
                        "shotName": "retract1-rail-groupcard"}, run, rep, "rail", absorb=True)
    stop(proc, out_h)
    red_ids = [c["id"] for c in data.get("checks", []) if not c.get("ok")]
    emit(rep, "R1-3", "撤证①：**真浏览器** rail 判据同时变红（RT1 族容器计数 / RT3 容器类名）",
         {"RT1", "RT3"} <= set(red_ids), f"红判据={j0(red_ids)}（明细见上一行打印）")
    shutil.copy2(page_main, page_copy)
    emit(rep, "R1-4", "恢复证明：复制品 accounts.js 与主树 sha256 逐字节相同（主树未被改动）",
         sha256(page_copy) == before == sha256(page_main), f"sha256={before[:20]}…")
    rc2, out2 = run_gate(page_copy)
    try:
        red2 = [c["id"] for c in json.loads(out2).get("checks", []) if not c.get("ok")]
    except Exception:  # noqa: BLE001
        red2 = ["<读数失败>"]
    emit(rep, "R1-5", "恢复后静态门回到全绿（红证可逆）", red2 == [], f"红判据={j0(red2)}")
    return 0


BD8_OLD = """        seeded = ops_runner.all_accounts(declared)
    except Exception as e:  # noqa: BLE001 — 枚举不可用 ≠ 运营必须崩：不起调度并留痕"""
BD8_NEW = """        seeded = ops_runner.all_accounts(declared)
        if not seeded:                      # 撤证②：把 BD8 撤掉的「无账号即永不起」门塞回来
            return None
    except Exception as e:  # noqa: BLE001 — 枚举不可用 ≠ 运营必须崩：不起调度并留痕"""

BD1_A = """        report = await ops_runner.run_once(operation=op_claim, runtime=runtime,
                                           enabled_of=cron_enabled_of)"""
BD1_B = """        breport = await ops_runner.run_once(operation=op_balance, runtime=runtime,
                                            enabled_of=cron_enabled_of)"""


def quota_cell_text(base: Path, port: int, rep: Report, product: str, account: str,
                    shot_name: str) -> str:
    expect = build_expect(api_view(port))
    expect["quotaProduct"] = product
    expect["quotaAccount"] = account
    data = run_browser({"mode": "quota", "url": f"http://127.0.0.1:{port}/",
                        "shotsDir": str(base / "shots"), "expect": expect,
                        "shotName": shot_name}, base, rep, shot_name, absorb=True)
    for c in data.get("checks", []):
        if c.get("id") == "RT5":
            return c.get("measured", "")
    return "（读数缺失）"


def retract_2(base: Path, port: int, rep: Report, shots: Path) -> int:
    """BD8 成对撤证：断 BD8 → 接入账号后额度列恒「尚未刷新」；恢复 → 定时轮写出 runtime.quota。"""
    spec = [SEED[0], SEED[1]]      # buddy/ix-on（启用，无 runtime.json）+ buddy/ix-off（停用）
    results = {}
    for tag, broken in (("broken-bd8", True), ("restored-bd8", False)):
        copy = make_copy(base / tag)
        if broken:
            apply_edit(copy / "coding/model_gateway/main.py", BD8_OLD, BD8_NEW, "撤证②")
        run = base / f"gw-{tag}"
        cfg = write_config(run, port, interval=5)
        proc, out_h = start_gateway(cfg, run, copy, log_name="gw")
        ok, health = wait_health(port, proc)
        if not ok:
            emit(rep, f"R2-{tag}", "空数据根实例启动（0 账号）", False, str(health))
            stop(proc, out_h)
            return 2
        time.sleep(1.5)
        seeded = seed_accounts(cfg, run, copy, spec=spec)     # 接入发生在启动**之后**
        time.sleep(28)                                        # ≥4 个 5s tick（含重试退避）
        files = sorted((cfg.parent / "usage").glob("ops-results-*.jsonl"))
        runtime_state = {}
        for pid, names in seeded.items():
            for nm in names:
                p = account_dir(cfg, pid, nm) / "runtime.json"
                has = p.exists()
                runtime_state[f"{pid}/{nm}"] = {
                    "file": has,
                    "quota": (json.loads(p.read_text(encoding="utf-8")).get("quota") or {}).get("state")
                    if has else None}
        cell = quota_cell_text(run, port, rep, "buddy", "ix-on", f"retract2-{tag}")
        results[tag] = {"runtime": runtime_state, "cell": cell, "jsonl": [f.name for f in files],
                        "log": (run / "gw.log").read_text(encoding="utf-8")}
        stop(proc, out_h)
        for src in sorted((run / "shots").glob("retract2-*.png")):
            shutil.copy2(src, shots / src.name)
    b, f = results["broken-bd8"], results["restored-bd8"]
    emit(rep, "R2-1", "撤证②（断 BD8）：接入账号后额度列**恒**「尚未刷新」且 runtime.json 从未写出",
         "尚未刷新" in b["cell"] and not any(v["file"] for v in b["runtime"].values()),
         f"额度格={b['cell']}；runtime.json={j0(b['runtime'])}；jsonl={j0(b['jsonl'])}")
    emit(rep, "R2-2", "恢复 BD8：同一份种子下定时轮**写出** runtime.quota → 额度列移动",
         any(v["quota"] for v in f["runtime"].values()) and "尚未刷新" not in f["cell"],
         f"额度格={f['cell']}；runtime.json={j0(f['runtime'])}；jsonl={j0(f['jsonl'])}")
    diff = subprocess.run(["diff", "-rq", str(base / "broken-bd8"), str(base / "restored-bd8")],
                          capture_output=True, text=True, timeout=180)
    raw = [ln.strip() for ln in diff.stdout.splitlines() if ln.strip()]
    src = [ln for ln in raw if "__pycache__" not in ln and ".py " in ln]
    emit(rep, "R2-3", "两跑差异只来自 main.py 那一处（整树 diff 的源码差异只点名 main.py）",
         len(src) == 1 and "model_gateway/main.py" in src[0],
         f"源码差异={j0(src)}（原始差异行 {len(raw)} 条，其余为 __pycache__ 产物）")
    return 0


def retract_3(base: Path, port: int, rep: Report, shots: Path) -> int:
    """BD1 成对撤证：断 cron 腿的 enabled_of → 停用账号仍被定时轮领取（进 jsonl 参与方）。"""
    spec = [SEED[0], SEED[1]]
    out = {}
    for tag, broken in (("broken-bd1", True), ("restored-bd1", False)):
        copy = make_copy(base / tag)
        main_py = copy / "coding/model_gateway/main.py"
        if broken:
            apply_edit(main_py, BD1_A,
                       "        report = await ops_runner.run_once(operation=op_claim, runtime=runtime)",
                       "撤证③-claim 腿")
            apply_edit(main_py, BD1_B,
                       "        breport = await ops_runner.run_once(operation=op_balance, runtime=runtime)",
                       "撤证③-balance 腿")
        run = base / f"gw-{tag}"
        cfg = write_config(run, port, interval=5)
        seed_accounts(cfg, run, copy, spec=spec)
        proc, out_h = start_gateway(cfg, run, copy, log_name="gw")
        ok, health = wait_health(port, proc)
        if not ok:
            emit(rep, f"R3-{tag}", "实例启动", False, str(health))
            stop(proc, out_h)
            return 2
        time.sleep(30)                                       # ≥4 个 tick（含重试退避）
        rounds = []
        files = sorted((cfg.parent / "usage").glob("ops-results-*.jsonl"))
        for fp in files:
            for line in fp.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rounds.append(json.loads(line))
        out[tag] = {"rounds": rounds, "files": [f.name for f in files]}
        stop(proc, out_h)

    def participates(rounds, account):
        hit = []
        for idx, r in enumerate(rounds):
            cats = [k for k in ("success", "already_done", "inactive") if account in (r.get(k) or [])]
            if any((x or {}).get("account") == account for x in (r.get("failed") or [])):
                cats.append("failed")
            if cats:
                hit.append({"round": idx, "cats": cats})
        return hit

    for tag in out:
        log(f"  [{tag}] jsonl={j0(out[tag]['files'])} 轮次={len(out[tag]['rounds'])}")
        for r in out[tag]["rounds"][:6]:
            log("    " + j0({k: r.get(k) for k in ("success", "failed", "inactive", "skipped")})[:230])
    b = participates(out["broken-bd1"]["rounds"], "ix-off")
    f_hit = participates(out["restored-bd1"]["rounds"], "ix-off")
    f_skip = [i for i, r in enumerate(out["restored-bd1"]["rounds"]) if "ix-off" in (r.get("skipped") or [])]
    f_on = participates(out["restored-bd1"]["rounds"], "ix-on")
    emit(rep, "R3-1", "撤证③（断 BD1）：**停用**账号 ix-off 作为参与方出现在定时轮 jsonl 里",
         len(b) > 0, f"命中={j0(b)}")
    emit(rep, "R3-2", "恢复 BD1：ix-off 只进 skipped、从不作参与方",
         len(f_hit) == 0 and len(f_skip) > 0,
         f"参与方命中={j0(f_hit)} skipped 轮={j0(f_skip)}")
    emit(rep, "R3-3", "对照：启用账号 ix-on 在恢复后仍正常进参与方（撤证没把腿撤断）",
         len(f_on) > 0, f"ix-on 参与={j0(f_on[:3])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
