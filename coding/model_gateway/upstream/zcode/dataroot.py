"""ZCode 账号数据根与设备身份（tech-design v2.0 §15.3 / §17）。

**整根隔离**（采纳 `ZCode-Panel` 路线，而非 zcode-switch 的"覆写凭据"路线）：

```
accounts/<账号名>/
  data/.zcode/v2/     ← ZCODE_DATA_BASE_DIR        凭据/配置/日志/遥测/provider_config
  userdata/           ← ZCODE_DESKTOP_USER_DATA_DIR Chromium userData
  session/            ← ZCODE_DESKTOP_SESSION_DATA_DIR cookies/localStorage
  home/               ← ZCODE_DESKTOP_HOME_DIR      agent 的 shell HOME
  meta.json           ← 注册时间 / 设备码 / 切换次数
```

**为什么整根隔离优于覆写**：切换 = **启动对应账号的那一份数据**，
**不覆盖任何凭据文件** —— 根除"老架构把快照复制成全局 live"那一整类故障
（参考实现注释：`main.js:1264-1275`）。

**设备身份双通道**（§15.3）：`--device-id=<uuid>`（命令行）
+ `<账号>/data/.zcode/v2/telemetry-state.json` 的 `deviceMid`（遥测）—— 两条都要喂。

⚠️ 已知例外（§15.3，**不宣称"完全隔离"**）：
  - `setting.json` 由客户端**固定写主 `~/.zcode/v2/`**（不受 `ZCODE_DATA_BASE_DIR` 重定向）
  - ZCode **内置浏览器 session 跨账号共用**（客户端用 `app.setPath` 覆盖，`--user-data-dir` 无效）
  - 三个 `ZCODE_DESKTOP_*` 是否真的覆盖 `app.setPath` —— **本机未实测**（§19 T10）

🔴 设备身份三函数（`check_device_id_unique` / `find_account_by_device_id` /
   `generate_unique_device_id`）自 M6-1 起**委托公共层** `model_gateway/accounts/device.py`
   （tech-design §22.1「zcode 零重写：公共层按现状泛化，既有函数改为委托调用」）——
   本文件保留同名同签名的外壳（既有测试/调用点零改动），**行为零变化**。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from model_gateway.accounts.device import (
    check_unique,
    find_account_by_values,
    generate_unique,
)

# —— 整根隔离的四组环境变量（§15.3）——
ENV_DATA_BASE = "ZCODE_DATA_BASE_DIR"
ENV_USER_DATA = "ZCODE_DESKTOP_USER_DATA_DIR"
ENV_SESSION_DATA = "ZCODE_DESKTOP_SESSION_DATA_DIR"
ENV_HOME = "ZCODE_DESKTOP_HOME_DIR"

#: macOS 客户端进程名（**必须精确匹配**，否则会误杀自己的 Helper / Panel）
ZCODE_PROCESS_NAMES = ("ZCode",)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 目录布局 ----------

def data_root_of(accounts_root: Path, account: str) -> Path:
    return accounts_root / account / "data"


def v2_dir_of(accounts_root: Path, account: str) -> Path:
    return data_root_of(accounts_root, account) / ".zcode" / "v2"


def ensure_layout(accounts_root: Path, account: str) -> None:
    """建立账号目录骨架（幂等）。"""
    root = accounts_root / account
    for sub in ("data/.zcode/v2", "userdata", "session", "home"):
        (root / sub).mkdir(parents=True, exist_ok=True)


def build_env(accounts_root: Path, account: str,
              device_id: str | None = None) -> dict[str, str]:
    """构造启动客户端所需的环境变量（**在继承环境上追加**，不清空）。"""
    root = accounts_root / account
    env = {
        ENV_DATA_BASE: str(root / "data"),
        ENV_USER_DATA: str(root / "userdata"),
        ENV_SESSION_DATA: str(root / "session"),
        ENV_HOME: str(root / "home"),
    }
    return env


def build_args(device_id: str) -> list[str]:
    """构造命令行参数（**设备码通道 ①**）。"""
    return [f"--device-id={device_id}"]


# ---------- 设备身份 ----------

def _device_spec():
    """本产品的设备规格（唯一事实源 = `accounts/registry.py`，**不在此复制一份字段表**）。"""
    from model_gateway.accounts.registry import get as registry_get

    return registry_get("zcode").device


def ensure_device_id(accounts_root: Path, account: str) -> str:
    """取该账号的设备 ID；不存在则生成。**生成一次后永不重算。**

    ⚠️ 仅用于「**生成新账号**」路径 —— 导入路径见 `store.import_account`
    （冲突 → **拒绝 + 交用户决策**，不自动重生成；§15.1 硬约束 3）。
    """
    meta_path = accounts_root / account / "meta.json"
    meta = _read_json(meta_path)
    mid = meta.get("device_mid")
    if not (isinstance(mid, str) and mid.strip()):
        mid = str(uuid.uuid4())
        meta["device_mid"] = mid
        _write_json(meta_path, meta)
    return mid.strip()


def check_device_id_unique(accounts_root: Path, device_id: str) -> bool:
    """跨账号唯一性校验（§15.1 硬约束 1）。**委托公共层**（`accounts/device.py`）。

    **本函数只做校验、不做处置** —— 两条调用路径的处置不同（§15.1）：
      · 生成新账号：冲突 → 重新生成（有上限）
      · 导入已有账号：冲突 → **拒绝 + 交用户决策**（不自动重生成）
    """
    return check_unique(Path(accounts_root), _device_spec(), (device_id,))


def find_account_by_device_id(accounts_root: Path, device_id: str) -> str | None:
    """反查哪个账号占用了该设备 ID（冲突提示用）。**委托公共层**。"""
    return find_account_by_values(Path(accounts_root), _device_spec(), (device_id,))


def generate_unique_device_id(accounts_root: Path, *, tries: int = 20) -> str:
    """生成一个**跨账号唯一**的设备 ID（生成新账号路径用）。**委托公共层**。

    ⚠️ 有上限，**不静默降级** —— 耗尽则抛异常（UUID v4 碰撞概率极低，
    但"耗尽"意味着目录里已有巨量账号或读取异常，应当显式失败）。
    """
    # `is_unique` 显式包一层调本模块的 `check_device_id_unique`：既有单测 monkeypatch 它
    # 制造"永远冲突"来验上限，委托后这条缝必须保留（§22.1 行为零变化）。
    return generate_unique(
        Path(accounts_root), _device_spec(), tries=tries,
        is_unique=lambda mid: check_device_id_unique(accounts_root, mid))


def sync_device_mid_to_telemetry(accounts_root: Path, account: str,
                                 device_id: str) -> bool:
    """把设备码写入该账号的 `telemetry-state.json`（**设备码通道 ②**）。

    值相同则跳过写入（幂等，避免无谓的文件写）。
    """
    path = v2_dir_of(accounts_root, account) / "telemetry-state.json"
    data = _read_json(path)
    if str(data.get("deviceMid") or "").strip() == device_id:
        return False
    data["deviceMid"] = device_id
    _write_json(path, data)
    return True


# ---------- 启动 / 进程控制（Mac）----------

def is_zcode_running() -> bool:
    """探测 ZCode 是否在运行（macOS：`pgrep -x`，**必须精确匹配**）。"""
    if os.name != "posix":
        return False
    for name in ZCODE_PROCESS_NAMES:
        try:
            r = subprocess.run(["pgrep", "-x", name], capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and r.stdout.strip():
            return True
    return False


def kill_zcode(*, wait_seconds: float = 4.0) -> bool:
    """关闭 ZCode（优雅 → 强杀）。

    ⚠️ 必须 `pkill -x` **精确匹配** —— 宽匹配会连带杀掉
    `ZCode Helper` / `ZCode Panel` 等其它进程。
    """
    if os.name != "posix":
        return False
    for name in ZCODE_PROCESS_NAMES:
        with _suppress():
            subprocess.run(["pkill", "-x", name], capture_output=True, timeout=10)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if not is_zcode_running():
            return True
        time.sleep(0.2)
    if is_zcode_running():
        for name in ZCODE_PROCESS_NAMES:
            with _suppress():
                subprocess.run(["pkill", "-9", "-x", name],
                               capture_output=True, timeout=10)
        time.sleep(1.0)
    return not is_zcode_running()


class _suppress:
    """`with _suppress():` —— 抑制所有异常（进程操作尽最大努力）。"""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return True


def launch_command(exe: str, accounts_root: Path, account: str) -> tuple[str, list[str], dict]:
    """构造启动命令（**不实际启动**，便于单测与干跑）。

    返回 `(exe, args, env)` —— env 是**追加项**（调用方在此基础上合并父进程环境）。
    """
    device_id = ensure_device_id(accounts_root, account)
    sync_device_mid_to_telemetry(accounts_root, account, device_id)
    return exe, build_args(device_id), build_env(accounts_root, account)
