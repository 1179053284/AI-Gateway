"""路径解析：配置 / 数据目录 / 各类状态文件（**必须与 cwd 无关**）。

🔴 为什么单独成模块（验收 eng M-4）：全项目原先到处写 `Path("data") / ...`，
含义是"**当前工作目录下的 data/**"。而 `mgw` CLI 是独立进程、可以在任意目录执行
（用户从 `~` 敲 `mgw zcode claim`），于是同一份数据被解析成两个不同位置：

| 后果 | 表现 |
|---|---|
| 运营互斥锁 | cron 用 `<repo>/data/ops-locks`、CLI 用 `~/data/ops-locks` → **跨进程互斥形同不存在** |
| 3012 熔断状态 | 熔断文件写到别处 → 重启/跨进程读不到，熔断永不生效 |
| 单实例锁 | 两个目录各建一把锁 → 可起**两个网关实例**抢同一端口 |
| `MG_CONFIG` | 被 `load_config()` 完全忽略 → CLI 打到错误端口/错误配置 |

**规则**：需要"项目数据目录"时一律经本模块解析；`MG_CONFIG` / `MGW_*` 环境变量**优先级最高**；
返回值一律 `.resolve()` 成绝对路径。
"""

from __future__ import annotations

import os
from pathlib import Path

#: 环境变量名：全包唯一事实源（需要它的地方 `from . import paths` 用它，别各自再导一份别名）
CONFIG_ENV = "MG_CONFIG"

#: 包所在目录的父级 = 项目根（本项目按源码目录 / `pip install -e .` 运行）
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    """`MG_CONFIG` 优先，其次项目根的 `data/config.yaml`（**不随 cwd 变**）。"""
    raw = (os.environ.get(CONFIG_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (PROJECT_ROOT / "data" / "config.yaml").resolve()


def resolve_config_path(path: Path | str | None = None) -> Path:
    """三层优先级：显式参数 > `MG_CONFIG` > 项目默认。"""
    if path is not None and str(path).strip():
        return Path(path).expanduser().resolve()
    return default_config_path()


def data_dir(config_path: Path | str | None = None) -> Path:
    """运行时数据目录 = 生效配置文件的父目录（配置文件在哪，数据就跟着在哪）。

    这样 `MG_CONFIG=/x/my.yaml` 时不会把状态写回项目 `data/`，
    也不会因为 CLI 的 cwd 不同而分裂成两个目录。
    """
    return resolve_config_path(config_path).parent
