# 启动脚本 v2 后台化改造实测记录（2026-09-05）

## 变更
`启动网关.command` 由「前台运行网关」改为「守护式启动器」：
- ① 已运行（`/health` 免鉴权可达，`model_gateway/api/auth.py:15`）→ `open` 默认浏览器打开管理页 + AppleScript 按 tty 关闭承载脚本的 Terminal 标签页，退出码 0。
- ② 未运行 → `nohup` 后台拉起（stdin=/dev/null、stdout/stderr 追加 `data/gateway.log`、脱离终端会话），轮询 `/health` 就绪（≤15s）后开页 + 关窗。
- ③ 失败/超时 → 窗口保留，按字节偏移截取「本次启动」段日志原样展示（退出码 2 配置错 / 3 已有实例，口径同 `main.py`）；若日志含「已有实例运行中」按已运行处理（双击竞态）。

## 实测证据（macOS 26 arm64，网关 127.0.0.1:8300）
- 场景①（已运行）：`bash 启动网关.command` → 输出「网关已在运行…即将打开管理页」，`open` 触发浏览器加载，`exit=0`。
- 场景②（首次启动）：SIGTERM 停掉在跑实例（health 不可达确认）→ 跑脚本 → 「网关未在运行，正在后台启动…网关已就绪」`exit=0`；**新开 shell** 复查：`health OK`、`pgrep`=PID 80208、锁 `{"pid":80208,"port":8300,…}`（启动 shell 退出后守护进程存活）。日志中可见浏览器真实加载全部 UI 资源（`/js/pages/*.js`、`/admin/api/overview` 均 200）。
- 场景③（启动失败）：`MG_CONFIG=/tmp/mg-bad-config.yaml`（`fail_threshold: 0` 违反 ge=1）→ 窗口输出：
  ```
  网关启动失败，本次启动日志如下（完整日志：data/gateway.log）：
  配置校验失败，拒绝启动：
    - /tmp/mg-bad-config.yaml → scheduling.fail_threshold: Input should be greater than or equal to 1
  ```
  `exit=1`，窗口保留至按回车。
- 语法：`bash -n` / `zsh -n` 双通过。

## 已知边界（诚实声明）
- 自动关窗依赖 Terminal.app + AppleEvents 授权；未授权/其他终端软件/无 tty 环境（如 CI）自动降级为不关窗，不影响网关。
- 实测在本会话 shell 内执行（无 Terminal 标签页），「关窗」分支为降级空转；nohup 脱离会话与 tty 精确关窗的 AppleScript 逻辑为成熟模式，但**双击真机关窗动作未逐帧录像验证**。
- `data/gateway.log` 为 uvicorn INFO 级追加写（含访问日志），无轮转；事件流水另有 retention_days 管控，此文件不适用。
