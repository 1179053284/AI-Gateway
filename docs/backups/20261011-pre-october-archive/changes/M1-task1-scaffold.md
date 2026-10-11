# M1 任务 1 实测记录：脚手架（2026-09-03）

> 对应：tech-design v1.0 §10.1 任务 1（pyproject + 包结构 + 配置 schema + 样例 config）
> 环境：macOS · Python 3.12.13 · venv `.venv`
> 本文件为铁律 2 要求的运行证据；任务 2（商汤双端点实测）因 `SENSENOVA_API_KEY` 未设置，**SHELL（阻塞）**。

## 1. 交付物清单

| 文件 | 内容 |
|---|---|
| `pyproject.toml` | 包元数据 + 依赖（fastapi/uvicorn/httpx/pydantic/pyyaml）+ pytest 配置 |
| `.gitignore` | `data/`（明文密钥绝不入库，铁律 1）+ Python 产物 |
| `model_gateway/` | 包结构 12 模块（api/core/adapters/config/enums/stats/web + main.py + logsetup.py），各骨架标注对应 M1 任务编号 |
| `model_gateway/config/schemas.py` | 配置 schema 完整落地（PRD §6 v1.3 + tech §4.7 参数表：60s/300s/x/y/m/冷却/退避/error_rules/allow_admin/推理默认） |
| `model_gateway/config/loader.py` | 加载 + pydantic 校验（错误逐条指明位置）+ 原子写（tempfile + os.replace） |
| `model_gateway/main.py` | 入口装配 + `GET /health`（配置摘要）+ 校验失败拒绝启动（exit 2） |
| `config.example.yaml` | 样例配置（商汤双预设 + chat/images 双端点模型 + pricing 双口径 + error_rules 注释示例） |
| `scripts/sensenova_probe.py` | 商汤双端点实测脚本（任务 2 待执行：A `token.sensenova.cn/v1` / B `api.sensenova.cn/compatible-mode/v2`） |
| `tests/unit/test_config.py` | 15 用例：样例加载/三层引用完整性/数值边界/推理规则/原子写 |

## 2. 实测证据

### 2.1 依赖安装

```
$ python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
deps ok: 0.141.1 2.13.5        # fastapi 0.141.1 · pydantic 2.13.5
```

### 2.2 单元测试（15/15 通过）

```
$ .venv/bin/python -m pytest tests/unit/ -v
tests/unit/test_config.py::TestLoadExample::test_example_config_loads PASSED
tests/unit/test_config.py::TestLoadExample::test_default_config_when_file_missing PASSED
tests/unit/test_config.py::TestLoadExample::test_empty_file_loads_defaults PASSED
tests/unit/test_config.py::TestCrossReferences::test_resource_ref_unknown_provider PASSED
tests/unit/test_config.py::TestCrossReferences::test_resource_ref_unknown_key PASSED
tests/unit/test_config.py::TestCrossReferences::test_resource_key_provider_mismatch PASSED
tests/unit/test_config.py::TestCrossReferences::test_duplicate_provider_id PASSED
tests/unit/test_config.py::TestValueBounds::test_endpoint_invalid PASSED
tests/unit/test_config.py::TestValueBounds::test_budget_lt_attempt_timeout PASSED
tests/unit/test_config.py::TestValueBounds::test_x_zero_rejected PASSED
tests/unit/test_config.py::TestValueBounds::test_port_out_of_range PASSED
tests/unit/test_config.py::TestReasoningRules::test_images_resource_reasoning_ignored_with_warning PASSED
tests/unit/test_config.py::TestReasoningRules::test_chat_resource_reasoning_kept PASSED
tests/unit/test_config.py::TestAtomicWrite::test_save_and_reload_roundtrip PASSED
tests/unit/test_config.py::TestAtomicWrite::test_save_leaves_no_tmp_files PASSED
============================== 15 passed in 0.07s ==============================
```

### 2.3 /health 实测（样例配置 data/config.yaml）

```
$ cp config.example.yaml data/config.yaml && .venv/bin/python -m model_gateway.main &
$ curl -s http://127.0.0.1:8300/health
{
    "status": "ok",
    "version": "0.1.0",
    "config": { "path": "data/config.yaml", "file_loaded": true, "warnings": [] },
    "gateway": { "host": "0.0.0.0", "port": 8300,
                 "attempt_timeout_seconds": 60,          ← 终审值
                 "request_total_budget_seconds": 300 },   ← 终审值
    "scheduling": { "max_active_per_model": 2, "fail_threshold": 2, "retry_per_request": 3 },
    "providers": 2, "system_models": 2, "access_tokens": 2
}
```

### 2.4 负例：坏配置拒绝启动（校验失败指明位置）

```
$ # 将资源 provider 改为 openrouter（不存在的 provider）后启动：
$ .venv/bin/python -m model_gateway.main
配置校验失败，拒绝启动：
  - data/config.yaml → (root): Value error, models[0]('deepseek-v4-flash').resources[0]: 引用不存在的 provider 'openrouter'
exit=2
$ # 恢复配置后重启：status ok | file_loaded True | providers 2 | models 2 ✓
```

## 3. 任务 2 状态：SHELL（阻塞）

`SENSENOVA_API_KEY` 环境变量未设置，商汤双端点实测无法执行。
待用户设置后运行：`export SENSENOVA_API_KEY=sk-xxx && .venv/bin/python scripts/sensenova_probe.py`
脚本就绪（清单将落盘 `docs/changes/sensenova-models-{A,B}.json`，判定表以最小 chat 调用为主判据）。

## 4. 未实现（防虚报）

调度/出站/统计/鉴权主体均未实现（M1 任务 3-9）；本记录仅覆盖任务 1 脚手架范围。
