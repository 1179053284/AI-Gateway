#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""起一台**隔离实例**给参数配置卡做真机核验（2026-10-04 参数档案回填轮）。

为什么要有它：`:8300` 跑的是重启前的旧后端 ⇒ `/admin/api/enums` 里没有 `param_fields`，
在它上面只能验"回落形状"，验不到"档案回填之后界面到底画了几行、依据列写没写官方原话"。
重启 :8300 要用户点头（并行会话也可能在这台实例上做事），所以按本仓既有做法起临时实例。

🔴 零真实凭据：配置是合成的（一条假资源 + 按内置目录取网关模型名单），数据根在 `--dir`
指定处（默认 `/tmp/mgw-param-instance`）；`MG_CONFIG` 指过去 ⇒ `data_dir()` 跟着走，
不碰项目 `coding/data/`，也不发任何真实上游请求（出站会打到 127.0.0.1:1 直接失败）。

用法：
  python3 bianyiandhuanjing/scripts/serve_param_instance.py --port 8491
  MGW_PARAM_URL=http://127.0.0.1:8491/#/models python3 bianyiandhuanjing/scripts/probe_model_param_card.py
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import uvicorn
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "coding"))

from model_gateway.enums.matcher import BUILTIN_ENTRIES          # noqa: E402
from model_gateway.main import create_app                        # noqa: E402

#: 真机要看的模型（覆盖：档案全空的、只有平台级默认的、被忽略的、会报错的、推荐值的）
MODELS = ["hy3", "gemini-3.6-flash", "claude-fable-5-1", "claude-haiku-4-5",
          "sensenova-6.8-flash-lite", "MiniMax-M2.7", "glm-5.2",
            "gpt-6-astra", "sensenova-u1-fast"]


class _FakeUpstream(BaseHTTPRequestHandler):
    """假供应商通道（占位用；参数卡核验不需要真出站，任何请求都回 500）。"""

    def do_POST(self):  # noqa: N802
        self.send_response(500)
        self.end_headers()

    def log_message(self, *_a):
        pass


def _free_or_given(port: int) -> int:
    with socket.socket() as s:
        if port:
            s.bind(("127.0.0.1", port))
            return port
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_config(fake_port: int, port: int) -> dict:
    by_name = {e.name: e for e in BUILTIN_ENTRIES}
    missing = [n for n in MODELS if n not in by_name]
    if missing:
        raise SystemExit(f"模型不在内置目录，验不到档案：{missing}")
    entry = {"id": "res-fake", "name": "假供应商通道", "access_mode": "api",
             "protocol": "openai", "base_url": f"http://127.0.0.1:{fake_port}/v1",
             "api_key": "sk-not-a-real-key", "enabled": True}
    models = []
    for name in MODELS:
        e = by_name[name]
        models.append({"name": name, "group": e.group or "未分组", "endpoint": e.endpoint,
                       "enabled": True, "params": dict(e.params_default),
                       "resources": [{"resource": "res-fake", "model": name, "enabled": True}]})
    return {"gateway": {"port": port, "host": "127.0.0.1"}, "resources": [entry], "models": models}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8491)
    ap.add_argument("--dir", default="/tmp/mgw-param-instance")
    args = ap.parse_args()

    base = Path(args.dir)
    base.mkdir(parents=True, exist_ok=True)
    fake = _free_or_given(0)
    srv = HTTPServer(("127.0.0.1", fake), _FakeUpstream)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    port = _free_or_given(args.port)
    cfg_path = base / "config.yaml"
    # 🔴 先指 `MG_CONFIG` 再建 app：账号根 / 运营锁根 / 日志根都经 `core/paths.py` 解析，
    #   而它优先读环境变量。只把 `config_path=` 传给 `create_app` 是不够的 ——
    #   2026-10-04 就这么把一台"临时实例"接到了真实 `coding/data/` 上（枚举到 35 个账号；
    #   本轮零出站动作，但隔离面是破了）。判据：启动行必须报"枚举到 0 个账号"。
    import os
    os.environ["MG_CONFIG"] = str(cfg_path)
    cfg_path.write_text(yaml.safe_dump(build_config(fake, port), allow_unicode=True,
                                       sort_keys=False), encoding="utf-8")
    app = create_app(config_path=cfg_path, usage_dir=base / "usage",
                     enums_path=base / "model-enums.yaml")
    print(f"SERVED http://127.0.0.1:{port}/#/models  数据根={base}  假通道={fake}", flush=True)
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    except KeyboardInterrupt:
        pass
    time.sleep(0.2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
