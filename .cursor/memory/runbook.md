# Model-Gateway 操作手册（命令/链路 · 直接复制用）
> 🔴 **术语读法（2026-10-04）**：本文件条目按写入当时的措辞保留（存证不改写）。旧条目里指接入方的「厂商」读作**供应商**、「系统模型」读作**网关模型**。定义源 = `docs/specs/prd.md` §2，细则 = `.cursor/rules/mg-terminology.mdc`，台账侧同读法说明见 `docs/changes/_TERMINOLOGY.md`。
> 用途：**命令字面只在这里存一份**（人复制走本文件；AI 的执行顺序与判读见项目场景手册 `.cursor/skills/`——`mgw-delivery-round` / `mgw-gate-hygiene` / `mgw-live-audit`，入口 `INDEX.md`；skill 不复制命令，只指针回本文件）。
> 目录布局真相源 = 根 `项目目录说明.md`；本文件命令全部实测可跑，改命令前先实跑（原文：无命令可复制前禁止凭印象写）。
> 核验：2026-10-11 只读腿 5/5 实测通过（台账 `docs/changes/e2e-records/E2E-20261011-knowledge-refit.md` §5）；**全量门整链复跑为在册债务**（并行会话在飞，待收敛后首跑补账）——「全部实测可跑」按此口径读。

## 1 环境准备
- 源码唯一区 `coding/`；venv 就地（Python 3.12）：`cd coding && ~/.local/bin/python3.12 -m venv .venv && .venv/bin/pip install -e .`
  - 🔴 本机系统 `python3` = 3.9.6 且**无 pytest/pyyaml** ⇒ 一切脚本一律用 **`coding/.venv/bin/python`**。
- 生效配置 = `coding/data/config.yaml`；`MG_CONFIG` 指向它，**数据目录 = 该配置文件的父目录**（`core/paths.py`）。
- 🔴 隔离实例/临时腿一律 `MG_CONFIG=<仓库外路径>`（**每条命令都带，不能靠 `cd`**）；改配置/写盘类动作在仓库外数据根做。
- 仓库外数据根没有环境变量别名（**不存在 `MGW_DATA_ROOT`**，写了是 no-op）。

## 2 运行
- 启动（用户双击）：`bianyiandhuanjing/启动网关.command`（等价后台：`cd coding && exec nohup .venv/bin/python -m model_gateway.main`）
- 健康检查：`curl -fsS -m 2 http://127.0.0.1:8300/health | grep '"status"'`
- 停止/重启（admin 令牌）：`POST http://127.0.0.1:8300/admin/api/system/stop` / `…/system/restart`
  - 🔴 重启走 `os.execv`：**同 PID 换代**（`ps -o lstart` 也不变）⇒ **进程时刻不是重启判据**；判据用"幂等零写盘请求的回执新键 + 配置 md5 跑前=跑后"。
  - 重启/停止**须用户逐次批准**（会打断在途请求）。
- 端口占用排查：`lsof -nP -iTCP:8300 -sTCP:LISTEN` 取 PID 再 kill（🔴 禁 `pkill -f`：`env VAR=… ` 前缀不在命令行里，匹配不到 ⇒ 旧进程占端口、旧代码冒充新代码）。
- 管理 CLI：`cd coding && .venv/bin/python -m model_gateway.cli --help`（安装后等价 `mgw --help`）。

## 3 验收（一轮改动的完整门链 · 逐字可跑）
0. **前端语法（ES 模块）**：`cp <file>.js /tmp/x.mjs && node --check /tmp/x.mjs`
   （🔴 `node --check <file>.js` 按 CommonJS 解析 = **假绿**。🔴 **本条是「页面 .js 语法检查」规则的唯一主人**——skill 与 pitfalls 只留指针（P-033）；门内嵌 JS 的抽取检查归 skill `mgw-gate-hygiene` §2.1 专用脚本，两者对象不同不算重复）
1. **全量机械门**：`bash bianyiandhuanjing/scripts/ship-gate.sh --gates`
   - 🔴 `[1/2] pytest` 非 0 时**直接 exit，`[2/2]` 根本不跑** ⇒ 红时必须手工复跑下列门才能报"其余门号"；终局行 `SHIP-GATE: GREEN|RED`
2. **全量 pytest（原始输出行）**：`cd coding && .venv/bin/python -m pytest -q`
3. **账号页静态门**：`node bianyiandhuanjing/scripts/verify_accounts_ui.mjs`（+ `--mutation`）
   - 终局行：`合计：N 通过 / M 失败`；变异行：`可红 X/Y；Y 条判据全部可证伪（expectGreen 型…）` 或 `…；N 项 BAD`
   - 🔴 取终局数一律 **grep 关键词**（失败清单打在合计行**之后**，tail 会取错）
