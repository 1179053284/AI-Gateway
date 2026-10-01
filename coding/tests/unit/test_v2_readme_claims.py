"""README 里那些"用户会照着核"的数字，必须有东西钉住（第十一轮 PM B-11-4 / B-11-2）。

上一轮 README 写着 `462/462 tests`、`v0.2.0`，实测是 705 条与 `mgw --version`=0.1.0，
还把证据指向 `docs/…` —— 而 `docs/` 在 .gitignore 里，用户点开就是 404。
这类失真不会被任何功能测试抓到：它既不是崩溃也不是错判，只是**文档在说谎**。
本文件的判据全部是"README 说的 == 跑出来的"，改文案的人不需要记得同步，红的是判据。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
READMES = {"README.md": REPO / "README.md", "README.zh-CN.md": REPO / "README.zh-CN.md"}


@pytest.fixture(scope="module")
def texts() -> dict[str, str]:
    return {n: p.read_text(encoding="utf-8") for n, p in READMES.items()}


@pytest.fixture(scope="module")
def collected() -> int:
    """真实测试条数 —— 用 `--collect-only` 现算，不抄任何文档里的数字。"""
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--collect-only",
                        "-p", "no:warnings", "--basetemp=/tmp/mgw-pytest-collect"],
                       capture_output=True, text=True, cwd=str(REPO), timeout=300)
    m = re.search(r"(\d+) tests? collected", r.stdout)
    assert m, f"没能从收集输出里读到条数：\n{r.stdout[-400:]}\n{r.stderr[-400:]}"
    return int(m.group(1))


def test_readme_version_claims_match_the_code(texts):
    """README 报的版本 == `__version__` == `pyproject.toml`，且没留下旧版本字样。"""
    from model_gateway import __version__

    py = re.search(r'^version = "([^"]+)"',
                   (REPO / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    assert py and py.group(1) == __version__, f"pyproject {py and py.group(1)} ≠ {__version__}"
    for name, t in texts.items():
        assert f"v{__version__}" in t, f"{name} 里没有当前版本 v{__version__} 的字样"
    assert not re.search(r"v0\.1\.0", texts["README.md"] + texts["README.zh-CN.md"]), \
        "README 仍留着旧版本号（同一份文档两处版本 = 至少一处是假的）"


def test_cli_version_agrees_with_readme():
    """`mgw --version` 是用户唯一能自己核的出口，必须与 README 同一条款。"""
    r = subprocess.run([sys.executable, "-m", "model_gateway.cli", "--version"],
                       capture_output=True, text=True, cwd=str(REPO), timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    from model_gateway import __version__

    assert __version__ in r.stdout, f"CLI 报的是 {r.stdout.strip()!r}"


def test_readme_test_counts_are_not_stale(texts, collected):
    """🔴 文档里的测试条数只许**贴近真实**（±20），不许漂成一个时代的数字。

    方向也钉死：只许"文档 ≤ 真实"（新增测试还没来得及改文案），
    反向（文档比真实多）就是虚报通过数，一律红。
    """
    claims: list[tuple[str, int]] = []
    for name, t in texts.items():
        for m in re.finditer(r"tests-([0-9]+)%2F([0-9]+)|([0-9]{3,4})\s*(?:/| )*(?:passed|tests)", t):
            claims += [(name, int(g)) for g in m.groups() if g]
    assert claims, "README 里已经没有测试条数的宣称了 —— 判据要跟着删，别让它空过"
    for name, n in claims:
        assert n <= collected, f"{name} 宣称 {n} 条通过，实际只收集到 {collected} 条 = 虚报"
        assert collected - n <= 20, f"{name} 的数字漂了：宣称 {n}，实际 {collected}"


def test_login_first_disclaimer_ships_in_both_languages(texts):
    """PRD Q25-⑩ / tech-design §20-17 明令：文档须写「先登录工具，再配网关」。

    这条是**范围承诺**（网关不代用户登录工具），不是可选提示 —— 上一轮零命中。
    """
    assert "先登录工具，再配网关" in texts["README.zh-CN.md"], "中文 README 没写 Q25-⑩ 的那句话"
    assert re.search(r"Log in to the tool first", texts["README.md"]), \
        "英文 README 没有对应条款（双语必须同时交付）"
    assert "mgw setup` only writes" in texts["README.md"] or "只会写配置" in texts["README.zh-CN.md"], \
        "要同时说清 `mgw setup` 不代登录、只写配置"


def test_readmes_do_not_reference_gitignored_paths(texts):
    """`docs/` 与 `.cursor/` 都在 .gitignore 里 —— README 指过去就是给用户 404。

    `data/` 不在其列：README 提它是在说"**你本机**运行时产生的文件"（含明文密钥，
    本来就不该入库），不是在承诺一个仓库里的链接。
    """
    ignored = ("docs/", ".cursor/")
    for name, t in texts.items():
        hits = [w for w in ignored if w in t]
        assert not hits, f"{name} 引用了不入库的路径 {hits}（用户 clone 后点不开）"
