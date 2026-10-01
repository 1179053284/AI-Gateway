"""`accounts/device.py` 单测（tech-design v2.0 §15.1 三约束的**泛化**）。

🔴 判据逐条对应契约：
  · 生成路径：冲突 → 重新生成（有上限，耗尽**显式失败**，不静默降级）
  · 导入路径：冲突 → **拒绝 + 交用户决策**；`--reuse` 复用 / `--regenerate` 重生成
  · 导入复用原 ID（缓存里的值原样用，绝不重算）
  · 跨账号唯一（身份 = `DeviceSpec.fields` 各字段值；**任一字段相同即冲突**，保守口径）
  · 多字段生成 = `generate_identity_values` 逐字段生成（单值 `generate_unique` 对多字段显式报错）
  · `DeviceSpec.derive=True` + seed → 确定性派生（同 seed 同值；不是随机）
"""

from __future__ import annotations

import json

import pytest

from model_gateway.accounts import device
from model_gateway.accounts.store import plan_import_device
from model_gateway.accounts.types import DeviceSpec

ONE_FIELD = DeviceSpec(fields=("machine_id",), derive=False)
TWO_FIELD = DeviceSpec(fields=("machine_id", "device_id"), derive=True)
DERIVE = DeviceSpec(fields=("device_id",), derive=True)


def _account(root, name: str, **meta) -> None:
    """造一个账号目录（判据 = 目录里有 meta.json，与生产同口径）。"""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


# ============ 生成路径（硬约束 1）============

def test_generate_regenerates_on_collision(tmp_path):
    """冲突 → 重新生成（前两次冲突、第三次成功 → 返回第三个候选）。"""
    seen: list[str] = []

    def is_unique(candidate: str) -> bool:
        seen.append(candidate)
        return len(seen) >= 3

    got = device.generate_unique(tmp_path, ONE_FIELD, is_unique=is_unique)
    assert len(seen) == 3 and got == seen[-1]


def test_generate_raises_when_exhausted(tmp_path):
    """耗尽 → **显式失败**（有上限，不静默降级）。"""
    with pytest.raises(RuntimeError, match="无法生成唯一设备 ID"):
        device.generate_unique(tmp_path, ONE_FIELD, tries=3, is_unique=lambda c: False)


def test_generate_without_device_identity_is_refused(tmp_path):
    """无设备身份的产品不得调生成（空 spec = 编程错误，显式报错）。"""
    with pytest.raises(ValueError, match="无设备身份"):
        device.generate_unique(tmp_path, DeviceSpec(fields=(), derive=False))


def test_generate_derive_is_deterministic_and_not_random(tmp_path):
    """`derive=True` + seed → 确定性派生：同 seed 同值、异 seed 异值、且**不重随机**。"""
    a1 = device.generate_unique(tmp_path, DERIVE, seed="uid-1")
    a2 = device.generate_unique(tmp_path, DERIVE, seed="uid-1")
    b = device.generate_unique(tmp_path, DERIVE, seed="uid-2")
    assert a1 == a2 and a1 != b
    assert device.derive_id(DERIVE, "uid-1") == a1


def test_derive_conflict_fails_loudly(tmp_path):
    """派生值与既有账号冲突 → 显式失败（不偷偷换算法/重随机）。"""
    _account(tmp_path, "owner", device_id=device.derive_id(DERIVE, "uid-1"))
    with pytest.raises(RuntimeError, match="确定性派生"):
        device.generate_unique(tmp_path, DERIVE, seed="uid-1")


# ============ 唯一性 / 反查（§15.1 硬约束 1）============

def test_check_unique_and_find_owner(tmp_path):
    _account(tmp_path, "owner", machine_id="mid-1")
    assert device.check_unique(tmp_path, ONE_FIELD, ("mid-1",)) is False
    assert device.find_account_by_values(tmp_path, ONE_FIELD, ("mid-1",)) == "owner"
    assert device.check_unique(tmp_path, ONE_FIELD, ("mid-2",)) is True
    assert device.find_account_by_values(tmp_path, ONE_FIELD, ("mid-2",)) is None


