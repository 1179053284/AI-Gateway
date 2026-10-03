"""M6 A-1 **接线**端到端红证（API 真实路径）：异步写盘不再阻塞事件循环。

背景（面板修复轮-2，eng-a A-1）：`store.commit_login` / `import_account` / `delete_account`
三条写路径的跨进程写锁等待（`_LOCK_WAIT_S = 1.0s`）与同步 fsync 写盘都发生在**调用线程**里。
异步服务路径（登录提交 `accounts/login.py::_commit_outcome`；管理端 import / refresh /
enable / disable / delete）如果直接调同步版，这段等待会把**整个事件循环**停摆
（eng-a 实测打点间隔 1007ms，所有并发请求一起被拖住）。修复 = 三条 `*_async` 入口把
整段下放工作线程；本文件把"**生产真的接了线**"钉死在 API 路径上：

- ① 接线后：持锁（另一进程）时 `POST /admin/api/accounts/{p}/{n}/disable` 等满锁预算
  （≥0.8s，证明真打到等锁路径）但**并发心跳**延迟 < 50ms（事件循环照常调度）；
- ② 撤接线（异步入口换回"协程里直接调同步版" = 未接线的调用形态）→ 同一并发心跳被
  拖住 ≥ 500ms（~1.0s 停摆红证）；
- ③ 恢复 → 新账号再打一拍，心跳回到 < 50ms。
- 另有 AST 静态判据逐点钉"五个接线点都是 `await store.*_async(...)`、同步版零残留"。

真 uvicorn 一律 `127.0.0.1:0`（随机端口）：`:8300` 与仓库 `data/` 零触碰；无网络。

⚠️ 本文件与 `test_m6_panel_fixes.py::test_a1_*` 的分工：那两条钉**入口函数自身**
（`store.commit_login_async` 的工作线程语义）；本文件钉**生产调用点真接了线**
（端点在 API 路径上不再直接调同步版）。
"""

from __future__ import annotations

import ast
import asyncio
import threading
import time
from pathlib import Path

import httpx
import pytest

from model_gateway.accounts import store
from tests.integration.conftest import chat_res, gateway_config

REPO = Path(__file__).resolve().parents[2]

#: 接入密钥（管理端免鉴权，仅 gateway 段完整性所需；同 `test_admin_accounts.py` 口径）
TOKENS = {"access_tokens": [{"id": "t-user", "value": "gw-user"}]}


def _cfg(port: int) -> dict:
    return gateway_config(port, models=[chat_res("A")], gateway=TOKENS)


def _seed(product: str, name: str) -> None:
    """造一个启用态账号（走生产同一条落盘入口；`enabled` 缺省 = 启用）。"""
    store.commit_login(product, name, {"token": "T"}, {})


def _lock_dir(tmp_path: Path, monkeypatch) -> Path:
    """把跨进程写锁目录指到 tmp（缺省落 `data/locks`，零触碰），并返回之。"""
    directory = tmp_path / "locks"
    monkeypatch.setenv(store.ACCOUNTS_LOCK_DIR_ENV, str(directory))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _hold_foreign_lock(directory: Path) -> None:
    """伪造"另一个进程持有锁"：pid=1 恒活 → 等满 1.0s 预算后**拒写**（fail closed）。"""
    (directory / store.ACCOUNTS_LOCK_NAME).write_text(f"1 {'f' * 16}", encoding="utf-8")


async def _probe(client: httpx.AsyncClient, gw, path: str) -> dict:
    """并发打两拍（同一事件循环、同一 client），心跳延迟 = "循环有没有被写请求拖住"。

    - 写请求 = `path`（会走到跨进程写锁等待）；
    - 心跳请求 = 廉价读端点（`GET /admin/api/accounts/capabilities`）。
    两任务**背靠背创建**（写先、心跳后），耗时从**发起时刻**起算（`t0` 在创建任务前
    取好：撤接线红态里心跳任务可能直到事件循环解冻才第一次被调度，用"任务首次运行"
    计时会把停摆时间漏掉）。
    """
    loop = asyncio.get_running_loop()

    async def _one(coro, t0: float) -> tuple[float, httpx.Response]:
        resp = await coro
        return time.monotonic() - t0, resp

    t_write = time.monotonic()
    write = loop.create_task(_one(client.post(f"{gw.base_url}{path}", json={}), t_write))
    t_hb = time.monotonic()
    heartbeat = loop.create_task(
        _one(client.get(f"{gw.base_url}/admin/api/accounts/capabilities"), t_hb))
    (write_s, write_resp), (hb_s, hb_resp) = await asyncio.gather(write, heartbeat)
    assert hb_resp.status_code == 200, hb_resp.text
    return {"write_s": write_s, "hb_s": hb_s, "write": write_resp}


