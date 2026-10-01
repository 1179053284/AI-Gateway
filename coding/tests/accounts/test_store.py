"""`accounts/store.py` 单测（tech-design v2.0 §22.2 布局/不变式 + §22.3 写回自检）。

🔴 判据逐条对应契约：
  · 原子写（tmp+rename；失败不留半截、不毁旧值）
  · 目录穿越拒绝（白名单 + 空名 + 超长名）
  · 写回自检 + **失败整体回滚**（新建删目录 / 既有写回旧内容，照抄 `22 §5.7`）
  · 凭据与运行态**分离**（runtime.json 不在凭据写入面里）
  · 导入**只读源文件**（逐字节不变，`23 B4`）
  · 导入**全部身份字段**落 meta.json 并全字段查重（任一字段相同即冲突；W2-fix 缺陷回归）
  · **跨进程写互斥**（§22.8-4 fail closed）：三条写路径持同一把落盘锁；锁被别的进程
    持有 / 锁建不起来 → 拒写且**一个字节不落**（`ops/runner.py::AccountLocks` 同款形态）
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from model_gateway.accounts import store

# ============ 助手 ============

def _seed(product: str, name: str, root, credentials: dict | None = None, meta=None) -> None:
    """用生产入口建一个账号（不绕过 store）。"""
    store.commit_login(product, name, credentials or {"token": "t-1"},
                       meta if meta is not None else {"machine_id": f"mid-{name}"}, root=root)


# ============ 原子写 ============

def test_atomic_write_leaves_no_temp_and_replaces(tmp_path):
    """原子写：落盘后目录里没有残留 `.*.tmp`；内容可读回。"""
    d = tmp_path / "w"
    store.atomic_write_json(d / "a.json", {"k": 1})
    assert json.loads((d / "a.json").read_text(encoding="utf-8")) == {"k": 1}
    assert [p.name for p in d.iterdir()] == ["a.json"]


def test_failed_atomic_write_keeps_old_content_and_cleans_temp(tmp_path, monkeypatch):
    """`os.replace` 失败 → 旧内容完好、临时文件清干净（中断不毁旧值）。"""
    d = tmp_path / "w"
    target = d / "a.json"
    store.atomic_write_json(target, {"v": "old"})
    monkeypatch.setattr(store.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        store.atomic_write_json(target, {"v": "new"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": "old"}
    assert [p.name for p in d.iterdir()] == ["a.json"], "临时文件没清掉"


# ============ 白名单 / 目录穿越 ============

def test_name_whitelist_rejects_traversal_and_overlong(tmp_path):
    """🔴 账号名白名单（§22.2）：非法名**显式拒绝**，不静默改名、不越出根目录。"""
    root = tmp_path / "accounts"
    for bad in ("../evil", "a/b", "a.b", "", "x" * 33, "  spaced  "):
        with pytest.raises(ValueError):
            store.commit_login("buddy", bad, {"t": "1"}, {}, root=root)
    assert not (tmp_path / "evil").exists()
    assert not root.exists() or list(root.iterdir()) == []


def test_sanitize_name_matches_legacy_semantics():
    """清洗语义与 zcode 既有 `_sanitize` 一致（导入路径靠它兜底，不是拒绝）。"""
    assert store.sanitize_name("../../etc/passwd") == "etcpasswd"
    assert store.sanitize_name("") == "account"
    assert store.sanitize_name("x" * 40) == "x" * 32


def test_has_account_never_escapes_root(tmp_path):
    """判存在性不得被 `../` 越出账号根（"外面有个同名目录"不算账号）。"""
    root = tmp_path / "accounts"
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "meta.json").write_text("{}", encoding="utf-8")
    assert store.has_account(root, "../elsewhere") is False
    assert store.has_account(root, "") is False


# ============ 写回自检 + 失败整体回滚 ============

def test_verify_failure_deletes_new_account_directory(tmp_path, monkeypatch):
    """🔴 新建账号：自检不过 → **删掉整个账号目录**（不留"永远切不过去"的半成品）。"""
    root = tmp_path / "accounts"
    real = store.atomic_write_json

    def lossy(path, data):
        if path.name == "credentials.json":
            data = {k: v for k, v in data.items() if k != "token"}
        return real(path, data)

    monkeypatch.setattr(store, "atomic_write_json", lossy)
    with pytest.raises(store.CommitError, match="凭据键"):
        store.commit_login("buddy", "acct-1", {"token": "secret"}, {}, root=root)
    assert not (root / "acct-1").exists()


def test_verify_failure_restores_existing_account(tmp_path, monkeypatch):
    """🔴 重登：自检不过 → **写回旧内容**（旧凭据不能被半截新值覆盖）。"""
    root = tmp_path / "accounts"
    store.commit_login("buddy", "acct-1", {"token": "old"}, {"plan": "free"}, root=root)
    cred_before = (root / "acct-1" / "credentials.json").read_bytes()
    meta_before = (root / "acct-1" / "meta.json").read_bytes()

    real = store.atomic_write_json
    monkeypatch.setattr(store, "atomic_write_json",
                        lambda p, d: real(p, {**d, "token": "TAMPERED"}
                                          if p.name == "credentials.json" else d))
    with pytest.raises(store.CommitError):
        store.commit_login("buddy", "acct-1", {"token": "new"}, {}, root=root)
    assert (root / "acct-1" / "credentials.json").read_bytes() == cred_before
    assert (root / "acct-1" / "meta.json").read_bytes() == meta_before


def test_verify_checks_meta_keys_too(tmp_path, monkeypatch):
    """自检覆盖**元信息键**（设备字段写不准 = 上游眼里"换设备"）。"""
    root = tmp_path / "accounts"
    real = store.atomic_write_json
    monkeypatch.setattr(store, "atomic_write_json",
                        lambda p, d: real(p, {k: v for k, v in d.items() if k != "machine_id"}
                                          if p.name == "meta.json" else d))
    with pytest.raises(store.CommitError, match="元信息键"):
        store.commit_login("qoder", "acct-1", {"token": "t"}, {"machine_id": "m-1"}, root=root)
    assert not (root / "acct-1").exists()


# ============ 凭据与运行态分离 ============

def test_runtime_is_written_only_by_write_runtime(tmp_path):
    """🔴 不变式④：凭据落盘**不碰** runtime.json；运行态写入**不碰**凭据/元信息。"""
    root = tmp_path / "accounts"
    _seed("buddy", "acct-1", root)
    store.write_runtime("buddy", "acct-1", {"cooldown_until": 123}, root=root)
    runtime_before = (root / "acct-1" / "runtime.json").read_bytes()
    cred_before = (root / "acct-1" / "credentials.json").read_bytes()
    meta_before = (root / "acct-1" / "meta.json").read_bytes()

    store.commit_login("buddy", "acct-1", {"token": "t-2"}, {}, root=root)
    assert (root / "acct-1" / "runtime.json").read_bytes() == runtime_before

    cred_before = (root / "acct-1" / "credentials.json").read_bytes()
    meta_before = (root / "acct-1" / "meta.json").read_bytes()
    store.write_runtime("buddy", "acct-1", {"cooldown_until": 456}, root=root)
    assert (root / "acct-1" / "credentials.json").read_bytes() == cred_before
    assert (root / "acct-1" / "meta.json").read_bytes() == meta_before
    assert store.read_runtime("buddy", "acct-1", root=root) == {"cooldown_until": 456}


def test_read_runtime_missing_is_empty_and_corrupt_fails_closed(tmp_path):
    """🔴 §22.8-5：文件不存在 = 新账号（`{}`）；**读不动 = fail closed**（抛错，不当健康）。"""
    root = tmp_path / "accounts"
    _seed("buddy", "acct-1", root)
    assert store.read_runtime("buddy", "acct-1", root=root) == {}

    (root / "acct-1" / "runtime.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(store.RuntimeUnreadable):
        store.read_runtime("buddy", "acct-1", root=root)

    (root / "acct-1" / "runtime.json").write_text("[1,2]", encoding="utf-8")
    with pytest.raises(store.RuntimeUnreadable):
        store.read_runtime("buddy", "acct-1", root=root)


def test_load_credentials_reads_back_and_merges_meta(tmp_path):
    """重登：凭据覆盖、meta 合并（旧键保留，`created_at` 不重写）。"""
    root = tmp_path / "accounts"
    _seed("buddy", "acct-1", root, {"token": "t-1"}, {"plan": "free"})
    created_at = json.loads((root / "acct-1" / "meta.json").read_text())["created_at"]

    store.commit_login("buddy", "acct-1", {"token": "t-2"}, {"plan": "pro"}, root=root)
    assert store.load_credentials("buddy", "acct-1", root=root) == {"token": "t-2"}
    meta = store.load_meta(root, "acct-1")
    assert meta["plan"] == "pro" and meta["created_at"] == created_at
    assert meta["via"] == "login" and meta["updated_at"]


# ============ 枚举 / 删除 / 根解析 ============

def test_list_accounts_criterion_and_sorted(tmp_path):
    """🔴 枚举判据 = "有 meta.json 的目录"（任意子目录不算账号，zcode 的历史教训）。"""
    root = tmp_path / "accounts"
    _seed("buddy", "b-acct", root)
    _seed("buddy", "a-acct", root)
    (root / "stray-dir").mkdir()                      # 别的模块留下的目录
    (root / "no-meta").mkdir()
    (root / "a-file").write_text("x", encoding="utf-8")
    assert store.list_accounts("buddy", root=root) == ["a-acct", "b-acct"]
    assert store.list_accounts("buddy", root=tmp_path / "missing") == []


def test_delete_account_only_removes_that_one(tmp_path):
    root = tmp_path / "accounts"
    _seed("buddy", "a", root)
    _seed("buddy", "b", root)
    assert store.delete_account("buddy", "a", root=root) is True
    assert store.delete_account("buddy", "a", root=root) is False
    assert store.list_accounts("buddy", root=root) == ["b"]


def test_product_root_env_override(tmp_path, monkeypatch):
    """账号根可被 `MGW_<PRODUCT>_ACCOUNTS` 覆盖（既有 `MGW_ZCODE_ACCOUNTS` 口径的泛化）。"""
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(tmp_path / "zc"))
    monkeypatch.setenv("MGW_BUDDY_ACCOUNTS", str(tmp_path / "bd"))
    assert store.product_root("zcode") == tmp_path / "zc"
    assert store.product_root("buddy") == tmp_path / "bd"
    monkeypatch.delenv("MGW_BUDDY_ACCOUNTS")
    assert store.product_root("buddy").name == "accounts"
    assert store.product_root("buddy").parent.name == "buddy"


# ============ 钩子 meta 通道（§22.3 补入①：`hook_meta` 唯一组装入口）============

def test_hook_meta_anchors_plus_meta_json(tmp_path):
    """`hook_meta` = 锚字段（`account`/`dir`）+ `meta.json` 铺开（钩子 `meta` 形参的唯一入口）。"""
    root = tmp_path / "accounts"
    _seed("buddy", "acct-1", root, {"token": "t-1"}, {"plan": "free"})
    meta = store.hook_meta("buddy", "acct-1", root=root)
    assert meta["account"] == "acct-1"
    assert meta["dir"] == str(root / "acct-1")
    assert meta["plan"] == "free"                      # meta.json 的普通键照原样铺开
    assert meta["via"] == "login" and meta["updated_at"]   # `commit_login` 写的元信息也在


def test_hook_meta_anchors_win_over_meta_json(tmp_path):
    """🔴 锚字段不得被 `meta.json` 覆盖：被污染/旧布局的元信息不能把钩子引到别的目录。

    （zcode 代理实测的「退化为 unknown / 续期回写静默跳过」正是这类静默失效。）
    """
    root = tmp_path / "accounts"
    _seed("buddy", "acct-1", root)
    path = root / "acct-1" / "meta.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update({"account": "evil", "dir": "/tmp/evil"})
    path.write_text(json.dumps(data), encoding="utf-8")
    meta = store.hook_meta("buddy", "acct-1", root=root)
    assert meta["account"] == "acct-1" and meta["dir"] == str(root / "acct-1")


def test_hook_meta_missing_meta_json_reads_only_and_yields_anchors(tmp_path):
    """账号还没落盘（或 `meta.json` 损坏）→ 只回锚字段；**只读**，不建目录、不改盘。"""
    root = tmp_path / "accounts"
    assert store.hook_meta("buddy", "ghost", root=root) == {
        "account": "ghost", "dir": str(root / "ghost")}
    assert not root.exists() or list(root.iterdir()) == []
    (root / "broken").mkdir(parents=True)
    (root / "broken" / "meta.json").write_text("{not json", encoding="utf-8")
    assert store.hook_meta("buddy", "broken", root=root) == {
        "account": "broken", "dir": str(root / "broken")}


def test_hook_meta_anchors_are_whitelisted(tmp_path):
    """锚字段取**白名单后**的名字（§22.2 防目录穿越）：`account` 与 `dir` 恒一致、不出根。"""
    root = tmp_path / "accounts"
    meta = store.hook_meta("buddy", "../evil", root=root)
    assert meta["dir"] == str(root / "evil") and meta["account"] == "evil"
    assert Path(meta["dir"]).parent == root


def test_hook_meta_default_root_goes_through_product_root(tmp_path, monkeypatch):
    """不给 `root` 时走 `product_root`（`MGW_<PRODUCT>_ACCOUNTS` 覆盖生效；目录为绝对路径）。"""
    monkeypatch.setenv("MGW_BUDDY_ACCOUNTS", str(tmp_path / "bd"))
    meta = store.hook_meta("buddy", "acct-1")
    assert meta["dir"] == str(tmp_path / "bd" / "acct-1")
    assert Path(meta["dir"]).is_absolute()


# ============ 导入 ============

def _write_source(tmp_path, data: dict) -> "object":
    src = tmp_path / "import.json"
    src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return src


def test_import_reads_source_file_byte_identical(tmp_path):
    """🔴 `23 B4`：导入**只读快照**，源文件逐字节不变。"""
    root = tmp_path / "accounts"
    src = _write_source(tmp_path, {"name": "acct-9", "machine_id": "mid-9", "token": "T"})
    before = src.read_bytes()
    res = store.import_account("qoder", str(src), root=root)
    assert res.ok and res.device_id == "mid-9"
    assert src.read_bytes() == before
    assert store.load_credentials("qoder", "acct-9", root=root) == {"token": "T"}


def test_import_generates_unique_device_when_absent(tmp_path):
    """硬约束 1：无设备字段的载荷 → 各分配一个**跨账号唯一**的新 ID。"""
    root = tmp_path / "accounts"
    a = store.import_account("qoder", payload={"name": "a", "token": "A"}, root=root)
    b = store.import_account("qoder", payload={"name": "b", "token": "B"}, root=root)
    assert a.ok and b.ok and a.device_id and a.device_id != b.device_id


def test_import_conflict_rejected_by_default(tmp_path):
    """🔴 硬约束 3：冲突 → **拒绝 + 交用户决策**（不写盘、报出与谁冲突）。"""
    root = tmp_path / "accounts"
    assert store.import_account("qoder", payload={"name": "owner", "machine_id": "shared"},
                                root=root).ok
    res = store.import_account("qoder", payload={"name": "other", "machine_id": "shared"},
                               root=root)
    assert res.ok is False and res.conflict is True and res.conflict_with == "owner"
    assert "未导入" in res.message
    assert not (root / "other" / "meta.json").exists()


def test_import_reuse_and_regenerate(tmp_path):
    """选项 ① 复用目标设备 ID；选项 ② 生成新 ID（各有别名语义）。"""
    root = tmp_path / "accounts"
    store.import_account("qoder", payload={"name": "owner", "machine_id": "shared"}, root=root)
    reused = store.import_account("qoder", payload={"name": "r1", "machine_id": "shared"},
                                  root=root, reuse="owner")
    assert reused.ok and reused.device_id == "shared"
    regen = store.import_account("qoder", payload={"name": "r2", "machine_id": "shared"},
                                 root=root, regenerate=True)
    assert regen.ok and regen.device_id != "shared"
    missing = store.import_account("qoder", payload={"name": "r3", "machine_id": "shared"},
                                   root=root, reuse="nope")
    assert missing.ok is False and "--reuse" in missing.message


def test_import_device_less_product_needs_no_device(tmp_path):
    """无设备身份的产品（buddy/workbuddy/cline/loomy）：导入不生成也不报冲突。"""
    root = tmp_path / "accounts"
    res = store.import_account("buddy", payload={"name": "a", "token": "A"}, root=root)
    assert res.ok and res.device_id == ""
    assert store.load_meta(root, "a")["via"] == "import"


def test_import_duplicate_name_rejected_and_wrapped_payload(tmp_path):
    """重名拒绝；载荷允许外包一层（`account`/`data`/`payload`——与参考实现同口径）。"""
    root = tmp_path / "accounts"
    assert store.import_account("buddy", payload={"name": "a"}, root=root).ok
    dup = store.import_account("buddy", payload={"name": "a"}, root=root)
    assert dup.ok is False and "已存在" in dup.message

    wrapped = tmp_path / "w.json"
    wrapped.write_text(json.dumps({"account": {"name": "wrapped", "token": "W"}}),
                       encoding="utf-8")
    got = store.import_account("buddy", str(wrapped), root=root)
    assert got.ok and got.account == "wrapped"

    assert store.import_account("buddy", None, root=root).ok is False
    bad = tmp_path / "bad.json"
    bad.write_text("[1]", encoding="utf-8")
    assert store.import_account("buddy", str(bad), root=root).ok is False


def test_import_traversal_name_is_sanitized(tmp_path):
    """导入路径的账号名走清洗（照抄 zcode 口径）：不越根、不留 `..`。"""
    root = tmp_path / "accounts"
    res = store.import_account("buddy", payload={"name": "../../etc/passwd"}, root=root)
    assert res.ok and "/" not in res.account and ".." not in res.account
    assert not (tmp_path.parent / "etc").exists()


# ============ 导入：多字段身份（W2-fix 缺陷回归）============

def _patch_two_field_registry(monkeypatch):
    """把注册表替身成「与 trae 同形」的两字段身份产品。

    不依赖真实产品 block：并行波次正在改动其他产品的注册表条目，测试桩保证本用例
    只验证**公共层**行为（`DeviceSpec.fields` 双字段：machine_id + device_id）。
    """
    from model_gateway.accounts import registry
    from model_gateway.accounts.types import Capabilities, DeviceSpec, ProductMeta

    stub = ProductMeta(id="twofield", title="Two-Field", login="device_code",
                       protocol="openai", base_url="",
                       device=DeviceSpec(fields=("machine_id", "device_id"), derive=False),
                       capabilities=Capabilities(), models_source="static")
    monkeypatch.setattr(registry, "get", lambda product: stub)


def test_import_multi_field_writes_all_identity_fields_and_dedups(tmp_path, monkeypatch):
    """🔴 W2-fix 缺陷回归：导入落**全部**身份字段，且全字段查重（任一字段相同即冲突）。

    旧实现只写 `fields[0]` + 单值比整元组查重 → 导入账号身份残缺、后一个账号查重恒通过。
    """
    _patch_two_field_registry(monkeypatch)
    root = tmp_path / "accounts"
    first = store.import_account(
        "twofield", payload={"name": "a", "machine_id": "m-1", "device_id": "d-1"}, root=root)
    assert first.ok and first.device_values == ("m-1", "d-1")
    meta = store.load_meta(root, "a")
    assert meta["machine_id"] == "m-1" and meta["device_id"] == "d-1", "全部身份字段必须落盘"
    assert store.load_credentials("twofield", "a", root=root) == {}, "身份字段不进凭据本体"

    # 同 machine_id、不同 device_id → 冲突（旧实现会静默放过）
    clash = store.import_account(
        "twofield", payload={"name": "b", "machine_id": "m-1", "device_id": "d-2"}, root=root)
    assert clash.ok is False and clash.conflict is True and clash.conflict_with == "a"
    assert not (root / "b" / "meta.json").exists()

    # 同 device_id、不同 machine_id → 冲突
    clash2 = store.import_account(
        "twofield", payload={"name": "c", "machine_id": "m-2", "device_id": "d-1"}, root=root)
    assert clash2.ok is False and clash2.conflict is True and clash2.conflict_with == "a"

    # 全异 → 通过
    fresh = store.import_account(
        "twofield", payload={"name": "d", "machine_id": "m-3", "device_id": "d-3"}, root=root)
    assert fresh.ok and fresh.device_values == ("m-3", "d-3")


def test_import_multi_field_fills_missing_field_and_participates(tmp_path, monkeypatch):
    """载荷缺一个身份字段 → 补生成并落盘（不放任身份残缺），补出的值也参与查重。"""
    _patch_two_field_registry(monkeypatch)
    root = tmp_path / "accounts"
    res = store.import_account("twofield", payload={"name": "a", "machine_id": "m-1"}, root=root)
    assert res.ok and res.device_values[0] == "m-1" and res.device_values[1]
    meta = store.load_meta(root, "a")
    assert meta["machine_id"] == "m-1" and meta["device_id"] == res.device_values[1]

    back = store.import_account(
        "twofield", payload={"name": "b", "machine_id": "m-9", "device_id": meta["device_id"]},
        root=root)
    assert back.ok is False and back.conflict is True and back.conflict_with == "a"


def test_import_multi_field_regenerate_writes_complete_identity(tmp_path, monkeypatch):
    """`--regenerate`：生成一套**完整**新身份（与冲突账号无任何字段相同）。"""
    _patch_two_field_registry(monkeypatch)
    root = tmp_path / "accounts"
    store.import_account("twofield", payload={"name": "owner", "machine_id": "m-1",
                                              "device_id": "d-1"}, root=root)
    res = store.import_account("twofield", payload={"name": "r", "machine_id": "m-1",
                                                    "device_id": "d-2"},
                               root=root, regenerate=True)
    assert res.ok and res.device_values[0] != "m-1" and res.device_values[1] != "d-1"
    meta = store.load_meta(root, "r")
    assert meta["machine_id"] == res.device_values[0]
    assert meta["device_id"] == res.device_values[1]


# ============ P-B1 回归（写回自检的比较基准）============

def test_commit_login_accepts_stale_store_managed_meta_keys(tmp_path, monkeypatch):
    """调用方带着**过期的** store 管理键（`updated_at`/`via`）再提交，不得触发写回自检。

    真机复现（Fix-4，8399 独立实例）：账号 API 的 enable/disable 对任何"隔秒后再写"的
    账号必 500「写回自检：元信息键 'updated_at' 读回不一致」——`_set_enabled` 把整份旧
    meta 交回 `commit_login`，而 store 会覆写 `updated_at`；同秒内侥幸相等，M6-4a 的
    用例因此漏网。判据 = 比较基准必须是**真正要写的内容**（`merged`）。
    """
    root = tmp_path / "r"
    store.commit_login("buddy", "acc-1", {"token": "t"}, {"machine_id": "m-1"}, root=root)
    stale = store.load_meta(root, "acc-1")            # 含 store 写过的 updated_at / via
    assert "updated_at" in stale and "via" in stale
    monkeypatch.setattr(store, "_now", lambda: "2099-01-01T00:00:00")
    store.commit_login("buddy", "acc-1", {"token": "t"},
                       {**stale, "enabled": False}, root=root)
    meta = store.load_meta(root, "acc-1")
    assert meta["enabled"] is False
    assert meta["updated_at"] == "2099-01-01T00:00:00"   # store 管理键被刷新（非照抄旧值）


# ============ 跨进程写互斥（§22.8-4 fail closed；F5 修复）============

#: 第二进程脚本：父进程持锁期间尝试写**同一账号**。判据 = 被拒（退出码 3 + 可读原因）；
#: 无锁时会写成功（退出码 0）→ 父进程随后的写/自检观测到丢更新 → 用例红。
_SECOND_PROCESS = """
import sys
from model_gateway.accounts import store

