#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机只读探针：总览页「账号资源额度」板块（2026-10-07 用户指令）。

为什么起**隔离实例**而不是打 :8300：本轮含后端改动（`/admin/api/overview` 新增
`accounts_quota`），而 :8300 未重启前线上没有这条腿 ⇒ 在它上面只能验"板块缺席"这一种
回落形状，验不到卡片到底画成什么样。重启要用户点头，所以按本仓既有做法
（`serve_param_instance.py` 那一型）起一台自己的实例。

🔴 零真实凭据、零出站：数据根在 `--dir`（默认 `/tmp/mgw-aq-instance`），`MG_CONFIG` 指过去
⇒ `core/paths::data_dir()` 跟着走，绝不回落项目 `coding/data/`（2026-10-07 的一次自伤就是
门载荷脚本没设 `MG_CONFIG`，把 5 个假账号物化进了真实配置）；配置的
`gateway.zcode.claim_interval_seconds = 0` ⇒ **运营定时器不起**，本探针不发起任何上游请求。
账号文件（meta/credentials/runtime）**直接手写字节**，不走 `commit_login`（那条腿会物化资源）。

判据（布局类成对：既验"画出来了"也验"没撑破"）：
  P1 板块挂进总览页且可见，卡片数 = 有账号的产品数；
  P2 每卡官方图标真的加载成功（`naturalWidth>0`、20px 同档、无 404）；
  P3 逐卡读数对得上口径（积分/亿/0+已耗尽/未知 四种形状各一张）；
  P4 「1 启用」只在启用数<账号数的那张卡上出现；
  P5 值槽与 meta 零裁字、文档零横向溢出（撑破 = 用户实拍那一类缺陷）；
  P6 已耗尽那张卡的**值槽**计算色 === `--warn`（着色对象是整槽，不只染一个词）；
  P7 证据条挂在**卡根** title（口径 + 计入账号数 + 最旧时刻）；
  P8 板块位置在指标卡之后、趋势卡之前；
  P9 深色主题下同一套读数照常成立（令牌反转不破相）；
  P10 页面装配成功且零 JS 异常（`window.__MG_BOOTED`，且没有"界面脚本未能加载"）。
零写入：不点任何钮、不拨任何开关。
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "coding"))

from model_gateway.main import create_app          # noqa: E402

