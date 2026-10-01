"""v2.0 §15 / §17 ZCode 接入单元测试（tech-design §19 M4-2）。

🔴 重点：**用户需求 ① 的三条硬约束**
  1. 不允许两个账号绑定到同一设备 ID
  2. 导入已有账号缓存 → **复用原设备 ID**（绝不重新生成）
  3. 冲突 → **拒绝 + 交用户决策**（不自动替换）
"""

from __future__ import annotations

import json
import os
import pathlib
from pathlib import Path

import pytest

from model_gateway.upstream.zcode import crypto, dataroot, store

# ============ crypto：enc:v1 ============

def test_encrypt_decrypt_roundtrip():
    enc = crypto.encrypt("hello-世界")
    assert enc.startswith("enc:v1:")
    assert crypto.decrypt(enc) == "hello-世界"


def test_encrypted_format_is_nonce_tag_ct():
    """格式：`enc:v1:<b64url(nonce12)>.<b64url(tag16)>.<b64url(ct)>`。"""
    enc = crypto.encrypt("x")
    parts = enc[len(crypto.PREFIX):].split(".")
    assert len(parts) == 3
    assert len(crypto._b64url_decode(parts[0])) == 12      # nonce
    assert len(crypto._b64url_decode(parts[1])) == 16      # authTag


def test_plaintext_passes_through_unchanged():
    """**非 `enc:v1` 前缀的值原样返回**（明文兼容）。"""
    assert crypto.decrypt("plain-text") == "plain-text"
    assert crypto.decrypt("") == ""


def test_decrypt_failure_degrades_silently():
    """解密失败（错误 secret / 格式坏）→ 返回空串**不崩**（与参考实现同口径）。"""
    enc = crypto.encrypt("secret-data")
    assert crypto.decrypt(enc, secret="wrong-secret") == ""
    assert crypto.decrypt("enc:v1:bad.format") == ""
    assert crypto.decrypt("enc:v1:a.b") == ""


def test_env_secret_takes_priority(monkeypatch):
    monkeypatch.setenv("ZCODE_CREDENTIAL_SECRET", "from-env")
    assert crypto.current_secret() == "from-env"
    enc = crypto.encrypt("v")
    monkeypatch.delenv("ZCODE_CREDENTIAL_SECRET")
    # 换回回退 secret → 解不开（证明 env 优先且参与派生）
    assert crypto.decrypt(enc) == ""


def test_fallback_secret_format():
    """`zcode-credential-fallback:{platform}:{home}:{username}`。"""
    s = crypto.fallback_secret(platform="darwin", home="/Users/x", username="w")
    assert s == "zcode-credential-fallback:darwin:/Users/x:w"


def test_derive_key_is_sha256():
    import hashlib
    assert crypto.derive_key("abc") == hashlib.sha256(b"abc").digest()
    assert len(crypto.derive_key("abc")) == 32


def test_encrypt_decrypt_roundtrip_with_explicit_secret():
    """往返自检直接测生产函数（原先靠 `crypto.roundtrip_ok` 包装，该包装无人调用已删）。"""
    enc = crypto.encrypt("诊断串-世界", secret=crypto.current_secret())
    assert enc.startswith(crypto.PREFIX)
    assert crypto.decrypt(enc, secret=crypto.current_secret()) == "诊断串-世界"


# ============ dataroot：整根隔离 ============

def test_ensure_layout_creates_four_dirs(tmp_path: Path):
    """整根隔离的目录骨架（data / userdata / session / home）。"""
    dataroot.ensure_layout(tmp_path, "acct")
    for sub in ("data/.zcode/v2", "userdata", "session", "home"):
        assert (tmp_path / "acct" / sub).is_dir()


def test_build_env_sets_four_env_vars(tmp_path: Path):
    """🔴 四组环境变量缺一不可（§15.3）。"""
    env = dataroot.build_env(tmp_path, "acct")

    assert env["ZCODE_DATA_BASE_DIR"] == str(tmp_path / "acct" / "data")
    assert env["ZCODE_DESKTOP_USER_DATA_DIR"] == str(tmp_path / "acct" / "userdata")
    assert env["ZCODE_DESKTOP_SESSION_DATA_DIR"] == str(tmp_path / "acct" / "session")
    assert env["ZCODE_DESKTOP_HOME_DIR"] == str(tmp_path / "acct" / "home")


def test_build_args_carries_device_id():
    """设备码通道 ①：命令行 `--device-id=`。"""
    assert dataroot.build_args("mid-1") == ["--device-id=mid-1"]