def test_missing_root_or_empty_values_are_unique(tmp_path):
    """根不存在 / 空值 → 判唯一（空身份不是"占用"）。"""
    assert device.check_unique(tmp_path / "nope", ONE_FIELD, ("x",)) is True
    assert device.find_account_by_values(tmp_path, ONE_FIELD, ()) is None


def test_account_without_complete_identity_is_not_an_owner(tmp_path):
    """字段缺失 / 非字符串 / 空串 → 该账号**不参与**唯一性判定（不是"占用者"）。"""
    _account(tmp_path, "half", other="1")
    _account(tmp_path, "blank", machine_id="   ")
    _account(tmp_path, "typed", machine_id=123)
    assert device.check_unique(tmp_path, ONE_FIELD, ("mid-x",)) is True
    assert device.find_account_by_values(tmp_path, ONE_FIELD, ("mid-x",)) is None


def test_stray_directory_is_not_an_account(tmp_path):
    """没有 meta.json 的目录不算账号（zcode 历史教训：别的模块落盘会被误当账号）。"""
    (tmp_path / "stray").mkdir()
    assert device.check_unique(tmp_path, ONE_FIELD, ("mid-x",)) is True


def test_multi_field_identity_conflicts_on_any_shared_field(tmp_path):
    """多字段身份（trae 的 machine_id + device_id）**任一字段相同即冲突**（保守口径）。

    §22.3 裁决（2026-09-29 W2-fix）：多字段产品共用一个身份字段就可能在上游眼里是
    同一设备 → 全同 ⇒ 冲突；只同一半 ⇒ 也冲突；全异 ⇒ 才通过。
    """
    _account(tmp_path, "trae-1", machine_id="mid-1", device_id="dev-1")
    # 全同 → 冲突
    assert device.check_unique(tmp_path, TWO_FIELD, ("mid-1", "dev-1")) is False
    assert device.find_account_by_values(tmp_path, TWO_FIELD, ("mid-1", "dev-1")) == "trae-1"
    # 同 machine_id、不同 device_id → 仍冲突（旧实现只比整元组会在此静默放过）
    assert device.check_unique(tmp_path, TWO_FIELD, ("mid-1", "dev-2")) is False
    assert device.find_account_by_values(tmp_path, TWO_FIELD, ("mid-1", "dev-2")) == "trae-1"
    # 同 device_id、不同 machine_id → 仍冲突
    assert device.check_unique(tmp_path, TWO_FIELD, ("mid-2", "dev-1")) is False
    # 全异 → 通过
    assert device.check_unique(tmp_path, TWO_FIELD, ("mid-2", "dev-2")) is True
    assert device.find_account_by_values(tmp_path, TWO_FIELD, ("mid-2", "dev-2")) is None


def test_multi_field_partial_account_still_occupies_its_fields(tmp_path):
    """身份残缺的账号（只落了部分字段）**按已有字段参与**判定（保守口径）。"""
    _account(tmp_path, "half", machine_id="mid-1")
    assert device.check_unique(tmp_path, TWO_FIELD, ("mid-1", "dev-9")) is False
    assert device.check_unique(tmp_path, TWO_FIELD, ("mid-9", "dev-9")) is True


def test_multi_field_comparison_is_field_aligned(tmp_path):
    """比较按**同字段对齐**：候选的 machine_id 不与别人的 device_id 比（不跨字段误伤）。"""
    _account(tmp_path, "trae-1", machine_id="mid-1", device_id="dev-1")
    # 候选 machine_id 恰好等于对方 device_id，但两字段各自都不同 → 不冲突
    assert device.check_unique(tmp_path, TWO_FIELD, ("dev-1", "dev-2")) is True
    # 同名同值 → 冲突
    assert device.check_unique(tmp_path, TWO_FIELD, ("mid-1", "dev-2")) is False


