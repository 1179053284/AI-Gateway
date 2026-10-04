#!/bin/bash
# Model-Gateway 双击启动脚本（tech-design §4.10-⑥；PRD FR-12.2）
# v2 行为：
#   ① 网关已在运行（/health 可达）→ 直接用默认浏览器打开管理页，并自动关闭本终端窗口；
#      网关继续在后台运行，关窗无影响。
#   ② 网关未运行 → 以 nohup 守护方式后台拉起（脱离终端会话；stdin 断开；
#      stdout/stderr 追加到 data/gateway.log），就绪后打开管理页并自动关闭本终端窗口。
#   ③ 启动失败（配置校验失败/端口被占/依赖缺失等）或等待超时 → 终端窗口保留，
#      原样展示本次启动日志末尾的具体原因，按回车后才关闭。
# 说明：
#   - 自动关窗 = AppleScript 按 tty 精确关闭承载本脚本的 Terminal 标签页；
#     未授权自动化/非 Terminal 环境/其他终端软件时自动降级为不关窗，不影响网关。
#   - 停止/重启网关：管理界面「设置 → 系统运行控制」，或命令行 pkill -f model_gateway.main。
#   - 退出码口径与 model_gateway.main 一致：0 正常、2 配置校验失败、3 已有实例运行。

# v2 结构（2026-10-01 对齐 codex-coding）：源码唯一区 = coding/，本脚本退到仓库根取 coding/ 下的 venv 与 data
cd "$(dirname "$0")/.." || exit 1

# 本机运行环境（gitignore 掉的文件，不存在就什么都不变）
# 为什么走文件而不是写死在本脚本里：本脚本入仓，机器路径入仓 = 换台机器就指错地方。
# 目前只有一项：MGW_QODER_WASM_GLUE（Qoder 加密端点的 wasm 签名桥目录，见 tech-design §22.4-A）。
if [ -f "coding/data/gateway.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "coding/data/gateway.env"
    set +a
fi

URL_HOST="127.0.0.1"
DEFAULT_PORT=8300
CONFIG_FILE="${MG_CONFIG:-coding/data/config.yaml}"
LOG_FILE="coding/data/gateway.log"

# 环境自检：无 venv 无法启动，给出搭建指引后保留窗口（失败原因可见）
if [ ! -x "coding/.venv/bin/python" ]; then
    printf '未检测到虚拟环境 coding/.venv，请先完成环境搭建：\n\n'
    printf '  cd coding\n  ../.local/bin/python3.12 -m venv .venv 2>/dev/null || python3.12 -m venv .venv\n  .venv/bin/pip install -e .\n\n'
    printf '完成后再次双击本脚本即可启动网关。\n'
    printf '按回车关闭本窗口…'
    read -r
    exit 1
fi

# 从配置读取端口（MG_CONFIG 可覆盖；读不到/解析失败回退 8300，配置错误由网关进程自己报出）
PORT="$(MG_CFG="$CONFIG_FILE" MG_DEF="$DEFAULT_PORT" coding/.venv/bin/python -c "
import os
try:
    import yaml
    with open(os.environ['MG_CFG'], encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    print(int((cfg.get('gateway') or {}).get('port') or os.environ['MG_DEF']))
except Exception:
    print(os.environ['MG_DEF'])
" 2>/dev/null)"
[ -n "$PORT" ] || PORT="$DEFAULT_PORT"
ADMIN_URL="http://${URL_HOST}:${PORT}/"

health_ok() {
    curl -fsS -m 2 "http://${URL_HOST}:${PORT}/health" 2>/dev/null | grep -q '"status"'
}

open_admin() {
    printf '正在打开管理页 %s …\n' "$ADMIN_URL"
    open "$ADMIN_URL" >/dev/null 2>&1
}

# 按 tty 精确关闭承载本脚本的 Terminal 标签页（nohup 异步：窗口关闭时的 SIGHUP 杀不掉它）
close_own_tab() {
    MY_TTY="$(tty 2>/dev/null)" || MY_TTY=""
    [ -n "$MY_TTY" ] || return 0
    nohup osascript -e "tell application \"Terminal\" to close (every tab of every window whose tty is \"${MY_TTY}\")" >/dev/null 2>&1 &
}

# ① 已在运行 → 开管理页 + 关窗（网关继续后台运行）
if health_ok; then
    printf '网关已在运行：%s\n即将打开管理页并自动关闭本窗口（网关不受影响）。\n' "$ADMIN_URL"
    open_admin
    close_own_tab
    exit 0
fi

# ② 未运行 → 后台守护拉起（nohup 脱离会话；关窗/注销均不影响；日志统一落 data/gateway.log）
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null
LOG_OFFSET=0
[ -f "$LOG_FILE" ] && LOG_OFFSET="$(wc -c < "$LOG_FILE" | tr -d ' ')"
printf '网关未在运行，正在后台启动（日志：%s）…\n' "$LOG_FILE"
{
    printf '===== %s 启动网关 =====\n' "$(date '+%Y-%m-%d %H:%M:%S')"
    exec nohup coding/.venv/bin/python -m model_gateway.main
} >> "$LOG_FILE" 2>&1 < /dev/null &
DAEMON_PID=$!

# ③ 轮询就绪（最长约 15 秒）；进程退出立即转入失败分支
WAITED=0
while [ "$WAITED" -lt 30 ]; do
    if health_ok; then
        printf '网关已就绪：%s\n即将打开管理页并自动关闭本窗口（网关转入后台运行，关窗不影响服务）。\n' "$ADMIN_URL"
        open_admin
        close_own_tab
        exit 0
    fi
    kill -0 "$DAEMON_PID" 2>/dev/null || break
    sleep 0.5
    WAITED=$((WAITED + 1))
done

# ④ 失败/超时：取「本次启动」段日志（按字节偏移截取，避免旧日志干扰判断）
SESSION_LOG="$(tail -c "+$((LOG_OFFSET + 1))" "$LOG_FILE" 2>/dev/null)"
[ -n "$SESSION_LOG" ] || SESSION_LOG="（本次启动日志为空或不可读）"

if printf '%s\n' "$SESSION_LOG" | grep -q "已有实例运行中"; then
    # 竞态：另一实例恰好先行完成启动（单实例锁拒绝，退出码 3）→ 按已运行处理
    printf '网关已在运行（另一实例先行启动）：%s\n即将打开管理页并自动关闭本窗口。\n' "$ADMIN_URL"
    open_admin
    close_own_tab
    exit 0
fi

if kill -0 "$DAEMON_PID" 2>/dev/null; then
    printf '等待超时：网关进程仍在启动中（%s 端口约 15 秒未就绪）。\n进程将继续后台运行；若稍后启动完成，再次双击本脚本即可打开管理页。\n' "$PORT"
else
    printf '网关启动失败，本次启动日志如下（完整日志：%s）：\n' "$LOG_FILE"
    printf '%s\n' '----------------------------------------'
    printf '%s\n' "$SESSION_LOG" | tail -n 60
    printf '%s\n' '----------------------------------------'
fi
printf '按回车关闭本窗口…'
read -r
exit 1
