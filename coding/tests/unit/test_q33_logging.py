"""Q33-债13 · INFO 级诊断必须在**出货形状**下真的看得见（2026-10-03 真机复验自抓）。

病灶不是"日志太吵"，是"排障证据不存在"：`uvicorn.run(log_level="info")` 的 dictConfig 只配
`uvicorn*` 三个 logger、不碰 root，而 `model_gateway` 这个 logger 自己不挂 handler ⇒
记录向上传给 root（`WARNING` + 无 handler）后只能落到 `logging.lastResort`，
按 WARNING 起放 ⇒ **所有 `logger.info` 静默**。真机对照：同一实例同一批请求，
启动前多一行 `basicConfig(level=INFO)` 就有 2 行 `[选路·流式]`，出货形状 0 行。

四条判据各挡一种"看起来修好了"：
① 挂上 handler 且 INFO 真的写到 stderr（fd 级捕获，不是"handler 存在"这种半证据）；
② 级别旋钮是真的（`MGW_LOG_LEVEL=WARNING` ⇒ INFO 不再出现）；
③ 幂等（重复装配不叠加 handler ⇒ 同一条日志不会印 N 遍）；
④ `create_app` 真的调了它（只测函数本身 = 一条没人接的线也能全绿）。
"""

from __future__ import annotations

import importlib
import logging
import sys

import pytest
import yaml


def _fresh_logger():
    """清掉上一次留下的 handler，模拟"进程刚起来"的形状（本模块的判据不能被前一个用例预热）。"""
    log = logging.getLogger("model_gateway")
    for h in list(log.handlers):
        log.removeHandler(h)
        h.close()
    return log


def _write_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({
        "gateway": {"host": "127.0.0.1", "port": 8399, "access_tokens": []},
        "resources": [{"id": "res-u", "name": "U", "protocol": "openai",
                       "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-u"}],
        "models": [{"name": "m-u", "endpoint": "chat",
                    "resources": [{"resource": "res-u", "model": "vm-u"}]}],
    }, allow_unicode=True), encoding="utf-8")
    return path


def test_info_reaches_stderr_once_wired(tmp_path, capfd, monkeypatch):
    monkeypatch.delenv("MGW_LOG_LEVEL", raising=False)
    log = _fresh_logger()
    from model_gateway.main import configure_logging
    configure_logging()

    assert log.level == logging.INFO, log.level
    assert log.handlers, "没挂 handler ⇒ 又回到 lastResort 那条静默路上"
    log.info("[选路] 探针：承载不了，已换下一条")
    err = capfd.readouterr().err
    assert "[选路] 探针" in err, f"INFO 没落到 stderr（读到 {err[:120]!r}）"


def test_level_knob_is_real(tmp_path, capfd, monkeypatch):
    monkeypatch.setenv("MGW_LOG_LEVEL", "WARNING")
    log = _fresh_logger()
    from model_gateway.main import configure_logging
    configure_logging()

    assert log.level == logging.WARNING, log.level
    log.info("[选路] 这条不该出现")
    log.warning("这条该出现")
    err = capfd.readouterr().err
    assert "这条不该出现" not in err, "环境变量没生效 ⇒ 旋钮是装饰"
    assert "这条该出现" in err


def test_wiring_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.delenv("MGW_LOG_LEVEL", raising=False)
    _fresh_logger()
    from model_gateway.main import configure_logging
    configure_logging()
    n = len(logging.getLogger("model_gateway").handlers)
    configure_logging()
    configure_logging()
    assert len(logging.getLogger("model_gateway").handlers) == n == 1, "handler 叠加 ⇒ 一条日志印 N 遍"


def test_create_app_actually_calls_it(tmp_path, monkeypatch):
    """🔴 只测函数本体 = 一条没人接的线也能全绿（装配点才是这条债的落点）。"""
    _fresh_logger()
    import model_gateway.main as m
    main = importlib.reload(m)
    calls: list[int] = []
    real = main.configure_logging

    def spy():
        calls.append(1)
        return real()

    monkeypatch.setattr(main, "configure_logging", spy)
    monkeypatch.setenv("MG_CONFIG", str(_write_config(tmp_path)))
    main.create_app(_write_config(tmp_path))
    assert calls, "create_app 没调用 ⇒ 出货形状依旧静默"
    assert logging.getLogger("model_gateway").handlers, "调用后仍无 handler"
