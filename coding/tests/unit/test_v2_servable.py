"""v2.0 §12.1 可服务判定单元测试（BUG-1 修正的判据本体）。

`servable_models()` 是**唯一判据源**：`/v1/models`（路径 B）与 `mgw setup`（路径 A）
共用它 —— 两条下发路径必须同一口径，否则只读文件的工具仍会拿到必然失败的模型。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from model_gateway.cli_setup import build_cli_models
from model_gateway.config.schemas import AppConfig
from model_gateway.core.dialects import DialectTable
from model_gateway.core.resources import servable_models
from model_gateway.enums.matcher import load_enum_pool


def make_config(*, resources: list[dict], models: list[dict]) -> AppConfig:
    return AppConfig.model_validate({"resources": resources, "models": models})


RES = [{"id": "res-a", "name": "资源A", "base_url": "http://127.0.0.1:9/v1",
        "api_key": "sk-a"},
       {"id": "res-b", "name": "资源B", "base_url": "http://127.0.0.1:9/v1",
        "api_key": "sk-b"}]


def ref(rid="res-a", vm="vm-a", **over):
    return {"resource": rid, "model": vm, **over}


# ---------- 判据本体 ----------

def test_model_with_empty_resources_is_not_servable():
    cfg = make_config(resources=RES, models=[
        {"name": "m1", "endpoint": "chat", "resources": []}])
    assert servable_models(cfg) == set()


def test_model_with_enabled_resource_is_servable():
    cfg = make_config(resources=RES, models=[
        {"name": "m1", "endpoint": "chat", "resources": [ref("res-a", "vm-a")]}])
    assert servable_models(cfg) == {"m1"}


def test_model_whose_resources_are_all_disabled_is_not_servable():
    """🔴 BUG-1 本体：资源存在但全部停用 → 调用必返 NO_RESOURCE，不得对外声明。"""
    disabled = [dict(r, enabled=False) for r in RES]
    cfg = make_config(resources=disabled, models=[
        {"name": "m1", "endpoint": "chat",
         "resources": [ref("res-a", "vm-a"), ref("res-b", "vm-b")]}])
    assert servable_models(cfg) == set()


def test_one_live_resource_is_enough():
    mixed = [dict(RES[0], enabled=False), RES[1]]
    cfg = make_config(resources=mixed, models=[
        {"name": "m1", "endpoint": "chat",
         "resources": [ref("res-a", "vm-a"), ref("res-b", "vm-b")]}])
    assert servable_models(cfg) == {"m1"}


def test_disabled_model_excluded_even_with_live_resource():
    cfg = make_config(resources=RES, models=[
        {"name": "m1", "endpoint": "chat", "enabled": False,
         "resources": [ref("res-a", "vm-a")]}])
    assert servable_models(cfg) == set()


def test_dangling_resource_reference_is_rejected_upstream():
    """映射指向不存在的资源 id → **配置校验阶段**就拒绝（到不了判据层）。

    保留这条用例是为了钉住边界：`servable_models` 不需要为悬空引用兜底，
    因为 `AppConfig` 的交叉校验已经拦下（改坏这层校验会在这里红）。
    """
    import pytest

    with pytest.raises(ValidationError):
        make_config(resources=RES, models=[
            {"name": "m1", "endpoint": "chat", "resources": [ref("res-zzz", "vm-z")]}])


# ---------- 运行态（registry）维度 ----------

class _State:
    """`ResourceState` 替身：判据只读 `status`。"""

    def __init__(self, status: str):
        self.status = status


def test_registry_invalid_status_hides_model():
    cfg = make_config(resources=RES, models=[
        {"name": "m1", "endpoint": "chat", "resources": [ref("res-a", "vm-a")]}])
    registry = {("res-a", "vm-a"): _State("invalid")}
    assert servable_models(cfg, registry) == set()


def test_registry_disabled_status_hides_model():
    cfg = make_config(resources=RES, models=[
        {"name": "m1", "endpoint": "chat", "resources": [ref("res-a", "vm-a")]}])
    assert servable_models(cfg, {("res-a", "vm-a"): _State("disabled")}) == set()


def test_cooldown_does_not_hide_model():
    """冷却是临时态 —— 隐藏会让模型在工具里凭空消失，判据**只**看停用/失效。"""
    cfg = make_config(resources=RES, models=[
        {"name": "m1", "endpoint": "chat", "resources": [ref("res-a", "vm-a")]}])
    assert servable_models(cfg, {("res-a", "vm-a"): _State("cooldown")}) == {"m1"}


def test_second_healthy_resource_rescues_model():
    cfg = make_config(resources=RES, models=[
        {"name": "m1", "endpoint": "chat",
         "resources": [ref("res-a", "vm-a"), ref("res-b", "vm-b")]}])
    registry = {("res-a", "vm-a"): _State("invalid"), ("res-b", "vm-b"): _State("active")}
    assert servable_models(cfg, registry) == {"m1"}


# ---------- 路径 A（mgw setup 写文件）同判据 ----------

def test_setup_path_skips_unservable_models(tmp_path: Path):
    """🔴 只读文件的工具走路径 A：`models.json` 也必须守同一判据。"""
    cfg = make_config(resources=[dict(RES[0], enabled=False), RES[1]], models=[
        {"name": "alive", "endpoint": "chat", "resources": [ref("res-b", "vm-b")]},
        {"name": "dead", "endpoint": "chat", "resources": [ref("res-a", "vm-a")]},
    ])
    models = build_cli_models(cfg, load_enum_pool(tmp_path / "none.yaml"),
                              DialectTable.load(tmp_path / "d.json"),
                              "http://127.0.0.1:8300/v1", "sk-token")
    ids = [m["id"] for m in models]
    assert ids == ["custom-local:alive"], "不可服务模型不得写入 models.json"
    assert not any("dead" in str(m) for m in models)


# ---------- 路径与配置来源（§16.4 跨进程互斥 / §17 熔断落盘的成立前提，验收 M-4）----------

def test_ops_lock_dir_ignores_cwd(tmp_path):
    """🔴 cron（repo cwd）与 CLI（任意 cwd）必须解析出**同一把**锁目录。

    用子进程换 cwd 真实验证：`ops_lock_dir()` 一旦回到 `Path("data")/...`，
    两个进程就会各用一把锁，§16.4 的双层互斥静默失效。
    """
    import subprocess
    import sys
    from pathlib import Path as _P

    code = ("from model_gateway.ops.runner import ops_lock_dir; print(ops_lock_dir())")
    repo = _P(__file__).resolve().parents[2]

    def run_from(cwd):
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
        out = subprocess.run([sys.executable, "-c", code], cwd=str(cwd), env=env,
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()

    a = run_from(repo)
    b = run_from(tmp_path)
    assert a == b, f"锁目录随 cwd 漂移：{a} != {b}"
    assert _P(a).is_absolute() and a.endswith("ops-locks")
    assert _P(repo) in _P(a).parents or _P(a) == _P(tmp_path), a


def test_ops_lock_dir_follows_mg_config(tmp_path, monkeypatch):
    """`MG_CONFIG` 决定数据目录：配置放哪，锁/事件/熔断就落哪（隔离与一致性都要成立）。"""
    from model_gateway.ops.runner import ops_lock_dir

    cfg = tmp_path / "elsewhere" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("MGW_OPS_LOCK_DIR", raising=False)
    monkeypatch.setenv("MG_CONFIG", str(cfg))
    assert ops_lock_dir() == (tmp_path / "elsewhere" / "ops-locks").resolve()


def test_admin_post_targets_mg_config_port(monkeypatch, tmp_path):
    """CLI 跨进程出口必须打到 `MG_CONFIG` 里那个端口（否则熔断回写打到别的实例）。"""
    import model_gateway.core.local_admin as la

    cfg = tmp_path / "config.yaml"
    cfg.write_text("gateway:\n  port: 9999\n  access_tokens: []\nresources: []\nmodels: []\n",
                   encoding="utf-8")
    monkeypatch.setenv("MG_CONFIG", str(cfg))
    seen: list[str] = []

    class _Resp:
        def read(self):
            return b'{"ok": true}'

    def fake_req(url, **kw):
        seen.append(url)
        return url

    monkeypatch.setattr(la.urllib.request, "Request", fake_req)
    monkeypatch.setattr(la.urllib.request, "urlopen", lambda req, timeout=None: _Resp())
    assert la.admin_post("/admin/api/zcode/bench") == {"ok": True}
    assert ":9999/admin/api/zcode/bench" in seen[0], seen


# ---------- S-4：资源行聚合与到期归位（面板 ix S-2 / PM M-4）----------

def _mgr_two_entries():
    """一个资源两条映射（不同厂商模型），便于构造"一条判死一条正常"的混合态。"""
    from model_gateway.core.resources import ResourceManager

    cfg = make_config(resources=[{"id": "res-a", "name": "资源A", "access_mode": "api",
                                  "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-a"}],
                     models=[{"name": "m", "endpoint": "chat", "resources": [
                         ref("res-a", "vm-a"), ref("res-a", "vm-b")]}])
    mgr = ResourceManager()
    mgr.rebuild(cfg)
    return cfg, mgr


def row_of(cfg, mgr, rid="res-a"):
    return next(r for r in mgr.snapshot_by_resource(cfg) if r["rid"] == rid)


def test_single_disabled_entry_is_not_reported_as_cooldown():
    """🔴 401 判死的条目**不得**被折成 `cooldown`。

    原口径"全部非 active 即 cooldown"让徽章渲染出 `b-cool title="剩余 0s"`、
    「冷却剩余」列显示 `—`，而同页横幅写着"凭据失效" —— 同一屏互相打脸（面板实测）。
    """
    cfg, mgr = _mgr_two_entries()
    a = mgr.registry[("res-a", "vm-a")]
    b = mgr.registry[("res-a", "vm-b")]
    mgr.disable(a)
    mgr.disable(b)
    a.last_error = "上游返回 401：invalid_api_key"

    row = row_of(cfg, mgr)
    assert row["status"] == "disabled", row
    assert row["available"] is False
    assert row["cooldown_remaining_ms"] == 0
    assert row["last_error"] == "上游返回 401：invalid_api_key"


def test_invalid_outranks_cooldown_in_the_aggregate():
    """判死（不会自愈）比暂时冷却（会自愈）更该被用户看到 —— 聚合与取原因共用一把尺。"""
    from model_gateway.core.resources import _SEVERITY, _rendered_last_error

    assert _SEVERITY["disabled"] > _SEVERITY["cooldown"], "判死被排到冷却之后即为口径错"
    cfg, mgr = _mgr_two_entries()
    a, b = mgr.registry[("res-a", "vm-a")], mgr.registry[("res-a", "vm-b")]
    mgr.bench(a, 600.0)
    a.last_error = "上游限流，冷却中"
    mgr.invalidate(b)
    b.last_error = "上游返回 404：model_not_found"
    assert row_of(cfg, mgr)["status"] == "invalid"
    # 判死的条目不是 cooldown → 「最近错误」只留原因，不配恢复钟点（验收 S-23）
    assert _rendered_last_error([a, b], "invalid", 0) == "上游返回 404：model_not_found"


def test_one_healthy_entry_keeps_the_resource_servable_and_advertised():
    """🔴 正向对照：两条映射里有一条 active → 资源仍是 active，模型不下发丢失。"""
    cfg, mgr = _mgr_two_entries()
    mgr.invalidate(mgr.registry[("res-a", "vm-b")])
    row = row_of(cfg, mgr)
    assert row["status"] == "active" and row["available"] is True
    assert servable_models(cfg, mgr.registry) == {"m"}


def test_expired_cooldown_reads_as_available_without_traffic():
    """到期即归位：没有请求经过时，快照也不得继续报"冷却中 + 旧原因"（PM M-4）。"""
    t = [1000.0]
    from model_gateway.core.resources import ResourceManager

    cfg = make_config(resources=[{"id": "res-a", "name": "资源A", "access_mode": "api",
                                  "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-a"}],
                     models=[{"name": "m", "endpoint": "chat",
                              "resources": [ref("res-a", "vm-a")]}])
    mgr = ResourceManager(clock=lambda: t[0])
    mgr.rebuild(cfg)
    st = mgr.registry[("res-a", "vm-a")]
    mgr.bench(st, 60.0)
    st.last_error = "ZCode 额度耗尽"
    assert row_of(cfg, mgr)["status"] == "cooldown"       # 未到期：如实报冷却

    t[0] += 61.0                                          # 冷却到期，且**零流量**
    row = row_of(cfg, mgr)
    assert row["status"] == "active" and row["available"] is True, row
    # 🔴 语义定稿（验收 S-15 的裁决，含对上一版的**反转**）：归位**不清** `last_error`。
    # 这一列的语义是「最近错误」（历史），"现在能不能用"由 status 与「冷却剩余」表达；
    # 清了之后用户在冷却结束就再也查不到"刚才为什么不可用"（面板 ix §4-4）。
    assert row["last_error"] == "ZCode 额度耗尽", row
    assert st.status == "active"


def test_reconcile_returns_the_number_of_recovered_entries():
    """返回值可断言（不是"顺手改一下"），也便于日志留痕。"""
    t = [1000.0]
    from model_gateway.core.resources import ResourceManager

    cfg = make_config(resources=[{"id": "res-a", "name": "资源A", "access_mode": "api",
                                  "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-a"}],
                     models=[{"name": "m", "endpoint": "chat", "resources": [
                         ref("res-a", "vm-a"), ref("res-a", "vm-b")]}])
    mgr = ResourceManager(clock=lambda: t[0])
    mgr.rebuild(cfg)
    a, b = mgr.registry[("res-a", "vm-a")], mgr.registry[("res-a", "vm-b")]
    mgr.bench(a, 10.0)
    mgr.bench(b, 600.0)
    t[0] += 11.0
    assert mgr.reconcile_expired() == 1
    assert a.status == "active" and b.status == "cooldown"


def test_both_expiry_paths_agree_on_the_recovered_row():
    """🔴 两条到期路径必须同一语义（S-15 根因）：原先快照归位清 `last_error`、
    选路归位不清 —— 有流量的资源恢复后被永久钉在旧原因上，且两份口径互相打脸。

    判据形状：同一份"冷却到期"的状态，分别只走 **选路** 与只走 **快照** 两条路径，
    两边得到的 (status, last_error) 必须一致。
    """
    t = [1000.0]
    from model_gateway.core.resources import ResourceManager

    cfg = make_config(resources=[{"id": "res-a", "name": "资源A", "access_mode": "api",
                                  "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-a"}],
                     models=[{"name": "m", "endpoint": "chat", "resources": [
                         ref("res-a", "vm-a")]}])
    outcomes = []
    for via in ("pick", "snapshot"):
        mgr = ResourceManager(clock=lambda: t[0])
        mgr.rebuild(cfg)
        st = mgr.registry[("res-a", "vm-a")]
        mgr.bench(st, 30.0)
        st.last_error = "上游 429 限流"
        t[0] += 31.0                                  # 到期，零流量后再触碰
        if via == "pick":
            assert mgr.pick_and_acquire("m", set()) is not None
        else:
            row_of(cfg, mgr)
        outcomes.append((st.status, st.last_error))

    assert outcomes[0] == outcomes[1] == ("active", "上游 429 限流"), outcomes
