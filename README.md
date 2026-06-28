# tokenkeeper-ai

tokenkeeper-ai 是一个 AI 调用用量和成本记账工具。它可以统计受支持 SDK、回调、HTTP proxy、手动上报，以及 Hermes 本地状态库里的调用记录。

当前版本：`0.4.0`

PyPI：<https://pypi.org/project/tokenkeeper-ai/>

## 先说清楚边界

tokenkeeper 不是系统级流量监听器，也不是“安装后自动统计所有 agent”的工具。

安装 `tokenkeeper-ai` 只代表机器上有这个包。要产生统计数据，必须接入下面某一种路径：

| 接入路径 | 当前状态 | 用量从哪里来 |
| --- | --- | --- |
| OpenAI Python SDK | 已验证 | 同一 Python 进程内 `guard.install()` patch SDK 调用 |
| OpenAI-compatible provider | 已验证 | 通过 OpenAI Python SDK 调用，并且 provider 返回 OpenAI 风格 `usage` |
| Anthropic Python SDK | 已验证 | 同一 Python 进程内 patch Anthropic messages 调用 |
| LangChain callback | 已验证 | 显式挂载 `TokenKeeperCallbackHandler` |
| 外部 agent HTTP proxy | 已验证测试路径 | agent 必须能把 `base_url` 指向本地 tokenkeeper proxy |
| 手动 HTTP record | 已验证 | 任意语言主动 `POST /tokenkeeper/record` 上报用量 |
| Hermes 本地状态库同步 | 已验证测试库结构 | Hermes 必须已经把 session/token 写入本地 `state.db` |
| Dashboard | 已验证 | 读取指定的 tokenkeeper ledger DB |

详细验收矩阵见 [`docs/CAPTURE_MATRIX.md`](docs/CAPTURE_MATRIX.md)。

## 不能做到什么

tokenkeeper 不能静默统计所有模型、所有 agent、所有语言、所有桌面应用。

这些场景不能自动统计：

- SaaS agent 不暴露用量，也不能配置回调或上报；
- 私有二进制、桌面应用、Node/Rust/Go 进程不能配置 proxy，也不能主动上报；
- HTTPS 请求没有显式走 tokenkeeper proxy；
- provider 不返回 usage，此时只能记录 0 token/0 cost 或依赖手动上报；
- Hermes 没有把某次调用写入 `state.db`；
- 用户只安装了包，但没有运行 `connect hermes`、没有配置 proxy、没有 `guard.install()`。

因此，Codex、ChatGPT、Cursor、Hermes 或其他 agent 不会因为你安装了 tokenkeeper 就自动被统计。必须有明确接入点。

## 安装

核心包：

```bash
pip install -U tokenkeeper-ai==0.4.0
```

Dashboard 和 Hermes 本地同步需要 dashboard extra：

```bash
pip install -U "tokenkeeper-ai[dashboard]==0.4.0"
```

包含常用可选依赖：

```bash
pip install -U "tokenkeeper-ai[all]==0.4.0"
```

确认版本：

```bash
tokenkeeper version
```

应该输出：

```text
tokenkeeper 0.4.0
```

## 按场景接入

### 1. Python 代码里使用 OpenAI/Anthropic SDK

适用场景：你的 Python 进程直接调用 OpenAI、OpenAI-compatible provider 或 Anthropic SDK。

```python
from tokenkeeper import guard

guard.install(
    db_path="./tokenkeeper.db",
    project="my-app",
    user="alice",
)
```

之后，同一 Python 进程内受支持的 SDK 调用会被记录。

限制：

- 只影响当前 Python 进程；
- 不会 patch 其他进程；
- 不会 patch Rust/Node/Go 写的桌面应用；
- provider 不返回 usage 时，token/cost 可能是 0。

### 2. Hermes Desktop 本地状态库同步

适用场景：你想把 Hermes 本地 `state.db` 里的会话用量同步进 tokenkeeper，并在 Dashboard 看。

先诊断：

```bash
tokenkeeper doctor --target hermes --db ./tokenkeeper.db --port 8502
```

启动 Hermes 同步和 Dashboard：

```bash
tokenkeeper connect hermes --db ./tokenkeeper.db --port 8502 --since now
```

如果 Hermes 的 `state.db` 不在默认路径，显式指定：

```bash
tokenkeeper connect hermes --hermes-db "C:\path\to\state.db" --db ./tokenkeeper.db --port 8502 --since now
```

这里的真实含义：

- `--since now` 只同步命令启动后 Hermes 写入的记录；
- 如果要导入历史可读记录，不要传 `--since now`；
- Dashboard 读取的是 `--db` 指定的 tokenkeeper DB；
- Hermes 必须真的把用量写进 `state.db`，否则 tokenkeeper 没有数据可同步；
- 这是本地数据库同步，不是实时网络拦截。

### 3. 外部 agent 走本地 HTTP proxy

适用场景：agent 可以配置 OpenAI-compatible `base_url`。

先诊断：

```bash
tokenkeeper doctor --target proxy --db ./tokenkeeper.db --port 8502
```

启动 proxy 和 Dashboard：

```bash
tokenkeeper connect proxy --upstream https://api.deepseek.com/v1 --listen 127.0.0.1:8787 --db ./tokenkeeper.db --project default --user default --dashboard --port 8502
```

把 agent 的 OpenAI-compatible `base_url` 改成：

```text
http://127.0.0.1:8787/v1
```

底层 proxy 命令也可以单独运行：

```bash
tokenkeeper proxy --upstream https://api.deepseek.com/v1 --listen 127.0.0.1:8787 --db ./tokenkeeper.db --project default --user default
```

已验证的 proxy 路径：

