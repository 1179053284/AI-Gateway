"""前端渲染门（§21 / Q28）纳入机械门 —— 含**变异自证**（验收 IX-5）。

为什么必须在 pytest 里跑：`scripts/verify_v2_frontend.mjs` 是全站唯一的前端判据，
此前只能手工敲；手工的门等于没有门（改坏前端不会有任何东西变红）。
本测试用**真实装配**产 overview.json（不启服务），然后要求：
① 145 条实测断言全绿；② 203 个源码变异**每个都能让指定断言变红**。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO.parent / "bianyiandhuanjing" / "scripts" / "verify_v2_frontend.mjs"


def _seed_quota_accounts() -> None:
    """给「账号资源额度」板块播种判别性数据（2026-10-07）。

    🔴 为什么要播种：板块渲染函数即使整块缺失/写坏，只要载荷里 `accounts_quota` 是空表，
    整页类判据就没有对象可测（「无对象的判据就是空判据」）。播种三类形状：

    - `buddy`：两个账号（一启用一停用）→ 合计 640.5 credits、`1 启用`、停用号也计入；
      同时塞一条**失效包 999**（不得计入）与一条 **null 余量**（不得当 0）；
    - `zcode`：一个 token 号（1 亿）+ 一个 `no_plan` 号 → 量纲是 token、`1 个无套餐`；
    - `raccoon`：一个账号**没有 runtime.json** → 卡片出「尚未刷新」状态词。

    数据经生产同一条落盘入口（`store.commit_login` + `store.write_runtime`），
    数据目录由 conftest 的 `MG_CONFIG` 隔离在 tmp（不碰仓库 `data/`）。
    """
    from model_gateway.accounts import store

    def _item(unit, remaining, *, active=True):
        return {"name": "包", "unit": unit, "remaining": remaining, "total": None,
                "used": None, "active": active, "expires_at": ""}

    def _quota(state="available", *, reason="", items=None, checked_at="2026-10-07T10:00:00"):
        return {"state": state, "source": "gate", "detail": "", "checked_at": checked_at,
                "plan": "", "items": items or [], "remaining": None, "reason": reason,
                "data_at": "", "plan_key": ""}

    store.commit_login("buddy", "acc-gate-a", {"token": "t"}, {"enabled": True})
    store.write_runtime("buddy", "acc-gate-a", {"quota": _quota(items=[
        _item("credits", 500.0), _item("credits", 100.5), _item("credits", None),
        _item("credits", 999.0, active=False)])})
    store.commit_login("buddy", "acc-gate-b", {"token": "t"}, {"enabled": False})
    store.write_runtime("buddy", "acc-gate-b", {"quota": _quota(items=[_item("credits", 40.0)])})

    store.commit_login("zcode", "acc-gate-tok", {"token": "t"}, {"enabled": True})
    store.write_runtime("zcode", "acc-gate-tok",
                        {"quota": _quota(items=[_item("token", 100_000_000)])})
    store.commit_login("zcode", "acc-gate-noplan", {"token": "t"}, {"enabled": True})
    store.write_runtime("zcode", "acc-gate-noplan",
                        {"quota": _quota(state="unknown", reason="no_plan")})

    store.commit_login("raccoon", "acc-gate-never", {"token": "t"}, {"enabled": True})


def _overview_payload(tmp_path: Path) -> Path:
    """用**真实端点**造 overview 载荷（四类告警 + 一条被熔断的资源 + 整页所需的全部字段）。"""
    from model_gateway.main import create_app
    from model_gateway.upstream.zcode import quota as zq

    # 🔴 数据根隔离守卫（2026-10-07 一次真实自伤钉死：本文件的 `_seed_quota_accounts()`
    #    在 `MG_CONFIG` 未设时被 `make_overview_payload.py` 直接调用，5 个假账号被物化成
    #    资源并继承了产品位映射，写进了用户正在使用的 `coding/data/`）。
    #    隔离不是"记得设环境变量"，而是**装配函数自己查**：落在默认那份数据根上就当场红。
    from model_gateway.core import paths

    root = paths.data_dir()
    assert root != paths.default_data_dir(), (
        f"数据根 = 仓库默认那份（{root}）—— 门载荷的假账号会写进用户正在使用的配置；"
        "调用方必须先设 MG_CONFIG 指向隔离目录（pytest 由 conftest 钉，"
        "手工跑 make_overview_payload.py 由脚本自己钉）")

    cfg = {
        "resources": [
            {"id": "res-a", "name": "资源A", "access_mode": "api", "protocol": "openai",
             "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-a"},
            {"id": "res-b", "name": "孤儿资源", "access_mode": "api", "protocol": "openai",
             "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-b"},
            {"id": "res-c", "name": "停用资源", "enabled": False, "access_mode": "api",
             "protocol": "openai", "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-c"},
            {"id": "res-d", "name": "资源D", "access_mode": "api", "protocol": "openai",
             "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-d"},
        ],
        "models": [
            {"name": "ok-model", "endpoint": "chat",
             "resources": [{"resource": "res-a", "model": "vm-a"}]},
            {"name": "empty-model", "endpoint": "chat", "resources": []},
            {"name": "zombie-model", "endpoint": "chat",
             "resources": [{"resource": "res-c", "model": "vm-c"}]},
            {"name": "shadow-model", "endpoint": "chat", "params": {"reasoning_effort": "max"},
             "resources": [{"resource": "res-d", "model": "vm-d",
                            "reasoning": {"enabled": True, "effort": "low"}}]},
        ],
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    app = create_app(config_path=cfg_path, usage_dir=tmp_path / "usage",
                     enums_path=tmp_path / "enums.yaml")
    runtime = app.state.runtime
    # 🔴 把「连续失败」与「处理中」造出**不同的值**（第十一轮 eng-B B11-4）：
    #    原来两列恒为 0/0，把它们的取值对调，81 条判据一条都不会红。
    held = runtime.resources.pick_and_acquire("ok-model", set())
    assert held is not None, "取不到资源说明生效集为空，fixture 不再可判别"
    for _ in range(3):
        runtime.resources.note_failure(held, "上游 500：连续失败（fixture 造的判别值）")
    # 熔断原因走**生产函数**（与 `/admin/api/zcode/bench` 同一条路径）
    assert zq.apply_to_resource(runtime, ["res-a"], reason="ZCode 风控熔断（30min，全局）") == 1
    # 🔴 载荷必须由**真实端点**产出（第八轮 ix B-8 / K0）：原先手工拼 `{warnings, resources}`
    #    两件，前端门于是拿到一份生产里不存在的形状 —— `renderDashboard` 读的
    #    `data.today` / `data.counts` 全缺，整页装配类判据（K0~K6）根本没有对象可测。
    # 🔴 账号侧播种（2026-10-07）：让 `accounts_quota` 板块在整页渲染里有判别性对象；
    #    必须在 GET 之前落盘（端点每次请求重算、进程不缓存）。
    _seed_quota_accounts()
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        resp = client.get("/admin/api/overview")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload.get("today") and payload.get("counts"), "端点形状变了，前端门的整页判据要跟着改"
    assert payload.get("accounts_quota"), "账号资源额度板块的载荷为空 —— 播种失效或端点丢了该键"
    seeded = {p["product"] for p in payload["accounts_quota"]}
    assert {"buddy", "zcode", "raccoon"} <= seeded, f"播种的三个产品没出现在载荷里：{seeded}"
    out = tmp_path / "overview.json"
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return out


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=180, cwd=str(REPO))


@pytest.fixture(scope="module")
def node() -> str:
    found = shutil.which("node")
    if not found:
        pytest.skip("本机无 node，前端门无法执行")
    return found


def test_frontend_assertions_all_pass(tmp_path, node):
    """145 条前端断言全绿（IX-4/S-18 徽章四态人话判据 + S-19 冷却口径 C12~C14
    + 第七轮 C15/C16 + 第八/九轮 K0~K9 整页装配可达性（含可见性清洗与端点分派）
    + 第十一轮 Z1/Z2/Z3 门自测（可见性语义 / 派生出的 Node 全局集 / 门没被抛错打瞎）
    + 第十二轮 Z4 样式表派生自测 / Z5 realm 桥封死 / C18 冷却到期那一支
    + J3 指路↔控件归属派生 + 红点行为段 I0~I9
    + S-46 第一批：`api.js`/`components.js` 共享行为真跑 L0~L20 + L21（✕/遮罩也要给答复，S-61）
    + S-46 第二批：两个正式页面真跑 M0~M18（apiaccess.js 的 D3 启停/编辑/增删/密文/眼睛/复制
      + settings.js 的脏态徽章⇔保存使能同源、二段保存、400 失败支、参数绑定、维护区、参数行结构）
    + 2026-10-03 系统设置两卡参数行：H3 定宽 / H4 死类已删 / M18 逐行一对一
    + 页名↔导航交叉核对 J1/J2
    + 2026-10-07 总览「账号资源额度」板块 Q1~Q13（每产品小卡：量纲/状态词/新鲜度/证据条
      + dashboard 与 accounts.js 两份额度格式化的交叉断言）。"""
    payload = _overview_payload(tmp_path)
    r = _run([node, str(SCRIPT), str(payload)])
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "失败 0 项" in r.stdout, r.stdout
    # 判据数量本身也要钉住：断言被悄悄删掉 = 门变窄而无人察觉。
    # 🔴 取**最后一次**出现：`split("实测 ")` 拿第一段会被判据名里的一句"（不依赖浏览器
    #    实测）"抢走，届时解析出来的是别的数字，下限形同虚设（S-47 同族：缺省/取数错方向
    #    都会让判据"永远绿"）。
    # 🔴 下限必须钉在**当前真实条数**上，不是"很久以前的条数"：留 85 这种旧下限等于允许
    #    门悄悄缩水 24 条而一声不响。删判据应当立刻红，要留就一起改这个数字并说明理由。
    count = int(r.stdout.rsplit("实测 ", 1)[1].split(" 项")[0])
    assert count >= 145, f"断言总数只剩 {count} 条（门被删窄也要能红）"


def test_frontend_assertions_can_actually_go_red(tmp_path, node):
    """🔴 变异自证：203 个源码变异都必须让指定断言变红，且无断言未被覆盖。"""
    payload = _overview_payload(tmp_path)
    r = _run([node, str(SCRIPT), str(payload), "--mutation"])
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "未被任何变异覆盖的断言" not in r.stdout, r.stdout
    left, total = r.stdout.rsplit("可红 ", 1)[1].split("；")[0].split("/")
    assert int(left) == int(total), f"只有 {left}/{total} 个变异能打破绿态"
    assert int(total) >= 203, f"变异表缩水到 {total} 条（每条判据都得配一个能打红的变异）"
