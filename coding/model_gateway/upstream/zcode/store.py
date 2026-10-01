"""ZCode 账号存储与导入（tech-design v2.0 §15.1 / §17）。

🔴 三条硬约束（用户需求 ①，**不可妥协**）：

| # | 约束 | 机制 |
|---|---|---|
| 1 | 不允许两个账号绑定到同一设备 ID | 分配时查唯一性；冲突则重新生成（**有上限，不静默降级**） |
| 2 | 导入已有账号缓存 → **复用原设备 ID** | 缓存内已有设备标识 → 原样复用，**绝不重新生成** |
| 3 | 冲突 → **拒绝 + 报由用户决策** | **不自动替换**（自动换 = 上游眼里"换设备" → 反而触发风控） |

🔴 两条路径的处置**不同**（§15.1 裁决）：
  · **生成新账号**：冲突 → 重新生成（新 ID 无上游历史，重生成无副作用）
  · **导入已有账号**：冲突 → **拒绝 + 交用户决策**（缓存里的 ID **已有上游登录历史**）

🔴 与公共层的关系（M6-1，§22.1「zcode 零重写」）：**账号根解析、账号名白名单、
   账号枚举判据、设备唯一性三原语、删除**都**委托 `model_gateway/accounts/`**
   （`store.py` / `device.py`）；本文件保留两样**产品私有**的东西：
   ① 整根隔离的 v2 目录落盘布局与凭据导入形态；② §15.1 三约束的**决策顺序**
   （与 `mgw zcode import` 的交互契约逐字绑定，见 `import_account` 的说明）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from model_gateway.accounts import store as accounts_store
from model_gateway.accounts.store import ImportResult
from model_gateway.upstream.zcode import dataroot

#: 本产品标识（§14.2 `Resource.product` / §16.4 operation 的 supported_products 对齐）
PRODUCT = "zcode"
# 账号根 = `data/upstream/zcode/accounts`（`MGW_ZCODE_ACCOUNTS` 可覆盖）：
# **调用时**由公共层 `accounts.store.product_root("zcode")` 解析 —— 原 `DEFAULT_ACCOUNTS_ROOT`
# 常量是 import 期求值（PM-accept-3 登记过该缺陷），委托后随之下线；环境变量口径不变。


@dataclass
class Account:
    name: str
    device_id: str = ""
    plan: str = ""
    status: str = "active"


def accounts_root() -> Path:
    """本产品账号根（委托公共层：`MGW_<PRODUCT>_ACCOUNTS` 口径的泛化，行为零变化）。"""
    return accounts_store.product_root(PRODUCT)


def has_account(name: str) -> bool:
    """该账号名是否属于本产品（运营执行器用它把账号映射到 product，§16.4）。"""
    return accounts_store.has_account(accounts_root(), name)


def list_accounts() -> list[Account]:
    """列出已接入账号（按目录名排序）。

    🔴 判据与 `has_account()` **同一把尺**：必须是"有 meta.json 的目录"（枚举委托
    公共层 `accounts.store.list_accounts`）。原实现把账号根下的**任何子目录**都当成
    一个账号，于是别的模块在同一个数据目录里落盘时（例如 `data/` 下多出一个 `data/`
    子目录），会被当成"多了一个 ZCode 账号" —— 直接后果是全局熔断 `bench_all_zcode()`
    去 bench 一个根本不存在的号，运营批量也替它白跑一轮。
    """
    root = accounts_root()
    out: list[Account] = []
    for name in accounts_store.list_accounts(PRODUCT, root=root):
        meta = dataroot._read_json(root / name / "meta.json")
        out.append(Account(
            name=name,
            device_id=str(meta.get("device_mid") or ""),
            plan=str(meta.get("plan") or ""),
            status=str(meta.get("status") or "active"),
        ))
    return out


def _extract_device_id(payload: dict) -> str:
    """从导入凭据里抽取设备 ID（多别名，防御性）。"""
    for k in ("device_mid", "deviceMid", "mid", "deviceId", "device_id"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _extract_account_name(payload: dict, fallback: str) -> str:
    for k in ("name", "id", "accountName"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return _sanitize(v.strip())
    return _sanitize(fallback)


def _sanitize(name: str) -> str:
    """账号名白名单（与参考实现同口径）：`[A-Za-z0-9_-]{1,32}` —— 防目录穿越。

    委托公共层 `accounts.store.sanitize_name`（清洗语义逐字一致，行为零变化）。
    """
    return accounts_store.sanitize_name(name)


def _load_payload(path: Path | None) -> dict | None:
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    # 允许外包一层 account / data / payload（与参考实现同口径）
    for outer in ("account", "data", "payload"):
        inner = data.get(outer)
        if isinstance(inner, dict):
            return inner
    return data


def import_account(path: str | None = None, *, reuse: str | None = None,
                   regenerate: bool = False, payload: dict | None = None,
                   fallback_name: str | None = None,
                   device_mid: str | None = None) -> ImportResult:
    """导入账号（§15.1 三条硬约束的落地）。

    决策顺序：
    1. 凭据里有设备 ID：
       - 唯一 → **复用**（硬约束 2）
       - 冲突 → 按 `reuse` / `regenerate` 处置；**两者都无 → 拒绝**（硬约束 3）
    2. 凭据里无设备 ID → 生成一个**跨账号唯一**的新 ID（硬约束 1）

    🔴 三个设备原语已委托公共层（`dataroot.check_device_id_unique` /
       `find_account_by_device_id` / `generate_unique_device_id` → `accounts.device`）；
       本函数只保留**决策顺序**——它与 `mgw zcode import` 的交互契约（`--reuse`/
       `--regenerate`、退出码 4 依赖 `conflict` 字段）逐字绑定（§15.1）。
       其余 9 个产品的同一决策走公共层 `accounts.store.plan_import_device`（同一套语义），
       zcode 的流程在 M6-3 对齐时再评估是否并入（并入必须保持本契约）。

    🔴 载荷理解扩展（Q31，2026-10-01；**决策顺序与上表零变化，只多"载荷从哪来"**）：
    - `payload`：直接给载荷对象（与 `path` 二选一；`upstream/zcode/imports.py` 的转换出口
      —— 面板/小店粘贴形态、面板账号目录、zcode-switch 文件都归到这一条）；
    - `fallback_name`：无 `path` 时载荷没带名字的兜底账号名（来源侧命名，如面板目录名）；
    - `device_mid`：显式覆盖载荷里的设备 ID（`mgw zcode import --device-mid`）——
      **只覆盖设备字段**，唯一性/冲突决策照旧（覆盖值照样要过三约束）。
    """
    root = accounts_root()
    if payload is None:
        payload = _load_payload(path)
    if payload is None or not isinstance(payload, dict):
        return ImportResult(ok=False, message="凭据不可用（路径不存在或不是合法 JSON）")
    override = str(device_mid or "").strip()
    if override:
        # 不改调用方的对象（复制一份再覆盖；`device_mid` 键在抽取顺序里排第一）
        payload = {**payload, "device_mid": override}

    fallback = fallback_name or (Path(path).stem if path else "account")
    name = _extract_account_name(payload, fallback)
    incoming_mid = _extract_device_id(payload)

    if has_account(name) and not (reuse or regenerate):
        return ImportResult(ok=False, message=f"账号『{name}』已存在（用 --reuse/--regenerate 覆盖）")

    # —— 有设备 ID：优先复用（硬约束 2）——
    if incoming_mid:
        if dataroot.check_device_id_unique(root, incoming_mid):
            return _commit(root, name, incoming_mid, payload)

        owner = dataroot.find_account_by_device_id(root, incoming_mid)
        if regenerate:
            new_mid = dataroot.generate_unique_device_id(root)
            return _commit(root, name, new_mid, payload)
        if reuse:
            reused = _reuse_device_id_of(root, reuse)
            if reused is None:
                return ImportResult(ok=False, message=f"--reuse 目标账号『{reuse}』不存在")
            return _commit(root, name, reused, payload)
        # 🔴 默认：**拒绝 + 交用户决策**（硬约束 3）
        return ImportResult(ok=False, conflict=True, account=name,
                            conflict_with=owner or "（未知）",
                            message=f"设备 ID 冲突（被『{owner}』占用），未导入")

    # —— 无设备 ID：生成唯一的新 ID（硬约束 1）——
    new_mid = dataroot.generate_unique_device_id(root)
    return _commit(root, name, new_mid, payload)


def _reuse_device_id_of(root: Path, account: str) -> str | None:
    meta = dataroot._read_json(root / _sanitize(account) / "meta.json")
    mid = meta.get("device_mid")
    return str(mid).strip() if isinstance(mid, str) and mid.strip() else None


def _commit(root: Path, name: str, device_id: str, payload: dict) -> ImportResult:
    """落盘：建目录骨架 + 写 meta.json + 凭据（若提供）+ 同步 telemetry。

    Q31（2026-10-01）扩展：载荷可带 `meta`（dict）→ 扁平标量键合并进 meta.json
    （面板 / switch 的 `family` 之类**展示镜像**字段；嵌套对象一律不落 —— meta.json 是
    账号元信息，不是第二个载荷容器）。
    """
    dataroot.ensure_layout(root, name)
    meta_path = root / name / "meta.json"
    meta = dataroot._read_json(meta_path)
    extra = payload.get("meta")
    if isinstance(extra, dict):
        meta.update({k: v for k, v in extra.items()
                     if isinstance(v, (str, int, float, bool)) or v is None})
    meta.update({
        "device_mid": device_id,
        "via": str(meta.get("via") or "import"),
        "imported_at": _now(),
    })
    dataroot._write_json(meta_path, meta)
    dataroot.sync_device_mid_to_telemetry(root, name, device_id)

    # 凭据：若 payload 带 credentials/config 则原样落进该账号的 v2 目录
    for fname in ("credentials.json", "config.json"):
        v = payload.get(fname)
        if isinstance(v, (dict, str)):
            dest = dataroot.v2_dir_of(root, name) / fname
            dest.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(v, str):
                dest.write_text(v, encoding="utf-8")
            else:
                dest.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    # Q31 修复（2026-10-01，E2E 抓到的缺口）：导入成功后自动物化资源（§22.5-1）。
    # 公共层 `accounts.store.commit_login` 自带物化（`mgw zcode login` 走它，已物化），
    # 而本私有导入路径原先**不物化** → 导入的账号进不了「模型映射 / 转接」（映射落点是
    # 物化资源）。口径与公共层 `_materialize_best_effort` 一致：**best-effort**，
    # 物化失败不回滚账号导入（本地写成功的事实不因配置写失败而抹掉）。
    _materialize_best_effort(name)
    return ImportResult(ok=True, account=name, device_id=device_id,
                        message=f"已导入账号 {name}")


def _materialize_best_effort(name: str) -> None:
    """导入后物化资源（失败只记日志，不回滚账号；与 `accounts.store` 同口径）。"""
    import logging
    try:
        from model_gateway.accounts import materialize  # 延迟：避免 import 期成环
        materialize.ensure_resource(PRODUCT, name)
    except Exception as e:  # noqa: BLE001 — best-effort，不反向破坏已成功的导入
        logging.getLogger("model_gateway.upstream.zcode.store").warning(
            "[zcode] 资源物化失败（账号已导入；可在「接入模型资源」页手动检查）：%s", e)


def _now() -> str:
    import datetime as dt
    return dt.datetime.now().isoformat(timespec="seconds")


def delete_account(name: str) -> bool:
    """删除账号目录（破坏性，调用方需确认）。委托公共层（判据与白名单同源）。"""
    return accounts_store.delete_account(PRODUCT, name, root=accounts_root())
