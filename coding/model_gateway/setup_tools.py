"""工具接入配置下发（tech-design v2.0 §12.4 / PRD Q25-⑨）。

**路径 A · 文件下发**：把网关的系统模型 + 能力位写成工具可读的 `models.json`。

🔴 为什么需要（§12.4）：实测 WorkBuddy CLI **只读文件、不调 `/v1/models`** ——
    只做 API 下发（路径 B）对它**完全无效**。两条路径都要做。

🔴 目录解析规则（PRD Q25-⑨ **明文要求**）：
    1. 环境变量 `WORKBUDDY_CONFIG_DIR` / `CODEBUDDY_CONFIG_DIR`（**最高优先级**）
    2. 产品配置的 `customUserDataDir`
    3. **按「产品标识 → `dataFolderName`」解析**（WorkBuddy=`.workbuddy`，WorkBuddy AI=`.workbuddy-ai`）
    ⚠️ **不得使用 `productName` 的子串判断** —— 实测其实现为 `includes("workbuddy")`，
       **对两个产品均返回 true，永远推不出 `.workbuddy-ai`**。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProductSpec:
    """产品注册表条目。`data_folder_name` 是目录解析的**唯一依据**（Q25-⑨）。"""

    key: str                # 产品标识（如 "workbuddy" / "workbuddy-ai"）
    display: str            # 展示名
    data_folder_name: str   # 🔴 目录名（`.workbuddy` / `.workbuddy-ai`）
    config_envs: tuple[str, ...] = ()   # 该产品读取的环境变量（按优先级）
    custom_user_data_dir: str = ""      # product.config.customUserDataDir（次优先）


PRODUCTS: dict[str, ProductSpec] = {
    "workbuddy": ProductSpec(
        key="workbuddy", display="WorkBuddy", data_folder_name=".workbuddy",
        config_envs=("WORKBUDDY_CONFIG_DIR", "CODEBUDDY_CONFIG_DIR"),
    ),
    "workbuddy-ai": ProductSpec(
        key="workbuddy-ai", display="WorkBuddy AI", data_folder_name=".workbuddy-ai",
        config_envs=("WORKBUDDY_CONFIG_DIR", "CODEBUDDY_CONFIG_DIR"),
    ),
}


def resolve_target_dir(product: str, home: Path | None = None,
                       env: dict[str, str] | None = None) -> tuple[Path, str]:
    """解析工具配置目录，返回 `(目录, 来源说明)`。

    来源说明会**打印给用户确认**（§12.4.1 写入纪律 0）—— 因为实测该路径
    **曾被环境变量劫持**（`WORKBUDDY_CONFIG_DIR` 由另一个产品注入）。
    """
    spec = PRODUCTS.get(product)
    if spec is None:
        raise ValueError(f"未知产品 '{product}'（可选：{', '.join(PRODUCTS)}）")
    env = env if env is not None else dict(os.environ)
    home = home if home is not None else Path.home()

    # ① 环境变量（最高优先级）
    for name in spec.config_envs:
        v = (env.get(name) or "").strip()
        if v:
            return Path(v), f"环境变量 {name}"
    # ② 产品配置的 customUserDataDir
    if spec.custom_user_data_dir:
        return home / spec.custom_user_data_dir, "产品配置 customUserDataDir"
    # ③ 🔴 按「产品标识 → dataFolderName」解析（**不得用 productName 子串判断**）
    return home / spec.data_folder_name, f"产品标识 {spec.key} → dataFolderName {spec.data_folder_name}"


def build_models_json(models: list[dict[str, Any]]) -> dict[str, Any]:
    """构造 CLI 侧 `models.json` 内容。

    🔴 格式（实测 `08` §4.1）：`{"models": [...], "availableModels": [...]}`。
       **裸数组会被 CLI 解析器直接丢弃**（GUI 用的是裸数组，两者格式不同、不可混用）。
    """
    return {
        "models": list(models),
        "availableModels": [m["id"] for m in models if m.get("id")],
    }


def merge_models(existing: Any, incoming: list[dict[str, Any]]) -> tuple[list[dict], int]:
    """合并：保留已有条目，按 `id` 覆盖同名、追加新名。

    返回 `(合并结果, 新增数)`。**不删除任何已有条目**（防"静默清空"事故）。
    """
    by_id: dict[str, dict] = {}
    order: list[str] = []
    if isinstance(existing, dict):
        for m in (existing.get("models") or []):
            if isinstance(m, dict) and m.get("id"):
                by_id[m["id"]] = m
                order.append(m["id"])
    elif isinstance(existing, list):  # 兼容 GUI 的裸数组形态
        for m in existing:
            if isinstance(m, dict) and m.get("id"):
                by_id[m["id"]] = m
                order.append(m["id"])
    added = 0
    for m in incoming:
        mid = m.get("id")
        if not mid:
            continue
        if mid not in by_id:
            order.append(mid)
            added += 1
        by_id[mid] = m  # 同名覆盖（更新能力位）
    return [by_id[i] for i in order], added


@dataclass
class WriteResult:
    ok: bool
    target: Path
    source: str
    backup: Path | None = None
    added: int = 0
    total: int = 0
    message: str = ""
    rolled_back: bool = False


def write_models_json(
    product: str,
    models: list[dict[str, Any]],
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    dry_run: bool = False,
) -> WriteResult:
    """写入 `models.json`（§12.4.1 写入纪律）。

    纪律（四条 + 第 0 条）：
    0. **写前打印解析结果并等待确认**（由 CLI 层做；本函数只返回 `source` 供打印）
    1. **写入前先备份**为 `models.json.bak-<ts>`（该文件存在**外部并发写**，历史上被清空过）
    2. **合并而非覆盖**（保留用户已有条目）
    3. **原子写**：同目录 tempfile + `os.replace`
    4. 写入后**读回校验**；失败用备份回滚
    """
    target_dir, source = resolve_target_dir(product, home=home, env=env)
    target = target_dir / "models.json"

    existing: Any = None
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = None

    merged, added = merge_models(existing, models)
    payload = build_models_json(merged)

    if dry_run:
        return WriteResult(ok=True, target=target, source=source,
                           added=added, total=len(merged),
                           message=f"[dry-run] 将写入 {len(merged)} 条（新增 {added}）")

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return WriteResult(ok=False, target=target, source=source,
                           message=f"目录不可写：{e}")

    # 1. 备份
    backup: Path | None = None
    if target.exists():
        import datetime as _dt
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = target.with_name(f"models.json.bak-{ts}")
        try:
            backup.write_bytes(target.read_bytes())
        except OSError as e:
            return WriteResult(ok=False, target=target, source=source,
                               message=f"备份失败，已中止（不冒险写入）：{e}")

    # 3. 原子写（同目录 tempfile + os.replace）
    try:
        fd, tmp_name = tempfile.mkstemp(dir=str(target_dir), prefix=".models-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, target)
    except OSError as e:
        return WriteResult(ok=False, target=target, source=source, backup=backup,
                           message=f"写入失败：{e}")

    # 4. 读回校验
    try:
        back = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(back, dict) or not isinstance(back.get("models"), list):
            raise ValueError("读回内容格式异常")
    except (OSError, ValueError) as e:
        rolled = False
        if backup is not None and backup.exists():
            try:
                target.write_bytes(backup.read_bytes())
                rolled = True
            except OSError:
                pass
        return WriteResult(ok=False, target=target, source=source, backup=backup,
                           rolled_back=rolled,
                           message=f"读回校验失败：{e}" + ("（已从备份回滚）" if rolled else "（回滚失败）"))

    return WriteResult(ok=True, target=target, source=source, backup=backup,
                       added=added, total=len(merged),
                       message=f"已写入 {target}（{len(merged)} 条，新增 {added}）")
