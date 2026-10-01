"""`/admin/api/zcode/import*` + 小店代理端点集成测试（Q31，2026-10-01）。

- 网关走 **ASGI transport**（与 `test_int_v2_zcode_admin.py` 同法，不起真实端口）；
- 小店代理的假上游 = **本机回环 stub 服务器**（`http.server` + 线程，随用随停）——
  **绝不访问真实小店**（https://shop.youyuaiwan.xyz 只在默认基址里出现）；
- 凭据全为合成值；断言用 `crypto.decrypt` 做本机 secret 往返校验。
"""

from __future__ import annotations

import http.server
import json
import logging
import threading
import urllib.parse
from types import SimpleNamespace

import httpx
import pytest
import yaml

from tests.integration.conftest import chat_res, gateway_config

pytestmark = pytest.mark.asyncio

JWT = "eyJhbGciOiJIUzI1NiJ9.QUJDREVGR0g.SIGNATURE_PART"
MID = "c363eb06-2b63-4c59-9c69-1c5794ccf0cb"
MID2 = "560be077-8cfc-527d-bf3b-7f431573428f"

#: 小店 shipped 的那个账号（面板粘贴形态；小店实测下发字段名，含 verifiedPlans 冗余键）
_DELIVERED_ACCOUNT = {
    "name": "fromshop", "verifiedPlans": [{"plan": "coding"}],
    "jwt": JWT, "device_mid": MID, "family": "zai",
    "credentials": {"oauth:zai:access_token": JWT, "oauth:zai:user_info": '{"sub":"u2"}'},
}


# ---------- 本机小店桩 ----------

class _StubShop(http.server.BaseHTTPRequestHandler):
    """回环 stub：/api/list、/api/buy、/api/order（含 delivered 账号下发）。"""

    def log_message(self, *args):        # 不让 stub 的请求行进测试输出
        pass

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):                                        # noqa: N802
        u = urllib.parse.urlsplit(self.path)
        self.server.requests.append(
            {"method": "GET", "path": u.path, "query": urllib.parse.parse_qs(u.query)})
        if u.path == "/api/list":
            self._json(200, {"items": [{"id": "i-1", "title": "一元号", "price": "1.00",
                                        "note": "n", "listed": True, "stock": 5,
                                        "validity": {"dailyUnits": 3_000_000}}]})
        elif u.path == "/api/order":
            oid = (urllib.parse.parse_qs(u.query).get("orderId") or [""])[0]
            if oid == "o-delivered":
                self._json(200, {"status": "delivered", "expired": False, "qty": 1,
                                 "amount": "1.00", "reallyPrice": "1.00",
                                 "accounts": [_DELIVERED_ACCOUNT]})
            elif oid == "o-pending":
                self._json(200, {"status": "pending", "expired": False, "qty": 1,
                                 "payPath": "/pay/o-pending"})
            else:
                self._json(404, {"error": "订单不存在"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):                                       # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        self.server.requests.append(
            {"method": "POST", "path": urllib.parse.urlsplit(self.path).path, "body": body})
        if self.path == "/api/buy":
            if body.get("itemId") != "i-1":
                self._json(400, {"error": "商品不存在"})
                return
            self._json(200, {"orderId": "o-1", "orderToken": "tk-order-1",
                             "itemId": body.get("itemId"), "qty": body.get("qty"),
                             "title": "一元号", "payPath": "/pay/o-1", "payTypeName": "微信"})
        else:
            self._json(404, {"error": "not found"})


@pytest.fixture
def shop_stub():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _StubShop)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(base=f"http://127.0.0.1:{server.server_address[1]}",
                              requests=server.requests)
    finally:
        server.shutdown()
        server.server_close()


# ---------- 网关夹具 ----------

