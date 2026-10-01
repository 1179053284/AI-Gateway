"""ZCode 导入兼容 + 小店（YouYu Shop）代理（Q31，2026-10-01；§22.7 端点纪律的 zcode 私有面）。

端点全集::

    GET  /admin/api/zcode/import/sources        面板 / switch 两个来源的扫描结果（含已导入判据）
    POST /admin/api/zcode/import                {source, account?, payload?, reuse?, regenerate?}
    GET  /admin/api/zcode/shop/items            小店库存（代理 {base}/api/list）
    POST /admin/api/zcode/shop/buy              下单（代理 {base}/api/buy，body {itemId, qty}）
    GET  /admin/api/zcode/shop/order            查单（代理 {base}/api/order?orderId&token）

**导入面契约**（与 `api/admin_accounts.py::accounts_import` 同族；决策在
`upstream/zcode/store.py::import_account`，§15.1 三条硬约束不动）：

| 情形 | 出口 |
|---|---|
| `source` 非法 / 缺 `account`（panel/switch）/ 缺 `payload`（payload）/ qty 非法 | 400 + 可读原因 |
| 来源侧账号不存在（panel 名 / switch 文件名） | 404 + 已发现数量 |
| 形态校验不过（`imports.ImportValidationError`：坏名/坏 jwt/签名密钥/未知形态…） | 400（带面板同款短码） |
| 设备 ID 冲突 | **409** + `conflict_with` + reuse/regenerate 出路（**不静默覆盖**，硬约束 3） |
| 其余落盘失败 | 400（`store.ImportResult.message` 原话） |

🔴 写盘安全（与 `mgw zcode import` **同一条实现**，不另起一份）：写盘一律走
`upstream/zcode/store.py::import_account`（与 CLI 同一个函数对象）——注意 zcode 这条
**产品私有导入路径的现状就是"无跨进程写锁"**（公共层 `accounts/store.py` 的三条写路径
才持 `data/locks/accounts.lock`；zcode 的并入见 `zcode/store.py` 注释里的 M6-3 待办）。
本模块**如实镜像 CLI 的既有安全性**（同写者、同判据），并把整段读-改-写下放工作线程
（`asyncio.to_thread`，A-1 同纪律：等锁/写盘不停摆事件循环）。本模块不写任何 ad-hoc 文件。

**小店代理契约**：

- `{base}` 默认 `https://shop.youyuaiwan.xyz`（= 面板 `renderer/app.js:22` 指向的同一站点），
  环境变量 `MGW_SHOP_BASE` 覆盖（本地桩测试即走它）；
- 基址白名单**逐字照抄面板** `main.js:2347-2361`：https 一律允许；http 只放行
  回环（127.0.0.1 / localhost / ::1）+ 自家域名（youyuaiwan.xyz / www.youyuaiwan.xyz）；
- 超时 10s；网络失败 → 502 + 可读原因；小店的非 200/JSON 响应按原状态码原样转发
  （错误文案由小店给，代理不编造）；
- 🔴 **响应体永不进日志**（发货载荷含账号凭据，`/api/order` 命中 delivered 时
  `accounts[]` 就是凭据本体）——本模块的日志只有路径与异常**类型**，不落任何响应内容；
  502 文案里会把 orderToken 值抹成 `***`（httpx 个别异常文案会带 URL）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from model_gateway.api.admin_accounts import _ApiError, _body, _endpoint
from model_gateway.upstream.zcode import imports as zim
from model_gateway.upstream.zcode import store as zstore

logger = logging.getLogger("model_gateway.api.zcode")

router = APIRouter()

# ---------- 导入面 ----------

def _already_imported(entry: zim.DetectedAccount, names: set, mids: set) -> bool:
    """已导入判据：网关有同名账号 **或** 同设备码的账号（两者任一命中）。"""
    return entry.name in names or (bool(entry.device_mid) and entry.device_mid in mids)


def _sources_payload() -> dict:
    """扫描两个来源（磁盘 IO → 由调用方下放工作线程）。

    单个来源扫描失败（如目录不可读）→ 该来源带 `error` 字段、账号表为空，
    **不把整页打成 500**（另一来源与"根在哪"仍可见；§22.8-5 fail-soft + 留痕）。
    """
    accounts = zstore.list_accounts()
    names = {a.name for a in accounts}
    mids = {a.device_id for a in accounts if a.device_id}

    def block(kind: str) -> dict:
        root = zim.default_panel_root() if kind == "panel" else zim.default_switch_root()
        try:
            entries = (zim.scan_panel_dir() if kind == "panel" else zim.scan_switch_dir())
        except OSError as e:
            logger.warning("导入源扫描失败：%s：%s: %s", kind, type(e).__name__, e)
            return {"root": str(root), "exists": root.is_dir(), "accounts": [],
                    "error": f"{type(e).__name__}: {e}"}
        return {"root": str(root), "exists": root.is_dir(),
                "accounts": [{"name": e.name, "device_mid": e.device_mid,
                              "family": e.family,
                              "already_imported": _already_imported(e, names, mids)}
                             for e in entries]}

    return {"panel": block("panel"), "switch": block("switch")}


@router.get("/admin/api/zcode/import/sources")
@_endpoint
async def zcode_import_sources():
    """面板 / switch 两个来源的扫描结果（「导入账号」弹窗的数据面）。

    响应：`{panel: {root, exists, accounts[]}, switch: {root, exists, accounts[]}}`；
    每个账号 `{name, device_mid, family, already_imported}`。**只读**：不产生任何写盘副作用。
    """
    return await asyncio.to_thread(_sources_payload)


def _match_entry(entries: list[zim.DetectedAccount], target: str):
    """按名字/目录名/文件名（含 stem）匹配来源侧账号（**只做与扫描结果的等值比较**，
    不拿 target 去拼任何文件路径 —— 目录穿越在此无面）。"""
    t = str(target).strip()
    for e in entries:
        p = Path(e.path)
        if e.name == t or p.name == t or p.stem == t:
            return e
    return None


def _run_import(source: str, account: str, payload_obj, reuse, regenerate):
    """来源解析 → 载荷转换 → `store.import_account`（整段在工作线程里跑）。

    来源侧问题抛 `_ApiError`（404/400）；导入结果（含设备冲突）由返回值交由端点映射。
    """
    form = ""
    if source == "panel":
        entries = zim.scan_panel_dir()
        entry = _match_entry(entries, account)
        if entry is None:
            raise _ApiError(404, f"面板账号库中没有『{account}』（已发现 {len(entries)} 个账号）")
        try:
            payload = zim.from_panel_account(entry.path)
        except zim.ImportValidationError as e:
            raise _ApiError(400, f"面板账号不可导入：{e.message}（{e.code}）") from None
        form = "panel-account"
    elif source == "switch":
        entries = zim.scan_switch_dir()
        entry = _match_entry(entries, account)
        if entry is None:
            raise _ApiError(404, f"zcode-switch 账号库中没有『{account}』（已发现 {len(entries)} 个账号）")
        try:
            payload = zim.from_switch_json(entry.path)
        except zim.ImportValidationError as e:
            raise _ApiError(400, f"zcode-switch 账号不可导入：{e.message}（{e.code}）") from None
        form = "switch-account"
    else:  # payload
        form = zim.detect_payload_form(payload_obj)
        if form == zim.FORM_UNKNOWN:
            raise _ApiError(
                400, "无法识别的 payload 形态（支持：面板/小店粘贴 JSON、zcode-switch "
                     "账号 JSON、网关载荷 JSON）")
        try:
            template = (zim.find_config_template(zstore.accounts_root())
                        if form == zim.FORM_PASTE else None)
            payload = zim.payload_for_form(payload_obj, form, template=template)
        except zim.ImportValidationError as e:
            raise _ApiError(400, f"payload 不可导入：{e.message}（{e.code}）") from None

    res = zstore.import_account(None, reuse=reuse, regenerate=regenerate,
                                payload=payload, fallback_name=account)
    return res, form


@router.post("/admin/api/zcode/import")
@_endpoint
async def zcode_import(request: Request):
    """按来源导入一个账号（panel / switch / payload 三选一）。

    载荷：`{source, account?, payload?, reuse?, regenerate?}`
    （`source=panel|switch` 用 `account` 指定来源侧账号名；`source=payload` 用 `payload` 对象）。
    `reuse` / `regenerate` 语义与 §15.1 契约逐字一致（冲突默认拒绝）。
    """
    body = await _body(request)
    source = str(body.get("source") or "").strip()
    if source not in ("panel", "switch", "payload"):
        raise _ApiError(400, "source 必须是 panel / switch / payload 之一")
    account = str(body.get("account") or "").strip()
    reuse = str(body.get("reuse") or "").strip() or None
    regenerate = bool(body.get("regenerate"))
    payload_obj = body.get("payload")
    if source == "payload":
        if not isinstance(payload_obj, dict):
            raise _ApiError(400, "source=payload 需要 payload 对象")
    elif not account:
        raise _ApiError(400, f"source={source} 需要 account（来源侧账号名）")

    res, form = await asyncio.to_thread(_run_import, source, account, payload_obj,
                                        reuse, regenerate)
    if res.ok:
        return {"status": "ok", "product": "zcode", "account": res.account,
                "device_id": res.device_id, "message": res.message,
                "source": source, "form": form}
    if res.conflict:
        raise _ApiError(409, res.message, conflict=True,
                        conflict_with=res.conflict_with, account=res.account,
                        hint="设备 ID 与既有账号冲突：带 reuse=<账号名> 复用其设备 ID，"
                             "或带 regenerate=true 重新生成（拒绝 + 交用户决策，不静默覆盖）")
    raise _ApiError(400, res.message)


# ---------- 小店代理 ----------

#: 小店基址默认值 = 面板 `renderer/app.js:22` 指向的同一站点（`MGW_SHOP_BASE` 可覆盖）
SHOP_DEFAULT_BASE = "https://shop.youyuaiwan.xyz"
#: 单次请求超时（秒）——代理只做转发，不做重试（下单是购买动作，重试语义必须留在调用方）
SHOP_TIMEOUT_S = 10.0
#: http 放行主机白名单（**逐字**照抄面板 `main.js:2347-2361`）：回环（本地测试）+ 自家域名
_SHOP_HTTP_OK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1",
                                 "youyuaiwan.xyz", "www.youyuaiwan.xyz"})


def shop_base() -> str:
    """当前小店基址（`MGW_SHOP_BASE` 优先；**调用时**读取，测试可即时覆盖）。"""
    return (os.environ.get("MGW_SHOP_BASE") or SHOP_DEFAULT_BASE).strip().rstrip("/")


def _shop_base_error(base: str) -> str:
    """基址白名单校验（照抄面板口径）；不通过返回可读原因，通过返回空串。"""
    try:
        parts = urlsplit(base)
    except ValueError:
        return "基址解析失败"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "只允许 http(s) 基址"
    if parts.scheme == "http" and parts.hostname.lower() not in _SHOP_HTTP_OK_HOSTS:
        return "http 只放行本机回环 / youyuaiwan.xyz（同面板白名单）"
    return ""


def _make_shop_client() -> httpx.AsyncClient:
    """出站客户端（**测试缝**：用例 monkeypatch 本函数即可注入本地桩/零网络）。"""
    return httpx.AsyncClient(timeout=httpx.Timeout(SHOP_TIMEOUT_S))


def _redact(text: str, secrets) -> str:
    """把能力令牌值从文案里抹掉（httpx 个别异常会把 URL 带进 str(e)）。"""
    out = text
    for s in secrets:
        if s:
            out = out.replace(s, "***")
    return out


async def _shop_request(method: str, path: str, *, json_body=None, params=None,
                        redact=()) -> JSONResponse:
    """小店请求的**唯一出口**：白名单 → 请求 → 转发（状态码原样，JSON 原样）。

    🔴 本函数（以及本模块）**不打印任何请求/响应体** —— 发货响应含账号凭据；
    失败只记路径与异常类型（见模块头「小店代理契约」）。
    """
    base = shop_base()
    err = _shop_base_error(base)
    if err:
        raise _ApiError(400, f"小店基址不被允许（{err}）：{base}")
    try:
        async with _make_shop_client() as client:
            resp = await client.request(method, f"{base}{path}",
                                        json=json_body, params=params)
    except httpx.HTTPError as e:
        detail = _redact(str(e) or type(e).__name__, redact)
        logger.warning("小店请求失败：%s %s：%s", method, path, type(e).__name__)
        raise _ApiError(502, f"小店不可达（{type(e).__name__}）：{detail}") from None
    try:
        data = resp.json()
    except ValueError:
        raise _ApiError(502, f"小店响应不是 JSON（HTTP {resp.status_code}）") from None
    return JSONResponse(status_code=resp.status_code, content=data)


@router.get("/admin/api/zcode/shop/items")
@_endpoint
async def zcode_shop_items():
    """小店库存（代理 `GET {base}/api/list`；小店免鉴权协议，实测 2026-10-01）。"""
    return await _shop_request("GET", "/api/list")


@router.post("/admin/api/zcode/shop/buy")
@_endpoint
async def zcode_shop_buy(request: Request):
    """下单（代理 `POST {base}/api/buy`，body `{itemId, qty}`）。

    只做形状校验（itemId 非空、qty 1..99）—— 不代替小店做业务上限判断；
    付款仍在 `payPath` 收银台（用户驱动步骤，§22.0 边界翻案后也只做协议对接+展示）。
    """
    body = await _body(request)
    item_id = str(body.get("itemId") or "").strip()
    if not item_id:
        raise _ApiError(400, "缺少 itemId")
    try:
        qty = int(body.get("qty"))
    except (TypeError, ValueError):
        raise _ApiError(400, "qty 必须是正整数") from None
    if qty < 1 or qty > 99:
        raise _ApiError(400, "qty 必须在 1..99（小店页面自限 10；代理只挡明显非法值）")
    return await _shop_request("POST", "/api/buy", json_body={"itemId": item_id, "qty": qty})


@router.get("/admin/api/zcode/shop/order")
@_endpoint
async def zcode_shop_order(orderId: str = Query(default=""), token: str = Query(default="")):
    """查单（代理 `GET {base}/api/order?orderId&token`）。

    小店在 `status="delivered"` 时随响应下发 `accounts[]`（买到的账号，面板/小店
    粘贴导入形态）—— 代理**原样转发给本机发起方**（本机管理端就是买家本人），
    但绝不落日志（模块头「小店代理契约」；`token` 亦从异常文案里抹除）。
    """
    oid = str(orderId or "").strip()
    tok = str(token or "").strip()
    if not oid or not tok:
        raise _ApiError(400, "缺少 orderId / token（下单响应里的 orderId/orderToken）")
    return await _shop_request("GET", "/api/order",
                               params={"orderId": oid, "token": tok}, redact=(tok,))