def test_ensure_device_id_generates_once_and_never_recomputes(tmp_path: Path):
    """🔴 设备码**生成一次后永不重算**（换码 = 上游眼里一次异常的设备迁移）。"""
    first = dataroot.ensure_device_id(tmp_path, "acct")
    second = dataroot.ensure_device_id(tmp_path, "acct")
    third = dataroot.ensure_device_id(tmp_path, "acct")

    assert first == second == third
    assert len(first) == 36            # 标准 UUID 形态


def test_device_id_is_persisted_in_meta(tmp_path: Path):
    mid = dataroot.ensure_device_id(tmp_path, "acct")
    meta = json.loads((tmp_path / "acct" / "meta.json").read_text(encoding="utf-8"))
    assert meta["device_mid"] == mid


def test_sync_device_mid_to_telemetry_is_idempotent(tmp_path: Path):
    """设备码通道 ②：写 `telemetry-state.json` 的 `deviceMid`；值相同则跳过写。"""
    dataroot.ensure_layout(tmp_path, "acct")
    assert dataroot.sync_device_mid_to_telemetry(tmp_path, "acct", "mid-1") is True
    assert dataroot.sync_device_mid_to_telemetry(tmp_path, "acct", "mid-1") is False  # 幂等

    p = dataroot.v2_dir_of(tmp_path, "acct") / "telemetry-state.json"
    assert json.loads(p.read_text(encoding="utf-8"))["deviceMid"] == "mid-1"


def test_check_device_id_unique_detects_collision(tmp_path: Path):
    mid_a = dataroot.ensure_device_id(tmp_path, "a")
    assert dataroot.check_device_id_unique(tmp_path, mid_a) is False
    assert dataroot.check_device_id_unique(tmp_path, "brand-new") is True


def test_check_device_id_unique_on_missing_root(tmp_path: Path):
    assert dataroot.check_device_id_unique(tmp_path / "nope", "any") is True


def test_find_account_by_device_id(tmp_path: Path):
    mid = dataroot.ensure_device_id(tmp_path, "owner")
    assert dataroot.find_account_by_device_id(tmp_path, mid) == "owner"
    assert dataroot.find_account_by_device_id(tmp_path, "other") is None


def test_generate_unique_device_id_avoids_existing(tmp_path: Path):
    taken = dataroot.ensure_device_id(tmp_path, "a")
    for _ in range(20):
        new = dataroot.generate_unique_device_id(tmp_path)
        assert new != taken


def test_generate_unique_device_id_raises_when_exhausted(tmp_path: Path, monkeypatch):
    """耗尽则**显式失败**（不静默降级）—— UUID 碰撞概率极低，耗尽意味着异常状态。"""
    monkeypatch.setattr(dataroot, "check_device_id_unique", lambda *a, **k: False)
    with pytest.raises(RuntimeError, match="无法生成唯一设备 ID"):
        dataroot.generate_unique_device_id(tmp_path, tries=3)


def test_launch_command_combines_device_and_env(tmp_path: Path):
    exe, args, env = dataroot.launch_command("/Applications/ZCode.app/x", tmp_path, "acct")

    assert exe.endswith("/x")
    assert len(args) == 1 and args[0].startswith("--device-id=")
    assert dataroot.ENV_DATA_BASE in env
    # 设备码也同步到了 telemetry（双通道）
    mid = args[0].split("=", 1)[1]
    assert dataroot._read_json(
        dataroot.v2_dir_of(tmp_path, "acct") / "telemetry-state.json")["deviceMid"] == mid


# ============ store：三条硬约束 ============

@pytest.fixture
def accounts_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    return root