JS = r'''
const fs = await import("node:fs");
const PAYLOAD = JSON.parse(fs.readFileSync("__PAYLOAD__", "utf8"));
const OUT = "__OUT__";
const checks = [];
const rows = [];
const errs = [];
function ck(id, desc, ok, measured) { checks.push({ id, desc, ok: !!ok, measured: String(measured) }); }

const task = await taskSpace("MGW 总览账号资源额度探针");
let page;
try { page = await task.page(PAYLOAD.pageLabel); await page.evaluate(() => 1); }
catch (e) { page = await task.newPage(); }

const READ = () => {
  const txt = (n) => (n ? String(n.textContent || "").replace(/\s+/g, " ").trim() : "");
  const q = (s, r) => Array.from((r || document).querySelectorAll(s));
  const grid = document.querySelector(".aqgrid");
  const cards = q(".aqcard");
  const sectionCard = grid ? grid.closest(".card") : null;
  const metric = document.querySelector(".metric-card");
  const trend = document.getElementById("hour-chart");
  const warnVar = getComputedStyle(document.documentElement).getPropertyValue("--warn").trim();
  const top = (n) => (n ? Math.round(n.getBoundingClientRect().top) : -1);
  const FOLLOWS = Node.DOCUMENT_POSITION_FOLLOWING;
  const out = {
    // 位置：文档序 + 视口纵坐标（两者都判，只判一个的话"板块被搬到页尾"看不出来）
    orderTop: { metric: top(metric), grid: top(grid), trend: top(trend) },
    orderDoc: !!(metric && grid && trend)
      && ((metric.compareDocumentPosition(grid) & FOLLOWS) > 0)
      && ((grid.compareDocumentPosition(trend) & FOLLOWS) > 0),
    boot: !!window.__MG_BOOTED,
    // 🔴 判"页面坏了"要用**兜底卡节点本身**（`body.textContent` 里那句话本来就写在
  //    index.html 的内联 script 里 ⇒ 拿全文扫是一句永远为真的假判据，探针轮踩过一次）
    loadFail: (function () {
      const c = document.querySelector(".center-card");
      return !!c && String(c.textContent).indexOf("界面脚本未能加载") >= 0;
    })(),
    title: sectionCard ? txt(sectionCard.querySelector(".card-title")) : "",
    desc: sectionCard ? txt(sectionCard.querySelector(".bh-d")) : "",
    docScrollX: Math.round(document.documentElement.scrollWidth - document.documentElement.clientWidth),
    warnVar: warnVar,
    order: { metric: !!metric, grid: !!grid, trend: !!trend },
    theme: document.documentElement.getAttribute("data-theme"),
    cards: [],
  };
  cards.forEach((c) => {
    const img = c.querySelector(".mark-sm img");
    const val = c.querySelector(".aqv");
    const meta = c.querySelector(".aqm");
    const ico = c.querySelector(".mark-sm");
    out.cards.push({
      name: txt(c.querySelector(".aqt")),
      imgOk: !!img && img.naturalWidth > 0,
      imgSrc: img ? img.getAttribute("src") : "(无 img)",
      icoBox: ico ? [Math.round(ico.getBoundingClientRect().width), Math.round(ico.getBoundingClientRect().height)] : [],
      value: txt(val),
      valueClip: val ? Math.round((val.scrollWidth - val.clientWidth) * 10) / 10 : null,
      valueColor: val ? getComputedStyle(val).color : "",
      meta: txt(meta),
      metaClip: meta ? Math.round((meta.scrollWidth - meta.clientWidth) * 10) / 10 : null,
      cardTitle: (c.getAttribute("title") || ""),
      isWarn: c.classList.contains("is-warn"),
      cardBox: [Math.round(c.getBoundingClientRect().width), Math.round(c.getBoundingClientRect().height)],
    });
  });
  return out;
};

const setViewport = async (w, h) => {
  // 本机 Ego Lite 的窗口是 0 宽 ⇒ 不显式设视口，几何读数（裁字/溢出）全部没有意义
  await page.cdp("Emulation.setDeviceMetricsOverride",
    { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  await page.waitForTimeout(260);
};
const runOnce = async (theme) => {
  // 顺序 = goto → 设主题 → reload：`localStorage` 在 about:blank 上读会 SecurityError
  //（本轮实测撞过一次），必须先落到本页再写。
  await page.goto(PAYLOAD.url);
  await page.waitForSelector(".aqgrid", { timeout: 20000 });
  await page.evaluate((t) => { localStorage.setItem("mg-theme", t); }, theme);
  await page.reload();
  await page.waitForSelector(".aqgrid", { timeout: 20000 });
  await page.waitForTimeout(1200);          // 图标是真的在加载，给一次网络往返
  const d = await page.evaluate(READ);
  const by = {};
  d.cards.forEach((c) => { by[c.name] = c; });
  return { d, by };
};

await setViewport(1440, 900);
const light = await runOnce("light");
const L = light.d, B = light.by;
ck("P1", "板块挂进总览页且可见，卡片数 = 播种的产品数（4）",
   L.title.indexOf("账号资源额度") >= 0 && L.cards.length === 4 && B["CodeBuddy"] !== undefined,
   `标题=「${L.title}」描述=「${L.desc}」卡数=${L.cards.length}`);
ck("P2", "每卡官方图标真的加载成功（naturalWidth>0）且同一档尺寸",
   L.cards.every((c) => c.imgOk) && new Set(L.cards.map((c) => c.icoBox.join("x"))).size === 1,
   L.cards.map((c) => `${c.imgSrc || "—"}:${c.imgOk ? "✓" : "破图"}@${c.icoBox.join("x")}`).join(" "));
ck("P3a", "积分制卡片 = 数值 + 「积分」单位词（合计含失效包之外的两个号）",
   B["CodeBuddy"] && B["CodeBuddy"].value === "640.5 积分",
   B["CodeBuddy"] ? B["CodeBuddy"].value : "(缺卡)");
ck("P3b", "token 制卡片用中文量纲（1011158306 → 10.11亿，不裸印数字）",
   B["ZCode"] && B["ZCode"].value === "10.11亿", B["ZCode"] ? B["ZCode"].value : "(缺卡)");
ck("P3c", "取到数但合计 0 ⇒ 「0 积分 已耗尽」（真 0 与未知分得开）",
   B["Qoder"] && B["Qoder"].value === "0 积分 已耗尽" && B["Qoder"].isWarn,
   B["Qoder"] ? `${B["Qoder"].value}｜is-warn=${B["Qoder"].isWarn}` : "(缺卡)");
ck("P3d", "全部未取到 ⇒ 值槽出「未知」而**不印 0**（未知不当零）",
   B["Raccoon"] && B["Raccoon"].value === "未知" && !B["Raccoon"].isWarn,
   B["Raccoon"] ? B["Raccoon"].value : "(缺卡)");
ck("P4", "「N 启用」只在启用数<账号数的卡上出现（Qoder 单号启用不刷屏）",
   B["CodeBuddy"].meta.indexOf("1 启用") >= 0 && B["ZCode"].meta.indexOf("2 启用") >= 0
   && B["Qoder"].meta.indexOf("启用") < 0 && B["Raccoon"].meta.indexOf("启用") < 0,
   [B["CodeBuddy"], B["ZCode"], B["Qoder"], B["Raccoon"]].map((c) => c.meta).join(" ｜ "));
ck("P5", "值槽/meta 零裁字 + 文档零横向溢出（撑破 = 只验一半的通行证）",
   L.cards.every((c) => (c.valueClip || 0) <= 0.5 && (c.metaClip || 0) <= 0.5) && L.docScrollX <= 0,
   `值槽裁=${L.cards.map((c) => c.valueClip).join(",")} meta裁=${L.cards.map((c) => c.metaClip).join(",")} 文档溢出=${L.docScrollX}px`);
ck("P6", "已耗尽那张卡的**值槽**计算色 === --warn 令牌（着色对象是整槽）",
   B["Qoder"].valueColor === warnToRgb(L.warnVar),
   `值槽色=${B["Qoder"].valueColor} --warn=${L.warnVar} 转换=${warnToRgb(L.warnVar)}`);
ck("P7", "证据条挂在卡根 title（口径 + 计入账号数 + 最旧数据时刻）",
   B["CodeBuddy"].cardTitle.indexOf("只计未失效") >= 0
   && B["CodeBuddy"].cardTitle.indexOf("2 个账号计入合计") >= 0
   && /最旧数据 \d{4}-\d{2}-\d{2}/.test(B["CodeBuddy"].cardTitle),
   B["CodeBuddy"].cardTitle.slice(0, 96));
ck("P8", "板块位置 = 指标卡之后、趋势图之前（文档序与视口纵坐标一致）",
   L.orderDoc && L.orderTop.metric < L.orderTop.grid && L.orderTop.grid < L.orderTop.trend,
   `文档序=${L.orderDoc} 视口 top：指标卡=${L.orderTop.metric} 板块=${L.orderTop.grid} 趋势=${L.orderTop.trend}`);
ck("P10", "页面装配成功且没有「界面脚本未能加载」兜底卡", L.boot && !L.loadFail,
   `__MG_BOOTED=${L.boot} 兜底卡=${L.loadFail}`);

const dark = await runOnce("dark");
const D = dark.d, DB = dark.by;
ck("P9", "深色主题下同一套读数照常成立（四张卡、量纲、状态词都不受主题影响）",
   D.theme === "dark" && D.cards.length === 4 && DB["CodeBuddy"].value === "640.5 积分"
   && DB["ZCode"].value === "10.11亿" && DB["Raccoon"].value === "未知" && DB["Qoder"].isWarn,
   `theme=${D.theme} 卡数=${D.cards.length} buddy=「${DB["CodeBuddy"] ? DB["CodeBuddy"].value : "—"}」 zcode=「${DB["ZCode"] ? DB["ZCode"].value : "—"}」`);
ck("P9b", "深色下值槽色仍等于该主题的 --warn（令牌驱动，不是硬编码色）",
   DB["Qoder"].valueColor === warnToRgb(D.warnVar),
   `值槽色=${DB["Qoder"].valueColor} --warn=${D.warnVar}`);
ck("P9c", "深色下同样零裁字、零横向溢出", D.cards.every((c) => (c.valueClip || 0) <= 0.5 && (c.metaClip || 0) <= 0.5) && D.docScrollX <= 0,
   `文档溢出=${D.docScrollX}px 值槽裁=${D.cards.map((c) => c.valueClip).join(",")}`);

// 逐卡读数如实打印（报告里要能看见画出来的是什么，而不是只有 ✓）
L.cards.forEach((c) => rows.push(`浅色 ${c.name.padEnd(12)} 「${c.value}」｜${c.meta}｜卡=${c.cardBox.join("x")}`));
D.cards.forEach((c) => rows.push(`深色 ${c.name.padEnd(12)} 「${c.value}」｜${c.meta}`));
if (errs.length) rows.push("JS 异常: " + errs.join(" | "));

function warnToRgb(v) {
  // 令牌串支持 #rgb / #rrggbb（深浅两套都是 hex）
  let h = String(v || "").trim().replace("#", "");
  if (h.length === 3) h = h.split("").map((x) => x + x).join("");
  if (h.length !== 6) return "(解析不了)";
  const n = parseInt(h, 16);
  return "rgb(" + ((n >> 16) & 255) + ", " + ((n >> 8) & 255) + ", " + (n & 255) + ")";
}

try { await page.cdp("Emulation.clearDeviceMetricsOverride"); } catch (e) {}
fs.writeFileSync(OUT, JSON.stringify({ checks, rows }, null, 1), "utf8");
// 收尾关掉自己开的标签页：漏关会毒化下一轮（`page label not found: pN` 连片 FATAL 那次的教训）
try { await page.close(); } catch (e) {}
'''


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed_account(root: Path, product: str, name: str, *, enabled: bool,
                  quota: dict | None) -> None:
    """手写账号三件套（**不走** `commit_login`：那条腿会把资源物化进配置）。"""
    d = root / "upstream" / product / "accounts" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps({"name": name, "enabled": enabled},
                                            ensure_ascii=False), encoding="utf-8")
    (d / "credentials.json").write_text(json.dumps({"token": "合成的假凭据-不出站"}),
                                        encoding="utf-8")
    if quota is not None:
        (d / "runtime.json").write_text(json.dumps({"quota": quota}, ensure_ascii=False),
                                        encoding="utf-8")


