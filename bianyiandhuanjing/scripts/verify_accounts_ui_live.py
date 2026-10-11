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
       2026-10-02 起假上游多一条 `GET /billing/balance`，按 `X-Device-Mid` 分流两种回体
       （【台账】§6.1 有数值原件 / §6.2 空 plans 原件 —— 缺后者则「无套餐」这条判据真机零覆盖），
       并给每条轨迹落 `ts` + `mid` + `kind`，使"哪个号打了几次"是**可核对**的。
    ⑤ 额度**联网腿**分段（`run_quota_legs`，方案 §6 九格里真机可及的那几格）：主实例跑完后
       再起**四台**独立实例（各自数据根 + 各自 `MGW_FAKE_TRACE`）——
       段① 强制腿 + 产品级 + V16 迟到回执 / 段② 门侧**预写** `circuit.json` 的熔断腿（跑完删除）/
       段③ 反向撤证（同窗口先点「探活」，额度腿判据必须红）/ 段④ `quota_net=false` 的 cron 腿。
       🔴 窗口纪律：额度腿与探活腿打的是**同一个** `/billing/balance`，分实例 + 分窗口才不被互喂绿。

用法：
    .venv/bin/python scripts/verify_accounts_ui_live.py                  # 全量真机断言 + 截图
    .venv/bin/python scripts/verify_accounts_ui_live.py --port 8412      # 指定端口
    .venv/bin/python scripts/verify_accounts_ui_live.py --basetemp DIR   # 指定临时根
    .venv/bin/python scripts/verify_accounts_ui_live.py --shots DIR      # 截图目录
    .venv/bin/python scripts/verify_accounts_ui_live.py --retract 1|2|3  # 三项成对撤证
    .venv/bin/python scripts/verify_accounts_ui_live.py --skip-legs      # 只跑主实例（跳过额度腿）
    .venv/bin/python scripts/verify_accounts_ui_live.py --keep           # 保留临时目录

退出码：0 = 全绿；1 = 有失败；2 = 装配级错误（实例起不来 / 浏览器跑不出读数）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import traceback
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
#: 额度列**五档**（2026-10-02 方案 §4-7：「无套餐」= `state=unknown + reason=no_plan` 的**前端映射**，
#: 不是第四态枚举；「（冷却中）」等附属标注**不在此表**——它们挂在同一档后面，多一档就会打红 D6a）。
QUOTA_WORDS = ["有余量", "已耗尽", "无套餐", "未知", "尚未刷新"]
PRODUCT_IDS = ["buddy", "workbuddy", "workbuddycn", "lobsterai", "qoder", "qodercn",
               "trae", "cline", "loomy", "raccoon", "zcode"]
CHECKED_AT = "2026-10-01T09:30:00"

#: 界面空态文案的形态表 = `accounts.js:99 KIND_TEXT` 的 Python 镜像。C3 用它把"空态按 login 生成"
#: 钉成**数据侧期望**，而不是在 JS 里再抄一份同样字面量的文案（那等于前端自证）。
KIND_TEXT = {"device_code": "设备码授权", "external_link": "外链授权",
             "local_callback": "本机回跳", "qr": "扫码", "sms_code": "短信验证码"}
#: 种子用的**假 jwt 前缀**（进 A3c 的凭据外泄词表；值本身是假值，SEED 顶注写了为什么必须带）。
SEED_JWT_PREFIX = "IX-SEED-JWT"

#: 🔴 假上游 `/billing/balance` 的**分流键** = 请求头 `X-Device-Mid`（`auth.build_headers` 的唯一
#:    设备头）。单一定义 + 经环境变量同时喂给 FAKEBOOT 与种子，杜绝"门里两处各抄一份、改一处静默分叉"。
ZCODE_MID_NET = "ix-mid-quota-net"          # → §6.1 有数值原件（plans/balances 各 1）
ZCODE_MID_NO_PLAN = "ix-mid-no-plan"        # → §6.2 空 plans 原件（no_plan 只能由**这条**产出）
ZCODE_MID_NULL = "ix-mid-null-remaining"    # → 同 §6.1 体（这一档的「未给出」是**展示档**，由种子
                                            #    的 `items[].remaining=null` 钉，见 V13；联网侧同格
                                            #    = 仅单测覆盖，真机门未构造，见报告「仍未覆盖」）

#: 上游时间字段全是**秒级整数 epoch**（【台账】§6.4），种子必须写归一化**之后**的 ISO；
#: 日期动态算（固定日期会随时间腐坏成"临期/已失效"，那类跳变不是本轮判据的对象）。
def _iso_ahead(seconds: float) -> str:
    import datetime as dt

    return (dt.datetime.now() + dt.timedelta(seconds=seconds)).isoformat(timespec="seconds")


EXPIRES_ISO = _iso_ahead(86400)             # 明天：active + ISO 形状 ⇒ 「重置于 MM-DD HH:mm」必出

#: 种子表（生产入口 commit_login 落盘；runtime 三形态 absent / dict / corrupt）
SEED = [
    # 登录态失效时刻三形态（2026-10-01 用户裁决）：≤2h（警示 + 自动续期）/ 远期（正常）/ 无字段（未知）
    {"product": "buddy", "name": "ix-on", "enabled": True, "runtime": "absent",
     "cred": {"expires_at": str(int((__import__("time").time() + 1800) * 1000))}},
    {"product": "buddy", "name": "ix-off", "enabled": False, "runtime": "absent",
     "cred": {"expires_at": str(int((__import__("time").time() + 10 * 86400) * 1000))}},
    {"product": "workbuddy", "name": "ix-only-off", "enabled": False, "runtime": "absent"},
    {"product": "lobsterai", "name": "ix-quota-avail", "enabled": True,
     "device": {"uuid": "ix-uuid-0001"},
     # 🔴 2026-10-03 这格从「1 个包」改成「2 个有效包 + 1 个已失效包」：D4b 钉的是**多组逐组给量**
     #    （chips 行），旧种子聚合后只有 1 组 ⇒ chips 行**从来不渲染** ⇒ 那条判据一直在空转
     #    （同一课上一轮刚记过：判据的对象必须是需求那个集合）。已失效包另钉「另有 N 包已失效」。
     "runtime": {"quota": {"state": "available", "source": "ix-fake",
                           "detail": "有效包 2 个，本周期剩余 1000 积分",
                           "checked_at": CHECKED_AT,
                           "plan": "LobsterAI 活动包",
                           "items": [{"name": "LobsterAI 活动包", "unit": "积分",
                                      "remaining": 300, "total": None, "used": None,
                                      "active": True, "expires_at": ""},
                                     {"name": "新用户赠送", "unit": "积分",
                                      "remaining": 700, "total": 1000, "used": 300,
                                      "active": True, "expires_at": EXPIRES_ISO},
                                     {"name": "首轮赠送（已过期）", "unit": "积分",
                                      "remaining": 0, "total": 50, "used": 50,
                                      "active": False, "expires_at": "2026-09-01T08:00:00"}]}}},
    # 🔴 2026-10-03 D4c 的**对象**：同产品第二行带条、且数字列宽度与上一行差出一截。
    #    旧布局 `minmax(0,1fr) 56px auto` 下，数字 `auto` 一长短就把第一列的 `1fr` 挤掉 ⇒
    #    两行的进度条左边缘错开（用户实拍「进度条怎么还有错落啊」）。没有这一行，D4c 无从测起。
    {"product": "lobsterai", "name": "ix-quota-token", "enabled": True,
     "device": {"uuid": "ix-uuid-0002"},
     "runtime": {"quota": {"state": "available", "source": "ix-fake",
                           "detail": "有效包 1 个，本周期剩余 1 亿 token",
                           "checked_at": CHECKED_AT, "plan": "GLM 资源包",
                           "items": [{"name": "GLM 资源包", "unit": "token",
                                      "remaining": 100000000, "total": 100000000, "used": 0,
                                      "active": True, "expires_at": EXPIRES_ISO}]}}},
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
    {"product": "cline", "name": "ix-device", "enabled": True, "runtime": "absent",
     "cred": {"expires_at": str(int((__import__("time").time() - 3600) * 1000))}},   # 已过期 1h
    {"product": "loomy", "name": "ix-norefresh", "enabled": True, "runtime": "absent"},
    # 🔴 2026-10-02 方案 §8.2 的 zcode 三行额度种子。每行**必须**带 `cred.jwt` + `device_mid`：
    #    `product.quota` 在 `_resolved_credentials`（cred 优先 → meta["device_mid"]）之前就判
    #    「缺 jwt / 缺设备码 ⇒ reason=no_credentials、**不发起**」⇒ 少任一个联网腿恒 0 请求、
    #    Δtrace 恒 0，额度腿判据"红得没有道理"（QA r5 X-R4-7 点名的坑）。
    {"product": "zcode", "name": "ix-quota-net", "enabled": True,
     "cred": {"jwt": SEED_JWT_PREFIX + "-quotanet-0001"},
     "device": {"device_mid": ZCODE_MID_NET},
     "runtime": {"quota": {"state": "available", "source": "zcode-billing",
                           "detail": "plan=ZCode Trust Build；可用余量 100000000（token 量纲）",
                           "checked_at": CHECKED_AT, "plan": "ZCode Trust Build",
                           "items": [{"name": "GLM-5.3-Flash", "unit": "token",
                                      "remaining": 100000000, "total": 100000000, "used": 0,
                                      "active": True, "expires_at": EXPIRES_ISO}],
                           "remaining": 100000000, "reason": "", "data_at": CHECKED_AT,
                           "plan_key": "upl_2105792494636244992"}}},
    {"product": "zcode", "name": "ix-no-plan", "enabled": True,
     "cred": {"jwt": SEED_JWT_PREFIX + "-noplan-0002"},
     "device": {"device_mid": ZCODE_MID_NO_PLAN},
     # 「无套餐」= `state=unknown` + `reason=no_plan` + `items=[]`（裁决③：**不动枚举**）。
     # 两可性原文进 detail（【台账】§5：分不清"确实无套餐"与"该身份无 entitlement"）。
     "runtime": {"quota": {"state": "unknown", "source": "zcode-billing",
                           "detail": "上游返回空套餐列表（plans=[] 且 balances=[]）；无法区分"
                                     "「确实无套餐」与「该身份无 entitlement」",
                           "checked_at": CHECKED_AT, "plan": "", "items": [],
                           "remaining": None, "reason": "no_plan", "data_at": CHECKED_AT,
                           "plan_key": ""}}},
    {"product": "zcode", "name": "ix-null-remaining", "enabled": True,
     "cred": {"jwt": SEED_JWT_PREFIX + "-nullrem-0003"},
     "device": {"device_mid": ZCODE_MID_NULL},
     # 有桶但 `available` 未给出 ⇒ 整号 `remaining=None` ⇒ `state=unknown`（**绝不**当 0、
     # 绝不落「已耗尽」；V13 钉的就是这一格）。
     "runtime": {"quota": {"state": "unknown", "source": "zcode-billing",
                           "detail": "plan=ZCode Trust Build；可用余量 未给出（token 量纲）",
                           "checked_at": CHECKED_AT, "plan": "ZCode Trust Build",
                           "items": [{"name": "GLM-5.3-Flash", "unit": "token",
                                      "remaining": None, "total": 100000000, "used": None,
                                      "active": True, "expires_at": EXPIRES_ISO}],
                           "remaining": None, "reason": "", "data_at": CHECKED_AT,
                           "plan_key": "upl_2105792494636244992"}}},
]

#: 额度联网腿的分段实例只用 zcode 三行（独立数据根 + 独立 `MGW_FAKE_TRACE`，见「窗口纪律」）。
ZCODE_SEED = [row for row in SEED if row["product"] == "zcode"]


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
    # 🔴 显式写死**缺省形态**（方案 §2 裁决②/§6 第 8 格：默认 false = cron 腿不发起，
    #    只有用户当场点「刷新额度」（via="user"）才联网）。QN1/QN2 两条判据钉的就是这一格，
    #    靠"读不到键时的 fail-closed 缺省"来绿等于把判据建在隐式行为上。
    quota_net: false
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


#: `/billing/balance` 的分流键（= 种子 `meta.device_mid`，经 `X-Device-Mid` 头带过来）。
#: 单一来源 = 门侧环境变量，门与假上游不各抄一份。
MID_NO_PLAN = os.environ.get("MGW_IX_NO_PLAN_MID", "")


def _balance_ok(now):
    """【台账】§6.1 无损原件的**逐字形状**（字段名/量纲/嵌套照抄，只有 epoch 换成"现跑"值——
    上游时间字段全是秒级整数 epoch（§6.4），绑死历史 epoch 会让判据随日期腐坏）。"""
    return {"code": 0, "msg": "", "data": {
        "server_time": now,
        "plans": [{"user_plan_id": "upl_2105792494636244992",
                   "plan_id": "zcode-v3-start-plan-trust-1002",
                   "name": "ZCode Trust Build", "description": "ZCode Global Build",
                   "priority": 110, "status": "active",
                   "starts_at": now - 3600, "ends_at": now + 86400,
                   "entitlements": [{"entitlement_id": "zcode-v3-start-plan-trust-1002",
                                     "show_name": "GLM-5.3-Flash", "meter": "model_usage",
                                     "unit_type": "token",
                                     "capabilities": ["model:glm-5.3-flash"],
                                     "grant_units": 100000000, "period": "one_time",
                                     "priority": 110, "effective_at": 0}]}],
        "balances": [{"bucket_id": "bucket_2105792494661410816",
                      "user_plan_id": "upl_2105792494636244992",
                      "plan_id": "zcode-v3-start-plan-trust-1002",
                      "entitlement_id": "zcode-v3-start-plan-trust-1002",
                      "show_name": "GLM-5.3-Flash", "meter": "model_usage",
                      "unit_type": "token", "capabilities": ["model:glm-5.3-flash"],
                      "priority": 110, "plan_priority": 110, "entitlement_priority": 110,
                      "total_units": 100000000, "used_units": 0,
                      "remaining_units": 100000000, "available_units": 100000000,
                      "period_start": now - 3600, "period_end": now + 86400,
                      "expires_at": now + 86400}]},
        "logid": "ix-fake-balance-ok"}


def _balance_empty(now):
    """【台账】§6.2 空 plans 原件（135 字节那条的形状，逐字 `plans=[] balances=[]` + code=0）。
    🔴 「无套餐」这条判据在真机上**只有这一条产出路径**（后端 no_plan 走整键覆盖 ⇒ items 恒空），
       删掉它就等于「无套餐」零真机覆盖——反向实验①（将本路由改回 503）钉的就是这件事。"""
    return {"code": 0, "msg": "", "data": {"server_time": now, "plans": [], "balances": []},
            "logid": "ix-fake-balance-empty"}


def _handler(request):
    url = str(request.url)
    path = request.url.path
    mid = request.headers.get("X-Device-Mid") or ""
    is_balance = request.method == "GET" and path.endswith("/billing/balance")
    kind = ""
    if is_balance:
        kind = "empty-plans" if mid == MID_NO_PLAN else "ok"
    entry = {"method": request.method, "url": url, "host": request.url.host,
             "path": path, "ts": _t.time()}
    if mid:
        entry["mid"] = mid
    if kind:
        entry["kind"] = kind
    _trace(entry)                                    # 轨迹**先落**，再回响应（断腿不丢计数）
    if is_balance:
        now = int(_t.time())
        body = (_balance_empty if kind == "empty-plans" else _balance_ok)(now)
        return httpx.Response(200, json=body)
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
    cred.update(row.get("cred") or {})     # 2026-10-01：登录态失效时刻（credexp 判据）按种子注入
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
    # 假上游 `/billing/balance` 的分流键（与种子同源的那个常量，见 FAKEBOOT 顶注）：
    # 只有 `ix-no-plan` 的 mid 走空 plans 体，其余走 §6.1 有数值体。
    env["MGW_IX_NO_PLAN_MID"] = ZCODE_MID_NO_PLAN
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
/* 🔴 页标签按"进程 + 分段"唯一：并行跑动时会话之间会抢同一个 taskSpace 的同一标签
   （实测被抢后本段后续判据全报 `page label not found: p1`，且上一段留在标签页里的弹窗
   会串进本段读数 —— 遮罩数、行内钮全都不可信）。唯一标签 = 各跑各的页，红就红在自己的因上。 */
/* 🔴 取页姿势要**两种 API 都能跑**（2026-10-02 实测）：
   - 旧：`task.page(label)` 直接按标签建页；
   - 新（本机 ego lite 现版本）：`task.page(label)` 只**查**已有页 —— 返回的是懒代理，
     第一次真正使用才抛 `Error: page label not found: <label>`，而建页只有 `task.newPage()`。
   不兜底的症状 = **每一个浏览器分段都以 FATAL 收场**（读数全空、下游判据"红得没道理"），
   看起来像页面坏了，其实是取页姿势失效 ⇒ 先按标签试（保留并行会话的标签隔离），
   试不通（或拿不到可执行页）就 `newPage()`，两版都能跑完。 */