@pytest.mark.asyncio
async def test_a1_wiring_disable_api_does_not_block_loop_and_revert_proves_it(
        vendor, make_gateway, client, tmp_path, monkeypatch):
    """🔴 A-1 接线三态闭环（API 真实路径）：绿 <50ms → 撤接线红 ~1s → 恢复绿。

    撤接线形态 = `store.commit_login_async` 换回"协程里直接调同步版"（修复前生产调用点
    的真实形态；`test_m6_panel_fixes.py` 的红证同款手法，但这里打在**端点收发**的
    API 路径上）—— 同一并发心跳立刻被拖住 ~1.0s。
    """
    gw = await make_gateway(_cfg(vendor.port))
    lock_dir = _lock_dir(tmp_path, monkeypatch)
    for name in ("acc-w1", "acc-w2", "acc-w3"):
        _seed("buddy", name)
    _hold_foreign_lock(lock_dir)                 # 此后一切写盘都要等满锁预算 → 拒写

    warm = await client.get(f"{gw.base_url}/admin/api/accounts/capabilities")  # 连接预热
    assert warm.status_code == 200

    # ① 接线后（绿）：写请求等满锁预算（真打到等锁路径），心跳毫秒级
    p1 = await _probe(client, gw, "/admin/api/accounts/buddy/acc-w1/disable")
    assert p1["write_s"] >= 0.8, (
        f"写请求没等满锁预算（{p1['write_s']:.2f}s）—— 没真打到跨进程等锁路径，判据不成立")
    assert p1["write"].status_code == 500 and "互斥" in p1["write"].text, p1["write"].text
    # 拒写 = 零落字节（启用位原样）
    assert store.load_meta(store.product_root("buddy"), "acc-w1").get("enabled", True) is True
    assert p1["hb_s"] < 0.05, (
        f"接线后心跳仍被写请求阻塞（{p1['hb_s'] * 1000:.0f}ms ≥ 50ms）—— "
        "async 入口没有把等锁下放工作线程")
    print(f"[A-1 接线①绿] 写 {p1['write_s']:.3f}s（等满锁预算） / 心跳 {p1['hb_s'] * 1000:.0f}ms（<50ms）")

    # ② 撤接线（红）：未接线形态 = 协程里直接调同步版 → 等锁落在事件循环线程
    async def _unwired(product, name, credentials, meta, *, root=None, via="login"):
        return store.commit_login(product, name, credentials, meta, root=root, via=via)

    # 🔴 Q33-①② 之后启停路径的**第一个等锁写者**不再是 `commit_login_async`：
    # 「一个开关一个主人」把派生资源位写在 meta 之前（先资源后 meta、meta 失败回滚），
    # 所以只撤 `commit_login_async` 这一条桩，写请求会先死在前一步的工作线程等锁里、
    # 心跳照常毫秒级 ⇒ 红证打不响（本仓纪律：红证不响 = 判据失效，必须随设计推进而不是放宽阈值）。
    # 改法 = 两条 async 入口**一起**换回"协程里直调同步版"，这才是修复前的真实生产形态。
    from model_gateway.accounts import materialize as mat_mod

    async def _unwired_resource(product, name, enabled, *, config_path=None):
        return mat_mod.set_resource_enabled(product, name, enabled, config_path=config_path)

    async def _unwired_ensure(product, name, *, config_path=None):
        return mat_mod.ensure_resource(product, name, config_path=config_path)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(store, "commit_login_async", _unwired)
        mp.setattr(mat_mod, "set_resource_enabled_async", _unwired_resource, raising=False)
        mp.setattr(mat_mod, "ensure_resource_async", _unwired_ensure, raising=False)
        p2 = await _probe(client, gw, "/admin/api/accounts/buddy/acc-w2/disable")
    assert p2["write_s"] >= 0.8
    assert p2["write"].status_code == 500, p2["write"].text
    assert p2["hb_s"] >= 0.5, (
        f"撤接线后心跳未被拖住（{p2['hb_s'] * 1000:.0f}ms < 500ms）—— 红证不成立："
        "写请求没有在事件循环线程上等锁（检查撤线桩是否生效）")
    print(f"[A-1 撤线②红] 写 {p2['write_s']:.3f}s（等满锁预算，在循环线程上） / 心跳 {p2['hb_s'] * 1000:.0f}ms（≥500ms）")

    # ③ 恢复（绿）：接线回来，新账号再打一拍 → 心跳立即回到毫秒级
    p3 = await _probe(client, gw, "/admin/api/accounts/buddy/acc-w3/disable")
    assert p3["write_s"] >= 0.8 and p3["write"].status_code == 500
    assert p3["hb_s"] < 0.05, (
        f"恢复接线后心跳仍被阻塞（{p3['hb_s'] * 1000:.0f}ms）—— 撤线桩没有恢复干净")
    print(f"[A-1 恢复③绿] 写 {p3['write_s']:.3f}s（等满锁预算） / 心跳 {p3['hb_s'] * 1000:.0f}ms（<50ms）")


