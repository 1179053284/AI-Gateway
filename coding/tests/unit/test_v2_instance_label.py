"""实例身份自证（`Runtime.instance_label()`）—— 2026-10-02 用户实拍立项。

验收门跑在 :8400-:8499 的独立实例上，界面与 :8300 **逐像素一致**，账号/额度全是注入样本；
用户把它当成真实数据来质问。端口是界面上唯一可区分真假的线索，不够 ⇒ 每页顶部一条横幅。
本测试钉三态：默认数据根（不显示）/ 非默认（显示路径）/ 假上游在环（说"注入样本"）。
"""

from __future__ import annotations

import os
from pathlib import Path

from model_gateway.core import paths
from model_gateway.main import Runtime


def _runtime(tmp_path: Path, config_path: Path | None = None) -> Runtime:
    rt = Runtime.__new__(Runtime)          # 只验 label 判据，不拉起整个运行态
    # 显式给路径：`default_config_path()` 会被 conftest 钉的 MG_CONFIG 带偏（那正是本判据
    # 要区分的"非默认数据根"），这里要的是"读起来就像默认实例"这一形态本身。
    rt.config_path = config_path or (paths.PROJECT_ROOT / "data" / "config.yaml")
    rt.config = type("C", (), {"gateway": type("G", (), {"port": 8300})()})()
    return rt


def test_default_data_root_produces_no_banner(tmp_path, monkeypatch):
    monkeypatch.delenv("MGW_FAKE_TRACE", raising=False)
    monkeypatch.delenv("MGW_IX_REPO", raising=False)
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    rt = _runtime(tmp_path)
    lab = rt.instance_label()
    assert lab["kind"] == "default" and lab["note"] == ""


def test_external_data_root_names_both_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("MGW_FAKE_TRACE", raising=False)
    monkeypatch.delenv("MGW_IX_REPO", raising=False)
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    other = tmp_path / "elsewhere" / "config.yaml"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("gateway: {}\n", encoding="utf-8")
    rt = _runtime(tmp_path)
    rt.config_path = other
    lab = rt.instance_label()
    assert lab["kind"] == "external"
    assert str(other.parent) in lab["note"] and str(paths.default_data_dir()) in lab["note"]
    assert "注入样本" not in lab["note"]          # 没有假上游证据时不得断言"这是门"


def test_fake_upstream_env_is_named_as_injected_samples(tmp_path, monkeypatch):
    monkeypatch.delenv("MGW_FAKE_TRACE", raising=False)
    monkeypatch.setenv("MGW_IX_REPO", str(tmp_path))
    rt = _runtime(tmp_path)
    rt.config_path = tmp_path / "gate" / "config.yaml"
    lab = rt.instance_label()
    assert lab["kind"] == "fake-upstream"
    assert "注入样本" in lab["note"] and "验收门实例" in lab["note"]
