"""INT 模型目录 API：`GET /admin/api/accounts/{product}/{name}/models`（B-1 生产出口）。

背景（M6 交付验收面板 PM 报告 B-1）：10 产品的 `list_models` 钩子全部实现但**零生产消费者**；
本文件钉住修复轮-1 为该钩子建的第一组出口的契约（`api/admin_accounts.py::account_models`）：

| # | 态 | 出口 |
|---|---|---|
| 1 | 成功 | 200 `state:"ok"` + `models[]` + `source`（注册表 `models_source`） |
| 2 | 未知产品 | 400 + 可读原因（`codearts` 负例，不落任何调用） |
| 3 | 未接线（`_HOOKS` 缺 `list_models`） | 400 + 可读原因（§22.6「未登记 = 不支持」） |
| 4 | 取不动（钩子抛错） | 200 `state:"unknown"` + `reason`（空 `models`，**不编造**） |

成功态用 **qoder 真产品代码**跑通一次（其 `list_models` 为「恒本地兜底表」，零网络、
零假钩子），证明出口真的接到了产品实现而非测试桩；另用假钩子钉响应形状与 `meta` 通道。
全用例断言 **响应不含凭据明文**（§22.7 硬约束）；视图 `models_wired` 与端点取用同一张表。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from model_gateway.accounts import store
from model_gateway.accounts.types import ModelInfo
from model_gateway.upstream.buddy import product as buddy
from tests.integration.conftest import chat_res, gateway_config

#: 全用例共用的"凭据不落 HTTP"探针值（出现在所有假凭据里，逐个响应对它断言）
SECRET = "SECRET-TOKEN-DO-NOT-LEAK-c4f1"

#: 接入密钥（管理端免鉴权，仅 gateway 段完整性所需）
TOKENS = {"access_tokens": [{"id": "t-user", "value": "gw-user"}]}

#: `ModelInfo` 的载荷键集合（响应形状 = `dataclasses.asdict(ModelInfo)` 逐字段；
#: `free` / `rate` 为 2026-10-01 新增的结构化计费字段，随 asdict 自动出口）
MODEL_KEYS = {"id", "name", "vendor", "context_window", "max_output",
              "tool_call", "image_input", "reasoning", "effort_levels",
              "free", "rate"}


def _cfg(port: int) -> dict:
    """最小网关配置（资源指向 FakeVendor；账号侧数据经 `store.product_root` 落在 tmp）。"""
    return gateway_config(port, models=[chat_res("A")], gateway=TOKENS)


def _seed(product: str, name: str, credentials: dict, meta: dict | None = None) -> None:
    """造一个账号（走生产同一条落盘入口 `store.commit_login`）。"""
    store.commit_login(product, name, credentials, meta or {})


def _models_url(gw, product: str, name: str) -> str:
    return f"{gw.base_url}/admin/api/accounts/{product}/{name}/models"


# ============ 成功态 ============

class TestModelsOk:
    async def test_real_product_hook_qoder_static_catalog(self, vendor, make_gateway, client):
        """成功态（真产品代码，零网络）：qoder 恒本地兜底表 → 200 ok + 17 条 + source=static。

        本用例**不 monkeypatch 任何钩子**——走 `qoder/product.py::list_models` 的真实实现，
        证明出口接的是产品层而非测试桩（B-1 的「零用户出口」修复点）。
        """
        gw = await make_gateway(_cfg(vendor.port))
        _seed("qoder", "mdl-real", {"access_token": SECRET})

        r = await client.get(_models_url(gw, "qoder", "mdl-real"))
        assert r.status_code == 200, r.text
        assert SECRET not in r.text
        body = r.json()
        assert body["product"] == "qoder" and body["account"] == "mdl-real"
        assert body["state"] == "ok" and body["source"] == "static"
        ids = [m["id"] for m in body["models"]]
        assert len(ids) == 17 and "auto" in ids and "qmodel" in ids
        assert all(set(m) == MODEL_KEYS for m in body["models"])
        # 「不编造」样例（qoder 兜底表口径）：tool_call 恒 None；max_output 不虚构
        auto = next(m for m in body["models"] if m["id"] == "auto")
        assert auto["tool_call"] is None and auto["max_output"] is None
        assert auto["context_window"] == 200000
        # 结构化计费字段真实出口（2026-10-01）：
        # qfmodel 的 `price_factor: 0` → free=True（免费额度模型，`qoder-product.ts:408-410`）；
        # kmodel_latest 无促销 → 倍率即原价（free=False + `x1.4`，`:426`）。
        qfmodel = next(m for m in body["models"] if m["id"] == "qfmodel")
        assert qfmodel["free"] is True and qfmodel["rate"] == "x0"
        kimi = next(m for m in body["models"] if m["id"] == "kmodel_latest")
        assert kimi["free"] is False and kimi["rate"] == "x1.4"

    async def test_fake_hook_shape_meta_channel_and_no_credential(
            self, vendor, make_gateway, client, monkeypatch):
        """成功态（假钩子）：响应逐字段透传；`meta` 锚字段送达钩子；凭据只进不出。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "mdl-shape", {"token": SECRET})
        seen: dict = {}

        async def fake(cred, meta):
            seen["cred"], seen["meta"] = cred, meta
            return [ModelInfo(id="vm-a", name="VM A", vendor="V", context_window=200000,
                              max_output=8192, tool_call=True, image_input=False,
                              reasoning=True, effort_levels=("low", "high"))]

        monkeypatch.setitem(buddy._HOOKS, "list_models", fake)
        r = await client.get(_models_url(gw, "buddy", "mdl-shape"))
        assert r.status_code == 200, r.text
        assert SECRET not in r.text
        body = r.json()
        assert body["state"] == "ok" and body["source"] == "remote"
        assert body["models"] == [{
            "id": "vm-a", "name": "VM A", "vendor": "V", "context_window": 200000,
            "max_output": 8192, "tool_call": True, "image_input": False,
            "reasoning": True, "effort_levels": ["low", "high"],
            "free": None, "rate": ""}]
        # 钩子拿到凭据（进程内流转）与 meta 锚字段（§22.3 补入①），但响应绝不回传
        assert seen["cred"] == {"token": SECRET}
        assert seen["meta"]["account"] == "mdl-shape"
        assert Path(seen["meta"]["dir"]).is_absolute()
        assert seen["meta"]["dir"] not in r.text


