#!/bin/bash
# ship-gate —— 机械验收门（结构对齐 codex-coding：自验收 = 可复跑机械门，全绿才合并 main）
# 用法：
#   bash bianyiandhuanjing/scripts/ship-gate.sh            # 全量 pytest（默认门）
#   bash bianyiandhuanjing/scripts/ship-gate.sh --gates    # 追加前端/账号静态验收门
# 判据：退出码 0 = GREEN（可合并）；非 0 = RED（禁止合并，继续修）。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$ROOT/coding/.venv/bin/python"

if [ ! -x "$PY" ]; then
    echo "SHIP-GATE: RED —— 缺少 $PY（先在 coding/ 建 venv 并 pip install -e .）" >&2
    exit 1
fi

cd "$ROOT/coding" || exit 1

echo "== [1/2] pytest 全量 =="
if ! "$PY" -m pytest -q; then
    echo "SHIP-GATE: RED (pytest)" >&2
    exit 1
fi

if [ "${1:-}" = "--gates" ]; then
    echo "== [2/2] 前端/账号静态验收门 =="
    node "$ROOT/bianyiandhuanjing/scripts/verify_v2_frontend.mjs" || { echo "SHIP-GATE: RED (v2 frontend gate)" >&2; exit 1; }
    node "$ROOT/bianyiandhuanjing/scripts/verify_accounts_ui.mjs" || { echo "SHIP-GATE: RED (accounts gate)" >&2; exit 1; }
else
    echo "== [2/2] 跳过（--gates 可追加前端/账号门）=="
fi

echo "SHIP-GATE: GREEN"