# ============ 接线静态判据（AST：五个调用点逐点钉死）============

def _store_calls(tree: ast.Module, attr: str) -> tuple[int, int]:
    """模块里 `store.<attr>(...)` 调用的 `(await 形态数, 未 await 形态数)`（AST 级：注释/字符串不算）。"""
    awaited = {id(n.value) for n in ast.walk(tree)
               if isinstance(n, ast.Await) and isinstance(n.value, ast.Call)}
    in_await = plain = 0
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == attr
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "store"):
            if id(node) in awaited:
                in_await += 1
            else:
                plain += 1
    return in_await, plain


def test_async_service_paths_are_wired_to_the_await_forms():
    """🔴 接线判据（逐调用点）：异步服务路径的写盘**必须**是 `await store.*_async(...)`。

    - `api/admin_accounts.py`：`commit_login_async` 2 处（enable/disable 共用的
      `_set_enabled` 与 refresh）、`import_account_async` 1 处（import 端点）、
      `delete_account_async` 1 处（delete 端点）；三个**同步版零调用**；
    - `accounts/login.py`：`commit_login_async` 1 处（`_commit_outcome` —— poll /
      callback / alt 三通道同一实现）；同步版零调用。

    （CLI / 同步路径继续用同步版，不在本判据面内 —— 那是 `cli_zcode.py` 的调用面。）
    """
    admin = ast.parse(
        (REPO / "model_gateway" / "api" / "admin_accounts.py").read_text(encoding="utf-8"))
    login_mod = ast.parse(
        (REPO / "model_gateway" / "accounts" / "login.py").read_text(encoding="utf-8"))

    cases = [
        (admin, "commit_login_async", (2, 0)),
        (admin, "import_account_async", (1, 0)),
        (admin, "delete_account_async", (1, 0)),
        (admin, "commit_login", (0, 0)),
        (admin, "import_account", (0, 0)),
        (admin, "delete_account", (0, 0)),
        (login_mod, "commit_login_async", (1, 0)),
        (login_mod, "commit_login", (0, 0)),
    ]
    for tree, attr, want in cases:
        got = _store_calls(tree, attr)
        assert got == want, f"store.{attr} 调用形态漂移：期望 {want}（await 数, 未 await 数），实际 {got}"