@pytest.fixture
async def gw(tmp_path, monkeypatch):
    from model_gateway.main import create_app
    from model_gateway.upstream.zcode import imports as zim

    root = tmp_path / "zcode-accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    panel = tmp_path / "panel-accounts"
    switch = tmp_path / "switch-accounts"
    monkeypatch.setattr(zim, "default_panel_root", lambda: panel)
    monkeypatch.setattr(zim, "default_switch_root", lambda: switch)

    cfg = gateway_config(1, models=[chat_res("AB")])
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    app = create_app(config_path=p, usage_dir=tmp_path / "usage",
                     enums_path=tmp_path / "enums.yaml")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gw") as client:
        yield SimpleNamespace(client=client, root=root, panel=panel, switch=switch)


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _panel_account(root, name: str, *, mid: str, family: str = "zai"):
    d = root / name
    v2 = d / "data" / ".zcode" / "v2"
    v2.mkdir(parents=True, exist_ok=True)
    _write_json(d / "meta.json", {"device_mid": mid, "family": family, "via": "import"})
    cred = {"zcodejwttoken": "enc:v1:aa.bb.cc",
            "oauth:active_provider": "enc:v1:dd.ee.ff",
            f"oauth:{family}:access_token": "enc:v1:gg.hh.ii"}
    _write_json(v2 / "credentials.json", cred)
    cfg = {"provider": {f"builtin:{family}-start-plan": {
        "name": "x", "kind": "anthropic", "enabled": True,
        "options": {"apiKey": "j",
                    "baseURL": "https://zcode.z.ai/api/v1/zcode-plan/anthropic"}}}}
    _write_json(v2 / "config.json", cfg)
    _write_json(d / "config.json", cfg)
    return d


def _switch_file(root, stem: str, *, name: str, mid: str):
    return _write_json(root / f"{stem}.json", {
        "id": stem, "name": name, "hash": "h",
        "virtual_device_mid": mid, "virtual_arms_uid": "uid_x",
        "credentials": {"zcodejwttoken": "enc:v1:11.22.33",
                        "oauth:active_provider": "enc:v1:44.55.66",
                        "oauth:bigmodel:access_token": "enc:v1:77.88.99"},
        "config": {"provider": {"builtin:bigmodel-start-plan": {}}},
    })


# ============ 1) GET /admin/api/zcode/import/sources ============

async def test_sources_lists_both_roots_with_already_imported(gw, tmp_path):
    # 网关既有账号：seed 占 MID2；另一个按名字与面板条目重名
    _write_json(gw.root / "seed" / "meta.json", {"device_mid": MID2})
    _write_json(gw.root / "bysname" / "meta.json", {"device_mid": "other-mid"})
    _panel_account(gw.panel, "bysname", mid="c1111111-1111-1111-1111-111111111111")
    _panel_account(gw.panel, "p-mid", mid=MID2)          # 与 seed 同设备码
    _panel_account(gw.panel, "p-new", mid=MID)
    _switch_file(gw.switch, "aa-11", name="sw-new", mid="d2222222-2222-2222-2222-222222222222")

    r = await gw.client.get("/admin/api/zcode/import/sources")
    assert r.status_code == 200
    body = r.json()
    assert body["panel"]["root"] == str(gw.panel) and body["panel"]["exists"] is True
    assert body["switch"]["root"] == str(gw.switch)
    by_name = {a["name"]: a for a in body["panel"]["accounts"]}
    assert by_name["bysname"]["already_imported"] is True     # 同名命中
    assert by_name["p-mid"]["already_imported"] is True       # 同设备码命中
    assert by_name["p-new"]["already_imported"] is False
    assert body["panel"]["accounts"][0]["device_mid"]
    assert len(body["switch"]["accounts"]) == 1
    assert body["switch"]["accounts"][0]["already_imported"] is False


async def test_sources_missing_roots_are_empty_not_errors(gw):
    r = await gw.client.get("/admin/api/zcode/import/sources")
    body = r.json()
    assert r.status_code == 200
    assert body["panel"]["exists"] is False and body["panel"]["accounts"] == []
    assert body["switch"]["exists"] is False


# ============ 2) POST /admin/api/zcode/import ============