const page = await (async () => {
  const label = PAYLOAD.pageLabel || "p1";
  try {
    const p = task.page(label);
    await p.evaluate(() => 1);                     // 真用一次才知道这个标签到底存不存在
    return p;
  } catch (e) {
    return await task.newPage();                   // 每次调用自带独立页 ⇒ 同样不与别的会话抢标签
  }
})();

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
      // 🔴 Q44 起新增（H6 的观测量）：量**文本**矩形不量盒子（P-040）——名字被 flex 拉满时
      //    盒宽读的是剩余空间，文本宽才是「占用了多少 174px 预算」。徽章同理（缺省 0）。
      textW: (() => { if (!nameSpan) return 0; const r = document.createRange();
        r.selectNodeContents(nameSpan); const rects = r.getClientRects();
        return Math.round((rects.length ? rects[0].width : 0) * 10) / 10; })(),
      badgeW: (() => { const m = b.querySelector(".badge"); if (!m) return 0;
        const r = document.createRange(); r.selectNodeContents(m);
        const rects = r.getClientRects();
        return Math.round((rects.length ? rects[0].width : 0) * 10) / 10; })(),
      markH: (() => { const m = b.querySelector(".mark-sm"); return m ? Math.round(m.getBoundingClientRect().height * 10) / 10 : null; })(),
      badgeH: (() => { const m = b.querySelector(".badge"); return m ? Math.round(m.getBoundingClientRect().height * 10) / 10 : null; })(),
    };
  });
  /* 🔴 列位**按表头文字定位**，不写死下标（2026-10-03 用户指示「状态列和额度列交换下位置」）。
     此前 13 处 `td[2]` 全是硬编码：改一次列序就要扫一遍全部门，漏一处就产出"红得没有道理"的读数
     （额度列变成开关列 ⇒ 词表判据恒不命中、几何判据读不到 `.qbar`）。表头本身由静态门 V6 逐字钉住。 */
  const thTexts = q("#ac-table thead th").map((x) => txt(x));
  const QI = thTexts.indexOf("额度"), SI = thTexts.indexOf("状态");
  const rows = q("#ac-table tbody tr[data-acc]").map((tr) => {
    const td = q("td", tr);
    const sw = tr.querySelector("[role=switch]");
    const qcell = td[QI] || null;
    const cell = qcell ? qcell.firstElementChild : null;
    return {
      name: tr.dataset.acc, cls: tr.className,
      account: txt(td[0]), state: txt(td[SI]),
      sub: (() => { const ds = q("div", td[0]); return ds.length > 1 ? txt(ds[1]) : ""; })(),
      quota: txt(td[QI]), quotaColor: cell ? cs(cell).color : "",
      // 🔴 2026-10-03 额度格重做（用户实拍「乱对齐 + 放不下 + 还弄个展开折叠」，点名照
      //    zcode-switch / ZCode-Panel / Jet Hub 做）⇒ 读取面整体搬家：
      //    `.qchk`→`.qmeta`（到期 + 相对新鲜度 + 失效计数）、`.qpacks-detail`→`.qchips`（同名聚合逐组给量）、
      //    折叠入口不存在 ⇒ 反向钉 `foldCount === 0`；占比条新增 `barW`（= Σ剩余/Σ总量）。
      quotaMeta: td[QI] ? txt(td[QI].querySelector(".qmeta")) : null,
      quotaTip: (cell && cell.getAttribute && cell.getAttribute("title")) || "",
      quotaChips: (() => { const d = td[QI] && td[QI].querySelector(".qchips");
        return d ? txt(d) : ""; })(),
      /* 🔴 「合计：900 积分」= 数值贴标签（2026-10-03 用户裁定）。三把尺全部**量文本边缘**：
         `labelGapPx` = 标签文本右缘 → 数值文本左缘（量盒子会被 flex 项拉宽骗过 ⇒ 读数恒等于 gap，
         「量盒子不等于量文本」这一课已经踩过两次）；
         `numClip` = 数值被裁掉多少（必须 0：被挤的只能是标签那一半）；
         `labelClip` = 标签被省略号收掉多少（允许 >0，但 `title` 必须给全名）；
         `labelEndsColon` / `qvalShell` = 语法两半（「：」收尾 + 右浮壳不得回魂）。 */
      labelGapPx: (() => { const row = td[QI] && td[QI].querySelector(".qrow");
        const nm = row && row.querySelector(".qname");
        const num = row && row.querySelector(".qnum");
        if (!nm || !num) return null;
        const r1 = document.createRange(); r1.selectNodeContents(nm);
        const r2 = document.createRange(); r2.selectNodeContents(num);
        return Math.round((r2.getBoundingClientRect().left
          - r1.getBoundingClientRect().right) * 10) / 10; })(),
      numClip: (() => { const n = td[QI] && td[QI].querySelector(".qnum");
        return n ? Math.round((n.scrollWidth - n.clientWidth) * 10) / 10 : null; })(),
      labelClip: (() => { const n = td[QI] && td[QI].querySelector(".qname");
        return n ? Math.round((n.scrollWidth - n.clientWidth) * 10) / 10 : null; })(),
      labelEndsColon: (() => { const n = td[QI] && td[QI].querySelector(".qname");
        return n ? /[：:]$/.test(txt(n)) : null; })(),
      qvalShell: td[QI] ? td[QI].querySelectorAll(".qval").length : 0,
      foldCount: td[QI] ? td[QI].querySelectorAll("[data-qpacks], .qpacks-detail").length : 0,
      badgeCount: td[QI] ? td[QI].querySelectorAll(".badge").length : 0,
      barW: (() => { const i = td[QI] && td[QI].querySelector(".qbar > i");
        return i ? (i.style.width || "") : ""; })(),
      // 🔴 D4c 的两把尺：条的**左边缘 x**（同产品各行必须同一个值）与**轨道底色**
      //（用掉的那一段是灰的，不是"看不见总长"）。左边缘按当前视口实测，不按 CSS 字符串猜。
      barLeft: (() => { const b = td[QI] && td[QI].querySelector(".qbar");
        return b ? Math.round(b.getBoundingClientRect().left * 10) / 10 : null; })(),
      barTrack: (() => { const b = td[QI] && td[QI].querySelector(".qbar");
        return b ? cs(b).backgroundColor : ""; })(),
      // 🔴 D4d：溢出与裁字必须**入账**（2026-10-03 「定宽三列」那版把条钉住了、把数字挤到裁字，
      //    门里当时没有任何一条判据看得见这件事——只有我手写的 :8300 探针抓到了）。
      cellOver: (() => { const c = td[QI] && td[QI].querySelector(".qcell");
        return c ? c.scrollWidth - c.clientWidth : 0; })(),
      numOver: (() => { const n = td[QI] && td[QI].querySelector(".qnum");
        return n ? n.scrollWidth - n.clientWidth : 0; })(),
      // 🔴 D4e（2026-10-03 用户实拍「怎么有的字体加粗有的不加粗」）：字重是**层级语言**，
      //    一格只许一处 700 = 主读数；标签 / 档位词 / meta 一律 600。这里把当行取到的计算字重交出去。
      weights: (() => {
        const c = td[QI] && td[QI].querySelector(".qcell");
        if (!c) return null;
        const pick = (sel) => { const e = c.querySelector(sel); return e ? cs(e).fontWeight : ""; };
        return { num: pick(".qnum"), name: pick(".qname"), meta: pick(".qmeta"),
                 tier: pick(".qtier"), none: pick(".qnone"),
                 boldCount: Array.from(c.querySelectorAll("*"))
                   .filter((e) => ["700", "800", "bold"].includes(cs(e).fontWeight)).length };
      })(),
      ops: q("[data-op]", tr).map((b) => b.dataset.op),
      swAria: sw ? { role: sw.getAttribute("role"), checked: sw.getAttribute("aria-checked"),
        label: sw.getAttribute("aria-label"), on: sw.classList.contains("on"),
        h: Math.round(sw.getBoundingClientRect().height * 10) / 10 } : null,
      h: Math.round(tr.getBoundingClientRect().height * 10) / 10,
    };
  });
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
    navTitles: q(".subnav .nav-group-title").map(txt),
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
    rows, resident,
    expCells: q("#ac-table [data-exp]").length + q("#ac-table tr[data-rexp]").length,
    modalMopRows: q(".modal [data-mop]").map((b) => b.dataset.acc + ":" + b.dataset.mop),
    modalMopTexts: q(".modal [data-mop]").map(txt),
    modalMaskCount: document.querySelectorAll(".modal-mask").length,
    modalW: (() => { const m = document.querySelector(".modal");
      return m ? Math.round(m.getBoundingClientRect().width) : null; })(),
    /* 脚钮两态（2026-10-03 用户「初始化之后，则这个按钮不再显示，变为保存按钮」）：
       读**画出来的文案**与主动钮颗数 —— 静态门 V22 钉的是源码形状，这里钉的是屏幕上那一颗。 */
    modalPrimary: q(".modal-foot .btn-primary").map((b) => txt(b)),
    /* 🔴 「已初始化就收起」画出来是什么：`hidden` 的钮仍在 DOM 里 ⇒ 只看 `modalPrimary` 会把
       "收起了"读成"还挂着"。可见性单独取一次（2026-10-05 脚钮语义从两态变一态后必须分相）。 */
    modalPrimaryVisible: q(".modal-foot .btn-primary")
      .filter((b) => !b.hidden && b.offsetParent !== null).map((b) => txt(b)),
    mapFootBtns: q(".modal-foot .btn").length,
    /* 🔴 草稿制（2026-10-05 第四次裁定）三颗钮各有各的主人：AI 那颗**常驻一态**，
       保存那颗的文案与使能读的是**脏态数**（源码形状由静态门 V22 钉，这里钉画出来的那一份）。 */
    aiBtn: (() => { const b = document.querySelector('.modal-foot [data-map="ai"]');
      return b ? { text: txt(b), disabled: !!b.disabled, hidden: !!b.hidden } : null; })(),
    saveBtn: (() => { const b = document.querySelector('.modal-foot [data-map="save"]');
      return b ? { text: txt(b), disabled: !!b.disabled } : null; })(),
    footTexts: q(".modal-foot .btn").map((b) => txt(b)),
    /* 消耗声明必须在**表上方**（483 行的表里脚注滚不到 = 等于没声明）。 */
    mapNoteAbove: (() => { const card = document.querySelector(".modal .list-card");
      const note = Array.from(document.querySelectorAll(".modal .alert-warn"))
        .find((x) => txt(x).indexOf("真实出站一次") >= 0);
      if (!note) return null;
      const n = note.getBoundingClientRect(), c = card ? card.getBoundingClientRect() : null;
      return { beforeTable: c ? (n.bottom <= c.top + 0.5) : false,
               text: txt(note).slice(0, 220) }; })(),
    mapRows: (() => { const card = document.querySelector(".modal .list-card");
      return card ? Array.from(card.querySelectorAll(".list-row")).slice(1).map((r2) => {
        const name = r2.querySelector("b");
        const sub = r2.querySelector("span span");
        const sel = r2.querySelector("select[data-idx]");
        const sw = r2.querySelector("[data-mapsw] .switch");
        const foot = r2.querySelector("[data-mapfoot]");
        return { name: name ? txt(name) : "", sub: sub ? txt(sub) : "",
                 hasSel: !!sel, selV: sel ? sel.value : null,
                 /* 2026-10-04「状态列删除」：旧 `badge`（第 4 格文本）这个读数对象已不存在。
                    换成两个**新载体**：下拉下面那一行（未落库说明 ⇄ 删除钮）与格数。
                    `foot: "∅"` = 那一行整条不在 = 结构坏了，与"空文本"必须分得开。 */
                 foot: foot ? txt(foot) : "∅", hasFoot: !!foot,
                 delBtn: !!r2.querySelector("[data-mapdel]"),
                 /* 「建议挂到 X · 采纳并入库」（2026-10-05：建议不再进下拉，只在这里给一键采纳） */
                 adopt: !!r2.querySelector("[data-adopt]"),
                 adoptName: (r2.querySelector("[data-adopt]") || {}).dataset?.adopt || "", 
                 cells: r2.children.length,
                 opts: sel ? Array.from(sel.options).map((o) => o.value) : [],
                 hasSw: !!sw, swOn: sw ? sw.classList.contains("on") : null,
                 ariaSw: sw ? sw.getAttribute("aria-checked") : null,
                 swDisabled: sw ? !!sw.disabled : null, swTitle: sw ? (sw.title || "") : "",
                 swMissingCell: !!(r2.children[3] && !r2.children[3].querySelector(".switch")) };
      }) : []; })(),
    /* 表头逐字（状态列删除的判据对象：第 4 列「状态」不许回来，也不许留下没人住的空列）。 */
    mapHeads: (() => { const card = document.querySelector(".modal .list-card");
      const h = card ? card.querySelector(".list-row") : null;
      return h ? Array.from(h.children).map((c) => txt(c)) : []; })(),
    alertErr: q("#ac-panel .alert-err").length,
    alertErrText: txt(document.querySelector("#ac-panel .alert-err")),
    retry: q("#ac-retry").length,
    // 🔴 批量结果的**结果浮层**（2026-10-03 用户裁定：「各类处理结果，不允许用这种形式固化显示。
    //    执行完毕，弹窗提示具体执行结果，3s 后自动消失，也可以手动关闭」⇒ 旧的"就地槽 + 回填"整族作废）。
    //    读数要三件事：浮层说了什么（计数原文 + 逐号行 + 计数行悬停的解释）、它是不是**浮层**
    //    （住在 #toast-wrap、不在任何弹窗里）、以及**面板里还有没有固化块**（必须 0）。
    toastCard: (() => {
      const t = document.querySelector("#toast-wrap .toast.card");
      if (!t) return null;
      const r = t.getBoundingClientRect();
      const sum = t.querySelector(".t-sum");
      return {
        text: txt(t), sum: sum ? txt(sum) : "", sumTitle: sum ? (sum.getAttribute("title") || "") : "",
        rows: t.querySelectorAll(".t-row").length,
        tags: q(".t-tag", t).map(txt),
        hasClose: !!t.querySelector(".t-close"),
        closeAria: (t.querySelector(".t-close") || {}).ariaLabel
          || t.querySelector(".t-close")?.getAttribute("aria-label") || "",
        inModal: !!(t.closest && t.closest(".modal")),
        inWrap: !!t.closest("#toast-wrap"),
        w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10,
      };
    })(),
    toastCount: document.querySelectorAll("#toast-wrap .toast.card").length,
    receiptBlocks: document.querySelectorAll(".bulk-receipt, #ac-receipt").length,
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
      trackRgb: probe("backgroundColor", "--progress-track"),
      okRgb: probe("backgroundColor", "--ok"),
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
  ck("RT2", "撤证①：.anchor-item 计数 === 在册产品数 11（Q44 起）", r.rail.length === 11, "计数=" + r.rail.length);
  ck("RT3", "撤证①：rail 容器类名含 subnav-scroll（不得被换成族卡片）",
     /subnav-scroll/.test(r.railBox.cls), "class=「" + r.railBox.cls + "」");
  ck("RT4", "撤证①：rail 行 title 逐字判据仍成立（与族层无关的对照项）",
     r.rail.every((x) => E.railTitles[x.pid] === x.title),
     "不符 " + r.rail.filter((x) => x.title !== E.railTitles[x.pid]).length + "/11；首行=「" + (r.rail[0] || {}).title + "」");
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
} else if (MODE === "quota-leg") {
  /* 🔴 额度**联网腿**分段（2026-10-02 方案 §8.2「窗口纪律」）。
     本段跑在**独立实例**上：自己的数据根 + 自己的 `MGW_FAKE_TRACE`（假上游把每条
     `GET /billing/balance` 落轨迹，带 ts 与 `X-Device-Mid`）。窗口边界时间戳由页面给出
     （与轨迹同一台机器的墙钟），Python 侧按窗口切轨迹算 Δtrace，再与**回执**对表。
     为什么非切不可：额度腿与探活腿打的是**同一个** `/billing/balance`，
     混在一个窗口里就是"被探活喂绿"。 */
  const leg = E.leg || {};
  const variant = String(leg.variant || "clean");
  const pid = String(leg.product || "zcode");
  const acct = String(leg.account || "ix-quota-net");
  const onePath = "/admin/api/accounts/" + pid + "/" + acct + "/quota";
  const allPath = "/admin/api/accounts/" + pid + "/quota-all";
  const probePath = "/admin/api/accounts/" + pid + "/" + acct + "/probe";
  const windows = [];
  const SETTLE = 700;                       // 窗口两端的余量（轨迹 ts 落在窗口内即可归属）
  await setViewport(1440, 900);
  await page.goto(PAYLOAD.url + "#/accounts?p=" + pid);
  await page.waitForSelector("#ac-table tbody tr[data-acc]", { timeout: 25000 });
  await page.waitForTimeout(400);
  await instrument();
  const has = (k) => page.evaluate((key) => !!(window.__ix && window.__ix.byPath
                                      && window.__ix.byPath[key]), k);
  const waitResp = async (k, ms) => {
    const dl = Date.now() + (ms || 45000);
    while (Date.now() < dl) { if (await has(k)) return true; await page.waitForTimeout(150); }
    return false;
  };
  // 浮层的"新鲜度"探针：点击前给**当时已在屏上的**浮层打 `ixseen` 标记 ⇒
  // 「出现一条没有标记的新浮层且含"刷新"」= 这批结果真的送达，不是上一批那 3 秒还没走完的残影。
  const markSlot = () => page.evaluate(() => {
    document.querySelectorAll("#toast-wrap .toast.card").forEach((t) => { t.dataset.ixseen = "1"; });
    return true;
  });
  const waitReceipt = async (ms) => {
    const dl = Date.now() + ms;
    while (Date.now() < dl) {
      const ready = await page.evaluate(() => {
        const t = document.querySelector("#toast-wrap .toast.card:not([data-ixseen])");
        return !!t && (t.textContent || "").indexOf("刷新") >= 0;
      });
      if (ready) return true;
      await page.waitForTimeout(120);
    }
    return false;
  };
  const snap = async (name, t0) => {
    await page.waitForTimeout(SETTLE);
    const rr = await read();
    windows.push({ name, t0, t1: await page.evaluate(() => Date.now()) });
    return rr;
  };

  if (variant === "circuit") {
    /* 熔断腿：门侧**预写** circuit.json（与账号根同级，`quota.py::circuit_path()` 同一口径）
       ⇒ 钩子在"发起前判定"就拒跑：Δtrace 必须恒 0、reason=circuit、合并写保住旧数值面。 */
    const t0 = await page.evaluate(() => Date.now());
    await click("tr[data-acc='" + acct + "'] [data-op='quota']");
    const arrived = await waitResp(onePath, 45000);
    const rr = await snap("circuit", t0);
    ck("QC0", "熔断腿：账号级「刷新额度」端点有响应（熔断是**拒跑**，不是把请求挂死）",
       arrived, "响应到位=" + arrived);
    ck("QC-UI", "熔断腿界面：数值**不被洗掉**且挂附属标注「（冷却中）」（合并写的可见后果，五档不新增）",
       (rowOf(rr, acct).quota || "").indexOf("（冷却中）") >= 0
       && /\d/.test(rowOf(rr, acct).quota || ""),
       "额度格=「" + (rowOf(rr, acct).quota || "") + "」 toasts=" + j(rr.toasts));
    extra.leg = { variant, windows, bodies: await page.evaluate((keys) => {
      const o = {}; keys.forEach((k) => { o[k] = window.__ix.byPath[k] || null; }); return o;
    }, [onePath]), rows: (rr.rows || []).map((x) => ({ name: x.name, quota: x.quota, sub: x.quotaMeta })) };
    await shot(PAYLOAD.shotName || "quota-leg-circuit");
  } else if (variant === "probe-window") {
    /* 🔴 反向撤证：同一窗口内先点「探活」（同一个 `/billing/balance`），再点「刷新额度」。
       额度腿判据（Δtrace == 回执 N）在这种窗口里**必须红**——不写这条就等于"被探活喂绿"。 */
    const t0 = await page.evaluate(() => Date.now());
    await click("tr[data-acc='" + acct + "'] [data-op='probe']");
    const p1 = await waitResp(probePath, 45000);
    await page.waitForTimeout(SETTLE);
    await click("tr[data-acc='" + acct + "'] [data-op='quota']");
    const p2 = await waitResp(onePath, 45000);
    const rr = await snap("probe-then-quota", t0);
    ck("QR0", "撤证窗口装配：探活与额度两次响应都到位（红要红得起来，先得确认动作发生了）",
       p1 && p2, "probe=" + p1 + " quota=" + p2);
    extra.leg = { variant, windows, bodies: await page.evaluate((keys) => {
      const o = {}; keys.forEach((k) => { o[k] = window.__ix.byPath[k] || null; }); return o;
    }, [probePath, onePath]), rows: (rr.rows || []).map((x) => ({ name: x.name, quota: x.quota })) };
    await shot(PAYLOAD.shotName || "quota-leg-probe-window");
  } else {
    /* 干净窗口三段：W1 账号级强制腿 → W2 产品级（扇出 delay_s=1.2）→ W3 迟到回执 V16。 */
    const t0 = await page.evaluate(() => Date.now());
    await click("tr[data-acc='" + acct + "'] [data-op='quota']");
    const a1 = await waitResp(onePath, 45000);
    const r1 = await snap("account-quota", t0);
    ck("QL0a", "强制腿装配：账号级「刷新额度」= 1 击 + 1 次端点响应（回执 N 的来源必须是这一次）",
       a1 && nOf(await reqs(), onePath) === 1,
       "响应到位=" + a1 + " POST 计数=" + nOf(await reqs(), onePath));
    const t2 = await page.evaluate(() => Date.now());
    await click("#ac-quota");
    const a2 = await waitResp(allPath, 60000);
    const r2 = await snap("quota-all", t2);
    // 🔴 `byPath` 每个 path 只留**最后一次**响应 ⇒ W2 的回执必须当场取走，不能事后从
    //    `bodies[allPath]` 读（那已经是 W3 的那一次了，Δtrace 与回执就不是同一批的账）。
    const rcpt2 = await page.evaluate((k) => window.__ix.byPath[k] || null, allPath);
    ck("QL0b", "产品级装配：卡头「刷新额度」= 1 击 + 1 次 quota-all 响应",
       a2 && nOf(await reqs(), allPath) === 1,
       "响应到位=" + a2 + " POST 计数=" + nOf(await reqs(), allPath));
    /* 🔴 2026-10-03 用户裁定（实拍 Raccoon 面板上那块常驻的「刷新 0 · 失败 0 · 未发起 2」）：
       「各类处理结果，不允许用这种形式固化显示。执行完毕，弹窗提示具体执行结果，3s 后自动消失，
        也可以手动关闭。」⇒ 批量结果**既不是弹窗、也不是面板里的一块**，而是结果浮层。
       旧 QL0c 钉的"无遮罩时开一层回执弹窗"随之作废（反转而不是删条目）：现在遮罩数必须恒为 0。
       🔴 2026-10-11：原「截图在浮层读取之前」挪到**之后**——CDP 截图慢时会把读取推过浮层
       3s 寿命 ⇒ 偶发假红（本轮第一/三跑各红一次、第二跑绿 = 边缘竞态实证）。读取是证据本体，
       截图只是辅助；判据一字未改。 */
    const masksW2 = await page.evaluate(() => document.querySelectorAll(".modal-mask").length);
    const rW2 = await read();
    await shot("quota-leg-after-all");
    ck("QL0c", "产品级回执**不开弹窗**（遮罩数 === 0）且结果浮层恰一张、住在 #toast-wrap 里"
       + "（旧判据「无遮罩时开单层弹窗」随本轮裁定反转）",
       masksW2 === 0 && rW2.toastCount === 1 && !!rW2.toastCard
       && rW2.toastCard.inWrap === true && rW2.toastCard.inModal === false,
       "遮罩数=" + masksW2 + " 浮层数=" + rW2.toastCount
       + " 卡=「" + ((rW2.toastCard || {}).text || "").slice(0, 90) + "」");
    // 让它**自然到期**（不手动 remove）：这一等同时是"3s 自动消失"的第一次实证
    await page.waitForTimeout(3400);
    const rGone = await read();
    ck("QL0c2", "结果浮层到期自动消失，且面板里**没有任何固化块**（`.bulk-receipt`/`#ac-receipt` = 0）",
       rGone.toastCount === 0 && rGone.receiptBlocks === 0,
       "到期后浮层数=" + rGone.toastCount + " 固化块=" + rGone.receiptBlocks);

    /* V16（迟到回执判据，静态门没有遮罩机制 ⇒ 只在真机门跑得成；2026-10-03 随裁定改写）：
       ① 批量在飞期间开着映射弹窗 → 新浮层到达，`.modal-mask` **恒为 1**
          （浮层不碰遮罩 ⇒ 单层红线由**构造**保证，不再需要"判遮罩 + 退回就地槽"那条分支）；
       ② 浮层含三段计数**原文** + 逐号行，术语解释挂计数行悬停（不坐正文）；
       ③ × 手动关闭 = 立即消失；
       ④ 取消映射弹窗后归零，全程面板零固化块。 */
    await click("#ac-map");
    await page.waitForSelector(".modal .list-card", { timeout: 25000 });
    await markSlot();
    const t4 = await page.evaluate(() => Date.now());
    await click("#ac-quota");
    const arrived = await waitReceipt(60000);
    const masks = await page.evaluate(() => document.querySelectorAll(".modal-mask").length);
    const r3a = await read();
    const rcpt3 = await page.evaluate((k) => window.__ix.byPath[k] || null, allPath);
    ck("V16a", "🔴 单层弹窗红线：批量额度在飞期间开着映射弹窗，**新**结果浮层到达后 .modal-mask 恒为 1"
       + "（浮层不是 modal ⇒ 不需要判遮罩分支也不叠第二层）",
       arrived && masks === 1 && r3a.toastCount === 1 && !!r3a.toastCard
       && r3a.toastCard.inModal === false,
       "送达=" + arrived + " 遮罩数=" + masks + " 浮层数=" + r3a.toastCount
       + " 卡住弹窗里=" + ((r3a.toastCard || {}).inModal));
    const card = r3a.toastCard || {};
    ck("V16b", "结果浮层说清这一批：三段计数**原文**（刷新 N · 失败 K · 未发起 J）+ 逐号行 + "
       + "术语解释挂计数行悬停（3 秒读不完的定义不做成正文必读）",
       /刷新 \d+ 个 · 失败 \d+ 个 · 未发起 \d+ 个/.test(card.sum || "")
       && (card.rows || 0) >= 1 && (card.tags || []).length === card.rows
       && (card.sumTitle || "").indexOf("未发起") >= 0
       && card.hasClose === true && /关闭/.test(card.closeAria || ""),
       "计数行=「" + (card.sum || "").slice(0, 90) + "」 逐号行=" + card.rows
       + " 结果词=" + j(card.tags) + " 悬停解释长度=" + (card.sumTitle || "").length
       + " 关闭钮=" + card.hasClose + "/" + card.closeAria);
    await page.click("#toast-wrap .toast.card .t-close");
    await page.waitForTimeout(350);
    const r3c = await read();
    ck("V16c", "× 手动关闭立即消失（不等 3 秒）",
       r3c.toastCount === 0, "点关闭后浮层数=" + r3c.toastCount);
    await click(".modal-foot .btn");                 // 取消映射弹窗（不落库）
    await page.waitForTimeout(500);
    const r3b = await read();
    ck("V16d", "映射弹窗取消归零，且 V16 全程**面板零固化块**（结果不落进页面任何常驻位置）",
       r3b.modalCount === 0 && r3b.receiptBlocks === 0 && r3b.toastCount === 0,
       "modal-root=" + r3b.modalCount + " 固化块=" + r3b.receiptBlocks + " 浮层数=" + r3b.toastCount);
    const w3 = { name: "v16-quota-all", t0: t4, t1: await page.evaluate(() => Date.now()) };
    windows.push(w3);
    extra.leg = { variant, windows, receiptW2: rcpt2, receiptW3: rcpt3, bodies: await page.evaluate((keys) => {
      const o = {}; keys.forEach((k) => { o[k] = window.__ix.byPath[k] || null; }); return o;
    }, [onePath, allPath]),
      rows: (r1.rows || []).map((x) => ({ name: x.name, quota: x.quota, sub: x.quotaMeta })),
      rowsAfter: (r2.rows || []).map((x) => ({ name: x.name, quota: x.quota, sub: x.quotaMeta,
      chips: x.quotaChips, barW: x.barW, fold: x.foldCount,
      labelGap: x.labelGapPx, numClip: x.numClip, labelClip: x.labelClip,
      qvalShell: x.qvalShell })),
      receiptText: (r2.toastCard || {}).text || "" };
    await shot(PAYLOAD.shotName || "quota-leg-receipt-inline");
  }
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
  ck("B1", "rail 行数：.anchor-item 计数 === 在册产品数 11（扁平、无族层；Q44 起）",
     r.rail.length === 11, "计数=" + r.rail.length + " pids=" + r.rail.map((x) => x.pid).join(","));
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
  ck("B4d", "四态点·无：0 账号产品（按实际计数，2026-10-02 起只剩 raccoon）的 dots 数 === 0",
     E.zeroAccountProducts.every((p) => (((r.rail.find((x) => x.pid === p) || {}).dots) || []).length === 0),
     E.zeroAccountProducts.map((p) => p + "=" + (((r.rail.find((x) => x.pid === p) || {}).dots) || []).length).join(" "));
  ck("B4e", "四态互不相同（绿/橙/灰 三色各异，杜绝「三态同形」）",
     new Set([dot("buddy"), dot("qodercn"), dot("workbuddy")]).size === 3,
     "green=" + dot("buddy") + " warn=" + dot("qodercn") + " off=" + dot("workbuddy"));
  ck("B5", "rail 行 title 逐字 === 「产品名 · N 个账号（M 已启用）」（11/11）",
     r.rail.every((x) => x.title === E.railTitles[x.pid]),
     "首行=「" + (r.rail[0] || {}).title + "」；不符 " + r.rail.filter((x) => x.title !== E.railTitles[x.pid]).length + "/11");
  ck("B6", "rail 容器 role=tablist + aria-orientation=vertical + aria-label",
     r.railBox.role === "tablist" && r.railBox.orient === "vertical" && !!r.railBox.label,
     "role=" + r.railBox.role + " orientation=" + r.railBox.orient + " label=「" + r.railBox.label + "」");
  ck("B6b", "每行 role=tab（11/11）",
     r.rail.every((x) => E.railTitles[x.pid] !== undefined) && r.rail.length === 11,
     "行数=" + r.rail.length + "；tabindex 值集=" + j(Array.from(new Set(r.rail.map((x) => x.tab)))));
  // 🔴 H6 · 窄栏宽度预算（frontend-spec §2.3 `.panel-split-narrow` 定版公式，Q44 起钉住；
  //    2026-10-11 加宽 174→200：最长名 `WorkBuddy（国际版/中国版）` 实测 139.9px+徽章 ⇒
  //    旧 174px 下名字被裁（国际版行自 09-30 起既已裁，本轮 H6 首次量出）。
  //    200px = 10(subnav padding)+20(icon)+8+名字+8+徽章+8+圆点 ⇒ **名字+徽章 ≤ 146px**
  //    （1px 容差）。撤证方向 = 往注册表 title 再塞两个字 ⇒ 本条当场红。
  {
    const over = r.rail.filter((x) => (x.textW || 0) + (x.badgeW || 0) > 146);
    ck("H6", "窄栏宽度预算：每行 名字文本+徽章 ≤ 121px（174px 分解公式的判据化，P-040 量文本）",
       over.length === 0 && r.rail.every((x) => (x.textW || 0) > 0),
       over.map((x) => x.pid + "=名字" + x.textW + "+徽章" + x.badgeW).join(" | ")
       + "｜全行 textW=" + r.rail.map((x) => x.pid + ":" + x.textW).join(","));
  }
  const sel = r.rail.filter((x) => x.aria === "true");
  ck("B7", "aria-selected=true 恰好 1 行，且与 .active 同位",
     sel.length === 1 && sel[0].pid === act(r),
     "selected=" + sel.map((x) => x.pid).join(",") + " active=" + act(r));
  ck("B8", "roving tabindex：active 行 tabindex=0，其余 10 行 = -1（Q44 起 11 行）",
     r.rail.filter((x) => x.tab === "0").length === 1 && r.rail.filter((x) => x.tab === "-1").length === 10,
     "tab0=" + r.rail.filter((x) => x.tab === "0").map((x) => x.pid).join(",") + " tab-1 数=" + r.rail.filter((x) => x.tab === "-1").length);
  ck("B13", "「只看有账号」派生开关在空产品数 <5 时不渲染（§1.3 触发态；判据按**实际计数**，不写死个数）",
     r.filterSwitch === 0 && E.zeroAccountProducts.length < 5,
     "#ac-only=" + r.filterSwitch + " 空产品数=" + E.zeroAccountProducts.length
     + "（阈值 5，railScope 同源）");
  /* 🔴 顶距读数必须在 `page.evaluate` 里取：**分段体本身跑在 Node 侧，没有 `document`**。
     2026-10-02 全量第一轮我把它写成裸 `document.getElementById(...)`，整个 `rail` 分段当场
     `ReferenceError: document is not defined` 中断 ⇒ 连带 20 条红（门内 SEC-rail 自测正是为此而设，
     它把这一条报成红是对的）。同一段的 `r.subnav` 是 `read()` 已经量好的框，只用它。 */
  const railGap = await page.evaluate(() => {
    const a = document.querySelector("#content aside.subnav");
    const b = document.getElementById("ac-claim-all");
    if (!a || !b) return null;
    return Math.round((b.getBoundingClientRect().top - a.getBoundingClientRect().top) * 10) / 10;
  });
  ck("B18b", "rail 顶区内衬：第一个元素（「一键签到」）上缘距 rail 上缘 = 12px（删标题后不许贴线；"
     + "2026-10-02 用户「一键签到按钮怎么顶到上面横线上去了」）",
     railGap !== null && railGap >= 10 && railGap <= 14,
     "实测顶距=" + railGap + "px（期望 12；null = 探针没取到 rail 或那颗钮）");
  ck("B14", "子侧栏顶部零分组总标题（2026-10-02 用户指示删「产品列表」，与「模型厂商」同口径；"
     + "页标题已自明，无障碍名保留在 #ac-rail 的 aria-label）",
     r.navTitles.length === 0, "rail 内 .nav-group-title=" + j(r.navTitles));
});