# ============ 拒绝态（未知产品 / 账号不存在 / 未接线）============

class TestModelsRefusals:
    async def test_unknown_product_400(self, vendor, make_gateway, client):
        """未知产品 → 400 + 可读原因（codearts 负例：全仓一致，不静默降级）。"""
        gw = await make_gateway(_cfg(vendor.port))
        r = await client.get(_models_url(gw, "codearts", "x"))
        assert r.status_code == 400, r.text
        assert "未登记的产品" in r.json()["error"]["message"]

    async def test_unknown_account_404(self, vendor, make_gateway, client):
        """账号不存在 → 404；非法账号名（穿越形态）→ 400。"""
        gw = await make_gateway(_cfg(vendor.port))
        r = await client.get(_models_url(gw, "buddy", "ghost"))
        assert r.status_code == 404 and "账号不存在" in r.json()["error"]["message"]
        r = await client.get(_models_url(gw, "buddy", "%2E%2E"))
        assert r.status_code == 400 and "账号名必须匹配" in r.json()["error"]["message"]

    async def test_not_wired_hook_400_and_view_flag(self, vendor, make_gateway, client,
                                                    monkeypatch):
        """未接线（`_HOOKS` 缺 `list_models`）→ 400 可读原因；视图 `models_wired` 同步为 false。

        判据同源：端点 `_hook()` 读 `_HOOKS` 表；视图 `models_wired` 由同一张表现算 ——
        「按钮可见」等价于「端点可达」（§22.6：未登记 = 不渲染，不出"点了必然失败"的钮）。
        """
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "mdl-wire", {"token": SECRET})

        view = (await client.get(f"{gw.base_url}/admin/api/accounts")).json()
        assert all(p["models_wired"] is True for p in view["products"])   # 10 产品全接线

        monkeypatch.delitem(buddy._HOOKS, "list_models")
        r = await client.get(_models_url(gw, "buddy", "mdl-wire"))
        assert r.status_code == 400, r.text
        msg = r.json()["error"]["message"]
        assert "未提供钩子 'list_models'" in msg and "契约表" in msg
        assert SECRET not in r.text

        view = (await client.get(f"{gw.base_url}/admin/api/accounts")).json()
        flags = {p["id"]: p["models_wired"] for p in view["products"]}
        assert flags["buddy"] is False and flags["trae"] is True           # 只影响被摘的产品


# ============ 取不动（钩子抛错）与类型异常 ============

