"""CLI → **运行中的网关** 的本地接口调用（v2.0 §16.6 / §21 跨进程出口）。

**为什么需要**：`mgw zcode claim` / `mgw probe` 都是**独立进程**，改不动运行中网关的
内存态（方言表快照、资源冷却状态、顶栏红点计数）。验收发现同类缺陷两处：
探测后方言表不重载、CLI 领取路径的风控熔断不回写 —— 都是"只在 cron 进程内生效"。

**约定**：取数走 `admin_get_detail`，它把"为什么没拿到"一起返回
（未运行 / 超时 / 401 密钥失效是三件不同的事，用户在 CLI 看到的判据必须能分辨）。
`admin_post` 只敲免鉴权的 `/admin/*`，失败返回 `None` 由调用方降级（下次启动自然加载）。
**只对本机 `127.0.0.1:<gateway.port>` 发请求**，不外发（铁律 1 纯本地运行）。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path


def _local_opener() -> urllib.request.OpenerDirector:
    """🔴 禁用代理的 opener（铁律 1 纯本地运行；2026-10-08 实盘抓修）。

    `urllib.request.urlopen` 默认读环境代理（`urllib.request.getproxies()`）——
    本机开着系统代理（如 `http_proxy=127.0.0.1:7890`）时，对 `127.0.0.1:<port>`
    的请求会被**代理转发**：空端口打过去得到 `HTTPError 502`（落 "timeout"/
    "http-502" 而非 "not-running"），真在跑的网关也可能被代理挡成超时 ⇒
    「未运行 / 超时 / 401」三态判据全失真。本模块只对本机回环发请求，
    代理永远不该出现在这条路上。
    """
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def admin_post(path: str, *, port: int | None = None, timeout: float = 3.0,
               payload: dict | None = None,
               config_path: Path | None = None) -> dict | None:
    """向运行中的网关 POST 一个管理端点；失败（含未运行）返回 None。

    `path` 形如 `/admin/api/ops/ack`；`payload` 给出时以 JSON 体发送。
    `port` 缺省从配置读 `gateway.port`。
    """
    if port is None:
        try:
            from model_gateway.config.loader import load_config
            port = load_config(config_path).gateway.port
        except Exception:  # noqa: BLE001 — 配置不可用（未初始化/路径不同）视为不可达
            return None
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                     data=body, method="POST", headers=headers)
        raw = _local_opener().open(req, timeout=timeout).read()
        data = json.loads(raw) if raw else {}
    except (OSError, ValueError):  # 未运行 / 网络错误 / 非 JSON 响应
        return None
    return data if isinstance(data, dict) else {}


#: 失败原因 → 一句话判据（给用户看的，不是给日志看的）
REASONS = {
    "ok": "运行中网关的真实状态",
    "not-running": "网关未运行（连接被拒）",
    "timeout": "网关无响应（超时）",
    "unauthorized": "网关在运行但拒绝了接入密钥（401：密钥已停用或删除）",
    "forbidden": "网关拒绝访问该接口（403）",
    "bad-json": "网关返回了非 JSON 响应",
}


def reason_text(why: str) -> str:
    """把 `admin_get_detail` 的原因码翻成**给用户看的一句话**。

    🔴 不能直接打印原因码：`http-404` 这类黑话对使用者没有任何信息量（验收 L-1）。
    未登记的状态码也要说清"是网关答了但答得不对"，而不是漏出码值。
    """
    if why in REASONS:
        return REASONS[why]
    if why.startswith("http-"):
        code = why.split("-", 1)[1]
        return (f"网关有应答但返回了未预期的状态码 {code}"
                "（接口版本与网关不一致的可能性最大）")
    return f"取数失败（未归类的原因：{why}）"


def admin_get_detail(path: str, *, port: int | None = None, timeout: float = 3.0,
                     headers: dict | None = None,
                     config_path: Path | None = None) -> tuple[dict | None, str]:
    """`admin_get` 的**带判据**版本：返回 `(数据, 原因)`。

    🔴 为什么要把原因拿出来（验收 T9b）：原先只有 `None` 一种失败值，
    调用方只能说"网关未运行"—— 而真实原因是 `/v1/models` 在鉴权中间件后面，
    **网关跑得好好的，是我们的请求没带密钥**。判据说谎比没有判据更坏。

    原因取值见 `REASONS`；HTTP 4xx/5xx 的其他情况返回 `"http-<code>"`。
    """
    if port is None:
        try:
            from model_gateway.config.loader import load_config
            port = load_config(config_path).gateway.port
        except Exception:  # noqa: BLE001 — 配置不可用视为不可达
            return None, "not-running"
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                     method="GET", headers=dict(headers or {}))
        data = json.loads(_local_opener().open(req, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        return None, {401: "unauthorized", 403: "forbidden",
                      404: "http-404", 500: "http-500", 502: "http-502",
                      503: "http-503"}.get(e.code, f"http-{e.code}")
    except TimeoutError:            # socket.timeout 在 3.10+ 就是它的别名
        return None, "timeout"
    except OSError:                 # 连接被拒 / 端口未监听
        return None, "not-running"
    except ValueError:
        return None, "bad-json"
    return (data if isinstance(data, dict) else None), "ok"
