"""pytest 共享 fixture（test-cases.md §1 三层：unit 纯逻辑 / integration 假厂商 / e2e 实测）。"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _data_dir_isolated(tmp_path, monkeypatch):
    """🔴 每个用例的**数据目录**都指向自己的 tmp —— 生产路径一律经 `core/paths`，
    而它认 `MG_CONFIG`（数据目录 = 生效配置的父目录），所以这里只需钉住 MG_CONFIG。

    本轮实测踩到的污染：`mgw zcode claim` 的 CLI 腿要把结果落
    `data/usage/ops-results-<date>.jsonl`，测试跑一轮就把两行假数据
    写进了**用户正在使用的**仓库 `data/`（那是 live 配置目录，只读）。
    挡住它的正确位置是 conftest，而不是每个用例自己记得设。

    ⚠️ 配置目录刻意**不叫 `data`**：`MGW_ZCODE_ACCOUNTS` 在部分用例里就指向
    `tmp_path` 本身，同名会多出一个"假账号"目录 —— 而它顺手暴露了 `store.list_accounts()`
    把任意子目录当账号的真实缺陷（本轮已在生产侧修掉，见 `store.py` 注释）。
    """
    cfg = tmp_path / "mgw-conf" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MG_CONFIG", str(cfg))


@pytest.fixture(autouse=True)
def _ops_lock_dir_isolated(tmp_path, monkeypatch):
    """把运营互斥锁目录指到 tmp —— 锁文件是**跨进程**的，不能落在仓库 `data/` 里。

    `MGW_OPS_LOCK_DIR` 由 `ops.runner.ops_lock_dir()` **调用时**读取，
    因此对模块级单例 `_SHARED_LOCKS` 也生效（否则用例会互相串扰并污染真实运行目录）。
    """
    monkeypatch.setenv("MGW_OPS_LOCK_DIR", str(tmp_path / "ops-locks"))


@pytest.fixture(autouse=True)
def _ops_held_locks_reset():
    """清空"本进程持有集"：它是**进程级**状态，用例之间必须互不留痕。

    留一个未释放的键会让后续用例莫名其妙地被"另一入口正持有"挡住
    —— 这类串扰比缺断言更坑（表现为假失败，排查成本高）。
    """
    from model_gateway.ops import runner

    runner._HELD_BY_US.clear()
    yield
    runner._HELD_BY_US.clear()


@pytest.fixture(autouse=True)
def _circuit_singleton_isolated(tmp_path, monkeypatch):
    """重建 3012 熔断单例，指向本用例私有文件。

    🔴 熔断状态是**进程内单例 + 落盘**的：不重置的话，前一个用例里 `enter()` 写下的
    30 分钟熔断会让后续所有领取用例直接返回 `inactive`（表现为"莫名其妙全跳过了"）。
    """
    from model_gateway.upstream.zcode import quota as zq

    monkeypatch.setattr(zq, "circuit_path", lambda: tmp_path / "circuit.json")
    zq._reset_circuit_for_tests(tmp_path / "circuit.json")
    yield
    zq._reset_circuit_for_tests(tmp_path / "circuit.json")


@pytest.fixture(autouse=True)
def _no_real_local_admin_traffic(monkeypatch):
    """测试期**禁止**真的去敲 `127.0.0.1:<gateway.port>`。

    🔴 本机常态跑着一个真实的网关实例（默认 8300）：`mgw setup` / CLI 熔断回写
    在测试里若走真实 HTTP，会读到那个实例的运行态 —— 测试结论随本机状态漂移，
    甚至误伤真实实例。需要该通道的用例自行 monkeypatch 覆盖本 fixture。
    """
    # 只桩**网络层**（不桩 admin_get/admin_post 本身）：
    # 这样被测代码仍走完整的 URL 拼装与异常处理逻辑，测试才能验到"打到哪个端口"。
    import urllib.error

    import model_gateway.core.local_admin as la

    def _refused(*a, **k):
        raise urllib.error.URLError("测试环境不放行本机 HTTP")

    monkeypatch.setattr(la.urllib.request, "urlopen", _refused)
