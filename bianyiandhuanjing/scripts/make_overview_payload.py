#!/usr/bin/env python
"""生成前端验收门（verify_v2_frontend.mjs）所需的 overview.json 载荷。

单一真相：**复用** pytest 侧的装配函数 `test_int_v2_frontend_gate._overview_payload`
（真实端点 `/admin/api/overview` 产出，含四类告警 + 熔断资源 + 整页字段），
这样 `ship-gate.sh --gates` 手工跑的门和 pytest 跑的是同一份载荷。

用法：python bianyiandhuanjing/scripts/make_overview_payload.py <输出目录>
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CODING = REPO / "coding"
for p in (CODING, CODING / "tests" / "integration"):
    sys.path.insert(0, str(p))


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/mgw-gate")
    out_dir.mkdir(parents=True, exist_ok=True)
    from test_int_v2_frontend_gate import _overview_payload

    print(_overview_payload(out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
