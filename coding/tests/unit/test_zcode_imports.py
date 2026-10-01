"""ZCode 导入源转换单测（Q31，2026-10-01；`upstream/zcode/imports.py`）。

**无网络、无真实凭据**：全部夹具为 tmp 目录里的合成数据；加密往返用本机 secret
（`crypto.encrypt/decrypt` 同机配对，值均为测试造的假令牌）。

判据逐条对应参考实现（只读对照，逐行出处在 `imports.py` docstring）：
- 面板 `import-account.js`：形态识别（:8-18）、校验尺（:39-46）、家族解析（:80-104）、
  凭据键白名单（:113-135）、归一化（:138-173）、buildConfig（:182-214）、
  verifyWritten（:221-253）；
- 面板 `settings.js:395-430`：账号目录解析；
- zcode-switch：`~/.zcode-switch/accounts/<uuid>.json` 实测形态（凭据/配置原样透传）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from model_gateway.upstream.zcode import crypto, imports as zim

JWT = "eyJhbGciOiJIUzI1NiJ9.QUJDREVGR0g.SIGNATURE_PART"
MID = "c363eb06-2b63-4c59-9c69-1c5794ccf0cb"


def _panel_account(root: Path, name: str, *, mid: str = MID, family: str = "zai",
                   cred: dict | None = None, cfg: dict | None = None,
                   with_meta: dict | None = None, v2_cred: bool = True,
                   v2_cfg: bool = True, top_cfg: bool = True) -> Path:
    """合成一个面板账号目录（值全是假 `enc:v1:`，因为透传路径不解密）。"""
    d = root / name
    v2 = d / "data" / ".zcode" / "v2"
    v2.mkdir(parents=True, exist_ok=True)
    meta = {"device_mid": mid, "family": family, "via": "import"}
    meta.update(with_meta or {})
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if v2_cred:
        (v2 / "credentials.json").write_text(json.dumps(cred or {
            "zcodejwttoken": "enc:v1:aa.bb.cc",
            "oauth:active_provider": "enc:v1:dd.ee.ff",
            f"oauth:{family}:access_token": "enc:v1:gg.hh.ii",
        }), encoding="utf-8")
    if v2_cfg:
        (v2 / "config.json").write_text(json.dumps(cfg or {
            "provider": {f"builtin:{family}-start-plan": {"kind": "anthropic"}},
        }), encoding="utf-8")
    if top_cfg:
        (d / "config.json").write_text(json.dumps(cfg or {
            "provider": {f"builtin:{family}-start-plan": {"kind": "anthropic"}},
        }), encoding="utf-8")
    return d


def _switch_file(root: Path, stem: str, *, name: str = "sw1", mid: str = MID,
                 cred: dict | None = None, cfg: dict | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    p = root / f"{stem}.json"
    p.write_text(json.dumps({
        "id": stem, "name": name, "created_at": "2026-09-21 10:26",
        "updated_at": "2026-09-24 23:34", "hash": "0123456789abcdef",
        "virtual_device_mid": mid, "virtual_arms_uid": "uid_x",
        "credentials": cred or {
            "zcodejwttoken": "enc:v1:11.22.33",
            "oauth:active_provider": "enc:v1:44.55.66",
            "oauth:bigmodel:access_token": "enc:v1:77.88.99",
        },
        "config": cfg or {"provider": {"builtin:bigmodel-start-plan": {}}},
    }, ensure_ascii=False), encoding="utf-8")
    return p


# ============ 形态识别（detect_payload_form）============

def test_detect_forms():
    assert zim.detect_payload_form({"name": "a", "jwt": JWT, "device_mid": MID}) == zim.FORM_PASTE
    assert zim.detect_payload_form(
        {"family": "zai", "credentials": {"oauth:zai:access_token": "eyJx"}}) == zim.FORM_PASTE
    assert zim.detect_payload_form(
        {"account": {"name": "a", "jwtToken": JWT, "deviceMid": MID}}) == zim.FORM_PASTE
    assert zim.detect_payload_form(
        {"name": "a", "credentials.json": {"k": "v"}}) == zim.FORM_GATEWAY
    assert zim.detect_payload_form(
        {"id": "x", "hash": "h", "virtual_device_mid": MID,
         "credentials": {}, "config": {}}) == zim.FORM_SWITCH
    assert zim.detect_payload_form({"name": "a", "device_mid": "m"}) == zim.FORM_META
    assert zim.detect_payload_form({}) == zim.FORM_UNKNOWN
    assert zim.detect_payload_form([1, 2]) == zim.FORM_UNKNOWN
    assert zim.detect_payload_form("not json at all") == zim.FORM_UNKNOWN
    # JSON 文本也认（从剪贴板/文件来的文本形态）
    assert zim.detect_payload_form(json.dumps({"name": "a", "jwt": JWT, "mid": MID})) \
        == zim.FORM_PASTE


# ============ 粘贴形态 → 载荷（面板 importAccount 等价）============

def test_paste_legacy_form_encrypts_and_builds_bigmodel_config():
    """老格式（`{name,jwt,device_mid}`）：默认 family = bigmodel（`import-account.js:58`）。"""
    p = zim.paste_to_payload({"name": "a1", "jwt": JWT, "device_mid": MID})

    assert p["name"] == "a1" and p["device_mid"] == MID
    raw = p["credentials.json"]
    assert raw["zcodejwttoken"].startswith(crypto.PREFIX)
    assert crypto.decrypt(raw["zcodejwttoken"]) == JWT          # 加密往返（本机 secret）
    assert crypto.decrypt(raw["oauth:active_provider"]) == "bigmodel"
    assert set(raw) == {"zcodejwttoken", "oauth:active_provider"}  # 没给 oauth 就不写
    fb = p["config.json"]["provider"]["builtin:bigmodel-start-plan"]
    assert fb["kind"] == "anthropic" and fb["enabled"] is True
    assert fb["options"]["apiKey"] == JWT
    assert "zcode-plan" in fb["options"]["baseURL"]
    assert p["meta"] == {"family": "bigmodel", "family_source": "default"}


def test_paste_family_credentials_form():
    """新格式（小店新版下发）：family + credentials → active_provider 与 oauth 键对齐家族。"""
    p = zim.paste_to_payload({
        "name": "z1", "jwt": JWT, "device_mid": MID, "family": "zai",
        "credentials": {"oauth:zai:access_token": JWT,
                        "oauth:zai:user_info": '{"sub":"u1","name":"n"}'},
    })
    raw = p["credentials.json"]
    assert crypto.decrypt(raw["oauth:active_provider"]) == "zai"
    assert crypto.decrypt(raw["oauth:zai:access_token"]) == JWT
    assert json.loads(crypto.decrypt(raw["oauth:zai:user_info"]))["sub"] == "u1"
    assert "oauth:zai:refresh_token" not in raw                # 没给的键不编造
    assert "builtin:zai-start-plan" in p["config.json"]["provider"]
    assert p["meta"]["family_source"] == "field"


def test_paste_account_wrapper_and_alt_keys():
    """外包一层 + 别名键（`jwtToken`/`deviceMid`），家族从 credentials 键推断。"""
    p = zim.paste_to_payload({
        "account": {"name": "w1", "jwtToken": JWT, "deviceMid": MID,
                    "credentials": {"oauth:zai:access_token": JWT}},
    })
    assert p["name"] == "w1" and p["device_mid"] == MID
    assert crypto.decrypt(p["credentials.json"]["oauth:active_provider"]) == "zai"
    assert p["meta"]["family_source"] == "credentials"


def test_paste_enc_v1_value_passes_through_not_double_encrypted():
    """⚠️ 刻意收窄：已是 `enc:v1:` 的粘贴值原样透传（面板会二次加密 —— 那是缺陷面）。"""
    already = "enc:v1:AAA.BBB.CCC"
    p = zim.paste_to_payload({
        "name": "e1", "jwt": JWT, "device_mid": MID,
        "credentials": {"oauth:bigmodel:access_token": already},
    })
    assert p["credentials.json"]["oauth:bigmodel:access_token"] == already


def test_paste_template_scrubs_foreign_providers_and_credentials():
    """模板清洗（`import-account.js:182-214`）：只留本家族、清凭据残留、nodeKey 填 jwt。"""
    signing = "0123456789abcdef0123456789abcdef.somesecret123"   # 32hex.<secret>
    template = {"provider": {
        "builtin:zai": {"nodeKey": True, "options": {"apiKey": "sk-old", "keep": "v"}},
        "builtin:bigmodel-start-plan": {"name": "别家族", "options": {"apiKey": "sk-leak"}},
        "custom-1": {"options": {"apiKey": "sk-foreign"}},
    }}
    p = zim.paste_to_payload(
        {"name": "t1", "jwt": JWT, "device_mid": MID, "family": "zai"}, template=template)
    prov = p["config.json"]["provider"]
    assert set(prov) == {"builtin:zai", "builtin:zai-start-plan"}
    assert prov["builtin:zai"]["nodeKey"] == JWT
    assert prov["builtin:zai"]["options"]["apiKey"] == ""       # 旧凭据残留已清
    assert prov["builtin:zai"]["options"]["keep"] == "v"        # 非凭据字段保留
    assert prov["builtin:zai-start-plan"]["options"]["apiKey"] == JWT

    template["provider"]["builtin:zai"]["options"]["leak"] = signing   # 签名密钥形态
    p2 = zim.paste_to_payload(
        {"name": "t2", "jwt": JWT, "device_mid": MID, "family": "zai"}, template=template)
    assert p2["config.json"]["provider"]["builtin:zai"]["options"]["leak"] == ""


def test_paste_template_base_url_not_zcode_plan_falls_back():
    template = {"provider": {"builtin:zai-start-plan": {
        "options": {"baseURL": "https://example.com/other"}}}}
    p = zim.paste_to_payload(
        {"name": "t3", "jwt": JWT, "device_mid": MID, "family": "zai"}, template=template)
    base = p["config.json"]["provider"]["builtin:zai-start-plan"]["options"]["baseURL"]
    assert "zcode-plan" in base


@pytest.mark.parametrize("obj,code", [
    ({"name": "bad name!", "jwt": JWT, "device_mid": MID}, "bad-name"),
    ({"name": "../etc/passwd", "jwt": JWT, "device_mid": MID}, "bad-name"),
    ({"name": "a", "device_mid": MID}, "bad-jwt"),
    ({"name": "a", "jwt": "not-a-jwt", "device_mid": MID}, "bad-jwt"),
    ({"name": "a", "jwt": JWT, "device_mid": "not-a-uuid"}, "bad-mid"),
    ({"name": "a", "jwt": JWT, "device_mid": MID, "family": "openai"}, "bad-family"),
    ({"name": "a", "jwt": JWT, "device_mid": MID,
      "credentials": {"oauth:openai:access_token": JWT}}, "bad-family"),  # 未知家族键
    ({"name": "a", "jwt": JWT, "device_mid": MID, "family": "zai",
      "credentials": {"oauth:zai:user_info": ""}}, "bad-cred"),            # 空值
    ({"name": "a", "jwt": JWT, "device_mid": MID, "family": "zai",
      "credentials": {"oauth:zai:access_token": "abc"}}, "bad-cred"),     # 形态不认识
    ({"name": "a", "jwt": JWT, "device_mid": MID, "family": "zai",
      "credentials": {"oauth:zai:access_token": "0123456789abcdef0123456789abcdef.s"}},
     "bad-cred"),                                                         # 签名密钥
    ({"name": "a", "jwt": JWT, "device_mid": MID, "family": "zai",
      "credentials": {"oauth:zai:user_info": "{not json"}}, "bad-cred"),
    ({"name": "a", "jwt": JWT, "device_mid": MID, "family": "zai",
      "credentials": {"oauth:zai:access_token": 123}}, "bad-cred"),
    ({"name": "a", "jwt": JWT, "device_mid": MID, "family": "zai",
      "credentials": {"oauth:zai:access_token": "  "}}, "bad-cred"),
    ({"name": "a", "jwt": JWT, "device_mid": MID, "family": "zai",
      "credentials": {"oauth:zai:access_token": "eyJ" + "x" * 200_001}}, "bad-cred"),
    ([1, 2, 3], "not-object"),
    ("   ", "empty"),
    ("{broken", "not-json"),
])
def test_paste_rejects_malformed(obj, code):
    with pytest.raises(zim.ImportValidationError) as ei:
        zim.paste_to_payload(obj)
    assert ei.value.code == code


def test_paste_mixed_families_requires_explicit_family():
    with pytest.raises(zim.ImportValidationError) as ei:
        zim.paste_to_payload({
            "name": "a", "jwt": JWT, "device_mid": MID,
            "credentials": {"oauth:zai:access_token": JWT,
                            "oauth:bigmodel:access_token": JWT}})
    assert ei.value.code == "bad-family"


def test_verify_payload_catches_tampered_config():
    p = zim.paste_to_payload({"name": "v1", "jwt": JWT, "device_mid": MID})
    p["config.json"]["provider"]["other-vendor"] = {}
    bad = zim.verify_payload(p, family="bigmodel", jwt=JWT)
    assert any("别的 provider" in x for x in bad)
    del p["credentials.json"]["zcodejwttoken"]
    bad = zim.verify_payload(p, family="bigmodel", jwt=JWT)
    assert any("zcodejwttoken" in x for x in bad)


# ============ 面板账号目录（整份透传）============

def test_from_panel_account_passes_files_through(tmp_path):
    d = _panel_account(tmp_path, "river4812")
    src_cred = json.loads((d / "data/.zcode/v2/credentials.json").read_text(encoding="utf-8"))
    p = zim.from_panel_account(d)
    assert p["name"] == "river4812" and p["device_mid"] == MID
    assert p["family"] == "zai"
    assert p["credentials.json"] == src_cred          # 逐值透传（不重加密/不解密）
    assert "provider" in p["config.json"]
    assert p["meta"] == {"family": "zai"}


def test_from_panel_account_requires_device_mid(tmp_path):
    d = _panel_account(tmp_path, "nomid", with_meta={"device_mid": ""})
    with pytest.raises(zim.ImportValidationError) as ei:
        zim.from_panel_account(d)
    assert ei.value.code == "bad-mid"


def test_from_panel_account_requires_anchor_credential_keys(tmp_path):
    d = _panel_account(tmp_path, "nokeys", cred={"something": "enc:v1:a.b.c"})
    with pytest.raises(zim.ImportValidationError) as ei:
        zim.from_panel_account(d)
    assert ei.value.code == "bad-cred"


def test_from_panel_account_requires_provider_section(tmp_path):
    d = _panel_account(tmp_path, "nocfg", cfg={"other": {}})
    with pytest.raises(zim.ImportValidationError) as ei:
        zim.from_panel_account(d)
    assert ei.value.code == "bad-cfg"


def test_from_panel_account_bad_dir_name(tmp_path):
    d = _panel_account(tmp_path, "ok")
    d2 = d.rename(tmp_path / "bad name!")
    with pytest.raises(zim.ImportValidationError) as ei:
        zim.from_panel_account(d2)
    assert ei.value.code == "bad-name"


# ============ 面板账号库扫描 ============

def test_scan_panel_dir_filters_and_reads(tmp_path):
    good = _panel_account(tmp_path, "good", mid=MID)
    _panel_account(tmp_path, "no-files", mid=MID, v2_cred=False)
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "last").mkdir()
    (tmp_path / "not-a-dir.txt").write_text("x", encoding="utf-8")
    assert good.is_dir()

    entries = zim.scan_panel_dir(str(tmp_path))
    assert [e.name for e in entries] == ["good"]
    assert entries[0].device_mid == MID and entries[0].family == "zai"


def test_scan_panel_dir_default_root_env(monkeypatch, tmp_path):
    _panel_account(tmp_path, "env-acc")
    monkeypatch.setenv("ZPANEL_ACCOUNTS_DIR", str(tmp_path))
    assert zim.default_panel_root() == tmp_path
    assert [e.name for e in zim.scan_panel_dir()] == ["env-acc"]


def test_default_panel_root_reads_panel_settings(monkeypatch, tmp_path):
    """settings.json 的自定义 accountsDir（`settings.js:415-417` 的 `load().accountsDir`）。"""
    monkeypatch.delenv("ZPANEL_ACCOUNTS_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    custom = tmp_path / "custom-accounts"
    custom.mkdir()
    app = tmp_path / "Library" / "Application Support" / "zcode-panel"
    app.mkdir(parents=True)
    (app / "settings.json").write_text(json.dumps(
        {"zcodeExe": "", "accountsDir": str(custom)}), encoding="utf-8")
    assert zim.default_panel_root() == custom


def test_default_panel_root_packaged_default(monkeypatch, tmp_path):
    monkeypatch.delenv("ZPANEL_ACCOUNTS_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Library" / "Application Support" / "zcode-panel").mkdir(parents=True)
    root = zim.default_panel_root()
    assert root == tmp_path / "Library" / "Application Support" / "zcode-panel" / "accounts"
    assert zim.scan_panel_dir() == []          # 目录不存在 → 空表，不抛


# ============ zcode-switch ============

def test_from_switch_json_passes_maps_through(tmp_path):
    f = _switch_file(tmp_path, "1eff0f2f-225c-4d87-8c9c-936ddf3190da", name="enhbhfn2")
    p = zim.from_switch_json(f)
    data = json.loads(f.read_text(encoding="utf-8"))
    assert p["name"] == "enhbhfn2"
    assert p["device_mid"] == MID                       # virtual_device_mid → 设备字段
    assert p["credentials.json"] == data["credentials"]  # as-is
    assert p["config.json"] == data["config"]            # as-is
    assert p["family"] == "bigmodel"
    assert p["meta"] == {"family": "bigmodel"}


def test_from_switch_email_name_sanitized_with_display_mirror(tmp_path):
    f = _switch_file(tmp_path, "aa", name="1971962463@qq.com")
    p = zim.from_switch_json(f)
    assert p["name"] == "1971962463qqcom"               # 网关既有清洗语义
    assert p["meta"]["display_name"] == "1971962463@qq.com"


def test_from_switch_uuid_stem_fallback(tmp_path):
    f = _switch_file(tmp_path, "1eff0f2f-225c-4d87-8c9c-936ddf3190da", name="???")
    p = zim.from_switch_json(f)
    assert p["name"] == "1eff0f2f-225c-4d87-8c9c-936ddf31"   # uuid 截 32
    assert len(p["name"]) == 32


@pytest.mark.parametrize("mutate,code", [
    ({"virtual_device_mid": ""}, "bad-mid"),
    ({"credentials": {}}, "bad-cred"),
    ({"config": {}}, "bad-cfg"),
])
def test_from_switch_json_rejects_incomplete(tmp_path, mutate, code):
    f = _switch_file(tmp_path, "bb", name="sw")
    data = json.loads(f.read_text(encoding="utf-8"))
    data.update(mutate)
    f.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(zim.ImportValidationError) as ei:
        zim.from_switch_json(f)
    assert ei.value.code == code


def test_from_switch_json_rejects_non_object(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("[1,2]", encoding="utf-8")
    with pytest.raises(zim.ImportValidationError) as ei:
        zim.from_switch_json(f)
    assert ei.value.code == "not-object"


def test_scan_switch_dir_ignores_tmp_and_bad(tmp_path):
    _switch_file(tmp_path, "1eff0f2f-225c-4d87-8c9c-936ddf3190da", name="a")
    (tmp_path / "491b0ca7.tmp-58a4393e4c884315be28734397be03d4").write_text(
        (tmp_path / "1eff0f2f-225c-4d87-8c9c-936ddf3190da.json").read_text(), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{broken", encoding="utf-8")
    (tmp_path / "nomid.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    entries = zim.scan_switch_dir(str(tmp_path))
    assert [e.name for e in entries] == ["a"]


# ============ 模板挑选 / 统一入口 ============

def test_find_config_template_prefers_builtin_provider(tmp_path):
    (tmp_path / "no-builtin").mkdir()
    (tmp_path / "no-builtin" / "config.json").write_text(
        json.dumps({"provider": {"custom": {}}}), encoding="utf-8")
    _panel_account(tmp_path, "with-builtin", family="zai")
    tpl = zim.find_config_template(tmp_path)
    assert tpl is not None and any(k.startswith("builtin:") for k in tpl["provider"])


def test_payload_for_form_dispatches():
    gw = {"name": "g", "device_mid": MID, "credentials.json": {}, "config.json": {}}
    assert zim.payload_for_form(gw, zim.FORM_GATEWAY) == gw
    assert zim.payload_for_form(json.dumps(gw), zim.FORM_GATEWAY) == gw   # 文本形态也认
    meta = {"name": "m", "device_mid": MID}
    assert zim.payload_for_form(meta, zim.FORM_META) == meta
    with pytest.raises(zim.ImportValidationError) as ei:
        zim.payload_for_form({}, zim.FORM_UNKNOWN)
    assert ei.value.code == "unknown-form"
    p = zim.payload_for_form({"name": "s", "jwt": JWT, "device_mid": MID},
                             zim.FORM_PASTE)
    assert "credentials.json" in p
