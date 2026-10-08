#!/usr/bin/env python
"""生成前端验收门（verify_v2_frontend.mjs）所需的 overview.json 载荷。

单一真相：**复用** pytest 侧的装配函数 `test_int_v2_frontend_gate._overview_payload`
（真实端点 `/admin/api/overview` 产出，含四类告警 + 熔断资源 + 整页字段），
这样 `ship-gate.sh --gates` 手工跑的门和 pytest 跑的是同一份载荷。

🔴 数据根隔离（2026-10-07 由一次真实自伤钉死）：pytest 侧靠 conftest 的 autouse fixture
把 `MG_CONFIG` 钉到 tmp，而**本脚本单独跑时没有那层保护** —— 不设 `MG_CONFIG` 时
`core/paths` 回落到仓库 `coding/data/`，于是载荷装配会
① 枚举到用户的 35 个真实账号、② 把门用的假账号（`store.commit_login` + 资源物化）
**写进用户正在使用的配置与账号目录**。所以这里在 import 装配函数之前就把 `MG_CONFIG`
钉进输出目录下的隔离根，并由 `_overview_payload` 侧的守卫二次兜住。

用法：python bianyiandhuanjing/scripts/make_overview_payload.py <输出目录>
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CODING = REPO / "coding"
for p in (CODING, CODING / "tests" / "integration"):
    sys.path.insert(0, str(p))


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/mgw-gate")
    out_dir.mkdir(parents=True, exist_ok=True)
    # 隔离数据根：账号/配置/运营锁全部落在输出目录里，绝不回落仓库 `coding/data/`
    isolated_cfg = out_dir / "mgw-conf" / "config.yaml"
    isolated_cfg.parent.mkdir(parents=True, exist_ok=True)
    os.environ["MG_CONFIG"] = str(isolated_cfg)
    os.environ.setdefault("MGW_OPS_LOCK_DIR", str(out_dir / "ops-locks"))
    from test_int_v2_frontend_gate import _overview_payload

    print(_overview_payload(out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
