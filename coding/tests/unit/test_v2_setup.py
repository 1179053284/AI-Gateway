"""v2.0 §12.4 文件下发单元测试（tech-design §19 M3-5 / PRD Q25-⑨）。

🔴 重点验收 **目录解析规则**（PRD Q25-⑨ **明文禁止** `productName` 子串判断，
   必须按「产品标识 → `dataFolderName`」解析）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from model_gateway.setup_tools import (
    PRODUCTS,
    build_models_json,
    merge_models,
    resolve_target_dir,
    write_models_json,
)


# ---------- 目录解析（Q25-⑨）----------

def test_two_products_have_distinct_data_folder_names():
    """WorkBuddy=`.workbuddy` / WorkBuddy AI=`.workbuddy-ai` —— 两者**必须不同**。"""
    assert PRODUCTS["workbuddy"].data_folder_name == ".workbuddy"
    assert PRODUCTS["workbuddy-ai"].data_folder_name == ".workbuddy-ai"
    assert (PRODUCTS["workbuddy"].data_folder_name
            != PRODUCTS["workbuddy-ai"].data_folder_name)


def test_resolve_by_data_folder_name(tmp_path: Path):
    """🔴 按「产品标识 → `dataFolderName`」解析 —— **不得**用 productName 子串判断。

    原稿曾写成 `productName 含 "workbuddy"`，那对**两个产品都返回 true**，
    永远推不出 `.workbuddy-ai`。
    """
    d1, src1 = resolve_target_dir("workbuddy", home=tmp_path, env={})
    d2, src2 = resolve_target_dir("workbuddy-ai", home=tmp_path, env={})

    assert d1 == tmp_path / ".workbuddy"
    assert d2 == tmp_path / ".workbuddy-ai"          # ← 子串判断**推不出**这个结果
    assert "dataFolderName" in src1 and "dataFolderName" in src2


def test_env_var_takes_priority(tmp_path: Path):
    """环境变量优先级**最高**（Q25-⑨ 明文要求）。"""
    env = {"WORKBUDDY_CONFIG_DIR": str(tmp_path / "hijacked")}
    d, src = resolve_target_dir("workbuddy", home=tmp_path, env=env)

    assert d == tmp_path / "hijacked"
    assert "环境变量" in src


def test_env_var_can_point_to_other_product_dir(tmp_path: Path):
    """🔴 实测踩坑：`WORKBUDDY_CONFIG_DIR` 由**另一个产品**注入，
    导致从 WorkBuddy.app 取的 CLI 跑到了 WorkBuddy AI 的目录 —— 环境变量必须最高优先。
    """
    env = {"WORKBUDDY_CONFIG_DIR": str(tmp_path / ".workbuddy-ai")}
    d, _ = resolve_target_dir("workbuddy", home=tmp_path, env=env)
    assert d == tmp_path / ".workbuddy-ai"


def test_unknown_product_raises():
    with pytest.raises(ValueError, match="未知产品"):
        resolve_target_dir("nope", env={})


# ---------- 格式与合并 ----------

def test_models_json_format_is_object_not_bare_array():
    """🔴 格式必须是 `{"models": [...], "availableModels": [...]}` ——
    **裸数组会被 CLI 解析器直接丢弃**（GUI 才用裸数组）。"""
    payload = build_models_json([{"id": "a"}, {"id": "b"}])

    assert isinstance(payload, dict)
    assert payload["availableModels"] == ["a", "b"]
    assert len(payload["models"]) == 2


def test_merge_preserves_existing_entries():
    """合并**不删除**任何已有条目（防"静默清空"事故）。"""
    existing = {"models": [{"id": "old", "keep": True}], "availableModels": ["old"]}
    merged, added = merge_models(existing, [{"id": "new"}])

    ids = [m["id"] for m in merged]
    assert ids == ["old", "new"]     # 顺序保留 + 追加
    assert added == 1


def test_merge_overwrites_same_id():
    """同名 id → 覆盖（更新能力位），不重复追加。"""
    existing = {"models": [{"id": "m", "v": 1}]}
    merged, added = merge_models(existing, [{"id": "m", "v": 2}])

    assert len(merged) == 1
    assert merged[0]["v"] == 2
    assert added == 0


def test_merge_accepts_bare_array_from_gui():
    """兼容 GUI 的裸数组形态（不丢已有条目）。"""
    merged, _ = merge_models([{"id": "gui-model"}], [{"id": "gw"}])
    assert [m["id"] for m in merged] == ["gui-model", "gw"]


# ---------- 写入纪律（§12.4.1）----------

def test_dry_run_writes_nothing(tmp_path: Path):
    res = write_models_json("workbuddy", [{"id": "a"}], home=tmp_path, env={}, dry_run=True)

    assert res.ok
    assert not (tmp_path / ".workbuddy" / "models.json").exists()
    assert "dry-run" in res.message


def test_write_creates_file_and_reports_target(tmp_path: Path):
    res = write_models_json("workbuddy", [{"id": "a"}], home=tmp_path, env={})

    assert res.ok
    target = tmp_path / ".workbuddy" / "models.json"
    assert target.exists()
    assert str(target) in res.message
    assert json.loads(target.read_text(encoding="utf-8"))["availableModels"] == ["a"]


def test_write_backs_up_existing_file(tmp_path: Path):
    """写入前**必须备份**（该文件存在外部并发写，历史上被清空过）。"""
    d = tmp_path / ".workbuddy"
    d.mkdir(parents=True)
    (d / "models.json").write_text(json.dumps({"models": [{"id": "pre"}]}), encoding="utf-8")

    res = write_models_json("workbuddy", [{"id": "post"}], home=tmp_path, env={})

    assert res.ok and res.backup is not None and res.backup.exists()
    backup = json.loads(res.backup.read_text(encoding="utf-8"))
    assert backup["models"][0]["id"] == "pre"       # 备份是**改前**内容
    # 合并语义：原有条目保留
    after = json.loads((d / "models.json").read_text(encoding="utf-8"))
    assert [m["id"] for m in after["models"]] == ["pre", "post"]


def test_write_leaves_no_tmp_residue(tmp_path: Path):
    """原子写（tempfile + os.replace）—— 不留临时文件。"""
    write_models_json("workbuddy", [{"id": "a"}], home=tmp_path, env={})
    leftovers = [p.name for p in (tmp_path / ".workbuddy").iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_write_reports_added_and_total(tmp_path: Path):
    res = write_models_json("workbuddy", [{"id": "a"}, {"id": "b"}], home=tmp_path, env={})
    assert res.added == 2 and res.total == 2