async def test_import_panel_account_passes_files_through(gw):
    src = _panel_account(gw.panel, "river4812", mid=MID)

    r = await gw.client.post("/admin/api/zcode/import",
                             json={"source": "panel", "account": "river4812"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["account"] == "river4812"
    assert body["device_id"] == MID and body["form"] == "panel-account"

    v2 = gw.root / "river4812" / "data" / ".zcode" / "v2"
    assert json.loads((v2 / "credentials.json").read_text(encoding="utf-8")) == \
        json.loads((src / "data" / ".zcode" / "v2" / "credentials.json").read_text())
    assert json.loads((v2 / "config.json").read_text(encoding="utf-8")) == \
        json.loads((src / "config.json").read_text(encoding="utf-8"))
    tele = json.loads((v2 / "telemetry-state.json").read_text(encoding="utf-8"))
    assert tele["deviceMid"] == MID


async def test_import_materializes_resource(gw):
    """Q31 修复（E2E 抓到的缺口）：导入成功 → **自动物化资源**（§22.5-1）。

    私有导入路径原先不物化 → 导入的账号进不了「模型映射 / 转接」（映射落点=物化资源）。
    物化目标 = `MG_CONFIG` 指向的配置（conftest 已钉进 tmp；`ensure_resource` 经
    `core.paths` 解析）——先写入一份合法配置，导入后断言资源出现。
    """
    from model_gateway.core import paths

    cfg_path = paths.resolve_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.safe_dump(gateway_config(1, models=[chat_res("AB")]),
                                       allow_unicode=True), encoding="utf-8")
    _panel_account(gw.panel, "mat-1", mid="11111111-2222-4333-8444-555555555555")

    r = await gw.client.post("/admin/api/zcode/import",
                             json={"source": "panel", "account": "mat-1"})
    assert r.status_code == 200, r.text
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    hits = [x for x in cfg.get("resources") or []
            if x.get("product") == "zcode" and x.get("account_ref") == "mat-1"]
    assert len(hits) == 1, f"导入未物化资源（resources={cfg.get('resources')}）"
    assert hits[0].get("enabled") is True


async def test_import_panel_conflict_409_then_reuse(gw):
    _panel_account(gw.panel, "p1", mid=MID)
    _panel_account(gw.panel, "p2", mid=MID)
    assert (await gw.client.post("/admin/api/zcode/import",
                                 json={"source": "panel", "account": "p1"})).status_code == 200

    r = await gw.client.post("/admin/api/zcode/import",
                             json={"source": "panel", "account": "p2"})
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["conflict"] is True and err["conflict_with"] == "p1"
    assert "不静默覆盖" in err["hint"]
    assert not (gw.root / "p2" / "meta.json").exists()        # 拒绝 = 不写盘

    r2 = await gw.client.post("/admin/api/zcode/import",
                              json={"source": "panel", "account": "p2", "reuse": "p1"})
    assert r2.status_code == 200
    meta = json.loads((gw.root / "p2" / "meta.json").read_text(encoding="utf-8"))
    assert meta["device_mid"] == MID


async def test_import_unknown_panel_account_404(gw):
    _panel_account(gw.panel, "p1", mid=MID)
    r = await gw.client.post("/admin/api/zcode/import",
                             json={"source": "panel", "account": "nope"})
    assert r.status_code == 404
    assert "已发现 1 个账号" in r.json()["error"]["message"]


async def test_import_payload_paste_form_encrypts(gw):
    from model_gateway.upstream.zcode import crypto

    r = await gw.client.post("/admin/api/zcode/import", json={
        "source": "payload", "payload": _DELIVERED_ACCOUNT})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["account"] == "fromshop" and body["form"] == "paste"
    v2 = gw.root / "fromshop" / "data" / ".zcode" / "v2"
    cred = json.loads((v2 / "credentials.json").read_text(encoding="utf-8"))
    assert crypto.decrypt(cred["zcodejwttoken"]) == JWT
    assert crypto.decrypt(cred["oauth:active_provider"]) == "zai"
    assert crypto.decrypt(cred["oauth:zai:user_info"]) == '{"sub":"u2"}'
    meta = json.loads((gw.root / "fromshop" / "meta.json").read_text(encoding="utf-8"))
    assert meta["device_mid"] == MID and meta["family"] == "zai"


async def test_import_payload_switch_object(gw):
    obj = json.loads(_switch_file(gw.switch, "aa-11", name="sw1", mid=MID2)
                     .read_text(encoding="utf-8"))
    r = await gw.client.post("/admin/api/zcode/import",
                             json={"source": "payload", "payload": obj})
    assert r.status_code == 200, r.text
    assert r.json()["form"] == "switch"
    meta = json.loads((gw.root / "sw1" / "meta.json").read_text(encoding="utf-8"))
    assert meta["device_mid"] == MID2


async def test_import_switch_source_by_file_stem(gw):
    _switch_file(gw.switch, "1eff0f2f-225c-4d87-8c9c-936ddf3190da", name="sw9", mid=MID)
    r = await gw.client.post("/admin/api/zcode/import", json={
        "source": "switch", "account": "1eff0f2f-225c-4d87-8c9c-936ddf3190da"})
    assert r.status_code == 200, r.text
    assert r.json()["account"] == "sw9"


@pytest.mark.parametrize("body,status", [
    ({"source": "nope"}, 400),
    ({"source": "panel"}, 400),                             # 缺 account
    ({"source": "payload"}, 400),                           # 缺 payload
    ({"source": "payload", "payload": [1]}, 400),
    ({"source": "payload", "payload": {}}, 400),            # 未知形态
    ({"source": "payload", "payload": {"name": "x", "jwt": "bad", "device_mid": MID}}, 400),
    ({"source": "payload", "payload": {"name": "x", "jwt": JWT, "device_mid": "no-uuid"}}, 400),
])
async def test_import_invalid_requests(gw, body, status):
    r = await gw.client.post("/admin/api/zcode/import", json=body)
    assert r.status_code == status, r.text
    assert "message" in r.json()["error"]


async def test_import_payload_error_names_the_short_code(gw):
    r = await gw.client.post("/admin/api/zcode/import", json={
        "source": "payload",
        "payload": {"name": "x", "jwt": JWT, "device_mid": MID, "family": "zai",
                    "credentials": {"oauth:zai:access_token":
                                    "0123456789abcdef0123456789abcdef.somesecret"}}})
    assert r.status_code == 400
    assert "bad-cred" in r.json()["error"]["message"]
    assert "签名密钥" in r.json()["error"]["message"]


# ============ 3) 小店代理 ============

async def test_shop_items_relayed(gw, shop_stub, monkeypatch):
    monkeypatch.setenv("MGW_SHOP_BASE", shop_stub.base)
    r = await gw.client.get("/admin/api/zcode/shop/items")
    assert r.status_code == 200
    assert r.json()["items"][0]["id"] == "i-1"
    assert shop_stub.requests[-1]["method"] == "GET" and \
        shop_stub.requests[-1]["path"] == "/api/list"


async def test_shop_buy_relayed(gw, shop_stub, monkeypatch):
    monkeypatch.setenv("MGW_SHOP_BASE", shop_stub.base)
    r = await gw.client.post("/admin/api/zcode/shop/buy",
                             json={"itemId": "i-1", "qty": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["orderId"] == "o-1" and body["orderToken"] == "tk-order-1"
    sent = shop_stub.requests[-1]
    assert sent["method"] == "POST" and sent["path"] == "/api/buy"
    assert sent["body"] == {"itemId": "i-1", "qty": 2}


@pytest.mark.parametrize("body", [
    {}, {"itemId": "i-1"}, {"itemId": "i-1", "qty": 0},
    {"itemId": "i-1", "qty": -1}, {"itemId": "i-1", "qty": "x"},
    {"itemId": "i-1", "qty": 100},
])
async def test_shop_buy_validates_shape(gw, shop_stub, monkeypatch, body):
    monkeypatch.setenv("MGW_SHOP_BASE", shop_stub.base)
    r = await gw.client.post("/admin/api/zcode/shop/buy", json=body)
    assert r.status_code == 400
    assert shop_stub.requests == []                          # 先拒后动：一个请求都没发


async def test_shop_order_delivered_includes_accounts(gw, shop_stub, monkeypatch):
    monkeypatch.setenv("MGW_SHOP_BASE", shop_stub.base)
    r = await gw.client.get("/admin/api/zcode/shop/order",
                            params={"orderId": "o-delivered", "token": "tk-order-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "delivered"
    assert body["accounts"][0]["name"] == "fromshop"         # 原样转发（本机发起方=买家）
    sent = shop_stub.requests[-1]
    assert sent["query"]["orderId"] == ["o-delivered"] and \
        sent["query"]["token"] == ["tk-order-1"]


async def test_shop_order_pending_and_upstream_error_relay(gw, shop_stub, monkeypatch):
    monkeypatch.setenv("MGW_SHOP_BASE", shop_stub.base)
    body = (await gw.client.get("/admin/api/zcode/shop/order",
                                params={"orderId": "o-pending", "token": "t"})).json()
    assert body["status"] == "pending" and "accounts" not in body
    r = await gw.client.get("/admin/api/zcode/shop/order",
                            params={"orderId": "o-404", "token": "t"})
    assert r.status_code == 404                              # 小店状态码原样转发
    assert r.json()["error"] == "订单不存在"


async def test_shop_order_requires_params(gw, shop_stub, monkeypatch):
    monkeypatch.setenv("MGW_SHOP_BASE", shop_stub.base)
    for params in ({}, {"orderId": "o-1"}, {"token": "t"}):
        r = await gw.client.get("/admin/api/zcode/shop/order", params=params)
        assert r.status_code == 400
    assert shop_stub.requests == []


async def test_shop_base_allowlist_rejects_foreign_http(gw, monkeypatch):
    monkeypatch.setenv("MGW_SHOP_BASE", "http://evil.example.com")
    r = await gw.client.get("/admin/api/zcode/shop/items")
    assert r.status_code == 400
    assert "白名单" in r.json()["error"]["message"]


async def test_shop_base_allowlist_matches_panel_rules():
    """白名单判据 = 面板 `main.js:2347-2361`（https 一律；http 只回环 + youyuaiwan.xyz）。

    纯函数断言（**不出网**）：本机回环 http 放行、自家域名 http 放行、陌生 http 拒。
    """
    from model_gateway.api.admin_zcode import _shop_base_error

    assert _shop_base_error("https://example.com") == ""          # https 一律放行
    assert _shop_base_error("http://127.0.0.1:8790") == ""        # 回环（本地桩）
    assert _shop_base_error("http://localhost:1") == ""
    assert _shop_base_error("http://youyuaiwan.xyz") == ""
    assert _shop_base_error("http://www.youyuaiwan.xyz") == ""
    assert _shop_base_error("http://evil.example.com") != ""      # 陌生 http 拒
    assert _shop_base_error("ftp://youyuaiwan.xyz") != ""         # 非 http(s) 拒


async def test_shop_network_failure_maps_to_502(gw, monkeypatch):
    """httpx 网络错误 → 502 + 可读原因（经**测试缝**注入 ConnectError，确定性、不出网）。"""
    import model_gateway.api.admin_zcode as az

    def _boom():
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(az, "_make_shop_client", _boom)
    r = await gw.client.get("/admin/api/zcode/shop/items")
    assert r.status_code == 502
    assert "小店不可达" in r.json()["error"]["message"]
    assert "ConnectError" in r.json()["error"]["message"]


async def test_shop_order_never_logs_response_credentials(gw, shop_stub, monkeypatch, caplog):
    """🔴 代理**任何级别**都不得把发货载荷（凭据本体）写进日志。"""
    monkeypatch.setenv("MGW_SHOP_BASE", shop_stub.base)
    with caplog.at_level(logging.DEBUG):
        r = await gw.client.get("/admin/api/zcode/shop/order",
                                params={"orderId": "o-delivered", "token": "tk-order-1"})
    assert r.status_code == 200 and r.json()["accounts"]
    assert JWT not in caplog.text
    assert "oauth:zai:access_token" not in caplog.text
    assert '{"sub":"u2"}' not in caplog.text