class TestModelsUnavailable:
    async def test_hook_exception_is_state_unknown_with_reason(self, vendor, make_gateway,
                                                               client, monkeypatch):
        """取不动 → **200 `state:"unknown"` + `reason`**（空 models，不编造；HTTP 非 5xx）。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "mdl-un", {"token": SECRET})

        async def boom(cred, meta):
            raise RuntimeError("上游炸了（假钩子）")

        monkeypatch.setitem(buddy._HOOKS, "list_models", boom)
        r = await client.get(_models_url(gw, "buddy", "mdl-un"))
        assert r.status_code == 200, r.text
        assert SECRET not in r.text
        body = r.json()
        assert body["state"] == "unknown" and body["models"] == []
        assert body["source"] == "remote"
        assert body["reason"].startswith("RuntimeError") and "上游炸了" in body["reason"]

    async def test_not_implemented_hook_is_unknown_too(self, vendor, make_gateway,
                                                       client, monkeypatch):
        """钩子体抛 `NotImplementedError`（声明未实现）→ 同一 `unknown` 出口，原因可读。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "mdl-ni", {"token": SECRET})

        async def notimpl(cred, meta):
            raise NotImplementedError("本产品目录端点未移植")

        monkeypatch.setitem(buddy._HOOKS, "list_models", notimpl)
        r = await client.get(_models_url(gw, "buddy", "mdl-ni"))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["state"] == "unknown" and "未移植" in body["reason"]

    async def test_bad_return_type_is_502(self, vendor, make_gateway, client, monkeypatch):
        """违反返回值契约（非 `list[ModelInfo]`）→ 502 + 可读原因（编程错误不静默）。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "mdl-bad", {"token": SECRET})

        async def not_a_list(cred, meta):
            return {"models": "nope"}

        monkeypatch.setitem(buddy._HOOKS, "list_models", not_a_list)
        r = await client.get(_models_url(gw, "buddy", "mdl-bad"))
        assert r.status_code == 502, r.text
        assert "类型异常" in r.json()["error"]["message"]

        async def wrong_items(cred, meta):
            return ["not-a-model-info"]

        monkeypatch.setitem(buddy._HOOKS, "list_models", wrong_items)
        r = await client.get(_models_url(gw, "buddy", "mdl-bad"))
        assert r.status_code == 502, r.text
        assert "条目类型异常" in r.json()["error"]["message"]


# ============ 凭据不回传（四态扫尾）============

class TestModelsNoCredentialLeak:
    async def test_no_credential_in_all_four_states(self, vendor, make_gateway, client,
                                                    monkeypatch):
        """四态响应全量扫尾：凭据明文（含 refresh_token / meta.json 私有值）零出现。"""
        gw = await make_gateway(_cfg(vendor.port))
        _seed("buddy", "mdl-leak", {"token": SECRET, "refresh_token": SECRET},
              {"plan": "x", "nickname": SECRET})

        async def ok_hook(cred, meta):
            return [ModelInfo(id="m", name="M")]

        monkeypatch.setitem(buddy._HOOKS, "list_models", ok_hook)
        responses = [await client.get(_models_url(gw, "buddy", "mdl-leak"))]     # 成功

        responses.append(await client.get(_models_url(gw, "codearts", "x")))     # 未知产品

        monkeypatch.delitem(buddy._HOOKS, "list_models")
        responses.append(await client.get(_models_url(gw, "buddy", "mdl-leak")))  # 未接线

        async def boom(cred, meta):
            raise RuntimeError("上游拒绝读取目录")

        monkeypatch.setitem(buddy._HOOKS, "list_models", boom)
        responses.append(await client.get(_models_url(gw, "buddy", "mdl-leak")))  # 取不动

        assert responses[0].json()["state"] == "ok"
        assert responses[1].status_code == 400
        assert responses[2].status_code == 400
        assert responses[3].json()["state"] == "unknown"
        for resp in responses:
            assert SECRET not in resp.text, f"凭据泄露：{resp.request.url} → {resp.text}"
        # `reason` 面 = 产品层异常文案（与既有 502 出口同口径）：本层只保证自己构造的字段
        # （models/source/account/…）不含凭据；产品钩子不得把凭据拼进异常文案（§22.2 不变式②）。
        assert set(responses[0].json()) == {"product", "account", "source", "state", "models"}
        assert set(responses[3].json()) == {"product", "account", "source", "state",
                                            "models", "reason"}
