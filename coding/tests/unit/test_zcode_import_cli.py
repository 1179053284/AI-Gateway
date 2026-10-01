"""`mgw zcode import` 三源兼容 CLI 测试（Q31，2026-10-01）。

覆盖：单文件自动识别（粘贴形态 / switch 文件）→ 转换落盘；旧形态直通不受影响；
`--device-mid` 覆盖；`--from-panel` / `--from-switch` 批量（冲突不中断 + 退出码契约）；
`--json` 机器可读输出；用法错误退出码 2。

**无网络、无真实凭据**（合成 tmp 夹具；加密往返用本机 secret）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from model_gateway.cli import main
from model_gateway.upstream.zcode import crypto

JWT = "eyJhbGciOiJIUzI1NiJ9.QUJDREVGR0g.SIGNATURE_PART"
MID = "c363eb06-2b63-4c59-9c69-1c5794ccf0cb"
MID2 = "560be077-8cfc-527d-bf3b-7f431573428f"


@pytest.fixture
def accounts_root(tmp_path, monkeypatch):
    root = tmp_path / "zcode-accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    return root


def _write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _panel_account(root: Path, name: str, *, mid: str, family: str = "zai") -> Path:
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
        "options": {"apiKey": "enc-not-checked", "baseURL": "https://zcode.z.ai/api/v1/zcode-plan/anthropic"}}}}
    _write_json(v2 / "config.json", cfg)
    _write_json(d / "config.json", cfg)
    return d


def _switch_file(root: Path, stem: str, *, name: str, mid: str) -> Path:
    return _write_json(root / f"{stem}.json", {
        "id": stem, "name": name, "hash": "0123456789abcdef",
        "virtual_device_mid": mid, "virtual_arms_uid": "uid_x",
        "credentials": {"zcodejwttoken": "enc:v1:11.22.33",
                        "oauth:active_provider": "enc:v1:44.55.66",
                        "oauth:bigmodel:access_token": "enc:v1:77.88.99"},
        "config": {"provider": {"builtin:bigmodel-start-plan": {}}},
    })


def _seed_gateway_account(root: Path, name: str, mid: str) -> None:
    _write_json(root / name / "meta.json", {"device_mid": mid, "via": "import"})


# ============ 单文件：粘贴形态 ============

def test_import_paste_file_writes_encrypted_client_files(accounts_root, tmp_path, capsys):
    f = _write_json(tmp_path / "shop.json", {"name": "shop1", "jwt": JWT, "device_mid": MID})

    assert main(["zcode", "import", str(f)]) == 0
    v2 = accounts_root / "shop1" / "data" / ".zcode" / "v2"
    cred = json.loads((v2 / "credentials.json").read_text(encoding="utf-8"))
    assert crypto.decrypt(cred["zcodejwttoken"]) == JWT
    assert crypto.decrypt(cred["oauth:active_provider"]) == "bigmodel"
    cfg = json.loads((v2 / "config.json").read_text(encoding="utf-8"))
    assert "builtin:bigmodel-start-plan" in cfg["provider"]
    tele = json.loads((v2 / "telemetry-state.json").read_text(encoding="utf-8"))
    assert tele["deviceMid"] == MID                       # 设备码通道 ②（dataroot 同步）
    meta = json.loads((accounts_root / "shop1" / "meta.json").read_text(encoding="utf-8"))
    assert meta["device_mid"] == MID and meta["family"] == "bigmodel"
    assert "✓ 已导入账号 shop1" in capsys.readouterr().out


def test_import_paste_family_credentials_form(accounts_root, tmp_path):
    f = _write_json(tmp_path / "shop2.json", {
        "name": "shop2", "jwt": JWT, "device_mid": MID2, "family": "zai",
        "credentials": {"oauth:zai:access_token": JWT, "oauth:zai:user_info": '{"a":1}'},
    })
    assert main(["zcode", "import", str(f)]) == 0
    v2 = accounts_root / "shop2" / "data" / ".zcode" / "v2"
    cred = json.loads((v2 / "credentials.json").read_text(encoding="utf-8"))
    assert crypto.decrypt(cred["oauth:active_provider"]) == "zai"
    assert crypto.decrypt(cred["oauth:zai:access_token"]) == JWT
    cfg = json.loads((v2 / "config.json").read_text(encoding="utf-8"))
    assert "builtin:zai-start-plan" in cfg["provider"]


def test_import_paste_uses_existing_account_config_as_template(accounts_root, tmp_path):
    """模板取自网关**既有账号**的 config（面板 main.js:2325-2335 同路线）。"""
    seed_cfg = {"provider": {"builtin:zai-start-plan": {
        "name": "seed", "kind": "anthropic", "enabled": True,
        "options": {"apiKey": "old", "baseURL": "https://zcode.z.ai/api/v1/zcode-plan/anthropic",
                    "keepme": "v1"}}}}
    _write_json(accounts_root / "seed" / "data" / ".zcode" / "v2" / "config.json", seed_cfg)

    f = _write_json(tmp_path / "shop3.json", {
        "name": "shop3", "jwt": JWT, "device_mid": MID, "family": "zai"})
    assert main(["zcode", "import", str(f)]) == 0
    cfg = json.loads((accounts_root / "shop3" / "data" / ".zcode" / "v2"
                      / "config.json").read_text(encoding="utf-8"))
    entry = cfg["provider"]["builtin:zai-start-plan"]
    assert entry["options"]["keepme"] == "v1"             # 模板字段保留 → 证明模板被使用
    assert entry["options"]["apiKey"] == JWT              # apiKey 被本次 jwt 覆盖


def test_import_bad_paste_rejected(accounts_root, tmp_path, capsys):
    f = _write_json(tmp_path / "bad.json", {"name": "b", "jwt": "not-a-jwt", "device_mid": MID})
    rc = main(["zcode", "import", str(f)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "jwt 不合法" in err
    assert not (accounts_root / "b").exists()


def test_import_device_mid_override(accounts_root, tmp_path):
    f = _write_json(tmp_path / "ov.json", {"name": "ov", "jwt": JWT, "device_mid": MID})
    assert main(["zcode", "import", str(f), "--device-mid", MID2]) == 0
    meta = json.loads((accounts_root / "ov" / "meta.json").read_text(encoding="utf-8"))
    assert meta["device_mid"] == MID2


# ============ 单文件：zcode-switch 文件 ============

def test_import_switch_file(accounts_root, tmp_path):
    f = _switch_file(tmp_path, "1eff0f2f-225c-4d87-8c9c-936ddf3190da", name="sw1", mid=MID)
    assert main(["zcode", "import", str(f)]) == 0
    meta = json.loads((accounts_root / "sw1" / "meta.json").read_text(encoding="utf-8"))
    assert meta["device_mid"] == MID
    v2 = accounts_root / "sw1" / "data" / ".zcode" / "v2"
    src = json.loads(f.read_text(encoding="utf-8"))
    assert json.loads((v2 / "credentials.json").read_text(encoding="utf-8")) \
        == src["credentials"]                              # 原样透传（不重加密）
    assert json.loads((v2 / "config.json").read_text(encoding="utf-8")) == src["config"]


# ============ 单文件：旧形态直通（既有契约）============

def test_import_legacy_meta_file_unchanged(accounts_root, tmp_path):
    f = _write_json(tmp_path / "legacy.json", {"name": "legacy", "device_mid": "MID-OLD"})
    assert main(["zcode", "import", str(f)]) == 0
    meta = json.loads((accounts_root / "legacy" / "meta.json").read_text(encoding="utf-8"))
    assert meta["device_mid"] == "MID-OLD"                 # 旧形态不强制 UUID，原样复用


def test_import_wrapped_meta_file_unchanged(accounts_root, tmp_path):
    f = _write_json(tmp_path / "w.json", {"account": {"name": "wrapped", "device_mid": "MID-X"}})
    assert main(["zcode", "import", str(f)]) == 0
    assert (accounts_root / "wrapped" / "meta.json").exists()


def test_import_json_output(accounts_root, tmp_path, capsys):
    f = _write_json(tmp_path / "j.json", {"name": "j1", "jwt": JWT, "device_mid": MID})
    assert main(["zcode", "import", str(f), "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["ok"] is True and body["account"] == "j1" and body["form"] == "paste"


# ============ 批量：--from-panel ============

def test_from_panel_bulk_ok(accounts_root, tmp_path, capsys):
    panel = tmp_path / "panel"
    _panel_account(panel, "p1", mid=MID)
    _panel_account(panel, "p2", mid=MID2, family="bigmodel")

    assert main(["zcode", "import", "--from-panel", str(panel)]) == 0
    out = capsys.readouterr().out
    assert "✓ p1：已导入" in out and "✓ p2：已导入" in out
    assert "合计：成功 2 / 冲突 0 / 失败 0" in out
    for name, mid in (("p1", MID), ("p2", MID2)):
        meta = json.loads((accounts_root / name / "meta.json").read_text(encoding="utf-8"))
        assert meta["device_mid"] == mid


def test_from_panel_bulk_conflict_does_not_abort(accounts_root, tmp_path, capsys):
    """冲突**不中断**批量；有成功且无硬失败 → 0（冲突逐条明示）。"""
    _seed_gateway_account(accounts_root, "owner", MID2)     # 预占 MID2
    panel = tmp_path / "panel"
    _panel_account(panel, "p1", mid=MID)
    _panel_account(panel, "p2", mid=MID2)                   # 与 owner 冲突

    assert main(["zcode", "import", "--from-panel", str(panel)]) == 0
    out = capsys.readouterr().out
    assert "✓ p1：已导入" in out
    assert "冲突 p2：设备 ID 冲突（被『owner』占用），未导入" in out
    assert "合计：成功 1 / 冲突 1 / 失败 0" in out
    assert (accounts_root / "p1").exists()
    assert not (accounts_root / "p2" / "meta.json").exists()


def test_from_panel_bulk_failure_beats_conflict(accounts_root, tmp_path, capsys):
    """硬失败优先于冲突：退出码 1；坏目录照常逐条报原因。"""
    _seed_gateway_account(accounts_root, "owner", MID2)
    panel = tmp_path / "panel"
    _panel_account(panel, "p1", mid=MID)
    _panel_account(panel, "p2", mid=MID2)
    _panel_account(panel, "broken", mid="")                 # meta 缺 device_mid → 转换失败

    assert main(["zcode", "import", "--from-panel", str(panel)]) == 1
    out = capsys.readouterr().out
    assert "✗ broken：" in out
    assert "合计：成功 1 / 冲突 1 / 失败 1" in out


def test_from_panel_bulk_all_conflict_exits_4(accounts_root, tmp_path, capsys):
    _seed_gateway_account(accounts_root, "owner", MID)
    panel = tmp_path / "panel"
    _panel_account(panel, "p1", mid=MID)

    assert main(["zcode", "import", "--from-panel", str(panel)]) == 4
    out = capsys.readouterr().out
    assert "冲突 p1：" in out and "合计：成功 0 / 冲突 1 / 失败 0" in out


def test_from_panel_bulk_reuse_resolves_conflict(accounts_root, tmp_path):
    _seed_gateway_account(accounts_root, "owner", MID)
    _seed_gateway_account(accounts_root, "other", MID2)
    panel = tmp_path / "panel"
    _panel_account(panel, "p1", mid=MID2)                   # 与 other 冲突

    assert main(["zcode", "import", "--from-panel", str(panel), "--reuse", "owner"]) == 0
    meta = json.loads((accounts_root / "p1" / "meta.json").read_text(encoding="utf-8"))
    assert meta["device_mid"] == MID                        # 落到 owner 的设备码


def test_from_panel_dir_missing_exits_2(accounts_root, tmp_path, capsys):
    assert main(["zcode", "import", "--from-panel", str(tmp_path / "nope")]) == 2
    assert "目录不存在" in capsys.readouterr().err


def test_from_panel_no_accounts_exits_2(accounts_root, tmp_path, capsys):
    panel = tmp_path / "panel"
    panel.mkdir()
    assert main(["zcode", "import", "--from-panel", str(panel)]) == 2
    assert "没有可导入的账号" in capsys.readouterr().err


def test_from_panel_json_output(accounts_root, tmp_path, capsys):
    panel = tmp_path / "panel"
    _panel_account(panel, "p1", mid=MID)
    assert main(["zcode", "import", "--from-panel", str(panel), "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["source"] == "panel" and body["summary"] == {
        "total": 1, "ok": 1, "conflict": 0, "failed": 0}
    assert body["results"][0]["name"] == "p1"


# ============ 批量：--from-switch ============

def test_from_switch_bulk(accounts_root, tmp_path, capsys):
    switch = tmp_path / "switch"
    _switch_file(switch, "1eff0f2f-225c-4d87-8c9c-936ddf3190da", name="sw1", mid=MID)
    _switch_file(switch, "2bee2799-baa4-4d5f-b7e2-50e949603fc8", name="sw2", mid=MID2)
    # 写盘中间态必须被忽略
    (switch / "491b0ca7.tmp-58a4393e4c884315be28734397be03d4").write_text("{}", encoding="utf-8")

    assert main(["zcode", "import", "--from-switch", str(switch)]) == 0
    out = capsys.readouterr().out
    assert "发现 2 个账号" in out
    assert (accounts_root / "sw1" / "meta.json").exists()
    assert (accounts_root / "sw2" / "meta.json").exists()


def test_from_switch_bulk_reports_broken_file(accounts_root, tmp_path, capsys):
    switch = tmp_path / "switch"
    _switch_file(switch, "aa", name="ok1", mid=MID)
    (switch / "bb.json").write_text(json.dumps(
        {"name": "bad", "virtual_device_mid": MID2, "credentials": {}, "config": {}}),
        encoding="utf-8")

    assert main(["zcode", "import", "--from-switch", str(switch)]) == 1
    out = capsys.readouterr().out
    assert "✓ ok1：已导入" in out
    assert "✗ bad：" in out and "credentials" in out


# ============ 用法错误（退出码 2）============

def test_usage_errors(accounts_root, tmp_path, capsys):
    f = _write_json(tmp_path / "u.json", {"name": "u", "device_mid": "m"})
    assert main(["zcode", "import"]) == 2                                  # 无路径无来源
    assert main(["zcode", "import", str(f), "--from-panel", str(tmp_path)]) == 2
    assert main(["zcode", "import", "--from-panel", "--from-switch"]) == 2
    assert main(["zcode", "import", "--from-panel", str(tmp_path),
                 "--device-mid", MID]) == 2
    err = capsys.readouterr().err
    assert "不能同用" in err or "不接受位置参数" in err or "仅适用于单文件" in err