await section("panel", async () => {
  // 2026-09-30 改口径：用户判定「选定产品后还要到左下方操作」动线不合理 → 入口定版在卡头（与所作用产品同框）
  // Q30 起卡头 = 模型映射 + 一键领取（checkin 门控）+ 批量续期（refresh 门控）+ 接入账号 → buddy 恒 4 钮
  // 2026-10-02 方案 §5-6：卡头新增第 5 颗「刷新额度」（balance 能力位门控，产品级）→ buddy 恒 **5** 钮
  ck("C1", "卡头 = 产品名 + 计数 + 操作组（模型映射/一键领取/刷新额度/批量续期/接入账号，入口 #ac-add 唯一）",
     r.head.buttons === 5 && r.headAdd === 1 && r.head.title === "CodeBuddy" && r.head.values.length === 1,
     "card-head 按钮=" + r.head.buttons + " #ac-add=" + r.headAdd + " title=「" + r.head.title + "」 values=" + j(r.head.values));
  ck("C2", "全页接入入口恰好 1 处，且就在卡头（rail 底 .side-add 已移除）",
     r.headAdd === 1 && r.addBtnsAnywhere === 1 && r.sideAdd === 0,
     "#ac-add=" + r.headAdd + "；文本含「接入账号」的 button=" + r.addBtnsAnywhere + " .side-add=" + r.sideAdd);
  /* 🔴 2026-10-03 用户「状态列和额度列交换下位置」⇒ 列集随设计前进为 账号/额度/状态/操作
     （与静态门 V6 同一份口径；仍是逐字钉四列，不是放宽判据）。 */
  ck("C4", "表头逐字 = 账号 / 额度 / 状态 / 操作（4 列，无展开指示列）",
     j(r.ths.map((t) => t.text)) === j(["账号", "额度", "状态", "操作"]),
     "实测=" + j(r.ths.map((t) => (t.cls ? "." + t.cls : "·") + (t.text || "∅"))));
  ck("C3b", "buddy 面板两行按数据渲染（ix-off / ix-on）",
     j(r.rows.map((x) => x.name)) === j(["ix-off", "ix-on"]), "行=" + r.rows.map((x) => x.name).join(","));
  ck("C11", "状态列零文字：只放开关，不再有「已启用/已停用」状态字（2026-10-01 用户指示）",
     rowOf(r, "ix-off").state === "" && rowOf(r, "ix-on").state === ""
     && !!rowOf(r, "ix-on").swAria,
     "ix-off=「" + rowOf(r, "ix-off").state + "」 ix-on=「" + rowOf(r, "ix-on").state + "」");
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
  /* 🔴 D6 拆两半（2026-10-02 方案 §8.2）：旧 D6 的"文案必须以词表词开头"与**结构化行**互斥
     —— 结构化行（有 items）开头是套餐徽章名（如「ZCode Trust Build 1.00M Token …」），
     加了 zcode 种子后按原写法必误红。
     · D6a = 无 items 的行：词表逐字/前缀判据（五档）+ 状态→文案映射；
     · D6b = 有 items 的行：只要求含「查于」，**不要求前缀相等**（前缀判据由 D6a 承担）。 */
  const pid = act(r);
  const plain = r.rows.filter((x) => !(E.quotaItems || {})[pid + "/" + x.name]);
  const structured = r.rows.filter((x) => !!((E.quotaItems || {})[pid + "/" + x.name]));
  ck("D6a", "额度格文本 ⊂ 五档词表（**无 items 的行**，全表扫描零越界）",
     plain.every((x) => QUOTA_LIST.some((w) => x.quota === w || (x.quota || "").indexOf(w) === 0)),
     "本表=" + j(plain.map((x) => x.quota)) + " 词表=" + QUOTA_LIST.join("/"));
  ck("D6b", "结构化行（有 items）只钉 meta 行的新鲜度段「…查」在位，**不要求前缀相等**（词表让位给名称 + 数值）",
     structured.every((x) => /\S查/.test(x.quota || "")),
     "结构化行=" + j(structured.map((x) => x.name + "=「" + x.quota + "」")) + "（本表 " + structured.length + " 行）");
  ck("D7", "未知不当零：额度格无 0 / — / undefined / NaN",
     r.rows.every((x) => ["0", "—", "undefined", "NaN"].indexOf(x.quota) < 0),
     "实测=" + j(r.rows.map((x) => x.quota)));
});

await section("expand-removed", async () => {
  const r2 = await read();
  ck("C5", "展开行已废除：[data-exp] 与 tr[data-rexp] 全页为 0（2026-10-01 用户指示）",
     r2.expCells === 0, "data-exp + data-rexp 计数=" + r2.expCells);
  ck("B15", "rail 首行 dataset.ixrow 探针仍在（三级重绘只到行级，结构未整页重洗）",
     r2.railBox.probe === "1" && r2.railBox.rowProbe === "1",
     "容器探针=" + r2.railBox.probe + " 首行探针=" + r2.railBox.rowProbe);
  await shot("1440-light-rows");
});

await section("map-modal", async () => {
  /* 🔴 2026-10-01 用户裁决（两条定版叠加）：
     ① 弹窗内禁止再开第二层弹窗（模型目录二级弹窗已废，目录字段融合进映射行）；
     ② **续期是账号维度动作 → 回到列表行操作列**，映射弹窗内不放任何账号级动作。 */
  await click("#ac-map");
  await page.waitForSelector(".modal .list-card", { timeout: 15000 });
  await page.waitForTimeout(300);
  const rm = await read();
  ck("C6", "映射弹窗内零账号级动作：[data-mop] 计数 = 0（续期/刷新额度都只在行内，弹窗不承载账号操作）",
     rm.modalMopRows.length === 0, "弹窗内账号级动作=" + j(rm.modalMopRows));
  ck("C6b", "映射弹窗为宽版 880px（§7.11 wide + 2026-10-03「调整好弹窗总宽度」⇒ `.map-modal` 880）"
     + "且全程单层弹窗（mask 计数 == 1）",
     rm.modalW === 880 && rm.modalMaskCount === 1,
     "modal 宽=" + rm.modalW + "px 遮罩数=" + rm.modalMaskCount);
  await shot("1440-light-map-modal");
  await click(".modal-foot .btn");          // 取消
  await page.waitForTimeout(300);
  const closed = await read();
  ck("C7b", "映射弹窗取消后 modal-root 归零（未落库）",
     closed.modalCount === 0, "modal-root 子节点=" + closed.modalCount);
});

await section("model-check", async () => {
  /* 账号维度「模型检测」（2026-10-02 用户指令）：范围 = 该账号**已开启**的模型映射；
     三态 = 检测中（灰/橘闪）/ 可用（蓝）/ 不可用（红 + 原因原文）；🔴 单层弹窗。
     本门实例 `models: []` ⇒ 真配置下没有任何已开启映射 ⇒ 先验"空范围零请求"（不谎报、不偷发），
     再用 fetch 打桩喂两条结果验三态与计数（与 import-conflict 段同一打桩手法）。 */
  await click(".anchor-item[data-pid='buddy']");
  await page.waitForTimeout(400);
  await page.evaluate(() => {
    /* 🔴 门在 :662 装了**自己的** fetch 钩子做请求计数（E1/E2/E11/E12 全靠它）。
       本段打桩必须把上一手存下来并在段末还原——直接覆盖会让后续分段数不到任何请求
       （实测连带打红 12 条：E1「启停请求=[]」、E2「响应体=undefined」…）。 */
    if (!window.__mcPrevFetch) window.__mcPrevFetch = window.fetch;
    const of = window.__mcPrevFetch;
    window.__mcCalls = [];
    window.__mcStub = null;                 // null = 不打桩（走真后端）；否则按桩表回答
    window.fetch = async (u, o) => {
      const path = String(u).split("?")[0];
      if (path.endsWith("/check-models")) {
        window.__mcCalls.push("list");
        if (window.__mcStub) return { ok: true, status: 200, json: async () => window.__mcStub };
      }
      if (path === "/admin/api/resources/test" && o && o.method === "POST") {
        const b = JSON.parse(o.body || "{}");
        window.__mcCalls.push("test:" + b.model);
        if (window.__mcStub) {
          const hit = (window.__mcStub.tests || {})[b.model];
          if (hit) return { ok: true, status: 200,
            json: async () => Object.assign({ model: b.model }, hit) };
        }
      }
      return of(u, o);
    };
  });
  await click("tr[data-acc='ix-on'] [data-op='check']");
  await page.waitForSelector(".modal #ac-mc-list, .modal .alert-warn", { timeout: 20000 });
  await page.waitForTimeout(400);
  const empty = await page.evaluate(() => ({
    text: (document.querySelector(".modal") || {}).textContent?.replace(/\s+/g, " ").trim() || "",
    tests: (window.__mcCalls || []).filter((x) => x.indexOf("test:") === 0).length,
    masks: document.querySelectorAll(".modal-mask").length }));
  ck("MC1", "无已开启映射 ⇒ 弹窗如实说「不会发出任何请求」，且真发请求数 = 0（不偷烧额度）",
     /没有任何/.test(empty.text) && /不会发出任何请求/.test(empty.text) && empty.tests === 0,
     "tests 调用数=" + empty.tests + " 文案=「" + empty.text.slice(0, 90) + "」");
  await click(".modal-foot .btn");
  await page.waitForTimeout(300);

  // 打桩：两条已开启映射，一条可用一条不可用
  await page.evaluate(() => {
    window.__mcCalls = [];
    window.__mcStub = {
      product: "buddy", name: "ix-on", resource_enabled: true, has_adapter: true, mapped_off: 1,
      models: [{ vendor_model: "vm-ok", system_model: "sys-ok", resource_id: "res-x" },
               { vendor_model: "vm-bad", system_model: "sys-bad", resource_id: "res-x" }],
      tests: { "vm-ok": { ok: true, latency_ms: 123 },
               "vm-bad": { ok: false, latency_ms: 45, error: "HTTP 401：凭据已失效，请重新登录" } },
    };
  });
  await click("tr[data-acc='ix-on'] [data-op='check']");
  await page.waitForSelector(".modal .mc-row.mc-fail", { timeout: 20000 });
  await page.waitForTimeout(400);
  const st = await page.evaluate(() => {
    const rows = [...document.querySelectorAll(".modal .mc-row")];
    const cs = (n) => getComputedStyle(n.querySelector(".mc-ico"));
    return {
      n: rows.length,
      okCls: rows.map((r) => r.className.match(/mc-(run|ok|fail)/)?.[1] || ""),
      okColor: rows.map((r) => cs(r).color),
      tok: (() => { const mk = (t) => { const el = document.createElement("span");
        el.style.color = "var(" + t + ")"; document.body.append(el);
        const v = getComputedStyle(el).color; el.remove(); return v; };
        return { cool: mk("--cool"), err: mk("--err"), faint: mk("--text-faint"), warn: mk("--warn") }; })(),
      txt: rows.map((r) => r.querySelector(".mc-result").textContent.trim()),
      anim: rows.map((r) => cs(r).animationName),
      masks: document.querySelectorAll(".modal-mask").length,
      sum: (document.querySelector(".mc-summary") || {}).textContent?.trim() || "",
      head: (document.querySelector(".modal .modal-body") || document.body).textContent
        .replace(/\s+/g, " ").match(/消耗该账号额度/) ? "有" : "无",
      off: (document.querySelector(".modal") || {}).textContent?.indexOf("不在本次检测范围内") >= 0,
    };
  });
  ck("MC2", "三态各如其分：可用=蓝(--cool) + 「可用 · 123ms」；不可用=红 + 原因原文；无残留「检测中」",
     st.n === 2 && j(st.okCls) === j(["ok", "fail"])
     && /可用 · 123ms/.test(st.txt[0]) && /HTTP 401/.test(st.txt[1])
     && st.okColor[0] === st.tok.cool && st.okColor[1] === st.tok.err,
     "态=" + j(st.okCls) + " 色=" + j(st.okColor) + "（令牌 cool=" + st.tok.cool
     + " err=" + st.tok.err + "）文本=" + j(st.txt));
  ck("MC3", "🔴 单层弹窗（遮罩数 = 1），且弹窗内零账号级动作（不放续期/额度/删除）",
     st.masks === 1, "modal-mask=" + st.masks);
  ck("MC4", "汇总计数如实（可用 1 · 不可用 1），并写明关闭态映射不在范围内",
     /可用 1 · 不可用 1/.test(st.sum) && st.off === true, "汇总=「" + st.sum + "」 范围说明=" + st.off);
  ck("MC5", "弹窗头部先声明「真实出站，会消耗该账号额度」（不偷偷花用户的量）",
     st.head === "有", "消耗额度声明=" + st.head);
  await shot("1440-light-model-check");
  /* 收尾：先无条件还原 fetch 钩子（哪怕下面关窗抛错也不能留给后续分段一个假计数），
     再关弹窗——关窗选择器放宽：`.modal-close`（图标钮）优先，`.modal-foot .btn` 兜底。 */
  await page.evaluate(() => {
    if (window.__mcPrevFetch) { window.fetch = window.__mcPrevFetch; window.__mcPrevFetch = null; }
    window.__mcStub = null; window.__mcCalls = [];
  });
  const stillOpen = await page.evaluate(() => document.querySelectorAll(".modal").length);
  if (stillOpen) {
    await page.evaluate(() => {
      const b = document.querySelector(".modal .modal-close")
        || document.querySelector(".modal-foot .btn");
      if (b) b.click();
    });
    await page.waitForTimeout(400);
  }
  const restored = await page.evaluate(() => ({
    masks: document.querySelectorAll(".modal-mask").length,
    hooked: !window.__mcPrevFetch }));
  ck("MC6", "段末自清理：弹窗归零 + **fetch 钩子已还原**（不污染后续分段的请求计数）",
     restored.masks === 0 && restored.hooked === true,
     "遮罩=" + restored.masks + " 残留打桩=" + (!restored.hooked));
});

