
> 🔴 **术语读法（2026-10-04 定版）**：本文规范性正文已统一到 **厂商 = 模型生产公司 / 供应商 = 接入方（「接入模型资源」每个 Key 接入 + 「接入账号资源」每个产品账号）/ 网关模型 = 把各供应商的同一厂商模型标准化成一个名字并统一规格（旧称「系统模型」作废、同义）/ 资源 = 供应商名下一条可调用模型接入**。版本史段落（`> vN（…）`、变更表 `| v… |`）、Q## 归档条目原文与用户原话引号内**保留当时措辞**（存证不改写），其中指接入方的「厂商」一律按**供应商**读、「系统模型」按**网关模型**读；定义源 = 需求文档 PRD §2「术语与核心概念」，执行细则 = 项目规则 `mg-terminology`。🔴 另注：`resources[].vendor` 这个字段名承载的是**供应商名称**（历史命名，不改字段以免打断实盘配置），内置目录的 `vendor` 字段承载的才是**厂商**（生产公司）——同名字段两种语义，判身份看它在哪一层。
<p align="right"><strong>English</strong> · <a href="./README.zh-CN.md">简体中文</a></p>

<p align="center">
  <img src="./assets/readme/hero-en.svg" width="100%"
       alt="Model-Gateway pools LLM resources from multiple suppliers into one local gateway that serves Trae, Cursor and Cherry Studio through a single OpenAI-compatible endpoint.">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-Apache--2.0-171b22" alt="License: Apache-2.0">
  <img src="https://img.shields.io/badge/python-3.12%2B-171b22" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/tests-2050%2F2050-188038" alt="Tests: 2050/2050">
  <img src="https://img.shields.io/badge/runtime-100%25%20local-188038" alt="100% local runtime">
</p>

**Model-Gateway** is a local-first LLM gateway for individual developers. It pools every supplier key you own — multiple suppliers, multiple accounts, API keys and subscription plans — behind **one OpenAI-compatible endpoint**, and keeps calls alive with automatic retry, failover and resume.

Point Trae, Cursor, Cherry Studio or any OpenAI-compatible client at `http://127.0.0.1:8300/v1` once. From then on, add, swap or drain supplier keys behind the gateway without ever touching your tools again.

## Why

- **Key sprawl.** Every tool × every supplier × every key is another line of config you re-type and re-audit. The gateway is the only endpoint your tools ever see.
- **Single points of failure.** A rate-limited or flaky key usually kills the whole session. Here, failures are classified, retried, and — when a resource is exhausted — the request **switches to another resource and continues** mid-task.
- **Opaque consumption.** Every call lands in a plain-text event log with tokens, latency and cost estimates, surfaced in a built-in dashboard.

## Features

| Area | What you get |
| --- | --- |
| Unified inbound API | `/v1/chat/completions` (streaming + non-streaming), `/v1/images/generations`, `/v1/messages` (native Anthropic, bidirectional conversion), `/v1/models` |
| Outbound adapters | OpenAI-compatible, Anthropic and Gemini protocol families |
| Scheduling | `x`/`y`/`m` concurrency-aware routing (see below) |
| Failover-continue | When retries are exhausted, the same request resumes on the next available resource — tools never see the error as long as one resource works |
| Streaming safety | 15s SSE heartbeat; pre-first-token failures switch invisibly; after partial output, received content and errors are passed through verbatim instead of being swallowed; client cancellations propagate upstream |
| Reasoning params | Three-level merge: request-level > resource-level default > producer builtin (chat only) |
| Web console | Overview, model resources, gateway models, dashboard, request logs, API access and settings, plus a templates page (built-in UI reference template gallery) — light / dark / system themes |
| Plain-text data | YAML config, JSONL event streams, no database, no binary blobs |
| Access tokens | Multiple named tokens for `/v1/*`, one per tool, individually revocable |

## How scheduling works

The gateway routes each gateway model over an ordered pool of resources. Three global knobs control everything:

| Knob | Default | Meaning |
| --- | --- | --- |
| `x` — active set | 2 | At most *x* resources serve traffic at once. Requests go to the resource with the fewest in-flight requests (ties break by priority). A failed member is replaced by the next standby. |
| `y` — fail threshold | 2 | *y* consecutive failures (counted across requests) cool a resource down and trigger an immediate switch. |
| `m` — retry limit | 3 | Up to *m* retries on the same resource per request; exhaustion triggers failover-continue. |

Additional guards: each upstream attempt times out after 60s; failed-switch budgets are capped at 300s per request; cooled resources recover automatically (60s for API mode, aligned to the 5h rolling window for plan mode).

## Quick start

> Requires Python 3.12+.

```bash
git clone https://github.com/1179053284/AI-Gateway.git
cd AI-Gateway
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .

mkdir -p data
cp config.example.yaml data/config.yaml
# edit data/config.yaml: add one supplier key to get started

python -m model_gateway.main
```

The web console opens at `http://127.0.0.1:8300`. Create an access token on the **API Access** page (or keep the sample one), then:

```bash
curl http://127.0.0.1:8300/v1/chat/completions \
  -H "Authorization: Bearer mg-xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

To connect a tool, set its OpenAI-compatible base URL to `http://127.0.0.1:8300/v1` and use the access token as the API key. On macOS you can also start the gateway by double-clicking `启动网关.command`.

## CLI (`mgw`)

Installing with `pip install -e .` also installs a `mgw` command. If `mgw` is not on your `PATH`, use the equivalent `python -m model_gateway.cli …` form.