def _quota(state: str, items: list, reason: str = "", data_at: str = "") -> dict:
    return {"state": state, "source": "probe", "detail": "探针合成的额度快照",
            "checked_at": "2026-10-07T09:00:00", "plan": "", "items": items,
            "remaining": None, "reason": reason, "data_at": data_at, "plan_key": ""}


def _item(unit: str, remaining, total=None, active=True) -> dict:
    return {"name": "探针包", "unit": unit, "remaining": remaining, "total": total,
            "used": None, "active": active, "expires_at": ""}


def build_instance(dirs: Path, port: int):
    """起隔离实例：配置合成 + 定时器关掉 + 数据根指向 `dirs`（`MG_CONFIG` 已设）。"""
    cfg = {
        "gateway": {"host": "127.0.0.1", "port": port,
                    "zcode": {"claim_interval_seconds": 0, "quota_net": False}},
        "resources": [],
        "models": [],
    }
    (dirs / "mgw-conf").mkdir(parents=True, exist_ok=True)
    import yaml
    (dirs / "mgw-conf" / "config.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    root = dirs / "mgw-conf"
    # 四张卡 = 四种读法：积分合计 / token 中文量纲 / 真 0（已耗尽）/ 全部未取到（未知）
    _seed_account(root, "buddy", "probe-a", enabled=True, quota=_quota("available", [
        _item("credits", 500.0, 500.0), _item("credits", 100.5, 200.0),
        _item("credits", 999.0, 999.0, active=False),     # 失效包：不得计入
        _item("credits", None),                            # 没给数字：不得当 0
    ]))
    _seed_account(root, "buddy", "probe-b", enabled=False,
                  quota=_quota("available", [_item("credits", 40.0, 40.0)]))
    _seed_account(root, "zcode", "probe-tok", enabled=True, quota=_quota(
        "available", [_item("token", 100_000_000, 100_000_000)],
        data_at="2026-10-07T08:33:00"))
    # 停用号照常计入合计（额度是只读视图，Q32 纪律）——这张卡因此同时带「2 启用」标注
    _seed_account(root, "zcode", "probe-more", enabled=False,
                  quota=_quota("available", [_item("token", 911_158_306, 1_000_000_000)]))
    _seed_account(root, "zcode", "probe-noplan", enabled=True,
                  quota=_quota("unknown", [], reason="no_plan"))
    _seed_account(root, "qoder", "probe-zero", enabled=True,
                  quota=_quota("exhausted", [_item("credits", 0.0, 100.0)]))
    _seed_account(root, "raccoon", "probe-unknown", enabled=True,
                  quota=_quota("unknown", [], reason="unreachable"))
    app = create_app(config_path=root / "config.yaml", usage_dir=dirs / "usage",
                     enums_path=dirs / "enums.yaml")
    return app


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--dir", default="")
    args = ap.parse_args()
    port = args.port or _free_port()
    base = Path(args.dir) if args.dir else Path(tempfile.mkdtemp(prefix="mgw-aq-"))
    base.mkdir(parents=True, exist_ok=True)
    import os
    os.environ["MG_CONFIG"] = str(base / "mgw-conf" / "config.yaml")
    os.environ["MGW_OPS_LOCK_DIR"] = str(base / "ops-locks")

    app = build_instance(base, port)
    # 🔴 隔离自证（本仓那条坑的正面钉法）：数据根必须不是仓库默认那份
    from model_gateway.core import paths
    root_now = paths.data_dir()
    assert root_now != paths.default_data_dir(), \
        f"数据根回落到了真实配置目录（{root_now}）—— 本探针必须隔离运行"
    print(f"隔离实例：数据根={root_now} 端口={port}（定时器 claim_interval_seconds=0 ⇒ 零出站）")

    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    import urllib.request
    up = False
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/admin/api/status", timeout=1) as r:
                up = r.status == 200
                if up:
                    break
        except Exception:
            time.sleep(0.25)
    if not up:
        print("✗ 隔离实例没起来", file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="mgw-aq-probe-"))
    pfile = tmp / "payload.json"
    ofile = tmp / "results.json"
    jfile = tmp / "probe.js"
    pfile.write_text(json.dumps({"url": f"http://127.0.0.1:{port}/#/dashboard",
                                 "pageLabel": f"aq-{tmp.name[-6:]}"}, ensure_ascii=False),
                     encoding="utf-8")
    jfile.write_text(JS.replace("__PAYLOAD__", str(pfile)).replace("__OUT__", str(ofile)),
                     encoding="utf-8")
    rc = 2
    try:
        with jfile.open("r", encoding="utf-8") as fh:
            proc = subprocess.run(["ego-browser", "nodejs"], stdin=fh, capture_output=True,
                                  text=True, timeout=300, cwd=str(tmp))
        if not ofile.exists():
            print(f"✗ 浏览器没交回读数（rc={proc.returncode}）", file=sys.stderr)
            print("  stdout: " + proc.stdout[-700:], file=sys.stderr)
            print("  stderr: " + proc.stderr[-700:], file=sys.stderr)
        else:
            data = json.loads(ofile.read_text(encoding="utf-8"))
            rows = data.get("checks", [])
            bad = [c["id"] for c in rows if not c["ok"]]
            for c in rows:
                print(f"  {'✓' if c['ok'] else '✗'} {c['id']} {c['desc']}｜{c['measured'][:230]}")
            print("\n逐卡读数：")
            for r in data.get("rows", []):
                print("  " + r)
            print(f"\n合计：{len(rows) - len(bad)} 通过 / {len(bad)} 失败"
                  + (f"  红：{bad}" if bad else ""))
            rc = 1 if bad else 0
    finally:
        server.should_exit = True
        th.join(timeout=8)
    return rc


if __name__ == "__main__":
    sys.exit(main())
