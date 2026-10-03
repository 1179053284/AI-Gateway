"""INT 「初始化映射」`POST /admin/api/accounts/auto-map`（2026-10-03 用户指令）。

需求原话拆成判据：
- 「调用网关内任意可用的 DeepSeek flash 模型，然后分析这些模型应该匹配哪个网关模型」
  ⇒ 有可用 chat 腿时**由模型判定**，且优先低档位那条（A-1/A-2）；
- 「如果网关内没有可用的模型降级使用正则进行网关模型匹配」
  ⇒ 选不出腿 / 出站失败 / 回答不可解析 / 一条都没采纳 ⇒ **整表**走 `_enum_suggest`（A-3/A-4/A-5）；
- 落库必须与弹窗「保存」同一条写入出口（A-7：回执字段集合 ⊇ `mappings` 那份，产品位与条目一起写）；
- 「初始化之后按钮变为保存」⇒ 本端点**可重复调用**且幂等（A-7）。

零真实网络：分析腿用替身适配器（直接塞进 `runtime.adapters`），目录腿用 `_HOOKS["list_models"]`
假钩子；凭据明文在所有响应与所有出站请求体里逐条断言不出现（A-8）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from model_gateway.accounts import store
from model_gateway.accounts.types import ModelInfo
from model_gateway.api import admin_accounts as aa
from model_gateway.upstream.buddy import product as buddy
from tests.integration.conftest import chat_res, gateway_config
from tests.integration.fakevendor import Err, Ok

SECRET = "SECRET-AUTOMAP-DO-NOT-LEAK-9c41"
TOKENS = {"access_tokens": [{"id": "t-user", "value": "gw-user"}]}


def _cfg(port: int, models: list[dict]) -> dict:
    return gateway_config(port, models=models, gateway=TOKENS)


def _seed(name: str) -> None:
    store.commit_login("buddy", name, {"access_token": SECRET}, {})


def _saved(gw) -> dict:
    return yaml.safe_load(Path(gw.config_path).read_text(encoding="utf-8"))


class _Stub:
    """分析腿替身：记录每次出站请求，返回预设内容（或抛预设异常）。"""

    def __init__(self, reply: str = "", boom: Exception | None = None):
        self.calls: list[dict] = []
        self.reply = reply
        self.boom = boom

    async def chat_nonstream(self, key, vendor_model, body, timeout):
        self.calls.append({"key": key, "model": vendor_model, "body": body, "timeout": timeout})
        if self.boom is not None:
            raise self.boom
        return {"choices": [{"message": {"content": self.reply}}]}

    async def aclose(self) -> None:
        pass


def _catalog(*ids: str):
    async def fake(cred, meta):
        return [ModelInfo(id=i, name=i.upper()) for i in ids]
    return fake


def _json(rows: list[dict]) -> str:
    return json.dumps({"mappings": rows}, ensure_ascii=False)


class TestAutoMap:
    async def test_a1_model_engine_decides_and_regex_backfills(self, vendor, make_gateway,
                                                               client, monkeypatch):
        """A-1：模型答案优先；模型留空/幻觉的行由正则补齐，两个引擎各 matched 几条**分开报**。

        三条目录条目故意各走一支：
        - `zzz-unique-1` 模型给了名单内的 `claude-sonnet-4` ⇒ 记 `matched_model`；
        - `zzz-unique-2` 模型明确填空串 ⇒ 正则也认不出 ⇒ 计入 `unmatched`（不编造）；
        - `sn-glm-5-3` 模型给了**名单外**的名字 ⇒ 就地丢弃 ⇒ 正则剥前缀命中 `glm-5.3` ⇒ `matched_regex`。
        """
        gw = await make_gateway(_cfg(vendor.port, [chat_res("A", name="glm-4.6-flash")]))
        _seed("am-1")
        monkeypatch.setitem(buddy._HOOKS, "list_models",
                            _catalog("zzz-unique-1", "zzz-unique-2", "sn-glm-5-3"))
        stub = _Stub(reply=_json([
            {"model": "zzz-unique-1", "target": "claude-sonnet-4"},
            {"model": "zzz-unique-2", "target": ""},
            {"model": "sn-glm-5-3", "target": "gpt-9-ultra"},      # 名单外 = 幻觉
            {"model": "made-up-row", "target": "glm-5.3"},          # 本批没送出去的 id
        ]))
        gw.runtime.adapters["res-A"] = stub

        r = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                              json={"product": "buddy"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["via"] == "model" and body["analyzed_by"] == "glm-4.6-flash"
        assert body["entries"] == 3 and body["analyzed"] == 3
        assert body["matched_model"] == 1 and body["matched_regex"] == 1
        assert body["unmatched"] == 1
        assert body["added"] == 2 and body["skipped"] == []
        assert sorted(body["created_models"]) == ["claude-sonnet-4", "glm-5.3"]
        # 送出去的确实是所选那条腿自己的凭据与厂商模型 id（替身收到的）
        assert len(stub.calls) == 1
        assert stub.calls[0]["key"] == "sk-A" and stub.calls[0]["model"] == "vm-A"
        # 落库形状与手动「保存」同一条出口：产品位是真相
        bits = {(b["model"], b["system_model"], b["enabled"])
                for b in _saved(gw)["product_models"]}
        assert bits == {("zzz-unique-1", "claude-sonnet-4", True),
                        ("sn-glm-5-3", "glm-5.3", True)}
        # 模型编出来的那个名字**没有**被创建成系统模型（丢弃 ≠ 落库）
        assert "gpt-9-ultra" not in {m["name"] for m in _saved(gw)["models"]}

    async def test_a2_flash_tier_leg_is_preferred(self, vendor, make_gateway, client, monkeypatch):
        """A-2：多条可用腿并列时选**低档位**那条（名字含 flash/lite/…），且选择可复现。"""
        gw = await make_gateway(_cfg(vendor.port, [
            chat_res("A", name="glm-4.6"),                 # 旗舰（无档位词）
            chat_res("B", name="glm-4.6-flash"),           # 低档位 ⇒ 应选它
        ]))
        _seed("am-2")
        monkeypatch.setitem(buddy._HOOKS, "list_models", _catalog("glm-5.3"))
        cheap = _Stub(reply=_json([{"model": "glm-5.3", "target": "glm-5.3"}]))
        pricey = _Stub()
        gw.runtime.adapters["res-A"] = pricey
        gw.runtime.adapters["res-B"] = cheap

        r = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                              json={"product": "buddy"})
        assert r.status_code == 200, r.text
        assert r.json()["analyzed_by"] == "glm-4.6-flash"
        assert len(cheap.calls) == 1 and pricey.calls == []

    async def test_a3_no_available_leg_degrades_to_regex(self, vendor, make_gateway,
                                                         client, monkeypatch):
        """A-3：网关内**没有**可用模型（唯一那条映射被关掉）⇒ 整表走正则，`via` 如实写 `regex`。"""
        gw = await make_gateway(_cfg(vendor.port, [{
            "name": "glm-4.6-flash", "endpoint": "chat",
            "resources": [{"resource": "res-A", "model": "vm-A", "enabled": False}]}]))
        _seed("am-3")
        monkeypatch.setitem(buddy._HOOKS, "list_models", _catalog("sn-glm-5-3", "mystery-x"))

        r = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                              json={"product": "buddy"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["via"] == "regex" and body["analyzed_by"] == ""
        assert "没有可用的模型" in body["reason"]
        assert body["matched_model"] == 0 and body["matched_regex"] == 1
        assert body["unmatched"] == 1, "mystery-x 正则也认不出 ⇒ 不许编造"
        bits = [(b["model"], b["system_model"]) for b in _saved(gw)["product_models"]]
        assert bits == [("sn-glm-5-3", "glm-5.3")]

    async def test_a4_upstream_failure_degrades_whole_table(self, vendor, make_gateway,
                                                           client, monkeypatch):
        """A-4：分析腿**报错**（超时/上游 5xx…）⇒ 整表降级，绝不交出"半张模型表 + 半张正则表"。"""
        gw = await make_gateway(_cfg(vendor.port, [chat_res("A", name="glm-4.6-flash")]))
        _seed("am-4")
        monkeypatch.setitem(buddy._HOOKS, "list_models", _catalog("sn-glm-5-3"))
        gw.runtime.adapters["res-A"] = _Stub(
            boom=RuntimeError("upstream 503 service unavailable"))

        r = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                              json={"product": "buddy"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["via"] == "regex"
        assert "模型分析未能完成" in body["reason"] and "RuntimeError" in body["reason"]
        assert body["matched_regex"] == 1 and body["matched_model"] == 0
        # 降级后照样落库（用户点一次就得到结果，而不是"报个错什么都没写"）
        assert [(b["model"], b["system_model"]) for b in _saved(gw)["product_models"]] \
            == [("sn-glm-5-3", "glm-5.3")]

    async def test_a5_unparseable_answer_degrades(self, vendor, make_gateway, client, monkeypatch):
        """A-5：回答不是 JSON / 是空内容 ⇒ 同一支整表降级（两条独立形状各测一次）。"""
        gw = await make_gateway(_cfg(vendor.port, [chat_res("A", name="glm-4.6-flash")]))
        _seed("am-5")
        monkeypatch.setitem(buddy._HOOKS, "list_models", _catalog("sn-glm-5-3"))
        gw.runtime.adapters["res-A"] = _Stub(reply="抱歉，我需要更多信息才能判断。")
        r = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                              json={"product": "buddy"})
        assert r.status_code == 200, r.text
        assert r.json()["via"] == "regex" and "没有 JSON 对象" in r.json()["reason"]

        gw.runtime.adapters["res-A"] = _Stub(reply="")      # 空内容 = 另一条独立支路
        r2 = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                               json={"product": "buddy"})
        assert r2.status_code == 200, r2.text
        assert r2.json()["via"] == "regex" and "空内容" in r2.json()["reason"]

    async def test_a6_empty_catalog_and_zero_match_are_refusals(self, vendor, make_gateway,
                                                                client, monkeypatch):
        """A-6：目录为空 / 一条也没匹配上 ⇒ **400**（不做假成功），且拒绝时零写盘。"""
        gw = await make_gateway(_cfg(vendor.port, [chat_res("A", name="glm-4.6-flash")]))
        _seed("am-6")

        async def empty(cred, meta):
            return []
        monkeypatch.setitem(buddy._HOOKS, "list_models", empty)
        before = Path(gw.config_path).read_text(encoding="utf-8")
        r = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                              json={"product": "buddy"})
        assert r.status_code == 400
        assert "目录为空" in r.json()["error"]["message"]
        assert Path(gw.config_path).read_text(encoding="utf-8") == before, "拒绝却写了盘"

        # 目录有条目，但模型全部留空 + 正则全部认不出 ⇒ 零命中 ⇒ 400
        monkeypatch.setitem(buddy._HOOKS, "list_models", _catalog("mystery-x", "mystery-y"))
        gw.runtime.adapters["res-A"] = _Stub(
            reply=_json([{"model": "mystery-x", "target": ""},
                         {"model": "mystery-y", "target": ""}]))
        r2 = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                               json={"product": "buddy"})
        assert r2.status_code == 400, r2.text
        assert "没有任何目录条目能匹配上" in r2.json()["error"]["message"]
        assert Path(gw.config_path).read_text(encoding="utf-8") == before, "拒绝却写了盘"

    async def test_a7_second_run_is_idempotent_and_shares_write_exit(self, vendor, make_gateway,
                                                                     client, monkeypatch):
        """A-7/A-8：重复初始化不重复挂载（幂等），回执字段集合 ⊇ 手动「保存」那份 = 同一条出口。"""
        gw = await make_gateway(_cfg(vendor.port, [chat_res("A", name="glm-4.6-flash")]))
        _seed("am-7")
        monkeypatch.setitem(buddy._HOOKS, "list_models", _catalog("sn-glm-5-3"))
        url = f"{gw.base_url}/admin/api/accounts/auto-map"
        reply = _json([{"model": "sn-glm-5-3", "target": "glm-5.3"}])

        gw.runtime.adapters["res-A"] = _Stub(reply=reply)
        first = (await client.post(url, json={"product": "buddy"})).json()
        assert first["added"] == 1 and first["already"] == 0

        gw.runtime.adapters["res-A"] = _Stub(reply=reply)
        r2 = await client.post(url, json={"product": "buddy"})
        assert r2.status_code == 200, r2.text
        again = r2.json()
        assert again["added"] == 0 and again["already"] == 1, "重复初始化把映射挂了两遍"
        assert len([b for b in _saved(gw)["product_models"]
                    if b["model"] == "sn-glm-5-3"]) == 1

        # 同一条写入出口：手动保存那份字段一个都不少（不是"初始化另有一套回执"）
        man = await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                                json={"product": "buddy",
                                      "items": [{"model": "sn-glm-5-3", "target": "glm-5.3"}]})
        assert man.status_code == 200, man.text
        missing = set(man.json()) - set(first)
        assert not missing, f"auto-map 回执缺字段：{missing}"
        for k in ("product", "created_models", "accounts", "added", "already", "skipped",
                  "reload", "turned_on", "turned_off", "product_models", "accounts_mapped"):
            assert k in first, k

    async def test_a8_credentials_never_enter_prompt_or_response(self, vendor, make_gateway,
                                                                 client, monkeypatch):
        """A-8：账号凭据明文既不出现在响应里，也不出现在送给模型的请求体里（铁律 1）。"""
        gw = await make_gateway(_cfg(vendor.port, [chat_res("A", name="glm-4.6-flash")]))
        _seed("am-8")
        monkeypatch.setitem(buddy._HOOKS, "list_models", _catalog("sn-glm-5-3"))
        stub = _Stub(reply=_json([{"model": "sn-glm-5-3", "target": "glm-5.3"}]))
        gw.runtime.adapters["res-A"] = stub

        r = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                              json={"product": "buddy"})
        assert r.status_code == 200, r.text
        assert SECRET not in r.text
        assert SECRET not in yaml.safe_dump(stub.calls, allow_unicode=True)
        # 送给模型的内容只有：名单 + 目录条目 id/展示名/能力事实
        user_msg = stub.calls[0]["body"]["messages"][1]["content"]
        assert "sn-glm-5-3" in user_msg and "网关模型名单" in user_msg
        assert "access_token" not in user_msg

    async def test_a9_budget_stops_analysis_and_says_so(self, vendor, make_gateway, client,
                                                       monkeypatch):
        """A-9：目录行数超过分析预算 ⇒ 只分析预算内的行，其余由正则补齐，`reason` 逐数说清。

        预算在这里被改小（而不是造 200 行目录）：判据是"超预算时行为与回执一致"，
        与预算数值本身无关。第三批故意送去一个模型不认识的 id，验证"模型没给出结论"
        的行同样由正则补，而不是被算成分析覆盖。
        """
        gw = await make_gateway(_cfg(vendor.port, [chat_res("A", name="glm-4.6-flash")]))
        _seed("am-9")
        monkeypatch.setitem(buddy._HOOKS, "list_models",
                            _catalog("glm-5.3", "mystery-x", "sn-glm-5-3"))
        monkeypatch.setattr(aa, "_ANALYZE_ROWS_PER_CALL", 1)
        monkeypatch.setattr(aa, "_ANALYZE_MAX_CALLS", 2)
        stub = _Stub(reply=_json([{"model": "glm-5.3", "target": "glm-5.3"}]))
        gw.runtime.adapters["res-A"] = stub

        r = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                              json={"product": "buddy"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["via"] == "model" and body["analyzed"] == 2 and body["entries"] == 3
        assert len(stub.calls) == 2
        assert "模型分析了 2/3 行" in body["reason"]
        # 第 3 行没送去分析 ⇒ 正则补（sn-glm-5-3 命中 glm-5.3）；mystery-x 谁都不认得 ⇒ 不编造
        assert body["matched_model"] == 1 and body["matched_regex"] == 1
        assert body["unmatched"] == 1

    async def test_a10_unknown_product_is_refused(self, vendor, make_gateway, client):
        """A-10：未登记产品 400（与账号面其余端点同一个 `_product_meta` 判据点）。"""
        gw = await make_gateway(_cfg(vendor.port, [chat_res("A", name="glm-4.6-flash")]))
        r = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                              json={"product": "no-such-product"})
        assert r.status_code == 400
        assert "no-such-product" in r.json()["error"]["message"]

    async def test_a11_no_accounts_means_nothing_to_write(self, vendor, make_gateway,
                                                          client, monkeypatch):
        """A-11：产品没有已启用账号 ⇒ 沿用写入出口那条 400（映射无处可落，不空跑）。

        钉的是"初始化"与"保存"**共用同一道闸门**：这条如果各写一份，初始化就会出现
        「分析成功、added:0、HTTP 200」那种最难查的假成功。
        """
        gw = await make_gateway(_cfg(vendor.port, [chat_res("A", name="glm-4.6-flash")]))
        monkeypatch.setitem(buddy._HOOKS, "list_models", _catalog("sn-glm-5-3"))
        gw.runtime.adapters["res-A"] = _Stub(
            reply=_json([{"model": "sn-glm-5-3", "target": "glm-5.3"}]))

        r = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                              json={"product": "buddy"})
        assert r.status_code == 400, r.text
        assert "没有已启用的账号" in r.json()["error"]["message"]
        assert "product_models" not in _saved(gw) or not _saved(gw)["product_models"]


    async def test_a12_real_outbound_leg_through_production_adapter(self, vendor, make_gateway,
                                                                   client, monkeypatch):
        """A-12：分析腿走**生产出站栈**（真 HTTP 到本地 FakeVendor，不是替身适配器）。

        🔴 为什么单独一条：替身只能证明"我调了那个方法"，证不了"这条出站通道存在、请求体
        形态上游认得"（验收纪律：mock 全绿不等于通道存在）。这里用 `gateway_config` 造的
        真资源（openai 协议 → FakeVendor），脚本回一份 JSON ⇒ 必须被采纳并落库。
        """
        gw = await make_gateway(_cfg(vendor.port, [chat_res("A", name="glm-4.6-flash")]))
        _seed("am-12")
        monkeypatch.setitem(buddy._HOOKS, "list_models", _catalog("zzz-real-1", "sn-glm-5-3"))
        vendor.set("sk-A", Ok(content=_json([
            {"model": "zzz-real-1", "target": "glm-5.3"},
            {"model": "sn-glm-5-3", "target": ""},          # 这条留给正则补
        ])))
        # 运行态用的是**真**适配器（本用例绝不塞替身）
        assert "res-A" in gw.runtime.adapters
        assert not isinstance(gw.runtime.adapters["res-A"], _Stub)

        r = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                              json={"product": "buddy"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["via"] == "model" and body["matched_model"] == 1
        assert body["matched_regex"] == 1 and body["analyzed_by"] == "glm-4.6-flash"

        calls = vendor.bodies_for("sk-A")
        assert len(calls) == 1, f"一次初始化发了 {len(calls)} 次出站"
        sent = calls[0]
        assert sent["stream"] is False and sent["model"] == "vm-A"
        joined = json.dumps(sent["messages"], ensure_ascii=False)
        assert "zzz-real-1" in joined and "sn-glm-5-3" in joined and "glm-5.3" in joined
        assert SECRET not in joined
        bits = {(b["model"], b["system_model"]) for b in _saved(gw)["product_models"]}
        assert bits == {("zzz-real-1", "glm-5.3"), ("sn-glm-5-3", "glm-5.3")}

    async def test_a13_real_leg_failure_degrades_over_http(self, vendor, make_gateway,
                                                          client, monkeypatch):
        """A-13：真出站**报错**（上游 500）时也照样整表降级 —— 这条只在真 HTTP 形状上才存在
        （替身抛的是异常对象，生产适配器抛的是 `UpstreamError`，两支文案不同）。"""
        gw = await make_gateway(_cfg(vendor.port, [chat_res("A", name="glm-4.6-flash")]))
        _seed("am-13")
        monkeypatch.setitem(buddy._HOOKS, "list_models", _catalog("sn-glm-5-3"))
        vendor.set("sk-A", Err(status=500, message="vendor exploded"))

        r = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                              json={"product": "buddy"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["via"] == "regex" and "模型分析未能完成" in body["reason"]
        assert "vendor exploded" in body["reason"], "上游原话要带给用户，不许只剩'失败'两个字"
        assert [(b["model"], b["system_model"]) for b in _saved(gw)["product_models"]] \
            == [("sn-glm-5-3", "glm-5.3")]


class TestParseAnalysis:
    """`_parse_analysis` 的三支丢弃判据（端点级只测到其中一支，这里逐支钉死）。"""

    def test_hallucinated_target_and_foreign_row_dropped(self):
        ids = {"a-1", "a-2"}
        allowed = {"glm-5.3"}
        text = "```json\n" + _json([
            {"model": "a-1", "target": "glm-5.3"},
            {"model": "a-2", "target": "glm-5-3-extra"},   # 名单外
            {"model": "a-3", "target": "glm-5.3"},          # 本批没送出去
            "not-an-object",                                # 形态不符
            {"model": "a-2", "target": ""},                 # 空串 = 不确定，不算丢弃
        ]) + "\n```"
        out, dropped = aa._parse_analysis(text, ids, allowed)
        assert out == {"a-1": "glm-5.3"}
        assert dropped == 3

    def test_bad_shapes_raise_rather_than_returning_nothing(self):
        """「回答里根本没有结构」必须**抛**（由调用方整表降级），不能悄悄返回空表 ——
        空表在端点里会走"模型一条也没给出"那支，原因就被写成假的那一句。"""
        for text in ("没有 JSON", '{"other":1}', '{"mappings":"no"}'):
            with pytest.raises(ValueError):
                aa._parse_analysis(text, {"a-1"}, {"glm-5.3"})