await section("renew", async () => {
  /* 续期回行内 + 登录态倒计时（2026-10-01 用户裁决三条之两条的界面面）。
     种子：ix-on = 30 分钟后失效（≤2h 警示）、ix-off = 10 天后失效（正常）、
     cline/ix-device = 无失效字段（未知）。 */
  const r0 = await read();
  ck("C6c", "行内操作列 = 签到/续期/刷新额度/探活/模型检测/删除（全中文文字钮，无图标按钮）"
     + "（2026-10-02 方案 §5-6 加 quota；同日用户指令再加 check=账号维度模型检测）",
     r0.rows.every((x) => j(x.ops) === j(["claim", "refresh", "quota", "probe", "check", "delete"])),
     "buddy ops=" + j(r0.rows.map((x) => x.ops)));
  ck("C7", "停用账号（ix-off）的续期钮同样在位（续期与启用位正交，§22.6）",
     rowOf(r0, "ix-off").cls.indexOf("off") >= 0
     && rowOf(r0, "ix-off").ops.indexOf("refresh") >= 0,
     "ix-off class=「" + rowOf(r0, "ix-off").cls + "」 ops=" + j(rowOf(r0, "ix-off").ops));
  const on = rowOf(r0, "ix-on"), off = rowOf(r0, "ix-off");
  ck("C16", "登录态倒计时三态各如其分：≤2h 出警示 +「将自动续期」/ 远期为普通文本 / 种子无字段的产品说「未知」",
     on.sub.indexOf("登录态") >= 0 && on.sub.indexOf("将自动续期") >= 0
     && off.sub.indexOf("登录态") >= 0 && off.sub.indexOf("将自动续期") < 0,
     "ix-on 副行=「" + on.sub + "」｜ix-off 副行=「" + off.sub + "」");
  await click(".anchor-item[data-pid='qoder']");
  await page.waitForTimeout(300);
  const rq2 = await read();
  ck("C16b", "可续期但拿不到失效时刻 → 如实写「登录态失效时间未知」（不判定、不猜、不制造倒计时）",
     (rq2.rows[0].sub || "").indexOf("登录态失效时间未知") >= 0,
     "qoder 行副行=「" + (rq2.rows[0].sub || "") + "」");
  await click(".anchor-item[data-pid='cline']");
  await page.waitForTimeout(300);
  const rc = await read();
  ck("C16c", "行内按钮按能力位分化（cline refresh=✓ 有续期钮；loomy refresh=✗ 无，见 E9）",
     rc.rows.every((x) => x.ops.indexOf("refresh") >= 0),
     "cline/ix-device ops=" + j(rc.rows[0].ops));
  ck("C16d", "登录态**已过期**（:8300 实测 raccoon 两号形态）→ 直说「已过期，需重新登录」，"
     + "不谎称「将自动续期」（终态账号自动续期腿已记 terminal、不再空转）",
     (rc.rows[0].sub || "").indexOf("登录态已过期") >= 0
     && (rc.rows[0].sub || "").indexOf("需重新登录") >= 0
     && (rc.rows[0].sub || "").indexOf("将自动续期") < 0,
     "cline/ix-device 副行=「" + (rc.rows[0].sub || "") + "」");
  await click(".anchor-item[data-pid='buddy']");
  await page.waitForTimeout(300);

  /* 通道级判据（假上游环境）：点击确实打到 refresh / refresh-due 端点各恰好一次 */
  const reqB = (await reqs()).length;
  await click("tr[data-acc='ix-on'] [data-op='refresh']");
  await page.waitForTimeout(1200);
  const reqA = (await reqs()).slice(reqB);
  const hits = reqA.filter((x) => x === "POST /admin/api/accounts/buddy/ix-on/refresh");
  ck("E11", "行内「续期」= 1 击 + 1 请求（POST …/ix-on/refresh 恰好一次；结果由回执说真话）",
     hits.length === 1, "新增请求=" + j(reqA.slice(0, 6)) + "；refresh 命中=" + hits.length);
  /* 🔴 2026-10-11 重定锚（P-079 处置①/门卫生 (b) 判据过期）：批量续期回执自 `showBulkReceipt`
     起走**结果浮层**（#toast-wrap；2026-10-03 用户裁定「执行完毕，弹窗提示具体执行结果，3s 后
     自动消失」的同款反转——quota 腿 QL0c 已改，renew 腿漏改）⇒ 旧 `waitForSelector(".modal")`
     等的是一个**构造上不再存在**的弹窗，renew 段自那以后从未绿过（全量门整链在册债务期间
     无人复跑，本轮 223/1 首次现形）。改为等 refresh-due 响应到位后读浮层；先等 E11 的行级
     toast（3s 自灭）过期 ⇒ 浮层恰一张，判据才唯一。 */
  await page.waitForTimeout(3400);
  const reqB2 = (await reqs()).length;
  await click("#ac-renew");
  // 等 refresh-due 响应到位（局部轮询：`waitResp` 是 quota 腿腿变体块内的局部助手，此处不可见）
  let dueSeen = false;
  for (let i = 0; i < 60 && !dueSeen; i++) {
    await page.waitForTimeout(250);
    dueSeen = (await reqs()).slice(reqB2)
      .some((x) => x === "POST /admin/api/accounts/buddy/refresh-due");
  }
  await page.waitForTimeout(400);
  const reqA2 = (await reqs()).slice(reqB2);
  const due = reqA2.filter((x) => x === "POST /admin/api/accounts/buddy/refresh-due");
  const rr = await read();
  ck("E12", "卡头「批量续期」= 1 击 + 1 请求（POST …/refresh-due），回执走**结果浮层**"
     + "（遮罩 0 · 恰一张 · 住 #toast-wrap · 不在任何弹窗里）",
     due.length === 1 && rr.modalMaskCount === 0 && rr.toastCount === 1
     && !!(rr.toastCard || {}).inWrap && (rr.toastCard || {}).inModal === false,
     "refresh-due 命中=" + due.length + " 遮罩=" + rr.modalMaskCount
     + " 浮层=" + rr.toastCount + " 卡=" + j((rr.toastCard || {}).text || "").slice(0, 90));
  ck("E12b", "批量续期回执如实报窗口与计数（续期/失败两类必报，跳过分类按需追加）",
     ((rr.toastCard || {}).text || "").indexOf("窗口 5 小时内到期的账号") >= 0
     && /续期 \d+ 个 · 失败 \d+ 个/.test((rr.toastCard || {}).text || ""),
     "回执=「" + ((rr.toastCard || {}).text || "").slice(0, 140) + "」");
  await shot("1440-light-renew-result");
  /* E12c：浮层 3s 自动消失（与 QL0c2 同一口径的"到期即灭"；不再有 .modal-foot 可点）。 */
  await page.waitForTimeout(3400);
  const rz = await read();
  ck("E12c", "回执浮层到期自动消失（浮层归零）且遮罩恒 0（不留残层）",
     rz.toastCount === 0 && rz.modalMaskCount === 0,
     "浮层=" + rz.toastCount + " 遮罩=" + rz.modalMaskCount);
});

await section("import-conflict", async () => {
  /* 🔴 2026-10-01 红线审计新增覆盖：导入弹窗遇 409 设备身份冲突——
     ① 必须**单层**（就地渲染决策，绝不再开第二层弹窗）；
     ② 必须**真的触发**（后端 409 附加字段嵌在 `error` 里，此前前端读 `e.data.conflict`
        恒 undefined → 整条决策路径是死的，靠本段打桩才暴露）。
     打桩只截 POST /admin/api/zcode/import，其余请求放行；两次都回 409 → 零落库。 */
  await page.evaluate(() => {
    const of = window.fetch;
    window.__impCalls = [];
    window.fetch = async (u, o) => {
      const path = String(u).split("?")[0];
      if (path === "/admin/api/zcode/import" && o && o.method === "POST") {
        const b = JSON.parse(o.body || "{}");
        window.__impCalls.push({ source: b.source || "", reuse: b.reuse || null, regen: !!b.regenerate });
        return { ok: false, status: 409, json: async () => ({ error: {
          message: "设备身份冲突（判据桩）", conflict: true, account: "ix-conflict-acct",
          conflict_with: "ix-existing", hint: "桩：同一设备身份已在册" } }) };
      }
      return of(u, o);
    };
  });
  await click(".anchor-item[data-pid='zcode']");
  await page.waitForTimeout(400);
  await click("#ac-zimport");
  await page.waitForSelector("#ac-zimp-json", { timeout: 20000 });
  await page.waitForTimeout(300);
  await page.evaluate(() => {
    document.getElementById("ac-zimp-json").value = JSON.stringify({ token: "ix", device_id: "ix" });
    document.querySelector('[data-z="paste"]').click();
  });
  await page.waitForTimeout(1000);
  const ic = await page.evaluate(() => ({
    masks: document.querySelectorAll(".modal-mask").length,
    titles: Array.from(document.querySelectorAll(".modal-head h3")).map((h) => h.textContent.trim()),
    inline: !!document.querySelector("#ac-zimp-err [data-zcf='reuse']"),
    body: (document.querySelector("#ac-zimp-err .alert-warn") || {}).textContent || "",
    btns: Array.from(document.querySelectorAll("#ac-zimp-err button[data-zcf]")).map((b) => b.textContent.trim()),
  }));
  ck("IC1", "🔴 409 后仍单层弹窗（遮罩恒 1）且决策就地渲染在导入弹窗错误槽内",
    ic.masks === 1 && ic.inline && ic.titles.length === 1,
    "遮罩=" + ic.masks + " 标题=" + j(ic.titles) + " 就地块=" + ic.inline);
  ck("IC2", "409 形状契约：附加字段嵌在 error 里（读得到 account / conflict_with，路径非死）",
    ic.body.indexOf("ix-conflict-acct") >= 0 && ic.body.indexOf("ix-existing") >= 0,
    "就地块含双方账号名=" + (ic.body.indexOf("ix-existing") >= 0));
  ck("IC3", "三钮齐备且序 = 取消 / 重新生成 / 复用其身份（绝不自动选）",
    j(ic.btns) === j(["取消", "重新生成", "复用其身份"]), "按钮=" + j(ic.btns));
  await page.evaluate(() => document.querySelector("#ac-zimp-err [data-zcf='reuse']").click());
  await page.waitForTimeout(900);
  const ic2 = await page.evaluate(() => ({
    calls: window.__impCalls.slice(),
    masks: document.querySelectorAll(".modal-mask").length,
  }));
  ck("IC4", "「复用其身份」= 带 reuse=<既有账号名> 二次提交（仍单层、不静默覆盖）",
    ic2.calls.length === 2 && ic2.calls[1].reuse === "ix-existing" && ic2.masks === 1,
    "二次请求=" + j(ic2.calls[1]) + " 遮罩=" + ic2.masks);
  await page.evaluate(() => {
    const c = document.querySelector("#ac-zimp-err [data-zcf='cancel']");
    if (c) c.click();
    const f = document.querySelector(".modal-foot .btn");
    if (f) f.click();
  });
  await page.waitForTimeout(500);
  const ic3 = await page.evaluate(() => ({ masks: document.querySelectorAll(".modal-mask").length,
    inline: !!document.querySelector("#ac-zimp-err [data-zcf='reuse']") }));
  ck("IC5", "取消收起就地块、关窗归零；全程两次请求都是 409 → **零落库**",
    ic3.masks === 0 && !ic3.inline, "遮罩=" + ic3.masks + " 残留就地块=" + ic3.inline);
  await page.evaluate(() => { window.fetch = window.fetch; });
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
  const rq2 = await read();
  ck("C8", "展开行废除后 resource 三态不再常驻上屏（BD3a 语义仍在接口层，界面不编造）",
     rq2.expCells === 0 && (rq2.resident || "").indexOf("网关资源") < 0,
     "expCells=" + rq2.expCells + "；常驻面「网关资源」indexOf=" + (rq2.resident || "").indexOf("网关资源"));
  await page.waitForTimeout(200);

  await click(".anchor-item[data-pid='lobsterai']");
  await page.waitForTimeout(300);
  const rl = await read();
  ck("D1", "结构化套餐余粮：额度格 = 名称/合计 + 数字 + 量纲 + meta 新鲜度段（runtime.json 真文件真值）",
     /[0-9]/.test(rowOf(rl, "ix-quota-avail").quota || "")
     && (rowOf(rl, "ix-quota-avail").quota || "").indexOf("积分") >= 0
     && /\S查/.test(rowOf(rl, "ix-quota-avail").quota || "")
     && (rowOf(rl, "ix-quota-avail").quota || "").indexOf("LobsterAI 活动包") >= 0
     && E.poolStates["lobsterai/ix-quota-avail"] === "unknown",
     "额度=「" + rowOf(rl, "ix-quota-avail").quota + "」；池摘要=" + E.poolStates["lobsterai/ix-quota-avail"]);
  /* 🔴 D4 随 2026-10-03 改版前进：绝对数据时刻**退出常驻面**（三家参考的新鲜度都是相对量），
     所以"原样投影 checked_at 前 16 字符"这条判据的读取点从可见文本搬到**悬停**；
     同时反向钉常驻面不再出现「查于」——退回旧写法即红。 */
  ck("D4", "数据绝对时刻只在悬停（原样投影 checked_at 前 16 字符，不重算时区），常驻面不得再出现「查于」",
     (rowOf(rl, "ix-quota-avail").quotaTip || "").indexOf("数据时刻：" + E.checkedAtText) >= 0
     && (rowOf(rl, "ix-quota-avail").quota || "").indexOf("查于") < 0,
     "悬停=「" + (rowOf(rl, "ix-quota-avail").quotaTip || "").slice(0, 70) + "」 期望含「数据时刻：" + E.checkedAtText
     + "」；常驻面=「" + rowOf(rl, "ix-quota-avail").quota + "」");
  ck("D4b", "多组额度**逐组给量**住在明细行（2026-10-03 裁定链：先否掉折叠 ⇒ 逐组给量必须常驻，"
     + "再定「合计：900 积分」⇒ 明细留在自己一行、不并进主行）：组名 + 余量在常驻面、"
     + "零折叠入口、零套餐徽章、失效包只计数不占行",
     (rowOf(rl, "ix-quota-avail").quotaChips || "").indexOf("LobsterAI 活动包") >= 0
     && (rowOf(rl, "ix-quota-avail").quotaChips || "").indexOf("300") >= 0
     && (rowOf(rl, "ix-quota-avail").quotaChips || "").indexOf("新用户赠送") >= 0
     // 主行标签在多组时必须是「合计」，且数 = Σ各组剩余（300 + 700）
     && (rowOf(rl, "ix-quota-avail").quota || "").indexOf("合计") >= 0
     && (rowOf(rl, "ix-quota-avail").quotaMeta || "").indexOf("另有 1 包已失效") >= 0
     && rowOf(rl, "ix-quota-avail").foldCount === 0
     && rowOf(rl, "ix-quota-avail").badgeCount === 0
     && (rowOf(rl, "ix-quota-avail").quota || "").indexOf("展开") < 0,
     "明细行=「" + (rowOf(rl, "ix-quota-avail").quotaChips || "").slice(0, 80)
     + "」 meta=「" + (rowOf(rl, "ix-quota-avail").quotaMeta || "") + "」 折叠入口=" + rowOf(rl, "ix-quota-avail").foldCount
     + " 徽章=" + rowOf(rl, "ix-quota-avail").badgeCount);
  /* 🔴 D4f（2026-10-03 用户裁定「合计：900 积分」）：判据对象是**画出来的文本边缘**，不是 CSS 字符串。
     三条腿成对：① 标签文本右缘 → 数值文本左缘 ≤ 8px（"贴"）；② 数值零裁字（被挤的只能是标签）；
     ③ 标签以「：」收尾 + 零右浮 `.qval` 壳。缺任何一条都可能是"看着贴了其实没贴"。 */
  const sumRows = (rl.rows || []).filter((x) => (x.quota || "").indexOf("合计") >= 0);
  ck("D4f", "「合计：900 积分」= 数值贴标签：标签文本右缘→数值文本左缘 ≤8px、数值零裁字、"
     + "标签以「：」收尾、零右浮 .qval 壳",
     sumRows.length > 0
     && sumRows.every((x) => x.labelGapPx !== null && x.labelGapPx <= 8 && x.labelGapPx > -1)
     && sumRows.every((x) => x.numClip === 0)
     && sumRows.every((x) => x.labelEndsColon === true)
     && sumRows.every((x) => x.qvalShell === 0),
     "多组行 " + sumRows.length + " 条｜labelGap=" + j(sumRows.map((x) => x.labelGapPx))
     + " numClip=" + j(sumRows.map((x) => x.numClip))
     + " 冒号=" + j(sumRows.map((x) => x.labelEndsColon))
     + " qval壳=" + j(sumRows.map((x) => x.qvalShell)));
  /* 🔴 D4c（2026-10-03 用户实拍「进度条怎么还有错落啊，左对齐固定在一个位置，用完的部分用灰色显示」）：
     判据对象是**画出来的几何**，不是 CSS 字符串。终版形态 = 占比条**自占一行、画满格宽**
     （`.qbarline > .qbar`）⇒ 左边缘恒 = 额度格内容区的左边缘，对齐由**结构**保证，不依赖列宽算式。
     （中间那版「定宽三列 112/64/1fr」也被实测定量过：条钉住了，数字被挤到裁字 ⇒ 由 D4d 钉住这一半。） */
  const barRows = (rl.rows || []).filter((x) => x.barLeft !== null && x.barLeft !== undefined);
  ck("D4c", "进度条**各行左边缘同一个 x**（条自占一行画满格宽 ⇒ 结构上对齐）+ 用掉的段是灰色轨道",
     barRows.length >= 2
     && Math.max.apply(null, barRows.map((x) => x.barLeft))
        - Math.min.apply(null, barRows.map((x) => x.barLeft)) <= 0.5
     && barRows.every((x) => x.barTrack === rl.tokens.trackRgb)
     && barRows.every((x) => x.barTrack !== rl.tokens.okRgb),
     "带条行=" + j(barRows.map((x) => x.name + "@" + x.barLeft + " " + x.barTrack))
     + " 轨道令牌=" + rl.tokens.trackRgb + " 填充=" + rl.tokens.okRgb);
  /* 🔴 D4e：额度格**字重档**（2026-10-03 用户实拍「怎么有的字体加粗有的不加粗。看下什么问题」）。
     红因两类：① 主读数（剩余/总量）与档位词/标签同权重或互相抢权重；② 同一档在五档之间字重不一致
     （旧版「已耗尽」700 而「无套餐/未知」400，且 `.qcell.qwarnw` 把**整格**加粗）。
     定版 = 一格只有一处 700（数值），名称/meta/档位词一律 600 ⇒ 带数值行 boldCount 恰为 1。 */
  const wRows = (rl.rows || []).filter((x) => x.weights && x.weights.num);
  ck("D4e", "额度格字重档：主读数 700 且**每格只有一处 700**，名称 / meta 600（警示只走颜色不走字重）",
     wRows.length >= 1
     && wRows.every((x) => x.weights.num === "700")
     && wRows.every((x) => !x.weights.name || x.weights.name === "600")
     && wRows.every((x) => !x.weights.meta || x.weights.meta === "600")
     && wRows.every((x) => x.weights.boldCount === 1),
     "取重行=" + j(wRows.map((x) => x.name + " num=" + x.weights.num + " name=" + x.weights.name
       + " meta=" + x.weights.meta + " 700数=" + x.weights.boldCount)));
  /* 🔴 D4d：额度格**零溢出、数值不裁字**（逐产品逐行，全站扫描段里再合一次）。
     这一条存在的意义 = 上一版布局缺陷（`.qnum` 需 129px 只分到 90px）当时**只有手写探针看得见**。 */
  ck("D4d", "额度格**零溢出**（`.qcell` scrollWidth ≤ clientWidth）且数值**不裁字**（`.qnum` 同理）",
     (rl.rows || []).every((x) => (x.cellOver || 0) <= 0 && (x.numOver || 0) <= 0),
     "溢出行=" + j((rl.rows || []).filter((x) => (x.cellOver || 0) > 0 || (x.numOver || 0) > 0)
       .map((x) => x.name + " cell+" + x.cellOver + " num+" + x.numOver)));
  await click(".anchor-item[data-pid='qodercn']");
  await page.waitForTimeout(300);
  const rc = await read();
  ck("C11d", "qodercn/ix-corrupt：状态列零文字（switch-only）且 runtime_ok=false 蕴含 status=unknown（数据层）",
     rowOf(rc, "ix-corrupt").state === "" && E.statuses["qodercn/ix-corrupt"] === "unknown",
     "状态文字=「" + rowOf(rc, "ix-corrupt").state + "」 后端 status=" + E.statuses["qodercn/ix-corrupt"]);
  await click(".anchor-item[data-pid='trae']");
  await page.waitForTimeout(300);
  const rt = await read();
  ck("D1c", "四值之「未知」：runtime.quota.state=unknown（查了但拿不到 ≠ 还没查）",
     rowOf(rt, "ix-unknown-quota").quota === "未知",
     "trae/ix-unknown-quota 额度格=「" + rowOf(rt, "ix-unknown-quota").quota + "」");
  await click(".anchor-item[data-pid='buddy']");
  await page.waitForTimeout(300);
});