@pytest.mark.asyncio
async def test_mappings_write_offloads_the_blocking_save(vendor, make_gateway, client, monkeypatch):
    """🔴 A-1 同族第二条（债务 Q33-债3 / 复验轮 R4-⑦）：映射写面阶段 3 也必须在工作线程里。

    与启停那条同形，但**阻塞源不同**：不是跨进程文件锁，而是本进程的**配置写锁**
    （`materialize.order_lock()`）+ 读盘 + `save_config` 的 fsync。三态闭环：
    ① 接线（写请求等满锁 ≥0.8s，心跳 <50ms）→ ② 撤接线（阶段 3 在循环线程里同步跑完，
    心跳 ≥500ms）→ ③ 恢复（<50ms）。阈值与 `test_a1_wiring_*` 完全同一把尺，**没有放宽**。

    ② 的桩 = 把 `asyncio.to_thread` 换成"在当前线程直接跑完"，即本轮修复前的生产形态；
    这一替换会让同窗口内其它 `to_thread` 也变同步（只会让红更强，不会把红掩掉）。
    """
    from model_gateway.api import admin_accounts as aa

    gw = await make_gateway(_cfg(vendor.port))
    _seed("buddy", "map-loop-1")
    body = {"product": "buddy", "items": [{"model": "vm-x", "target": "glm-5.3"}]}
    url = f"{gw.base_url}/admin/api/accounts/mappings"
    hb_url = f"{gw.base_url}/admin/api/accounts/capabilities"

    def _held_lock() -> threading.Lock:
        lk = threading.Lock()
        lk.acquire()
        threading.Timer(1.0, lk.release).start()
        return lk

    async def _probe() -> tuple[float, float, int]:
        """与文件头那条 `_probe` **同一计时形状**：起点取在创建任务之前，
        终点取在各任务**自己完成**的那一刻（在任务内部算）。

        🔴 两个错法都实测踩过（M21 那一轮）：
        ① 起点写在任务体内 ⇒ 循环被按住时心跳任务还没开始跑，起点也跟着晚 ⇒ 假绿 9ms；
        ② 终点写在 `asyncio.gather` 之后 ⇒ 量到的是两者里**更慢**的那个（写要等满锁 1s）
          ⇒ 接线态也"红"，判据反向失效。
        """
        loop = asyncio.get_running_loop()

        async def _one(coro, t0: float) -> tuple[float, httpx.Response]:
            resp = await coro
            return time.monotonic() - t0, resp

        t_write = time.monotonic()
        write = loop.create_task(_one(client.post(url, json=body), t_write))
        t_hb = time.monotonic()
        heartbeat = loop.create_task(_one(client.get(hb_url), t_hb))
        (write_s, write_resp), (hb_s, hb_resp) = await asyncio.gather(write, heartbeat)
        assert hb_resp.status_code == 200, hb_resp.text
        return write_s, hb_s, write_resp.status_code

    monkeypatch.setattr(aa, "materialize_order_lock", _held_lock)
    w1, h1, code1 = await _probe()
    assert code1 == 200
    assert w1 >= 0.8, f"写请求没等满配置写锁（{w1:.2f}s）⇒ 判据前提不成立"
    assert h1 < 0.05, f"接线后心跳被写请求拖住（{h1 * 1000:.0f}ms ≥ 50ms）"
    print(f"[映射写面①绿] 写 {w1:.3f}s（等满锁）/ 心跳 {h1 * 1000:.0f}ms（<50ms）")

    async def _inline(fn, *args, **kwargs):
        return fn(*args, **kwargs)                  # 未接线形态：阻塞动作留在事件循环线程

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(aa.asyncio, "to_thread", _inline)
        w2, h2, code2 = await _probe()
    assert code2 == 200 and w2 >= 0.8
    assert h2 >= 0.5, f"撤接线后心跳未被拖住（{h2 * 1000:.0f}ms < 500ms）⇒ 红证不成立"
    print(f"[映射写面②红] 写 {w2:.3f}s / 心跳 {h2 * 1000:.0f}ms（≥500ms）")

    w3, h3, code3 = await _probe()                  # ③ 恢复：桩随 context 退出撤销
    assert code3 == 200 and h3 < 0.05, f"恢复后心跳仍被阻塞（{h3 * 1000:.0f}ms）"
    print(f"[映射写面③绿] 写 {w3:.3f}s / 心跳 {h3 * 1000:.0f}ms（<50ms）")
