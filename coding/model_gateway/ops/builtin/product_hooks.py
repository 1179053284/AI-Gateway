"""产品契约表的**公共取用点**（ops/builtin 内部；§22.3 `_HOOKS` / `_OPTIONAL_HOOKS`）。

两个多产品 operation（`claim` / `query_balance`）都要"按名取产品钩子"与"判定传输类异常"
—— **只此一份**：各写一份就是"两份实现迟早分叉"的老坑（同 §16.3「业务码表只留一份」的口径）。

🔴 取用纪律（与 `api/admin_accounts.py::_hook` / `accounts/login.py::_hook` 同形）：
只认产品模块导出的**契约表**，不给字符串 `getattr` 后门；表里没有的名字当场 `KeyError`
（消息列合法值），由调用方隔离成单账号失败。
"""

from __future__ import annotations

import importlib

import httpx

#: 传输类异常（钩子**没有折叠**它们 = 网络边界直接抛出来了）→ 结构化声明可重试。
#: 用异常类判定而不是文案：`httpx.HTTPError` 覆盖连接/超时/协议错误，`OSError` 覆盖
#: 底层 socket 失败（`TimeoutError` 自 py3.10 起是 `OSError` 子类）。
_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (httpx.HTTPError, OSError)


def hook_of(product: str, hook_name: str):
    """按名取产品钩子（**只经契约表**；缺项当场 `KeyError`，见模块头）。"""
    module = importlib.import_module(f"model_gateway.upstream.{product}.product")
    for table_name in ("_HOOKS", "_OPTIONAL_HOOKS"):
        table = getattr(module, table_name, None)
        if isinstance(table, dict) and hook_name in table:
            return table[hook_name]
    raise KeyError(f"{product} 未导出钩子 {hook_name!r}（契约表缺项，§22.3）")


def is_transport_failure(e: BaseException) -> bool:
    """该异常是否传输类（= 可重试的网络边界失败；R1-F2 的结构化判据之一）。"""
    return isinstance(e, _TRANSPORT_ERRORS) or isinstance(
        getattr(e, "__cause__", None), _TRANSPORT_ERRORS)
