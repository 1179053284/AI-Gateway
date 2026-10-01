"""设备身份：zcode `dataroot` 三函数的**泛化**（tech-design v2.0 §15.1 / §22.2 不变式③）。

🔴 三条硬约束（§15.1，**对全部产品生效**，不只 zcode）：

| # | 约束 | 机制 |
|---|---|---|
| 1 | 不允许两个账号绑定到同一设备 ID | 生成：冲突→重生成（**有上限，不静默降级**）；导入：冲突→拒绝 |
| 2 | 导入已有账号缓存 → **复用原设备 ID** | 缓存里已有的值原样复用，**绝不重新生成** |
| 3 | 冲突 → **拒绝 + 报由用户决策** | 不自动替换（自动换 = 上游眼里"换设备"→ 反而触发风控） |

🔴 两条路径的处置**不同**（§15.1 裁决）：生成新账号可以重生成（新 ID 无上游历史），
   导入路径必须交用户决策 —— 该决策在 `store.plan_import_device()` 里，本模块只**校验**。

🔴 设备身份 = `DeviceSpec.fields` 各字段值（跨账号**逐字段比较，任一字段相同即冲突**）：
   多字段产品（trae 的 `machine_id`+`device_id`）只要共用一个身份字段就按同一设备拦下
   （保守口径，§22.3 裁决 2026-09-29：与 §15.1 三约束一致）。字段存 `meta.json`（§22.2），
   凭据本体不参与比较。

⚠️ 历史缺陷（W2-fix 已修，勿重犯）：旧实现把**单值候选**与完整元组比较 → 多字段规格下
   查重恒通过；单值生成器 `generate_unique` 现对多字段规格**显式报错**，多字段必须走
   `generate_identity_values`（逐字段生成完整元组）。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Callable

from model_gateway.accounts.types import DeviceSpec


def _meta_of(account_dir: Path) -> dict:
    """读该账号的 `meta.json`（读不动 → 空 dict，**不抛**：唯一性判定不该因坏文件中断）。

    判据与 zcode 既有口径一致：**目录里有 `meta.json` 才算账号**（防止把别的模块
    落在同一数据目录里的子目录当成账号，见 `upstream/zcode/store.py::list_accounts` 的教训）。
    """
    path = account_dir / "meta.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _present_fields(spec: DeviceSpec, meta: dict) -> dict[str, str]:
    """从 meta 里取该账号**实际存在**的设备身份字段值（逐字段）。

    - 字段缺失 / 非字符串 / `strip()` 后为空 → 该字段**缺席**（空身份不构成"占用"）；
    - 存盘值 `strip()` 后再比较（空白差异不算两个设备，照抄 zcode 原实现）。
    """
    out: dict[str, str] = {}
    for field in spec.fields:
        value = meta.get(field)
        if isinstance(value, str) and value.strip():
            out[field] = value.strip()
    return out


def check_unique(root: Path, spec: DeviceSpec, values: tuple[str, ...]) -> bool:
    """跨账号唯一性校验（§15.1 硬约束 1 的泛化；**任一身份字段相同即冲突**）。

    **只校验、不做处置**（§15.1：两条路径的处置不同，处置在调用方）。
    `values` = 待校验的设备身份（按 `spec.fields` 顺序；单字段调用方包成 1 元组）。
    根目录不存在 / 候选值全空 / 无账号带设备身份 → `True`（唯一）。
    """
    return find_account_by_values(root, spec, values) is None


def find_account_by_values(root: Path, spec: DeviceSpec, values: tuple[str, ...]) -> str | None:
    """反查哪个账号占用了该设备身份（冲突提示用，§15.1 交互契约要报"与谁冲突"）。

    🔴 口径（§22.3 裁决 2026-09-29）：**逐字段比较，任一字段值相同即冲突** ——
    多字段产品只要共用一个身份字段（如 trae 共用 `machine_id`）就按同一设备拦下
    （保守口径，与 §15.1 三约束一致）。比较是**同字段对齐**的（候选的 A 字段只与该
    账号的 A 字段比）；候选里的空白字段视作缺席、不参与。返回按目录名排序的**第一个**
    冲突账号。
    """
    wanted = [(field, v.strip()) for field, v in zip(spec.fields, values)
              if isinstance(v, str) and v.strip()]
    if not wanted or not root.exists():
        return None
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        present = _present_fields(spec, _meta_of(entry))
        if any(present.get(field) == value for field, value in wanted):
            return entry.name
    return None


def derive_id(spec: DeviceSpec, seed: str, *, field: str = "") -> str:
    """**确定性派生占位**（`DeviceSpec.derive=True` 的产品用；`20 B12/§3.5`）。

    🔴 形态契约（§22.3）：同 seed 同值、跨进程稳定、天然互异、免持久化。
    `field` 指定时把字段名并入素材（多字段身份**逐字段派生**时保证各字段互异）；
    不指定 = 整元/单字段的既有素材（行为不变）。
    ⚠️ **这不是各产品官方算法**：trae 的官方形态是 `deriveDeviceId15(userId)`（15 位数字，
    `trae.ts:286`），真算法由产品层在 M6-2/M6-3 提供；此处只保证"derive=True 时不随机"
    这一可测形态（占位，**未核实**上游是否接受本形态）。
    """
    material = f"{field or '+'.join(spec.fields)}|{seed}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def generate_unique(root: Path, spec: DeviceSpec, *, seed: str = "", tries: int = 20,
                    is_unique: Callable[[str], bool] | None = None) -> str:
    """生成一个**跨账号唯一**的新设备标识（§15.1 硬约束 1 —— 仅「生成新账号」路径）。

    🔴 **只受理单字段规格**（`len(spec.fields) == 1`）：多字段必须走
      `generate_identity_values`（逐字段生成完整元组）。旧实现拿单值候选与完整元组比较
      → 多字段查重恒通过（§22.3 裁决 2026-09-29 的 W2-fix 缺陷根因），
      本函数现对多字段**显式报错**，拒绝再次静默通过。
    - `spec.derive=True` 且给了 `seed`（账号 uid/id）→ 走 `derive_id` **确定性派生**
      （不重随机；派生值与既有账号冲突 → 显式失败，不偷偷换算法）；
    - 其余 → `uuid4`，冲突即重生成，**有上限、不静默降级**（耗尽抛 `RuntimeError`，
      照抄 zcode：碰撞概率极低，耗尽意味着目录异常，应当显式失败）；
    - `is_unique` 可注入（既有 zcode 单测 monkeypatch 该判据，行为零变化）。
    """
    if not spec.fields:
        raise ValueError("该产品无设备身份（DeviceSpec.fields 为空），不应生成设备 ID")
    if len(spec.fields) != 1:
        raise ValueError(
            f"多字段设备身份 {spec.fields} 必须走 generate_identity_values："
            "generate_unique 只生成单个值，与完整身份比较会恒通过（已修缺陷）")
    check = is_unique if is_unique is not None else (
        lambda candidate: check_unique(root, spec, (candidate,)))
    if spec.derive and seed:
        candidate = derive_id(spec, seed)
        if check(candidate):
            return candidate
        raise RuntimeError(f"确定性派生的设备 ID 与既有账号冲突：{candidate}（不重随机）")
    for _ in range(tries):
        candidate = str(uuid.uuid4())
        if check(candidate):
            return candidate
    raise RuntimeError(f"无法生成唯一设备 ID（尝试 {tries} 次仍冲突）")


def generate_identity_values(root: Path, spec: DeviceSpec, *, seed: str = "",
                             presets: dict[str, str] | None = None, tries: int = 20,
                             is_unique: Callable[[tuple[str, ...]], bool] | None = None,
                             ) -> tuple[str, ...]:
    """生成一套**完整且跨账号唯一**的设备身份（§15.1 硬约束 1；**多字段路径**）。

    逐字段取值（§22.3 裁决 2026-09-29：「生成路径对多字段逐字段生成」）：
      ① `presets[field]` —— **产品侧提供的值**（含各产品官方算法的派生结果；
         `derive` 语义保持：派生由产品侧提供/授权，公共层不虚构产品算法）；
      ② 其余字段：`spec.derive=True` 且给了 `seed`（账号 uid/id）→ `derive_id(field=…)`
         **确定性派生**；否则 `uuid4`。

    🔴 冲突处置（与 `generate_unique` 同口径）：
      - 候选与既有账号**任一字段相同** → 冲突（保守口径，`check_unique`）；
      - 含确定性值（presets/派生）→ **显式失败、不重随机**（不偷换算法）；
      - 全随机 → 整体重生成，有上限（耗尽抛 `RuntimeError`）。
    `is_unique` 可注入（测试用）；返回值顺序 == `spec.fields`；空 spec → `()`（调用方先拦）。
    """
    if not spec.fields:
        return ()
    presets = dict(presets or {})
    has_deterministic = (spec.derive and bool(seed)) or any(
        isinstance(v, str) and v.strip() for v in presets.values())
    check = is_unique if is_unique is not None else (
        lambda values: check_unique(root, spec, values))

    def build() -> tuple[str, ...]:
        out: list[str] = []
        for field in spec.fields:
            preset = presets.get(field)
            if isinstance(preset, str) and preset.strip():
                out.append(preset.strip())
            elif spec.derive and seed:
                out.append(derive_id(spec, seed, field=field))
            else:
                out.append(str(uuid.uuid4()))
        return tuple(out)

    if has_deterministic:
        values = build()
        if check(values):
            return values
        raise RuntimeError(f"设备身份与既有账号冲突：{values}（含派生/供给值，不重随机）")
    for _ in range(tries):
        values = build()
        if check(values):
            return values
    raise RuntimeError(f"无法生成唯一设备身份（尝试 {tries} 次仍冲突）")