# ============ 生成路径（多字段：逐字段生成）============

def test_generate_unique_refuses_multi_field_spec(tmp_path):
    """🔴 已修缺陷的防回归：单值生成器对多字段规格**显式报错**（曾经静默通过）。"""
    with pytest.raises(ValueError, match="generate_identity_values"):
        device.generate_unique(tmp_path, TWO_FIELD)


def test_generate_identity_values_multi_field_is_complete_and_unique(tmp_path):
    """多字段逐字段生成：两字段都非空、字段间互异、与既有账号不冲突。"""
    _account(tmp_path, "owner", machine_id="mid-1", device_id="dev-1")
    values = device.generate_identity_values(tmp_path, TWO_FIELD)
    assert len(values) == 2 and all(values)
    assert values[0] != values[1]
    assert device.check_unique(tmp_path, TWO_FIELD, values) is True


def test_generate_identity_values_retries_on_collision_then_succeeds(tmp_path):
    """全随机字段：与既有账号冲突 → **整体重生成**，有上限（耗尽显式失败）。"""
    seen: list[tuple[str, ...]] = []

    def is_unique(values: tuple[str, ...]) -> bool:
        seen.append(values)
        return len(seen) >= 3

    values = device.generate_identity_values(tmp_path, TWO_FIELD, is_unique=is_unique)
    assert len(seen) == 3 and values == seen[-1]

    with pytest.raises(RuntimeError, match="无法生成唯一设备身份"):
        device.generate_identity_values(tmp_path, TWO_FIELD, tries=2,
                                        is_unique=lambda values: False)


def test_generate_identity_values_keeps_product_provided_values(tmp_path):
    """`derive` 语义保持：产品侧提供的值（含官方算法派生结果）**原样采用**，其余字段补生成。"""
    values = device.generate_identity_values(tmp_path, TWO_FIELD,
                                             presets={"device_id": "derived-15"})
    assert values[1] == "derived-15" and values[0]
    assert device.check_unique(tmp_path, TWO_FIELD, values) is True


def test_generate_identity_values_provided_value_conflict_fails_loudly(tmp_path):
    """供给值（产品侧）与既有账号冲突 → **显式失败、不重随机**（不偷换算法）。"""
    _account(tmp_path, "owner", machine_id="mid-1", device_id="dev-1")
    with pytest.raises(RuntimeError, match="不重随机"):
        device.generate_identity_values(tmp_path, TWO_FIELD, presets={"device_id": "dev-1"})


def test_generate_identity_values_derive_is_deterministic_per_field(tmp_path):
    """`derive=True` + seed → 逐字段确定性派生：同 seed 同值、字段间互异（不重随机）。"""
    a = device.generate_identity_values(tmp_path, TWO_FIELD, seed="uid-1")
    b = device.generate_identity_values(tmp_path, TWO_FIELD, seed="uid-1")
    assert a == b and a[0] != a[1]
    assert a[0] == device.derive_id(TWO_FIELD, "uid-1", field="machine_id")

    _account(tmp_path, "owner", machine_id=a[0], device_id="dev-x")
    with pytest.raises(RuntimeError, match="不重随机"):
        device.generate_identity_values(tmp_path, TWO_FIELD, seed="uid-1")


# ============ 导入路径决策（硬约束 2 / 3）============

def test_import_plan_reuses_original_id(tmp_path):
    """🔴 硬约束 2：缓存里已有设备 ID → **原样复用，绝不重新生成**。"""
    plan = plan_import_device(tmp_path, ONE_FIELD, "cached-mid-777")
    assert plan.ok and plan.device_id == "cached-mid-777"


