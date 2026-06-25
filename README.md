# tokenkeeper

<div align="center">

**AI API 成本监控与限流守护者**

让任何 AI 应用开发者自动获得 token 统计、成本追踪、预算限额与熔断保护

[![PyPI version](https://img.shields.io/pypi/v/tokenkeeper)](https://pypi.org/project/tokenkeeper/)
[![Python](https://img.shields.io/pypi/pyversions/tokenkeeper)](https://pypi.org/project/tokenkeeper/)
[![CI](https://github.com/wzwailr/tokenkeeper/actions/workflows/tests.yml/badge.svg)](https://github.com/wzwailr/tokenkeeper/actions/workflows/tests.yml)
[![License](https://img.shields.io/pypi/l/tokenkeeper)](https://github.com/wzwailr/tokenkeeper/blob/master/LICENSE)

</div>

---

## 目次

- [它解决什么问题](#-它解决什么问题)
- [30 秒接入](#-30-秒接入)
- [功能特性](#-功能特性)
- [安装](#-安装)
- [快速开始](#-快速开始)
- [国产模型](#-国产模型openai-兼容协议)
- [预算管理](#️-预算管理)
- [流式调用](#-流式调用)
- [看板](#-看板-streamlit)
- [命令行](#-命令行)
- [手动记账](#-手动记账sdk-不自动拦截)
- [自定义模型价格](#️-自定义模型价格)
- [数据导出](#-数据导出)
- [API 参考](#-api-参考)
- [常见问题](#-常见问题)
- [故障排查](#️-故障排查)
- [开发](#-开发)
- [License](#-license)

---

## 🎯 它解决什么问题

| 痛点 | 解决方案 |
|------|---------|
| ❌ 不知道 AI 调用花了多少钱 | ✅ 自动按模型价格表计费，`$` / `¥` 双币种 |
| ❌ Agent 失控循环一下烧了几百美元 | ✅ 超预算自动熔断（`BudgetExceededError`） |
| ❌ 团队预算没法分摊、没法预警 | ✅ project / user 双维度拆分，看板实时监控 |

---

## 🚀 30 秒接入

```python
# 1. 安装
pip install tokenkeeper

# 2. 在你的 AI 应用入口加 3 行
from tokenkeeper import guard

guard.install(project="my-ai-app")
guard.set_budget(daily_limit_usd=10.0, action="block")  # 超 $10/天自动停

# 3. 业务代码 0 改动
import openai
client = openai.OpenAI()          # 你的原有代码
resp = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
)
# ↑ 这一行就被自动记账 + 限额检查
```

**就这么多。** 不需要改任何业务逻辑。

---

## ✨ 功能特性

- **零侵入** — monkey-patch OpenAI/Anthropic SDK，业务代码零改动
- **自动计费** — 内置 43 个模型价格表（OpenAI / Anthropic / DeepSeek / 阿里 / 智谱 / 百度 / 月之暗面 / 零一万物 / minimax），支持 $ / ¥ 双币种
- **预算熔断** — 每日 / 每月 / 单项目 / 单用户限额，超限 block 或 warn
- **流式支持** — OpenAI/Anthropic 流式调用自动记账
- **本地优先** — SQLite 本地存储，数据不出机器
- **看板** — Streamlit 实时仪表盘（KPI + 趋势图 + Top 烧钱模型）
- **错误健壮** — 网络重试、降级模式、错误隔离，patch 失败不影响原 SDK

---

## 📦 安装

```bash
# 基础安装（只看核心功能）
pip install tokenkeeper

# 带看板
pip install "tokenkeeper[dashboard]"

# 带 OpenAI 集成（通常你已装了 openai）
pip install "tokenkeeper[openai]"

# 带 Anthropic 集成
pip install "tokenkeeper[anthropic]"

# 一键装齐
pip install "tokenkeeper[all]"

# 开发模式（从源码）
git clone https://github.com/wzwailr/tokenkeeper.git
cd tokenkeeper
pip install -e ".[all]"
```

---

## 🚀 快速开始

### 基础用法

```python
from tokenkeeper import guard

guard.install(project="my-app", user="alice")
guard.set_budget(daily_limit_usd=5.0, action="block")

import openai
client = openai.OpenAI()
resp = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
)
print(resp.choices[0].message.content)
# 同时写入 SQLite：model / tokens / cost / latency
```

### 捕获超限

```python
from tokenkeeper import guard, BudgetExceededError

guard.install(project="my-app")
guard.set_budget(daily_limit_usd=1.0, action="block")

try:
    resp = client.chat.completions.create(model="gpt-4o", messages=[...])
except BudgetExceededError as e:
    print(f"预算超限: {e}")
    # 降级到更便宜的模型 / 暂停 / 通知用户
```

---

## 🇨🇳 国产模型（OpenAI 兼容协议）

任何 OpenAI 兼容服务都自动支持——**只需改 `base_url`**：

```python
# DeepSeek
client = openai.OpenAI(
    api_key="sk-***",
    base_url="https://api.deepseek.com/v1",
)

# 阿里通义千问
client = openai.OpenAI(
    api_key="sk-***",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# 月之暗面 Kimi
client = openai.OpenAI(
    api_key="sk-***",
    base_url="https://api.moonshot.cn/v1",
)

# minimax
client = openai.OpenAI(
    api_key="sk-cp-***",
    base_url="https://api.minimaxi.com/v1",
)
```

内置价格表已覆盖 43 个模型。未识别的模型 `cost_usd=0`，可通过 `register_custom_pricing()` 补录。

---

## 🛡️ 预算管理

### 三种粒度

```python
# 全局预算
guard.set_budget(
    daily_limit_usd=10.0,
    monthly_limit_usd=200.0,
    per_call_limit_usd=1.0,
    action="block",
)

# 单项目预算
guard.set_budget(
    scope="project",
    scope_key="my-app",
    daily_limit_usd=5.0,
    action="block",
)

# 单用户预算
guard.set_budget(
    scope="user",
    scope_key="alice",
    daily_limit_usd=2.0,
    action="block",
)
```

### 两种动作

| action | 行为 |
|--------|------|
| `"warn"` | 超限只记日志，调用继续 |
| `"block"` | 超限抛 `BudgetExceededError` |

---

## 🌊 流式调用

OpenAI 和 Anthropic 流式调用自动记账——**无需额外配置**：

```python
# OpenAI 流式
stream = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello"}],
    stream=True,
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
# ↑ 流结束后自动记账

# Anthropic 流式
import anthropic
client = anthropic.Anthropic()
with client.messages.stream(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}],
) as stream:
    for text in stream.text_stream:
        print(text, end="")
# ↑ 同样自动记账
```

**工作原理**：tokenkeeper 劫持 `chat.completions.create` / `messages.create`，在调用完成后提取 `usage`，计算成本，写入 ledger。流式调用对上层代码完全透明。

---

## 📊 看板（Streamlit）

```bash
tokenkeeper dashboard
# 打开 http://localhost:8501
```

看板功能：
- 💰 KPI 卡片：总成本 / 调用次数 / 平均成本 / 错误率
- 📈 每日趋势图
- 🏆 Top 烧钱模型
- 📋 最近调用列表（可筛选、导出 CSV）

自定义端口和 DB：

```bash
tokenkeeper dashboard --port 8888 --db /path/to/db.sqlite
```

---

## 🔌 命令行

```bash
tokenkeeper version          # 显示版本
tokenkeeper info             # 运行时信息（已加载模型数、价格表日期）
tokenkeeper dashboard        # 启动看板（默认 8501）
tokenkeeper dashboard --port 8888 --db /path/to/db.sqlite
```

---

## 🧪 手动记账（SDK 不自动拦截）

如果你用非 OpenAI/Anthropic SDK 或自建调用，可以手动调用 `guard.record()`：

```python
from tokenkeeper import guard

guard.install(project="my-app")

# 任何 LLM 调用后，手动记一笔
guard.record(
    model="custom-llm",
    prompt_tokens=1000,
    completion_tokens=500,
    cost_usd=0.005,
    cost_cny=0.036,
    latency_ms=1200,
)
```

---

## 🛠️ 自定义模型价格

### 代码方式

```python
from tokenkeeper import register_custom_pricing, ModelPricing

register_custom_pricing(
    "my-local-llama-3-70b",
    ModelPricing(
        input_per_1m=0.0,      # 自托管免费
        output_per_1m=0.0,
        provider="self-hosted",
        notes="本地 Llama 3 70B",
    ),
)
```

### 环境变量方式（无需改代码）

```bash
export TOKENKEEPER_PRICING_OVERRIDE='{"my-llm": {"input_per_1m": 1.0, "output_per_1m": 2.0}}'
```

---

## 📂 数据导出

```python
from tokenkeeper import guard
import time

guard.install()

# 导出最近 7 天为 CSV
guard.ledger().export_csv("./calls.csv", since=time.time() - 7*86400)

# 导出为 JSONL
guard.ledger().export_jsonl("./calls.jsonl", since=time.time() - 7*86400)
```

---

## 📖 API 参考

### `tokenkeeper.guard`（全局单例）

```python
from tokenkeeper import guard

guard.install(
    db_path="./tokenkeeper.db",  # SQLite 文件路径
    project="default",           # 项目标识
    user="default",              # 用户标识
    auto_patch_openai=True,      # 是否自动 patch OpenAI SDK
)

guard.set_budget(
    daily_limit_usd=10.0,        # 每日美元限额
    monthly_limit_usd=200.0,     # 每月美元限额
    per_call_limit_usd=1.0,      # 单次调用美元限额
    action="block",              # "block" | "warn"
    scope="global",              # "global" | "project" | "user"
    scope_key=None,              # scope 非 global 时必填
)

guard.is_installed()             # -> bool
guard.ledger()                   # -> Ledger 实例
guard.guard_instance()           # -> Guard 实例
guard.uninstall()                # 恢复原始 SDK
```

### `BudgetExceededError`

```python
from tokenkeeper import BudgetExceededError

try:
    resp = client.chat.completions.create(...)
except BudgetExceededError as e:
    print(e.scope)        # "global" | "project" | "user"
    print(e.limit_type)   # "daily" | "monthly" | "per_call"
    print(e.current_cost) # 当前已花费
    print(e.limit)        # 限额
```

### `register_custom_pricing()`

```python
from tokenkeeper import register_custom_pricing, ModelPricing

register_custom_pricing(
    "model-id",
    ModelPricing(
        input_per_1m=1.0,       # 输入每百万 token 美元
        output_per_1m=2.0,      # 输出每百万 token 美元
        provider="custom",       # 供应商名
        notes="可选备注",
    ),
)
```

---

## ❓ 常见问题

### Q1：会拖慢我的 LLM 调用吗？
**A**：不会。拦截器只是包一层（<1ms 开销），不修改请求内容。流式调用也是调用完成后记账，不阻塞 streaming。

### Q2：我的 token 数据会泄露吗？
**A**：不会。所有数据存在本地 SQLite（默认 `./tokenkeeper.db`），不连接任何云服务。

### Q3：支持哪些模型？
**A**：43 个内置模型。覆盖 OpenAI、Anthropic、DeepSeek、阿里、智谱、百度、月之暗面、零一万物、minimax。任何 OpenAI 兼容协议的端点都自动工作。

### Q4：怎么区分不同项目/用户的费用？
**A**：`guard.install()` 时设 `project="..."` 和 `user="..."`，看板上按这两个维度筛选。

### Q5：团队能用吗？
**A**：可以。每个人的 guard 指向同一个 SQLite 文件（放共享盘 / S3 / NAS），数据自动合并。

### Q6：patch 失败会怎样？
**A**：tokenkeeper 采用 fail-open 策略。patch 失败时记录错误日志，但原始 SDK 调用不受影响——只是本次调用不计账。

---

## 🛠️ 故障排查

### "Unknown model" 警告
模型不在内置价格表。`cost_usd=0`，但调用正常记账。  
**解决**：用 `register_custom_pricing()` 或环境变量 `TOKENKEEPER_PRICING_OVERRIDE` 补录价格。

### 安装后找不到 `tokenkeeper` 命令
检查 `pip install` 是否成功。`python -m tokenkeeper --help` 应该能跑。

### 看板打不开
默认 8501 端口被占用：`tokenkeeper dashboard --port 8888`。

---

## 👩‍💻 开发

```bash
git clone https://github.com/wzwailr/tokenkeeper.git
cd tokenkeeper
pip install -e ".[all]"

# 运行测试
pytest

# 类型检查
mypy tokenkeeper

# 构建
python -m build --wheel
```

### 架构

```
tokenkeeper/
├── core.py          # GuardAPI 单例，install / uninstall / record / set_budget
├── guard.py         # Guard 预算检查逻辑
├── ledger.py        # Ledger SQLite 读写
├── pricing.py       # 模型价格查找
├── pricing_data.py  # 43 个模型内置价格表
├── cli.py           # 命令行入口
└── integrations/
    ├── openai_compat.py   # OpenAI SDK patch（兼容所有 OpenAI-like 端点）
    └── anthropic.py       # Anthropic SDK patch
```

---

## 📜 License

MIT © tokenkeeper contributors
