"""T9b（第四轮验收）：`mgw setup` 的**运行态取数**必须真的穿过鉴权。

上一版的缺陷：`/v1/models` 在 `AuthMiddleware` 后面（`/v1/*` 一律要接入密钥），
而 `mgw setup` 发的是**匿名**请求 → 401 → `admin_get` 只返回 `None` → CLI 把
"网关跑得好好的、是我们没带钥匙"打印成"网关未运行"。**判据说谎比没有判据更坏**：
用户会去查网关进程，永远查不出真正的原因（密钥/配置不一致）。

本文件因此**不桩 `admin_get`**：起真 uvicorn（随机高位端口、真鉴权中间件），
CLI 侧走真 `urllib` 打过去，只把 conftest 对本机 HTTP 的封锁解掉。
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import socket
import urllib.request
from pathlib import Path

import pytest
import yaml

from model_gateway.cli import main
from model_gateway.core import local_admin as la
from tests.integration.conftest import chat_res, gateway_config

#: conftest 的 autouse fixture 会桩掉 `urllib.request.urlopen`（防误伤本机 8300 实例）。
#: 本文件要的就是真回环请求，故在**模块导入时**（fixture 尚未介入）存下原始函数。
_REAL_URLOPEN = urllib.request.urlopen

LIVE_TOKEN = "mg-live-token"

#: 占位厂商端口：本文件不发推理请求，只用 `/v1/models` 的配置视角（port 9 = 丢弃位）
_VENDOR = 9


@pytest.fixture(autouse=True)
def allow_loopback(monkeypatch):
    """解掉 conftest 对本机 HTTP 的封锁（只打随机高位端口，不碰 8300）。"""
    monkeypatch.setattr(la.urllib.request, "urlopen", _REAL_URLOPEN)


def _cli_config(tmp_path: Path, *, port: int, token_value: str,
                models: list[dict]) -> Path:
    """CLI 侧配置：端口指向在跑的网关，模型清单可与网关侧不同（真实场景：本地文件更旧）。"""
    cfg = gateway_config(_VENDOR, models=models, gateway={
        "port": port,
        "access_tokens": [{"id": "tok", "name": "接入", "value": token_value}],
    })
    path = tmp_path / "cli-config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


def _setup(cfg_path: Path) -> tuple[int, str, str]:
    """跑一次 `mgw setup --dry-run --yes`，返回 (退出码, stdout, stderr)。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = main(["setup", "workbuddy", "--config", str(cfg_path),
                   "--dry-run", "--yes"])
    return rc, out.getvalue(), err.getvalue()


async def _gateway(make_gateway, *model_names: str) -> int:
    """起带接入密钥的网关（→ `/v1/models` 需要鉴权），返回其监听端口。"""
    gw = await make_gateway(gateway_config(
        _VENDOR,
        models=[chat_res("AB", name=n) for n in model_names],
        gateway={"access_tokens": [{"id": "tok", "name": "接入", "value": LIVE_TOKEN}]}))
    return int(gw.base_url.rsplit(":", 1)[1])


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------- 前置事实：/v1/models 确实要鉴权（否则下面的用例全是空过）----------

async def test_models_endpoint_rejects_anonymous(make_gateway):
    """🔴 正向对照：匿名打 `/v1/models` 必须被挡（401）。

    哪天有人把 `/v1/models` 加进豁免前缀，本文件其余用例断言的"带密钥才拿得到
    运行态"就变成恒真 —— 这条对照让它们不会集体空过。
    """
    port = await _gateway(make_gateway, "healthy-model")
    assert await _why(port, None) == "unauthorized"


async def _why(port: int, headers: dict | None) -> str:
    """在线程里发阻塞 urllib 请求（asyncio 循环被卡住的话，网关就无法应答）。"""
    _data, why = await asyncio.to_thread(la.admin_get_detail, "/v1/models",
                                         port=port, headers=headers)
    return why


# ---------- 判定依据必须与真实原因一致 ----------