store._LOCK_WAIT_S = 0.05          # 父进程正持有 → 快速走完等待预算后被拒
try:
    store.commit_login("buddy", "acct-1", {"token": "CHILD"}, {"from": "CHILD"})
except store.WriteLockError as e:
    print("REFUSED:" + str(e))
    sys.exit(3)
print("WROTE")
"""


def _lock_dir(tmp_path, monkeypatch) -> Path:
    """把锁目录指到 tmp（`MGW_ACCOUNTS_LOCK_DIR`；缺省是 `data/locks`，不许污染）。"""
    directory = tmp_path / "locks"
    monkeypatch.setenv(store.ACCOUNTS_LOCK_DIR_ENV, str(directory))
    return directory


def _foreign_lock(lock_dir: Path, pid: int = 1) -> Path:
    """伪造"另一个进程持有锁"：锁文件写 `<pid> <token>`。

    `pid=1`（launchd/init）恒存活 → 命中"别人确实还在持有"分支
    （`ops/runner.py::AccountLocks._try_create` 的同款口径；非 root 下 `os.kill(1, 0)`
    抛 PermissionError → 判活）。
    """
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / store.ACCOUNTS_LOCK_NAME
    path.write_text(f"{pid} {'f' * 16}", encoding="utf-8")
    return path


def test_write_is_refused_while_another_process_holds_the_lock(tmp_path, monkeypatch):
    """🔴 §22.8-4 fail closed：锁被别的进程持有时，三条写路径一律**拒写**且不落一个字节。

    红证（撤修复）：把写路径上的 `_WRITE_LOCK` 换成 `contextlib.nullcontext()` /
    删掉 `with _WRITE_LOCK:` → 本用例必红（不再抛 `WriteLockError`，账号目录被写出来）。
    """
    root = tmp_path / "accounts"
    lock_dir = _lock_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "_LOCK_WAIT_S", 0.05)
    _seed("buddy", "acct-1", root)                      # 先建号：删除路径也要有可删对象
    lock = _foreign_lock(lock_dir)

    with pytest.raises(store.WriteLockError, match="互斥被占用"):
        store.commit_login("buddy", "acct-1", {"token": "t"}, {}, root=root)
    with pytest.raises(store.WriteLockError, match="互斥被占用"):
        store.delete_account("buddy", "acct-1", root=root)

    res = store.import_account("buddy", payload={"name": "acct-2", "token": "t"}, root=root)
    assert res.ok is False and "互斥被占用" in res.message   # CLI 面：可读原因，不抛栈

    assert (root / "acct-1" / "credentials.json").exists(), "拒写：已有账号一个字节都不能动"
    assert not (root / "acct-2").exists(), "拒写：新账号目录都不该出现"
    assert lock.read_text(encoding="utf-8").startswith("1 "), "他人的锁不得被误删"


def test_lock_released_after_write_and_stale_lock_reclaimed(tmp_path, monkeypatch):
    """① 写成功即释放（锁目录不留锁文件）；② 死进程留下的陈旧锁可回收（不永久堵死写入）。"""
    root = tmp_path / "accounts"
    lock_dir = _lock_dir(tmp_path, monkeypatch)

    store.commit_login("buddy", "acct-1", {"token": "t-1"}, {}, root=root)
    assert not (lock_dir / store.ACCOUNTS_LOCK_NAME).exists(), "① 正常路径必须释放干净"

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()                                                    # 已回收 → pid 确定已死
    _foreign_lock(lock_dir, pid=dead.pid)
    store.commit_login("buddy", "acct-1", {"token": "t-2"}, {}, root=root)   # ② 不被死锁堵死
    assert store.load_credentials("buddy", "acct-1", root=root) == {"token": "t-2"}
    assert not (lock_dir / store.ACCOUNTS_LOCK_NAME).exists()


def test_lock_dir_unusable_fails_closed_with_readable_error(tmp_path, monkeypatch):
    """🔴 锁**建不起来**（锁目录位置被普通文件占住 / 只读盘）→ 拒写 + 可读错误。

    判据同时钉"**不退 `/tmp` 退路**"：本次调用零落盘（账号目录一个都没建出来）。
    红证（撤修复）：写路径不取锁 → 本用例必红（拿不到锁就直接干，账号照样落盘）。
    """
    root = tmp_path / "accounts"
    blocked = tmp_path / "locks"
    blocked.write_text("我是文件，不是目录", encoding="utf-8")
    monkeypatch.setenv(store.ACCOUNTS_LOCK_DIR_ENV, str(blocked))
    monkeypatch.setattr(store, "_LOCK_WAIT_S", 0.05)

    with pytest.raises(store.WriteLockError, match="锁目录不可用"):
        store.commit_login("buddy", "acct-1", {"token": "t"}, {}, root=root)
    assert not (root / "acct-1").exists(), "锁建不起来 → 必须一个字节都不落"

    res = store.import_account("buddy", payload={"name": "acct-1", "token": "t"}, root=root)
    assert res.ok is False and "锁目录不可用" in res.message
    assert blocked.is_file() and blocked.read_text(encoding="utf-8") == "我是文件，不是目录", \
        "不得把占位的用户文件当锁目录删掉/改写"


def test_lock_covers_the_materialization_config_save(tmp_path, monkeypatch):
    """🔴 临界区必须**包住资源物化**（配置的读-改-写）——否则"两个进程各自物化"仍丢资源。

    构造：`commit_login` 触发物化时（monkeypatch `materialize.ensure_resource`）观察
    锁文件正被**本进程**持有；物化不在锁内时该观察为假（= 本用例红）。
    """
    root = tmp_path / "accounts"
    lock_dir = _lock_dir(tmp_path, monkeypatch)
    from model_gateway.accounts import materialize

    seen: dict[str, bool] = {}

    def probing_ensure(product, name, **kw):
        path = lock_dir / store.ACCOUNTS_LOCK_NAME
        seen["lock_held"] = (path.exists()
                             and path.read_text(encoding="utf-8").split()[0] == str(os.getpid()))
        return "res-probe"

    monkeypatch.setattr(materialize, "ensure_resource", probing_ensure)
    store.commit_login("buddy", "acct-1", {"token": "t"}, {}, root=root)
    assert seen.get("lock_held") is True, "物化（配置读-改-写）必须落在同一临界区里"


def test_interleaved_second_process_write_is_refused_and_nothing_is_lost(tmp_path, monkeypatch):
    """🔴 F5 主红证：在 A 的"写凭据"与"写 meta"之间插入**真第二进程**的写。

    有锁：第二进程被拒（退出码非 0 + 可读原因），A 的落盘完整、写回自检通过；
    无锁（撤修复）：第二进程写成功 → A 随后写 meta 覆盖它、自检读回被改的凭据 →
    以 `CommitError` 收场（丢更新的可观测化）→ 本用例红。
    """
    root = tmp_path / "accounts"
    _lock_dir(tmp_path, monkeypatch)
    second: dict[str, object] = {}
    real_write = store.atomic_write_json

    def interleaving_write(path, data):
        if Path(path).name == "meta.json" and "proc" not in second:
            second["proc"] = subprocess.run(
                [sys.executable, "-c", _SECOND_PROCESS], capture_output=True, text=True,
                env={**os.environ, "MGW_BUDDY_ACCOUNTS": str(root)})
        return real_write(path, data)

    monkeypatch.setattr(store, "atomic_write_json", interleaving_write)
    failure: Exception | None = None
    try:
        store.commit_login("buddy", "acct-1", {"token": "A"}, {"from": "A"}, root=root)
    except Exception as e:                     # noqa: BLE001 — 无锁时这里因丢更新自检失败
        failure = e

    assert "proc" in second, "交错点没被触发（用例自身失效）"
    proc = second["proc"]
    assert proc.returncode != 0, (
        f"第二个进程没有被拒（跨进程互斥失效 → 丢更新）：stdout={proc.stdout!r} "
        f"stderr={proc.stderr!r}")
    assert "REFUSED" in proc.stdout and "互斥" in proc.stdout, proc.stdout
    assert failure is None, f"有锁时不该出现落盘失败：{failure!r}"
    assert store.load_credentials("buddy", "acct-1", root=root) == {"token": "A"}
    assert store.load_meta(root, "acct-1")["from"] == "A"