def _write_payload(tmp_path: Path, data: dict, name: str = "p.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_constraint1_no_device_id_gets_unique_new_one(tmp_path, accounts_root):
    """硬约束 1：无设备 ID 的凭据 → 分配一个**跨账号唯一**的新 ID。"""
    p1 = _write_payload(tmp_path, {"name": "a"}, "a.json")
    p2 = _write_payload(tmp_path, {"name": "b"}, "b.json")

    r1 = store.import_account(str(p1))
    r2 = store.import_account(str(p2))

    assert r1.ok and r2.ok
    assert r1.device_id != r2.device_id          # ← 不允许共用


def test_constraint2_import_reuses_existing_device_id(tmp_path, accounts_root):
    """🔴 硬约束 2：缓存内已有设备标识 → **原样复用，绝不重新生成**。"""
    p = _write_payload(tmp_path, {"name": "a", "device_mid": "cached-mid-123"})
    r = store.import_account(str(p))

    assert r.ok
    assert r.device_id == "cached-mid-123"       # ← 复用，不是新生成


def test_constraint3_conflict_is_rejected_by_default(tmp_path, accounts_root):
    """🔴 硬约束 3：冲突 → **拒绝 + 交用户决策**（不自动替换）。"""
    store.import_account(str(_write_payload(tmp_path, {"name": "owner",
                                                       "device_mid": "shared-mid"}, "o.json")))
    r = store.import_account(str(_write_payload(tmp_path, {"name": "other",
                                                           "device_mid": "shared-mid"}, "n.json")))

    assert r.ok is False
    assert r.conflict is True                    # ← 调用方据此打印 3 选项、退出非 0
    assert r.conflict_with == "owner"            # ← 告诉用户与谁冲突
    # 未落盘（拒绝 = 不写）
    assert not (accounts_root / "other" / "meta.json").exists()


def test_conflict_with_regenerate_generates_new_id(tmp_path, accounts_root):
    """选项 ②：`--regenerate` 为本账号生成新 ID（上游会视为换设备）。"""
    store.import_account(str(_write_payload(tmp_path, {"name": "owner",
                                                       "device_mid": "shared-mid"}, "o.json")))
    r = store.import_account(str(_write_payload(tmp_path, {"name": "other",
                                                           "device_mid": "shared-mid"}, "n.json")),
                             regenerate=True)

    assert r.ok and r.device_id != "shared-mid"


def test_conflict_with_reuse_shares_device_id(tmp_path, accounts_root):
    """选项 ①：`--reuse <账号>` 复用目标账号的设备 ID（两者共享设备）。"""
    store.import_account(str(_write_payload(tmp_path, {"name": "owner",
                                                       "device_mid": "shared-mid"}, "o.json")))
    r = store.import_account(str(_write_payload(tmp_path, {"name": "other",
                                                           "device_mid": "shared-mid"}, "n.json")),
                             reuse="owner")

    assert r.ok and r.device_id == "shared-mid"


def test_reuse_target_missing_is_rejected(tmp_path, accounts_root):
    store.import_account(str(_write_payload(tmp_path, {"name": "owner",
                                                       "device_mid": "shared-mid"}, "o.json")))
    r = store.import_account(str(_write_payload(tmp_path, {"name": "other",
                                                           "device_mid": "shared-mid"}, "n.json")),
                             reuse="nope")
    assert r.ok is False and "--reuse" in r.message


def test_duplicate_account_name_is_rejected(tmp_path, accounts_root):
    p = _write_payload(tmp_path, {"name": "a"})
    assert store.import_account(str(p)).ok is True
    r = store.import_account(str(p))
    assert r.ok is False and "已存在" in r.message


def test_account_name_is_sanitized_against_path_traversal(tmp_path, accounts_root):
    """账号名白名单 —— 防目录穿越。"""
    p = _write_payload(tmp_path, {"name": "../../etc/passwd"})
    r = store.import_account(str(p))

    assert r.ok
    assert "/" not in r.account and ".." not in r.account
    assert (accounts_root / r.account).is_dir()
    # 没有在 accounts_root 之外创建目录
    assert not (tmp_path.parent / "etc").exists()


def test_payload_may_be_wrapped_in_outer_object(tmp_path, accounts_root):
    """允许外包一层 `account` / `data` / `payload`（与参考实现同口径）。"""
    p = _write_payload(tmp_path, {"account": {"name": "wrapped", "device_mid": "mid-x"}})
    r = store.import_account(str(p))
    assert r.ok and r.account == "wrapped" and r.device_id == "mid-x"


def test_missing_or_invalid_payload_is_rejected(tmp_path, accounts_root):
    assert store.import_account(None).ok is False
    assert store.import_account(str(tmp_path / "nope.json")).ok is False
    bad = tmp_path / "bad.json"
    bad.write_text("[1,2,3]", encoding="utf-8")
    assert store.import_account(str(bad)).ok is False


def test_import_writes_credentials_into_account_v2_dir(tmp_path, accounts_root):
    """凭据原样落进**该账号自己的** v2 目录（整根隔离）。"""
    p = _write_payload(tmp_path, {
        "name": "a", "device_mid": "mid-1",
        "credentials.json": {"zcodejwttoken": "enc:v1:x.y.z"},
    })
    r = store.import_account(str(p))
    assert r.ok

    dest = dataroot.v2_dir_of(accounts_root, "a") / "credentials.json"
    assert dest.exists()
    assert json.loads(dest.read_text(encoding="utf-8"))["zcodejwttoken"] == "enc:v1:x.y.z"


def test_list_accounts_reports_device_ids(tmp_path, accounts_root):
    store.import_account(str(_write_payload(tmp_path, {"name": "a", "device_mid": "m1"}, "a.json")))
    store.import_account(str(_write_payload(tmp_path, {"name": "b", "device_mid": "m2"}, "b.json")))

    got = {a.name: a.device_id for a in store.list_accounts()}
    assert got == {"a": "m1", "b": "m2"}


def test_list_accounts_empty_when_root_missing(accounts_root):
    assert store.list_accounts() == []


def test_delete_account(tmp_path, accounts_root):
    store.import_account(str(_write_payload(tmp_path, {"name": "a"})))
    assert store.delete_account("a") is True
    assert store.delete_account("a") is False


# ============ §19 M4-2 判据补齐（本轮 R6a / R6b）============

def test_two_accounts_do_not_overwrite_each_other(tmp_path, accounts_root):
    """🔴 判据「两账号各自 `credentials.json` / `telemetry-state.json` **互不覆盖**」。

    整根隔离的全部意义就在这条：切换账号 = 各用各的数据根，**不覆写任何凭据**。
    上一轮只测了单账号落盘，判据行因此一直挂着 ⚠️。
    """
    pa = _write_payload(tmp_path, {
        "name": "acct-a", "device_mid": "mid-aaa",
        "credentials.json": {"zcodejwttoken": "TOKEN-A"},
    }, "a.json")
    pb = _write_payload(tmp_path, {
        "name": "acct-b", "device_mid": "mid-bbb",
        "credentials.json": {"zcodejwttoken": "TOKEN-B"},
    }, "b.json")
    assert store.import_account(str(pa)).ok and store.import_account(str(pb)).ok

    creds_a = dataroot.v2_dir_of(accounts_root, "acct-a") / "credentials.json"
    creds_b = dataroot.v2_dir_of(accounts_root, "acct-b") / "credentials.json"
    tele_a = dataroot.v2_dir_of(accounts_root, "acct-a") / "telemetry-state.json"
    tele_b = dataroot.v2_dir_of(accounts_root, "acct-b") / "telemetry-state.json"

    assert json.loads(creds_a.read_text())["zcodejwttoken"] == "TOKEN-A"
    assert json.loads(creds_b.read_text())["zcodejwttoken"] == "TOKEN-B"
    assert json.loads(tele_a.read_text())["deviceMid"] == "mid-aaa"
    assert json.loads(tele_b.read_text())["deviceMid"] == "mid-bbb"
    # 两份凭据必须是**不同文件**（同路径互相覆盖是这套设计最坏的失败模式）
    assert creds_a != creds_b and creds_a.exists() and creds_b.exists()


def test_reimport_of_one_account_leaves_the_other_intact(tmp_path, accounts_root):
    """重复导入 A 不得动到 B（B 的凭据/设备码逐字节不变）。"""
    pa = _write_payload(tmp_path, {"name": "acct-a", "device_mid": "mid-aaa",
                                   "credentials.json": {"t": "A1"}}, "a.json")
    pb = _write_payload(tmp_path, {"name": "acct-b", "device_mid": "mid-bbb",
                                   "credentials.json": {"t": "B1"}}, "b.json")
    store.import_account(str(pa))
    store.import_account(str(pb))

    b_creds = dataroot.v2_dir_of(accounts_root, "acct-b") / "credentials.json"
    b_tele = dataroot.v2_dir_of(accounts_root, "acct-b") / "telemetry-state.json"
    before_c, before_t = b_creds.read_bytes(), b_tele.read_bytes()

    pa2 = _write_payload(tmp_path, {"name": "acct-a", "device_mid": "mid-aaa2",
                                    "credentials.json": {"t": "A2"}}, "a2.json")
    assert store.import_account(str(pa2), regenerate=True).ok

    assert b_creds.read_bytes() == before_c
    assert b_tele.read_bytes() == before_t


def test_main_client_directory_three_files_never_written(tmp_path, accounts_root, monkeypatch):
    """🔴 判据「主 `~/.zcode/v2/` 三件未被写入」—— **拦截式**验，不靠环境变量指路。

    上一版只设 `MGW_ZCODE_HOME` 再比对字节，但那个变量**只影响读的默认值**、
    写路径根本不经过它 → 真误写也不会红（验收 PM-B1 判为空过用例）。
    这一版直接拦所有落盘调用，并带**正控制**：探针必须先证明拦得住一次误写。
    ⚠️ `setting.json` 是 §15.3 记录的已知例外，本判据**不断言它**。
    """
    main_v2 = tmp_path / "main-home" / ".zcode" / "v2"
    main_v2.mkdir(parents=True)
    original = {}
    for fname, content in (("credentials.json", '{"zcodejwttoken":"MASTER"}'),
                           ("config.json", '{"theme":"dark"}'),
                           ("telemetry-state.json", '{"deviceMid":"MASTER-MID"}'),
                           ("setting.json", '{"a":1}')):
        (main_v2 / fname).write_text(content, encoding="utf-8")
        original[fname] = (main_v2 / fname).read_bytes()

    touched: list[str] = []
    guarded = tuple(f"{main_v2}/{n}" for n in
                    ("credentials.json", "config.json", "telemetry-state.json"))
    _real_write_text, _real_write_bytes = (pathlib.Path.write_text,
                                           pathlib.Path.write_bytes)
    _real_replace, _real_open = os.replace, os.open

    def _flag(target) -> None:
        text = str(target)
        if any(text.startswith(g) for g in guarded):
            touched.append(text)
            raise AssertionError(f"整根隔离被破坏：写到了客户端主目录 {text}")

    def wt(self, data, *a, **kw):
        _flag(self)
        return _real_write_text(self, data, *a, **kw)

    def wb(self, data, *a, **kw):
        _flag(self)
        return _real_write_bytes(self, data, *a, **kw)

    def rp(src, dst, *a, **kw):
        _flag(dst)
        return _real_replace(src, dst, *a, **kw)

    def op(path, flags, *a, **kw):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT):
            _flag(path)
        return _real_open(path, flags, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "write_text", wt)
    monkeypatch.setattr(pathlib.Path, "write_bytes", wb)
    monkeypatch.setattr(os, "replace", rp)
    monkeypatch.setattr(os, "open", op)
    monkeypatch.setenv("MGW_ZCODE_HOME", str(main_v2))

    # —— 正控制：探针必须拦得住一次真实误写 ——
    with pytest.raises(AssertionError):
        (main_v2 / "credentials.json").write_text('{"hacked":true}', encoding="utf-8")
    assert touched, "探针未生效 → 本用例会退化成'零命中'假绿"
    touched.clear()

    for name, mid in (("acct-a", "mid-aaa"), ("acct-b", "mid-bbb")):
        pl = _write_payload(tmp_path, {"name": name, "device_mid": mid,
                                      "credentials.json": {"zcodejwttoken": f"T-{name}"}},
                            f"{name}.json")
        assert store.import_account(str(pl)).ok
    dataroot.build_env(accounts_root, "acct-a", "mid-aaa")
    dataroot.ensure_layout(accounts_root, "acct-a")

    assert touched == [], f"导入链路写到了客户端主目录：{touched}"
    for fname in ("credentials.json", "config.json", "telemetry-state.json"):
        assert (main_v2 / fname).read_bytes() == original[fname]
    assert (dataroot.v2_dir_of(accounts_root, "acct-b") / "credentials.json").exists()


def test_stray_directory_is_not_an_account(tmp_path, monkeypatch):
    """🔴 账号根下的**任意子目录**不得被当成账号（与 `has_account()` 同一把尺：要有 meta.json）。

    真实后果：别的模块在同一个数据目录下落盘（本轮 conftest 就撞出过一个 `data/`
    子目录），全局熔断会去 bench 一个不存在的号、运营批量替它白跑一轮。
    """
    import json

    from model_gateway.upstream.zcode import quota as zq
    from model_gateway.upstream.zcode import store

    root = tmp_path / "accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    (root / "acct-real").mkdir(parents=True)
    (root / "acct-real" / "meta.json").write_text(json.dumps({"device_mid": "m-1"}),
                                                  encoding="utf-8")
    (root / "data").mkdir()                                  # 别的模块留下的目录
    (root / "acct-no-meta").mkdir()                          # 半成品/手工 mkdir

    assert [a.name for a in store.list_accounts()] == ["acct-real"]
    assert store.has_account("data") is False
    assert zq.zcode_account_names() == ["acct-real"], "熔断作用域里混进了假账号"
