"""`mgw` 命令行入口（tech-design v2.0 §19 M3-0 / M5-0）。

⚠️ 本项目**此前没有任何命令入口**（`pyproject.toml` 无 `[project.scripts]`，
只能 `python -m model_gateway.main`）。本模块是 v2.0 新增的 CLI 骨架。

子命令：
- `mgw probe`            参数方言探测（§13.3）
- `mgw setup <tool>`     工具配置下发（§12.4，路径 A）
- `mgw zcode <cmd>`      ZCode 账号管理（§17 / §19 M5-0）
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mgw",
        description="Model-Gateway 命令行工具（本地 LLM 网关）",
    )
    p.add_argument("--version", action="store_true", help="显示版本并退出")
    sub = p.add_subparsers(dest="command", metavar="<命令>")

    # —— probe（§13.3）——
    pr = sub.add_parser("probe", help="参数方言探测（三步：S1 粗筛 → S2 生效验证 → S3 定档）")
    pr.add_argument("--model", action="append", default=[],
                    help="指定模型名（可重复）；缺省 = 探测当前启用且尚无方言记录的模型")
    pr.add_argument("--all", action="store_true", help="探测全部启用模型（含已有记录的）")
    pr.add_argument("--yes", "-y", action="store_true", help="跳过确认提示（非交互场景必填）")
    pr.add_argument("--config", default=None, help="配置文件路径（缺省 data/config.yaml）")

    # —— setup（§12.4 路径 A）——
    st = sub.add_parser("setup", help="把网关模型写成工具可读的 models.json（文件下发）")
    st.add_argument("tool", help="目标工具标识（workbuddy / workbuddy-ai）")
    st.add_argument("--yes", "-y", action="store_true", help="跳过路径确认（非交互场景必填）")
    st.add_argument("--dry-run", action="store_true", help="只打印将写入的内容与目标路径，不落盘")
    st.add_argument("--config", default=None, help="配置文件路径（缺省 data/config.yaml）")

    # —— zcode（§17 / M5-0）——
    zc = sub.add_parser("zcode", help="ZCode 账号管理（登录 / 导入 / 列表 / 领取）")
    zsub = zc.add_subparsers(dest="zcode_command", metavar="<子命令>")
    zsub.add_parser("list", help="列出已接入的 ZCode 账号")
    zl = zsub.add_parser(
        "login", help="OAuth 设备流登录并新增账号（浏览器完成授权）",
        description="发起 ZCode 官方 CLI 设备授权流：打印授权地址与设备码 → 在浏览器完成授权 "
                    "→ 自动轮询并在成功后新增账号（凭据同时写入该账号的客户端数据根）。",
        epilog="退出码：0 = 登录成功并已落盘；1 = 登录失败（发起失败 / 授权被拒 / 流程过期）。\n"
               "        `mgw zcode import <凭据.json>` 仍保留为备用通道（导入本机已登录缓存）。")
    zl.add_argument("--provider", default="bigmodel", choices=["bigmodel", "zai"])
    zl.add_argument("--name", default=None, metavar="ACCOUNT",
                    help="新账号名（白名单 [A-Za-z0-9_-]{1,32}；缺省 zcode-<4位十六进制>）")
    zlaunch = zsub.add_parser("launch", help="以该账号的数据根启动 ZCode 客户端（整根隔离）")
    zlaunch.add_argument("account", help="账号名（见 `mgw zcode list`）")
    zlaunch.add_argument("--exe", default=None, help="ZCode 可执行文件路径（缺省自动探测）")
    zlaunch.add_argument("--dry-run", action="store_true", help="只打印将设置的环境变量与参数")
    zi = zsub.add_parser(
        "import",
        help="导入账号（单文件自动识别面板/小店粘贴形态与 zcode-switch 文件；或整库批量）",
        description="导入 ZCode 账号。单文件 = 自动识别形态：面板/小店粘贴 JSON"
                    "（{name,jwt,device_mid} 或 {family,credentials:{oauth:<家族>:*}}）、"
                    "zcode-switch 账号 JSON、网关载荷；其余形态按原样直交存储层。\n"
                    "整库批量：--from-panel（ZCode-Panel 账号库）/ --from-switch"
                    "（zcode-switch 账号库），逐条导入、冲突不中断。",
        epilog="退出码（单文件）：0 = 成功；4 = 设备 ID 冲突（拒绝，可 --reuse/--regenerate 重跑）；\n"
               "        1 = 失败；2 = 用法错误（缺路径 / 参数组合不合法 / 源目录不存在）。\n"
               "退出码（批量）：1 = 有硬失败（优先）；0 = 无硬失败且至少一条成功\n"
               "        （冲突已逐条打印，可 --reuse/--regenerate 重跑）；\n"
               "        4 = 无成功、全为设备冲突（与单文件同一约定：需用户决策）；\n"
               "        2 = 源目录缺失或没有可导入账号。")
    zi.add_argument("path", nargs="?", default=None,
                    help="凭据 JSON 路径（与 --from-panel/--from-switch 二选一）")
    zi.add_argument("--reuse", default=None, metavar="ACCOUNT",
                    help="设备 ID 冲突时：复用该账号的设备 ID（两者共享设备，上游可能风控）")
    zi.add_argument("--regenerate", action="store_true",
                    help="设备 ID 冲突时：为本账号生成新 ID（上游会视为换设备）")
    zi.add_argument("--device-mid", default=None, metavar="UUID",
                    help="覆盖载荷里的设备 ID（仅单文件导入；覆盖值照样过唯一性/冲突判定）")
    zi.add_argument("--from-panel", nargs="?", const="", default=None, metavar="DIR",
                    help="批量导入 ZCode-Panel 账号库（缺省自动定位：$ZPANEL_ACCOUNTS_DIR "
                         "> 面板 settings.json > 打包态默认目录）")
    zi.add_argument("--from-switch", nargs="?", const="", default=None, metavar="DIR",
                    help="批量导入 zcode-switch 账号库（缺省 ~/.zcode-switch/accounts）")
    zi.add_argument("--json", action="store_true",
                    help="机器可读 JSON 输出（单文件：结果对象；批量：结果数组 + 合计）")
    zc_claim = zsub.add_parser(
        "claim", help="领取 / 签到（批量或指定账号）",
        description="批量领取 ZCode 每日额度（未配住宅代理时可 --manual）。",
        epilog="退出码：0 = 全部正常；1 = 有失败（需关注）；2 = 无账号参与；\n"
               "        3 = **全局风控熔断中，本轮未对上游发起领取**（可能同屏列出\n"
               "            未发起即失败的账号，结论仍以 3 为准：本轮没真正跑过）\n"
               "⚠️ 3 与 `mgw setup` 的 3（写盘失败）同码不同义 —— 按子命令读退出码。")
    zc_claim.add_argument("--account", action="append", default=[], help="指定账号（可重复）")
    zc_claim.add_argument("--manual", action="store_true",
                          help="未配置住宅代理时，手动完成验证码")
    zr = zsub.add_parser("remove", help="删除该账号的本地数据根（破坏性；先打印路径再确认）")
    zr.add_argument("account", help="账号名（见 `mgw zcode list`）")
    zr.add_argument("--yes", "-y", action="store_true",
                    help="跳过确认（非交互场景必填）")

    return p


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。返回进程退出码（0 = 成功）。"""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from model_gateway import __version__
        print(f"mgw {__version__}")
        return 0

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "probe":
        from model_gateway.cli_probe import run_probe
        return run_probe(args)
    if args.command == "setup":
        from model_gateway.cli_setup import run_setup
        return run_setup(args)
    if args.command == "zcode":
        from model_gateway.cli_zcode import run_zcode
        return run_zcode(args)

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
