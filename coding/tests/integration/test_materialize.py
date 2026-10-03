"""账号 → 资源物化（tech-design §22.5-1；M6-5a）——幂等 / 拒建 / 停用 / 落盘路径 / 登录接线。

判据逐条对应 §22.5-1 与 §22.5-2：

· 物化字段 = id 自动生成 + product + account_ref + vendor（产品显示名）+ account（账号名）
  + protocol/base_url（注册表值）+ enabled=true，`api_key` 为空（凭据在账号目录）；
· **幂等**：重复调用不重复建，命中即返回其 id（内容零变更；额外前推一次配置 mtime
  作重载信号 —— B-2 残差修复，见 `test_ensure_resource_on_existing_row_nudges_config_mtime`）；
· **不编造**：注册表 base_url 为空 → 拒建 + 可执行错误；配置读不动 → 拒建（不覆盖）；
· **删除 = 停用**（`enabled=false` 保留历史）；
· 接线：登录/导入成功自动物化，账号删除自动停用；两条接线**都不得**动摇既有语义
  （凭据已保存的事实不因物化失败而改变）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

import pytest
import yaml

from model_gateway.accounts import materialize, registry, store
from model_gateway.accounts.materialize import (
    MaterializeError,
    credential_fingerprint,
    disable_resource,
    ensure_resource,
)
from model_gateway.config.loader import load_config
from model_gateway.core import paths

LEGACY = {"id": "res-legacy", "name": "旧资源", "account": "a", "protocol": "openai",
          "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-1"}


def _write(path, *, resources=None, models=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"resources": resources or [], "models": models or []},
                                   allow_unicode=True), encoding="utf-8")


def _rows(path) -> list:
    return load_config(path).resources


def _row(path, rid: str):
    return next(r for r in _rows(path) if r.id == rid)


# ============ 物化 ============

def test_ensure_resource_writes_registry_values_and_is_idempotent(tmp_path):
    cfg = tmp_path / "conf" / "config.yaml"
    _write(cfg, resources=[LEGACY])
    rid = ensure_resource("buddy", "acc-1", config_path=cfg)

    r = _row(cfg, rid)
    assert (r.product, r.account_ref, r.account) == ("buddy", "acc-1", "acc-1")
    assert r.vendor == "CodeBuddy"                      # 产品显示名（§22.5-1）
    assert (r.protocol, r.base_url) == ("openai", registry.get("buddy").base_url)
    assert r.api_key == "" and r.enabled is True
    assert any(x.id == "res-legacy" for x in _rows(cfg)), "既有资源被改坏了"

    after_first = cfg.read_bytes()
    assert ensure_resource("buddy", "acc-1", config_path=cfg) == rid
    assert cfg.read_bytes() == after_first, "幂等被破：重复调用改动了内容"


def test_ensure_resource_on_existing_row_nudges_config_mtime(tmp_path):
    """🔴 B-2 残差（M6-6 Fix-η）：命中既有资源（内容零变更）时必须前推配置 mtime。

    这是"重登/续期后运行态必须被重算"交给**既有** 1s 热重载协议的信号 ——
    没有它，401 判死的资源永不复活（用户按提示重新登录仍 503）。
    红证（撤 `_nudge_reload`）：`st_mtime` 停在被钉死的过去值，本用例即红。
    """
    cfg = tmp_path / "conf" / "config.yaml"
    rid = ensure_resource("buddy", "acc-1", config_path=cfg)
    past = time.time() - 60.0
    os.utime(cfg, (past, past))                  # 钉死为过去值，消除同秒假绿

    before = cfg.read_bytes()
    assert ensure_resource("buddy", "acc-1", config_path=cfg) == rid
    assert cfg.read_bytes() == before, "命中路径改了内容（幂等被破）"
    assert cfg.stat().st_mtime > past + 1, \
        "命中路径没有前推配置 mtime —— 网关收不到重载信号（B-2 残差）"


def test_commit_login_relogin_nudges_config_through_the_only_write_path(tmp_path):
    """🔴 接线判据（M6-6 Fix-η）：登录 / 续期 / 导入共用的**唯一落盘入口**
    `store.commit_login` 在资源已存在时也要发出重载信号 —— 用户"重新登录"这一动作
    自身触发运行态重算，不需要任何额外操作（也不必记得去改配置）。

    红证（撤 `_nudge_reload`）：mtime 同上停在被钉死的过去值，本用例即红。
    """
    cfg = paths.resolve_config_path(None)        # conftest 已把 MG_CONFIG 钉到 tmp
    store.commit_login("buddy", "acc-relogin", {"access_token": "T1"}, {})
    past = time.time() - 60.0
    os.utime(cfg, (past, past))
    before = cfg.read_bytes()

    store.commit_login("buddy", "acc-relogin", {"access_token": "T2"}, {})   # 重登/续期
    assert cfg.read_bytes() == before, "重登改动了配置内容（物化应命中幂等，只发信号）"
    assert cfg.stat().st_mtime > past + 1, \
        "重登/续期没有发出重载信号 —— 401 判死的资源不会复活（B-2 残差）"


def test_ensure_resource_keeps_an_existing_disabled_switch(tmp_path):
    """命中既有资源（哪怕已停用）→ 只返回 id，**不拨回开关**（用户的决定优先）。"""
    cfg = tmp_path / "conf" / "config.yaml"
    rid = ensure_resource("buddy", "acc-1", config_path=cfg)
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["resources"][0]["enabled"] = False
    _write(cfg, resources=data["resources"])

    assert ensure_resource("buddy", "acc-1", config_path=cfg) == rid
    assert _row(cfg, rid).enabled is False


def test_ensure_resource_on_a_disabled_account_lands_disabled(tmp_path):
    """🔴 **新建**资源的启用位 = 账号自己的启用位（Q33 评审 R1-④ 判死后的判据）。

    旧实现一律写 `enabled=True`，而这条路径是真实存在的（导入/重登一个停用号、
    `_set_enabled` 的启用前置物化、`commit_login` 尾部的 best-effort 物化）——
    一律 True 就等于凭空造出"账号停用、资源启用、条目齐全"的**可调用号**，
    号开关被绕过（违反 Q33-①②「一个开关一个主人」）。
    红证（把 `enabled=_account_enabled(...)` 撤成 `enabled=True`）：本用例第一条断言即红。
    """
    cfg = tmp_path / "conf" / "config.yaml"
    _write(cfg, resources=[LEGACY])

    store.commit_login("buddy", "acc-off", {"access_token": "T-off"}, {"enabled": False})
    assert store.load_meta(store.product_root("buddy"), "acc-off")["enabled"] is False
    rid_off = ensure_resource("buddy", "acc-off", config_path=cfg)
    assert _row(cfg, rid_off).enabled is False

    # 对照腿：账号没有显式停用（缺省 = 启用）⇒ 新建资源照旧启用，不把停用语义扩大化
    store.commit_login("buddy", "acc-on", {"access_token": "T-on"}, {})
    rid_on = ensure_resource("buddy", "acc-on", config_path=cfg)
    assert _row(cfg, rid_on).enabled is True


def test_ensure_resource_refuses_when_registry_has_no_base_url(tmp_path, monkeypatch):
    """🔴 基址取不到 → **拒建** + 可执行错误（不编造域名），且配置文件原样不动。"""
    meta = registry.get("buddy")
    monkeypatch.setitem(registry.PRODUCTS, "buddy",
                        type(meta)(**{**meta.__dict__, "base_url": ""}))
    cfg = tmp_path / "conf" / "config.yaml"
    _write(cfg, resources=[LEGACY])
    before = cfg.read_bytes()

    with pytest.raises(MaterializeError) as e:
        ensure_resource("buddy", "acc-1", config_path=cfg)
    message = str(e.value)
    assert "base_url" in message and "取证" in message and "重试" in message
    assert cfg.read_bytes() == before


def test_ensure_resource_refuses_unregistered_product(tmp_path):
    cfg = tmp_path / "conf" / "config.yaml"
    with pytest.raises(MaterializeError, match="未登记的产品"):
        ensure_resource("codearts", "acc", config_path=cfg)


@pytest.mark.parametrize("bad", ["", "  ", "../x", "a/b", "x" * 33])
def test_ensure_resource_rejects_bad_account_names(tmp_path, bad):
    cfg = tmp_path / "conf" / "config.yaml"
    with pytest.raises(MaterializeError, match="账号名不合法"):
        ensure_resource("buddy", bad, config_path=cfg)


def test_ensure_resource_refuses_to_overwrite_a_corrupt_config(tmp_path):
    """配置读不动 → 拒建：拿一份"缺了很多资源"的快照覆盖用户配置 = 数据丢失。

    🔴 消息必须是**真实成因**（复验轮 R4 阻塞项 B 的处置）：哪份文件、校验说了什么、
    下一步怎么办。⚠️ 同轮复验裁定：R4 说 `ValidationError` 会以 `ValueError` 穿出
    `load_config` —— 九种坏形状逐一复跑**全部只出 `ConfigError`**（`config/loader.py:49-54`
    统一包装），所以实现里**不留** `except ValueError` 死分支；这里第二腿用
    `resources: [{a: 1, b: 2}]`（缺必填字段）而不是 `{"a":1,"b":2}`（后者是"合法的空配置"，
    根本不抛 —— 记进 pitfalls：**拒绝式判据的前提必须实测存在**）。
    """
    cfg = tmp_path / "conf" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("resources:\n  - id: res-x\n    product: buddy\n    api_key: ''\n",
                   encoding="utf-8")
    before = cfg.read_bytes()
    with pytest.raises(MaterializeError, match="配置读不动") as e:
        ensure_resource("buddy", "acc-1", config_path=cfg)
    message = str(e.value)
    assert "不覆盖坏配置" in message and "下一步" in message
    assert str(cfg) in message                        # 指到**哪份文件**，不是泛泛"校验失败"
    assert "未登记" not in message                    # 成因是"读不动"，不借产品名义
    assert cfg.read_bytes() == before

    cfg.write_text("resources:\n  - {a: 1, b: 2}\n", encoding="utf-8")
    with pytest.raises(MaterializeError, match="配置读不动"):
        ensure_resource("buddy", "acc-1", config_path=cfg)


def test_ensure_resource_does_not_touch_model_mappings(tmp_path):
    """物化只加资源，**不自动建映射**（§22.5-4：映射仍是用户动作）。"""
    cfg = tmp_path / "conf" / "config.yaml"
    models = [{"name": "m", "endpoint": "chat",
               "resources": [{"resource": "res-legacy", "model": "vm"}]}]
    _write(cfg, resources=[LEGACY], models=models)
    ensure_resource("buddy", "acc-1", config_path=cfg)
    saved = load_config(cfg).model_dump()["models"]
    assert [m["name"] for m in saved] == ["m"]
    # 只比较映射**实体**（resource/model）；`reasoning: None` 是序列化形态，不是语义差异
    assert [(r["resource"], r["model"]) for r in saved[0]["resources"]] \
        == [("res-legacy", "vm")], "物化动了既有映射"


def test_ensure_resource_uses_atomic_write(tmp_path):
    cfg = tmp_path / "conf" / "config.yaml"
    _write(cfg)
    ensure_resource("buddy", "acc-1", config_path=cfg)
    leftovers = [p.name for p in cfg.parent.iterdir() if p.name != cfg.name]
    assert leftovers == [], f"原子写留下临时文件：{leftovers}"


def test_ensure_resource_with_manual_path_is_independent_of_mg_config(tmp_path):
    """显式 `config_path` 优先（CLI / 测试隔离口径，`paths.resolve_config_path` 同源）。"""
    cfg = tmp_path / "other.yaml"
    ensure_resource("buddy", "acc-1", config_path=cfg)
    assert cfg.exists()
    assert not paths.default_config_path().exists() or \
        not any(r.product == "buddy" for r in _rows(paths.default_config_path()))


# ============ 停用（删除账号的后果）============

def test_disable_resource_keeps_history_and_is_idempotent(tmp_path):
    cfg = tmp_path / "conf" / "config.yaml"
    rid = ensure_resource("buddy", "acc-1", config_path=cfg)

    assert disable_resource("buddy", "acc-1", config_path=cfg) is True
    assert _row(cfg, rid).enabled is False, "停用必须保留行（统计与历史不丢）"
    after = cfg.read_bytes()
    assert disable_resource("buddy", "acc-1", config_path=cfg) is False
    assert cfg.read_bytes() == after, "已停用还写盘 = 幂等被破"


def test_disable_resource_only_touches_the_matching_account(tmp_path):
    cfg = tmp_path / "conf" / "config.yaml"
    rid_a = ensure_resource("buddy", "acc-a", config_path=cfg)
    rid_b = ensure_resource("workbuddy", "acc-b", config_path=cfg)
    assert disable_resource("buddy", "acc-a", config_path=cfg) is True
    assert _row(cfg, rid_a).enabled is False
    assert _row(cfg, rid_b).enabled is True, "别的产品/账号被误停用"


def test_disable_resource_on_missing_account_is_a_noop(tmp_path):
    cfg = tmp_path / "conf" / "config.yaml"
    _write(cfg, resources=[LEGACY])
    before = cfg.read_bytes()
    assert disable_resource("buddy", "nobody", config_path=cfg) is False
    assert cfg.read_bytes() == before


# ============ 凭据指纹（复用判据素材）============

def test_credential_fingerprint_tracks_relogin(tmp_path):
    """指纹随凭据内容变化（且**不含明文**）—— S-14 同族判据的素材。"""
    store.commit_login("buddy", "acc-fp", {"access_token": "T1"}, {})
    first = credential_fingerprint("buddy", "acc-fp")
    assert first and "T1" not in first and len(first) == 6
    store.commit_login("buddy", "acc-fp", {"access_token": "T2"}, {})
    assert credential_fingerprint("buddy", "acc-fp") != first
    assert credential_fingerprint("buddy", "no-such-account") == ""


# ============ 登录/删除接线（store 唯一入口）============

def test_login_materializes_and_delete_disables(tmp_path, caplog):
    """🔴 端到端接线：`commit_login` → 资源出现；`delete_account` → 资源停用（保留）。"""
    cfg = paths.resolve_config_path(None)          # conftest 已把 MG_CONFIG 钉到 tmp
    store.commit_login("buddy", "acc-wire", {"access_token": "T"}, {"uid": "u1"})

    rows = [r for r in _rows(cfg) if (r.product, r.account_ref) == ("buddy", "acc-wire")]
    assert len(rows) == 1, "登录成功却没物化资源（§22.5-1）"
    assert rows[0].enabled is True

    assert store.delete_account("buddy", "acc-wire") is True
    assert _row(cfg, rows[0].id).enabled is False, "删账号后资源仍启用（会打到无凭据的账号上）"


def test_materialize_failure_does_not_break_the_login(tmp_path, monkeypatch, caplog):
    """物化失败（配置面问题）**不得**升级成登录失败：凭据已保存这一事实不改变。"""
    def _boom(product, name, *, config_path=None):
        raise MaterializeError("基址未取证，拒绝物化")

    monkeypatch.setattr(materialize, "ensure_resource", _boom)
    with caplog.at_level(logging.WARNING, logger="model_gateway.accounts"):
        store.commit_login("buddy", "acc-fail", {"access_token": "T"}, {})

    assert store.load_credentials("buddy", "acc-fail")["access_token"] == "T"
    assert any("资源物化未完成" in r.message for r in caplog.records), \
        "物化失败必须留痕（否则用户以为已生效）"


def test_import_account_materializes_too(tmp_path):
    """导入路径同样物化（§22.5-1「登录/导入成功」）。"""
    cfg = paths.resolve_config_path(None)
    src = tmp_path / "cred.json"
    src.write_text(json.dumps({"credentials": {"access_token": "T-import"}}),
                   encoding="utf-8")
    result = store.import_account("workbuddy", str(src), name="acc-imp")
    assert result.ok, result.message
    rows = [r for r in _rows(cfg) if (r.product, r.account_ref) == ("workbuddy", "acc-imp")]
    assert len(rows) == 1 and rows[0].vendor == "WorkBuddy（国际版）"


def test_custom_protocol_products_land_openai_literal(tmp_path):
    """§22.5-3 裁决：`custom` 产品物化时 `protocol` 落 `openai` 字面量（分派以 product 为准）。"""
    cfg = tmp_path / "conf" / "config.yaml"
    rid = ensure_resource("qoder", "acc-q", config_path=cfg)
    r = _row(cfg, rid)
    assert (r.protocol, r.vendor) == ("openai", "Qoder")
    assert re.match(r"^res-[0-9a-f]{8}$", rid), f"资源 id 形态与既有生成器不一致：{rid}"
