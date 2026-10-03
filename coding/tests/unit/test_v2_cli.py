"""v2.0 §19 M3-0 / M3-5 CLI 测试。

🔴 判据（§19）：`mgw --help` 退出码 0；`mgw setup` 支持 `--dry-run` 与路径确认。
⚠️ 本项目此前**没有任何命令入口**（`pyproject.toml` 无 `[project.scripts]`）——
   本测试同时守住"入口声明存在"这条。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from model_gateway.cli import main


def _write_config(tmp_path: Path, *, with_token: bool = True, with_model: bool = True) -> Path:
    cfg: dict = {
        "resources": [{"id": "res-a", "name": "资源A", "access_mode": "api",
                       "protocol": "openai", "base_url": "http://127.0.0.1:9/v1",
                       "api_key": "sk-a"}],
        "models": ([{"name": "glm-5.2", "endpoint": "chat",
                     "resources": [{"resource": "res-a", "model": "vm-a"}]}]
                   if with_model else []),
    }
    if with_token:
        cfg["gateway"] = {"port": 8300, "access_tokens": [
            {"id": "tok_1", "name": "测试", "value": "mg-test-token"}]}
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return p


# ---------- CLI 骨架（M3-0）----------

def test_cli_entry_declared_in_pyproject():
    """🔴 `[project.scripts]` 必须存在（此前项目无任何命令入口）。"""
    text = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.scripts]" in text
    assert 'mgw = "model_gateway.cli:main"' in text


def test_help_exits_zero(capsys):
    """§19 M3-0 交付判据：`mgw --help` 退出码 0。"""
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0
    assert "mgw" in capsys.readouterr().out


def test_version_exits_zero(capsys):
    assert main(["--version"]) == 0
    assert "mgw" in capsys.readouterr().out


def test_no_command_prints_help(capsys):
    assert main([]) == 0
    assert "probe" in capsys.readouterr().out


@pytest.mark.parametrize("sub", ["probe", "setup", "zcode"])
def test_subcommand_help_exits_zero(sub, capsys):
    with pytest.raises(SystemExit) as e:
        main([sub, "--help"])
    assert e.value.code == 0


def test_zcode_without_subcommand_prints_usage(capsys):
    assert main(["zcode"]) == 0
    assert "list" in capsys.readouterr().out


# ---------- mgw setup（M3-5）----------

def test_setup_unknown_product_exits_2(tmp_path, capsys):
    cfg = _write_config(tmp_path)
    assert main(["setup", "nope", "--config", str(cfg)]) == 2
    assert "未知产品" in capsys.readouterr().err


def test_setup_dry_run_writes_nothing(tmp_path, capsys):
    cfg = _write_config(tmp_path)
    rc = main(["setup", "workbuddy", "--config", str(cfg),
               "--dry-run", "--yes"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "目标目录" in out and "来源" in out      # 路径确认（写入纪律 0）
    assert "dry-run" in out
    assert not (tmp_path / ".workbuddy" / "models.json").exists()


def test_setup_prints_resolved_target_and_source(tmp_path, capsys):
    """🔴 写前**必须打印解析结果与来源** —— 该路径曾被环境变量劫持。"""
    cfg = _write_config(tmp_path)
    main(["setup", "workbuddy", "--config", str(cfg), "--dry-run", "--yes"])
    out = capsys.readouterr().out

    assert "目标目录" in out
    assert "来源" in out


def test_setup_non_interactive_requires_yes(tmp_path, capsys, monkeypatch):
    """非交互环境缺 `--yes` → 拒绝执行（防误写）。"""
    cfg = _write_config(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    rc = main(["setup", "workbuddy", "--config", str(cfg)])

    assert rc == 2
    assert "--yes" in capsys.readouterr().err


def test_setup_without_token_exits_2(tmp_path, capsys):
    cfg = _write_config(tmp_path, with_token=False)
    rc = main(["setup", "workbuddy", "--config", str(cfg), "--yes"])
    assert rc == 2
    assert "接入密钥" in capsys.readouterr().err


def test_setup_without_models_exits_2(tmp_path, capsys):
    cfg = _write_config(tmp_path, with_model=False)
    rc = main(["setup", "workbuddy", "--config", str(cfg), "--yes"])
    assert rc == 2
    assert "系统模型" in capsys.readouterr().err


def test_setup_writes_valid_models_json(tmp_path, monkeypatch, capsys):
    """端到端：写出符合 CLI 契约的 models.json（`{models, availableModels}`）。"""
    cfg = _write_config(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("WORKBUDDY_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEBUDDY_CONFIG_DIR", raising=False)

    rc = main(["setup", "workbuddy", "--config", str(cfg), "--yes"])

    assert rc == 0
    target = home / ".workbuddy" / "models.json"
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and "models" in data and "availableModels" in data
    entry = data["models"][0]
    assert entry["id"] == "custom-local:glm-5.2"
    assert entry["supportsToolCall"] is True
    assert len(entry["caps"]["thinkingLevelMap"]) == 7
    assert "已写入" in capsys.readouterr().out


# ---------- mgw probe（M3-3）----------

def test_probe_non_interactive_requires_yes(tmp_path, capsys, monkeypatch):
    cfg = _write_config(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    rc = main(["probe", "--config", str(cfg)])

    assert rc == 2
    assert "--yes" in capsys.readouterr().err


def test_probe_unknown_model_exits_2(tmp_path, capsys):
    cfg = _write_config(tmp_path)
    rc = main(["probe", "--model", "nope", "--yes", "--config", str(cfg)])
    assert rc == 2
    assert "未定义的系统模型" in capsys.readouterr().err


# ---------- Q28-②：文件下发路径必须与 /v1/models **同一判据**（验收 IX M-1）----------

def _setup_cfg(tmp_path):
    """两条映射都"配置上可用"的模型 + 一条映射指向停用资源的模型。"""
    cfg = {
        "resources": [
            {"id": "res-a", "name": "资源A", "base_url": "http://127.0.0.1:9/v1",
             "api_key": "sk-a"},
            {"id": "res-b", "name": "资源B", "base_url": "http://127.0.0.1:9/v1",
             "api_key": "sk-b"},
        ],
        "models": [
            {"name": "healthy-model", "endpoint": "chat",
             "resources": [{"resource": "res-a", "model": "vm-a"}]},
            {"name": "runtime-dead", "endpoint": "chat",
             "resources": [{"resource": "res-b", "model": "vm-b"}]},
        ],
        "gateway": {"port": 8399, "access_tokens": [
            {"id": "tok", "name": "t", "value": "mg-t"}]},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


def test_cli_models_hide_what_the_gateway_cannot_serve(tmp_path):
    """🔴 判据机制（Q28-② 路径 A）：`servable` 里没有的模型**不得**进 `models.json`。

    上一版文件下发路径只看配置文件（`Resource.enabled`），感知不到运行态
    → 只读文件的 WorkBuddy 仍会拿到一个必然失败的模型。
    "运行态从哪来"不在此断言 —— 那归 `tests/integration/test_int_v2_setup_live.py`
    （真网关 + 真鉴权）；这里曾桩掉 `admin_get` 自证，属**空过**（验收 T9b 点名）。
    """
    from model_gateway.cli_setup import build_cli_models
    from model_gateway.config.loader import load_config
    from model_gateway.core.dialects import DialectTable
    from model_gateway.enums.matcher import load_enum_pool

    config = load_config(_setup_cfg(tmp_path))
    enums, dialects = load_enum_pool(tmp_path / "enums.yaml"), DialectTable.load(tmp_path / "d.yaml")
    rows = build_cli_models(config, enums, dialects, "http://127.0.0.1:1/v1", "mg-t",
                            servable={"healthy-model"})     # 网关说只有这一个可服务
    assert [r["id"] for r in rows] == ["custom-local:healthy-model"]
    assert "runtime-dead" not in json.dumps(rows, ensure_ascii=False)
    # 不给 servable 时退回纯配置判定：两个都算可服务（判据来源不同，结论必须不同才说明真的用了它）
    both = build_cli_models(config, enums, dialects, "http://127.0.0.1:1/v1", "mg-t")
    assert len(both) == 2


def test_setup_without_running_gateway_says_it_is_config_only(tmp_path, capsys):
    """网关没跑 → 可以按配置判定，但**必须声明判定依据**（不得让用户以为是实时状态）。"""
    cfg = _setup_cfg(tmp_path)
    rc = main(["setup", "workbuddy", "--config", str(cfg), "--dry-run", "--yes"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "本地配置" in out and "网关未运行" in out, out
    assert "运行中网关" not in out, out
    assert "已跳过" not in out                 # 配置视角下两个模型都可服务


def test_setup_degrade_warning_travels_on_the_write_line(tmp_path, capsys):
    """🔴 降级提醒必须钉在「将写入」那一行上（面板 S-19 escape）。

    用户读的是最后那行清单条数；提醒若漂到别的位置（或被后续输出挤出屏幕），
    "2 条系统模型"看起来就像实时结论 —— 判据因此不看"某处提到过"，只看那一行。
    """
    cfg = _setup_cfg(tmp_path)
    rc = main(["setup", "workbuddy", "--config", str(cfg), "--dry-run", "--yes"])
    out = capsys.readouterr().out
    assert rc == 0
    lines = [l for l in out.splitlines() if l.startswith("将写入")]
    assert len(lines) == 1, out
    assert "⚠ 未取到运行态" in lines[0], lines[0]
    # 同一条里必须同时看得见"条数"和"这条清单可能是旧的"
    assert "条系统模型" in lines[0], lines[0]


# ---------- S-9：`mgw setup` 的隐藏说明必须**按成因**分别指路 ----------

def test_hidden_causes_are_split_into_three_buckets(tmp_path):
    """🔴 三种成因三句话（面板 S-9：统一说"去添加映射"对其中两种是错的指路）。"""
    import yaml as _yaml

    from model_gateway.cli_setup import _CAUSE_HINTS, _hidden_causes
    from model_gateway.config.loader import load_config

    cfg = {
        "resources": [
            {"id": "res-on", "name": "开着的资源", "access_mode": "api",
             "base_url": "http://127.0.0.1:9/v1", "api_key": "sk"},
            {"id": "res-off", "name": "关着的资源", "enabled": False, "access_mode": "api",
             "base_url": "http://127.0.0.1:9/v1", "api_key": "sk"},
        ],
        "models": [
            {"name": "no-map", "endpoint": "chat", "resources": []},
            {"name": "off-map", "endpoint": "chat",
             "resources": [{"resource": "res-off", "model": "vm"}]},
            {"name": "runtime-dead", "endpoint": "chat",
             "resources": [{"resource": "res-on", "model": "vm"}]},
        ],
    }
    path = tmp_path / "config.yaml"
    path.write_text(_yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    config = load_config(path)

    buckets = _hidden_causes(config, ["no-map", "off-map", "runtime-dead"])
    assert buckets["no_mapping"] == ["no-map"]
    assert buckets["resource_disabled"] == ["off-map"]
    assert buckets["runtime_dead"] == ["runtime-dead"], "资源开着却不可服务 = 运行态问题"
    # 三句指路各不相同（相同即等于又回到"统一指路"）
    hints = {_CAUSE_HINTS[k] for k in buckets}
    assert len(hints) == 3, hints
    assert "添加资源映射" in _CAUSE_HINTS["no_mapping"]
    assert "启用开关" in _CAUSE_HINTS["resource_disabled"]
    assert "最近错误" in _CAUSE_HINTS["runtime_dead"]


def test_route_copy_names_the_page_that_actually_hosts_the_column():
    """🔴 排障指路的页名必须与**真实现**交叉核对（验收 S-17 / ix M7）。

    页名从前分散在 `main.config_warnings()` 与 `cli_setup._CAUSE_HINTS` 两处，
    而前端门只验"后端文案原样透传" —— 指错页面（"去「模型资源」页看「最近错误」"，
    而那一列长在「总览」）谁都不会红。现在页名收在 `core.resources` 一份，
    本判据再把"文案点到的列"与"该列真正所在的 js 文件"对齐一次
    （判据自己从仓库根找文件，不依赖生产侧放常量）。
    """
    from pathlib import Path

    from model_gateway.cli_setup import _CAUSE_HINTS
    from model_gateway.core.resources import OVERVIEW_HEALTH_PAGE, RESOURCE_PAGE

    pages = Path(__file__).resolve().parents[2] / "model_gateway" / "web" / "static" / "js" / "pages"
    body = {p.name: p.read_text(encoding="utf-8") for p in sorted(pages.glob("*.js"))}
    hosts = sorted(name for name, text in body.items() if "最近错误" in text)
    assert hosts == ["dashboard.js"], f"「最近错误」列的归属变了，请同步路线常量：{hosts}"

    dead_hint = _CAUSE_HINTS["runtime_dead"]
    assert "最近错误" in dead_hint and OVERVIEW_HEALTH_PAGE in dead_hint, dead_hint
    assert RESOURCE_PAGE not in dead_hint, "又把人指到没有这一列的页面了"
    # 三条指路各点一个真实存在的页面（页名与 PAGE 常量同源，不允许自由文本漂移）
    from model_gateway.core.resources import ROUTE_POOL_PAGE

    for kind, hint in _CAUSE_HINTS.items():
        assert any(page in hint for page in (ROUTE_POOL_PAGE, RESOURCE_PAGE,
                                             OVERVIEW_HEALTH_PAGE)), (kind, hint)


def test_route_copy_points_at_a_page_that_actually_hosts_the_control():
    """🔴 指路不能只"页存在"，那一页还得**真的长着它承诺的控件**（第八轮 ix B-2）。

    面板的变异把徽章点到的页换成「资源池设置」页：页名在导航里真实存在
    （"页名↔导航"那类判据全绿），但那一页**没有启用开关也没有 Key 编辑器** ——
    用户照着提示翻遍该页找不到入口，比指到一个不存在的页更难查（他会以为自己找错地方）。
    判据两边都钉：① 控件的实现标记还在（改名/删除即红）；
    ② 「X」页**后面紧跟的那个分句**里承诺的动作，必须能由 X 页的实现文件承载。
    """
    import re
    from pathlib import Path

    from model_gateway.core.resources import (OVERVIEW_HEALTH_PAGE, RESOURCE_PAGE,
                                              ROUTE_POOL_PAGE)

    root = Path(__file__).resolve().parents[2] / "model_gateway"
    pages_js = root / "web" / "static" / "js" / "pages"
    body = {p.name: p.read_text(encoding="utf-8") for p in sorted(pages_js.glob("*.js"))}

    # ① 控件实现标记必须还在（改名或删掉 = 指路落空）
    for fname, tokens in (("resources.js", ("keyDrafts", "reveal", "rv-toggle")),
                          ("models.js", ("poolRows",)),
                          ("dashboard.js", ("最近错误", "冷却剩余"))):
        missing = [t for t in tokens if t not in body.get(fname, "")]
        assert not missing, f"{fname} 里找不到实现标记 {missing}（控件被改名/删除？）"

    # 🔴 归属**由控件派生**（第十一轮 PM B-11-1 + ix B11-6）：原先这里手写
    #    `"映射": {"resources.js", "models.js"}` —— 把"两侧都可以"写进表里，
    #    正是"页名真实存在但那一页没有该控件"能双绿的原因。
    #    规则：动作绑一个源码里真实存在的控件标记，谁的文件含该标记，动作就归谁。
    markers = {
        "添加·更换映射": (r"(?:添加|新增|更换|新建)[^，。；、「」()]{0,10}映射", "rv-addmap"),
        "换 Key": (r"(?:更换|换)\s*(?:Key|key|密钥)", "rv-addkey"),
        "启用开关": (r"(?:打开|启用)[^，。；、「」()]{0,6}(?:开关|资源)", "rv-toggle"),
        "档位·移除映射": (r"(?:移除映射|档位|优先级)", "poolRows"),
    }
    owners = {label: {f for f, text in body.items() if ctrl in text}
              for label, (_, ctrl) in markers.items()}
    for label, files in owners.items():
        assert files, f"动作「{label}」的控件标记在全部页面实现里都找不到（改名/删页？）"

    # 页名 → 实现文件：由路由元数据派生（PAGE_META 的 key 就是 pages/<key>.js）
    main_js = (root / "web" / "static" / "js" / "main.js").read_text(encoding="utf-8")
    page_to_file = {title: f"{key}.js" for key, title in
                    re.findall(r'(\w+):\s*\{\s*title:\s*"([^"]+)"', main_js)}
    consts = {"ROUTE_POOL_PAGE": ROUTE_POOL_PAGE, "RESOURCE_PAGE": RESOURCE_PAGE,
              "OVERVIEW_HEALTH_PAGE": OVERVIEW_HEALTH_PAGE}

    def expand(src: str) -> str:
        """Python 侧的指路是 f-string 拼常量（`到{RESOURCE_PAGE}启用…`），
        不还原成字面值就扫不到 —— 本轮的错指路恰好都长这样。"""
        return re.sub(r"\{(ROUTE_POOL_PAGE|RESOURCE_PAGE|OVERVIEW_HEALTH_PAGE)\}",
                      lambda m: consts[m.group(1)], src)

    clause = re.compile(r"[「『]([^「」『』]{2,10})[」』]页([^「」『』]{0,60})")
    offenders = []
    seen = 0
    copy_files = [pages_js / n for n in sorted(p.name for p in pages_js.glob("*.js"))]
    copy_files += [root / "main.py", root / "cli_setup.py"]
    for f in copy_files:
        text = expand(f.read_text(encoding="utf-8"))
        for m in clause.finditer(text):
            named = page_to_file.get(m.group(1))
            if named is None:
                continue                 # 未知页名由前端门的 J2 负责
            # 括号里是解释不是"到这一页要做的事"；`<` 之后是模板串外的代码
            promise = re.split(r"[<（(。;#]", m.group(2))[0]
            for label, (pat, ctrl) in markers.items():
                if not re.search(pat, promise):
                    continue
                seen += 1
                if named not in owners[label]:
                    offenders.append(
                        f"{f.name}: 说「{m.group(1)}」页{promise[:18]}（{label}），"
                        f"但该动作的控件只在 {'/'.join(sorted(owners[label]))}")
    # `seen` 下限：抽取本身坏掉（正则/文件被改坏）时不得把"零违规"当成通过
    assert seen >= 4, f"只命中 {seen} 条指路，判据可能在空转"
    assert not offenders, "; ".join(offenders)

    # ③ 三条路线常量本身与这张表一致（常量写错 = 所有指路一起歪）
    assert RESOURCE_PAGE == "「接入模型资源」页" and ROUTE_POOL_PAGE == "「网关模型管理」页"
    assert OVERVIEW_HEALTH_PAGE == "「总览」页的资源健康表"


def test_cli_models_feed_the_same_spec_into_the_caps_block(tmp_path, monkeypatch):
    """🔴 UT-88 · `mgw setup` 写进工具配置文件的 `caps.thinkingLevelMap` 必须吃同一份规格。

    复验轮 R5-③：`build_cli_models` 里 `build_model_caps(..., spec=...)` 传了规格，
    而 `build_caps_block(m, enum_pool, dialects)` **漏传** ⇒ 不在内置枚举池、档位只存在于
    按号目录缓存里的账号模型，写出来的七个键全是 null —— 工具侧推理档位变哑，
    正是 `/v1/models` 那条路上刚消灭的原缺陷在**另一条出口**复活
    （与本文件自己的"两条路径同一判据，不得各说各话"直接冲突）。
    """
    import yaml
    from model_gateway.accounts import catalog_cache
    from model_gateway.accounts.types import ModelInfo
    from model_gateway.cli_setup import build_cli_models
    from model_gateway.config.loader import load_config
    from model_gateway.core.dialects import DialectTable
    from model_gateway.enums.matcher import load_enum_pool

    root = tmp_path / "up" / "buddy"
    (root / "accounts").mkdir(parents=True)
    monkeypatch.setenv("MGW_BUDDY_ACCOUNTS", str(root / "accounts"))
    catalog_cache.write_cache("buddy", [ModelInfo(id="vm-x", context_window=200000,
                                                  max_output=8000, reasoning=True,
                                                  effort_levels=("low", "high"))],
                              source_account="acc-1", root=root)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "resources": [{"id": "res-p", "name": "号1", "product": "buddy", "account_ref": "acc-1",
                       "account": "acc-1", "protocol": "openai",
                       "base_url": "http://127.0.0.1:9/v1", "api_key": ""}],
        "models": [{"name": "账号独有模型", "endpoint": "chat",
                    "resources": [{"resource": "res-p", "model": "vm-x"}]}],
    }, allow_unicode=True), encoding="utf-8")
    config = load_config(cfg_path)
    enums = load_enum_pool(tmp_path / "enums.yaml")
    dialects = DialectTable.load(tmp_path / "d.yaml")

    rows = build_cli_models(config, enums, dialects, "http://127.0.0.1:1/v1", "mg-t")
    assert len(rows) == 1, rows
    levels = rows[0]["caps"]["thinkingLevelMap"]
    assert any(v for v in levels.values()), f"档位全 null（spec 没喂进 caps 块）：{levels}"
    assert rows[0]["supportsReasoning"] is True
    assert rows[0]["maxOutputTokens"] == 8000
    # 🔴 复验 R10 报备 4：`/v1/models` 有的**陈旧标注位**，下发文件也必须有 ——
    #    只读文件的工具（WorkBuddy 这类）拿不到这个位，就仍然会把"昨天缓存里的数"
    #    当成实时事实，正是刚闭口那条欠账在**第二条出口**复活（与本测试自己的立意冲突）。
    assert rows[0]["specStale"] is False, rows[0]
    # 🔴 两份都要推过期：规格取数是「**按号**优先、产品级兜底」，只改产品级那份
    #    等于测了兜底腿（我第一次就写错在这里：glob 的是 `CACHE_FILE + "*"`，
    #    只命中 `_catalog_cache.json`，按号副本 `_catalog_cache.<名>-<hash>.json` 没动 ⇒ 判据假红）。
    for p in sorted(root.glob("_catalog_cache*")):
        data = json.loads(p.read_text(encoding="utf-8"))
        data["fetched_at"] -= catalog_cache.DEFAULT_TTL_SECONDS + 60
        p.write_text(json.dumps(data), encoding="utf-8")
    stale = build_cli_models(config, enums, dialects, "http://127.0.0.1:1/v1", "mg-t")
    assert stale[0]["specStale"] is True, stale[0]
    # 标"陈旧"不收回数值：陈旧缓存仍是可用的兜底来源（工具按承诺上限规划请求）
    assert stale[0]["maxOutputTokens"] == 8000 and stale[0]["maxInputTokens"] == 200000