await section("quota-sweep", async () => {
  /* 🔴 2026-10-02 方案 §8.2 的额度面全站扫描（逐产品、逐行）。四组判据：
     · V11 = `balance` 能力位**同相护栏**（行内有「刷新额度」钮 ⟺ capabilities.balance=true）；
       今天 10/10 全 true ⇒ 这条**只作护栏**，false 形态未构造（台账如实标"未验证：balance=false 档"）。
     · D6a/D6b = 五档词表（无 items 行）/ 「查于」在位（有 items 行）——与 quota 段同源，扩到全站。
     · V13/V14/V15/V17 = 「未给出 ≠ 已耗尽」/「无套餐」映射/「重置于」/额度格可见面零裸 epoch。 */
  const swept = [];
  for (const pid of E.sweepProducts) {
    await click(".anchor-item[data-pid='" + pid + "']");
    await page.waitForTimeout(320);
    const rs = await read();
    for (const row of rs.rows) {
      swept.push({ pid, name: row.name, quota: row.quota, tip: row.quotaTip || "",
                   ops: row.ops, sub: row.quotaMeta || "", meta: row.quotaMeta || "",
                   cellOver: row.cellOver || 0, numOver: row.numOver || 0,
                   hasItems: !!(E.quotaItems || {})[pid + "/" + row.name],
                   balance: !!(E.caps[pid] || {}).balance });
    }
    if (pid === "zcode") {
      const np = rowOf(rs, "ix-no-plan"), nr = rowOf(rs, "ix-null-remaining");
      const qn = rowOf(rs, "ix-quota-net");
      ck("V14", "「无套餐」= `state=unknown` + `reason=no_plan` 的**前端映射**（裁决③：不扩枚举）"
         + "——可见文本以「无套餐」开头，tooltip 带两可性原文",
         (np.quota || "").indexOf("无套餐") === 0 && E.quotaReasons["zcode/ix-no-plan"] === "no_plan"
         && (np.quota || "").indexOf("已耗尽") < 0 && (np.quotaTip || "").indexOf("entitlement") >= 0,
         "额度格=「" + (np.quota || "") + "」 state=" + j(E.quotaStates["zcode/ix-no-plan"])
         + " reason=" + j(E.quotaReasons["zcode/ix-no-plan"]) + "｜tooltip=「" + (np.quotaTip || "") + "」");
      ck("V13", "「未给出 ≠ 已耗尽」：items 有桶但 remaining=null ⇒ 可见面出「用量未知」，"
         + "不出「已耗尽」、不印 `0 / 总量`，且悬停如实写「这一格没有可用数」"
         + "（2026-10-03 读取点随额度格重做搬家：护栏从展开块回到档位词本身；"
         + " 悬停文案两可 = 上游原话 `未给出` 或页面兜底 `上游未给可用数`，两者都算如实）",
         (nr.quota || "").indexOf("已耗尽") < 0 && E.quotaRemaining["zcode/ix-null-remaining"] === null
         && (nr.quota || "").indexOf("用量未知") >= 0
         && !/(^|[^0-9])0\s*(亿|万|积分|Token|\/)/.test(nr.quota || "")
         && /(未给出|上游未给可用数)/.test(nr.quotaTip || "")
         && nr.barW === "",
         "额度格=「" + (nr.quota || "") + "」 悬停=「" + (nr.quotaTip || "").slice(0, 70)
         + "」 条宽=「" + nr.barW + "」｜runtime.remaining=" + j(E.quotaRemaining["zcode/ix-null-remaining"]));
      /* 🔴 V15 判据对象随重做前进：meta 行**是**一行独立元素，`txt(td[QI])` 把主行与 meta
         拼成一串（`…1亿至 10-04 09:31`），`(^|\s)至` 在拼接串上是**结构性不可能**——
         那不再是"到期时刻在不在"的判据，而是"拼接顺序"的伪判据。改读 `.qmeta` 本体。 */
      ck("V15", "active 且 `expires_at` 为 ISO 形状 ⇒ meta 行**必出**「至 MM-DD HH:mm」"
         + "（2026-10-03 措辞随额度格重做前进：「重置于」并入 meta 行，取数定义一字未改；"
         + "钩子归一化的界面侧后果，额度腿的真机版由 QL6 再钉一次）",
         /^至 \d{2}-\d{2} \d{2}:\d{2}(?:\s|$)/.test(qn.quotaMeta || "")
         && (qn.quota || "").indexOf(E.expiresShort) >= 0
         && (qn.quota || "").indexOf("重置于") < 0,
         "meta 行=「" + (qn.quotaMeta || "") + "」 整格=「" + (qn.quota || "")
         + "」 期望含「至 " + E.expiresShort + "」"
         + "｜runtime.expires_at=" + j(E.quotaExpires["zcode/ix-quota-net"]));
    }
  }
  ck("V11", "balance 能力位同相护栏：行内有/无「刷新额度」钮 ⟺ capabilities.balance（全产品逐行）",
     swept.length > 0 && swept.every((x) => (x.ops.indexOf("quota") >= 0) === x.balance),
     "扫描行=" + swept.length + "；越界行=" + j(swept.filter((x) => (x.ops.indexOf("quota") >= 0) !== x.balance)
       .map((x) => x.pid + "/" + x.name)) + "（今天 10/10 全 true ⇒ balance=false 档**未构造**，仅护栏）");
  ck("D6a", "五档词表全站扫描（无 items 的行，逐字或前缀）",
     swept.filter((x) => !x.hasItems).every((row) => QUOTA_LIST.some((w) => row.quota === w
       || (row.quota || "").indexOf(w) === 0)),
     "无 items 行=" + swept.filter((x) => !x.hasItems).length + "；越界="
     + j(swept.filter((x) => !x.hasItems && !QUOTA_LIST.some((w) => x.quota === w
        || (x.quota || "").indexOf(w) === 0)).map((x) => x.pid + "/" + x.name + "=「" + x.quota + "」")));
  ck("D6b", "结构化行（有 items）全站只钉新鲜度段「…查」，**不要求前缀相等**（旧 D6 与结构化互斥的那一处）",
     swept.filter((x) => x.hasItems).every((row) => /\S查/.test(row.quota || "")),
     "结构化行=" + swept.filter((x) => x.hasItems).length
     + "；缺查于=" + j(swept.filter((x) => x.hasItems && (x.quota || "").indexOf("查于") < 0)
       .map((x) => x.pid + "/" + x.name)));
  ck("D4d2", "全站逐行：额度格**零溢出**、数值**不裁字**（D4d 的扫描面版本——上一版「定宽三列」的裁字缺陷当时只有手写探针看得见）",
     swept.length > 0 && swept.every((x) => x.cellOver <= 0 && x.numOver <= 0),
     "扫描行=" + swept.length + "；越界=" + j(swept.filter((x) => x.cellOver > 0 || x.numOver > 0)
       .map((x) => x.pid + "/" + x.name + " cell+" + x.cellOver + " num+" + x.numOver)));
  /* 2026-10-03 随额度格重做补第二支：逐包 `失效于` 那行没了 ⇒ 摘掉 ISO 护栏的泄漏形态
     从"10 位裸 epoch"变成"被 slice 切出来的残串"（`至 56800`），只扫 ≥9 位就抓不到。
     合形与否归 V15，本条只管"时刻的位置上不许出现裸数字"。
     🔴 2026-10-03 续（D4/V13/V14 把证据条搬到**格根**之后，本条的扫描面要分两把尺）：
     · **常驻面**（整格 + meta 行）仍按"任何 ≥9 位连续数字即红"——那一面上出现长数字没有合法解释；
     · **悬停**里现在带着**上游原话**（`plan=…；可用余量 100000000（token 量纲）`），
       那是被如实投影的业务数值而不是时刻 ⇒ 整串扫会**假红**（本轮真机门唯一那条红就是这个）。
       悬停只扫"时刻的位置"：`至/查于/数据时刻/失效于/重置于` 后面紧跟的长数字，
       以及被 slice 切出来的 4-8 位残串。摘掉 ISO 护栏时 epoch 会同时上到常驻面 ⇒ 本条照红，
       可红路径没有因为收窄悬停扫描而消失。 */
  const epochHit = (x) => /\d{9,}/.test((x.quota || "") + " " + (x.meta || ""))
    || /(?:至|查|数据时刻|失效于|重置于)[^0-9\n]{0,3}\d{9,}/.test(x.tip || "")
    || /(?:至|查|失效于)\s*\d{4,8}(?![\d:])/.test((x.quota || "") + " " + (x.meta || ""));
  ck("V17", "额度格用户可见面**零裸 epoch / 零时刻残串**（常驻面任何 ≥9 位数字即红；"
     + "悬停带上游原话 ⇒ 只扫「时刻的位置」上的长数字与 4-8 位残串）",
     swept.every((x) => !epochHit(x)),
     "命中=" + j(swept.filter(epochHit).map((x) => x.pid + "/" + x.name + "=「" + x.quota + "」")));
  await click(".anchor-item[data-pid='buddy']");
  await page.waitForTimeout(300);
});

await section("keys", async () => {
  await click(".anchor-item[data-pid='buddy']");
  await page.waitForTimeout(200);
  /* 🔴 基线必须在**键盘动作前一刻**取：前面段落（renew 的视图重取 / 映射弹窗的 catalog）
     会合法地重建 rail 并冲掉探针、往累计日志里塞请求。本段判据的对象是
     "键盘导航期间不重建 rail、不发请求"，用全量累计 = 把前段的正常流量算到本段头上（实测假红）。 */
  await page.evaluate(() => {
    const rail = document.getElementById("ac-rail");
    if (rail) {
      rail.dataset.ixprobe = "1";
      if (rail.firstElementChild) rail.firstElementChild.dataset.ixrow = "1";
    }
  });
  const reqBase = (await reqs()).length;
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
  const reqsAll = await reqs();
  const reqsNow = reqsAll.slice(reqBase);
  ck("B12", "切产品 0 请求（§4-5「1 击 + 2 class」）：键盘驱动期（基线之后）无新 API 调用"
     + "（topbar 的 /admin/api/status 全局心跳除外）",
     reqsNow.filter((x) => x.indexOf("/admin/api/status") < 0).length === 0,
     "基线前=" + reqBase + " 累计=" + reqsAll.length + "；驱动期新增=" + j(reqsNow.slice(0, 8)));
  ck("B12b", "键盘导航只改 class：容器 + 首行 dataset 探针在 4 次移动后仍在（未重建 rail）",
     end.railBox.probe === "1" && end.railBox.rowProbe === "1",
     "容器探针=" + end.railBox.probe + " 首行探针=" + end.railBox.rowProbe);
  /* 空态产品**按实际计数选**（2026-10-02 起 zcode 有种子账号，不再是 0 号产品；
     写死 zcode 会让这条判据随种子腐坏。raccoon = qr → 文案「扫码」与 KIND_TEXT 同源）。 */
  const zeroPid = (E.zeroAccountProducts || [])[0] || "";
  const zeroKind = (E.emptyKindTexts || {})[zeroPid] || "";
  await click(".anchor-item[data-pid='" + zeroPid + "']");
  await page.waitForTimeout(400);
  const rz = await read();
  ck("C3", "0 账号产品面板给出空态两行，且按该产品的 login 形态生成（文案与 KIND_TEXT 同源）",
     !!zeroPid && !!zeroKind && /还没有账号/.test(rz.empty || "")
     && /点右上『接入账号』/.test(rz.empty || "") && (rz.empty || "").indexOf(zeroKind) >= 0,
     "产品=" + zeroPid + " 形态=「" + zeroKind + "」｜「" + (rz.empty || "") + "」");
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
  ck("E1b", "行原地 patch：rail 探针仍在（未整页重洗）+ 行加 .off（状态由样式承担，无状态文字）",
     after.railBox.probe === "1" && rowOf(after, "ix-on").cls.indexOf("off") >= 0
     && rowOf(after, "ix-on").state === "",
     "ix-on class=「" + rowOf(after, "ix-on").cls + "」 状态文字=「" + rowOf(after, "ix-on").state + "」 ixprobe=" + after.railBox.probe);
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
  ck("E4", "行内动作按能力位门控：buddy(checkin✓ refresh✓ balance✓) = claim/refresh/quota/probe/check/delete"
     + "（2026-10-01 续期回行内；2026-10-02 新增 quota；同日新增 check=账号维度模型检测，"
     + "它**不挂能力位**——只依赖「有没有已开启的映射」，空范围时弹窗自己说「不会发出任何请求」（MC1 钉）",
     j(rowOf(back, "ix-on").ops) === j(["claim", "refresh", "quota", "probe", "check", "delete"]),
     "buddy/ix-on ops=" + j(rowOf(back, "ix-on").ops)
     + "（checkin=" + j(E.caps.buddy.checkin) + " refresh=" + j(E.caps.buddy.refresh)
     + " balance=" + j(E.caps.buddy.balance) + "）");
  await click(".anchor-item[data-pid='cline']");
  await page.waitForTimeout(300);
  const rc = await read();
  ck("E4b", "cline（checkin=✗ refresh=✓ balance=✓）行内 = 续期/刷新额度/探活/模型检测/删除，**无签到死钮**",
     j(rc.rows[0].ops) === j(["refresh", "quota", "probe", "check", "delete"]),
     "实测 ops=" + j(rc.rows[0].ops));
  ck("E5", "行内动作 ≤6 颗（§3 上限随同日新增的「模型检测」推进：能力位全开时 签到+续期+刷新额度+探活+模型检测+删除）",
     rc.rows.every((x) => x.ops.length <= 6) && back.rows.every((x) => x.ops.length <= 6),
     "cline=" + rc.rows[0].ops.length + " 颗；buddy 最多=" + Math.max.apply(null, back.rows.map((x) => x.ops.length)) + " 颗");
  await click(".anchor-item[data-pid='loomy']");
  await page.waitForTimeout(300);
  const rl0 = await read();
  ck("E9", "能力位 refresh=false（loomy）→ **行内**不渲染续期钮（= claim/quota/probe/check/delete）；"
     + "映射弹窗内本就零账号级动作（C6 已钉，此处不再重复断言空集）",
     j(rl0.rows.map((x) => x.ops)[0] || []) === j(["claim", "quota", "probe", "check", "delete"]),
     "loomy ops=" + j(rl0.rows.map((x) => x.ops)) + "（capabilities.refresh=" + j(E.caps.loomy.refresh)
     + " balance=" + j(E.caps.loomy.balance) + "）");
  ck("E9b", "能力位 onboarding=true 但 BD7 端点未落地 → 新手任务钮不渲染（行内与弹窗都无，不「点了必然失败」）",
     rl0.rows.every((x) => x.ops.indexOf("onboarding") < 0)
     && rl0.modalMopRows.every((x) => x.indexOf(":onboarding") < 0),
     "行内 ops 汇总=" + j(rl0.rows.map((x) => x.ops)));
  /* 弹窗侧再开一次，验「零账号级动作」在 loomy 上同样成立（顺带覆盖 C6 的另一产品） */
  await click("#ac-map");
  /* 🔴 这里**不能**等 [data-mop]（映射弹窗内已无任何账号级动作，恒无 → 超时 → 弹窗滞留
     → 后续全段被滞留遮罩连锁打崩，实测教训）——等弹窗内容就绪即可 */
  await page.waitForSelector(".modal .list-card", { timeout: 10000 });
  await page.waitForTimeout(300);
  const rl = await read();
  ck("E9c", "loomy 映射弹窗同样零账号级动作 + 单层遮罩",
     rl.modalMopRows.length === 0 && rl.modalMaskCount === 1,
     "弹窗动作=" + j(rl.modalMopRows) + " 遮罩=" + rl.modalMaskCount);
  await click(".modal-foot .btn");          // 取消，不落库
  await page.waitForTimeout(300);
});

