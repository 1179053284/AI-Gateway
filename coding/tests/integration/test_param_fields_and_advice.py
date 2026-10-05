"""INT · 参数档案的三条出口（2026-10-04 参数卡排查轮）。

钉的三个形状，都是排查时**当下没有判据**的那些：

1. **出站优先级**（R2/R3）：本卡写了 `max_tokens` 就以本卡为准，规格里那份更大的数**不得**覆盖它；
   本卡清空之后，注入的是**统一规格**那个数 —— 而不是界面原先宣称的"走供应商通道默认"。
   方向说反过一次，所以两条腿一起钉（同一个字段、两个来源，必须能分出谁赢）。
2. **枚举池出口带回读**（Q24 那课）：`GET /admin/api/enums` 下发 `param_fields`，
   `PUT` 必须把它读回来；档案写坏 ⇒ 400 说清是哪一条（不许甩 500）。
3. **写面只标不拦**：用户设了厂商会忽略/会报错的参数 ⇒ `200` + 回执带 `warnings` + **照原样落盘**。
   写面一拦，「上游真回 400 ⇒ 界面报保存失败」那条路径就永远走不到了（v2 门 M15 同一条契约）。
"""

from __future__ import annotations

import httpx
import yaml

from tests.integration.conftest import gateway_config
from tests.integration.fakevendor import Ok

MODEL = "glm-5.3"          # 内置目录条目：max_output=131072、官方缺省 temperature 1.0 / top_p 0.95
CHAT_URL = "/v1/chat/completions"

FIELDS = {
    "temperature": {"kind": "number", "availability": "supported", "default": 1.0,
                    "min": 0.0, "max": 1.0, "note": "分系列默认", "source": "docs.z.ai 2026-10-04"},
    "top_k": {"kind": "integer", "availability": "rejected", "default": 20,
              "note": "传非默认值返回 400", "source": "docs.z.ai 2026-10-04"},
    "seed": {"kind": "integer", "availability": "ignored", "note": "设了不生效",
             "source": "docs.z.ai 2026-10-04"},
}


def _model_cfg(vendor_port: int, params: dict) -> dict:
    return gateway_config(vendor_port, models=[{
        "name": MODEL, "endpoint": "chat", "params": params,
        "resources": [{"resource": "res-A", "model": MODEL}]}])


async def _chat(client, gw, model: str = MODEL) -> httpx.Response:
    return await client.post(f"{gw.base_url}{CHAT_URL}", json={
        "model": model, "messages": [{"role": "user", "content": "hi"}]})


# ---------- 1) 出站优先级：本卡 max_tokens vs 统一规格 ----------
class TestMaxTokenSourceOfTruth:

    async def test_card_value_wins_over_bigger_spec_number(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="r"))
        gw = await make_gateway(_model_cfg(vendor.port, {"max_tokens": 65536}))
        r = await _chat(client, gw)
        assert r.status_code == 200, r.text
        body = vendor.bodies_for("sk-A")[-1]
        assert body.get("max_tokens") == 65536, f"参数卡那份没赢过规格：{body!r}"

    async def test_clearing_the_key_falls_to_spec_not_supplier_default(
            self, vendor, make_gateway, client):
        """目录里 GLM 的官方缺省是 65536、而对外承诺的 max_output 是 131072。

        清空之后出站带的必须是 **131072**（统一规格那一腿补的），界面那句"清空 = 走供应商通道默认"
        在这个键上是假的 —— 本用例就是把那句错话钉死成不可回退。
        """
        vendor.set("sk-A", Ok(content="r"))
        gw = await make_gateway(_model_cfg(vendor.port, {}))
        r = await _chat(client, gw)
        assert r.status_code == 200, r.text
        body = vendor.bodies_for("sk-A")[-1]
        assert body.get("max_tokens") == 131072, (
            f"清空 max_tokens 后没走统一规格：{body!r}")