async def test_setup_reads_live_models_through_auth(make_gateway, tmp_path):
    """带对了密钥 → 用运行中网关的清单判定，并**跳过**网关侧没有的模型。"""
    port = await _gateway(make_gateway, "healthy-model")
    cfg = _cli_config(tmp_path, port=port, token_value=LIVE_TOKEN, models=[
        chat_res("AB", name="healthy-model"),
        chat_res("AB", name="runtime-dead"),
    ])
    rc, out, err = await asyncio.to_thread(_setup, cfg)
    assert rc == 0, out + err
    assert "运行中网关的 /v1/models" in out, out
    assert "1 个模型可服务" in out, out
    assert "已跳过 1 个" in out and "runtime-dead" in out, out
    # 🔴 S-9：这个模型在 CLI 配置里**映射齐全且资源启用**，是网关侧不可服务
    # → 指路必须是"看最近错误"，不能是"去添加映射"
    assert "运行态不可用" in out and "最近错误" in out, out
    assert "添加资源映射" not in out, out
    assert "1 条系统模型" in out, out


async def test_setup_on_wrong_token_says_401_not_not_running(make_gateway, tmp_path):
    """🔴 本项核心：密钥不对时**不得**说"网关未运行"，要说 401 / 接入密钥。"""
    port = await _gateway(make_gateway, "healthy-model")
    cfg = _cli_config(tmp_path, port=port, token_value="mg-wrong-token",
                      models=[chat_res("AB", name="healthy-model")])
    rc, out, err = await asyncio.to_thread(_setup, cfg)
    assert rc == 0, out + err                 # 降级到配置判定仍可交付，但要警告
    assert "未运行" not in out + err, out + err
    assert "401" in out + err, out + err
    assert "接入密钥" in out + err, out + err
    assert "本地配置" in out, out


async def test_setup_when_nothing_listens_says_not_running(tmp_path):
    """端口上确实没有监听 → 才是"未运行"（三态可分辨，不是一句万能兜底）。"""
    cfg = _cli_config(tmp_path, port=_free_port(), token_value=LIVE_TOKEN,
                      models=[chat_res("AB", name="healthy-model")])
    rc, out, err = await asyncio.to_thread(_setup, cfg)
    assert rc == 0, out + err
    assert "未运行" in out + err, out + err
    assert "401" not in out + err, out + err


def test_reasons_table_covers_every_documented_reason():
    """REASONS 与 `admin_get_detail` 的返回值同源：漏一条，CLI 就打印黑话码值。"""
    assert set(la.REASONS) >= {"ok", "not-running", "timeout", "unauthorized", "bad-json"}


async def test_setup_when_gateway_hangs_says_timeout(tmp_path):
    """🔴 端口在听但不接活 → 必须说"无响应（超时）"，不是"未运行"也不是黑话状态码。

    判据缺口（面板 eng）：PRD Q28-⑤ 明写"未运行 / 超时 / 401 三态可分辨"，
    而 timeout 分支此前**零测试** —— 三态里少一态被测到，就等于该态随时可以坏掉。
    实现：`listen()` 后不 `accept()`，connect 会挂在 SYN 队列直到 read 超时。
    """
    import socket

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    hung_port = listener.getsockname()[1]
    try:
        cfg = _cli_config(tmp_path, port=hung_port, token_value=LIVE_TOKEN,
                          models=[chat_res("AB", name="healthy-model")])
        rc, out, err = await asyncio.to_thread(_setup, cfg)
    finally:
        listener.close()

    assert rc == 0, out + err
    assert "无响应" in out and "超时" in out, out
    assert "未运行" not in out, out
    assert "http-" not in out and "Traceback" not in out, out


async def test_setup_prints_human_words_for_any_http_status(make_gateway, tmp_path):
    """🔴 未登记的状态码也不得漏出 `http-404` 这类黑话（验收 L-1）。"""
    import model_gateway.core.local_admin as la

    # 直接验"翻译层"：未登记原因码必须给人话，且不泄漏码值格式
    assert "未预期" in la.reason_text("http-418") and "418" in la.reason_text("http-418")
    assert la.reason_text("not-running") == la.REASONS["not-running"]
    assert "未归类" in la.reason_text("weird-thing")