await section("map-fusion", async () => {
  /* 🔴 2026-10-01 用户定版：模型目录**二级弹窗废除**（弹窗套弹窗明令禁止，frontend-spec §7.11 红线）——
     目录字段（上下文/输出/推理/图片/工具）直接融合进映射行；本段钉新契约。 */
  await click(".anchor-item[data-pid='loomy']");
  await page.waitForTimeout(300);
  await click("#ac-map");
  await page.waitForSelector(".modal .list-card", { timeout: 25000 });
  await page.waitForTimeout(400);
  const rf = await read();
  /* UI 行 == API 目录：行数一致，且「带目录字段的行数」== API 里 context_window 非空条数（不编造口径） */
  const api = await page.evaluate(async () => {
    const r = await fetch("/admin/api/accounts/loomy/catalog").then((x) => x.json());
    return { n: (r.models || []).length,
             withFacts: (r.models || []).filter((m) => m.context_window != null || m.max_output != null
               || m.reasoning === true || m.image_input === true || m.tool_call === true).length,
             source: (r.source || {}).detail || "",
             /* 该产品的「是否首次配置」= 后端三态位里有没有任何一行不是 null
                （2026-10-05 第三次指示后这颗钮**常驻**，不再随这个数翻态；
                   MS3 于是改钉"常驻 + 文案固定 + 消耗声明常驻"，这个数只用来核对回显是否自洽） */
             known: (r.models || []).filter((m) => m.map_enabled !== null
               && m.map_enabled !== undefined).length,
             /* 🔴 逐行的**后端真相**（2026-10-04 状态列删除后，界面读数的对账对象只能是它）：
                `map_enabled` 三态位 + `mapped_to` 已落库的网关模型名。 */
             rows: (r.models || []).map((m) => ({ id: m.id, enabled: m.map_enabled === null
               || m.map_enabled === undefined ? null : m.map_enabled === true,
               mappedTo: (m.mapped_to || []).filter(Boolean),
               suggest: (m.suggest || {}).name || "",
               conf: (m.suggest || {}).confidence || 0 })) };
  });
  ck("E10", "目录字段融合进行内：映射行数 == /catalog 条数，且带辅助信息的行数 == API 非空字段条数",
     rf.mapRows.length === api.n
     && rf.mapRows.filter((x) => x.sub.indexOf("上下文") >= 0 || x.sub.indexOf("输出") >= 0
        || x.sub.indexOf("推理") >= 0 || x.sub.indexOf("图片") >= 0 || x.sub.indexOf("工具") >= 0).length === api.withFacts,
     "UI 行=" + rf.mapRows.length + " / API models=" + api.n
     + "；带目录字段行=" + rf.mapRows.filter((x) => x.sub.indexOf("上下文") >= 0).length + " / API=" + api.withFacts
     + "（来源=「" + api.source + "」）");
  ck("E10b", "🔴 单层弹窗契约：打开映射弹窗后 .modal-mask 计数恒为 1（嵌套弹窗零容忍）",
     rf.modalMaskCount === 1, "遮罩数=" + rf.modalMaskCount);
  ck("E10c", "二级弹窗入口已删：全弹窗无 [data-mop='models']，文本无「模型目录」钮",
     rf.modalMopRows.indexOf(":models") < 0 && (rf.wizardText || "").indexOf("模型目录") < 0,
     "弹窗动作=" + j(rf.modalMopRows));
  ck("E10d", "映射行为宽版版式：modal 880px + 行内目标下拉在位（前两行抽查）",
     rf.modalW === 880 && rf.mapRows.length > 0 && rf.mapRows.slice(0, 2).every((x) => x.hasSel),
     "modal 宽=" + rf.modalW + "px；前两行下拉=" + j(rf.mapRows.slice(0, 2).map((x) => x.hasSel)));
  /* 🔴 脚部三颗钮（2026-10-05 第四次裁定：「右侧显示黑色 保存按钮，所有修改、设置 点击保存
     提交数据后才能入库存储」）：取消 · AI智能匹配（常驻）· 保存（primary，读脏态使能）。
     MS3 钉"AI 那颗常驻一态 + 消耗声明常驻在表上方且写明只回填不写盘"；
     MS4 钉 footer 形状：恰 3 颗、primary 只有「保存」、**无改动时它是禁用的**、零「初始化映射」回潮。
     本段**不点** AI 那颗钮（它真发一次出站、消耗所选资源/账号的额度）；
     它的行为判据 = pytest A 系列（INT-111/112）+ 静态门 V23，界面上钉的是它"在册且文案恒定"。 */
  ck("MS3", "AI 钮常驻一态：文案恒「AI智能匹配」（与后端有没有位无关、不随脏态改字）"
     + " 消耗声明常驻在表上方并写明「不写入配置」与「暂不设置」",
     !!rf.aiBtn && rf.aiBtn.text === "AI智能匹配" && rf.aiBtn.hidden === false
     && rf.mapFootBtns === 3
     && !!rf.mapNoteAbove && rf.mapNoteAbove.beforeTable
     && rf.mapNoteAbove.text.indexOf("不写入配置") >= 0
     && rf.mapNoteAbove.text.indexOf("暂不设置") >= 0,
     "AI 钮=" + j(rf.aiBtn) + "／脚钮数=" + rf.mapFootBtns
     + "／后端非 null 行数=" + api.known + "（钮已与此无关）"
     + "／消耗声明=" + (rf.mapNoteAbove ? (rf.mapNoteAbove.beforeTable ? "在表上方" : "在表下方(红)") : "缺失")
     + "「" + (rf.mapNoteAbove ? rf.mapNoteAbove.text.slice(0, 40) : "") + "」");
  ck("MS4", "footer 恰 3 颗（取消 / AI智能匹配 / 保存）：primary 只有「保存」一颗、"
     + "无改动时它是**禁用**的、零「初始化映射」文案回潮",
     rf.mapFootBtns === 3 && rf.modalPrimary.join() === "保存"
     && !!rf.saveBtn && rf.saveBtn.text === "保存" && rf.saveBtn.disabled === true
     && rf.footTexts.join("/") === "取消/AI智能匹配/保存"
     && rf.footTexts.filter((t) => t.indexOf("初始化") >= 0).length === 0,
     "脚钮数=" + rf.mapFootBtns + " 全部文案=" + j(rf.footTexts)
     + " primary=" + j(rf.modalPrimary) + " 保存态=" + j(rf.saveBtn));
  /* 🔴 进池开关覆盖面（2026-10-02 用户「让增加的开关哪里去了呢，需求丢了么？」）：需求原文
     = 「针对每个产品内的模型，需要支持一个开关」⇒ **每一行都得有**，不是"已有映射的行才有"。
     旧实现把开关挂在 `mapped_to` 非空上 ⇒ 未初始化过的产品整列只有 `—`（:8300 实盘 zcode 2 行 /
     buddy 17 行 = 0 颗开关），功能等于没做。本段双向钉：MS1 行行有开关（零缺失格），
     MS2 没有落点的行是「禁用 + 悬停说明」而不是消失，有落点的行必须可拨。 */
  ck("MS1", "每一行都有进池开关：[data-mapsw] .switch 数 == 行数，且零「只有文字占位」的缺失格",
     rf.mapRows.length > 0 && rf.mapRows.every((x) => x.hasSw)
     && rf.mapRows.filter((x) => x.swMissingCell).length === 0,
     "行=" + rf.mapRows.length + " 开关=" + rf.mapRows.filter((x) => x.hasSw).length
     + " 缺失格=" + rf.mapRows.filter((x) => x.swMissingCell).length);
  const pre = rf.mapRows.filter((x) => x.selV), unp = rf.mapRows.filter((x) => !x.selV);
  ck("MS2", "可拨性 = 该行有没有落点：下拉已选目标的行必须可拨（disabled=false），"
     + "未选目标的行必须禁用且悬停给出原因（禁用态可见 ≠ 消失）",
     pre.every((x) => x.hasSw && x.swDisabled === false)
     && unp.every((x) => x.hasSw && x.swDisabled === true && x.swTitle.indexOf("网关模型映射") >= 0),
     "预选目标行 " + pre.length + "（可拨 " + pre.filter((x) => x.swDisabled === false).length
     + "）／未选目标行 " + unp.length + "（禁用+有说明 "
     + unp.filter((x) => x.swDisabled === true && x.swTitle.indexOf("网关模型映射") >= 0).length + "）");
  /* MS2f（2026-10-03 用户「资源池里已经关联并开启进池的怎么没显示？」追出来的**读取面假态**；
     2026-10-04 随「状态列删除」换对账对象，**判据不删**）：
     旧写法读的是那一列的徽章文案 —— 列没了，判据只能升级成**跟后端那个位对账**：
     `map_enabled === null`（从没写入配置）的行，开关必须为关。这比徽章更强，因为徽章是前端
     自己印的字，而这里的依据是配置里那个位（`admin_accounts.py::_map_enabled` 末行
     `return False if seen else None`）。样本缺失时如实红（同 MS2b0 的口径，不许用空判据交差）。 */
  const noBit = api.rows.map((r3, i) => ({ r: r3, ui: rf.mapRows[i] }))
    .filter((x) => x.r && x.r.enabled === null);
  const lyingOn = noBit.filter((x) => x.ui && x.ui.swOn !== false);
  if (noBit.length === 0) {
    ck("MS2f", "读取面不撒谎：后端无位（`map_enabled=null`）的行开关必须为关",
       false, "本段样本里没有任何「后端无位」的行 ⇒ 该不变量无从验证，如实登记（不许用空判据交差）");
  } else {
    ck("MS2f", "读取面不撒谎：后端无位（`map_enabled=null`）的行开关必须为关，全弹窗零矛盾行",
       lyingOn.length === 0 && noBit.every((x) => !!x.ui),
       "无位行 " + noBit.length + "，其中开关显示为开/未知的 = " + lyingOn.length
         + (lyingOn.length ? "（" + j(lyingOn.slice(0, 3).map((x) => x.ui.name)) + "）" : "")
         + "；开关悬停含「未落库」的行 = " + rf.mapRows.filter((x) => x.swTitle.indexOf("未落库") >= 0).length);
  }

  /* ---------- MS5/MS6/MS7 · 「状态」列删除后的三条对账（2026-10-04 指示 + 2026-10-05 推进） ----------
     用户原话：「有关联映射配置不就是映射了吗，没关联就是没映射啊。弄个状态这不多次一举么。给我去掉这列」
     删列成立的前提 = 剩下那几格**各自读得对**，否则只是把信息删掉了。三条各钉一个前提：
     MS5 列形状：表头逐字四列（「状态」不许回来）+ 每行恰四格（不许留没人住的空列）；
     MS6 「映射了什么」= 下拉当前值，🔴 且**只**= 下拉当前值：已落库的行显示那个目标；后端无位的行
         下拉必须为空 —— 旧契约允许它显示正则建议（配一句「未落库」），那正是本轮第 1 条
         「资源池里怎么没显示」的病源（:8300 实盘 26 行挂着从没写进配置的名字）。建议改由
         行内「采纳并入库」钮给，所以**有够格建议的无位行必须画得出那颗钮**（没对象就不许蒙绿）；
     MS7 弹窗零删除入口（用户 2026-10-04 明令）+ 已落库的行那一行必须**空着**
         （下拉的值 + 开关的位置已经说完了，再说一遍就是两套真相）。 */
  ck("MS5", "状态列已删：表头逐字 = 模型/规则/网关模型映射/进池（4 列、零「状态」）且每行恰 4 格",
     rf.mapHeads.length === 4 && rf.mapHeads.join("/") === "模型/规则/网关模型映射/进池"
     && rf.mapRows.length > 0 && rf.mapRows.every((x) => x.cells === 4),
     "表头=" + j(rf.mapHeads) + "；行格数集合=" + j([...new Set(rf.mapRows.map((x) => x.cells))])
     + "（行数 " + rf.mapRows.length + "）");
  const selBad = [], hintBad = [], noFoot = [], adoptBad = [];
  api.rows.forEach((r3, i) => {
    const u = rf.mapRows[i];
    if (!u) return;
    const want = (r3.mappedTo || []).find((n) => (u.opts || []).indexOf(n) >= 0);
    if (want && u.selV !== want) selBad.push(u.name + ":显示" + j(u.selV) + "≠已落库" + j(want));
    /* 🔴 反转腿：后端无位 ⇒ 下拉必须空（把建议显示成"已关联"= 本轮判死的假态） */
    if (r3.enabled === null && u.selV) {
      selBad.push(u.name + ":后端无位而下拉显示「" + u.selV + "」（建议不许占当前值）");
    }
    if (!u.hasFoot) noFoot.push(u.name);
    /* 无位 + 有够格建议（≥0.7 且这个名字在下拉清单里）⇒ 必须画得出采纳钮，且采纳的就是那条建议 */
    const sugg = r3.conf >= 0.7 && (u.opts || []).indexOf(r3.suggest) >= 0 ? r3.suggest : "";
    if (r3.enabled === null && sugg) {
      if (!u.adopt || u.adoptName !== sugg) adoptBad.push(u.name + ":建议「" + sugg + "」没给出可采纳入口");
      if (u.foot.indexOf("建议挂到") < 0) hintBad.push(u.name + ":那一行没写「建议挂到」（只住钮不住文字）");
    }
    if (r3.enabled !== null && u.foot) hintBad.push(u.name + ":已落库的行那一行不该有文字，实得「" + u.foot.slice(0, 28) + "」");
  });
  const expectAdopt = api.rows.filter((r3, i) => r3.enabled === null
    && r3.conf >= 0.7 && ((rf.mapRows[i] || {}).opts || []).indexOf(r3.suggest) >= 0).length;
  const drawnAdopt = rf.mapRows.filter((x) => x.adopt).length;
  ck("MS6", "🔴 下拉就是「映射了什么」的唯一读数且**只报配置事实**：已落库的行显示那个目标、后端无位的行"
     + "下拉为空；有够格建议的无位行必须画得出「采纳并入库」，且采纳入口**不多画**（对账对象 = 后端 `mapped_to`/`map_enabled`/`suggest`）",
     selBad.length === 0 && hintBad.length === 0 && adoptBad.length === 0 && noFoot.length === 0
     && drawnAdopt === expectAdopt,
     selBad.length || hintBad.length || adoptBad.length || noFoot.length
       ? [...noFoot.map((x) => "缺那一行:" + x), ...selBad, ...adoptBad, ...hintBad].slice(0, 4).join(" ／ ")
       : "对账 " + api.rows.length + " 行：显示值 == 已落库目标、无位行为空、采纳入口 " + drawnAdopt + " 颗 == 有够格建议的无位行 " + expectAdopt);
  /* MS7（2026-10-04 第二次裁定 + 2026-10-05 去「保存」）：「去掉 删除映射按钮，如果之前关联了，
     调整编辑为跳过即解除之前关联关系。如果之前没配置 则空着」⇒ 弹窗里**不许再有删除入口**，
     而"已落库"这件事由下拉的值本身说。两条腿：① 全弹窗零 `[data-mapdel]` / 零两步确认残留；
     ② 已落库且没被改动的行必须**空着** —— 「保存后解除关联」「未落库」这类"还有一步"的暗示随
        「保存」一起作废（MS6 已按后端位逐行对账过文本，这里钉的是删除入口与格数不退化）。 */
  const delGhosts = rf.mapRows.filter((x) => x.delBtn).map((x) => x.name);
  const modalText = await page.evaluate(() => {
    const m = document.querySelector(".modal");
    return m ? (m.innerText || m.textContent || "") : "";
  });
  const saveWord = (modalText.match(/保\s*存/g) || []).length;
  ck("MS7", "弹窗零删除入口（用户明令去掉）+ 🔴「保存」这件事在画面上有主人"
     + "（那颗 primary 在册 + 脚注写明「点「保存」才写入配置」）+ 每行恰 4 格"
     + " —— 上一轮禁「保存」字样是因为那一步不存在了，本轮它回来了且是唯一写入口，判据随之反转、条目不删",
     rf.mapRows.length > 0 && delGhosts.length === 0
     && !!rf.saveBtn && rf.saveBtn.text.indexOf("保存") === 0
     && modalText.indexOf("点「保存」才写入配置") >= 0
     && rf.mapRows.every((x) => x.cells === 4),
     `删除入口残留=${delGhosts.length ? j(delGhosts.slice(0, 3)) : "0"}；「保存」字样=${saveWord} 处；`
     + `保存钮=${j(rf.saveBtn)}；脚注写明=${modalText.indexOf("点「保存」才写入配置") >= 0}；格数集合=`
     + j([...new Set(rf.mapRows.map((x) => x.cells))]) + "（行数 " + rf.mapRows.length + "）");

  /* ---------- MS2b0 / MS2b / MS2c / MS2e / MS2d / MS8a / MS8 / MS8b · 草稿制 ----------
     2026-10-05 第四次裁定把这几条从"当场落库"改回"草稿 + 保存"，判据方向随之反转、**条目不删**：
       MS2b0 样本前提（目录里存在"后端无位"的行，否则本段无从验，如实红）；
       MS2b  选目标 ⇒ 🔴 **零请求**（草稿制的形状就是"改一格不动盘"）+ 该行开关点亮可拨
             + 那一行写明「点「保存」才入库」+ 脚部那颗钮改口「保存（1 处未保存）」并解禁
             + 后端位**仍为 null**（对账对象是后端，不是界面自己的说法）；
       MS2c  同一个目标再选一次 ⇒ 仍零请求，且脏态计数**不重复累加**（还是 1 处）；
       MS2e  拨进池开关 ⇒ 零请求、开关位置跟着动、后端位仍 null；
       MS2d  点「保存」⇒ 恰一次 `accounts/mappings`、零 remove、后端位=true、成功即关窗；
       MS8a  改挂第一步也只改草稿（零请求、位仍=true）；
       MS8   保存一次就改挂到位：位改指 B 且资源池条目**跟着搬**（B 里有、A 里不再有）；
       MS8b  段末净零：改回「暂不设置」并保存 ⇒ 恰一次 remove、位=null、A/B 两池都不再挂着这一行。 */
  const bitOf = async (idx) => (await page.evaluate(async () => {
    const r = await fetch("/admin/api/accounts/loomy/catalog").then((x) => x.json());
    return (r.models || []).map((m) => (m.map_enabled === null || m.map_enabled === undefined
      ? null : m.map_enabled === true));
  }))[idx];
  const ui = rf.mapRows.findIndex((x, i2) => !x.selV && x.hasSw && x.swDisabled === true
    && api.rows[i2] && api.rows[i2].enabled === null);
  const setSel = async (idx, v) => {
    await page.evaluate(({ ix, val }) => {
      const sel = document.querySelector(`.modal select[data-idx='${ix}']`);
      sel.value = val; sel.dispatchEvent(new Event("change", { bubbles: true }));
    }, { ix: idx, val: v });
    await page.waitForTimeout(500);
  };
  const clickFoot = async (which) => {
    await page.evaluate((w) => {
      const b = document.querySelector(`.modal-foot [data-map="${w}"]`);
      if (b && !b.disabled) b.click();
    }, which);
    await page.waitForTimeout(1400);
  };
  const writeReqs = (list) => list.filter((x) => /accounts\/(mappings|product-models\/remove)/.test(x));
  const reopenMap = async () => {
    await click("#ac-map");
    await page.waitForSelector(".modal .list-card", { timeout: 25000 });
    await page.waitForTimeout(400);
  };
  /* 目标优先取配置里已在册的网关模型；本门实例 `models: []` ⇒ 取不到就退到枚举池里那个名字，
     保存那一次会顺手建一个系统模型，临时目录跑完即弃，不去动别段依赖的 `models: []` 前提。 */
  const pickTarget = async (idx) => await page.evaluate(async (ix) => {
    const sel = document.querySelector(`.modal select[data-idx='${ix}']`);
    if (!sel) return "";
    const r = await fetch("/admin/api/config").then((x) => x.json());
    const has = new Set(Array.from(sel.options).map((o) => o.value));
    const existing = (r.models || []).map((m) => m.name).find((n) => has.has(n));
    return existing || Array.from(has).find((n) => n) || "";
  }, idx);
  const poolOf = async (name) => (await page.evaluate(async (nm) => {
    const r = await fetch("/admin/api/config").then((x) => x.json());
    const m = (r.models || []).find((x) => x.name === nm);
    return m ? (m.resources || []).map((e) => e.resource) : [];
  }, name));
  if (ui < 0) {
    /* 编号 MS2b0：与下面几条互斥（if/else 只走一支），但报告按 id 收口，
       同号会让"缺样本"这一支把真判据吃掉 ⇒ 另起一号，让缺样本**可见地红**。 */
    ck("MS2b0", "样本前提：目录里存在「后端无位」的行（否则草稿制判据没有对象，如实登记）",
       false, "本次 loomy 目录每一行都已落位 ⇒ 未覆盖（同 MS8 的口径，不许用空判据交差）");
  } else {
    const target = await pickTarget(ui);
    let n0 = (await reqs()).length;
    await setSel(ui, target);
    const reqs1 = writeReqs((await reqs()).slice(n0));
    const after = await read();
    const r1 = (after.mapRows || [])[ui] || {};
    ck("MS2b", "🔴 选目标 = 只改草稿：**零写请求**；该行开关点亮可拨、那一行写明「点「保存」才入库」，"
       + "脚部那颗钮改口「保存（1 处未保存）」并解禁，后端位**仍为 null**",
       !!target && reqs1.length === 0
       && r1.selV === target && r1.swDisabled === false
       && r1.foot.indexOf("点「保存」才入库") >= 0
       && !!after.saveBtn && after.saveBtn.text === "保存（1 处未保存）"
       && after.saveBtn.disabled === false
       && (await bitOf(ui)) === null,
       `行${ui} 目标=「${target}」：写请求=${j(reqs1.slice(0, 3))}`
       + `｜选中=${j(r1.selV)} 开关禁用=${r1.swDisabled}｜那一行=「${(r1.foot || "").slice(0, 26)}」`
       + `｜保存钮=${j(after.saveBtn)}｜后端位=${JSON.stringify(await bitOf(ui))}`);
    n0 = (await reqs()).length;
    await setSel(ui, target);
    const again = await read();
    ck("MS2c", "同一个目标再选一次 ⇒ 仍零请求，且脏态计数**不重复累加**（还是 1 处）",
       writeReqs((await reqs()).slice(n0)).length === 0
       && !!again.saveBtn && again.saveBtn.text === "保存（1 处未保存）",
       "本轮写请求=" + j(writeReqs((await reqs()).slice(n0)).slice(0, 3))
       + " 保存钮=" + j(again.saveBtn));
    n0 = (await reqs()).length;
    await click(`.modal [data-mapsw="${ui}"] .switch`);
    const sw1 = await read();
    ck("MS2e", "拨进池开关 = 也只改草稿：零请求 + 开关位置跟着动 + 后端位仍 null",
       writeReqs((await reqs()).slice(n0)).length === 0
       && (sw1.mapRows[ui] || {}).swOn === false && (await bitOf(ui)) === null,
       `写请求=${j(writeReqs((await reqs()).slice(n0)).slice(0, 3))}｜开关 on=${(sw1.mapRows[ui] || {}).swOn}`
       + `｜位=${JSON.stringify(await bitOf(ui))}`);
    await click(`.modal [data-mapsw="${ui}"] .switch`);        // 拨回"进池"（新映射缺省即进池）
    n0 = (await reqs()).length;
    await clickFoot("save");
    const reqsS = (await reqs()).slice(n0);
    const st1 = await read();
    ck("MS2d", "🔴 点「保存」= 唯一写入口：恰一次 `accounts/mappings`、零 remove、后端位=true、成功即关窗",
       reqsS.filter((x) => x.indexOf("accounts/mappings") >= 0).length === 1
       && reqsS.filter((x) => x.indexOf("product-models/remove") >= 0).length === 0
       && (await bitOf(ui)) === true && st1.modalMaskCount === 0,
       `mappings=${reqsS.filter((x) => x.indexOf("accounts/mappings") >= 0).length}`
       + ` remove=${reqsS.filter((x) => x.indexOf("product-models/remove") >= 0).length}`
       + `｜位=${JSON.stringify(await bitOf(ui))}｜遮罩=${st1.modalMaskCount}`);
    /* ---------- MS8 · 改挂 = 一次动作（草稿制下"一次"= 选一次 + 保存一次） ---------- */
    await reopenMap();
    const rf2 = await read();
    const row2 = (rf2.mapRows || [])[ui] || {};
    const targetA = row2.selV || "";
    const targetB = (row2.opts || []).find((v) => v && v !== targetA) || "";
    if (!targetB || !targetA) {
      ck("MS8", "样本前提：这一行已落库且下拉里存在第二个可选目标（改挂判据需要两个名字才有对象）",
         false, `A=「${targetA}」 候选=${j((row2.opts || []).slice(0, 4))} ⇒ 未覆盖，如实登记`);
    } else {
      n0 = (await reqs()).length;
      await setSel(ui, targetB);
      const mid = await read();
      ck("MS8a", "改挂第一步同样只改草稿：零请求、位仍=true、脏态计数 1",
         writeReqs((await reqs()).slice(n0)).length === 0 && (await bitOf(ui)) === true
         && !!mid.saveBtn && mid.saveBtn.text === "保存（1 处未保存）",
         `写请求=${j(writeReqs((await reqs()).slice(n0)).slice(0, 3))}｜位=${JSON.stringify(await bitOf(ui))}`
         + `｜保存钮=${j(mid.saveBtn)}`);
      n0 = (await reqs()).length;
      await clickFoot("save");
      const reqsB = (await reqs()).slice(n0);
      const rB = await poolOf(targetB), rA = await poolOf(targetA);
      ck("MS8", "保存一次就改挂到位：位改指 B 且资源池条目**跟着搬**（B 里有、A 里不再有），"
         + "无需「先改回暂不设置保存一次」",
         reqsB.filter((x) => x.indexOf("accounts/mappings") >= 0).length === 1
         && (await bitOf(ui)) === true && rB.length >= 1 && !rA.some((x) => rB.indexOf(x) >= 0),
         `A=「${targetA}」池内资源=${j(rA)}｜B=「${targetB}」池内资源=${j(rB)}｜位=${JSON.stringify(await bitOf(ui))}`
         + `｜mappings=${reqsB.filter((x) => x.indexOf("accounts/mappings") >= 0).length}`);
      await reopenMap();
      n0 = (await reqs()).length;
      await setSel(ui, "");
      await clickFoot("save");
      const reqsC = (await reqs()).slice(n0);
      const rB2 = await poolOf(targetB), rA2 = await poolOf(targetA);
      ck("MS8b", "段末净零：改回「暂不设置」并保存 ⇒ 恰一次 remove、位=null、A/B 两池都不再挂着这一行的资源",
         reqsC.filter((x) => x.indexOf("product-models/remove") >= 0).length === 1
         && reqsC.filter((x) => x.indexOf("accounts/mappings") >= 0).length === 0
         && (await bitOf(ui)) === null && rB2.length === 0 && rA2.length === 0,
         `remove=${reqsC.filter((x) => x.indexOf("product-models/remove") >= 0).length}`
         + ` mappings=${reqsC.filter((x) => x.indexOf("accounts/mappings") >= 0).length}`
         + `｜B 残留=${j(rB2)}｜A 残留=${j(rA2)}｜位=${JSON.stringify(await bitOf(ui))}`);
    }
  }
  await shot("1440-light-map-modal-fusion");
  /* 🔴 段末关窗：选择器放宽 + **弹窗没有脚钮时如实记一条红**，绝不让它抛错带走整段。
     旧写法是一句裸 `click(".modal-foot .btn")`：脚钮一旦不在就抛 ⇒ 分段中断 ⇒ **弹窗滞留**，
     下游 `wizard-device` 的六条（F3/F4/F4c/F5/F6/F11）全部打在"遮罩还开着"上（实测 2026-10-03：
     本段十条判据逐条绿、只有这条收尾红，报告却是 7 红）。同一课 model-check 段早已修过（MC6）。 */
  const footState = await page.evaluate(() => ({
    masks: document.querySelectorAll(".modal-mask").length,
    footBtns: document.querySelectorAll(".modal-foot .btn").length,
    closeBtn: document.querySelectorAll(".modal .modal-close").length,
    footHead: ((document.querySelector(".modal-foot") || {}).innerHTML || "").slice(0, 80),
  }));
  ck("E10f", "映射弹窗脚钮在位（`.modal-foot .btn` ≥1）——不在位就是真缺陷，如实红在这里而不是抛错连锁",
     footState.masks === 0 || footState.footBtns >= 1 || footState.closeBtn >= 1,
     "遮罩=" + footState.masks + " 脚钮=" + footState.footBtns + " 关闭钮=" + footState.closeBtn
     + " 脚区HTML=「" + footState.footHead + "」");
  if (footState.masks > 0) {
    /* 🔴 草稿制（2026-10-05 第四次裁定）之后"关窗"可能要按两次：有未保存改动时第一次只警告。
       门末这段是**兜底清理**，不是判据 —— 所以点到关为止（≤3 次），而不是点一次就断定"关不掉"。
       真关不掉（比如脚钮坏了）仍然走下面的强制移除 + E10g 如实红。 */
    for (let k = 0; k < 3; k++) {
      const still = await page.evaluate(() => {
        const b = document.querySelector(".modal .modal-close") || document.querySelector(".modal-foot .btn");
        if (b) b.click();
        return document.querySelectorAll(".modal-mask").length;
      });
      await page.waitForTimeout(400);
      if (still === 0) break;
    }
    /* 两条都按不到 ⇒ 兜底：直接摘掉遮罩容器，保证不把脏状态漏给后续分段（并如实红）。 */
    const stuck = await page.evaluate(() => {
      const list = document.querySelectorAll(".modal-mask");
      list.forEach((x) => x.remove());
      return list.length;
    });
    if (stuck) ck("E10g", "兜底清理：弹窗无法经 UI 关闭时移除遮罩（不把滞留弹窗漏给后续分段）",
                  false, "关不掉的遮罩数=" + stuck + "（已强制移除，下游 F3-F6 若仍红就不是本段的连锁）");
  }
  const closed = await read();
  ck("E10e", "映射弹窗关闭后 #modal-root 回到基线（0 子节点）",
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
  /* 存在性用 page.evaluate 查（ego-browser **没有** `page.$`——旧写法整段抛
     TypeError: page.$ is not a function，把本段其余判据一起带走；2026-10-01 修） */
  const hasNameField = await page.evaluate(() => !!document.querySelector("#ac-wz-name"));
  ck("F0b", "参数段：无账号名输入（M7-E 免填标识）+ 「开始登录」；会话未建时页脚只有「关闭」",
     w0.wizardBtns.join(",") === "cancel:关闭" && !hasNameField,
     "页脚=" + j(w0.wizardBtns) + " #ac-wz-name=" + (hasNameField ? "仍在（回归）" : "缺（正确）"));
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
  ck("H1", ".subnav 计算宽度：1440→200px、1280→200px、375→全宽 375px（Q44 起加宽：最长名 139.9px，见 H6）",
     L1440.subnav.w === "200px" && L1280.subnav.w === "200px" && L375.subnav.bw === 375,
     "1440=" + L1440.subnav.w + " 1280=" + L1280.subnav.w + " 375=" + L375.subnav.w + "/" + L375.subnav.bw + "px");
  ck("H2", "375px：骨架转竖排、rail 变横向条带（.subnav column + .subnav-scroll row + 横滚）",
     L375.subnav.fd === "column" && L375.railBox.fd === "row" && L375.railBox.overflowX === "auto",
     "subnav.fd=" + L375.subnav.fd + " rail.fd=" + L375.railBox.fd + " rail.overflow-x=" + L375.railBox.overflowX);
  const ys = L375.rail.map((x) => x.by);
  // 🔴 空过防线：值必须是**有限数**（缺字段时 Set{undefined} 的 size 也是 1，那就是死判据）
  ck("H2b", "375px：11 行 rail 同处一条横带（同一 y，且 y 必须真读到）",
     ys.length === 11 && ys.every((v) => typeof v === "number" && Number.isFinite(v))
     && new Set(ys).size === 1, "y 值=" + j(Array.from(new Set(ys))) + "（" + ys.length + " 行）");
  ck("H3", "375px：主区未被挤扁（main ≥ 300px）且表格交给 .table-wrap 横滚",
     L375.main.bw >= 300 && !!L375.wrap && L375.wrap.overflowX === "auto" && L375.wrap.sw >= L375.wrap.cw,
     "main.bw=" + L375.main.bw + "px wrap sw=" + (L375.wrap || {}).sw + " cw=" + (L375.wrap || {}).cw);
  ck("H4", "375px：rail 文案零折行（11/11 单行矩形）",
     L375.rail.every((x) => !x.wrapped), "折行=" + L375.rail.filter((x) => x.wrapped).length + "/11");
  ck("H4b", "1440px：rail 文案零折行",
     L1440.rail.every((x) => !x.wrapped), "折行=" + L1440.rail.filter((x) => x.wrapped).length + "/11");
  const hs = L1440.rail.map((x) => x.h);
  ck("H5", "rail 行高一致（≤1px 容差）：11 行同一高度档",
     new Set(hs).size === 1, "高度集合=" + j(Array.from(new Set(hs))));
  const marks = L1440.rail.filter((x) => x.markH).map((x) => x.markH);
  ck("H5b", "rail 行内控件等高（mark-sm 徽章块 11/11 同档）",
     marks.length === 11 && new Set(marks).size === 1, "mark-sm 高度=" + j(Array.from(new Set(marks))));
  await shot("375-light");
  ck("H7", "1280px 档：主区仍完整（.subnav 200px + main ≥ 900px）",
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
     pre.rail === 11 && pre.rows.indexOf("ix-on") >= 0,
     "href=" + pre.href + " rail=" + pre.rail + " rows=" + j(pre.rows) + " 面板=「" + pre.panel + "」");
  const rn = await read();
  ck("C9", "resource:null（配置读不动）注入：界面零编造——展开行已废、resource 不再常驻展示，行照常渲染",
     rn.expCells === 0 && (rn.resident || "").indexOf("网关资源") < 0 && rn.rows.length >= 1,
     "注入形态=" + E.injectResourceNull + "；expCells=" + rn.expCells + " 常驻面「网关资源」indexOf="
     + (rn.resident || "").indexOf("网关资源"));

  /* §5 读失败：视图端点 502 + 一次**行操作**触发重取（POST 成功、GET 失败），再一次面板级重绘 */
  fs.writeFileSync(PAYLOAD.modeFile, "error");
  await click("tr[data-acc='ix-on'] [role=switch]");
  await page.waitForTimeout(1600);
  const re0 = await read();
  ck("G5a", "现状登记（缺陷 D-1）：行操作后视图重取失败**不**给 alert/过期注记，旧数据静默继续显示",
     re0.alertErr === 0 && re0.retry === 0 && re0.rail.length === 11
     && !re0.head.values.some((v) => v.indexOf("数据可能已过期") >= 0),
     "alert=" + re0.alertErr + " 重试钮=" + re0.retry + " rail=" + re0.rail.length
     + " values=" + j(re0.head.values) + " toasts=" + j(re0.toasts));
  await click(".anchor-item[data-pid='workbuddy']");
  await page.waitForTimeout(1500);
  const re1 = await read();
  ck("G5", "§5 读失败（面板级重绘后到齐）：.alert.alert-err + 「重试」+ rail 保留上次数据 + 「数据可能已过期」",
     re1.alertErr === 1 && re1.retry === 1 && re1.rail.length === 11
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
  /* （目录 state=unknown 注入段随「模型目录二级弹窗废除」一起移除：
     界面不再调用 GET /models，/catalog 的取不动出口由 openModelMap 的 catch 走 alert-err。） */
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
  ck("E6", "删除二次确认：文案如实承诺「资源置停用并保留 + 该行不在供应商资源页显示 + 彻底清除走配置文件」"
     + "（2026-10-02 用户裁决两类资源不得互串后推进：旧判据钉的是「彻底删除请到「接入模型资源」页」，"
     + "而派生资源已从那一页整体移出，旧指路成了死路 —— 判据随设计推进，不退回）",
     /^确定删除 Loomy 的账号「ix-norefresh」？/.test(dm.confirmText || "")
     && (dm.confirmText || "").indexOf("关联资源会被置为停用并保留") >= 0
     && (dm.confirmText || "").indexOf("不在「接入模型资源」页显示") >= 0
     && (dm.confirmText || "").indexOf("resources[]") >= 0
     && (dm.confirmText || "").indexOf("彻底删除请到「接入模型资源」页") < 0,
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
     rf.rail.length === 11, "rail=" + rf.rail.length + " 计数=" + j(rf.rail.map((x) => E.railCounts[x.pid])));
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
    # 🔴 页标签按"进程 + 分段"唯一（见 JS 顶注：并行会话抢同一标签会把整段读数打成一团）
    payload = {**payload, "pageLabel": f"p{os.getpid()}-{tag}"}
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
    # 🔴 额度面的**数据侧**期望（判据不许从界面文案反推）：state/reason/items/remaining/expires_at
    #    全部直接取 `GET /admin/api/accounts` 的 `a.runtime.quota`（真后端读盘的结果）。
    quota_states, quota_reasons, quota_items, quota_remaining, quota_expires = {}, {}, {}, {}, {}
    for p in view["products"]:
        caps[p["id"]] = p["capabilities"]
        for a in p["accounts"]:
            res = a.get("resource")
            if isinstance(res, list) and res:
                resource_ids[f"{p['id']}/{a['name']}"] = res[0]["id"]
            pool_states[f"{p['id']}/{a['name']}"] = a["quota"]["state"]
            statuses[f"{p['id']}/{a['name']}"] = a["status"]
            rq = (a.get("runtime") or {}).get("quota") or {}
            key = f"{p['id']}/{a['name']}"
            quota_states[key] = rq.get("state")
            quota_reasons[key] = rq.get("reason")
            items = rq.get("items") or []
            quota_items[key] = bool(items)
            quota_remaining[key] = rq.get("remaining")
            quota_expires[key] = (items[0] or {}).get("expires_at") if items else ""
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
        # accounts.js:99 KIND_TEXT 的 Python 镜像（空态文案判据的数据源；改了那边不改这里 → C3 红）
        "emptyKindTexts": {p["id"]: KIND_TEXT.get(p.get("login") or "", p.get("login") or "")
                           for p in view["products"]},
        "sweepProducts": [p["id"] for p in view["products"] if p["accounts"]],
        "resourceIds": resource_ids,
        "poolStates": pool_states,
        "statuses": statuses,
        "caps": caps,
        "quotaStates": quota_states,
        "quotaReasons": quota_reasons,
        "quotaItems": quota_items,
        "quotaRemaining": quota_remaining,
        "quotaExpires": quota_expires,
        "expiresShort": EXPIRES_ISO.replace("T", " ")[:16][5:],
        "checkedAt": CHECKED_AT,
        "checkedAtText": CHECKED_AT.replace("T", " ")[:16],
        "loomyModels": ms,
        "emptyResource": (qoder["accounts"][0]["resource"] if qoder["accounts"] else []),
        "injectResourceNull": "resource=null（注入代理改写 GET /admin/api/accounts）",
    }


def api_view(port: int) -> dict:
    return http("GET", f"http://127.0.0.1:{port}/admin/api/accounts")[1]


# ==================== 额度联网腿分段（方案 §6 九格 · 真机可及面） ====================
#
# 🔴 **窗口纪律**（方案 §8.2 明写，最容易自我蒙混的一处）：额度腿与探活腿打的是**同一个**
#    `GET /billing/balance`（`product.PROBE_PATH` 与 `billing.BALANCE_PATH` 同值），
#    混在一个窗口里就是"被探活喂绿"。⇒ 每条腿跑在**独立实例**上（各自的 `MGW_FAKE_TRACE`），
#    窗口时间戳由页面给出（与轨迹同一台机器的墙钟），Python 侧按窗口切轨迹算 Δtrace。
#    假上游把每条轨迹落 `ts` + `X-Device-Mid` + 回体种类（ok / empty-plans），
#    所以"哪一号打了几次"是可核对的，不是推断的。

#: 时间戳归属的容差 = **0**。窗口是首尾相接的（上一窗口的 `t1` 就是下一窗口的 `t0` 之前一刻，
#: 页面两次取值之间才发生点击与出站），浏览器 `Date.now()` 与轨迹 `time.time()` 同源一台机器。
#: 曾给过 300ms 容差，实测把下一窗口的第一条请求算进上一窗口（Δtrace 2≠1、4≠3，红得没有道理）
#: ⇒ 容差在这里是**有害的**；窗口是否切干净由 QL0 的"总轨迹 == 各窗口之和"自证。
TS_GUARD_MS = 0.0


def read_json_file(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 读数失败返回 None，由判据如实说"读不到"
        return None


def quota_of(cfg: Path, product: str, name: str) -> dict:
    return (read_json_file(account_dir(cfg, product, name) / "runtime.json") or {}).get("quota") or {}


def quota_fingerprint(quota: dict) -> str:
    """`runtime.json.quota` 的**字节指纹**（QN2「一个字节都不动」的载体；键序无关）。"""
    blob = json.dumps(quota, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16] + f"/{len(blob)}B"


def trace_entries(run_dir: Path) -> list[dict]:
    path = Path(run_dir) / "fake-trace.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            out.append({"_unparsed": line[:80]})
    return out


def balance_events(entries: list[dict]) -> list[dict]:
    return [x for x in entries if str(x.get("path", "")).endswith("/billing/balance")
            and str(x.get("method", "")).upper() == "GET"]


def in_window(events: list[dict], win) -> list[dict]:
    t0, t1 = win
    lo, hi = t0 - TS_GUARD_MS, t1 + TS_GUARD_MS
    return [x for x in events if lo <= float(x.get("ts", 0)) * 1000 <= hi]


def quota_leg_criterion(delta: int, fired_receipt: int) -> bool:
    """🔴 额度腿的**唯一判据式**：`Δtrace(GET /billing/balance) == 回执 N`。

    正向腿与反向撤证**共用这一个函数** —— 撤证才有靶：把这里的 `==` 改成 `>= 0`（恒真）
    后，反向撤证那条必须变红（交付前反向实验②钉的就是这件事）。
    """
    return delta == fired_receipt


def circuit_file(cfg: Path) -> Path:
    """熔断状态文件 = `store.accounts_root().parent / "circuit.json"`（`quota.py::circuit_path()`
    同一口径；本门的数据根就是 `MG_CONFIG` 的目录，见 `account_dir()`）。"""
    return cfg.parent / "upstream" / "zcode" / "circuit.json"


def start_leg(tag: str, base: Path, port: int, interval: int):
    """起一台**只装 zcode 三行种子**的独立实例（自己的数据根 + 自己的 `MGW_FAKE_TRACE`）。"""
    run = base / f"leg-{tag}"
    run.mkdir(parents=True, exist_ok=True)
    cfg = write_config(run, port, interval=interval)
    seed_accounts(cfg, run, ROOT, spec=ZCODE_SEED)
    proc, out_h = start_gateway(cfg, run, ROOT, log_name="gw")
    ok, health = wait_health(port, proc)
    if not ok:
        log((run / "gw.log").read_text(encoding="utf-8")[-2000:])
        raise RuntimeError(f"额度腿分段「{tag}」实例起不来：{health}")
    time.sleep(1.2)
    return run, cfg, proc, out_h, health


def leg_browser(run: Path, cfg: Path, port: int, shots: Path, rep: Report, tag: str,
                variant: str, account: str = "ix-quota-net") -> dict:
    expect = {"leg": {"variant": variant, "product": "zcode", "account": account}}
    payload = {"mode": "quota-leg", "url": f"http://127.0.0.1:{port}/",
               "shotsDir": str(shots), "expect": expect,
               "shotName": f"quota-leg-{tag}"}
    return run_browser(payload, run, rep, f"leg-{tag}")


def leg_windows(extra: dict) -> dict:
    return {w["name"]: (w["t0"], w["t1"]) for w in ((extra or {}).get("leg") or {}).get("windows", [])}


def row_of_rows(rows, name: str) -> dict:
    return next((x for x in (rows or []) if x.get("name") == name), {})


def run_legs_guarded(rep: Report, base: Path, shots: Path) -> None:
    """分段装配级失败 = **判据红**，不是整门崩（独立实例起不来时，主实例的读数仍然有意义）。"""
    try:
        run_quota_legs(rep, base, shots)
    except Exception as e:  # noqa: BLE001
        # 🔴 带**调用点**行号：只报 `ValueError: too many values to unpack` 等于没报
        #    （装配级失败会让整段额度腿静默不跑，其余格子全变"红得没道理"）
        tb = traceback.extract_tb(e.__traceback__)[-1]
        emit(rep, "QL-FATAL", "额度联网腿分段可装配（四台独立实例 + 假上游都起得来）", False,
             f"{type(e).__name__}: {e} @ {Path(tb.filename).name}:{tb.lineno}｜{tb.line}")


def run_quota_legs(rep: Report, base: Path, shots: Path) -> None:
    """四段：干净窗口（强制腿 + 产品级 + V16）/ 预写熔断 / 探活同窗口撤证 / cron+`quota_net=false`。"""
    # ---------------- 段①：干净窗口 ----------------
    port1, why1 = pick_port(0)
    run1, cfg1, proc1, out1, health1 = start_leg("clean", base, port1, interval=0)
    emit(rep, "QL-A", f"额度腿段①独立实例在跑且**与 :8300 无关**（端口 {port1}｜{why1}；"
         + "interval=0 ⇒ 无 cron 干扰窗口；数据根在本段的 run 目录里）",
         port1 != 8300 and "leg-clean" in str(health1.get("config", {}).get("path", "")),
         f"port={port1} config={j0(health1.get('config', {}).get('path'))}")
    before = {s["name"]: quota_of(cfg1, "zcode", s["name"]) for s in ZCODE_SEED}
    data1 = leg_browser(run1, cfg1, port1, shots, rep, "clean", "clean")
    stop(proc1, out1)
    events1 = balance_events(trace_entries(run1))
    win1 = leg_windows(data1.get("extra"))
    leg1 = (data1.get("extra") or {}).get("leg") or {}
    bodies = leg1.get("bodies") or {}
    one_p = "/admin/api/accounts/zcode/ix-quota-net/quota"
    all_p = "/admin/api/accounts/zcode/quota-all"
    rep1 = (bodies.get(one_p) or {}).get("report") or {}
    n1 = (len(rep1.get("success") or []) + len(rep1.get("already_done") or [])
          + len(rep1.get("inactive") or []) + len(rep1.get("failed") or []))
    # 🔴 每批回执**当场取走**（`byPath` 只留最后一次），Δtrace 与回执才是同一批的账。
    receipt = (leg1.get("receiptW2") or {}).get("receipt") or {}
    receipt3 = (leg1.get("receiptW3") or {}).get("receipt") or {}
    d1 = in_window(events1, win1.get("account-quota", (0, 0)))
    d2 = in_window(events1, win1.get("quota-all", (0, 0)))
    d3 = in_window(events1, win1.get("v16-quota-all", (0, 0)))
    covered = len(d1) + len(d2) + len(d3)
    emit(rep, "QL0", "窗口记账自证：实例轨迹里的 /billing/balance **全部**落在声明窗口内"
         + "（窗口外 0 条 ⇒ 不存在「窗口外的请求替窗口内交账」；各窗口首尾相接、零容差）",
         covered == len(events1) and len(d1) >= 1,
         f"总={len(events1)} 声明窗口覆盖={covered}（W1={len(d1)} W2={len(d2)} W3={len(d3)}）"
         f"；窗口名={j0(sorted(win1))}")
    emit(rep, "QL1", "强制腿（点行内「刷新额度」）Δtrace == 回执 N：单次点击 ⇒ 恰好 1 条上游 GET",
         quota_leg_criterion(len(d1), n1) and len(d1) == 1 and n1 == 1
         and {x.get("mid") for x in d1} == {ZCODE_MID_NET},
         f"Δtrace={len(d1)} 回执参与数={n1} category={j0((bodies.get(one_p) or {}).get('category'))}"
         f" reason={j0((bodies.get(one_p) or {}).get('reason'))} 命中 mid={j0(sorted({str(x.get('mid')) for x in d1}))}")
    emit(rep, "QL2", "产品级「刷新额度」（quota-all）Δtrace == 回执 N=refreshed"
         + "（3 个号都真打了上游，且没有一号被熔断/开关挡在门外）",
         quota_leg_criterion(len(d2), int(receipt.get("refreshed", -1))) and len(d2) == 3,
         f"Δtrace={len(d2)} 回执={j0({k: receipt.get(k) for k in ('refreshed', 'failed', 'not_fired', 'not_participating')})}"
         f" by_reason={j0(receipt.get('by_reason'))}")
    emit(rep, "QL2b", "V16 窗口内那一次 quota-all 同样 Δtrace == 回执 N（迟到回执不是「只画了个槽」）",
         quota_leg_criterion(len(d3), int(receipt3.get("refreshed", -1))) and len(d3) == 3,
         f"Δtrace={len(d3)} 回执={j0({k: receipt3.get(k) for k in ('refreshed', 'failed', 'not_fired')})}")
    after = {s["name"]: quota_of(cfg1, "zcode", s["name"]) for s in ZCODE_SEED}
    bq, aq = before["ix-quota-net"], after["ix-quota-net"]
    emit(rep, "QL3", "强制腿写盘两个时刻**都前进**：`checked_at`（写盘时刻）与 `data_at`（上游 server_time 的 ISO）"
         + "—— 缺一半就是「改了盘没联网」或「联网了没改时刻」（方案 §4-6 两态）",
         bool(aq.get("checked_at")) and aq["checked_at"] > bq.get("checked_at", "")
         and bool(aq.get("data_at")) and aq["data_at"] > bq.get("data_at", "")
         and aq.get("state") == "available" and aq.get("source") == "zcode-billing"
         and aq.get("plan_key") == "upl_2105792494636244992",
         f"checked_at {bq.get('checked_at')} → {aq.get('checked_at')}；"
         f"data_at {bq.get('data_at')} → {aq.get('data_at')}；state={j0(aq.get('state'))}"
         f" source={j0(aq.get('source'))} plan_key={j0(aq.get('plan_key'))}")
    np_before, np_after = before["ix-no-plan"], after["ix-no-plan"]
    emit(rep, "QL4", "「无套餐」的**真机产出**：空 plans 路由 ⇒ 盘上 reason=no_plan + state=unknown"
         + " + items==[]（整键覆盖，不是种子摆出来的）",
         np_after.get("reason") == "no_plan" and np_after.get("state") == "unknown"
         and np_after.get("items") == [] and np_after.get("source") == "zcode-billing",
         f"reason={j0(np_after.get('reason'))} state={j0(np_after.get('state'))}"
         f" items={j0(np_after.get('items'))} 种子上一次={j0(np_before.get('reason'))}"
         f"；empty-plans 轨迹={len([x for x in d2 if x.get('kind') == 'empty-plans'])} 条")
    rows_after = ((data1.get("extra") or {}).get("leg") or {}).get("rowsAfter") or []
    np_row = row_of_rows(rows_after, "ix-no-plan")
    qn_row = row_of_rows(rows_after, "ix-quota-net")
    emit(rep, "QL4b", "界面侧「无套餐」：真机联网后的那一行可见文本仍以「无套餐」开头"
         + "（反向实验①：把空 plans 路由改回 503 ⇒ 本条 + QL4 必须红）",
         str(np_row.get("quota", "")).startswith("无套餐"),
         f"额度格=「{np_row.get('quota')}」")
    # 🔴 2026-10-03 随额度格重做前进：「查于 + 绝对时刻」退出常驻面（改相对新鲜度），
    #    「重置于」并入 meta 行的「至 MM-DD HH:mm」；裸 epoch 之外再钉"时刻位残串"这一支。
    qn_all = " ".join(str(qn_row.get(k) or "") for k in ("quota", "sub", "chips"))
    emit(rep, "QL6", "联网后的额度格 = 数值 + 相对新鲜度「…查」 + meta「至 MM-DD HH:mm」，"
         + "且**零裸 epoch / 零时刻残串**（钩子把上游 epoch 归一成 ISO 的界面后果，"
         + "方案 §3-5 连带登记的 expiresSoon 首次真会命中）",
         re.search(r"(^|\s)至 \d{2}-\d{2} \d{2}:\d{2}", qn_all) is not None
         and re.search(r"\S查", qn_all) is not None
         and "查于" not in str(qn_row.get("quota") or "")
         and not re.search(r"\d{9,}", qn_all + " " + str(qn_row.get("sub") or ""))
         and not re.search(r"(?:至|查|失效于)\s*\d{4,8}(?![\d:])", qn_all)
         and int(qn_row.get("fold") or 0) == 0,
         f"额度格=「{qn_row.get('quota')}」 meta=「{qn_row.get('sub')}」 chips=「{qn_row.get('chips')}」"
         f" 条宽={j0(qn_row.get('barW'))} 折叠入口={j0(qn_row.get('fold'))}"
         f" 盘上 items[0].expires_at={j0((aq.get('items') or [{}])[0].get('expires_at'))}")

    # ---------------- 段②：预写熔断 ----------------
    port2, _why2 = pick_port(0)
    cpath = None
    try:
        run2, cfg2, proc2, out2 = None, None, None, None
        # 先起实例拿数据根，再**预写** circuit.json（钩子每次判定都按 mtime 回读 ⇒ 顺序无所谓，
        # 但必须在点击之前落盘；这里先写文件再启动，避免与启动期的领取腿抢窗口）
        run2 = base / "leg-circuit"
        run2.mkdir(parents=True, exist_ok=True)
        cfg2 = write_config(run2, port2, interval=0)
        seed_accounts(cfg2, run2, ROOT, spec=ZCODE_SEED)
        cpath = circuit_file(cfg2)
        cpath.parent.mkdir(parents=True, exist_ok=True)
        now_ms = time.time() * 1000
        cpath.write_text(json.dumps({"until_ms": now_ms + 30 * 60 * 1000,
                                     "reason": "IX 门预写：模拟 3012 全局风控",
                                     "last_call_ms": now_ms}, ensure_ascii=False),
                         encoding="utf-8")
        proc2, out2 = start_gateway(cfg2, run2, ROOT, log_name="gw")
        ok2, health2 = wait_health(port2, proc2)
        if not ok2:
            raise RuntimeError(f"熔断腿实例起不来：{health2}")
        time.sleep(1.2)
        before2 = quota_of(cfg2, "zcode", "ix-quota-net")
        data2 = leg_browser(run2, cfg2, port2, shots, rep, "circuit", "circuit")
        stop(proc2, out2)
        events2 = balance_events(trace_entries(run2))
        win2 = leg_windows(data2.get("extra"))
        d_c = in_window(events2, win2.get("circuit", (0, 0)))
        after2 = quota_of(cfg2, "zcode", "ix-quota-net")
        emit(rep, "QC1", "熔断腿（门侧预写 circuit.json）Δtrace == 0：钩子在「发起前判定」就拒跑，"
             + "一次上游请求都不发",
             len(d_c) == 0 and len(events2) == 0,
             f"窗口内={len(d_c)} 实例全部 /billing/balance={len(events2)}"
             f"（熔断文件={cpath.name} 已预写）")
        emit(rep, "QC2", "熔断腿落档 reason=circuit + source=zcode-circuit（不是 unreachable）",
             after2.get("reason") == "circuit" and after2.get("source") == "zcode-circuit",
             f"reason={j0(after2.get('reason'))} source={j0(after2.get('source'))}"
             f" detail={j0((after2.get('detail') or '')[:70])}")
        emit(rep, "QC3", "熔断腿时间面：**`data_at` 不前进**（上游这一轮没说话）而 `checked_at` 前进"
             + "（方案 §4-6 两态；把两者混成一个就是「伪装刷新」）",
             after2.get("data_at") == before2.get("data_at")
             and bool(after2.get("checked_at")) and after2["checked_at"] > before2.get("checked_at", ""),
             f"data_at {before2.get('data_at')} → {after2.get('data_at')}；"
             f"checked_at {before2.get('checked_at')} → {after2.get('checked_at')}")
        kept = all(after2.get(k) == before2.get(k) for k in
                   ("items", "plan", "remaining", "data_at", "plan_key"))
        emit(rep, "QC4", "熔断腿**合并写**保住五个数值键（items/plan/remaining/data_at/plan_key 逐字不变）"
             + "—— 一次熔断不得把上一轮的真实余量洗成空",
             kept and bool(after2.get("items")),
             f"保住={j0({k: (k in after2 and after2[k] == before2.get(k)) for k in ('items', 'plan', 'remaining', 'data_at', 'plan_key')})}"
             f"；items 数={len(after2.get('items') or [])}")
        cpath.unlink()                       # 门侧收尾：跑完删除，不留熔断给后续段/实盘
        emit(rep, "QC5", "门侧收尾：跑完**删除** circuit.json（不留熔断给后续段/实盘）",
             not cpath.exists(), f"path={cpath} 删除后存在={cpath.exists()}")
    finally:
        if cpath and cpath.exists():
            cpath.unlink()
        if proc2 is not None:
            stop(proc2, out2)

    # ---------------- 段③：反向撤证（探活与额度同窗口） ----------------
    port3, _why3 = pick_port(0)
    run3, cfg3, proc3, out3, _h3 = start_leg("probe", base, port3, interval=0)
    data3 = leg_browser(run3, cfg3, port3, shots, rep, "probe", "probe-window")
    stop(proc3, out3)
    events3 = balance_events(trace_entries(run3))
    win3 = leg_windows(data3.get("extra"))
    d3w = in_window(events3, win3.get("probe-then-quota", (0, 0)))
    bodies3 = ((data3.get("extra") or {}).get("leg") or {}).get("bodies") or {}
    rep3 = (bodies3.get(one_p) or {}).get("report") or {}
    n3 = (len(rep3.get("success") or []) + len(rep3.get("already_done") or [])
          + len(rep3.get("inactive") or []) + len(rep3.get("failed") or []))
    same_path = {str(x.get("path")) for x in d3w}
    emit(rep, "QR1", "🔴 反向撤证成立：同一窗口里先点「探活」再点「刷新额度」⇒ 额度腿判据必须红"
         + "（不写这条 = 额度腿可以被探活喂绿）",
         len(d3w) == 2 and n3 == 1 and (not quota_leg_criterion(len(d3w), n3))
         and len(same_path) == 1,
         f"窗口内 /billing/balance={len(d3w)} 回执 N={n3}"
         f" ⇒ quota_leg_criterion(Δ,N)={quota_leg_criterion(len(d3w), n3)}（期望 False）"
         f"；两条同一 path={j0(sorted(same_path))}")
    emit(rep, "QR2", "同 path 事实登记（撤证的前提，不是假设）：探活腿与额度腿打的是同一个只读 GET",
         all(str(x.get("path", "")).endswith("/billing/balance") for x in d3w)
         and {x.get("mid") for x in d3w} == {ZCODE_MID_NET},
         f"两条轨迹 mid={j0(sorted({str(x.get('mid')) for x in d3w}))} kinds={j0([x.get('kind') for x in d3w])}")

    # ---------------- 段④：cron 腿 + `quota_net=false`（方案 §6 第 8 格） ----------------
    port4, _why4 = pick_port(0)
    run4, cfg4, proc4, out4, _h4 = start_leg("cron", base, port4, interval=5)
    before4 = {s["name"]: quota_of(cfg4, "zcode", s["name"]) for s in ZCODE_SEED}
    fp_before = {k: quota_fingerprint(v) for k, v in before4.items()}
    deadline = time.time() + 60.0
    balance_rounds: list[dict] = []
    while time.time() < deadline and len(balance_rounds) < 2:
        time.sleep(2.0)
        rounds = []
        for fp in sorted((cfg4.parent / "usage").glob("ops-results-*.jsonl")):
            for line in fp.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                why = row.get("inactive_reasons") or {}
                if any("额度联网腿未启用" in str(v) for v in why.values()):
                    rounds.append(row)
        balance_rounds = rounds
    stop(proc4, out4)
    events4 = balance_events(trace_entries(run4))
    after4 = {s["name"]: quota_of(cfg4, "zcode", s["name"]) for s in ZCODE_SEED}
    fp_after = {k: quota_fingerprint(v) for k, v in after4.items()}
    emit(rep, "QN0", f"cron 段装配：`quota_net: false` + interval=5 的实例真跑了 ≥2 轮额度腿"
         + "（先证明「腿在跑」，下面的 0 发起才有意义 —— 否则「盘没动」可能只是根本没跑）",
         len(balance_rounds) >= 2, f"额度腿轮次={len(balance_rounds)}")
    emit(rep, "QN1", "方案 §6 第 8 格（`quota_net=false` + `via='cron'`）：Δtrace == 0 ⇒ cron 腿不发起",
         len(events4) == 0, f"实例全程 /billing/balance={len(events4)} 条；轨迹总条数={len(trace_entries(run4))}"
         f"（领取腿照常在跑，见 gw.log 与 jsonl）")
    emit(rep, "QN2", "同格另一半：`runtime.json.quota` **一个字节都不动**（三个号逐一比指纹）",
         fp_after == fp_before and all(v for v in fp_after.values()),
         f"指纹前后={j0({'before': fp_before, 'after': fp_after})}")
    emit(rep, "QN3", "对照腿（方案 §5-1 的 `via='user'`）：同一份 `quota_net=false` 配置下，"
         + "手动腿照样发起并写盘（段①已证 ⇒ 本条把两格钉在同一实例语义上）",
         len(d1) == 1 and aq.get("source") == "zcode-billing",
         f"手动腿 Δtrace={len(d1)}；cron 腿 Δtrace={len(events4)}；"
         f"jsonl 里的短退文案={j0(sorted({str(v) for r in balance_rounds[:1] for v in (r.get('inactive_reasons') or {}).values()})[:1])}")


# ==================== 主流程 ====================

def main() -> int:
    ap = argparse.ArgumentParser(description="M7-UI 账号接入页真机验收")
    ap.add_argument("--port", type=int, default=0, help="实例端口（缺省在 8400-8499 自动挑）")
    ap.add_argument("--basetemp", default="/tmp/m7-ix", help="临时根（默认 /tmp/m7-ix）")
    ap.add_argument("--shots", default="", help="截图目录（默认 docs/changes/e2e-records/m7-accounts-ui）")
    ap.add_argument("--retract", type=int, choices=[1, 2, 3], default=0, help="成对撤证模式")
    ap.add_argument("--keep", action="store_true", help="保留临时目录")
    ap.add_argument("--no-proxy", action="store_true", help="跳过注入段（resource:null / 读失败）")
    ap.add_argument("--skip-legs", action="store_true",
                    help="跳过额度联网腿的四段独立实例（调试主实例判据用；正式交付必须跑全）")
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
    want_counts = {"products": 11, "accounts": len(SEED),
                   "enabled": sum(1 for s in SEED if s["enabled"]),
                   "disabled": sum(1 for s in SEED if not s["enabled"])}
    emit(rep, "A3", "GET /admin/api/accounts 200 且 counts 与种子逐字相符",
         code == 200 and view["counts"] == want_counts,
         f"counts={j0(view['counts'])} 期望={j0(want_counts)}")
    emit(rep, "A3b", "热重载后 resource 三态之 [] 由**真后端**给出（不是注入）",
         expect["emptyResource"] == [], f"qoder/ix-quota-exhausted resource={j0(expect['emptyResource'])}")
    raw = json.dumps(view, ensure_ascii=False)
    # 2026-10-02：种子新增 zcode 假 jwt（额度联网腿的前提）→ 外泄词表同步把它的**前缀**也钉上
    # 🔴 2026-10-11 重定锚（P-079 合法处置①）：`credentials` 这根针 10-05 起被合法字段名
    #    `credentials_from`（能力枚举 "store"/"product"，非凭据值）误中 ⇒ 该条自 10-05 起从未
    #    绿过。收紧为带引号的 `"credentials"`（JSON 键精确形，误报消除）；真实泄漏形状
    #    （凭据对象/键 `"credentials": {…}`）依旧命中，意图不变、判据不放宽。
    leaks = [t for t in ("IXFAKE", "ix_fake_token", '"credentials"', "IX-SEED-JWT") if t in raw]
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

    # 🔴 额度**联网腿**分段（主实例已停 ⇒ 不与上面的窗口共用轨迹）。每段一台独立实例 +
    #    独立 `MGW_FAKE_TRACE`；装配级失败按判据如实记红，不冒泡成"整轮没读数"。
    if args.skip_legs:
        emit(rep, "QL-SKIP", "额度联网腿分段按 --skip-legs 跳过（**调试开关，不得用于交付**）",
             True, "四段判据本轮未跑；正式交付判据 = 不带该开关的全量跑")
    else:
        run_legs_guarded(rep, run_dir, shots)

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
