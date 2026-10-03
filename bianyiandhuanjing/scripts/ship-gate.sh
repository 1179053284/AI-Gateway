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
    # 🔴 verify_v2_frontend.mjs 必须吃 `<overview-json>`（`:3734` 无参数 = 打印用法并 exit 2），
    #    原先这里裸调 `node …mjs` ⇒ `--gates` 分支与代码状态无关、永远在第 2 步红。
    #    载荷由 make_overview_payload.py 生成，它复用 pytest 侧同一个
    #    `test_int_v2_frontend_gate._overview_payload`（真实 `/admin/api/overview` 装配），
    #    保证手工门与 [1/2] pytest 门喂的是同一份形状，不落第二套真相。
    GATE_TMP="$(mktemp -d "${TMPDIR:-/tmp}/mgw-ship-gate.XXXXXX")" \
        || { echo "SHIP-GATE: RED —— mktemp 失败（门没有输入目录）" >&2; exit 1; }
    trap 'rm -rf "$GATE_TMP"' EXIT
    OVERVIEW_JSON="$("$PY" "$ROOT/bianyiandhuanjing/scripts/make_overview_payload.py" "$GATE_TMP" | tail -1)" \
        || { echo "SHIP-GATE: RED —— overview 载荷生成失败（门没有输入，结论无效）" >&2; exit 1; }
    if [ ! -s "$OVERVIEW_JSON" ]; then
        echo "SHIP-GATE: RED —— 载荷文件不存在或为空：${OVERVIEW_JSON:-（未取到路径）}" >&2
        exit 1
    fi
    echo "   载荷：$OVERVIEW_JSON"
    node "$ROOT/bianyiandhuanjing/scripts/verify_v2_frontend.mjs" "$OVERVIEW_JSON" || { echo "SHIP-GATE: RED (v2 frontend gate)" >&2; exit 1; }
    node "$ROOT/bianyiandhuanjing/scripts/verify_accounts_ui.mjs" || { echo "SHIP-GATE: RED (accounts gate)" >&2; exit 1; }
else
    echo "== [2/2] 跳过（--gates 可追加前端/账号门）=="
fi

echo "SHIP-GATE: GREEN"