| Endpoint | 行为 |
| --- | --- |
| `POST /v1/chat/completions` | OpenAI-compatible 非流式和 SSE 流式 |
| `POST /chat/completions` | 不带 `/v1` 前缀的 OpenAI-compatible chat completions |
| `POST /v1/messages` | Anthropic messages 非流式 |
| `GET /tokenkeeper/health` | 健康检查，不写账本 |
| `POST /tokenkeeper/record` | 手动上报用量 |

鉴权说明：

- 默认转发客户端传进来的 auth header；
- 可用 `--upstream-auth-env` 和 `--upstream-auth-header` 让 proxy 从环境变量注入上游 API key；
- tokenkeeper 不打印、不持久化 API key。

预算参数：

```bash
--daily-limit-usd 10 --monthly-limit-usd 200 --per-call-limit-usd 1 --budget-action warn
```

如果使用 `--budget-action block`，超限时 proxy 会返回 HTTP 429，并且不会调用上游。

### 4. 手动 HTTP 记账

适用场景：任意语言或 agent 能主动上报用量。

```bash
curl -X POST http://127.0.0.1:8787/tokenkeeper/record -H "Content-Type: application/json" -d "{\"model\":\"custom-model\",\"provider\":\"manual\",\"prompt_tokens\":100,\"completion_tokens\":40,\"latency_ms\":1200,\"status\":\"success\"}"
```

手动 record 是最明确的兜底方式，但前提是调用方知道或能估算 token 用量。

## Dashboard

直接启动：

```bash
tokenkeeper dashboard --port 8502 --db ./tokenkeeper.db
```

Dashboard 展示：

- 总成本；
- 调用次数；
- Top 烧钱模型；
- 最近调用；
- 预算状态；
- 当前 DB 路径；
- Hermes 同步状态。

如果 Dashboard 没有数据，按这个顺序查：

1. 调用记录是否写入了 Dashboard 正在读的同一个 `--db`；
2. Hermes 是否真的写入了 `state.db`；
3. agent 是否真的把请求路由到了 tokenkeeper proxy；
4. provider 是否返回了 usage；
5. 模型是否在价格表里，或者是否需要手动上报 cost。

## 命令行

| 命令 | 用途 |
| --- | --- |
| `tokenkeeper version` | 查看版本 |
| `tokenkeeper info` | 查看运行时信息 |
| `tokenkeeper doctor` | 检查安装、DB、Hermes、proxy、dashboard 是否可用 |
| `tokenkeeper connect hermes` | 同步 Hermes 本地 `state.db` 并启动 Dashboard |
| `tokenkeeper connect proxy` | 启动记账 proxy，可选启动 Dashboard |
| `tokenkeeper dashboard` | 启动 Dashboard |
| `tokenkeeper proxy` | 启动底层 HTTP proxy |

## 数据和隐私

默认调用记录写入本地 SQLite，例如 `./tokenkeeper.db`。核心 ledger 不上传数据。

只有启用这些显式功能时才会发生对应网络请求：

- 使用 `tokenkeeper proxy` 转发模型请求；
- 配置 webhook/alerting；
- 你自己的服务主动调用 `/tokenkeeper/record`。

## 常见问题

### 安装后会自动接入 Hermes 吗？

不会。安装只是在机器上安装 Python 包。Hermes 要运行：

```bash
tokenkeeper connect hermes --db ./tokenkeeper.db --port 8502 --since now
```

### 能自动统计我当前 Codex 或 ChatGPT 的对话吗？

不能，除非这个应用满足其中之一：

- 请求能走 tokenkeeper proxy；
- 使用了受支持 SDK/callback；
- 写入了 tokenkeeper 支持读取的本地状态库；
- 主动上报 record。

否则 tokenkeeper 不能静默看到它的用量。

### Hermes 的用量可以统计吗？

可以，但前提是 Hermes 把会话和 token 用量写入了本地 `state.db`，并且字段结构符合当前已测试形态。

不能保证统计：

- Hermes 未落盘的调用；
- Hermes 没写 usage 字段的调用；
- tokenkeeper 指向了错误的 `state.db`；
- Dashboard 指向了错误的 tokenkeeper DB。

### 为什么 Hermes 最新调用没出现在 Dashboard？

常见原因：

- Hermes 没把那次调用写进 `state.db`；
- `--since now` 过滤掉了旧记录；
- tokenkeeper 读取的是另一个 `state.db`；
- Dashboard 读取的是另一个 `tokenkeeper.db`；
- provider/model 没有可用 usage 或价格。

### 外部 Node/Rust/桌面 agent 能统计吗？

能，但必须满足至少一个条件：

- 能配置 `base_url` 到 `http://127.0.0.1:8787/v1`；
- 能主动 `POST /tokenkeeper/record`；
- 有 tokenkeeper 已支持的本地状态库同步。

如果不能路由、不能 callback、不能上报、也没有可读状态库，就不能自动统计。

### 这么多限制还有没有实用意义？

有，但实用范围是明确的：

- 自己控制的 Python AI 应用；
- LangChain 应用；
- 能配置 `base_url` 的外部 agent；
- Hermes 本地状态库同步；
- 能主动上报 usage 的脚本或服务。

它不是通用的系统级 AI 用量表。

## 0.4.0 验证记录

`0.4.0` 发布前已运行：

```bash
python -m compileall -q tokenkeeper tests scripts
python -m pytest tests/ -v --tb=short --cov=tokenkeeper --cov-report=term-missing
python scripts/validate_pricing.py
python -m build
python -m mypy tokenkeeper
git diff --check
```

也从临时虚拟环境验证过 PyPI 安装：

```bash
pip install --no-cache-dir tokenkeeper-ai==0.4.0
python -m tokenkeeper.cli version
python -m tokenkeeper.cli connect --help
python -m tokenkeeper.cli doctor --help
```

## License

MIT