# ---------- 2) 枚举池出口 + 回读 + 坏档案 400 ----------
class TestEnumsApi:

    async def test_enums_endpoint_delivers_and_round_trips_param_fields(
            self, vendor, make_gateway, client, tmp_path):
        # `make_gateway` 第一次装配用的枚举池路径 = enums-0.yaml（先落盘再启动，零 hack）
        (tmp_path / "enums-0.yaml").write_text(yaml.safe_dump({"entries": [{
            "name": MODEL, "display": "GLM 5.3", "group": "编程", "vendor": "智谱 GLM",
            "context_window": 1048576, "max_output": 131072,
            "param_fields": FIELDS,     # params_default 不写：由档案派生
        }]}, allow_unicode=True), encoding="utf-8")
        gw = await make_gateway(_model_cfg(vendor.port, {}))

        got = (await client.get(f"{gw.base_url}/admin/api/enums")).json()
        assert got["source"] == "file", got
        entry = next(e for e in got["entries"] if e["name"] == MODEL)
        assert entry["param_fields"]["top_k"]["availability"] == "rejected"
        # 派生：只有 supported + 有缺省值的键进 params_default
        assert entry["params_default"] == {"temperature": 1.0}

        # 原样 PUT 回去 ⇒ 档案不能掉（GET 导出、PUT 不读回来 = 编辑一次就把档案抹平）
        r = await client.put(f"{gw.base_url}/admin/api/enums", json={"entries": got["entries"]})
        assert r.status_code == 200, r.text
        again = (await client.get(f"{gw.base_url}/admin/api/enums")).json()
        # 🔴 S-3（2026-10-05）：用户文件改**增量覆写** ⇒ GET 出口 = 内置目录 + 用户覆写
        # （内置在前），按 name 取条目而不是按位置。
        entry2 = next(e for e in again["entries"] if e["name"] == MODEL)
        assert entry2["param_fields"]["seed"]["availability"] == "ignored"

    async def test_bad_param_field_is_a_400_not_a_500(self, vendor, make_gateway, client):
        gw = await make_gateway(_model_cfg(vendor.port, {}))
        bad = {"name": "some-model", "param_fields": {"temperature": {"kind": "map"}}}
        r = await client.put(f"{gw.base_url}/admin/api/enums", json={"entries": [bad]})
        assert r.status_code == 400, r.text
        assert "kind" in r.json()["errors"][0]


# ---------- 3) 写面只标不拦（唯一出口 = `config_warnings()` 横幅） ----------
class TestWriteFaceWarnsButPersists:

    async def test_rejected_and_ignored_keys_save_and_surface_one_banner(
            self, vendor, make_gateway, client, tmp_path):
        (tmp_path / "enums-0.yaml").write_text(yaml.safe_dump({"entries": [{
            "name": MODEL, "vendor": "智谱 GLM", "max_output": 131072,
            "param_fields": FIELDS,
        }]}, allow_unicode=True), encoding="utf-8")
        cfg = _model_cfg(vendor.port, {"top_k": 40, "seed": 7})
        gw = await make_gateway(cfg)

        body = yaml.safe_load(gw.config_path.read_text(encoding="utf-8"))
        r = await client.put(f"{gw.base_url}/admin/api/config", json=body)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ok", r.text
        # 🔴 只标不拦：值原样落盘，热重载后照样是这两个键（拦下来就等于把上游 400 那条路封死）
        saved = yaml.safe_load(gw.config_path.read_text(encoding="utf-8"))
        assert saved["models"][0]["params"] == {"top_k": 40, "seed": 7}

        kinds = {w["kind"]: w["message"] for w in gw.runtime.config_warnings()}
        assert "param_vs_catalog" in kinds, list(kinds)
        text = kinds["param_vs_catalog"]
        assert "top_k" in text and "报错" in text, text          # rejected
        assert "seed" in text and "忽略" in text, text            # ignored
        assert "docs.z.ai" in text, text                        # 每句都带官方出处
        # 用户可见出口只有一个：总览页横幅（与 ④ 推理遮蔽同一通道），不是第二份回执
        over = (await client.get(f"{gw.base_url}/admin/api/overview")).json()
        assert any(w["kind"] == "param_vs_catalog" for w in over["warnings"]), over["warnings"]

    async def test_clean_config_produces_no_such_warning(
            self, vendor, make_gateway, client, tmp_path):
        (tmp_path / "enums-0.yaml").write_text(yaml.safe_dump({"entries": [{
            "name": MODEL, "vendor": "智谱 GLM", "max_output": 131072,
            "param_fields": FIELDS,
        }]}, allow_unicode=True), encoding="utf-8")
        gw = await make_gateway(_model_cfg(vendor.port, {"temperature": 1.0}))
        body = yaml.safe_load(gw.config_path.read_text(encoding="utf-8"))
        r = await client.put(f"{gw.base_url}/admin/api/config", json=body)
        assert r.status_code == 200, r.text
        assert "param_vs_catalog" not in {w["kind"] for w in gw.runtime.config_warnings()}
