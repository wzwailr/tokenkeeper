# tokenkeeper — 用户上手指南

> **5 分钟让你的 AI 应用有"成本可见 + 超预算自动停"**

---

## 🎯 它解决什么问题

- ❌ 不知道 AI 调用花了多少钱
- ❌ Agent 失控循环一下烧了几百美元
- ❌ 团队预算没法分摊、没法预警

---

## 🚀 30 秒接入（4 步）

### 第 1 步：装包

```bash
pip install tokenkeeper[all]
# 或从源码：
# git clone https://github.com/yourname/tokenkeeper.git
# cd tokenkeeper && pip install -e ".[all]"
```

### 第 2 步：写 4 行代码（在你的 AI 应用入口）

```python
from tokenkeeper import guard

guard.install(project="my-ai-app")
guard.set_budget(daily_limit_usd=10.0, action="block")  # 超日预算 $10 报错
```

### 第 3 步：**业务代码 0 改动**

```python
import openai

client = openai.OpenAI()  # 你的原有代码
resp = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
)
# ↑ 这一行就被自动记账 + 限额检查
```

### 第 4 步：启动看板（另一终端）

```bash
tokenkeeper dashboard
# 打开 http://localhost:8501
```

**就这么多。**

---

## 🇨🇳 用国产模型（OpenAI 兼容协议）

任何 OpenAI 兼容服务都自动支持——**只需改 `base_url`**：

```python
# DeepSeek
client = openai.OpenAI(
    api_key="sk-***",
    base_url="https://api.deepseek.com/v1",
)

# 阿里通义千问（DashScope 兼容模式）
client = openai.OpenAI(
    api_key="sk-***",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# 月之暗面 Kimi
client = openai.OpenAI(
    api_key="sk-***",
    base_url="https://api.moonshot.cn/v1",
)

# minimax（minimax M3、M2.7 等）
client = openai.OpenAI(
    api_key="sk-cp-***",
    base_url="https://api.minimaxi.com/v1",
)
```

**内置价格表已覆盖** OpenAI / Anthropic / DeepSeek / 阿里 / 智谱 / 百度 / 月之暗面 / 零一万物 / **minimax** 共 43 个模型。

---

## 🛡️ 预算管理

### 三种粒度

```python
# 全局预算
guard.set_budget(
    daily_limit_usd=10.0,
    monthly_limit_usd=200.0,
    per_call_limit_usd=1.0,
    action="block",  # 超限 block；或 "warn" 只警告
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

- `action="warn"` — 超限只记日志，调用继续
- `action="block"` — 超限抛 `BudgetExceededError`

```python
from tokenkeeper import BudgetExceededError

try:
    response = client.chat.completions.create(...)
except BudgetExceededError as e:
    print(f"预算超限: {e}")
    # 降级到更便宜的模型、暂停、通知用户
```

---

## 📊 看板（Streamlit）

启动后访问 `http://localhost:8501`：

- 💰 **KPI 卡片**：总成本、调用次数、平均成本、错误率
- 📈 **每日趋势**：折线图
- 🏆 **Top 烧钱模型**：按模型汇总
- 💰 **预算状态**：今日已花费
- 📋 **最近调用**：可筛选、可导出 CSV

---

## 🔌 命令行

```bash
tokenkeeper version          # 显示版本
tokenkeeper info             # 显示运行时信息（已加载模型数、价格表日期）
tokenkeeper dashboard        # 启动看板（默认 8501）
tokenkeeper dashboard --port 8888 --db /path/to/db.sqlite
```

---

## 🧪 直接用 SDK（不自动拦截）

如果你不用 OpenAI 兼容协议，可以**手动记账**：

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

**代码方式**：

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

**环境变量方式**（无需改代码）：

```bash
export TOKENKEEPER_PRICING_OVERRIDE='{"my-llm": {"input_per_1m": 1.0, "output_per_1m": 2.0}}'
```

---

## 📂 数据导出

```python
from tokenkeeper import guard

guard.install()

# 导出最近 7 天为 CSV
guard.ledger().export_csv("./calls.csv", since=time.time() - 7*86400)
guard.ledger().export_jsonl("./calls.jsonl", since=time.time() - 7*86400)
```

---

## ❓ 常见问题

### Q1：会拖慢我的 LLM 调用吗？
**A**：不会。拦截器只是**包一层**（<1ms 开销），不修改请求内容。

### Q2：我的 token 数据会泄露吗？
**A**：不会。所有数据**存在本地 SQLite**（默认 `./tokenkeeper.db`），**不连任何云**。

### Q3：支持哪些模型？
**A**：43 个内置模型。覆盖 OpenAI、Anthropic、DeepSeek、阿里、智谱、百度、月之暗面、零一万物、minimax。**任何 OpenAI 兼容协议都自动工作**。

### Q4：怎么知道是哪个项目/用户烧的钱？
**A**：guard.install 时设 `project="..."` 和 `user="..."`，看板上能按这两个维度筛选。

### Q5：能用在团队吗？
**A**：可以。每个人的 guard 指向**同一个 SQLite 文件**（放在共享盘 / S3 / NAS），数据自动合并。

---

## 🛠️ 故障排查

### "Unknown model" 警告
模型没在内置价格表里。`cost_usd = 0`，但调用正常记账。

**解决**：`register_custom_pricing()` 或环境变量 `TOKENKEEPER_PRICING_OVERRIDE`。

### 安装后找不到 `tokenkeeper` 命令
检查 `pip install` 是否成功，`python -m tokenkeeper --help` 应能跑。

### 看板打不开
默认 8501 端口被占用：`tokenkeeper dashboard --port 8888`。

---

## 📜 License

MIT