def test_import_plan_conflict_is_rejected_by_default(tmp_path):
    """🔴 硬约束 3：冲突 → 拒绝 + 报出占用者（**不自动替换**，交用户决策）。"""
    _account(tmp_path, "owner", machine_id="shared")
    plan = plan_import_device(tmp_path, ONE_FIELD, "shared")
    assert plan.ok is False and plan.conflict is True and plan.conflict_with == "owner"
    assert "未导入" in plan.message


def test_import_plan_regenerate_and_reuse(tmp_path):
    _account(tmp_path, "owner", machine_id="shared")
    regen = plan_import_device(tmp_path, ONE_FIELD, "shared", regenerate=True)
    assert regen.ok and regen.device_id and regen.device_id != "shared"
    assert device.check_unique(tmp_path, ONE_FIELD, (regen.device_id,)) is True

    reuse = plan_import_device(tmp_path, ONE_FIELD, "shared", reuse="owner")
    assert reuse.ok and reuse.device_id == "shared"

    missing = plan_import_device(tmp_path, ONE_FIELD, "shared", reuse="ghost")
    assert missing.ok is False and "--reuse" in missing.message


def test_import_plan_without_incoming_id_generates_unique(tmp_path):
    _account(tmp_path, "owner", machine_id="mid-1")
    plan = plan_import_device(tmp_path, ONE_FIELD, "")
    assert plan.ok and plan.device_id not in ("", "mid-1")
    assert device.check_unique(tmp_path, ONE_FIELD, (plan.device_id,)) is True


def test_import_plan_without_device_identity_passes_through(tmp_path):
    """无设备身份的产品（buddy/workbuddy/cline/loomy）→ 无冲突可言、不生成。"""
    plan = plan_import_device(tmp_path, DeviceSpec(fields=(), derive=False), "")
    assert plan.ok and plan.device_id == ""


# ============ 导入路径决策（多字段：全字段查重 + 缺字段补生成）============

def test_import_plan_multi_field_same_machine_id_conflicts(tmp_path):
    """🔴 同 machine_id、不同 device_id ⇒ 冲突（旧实现只比整元组会静默放过）。"""
    _account(tmp_path, "owner", machine_id="mid-1", device_id="dev-1")
    plan = plan_import_device(tmp_path, TWO_FIELD, ("mid-1", "dev-2"))
    assert plan.ok is False and plan.conflict is True and plan.conflict_with == "owner"

    same_all = plan_import_device(tmp_path, TWO_FIELD, ("mid-1", "dev-1"))
    assert same_all.ok is False and same_all.conflict is True

    fresh = plan_import_device(tmp_path, TWO_FIELD, ("mid-9", "dev-9"))
    assert fresh.ok and fresh.device_values == ("mid-9", "dev-9")
    assert fresh.device_id == "mid-9"


def test_import_plan_multi_field_fills_missing_fields(tmp_path):
    """部分字段的载荷：已有值**原样保留**（硬约束 2），缺失字段逐字段补生成。"""
    plan = plan_import_device(tmp_path, TWO_FIELD, ("mid-7", ""))
    assert plan.ok and plan.device_values[0] == "mid-7" and plan.device_values[1]
    assert device.check_unique(tmp_path, TWO_FIELD, plan.device_values) is True


def test_import_plan_multi_field_reuse_takes_target_identity(tmp_path):
    """`--reuse`：取目标账号的**完整**身份（多字段逐字段），目标身份残缺 → 报不存在。"""
    _account(tmp_path, "owner", machine_id="mid-1", device_id="dev-1")
    reuse = plan_import_device(tmp_path, TWO_FIELD, ("mid-1", "dev-2"), reuse="owner")
    assert reuse.ok and reuse.device_values == ("mid-1", "dev-1")

    _account(tmp_path, "half", machine_id="mid-2")
    incomplete = plan_import_device(tmp_path, TWO_FIELD, ("mid-2", "dev-3"), reuse="half")
    assert incomplete.ok is False and "--reuse" in incomplete.message
