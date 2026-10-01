"""「账号接入」页判据门（M7-UI / design-accounts-list-v2.md §8-1）纳入机械门 —— 含变异自证。

为什么必须在 pytest 里跑：`scripts/verify_accounts_ui.mjs` 是这一页唯一的静态判据
（族层消失 / rail 平铺 10 行 / 唯一接入入口 / 额度四值 / 列集逐字 / 禁用词零命中），
此前只能手工敲；手工的门等于没有门 —— 本页已经被"没人拦"的方式交付坏过两次
（M6 一版、M7 v1 一版）。设计书 §8-1 要求「判据先行」，门已入库，本测试就是给它接上电。

口径照 `test_int_v2_frontend_gate.py`：① 真实跑门（不启服务、不发网络、不读 config）；
② 要求退出码 0 且 `0 失败`；③ **判据条数本身也要钉住**（门被悄悄删窄必须立刻红）；
④ 变异自证：8 条回归变异每个都要能打红指定判据。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO.parent / "bianyiandhuanjing" / "scripts" / "verify_accounts_ui.mjs"

#: 本门当前实有判据条数（R0 + V1~V8 + L-A6/A8/A10 = 12）。
#: 🔴 下限钉在**当前真实条数**上，不是"很久以前的条数"：留个旧下限等于允许门悄悄
#:    缩水若干条而一声不响（同 `test_int_v2_frontend_gate.py:107-111` 的教训）。
MIN_CHECKS = 14
#: 变异表条数下限（设计书 §8-1 要求八条 V 判据每条配一个能打红的变异）。
MIN_MUTATIONS = 9


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=300, cwd=str(REPO))


@pytest.fixture(scope="module")
def node() -> str:
    found = shutil.which("node")
    if not found:
        pytest.skip("本机无 node，账号接入页门无法执行")
    return found


def test_accounts_ui_assertions_all_pass(node):
    """实测：12 条判据全绿（V1 族层消失 / V2 平铺 10 行 / V3 唯一接入入口 /
    V4 额度读 runtime.quota（BUG-1）/ V5 圆点不当动作目标 / V6 列集逐字 /
    V7 额度四值口径含「尚未刷新」（BUG-2）/ V8 禁用词零命中 +
    L-A6/A8/A10 三条反转的 M6-IX 判据）。"""
    r = _run([node, str(SCRIPT)])
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "0 失败" in r.stdout, r.stdout
    # 🔴 取**最后一次**出现（同前端门 L104-109 的口径）：门的人读输出里判据名/注记
    #    也可能出现「合计」二字，取第一段会解析到别的数字，下限形同虚设。
    tail = r.stdout.rsplit("合计：", 1)
    assert len(tail) == 2, f"门没有报出「合计：N 通过 / M 失败」汇总行：\n{r.stdout[-400:]}"
    m = re.search(r"(\d+)\s*通过\s*/\s*(\d+)\s*失败", tail[1])
    assert m, f"汇总行形状变了，判据条数无从核对：{tail[1][:200]!r}"
    passed, failed = int(m.group(1)), int(m.group(2))
    assert failed == 0, f"门自报 {failed} 条失败"
    assert passed >= MIN_CHECKS, \
        f"判据总数只剩 {passed} 条（门被删窄也要能红；当前应有 {MIN_CHECKS} 条）"


def test_accounts_ui_assertions_can_actually_go_red(node):
    """🔴 变异自证：8 个源码变异都必须让指定判据变红，且门里不能出现「永远绿」的死判据。

    本门的基线本身已由上一条测试证明全绿，故这里回归变异 → 必须变红是有效判据
    （门自证口径见 `verify_accounts_ui.mjs:33-43`）。
    """
    r = _run([node, str(SCRIPT), "--mutation"])
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "BAD" not in r.stdout, f"变异锚点过期/命中数不符（假通过最隐蔽的形态）：\n{r.stdout}"
    left, total = r.stdout.rsplit("可红 ", 1)[1].split("；")[0].split("/")
    assert int(left) == int(total), f"只有 {left}/{total} 个变异能打破绿态"
    assert int(total) >= MIN_MUTATIONS, f"变异表缩水到 {total} 条（每条判据都得配一个能打红的变异）"
