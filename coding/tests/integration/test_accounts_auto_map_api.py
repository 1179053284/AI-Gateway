"""INT 「初始化映射」`POST /admin/api/accounts/auto-map`（2026-10-03 用户指令）。

需求原话拆成判据：
- 「调用网关内任意可用的 DeepSeek flash 模型，然后分析这些模型应该匹配哪个网关模型」
  ⇒ 有可用 chat 腿时**由模型判定**，且优先低档位那条（A-1/A-2）；
- 「如果网关内没有可用的模型降级使用正则进行网关模型匹配」
  ⇒ 选不出腿 / 出站失败 / 回答不可解析 / 一条都没采纳 ⇒ **整表**走 `_enum_suggest`（A-3/A-4/A-5）；
- 落库**只有「保存」那一个入口**（`POST /admin/api/accounts/mappings`）；本端点只出建议（A-7）。
- 🔴 2026-10-05 第四次指示（草稿制：「调用AI分析结果直接回填到弹窗内，但不提交保存，仅在前端进行展示
  …… 所有修改、设置 点击保存提交数据后才能入库存储」）⇒ 这条腿**从不写盘**（`written` 恒 `false`），
  而"每次只分析屏幕上还空着的那些行"由两道闸门共同保证（INT-111 / INT-112）：
  ① 服务端 `_map_enabled(...) is None`（配置里从没落过位的行才送）；
  ② 请求带 `models:[目录条目 id…]` = 界面当前显示为「暂不设置」的那些行
     （草稿制下"已配置"不再等于"待补" —— AI 填进下拉但还没保存的行仍然没落库，
     只按①判就会每次点击都重烧一遍同一批额度）。

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

        before = Path(gw.config_path).read_text(encoding="utf-8")
        r = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                              json={"product": "buddy"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["via"] == "model" and body["analyzed_by"] == "glm-4.6-flash"
        assert body["entries"] == 3 and body["analyzed"] == 3
        assert body["matched_model"] == 1 and body["matched_regex"] == 1
        assert body["unmatched"] == 1
        # 🔴 草稿制（2026-10-05 第三次裁定：「调用AI分析结果直接回填到弹窗内，但不提交保存」）：
        #    这条腿**一个字节都不写**，答案只住在 `suggested` 里；写面那套字段不许出现在这份回执上
        #    （递过去就等于给界面第二套真相 —— 它会以为"已经入库"）。
        assert body["written"] is False
        assert {(s["model"], s["target"], s["engine"]) for s in body["suggested"]} == {
            ("zzz-unique-1", "claude-sonnet-4", "model"),
            ("sn-glm-5-3", "glm-5.3", "regex")}
        assert not ({"added", "already", "moved", "product_models", "reload", "accounts_mapped"}
                    & set(body)), sorted({"added", "already", "moved", "product_models",
                                          "reload", "accounts_mapped"} & set(body))
        assert Path(gw.config_path).read_text(encoding="utf-8") == before, "AI 匹配把建议写进配置了"
        # 送出去的确实是所选那条腿自己的凭据与供应商模型名（替身收到的）
        assert len(stub.calls) == 1
        assert stub.calls[0]["key"] == "sk-A" and stub.calls[0]["model"] == "vm-A"
        # 模型编出来的那个名字**没有**进建议表（丢弃 ≠ 落库，也 ≠ 递给界面）
        assert "gpt-9-ultra" not in {s["target"] for s in body["suggested"]}
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
        assert body["written"] is False
        assert [(s["model"], s["target"]) for s in body["suggested"]] == [("sn-glm-5-3", "glm-5.3")]
        assert not _saved(gw).get("product_models"), "降级正则那条腿也不许写盘"

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
        # 降级后照样**给出建议**（用户点一次就拿到结果），但和模型腿一样一个字都不写
        assert body["written"] is False
        assert [(s["model"], s["target"]) for s in body["suggested"]] == [("sn-glm-5-3", "glm-5.3")]
        assert not _saved(gw).get("product_models")

    async def test_a5_unparseable_answer_degrades(self, vendor, make_gateway, client, monkeypatch):
        """A-5：回答不是 JSON / 是空内容 ⇒ 同一支整表降级（两条独立形状各测一次）。

        🔴 两条形状各起一台实例：2026-10-05 起这颗钮**只补未配置的行**，第一条形状已经把那一行
        写进配置 ⇒ 同一台实例上第二次调用会走「全部已配置」的零出站早退支，测不到降级这条路。
        """
        for reply, want in (("抱歉，我需要更多信息才能判断。", "没有 JSON 对象"), ("", "空内容")):
            gw = await make_gateway(_cfg(vendor.port, [chat_res("A", name="glm-4.6-flash")]))
            _seed(f"am-5-{len(want)}")
            monkeypatch.setitem(buddy._HOOKS, "list_models", _catalog("sn-glm-5-3"))
            gw.runtime.adapters["res-A"] = _Stub(reply=reply)
            r = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                                  json={"product": "buddy"})
            assert r.status_code == 200, r.text
            assert r.json()["via"] == "regex" and want in r.json()["reason"], (reply, r.json())

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
        msg = r2.json()["error"]["message"]
        # 判据随文案前进（不是放宽）：400 必须**说清是几行没匹配上**，
        # 因为自 2026-10-05 起"待匹配的行"只是目录的一个子集，光说"目录条目"会读成整表都试过了
        assert "2 行待匹配的目录条目里没有任何一条能匹配上网关模型" in msg, msg
        assert Path(gw.config_path).read_text(encoding="utf-8") == before, "拒绝却写了盘"

    async def test_a7_zero_write_and_screen_scope_stops_the_second_burn(self, vendor, make_gateway,
                                                                       client, monkeypatch):
        """INT-111（随 2026-10-05 第三次裁定改写）：AI 这条腿**从不写盘**，
        而"这一行还要不要再问一次模型"由**屏幕上的空集**决定（`models` 参数）。

        旧契约（上一轮）：`written:false` 只在"全部已配置"时出现 —— 因为那时答案已经落库了。
        草稿制之后配置里永远不会有 AI 的痕迹，所以那条判据换不成真：**任何一次调用都零写盘**；
        而"不重跑同一批行"这件事只能由界面说（它才知道哪些格子已经被回填），
        于是三条腿缺一不可：
        ① 带 `models` 且那一行还空着 ⇒ 发一次出站、出一条建议、**盘上一字未动**；
        ② 同一行已被回填（`models` 里不再含它）⇒ **零出站 + 零建议**，`via:"none"` + `kept` 报数；
        ③ 不带 `models` ⇒ 回落到"全部未落位的行"，于是**会**再问一次模型
           （这条不是缺陷，是"为什么前端必须带那份清单"的反证，所以把它钉住而不是藏起来）。
        """
        gw = await make_gateway(_cfg(vendor.port, [chat_res("A", name="glm-4.6-flash")]))
        _seed("am-7")
        monkeypatch.setitem(buddy._HOOKS, "list_models", _catalog("sn-glm-5-3"))
        url = f"{gw.base_url}/admin/api/accounts/auto-map"
        reply = _json([{"model": "sn-glm-5-3", "target": "glm-5.3"}])
        before = Path(gw.config_path).read_text(encoding="utf-8")

        stub1 = _Stub(reply=reply)
        gw.runtime.adapters["res-A"] = stub1
        first = (await client.post(url, json={"product": "buddy",
                                              "models": ["sn-glm-5-3"]})).json()
        assert len(stub1.calls) == 1, stub1.calls
        assert first["written"] is False and first["analyzed"] == 1 and first["kept"] == 0
        assert [(s["model"], s["target"]) for s in first["suggested"]] == [("sn-glm-5-3", "glm-5.3")]
        assert Path(gw.config_path).read_text(encoding="utf-8") == before, "第一次调用就写了盘"

        # ② 那一行已经填进下拉（还没保存）⇒ 界面不再把它列进 `models`
        stub2 = _Stub(reply=reply)
        gw.runtime.adapters["res-A"] = stub2
        again = (await client.post(url, json={"product": "buddy", "models": []})).json()
        assert again["written"] is False and again["kept"] == 1 and again["suggested"] == []
        assert again["via"] == "none" and again["analyzed"] == 0
        assert "reload" not in again and "product_models" not in again, "没写盘却递出写面字段 = 假陈述"
        assert stub2.calls == [], f"屏幕上已填的行又被送去烧了一次额度：{len(stub2.calls)}"
        assert Path(gw.config_path).read_text(encoding="utf-8") == before

        # ③ 不带 `models` 的那类调用方（含旧客户端）⇒ 回落"全部未落位"，会再问一次
        stub3 = _Stub(reply=reply)
        gw.runtime.adapters["res-A"] = stub3
        legacy = (await client.post(url, json={"product": "buddy"})).json()
        assert len(stub3.calls) == 1 and legacy["analyzed"] == 1, "回落口径变了 ⇒ 前端漏传时会静默不干活"
        assert Path(gw.config_path).read_text(encoding="utf-8") == before

        # 🔴 两份回执**故意不同形**：写面那份只属于「保存」（`mappings`），建议那份不许带写面字段
        man = (await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                                 json={"product": "buddy",
                                       "items": [{"model": "sn-glm-5-3", "target": "glm-5.3"}]})).json()
        for k in ("added", "already", "moved", "product_models", "reload", "accounts_mapped",
                  "turned_on", "turned_off", "emptied_models", "created_models", "skipped"):
            assert k in man, f"唯一写入口的回执缺字段：{k}"
        assert man["added"] == 1 and man["product_models"], man
        assert "written" not in man, "不为对称而给写面契约臆造新字段（`written` 只属于建议那份）"
        assert Path(gw.config_path).read_text(encoding="utf-8") != before, "保存那一次必须真的写盘"

    async def test_a14_two_gates_keep_configured_rows_out_of_scope(self, vendor, make_gateway,
                                                                  client, monkeypatch):
        """INT-112（随草稿制改写）：**两道闸门缺一不可** —— ① 配置里已落位的行永不送分析
        （哪怕前端把它的 id 一起传上来）；② 屏幕上已填值的行由前端负责不传（见 A-7 ②）。

        这条钉的是"常驻的这颗钮不许盖掉用户逐行配好的东西"：草稿制之后 AI 自己不写盘，
        覆盖的风险搬到了**保存**那一次 —— 而保存提交的是界面上的值，所以"已配置那行根本没被
        重问模型"仍然是必须在这里成立的一条（它一旦不成立，模型答的 `kimi-k3` 就会出现在下拉里，
        用户按保存 = 覆盖发生）。三条腿：
        ① 出站请求体里出现未落位那行的 id、**不出现**已落位那行的 id；
        ② 已落位那行的产品位目标与开关位在配置里逐字未动；
        ③ 回执 `kept=1` + `matched_*` 只数送分析那几行，且**整份配置一字未改**。
        """
        gw = await make_gateway(_cfg(vendor.port, [chat_res("A", name="glm-4.6-flash")]))
        _seed("am-14")
        monkeypatch.setitem(buddy._HOOKS, "list_models",
                            _catalog("sn-glm-5-3", "sn-deepseek-v4-pro"))
        url = f"{gw.base_url}/admin/api/accounts/auto-map"
        # 先把 sn-glm-5-3 逐行配好（手动腿 = 保存），并且刻意让它指向一个模型分析会给出的**不同**目标
        man = await client.post(f"{gw.base_url}/admin/api/accounts/mappings",
                                json={"product": "buddy",
                                      "items": [{"model": "sn-glm-5-3", "target": "glm-5.3",
                                                 "enabled": False}]})
        assert man.status_code == 200, man.text
        # 关着的新映射只写位、不建条目（`enabled=false` 那条早退支）⇒ added=0 才是对的
        assert man.json()["moved"] == 0 and man.json()["added"] == 0, man.json()
        before = Path(gw.config_path).read_text(encoding="utf-8")

        stub = _Stub(reply=_json([{"model": "sn-glm-5-3", "target": "kimi-k3"},
                                  {"model": "sn-deepseek-v4-pro", "target": "deepseek-v4-pro"}]))
        gw.runtime.adapters["res-A"] = stub
        # 🔴 前端故意"报错"：把已落位那行也列进 `models` ⇒ 服务端那道闸门必须还拦得住
        out = (await client.post(url, json={"product": "buddy",
                                            "models": ["sn-glm-5-3", "sn-deepseek-v4-pro"]})).json()
        assert len(stub.calls) == 1, stub.calls
        sent = json.dumps(stub.calls[0]["body"], ensure_ascii=False)
        assert "sn-deepseek-v4-pro" in sent, "未落位那行没进送模型的清单"
        assert "sn-glm-5-3" not in sent, "已落位那行还被送去分析 ⇒ 覆盖只是时间问题"
        assert out["kept"] == 1 and out["written"] is False, out
        assert [(s["model"], s["target"]) for s in out["suggested"]] == [
            ("sn-deepseek-v4-pro", "deepseek-v4-pro")], out
        # ③ 整份配置一字未改（建议不落库；已配置那行当然也没被动过）
        assert Path(gw.config_path).read_text(encoding="utf-8") == before, "AI 这条腿写了盘"
        saved = _saved(gw)
        pm = {(x["product"], x["model"]): x for x in saved["product_models"]}
        assert pm[("buddy", "sn-glm-5-3")]["system_model"] == "glm-5.3", pm
        assert pm[("buddy", "sn-glm-5-3")]["enabled"] is False, pm
        assert ("buddy", "sn-deepseek-v4-pro") not in pm, "建议被顺手建成了位"
        assert "kimi-k3" not in {m["name"] for m in saved["models"]}, "幻觉目标顺手建了模型"

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

    async def test_a11_no_accounts_still_analyzes_and_writes_nothing(self, vendor, make_gateway,
                                                                     client, monkeypatch):
        """A-11（随草稿制改写）：产品没有已启用账号 ⇒ **分析照做、建议照给、盘上一字未动**。

        旧契约是"沿用写入出口那道 400（映射无处可落，不空跑）"。草稿制之后这条不成立了，
        而且**不该成立**：AI 这条腿本来就不写盘，"有没有账号可挂"是**保存**那一次的事。
        留着那道 400 会长出第二种假态 —— 用户在没账号时连"网关建议挂哪个"都看不到，
        而界面上那颗钮此时是禁用的（`setMode` 的判据 = 有没有账号 + 目录非空，静态门 V22 钉），
        两边各说一套 = 两套真相。所以这里钉三件事：① 200 + 建议；② 零写盘；
        ③ 「无处可挂」这件事由保存那次拒（`mappings` 那条 400 判据在 catalog_mapping 那支钉着）。
        """
        gw = await make_gateway(_cfg(vendor.port, [chat_res("A", name="glm-4.6-flash")]))
        monkeypatch.setitem(buddy._HOOKS, "list_models", _catalog("sn-glm-5-3"))
        gw.runtime.adapters["res-A"] = _Stub(
            reply=_json([{"model": "sn-glm-5-3", "target": "glm-5.3"}]))
        before = Path(gw.config_path).read_text(encoding="utf-8")

        r = await client.post(f"{gw.base_url}/admin/api/accounts/auto-map",
                              json={"product": "buddy"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["written"] is False
        assert [(s["model"], s["target"]) for s in body["suggested"]] == [("sn-glm-5-3", "glm-5.3")]
        assert not _saved(gw).get("product_models"), "没有账号时 AI 照样不许写盘"
        assert Path(gw.config_path).read_text(encoding="utf-8") == before


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
        assert body["written"] is False
        assert {(s["model"], s["target"]) for s in body["suggested"]} == {
            ("zzz-real-1", "glm-5.3"), ("sn-glm-5-3", "glm-5.3")}
        assert not _saved(gw).get("product_models"), "真出站腿跑通了就顺手写盘 = 草稿制被破坏"

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
        assert body["written"] is False
        assert [(s["model"], s["target"]) for s in body["suggested"]] == [("sn-glm-5-3", "glm-5.3")]
        assert not _saved(gw).get("product_models"), "真 HTTP 降级这条腿也不能顺手写盘"


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
