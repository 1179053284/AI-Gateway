<p align="right"><a href="./README.md">English</a> · <strong>简体中文</strong></p>

<p align="center">
  <img src="./assets/readme/hero-zh.svg" width="100%"
       alt="Model-Gateway 将多个厂商资源聚合为一个本地网关，通过统一的 OpenAI 兼容端点服务 Trae、Cursor 与 Cherry Studio。">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-Apache--2.0-171b22" alt="协议：Apache-2.0">
  <img src="https://img.shields.io/badge/python-3.12%2B-171b22" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/tests-199%2F199-188038" alt="测试：199/199">
  <img src="https://img.shields.io/badge/runtime-100%25%20local-188038" alt="100% 本地运行">
</p>

**Model-Gateway** 是一个面向个人开发者的本地优先 LLM 网关。它把你手里的每一个厂商 Key —— 多厂商、多账号、按量 API 与订阅套餐 —— 聚合到**一个 OpenAI 兼容端点**之后，并用自动重试、故障切换与续跑保证调用不中断。

只需把 Trae、Cursor、Cherry Studio 或任何 OpenAI 兼容客户端指向 `http://127.0.0.1:8300/v1` 一次。此后在网关背后新增、更换、下线厂商 Key，都不必再动工具端的任何配置。

## 为什么需要它

- **Key 太散。** 每个工具 × 每个厂商 × 每个 Key，都是要反复填写、反复核对的一行配置。有了网关，工具端永远只需要看到这一个端点。
- **单点故障。** 限流或抖动的 Key 通常会断掉整个会话。在这里，失败会被分类、重试，资源耗尽时请求**切换到其他资源并继续执行**——只要还有一个可用资源，工具端就不会收到报错。
- **消耗黑盒。** 每次调用都落在明文事件流水里，带 token 数、延迟与费用估算，内置看板直接呈现。

## 功能

| 领域 | 内容 |
| --- | --- |
| 统一入站 API | `/v1/chat/completions`（流式 + 非流式）、`/v1/images/generations`、`/v1/messages`（Anthropic 原生，双向转换）、`/v1/models` |
| 出站适配 | OpenAI 兼容、Anthropic、Gemini 三大协议族 |
| 调度 | `x`/`y`/`m` 并发感知路由（见下文） |
| 切换续跑 | 重试耗尽后，同一请求自动换到下一个可用资源继续执行——只要有可用资源，工具端无感 |
| 流式安全 | 15s SSE 心跳；首 token 前的失败无感切换；已输出部分内容后失败，把收到的内容与错误原样透传，不吞内容；客户端主动取消会透传到上游 |
| 推理参数 | 三级合并：请求级 > 资源级默认 > 厂商内置（仅 chat） |
| Web 控制台 | 总览、资源管理、系统模型、数据看板、请求日志、API 接入、系统设置——浅色 / 深色 / 跟随系统三主题 |
| 全明文数据 | YAML 配置、JSONL 事件流水，无数据库、无二进制格式 |
| 访问令牌 | `/v1/*` 支持多枚命名令牌，一工具一枚，可单独启停 |

## 调度是怎么工作的

网关为每个系统模型维护一个有序资源池，三个全局参数决定一切：

| 参数 | 默认 | 含义 |
| --- | --- | --- |
| `x` — 生效集 | 2 | 最多 *x* 个资源同时承接流量。请求路由到在途请求最少的资源（平局取优先级高者）；成员故障时由待命资源补位。 |
| `y` — 失败阈值 | 2 | 连续失败 *y* 次（跨请求累计）即冷却该资源并立即切换。 |
| `m` — 重试上限 | 3 | 单请求对同一资源最多重试 *m* 次；耗尽即切换续跑。 |

其他护栏：单次上游尝试超时 60s；失败重试切换总预算每请求 300s；冷却资源到期自动恢复（API 模式 60s，Plan 模式对齐 5 小时滚动窗口）。

## 快速开始

> 需要 Python 3.12+。

```bash
git clone https://github.com/<your-username>/model-gateway.git
cd model-gateway
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .

mkdir -p data
cp config.example.yaml data/config.yaml
# 编辑 data/config.yaml：先填一个厂商 Key 即可跑通

python -m model_gateway.main
```

Web 控制台地址：`http://127.0.0.1:8300`。在**API 接入**页创建访问令牌（或沿用样例），然后：

```bash
curl http://127.0.0.1:8300/v1/chat/completions \
  -H "Authorization: Bearer mg-xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "你好！"}]
  }'
```

接入工具时，把 OpenAI 兼容 base URL 填为 `http://127.0.0.1:8300/v1`，API Key 填访问令牌即可。macOS 上也可以直接双击 `启动网关.command` 启动。

## 配置

所有配置都在一个明文文件里：`data/config.yaml`（已被 git 忽略）。核心结构：

```yaml
scheduling:
  max_active_per_model: 2   # x — 生效集大小
  fail_threshold: 2         # y — 连续失败阈值
  retry_per_request: 3      # m — 单请求单资源重试上限

resources:                  # 每条 = 厂商 + Key
  - id: res-xxxxxxxx        # 系统自动生成
    name: 商汤 · 主Key
    preset: sensenova-api    # sensenova-api | sensenova-tokenplan | 自定义留空
    access_mode: api         # api | plan
    protocol: openai         # openai | anthropic | gemini
    base_url: https://api.sensenova.cn/compatible-mode/v2
    api_key: sk-xxxxxxxx
    enabled: true

models:                      # 对工具端暴露的系统模型
  - name: deepseek-v4-flash
    endpoint: chat            # chat | images
    resources:                # 有序 = 优先级
      - resource: res-xxxxxxxx
        model: deepseek-v4-flash
```

厂商预设会自动填好协议与端点（商汤内置 `api` 与 `tokenplan` 两套预设）；任何自定义 OpenAI 兼容端点用 `preset: ""` 接入。完整字段见 [`config.example.yaml`](./config.example.yaml)。

## 设计立场

- **全明文。** 配置、模型枚举、事件流水与日志都是本地可读文件，没有数据库。
- **纯本地。** 无遥测、无远程配置、无自动更新；除你配置的厂商外，不向任何外部发送请求。
- **密钥不出本机。** 凭据只存本地配置文件（git 忽略），绝不硬编码、绝不上传。
- **单用户。** 无注册无登录，管理界面按本机自用设计为免鉴权——请只在自己的设备上运行；`/v1/*` 调用由访问令牌保护。

## 状态与路线图

当前版本：**v0.1.0** —— 199/199 测试通过，并经过真实厂商调用验证。

接下来计划：

- [ ] Key 支持环境变量引用（`${PROVIDER_API_KEY}`）
- [ ] 订阅（Plan）资源的额度感知
- [ ] Gemini 原生入站端点

## 开发

```bash
pip install -e ".[dev]"
pytest
```

## 协议

[Apache-2.0](./LICENSE)