4. **v2 前端门（必须吃载荷）**：
   `OV=$(coding/.venv/bin/python bianyiandhuanjing/scripts/make_overview_payload.py "${TMPDIR:-/tmp}") && node bianyiandhuanjing/scripts/verify_v2_frontend.mjs "$OV"`
   （裸调 = 打印用法并 exit 2）
5. **映射回执门**：`node bianyiandhuanjing/scripts/verify_map_switch_receipt.mjs`（+ `--mutate 1..N`，要求逐条恰一红）
6. **参数卡门**：`node bianyiandhuanjing/scripts/verify_model_param_card.mjs`（+ `--mutate 1..12`）
7. **设置页真机**：`coding/.venv/bin/python bianyiandhuanjing/scripts/verify_settings_layout.py`
8. **账号页真机（隔离实例 + 假上游，端口 8400–8499 自挑空闲）**：
   `coding/.venv/bin/python bianyiandhuanjing/scripts/verify_accounts_ui_live.py --port 84xx`
   （`--skip-legs` = 调试开关，脚本自己标注「**不得用于交付**」；跑前=跑后源码 md5 一致才算该轮读数有效）
9. **岛式计数（README 取值口径 · 🔴 本条是「README 测试计数取值」规则的唯一主人**，skill 与 pitfalls 只留指针（P-064/P-066）**）**：
   `git archive HEAD | tar -x -C /tmp/island-N && cd /tmp/island-N/coding && /Users/w/Desktop/Model-Gateway/coding/.venv/bin/python -m pytest -q`
   - README 两处都要改：badge（`coding/README.md:13`）+ 正文（`:182`），`README.zh-CN.md` 同步；取值 = 收集数 − skip 数
   - 守卫窗口 = **单向区间** `[collected−20, collected]`（`coding/tests/unit/test_v2_readme_claims.py` 单向断言，不许虚报；本机守卫因并行会话未跟踪测试而红是**设计内**，报备 + 写红因，禁改数字蒙绿）
   - 收集面含 `coding/tests/` 下五支 `verify_v*_repro.py`（`coding/pyproject.toml` 的 `python_files` 覆写；行号随编辑漂移不引，事实以该键现值为准）
10. **端到端最小调用（需真实凭据 + 用户授权）**：
    `curl -sS http://127.0.0.1:8300/v1/chat/completions -H "Authorization: Bearer <access_token>" -H 'Content-Type: application/json' -d '{"model":"<网关模型>","messages":[{"role":"user","content":"ping"}],"max_tokens":2048,"stream":false}'`
    - 🔴 `max_tokens` 过小会被带思考的模型整份花在 reasoning 上 ⇒ 正文空但事件行 success（假阴性制造机）；判"通道不可用"前先放大到 ≥2048。

## 4 数据位置与清理
- 配置/锁：`coding/data/config.yaml`、`coding/data/gateway.lock`；日志 `coding/data/gateway.log`（>32MB 由启动器轮转 `.1`）
- 用量流水：`coding/data/usage/events-YYYYMMDD.jsonl`（🔴 字段名是 **`system_model`**，不是 `model`）、`ops-results-*.jsonl`（相邻 `ts` 差 = 真实刷新节奏）
- 账号运行态：`coding/data/upstream/<product>/accounts/*/runtime.json`（`quota.checked_at` 是 ISO 串，不是 epoch）
- 证据台账：`docs/changes/**`（🔴 `docs/changes/` 维持 gitignore ⇒ 永不进提交，别把"没进提交"误读为失败；`docs/specs/` 自 2026-10-11 起跟踪）
- **台账生命周期（2026-10-11 定版，decisions ⑤）**：进行中住 `docs/changes/open/`；轮次彻底完结**自主迁移** `docs/changes/e2e-records/`（完结存证区，查找按文件名 `E2E-YYYYMMDD-*` 日期 + 内容 grep）；待用户表态 = `docs/handoffs/`（完成移 `done/`；2026-10-11 自根 `other/` 并入）
- 清理：临时实例数据根、探针脚本一律 `/tmp`，跑完即清（规矩 12 零垃圾）；运行期临时物不入库

## 5 授权协议（哪些必须先问用户）
- **逐次批准**：重启/停止 `:8300`、真实厂商出站（会烧额度）、写真实 `coding/data/config.yaml`、`git push`（规矩 13）。
- **可自主**：只读 GET 探针、隔离实例（仓库外数据根 + 假上游）、本地门与 pytest、`docs/changes` 台账与评审文档。
