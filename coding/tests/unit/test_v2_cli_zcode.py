"""v2.0 §19 M5-0 CLI 层测试 + 死代码护栏（本轮补 R6c / R7）。

补的正是验收判据里"零件有了、CLI 层没测"那几行：
- `import` 设备冲突 → **退出码 4 且不写盘**（§15.1 硬约束 3 的交互契约）
- `remove`（本轮接线 `store.delete_account`）破坏性确认流程
- 🔴 曾经无生产调用点的符号，必须**一直**有调用点（防再长出死代码）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from model_gateway.cli import main
from model_gateway.upstream.zcode import store

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def accounts_root(tmp_path, monkeypatch):
    root = tmp_path / "zcode-accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    return root


def _payload(path: Path, name: str, mid: str) -> Path:
    path.write_text(json.dumps({"name": name, "device_mid": mid}), encoding="utf-8")
    return path


# ---------- M5-0：设备 ID 冲突的 CLI 契约（§15.1 硬约束 3）----------

def test_import_conflict_exits_4_and_writes_nothing(accounts_root, tmp_path, capsys, monkeypatch):
    """🔴 判据：冲突 → 退出码非 0（4）**且不写盘**，并打印 3 个显式选项、默认取消。

    上一轮只在 store 层测了 `conflict=True`，CLI 的退出码与"不写盘"没人测 ——
    判据原文是「`import` 的设备冲突返回非 0 退出码**且不写盘**」。
    """
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    _payload(tmp_path / "a.json", "acct-a", "MID-SHARED")
    assert main(["zcode", "import", str(tmp_path / "a.json")]) == 0

    _payload(tmp_path / "b.json", "acct-b", "MID-SHARED")   # 同一设备 ID
    rc = main(["zcode", "import", str(tmp_path / "b.json")])
    err = capsys.readouterr().err

    assert rc == 4, f"冲突必须返回非 0 退出码，实得 {rc}"
    assert not (accounts_root / "acct-b").exists(), "冲突时不得写盘"
    assert "设备 ID 冲突" in err
    assert "--reuse acct-a" in err and "--regenerate" in err and "取消（默认）" in err
    assert [a.name for a in store.list_accounts()] == ["acct-a"]


def test_import_conflict_with_regenerate_succeeds(accounts_root, tmp_path, capsys):
    """用户显式选 ② `--regenerate` → 放行，但设备码**必须与冲突者不同**。"""
    _payload(tmp_path / "a.json", "acct-a", "MID-SHARED")
    assert main(["zcode", "import", str(tmp_path / "a.json")]) == 0
    _payload(tmp_path / "b.json", "acct-b", "MID-SHARED")

    assert main(["zcode", "import", str(tmp_path / "b.json"), "--regenerate"]) == 0
    names = {a.name for a in store.list_accounts()}
    assert names == {"acct-a", "acct-b"}
    mids = {a.device_id for a in store.list_accounts()}
    assert len(mids) == 2, "两条账号不得共用一个设备 ID（硬约束 1）"


def test_import_reuse_shares_device_id_on_explicit_choice(accounts_root, tmp_path):
    """用户显式选 ① `--reuse <账号>` → 用**该账号**的设备 ID（文案已提示两者共享、可能风控）。

    场景要有区分度：来料自带 MID-2，但 MID-2 已被 acct-c 占用 → 冲突；
    此时 `--reuse acct-a` 必须落到 acct-a 的 MID-1（而不是来料自己的 MID-2）。
    """
    _payload(tmp_path / "a.json", "acct-a", "MID-1")
    assert main(["zcode", "import", str(tmp_path / "a.json")]) == 0
    _payload(tmp_path / "c.json", "acct-c", "MID-2")
    assert main(["zcode", "import", str(tmp_path / "c.json")]) == 0

    _payload(tmp_path / "b.json", "acct-b", "MID-2")      # 与 acct-c 撞
    assert main(["zcode", "import", str(tmp_path / "b.json")]) == 4   # 默认拒绝
    assert main(["zcode", "import", str(tmp_path / "b.json"),
                 "--reuse", "acct-a"]) == 0
    by_name = {a.name: a.device_id for a in store.list_accounts()}
    assert by_name["acct-b"] == "MID-1"
    assert by_name["acct-c"] == "MID-2"


# ---------- `mgw zcode remove`（接线 `store.delete_account`）----------

def test_remove_unknown_account_exits_2(accounts_root, capsys):
    rc = main(["zcode", "remove", "nope", "--yes"])
    assert rc == 2
    assert "不存在" in capsys.readouterr().err


def test_remove_requires_yes_in_non_interactive(accounts_root, tmp_path, capsys, monkeypatch):
    """🔴 破坏性操作：非交互环境没有 `--yes` 就**拒绝执行**（§21.3 原则 2）。"""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    _payload(tmp_path / "a.json", "acct-a", "MID-1")
    assert main(["zcode", "import", str(tmp_path / "a.json")]) == 0

    assert main(["zcode", "remove", "acct-a"]) == 2
    assert (accounts_root / "acct-a").exists(), "未确认时不得删除"
    assert "--yes" in capsys.readouterr().err


def test_remove_prints_target_then_deletes_on_yes(accounts_root, tmp_path, capsys):
    _payload(tmp_path / "a.json", "acct-a", "MID-1")
    assert main(["zcode", "import", str(tmp_path / "a.json")]) == 0

    rc = main(["zcode", "remove", "acct-a", "--yes"])
    out = capsys.readouterr().out
    assert rc == 0
    assert str(accounts_root / "acct-a") in out, "必须先把要删的路径打印给用户"
    assert not (accounts_root / "acct-a").exists()


def test_remove_declined_keeps_account(accounts_root, tmp_path, capsys, monkeypatch):
    """交互回答 n → 取消且账号完好。"""
    _payload(tmp_path / "a.json", "acct-a", "MID-1")
    assert main(["zcode", "import", str(tmp_path / "a.json")]) == 0
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "n")

    assert main(["zcode", "remove", "acct-a"]) == 0
    assert (accounts_root / "acct-a").exists()
    assert "已取消" in capsys.readouterr().out


# ---------- 🔴 死代码护栏：曾无调用点的符号必须一直有调用点 ----------

#: 符号 → 允许出现调用的文件（定义文件本身不算调用点）
_WIRED_SYMBOLS = {
    "build_headers": "upstream/zcode/claim.py",
    "bench_account": "ops/builtin/zcode_claim.py",
    "apply_to_resource": "upstream/zcode/quota.py",
    "refresh_runtime_quotas": "main.py",
    "read_account_snapshot": "api/admin.py",
    "delete_account": "cli_zcode.py",
    "reserve_quota": "core/resources.py",       # 由 pick_and_acquire 内部调用
    "settle_quota": "core/scheduler.py",
    "release_quota": "core/scheduler.py",
    "servable_models": "api/openai_compat.py",
    "admin_post": "ops/builtin/zcode_claim.py",
    "degrade_effort": "core/scheduler.py",
}


def _sources() -> list[Path]:
    return [p for p in (REPO_ROOT / "model_gateway").rglob("*.py")
            if "__pycache__" not in str(p)]


@pytest.mark.parametrize("symbol", sorted(_WIRED_SYMBOLS))
def test_symbol_has_a_production_call_site(symbol):
    """判据：`model_gateway/` 内除定义处之外至少一处**真实引用**（AST，非字符串匹配）。

    用 AST 而不是 grep：docstring / 注释里提到符号名很常见，字符串匹配会把
    "只在文档里出现"误判成"已接线"—— 那正是前两轮验收都被骗过的形态。
    `def f` / `class C` 的名字在 AST 里不是 Name/Attribute 节点，
    所以定义本身天然不计入引用。
    """
    import ast

    used_in: list[str] = []
    for f in _sources():
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            name = node.id if isinstance(node, ast.Name) else (
                node.attr if isinstance(node, ast.Attribute) else None)
            if name == symbol:
                used_in.append(
                    f"{f.relative_to(REPO_ROOT / 'model_gateway').as_posix()}"
                    f":{getattr(node, 'lineno', 0)}")
                break
    assert used_in, (f"{symbol} 无生产调用点（死代码）；"
                     f"预期接线于 {_WIRED_SYMBOLS[symbol]}")


def test_removed_dead_symbols_stay_removed():
    """已按"无落点即删"清理的符号，不得悄悄长回来（长回来就必须接线）。

    🔴 扫描面裁决（2026-09-29，M6-1）：`def refresh(` 现为 tech-design §22.3 的**冻结钩子名**
    （`upstream/<product>/product.py` 的在册接口）——按全仓字面匹配会把"接口落地"误判成
    "死代码复活"。**排除面 = 单个符号**（M6-6 收窄，R4 §2.2/NB-1）：只在
    `upstream/*/product.py` 里放行 `def refresh(` 这一处形态；
    其余 5 个死符号在**任何**文件（含 `upstream/*/product.py`）复活都必须红。
    修前排除的是**整个文件**：往 `qoder/product.py` 种 `def oauth_refresh(` 不红（实测 R4 E3a）。
    """
    product_py = {p for p in _sources()
                  if p.name == "product.py" and p.parent.parent.name == "upstream"}
    for gone in ("def degradation_chain(", "def classify_status(",
                 "def classify_http_error(", "def is_retryable(",
                 "def oauth_refresh("):
        for p in _sources():
            assert gone not in p.read_text(encoding="utf-8"), \
                f"死代码复活：{gone}（{p.relative_to(REPO_ROOT)}）"
    for p in _sources():
        if p in product_py:
            continue                     # §22.3 冻结钩子名：产品契约表里的 `def refresh(` 是接口
        assert "def refresh(" not in p.read_text(encoding="utf-8"), \
            f"死代码复活：def refresh(（{p.relative_to(REPO_ROOT)}）"


# ---------- IX-2：熔断中的 CLI 结论（不得打印"全部正常"、退出码不得为 0）----------

def _account_with_credentials(root: Path, name: str) -> None:
    """造一个**能通过凭据解析**的账号，让流程真的走到熔断闸门（而不是先撞"凭据缺失"）。"""
    from model_gateway.upstream.zcode.dataroot import v2_dir_of

    (root / name).mkdir(parents=True, exist_ok=True)
    (root / name / "meta.json").write_text(json.dumps({"device_mid": f"mid-{name}"}),
                                           encoding="utf-8")
    v2 = v2_dir_of(root, name)
    v2.mkdir(parents=True, exist_ok=True)
    (v2 / "credentials.json").write_text(json.dumps({
        "oauth:active_provider": "zai", "zcodejwttoken": f"jwt-{name}"}), encoding="utf-8")


def _last_ops_record() -> dict:
    """取本轮落盘的最后一行 ops-results，**按 JSON 结构**返回。

    🔴 不许用 `"failed" in body` 这种子串判据：`failed` 是恒存在的键（空数组也算），
    把分类从 failed 改回 inactive 后，`"failed"` 和详情文本都还在串里 —— 实测这样
    写的判据对着被改坏的源码一路绿灯。红点数的是 `failed` **数组里的账号**。
    """
    from model_gateway.core import paths

    files = sorted((paths.data_dir() / "usage").glob("ops-results-*.jsonl"))
    assert files, "这一轮没落盘 → 红点与历史都查不到"
    lines = [x for x in files[-1].read_text(encoding="utf-8").splitlines() if x.strip()]
    assert lines, "落盘文件是空的"
    return json.loads(lines[-1])


def test_claim_under_global_breaker_exits_3(accounts_root, capsys):
    """🔴 熔断开局：本轮一次上游都没打 → 必须说清"被什么挡住、还剩多久"，且**不是 0**。

    上一版这里打印 `– 跳过 2 个（无资格 2）` + `全部正常，无需处理` + 退出码 0 ——
    把"被风控挡住"说成"一切都好"（§16.2 原则 3：正常业务态与需关注必须分开）。
    """
    from model_gateway.upstream.zcode import quota as zq

    _account_with_credentials(accounts_root, "acct-a")
    _account_with_credentials(accounts_root, "acct-b")
    zq.get_circuit().enter("ZCode 风控熔断（30min，全局）")

    rc = main(["zcode", "claim"])
    out = capsys.readouterr().out

    assert rc == 3, f"熔断中不得返回 0/1，实得 {rc}"
    assert "全部正常" not in out, out
    assert "未对上游发起任何领取" in out, out
    assert "至 " in out, "必须给出恢复时刻（§17 文案）"
    assert str(zq.circuit_path()) in out, "要给出状态文件，用户才有可操作的出口"
    # 🔴 落盘的那一行必须事后分辨得出"被熔断拦住、根本没试"（面板 S-17：
    # 红点/CLI 都把用户指到 ops-results-*.jsonl，那里原先只有账号名）
    rec = _last_ops_record()
    # 🔴 口径分档（第十二轮 PM B-12-4 的另一半）：**读得动**的熔断是正常业务态，
    #    落 `inactive` 且**不点红点** —— 红点只数 `failed`，把"上游没风控、只是到点
    #    自己回池"染成需关注，等于让用户每次熔断都去查一遍。两头都要钉：
    #    钉错方向就变成"永远断言 failed"的空过红（见下一条用例的正向）。
    assert rec["inactive"] == ["acct-a", "acct-b"], rec
    assert rec["failed"] == [], "可信熔断轮不得点红点（红点专用于需要动手的档）"
    # 落盘行要事后分辨得出"被熔断拦住、根本没试"，不能只剩账号名（面板 S-17）
    reasons = json.dumps(rec["inactive_reasons"], ensure_ascii=False)
    assert "熔断" in reasons and "剩余约" in reasons, rec
    # 🔴 出口的**作用域**必须写清楚（面板 S1：旧文案"删除即解除"过度承诺）
    assert "删除该文件可立即放开后续领取" in out, out
    assert "已冷却的资源按其剩余时间自行回池" in out, out


def test_claim_with_unreadable_state_file_promises_no_auto_recovery(accounts_root, capsys):
    """🔴 第十二轮 PM B-12-3 + eng-A BLK-A：未知档没有"点"可到，CLI 不许再许诺自动恢复。

    上一版第二行固定打印「到点自动恢复」，与上一行的"读不动 → 按熔断拒跑"自相矛盾 ——
    用户会站着等，而实际上不删文件永远不会放开。载荷用**数字串**时间戳：
    这一条同时端到端验 S-55（字符串形态必须按读不动处理，而不是被 `float()` 收编后放行）。
    """
    from model_gateway.upstream.zcode import quota as zq

    _account_with_credentials(accounts_root, "acct-a")
    path = zq.circuit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"until_ms": "1770000000000", "reason": "覆盖"}', encoding="utf-8")

    rc = main(["zcode", "claim"])
    out = capsys.readouterr().out
    assert rc == 3, f"状态读不动必须整轮拒跑（rc=3），实得 {rc}"
    assert "读不动" in out, out
    assert "不会自动恢复" in out, out
    assert "到点自动恢复" not in out, "未知档许诺自动恢复 = 空头承诺"
    assert str(path) in out, "必须给出可执行的手动出口（删哪个文件）"
    assert "全部正常" not in out, out
    # 🔴 第十二轮 PM B-12-4 的正面：**未知档必须点亮顶栏红点**。
    #    红点只数 `failed` 数组里的账号（`admin.py` + `runner.py`），这一档原先记
    #    inactive = "整轮拒跑了但没有任何人知道"；原因在用户侧（状态文件读不动），
    #    不删文件永远不会放开 → 属于"需要动手"，必须进 failed 且写明未发起。
    rec = _last_ops_record()
    assert [x["account"] for x in rec["failed"]] == ["acct-a"], \
        f"未知拒跑必须进 failed 数组（红点只数它）：{rec}"
    reasons = json.dumps([x["reason"] for x in rec["failed"]], ensure_ascii=False)
    assert "未发起" in reasons and "读不动" in reasons, rec
    assert rec["inactive"] == [], "未知档被聚合成 inactive = 红点不亮（S-4 同族）"


def test_claim_without_breaker_prints_no_circuit_warning(accounts_root, monkeypatch, capsys):
    """🔴 正向对照：没熔断时**不得**出现熔断块（否则上一条用例是空过）。

    凭据齐但无任何可领活动 → 走真实 `run_once`；把上游三段式换成"无可领取活动"，
    不碰网络。
    """
    from model_gateway.ops.builtin import zcode_claim
    from model_gateway.upstream.zcode import quota as zq

    _account_with_credentials(accounts_root, "acct-a")
    assert not zq.get_circuit().active()

    class _NoPlan:
        async def preview(self):
            return None

        async def aclose(self):
            pass

    monkeypatch.setattr(zcode_claim, "_build_client", lambda *a, **k: _NoPlan())
    rc = main(["zcode", "claim"])
    out = capsys.readouterr().out

    assert rc == 0, out
    assert "未对上游发起任何领取" not in out, out
    assert "全部正常" in out, out


# ---------- S-5：红点的"确认"必须只吃掉**用户真看过**的失败（面板 M-3 / M-4）----------

def _record_acks(monkeypatch) -> list[str]:
    import model_gateway.core.local_admin as local_admin

    calls: list[str] = []
    monkeypatch.setattr(local_admin, "admin_post",
                        lambda path, **kw: calls.append(path) or {"ok": True})
    return calls


def test_clean_round_does_not_ack(accounts_root, monkeypatch, capsys):
    """🔴 本轮无失败 → **不得**清零：cron 里用户没看过的失败会被一次空跑抹掉。"""
    from model_gateway.ops.builtin import zcode_claim
    from model_gateway.upstream.zcode import quota as zq

    _account_with_credentials(accounts_root, "acct-a")
    assert not zq.get_circuit().active()

    class _NoPlan:
        async def preview(self):
            return None

        async def aclose(self):
            pass

    monkeypatch.setattr(zcode_claim, "_build_client", lambda *a, **k: _NoPlan())
    acks = _record_acks(monkeypatch)
    rc = main(["zcode", "claim"])
    out = capsys.readouterr().out

    assert rc == 0, out
    assert acks == [], f"无失败的轮次不该替用户确认失败：{acks}"


def test_breaker_round_does_not_ack(accounts_root, monkeypatch, capsys):
    """🔴 熔断空跑（一次上游都没打）更不得清零 —— 面板实测未读 7 → 0 就是这么来的。"""
    from model_gateway.upstream.zcode import quota as zq

    _account_with_credentials(accounts_root, "acct-a")
    _account_with_credentials(accounts_root, "acct-b")
    zq.get_circuit().enter("ZCode 风控熔断（30min，全局）")
    acks = _record_acks(monkeypatch)

    rc = main(["zcode", "claim"])
    out = capsys.readouterr().out

    assert rc == 3, out
    assert acks == [], f"熔断轮清了零 = 把用户没看过的失败一起抹掉：{acks}"
    assert "未对上游发起任何领取" in out


def test_failure_round_acks_once_and_lands_in_the_pointer_file(
        accounts_root, monkeypatch, capsys):
    """🔴 有失败时：打印明细 → 清零（用户确实看过了）→ 且**必须落盘**到红点指的那个文件。"""
    from model_gateway.core import paths
    from model_gateway.ops.builtin import zcode_claim
    from model_gateway.upstream.zcode import claim as claim_mod

    _account_with_credentials(accounts_root, "acct-a")

    class _Boom:
        async def preview(self):
            raise OSError("connection reset")

        async def aclose(self):
            pass

    monkeypatch.setattr(zcode_claim, "_build_client", lambda *a, **k: _Boom())
    acks = _record_acks(monkeypatch)
    rc = main(["zcode", "claim"])
    out = capsys.readouterr().out

    assert rc == 1, out
    assert acks == ["/admin/api/ops/ack"], acks
    assert "失败 1 个" in out and "逐条明细已落盘" in out, out
    # 指路文案与真实落点必须一致（面板 M-4：红点指向的 jsonl 原先只有 cron 写）
    usage = paths.data_dir() / "usage"
    files = sorted(usage.glob("ops-results-*.jsonl"))
    assert files, f"CLI 腿没落盘，红点指路的文件里不会有它的失败：{usage}"
    text = files[-1].read_text(encoding="utf-8")
    assert '"failed"' in text and "connection reset" in text, text


# ---------- S-8：退出码优先级、归因文案与退出码文档 ----------

def test_breaker_wins_over_a_credential_failure_in_exit_code(
        accounts_root, monkeypatch, capsys):
    """🔴 熔断 + 同屏"未发起即失败"（缺凭据）→ 退出码必须是 3，不是 1。

    面板实测：原先 `✗ 失败 1 个：凭据缺失` 把 3 吞成 1，脚本据此判断
    "这轮真跑了但有错" —— 而真相是一次上游都没打。
    """
    from model_gateway.upstream.zcode import quota as zq

    _account_with_credentials(accounts_root, "acct-ok")
    # 有账号目录（meta.json）但没有凭据 → 未发起即失败
    (accounts_root / "acct-nojwt").mkdir(parents=True, exist_ok=True)
    (accounts_root / "acct-nojwt" / "meta.json").write_text('{"device_mid":"m2"}',
                                                            encoding="utf-8")
    zq.get_circuit().enter("ZCode 风控熔断（30min，全局）")
    _record_acks(monkeypatch)

    rc = main(["zcode", "claim"])
    out = capsys.readouterr().out

    assert rc == 3, f"熔断必须优先于失败：{out}"
    assert "失败 1 个" in out and "凭据缺失" in out, out
    assert "未对上游发起任何领取" in out, out
    # 归因文案：熔断轮的 inactive 不得被说成"无资格"
    assert "被熔断拦住" in out, out
    assert "无资格" not in out, out


def test_non_breaker_round_still_labels_inactive_as_unqualified(
        accounts_root, monkeypatch, capsys):
    """🔴 正向对照：没熔断时走"无需动作"口径且不带熔断字样（否则上一条换成常量也能过）。"""
    from model_gateway.ops.builtin import zcode_claim
    from model_gateway.upstream.zcode import quota as zq

    _account_with_credentials(accounts_root, "acct-ok")
    assert not zq.get_circuit().active()

    class _NoPlan:
        async def preview(self):
            return None

        async def aclose(self):
            pass

    monkeypatch.setattr(zcode_claim, "_build_client", lambda *a, **k: _NoPlan())
    rc = main(["zcode", "claim"])
    out = capsys.readouterr().out

    assert rc == 0, out
    assert "无需动作" in out and "被熔断拦住" not in out, out


def test_claim_help_documents_all_four_exit_codes(capsys):
    """退出码 0/1/2/3 必须在 `--help` 里查得到（面板 S-8：原先只活在源码注释里）。"""
    with pytest.raises(SystemExit) as e:
        main(["zcode", "claim", "--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    for token in ("0 = 全部正常", "1 = 有失败", "2 = 无账号参与", "3 ="):
        assert token in out, f"退出码表缺 {token}：\n{out}"
    assert "同码不同义" in out, "3 与 setup 的写盘失败同码，必须在文案里点明"


def test_breaker_tripped_during_this_round_is_reported(accounts_root, monkeypatch, capsys):
    """🔴 熔断是**本轮里**建立的（开局没熔）→ 也必须给出提示（面板 ix-M-1）。

    上一版只在开局判 `active()`，于是"正是这一轮把风控打出来"的情况反而一个字都不提，
    用户看到 `✗ 失败 …3012` 却不知道后面 30 分钟所有账号都会被挡住。
    """
    from model_gateway.ops.builtin import zcode_claim
    from model_gateway.upstream.zcode import claim as claim_mod
    from model_gateway.upstream.zcode import quota as zq

    _account_with_credentials(accounts_root, "acct-a")
    assert not zq.get_circuit().active()

    class _Risk:
        async def preview(self):
            return _Planish()

        async def claim(self, plan_id, *, manual=False):
            return claim_mod.ClaimOutcome(code=zq.CODE_RISK_CONTROL,
                                          message="unusual activity")

        async def report_activation(self, *, user_id=""):
            return []

        async def aclose(self):
            pass

    class _Planish:
        plan_id = "p1"

    monkeypatch.setattr(zcode_claim, "_build_client", lambda *a, **k: _Risk())
    monkeypatch.setattr(zcode_claim, "_handle_risk_control",
                        lambda runtime, account: zq.get_circuit().enter(
                            "ZCode 风控熔断（30min，全局）"))
    _record_acks(monkeypatch)

    rc = main(["zcode", "claim"])
    out = capsys.readouterr().out

    assert rc == 1, out                       # 本轮确有失败 → 1（但必须说出熔断）
    assert "本轮命中风控，已建立全局熔断" in out, out
    assert "至 " in out, out
    assert str(zq.circuit_path()) in out, out


def test_write_report_failure_is_logged_not_swallowed(tmp_path, caplog):
    """🔴 落盘失败必须留痕（验收 S-26④）：原先 `except OSError: return None` 一声不响。

    顶栏红点的未读数**以这份文件为唯一事实源**（S-5 裁决）—— 写不进去就等于
    这一轮的失败对用户彻底不存在，比"没跑"更难查。
    """
    import logging
    import os

    from model_gateway.ops.base import OpReport, OpResult
    from model_gateway.ops.runner import write_report

    base = tmp_path / "usage"
    base.mkdir()
    os.chmod(base, 0o500)
    try:
        rep = OpReport()
        rep.add(OpResult("acct-a", "failed", "上游 500"))
        with caplog.at_level(logging.ERROR, logger="model_gateway.ops"):
            assert write_report(rep, base) is None
        assert any("落盘失败" in r.getMessage() for r in caplog.records), [
            r.getMessage() for r in caplog.records]
    finally:
        os.chmod(base, 0o700)
    # 正向对照：目录恢复可写就真落盘，且不再报错
    caplog.clear()
    rep2 = OpReport()
    rep2.add(OpResult("acct-a", "failed", "上游 500"))
    with caplog.at_level(logging.ERROR, logger="model_gateway.ops"):
        assert write_report(rep2, base) is not None
    assert not [r for r in caplog.records if "落盘失败" in r.getMessage()]


def test_claim_says_out_loud_when_the_round_was_not_persisted(accounts_root, monkeypatch,
                                                              capsys):
    """🔴 落不了盘时 CLI 当场改口，不许继续把用户指到一个没有内容的文件（S-26④）。"""
    import model_gateway.ops.runner as runner_mod

    _account_with_credentials(accounts_root, "acct-a")

    async def fake_run_once(**_kw):
        from model_gateway.ops.base import OpReport, OpResult
        rep = OpReport()
        rep.add(OpResult("acct-a", "failed", "上游 500"))
        return rep

    monkeypatch.setattr(runner_mod, "run_once", fake_run_once)
    monkeypatch.setattr(runner_mod, "write_report", lambda *a, **k: None)
    rc = main(["zcode", "claim"])
    err = capsys.readouterr().err
    assert rc == 1, rc
    assert "未能写入" in err, err
    assert "顶栏红点" in err, err


def test_claim_head_separates_refused_from_attempted_failures(accounts_root, monkeypatch,
                                                              capsys):
    """🔴 「✗ 失败 N 个」必须区分"未发起（拒跑）"与"发起了但失败"（第八轮 ix-8）。

    只写"失败 3 个"会让人以为三次领取都打了上游只是没成，处置方向完全不同
    （查数据目录权限 vs 查凭据/额度）。
    """
    import model_gateway.ops.runner as runner_mod
    from model_gateway.ops.base import OpReport, OpResult

    _account_with_credentials(accounts_root, "acct-a")

    async def fake_run_once(**_kw):
        rep = OpReport()
        rep.add(OpResult("acct-a", "failed", "上游 500：服务端错误"))
        rep.add(OpResult("acct-b", "failed",
                         f"{runner_mod.LOCK_REFUSAL_PREFIX}在本轮中途不可写：/x —— 未发起操作"))
        return rep

    monkeypatch.setattr(runner_mod, "run_once", fake_run_once)
    monkeypatch.setattr(runner_mod, "write_report", lambda *a, **k: None)
    rc = main(["zcode", "claim"])
    out = capsys.readouterr().out
    assert rc == 1, rc
    assert "未发起" in out and "1 个" in out, out