```bash
mgw --help

# Probe how an upstream actually accepts reasoning levels (S1 → S2 → S3)
mgw probe --model <name>            # --all to re-probe everything

# Write the gateway's models into a tool's local config file (file-based path)
mgw setup workbuddy --dry-run       # print target dir + plan first
mgw setup workbuddy                 # backup → merge → atomic write → verify

# ZCode account management
mgw zcode list                      # list accounts + device ids
mgw zcode import <creds.json>       # import a locally signed-in account
mgw zcode launch <account> --dry-run
mgw zcode claim                     # claim / check-in (batch)
mgw zcode remove <account>          # delete that account's local data root
```

Notes:

- **Log in to the tool first, then point it at the gateway** (PRD Q25-⑩).
  A tool's own account system is the first gate for supplier access: this gateway never
  logs in on your behalf and does not manage tool login state — `mgw setup` only writes
  config files. Sign in inside the tool first, then run `mgw setup`.
- `mgw setup` writes into **another tool's data directory**. It prints the resolved target
  directory and its source (env var / `dataFolderName`) and asks for confirmation;
  use `--yes` in non-interactive contexts and `--dry-run` to inspect only.
- `mgw zcode remove` is destructive and follows the same rule: it prints the exact path
  first, then asks; `--yes` is required when there is no TTY.
- `mgw zcode` defaults to `data/upstream/zcode/accounts`; override with `MGW_ZCODE_ACCOUNTS`.
- `mgw zcode claim` exit codes: `0` all normal · `1` some account failed ·
  `2` no account participated · `3` **the global risk-control circuit breaker is open, so this
  round never reached upstream** (failures shown alongside are "failed before sending"; the
  verdict is still `3`). Note `3` means something different for `mgw setup` (write failed) —
  read exit codes per subcommand, and see `mgw zcode claim --help`.
- A breaker has **two causes with completely different handling** — don't merge them.
  If the state file **reads fine**, the cooldown expires on its own and both the UI and the CLI
  print the recovery time. If the state file **cannot be read** (corrupt value, wrong type,
  duplicate JSON keys) every round is **refused**, and it will **not** recover by itself —
  only deleting that file releases later claims, and the CLI prints its exact absolute path.
  The refused case is recorded as `failed` (not a normal business state), so the header alert
  dot lights up. The gateway never treats "cannot read" as "no breaker" and lets traffic through.
- Auto claim/check-in must pass Aliyun's invisible captcha (§16.5) and has a **hard dependency on
  a residential proxy**: set `gateway.zcode.proxy` in `config.yaml` (or `MGW_ZCODE_PROXY`), and
  install the solver with `pip install "model-gateway[captcha]" && python -m playwright install
  chromium`. Without it the claim fails loudly with guidance — or use `mgw zcode claim --manual`.
- `GET /v1/models` (and `mgw setup`) only publish models that are actually **servable** —
  at least one enabled, non-invalid resource mapping. Hidden models are reported as a
  banner on the dashboard, never silently dropped.

## Configuration

Everything lives in one plain-text file, `data/config.yaml` (git-ignored). The essentials:

```yaml
scheduling:
  max_active_per_model: 2   # x — active set size
  fail_threshold: 2         # y — consecutive-failure threshold
  retry_per_request: 3      # m — retries per resource per request

resources:                  # one entry per supplier + key
  - id: res-xxxxxxxx        # auto-generated
    name: SenseNova · main
    preset: sensenova-api    # sensenova-api | sensenova-tokenplan | custom
    access_mode: api         # api | plan
    protocol: openai         # openai | anthropic | gemini
    base_url: https://api.sensenova.cn/compatible-mode/v2
    api_key: sk-xxxxxxxx
    enabled: true

models:                      # gateway models exposed to your tools
  - name: deepseek-v4-flash
    endpoint: chat            # chat | images
    resources:                # ordered = priority
      - resource: res-xxxxxxxx
        model: deepseek-v4-flash
```

Supplier presets pre-fill protocol and endpoints (SenseNova ships both `api` and `tokenplan` presets); any custom OpenAI-compatible endpoint works with `preset: ""`. See [`config.example.yaml`](./config.example.yaml) for every field.

## Design principles

- **Plaintext everywhere.** Config, model enums, event streams and logs are local, readable files. No database.
- **Purely local.** No telemetry, no remote configuration, no auto-update, no external calls except to the suppliers you configure.
- **Keys stay on your machine.** Credentials live only in the local config file (git-ignored); they are never hardcoded or sent anywhere else.
- **Single user.** No accounts or login. The admin console is unauthenticated by design — run it on your own machine; `/v1/*` calls are protected by access tokens.

## Status & roadmap

> **Note:** This project is under continuous development and provided for personal research use only. The feature set is still simple — it primarily targets the maintainer's own use cases. Ideas and feedback are welcome in [Issues](https://github.com/1179053284/AI-Gateway/issues).

Current version: **v0.2.0** — matches `mgw --version` and `pyproject.toml`. Test suite: **2050 passed / 3 skipped**（= 本提交树收集 2053 条减 3 条 skip） as of 2026-10-05; reproduce with `.venv/bin/python -m pytest -q` (a `test_v2_readme_claims.py` guard fails if this number drifts from reality). Live-provider calls are verified for the OpenAI path; ZCode / Anthropic-path items that need real credentials remain **not yet verified**.

Planned next:

- [ ] Environment-variable references for keys (`${PROVIDER_API_KEY}`)
- [ ] Plan-quota awareness for subscription resources
- [ ] Native Gemini inbound endpoint

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

[Apache-2.0](./LICENSE)
